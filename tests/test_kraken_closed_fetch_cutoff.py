"""Vertical tracer: the real default Kraken fetch must cache only closed bars.

This file is the RED-first tracer for issue #197. It calls the production
`fetch_kraken_ohlc` exactly as the CLI does - no `now_ms`, no injected clock
argument - and injects only the TLS boundary (`krellbot.tls.urlopen`), which is
the single place the HTTP request leaves the process. Fetch, parser, the closed
predicate, the 720-row tail and `write_cache`/`read_cache` are all real code.

Contract under test: `fetch_kraken_ohlc` applies the established inclusive
closed predicate (`drop_forming`: `ts_ms + tf_ms <= now_ms`) at one fetch
cutoff taken from the wall clock, and it filters before the 720-row tail and
before anything is cached. The parser keeps its own no-cutoff contract; this
tracer never imports or calls `parse_kraken_ohlc` and never mocks a fetch,
parse or cache outcome.

Clock: the production fetch must read wall-clock time through `time.time()` /
`time.time_ns()` (the repo's `_now_seconds` / `_default_now` helper style), so
freezing those stdlib functions pins the cutoff deterministically. The payload
timestamps sit in the past relative to real "now" on purpose: an implementation
that ignores the injected clock caches the forming bar and fails here.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import tls
from krellbot.data import cache_path, fetch_kraken_ohlc, kraken_public, read_cache, write_cache

PAIR = "SUIUSD"
# Kraken's internal pair name differs from the requested altname.
PAIR_KEY = "XSUIZUSD"
TF = "1h"
TF_MS = 3_600_000
# Fixed synthetic hourly-aligned epoch; these fixtures are not market data.
BASE_S = 1_699_999_200
BASE_MS = BASE_S * 1000


def _row(index: int, close: str = "0.42190000") -> list:
    """One genuine 8-field Kraken OHLC row: time, o, h, l, c, vwap, volume, count."""
    ts_s = BASE_S + index * (TF_MS // 1000)
    return [
        ts_s,
        "0.41230000",
        "0.42500000",
        "0.40100000",
        close,
        "0.41800000",
        "12345.67890000",
        42 + index,
    ]


def _payload(rows: list[list]) -> dict:
    """A real `/0/public/OHLC` body: `error` list plus one array-valued pair key."""
    return {
        "error": [],
        "result": {
            PAIR_KEY: rows,
            # Kraken's `last` is an id in the array-of-arrays format, not a bar.
            "last": rows[-1][0] if rows else 0,
        },
    }


class _Response:
    """Minimal `http.client.HTTPResponse` stand-in returned by the TLS seam."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, now_ms: int) -> None:
    """Pin the one cutoff `fetch_kraken_ohlc` is allowed to use.

    Freeze stdlib clocks, not the fetch, parser or their private return values.
    """
    monkeypatch.setattr(time, "time", lambda: now_ms / 1000.0)
    monkeypatch.setattr(time, "time_ns", lambda: now_ms * 1_000_000)


def test_default_fetch_caches_only_inclusive_closed_bars(monkeypatch, tmp_path):
    calls: list[tuple[str, float, dict[str, str]]] = []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout, {k.lower(): v for k, v in req.header_items()}))
        return _Response(json.dumps(_payload([_row(0), _row(1), _row(2)])).encode("utf-8"))

    # No real network anywhere: the TLS seam answers, every deeper HTTP entry
    # point refuses. `krellbot.tls.urlopen` is imported inside the fetch, so
    # patching the module attribute is the live seam.
    monkeypatch.setattr(tls, "urlopen", fake_urlopen)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("real HTTP"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("real socket"))

    # Row 0 closes exactly at the frozen cutoff -> inclusive, must stay.
    # Row 1 is forming, row 2 is future -> both must be absent.
    _freeze_clock(monkeypatch, BASE_MS + TF_MS)

    candles = fetch_kraken_ohlc(PAIR, TF)

    assert calls == [
        ("https://api.kraken.com/0/public/OHLC?pair=SUIUSD&interval=60", 20, {"user-agent": "krellbot/0.1"})
    ], "the default fetch must issue one Kraken OHLC request for the requested pair/interval"

    assert [c.ts_ms for c in candles] == [BASE_MS], (
        "exactly the bar closing at the cutoff must survive; the forming and future bars must not"
    )
    assert candles[0].close == Decimal("0.42190000")
    assert candles[0].volume == Decimal("12345.67890000")

    # Filtering happens before the cache: the bytes a consumer reads hold no
    # forming bar, and the manifest counts only the closed bar.
    home = tmp_path / "home"
    write_cache(home, "kraken", PAIR, TF, candles)
    cached = read_cache(home, "kraken", PAIR, TF)
    assert cached is not None
    cached_candles, digest = cached
    assert [c.ts_ms for c in cached_candles] == [BASE_MS]
    manifest = json.loads(cache_path(home, "kraken", PAIR, TF).with_suffix(".manifest.json").read_text("utf-8"))
    assert manifest["rows"] == 1
    assert len(digest) == 64

    # Tail order: 721 closed bars plus one forming bar can only become 720
    # closed candles when the cutoff runs BEFORE the `[-OHLC_CAP:]` slice.
    # Slicing first would drop the oldest closed bar and cache 719.
    calls.clear()

    def fake_urlopen_many(req, timeout):
        calls.append((req.full_url, timeout, {}))
        return _Response(json.dumps(_payload([_row(i) for i in range(722)])).encode("utf-8"))

    monkeypatch.setattr(tls, "urlopen", fake_urlopen_many)
    _freeze_clock(monkeypatch, BASE_MS + 721 * TF_MS)

    tail = fetch_kraken_ohlc(PAIR, TF)

    assert len(calls) == 1
    assert len(tail) == 720, "the closed-only fetch must still honour the 720-row cap"
    assert tail[0].ts_ms == BASE_MS + TF_MS, "filter-then-cap keeps the newest 720 closed bars"
    assert tail[-1].ts_ms == BASE_MS + 720 * TF_MS


_INTERVALS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _rows_for(tf, count):
    seconds = _INTERVALS[tf] // 1000
    anchor = BASE_S // seconds * seconds
    rows = [_row(i) for i in range(count)]
    for i, row in enumerate(rows):
        row[0] = anchor + i * seconds
    return anchor * 1000, rows


def _tls_fixture(monkeypatch, payload):
    calls = []

    def response(req, timeout, context):
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
        calls.append((req.full_url, timeout, context.verify_mode, context.check_hostname))
        return _Response(json.dumps(payload).encode("utf-8"))

    # Retain the real product TLS wrapper and inspect its verifying context.
    monkeypatch.setattr(urllib.request, "urlopen", response)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("real socket"))
    return calls


@pytest.mark.parametrize("tf", _INTERVALS)
@pytest.mark.parametrize("offset,expected_count", [(-1, 0), (0, 1), (1, 1)])
def test_default_cutoff_boundary_across_timeframes(monkeypatch, tf, offset, expected_count):
    anchor, rows = _rows_for(tf, 3)
    calls = _tls_fixture(monkeypatch, _payload([rows[2], rows[0], rows[1]]))
    _freeze_clock(monkeypatch, anchor + _INTERVALS[tf] + offset)
    result = fetch_kraken_ohlc(PAIR, tf)
    assert [c.ts_ms for c in result] == ([anchor] if expected_count else [])
    assert len(calls) == 1 and calls[0][1] == 20
    assert f"interval={_INTERVALS[tf] // 60_000}" in calls[0][0]
    assert "pair=SUIUSD" in calls[0][0]


@pytest.mark.parametrize("tf", _INTERVALS)
def test_closed_filter_precedes_tail_and_preserves_decimal_cache(monkeypatch, tmp_path, tf):
    anchor, rows = _rows_for(tf, 722)
    _tls_fixture(monkeypatch, _payload(list(reversed(rows))))
    _freeze_clock(monkeypatch, anchor + 721 * _INTERVALS[tf])
    result = fetch_kraken_ohlc(PAIR, tf)
    assert len(result) == 720
    assert [c.ts_ms for c in result] == [anchor + i * _INTERVALS[tf] for i in range(1, 721)]
    assert all(c.close == Decimal("0.42190000") and c.volume == Decimal("12345.67890000") for c in result)
    _, digest = write_cache(tmp_path, "kraken", PAIR, tf, result)
    cached = read_cache(tmp_path, "kraken", PAIR, tf)
    assert cached is not None
    loaded, stored_digest = cached
    assert stored_digest == digest
    assert loaded == result


@pytest.mark.parametrize("tf", _INTERVALS)
def test_all_closed_retains_latest_and_parser_without_cutoff_stays_unfiltered(monkeypatch, tf):
    anchor, rows = _rows_for(tf, 3)
    payload = _payload(list(reversed(rows)))
    _tls_fixture(monkeypatch, payload)
    _freeze_clock(monkeypatch, anchor + 3 * _INTERVALS[tf])
    assert len(fetch_kraken_ohlc(PAIR, tf)) == 3
    _freeze_clock(monkeypatch, anchor)
    assert [c.ts_ms for c in kraken_public.parse_kraken_ohlc(payload, PAIR, tf=tf)] == [
        anchor + i * _INTERVALS[tf] for i in range(3)
    ]


def test_one_request_start_cutoff_does_not_advance_during_response(monkeypatch):
    anchor, rows = _rows_for("1h", 3)
    state = {"now": anchor + TF_MS, "clock_reads": 0, "advanced": False}
    events = []

    def now():
        state["clock_reads"] += 1
        events.append("clock")
        return state["now"] * 1_000_000

    class SlowResponse(_Response):
        def read(self):
            state["now"] += 2 * TF_MS
            state["advanced"] = True
            events.append("read")
            return super().read()

    def response(req, timeout, context):
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        events.append("request")
        return SlowResponse(json.dumps(_payload(rows)).encode())

    monkeypatch.setattr(time, "time_ns", now)
    monkeypatch.setattr(urllib.request, "urlopen", response)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("real socket"))
    result = fetch_kraken_ohlc(PAIR, "1h")
    assert state["advanced"] is True  # delayed response adversary actually fired
    assert state["clock_reads"] == 1
    assert events == ["clock", "request", "read"]
    assert [c.ts_ms for c in result] == [anchor]


@pytest.mark.parametrize(
    "payload,error",
    [
        ({}, TypeError),
        ({"result": []}, TypeError),
        ({"result": {"last": 1}}, ValueError),
        (_payload([[1, "bad-width"]]), ValueError),
    ],
)
def test_existing_response_validation_is_preserved(monkeypatch, payload, error):
    _tls_fixture(monkeypatch, payload)
    _freeze_clock(monkeypatch, BASE_MS + TF_MS)
    with pytest.raises(error):
        fetch_kraken_ohlc(PAIR, "1h")


def test_empty_response_and_unsupported_timeframe_keep_behavior(monkeypatch):
    calls = _tls_fixture(monkeypatch, _payload([]))
    _freeze_clock(monkeypatch, BASE_MS)
    assert fetch_kraken_ohlc(PAIR, "1h") == []
    with pytest.raises(ValueError, match="unsupported timeframe"):
        fetch_kraken_ohlc(PAIR, "5m")
    assert len(calls) == 1


_SITE_FIXTURE = """import json, os, socket, ssl, time, urllib.request
def deny(*a, **k):
    raise RuntimeError("offline fixture refuses network")
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
urllib.request.urlopen = deny
try:
    body = open(os.environ["PROBE_PAYLOAD"], "rb").read()
    now = int(os.environ["PROBE_CUTOFF_MS"])
    time.time = lambda: now / 1000
    time.time_ns = lambda: now * 1000000
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return body
    def response(req, timeout, context):
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        assert req.full_url.startswith("https://api.kraken.com/0/public/OHLC?")
        with open(os.environ["PROBE_CALLS"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"url": req.full_url, "timeout": timeout, "verify": True}) + "\\n")
        return Response()
    urllib.request.urlopen = response
except BaseException:
    os._exit(97)
"""


@pytest.mark.parametrize("tf", _INTERVALS)
def test_fresh_cli_default_fetch_writes_closed_cache_then_reuses_it(tmp_path, tf):
    root = tmp_path / "cli"
    root.mkdir()
    for name in ("home", "app", "tmp", "cwd", "shim"):
        (root / name).mkdir()
    compile(_SITE_FIXTURE, "sitecustomize.py", "exec")
    (root / "shim/sitecustomize.py").write_text(_SITE_FIXTURE, encoding="utf-8")
    anchor, rows = _rows_for(tf, 17)
    payload = root / "synthetic-response.json"
    payload.write_text(json.dumps(_payload(rows)), encoding="utf-8")
    pack = {
        "schema_version": 1,
        "id": "closed-fetch-synthetic",
        "version": "1.0.0",
        "label": "Synthetic closed-candle CLI",
        "author": "tests",
        "origin": "Synthetic, not market data",
        "timeframe": tf,
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", ">", "sma2"],
        "exit": ["close", "<", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": PAIR}],
    }
    pack_path = root / "pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    calls = root / "calls.jsonl"
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}
    }
    env.update(
        HOME=str(root / "home"),
        USERPROFILE=str(root / "home"),
        KRELLBOT_HOME=str(root / "app"),
        TMPDIR=str(root / "tmp"),
        TEMP=str(root / "tmp"),
        TMP=str(root / "tmp"),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(root / "shim"),
        PROBE_PAYLOAD=str(payload),
        PROBE_CUTOFF_MS=str(anchor + 16 * _INTERVALS[tf]),
        PROBE_CALLS=str(calls),
    )
    console = Path(sys.executable).parent / ("krellbot.exe" if os.name == "nt" else "krellbot")
    assert console.is_file()
    command = [str(console), "backtest", str(pack_path), "--venue", "kraken", "--json"]
    csv_path = cache_path(root / "app", "kraken", PAIR, tf)
    assert not csv_path.exists()  # no --data and no seeded cache
    first = subprocess.run(command, cwd=root / "cwd", env=env, capture_output=True, text=True, timeout=40, check=False)
    assert first.returncode == 0, first.stderr
    assert f"fetched 16 {tf} candles" in first.stderr
    receipt = json.loads(first.stdout)
    stored = read_cache(root / "app", "kraken", PAIR, tf)
    assert stored is not None
    cached, digest = stored
    assert [c.ts_ms for c in cached] == [anchor + i * _INTERVALS[tf] for i in range(16)]
    assert receipt["data_manifest_sha256"] == digest == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert json.loads(csv_path.with_suffix(".manifest.json").read_text())["rows"] == 16
    assert len(calls.read_text().splitlines()) == 1
    second = subprocess.run(command, cwd=root / "cwd", env=env, capture_output=True, text=True, timeout=40, check=False)
    assert second.returncode == 0, second.stderr
    assert "fetched" not in second.stderr
    assert second.stdout == first.stdout
    assert len(calls.read_text().splitlines()) == 1

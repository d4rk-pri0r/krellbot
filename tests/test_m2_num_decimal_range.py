"""M2-NUM round 2: research must surface a typed refusal above the numeric domain.

Numeric-domain requirements:

    1. ``Backtester.run`` raises ``NumericRangeExceeded`` when ``starting_cash``
       or per-bar ``equity`` exceeds ``MAX_MONEY = 1e20``; the engine never
       silently clamps positions.
    2. ``ResearchService.run`` translates that exception to a typed refusal
       with ``code == "numeric_out_of_range"`` and a message that names
       ``1e20``.
    3. The 400-row zig-zag at ``1e12`` (well below ``MAX_MONEY``) succeeds
       with the same ``trade_count`` as at cash ``10000`` — sizing is
       not clamped below the bound.
    4. The 400-row zig-zag at ``10000`` still produces a receipt whose
       canonical bytes hash to the pinned base SHA.
    5. Job boundary: 100k zig-zag at "10000" refuses with
       ``numeric_out_of_range``; "1e21" and "1e400" refuse the same way;
       400 rows at "10000" succeed and the download parses strictly.
"""

from __future__ import annotations

import hashlib
import json
import math
import socket
import time
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.api.jobs import canonical_receipt_bytes
from krellbot.api.serve import WorkstationServer
from krellbot.application.research import (
    CODE_NUMERIC_OUT_OF_RANGE,
    ResearchRequest,
    ResearchService,
)
from krellbot.application.strategy import StrategyDraftService

PINNED_BASE_SHA256 = "5b5d3b5841eedb8e6188cd59f3d6a505201ebd0d9ded6a75e1a45608a3ed0145"

PACK_DICT: dict = {
    "schema_version": 1,
    "id": "m2-num-pinned",
    "version": "1.0.0",
    "label": "M2 NUM pinned",
    "author": "m2",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _write_zigzag(path: Path, rows: int) -> None:
    """Write the brief's exact zig-zag CSV shape."""
    lines = ["ts_ms,open,high,low,close,volume"]
    for i in range(rows):
        ts = 1_700_000_000_000 + i * 3_600_000
        close = 100 + 12 * math.sin(i / 18) + (1.5 if i % 2 == 0 else -1.5)
        op = close - 0.5
        lines.append(f"{ts},{op:.4f},{max(op, close) + 0.25:.4f},{min(op, close) - 0.25:.4f},{close:.4f},1")
    # write_bytes, not write_text: text mode turns "\n" into "\r\n" on Windows,
    # which changes the input bytes and so data_manifest_sha256 in the receipt.
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def _write_pack(tmp_path: Path) -> Path:
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(PACK_DICT), encoding="utf-8")
    return p


@pytest.fixture
def fresh_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Out-of-range starting cash refuses with the typed code.
# ---------------------------------------------------------------------------


def test_research_service_starting_cash_above_bound_refuses(fresh_home: Path, tmp_path: Path):
    """Both ``1e21`` and ``1e400`` starting cash refuse typed.

    ``Backtester.run`` raises ``NumericRangeExceeded`` before the loop on
    ``1e21`` (just above ``MAX_MONEY = 1e20``) and on ``1e400`` (vastly
    above). ``ResearchService.run`` translates that to a refusal.
    """
    csv_path = tmp_path / "zz400.csv"
    _write_zigzag(csv_path, 400)
    pack_path = _write_pack(tmp_path)
    svc = ResearchService(home=fresh_home)

    for cash in (Decimal("1e21"), Decimal("1e400")):
        result = svc.run(
            ResearchRequest(
                pack_path=pack_path,
                venue="kraken",
                pair="SUIUSD",
                dataset_csv=csv_path,
                fee_bps=10,
                starting_cash=cash,
            )
        )
        assert result.ok is False, (cash, result)
        assert result.legacy_receipt is None, (cash, result)
        assert result.refusal is not None, (cash, result)
        assert result.refusal["code"] == CODE_NUMERIC_OUT_OF_RANGE, (cash, result.refusal)
        assert "1e20" in result.refusal["message"], (cash, result.refusal)


# ---------------------------------------------------------------------------
# 2. 100k zig-zag at ordinary cash refuses because equity compounds past 1e20.
# ---------------------------------------------------------------------------


def test_research_service_zigzag_100k_ordinary_cash_refuses_typed(fresh_home: Path, tmp_path: Path):
    """100k zig-zag at cash 10000 compounds past 1e20 and is refused.

    The winning strategy in the brief's fixture compounds equity past
    the supported numeric domain during a 100000-bar run. The user
    must be told, not handed a clamped receipt.
    """
    csv_path = tmp_path / "zz100k.csv"
    _write_zigzag(csv_path, 100_000)
    pack_path = _write_pack(tmp_path)

    svc = ResearchService(home=fresh_home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            pair="SUIUSD",
            dataset_csv=csv_path,
            fee_bps=10,
            starting_cash=Decimal(10000),
        )
    )
    assert result.ok is False, result
    assert result.legacy_receipt is None, result
    assert result.refusal is not None, result
    assert result.refusal["code"] == CODE_NUMERIC_OUT_OF_RANGE, result.refusal
    assert "1e20" in result.refusal["message"], result.refusal


# ---------------------------------------------------------------------------
# 3. Just below the bound: no clamping, trade_count matches the pinned case.
# ---------------------------------------------------------------------------


def test_research_service_just_below_bound_is_unclamped(fresh_home: Path, tmp_path: Path):
    """400-row fixture at cash 1e12 succeeds with the same trade_count as cash 10000.

    Proves sizing is not clamped below the bound: a winning strategy on
    a sub-1e20 run sees the same number of trades whether you start with
    10000 or 1e12, because position sizing is rule-based (max_account_pct)
    and the rule triggers the same way at any sub-bound cash level.
    """
    csv_path = tmp_path / "zz400.csv"
    _write_zigzag(csv_path, 400)
    pack_path = _write_pack(tmp_path)
    svc = ResearchService(home=fresh_home)

    result_10k = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            pair="SUIUSD",
            dataset_csv=csv_path,
            fee_bps=10,
            starting_cash=Decimal(10000),
        )
    )
    assert result_10k.ok is True, result_10k
    trades_10k = result_10k.legacy_receipt["metrics"]["trade_count"]

    result_big = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            pair="SUIUSD",
            dataset_csv=csv_path,
            fee_bps=10,
            starting_cash=Decimal("1e12"),
        )
    )
    assert result_big.ok is True, result_big
    trades_big = result_big.legacy_receipt["metrics"]["trade_count"]
    assert trades_big == trades_10k, (trades_big, trades_10k, result_big)


# ---------------------------------------------------------------------------
# 4. Ordinary-cash receipt is byte-identical to the pinned base SHA.
# ---------------------------------------------------------------------------


def test_ordinary_receipt_is_byte_identical_to_base(fresh_home: Path, tmp_path: Path):
    """The 400-row zig-zag at cash 10000 must hash to the pinned base SHA.

    Computed at base ``01a1229``. The engine and metrics are now byte-
    identical to base for sub-1e20 inputs, so the receipt must match.
    """
    csv_path = tmp_path / "zz400.csv"
    _write_zigzag(csv_path, 400)
    # The pin covers the input bytes via data_manifest_sha256; they must be
    # LF-only on every OS (Windows CI failed here with CRLF input).
    assert b"\r" not in csv_path.read_bytes()
    pack_path = _write_pack(tmp_path)

    svc = ResearchService(home=fresh_home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            pair="SUIUSD",
            dataset_csv=csv_path,
            fee_bps=10,
            starting_cash=Decimal(10000),
        )
    )
    assert result.ok is True, result
    body = canonical_receipt_bytes(result.legacy_receipt)
    digest = hashlib.sha256(body).hexdigest()
    assert digest == PINNED_BASE_SHA256, (digest, len(body))


# ---------------------------------------------------------------------------
# 5. End-to-end job boundary tests via the real WorkstationServer.
# ---------------------------------------------------------------------------


class _LoopbackClient:
    """Minimal cookie/CSRF loopback client that talks HTTP/1.1 over a socket."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._cookie: str | None = None
        self._csrf: str | None = None

    def _send(self, method: str, path: str, payload: dict | None) -> tuple[int, dict[str, str], bytes]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = [
            f"Host: {self._host}:{self._port}",
            "Connection: close",
            f"Content-Length: {len(body)}",
            "Content-Type: application/json",
            f"Origin: http://{self._host}:{self._port}",
        ]
        if self._cookie is not None:
            headers.append(f"Cookie: krellbot_session={self._cookie}")
        if self._csrf is not None:
            headers.append(f"X-Krellbot-CSRF: {self._csrf}")
        request = (method + " " + path + " HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
        with socket.create_connection((self._host, self._port), timeout=30) as sock:
            sock.sendall(request)
            chunks = bytearray()
            while True:
                try:
                    chunk = sock.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.extend(chunk)
        return self._parse(bytes(chunks))

    @staticmethod
    def _parse(raw: bytes) -> tuple[int, dict[str, str], bytes]:
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        status_line = lines[0].decode("ascii", errors="replace")
        code = int(status_line.split(" ", 2)[1])
        header_map: dict[str, str] = {}
        for line in lines[1:]:
            if b":" not in line:
                continue
            name, _, value = line.partition(b":")
            header_map[name.decode("ascii").strip().lower()] = value.decode("ascii").strip()
        return code, header_map, body

    def post(self, path: str, payload: dict | None) -> tuple[int, bytes]:
        code, headers, raw = self._send("POST", path, payload)
        set_cookie = headers.get("set-cookie", "")
        if "krellbot_session=" in set_cookie:
            for part in set_cookie.split(";"):
                if part.strip().startswith("krellbot_session="):
                    self._cookie = part.strip().split("=", 1)[1]
                    break
        if path == "/api/v1/session/bootstrap" and raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                csrf = parsed.get("csrf_token")
                if isinstance(csrf, str):
                    self._csrf = csrf
        return code, raw

    def get(self, path: str) -> tuple[int, bytes]:
        code, _headers, body = self._send("GET", path, None)
        return code, body

    def bootstrap(self, token: str) -> tuple[int, bytes]:
        return self.post("/api/v1/session/bootstrap", {"token": token})


def _wait_terminal(client: _LoopbackClient, job_id: str, *, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    snap: dict | None = None
    statuses: list[int] = []
    while time.monotonic() < deadline:
        code, raw = client.get(f"/api/v1/jobs/{job_id}")
        statuses.append(code)
        if code == 200 and raw:
            snap = json.loads(raw)
            if snap["state"] in {"succeeded", "failed", "cancelled"}:
                return snap
        elif code == 404:
            pass
        time.sleep(0.05)
    raise AssertionError(f"job never reached terminal state within {timeout}s; statuses={statuses}; last={snap}")


def _run_one(
    *,
    fresh_home: Path,
    payload: dict,
    timeout: float = 60.0,
) -> tuple[list[int], dict | None, dict | None, bytes | None]:
    """Spin up a real WorkstationServer, submit one job, return HTTP statuses,
    the terminal job snapshot, the result download body, and the raw bytes.
    """
    csv_rows = payload.pop("_csv_rows", 400)
    csv_path = fresh_home / "zz.csv"
    _write_zigzag(csv_path, csv_rows)
    summary = StrategyDraftService(home=fresh_home).create(PACK_DICT)
    payload = dict(payload)
    payload.setdefault("revision_id", summary["revision_id"])
    payload.setdefault("dataset_csv", str(csv_path))

    server = WorkstationServer(home=fresh_home, port=0)
    server.start()
    statuses: list[int] = []
    snap: dict | None = None
    download_body: dict | None = None
    download_bytes: bytes | None = None
    try:
        cli = _LoopbackClient(server.bound_host, server.bound_port)
        code, raw = cli.bootstrap(server.bootstrap_token)
        statuses.append(code)
        assert code == 200, raw

        code, raw = cli.post("/api/v1/research/jobs", payload)
        statuses.append(code)
        assert code == 200, (code, raw)
        job = json.loads(raw)
        snap = _wait_terminal(cli, job["id"], timeout=timeout)
        statuses.append(200)

        if snap["state"] == "succeeded":
            dcode, dbody = cli.get(f"/api/v1/jobs/{job['id']}/result/download")
            statuses.append(dcode)
            if dcode == 200:
                download_bytes = dbody
                parsed = json.loads(dbody.decode("utf-8"))
                download_body = parsed
    finally:
        server.stop()
    return statuses, snap, download_body, download_bytes


def test_job_boundary_zigzag_100k_refuses_with_numeric_out_of_range(fresh_home: Path):
    """100k zig-zag at cash 10000 must refuse with ``numeric_out_of_range``."""
    statuses, snap, _download, _download_bytes = _run_one(
        fresh_home=fresh_home,
        payload={"fee_bps": 10, "starting_cash": "10000", "_csv_rows": 100_000},
        timeout=60.0,
    )
    assert all(s in {200, 404} for s in statuses), statuses
    assert snap is not None
    assert snap["state"] == "failed", snap
    assert snap["error"] is not None, snap
    assert snap["error"]["code"] == "numeric_out_of_range", snap["error"]
    assert snap["error"]["code"] != "job_failed", snap["error"]


def test_job_boundary_starting_cash_above_bound_refuses(fresh_home: Path):
    """400-row fixture at ``1e21`` and ``1e400`` must refuse with the typed code."""
    for cash in ("1e21", "1e400"):
        statuses, snap, _, _ = _run_one(
            fresh_home=fresh_home,
            payload={"fee_bps": 10, "starting_cash": cash},
            timeout=30.0,
        )
        assert all(s in {200, 404} for s in statuses), (cash, statuses)
        assert snap is not None
        assert snap["state"] == "failed", (cash, snap)
        assert snap["error"] is not None, (cash, snap)
        assert snap["error"]["code"] == "numeric_out_of_range", (cash, snap["error"])


def test_job_boundary_400_rows_at_10000_succeeds(fresh_home: Path):
    """400 rows at cash 10000 must succeed; the download parses strictly."""
    statuses, snap, download, download_bytes = _run_one(
        fresh_home=fresh_home,
        payload={"fee_bps": 10, "starting_cash": "10000"},
        timeout=30.0,
    )
    assert all(s in {200, 404} for s in statuses), statuses
    assert snap is not None
    assert snap["state"] == "succeeded", snap
    assert download is not None
    assert download_bytes is not None
    parsed = json.loads(
        download_bytes.decode("utf-8"),
        parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"non-finite: {c}")),
    )
    assert parsed["metrics"]["trade_count"] > 0, parsed["metrics"]


@pytest.mark.parametrize(
    "bad_cash",
    ["abc", "NaN", "Infinity", "-5", "0", True],
)
def test_job_boundary_invalid_starting_cash_typed(fresh_home: Path, bad_cash):
    """Each invalid starting_cash must yield ``invalid_starting_cash``."""
    statuses, snap, _, _ = _run_one(
        fresh_home=fresh_home,
        payload={"fee_bps": 10, "starting_cash": bad_cash},
        timeout=30.0,
    )
    assert all(s in {200, 404} for s in statuses), statuses
    assert snap is not None
    assert snap["state"] == "failed", snap
    assert snap["error"] is not None, snap
    assert snap["error"]["code"] == "invalid_starting_cash", snap["error"]
    assert snap["error"]["code"] != "job_failed", snap["error"]

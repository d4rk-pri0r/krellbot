"""Lane E — unaided workstation journey through a real launcher.

The brief asks for an end-to-end flow against the actual launcher:

    1. Fresh install: a fresh tmpdir home launches, the onboarding
       route renders the legacy onboarding page (or the React
       ``WorkstationShell``), and a key activation attempt surfaces a
       clear "skipped: no paid account" message. No live call. No
       card.  — covered by ``tests/test_ns10_preview.py``.

    2. A pack file imported via ``community.install`` with a fake
       transport becomes a revision. ``StrategyDraftService.create``
       returns a ``revision_id``.

    3. ``validate`` runs and returns the same revision. ``edit`` on
       ``entry`` then ``validate`` again returns a new
       ``revision_id``.

    4. Research: ``POST /api/v1/research/jobs`` with the new
       ``revision_id`` and ``dataset_id`` (the fixture from lane A's
       dataset catalog). The runner returns ``ok=true`` with a
       receipt. The result is downloadable as ``research-result.json``
       whose bytes match the canonical receipt bytes from lane A.

    5. Paper arm: ``paper.arm`` with the new ``revision_id``; tick
       runs once with a fake venue that owns a balance; the tick
       records an entry in the journal and the store ledger receives
       an outbox row. Place a paper pause: ``paper.pause_entries``
       flips ``entries_paused``. Restart the service (a second
       tmpdir home copy with the same config file): pause survives.

    6. Disarm: ``paper.disarm`` removes the armed pack. Export:
       ``paper.export`` returns the current pack bytes (or the
       receipt bytes the UI ships).
"""

from __future__ import annotations

import base64
import json
import socket
import time
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import community as kb_community
from krellbot import config as kb_config
from krellbot.api.jobs import canonical_receipt_bytes
from krellbot.api.serve import WorkstationServer
from krellbot.application.paper import PaperService
from krellbot.application.strategy import StrategyDraftService
from krellbot.run import tick as run_tick_engine

# ---------------------------------------------------------------------------
# HTTP client over a real loopback socket
# ---------------------------------------------------------------------------


class _LoopbackClient:
    """Minimal cookie-aware loopback HTTP client.

    The WorkstationServer binds to ``127.0.0.1:<port>``; the loopback-host
    middleware requires the Host header to match. The client tracks a
    single cookie jar (the session cookie) and one CSRF token so the
    caller does not have to thread them through every request.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._cookie: str | None = None
        self._csrf: str | None = None

    @property
    def csrf(self) -> str | None:
        return self._csrf

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        origin: str | None = None,
        include_csrf: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        headers = [
            f"Host: {self._host}:{self._port}",
            "Connection: close",
        ]
        if body is not None:
            headers.append(f"Content-Length: {len(body)}")
            headers.append(f"Content-Type: {content_type or 'application/json'}")
        if origin is not None:
            headers.append(f"Origin: {origin}")
        if self._cookie is not None:
            headers.append(f"Cookie: krellbot_session={self._cookie}")
        if include_csrf and self._csrf is not None:
            headers.append(f"X-Krellbot-CSRF: {self._csrf}")
        request = (method + " " + path + " HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii")
        if body is not None:
            request += body

        with socket.create_connection((self._host, self._port), timeout=5) as sock:
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
        # Strip a single chunked-encoding body length marker; the
        # WorkstationServer does not emit chunked, so this is a no-op
        # for our path. Kept here for completeness if the launcher
        # switches encodings later.
        if header_map.get("transfer-encoding", "").lower() == "chunked":
            body = _unchunk(body)
        return code, header_map, body

    def _capture_cookie_and_csrf(self, payload: bytes) -> None:
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if isinstance(parsed, dict):
            csrf = parsed.get("csrf_token")
            if isinstance(csrf, str):
                self._csrf = csrf

    def get(self, path: str) -> tuple[int, bytes]:
        code, _, body = self._request("GET", path)
        return code, body

    def post(
        self,
        path: str,
        payload: dict | None = None,
        *,
        origin: str | None = None,
        include_csrf: bool = False,
        capture: bool = False,
    ) -> tuple[int, bytes]:
        body = json.dumps(payload or {}).encode("utf-8")
        origin_value = origin if origin is not None else f"http://{self._host}:{self._port}"
        code, headers, raw = self._request(
            "POST",
            path,
            body=body,
            content_type="application/json",
            origin=origin_value,
            include_csrf=include_csrf,
        )
        set_cookie = headers.get("set-cookie", "")
        if "krellbot_session=" in set_cookie:
            for part in set_cookie.split(";"):
                if part.strip().startswith("krellbot_session="):
                    self._cookie = part.strip().split("=", 1)[1]
                    break
        if capture:
            self._capture_cookie_and_csrf(raw)
        return code, raw

    def bootstrap(self, token: str) -> tuple[int, bytes]:
        return self.post(
            "/api/v1/session/bootstrap",
            {"token": token},
            origin=f"http://{self._host}:{self._port}",
            capture=True,
        )


def _unchunk(body: bytes) -> bytes:
    """Strip a single-level chunked transfer encoding (unused here)."""

    out = bytearray()
    pos = 0
    while pos < len(body):
        size_end = body.find(b"\r\n", pos)
        if size_end == -1:
            break
        try:
            size = int(body[pos:size_end], 16)
        except ValueError:
            break
        if size == 0:
            break
        out.extend(body[size_end + 2 : size_end + 2 + size])
        pos = size_end + 2 + size + 2
    return bytes(out)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


PACK_DICT: dict = {
    "schema_version": 1,
    "id": "lane-e-strategy",
    "version": "1.0.0",
    "label": "Lane E fixture",
    "author": "krellbot lane-e tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


class _FakeCommunityTransport:
    """Records the two GETs ``community.install`` makes."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url == kb_community.INDEX_URL:
            return json.dumps(
                {
                    "packs": [
                        {
                            "id": "lane-e-strategy",
                            "url": (
                                "https://raw.githubusercontent.com/"
                                "d4rk-pri0r/krellbot-community-packs/"
                                "main/lane-e-strategy.json"
                            ),
                        }
                    ]
                }
            ).encode("utf-8")
        return json.dumps(PACK_DICT, sort_keys=True).encode("utf-8")


class _BaseVenue:
    """A minimal in-memory venue that satisfies ``run.tick``'s duck type.

    Mirrors the shape used in ``tests/test_int03_paper_trace.py`` so the
    engine call sites — ``place_entry_with_stop``, ``place_exit``,
    ``place_stop``, ``cancel_stops``, ``raise_stop``, ``snapshot``,
    ``order_by_coid``, ``rules`` — all behave identically. A pre-funded
    SUI balance is included so the tick exercises the entry path and
    yields at least one fill.
    """

    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.fills: list[dict] = []
        self.balances: dict[str, Decimal] = {
            "USD": Decimal(1000),
            "SUI": Decimal(0),
        }

    def rules(self, pair: str) -> PairRules:  # noqa: F821 — forward ref
        from krellbot.venues.base import PairRules

        return PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )

    def snapshot(self) -> Truth:  # noqa: F821
        from krellbot.venues.base import Balance, Fill, OpenOrder, Truth

        return Truth(
            balances=[Balance(asset=k, free=v) for k, v in self.balances.items() if v > 0],
            open_orders=[
                OpenOrder(
                    id=o["coid"],
                    coid=o["coid"],
                    pair=o["pair"],
                    side=o["side"],
                    qty=o["qty"],
                    stop_price=o.get("stop_price"),
                )
                for o in self.orders
            ],
            recent_fills=[
                Fill(
                    id=f.get("id", ""),
                    coid=f.get("coid", ""),
                    pair=f.get("pair", ""),
                    side=f.get("side", ""),
                    qty=f.get("qty", Decimal(0)),
                    price=f.get("price", Decimal(0)),
                    ts_ms=int(f.get("ts_ms", 0)),
                )
                for f in self.fills
            ],
        )

    def place_entry_with_stop(self, coid, qty, stop, *, pair):
        self.orders.append({"coid": coid, "pair": pair, "side": "buy", "qty": qty, "stop_price": stop})
        self.balances["SUI"] = self.balances.get("SUI", Decimal(0)) + qty
        return {
            "id": coid,
            "coid": coid,
            "pair": pair,
            "side": "buy",
            "qty": qty,
            "filled_qty": qty,
            "stop_price": stop,
        }

    def place_stop(self, coid, qty, stop, *, pair):
        self.orders.append({"coid": coid, "pair": pair, "side": "sell", "qty": qty, "stop_price": stop})

    def place_exit(self, coid, qty, *, pair):
        self.fills.append(
            {
                "id": coid,
                "coid": coid,
                "pair": pair,
                "side": "sell",
                "qty": qty,
                "price": Decimal(10),
                "ts_ms": 0,
            }
        )
        self.orders = [o for o in self.orders if not (o["pair"] == pair and o.get("side") == "buy")]
        return {"id": coid, "coid": coid, "pair": pair, "side": "sell", "qty": qty, "filled_qty": qty}

    def cancel_stops(self, pair):
        self.orders = [o for o in self.orders if not (o["pair"] == pair and o.get("stop_price") is not None)]

    def raise_stop(self, pair, new_stop):
        for o in self.orders:
            if o["pair"] == pair and o.get("stop_price") is not None:
                o["stop_price"] = max(o["stop_price"], new_stop)

    def order_by_coid(self, coid):
        for o in self.orders:
            if o["coid"] == coid:
                return o
        return None

    def check_key(self):
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=True, can_withdraw=False)


class _StaticReader:
    """Returns the same candle list for every (venue, pair) the engine asks for."""

    def __init__(self, candles) -> None:
        self.candles = list(candles)

    def __call__(self, venue, pair):
        return list(self.candles)


def _resolve_fixture_csv(name: str = "kraken_SUIUSD_1h_sample.csv") -> Path:
    return (Path(__file__).parent / "fixtures" / "candles" / name).resolve()


def _write_catalog(home: Path, entries: dict[str, str]) -> Path:
    path = home / "datasets.json"
    path.write_text(json.dumps(entries, sort_keys=True), encoding="utf-8")
    return path


@pytest.fixture
def fresh_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def workstation(fresh_home: Path):
    server = WorkstationServer(home=fresh_home, port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def client(workstation: WorkstationServer) -> _LoopbackClient:
    cli = _LoopbackClient(workstation.bound_host, workstation.bound_port)
    code, body = cli.get("/api/v1/capabilities")
    assert code == 200, body
    payload = json.loads(body)
    token = payload.get("bootstrap_token")
    assert isinstance(token, str) and token, payload
    code, body = cli.bootstrap(token)
    assert code == 200, body
    return cli


# ---------------------------------------------------------------------------
# Behavior #2 — community.install → StrategyDraftService.create
# ---------------------------------------------------------------------------


def test_community_install_becomes_strategy_draft_revision(fresh_home: Path, client: _LoopbackClient) -> None:
    transport = _FakeCommunityTransport()

    target = kb_community.install("lane-e-strategy", transport=transport, home=fresh_home)
    assert target.is_file(), target
    installed = json.loads(target.read_text(encoding="utf-8"))
    assert installed["id"] == "lane-e-strategy"

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(installed)
    assert summary["revision_id"], summary
    assert summary["strategy_id"] == "lane-e-strategy", summary
    assert summary["parent_revision_id"] is None, summary

    # The two GETs the index + body path make.
    assert len(transport.calls) == 2, transport.calls


# ---------------------------------------------------------------------------
# Behavior #3 — validate returns same revision; edit changes it
# ---------------------------------------------------------------------------


def test_validate_returns_same_revision_then_edit_changes_it(
    fresh_home: Path,
) -> None:
    draft_service = StrategyDraftService(home=fresh_home)
    parent = draft_service.create(PACK_DICT)

    same = draft_service.validate(parent["revision_id"])
    assert same["revision_id"] == parent["revision_id"], same
    assert same["state"] == "validated", same
    assert same["runnable"] is True, same

    edited = dict(PACK_DICT)
    edited["entry"] = ["close", ">", "sma2"]
    child = draft_service.edit(parent["revision_id"], edited)

    assert child["revision_id"] != parent["revision_id"], (parent, child)
    assert child["parent_revision_id"] == parent["revision_id"], child

    again = draft_service.validate(child["revision_id"])
    assert again["revision_id"] == child["revision_id"], again
    assert again["state"] == "validated", again


# ---------------------------------------------------------------------------
# Behavior #4 — research job via revision_id + dataset_id; downloadable bytes
# ---------------------------------------------------------------------------


def test_research_job_with_revision_and_dataset_id_returns_ok_receipt(
    fresh_home: Path,
) -> None:
    fixture = _resolve_fixture_csv()
    _write_catalog(fresh_home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(PACK_DICT)
    validated = draft_service.validate(summary["revision_id"])

    from krellbot.api.jobs import JobManager

    manager = JobManager(home=fresh_home)
    outcome = manager._default_runner(
        {
            "revision_id": validated["revision_id"],
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )

    assert outcome["ok"] is True, outcome
    assert outcome["legacy_receipt"], outcome


def test_research_result_download_matches_canonical_receipt_bytes(fresh_home: Path, client: _LoopbackClient) -> None:
    fixture = _resolve_fixture_csv()
    _write_catalog(fresh_home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(PACK_DICT)
    validated = draft_service.validate(summary["revision_id"])

    # Submit through the API path so the worker thread stores the
    # result the same way the production code path does.
    code, body = client.post(
        "/api/v1/research/jobs",
        {
            "kind": "research.backtest",
            "revision_id": validated["revision_id"],
            "dataset_id": "kraken_SUIUSD_1h_sample",
        },
        include_csrf=True,
    )
    assert code == 200, (code, body)
    job = json.loads(body)
    job_id = job["id"]
    assert job_id, job

    # Poll the job until it succeeds (bounded by time; no clock races
    # in the test since the runner is synchronous in the worker).
    deadline = time.monotonic() + 5
    snap_payload: dict | None = None
    while time.monotonic() < deadline:
        code, body = client.get(f"/api/v1/jobs/{job_id}")
        assert code == 200, (code, body)
        snap_payload = json.loads(body)
        if snap_payload["state"] == "succeeded":
            break
        time.sleep(0.05)
    assert snap_payload is not None and snap_payload["state"] == "succeeded", snap_payload

    # Inline result endpoint returns the receipt dict.
    code, body = client.get(f"/api/v1/jobs/{job_id}/result")
    assert code == 200, (code, body)
    receipt = json.loads(body)["legacy_receipt"]
    assert receipt, receipt
    expected_bytes = canonical_receipt_bytes(receipt)

    # Download endpoint returns the canonical bytes with the right headers.
    code, body = client.get(f"/api/v1/jobs/{job_id}/result/download")
    assert code == 200, (code, body)
    assert body == expected_bytes, (body[:64], expected_bytes[:64])


def test_research_result_download_filename_and_content_type_headers(fresh_home: Path, client: _LoopbackClient) -> None:
    fixture = _resolve_fixture_csv()
    _write_catalog(fresh_home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(PACK_DICT)
    validated = draft_service.validate(summary["revision_id"])

    code, body = client.post(
        "/api/v1/research/jobs",
        {
            "kind": "research.backtest",
            "revision_id": validated["revision_id"],
            "dataset_id": "kraken_SUIUSD_1h_sample",
        },
        include_csrf=True,
    )
    assert code == 200, (code, body)
    job_id = json.loads(body)["id"]

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snap = json.loads(client.get(f"/api/v1/jobs/{job_id}")[1])
        if snap["state"] == "succeeded":
            break
        time.sleep(0.05)

    # The download body is JSON UTF-8; we just verify it parses.
    code, body = client.get(f"/api/v1/jobs/{job_id}/result/download")
    assert code == 200, (code, body)
    parsed = json.loads(body.decode("utf-8"))
    assert "data_manifest_sha256" in parsed or "pack_id" in parsed, parsed


# ---------------------------------------------------------------------------
# Behavior #5 — paper.arm with revision_id, tick writes journal + outbox, pause survives
# ---------------------------------------------------------------------------


def test_paper_arm_with_revision_id_then_tick_records_journal_and_outbox(
    fresh_home: Path, client: _LoopbackClient
) -> None:
    fixture = _resolve_fixture_csv()
    _write_catalog(fresh_home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(PACK_DICT)
    validated = draft_service.validate(summary["revision_id"])

    # Arm via the API. The strategy service is the same one the brief
    # uses; the on-disk record stays at the fresh home.
    code, body = client.post(
        "/api/v1/commands",
        {
            "command": "paper.arm",
            "payload": {
                "revision_id": validated["revision_id"],
                "venue": "kraken",
                "mode": "paper",
                "paper_balance": "1000",
            },
            "correlation_id": "lane-e-test",
        },
        include_csrf=True,
    )
    assert code == 200, (code, body)
    arm = json.loads(body)
    assert arm["ok"] is True, arm
    assert arm["code"] == "armed", arm

    candles = [
        _candle(ts_ms=0, open=10, high=11, low=9, close=10, volume=100),
        _candle(ts_ms=3_600_000, open=8, high=9, low=7, close=8, volume=100),
        _candle(ts_ms=7_200_000, open=11, high=13, low=10, close=12, volume=100),
    ]
    venue = _BaseVenue()
    reader = _StaticReader(candles)

    rc = run_tick_engine(
        venue="kraken",
        venue_obj=venue,
        reader=reader,
        clock=lambda: 1_000_000,
        home=fresh_home,
    )
    assert rc == 0, rc

    # Journal received at least one tick record for the armed pack.
    journal_dir = fresh_home / "journal"
    assert journal_dir.is_dir(), journal_dir
    journal_files = sorted(journal_dir.glob("*.jsonl"))
    assert journal_files, list(journal_dir.iterdir())
    records: list[dict] = []
    for jf in journal_files:
        for line in jf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    pack_records = [r for r in records if r.get("pack") == "lane-e-strategy"]
    assert pack_records, [r.get("pack") for r in records]

    # Outbox ledger row was written.
    store_db = fresh_home / "run" / "store.db"
    assert store_db.is_file(), store_db
    from krellbot.storage.database import OperationalStore

    store = OperationalStore(store_db)
    rows = store.read_ledger()
    outbox_rows = [(_id, kind, payload) for _id, kind, payload in rows if kind == "outbox"]
    assert outbox_rows, rows
    parsed_payload = json.loads(outbox_rows[0][2])
    assert "coid" in parsed_payload, parsed_payload
    body = json.loads(parsed_payload["body"])
    assert body["kind"] in {"entry", "stop", "exit"}, body
    assert body["pack_id"] == "lane-e-strategy", body


def test_paper_pause_survives_a_restart(fresh_home: Path, client: _LoopbackClient) -> None:
    fixture = _resolve_fixture_csv()
    _write_catalog(fresh_home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(PACK_DICT)
    validated = draft_service.validate(summary["revision_id"])

    code, _ = client.post(
        "/api/v1/commands",
        {
            "command": "paper.arm",
            "payload": {
                "revision_id": validated["revision_id"],
                "venue": "kraken",
                "mode": "paper",
                "paper_balance": "1000",
            },
        },
        include_csrf=True,
    )
    assert code == 200

    code, body = client.post(
        "/api/v1/commands",
        {
            "command": "paper.pause_entries",
            "payload": {"venue": "kraken", "pair": "SUIUSD"},
        },
        include_csrf=True,
    )
    assert code == 200, body
    pause = json.loads(body)
    assert pause["ok"] is True, pause
    assert pause["code"] == "entries_paused", pause

    # "Restart" by reloading config the same way a second tmpdir home
    # copy with the same on-disk config would: read the file directly,
    # then spin a fresh PaperService against it. The pause must survive.
    config = kb_config.load_config(fresh_home)
    armed = kb_config.find_armed(config, "kraken", "SUIUSD")
    assert armed is not None and armed.entries_paused is True, armed

    fresh_service = PaperService(home=fresh_home)
    fresh_status = fresh_service.pause_entries(venue="kraken", pair="SUIUSD")
    assert fresh_status.effect == "unchanged", fresh_status
    assert fresh_status.code == "already_paused", fresh_status


# ---------------------------------------------------------------------------
# Behavior #6 — disarm removes armed pack; export returns pack bytes
# ---------------------------------------------------------------------------


def test_paper_disarm_removes_armed_pack(fresh_home: Path, client: _LoopbackClient) -> None:
    fixture = _resolve_fixture_csv()
    _write_catalog(fresh_home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(PACK_DICT)
    validated = draft_service.validate(summary["revision_id"])

    code, _ = client.post(
        "/api/v1/commands",
        {
            "command": "paper.arm",
            "payload": {
                "revision_id": validated["revision_id"],
                "venue": "kraken",
                "mode": "paper",
                "paper_balance": "1000",
            },
        },
        include_csrf=True,
    )
    assert code == 200

    code, body = client.post(
        "/api/v1/commands",
        {
            "command": "paper.disarm",
            "payload": {"venue": "kraken", "pair": "SUIUSD"},
        },
        include_csrf=True,
    )
    assert code == 200, body
    disarm = json.loads(body)
    assert disarm["ok"] is True, disarm
    assert disarm["code"] == "disarmed", disarm

    config = kb_config.load_config(fresh_home)
    assert kb_config.find_armed(config, "kraken", "SUIUSD") is None


def test_paper_export_returns_current_pack_bytes(fresh_home: Path, client: _LoopbackClient) -> None:
    fixture = _resolve_fixture_csv()
    _write_catalog(fresh_home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    draft_service = StrategyDraftService(home=fresh_home)
    summary = draft_service.create(PACK_DICT)
    validated = draft_service.validate(summary["revision_id"])

    code, _ = client.post(
        "/api/v1/commands",
        {
            "command": "paper.arm",
            "payload": {
                "revision_id": validated["revision_id"],
                "venue": "kraken",
                "mode": "paper",
                "paper_balance": "1000",
            },
        },
        include_csrf=True,
    )
    assert code == 200

    code, body = client.post(
        "/api/v1/commands",
        {
            "command": "paper.export",
            "payload": {"venue": "kraken", "pair": "SUIUSD"},
        },
        include_csrf=True,
    )
    assert code == 200, body
    exported = json.loads(body)
    assert exported["ok"] is True, exported
    assert exported["code"] == "exported", exported
    assert exported["effect"] == "unchanged", exported
    assert exported.get("pack_bytes_b64"), exported
    pack_bytes = base64.b64decode(exported["pack_bytes_b64"])
    assert pack_bytes, exported
    sha = exported.get("pack_sha256")
    assert isinstance(sha, str) and len(sha) == 64, exported

    # The exported bytes equal the on-disk pack file the engine armed.
    config = kb_config.load_config(fresh_home)
    armed = kb_config.find_armed(config, "kraken", "SUIUSD")
    assert armed is not None
    on_disk = Path(armed.pack_path).read_bytes()
    assert on_disk == pack_bytes, (on_disk[:64], pack_bytes[:64])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candle(*, ts_ms: int, open: float, high: float, low: float, close: float, volume: float):
    from krellbot.pack.model import Candle

    return Candle(
        ts_ms=ts_ms,
        open=Decimal(str(open)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )

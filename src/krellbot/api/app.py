"""Loopback HTTP API factory and routes."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from krellbot import config as kb_config
from krellbot import release_policy
from krellbot.api.jobs import (
    JOB_ERROR_NOT_FOUND,
    JOB_ERROR_RESULT_UNAVAILABLE,
    JOB_KIND_RESEARCH_BACKTEST,
    JobManager,
    QueueFull,
)
from krellbot.api.security import (
    ReconnectOffer,
    generate_csrf_token,
    generate_session_token,
    is_loopback_host,
    is_loopback_origin,
    issue_reconnect_offer,
    reconnect_offer_valid,
    reconnect_redeem_path,
)
from krellbot.api.tailnet import TailnetAccess
from krellbot.application import alerts as alerts_app
from krellbot.application import live_gate
from krellbot.application import operations as operations_view_app
from krellbot.application import packs as app_packs
from krellbot.application.live_preflight import SandboxTransport
from krellbot.application.live_preflight import evaluate as live_preflight_evaluate
from krellbot.application.paper import (
    project_owned_position,
    project_paper_pnl_position_chart,
    project_portfolio_history,
)
from krellbot.application.strategy import (
    DraftNotRunnable,
    RevisionNotFound,
    StrategyDraftService,
    StrategyIdMismatch,
)

SCHEMA_VERSION = "1"
SESSION_COOKIE = "krellbot_session"
CSRF_HEADER = "X-Krellbot-CSRF"


def _now_seconds() -> int:
    return int(time.time())


PAPER_COMMANDS = (
    "paper.arm",
    "paper.disarm",
    "paper.pause_entries",
    "paper.resume_entries",
    "paper.raise_stop",
    "paper.export",
)


@dataclass
class _AppState:
    home: Path
    port: int
    bootstrap_token: str
    bootstrap_used: bool = False
    sessions: dict[str, str] = field(default_factory=dict)
    # At most one outstanding short-lived reconnect offer (second browser).
    reconnect_offer: ReconnectOffer | None = None
    # Tests inject a fake clock; production uses wall time via `_now_seconds`.
    clock: Callable[[], int] | None = None
    jobs: JobManager = field(default=None)  # type: ignore[assignment]
    draft_service: object = field(default=None)  # StrategyDraftService singleton per home
    paper_service: object = field(default=None)  # PaperService singleton per home
    rehearsal_service: object = field(default=None)
    live_transport: object = field(default=None)  # SandboxTransport or test spy for live.preflight
    keys_transport: object = field(default=None)  # injectable venue transport for keys routes
    catalogue_transport: object = field(default=None)  # injectable signed-catalogue fetch
    keys_allow_fake_backend: bool = False  # tests-only FakeKeyring opt-in
    scheduler_supervisor: object = None  # PlatformSupervisor; tests inject FakeSupervisor
    scheduler_write_root: Path | None = None  # defaults to Path.home()
    scheduler_executable: str | None = None  # defaults to sys.executable
    alert_notifier: object = None  # Notifier; tests inject FakeNotifier


def _app_now(s: _AppState) -> int:
    """Return the app clock in unix seconds (injectable for reconnect TTL tests)."""

    if s.clock is not None:
        return int(s.clock())
    return _now_seconds()


def _state(app: FastAPI) -> _AppState:
    return app.state.krellbot


def _draft_service(s: _AppState) -> StrategyDraftService:
    """Lazily build the strategy-draft service bound to the app's home."""

    if s.draft_service is None:
        s.draft_service = StrategyDraftService(home=s.home)
    return s.draft_service


def _paper_service(s: _AppState):
    """Lazily build the paper service bound to the app's home."""

    if s.paper_service is None:
        from krellbot.application.paper import PaperService

        s.paper_service = PaperService(home=s.home)
    return s.paper_service


def _rehearsal_service(s: _AppState):
    if s.rehearsal_service is None:
        from krellbot.application.rehearsal import RehearsalService

        s.rehearsal_service = RehearsalService(home=s.home)
    return s.rehearsal_service


def _rehearsal_wire(body: dict) -> dict:
    """Adapt durable service truth to the existing rehearsalClient contract."""
    # `exited` describes the trading outcome, not a terminal Stop. The
    # existing UI disables Stop for `exited`; expose its true paused control
    # phase so the user can explicitly Stop after the rule closes ownership.
    return {
        **body,
        "position": body["position"]["qty"],
        "status": "paused" if body["status"] == "exited" else body["status"],
        "outcome": "exited" if body["status"] == "exited" else None,
    }


def _live_transport(s: _AppState):
    """Lazily build the sandbox live transport bound to the app's home.

    Tests pre-set ``s.live_transport`` to a spy before issuing a
    ``live.preflight`` command so they can assert that ``send`` was
    never called.
    """

    if s.live_transport is None:
        s.live_transport = SandboxTransport(account="sandbox-default")
    return s.live_transport


def _live_arm_gate_refusal(result: live_gate.LiveGateResult) -> JSONResponse:
    """Honest 403 body for a refused web ``live.arm`` gate check."""
    return JSONResponse(
        {
            "schema_version": SCHEMA_VERSION,
            "code": result.code,
            "ok": False,
            "effect": "refused",
            "message": result.message,
            "detail": result.message,
        },
        status_code=403,
    )


def _live_arm_key_check(s: _AppState) -> Callable[[str], object]:
    """Build a key_check callable that uses the injectable keys transport."""
    from krellbot import secrets as kb_secrets
    from krellbot.cli_keys import _probe

    def key_check(venue_arg: str) -> object:
        try:
            api_key, api_secret = kb_secrets.get(venue_arg)
        except (FileNotFoundError, ValueError, PermissionError):
            return None
        probe = _probe(venue_arg, api_key, api_secret, transport=s.keys_transport)
        return probe.to_key_perms()

    return key_check


def _client_pack_basename(pack_path: str) -> str | None:
    """Return a safe ``*.json`` basename from a client pack_path, or None.

    Uses ``os.path.basename`` so directory components never reach a path
    expression; the name is joined only onto the trusted data home.
    """
    import os.path

    if type(pack_path) is not str or not pack_path:
        return None
    # CodeQL-recognized sanitizer: basename strips directory components.
    name = os.path.basename(pack_path)
    if not name or name in {".", ".."}:
        return None
    if not name.endswith(".json") or name.startswith("."):
        return None
    if os.path.basename(name) != name:
        return None
    return name


def _pair_from_pack_data(pack_data: object, venue: str) -> str | None:
    """Return the market pair for ``venue`` from an in-memory pack object."""
    if type(pack_data) is not dict:
        return None
    markets = pack_data.get("markets") or []
    if type(markets) is not list:
        return None
    for market in markets:
        if type(market) is dict and market.get("venue") == venue:
            pair = market.get("pair")
            if type(pair) is str and pair:
                return pair
    return None


def _scheduler_supervisor(s: _AppState):
    """Return the platform supervisor, creating the production default.

    Tests pre-set ``s.scheduler_supervisor`` to a ``FakeSupervisor`` so
    no ``systemctl`` / ``launchctl`` / ``schtasks`` process is spawned.
    """

    if s.scheduler_supervisor is None:
        from krellbot.service import supervise as kb_supervise

        s.scheduler_supervisor = kb_supervise.platform_supervisor()
    return s.scheduler_supervisor


def _scheduler_write_root(s: _AppState) -> Path:
    """Where unit files are written; defaults to the process user home."""

    if s.scheduler_write_root is None:
        return Path.home()
    return Path(s.scheduler_write_root)


def _scheduler_executable(s: _AppState) -> str:
    """Executable path baked into rendered unit files."""

    if s.scheduler_executable:
        return s.scheduler_executable
    return sys.executable


def _stored_deployment_mode(home: Path) -> str | None:
    """Return the mode of the first armed pack, or None when no record exists.

    Used by ``live.preflight`` to honor the symmetric stored-live
    refusal (``stored_mode_not_sandbox``). The full-mode-only check is
    a deliberate read of the existing config bytes; the helper never
    mutates the config.
    """

    config = kb_config.load_config(home)
    if not config.armed:
        return None
    return config.armed[0].mode


def _resolve_dist_dir(dist_dir: Path | None) -> Path:
    """Resolve the frontend ``dist`` directory.

    Resolution order:

    1. An explicit ``dist_dir`` wins; callers (tests, operators) get
       exactly what they passed.
    2. A frozen process always resolves ``<sys._MEIPASS>/frontend/dist``.
       A missing ``index.html`` stays missing so the static route returns
       ``shell_not_built``. It does not fall back to a checkout, which
       would hide a bundle that omitted the shell.
    3. A non-frozen run returns the checkout ``<repo>/frontend/dist``.
       A missing build is handled by the existing static route. The
       resolver never synthesises HTML.
    """

    if dist_dir is not None:
        return Path(dist_dir)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None) or ""
        return Path(meipass) / "frontend" / "dist"
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / "frontend" / "dist"


def _gate_state_change(request: Request, s: _AppState) -> Response | None:
    """Apply the session-cookie + CSRF + loopback-origin gate for state changes."""

    origin = request.headers.get("origin", "")
    if not is_loopback_origin(origin, port=s.port):
        return JSONResponse({"detail": "origin not loopback"}, status_code=403)

    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return JSONResponse({"detail": "session required"}, status_code=403)
    expected_csrf = s.sessions.get(session_id)
    presented_csrf = request.headers.get(CSRF_HEADER, "")
    if not expected_csrf or not hmac.compare_digest(expected_csrf, presented_csrf):
        return JSONResponse({"detail": "csrf required"}, status_code=403)

    return None


def _gate_get(request: Request, s: _AppState) -> Response | None:
    """Apply the session-cookie + loopback-origin gate for read endpoints.

    The cookie must be a key in ``s.sessions``: presence alone is not
    sufficient. A missing or invented cookie, or one that has been
    revoked (popped from the map) is 403 with body
    ``{"detail": "session required"}``. Browsers do not send ``Origin``
    on same-origin GET, so a missing ``Origin`` with a loopback ``Host``
    is allowed; a present non-loopback ``Origin`` is still 403.

    POST routes use ``_gate_state_change`` instead, which keeps the
    loopback-Origin + cookie-present + CSRF triad unchanged.
    """

    origin = request.headers.get("origin", "")
    if origin and not is_loopback_origin(origin, port=s.port):
        # A missing Origin is accepted (same-origin GETs ship without
        # one). A present non-loopback Origin is the only Origin case
        # we refuse; a present loopback Origin still passes through.
        return JSONResponse({"detail": "origin not loopback"}, status_code=403)
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id or session_id not in s.sessions:
        return JSONResponse({"detail": "session required"}, status_code=403)
    return None


def _paper_details_decimal(value: object) -> str | None:
    """Render a finite Decimal without exponent, padding, or precision loss."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    if number.is_zero():
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _select_armed_for_request(
    config: kb_config.Config,
    request: Request,
) -> tuple[kb_config.ArmedPack | None, int]:
    """Pick the armed record a paper GET should project, with multi-deploy clarity.

    Without ``venue``+``pair`` query params, returns the first armed record
    (legacy single-projection behaviour) together with ``armed_count`` so
    the workstation can say when several deployments are armed. With both
    params, returns that exact record or ``None`` when it is not armed.
    A partial selector (only one of venue/pair) never guesses — returns
    ``None`` with the real count.
    """

    count = len(config.armed)
    if count == 0:
        return None, 0
    venue = (request.query_params.get("venue") or "").strip()
    pair = (request.query_params.get("pair") or "").strip()
    if venue and pair:
        return kb_config.find_armed(config, venue, pair), count
    if venue or pair:
        return None, count
    return config.armed[0], count


def _with_armed_count(body: dict, armed_count: int) -> dict:
    """Attach ``armed_count`` only when more than one pack is armed.

    Single-armed and unarmed closed shapes stay byte-compatible with
    existing clients; multi-deploy clarity appears only when it matters.
    """

    if armed_count > 1:
        body["armed_count"] = armed_count
    return body


# ---- paper history projection (read-only) ---------------------------------

PAPER_HISTORY_MAX_RUNS = 20
PAPER_HISTORY_MAX_FILLS = 50


def _read_journal_records(home: Path) -> list[dict]:
    """Return every valid tick record under ``<home>/journal/*.jsonl``.

    Malformed lines and unreadable files are skipped, never fatal: the
    history view is read-only evidence over an append-only journal, so a
    torn last line must not take the panel down.
    """

    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _tick_refusal_code(record: dict) -> str | None:
    """Return the refusal code a tick record carries, else ``None``.

    Refusal paths in the engine write a literal code: the live gate and
    store refusals carry ``detail.code``, per-pack send refusals carry
    ``detail.intent_refused``, and an instrument-metadata refusal carries
    ``detail.metadata_refusal``. A plain decision ``reason`` is NOT a
    refusal, so it is never reported as one.
    """

    detail = record.get("detail")
    if not isinstance(detail, dict):
        return None
    for key in ("code", "intent_refused", "metadata_refusal"):
        value = detail.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _paper_state_fills(home: Path, venue: str) -> list[dict]:
    """Return the paper state's ``recent_fills`` for ``venue``, with pair.

    The returned items are internal: they keep ``pair`` so the caller can
    bucket them per run. Exposure rule for the wire: only ``coid``,
    ``side`` and ``ts_ms`` survive the projection — fill ``qty``/``price``
    belong to the money plane the brief keeps off the wire, and the state
    file's balances (owned cash) are never read here at all.
    """

    path = Path(home) / "run" / f"paper-{venue}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    fills_raw = raw.get("recent_fills")
    if not isinstance(fills_raw, list):
        return []
    fills: list[dict] = []
    for item in fills_raw:
        if not isinstance(item, dict):
            continue
        pair = item.get("pair")
        if not isinstance(pair, str) or not pair:
            continue
        fills.append(
            {
                "coid": str(item.get("coid", "")),
                "side": str(item.get("side", "")),
                "pair": pair,
                "ts_ms": int(item.get("ts_ms", 0) or 0),
            }
        )
    return fills


def _paper_position_run_id(home: Path, venue: str, pair: str) -> str | None:
    """Return the most recent journal run id for ``(venue, pair)``, or ``None``.

    A run id is the ``"<venue>:<pack>:<pair>"`` triple of the latest tick
    record the journal holds for the pair — the same run identity
    ``_paper_history_view`` keys its runs by. ``None`` means the journal
    has no tick record for the pair: the engine has never evaluated it,
    so the persisted paper state cannot yet carry engine-produced money.
    """

    best: tuple[int, str] | None = None
    for record in _read_journal_records(home):
        if record.get("kind") != "tick":
            continue
        if record.get("venue") != venue:
            continue
        detail = record.get("detail")
        if not isinstance(detail, dict) or detail.get("pair") != pair:
            continue
        pack_id = record.get("pack")
        if not isinstance(pack_id, str) or not pack_id:
            continue
        ts = record.get("ts")
        ts_value = int(ts) if isinstance(ts, (int, float)) else 0
        if best is None or ts_value >= best[0]:
            best = (ts_value, f"{venue}:{pack_id}:{pair}")
    return best[1] if best is not None else None


def _paper_history_view(home: Path) -> dict:
    """Build the closed-shape read-only paper history body.

    A "run" is the journal's evidence for one ``(venue, pack, pair)``
    triple — the identity the tick journal actually records. Runs sort
    most-recent-first and cap at ``PAPER_HISTORY_MAX_RUNS``. ``status``
    is ``"active"`` when the config still arms that triple, else
    ``"closed"``. No cash, quantity, stop, cap, pack path, or pack
    digest is read into or returned by this view.
    """

    home = Path(home)
    runs: dict[tuple[str, str, str], dict] = {}
    for record in _read_journal_records(home):
        if record.get("kind") != "tick":
            continue
        venue = record.get("venue")
        pack_id = record.get("pack")
        if not isinstance(venue, str) or not isinstance(pack_id, str):
            continue
        detail = record.get("detail")
        pair = detail.get("pair") if isinstance(detail, dict) else None
        if not isinstance(pair, str) or not pair:
            continue
        ts = record.get("ts")
        ts_ms = int(ts) * 1000 if isinstance(ts, (int, float)) else 0
        key = (venue, pack_id, pair)
        run = runs.setdefault(
            key,
            {
                "venue": venue,
                "pair": pair,
                "pack_id": pack_id,
                "pack_version": None,
                "first_ts_ms": ts_ms,
                "last_ts_ms": ts_ms,
                "ticks_total": 0,
                "last_refusal_code": None,
                "mode": "paper",
                "status": "closed",
                "summary": "",
                "recent_fills": [],
                "_refusals": [],
            },
        )
        run["first_ts_ms"] = min(run["first_ts_ms"], ts_ms)
        run["last_ts_ms"] = max(run["last_ts_ms"], ts_ms)
        run["ticks_total"] += 1
        refusal = _tick_refusal_code(record)
        if refusal is not None:
            run["_refusals"].append((ts_ms, refusal))

    try:
        config = kb_config.load_config(home)
    except (OSError, ValueError):
        config = None
    if config is not None:
        for armed in config.armed:
            key = (armed.venue, armed.pack_id, armed.pair)
            run = runs.get(key)
            if run is not None:
                run["status"] = "active"
                run["mode"] = armed.mode
                run["pack_version"] = armed.pack_version

    venue_fills: dict[str, list[dict]] = {}
    body_runs: list[dict] = []
    for run in runs.values():
        # Paper fills carry no pack id; the state file is per venue, so
        # bucket the venue's fills by pair and hand this run its bucket.
        if run["venue"] not in venue_fills:
            venue_fills[run["venue"]] = _paper_state_fills(home, run["venue"])
        run_fills = [fill for fill in venue_fills[run["venue"]] if fill["pair"] == run["pair"]]
        refusal_code = None
        if run["_refusals"]:
            refusal_code = max(run["_refusals"], key=lambda item: item[0])[1]
        parts = [
            f"{run['ticks_total']} tick{'s' if run['ticks_total'] != 1 else ''}",
            f"{len(run_fills)} fill{'s' if len(run_fills) != 1 else ''}",
        ]
        if refusal_code is not None:
            parts.append(f"last refusal {refusal_code}")
        else:
            parts.append("no refusal")
        parts.append(run["status"])
        exposed_run: dict = {
            "venue": run["venue"],
            "pair": run["pair"],
            "pack_id": run["pack_id"],
            "first_ts_ms": run["first_ts_ms"],
            "last_ts_ms": run["last_ts_ms"],
            "ticks_total": run["ticks_total"],
            "last_refusal_code": refusal_code,
            "mode": run["mode"],
            "status": run["status"],
            "summary": ", ".join(parts),
            "recent_fills": [
                {
                    "coid": fill["coid"],
                    "side": fill["side"],
                    "ts_ms": fill["ts_ms"],
                }
                for fill in run_fills[-PAPER_HISTORY_MAX_FILLS:]
            ],
        }
        if run["pack_version"]:
            exposed_run["pack_version"] = run["pack_version"]
        body_runs.append(exposed_run)

    body_runs.sort(key=lambda run: run["last_ts_ms"], reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "runs": body_runs[:PAPER_HISTORY_MAX_RUNS],
    }


def _fleet_tick_index(home: Path) -> dict[tuple[str, str, str], dict]:
    """Index the journal's latest tick evidence per ``(venue, pack, pair)``.

    Used by the armed-fleet management view so each armed row can carry
    last-tick time/result without inventing cash, quantity, stop, or cap.
    Malformed journal lines are skipped the same way as paper history.
    """

    ticks: dict[tuple[str, str, str], dict] = {}
    for record in _read_journal_records(home):
        if record.get("kind") != "tick":
            continue
        venue = record.get("venue")
        pack_id = record.get("pack")
        if not isinstance(venue, str) or not isinstance(pack_id, str):
            continue
        detail = record.get("detail")
        pair = detail.get("pair") if isinstance(detail, dict) else None
        if not isinstance(pair, str) or not pair:
            continue
        ts = record.get("ts")
        ts_ms = int(ts) * 1000 if isinstance(ts, (int, float)) else 0
        key = (venue, pack_id, pair)
        entry = ticks.setdefault(
            key,
            {
                "last_tick_ts_ms": ts_ms,
                "ticks_total": 0,
                "_refusals": [],
            },
        )
        entry["last_tick_ts_ms"] = max(entry["last_tick_ts_ms"], ts_ms)
        entry["ticks_total"] += 1
        refusal = _tick_refusal_code(record)
        if refusal is not None:
            entry["_refusals"].append((ts_ms, refusal))
    return ticks


def _fleet_last_tick_result(*, ticks_total: int, last_refusal_code: str | None) -> str:
    """Closed last-tick result sentence for one armed fleet row."""

    parts = [
        f"{ticks_total} tick{'s' if ticks_total != 1 else ''}",
    ]
    if last_refusal_code is not None:
        parts.append(f"last refusal {last_refusal_code}")
    else:
        parts.append("no refusal")
    return ", ".join(parts)


def _fleet_detail_href(*, venue: str, pair: str) -> str:
    """Relative deep link into the Workstation status detail for one market."""

    return "/?" + urlencode({"view": "workstation", "venue": venue, "pair": pair})


def _fleet_armed_view(home: Path) -> dict:
    """Build the closed-shape armed fleet list with last tick time/result.

    Every armed config record becomes one row. Last-tick fields come from
    the journal when evidence exists; an armed market that has never
    ticked reports ``last_tick_ts_ms: null`` and
    ``last_tick_result: "no tick yet"``. ``detail_href`` is the relative
    deep link the workstation uses to open that market's status detail.
    Cash, quantity, stop, cap, and pack path stay off the wire.
    """

    home = Path(home)
    try:
        config = kb_config.load_config(home)
    except (OSError, ValueError):
        return {
            "schema_version": SCHEMA_VERSION,
            "armed": False,
            "deployments": [],
        }

    tick_index = _fleet_tick_index(home) if config.armed else {}
    deployments: list[dict] = []
    for record in config.armed:
        key = (record.venue, record.pack_id, record.pair)
        tick = tick_index.get(key)
        if tick is None:
            last_tick_ts_ms = None
            last_refusal_code = None
            last_tick_result = "no tick yet"
        else:
            last_tick_ts_ms = int(tick["last_tick_ts_ms"])
            last_refusal_code = None
            if tick["_refusals"]:
                last_refusal_code = max(tick["_refusals"], key=lambda item: item[0])[1]
            last_tick_result = _fleet_last_tick_result(
                ticks_total=int(tick["ticks_total"]),
                last_refusal_code=last_refusal_code,
            )
        deployments.append(
            {
                "venue": record.venue,
                "pair": record.pair,
                "mode": record.mode,
                "pack_id": record.pack_id,
                "entries_paused": bool(record.entries_paused),
                "last_tick_ts_ms": last_tick_ts_ms,
                "last_tick_result": last_tick_result,
                "last_refusal_code": last_refusal_code,
                "detail_href": _fleet_detail_href(venue=record.venue, pair=record.pair),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "armed": bool(deployments),
        "deployments": deployments,
    }


def _format_sse(event_id: str, event_name: str, data_payload: dict) -> bytes:
    """Render a single SSE frame. JSON-encode the payload as ``data:``."""

    data = json.dumps(data_payload, sort_keys=True, separators=(",", ":"))
    lines = [
        f"id: {event_id}",
        f"event: {event_name}",
        f"data: {data}",
        "",
        "",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _format_resync_marker(last_event_id: str) -> bytes:
    """Render a ``resync_required`` SSE marker with no body."""

    lines = ["event: resync_required", f"id: {last_event_id}", "data: ", "", ""]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def create_app(
    home: Path,
    *,
    port: int,
    bootstrap_token: str,
    runner: Callable | None = None,
    dist_dir: Path | None = None,
    tailnet_access: TailnetAccess | None = None,
) -> FastAPI:
    state = _AppState(
        home=Path(home),
        port=port,
        bootstrap_token=bootstrap_token,
        jobs=JobManager(home=Path(home), runner=runner),
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        from krellbot.application.rehearsal import DRIVER_CADENCE_SECONDS

        async def drive_rehearsal():
            while True:
                await asyncio.sleep(DRIVER_CADENCE_SECONDS)
                # Deliberately synchronous on the API event loop. Commands,
                # reads and driving cannot interleave inside the engine's
                # scoped environment override; no thread executor is used.
                _rehearsal_service(state).drive()

        task = asyncio.create_task(drive_rehearsal())
        print(
            f"Synthetic rehearsal cadence: one bar every {DRIVER_CADENCE_SECONDS:g}s while running; paused/stopped do not evaluate",
            flush=True,
        )
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="krellbot.api",
        version=SCHEMA_VERSION,
        lifespan=lifespan,
    )
    app.state.krellbot = state

    from krellbot.api import static as _static

    _static.register(
        app,
        _resolve_dist_dir(dist_dir),
        bootstrap_token=lambda: None if state.bootstrap_used or tailnet_access else bootstrap_token,
    )

    @app.middleware("http")
    async def _enforce_loopback_host(request: Request, call_next):
        host = request.headers.get("host", "")
        if not is_loopback_host(host, port=port):
            return JSONResponse({"detail": "loopback only"}, status_code=403)
        return await call_next(request)

    if tailnet_access is not None:
        tailnet_access.install(app, state.sessions, port=port, dist_dir=_resolve_dist_dir(dist_dir))

    @app.post("/api/v1/session/bootstrap")
    async def bootstrap(request: Request) -> Response:
        s = _state(request.app)
        origin = request.headers.get("origin", "")
        if not is_loopback_origin(origin, port=s.port):
            return JSONResponse({"detail": "origin not loopback"}, status_code=403)

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        submitted = payload.get("token", "")
        if not isinstance(submitted, str) or not hmac.compare_digest(submitted, s.bootstrap_token):
            return JSONResponse({"detail": "wrong token"}, status_code=403)
        if s.bootstrap_used:
            return JSONResponse({"detail": "token already redeemed"}, status_code=403)
        s.bootstrap_used = True

        session_id = generate_session_token()
        csrf_token = generate_csrf_token()
        s.sessions[session_id] = csrf_token

        body = {"schema_version": SCHEMA_VERSION, "csrf_token": csrf_token}
        response = JSONResponse(body, status_code=200)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_id,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/api/v1/session/csrf")
    async def session_csrf(request: Request) -> Response:
        """Return the CSRF token for the caller's existing session.

        A page reload loses the module-memory CSRF while the session
        cookie stays valid; this read endpoint lets the reloaded shell
        recover the token. It runs ``_gate_get`` (session membership
        plus the loopback Origin/Host checks), never mints a session,
        and never returns the bootstrap token.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        session_id = request.cookies.get(SESSION_COOKIE)
        csrf_token = s.sessions[session_id]
        return JSONResponse(
            {"schema_version": SCHEMA_VERSION, "csrf_token": csrf_token},
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/v1/session/reconnect/issue")
    async def reconnect_issue(request: Request) -> Response:
        """Issue a short-lived reconnect token for a second browser/profile.

        Local re-pair: an already-authenticated session (cookie + CSRF +
        loopback Origin) mints a one-time token the primary UI (or a
        terminal that holds the same session) can show as text or QR.
        The outstanding offer is replaced on each successful issue.
        Host middleware still refuses non-loopback Host headers.
        """

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        now = _app_now(s)
        offer = issue_reconnect_offer(now=now)
        s.reconnect_offer = offer
        path = reconnect_redeem_path(offer.token)
        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "token": offer.token,
                "expires_at": offer.expires_at,
                "expires_in": max(0, offer.expires_at - now),
                "redeem_path": path,
                "qr_payload": f"http://127.0.0.1:{s.port}{path}",
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/v1/session/reconnect/redeem")
    async def reconnect_redeem(request: Request) -> Response:
        """Redeem a reconnect token into a new authenticated session.

        Same loopback-Origin gate as bootstrap (no prior session required).
        A matching unexpired token is single-use: the offer is cleared
        before the new session cookie is set. Expired, wrong, or already-
        spent tokens are 403. Does not revive the one-time bootstrap
        token and does not weaken Host/Origin/CSRF checks for later
        state changes.
        """

        s = _state(request.app)
        origin = request.headers.get("origin", "")
        if not is_loopback_origin(origin, port=s.port):
            return JSONResponse({"detail": "origin not loopback"}, status_code=403)

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        submitted = payload.get("token", "")
        now = _app_now(s)
        offer = s.reconnect_offer
        if not reconnect_offer_valid(offer, submitted=submitted if isinstance(submitted, str) else "", now=now):
            detail = "token expired" if offer is not None and int(now) >= int(offer.expires_at) else "wrong token"
            # Clear a spent/expired offer so a stale QR cannot be retried
            # after the clock advances past expiry (wrong token leaves a
            # still-valid offer for the rightful redeem).
            if offer is not None and int(now) >= int(offer.expires_at):
                s.reconnect_offer = None
            return JSONResponse({"detail": detail}, status_code=403)

        s.reconnect_offer = None
        session_id = generate_session_token()
        csrf_token = generate_csrf_token()
        s.sessions[session_id] = csrf_token

        body = {"schema_version": SCHEMA_VERSION, "csrf_token": csrf_token}
        response = JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_id,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/api/v1/commands")
    async def commands(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        command = payload.get("command", "")
        inner = payload.get("payload") or {}
        if not isinstance(command, str) or not isinstance(inner, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        correlation_id = payload.get("correlation_id") or ""

        if command.startswith("rehearsal."):
            from krellbot.application.rehearsal import COMMANDS

            if inner.get("mode") == "live" or payload.get("mode") == "live":
                return JSONResponse({"detail": "live orders are disabled"}, status_code=403)
            if command not in COMMANDS:
                return JSONResponse({"detail": f"unknown command {command}"}, status_code=403)
            if inner:
                return JSONResponse({"detail": "invalid body"}, status_code=400)
            result = _rehearsal_service(s).handle(command, inner)
            # Keep the durable service envelope and supply the actual UI
            # client's `status` readback. No synthetic success or fills.
            return JSONResponse({**result, "status": _rehearsal_wire(result["rehearsal"])}, status_code=200)

        if command == "live.preflight":
            # ``live.preflight`` is the single carve-out from the prefix
            # gate: a sandbox-only dry-run against the fake transport
            # that never sends an order. Every other ``live.*`` command
            # still returns 403 below; the ``mode == "live"`` payload
            # refusal remains in force for non-preflight commands.
            if live_gate.kill_state(s.home).engaged:
                return JSONResponse(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "code": "kill_switch_engaged",
                        "ok": False,
                        "effect": "refused",
                        "message": "kill switch engaged",
                    },
                    status_code=200,
                )
            account_id = inner.get("account_id") or ""
            revision_id = inner.get("revision_id")
            mode = inner.get("mode")
            if not isinstance(account_id, str) or not isinstance(revision_id, str) or not isinstance(mode, str):
                return JSONResponse({"detail": "invalid body"}, status_code=400)
            stored_mode = _stored_deployment_mode(s.home)
            result = live_preflight_evaluate(
                account_id=account_id,
                revision_id=revision_id,
                mode=mode,
                transport=_live_transport(s),
                stored_mode=stored_mode,
            )
            return JSONResponse(result.to_dict(), status_code=200)
        if command == "live.promote":
            venue = inner.get("venue")
            pair = inner.get("pair")
            revision_id = inner.get("revision_id")
            if not isinstance(venue, str) or not isinstance(pair, str) or not isinstance(revision_id, str):
                return JSONResponse({"detail": "invalid body"}, status_code=400)
            promote = live_gate.check_promotion(
                s.home,
                venue=venue,
                pair=pair,
                revision_id=revision_id,
            )
            body_promote = {
                "schema_version": SCHEMA_VERSION,
                "code": promote.code,
                "ok": False,
                "message": promote.message,
                "effect": "refused",
                "venue": venue,
                "pair": pair,
            }
            return JSONResponse(body_promote, status_code=200)
        if command == "operations.kill":
            reason = inner.get("reason")
            if not isinstance(reason, str):
                return JSONResponse(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "code": "bad_input",
                        "ok": False,
                        "effect": "refused",
                        "message": "reason must be a string",
                    },
                    status_code=200,
                )
            try:
                state = live_gate.engage_kill(s.home, reason=reason, now=_now_seconds())
            except ValueError as exc:
                return JSONResponse(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "code": "bad_input",
                        "ok": False,
                        "effect": "refused",
                        "message": str(exc),
                    },
                    status_code=200,
                )
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "kill_switch_engaged",
                    "ok": True,
                    "effect": "changed",
                    "kill_switch": state.to_dict(),
                },
                status_code=200,
            )
        if command == "operations.release_kill":
            state = live_gate.release_kill(s.home)
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "kill_switch_released",
                    "ok": True,
                    "effect": "changed",
                    "kill_switch": state.to_dict(),
                },
                status_code=200,
            )
        if command == "alerts.ack":
            alert_id = inner.get("alert_id")
            if not isinstance(alert_id, str):
                return JSONResponse({"detail": "invalid body"}, status_code=400)
            try:
                acked = alerts_app.acknowledge(s.home, alert_id, now=_now_seconds())
            except KeyError:
                return JSONResponse(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "code": "alert_not_found",
                        "ok": False,
                    },
                    status_code=404,
                )
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "acknowledged",
                    "ok": True,
                    "alert": acked.to_dict(),
                },
                status_code=200,
            )
        if command == "live.arm":
            # Web live arm behind the existing gate. While PAPER_ONLY_RELEASE
            # is active, refuse with an honest structured 403 before any
            # pack/key/transport work. When live is re-enabled, authorize via
            # grant + kill switch + env and skip stdin Type LIVE (grant
            # already required typed LIVE).
            if release_policy.paper_only_release_active():
                paper_only = live_gate.check_web_live_arm(
                    s.home,
                    venue="kraken",
                    pair="unused",
                )
                return _live_arm_gate_refusal(paper_only)

            venue = inner.get("venue")
            pack_path_raw = inner.get("pack_path")
            revision_id = inner.get("revision_id")
            if not isinstance(venue, str) or not venue:
                return JSONResponse({"detail": "invalid body"}, status_code=400)
            if not pack_path_raw and not revision_id:
                return JSONResponse({"detail": "invalid body"}, status_code=400)

            trusted_pack: Path | None = None
            pack_data: object | None = None
            if revision_id:
                if not isinstance(revision_id, str):
                    return JSONResponse({"detail": "invalid body"}, status_code=400)
                try:
                    draft = _draft_service(s)
                    # Server-owned draft path + pack bytes; never from client path.
                    trusted_pack, pack_data = draft.pack_for_arm(revision_id)
                except RevisionNotFound:
                    return JSONResponse(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "code": "draft_not_found",
                            "ok": False,
                            "message": f"draft {revision_id} not found",
                            "effect": "refused",
                            "detail": f"draft {revision_id} not found",
                        },
                        status_code=404,
                    )
                except DraftNotRunnable:
                    msg = f"draft {revision_id} is not runnable"
                    return JSONResponse(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "code": "draft_not_runnable",
                            "ok": False,
                            "message": msg,
                            "effect": "refused",
                            "detail": msg,
                        },
                        status_code=403,
                    )
            else:
                if not isinstance(pack_path_raw, str):
                    return JSONResponse({"detail": "invalid body"}, status_code=400)
                basename = _client_pack_basename(pack_path_raw)
                if basename is None:
                    return JSONResponse({"detail": "invalid body"}, status_code=400)
                # Path is home + sanitized basename only (no user directories).
                trusted_pack = s.home / basename
                try:
                    pack_data = json.loads(trusted_pack.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    return JSONResponse(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "code": "pack_has_no_market",
                            "ok": False,
                            "effect": "refused",
                            "message": f"pack has no market for {venue}",
                            "detail": f"pack has no market for {venue}",
                        },
                        status_code=400,
                    )

            if trusted_pack is None:
                return JSONResponse({"detail": "invalid body"}, status_code=400)

            pair = _pair_from_pack_data(pack_data, venue)
            if pair is None:
                return JSONResponse(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "code": "pack_has_no_market",
                        "ok": False,
                        "effect": "refused",
                        "message": f"pack has no market for {venue}",
                        "detail": f"pack has no market for {venue}",
                    },
                    status_code=400,
                )

            gate = live_gate.check_web_live_arm(s.home, venue=venue, pair=pair)
            if not gate.ok:
                return _live_arm_gate_refusal(gate)
            # Successful gate ⇒ grant already collected typed LIVE; skip stdin
            # (see live_gate.web_arm_skips_stdin_confirmation).

            from krellbot.run import arm_pack

            rc = arm_pack(
                trusted_pack,
                venue=venue,
                mode="live",
                home=s.home,
                skip_confirm=True,
                key_check=_live_arm_key_check(s),
            )
            if rc == 0:
                if revision_id:
                    try:
                        _draft_service(s).mark_deployed(revision_id)
                    except (RevisionNotFound, DraftNotRunnable):
                        pass
                return JSONResponse(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "correlation_id": correlation_id,
                        "code": "armed",
                        "ok": True,
                        "effect": "changed",
                        "message": f"armed on {venue} {pair}",
                        "venue": venue,
                        "pair": pair,
                    },
                    status_code=200,
                )
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "correlation_id": correlation_id,
                    "code": "live_arm_refused",
                    "ok": False,
                    "effect": "refused",
                    "message": "live arm refused",
                    "detail": "live arm refused",
                    "venue": venue,
                    "pair": pair,
                },
                status_code=403,
            )
        if command.startswith("live."):
            return JSONResponse({"detail": "live orders are disabled"}, status_code=403)
        if inner.get("mode") == "live":
            return JSONResponse({"detail": "live orders are disabled"}, status_code=403)
        if command not in PAPER_COMMANDS:
            return JSONResponse({"detail": f"unknown command {command}"}, status_code=403)

        service = _paper_service(s)

        if command == "paper.arm":
            # ``paper.arm`` may be addressed by ``pack_path`` (legacy) or
            # by ``revision_id`` for a draft (NS08a). Draft addressing
            # resolves the on-disk draft bytes without rewriting the
            # file. A non-runnable draft is refused before any config
            # byte changes.
            pack_path = inner.get("pack_path")
            revision_id = inner.get("revision_id")
            if not pack_path and not revision_id:
                return JSONResponse({"detail": "invalid body"}, status_code=400)
            if revision_id:
                try:
                    draft = _draft_service(s)
                    pack_path, _pack = draft.pack_for_arm(revision_id)
                except RevisionNotFound:
                    return JSONResponse(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "code": "draft_not_found",
                            "ok": False,
                            "message": f"draft {revision_id} not found",
                            "effect": "refused",
                            "revision_before": None,
                            "revision_after": None,
                        },
                        status_code=404,
                    )
                except DraftNotRunnable as exc:
                    return JSONResponse(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "code": "draft_not_runnable",
                            "ok": False,
                            "message": str(exc),
                            "effect": "refused",
                            "revision_before": None,
                            "revision_after": None,
                        },
                        status_code=403,
                    )
            result = service.arm(
                Path(pack_path),
                venue=inner["venue"],
                mode=inner.get("mode", "paper"),
                paper_balance=Decimal(inner["paper_balance"]),
                correlation_id=correlation_id,
            )
            if revision_id and result.ok:
                try:
                    _draft_service(s).mark_deployed(revision_id)
                except (RevisionNotFound, DraftNotRunnable):
                    pass
        elif command == "paper.disarm":
            result = service.disarm(
                venue=inner["venue"],
                pair=inner["pair"],
                correlation_id=correlation_id,
            )
        elif command == "paper.pause_entries":
            result = service.pause_entries(
                venue=inner["venue"],
                pair=inner["pair"],
                correlation_id=correlation_id,
            )
        elif command == "paper.resume_entries":
            result = service.resume_entries(
                venue=inner["venue"],
                pair=inner["pair"],
                correlation_id=correlation_id,
            )
        elif command == "paper.raise_stop":
            if "new_stop" not in inner:
                return JSONResponse({"detail": "invalid stop", "code": "invalid_stop"}, status_code=400)
            try:
                new_stop_value = Decimal(str(inner["new_stop"]))
                if not new_stop_value.is_finite():
                    return JSONResponse({"detail": "invalid stop", "code": "invalid_stop"}, status_code=400)
            except (InvalidOperation, ValueError, TypeError):
                return JSONResponse({"detail": "invalid stop", "code": "invalid_stop"}, status_code=400)
            result = service.raise_stop(
                venue=inner["venue"],
                pair=inner["pair"],
                new_stop=new_stop_value,
                correlation_id=correlation_id,
            )
        elif command == "paper.export":
            result = service.export(
                venue=inner["venue"],
                pair=inner["pair"],
                correlation_id=correlation_id,
            )
        else:
            return JSONResponse({"detail": f"unknown command {command}"}, status_code=403)

        return JSONResponse(result.to_dict(), status_code=200)

    @app.post("/api/v1/research/jobs")
    async def research_jobs(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        kind = payload.get("kind", JOB_KIND_RESEARCH_BACKTEST)
        if not isinstance(kind, str):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        correlation_id = payload.get("correlation_id")
        if not isinstance(correlation_id, str):
            correlation_id = ""

        # F4 — refuse an ambiguous pack source: both a non-empty
        # ``pack_path`` and a non-empty ``revision_id``. The default
        # runner prefers ``pack_path`` over ``revision_id``, so a
        # payload that sets both would silently run the typed path
        # instead of the revision the UI showed. Surface the refusal
        # before ``jobs.submit`` so no job is created.
        pack_path_raw = payload.get("pack_path")
        revision_id_raw = payload.get("revision_id")
        pack_path_filled = isinstance(pack_path_raw, str) and pack_path_raw != ""
        revision_id_filled = isinstance(revision_id_raw, str) and revision_id_raw != ""
        if pack_path_filled and revision_id_filled:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "ambiguous_pack_source",
                    "message": ("request sets both pack_path and revision_id; pick one"),
                },
                status_code=400,
            )

        try:
            job = s.jobs.submit(kind=kind, correlation_id=correlation_id, request=payload)
        except QueueFull as qf:
            return JSONResponse(
                {"code": qf.code, "message": qf.message, "schema_version": SCHEMA_VERSION},
                status_code=429,
            )

        return JSONResponse(job.to_dict(), status_code=200)

    @app.get("/api/v1/jobs")
    async def list_jobs(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied
        rows = [job.to_dict() for job in s.jobs.list_jobs()]
        return JSONResponse({"schema_version": SCHEMA_VERSION, "jobs": rows}, status_code=200)

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(request: Request, job_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        snap = s.jobs.get(job_id)
        if snap is None:
            return JSONResponse(
                {"code": JOB_ERROR_NOT_FOUND, "message": "job not found"},
                status_code=404,
            )
        return JSONResponse(snap.to_dict(), status_code=200)

    @app.post("/api/v1/jobs/{job_id}/cancel")
    async def cancel_job(request: Request, job_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            pass

        snap = s.jobs.cancel(job_id)
        if snap is None:
            return JSONResponse(
                {"code": JOB_ERROR_NOT_FOUND, "message": "job not found"},
                status_code=404,
            )
        return JSONResponse(snap.to_dict(), status_code=200)

    @app.get("/api/v1/jobs/{job_id}/result")
    async def get_job_result(request: Request, job_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        snap = s.jobs.get(job_id)
        if snap is None:
            return JSONResponse(
                {"code": JOB_ERROR_NOT_FOUND, "message": "job not found"},
                status_code=404,
            )
        result = s.jobs.result_for(job_id)
        if result is None:
            # The job is known and not succeeded: running, cancelling,
            # cancelled, queued, or failed. Per the contract the result
            # route is unavailable in those states.
            return JSONResponse(
                {"code": JOB_ERROR_RESULT_UNAVAILABLE},
                status_code=404,
            )
        return JSONResponse(result, status_code=200)

    @app.get("/api/v1/events")
    async def events(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        buffer = s.jobs.event_buffer()
        last_event_id_raw = request.headers.get("Last-Event-ID") or None
        last_event_id: int | None
        if last_event_id_raw is None:
            last_event_id = None
        else:
            try:
                last_event_id = int(last_event_id_raw)
            except (TypeError, ValueError):
                return JSONResponse({"detail": "bad last event id"}, status_code=400)

        gap = last_event_id is not None and buffer.is_gap(last_event_id)
        to_replay = [] if gap else buffer.replay(last_event_id)

        async def _emit():
            if gap:
                yield _format_resync_marker(str(last_event_id))
                return
            for event in to_replay:
                yield _format_sse(
                    event_id=event.event_id,
                    event_name=event.kind,
                    data_payload=event.to_dict(),
                )

        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        return StreamingResponse(_emit(), media_type="text/event-stream", headers=headers)

    @app.get("/api/v1/operations")
    async def operations(request: Request) -> Response:
        """Return the closed-shape operations view (M3-GUI).

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF
        required. The body aggregates ``live_gate.live_status`` (with the
        app's actual ``env`` so ``KRELLBOT_ENABLE_LIVE`` is honored), the
        per-deployment projection (mode verbatim, promotion refusal code),
        and the deduped, severity-sorted alert list. No ``cap``,
        ``stop``, ``starting_cash``, ``owned_qty``, ``pack_path``,
        ``pack_sha256``, balance, or key material appears in the body.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = operations_view_app.operations_view(s.home, now=_now_seconds())
        # Opt-in alert notifications (desktop/email). Separate from telemetry.
        # FakeNotifier is injected by tests; production builds the default.
        from krellbot import notifications as kb_notifications

        kb_notifications.maybe_notify(
            s.home,
            body.get("alerts") or [],
            notifier=s.alert_notifier,
        )
        return JSONResponse(body, status_code=200)

    @app.get("/api/v1/notifications")
    async def notifications_settings_get(request: Request) -> Response:
        """Return closed-shape notification settings (M9.4).

        Same session gate as ``GET /api/v1/operations`` (``_gate_get``).
        The body never carries an SMTP password or any secret — password
        is supplied only via ``KRELLBOT_SMTP_PASSWORD`` at send time.
        Telemetry remains a separate opt-in.
        """

        from krellbot import notifications as kb_notifications

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = kb_notifications.get_settings(s.home)
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.put("/api/v1/notifications")
    async def notifications_settings_put(request: Request) -> Response:
        """Update opt-in desktop/email notification settings (M9.4).

        Same state-change gate as ``POST /api/v1/commands``. Rejects any
        attempt to persist an SMTP password in settings.
        """

        from krellbot import notifications as kb_notifications

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        try:
            body = kb_notifications.update_settings(s.home, payload)
        except ValueError:
            # Fixed copy only — do not echo exception text (CodeQL py/stack-trace-exposure).
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "bad_input",
                    "ok": False,
                    "message": "email password must come from KRELLBOT_SMTP_PASSWORD, not settings",
                },
                status_code=400,
            )
        except TypeError:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "bad_input",
                    "ok": False,
                    "message": "invalid notification settings",
                },
                status_code=400,
            )
        return JSONResponse(
            {**body, "ok": True, "code": "notifications_updated"},
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/operations/deployments")
    async def operations_deployment_history(request: Request) -> Response:
        """Return the closed-shape deployment history rows (read-only).

        Same session gate as ``GET /api/v1/operations`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF
        required for the read. Rows are projected from the append-only
        journal by ``operations_view_app.list_deployment_records`` and
        are capped at the 50 most recent. The body never carries
        ``cap``, ``stop``, ``starting_cash``, ``owned_qty``,
        ``pack_path``, ``pack_sha256``, balance, or key material.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        rows = operations_view_app.list_deployment_records(s.home)
        return JSONResponse(
            {"schema_version": SCHEMA_VERSION, "deployments": rows},
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/operations/deployments/{deployment_id}")
    async def operations_deployment_record(request: Request, deployment_id: str) -> Response:
        """Return one closed-shape deployment history row, or 404.

        Same session gate and same closed row shape as the list route.
        An unknown ``deployment_id`` is a 404 with a typed refusal code;
        there is no editing, starting, or promotion on this path.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        row = operations_view_app.get_deployment_record(s.home, deployment_id)
        if row is None:
            return JSONResponse(
                {"code": "deployment_not_found", "message": "deployment record not found"},
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(row, status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/operations/unresolved-orders")
    async def operations_unresolved_orders(request: Request) -> Response:
        """Return every order awaiting reconcile (read-only, M1.9).

        Same session gate as ``GET /api/v1/operations`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF
        required for the read. Each row carries ``client_order_id``,
        ``age_seconds``, and ``last_lookup_result``. An empty list is a
        successful 200 with ``orders: []``. The body never carries
        ``cap``, ``stop``, ``starting_cash``, ``owned_qty``,
        ``pack_path``, ``pack_sha256``, balance, or key material.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        rows = operations_view_app.list_unresolved_orders(s.home, now=_now_seconds())
        return JSONResponse(
            {"schema_version": SCHEMA_VERSION, "orders": rows},
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/operations/live-authorization")
    async def operations_live_authorization_get(request: Request) -> Response:
        """Return the closed-shape live authorization snapshot (M1.10).

        Same session gate as ``GET /api/v1/operations`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF
        required for the read. While ``PAPER_ONLY_RELEASE`` is active the
        body still reports the paper-only policy so the Operations panel
        can stay visible, disabled, and explain why.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        now = _now_seconds()
        live = live_gate.live_status(s.home, now=now)
        paper_only = live.get("release_policy") == "paper_only"
        body = {
            "schema_version": SCHEMA_VERSION,
            "authorization": live_gate.authorization_state(s.home, now=now).to_dict(),
            "release_policy": live.get("release_policy"),
            "release_policy_code": live.get("release_policy_code"),
            "release_policy_message": (release_policy.paper_only_message() if paper_only else None),
            "confirmation_required": live_gate.CONFIRMATION_TEXT,
        }
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/operations/live-authorization")
    async def operations_live_authorization_grant(request: Request) -> Response:
        """Create a live authorization for one exact venue/pair with expiry.

        Same state-change gate as ``POST /api/v1/commands``
        (``_gate_state_change``): session cookie + CSRF + loopback Origin.
        Requires the typed confirmation text ``LIVE``. While
        ``PAPER_ONLY_RELEASE`` is active the grant is refused and no file
        is written.
        """

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        venue = payload.get("venue")
        pair = payload.get("pair")
        expires_at = payload.get("expires_at")
        confirmation = payload.get("confirmation")
        if (
            not isinstance(venue, str)
            or not isinstance(pair, str)
            or not isinstance(expires_at, int)
            or not isinstance(confirmation, str)
        ):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        now = _now_seconds()
        result = live_gate.grant_authorization(
            s.home,
            venue=venue,
            pair=pair,
            expires_at=expires_at,
            confirmation=confirmation,
            now=now,
        )
        auth = live_gate.authorization_state(s.home, now=now).to_dict()
        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "code": result.code,
                "ok": result.ok,
                "message": result.message,
                "effect": "changed" if result.ok else "refused",
                "authorization": auth,
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.delete("/api/v1/operations/live-authorization")
    async def operations_live_authorization_revoke(request: Request) -> Response:
        """Revoke the current live authorization record.

        Same state-change gate as ``POST /api/v1/commands``. While
        ``PAPER_ONLY_RELEASE`` is active revocation is refused so the
        panel stays disabled for the paper-only release.
        """

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        now = _now_seconds()
        result = live_gate.revoke_authorization(s.home, now=now)
        auth = live_gate.authorization_state(s.home, now=now).to_dict()
        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "code": result.code,
                "ok": result.ok,
                "message": result.message,
                "effect": "changed" if result.ok else "refused",
                "authorization": auth,
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/scheduler")
    async def scheduler_status_get(request: Request) -> Response:
        """Return closed-shape scheduler status (M2.7).

        Same session gate as ``GET /api/v1/operations`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF.
        Body keys: ``installed``, ``enabled``, ``last_error``.
        """

        from krellbot.service import supervise as kb_supervise

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = kb_supervise.scheduler_status(
            s.home,
            write_root=_scheduler_write_root(s),
            supervisor=_scheduler_supervisor(s),
        )
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/scheduler/install")
    async def scheduler_install(request: Request) -> Response:
        """Install OS scheduler unit files via existing service renderers.

        Same state-change gate as ``POST /api/v1/commands``
        (``_gate_state_change``): session cookie + CSRF + loopback Origin.
        Already-installed units are reported as success without rewrite.
        """

        from krellbot.service import supervise as kb_supervise

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        body = kb_supervise.install_scheduler(
            s.home,
            write_root=_scheduler_write_root(s),
            supervisor=_scheduler_supervisor(s),
            executable=_scheduler_executable(s),
        )
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/scheduler/enable")
    async def scheduler_enable(request: Request) -> Response:
        """Enable the installed scheduler unit via the platform supervisor.

        Same state-change gate as ``POST /api/v1/commands``. Platform
        calls go through ``s.scheduler_supervisor`` (fake in tests).
        """

        from krellbot.service import supervise as kb_supervise

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        body = kb_supervise.enable_scheduler(
            s.home,
            write_root=_scheduler_write_root(s),
            supervisor=_scheduler_supervisor(s),
        )
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/paper/status")
    async def paper_status(request: Request) -> Response:
        """Return the closed-shape paper status projection (NS10b).

        The route uses the same session gate as ``GET /api/v1/jobs/{id}``
        (``_gate_get``): session cookie + loopback Origin + loopback Host,
        no CSRF required. The body never carries cash, quantity, stop,
        cap, or the pack path. ``mode`` is always ``"paper"`` for an
        armed record; the brief forbids a live-order control and
        forbids ``mode: live`` over the wire.

        Multi-deploy: optional ``venue``+``pair`` query params select one
        armed record. Without them the first record is projected, and
        ``armed_count`` always reports how many packs are armed so the
        UI is not silently limited to ``config.armed[0]``.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        config = kb_config.load_config(s.home)
        armed, armed_count = _select_armed_for_request(config, request)
        if armed is None:
            return JSONResponse(
                _with_armed_count(
                    {"schema_version": SCHEMA_VERSION, "armed": False},
                    armed_count,
                ),
                status_code=200,
                headers={"Cache-Control": "no-store"},
            )

        body = _with_armed_count(
            {
                "schema_version": SCHEMA_VERSION,
                "armed": True,
                "venue": armed.venue,
                "pair": armed.pair,
                "entries_paused": bool(armed.entries_paused),
                "mode": armed.mode,
                "pack_id": armed.pack_id,
            },
            armed_count,
        )
        return JSONResponse(body, status_code=200)

    @app.get("/api/v1/paper/details")
    async def paper_details(request: Request) -> Response:
        """Read configured paper deposit/percent and this pair's durable stop.

        The deposit is not free cash, and the cap is not a currency amount.
        Only a paper-mode armed record is projected (first by default, or
        the ``venue``+``pair`` query selection). Reading raw state never
        constructs a venue, seeds balances, evaluates stops, or infers a
        fill. Existing status/position contracts stay closed.
        """
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        config = kb_config.load_config(s.home)
        armed, _armed_count = _select_armed_for_request(config, request)
        if armed is None or armed.mode != "paper":
            return JSONResponse(
                {"schema_version": SCHEMA_VERSION, "armed": False},
                headers={"Cache-Control": "no-store"},
            )

        try:
            # Unlike the legacy display reader, preserve raw JSON fractions
            # as Decimal: binary floats can round a price or underflow to zero.
            # Keep the default integer parser's safety limit local and intact.
            path = s.home / "run" / f"paper-{armed.venue}.json"
            state = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        except (OSError, ValueError, InvalidOperation, RecursionError):
            state = {}
        orders = state.get("open_orders") if isinstance(state, dict) else None
        resting_stop = None
        if isinstance(orders, list):
            # Match PaperVenue.resting_stop's first matching non-null stop,
            # but fail closed on malformed/nonfinite persisted values.
            for order in orders:
                if isinstance(order, dict) and order.get("pair") == armed.pair and order.get("stop_price") is not None:
                    resting_stop = _paper_details_decimal(order["stop_price"])
                    break

        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "armed": True,
                "venue": armed.venue,
                "pair": armed.pair,
                "pack_id": armed.pack_id,
                "starting_cash": _paper_details_decimal(armed.starting_cash),
                "risk_cap_pct": _paper_details_decimal(armed.cap),
                "resting_stop": resting_stop,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/paper/position")
    async def paper_position(request: Request) -> Response:
        """Return the owned paper position read from the persisted state file.

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF. The
        body is the paper-only owned-position projection the workstation
        displays verbatim:

        * ``free_cash`` — the quote-asset balance string exactly as
          ``<home>/run/paper-<venue>.json`` persists it (Decimal-as-string,
          never re-formatted). When no state file exists yet (just-armed,
          before the first tick), the armed record's ``starting_cash`` is
          projected instead of a false ``\"0\"``.
        * ``holdings`` — at most one ``{"symbol", "qty"}`` row for this
          armed pair's base asset when its balance is above zero, qty
          verbatim from the state file. Other base assets in the same
          venue wallet are omitted so another market's position is never
          presented here. The quote asset is the pair's USD-style suffix,
          the same base/quote split ``krellbot.application.paper`` uses.
        * ``as_of_run`` — ``"<venue>:<pack>:<pair>"`` of the most recent
          journal tick run for the armed pair, or ``null`` when the
          journal has no tick record for it (the engine has never run).
        * ``armed_count`` — present only when more than one pack is armed;
          optional ``venue``+``pair`` query params select which record to
          project.

        The route never writes, arms, or flattens anything, and the
        closed-shape ``/api/v1/paper/status`` contract is untouched:
        cash, quantity, stop, cap and pack path stay off that body. When
        no pack is armed the body is ``{"schema_version": <v>,
        "armed": false}`` and no state file is read.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        config = kb_config.load_config(s.home)
        armed, armed_count = _select_armed_for_request(config, request)
        if armed is None:
            return JSONResponse(
                _with_armed_count(
                    {"schema_version": SCHEMA_VERSION, "armed": False},
                    armed_count,
                ),
                status_code=200,
                headers={"Cache-Control": "no-store"},
            )

        body = project_owned_position(
            s.home,
            venue=armed.venue,
            pair=armed.pair,
            mode=armed.mode,
            as_of_run=_paper_position_run_id(s.home, armed.venue, armed.pair),
            starting_cash=armed.starting_cash,
        )
        return JSONResponse(
            _with_armed_count(body, armed_count),
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/paper/chart")
    async def paper_chart(request: Request) -> Response:
        """Return P&L + position (or mark) series for the armed paper market.

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF. The
        body is the closed-shape chart projection from journal ticks and
        paper-state fills:

        * ``pnl`` — fill-replay equity minus ``starting_cash``
        * ``position`` — journal ``owned_qty_after`` over time
        * ``marks`` — fill prices (mark series when position is thin)

        Series stay empty when evidence is missing; nothing is fabricated.
        When no pack is armed the body is
        ``{"schema_version": <v>, "armed": false}``. Read-only: never
        writes, arms, or flattens.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = project_paper_pnl_position_chart(s.home)
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/paper/history")
    async def paper_history(request: Request) -> Response:
        """Return the read-only "Last runs" projection (paper panel).

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF. The
        body is read-only evidence over ``<home>/journal/*.jsonl`` plus
        the paper state file ``<home>/run/paper-<venue>.json``: one run
        per ``(venue, pack, pair)`` the journal records, capped at 20
        runs with ``recent_fills`` capped at 50. The route never reads
        or returns owned cash, quantity, stop, cap, or the pack path —
        fill ``qty``/``price`` stay off the wire too — and there is no
        control surface here: nothing edits, arms, or starts a run.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = _paper_history_view(s.home)

        return JSONResponse(
            body,
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/journal")
    async def journal_browse(request: Request) -> Response:
        """Browse journal events — CLI ``krellbot journal`` parity subset.

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF.

        Query params (mutually exclusive selection; ``since`` wins when both
        are present, matching the CLI):

        - ``tail`` — positive integer; default 5 when ``since`` is absent.
        - ``since`` — ``24h`` or ``14d`` only.

        Body is ``{"schema_version": "1", "records": [...]}`` with export
        secret fields (``key``, ``secret``, ``license``, ``balance``)
        dropped at any depth. Empty journal → ``records: []``. Invalid
        params → 400 with a typed ``code``. Served with
        ``Cache-Control: no-store``.
        """

        from krellbot import journal as kb_journal

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        raw_tail = request.query_params.get("tail")
        raw_since = request.query_params.get("since")

        tail: int | None = None
        since: str | None = None

        if raw_since is not None and raw_since != "":
            since = raw_since
        if raw_tail is not None and raw_tail != "":
            try:
                tail = int(raw_tail)
            except (TypeError, ValueError):
                return JSONResponse(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "detail": f"invalid --tail: {raw_tail}",
                        "code": "invalid_tail",
                    },
                    status_code=400,
                )

        try:
            records = kb_journal.browse(s.home, tail=tail, since=since)
        except kb_journal.BrowseError as err:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "detail": err.message,
                    "code": err.code,
                },
                status_code=400,
            )

        body = {
            "schema_version": SCHEMA_VERSION,
            "records": records,
        }
        return JSONResponse(
            body,
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/portfolio/history")
    async def portfolio_history(request: Request) -> Response:
        """Return cross-deployment portfolio history (equity + deployments).

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF. The
        body is read-only evidence over ``<home>/journal/*.jsonl`` and
        ``<home>/run/paper-<venue>.json``:

        * ``equity`` — absolute portfolio equity series from venue fill
          replay (empty when starting cash or fills are absent)
        * ``deployments`` — one card per journalled / armed
          ``(venue, pack, pair)``, with pair-scoped ``pnl`` only when
          ``starting_cash`` is known from the armed config

        Never fabricates sample bots or flat zero equity. Does not
        change opt-in telemetry. Read-only: never arms or writes.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = project_portfolio_history(s.home)
        return JSONResponse(
            body,
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/paper/armed")
    async def paper_armed(request: Request) -> Response:
        """Return the closed-shape list of every armed pack record.

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF
        required. The service guarantees one armed record per
        (venue, pair); unlike the single-record status projection this
        view returns one row per armed record so the workstation can
        show which packs are armed where. Each row carries only the
        closed field set — venue, pair, mode, pack_id,
        entries_paused — never cash, quantity, stop, cap, or the pack
        path.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        config = kb_config.load_config(s.home)
        records = [
            {
                "venue": record.venue,
                "pair": record.pair,
                "mode": record.mode,
                "pack_id": record.pack_id,
                "entries_paused": bool(record.entries_paused),
            }
            for record in config.armed
        ]
        body = {
            "schema_version": SCHEMA_VERSION,
            "armed": bool(records),
            "records": records,
        }

        return JSONResponse(
            body,
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/paper/fleet")
    async def paper_fleet(request: Request) -> Response:
        """Return the armed fleet management list with last tick evidence.

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF. One
        row per armed config record joins the closed armed identity with
        journal last-tick time/result and a relative ``detail_href`` deep
        link into the Workstation status surface. Cash, quantity, stop,
        cap, and pack path never appear on the wire.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = _fleet_armed_view(s.home)

        return JSONResponse(
            body,
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/rehearsal/status")
    async def rehearsal_status(request: Request) -> Response:
        """Return the synthetic rehearsal projection.

        Same gate as ``GET /api/v1/paper/status``: session cookie +
        loopback Origin + loopback Host, no CSRF. The body is the closed
        plain-JSON rehearsal projection — status, cursor, total bars,
        balances, position, resting stop, recent fills — with the
        explicit synthetic label, and never an internal service object.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = _rehearsal_wire(_rehearsal_service(s).status_dict())
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/packs")
    async def packs(request: Request) -> Response:
        """Return the closed-shape installed pack rows (installed pack library).

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF
        required. The body is exactly the row list from
        ``krellbot.application.packs.list_packs`` — one object per pack
        with the closed keys ``bucket``, ``pack_id``, ``version``,
        ``permissions``, ``rollback_ref``. The route is read-only: it
        mounts no install, catalog, entitlement, or rollback surface,
        and adds nothing to ``/api/v1/capabilities``.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        body = app_packs.list_packs(s.home)
        return JSONResponse(body, status_code=200)

    @app.get("/api/v1/packs/starters")
    async def packs_starters(request: Request) -> Response:
        """Return the shipped read-only starter pack catalogue.

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF
        required. The body is the frozen catalogue document from
        ``krellbot.packs.catalogue`` — ``schema_version``,
        ``catalogue_version``, and ``examples`` rows carrying exactly
        ``id``, ``label``, ``description``, ``pack``. The examples are
        ordinary valid DSL packs served from package resources. The
        route is read-only: it installs nothing, validates no user
        draft, arms nothing, starts nothing, overwrites nothing, and
        edits no state. A user turns a starter into an owned editable
        copy by POSTing ``pack`` through the existing drafts route.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        from krellbot.packs import catalogue as starter_catalogue

        try:
            body = starter_catalogue.catalogue_document()
        except starter_catalogue.StarterCatalogueError as exc:
            return JSONResponse(
                {"detail": f"starter catalogue unavailable: {exc}"},
                status_code=500,
            )
        return JSONResponse(body, status_code=200)

    @app.get("/api/v1/catalogue")
    async def catalogue_list(request: Request) -> Response:
        """Fetch and verify the signed Strategy Pack catalogue (free + paid).

        Same session gate as ``GET /api/v1/packs`` (``_gate_get``): session
        cookie + loopback Origin + loopback Host, no CSRF required. The
        route asks ``pack_library.refresh_catalogue`` to pull the signed
        envelope through the injectable ``catalogue_transport`` (production
        uses the HTTPS JSON transport in ``license_activation``), verify
        the ed25519 signature, and rewrite the local catalogue cache.
        Tampered or malformed envelopes are refused with 502 and never
        rewrite the cache. The body is the closed catalogue document:
        ``schema_version``, ``catalogue_version``, optional ``updated``,
        and ``packs`` rows each carrying ``id``, ``tier`` (``free`` or
        ``paid``), and optional label/description/version/permissions.
        """

        from krellbot.application import pack_library as pack_library_app

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        try:
            document = pack_library_app.refresh_catalogue(
                s.home,
                transport=s.catalogue_transport,
            )
        except OSError:
            return JSONResponse(
                {"detail": "catalogue unreachable"},
                status_code=502,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return JSONResponse(
                {"detail": "catalogue signature rejected"},
                status_code=502,
            )

        body = {
            "schema_version": SCHEMA_VERSION,
            "catalogue_version": document["catalogue_version"],
            "packs": document["packs"],
        }
        if isinstance(document.get("updated"), str):
            body["updated"] = document["updated"]
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/capabilities")
    async def capabilities(request: Request) -> Response:
        # The bootstrap token reaches the shell only through the
        # ``<meta name="krellbot-bootstrap">`` tag the static layer
        # injects into the served index.html. It is never part of this
        # (or any) JSON body.
        body = {
            "schema_version": SCHEMA_VERSION,
            "paper_commands": list(PAPER_COMMANDS),
            "research": True,
            "live_orders": False,
        }
        return JSONResponse(body, status_code=200)

    @app.get("/api/v1/version")
    async def version(request: Request) -> Response:
        """Surface engine version and release-channel honesty.

        Same loopback Host gate as ``GET /api/v1/capabilities`` (no
        session). Channel is prerelease while artifacts are unsigned;
        GA is refused until signing state matches.
        """

        from krellbot import release_channel

        return JSONResponse(release_channel.version_payload(), status_code=200)

    # ---- keys onboarding (M3.1 Kraken + M11.1 Coinbase) ----------------

    KEYS_VENUES = frozenset({"kraken", "coinbase"})

    def _keys_keyring():
        import keyring as _keyring

        return _keyring.get_keyring()

    def _keys_venue_or_404(venue: str) -> Response | None:
        if venue not in KEYS_VENUES:
            return JSONResponse({"detail": "not found"}, status_code=404)
        return None

    @app.post("/api/v1/keys/{venue}")
    async def keys_probe_and_store(venue: str, request: Request) -> Response:
        """Probe then store a trade-only key for ``venue`` (Kraken or Coinbase).

        Same state-change gate as ``POST /api/v1/commands``
        (``_gate_state_change``): session cookie + CSRF + loopback Origin.
        Persistence is owned by ``keys_onboarding.probe_and_store``; trade-
        only enforcement is unchanged. The response never carries the raw
        key, secret, or venue error text.
        """

        from krellbot import keys_onboarding

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied
        missing = _keys_venue_or_404(venue)
        if missing is not None:
            return missing

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        key = payload.get("key")
        secret = payload.get("secret")
        if not isinstance(key, str) or not isinstance(secret, str):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        result = keys_onboarding.probe_and_store(
            venue,
            key,
            secret,
            keyring_backend=_keys_keyring(),
            probe=s.keys_transport,
            allow_injected_fake_backend=s.keys_allow_fake_backend,
        )
        ok = result.status == keys_onboarding.Status.STORED
        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "venue": venue,
                "status": result.status.value,
                "ok": ok,
                "message": result.message,
                "effect": "changed" if ok else "refused",
                "backend_label": result.backend_label,
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/keys/{venue}")
    async def keys_status(venue: str, request: Request) -> Response:
        """Return connection status and balances for ``venue`` (Kraken or Coinbase).

        Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
        session cookie + loopback Origin + loopback Host, no CSRF. Balances
        are read through an injectable venue transport (tests use a fake).
        """

        from krellbot import keys_onboarding

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied
        missing = _keys_venue_or_404(venue)
        if missing is not None:
            return missing

        snap = keys_onboarding.connection_status(
            venue,
            keyring_backend=_keys_keyring(),
            transport=s.keys_transport,
            allow_injected_fake_backend=s.keys_allow_fake_backend,
            include_balances=True,
        )
        balances = None
        if snap.balances is not None:
            balances = [{"asset": row.asset, "free": row.free} for row in snap.balances]
        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "venue": snap.venue,
                "present": snap.present,
                "corrupt": snap.corrupt,
                "message": snap.message,
                "backend_label": snap.backend_label,
                "balances": balances,
                "balances_available": snap.balances_available,
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    @app.delete("/api/v1/keys/{venue}")
    async def keys_remove(venue: str, request: Request) -> Response:
        """Remove the stored key pair for ``venue`` (Kraken or Coinbase).

        Same state-change gate as ``POST /api/v1/commands``
        (``_gate_state_change``): session cookie + CSRF + loopback Origin.
        """

        from krellbot import keys_onboarding

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied
        missing = _keys_venue_or_404(venue)
        if missing is not None:
            return missing

        result = keys_onboarding.remove_stored(
            venue,
            keyring_backend=_keys_keyring(),
            allow_injected_fake_backend=s.keys_allow_fake_backend,
        )
        ok = result.status == keys_onboarding.RemovalStatus.REMOVED
        absent = result.status == keys_onboarding.RemovalStatus.ABSENT
        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "venue": venue,
                "status": result.status.value,
                "ok": ok or absent,
                "message": result.message,
                "effect": "changed" if ok else ("unchanged" if absent else "refused"),
                "backend_label": result.backend_label,
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    # ---- strategy drafts (NS08a) --------------------------------------

    def _resolve_pack_field(payload: dict) -> tuple[dict | None, Response | None]:
        """Return ``(pack, None)`` or ``(None, bad_request)``."""

        if not isinstance(payload, dict):
            return None, JSONResponse({"detail": "invalid body"}, status_code=400)
        raw = payload.get("pack")
        if not isinstance(raw, dict):
            return None, JSONResponse({"detail": "invalid body"}, status_code=400)
        return raw, None

    @app.post("/api/v1/strategies/drafts")
    async def create_draft(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        pack, err = _resolve_pack_field(payload)
        if err is not None:
            return err

        try:
            summary = _draft_service(s).create(pack)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse(summary, status_code=200)

    @app.put("/api/v1/strategies/drafts/{revision_id}")
    async def edit_draft(request: Request, revision_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        pack, err = _resolve_pack_field(payload)
        if err is not None:
            return err

        try:
            summary = _draft_service(s).edit(revision_id, pack)
        except RevisionNotFound:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "draft_not_found",
                    "message": f"draft {revision_id} not found",
                },
                status_code=404,
            )
        except StrategyIdMismatch as exc:
            # F3 — pack strategy id differs from the parent's strategy
            # id. Catching this before the generic ``ValueError``
            # branch keeps the 400 mapping for the other errors.
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "strategy_id_mismatch",
                    "message": str(exc),
                },
                status_code=409,
            )
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse(summary, status_code=200)

    @app.post("/api/v1/strategies/drafts/{revision_id}/validate")
    async def validate_draft(request: Request, revision_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        # Body is optional. Eat it so a trailing JSON parse error does
        # not 400 a valid request.
        try:
            await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            pass

        try:
            summary = _draft_service(s).validate(revision_id)
        except RevisionNotFound:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "draft_not_found",
                    "message": f"draft {revision_id} not found",
                },
                status_code=404,
            )
        return JSONResponse(summary, status_code=200)

    @app.get("/api/v1/strategies/drafts/{revision_id}")
    async def get_draft(request: Request, revision_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied
        summary = _draft_service(s).get(revision_id)
        if summary is None:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "draft_not_found",
                    "message": f"draft {revision_id} not found",
                },
                status_code=404,
            )
        return JSONResponse(summary, status_code=200)

    @app.post("/api/v1/strategies/drafts/{revision_id}/editor")
    async def save_draft_editor(request: Request, revision_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict) or not isinstance(payload.get("editor"), dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        try:
            summary = _draft_service(s).save_editor(revision_id, payload["editor"])
        except RevisionNotFound:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "draft_not_found",
                    "message": f"draft {revision_id} not found",
                },
                status_code=404,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse(summary, status_code=200)

    @app.get("/api/v1/strategies/drafts")
    async def list_drafts(request: Request) -> Response:
        """List every owned revision the user has saved locally.

        Read-only walk of ``<home>/drafts`` behind the same
        session/loopback gate as ``GET
        /api/v1/strategies/drafts/{revision_id}``. Rows are one summary
        per revision (newest first); a revision whose stored bytes or
        meta fail to parse is skipped rather than failing the request.
        Imported packs that never became an owned revision live under
        ``<home>/packs`` and never appear here. Nothing is armed,
        rewritten, or state-changed by this route.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied
        rows = _draft_service(s).list_owned_summaries()
        body = {"schema_version": SCHEMA_VERSION, "drafts": rows}
        return JSONResponse(body, status_code=200, headers={"Cache-Control": "no-store"})

    # ---- research result download (lane E) ------------------------------

    @app.get("/api/v1/jobs/{job_id}/result/download")
    async def download_job_result(request: Request, job_id: str) -> Response:
        """Return the canonical receipt bytes for ``job_id`` as a download.

        The route uses ``_gate_get`` so a session is required; no CSRF
        since it is a read. The body is the byte-identical canonical
        UTF-8 JSON of ``legacy_receipt`` so a workstation ``Save As``
        yields the exact bytes the runner shipped. A missing or non-
        succeeded job is 404 with the same closed shape the inline
        result route uses.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        snap = s.jobs.get(job_id)
        if snap is None:
            return JSONResponse(
                {"code": JOB_ERROR_NOT_FOUND, "message": "job not found"},
                status_code=404,
            )
        if snap.state != "succeeded":
            return JSONResponse(
                {"code": JOB_ERROR_RESULT_UNAVAILABLE},
                status_code=404,
            )
        result = s.jobs.result_for(job_id)
        if result is None or "legacy_receipt" not in result:
            return JSONResponse(
                {"code": JOB_ERROR_RESULT_UNAVAILABLE},
                status_code=404,
            )
        receipt = result["legacy_receipt"]
        if not isinstance(receipt, dict):
            return JSONResponse(
                {"code": JOB_ERROR_RESULT_UNAVAILABLE},
                status_code=404,
            )
        # ``canonical_receipt_bytes`` is the single source of truth for
        # the wire shape; using it keeps the inline route and the
        # download byte-identical.
        from krellbot.api.jobs import canonical_receipt_bytes

        body = canonical_receipt_bytes(receipt)
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="research-result.json"',
                "Cache-Control": "no-store",
            },
        )

    # ---- pack catalogue one-click install (M5.2) ------------------------

    @app.post("/api/v1/packs/install")
    async def packs_install(request: Request) -> Response:
        """One-click install a free signed-catalogue pack into the library.

        Same state-change gate as other POSTs (``_gate_state_change``):
        session cookie + CSRF + loopback Origin. Body is
        ``{"pack_id": "<id>"}`` (optional ``schema_version`` /
        ``command`` wrappers are ignored). Free catalogue entries write
        a ``download_pending`` marker so the library can show
        bucket+version; paid entries return 403 with
        ``activation_required``. Unknown ids return 404. No network
        call — the verified catalogue cache is the only source.
        """

        from krellbot.application import pack_library as pack_library_app

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        pack_id = payload.get("pack_id")
        if not isinstance(pack_id, str) or not pack_id:
            nested = payload.get("payload")
            if isinstance(nested, dict):
                pack_id = nested.get("pack_id")
        if not isinstance(pack_id, str) or not pack_id:
            return JSONResponse({"detail": "pack_id is required"}, status_code=400)

        try:
            row = pack_library_app.install_from_catalogue(s.home, pack_id)
        except pack_library_app.InstallRefused as exc:
            status = 404 if exc.code == "pack_not_found" else 403
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "code": exc.code,
                    "message": str(exc),
                },
                status_code=status,
            )

        return JSONResponse(
            {
                "schema_version": SCHEMA_VERSION,
                "ok": True,
                "pack": row,
            },
            status_code=200,
        )

    # ---- activation redeem (lane E) -------------------------------------

    @app.post("/api/v1/activation/redeem")
    async def redeem_activation(request: Request) -> Response:
        """Delegate to ``krellbot.application.license_activation.redeem``; never echoes a key.

        The route is a state change (it can rewrite the license cache),
        so it runs the same session-cookie + CSRF + loopback-origin
        gate as every other POST before any body byte is read. The
        redeem pass then runs against ``s.home`` and returns the closed
        ``ActivateOutcome`` as JSON. Any ``OSError`` / decode failure
        surfaces as the matching safe message; the key never appears
        in the URL, body, header, or response.
        """

        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        key = payload.get("key", "")
        if not isinstance(key, str):
            key = ""

        from krellbot.application.license_activation import redeem

        outcome = redeem(key, home=s.home, now=int(_now_seconds()))
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": outcome.status,
            "message": outcome.message,
            "catalog_downloaded": outcome.catalog_downloaded,
        }
        return JSONResponse(body, status_code=200)

    return app

"""Loopback HTTP API factory and routes."""

from __future__ import annotations

import hmac
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from krellbot import config as kb_config
from krellbot.api.jobs import (
    JOB_ERROR_NOT_FOUND,
    JOB_ERROR_RESULT_UNAVAILABLE,
    JOB_KIND_RESEARCH_BACKTEST,
    JobManager,
    QueueFull,
)
from krellbot.api.security import (
    generate_csrf_token,
    generate_session_token,
    is_loopback_host,
    is_loopback_origin,
)
from krellbot.application import alerts as alerts_app
from krellbot.application import live_gate
from krellbot.application import operations as operations_view_app
from krellbot.application import packs as app_packs
from krellbot.application.live_preflight import SandboxTransport
from krellbot.application.live_preflight import evaluate as live_preflight_evaluate
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
    jobs: JobManager = field(default=None)  # type: ignore[assignment]
    draft_service: object = field(default=None)  # StrategyDraftService singleton per home
    paper_service: object = field(default=None)  # PaperService singleton per home
    live_transport: object = field(default=None)  # SandboxTransport or test spy for live.preflight


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


def _live_transport(s: _AppState):
    """Lazily build the sandbox live transport bound to the app's home.

    Tests pre-set ``s.live_transport`` to a spy before issuing a
    ``live.preflight`` command so they can assert that ``send`` was
    never called.
    """

    if s.live_transport is None:
        s.live_transport = SandboxTransport(account="sandbox-default")
    return s.live_transport


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
        run_fills = [
            fill
            for fill in venue_fills[run["venue"]]
            if fill["pair"] == run["pair"]
        ]
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
) -> FastAPI:
    state = _AppState(
        home=Path(home),
        port=port,
        bootstrap_token=bootstrap_token,
        jobs=JobManager(home=Path(home), runner=runner),
    )

    app = FastAPI(
        title="krellbot.api",
        version=SCHEMA_VERSION,
    )
    app.state.krellbot = state

    from krellbot.api import static as _static

    _static.register(
        app,
        _resolve_dist_dir(dist_dir),
        bootstrap_token=lambda: None if state.bootstrap_used else bootstrap_token,
    )

    @app.middleware("http")
    async def _enforce_loopback_host(request: Request, call_next):
        host = request.headers.get("host", "")
        if not is_loopback_host(host, port=port):
            return JSONResponse({"detail": "loopback only"}, status_code=403)
        return await call_next(request)

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
            result = service.raise_stop(
                venue=inner["venue"],
                pair=inner["pair"],
                new_stop=Decimal(inner["new_stop"]),
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
        return JSONResponse(body, status_code=200)

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

    @app.get("/api/v1/paper/status")
    async def paper_status(request: Request) -> Response:
        """Return the closed-shape paper status projection (NS10b).

        The route uses the same session gate as ``GET /api/v1/jobs/{id}``
        (``_gate_get``): session cookie + loopback Origin + loopback Host,
        no CSRF required. The body never carries cash, quantity, stop,
        cap, or the pack path. ``mode`` is always ``"paper"`` for an
        armed record; the brief forbids a live-order control and
        forbids ``mode: live`` over the wire.
        """

        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        config = kb_config.load_config(s.home)
        if not config.armed:
            return JSONResponse(
                {"schema_version": SCHEMA_VERSION, "armed": False},
                status_code=200,
            )

        # The brief spells out a single armed-pack projection; the
        # service guarantees one armed record per (venue, pair) but a
        # workstation view reads one record. Take the first armed
        # record for the closed-shape body.
        armed = config.armed[0]
        body = {
            "schema_version": SCHEMA_VERSION,
            "armed": True,
            "venue": armed.venue,
            "pair": armed.pair,
            "entries_paused": bool(armed.entries_paused),
            "mode": armed.mode,
            "pack_id": armed.pack_id,
        }
        return JSONResponse(body, status_code=200)

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

        body = _rehearsal_service(s).status_dict()
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
        return JSONResponse(
            body, status_code=200, headers={"Cache-Control": "no-store"}
        )

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

    # ---- activation redeem (lane E) -------------------------------------

    @app.post("/api/v1/activation/redeem")
    async def redeem_activation(request: Request) -> Response:
        """Delegate to ``krellbot.ui.activate.redeem``; never echoes a key.

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

        from krellbot.ui.activate import redeem

        outcome = redeem(key, home=s.home, now=int(_now_seconds()))
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": outcome.status,
            "message": outcome.message,
            "catalog_downloaded": outcome.catalog_downloaded,
        }
        return JSONResponse(body, status_code=200)

    return app

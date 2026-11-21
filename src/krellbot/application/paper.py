"""Paper command service — the single application boundary for paper commands.

`PaperService` owns:

    paper.arm          (paper mode only — the legacy live path stays in run.arm_pack)
    paper.disarm
    paper.pause_entries
    paper.resume_entries
    paper.raise_stop
    paper.export       (read the on-disk pack bytes for an armed paper record)

Every method validates completely before mutating the armed-pack config and
returns a typed `CommandResultV1`. CLI, dashboard forms, and any future
versioned API route through this service; nothing else re-implements pause
semantics, entitlement checks, or persistence.

Command contracts:

  * `home` is explicit. A supplied `home` always wins over `KRELLBOT_HOME`
    or `Path.home()`; the service never reads the process environment to
    decide where to write.
  * `clock` is injected; the service has no internal `time.time()` call.
  * The service does NOT read the OS keyring and does NOT open a network
    transport. Paper commands are local-only.
  * `entries_paused` persists and survives `load_config`. Pause and resume
    are idempotent. Pause does NOT disarm or liquidate.
  * Invalid venue, mode, pack, balance, stop, or a live command sent here
    refuses before any config byte changes. Refusals leave `revision_after`
    equal to `revision_before`.
  * `disarm`, `pause_entries`, `resume_entries`, and `raise_stop` read the
    stored armed record and refuse with `stored_mode_not_paper` when its
    `mode` is not `paper`. The caller payload does not influence the
    stored-mode check; a missing `mode` or a `mode: paper` payload still
    refuses when the stored record is live. Live authority stays in the
    legacy CLI path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from krellbot import config as kb_config
from krellbot import secrets as kb_secrets
from krellbot.execution import reservations
from krellbot.pack import lint as kb_pack_lint

SCHEMA_VERSION = "1"

# Stable codes per contracts/commands.md v1 closed set.
CODE_ARMED = "armed"
CODE_DISARMED = "disarmed"
CODE_ENTRIES_PAUSED = "entries_paused"
CODE_ENTRIES_RESUMED = "entries_resumed"
CODE_STOP_RAISED = "stop_raised"
CODE_ALREADY_PAUSED = "already_paused"
CODE_ALREADY_RESUMED = "already_resumed"
CODE_ALREADY_ARMED = "already_armed"
CODE_NOT_ARMED = "not_armed"
CODE_INVALID_REQUEST = "invalid_request"
CODE_INVALID_PACK = "invalid_pack"
CODE_LEGACY_PACK_NOT_RUNNABLE = "legacy_pack_not_runnable"
CODE_UNKNOWN_VENUE = "unknown_venue"
CODE_PACK_HAS_NO_MARKET = "pack_has_no_market"
CODE_INVALID_BALANCE = "invalid_balance"
CODE_INVALID_STOP = "invalid_stop"
CODE_MINIMUM_NOT_MET = "minimum_not_met"
CODE_STORED_MODE_NOT_PAPER = "stored_mode_not_paper"
CODE_EXPORTED = "exported"
CODE_OVER_RESERVED = reservations.CODE_OVER_RESERVED
CODE_KILL_SWITCH_ENGAGED = "kill_switch_engaged"
CODE_USER_POLICY_DENIED = "user_policy_denied"


@dataclass(frozen=True)
class CommandResultV1:
    """Versioned paper-command result.

    `schema_version` is the literal string `"1"`. `effect` is one of
    `changed`, `unchanged`, `refused`. `revision_before` and
    `revision_after` are sha256 hex strings of the on-disk armed-pack
    config bytes; `None` when the file does not yet exist. A refusal
    leaves both revisions equal.
    """

    schema_version: str
    correlation_id: str
    code: str
    ok: bool
    message: str
    effect: str
    revision_before: str | None
    revision_after: str | None
    # Optional. Set only on ``paper.export`` so the on-disk pack bytes
    # can ship to the client. Base64 in the wire shape for JSON safety.
    pack_bytes: bytes | None = None

    def to_dict(self) -> dict:
        out = {
            "schema_version": self.schema_version,
            "correlation_id": self.correlation_id,
            "code": self.code,
            "ok": self.ok,
            "message": self.message,
            "effect": self.effect,
            "revision_before": self.revision_before,
            "revision_after": self.revision_after,
        }
        if self.pack_bytes is not None:
            out["pack_bytes_b64"] = base64.b64encode(self.pack_bytes).decode("ascii")
            out["pack_sha256"] = hashlib.sha256(self.pack_bytes).hexdigest()
            out["pack_bytes_len"] = len(self.pack_bytes)
        return out


def read_paper_state(home: Path, venue: str) -> dict:
    """Read the paper venue's state file, or return a blank state."""
    path = Path(home) / "run" / f"paper-{venue}.json"
    if not path.is_file():
        return {"venue": venue, "balances": {}, "open_orders": [], "recent_fills": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"venue": venue, "balances": {}, "open_orders": [], "recent_fills": []}


def base_quote(pair: str) -> tuple[str, str]:
    """Split a venue pair into ``(base, quote)``.

    Mirrors the paper venue's pair split so the owned-position projection
    and the engine agree on which balance is this market's holding.
    Coinbase product ids use ``BASE-QUOTE`` (wave paper arm: ``BTC-USD``);
    Binance-class compact symbols strip longer stablecoin suffixes first
    (``BTCUSDT`` → BTC/USDT); Kraken-style compact pairs like ``SUIUSD``
    strip a trailing ``USD``.
    """
    if not pair:
        return ("", "")
    if "-" in pair:
        base, _, quote = pair.partition("-")
        if base and quote and "-" not in quote:
            return base, quote
    for quote in ("USDT", "USDC", "USD"):
        if pair.endswith(quote) and len(pair) > len(quote):
            return pair[: -len(quote)], quote
    if len(pair) >= 6:
        return pair[:-3], pair[-3:]
    return pair, ""


def project_owned_position(
    home: Path,
    *,
    venue: str,
    pair: str,
    mode: str,
    as_of_run: str | None,
    starting_cash: Decimal | str | float | None = None,
) -> dict:
    """Project the owned position for one armed market from persisted state.

    Holdings are scoped to this market's base asset only. A shared venue
    wallet may hold balances for other pairs; those are never presented as
    this market's owned position. ``free_cash`` is the quote-asset balance
    string exactly as the state file persists it. When the quote balance
    is absent (just-armed, engine has not materialised ``paper-<venue>.json``
    yet), ``starting_cash`` from the armed record is projected instead of a
    false ``\"0\"``. An explicit persisted ``\"0\"`` stays ``\"0\"``.
    """
    state = read_paper_state(home, venue)
    balances = state.get("balances") or {}
    if not isinstance(balances, dict):
        balances = {}
    base, quote = base_quote(pair)
    free_cash_raw = balances.get(quote) if quote else None
    if isinstance(free_cash_raw, (str, int, float)) and str(free_cash_raw) != "":
        free_cash = str(free_cash_raw)
    elif starting_cash is not None and str(starting_cash) != "":
        free_cash = format(Decimal(str(starting_cash)), "f")
    else:
        free_cash = "0"
    holdings: list[dict] = []
    if base:
        raw = balances.get(base)
        if raw is not None:
            try:
                if Decimal(str(raw)) > 0:
                    holdings.append({"symbol": base, "qty": str(raw)})
            except (InvalidOperation, ValueError, ArithmeticError):
                pass
    return {
        "schema_version": SCHEMA_VERSION,
        "armed": True,
        "venue": venue,
        "pair": pair,
        "mode": mode,
        "free_cash": free_cash,
        "holdings": holdings,
        "as_of_run": as_of_run,
    }


# Cap for workstation chart series. Journal and fill evidence can grow
# without bound; the UI needs a bounded polyline, so we keep the first
# and last points and downsample the middle evenly when over the cap.
PAPER_CHART_MAX_POINTS = 256

# Taker fees match ``krellbot.venues.paper`` Phase-3 costs so fill replay
# for the P&L series uses the same bps the paper venue applied. Duplicated
# here so the chart projection never imports the venue risk path.
_PAPER_TAKER_BPS = {"kraken": 40, "coinbase": 120, "binance": 10, "gate": 20}


def _chart_decimal(value: object) -> str | None:
    """Finite Decimal as a plain string (no exponent / trailing zeros)."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    if not number.is_finite():
        return None
    if number.is_zero():
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _downsample_points(points: list[dict], *, max_points: int = PAPER_CHART_MAX_POINTS) -> list[dict]:
    """Keep first and last; evenly sample the middle when over the cap."""
    if len(points) <= max_points or max_points < 2:
        return points
    last_index = len(points) - 1
    # Always include endpoints; sample the remaining slots across the span.
    inner_slots = max_points - 2
    chosen = {0, last_index}
    for slot in range(inner_slots):
        # Map slot onto (1 .. last_index-1) inclusive.
        idx = 1 + round(slot * (last_index - 2) / max(inner_slots - 1, 1))
        chosen.add(min(max(idx, 1), last_index - 1))
    return [points[i] for i in sorted(chosen)]


def _read_journal_dicts(home: Path) -> list[dict]:
    """Return every parseable journal object under ``<home>/journal/*.jsonl``.

    Malformed lines and unreadable files are skipped: the chart is
    read-only evidence over an append-only journal.
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


def _position_series_from_journal(
    records: list[dict],
    *,
    venue: str,
    pair: str,
) -> list[dict]:
    """Build ``[{ts_ms, qty}, …]`` from tick ``owned_qty_after`` for one market."""
    points: list[dict] = []
    for record in records:
        if record.get("kind") != "tick":
            continue
        if record.get("venue") != venue:
            continue
        detail = record.get("detail")
        if not isinstance(detail, dict) or detail.get("pair") != pair:
            continue
        qty = _chart_decimal(detail.get("owned_qty_after"))
        if qty is None:
            continue
        ts = record.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        points.append({"ts_ms": int(ts) * 1000, "qty": qty})
    return _downsample_points(points)


def _fills_for_pair(state: dict, pair: str) -> list[dict]:
    """Return fill rows for ``pair`` with finite qty/price/ts_ms, sorted."""
    raw = state.get("recent_fills")
    if not isinstance(raw, list):
        return []
    fills: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("pair") != pair:
            continue
        side = item.get("side")
        if side not in ("buy", "sell"):
            continue
        qty = _chart_decimal(item.get("qty"))
        price = _chart_decimal(item.get("price"))
        ts_ms = item.get("ts_ms")
        if qty is None or price is None or not isinstance(ts_ms, (int, float)):
            continue
        fills.append(
            {
                "side": side,
                "qty": Decimal(qty),
                "price": Decimal(price),
                "ts_ms": int(ts_ms),
            }
        )
    fills.sort(key=lambda row: row["ts_ms"])
    return fills


def _pnl_and_mark_series(
    *,
    venue: str,
    starting_cash: Decimal,
    fills: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Replay fills into P&L + mark series (Decimal-as-string wire points).

    P&L at each fill is ``cash + qty * fill_price − starting_cash`` after
    applying that fill with the paper venue's taker fee bps. Marks are the
    fill prices themselves — evidence, never a fabricated candle series.
    """
    fee_bps = Decimal(_PAPER_TAKER_BPS.get(venue, 40))
    cash = starting_cash
    qty = Decimal(0)
    pnl_points: list[dict] = []
    mark_points: list[dict] = []

    for fill in fills:
        notional = fill["qty"] * fill["price"]
        fee = notional * fee_bps / Decimal(10_000)
        if fill["side"] == "buy":
            cash -= notional + fee
            qty += fill["qty"]
        else:
            cash += notional - fee
            qty -= fill["qty"]
        equity = cash + qty * fill["price"]
        pnl = equity - starting_cash
        pnl_text = _chart_decimal(pnl)
        price_text = _chart_decimal(fill["price"])
        if pnl_text is None or price_text is None:
            continue
        pnl_points.append({"ts_ms": fill["ts_ms"], "value": pnl_text})
        mark_points.append({"ts_ms": fill["ts_ms"], "price": price_text})

    return _downsample_points(pnl_points), _downsample_points(mark_points)


def project_paper_pnl_position_chart(home: Path) -> dict:
    """Closed-shape P&L + position (or mark) series for the armed paper market.

    * ``position`` — journal tick ``owned_qty_after`` over time for the
      armed ``(venue, pair)``.
    * ``pnl`` — fill-replay equity minus ``starting_cash`` (paper-state
      ``recent_fills`` for the armed pair).
    * ``marks`` — fill prices for the same pair (the mark series the
      milestone allows when position evidence is thin).

    When no pack is armed the body is ``{"schema_version", "armed": false}``.
    Series stay empty rather than fabricated when journal/fills are absent.
    Uses the first armed record, matching ``/api/v1/paper/position``.
    """
    home = Path(home)
    try:
        config = kb_config.load_config(home)
    except (OSError, ValueError):
        return {"schema_version": SCHEMA_VERSION, "armed": False}
    if not config.armed:
        return {"schema_version": SCHEMA_VERSION, "armed": False}

    armed = config.armed[0]
    starting_raw = armed.starting_cash
    starting_cash = Decimal(str(starting_raw)) if starting_raw is not None else Decimal(0)
    starting_text = _chart_decimal(starting_cash) or "0"

    records = _read_journal_dicts(home)
    position = _position_series_from_journal(records, venue=armed.venue, pair=armed.pair)

    state = read_paper_state(home, armed.venue)
    fills = _fills_for_pair(state, armed.pair)
    pnl, marks = _pnl_and_mark_series(
        venue=armed.venue,
        starting_cash=starting_cash,
        fills=fills,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "armed": True,
        "venue": armed.venue,
        "pair": armed.pair,
        "mode": armed.mode,
        "pack_id": armed.pack_id,
        "starting_cash": starting_text,
        "pnl": pnl,
        "position": position,
        "marks": marks,
    }


# Cap for portfolio deployment cards — same order of magnitude as the
# paper "Last runs" panel so the wire stays bounded.
PORTFOLIO_HISTORY_MAX_DEPLOYMENTS = 20


def _all_fills(state: dict) -> list[dict]:
    """Return every finite fill in ``state`` with pair/side/qty/price/ts_ms."""
    raw = state.get("recent_fills")
    if not isinstance(raw, list):
        return []
    fills: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pair = item.get("pair")
        if not isinstance(pair, str) or not pair:
            continue
        side = item.get("side")
        if side not in ("buy", "sell"):
            continue
        qty = _chart_decimal(item.get("qty"))
        price = _chart_decimal(item.get("price"))
        ts_ms = item.get("ts_ms")
        if qty is None or price is None or not isinstance(ts_ms, (int, float)):
            continue
        fills.append(
            {
                "pair": pair,
                "side": side,
                "qty": Decimal(qty),
                "price": Decimal(price),
                "ts_ms": int(ts_ms),
            }
        )
    fills.sort(key=lambda row: row["ts_ms"])
    return fills


def _venue_equity_series(
    *,
    venue: str,
    starting_cash: Decimal,
    fills: list[dict],
) -> list[dict]:
    """Replay a venue's fills into absolute equity points (cash + marks).

    Tracks per-pair qty and last mark so multi-pair wallets mark correctly
    after each fill. Fees match the paper taker bps used by the P&L chart.
    """
    fee_bps = Decimal(_PAPER_TAKER_BPS.get(venue, 40))
    cash = starting_cash
    qty_by_pair: dict[str, Decimal] = {}
    mark_by_pair: dict[str, Decimal] = {}
    points: list[dict] = []

    for fill in fills:
        pair = fill["pair"]
        notional = fill["qty"] * fill["price"]
        fee = notional * fee_bps / Decimal(10_000)
        held = qty_by_pair.get(pair, Decimal(0))
        if fill["side"] == "buy":
            cash -= notional + fee
            held += fill["qty"]
        else:
            cash += notional - fee
            held -= fill["qty"]
        qty_by_pair[pair] = held
        mark_by_pair[pair] = fill["price"]
        marked = sum(
            (qty_by_pair.get(p, Decimal(0)) * mark_by_pair.get(p, Decimal(0)) for p in qty_by_pair),
            Decimal(0),
        )
        equity_text = _chart_decimal(cash + marked)
        if equity_text is None:
            continue
        points.append({"ts_ms": fill["ts_ms"], "value": equity_text})
    return _downsample_points(points)


def _merge_venue_equity(series_by_venue: dict[str, list[dict]]) -> list[dict]:
    """Sum last-known per-venue equity at every fill timestamp across venues."""
    if not series_by_venue:
        return []
    if len(series_by_venue) == 1:
        return next(iter(series_by_venue.values()))

    events: list[tuple[int, str, Decimal]] = []
    for venue, series in series_by_venue.items():
        for point in series:
            value = _chart_decimal(point.get("value"))
            if value is None:
                continue
            events.append((int(point["ts_ms"]), venue, Decimal(value)))
    events.sort(key=lambda row: row[0])

    last: dict[str, Decimal] = {}
    merged: list[dict] = []
    for ts_ms, venue, value in events:
        last[venue] = value
        total = sum(last.values(), Decimal(0))
        text = _chart_decimal(total)
        if text is None:
            continue
        merged.append({"ts_ms": ts_ms, "value": text})
    return _downsample_points(merged)


def project_portfolio_history(home: Path) -> dict:
    """Closed-shape cross-deployment portfolio history from journal + fills.

    * ``deployments`` — one row per ``(venue, pack, pair)`` the journal
      records (plus currently armed markets with no ticks yet), newest
      ``last_ts_ms`` first, capped at ``PORTFOLIO_HISTORY_MAX_DEPLOYMENTS``.
      Pair-scoped ``pnl`` / ``last_pnl`` appear only when ``starting_cash``
      is known from the armed config for that market.
    * ``equity`` — absolute portfolio equity over time from venue-level
      fill replay (shared paper wallet per venue; multi-venue series are
      summed by last-known carry). Empty when no starting cash is known
      or no fills exist — never a fabricated flat zero series.

    Read-only. Does not invent Learn/marketing sample bots or touch
    telemetry consent.
    """
    home = Path(home)
    try:
        config = kb_config.load_config(home)
    except (OSError, ValueError):
        config = kb_config.Config()

    armed_by_market: dict[tuple[str, str], kb_config.ArmedPack] = {}
    for armed in config.armed:
        armed_by_market[(armed.venue, armed.pair)] = armed

    deployments: dict[tuple[str, str, str], dict] = {}
    for record in _read_journal_dicts(home):
        if record.get("kind") != "tick":
            continue
        venue = record.get("venue")
        pack_id = record.get("pack")
        if not isinstance(venue, str) or not isinstance(pack_id, str) or not pack_id:
            continue
        detail = record.get("detail")
        pair = detail.get("pair") if isinstance(detail, dict) else None
        if not isinstance(pair, str) or not pair:
            continue
        ts = record.get("ts")
        ts_ms = int(ts) * 1000 if isinstance(ts, (int, float)) else 0
        key = (venue, pack_id, pair)
        row = deployments.setdefault(
            key,
            {
                "venue": venue,
                "pair": pair,
                "pack_id": pack_id,
                "mode": "paper",
                "status": "closed",
                "starting_cash": None,
                "fills_total": 0,
                "first_ts_ms": ts_ms,
                "last_ts_ms": ts_ms,
                "last_pnl": None,
                "pnl": [],
            },
        )
        row["first_ts_ms"] = min(row["first_ts_ms"], ts_ms)
        row["last_ts_ms"] = max(row["last_ts_ms"], ts_ms)

    for armed in config.armed:
        key = (armed.venue, armed.pack_id, armed.pair)
        row = deployments.setdefault(
            key,
            {
                "venue": armed.venue,
                "pair": armed.pair,
                "pack_id": armed.pack_id,
                "mode": armed.mode,
                "status": "active",
                "starting_cash": None,
                "fills_total": 0,
                "first_ts_ms": int(armed.armed_at_ts) * 1000 if armed.armed_at_ts else 0,
                "last_ts_ms": int(armed.armed_at_ts) * 1000 if armed.armed_at_ts else 0,
                "last_pnl": None,
                "pnl": [],
            },
        )
        row["status"] = "active"
        row["mode"] = armed.mode
        if armed.starting_cash is not None:
            row["starting_cash"] = _chart_decimal(armed.starting_cash)

    venue_states: dict[str, dict] = {}
    venue_start: dict[str, Decimal] = {}

    for row in deployments.values():
        armed = armed_by_market.get((row["venue"], row["pair"]))
        if armed is not None and armed.starting_cash is not None:
            cash = Decimal(str(armed.starting_cash))
            row["starting_cash"] = _chart_decimal(cash)
            prior = venue_start.get(row["venue"])
            if prior is None or cash > prior:
                venue_start[row["venue"]] = cash

        if row["venue"] not in venue_states:
            venue_states[row["venue"]] = read_paper_state(home, row["venue"])
        state = venue_states[row["venue"]]
        pair_fills = _fills_for_pair(state, row["pair"])
        row["fills_total"] = len(pair_fills)
        if pair_fills:
            first_fill_ts = pair_fills[0]["ts_ms"]
            last_fill_ts = pair_fills[-1]["ts_ms"]
            if row["first_ts_ms"] == 0:
                row["first_ts_ms"] = first_fill_ts
            else:
                row["first_ts_ms"] = min(row["first_ts_ms"], first_fill_ts)
            row["last_ts_ms"] = max(row["last_ts_ms"], last_fill_ts)

        if row["starting_cash"] is None:
            continue
        pnl, _marks = _pnl_and_mark_series(
            venue=row["venue"],
            starting_cash=Decimal(row["starting_cash"]),
            fills=pair_fills,
        )
        row["pnl"] = pnl
        if pnl:
            row["last_pnl"] = pnl[-1]["value"]

    series_by_venue: dict[str, list[dict]] = {}
    for venue, starting in venue_start.items():
        state = venue_states.get(venue) or read_paper_state(home, venue)
        series_by_venue[venue] = _venue_equity_series(
            venue=venue,
            starting_cash=starting,
            fills=_all_fills(state),
        )

    body_deployments = sorted(
        deployments.values(),
        key=lambda row: row["last_ts_ms"],
        reverse=True,
    )[:PORTFOLIO_HISTORY_MAX_DEPLOYMENTS]

    return {
        "schema_version": SCHEMA_VERSION,
        "equity": _merge_venue_equity(series_by_venue),
        "deployments": body_deployments,
    }


# Cap keeps the wire bounded while preserving oldest→newest order for
# outsider reproduction (drop the newest surplus, never reverse).
FORWARD_PAPER_LEDGER_MAX_EVENTS = 5000
_FORWARD_PAPER_LEDGER_KIND_ORDER = {"arm": 0, "tick": 1, "fill": 2, "refusal": 3}
FORWARD_PAPER_LEDGER_DISCLAIMER = "Paper evidence — not live P&L"


def _forward_ledger_refusal_code(detail: dict) -> str | None:
    """Return the refusal code a tick detail carries, else ``None``.

    Matches the paper-history refusal keys: ``code``, ``intent_refused``,
    ``metadata_refusal``. A plain decision ``reason`` is not a refusal.
    """

    for key in ("code", "intent_refused", "metadata_refusal"):
        value = detail.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _forward_ledger_safe_detail(detail: object) -> dict:
    """Drop export secret fields from a tick detail for the ledger wire."""

    from krellbot import journal as kb_journal

    if not isinstance(detail, dict):
        return {}
    cleaned = kb_journal.drop_export_secret_fields(detail)
    return cleaned if isinstance(cleaned, dict) else {}


def project_forward_paper_ledger(home: Path) -> dict:
    """Forward (oldest→newest) paper evidence ledger for outsider reproduction.

    Projects journal-backed ticks and refusals, paper-state fills, and
    paper-mode arm records into a single chronological ``events`` list.
    Never fabricates live P&L: fill qty/price and owned cash stay off the
    wire; the body is labeled ``mode: paper`` / ``presentation:
    local_evidence``. Read-only over ``<home>/journal`` +
    ``<home>/run/paper-*.json`` + paper armed config.
    """

    home = Path(home)
    events: list[dict] = []

    try:
        config = kb_config.load_config(home)
    except (OSError, ValueError):
        config = kb_config.Config()

    for armed in config.armed:
        if armed.mode != "paper":
            continue
        pack_version = armed.pack_version
        detail: dict = {"mode": "paper"}
        if isinstance(pack_version, str) and pack_version:
            detail["pack_version"] = pack_version
        events.append(
            {
                "ts": int(armed.armed_at_ts) if armed.armed_at_ts else 0,
                "kind": "arm",
                "venue": armed.venue,
                "pack": armed.pack_id,
                "pair": armed.pair,
                "detail": detail,
            }
        )

    for record in _read_journal_dicts(home):
        if record.get("kind") != "tick":
            continue
        venue = record.get("venue")
        pack_id = record.get("pack")
        if not isinstance(venue, str) or not isinstance(pack_id, str):
            continue
        raw_detail = record.get("detail")
        detail = raw_detail if isinstance(raw_detail, dict) else {}
        pair = detail.get("pair")
        pair_text = pair if isinstance(pair, str) and pair else None
        ts = record.get("ts")
        ts_value = int(ts) if isinstance(ts, (int, float)) else 0
        safe_detail = _forward_ledger_safe_detail(detail)
        events.append(
            {
                "ts": ts_value,
                "kind": "tick",
                "venue": venue,
                "pack": pack_id,
                "pair": pair_text,
                "detail": safe_detail,
            }
        )
        refusal = _forward_ledger_refusal_code(detail)
        if refusal is not None:
            events.append(
                {
                    "ts": ts_value,
                    "kind": "refusal",
                    "venue": venue,
                    "pack": pack_id,
                    "pair": pair_text,
                    "detail": {"code": refusal},
                }
            )

    run_dir = home / "run"
    if run_dir.is_dir():
        for path in sorted(run_dir.glob("paper-*.json")):
            name = path.name
            if not (name.startswith("paper-") and name.endswith(".json")):
                continue
            venue = name[len("paper-") : -len(".json")]
            if not venue:
                continue
            state = read_paper_state(home, venue)
            raw_fills = state.get("recent_fills")
            if not isinstance(raw_fills, list):
                continue
            for item in raw_fills:
                if not isinstance(item, dict):
                    continue
                pair = item.get("pair")
                if not isinstance(pair, str) or not pair:
                    continue
                side = item.get("side")
                if side not in ("buy", "sell"):
                    continue
                ts_ms = item.get("ts_ms")
                if not isinstance(ts_ms, (int, float)):
                    continue
                ts_ms_int = int(ts_ms)
                coid = item.get("coid", item.get("id", ""))
                events.append(
                    {
                        "ts": ts_ms_int // 1000,
                        "kind": "fill",
                        "venue": venue,
                        "pack": "",
                        "pair": pair,
                        "detail": {
                            "coid": str(coid) if coid is not None else "",
                            "side": side,
                            "ts_ms": ts_ms_int,
                        },
                    }
                )

    events.sort(
        key=lambda row: (
            int(row["ts"]),
            _FORWARD_PAPER_LEDGER_KIND_ORDER.get(str(row["kind"]), 99),
            str(row.get("venue") or ""),
            str(row.get("pack") or ""),
            str(row.get("pair") or ""),
        )
    )
    if len(events) > FORWARD_PAPER_LEDGER_MAX_EVENTS:
        events = events[:FORWARD_PAPER_LEDGER_MAX_EVENTS]

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "paper",
        "order": "forward",
        "presentation": "local_evidence",
        "disclaimer": FORWARD_PAPER_LEDGER_DISCLAIMER,
        "events": events,
    }


def _revision(home: Path) -> str | None:
    path = kb_config.config_path(home)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_pair(pack_path: Path, venue: str) -> str:
    """Return the pack's pair for `venue`. Mirrors `run.arm_pack`'s lookup.

    The service does not read the engine's private state — it re-reads
    the same pack file the engine just validated. Raises if the pack
    has no market for the venue; the caller is responsible for mapping
    that case to a refusal before persistence would have happened.
    """
    try:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    markets = data.get("markets") or []
    market = next((m for m in markets if m.get("venue") == venue), None)
    if market is None:
        return ""
    return str(market.get("pair", ""))


def _resolve_cap(pack_path: Path) -> Decimal | None:
    """Return the pack's `risk.max_account_pct` as a Decimal.

    Mirrors the engine's lookup in `run.arm_pack`. Returns None when
    the pack is missing or malformed; the caller treats None as "skip
    the over-reserve check" and lets the existing run.arm_pack
    validation classify the input.
    """
    try:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    risk = data.get("risk") or {}
    if not isinstance(risk, dict):
        return None
    raw = risk.get("max_account_pct", None)
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError):
        return None


def _classify_invalid_input(pack_path: Path, venue: str) -> tuple[str, str]:
    """Map an `rc=2` (invalid input) refusal to a specific code + message.

    `run.arm_pack` returns 2 for any input failure but does not expose
    which one. The service classifies by re-reading the pack file the
    engine just looked at; this is presentation logic only and does
    not change the engine's on-disk refusal contract.
    """
    if not pack_path.exists():
        return CODE_INVALID_REQUEST, "pack file not found"
    try:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return CODE_INVALID_PACK, "pack JSON parse error"
    if not isinstance(data, dict):
        return CODE_INVALID_PACK, "pack must be a JSON object"
    if kb_pack_lint.is_legacy(data):
        return CODE_LEGACY_PACK_NOT_RUNNABLE, "legacy packs are not runnable"
    errors = kb_pack_lint.check(data)
    if errors:
        return CODE_INVALID_PACK, "pack validation failed"
    pair = _resolve_pair(pack_path, venue)
    if not pair:
        return CODE_PACK_HAS_NO_MARKET, f"pack has no market for {venue}"
    return CODE_INVALID_REQUEST, "invalid input refused by paper service"


def _now_seconds_default() -> float:
    return time.time()


class PaperService:
    """Single application-service boundary for paper commands."""

    def __init__(self, home: Path, *, clock: Callable[[], float] | None = None) -> None:
        self._home = Path(home)
        self._clock = clock or _now_seconds_default

    @property
    def home(self) -> Path:
        return self._home

    # ---- arm -------------------------------------------------------------

    def arm(
        self,
        pack_path: Path,
        *,
        venue: str,
        mode: str,
        paper_balance: Decimal | None,
        correlation_id: str = "",
        requires_license: bool | None = None,
    ) -> CommandResultV1:
        """Arm a pack in paper mode.

        The service is the boundary; the engine's ``run.arm_pack``
        remains the single authority for live key checks, pack-shape
        validation, and the costmin check (so the existing live path
        and the existing engine guarantees are unchanged). Live typed
        ``LIVE`` confirmation is the workstation grant + ``skip_confirm``
        seam, not a CLI stdin prompt. For paper mode the service runs
        its own validation, then delegates to ``run.arm_pack`` with
        ``home=self._home`` so the persistence and the on-disk
        record are byte-identical to what the engine produces.

        Refuses a `mode=live` request before any config byte changes.
        """
        rev_before = _revision(self._home)

        if mode != "paper":
            return self._refusal(
                CODE_INVALID_REQUEST,
                "live arm is not handled by the paper service",
                correlation_id,
                rev_before,
            )

        from krellbot.application import user_policy as kb_user_policy

        policy = kb_user_policy.ensure_allowed(self._home, kb_user_policy.ACTION_PAPER_ARM)
        if not policy.ok:
            return self._refusal(
                CODE_USER_POLICY_DENIED,
                policy.message,
                correlation_id,
                rev_before,
            )

        from krellbot.application import live_gate as kb_live_gate

        if kb_live_gate.kill_state(self._home).engaged:
            return self._refusal(
                CODE_KILL_SWITCH_ENGAGED,
                "kill switch engaged; paper arm refused",
                correlation_id,
                rev_before,
            )

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        if paper_balance is None:
            return self._refusal(
                CODE_INVALID_BALANCE,
                "paper arm requires --paper-balance",
                correlation_id,
                rev_before,
            )
        if not paper_balance.is_finite():
            return self._refusal(CODE_INVALID_BALANCE, "paper-balance must be finite", correlation_id, rev_before)
        if paper_balance <= Decimal(0):
            return self._refusal(
                CODE_INVALID_BALANCE,
                "paper-balance must be positive",
                correlation_id,
                rev_before,
            )

        try:
            cap = _resolve_cap(pack_path)
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            cap = None

        if (
            cap is not None
            and cap > Decimal(0)
            and reservations.would_over_reserve(
                self._home,
                new_starting_cash=paper_balance,
                new_cap=cap,
            )
        ):
            return self._refusal(
                CODE_OVER_RESERVED,
                "combined paper reservation would exceed account cash",
                correlation_id,
                rev_before,
            )

        # Delegate the actual arm to ``run.arm_pack`` so the existing
        # engine guarantees (pack-shape validation, costmin check,
        # costmin refusal) and the on-disk record stay identical.
        # We pass ``home=self._home`` so persistence lands in the
        # supplied home, not in whatever ``KRELLBOT_HOME`` happens to
        # be at process start.
        from krellbot import run as kb_run

        rc = kb_run.arm_pack(
            pack_path,
            venue=venue,
            mode=mode,
            paper_balance=paper_balance,
            requires_license=requires_license,
            home=self._home,
        )

        rev_after = _revision(self._home)

        if rc == 0:
            # Build the typed message from the on-disk record when one
            # is present (the production path). The record MAY be
            # absent in tests that monkeypatch ``run.arm_pack`` with a
            # spy that returns 0 without persisting — the service still
            # trusts the rc and emits a typed success result.
            config = kb_config.load_config(self._home)
            pair = _resolve_pair(pack_path, venue)
            armed = kb_config.find_armed(config, venue, pair) if pair else None
            if armed is not None:
                message = f"armed {armed.pack_id} {armed.pack_version} on {venue} {armed.pair}"
            else:
                message = f"armed {venue} {pair or '?'}"
            # Library packs (under <home>/packs/) get a deployed sidecar
            # so the pack-library classifier matches the arm flow. Use
            # the armed record's pack_id (never open the caller path).
            if armed is not None and isinstance(armed.pack_id, str) and armed.pack_id:
                from krellbot.application import pack_library as pack_library_app

                if pack_library_app.is_library_pack_path(pack_path):
                    try:
                        pack_library_app.mark_deployed(
                            self._home,
                            armed.pack_id,
                            now=int(self._clock()),
                        )
                    except pack_library_app.InstallRefused:
                        pass
            return CommandResultV1(
                schema_version=SCHEMA_VERSION,
                correlation_id=correlation_id,
                code=CODE_ARMED,
                ok=True,
                message=message,
                effect="changed",
                revision_before=rev_before,
                revision_after=rev_after,
            )
        if rc == 1:
            # State refusal. Distinguish already-armed from costmin by
            # inspecting the current config (costmin leaves no record;
            # already-armed leaves the record unchanged).
            pair = _resolve_pair(pack_path, venue)
            config = kb_config.load_config(self._home)
            armed = kb_config.find_armed(config, venue, pair)
            if armed is not None:
                return self._refusal(
                    CODE_ALREADY_ARMED,
                    f"already armed: {venue} {pair}",
                    correlation_id,
                    rev_before,
                )
            return self._refusal(
                CODE_MINIMUM_NOT_MET,
                "cap cannot meet the pair minimum",
                correlation_id,
                rev_before,
            )
        # rc == 2: invalid input — pack shape / venue / balance. The
        # service has already enforced the balance branch; anything
        # reaching this return is pack-shape. ``rev_after == rev_before``
        # proves no byte changed. Classify to a specific code so the
        # adapter can render the right reason.
        code, msg = _classify_invalid_input(pack_path, venue)
        return self._refusal(code, msg, correlation_id, rev_before)

    # ---- disarm ----------------------------------------------------------

    def disarm(self, *, venue: str, pair: str, correlation_id: str = "") -> CommandResultV1:
        rev_before = _revision(self._home)

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        config = kb_config.load_config(self._home)
        armed = kb_config.find_armed(config, venue, pair)
        if armed is None:
            return self._refusal(
                CODE_NOT_ARMED,
                f"not armed: {venue} {pair}",
                correlation_id,
                rev_before,
            )

        # F01: paper commands read the stored record's mode and refuse to
        # mutate a non-paper target. The caller payload does not override
        # this check; live authority stays in the legacy CLI path.
        if armed.mode != "paper":
            return self._refusal(
                CODE_STORED_MODE_NOT_PAPER,
                f"stored mode is {armed.mode!r}; paper service only mutates paper targets",
                correlation_id,
                rev_before,
            )

        disarmed_pack_id = armed.pack_id
        config.armed = [a for a in config.armed if not (a.venue == venue and a.pair == pair)]
        kb_config.save_config(self._home, config)

        # Still-armed copies of the same pack keep the deployed marker;
        # only demote when this pack_id is no longer armed anywhere.
        still_armed = any(a.pack_id == disarmed_pack_id for a in config.armed)
        if not still_armed and isinstance(disarmed_pack_id, str) and disarmed_pack_id:
            from krellbot.application import pack_library as pack_library_app

            pack_library_app.demote_deployed_to_configured(
                self._home,
                disarmed_pack_id,
                now=int(self._clock()),
            )

        rev_after = _revision(self._home)

        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=CODE_DISARMED,
            ok=True,
            message=f"disarmed {venue} {pair}",
            effect="changed",
            revision_before=rev_before,
            revision_after=rev_after,
        )

    # ---- pause / resume --------------------------------------------------

    def pause_entries(self, *, venue: str, pair: str, correlation_id: str = "") -> CommandResultV1:
        return self._set_entries_paused(venue=venue, pair=pair, paused=True, correlation_id=correlation_id)

    def resume_entries(self, *, venue: str, pair: str, correlation_id: str = "") -> CommandResultV1:
        return self._set_entries_paused(venue=venue, pair=pair, paused=False, correlation_id=correlation_id)

    def _set_entries_paused(self, *, venue: str, pair: str, paused: bool, correlation_id: str) -> CommandResultV1:
        with kb_config._paper_command_transaction(self._home) as acquired:
            if not acquired:
                return self._refusal(
                    CODE_INVALID_REQUEST,
                    "another paper command is updating config",
                    correlation_id,
                    _revision(self._home),
                )
            return self._set_entries_paused_locked(venue=venue, pair=pair, paused=paused, correlation_id=correlation_id)

    def _set_entries_paused_locked(
        self, *, venue: str, pair: str, paused: bool, correlation_id: str
    ) -> CommandResultV1:
        rev_before = _revision(self._home)

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        config = kb_config.load_config(self._home)
        armed = kb_config.find_armed(config, venue, pair)
        if armed is None:
            return self._refusal(
                CODE_NOT_ARMED,
                f"not armed: {venue} {pair}",
                correlation_id,
                rev_before,
            )

        # F01: refuse before any byte change. The caller payload does not
        # override the stored-mode check.
        if armed.mode != "paper":
            return self._refusal(
                CODE_STORED_MODE_NOT_PAPER,
                f"stored mode is {armed.mode!r}; paper service only mutates paper targets",
                correlation_id,
                rev_before,
            )

        if armed.entries_paused == paused:
            if paused:
                code, msg = CODE_ALREADY_PAUSED, f"already paused: {venue} {pair}"
            else:
                code, msg = CODE_ALREADY_RESUMED, f"already resumed: {venue} {pair}"
            return CommandResultV1(
                schema_version=SCHEMA_VERSION,
                correlation_id=correlation_id,
                code=code,
                ok=True,
                message=msg,
                effect="unchanged",
                revision_before=rev_before,
                revision_after=rev_before,
            )

        armed.entries_paused = paused
        kb_config.save_config(self._home, config)
        rev_after = _revision(self._home)

        if paused:
            code, msg = CODE_ENTRIES_PAUSED, f"entries paused: {venue} {pair}"
        else:
            code, msg = CODE_ENTRIES_RESUMED, f"entries resumed: {venue} {pair}"

        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=code,
            ok=True,
            message=msg,
            effect="changed",
            revision_before=rev_before,
            revision_after=rev_after,
        )

    # ---- raise stop ------------------------------------------------------

    def raise_stop(
        self,
        *,
        venue: str,
        pair: str,
        new_stop: Decimal,
        correlation_id: str = "",
    ) -> CommandResultV1:
        with kb_config._paper_command_transaction(self._home) as acquired:
            if not acquired:
                return self._refusal(
                    CODE_INVALID_REQUEST,
                    "another paper command is updating config",
                    correlation_id,
                    _revision(self._home),
                )
            return self._raise_stop_locked(venue=venue, pair=pair, new_stop=new_stop, correlation_id=correlation_id)

    def _raise_stop_locked(
        self,
        *,
        venue: str,
        pair: str,
        new_stop: Decimal,
        correlation_id: str,
    ) -> CommandResultV1:
        rev_before = _revision(self._home)

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        config = kb_config.load_config(self._home)
        armed = kb_config.find_armed(config, venue, pair)
        if armed is None:
            return self._refusal(
                CODE_NOT_ARMED,
                f"not armed: {venue} {pair}",
                correlation_id,
                rev_before,
            )

        # F01: refuse before any byte change. The caller payload does not
        # override the stored-mode check.
        if armed.mode != "paper":
            return self._refusal(
                CODE_STORED_MODE_NOT_PAPER,
                f"stored mode is {armed.mode!r}; paper service only mutates paper targets",
                correlation_id,
                rev_before,
            )

        if not new_stop.is_finite():
            return self._refusal(CODE_INVALID_STOP, "new stop must be finite", correlation_id, rev_before)
        if new_stop <= armed.stop:
            return self._refusal(
                CODE_INVALID_STOP,
                "new stop must be strictly above the current stop",
                correlation_id,
                rev_before,
            )

        armed.stop = new_stop
        kb_config.save_config(self._home, config)
        rev_after = _revision(self._home)

        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=CODE_STOP_RAISED,
            ok=True,
            message=f"stop set: {venue} {pair} -> {new_stop}",
            effect="changed",
            revision_before=rev_before,
            revision_after=rev_after,
        )

    # ---- export ----------------------------------------------------------

    def export(
        self,
        *,
        venue: str,
        pair: str,
        correlation_id: str = "",
    ) -> CommandResultV1:
        """Return the on-disk pack bytes for the armed (venue, pair) record.

        The workstation uses this to ship the same bytes the engine
        currently has armed — the canonical pack the user uploaded. The
        method refuses when no record exists, the venue is unknown, or
        the stored mode is not paper (the legacy live path owns live
        export). On success ``pack_bytes`` carries the verbatim file
        bytes; ``effect`` is ``unchanged`` so callers can distinguish
        a read from a write.
        """

        rev = _revision(self._home)

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev,
            )

        config = kb_config.load_config(self._home)
        armed = kb_config.find_armed(config, venue, pair)
        if armed is None:
            return self._refusal(
                CODE_NOT_ARMED,
                f"not armed: {venue} {pair}",
                correlation_id,
                rev,
            )

        if armed.mode != "paper":
            return self._refusal(
                CODE_STORED_MODE_NOT_PAPER,
                f"stored mode is {armed.mode!r}; paper service only exports paper targets",
                correlation_id,
                rev,
            )

        pack_path = Path(armed.pack_path)
        try:
            pack_bytes = pack_path.read_bytes()
        except OSError:
            return self._refusal(
                CODE_INVALID_PACK,
                f"pack file unreadable: {pack_path}",
                correlation_id,
                rev,
            )

        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=CODE_EXPORTED,
            ok=True,
            message=f"exported {venue} {pair}",
            effect="unchanged",
            revision_before=rev,
            revision_after=rev,
            pack_bytes=pack_bytes,
        )

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _refusal(
        code: str,
        message: str,
        correlation_id: str,
        revision: str | None,
    ) -> CommandResultV1:
        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=code,
            ok=False,
            message=message,
            effect="refused",
            revision_before=revision,
            revision_after=revision,
        )

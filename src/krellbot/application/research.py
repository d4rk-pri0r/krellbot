"""Research service — the callable boundary for a v1 backtest.

`ResearchService` is the application-layer entry point for research requests.
The CLI `backtest` command delegates to it so the existing stdout sentences,
the `--json` receipt shape, and the exit codes stay byte-identical, and any
future adapter (GUI, versioned API) can call the same boundary.

Strategy compatibility contracts:

  * `home` is explicit. A supplied home always wins over `KRELLBOT_HOME`
    and `Path.home()`. The service never reads the process environment
    to decide where to look.
  * `fetch` is an optional injected callable with signature
    `(venue, pair, tf) -> list[Candle]`. A `None` fetch means offline:
    zero network calls and zero keyring reads.
  * The service never reads the OS keyring and never opens a network
    transport on its own. With `dataset_csv` set, no fetch happens; with
    `fetch=None` set and `dataset_csv` missing, the request refuses.
  * Result is a typed `ResearchResult` with `legacy_receipt` (exactly the
    locked key set) and a separate `detail` object with
    `schema_version: "1"` plus a minimal decision trace. No trace field
    lives inside `legacy_receipt`.
  * The trace explains evaluator output, not venue execution or fill
    certainty. Warmup/unknown is a separate state from false and from
    numeric zero. Values only ever come from bars at or before `bar_ts`.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from pathlib import Path

from krellbot.backtest.engine import Backtester
from krellbot.backtest.receipt import build_receipt
from krellbot.data import TF_MS, GapError, check_gaps
from krellbot.data.cache import _parse_csv, sha256_bytes
from krellbot.domain.trace import shared_decision_trace
from krellbot.pack import lint as kb_pack_lint
from krellbot.pack.model import Candle
from krellbot.research.holdout import HoldoutOverlap, assert_disjoint
from krellbot.strategy_ir.availability import FutureData
from krellbot.strategy_ir.v1 import prepare_v1

SCHEMA_VERSION = "1"

CODE_OK = "ok"
CODE_MISSING_PACK = "missing_pack"
CODE_INVALID_PACK = "invalid_pack"
CODE_LEGACY_PACK_NOT_RUNNABLE = "legacy_pack_not_runnable"
CODE_PACK_HAS_NO_MARKET = "pack_has_no_market"
CODE_UNKNOWN_VENUE = "unknown_venue"
CODE_UNSUPPORTED_TIMEFRAME = "unsupported_timeframe"
CODE_GAPPED_DATA = "gapped_data"
CODE_EMPTY_DATASET = "empty_dataset"
CODE_NO_DATASET_AND_NO_FETCH = "no_dataset_and_no_fetch"
CODE_INVALID_DATASET = "invalid_dataset"
CODE_INVALID_HOLDOUT = "invalid_holdout"
CODE_HOLDOUT_OVERLAP = "holdout_overlap"
CODE_FUTURE_DATA = "future_data"
CODE_INVALID_NODES = "invalid_nodes"
CODE_NUMERIC_OUT_OF_RANGE = "numeric_out_of_range"

NUMERIC_OUT_OF_RANGE_MESSAGE = "backtest equity exceeded the supported numeric range (1e20)"


FetchFn = Callable[[str, str, str], list[Candle]]


@dataclass(frozen=True)
class ResearchRequest:
    """One v1 research request.

    Either `dataset_csv` is supplied (offline by data) or an injected `fetch`
    is bound on the service and `dataset_csv` is left None.
    """

    pack_path: Path
    venue: str
    pair: str | None = None
    timeframe: str | None = None
    dataset_csv: Path | None = None
    starting_cash: Decimal = Decimal(10000)
    fee_bps: int | None = None
    slippage_bps: int | None = None
    slippage_mult: float | None = None
    from_ms: int | None = None
    to_ms: int | None = None
    holdout_from_ms: int | None = None
    holdout_to_ms: int | None = None
    allow_gaps: bool = False
    nodes: list | None = None


@dataclass(frozen=True)
class ResearchResult:
    """Versioned research result.

    `legacy_receipt` is the byte-compatible CLI receipt shape (or None on a
    refusal). `detail` is the versioned object that carries the refusal code
    or the decision trace; it is always present and starts with
    `schema_version: "1"`.
    """

    ok: bool
    legacy_receipt: dict | None
    detail: dict = field(default_factory=dict)
    refusal: dict | None = None


class ResearchService:
    """Callable v1 research boundary.

    The service has no internal `time.time()`, no internal keyring call,
    and no internal HTTP call. The only environment reading is the
    supplied `home`; the only external I/O is the optional `fetch`
    callable and the explicit `dataset_csv`.
    """

    def __init__(self, home: Path, *, fetch: FetchFn | None = None) -> None:
        self._home = Path(home)
        self._fetch = fetch

    @property
    def home(self) -> Path:
        return self._home

    # ---- public ----------------------------------------------------------

    def run(self, request: ResearchRequest) -> ResearchResult:
        """Run a research request and return a typed result.

        The return is always a `ResearchResult`; refusals come back with
        `ok=False`, `legacy_receipt=None`, and `detail["refusal"]` set.
        Successes come back with `ok=True`, the locked `legacy_receipt`,
        and `detail["trace"]` populated.
        """
        refusal = self._validate_request(request)
        if refusal is not None:
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        pack = self._load_pack(request.pack_path)
        if pack is None:
            refusal = {
                "code": CODE_MISSING_PACK,
                "message": f"pack file not found: {request.pack_path}",
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        if kb_pack_lint.is_legacy(pack):
            refusal = {
                "code": CODE_LEGACY_PACK_NOT_RUNNABLE,
                "message": "legacy packs are not runnable",
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        errors = kb_pack_lint.check(pack)
        if errors:
            refusal = {
                "code": CODE_INVALID_PACK,
                "message": "pack validation failed",
                "errors": errors,
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        pair = self._resolve_pair(pack, request.venue)
        if pair is None:
            refusal = {
                "code": CODE_PACK_HAS_NO_MARKET,
                "message": f"pack has no market for {request.venue}",
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        timeframe = request.timeframe or pack.get("timeframe") or ""
        if timeframe not in TF_MS:
            refusal = {
                "code": CODE_UNSUPPORTED_TIMEFRAME,
                "message": f"unsupported timeframe: {timeframe!r}",
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        fee_bps = int(request.fee_bps) if request.fee_bps is not None else self._default_fee(request.venue)
        slippage_bps = int(request.slippage_bps) if request.slippage_bps is not None else 5
        slippage_mult = float(request.slippage_mult) if request.slippage_mult is not None else 1.0

        candles, manifest_sha, refusal = self._resolve_candles(request, venue=request.venue, pair=pair, tf=timeframe)
        if refusal is not None:
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )
        assert candles is not None and manifest_sha is not None

        if request.from_ms is not None:
            candles = [c for c in candles if c.ts_ms >= int(request.from_ms)]
        if request.to_ms is not None:
            candles = [c for c in candles if c.ts_ms <= int(request.to_ms)]
        if not candles:
            refusal = {
                "code": CODE_EMPTY_DATASET,
                "message": f"no candles after filtering (pair={pair})",
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        if request.holdout_from_ms is not None or request.holdout_to_ms is not None:
            if (
                request.holdout_from_ms is None
                or request.holdout_to_ms is None
                or type(request.holdout_from_ms) is not int
                or type(request.holdout_to_ms) is not int
            ):
                refusal = {
                    "code": CODE_INVALID_HOLDOUT,
                    "message": "holdout bounds must be a pair of ints",
                }
                return ResearchResult(
                    ok=False,
                    legacy_receipt=None,
                    detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                    refusal=refusal,
                )
            scored_from = candles[0].ts_ms
            scored_to = candles[-1].ts_ms
            try:
                assert_disjoint(
                    scored_from,
                    scored_to,
                    int(request.holdout_from_ms),
                    int(request.holdout_to_ms),
                )
            except HoldoutOverlap:
                refusal = {
                    "code": CODE_HOLDOUT_OVERLAP,
                    "message": "scored window overlaps the holdout window",
                }
                return ResearchResult(
                    ok=False,
                    legacy_receipt=None,
                    detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                    refusal=refusal,
                )

        nodes = request.nodes if request.nodes is not None else []
        if not isinstance(nodes, list):
            refusal = {
                "code": CODE_INVALID_NODES,
                "message": "nodes must be a list when present",
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )
        decision_bar = len(candles) - 1
        evaluated: dict = {}
        runners: list[Backtester] = []

        def _evaluate(stripped: dict) -> list:
            evaluated["pack"] = stripped
            runner = Backtester(
                stripped,
                candles,
                starting_cash=Decimal(request.starting_cash),
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                slippage_mult=slippage_mult,
            )
            runners.append(runner)
            return runner.run()

        try:
            records = prepare_v1(pack, nodes, decision_bar, _evaluate)
        except FutureData as exc:
            refusal = {
                "code": CODE_FUTURE_DATA,
                "message": str(exc),
                "node_id": exc.node_id,
                "index": exc.index,
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )
        except (DecimalException, OverflowError):
            refusal = {
                "code": CODE_NUMERIC_OUT_OF_RANGE,
                "message": NUMERIC_OUT_OF_RANGE_MESSAGE,
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )
        bt = runners[0]
        receipt_pack = evaluated["pack"]
        try:
            receipt = build_receipt(
                pack=receipt_pack,
                records=records,
                trade_count=bt.trade_count,
                data_manifest_sha256=manifest_sha,
                venue=request.venue,
                pair=pair,
                tf=timeframe,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                slippage_mult=slippage_mult,
                starting_cash=Decimal(request.starting_cash),
            )
        except (DecimalException, OverflowError):
            refusal = {
                "code": CODE_NUMERIC_OUT_OF_RANGE,
                "message": NUMERIC_OUT_OF_RANGE_MESSAGE,
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        if _receipt_has_non_finite(receipt):
            refusal = {
                "code": CODE_NUMERIC_OUT_OF_RANGE,
                "message": NUMERIC_OUT_OF_RANGE_MESSAGE,
            }
            return ResearchResult(
                ok=False,
                legacy_receipt=None,
                detail={"schema_version": SCHEMA_VERSION, "refusal": refusal},
                refusal=refusal,
            )

        trace = self._build_trace(receipt_pack, candles)
        detail = {
            "schema_version": SCHEMA_VERSION,
            "venue": request.venue,
            "pair": pair,
            "tf": timeframe,
            "bar_count": len(candles),
            "trade_count": bt.trade_count,
            "trace": trace,
        }
        return ResearchResult(ok=True, legacy_receipt=receipt, detail=detail, refusal=None)

    # ---- validation ------------------------------------------------------

    def _validate_request(self, request: ResearchRequest) -> dict | None:
        if not isinstance(request.pack_path, Path):
            request = ResearchRequest(**{**request.__dict__, "pack_path": Path(request.pack_path)})
        if request.venue not in {"kraken", "coinbase"}:
            return {
                "code": CODE_UNKNOWN_VENUE,
                "message": f"unknown venue: {request.venue}",
            }
        if request.dataset_csv is None and self._fetch is None:
            return {
                "code": CODE_NO_DATASET_AND_NO_FETCH,
                "message": "no dataset and no fetch injected",
            }
        return None

    # ---- helpers ---------------------------------------------------------

    def _load_pack(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _resolve_pair(self, pack: dict, venue: str) -> str | None:
        for m in pack.get("markets") or []:
            if m.get("venue") == venue and m.get("pair"):
                return str(m["pair"])
        return None

    def _default_fee(self, venue: str) -> int:
        return 40 if venue == "kraken" else 120

    def _resolve_candles(
        self,
        request: ResearchRequest,
        *,
        venue: str,
        pair: str,
        tf: str,
    ) -> tuple[list[Candle] | None, str | None, dict | None]:
        """Return (candles, manifest_sha, refusal). Exactly one of candles and refusal is set."""
        if request.dataset_csv is not None:
            csv_path = Path(request.dataset_csv)
            if not csv_path.exists():
                refusal = {
                    "code": CODE_INVALID_DATASET,
                    "message": f"dataset file not found: {csv_path}",
                }
                return None, None, refusal
            try:
                body = csv_path.read_bytes()
                candles = _parse_csv(body)
                digest = sha256_bytes(body)
            except (OSError, ValueError) as exc:
                refusal = {
                    "code": CODE_INVALID_DATASET,
                    "message": f"dataset unreadable: {type(exc).__name__}",
                }
                return None, None, refusal
        else:
            assert self._fetch is not None
            try:
                fetched = self._fetch(venue, pair, tf)
            except (OSError, ValueError, TypeError, RuntimeError, TimeoutError) as exc:
                refusal = {
                    "code": CODE_INVALID_DATASET,
                    "message": f"fetch failed: {type(exc).__name__}",
                }
                return None, None, refusal
            candles = list(fetched or [])
            digest = hashlib.sha256(_candles_to_canonical_bytes(candles)).hexdigest()

        if not candles:
            refusal = {
                "code": CODE_EMPTY_DATASET,
                "message": f"no candles for {venue} {pair} {tf}",
            }
            return None, None, refusal

        try:
            check_gaps(candles, tf, pair=pair, allow_gaps=request.allow_gaps)
        except GapError as exc:
            refusal = {
                "code": CODE_GAPPED_DATA,
                "message": str(exc),
            }
            return None, None, refusal

        return candles, digest, None

    # ---- trace -----------------------------------------------------------

    def _build_trace(self, pack: dict, candles: list[Candle]) -> list[dict]:
        """Replay-mode trace builder. Delegates to the shared builder.

        Replay and paper both call `shared_decision_trace(pack, candles)`
        in `krellbot.domain.trace`; this method is a thin shim that
        keeps the call site readable. The trace explains evaluator
        output, not venue execution or fill certainty.
        """
        return shared_decision_trace(pack, candles)


def _candles_to_canonical_bytes(candles: list[Candle]) -> bytes:
    """Render a candle list into canonical bytes for sha256.

    The same shape `krellbot.data.cache._render_csv` uses, but bypasses
    the on-disk path so the injected-fetch research path has a stable
    digest without writing a temp file.
    """
    parts = ["ts_ms,open,high,low,close,volume"]
    for c in candles:
        parts.append(f"{c.ts_ms},{c.open},{c.high},{c.low},{c.close},{c.volume}")
    return ("\n".join(parts) + "\n").encode("utf-8")


def _receipt_has_non_finite(value: object) -> bool:
    """Return True if ``value`` is or contains a non-finite float.

    Walks dicts, lists, and tuples. Strings, ints, bools, None, and
    Decimals are always finite. The browser cannot parse ``Infinity``
    or ``NaN`` in JSON, so any receipt containing one of these floats
    must be rejected before it is handed back to the caller.
    """
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_receipt_has_non_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_receipt_has_non_finite(v) for v in value)
    return False

"""Lane A — dataset selection, byte-identical export, studio edit changes a backtest.

Behavior under test (brief: `lane-a-brief.md`):

  1. ``_default_runner`` accepts ``dataset_id`` naming a fixture registered
     under the job home (a catalog file the test writes). It resolves that
     id to the fixture CSV and passes that path to ``ResearchRequest``.
     A ``dataset_csv`` path that is not the resolved fixture is
     ``invalid_dataset``. Missing ``dataset_id`` and missing ``dataset_csv``
     stays a refusal, not a zero-filled result. Do not coerce True, 1.0,
     or missing keys into a path.

  2. Byte-identical export. The canonical UTF-8 bytes of ``legacy_receipt``
     must equal ``json.dumps(legacy_receipt, sort_keys=True,
     separators=(",", ":")).encode()``. Missing receipt fields stay absent.
     Do not add equity or fill_price.

  3. Studio edit changes the backtest. Editing ``entry`` through
     ``StrategyDraftService.edit`` produces a new ``revision_id`` whose
     receipt bytes differ from the parent. A layout-only ``save_editor``
     does not change the receipt bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot.api.jobs import JobManager, canonical_receipt_bytes
from krellbot.application.research import (
    CODE_INVALID_DATASET,
    CODE_NO_DATASET_AND_NO_FETCH,
)
from krellbot.application.strategy import StrategyDraftService

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

DATASET_CATALOG_FILENAME = "datasets.json"


def _valid_pack_dict() -> dict:
    """Return a runnable v1 pack used by Lane A tests."""

    return {
        "schema_version": 1,
        "id": "lane-a-strategy",
        "version": "1.0.0",
        "label": "Lane A fixture",
        "author": "krellbot lane-a tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


def _write_pack(home: Path) -> Path:
    """Write a runnable v1 pack to ``home/pack.json`` and return its path."""

    path = home / "pack.json"
    path.write_text(json.dumps(_valid_pack_dict(), sort_keys=True), encoding="utf-8")
    return path


def _write_catalog(home: Path, entries: dict[str, str]) -> Path:
    """Write the dataset catalog that ``_default_runner`` consults.

    Returns the catalog path so the test can refer to it if needed.
    """

    path = home / DATASET_CATALOG_FILENAME
    path.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _resolve_fixture_csv(name: str = "kraken_SUIUSD_1h_sample.csv") -> Path:
    """Absolute path to a candle fixture the lane-a tests register."""

    return (Path(__file__).parent / "fixtures" / "candles" / name).resolve()


def _make_runner(home: Path) -> JobManager:
    """Return a ``JobManager`` wired at ``home`` for direct ``_default_runner`` calls."""

    return JobManager(home=home)


def _create_draft(home: Path) -> dict:
    """Create the strategy draft used by Lane A tests; return its summary."""

    return StrategyDraftService(home=home).create(_valid_pack_dict())


# ---------------------------------------------------------------------------
# 1. Permitted dataset selection
# ---------------------------------------------------------------------------


def test_dataset_id_resolves_to_catalog_fixture_and_runs(home: Path) -> None:
    """``dataset_id`` registered in the catalog resolves to the fixture CSV.

    The runner picks the catalog file up from the job home and passes the
    resolved path to ``ResearchRequest``. A successful run returns
    ``ok=True`` with a non-empty ``legacy_receipt``.
    """

    fixture = _resolve_fixture_csv()
    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(fixture)})
    pack = _write_pack(home)

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )

    assert outcome["ok"] is True, outcome
    assert outcome["legacy_receipt"], outcome


def test_dataset_id_unknown_id_is_invalid_dataset(home: Path) -> None:
    """An id not registered in the catalog is ``invalid_dataset``, not ok=False-zero."""

    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(_resolve_fixture_csv())})
    pack = _write_pack(home)

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_id": "not-in-catalog",
        }
    )

    assert outcome["ok"] is False, outcome
    assert outcome["code"] == CODE_INVALID_DATASET, outcome


def test_dataset_id_missing_catalog_file_is_invalid_dataset(home: Path) -> None:
    """A ``dataset_id`` with no catalog file is ``invalid_dataset``."""

    pack = _write_pack(home)
    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )

    assert outcome["ok"] is False, outcome
    assert outcome["code"] == CODE_INVALID_DATASET, outcome


def test_dataset_id_with_dataset_csv_must_match_fixture(home: Path) -> None:
    """A ``dataset_csv`` that disagrees with the resolved fixture is invalid."""

    fixture = _resolve_fixture_csv()
    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(fixture)})
    pack = _write_pack(home)

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_id": "kraken_SUIUSD_1h_sample",
            "dataset_csv": "/tmp/some-other-csv.csv",
        }
    )

    assert outcome["ok"] is False, outcome
    assert outcome["code"] == CODE_INVALID_DATASET, outcome


def test_dataset_id_resolves_to_legacy_receipt_for_backtest(home: Path) -> None:
    """End-to-end: ``dataset_id`` resolution feeds the ResearchService and the
    receipt surfaces ``data_manifest_sha256`` reflecting the fixture file."""

    fixture = _resolve_fixture_csv()
    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(fixture)})
    pack = _write_pack(home)

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )

    assert outcome["ok"] is True, outcome
    receipt = outcome["legacy_receipt"]
    assert receipt["data_manifest_sha256"], receipt


def test_dataset_csv_passes_through_when_no_dataset_id(home: Path) -> None:
    """A ``dataset_csv`` with no ``dataset_id`` keeps the existing path through."""

    fixture = _resolve_fixture_csv()
    pack = _write_pack(home)

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_csv": str(fixture),
        }
    )

    assert outcome["ok"] is True, outcome


def test_missing_dataset_id_and_dataset_csv_is_refusal(home: Path) -> None:
    """Missing both ``dataset_id`` and ``dataset_csv`` is a refusal, not ok."""

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
        }
    )

    assert outcome["ok"] is False, outcome
    assert outcome["code"] == CODE_NO_DATASET_AND_NO_FETCH, outcome


def test_truthy_dataset_id_is_not_a_path(home: Path) -> None:
    """``True``, ``1.0``, and similar non-strings are not coerced into a path."""

    pack = _write_pack(home)
    runner = _make_runner(home)
    for value in (True, 1.0, 1, 0):
        outcome = runner._default_runner(
            {
                "pack_path": str(pack),
                "venue": "kraken",
                "pair": "SUIUSD",
                "timeframe": "1h",
                "dataset_id": value,
            }
        )
        assert outcome["ok"] is False, (value, outcome)


def test_missing_dataset_id_with_unknown_dataset_csv_is_refusal(home: Path) -> None:
    """An explicit ``dataset_csv`` that doesn't exist is ``invalid_dataset``."""

    pack = _write_pack(home)
    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_csv": "/tmp/this-file-does-not-exist.csv",
        }
    )

    assert outcome["ok"] is False, outcome
    assert outcome["code"] == CODE_INVALID_DATASET, outcome


# ---------------------------------------------------------------------------
# 2. Byte-identical export
# ---------------------------------------------------------------------------


def test_canonical_receipt_bytes_are_sorted_key_compact_utf8() -> None:
    """``canonical_receipt_bytes`` is UTF-8, sorted keys, (',', ':') separators."""

    receipt = {"b": 1, "a": 2, "nested": {"y": True, "x": None}}
    expected = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert canonical_receipt_bytes(receipt) == expected
    # Sort key + compact separators → no whitespace.
    assert b" " not in canonical_receipt_bytes(receipt)


def test_canonical_receipt_bytes_match_runner_outcome_receipt(home: Path) -> None:
    """The ``legacy_receipt`` returned by ``_default_runner`` is byte-identical
    to ``canonical_receipt_bytes(legacy_receipt)``.

    The function is part of the existing job result path: it is invoked
    inside ``_default_runner`` to compute the result's receipt digest,
    and the same canonicalization is what the result bytes expose.
    """

    fixture = _resolve_fixture_csv()
    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(fixture)})
    pack = _write_pack(home)

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )

    assert outcome["ok"] is True, outcome
    receipt = outcome["legacy_receipt"]
    assert receipt, outcome

    # Byte-identical to canonical JSON of the same dict.
    expected = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert canonical_receipt_bytes(receipt) == expected

    # The runner's result already advertises a digest keyed by the same
    # canonical bytes; the function used by the result path returns the
    # canonical bytes for any dict, byte-identical.
    assert outcome["receipt_canonical_sha256"]


def test_canonical_receipt_bytes_do_not_invent_fields(home: Path) -> None:
    """Canonical bytes stay absent of any field the brief forbids."""

    fixture = _resolve_fixture_csv()
    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(fixture)})
    pack = _write_pack(home)

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "pack_path": str(pack),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )

    assert outcome["ok"] is True, outcome
    receipt = outcome["legacy_receipt"]
    canonical = canonical_receipt_bytes(receipt).decode("utf-8")
    parsed = json.loads(canonical)
    assert "equity" not in parsed, parsed.keys()
    assert "fill_price" not in parsed, parsed.keys()


# ---------------------------------------------------------------------------
# 3. Studio edit changes the backtest
# ---------------------------------------------------------------------------


def test_default_runner_uses_draft_pack_from_revision_id(home: Path) -> None:
    """A ``revision_id`` is enough to make ``_default_runner`` execute the draft."""

    summary = _create_draft(home)
    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "revision_id": summary["revision_id"],
            "dataset_csv": str(_resolve_fixture_csv()),
        }
    )

    assert outcome["ok"] is True, outcome
    assert outcome["legacy_receipt"], outcome


def test_studio_edit_changes_backtest_receipt_bytes(home: Path) -> None:
    """Editing ``entry`` through ``StrategyDraftService.edit`` produces a new
    ``revision_id`` whose receipt bytes differ from the parent's.

    The Python test goes through ``_default_runner`` so the assertion is
    that the bytes flow through the same code path that ships to clients.
    """

    fixture = _resolve_fixture_csv()
    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    parent = _create_draft(home)
    runner = _make_runner(home)

    parent_outcome = runner._default_runner(
        {
            "revision_id": parent["revision_id"],
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )
    assert parent_outcome["ok"] is True, parent_outcome
    parent_bytes = canonical_receipt_bytes(parent_outcome["legacy_receipt"])

    edited_pack = _valid_pack_dict()
    edited_pack["entry"] = ["close", ">", "sma2"]
    child = StrategyDraftService(home=home).edit(parent["revision_id"], edited_pack)

    child_outcome = runner._default_runner(
        {
            "revision_id": child["revision_id"],
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )
    assert child_outcome["ok"] is True, child_outcome
    child_bytes = canonical_receipt_bytes(child_outcome["legacy_receipt"])

    assert parent_bytes != child_bytes, "entry edit must change the receipt bytes"


def test_layout_only_save_editor_does_not_change_backtest_bytes(home: Path) -> None:
    """A ``save_editor`` call (layout only) leaves the receipt bytes unchanged."""

    fixture = _resolve_fixture_csv()
    _write_catalog(home, {"kraken_SUIUSD_1h_sample": str(fixture)})

    parent = _create_draft(home)
    runner = _make_runner(home)

    before = runner._default_runner(
        {
            "revision_id": parent["revision_id"],
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )
    assert before["ok"] is True, before
    before_bytes = canonical_receipt_bytes(before["legacy_receipt"])

    StrategyDraftService(home=home).save_editor(
        parent["revision_id"],
        {"layout": {"entry": {"x": 10, "y": 20}}, "panes": {"left": "raw"}},
    )

    after = runner._default_runner(
        {
            "revision_id": parent["revision_id"],
            "dataset_id": "kraken_SUIUSD_1h_sample",
        }
    )
    assert after["ok"] is True, after
    after_bytes = canonical_receipt_bytes(after["legacy_receipt"])

    assert before_bytes == after_bytes


def test_default_runner_unknown_revision_id_is_not_found(home: Path) -> None:
    """An unknown revision id with no fallback data is ``not_found``."""

    runner = _make_runner(home)
    outcome = runner._default_runner(
        {
            "revision_id": "0" * 64,
            "dataset_csv": str(_resolve_fixture_csv()),
        }
    )

    assert outcome["ok"] is False, outcome
    assert outcome["code"] == "not_found", outcome

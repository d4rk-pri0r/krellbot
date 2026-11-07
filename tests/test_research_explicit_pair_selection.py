"""Explicit research pairs must match the requested venue, never silently default.

All prices are synthetic. Exercise the real service, default job runner and
session/CSRF/origin-guarded ASGI routes; no exchange or keyring access is needed.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from krellbot.application.research import CODE_PACK_HAS_NO_MARKET, ResearchRequest, ResearchService
from krellbot.pack.model import Candle
from tests.test_ns04_research_service import PACK_DICT, _write_synthetic_csv
from tests.test_ns06_jobs import _bootstrap_session, _build_app, _submit_job
from tests.test_ns09_research_api import _get_result, _wait_for_terminal


@pytest.fixture
def synthetic_inputs(home, monkeypatch, fresh_keyring):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)
    pack = {
        **PACK_DICT,
        "label": "Synthetic multi-market selection fixture",
        "markets": [
            {"venue": "coinbase", "pair": "BTC-USD"},
            {"venue": "kraken", "pair": "SUIUSD"},
            {"venue": "kraken", "pair": "ETHUSD"},
        ],
    }
    pack_path = home / "synthetic-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    csv_path = _write_synthetic_csv(home / "synthetic-prices.csv")
    candles = [
        Candle(i * 3_600_000, Decimal(c), Decimal(c) + 1, Decimal(c) - 1, Decimal(c), Decimal(100))
        for i, c in enumerate([10, 10, 12, 14, 8, 8, 8, 8])
    ]
    return pack_path, csv_path, candles


@pytest.mark.parametrize("mode", ["csv", "fetch"])
@pytest.mark.parametrize(
    "venue,pair,expected",
    [
        ("kraken", None, "SUIUSD"),
        ("kraken", "SUIUSD", "SUIUSD"),
        ("kraken", "ETHUSD", "ETHUSD"),
        ("coinbase", None, "BTC-USD"),
        ("coinbase", "BTC-USD", "BTC-USD"),
    ],
)
def test_service_selected_pair_matches_receipt_detail_and_fetch(home, synthetic_inputs, mode, venue, pair, expected):
    pack_path, csv_path, candles = synthetic_inputs
    calls = []

    def fetch(fetch_venue, fetch_pair, tf):
        calls.append((fetch_venue, fetch_pair, tf))
        return candles

    result = ResearchService(home=home, fetch=fetch).run(
        ResearchRequest(pack_path=pack_path, venue=venue, pair=pair, dataset_csv=csv_path if mode == "csv" else None)
    )
    assert result.ok, result.refusal
    assert result.refusal is None
    assert result.legacy_receipt["pair"] == result.detail["pair"] == expected
    assert result.legacy_receipt["venue"] == result.detail["venue"] == venue
    assert calls == ([] if mode == "csv" else [(venue, expected, "1h")])


@pytest.mark.parametrize("mode", ["csv", "fetch"])
@pytest.mark.parametrize("pair", ["BTCUSD", "BTC-USD", "", "ethusd", "ETH/USD", " ETHUSD", "ETHUSD "])
def test_service_invalid_explicit_pair_refuses_without_fetch_or_receipt(home, synthetic_inputs, mode, pair):
    pack_path, csv_path, candles = synthetic_inputs
    calls = []

    def fetch(*args):
        calls.append(args)
        return candles

    result = ResearchService(home=home, fetch=fetch).run(
        ResearchRequest(pack_path=pack_path, venue="kraken", pair=pair, dataset_csv=csv_path if mode == "csv" else None)
    )
    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.refusal == {"code": CODE_PACK_HAS_NO_MARKET, "message": "pack has no market for kraken"}
    assert result.detail == {"schema_version": "1", "refusal": result.refusal}
    assert calls == []


@pytest.mark.parametrize("pair", [None, "ETHUSD"])
def test_service_existing_no_venue_market_refusal_is_preserved(home, synthetic_inputs, pair):
    pack_path, csv_path, _ = synthetic_inputs
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    pack["markets"] = [{"venue": "coinbase", "pair": "ETHUSD"}]
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    result = ResearchService(home=home).run(
        ResearchRequest(pack_path=pack_path, venue="kraken", pair=pair, dataset_csv=csv_path)
    )
    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.refusal == {"code": CODE_PACK_HAS_NO_MARKET, "message": "pack has no market for kraken"}


@pytest.mark.parametrize("pair", [None, "SUIUSD", "ETHUSD", "BTCUSD", "BTC-USD", "", "ethusd", " ETHUSD"])
def test_guarded_http_default_job_runner_preserves_pair_and_refusal(home, synthetic_inputs, pair):
    pack_path, csv_path, _ = synthetic_inputs
    app = _build_app(home)  # No injected runner: actual JobManager and ResearchService.
    csrf, session = _bootstrap_session(app)
    payload = {"pack_path": str(pack_path), "dataset_csv": str(csv_path), "venue": "kraken"}
    if pair is not None:
        payload["pair"] = pair
    status, submitted = _submit_job(app, csrf, session, payload)
    assert status == 200, submitted
    job_id = submitted["id"]
    final = _wait_for_terminal(app, csrf, session, job_id, timeout=5)
    result_status, result = _get_result(app, csrf, session, job_id)
    if pair in {None, "SUIUSD", "ETHUSD"}:
        assert final["state"] == "succeeded", final
        assert final["result_ref"]
        assert result_status == 200
        assert result["legacy_receipt"]["pair"] == (pair if pair is not None else "SUIUSD")
        assert result["legacy_receipt"]["venue"] == "kraken"
    else:
        assert final["state"] == "failed", final
        assert final["error"] == {"code": CODE_PACK_HAS_NO_MARKET, "message": "pack has no market for kraken"}
        assert final["result_ref"] is None
        assert result_status == 404
        assert result == {"code": "result_unavailable"}

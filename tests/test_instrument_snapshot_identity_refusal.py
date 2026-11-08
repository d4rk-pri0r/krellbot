"""Synthetic persisted records must match their exact requested lookup identity."""

from dataclasses import replace
from decimal import Decimal

import pytest

from krellbot.cli import _build_paper_rules_provider
from krellbot.data.instruments import InstrumentMetadataError, InstrumentRulesSnapshot, OfflineModeRequired
from krellbot.pack.model import Candle
from krellbot.venues.paper import PaperVenue, default_rules
from tests.test_instrument_adapter_step_representability import _record


@pytest.fixture(autouse=True)
def isolated(home, monkeypatch, fresh_keyring):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)
    monkeypatch.setattr("krellbot.data.instruments._default_now", lambda: 1_700_000_000)


@pytest.mark.parametrize("requested_venue,requested_pair", [("coinbase", "ABC-USD"), ("kraken", "SUIUSD")])
@pytest.mark.parametrize("wrong", ["venue", "pair", "both", "pair-case", "pair-space"])
@pytest.mark.parametrize("stale", [False, True])
def test_mismatch_refuses_before_freshness_and_cli_fallback(home, requested_venue, requested_pair, wrong, stale):
    venue = ("coinbase" if requested_venue == "kraken" else "kraken") if wrong in {"venue", "both"} else requested_venue
    pair = {
        "pair": "OTHER-SYNTHETIC",
        "both": "OTHER-SYNTHETIC",
        "pair-case": requested_pair.lower(),
        "pair-space": " " + requested_pair,
    }.get(wrong, requested_pair)
    record = _record(
        venue=venue,
        canonical_pair=pair,
        venue_symbol=pair,
        usable_until="2000-01-01T00:00:00Z" if stale else "2099-01-01T00:00:00Z",
    )
    InstrumentRulesSnapshot(home).write({requested_venue: {requested_pair: record}})
    path = home / "run" / "instrument-rules.json"
    before = path.read_bytes()
    for read in (
        lambda: InstrumentRulesSnapshot(home).read_pair(requested_venue, requested_pair, offline=True),
        lambda: _build_paper_rules_provider(home, requested_venue)(requested_pair),
    ):
        with pytest.raises(InstrumentMetadataError) as caught:
            read()
        assert (caught.value.code, caught.value.venue, caught.value.pair) == (
            "metadata_symbol_mismatch",
            requested_venue,
            requested_pair,
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize("corrupt", [True, False])
def test_real_provider_and_paper_entry_refuse_before_publication(home, corrupt):
    pair = "SUIUSD"
    record = _record(venue="kraken", canonical_pair="OTHER-SYNTHETIC" if corrupt else pair, venue_symbol=pair)
    InstrumentRulesSnapshot(home).write({"kraken": {pair: record}})
    candle = Candle(0, Decimal(100), Decimal(100), Decimal(100), Decimal(100), Decimal(10))
    venue = PaperVenue(
        "kraken",
        rules_provider=_build_paper_rules_provider(home, "kraken"),
        candle_reader=lambda *_: [candle],
        home=home,
        starting_cash=Decimal(1000),
    )
    before = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    if corrupt:
        with pytest.raises(InstrumentMetadataError) as caught:
            venue.place_entry_with_stop("synthetic-entry", Decimal("0.13"), Decimal("90.13"), pair=pair)
        assert caught.value.code == "metadata_symbol_mismatch"
        assert not venue.snapshot().recent_fills and not venue.snapshot().open_orders
        assert {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()} == before
    else:
        venue.place_entry_with_stop("synthetic-entry", Decimal("0.13"), Decimal("90.13"), pair=pair)
        assert len(venue.snapshot().recent_fills) == len(venue.snapshot().open_orders) == 1


def test_correct_identity_offline_missing_stale_and_multi_market_controls(home):
    kraken = _record(venue="kraken", canonical_pair="SUIUSD", venue_symbol="SUIUSD")
    coinbase = _record()
    snapshot = InstrumentRulesSnapshot(home)
    snapshot.write({"kraken": {"SUIUSD": kraken}, "coinbase": {"ABC-USD": coinbase}})
    fresh = InstrumentRulesSnapshot(home)
    assert fresh.read_pair("kraken", "SUIUSD", offline=True) == kraken
    assert fresh.read_pair("coinbase", "ABC-USD", offline=True) == coinbase
    with pytest.raises(OfflineModeRequired):
        fresh.read_pair("kraken", "SUIUSD")
    with pytest.raises(InstrumentMetadataError) as missing:
        fresh.read_pair("coinbase", "MISSING", offline=True)
    assert missing.value.code == "metadata_unavailable"
    snapshot.write({"kraken": {"SUIUSD": replace(kraken, usable_until="2000-01-01T00:00:00Z")}})
    with pytest.raises(InstrumentMetadataError) as stale:
        InstrumentRulesSnapshot(home).read_pair("kraken", "SUIUSD", offline=True)
    assert stale.value.code == "metadata_stale"
    assert _build_paper_rules_provider(home / "empty-home", "kraken")("SUIUSD") == default_rules("SUIUSD")

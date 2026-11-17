"""Built-in DCA mode pack validates; interval and sizing are explicit in JSON."""

from __future__ import annotations

from krellbot.pack import lint, modes
from krellbot.packs import mode_packs


def test_builtin_dca_mode_pack_loads_and_validates():
    pack = mode_packs.load_mode_pack("dca")
    assert pack["id"] == modes.MODE_IDS["dca"] == "mode-dca"
    assert pack["mode"] == {"kind": "dca"}
    errors = lint.check(pack)
    assert errors == [], f"unexpected lint errors: {errors}"


def test_dca_interval_and_sizing_are_explicit_in_json():
    pack = mode_packs.load_mode_pack("dca")
    # Interval = timeframe; slice size = risk.max_account_pct. No hidden CLI scheduler.
    assert pack["timeframe"] in {"1h", "4h", "1d"}
    assert isinstance(pack["risk"]["max_account_pct"], int)
    assert 1 <= pack["risk"]["max_account_pct"] <= 100
    assert isinstance(pack.get("origin"), str) and pack["origin"].strip()
    assert "timeframe" in pack["origin"] or "Interval" in pack["origin"] or "interval" in pack["origin"].lower()
    assert "max_account_pct" in pack["origin"] or "slice" in pack["origin"].lower()


def test_dca_is_listed_among_available_builtin_modes():
    kinds = mode_packs.available_mode_kinds()
    assert "dca" in kinds


def test_unknown_mode_kind_raises():
    try:
        mode_packs.load_mode_pack("not-a-mode")
    except KeyError as exc:
        assert "not-a-mode" in str(exc)
    else:
        raise AssertionError("expected KeyError for unknown kind")

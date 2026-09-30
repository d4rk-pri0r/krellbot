"""NS11b — declare stop capability without calling a venue.

Per-venue stop capabilities and a `submit_if_supported` helper that
checks the asset class and the venue capability before any submit
side effect. No venue adapter is imported.
"""

from __future__ import annotations

import importlib

import pytest

from krellbot import domain as domain_mod
from krellbot.domain import capabilities as capabilities_mod
from krellbot.domain.capabilities import (
    stop_capability,
    submit_if_supported,
)
from krellbot.domain.records import (
    UnsupportedAssetClass,
    UnsupportedStop,
)

# ---- stop_capability: per-venue table ----------------------------------


def test_stop_capability_paper_is_emulated():
    assert stop_capability("paper") == "emulated"


def test_stop_capability_kraken_is_unsupported():
    assert stop_capability("kraken") == "unsupported"


def test_stop_capability_coinbase_is_unsupported():
    assert stop_capability("coinbase") == "unsupported"


def test_stop_capability_unknown_venue_is_unsupported():
    assert stop_capability("binance") == "unsupported"
    assert stop_capability("") == "unsupported"
    assert stop_capability("Paper") == "unsupported"


def test_stop_capability_never_returns_native_in_this_leaf():
    """This leaf does not claim a native exchange stop, even for paper."""
    for venue in ("paper", "kraken", "coinbase", "binance", "okx", "bybit"):
        assert stop_capability(venue) != "native", venue


# ---- submit_if_supported: paper spot is the one supported path ---------


def test_submit_if_supported_calls_submit_for_paper_spot():
    called = []

    def submit():
        called.append("submit")
        return "ok-paper-emulated"

    result = submit_if_supported("paper", "spot", submit)
    assert result == "ok-paper-emulated"
    assert called == ["submit"]


def test_submit_if_supported_returns_submit_result_unchanged():
    """Whatever `submit()` returns is what `submit_if_supported` returns."""
    sentinel = {"id": "receipt-1", "filled": True}
    assert submit_if_supported("paper", "spot", lambda: sentinel) is sentinel
    assert submit_if_supported("paper", "spot", lambda: None) is None


# ---- submit_if_supported: live venues are unsupported -------------------


def test_submit_if_supported_refuses_kraken_spot_and_skips_submit():
    called = []

    def submit():
        called.append("submit")
        return "should-never-happen"

    with pytest.raises(UnsupportedStop) as ei:
        submit_if_supported("kraken", "spot", submit)
    assert ei.value.capability == "unsupported"
    assert called == []


def test_submit_if_supported_refuses_coinbase_spot_and_skips_submit():
    called = []

    def submit():
        called.append("submit")
        return "should-never-happen"

    with pytest.raises(UnsupportedStop) as ei:
        submit_if_supported("coinbase", "spot", submit)
    assert ei.value.capability == "unsupported"
    assert called == []


def test_submit_if_supported_refuses_unknown_venue_and_skips_submit():
    called = []

    def submit():
        called.append("submit")

    with pytest.raises(UnsupportedStop):
        submit_if_supported("binance", "spot", submit)
    assert called == []


# ---- submit_if_supported: asset_class check runs before capability -----


def test_submit_if_supported_rejects_futures_before_submit():
    """`asset_class != spot` raises `UnsupportedAssetClass` before any submit."""
    called = []

    def submit():
        called.append("submit")

    with pytest.raises(UnsupportedAssetClass) as ei:
        submit_if_supported("paper", "futures", submit)
    assert ei.value.asset_class == "futures"
    assert called == []


def test_submit_if_supported_rejects_perpetual_before_submit():
    called = []

    def submit():
        called.append("submit")

    with pytest.raises(UnsupportedAssetClass):
        submit_if_supported("paper", "perpetual", submit)
    assert called == []


def test_submit_if_supported_rejects_empty_asset_class_before_submit():
    called = []

    def submit():
        called.append("submit")

    with pytest.raises(UnsupportedAssetClass):
        submit_if_supported("paper", "", submit)
    assert called == []


def test_submit_if_supported_asset_class_check_runs_before_capability_check():
    """A non-spot asset_class raises `UnsupportedAssetClass`, not `UnsupportedStop`,
    even when the venue would also be unsupported."""
    with pytest.raises(UnsupportedAssetClass):
        submit_if_supported("kraken", "futures", lambda: None)
    with pytest.raises(UnsupportedAssetClass):
        submit_if_supported("coinbase", "perpetual", lambda: None)


def test_submit_if_supported_does_not_call_submit_for_futures_on_paper():
    """A non-spot asset class for a venue that would otherwise support
    a stop still raises `UnsupportedAssetClass` and skips `submit`."""
    called = []

    def submit():
        called.append("submit")

    with pytest.raises(UnsupportedAssetClass):
        submit_if_supported("paper", "futures", submit)
    assert called == []


# ---- isolation from venue adapters --------------------------------------


def test_capabilities_module_does_not_import_krellbot_venues():
    """NS11b: do not import or call `krellbot.venues` from the domain layer."""
    for mod_name in ("krellbot.domain", "krellbot.domain.capabilities"):
        mod = importlib.import_module(mod_name)
        for attr in dir(mod):
            if attr.startswith("__"):
                continue
            obj = getattr(mod, attr)
            mod_obj = getattr(obj, "__module__", "") or ""
            assert "krellbot.venues" not in mod_obj, (
                f"{mod_name}.{attr} resolves to {mod_obj!r}; the domain layer must not depend on venue adapters"
            )


def test_capabilities_module_does_not_call_into_venues(monkeypatch):
    """A tripwire: any import of `krellbot.venues` raises immediately.

    Reloads `capabilities` and `domain` so the patched `__import__`
    runs against fresh module objects, not the ones cached from earlier
    in the session. We do NOT reload `records` here; that is the
    NS11a tripwire's job, and reloading it would also rebind the
    exception classes that other modules imported at load time.
    """
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "krellbot.venues" or name.startswith("krellbot.venues."):
            raise AssertionError(
                f"krellbot.domain must not import or call krellbot.venues (attempted import of {name!r})"
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.reload(capabilities_mod)
    importlib.reload(domain_mod)


# ---- re-exports --------------------------------------------------------


def test_domain_package_reexports_capability_symbols():
    for name in (
        "stop_capability",
        "submit_if_supported",
    ):
        assert hasattr(domain_mod, name), name

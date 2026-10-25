"""Runtime import boundaries, each proved in a fresh, network-denied interpreter.

These checks observe actual imports, not the conservative static import graph.
No test-suite modules or remote adapter instances are loaded into the child.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REMOTE_MODULES = {"krellbot.venues.kraken", "krellbot.venues.coinbase"}
PUBLIC_NAMES = [
    "Balance",
    "CoinbaseVenue",
    "Fill",
    "KeyPerms",
    "KrakenVenue",
    "OpenOrder",
    "OrderRef",
    "PairRules",
    "Truth",
    "Venue",
    "WithdrawCapableError",
]
PRELUDE = """
import json
import os
import sys

assert not any(name == 'krellbot' or name.startswith('krellbot.') for name in sys.modules)
network_attempts = []


def deny_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        network_attempts.append(event)
        raise AssertionError('network forbidden during venue import: ' + event)


sys.addaudithook(deny_network)
"""
EPILOGUE = """
assert not network_attempts, network_attempts
print(json.dumps({
    'pid': os.getpid(),
    'modules': sorted(name for name in sys.modules if name.startswith('krellbot')),
    'network_attempts': network_attempts,
}))
"""


def run_import(tmp_path: Path, source: str) -> dict:
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        HOME=str(tmp_path),
        KRELLBOT_HOME=str(tmp_path / "home"),
        KRELLBOT_ENABLE_LIVE="0",
        KRELLBOT_LIVE="0",
        KRELLBOT_API_LIVE="0",
    )
    argv = [sys.executable, "-c", PRELUDE + textwrap.dedent(source) + EPILOGUE]
    result = subprocess.run(
        argv,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    (tmp_path / "import-process.json").write_text(
        json.dumps(
            {
                "argv": argv,
                "cwd": str(tmp_path),
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["pid"] != os.getpid()
    assert observed["network_attempts"] == []
    return observed


@pytest.mark.parametrize(
    ("source", "expected_module"),
    [
        ("import krellbot.venues", "krellbot.venues"),
        ("import krellbot.venues.base", "krellbot.venues.base"),
        ("from krellbot.venues.paper import PaperVenue", "krellbot.venues.paper"),
        ("import krellbot.data.instruments", "krellbot.data.instruments"),
        (
            """
            from krellbot.venues import (
                Balance, Fill, KeyPerms, OpenOrder, OrderRef, PairRules,
                Truth, Venue, WithdrawCapableError,
            )
            import krellbot.venues.base as base
            for name in (
                'Balance', 'Fill', 'KeyPerms', 'OpenOrder', 'OrderRef',
                'PairRules', 'Truth', 'Venue', 'WithdrawCapableError',
            ):
                assert globals()[name] is getattr(base, name)
            """,
            "krellbot.venues.base",
        ),
    ],
    ids=["package", "base-alone", "paper-alone", "instruments-alone", "public-protocol"],
)
def test_offline_import_does_not_load_remote_adapters(tmp_path, source, expected_module):
    observed = run_import(tmp_path, source)
    assert expected_module in observed["modules"]
    assert REMOTE_MODULES.isdisjoint(observed["modules"]), observed["modules"]


@pytest.mark.parametrize(("module", "name"), [("kraken", "KrakenVenue"), ("coinbase", "CoinbaseVenue")])
@pytest.mark.parametrize("direct_first", [False, True], ids=["reexport-first", "direct-first"])
def test_explicit_adapter_reexport_is_the_cached_underlying_class(tmp_path, module, name, direct_first):
    observed = run_import(
        tmp_path,
        f"""
        import krellbot.venues as venues
        assert {name!r} not in vars(venues)
        if {direct_first!r}:
            from krellbot.venues.{module} import {name} as direct
        from krellbot.venues import {name} as exported
        from krellbot.venues.{module} import {name} as direct
        from krellbot.venues import {name} as repeated
        assert exported is direct is repeated
        assert getattr(venues, {name!r}) is direct
        assert vars(venues)[{name!r}] is direct
        assert direct.__module__ == 'krellbot.venues.{module}'
        """,
    )
    assert set(observed["modules"]) & REMOTE_MODULES == {f"krellbot.venues.{module}"}


def test_import_star_preserves_public_names_and_class_identity(tmp_path):
    observed = run_import(
        tmp_path,
        f"""
        import krellbot.venues as venues
        namespace = {{}}
        exec('from krellbot.venues import *', namespace)
        assert sorted(name for name in namespace if name != '__builtins__') == sorted({PUBLIC_NAMES!r})
        from krellbot.venues.kraken import KrakenVenue
        from krellbot.venues.coinbase import CoinbaseVenue
        assert namespace['KrakenVenue'] is KrakenVenue
        assert namespace['CoinbaseVenue'] is CoinbaseVenue
        assert vars(venues)['KrakenVenue'] is KrakenVenue
        assert vars(venues)['CoinbaseVenue'] is CoinbaseVenue
        for name in venues.__all__:
            assert namespace[name] is getattr(venues, name)
        """,
    )
    assert REMOTE_MODULES.issubset(observed["modules"])


def test_unknown_attribute_raises_without_loading_adapters(tmp_path):
    observed = run_import(
        tmp_path,
        """
        import krellbot.venues as venues
        for name in ('NoSuchVenue', '__not_a_venue__'):
            try:
                getattr(venues, name)
            except AttributeError as error:
                assert name in str(error)
            else:
                raise AssertionError('unknown attribute accepted: ' + name)
            assert name not in vars(venues)
            assert not hasattr(venues, name)
        """,
    )
    assert REMOTE_MODULES.isdisjoint(observed["modules"]), observed["modules"]


def test_all_is_preserved_without_resolving_lazy_names(tmp_path):
    observed = run_import(
        tmp_path,
        f"""
        import krellbot.venues as venues
        assert venues.__all__ == {PUBLIC_NAMES!r}
        assert isinstance(venues.__all__, list)
        """,
    )
    assert REMOTE_MODULES.isdisjoint(observed["modules"]), observed["modules"]


@pytest.mark.parametrize("resolved_name", [None, "KrakenVenue", "CoinbaseVenue"])
def test_dir_discovers_public_names_without_loading_remote_adapters(tmp_path, resolved_name):
    observed = run_import(
        tmp_path,
        f"""
        import krellbot.venues as venues
        remote_modules = {{'krellbot.venues.kraken', 'krellbot.venues.coinbase'}}
        assert remote_modules.isdisjoint(sys.modules)
        names = dir(venues)
        assert set({PUBLIC_NAMES!r}).issubset(names)
        assert set(vars(venues)).issubset(names)
        assert names == sorted(set(names))
        assert remote_modules.isdisjoint(sys.modules)
        assert 'KrakenVenue' not in vars(venues)
        assert 'CoinbaseVenue' not in vars(venues)
        resolved_name = {resolved_name!r}
        if resolved_name is not None:
            resolved = getattr(venues, resolved_name)
            loaded = set(sys.modules)
            names = dir(venues)
            assert set({PUBLIC_NAMES!r}).issubset(names)
            assert set(vars(venues)).issubset(names)
            assert names == sorted(set(names))
            assert set(sys.modules) == loaded
            assert vars(venues)[resolved_name] is resolved
        """,
    )
    expected_remote = {
        None: set(),
        "KrakenVenue": {"krellbot.venues.kraken"},
        "CoinbaseVenue": {"krellbot.venues.coinbase"},
    }
    assert set(observed["modules"]) & REMOTE_MODULES == expected_remote[resolved_name]


@pytest.mark.parametrize(("module", "name"), [("kraken", "KrakenVenue"), ("coinbase", "CoinbaseVenue")])
def test_adapter_import_errors_propagate_without_caching_a_placeholder(tmp_path, module, name):
    observed = run_import(
        tmp_path,
        f"""
        import importlib.abc
        import krellbot.venues as venues

        failure = ImportError('adapter import deliberately refused')

        class RefuseAdapter(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == 'krellbot.venues.{module}':
                    raise failure

        finder = RefuseAdapter()
        sys.meta_path.insert(0, finder)
        try:
            try:
                from krellbot.venues import {name}
            except ImportError as error:
                assert error is failure
            else:
                raise AssertionError('adapter import failure was swallowed')
            assert {name!r} not in vars(venues)
            assert 'krellbot.venues.{module}' not in sys.modules
        finally:
            sys.meta_path.remove(finder)
        from krellbot.venues import {name} as exported
        from krellbot.venues.{module} import {name} as direct
        assert exported is direct is vars(venues)[{name!r}]
        """,
    )
    assert set(observed["modules"]) & REMOTE_MODULES == {f"krellbot.venues.{module}"}

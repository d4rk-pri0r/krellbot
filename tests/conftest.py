"""Test configuration for krellbot.

Every test loads the fake keyring backend through the PYTHON_KEYRING_BACKEND
env var before any `import keyring` resolves a backend. The fresh_keyring
fixture resets the backend to a brand-new FakeKeyring per test so state from
one case never leaks into the next.
"""

from __future__ import annotations

import os

# Set the keyring backend BEFORE importing pytest/keyring so the resolution
# machinery picks up our fake.
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "tests.fakes.fake_keyring.FakeKeyring")

import keyring
import pytest
from fakes.fake_keyring import FakeKeyring


@pytest.fixture
def fresh_keyring() -> FakeKeyring:
    """Replace the active keyring backend with a fresh FakeKeyring per test."""
    fake = FakeKeyring()
    keyring.set_keyring(fake)
    return fake


@pytest.fixture
def home(monkeypatch, tmp_path):
    """Point both KRELLBOT_HOME and Path.home() at a temp dir."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path

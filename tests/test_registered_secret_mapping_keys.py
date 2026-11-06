"""Issue #266: synthetic registered secrets cannot persist in mapping keys."""

from __future__ import annotations

import copy
import os
import pickle
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from krellbot import sanitize


def test_fresh_public_redaction_and_real_journal_do_not_persist_secret_keys(tmp_path: Path):
    """Run actual public functions in a credential-free fresh process/home."""
    root = tmp_path.resolve()
    for name in ("user", "app", "tmp"):
        (root / name).mkdir()
    env = {k: os.environ[k] for k in ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR") if k in os.environ}
    env.update(
        HOME=str(root / "user"),
        USERPROFILE=str(root / "user"),
        KRELLBOT_HOME=str(root / "app"),
        TMPDIR=str(root / "tmp"),
        TMP=str(root / "tmp"),
        TEMP=str(root / "tmp"),
        APPDATA=str(root / "user" / "appdata"),
        LOCALAPPDATA=str(root / "user" / "localappdata"),
        XDG_CONFIG_HOME=str(root / "user" / "config"),
        XDG_CACHE_HOME=str(root / "user" / "cache"),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONUTF8="1",
    )
    script = textwrap.dedent("""
        import json
        import os
        from pathlib import Path
        root = Path.cwd().resolve()
        for name in ("HOME", "KRELLBOT_HOME", "TMPDIR", "TMP", "TEMP"):
            assert Path(os.environ[name]).resolve().is_relative_to(root), name
        from krellbot import sanitize, journal
        secret = "SYNTHETIC_REGISTERED_KEY_266_ONLY"
        sanitize.register_secret(secret)
        record = {
            "ts": 1700000000, "kind": "synthetic-diagnostic", "venue": "paper",
            "pack": "synthetic", "bar_ts": 0,
            "detail": [{"nested:" + secret: {"value": secret, "normal": 7}}],
            "top:" + secret: "ordinary",
        }
        before = json.dumps(record, ensure_ascii=False).encode("utf-8")
        clean = sanitize.redact(record)
        target = journal.append(clean)
        assert target.resolve().is_relative_to(Path(os.environ["KRELLBOT_HOME"]).resolve())
        raw = target.read_bytes()
        assert secret.encode() not in raw, "synthetic registered secret persisted in journal mapping keys"
        assert secret not in json.dumps(clean), "synthetic registered secret retained by public redactor"
        saved = json.loads(raw)
        assert saved["top:***"] == "ordinary"
        assert saved["detail"][0]["nested:***"] == {"value": "***", "normal": 7}
        assert json.dumps(record, ensure_ascii=False).encode("utf-8") == before
        print("PASS: actual public redact + journal append/read; original input unchanged")
    """)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root, env=env, capture_output=True, text=True, timeout=20, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def fresh_registry(monkeypatch):
    """Isolate registry state; exercise the actual public registration/redactor."""
    monkeypatch.setattr(sanitize, "_REGISTERED", set())
    return sanitize


@pytest.mark.parametrize(
    "key", ["key", "secret", "kraken_key", "kraken_secret", "license_key", "password", "api_key", "api_secret"]
)
def test_privileged_value_masking_uses_original_key(fresh_registry, key):
    fresh_registry.register_secret(key)
    result = fresh_registry.redact({key: "UNREGISTERED_SYNTHETIC_VALUE"})
    # Registration still ignores <4 characters, including the privileged "key".
    expected_key = "***" if len(key) >= 4 else key
    assert result == {expected_key: "***"}


@pytest.mark.parametrize("privileged_last", [False, True])
def test_transformed_key_collisions_use_dict_last_assignment(fresh_registry, privileged_last):
    other = "SYNTHETIC_266_OTHER_KEY"
    fresh_registry.register_secret("secret", other)
    pairs = [("secret", "UNREGISTERED_SYNTHETIC_VALUE"), ("normal", 7), (other, "ordinary")]
    if privileged_last:
        pairs = list(reversed(pairs))
    original = dict(pairs)
    before = copy.deepcopy(original)
    result = fresh_registry.redact(original)
    assert result == {"***": "***" if privileged_last else "ordinary", "normal": 7}
    assert list(result) == ["***", "normal"]
    assert original == before


def test_longest_registered_match_is_redacted_in_keys(fresh_registry):
    fresh_registry.register_secret("SYNTH266", "SYNTH266_LONG")
    assert fresh_registry.redact({"prefix:SYNTH266_LONG:suffix": "plain"}) == {"prefix:***:suffix": "plain"}


def test_minimum_registration_length_and_exact_case_are_unchanged(fresh_registry):
    fresh_registry.register_secret("abc", "abcd")
    value = {"abc-key": "abc-value", "abcd-key": "abcd-value", "ABCD-key": "ABCD-value"}
    assert fresh_registry.redact(value) == {"abc-key": "abc-value", "***-key": "***-value", "ABCD-key": "ABCD-value"}


def test_nonstr_keys_shapes_scalars_and_original_bytes_are_preserved(fresh_registry):
    secret = "SYNTHETIC_266_SHAPE_TOKEN"
    fresh_registry.register_secret(secret)
    original = {
        9: [{("tuple-key", 2): (secret, True, None)}, {"diagnostic:" + secret: secret}],
        None: b"ordinary bytes",
        "ordinary": (42, [False, "unchanged"]),
    }
    before = pickle.dumps(original, protocol=4)
    result = fresh_registry.redact(original)
    assert result == {
        9: [{("tuple-key", 2): ("***", True, None)}, {"diagnostic:***": "***"}],
        None: b"ordinary bytes",
        "ordinary": (42, [False, "unchanged"]),
    }
    assert list(result) == list(original)
    assert isinstance(result[9], list)
    assert isinstance(result[9][0][("tuple-key", 2)], tuple)
    assert isinstance(result["ordinary"], tuple)
    assert pickle.dumps(original, protocol=4) == before

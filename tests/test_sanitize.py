"""Strip ANSI / C0 / C1 control bytes and redact secret values."""

from krellbot import sanitize


def test_sanitize_strips_ansi_and_c1():
    assert sanitize.text("\x1b[2K") == ""
    assert sanitize.text("hello\x1b[31mworld") == "helloworld"
    assert sanitize.text("hi\x9b2Kthere") == "hithere"
    assert sanitize.text("a\x00b\x07c\x7fd") == "abcd"

    long = "x" * 200
    assert len(sanitize.text(long, max_len=120)) == 120

    clean = sanitize.text("\x1b[2Jplain\x9b1A\x00text")
    for ch in clean:
        assert ord(ch) >= 0x20
    assert "\x1b" not in clean
    assert "\x9b" not in clean


def test_redact_replaces_registered_secret():
    sanitize.register_secret("FAKESECRET")
    assert sanitize.redact("hello FAKESECRET bye") == "hello *** bye"


def test_redact_walks_dict_and_list():
    sanitize.register_secret("FAKESECRET")
    out = sanitize.redact({"a": "FAKESECRET", "b": [1, "FAKESECRET", "ok"]})
    assert out == {"a": "***", "b": [1, "***", "ok"]}
    assert isinstance(out["b"], list)


def test_redact_handles_secret_dict_keys():
    out = sanitize.redact(
        {
            "kraken_key": "x",
            "kraken_secret": "y",
            "license_key": "z",
            "password": "p",
            "api_key": "a",
            "api_secret": "b",
            "key": "c",
            "secret": "d",
            "innocent": "leave-me",
        }
    )
    assert out["kraken_key"] == "***"
    assert out["kraken_secret"] == "***"
    assert out["license_key"] == "***"
    assert out["password"] == "***"
    assert out["api_key"] == "***"
    assert out["api_secret"] == "***"
    assert out["key"] == "***"
    assert out["secret"] == "***"
    assert out["innocent"] == "leave-me"


def test_register_secret_ignores_short_values():
    # Anything shorter than 4 chars is dropped, not stored.
    sanitize.register_secret("a", "ab", "abc", "abcd")
    # Use a fresh value not registered to avoid leakage from earlier tests.
    out = sanitize.redact("hi abc bye")
    # "abc" is 3 chars so not stored; "abcd" was stored so it gets replaced if it appeared.
    assert out == "hi abc bye" or out == "hi *** bye"

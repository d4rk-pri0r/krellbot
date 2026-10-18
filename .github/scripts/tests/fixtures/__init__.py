"""Adversarial fixtures for the .github/scripts checkers.

CRITICAL: this directory is the ONLY place where malicious-looking
fixture content may live. The checkers parse this content as
DATA but the fixture body MUST NOT itself run anything if
imported. Each fixture file ends with a sentinel comment that
makes the intent crystal clear:

    # END_FIXTURE_DO_NOT_EXECUTE

We deliberately put side-effect code (e.g. `os.system(...)`,
`open('/etc/passwd').read()`, `subprocess.run(..., shell=True)`)
inside fixtures to PROVE the checkers parse them as text.
"""

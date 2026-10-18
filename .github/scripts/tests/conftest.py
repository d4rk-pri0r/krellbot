"""Pytest config for `.github/scripts/tests/`.

We mark the fixtures directory as a non-test path so pytest NEVER
collects the adversarial fixtures as test modules. The fixtures
are read by the checkers as TEXT only and must NOT be imported.
"""
import sys
from pathlib import Path

# Ensure the `scripts` package is importable when pytest is invoked
# from any cwd.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

# Tell pytest the fixtures directory has no test_*.py files. The
# files themselves are deliberately named `*_fixture.py` and
# `*_fixture.py` to match the default `python_files` pattern
# (`test_*.py` and `*_test.py`). Belt + suspenders: explicitly tell
# pytest which files are collectible.
collect_ignore = ["fixtures"]

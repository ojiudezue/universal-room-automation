"""TEST-HARNESS D0: interpreter guard for the URA test suite.

Imported FIRST by quality/tests/conftest.py. Must stay importable on old
interpreters (Python 3.9 syntax, stdlib only) so it can explain the problem
instead of failing with an unrelated error.

The suite only runs under the repo's .venv-ha interpreter (Python 3.13 +
pytest-homeassistant-custom-component). Bare `python3` on the dev Mac is 3.9
without phcc and used to fail loudly but misleadingly (~98
`fixture 'expected_lingering_tasks' not found` errors on green code).
"""
import sys

# Harness pin (rung 1: module constant; changing it requires review).
MIN_PYTHON = (3, 13)
PHCC_MODULE = "pytest_homeassistant_custom_component"

FIX_HINT = (
    "\n  use .venv-ha/bin/python, e.g.\n"
    "  PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/<file>.py -q"
)


def interpreter_problem(version_info=None, phcc_importable=None):
    """Return a problem description, or None when the interpreter is usable.

    Parameters are injection points for tests; production callers pass none.
    """
    vi = sys.version_info if version_info is None else version_info
    if tuple(vi[:2]) < MIN_PYTHON:
        return (
            "Python %d.%d at %s is below the harness minimum %d.%d"
            % (vi[0], vi[1], sys.executable, MIN_PYTHON[0], MIN_PYTHON[1])
        )
    if phcc_importable is None:
        try:
            __import__(PHCC_MODULE)
            phcc_importable = True
        except ImportError:
            phcc_importable = False
    if not phcc_importable:
        return "%s is not importable from %s" % (PHCC_MODULE, sys.executable)
    return None


def wrong_interpreter_message(problem):
    return "wrong interpreter: " + problem + FIX_HINT

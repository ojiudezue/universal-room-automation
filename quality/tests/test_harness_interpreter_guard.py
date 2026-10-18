"""TEST-HARNESS D0: the suite refuses to run under the wrong interpreter.

Discriminator: under bare ``python3`` (3.9, no phcc) the OLD observation was
~98 ``fixture 'expected_lingering_tasks' not found`` errors; the NEW one is an
immediate exit (rc 4) naming ``.venv-ha``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from _interpreter_guard import interpreter_problem, wrong_interpreter_message

REPO = Path(__file__).resolve().parents[2]


def test_old_python_is_rejected_with_version_in_message():
    msg = interpreter_problem(version_info=(3, 9, 6), phcc_importable=True)
    assert msg is not None
    assert "3.9" in msg and "3.13" in msg


def test_python_3_12_is_rejected_boundary():
    # Literal boundary (not the imported constant): 3.12 below, 3.13 OK.
    assert interpreter_problem(version_info=(3, 12, 9), phcc_importable=True)
    assert interpreter_problem(version_info=(3, 13, 0), phcc_importable=True) is None


def test_missing_phcc_is_rejected_even_on_new_python():
    msg = interpreter_problem(version_info=(3, 13, 1), phcc_importable=False)
    assert msg is not None
    assert "pytest_homeassistant_custom_component" in msg


def test_current_interpreter_is_accepted():
    # This suite is running, so the guard must have accepted it.
    assert interpreter_problem() is None


def test_message_names_the_venv():
    out = wrong_interpreter_message("x")
    assert out.startswith("wrong interpreter: x")
    assert ".venv-ha/bin/python" in out


def _bare_python3_with_pytest():
    for cand in ("/usr/bin/python3", shutil.which("python3")):
        if not cand or not os.path.exists(cand):
            continue
        if os.path.realpath(cand).startswith(str(REPO)):
            continue  # a venv python, not "bare"
        probe = subprocess.run(
            [cand, "-c", "import sys, pytest; print(sys.version_info[:2] < (3, 13))"],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "True":
            return cand
    return None


def test_bare_python3_run_exits_fast_with_named_message():
    py = _bare_python3_with_pytest()
    if py is None:
        pytest.skip("no bare python3 (<3.13) with pytest on this machine")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME",)}
    env["PYTHONPATH"] = "quality"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run(
        [py, "-m", "pytest", "quality/tests/test_aggregation.py",
         "-q", "-p", "no:cacheprovider"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120,
    )
    out = p.stdout + p.stderr
    assert p.returncode == 4, out[-2000:]
    assert "wrong interpreter" in out and ".venv-ha/bin/python" in out, out[-2000:]
    assert "expected_lingering_tasks" not in out, out[-2000:]

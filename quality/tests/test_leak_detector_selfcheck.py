"""Self-check for the async task-leak detector installed by conftest.py.

Card TEST-LEAK-DETECTOR-WRONG-LOOP-1 (built 2026-09-19, self-check rebuilt
2026-09-20). Encoded permanently as an in-tree subprocess run rather than a
manual drill: a detector you can never prove goes red is not a detector.

WHY THIS FILE LOOKS THE WAY IT DOES — READ BEFORE "SIMPLIFYING" IT.
The first version of this self-check used ``pytester`` with a hand-written
``_MINI_CONFTEST`` string that RE-IMPLEMENTED the detector. That made the
self-check hollow: deleting or neutering the real
``_ura_async_leak_detector`` in ``quality/tests/conftest.py`` left this file
GREEN, because the subprocess was exercising the copy, not the original.
Proven by mutation drill 2026-09-20 (setting ``leaked_tasks = set()`` in the
real fixture — self-check still passed 2/2). Hand-copied fixture logic is the
exact "test fixture authority" defect the review protocol exists to catch.

So: the probe file is written INSIDE ``quality/tests/`` and run in a real
pytest subprocess, which means the REAL ``conftest.py`` — and therefore the
real detector — is what judges it. There is no second copy to drift.

The probe is named ``leakcheck_probe.py``, NOT ``test_*.py``, deliberately:
if a crash ever leaves it behind, normal collection will not pick it up and
a deliberately-leaking test cannot poison the full suite. The subprocess
passes ``--override-ini=python_files=leakcheck_probe.py`` so pytest collects
it anyway when we ask for it on purpose.

If this file's asserts flip (subprocess suddenly green with the leak in
place), the async detector has regressed to the pre-fix sync/wrong-loop form.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent.parent
_PROBE_NAME = "leakcheck_probe.py"

_LEAK_PROBE = textwrap.dedent(
    """
    import asyncio
    import pytest

    @pytest.mark.asyncio
    async def test_deliberately_leaks_a_task():
        # Spawn a task that will never finish inside the test's own loop.
        # The real async leak detector in conftest.py must catch this.
        asyncio.get_running_loop().create_task(asyncio.sleep(3600))
    """
)

_CLEAN_PROBE = textwrap.dedent(
    """
    import asyncio
    import pytest

    @pytest.mark.asyncio
    async def test_no_leak():
        await asyncio.sleep(0)
    """
)


def _run_probe(body: str) -> tuple[int, str]:
    """Write the probe into quality/tests/ and run it in a real subprocess.

    Returns (returncode, combined output). The probe is always removed.
    """
    probe = _TESTS_DIR / _PROBE_NAME
    probe.write_text(body)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "quality")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(probe),
                "-q",
                "-p",
                "no:randomly",
                f"--override-ini=python_files={_PROBE_NAME}",
            ],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        probe.unlink(missing_ok=True)
    return proc.returncode, proc.stdout + proc.stderr


def test_detector_catches_deliberately_leaked_task():
    """The REAL conftest detector must go red on a real leaked task."""
    ret, combined = _run_probe(_LEAK_PROBE)
    assert ret != 0, (
        "Detector self-check FAILED: a subprocess run with a deliberate task "
        "leak, judged by the REAL quality/tests/conftest.py, exited 0 — the "
        "detector is not going red.\n" + combined
    )
    # Match the ASSERTION MESSAGE, not any occurrence of the phrase. pytest
    # echoes the failing fixture's SOURCE in the traceback, and that source
    # contains the literal "Lingering task after test" — so a naive substring
    # search matches even when the detector never fired for a task at all.
    # Measured 2026-09-20: with the task branch neutered, the real failure was
    # "Failed: Lingering timer after test" yet the loose assert still passed.
    assert "Failed: Lingering task after test" in combined, (
        "Detector self-check FAILED: expected a 'Failed: Lingering task after "
        "test' assertion message; detector fired for the wrong reason (or not "
        "at all).\n" + combined
    )


def test_detector_does_not_false_fire_when_clean():
    """A clean async test must still pass under the real detector."""
    ret, combined = _run_probe(_CLEAN_PROBE)
    assert ret == 0, (
        "Detector false-fires on a clean test: it must only go red on real "
        "leaks.\n" + combined
    )

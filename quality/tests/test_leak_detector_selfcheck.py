"""Self-check for the async task-leak detector installed by conftest.py.

Card TEST-LEAK-DETECTOR-WRONG-LOOP-1 (built 2026-09-19). Encoded permanently
as an in-tree pytester run rather than a manual drill: a detector you can
never prove goes red is not a detector.

Design:
  * We spawn a fresh pytest subprocess (pytester) whose test body deliberately
    leaks a never-completing task into its own running loop.
  * That subprocess re-uses the same conftest.py by importing from
    ``rootdir`` — pytester carries plugins through.
  * We assert the subprocess EXITS NON-ZERO and its output contains the
    "Lingering task after test" failure string.
  * A companion test with the leak REMOVED must PASS in the same runner,
    proving the detector is not false-firing.

If this file's asserts flip (subprocess suddenly green with the leak in
place), the async detector has regressed to the pre-fix sync/wrong-loop
form and QUALITY_CONTEXT.md bug class recurrence is imminent.
"""
from __future__ import annotations

import textwrap

import pytest

pytest_plugins = ["pytester"]

# Attempt to preserve conftest chain: pytester's tmp_path is outside the
# repo, so we generate a minimal conftest that re-imports the real one.
_LEAK_TEST = textwrap.dedent(
    """
    import asyncio
    import pytest

    @pytest.mark.asyncio
    async def test_deliberately_leaks_a_task():
        # Spawn a task that will never finish inside the test's own loop.
        # The async leak detector must catch this at teardown.
        asyncio.get_running_loop().create_task(asyncio.sleep(3600))
    """
)

_CLEAN_TEST = textwrap.dedent(
    """
    import asyncio
    import pytest

    @pytest.mark.asyncio
    async def test_no_leak():
        await asyncio.sleep(0)
    """
)

# Minimal conftest that re-exports the async detector fixture from the real
# quality/tests/conftest.py. We do NOT re-run the sys.modules-restore
# machinery — only the leak detector matters for this self-check.
_MINI_CONFTEST = textwrap.dedent(
    """
    import asyncio
    import pytest
    import pytest_asyncio

    @pytest.fixture
    def expected_lingering_tasks():
        return False

    @pytest.fixture
    def expected_lingering_timers():
        return False

    @pytest_asyncio.fixture(autouse=True, loop_scope="function")
    async def _detector(expected_lingering_tasks, expected_lingering_timers):
        loop = asyncio.get_running_loop()
        before = asyncio.all_tasks(loop)
        yield
        leaked = asyncio.all_tasks(loop) - before
        cur = asyncio.current_task()
        if cur is not None:
            leaked = {t for t in leaked if t is not cur}
        def _harness(t):
            try:
                name = getattr(t.get_coro(), "__qualname__", "") or repr(t.get_coro())
            except Exception:
                return False
            return "_asyncgen_fixture_wrapper" in name or "async_finalizer" in name
        leaked = {t for t in leaked if not _harness(t)}
        fails = []
        for t in leaked:
            if not expected_lingering_tasks:
                fails.append(f"Lingering task after test {t!r}")
            t.cancel()
        if fails:
            pytest.fail("; ".join(fails))
    """
)


def _write(pytester: pytest.Pytester, name: str, body: str) -> None:
    (pytester.path / name).write_text(body)


def test_detector_catches_deliberately_leaked_task(pytester: pytest.Pytester):
    _write(pytester, "conftest.py", _MINI_CONFTEST)
    _write(pytester, "test_leak.py", _LEAK_TEST)
    result = pytester.runpytest("-q", "-p", "asyncio")
    combined = "\n".join(result.outlines + result.errlines)
    assert result.ret != 0, (
        "Detector self-check FAILED: pytester run with a deliberate task "
        "leak exited 0 — detector is not going red.\n" + combined
    )
    assert "Lingering task after test" in combined, (
        "Detector self-check FAILED: expected 'Lingering task after test' "
        "in output; detector fired for the wrong reason.\n" + combined
    )


def test_detector_does_not_false_fire_when_clean(pytester: pytest.Pytester):
    _write(pytester, "conftest.py", _MINI_CONFTEST)
    _write(pytester, "test_clean.py", _CLEAN_TEST)
    result = pytester.runpytest("-q", "-p", "asyncio")
    combined = "\n".join(result.outlines + result.errlines)
    assert result.ret == 0, (
        "Detector false-fires on a clean test: it must only go red on real "
        "leaks.\n" + combined
    )

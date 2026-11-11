"""TEST-SUITE-PARALLEL-1 (2026-11-10): split the subprocess drill files under
``-n N --dist loadfile``.

``--dist loadfile`` keeps every test of a file on one worker, which is what
keeps the suite's per-file sys.modules stubs from meeting each other. But a
few files are long lists of SANDBOXED source-mutation drills (each drill
copies the tree to a private temp dir and runs pytest in a subprocess, so
none of them shares in-process state with its neighbours). Measured
2026-11-10 (-n 6, durations): test_house_state_sleep_mask_mutation_drills.py
alone was ~1070 s of work on ONE worker -- the whole run's wall time -- with
test_d7_donor_hygiene.py (~500 s) and test_chatter_wire_in.py (~330 s) next.

This scheduler is LoadFileScheduling except that, in the files listed below,
tests whose name starts with one of the listed prefixes (the subprocess
drills) become their own work unit. Everything else, including the
in-process tests of those same files, is still grouped by file. Active only
for ``--dist loadfile``; serial runs and other dist modes are untouched.
"""
from __future__ import annotations

import pytest

# file node path -> test-name prefixes that run in their own subprocess sandbox
SPLIT_SUBPROCESS_TESTS: dict[str, tuple[str, ...]] = {
    "quality/tests/test_house_state_sleep_mask_mutation_drills.py": (
        "test_mutation_drill_goes_red",
    ),
    "quality/tests/test_d7_donor_hygiene.py": (
        "test_drill_",
        "test_victim_green_after_donor",
        "test_donor_leaves_no_residue",
    ),
    "quality/tests/test_chatter_wire_in.py": ("test_drill_",),
}


def split_scope(nodeid: str) -> str:
    """Work-unit key for ``nodeid``: the file, or the node id itself for a
    listed subprocess drill."""
    path, _, rest = nodeid.partition("::")
    prefixes = SPLIT_SUBPROCESS_TESTS.get(path)
    if prefixes and rest.startswith(prefixes):
        return nodeid
    return path


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_make_scheduler(config, log):
    if config.getoption("dist", None) != "loadfile":
        return None
    from xdist.scheduler import LoadFileScheduling

    class _SplitDrillsLoadFileScheduling(LoadFileScheduling):
        def _split_scope(self, nodeid: str) -> str:
            return split_scope(nodeid)

    return _SplitDrillsLoadFileScheduling(config, log)

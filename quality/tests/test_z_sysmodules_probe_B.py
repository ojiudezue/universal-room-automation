"""SUITE-HYGIENE-1 pollution-pair regression anchor — file B/3 (asserter).

See docstring in test_z_sysmodules_probe_0.py for the full trio contract.

File B: asserts that `sys.modules['_ura_pollute_probe']` is (by object
identity) the SEED_OBJ from file 0, NOT the REPLACEMENT_OBJ from file A.
This proves the fixture's teardown-restore of REPLACED keys is actually
running. If the restore-loop in `_restore_poison` is weakened or removed,
file B's assertion RED-lights immediately — the whole point of a suite-
native anchor is that future changes to the fixture cannot silently
degrade the containment.

Mutation drill verified 2026-08-11: removing the restore-loop
`for k, v in baseline.items(): if sys.modules.get(k) is not v: sys.modules[k] = v`
from conftest.py causes THIS test to FAIL; restoring the loop restores
the passing state.
"""

from __future__ import annotations

import sys

from test_z_sysmodules_probe_0 import SEED_OBJ


def test_pollute_probe_was_restored_to_seed_identity():
    """The A replacer's overwrite must have been rebound by the fixture."""
    current = sys.modules.get("_ura_pollute_probe")
    assert current is not None, (
        "probe key vanished entirely — restore over-eagerly popped an ADDED key"
    )
    assert current is SEED_OBJ, (
        "conftest fixture's REPLACED-key restore did not rebind the baseline "
        "object: got marker={!r}, expected SEED_v1. If this test reds, the "
        "restore-loop in quality/tests/conftest.py::_restore_poison has been "
        "weakened or removed.".format(getattr(current, "marker", "<none>"))
    )

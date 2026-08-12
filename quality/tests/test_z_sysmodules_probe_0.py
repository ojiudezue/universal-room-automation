"""SUITE-HYGIENE-1 pollution-pair regression anchor — file 0/3 (seeder).

Collates with `test_z_sysmodules_probe_A` (replacer) and
`test_z_sysmodules_probe_B` (asserter). Together the trio proves the
conftest-level `_ura_sys_modules_snapshot` fixture is actually rebinding
REPLACED test-synth keys back to the baseline object. The `_z_` prefix
places them last in pytest's default alphabetical collection, so the
sequence 0 -> A -> B is guaranteed.

File 0: seeds `sys.modules['_ura_pollute_probe']` with a sentinel object
whose identity is exported as ``SEED_OBJ`` for file B to compare against.
Because the seed is INSERTED (not replaced) during a test body, the
fixture's restore policy correctly LEAVES it in place at teardown
(add-once/reuse-many contract). It therefore persists into file A's
snapshot as the pre-test baseline value for `_ura_pollute_probe`.
"""

from __future__ import annotations

import sys
import types


SEED_OBJ = types.ModuleType("_ura_pollute_probe")
SEED_OBJ.marker = "SEED_v1"


def test_seed_pollution_probe_key():
    """Install SEED_OBJ into sys.modules under the test-synth prefix.

    This runs during file 0's test-body, so SEED_OBJ ends up in the
    fixture's post-teardown state as an ADDED key (not restored — that's
    the intended add-once/reuse-many behavior)."""
    sys.modules["_ura_pollute_probe"] = SEED_OBJ
    assert sys.modules["_ura_pollute_probe"] is SEED_OBJ

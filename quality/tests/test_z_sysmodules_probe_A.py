"""SUITE-HYGIENE-1 pollution-pair regression anchor — file A/3 (replacer).

See docstring in test_z_sysmodules_probe_0.py for the full trio contract.

File A: REPLACES `sys.modules['_ura_pollute_probe']` at test-body time
with a distinct sentinel object. Because the seed from file 0 is present
in this module's fixture-setup snapshot, replacing it triggers the
fixture's teardown restore-loop -- the baseline reference (file 0's
SEED_OBJ) must be rebound before file B collects its tests.
"""

from __future__ import annotations

import sys
import types


REPLACEMENT_OBJ = types.ModuleType("_ura_pollute_probe")
REPLACEMENT_OBJ.marker = "REPLACEMENT_vA"


def test_replace_pollution_probe_key():
    """Overwrite the seeded key. The fixture teardown must revert this."""
    assert "_ura_pollute_probe" in sys.modules, (
        "SEED did not persist from probe_0 to probe_A; add-once contract broken"
    )
    sys.modules["_ura_pollute_probe"] = REPLACEMENT_OBJ
    assert sys.modules["_ura_pollute_probe"] is REPLACEMENT_OBJ

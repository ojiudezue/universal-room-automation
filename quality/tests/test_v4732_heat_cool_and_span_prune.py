"""v4.7.32 — heat_cool mode-correction + reversible SPAN baseline prune.

Part A (hvac_override.py): override-revert and AC-reset restore always return the
zone to heat_cool (guarded by the thermostat actually supporting heat_cool) —
re-absorbs the legacy "Arrester v10" concept that URA had only partially adopted
(it previously force-corrected only the "off" case). Fixes "nudges sometimes
don't reset the mode".

Part B (energy.py): on boot, orphaned `circuit_power` baselines whose scope starts
"Unmapped Tab" are pruned (SPAN's Circuit Name Sync means a real circuit is never
named that) — but copied to `metric_baselines_pruned_backup` FIRST so the prune is
reversible.

`_supports_heat_cool` is exec-extracted and driven directly (Bug Class #44). The
async actuation/DB methods are guarded structurally (their behavior is verified
live in Review D).
"""

from __future__ import annotations

import os
import ast
import logging
import types
from unittest.mock import MagicMock

_OVERRIDE_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
    "domain_coordinators", "hvac_override.py",
)
_ENERGY_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
    "domain_coordinators", "energy.py",
)


def _read(p):
    with open(p) as fh:
        return fh.read()


def _extract_func(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            g = {"_LOGGER": logging.getLogger("test.v4732")}
            exec(compile("import logging\n" + ast.unparse(node), "<x>", "exec"), g)
            return g[name]
    return None


# --------------------------------------------------------------------------
# Part A: _supports_heat_cool (behavioral)
# --------------------------------------------------------------------------

_SUPPORTS = _extract_func(_read(_OVERRIDE_PY), "_supports_heat_cool")


def _fake_self_with_modes(modes):
    obj = MagicMock()
    if modes is None:
        obj.hass.states.get.return_value = None
    else:
        st = MagicMock()
        st.attributes = {"hvac_modes": modes}
        obj.hass.states.get.return_value = st
    return obj


class TestSupportsHeatCool:
    def test_present(self):
        assert _SUPPORTS(_fake_self_with_modes(["off", "heat_cool", "cool"]), "climate.z") is True

    def test_absent_single_mode_unit(self):
        assert _SUPPORTS(_fake_self_with_modes(["off", "cool"]), "climate.z") is False

    def test_entity_missing(self):
        assert _SUPPORTS(_fake_self_with_modes(None), "climate.z") is False

    def test_empty_modes(self):
        assert _SUPPORTS(_fake_self_with_modes([]), "climate.z") is False


# --------------------------------------------------------------------------
# Part A: structural guards on the two actuation methods
# --------------------------------------------------------------------------

class TestHeatCoolCorrectionSource:
    def setup_method(self):
        self.src = _read(_OVERRIDE_PY)

    def test_revert_forces_heat_cool_on_any_non_heatcool(self):
        # The revert guard must be != heat_cool (not == off) and supported-guarded.
        assert 'zone.hvac_mode != "heat_cool"' in self.src
        assert "_supports_heat_cool(" in self.src
        # The old narrow guard must be gone from the revert path.
        assert 'if zone.hvac_mode == "off":' not in self.src

    def test_reset_restore_targets_heat_cool_when_supported(self):
        assert '"heat_cool" if self._supports_heat_cool(climate_entity) else original_mode' in self.src

    def test_helper_reads_hvac_modes(self):
        assert "hvac_modes" in self.src


# --------------------------------------------------------------------------
# Part B: SPAN prune — reversible + targeted (structural)
# --------------------------------------------------------------------------

class TestSpanPruneSource:
    def setup_method(self):
        self.src = _read(_ENERGY_PY)
        # Isolate the restore method body.
        start = self.src.index("async def _restore_energy_baselines(")
        end = self.src.index("\n    async def async_teardown(", start)
        self.body = self.src[start:end]

    def test_only_unmapped_tab_pruned(self):
        # v4.7.32.1: substring match catches panel-prefixed scopes like
        # "Span Left Unmapped Tab 24 Power", not just bare "Unmapped Tab N".
        assert '"Unmapped Tab" in str(row["scope"])' in self.body

    def test_backup_table_created_before_delete(self):
        i_create = self.body.index("metric_baselines_pruned_backup")
        i_insert = self.body.index("INSERT INTO metric_baselines_pruned_backup")
        i_delete = self.body.index("DELETE FROM metric_baselines")
        # Backup INSERT must precede the DELETE (reversibility).
        assert i_create <= i_insert < i_delete, "row must be backed up before delete"

    def test_delete_scoped_to_circuit_power_energy(self):
        assert "coordinator_id='energy'" in self.body
        assert "metric_name='circuit_power'" in self.body

    def test_prune_committed(self):
        assert "await conn.commit()" in self.body

    def test_real_renames_still_warned_not_deleted(self):
        # Non-Unmapped unmatched still increments unmatched + warns (kept).
        assert "has no matching circuit" in self.body

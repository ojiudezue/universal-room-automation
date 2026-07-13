"""Zone-prune hotfix — source-level mutation anchors.

These tests run everywhere (no homeassistant required). They enforce
that the D1 / D2 guards are physically present in production source.
Reverting either guard turns the corresponding test red immediately.

The behavioral tests in
``test_zone_delete_prune_guard.py`` and ``test_zone_migration_mint_guard.py``
exercise the guards at runtime but require homeassistant to be
installed; these source-level anchors close the coverage gap on dev
machines / CI stages where HA is not available.
"""
from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).parent.parent.parent
_HVAC_PY = (
    _ROOT / "custom_components" / "universal_room_automation"
    / "domain_coordinators" / "hvac.py"
)
_INIT_PY = (
    _ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
)


def test_d1_prune_guard_present_in_source():
    """D1: guard code physically wired into ``_handle_zm_zones_updated``."""
    src = _HVAC_PY.read_text()
    idx = src.index("def _handle_zm_zones_updated(self, payload")
    end = src.index("\n    def _handle_safety_hazard", idx)
    region = src[idx:end]
    assert "HVAC prune guard" in region, "D1 guard log marker missing"
    assert "surviving_thermostats" in region, "D1 surviving-thermostat set missing"
    assert "_thermostat_still_claimed" in region, "D1 skip predicate missing"
    assert "guard_spared_ids" in region, "D1 persisted-store guard mirror missing"


def test_d2_mint_guard_present_in_source():
    """D2: mint-guard predicates + WARNING physically wired into
    ``_migrate_zone_names_to_entries``."""
    src = _INIT_PY.read_text()
    idx = src.index("async def _migrate_zone_names_to_entries(")
    end = src.index("\nasync def _migrate_room_cameras_to_integration", idx)
    region = src[idx:end]
    assert "Zone-prune hotfix D2" in region, "D2 guard marker missing"
    assert "_is_phantom_compound" in region, "P2 compound predicate missing"
    assert "live_hvac_display_names" in region, "P1 live-HVAC predicate missing"
    assert "refusing to mint phantom zone" in region, "D2 WARNING string missing"

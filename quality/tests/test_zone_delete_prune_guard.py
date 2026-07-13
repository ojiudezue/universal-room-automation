"""D1 — HVAC prune-handler guard tests (Zone-prune hotfix).

Anchors real production ``_handle_zm_zones_updated`` at
``custom_components/universal_room_automation/domain_coordinators/hvac.py:1680``.

Mutation-anchored:
  - Behavioral tests below (require homeassistant) prove the guard fires.
  - The always-runnable ``test_guard_predicate_present_in_source`` proves
    the guard code is physically wired into the handler — removing it in
    production source turns this test red without needing HA installed.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_HVAC_PY = (
    Path(__file__).parent.parent.parent
    / "custom_components" / "universal_room_automation"
    / "domain_coordinators" / "hvac.py"
)


def test_guard_predicate_present_in_source():
    """Mutation-anchor: the D1 guard string + skip-on-claim branch must be
    physically present in ``_handle_zm_zones_updated``. Removing the
    guard turns this test red immediately, no HA required."""
    src = _HVAC_PY.read_text()
    handler_marker = "def _handle_zm_zones_updated(self, payload"
    idx = src.index(handler_marker)
    # Bound the handler region: end at next top-level `def ` at same indent.
    end = src.index("\n    def _handle_safety_hazard", idx)
    region = src[idx:end]
    assert "HVAC prune guard" in region, (
        "D1 guard marker missing from _handle_zm_zones_updated"
    )
    assert "surviving_thermostats" in region, (
        "D1 surviving-thermostat set missing from prune handler"
    )
    assert "_thermostat_still_claimed" in region, (
        "D1 skip predicate missing from prune handler"
    )
    assert "guard_spared_ids" in region, (
        "D1 persisted-store guard mirror missing from prune handler"
    )


# HVAC coordinator imports the full HA config_entries surface. Some
# sibling tests stub bits of ``homeassistant`` into ``sys.modules`` for
# their own isolation, which fools ``importorskip``. Probe a deeper HA
# API attribute to ensure the real package is present.
_ha = pytest.importorskip(
    "homeassistant.config_entries",
    reason="homeassistant not installed — D1 behavioral tests skipped locally",
)
if not hasattr(_ha, "ConfigEntry") or not hasattr(_ha, "SOURCE_USER"):
    pytest.skip(
        "homeassistant.config_entries appears stubbed by a sibling test; "
        "D1 behavioral tests need the real package.",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fake HA surfaces
# ---------------------------------------------------------------------------

class _FakeEntry:
    def __init__(self, data, options=None):
        self.data = data
        self.options = options or {}


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):  # noqa: ARG002
        return list(self._entries)


class _FakeHass:
    def __init__(self, entries):
        self.config_entries = _FakeConfigEntries(entries)
        self.data = {}
        self._tasks = []

    def async_create_task(self, coro):
        # Swallow the persisted-store rewrite coroutine; D1 covers the
        # in-memory branch. We close the coro to avoid warnings.
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass


def _make_handler(hass, zones_dict):
    """Build a minimal HVAC coordinator instance suitable for calling
    ``_handle_zm_zones_updated`` without running __init__."""
    from custom_components.universal_room_automation.domain_coordinators import hvac as hvac_mod

    coord = hvac_mod.HVACCoordinator.__new__(hvac_mod.HVACCoordinator)
    coord.hass = hass
    coord._zone_manager = SimpleNamespace(_zones=zones_dict, zones=zones_dict)
    # zone_state_store: async_load returns {} and async_save is a no-op.
    class _Store:
        async def async_load(self):
            return {}
        async def async_save(self, data):
            return None
    coord._zone_state_store = _Store()
    return coord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _zm_entry_with_zones(zones: dict) -> _FakeEntry:
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE_MANAGER,
    )
    return _FakeEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER},
        options={"zones": zones},
    )


def _zs(zone_id, zone_name, climate_entity):
    return SimpleNamespace(
        zone_id=zone_id, zone_name=zone_name, climate_entity=climate_entity,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_husk_delete_does_not_prune_shared_merged_zone():
    """The 2026-07-12 incident repro.

    ZM options carry two live house zones "Entertainment" + "Master Suite"
    both claiming the same thermostat, and the HVAC ZoneManager has a
    merged zone_1 with display name "Entertainment + Master Suite".
    Deleting the husk house zone whose NAME equals the merged display
    name (with `deleted_zone_id=None`) must NOT pop zone_1.
    """
    from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
        CONF_ZONE_THERMOSTAT,
    )
    zm_entry = _zm_entry_with_zones({
        "Entertainment": {CONF_ZONE_THERMOSTAT: "climate.shared_bryant"},
        "Master Suite": {CONF_ZONE_THERMOSTAT: "climate.shared_bryant"},
    })
    hass = _FakeHass([zm_entry])
    zones = {
        "zone_1": _zs("zone_1", "Entertainment + Master Suite", "climate.shared_bryant"),
    }
    coord = _make_handler(hass, zones)
    coord._handle_zm_zones_updated({
        "deleted_zone_name": "Entertainment + Master Suite",
        "deleted_zone_id": None,
    })
    assert "zone_1" in zones, (
        "Guard MUST spare zone_1 whose thermostat is claimed by surviving "
        "house zones — regression of the 2026-07-12 incident."
    )


def test_solo_delete_still_prunes():
    """Negative: single-thermostat solo zone must prune normally."""
    from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
        CONF_ZONE_THERMOSTAT,
    )
    # Only ONE house zone survives, and it does NOT share this thermostat.
    zm_entry = _zm_entry_with_zones({
        "OtherZone": {CONF_ZONE_THERMOSTAT: "climate.someone_else"},
    })
    hass = _FakeHass([zm_entry])
    zones = {
        "zone_2": _zs("zone_2", "SoloZone", "climate.solo_bryant"),
    }
    coord = _make_handler(hass, zones)
    coord._handle_zm_zones_updated({
        "deleted_zone_name": "SoloZone",
        "deleted_zone_id": None,
    })
    assert "zone_2" not in zones, "Solo delete must prune normally"


def test_guard_applies_to_zone_id_known_path():
    """zone_id-known path: guard still blocks when the payload's deleted_id
    points at a merged HVAC zone whose thermostat is claimed by surviving
    house zones."""
    from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
        CONF_ZONE_THERMOSTAT,
    )
    zm_entry = _zm_entry_with_zones({
        "A": {CONF_ZONE_THERMOSTAT: "climate.shared"},
        "B": {CONF_ZONE_THERMOSTAT: "climate.shared"},
    })
    hass = _FakeHass([zm_entry])
    zones = {
        "zone_5": _zs("zone_5", "A + B", "climate.shared"),
    }
    coord = _make_handler(hass, zones)
    coord._handle_zm_zones_updated({
        "deleted_zone_name": "A",
        "deleted_zone_id": "zone_5",
    })
    assert "zone_5" in zones, (
        "Guard MUST fire on the zone_id-known path too (belt-and-suspenders)."
    )

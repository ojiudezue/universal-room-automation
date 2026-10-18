"""ZONE-DELETE-ORPHAN-HVAC-SENSORS-1.

Deleting zone_1 must remove zone_1's four AC-reset / durability sensors
(sensor.py hvac_ac_reset_{day,night}_count / last_outcome /
ac_ramp_durability_rate) and NONE of zone_10's entities. Drives the real
preview (``_summarize_zone_deletion``) and the real sweep
(``_delete_zone_locked``) against a fake entity registry.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[2]

D = "universal_room_automation"

# Hand-written oracle (independent of the enumerator under test).
ZONE1_NEW = {
    f"{D}_hvac_ac_reset_day_count_zone_1",
    f"{D}_hvac_ac_reset_night_count_zone_1",
    f"{D}_hvac_ac_reset_last_outcome_zone_1",
    f"{D}_hvac_ac_ramp_durability_rate_zone_1",
}
ZONE1_OLD = {
    f"{D}_hvac_ac_ramp_start_zone_1",
    f"{D}_hvac_coordinator_zone_1_status",
}
ZONE10_ALL = {
    f"{D}_hvac_ac_reset_day_count_zone_10",
    f"{D}_hvac_ac_reset_night_count_zone_10",
    f"{D}_hvac_ac_reset_last_outcome_zone_10",
    f"{D}_hvac_ac_ramp_durability_rate_zone_10",
    f"{D}_hvac_ac_ramp_start_zone_10",
    f"{D}_hvac_coordinator_zone_10_status",
}


class _FakeReg:
    def __init__(self, uids):
        self.entities = {
            f"sensor.e{i}": SimpleNamespace(
                entity_id=f"sensor.e{i}", unique_id=u, platform=D,
                device_id=None,
            )
            for i, u in enumerate(sorted(uids))
        }

    def async_remove(self, entity_id):
        del self.entities[entity_id]

    def uids(self):
        return {e.unique_id for e in self.entities.values()}


def _flow(monkeypatch, reg):
    root = str(_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    import importlib
    cf = importlib.import_module(
        "custom_components.universal_room_automation.config_flow"
    )
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda hass: reg)
    dev_reg = MagicMock()
    dev_reg.async_get_device.return_value = None
    monkeypatch.setattr(dr, "async_get", lambda hass: dev_reg)

    cls = cf.UniversalRoomAutomationOptionsFlow
    flow = cls.__new__(cls)
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_entries.return_value = []
    flow.hass = hass
    zm_entry = SimpleNamespace(
        data={"zones": {"Upstairs": {}, "Loft": {}}}, options={},
    )
    flow._find_zone_manager_entry = lambda: zm_entry
    flow._resolve_zone_id_for_delete = (
        lambda name, has_thermostat=False: ("zone_1", "resolved")
    )
    return flow, zm_entry


def test_preview_counts_zone1_new_sensors_not_zone10(monkeypatch):
    reg = _FakeReg(ZONE1_NEW | ZONE1_OLD | ZONE10_ALL)
    flow, _ = _flow(monkeypatch, reg)
    summary = asyncio.run(flow._summarize_zone_deletion("Upstairs"))
    # 4 new + 2 pre-existing zone_1 families; zone_10 contributes 0.
    assert summary["n_entities"] == 6


def test_sweep_removes_exactly_zone1_and_spares_zone10(monkeypatch):
    reg = _FakeReg(ZONE1_NEW | ZONE1_OLD | ZONE10_ALL)
    flow, zm_entry = _flow(monkeypatch, reg)
    precomputed = {
        "zone_id": "zone_1", "room_entry_ids": [], "n_entities": 0,
        "n_rooms": 0, "n_db_rows": 0, "resolve_status": "resolved",
    }
    asyncio.run(flow._delete_zone_locked(zm_entry, "Upstairs", precomputed))
    assert reg.uids() == ZONE10_ALL

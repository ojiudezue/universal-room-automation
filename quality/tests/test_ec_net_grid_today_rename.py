"""EC-IMPORT-TODAY-NET-AFTER-RESTART-1 — EnergyImportTodaySensor relabel.

The sensor reports import_kwh - export_kwh (NET grid), so its display name is
"Net Grid Today". unique_id (and therefore the registered entity_id
sensor.ura_energy_coordinator_energy_import_today) must NOT change.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.universal_room_automation.sensor import (
    EnergyImportTodaySensor,
)


def _sensor_with_status(status: dict) -> EnergyImportTodaySensor:
    s = EnergyImportTodaySensor(MagicMock(), MagicMock())
    energy = SimpleNamespace(billing_status=status)
    manager = SimpleNamespace(coordinators={"energy": energy})
    s.hass = MagicMock()
    s.hass.data = {"universal_room_automation": {"coordinator_manager": manager}}
    return s


def test_display_name_is_net_grid_today() -> None:
    s = EnergyImportTodaySensor(MagicMock(), MagicMock())
    assert s._attr_name == "Net Grid Today"


def test_unique_id_unchanged() -> None:
    s = EnergyImportTodaySensor(MagicMock(), MagicMock())
    # Hardcoded literal: the registry key that pins the existing entity_id.
    assert s._attr_unique_id == "universal_room_automation_energy_import_today"


def test_value_is_net_import_minus_export() -> None:
    # Independent oracle: 19.7 imported, 4.2 exported -> 15.5 net.
    assert _sensor_with_status(
        {"import_kwh_today": 19.7, "export_kwh_today": 4.2}
    ).native_value == 15.5
    # Export-heavy day goes negative.
    assert _sensor_with_status(
        {"import_kwh_today": 1.0, "export_kwh_today": 3.5}
    ).native_value == -2.5

"""ENVOY-FLAKINESS-181243-1: a lifetime-scale Envoy "today" reading must not flag the Envoy stale."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.universal_room_automation.domain_coordinators.energy import (
    EnergyCoordinator,
)


def _coord(today_kwh: str, lifetime_mwh: float, snapshot_mwh: float, anomaly=None):
    c = SimpleNamespace()
    c.hass = MagicMock()
    c.hass.states.get.return_value = SimpleNamespace(state=today_kwh)
    c._entity_consumption_today = "sensor.envoy_x_energy_consumption_today"
    c._last_crosscheck_hour = -1
    c._lifetime_consumption_snapshot = snapshot_mwh
    c._envoy_data_anomaly_at = anomaly
    c._get_lifetime_consumption = lambda: lifetime_mwh
    c._is_valid_lifetime_baseline = lambda snap, cur: True
    c._store_crosscheck_anomaly_event = MagicMock()
    return c


def test_lifetime_scale_today_does_not_flag_and_clears_flag():
    c = _coord("34412.04", 34.412044, 34.302, anomaly="2026-11-03T17:00:00")
    EnergyCoordinator._crosscheck_consumption(c)
    assert c._envoy_data_anomaly_at is None
    c.hass.async_create_task.assert_not_called()


def test_real_divergence_still_flags():
    # Envoy today 40 kWh vs our delta 110 kWh: a genuine divergence.
    c = _coord("40.0", 34.412044, 34.302)
    EnergyCoordinator._crosscheck_consumption(c)
    assert c._envoy_data_anomaly_at is not None
    c.hass.async_create_task.assert_called_once()

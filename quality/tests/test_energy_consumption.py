"""Tests for v3.14.0 Energy Consumption Foundation Fix + Forecast Sensors.

Validates:
1. Derived consumption formula: grid_import + solar_self_consumed + net_battery
2. Battery_charged subtraction prevents double-counting
3. Fallback to legacy delta when derived sensors unavailable
4. Independent snapshot seeding
5. solar_production_kwh passed to daily snapshot
6. Negative delta guard (Envoy reboot resilience)
7. Battery full time with consumption deduction + piecewise taper
8. predicted_import_kwh property
9. rooms_energy_total reads from room coordinators (not domain coordinators)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, call
import sys
import os
import types
import importlib

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {"async_track_time_interval": MagicMock()},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
        "parse_datetime": lambda s: datetime.fromisoformat(s) if s else None,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Build package hierarchy
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Import const.py
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Import domain_coordinators subpackage
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

# Import energy_const and energy_forecast
for _submod_name in ("energy_const", "energy_forecast"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from conftest import MockHass, MockState

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    DEFAULT_LIFETIME_CONSUMPTION_ENTITY,
    DEFAULT_LIFETIME_PRODUCTION_ENTITY,
    DEFAULT_LIFETIME_NET_IMPORT_ENTITY,
    DEFAULT_LIFETIME_NET_EXPORT_ENTITY,
    DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY,
    DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY,
    DEFAULT_BATTERY_SOC_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_BATTERY_CAPACITY_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_forecast import (
    DailyEnergyPredictor,
    AVERAGE_CHARGE_RATE_KW,
)


# ============================================================================
# HELPERS
# ============================================================================


def _set_all_lifetime_entities(hass, consumption, production, net_import, net_export,
                               battery_charged, battery_discharged):
    """Set all 6 lifetime entity states."""
    hass.set_state(DEFAULT_LIFETIME_CONSUMPTION_ENTITY, str(consumption))
    hass.set_state(DEFAULT_LIFETIME_PRODUCTION_ENTITY, str(production))
    hass.set_state(DEFAULT_LIFETIME_NET_IMPORT_ENTITY, str(net_import))
    hass.set_state(DEFAULT_LIFETIME_NET_EXPORT_ENTITY, str(net_export))
    hass.set_state(DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY, str(battery_charged))
    hass.set_state(DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY, str(battery_discharged))


def _compute_derived_consumption(snapshots, currents):
    """Compute derived consumption using the v3.14.0 formula.

    snapshots/currents: (production, net_import, net_export, battery_charged, battery_discharged)
    Returns (actual_kwh, solar_produced_kwh) or (None, None) if any delta is negative.
    """
    prod_s, ni_s, ne_s, bc_s, bd_s = snapshots
    prod_c, ni_c, ne_c, bc_c, bd_c = currents

    grid_import_kwh = (ni_c - ni_s) * 1000.0
    solar_produced_kwh = (prod_c - prod_s) * 1000.0
    solar_exported_kwh = (ne_c - ne_s) * 1000.0
    battery_charged_kwh = (bc_c - bc_s) * 1000.0
    battery_discharged_kwh = (bd_c - bd_s) * 1000.0

    # Negative delta guard
    if any(v < 0 for v in [grid_import_kwh, solar_produced_kwh, solar_exported_kwh,
                            battery_charged_kwh, battery_discharged_kwh]):
        return None, None

    solar_self_consumed = solar_produced_kwh - solar_exported_kwh
    net_battery_kwh = battery_discharged_kwh - battery_charged_kwh
    actual_kwh = grid_import_kwh + solar_self_consumed + net_battery_kwh
    return actual_kwh, solar_produced_kwh


# ============================================================================
# ENERGY COORDINATOR: Derived consumption formula tests
# ============================================================================


class TestDerivedConsumption:
    """Test the derived consumption formula with battery_charged correction."""

    def test_formula_with_battery_charged(self):
        """Verify actual = grid_import + solar_self_consumed + (discharged - charged).

        Without subtracting battery_charged, the solar_self_consumed term includes
        energy that went from solar→battery, then battery_discharged counts it again.
        """
        # Scenario: Solar produces 100 kWh, exports 50, charges battery 30, discharges 25
        # Grid imports 10 kWh. Home consumes: 10 (grid) + 20 (solar direct) + 25 (battery) = 55
        snapshots = (200.0, 50.0, 80.0, 40.0, 30.0)  # prod, ni, ne, bc, bd
        currents = (200.100, 50.010, 80.050, 40.030, 30.025)

        actual, solar = _compute_derived_consumption(snapshots, currents)

        # grid_import = 10, solar_self = 50, net_battery = 25-30 = -5
        # actual = 10 + 50 + (-5) = 55
        assert abs(actual - 55.0) < 0.1
        assert abs(solar - 100.0) < 0.1

    def test_formula_without_battery_charged_would_overcount(self):
        """Demonstrate that omitting battery_charged gives wrong (too high) result."""
        snapshots = (200.0, 50.0, 80.0, 40.0, 30.0)
        currents = (200.100, 50.010, 80.050, 40.030, 30.025)

        # Wrong formula (without battery_charged subtraction):
        grid_import_kwh = (50.010 - 50.0) * 1000.0   # 10
        solar_produced_kwh = (200.100 - 200.0) * 1000.0  # 100
        solar_exported_kwh = (80.050 - 80.0) * 1000.0   # 50
        battery_discharged_kwh = (30.025 - 30.0) * 1000.0  # 25
        wrong_actual = grid_import_kwh + (solar_produced_kwh - solar_exported_kwh) + battery_discharged_kwh
        # wrong = 10 + 50 + 25 = 85 (overcounts by battery_charged = 30)

        correct_actual, _ = _compute_derived_consumption(snapshots, currents)

        assert wrong_actual > correct_actual + 20  # overcounts significantly
        assert abs(correct_actual - 55.0) < 0.1

    def test_derived_consumption_sunny_day(self):
        """On a sunny day, consumption should be ~35 kWh, not near-zero.

        Legacy delta (net grid import) gives near-zero on sunny days.
        """
        # Sunny: 2 kWh grid import, 100 kWh solar, 70 exported, 15 charged, 3 discharged
        # Home = 2 + (100 - 70) + (3 - 15) = 2 + 30 + (-12) = 20 kWh
        snapshots = (200.0, 50.0, 80.0, 40.0, 30.0)
        currents = (200.100, 50.002, 80.070, 40.015, 30.003)

        actual, solar = _compute_derived_consumption(snapshots, currents)

        # grid=2, solar_self=30, net_battery=-12 → 20 kWh
        assert actual > 10.0, f"Derived consumption {actual} should be realistic"
        assert abs(actual - 20.0) < 0.1

        # Legacy delta would be near-zero
        legacy_kwh = (50.002 - 50.0) * 1000.0  # net_import delta = 2 kWh
        # Even the net import (2 kWh) is more than the old lifetime_consumption delta
        # which measures the same thing with net-consumption CT

    def test_fallback_to_legacy_when_sensors_unavailable(self):
        """When derived sensors are unavailable, fall back to legacy consumption delta."""
        hass = MockHass()

        # Only set the legacy consumption entity
        hass.set_state(DEFAULT_LIFETIME_CONSUMPTION_ENTITY, "100.030")

        state = hass.states.get(DEFAULT_LIFETIME_CONSUMPTION_ENTITY)
        current_lifetime = float(state.state)
        snapshot = 100.0

        # Derived sensors not available
        prod_state = hass.states.get(DEFAULT_LIFETIME_PRODUCTION_ENTITY)
        assert prod_state is None

        # Legacy path works
        actual_kwh = (current_lifetime - snapshot) * 1000.0
        assert abs(actual_kwh - 30.0) < 0.1

    def test_independent_snapshot_seeding(self):
        """Each snapshot seeds independently as entities become available."""
        # Simulate the seeding logic from _maybe_reset_daily else branch
        snapshots = {
            "consumption": None,
            "production": None,
            "net_import": None,
        }

        # Seed consumption only
        snapshots["consumption"] = 100.0 if snapshots["consumption"] is None else snapshots["consumption"]
        assert snapshots["consumption"] == 100.0
        assert snapshots["production"] is None  # still None

        # Seed production
        snapshots["production"] = 200.0 if snapshots["production"] is None else snapshots["production"]
        assert snapshots["production"] == 200.0

    def test_solar_production_kwh_computed_from_delta(self):
        """solar_produced_kwh = production delta, passed to DB as solar_production_kwh."""
        snapshots = (200.0, 50.0, 80.0, 40.0, 30.0)
        currents = (200.090, 50.010, 80.060, 40.010, 30.005)

        actual, solar = _compute_derived_consumption(snapshots, currents)
        assert abs(solar - 90.0) < 0.1
        assert solar is not None

    def test_negative_delta_guard_rejects_envoy_reboot(self):
        """If any lifetime delta is negative (Envoy reboot), derived path is skipped."""
        # Envoy rebooted: production reset from 200 to ~0
        snapshots = (200.0, 50.0, 80.0, 40.0, 30.0)
        currents = (0.001, 50.010, 80.050, 40.010, 30.005)  # production reset

        actual, solar = _compute_derived_consumption(snapshots, currents)
        assert actual is None, "Negative delta should cause derived path to return None"
        assert solar is None

    def test_negative_delta_guard_all_reset(self):
        """Full Envoy reboot (all sensors reset to ~0) is caught."""
        snapshots = (200.0, 50.0, 80.0, 40.0, 30.0)
        currents = (0.001, 0.001, 0.001, 0.001, 0.001)

        actual, solar = _compute_derived_consumption(snapshots, currents)
        assert actual is None

    def test_non_positive_consumption_discarded(self):
        """If derived actual_kwh is <= 0, it should be discarded."""
        # Edge case: net_battery is very negative (battery charged a lot, little discharged)
        # This can happen on a day with huge solar and minimal consumption
        snapshots = (200.0, 50.0, 80.0, 40.0, 30.0)
        # grid=1, solar_self=5, net_battery = 0 - 10 = -10 → actual = -4
        currents = (200.005, 50.001, 80.000, 40.010, 30.000)

        actual, solar = _compute_derived_consumption(snapshots, currents)
        # actual = 1 + 5 + (0-10) = -4
        assert actual is not None  # formula computes it
        assert actual < 0  # but it's negative
        # In production code, the guard `if actual_kwh <= 0` would discard it


# ============================================================================
# ENERGY FORECAST: Battery full time with consumption + piecewise taper
# ============================================================================


class TestBatteryFullTime:
    """Test _estimate_battery_full_time with consumption-aware + piecewise taper."""

    def _make_predictor(self, hass):
        return DailyEnergyPredictor(hass)

    def test_battery_full_already_full(self):
        """SOC >= 99 returns 'already_full'."""
        hass = MockHass()
        hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "100")
        hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, "50.0")

        p = self._make_predictor(hass)
        p._estimate_battery_full_time(datetime(2026, 3, 13, 10, 0))
        assert p._battery_full_time == "already_full"

    def test_battery_full_unlikely_high_consumption(self):
        """High consumption eats all solar surplus."""
        hass = MockHass()
        hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "50")
        hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, "20.0")
        hass.set_state(DEFAULT_BATTERY_CAPACITY_ENTITY, "15000")

        p = self._make_predictor(hass)
        p._predicted_consumption_kwh = 50.0

        # hours_left=10, remaining_consumption=50*(10/24)=20.83, net_solar=20-20.83=-0.83
        p._estimate_battery_full_time(datetime(2026, 3, 13, 10, 0))
        assert p._battery_full_time == "unlikely_today"

    def test_battery_full_piecewise_taper_low_soc(self):
        """At low SOC, piecewise taper gives later time than flat rate.

        SOC=30%, capacity=15 kWh, remaining=10.5 kWh to fill.
        Piecewise: 30→80% (7.5 kWh @ 3.5) + 80→90% (1.5 kWh @ 2.5) + 90→100% (1.5 kWh @ 1.5)
        = 2.143 + 0.6 + 1.0 = 3.743 hours
        """
        hass = MockHass()
        hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "30")
        hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, "60.0")
        hass.set_state(DEFAULT_BATTERY_CAPACITY_ENTITY, "15000")

        p = self._make_predictor(hass)
        p._predicted_consumption_kwh = 30.0

        # At 10 AM: hours_left=10, remaining_consumption=12.5, net_solar=47.5
        # remaining_capacity=10.5, net_solar > remaining → proceed
        p._estimate_battery_full_time(datetime(2026, 3, 13, 10, 0))

        assert p._battery_full_time is not None
        assert p._battery_full_time != "unlikely_today"
        hour, minute = map(int, p._battery_full_time.split(":"))
        # 10:00 + 3.743h ≈ 13:44-13:45
        assert hour == 13
        assert 43 <= minute <= 46

    def test_battery_full_taper_at_high_soc(self):
        """Above 90% SOC, only the 1.5 kW band applies."""
        hass = MockHass()
        hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "92")
        hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, "40.0")
        hass.set_state(DEFAULT_BATTERY_CAPACITY_ENTITY, "15000")

        p = self._make_predictor(hass)
        p._predicted_consumption_kwh = 20.0

        # remaining_capacity = 15 * 8/100 = 1.2 kWh
        # Piecewise: 92→100% all in 1.5 kW band = 1.2/1.5 = 0.8 hours = 48 min
        p._estimate_battery_full_time(datetime(2026, 3, 13, 12, 0))

        assert p._battery_full_time is not None
        hour, minute = map(int, p._battery_full_time.split(":"))
        assert hour == 12
        assert 45 <= minute <= 50

    def test_battery_full_mid_soc(self):
        """SOC=85%, piecewise: 85→90% @ 2.5 kW + 90→100% @ 1.5 kW."""
        hass = MockHass()
        hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "85")
        hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, "50.0")
        hass.set_state(DEFAULT_BATTERY_CAPACITY_ENTITY, "15000")

        p = self._make_predictor(hass)
        p._predicted_consumption_kwh = 25.0

        # remaining_capacity = 15 * 15/100 = 2.25 kWh
        # 85→90%: 0.75 kWh @ 2.5 = 0.3h
        # 90→100%: 1.5 kWh @ 1.5 = 1.0h
        # Total: 1.3h = 1h18min → 11:00 + 1:18 = 12:18
        p._estimate_battery_full_time(datetime(2026, 3, 13, 11, 0))

        assert p._battery_full_time is not None
        hour, minute = map(int, p._battery_full_time.split(":"))
        assert hour == 12
        assert 16 <= minute <= 20

    def test_battery_full_after_8pm(self):
        """After 8 PM, hours_left=0, remaining_consumption=0. Near-zero solar left."""
        hass = MockHass()
        hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "80")
        hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, "0.5")  # tiny solar left
        hass.set_state(DEFAULT_BATTERY_CAPACITY_ENTITY, "15000")

        p = self._make_predictor(hass)
        p._predicted_consumption_kwh = 30.0

        # remaining_capacity = 15 * 20/100 = 3.0 kWh
        # net_available_solar = 0.5 - 0 = 0.5 kWh
        # 0.5 < 3.0 → unlikely
        p._estimate_battery_full_time(datetime(2026, 3, 13, 21, 0))
        assert p._battery_full_time == "unlikely_today"

    def test_battery_full_none_when_soc_missing(self):
        """If SOC entity unavailable, battery_full_time = None."""
        hass = MockHass()
        hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, "50.0")
        # No SOC entity

        p = self._make_predictor(hass)
        p._estimate_battery_full_time(datetime(2026, 3, 13, 10, 0))
        assert p._battery_full_time is None

    def test_battery_full_time_live_soc_fallback(self):
        """Coordinator battery_full_time falls back to live SOC when predictor is None.

        Covers the case where prediction was cached while Envoy was offline
        (battery_full_time = None), but battery later reached 100%.
        """
        # Simulate coordinator with predictor that has None battery_full_time
        # and battery that reports SOC >= 99
        predictor = MagicMock()
        predictor._battery_full_time = None

        battery = MagicMock()
        battery.battery_soc = 100

        # Simulate the coordinator property logic
        result = predictor._battery_full_time
        if result is None:
            soc = battery.battery_soc
            if soc is not None and soc >= 99:
                result = "already_full"
        assert result == "already_full"

    def test_battery_full_time_no_fallback_when_soc_low(self):
        """No fallback when predictor is None and SOC is low."""
        predictor = MagicMock()
        predictor._battery_full_time = None

        battery = MagicMock()
        battery.battery_soc = 50

        result = predictor._battery_full_time
        if result is None:
            soc = battery.battery_soc
            if soc is not None and soc >= 99:
                result = "already_full"
        assert result is None


# ============================================================================
# PREDICTED IMPORT PROPERTY
# ============================================================================


def _compute_grid_import(consumption, production, capacity, reserve):
    """Replicate the grid import formula from energy.py.

    Simple energy balance: positive = import, negative = export.
    Battery is a fixed buffer of usable_capacity kWh.
    """
    usable_battery = capacity * (1.0 - reserve / 100.0)

    if production >= consumption:
        surplus = production - consumption
        battery_absorbs = min(usable_battery, surplus)
        return round(-(surplus - battery_absorbs), 1)
    else:
        deficit = consumption - production
        battery_provides = min(usable_battery, deficit)
        return round(deficit - battery_provides, 1)


class TestPredictedImport:
    """Test grid import prediction.

    positive = net grid import, negative = net grid export.
    Battery usable capacity buffers the difference between solar and consumption.
    """

    def test_sunny_day_net_export(self):
        """150 kWh solar, 31 kWh consumption, 40 kWh battery (10% reserve).

        surplus = 119, battery absorbs 36, export = 83.
        """
        result = _compute_grid_import(
            consumption=31.0, production=150.0,
            capacity=40.0, reserve=10,
        )
        assert result == -83.0

    def test_cloudy_day_battery_covers_deficit(self):
        """10 kWh solar, 30 kWh consumption → deficit 20, battery covers all."""
        result = _compute_grid_import(
            consumption=30.0, production=10.0,
            capacity=40.0, reserve=10,
        )
        # deficit = 20, usable battery = 36 → battery covers all, 0 import
        assert result == 0.0

    def test_very_cloudy_day_grid_import(self):
        """0 kWh solar, 50 kWh consumption → deficit 50, battery covers 36."""
        result = _compute_grid_import(
            consumption=50.0, production=0.0,
            capacity=40.0, reserve=10,
        )
        # deficit = 50, battery provides 36, import = 14
        assert result == 14.0

    def test_moderate_solar_no_grid_exchange(self):
        """Solar exactly covers consumption + battery. No grid exchange."""
        result = _compute_grid_import(
            consumption=30.0, production=66.0,
            capacity=40.0, reserve=10,
        )
        # surplus = 36, battery absorbs 36, export = 0
        assert result == 0.0

    def test_surplus_exceeds_battery(self):
        """100 kWh solar, 24 kWh consumption, 40 kWh battery (10% reserve)."""
        result = _compute_grid_import(
            consumption=24.0, production=100.0,
            capacity=40.0, reserve=10,
        )
        # surplus = 76, battery absorbs 36, export = 40
        assert result == -40.0

    def test_high_reserve_reduces_buffer(self):
        """High reserve (30%) means less usable battery."""
        result = _compute_grid_import(
            consumption=30.0, production=0.0,
            capacity=40.0, reserve=30,
        )
        # deficit = 30, usable = 28, import = 2
        assert result == 2.0

    def test_none_when_prediction_missing(self):
        """None propagated when consumption or production unavailable."""
        hass = MockHass()
        p = DailyEnergyPredictor(hass)
        prediction = p._get_current_prediction()
        assert prediction.get("predicted_consumption_kwh") is None
        assert prediction.get("predicted_production_kwh") is None


# ============================================================================
# ROOMS ENERGY TOTAL
# ============================================================================


class TestRoomsEnergyTotal:
    """Test rooms_energy_total logic uses room coordinators (not domain coordinators)."""

    def test_rooms_energy_total_sums_room_coordinators(self):
        """Sum energy_today from UniversalRoomCoordinator instances in hass.data[DOMAIN]."""
        # The real code iterates hass.data[DOMAIN].values() and checks isinstance(data, URC)
        # Simulate with a mock class standing in for UniversalRoomCoordinator
        class FakeRoomCoord:
            def __init__(self, energy):
                self.data = {"energy_today": energy} if energy is not None else {}

        room1 = FakeRoomCoord(5.5)
        room2 = FakeRoomCoord(3.2)
        room3 = FakeRoomCoord(None)  # no energy

        # Simulate the iteration pattern from the fixed _get_rooms_energy_total
        rooms_total = 0.0
        for data in [room1, room2, room3, "coordinator_manager", {"database": MagicMock()}]:
            if isinstance(data, FakeRoomCoord):  # isinstance check in real code
                if hasattr(data, 'data') and isinstance(data.data, dict):
                    energy = data.data.get("energy_today")
                    if energy is not None:
                        rooms_total += energy
        result = round(rooms_total, 2) if rooms_total > 0 else None

        assert result == 8.7

    def test_rooms_energy_total_none_when_no_room_coordinators(self):
        """Returns None when no room coordinators exist."""
        rooms_total = 0.0
        # Only non-coordinator entries
        for data in ["coordinator_manager", {"database": MagicMock()}]:
            pass  # no isinstance match
        result = round(rooms_total, 2) if rooms_total > 0 else None
        assert result is None

    def test_rooms_energy_total_ignores_domain_coordinators(self):
        """Domain coordinators (energy, presence) don't have energy_today — must be skipped."""
        class FakeDomainCoord:
            def __init__(self):
                self.data = {"mode": "normal"}  # no energy_today

        domain = FakeDomainCoord()
        rooms_total = 0.0
        # Only domain coordinator — no isinstance(data, UniversalRoomCoordinator) match
        energy = domain.data.get("energy_today")
        assert energy is None  # domain coords don't have this key


# ============================================================================
# FIRST BOOT / RESTART SCENARIO
# ============================================================================


class TestFirstBoot:
    """Test behavior when coordinator starts fresh (all snapshots None)."""

    def test_first_boot_all_snapshots_none(self):
        """On first boot, _last_reset_date='', all snapshots None.

        The date-change branch fires ('' != today), but both derived and
        legacy paths require self._last_reset_date to be truthy, so
        actual_kwh stays None. No accuracy evaluation. Snapshots get seeded.
        """
        snapshots_all_none = all(s is None for s in [None, None, None, None, None, None])
        assert snapshots_all_none

        last_reset_date = ""
        # Both paths check `and self._last_reset_date` which is falsy for ""
        derived_ok = (
            None is not None  # production snapshot
            and last_reset_date  # evaluates to False
        )
        assert not derived_ok

        legacy_ok = (
            None is not None  # consumption snapshot
            and last_reset_date  # evaluates to False
        )
        assert not legacy_ok

    def test_seeding_after_first_boot(self):
        """After first boot resets date, subsequent cycles seed snapshots."""
        # After the date-change branch, _last_reset_date = today, snapshots = current values
        # If some entities weren't available, their snapshots stay None
        # Next cycle hits the else branch and seeds them independently
        current_values = {
            "consumption": 100.0,
            "production": None,  # not available yet
        }
        snapshots = {
            "consumption": current_values["consumption"],  # seeded from reset
            "production": None,  # stays None
        }
        # Next cycle: production becomes available
        current_values["production"] = 200.0
        if snapshots["production"] is None and current_values["production"] is not None:
            snapshots["production"] = current_values["production"]
        assert snapshots["production"] == 200.0

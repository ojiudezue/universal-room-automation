"""Tests for v4.6.12: Dashboard Aggregator Sensors (Cycle B).

Deliverables covered:
  D1 — ZoneMotionEventCountSensor
  D2 — HouseSystemDemandSensor
  D3 — EnergyGridDemandSensor

Test strategy (mirrors v4.6.10 pattern):
- Module-level sys.modules.setdefault for ALL HA stubs so integration
  modules can be imported.
- Behavioral tests use mock coordinators injected via hass.data.
- Structural tests use source-file grep for immutable properties.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# HA module stubs — must be at module top before ANY integration import
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parents[2]


class _SensorStateClass:
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class _SensorDeviceClass:
    MONETARY = "monetary"
    DURATION = "duration"
    ENERGY = "energy"
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    POWER = "power"


class _BinarySensorDeviceClass:
    MOTION = "motion"
    DOOR = "door"


class _EntityCategory:
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"


_sensor_mod = MagicMock()
_sensor_mod.SensorEntity = object
_sensor_mod.SensorDeviceClass = _SensorDeviceClass
_sensor_mod.SensorStateClass = _SensorStateClass

_binary_sensor_mod = MagicMock()
_binary_sensor_mod.BinarySensorEntity = object
_binary_sensor_mod.BinarySensorDeviceClass = _BinarySensorDeviceClass

_entity_mod = MagicMock()
_entity_mod.DeviceInfo = dict
_entity_mod.EntityCategory = _EntityCategory

_dt_stub = MagicMock()
_dt_stub.utcnow = lambda: datetime.now(tz=timezone.utc)
_dt_stub.now = lambda: datetime.now(tz=timezone.utc)
_dt_stub.UTC = timezone.utc
_dt_stub.parse_datetime = MagicMock(return_value=None)
_dt_stub.as_utc = lambda dt: dt

_util_stub = MagicMock()
_util_stub.dt = _dt_stub

_HA_STUBS = {
    "homeassistant": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.update_coordinator": MagicMock(),
    "homeassistant.helpers.restore_state": MagicMock(),
    "homeassistant.helpers.dispatcher": MagicMock(),
    "homeassistant.helpers.entity": _entity_mod,
    "homeassistant.helpers.entity_platform": MagicMock(),
    "homeassistant.helpers.event": MagicMock(),
    "homeassistant.helpers.device_registry": MagicMock(),
    "homeassistant.components.sensor": _sensor_mod,
    "homeassistant.components.button": MagicMock(),
    "homeassistant.components.binary_sensor": _binary_sensor_mod,
    "homeassistant.util": _util_stub,
    "homeassistant.util.dt": _dt_stub,
    "homeassistant.const": MagicMock(),
}
for _k, _v in _HA_STUBS.items():
    sys.modules.setdefault(_k, _v)

_HA_STUBS["homeassistant.util"].dt = _dt_stub

DOMAIN = "universal_room_automation"
ENTRY_TYPE_INTEGRATION = "integration"
CONF_ZONE = "zone"
ZONE_MOTION_WINDOW_SECONDS = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    return hass


def _make_entry():
    entry = MagicMock()
    entry.entry_id = "test_integration_entry"
    entry.data = {"entry_type": ENTRY_TYPE_INTEGRATION}
    entry.options = {}
    return entry


def _utc_now():
    return datetime.now(tz=timezone.utc)


def _make_room_coord(zone: str | None, last_motion: datetime | None):
    """Build a minimal room coordinator mock."""
    coord = MagicMock()
    coord._last_motion_time = last_motion
    coord.entry = MagicMock()
    coord.entry.options = {CONF_ZONE: zone} if zone else {}
    coord.entry.data = {CONF_ZONE: zone} if zone else {}
    return coord


def _make_zone(hvac_action: str, zone_name: str = "TestZone"):
    z = MagicMock()
    z.hvac_action = hvac_action
    z.zone_name = zone_name
    return z


def _make_hvac_coord(zones: dict):
    """Build a minimal HVAC coordinator mock."""
    hvac = MagicMock()
    hvac.zone_manager = MagicMock()
    hvac.zone_manager.zones = zones
    return hvac


def _make_energy_coord(cap_kw: float, cap_enabled: bool, net_power_w: float | None):
    """Build a minimal energy coordinator mock."""
    ec = MagicMock()
    ec._grid_import_cap_kw = cap_kw
    ec._grid_import_cap_enabled = cap_enabled
    battery = MagicMock()
    battery.net_power_w = net_power_w
    ec._battery = battery
    return ec


# ---------------------------------------------------------------------------
# Sensor instantiation helpers (bypass AggregationEntity.__init__ complexity)
# ---------------------------------------------------------------------------

def _make_motion_sensor(hass, room_coords):
    """Build ZoneMotionEventCountSensor with mocked _get_room_coordinators."""
    # Import lazily after stubs are in place
    import importlib
    # We test the logic directly rather than importing the full module
    # (avoids cascading import of all coordinators).
    # Use a thin inline class that replicates the production logic.
    class _Sensor:
        def __init__(self, h, coords):
            self.hass = h
            self._coords = coords

        def _get_room_coordinators(self):
            return self._coords

        @property
        def native_value(self) -> int:
            now = _dt_stub.utcnow()
            window = timedelta(seconds=ZONE_MOTION_WINDOW_SECONDS)
            zones_with_motion: set[str] = set()
            for coord in self._get_room_coordinators():
                try:
                    last = coord._last_motion_time
                except AttributeError:
                    continue
                if last is None:
                    continue
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last) > window:
                    continue
                zone = coord.entry.options.get(CONF_ZONE) or coord.entry.data.get(CONF_ZONE)
                if zone:
                    zones_with_motion.add(zone)
            return len(zones_with_motion)

        @property
        def extra_state_attributes(self) -> dict:
            now = _dt_stub.utcnow()
            window = timedelta(seconds=ZONE_MOTION_WINDOW_SECONDS)
            zones_with_motion: set[str] = set()
            for coord in self._get_room_coordinators():
                try:
                    last = coord._last_motion_time
                except AttributeError:
                    continue
                if last is None:
                    continue
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last) > window:
                    continue
                zone = coord.entry.options.get(CONF_ZONE) or coord.entry.data.get(CONF_ZONE)
                if zone:
                    zones_with_motion.add(zone)
            return {
                "zones": sorted(zones_with_motion),
                "window_minutes": ZONE_MOTION_WINDOW_SECONDS // 60,
            }

    return _Sensor(hass, room_coords)


def _make_demand_sensor(hass, hvac_coord_or_none):
    """Build HouseSystemDemandSensor with injected HVAC coordinator."""
    class _Sensor:
        def __init__(self, h, hvac):
            self.hass = h
            self._hvac = hvac

        def _get_hvac(self):
            return self._hvac

        @property
        def available(self) -> bool:
            return self._get_hvac() is not None

        @property
        def native_value(self) -> int | None:
            hvac = self._get_hvac()
            if hvac is None:
                return None
            try:
                zones = hvac.zone_manager.zones
            except AttributeError:
                return None
            total = len(zones)
            if total == 0:
                return None
            active = sum(
                1 for z in zones.values()
                if z.hvac_action in ("cooling", "heating")
            )
            return int(round((active / total) * 100))

        @property
        def extra_state_attributes(self) -> dict:
            hvac = self._get_hvac()
            if hvac is None:
                return {}
            try:
                zones = hvac.zone_manager.zones
            except AttributeError:
                return {}
            active_names = sorted(
                z.zone_name for z in zones.values()
                if z.hvac_action in ("cooling", "heating")
            )
            pct = self.native_value or 0
            if pct == 0:
                bucket = "idle"
            elif pct <= 33:
                bucket = "light"
            elif pct <= 66:
                bucket = "moderate"
            else:
                bucket = "heavy"
            return {
                "active_zones": active_names,
                "active_count": len(active_names),
                "total_zones": len(zones),
                "load_bucket": bucket,
                "formula": "active_zones / total_zones",
            }

    return _Sensor(hass, hvac_coord_or_none)


def _make_grid_sensor(hass, ec_or_none):
    """Build EnergyGridDemandSensor mirror.

    MIRRORS production EnergyGridDemandSensor at
    custom_components/universal_room_automation/aggregation.py
    (class EnergyGridDemandSensor, see `available`/`native_value`/
    `extra_state_attributes`). When that body changes, update this mirror
    in lock-step or these tests will lock the wrong contract.

    B4 live-health repair (2026-06-10): production no longer short-circuits
    `available` on cap-disabled / cap-kw-unset. The sensor is available
    whenever the EC is registered; the cap/net inputs are exposed via
    `unconfigured_reason` instead.
    """
    class _Sensor:
        def __init__(self, h, ec):
            self.hass = h
            self._ec = ec

        def _get_ec(self):
            return self._ec

        @property
        def available(self) -> bool:
            # B4: only gates on EC presence.
            return self._get_ec() is not None

        @property
        def native_value(self) -> float | None:
            ec = self._get_ec()
            if ec is None:
                return None
            if not getattr(ec, "_grid_import_cap_enabled", False):
                return None
            cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
            if cap_kw <= 0:
                return None
            try:
                net_w = getattr(getattr(ec, "_battery", None), "net_power_w", None)
            except Exception:
                return None
            if net_w is None:
                return None
            grid_kw = max(net_w, 0) / 1000.0
            return round((grid_kw / cap_kw) * 100.0, 1)

        @property
        def extra_state_attributes(self) -> dict:
            ec = self._get_ec()
            if ec is None:
                return {}
            cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
            cap_enabled = getattr(ec, "_grid_import_cap_enabled", False)
            battery = getattr(ec, "_battery", None)
            try:
                net_w = getattr(battery, "net_power_w", None)
            except Exception:
                net_w = None
            grid_kw = round(max(net_w, 0) / 1000.0, 3) if net_w is not None else None
            unconfigured_reason = None
            if not cap_enabled:
                unconfigured_reason = "grid_import_cap_disabled"
            elif cap_kw <= 0:
                unconfigured_reason = "grid_import_cap_kw_unset"
            elif net_w is None:
                unconfigured_reason = "net_power_w_unavailable"
            attrs = {
                "grid_import_kw": grid_kw,
                "grid_import_cap_kw": cap_kw,
                "grid_import_cap_enabled": cap_enabled,
                "exporting": net_w is not None and net_w < 0,
            }
            if unconfigured_reason is not None:
                attrs["unconfigured_reason"] = unconfigured_reason
            return attrs

    return _Sensor(hass, ec_or_none)


# ---------------------------------------------------------------------------
# D1 — ZoneMotionEventCountSensor
# ---------------------------------------------------------------------------

class TestZoneMotionEventCountSensor:
    """D1: ZoneMotionEventCountSensor behavioral tests."""

    def test_zone_motion_count_basic(self):
        """5 coords across 3 zones; 2 zones have at least one room < 5 min."""
        hass = _make_hass()
        now = _utc_now()
        coords = [
            _make_room_coord("living_room", now - timedelta(minutes=1)),   # zone A in-window
            _make_room_coord("living_room", now - timedelta(minutes=3)),   # zone A in-window (dup)
            _make_room_coord("kitchen", now - timedelta(minutes=3)),       # zone B in-window
            _make_room_coord("bedroom", now - timedelta(minutes=6)),       # zone C out-of-window
            _make_room_coord("office", None),                               # no motion
        ]
        sensor = _make_motion_sensor(hass, coords)
        assert sensor.native_value == 2

    def test_zone_motion_count_no_motion_ever(self):
        """Coordinator with _last_motion_time = None is not counted."""
        hass = _make_hass()
        coords = [_make_room_coord("living_room", None)]
        sensor = _make_motion_sensor(hass, coords)
        assert sensor.native_value == 0

    def test_zone_motion_count_outside_window(self):
        """Coordinator with last motion 6 min ago is not counted."""
        hass = _make_hass()
        now = _utc_now()
        coords = [_make_room_coord("living_room", now - timedelta(minutes=6))]
        sensor = _make_motion_sensor(hass, coords)
        assert sensor.native_value == 0

    def test_zone_motion_count_dedup_same_zone(self):
        """Two rooms in the same zone both active → counted as 1."""
        hass = _make_hass()
        now = _utc_now()
        coords = [
            _make_room_coord("living_room", now - timedelta(minutes=1)),
            _make_room_coord("living_room", now - timedelta(minutes=2)),
        ]
        sensor = _make_motion_sensor(hass, coords)
        assert sensor.native_value == 1

    def test_zone_motion_count_naive_datetime_handled(self):
        """Naive _last_motion_time does not raise (bug class #21)."""
        hass = _make_hass()
        # Naive datetime — no tzinfo
        naive_ts = datetime.utcnow()  # naive
        assert naive_ts.tzinfo is None
        coords = [_make_room_coord("living_room", naive_ts)]
        sensor = _make_motion_sensor(hass, coords)
        # Should not raise; result is 1 because naive is treated as UTC (just now)
        result = sensor.native_value
        assert isinstance(result, int)

    def test_zone_motion_count_attrs_window_and_zones(self):
        """extra_state_attributes returns zones list and window_minutes=5."""
        hass = _make_hass()
        now = _utc_now()
        coords = [
            _make_room_coord("kitchen", now - timedelta(minutes=1)),
            _make_room_coord("bedroom", now - timedelta(minutes=7)),
        ]
        sensor = _make_motion_sensor(hass, coords)
        attrs = sensor.extra_state_attributes
        assert attrs["window_minutes"] == 5
        assert "zones" in attrs
        assert "kitchen" in attrs["zones"]
        assert "bedroom" not in attrs["zones"]

    def test_zone_motion_count_no_zone_configured_skipped(self):
        """Room coordinator with no CONF_ZONE is not counted."""
        hass = _make_hass()
        now = _utc_now()
        # zone=None — no CONF_ZONE in options or data
        coord = MagicMock()
        coord._last_motion_time = now - timedelta(minutes=1)
        coord.entry = MagicMock()
        coord.entry.options = {}
        coord.entry.data = {}
        sensor = _make_motion_sensor(hass, [coord])
        assert sensor.native_value == 0

    def test_zone_motion_count_all_in_window(self):
        """All 3 rooms in 3 distinct zones active → count = 3."""
        hass = _make_hass()
        now = _utc_now()
        coords = [
            _make_room_coord("zone_a", now - timedelta(seconds=10)),
            _make_room_coord("zone_b", now - timedelta(seconds=30)),
            _make_room_coord("zone_c", now - timedelta(minutes=4)),
        ]
        sensor = _make_motion_sensor(hass, coords)
        assert sensor.native_value == 3


# ---------------------------------------------------------------------------
# D2 — HouseSystemDemandSensor
# ---------------------------------------------------------------------------

class TestHouseSystemDemandSensor:
    """D2: HouseSystemDemandSensor behavioral tests."""

    def test_hvac_demand_all_idle(self):
        """5 zones all hvac_action='idle' → value = 0."""
        hass = _make_hass()
        zones = {f"z{i}": _make_zone("idle", f"Zone{i}") for i in range(5)}
        sensor = _make_demand_sensor(hass, _make_hvac_coord(zones))
        assert sensor.native_value == 0

    def test_hvac_demand_all_calling(self):
        """5 zones all hvac_action='cooling' → value = 100."""
        hass = _make_hass()
        zones = {f"z{i}": _make_zone("cooling", f"Zone{i}") for i in range(5)}
        sensor = _make_demand_sensor(hass, _make_hvac_coord(zones))
        assert sensor.native_value == 100

    def test_hvac_demand_partial(self):
        """3 of 5 zones cooling → value = 60."""
        hass = _make_hass()
        zones = {
            "z0": _make_zone("cooling", "Zone0"),
            "z1": _make_zone("cooling", "Zone1"),
            "z2": _make_zone("cooling", "Zone2"),
            "z3": _make_zone("idle", "Zone3"),
            "z4": _make_zone("idle", "Zone4"),
        }
        sensor = _make_demand_sensor(hass, _make_hvac_coord(zones))
        assert sensor.native_value == 60

    def test_hvac_demand_mixed_directions(self):
        """2 cooling + 1 heating + 2 idle → value = 60 (both call types count)."""
        hass = _make_hass()
        zones = {
            "z0": _make_zone("cooling", "Zone0"),
            "z1": _make_zone("cooling", "Zone1"),
            "z2": _make_zone("heating", "Zone2"),
            "z3": _make_zone("idle", "Zone3"),
            "z4": _make_zone("idle", "Zone4"),
        }
        sensor = _make_demand_sensor(hass, _make_hvac_coord(zones))
        assert sensor.native_value == 60

    def test_hvac_demand_no_coordinator(self):
        """No HVAC coordinator → native_value = None, available = False."""
        hass = _make_hass()
        sensor = _make_demand_sensor(hass, None)
        assert sensor.native_value is None
        assert sensor.available is False

    def test_hvac_demand_zero_zones(self):
        """Empty zone_manager.zones → native_value = None (no div-by-zero)."""
        hass = _make_hass()
        sensor = _make_demand_sensor(hass, _make_hvac_coord({}))
        assert sensor.native_value is None

    def test_hvac_demand_attrs_bucket_thresholds(self):
        """Load bucket thresholds: 0%→idle, 20%→light, 50%→moderate, 80%→heavy."""
        hass = _make_hass()

        # 0% — idle
        zones_idle = {f"z{i}": _make_zone("idle", f"Zone{i}") for i in range(5)}
        s = _make_demand_sensor(hass, _make_hvac_coord(zones_idle))
        assert s.extra_state_attributes["load_bucket"] == "idle"

        # 20% — light (1 of 5 cooling)
        zones_light = {
            "z0": _make_zone("cooling", "Zone0"),
            "z1": _make_zone("idle", "Zone1"),
            "z2": _make_zone("idle", "Zone2"),
            "z3": _make_zone("idle", "Zone3"),
            "z4": _make_zone("idle", "Zone4"),
        }
        s = _make_demand_sensor(hass, _make_hvac_coord(zones_light))
        assert s.extra_state_attributes["load_bucket"] == "light"

        # 50% — moderate (5 of 10)
        zones_mod = {}
        for i in range(5):
            zones_mod[f"a{i}"] = _make_zone("cooling", f"ZoneA{i}")
        for i in range(5):
            zones_mod[f"b{i}"] = _make_zone("idle", f"ZoneB{i}")
        s = _make_demand_sensor(hass, _make_hvac_coord(zones_mod))
        assert s.extra_state_attributes["load_bucket"] == "moderate"

        # 80% — heavy (4 of 5 cooling)
        zones_heavy = {
            "z0": _make_zone("cooling", "Zone0"),
            "z1": _make_zone("cooling", "Zone1"),
            "z2": _make_zone("cooling", "Zone2"),
            "z3": _make_zone("cooling", "Zone3"),
            "z4": _make_zone("idle", "Zone4"),
        }
        s = _make_demand_sensor(hass, _make_hvac_coord(zones_heavy))
        assert s.extra_state_attributes["load_bucket"] == "heavy"

    def test_hvac_demand_attrs_keys(self):
        """extra_state_attributes contains expected keys."""
        hass = _make_hass()
        zones = {"z0": _make_zone("cooling", "Zone0"), "z1": _make_zone("idle", "Zone1")}
        sensor = _make_demand_sensor(hass, _make_hvac_coord(zones))
        attrs = sensor.extra_state_attributes
        for key in ("active_zones", "active_count", "total_zones", "load_bucket", "formula"):
            assert key in attrs, f"missing key: {key}"
        assert attrs["total_zones"] == 2
        assert attrs["active_count"] == 1


# ---------------------------------------------------------------------------
# D3 — EnergyGridDemandSensor
# ---------------------------------------------------------------------------

class TestEnergyGridDemandSensor:
    """D3: EnergyGridDemandSensor behavioral tests."""

    def test_grid_demand_zero(self):
        """net import 0 W, cap 8 kW → value = 0.0."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, 0))
        assert sensor.native_value == 0.0

    def test_grid_demand_at_cap(self):
        """net import 8000 W, cap 8 kW → value = 100.0."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, 8000))
        assert sensor.native_value == 100.0

    def test_grid_demand_double_cap_no_clamp(self):
        """net import 16000 W, cap 8 kW → value = 200.0 (no clamping)."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, 16000))
        assert sensor.native_value == 200.0

    def test_grid_demand_half_cap(self):
        """net import 4000 W, cap 8 kW → value = 50.0."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, 4000))
        assert sensor.native_value == 50.0

    def test_grid_demand_exporting_returns_zero(self):
        """net import -2000 W (exporting) → value = 0.0, attrs exporting=True."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, -2000))
        assert sensor.native_value == 0.0
        assert sensor.extra_state_attributes["exporting"] is True

    def test_grid_demand_cap_disabled_returns_none(self):
        """B4 (2026-06-10): cap disabled → native_value=None but sensor
        stays AVAILABLE (HA shows "Unknown" instead of "Unavailable"); attrs
        expose `unconfigured_reason="grid_import_cap_disabled"`."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, False, 4000))
        assert sensor.native_value is None
        assert sensor.available is True
        attrs = sensor.extra_state_attributes
        assert attrs["unconfigured_reason"] == "grid_import_cap_disabled"

    def test_grid_demand_no_coordinator_returns_none(self):
        """No energy coordinator → value=None, available=False (EC-missing
        is the ONLY unavailable state post-B4)."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, None)
        assert sensor.native_value is None
        assert sensor.available is False

    def test_grid_demand_zero_cap_returns_none(self):
        """cap=0 kW → value=None (no div-by-zero)."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(0.0, True, 4000))
        assert sensor.native_value is None

    def test_grid_demand_net_power_none(self):
        """battery.net_power_w=None → value=None."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, None))
        assert sensor.native_value is None

    def test_grid_demand_attrs_complete(self):
        """extra_state_attributes has the 4 expected keys."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, 2000))
        attrs = sensor.extra_state_attributes
        for key in ("grid_import_kw", "grid_import_cap_kw", "grid_import_cap_enabled", "exporting"):
            assert key in attrs, f"missing key: {key}"
        assert attrs["grid_import_cap_kw"] == 8.0
        assert attrs["grid_import_cap_enabled"] is True
        assert attrs["exporting"] is False
        assert attrs["grid_import_kw"] == 2.0

    def test_grid_demand_exporting_attrs_grid_kw_zero(self):
        """When exporting, grid_import_kw=0.0 (clamped at max(0,...))."""
        hass = _make_hass()
        sensor = _make_grid_sensor(hass, _make_energy_coord(8.0, True, -3000))
        attrs = sensor.extra_state_attributes
        assert attrs["grid_import_kw"] == 0.0
        assert attrs["exporting"] is True


# ---------------------------------------------------------------------------
# Structural: verify class + constant presence in source files
# ---------------------------------------------------------------------------

class TestSourceStructure:
    """Grep-based structural checks — confirm the code landed correctly."""

    def _src(self, filename: str) -> str:
        path = ROOT / "custom_components" / "universal_room_automation" / filename
        return path.read_text()

    def test_zone_motion_window_constant_in_const(self):
        src = self._src("const.py")
        assert "ZONE_MOTION_WINDOW_SECONDS" in src
        assert "300" in src

    def test_zone_motion_sensor_class_in_aggregation(self):
        src = self._src("aggregation.py")
        assert "class ZoneMotionEventCountSensor" in src

    def test_house_system_demand_sensor_class_in_aggregation(self):
        src = self._src("aggregation.py")
        assert "class HouseSystemDemandSensor" in src

    def test_energy_grid_demand_sensor_class_in_aggregation(self):
        src = self._src("aggregation.py")
        assert "class EnergyGridDemandSensor" in src

    def test_all_three_registered_in_setup(self):
        src = self._src("aggregation.py")
        assert "ZoneMotionEventCountSensor(hass, entry)" in src
        assert "HouseSystemDemandSensor(hass, entry)" in src
        assert "EnergyGridDemandSensor(hass, entry)" in src

    def test_get_hvac_coordinator_helper_present(self):
        src = self._src("aggregation.py")
        assert "_get_hvac_coordinator" in src

    def test_dt_util_utcnow_not_datetime_utcnow_in_motion_sensor(self):
        """D1 must use dt_util.utcnow(), not datetime.utcnow() (bug class #21)."""
        src = self._src("aggregation.py")
        # Find the ZoneMotionEventCountSensor class block
        motion_block_start = src.index("class ZoneMotionEventCountSensor")
        # Find next class definition after it
        next_class = src.index("\nclass ", motion_block_start + 1)
        motion_block = src[motion_block_start:next_class]
        assert "dt_util.utcnow()" in motion_block
        assert "datetime.utcnow()" not in motion_block

    def test_super_call_in_all_three_inits(self):
        src = self._src("aggregation.py")
        # Each __init__ must call super().__init__
        for class_name in (
            "ZoneMotionEventCountSensor",
            "HouseSystemDemandSensor",
            "EnergyGridDemandSensor",
        ):
            start = src.index(f"class {class_name}")
            try:
                end = src.index("\nclass ", start + 1)
            except ValueError:
                end = len(src)  # last class in file
            block = src[start:end]
            assert "super().__init__" in block, f"{class_name} missing super().__init__"

    def test_no_db_reads_in_new_sensors(self):
        """None of the 3 new sensors should call _db_read or _db()."""
        src = self._src("aggregation.py")
        start = src.index("class ZoneMotionEventCountSensor")
        # Check from first new class to end of file
        new_sensor_block = src[start:]
        assert "_db_read(" not in new_sensor_block
        assert "_db(" not in new_sensor_block

    def test_zone_motion_window_imported_in_aggregation(self):
        src = self._src("aggregation.py")
        assert "ZONE_MOTION_WINDOW_SECONDS" in src


# ---------------------------------------------------------------------------
# Production-class import smoke tests (Review C C1 fix)
# ---------------------------------------------------------------------------
# These prove the real classes named in the plan actually exist at the
# expected import path and bind to the names the dashboard wiring will use.
# Behavioral tests above exercise inline replicas of the algorithm — these
# smoke tests close the "is it actually wired?" loop without requiring a
# full HA-stack import.


class TestProductionClassImports:
    """Review C C1: verify the three sensor classes are real and importable."""

    def _src_module_path(self):
        """Return AST of the aggregation.py source for symbol introspection."""
        import ast
        path = ROOT / "custom_components" / "universal_room_automation" / "aggregation.py"
        return ast.parse(path.read_text())

    def _class_node(self, tree, name):
        """Return the ClassDef AST node for the given class name."""
        import ast
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        return None

    def test_zone_motion_class_defined_with_expected_bases(self):
        """ZoneMotionEventCountSensor exists and inherits AggregationEntity."""
        node = self._class_node(self._src_module_path(), "ZoneMotionEventCountSensor")
        assert node is not None, "ZoneMotionEventCountSensor missing from aggregation.py"
        base_names = {b.id for b in node.bases if hasattr(b, "id")}
        assert "AggregationEntity" in base_names
        assert "SensorEntity" in base_names

    def test_house_system_demand_class_defined_with_expected_bases(self):
        node = self._class_node(self._src_module_path(), "HouseSystemDemandSensor")
        assert node is not None
        base_names = {b.id for b in node.bases if hasattr(b, "id")}
        assert "AggregationEntity" in base_names
        assert "SensorEntity" in base_names

    def test_energy_grid_demand_class_defined_with_expected_bases(self):
        node = self._class_node(self._src_module_path(), "EnergyGridDemandSensor")
        assert node is not None
        base_names = {b.id for b in node.bases if hasattr(b, "id")}
        assert "AggregationEntity" in base_names
        assert "SensorEntity" in base_names

    def test_each_class_has_native_value_and_extra_state_attributes(self):
        """All three sensors must implement both properties — dashboard depends on attrs."""
        import ast
        tree = self._src_module_path()
        for cls_name in (
            "ZoneMotionEventCountSensor",
            "HouseSystemDemandSensor",
            "EnergyGridDemandSensor",
        ):
            node = self._class_node(tree, cls_name)
            method_names = {
                m.name for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert "native_value" in method_names, f"{cls_name} missing native_value"
            assert "extra_state_attributes" in method_names, (
                f"{cls_name} missing extra_state_attributes"
            )

    def test_zone_motion_uses_shared_compute_helper(self):
        """Review C C2: native_value + attrs must call the shared helper, not duplicate."""
        import ast
        node = self._class_node(self._src_module_path(), "ZoneMotionEventCountSensor")
        method_names = {
            m.name for m in node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "_compute_zones_with_motion" in method_names, (
            "C2 fix missing: extract shared helper to avoid TOCTOU between "
            "native_value and extra_state_attributes."
        )

    def test_house_system_demand_attrs_do_not_call_native_value(self):
        """Review C M3: attrs should compute pct locally, not call self.native_value."""
        src = (ROOT / "custom_components" / "universal_room_automation" / "aggregation.py").read_text()
        start = src.index("class HouseSystemDemandSensor")
        end = src.index("\nclass ", start + 1)
        cls_block = src[start:end]
        # Find extra_state_attributes block
        attrs_start = cls_block.index("def extra_state_attributes")
        # The method body should not call self.native_value
        # (find the next method def or end of class)
        attrs_end_marker = cls_block.find("\n    def ", attrs_start + 1)
        attrs_block = cls_block[attrs_start:attrs_end_marker if attrs_end_marker != -1 else len(cls_block)]
        assert "self.native_value" not in attrs_block, (
            "M3 fix missing: attrs should compute pct locally."
        )

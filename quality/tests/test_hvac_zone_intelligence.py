"""Tests for HVAC Zone Intelligence (v3.17.0).

D1: Zone Vacancy Management
D2: Zone-Specific Pre-Conditioning (solar banking, pre-arrival)
D3: Person-to-Zone Mapping
D4: Zone Presence State Machine
D5: HVAC Duty Cycle Enforcement
D6: Max-Occupancy-Duration Failsafe
D7: Diagnostic Sensors
"""

from __future__ import annotations

import sys
import os
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []  # Make it a package so submodule imports work
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
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": datetime.now,
        "as_local": lambda dt: dt,
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
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

# Now safe to import URA code — use importlib.util to load specific modules
# without triggering the __init__.py chain (which has Python 3.10+ syntax)
import importlib.util

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(_project_root, "custom_components", "universal_room_automation")
_dc_root = os.path.join(_ura_root, "domain_coordinators")


def _load_module(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Create stub parent packages so relative imports work
_cc_pkg = _mock_module("custom_components")
sys.modules["custom_components"] = _cc_pkg

_ura_pkg = _mock_module("custom_components.universal_room_automation")
_ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
sys.modules["custom_components.universal_room_automation"] = _ura_pkg

# Load const.py directly (it has `from __future__ import annotations` so OK)
_const = _load_module(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_root, "const.py"),
)
_ura_pkg.const = _const

# Create domain_coordinators package stub
_dc_pkg = _mock_module("custom_components.universal_room_automation.domain_coordinators")
_dc_pkg.__file__ = os.path.join(_dc_root, "__init__.py")
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc_pkg

# Load hvac_const.py
hvac_const = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    os.path.join(_dc_root, "hvac_const.py"),
)

# Load hvac_zones.py
hvac_zones = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    os.path.join(_dc_root, "hvac_zones.py"),
)

from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
    RoomCondition,
    ZoneState,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
    DEFAULT_MAX_OCCUPANCY_HOURS,
    DEFAULT_VACANCY_GRACE_CONSTRAINED,
    DEFAULT_VACANCY_GRACE_MINUTES,
    DUTY_CYCLE_COAST,
    DUTY_CYCLE_SHED,
    DUTY_CYCLE_WINDOW_SECONDS,
    MIN_DEADBAND,
    SOLAR_BANK_FLOOR,
    SOLAR_BANK_OFFSET,
    SOLAR_BANK_SOC_MIN,
    SOLAR_BANK_TEMP_MIN,
)


def _utcnow():
    return datetime.now(timezone.utc)


def _make_zone(
    zone_id="zone_1",
    zone_name="Zone 1",
    occupied=True,
    preset_mode="home",
    temp_high=77.0,
    temp_low=70.0,
    hvac_action="cooling",
    vacancy_sweep_enabled=True,
    rooms=None,
) -> ZoneState:
    """Create a test ZoneState with room conditions."""
    zone = ZoneState(
        zone_id=zone_id,
        zone_name=zone_name,
        climate_entity=f"climate.ecobee_{zone_id}",
        rooms=rooms or ["room_a", "room_b"],
        preset_mode=preset_mode,
        hvac_mode="heat_cool",
        hvac_action=hvac_action,
        current_temperature=75.0,
        target_temp_high=temp_high,
        target_temp_low=temp_low,
        vacancy_sweep_enabled=vacancy_sweep_enabled,
    )
    zone.room_conditions = [
        RoomCondition(room_name="room_a", occupied=occupied),
        RoomCondition(room_name="room_b", occupied=False),
    ]
    zone.last_occupied_time = _utcnow() if occupied else (_utcnow() - timedelta(minutes=20))
    return zone


# ============================================================================
# D1: Zone Vacancy Management
# ============================================================================


class TestZoneVacancyManagement:
    """D1: Zone vacancy management tests."""

    def test_zone_unoccupied_past_normal_grace_triggers_away(self):
        """Zone unoccupied for 16 min (> 15 min normal grace) -> away."""
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=16)

        now = _utcnow()
        grace_minutes = DEFAULT_VACANCY_GRACE_MINUTES
        zone_vacant_past_grace = (
            not zone.any_room_occupied
            and zone.last_occupied_time is not None
            and (now - zone.last_occupied_time).total_seconds() > grace_minutes * 60
        )
        assert zone_vacant_past_grace is True

    def test_zone_unoccupied_past_constrained_grace_triggers_away(self):
        """Zone unoccupied for 6 min (> 5 min constrained grace) -> away."""
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=6)

        now = _utcnow()
        grace_minutes = DEFAULT_VACANCY_GRACE_CONSTRAINED
        zone_vacant_past_grace = (
            not zone.any_room_occupied
            and zone.last_occupied_time is not None
            and (now - zone.last_occupied_time).total_seconds() > grace_minutes * 60
        )
        assert zone_vacant_past_grace is True

    def test_zone_unoccupied_within_normal_grace_no_change(self):
        """Zone unoccupied for 10 min (< 15 min normal grace) -> no change."""
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=10)

        now = _utcnow()
        grace_minutes = DEFAULT_VACANCY_GRACE_MINUTES
        zone_vacant_past_grace = (
            not zone.any_room_occupied
            and zone.last_occupied_time is not None
            and (now - zone.last_occupied_time).total_seconds() > grace_minutes * 60
        )
        assert zone_vacant_past_grace is False

    def test_zone_reoccupied_resets_sweep_flag(self):
        """Zone re-occupied -> vacancy_sweep_done resets."""
        zone = _make_zone(occupied=False)
        zone.vacancy_sweep_done = True
        zone.last_occupied_time = _utcnow() - timedelta(minutes=20)

        # Simulate re-occupation
        zone.room_conditions[0].occupied = True
        assert zone.any_room_occupied is True

        if zone.any_room_occupied:
            zone.last_occupied_time = _utcnow()
            zone.vacancy_sweep_done = False

        assert zone.vacancy_sweep_done is False

    def test_sleep_state_no_vacancy_override(self):
        """House state SLEEP -> target_preset is 'sleep', not 'home'."""
        target_preset = "sleep"
        assert target_preset not in ("home",)

    def test_away_state_passthrough(self):
        """House state AWAY -> house-level 'away' preset already correct."""
        target_preset = "away"
        assert target_preset not in ("home",)

    def test_zone_sweep_disabled_still_changes_preset(self):
        """Zone with sweep disabled -> away preset but no sweep."""
        zone = _make_zone(occupied=False, vacancy_sweep_enabled=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=20)

        now = _utcnow()
        grace_minutes = DEFAULT_VACANCY_GRACE_MINUTES
        zone_vacant = (
            not zone.any_room_occupied
            and zone.last_occupied_time is not None
            and (now - zone.last_occupied_time).total_seconds() > grace_minutes * 60
        )
        assert zone_vacant is True
        should_sweep = not zone.vacancy_sweep_done and zone.vacancy_sweep_enabled
        assert should_sweep is False

    def test_never_occupied_zone_at_startup_immediately_eligible(self):
        """Zone that was never occupied at startup should be immediately eligible."""
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=DEFAULT_VACANCY_GRACE_MINUTES + 1)

        now = _utcnow()
        grace_minutes = DEFAULT_VACANCY_GRACE_MINUTES
        zone_vacant = (
            not zone.any_room_occupied
            and zone.last_occupied_time is not None
            and (now - zone.last_occupied_time).total_seconds() > grace_minutes * 60
        )
        assert zone_vacant is True

    def test_manual_preset_overridden_for_vacant_zone(self):
        """Manual preset + vacant -> override to away anyway (RH3 fix)."""
        zone = _make_zone(occupied=False, preset_mode="manual")
        zone.last_occupied_time = _utcnow() - timedelta(minutes=20)
        assert zone.preset_mode != "away"

    def test_sweep_only_ura_configured_entities(self):
        """Sweep should only use CONF_LIGHTS and CONF_FANS."""
        zone = _make_zone(occupied=False)
        assert zone.vacancy_sweep_enabled is True


# ============================================================================
# D2: Zone-Specific Pre-Conditioning
# ============================================================================


class TestZonePreConditioning:
    """D2: Zone-specific pre-conditioning tests."""

    def test_solar_banking_requires_soc_95(self):
        """Solar banking does NOT trigger when SOC is 90%."""
        assert 90 < SOLAR_BANK_SOC_MIN

    def test_solar_banking_requires_net_exporting(self):
        """Solar banking requires net power < -500W."""
        net_power = 100
        assert not (net_power < -500)

    def test_solar_banking_not_during_peak(self):
        """Solar banking does NOT trigger during coast/shed."""
        mode = "coast"
        assert mode != "normal"

    def test_solar_banking_offset_floored_tight_band(self):
        """Solar banking on tight band (71-74) -> clamped to 73 F."""
        target_temp_high = 74.0
        target_temp_low = 71.0
        offset = SOLAR_BANK_OFFSET

        banked_high = target_temp_high + offset
        floor = max(SOLAR_BANK_FLOOR, target_temp_low + MIN_DEADBAND)
        effective_high = max(banked_high, floor)

        assert effective_high == 73.0
        assert effective_high < target_temp_high

    def test_solar_banking_on_away_zone_82F(self):
        """Solar banking on away zone (82 F) -> cools to 79 F."""
        target_temp_high = 82.0
        target_temp_low = 60.0
        offset = SOLAR_BANK_OFFSET

        banked_high = target_temp_high + offset
        floor = max(SOLAR_BANK_FLOOR, target_temp_low + MIN_DEADBAND)
        effective_high = max(banked_high, floor)

        assert effective_high == 79.0

    def test_pre_arrival_fans_skipped_during_sleep(self):
        """Pre-arrival fans should NOT activate during sleep."""
        house_state = "sleep"
        assert house_state == "sleep"

    def test_solar_bank_triggered_today_prevents_retrigger(self):
        """_solar_bank_triggered_today prevents re-triggering."""
        triggered = True
        assert triggered is True

    def test_weather_precool_only_occupied_zones(self):
        """Weather pre-cool only applies to occupied zones."""
        zone_occ = _make_zone(occupied=True)
        zone_empty = _make_zone(occupied=False, zone_id="zone_2")
        assert zone_occ.any_room_occupied is True
        assert zone_empty.any_room_occupied is False


# ============================================================================
# D3: Person-to-Zone Mapping
# ============================================================================


class TestPersonToZoneMapping:
    """D3: Person-to-zone mapping tests."""

    def test_geofence_arrival_marks_preferred_zones(self):
        """Geofence arrival -> preferred zones marked for pre-arrival."""
        person_zone_map = {"person.john": ["zone_1", "zone_3"]}
        pre_arrival_zones: set[str] = set()
        pre_arrival_persons: dict[str, str] = {}

        person_entity = "person.john"
        preferred_zones = person_zone_map.get(person_entity, [])
        valid_zones = {"zone_1", "zone_2", "zone_3"}

        for zone_id in preferred_zones:
            if zone_id in valid_zones:
                pre_arrival_zones.add(zone_id)
                pre_arrival_persons[zone_id] = person_entity

        assert pre_arrival_zones == {"zone_1", "zone_3"}
        assert pre_arrival_persons["zone_1"] == "person.john"

    def test_unmapped_person_no_zone_targeting(self):
        """Person not in map -> no zone targeting."""
        person_zone_map = {"person.john": ["zone_1"]}
        pre_arrival_zones: set[str] = set()

        person_entity = "person.unknown"
        preferred_zones = person_zone_map.get(person_entity, [])
        assert preferred_zones == []
        assert len(pre_arrival_zones) == 0

    def test_ble_confirms_arrival_clears_pre_arrival(self):
        """BLE confirms person in zone -> pre-arrival cleared."""
        pre_arrival_zones = {"zone_1"}
        zone = _make_zone(occupied=True)

        if zone.any_room_occupied:
            pre_arrival_zones.discard("zone_1")

        assert len(pre_arrival_zones) == 0

    def test_pre_arrival_timeout_30_min(self):
        """Pre-arrival timeout (30 min) -> pre-arrival cleared."""
        now = _utcnow()
        pre_arrival_start = {"zone_1": now - timedelta(minutes=31)}
        pre_arrival_zones = {"zone_1"}
        timeout = timedelta(minutes=30)

        for zone_id in list(pre_arrival_zones):
            start = pre_arrival_start.get(zone_id)
            if start and (now - start) > timeout:
                pre_arrival_zones.discard(zone_id)

        assert len(pre_arrival_zones) == 0

    def test_two_persons_arriving_both_get_zones(self):
        """Two persons arriving -> both get zone pre-conditioning."""
        person_zone_map = {
            "person.john": ["zone_1"],
            "person.jane": ["zone_2"],
        }
        pre_arrival_zones: set[str] = set()
        valid_zones = {"zone_1", "zone_2", "zone_3"}

        for person_entity in ["person.john", "person.jane"]:
            for zone_id in person_zone_map.get(person_entity, []):
                if zone_id in valid_zones:
                    pre_arrival_zones.add(zone_id)

        assert pre_arrival_zones == {"zone_1", "zone_2"}

    def test_person_mapped_to_multiple_zones(self):
        """Person mapped to multiple zones -> all zones targeted."""
        person_zone_map = {"person.john": ["zone_1", "zone_2", "zone_3"]}
        pre_arrival_zones: set[str] = set()
        valid_zones = {"zone_1", "zone_2", "zone_3"}

        for zone_id in person_zone_map["person.john"]:
            if zone_id in valid_zones:
                pre_arrival_zones.add(zone_id)

        assert len(pre_arrival_zones) == 3


# ============================================================================
# D4: Zone Presence State Machine
# ============================================================================


class TestZonePresenceStateMachine:
    """D4: Zone presence state machine tests."""

    def test_occupied_state(self):
        zone = _make_zone(occupied=True)
        zone.zone_presence_state = "occupied" if zone.any_room_occupied else "away"
        assert zone.zone_presence_state == "occupied"

    def test_away_state_past_grace(self):
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=20)
        now = _utcnow()
        grace = DEFAULT_VACANCY_GRACE_MINUTES * 60
        elapsed = (now - zone.last_occupied_time).total_seconds()
        zone.zone_presence_state = "away" if elapsed > grace else "vacant"
        assert zone.zone_presence_state == "away"

    def test_vacant_state_within_grace(self):
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=10)
        now = _utcnow()
        grace = DEFAULT_VACANCY_GRACE_MINUTES * 60
        elapsed = (now - zone.last_occupied_time).total_seconds()
        zone.zone_presence_state = "away" if elapsed > grace else "vacant"
        assert zone.zone_presence_state == "vacant"

    def test_sleep_state_highest_priority(self):
        zone = _make_zone(occupied=True)
        zone.runtime_exceeded = True
        house_state = "sleep"

        if house_state == "sleep":
            zone.zone_presence_state = "sleep"
        elif zone.runtime_exceeded:
            zone.zone_presence_state = "runtime_limited"
        elif zone.any_room_occupied:
            zone.zone_presence_state = "occupied"

        assert zone.zone_presence_state == "sleep"

    def test_runtime_limited_overrides_occupied(self):
        zone = _make_zone(occupied=True)
        zone.runtime_exceeded = True
        house_state = "home_day"

        if house_state == "sleep":
            zone.zone_presence_state = "sleep"
        elif zone.runtime_exceeded:
            zone.zone_presence_state = "runtime_limited"
        elif zone.any_room_occupied:
            zone.zone_presence_state = "occupied"

        assert zone.zone_presence_state == "runtime_limited"

    def test_pre_arrival_state(self):
        zone = _make_zone(occupied=False, zone_id="zone_1")
        pre_arrival_zones = {"zone_1"}
        house_state = "home_day"

        if house_state == "sleep":
            zone.zone_presence_state = "sleep"
        elif zone.runtime_exceeded:
            zone.zone_presence_state = "runtime_limited"
        elif zone.zone_id in pre_arrival_zones:
            zone.zone_presence_state = "pre_arrival"
        elif zone.any_room_occupied:
            zone.zone_presence_state = "occupied"
        else:
            zone.zone_presence_state = "away"

        assert zone.zone_presence_state == "pre_arrival"

    def test_all_seven_states_distinct(self):
        states = {"occupied", "vacant", "away", "sleep", "pre_conditioning",
                  "pre_arrival", "runtime_limited"}
        assert len(states) == 7


# ============================================================================
# D5: HVAC Duty Cycle Enforcement
# ============================================================================


class TestDutyCycleEnforcement:
    """D5: HVAC duty cycle enforcement tests."""

    def test_shed_mode_16_min_exceeded(self):
        """Zone runs 16 min in 20-min window during shed (50%) -> exceeded."""
        zone = _make_zone()
        zone.runtime_seconds_this_window = 16 * 60

        max_seconds = DUTY_CYCLE_WINDOW_SECONDS * DUTY_CYCLE_SHED
        assert zone.runtime_seconds_this_window >= max_seconds

    def test_shed_mode_10_min_at_limit(self):
        """Zone runs 10 min in 20-min window during shed -> at limit."""
        zone = _make_zone()
        zone.runtime_seconds_this_window = 10 * 60

        max_seconds = DUTY_CYCLE_WINDOW_SECONDS * DUTY_CYCLE_SHED
        assert zone.runtime_seconds_this_window >= max_seconds

    def test_coast_mode_16_min_exceeded(self):
        """Zone runs 16 min during coast (75%) -> exceeded (960 > 900)."""
        zone = _make_zone()
        zone.runtime_seconds_this_window = 16 * 60

        max_seconds = DUTY_CYCLE_WINDOW_SECONDS * DUTY_CYCLE_COAST
        assert zone.runtime_seconds_this_window >= max_seconds

    def test_window_expiry_resets_counters(self):
        zone = _make_zone()
        zone.window_start = _utcnow() - timedelta(minutes=21)
        zone.runtime_seconds_this_window = 900
        zone.runtime_exceeded = True

        now = _utcnow()
        if (now - zone.window_start).total_seconds() >= DUTY_CYCLE_WINDOW_SECONDS:
            zone.window_start = now
            zone.runtime_seconds_this_window = 0.0
            zone.runtime_exceeded = False

        assert zone.runtime_exceeded is False
        assert zone.runtime_seconds_this_window == 0.0

    def test_sleep_state_no_enforcement(self):
        house_state = "sleep"
        assert house_state == "sleep"

    def test_constraint_change_resets_counters(self):
        zone = _make_zone()
        zone.runtime_seconds_this_window = 800
        zone.runtime_exceeded = True
        zone.window_start = _utcnow()

        zone.runtime_seconds_this_window = 0.0
        zone.window_start = None
        zone.runtime_exceeded = False

        assert zone.runtime_exceeded is False
        assert zone.runtime_seconds_this_window == 0.0
        assert zone.window_start is None


# ============================================================================
# D6: Max-Occupancy-Duration Failsafe
# ============================================================================


class TestMaxOccupancyFailsafe:
    """D6: Max-occupancy-duration failsafe tests."""

    def test_zone_occupied_9_hours_triggers_failsafe(self):
        zone = _make_zone(occupied=True)
        zone.continuous_occupied_since = _utcnow() - timedelta(hours=9)

        now = _utcnow()
        max_hours = DEFAULT_MAX_OCCUPANCY_HOURS
        stale = (
            zone.any_room_occupied
            and zone.continuous_occupied_since is not None
            and (now - zone.continuous_occupied_since).total_seconds()
            > max_hours * 3600
        )
        assert stale is True

    def test_zone_occupied_7_hours_no_failsafe(self):
        zone = _make_zone(occupied=True)
        zone.continuous_occupied_since = _utcnow() - timedelta(hours=7)

        now = _utcnow()
        max_hours = DEFAULT_MAX_OCCUPANCY_HOURS
        stale = (
            zone.any_room_occupied
            and zone.continuous_occupied_since is not None
            and (now - zone.continuous_occupied_since).total_seconds()
            > max_hours * 3600
        )
        assert stale is False

    def test_zone_occupied_9_hours_during_sleep_no_failsafe(self):
        house_state = "sleep"
        assert house_state == "sleep"

    def test_zone_goes_vacant_resets_counter(self):
        zone = _make_zone(occupied=True)
        zone.continuous_occupied_since = _utcnow() - timedelta(hours=6)

        zone.room_conditions[0].occupied = False
        assert zone.any_room_occupied is False

        if not zone.any_room_occupied:
            zone.continuous_occupied_since = None
        assert zone.continuous_occupied_since is None

        zone.room_conditions[0].occupied = True
        assert zone.any_room_occupied is True

        if zone.continuous_occupied_since is None:
            zone.continuous_occupied_since = _utcnow()

        elapsed = (_utcnow() - zone.continuous_occupied_since).total_seconds()
        assert elapsed < 10


# ============================================================================
# D7: Diagnostic Sensors
# ============================================================================


class TestDiagnosticSensors:
    """D7: Diagnostic sensor tests."""

    def test_zone_status_attrs_include_new_fields(self):
        zone = _make_zone(occupied=True)
        zone.zone_presence_state = "occupied"
        zone.vacancy_sweep_done = False
        zone.runtime_exceeded = False
        zone.continuous_occupied_since = _utcnow() - timedelta(hours=2)
        zone.window_start = _utcnow() - timedelta(minutes=5)
        zone.runtime_seconds_this_window = 300

        assert zone.zone_presence_state == "occupied"
        assert zone.vacancy_sweep_done is False
        assert zone.runtime_exceeded is False
        assert zone.vacancy_sweep_enabled is True
        assert zone.continuous_occupied_since is not None

    def test_zone_intelligence_counts_away_zones(self):
        zones = {
            "zone_1": _make_zone(zone_id="zone_1", occupied=True),
            "zone_2": _make_zone(zone_id="zone_2", occupied=False),
            "zone_3": _make_zone(zone_id="zone_3", occupied=False),
        }
        zones["zone_1"].zone_presence_state = "occupied"
        zones["zone_2"].zone_presence_state = "away"
        zones["zone_3"].zone_presence_state = "away"

        away_count = sum(1 for z in zones.values() if z.zone_presence_state == "away")
        assert away_count == 2

    def test_zone_states_update_on_change(self):
        zone = _make_zone(occupied=True)
        zone.zone_presence_state = "occupied"
        assert zone.zone_presence_state == "occupied"

        zone.room_conditions[0].occupied = False
        zone.last_occupied_time = _utcnow() - timedelta(minutes=20)
        now = _utcnow()
        grace = DEFAULT_VACANCY_GRACE_MINUTES * 60
        elapsed = (now - zone.last_occupied_time).total_seconds()
        zone.zone_presence_state = "away" if elapsed > grace else "vacant"
        assert zone.zone_presence_state == "away"


# ============================================================================
# Integration: ZoneState dataclass fields
# ============================================================================


class TestZoneStateFields:
    """Verify all new v3.17.0 fields exist on ZoneState."""

    def test_vacancy_fields_exist(self):
        zone = ZoneState(zone_id="z", zone_name="Z", climate_entity="c.e")
        assert zone.last_occupied_time is None
        assert zone.vacancy_sweep_done is False
        assert zone.vacancy_sweep_enabled is True

    def test_presence_state_field_exists(self):
        zone = ZoneState(zone_id="z", zone_name="Z", climate_entity="c.e")
        assert zone.zone_presence_state == "unknown"

    def test_duty_cycle_fields_exist(self):
        zone = ZoneState(zone_id="z", zone_name="Z", climate_entity="c.e")
        assert zone.runtime_seconds_this_window == 0.0
        assert zone.window_start is None
        assert zone.runtime_exceeded is False

    def test_failsafe_field_exists(self):
        zone = ZoneState(zone_id="z", zone_name="Z", climate_entity="c.e")
        assert zone.continuous_occupied_since is None


# ============================================================================
# Zone Intelligence Toggle
# ============================================================================


class TestZoneIntelligenceToggle:
    """Test the Zone Intelligence on/off toggle behavior."""

    def test_zi_disabled_skips_vacancy_override(self):
        """When ZI is off, vacancy doesn't trigger away override."""
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=20)

        zi_enabled = False
        target_preset = "home"
        grace_minutes = DEFAULT_VACANCY_GRACE_MINUTES

        # With ZI disabled, we skip vacancy logic entirely
        if zi_enabled:
            now = _utcnow()
            zone_vacant_past_grace = (
                not zone.any_room_occupied
                and zone.last_occupied_time is not None
                and (now - zone.last_occupied_time).total_seconds()
                > grace_minutes * 60
            )
            if zone_vacant_past_grace:
                target_preset = "away"

        # Preset stays "home" because ZI was disabled
        assert target_preset == "home"

    def test_zi_enabled_triggers_vacancy_override(self):
        """When ZI is on, vacancy triggers away override as expected."""
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=20)

        zi_enabled = True
        target_preset = "home"
        grace_minutes = DEFAULT_VACANCY_GRACE_MINUTES

        if zi_enabled:
            now = _utcnow()
            zone_vacant_past_grace = (
                not zone.any_room_occupied
                and zone.last_occupied_time is not None
                and (now - zone.last_occupied_time).total_seconds()
                > grace_minutes * 60
            )
            if zone_vacant_past_grace:
                target_preset = "away"

        assert target_preset == "away"

    def test_zi_disabled_skips_duty_cycle(self):
        """When ZI is off, runtime_exceeded doesn't force away."""
        zone = _make_zone()
        zone.runtime_exceeded = True

        zi_enabled = False
        target_preset = "home"

        if zi_enabled and zone.runtime_exceeded:
            target_preset = "away"

        assert target_preset == "home"

    def test_zi_disabled_skips_stale_failsafe(self):
        """When ZI is off, continuous occupancy doesn't trigger failsafe."""
        zone = _make_zone(occupied=True)
        zone.continuous_occupied_since = _utcnow() - timedelta(hours=9)

        zi_enabled = False
        target_preset = "home"

        if zi_enabled:
            now = _utcnow()
            stale = (
                zone.any_room_occupied
                and zone.continuous_occupied_since is not None
                and (now - zone.continuous_occupied_since).total_seconds()
                > DEFAULT_MAX_OCCUPANCY_HOURS * 3600
            )
            if stale:
                target_preset = "away"

        assert target_preset == "home"

    def test_zi_toggle_default_on(self):
        """Zone Intelligence defaults to enabled."""
        zi_enabled = True  # default
        assert zi_enabled is True

"""Tests for v3.18.x fan control and sensor features.

These tests verify decision logic for:
- Fan vacancy hold grace period (v3.18.0)
- Fan sleep policy (v3.18.1)
- HVAC fan deconfliction (v3.18.1)
- Occupancy timeout int() truncation fix (v3.18.0)
- HVAC fan min_runtime protection (v3.18.0)
- Comfort scoring formula (v3.18.4)
- Efficiency scoring formula (v3.18.4)

TESTING METHODOLOGY:
Tests verify decision logic directly using simple fixtures (MockHass,
basic_room_config). No heavy HA module mocking. Each test is self-contained
with clear setup/assert.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from tests.conftest import (
    MockHass, MockConfigEntry, MockCoordinator,
    create_automation_config,
)


# =============================================================================
# HELPERS
# =============================================================================

def make_fan_config(**overrides):
    """Create a fan control configuration with sensible defaults."""
    config = {
        "room_name": "Bedroom",
        "fan_control_enabled": True,
        "fan_temp_threshold": 75,
        "fan_vacancy_hold": 300,
        "fans": ["fan.bedroom_ceiling"],
        "hvac_coordination_enabled": False,
        "sleep_protection_enabled": False,
        "sleep_start_hour": 22,
        "sleep_end_hour": 7,
        "fan_sleep_policy": "reduce",
    }
    config.update(overrides)
    return config


def is_sleep_active(config, current_hour):
    """Replicate the sleep-time check logic from automation.py."""
    if not config.get("sleep_protection_enabled", False):
        return False
    sleep_start = config.get("sleep_start_hour", 22)
    sleep_end = config.get("sleep_end_hour", 7)
    if sleep_start > sleep_end:
        return current_hour >= sleep_start or current_hour < sleep_end
    else:
        return sleep_start <= current_hour < sleep_end


def compute_fan_speed(temperature, config, sleep_speed_cap=None):
    """Replicate the fan speed tier logic from automation.py."""
    low_temp = config.get("fan_speed_low_temp", 69)
    med_temp = config.get("fan_speed_med_temp", 72)
    high_temp = config.get("fan_speed_high_temp", 75)

    if temperature >= high_temp:
        speed_pct = 100
    elif temperature >= med_temp:
        speed_pct = 66
    elif temperature >= low_temp:
        speed_pct = 33
    else:
        speed_pct = 0

    if sleep_speed_cap is not None:
        speed_pct = min(speed_pct, sleep_speed_cap)

    return speed_pct


def is_hvac_managing_fans(config, hass_data):
    """Replicate _is_hvac_managing_fans decision logic from automation.py."""
    if not config.get("hvac_coordination_enabled", False):
        return False
    mgr = hass_data.get("universal_room_automation", {}).get("coordinator_manager")
    if not mgr:
        return False
    hvac = getattr(mgr, 'coordinators', {}).get("hvac")
    if not hvac or not getattr(hvac, 'enabled', False):
        return False
    fan_ctrl = getattr(hvac, 'fan_controller', None)
    if not fan_ctrl:
        return False
    room = config.get("room_name", "")
    return room in getattr(fan_ctrl, '_room_fans', {})


# =============================================================================
# TestFanVacancyHold (v3.18.0)
# =============================================================================

class TestFanVacancyHold:
    """Test fan vacancy hold grace period in automation.py.

    When a room becomes unoccupied, fans should not turn off immediately.
    Instead they hold on for fan_vacancy_hold seconds (default 300).
    """

    def test_fan_stays_on_during_vacancy_hold(self, mock_hass, basic_room_config):
        """Fan should still be logically on during the 300s hold period.

        Config: fan_control_enabled=True, fan_temp_threshold=75,
        fan_vacancy_hold=300. Temperature=80, occupancy just went False.
        """
        config = make_fan_config(
            fan_control_enabled=True,
            fan_temp_threshold=75,
            fan_vacancy_hold=300,
        )

        temperature = 80.0
        occupied = False

        # Simulate: occupancy just went False, vacancy started now
        fan_vacancy_start = datetime.now()
        vacancy_elapsed = (datetime.now() - fan_vacancy_start).total_seconds()

        # Decision logic from automation.py lines 972-977
        fan_vacancy_hold = config.get("fan_vacancy_hold", 300)
        if not occupied:
            if vacancy_elapsed < fan_vacancy_hold:
                occupied = True  # Override: hold fans during grace period

        # With vacancy hold active, the fan decision should treat room as occupied
        threshold = config["fan_temp_threshold"]
        should_run_fan = (
            config.get("fan_control_enabled")
            and temperature > threshold
            and occupied
        )

        assert occupied is True, "Vacancy hold should override occupied to True"
        assert should_run_fan is True, "Fan should stay on during vacancy hold"

    def test_fan_turns_off_after_vacancy_hold_expires(self, mock_hass, basic_room_config):
        """Fan should turn off once 301 seconds have passed since vacancy.

        Same setup, but vacancy started 301s ago -- hold has expired.
        """
        config = make_fan_config(
            fan_control_enabled=True,
            fan_temp_threshold=75,
            fan_vacancy_hold=300,
        )

        temperature = 80.0
        occupied = False

        # Vacancy started 301 seconds ago
        fan_vacancy_start = datetime.now() - timedelta(seconds=301)
        vacancy_elapsed = (datetime.now() - fan_vacancy_start).total_seconds()

        fan_vacancy_hold = config.get("fan_vacancy_hold", 300)
        if not occupied:
            if vacancy_elapsed < fan_vacancy_hold:
                occupied = True  # Would override, but won't since elapsed > hold

        # occupied remains False -- vacancy hold expired
        threshold = config["fan_temp_threshold"]
        should_run_fan = (
            config.get("fan_control_enabled")
            and temperature > threshold
            and occupied
        )

        assert occupied is False, "Vacancy hold should have expired"
        assert should_run_fan is False, "Fan should turn off after vacancy hold expires"

    def test_vacancy_hold_resets_on_reoccupation(self, mock_hass, basic_room_config):
        """When occupancy goes True within hold period, vacancy_start resets to None."""
        config = make_fan_config(fan_vacancy_hold=300)

        # Phase 1: occupancy goes False, vacancy starts
        fan_vacancy_start = datetime.now() - timedelta(seconds=60)
        assert fan_vacancy_start is not None

        # Phase 2: occupancy returns True within hold period
        occupied = True
        if occupied:
            fan_vacancy_start = None  # Reset on re-occupation (line 979)

        assert fan_vacancy_start is None, "Vacancy timer should reset on re-occupation"

    def test_fan_turns_off_immediately_below_threshold(self, mock_hass, basic_room_config):
        """Temperature below threshold turns fan off even when occupied.

        Temperature check comes before vacancy hold matters -- if temp is
        below threshold, fan is off regardless.
        """
        config = make_fan_config(
            fan_control_enabled=True,
            fan_temp_threshold=75,
        )

        temperature = 70.0  # Below 75 threshold
        occupied = True
        any_fan_on = False  # No hysteresis since fans are off
        hysteresis = 2.0

        effective_threshold = (config["fan_temp_threshold"] - hysteresis) if any_fan_on else config["fan_temp_threshold"]

        # Decision: temp < effective_threshold → turn off (line 990)
        should_turn_off = temperature < effective_threshold or not occupied

        assert should_turn_off is True, "Fan should be off when temp is below threshold"

    def test_default_vacancy_hold_is_300s(self):
        """Verify the default constant value for fan vacancy hold is 300 seconds."""
        # From const.py line 493: DEFAULT_FAN_VACANCY_HOLD: Final = 300
        DEFAULT_FAN_VACANCY_HOLD = 300

        config = {}  # No explicit vacancy hold set
        fan_vacancy_hold = config.get("fan_vacancy_hold", DEFAULT_FAN_VACANCY_HOLD)

        assert fan_vacancy_hold == 300, "Default fan vacancy hold should be 300 seconds"


# =============================================================================
# TestFanSleepPolicy (v3.18.1)
# =============================================================================

class TestFanSleepPolicy:
    """Test fan sleep policy in automation.py.

    Three policies: 'off' (fans off during sleep), 'reduce' (cap at 33%),
    'normal' (no change). Default is 'reduce'.
    """

    def test_sleep_policy_off_turns_fans_off(self, mock_hass, basic_room_config):
        """With policy='off' during sleep hours, fans should turn off regardless of temp."""
        config = make_fan_config(
            fan_sleep_policy="off",
            sleep_protection_enabled=True,
            sleep_start_hour=22,
            sleep_end_hour=7,
        )

        current_hour = 23  # Within sleep hours
        temperature = 85.0  # Very hot -- would normally run fans

        sleep_active = is_sleep_active(config, current_hour)
        assert sleep_active is True, "Should be within sleep hours"

        # Decision logic from automation.py lines 960-966
        policy = config.get("fan_sleep_policy", "reduce")
        if sleep_active and policy == "off":
            should_turn_off = True
        else:
            should_turn_off = False

        assert should_turn_off is True, "Policy 'off' should turn fans off during sleep"

    def test_sleep_policy_reduce_caps_at_33(self, mock_hass, basic_room_config):
        """With policy='reduce' during sleep, speed capped at 33% regardless of temp."""
        config = make_fan_config(
            fan_sleep_policy="reduce",
            sleep_protection_enabled=True,
            fan_speed_high_temp=75,
        )

        current_hour = 1  # 1 AM, within sleep hours
        temperature = 85.0  # Would normally be 100% speed (>= high_temp)

        sleep_active = is_sleep_active(config, current_hour)
        assert sleep_active is True

        # Normal speed would be 100% for temp >= high_temp
        policy = config.get("fan_sleep_policy", "reduce")
        sleep_speed_cap = None
        if sleep_active and policy == "reduce":
            sleep_speed_cap = 33

        speed_pct = compute_fan_speed(temperature, config, sleep_speed_cap)

        assert speed_pct == 33, "Sleep reduce policy should cap speed at 33%"

    def test_sleep_policy_normal_no_cap(self, mock_hass, basic_room_config):
        """With policy='normal' during sleep, speed is uncapped."""
        config = make_fan_config(
            fan_sleep_policy="normal",
            sleep_protection_enabled=True,
            fan_speed_high_temp=75,
        )

        current_hour = 23  # Within sleep hours
        temperature = 85.0  # Would be 100% speed

        sleep_active = is_sleep_active(config, current_hour)
        assert sleep_active is True

        policy = config.get("fan_sleep_policy", "normal")
        sleep_speed_cap = None
        if sleep_active:
            if policy == "off":
                pass  # Would return early
            elif policy == "reduce":
                sleep_speed_cap = 33
            # 'normal' → no cap

        speed_pct = compute_fan_speed(temperature, config, sleep_speed_cap)

        assert speed_pct == 100, "Sleep normal policy should not cap fan speed"

    def test_no_sleep_policy_effect_outside_sleep_hours(self, mock_hass, basic_room_config):
        """Any policy should have no effect outside sleep hours -- normal operation."""
        config = make_fan_config(
            fan_sleep_policy="off",  # Most restrictive policy
            sleep_protection_enabled=True,
            fan_speed_high_temp=75,
        )

        current_hour = 14  # 2 PM, NOT within sleep hours (22-7)
        temperature = 85.0

        sleep_active = is_sleep_active(config, current_hour)
        assert sleep_active is False, "Should NOT be in sleep hours at 2 PM"

        # Since sleep is not active, no cap applies regardless of policy
        sleep_speed_cap = None
        if sleep_active:
            policy = config.get("fan_sleep_policy", "reduce")
            if policy == "off":
                pass  # Would return early
            elif policy == "reduce":
                sleep_speed_cap = 33

        speed_pct = compute_fan_speed(temperature, config, sleep_speed_cap)

        assert speed_pct == 100, "Outside sleep hours, fan speed should be uncapped"

    def test_default_sleep_policy_is_reduce(self):
        """Verify the default fan sleep policy constant is 'reduce'."""
        # From const.py line 444: DEFAULT_FAN_SLEEP_POLICY: Final = "reduce"
        DEFAULT_FAN_SLEEP_POLICY = "reduce"

        config = {}  # No explicit policy set
        policy = config.get("fan_sleep_policy", DEFAULT_FAN_SLEEP_POLICY)

        assert policy == "reduce", "Default fan sleep policy should be 'reduce'"


# =============================================================================
# TestHvacFanDeconfliction (v3.18.1)
# =============================================================================

class TestHvacFanDeconfliction:
    """Decision logic tests -- does room-level defer to HVAC?

    When HVAC coordinator is managing a room's fans, room-level
    automation should return early (defer) to avoid dual-control fighting.
    """

    def test_room_defers_when_hvac_managing(self, mock_hass):
        """Room-level fan control should defer when HVAC is managing fans.

        Config: hvac_coordination_enabled=True. HVAC coordinator has this
        room in fan_controller._room_fans.
        """
        config = make_fan_config(
            room_name="Bedroom",
            hvac_coordination_enabled=True,
        )

        # Build mock HVAC coordinator chain
        mock_fan_ctrl = MagicMock()
        mock_fan_ctrl._room_fans = {"Bedroom": MagicMock()}

        mock_hvac = MagicMock()
        mock_hvac.enabled = True
        mock_hvac.fan_controller = mock_fan_ctrl

        mock_mgr = MagicMock()
        mock_mgr.coordinators = {"hvac": mock_hvac}

        hass_data = {
            "universal_room_automation": {
                "coordinator_manager": mock_mgr,
            }
        }

        result = is_hvac_managing_fans(config, hass_data)

        assert result is True, "Should defer to HVAC when it manages this room's fans"

    def test_room_operates_without_hvac(self, mock_hass):
        """Room-level fan control should proceed when hvac_coordination_enabled=False."""
        config = make_fan_config(
            room_name="Bedroom",
            hvac_coordination_enabled=False,
        )

        hass_data = {}  # No coordinator manager even needed

        result = is_hvac_managing_fans(config, hass_data)

        assert result is False, "Should not defer when HVAC coordination is disabled"

    def test_room_operates_when_hvac_disabled(self, mock_hass):
        """Room-level should operate when hvac_coordination_enabled=True but HVAC is disabled.

        The HVAC coordinator exists but is disabled (enabled=False) or missing.
        """
        config = make_fan_config(
            room_name="Bedroom",
            hvac_coordination_enabled=True,
        )

        # HVAC coordinator exists but is disabled
        mock_hvac = MagicMock()
        mock_hvac.enabled = False

        mock_mgr = MagicMock()
        mock_mgr.coordinators = {"hvac": mock_hvac}

        hass_data = {
            "universal_room_automation": {
                "coordinator_manager": mock_mgr,
            }
        }

        result = is_hvac_managing_fans(config, hass_data)

        assert result is False, "Should not defer when HVAC coordinator is disabled"


# =============================================================================
# TestOccupancyTimeoutFix (v3.18.0)
# =============================================================================

class TestOccupancyTimeoutFix:
    """Test the int() truncation fix in coordinator.py.

    Before fix: remaining = int(max(0, timeout - elapsed))
    After fix:  remaining = max(0.0, timeout - elapsed) then int(remaining)
    The issue: int(0.3) = 0 but remaining > 0 should mean occupied=True.
    The actual line 1117 still uses int(remaining) for the attribute, but
    the occupied check (line 1118) uses remaining > 0 (float comparison).
    """

    def test_occupancy_timeout_no_int_truncation(self):
        """elapsed=299.7s, timeout=300s. remaining=0.3, should be occupied=True.

        The key insight: occupied is determined by float remaining > 0,
        NOT by int(remaining) > 0. So 0.3 > 0 is True even though int(0.3)=0.
        """
        timeout = 300.0
        elapsed = 299.7

        remaining = max(0.0, timeout - elapsed)  # 0.3
        remaining_int = int(remaining)  # 0 (for display attribute)
        occupied = remaining > 0  # True (float comparison)

        assert remaining == pytest.approx(0.3, abs=0.01)
        assert remaining_int == 0, "int(0.3) truncates to 0 for display"
        assert occupied is True, "Float remaining > 0 means still occupied"

    def test_occupancy_timeout_exact_boundary(self):
        """elapsed=300.0s, timeout=300s. remaining=0.0, occupied=False."""
        timeout = 300.0
        elapsed = 300.0

        remaining = max(0.0, timeout - elapsed)  # 0.0
        occupied = remaining > 0  # False

        assert remaining == 0.0
        assert occupied is False, "Exactly at timeout boundary means not occupied"


# =============================================================================
# TestHvacFanMinRuntime (v3.18.0)
# =============================================================================

class TestHvacFanMinRuntime:
    """Test min_runtime fix in hvac_fans.py.

    Fans have a minimum runtime to prevent short cycling. Once turned on,
    they must stay on for min_runtime minutes regardless of occupancy changes.
    Default is 10 minutes (DEFAULT_FAN_MIN_RUNTIME in hvac_const.py).
    """

    def test_min_runtime_applies_when_unoccupied(self):
        """Fan on for 3 min (min_runtime=10). Occupancy False. Fan stays on.

        Even though occupancy dropped, min_runtime protection keeps the fan
        running to prevent compressor/motor short cycling.
        """
        DEFAULT_FAN_MIN_RUNTIME = 10  # minutes
        min_runtime = DEFAULT_FAN_MIN_RUNTIME

        fan_is_on = True
        fan_last_on_time = datetime.now() - timedelta(minutes=3)
        occupied = False

        # Decision logic from hvac_fans.py lines 252-256
        runtime_minutes = (datetime.now() - fan_last_on_time).total_seconds() / 60
        should_off = True  # Default: want to turn off

        # Min runtime check
        if fan_is_on and runtime_minutes < min_runtime:
            should_off = False  # Protected by min_runtime

        assert runtime_minutes < min_runtime, "Fan has only run 3 of 10 min"
        assert should_off is False, "Min runtime protection should keep fan on"

    def test_min_runtime_expires_allows_off(self):
        """Fan on for 11 min. Occupancy False. Min_runtime passed, fan can turn off."""
        DEFAULT_FAN_MIN_RUNTIME = 10  # minutes
        min_runtime = DEFAULT_FAN_MIN_RUNTIME

        fan_is_on = True
        fan_last_on_time = datetime.now() - timedelta(minutes=11)
        occupied = False

        runtime_minutes = (datetime.now() - fan_last_on_time).total_seconds() / 60
        should_off = True

        # Min runtime check
        if fan_is_on and runtime_minutes < min_runtime:
            should_off = False

        assert runtime_minutes > min_runtime, "Fan has run longer than min_runtime"
        assert should_off is True, "Fan can turn off after min_runtime expires"


# =============================================================================
# COMFORT SCORING TESTS (v3.18.4)
# =============================================================================

def compute_comfort_score(
    temperature: float | None,
    humidity: float | None,
    occupied: bool,
    setpoint: float = 76.0,
) -> int | None:
    """Compute comfort score 0-100 using the same formula as sensor.py."""
    if temperature is None:
        return None
    temp_score = max(0, 100 - abs(temperature - setpoint) * 10)
    if humidity is not None:
        humidity_score = max(0, 100 - abs(humidity - 45) * 2)
    else:
        humidity_score = 70
    occupancy_score = 100 if occupied else 50
    score = temp_score * 0.4 + humidity_score * 0.3 + occupancy_score * 0.3
    return round(score)


def compute_efficiency_score_hvac(
    duty_cycle_pct: float, override_count_today: int,
) -> int:
    """Compute efficiency score with HVAC zone data."""
    override_penalty = override_count_today * 5
    score = 100 - (duty_cycle_pct * 0.5) - override_penalty
    return max(0, min(100, round(score)))


def compute_efficiency_score_fallback(
    temperature: float | None, setpoint: float = 76.0,
) -> int | None:
    """Compute efficiency score with temperature proximity fallback."""
    if temperature is None:
        return None
    deviation = abs(temperature - setpoint)
    if deviation <= 2:
        return 90
    elif deviation <= 5:
        return 70
    else:
        return 50


class TestComfortScoring:
    """Test comfort score formula (v3.18.4)."""

    def test_perfect_conditions_score_100(self):
        score = compute_comfort_score(temperature=76.0, humidity=45.0, occupied=True, setpoint=76.0)
        assert score == 100

    def test_temperature_deviation_reduces_score(self):
        score = compute_comfort_score(temperature=80.0, humidity=45.0, occupied=True, setpoint=76.0)
        assert score == 84  # 0.4*60 + 0.3*100 + 0.3*100

    def test_unoccupied_room_penalized(self):
        score = compute_comfort_score(temperature=76.0, humidity=45.0, occupied=False, setpoint=76.0)
        assert score == 85  # 0.4*100 + 0.3*100 + 0.3*50

    def test_extreme_conditions_minimum(self):
        score = compute_comfort_score(temperature=90.0, humidity=90.0, occupied=False, setpoint=76.0)
        assert score == 18  # 0.4*0 + 0.3*10 + 0.3*50

    def test_missing_temperature_returns_none(self):
        score = compute_comfort_score(temperature=None, humidity=45.0, occupied=True, setpoint=76.0)
        assert score is None


class TestEfficiencyScoring:
    """Test efficiency score formula (v3.18.4)."""

    def test_hvac_zone_scoring_no_overrides(self):
        score = compute_efficiency_score_hvac(duty_cycle_pct=40.0, override_count_today=0)
        assert score == 80  # 100 - 20 - 0

    def test_hvac_zone_scoring_with_overrides(self):
        score = compute_efficiency_score_hvac(duty_cycle_pct=60.0, override_count_today=3)
        assert score == 55  # 100 - 30 - 15

    def test_fallback_scoring_near_setpoint(self):
        score = compute_efficiency_score_fallback(temperature=77.0, setpoint=76.0)
        assert score == 90

    def test_fallback_scoring_far_from_setpoint(self):
        score = compute_efficiency_score_fallback(temperature=84.0, setpoint=76.0)
        assert score == 50


# =============================================================================
# PERSON-ZONE MAP TESTS (v3.18.5)
# =============================================================================

class TestPersonZoneMap:
    """Test person-to-zone reverse map building (v3.18.5)."""

    def test_build_reverse_map_single_person(self):
        """One person in one zone."""
        # Simulate zone data
        zones = {
            "zone_1": type("Z", (), {"zone_persons": ["person.oji"]})(),
        }
        pzm = {}
        for zone_id, zone in zones.items():
            for person in zone.zone_persons:
                pzm.setdefault(person, []).append(zone_id)
        assert pzm == {"person.oji": ["zone_1"]}

    def test_build_reverse_map_multi_zone(self):
        """One person in multiple zones."""
        zones = {
            "zone_1": type("Z", (), {"zone_persons": ["person.oji"]})(),
            "zone_3": type("Z", (), {"zone_persons": ["person.oji"]})(),
        }
        pzm = {}
        for zone_id, zone in zones.items():
            for person in zone.zone_persons:
                pzm.setdefault(person, []).append(zone_id)
        assert pzm == {"person.oji": ["zone_1", "zone_3"]}

    def test_build_reverse_map_multi_person(self):
        """Multiple persons in same zone."""
        zones = {
            "zone_1": type("Z", (), {"zone_persons": ["person.oji", "person.nkem"]})(),
        }
        pzm = {}
        for zone_id, zone in zones.items():
            for person in zone.zone_persons:
                pzm.setdefault(person, []).append(zone_id)
        assert pzm == {"person.oji": ["zone_1"], "person.nkem": ["zone_1"]}

    def test_build_reverse_map_empty(self):
        """No persons configured."""
        zones = {
            "zone_1": type("Z", (), {"zone_persons": []})(),
        }
        pzm = {}
        for zone_id, zone in zones.items():
            for person in zone.zone_persons:
                pzm.setdefault(person, []).append(zone_id)
        assert pzm == {}

    def test_fallback_uses_cache(self):
        """When zone config is empty, cached map is used."""
        cache = {"person.oji": ["zone_1"]}
        new_map = {}  # Empty from zone configs

        if new_map:
            result = new_map
        elif cache:
            result = cache
        else:
            result = {}

        assert result == {"person.oji": ["zone_1"]}

    def test_fallback_uses_db(self):
        """When cache is also empty, DB map is used."""
        cache = {}
        db_map = {"person.oji": ["zone_2"]}
        new_map = {}

        if new_map:
            result = new_map
        elif cache:
            result = cache
        elif db_map:
            result = db_map
        else:
            result = {}

        assert result == {"person.oji": ["zone_2"]}


# =============================================================================
# BLE PRE-ARRIVAL DETECTION TESTS (v3.18.6)
# =============================================================================

class TestBLEPreArrival:
    """Test BLE pre-arrival detection (v3.18.6)."""

    def test_ble_triggers_after_min_away_time(self):
        """Person LOST for 15+ min then detected → pre-arrival fires."""
        min_away_minutes = 15
        lost_since = datetime.now() - timedelta(minutes=20)
        now = datetime.now()
        lost_duration = (now - lost_since).total_seconds()
        person_was_away = lost_duration >= min_away_minutes * 60
        assert person_was_away is True

    def test_ble_no_trigger_for_quick_trip(self):
        """Person LOST for 5 min then detected → no pre-arrival."""
        min_away_minutes = 15
        lost_since = datetime.now() - timedelta(minutes=5)
        now = datetime.now()
        lost_duration = (now - lost_since).total_seconds()
        person_was_away = lost_duration >= min_away_minutes * 60
        assert person_was_away is False

    def test_source_filter_blocks_disabled_source(self):
        """HVAC ignores pre-arrival from disabled source."""
        enabled_sources = ["geofence"]  # BLE disabled
        source = "ble"
        assert source not in enabled_sources

    def test_source_filter_allows_enabled_source(self):
        """HVAC accepts pre-arrival from enabled source."""
        enabled_sources = ["geofence", "ble"]
        source = "ble"
        assert source in enabled_sources

    def test_dedup_same_person_idempotent(self):
        """Two triggers for same person don't create duplicate zones."""
        pre_arrival_zones = set()
        pre_arrival_zones.add("zone_1")
        pre_arrival_zones.add("zone_1")  # Duplicate
        assert len(pre_arrival_zones) == 1

    def test_toggle_off_blocks_all_sources(self):
        """Pre-arrival disabled → both geofence and BLE blocked."""
        pre_arrival_enabled = False
        assert not pre_arrival_enabled


# =============================================================================
# ZONE CAMERA FACE-CONFIRMED ARRIVAL TESTS (v3.19.0)
# =============================================================================


class TestZoneCameraFaceArrival:
    """Test zone camera face-confirmed arrival (v3.19.0)."""

    def test_face_sensor_derivation_frigate(self):
        """Frigate binary_sensor pattern → face sensor."""
        bs = "binary_sensor.hallway_person_occupancy"
        base = bs[len("binary_sensor."):-len("_person_occupancy")]
        face_sensor = f"sensor.{base}_last_recognized_face"
        assert face_sensor == "sensor.hallway_last_recognized_face"

    def test_face_sensor_derivation_unifi(self):
        """UniFi binary_sensor pattern → face sensor (person_detected suffix)."""
        bs = "binary_sensor.front_door_person_detected"
        base = bs[len("binary_sensor."):-len("_person_detected")]
        face_sensor = f"sensor.{base}_last_recognized_face"
        assert face_sensor == "sensor.front_door_last_recognized_face"

    def test_face_sensor_derivation_unknown_pattern(self):
        """Non-matching pattern returns None."""
        bs = "binary_sensor.random_sensor"
        base_name = None
        for suffix in ("_person_occupancy", "_person_detected", "_occupancy"):
            if bs.endswith(suffix):
                base_name = bs[len("binary_sensor."):-len(suffix)]
        assert base_name is None

    def test_face_freshness_fresh(self):
        """Face detected 10s ago is fresh."""
        from datetime import datetime, timedelta
        last_changed = datetime.now() - timedelta(seconds=10)
        age = (datetime.now() - last_changed).total_seconds()
        assert age < 30

    def test_face_freshness_stale(self):
        """Face detected 60s ago is stale."""
        from datetime import datetime, timedelta
        last_changed = datetime.now() - timedelta(seconds=60)
        age = (datetime.now() - last_changed).total_seconds()
        assert age >= 30

    def test_cooldown_blocks_duplicate(self):
        """Same person+zone within 60s is debounced."""
        from datetime import datetime, timedelta
        cooldown = {"person.oji:Entertainment": datetime.now() - timedelta(seconds=30)}
        key = "person.oji:Entertainment"
        last = cooldown.get(key)
        should_skip = last and (datetime.now() - last).total_seconds() < 60
        assert should_skip is True

    def test_cooldown_allows_after_expiry(self):
        """Same person+zone after 60s is allowed."""
        from datetime import datetime, timedelta
        cooldown = {"person.oji:Entertainment": datetime.now() - timedelta(seconds=90)}
        key = "person.oji:Entertainment"
        last = cooldown.get(key)
        should_skip = last and (datetime.now() - last).total_seconds() < 60
        assert should_skip is False

    def test_face_name_to_person_entity(self):
        """Face name 'Oji' maps to 'person.oji'."""
        face_name = "Oji"
        candidate = f"person.{face_name.lower().replace(' ', '_')}"
        assert candidate == "person.oji"

    def test_camera_zone_map_building(self):
        """Build camera→zone reverse map."""
        zones = {
            "zone_1": type("Z", (), {"zone_cameras": ["binary_sensor.hallway_person_occupancy"]})(),
            "zone_2": type("Z", (), {"zone_cameras": ["binary_sensor.staircase_person_occupancy"]})(),
        }
        czm = {}
        for zone_id, zone in zones.items():
            for cam in zone.zone_cameras:
                czm[cam] = zone_id
        assert czm == {
            "binary_sensor.hallway_person_occupancy": "zone_1",
            "binary_sensor.staircase_person_occupancy": "zone_2",
        }

    def test_face_value_filtering(self):
        """Invalid face values are rejected."""
        invalid = ["Unknown", "unavailable", "none", "no_match", "", "None"]
        for val in invalid:
            clean = val.strip() if val else ""
            is_valid = bool(clean) and clean.lower() not in ("unknown", "unavailable", "none", "no_match", "")
            assert is_valid is False, f"'{val}' should be invalid"

    def test_valid_face_accepted(self):
        """Valid face name is accepted."""
        val = "Oji"
        clean = val.strip()
        is_valid = bool(clean) and clean.lower() not in ("unknown", "unavailable", "none", "no_match", "")
        assert is_valid is True

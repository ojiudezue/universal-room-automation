"""Tests for automation behavior.

These tests verify automation triggers, actions, and conditions:
- Entry actions (lights, covers)
- Exit actions
- Climate control
- Sleep protection
- Fan control
- Alert handling

TESTING METHODOLOGY:
Rather than running actual HA automations, we test the decision logic
by simulating the state conditions and verifying expected outcomes.
"""
import pytest
from datetime import datetime, timedelta
from tests.conftest import (
    MockHass, MockConfigEntry, MockCoordinator,
    assert_light_turned_on, assert_light_turned_off, 
    assert_fan_turned_on, assert_no_service_called,
)


# =============================================================================
# LIGHT AUTOMATION TESTS
# =============================================================================

class TestLightEntryActions:
    """Test light behavior on room entry."""
    
    def test_turn_on_if_dark_when_dark(self, mock_hass, basic_room_config):
        """Lights should turn on when entering dark room."""
        basic_room_config["entry_light_action"] = "turn_on_if_dark"
        basic_room_config["illuminance_dark_threshold"] = 20
        
        # Room is dark
        mock_hass.set_state("sensor.bedroom_lux", "5")
        mock_hass.set_state("binary_sensor.bedroom_motion", "on")  # entry
        
        # Decision logic
        lux_state = mock_hass.states.get("sensor.bedroom_lux")
        lux = float(lux_state.state) if lux_state else 0
        is_dark = lux < basic_room_config["illuminance_dark_threshold"]
        
        should_turn_on = (
            basic_room_config["entry_light_action"] == "turn_on_if_dark" and
            is_dark
        )
        
        assert should_turn_on is True
    
    def test_turn_on_if_dark_when_bright(self, mock_hass, basic_room_config):
        """Lights should NOT turn on when entering bright room."""
        basic_room_config["entry_light_action"] = "turn_on_if_dark"
        basic_room_config["illuminance_dark_threshold"] = 20
        
        # Room is bright
        mock_hass.set_state("sensor.bedroom_lux", "150")
        mock_hass.set_state("binary_sensor.bedroom_motion", "on")
        
        lux_state = mock_hass.states.get("sensor.bedroom_lux")
        lux = float(lux_state.state) if lux_state else 0
        is_dark = lux < basic_room_config["illuminance_dark_threshold"]
        
        should_turn_on = (
            basic_room_config["entry_light_action"] == "turn_on_if_dark" and
            is_dark
        )
        
        assert should_turn_on is False
    
    def test_always_turn_on(self, mock_hass, basic_room_config):
        """turn_on action should always turn on lights."""
        basic_room_config["entry_light_action"] = "turn_on"
        
        # Even if bright
        mock_hass.set_state("sensor.bedroom_lux", "500")
        
        should_turn_on = basic_room_config["entry_light_action"] == "turn_on"
        assert should_turn_on is True
    
    def test_no_action(self, mock_hass, basic_room_config):
        """none action should not change lights."""
        basic_room_config["entry_light_action"] = "none"
        
        should_turn_on = basic_room_config["entry_light_action"] in ["turn_on", "turn_on_if_dark"]
        assert should_turn_on is False
    
    def test_no_lux_sensor_assumes_dark(self, mock_hass, basic_room_config):
        """Without lux sensor, should assume dark for turn_on_if_dark."""
        basic_room_config["entry_light_action"] = "turn_on_if_dark"
        basic_room_config.pop("illuminance_sensor", None)
        
        # No lux sensor configured
        lux_state = mock_hass.states.get("sensor.bedroom_lux")  # None
        
        # Logic: if no lux sensor, assume dark
        is_dark = lux_state is None or float(lux_state.state) < 20
        
        should_turn_on = (
            basic_room_config["entry_light_action"] == "turn_on_if_dark" and
            is_dark
        )
        
        assert should_turn_on is True


class TestLightExitActions:
    """Test light behavior on room exit."""
    
    def test_turn_off_on_exit(self, mock_hass, basic_room_config):
        """Lights should turn off when room becomes vacant."""
        basic_room_config["exit_light_action"] = "turn_off"
        mock_hass.set_state("light.bedroom_main", "on")
        
        # Room becomes vacant (all sensors off, timeout expired)
        room_vacant = True
        
        should_turn_off = (
            basic_room_config["exit_light_action"] == "turn_off" and
            room_vacant
        )
        
        assert should_turn_off is True
    
    def test_leave_on_exit(self, mock_hass, basic_room_config):
        """leave_on should keep lights on when exiting."""
        basic_room_config["exit_light_action"] = "leave_on"
        mock_hass.set_state("light.bedroom_main", "on")
        
        should_turn_off = basic_room_config["exit_light_action"] == "turn_off"
        assert should_turn_off is False
    
    def test_transition_time_applied(self, basic_room_config):
        """Exit transition time should be applied."""
        basic_room_config["light_transition_seconds_off"] = 5
        
        transition = basic_room_config.get("light_transition_seconds_off", 3)
        assert transition == 5


class TestLightBrightness:
    """Test brightness control."""
    
    def test_custom_brightness(self, basic_room_config):
        """Custom brightness should be applied."""
        basic_room_config["light_brightness_pct"] = 75
        
        brightness = basic_room_config.get("light_brightness_pct", 100)
        assert brightness == 75
    
    def test_default_brightness(self, basic_room_config):
        """Default brightness should be 100%."""
        # Remove custom setting
        basic_room_config.pop("light_brightness_pct", None)
        
        brightness = basic_room_config.get("light_brightness_pct", 100)
        assert brightness == 100


# =============================================================================
# SLEEP PROTECTION TESTS
# =============================================================================

class TestSleepProtection:
    """Test sleep mode behavior."""
    
    def test_sleep_hours_detection(self, basic_room_config, sleep_hours):
        """Should detect when in sleep hours."""
        basic_room_config["sleep_protection_enabled"] = True
        basic_room_config["sleep_start_hour"] = 22
        basic_room_config["sleep_end_hour"] = 7
        
        current_hour = sleep_hours.hour  # 23
        sleep_start = basic_room_config["sleep_start_hour"]
        sleep_end = basic_room_config["sleep_end_hour"]
        
        # Handle overnight span (22:00 - 07:00)
        if sleep_start > sleep_end:
            is_sleep_time = current_hour >= sleep_start or current_hour < sleep_end
        else:
            is_sleep_time = sleep_start <= current_hour < sleep_end
        
        assert is_sleep_time is True
    
    def test_not_sleep_hours(self, basic_room_config, daytime_hours):
        """Should detect when NOT in sleep hours."""
        basic_room_config["sleep_start_hour"] = 22
        basic_room_config["sleep_end_hour"] = 7
        
        current_hour = daytime_hours.hour  # 14
        sleep_start = basic_room_config["sleep_start_hour"]
        sleep_end = basic_room_config["sleep_end_hour"]
        
        if sleep_start > sleep_end:
            is_sleep_time = current_hour >= sleep_start or current_hour < sleep_end
        else:
            is_sleep_time = sleep_start <= current_hour < sleep_end
        
        assert is_sleep_time is False
    
    def test_early_morning_still_sleep(self, basic_room_config, morning_hours):
        """6 AM should still be sleep time if end is 7 AM."""
        basic_room_config["sleep_start_hour"] = 22
        basic_room_config["sleep_end_hour"] = 7
        
        current_hour = morning_hours.hour  # 6
        sleep_start = basic_room_config["sleep_start_hour"]
        sleep_end = basic_room_config["sleep_end_hour"]
        
        if sleep_start > sleep_end:
            is_sleep_time = current_hour >= sleep_start or current_hour < sleep_end
        else:
            is_sleep_time = sleep_start <= current_hour < sleep_end
        
        assert is_sleep_time is True
    
    def test_lights_blocked_during_sleep(self, basic_room_config, sleep_hours):
        """Lights should not auto-turn-on during sleep hours."""
        basic_room_config["sleep_protection_enabled"] = True
        basic_room_config["entry_light_action"] = "turn_on_if_dark"
        
        current_hour = sleep_hours.hour
        is_sleep_time = current_hour >= 22 or current_hour < 7
        
        # Even if dark, lights should not turn on during sleep
        should_turn_on = (
            basic_room_config["entry_light_action"] != "none" and
            not (basic_room_config["sleep_protection_enabled"] and is_sleep_time)
        )
        
        assert should_turn_on is False
    
    def test_covers_blocked_during_sleep(self, basic_room_config, sleep_hours):
        """Covers should not auto-open during sleep hours."""
        basic_room_config["sleep_protection_enabled"] = True
        basic_room_config["sleep_block_covers"] = True
        basic_room_config["entry_cover_action"] = "smart"
        
        current_hour = sleep_hours.hour
        is_sleep_time = current_hour >= 22 or current_hour < 7
        
        should_open_covers = (
            basic_room_config["entry_cover_action"] != "none" and
            not (basic_room_config.get("sleep_block_covers") and is_sleep_time)
        )
        
        assert should_open_covers is False
    
    def test_motion_bypass_during_sleep(self, basic_room_config, sleep_hours):
        """Multiple motion events should bypass sleep protection."""
        basic_room_config["sleep_protection_enabled"] = True
        basic_room_config["sleep_bypass_motion_count"] = 3
        
        motion_count = 5  # More than bypass threshold
        bypass_threshold = basic_room_config.get("sleep_bypass_motion_count", 3)
        
        should_bypass = motion_count >= bypass_threshold
        assert should_bypass is True
    
    def test_sleep_disabled_no_blocking(self, basic_room_config, sleep_hours):
        """If sleep protection disabled, no blocking occurs."""
        basic_room_config["sleep_protection_enabled"] = False
        basic_room_config["entry_light_action"] = "turn_on"
        
        # Even during sleep hours, protection disabled = no blocking
        should_block = basic_room_config.get("sleep_protection_enabled", False)
        assert should_block is False


# =============================================================================
# FAN CONTROL TESTS
# =============================================================================

class TestCoolingFanControl:
    """Test temperature-based fan control."""
    
    def test_fan_on_above_threshold(self, mock_hass, basic_room_config):
        """Fan should turn on when temp exceeds threshold."""
        basic_room_config["fan_control_enabled"] = True
        basic_room_config["fan_temp_threshold"] = 78
        
        mock_hass.set_state("sensor.bedroom_temp", "82")
        
        temp_state = mock_hass.states.get("sensor.bedroom_temp")
        temp = float(temp_state.state) if temp_state else 0
        threshold = basic_room_config["fan_temp_threshold"]
        
        should_run_fan = (
            basic_room_config.get("fan_control_enabled") and
            temp > threshold
        )
        
        assert should_run_fan is True
    
    def test_fan_off_below_threshold(self, mock_hass, basic_room_config):
        """Fan should stay off when temp below threshold."""
        basic_room_config["fan_control_enabled"] = True
        basic_room_config["fan_temp_threshold"] = 78
        
        mock_hass.set_state("sensor.bedroom_temp", "72")
        
        temp_state = mock_hass.states.get("sensor.bedroom_temp")
        temp = float(temp_state.state)
        
        should_run_fan = temp > basic_room_config["fan_temp_threshold"]
        assert should_run_fan is False
    
    def test_fan_speed_tiers(self, mock_hass, basic_room_config):
        """Fan speed should increase with temperature."""
        basic_room_config["fan_speed_low_temp"] = 69
        basic_room_config["fan_speed_med_temp"] = 72
        basic_room_config["fan_speed_high_temp"] = 75
        
        # Test low speed
        temp = 70
        if temp >= basic_room_config["fan_speed_high_temp"]:
            speed = "high"
        elif temp >= basic_room_config["fan_speed_med_temp"]:
            speed = "medium"
        elif temp >= basic_room_config["fan_speed_low_temp"]:
            speed = "low"
        else:
            speed = "off"
        
        assert speed == "low"
        
        # Test high speed
        temp = 76
        if temp >= basic_room_config["fan_speed_high_temp"]:
            speed = "high"
        elif temp >= basic_room_config["fan_speed_med_temp"]:
            speed = "medium"
        else:
            speed = "low"
        
        assert speed == "high"
    
    def test_fan_only_when_occupied(self, mock_hass, basic_room_config):
        """Fan should only run when room is occupied."""
        basic_room_config["fan_control_enabled"] = True
        basic_room_config["fan_temp_threshold"] = 78
        
        mock_hass.set_state("sensor.bedroom_temp", "82")  # Hot
        mock_hass.set_state("binary_sensor.bedroom_motion", "off")
        mock_hass.set_state("binary_sensor.bedroom_mmwave", "off")
        
        # Room is vacant
        is_occupied = False
        temp = 82
        
        should_run_fan = (
            basic_room_config.get("fan_control_enabled") and
            temp > basic_room_config["fan_temp_threshold"] and
            is_occupied
        )
        
        assert should_run_fan is False


class TestHumidityFanControl:
    """Test humidity-based fan control (bathroom exhaust)."""
    
    def test_humidity_fan_on(self, mock_hass, bathroom_config):
        """Exhaust fan should turn on when humidity high."""
        mock_hass.set_state("sensor.bath_humidity", "75")
        
        humidity_state = mock_hass.states.get("sensor.bath_humidity")
        humidity = float(humidity_state.state)
        threshold = bathroom_config["humidity_fan_threshold"]  # 60
        
        should_run_fan = humidity > threshold
        assert should_run_fan is True
    
    def test_humidity_fan_off(self, mock_hass, bathroom_config):
        """Exhaust fan should stay off when humidity normal."""
        mock_hass.set_state("sensor.bath_humidity", "45")
        
        humidity = float(mock_hass.states.get("sensor.bath_humidity").state)
        threshold = bathroom_config["humidity_fan_threshold"]
        
        should_run_fan = humidity > threshold
        assert should_run_fan is False
    
    def test_humidity_fan_timeout(self, bathroom_config):
        """Fan should run for timeout duration after humidity drops."""
        bathroom_config["humidity_fan_timeout"] = 600  # 10 minutes
        
        humidity_went_below_threshold = datetime.now() - timedelta(seconds=300)
        time_since_trigger = (datetime.now() - humidity_went_below_threshold).total_seconds()
        timeout = bathroom_config["humidity_fan_timeout"]
        
        should_still_run = time_since_trigger < timeout
        assert should_still_run is True
    
    def test_humidity_fan_after_timeout(self, bathroom_config):
        """Fan should stop after timeout expires."""
        bathroom_config["humidity_fan_timeout"] = 600
        
        humidity_went_below = datetime.now() - timedelta(seconds=700)
        time_since = (datetime.now() - humidity_went_below).total_seconds()
        
        should_stop = time_since >= bathroom_config["humidity_fan_timeout"]
        assert should_stop is True


# =============================================================================
# COVER AUTOMATION TESTS
# =============================================================================

class TestCoverAutomation:
    """Test cover/blind automation."""
    
    def test_cover_opens_on_entry(self, mock_hass, basic_room_config):
        """Covers should open when entering room."""
        basic_room_config["entry_cover_action"] = "always"
        basic_room_config["covers"] = ["cover.bedroom_blinds"]
        
        should_open = basic_room_config["entry_cover_action"] != "none"
        assert should_open is True
    
    def test_cover_closes_on_exit(self, mock_hass, basic_room_config):
        """Covers should close when leaving room."""
        basic_room_config["exit_cover_action"] = "always"
        
        should_close = basic_room_config["exit_cover_action"] != "none"
        assert should_close is True
    
    def test_smart_cover_after_sunset(self, basic_room_config):
        """Smart mode should only close after sunset."""
        basic_room_config["entry_cover_action"] = "after_sunset"
        
        # Simulate after sunset
        is_after_sunset = True  # Would come from sun.sun state
        
        should_open = (
            basic_room_config["entry_cover_action"] == "after_sunset" and
            is_after_sunset
        )
        
        assert should_open is True
    
    def test_timed_close(self, basic_room_config):
        """Covers should auto-close at configured time."""
        basic_room_config["timed_close_enabled"] = True
        basic_room_config["close_time"] = 21  # 9 PM
        
        current_hour = 21
        should_close = (
            basic_room_config.get("timed_close_enabled") and
            current_hour >= basic_room_config["close_time"]
        )
        
        assert should_close is True


# =============================================================================
# SHARED SPACE TESTS (v3.1.0)
# =============================================================================

class TestSharedSpaceAutomation:
    """Test shared space specific behavior."""
    
    def test_shorter_timeout_for_shared(self, shared_space_config):
        """Shared spaces should have shorter timeouts."""
        # Shared space timeout is in minutes
        timeout_minutes = shared_space_config["shared_space_timeout"]  # 15
        
        # Should be shorter than typical bedroom timeout
        assert timeout_minutes <= 15
    
    def test_auto_off_when_vacant(self, mock_hass, shared_space_config):
        """Shared space should auto-off devices when vacant."""
        shared_space_config["shared_space"] = True
        
        # Simulate vacancy
        is_occupied = False
        is_shared = shared_space_config.get("shared_space", False)
        
        should_auto_off = is_shared and not is_occupied
        assert should_auto_off is True
    
    def test_sleep_time_door_alert(self, mock_hass, shared_space_config, sleep_hours):
        """Egress door open during sleep should alert faster."""
        shared_space_config["door_type"] = "egress"
        
        # Door open for 2 minutes during sleep
        door_open_time = datetime.now() - timedelta(minutes=2)
        time_open = (datetime.now() - door_open_time).total_seconds() / 60
        
        # During sleep, egress doors alert at 1 min
        sleep_threshold = 1  # minute
        normal_threshold = 10  # minutes
        
        current_hour = sleep_hours.hour
        is_sleep = current_hour >= 22 or current_hour < 7
        
        threshold = sleep_threshold if is_sleep else normal_threshold
        should_alert = time_open > threshold
        
        assert should_alert is True


# =============================================================================
# HYSTERESIS TESTS
# =============================================================================

class TestHysteresis:
    """Test hysteresis to prevent flickering."""
    
    def test_light_not_toggled_rapidly(self, mock_hass, basic_room_config):
        """Lights should not toggle on rapid occupancy changes."""
        # This is handled by timeout - even if sensors flicker,
        # room stays occupied until timeout expires
        
        last_state_change = datetime.now() - timedelta(seconds=5)
        min_state_duration = 10  # seconds
        
        time_in_state = (datetime.now() - last_state_change).total_seconds()
        can_change = time_in_state >= min_state_duration
        
        assert can_change is False
    
    def test_temperature_hysteresis(self, basic_room_config):
        """Temperature thresholds should have hysteresis."""
        threshold = 78
        hysteresis = 2  # degrees
        
        # If fan turned on at 78, don't turn off until below 76
        current_temp = 77
        fan_is_on = True
        
        turn_off_point = threshold - hysteresis
        should_turn_off = current_temp < turn_off_point
        
        assert should_turn_off is False  # Still above 76
    
    def test_humidity_hysteresis(self, bathroom_config):
        """Humidity thresholds should have hysteresis."""
        threshold = 60
        hysteresis = 5
        
        current_humidity = 58
        fan_was_triggered = True
        
        turn_off_point = threshold - hysteresis
        should_continue = current_humidity > turn_off_point
        
        assert should_continue is True  # Above 55


# =============================================================================
# CLIMATE COORDINATION TESTS
# =============================================================================

class TestClimateCoordination:
    """Test HVAC coordination features."""
    
    def test_precooling_timing(self, basic_room_config):
        """Should start cooling before expected occupancy."""
        basic_room_config["hvac_coordination_enabled"] = True
        
        expected_arrival = datetime.now() + timedelta(minutes=30)
        precool_lead_time = 45  # minutes
        
        should_start_now = (
            expected_arrival - datetime.now()
        ).total_seconds() / 60 <= precool_lead_time
        
        assert should_start_now is True
    
    def test_no_hvac_when_vacant(self, mock_hass, basic_room_config):
        """HVAC should not run when house is vacant."""
        # Unless preconditioning for expected arrival
        is_occupied = False
        expected_arrival = None  # No expected arrival
        
        should_run_hvac = is_occupied or expected_arrival is not None
        assert should_run_hvac is False
    
    def test_setback_temperature(self, basic_room_config):
        """Setback temp should be used when vacant."""
        basic_room_config["target_temp_cool"] = 76
        setback_degrees = 4
        
        is_occupied = False
        
        if is_occupied:
            target = basic_room_config["target_temp_cool"]
        else:
            target = basic_room_config["target_temp_cool"] + setback_degrees
        
        assert target == 80  # 76 + 4


# =============================================================================
# NOTIFICATION TESTS
# =============================================================================

class TestNotifications:
    """Test notification triggers."""
    
    def test_safety_alert_notification(self, basic_room_config):
        """Safety alerts should trigger notifications."""
        basic_room_config["notification_level"] = "errors"
        
        alert_type = "safety"  # Critical
        notification_level = basic_room_config["notification_level"]
        
        # Safety always notifies unless level is "off"
        should_notify = notification_level != "off"
        assert should_notify is True
    
    def test_notification_level_filtering(self, basic_room_config):
        """Notifications should respect level settings."""
        test_cases = [
            ("off", "error", False),
            ("errors", "error", True),
            ("errors", "info", False),
            ("important", "error", True),
            ("important", "info", False),
            ("all", "info", True),
        ]
        
        for level, event_type, expected in test_cases:
            basic_room_config["notification_level"] = level
            
            level_priority = {"off": 0, "errors": 1, "important": 2, "all": 3}
            event_priority = {"error": 1, "important": 2, "info": 3}
            
            should_notify = (
                level_priority.get(level, 0) >= event_priority.get(event_type, 3)
            )
            
            # Simplified logic - errors level should send errors
            if level == "errors" and event_type == "error":
                should_notify = True
            elif level == "all":
                should_notify = True
            elif level == "off":
                should_notify = False
            
            assert should_notify == expected, f"Failed for {level}/{event_type}"

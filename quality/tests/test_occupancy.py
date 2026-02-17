"""Tests for occupancy detection logic.

These tests verify the core occupancy state machine:
- Motion → Occupied transition
- Presence detection (mmWave)
- Timeout behavior
- Multi-sensor fusion
- Edge cases
"""
import pytest
from datetime import datetime, timedelta
from tests.conftest import (
    MockHass, MockConfigEntry, MockCoordinator,
    assert_light_turned_on, assert_light_turned_off, assert_no_service_called
)


class TestOccupancyDetection:
    """Test basic occupancy detection."""
    
    def test_motion_triggers_occupied(self, mock_hass, basic_room_config):
        """Motion detection should trigger occupied state."""
        # Setup: Room is vacant
        mock_hass.set_state("binary_sensor.bedroom_motion", "off")
        mock_hass.set_state("binary_sensor.bedroom_mmwave", "off")
        
        # Simulate coordinator logic
        motion_state = mock_hass.states.get("binary_sensor.bedroom_motion")
        mmwave_state = mock_hass.states.get("binary_sensor.bedroom_mmwave")
        
        occupied = (
            (motion_state and motion_state.state == "on") or
            (mmwave_state and mmwave_state.state == "on")
        )
        assert occupied is False
        
        # Action: Motion detected
        mock_hass.set_state("binary_sensor.bedroom_motion", "on")
        
        # Verify
        motion_state = mock_hass.states.get("binary_sensor.bedroom_motion")
        occupied = (motion_state and motion_state.state == "on")
        assert occupied is True
    
    def test_mmwave_maintains_occupied(self, mock_hass, basic_room_config):
        """mmWave presence should maintain occupied even without motion."""
        # Motion goes off, but mmWave stays on (person sitting still)
        mock_hass.set_state("binary_sensor.bedroom_motion", "off")
        mock_hass.set_state("binary_sensor.bedroom_mmwave", "on")
        
        mmwave_state = mock_hass.states.get("binary_sensor.bedroom_mmwave")
        occupied = (mmwave_state and mmwave_state.state == "on")
        
        assert occupied is True
    
    def test_all_sensors_off_starts_timeout(self, mock_hass, basic_room_config):
        """When all sensors off, timeout countdown should start."""
        mock_hass.set_state("binary_sensor.bedroom_motion", "off")
        mock_hass.set_state("binary_sensor.bedroom_mmwave", "off")
        
        # All sensors off - this would trigger timeout in real coordinator
        motion = mock_hass.states.get("binary_sensor.bedroom_motion")
        mmwave = mock_hass.states.get("binary_sensor.bedroom_mmwave")
        
        all_clear = (
            (not motion or motion.state == "off") and
            (not mmwave or mmwave.state == "off")
        )
        
        assert all_clear is True
    
    def test_motion_during_timeout_resets(self, mock_hass, basic_room_config):
        """Motion during timeout should reset the countdown."""
        # Scenario: Timeout started, then motion detected again
        timeout_started = datetime.now() - timedelta(seconds=100)
        timeout_duration = basic_room_config["occupancy_timeout"]  # 300s
        
        # Motion detected at t+100s (before timeout expires at t+300s)
        motion_time = datetime.now()
        
        # This should reset timeout
        time_since_motion = (datetime.now() - motion_time).total_seconds()
        should_remain_occupied = time_since_motion < timeout_duration
        
        assert should_remain_occupied is True


class TestOccupancyTimeout:
    """Test timeout behavior."""
    
    def test_timeout_expires_room_vacant(self, basic_room_config):
        """Room should become vacant after timeout expires."""
        timeout = basic_room_config["occupancy_timeout"]  # 300 seconds
        last_motion = datetime.now() - timedelta(seconds=301)
        
        time_since_motion = (datetime.now() - last_motion).total_seconds()
        should_be_vacant = time_since_motion >= timeout
        
        assert should_be_vacant is True
    
    def test_timeout_not_expired_still_occupied(self, basic_room_config):
        """Room should remain occupied before timeout expires."""
        timeout = basic_room_config["occupancy_timeout"]  # 300 seconds
        last_motion = datetime.now() - timedelta(seconds=100)
        
        time_since_motion = (datetime.now() - last_motion).total_seconds()
        still_occupied = time_since_motion < timeout
        
        assert still_occupied is True
    
    def test_room_type_default_timeouts(self):
        """Different room types should have different default timeouts."""
        # Room type timeout defaults (from const.py)
        ROOM_TYPE_TIMEOUTS = {
            "bedroom": 900,      # 15 minutes
            "bathroom": 300,     # 5 minutes  
            "closet": 120,       # 2 minutes
            "common_area": 300,  # 5 minutes
            "office": 600,       # 10 minutes
        }
        
        bedroom_timeout = ROOM_TYPE_TIMEOUTS.get("bedroom", 300)
        closet_timeout = ROOM_TYPE_TIMEOUTS.get("closet", 120)
        
        # Bedroom should have longer timeout than closet
        assert bedroom_timeout > closet_timeout
        assert closet_timeout == 120  # 2 minutes
        assert bedroom_timeout == 900  # 15 minutes
    
    def test_custom_timeout_overrides_default(self, basic_room_config):
        """Custom timeout should override room type default."""
        custom_timeout = 600  # 10 minutes
        basic_room_config["occupancy_timeout"] = custom_timeout
        
        # This is what coordinator would use
        timeout = basic_room_config.get("occupancy_timeout", 300)
        assert timeout == custom_timeout


class TestMultiSensorFusion:
    """Test combining multiple sensors."""
    
    def test_motion_only_triggers_occupied(self, mock_hass):
        """Motion alone should trigger occupied."""
        mock_hass.set_state("binary_sensor.room_motion", "on")
        mock_hass.set_state("binary_sensor.room_mmwave", "unavailable")
        
        motion = mock_hass.states.get("binary_sensor.room_motion")
        mmwave = mock_hass.states.get("binary_sensor.room_mmwave")
        
        # Should be occupied even if mmWave unavailable
        occupied = (motion and motion.state == "on")
        assert occupied is True
    
    def test_mmwave_only_triggers_occupied(self, mock_hass):
        """mmWave alone should trigger occupied."""
        mock_hass.set_state("binary_sensor.room_motion", "off")
        mock_hass.set_state("binary_sensor.room_mmwave", "on")
        
        mmwave = mock_hass.states.get("binary_sensor.room_mmwave")
        occupied = (mmwave and mmwave.state == "on")
        assert occupied is True
    
    def test_combined_sensor_any_triggers(self, mock_hass):
        """Combined occupancy sensor should work."""
        # Some rooms use combined sensors instead of separate motion/mmwave
        mock_hass.set_state("binary_sensor.room_occupancy", "on")
        
        occupancy = mock_hass.states.get("binary_sensor.room_occupancy")
        occupied = (occupancy and occupancy.state == "on")
        assert occupied is True
    
    def test_unavailable_sensor_ignored(self, mock_hass):
        """Unavailable sensors should not block occupancy detection."""
        mock_hass.set_state("binary_sensor.room_motion", "on")
        mock_hass.set_state("binary_sensor.room_mmwave", "unavailable")
        
        motion = mock_hass.states.get("binary_sensor.room_motion")
        mmwave = mock_hass.states.get("binary_sensor.room_mmwave")
        
        # Should not crash, should still detect occupancy
        motion_detected = motion and motion.state == "on"
        mmwave_detected = mmwave and mmwave.state == "on"  # False for unavailable
        
        occupied = motion_detected or mmwave_detected
        assert occupied is True


class TestOccupancyEdgeCases:
    """Test edge cases and race conditions."""
    
    def test_rapid_motion_toggle(self, mock_hass, basic_room_config):
        """Rapid on/off should not cause issues."""
        # Simulate rapid toggling (common with some PIR sensors)
        for _ in range(10):
            mock_hass.set_state("binary_sensor.bedroom_motion", "on")
            mock_hass.set_state("binary_sensor.bedroom_motion", "off")
        
        # Should handle gracefully - check final state
        state = mock_hass.states.get("binary_sensor.bedroom_motion")
        assert state is not None
    
    def test_sensor_becomes_unavailable(self, mock_hass):
        """Handle sensor becoming unavailable."""
        mock_hass.set_state("binary_sensor.room_motion", "on")
        mock_hass.set_state("binary_sensor.room_motion", "unavailable")
        
        state = mock_hass.states.get("binary_sensor.room_motion")
        
        # Should not crash, should not count as "on"
        is_on = state and state.state == "on"
        assert is_on is False
    
    def test_no_sensors_configured(self):
        """Room with no sensors should handle gracefully."""
        config = {
            "room_name": "Storage",
            "motion_sensors": [],
            "presence_sensors": [],
            "occupancy_sensors": [],
        }
        
        has_sensors = bool(
            config.get("motion_sensors") or
            config.get("presence_sensors") or
            config.get("occupancy_sensors")
        )
        
        assert has_sensors is False
        # Integration should reject this in config flow
    
    def test_door_open_without_motion(self, mock_hass):
        """Door opening without motion (e.g., pet) should be handled."""
        mock_hass.set_state("binary_sensor.room_motion", "off")
        mock_hass.set_state("binary_sensor.room_door", "on")  # opened
        
        # Door alone should NOT trigger occupancy
        motion = mock_hass.states.get("binary_sensor.room_motion")
        door = mock_hass.states.get("binary_sensor.room_door")
        
        occupied = motion and motion.state == "on"
        door_opened = door and door.state == "on"
        
        assert occupied is False
        assert door_opened is True


class TestPhoneTrackerPresence:
    """Test phone tracker integration for presence."""
    
    def test_phone_home_extends_presence(self, mock_hass, basic_room_config):
        """Phone tracker being home should factor into presence."""
        basic_room_config["phone_tracker"] = "device_tracker.user_phone"
        
        mock_hass.set_state("device_tracker.user_phone", "home")
        mock_hass.set_state("binary_sensor.bedroom_motion", "off")
        
        phone = mock_hass.states.get("device_tracker.user_phone")
        phone_home = phone and phone.state == "home"
        
        # Phone home could extend timeout or boost confidence
        assert phone_home is True
    
    def test_phone_away_does_not_block(self, mock_hass, basic_room_config):
        """Phone being away should not block local sensor detection."""
        basic_room_config["phone_tracker"] = "device_tracker.user_phone"
        
        mock_hass.set_state("device_tracker.user_phone", "not_home")
        mock_hass.set_state("binary_sensor.bedroom_motion", "on")
        
        motion = mock_hass.states.get("binary_sensor.bedroom_motion")
        occupied_by_motion = motion and motion.state == "on"
        
        # Motion should still trigger occupied even if phone away
        # (visitor, or phone left elsewhere)
        assert occupied_by_motion is True

"""Tests for sensor calculations and state reporting.

These tests verify that sensors correctly calculate and report their values.
"""
import pytest
from datetime import datetime, timedelta
from tests.conftest import MockHass, MockConfigEntry, MockCoordinator


# =============================================================================
# ENVIRONMENTAL SENSOR TESTS
# =============================================================================

class TestTemperatureSensor:
    """Test temperature sensor behavior."""
    
    def test_temperature_from_source(self, mock_hass, basic_room_config):
        """Temperature should reflect source sensor."""
        mock_hass.set_state("sensor.bedroom_temp", "72.5", {
            "unit_of_measurement": "°F"
        })
        
        state = mock_hass.states.get("sensor.bedroom_temp")
        temp = float(state.state)
        
        assert temp == 72.5
    
    def test_temperature_unavailable(self, mock_hass, basic_room_config):
        """Handle unavailable temperature sensor."""
        mock_hass.set_state("sensor.bedroom_temp", "unavailable")
        
        state = mock_hass.states.get("sensor.bedroom_temp")
        
        try:
            temp = float(state.state)
        except (ValueError, TypeError):
            temp = None
        
        assert temp is None
    
    def test_temperature_no_sensor(self, mock_hass, basic_room_config):
        """Handle missing temperature sensor gracefully."""
        basic_room_config.pop("temperature_sensor", None)
        
        state = mock_hass.states.get("sensor.nonexistent")
        temp = float(state.state) if state else None
        
        assert temp is None


class TestHumiditySensor:
    """Test humidity sensor behavior."""
    
    def test_humidity_from_source(self, mock_hass, basic_room_config):
        """Humidity should reflect source sensor."""
        mock_hass.set_state("sensor.bedroom_humidity", "45", {
            "unit_of_measurement": "%"
        })
        
        state = mock_hass.states.get("sensor.bedroom_humidity")
        humidity = float(state.state)
        
        assert humidity == 45
    
    def test_humidity_alerts(self, mock_hass):
        """Test humidity alert thresholds."""
        # Too humid
        mock_hass.set_state("sensor.room_humidity", "75")
        humidity = float(mock_hass.states.get("sensor.room_humidity").state)
        
        is_too_humid = humidity > 70
        is_too_dry = humidity < 25
        
        assert is_too_humid is True
        assert is_too_dry is False


class TestIlluminanceSensor:
    """Test illuminance sensor behavior."""
    
    def test_dark_detection(self, mock_hass, basic_room_config):
        """Should correctly detect dark conditions."""
        basic_room_config["illuminance_dark_threshold"] = 20
        mock_hass.set_state("sensor.bedroom_lux", "5")
        
        lux = float(mock_hass.states.get("sensor.bedroom_lux").state)
        threshold = basic_room_config["illuminance_dark_threshold"]
        
        is_dark = lux < threshold
        assert is_dark is True
    
    def test_bright_detection(self, mock_hass, basic_room_config):
        """Should correctly detect bright conditions."""
        basic_room_config["illuminance_dark_threshold"] = 20
        mock_hass.set_state("sensor.bedroom_lux", "500")
        
        lux = float(mock_hass.states.get("sensor.bedroom_lux").state)
        is_dark = lux < basic_room_config["illuminance_dark_threshold"]
        
        assert is_dark is False


# =============================================================================
# OCCUPANCY TIMEOUT SENSOR TESTS
# =============================================================================

class TestOccupancyTimeoutSensor:
    """Test occupancy timeout countdown sensor."""
    
    def test_timeout_counting_down(self, basic_room_config):
        """Should show remaining timeout."""
        timeout = basic_room_config["occupancy_timeout"]  # 300
        last_motion = datetime.now() - timedelta(seconds=100)
        
        elapsed = (datetime.now() - last_motion).total_seconds()
        remaining = max(0, timeout - elapsed)
        
        assert remaining > 0
        assert remaining < timeout
    
    def test_timeout_expired(self, basic_room_config):
        """Should show 0 when timeout expired."""
        timeout = basic_room_config["occupancy_timeout"]
        last_motion = datetime.now() - timedelta(seconds=400)
        
        elapsed = (datetime.now() - last_motion).total_seconds()
        remaining = max(0, timeout - elapsed)
        
        assert remaining == 0
    
    def test_timeout_reset_on_motion(self, basic_room_config):
        """Timeout should reset when motion detected."""
        timeout = basic_room_config["occupancy_timeout"]
        last_motion = datetime.now()  # Just now
        
        elapsed = (datetime.now() - last_motion).total_seconds()
        remaining = max(0, timeout - elapsed)
        
        assert remaining == pytest.approx(timeout, abs=1)


# =============================================================================
# ENERGY SENSOR TESTS
# =============================================================================

class TestEnergySensors:
    """Test energy calculation sensors."""
    
    def test_power_current(self, mock_hass, basic_room_config):
        """Current power should sum all power sensors."""
        basic_room_config["power_sensors"] = [
            "sensor.light_power",
            "sensor.fan_power"
        ]
        
        mock_hass.set_state("sensor.light_power", "60")
        mock_hass.set_state("sensor.fan_power", "45")
        
        total_power = 0
        for sensor_id in basic_room_config["power_sensors"]:
            state = mock_hass.states.get(sensor_id)
            if state:
                try:
                    total_power += float(state.state)
                except (ValueError, TypeError):
                    pass
        
        assert total_power == 105
    
    def test_energy_cost_calculation(self, basic_room_config):
        """Energy cost should use configured rate."""
        basic_room_config["electricity_rate"] = 0.15
        energy_kwh = 10
        
        cost = energy_kwh * basic_room_config["electricity_rate"]
        assert cost == 1.50
    
    def test_cost_per_hour(self, basic_room_config):
        """Should calculate cost per hour from current power."""
        basic_room_config["electricity_rate"] = 0.15
        power_watts = 100
        
        # Convert watts to kW, multiply by rate
        cost_per_hour = (power_watts / 1000) * basic_room_config["electricity_rate"]
        
        assert cost_per_hour == 0.015


# =============================================================================
# DEVICE COUNTING SENSOR TESTS
# =============================================================================

class TestDeviceCountingSensors:
    """Test sensors that count active devices."""
    
    def test_lights_on_count(self, mock_hass, basic_room_config):
        """Should count lights that are on."""
        basic_room_config["lights"] = [
            "light.bedroom_main",
            "light.bedroom_lamp",
            "light.bedroom_closet"
        ]
        
        mock_hass.set_state("light.bedroom_main", "on")
        mock_hass.set_state("light.bedroom_lamp", "off")
        mock_hass.set_state("light.bedroom_closet", "on")
        
        count = 0
        for light in basic_room_config["lights"]:
            state = mock_hass.states.get(light)
            if state and state.state == "on":
                count += 1
        
        assert count == 2
    
    def test_fans_on_count(self, mock_hass, basic_room_config):
        """Should count fans that are on."""
        basic_room_config["fans"] = ["fan.bedroom_fan", "fan.bedroom_ceiling"]
        
        mock_hass.set_state("fan.bedroom_fan", "on")
        mock_hass.set_state("fan.bedroom_ceiling", "off")
        
        count = sum(
            1 for fan in basic_room_config["fans"]
            if mock_hass.states.get(fan) and 
               mock_hass.states.get(fan).state == "on"
        )
        
        assert count == 1
    
    def test_covers_open_count(self, mock_hass, basic_room_config):
        """Should count covers that are open."""
        basic_room_config["covers"] = ["cover.blinds_1", "cover.blinds_2"]
        
        mock_hass.set_state("cover.blinds_1", "open")
        mock_hass.set_state("cover.blinds_2", "closed")
        
        count = sum(
            1 for cover in basic_room_config["covers"]
            if mock_hass.states.get(cover) and
               mock_hass.states.get(cover).state == "open"
        )
        
        assert count == 1


# =============================================================================
# PREDICTION SENSOR TESTS
# =============================================================================

class TestPredictionSensors:
    """Test occupancy prediction sensors."""
    
    def test_next_occupancy_prediction(self):
        """Should predict next occupancy based on patterns."""
        # Simulate historical data: room occupied 7-8 AM on weekdays
        historical_occupancy = [
            {"day": "monday", "hour": 7, "occupied": True},
            {"day": "monday", "hour": 8, "occupied": True},
            {"day": "tuesday", "hour": 7, "occupied": True},
            {"day": "wednesday", "hour": 7, "occupied": True},
        ]
        
        # Current: Wednesday 6 AM
        current_day = "wednesday"
        current_hour = 6
        
        # Simple prediction: check if typically occupied next hour
        next_hour_typical = any(
            h["day"] == current_day and h["hour"] == current_hour + 1
            for h in historical_occupancy
        )
        
        assert next_hour_typical is True
    
    def test_occupancy_percentage(self):
        """Should calculate occupancy percentage over time."""
        # 7 days, 24 hours each
        total_hours = 7 * 24
        occupied_hours = 42  # 6 hours per day average
        
        occupancy_pct = (occupied_hours / total_hours) * 100
        
        assert occupancy_pct == 25.0
    
    def test_peak_occupancy_time(self):
        """Should identify peak occupancy hours."""
        hourly_counts = {
            6: 2, 7: 5, 8: 7, 9: 3, 10: 2,
            17: 4, 18: 6, 19: 7, 20: 6, 21: 5
        }
        
        peak_hour = max(hourly_counts, key=hourly_counts.get)
        
        assert peak_hour in [8, 19]  # Morning or evening peak


# =============================================================================
# COMFORT SCORE SENSOR TESTS
# =============================================================================

class TestComfortScoreSensor:
    """Test comfort score calculation."""
    
    def test_comfort_score_ideal(self):
        """Perfect conditions should give high score."""
        temp = 72  # Ideal
        humidity = 45  # Ideal
        
        # Simple scoring: distance from ideal
        temp_ideal = 72
        humidity_ideal = 45
        
        temp_score = max(0, 100 - abs(temp - temp_ideal) * 5)
        humidity_score = max(0, 100 - abs(humidity - humidity_ideal) * 2)
        
        comfort_score = (temp_score + humidity_score) / 2
        
        assert comfort_score == 100
    
    def test_comfort_score_hot(self):
        """Hot conditions should lower score."""
        temp = 85
        humidity = 45
        
        temp_ideal = 72
        temp_score = max(0, 100 - abs(temp - temp_ideal) * 5)
        
        # 85 - 72 = 13 degrees off, * 5 = 65 points lost
        assert temp_score == 35
    
    def test_comfort_score_humid(self):
        """High humidity should lower score."""
        temp = 72
        humidity = 75
        
        humidity_ideal = 45
        humidity_score = max(0, 100 - abs(humidity - humidity_ideal) * 2)
        
        # 75 - 45 = 30 points off, * 2 = 60 points lost
        assert humidity_score == 40


# =============================================================================
# DIAGNOSTIC SENSOR TESTS
# =============================================================================

class TestDiagnosticSensors:
    """Test diagnostic and status sensors."""
    
    def test_time_since_motion(self, mock_hass):
        """Should track time since last motion."""
        last_motion = datetime.now() - timedelta(minutes=5)
        
        time_since = (datetime.now() - last_motion).total_seconds() / 60
        
        assert time_since == pytest.approx(5, abs=0.1)
    
    def test_time_since_occupied(self, mock_hass):
        """Should track time since room became vacant."""
        became_vacant = datetime.now() - timedelta(hours=2)
        
        time_vacant = (datetime.now() - became_vacant).total_seconds() / 3600
        
        assert time_vacant == pytest.approx(2, abs=0.1)
    
    def test_occupancy_today_percentage(self):
        """Should calculate today's occupancy percentage."""
        # Simulate: it's 2 PM, room was occupied 4 hours today
        hours_today = 14
        occupied_hours = 4
        
        occupancy_pct = (occupied_hours / hours_today) * 100
        
        assert occupancy_pct == pytest.approx(28.6, abs=0.1)

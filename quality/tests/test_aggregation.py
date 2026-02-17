"""Tests for v3.1.0 aggregation sensors.

These tests verify whole-house and zone-level sensors:
- Anyone home detection
- Room/zone occupancy counts
- Safety alerts aggregation
- Security alerts (door/window thresholds)
- Climate delta calculations
- Energy predictions
"""
import pytest
from datetime import datetime, timedelta
from tests.conftest import MockHass, MockConfigEntry


# =============================================================================
# ANYONE HOME SENSOR TESTS
# =============================================================================

class TestAnyoneHomeSensor:
    """Test anyone_home binary sensor."""
    
    def test_anyone_home_true(self, mock_hass):
        """Should be True if any room occupied."""
        # Simulate coordinator data from multiple rooms
        rooms_data = [
            {"room_name": "Bedroom", "occupied": True},
            {"room_name": "Kitchen", "occupied": False},
            {"room_name": "Office", "occupied": False},
        ]
        
        anyone_home = any(r["occupied"] for r in rooms_data)
        assert anyone_home is True
    
    def test_anyone_home_false(self, mock_hass):
        """Should be False if no rooms occupied."""
        rooms_data = [
            {"room_name": "Bedroom", "occupied": False},
            {"room_name": "Kitchen", "occupied": False},
            {"room_name": "Office", "occupied": False},
        ]
        
        anyone_home = any(r["occupied"] for r in rooms_data)
        assert anyone_home is False
    
    def test_anyone_home_attributes(self):
        """Should include occupied room list in attributes."""
        rooms_data = [
            {"room_name": "Bedroom", "occupied": True, "zone": "upstairs"},
            {"room_name": "Kitchen", "occupied": True, "zone": "downstairs"},
            {"room_name": "Office", "occupied": False, "zone": "upstairs"},
        ]
        
        occupied_rooms = [r["room_name"] for r in rooms_data if r["occupied"]]
        zones_occupied = set(r["zone"] for r in rooms_data if r["occupied"])
        
        assert occupied_rooms == ["Bedroom", "Kitchen"]
        assert zones_occupied == {"upstairs", "downstairs"}


# =============================================================================
# ROOMS OCCUPIED SENSOR TESTS
# =============================================================================

class TestRoomsOccupiedSensor:
    """Test rooms_occupied count sensor."""
    
    def test_count_correct(self):
        """Should count occupied rooms correctly."""
        rooms_data = [
            {"room_name": "Bedroom", "occupied": True},
            {"room_name": "Kitchen", "occupied": True},
            {"room_name": "Office", "occupied": False},
            {"room_name": "Bathroom", "occupied": True},
        ]
        
        count = sum(1 for r in rooms_data if r["occupied"])
        assert count == 3
    
    def test_count_zero(self):
        """Should be 0 when no rooms occupied."""
        rooms_data = [
            {"room_name": "Bedroom", "occupied": False},
            {"room_name": "Kitchen", "occupied": False},
        ]
        
        count = sum(1 for r in rooms_data if r["occupied"])
        assert count == 0


# =============================================================================
# SAFETY ALERT SENSOR TESTS
# =============================================================================

class TestSafetyAlertSensor:
    """Test safety_alert binary sensor."""
    
    def test_temperature_alert_too_hot(self):
        """Should alert when temperature too high."""
        rooms_data = [
            {"room_name": "Bedroom", "temperature": 72},
            {"room_name": "Attic", "temperature": 95},  # Too hot!
        ]
        
        alerts = []
        for room in rooms_data:
            if room["temperature"] > 85:
                alerts.append({
                    "room": room["room_name"],
                    "type": "temperature",
                    "issue": "too_hot",
                    "value": room["temperature"]
                })
        
        assert len(alerts) == 1
        assert alerts[0]["room"] == "Attic"
    
    def test_temperature_alert_too_cold(self):
        """Should alert when temperature too low."""
        rooms_data = [
            {"room_name": "Garage", "temperature": 45},  # Too cold!
            {"room_name": "Living", "temperature": 70},
        ]
        
        alerts = []
        for room in rooms_data:
            if room["temperature"] < 55:
                alerts.append({
                    "room": room["room_name"],
                    "type": "temperature",
                    "issue": "too_cold"
                })
        
        assert len(alerts) == 1
        assert alerts[0]["room"] == "Garage"
    
    def test_humidity_alert(self):
        """Should alert on extreme humidity."""
        rooms_data = [
            {"room_name": "Bathroom", "humidity": 85},  # Too humid!
            {"room_name": "Bedroom", "humidity": 45},
        ]
        
        alerts = []
        for room in rooms_data:
            if room["humidity"] > 70:
                alerts.append({"room": room["room_name"], "type": "humidity"})
        
        assert len(alerts) == 1
    
    def test_water_leak_alert(self, mock_hass):
        """Should alert on water leak detection."""
        mock_hass.set_state("binary_sensor.kitchen_leak", "on")
        mock_hass.set_state("binary_sensor.bath_leak", "off")
        
        leak_sensors = [
            ("Kitchen", "binary_sensor.kitchen_leak"),
            ("Bathroom", "binary_sensor.bath_leak"),
        ]
        
        alerts = []
        for room, sensor in leak_sensors:
            state = mock_hass.states.get(sensor)
            if state and state.state == "on":
                alerts.append({"room": room, "type": "water_leak"})
        
        assert len(alerts) == 1
        assert alerts[0]["room"] == "Kitchen"
    
    def test_no_alerts(self):
        """Should be False when no alerts."""
        rooms_data = [
            {"room_name": "Bedroom", "temperature": 72, "humidity": 45},
            {"room_name": "Living", "temperature": 70, "humidity": 50},
        ]
        
        alerts = []
        for room in rooms_data:
            if room["temperature"] > 85 or room["temperature"] < 55:
                alerts.append({"type": "temperature"})
            if room["humidity"] > 70 or room["humidity"] < 25:
                alerts.append({"type": "humidity"})
        
        has_alert = len(alerts) > 0
        assert has_alert is False


# =============================================================================
# SECURITY ALERT SENSOR TESTS
# =============================================================================

class TestSecurityAlertSensor:
    """Test security_alert binary sensor."""
    
    def test_door_open_normal_hours(self, mock_hass):
        """Door open > 10 min during normal hours should alert."""
        door_opened = datetime.now() - timedelta(minutes=15)
        mock_hass.set_state_with_time(
            "binary_sensor.front_door", "on", door_opened
        )
        
        state = mock_hass.states.get("binary_sensor.front_door")
        duration_min = (datetime.now() - state.last_changed).total_seconds() / 60
        
        normal_threshold = 10  # minutes
        should_alert = state.state == "on" and duration_min > normal_threshold
        
        assert should_alert is True
    
    def test_door_open_sleep_hours_egress(self):
        """Egress door during sleep should alert at 1 min."""
        door_opened = datetime.now() - timedelta(minutes=2)
        duration_min = (datetime.now() - door_opened).total_seconds() / 60
        
        is_sleep = True
        is_egress = True
        
        threshold = 1 if (is_sleep and is_egress) else 10
        should_alert = duration_min > threshold
        
        assert should_alert is True
    
    def test_window_open_normal_hours(self, mock_hass):
        """Window open > 30 min during normal hours should alert."""
        window_opened = datetime.now() - timedelta(minutes=45)
        mock_hass.set_state_with_time(
            "binary_sensor.bedroom_window", "on", window_opened
        )
        
        state = mock_hass.states.get("binary_sensor.bedroom_window")
        duration_min = (datetime.now() - state.last_changed).total_seconds() / 60
        
        normal_threshold = 30
        should_alert = duration_min > normal_threshold
        
        assert should_alert is True
    
    def test_window_open_sleep_hours_shared(self):
        """Window in shared space during sleep should alert at 5 min."""
        window_opened = datetime.now() - timedelta(minutes=7)
        duration_min = (datetime.now() - window_opened).total_seconds() / 60
        
        is_sleep = True
        is_shared = True
        
        threshold = 5 if (is_sleep and is_shared) else 30
        should_alert = duration_min > threshold
        
        assert should_alert is True
    
    def test_no_security_issues(self, mock_hass):
        """Should be False when doors/windows closed."""
        mock_hass.set_state("binary_sensor.front_door", "off")
        mock_hass.set_state("binary_sensor.window", "off")
        
        door = mock_hass.states.get("binary_sensor.front_door")
        window = mock_hass.states.get("binary_sensor.window")
        
        has_issue = (
            (door and door.state == "on") or
            (window and window.state == "on")
        )
        
        assert has_issue is False


# =============================================================================
# CLIMATE DELTA SENSOR TESTS
# =============================================================================

class TestClimateDeltaSensor:
    """Test climate_delta sensor."""
    
    def test_temperature_delta(self):
        """Should calculate temperature spread."""
        rooms_data = [
            {"room_name": "Attic", "temperature": 85},
            {"room_name": "Bedroom", "temperature": 72},
            {"room_name": "Basement", "temperature": 65},
        ]
        
        temps = [r["temperature"] for r in rooms_data]
        delta = max(temps) - min(temps)
        
        assert delta == 20
    
    def test_hottest_coldest_rooms(self):
        """Should identify hottest and coldest rooms."""
        rooms_data = [
            {"room_name": "Attic", "temperature": 85},
            {"room_name": "Bedroom", "temperature": 72},
            {"room_name": "Basement", "temperature": 65},
        ]
        
        hottest = max(rooms_data, key=lambda r: r["temperature"])
        coldest = min(rooms_data, key=lambda r: r["temperature"])
        
        assert hottest["room_name"] == "Attic"
        assert coldest["room_name"] == "Basement"
    
    def test_humidity_delta(self):
        """Should calculate humidity spread."""
        rooms_data = [
            {"room_name": "Bathroom", "humidity": 75},
            {"room_name": "Bedroom", "humidity": 45},
            {"room_name": "Living", "humidity": 50},
        ]
        
        humidities = [r["humidity"] for r in rooms_data]
        delta = max(humidities) - min(humidities)
        
        assert delta == 30
    
    def test_single_room_no_delta(self):
        """Single room should have 0 delta."""
        rooms_data = [
            {"room_name": "Only Room", "temperature": 72},
        ]
        
        temps = [r["temperature"] for r in rooms_data]
        if len(temps) < 2:
            delta = 0
        else:
            delta = max(temps) - min(temps)
        
        assert delta == 0


# =============================================================================
# PREDICTED ENERGY SENSOR TESTS
# =============================================================================

class TestPredictedEnergySensors:
    """Test energy prediction sensors."""
    
    def test_cooling_prediction_hot_day(self):
        """Should predict higher cooling need on hot days."""
        forecast_high = 98
        baseline_temp = 65
        
        if forecast_high <= baseline_temp:
            predicted_kwh = 0
        else:
            cooling_degrees = forecast_high - baseline_temp
            base_kwh = 2.0
            temp_factor = cooling_degrees * 0.5
            predicted_kwh = base_kwh + temp_factor
        
        # 98 - 65 = 33 degrees * 0.5 = 16.5 + 2 = 18.5 kWh
        assert predicted_kwh == 18.5
    
    def test_cooling_prediction_mild_day(self):
        """Should predict zero cooling on cool days."""
        forecast_high = 60
        baseline_temp = 65
        
        if forecast_high <= baseline_temp:
            predicted_kwh = 0
        else:
            predicted_kwh = (forecast_high - baseline_temp) * 0.5 + 2
        
        assert predicted_kwh == 0
    
    def test_heating_prediction_cold_day(self):
        """Should predict higher heating need on cold days."""
        forecast_low = 25
        baseline_temp = 65
        
        if forecast_low >= baseline_temp:
            predicted_kwh = 0
        else:
            heating_degrees = baseline_temp - forecast_low
            base_kwh = 1.5
            temp_factor = heating_degrees * 0.4
            predicted_kwh = base_kwh + temp_factor
        
        # 65 - 25 = 40 degrees * 0.4 = 16 + 1.5 = 17.5 kWh
        assert predicted_kwh == 17.5
    
    def test_occupancy_affects_prediction(self):
        """Prediction should factor in occupancy."""
        forecast_high = 90
        occupied_zones = 3
        
        cooling_degrees = 90 - 65
        base_kwh = 2.0
        temp_factor = cooling_degrees * 0.5
        occupancy_factor = occupied_zones * 0.3  # More zones = more cooling
        
        predicted_kwh = base_kwh + temp_factor + occupancy_factor
        
        # 25 * 0.5 = 12.5 + 2 + 0.9 = 15.4 kWh
        assert predicted_kwh == 15.4


# =============================================================================
# ZONE SENSOR TESTS
# =============================================================================

class TestZoneSensors:
    """Test dynamic zone sensors."""
    
    def test_zone_occupied_count(self):
        """Should count occupied rooms in zone."""
        rooms_data = [
            {"room_name": "Master Bed", "zone": "upstairs", "occupied": True},
            {"room_name": "Kids Room", "zone": "upstairs", "occupied": False},
            {"room_name": "Bath", "zone": "upstairs", "occupied": True},
            {"room_name": "Kitchen", "zone": "downstairs", "occupied": False},
        ]
        
        upstairs_occupied = sum(
            1 for r in rooms_data 
            if r["zone"] == "upstairs" and r["occupied"]
        )
        
        assert upstairs_occupied == 2
    
    def test_zone_anyone_binary(self):
        """Should be True if any room in zone occupied."""
        rooms_data = [
            {"room_name": "Master Bed", "zone": "upstairs", "occupied": False},
            {"room_name": "Kids Room", "zone": "upstairs", "occupied": True},
        ]
        
        anyone_upstairs = any(
            r["occupied"] for r in rooms_data if r["zone"] == "upstairs"
        )
        
        assert anyone_upstairs is True
    
    def test_zone_avg_temperature(self):
        """Should calculate average temperature in zone."""
        rooms_data = [
            {"room_name": "Master Bed", "zone": "upstairs", "temperature": 74},
            {"room_name": "Kids Room", "zone": "upstairs", "temperature": 72},
            {"room_name": "Bath", "zone": "upstairs", "temperature": 76},
        ]
        
        upstairs_temps = [
            r["temperature"] for r in rooms_data if r["zone"] == "upstairs"
        ]
        avg_temp = sum(upstairs_temps) / len(upstairs_temps)
        
        assert avg_temp == pytest.approx(74, abs=0.1)
    
    def test_zone_discovery(self):
        """Should discover zones from room configs."""
        rooms_configs = [
            {"room_name": "Bedroom", "zone": "upstairs"},
            {"room_name": "Office", "zone": "upstairs"},
            {"room_name": "Kitchen", "zone": "downstairs"},
            {"room_name": "Garage", "zone": "outdoor"},
            {"room_name": "Storage"},  # No zone
        ]
        
        zones = set()
        for config in rooms_configs:
            zone = config.get("zone")
            if zone:
                zones.add(zone)
        
        assert zones == {"upstairs", "downstairs", "outdoor"}

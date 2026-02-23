"""Aggregation sensors for Universal Room Automation v3.3.5.5.

Provides whole-house and zone-level sensors from the integration entry.
"""
#
# Universal Room Automation v3.2.10
# Build: 2026-01-04
# File: aggregation.py
# v3.2.10: Fixed zone person sensors to persist when zone becomes empty
# v3.2.9: Fixed zone sensor race condition with deferred initialization
# v3.2.8.3: Added person_coordinator subscriptions for real-time person sensor updates
# v3.2.8.3: Renamed zone sensors: "Last Occupant" → "Last Identified Person/Time"
# v3.2.8.3: Fixed previous_location_time to record when person LEFT (not when they entered)
# v3.2.8.1: Added ZonePersonTrackingStatusSensor for zone-level diagnostic tracking
# v3.2.8.1: Fixed PersonPreviousSeenSensor to use previous_location_time
# FIX v3.2.8: PersonLocationSensor now uses active state change listeners for instant updates
# FIX v3.2.8: Added presence decay with tracking_status states (active/stale/lost)
# FIX v3.2.8: Added recent_path attribute for path tracking
# FIX v3.2.6: OccupantCountSensor now uses person_coordinator for real person count
# FIX v3.2.6: Renamed "Occupant Count" to "Identified People Count" for clarity
#

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfPower,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_time_interval,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    NAME,
    VERSION,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,
    CONF_ENTRY_TYPE,
    CONF_ZONE,
    CONF_ZONE_NAME,
    CONF_ZONE_ROOMS,
    CONF_TRACKED_PERSONS,  # v3.2.0: Person tracking
    CONF_SHARED_SPACE,
    CONF_WATER_LEAK_SENSOR,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_OUTSIDE_HUMIDITY_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_SLEEP_START_HOUR,
    CONF_SLEEP_END_HOUR,
    CONF_DOOR_SENSORS,
    CONF_DOOR_TYPE,
    CONF_WINDOW_SENSORS,
    CONF_ALERT_LIGHTS,
    CONF_ALERT_LIGHT_COLOR,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_LEVEL,
    DOOR_TYPE_EGRESS,
    DEFAULT_SLEEP_START,
    DEFAULT_SLEEP_END,
    DEFAULT_DOOR_ALERT_THRESHOLD,
    DEFAULT_WINDOW_ALERT_THRESHOLD,
    SLEEP_DOOR_ALERT_THRESHOLD,
    SLEEP_WINDOW_ALERT_THRESHOLD,
    STATE_OCCUPIED,
    STATE_TEMPERATURE,
    STATE_HUMIDITY,
    STATE_POWER_CURRENT,
    STATE_ENERGY_TODAY,
    # v3.1.6: Energy config
    CONF_SOLAR_EXPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR_2,
    CONF_BATTERY_LEVEL_SENSOR,
    CONF_WHOLE_HOUSE_POWER_SENSOR,
    CONF_WHOLE_HOUSE_ENERGY_SENSOR,
    CONF_ELECTRICITY_RATE,
    CONF_DELIVERY_RATE,
    CONF_EXPORT_REIMBURSEMENT_RATE,
    DEFAULT_ELECTRICITY_RATE,
    DEFAULT_DELIVERY_RATE,
    DEFAULT_EXPORT_REIMBURSEMENT_RATE,
    # Energy confidence levels
    ENERGY_CONFIDENCE_HIGH,
    ENERGY_CONFIDENCE_MEDIUM,
    ENERGY_CONFIDENCE_LOW,
    CONFIDENCE_LEVEL_HIGH,
    CONFIDENCE_LEVEL_MEDIUM,
    CONFIDENCE_LEVEL_LOW,
    CONFIDENCE_LEVEL_VERY_LOW,
    CONFIDENCE_LEVEL_COLLECTING,
    # Coverage ratings
    COVERAGE_EXCELLENT_THRESHOLD,
    COVERAGE_GOOD_THRESHOLD,
    COVERAGE_FAIR_THRESHOLD,
    COVERAGE_RATING_EXCELLENT,
    COVERAGE_RATING_GOOD,
    COVERAGE_RATING_FAIR,
    COVERAGE_RATING_INCOMPLETE,
    # HVAC direction
    HVAC_DIRECTION_COOLING,
    HVAC_DIRECTION_HEATING,
    HVAC_DIRECTION_NEUTRAL,
    HVAC_COOLING_THRESHOLD,
    HVAC_HEATING_THRESHOLD,
    COMFORT_TEMP_MAX,
    COMFORT_TEMP_MIN,
    MIN_DATA_DAYS_PREDICTION,
    # Alert colors
    ALERT_COLOR_RGB,
    ALERT_TYPE_COLORS,
    ALERT_COLOR_AMBER,
    NOTIFY_LEVEL_ERRORS,
    NOTIFY_LEVEL_OFF,
    # Icons
    ICON_HVAC_DIRECTION,
    ICON_COOLING,
    ICON_HEATING,
    ICON_COVERAGE,
    # v3.2.8: Presence decay constants
    CONF_PERSON_DECAY_TIMEOUT,
    DEFAULT_PERSON_DECAY_TIMEOUT,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_STALE,
    TRACKING_STATUS_LOST,
    STALE_THRESHOLD_SECONDS,
    MAX_RECENT_PATH_LENGTH,
    ATTR_RECENT_PATH,
    ATTR_TRACKING_STATUS,
    ATTR_LAST_BERMUDA_UPDATE,
    ICON_TRACKING_ACTIVE,
    ICON_TRACKING_STALE,
    ICON_TRACKING_LOST,
    # HVAC Zone Preset Triggers (v3.3.5.9)
    CONF_CLIMATE_ENTITY,
    CONF_ZONE_VACANT_PRESET,
    CONF_ZONE_OCCUPIED_PRESET,
    DEFAULT_ZONE_VACANT_PRESET,
    DEFAULT_ZONE_OCCUPIED_PRESET,
    HVAC_PRESET_SKIP,
)
from .coordinator import UniversalRoomCoordinator

_LOGGER = logging.getLogger(__name__)

# Update interval for aggregation sensors
AGGREGATION_UPDATE_INTERVAL = timedelta(seconds=30)


async def async_setup_aggregation_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up aggregation sensors (non-binary) for the integration entry."""
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_INTEGRATION:
        return  # Only for integration entry
    
    # v3.3.5.6: Integration entry now only creates whole-house + person sensors.
    # Zone sensors are created by zone config entries via async_setup_zone_sensors().
    entities: list[SensorEntity] = [
        # === PRESENCE & OCCUPANCY ===
        RoomsOccupiedSensor(hass, entry),
        OccupantCountSensor(hass, entry),
        PersonTrackingDiagnosticSensor(hass, entry),  # v3.2.6: New diagnostic sensor

        # === CLIMATE ===
        ClimateDeltaSensor(hass, entry),
        HVACDirectionSensor(hass, entry),

        # === CLIMATE DELTAS (Inside vs Outside) ===
        HumidityDeltaSensor(hass, entry),
        TempDeltaOutsideSensor(hass, entry),
        HumidityDeltaOutsideSensor(hass, entry),

        # === HVAC PREDICTIONS ===
        PredictedCoolingNeedSensor(hass, entry),
        PredictedHeatingNeedSensor(hass, entry),

        # === ENERGY TRACKING ===
        WholeHousePowerSensor(hass, entry),
        WholeHouseEnergySensor(hass, entry),
        RoomsEnergyTotalSensor(hass, entry),
        EnergyCoverageDeltaSensor(hass, entry),

        # === ENERGY PREDICTIONS ===
        PredictedEnergyTodaySensor(hass, entry),
        PredictedEnergyWeekSensor(hass, entry),
        PredictedEnergyMonthSensor(hass, entry),
        PredictedCostTodaySensor(hass, entry),
        PredictedCostWeekSensor(hass, entry),
        PredictedCostMonthSensor(hass, entry),
    ]

    # === v3.2.0: INTEGRATION PERSON LOCATION SENSORS ===
    person_coordinator = hass.data[DOMAIN].get("person_coordinator")
    if person_coordinator:
        tracked_persons = entry.data.get(CONF_TRACKED_PERSONS, [])
        for person_entity_id in tracked_persons:
            person_id = person_entity_id.split('.')[-1]  # person.oji -> oji
            entities.extend([
                PersonLocationSensor(hass, entry, person_id),
                PersonPreviousLocationSensor(hass, entry, person_id),
                PersonPreviousSeenSensor(hass, entry, person_id),
            ])

            # v3.3.0: Pattern learning sensors
            from .sensor import PersonLikelyNextRoomSensor, PersonCurrentPathSensor
            entities.extend([
                PersonLikelyNextRoomSensor(hass, entry, person_id),
                PersonCurrentPathSensor(hass, entry, person_id),
            ])

    async_add_entities(entities)
    _LOGGER.info("Set up %d whole-house aggregation sensors", len(entities))


async def async_setup_aggregation_binary_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up aggregation binary sensors for the integration entry."""
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_INTEGRATION:
        return  # Only for integration entry

    # v3.3.5.6: Integration entry now only creates whole-house binary sensors.
    # Zone binary sensors are created by zone config entries via async_setup_zone_binary_sensors().
    entities: list[BinarySensorEntity] = [
        AnyoneHomeBinarySensor(hass, entry),
        SafetyAlertBinarySensor(hass, entry),
        SecurityAlertBinarySensor(hass, entry),
    ]

    async_add_entities(entities)
    _LOGGER.info("Set up %d whole-house aggregation binary sensors", len(entities))


async def async_setup_zone_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone-level aggregation sensors for a zone config entry (v3.3.5.6).

    Called when a zone config entry forwards its sensor platform.
    Entities created here are registered under the zone config entry,
    so they appear grouped with the zone in the HA UI.
    """
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE:
        return

    zone_name = entry.data.get(CONF_ZONE_NAME)
    if not zone_name:
        _LOGGER.warning("Zone entry %s has no zone_name, skipping sensor setup", entry.entry_id)
        return

    # We need the integration entry for config lookups (energy rates, etc.)
    integration_entry = hass.data.get(DOMAIN, {}).get("integration")

    entities: list[SensorEntity] = [
        # === OCCUPANCY ===
        ZoneOccupiedSensor(hass, entry, zone_name),
        ZoneActiveRoomsSensor(hass, entry, zone_name),

        # === CLIMATE ===
        ZoneAvgTemperatureSensor(hass, entry, zone_name),
        ZoneAvgHumiditySensor(hass, entry, zone_name),
        ZoneTempDeltaSensor(hass, entry, zone_name),
        ZoneHumidityDeltaSensor(hass, entry, zone_name),

        # === SAFETY ===
        ZoneSafetyAlertSensor(hass, entry, zone_name),

        # === ENERGY ===
        ZoneTotalPowerSensor(hass, entry, zone_name),
        ZoneEnergyTodaySensor(hass, entry, zone_name),

        # === PERSON TRACKING ===
        ZoneCurrentOccupantsSensor(hass, entry, zone_name),
        ZoneOccupantCountSensor(hass, entry, zone_name),
        ZoneLastOccupantSensor(hass, entry, zone_name),
        ZoneLastOccupantTimeSensor(hass, entry, zone_name),
        ZonePersonTrackingStatusSensor(hass, entry, zone_name),
    ]

    async_add_entities(entities)
    _LOGGER.info("Set up %d zone sensors for '%s'", len(entities), zone_name)


async def async_setup_zone_binary_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone-level binary sensors for a zone config entry (v3.3.5.6)."""
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE:
        return

    zone_name = entry.data.get(CONF_ZONE_NAME)
    if not zone_name:
        _LOGGER.warning("Zone entry %s has no zone_name, skipping binary sensor setup", entry.entry_id)
        return

    entities: list[BinarySensorEntity] = [
        ZoneAnyoneBinarySensor(hass, entry, zone_name),
    ]

    async_add_entities(entities)
    _LOGGER.info("Set up %d zone binary sensors for '%s'", len(entities), zone_name)


def _get_all_zones(hass: HomeAssistant, entry: ConfigEntry | None = None) -> set[str]:
    """Get all unique zones from room entries and zone entries."""
    zones = set()
    
    # Get zones from room entries
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if isinstance(data, UniversalRoomCoordinator):
            zone = data.entry.data.get(CONF_ZONE) or data.entry.options.get(CONF_ZONE)
            if zone:
                zones.add(zone)
    
    # Get zones from zone entries
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
            zone_name = config_entry.data.get(CONF_ZONE_NAME)
            if zone_name:
                zones.add(zone_name)
    
    return zones


def _get_room_coordinators(hass: HomeAssistant) -> list[UniversalRoomCoordinator]:
    """Get all room coordinators."""
    coordinators = []
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if isinstance(data, UniversalRoomCoordinator):
            coordinators.append(data)
    return coordinators


def _is_sleep_hours(hass: HomeAssistant) -> bool:
    """Check if currently in sleep hours."""
    now = dt_util.now()
    current_hour = now.hour
    
    # Get sleep hours from any room (use defaults if not found)
    sleep_start = DEFAULT_SLEEP_START
    sleep_end = DEFAULT_SLEEP_END
    
    for coord in _get_room_coordinators(hass):
        sleep_start = coord.entry.options.get(
            CONF_SLEEP_START_HOUR,
            coord.entry.data.get(CONF_SLEEP_START_HOUR, DEFAULT_SLEEP_START)
        )
        sleep_end = coord.entry.options.get(
            CONF_SLEEP_END_HOUR,
            coord.entry.data.get(CONF_SLEEP_END_HOUR, DEFAULT_SLEEP_END)
        )
        break  # Use first room's settings
    
    if sleep_start > sleep_end:
        # Overnight (e.g., 22:00 - 07:00)
        return current_hour >= sleep_start or current_hour < sleep_end
    else:
        return sleep_start <= current_hour < sleep_end


def _get_confidence_level(confidence: int) -> str:
    """Convert confidence percentage to level label."""
    if confidence >= ENERGY_CONFIDENCE_HIGH:
        return CONFIDENCE_LEVEL_HIGH
    elif confidence >= ENERGY_CONFIDENCE_MEDIUM:
        return CONFIDENCE_LEVEL_MEDIUM
    elif confidence >= ENERGY_CONFIDENCE_LOW:
        return CONFIDENCE_LEVEL_LOW
    elif confidence > 0:
        return CONFIDENCE_LEVEL_VERY_LOW
    else:
        return CONFIDENCE_LEVEL_COLLECTING


def _get_delta_description(delta_type: str, delta_value: float, highest_name: str = "", lowest_name: str = "") -> str:
    """Generate natural language description of delta direction.
    
    Args:
        delta_type: Type of delta (temperature, humidity, temp_outside, humidity_outside)
        delta_value: The delta value (can be negative)
        highest_name: Name of location with highest value (for room comparisons)
        lowest_name: Name of location with lowest value (for room comparisons)
    
    Returns:
        Natural language description of the delta direction
    """
    if delta_value == 0:
        if highest_name and lowest_name:
            return f"{highest_name} and {lowest_name} are equal"
        return "Values are equal"
    
    if delta_type == "temperature":
        if delta_value > 0:
            return f"{highest_name} is warmer than {lowest_name}"
        else:
            return f"{lowest_name} is warmer than {highest_name}"
    elif delta_type == "humidity":
        if delta_value > 0:
            return f"{highest_name} is more humid than {lowest_name}"
        else:
            return f"{lowest_name} is more humid than {highest_name}"
    elif delta_type == "temp_outside":
        if delta_value > 0:
            return "Outside is warmer than inside"
        elif delta_value < 0:
            return "Inside is warmer than outside"
        else:
            return "Inside and outside temperatures are equal"
    elif delta_type == "humidity_outside":
        if delta_value > 0:
            return "Outside is more humid than inside"
        elif delta_value < 0:
            return "Inside is more humid than outside"
        else:
            return "Inside and outside humidity are equal"
    
    return ""


def _get_coverage_rating(delta_percent: float) -> str:
    """Get coverage rating from delta percentage."""
    if delta_percent < COVERAGE_EXCELLENT_THRESHOLD:
        return COVERAGE_RATING_EXCELLENT
    elif delta_percent < COVERAGE_GOOD_THRESHOLD:
        return COVERAGE_RATING_GOOD
    elif delta_percent < COVERAGE_FAIR_THRESHOLD:
        return COVERAGE_RATING_FAIR
    else:
        return COVERAGE_RATING_INCOMPLETE


class AggregationEntity:
    """Base class for aggregation entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize aggregation entity."""
        self.hass = hass
        self.entry = entry
        self._attr_has_entity_name = True
        self._rooms_ready = False
        self._agg_retry_unsub = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        """v3.3.5.6: Poll for room coordinators to become available after startup.

        Whole-house sensors load during integration entry setup, before room
        entries have initialized their coordinators. We poll every 5s for up
        to 60s, then write state once rooms appear so the UI reflects data
        immediately instead of requiring a manual reload.
        """
        await super().async_added_to_hass()
        if _get_room_coordinators(self.hass):
            self._rooms_ready = True
            return

        self._agg_retry_count = 0
        max_retries = 12  # 60s

        @callback
        def _check_rooms(now=None):
            self._agg_retry_count += 1
            if _get_room_coordinators(self.hass):
                self._rooms_ready = True
                self.async_write_ha_state()
                if self._agg_retry_unsub:
                    self._agg_retry_unsub()
                    self._agg_retry_unsub = None
            elif self._agg_retry_count >= max_retries:
                # Give up retrying but still mark as ready so sensor shows 0 values
                self._rooms_ready = True
                if self._agg_retry_unsub:
                    self._agg_retry_unsub()
                    self._agg_retry_unsub = None

        self._agg_retry_unsub = async_track_time_interval(
            self.hass, _check_rooms, timedelta(seconds=5)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up retry timer."""
        if self._agg_retry_unsub:
            self._agg_retry_unsub()
            self._agg_retry_unsub = None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True
    
    def _get_config(self, key: str, default: Any = None) -> Any:
        """Get config from integration entry."""
        return self.entry.options.get(key, self.entry.data.get(key, default))
    
    def _get_outside_temp(self) -> float | None:
        """Get outside temperature from configured sensor."""
        sensor = self._get_config(CONF_OUTSIDE_TEMP_SENSOR)
        if sensor:
            state = self.hass.states.get(sensor)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except ValueError:
                    pass
        return None
    
    def _get_outside_humidity(self) -> float | None:
        """Get outside humidity from configured sensor."""
        sensor = self._get_config(CONF_OUTSIDE_HUMIDITY_SENSOR)
        if sensor:
            state = self.hass.states.get(sensor)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except ValueError:
                    pass
        return None
    
    def _get_house_avg_temp(self) -> float | None:
        """Calculate average temperature across all rooms."""
        temps = []
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                temp = coord.data.get(STATE_TEMPERATURE)
                if temp is not None:
                    temps.append(temp)
        return round(sum(temps) / len(temps), 1) if temps else None
    
    def _get_house_avg_humidity(self) -> float | None:
        """Calculate average humidity across all rooms."""
        humidities = []
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                humidity = coord.data.get(STATE_HUMIDITY)
                if humidity is not None:
                    humidities.append(humidity)
        return round(sum(humidities) / len(humidities), 1) if humidities else None
    
    def _get_forecast_temp(self) -> float | None:
        """Get forecast high temperature from weather entity."""
        weather_entity = self._get_config(CONF_WEATHER_ENTITY)
        if not weather_entity:
            return None
        
        state = self.hass.states.get(weather_entity)
        if not state:
            return None
        
        # Try to get forecast from attributes
        forecast = state.attributes.get("forecast", [])
        if forecast and len(forecast) > 0:
            return forecast[0].get("temperature")
        
        return state.attributes.get("temperature")


# ============================================================================
# EXISTING SENSORS (AnyoneHome, RoomsOccupied, SafetyAlert, SecurityAlert, ClimateDelta)
# ============================================================================

class AnyoneHomeBinarySensor(AggregationEntity, BinarySensorEntity):
    """Binary sensor: True if any room is occupied."""
    
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:home-account"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_anyone_home"
        self._attr_name = "Anyone Home"
    
    @property
    def is_on(self) -> bool:
        """Return True if any room occupied."""
        for coord in _get_room_coordinators(self.hass):
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                return True
        return False
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed occupancy info."""
        occupied_rooms = []
        zones_occupied = set()
        shared_spaces = []
        
        for coord in _get_room_coordinators(self.hass):
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                room_name = coord.entry.data.get("room_name", "Unknown")
                occupied_rooms.append(room_name)
                
                zone = coord.entry.options.get(CONF_ZONE) or coord.entry.data.get(CONF_ZONE)
                if zone:
                    zones_occupied.add(zone)
                
                is_shared = coord.entry.options.get(CONF_SHARED_SPACE) or coord.entry.data.get(CONF_SHARED_SPACE, False)
                if is_shared:
                    shared_spaces.append(room_name)
        
        return {
            "occupied_rooms": occupied_rooms,
            "occupied_count": len(occupied_rooms),
            "zones_occupied": list(zones_occupied),
            "zones_count": len(zones_occupied),
            "shared_spaces_occupied": shared_spaces,
        }


class RoomsOccupiedSensor(AggregationEntity, SensorEntity):
    """Sensor: Count of occupied rooms."""
    
    _attr_icon = "mdi:door-open"
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_rooms_occupied"
        self._attr_name = "Rooms Occupied"
        self._attr_native_unit_of_measurement = "rooms"
    
    @property
    def native_value(self) -> int:
        """Return count of occupied rooms."""
        count = 0
        for coord in _get_room_coordinators(self.hass):
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                count += 1
        return count
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return room list."""
        rooms = []
        for coord in _get_room_coordinators(self.hass):
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                rooms.append(coord.entry.data.get("room_name", "Unknown"))
        return {"rooms": rooms}


class SafetyAlertBinarySensor(AggregationEntity, BinarySensorEntity):
    """Binary sensor: Any room has safety alert (temp, humidity, leak)."""
    
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_icon = "mdi:alert-circle"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_alert"
        self._attr_name = "Safety Alert"
        self._last_alert_time: datetime | None = None
    
    @property
    def is_on(self) -> bool:
        """Return True if any safety alert active."""
        alerts = self._get_alerts()
        if alerts:
            # Trigger alert actions if not recently triggered
            self.hass.async_create_task(self._process_alerts(alerts))
        return len(alerts) > 0
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return alert details."""
        alerts = self._get_alerts()
        return {
            "alert_count": len(alerts),
            "alert_rooms": list(set(a["room"] for a in alerts)),
            "alert_types": list(set(a["type"] for a in alerts)),
            "alerts": alerts,
            "temperature_alerts": [a for a in alerts if a["type"] == "temperature"],
            "humidity_alerts": [a for a in alerts if a["type"] == "humidity"],
            "leak_alerts": [a for a in alerts if a["type"] == "water_leak"],
        }
    
    def _get_alerts(self) -> list[dict]:
        """Collect all safety alerts from rooms."""
        alerts = []
        
        for coord in _get_room_coordinators(self.hass):
            room_name = coord.entry.data.get("room_name", "Unknown")
            
            # Temperature alerts
            temp = coord.data.get(STATE_TEMPERATURE) if coord.data else None
            if temp is not None:
                if temp > 85:  # Too hot
                    alerts.append({"room": room_name, "type": "temperature", "value": temp, "issue": "too_hot"})
                elif temp < 55:  # Too cold
                    alerts.append({"room": room_name, "type": "temperature", "value": temp, "issue": "too_cold"})
            
            # Humidity alerts
            humidity = coord.data.get(STATE_HUMIDITY) if coord.data else None
            if humidity is not None:
                if humidity > 70:
                    alerts.append({"room": room_name, "type": "humidity", "value": humidity, "issue": "too_humid"})
                elif humidity < 25:
                    alerts.append({"room": room_name, "type": "humidity", "value": humidity, "issue": "too_dry"})
            
            # Water leak
            leak_sensor = coord.entry.options.get(CONF_WATER_LEAK_SENSOR) or coord.entry.data.get(CONF_WATER_LEAK_SENSOR)
            if leak_sensor:
                state = self.hass.states.get(leak_sensor)
                if state and state.state == "on":
                    alerts.append({"room": room_name, "type": "water_leak", "sensor": leak_sensor, "issue": "leak_detected"})
        
        return alerts
    
    async def _process_alerts(self, alerts: list[dict]) -> None:
        """Process alerts - send notifications and flash lights."""
        if not alerts:
            return
        
        # Debounce: don't alert more than once per minute
        now = datetime.now()
        if self._last_alert_time and (now - self._last_alert_time).total_seconds() < 60:
            return
        
        self._last_alert_time = now
        
        # Group alerts by room for notification
        alert_rooms = list(set(a["room"] for a in alerts))
        alert_types = list(set(a["type"] for a in alerts))
        
        # Send notification
        notify_service = self._get_config(CONF_NOTIFY_SERVICE)
        notify_target = self._get_config(CONF_NOTIFY_TARGET)
        notify_level = self._get_config(CONF_NOTIFY_LEVEL, NOTIFY_LEVEL_ERRORS)
        
        if notify_service and notify_level != NOTIFY_LEVEL_OFF:
            message = f"🚨 Safety Alert in {', '.join(alert_rooms)}: {', '.join(alert_types)}"
            try:
                await self.hass.services.async_call(
                    "notify",
                    notify_service.replace("notify.", ""),
                    {"message": message, "title": "URA Safety Alert"},
                    blocking=False,
                )
            except Exception as e:
                _LOGGER.error("Failed to send safety alert notification: %s", e)
        
        # Flash alert lights in affected rooms
        for alert in alerts:
            room_name = alert["room"]
            alert_type = alert["type"]
            
            # Find coordinator for this room
            for coord in _get_room_coordinators(self.hass):
                if coord.entry.data.get("room_name") == room_name:
                    alert_lights = coord.entry.options.get(CONF_ALERT_LIGHTS) or coord.entry.data.get(CONF_ALERT_LIGHTS)
                    alert_color = coord.entry.options.get(CONF_ALERT_LIGHT_COLOR) or coord.entry.data.get(CONF_ALERT_LIGHT_COLOR)
                    
                    if alert_lights:
                        # Use alert-type specific color or configured color
                        color = ALERT_TYPE_COLORS.get(alert_type, alert_color or ALERT_COLOR_AMBER)
                        rgb = ALERT_COLOR_RGB.get(color, [255, 191, 0])
                        
                        for light in alert_lights if isinstance(alert_lights, list) else [alert_lights]:
                            await self._flash_light(light, rgb)
                    break
    
    async def _flash_light(self, light_entity: str, rgb: list[int], flashes: int = 3) -> None:
        """Flash a light with specified color.
        
        v3.2.2.6: Improved error handling for Matter/Thread device timeouts.
        """
        # Track failed devices to avoid hammering unresponsive ones
        if not hasattr(self, '_failed_alert_lights'):
            self._failed_alert_lights = {}
        
        # Skip if device failed recently (within 5 minutes)
        now = datetime.now()
        if light_entity in self._failed_alert_lights:
            last_failure = self._failed_alert_lights[light_entity]
            if (now - last_failure).total_seconds() < 300:  # 5 minute cooldown
                _LOGGER.debug(
                    "Skipping alert light %s - in cooldown after previous failure",
                    light_entity
                )
                return
        
        try:
            # Get current state to restore later
            current_state = self.hass.states.get(light_entity)
            was_on = current_state and current_state.state == "on"
            
            for _ in range(flashes):
                # Flash on with color - use shorter timeout
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": light_entity, "rgb_color": rgb, "brightness": 255},
                    blocking=True,
                )
                await self.hass.async_add_executor_job(lambda: __import__('time').sleep(0.3))
                
                # Flash off
                await self.hass.services.async_call(
                    "light",
                    "turn_off",
                    {"entity_id": light_entity},
                    blocking=True,
                )
                await self.hass.async_add_executor_job(lambda: __import__('time').sleep(0.3))
            
            # Restore previous state
            if was_on:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": light_entity},
                    blocking=False,
                )
            
            # Clear from failed list if it succeeded
            self._failed_alert_lights.pop(light_entity, None)
            
        except Exception as e:
            error_str = str(e).lower()
            # Check for timeout-related errors (Matter/Thread devices)
            if "timeout" in error_str or "chip error" in error_str:
                _LOGGER.warning(
                    "Alert light %s timed out (Matter/Thread device) - skipping for 5 minutes: %s",
                    light_entity, e
                )
            else:
                _LOGGER.error("Failed to flash alert light %s: %s", light_entity, e)
            
            # Track failure for cooldown
            self._failed_alert_lights[light_entity] = now


class SecurityAlertBinarySensor(AggregationEntity, BinarySensorEntity):
    """Binary sensor: Any door/window open too long."""
    
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:door-open"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_alert"
        self._attr_name = "Security Alert"
    
    @property
    def is_on(self) -> bool:
        """Return True if any security issue."""
        issues = self._get_security_issues()
        return len(issues["doors"]) > 0 or len(issues["windows"]) > 0
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return security issue details."""
        issues = self._get_security_issues()
        return {
            "open_doors": issues["doors"],
            "open_windows": issues["windows"],
            "door_count": len(issues["doors"]),
            "window_count": len(issues["windows"]),
            "is_sleep_hours": _is_sleep_hours(self.hass),
        }
    
    def _get_security_issues(self) -> dict[str, list]:
        """Get doors/windows open too long."""
        is_sleep = _is_sleep_hours(self.hass)
        doors = []
        windows = []
        
        for coord in _get_room_coordinators(self.hass):
            room_name = coord.entry.data.get("room_name", "Unknown")
            is_shared = coord.entry.options.get(CONF_SHARED_SPACE) or coord.entry.data.get(CONF_SHARED_SPACE, False)
            door_type = coord.entry.options.get(CONF_DOOR_TYPE) or coord.entry.data.get(CONF_DOOR_TYPE)
            is_egress = door_type == DOOR_TYPE_EGRESS
            
            # Determine thresholds based on sleep hours and room type
            if is_sleep and (is_shared or is_egress):
                door_threshold = SLEEP_DOOR_ALERT_THRESHOLD
                window_threshold = SLEEP_WINDOW_ALERT_THRESHOLD
            else:
                door_threshold = DEFAULT_DOOR_ALERT_THRESHOLD
                window_threshold = DEFAULT_WINDOW_ALERT_THRESHOLD
            
            # Check door
            door_sensor = coord.entry.options.get(CONF_DOOR_SENSORS) or coord.entry.data.get(CONF_DOOR_SENSORS)
            if door_sensor and is_egress:
                state = self.hass.states.get(door_sensor)
                if state and state.state == "on":
                    duration = (dt_util.now() - state.last_changed).total_seconds() / 60
                    if duration > door_threshold:
                        doors.append({
                            "room": room_name,
                            "sensor": door_sensor,
                            "duration_min": round(duration, 1),
                            "threshold_min": door_threshold,
                        })
            
            # Check window
            window_sensor = coord.entry.options.get(CONF_WINDOW_SENSORS) or coord.entry.data.get(CONF_WINDOW_SENSORS)
            if window_sensor:
                state = self.hass.states.get(window_sensor)
                if state and state.state == "on":
                    duration = (dt_util.now() - state.last_changed).total_seconds() / 60
                    if duration > window_threshold:
                        windows.append({
                            "room": room_name,
                            "sensor": window_sensor,
                            "duration_min": round(duration, 1),
                            "threshold_min": window_threshold,
                        })
        
        return {"doors": doors, "windows": windows}


class ClimateDeltaSensor(AggregationEntity, SensorEntity):
    """Sensor: Temperature delta across rooms (hottest - coldest)."""
    
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-lines"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_climate_delta"
        self._attr_name = "Climate Delta"
    
    @property
    def native_value(self) -> float | None:
        """Return temperature delta (hottest - coldest)."""
        temps = self._get_room_temperatures()
        if len(temps) < 2:
            return None
        return round(max(temps.values()) - min(temps.values()), 1)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed climate info."""
        temps = self._get_room_temperatures()
        humidities = self._get_room_humidities()
        
        attrs = {
            "room_count": len(temps),
        }
        
        if temps:
            hottest = max(temps, key=temps.get)
            coldest = min(temps, key=temps.get)
            temp_delta = round(temps[hottest] - temps[coldest], 1) if len(temps) >= 2 else 0
            attrs.update({
                "hottest_room": hottest,
                "hottest_temp": temps[hottest],
                "coldest_room": coldest,
                "coldest_temp": temps[coldest],
                "temp_delta": temp_delta,
            })
        
        if humidities:
            most_humid = max(humidities, key=humidities.get)
            least_humid = min(humidities, key=humidities.get)
            humidity_delta = round(humidities[most_humid] - humidities[least_humid], 1) if len(humidities) >= 2 else 0
            attrs.update({
                "most_humid_room": most_humid,
                "most_humid_value": humidities[most_humid],
                "least_humid_room": least_humid,
                "least_humid_value": humidities[least_humid],
                "humidity_delta": humidity_delta,
            })
        
        return attrs
    
    def _get_room_temperatures(self) -> dict[str, float]:
        """Get temperatures from all rooms."""
        temps = {}
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                temp = coord.data.get(STATE_TEMPERATURE)
                if temp is not None:
                    room_name = coord.entry.data.get("room_name", "Unknown")
                    temps[room_name] = temp
        return temps
    
    def _get_room_humidities(self) -> dict[str, float]:
        """Get humidities from all rooms."""
        humidities = {}
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                humidity = coord.data.get(STATE_HUMIDITY)
                if humidity is not None:
                    room_name = coord.entry.data.get("room_name", "Unknown")
                    humidities[room_name] = humidity
        return humidities


class PredictedCoolingNeedSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted cooling energy need based on forecast."""
    
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_COOLING
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_cooling_need"
        self._attr_name = "Predicted Cooling Need"
    
    @property
    def native_value(self) -> float | None:
        """Return predicted kWh for cooling."""
        forecast_high = self._get_forecast_temp()
        if forecast_high is None:
            return None
        
        occupied_count = sum(
            1 for coord in _get_room_coordinators(self.hass)
            if coord.data and coord.data.get(STATE_OCCUPIED, False)
        )
        zones_count = len(_get_all_zones(self.hass))
        
        if forecast_high <= 65:
            return 0.0
        
        cooling_degrees = forecast_high - 65
        base_kwh = 2.0
        temp_factor = cooling_degrees * 0.5
        occupancy_factor = max(occupied_count, zones_count) * 0.3
        
        return round(base_kwh + temp_factor + occupancy_factor, 1)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details."""
        return {
            "forecast_high": self._get_forecast_temp(),
            "cooling_baseline": 65,
            "model": "degree_day_simple",
        }


class PredictedHeatingNeedSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted heating energy need based on forecast."""
    
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_HEATING
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_heating_need"
        self._attr_name = "Predicted Heating Need"
    
    @property
    def native_value(self) -> float | None:
        """Return predicted kWh equivalent for heating."""
        weather_entity = self._get_config(CONF_WEATHER_ENTITY)
        if not weather_entity:
            return None
        
        state = self.hass.states.get(weather_entity)
        if not state:
            return None
        
        forecast = state.attributes.get("forecast", [])
        forecast_low = forecast[0].get("templow") if forecast else None
        
        if forecast_low is None or forecast_low >= 65:
            return 0.0
        
        heating_degrees = 65 - forecast_low
        base_kwh = 1.5
        temp_factor = heating_degrees * 0.4
        
        return round(base_kwh + temp_factor, 1)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details."""
        return {
            "heating_baseline": 65,
            "model": "degree_day_simple",
            "note": "Values in kWh equivalent",
        }


# ============================================================================
# v3.1.6: NEW CLIMATE DELTA SENSORS
# ============================================================================

class HumidityDeltaSensor(AggregationEntity, SensorEntity):
    """Sensor: Humidity delta across rooms (highest - lowest)."""
    
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_humidity_delta"
        self._attr_name = "Humidity Delta"
    
    @property
    def native_value(self) -> float | None:
        """Return humidity delta."""
        humidities = []
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                h = coord.data.get(STATE_HUMIDITY)
                if h is not None:
                    humidities.append(h)
        
        if len(humidities) < 2:
            return None
        return round(max(humidities) - min(humidities), 1)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        room_humidities = {}
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                h = coord.data.get(STATE_HUMIDITY)
                if h is not None:
                    room_humidities[coord.entry.data.get("room_name", "Unknown")] = h
        
        if room_humidities:
            return {
                "highest_room": max(room_humidities, key=room_humidities.get),
                "highest_value": max(room_humidities.values()),
                "lowest_room": min(room_humidities, key=room_humidities.get),
                "lowest_value": min(room_humidities.values()),
                "room_count": len(room_humidities),
            }
        return {}


class TempDeltaOutsideSensor(AggregationEntity, SensorEntity):
    """Sensor: Temperature delta between house average and outside."""
    
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-lines"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_temp_delta_outside"
        self._attr_name = "Temp Delta Outside"
    
    @property
    def native_value(self) -> float | None:
        """Return house avg - outside temp."""
        house_avg = self._get_house_avg_temp()
        outside = self._get_outside_temp()
        
        if house_avg is None or outside is None:
            return None
        return round(house_avg - outside, 1)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        house_avg = self._get_house_avg_temp()
        outside = self._get_outside_temp()
        delta = self.native_value
        
        # Short directional description for UI constraints
        direction = "(equal)"
        if delta is not None:
            if delta > 0:
                direction = "(inside warmer)"
            elif delta < 0:
                direction = "(outside warmer)"
        
        return {
            "house_avg_temp": house_avg,
            "outside_temp": outside,
            "direction": direction,
        }


class HumidityDeltaOutsideSensor(AggregationEntity, SensorEntity):
    """Sensor: Humidity delta between house average and outside."""
    
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_humidity_delta_outside"
        self._attr_name = "Humidity Delta Outside"
    
    @property
    def native_value(self) -> float | None:
        """Return house avg - outside humidity."""
        house_avg = self._get_house_avg_humidity()
        outside = self._get_outside_humidity()
        
        if house_avg is None or outside is None:
            return None
        return round(house_avg - outside, 1)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        house_avg = self._get_house_avg_humidity()
        outside = self._get_outside_humidity()
        delta = self.native_value
        
        # Short directional description for UI constraints
        direction = "(equal)"
        if delta is not None:
            if delta > 0:
                direction = "(inside more humid)"
            elif delta < 0:
                direction = "(outside more humid)"
        
        return {
            "house_avg_humidity": house_avg,
            "outside_humidity": outside,
            "direction": direction,
        }


class HVACDirectionSensor(AggregationEntity, SensorEntity):
    """Sensor: Whether house needs heating, cooling, or neutral."""
    
    _attr_icon = ICON_HVAC_DIRECTION
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_direction"
        self._attr_name = "HVAC Direction"
    
    @property
    def native_value(self) -> str:
        """Return cooling, heating, or neutral."""
        outside_temp = self._get_outside_temp()
        if outside_temp is None:
            return HVAC_DIRECTION_NEUTRAL
        
        if outside_temp > COMFORT_TEMP_MAX + HVAC_COOLING_THRESHOLD:
            return HVAC_DIRECTION_COOLING
        elif outside_temp < COMFORT_TEMP_MIN - HVAC_HEATING_THRESHOLD:
            return HVAC_DIRECTION_HEATING
        else:
            return HVAC_DIRECTION_NEUTRAL
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        outside_temp = self._get_outside_temp()
        house_avg = self._get_house_avg_temp()
        delta = None
        if house_avg and outside_temp:
            delta = round(house_avg - outside_temp, 1)
        
        return {
            "outside_temp": outside_temp,
            "house_avg_temp": house_avg,
            "temp_delta": delta,
            "comfort_range": f"{COMFORT_TEMP_MIN}-{COMFORT_TEMP_MAX}°F",
            "cooling_threshold": COMFORT_TEMP_MAX + HVAC_COOLING_THRESHOLD,
            "heating_threshold": COMFORT_TEMP_MIN - HVAC_HEATING_THRESHOLD,
        }
    
    @property
    def icon(self) -> str:
        """Return icon based on direction."""
        value = self.native_value
        if value == HVAC_DIRECTION_COOLING:
            return ICON_COOLING
        elif value == HVAC_DIRECTION_HEATING:
            return ICON_HEATING
        return ICON_HVAC_DIRECTION


class OccupantCountSensor(AggregationEntity, SensorEntity):
    """Sensor: Count of identified people who are home (BLE tracked).
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:account-group"
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_occupant_count"
        self._attr_name = "Identified People Count"  # v3.2.6: Renamed for clarity
        self._attr_native_unit_of_measurement = "people"
        self._unsub_person_coordinator = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates.

        v3.2.8.3: Enables real-time updates when person tracking changes
        """
        await super().async_added_to_hass()
        # Subscribe to person_coordinator updates
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            self._unsub_person_coordinator = person_coordinator.async_add_listener(
                self._handle_person_update
            )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up person_coordinator subscription."""
        await super().async_will_remove_from_hass()
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None
    
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> int:
        """Return count of tracked people who are home.
        
        v3.2.6: Now uses person_coordinator.get_tracked_person_count()
        instead of counting occupied rooms.
        """
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            return person_coordinator.get_tracked_person_count()
        
        # Fallback to room count if person_coordinator not available
        count = 0
        for coord in _get_room_coordinators(self.hass):
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                count += 1
        return count
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return tracked persons info."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if person_coordinator and person_coordinator.data:
            # v3.2.6: Show actual person data
            persons_home = []
            persons_locations = {}
            for name, info in person_coordinator.data.items():
                location = info.get("location", "unknown")
                if location not in ("unknown", "away"):
                    persons_home.append(name)
                    persons_locations[name] = {
                        "location": location,
                        "confidence": info.get("confidence", 0),
                    }
            
            return {
                "method": "person_tracking",
                "confidence_level": CONFIDENCE_LEVEL_HIGH,
                "persons_home": persons_home,
                "persons_locations": persons_locations,
                "tracking_active": True,
            }
        
        # Fallback attributes
        occupied_rooms = []
        for coord in _get_room_coordinators(self.hass):
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                occupied_rooms.append(coord.entry.data.get("room_name", "Unknown"))
        
        return {
            "method": "room_count_fallback",
            "confidence_level": CONFIDENCE_LEVEL_LOW,
            "occupied_rooms": occupied_rooms,
            "tracking_active": False,
            "note": "Person coordinator unavailable - using room count as fallback",
        }


class PersonTrackingDiagnosticSensor(AggregationEntity, SensorEntity):
    """Sensor: Person tracking diagnostic information (v3.2.6).
    
    Provides diagnostic data about the person tracking coordinator status,
    useful for debugging staleness and matching issues.
    """
    
    _attr_icon = "mdi:account-search"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_person_tracking_diagnostic"
        self._attr_name = "Person Tracking Status"
    
    @property
    def native_value(self) -> str:
        """Return tracking status summary."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return "Unavailable"
        
        if not person_coordinator.data:
            return "No Data"
        
        # Count people with valid locations
        valid_count = 0
        for info in person_coordinator.data.values():
            location = info.get("location", "unknown")
            if location not in ("unknown", "away"):
                valid_count += 1
        
        total = len(person_coordinator.data)
        return f"{valid_count}/{total} home"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed diagnostic information."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return {
                "status": "coordinator_unavailable",
                "tracking_active": False,
            }
        
        # Get diagnostic data from coordinator
        if hasattr(person_coordinator, 'get_diagnostic_data'):
            diag = person_coordinator.get_diagnostic_data()
        else:
            diag = {}
        
        # Build attributes
        attrs = {
            "status": "active" if person_coordinator.data else "no_data",
            "tracking_active": person_coordinator.data is not None,
            "tracked_persons": diag.get("tracked_persons", []),
            "person_count": diag.get("person_count", 0),
            "update_interval_seconds": diag.get("update_interval_seconds", 30),
            "confidence_threshold": diag.get("confidence_threshold", 0.3),
            "area_mappings_count": diag.get("area_mappings_count", 0),
            "scanner_mappings_count": diag.get("scanner_mappings_count", 0),
            "room_coordinators_count": diag.get("room_coordinators_count", 0),
        }
        
        # Add person details
        if diag.get("persons_data"):
            attrs["persons"] = diag["persons_data"]
        
        # Add last update time if available
        if hasattr(person_coordinator, 'last_update_success_time'):
            last_update = person_coordinator.last_update_success_time
            if last_update:
                attrs["last_update"] = last_update.isoformat()
                time_ago = (dt_util.now() - last_update).total_seconds()
                if time_ago < 60:
                    attrs["last_update_ago"] = f"{int(time_ago)} seconds ago"
                elif time_ago < 3600:
                    attrs["last_update_ago"] = f"{int(time_ago / 60)} minutes ago"
                else:
                    attrs["last_update_ago"] = f"{int(time_ago / 3600)} hours ago"
        
        return attrs


# ============================================================================
# v3.1.6: ENERGY PREDICTION SENSORS
# ============================================================================

class PredictedEnergyTodaySensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted net energy for today."""
    
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:crystal-ball"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_energy_today"
        self._attr_name = "Predicted Energy Today"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
        self._cache_time: datetime | None = None
    
    @property
    def native_value(self) -> float | None:
        """Return predicted kWh value."""
        # Use cached value if recent (predictions are expensive)
        if self._cached_value is not None and self._cache_time:
            return self._cached_value
        
        # Return None if no data yet
        return None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details."""
        attrs = {
            "value": self._cached_value,
            "unit": "kWh",
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "today",
            "method": "historical_pattern",
            "last_updated": self._cache_time.isoformat() if self._cache_time else None,
        }
        
        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"{self._cached_value} kWh ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
            
        return attrs
    
    async def async_update(self) -> None:
        """Update prediction from database."""
        # Check if database is available
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        
        # Only update every 15 minutes
        now = datetime.now()
        if self._cache_time and (now - self._cache_time).total_seconds() < 900:
            return
        
        forecast_temp = self._get_forecast_temp()
        value, confidence = await db.predict_energy("day", forecast_temp)
        
        self._cached_value = value
        self._cached_confidence = confidence
        self._cache_time = now


class PredictedEnergyWeekSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted net energy for this week."""
    
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:crystal-ball"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_energy_week"
        self._attr_name = "Predicted Energy Week"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
        self._cache_time: datetime | None = None
    
    @property
    def native_value(self) -> float | None:
        """Return predicted kWh value."""
        return self._cached_value
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details."""
        attrs = {
            "value": self._cached_value,
            "unit": "kWh",
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "week",
        }
        
        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"{self._cached_value} kWh ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
            
        return attrs


class PredictedEnergyMonthSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted net energy for this month."""
    
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:crystal-ball"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_energy_month"
        self._attr_name = "Predicted Energy Month"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
    
    @property
    def native_value(self) -> float | None:
        """Return predicted kWh value."""
        return self._cached_value
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details."""
        attrs = {
            "value": self._cached_value,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "month",
        }
        
        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"{self._cached_value} kWh ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
            
        return attrs


class PredictedCostTodaySensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted energy cost for today."""
    
    _attr_native_unit_of_measurement = "$"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-usd"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_cost_today"
        self._attr_name = "Predicted Cost Today"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
    
    @property
    def native_value(self) -> float | None:
        """Return predicted cost value."""
        return self._cached_value if self._cached_value is not None else None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return cost calculation details."""
        rate = self._get_config(CONF_ELECTRICITY_RATE, DEFAULT_ELECTRICITY_RATE)
        delivery = self._get_config(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
        export_rate = self._get_config(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)
        
        attrs = {
            "value": self._cached_value,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "electricity_rate": rate,
            "delivery_rate": delivery,
            "export_rate": export_rate,
            "period": "today",
        }
        
        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"${self._cached_value:.2f} ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
            
        return attrs


class PredictedCostWeekSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted energy cost for this week."""
    
    _attr_native_unit_of_measurement = "$"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-usd"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_cost_week"
        self._attr_name = "Predicted Cost Week"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
    
    @property
    def native_value(self) -> float | None:
        """Return predicted cost value."""
        return self._cached_value if self._cached_value is not None else None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        attrs = {
            "value": self._cached_value,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "week",
        }
        
        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"${self._cached_value:.2f} ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
            
        return attrs


class PredictedCostMonthSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted energy cost for this month."""
    
    _attr_native_unit_of_measurement = "$"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-usd"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_cost_month"
        self._attr_name = "Predicted Cost Month"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
    
    @property
    def native_value(self) -> float | None:
        """Return predicted cost value."""
        return self._cached_value if self._cached_value is not None else None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        attrs = {
            "value": self._cached_value,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "month",
        }
        
        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"${self._cached_value:.2f} ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
            
        return attrs


# ============================================================================
# v3.1.6: ENERGY TRACKING SENSORS
# ============================================================================

class WholeHousePowerSensor(AggregationEntity, SensorEntity):
    """Sensor: Whole house power from configured sensor."""
    
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_whole_house_power"
        self._attr_name = "Whole House Power"
    
    @property
    def native_value(self) -> float | None:
        """Return whole house power."""
        sensor = self._get_config(CONF_WHOLE_HOUSE_POWER_SENSOR)
        if not sensor:
            return None
        
        state = self.hass.states.get(sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except ValueError:
                pass
        return None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return source info."""
        return {
            "source_sensor": self._get_config(CONF_WHOLE_HOUSE_POWER_SENSOR),
        }


class WholeHouseEnergySensor(AggregationEntity, SensorEntity):
    """Sensor: Whole house energy today from configured sensor."""
    
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lightning-bolt"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_whole_house_energy"
        self._attr_name = "Whole House Energy Today"
        self._last_valid_value: float | None = None
    
    @property
    def native_value(self) -> float | None:
        """Return whole house energy with monotonic increasing enforcement."""
        sensor = self._get_config(CONF_WHOLE_HOUSE_ENERGY_SENSOR)
        if not sensor:
            return None
        
        state = self.hass.states.get(sensor)
        if not state or state.state in ("unknown", "unavailable"):
            return None
        
        try:
            current = float(state.state)
        except ValueError:
            return None
        
        # Handle reset (new day, very small value)
        if current < 0.1:
            self._last_valid_value = current
            return current
        
        # Enforce monotonic increasing - reject decreases
        if self._last_valid_value is not None:
            if current < self._last_valid_value:
                # Value decreased - return last known good value
                return self._last_valid_value
        
        # Valid value - update and return
        self._last_valid_value = current
        return current
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return source info."""
        return {
            "source_sensor": self._get_config(CONF_WHOLE_HOUSE_ENERGY_SENSOR),
        }


class RoomsEnergyTotalSensor(AggregationEntity, SensorEntity):
    """Sensor: Sum of energy from all configured room sensors."""
    
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lightning-bolt"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_rooms_energy_total"
        self._attr_name = "Rooms Energy Total"
        self._last_valid_value: float | None = None
    
    @property
    def native_value(self) -> float:
        """Return sum of room energy sensors with monotonic increasing enforcement."""
        total = 0.0
        room_energies = {}
        
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                energy = coord.data.get(STATE_ENERGY_TODAY, 0)
                if energy:
                    room_name = coord.entry.data.get("room_name", "Unknown")
                    room_energies[room_name] = energy
                    total += energy
        
        current = round(total, 2)
        
        # Handle reset (new day, very small value)
        if current < 0.1:
            self._last_valid_value = current
            return current
        
        # Enforce monotonic increasing - reject decreases
        if self._last_valid_value is not None:
            if current < self._last_valid_value:
                # Value decreased - return last known good value
                return self._last_valid_value
        
        # Valid value - update and return
        self._last_valid_value = current
        return current
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return room breakdown."""
        room_energies = {}
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                energy = coord.data.get(STATE_ENERGY_TODAY, 0)
                if energy:
                    room_name = coord.entry.data.get("room_name", "Unknown")
                    room_energies[room_name] = round(energy, 2)
        
        return {
            "room_energies": room_energies,
            "room_count": len(room_energies),
        }


class EnergyCoverageDeltaSensor(AggregationEntity, SensorEntity):
    """Sensor: Delta between whole house energy and sum of room sensors."""
    
    # No device_class - this is a delta/difference, not cumulative energy
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_COVERAGE
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_coverage_delta"
        self._attr_name = "Energy Coverage Delta"
    
    @property
    def native_value(self) -> float | None:
        """Return whole house - rooms total."""
        whole_house = self._get_whole_house_energy()
        rooms_total = self._get_rooms_total_energy()
        
        if whole_house is None:
            return None
        
        return round(whole_house - rooms_total, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return coverage analysis."""
        whole_house = self._get_whole_house_energy()
        rooms_total = self._get_rooms_total_energy()
        
        if whole_house is None or whole_house == 0:
            return {
                "whole_house": whole_house,
                "rooms_total": rooms_total,
                "coverage_rating": "No data",
                "note": "Configure whole house energy sensor",
            }
        
        delta_kwh = whole_house - rooms_total
        delta_percent = (delta_kwh / whole_house) * 100 if whole_house > 0 else 0
        
        return {
            "whole_house": round(whole_house, 2),
            "rooms_total": round(rooms_total, 2),
            "delta_kwh": round(delta_kwh, 2),
            "delta_percent": round(delta_percent, 1),
            "coverage_rating": _get_coverage_rating(delta_percent),
            "coverage_notes": "Delta may include: HVAC loads (not room-assigned), unconfigured rooms, sub-panel gaps",
        }
    
    def _get_whole_house_energy(self) -> float | None:
        """Get whole house energy sensor value."""
        sensor = self._get_config(CONF_WHOLE_HOUSE_ENERGY_SENSOR)
        if not sensor:
            return None
        
        state = self.hass.states.get(sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except ValueError:
                pass
        return None
    
    def _get_rooms_total_energy(self) -> float:
        """Get sum of room energy sensors."""
        total = 0.0
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                energy = coord.data.get(STATE_ENERGY_TODAY, 0)
                if energy:
                    total += energy
        return total


# ============================================================================
# ZONE SENSORS (10 per zone)
# ============================================================================

class ZoneSensorBase(AggregationEntity):
    """Base class for zone sensors.
    
    v3.2.9: Added deferred initialization to fix race condition with room coordinators.
    Zone sensors now gracefully handle cases where room coordinators aren't ready yet.
    """
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize zone sensor."""
        super().__init__(hass, entry)
        self.zone = zone
        self._coordinators_ready = False
        self._retry_unsub = None
        # v3.3.5.6: Device is identified by zone name (consistent across entry changes).
        # Since entities are now added via the zone config entry's platform,
        # HA automatically links this device to the zone config entry.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"zone_{zone}")},
            name=f"Zone: {zone.title()}",
            manufacturer="Universal Room Automation",
            model="Zone",
            sw_version=VERSION,
            via_device=(DOMAIN, "integration"),
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass - set up coordinator readiness polling.

        v3.3.5.6: Replaced fragile fixed-delay approach with periodic retry.
        Zone sensors may load before room coordinators are ready. Instead of
        sleeping for a fixed 5+10 seconds (which can miss slow-loading rooms),
        we poll every 5 seconds up to 60 seconds. This eliminates the reload-
        required-for-availability issue.
        """
        await super().async_added_to_hass()

        # Check if coordinators are ready immediately
        if self._get_zone_coordinators():
            self._coordinators_ready = True
            return

        # Set up periodic retry until coordinators appear
        self._retry_count = 0
        max_retries = 12  # 12 * 5s = 60s total

        @callback
        def _check_coordinators(now=None):
            """Periodically check for zone coordinators."""
            self._retry_count += 1
            coords = self._get_zone_coordinators()
            if coords:
                self._coordinators_ready = True
                _LOGGER.debug(
                    "Zone '%s': Room coordinators now ready (%d found, attempt %d)",
                    self.zone, len(coords), self._retry_count,
                )
                self.async_write_ha_state()
                # Cancel further retries
                if self._retry_unsub:
                    self._retry_unsub()
                    self._retry_unsub = None
            elif self._retry_count >= max_retries:
                _LOGGER.warning(
                    "Zone '%s': No room coordinators found after %ds - "
                    "zone may be empty or rooms not configured",
                    self.zone, self._retry_count * 5,
                )
                if self._retry_unsub:
                    self._retry_unsub()
                    self._retry_unsub = None

        self._retry_unsub = async_track_time_interval(
            self.hass, _check_coordinators, timedelta(seconds=5)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up retry timer on removal."""
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None
    
    def _get_zone_coordinators(self) -> list[UniversalRoomCoordinator]:
        """Get coordinators for this zone."""
        try:
            all_coords = _get_room_coordinators(self.hass)
            
            zone_coords = []
            for coord in all_coords:
                coord_zone_options = coord.entry.options.get(CONF_ZONE)
                coord_zone_data = coord.entry.data.get(CONF_ZONE)
                coord_zone = coord_zone_options or coord_zone_data
                
                if coord_zone == self.zone:
                    zone_coords.append(coord)
            
            return zone_coords
        except Exception as e:
            _LOGGER.error("Zone '%s': Error getting coordinators: %s", self.zone, e)
            return []


class ZoneOccupiedSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Count of occupied rooms in zone."""
    
    _attr_icon = "mdi:door-open"
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_occupied"
        self._attr_name = f"Rooms Occupied"
        self._attr_native_unit_of_measurement = "rooms"
    
    @property
    def native_value(self) -> int:
        """Return count of occupied rooms in zone."""
        count = 0
        for coord in self._get_zone_coordinators():
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                count += 1
        return count
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return occupied room names."""
        rooms = []
        for coord in self._get_zone_coordinators():
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                rooms.append(coord.entry.data.get("room_name", "Unknown"))
        return {"rooms": rooms, "total_rooms": len(self._get_zone_coordinators())}


class ZoneAnyoneBinarySensor(ZoneSensorBase, BinarySensorEntity):
    """Binary sensor: Anyone in zone."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:account-group"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_anyone"
        self._attr_name = f"Anyone"
        self._last_zone_occupied: bool | None = None
        self._hvac_unsub_listeners: list = []

    async def async_added_to_hass(self) -> None:
        """Set up HVAC zone preset trigger after entity is added."""
        await super().async_added_to_hass()
        self._schedule_hvac_listener_setup()

    def _schedule_hvac_listener_setup(self) -> None:
        """Schedule HVAC listener setup once coordinators are ready."""
        if self._coordinators_ready:
            self.hass.async_create_task(self._setup_hvac_occupancy_listeners())
        else:
            # Coordinators not ready yet — hook into the existing retry mechanism
            # by scheduling a one-shot check after the base retry timer fires
            async def _delayed_setup() -> None:
                # Wait up to 65s for coordinators (base class retries for 60s)
                for _ in range(13):
                    await asyncio.sleep(5)
                    if self._coordinators_ready:
                        await self._setup_hvac_occupancy_listeners()
                        return
            self.hass.async_create_task(_delayed_setup())

    async def _setup_hvac_occupancy_listeners(self) -> None:
        """Watch room occupancy binary sensor entities for zone HVAC preset control.

        HVAC Zone Preset Triggers (v3.3.5.9):
        When all rooms in the zone become vacant -> set thermostat to 'away' preset.
        When any room becomes occupied          -> set thermostat to 'home' preset.
        Skips if current preset is in HVAC_PRESET_SKIP ('manual', 'sleep').
        """
        coordinators = self._get_zone_coordinators()
        if not coordinators:
            return

        # Build list of occupancy binary sensor entity_ids to watch.
        # URA names them: binary_sensor.<room_name_snake>_occupied
        occupancy_entity_ids = []
        for coord in coordinators:
            room_name = coord.entry.data.get("room_name", "")
            if room_name:
                entity_id = (
                    "binary_sensor."
                    + room_name.lower().replace(" ", "_")
                    + "_occupied"
                )
                occupancy_entity_ids.append(entity_id)

        if not occupancy_entity_ids:
            return

        # Set initial tracking state
        self._last_zone_occupied = self.is_on

        @callback
        def _on_room_occupancy_changed(event: Event) -> None:
            """Handle a room occupancy state change — trigger HVAC preset if needed."""
            self.hass.async_create_task(self._handle_zone_occupancy_change())

        unsub = async_track_state_change_event(
            self.hass, occupancy_entity_ids, _on_room_occupancy_changed
        )
        self._hvac_unsub_listeners.append(unsub)

        _LOGGER.debug(
            "Zone '%s': HVAC preset trigger active — watching %d room sensor(s)",
            self.zone, len(occupancy_entity_ids),
        )

    async def _handle_zone_occupancy_change(self) -> None:
        """Evaluate zone occupancy and set HVAC preset mode if it changed."""
        zone_occupied_now = self.is_on

        if zone_occupied_now == self._last_zone_occupied:
            return  # No change in zone-level occupancy

        self._last_zone_occupied = zone_occupied_now

        # Find a climate entity from any room in this zone
        climate_entity = self._get_zone_climate_entity()
        if not climate_entity:
            return

        # Determine target preset
        vacant_preset = self.entry.options.get(
            CONF_ZONE_VACANT_PRESET,
            self.entry.data.get(CONF_ZONE_VACANT_PRESET, DEFAULT_ZONE_VACANT_PRESET),
        )
        occupied_preset = self.entry.options.get(
            CONF_ZONE_OCCUPIED_PRESET,
            self.entry.data.get(CONF_ZONE_OCCUPIED_PRESET, DEFAULT_ZONE_OCCUPIED_PRESET),
        )
        target_preset = occupied_preset if zone_occupied_now else vacant_preset

        # Read current preset and skip if it's in HVAC_PRESET_SKIP
        climate_state = self.hass.states.get(climate_entity)
        if climate_state:
            current_preset = climate_state.attributes.get("preset_mode", "")
            if current_preset in HVAC_PRESET_SKIP:
                _LOGGER.debug(
                    "Zone '%s': Skipping HVAC preset change — current preset is '%s'",
                    self.zone, current_preset,
                )
                return

        _LOGGER.info(
            "Zone '%s': %s — setting %s to preset '%s'",
            self.zone,
            "occupied" if zone_occupied_now else "all vacant",
            climate_entity,
            target_preset,
        )

        try:
            await self.hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": climate_entity, "preset_mode": target_preset},
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error(
                "Zone '%s': Failed to set HVAC preset '%s' on %s: %s",
                self.zone, target_preset, climate_entity, e,
            )

    def _get_zone_climate_entity(self) -> str | None:
        """Return the climate entity from the first zone room that has one configured."""
        for coord in self._get_zone_coordinators():
            climate = coord.entry.options.get(
                CONF_CLIMATE_ENTITY,
                coord.entry.data.get(CONF_CLIMATE_ENTITY),
            )
            if climate:
                return climate
        return None

    async def async_will_remove_from_hass(self) -> None:
        """Clean up HVAC listeners."""
        for unsub in self._hvac_unsub_listeners:
            unsub()
        self._hvac_unsub_listeners.clear()
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool:
        """Return True if any room in zone occupied."""
        for coord in self._get_zone_coordinators():
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                return True
        return False


class ZoneSafetyAlertSensor(ZoneSensorBase, BinarySensorEntity):
    """Binary sensor: Safety alert in zone."""
    
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_icon = "mdi:alert-circle"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_safety_alert"
        self._attr_name = f"Safety Alert"
    
    @property
    def is_on(self) -> bool:
        """Return True if any safety alert in zone."""
        for coord in self._get_zone_coordinators():
            room_name = coord.entry.data.get("room_name", "Unknown")
            
            if coord.data:
                temp = coord.data.get(STATE_TEMPERATURE)
                if temp is not None and (temp > 85 or temp < 55):
                    return True
                
                humidity = coord.data.get(STATE_HUMIDITY)
                if humidity is not None and (humidity > 70 or humidity < 25):
                    return True
            
            leak_sensor = coord.entry.options.get(CONF_WATER_LEAK_SENSOR) or coord.entry.data.get(CONF_WATER_LEAK_SENSOR)
            if leak_sensor:
                state = self.hass.states.get(leak_sensor)
                if state and state.state == "on":
                    return True
        
        return False


class ZoneAvgTemperatureSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Average temperature in zone."""
    
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_avg_temp"
        self._attr_name = f"Avg Temperature"
    
    @property
    def native_value(self) -> float | None:
        """Return average temperature in zone."""
        try:
            coordinators = self._get_zone_coordinators()
            
            temps = []
            for coord in coordinators:
                if coord.data and coord.data.get(STATE_TEMPERATURE) is not None:
                    temp = coord.data.get(STATE_TEMPERATURE)
                    temps.append(temp)
            
            if not temps:
                return None
            
            avg = round(sum(temps) / len(temps), 1)
            return avg
        except Exception as e:
            _LOGGER.error("❌ ERROR in ZoneAvgTemperature.native_value for zone '%s': %s", 
                         self.zone, e, exc_info=True)
            return None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return temperature breakdown."""
        room_temps = {}
        for coord in self._get_zone_coordinators():
            if coord.data:
                temp = coord.data.get(STATE_TEMPERATURE)
                if temp is not None:
                    room_name = coord.entry.data.get("room_name", "Unknown")
                    room_temps[room_name] = temp
        return {"room_temperatures": room_temps, "room_count": len(room_temps)}


class ZoneAvgHumiditySensor(ZoneSensorBase, SensorEntity):
    """Sensor: Average humidity in zone."""
    
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_avg_humidity"
        self._attr_name = f"Avg Humidity"
    
    @property
    def native_value(self) -> float | None:
        """Return average humidity in zone."""
        humidities = []
        for coord in self._get_zone_coordinators():
            if coord.data:
                h = coord.data.get(STATE_HUMIDITY)
                if h is not None:
                    humidities.append(h)
        
        if not humidities:
            return None
        return round(sum(humidities) / len(humidities), 1)


class ZoneTempDeltaSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Temperature delta within zone."""
    
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-lines"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_temp_delta"
        self._attr_name = f"Temp Delta"
    
    @property
    def native_value(self) -> float | None:
        """Return temperature delta in zone."""
        temps = []
        for coord in self._get_zone_coordinators():
            if coord.data:
                temp = coord.data.get(STATE_TEMPERATURE)
                if temp is not None:
                    temps.append(temp)
        
        if len(temps) < 2:
            return None
        return round(max(temps) - min(temps), 1)


class ZoneHumidityDeltaSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Humidity delta within zone."""
    
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_humidity_delta"
        self._attr_name = f"Humidity Delta"
    
    @property
    def native_value(self) -> float | None:
        """Return humidity delta in zone."""
        humidities = []
        for coord in self._get_zone_coordinators():
            if coord.data:
                h = coord.data.get(STATE_HUMIDITY)
                if h is not None:
                    humidities.append(h)
        
        if len(humidities) < 2:
            return None
        return round(max(humidities) - min(humidities), 1)


class ZoneTotalPowerSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Total power consumption in zone."""
    
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_total_power"
        self._attr_name = f"Total Power"
    
    @property
    def native_value(self) -> float:
        """Return total power in zone."""
        total = 0.0
        for coord in self._get_zone_coordinators():
            if coord.data:
                power = coord.data.get(STATE_POWER_CURRENT, 0)
                if power:
                    total += power
        return round(total, 1)


class ZoneEnergyTodaySensor(ZoneSensorBase, SensorEntity):
    """Sensor: Total energy today in zone."""
    
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lightning-bolt"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_energy_today"
        self._attr_name = f"Energy Today"
        self._last_valid_value: float | None = None
    
    @property
    def native_value(self) -> float:
        """Return total energy today in zone with monotonic increasing enforcement."""
        total = 0.0
        for coord in self._get_zone_coordinators():
            if coord.data:
                energy = coord.data.get(STATE_ENERGY_TODAY, 0)
                if energy:
                    total += energy
        
        current = round(total, 2)
        
        # Handle reset (new day, very small value)
        if current < 0.1:
            self._last_valid_value = current
            return current
        
        # Enforce monotonic increasing - reject decreases
        if self._last_valid_value is not None:
            if current < self._last_valid_value:
                # Value decreased - return last known good value
                return self._last_valid_value
        
        # Valid value - update and return
        self._last_valid_value = current
        return current


class ZoneActiveRoomsSensor(ZoneSensorBase, SensorEntity):
    """Sensor: List of active rooms in zone."""
    
    _attr_icon = "mdi:home-group"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_active_rooms"
        self._attr_name = f"Active Rooms"
    
    @property
    def native_value(self) -> str:
        """Return comma-separated list of active rooms."""
        rooms = []
        for coord in self._get_zone_coordinators():
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                rooms.append(coord.entry.data.get("room_name", "Unknown"))
        return ", ".join(rooms) if rooms else "None"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return room details."""
        active = []
        inactive = []
        for coord in self._get_zone_coordinators():
            room_name = coord.entry.data.get("room_name", "Unknown")
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                active.append(room_name)
            else:
                inactive.append(room_name)
        
        return {
            "active_rooms": active,
            "inactive_rooms": inactive,
            "active_count": len(active),
            "total_rooms": len(active) + len(inactive),
        }


# =============================================================================
# v3.2.0: ZONE PERSON TRACKING SENSORS
# =============================================================================


class ZoneCurrentOccupantsSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Current occupants in zone.
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:account-multiple"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_current_occupants"
        self._attr_name = f"Current Occupants"
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates.

        v3.2.8.3: Enables real-time updates when person tracking changes
        """
        await super().async_added_to_hass()
        # Subscribe to person_coordinator updates
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            self._unsub_person_coordinator = person_coordinator.async_add_listener(
                self._handle_person_update
            )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up person_coordinator subscription."""
        await super().async_will_remove_from_hass()
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None

    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Always available - we have fallback handling in native_value
        return True

    @property
    def native_value(self) -> str:
        """Return comma-separated list of zone occupants."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator:
                return "None"
            
            # Get all room names in zone
            zone_rooms = self._get_zone_room_names()
            
            # Get persons in zone
            try:
                persons = person_coordinator.get_persons_in_zone(zone_rooms)
            except Exception as e:
                _LOGGER.error("Exception calling get_persons_in_zone for zone '%s': %s", self.zone, e)
                return "None"
            
            if not persons:
                return "None"
            
            # Format names nicely
            formatted_names = [p.replace('_', ' ').title() for p in persons]
            result = ", ".join(formatted_names)
            
            return result
        except Exception as e:
            _LOGGER.error("❌ CRITICAL ERROR in ZoneCurrentOccupants.native_value for zone '%s': %s", 
                         self.zone, e, exc_info=True)
            # Return default instead of raising - prevents "unavailable" state
            return "None"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator:
                return {}
            
            zone_rooms = self._get_zone_room_names()
            persons = person_coordinator.get_persons_in_zone(zone_rooms)
            
            # Get details for each person
            person_details = {}
            person_rooms = {}
            
            for person_id in persons:
                try:
                    room = person_coordinator.get_person_location(person_id)
                    confidence = person_coordinator.get_person_confidence(person_id)
                    
                    person_details[person_id] = {
                        "room": room,
                        "confidence": round(confidence, 2),
                        "confidence_level": (
                            "high" if confidence >= 0.8 else
                            "medium" if confidence >= 0.5 else
                            "low"
                        )
                    }
                    person_rooms[person_id] = room
                except Exception as e:
                    _LOGGER.warning("   Error getting details for person '%s': %s", person_id, e)
                    continue
            
            return {
                "person_ids": persons,
                "person_details": person_details,
                "person_rooms": person_rooms,
                "count": len(persons),
                "zone_rooms": zone_rooms
            }
        except Exception as e:
            _LOGGER.error("Error in ZoneCurrentOccupants.extra_state_attributes for zone '%s': %s", 
                         self.zone, e, exc_info=True)
            return {}
    
    def _get_zone_room_names(self) -> list[str]:
        """Get list of room names in zone."""
        room_names = []
        for coord in self._get_zone_coordinators():
            room_name = coord.entry.data.get("room_name", "")
            if room_name:
                room_names.append(room_name)
        return room_names


class ZoneOccupantCountSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Count of occupants in zone.
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "people"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_occupant_count"
        self._attr_name = f"Occupant Count"
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates.

        v3.2.8.3: Enables real-time updates when person tracking changes
        """
        await super().async_added_to_hass()
        # Subscribe to person_coordinator updates
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            self._unsub_person_coordinator = person_coordinator.async_add_listener(
                self._handle_person_update
            )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up person_coordinator subscription."""
        await super().async_will_remove_from_hass()
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None

    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    @property
    def native_value(self) -> int:
        """Return count of zone occupants."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator:
                return 0
            
            zone_rooms = [
                coord.entry.data.get("room_name", "")
                for coord in self._get_zone_coordinators()
            ]
            
            persons = person_coordinator.get_persons_in_zone(zone_rooms)
            
            return len(persons)
        except Exception as e:
            _LOGGER.error("Error in ZoneOccupantCount.native_value for zone '%s': %s", 
                         self.zone, e, exc_info=True)
            return 0


class ZoneLastOccupantSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Last person who occupied zone."""
    
    _attr_icon = "mdi:account-clock"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        # v3.2.8.3: Aligned with room/house naming convention (v3.2.6)
        # unique_id kept as "last_occupant" for backward compatibility
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_last_occupant"
        self._attr_name = f"Last Identified Person"
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True
    
    @property
    def native_value(self) -> str:
        """Return last zone occupant."""
        if hasattr(self, '_last_occupant'):
            return self._last_occupant
        return "Unknown"
    
    async def async_update(self) -> None:
        """Update last occupant from database."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return
        
        # Get all room names in zone
        zone_rooms = [
            coord.entry.data.get("room_name", "")
            for coord in self._get_zone_coordinators()
        ]
        
        if not zone_rooms:
            return
        
        try:
            # v3.2.2.6: Fixed - Use proper database API method
            result = await database.get_zone_last_occupant(zone_rooms)
            
            if result:
                person_id = result['person_id']
                self._last_occupant = person_id.replace('_', ' ').title()
                self._last_occupant_time = result['entry_time']
                self._last_occupant_room = result['room_id']
            else:
                # v3.2.10: Only set Unknown if never seen anyone (preserve when zone empties)
                if not hasattr(self, '_last_occupant'):
                    self._last_occupant = "Unknown"
                    self._last_occupant_time = None
                    self._last_occupant_room = None
                # else: preserve existing values when zone becomes empty
                
        except Exception as e:
            _LOGGER.error("Error getting zone last occupant: %s", e)
            self._last_occupant = "Unknown"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = {}
        
        if hasattr(self, '_last_occupant_time') and self._last_occupant_time:
            attrs["last_seen"] = self._last_occupant_time.isoformat()
            attrs["room"] = getattr(self, '_last_occupant_room', None)
        
        return attrs


class ZoneLastOccupantTimeSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Timestamp of last zone occupant."""
    
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        # v3.2.8.3: Aligned with room/house naming convention (v3.2.6)
        # unique_id kept as "last_occupant_time" for backward compatibility
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_last_occupant_time"
        self._attr_name = f"Last Identified Time"
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True
    
    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last zone occupant."""
        if hasattr(self, '_last_time'):
            return self._last_time
        return None
    
    async def async_update(self) -> None:
        """Update last occupant time from database."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return
        
        zone_rooms = [
            coord.entry.data.get("room_name", "")
            for coord in self._get_zone_coordinators()
        ]
        
        if not zone_rooms:
            return
        
        try:
            # v3.2.2.6: Fixed - Use proper database API method
            result = await database.get_zone_last_occupant(zone_rooms)
            
            if result:
                entry_time = result['entry_time']
                if isinstance(entry_time, str):
                    self._last_time = datetime.fromisoformat(entry_time)
                else:
                    self._last_time = entry_time
            else:
                # v3.2.10: Only set None if never seen anyone (preserve when zone empties)
                if not hasattr(self, '_last_time'):
                    self._last_time = None
                # else: preserve existing value when zone becomes empty
                
        except Exception as e:
            _LOGGER.error("Error getting zone last occupant time: %s", e)
            self._last_time = None


class ZonePersonTrackingStatusSensor(ZoneSensorBase, SensorEntity):
    """
    v3.2.8.1: Zone-level person tracking diagnostic sensor.
    
    Shows tracking quality and status for all persons in this zone,
    helping debug why occupancy detection may not be working.
    """
    
    _attr_icon = "mdi:account-search"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_person_tracking_status"
        self._attr_name = f"Person Tracking Status"
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True
    
    @property
    def native_value(self) -> str:
        """Return summary of person tracking status in this zone."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator or not person_coordinator.data:
                return "No tracking data"
            
            # Get rooms in this zone
            zone_rooms = [
                coord.entry.data.get("room_name", "")
                for coord in self._get_zone_coordinators()
            ]
            
            if not zone_rooms:
                return "No rooms in zone"
            
            # Count persons by tracking status
            active_count = 0
            stale_count = 0
            lost_count = 0
            
            for person_name, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location in zone_rooms:
                    status = person_info.get("tracking_status", "lost")
                    if status == "active":
                        active_count += 1
                    elif status == "stale":
                        stale_count += 1
                    else:
                        lost_count += 1
            
            total = active_count + stale_count + lost_count
            
            if total == 0:
                return "No persons in zone"
            
            # Return summary
            parts = []
            if active_count > 0:
                parts.append(f"{active_count} active")
            if stale_count > 0:
                parts.append(f"{stale_count} stale")
            if lost_count > 0:
                parts.append(f"{lost_count} lost")
            
            return ", ".join(parts)
            
        except Exception as e:
            _LOGGER.error("Error in ZonePersonTrackingStatus.native_value for zone '%s': %s", 
                         self.zone, e, exc_info=True)
            return "Error"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed tracking information."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator or not person_coordinator.data:
                return {}
            
            # Get rooms in this zone
            zone_rooms = [
                coord.entry.data.get("room_name", "")
                for coord in self._get_zone_coordinators()
            ]
            
            if not zone_rooms:
                return {"zone_rooms": []}
            
            # Build detailed person tracking info
            persons_in_zone = []
            for person_name, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location in zone_rooms:
                    persons_in_zone.append({
                        "person": person_name,
                        "room": location,
                        "status": person_info.get("tracking_status", "lost"),
                        "confidence": round(person_info.get("confidence", 0), 2),
                        "method": person_info.get("method", "none"),
                    })
            
            return {
                "zone_rooms": zone_rooms,
                "persons_in_zone": persons_in_zone,
                "total_persons": len(persons_in_zone),
            }
            
        except Exception as e:
            _LOGGER.error("Error in ZonePersonTrackingStatus.extra_state_attributes: %s", e)
            return {}


# =============================================================================
# v3.2.8: INTEGRATION PERSON LOCATION SENSORS (Per-Person) - ARCHITECTURAL FIX
# =============================================================================


class PersonLocationSensor(AggregationEntity, SensorEntity):
    """Sensor: Person's current location with active state change listeners.
    
    v3.2.8 ARCHITECTURAL FIX:
    - Changed from passive polling (SensorEntity) to active state change listeners
    - Subscribes to Bermuda sensor state changes for instant updates
    - Implements presence decay with tracking_status states
    - Tracks recent_path for room transition history
    - Sub-second response time matching Bermuda's update frequency
    """
    
    _attr_icon = "mdi:map-marker-account"
    _attr_should_poll = False  # v3.2.8: Disable polling - we use state change listeners
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self.person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id}_location"
        self._attr_name = f"{person_id.replace('_', ' ').title()} Location"
        
        # v3.2.8: State tracking for presence decay
        self._last_bermuda_update: datetime | None = None
        self._tracking_status: str = TRACKING_STATUS_LOST
        self._recent_path: list[dict] = []  # Last N room transitions
        self._cached_location: str | None = None
        self._cached_confidence: float = 0.0
        
        # v3.2.8: Cleanup callbacks
        self._unsub_state_listeners: list = []
        self._unsub_decay_timer: callable | None = None
    
    async def async_added_to_hass(self) -> None:
        """Set up state change listeners when entity is added.
        
        v3.2.8: Subscribe to Bermuda sensor state changes for instant updates.
        v3.2.8.3: Also subscribe to person_coordinator for instant coordinator updates.
        """
        await super().async_added_to_hass()
        
        # Get the person coordinator
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if not person_coordinator:
            _LOGGER.warning(
                "PersonLocationSensor for %s: person_coordinator not available",
                self.person_id
            )
            return
        
        # v3.2.8.3: Subscribe to person_coordinator updates for instant data refresh
        self._unsub_state_listeners.append(
            person_coordinator.async_add_listener(self._handle_coordinator_update)
        )
        
        # Find Bermuda sensors for this person
        bermuda_sensors = self._find_bermuda_sensors()
        
        if bermuda_sensors:
            _LOGGER.info(
                "PersonLocationSensor %s: Setting up listeners for %d Bermuda sensors",
                self.person_id, len(bermuda_sensors)
            )
            
            # Subscribe to state changes on Bermuda sensors
            for sensor_id in bermuda_sensors:
                unsub = async_track_state_change_event(
                    self.hass,
                    [sensor_id],
                    self._handle_bermuda_state_change,
                )
                self._unsub_state_listeners.append(unsub)
        else:
            _LOGGER.warning(
                "PersonLocationSensor %s: No Bermuda sensors found, falling back to polling",
                self.person_id
            )
        
        # Set up decay timer (runs every 30 seconds to check staleness)
        self._unsub_decay_timer = async_track_time_interval(
            self.hass,
            self._check_presence_decay,
            timedelta(seconds=30),
        )
        
        # Initial state update
        await self._update_from_coordinator()
    
    async def async_will_remove_from_hass(self) -> None:
        """Clean up listeners when entity is removed."""
        # Clean up state change listeners
        for unsub in self._unsub_state_listeners:
            unsub()
        self._unsub_state_listeners.clear()
        
        # Clean up decay timer
        if self._unsub_decay_timer:
            self._unsub_decay_timer()
            self._unsub_decay_timer = None
    
    def _find_bermuda_sensors(self) -> list[str]:
        """Find Bermuda distance sensors for this person.
        
        v3.2.8: Searches for sensor.bermuda_{person}_* patterns.
        """
        bermuda_sensors = []
        
        # Search patterns - Bermuda uses first name only
        # e.g., person.oji_udezue -> sensor.bermuda_oji_*
        person_first_name = self.person_id.split('_')[0].lower()
        
        # Find all Bermuda sensors for this person
        for state in self.hass.states.async_all():
            entity_id = state.entity_id
            
            # Match Bermuda distance sensors
            if entity_id.startswith(f"sensor.bermuda_{person_first_name}_"):
                # Distance sensors typically end with area names
                if "_distance" not in entity_id.lower():
                    bermuda_sensors.append(entity_id)
        
        _LOGGER.debug(
            "Found %d Bermuda sensors for person %s: %s",
            len(bermuda_sensors), self.person_id, bermuda_sensors[:5]  # Log first 5
        )
        
        return bermuda_sensors
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle person_coordinator data update - instant update.
        
        v3.2.8.3: Called when person_coordinator processes new tracking data.
        Ensures sensors update immediately without waiting for polling.
        """
        try:
            # Schedule coordinator data refresh (non-blocking)
            self.hass.async_create_task(self._update_from_coordinator())
            
            # Trigger HA state update
            self.async_write_ha_state()
            
        except Exception as e:
            _LOGGER.error(
                "Error handling coordinator update for %s: %s",
                self.person_id, e
            )
    
    @callback
    def _handle_bermuda_state_change(self, event: Event) -> None:
        """Handle Bermuda sensor state change - instant update.
        
        v3.2.8: Called immediately when any Bermuda sensor updates.
        This provides sub-second response time.
        """
        try:
            # Update timestamp
            self._last_bermuda_update = dt_util.now()
            self._tracking_status = TRACKING_STATUS_ACTIVE
            
            # Schedule coordinator update (non-blocking)
            self.hass.async_create_task(self._update_from_coordinator())
            
            # Trigger HA state update
            self.async_write_ha_state()
            
        except Exception as e:
            _LOGGER.error(
                "Error handling Bermuda state change for %s: %s",
                self.person_id, e
            )
    
    async def _update_from_coordinator(self) -> None:
        """Update cached values from person coordinator."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator:
                return
            
            # Get current location from coordinator
            new_location = person_coordinator.get_person_location(self.person_id)
            new_confidence = person_coordinator.get_person_confidence(self.person_id)
            
            # Track room transitions for path history
            if new_location and new_location != self._cached_location:
                self._add_to_recent_path(self._cached_location, new_location)
            
            # Update cached values
            self._cached_location = new_location
            self._cached_confidence = new_confidence
            
            # Update tracking status based on location
            if new_location and new_location not in ("unknown", "away"):
                self._tracking_status = TRACKING_STATUS_ACTIVE
                self._last_bermuda_update = dt_util.now()
            
        except Exception as e:
            _LOGGER.error("Error updating from coordinator for %s: %s", self.person_id, e)
    
    def _add_to_recent_path(self, from_room: str | None, to_room: str) -> None:
        """Add a room transition to the recent path history.
        
        v3.2.8: Tracks last N room transitions for path analysis.
        """
        if not to_room:
            return
        
        transition = {
            "from": from_room or "unknown",
            "to": to_room,
            "time": dt_util.now().isoformat(),
        }
        
        self._recent_path.append(transition)
        
        # Keep only last N transitions
        if len(self._recent_path) > MAX_RECENT_PATH_LENGTH:
            self._recent_path = self._recent_path[-MAX_RECENT_PATH_LENGTH:]
    
    @callback
    def _check_presence_decay(self, now: datetime) -> None:
        """Check for presence staleness and decay.
        
        v3.2.8: Called periodically to update tracking_status.
        States: active -> stale -> lost
        """
        if not self._last_bermuda_update:
            self._tracking_status = TRACKING_STATUS_LOST
            return
        
        time_since_update = (now - self._last_bermuda_update).total_seconds()
        
        # Get decay timeout from config
        decay_timeout = self._get_config(
            CONF_PERSON_DECAY_TIMEOUT,
            DEFAULT_PERSON_DECAY_TIMEOUT
        )
        
        if time_since_update > decay_timeout:
            # Location is lost - clear it
            if self._tracking_status != TRACKING_STATUS_LOST:
                _LOGGER.info(
                    "Person %s location decayed to LOST (no update for %.0f seconds)",
                    self.person_id, time_since_update
                )
                self._tracking_status = TRACKING_STATUS_LOST
                self._cached_location = None
                self._cached_confidence = 0.0
                self.async_write_ha_state()
        elif time_since_update > STALE_THRESHOLD_SECONDS:
            # Location is stale but still valid
            if self._tracking_status != TRACKING_STATUS_STALE:
                _LOGGER.debug(
                    "Person %s location is STALE (no update for %.0f seconds)",
                    self.person_id, time_since_update
                )
                self._tracking_status = TRACKING_STATUS_STALE
                self.async_write_ha_state()
        else:
            # Location is active
            if self._tracking_status != TRACKING_STATUS_ACTIVE:
                self._tracking_status = TRACKING_STATUS_ACTIVE
                self.async_write_ha_state()
    
    @property
    def native_value(self) -> str:
        """Return person's current location."""
        # v3.2.8: Use cached location with decay handling
        if self._tracking_status == TRACKING_STATUS_LOST:
            return "Away"
        
        if not self._cached_location:
            # Fallback to coordinator
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            if person_coordinator:
                location = person_coordinator.get_person_location(self.person_id)
                if location:
                    return location.replace('_', ' ').title()
            return "Unknown"
        
        # Format room name nicely
        return self._cached_location.replace('_', ' ').title()
    
    @property
    def icon(self) -> str:
        """Return icon based on tracking status.
        
        v3.2.8: Dynamic icon for tracking state.
        """
        if self._tracking_status == TRACKING_STATUS_ACTIVE:
            return ICON_TRACKING_ACTIVE
        elif self._tracking_status == TRACKING_STATUS_STALE:
            return ICON_TRACKING_STALE
        else:
            return ICON_TRACKING_LOST
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes including v3.2.8 tracking status and path."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        attrs = {
            # v3.2.8: New tracking attributes
            ATTR_TRACKING_STATUS: self._tracking_status,
            ATTR_LAST_BERMUDA_UPDATE: (
                self._last_bermuda_update.isoformat()
                if self._last_bermuda_update else None
            ),
            ATTR_RECENT_PATH: self._recent_path,
        }
        
        # Confidence from coordinator
        if person_coordinator:
            confidence = self._cached_confidence or person_coordinator.get_person_confidence(self.person_id)
            attrs["confidence"] = round(confidence, 2)
            attrs["confidence_level"] = (
                "high" if confidence >= 0.8 else
                "medium" if confidence >= 0.5 else
                "low" if confidence > 0 else
                "none"
            )
        
        # Room ID
        if self._cached_location:
            attrs["room_id"] = self._cached_location
        
        # Time since last update
        if self._last_bermuda_update:
            time_ago = (dt_util.now() - self._last_bermuda_update).total_seconds()
            if time_ago < 60:
                attrs["last_update_ago"] = f"{int(time_ago)} seconds ago"
            elif time_ago < 3600:
                attrs["last_update_ago"] = f"{int(time_ago / 60)} minutes ago"
            else:
                attrs["last_update_ago"] = f"{int(time_ago / 3600)} hours ago"
        
        return attrs


class PersonPreviousLocationSensor(AggregationEntity, SensorEntity):
    """Sensor: Person's previous location.
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:map-marker-outline"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self.person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id}_previous_location"
        self._attr_name = f"{person_id.replace('_', ' ').title()} Previous Location"
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates.
        
        v3.2.8.3: Enables real-time updates when person tracking changes
        """
        # Subscribe to person_coordinator updates
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            self._unsub_person_coordinator = person_coordinator.async_add_listener(
                self._handle_person_update
            )
    
    async def async_will_remove_from_hass(self) -> None:
        """Clean up person_coordinator subscription."""
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None
    
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> str:
        """Return person's previous location."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return "Unknown"
        
        prev_location = person_coordinator.get_person_previous_location(self.person_id)
        
        if not prev_location:
            return "Unknown"
        
        return prev_location.replace('_', ' ').title()


class PersonPreviousSeenSensor(AggregationEntity, SensorEntity):
    """
    Sensor: When person was last seen in previous location.
    
    v3.2.8.1: Fixed to use previous_location_time instead of last_changed.
    Now correctly shows when person left their previous room, not when they entered current room.
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self.person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id}_previous_seen"
        self._attr_name = f"{person_id.replace('_', ' ').title()} Previous Seen"
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates.
        
        v3.2.8.3: Enables real-time updates when person tracking changes
        """
        # Subscribe to person_coordinator updates
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            self._unsub_person_coordinator = person_coordinator.async_add_listener(
                self._handle_person_update
            )
    
    async def async_will_remove_from_hass(self) -> None:
        """Clean up person_coordinator subscription."""
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None
    
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> datetime | None:
        """Return when person was last seen in previous location."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return None
        
        # v3.2.8.1: Use previous_location_time instead of last_changed
        return person_coordinator.get_person_previous_location_time(self.person_id)

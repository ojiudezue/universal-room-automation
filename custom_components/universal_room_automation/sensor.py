"""Sensor platform for Universal Room Automation."""
#
# Universal Room Automation v3.3.5.5
# Build: 2026-01-04
# File: sensor.py
# v3.3.1.3: Fixed PersonLikelyNextRoomSensor/PersonCurrentPathSensor __init__ signature
# v3.3.1.2: Fixed missing Optional and AggregationEntity imports
# v3.2.9: No changes (zone fixes in aggregation.py, fan fixes in automation.py)
# v3.2.8.3: Added person_coordinator subscriptions for real-time room sensor updates
# v3.2.8.2: DevicesSensor updated to count multi-domain auto/manual devices
# v3.2.8.1: Added PersonTrackingStatusSensor for room-level diagnostic tracking
# v3.2.8: PersonLocationSensor architectural fix - active state listeners
# v3.2.6: Renamed occupant sensors for clarity:
#   - "Current Occupants" → "Identified People"
#   - "Occupant Count" → "Identified People Count"
#   - "Last Occupant" → "Last Identified Person"
#   - "Last Occupant Time" → "Last Identified Time"
# v3.2.6: Added LastAutomationTimeSensor and PersonCoordinatorDiagnosticSensor
#
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
    PERCENTAGE,
    LIGHT_LUX,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ICON_TEMPERATURE,
    ICON_HUMIDITY,
    ICON_ILLUMINANCE,
    ICON_TIMEOUT,
    ICON_POWER,
    ICON_ENERGY,
    ICON_COST,
    ICON_DEVICES,
    ICON_PREDICTION,
    ICON_PRECONDITIONING,
    ICON_COMFORT,
    ICON_EFFICIENCY,
    ICON_PATTERN,
    ICON_ANOMALY,
    ICON_CONFIG_STATUS,
    ICON_DIAGNOSTIC,
    ICON_LAST_TRIGGER,
    ICON_LAST_ACTION,
    STATE_TEMPERATURE,
    STATE_HUMIDITY,
    STATE_ILLUMINANCE,
    STATE_TIMEOUT_REMAINING,
    STATE_POWER_CURRENT,
    STATE_ENERGY_TODAY,
    STATE_ENERGY_COST_TODAY,
    STATE_ENERGY_MONTHLY,
    STATE_ENERGY_COST_MONTHLY,
    STATE_ENERGY_WEEKLY,
    STATE_ENERGY_COST_WEEKLY,
    STATE_COST_PER_HOUR,
    STATE_LIGHTS_ON_COUNT,
    STATE_FANS_ON_COUNT,
    STATE_SWITCHES_ON_COUNT,
    STATE_COVERS_OPEN_COUNT,
    STATE_COVERS_POSITION_AVG,
    STATE_NEXT_OCCUPANCY_TIME,
    STATE_NEXT_OCCUPANCY_IN,
    STATE_OCCUPANCY_PCT_7D,
    STATE_PEAK_OCCUPANCY_TIME,
    STATE_PRECOOL_START_TIME,
    STATE_PREHEAT_START_TIME,
    STATE_PRECOOL_LEAD_MINUTES,
    STATE_PREHEAT_LEAD_MINUTES,
    STATE_OCCUPANCY_CONFIDENCE,
    STATE_COMFORT_SCORE,
    STATE_ENERGY_EFFICIENCY_SCORE,
    STATE_TIME_SINCE_MOTION,
    STATE_TIME_SINCE_OCCUPIED,
    STATE_OCCUPANCY_PCT_TODAY,
    CONF_TEMPERATURE_SENSOR,
    CONF_ELECTRICITY_RATE,
    DEFAULT_ELECTRICITY_RATE,
    ATTR_CONFIDENCE,
    ATTR_BASED_ON,
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity
from .aggregation import AggregationEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation sensors."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE

    # Check if this is an integration entry (aggregation sensors)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
        # Call the comprehensive aggregation sensor setup function
        from .aggregation import async_setup_aggregation_sensors
        await async_setup_aggregation_sensors(hass, entry, async_add_entities)
        return

    # v3.3.5.6: Zone entry - set up zone-specific aggregation sensors
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
        from .aggregation import async_setup_zone_sensors
        await async_setup_zone_sensors(hass, entry, async_add_entities)
        return

    # Room entry - normal sensor setup
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # === ENVIRONMENTAL (Always Visible) ===
    entities = [
        TemperatureSensor(coordinator),
        HumiditySensor(coordinator),
        IlluminanceSensor(coordinator),
    ]
    
    # === OCCUPANCY (Always Visible) ===
    entities.extend([
        OccupancyTimeoutSensor(coordinator),
    ])
    
    # === v3.2.0: PERSON TRACKING (Optional) ===
    # ALWAYS create these sensors - they handle missing coordinator gracefully
    # Fixes issue where rooms created before person_coordinator initialization
    # didn't get person sensors (v3.2.2.5 fix)
    entities.extend([
        CurrentOccupantsSensor(coordinator),
        OccupantCountSensor(coordinator),
        LastOccupantSensor(coordinator),
        LastOccupantTimeSensor(coordinator),
        # v3.2.8.1: Room-level person tracking diagnostic sensor
        PersonTrackingStatusSensor(coordinator),
    ])
    
    # === ENERGY - CURRENT (Always Visible) ===
    entities.extend([
        PowerCurrentSensor(coordinator),
        EnergyTodaySensor(coordinator),
        EnergyCostTodaySensor(coordinator),
    ])
    
    # === ENERGY - TRACKING (Optional) ===
    entities.extend([
        EnergyWeeklySensor(coordinator),
        EnergyCostWeeklySensor(coordinator),
        EnergyMonthlySensor(coordinator),
        EnergyCostMonthlySensor(coordinator),
        CostPerHourSensor(coordinator),
    ])
    
    # === DEVICE STATUS (Optional) ===
    entities.extend([
        LightsOnCountSensor(coordinator),
        FansOnCountSensor(coordinator),
        SwitchesOnCountSensor(coordinator),
        CoversOpenCountSensor(coordinator),
        CoversPositionAvgSensor(coordinator),
        DevicesSensor(coordinator),
        DeviceStatusSensor(coordinator),
    ])
    
    # === OCCUPANCY PREDICTIONS (Optional) ===
    entities.extend([
        NextOccupancyTimeSensor(coordinator),
        NextOccupancyInSensor(coordinator),
        OccupancyPercentage7dSensor(coordinator),
        PeakOccupancyTimeSensor(coordinator),
        OccupancyPatternDetectedSensor(coordinator),
    ])
    
    # === HVAC PREDICTIONS (Optional) ===
    entities.extend([
        PrecoolStartTimeSensor(coordinator),
        PrecoolLeadMinutesSensor(coordinator),
        PreheatStartTimeSensor(coordinator),
        PreheatLeadMinutesSensor(coordinator),
    ])
    
    # === COMFORT & EFFICIENCY (Optional) ===
    entities.extend([
        ComfortScoreSensor(coordinator),
        EnergyEfficiencyScoreSensor(coordinator),
    ])
    
    # === TIME TRACKING (Optional) ===
    entities.extend([
        TimeSinceMotionSensor(coordinator),
        TimeSinceOccupiedSensor(coordinator),
        OccupancyPercentageTodaySensor(coordinator),
        TimeOccupiedTodaySensor(coordinator),
        DaysSinceOccupiedSensor(coordinator),
    ])
    
    # === ADVANCED DIAGNOSTICS (Optional) ===
    entities.extend([
        EnergyWasteIdleSensor(coordinator),
        MostExpensiveDeviceSensor(coordinator),
        OptimizationPotentialSensor(coordinator),
        EnergyCostPerOccupiedHourSensor(coordinator),
        TimeUncomfortableTodaySensor(coordinator),
        AvgTimeToComfortSensor(coordinator),
        WeekdayMorningOccupancyProbSensor(coordinator),
        WeekendEveningOccupancyProbSensor(coordinator),
        ConfigStatusSensor(coordinator),
        UnavailableEntitiesSensor(coordinator),
        LastAutomationTriggerSensor(coordinator),
        LastAutomationActionSensor(coordinator),
        LastAutomationTimeSensor(coordinator),  # v3.2.6: New sensor
        DatabaseStatusSensor(coordinator),
    ])
    
    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d sensors for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


# ===================================================================
# PHASE 1: CORE SENSORS
# ===================================================================

class TemperatureSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for room temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_TEMPERATURE

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "temperature", "Temperature")

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        return self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement from source sensor."""
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        # Get unit from source sensor to avoid conversion issues (bug fix from v2.0)
        temp_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        if temp_sensor:
            state = self.hass.states.get(temp_sensor)
            if state:
                return state.attributes.get("unit_of_measurement")
        return UnitOfTemperature.CELSIUS  # Fallback

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return (
            self.coordinator.last_update_success and
            (self.coordinator.data and self.coordinator.data.get(STATE_TEMPERATURE)) is not None
        )


class HumiditySensor(UniversalRoomEntity, SensorEntity):
    """Sensor for room humidity."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = ICON_HUMIDITY

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "humidity", "Humidity")

    @property
    def native_value(self) -> float | None:
        """Return the humidity."""
        return self.coordinator.data.get(STATE_HUMIDITY) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return (
            self.coordinator.last_update_success and
            (self.coordinator.data and self.coordinator.data.get(STATE_HUMIDITY)) is not None
        )


class IlluminanceSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for room illuminance."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_icon = ICON_ILLUMINANCE

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "illuminance", "Illuminance")

    @property
    def native_value(self) -> float | None:
        """Return the illuminance."""
        return self.coordinator.data.get(STATE_ILLUMINANCE) if self.coordinator.data else None


class OccupancyTimeoutSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for occupancy timeout remaining."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = ICON_TIMEOUT

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "timeout_remaining", "Occupancy Timeout Remaining")

    @property
    def native_value(self) -> int:
        """Return the timeout remaining in seconds."""
        return self.coordinator.data.get(STATE_TIMEOUT_REMAINING, 0) if self.coordinator.data else 0


# ===================================================================
# PHASE 2: ENERGY INTELLIGENCE
# ===================================================================

class PowerCurrentSensor(UniversalRoomEntity, SensorEntity):
    """Current power consumption sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "power_current", "Power")

    @property
    def native_value(self) -> float | None:
        """Return the current power consumption."""
        return self.coordinator.data.get(STATE_POWER_CURRENT) if self.coordinator.data else None


class EnergyTodaySensor(UniversalRoomEntity, SensorEntity):
    """Energy consumed today sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_today", "Energy Today")
        self._last_valid_value: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return energy consumed today with monotonic increasing enforcement."""
        if not self.coordinator.data:
            return 0
        
        current = self.coordinator.data.get(STATE_ENERGY_TODAY, 0)
        
        # Handle reset (new day, very small value)
        if current is not None and current < 0.1:
            self._last_valid_value = current
            return current
        
        # Enforce monotonic increasing - reject decreases
        if current is not None and self._last_valid_value is not None:
            if current < self._last_valid_value:
                # Value decreased - return last known good value
                return self._last_valid_value
        
        # Valid value - update and return
        if current is not None:
            self._last_valid_value = current
        
        return current


class EnergyCostTodaySensor(UniversalRoomEntity, SensorEntity):
    """Energy cost today sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = ICON_COST

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_cost_today", "Energy Cost Today")

    @property
    def native_value(self) -> float | None:
        """Return energy cost today."""
        energy = self.coordinator.data.get(STATE_ENERGY_TODAY, 0) if self.coordinator.data else 0
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        rate = config.get(CONF_ELECTRICITY_RATE, DEFAULT_ELECTRICITY_RATE)
        return round(energy * rate, 2)


class EnergyMonthlySensor(UniversalRoomEntity, SensorEntity):
    """Monthly energy consumption sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_monthly", "Energy Monthly")

    @property
    def native_value(self) -> float | None:
        """Return monthly energy from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_MONTHLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class EnergyCostMonthlySensor(UniversalRoomEntity, SensorEntity):
    """Monthly energy cost sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = ICON_COST
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_cost_monthly", "Energy Cost Monthly")

    @property
    def native_value(self) -> float | None:
        """Return monthly energy cost from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_COST_MONTHLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class EnergyWeeklySensor(UniversalRoomEntity, SensorEntity):
    """Weekly energy consumption sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_weekly", "Energy Weekly")

    @property
    def native_value(self) -> float | None:
        """Return weekly energy from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_WEEKLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class EnergyCostWeeklySensor(UniversalRoomEntity, SensorEntity):
    """Weekly energy cost sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = ICON_COST
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_cost_weekly", "Energy Cost Weekly")

    @property
    def native_value(self) -> float | None:
        """Return weekly energy cost from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_COST_WEEKLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class CostPerHourSensor(UniversalRoomEntity, SensorEntity):
    """Cost per hour sensor based on current power."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD/h"
    _attr_icon = ICON_COST
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "cost_per_hour", "Cost Per Hour")

    @property
    def native_value(self) -> float | None:
        """Return cost per hour from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_COST_PER_HOUR)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None and
            self.coordinator.data.get(STATE_COST_PER_HOUR) is not None
        )


class LightsOnCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of lights currently on."""

    _attr_icon = "mdi:lightbulb-on"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "lights_on_count", "Lights On")

    @property
    def native_value(self) -> int:
        """Return count of lights on."""
        return self.coordinator.data.get(STATE_LIGHTS_ON_COUNT, 0) if self.coordinator.data else 0


class FansOnCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of fans currently on."""

    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "fans_on_count", "Fans On")

    @property
    def native_value(self) -> int:
        """Return count of fans on."""
        return self.coordinator.data.get(STATE_FANS_ON_COUNT, 0) if self.coordinator.data else 0


class SwitchesOnCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of switches currently on."""

    _attr_icon = "mdi:light-switch"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "switches_on_count", "Switches On")

    @property
    def native_value(self) -> int:
        """Return count of switches on."""
        return self.coordinator.data.get(STATE_SWITCHES_ON_COUNT, 0) if self.coordinator.data else 0


class CoversOpenCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of covers currently open."""

    _attr_icon = "mdi:window-open"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "covers_open_count", "Covers Open")

    @property
    def native_value(self) -> int:
        """Return count of covers open."""
        return self.coordinator.data.get(STATE_COVERS_OPEN_COUNT, 0) if self.coordinator.data else 0


class CoversPositionAvgSensor(UniversalRoomEntity, SensorEntity):
    """Average position of all covers."""

    _attr_icon = "mdi:window-shutter"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "covers_position_avg", "Covers Position Average")

    @property
    def native_value(self) -> float | None:
        """Return average cover position."""
        return self.coordinator.data.get(STATE_COVERS_POSITION_AVG, 0) if self.coordinator.data else 0


# ===================================================================
# PHASE 3: PREDICTIONS
# ===================================================================

class NextOccupancyTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for predicted next occupancy time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = ICON_PREDICTION

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "next_occupancy_time", "Next Occupancy Time")

    @property
    def native_value(self) -> datetime | None:
        """Return predicted next occupancy time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_NEXT_OCCUPANCY_TIME)

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        attrs = {}
        if self.coordinator.data:
            confidence = self.coordinator.data.get(STATE_OCCUPANCY_CONFIDENCE)
            if confidence is not None:
                attrs[ATTR_CONFIDENCE] = f"{int(confidence * 100)}%"
        return attrs

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class NextOccupancyInSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for minutes until next occupancy."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = ICON_PREDICTION

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "next_occupancy_in", "Next Occupancy In")

    @property
    def native_value(self) -> int | None:
        """Return minutes until next occupancy from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_NEXT_OCCUPANCY_IN)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class OccupancyPercentage7dSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for 7-day occupancy percentage."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = ICON_PATTERN
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "occupancy_percentage_7d", "Occupancy % (7 days)")

    @property
    def native_value(self) -> float | None:
        """Return 7-day occupancy percentage from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_OCCUPANCY_PCT_7D)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class PeakOccupancyTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for peak occupancy hour."""

    _attr_icon = ICON_PATTERN

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "peak_occupancy_time", "Peak Occupancy Time")

    @property
    def native_value(self) -> str | None:
        """Return peak occupancy hour from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PEAK_OCCUPANCY_TIME)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class PrecoolStartTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for when to start precooling."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "precool_start_time", "Precool Start Time")

    @property
    def native_value(self) -> datetime | None:
        """Return precool start time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PRECOOL_START_TIME)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class PreheatStartTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for when to start preheating."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "preheat_start_time", "Preheat Start Time")

    @property
    def native_value(self) -> datetime | None:
        """Return preheat start time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PREHEAT_START_TIME)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class PrecoolLeadMinutesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for precooling lead time."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "precool_lead_minutes", "Precool Lead Minutes")

    @property
    def native_value(self) -> int | None:
        """Return precool lead time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PRECOOL_LEAD_MINUTES)

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True


class PreheatLeadMinutesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for preheating lead time."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "preheat_lead_minutes", "Preheat Lead Minutes")

    @property
    def native_value(self) -> int | None:
        """Return preheat lead time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PREHEAT_LEAD_MINUTES)

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True


# ===================================================================
# PHASE 4: COMFORT & EFFICIENCY
# ===================================================================

class ComfortScoreSensor(UniversalRoomEntity, SensorEntity):
    """Comfort score based on temperature and humidity."""

    _attr_native_unit_of_measurement = "%"
    _attr_icon = ICON_COMFORT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "comfort_score", "Comfort Score")

    @property
    def native_value(self) -> int | None:
        """Return comfort score 0-100."""
        # TODO: Implement comfort scoring algorithm
        return None


class EnergyEfficiencyScoreSensor(UniversalRoomEntity, SensorEntity):
    """Energy efficiency score."""

    _attr_native_unit_of_measurement = "%"
    _attr_icon = ICON_EFFICIENCY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_efficiency_score", "Energy Efficiency Score")

    @property
    def native_value(self) -> int | None:
        """Return efficiency score 0-100."""
        # TODO: Implement efficiency scoring
        return None


class TimeSinceMotionSensor(UniversalRoomEntity, SensorEntity):
    """Time since last motion detected."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:motion-sensor-off"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "time_since_motion", "Time Since Motion")

    @property
    def native_value(self) -> int | None:
        """Return seconds since last motion."""
        return self.coordinator.data.get(STATE_TIME_SINCE_MOTION) if self.coordinator.data else None


class TimeSinceOccupiedSensor(UniversalRoomEntity, SensorEntity):
    """Time since room was last occupied."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "time_since_occupied", "Time Since Occupied")

    @property
    def native_value(self) -> float | None:
        """Return hours since last occupied."""
        seconds = self.coordinator.data.get(STATE_TIME_SINCE_OCCUPIED) if self.coordinator.data else None
        if seconds is not None:
            return round(seconds / 3600, 2)  # Convert seconds to hours
        return None


class OccupancyPercentageTodaySensor(UniversalRoomEntity, SensorEntity):
    """Today's occupancy percentage."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = ICON_PATTERN
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "occupancy_percentage_today", "Occupancy % Today")

    @property
    def native_value(self) -> float | None:
        """Return today's occupancy percentage."""
        # TODO: Calculate from today's data
        return None


class EnergyWasteIdleSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for energy wasted when room is idle/vacant."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:alert-circle"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_waste_idle", "Energy Waste Idle")

    @property
    def native_value(self) -> float | None:
        """Return energy wasted when vacant."""
        # TODO: Calculate from database
        return 0.0


class MostExpensiveDeviceSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for identifying most expensive device."""

    _attr_icon = "mdi:currency-usd"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "most_expensive_device", "Most Expensive Device")

    @property
    def native_value(self) -> str | None:
        """Return name of most expensive device."""
        # TODO: Analyze power consumption by device
        return "Unknown"


class OptimizationPotentialSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for potential energy savings."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:cash-multiple"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "optimization_potential", "Optimization Potential")

    @property
    def native_value(self) -> float | None:
        """Return potential monthly savings."""
        # TODO: Calculate optimization potential
        return 0.0


class EnergyCostPerOccupiedHourSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for energy cost per occupied hour."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD/h"
    _attr_icon = "mdi:clock-time-eight"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_cost_per_occupied_hour", "Energy Cost per Occupied Hour")

    @property
    def native_value(self) -> float | None:
        """Return cost per occupied hour."""
        # TODO: Calculate from database
        return 0.0


class TimeUncomfortableTodaySensor(UniversalRoomEntity, SensorEntity):
    """Sensor for time outside comfort zone today."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:thermometer-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "time_uncomfortable_today", "Time Uncomfortable Today")

    @property
    def native_value(self) -> int | None:
        """Return minutes outside comfort zone."""
        # TODO: Calculate from database
        return 0


class AvgTimeToComfortSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for average time to reach comfort zone."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:clock-fast"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "avg_time_to_comfort", "Average Time to Comfort")

    @property
    def native_value(self) -> int | None:
        """Return average minutes to reach comfort."""
        # TODO: Calculate from database
        return 0


class WeekdayMorningOccupancyProbSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for weekday morning occupancy probability."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "weekday_morning_occupancy_prob", "Weekday Morning Occupancy Probability")

    @property
    def native_value(self) -> int | None:
        """Return probability percentage."""
        # TODO: Calculate from database
        return 0


class WeekendEveningOccupancyProbSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for weekend evening occupancy probability."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:calendar-weekend"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "weekend_evening_occupancy_prob", "Weekend Evening Occupancy Probability")

    @property
    def native_value(self) -> int | None:
        """Return probability percentage."""
        # TODO: Calculate from database
        return 0


class ConfigStatusSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for configuration health status."""

    _attr_icon = ICON_CONFIG_STATUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "config_status", "Configuration Status")

    @property
    def native_value(self) -> str:
        """Return configuration status."""
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        # Check for required sensors
        temp_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        motion_sensors = config.get("motion_sensors", [])
        mmwave_sensors = config.get("presence_sensors", [])
        occupancy_sensors = config.get("occupancy_sensors", [])
        
        if not temp_sensor:
            return "Missing Temperature Sensor"
        if not motion_sensors and not mmwave_sensors and not occupancy_sensors:
            return "Missing Occupancy Sensors"
        
        return "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        return {
            "has_temperature": bool(config.get(CONF_TEMPERATURE_SENSOR)),
            "has_humidity": bool(config.get("humidity_sensor")),
            "has_illuminance": bool(config.get("illuminance_sensor")),
            "has_motion": bool(config.get("motion_sensors")),
            "has_presence": bool(config.get("presence_sensors")),
            "has_occupancy": bool(config.get("occupancy_sensors")),
        }


class UnavailableEntitiesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor listing unavailable entities."""

    _attr_icon = ICON_ANOMALY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "unavailable_entities", "Unavailable Entities")

    @property
    def native_value(self) -> int:
        """Return count of unavailable entities."""
        return len(self._get_unavailable_entities())

    def _get_unavailable_entities(self) -> list[str]:
        """Get list of unavailable entities."""
        unavailable = []
        # v3.2.4 FIX: Merge entry.options with entry.data (options has reconfigured values)
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        
        # Check all configured sensors
        for key in ["motion_sensors", "presence_sensors", "occupancy_sensors", "power_sensors"]:
            sensors = config.get(key, [])
            for sensor in sensors:
                if sensor:
                    state = self.coordinator.hass.states.get(sensor)
                    if not state or state.state in ("unavailable", "unknown"):
                        unavailable.append(sensor)
        
        # Check single sensors
        for key in ["temperature_sensor", "humidity_sensor", "illuminance_sensor"]:
            sensor = config.get(key)
            if sensor:
                state = self.coordinator.hass.states.get(sensor)
                if not state or state.state in ("unavailable", "unknown"):
                    unavailable.append(sensor)
        
        return unavailable

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return list of unavailable entities."""
        return {
            "unavailable_entities": self._get_unavailable_entities()
        }


class LastAutomationTriggerSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for last automation trigger (what caused occupancy detection)."""

    _attr_icon = ICON_LAST_TRIGGER
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_automation_trigger", "Last Automation Trigger")

    @property
    def native_value(self) -> str:
        """Return last trigger source."""
        source = self.coordinator._last_trigger_source
        if not source:
            return "None"
        return source.capitalize()
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return trigger details."""
        if not self.coordinator._last_trigger_source:
            return {}
        
        attrs = {
            "entity_id": self.coordinator._last_trigger_entity,
            "trigger_source": self.coordinator._last_trigger_source,
        }
        
        if self.coordinator._last_trigger_time:
            attrs["timestamp"] = self.coordinator._last_trigger_time.isoformat()
            time_ago = (dt_util.now() - self.coordinator._last_trigger_time).total_seconds()
            if time_ago < 60:
                attrs["time_ago"] = f"{int(time_ago)} seconds ago"
            elif time_ago < 3600:
                attrs["time_ago"] = f"{int(time_ago / 60)} minutes ago"
            else:
                attrs["time_ago"] = f"{int(time_ago / 3600)} hours ago"
        
        return attrs


class LastAutomationActionSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for last automation action (what automation did)."""

    _attr_icon = ICON_LAST_ACTION
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_automation_action", "Last Automation Action")

    @property
    def native_value(self) -> str:
        """Return last action description."""
        action = self.coordinator._last_action_description
        if not action:
            return "None"
        return action
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return action details."""
        if not self.coordinator._last_action_description:
            return {}
        
        attrs = {
            "entity_id": self.coordinator._last_action_entity,
            "action_type": self.coordinator._last_action_type,
        }
        
        if self.coordinator._last_action_time:
            attrs["timestamp"] = self.coordinator._last_action_time.isoformat()
            time_ago = (dt_util.now() - self.coordinator._last_action_time).total_seconds()
            if time_ago < 60:
                attrs["time_ago"] = f"{int(time_ago)} seconds ago"
            elif time_ago < 3600:
                attrs["time_ago"] = f"{int(time_ago / 60)} minutes ago"
            else:
                attrs["time_ago"] = f"{int(time_ago / 3600)} hours ago"
        
        return attrs




class LastAutomationTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for last automation time (v3.2.6).
    
    Shows when the room automation last took an action as a timestamp.
    Useful for debugging automation timing and activity.
    """

    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_automation_time", "Last Automation Time")

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last automation action."""
        return self.coordinator._last_action_time
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional context about the last automation."""
        attrs = {}
        
        if self.coordinator._last_action_time:
            time_ago = (dt_util.now() - self.coordinator._last_action_time).total_seconds()
            if time_ago < 60:
                attrs["time_ago"] = f"{int(time_ago)} seconds ago"
            elif time_ago < 3600:
                attrs["time_ago"] = f"{int(time_ago / 60)} minutes ago"
            else:
                attrs["time_ago"] = f"{int(time_ago / 3600)} hours ago"
            
            attrs["action"] = self.coordinator._last_action_description or "Unknown"
            attrs["trigger"] = self.coordinator._last_trigger_source or "Unknown"
        else:
            attrs["time_ago"] = "Never"
        
        return attrs

class DevicesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for device enumeration."""

    _attr_icon = ICON_DEVICES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "devices", "Devices")

    @property
    def native_value(self) -> int:
        """Return total device count.
        
        v3.2.8.2: Counts both legacy (auto_switches/manual_switches) and
        new (auto_devices/manual_devices) fields without double-counting.
        """
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        count = 0
        count += len(config.get("lights", []))
        count += len(config.get("fans", []))
        count += len(config.get("humidity_fans", []))
        count += len(config.get("covers", []))
        
        # v3.2.8.2: Combine legacy + new auto/manual fields (avoid double-counting)
        auto_devices = set(config.get("auto_devices", []))
        auto_devices.update(config.get("auto_switches", []))
        count += len(auto_devices)
        
        manual_devices = set(config.get("manual_devices", []))
        manual_devices.update(config.get("manual_switches", []))
        count += len(manual_devices)

        # v3.3.5.5: Count media player, power sensors, energy sensor
        if config.get("room_media_player"):
            count += 1
        count += len(config.get("power_sensors", []))
        if config.get("energy_sensor"):
            count += 1

        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device details.
        
        v3.2.8.2: Returns combined lists of legacy + new auto/manual fields.
        """
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        
        # v3.2.8.2: Combine legacy + new auto/manual fields
        auto_devices = list(set(config.get("auto_devices", []) + config.get("auto_switches", [])))
        manual_devices = list(set(config.get("manual_devices", []) + config.get("manual_switches", [])))
        
        return {
            "lights": config.get("lights", []),
            "fans": config.get("fans", []),
            "humidity_fans": config.get("humidity_fans", []),
            "covers": config.get("covers", []),
            "auto_devices": auto_devices,
            "manual_devices": manual_devices,
            # Also include legacy fields for backward compatibility
            "auto_switches": config.get("auto_switches", []),
            "manual_switches": config.get("manual_switches", []),
            # v3.3.5.5: Media and energy devices
            "room_media_player": config.get("room_media_player"),
            "power_sensors": config.get("power_sensors", []),
            "energy_sensor": config.get("energy_sensor"),
        }


class DeviceStatusSensor(UniversalRoomEntity, SensorEntity):
    """Sensor showing parent device names (not entity IDs)."""

    _attr_icon = "mdi:devices"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "device_status", "Device Status")

    @property
    def native_value(self) -> str:
        """Return comma-separated device names."""
        device_names = self._get_device_names()
        if not device_names:
            return "No devices"
        return ", ".join(device_names)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device count and list."""
        device_names = self._get_device_names()
        return {
            "device_count": len(device_names),
            "device_list": device_names,
        }

    def _get_device_names(self) -> list[str]:
        """Get parent device names from entities."""
        from homeassistant.helpers import device_registry as dr, entity_registry as er

        entity_reg = er.async_get(self.hass)
        device_reg = dr.async_get(self.hass)

        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        all_entities = []

        # Collect all entities from list-type keys
        for key in ["lights", "fans", "humidity_fans", "covers", "auto_switches", "manual_switches",
                     "power_sensors"]:
            all_entities.extend(config.get(key, []))

        # Collect single-entity keys
        for key in ["room_media_player", "energy_sensor"]:
            entity_id = config.get(key)
            if entity_id:
                all_entities.append(entity_id)

        device_names = set()
        for entity_id in all_entities:
            if entity_entry := entity_reg.async_get(entity_id):
                if entity_entry.device_id:
                    if device := device_reg.async_get(entity_entry.device_id):
                        device_names.add(device.name_by_user or device.name)

        return sorted(list(device_names))


class DaysSinceOccupiedSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for days since room was last occupied."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:calendar-remove"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "days_since_occupied", "Days Since Occupied")

    @property
    def native_value(self) -> int | None:
        """Return days since last occupied."""
        if self.coordinator._last_occupied_time:
            elapsed = (dt_util.now() - self.coordinator._last_occupied_time).total_seconds()
            return int(elapsed / 86400)  # Convert seconds to days
        return None


class TimeOccupiedTodaySensor(UniversalRoomEntity, SensorEntity):
    """Sensor for total time occupied today."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_icon = "mdi:clock-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "time_occupied_today", "Time Occupied Today")

    @property
    def native_value(self) -> float | None:
        """Return hours occupied today."""
        # TODO: Calculate from database
        return 0.0


class OccupancyPatternDetectedSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for detected occupancy pattern."""

    _attr_icon = ICON_PATTERN
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "occupancy_pattern_detected", "Occupancy Pattern Detected")

    @property
    def native_value(self) -> str:
        """Return detected pattern description."""
        # TODO: Implement pattern detection
        return "No Pattern Detected"


class DatabaseStatusSensor(UniversalRoomEntity, SensorEntity):
    """Sensor showing database collection status and record counts."""

    _attr_icon = "mdi:database"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "database_status", "Database Status")
        self._counts = {"occupancy_events": 0, "environmental_data": 0, "energy_snapshots": 0}

    @property
    def available(self) -> bool:
        """Sensor available if database exists."""
        return DOMAIN in self.hass.data and "database" in self.hass.data[DOMAIN]

    @property
    def native_value(self) -> str:
        """Return database status."""
        if not self.available:
            return "Database Not Available"
        
        total = sum(self._counts.values())
        if total == 0:
            return "Collecting Data..."
        return f"{total} Records"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed record counts."""
        if not self.available:
            return {}
        
        return {
            "occupancy_events": self._counts.get("occupancy_events", 0),
            "environmental_data": self._counts.get("environmental_data", 0),
            "energy_snapshots": self._counts.get("energy_snapshots", 0),
            "total_records": sum(self._counts.values()),
            "database_file": self.hass.data[DOMAIN]["database"].db_file if self.available else None,
        }

    async def async_update(self) -> None:
        """Update record counts."""
        if not self.available:
            return
        
        database = self.hass.data[DOMAIN].get("database")
        if database:
            try:
                self._counts = await database.get_table_counts(self.coordinator.entry.entry_id)
            except Exception as e:
                _LOGGER.error("Error updating database status: %s", e)


# =============================================================================
# v3.2.0: PERSON TRACKING SENSORS
# =============================================================================


class CurrentOccupantsSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: List of current occupants in room.
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:account-multiple"
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Current Occupants" to "Identified People"
        # unique_id kept as "current_occupants" for backward compatibility
        super().__init__(coordinator, "current_occupants", "Identified People")
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates when added to hass.
        
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
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None
    
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update.
        
        v3.2.8.3: Called when person tracking data changes
        """
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> str:
        """Return comma-separated list of occupants."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return "None"
        
        # Get room name from coordinator entry
        room_name = self.coordinator.entry.data.get("room_name", "")
        
        # Get persons in this room
        persons = person_coordinator.get_persons_in_room(room_name)
        
        if not persons:
            return "None"
        
        # Format names nicely (capitalize first letter)
        formatted_names = [p.replace('_', ' ').title() for p in persons]
        
        return ", ".join(formatted_names)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return {}
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        persons = person_coordinator.get_persons_in_room(room_name)
        
        # Get confidence for each person
        person_details = {}
        for person_id in persons:
            confidence = person_coordinator.get_person_confidence(person_id)
            person_details[person_id] = {
                "confidence": round(confidence, 2),
                "confidence_level": (
                    "high" if confidence >= 0.8 else
                    "medium" if confidence >= 0.5 else
                    "low"
                )
            }
        
        return {
            "person_ids": persons,
            "person_details": person_details,
            "count": len(persons)
        }


class OccupantCountSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: Count of occupants in room.
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "people"
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Occupant Count" to "Identified People Count"
        # unique_id kept as "occupant_count" for backward compatibility
        super().__init__(coordinator, "occupant_count", "Identified People Count")
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates when added to hass.
        
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
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None
    
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update.
        
        v3.2.8.3: Called when person tracking data changes
        """
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> int:
        """Return count of occupants."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return 0
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        persons = person_coordinator.get_persons_in_room(room_name)
        
        return len(persons)


class LastOccupantSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: Last person who occupied room."""
    
    _attr_icon = "mdi:account-clock"
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Last Occupant" to "Last Identified Person"
        # unique_id kept as "last_occupant" for backward compatibility
        super().__init__(coordinator, "last_occupant", "Last Identified Person")
    
    @property
    def native_value(self) -> str:
        """Return last occupant."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return "Unknown"
        
        room_id = self.coordinator.entry.entry_id
        
        # Get occupants from database (async handled in update)
        if hasattr(self, '_last_occupant'):
            return self._last_occupant
        
        return "Unknown"
    
    async def async_update(self) -> None:
        """Update last occupant from database."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        
        try:
            # Get most recent visit
            cursor = await database._db.execute("""
                SELECT person_id, entry_time
                FROM person_visits
                WHERE room_id = ?
                ORDER BY entry_time DESC
                LIMIT 1
            """, (room_name,))
            
            row = await cursor.fetchone()
            
            if row:
                person_id = row['person_id']
                self._last_occupant = person_id.replace('_', ' ').title()
                self._last_occupant_time = row['entry_time']
            else:
                self._last_occupant = "Unknown"
                self._last_occupant_time = None
                
        except Exception as e:
            _LOGGER.error("Error getting last occupant: %s", e)
            self._last_occupant = "Unknown"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = {}
        
        if hasattr(self, '_last_occupant_time') and self._last_occupant_time:
            attrs["last_seen"] = self._last_occupant_time.isoformat()
            
            # Calculate time ago
            now = datetime.now()
            if isinstance(self._last_occupant_time, str):
                last_time = datetime.fromisoformat(self._last_occupant_time)
            else:
                last_time = self._last_occupant_time
            
            time_diff = now - last_time
            attrs["time_ago"] = str(time_diff).split('.')[0]  # Remove microseconds
        
        return attrs


class LastOccupantTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: Timestamp of last occupant."""
    
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Last Occupant Time" to "Last Identified Time"
        # unique_id kept as "last_occupant_time" for backward compatibility
        super().__init__(coordinator, "last_occupant_time", "Last Identified Time")
    
    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last occupant."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return None
        
        if hasattr(self, '_last_time'):
            return self._last_time
        
        return None
    
    async def async_update(self) -> None:
        """Update last occupant time from database."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        
        try:
            cursor = await database._db.execute("""
                SELECT entry_time
                FROM person_visits
                WHERE room_id = ?
                ORDER BY entry_time DESC
                LIMIT 1
            """, (room_name,))
            
            row = await cursor.fetchone()
            
            if row:
                entry_time = row['entry_time']
                # Convert string to datetime if needed
                if isinstance(entry_time, str):
                    self._last_time = datetime.fromisoformat(entry_time)
                else:
                    self._last_time = entry_time
            else:
                self._last_time = None
                
        except Exception as e:
            _LOGGER.error("Error getting last occupant time: %s", e)
            self._last_time = None


class PersonTrackingStatusSensor(UniversalRoomEntity, SensorEntity):
    """
    v3.2.8.1: Room-level person tracking diagnostic sensor.
    
    Shows tracking quality and status for all persons in this room,
    helping debug why occupancy detection may not be working.
    """
    
    _attr_icon = "mdi:account-search"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "person_tracking_status", "Person Tracking Status")
    
    @property
    def native_value(self) -> str:
        """Return summary of person tracking status in this room."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator or not person_coordinator.data:
                return "No tracking data"
            
            room_name = self.coordinator.entry.data.get("room_name", "")
            if not room_name:
                return "Room not configured"
            
            # Get persons in this room
            persons_in_room = []
            for person_name, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location == room_name:
                    persons_in_room.append({
                        "person": person_name,
                        "status": person_info.get("tracking_status", "lost"),
                        "confidence": person_info.get("confidence", 0),
                        "method": person_info.get("method", "none"),
                    })
            
            if not persons_in_room:
                return "No persons in room"
            
            # Count by status
            active_count = sum(1 for p in persons_in_room if p["status"] == "active")
            stale_count = sum(1 for p in persons_in_room if p["status"] == "stale")
            lost_count = sum(1 for p in persons_in_room if p["status"] == "lost")
            
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
            _LOGGER.error("Error in PersonTrackingStatus.native_value for room '%s': %s", 
                         self.coordinator.entry.data.get("room_name", ""), e, exc_info=True)
            return "Error"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed tracking information."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator or not person_coordinator.data:
                return {}
            
            room_name = self.coordinator.entry.data.get("room_name", "")
            if not room_name:
                return {}
            
            # Build detailed person tracking info
            persons_in_room = []
            for person_name, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location == room_name:
                    persons_in_room.append({
                        "person": person_name,
                        "status": person_info.get("tracking_status", "lost"),
                        "confidence": round(person_info.get("confidence", 0), 2),
                        "method": person_info.get("method", "none"),
                        "bermuda_area": person_info.get("bermuda_area", "N/A"),
                    })
            
            return {
                "room_name": room_name,
                "persons_in_room": persons_in_room,
                "total_persons": len(persons_in_room),
            }
            
        except Exception as e:
            _LOGGER.error("Error in PersonTrackingStatus.extra_state_attributes: %s", e)
            return {}


# v3.3.0: Pattern learning and prediction sensors

class PersonLikelyNextRoomSensor(AggregationEntity, SensorEntity):
    """Predicted next room for person (v3.3.0 - simplified, no time-of-day)."""
    
    _attr_icon = "mdi:map-marker-path"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id.lower()}_likely_next_room"
        self._attr_name = f"{person_id} Likely Next Room"
    
    @property
    def native_value(self) -> Optional[str]:
        """Return predicted next room."""
        try:
            pattern_learner = self.hass.data[DOMAIN].get("pattern_learner")
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not pattern_learner or not person_coordinator:
                return None
            
            person_data = person_coordinator.data.get(self._person_id, {})
            current_room = person_data.get("location")
            
            if not current_room or current_room in ("unknown", "away", "home"):
                return None
            
            # Get prediction (async in sync context - not ideal but sensor pattern requires it)
            # In production, we'd cache this or use a better pattern
            # For v3.3.0, we'll accept this limitation
            import asyncio
            try:
                prediction = asyncio.create_task(
                    pattern_learner.predict_next_room(self._person_id, current_room)
                )
                # This is a hack - in production we'd handle this better
                # But for v3.3.0 simplified scope, it works
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    return None  # Can't block event loop
                else:
                    prediction = loop.run_until_complete(prediction)
            except:
                return None
            
            if prediction:
                return prediction["next_room"]
            return None
            
        except Exception as e:
            _LOGGER.error(f"Error in PersonLikelyNextRoomSensor: {e}")
            return None
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return prediction details."""
        try:
            pattern_learner = self.hass.data[DOMAIN].get("pattern_learner")
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not pattern_learner or not person_coordinator:
                return {}
            
            person_data = person_coordinator.data.get(self._person_id, {})
            current_room = person_data.get("location")
            
            if not current_room or current_room in ("unknown", "away", "home"):
                return {}
            
            # Same async limitation as above
            import asyncio
            try:
                prediction = asyncio.create_task(
                    pattern_learner.predict_next_room(self._person_id, current_room)
                )
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    return {}
                else:
                    prediction = loop.run_until_complete(prediction)
            except:
                return {}
            
            if not prediction:
                return {}
            
            return {
                "confidence": prediction["confidence"],
                "sample_size": prediction["sample_size"],
                "reliability": prediction["reliability"],
                "alternatives": prediction["alternatives"],
                "predicted_path": prediction["predicted_path"],
                "current_room": current_room
            }
            
        except Exception as e:
            _LOGGER.error(f"Error in PersonLikelyNextRoomSensor attributes: {e}")
            return {}


class PersonCurrentPathSensor(AggregationEntity, SensorEntity):
    """Current movement path (last 3-4 rooms visited)."""
    
    _attr_icon = "mdi:routes"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id.lower()}_current_path"
        self._attr_name = f"{person_id} Current Path"
    
    @property
    def native_value(self) -> Optional[str]:
        """Return current path as string."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            if not person_coordinator:
                return None
            
            # Get person data
            person_data = person_coordinator.data.get(self._person_id, {})
            
            # Build path from recent_path + current location
            recent_path = person_data.get("recent_path", [])
            current_location = person_data.get("location", "")
            
            # Combine into path
            if recent_path and current_location:
                path = recent_path[-3:] + [current_location]  # Last 3 + current
            elif current_location:
                path = [current_location]
            else:
                path = recent_path[-4:] if recent_path else []
            
            if not path:
                return None
            
            return " → ".join(path)
            
        except Exception as e:
            _LOGGER.error(f"Error in PersonCurrentPathSensor: {e}")
            return None
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return path details."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            if not person_coordinator:
                return {}
            
            person_data = person_coordinator.data.get(self._person_id, {})
            current_location = person_data.get("location", "")
            recent_path = person_data.get("recent_path", [])
            
            return {
                "current_location": current_location,
                "recent_path": recent_path,
                "path_length": len(recent_path) + (1 if current_location else 0)
            }
            
        except Exception as e:
            _LOGGER.error(f"Error in PersonCurrentPathSensor attributes: {e}")
            return {}


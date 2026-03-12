"""Sensor platform for Universal Room Automation."""
#
# Universal Room Automation v3.11.2
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
from homeassistant.core import HomeAssistant, callback
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
    from .const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE,
        ENTRY_TYPE_ZONE_MANAGER, ENTRY_TYPE_COORDINATOR_MANAGER,
    )

    # Check if this is an integration entry (aggregation sensors)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
        # Call the comprehensive aggregation sensor setup function
        from .aggregation import async_setup_aggregation_sensors
        await async_setup_aggregation_sensors(hass, entry, async_add_entities)

        # v3.5.0: Add census sensors for integration entry
        census_sensors = [
            URAPersonsInHouseSensor(hass, entry),
            URAIdentifiedPersonsInHouseSensor(hass, entry),
            URAUnidentifiedPersonsInHouseSensor(hass, entry),
            URAPersonsOnPropertySensor(hass, entry),
            URATotalPersonsOnPropertySensor(hass, entry),
            # Disabled by default (diagnostics)
            URACensusConfidenceSensor(hass, entry),
            URACensusValidationAgeSensor(hass, entry),
            # v3.5.1: Perimeter alert status (disabled by default)
            PerimeterAlertStatusSensor(hass, entry),
            # v3.5.2: Warehoused sensors — entry/exit counts and unidentified persons
            PersonsEnteredTodaySensor(hass, entry),
            PersonsExitedTodaySensor(hass, entry),
            LastPersonEntrySensor(hass, entry),
            LastPersonExitSensor(hass, entry),
            UnidentifiedPersonsSensor(hass, entry),
            # v3.6.0-c1: House state on integration device
            IntegrationHouseStateSensor(hass, entry),
            # v3.6.21: Music following health sensor
            MusicFollowingHealthSensor(hass, entry),
        ]
        async_add_entities(census_sensors)

        return

    # v3.6.0: Zone Manager entry - set up ALL zone sensors under this entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
        from .aggregation import async_setup_zone_manager_sensors
        await async_setup_zone_manager_sensors(hass, entry, async_add_entities)
        return

    # v3.6.0: Coordinator Manager entry - set up coordinator sensors under this entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        coordinator_sensors = [
            CoordinatorManagerSensor(hass, entry),
            HouseStateSensor(hass, entry),
            CoordinatorSummarySensor(hass, entry),
            # v3.6.0-c1: Presence Coordinator sensors
            PresenceHouseStateSensor(hass, entry),
            HouseStateConfidenceSensor(hass, entry),
            PresenceAnomalySensor(hass, entry),
            PresenceComplianceSensor(hass, entry),
            # v3.6.0-c2: Safety Coordinator sensors
            SafetyStatusSensor(hass, entry),
            SafetyActiveHazardsSensor(hass, entry),
            SafetyAffectedRoomsSensor(hass, entry),
            SafetyDiagnosticsSensor(hass, entry),
            SafetyAnomalySensor(hass, entry),
            SafetyComplianceSensor(hass, entry),
            # v3.6.0-c3: Security Coordinator sensors
            SecurityArmedStateSensor(hass, entry),
            SecurityLastEntrySensor(hass, entry),
            SecurityAnomalySensor(hass, entry),
            SecurityComplianceSensor(hass, entry),
            SecurityOpenEntriesSensor(hass, entry),
            SecurityLastLockSweepSensor(hass, entry),
            SecurityExpectedArrivalsSensor(hass, entry),
            # v3.6.27: Music Following Coordinator sensors
            MusicFollowingAnomalySensor(hass, entry),
            MusicFollowingTransfersTodaySensor(hass, entry),
            MusicFollowingActiveRoomsSensor(hass, entry),
            MusicFollowingLastTransferSensor(hass, entry),
            # v3.6.29: Notification Manager sensors
            NMLastNotificationSensor(hass, entry),
            NMNotificationsTodaySensor(hass, entry),
            NMCooldownRemainingSensor(hass, entry),
            NMChannelStatusSensor(hass, entry),
            NMTriggerSensor(hass, entry),
            NMAnomalySensor(hass, entry),
            NMDeliveryRateSensor(hass, entry),
            NMDiagnosticsSensor(hass, entry),
            NMInboundTodaySensor(hass, entry),
            # v3.7.0-E1: Energy Coordinator sensors
            EnergyTOUPeriodSensor(hass, entry),
            EnergyTOURateSensor(hass, entry),
            EnergyTOUSeasonSensor(hass, entry),
            EnergyBatteryStrategySensor(hass, entry),
            EnergySolarDayClassSensor(hass, entry),
            # v3.7.0-E2: Pool + EV sensors
            EnergyPoolOptimizationSensor(hass, entry),
            EnergyEVChargingStatusSensor(hass, entry),
            # v3.7.0-E3: Circuit + Generator sensors
            EnergyCircuitAnomalySensor(hass, entry),
            EnergyGeneratorStatusSensor(hass, entry),
            # v3.7.0-E4: Billing + Cost sensors
            EnergyCoordCostTodaySensor(hass, entry),
            EnergyCostCycleSensor(hass, entry),
            EnergyPredictedBillSensor(hass, entry),
            EnergyCurrentRateSensor(hass, entry),
            EnergyDeliveryRateSensor(hass, entry),
            EnergyImportTodaySensor(hass, entry),
            EnergyExportTodaySensor(hass, entry),
            # v3.7.0-E5: Forecast sensors
            EnergyForecastTodaySensor(hass, entry),
            EnergyBatteryFullTimeSensor(hass, entry),
            EnergyForecastAccuracySensor(hass, entry),
            # v3.7.0-E6: Situation + Constraint sensors
            EnergySituationSensor(hass, entry),
            EnergyHVACConstraintSensor(hass, entry),
            # v3.9.0-E6: Battery decision + Load shedding sensors
            EnergyBatteryDecisionSensor(hass, entry),
            EnergyLoadSheddingSensor(hass, entry),
            # v3.7.7: Consumption + EV monitoring sensors
            EnergyTotalConsumptionSensor(hass, entry),
            EnergyNetConsumptionSensor(hass, entry),
            EnergyEVChargeRateASensor(hass, entry),
            EnergyEVChargeRateBSensor(hass, entry),
            # v3.8.0-H1: HVAC Coordinator sensors
            HVACModeSensor(hass, entry),
            HVACAnomalySensor(hass, entry),
            HVACComplianceSensor(hass, entry),
            HVACOverrideFrequencySensor(hass, entry),
            HVACPreCoolLikelihoodSensor(hass, entry),
            HVACComfortRiskSensor(hass, entry),
            # v3.9.0: HVAC transparency sensors
            HVACArresterStateSensor(hass, entry),
        ]
        # v3.8.0-H1: Add per-zone HVAC sensors dynamically
        # Read zone IDs from Zone Manager config entry (not coordinator)
        # to avoid race condition where coordinator_manager isn't ready yet
        from .const import ENTRY_TYPE_ZONE_MANAGER as _ZM, CONF_ZONE_THERMOSTAT
        zone_num = 0
        for zm_entry in hass.config_entries.async_entries(DOMAIN):
            if zm_entry.data.get(CONF_ENTRY_TYPE) != _ZM:
                continue
            merged = {**zm_entry.data, **zm_entry.options}
            for _zname, zcfg in merged.get("zones", {}).items():
                if zcfg.get(CONF_ZONE_THERMOSTAT):
                    zone_num += 1
                    zone_id = f"zone_{zone_num}"
                    coordinator_sensors.append(
                        HVACZoneStatusSensor(hass, entry, zone_id)
                    )
                    coordinator_sensors.append(
                        HVACZonePresetSensor(hass, entry, zone_id)
                    )
        async_add_entities(coordinator_sensors)
        return

    # v3.3.5.6: Legacy zone entry - no longer creates sensors (migrated to Zone Manager)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
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
        AutomationHealthSensor(coordinator),  # v3.6.17: Composite automation health
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
# v3.6.17: AUTOMATION HEALTH SENSOR
# =============================================================================


class AutomationHealthSensor(UniversalRoomEntity, SensorEntity):
    """Composite sensor surfacing room automation internal state.

    Primary state is a rollup: normal / debouncing / grace_hold /
    failsafe / stuck_sensor.  All detail is in attributes so a single
    entity per room replaces 8+ individual diagnostic entities.

    Entity:  sensor.ura_<room>_automation_health
    Device:  the room device
    """

    _attr_icon = "mdi:heart-pulse"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "automation_health", "Automation Health")

    # -- primary state --------------------------------------------------

    @property
    def native_value(self) -> str:
        """Return the most significant active condition."""
        c = self.coordinator

        # Failsafe is highest priority
        if c._failsafe_fired:
            return "failsafe"

        # Stuck sensors
        now = dt_util.now()
        stuck = [
            eid for eid, since in c._sensor_on_since.items()
            if (now - since).total_seconds() > c._stuck_sensor_hours * 3600
        ]
        if stuck:
            return "stuck_sensor"

        # Grace hold (all sensors unavailable)
        if c._all_sensors_unavailable_since is not None:
            elapsed = (now - c._all_sensors_unavailable_since).total_seconds()
            if elapsed < c._unavail_grace_seconds:
                return "grace_hold"

        # Debounce pending
        if (
            c._occupancy_first_detected is not None
            and not (c.data or {}).get("occupied", False)
        ):
            return "debouncing"

        return "normal"

    # -- icon follows state ---------------------------------------------

    @property
    def icon(self) -> str:
        val = self.native_value
        return {
            "normal": "mdi:heart-pulse",
            "debouncing": "mdi:timer-sand",
            "grace_hold": "mdi:shield-half-full",
            "failsafe": "mdi:alert-octagon",
            "stuck_sensor": "mdi:motion-sensor-off",
        }.get(val, "mdi:heart-pulse")

    # -- attributes -----------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        now = dt_util.now()
        attrs: dict[str, Any] = {}

        # --- Tier 1: Occupancy session & failsafe ---
        if c._became_occupied_time and (c.data or {}).get("occupied", False):
            session_s = (now - c._became_occupied_time).total_seconds()
            attrs["session_duration_minutes"] = round(session_s / 60, 1)
            attrs["failsafe_remaining_minutes"] = max(
                0, round((4 * 3600 - session_s) / 60, 1)
            )
        else:
            attrs["session_duration_minutes"] = 0
            attrs["failsafe_remaining_minutes"] = None
        attrs["failsafe_fired"] = c._failsafe_fired

        # --- Tier 1: Stuck sensors ---
        stuck = []
        for eid, since in c._sensor_on_since.items():
            on_hours = (now - since).total_seconds() / 3600
            if on_hours > c._stuck_sensor_hours:
                stuck.append({"entity_id": eid, "on_hours": round(on_hours, 1)})
        attrs["stuck_sensors"] = stuck
        attrs["stuck_sensor_count"] = len(stuck)

        # --- Tier 1: Debounce ---
        if c._occupancy_first_detected is not None:
            elapsed = (now - c._occupancy_first_detected).total_seconds()
            attrs["debounce_active"] = elapsed < c._occupancy_debounce_seconds
            attrs["debounce_elapsed_seconds"] = round(elapsed, 1)
        else:
            attrs["debounce_active"] = False
            attrs["debounce_elapsed_seconds"] = None

        # --- Tier 1: Sensor grace period ---
        if c._all_sensors_unavailable_since is not None:
            elapsed = (now - c._all_sensors_unavailable_since).total_seconds()
            attrs["grace_active"] = elapsed < c._unavail_grace_seconds
            attrs["grace_remaining_seconds"] = max(
                0, round(c._unavail_grace_seconds - elapsed, 1)
            )
        else:
            attrs["grace_active"] = False
            attrs["grace_remaining_seconds"] = None

        # --- Tier 2: Sleep bypass ---
        if hasattr(c, "automation") and c.automation:
            attrs["sleep_bypass_count"] = c.automation._sleep_motion_count
        else:
            attrs["sleep_bypass_count"] = 0

        # --- Tier 2: Service call health ---
        if hasattr(c, "automation") and c.automation:
            a = c.automation
            attrs["service_calls_today"] = a._service_calls_today
            attrs["service_failures_today"] = a._service_failures_today
        else:
            attrs["service_calls_today"] = 0
            attrs["service_failures_today"] = 0

        # --- Tier 2: Exit verify ---
        attrs["last_exit_verify_result"] = c._last_exit_verify_result
        if c._last_exit_verify_time:
            attrs["last_exit_verify_time"] = c._last_exit_verify_time.isoformat()
        else:
            attrs["last_exit_verify_time"] = None

        return attrs


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
        # v3.5.x: unique_id updated to "identified_people" to match entity name
        # Migration in __init__.py renames existing "current_occupants" entities
        super().__init__(coordinator, "identified_people", "Identified People")
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
        # v3.5.x: unique_id updated to "identified_people_count" to match entity name
        # Migration in __init__.py renames existing "occupant_count" entities
        super().__init__(coordinator, "identified_people_count", "Identified People Count")
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
        # v3.5.x: unique_id updated to "last_identified_person" to match entity name
        # Migration in __init__.py renames existing "last_occupant" entities
        super().__init__(coordinator, "last_identified_person", "Last Identified Person")
    
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
            from homeassistant.util import dt as dt_util
            now = dt_util.utcnow()
            if isinstance(self._last_occupant_time, str):
                last_time = datetime.fromisoformat(self._last_occupant_time)
            else:
                last_time = self._last_occupant_time
            # Ensure timezone-aware
            if last_time.tzinfo is None:
                import pytz
                last_time = last_time.replace(tzinfo=pytz.UTC)
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
        # v3.5.x: unique_id updated to "last_identified_time" to match entity name
        # Migration in __init__.py renames existing "last_occupant_time" entities
        super().__init__(coordinator, "last_identified_time", "Last Identified Time")
    
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
                # Ensure timezone-aware (DB stores UTC without tzinfo)
                if self._last_time is not None and self._last_time.tzinfo is None:
                    import pytz
                    self._last_time = self._last_time.replace(tzinfo=pytz.UTC)
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
    """Predicted next room for a tracked person."""

    _attr_icon = "mdi:map-marker-path"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id.lower()}_likely_next_room"
        self._attr_name = f"{person_id} Likely Next Room"
        self._cached_prediction: dict | None = None
        self._last_camera_sighting: dict | None = None

    async def async_update(self) -> None:
        """Fetch prediction asynchronously and cache it."""
        try:
            pattern_learner = self.hass.data.get(DOMAIN, {}).get("pattern_learner")
            person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

            if not pattern_learner or not person_coordinator:
                self._cached_prediction = None
                return

            person_data = person_coordinator.data.get(self._person_id, {})
            current_room = person_data.get("location")

            if not current_room or current_room in ("unknown", "away", "home"):
                self._cached_prediction = None
                return

            self._cached_prediction = await pattern_learner.predict_next_room(
                self._person_id, current_room
            )
        except Exception as e:
            _LOGGER.error(
                "Error updating PersonLikelyNextRoomSensor for %s: %s",
                self._person_id, e,
            )
            self._cached_prediction = None

        # v3.5.2: Fetch camera sighting for transit validation attribute
        try:
            transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")
            if transit_validator and self._cached_prediction:
                self._last_camera_sighting = transit_validator.get_last_camera_sighting(
                    self._person_id
                )
            else:
                self._last_camera_sighting = None
        except Exception:
            self._last_camera_sighting = None

    @property
    def native_value(self) -> str | None:
        """Return predicted next room from cache."""
        if self._cached_prediction:
            return self._cached_prediction.get("next_room")
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return prediction details from cache."""
        if not self._cached_prediction:
            return {}
        sighting = self._last_camera_sighting
        ts = sighting.get("timestamp") if sighting else None
        if ts and hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        return {
            "confidence": self._cached_prediction.get("confidence"),
            "sample_size": self._cached_prediction.get("sample_size"),
            "reliability": self._cached_prediction.get("reliability"),
            "alternatives": self._cached_prediction.get("alternatives"),
            "predicted_path": self._cached_prediction.get("predicted_path"),
            "current_room": self._cached_prediction.get("current_room", ""),
            # v3.5.2: Camera validation attributes
            "camera_last_seen": ts,
            "camera_last_room": sighting.get("room") if sighting else None,
            "transit_camera_validated": sighting is not None,
        }


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


# ============================================================================
# v3.5.0: CENSUS SENSORS
# Integration-level sensors backed by PersonCensus (camera_census.py)
# ============================================================================


class _CensusBaseSensor(AggregationEntity, SensorEntity):
    """Base class for census sensors.

    Reads data from hass.data[DOMAIN]["census"] (PersonCensus instance).
    Gracefully returns 0 / unavailable if census has not run yet or
    camera integration is not configured.

    Subscribes to SIGNAL_CENSUS_UPDATED for immediate push updates
    when event-driven census triggers (v3.10.1).
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize census base sensor."""
        super().__init__(hass, entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to census updates for immediate push."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_CENSUS_UPDATED

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CENSUS_UPDATED,
                self._handle_census_update,
            )
        )

    def _handle_census_update(self, data: dict) -> None:
        """Handle census update signal — push state immediately."""
        self.async_write_ha_state()

    def _get_census(self):
        """Return last FullCensusResult or None."""
        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census is None:
            return None
        return census.last_result


class URAPersonsInHouseSensor(_CensusBaseSensor):
    """Total persons counted inside the house (camera + BLE)."""

    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_persons_in_house"
        self._attr_name = "Persons In House"

    @property
    def native_value(self) -> int:
        """Return total persons inside the house."""
        result = self._get_census()
        if result is None:
            return 0
        return result.house.total_persons

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional census attributes."""
        result = self._get_census()
        if result is None:
            return {}
        attrs = {
            "identified_count": result.house.identified_count,
            "unidentified_count": result.house.unidentified_count,
            "confidence": result.house.confidence,
            "source_agreement": result.house.source_agreement,
            "frigate_count": result.house.frigate_count,
            "unifi_count": result.house.unifi_count,
            "degraded_mode": result.house.degraded_mode,
            "active_platforms": result.house.active_platforms,
            "last_updated": result.timestamp.isoformat() if result.timestamp else None,
        }
        # v3.10.1 enhanced census attributes
        if result.house.enhanced_census:
            attrs["wifi_guest_floor"] = result.house.wifi_guest_floor
            attrs["camera_unrecognized"] = result.house.camera_unrecognized
            attrs["peak_held"] = result.house.peak_held
            attrs["peak_age_minutes"] = result.house.peak_age_minutes
            attrs["face_recognized_persons"] = result.house.face_recognized_persons
            attrs["enhanced_census"] = True
        return attrs


class URAIdentifiedPersonsInHouseSensor(_CensusBaseSensor):
    """Number of identified (named) persons inside the house."""

    _attr_icon = "mdi:account-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_identified_persons_in_house"
        self._attr_name = "Identified Persons In House"

    @property
    def native_value(self) -> int:
        """Return count of identified persons."""
        result = self._get_census()
        if result is None:
            return 0
        return result.house.identified_count

    @property
    def extra_state_attributes(self) -> dict:
        """Return identified person list and source details."""
        result = self._get_census()
        if result is None:
            return {}
        import json
        return {
            "person_list": json.dumps(result.house.identified_persons),
            "ble_confirmed": result.ble_persons,
            "face_confirmed": result.face_persons,
            "confidence": result.house.confidence,
        }


class URAUnidentifiedPersonsInHouseSensor(_CensusBaseSensor):
    """Number of unidentified (guest) persons inside the house."""

    _attr_icon = "mdi:account-question"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_unidentified_persons_in_house"
        self._attr_name = "Unidentified Persons In House"

    @property
    def native_value(self) -> int:
        """Return count of unidentified (guest) persons."""
        result = self._get_census()
        if result is None:
            return 0
        return result.house.unidentified_count


class URAPersonsOnPropertySensor(_CensusBaseSensor):
    """Number of persons on the exterior property (egress + perimeter cameras)."""

    _attr_icon = "mdi:home-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_persons_on_property_exterior"
        self._attr_name = "Persons On Property (Exterior)"

    @property
    def native_value(self) -> int:
        """Return number of persons detected on property exterior."""
        result = self._get_census()
        if result is None:
            return 0
        return result.persons_outside

    @property
    def extra_state_attributes(self) -> dict:
        """Return exterior census attributes."""
        result = self._get_census()
        if result is None:
            return {}
        attrs = {
            "confidence": result.property_exterior.confidence,
            "source_agreement": result.property_exterior.source_agreement,
            "last_updated": result.timestamp.isoformat() if result.timestamp else None,
        }
        # v3.10.1 enhanced census attributes
        if result.property_exterior.enhanced_census:
            attrs["peak_held"] = result.property_exterior.peak_held
            attrs["peak_age_minutes"] = result.property_exterior.peak_age_minutes
        return attrs


class URATotalPersonsOnPropertySensor(_CensusBaseSensor):
    """Total persons on the whole property (house + exterior)."""

    _attr_icon = "mdi:account-group"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_total_persons_on_property"
        self._attr_name = "Total Persons On Property"

    @property
    def native_value(self) -> int:
        """Return total persons on property (house + exterior)."""
        result = self._get_census()
        if result is None:
            return 0
        return result.total_on_property

    @property
    def extra_state_attributes(self) -> dict:
        """Return combined census summary."""
        result = self._get_census()
        if result is None:
            return {}
        return {
            "inside_count": result.house.total_persons,
            "outside_count": result.persons_outside,
            "identified_total": result.house.identified_count,
            "unidentified_total": result.house.unidentified_count + result.property_exterior.unidentified_count,
            "house_confidence": result.house.confidence,
            "exterior_confidence": result.property_exterior.confidence,
            "last_updated": result.timestamp.isoformat() if result.timestamp else None,
        }


class URACensusConfidenceSensor(_CensusBaseSensor):
    """Census confidence level diagnostic sensor (disabled by default)."""

    _attr_icon = "mdi:gauge"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_confidence"
        self._attr_name = "Census Confidence"
        self._attr_state_class = None  # Enum state, not numeric

    @property
    def native_value(self) -> str:
        """Return overall census confidence level."""
        result = self._get_census()
        if result is None:
            return "none"
        return result.house.confidence

    @property
    def extra_state_attributes(self) -> dict:
        """Return confidence details."""
        result = self._get_census()
        if result is None:
            return {}
        return {
            "house_confidence": result.house.confidence,
            "house_source_agreement": result.house.source_agreement,
            "exterior_confidence": result.property_exterior.confidence,
        }


class URACensusValidationAgeSensor(_CensusBaseSensor):
    """Age of last census result in seconds (disabled by default)."""

    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "s"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_validation_age"
        self._attr_name = "Census Validation Age"

    @property
    def native_value(self) -> int | None:
        """Return seconds since last census run."""
        result = self._get_census()
        if result is None or result.timestamp is None:
            return None
        from homeassistant.util import dt as dt_util
        now = dt_util.utcnow()
        ts = result.timestamp
        # Ensure both are timezone-aware for subtraction
        if ts.tzinfo is None:
            import pytz
            ts = ts.replace(tzinfo=pytz.UTC)
        delta = now - ts
        return int(delta.total_seconds())


# ============================================================================
# v3.5.1: Perimeter Alert Status Sensor
# ============================================================================


class PerimeterAlertStatusSensor(AggregationEntity, SensorEntity):
    """Diagnostic sensor showing the last perimeter alert timestamp.

    Reads from the PerimeterAlertManager stored in hass.data[DOMAIN].
    Disabled by default.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_perimeter_alert_last_time"
        self._attr_name = "Last Perimeter Alert"

    @property
    def available(self) -> bool:
        """Available when the perimeter alert manager is active."""
        manager = self.hass.data.get(DOMAIN, {}).get("perimeter_alert_manager")
        return manager is not None and manager.is_active

    @property
    def native_value(self) -> str | None:
        """Return ISO timestamp of the last perimeter alert, or None."""
        manager = self.hass.data.get(DOMAIN, {}).get("perimeter_alert_manager")
        if not manager:
            return None
        last_time = manager.last_alert_time
        if last_time is None:
            return None
        return last_time.isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        """Return diagnostic details about the alert manager."""
        manager = self.hass.data.get(DOMAIN, {}).get("perimeter_alert_manager")
        if not manager:
            return {"status": "not_initialized"}
        last_time = manager.last_alert_time
        return {
            "status": "active" if manager.is_active else "inactive",
            "last_alert_time": last_time.isoformat() if last_time else None,
        }


# ============================================================================
# v3.5.2: WAREHOUSED SENSORS — Entry/Exit Counts, Timestamps, Unidentified
# ============================================================================


class PersonsEnteredTodaySensor(AggregationEntity, SensorEntity):
    """Count of confirmed entry events via egress cameras since midnight.

    Resets at midnight. Restores today's count from the database on startup.
    """

    _attr_icon = "mdi:account-arrow-right"
    _attr_native_unit_of_measurement = "persons"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_persons_entered_today"
        self._attr_name = "Persons Entered Today"
        self._count: int = 0
        self._entries: list[dict] = []
        self._last_reset = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self._restoring: bool = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events and restore today's count from DB."""
        await super().async_added_to_hass()
        self._restoring = True

        # Restore from database
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            today_start = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            events = await database.get_entry_exit_events_since(today_start, direction="entry")
            self._count = len(events)
            self._entries = events[-20:]

        # Subscribe to live egress events
        from homeassistant.core import callback as ha_callback
        from homeassistant.helpers.event import async_track_time_change

        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)
        async_track_time_change(self.hass, self._midnight_reset, hour=0, minute=0, second=0)

        self._restoring = False
        self.async_write_ha_state()

    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if self._restoring:
            return
        if event.data.get("direction") != "entry":
            return
        self._count += 1
        self._entries.append({
            "person_id": event.data.get("person_id") or "unidentified",
            "time": event.data.get("timestamp"),
            "egress_camera": event.data.get("egress_camera"),
        })
        self.async_write_ha_state()

    def _midnight_reset(self, now) -> None:
        """Reset count at midnight."""
        self._count = 0
        self._entries = []
        self._last_reset = now
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return today's entry count."""
        return self._count

    @property
    def extra_state_attributes(self) -> dict:
        """Return entry details."""
        return {
            "entries": self._entries[-20:],
            "last_reset": self._last_reset.isoformat() if self._last_reset else None,
        }


class PersonsExitedTodaySensor(AggregationEntity, SensorEntity):
    """Count of confirmed exit events via egress cameras since midnight.

    Resets at midnight. Restores today's count from the database on startup.
    """

    _attr_icon = "mdi:account-arrow-left"
    _attr_native_unit_of_measurement = "persons"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_persons_exited_today"
        self._attr_name = "Persons Exited Today"
        self._count: int = 0
        self._entries: list[dict] = []
        self._last_reset = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self._restoring: bool = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events and restore today's count from DB."""
        await super().async_added_to_hass()
        self._restoring = True

        # Restore from database
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            today_start = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            events = await database.get_entry_exit_events_since(today_start, direction="exit")
            self._count = len(events)
            self._entries = events[-20:]

        from homeassistant.helpers.event import async_track_time_change

        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)
        async_track_time_change(self.hass, self._midnight_reset, hour=0, minute=0, second=0)

        self._restoring = False
        self.async_write_ha_state()

    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if self._restoring:
            return
        if event.data.get("direction") != "exit":
            return
        self._count += 1
        self._entries.append({
            "person_id": event.data.get("person_id") or "unidentified",
            "time": event.data.get("timestamp"),
            "egress_camera": event.data.get("egress_camera"),
        })
        self.async_write_ha_state()

    def _midnight_reset(self, now) -> None:
        """Reset count at midnight."""
        self._count = 0
        self._entries = []
        self._last_reset = now
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return today's exit count."""
        return self._count

    @property
    def extra_state_attributes(self) -> dict:
        """Return exit details."""
        return {
            "entries": self._entries[-20:],
            "last_reset": self._last_reset.isoformat() if self._last_reset else None,
        }


class LastPersonEntrySensor(AggregationEntity, SensorEntity):
    """Timestamp of the most recent confirmed entry event."""

    _attr_icon = "mdi:account-arrow-right"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_last_person_entry"
        self._attr_name = "Last Person Entry"
        self._last_entry: datetime | None = None
        self._last_person_id: str | None = None
        self._last_egress_camera: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events."""
        await super().async_added_to_hass()
        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)

    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if event.data.get("direction") != "entry":
            return
        ts_str = event.data.get("timestamp")
        if ts_str:
            self._last_entry = dt_util.parse_datetime(ts_str) or dt_util.now()
        else:
            self._last_entry = dt_util.now()
        self._last_person_id = event.data.get("person_id") or "unidentified"
        self._last_egress_camera = event.data.get("egress_camera")
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last entry."""
        return self._last_entry

    @property
    def extra_state_attributes(self) -> dict:
        """Return entry details."""
        return {
            "person_id": self._last_person_id,
            "egress_camera": self._last_egress_camera,
        }


class LastPersonExitSensor(AggregationEntity, SensorEntity):
    """Timestamp of the most recent confirmed exit event."""

    _attr_icon = "mdi:account-arrow-left"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_last_person_exit"
        self._attr_name = "Last Person Exit"
        self._last_exit: datetime | None = None
        self._last_person_id: str | None = None
        self._last_egress_camera: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events."""
        await super().async_added_to_hass()
        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)

    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if event.data.get("direction") != "exit":
            return
        ts_str = event.data.get("timestamp")
        if ts_str:
            self._last_exit = dt_util.parse_datetime(ts_str) or dt_util.now()
        else:
            self._last_exit = dt_util.now()
        self._last_person_id = event.data.get("person_id") or "unidentified"
        self._last_egress_camera = event.data.get("egress_camera")
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last exit."""
        return self._last_exit

    @property
    def extra_state_attributes(self) -> dict:
        """Return exit details."""
        return {
            "person_id": self._last_person_id,
            "egress_camera": self._last_egress_camera,
        }


class UnidentifiedPersonsSensor(AggregationEntity, SensorEntity):
    """House-level unidentified persons — camera sees them but BLE can't identify.

    Uses house-level camera count (PersonCensus) minus BLE identified count.
    Not per-zone: per-zone camera data does not exist in v3.5.1 Slim.
    """

    _attr_icon = "mdi:account-question"
    _attr_native_unit_of_measurement = "persons"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_unidentified_persons"
        self._attr_name = "Unidentified Persons"

    @property
    def native_value(self) -> int | None:
        """Return count of unidentified persons (camera total minus BLE identified)."""
        census_state = self.hass.states.get(
            "sensor.universal_room_automation_persons_in_house"
        )
        if not census_state:
            return None
        try:
            camera_total = int(float(census_state.state))
        except (ValueError, TypeError):
            return None

        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None
        ble_identified = sum(
            1 for p in person_coordinator.data.values()
            if p.get("location") not in (None, "unknown", "away")
        )

        return max(0, camera_total - ble_identified)

    @property
    def extra_state_attributes(self) -> dict:
        """Return source details."""
        census_state = self.hass.states.get(
            "sensor.universal_room_automation_persons_in_house"
        )
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        camera_total = None
        ble_identified = None
        if census_state:
            try:
                camera_total = int(float(census_state.state))
            except (ValueError, TypeError):
                pass
        if person_coordinator:
            ble_identified = sum(
                1 for p in person_coordinator.data.values()
                if p.get("location") not in (None, "unknown", "away")
            )
        return {
            "camera_total": camera_total,
            "ble_identified": ble_identified,
            "data_scope": "house_level",
            "note": "Per-zone unidentified count deferred until per-zone camera data available",
        }


# ============================================================================
# v3.6.0 Domain Coordinator Sensors
# ============================================================================


class CoordinatorManagerSensor(AggregationEntity, SensorEntity):
    """Sensor showing Coordinator Manager status (running/stopped).

    Entity: sensor.ura_coordinator_manager
    Device: URA: Coordinator Manager
    Category: diagnostic
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:robot"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator manager sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_coordinator_manager"
        self._attr_name = "Coordinator Manager"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str:
        """Return the manager status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        return manager.get_overall_status()

    @property
    def extra_state_attributes(self) -> dict:
        """Return coordinator details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return {
            "coordinators_registered": len(manager.coordinators),
            "coordinators_active": sum(
                1 for c in manager.coordinators.values() if c.enabled
            ),
            "decisions_today": manager.decisions_today,
            "conflicts_resolved_today": manager.conflicts_resolved_today,
        }


class HouseStateSensor(AggregationEntity, SensorEntity):
    """Sensor showing the current house state.

    Entity: sensor.ura_house_state
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the house state sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_house_state"
        self._attr_name = "House State"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str:
        """Return the current house state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        return manager.house_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return state machine details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return manager.house_state_machine.to_dict()


class CoordinatorSummarySensor(AggregationEntity, SensorEntity):
    """Summary sensor showing overall coordinator status.

    Entity: sensor.ura_coordinator_summary
    Device: URA: Coordinator Manager
    State: all_clear / advisory / alert / critical
    Attributes: per-coordinator status
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:robot"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator summary sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_coordinator_summary"
        self._attr_name = "Coordinator Summary"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str:
        """Return overall status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        if not manager.is_running:
            return "stopped"
        # In C0, no coordinators are registered yet — always all_clear
        return "all_clear"

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-coordinator summary."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return manager.get_summary()


# ============================================================================
# v3.6.0-c1: Presence Coordinator Sensors
# ============================================================================


class PresenceHouseStateSensor(AggregationEntity, SensorEntity):
    """Authoritative house state sensor on the Presence Coordinator device.

    Entity: sensor.ura_presence_house_state
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_house_state"
        self._attr_name = "Presence House State"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> str:
        """Return the current house state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        return manager.house_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return state machine details and presence diagnostics."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        attrs = manager.house_state_machine.to_dict()
        presence = manager.coordinators.get("presence")
        if presence is not None:
            attrs["confidence"] = round(presence.confidence, 2)
            attrs["census_count"] = presence.census_count
            attrs["zones"] = {
                name: tracker.mode
                for name, tracker in presence.zone_trackers.items()
            }
        return attrs


class HouseStateConfidenceSensor(AggregationEntity, SensorEntity):
    """Confidence of the inferred house state (0.0-1.0).

    Entity: sensor.ura_house_state_confidence
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:gauge"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_house_state_confidence"
        self._attr_name = "House State Confidence"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> float | None:
        """Return the confidence percentage."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        return round(presence.confidence, 2)


class PresenceAnomalySensor(AggregationEntity, SensorEntity):
    """Presence anomaly status.

    Entity: sensor.ura_presence_anomaly
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_anomaly"
        self._attr_name = "Presence Anomaly"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        presence = manager.coordinators.get("presence")
        if presence is None:
            return "disabled"
        if presence.anomaly_detector is None:
            return "not_configured"
        # Show learning status if not yet active
        learning = presence.anomaly_detector.get_learning_status()
        if hasattr(learning, 'value') and learning.value in ("insufficient_data", "learning"):
            return learning.value
        return presence.anomaly_detector.get_worst_severity().value


class PresenceComplianceSensor(AggregationEntity, SensorEntity):
    """Presence compliance rate.

    Entity: sensor.ura_presence_compliance
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_compliance"
        self._attr_name = "Presence Compliance"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> float:
        """Return the compliance rate."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 100.0
        presence = manager.coordinators.get("presence")
        if presence is None or presence.compliance_tracker is None:
            return 100.0
        # Get compliance rate from tracker if available
        try:
            rate = presence.compliance_tracker.get_compliance_rate("presence")
            return round(rate * 100, 1) if rate is not None else 100.0
        except (AttributeError, TypeError):
            return 100.0


class IntegrationHouseStateSensor(AggregationEntity, SensorEntity):
    """House state sensor duplicated on the URA integration device.

    Entity: sensor.ura_integration_house_state
    Device: Universal Room Automation (integration device)
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_integration_house_state"
        self._attr_name = "House State"
        # device_info inherited from AggregationEntity — integration device

    @property
    def native_value(self) -> str:
        """Return the current house state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        return manager.house_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return state machine details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return manager.house_state_machine.to_dict()


# ============================================================================
# v3.6.0-c2: Safety Coordinator Sensors
# ============================================================================

# Helper for Safety device info
def _safety_device_info():
    """Return DeviceInfo for the Safety Coordinator device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "safety_coordinator")},
        name="URA: Safety Coordinator",
        manufacturer="Universal Room Automation",
        model="Safety Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class SafetyStatusSensor(AggregationEntity, SensorEntity):
    """Overall safety status sensor.

    Entity: sensor.ura_safety_status
    Device: URA: Safety Coordinator
    State: "normal" / "warning" / "alert" / "critical"
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_status"
        self._attr_name = "Safety Status"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return the current safety status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "normal"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "normal"
        return safety.get_safety_status()

    @property
    def extra_state_attributes(self) -> dict:
        """Return safety status attributes."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}

        # v3.6.0.3: Scope and detail
        hazards_detail = safety.get_all_hazards_detail()
        hazard_locations = set(h["location"] for h in hazards_detail)
        num_locations = len(hazard_locations)

        if not hazards_detail:
            scope = "clear"
        elif num_locations == 1:
            scope = "room"
        elif num_locations >= 3 or any(h["severity"] == "critical" for h in hazards_detail):
            scope = "house"
        else:
            scope = "multi_room"

        return {
            "active_hazards": len(safety.active_hazards),
            "sensors_monitored": safety.sensors_monitored,
            "last_check": dt_util.utcnow().isoformat(),
            # v3.6.0.3: Scope and detail
            "scope": scope,
            "worst_location": hazards_detail[0]["location"] if hazards_detail else None,
            "hazards": hazards_detail,
        }

    @property
    def icon(self) -> str:
        """Return icon based on safety status."""
        value = self.native_value
        if value == "critical":
            return "mdi:shield-alert"
        elif value == "alert":
            return "mdi:shield-alert-outline"
        elif value == "warning":
            return "mdi:shield-half-full"
        return "mdi:shield-check"

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_write_ha_state()


class SafetyDiagnosticsSensor(AggregationEntity, SensorEntity):
    """Safety diagnostics sensor.

    Entity: sensor.ura_safety_diagnostics
    Device: URA: Safety Coordinator
    State: "healthy" / "degraded"
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:stethoscope"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_diagnostics"
        self._attr_name = "Safety Diagnostics"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return the diagnostics health status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "degraded"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "degraded"
        return safety.get_diagnostics_status()

    @property
    def extra_state_attributes(self) -> dict:
        """Return diagnostics attributes."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}
        return {
            "sensors_total": safety.sensors_monitored,
            "sensors_available": safety.sensors_monitored,
            "hazards_detected_24h": safety._hazards_detected_24h,
            "alerts_sent_24h": safety._alerts_sent_24h,
        }


class SafetyActiveHazardsSensor(AggregationEntity, SensorEntity):
    """Count of active safety hazards with full detail.

    v3.6.0.3: Glanceable entity — shows how many things are wrong.
    Entity: sensor.ura_safety_active_hazards
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:shield-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_active_hazards"
        self._attr_name = "Safety Active Hazards"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> int:
        """Return count of active hazards."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        safety = manager.coordinators.get("safety")
        if safety is None:
            return 0
        return len(safety.active_hazards)

    @property
    def icon(self) -> str:
        """Dynamic icon based on hazard count."""
        val = self.native_value
        if val == 0:
            return "mdi:shield-check"
        return "mdi:alert-octagon"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full hazard detail list."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"hazards": []}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {"hazards": []}
        return {"hazards": safety.get_all_hazards_detail()}

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_write_ha_state()


class SafetyAffectedRoomsSensor(AggregationEntity, SensorEntity):
    """Rooms with active safety hazards, grouped by zone.

    v3.6.0.6: Shows which rooms are affected and their zone grouping.
    Entity: sensor.ura_safety_affected_rooms
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_affected_rooms"
        self._attr_name = "Safety Affected Rooms"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return comma-separated room names or 'clear'."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "clear"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "clear"
        status = safety.get_affected_rooms()
        rooms = status.get("affected_rooms", [])
        if not rooms:
            return "clear"
        return ", ".join(rooms)

    @property
    def icon(self) -> str:
        """Dynamic icon."""
        if self.native_value == "clear":
            return "mdi:home-check"
        return "mdi:home-alert"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return affected rooms detail."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"affected_rooms": [], "affected_by_zone": {},
                    "room_count": 0, "zone_count": 0, "worst_room": None}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {"affected_rooms": [], "affected_by_zone": {},
                    "room_count": 0, "zone_count": 0, "worst_room": None}
        return safety.get_affected_rooms()

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_write_ha_state()


class SafetyAnomalySensor(AggregationEntity, SensorEntity):
    """Safety anomaly status.

    Entity: sensor.ura_safety_anomaly
    Device: URA: Safety Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_anomaly"
        self._attr_name = "Safety Anomaly"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "disabled"
        if safety.anomaly_detector is None:
            return "not_configured"
        learning = safety.anomaly_detector.get_learning_status()
        if hasattr(learning, 'value') and learning.value in ("insufficient_data", "learning"):
            return learning.value
        return safety.anomaly_detector.get_worst_severity().value


class SafetyComplianceSensor(AggregationEntity, SensorEntity):
    """Safety compliance rate.

    Entity: sensor.ura_safety_compliance
    Device: URA: Safety Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_compliance"
        self._attr_name = "Safety Compliance"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> float:
        """Return the compliance rate."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 100.0
        safety = manager.coordinators.get("safety")
        if safety is None or safety.compliance_tracker is None:
            return 100.0
        try:
            rate = safety.compliance_tracker.get_compliance_rate("safety")
            return round(rate * 100, 1) if rate is not None else 100.0
        except (AttributeError, TypeError):
            return 100.0


# ============================================================================
# v3.6.0-c3: Security Coordinator sensors
# ============================================================================


def _security_device_info():
    """Return DeviceInfo for the Security Coordinator device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "security_coordinator")},
        name="URA: Security Coordinator",
        manufacturer="Universal Room Automation",
        model="Security Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class SecurityArmedStateSensor(AggregationEntity, SensorEntity):
    """Current security armed state.

    Entity: sensor.ura_security_armed_state
    Device: URA: Security Coordinator
    State: "disarmed" / "armed_home" / "armed_away" / "armed_vacation"
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-lock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_armed_state"
        self._attr_name = "Security Armed State"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> str:
        """Return the current armed state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "disarmed"
        security = manager.coordinators.get("security")
        if security is None:
            return "disarmed"
        return security.armed_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return armed state attributes."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"status": "not_initialized"}
        security = manager.coordinators.get("security")
        if security is None:
            return {"status": "disabled"}
        return {
            "status": security.get_security_status(),
            "active_alert": security.active_alert,
        }

    @property
    def icon(self) -> str:
        """Dynamic icon based on armed state."""
        value = self.native_value
        if value == "disarmed":
            return "mdi:shield-off-outline"
        if value == "armed_away":
            return "mdi:shield-lock"
        if value == "armed_vacation":
            return "mdi:shield-airplane"
        return "mdi:shield-home"

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


class SecurityLastEntrySensor(AggregationEntity, SensorEntity):
    """Last security entry event.

    Entity: sensor.ura_security_last_entry
    Device: URA: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_last_entry"
        self._attr_name = "Security Last Entry"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> str:
        """Return the last entry verdict."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "none"
        security = manager.coordinators.get("security")
        if security is None:
            return "none"
        event = security.last_entry_event
        return event.get("verdict", "none")

    @property
    def extra_state_attributes(self) -> dict:
        """Return last entry event details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.last_entry_event

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


class SecurityAnomalySensor(AggregationEntity, SensorEntity):
    """Security anomaly status.

    Entity: sensor.ura_security_anomaly
    Device: URA: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_anomaly"
        self._attr_name = "Security Anomaly"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        security = manager.coordinators.get("security")
        if security is None:
            return "disabled"
        return security.get_anomaly_status()

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


class SecurityComplianceSensor(AggregationEntity, SensorEntity):
    """Security lock compliance rate.

    Entity: sensor.ura_security_compliance
    Device: URA: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lock-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_compliance"
        self._attr_name = "Security Compliance"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> float:
        """Return the lock compliance rate."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 100.0
        security = manager.coordinators.get("security")
        if security is None:
            return 100.0
        summary = security.get_compliance_summary()
        return summary.get("compliance_rate", 100.0)

    @property
    def extra_state_attributes(self) -> dict:
        """Return compliance details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.get_compliance_summary()

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


class SecurityOpenEntriesSensor(AggregationEntity, SensorEntity):
    """Count of currently-open configured doors/windows.

    Entity: sensor.ura_security_open_entries
    Device: URA: Security Coordinator
    State: integer count of open entries
    Attributes: list of open entries with entity_id, opened_at, open_minutes
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_open_entries"
        self._attr_name = "Security Open Entries"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> int:
        """Return count of open entry sensors."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        security = manager.coordinators.get("security")
        if security is None:
            return 0
        return len(security.open_entries)

    @property
    def extra_state_attributes(self) -> dict:
        """Return open entry details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.get_open_entries_snapshot()

    @property
    def icon(self) -> str:
        """Dynamic icon based on open count."""
        if self.native_value > 0:
            return "mdi:door-open"
        return "mdi:door-closed-lock"

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


class SecurityLastLockSweepSensor(AggregationEntity, SensorEntity):
    """Last lock sweep timestamp and results.

    Entity: sensor.ura_security_last_lock_sweep
    Device: URA: Security Coordinator
    State: ISO timestamp of last sweep (or "never")
    Attributes: found_unlocked, lock_actions_sent, unavailable, checks_today
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lock-check"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_last_lock_sweep"
        self._attr_name = "Security Last Lock Sweep"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self):
        """Return the timestamp of the last lock sweep."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        security = manager.coordinators.get("security")
        if security is None:
            return None
        sweep = security.last_lock_sweep
        ts = sweep.get("timestamp")
        if not ts:
            return None
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                import pytz
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return lock sweep result details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        sweep = security.last_lock_sweep
        if not sweep:
            return {"status": "no_sweep_yet"}
        return {
            "found_unlocked": sweep.get("found_unlocked", []),
            "lock_actions_sent": sweep.get("lock_actions_sent", []),
            "unavailable": sweep.get("unavailable", []),
            "checks_today": sweep.get("checks_today", 0),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


class SecurityExpectedArrivalsSensor(AggregationEntity, SensorEntity):
    """Expected arrivals and authorized guests currently active.

    Entity: sensor.ura_security_expected_arrivals
    Device: URA: Security Coordinator
    State: count of active expected arrivals (geofence + manual)
    Attributes: expected_arrivals list, authorized_guests list
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-arrow-left"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_expected_arrivals"
        self._attr_name = "Security Expected Arrivals"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> int:
        """Return count of active expected arrivals."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        security = manager.coordinators.get("security")
        if security is None:
            return 0
        snapshot = security.get_arrivals_snapshot()
        return snapshot.get("expected_count", 0)

    @property
    def extra_state_attributes(self) -> dict:
        """Return arrival and guest details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.get_arrivals_snapshot()

    @property
    def icon(self) -> str:
        """Dynamic icon based on arrival count."""
        if self.native_value > 0:
            return "mdi:account-arrow-left"
        return "mdi:account-check"

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


# ============================================================================
# v3.6.21: Music Following Health Sensor
# v3.6.27: Music Following diagnostic sensors (anomaly, transfers, rooms, last)
# ============================================================================


def _music_following_device_info():
    """Return DeviceInfo for the Music Following Coordinator device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "music_following_coordinator")},
        name="URA: Music Following Coordinator",
        manufacturer="Universal Room Automation",
        model="Music Following Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class MusicFollowingHealthSensor(AggregationEntity, SensorEntity):
    """House-level diagnostic sensor for music following.

    Entity: sensor.ura_music_following_health
    Device: Coordinator device when Music Following Coordinator is active,
            otherwise falls back to integration device.
    State: idle / following / transferring / cooldown / error
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:music-note"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_health"
        self._attr_name = "Music Following Health"
        self._music_following = None
        # v3.6.27: Use shared device info helper
        self._attr_device_info = _music_following_device_info()

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the primary state."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return "idle"
        return mf._state

    @property
    def icon(self) -> str:
        val = self.native_value
        return {
            "idle": "mdi:music-note",
            "following": "mdi:music-note-plus",
            "transferring": "mdi:swap-horizontal",
            "cooldown": "mdi:timer-sand",
            "error": "mdi:alert-circle",
        }.get(val, "mdi:music-note")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return {}
        return mf.get_diagnostic_data()


class MusicFollowingAnomalySensor(AggregationEntity, SensorEntity):
    """Music Following anomaly status.

    v3.6.27: Anomaly detector was wired in v3.6.26 but had no visible sensor.
    Entity: sensor.ura_music_following_anomaly
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_anomaly"
        self._attr_name = "Music Following Anomaly"
        self._attr_device_info = _music_following_device_info()

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        mf_coord = manager.coordinators.get("music_following")
        if mf_coord is None:
            return "disabled"
        if mf_coord.anomaly_detector is None:
            return "not_configured"
        learning = mf_coord.anomaly_detector.get_learning_status()
        if hasattr(learning, 'value') and learning.value in ("insufficient_data", "learning"):
            return learning.value
        return mf_coord.anomaly_detector.get_worst_severity().value


class MusicFollowingTransfersTodaySensor(AggregationEntity, SensorEntity):
    """Total music transfers today with outcome breakdown.

    v3.6.27: Glanceable transfer count with success/failure detail.
    Entity: sensor.ura_music_following_transfers_today
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_transfers_today"
        self._attr_name = "Music Following Transfers Today"
        self._attr_device_info = _music_following_device_info()
        self._music_following = None

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_write_ha_state()

    # Stats that indicate actual music-involved transfer attempts
    _TRANSFER_STATS = ("success", "failed", "unverified", "active_playback_blocked")

    @property
    def native_value(self) -> int:
        """Return count of actual transfer attempts today (music-involved only)."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return 0
        return sum(mf._transfer_stats.get(k, 0) for k in self._TRANSFER_STATS)

    @property
    def icon(self) -> str:
        """Dynamic icon based on failure presence."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is not None and mf._transfer_stats.get("failed", 0) > 0:
            return "mdi:swap-horizontal-circle"
        return "mdi:swap-horizontal-bold"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return outcome breakdown."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return {}
        stats = mf._transfer_stats
        total = sum(stats.values())
        successes = stats.get("success", 0)
        return {
            "success": successes,
            "failed": stats.get("failed", 0),
            "unverified": stats.get("unverified", 0),
            "cooldown_blocked": stats.get("cooldown_blocked", 0),
            "active_playback_blocked": stats.get("active_playback_blocked", 0),
            "low_confidence": stats.get("low_confidence", 0),
            "ping_pong_suppressed": stats.get("ping_pong_suppressed", 0),
            "success_rate": round(successes / total * 100, 1) if total > 0 else 0.0,
        }


class MusicFollowingActiveRoomsSensor(AggregationEntity, SensorEntity):
    """Rooms with media players configured for music following.

    v3.6.27: Shows which rooms have music following capability.
    Entity: sensor.ura_music_following_active_rooms
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_active_rooms"
        self._attr_name = "Music Following Active Rooms"
        self._attr_device_info = _music_following_device_info()
        self._music_following = None

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return CSV of room names with media players, or 'none'."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return "none"
        rooms = self._get_configured_rooms(mf)
        if not rooms:
            return "none"
        return ", ".join(sorted(rooms))

    @property
    def icon(self) -> str:
        """Dynamic icon."""
        if self.native_value == "none":
            return "mdi:music-off"
        return "mdi:speaker-multiple"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return room and person details."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return {"rooms": [], "room_count": 0, "enabled_persons": [], "person_count": 0}
        rooms = sorted(self._get_configured_rooms(mf))
        persons = sorted(mf._enabled_persons)
        return {
            "rooms": rooms,
            "room_count": len(rooms),
            "enabled_persons": persons,
            "person_count": len(persons),
        }

    @staticmethod
    def _get_configured_rooms(mf) -> list[str]:
        """Get room names that have room_media_player configured."""
        rooms = []
        try:
            room_entries = mf._get_room_entries()
            for entry_data in room_entries.values():
                if entry_data.get("room_media_player"):
                    room_name = entry_data.get("name", entry_data.get("room_name", "unknown"))
                    rooms.append(room_name)
        except Exception:
            pass
        return rooms


class MusicFollowingLastTransferSensor(AggregationEntity, SensorEntity):
    """Last music transfer result with event details.

    v3.6.27: Shows the most recent transfer outcome.
    Entity: sensor.ura_music_following_last_transfer
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_last_transfer"
        self._attr_name = "Music Following Last Transfer"
        self._attr_device_info = _music_following_device_info()
        self._music_following = None

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return last transfer result or 'none'."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None or not mf._last_transfer_result:
            return "none"
        return mf._last_transfer_result

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return last transfer event details."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None or not mf._last_transfer_result:
            return {}
        return {
            "person": mf._last_transfer_person,
            "from_room": mf._last_transfer_from,
            "to_room": mf._last_transfer_to,
            "time": mf._last_transfer_time_iso,
            "result": mf._last_transfer_result,
        }


# ============================================================================
# v3.6.29: Notification Manager Sensors
# ============================================================================


def _nm_device_info():
    """Return DeviceInfo for the Notification Manager device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "notification_manager")},
        name="URA: Notification Manager",
        manufacturer="Universal Room Automation",
        model="Notification Manager",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class NMLastNotificationSensor(AggregationEntity, SensorEntity):
    """Last notification severity and details.

    Entity: sensor.ura_notification_last
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_last"
        self._attr_name = "Last Notification"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return severity of last notification or 'none'."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return "none"
        return nm.last_notification.get("severity", "none")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return last notification details."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return {}
        data = nm.last_notification
        return {
            "message": data.get("message", ""),
            "coordinator": data.get("coordinator", ""),
            "channels": data.get("channels", []),
            "hazard_type": data.get("hazard_type"),
            "location": data.get("location"),
            "timestamp": data.get("timestamp", ""),
        }


class NMNotificationsTodaySensor(AggregationEntity, SensorEntity):
    """Count of notifications sent today.

    Entity: sensor.ura_notifications_today
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notifications_today"
        self._attr_name = "Notifications Today"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return count of notifications today."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 0
        return nm.notifications_today


class NMCooldownRemainingSensor(AggregationEntity, SensorEntity):
    """Seconds remaining in post-ack cooldown.

    Entity: sensor.ura_notification_cooldown_remaining
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_cooldown_remaining"
        self._attr_name = "Notification Cooldown Remaining"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return seconds remaining in cooldown."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 0
        return nm.cooldown_remaining

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return cooldown context."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "hazard_type": nm._cooldown_hazard_type,
            "location": nm._cooldown_location,
            "alert_state": nm.alert_state,
        }


class NMChannelStatusSensor(AggregationEntity, SensorEntity):
    """Per-channel health status.

    Entity: sensor.ura_notification_channel_status
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_channel_status"
        self._attr_name = "Notification Channel Status"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return overall channel status."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return "not_initialized"
        statuses = nm.channel_status
        if any(ch.get("status") == "degraded" for ch in statuses.values()):
            return "degraded"
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-channel health."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return nm.channel_status


class NMTriggerSensor(AggregationEntity, SensorEntity):
    """Trigger sensor — state changes on each notification for user HA automations.

    Entity: sensor.ura_notification_trigger
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_trigger"
        self._attr_name = "Notification Trigger"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return coordinator_severity trigger string."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return "none"
        data = nm.last_notification
        coord = data.get("coordinator", "unknown")
        sev = data.get("severity", "unknown").lower()
        return f"{coord}_{sev}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return notification details for automation use."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return {}
        data = nm.last_notification
        return {
            "coordinator": data.get("coordinator", ""),
            "severity": data.get("severity", ""),
            "title": data.get("title", ""),
            "message": data.get("message", ""),
            "hazard_type": data.get("hazard_type"),
            "location": data.get("location"),
            "timestamp": data.get("timestamp", ""),
        }


class NMAnomalySensor(AggregationEntity, SensorEntity):
    """Notification volume anomaly status.

    Entity: sensor.ura_notification_anomaly
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_anomaly"
        self._attr_name = "Notification Anomaly"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return anomaly status."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return "not_initialized"
        if not nm.enabled:
            return "disabled"
        return nm.anomaly_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return anomaly detail attributes."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "dedup_suppressions": nm._dedup_suppressions,
            "quiet_suppressions": nm._quiet_suppressions,
            "notifications_today": nm.notifications_today,
        }


class NMDeliveryRateSensor(AggregationEntity, SensorEntity):
    """Notification delivery success rate.

    Entity: sensor.ura_notification_delivery_rate
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-network-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_delivery_rate"
        self._attr_name = "Notification Delivery Rate"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        """Return delivery success rate."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 100.0
        return nm.delivery_rate

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return delivery detail."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "send_attempts": nm._send_attempts,
            "send_successes": nm._send_successes,
            "send_failures": nm._send_failures,
        }


class NMDiagnosticsSensor(AggregationEntity, SensorEntity):
    """Composite NM health and diagnostics.

    Entity: sensor.ura_notification_diagnostics
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:stethoscope"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_diagnostics"
        self._attr_name = "Notification Diagnostics"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return overall NM health status."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return "not_initialized"
        if not nm.enabled:
            return "disabled"
        # Degraded if any channel is degraded or delivery rate < 80%
        any_degraded = any(
            ch["status"] == "degraded" for ch in nm.channel_status.values()
        )
        if any_degraded or nm.delivery_rate < 80:
            return "degraded"
        return "healthy"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full diagnostic breakdown."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return nm.diagnostics_summary


class NMInboundTodaySensor(AggregationEntity, SensorEntity):
    """Count of inbound messages received today.

    Entity: sensor.ura_notification_inbound_today
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:message-reply-text"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_inbound_today"
        self._attr_name = "Notification Inbound Today"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return count of inbound messages today."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 0
        return nm.inbound_today

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return inbound breakdown."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "by_channel": nm.inbound_by_channel,
            "by_command": nm.inbound_by_command,
            "safe_word_configured": nm.safe_word_configured,
        }


# ============================================================================
# v3.7.0-E1: ENERGY COORDINATOR SENSORS
# ============================================================================


def _energy_device_info():
    """Return device info for Energy Coordinator sensors."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "energy_coordinator")},
        name="URA: Energy Coordinator",
        manufacturer="Universal Room Automation",
        model="Energy Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class EnergyTOUPeriodSensor(AggregationEntity, SensorEntity):
    """Current TOU period: off_peak, mid_peak, or peak.

    Entity: sensor.ura_tou_period
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-time-four"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_tou_period"
        self._attr_name = "TOU Period"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return current TOU period."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.tou_period

    @property
    def extra_state_attributes(self) -> dict:
        """Return TOU details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        info = energy.tou_engine.get_period_info()
        next_t = info.get("next_transition", {})
        return {
            "season": info.get("season"),
            "import_rate": info.get("import_rate"),
            "export_rate": info.get("export_rate"),
            "effective_import_rate": info.get("effective_import_rate"),
            "next_period": next_t.get("next_period"),
            "hours_until_transition": next_t.get("hours_until"),
            "rate_source": info.get("rate_source"),
        }


class EnergyTOURateSensor(AggregationEntity, SensorEntity):
    """Current TOU import rate in $/kWh.

    Entity: sensor.ura_tou_rate
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:currency-usd"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_tou_rate"
        self._attr_name = "TOU Rate"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        """Return current import rate."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return round(energy.tou_rate, 6)


class EnergyTOUSeasonSensor(AggregationEntity, SensorEntity):
    """Current TOU season: summer, shoulder, or winter.

    Entity: sensor.ura_tou_season
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_tou_season"
        self._attr_name = "TOU Season"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return current season."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.tou_season


class EnergyBatteryStrategySensor(AggregationEntity, SensorEntity):
    """Current battery strategy mode and reason.

    Entity: sensor.ura_battery_strategy
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-charging"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_battery_strategy"
        self._attr_name = "Battery Strategy"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return current battery mode."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        status = energy.battery_status
        return status.get("mode", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        """Return battery strategy details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.battery_status


class EnergySolarDayClassSensor(AggregationEntity, SensorEntity):
    """Solar day classification from Solcast forecast.

    Entity: sensor.ura_solar_day_class
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:white-balance-sunny"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_solar_day_class"
        self._attr_name = "Solar Day Class"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return solar day classification."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.solar_day_class

    @property
    def extra_state_attributes(self) -> dict:
        """Return Solcast forecast details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        battery = energy.battery_strategy
        return {
            "forecast_today_kwh": battery.solcast_today,
            "forecast_remaining_kwh": battery.solcast_remaining,
        }


# ============================================================================
# v3.7.0-E2: ENERGY POOL + EV SENSORS
# ============================================================================


class EnergyPoolOptimizationSensor(AggregationEntity, SensorEntity):
    """Current pool optimization state.

    Entity: sensor.ura_pool_optimization
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:pool"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_pool_optimization"
        self._attr_name = "Pool Optimization"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return pool optimization state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.pool_status.get("state", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        """Return pool details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.pool_status


class EnergyEVChargingStatusSensor(AggregationEntity, SensorEntity):
    """EV charging status across all EVSEs.

    Entity: sensor.ura_ev_charging_status
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:ev-station"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_ev_charging_status"
        self._attr_name = "EV Charging Status"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return overall EV status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        status = energy.ev_status
        paused = status.get("paused_by_energy", [])
        if paused:
            return "paused"
        # Check if any EVSE is actively charging
        for key, val in status.items():
            if isinstance(val, dict) and val.get("charging"):
                return "charging"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-EVSE details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.ev_status


# ============================================================================
# v3.7.0-E3: CIRCUIT + GENERATOR SENSORS
# ============================================================================


class EnergyCircuitAnomalySensor(AggregationEntity, SensorEntity):
    """Circuit anomaly state.

    Entity: sensor.ura_circuit_anomaly
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:flash-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_circuit_anomaly"
        self._attr_name = "Circuit Anomaly"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return anomaly state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        status = energy.circuit_status
        count = status.get("anomaly_count", 0)
        if count > 0:
            return f"alert ({count})"
        return "normal"

    @property
    def extra_state_attributes(self) -> dict:
        """Return circuit monitoring details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.circuit_status


class EnergyGeneratorStatusSensor(AggregationEntity, SensorEntity):
    """Generator status sensor.

    Entity: sensor.ura_generator_status
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:engine"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_generator_status"
        self._attr_name = "Generator Status"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return generator status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.generator_status.get("status", "unknown")


# ============================================================================
# v3.7.0-E4: BILLING + COST SENSORS
# ============================================================================


class EnergyCoordCostTodaySensor(AggregationEntity, SensorEntity):
    """Net energy cost today (coordinator-level).

    Entity: sensor.ura_energy_cost_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:cash"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_cost_today"
        self._attr_name = "Energy Cost Today"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.cost_today

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.billing_status
        return {
            "import_kwh": status.get("import_kwh_today"),
            "import_cost": status.get("import_cost_today"),
            "export_kwh": status.get("export_kwh_today"),
            "export_credit": status.get("export_credit_today"),
        }


class EnergyCostCycleSensor(AggregationEntity, SensorEntity):
    """Cost so far in billing cycle.

    Entity: sensor.ura_energy_cost_this_cycle
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_cost_this_cycle"
        self._attr_name = "Energy Cost This Cycle"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.cost_this_cycle

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.billing_status
        return {
            "days_in_cycle": status.get("days_in_cycle"),
            "cycle_start_date": status.get("cycle_start_date"),
            "import_kwh_cycle": status.get("import_kwh_cycle"),
            "export_kwh_cycle": status.get("export_kwh_cycle"),
        }


class EnergyPredictedBillSensor(AggregationEntity, SensorEntity):
    """Predicted monthly bill (available after 7 days in cycle).

    Entity: sensor.ura_energy_predicted_bill
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:receipt-text"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_predicted_bill"
        self._attr_name = "Predicted Bill"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.predicted_bill

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        billing = energy.billing_status
        attrs = {}
        label = billing.get("prediction_label") if billing else None
        if label:
            attrs["status"] = label
        if billing:
            attrs["days_in_cycle"] = billing.get("days_in_cycle", 0)
            attrs["cycle_start_date"] = billing.get("cycle_start_date", "")
        return attrs or None


class EnergyCurrentRateSensor(AggregationEntity, SensorEntity):
    """Current effective import rate.

    Entity: sensor.ura_energy_current_rate
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:currency-usd"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_current_rate"
        self._attr_name = "Actual Energy Rate"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return round(energy.current_effective_rate, 6)


class EnergyDeliveryRateSensor(AggregationEntity, SensorEntity):
    """Delivery + transmission rate per kWh (non-commodity charges).

    Entity: sensor.ura_energy_delivery_rate
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:truck-delivery"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_delivery_rate"
        self._attr_name = "Delivery Rate"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return round(energy.delivery_rate, 6)


class EnergyImportTodaySensor(AggregationEntity, SensorEntity):
    """Import kWh today.

    Entity: sensor.ura_energy_import_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:transmission-tower-import"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_import_today"
        self._attr_name = "Energy Import Today"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.billing_status.get("import_kwh_today")

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return {"cost": energy.billing_status.get("import_cost_today")}


class EnergyExportTodaySensor(AggregationEntity, SensorEntity):
    """Export kWh today.

    Entity: sensor.ura_energy_export_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:transmission-tower-export"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_export_today"
        self._attr_name = "Energy Export Today"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.billing_status.get("export_kwh_today")

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return {"credit": energy.billing_status.get("export_credit_today")}


# ============================================================================
# v3.7.0-E5: FORECAST SENSORS
# ============================================================================


class EnergyForecastTodaySensor(AggregationEntity, SensorEntity):
    """Predicted net energy today (positive=export, negative=import).

    Entity: sensor.ura_energy_forecast_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-line"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_forecast_today"
        self._attr_name = "Energy Forecast Today"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.forecast_today.get("predicted_net_kwh")

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.forecast_today


class EnergyBatteryFullTimeSensor(AggregationEntity, SensorEntity):
    """Estimated time battery reaches 100%.

    Entity: sensor.ura_energy_battery_full_time
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-clock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_battery_full_time"
        self._attr_name = "Battery Full Time"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.battery_full_time


class EnergyForecastAccuracySensor(AggregationEntity, SensorEntity):
    """Forecast accuracy (7-day rolling %).

    Entity: sensor.ura_energy_forecast_accuracy
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:target"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_forecast_accuracy"
        self._attr_name = "Forecast Accuracy"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        accuracy = energy.forecast_accuracy
        return accuracy if accuracy > 0 else None


# ============================================================================
# v3.7.0-E6: SITUATION + CONSTRAINT SENSORS
# ============================================================================


class EnergySituationSensor(AggregationEntity, SensorEntity):
    """Overall energy situation.

    Entity: sensor.ura_energy_situation
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_situation"
        self._attr_name = "Energy Situation"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.energy_situation


class EnergyHVACConstraintSensor(AggregationEntity, SensorEntity):
    """Current HVAC constraint mode for future HVAC coordinator.

    Entity: sensor.ura_hvac_constraint
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_constraint"
        self._attr_name = "HVAC Constraint"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "normal"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "normal"
        return energy.hvac_constraint.get("mode", "normal")

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.hvac_constraint


# ============================================================================
# v3.7.7: CONSUMPTION + EV MONITORING SENSORS
# ============================================================================


class EnergyTotalConsumptionSensor(AggregationEntity, SensorEntity):
    """Total home consumption from Envoy CT clamp (ground truth).

    Entity: sensor.ura_energy_total_consumption
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kW"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_total_consumption"
        self._attr_name = "Total Consumption"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.total_consumption_kw


class EnergyNetConsumptionSensor(AggregationEntity, SensorEntity):
    """Net consumption (positive=importing from grid, negative=exporting).

    Entity: sensor.ura_energy_net_consumption
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:transmission-tower"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kW"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_net_consumption"
        self._attr_name = "Net Consumption"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.net_consumption_kw


class EnergyEVChargeRateASensor(AggregationEntity, SensorEntity):
    """EVSE Garage A charge rate in watts.

    Entity: sensor.ura_energy_ev_charge_rate_garage_a
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-station"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_suggested_display_precision = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_ev_charge_rate_garage_a"
        self._attr_name = "EV Charge Rate Garage A"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.evse_garage_a_power


class EnergyEVChargeRateBSensor(AggregationEntity, SensorEntity):
    """EVSE Garage B charge rate in watts.

    Entity: sensor.ura_energy_ev_charge_rate_garage_b
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-station"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_suggested_display_precision = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_ev_charge_rate_garage_b"
        self._attr_name = "EV Charge Rate Garage B"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.evse_garage_b_power


# ============================================================================
# v3.8.0-H1: HVAC COORDINATOR SENSORS
# ============================================================================


def _hvac_device_info():
    """Return device info for HVAC Coordinator sensors."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "hvac_coordinator")},
        name="URA: HVAC Coordinator",
        manufacturer="Universal Room Automation",
        model="HVAC Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class HVACModeSensor(AggregationEntity, SensorEntity):
    """HVAC operating mode.

    Entity: sensor.ura_hvac_coordinator_mode
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_mode"
        self._attr_name = "Mode"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.get_mode()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.get_mode_attrs()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HVACZoneStatusSensor(AggregationEntity, SensorEntity):
    """Per-zone HVAC status.

    Entity: sensor.ura_hvac_coordinator_zone_{n}_status
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, zone_id: str
    ) -> None:
        super().__init__(hass, entry)
        self._zone_id = zone_id
        zone_num = zone_id.split("_")[-1] if "_" in zone_id else zone_id
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_{zone_id}_status"
        self._attr_name = f"Zone {zone_num} Status"
        self._attr_icon = "mdi:thermostat"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unavailable"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        zone = hvac.zone_manager.zones.get(self._zone_id)
        if zone is None:
            return "unknown"
        return zone.hvac_mode or "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.zone_manager.get_zone_status_attrs(self._zone_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HVACAnomalySensor(AggregationEntity, SensorEntity):
    """HVAC anomaly status.

    Entity: sensor.ura_hvac_coordinator_anomaly
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_anomaly"
        self._attr_name = "HVAC Anomaly"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.get_anomaly_status()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        if hvac.anomaly_detector is None:
            return {}
        return hvac.anomaly_detector.get_status_summary()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HVACComplianceSensor(AggregationEntity, SensorEntity):
    """HVAC compliance rate.

    Entity: sensor.ura_hvac_coordinator_compliance
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-decagram"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_compliance"
        self._attr_name = "HVAC Compliance"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        summary = hvac.get_compliance_summary()
        return str(summary.get("overrides_today", 0))

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.get_compliance_summary()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HVACOverrideFrequencySensor(AggregationEntity, SensorEntity):
    """HVAC override frequency — tracks overrides and AC resets today.

    Entity: sensor.ura_hvac_coordinator_override_frequency
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-octagon"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_override_frequency"
        self._attr_name = "HVAC Override Frequency"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        status = hvac.override_arrester.get_override_status()
        return str(status.get("overrides_today", 0))

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.override_arrester.get_override_status()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HVACPreCoolLikelihoodSensor(AggregationEntity, SensorEntity):
    """HVAC pre-cool likelihood percentage.

    Entity: sensor.ura_hvac_coordinator_pre_cool_likelihood
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:snowflake-alert"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_pre_cool_likelihood"
        self._attr_name = "HVAC Pre-Cool Likelihood"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> int:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return 0
        return hvac.predictor.pre_cool_likelihood

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.predictor.get_prediction_attrs()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HVACComfortRiskSensor(AggregationEntity, SensorEntity):
    """HVAC comfort violation risk level.

    Entity: sensor.ura_hvac_coordinator_comfort_risk
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_comfort_risk"
        self._attr_name = "HVAC Comfort Risk"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.predictor.comfort_violation_risk

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.predictor.get_outcome_attrs()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


# ============================================================================
# v3.9.0-E6: ENERGY TRANSPARENCY SENSORS
# ============================================================================


class EnergyBatteryDecisionSensor(AggregationEntity, SensorEntity):
    """Last battery strategy decision and reason.

    Entity: sensor.ura_energy_battery_decision
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_battery_decision"
        self._attr_name = "Battery Decision"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "disabled"
        decision = energy.battery_decision_status
        return decision.get("mode", "unknown") if decision else "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.battery_decision_status or {}
        # Filter internal actions list — not useful as sensor attributes
        return {k: v for k, v in status.items() if k != "actions"}


class EnergyLoadSheddingSensor(AggregationEntity, SensorEntity):
    """Load shedding status — active level and shed loads.

    Entity: sensor.ura_energy_load_shedding
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:power-plug-off"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_load_shedding"
        self._attr_name = "Load Shedding"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "disabled"
        status = energy.load_shedding_status
        if not status.get("enabled"):
            return "disabled"
        if status.get("active"):
            return f"level_{status['level']}"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.load_shedding_status


# ============================================================================
# v3.9.0: HVAC TRANSPARENCY SENSORS
# ============================================================================


class HVACArresterStateSensor(AggregationEntity, SensorEntity):
    """Override arrester state — idle, grace_period, compromise, reverting, disabled.

    Entity: sensor.ura_hvac_arrester_state
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_arrester_state"
        self._attr_name = "Override Arrester State"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.override_arrester.get_arrester_state()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.override_arrester.get_arrester_detail()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HVACZonePresetSensor(AggregationEntity, SensorEntity):
    """Per-zone preset diagnostic — shows current target preset and setpoints.

    Entity: sensor.ura_hvac_zone_preset_{zone_id}
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermostat-box"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone_id: str) -> None:
        super().__init__(hass, entry)
        self._zone_id = zone_id
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_preset_{zone_id}"
        self._attr_name = f"HVAC Zone Preset {zone_id.replace('_', ' ').title()}"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        zone = hvac.zone_manager.zones.get(self._zone_id)
        if zone is None:
            return "unknown"
        return zone.preset_mode or "none"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        zone = hvac.zone_manager.zones.get(self._zone_id)
        if zone is None:
            return {}
        attrs = {
            "zone_name": zone.zone_name,
            "climate_entity": zone.climate_entity,
            "preset_mode": zone.preset_mode,
            "target_temp_high": zone.target_temp_high,
            "target_temp_low": zone.target_temp_low,
            "current_temperature": zone.current_temperature,
            "hvac_mode": zone.hvac_mode,
            "hvac_action": zone.hvac_action,
            "overrides_today": zone.override_count_today,
            "ac_resets_today": zone.ac_reset_count_today,
        }
        if zone.last_override_direction:
            attrs["last_override_direction"] = zone.last_override_direction
        # Add seasonal preset target from PresetManager
        season = hvac.preset_manager.current_season
        if season:
            attrs["season"] = season
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

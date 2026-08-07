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

from __future__ import annotations

import asyncio
import logging
import time
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
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    NAME,
    VERSION,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,
    ENTRY_TYPE_ZONE_MANAGER,
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
    CONF_WHOLE_HOUSE_POWER_SENSORS,
    CONF_WHOLE_HOUSE_ENERGY_SENSORS,
    CONF_HOUSE_DEVICE_POWER_SENSORS,
    CONF_HOUSE_DEVICE_ENERGY_SENSORS,
    CONF_ZONE_POWER_SENSORS,
    CONF_ZONE_ENERGY_SENSORS,
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
    COVERAGE_RATING_ANOMALOUS,
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
    # v3.5.1: Zone aggregation sensor keys
    SENSOR_ZONE_IDENTIFIED_PERSONS,
    SENSOR_ZONE_GUEST_COUNT,
    # v4.6.12: Dashboard aggregator sensors
    ZONE_MOTION_WINDOW_SECONDS,
)
from .coordinator import UniversalRoomCoordinator
from .domain_coordinators.energy_billing import _get_effective_rate_kwh
from .domain_coordinators._units import (
    energy_state_to_kwh,
    power_state_to_w,
    today_delta_kwh,
)

_LOGGER = logging.getLogger(__name__)

# v4.7.13 fix-up MEDIUM-2 (interim): Track zones for which the sleep-state
# person fallback was unavailable so we WARN at most once per boot per zone.
# Module-level intentionally: cleared on HA process restart, persists across
# coordinator reloads within a single boot.
# v4.7.15 D2: cache key widened from str to (zone_id, scope) so SLEEP and
# non-sleep fallback unavailability don't dedup-mask each other.
_SLEEP_FALLBACK_WARNED_ZONES: set[tuple[str, str]] = set()

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
        WholeHouseCostTodaySensor(hass, entry),
        RoomsEnergyTotalSensor(hass, entry),
        EnergyCoverageDeltaSensor(hass, entry),

        # === ENERGY PREDICTIONS ===
        PredictedEnergyTodaySensor(hass, entry),
        PredictedEnergyTomorrowSensor(hass, entry),  # 2026-07-27: additive display-only forecast
        PredictedEnergyWeekSensor(hass, entry),
        PredictedEnergyMonthSensor(hass, entry),
        PredictedCostTodaySensor(hass, entry),
        PredictedCostTomorrowSensor(hass, entry),  # 2026-07-27: trivial mirror of cost-today
        PredictedCostWeekSensor(hass, entry),
        PredictedCostMonthSensor(hass, entry),

        # === v4.2.0 B4 L3: ENERGY INTELLIGENCE ===
        EnergyWasteIdleSensor(hass, entry),
        EnergyCostPerOccupiedHourSensor(hass, entry),
        MostExpensiveCircuitSensor(hass, entry),
        OptimizationPotentialSensor(hass, entry),

        # === v4.6.12 Cycle B: DASHBOARD AGGREGATOR SENSORS ===
        ZoneMotionEventCountSensor(hass, entry),
        HouseSystemDemandSensor(hass, entry),
        EnergyGridDemandSensor(hass, entry),
    ]

    # === v3.2.0: INTEGRATION PERSON LOCATION SENSORS ===
    person_coordinator = hass.data[DOMAIN].get("person_coordinator")
    _LOGGER.warning(
        "PERSON SENSOR DIAGNOSTIC: person_coordinator=%s, "
        "entry.data CONF_TRACKED_PERSONS=%s",
        "FOUND" if person_coordinator else "NONE",
        entry.data.get(CONF_TRACKED_PERSONS, "NOT_IN_DATA"),
    )
    if person_coordinator:
        tracked_persons = entry.data.get(CONF_TRACKED_PERSONS, [])
        _LOGGER.warning(
            "PERSON SENSOR DIAGNOSTIC: creating sensors for %d persons: %s",
            len(tracked_persons), tracked_persons,
        )
        for person_entity_id in tracked_persons:
            person_id = person_entity_id.split('.')[-1]  # person.oji -> oji
            entities.extend([
                PersonLocationSensor(hass, entry, person_id),
                PersonPreviousLocationSensor(hass, entry, person_id),
                PersonPreviousSeenSensor(hass, entry, person_id),
            ])

            # v3.3.0: Pattern learning sensors
            # v4.6.2: D5 routine_status sensors co-located here for symmetry
            # with v4.6.0 accuracy sensors — both bind to CM device but
            # register via the Integration entry's aggregation setup.
            from .sensor import (
                PersonLikelyNextRoomSensor,
                PersonCurrentPathSensor,
                PersonNextRoomAccuracySensor,
                PersonRoutineStatusSensor,
            )
            entities.extend([
                PersonLikelyNextRoomSensor(hass, entry, person_id),
                PersonCurrentPathSensor(hass, entry, person_id),
                # v4.6.0: D4 — per-person next-room accuracy sensor
                PersonNextRoomAccuracySensor(hass, entry, person_id),
                # v4.6.2: D5 — per-person routine status sensor
                PersonRoutineStatusSensor(hass, entry, person_id),
            ])

    # v4.6.0: D5 — single house-aggregate next-room accuracy sensor
    # v4.6.2: D5 — single house-aggregate routine status sensor (same site)
    from .sensor import HouseNextRoomAccuracySensor, HouseRoutineStatusSensor
    entities.append(HouseNextRoomAccuracySensor(hass, entry))
    entities.append(HouseRoutineStatusSensor(hass, entry))

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
        # v4.2.0 B4 L3: Energy anomaly detection
        EnergyAnomalyBinarySensor(hass, entry),
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
        ZoneEnergyCostTodaySensor(hass, entry, zone_name),
        ZoneCostPerHourSensor(hass, entry, zone_name),

        # === PERSON TRACKING ===
        ZoneCurrentOccupantsSensor(hass, entry, zone_name),
        ZoneOccupantCountSensor(hass, entry, zone_name),
        ZoneLastOccupantSensor(hass, entry, zone_name),
        ZoneLastOccupantTimeSensor(hass, entry, zone_name),
        ZonePersonTrackingStatusSensor(hass, entry, zone_name),

        # === v3.5.1: CENSUS-BASED ZONE PERSON SENSORS (disabled by default) ===
        ZoneIdentifiedPersonsSensor(hass, entry, zone_name),
        ZoneGuestCountSensor(hass, entry, zone_name),
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


async def async_setup_zone_manager_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone sensors for ALL zones via the Zone Manager entry (v3.6.0).

    Replaces the per-zone-entry approach. Reads zone names from the Zone Manager
    entry data and creates sensors for each zone, all registered under the
    Zone Manager config entry so they appear grouped together in the UI.
    """
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE_MANAGER:
        return

    merged = {**entry.data, **entry.options}
    zones_data = merged.get("zones", {})

    if not zones_data:
        _LOGGER.info("Zone Manager: no zones configured, skipping sensor setup")
        return

    entities: list[SensorEntity] = []
    for zone_name in zones_data:
        entities.extend([
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
            ZoneEnergyCostTodaySensor(hass, entry, zone_name),
            ZoneCostPerHourSensor(hass, entry, zone_name),
            # === PERSON TRACKING ===
            ZoneCurrentOccupantsSensor(hass, entry, zone_name),
            ZoneOccupantCountSensor(hass, entry, zone_name),
            ZoneLastOccupantSensor(hass, entry, zone_name),
            ZoneLastOccupantTimeSensor(hass, entry, zone_name),
            ZonePersonTrackingStatusSensor(hass, entry, zone_name),
            # === CENSUS-BASED (disabled by default) ===
            ZoneIdentifiedPersonsSensor(hass, entry, zone_name),
            ZoneGuestCountSensor(hass, entry, zone_name),
            # === v3.6.0-c1: PRESENCE ===
            ZonePresenceStatusSensor(hass, entry, zone_name),
        ])

    async_add_entities(entities)
    _LOGGER.info(
        "Zone Manager: set up %d sensors for %d zones: %s",
        len(entities), len(zones_data), list(zones_data.keys()),
    )


async def async_setup_zone_manager_binary_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone binary sensors for ALL zones via the Zone Manager entry (v3.6.0)."""
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE_MANAGER:
        return

    merged = {**entry.data, **entry.options}
    zones_data = merged.get("zones", {})

    if not zones_data:
        return

    entities: list[BinarySensorEntity] = []
    for zone_name in zones_data:
        entities.append(ZoneAnyoneBinarySensor(hass, entry, zone_name))

    async_add_entities(entities)
    _LOGGER.info(
        "Zone Manager: set up %d binary sensors for %d zones",
        len(entities), len(zones_data),
    )


def _get_all_zones(hass: HomeAssistant, entry: ConfigEntry | None = None) -> set[str]:
    """Get all unique zones from room entries, zone entries, and zone manager."""
    zones = set()

    # Get zones from room entries
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if isinstance(data, UniversalRoomCoordinator):
            zone = data.entry.data.get(CONF_ZONE) or data.entry.options.get(CONF_ZONE)
            if zone:
                zones.add(zone)

    # Get zones from Zone Manager entry (v3.6.0)
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
            merged = {**config_entry.data, **config_entry.options}
            for zone_name in merged.get("zones", {}):
                zones.add(zone_name)

    # Get zones from legacy zone entries (backward compat)
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


_COVERAGE_RATING_ANOMALOUS_LAST_WARN: float = 0.0


def _get_coverage_rating(
    delta_percent: float | None,
    *,
    post_restart_window: bool = False,
) -> str:
    """Get coverage rating from delta percentage.

    D3: Bounds guard. Pre-fix the function was sign-blind — a hugely
    negative delta_percent (observed: −24,558,907,924%) fell through
    every < check and returned EXCELLENT. Return ANOMALOUS for None,
    NaN, ``< -2``, or ``> 100`` inputs and rate-limit a WARNING.

    Fix-up pass C-M2 (epsilon band): small negative values in [-2, 0)
    are timing skew between tiers and treated as 0 (EXCELLENT) rather
    than ANOMALOUS — Anomalous requires a clearly out-of-bounds reading.

    Fix-up pass B-H4 (post-restart asymmetry): when ``post_restart_window``
    is true, the rooms tier is full-day (DB-persisted) while in-memory
    tiers re-anchored mid-day → delta_percent goes negative for the
    rest of the day. Surface that as INCOMPLETE (not ANOMALOUS) and
    swap the WARNING text to name boot-time re-anchoring instead of
    misattributing to unit drift.
    """
    global _COVERAGE_RATING_ANOMALOUS_LAST_WARN
    # Epsilon band first (positive bias only — clearly out-of-bounds is
    # still ANOMALOUS even in the post-restart window).
    if (
        isinstance(delta_percent, (int, float))
        and delta_percent == delta_percent  # not NaN
        and -2.0 <= delta_percent < 0.0
    ):
        return COVERAGE_RATING_EXCELLENT
    out_of_bounds = (
        delta_percent is None
        or not isinstance(delta_percent, (int, float))
        or delta_percent != delta_percent  # NaN
        or delta_percent < 0
        or delta_percent > 100
    )
    if out_of_bounds:
        # Post-restart asymmetry path: negative deltas in the boot-window
        # are expected and DO NOT indicate unit-of-measurement drift.
        if (
            post_restart_window
            and isinstance(delta_percent, (int, float))
            and delta_percent == delta_percent
            and delta_percent < 0
        ):
            try:
                _now_mono = time.monotonic()
                if _now_mono - _COVERAGE_RATING_ANOMALOUS_LAST_WARN >= 3600.0:
                    _COVERAGE_RATING_ANOMALOUS_LAST_WARN = _now_mono
                    _LOGGER.warning(
                        "Coverage rating: delta_percent=%s negative inside "
                        "post-restart window — in-memory tiers re-anchored at "
                        "boot while rooms tier carries the full-day persisted "
                        "value. Returning INCOMPLETE; will converge at next "
                        "midnight re-anchor.",
                        delta_percent,
                    )
            except Exception:
                pass
            return COVERAGE_RATING_INCOMPLETE
        try:
            _now_mono = time.monotonic()
            if _now_mono - _COVERAGE_RATING_ANOMALOUS_LAST_WARN >= 3600.0:
                _COVERAGE_RATING_ANOMALOUS_LAST_WARN = _now_mono
                _LOGGER.warning(
                    "Coverage rating: delta_percent=%s out of bounds; "
                    "returning ANOMALOUS. Likely unit-of-measurement mismatch "
                    "between attributed tiers and whole-house tier "
                    "(Bug Class #30).",
                    delta_percent,
                )
        except Exception:
            pass
        return COVERAGE_RATING_ANOMALOUS
    if delta_percent < COVERAGE_EXCELLENT_THRESHOLD:
        return COVERAGE_RATING_EXCELLENT
    elif delta_percent < COVERAGE_GOOD_THRESHOLD:
        return COVERAGE_RATING_GOOD
    elif delta_percent < COVERAGE_FAIR_THRESHOLD:
        return COVERAGE_RATING_FAIR
    else:
        return COVERAGE_RATING_INCOMPLETE


# v4.6.10 D5a: Module-level constant for person state values that should not
# be seeded into the coordinator as real room names.  Replaces two inline
# _SKIP_STATES assignments in PersonPreviousLocationSensor and
# PersonPreviousSeenSensor (v4.6.9 review LOW finding).
_PERSON_LAST_STATE_SKIP_VALUES: frozenset[str] = frozenset({
    "unknown", "unavailable", "Unknown", "Unavailable",
    "None", "none", "away", "Away", "",
    "not_home", "Not_home", "home", "Home",
})


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
                self.async_schedule_update_ha_state()
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
    
    # ------------------------------------------------------------------
    # Weather forecast (2026-07-27): the `weather.forecast` state attribute
    # was removed in HA 2024.4. Source daily highs from the
    # `weather.get_forecasts` service instead. Fetch is cached on
    # hass.data[DOMAIN]["_forecast_cache"] with a 15-min TTL so the six
    # predicted-* sensors don't storm the weather integration on every read.
    # ------------------------------------------------------------------
    FORECAST_CACHE_TTL_S = 900

    async def _refresh_forecast_cache(self) -> None:
        """Fetch daily forecast via weather.get_forecasts, cache on hass.data.

        Idempotent: no-op if the cached entry is fresh (<15 min). Safe on
        service failure — leaves any stale cache in place; callers fall back
        to the weather entity's current-temperature attribute.
        """
        weather_entity = self._get_config(CONF_WEATHER_ENTITY)
        if not weather_entity:
            return
        cache = self.hass.data.setdefault(DOMAIN, {}).get("_forecast_cache")
        now = dt_util.utcnow()
        if (
            cache
            and cache.get("entity") == weather_entity
            and (now - cache["time"]).total_seconds() < self.FORECAST_CACHE_TTL_S
        ):
            return
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": "daily"},
                target={"entity_id": weather_entity},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 — service can raise many types
            _LOGGER.debug("weather.get_forecasts failed for %s: %s", weather_entity, err)
            return
        forecast: list = []
        try:
            forecast = (response or {}).get(weather_entity, {}).get("forecast", []) or []
        except Exception:  # noqa: BLE001
            forecast = []
        self.hass.data.setdefault(DOMAIN, {})["_forecast_cache"] = {
            "time": now,
            "entity": weather_entity,
            "forecast": forecast,
        }
        _LOGGER.info(
            "Refreshed weather forecast cache for %s: %d days",
            weather_entity,
            len(forecast),
        )

    def _get_forecast_temp(self, day_offset: int = 0, field: str = "temperature") -> float | None:
        """Return forecast temperature for the given day offset.

        day_offset=0 -> today's high, day_offset=1 -> tomorrow's high, etc.
        Reads from the cached weather.get_forecasts response
        (see _refresh_forecast_cache). Fallback chain when the service
        returned no data or the requested offset is missing:
          cached forecast[0]['<field>']
          -> weather entity's current `attributes.temperature`
          -> None
        Never returns None when the weather entity has a current temp.
        """
        weather_entity = self._get_config(CONF_WEATHER_ENTITY)
        if not weather_entity:
            return None
        cache = self.hass.data.get(DOMAIN, {}).get("_forecast_cache") or {}
        forecast = cache.get("forecast") or []
        if forecast and len(forecast) > day_offset:
            val = forecast[day_offset].get(field)
            if val is not None:
                return val
        if forecast:
            val = forecast[0].get(field)
            if val is not None:
                return val
        # Fallback: current temp attribute (only meaningful for the
        # temperature field; templow has no analogue on the state itself).
        if field == "temperature":
            try:
                state = self.hass.states.get(weather_entity)
                if state:
                    return state.attributes.get("temperature")
            except Exception:  # noqa: BLE001
                return None
        return None

    def _get_forecast_temp_tomorrow(self) -> float | None:
        """Backwards-compat thin wrapper -> _get_forecast_temp(1)."""
        return self._get_forecast_temp(1)


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
        """Return room list and per-zone breakdown."""
        rooms = []
        # v4.6.11 D4.2: per_zone_breakdown — zone → occupied room count.
        # Reads CONF_ZONE from entry.options first then entry.data (Bug Class #14).
        zone_breakdown: dict[str, int] = {}
        for coord in _get_room_coordinators(self.hass):
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                rooms.append(coord.entry.data.get("room_name", "Unknown"))
                try:
                    zone = coord.entry.options.get(CONF_ZONE) or coord.entry.data.get(CONF_ZONE, "unassigned")
                    zone_breakdown[zone] = zone_breakdown.get(zone, 0) + 1
                except Exception:
                    pass
        return {
            "rooms": rooms,
            "per_zone_breakdown": zone_breakdown,
        }


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
            # v5.38.1: presence-aware read — an `or`-chain treats the
            # clear-checkbox's explicit '' options override as absent and
            # falls through to the stale data value, defeating the clear.
            if CONF_WATER_LEAK_SENSOR in coord.entry.options:
                leak_sensor = coord.entry.options[CONF_WATER_LEAK_SENSOR]
            else:
                leak_sensor = coord.entry.data.get(CONF_WATER_LEAK_SENSOR)
            if leak_sensor:
                state = self.hass.states.get(leak_sensor)
                if state and state.state == "on":
                    alerts.append({"room": room_name, "type": "water_leak", "sensor": leak_sensor, "issue": "leak_detected"})
        
        return alerts
    
    async def _process_alerts(self, alerts: list[dict]) -> None:
        """Process alerts - send notifications and flash lights."""
        if not alerts:
            return

        # v3.6.0.3: When domain coordinators are active, Safety Coordinator
        # owns alert response. Skip legacy light flashing.
        if self.hass.data.get(DOMAIN, {}).get("coordinator_manager") is not None:
            return

        # Debounce: don't alert more than once per minute
        now = dt_util.now()  # v4.2.27: tz-aware (HA convention)
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
        now = dt_util.now()  # v4.2.27: tz-aware (HA convention)
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

    async def async_update(self) -> None:
        """Refresh cached weather forecast (see _refresh_forecast_cache)."""
        await self._refresh_forecast_cache()

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

    async def async_update(self) -> None:
        """Refresh cached weather forecast (see _refresh_forecast_cache)."""
        await self._refresh_forecast_cache()

    @property
    def native_value(self) -> float | None:
        """Return predicted kWh equivalent for heating.

        Sources tomorrow's forecast low (templow) from the cached
        weather.get_forecasts response (see _refresh_forecast_cache).
        """
        forecast_low = self._get_forecast_temp(day_offset=0, field="templow")
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

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_schedule_update_ha_state()

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
        """Return predicted kWh value.

        B4 live-health repair (2026-06-10): `db.predict_energy()` returns
        `net_energy = grid_import - solar_export` (see database.py
        get_energy_for_similar_days), which is legitimately negative on
        solar-rich days when export > import. The producer is correct —
        the sensor's display semantic is the GROSS consumer-facing forecast,
        so we surface `max(net, 0)` here and expose the signed raw net in
        the `raw_net_kwh` attribute. Not a blind clamp: the underlying
        method/source is unchanged; only the consumer-facing display is
        adjusted to match the sensor name ("Predicted Energy Today"). Cost
        is unaffected (PredictedCostTodaySensor.async_update applies the
        export-credit branch when energy_kwh < 0).
        """
        # Use cached value if recent (predictions are expensive)
        if self._cached_value is not None and self._cache_time:
            return max(self._cached_value, 0.0)

        # Return None if no data yet
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details.

        B4 repair: expose `raw_net_kwh` (signed net = grid_import -
        solar_export) so anyone needing the export-aware figure has it,
        without poisoning the gross display.
        """
        attrs = {
            "value": (
                max(self._cached_value, 0.0)
                if self._cached_value is not None
                else None
            ),
            "raw_net_kwh": self._cached_value,
            "unit": "kWh",
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "today",
            "method": "historical_pattern",
            "last_updated": self._cache_time.isoformat() if self._cache_time else None,
        }

        # Add friendly display text
        if self._cached_value is not None:
            display_val = max(self._cached_value, 0.0)
            attrs["display"] = f"{display_val} kWh ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."

        return attrs

    async def async_update(self) -> None:
        """Update prediction from database."""
        # Check if database is available
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return

        # Only update every 15 minutes — v4.2.27: tz-aware (HA convention)
        now = dt_util.now()
        if self._cache_time and (now - self._cache_time).total_seconds() < 900:
            return

        await self._refresh_forecast_cache()
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
        """Return predicted kWh value.

        B4 review A-M1 / B-M2 (2026-06-10): apply the same `max(net, 0)`
        clamp as PredictedEnergyTodaySensor for family consistency. Signed
        raw value is exposed via the `raw_net_kwh` attribute.
        """
        if self._cached_value is None:
            return None
        return max(self._cached_value, 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details.

        B4 review A-M1 / B-M2: expose `raw_net_kwh` (signed net) so the
        export-aware figure is available without poisoning the gross display.
        """
        attrs = {
            "value": (
                max(self._cached_value, 0.0)
                if self._cached_value is not None
                else None
            ),
            "raw_net_kwh": self._cached_value,
            "unit": "kWh",
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "week",
        }

        # Add friendly display text
        if self._cached_value is not None:
            display_val = max(self._cached_value, 0.0)
            attrs["display"] = f"{display_val} kWh ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."

        return attrs

    async def async_update(self) -> None:
        """Update prediction from database. v4.2.27: was missing — sensor stayed at None forever."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        # Cache for 60 minutes (week predictions don't move fast)
        now = dt_util.now()  # v4.2.27: tz-aware (HA convention)
        if self._cache_time and (now - self._cache_time).total_seconds() < 3600:
            return
        await self._refresh_forecast_cache()
        forecast_temp = self._get_forecast_temp()
        value, confidence = await db.predict_energy("week", forecast_temp)
        self._cached_value = value
        self._cached_confidence = confidence
        self._cache_time = now


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
        self._cache_time: datetime | None = None

    @property
    def native_value(self) -> float | None:
        """Return predicted kWh value.

        B4 review A-M1 / B-M2 (2026-06-10): apply the same `max(net, 0)`
        clamp as PredictedEnergyTodaySensor for family consistency. Signed
        raw value is exposed via the `raw_net_kwh` attribute.
        """
        if self._cached_value is None:
            return None
        return max(self._cached_value, 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details.

        B4 review A-M1 / B-M2: expose `raw_net_kwh` (signed net) so the
        export-aware figure is available without poisoning the gross display.
        """
        attrs = {
            "value": (
                max(self._cached_value, 0.0)
                if self._cached_value is not None
                else None
            ),
            "raw_net_kwh": self._cached_value,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "month",
        }

        # Add friendly display text
        if self._cached_value is not None:
            display_val = max(self._cached_value, 0.0)
            attrs["display"] = f"{display_val} kWh ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."

        return attrs

    async def async_update(self) -> None:
        """Update prediction from database. v4.2.27: was missing — sensor stayed at None forever."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        # Cache for 6 hours (month predictions are slow-moving)
        now = dt_util.now()  # v4.2.27: tz-aware (HA convention)
        if self._cache_time and (now - self._cache_time).total_seconds() < 21600:
            return
        await self._refresh_forecast_cache()
        forecast_temp = self._get_forecast_temp()
        value, confidence = await db.predict_energy("month", forecast_temp)
        self._cached_value = value
        self._cached_confidence = confidence
        self._cache_time = now


class PredictedEnergyTomorrowSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted net energy for tomorrow.

    Additive display-only forecast sensor (2026-07-27) feeding the dashboard
    "Net Tomorrow" tile (solar forecast - expected consumption). Mirrors
    PredictedEnergyTodaySensor exactly (same clamp, same raw_net_kwh attr,
    same 15-min cache) but calls db.predict_energy("tomorrow", tomorrow_temp)
    where the "tomorrow" period keys similar-day lookup on tomorrow's weekday
    and tomorrow's forecast high temp (see database.predict_energy). No
    decision consumer reads this value.
    """

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:crystal-ball"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_energy_tomorrow"
        self._attr_name = "Predicted Energy Tomorrow"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
        self._cache_time: datetime | None = None
        self._cached_forecast_temp: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return predicted kWh value, clamped >=0 (gross consumer semantic).

        See PredictedEnergyTodaySensor.native_value docstring — same
        rationale (net can be negative on solar-rich days; display shows
        gross, signed value exposed via raw_net_kwh attribute).
        """
        if self._cached_value is None:
            return None
        return max(self._cached_value, 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details."""
        attrs = {
            "value": (
                max(self._cached_value, 0.0)
                if self._cached_value is not None
                else None
            ),
            "raw_net_kwh": self._cached_value,
            "unit": "kWh",
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "tomorrow",
            "method": "historical_pattern_tomorrow_weekday_and_forecast_temp",
            "forecast_temp_tomorrow": self._cached_forecast_temp,
            "last_updated": self._cache_time.isoformat() if self._cache_time else None,
        }
        if self._cached_value is not None:
            display_val = max(self._cached_value, 0.0)
            attrs["display"] = f"{display_val} kWh ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
        return attrs

    async def async_update(self) -> None:
        """Update prediction from database."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        # Cache 15 minutes (same cadence as Today sibling; tomorrow's forecast
        # can shift intraday as the weather integration refreshes).
        now = dt_util.now()
        if self._cache_time and (now - self._cache_time).total_seconds() < 900:
            return
        await self._refresh_forecast_cache()
        forecast_temp = self._get_forecast_temp_tomorrow()
        value, confidence = await db.predict_energy("tomorrow", forecast_temp)
        self._cached_value = value
        self._cached_confidence = confidence
        self._cached_forecast_temp = forecast_temp
        self._cache_time = now


class PredictedCostTomorrowSensor(AggregationEntity, SensorEntity):
    """Sensor: Predicted energy cost for tomorrow.

    Trivial mirror of PredictedCostTodaySensor — same rate/delivery/export
    pipeline, only difference is db.predict_energy("tomorrow", tomorrow_temp).
    Cost stays signed (negative cost = valid export credit)."""

    _attr_native_unit_of_measurement = "$"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-usd"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_predicted_cost_tomorrow"
        self._attr_name = "Predicted Cost Tomorrow"
        self._cached_value: float | None = None
        self._cached_confidence: int = 0
        self._cache_time: datetime | None = None
        self._cached_raw_net_kwh: float | None = None

    @property
    def native_value(self) -> float | None:
        return self._cached_value if self._cached_value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rate, rate_source = _get_effective_rate_kwh(self.hass)
        delivery = self._get_config(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
        export_rate = self._get_config(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)
        attrs = {
            "value": self._cached_value,
            "raw_net_kwh": self._cached_raw_net_kwh,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "electricity_rate": rate,
            "delivery_rate": delivery,
            "export_rate": export_rate,
            "period": "tomorrow",
            "rate_source": rate_source,
        }
        if self._cached_value is not None:
            attrs["display"] = f"${self._cached_value:.2f} ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."
        return attrs

    async def async_update(self) -> None:
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        now = dt_util.now()
        if self._cache_time and (now - self._cache_time).total_seconds() < 900:
            return
        await self._refresh_forecast_cache()
        forecast_temp = self._get_forecast_temp_tomorrow()
        energy_kwh, confidence = await db.predict_energy("tomorrow", forecast_temp)
        self._cached_raw_net_kwh = energy_kwh
        if energy_kwh is None:
            self._cached_value = None
        else:
            rate, _src = _get_effective_rate_kwh(self.hass)
            delivery = self._get_config(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
            export_rate = self._get_config(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)
            if energy_kwh >= 0:
                self._cached_value = round(energy_kwh * (rate + delivery), 2)
            else:
                self._cached_value = round(energy_kwh * export_rate, 2)
        self._cached_confidence = confidence
        self._cache_time = now


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
        self._cache_time: datetime | None = None
        # B4 live-health repair (2026-06-10): raw signed net kWh mirrored
        # from db.predict_energy() for symmetry with PredictedEnergyTodaySensor.
        self._cached_raw_net_kwh: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return predicted cost value.

        B4 live-health repair (2026-06-10): unlike PredictedEnergyTodaySensor
        the cost can legitimately be negative on solar-export days (export
        credit @ export_rate, applied below in async_update at the
        `energy_kwh < 0` branch). We do NOT clamp here; the upstream raw
        net kWh is exposed via the `raw_net_kwh` attribute for parity with
        the sibling energy sensor.
        """
        return self._cached_value if self._cached_value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return cost calculation details."""
        rate, rate_source = _get_effective_rate_kwh(self.hass)
        delivery = self._get_config(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
        export_rate = self._get_config(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)

        attrs = {
            "value": self._cached_value,
            "raw_net_kwh": self._cached_raw_net_kwh,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "electricity_rate": rate,
            "delivery_rate": delivery,
            "export_rate": export_rate,
            "period": "today",
            "rate_source": rate_source,
        }

        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"${self._cached_value:.2f} ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."

        return attrs

    async def async_update(self) -> None:
        """Update prediction from database. v4.2.27: was missing — sensor stayed at None forever.
        Cost = energy_kwh × (electricity_rate + delivery_rate) when net-import,
               energy_kwh × export_rate when net-export (negative kWh).
        v4.6.8: Uses TOU-aware EC rate via _get_effective_rate_kwh helper.

        B4 live-health repair (2026-06-10): also caches `raw_net_kwh` so the
        sibling PredictedEnergyTodaySensor's raw_net attribute is mirrored
        here for parity (cost itself is unchanged — negative cost is a valid
        export credit)."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        now = dt_util.now()  # v4.2.27: tz-aware (HA convention)
        if self._cache_time and (now - self._cache_time).total_seconds() < 900:
            return
        await self._refresh_forecast_cache()
        forecast_temp = self._get_forecast_temp()
        energy_kwh, confidence = await db.predict_energy("day", forecast_temp)
        self._cached_raw_net_kwh = energy_kwh
        if energy_kwh is None:
            self._cached_value = None
        else:
            rate, _src = _get_effective_rate_kwh(self.hass)
            delivery = self._get_config(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
            export_rate = self._get_config(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)
            if energy_kwh >= 0:
                self._cached_value = round(energy_kwh * (rate + delivery), 2)
            else:
                self._cached_value = round(energy_kwh * export_rate, 2)
        self._cached_confidence = confidence
        self._cache_time = now


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
        self._cache_time: datetime | None = None

    @property
    def native_value(self) -> float | None:
        """Return predicted cost value."""
        return self._cached_value if self._cached_value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        _rate, rate_source = _get_effective_rate_kwh(self.hass)
        attrs = {
            "value": self._cached_value,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "week",
            "rate_source": rate_source,
        }

        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"${self._cached_value:.2f} ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."

        return attrs

    async def async_update(self) -> None:
        """Update prediction from database. v4.2.27: was missing — sensor stayed at None forever.
        v4.6.8: Uses TOU-aware EC rate via _get_effective_rate_kwh helper."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        now = dt_util.now()  # v4.2.27: tz-aware (HA convention)
        if self._cache_time and (now - self._cache_time).total_seconds() < 3600:
            return
        await self._refresh_forecast_cache()
        forecast_temp = self._get_forecast_temp()
        energy_kwh, confidence = await db.predict_energy("week", forecast_temp)
        if energy_kwh is None:
            self._cached_value = None
        else:
            rate, _src = _get_effective_rate_kwh(self.hass)
            delivery = self._get_config(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
            export_rate = self._get_config(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)
            if energy_kwh >= 0:
                self._cached_value = round(energy_kwh * (rate + delivery), 2)
            else:
                self._cached_value = round(energy_kwh * export_rate, 2)
        self._cached_confidence = confidence
        self._cache_time = now


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
        self._cache_time: datetime | None = None

    @property
    def native_value(self) -> float | None:
        """Return predicted cost value."""
        return self._cached_value if self._cached_value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details."""
        _rate, rate_source = _get_effective_rate_kwh(self.hass)
        attrs = {
            "value": self._cached_value,
            "confidence": self._cached_confidence,
            "confidence_level": _get_confidence_level(self._cached_confidence),
            "period": "month",
            "rate_source": rate_source,
        }

        # Add friendly display text
        if self._cached_value is not None:
            attrs["display"] = f"${self._cached_value:.2f} ({_get_confidence_level(self._cached_confidence)})"
        else:
            attrs["display"] = "Collecting data..."

        return attrs

    async def async_update(self) -> None:
        """Update prediction from database. v4.2.27: was missing — sensor stayed at None forever.
        v4.6.8: Uses TOU-aware EC rate via _get_effective_rate_kwh helper."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        now = dt_util.now()  # v4.2.27: tz-aware (HA convention)
        if self._cache_time and (now - self._cache_time).total_seconds() < 21600:
            return
        await self._refresh_forecast_cache()
        forecast_temp = self._get_forecast_temp()
        energy_kwh, confidence = await db.predict_energy("month", forecast_temp)
        if energy_kwh is None:
            self._cached_value = None
        else:
            rate, _src = _get_effective_rate_kwh(self.hass)
            delivery = self._get_config(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
            export_rate = self._get_config(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)
            if energy_kwh >= 0:
                self._cached_value = round(energy_kwh * (rate + delivery), 2)
            else:
                self._cached_value = round(energy_kwh * export_rate, 2)
        self._cached_confidence = confidence
        self._cache_time = now


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
    
    def _get_sensor_list(self, plural_key, singular_key):
        """Get sensor list with singular→plural migration fallback."""
        sensors = self._get_config(plural_key)
        if sensors:
            return sensors if isinstance(sensors, list) else [sensors]
        singular = self._get_config(singular_key)
        if singular:
            return [singular]
        return []

    def _sum_sensors(self, sensor_ids: list[str]) -> float | None:
        """Sum power readings (Watts) from a list of sensor entity IDs.

        Bug Class #30 (power-surface sibling): every read routes through
        ``power_state_to_w`` so kW / W / MW sources normalize to Watts.
        Live trigger (2026-06-09): ``sensor.ura_whole_house_power``
        read 0.29 W while the house drew ~2.7 kW because the configured
        whole-house source was an Envoy sensor reporting in kW.
        """
        total = 0.0
        any_valid = False
        for sensor_id in sensor_ids:
            state = self.hass.states.get(sensor_id)
            try:
                watts = power_state_to_w(state)
            except Exception:
                watts = None
            if watts is None:
                continue
            total += watts
            any_valid = True
        return total if any_valid else None

    @property
    def native_value(self) -> float | None:
        """Return whole house power in Watts (sum of all configured sensors)."""
        sensors = self._get_sensor_list(
            CONF_WHOLE_HOUSE_POWER_SENSORS, CONF_WHOLE_HOUSE_POWER_SENSOR)
        if not sensors:
            return None
        return self._sum_sensors(sensors)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return source info."""
        sensors = self._get_sensor_list(
            CONF_WHOLE_HOUSE_POWER_SENSORS, CONF_WHOLE_HOUSE_POWER_SENSOR)
        # v4.6.11 D4.5: source_breakdown — solar_power_w from existing config key.
        # battery_power_w and grid_power_w return None this cycle; CONF_BATTERY_POWER_SENSOR
        # + CONF_GRID_POWER_SENSOR config keys are filed for v4.6.13.
        solar_power_w: float | None = None
        try:
            solar_sensor = self._get_config(CONF_SOLAR_PRODUCTION_SENSOR)
            if solar_sensor:
                state = self.hass.states.get(solar_sensor)
                solar_power_w = power_state_to_w(state)
        except Exception:
            pass
        return {
            "source_sensors": sensors,
            "sensor_count": len(sensors),
            "source_breakdown": {
                "solar_power_w": solar_power_w,
                "battery_power_w": None,
                "grid_power_w": None,
            },
        }


class WholeHouseEnergySensor(AggregationEntity, SensorEntity):
    """Sensor: Whole house energy today from configured sensor.

    Fix-up pass B-M2: this sensor now applies the same per-sensor scope
    heuristic + today-delta tracking used by ``EnergyCoverageDeltaSensor``
    so its native_value cannot disagree with the coverage sensor's
    ``whole_house`` attribute by orders of magnitude when a Wh-reporting
    cumulative counter is configured.
    """

    # Same threshold as EnergyCoverageDeltaSensor.
    WHOLE_HOUSE_CUMULATIVE_THRESHOLD_KWH = 1000.0

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
        # Per-sensor today-delta tracker (B-M2 parity with coverage delta).
        self._tier_baselines: dict[str, dict[str, Any]] = {}

    def _get_sensor_list(self, plural_key, singular_key):
        """Get sensor list with singular→plural migration fallback."""
        sensors = self._get_config(plural_key)
        if sensors:
            return sensors if isinstance(sensors, list) else [sensors]
        singular = self._get_config(singular_key)
        if singular:
            return [singular]
        return []

    def _today_local(self):
        return dt_util.now().date()

    def _sum_sensors(self, sensor_ids: list[str]) -> float | None:
        """Sum today-scoped kWh readings using per-sensor scope heuristic.

        D1 (Bug Class #30) + B-M2: every read routes through
        ``energy_state_to_kwh`` (unit normalization) AND a per-sensor
        scope classifier (today-native pass-through vs today-derived
        today-delta) — same shape used by ``EnergyCoverageDeltaSensor``.
        Without this, a Wh-reporting cumulative source would inflate
        this sensor's native_value while the coverage sensor's
        ``whole_house`` attr stayed sane.
        """
        total = 0.0
        any_valid = False
        today = self._today_local()
        threshold = self.WHOLE_HOUSE_CUMULATIVE_THRESHOLD_KWH
        for sensor_id in sensor_ids:
            state = self.hass.states.get(sensor_id)
            kwh = energy_state_to_kwh(state)
            if kwh is None:
                continue
            any_valid = True
            tracker_key = f"__wh_self__{sensor_id}"
            entry = self._tier_baselines.get(tracker_key)
            needs_classify = (
                entry is None
                or entry.get("scope") is None
                or (
                    entry.get("scope") == "today_native"
                    and kwh > threshold
                )
            )
            if needs_classify:
                scope = "today_derived" if kwh > threshold else "today_native"
                self._tier_baselines[tracker_key] = {
                    "scope": scope,
                    "baseline_kwh": kwh if scope == "today_derived" else 0.0,
                    "anchor_date": today,
                }
                entry = self._tier_baselines[tracker_key]
            scope = entry["scope"]
            if scope == "today_derived":
                total += today_delta_kwh(
                    self._tier_baselines, tracker_key, kwh, today,
                )
            else:
                total += kwh
        return total if any_valid else None

    @property
    def native_value(self) -> float | None:
        """Return whole house energy with date-based reset acceptance.

        Fix-up pass C-H1: replaces the ``current < 0.1`` magnitude
        heuristic with a date-based acceptance — a decrease is only
        accepted when the local date has rolled over.
        """
        sensors = self._get_sensor_list(
            CONF_WHOLE_HOUSE_ENERGY_SENSORS, CONF_WHOLE_HOUSE_ENERGY_SENSOR)
        if not sensors:
            return None

        current = self._sum_sensors(sensors)
        if current is None:
            return None

        today = dt_util.now().date()
        if not hasattr(self, "_last_accepted_date") or self._last_accepted_date is None:
            self._last_accepted_date = today
            self._last_valid_value = current
            return current
        if self._last_valid_value is not None and current < self._last_valid_value:
            if self._last_accepted_date != today:
                self._last_accepted_date = today
                self._last_valid_value = current
                return current
            return self._last_valid_value
        self._last_accepted_date = today
        self._last_valid_value = current
        return current

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return source info."""
        sensors = self._get_sensor_list(
            CONF_WHOLE_HOUSE_ENERGY_SENSORS, CONF_WHOLE_HOUSE_ENERGY_SENSOR)
        return {
            "source_sensors": sensors,
            "sensor_count": len(sensors),
        }


class WholeHouseCostTodaySensor(AggregationEntity, SensorEntity):
    """Sensor: Whole house realized energy cost today — WholeHouseEnergy × TOU-aware rate.

    v4.6.8: New sensor. Returns None when whole_house_energy_sensors not configured.
    Uses _get_effective_rate_kwh helper (EC TOU first, static fallback).
    v4.6.10 D6: state_class TOTAL_INCREASING → TOTAL (MONETARY + TOTAL_INCREASING is
    rejected by HA recorder; TOTAL is correct for daily-resetting accumulators).
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:currency-usd"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_whole_house_cost_today"
        self._attr_name = "Whole House Cost Today"
        self._last_valid_value: float | None = None

    def _get_sensor_list(self, plural_key, singular_key):
        """Get sensor list with singular→plural migration fallback (mirrors WholeHouseEnergySensor)."""
        sensors = self._get_config(plural_key)
        if sensors:
            return sensors if isinstance(sensors, list) else [sensors]
        singular = self._get_config(singular_key)
        if singular:
            return [singular]
        return []

    def _sum_energy_sensors(self, sensor_ids: list[str]) -> float | None:
        """Sum energy sensor states normalized to kWh.

        Review C1 (power-units cycle): this sensor sums the SAME
        CONF_WHOLE_HOUSE_ENERGY_SENSORS list that WholeHouseEnergySensor
        normalizes — a raw sum here let a Wh source inflate cost 1000x
        while the energy sensor read correctly (Bug Class #30).
        """
        total = 0.0
        any_valid = False
        for sensor_id in sensor_ids:
            state = self.hass.states.get(sensor_id)
            value = energy_state_to_kwh(state)
            if value is not None:
                total += value
                any_valid = True
        return total if any_valid else None

    @property
    def native_value(self) -> float | None:
        """Return whole house cost today (energy_today × effective rate).

        Returns None when whole_house_energy_sensors not configured — HA history
        charts distinguish None (unconfigured) from 0.0 (configured but zero usage).
        """
        sensors = self._get_sensor_list(
            CONF_WHOLE_HOUSE_ENERGY_SENSORS, CONF_WHOLE_HOUSE_ENERGY_SENSOR)
        if not sensors:
            return None
        energy_kwh = self._sum_energy_sensors(sensors)
        if energy_kwh is None:
            return None
        rate, _src = _get_effective_rate_kwh(self.hass)
        return round(energy_kwh * rate, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return rate and source sensor details."""
        rate, rate_source = _get_effective_rate_kwh(self.hass)
        sensors = self._get_sensor_list(
            CONF_WHOLE_HOUSE_ENERGY_SENSORS, CONF_WHOLE_HOUSE_ENERGY_SENSOR)
        return {
            "rate_source": rate_source,
            "rate_used": round(rate, 6),
            "source_energy_sensor_count": len(sensors),
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
        # Fix-up pass C-H1: date-based reset acceptance (replaces the
        # ``current < 0.1`` magnitude heuristic which mis-fires for low-
        # draw houses sitting <0.1 kWh for hours).
        self._last_accepted_date = None

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

        # Fix-up pass C-H1: date-based day-reset acceptance.
        today = dt_util.now().date()
        if self._last_accepted_date is None:
            self._last_accepted_date = today
            self._last_valid_value = current
            return current
        if self._last_valid_value is not None and current < self._last_valid_value:
            if self._last_accepted_date != today:
                self._last_accepted_date = today
                self._last_valid_value = current
                return current
            return self._last_valid_value
        self._last_accepted_date = today
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
    """Sensor: Delta between whole house energy and sum of room sensors.

    D1 + D2 (Bug Class #30 on energy device class): all reads go through
    ``energy_state_to_kwh`` so Wh / kWh / MWh sources normalize correctly.

    D2 attribution semantics: zones, house-devices, and (when needed)
    whole-house tiers track an IN-MEMORY today-delta baseline per
    sensor_id, anchored at local midnight. Restart loses part-of-day
    accumulation for these diagnostic tiers — acceptable trade-off
    versus a new DB write path (post 2026-06-09 write-flood incident).
    Room tier (handled by per-room coordinator) remains the persistent
    truth source.

    Whole-house tier uses a one-time heuristic: if the first observed
    normalized value is large (> WHOLE_HOUSE_CUMULATIVE_THRESHOLD_KWH)
    the source is assumed to be a cumulative lifetime counter and a
    today-delta baseline is applied; otherwise the source is taken as
    today-native and the value passes through. The chosen path is
    exposed via the ``whole_house_scope`` attribute for post-deploy
    audit.
    """

    # Heuristic: if first observed whole-house value (kWh-normalized) is
    # above this threshold, treat the source as a lifetime cumulative
    # counter (apply today-delta baseline). Otherwise treat as today-
    # native. Single-day whole-house usage typically peaks ~100 kWh in a
    # large household; 1000 kWh chosen as a generous safety margin.
    WHOLE_HOUSE_CUMULATIVE_THRESHOLD_KWH = 1000.0

    # No device_class - this is a delta/difference, not cumulative energy
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_COVERAGE

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_coverage_delta"
        self._attr_name = "Energy Coverage Delta"
        # In-memory today-delta tracker keyed by sensor_id (or namespaced
        # tracker_key for per-tier classification). Each value carries
        # baseline_kwh, anchor_date, scope. Re-anchored lazily on first
        # read of a new local date; scope flagged for re-eval at midnight
        # so misclassified young sensors flip on their next observation.
        self._tier_baselines: dict[str, dict[str, Any]] = {}
        # whole_house_scope: "today_native" | "today_derived" | "mixed" |
        # "unknown". Updated only when the tier produced any valid read
        # (B-M1 / C-L2: dead cycles retain the previous classification).
        self._whole_house_scope: str = "unknown"
        # scope_mismatch_warning: empty string when clean; "<tier>:mixed"
        # when the named tier produced mixed today_native + today_derived
        # classifications on this cycle. Retained on dead cycles.
        self._scope_mismatch_warning: str = ""
        # B-H3 sticky misclassification undo: at every midnight the
        # heuristic re-runs against current readings so a young
        # cumulative counter (<1000 kWh on first observation) gets a
        # second chance.
        # Fourth-pass H-1: seed with the BOOT date, not None. A None seed
        # made the first-ever read trip the midnight-reclassify branch,
        # which closed the post-restart window immediately — the B-H4
        # protection never engaged. Seeded to boot date, the branch only
        # fires on a genuine date change.
        self._last_reclassify_date = dt_util.now().date()
        # B-H4 post-restart window: in-memory tiers re-anchor at boot
        # while the rooms tier is DB-persisted (full day). The resulting
        # negative delta_percent must NOT be misattributed to unit drift.
        # Window opens at any boot that happens after ~00:05 local and
        # closes at the next midnight re-anchor.
        self._boot_local_dt = dt_util.now()
        _boot_mins_into_day = (
            self._boot_local_dt.hour * 60 + self._boot_local_dt.minute
        )
        self._post_restart_window: bool = _boot_mins_into_day > 5

    # --- helpers ----------------------------------------------------------

    # Tunable threshold (kWh) for sticky-misclassification re-eval (B-H3):
    # any "today_native" sensor reading above this flips to today_derived
    # immediately on observation — it can't be a today value at that
    # magnitude.
    _RECLASSIFY_THRESHOLD_KWH = WHOLE_HOUSE_CUMULATIVE_THRESHOLD_KWH

    def _today_local(self):
        """Return today's local date (used as the anchor key).

        Fix-up pass C-M1: anchors are BOOT-TIME on first classification
        (the tracker re-anchors on first observation), and only converge
        to MIDNIGHT-aligned values at the next midnight rollover. This
        wording matters for Review-D live validation — pre-fix docstring
        implied immediate-midnight anchoring which is not what happens.
        """
        return dt_util.now().date()

    def _today_delta_kwh(self, sensor_id: str, current_kwh: float) -> float:
        """Return today-scoped delta for an assumed-cumulative sensor.

        Delegates to ``today_delta_kwh`` in domain_coordinators/_units.py
        so the logic is testable without HA installed.
        """
        return today_delta_kwh(
            self._tier_baselines, sensor_id, current_kwh, self._today_local(),
        )

    def _maybe_reclassify_at_midnight(self, today) -> None:
        """B-H3: flag every tracker entry for re-classification at midnight.

        The actual re-classify happens lazily in
        ``_classify_and_accumulate`` on the next read of each sensor.
        Also closes the post-restart window (B-H4) — once we crossed a
        midnight, the in-memory tiers are aligned with the rooms tier.
        """
        if self._last_reclassify_date != today:
            for entry in self._tier_baselines.values():
                if isinstance(entry, dict) and "scope" in entry:
                    entry["scope_pending_reeval"] = True
            self._last_reclassify_date = today
            self._post_restart_window = False

    def _get_sensor_list(self, plural_key, singular_key=None):
        """Get sensor list with optional singular→plural migration fallback."""
        sensors = self._get_config(plural_key)
        if sensors:
            return sensors if isinstance(sensors, list) else [sensors]
        if singular_key:
            singular = self._get_config(singular_key)
            if singular:
                return [singular]
        return []

    def _classify_and_accumulate(
        self,
        sensor_ids: list[str],
        key_prefix: str,
    ) -> tuple[float | None, set[str]]:
        """Per-sensor scope heuristic for an attribution tier.

        Fix-up pass B-H1 / B-H3: each sensor is independently classified
        as ``today_native`` (small first read, pass through normalized)
        or ``today_derived`` (large first read, today-delta tracked).
        Misclassification recovery:

        * At every midnight, ``_maybe_reclassify_at_midnight`` flags
          every entry for re-evaluation so a young counter (<threshold
          on first observation) gets a second chance.
        * Any time a ``today_native`` classified sensor reads above the
          threshold, it is immediately flipped to ``today_derived`` and
          re-anchored — it can't be a today value at that magnitude.

        ``key_prefix`` namespaces tracker entries per tier (so the same
        sensor_id can appear in two tiers without colliding).

        Returns ``(total, observed_scopes)``. ``total`` is None when no
        sensor produced a valid kWh value, so callers can retain prior
        classification + warning state (B-M1).
        """
        today = self._today_local()
        self._maybe_reclassify_at_midnight(today)

        total = 0.0
        any_valid = False
        observed_scopes: set[str] = set()
        for sensor_id in sensor_ids:
            state = self.hass.states.get(sensor_id)
            kwh = energy_state_to_kwh(state)
            if kwh is None:
                continue
            any_valid = True
            tracker_key = f"{key_prefix}__{sensor_id}"
            entry = self._tier_baselines.get(tracker_key)
            needs_classify = (
                entry is None
                or entry.get("scope") is None
                or entry.get("scope_pending_reeval")
                or (
                    entry.get("scope") == "today_native"
                    and kwh > self._RECLASSIFY_THRESHOLD_KWH
                )
            )
            if needs_classify:
                scope = (
                    "today_derived"
                    if kwh > self._RECLASSIFY_THRESHOLD_KWH
                    else "today_native"
                )
                self._tier_baselines[tracker_key] = {
                    "scope": scope,
                    "baseline_kwh": kwh if scope == "today_derived" else 0.0,
                    "anchor_date": today,
                }
                entry = self._tier_baselines[tracker_key]
            scope = entry["scope"]
            observed_scopes.add(scope)
            if scope == "today_derived":
                total += self._today_delta_kwh(tracker_key, kwh)
            else:
                total += kwh
        if not any_valid:
            return (None, observed_scopes)
        return (total, observed_scopes)

    def _sum_sensors(self, sensor_ids: list[str]) -> float | None:
        """Tier-aware sum used by attribution tiers (delegates).

        Now routes through ``_classify_and_accumulate`` under the
        ``_sum_sensors`` namespace so per-sensor scope classification
        applies to the zone + house-device tiers (B-H1) — previously
        these tiers naively today-delta'd every reading, which double-
        subtracted the baseline on already-today-native sensors.

        Returns None when no sensor produced a valid kWh value (callers
        retain prior classification per B-M1).
        """
        total, _ = self._classify_and_accumulate(sensor_ids, "_sum_sensors")
        return total

    # --- main read paths --------------------------------------------------

    @property
    def native_value(self) -> float | None:
        """Return unattributed energy (whole house minus all attributed tiers)."""
        whole_house = self._get_whole_house_energy()
        if whole_house is None:
            return None

        rooms_total = self._get_rooms_total_energy()
        zones_total = self._get_zones_total_energy()
        house_devices_total = self._get_house_devices_total_energy()
        attributed = rooms_total + zones_total + house_devices_total
        return round(whole_house - attributed, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return 4-tier attribution analysis."""
        whole_house = self._get_whole_house_energy()
        rooms_total = self._get_rooms_total_energy()
        zones_total = self._get_zones_total_energy()
        house_devices_total = self._get_house_devices_total_energy()

        if whole_house is None or whole_house == 0:
            return {
                "whole_house": whole_house,
                "rooms_total": rooms_total,
                "zones_total": zones_total,
                "house_devices_total": house_devices_total,
                "coverage_rating": "No data",
                "whole_house_scope": self._whole_house_scope,
                "scope_mismatch_warning": self._scope_mismatch_warning,
                "post_restart_window": self._post_restart_window,
                "baseline_anchor": str(self._today_local()),
                "note": "Configure whole house energy sensor",
            }

        attributed = rooms_total + zones_total + house_devices_total
        unattributed = whole_house - attributed
        coverage_pct = (attributed / whole_house) * 100 if whole_house > 0 else 0
        delta_percent = (unattributed / whole_house) * 100 if whole_house > 0 else 0

        return {
            "whole_house": round(whole_house, 2),
            "rooms_total": round(rooms_total, 2),
            "zones_total": round(zones_total, 2),
            "house_devices_total": round(house_devices_total, 2),
            "attributed_total": round(attributed, 2),
            "unattributed": round(unattributed, 2),
            "attribution_coverage_pct": round(coverage_pct, 1),
            "delta_kwh": round(unattributed, 2),
            "delta_percent": round(delta_percent, 1),
            "coverage_rating": _get_coverage_rating(
                delta_percent,
                post_restart_window=self._post_restart_window,
            ),
            "whole_house_scope": self._whole_house_scope,
            "scope_mismatch_warning": self._scope_mismatch_warning,
            "post_restart_window": self._post_restart_window,
            "baseline_anchor": str(self._today_local()),
        }

    def _record_tier_scope_warning(
        self,
        tier_name: str,
        observed_scopes: set[str],
    ) -> bool:
        """Update scope_mismatch_warning per tier (B-H1 / B-M1).

        Returns True when the tier was MIXED and its contribution should
        be skipped this cycle. Retains the previous value when
        ``observed_scopes`` is empty (dead cycle).
        """
        if not observed_scopes:
            return False  # dead tier — retain prior warning state
        if len(observed_scopes) > 1:
            self._scope_mismatch_warning = f"{tier_name}:mixed"
            return True
        # Clean tier — clear only if the prior warning was on this same tier.
        if self._scope_mismatch_warning.startswith(f"{tier_name}:"):
            self._scope_mismatch_warning = ""
        return False

    def _get_whole_house_energy(self) -> float | None:
        """Get whole house energy (sum of all configured whole-house sensors).

        D2: per-sensor cumulative-vs-today heuristic. Now delegates to
        ``_classify_and_accumulate`` for parity with zones / house-devices.
        Mixed scopes flag ``scope_mismatch_warning`` AND skip the tier's
        contribution this cycle (B-H1).
        """
        sensors = self._get_sensor_list(
            CONF_WHOLE_HOUSE_ENERGY_SENSORS, CONF_WHOLE_HOUSE_ENERGY_SENSOR)
        if not sensors:
            return None

        total, observed_scopes = self._classify_and_accumulate(
            sensors, "__whole_house__",
        )

        # B-M1: only update _whole_house_scope when we observed something.
        # Dead cycles retain the prior classification.
        if observed_scopes:
            if len(observed_scopes) == 1:
                self._whole_house_scope = next(iter(observed_scopes))
            elif len(observed_scopes) > 1:
                self._whole_house_scope = "mixed"

        mixed = self._record_tier_scope_warning("whole_house", observed_scopes)
        if mixed:
            return None  # skip tier when sensors disagree
        return total

    def _get_rooms_total_energy(self) -> float:
        """Get sum of energy from all room coordinators."""
        total = 0.0
        for coord in _get_room_coordinators(self.hass):
            if coord.data:
                energy = coord.data.get(STATE_ENERGY_TODAY, 0)
                if energy:
                    total += energy
        return total

    def _get_zones_total_energy(self) -> float:
        """Get sum of zone-level energy sensors across all zones.

        D2 / fix-up B-H1: per-sensor scope heuristic applied via
        ``_classify_and_accumulate``. Mixed scopes within the zone tier
        (e.g. one zone exposes ``_today``-native, another a lifetime
        counter) skip the zone-tier contribution this cycle and set
        ``scope_mismatch_warning="zones:mixed"``.
        """
        # Gather all zone energy sensors across all zone manager entries.
        all_zone_sensors: list[str] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE_MANAGER
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE_MANAGER:
                continue
            merged = {**entry.data, **entry.options}
            for zone_data in merged.get("zones", {}).values():
                zs = zone_data.get(CONF_ZONE_ENERGY_SENSORS, [])
                if zs:
                    all_zone_sensors.extend(zs)
        if not all_zone_sensors:
            return 0.0
        total, observed_scopes = self._classify_and_accumulate(
            all_zone_sensors, "_zones_tier",
        )
        if self._record_tier_scope_warning("zones", observed_scopes):
            return 0.0
        return total if total is not None else 0.0

    def _get_house_devices_total_energy(self) -> float:
        """Get sum of house-level device energy sensors.

        D2 / fix-up B-H1: per-sensor scope heuristic via
        ``_classify_and_accumulate``. Mixed scopes skip the tier this
        cycle (sets ``scope_mismatch_warning="house_devices:mixed"``).
        """
        sensors = self._get_config(CONF_HOUSE_DEVICE_ENERGY_SENSORS) or []
        if not sensors:
            return 0.0
        total, observed_scopes = self._classify_and_accumulate(
            sensors, "_house_devices_tier",
        )
        if self._record_tier_scope_warning("house_devices", observed_scopes):
            return 0.0
        return total if total is not None else 0.0


# ============================================================================
# v4.2.0 B4 L3: ENERGY INTELLIGENCE SENSORS
# ============================================================================


def _get_energy_coordinator(hass):
    """Get the energy coordinator instance (lazy, survives reloads)."""
    manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
    if manager is None:
        return None
    return manager.coordinators.get("energy")


class EnergyWasteIdleSensor(AggregationEntity, SensorEntity):
    """Total watts drawn by vacant non-infrastructure rooms.

    Reports waste rooms (vacant + drawing power) separately from
    infrastructure baseline (always-on equipment rooms like AV closets).
    """

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:power-plug-off-outline"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_waste_idle"
        self._attr_name = "Energy Waste Idle"

    @property
    def native_value(self):
        waste_watts = 0.0
        for coord in _get_room_coordinators(self.hass):
            if not coord.data:
                continue
            if getattr(coord, "_infrastructure_room", False):
                continue
            if not coord.data.get(STATE_OCCUPIED, True):
                power = coord.data.get(STATE_POWER_CURRENT, 0) or 0
                if power > 5:
                    waste_watts += power
        return round(waste_watts, 1)

    @property
    def extra_state_attributes(self):
        waste_rooms = []
        infra_baseline = []
        for coord in _get_room_coordinators(self.hass):
            if not coord.data:
                continue
            room_name = coord.entry.data.get("room_name", "Unknown")
            power = coord.data.get(STATE_POWER_CURRENT, 0) or 0
            is_infra = getattr(coord, "_infrastructure_room", False)

            if is_infra and power > 0:
                infra_baseline.append({"room": room_name, "watts": round(power, 1)})
            elif not coord.data.get(STATE_OCCUPIED, True) and power > 5:
                waste_rooms.append({"room": room_name, "watts": round(power, 1)})

        waste_total = sum(r["watts"] for r in waste_rooms)
        return {
            "waste_rooms": sorted(waste_rooms, key=lambda r: r["watts"], reverse=True),
            "infrastructure_baseline": infra_baseline,
            "waste_room_count": len(waste_rooms),
            "infrastructure_room_count": len(infra_baseline),
            "estimated_daily_waste_kwh": round(waste_total * 24 / 1000, 2),
        }


class EnergyCostPerOccupiedHourSensor(AggregationEntity, SensorEntity):
    """Whole-house energy cost per occupied hour."""

    _attr_native_unit_of_measurement = "USD/h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-usd"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_cost_per_occupied_hour"
        self._attr_name = "Energy Cost Per Occupied Hour"

    def _get_rate(self):
        """Get effective electricity rate — EC TOU when available, static config fallback.

        v4.6.8: Replaced hardcoded 0.1 fallback with _get_effective_rate_kwh helper.
        Returns (rate, source) tuple; callers only need rate.
        """
        rate, _src = _get_effective_rate_kwh(self.hass)
        return rate

    @property
    def available(self):
        """Only available when energy coordinator is active."""
        return _get_energy_coordinator(self.hass) is not None

    @property
    def native_value(self):
        rate = self._get_rate()
        total_cost = 0.0
        total_occupied_hours = 0.0
        now = dt_util.now()
        for coord in _get_room_coordinators(self.hass):
            if not coord.data or getattr(coord, "_infrastructure_room", False):
                continue
            # Compute cost from energy today * rate (coordinator doesn't store cost)
            energy_kwh = coord.data.get(STATE_ENERGY_TODAY, 0) or 0
            total_cost += energy_kwh * rate
            # Estimate occupied hours from became_occupied_time
            if coord.data.get(STATE_OCCUPIED, False) and hasattr(coord, "_became_occupied_time"):
                if coord._became_occupied_time:
                    elapsed = (now - coord._became_occupied_time).total_seconds() / 3600
                    total_occupied_hours += min(elapsed, 24)
        if total_occupied_hours < 0.1:
            return None
        return round(total_cost / total_occupied_hours, 4)

    @property
    def extra_state_attributes(self):
        rate = self._get_rate()
        rooms = []
        now = dt_util.now()
        for coord in _get_room_coordinators(self.hass):
            if not coord.data or getattr(coord, "_infrastructure_room", False):
                continue
            room_name = coord.entry.data.get("room_name", "Unknown")
            energy_kwh = coord.data.get(STATE_ENERGY_TODAY, 0) or 0
            cost = energy_kwh * rate
            occupied_hours = 0.0
            if hasattr(coord, "_became_occupied_time") and coord._became_occupied_time:
                if coord.data.get(STATE_OCCUPIED, False):
                    occupied_hours = min(
                        (now - coord._became_occupied_time).total_seconds() / 3600, 24
                    )
            cost_per_hour = round(cost / occupied_hours, 4) if occupied_hours > 0.1 else None
            rooms.append({
                "room": room_name, "cost_today": round(cost, 4),
                "occupied_hours": round(occupied_hours, 2),
                "cost_per_hour": cost_per_hour,
            })
        rooms_ranked = sorted(
            [r for r in rooms if r["cost_per_hour"] is not None],
            key=lambda r: r["cost_per_hour"], reverse=True,
        )
        return {
            "rooms": rooms_ranked,
            "most_expensive_room": rooms_ranked[0]["room"] if rooms_ranked else None,
            "most_efficient_room": rooms_ranked[-1]["room"] if rooms_ranked else None,
        }


class MostExpensiveCircuitSensor(AggregationEntity, SensorEntity):
    """Top 5 circuits by cost today (SPAN + Emporia + manual)."""

    _attr_native_unit_of_measurement = "USD"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash-alert"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_most_expensive_circuits"
        self._attr_name = "Most Expensive Circuits"

    @property
    def available(self):
        """Only available when energy coordinator is active."""
        return _get_energy_coordinator(self.hass) is not None

    def _get_circuits(self):
        """Get circuit data from energy coordinator."""
        ec = _get_energy_coordinator(self.hass)
        if ec is None or not hasattr(ec, "_circuits"):
            return [], 0.0
        if not ec._circuits._discovered:
            return [], 0.0
        circuits = []
        # v4.6.8: Replaced hardcoded 0.1 fallback with _get_effective_rate_kwh helper.
        rate, _src = _get_effective_rate_kwh(self.hass)
        for entity_id, circuit in ec._circuits._circuits.items():
            energy_kwh = circuit.cumulative_energy_wh / 1000.0
            cost = energy_kwh * rate
            circuits.append({
                "name": circuit.friendly_name,
                "entity_id": entity_id,
                "panel": circuit.panel,
                "power_w": round(circuit.last_power or 0, 1),
                "energy_today_kwh": round(energy_kwh, 3),
                "cost_today": round(cost, 4),
            })
        return circuits, rate

    @property
    def native_value(self):
        circuits, _ = self._get_circuits()
        if not circuits:
            return None
        top = max(circuits, key=lambda c: c["cost_today"])
        return round(top["cost_today"], 4)

    @property
    def extra_state_attributes(self):
        circuits, _ = self._get_circuits()
        top5 = sorted(circuits, key=lambda c: c["cost_today"], reverse=True)[:5]
        return {
            "top_circuits": top5,
            "circuit_count": len(circuits),
        }


class OptimizationPotentialSensor(AggregationEntity, SensorEntity):
    """Estimated daily savings from eliminating idle waste."""

    _attr_native_unit_of_measurement = "USD/day"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:leaf"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimization_potential"
        self._attr_name = "Energy Optimization Potential"

    @property
    def available(self):
        """Only available when energy coordinator is active."""
        return _get_energy_coordinator(self.hass) is not None

    @property
    def native_value(self):
        waste_watts = 0.0
        for coord in _get_room_coordinators(self.hass):
            if not coord.data or getattr(coord, "_infrastructure_room", False):
                continue
            if not coord.data.get(STATE_OCCUPIED, True):
                power = coord.data.get(STATE_POWER_CURRENT, 0) or 0
                if power > 5:
                    waste_watts += power

        # v4.6.8: Replaced hardcoded 0.1 fallback with _get_effective_rate_kwh helper.
        rate, _src = _get_effective_rate_kwh(self.hass)
        daily_kwh = waste_watts * 24 / 1000
        return round(daily_kwh * rate, 4)

    @property
    def extra_state_attributes(self):
        waste_rooms = []
        for coord in _get_room_coordinators(self.hass):
            if not coord.data or getattr(coord, "_infrastructure_room", False):
                continue
            if not coord.data.get(STATE_OCCUPIED, True):
                power = coord.data.get(STATE_POWER_CURRENT, 0) or 0
                if power > 5:
                    room_name = coord.entry.data.get("room_name", "Unknown")
                    waste_rooms.append({"room": room_name, "watts": round(power, 1)})

        waste_rooms.sort(key=lambda r: r["watts"], reverse=True)
        waste_total = sum(r["watts"] for r in waste_rooms)

        # v4.6.8: Replaced hardcoded 0.1 fallback with _get_effective_rate_kwh helper.
        rate, _src = _get_effective_rate_kwh(self.hass)
        daily_kwh = waste_total * 24 / 1000
        savings_day = daily_kwh * rate
        suggestion = None
        if waste_rooms:
            top = waste_rooms[0]
            suggestion = f"Turn off {top['room']} (drawing {top['watts']}W while vacant)"

        return {
            "waste_watts_total": round(waste_total, 1),
            "savings_per_day": round(savings_day, 4),
            "savings_per_month": round(savings_day * 30, 2),
            "top_waste_rooms": waste_rooms[:3],
            "actionable_suggestion": suggestion,
        }


class EnergyAnomalyBinarySensor(AggregationEntity, BinarySensorEntity):
    """ON when any room draws significantly more than its learned power profile baseline.

    Uses L1 power profiles (always learning). Does NOT require L2 occupancy toggle.
    Occupancy-aware: compares against appropriate baseline for current state.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:flash-alert-outline"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_anomaly"
        self._attr_name = "Energy Anomaly"
        self._cached_anomalies = []
        self._cache_time = 0.0

    @property
    def available(self):
        """Only available when energy coordinator has power profiles."""
        ec = _get_energy_coordinator(self.hass)
        return ec is not None and hasattr(ec, "_power_profiles")

    def _get_anomalies(self):
        """Check all rooms against their power profile baselines."""
        ec = _get_energy_coordinator(self.hass)
        if ec is None or not hasattr(ec, "_power_profiles"):
            return []

        from .domain_coordinators.energy_forecast import get_time_bin

        now = dt_util.now()
        time_bin = get_time_bin(now.hour)
        day_type = 1 if now.weekday() >= 5 else 0
        anomalies = []

        for coord in _get_room_coordinators(self.hass):
            if not coord.data:
                continue
            room_name = coord.entry.data.get("room_name", "Unknown")
            power = coord.data.get(STATE_POWER_CURRENT, 0) or 0
            if power < 10:  # Ignore trivial draws
                continue
            is_occupied = coord.data.get(STATE_OCCUPIED, False)

            baseline = ec._power_profiles.get_baseline_watts(
                room_name, time_bin, day_type
            )
            if baseline is None or baseline < 5:
                continue  # Not enough profile data

            ratio = power / baseline
            # Higher threshold for occupied rooms (more variability expected)
            threshold = 3.0 if is_occupied else 2.0
            if ratio > threshold:
                anomalies.append({
                    "room": room_name,
                    "current_watts": round(power, 1),
                    "expected_watts": round(baseline, 1),
                    "ratio": round(ratio, 1),
                    "is_occupied": is_occupied,
                })

        return anomalies

    @property
    def is_on(self):
        # Cache anomalies for this tick (avoid computing twice per state write)
        import time
        now = time.monotonic()
        if now - self._cache_time > 5:  # Refresh every 5s max
            self._cached_anomalies = self._get_anomalies()
            self._cache_time = now
        return len(self._cached_anomalies) > 0

    @property
    def extra_state_attributes(self):
        return {
            "anomalies": self._cached_anomalies,
            "anomaly_count": len(self._cached_anomalies),
        }


# ============================================================================
# ZONE SENSORS (10 per zone)
# ============================================================================

def _resolve_hvac_zone(zone_manager, zone_key):
    """Resolve an HVAC ZoneState by URA zone NAME (what aggregators carry).

    `ZoneManager.zones` is keyed by `zone_id` ("zone_1", "zone_2", …) derived
    from the thermostat entity, NOT by the zone name. Zone aggregators address
    zones by name (`self.zone`, a Zone-Manager `zones` dict key). A bare
    `zones.get(self.zone)` therefore never matches a real HVAC zone (Bug Class
    #53), which silently disabled the v4.7.13/v4.7.15 motionless-occupant
    fallback for every thermostat'd zone.

    Resolve by:
      1. direct zone_id key (cheap, also covers any future id-keyed caller), then
      2. exact zone_name match, then
      3. membership in a merged name ("Entertainment + Master Suite" → matches
         "Entertainment" or "Master Suite"). The merge separator is fixed at
         " + " in ZoneManager.async_discover_zones.

    Returns the ZoneState or None (None = genuinely no HVAC zone for this name,
    e.g. an aggregator zone with no thermostat).
    """
    zones = zone_manager.zones
    direct = zones.get(zone_key)
    if direct is not None:
        return direct
    for zs in zones.values():
        name = getattr(zs, "zone_name", "") or ""
        if name == zone_key:
            return zs
        if " + " in name and zone_key in [part.strip() for part in name.split(" + ")]:
            return zs
    return None


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
        # v3.6.0: Zone devices are registered under the Zone Manager config entry.
        # No via_device needed — devices appear under the Zone Manager entry on
        # the integration page because their entities are set up via that entry.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"zone_{zone}")},
            name=f"Zone: {zone.title()}",
            manufacturer="Universal Room Automation",
            model="Zone",
            sw_version=VERSION,
        )

    def _zone_still_configured(self) -> bool:
        """Zone Delete Flow D3: is this sensor's zone still in the ZM options?

        Returns True during the normal window (zone present). Returns False
        during the reload window after a zone has been removed from the ZM
        options dict but before entity_registry.async_remove has run against
        this entity — that transient window is where an aggregator would
        otherwise pull a KeyError trying to read from a deleted zone.
        Errors default to True so a lookup failure never nukes a live sensor.

        Fix-up R9 / B-MED-1: results are cached on the instance; the cache
        is invalidated when SIGNAL_ZM_ZONES_UPDATED fires (see
        ``async_added_to_hass``). This avoids a full ``async_entries`` walk
        on every ``available`` call for every zone sensor.

        During an unrelated reload window (transient config-entry state)
        the cache falls back to ``True`` so the entity does not flap
        available/unavailable at boot.
        """
        # Cache hit fast path.
        cached = getattr(self, "_zone_configured_cache", None)
        if cached is not None:
            return cached
        try:
            from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE_MANAGER
            zm_found = False
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                    zm_found = True
                    merged = {**entry.data, **entry.options}
                    result = self.zone in (merged.get("zones", {}) or {})
                    self._zone_configured_cache = result
                    return result
            # No ZM entry — legacy shape (per-zone entries) OR transient
            # reload window where the ZM entry is temporarily gone. Assume
            # configured so we don't flap during a reload (fix-up R9).
            if not zm_found:
                # Do NOT cache: the ZM entry may reappear on next call.
                return True
            return True
        except Exception:  # noqa: BLE001 — availability guard must never raise
            return True

    def _invalidate_zone_configured_cache(self, payload=None) -> None:
        """SIGNAL_ZM_ZONES_UPDATED handler — clear the availability cache."""
        try:
            self._zone_configured_cache = None
            # Ask HA to re-poll our state so the new unavailable rolls out.
            self.async_write_ha_state()
        except Exception:  # noqa: BLE001
            pass

    @property
    def available(self) -> bool:
        """Report unavailable during the reload window if the zone is gone.

        Zone Delete Flow D3: falls back to parent availability when the zone
        is still configured (i.e. steady-state — no change in behavior).
        """
        if not self._zone_still_configured():
            return False
        return super().available

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass - set up coordinator readiness polling.

        v3.3.5.6: Replaced fragile fixed-delay approach with periodic retry.
        Zone sensors may load before room coordinators are ready. Instead of
        sleeping for a fixed 5+10 seconds (which can miss slow-loading rooms),
        we poll every 5 seconds up to 60 seconds. This eliminates the reload-
        required-for-availability issue.
        """
        await super().async_added_to_hass()

        # Zone Delete Flow (fix-up R9 / B-MED-1): subscribe to
        # SIGNAL_ZM_ZONES_UPDATED so the availability cache invalidates
        # when a zone is deleted. Unsub via async_on_remove per HA pattern.
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ZM_ZONES_UPDATED
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_ZM_ZONES_UPDATED,
                    self._invalidate_zone_configured_cache,
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "ZoneSensorBase: SIGNAL_ZM_ZONES_UPDATED subscribe failed",
                exc_info=True,
            )

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
                # v4.7.18.2 review A-MED-1: if a prior entity in this zone hit
                # the no-coordinators threshold and recorded the zone, clear it
                # now that coordinators have appeared, so the dedup set never
                # holds a stale "unhealthy" zone. No-op if the set/zone absent.
                warned_zones = self.hass.data.get(DOMAIN, {}).get(
                    "_no_coord_warned_zones"
                )
                if warned_zones is not None:
                    warned_zones.discard(self.zone)
                self.async_schedule_update_ha_state()
                # Cancel further retries
                if self._retry_unsub:
                    self._retry_unsub()
                    self._retry_unsub = None
            elif self._retry_count >= max_retries:
                # v4.7.18.2: log at most once PER ZONE. Each zone sensor entity
                # runs its own retry timer, so without this dedup every entity
                # in a coordinator-less zone emits the same warning at t=60s
                # (~20 duplicate lines per restart for the largest HVAC zone).
                # A per-entity flag would NOT help (each entity already only
                # logs once via its own timer cancellation). Dedup must be at
                # the zone level, in integration-scoped state cleared on
                # Zone Manager unload (see async_unload_entry) so legitimate
                # reloads re-warn. Single-threaded HA event loop serializes
                # near-simultaneous t=60s firings, so read-check-then-add in
                # one synchronous callback body needs no lock.
                # v4.7.18.2 review B-LOW-2: read DOMAIN via get(), not
                # setdefault — if the callback somehow fires after integration
                # teardown removed the DOMAIN bag, skip rather than resurrect it.
                domain_data = self.hass.data.get(DOMAIN)
                if domain_data is None:
                    return
                warned_zones = domain_data.setdefault(
                    "_no_coord_warned_zones", set()
                )
                if self.zone not in warned_zones:
                    warned_zones.add(self.zone)
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

    # NOTE (Writer B removal, 2026-08-06): The HVAC preset write path that
    # formerly lived here (`_schedule_hvac_listener_setup`,
    # `_setup_hvac_occupancy_listeners`, `_handle_zone_occupancy_change`,
    # `_get_zone_climate_entity`) has been deleted outright. It was the v3.3.5.9
    # "Writer B" of `climate.set_preset_mode` — a second, event-driven writer
    # that raced Writer A (HVACCoordinator._apply_house_state_presets) on the
    # same thermostats. A-M1 (2026-08-06 fix-up) — accurate scope of Writer B's
    # ONLY pre-write guard: it skipped the write when the CURRENT preset was
    # already "manual" or "sleep" (see prior `_handle_zone_occupancy_change`
    # implementation at git blame HEAD~ before removal). It did NOT consult the
    # arrester, the night-trust suppression, the D1 vacancy grace, the D5 duty
    # cycle, or the D6 stale-sensor logic — Writer A owns all of those. Removal
    # spec: docs/planning/AUDIT_writer_b_removal_study.md (Option a). Removal
    # implication / reason-ledger context:
    # docs/planning/AUDIT_hvac_preset_flap_fix_implications.md
    # §Cross-cutting Finding X.
    #
    # Flap measurement anchor (pre-removal baseline, C-M1 fix-up 2026-08-06):
    # zone_1 (Entertainment + Master Suite / Study B thermostat, entity_id
    # `climate.study_b`) — two distinct fingerprints on 2026-08-06 CDT:
    #   * 16:05-17:45 CDT (21:05-22:45 UTC): 5 home↔away oscillations,
    #     seeded by an initial manual→away transition, while zone-anyone
    #     was continuously ON. Cadence irregular (Writer-B event-driven).
    #   * 11:59-13:19 CDT (16:59-18:19 UTC): 11 CONSECUTIVE away→home
    #     re-issues at ~5-minute cadence — the second-writer stomp
    #     fingerprint (Writer A re-asserting home every 5min against
    #     Writer B's away). This is the stronger midday evidence and the
    #     one to grep for in future regression checks.
    # Re-query anchors: entity_id=`climate.study_b`, event_type=
    # `state_changed`, restrict to the UTC windows above.
    # The post-deploy acceptance signal for this removal is zero URA-initiated
    # home<->away oscillations on that same thermostat over an equivalent
    # occupied window, with Writer A's 5-min cadence unchanged.
    #
    # The ZoneAnyoneBinarySensor SENSOR itself (is_on rollup + Layer 2 sleep-
    # trust fallback + Layer 3 non-sleep-trust fallback) is kept byte-identical
    # — the Lovelace dashboard consumes `binary_sensor.zone_*_anyone` and the
    # flap audit's P2 predicate is expected to consume it in future work.

    @property
    def is_on(self) -> bool:
        """Return True if any room in zone occupied.

        v4.7.13: Sleep-state zone presence trust fallback.
        v4.7.15 D2: Non-sleep-state zone presence trust fallback.

        Layer 1 (existing): any room-level occupancy sensor reports occupied.
        Layer 2 (v4.7.13): during house_state == "sleep", if any zone_persons
        member tracker is "home", treat the zone as occupied. This covers the
        structural degeneration where mmWave drops motionless sleepers, PIR
        can't fire on stationary bodies, and cameras are blind in dark rooms.
        Layer 3 (v4.7.15 D2): during HOME_DAY/EVENING/NIGHT/ARRIVING/GUEST/WAKING,
        if any zone_persons member is "home" AND room sensors have been quiet
        for >= 5 min, treat the zone as occupied. Bridges the same structural
        degeneration outside the sleep window (operator at desk going still
        for >5 min, guest reading on couch, etc).
        """
        # Layer 1: existing room-level rollup
        for coord in self._get_zone_coordinators():
            if coord.data and coord.data.get(STATE_OCCUPIED, False):
                return True

        # Layer 2: sleep-state person tracker fallback
        if self._sleep_person_fallback_occupied():
            return True

        # Layer 3: non-sleep-state person tracker fallback (v4.7.15 D2)
        if self._nonsleep_person_fallback_occupied():
            return True

        return False

    def _sleep_person_fallback_occupied(self) -> bool:
        """Return True if house is asleep AND a zone_persons member is home.

        v4.7.13 fallback: only engages when:
          - coordinator_manager is available and house_state == "sleep"
          - the HVAC coordinator has a Zone for self.zone with non-empty
            zone_persons
          - at least one zone_persons entity has state == "home"

        Guarded with try/except: any failure (missing manager, missing zone,
        stale state lookup) returns False — never raises into HA state read.

        v4.7.13 fix-up MEDIUM-2 (interim): If the fallback path is unavailable
        WHILE house_state == "sleep" (boot race: HVAC coordinator not yet
        booted, _zone_manager.zones empty, or zone not registered), emit a
        one-shot WARN per zone per boot. Without this, an overnight HA
        restart could silently leave the room degraded — exactly the bug
        v4.7.13 fixes. Full public-accessor refactor deferred to v4.7.13.1+.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return False

            # House must be asleep — no fabrication during other states.
            if getattr(manager, "house_state", None) != "sleep":
                return False

            hvac = manager.coordinators.get("hvac") if hasattr(manager, "coordinators") else None
            if hvac is None or not hasattr(hvac, "_zone_manager"):
                self._warn_sleep_fallback_unavailable(
                    "hvac coordinator or _zone_manager not ready",
                )
                return False

            zone = _resolve_hvac_zone(hvac._zone_manager, self.zone)
            if zone is None:
                self._warn_sleep_fallback_unavailable(
                    "zone not registered in zone_manager.zones",
                )
                return False

            zone_persons = getattr(zone, "zone_persons", None) or []
            if not zone_persons:
                return False

            any_person_home = False
            home_person_entity = ""
            for person_entity in zone_persons:
                # Strict "home" only — unknown/unavailable intentionally not trusted.
                state = self.hass.states.get(person_entity)
                if state is not None and state.state == "home":
                    any_person_home = True
                    home_person_entity = person_entity
                    break
            if not any_person_home:
                return False

            # v4.7.15 fix-up A1-M2: delegate the actual sleep-fallback decision
            # to the shared D1 helper via scope="zone_aggregator" Pattern B.
            # Behaviour preserved (any zone_persons home during sleep → veto)
            # but the SLEEP path now routes through the same arbitration as
            # the non-sleep path (Pattern C), so future cycles that retune
            # the sleep predicate only touch one place.
            presence = manager.coordinators.get("presence") if hasattr(
                manager, "coordinators",
            ) else None
            if presence is None or not hasattr(
                presence, "should_veto_due_to_reliable_signals",
            ):
                # Boot race — presence not ready. Fall back to v4.7.13's direct
                # bias so a slow boot doesn't lose the sleep-fallback safety net.
                _LOGGER.info(
                    "Zone '%s': sleep-state person fallback engaged — "
                    "%s == home (room sensors degraded, presence pending)",
                    self.zone, home_person_entity,
                )
                return True

            # function-local import — Bug Class #34
            from .domain_coordinators.presence import (  # noqa: PLC0415
                ReliableSignal,
            )

            decision = presence.should_veto_due_to_reliable_signals(
                reliable_signals=[ReliableSignal("zone_persons_home", True)],
                transient_signals=[],
                state_context={
                    "scope": "zone_aggregator",
                    "house_state": "sleep",
                    "zone_name": self.zone,
                },
            )
            if decision.fired:
                _LOGGER.info(
                    "Zone '%s': sleep-state person fallback engaged — "
                    "%s (%s == home, room sensors degraded)",
                    self.zone, decision.reason, home_person_entity,
                )
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            self._warn_sleep_fallback_unavailable(
                f"unexpected exception: {exc}",
            )
            return False

    def _warn_sleep_fallback_unavailable(self, reason: str, scope: str = "sleep") -> None:
        """Log a one-shot WARN per (zone, scope) per boot when the fallback is unavailable.

        v4.7.13 fix-up MEDIUM-2 (interim) — sleep-side telemetry.
        v4.7.15 D2: extended cache key to (zone_id, scope) so SLEEP and non-sleep
        path unavailability don't dedup-mask each other.
        """
        zone_id_for_warn = getattr(self, "zone", "?")
        key = (zone_id_for_warn, scope)
        if key in _SLEEP_FALLBACK_WARNED_ZONES:
            return
        _SLEEP_FALLBACK_WARNED_ZONES.add(key)
        _LOGGER.warning(
            "v4.7.13/v4.7.15 zone fallback unavailable: zone=%s scope=%s (%s). "
            "Room may incorrectly report unoccupied with motionless occupants. "
            "Subsequent occurrences this boot suppressed.",
            zone_id_for_warn, scope, reason,
        )

    def _nonsleep_person_fallback_occupied(self) -> bool:
        """Return True if house is in a non-sleep state where a zone_persons
        tracker is "home" AND all room-level sensors in this zone have been
        quiet for >= _NONSLEEP_QUIET_THRESHOLD_SECONDS.

        v4.7.15 D2: Layer 3 fallback. Mirrors v4.7.13 Layer 2's strict
        zone_persons=="home" bias but extends to HOME_DAY/EVENING/NIGHT,
        ARRIVING, GUEST, WAKING. SLEEP is intentionally excluded — Layer 2
        already covers it without the quiet-window guard (a sleeping occupant
        is structurally going to be quiet for hours).

        The quiet-window guard is the key safety belt for non-sleep states:
        a room briefly going dark while the occupant is in fact there is
        normal noise. We only veto when sensors have been quiet long enough
        that "structural degeneration" is the more likely explanation than
        "occupant left and rejoined".

        Calls the shared v4.7.15 D1 helper via scope="zone_aggregator" so this
        path stays unified with Layer 2 / Pattern C as patterns evolve.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return False

            # State guard: ONLY non-sleep home-like states. SLEEP is Layer 2.
            current_state = getattr(manager, "house_state", None)
            current_state_str = (
                current_state.value if hasattr(current_state, "value")
                else str(current_state or "")
            ).lower()
            if current_state_str not in (
                "home_day", "home_evening", "home_night",
                "arriving", "guest", "waking",
            ):
                return False

            hvac = manager.coordinators.get("hvac") if hasattr(manager, "coordinators") else None
            if hvac is None or not hasattr(hvac, "_zone_manager"):
                self._warn_sleep_fallback_unavailable(
                    "hvac coordinator or _zone_manager not ready", scope="nonsleep",
                )
                return False

            zone = _resolve_hvac_zone(hvac._zone_manager, self.zone)
            if zone is None:
                self._warn_sleep_fallback_unavailable(
                    "zone not registered in zone_manager.zones", scope="nonsleep",
                )
                return False

            zone_persons = getattr(zone, "zone_persons", None) or []
            if not zone_persons:
                return False

            # Conservative: require literal "home" — unknown/unavailable not trusted.
            any_person_home = False
            for person_entity in zone_persons:
                state = self.hass.states.get(person_entity)
                if state is not None and state.state == "home":
                    any_person_home = True
                    break
            if not any_person_home:
                return False

            # Compute quiet seconds from room coordinators' _last_motion_time.
            # Use the freshest motion across all rooms in the zone — even a
            # single room with recent motion means we should NOT engage the
            # fallback (an active room is real signal, not degeneration).
            now = dt_util.utcnow()
            freshest_motion: datetime | None = None
            for coord in self._get_zone_coordinators():
                last_motion = getattr(coord, "_last_motion_time", None)
                if last_motion is None:
                    continue
                if freshest_motion is None or last_motion > freshest_motion:
                    freshest_motion = last_motion
            if freshest_motion is None:
                # No recent motion at all — quiet "forever" for our purposes.
                room_sensors_quiet_seconds = 10**9
            else:
                room_sensors_quiet_seconds = max(
                    0, int((now - freshest_motion).total_seconds()),
                )

            # Delegate the actual decision to the shared D1 helper.
            presence = manager.coordinators.get("presence") if hasattr(manager, "coordinators") else None
            if presence is None or not hasattr(
                presence, "should_veto_due_to_reliable_signals",
            ):
                # Boot race — presence not ready. Conservative: no veto.
                return False

            # function-local import — Bug Class #34
            from .domain_coordinators.presence import (  # noqa: PLC0415
                ReliableSignal,
            )

            decision = presence.should_veto_due_to_reliable_signals(
                reliable_signals=[ReliableSignal("zone_persons_home", True)],
                transient_signals=[],
                state_context={
                    "scope": "zone_aggregator",
                    "house_state": current_state_str,
                    "room_sensors_quiet_seconds": room_sensors_quiet_seconds,
                    "zone_name": self.zone,
                },
            )
            if decision.fired:
                _LOGGER.info(
                    "Zone '%s': non-sleep person fallback engaged — %s "
                    "(state=%s, quiet=%ds)",
                    self.zone, decision.reason, current_state_str,
                    room_sensors_quiet_seconds,
                )
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            self._warn_sleep_fallback_unavailable(
                f"unexpected exception: {exc}", scope="nonsleep",
            )
            return False


class ZoneSafetyAlertSensor(ZoneSensorBase, BinarySensorEntity):
    """Binary sensor: Safety alert in zone.

    v5.38.0 (backlog #12): safety-grade rewrite. Bands come from
    ``safety.resolve_safety_bands(room_type)`` — a projection over the
    same tables the safety coordinator consumes, so the chip cannot
    drift out of alignment. Old comfort-grade thresholds live on the
    ``comfort_drift_rooms`` attribute (D4a, attribute-only).

    Outdoor authority: ``safety.outdoor_zone_names_snapshot(hass)``.
    Leak: always evaluated (no room-type gate). Empty-string CONF
    (cleared-checkbox pattern) is treated as absent; the entity_id must
    start with ``binary_sensor.`` — protects against a mis-configured
    non-binary entity wearing a leak hat.
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_icon = "mdi:alert-circle"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_safety_alert"
        self._attr_name = f"Safety Alert"
        # FIX 2 (B-H1): stick-last on evaluate exception so a transient
        # error can never silently flip a real alert to False. None until
        # the first successful evaluation.
        self._last_is_on: bool | None = None
        self._evaluate_error: str | None = None
        # FIX 3 (B-H2): evaluate-once cache — is_on and extra_state_attributes
        # read the SAME snapshot per update cycle. Refreshed in the
        # async_write_ha_state override (below).
        self._snapshot_is_on: bool = False
        self._snapshot_attrs: dict[str, Any] = {
            "tripping_rooms": [],
            "reasons": [],
            "comfort_drift_rooms": [],
            "tripping": [],
            "bands_source": "safety.resolve_safety_bands",
            "chip_semantics": "snapshot; bathroom trips may be transient",
        }
        self._snapshot_ready: bool = False

    def _evaluate(self) -> tuple[bool, dict[str, Any]]:
        """Evaluate safety trips + comfort-drift; return (is_on, attrs).

        Pure: does not mutate the stick-last / snapshot caches — that's
        the caller's job (``_refresh_snapshot``).
        """
        from .domain_coordinators.safety import (
            ZoneChipRoomInput,
            evaluate_zone_chip,
        )
        from .const import CONF_ROOM_TYPE

        # FIX 5 (B-M1): cached outdoor-zone set on hass.data. Invalidated
        # by the SIGNAL_ZM_ZONES_UPDATED handler ZoneSensorBase already
        # subscribes to (see _invalidate_zone_configured_cache override
        # below). Fallback to a fresh scan when the cache is absent.
        outdoor_zones = self._get_cached_outdoor_zones()
        zone_is_outdoor = self.zone in outdoor_zones

        room_inputs: list[ZoneChipRoomInput] = []
        for coord in self._get_zone_coordinators():
            try:
                merged = {**coord.entry.data, **coord.entry.options}
                room_name = merged.get("room_name") or "Unknown"
                # FIX 7 (A-LOW-3): the room-level CONF_ZONE_IS_OUTDOOR read
                # was dead — the ZONE flag is authoritative, resolved once
                # above via the snapshot. Do not re-read at the room tier.
                room_type = merged.get(CONF_ROOM_TYPE, "generic")

                temp = coord.data.get(STATE_TEMPERATURE) if coord.data else None
                humidity = coord.data.get(STATE_HUMIDITY) if coord.data else None

                # v5.38.1: presence-aware read (see comment at the
                # alert-manager site) — '' options override must win.
                if CONF_WATER_LEAK_SENSOR in coord.entry.options:
                    leak_sensor = coord.entry.options[CONF_WATER_LEAK_SENSOR]
                else:
                    leak_sensor = coord.entry.data.get(CONF_WATER_LEAK_SENSOR)
                leak_on = False
                leak_dc = None
                if leak_sensor and isinstance(leak_sensor, str):
                    try:
                        state = self.hass.states.get(leak_sensor)
                    except Exception:  # noqa: BLE001
                        state = None
                    if state:
                        leak_on = state.state == "on"
                        leak_dc = (state.attributes or {}).get("device_class")

                room_inputs.append(ZoneChipRoomInput(
                    room_name=room_name,
                    room_type=room_type,
                    temperature=temp,
                    humidity=humidity,
                    leak_sensor_entity_id=leak_sensor if isinstance(leak_sensor, str) else None,
                    leak_is_on=leak_on,
                    leak_device_class=leak_dc,
                ))
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug(
                    "ZoneSafetyAlertSensor(%s): room snapshot failed: %s",
                    self.zone, exc,
                )
                continue

        tripping, comfort_drift = evaluate_zone_chip(
            room_inputs, zone_is_outdoor=zone_is_outdoor, hass=self.hass,
        )
        tripping_rooms = [r for r, _ in tripping]
        reasons = [reason for _, reason in tripping]
        attrs: dict[str, Any] = {
            "tripping_rooms": tripping_rooms,
            "reasons": reasons,
            "comfort_drift_rooms": list(comfort_drift),
            # FIX 7 (B-L1): combined per-room trip records alongside the
            # flat lists — easier for dashboards to iterate atomically.
            "tripping": [
                {"room": r, "reason": reason} for r, reason in tripping
            ],
            "bands_source": "safety.resolve_safety_bands",
            # FIX 7 (A-LOW-4): document snapshot semantics; bathroom
            # medium-rung trips may be transient (safety coordinator uses
            # a 4h sustained window).
            "chip_semantics": "snapshot; bathroom trips may be transient",
        }
        return bool(tripping), attrs

    def _refresh_snapshot(self) -> None:
        """FIX 3 (B-H2): compute once, cache both is_on and attrs.

        On evaluate exception, FIX 2 (B-H1) sticky-last kicks in — the
        prior is_on/attrs are preserved and an ``_evaluate_error`` string
        is exposed via attrs so the failure is VISIBLE, not silent.
        """
        try:
            is_on, attrs = self._evaluate()
            self._evaluate_error = None
            self._snapshot_is_on = is_on
            self._snapshot_attrs = attrs
            self._last_is_on = is_on
            self._snapshot_ready = True
        except Exception as exc:  # noqa: BLE001
            self._evaluate_error = f"{type(exc).__name__}: {exc}"
            _LOGGER.error(
                "ZoneSafetyAlertSensor(%s): evaluation failed (sticky-last "
                "in effect, is_on=%s): %s",
                self.zone, self._last_is_on, exc,
            )
            # Preserve previous snapshot; annotate attrs with the error.
            self._snapshot_attrs = dict(self._snapshot_attrs)
            self._snapshot_attrs["_evaluate_error"] = self._evaluate_error
            # is_on falls back to last successful; False if never evaluated.
            if self._last_is_on is None:
                self._snapshot_is_on = False
            else:
                self._snapshot_is_on = self._last_is_on

    def _get_cached_outdoor_zones(self) -> set[str]:
        """FIX 5 (B-M1): hass.data-cached outdoor-zone set.

        Invalidated by ``_invalidate_zone_configured_cache`` (override
        below) on SIGNAL_ZM_ZONES_UPDATED. Fresh scan on cache miss.
        """
        from .domain_coordinators.safety import outdoor_zone_names_snapshot
        try:
            bag = self.hass.data.setdefault(DOMAIN, {})
            cached = bag.get("_outdoor_zones_cache")
            if cached is None:
                cached = outdoor_zone_names_snapshot(self.hass)
                bag["_outdoor_zones_cache"] = cached
            return cached
        except Exception:  # noqa: BLE001
            try:
                return outdoor_zone_names_snapshot(self.hass)
            except Exception:  # noqa: BLE001
                return set()

    def _invalidate_zone_configured_cache(self, payload=None) -> None:
        """Override: also invalidate the outdoor-zone cache on ZM update."""
        try:
            bag = self.hass.data.get(DOMAIN)
            if bag is not None:
                bag.pop("_outdoor_zones_cache", None)
        except Exception:  # noqa: BLE001
            pass
        super()._invalidate_zone_configured_cache(payload)

    @callback
    def async_write_ha_state(self) -> None:
        """Refresh the evaluate-once snapshot BEFORE state is read + written."""
        self._refresh_snapshot()
        super().async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return the cached snapshot's is_on."""
        if not self._snapshot_ready:
            # First access (e.g. HA polls before any coordinator tick has
            # driven async_write_ha_state) — compute lazily so we don't
            # report False before the first evaluation.
            self._refresh_snapshot()
        return bool(self._snapshot_is_on)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the cached snapshot's attrs (same evaluation as is_on)."""
        if not self._snapshot_ready:
            self._refresh_snapshot()
        return dict(self._snapshot_attrs)


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
        # Fix-up pass C-H1: date-based reset acceptance.
        self._last_accepted_date = None

    @property
    def native_value(self) -> float:
        """Return total energy today in zone with date-based reset acceptance.

        Fix-up pass C-H1: a decrease is only accepted when the local
        date has rolled over (genuine midnight reset). Replaces the
        ``current < 0.1`` magnitude heuristic.
        """
        total = 0.0
        for coord in self._get_zone_coordinators():
            if coord.data:
                energy = coord.data.get(STATE_ENERGY_TODAY, 0)
                if energy:
                    total += energy

        current = round(total, 2)

        today = dt_util.now().date()
        if self._last_accepted_date is None:
            self._last_accepted_date = today
            self._last_valid_value = current
            return current
        if self._last_valid_value is not None and current < self._last_valid_value:
            if self._last_accepted_date != today:
                self._last_accepted_date = today
                self._last_valid_value = current
                return current
            return self._last_valid_value
        self._last_accepted_date = today
        self._last_valid_value = current
        return current


class ZoneEnergyCostTodaySensor(ZoneSensorBase, SensorEntity):
    """Sensor: Total energy cost today in zone — energy_today × TOU-aware rate.

    v4.6.8: New sensor. Uses _get_effective_rate_kwh helper (EC TOU first, static fallback).
    v4.6.10 D6: state_class TOTAL_INCREASING → TOTAL (MONETARY incompatibility fix).
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:currency-usd"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_energy_cost_today"
        self._attr_name = "Energy Cost Today"

    @property
    def native_value(self) -> float | None:
        """Return zone energy cost today (energy_today × effective rate)."""
        total_energy = 0.0
        any_valid = False
        for coord in self._get_zone_coordinators():
            if coord.data:
                energy = coord.data.get(STATE_ENERGY_TODAY, 0)
                if energy:
                    total_energy += energy
                    any_valid = True
        if not any_valid:
            return None
        rate, _src = _get_effective_rate_kwh(self.hass)
        return round(total_energy * rate, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return rate details."""
        rate, rate_source = _get_effective_rate_kwh(self.hass)
        return {
            "rate_source": rate_source,
            "rate_used": round(rate, 6),
        }


class ZoneCostPerHourSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Real-time cost per hour for zone — (total_power_w / 1000) × rate.

    v4.6.8: New sensor. Uses _get_effective_rate_kwh helper (EC TOU first, static fallback).
    v4.6.10 D6: removed state_class MEASUREMENT — MONETARY + MEASUREMENT is rejected by
    HA recorder.  This sensor is a rate/instantaneous value, so no state_class is correct.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD/h"
    _attr_icon = "mdi:currency-usd"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_cost_per_hour"
        self._attr_name = "Cost Per Hour"

    @property
    def native_value(self) -> float | None:
        """Return zone cost per hour (W → kW × $/kWh = $/h)."""
        total_power_w = 0.0
        any_valid = False
        for coord in self._get_zone_coordinators():
            if coord.data:
                power = coord.data.get(STATE_POWER_CURRENT, 0)
                if power:
                    total_power_w += power
                    any_valid = True
        if not any_valid:
            return None
        rate, _src = _get_effective_rate_kwh(self.hass)
        return round((total_power_w / 1000.0) * rate, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return rate details."""
        rate, rate_source = _get_effective_rate_kwh(self.hass)
        return {
            "rate_source": rate_source,
            "rate_used": round(rate, 6),
        }


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
        # v3.5.x: unique_id updated to "identified_people" to match room sensor naming
        # v3.5.x: Renamed from "Current Occupants" to "Identified People" (zone parity with room sensor)
        # Migration in __init__.py renames existing "current_occupants" zone entities
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_identified_people"
        self._attr_name = f"Identified People"
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

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_schedule_update_ha_state()

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
        # v3.5.x: unique_id updated to "identified_people_count" to match room sensor naming
        # v3.5.x: Renamed from "Occupant Count" to "Identified People Count" (zone parity with room sensor)
        # Migration in __init__.py renames existing "occupant_count" zone entities
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_identified_people_count"
        self._attr_name = f"Identified People Count"
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

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_schedule_update_ha_state()

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
        # v3.5.x: unique_id updated to "last_identified_person" to match entity name
        # Migration in __init__.py renames existing "last_occupant" zone entities
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_last_identified_person"
        self._attr_name = f"Last Identified Person"
        # v4.2.11: Declare all instance attrs in __init__ (review fix)
        self._last_query_time: float = 0
        self._last_occupant: str = "Unknown"
        self._last_occupant_time: Any = None
        self._last_occupant_room: str | None = None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    @property
    def native_value(self) -> str:
        """Return last zone occupant."""
        return self._last_occupant

    async def async_update(self) -> None:
        """Update last occupant from database (cached 5 min)."""
        import time as _time
        now = _time.monotonic()
        if now - self._last_query_time < 300:  # 5 minutes
            return
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
            result = await database.get_zone_last_occupant(zone_rooms)
            self._last_query_time = now

            if result:
                person_id = result['person_id']
                self._last_occupant = person_id.replace('_', ' ').title()
                self._last_occupant_time = result['entry_time']
                self._last_occupant_room = result['room_id']
            # else: preserve existing values when zone becomes empty

        except Exception as e:
            _LOGGER.error("Error getting zone last occupant: %s", e)
            # v4.2.11: Update cache timer on exception to prevent log spam (review fix)
            # Preserve existing values — don't reset on transient DB error
            self._last_query_time = now
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = {}

        if self._last_occupant_time:
            t = self._last_occupant_time
            attrs["last_seen"] = t if isinstance(t, str) else t.isoformat()
            attrs["room"] = self._last_occupant_room

        return attrs


class ZoneLastOccupantTimeSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Timestamp of last zone occupant."""
    
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        # v3.2.8.3: Aligned with room/house naming convention (v3.2.6)
        # v3.5.x: unique_id updated to "last_identified_time" to match entity name
        # Migration in __init__.py renames existing "last_occupant_time" zone entities
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_last_identified_time"
        self._attr_name = f"Last Identified Time"
        # v4.2.11: Declare all instance attrs in __init__ (review fix)
        self._last_query_time: float = 0
        self._last_time: datetime | None = None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last zone occupant."""
        return self._last_time

    async def async_update(self) -> None:
        """Update last occupant time from database (cached 5 min)."""
        import time as _time
        now = _time.monotonic()
        if now - self._last_query_time < 300:  # 5 minutes
            return
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
            result = await database.get_zone_last_occupant(zone_rooms)
            self._last_query_time = now

            if result:
                entry_time = result['entry_time']
                if isinstance(entry_time, str):
                    # v4.2.9: Use dt_util.parse_datetime for tz-aware result
                    self._last_time = dt_util.parse_datetime(entry_time)
                else:
                    self._last_time = entry_time
                # Ensure tz-aware (DB may store naive UTC strings)
                if self._last_time is not None and self._last_time.tzinfo is None:
                    from datetime import timezone
                    self._last_time = self._last_time.replace(tzinfo=timezone.utc)
            # else: preserve existing value when zone becomes empty

        except Exception as e:
            _LOGGER.error("Error getting zone last occupant time: %s", e)
            # v4.2.11: Update cache timer on exception to prevent log spam (review fix)
            # Preserve existing value — don't reset on transient DB error
            self._last_query_time = now


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
            self.async_schedule_update_ha_state()

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
            self.async_schedule_update_ha_state()

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
                self.async_schedule_update_ha_state()
        elif time_since_update > STALE_THRESHOLD_SECONDS:
            # Location is stale but still valid
            if self._tracking_status != TRACKING_STATUS_STALE:
                _LOGGER.debug(
                    "Person %s location is STALE (no update for %.0f seconds)",
                    self.person_id, time_since_update
                )
                self._tracking_status = TRACKING_STATUS_STALE
                self.async_schedule_update_ha_state()
        else:
            # Location is active
            if self._tracking_status != TRACKING_STATUS_ACTIVE:
                self._tracking_status = TRACKING_STATUS_ACTIVE
                self.async_schedule_update_ha_state()
    
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


class PersonPreviousLocationSensor(AggregationEntity, SensorEntity, RestoreEntity):
    """Sensor: Person's previous location.

    v3.2.8.3: Added person_coordinator subscription for real-time updates
    v4.6.9: RestoreEntity — seeds coordinator with persisted previous_location
            on HA restart so persons already-away keep their last-seen room.
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
        """Subscribe to person_coordinator updates and restore persisted state.

        v3.2.8.3: Enables real-time updates when person tracking changes.
        v4.6.9: Restores previous_location from HA state registry so persons
                who were already-away at shutdown keep their last-seen room.
        """
        await super().async_added_to_hass()

        # v4.6.9: Restore persisted previous_location into coordinator.
        # v4.6.9 review HIGH#1: include HA person-entity sentinels ("not_home"/"home")
        # so we don't store them as restored room names.
        # v4.6.10 D5a: use module-level _PERSON_LAST_STATE_SKIP_VALUES constant.
        try:
            last_state = await self.async_get_last_state()
            if last_state is not None and last_state.state not in _PERSON_LAST_STATE_SKIP_VALUES:
                person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
                if person_coordinator is not None:
                    person_coordinator.seed_previous_location(
                        self.person_id, last_state.state
                    )
        except Exception:
            _LOGGER.debug(
                "PersonPreviousLocationSensor: restore failed for %s",
                self.person_id, exc_info=True,
            )

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

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_schedule_update_ha_state()

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


class PersonPreviousSeenSensor(AggregationEntity, SensorEntity, RestoreEntity):
    """Sensor: When person was last seen in previous location.

    v3.2.8.1: Fixed to use previous_location_time instead of last_changed.
    Now correctly shows when person left their previous room, not when they
    entered current room.
    v3.2.8.3: Added person_coordinator subscription for real-time updates.
    v4.6.9: RestoreEntity — seeds coordinator with persisted timestamp on
            HA restart.
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
        """Subscribe to person_coordinator updates and restore persisted state.

        v3.2.8.3: Enables real-time updates when person tracking changes.
        v4.6.9: Restores previous_location_time from HA state registry.
        """
        await super().async_added_to_hass()

        # v4.6.9: Restore persisted previous_location_time into coordinator.
        # v4.6.9 review HIGH#1: include HA person-entity sentinels ("not_home"/"home")
        # so we don't store them as restored room names.
        # v4.6.10 D5a: use module-level _PERSON_LAST_STATE_SKIP_VALUES constant.
        try:
            last_state = await self.async_get_last_state()
            if last_state is not None and last_state.state not in _PERSON_LAST_STATE_SKIP_VALUES:
                parsed_time = dt_util.parse_datetime(last_state.state)
                if parsed_time is not None:
                    person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
                    if person_coordinator is not None:
                        person_coordinator.seed_previous_location_time(
                            self.person_id, parsed_time
                        )
                else:
                    _LOGGER.debug(
                        "PersonPreviousSeenSensor: could not parse timestamp %r for %s — skip",
                        last_state.state, self.person_id,
                    )
        except Exception:
            _LOGGER.debug(
                "PersonPreviousSeenSensor: restore failed for %s",
                self.person_id, exc_info=True,
            )

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

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> datetime | None:
        """Return when person was last seen in previous location."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return None
        
        # v3.2.8.1: Use previous_location_time instead of last_changed
        return person_coordinator.get_person_previous_location_time(self.person_id)


# ============================================================================
# v3.5.1 Zone Person Aggregation Sensors
# ============================================================================


class ZoneIdentifiedPersonsSensor(ZoneSensorBase, SensorEntity):
    """Sensor: BLE-identified persons currently in a zone's rooms.

    Reads from person_coordinator to list persons whose current location
    is one of the rooms in this zone. Disabled by default.
    """

    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:account-multiple-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_{SENSOR_ZONE_IDENTIFIED_PERSONS}"
        self._attr_name = "Identified Persons"
        self._persons: list[str] = []
        self._unsub_person_coordinator = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates for real-time changes."""
        await super().async_added_to_hass()
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

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update — trigger state refresh."""
        self.async_schedule_update_ha_state()

    @property
    def available(self) -> bool:
        """Always available (returns empty list when no data)."""
        return True

    @property
    def native_value(self) -> str:
        """Return comma-separated person names in this zone, or 'none'."""
        persons = self._get_zone_persons()
        return ", ".join(persons) if persons else "none"

    @property
    def extra_state_attributes(self) -> dict:
        """Return person list, count, and zone name."""
        persons = self._get_zone_persons()
        return {
            "persons": persons,
            "count": len(persons),
            "zone": self.zone,
        }

    def _get_zone_persons(self) -> list[str]:
        """Return sorted list of person IDs in this zone."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            if not person_coordinator or not person_coordinator.data:
                return []

            zone_rooms = {
                coord.entry.data.get("room_name", "")
                for coord in self._get_zone_coordinators()
            }
            if not zone_rooms:
                return []

            seen: set[str] = set()
            for person_id, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location and location in zone_rooms:
                    seen.add(person_id)

            return sorted(seen)
        except Exception as exc:
            _LOGGER.error(
                "ZoneIdentifiedPersonsSensor '%s': error reading person data: %s",
                self.zone,
                exc,
            )
            return []


class ZoneGuestCountSensor(ZoneSensorBase, SensorEntity):
    """Sensor: Estimated guest (unidentified) count for this zone.

    Uses house-level PersonCensus total minus BLE-identified total.
    Guests = camera_total - ble_identified_total (clamped to 0).
    Disabled by default.
    """

    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:account-question"
    _attr_native_unit_of_measurement = "people"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        self._attr_unique_id = f"{DOMAIN}_zone_{zone}_{SENSOR_ZONE_GUEST_COUNT}"
        self._attr_name = "Guest Count"
        self._guest_count: int = 0

    @property
    def available(self) -> bool:
        """Always available."""
        return True

    @property
    def native_value(self) -> int:
        """Return estimated guest count."""
        return self._get_guest_count()

    @property
    def extra_state_attributes(self) -> dict:
        """Return census totals used to derive the guest count."""
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        camera_total = 0
        ble_total = 0
        confidence = "none"

        if census and census.last_result:
            camera_total = census.last_result.house.total_persons
            confidence = census.last_result.house.confidence

        if person_coordinator and person_coordinator.data:
            ble_total = len([
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == "active"
            ])

        return {
            "camera_total": camera_total,
            "ble_total": ble_total,
            "zone": self.zone,
            "confidence": confidence,
        }

    def _get_guest_count(self) -> int:
        """Calculate guest count from census minus BLE."""
        try:
            census = self.hass.data.get(DOMAIN, {}).get("census")
            person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

            if not census or census.last_result is None:
                return 0

            camera_total = census.last_result.house.total_persons

            ble_total = 0
            if person_coordinator and person_coordinator.data:
                ble_total = len([
                    pid for pid, info in person_coordinator.data.items()
                    if info.get("tracking_status") == "active"
                ])

            return max(0, camera_total - ble_total)
        except Exception as exc:
            _LOGGER.error(
                "ZoneGuestCountSensor '%s': error calculating guest count: %s",
                self.zone,
                exc,
            )
            return 0


# ============================================================================
# v3.6.0-c1: Zone Presence Status Sensor
# ============================================================================


class ZonePresenceStatusSensor(ZoneSensorBase, SensorEntity):
    """Zone presence status from the Presence Coordinator.

    Entity: sensor.ura_{zone_slug}_presence_status
    Device: URA: Zone {zone_name}
    State: away / occupied / sleep / unknown
    """

    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: str) -> None:
        """Initialize."""
        super().__init__(hass, entry, zone)
        zone_slug = zone.lower().replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_zone_{zone_slug}_presence_status"
        self._attr_name = "Zone Presence Status"

    @property
    def native_value(self) -> str:
        """Return the current zone presence mode."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        presence = manager.coordinators.get("presence")
        if presence is None:
            return "unknown"
        tracker = presence.zone_trackers.get(self.zone)
        if tracker is None:
            return "unknown"
        return tracker.mode

    @property
    def extra_state_attributes(self) -> dict:
        """Return zone presence details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"debug_reason": "no_coordinator_manager"}
        presence = manager.coordinators.get("presence")
        if presence is None:
            return {
                "debug_reason": "no_presence_coordinator",
                "available_coordinators": list(manager.coordinators.keys()),
            }
        tracker = presence.zone_trackers.get(self.zone)
        if tracker is None:
            return {
                "debug_reason": "no_tracker_for_zone",
                "zone_requested": self.zone,
                "available_zones": list(presence.zone_trackers.keys()),
                "zone_tracker_count": len(presence.zone_trackers),
            }
        return tracker.to_dict()


# ============================================================================
# v4.6.12 Cycle B: DASHBOARD AGGREGATOR SENSORS
# ============================================================================


def _get_hvac_coordinator(hass: HomeAssistant):
    """Get the HVAC coordinator instance (lazy, survives reloads)."""
    manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
    if manager is None:
        return None
    return manager.coordinators.get("hvac")


class ZoneMotionEventCountSensor(AggregationEntity, SensorEntity):
    """Diagnostic sensor: count of zones with motion in the last 5 minutes.

    v4.6.12: New aggregator sensor for dashboard House tab. Counts DISTINCT
    zones (per CONF_ZONE) where at least one room coordinator's
    `_last_motion_time` is within ZONE_MOTION_WINDOW_SECONDS of now.
    """

    _attr_icon = "mdi:motion-sensor"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "zones"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_zones_with_motion"
        self._attr_name = "Zones With Motion"

    def _compute_zones_with_motion(self) -> set[str]:
        """Single-pass zone-with-motion computation shared by both properties.

        Review C C2: extracting this guarantees native_value and
        extra_state_attributes see the same snapshot — no TOCTOU between
        property reads, and no double-iteration of room coordinators.
        """
        now = dt_util.utcnow()
        window = timedelta(seconds=ZONE_MOTION_WINDOW_SECONDS)
        zones_with_motion: set[str] = set()
        for coord in _get_room_coordinators(self.hass):
            try:
                last = coord._last_motion_time
            except AttributeError:
                continue
            if last is None:
                continue
            # bug class #21: tolerate naive datetimes
            if last.tzinfo is None:
                last = last.replace(tzinfo=dt_util.UTC)
            if (now - last) > window:
                continue
            # bug class #14: options first, then data
            zone = coord.entry.options.get(CONF_ZONE) or coord.entry.data.get(CONF_ZONE)
            if zone:
                zones_with_motion.add(zone)
        return zones_with_motion

    @property
    def native_value(self) -> int:
        """Return count of distinct zones with motion in the last 5 minutes."""
        return len(self._compute_zones_with_motion())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-zone last-motion context (no async, no DB, no mutation)."""
        return {
            "zones": sorted(self._compute_zones_with_motion()),
            "window_minutes": ZONE_MOTION_WINDOW_SECONDS // 60,
        }


class HouseSystemDemandSensor(AggregationEntity, SensorEntity):
    """Sensor: HVAC system demand — % of zones actively heating or cooling.

    v4.6.12: New aggregator for HVAC tab header. Defined as
    round((zones_in_call / total_zones) * 100) using `zone.hvac_action` from
    the HVAC ZoneManager (mirrors hvac.py:1514). Returns None when HVAC
    coordinator is unavailable or zero zones are configured.
    """

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:hvac"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_system_demand"
        self._attr_name = "HVAC System Demand"

    @property
    def available(self) -> bool:
        """Available only when HVAC coordinator is present."""
        return _get_hvac_coordinator(self.hass) is not None

    @property
    def native_value(self) -> int | None:
        """Return percentage of zones actively heating or cooling."""
        hvac = _get_hvac_coordinator(self.hass)
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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return zone breakdown and load bucket (no async, no DB, no mutation)."""
        hvac = _get_hvac_coordinator(self.hass)
        if hvac is None:
            return {}
        try:
            zones = hvac.zone_manager.zones
        except AttributeError:
            return {}
        # Review C M3: compute pct locally from the already-fetched zones
        # snapshot rather than re-invoking the value property (which would do
        # a second coordinator lookup + second zones iteration).
        active_names = sorted(
            z.zone_name for z in zones.values()
            if z.hvac_action in ("cooling", "heating")
        )
        total = len(zones)
        pct = int(round((len(active_names) / total) * 100)) if total else 0
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
            "total_zones": total,
            "load_bucket": bucket,
            "formula": "active_zones / total_zones",
        }


class EnergyGridDemandSensor(AggregationEntity, SensorEntity):
    """Sensor: current grid import as a percentage of the configured grid cap.

    v4.6.12: New aggregator for the Energy tab. Reads
    EnergyCoordinator._grid_import_cap_kw + live net_power_w (mirrors
    energy.py:1453). Does NOT clamp at 100% — dashboard surfaces excess.

    B4 live-health repair (2026-06-10): the prior `available` gate returned
    False whenever the EV Grid Import Cap option was disabled or set to 0,
    leaving this sensor permanently `unavailable` on installs that don't use
    the cap. Operator instruction: report cleanly via attribute instead of
    permanent unavailable. Now the sensor stays available whenever the EC is
    registered; when the cap is disabled / unset / live net_power_w missing,
    `native_value` returns None (HA shows "Unknown") and
    `extra_state_attributes['unconfigured_reason']` explains why, while
    `grid_import_kw` continues to surface the live whole-house import
    derived from the same EC battery/Envoy CT path that feeds the rest of
    aggregation.py.
    """

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_grid_demand"
        self._attr_name = "Energy Grid Demand"

    @property
    def available(self) -> bool:
        """Available whenever the Energy Coordinator is registered.

        B4 repair: do NOT gate on cap-enabled / cap-kw > 0. Those conditions
        are exposed via `unconfigured_reason` instead so the entity is never
        permanently `unavailable` on installs that don't use the EV cap.
        """
        return _get_energy_coordinator(self.hass) is not None

    @property
    def native_value(self) -> float | None:
        """Return grid import as % of cap. None when cap not configured.

        B4 review A-M2 / B-L2 (2026-06-10): branch order matches
        extra_state_attributes (cap_enabled checked first, then cap_kw, then
        net_power_w) so the two surfaces always agree on which input is the
        blocker. Broad Exception guard mirrors the attrs path — Bug Class #14
        (teardown race) defense in depth.
        """
        ec = _get_energy_coordinator(self.hass)
        if ec is None:
            return None
        if not getattr(ec, "_grid_import_cap_enabled", False):
            return None
        cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
        if cap_kw <= 0:
            return None
        try:
            net_w = getattr(getattr(ec, "_battery", None), "net_power_w", None)
        except Exception:  # battery teardown race — Bug Class #14 guard
            _LOGGER.debug("EnergyGridDemandSensor: battery read failed", exc_info=True)
            return None
        if net_w is None:
            return None
        grid_kw = max(net_w, 0) / 1000.0
        return round((grid_kw / cap_kw) * 100.0, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return grid import detail (no async, no DB, no mutation).

        B4 repair: always exposes `grid_import_kw` (live whole-house import,
        derived from EC battery / Envoy CT) and an `unconfigured_reason` key
        that names the missing input when `native_value` is None.

        B4 review A-L1 (2026-06-10): the prior `energy_coordinator_unavailable`
        reason branch was dead — when EC is missing, `available` is False so
        HA never reads extra_state_attributes. Removed; EC-missing now returns
        an empty dict to make the unreachable state explicit.
        """
        ec = _get_energy_coordinator(self.hass)
        if ec is None:
            # Unreachable: `available` is False here so HA won't query attrs.
            return {}
        cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
        cap_enabled = getattr(ec, "_grid_import_cap_enabled", False)
        battery = getattr(ec, "_battery", None)
        try:
            net_w = getattr(battery, "net_power_w", None)
        except Exception:  # battery teardown race — Bug Class #14 guard
            _LOGGER.debug("EnergyGridDemandSensor: battery read failed", exc_info=True)
            net_w = None
        grid_kw: float | None = None
        if net_w is not None:
            grid_kw = round(max(net_w, 0) / 1000.0, 3)

        # Determine which input (if any) blocks % computation.
        # Branch order matches native_value: cap_enabled → cap_kw → net_w.
        unconfigured_reason: str | None = None
        if not cap_enabled:
            unconfigured_reason = "grid_import_cap_disabled"
        elif cap_kw <= 0:
            unconfigured_reason = "grid_import_cap_kw_unset"
        elif net_w is None:
            unconfigured_reason = "net_power_w_unavailable"

        attrs: dict[str, Any] = {
            "grid_import_kw": grid_kw,
            "grid_import_cap_kw": cap_kw,
            "grid_import_cap_enabled": cap_enabled,
            "exporting": net_w is not None and net_w < 0,
        }
        if unconfigured_reason is not None:
            attrs["unconfigured_reason"] = unconfigured_reason
        return attrs

"""Data coordinator for Universal Room Automation."""
#
# Universal Room Automation v3.9.11
# Build: 2026-01-02
# File: coordinator.py
# v3.2.8: Support for active state change listeners in aggregation sensors
# NEW: get_became_occupied_time() for three-tier scanner disambiguation
# FIX: Environmental sensors now read from options (user changes) with data fallback
#

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    SCAN_INTERVAL_OCCUPANCY,
    CONF_MOTION_SENSORS,
    CONF_MMWAVE_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_DOOR_SENSORS,
    CONF_OCCUPANCY_TIMEOUT,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_ILLUMINANCE_SENSOR,
    CONF_POWER_SENSORS,
    CONF_ENERGY_SENSOR,
    CONF_ELECTRICITY_RATE,
    DEFAULT_OCCUPANCY_TIMEOUT,
    DEFAULT_ELECTRICITY_RATE,
    STATE_OCCUPIED,
    STATE_MOTION_DETECTED,
    STATE_PRESENCE_DETECTED,
    STATE_TEMPERATURE,
    STATE_HUMIDITY,
    STATE_ILLUMINANCE,
    STATE_DARK,
    STATE_TIMEOUT_REMAINING,
    STATE_BLE_PERSONS,
    STATE_OCCUPANCY_SOURCE,
    STATE_POWER_CURRENT,
    STATE_ENERGY_TODAY,
    STATE_ENERGY_WEEKLY,
    STATE_ENERGY_MONTHLY,
    STATE_ENERGY_COST_WEEKLY,
    STATE_ENERGY_COST_MONTHLY,
    STATE_COST_PER_HOUR,
    STATE_NEXT_OCCUPANCY_TIME,
    STATE_NEXT_OCCUPANCY_IN,
    STATE_OCCUPANCY_PCT_7D,
    STATE_PEAK_OCCUPANCY_TIME,
    STATE_PRECOOL_START_TIME,
    STATE_PREHEAT_START_TIME,
    STATE_PRECOOL_LEAD_MINUTES,
    STATE_PREHEAT_LEAD_MINUTES,
    STATE_OCCUPANCY_CONFIDENCE,
    STATE_LIGHTS_ON_COUNT,
    STATE_FANS_ON_COUNT,
    STATE_SWITCHES_ON_COUNT,
    STATE_COVERS_OPEN_COUNT,
    STATE_COVERS_POSITION_AVG,
    STATE_TIME_SINCE_MOTION,
    STATE_TIME_SINCE_OCCUPIED,
    DEFAULT_DARK_THRESHOLD,
    CONF_AREA_ID,
    # v3.0.0 entry type constants
    ENTRY_TYPE_INTEGRATION,
    CONF_ENTRY_TYPE,
    CONF_INTEGRATION_ENTRY_ID,
    CONF_OVERRIDE_NOTIFICATIONS,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_OUTSIDE_HUMIDITY_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_LEVEL,
    CONF_EXIT_LIGHT_ACTION,
    LIGHT_ACTION_TURN_OFF,
)
from .automation import RoomAutomation

_LOGGER = logging.getLogger(__name__)

MAX_OCCUPANCY_DURATION_SECONDS = 4 * 3600  # 4-hour failsafe


class UniversalRoomCoordinator(DataUpdateCoordinator):
    """Coordinator to manage room automation data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        # v3.2.8 STARTUP BANNER
        room_name = entry.data.get('room_name', 'Unknown')
        _LOGGER.info("Coordinator initialized for room: %s", room_name)
        
        self.entry = entry
        self._last_motion_time: datetime | None = None
        self._last_occupied_time: datetime | None = None  # Track when room was last occupied
        self._last_occupied_state = False
        self._became_occupied_time: datetime | None = None  # v3.2.4: When current occupancy session started
        self._unsub_state_listeners = []

        # Debounce: require sensors active for N seconds before confirming entry
        self._occupancy_first_detected: datetime | None = None
        self._occupancy_debounce_seconds: float = 0.5  # seconds sensor must stay on
        self._debounce_refresh_unsub = None  # cancel handle for scheduled debounce refresh

        # Sensor unavailability grace: hold state if all sensors go unavailable
        self._all_sensors_unavailable_since: datetime | None = None
        self._unavail_grace_seconds: int = 60

        # Stuck sensor tracking: per-sensor continuous-on timestamps
        self._sensor_on_since: dict[str, datetime] = {}
        self._stuck_sensor_hours: float = 4.0  # hours before flagging stuck

        # Energy accumulator timing
        self._last_energy_calc_time: datetime | None = None

        # Failsafe tracking
        self._failsafe_fired: bool = False

        # Exit verify tracking (for automation health sensor)
        self._last_exit_verify_result: str | None = None  # "skipped_reoccupied" / "retried" / "confirmed" / "retry_failed"
        self._last_exit_verify_time: datetime | None = None
        
        # Use _get_config for timeout (will work after __init__ completes)
        # Store entry for later _get_config calls
        self._occupancy_timeout = entry.options.get(
            CONF_OCCUPANCY_TIMEOUT, 
            entry.data.get(CONF_OCCUPANCY_TIMEOUT, DEFAULT_OCCUPANCY_TIMEOUT)
        )
        
        # Energy tracking
        self._energy_accumulator = 0.0
        self._last_power_reading = None
        self._last_energy_reset = dt_util.now().replace(hour=0, minute=0, second=0)
        
        # Energy sensor baselines for delta calculation (when using direct energy sensors)
        self._energy_baseline_today = 0.0
        self._energy_baseline_week = 0.0
        self._energy_baseline_month = 0.0
        self._last_week_reset = dt_util.now()
        self._last_month_reset = dt_util.now().replace(day=1)
        
        # Environmental data logging
        self._last_env_log = None
        self._last_energy_log = None
        
        # Automation tracking
        self._last_trigger_source = None  # "motion", "presence", "door"
        self._last_trigger_entity = None  # entity_id that triggered
        self._last_trigger_time = None    # datetime
        self._last_action_description = None  # "Turned on 3 lights"
        self._last_action_entity = None   # entity_id or list
        self._last_action_type = None     # "turn_on", "turn_off", etc.
        self._last_action_time = None     # datetime
        
        # v3.2.2.0 FIX: Merge entry.options with entry.data
        # entry.data = initial setup
        # entry.options = user changes via Configure button
        # options should override data!
        config = {**entry.data, **entry.options}
        
        # Automation handler
        self.automation = RoomAutomation(hass, config, self)
        
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data.get('room_name', 'unknown')}",
            update_interval=SCAN_INTERVAL_OCCUPANCY,
        )
    
    # =========================================================================
    # v3.0.0 CONFIG HELPER METHODS
    # =========================================================================
    
    def _get_config(self, key: str, default: Any = None) -> Any:
        """Get config value from options with data fallback.
        
        This follows the HA pattern:
        1. First check entry.options (changed via options flow)
        2. Then check entry.data (initial config)
        3. Finally use default
        """
        return self.entry.options.get(
            key, self.entry.data.get(key, default)
        )
    
    def _get_integration_entry(self):
        """Get the parent integration entry.
        
        Room entries store a reference to their integration entry
        via CONF_INTEGRATION_ENTRY_ID.
        """
        integration_id = self.entry.data.get(CONF_INTEGRATION_ENTRY_ID)
        if not integration_id:
            # Fallback: try to find integration entry directly
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                    return entry
            return None
        return self.hass.config_entries.async_get_entry(integration_id)
    
    def _get_global_config(self, key: str, default: Any = None) -> Any:
        """Get config value from integration entry.
        
        For integration-level settings like:
        - Outside temp sensor
        - Weather entity
        - Solar production sensor
        - Default electricity rate
        - Default notifications
        """
        integration_entry = self._get_integration_entry()
        if not integration_entry:
            # No integration entry - fall back to room config
            return self._get_config(key, default)
        
        return integration_entry.options.get(
            key, integration_entry.data.get(key, default)
        )
    
    def _get_notification_config(self, key: str, default: Any = None) -> Any:
        """Get notification config with room override support.
        
        If room has override_notifications=True, use room settings.
        Otherwise, use integration defaults.
        """
        if self._get_config(CONF_OVERRIDE_NOTIFICATIONS, False):
            # Room override enabled - use room settings
            return self._get_config(key, default)
        
        # Use integration defaults
        return self._get_global_config(key, default)
    
    def _get_electricity_rate(self) -> float:
        """Get electricity rate with proper fallback chain.
        
        1. Room-level rate (if set)
        2. Integration-level default rate
        3. Constant default
        """
        room_rate = self._get_config(CONF_ELECTRICITY_RATE)
        if room_rate is not None:
            return room_rate
        
        return self._get_global_config(CONF_ELECTRICITY_RATE, DEFAULT_ELECTRICITY_RATE)
    
    async def async_config_entry_first_refresh(self) -> None:
        """Perform first refresh and set up event listeners.
        
        v3.2.2.0 FIX: Moved from async_added_to_hass which never runs on coordinators!
        Coordinators are NOT entities, so async_added_to_hass is never called.
        async_config_entry_first_refresh IS called once during coordinator setup.
        """
        room_name = self.entry.data.get("room_name", "Unknown")
        _LOGGER.debug("async_config_entry_first_refresh called for room: %s", room_name)
        
        # Call parent first_refresh to fetch initial data
        await super().async_config_entry_first_refresh()
        
        # NOW set up event listeners (after coordinator is fully initialized)
        # Listen to all configured sensors for immediate updates
        sensors_to_track = []
        
        # v3.2.3.2: Use _get_config for sensor lists to pick up options changes
        # Add motion sensors
        motion_sensors = self._get_config(CONF_MOTION_SENSORS, [])
        _LOGGER.debug("Room %s motion sensors: %s", room_name, motion_sensors)
        if motion_sensors:
            sensors_to_track.extend(motion_sensors)
        
        # Add mmWave sensors
        mmwave_sensors = self._get_config(CONF_MMWAVE_SENSORS, [])
        _LOGGER.debug("Room %s mmwave sensors: %s", room_name, mmwave_sensors)
        if mmwave_sensors:
            sensors_to_track.extend(mmwave_sensors)
        
        # Add occupancy sensors (combined motion+presence)
        occupancy_sensors = self._get_config(CONF_OCCUPANCY_SENSORS, [])
        _LOGGER.debug("Room %s occupancy sensors: %s", room_name, occupancy_sensors)
        if occupancy_sensors:
            sensors_to_track.extend(occupancy_sensors)
        
        # v3.2.3.2 FIX: Use _get_config to pick up sensor changes from options flow
        # Add environmental sensors (only if they exist)
        if temp := self._get_config(CONF_TEMPERATURE_SENSOR):
            sensors_to_track.append(temp)
        if humidity := self._get_config(CONF_HUMIDITY_SENSOR):
            sensors_to_track.append(humidity)
        if lux := self._get_config(CONF_ILLUMINANCE_SENSOR):
            sensors_to_track.append(lux)
        
        # Add power sensors
        power_sensors = self._get_config(CONF_POWER_SENSORS, [])
        if power_sensors:
            sensors_to_track.extend(power_sensors)
        
        _LOGGER.debug("Room %s total sensors to track: %d - %s", room_name, len(sensors_to_track), sensors_to_track)
        
        # Set up listener for immediate coordinator refresh
        if sensors_to_track:
            @callback
            def sensor_state_changed(event):
                """Handle sensor state changes with motion event logging."""
                entity_id = event.data.get("entity_id", "")
                new_state = event.data.get("new_state")
                old_state = event.data.get("old_state")
                new_val = new_state.state if new_state else "None"
                old_val = old_state.state if old_state else "None"

                # RESILIENCE-002: Log motion/occupancy sensor transitions
                if entity_id in (motion_sensors + mmwave_sensors + occupancy_sensors):
                    _LOGGER.info(
                        "Room %s: Sensor %s changed %s -> %s",
                        room_name, entity_id, old_val, new_val,
                    )

                self.hass.async_create_task(self.async_refresh())
            
            self._unsub_state_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    sensors_to_track,
                    sensor_state_changed
                )
            )
            
            _LOGGER.info(
                "Room %s: Event-driven mode active - tracking %d sensors",
                room_name,
                len(sensors_to_track)
            )
        else:
            _LOGGER.warning(
                "Room %s: No motion/occupancy sensors configured - using 30-second polling mode. "
                "Configure sensors for faster response.",
                room_name
            )
    
    @callback
    def _debounce_refresh_callback(self, _now=None) -> None:
        """Re-evaluate occupancy after debounce period expires."""
        self._debounce_refresh_unsub = None
        self.hass.async_create_task(self.async_refresh())

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from state listeners."""
        if self._debounce_refresh_unsub is not None:
            self._debounce_refresh_unsub()
            self._debounce_refresh_unsub = None
        for unsub in self._unsub_state_listeners:
            unsub()
        self._unsub_state_listeners.clear()
    
    def _is_sensor_on(self, entity_id: str) -> bool:
        """Check if a binary sensor is on."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        if state.state in ("unavailable", "unknown"):
            _LOGGER.warning(
                "Sensor %s is %s - treating as off for room %s",
                entity_id, state.state,
                self.entry.data.get("room_name", "unknown"),
            )
            return False
        return state.state == "on"
    
    def _get_sensor_value(self, entity_id: str | None, default: Any = None) -> Any:
        """Get numeric sensor value with fallback."""
        if not entity_id:
            return default
        
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return default
        
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default
    
    def _get_room_area(self) -> str | None:
        """Return the HA area_id for this room.

        Reads CONF_AREA_ID from the room config entry (options override data).
        Returns None if no area is configured.
        """
        return self._get_config(CONF_AREA_ID)

    def _get_entities_in_area(self, area_id: str, domain: str) -> list[str]:
        """Get entities of domain in area."""
        if not area_id:
            return []
        
        ent_reg = er.async_get(self.hass)
        return [
            entity.entity_id
            for entity in ent_reg.entities.values()
            if entity.area_id == area_id and entity.domain == domain
        ]
    
    def _calculate_device_counts(self, area_id: str) -> dict[str, Any]:
        """Calculate device counts in area."""
        counts = {
            "lights_on": 0,
            "fans_on": 0,
            "switches_on": 0,
            "covers_open": 0,
            "covers_position_avg": 0,
        }
        
        if not area_id:
            return counts
        
        # Count lights (guard against removed entities)
        lights = self._get_entities_in_area(area_id, "light")
        counts["lights_on"] = sum(
            1 for light in lights
            if (s := self.hass.states.get(light)) is not None and s.state == "on"
        )

        # Count fans
        fans = self._get_entities_in_area(area_id, "fan")
        counts["fans_on"] = sum(
            1 for fan in fans
            if (s := self.hass.states.get(fan)) is not None and s.state == "on"
        )

        # Count switches
        switches = self._get_entities_in_area(area_id, "switch")
        counts["switches_on"] = sum(
            1 for switch in switches
            if (s := self.hass.states.get(switch)) is not None and s.state == "on"
        )

        # Count and average covers
        covers = self._get_entities_in_area(area_id, "cover")
        open_covers = 0
        total_position = 0
        cover_count = 0

        for cover in covers:
            state = self.hass.states.get(cover)
            if state is None:
                continue
            if state.state == "open":
                open_covers += 1
            if position := state.attributes.get("current_position"):
                total_position += position
                cover_count += 1
        
        counts["covers_open"] = open_covers
        counts["covers_position_avg"] = (
            total_position / cover_count if cover_count > 0 else 0
        )
        
        return counts
    
    def _is_automation_enabled(self) -> bool:
        """Check if automation switch is enabled."""
        # Look for the automation switch entity
        automation_switch = f"switch.{self.entry.data.get('room_name', 'unknown').lower().replace(' ', '_')}_automation"
        state = self.hass.states.get(automation_switch)
        if state is None:
            return True  # Default to enabled if switch not found
        return state.state == "on"
    
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from sensors."""
        now = dt_util.now()
        data = {}
        
        # === Phase 1: Occupancy Detection ===
        # v3.2.3.2: Use _get_config for all sensor lists
        motion_sensors = self._get_config(CONF_MOTION_SENSORS, [])
        mmwave_sensors = self._get_config(CONF_MMWAVE_SENSORS, [])
        occupancy_sensors = self._get_config(CONF_OCCUPANCY_SENSORS, [])
        room_name = self.entry.data.get("room_name", "unknown")

        # BUG-001: Log unavailable sensors for diagnostics
        for sensor_list_name, sensor_list in [
            ("motion", motion_sensors),
            ("mmwave", mmwave_sensors),
            ("occupancy", occupancy_sensors),
        ]:
            for sensor in sensor_list:
                if sensor:
                    s = self.hass.states.get(sensor)
                    if s and s.state in ("unavailable", "unknown"):
                        _LOGGER.warning(
                            "Room %s: %s sensor %s is %s",
                            room_name, sensor_list_name, sensor, s.state,
                        )

        # === Fix #10: Sensor unavailability grace period ===
        all_sensors = [s for s in (motion_sensors + mmwave_sensors + occupancy_sensors) if s]
        all_unavailable = all_sensors and all(
            (st := self.hass.states.get(s)) is not None and st.state in ("unavailable", "unknown")
            for s in all_sensors
        )
        grace_hold = False
        if all_unavailable:
            if self._all_sensors_unavailable_since is None:
                self._all_sensors_unavailable_since = now
                _LOGGER.warning(
                    "Room %s: All %d sensors unavailable — holding occupancy state for %ds",
                    room_name, len(all_sensors), self._unavail_grace_seconds,
                )
            grace_elapsed = (now - self._all_sensors_unavailable_since).total_seconds()
            if grace_elapsed < self._unavail_grace_seconds:
                grace_hold = True
        else:
            self._all_sensors_unavailable_since = None

        # === Fix #9: Stuck sensor detection (before detection + trigger tracking) ===
        for sensor_list in [motion_sensors, mmwave_sensors, occupancy_sensors]:
            for sensor in sensor_list:
                if not sensor:
                    continue
                if self._is_sensor_on(sensor):
                    if sensor not in self._sensor_on_since:
                        self._sensor_on_since[sensor] = now
                else:
                    self._sensor_on_since.pop(sensor, None)

        stuck_sensors = {
            s for s, since in self._sensor_on_since.items()
            if (now - since).total_seconds() / 3600 >= self._stuck_sensor_hours
        }
        if stuck_sensors:
            for s in stuck_sensors:
                on_hours = (now - self._sensor_on_since[s]).total_seconds() / 3600
                _LOGGER.warning(
                    "Room %s: Sensor %s stuck on for %.1f hours — ignoring",
                    room_name, s, on_hours,
                )

        # Check motion (excluding stuck sensors)
        motion_detected = any(
            self._is_sensor_on(sensor) for sensor in motion_sensors
            if sensor and sensor not in stuck_sensors
        )
        data[STATE_MOTION_DETECTED] = motion_detected

        # Check presence/mmWave (excluding stuck sensors)
        presence_detected = any(
            self._is_sensor_on(sensor) for sensor in mmwave_sensors
            if sensor and sensor not in stuck_sensors
        )
        data[STATE_PRESENCE_DETECTED] = presence_detected

        # Check occupancy sensors (excluding stuck sensors)
        occupancy_detected = any(
            self._is_sensor_on(sensor) for sensor in occupancy_sensors
            if sensor and sensor not in stuck_sensors
        )

        # Override detection to false during grace hold
        if grace_hold:
            motion_detected = False
            presence_detected = False
            occupancy_detected = False
            data[STATE_MOTION_DETECTED] = False
            data[STATE_PRESENCE_DETECTED] = False

        # Track which sensor triggered (after stuck filtering)
        if motion_detected and (not self.data or not self.data.get(STATE_MOTION_DETECTED)):
            for sensor in motion_sensors:
                if sensor and sensor not in stuck_sensors and self._is_sensor_on(sensor):
                    self._last_trigger_source = "motion"
                    self._last_trigger_entity = sensor
                    self._last_trigger_time = now
                    break

        if presence_detected and (not self.data or not self.data.get(STATE_PRESENCE_DETECTED)):
            for sensor in mmwave_sensors:
                if sensor and sensor not in stuck_sensors and self._is_sensor_on(sensor):
                    self._last_trigger_source = "presence"
                    self._last_trigger_entity = sensor
                    self._last_trigger_time = now
                    break

        if occupancy_detected:
            for sensor in occupancy_sensors:
                if sensor and sensor not in stuck_sensors and self._is_sensor_on(sensor):
                    if not motion_detected and not presence_detected:
                        self._last_trigger_source = "occupancy"
                        self._last_trigger_entity = sensor
                        self._last_trigger_time = now
                    break

        any_sensor_active = motion_detected or presence_detected or occupancy_detected

        # === Fix #6: Entry debouncing (time-based) ===
        # Require sensors active for N seconds before confirming new entry.
        # When debounce blocks, schedule a follow-up refresh so we don't
        # wait for the 30s polling interval to confirm occupancy.
        if any_sensor_active:
            if not self._last_occupied_state:
                if self._occupancy_first_detected is None:
                    self._occupancy_first_detected = now
                elapsed = (now - self._occupancy_first_detected).total_seconds()
                if elapsed < self._occupancy_debounce_seconds:
                    _LOGGER.debug(
                        "Room %s: Occupancy debounce %.1f/%.1fs — waiting",
                        room_name, elapsed, self._occupancy_debounce_seconds,
                    )
                    any_sensor_active = False
                    # Schedule follow-up refresh after debounce expires
                    if self._debounce_refresh_unsub is None:
                        remaining = self._occupancy_debounce_seconds - elapsed + 0.05
                        self._debounce_refresh_unsub = async_call_later(
                            self.hass,
                            remaining,
                            self._debounce_refresh_callback,
                        )
                else:
                    # Debounce passed — cancel any pending follow-up
                    if self._debounce_refresh_unsub is not None:
                        self._debounce_refresh_unsub()
                        self._debounce_refresh_unsub = None
        else:
            self._occupancy_first_detected = None
            if self._debounce_refresh_unsub is not None:
                self._debounce_refresh_unsub()
                self._debounce_refresh_unsub = None

        # Determine occupancy (any detection method)
        # Track which source is driving occupancy for sensor exposure
        data[STATE_BLE_PERSONS] = []
        if grace_hold:
            # Hold previous occupancy state during sensor unavailability grace
            data[STATE_OCCUPIED] = self._last_occupied_state
            data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout if self._last_occupied_state else 0
            data[STATE_OCCUPANCY_SOURCE] = "grace_hold" if self._last_occupied_state else "none"
        elif any_sensor_active:
            self._last_motion_time = now
            self._failsafe_fired = False  # Reset failsafe flag on genuine activity
            data[STATE_OCCUPIED] = True
            data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout
            # Determine primary source
            if motion_detected:
                data[STATE_OCCUPANCY_SOURCE] = "motion"
            elif presence_detected:
                data[STATE_OCCUPANCY_SOURCE] = "mmwave"
            else:
                data[STATE_OCCUPANCY_SOURCE] = "occupancy_sensor"

            # Update last occupied time when becoming occupied
            if not self._last_occupied_state:
                self._last_occupied_time = now
                self._became_occupied_time = now
        else:
            # Calculate timeout
            if self._last_motion_time:
                elapsed = (now - self._last_motion_time).total_seconds()
                remaining = max(0, self._occupancy_timeout - int(elapsed))
                data[STATE_TIMEOUT_REMAINING] = remaining
                data[STATE_OCCUPIED] = remaining > 0

                # Keep last_occupied_time updated while still occupied
                if data[STATE_OCCUPIED]:
                    self._last_occupied_time = now
                    data[STATE_OCCUPANCY_SOURCE] = "timeout"
                else:
                    self._became_occupied_time = None
                    data[STATE_OCCUPANCY_SOURCE] = "none"
            else:
                data[STATE_TIMEOUT_REMAINING] = 0
                data[STATE_OCCUPIED] = False
                data[STATE_OCCUPANCY_SOURCE] = "none"
                self._became_occupied_time = None
        
        # Calculate time since last motion
        if self._last_motion_time:
            data[STATE_TIME_SINCE_MOTION] = int((now - self._last_motion_time).total_seconds())
        else:
            data[STATE_TIME_SINCE_MOTION] = None
        
        # Calculate time since last occupied
        if self._last_occupied_time:
            data[STATE_TIME_SINCE_OCCUPIED] = int((now - self._last_occupied_time).total_seconds())
        else:
            data[STATE_TIME_SINCE_OCCUPIED] = None

        # RESILIENCE-001: Maximum active duration failsafe
        # Uses _became_occupied_time so legitimate motion doesn't reset the timer
        if (data.get(STATE_OCCUPIED)
                and self._became_occupied_time):
            duration = (now - self._became_occupied_time).total_seconds()
            if duration > MAX_OCCUPANCY_DURATION_SECONDS:
                _LOGGER.warning(
                    "Room %s: Forcing vacancy after %.1f hours (failsafe)",
                    room_name, duration / 3600,
                )
                data[STATE_OCCUPIED] = False
                data[STATE_OCCUPANCY_SOURCE] = "failsafe"
                data[STATE_TIMEOUT_REMAINING] = 0
                self._last_motion_time = None
                self._failsafe_fired = True

        # === v3.5.1: Camera extends room occupancy ===
        # If motion/mmWave have timed out but a camera in this room's area still
        # sees a person, override vacancy and keep the room occupied.
        # Fix #8: Skip camera override if failsafe just fired (prevents stuck camera defeating failsafe)
        if not data.get(STATE_OCCUPIED) and not self._failsafe_fired:
            camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
            if camera_manager:
                room_area = self._get_room_area()
                if room_area:
                    person_sensors = camera_manager.get_person_sensor_for_area(room_area)
                    for person_sensor in person_sensors:
                        state = self.hass.states.get(person_sensor)
                        if state and state.state == "on":
                            data[STATE_OCCUPIED] = True
                            data[STATE_OCCUPANCY_SOURCE] = "camera"
                            data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout
                            if not self._last_motion_time:
                                self._last_motion_time = now
                            # Ensure failsafe timer tracks camera-held occupancy
                            if self._became_occupied_time is None:
                                self._became_occupied_time = now
                            if not self._last_occupied_state:
                                self._last_occupied_time = now
                            _LOGGER.debug(
                                "Room %s: Camera person sensor %s overrides vacancy — "
                                "person detected",
                                room_name,
                                person_sensor,
                            )
                            break

        # === v3.8.8: BLE/Bermuda extends room occupancy ===
        # If motion/mmWave/camera have timed out but person_coordinator knows
        # a tracked person is in this room via BLE, override vacancy.
        # Respects failsafe like camera override.
        # v3.8.9: Sparse BLE hardening — rooms using a shared scanner
        # (Tier 2 / CONF_SCANNER_AREAS) require recent motion/mmWave
        # confirmation. BLE alone cannot create occupancy for those rooms.
        if not data.get(STATE_OCCUPIED) and not self._failsafe_fired:
            person_coordinator = self.hass.data.get(DOMAIN, {}).get(
                "person_coordinator"
            )
            if person_coordinator:
                ble_persons = person_coordinator.get_persons_in_room(room_name)
                if ble_persons:
                    # Check if this room has direct BLE coverage (Tier 1)
                    # or shared/indirect coverage (Tier 2)
                    direct_ble = person_coordinator.is_room_direct_ble(
                        room_name
                    )

                    # Tier 2 rooms need recent motion to confirm BLE placement.
                    # "Recent" = motion within 2x occupancy timeout.
                    ble_allowed = direct_ble
                    if not direct_ble and self._last_motion_time:
                        motion_age = (now - self._last_motion_time).total_seconds()
                        if motion_age < self._occupancy_timeout * 2:
                            ble_allowed = True

                    if ble_allowed:
                        data[STATE_OCCUPIED] = True
                        data[STATE_OCCUPANCY_SOURCE] = "ble"
                        data[STATE_BLE_PERSONS] = list(ble_persons)
                        data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout
                        if not self._last_motion_time:
                            self._last_motion_time = now
                        # Ensure failsafe timer tracks BLE-held occupancy
                        if self._became_occupied_time is None:
                            self._became_occupied_time = now
                        if not self._last_occupied_state:
                            self._last_occupied_time = now
                        _LOGGER.debug(
                            "Room %s: BLE persons %s override vacancy "
                            "(tier=%s)",
                            room_name,
                            ble_persons,
                            "direct" if direct_ble else "shared+confirmed",
                        )
                    else:
                        # Populate ble_persons for diagnostic visibility
                        # even though BLE is not driving occupancy.
                        data[STATE_BLE_PERSONS] = list(ble_persons)
                        _LOGGER.debug(
                            "Room %s: BLE persons %s present but shared "
                            "scanner — no recent motion confirmation, "
                            "skipping BLE override",
                            room_name,
                            ble_persons,
                        )

        # Always populate ble_persons even when occupied by other sources
        # (single lookup, avoids double-call when BLE override already set it)
        if not data.get(STATE_BLE_PERSONS):
            person_coordinator = self.hass.data.get(DOMAIN, {}).get(
                "person_coordinator"
            )
            if person_coordinator:
                data[STATE_BLE_PERSONS] = list(
                    person_coordinator.get_persons_in_room(room_name)
                )

        # === Phase 1: Environmental Sensors ===
        # v3.2.3.2 FIX: Use _get_config to read from options (user changes) with data fallback
        # Previously used self.entry.data.get() which ignored options flow changes
        data[STATE_TEMPERATURE] = self._get_sensor_value(
            self._get_config(CONF_TEMPERATURE_SENSOR)
        )
        data[STATE_HUMIDITY] = self._get_sensor_value(
            self._get_config(CONF_HUMIDITY_SENSOR)
        )
        data[STATE_ILLUMINANCE] = self._get_sensor_value(
            self._get_config(CONF_ILLUMINANCE_SENSOR), 100
        )
        data[STATE_DARK] = data[STATE_ILLUMINANCE] < DEFAULT_DARK_THRESHOLD
        
        # === Phase 2: Energy Tracking ===
        # v3.2.3.2: Use _get_config for power/energy sensors
        power_sensors = self._get_config(CONF_POWER_SENSORS, [])
        total_power = sum(
            self._get_sensor_value(sensor, 0) for sensor in power_sensors
        )
        data[STATE_POWER_CURRENT] = total_power
        
        # Energy accumulation (if no direct energy sensor)
        energy_sensor = self._get_config(CONF_ENERGY_SENSOR)
        if energy_sensor:
            # Direct energy sensor (usually TOTAL_INCREASING from smart plug)
            current_value = self._get_sensor_value(energy_sensor, 0)
            
            # Initialize baseline on first run
            if self._energy_baseline_today == 0.0:
                self._energy_baseline_today = current_value
            
            # Reset baselines at midnight
            if now.date() > self._last_energy_reset.date():
                self._energy_baseline_today = current_value
                self._last_energy_reset = now
            
            # Calculate today's delta (today's energy = current - baseline_at_midnight)
            data[STATE_ENERGY_TODAY] = max(0, current_value - self._energy_baseline_today)
        else:
            # Integrate power over time (for rooms without direct energy sensor)
            if self._last_power_reading is not None and self._last_energy_calc_time is not None:
                elapsed_hours = (now - self._last_energy_calc_time).total_seconds() / 3600
                avg_power = (total_power + self._last_power_reading) / 2
                self._energy_accumulator += (avg_power * elapsed_hours) / 1000  # Wh to kWh
            self._last_power_reading = total_power
            self._last_energy_calc_time = now
            
            # Reset at midnight
            if now.date() > self._last_energy_reset.date():
                self._energy_accumulator = 0.0
                self._last_energy_reset = now
            
            data[STATE_ENERGY_TODAY] = self._energy_accumulator
        
        # === Phase 2: Device Counts ===
        area_id = self._get_config(CONF_AREA_ID)
        if area_id:
            device_counts = self._calculate_device_counts(area_id)
            data[STATE_LIGHTS_ON_COUNT] = device_counts["lights_on"]
            data[STATE_FANS_ON_COUNT] = device_counts["fans_on"]
            data[STATE_SWITCHES_ON_COUNT] = device_counts["switches_on"]
            data[STATE_COVERS_OPEN_COUNT] = device_counts["covers_open"]
            data[STATE_COVERS_POSITION_AVG] = device_counts["covers_position_avg"]
        
        # Track occupancy transition for DB logging (must be before _last_occupied_state update)
        was_occupied = self._last_occupied_state

        # === Automation Logic ===
        if self._is_automation_enabled():
            # Handle occupancy changes
            if data[STATE_OCCUPIED] != self._last_occupied_state:
                self._last_occupied_state = data[STATE_OCCUPIED]
                try:
                    await self.automation.handle_occupancy_change(
                        data[STATE_OCCUPIED],
                        data
                    )
                except Exception as e:
                    _LOGGER.error("Error in occupancy automation: %s", e)

                # RESILIENCE-003: Verify vacancy exit — non-blocking delayed task
                if was_occupied and not data[STATE_OCCUPIED]:
                    exit_action = self._get_config(CONF_EXIT_LIGHT_ACTION, LIGHT_ACTION_TURN_OFF)
                    if exit_action == LIGHT_ACTION_TURN_OFF:
                        self.hass.async_create_task(
                            self._delayed_exit_verify(room_name, data)
                        )
            
            # Periodic automation tasks (refresh config for options flow changes)
            self.automation._refresh_config()
            try:
                # Temperature-based fan control
                await self.automation.handle_temperature_based_fan_control(
                    data.get(STATE_TEMPERATURE),
                    data.get(STATE_OCCUPIED, False)
                )
                
                # Humidity-based fan control
                await self.automation.handle_humidity_based_fan_control(
                    data.get(STATE_HUMIDITY)
                )
                
                # v3.1.0: Shared space scheduled auto-off check
                await self.automation.check_scheduled_auto_off()
                await self.automation.check_auto_off_warning()

                # v3.6.38: Timed cover open/close (sunrise/sunset/time-based)
                await self.automation.check_timed_cover_open()
                await self.automation.check_timed_cover_close()
                
            except Exception as e:
                _LOGGER.error("Error in periodic automation: %s", e)
        else:
            # Even with automation disabled, track state for DB logging
            self._last_occupied_state = data[STATE_OCCUPIED]

        # === Data Logging (for Phase 3 & 4) ===
        database = self.hass.data[DOMAIN].get("database")
        if database:
            # Log occupancy changes (use was_occupied captured before _last_occupied_state update)
            if data[STATE_OCCUPIED] != was_occupied:
                if data[STATE_OCCUPIED]:
                    # Entry event
                    trigger = data.get(STATE_OCCUPANCY_SOURCE, "motion")
                    await database.log_occupancy_event(
                        self.entry.entry_id,
                        "entry",
                        trigger
                    )
                else:
                    # Exit event (calculate duration)
                    if self._last_motion_time:
                        duration = int((now - self._last_motion_time).total_seconds())
                        await database.log_occupancy_event(
                            self.entry.entry_id,
                            "exit",
                            None,
                            duration
                        )
            
            # Log environmental data (every 5 minutes)
            if self._last_env_log is None or (now - self._last_env_log).total_seconds() >= 300:
                await database.log_environmental_data(
                    self.entry.entry_id,
                    {
                        'temperature': data.get(STATE_TEMPERATURE),
                        'humidity': data.get(STATE_HUMIDITY),
                        'illuminance': data.get(STATE_ILLUMINANCE),
                        'occupied': data.get(STATE_OCCUPIED),
                    }
                )
                self._last_env_log = now
            
            # Log energy snapshots (every 5 minutes)
            if self._last_energy_log is None or (now - self._last_energy_log).total_seconds() >= 300:
                await database.log_energy_snapshot(
                    self.entry.entry_id,
                    {
                        'power_watts': total_power,
                        'occupied': data.get(STATE_OCCUPIED),
                        'lights_on': data.get(STATE_LIGHTS_ON_COUNT, 0),
                        'fans_on': data.get(STATE_FANS_ON_COUNT, 0),
                        'switches_on': data.get(STATE_SWITCHES_ON_COUNT, 0),
                        'covers_open': data.get(STATE_COVERS_OPEN_COUNT, 0),
                    }
                )
                self._last_energy_log = now
        
        # === Phase 2: Extended Energy Calculations ===
        if database:
            # Weekly energy
            week_ago = now - timedelta(days=7)
            data[STATE_ENERGY_WEEKLY] = await database.get_energy_for_period(
                self.entry.entry_id,
                week_ago,
                now
            )
            
            # Monthly energy
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            data[STATE_ENERGY_MONTHLY] = await database.get_energy_for_period(
                self.entry.entry_id,
                month_start,
                now
            )
            
            # Calculate costs
            electricity_rate = self._get_electricity_rate()
            
            if data.get(STATE_ENERGY_WEEKLY) is not None:
                data[STATE_ENERGY_COST_WEEKLY] = round(data[STATE_ENERGY_WEEKLY] * electricity_rate, 2)
            
            if data.get(STATE_ENERGY_MONTHLY) is not None:
                data[STATE_ENERGY_COST_MONTHLY] = round(data[STATE_ENERGY_MONTHLY] * electricity_rate, 2)
            
            # Cost per hour (from current power)
            if data.get(STATE_POWER_CURRENT) is not None:
                power_kw = data[STATE_POWER_CURRENT] / 1000.0
                data[STATE_COST_PER_HOUR] = round(power_kw * electricity_rate, 3)
        
        # === Phase 3: Prediction Queries ===
        if database:
            # Next occupancy prediction
            prediction = await database.get_next_occupancy_prediction(self.entry.entry_id)
            if prediction:
                next_time, confidence = prediction
                data[STATE_NEXT_OCCUPANCY_TIME] = next_time
                data[STATE_OCCUPANCY_CONFIDENCE] = confidence
                
                # Calculate minutes until next occupancy
                now_aware = now.replace(tzinfo=next_time.tzinfo) if next_time.tzinfo else now
                minutes_until = int((next_time - now_aware).total_seconds() / 60)
                data[STATE_NEXT_OCCUPANCY_IN] = max(0, minutes_until)  # Don't return negative
                
                # Calculate precool/preheat start times
                # Use static lead times for now (Phase 4 will make dynamic)
                precool_lead = 15  # minutes
                preheat_lead = 20  # minutes
                
                data[STATE_PRECOOL_START_TIME] = next_time - timedelta(minutes=precool_lead)
                data[STATE_PREHEAT_START_TIME] = next_time - timedelta(minutes=preheat_lead)
                data[STATE_PRECOOL_LEAD_MINUTES] = precool_lead
                data[STATE_PREHEAT_LEAD_MINUTES] = preheat_lead
            
            # Occupancy percentage (7 days)
            occupancy_pct = await database.get_occupancy_percentage(self.entry.entry_id, days=7)
            if occupancy_pct is not None:
                data[STATE_OCCUPANCY_PCT_7D] = round(occupancy_pct, 1)
            
            # Peak occupancy hour
            peak_hour = await database.get_peak_occupancy_hour(self.entry.entry_id, days=7)
            if peak_hour is not None:
                # Format as time string
                from datetime import time
                t = time(hour=peak_hour)
                data[STATE_PEAK_OCCUPANCY_TIME] = t.strftime("%I:00 %p")
        
        return data
    
    async def _delayed_exit_verify(self, room_name: str, data: dict[str, Any]) -> None:
        """RESILIENCE-003: Verify exit automation after 3s delay (non-blocking)."""
        await asyncio.sleep(3)
        self._last_exit_verify_time = dt_util.now()
        # Re-check: if room became occupied again, skip retry
        if self.data and self.data.get(STATE_OCCUPIED):
            _LOGGER.debug("Room %s: Re-occupied during exit verify delay — skipping retry", room_name)
            self._last_exit_verify_result = "skipped_reoccupied"
            return
        area_id = self._get_config(CONF_AREA_ID)
        if not area_id:
            self._last_exit_verify_result = "confirmed"
            return
        device_counts = self._calculate_device_counts(area_id)
        lights_on = device_counts.get("lights_on", 0)
        switches_on = device_counts.get("switches_on", 0)
        if lights_on > 0 or switches_on > 0:
            _LOGGER.warning(
                "Room %s: Exit automation may have failed — "
                "%d light(s), %d switch(es) still on. Retrying.",
                room_name, lights_on, switches_on,
            )
            # Use fresh data from coordinator
            fresh_data = self.data or data
            try:
                await self.automation.handle_occupancy_change(False, fresh_data)
                self._last_exit_verify_result = "retried"
            except Exception as e:
                _LOGGER.error(
                    "Room %s: Retry exit automation also failed: %s",
                    room_name, e,
                )
                self._last_exit_verify_result = "retry_failed"
        else:
            self._last_exit_verify_result = "confirmed"

    def set_last_action(
        self,
        action_type: str,
        description: str,
        entity: str | list[str] | None = None
    ) -> None:
        """
        Record the last automation action for tracking.
        Called by automation.py methods after performing actions.
        
        Args:
            action_type: Type of action ("turn_on", "turn_off", "set_temperature", etc.)
            description: Human-readable description ("Turned on 3 lights", "Set fan to medium")
            entity: Single entity_id or list of entity_ids affected
        """
        self._last_action_type = action_type
        self._last_action_description = description
        self._last_action_entity = entity
        self._last_action_time = dt_util.now()
        
        _LOGGER.debug(
            "Action recorded for %s: %s (%s)",
            self.entry.data.get("room_name"),
            description,
            action_type
        )
    
    def get_last_trigger_info(self) -> dict[str, Any]:
        """Get last trigger information for sensors."""
        return {
            "source": self._last_trigger_source,
            "entity": self._last_trigger_entity,
            "time": self._last_trigger_time,
        }
    
    def get_last_action_info(self) -> dict[str, Any]:
        """Get last action information for sensors."""
        return {
            "type": self._last_action_type,
            "description": self._last_action_description,
            "entity": self._last_action_entity,
            "time": self._last_action_time,
        }

    def get_became_occupied_time(self) -> datetime | None:
        """
        Get timestamp when the room became occupied in the current session.
        
        v3.2.4: Used by PersonTrackingCoordinator for Tier 3 disambiguation
        when multiple rooms share a BLE scanner. The most recently occupied
        room wins when both rooms are occupied.
        
        Returns:
            datetime when room became occupied, or None if not currently occupied
        """
        return self._became_occupied_time

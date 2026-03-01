"""Automation logic for Universal Room Automation."""
#
# Universal Room Automation v3.6.0.8
# Build: 2026-01-04
# File: automation.py
# v3.3.1.1: Added int() cast to get_auto_off_hour to handle NumberSelector float values
# v3.2.9: Added switch support for temperature-based fans (not just humidity fans)
# v3.2.8.2: Multi-domain auto/manual devices (lights, fans, switches, input_booleans)
# v3.2.8.2: Multi-domain humidity fans (fans, switches)
#

import asyncio
import logging
from datetime import datetime, time
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import sun
from homeassistant.util import dt as dt_util
from homeassistant.const import (
    STATE_ON,
    STATE_OFF,
    SERVICE_TURN_ON,
    SERVICE_TURN_OFF,
)

from .const import (
    # Automation behavior
    CONF_ENTRY_LIGHT_ACTION,
    CONF_EXIT_LIGHT_ACTION,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_BRIGHTNESS_PCT,
    CONF_LIGHT_TRANSITION_ON,
    CONF_LIGHT_TRANSITION_OFF,
    CONF_ENTRY_COVER_ACTION,
    CONF_EXIT_COVER_ACTION,
    CONF_OPEN_TIMING_MODE,
    CONF_OPEN_TIME_START,
    CONF_OPEN_TIME_END,
    CONF_SUNRISE_OFFSET,
    CONF_CLOSE_TIMING_MODE,
    CONF_CLOSE_TIME,
    CONF_SUNSET_OFFSET,
    CONF_TIMED_CLOSE_ENABLED,
    # Light actions
    LIGHT_ACTION_NONE,
    LIGHT_ACTION_TURN_ON,
    LIGHT_ACTION_TURN_ON_IF_DARK,
    LIGHT_ACTION_TURN_OFF,
    LIGHT_ACTION_LEAVE_ON,
    # Cover actions
    COVER_ACTION_NONE,
    COVER_ACTION_ALWAYS,
    COVER_ACTION_SMART,
    COVER_ACTION_AFTER_SUNSET,
    # Timing modes
    TIMING_MODE_SUN,
    TIMING_MODE_TIME,
    TIMING_MODE_BOTH_LATEST,
    TIMING_MODE_BOTH_EARLIEST,
    # Climate
    CONF_CLIMATE_ENTITY,
    CONF_HVAC_COORDINATION_ENABLED,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FAN_SPEED_LOW_TEMP,
    CONF_FAN_SPEED_MED_TEMP,
    CONF_FAN_SPEED_HIGH_TEMP,
    CONF_HUMIDITY_FAN_THRESHOLD,
    CONF_HUMIDITY_FAN_TIMEOUT,
    # Sleep protection
    CONF_SLEEP_PROTECTION_ENABLED,
    CONF_SLEEP_START_HOUR,
    CONF_SLEEP_END_HOUR,
    CONF_SLEEP_BYPASS_MOTION,
    CONF_SLEEP_BLOCK_COVERS,
    # Devices
    CONF_LIGHTS,
    CONF_LIGHT_CAPABILITIES,
    CONF_FANS,
    CONF_HUMIDITY_FANS,
    CONF_COVERS,
    CONF_AUTO_SWITCHES,  # Legacy - still supported
    CONF_MANUAL_SWITCHES,  # Legacy - still supported
    CONF_AUTO_DEVICES,  # v3.2.8.2: New multi-domain
    CONF_MANUAL_DEVICES,  # v3.2.8.2: New multi-domain
    LIGHT_CAPABILITY_BASIC,
    LIGHT_CAPABILITY_BRIGHTNESS,
    LIGHT_CAPABILITY_FULL,
    # v3.2.2.5: Night lights
    CONF_NIGHT_LIGHTS,
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHT_SLEEP_COLOR,
    CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
    CONF_NIGHT_LIGHT_DAY_COLOR,
    DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_SLEEP_COLOR,
    DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_DAY_COLOR,
    # State
    STATE_OCCUPIED,
    STATE_DARK,
    STATE_ILLUMINANCE,
    STATE_TEMPERATURE,
    STATE_HUMIDITY,
    # v3.1.0: Shared space and alerts
    CONF_SHARED_SPACE,
    CONF_SHARED_SPACE_AUTO_OFF_HOUR,
    CONF_SHARED_SPACE_WARNING,
    CONF_ALERT_LIGHTS,
    CONF_ALERT_LIGHT_COLOR,
    ALERT_COLOR_RGB,
    ALERT_COLOR_AMBER,
    DEFAULT_SHARED_SPACE_AUTO_OFF_HOUR,
)

_LOGGER = logging.getLogger(__name__)


class RoomAutomation:
    """Handles automation logic for a room."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any], coordinator) -> None:
        """Initialize room automation."""
        # v3.2.8 STARTUP BANNER
        room_name = config.get('room_name', 'Unknown')
        _LOGGER.critical("🔧 v3.2.8 AUTOMATION MODULE INITIALIZED FOR ROOM: %s", room_name)
        _LOGGER.critical("    ✅ Light/Switch separation: ACTIVE")
        _LOGGER.critical("    ✅ Config merge: entry.options override entry.data")
        
        self.hass = hass
        self.config = config
        self._sleep_motion_count = 0
        self.coordinator = coordinator
        self._humidity_fan_triggered_time: datetime | None = None
        # v3.1.0: Shared space - track last auto-off to prevent repeated triggers
        self._last_auto_off_date: str | None = None
        # v3.1.0: Alert light state tracking
        self._alert_lights_active: bool = False
        self._alert_light_original_states: dict[str, dict] = {}

    async def _safe_service_call(
        self,
        domain: str,
        service: str,
        service_data: dict,
        blocking: bool = False,
        timeout: float = 5.0,
    ) -> bool:
        """Call a service with timeout and error handling."""
        entity_ids = service_data.get("entity_id", "unknown")
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    domain, service, service_data, blocking=blocking
                ),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            _LOGGER.error(
                "Service call timeout after %.1fs: %s.%s for %s in room %s",
                timeout, domain, service, entity_ids,
                self.config.get("room_name", "unknown"),
            )
            return False
        except Exception as e:
            _LOGGER.error(
                "Service call failed: %s.%s for %s in room %s: %s",
                domain, service, entity_ids,
                self.config.get("room_name", "unknown"), e,
            )
            return False

    def is_sleep_mode_active(self) -> bool:
        """Check if sleep protection is currently active."""
        if not self.config.get(CONF_SLEEP_PROTECTION_ENABLED, False):
            return False

        now = dt_util.now().time()
        sleep_start = time(hour=int(self.config.get(CONF_SLEEP_START_HOUR, 22)))
        sleep_end = time(hour=int(self.config.get(CONF_SLEEP_END_HOUR, 7)))

        # Handle sleep period that crosses midnight
        if sleep_start > sleep_end:
            return now >= sleep_start or now < sleep_end
        else:
            return sleep_start <= now < sleep_end

    def can_bypass_sleep_mode(self, motion_detected: bool) -> bool:
        """Check if enough motion has occurred to bypass sleep mode."""
        if not self.is_sleep_mode_active():
            return True

        if motion_detected:
            self._sleep_motion_count += 1

        bypass_threshold = self.config.get(CONF_SLEEP_BYPASS_MOTION, 3)
        return self._sleep_motion_count >= bypass_threshold

    def reset_sleep_bypass(self) -> None:
        """Reset sleep bypass counter."""
        self._sleep_motion_count = 0

    def is_dark(self, illuminance: float | None) -> bool:
        """Check if room is dark based on illuminance threshold."""
        if illuminance is None:
            return False  # Assume not dark if no sensor
        threshold = self.config.get(CONF_ILLUMINANCE_THRESHOLD, 20)
        return illuminance < threshold

    def should_execute_automation(self, state_data: dict[str, Any]) -> bool:
        """Check if automation should execute (respects sleep mode)."""
        if not self.is_sleep_mode_active():
            return True

        # During sleep mode, check bypass
        return self.can_bypass_sleep_mode(state_data.get(STATE_OCCUPIED, False))

    async def handle_occupancy_change(
        self,
        occupied: bool,
        state_data: dict[str, Any],
    ) -> None:
        """Handle occupancy state change."""
        room_name = self.config.get('room_name', 'Unknown')
        _LOGGER.debug("Occupancy change [%s]: occupied=%s, should_execute=%s", 
                       room_name, occupied, self.should_execute_automation(state_data))
        
        if not self.should_execute_automation(state_data):
            _LOGGER.debug("Skipping automation - sleep mode active")
            return

        if occupied:
            _LOGGER.debug("Occupancy [%s]: Calling _handle_entry", room_name)
            await self._handle_entry(state_data)
        else:
            _LOGGER.debug("Occupancy [%s]: Calling _handle_exit", room_name)
            await self._handle_exit(state_data)
            self.reset_sleep_bypass()

    async def _handle_entry(self, state_data: dict[str, Any]) -> None:
        """Handle room entry automation."""
        # Light control
        await self._control_lights_entry(state_data)

        # Auto switches - turn on
        await self._control_auto_switches(True)

        # Covers - open if configured
        await self._control_covers_entry(state_data)

    async def _handle_exit(self, state_data: dict[str, Any]) -> None:
        """Handle room exit automation."""
        # Light control
        await self._control_lights_exit(state_data)

        # Auto switches - turn off
        await self._control_auto_switches(False)

        # Manual switches - turn off
        await self._control_manual_switches_off()

        # Covers - close if configured
        await self._control_covers_exit(state_data)

    async def _control_lights_entry(self, state_data: dict[str, Any]) -> None:
        """Control lights on entry with night light support."""
        room_name = self.config.get('room_name', 'Unknown')
        
        action = self.config.get(CONF_ENTRY_LIGHT_ACTION, LIGHT_ACTION_NONE)
        _LOGGER.debug("Entry light control [%s]: action=%s", room_name, action)
        
        if action == LIGHT_ACTION_NONE:
            _LOGGER.debug("Entry light control [%s]: action is NONE, skipping", room_name)
            return

        lights = self.config.get(CONF_LIGHTS, [])
        _LOGGER.debug("Entry light control [%s]: lights=%s (count=%d)", room_name, lights, len(lights))
        
        if not lights:
            _LOGGER.debug("Entry light control [%s]: no lights configured, skipping", room_name)
            return

        # === v3.2.2.5: Check if we're in sleep hours ===
        is_sleep_hours = self.is_sleep_mode_active()
        night_lights = self.config.get(CONF_NIGHT_LIGHTS, [])
        
        _LOGGER.debug("Entry light control [%s]: is_sleep_hours=%s, night_lights=%s", 
                       room_name, is_sleep_hours, night_lights)
        
        if is_sleep_hours and night_lights:
            # SLEEP MODE: Only night lights, no darkness check
            _LOGGER.info("Sleep mode active - turning on night lights only")
            await self._turn_on_night_lights(mode="sleep")
            await self._turn_off_non_night_lights()
            return
        
        # NORMAL MODE: Check darkness if needed
        illuminance = state_data.get(STATE_ILLUMINANCE)
        is_dark = self.is_dark(illuminance)
        _LOGGER.debug("Entry light control [%s]: illuminance=%s, is_dark=%s", room_name, illuminance, is_dark)
        
        should_turn_on = action == LIGHT_ACTION_TURN_ON or (
            action == LIGHT_ACTION_TURN_ON_IF_DARK
            and is_dark
        )
        _LOGGER.debug("Entry light control [%s]: should_turn_on=%s", room_name, should_turn_on)

        if not should_turn_on:
            _LOGGER.debug("Entry light control [%s]: conditions not met, skipping", room_name)
            return

        # v3.2.5 FIX: Calculate actual_lights and switches_as_lights locally
        # (Previously these were undefined, causing NameError)
        actual_lights = [e for e in lights if e.startswith("light.")]
        switches_as_lights = [e for e in lights if e.startswith("switch.")]

        # Turn on all lights (regular + night lights with day settings)
        await self._turn_on_regular_lights()
        
        if night_lights:
            # Night lights also turn on during day with day settings
            await self._turn_on_night_lights(mode="day")
        _LOGGER.info(
            "Room entry automation: Turned on %d light(s) and %d switch(es)",
            len(actual_lights), len(switches_as_lights)
        )
        self.coordinator.set_last_action(
            "turn_on",
            f"Turned on {len(actual_lights)} light(s) and {len(switches_as_lights)} switch(es)",
            lights
        )

    async def _control_lights_exit(self, state_data: dict[str, Any]) -> None:
        """Control lights on exit."""
        action = self.config.get(CONF_EXIT_LIGHT_ACTION, LIGHT_ACTION_TURN_OFF)
        if action != LIGHT_ACTION_TURN_OFF:
            return

        lights = self.config.get(CONF_LIGHTS, [])
        if not lights:
            return

        # v3.2.0.8: Separate light.* entities from switch.* entities
        actual_lights = []
        switches_as_lights = []
        
        for entity_id in lights:
            if entity_id.startswith("light."):
                actual_lights.append(entity_id)
            elif entity_id.startswith("switch."):
                switches_as_lights.append(entity_id)
            else:
                actual_lights.append(entity_id)  # Assume light if unknown

        # Turn off actual light.* entities with 3s transition
        if actual_lights:
            await self._safe_service_call(
                "light",
                SERVICE_TURN_OFF,
                {
                    "entity_id": actual_lights,
                    "transition": self.config.get(CONF_LIGHT_TRANSITION_OFF, 3),
                },
                blocking=False,
            )
            _LOGGER.debug("Turned off %d light(s): %s", len(actual_lights), actual_lights)

        # Turn off switch.* entities instantly (no transition)
        if switches_as_lights:
            await self._safe_service_call(
                "switch",
                SERVICE_TURN_OFF,
                {"entity_id": switches_as_lights},
                blocking=False,
            )
            _LOGGER.debug("Turned off %d switch(es) as lights: %s", len(switches_as_lights), switches_as_lights)

        # Track action with INFO log
        _LOGGER.info(
            "Room exit automation: Turned off %d light(s) and %d switch(es)",
            len(actual_lights), len(switches_as_lights)
        )
        self.coordinator.set_last_action(
            "turn_off",
            f"Turned off {len(actual_lights)} light(s) and {len(switches_as_lights)} switch(es)",
            lights
        )

    # === v3.2.2.5: NIGHT LIGHT HELPER METHODS ===
    
    async def _turn_on_regular_lights(self) -> None:
        """Turn on regular lights (non-night lights) with standard settings."""
        lights = self.config.get(CONF_LIGHTS, [])
        night_lights = self.config.get(CONF_NIGHT_LIGHTS, [])
        
        # Get lights that are NOT night lights
        regular_lights = [light for light in lights if light not in night_lights]
        
        if not regular_lights:
            return
            
        # Separate light.* from switch.*
        actual_lights = [e for e in regular_lights if e.startswith("light.")]
        switches_as_lights = [e for e in regular_lights if e.startswith("switch.")]
        
        # Turn on light.* entities with transition and brightness
        if actual_lights:
            service_data = {
                "entity_id": actual_lights,
                "transition": self.config.get(CONF_LIGHT_TRANSITION_ON, 1),
            }
            
            # Add brightness if supported
            capability = self.config.get(CONF_LIGHT_CAPABILITIES, LIGHT_CAPABILITY_BASIC)
            if capability in [LIGHT_CAPABILITY_BRIGHTNESS, LIGHT_CAPABILITY_FULL]:
                brightness_pct = self.config.get(CONF_LIGHT_BRIGHTNESS_PCT, 100)
                service_data["brightness_pct"] = brightness_pct
            
            await self._safe_service_call(
                "light", SERVICE_TURN_ON, service_data, blocking=False
            )
            _LOGGER.debug("Turned on %d regular light(s)", len(actual_lights))

        # Turn on switch.* entities
        if switches_as_lights:
            await self._safe_service_call(
                "switch", SERVICE_TURN_ON,
                {"entity_id": switches_as_lights}, blocking=False
            )
            _LOGGER.debug("Turned on %d regular switch(es)", len(switches_as_lights))
    
    async def _turn_on_night_lights(self, mode: str = "sleep") -> None:
        """Turn on night lights with mode-specific settings.
        
        Args:
            mode: "sleep" for dim/warm settings, "day" for bright/cool settings
        """
        night_lights = self.config.get(CONF_NIGHT_LIGHTS, [])
        
        if not night_lights:
            return
        
        # Get settings based on mode
        if mode == "sleep":
            brightness = self.config.get(
                CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS, 
                DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS
            )
            color_temp = self.config.get(
                CONF_NIGHT_LIGHT_SLEEP_COLOR,
                DEFAULT_NIGHT_LIGHT_SLEEP_COLOR
            )
        else:  # day mode
            brightness = self.config.get(
                CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
                DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS
            )
            color_temp = self.config.get(
                CONF_NIGHT_LIGHT_DAY_COLOR,
                DEFAULT_NIGHT_LIGHT_DAY_COLOR
            )
        
        # Separate light.* from switch.*
        actual_lights = [e for e in night_lights if e.startswith("light.")]
        switches_as_lights = [e for e in night_lights if e.startswith("switch.")]
        
        # Turn on light.* entities with brightness/color based on capability
        if actual_lights:
            service_data = {
                "entity_id": actual_lights,
                "transition": self.config.get(CONF_LIGHT_TRANSITION_ON, 1),
            }
            
            capability = self.config.get(CONF_LIGHT_CAPABILITIES, LIGHT_CAPABILITY_BASIC)
            
            # Add brightness for BRIGHTNESS or FULL capability
            if capability in [LIGHT_CAPABILITY_BRIGHTNESS, LIGHT_CAPABILITY_FULL]:
                service_data["brightness_pct"] = brightness
            
            # Add color temp for FULL capability only
            if capability == LIGHT_CAPABILITY_FULL:
                service_data["kelvin"] = color_temp
            
            await self._safe_service_call(
                "light", SERVICE_TURN_ON, service_data, blocking=False
            )
            _LOGGER.info(
                "Turned on %d night light(s) in %s mode (brightness=%s%%, color=%sK)",
                len(actual_lights), mode, brightness, color_temp
            )

        # Turn on switch.* entities (no brightness/color support)
        if switches_as_lights:
            await self._safe_service_call(
                "switch", SERVICE_TURN_ON,
                {"entity_id": switches_as_lights}, blocking=False
            )
            _LOGGER.debug("Turned on %d night switch(es)", len(switches_as_lights))
    
    async def _turn_off_non_night_lights(self) -> None:
        """Turn off all lights that are NOT night lights."""
        lights = self.config.get(CONF_LIGHTS, [])
        night_lights = self.config.get(CONF_NIGHT_LIGHTS, [])
        
        # Get lights to turn off (not in night_lights list)
        lights_to_turn_off = [light for light in lights if light not in night_lights]
        
        if not lights_to_turn_off:
            return
        
        # Separate light.* from switch.*
        actual_lights = [e for e in lights_to_turn_off if e.startswith("light.")]
        switches_as_lights = [e for e in lights_to_turn_off if e.startswith("switch.")]
        
        # Turn off light.* entities with transition
        if actual_lights:
            await self._safe_service_call(
                "light", SERVICE_TURN_OFF,
                {
                    "entity_id": actual_lights,
                    "transition": self.config.get(CONF_LIGHT_TRANSITION_OFF, 3),
                },
                blocking=False
            )
            _LOGGER.debug("Turned off %d non-night light(s)", len(actual_lights))

        # Turn off switch.* entities
        if switches_as_lights:
            await self._safe_service_call(
                "switch", SERVICE_TURN_OFF,
                {"entity_id": switches_as_lights}, blocking=False
            )
            _LOGGER.debug("Turned off %d non-night switch(es)", len(switches_as_lights))

    async def _control_auto_switches(self, turn_on: bool) -> None:
        """Control auto devices (switches, lights, fans, input_booleans).
        
        v3.2.8.2: Supports multiple domains via homeassistant.turn_on/off
        Backward compatible: CONF_AUTO_SWITCHES still works
        """
        # Get devices from both old and new config keys
        devices = self.config.get(CONF_AUTO_DEVICES, [])
        legacy_switches = self.config.get(CONF_AUTO_SWITCHES, [])
        
        # Combine both lists (legacy + new)
        if legacy_switches:
            if isinstance(legacy_switches, str):
                legacy_switches = [legacy_switches]
            devices = list(set(devices + legacy_switches))
        
        if not devices:
            return

        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF

        # Use homeassistant domain for multi-domain support
        await self._safe_service_call(
            "homeassistant",
            service,
            {"entity_id": devices},
            blocking=False,
        )
        _LOGGER.debug("%s auto devices: %s", service, devices)

    async def _control_manual_switches_off(self) -> None:
        """Turn off manual devices on exit (switches, lights, fans, input_booleans).
        
        v3.2.8.2: Supports multiple domains via homeassistant.turn_off
        Backward compatible: CONF_MANUAL_SWITCHES still works
        """
        # Get devices from both old and new config keys
        devices = self.config.get(CONF_MANUAL_DEVICES, [])
        legacy_switches = self.config.get(CONF_MANUAL_SWITCHES, [])
        
        # Combine both lists (legacy + new)
        if legacy_switches:
            if isinstance(legacy_switches, str):
                legacy_switches = [legacy_switches]
            devices = list(set(devices + legacy_switches))
        
        if not devices:
            return

        # Use homeassistant domain for multi-domain support
        await self._safe_service_call(
            "homeassistant",
            SERVICE_TURN_OFF,
            {"entity_id": devices},
            blocking=False,
        )
        _LOGGER.debug("Turned off manual devices: %s", devices)

    def _is_within_cover_time_window(self) -> bool:
        """Check if current time is within configured cover operation window."""
        timing_mode = self.config.get(CONF_OPEN_TIMING_MODE, TIMING_MODE_SUN)
        now = dt_util.now()

        if timing_mode == TIMING_MODE_SUN:
            # Check if after sunrise
            sunrise_offset = self.config.get(CONF_SUNRISE_OFFSET, 0)
            sunrise_time = sun.get_astral_event_date(
                self.hass, "sunrise", dt_util.start_of_local_day()
            )
            if sunrise_time:
                sunrise_time = sunrise_time.replace(
                    minute=sunrise_time.minute + sunrise_offset
                )
                if now < sunrise_time:
                    return False

        elif timing_mode == TIMING_MODE_TIME:
            # Check if within time range
            start_hour = self.config.get(CONF_OPEN_TIME_START, 7)
            end_hour = self.config.get(CONF_OPEN_TIME_END, 20)
            current_hour = now.hour
            if not (start_hour <= current_hour < end_hour):
                return False

        elif timing_mode in [TIMING_MODE_BOTH_LATEST, TIMING_MODE_BOTH_EARLIEST]:
            # Implement combined logic
            pass  # TODO: Add both sun and time logic

        return True

    async def _control_covers_entry(self, state_data: dict[str, Any]) -> None:
        """Control covers on entry."""
        if self.is_sleep_mode_active() and self.config.get(CONF_SLEEP_BLOCK_COVERS, True):
            return

        action = self.config.get(CONF_ENTRY_COVER_ACTION, COVER_ACTION_NONE)
        if action == COVER_ACTION_NONE:
            return

        covers = self.config.get(CONF_COVERS, [])
        if not covers:
            return

        # Check time window
        if action in [COVER_ACTION_ALWAYS, COVER_ACTION_SMART]:
            if not self._is_within_cover_time_window():
                return

        await self._safe_service_call(
            "cover",
            "open_cover",
            {"entity_id": covers},
            blocking=False,
        )
        _LOGGER.debug("Opened covers: %s", covers)

    async def _control_covers_exit(self, state_data: dict[str, Any]) -> None:
        """Control covers on exit."""
        action = self.config.get(CONF_EXIT_COVER_ACTION, COVER_ACTION_NONE)
        if action == COVER_ACTION_NONE:
            return

        covers = self.config.get(CONF_COVERS, [])
        if not covers:
            return

        # Check if after sunset for after_sunset action
        if action == COVER_ACTION_AFTER_SUNSET:
            sunset = sun.get_astral_event_date(
                self.hass, "sunset", dt_util.start_of_local_day()
            )
            if sunset and dt_util.now() < sunset:
                return

        await self._safe_service_call(
            "cover",
            "close_cover",
            {"entity_id": covers},
            blocking=False,
        )
        _LOGGER.debug("Closed covers: %s", covers)

    async def handle_temperature_based_fan_control(
        self, temperature: float | None, occupied: bool
    ) -> None:
        """Control fans/switches based on temperature.
        
        v3.2.9: Added support for switch domain (fans on smart outlets/switches).
        """
        if not self.config.get(CONF_FAN_CONTROL_ENABLED, False):
            return

        fans = self.config.get(CONF_FANS, [])
        if not fans or temperature is None:
            return

        threshold = self.config.get(CONF_FAN_TEMP_THRESHOLD, 80)
        if temperature < threshold or not occupied:
            # Turn off fans/switches if below threshold or room vacant
            # v3.2.9: Use homeassistant domain for multi-domain support
            await self._safe_service_call(
                "homeassistant",
                SERVICE_TURN_OFF,
                {"entity_id": fans},
                blocking=False,
            )
            return

        # Determine fan speed based on temperature
        low_temp = self.config.get(CONF_FAN_SPEED_LOW_TEMP, 69)
        med_temp = self.config.get(CONF_FAN_SPEED_MED_TEMP, 72)
        high_temp = self.config.get(CONF_FAN_SPEED_HIGH_TEMP, 75)

        if temperature >= high_temp:
            speed_pct = 100
        elif temperature >= med_temp:
            speed_pct = 66
        elif temperature >= low_temp:
            speed_pct = 33
        else:
            speed_pct = 0

        if speed_pct > 0:
            try:
                # v3.2.9: Try to set speed (works for fan domain)
                # If it fails (e.g., switch domain), just turn on
                for fan_entity in fans:
                    if fan_entity.startswith("fan."):
                        # Real fan - set speed
                        await self._safe_service_call(
                            "fan",
                            SERVICE_TURN_ON,
                            {"entity_id": fan_entity, "percentage": speed_pct},
                            blocking=False,
                        )
                    else:
                        # Switch - just turn on (no speed control)
                        await self._safe_service_call(
                            "homeassistant",
                            SERVICE_TURN_ON,
                            {"entity_id": fan_entity},
                            blocking=False,
                        )
                _LOGGER.debug("Set fan speed to %d%% for temp %.1f°F", speed_pct, temperature)
            except Exception as e:
                _LOGGER.error("Error controlling fans: %s", e)

    async def handle_humidity_based_fan_control(
        self, humidity: float | None
    ) -> None:
        """Control humidity fans/switches based on humidity level.
        
        v3.2.8.2: Supports both fan.* and switch.* domains for RF fans on outlets
        """
        humidity_fans = self.config.get(CONF_HUMIDITY_FANS, [])
        if not humidity_fans or humidity is None:
            return

        threshold = self.config.get(CONF_HUMIDITY_FAN_THRESHOLD, 60)
        timeout = self.config.get(CONF_HUMIDITY_FAN_TIMEOUT, 600)

        if humidity >= threshold:
            # Turn on humidity fans/switches
            if self._humidity_fan_triggered_time is None:
                self._humidity_fan_triggered_time = dt_util.now()

            # Use homeassistant domain to support both fans and switches
            await self._safe_service_call(
                "homeassistant",
                SERVICE_TURN_ON,
                {"entity_id": humidity_fans},
                blocking=False,
            )
            _LOGGER.debug("Turned on humidity fans - humidity at %.1f%%", humidity)

        elif humidity < threshold and self._humidity_fan_triggered_time:
            # Check if timeout has passed
            elapsed = (dt_util.now() - self._humidity_fan_triggered_time).total_seconds()
            if elapsed >= timeout:
                # Use homeassistant domain to support both fans and switches
                await self._safe_service_call(
                    "homeassistant",
                    SERVICE_TURN_OFF,
                    {"entity_id": humidity_fans},
                    blocking=False,
                )
                _LOGGER.debug("Turned off humidity fans after timeout")
                self._humidity_fan_triggered_time = None

    def should_coordinate_with_hvac(self) -> bool:
        """Check if HVAC coordination is enabled and HVAC is running."""
        if not self.config.get(CONF_HVAC_COORDINATION_ENABLED, False):
            return False

        climate_entity = self.config.get(CONF_CLIMATE_ENTITY)
        if not climate_entity:
            return False

        state = self.hass.states.get(climate_entity)
        if not state:
            return False

        # Check if HVAC is actively heating or cooling
        hvac_action = state.attributes.get("hvac_action")
        return hvac_action in ["heating", "cooling"]

    # =========================================================================
    # v3.1.0: SHARED SPACE SCHEDULED AUTO-OFF
    # =========================================================================

    def is_shared_space(self) -> bool:
        """Check if this room is configured as a shared space."""
        return self.config.get(CONF_SHARED_SPACE, False)

    def get_auto_off_hour(self) -> int:
        """Get the hour for scheduled auto-off (0-23)."""
        return int(self.config.get(CONF_SHARED_SPACE_AUTO_OFF_HOUR, DEFAULT_SHARED_SPACE_AUTO_OFF_HOUR))

    def should_warn_before_auto_off(self) -> bool:
        """Check if warning flash is enabled before auto-off."""
        return self.config.get(CONF_SHARED_SPACE_WARNING, True)

    async def check_scheduled_auto_off(self) -> None:
        """Check if it's time for scheduled auto-off.
        
        This implements time-based "lights out" for shared spaces:
        - At the configured hour (default 11 PM), turn off all devices
        - Catches devices people forgot about
        - Only triggers once per day (prevents repeated triggers if called multiple times)
        
        Called by coordinator on each update cycle.
        """
        if not self.is_shared_space():
            return
        
        now = dt_util.now()
        current_hour = now.hour
        current_date = now.strftime("%Y-%m-%d")
        auto_off_hour = self.get_auto_off_hour()
        
        # Check if we've already triggered today
        if self._last_auto_off_date == current_date:
            return
        
        # Check if it's the auto-off hour
        if current_hour == auto_off_hour:
            _LOGGER.info(
                "Shared space scheduled auto-off triggered at %d:00",
                auto_off_hour
            )
            await self._shared_space_turn_off_all()
            self._last_auto_off_date = current_date

    async def check_auto_off_warning(self) -> None:
        """Check if it's time to warn before auto-off (5 minutes before).
        
        Flashes lights briefly to warn occupants that auto-off is coming.
        Called by coordinator on each update cycle.
        """
        if not self.is_shared_space():
            return
        
        if not self.should_warn_before_auto_off():
            return
        
        now = dt_util.now()
        auto_off_hour = self.get_auto_off_hour()
        
        # Warning at 5 minutes before the hour (e.g., 10:55 PM for 11 PM auto-off)
        warning_hour = auto_off_hour - 1 if auto_off_hour > 0 else 23
        
        if now.hour == warning_hour and now.minute == 55:
            # Only warn once - check if lights are actually on
            lights = self.config.get(CONF_LIGHTS, [])
            lights_on = False
            for light_id in lights:
                state = self.hass.states.get(light_id)
                if state and state.state == STATE_ON:
                    lights_on = True
                    break
            
            if lights_on:
                _LOGGER.info("Shared space auto-off warning - flashing lights")
                await self._warning_flash()

    async def _warning_flash(self) -> None:
        """Flash lights briefly to warn of upcoming auto-off."""
        lights = self.config.get(CONF_LIGHTS, [])
        if not lights:
            return
        
        try:
            # Quick dim-restore cycle (2 flashes)
            for _ in range(2):
                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_ON,
                    {"entity_id": lights, "brightness": 50},
                    blocking=True,
                )
                await asyncio.sleep(0.3)
                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_ON,
                    {"entity_id": lights, "brightness": 255},
                    blocking=True,
                )
                await asyncio.sleep(0.3)
        except Exception as e:
            _LOGGER.error("Error during warning flash: %s", e)

    async def _shared_space_turn_off_all(self) -> None:
        """Turn off all devices in shared space."""
        # Turn off lights
        lights = self.config.get(CONF_LIGHTS, [])
        if lights:
            await self._safe_service_call(
                "light",
                SERVICE_TURN_OFF,
                {"entity_id": lights},
                blocking=False,
            )
            _LOGGER.debug("Shared space: turned off lights")

        # Turn off fans
        fans = self.config.get(CONF_FANS, [])
        if fans:
            await self._safe_service_call(
                "fan",
                SERVICE_TURN_OFF,
                {"entity_id": fans},
                blocking=False,
            )
            _LOGGER.debug("Shared space: turned off fans")

        # Turn off auto switches
        auto_switches = self.config.get(CONF_AUTO_SWITCHES, [])
        if auto_switches:
            await self._safe_service_call(
                "switch",
                SERVICE_TURN_OFF,
                {"entity_id": auto_switches},
                blocking=False,
            )
            _LOGGER.debug("Shared space: turned off switches")

        # Turn off manual switches too
        manual_switches = self.config.get(CONF_MANUAL_SWITCHES, [])
        if manual_switches:
            await self._safe_service_call(
                "switch",
                SERVICE_TURN_OFF,
                {"entity_id": manual_switches},
                blocking=False,
            )

    # =========================================================================
    # v3.1.0: ALERT LIGHT TRIGGERING
    # =========================================================================

    async def trigger_alert_lights(self, alert_type: str = "warning") -> None:
        """Trigger alert lights with configured color.
        
        Args:
            alert_type: Type of alert - 'warning', 'critical', 'info', 'clear'
        """
        alert_lights = self.config.get(CONF_ALERT_LIGHTS, [])
        if not alert_lights:
            return

        if alert_type == "clear":
            await self._restore_alert_lights()
            return

        # Store original states before changing
        if not self._alert_lights_active:
            await self._store_alert_light_states(alert_lights)

        # Get configured color
        color_name = self.config.get(CONF_ALERT_LIGHT_COLOR, ALERT_COLOR_AMBER)
        rgb_color = ALERT_COLOR_RGB.get(color_name, ALERT_COLOR_RGB[ALERT_COLOR_AMBER])

        # Turn on lights with alert color
        await self._safe_service_call(
            "light",
            SERVICE_TURN_ON,
            {
                "entity_id": alert_lights,
                "rgb_color": rgb_color,
                "brightness": 255,  # Full brightness for alerts
            },
            blocking=False,
        )
        self._alert_lights_active = True
        _LOGGER.debug("Alert lights triggered with color %s", color_name)

    async def flash_alert_lights(self, flash_count: int = 3, flash_interval: float = 0.5) -> None:
        """Flash alert lights to draw attention.
        
        Args:
            flash_count: Number of times to flash
            flash_interval: Seconds between flashes
        """
        alert_lights = self.config.get(CONF_ALERT_LIGHTS, [])
        if not alert_lights:
            return

        # Store original states
        if not self._alert_lights_active:
            await self._store_alert_light_states(alert_lights)

        color_name = self.config.get(CONF_ALERT_LIGHT_COLOR, ALERT_COLOR_AMBER)
        rgb_color = ALERT_COLOR_RGB.get(color_name, ALERT_COLOR_RGB[ALERT_COLOR_AMBER])

        try:
            for _ in range(flash_count):
                # Turn on with color
                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_ON,
                    {
                        "entity_id": alert_lights,
                        "rgb_color": rgb_color,
                        "brightness": 255,
                    },
                    blocking=True,
                )
                await asyncio.sleep(flash_interval)

                # Turn off briefly
                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_OFF,
                    {"entity_id": alert_lights},
                    blocking=True,
                )
                await asyncio.sleep(flash_interval)

            # Restore original state after flashing
            await self._restore_alert_lights()
            _LOGGER.debug("Alert light flash complete")
        except Exception as e:
            _LOGGER.error("Error flashing alert lights: %s", e)

    async def _store_alert_light_states(self, lights: list[str]) -> None:
        """Store current state of alert lights before modifying them."""
        self._alert_light_original_states = {}
        
        for light_id in lights:
            state = self.hass.states.get(light_id)
            if state:
                self._alert_light_original_states[light_id] = {
                    "state": state.state,
                    "brightness": state.attributes.get("brightness"),
                    "rgb_color": state.attributes.get("rgb_color"),
                    "color_temp": state.attributes.get("color_temp"),
                }
        
        _LOGGER.debug("Stored original states for %d alert lights", len(self._alert_light_original_states))

    async def _restore_alert_lights(self) -> None:
        """Restore alert lights to their original state."""
        if not self._alert_light_original_states:
            self._alert_lights_active = False
            return

        for light_id, original in self._alert_light_original_states.items():
            if original["state"] == STATE_OFF:
                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_OFF,
                    {"entity_id": light_id},
                    blocking=False,
                )
            else:
                # Restore original color/brightness
                service_data = {"entity_id": light_id}
                if original.get("brightness"):
                    service_data["brightness"] = original["brightness"]
                if original.get("rgb_color"):
                    service_data["rgb_color"] = original["rgb_color"]
                elif original.get("color_temp"):
                    service_data["color_temp"] = original["color_temp"]

                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_ON,
                    service_data,
                    blocking=False,
                )

        self._alert_light_original_states = {}
        self._alert_lights_active = False
        _LOGGER.debug("Alert lights restored to original state")

    async def handle_safety_alert(self, alert_active: bool, alert_details: dict = None) -> None:
        """Handle safety alert by triggering alert lights.
        
        Args:
            alert_active: Whether an alert is currently active
            alert_details: Details about the alert (type, room, etc.)
        """
        if alert_active:
            _LOGGER.warning("Safety alert triggered: %s", alert_details)
            await self.flash_alert_lights(flash_count=5, flash_interval=0.3)
            await self.trigger_alert_lights(alert_type="critical")
        else:
            await self.trigger_alert_lights(alert_type="clear")

    async def handle_security_alert(self, alert_active: bool, alert_details: dict = None) -> None:
        """Handle security alert by triggering alert lights.
        
        Args:
            alert_active: Whether an alert is currently active
            alert_details: Details about the alert (doors/windows open, etc.)
        """
        if alert_active:
            _LOGGER.warning("Security alert triggered: %s", alert_details)
            await self.trigger_alert_lights(alert_type="warning")
        else:
            await self.trigger_alert_lights(alert_type="clear")

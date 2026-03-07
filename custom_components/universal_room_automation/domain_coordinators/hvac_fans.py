"""Fan Controller for HVAC Coordinator.

Manages ceiling/portable fans with temperature hysteresis,
occupancy gating, energy fan_assist, and humidity triggers.

v3.8.4-H3: Initial implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_FANS,
    CONF_HUMIDITY_FANS,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)
from .hvac_const import (
    DEFAULT_FAN_ACTIVATION_DELTA,
    DEFAULT_FAN_HYSTERESIS,
    DEFAULT_FAN_MIN_RUNTIME,
    DEFAULT_FAN_VACANCY_HOLD,
    DEFAULT_HUMIDITY_FAN_OFF,
    DEFAULT_HUMIDITY_FAN_ON,
    FAN_SPEED_HIGH_DELTA,
    FAN_SPEED_HIGH_PCT,
    FAN_SPEED_LOW_DELTA,
    FAN_SPEED_LOW_PCT,
    FAN_SPEED_MED_DELTA,
    FAN_SPEED_MED_PCT,
)
from .hvac_zones import ZoneManager
from .signals import EnergyConstraint

_LOGGER = logging.getLogger(__name__)


@dataclass
class RoomFanState:
    """Tracks fan state for a single room."""

    room_name: str
    zone_id: str
    fan_entities: list[str] = field(default_factory=list)
    humidity_fan_entities: list[str] = field(default_factory=list)
    is_on: bool = False
    speed_pct: int = 0
    trigger: str = ""  # "temperature" | "fan_assist" | "humidity" | ""
    last_on_time: str = ""
    vacancy_detected_time: str = ""


class FanController:
    """Manages room fans with hysteresis, occupancy gating, and energy awareness.

    Called from the HVAC decision cycle every 5 minutes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
        activation_delta: float = DEFAULT_FAN_ACTIVATION_DELTA,
        deactivation_delta: float = DEFAULT_FAN_HYSTERESIS,
        min_runtime: int = DEFAULT_FAN_MIN_RUNTIME,
    ) -> None:
        """Initialize fan controller."""
        self.hass = hass
        self._zone_manager = zone_manager
        self._activation_delta = activation_delta
        self._deactivation_delta = deactivation_delta
        self._min_runtime = min_runtime
        self._room_fans: dict[str, RoomFanState] = {}
        self._fan_assist_active: bool = False

    def discover_fans(self) -> int:
        """Discover fan entities from room config entries in HVAC zones.

        Only includes rooms that belong to a discovered HVAC zone.
        Returns count of rooms with fans.
        """
        self._room_fans.clear()

        # Build room_name -> zone_id mapping
        room_to_zone: dict[str, str] = {}
        for zone_id, zone in self._zone_manager.zones.items():
            for room_name in zone.rooms:
                room_to_zone[room_name] = zone_id

        # Scan room entries for fan entities
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue

            room_name = entry.data.get(CONF_ROOM_NAME, "")
            if not room_name or room_name not in room_to_zone:
                continue

            merged = {**entry.data, **entry.options}
            fans = merged.get(CONF_FANS, [])
            humidity_fans = merged.get(CONF_HUMIDITY_FANS, [])

            if not fans and not humidity_fans:
                continue

            fan_list = fans if isinstance(fans, list) else [fans]
            hfan_list = humidity_fans if isinstance(humidity_fans, list) else [humidity_fans]
            # Filter empty strings
            fan_list = [f for f in fan_list if f]
            hfan_list = [f for f in hfan_list if f]

            if not fan_list and not hfan_list:
                continue

            self._room_fans[room_name] = RoomFanState(
                room_name=room_name,
                zone_id=room_to_zone[room_name],
                fan_entities=fan_list,
                humidity_fan_entities=hfan_list,
            )

            _LOGGER.info(
                "HVAC Fans: %s -> %d fans, %d humidity fans (zone %s)",
                room_name, len(fan_list), len(hfan_list),
                room_to_zone[room_name],
            )

        _LOGGER.info("HVAC Fans: Discovered fans in %d rooms", len(self._room_fans))
        return len(self._room_fans)

    async def update(self, energy_constraint: EnergyConstraint | None) -> None:
        """Run fan control logic for all managed rooms.

        Called from the HVAC decision cycle every 5 minutes.
        """
        if not self._room_fans:
            return

        self._fan_assist_active = (
            energy_constraint is not None and energy_constraint.fan_assist
        )
        now = dt_util.now()

        for room_name, room_fan in self._room_fans.items():
            zone = self._zone_manager.zones.get(room_fan.zone_id)
            if zone is None:
                continue

            # Find room condition from zone
            room_cond = None
            for rc in zone.room_conditions:
                if rc.room_name == room_name:
                    room_cond = rc
                    break

            room_temp = room_cond.temperature if room_cond else None
            humidity = room_cond.humidity if room_cond else None
            occupied = room_cond.occupied if room_cond else False
            setpoint_high = zone.target_temp_high

            # Evaluate temperature fans
            if room_fan.fan_entities and setpoint_high is not None and room_temp is not None:
                should_on, trigger, speed = self._evaluate_temp_fan(
                    room_fan, room_temp, setpoint_high, occupied, now
                )
                if should_on != room_fan.is_on or (should_on and speed != room_fan.speed_pct):
                    await self._set_fan_state(
                        room_fan.fan_entities, should_on, speed
                    )
                    room_fan.is_on = should_on
                    room_fan.speed_pct = speed if should_on else 0
                    room_fan.trigger = trigger if should_on else ""
                    if should_on and not room_fan.last_on_time:
                        room_fan.last_on_time = now.isoformat()
                    elif not should_on:
                        room_fan.last_on_time = ""

            # Evaluate humidity fans
            if room_fan.humidity_fan_entities and humidity is not None:
                h_on = self._evaluate_humidity_fan(humidity, room_fan)
                h_currently_on = any(
                    self._is_entity_on(e) for e in room_fan.humidity_fan_entities
                )
                if h_on != h_currently_on:
                    await self._set_fan_state(
                        room_fan.humidity_fan_entities, h_on, 100
                    )

    def _evaluate_temp_fan(
        self,
        room_fan: RoomFanState,
        room_temp: float,
        setpoint_high: float,
        occupied: bool,
        now: datetime,
    ) -> tuple[bool, str, int]:
        """Evaluate whether temperature fan should be on.

        Returns (should_on, trigger_reason, speed_pct).
        """
        delta = room_temp - setpoint_high

        # 1. Energy fan_assist: turn on 1F above setpoint, off 1F below setpoint
        if self._fan_assist_active:
            if delta >= 1.0:
                return True, "fan_assist", self._compute_speed(delta)
            elif delta < -1.0 and room_fan.trigger == "fan_assist":
                pass  # fall through to off
            elif room_fan.trigger == "fan_assist":
                return True, "fan_assist", self._compute_speed(max(delta, 0))

        # 2. Temperature hysteresis
        if delta >= self._activation_delta:
            return True, "temperature", self._compute_speed(delta)
        elif room_fan.is_on and room_fan.trigger == "temperature":
            # Deactivation: off when delta drops below (activation - hysteresis)
            off_threshold = self._activation_delta - self._deactivation_delta
            if delta <= off_threshold:
                pass  # fall through to off check
            else:
                return True, "temperature", self._compute_speed(delta)

        # Evaluate off
        should_off = True

        # Occupancy gate with vacancy hold
        if not occupied:
            if not room_fan.vacancy_detected_time:
                room_fan.vacancy_detected_time = now.isoformat()
            vacancy_since = datetime.fromisoformat(room_fan.vacancy_detected_time)
            vacancy_seconds = (now - vacancy_since).total_seconds()
            if vacancy_seconds < DEFAULT_FAN_VACANCY_HOLD and room_fan.is_on:
                should_off = False  # Hold on during vacancy window
        else:
            room_fan.vacancy_detected_time = ""

        # Min runtime check (vacancy overrides min runtime)
        if room_fan.is_on and room_fan.last_on_time and occupied:
            on_since = datetime.fromisoformat(room_fan.last_on_time)
            runtime_minutes = (now - on_since).total_seconds() / 60
            if runtime_minutes < self._min_runtime:
                should_off = False

        if should_off and room_fan.is_on:
            return False, "", 0

        # If currently on with a trigger and we didn't explicitly turn off, keep on
        if room_fan.is_on and room_fan.trigger:
            return True, room_fan.trigger, room_fan.speed_pct

        return False, "", 0

    def _evaluate_humidity_fan(
        self, humidity: float, room_fan: RoomFanState,
    ) -> bool:
        """Evaluate humidity fan with hysteresis."""
        h_currently_on = any(
            self._is_entity_on(e) for e in room_fan.humidity_fan_entities
        )
        if humidity >= DEFAULT_HUMIDITY_FAN_ON:
            return True
        if h_currently_on and humidity > DEFAULT_HUMIDITY_FAN_OFF:
            return True  # Still above off threshold
        return False

    def _compute_speed(self, delta: float) -> int:
        """Compute fan speed percentage from temperature delta."""
        if delta >= FAN_SPEED_HIGH_DELTA:
            return FAN_SPEED_HIGH_PCT
        if delta >= FAN_SPEED_MED_DELTA:
            return FAN_SPEED_MED_PCT
        if delta >= FAN_SPEED_LOW_DELTA:
            return FAN_SPEED_LOW_PCT
        return FAN_SPEED_LOW_PCT  # minimum speed if on

    def _is_entity_on(self, entity_id: str) -> bool:
        """Check if an entity is currently on."""
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == "on"

    async def _set_fan_state(
        self, entities: list[str], on: bool, speed_pct: int,
    ) -> None:
        """Set fan entities on/off with speed."""
        for entity_id in entities:
            try:
                if on:
                    if entity_id.startswith("fan."):
                        await self.hass.services.async_call(
                            "fan", "turn_on",
                            {"entity_id": entity_id, "percentage": speed_pct},
                            blocking=False,
                        )
                    else:
                        await self.hass.services.async_call(
                            "homeassistant", "turn_on",
                            {"entity_id": entity_id},
                            blocking=False,
                        )
                else:
                    if entity_id.startswith("fan."):
                        await self.hass.services.async_call(
                            "fan", "turn_off",
                            {"entity_id": entity_id},
                            blocking=False,
                        )
                    else:
                        await self.hass.services.async_call(
                            "homeassistant", "turn_off",
                            {"entity_id": entity_id},
                            blocking=False,
                        )
            except Exception as e:
                _LOGGER.error("HVAC Fans: failed to control %s: %s", entity_id, e)

    def get_fan_status(self) -> dict[str, Any]:
        """Return fan status for sensor attributes."""
        active = sum(1 for r in self._room_fans.values() if r.is_on)
        return {
            "rooms_with_fans": len(self._room_fans),
            "active_fan_rooms": active,
            "fan_assist_active": self._fan_assist_active,
        }

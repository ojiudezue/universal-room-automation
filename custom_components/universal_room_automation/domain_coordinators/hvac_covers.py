"""Cover Controller for HVAC Coordinator.

Manages common area blinds for solar gain reduction.
Closes south/west facing covers during peak solar hours in warm months
when outdoor temperature is high.

v3.8.4-H3: Initial implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_COVERS,
    CONF_ENTRY_TYPE,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)
from .hvac_const import (
    CONF_HVAC_COVER_ENTITIES,
    COVER_CLOSE_TEMP,
    COVER_COMMAND_WINDOW_SECONDS,
    COVER_MANUAL_OVERRIDE_HOURS,
    COVER_OPEN_TEMP,
    COVER_SOLAR_HOUR_END,
    COVER_SOLAR_HOUR_START,
    COVER_SOLAR_MONTHS,
)
from .hvac_zones import ZoneManager
from .signals import EnergyConstraint

_LOGGER = logging.getLogger(__name__)


@dataclass
class ManagedCover:
    """Tracks state for a single managed cover."""

    entity_id: str
    last_command_time: str = ""  # ISO timestamp of last command we sent
    manual_override_until: str = ""  # ISO timestamp when override expires


class CoverController:
    """Manages common area covers for solar gain reduction.

    Closes covers during peak solar hours (13-18) in Apr-Oct when hot.
    Respects manual overrides with 2-hour backoff.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
    ) -> None:
        """Initialize cover controller."""
        self.hass = hass
        self._zone_manager = zone_manager
        self._covers: dict[str, ManagedCover] = {}
        self._covers_closed: bool = False
        self._state_listener_unsub: CALLBACK_TYPE | None = None
        self._outdoor_temp_entity: str = ""

    def discover_covers(self) -> int:
        """Discover cover entities for solar gain management.

        Sources:
        1. CONF_HVAC_COVER_ENTITIES from Coordinator Manager entry (explicit)
        2. CONF_COVERS from room entries in HVAC zones

        Excludes covers with device_class 'garage'.
        Returns count of managed covers.
        """
        self._covers.clear()
        seen: set[str] = set()

        # Find outdoor temp sensor from room entries (house-level config)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            entry_type = entry.data.get(CONF_ENTRY_TYPE, "")
            if entry_type == ENTRY_TYPE_ROOM:
                continue  # Skip room entries
            merged = {**entry.data, **entry.options}
            sensor = merged.get(CONF_OUTSIDE_TEMP_SENSOR, "")
            if sensor:
                self._outdoor_temp_entity = sensor
                break

        # 1. Coordinator Manager explicit covers
        from ..const import ENTRY_TYPE_COORDINATOR_MANAGER
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                continue
            merged = {**entry.data, **entry.options}
            cover_list = merged.get(CONF_HVAC_COVER_ENTITIES, [])
            if isinstance(cover_list, str):
                cover_list = [cover_list]
            for entity_id in cover_list:
                if entity_id and entity_id not in seen:
                    if not self._is_garage_cover(entity_id):
                        self._covers[entity_id] = ManagedCover(entity_id=entity_id)
                        seen.add(entity_id)

        # 2. Room covers from HVAC zone rooms
        room_to_zone: dict[str, str] = {}
        for zone_id, zone in self._zone_manager.zones.items():
            for room_name in zone.rooms:
                room_to_zone[room_name] = zone_id

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            room_name = entry.data.get(CONF_ROOM_NAME, "")
            if not room_name or room_name not in room_to_zone:
                continue

            merged = {**entry.data, **entry.options}
            covers = merged.get(CONF_COVERS, [])
            if isinstance(covers, str):
                covers = [covers]
            for entity_id in covers:
                if entity_id and entity_id not in seen:
                    if not self._is_garage_cover(entity_id):
                        self._covers[entity_id] = ManagedCover(entity_id=entity_id)
                        seen.add(entity_id)

        _LOGGER.info("HVAC Covers: Managing %d covers", len(self._covers))
        return len(self._covers)

    def setup_listeners(self) -> None:
        """Subscribe to cover state changes for manual override detection."""
        if not self._covers:
            return

        entity_ids = list(self._covers.keys())
        self._state_listener_unsub = async_track_state_change_event(
            self.hass, entity_ids, self._handle_cover_state_change
        )
        _LOGGER.info(
            "HVAC Covers: watching %d covers for manual overrides",
            len(entity_ids),
        )

    def teardown(self) -> None:
        """Cancel state listeners."""
        if self._state_listener_unsub:
            self._state_listener_unsub()
            self._state_listener_unsub = None

    async def update(self, energy_constraint: EnergyConstraint | None) -> None:
        """Run cover control logic.

        Called from the HVAC decision cycle every 5 minutes.
        """
        if not self._covers:
            return

        now = dt_util.now()
        month = now.month
        hour = now.hour

        # Get outdoor temperature
        outdoor_temp = self._get_outdoor_temp()
        if outdoor_temp is None and energy_constraint:
            outdoor_temp = energy_constraint.forecast_high_temp

        if outdoor_temp is None:
            return  # Can't make cover decisions without temperature

        # Determine if covers should be closed for solar gain
        in_solar_window = (
            month in COVER_SOLAR_MONTHS
            and COVER_SOLAR_HOUR_START <= hour < COVER_SOLAR_HOUR_END
        )

        # Hysteresis: close at COVER_CLOSE_TEMP, open at COVER_OPEN_TEMP
        should_close = False
        if in_solar_window:
            if outdoor_temp >= COVER_CLOSE_TEMP:
                should_close = True
            elif self._covers_closed and outdoor_temp > COVER_OPEN_TEMP:
                should_close = True  # Stay closed until below open threshold

        # Outside solar window: open
        if not in_solar_window and self._covers_closed:
            should_close = False

        # Execute commands
        if should_close and not self._covers_closed:
            await self._command_covers("close", now)
            self._covers_closed = True
        elif not should_close and self._covers_closed:
            await self._command_covers("open", now)
            self._covers_closed = False

    async def _command_covers(self, action: str, now: datetime) -> None:
        """Close or open all managed covers (respecting manual overrides)."""
        service = "close_cover" if action == "close" else "open_cover"
        commanded = 0

        for entity_id, cover in self._covers.items():
            # Skip if manual override is active
            if cover.manual_override_until:
                override_end = datetime.fromisoformat(cover.manual_override_until)
                if now < override_end:
                    _LOGGER.debug(
                        "HVAC Covers: skipping %s — manual override until %s",
                        entity_id, cover.manual_override_until,
                    )
                    continue
                else:
                    cover.manual_override_until = ""

            # Check if already in desired state
            state = self.hass.states.get(entity_id)
            if state:
                if action == "close" and state.state == "closed":
                    continue
                if action == "open" and state.state == "open":
                    continue

            try:
                cover.last_command_time = now.isoformat()
                await self.hass.services.async_call(
                    "cover", service,
                    {"entity_id": entity_id},
                    blocking=False,
                )
                commanded += 1
            except Exception as e:
                _LOGGER.error("HVAC Covers: failed to %s %s: %s",
                              action, entity_id, e)

        if commanded:
            _LOGGER.info("HVAC Covers: %s %d covers", action, commanded)

    @callback
    def _handle_cover_state_change(self, event: Event) -> None:
        """Detect manual cover position changes."""
        entity_id = event.data.get("entity_id", "")
        cover = self._covers.get(entity_id)
        if cover is None:
            return

        # If we recently commanded this cover, ignore the state change
        if cover.last_command_time:
            last_cmd = datetime.fromisoformat(cover.last_command_time)
            now = dt_util.now()
            if (now - last_cmd).total_seconds() < COVER_COMMAND_WINDOW_SECONDS:
                return

        # Manual change detected — set override backoff
        now = dt_util.now()
        override_end = now + timedelta(hours=COVER_MANUAL_OVERRIDE_HOURS)
        cover.manual_override_until = override_end.isoformat()

        _LOGGER.info(
            "HVAC Covers: manual override on %s, backoff until %s",
            entity_id, cover.manual_override_until,
        )

    def _get_outdoor_temp(self) -> float | None:
        """Read outdoor temperature from configured sensor."""
        if not self._outdoor_temp_entity:
            return None
        state = self.hass.states.get(self._outdoor_temp_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _is_garage_cover(self, entity_id: str) -> bool:
        """Check if a cover is a garage door (should be excluded)."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.attributes.get("device_class") == "garage"

    def get_cover_status(self) -> dict[str, Any]:
        """Return cover status for sensor attributes."""
        manual_overrides = sum(
            1 for c in self._covers.values()
            if c.manual_override_until
            and datetime.fromisoformat(c.manual_override_until) > dt_util.now()
        )
        return {
            "managed_covers": len(self._covers),
            "covers_closed": self._covers_closed,
            "manual_overrides": manual_overrides,
        }

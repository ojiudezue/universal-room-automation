"""Zone management for HVAC Coordinator.

Auto-discovers HVAC zones from CONF_ZONE_THERMOSTAT config on URA zones,
aggregates room conditions (temperature, humidity, occupancy) per zone,
and provides zone-aware control.

v3.8.0-H1: Initial implementation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ZONE_ROOMS,
    CONF_ZONE_THERMOSTAT,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,
    ENTRY_TYPE_ZONE_MANAGER,
)
from .hvac_const import DUTY_CYCLE_WINDOW_SECONDS

_LOGGER = logging.getLogger(__name__)


@dataclass
class RoomCondition:
    """Aggregated condition for a single room."""

    room_name: str
    temperature: float | None = None
    humidity: float | None = None
    occupied: bool = False
    weight: float = 1.0


@dataclass
class ZoneState:
    """State of a single HVAC zone."""

    zone_id: str
    zone_name: str
    climate_entity: str
    rooms: list[str] = field(default_factory=list)

    # Current climate entity state
    preset_mode: str = ""
    hvac_mode: str = ""
    hvac_action: str = ""
    current_temperature: float | None = None
    current_humidity: float | None = None
    target_temp_high: float | None = None
    target_temp_low: float | None = None

    # Aggregated room conditions
    room_conditions: list[RoomCondition] = field(default_factory=list)

    # Override tracking
    override_count_today: int = 0
    ac_reset_count_today: int = 0
    last_override_direction: str = ""  # "cooler" or "warmer" or ""
    last_stuck_detected: str = ""  # ISO timestamp when stuck cycle detected

    # v3.17.0: Zone Intelligence fields
    # D1: Vacancy management
    last_occupied_time: datetime | None = None
    vacancy_sweep_done: bool = False
    vacancy_sweep_enabled: bool = True

    # D4: Zone presence state machine
    zone_presence_state: str = "unknown"

    # D5: Duty cycle enforcement
    runtime_seconds_this_window: float = 0.0
    window_start: datetime | None = None
    runtime_exceeded: bool = False

    # D6: Max-occupancy-duration failsafe
    continuous_occupied_since: datetime | None = None

    @property
    def any_room_occupied(self) -> bool:
        """Return True if any room in this zone is occupied."""
        return any(r.occupied for r in self.room_conditions)

    @property
    def occupied_rooms(self) -> list[str]:
        """Return list of occupied room names."""
        return [r.room_name for r in self.room_conditions if r.occupied]

    @property
    def avg_temperature(self) -> float | None:
        """Weighted average temperature across rooms."""
        temps = [
            (r.temperature, r.weight)
            for r in self.room_conditions
            if r.temperature is not None
        ]
        if not temps:
            return self.current_temperature
        total_weight = sum(w for _, w in temps)
        if total_weight == 0:
            return None
        return sum(t * w for t, w in temps) / total_weight

    @property
    def avg_humidity(self) -> float | None:
        """Average humidity across rooms."""
        vals = [r.humidity for r in self.room_conditions if r.humidity is not None]
        if not vals:
            return self.current_humidity
        return sum(vals) / len(vals)


class ZoneManager:
    """Discovers and manages HVAC zones.

    Auto-discovers zones from CONF_ZONE_THERMOSTAT config entries.
    Aggregates room conditions per zone from URA room data.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize zone manager."""
        self.hass = hass
        self._zones: dict[str, ZoneState] = {}

    @property
    def zones(self) -> dict[str, ZoneState]:
        """Return all discovered zones."""
        return self._zones

    @property
    def zone_count(self) -> int:
        """Return number of discovered zones."""
        return len(self._zones)

    def _zone_id_from_thermostat(self, climate_entity: str, fallback_num: int) -> str:
        """Derive zone_id from the thermostat entity name.

        If the entity contains "zone_N", uses that number to match
        physical thermostat labeling. Otherwise auto-numbers sequentially.
        Guarantees no collisions with already-assigned zone IDs.
        """
        match = re.search(r"zone[_\s]?(\d+)", climate_entity)
        if match:
            candidate = f"zone_{match.group(1)}"
            if candidate not in self._zones:
                return candidate
            # Collision — fall through to auto-number

        # Auto-number: find next unused ID
        n = fallback_num
        while f"zone_{n}" in self._zones:
            n += 1
        return f"zone_{n}"

    async def async_discover_zones(self) -> int:
        """Discover HVAC zones from zone config entries.

        Reads CONF_ZONE_THERMOSTAT from:
        1. Zone Manager entry zones dict (current architecture, v3.6.0+)
        2. Legacy individual ENTRY_TYPE_ZONE entries (pre-v3.6.0 fallback)

        Returns count of discovered zones.
        """
        from datetime import timedelta
        from .hvac_const import DEFAULT_VACANCY_GRACE_MINUTES

        self._zones.clear()
        next_zone_num = 0  # Fallback counter for thermostats without a zone number

        # Build entry_id -> room_name mapping for Zone Manager rooms
        entry_id_to_room_name: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                room_name = entry.data.get(CONF_ROOM_NAME, "")
                if room_name:
                    entry_id_to_room_name[entry.entry_id] = room_name

        # 1. Read from Zone Manager entry (primary source)
        # Multiple URA zones can share a thermostat (e.g., Entertainment +
        # Master Suite both served by StudyB Zone 1). When this happens,
        # merge their rooms into a single HVAC zone so occupancy in ANY
        # of the mapped zones keeps the thermostat active.
        thermostat_to_zone_id: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE_MANAGER:
                continue

            merged = {**entry.data, **entry.options}
            zones_dict = merged.get("zones", {})

            for zm_zone_name, zone_cfg in zones_dict.items():
                thermostat = zone_cfg.get(CONF_ZONE_THERMOSTAT)
                if not thermostat:
                    continue

                # Convert entry IDs to room names
                raw_rooms = zone_cfg.get(CONF_ZONE_ROOMS, [])
                room_names: list[str] = []
                if isinstance(raw_rooms, list):
                    for r in raw_rooms:
                        name = entry_id_to_room_name.get(r)
                        if name:
                            room_names.append(name)
                        else:
                            _LOGGER.warning(
                                "HVAC: Zone %s has unknown room entry %s",
                                zm_zone_name, r,
                            )

                from .hvac_const import CONF_ZONE_VACANCY_SWEEP_ENABLED
                sweep_enabled = zone_cfg.get(CONF_ZONE_VACANCY_SWEEP_ENABLED, True)

                # If thermostat already assigned, merge rooms into existing zone
                existing_zone_id = thermostat_to_zone_id.get(thermostat)
                if existing_zone_id is not None:
                    existing = self._zones[existing_zone_id]
                    existing.rooms.extend(room_names)
                    existing.zone_name = f"{existing.zone_name} + {zm_zone_name}"
                    _LOGGER.info(
                        "HVAC: Merged %s into %s (%s) — now %d rooms",
                        zm_zone_name, existing_zone_id,
                        thermostat, len(existing.rooms),
                    )
                    continue

                zone_id = self._zone_id_from_thermostat(
                    thermostat, next_zone_num
                )
                if zone_id == f"zone_{next_zone_num}":
                    next_zone_num += 1
                thermostat_to_zone_id[thermostat] = zone_id

                zone_state = ZoneState(
                    zone_id=zone_id,
                    zone_name=zm_zone_name,
                    climate_entity=thermostat,
                    rooms=room_names,
                    vacancy_sweep_enabled=sweep_enabled,
                )
                # Initialize never-occupied zones as eligible for vacancy
                zone_state.last_occupied_time = (
                    dt_util.utcnow()
                    - timedelta(minutes=DEFAULT_VACANCY_GRACE_MINUTES + 1)
                )
                self._zones[zone_id] = zone_state

                _LOGGER.info(
                    "HVAC: Discovered %s (%s) → %s (%d rooms, sweep=%s)",
                    zone_id, zm_zone_name, thermostat, len(room_names),
                    sweep_enabled,
                )

        # 2. Legacy fallback: individual ENTRY_TYPE_ZONE entries
        seen_thermostats: set[str] = set(thermostat_to_zone_id.keys())
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE:
                continue

            merged = {**entry.data, **entry.options}
            thermostat = merged.get(CONF_ZONE_THERMOSTAT)
            if not thermostat:
                continue

            # Convert entry IDs to room names (same as Zone Manager path)
            raw_rooms = merged.get(CONF_ZONE_ROOMS, [])
            room_names = []
            if isinstance(raw_rooms, list):
                for r in raw_rooms:
                    room_names.append(entry_id_to_room_name.get(r, r))

            # Merge into existing zone if thermostat already assigned
            existing_zone_id = thermostat_to_zone_id.get(thermostat)
            if existing_zone_id is not None:
                existing = self._zones[existing_zone_id]
                existing.rooms.extend(room_names)
                continue

            if thermostat in seen_thermostats:
                continue

            seen_thermostats.add(thermostat)
            zone_id = self._zone_id_from_thermostat(
                thermostat, next_zone_num
            )
            if zone_id == f"zone_{next_zone_num}":
                next_zone_num += 1
            zone_name = merged.get("zone_name", f"Zone {zone_id.split('_')[-1]}")
            thermostat_to_zone_id[thermostat] = zone_id

            zone_state = ZoneState(
                zone_id=zone_id,
                zone_name=zone_name,
                climate_entity=thermostat,
                rooms=room_names,
            )
            zone_state.last_occupied_time = (
                dt_util.utcnow()
                - timedelta(minutes=DEFAULT_VACANCY_GRACE_MINUTES + 1)
            )
            self._zones[zone_id] = zone_state

            _LOGGER.info(
                "HVAC: Discovered %s (%s) → %s (%d rooms)",
                zone_id, zone_name, thermostat,
                len(room_names),
            )

        _LOGGER.info("HVAC: Discovered %d zones with thermostats", len(self._zones))
        return len(self._zones)

    def update_zone_climate_state(self, zone_id: str) -> None:
        """Update zone state from its climate entity."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return

        state = self.hass.states.get(zone.climate_entity)
        if state is None or state.state == "unavailable":
            return

        zone.hvac_mode = state.state
        zone.hvac_action = state.attributes.get("hvac_action", "")
        zone.preset_mode = state.attributes.get("preset_mode", "")
        zone.current_temperature = state.attributes.get("current_temperature")
        zone.current_humidity = state.attributes.get("current_humidity")
        zone.target_temp_high = state.attributes.get("target_temp_high")
        zone.target_temp_low = state.attributes.get("target_temp_low")

    def update_all_zones(self) -> None:
        """Update climate state for all zones."""
        for zone_id in self._zones:
            self.update_zone_climate_state(zone_id)

    def update_room_conditions(self) -> None:
        """Aggregate room conditions per zone from URA room coordinators.

        Room coordinators are stored at hass.data[DOMAIN][entry.entry_id],
        keyed by config entry UUID. We find them by matching room_name
        from config entries against zone.rooms.
        """
        # Build room_name -> coordinator mapping
        room_coordinators: dict[str, Any] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            room_name = entry.data.get(CONF_ROOM_NAME, "")
            if not room_name:
                continue
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coordinator is not None:
                room_coordinators[room_name] = coordinator

        now = dt_util.utcnow()
        for zone in self._zones.values():
            zone.room_conditions.clear()
            for room_name in zone.rooms:
                coordinator = room_coordinators.get(room_name)
                if coordinator is None:
                    continue

                # Read from room coordinator data dict
                data = {}
                if hasattr(coordinator, "data") and coordinator.data:
                    data = coordinator.data

                condition = RoomCondition(
                    room_name=room_name,
                    temperature=data.get("temperature"),
                    humidity=data.get("humidity"),
                    occupied=data.get("occupied", False),
                )
                zone.room_conditions.append(condition)

            # v3.17.0 D1: Track last_occupied_time for vacancy management
            if zone.any_room_occupied:
                zone.last_occupied_time = now
                zone.vacancy_sweep_done = False  # Reset sweep flag on re-occupation
                # D6: Track continuous occupancy
                if zone.continuous_occupied_since is None:
                    zone.continuous_occupied_since = now
            else:
                zone.continuous_occupied_since = None

    def get_zone_status_attrs(self, zone_id: str) -> dict[str, Any]:
        """Return rich attribute dict for a zone status sensor."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return {}

        return {
            "friendly_name": zone.zone_name,
            "zone_id": zone.zone_id,
            "climate_entity": zone.climate_entity,
            "preset_mode": zone.preset_mode,
            "hvac_action": zone.hvac_action,
            "current_temperature": zone.current_temperature,
            "current_humidity": zone.current_humidity,
            "target_temp_high": zone.target_temp_high,
            "target_temp_low": zone.target_temp_low,
            "any_room_occupied": zone.any_room_occupied,
            "occupied_rooms": zone.occupied_rooms,
            "avg_temperature": (
                round(zone.avg_temperature, 1)
                if zone.avg_temperature is not None
                else None
            ),
            "avg_humidity": (
                round(zone.avg_humidity, 1)
                if zone.avg_humidity is not None
                else None
            ),
            "room_count": len(zone.rooms),
            "override_count_today": zone.override_count_today,
            "ac_reset_count_today": zone.ac_reset_count_today,
            # v3.17.0: Zone Intelligence attributes
            "zone_presence_state": zone.zone_presence_state,
            "vacancy_sweep_done": zone.vacancy_sweep_done,
            "vacancy_sweep_enabled": zone.vacancy_sweep_enabled,
            "runtime_exceeded": zone.runtime_exceeded,
            "runtime_duty_cycle_pct": (
                min(
                    round(
                        zone.runtime_seconds_this_window
                        / DUTY_CYCLE_WINDOW_SECONDS
                        * 100,
                        1,
                    ),
                    100.0,
                )
                if zone.window_start is not None
                else 0.0
            ),
            "continuous_occupied_hours": (
                round(
                    (dt_util.utcnow() - zone.continuous_occupied_since).total_seconds()
                    / 3600,
                    1,
                )
                if zone.continuous_occupied_since is not None
                else 0.0
            ),
        }

    def reset_daily_counters(self) -> None:
        """Reset daily counters for all zones (call at midnight)."""
        for zone in self._zones.values():
            zone.override_count_today = 0
            zone.ac_reset_count_today = 0

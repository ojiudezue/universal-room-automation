"""Activity Logger for Universal Room Automation.

Provides transparent logging of URA coordinator decisions and automation actions.
Writes to ura_activity_log DB table, fires ura_action HA events, and dispatches
SIGNAL_ACTIVITY_LOGGED for sensor updates.

All writes go through the existing DB write queue. Never raises — all exceptions
are caught and logged.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .domain_coordinators.signals import SIGNAL_ACTIVITY_LOGGED

_LOGGER = logging.getLogger(__name__)

# Dedup windows by importance level (seconds)
_DEDUP_WINDOWS: dict[str, float] = {
    "info": 30.0,
    "notable": 60.0,
    "critical": 300.0,  # v4.0.11: 5-min safety net (coordinators should transition-gate)
}

# Maximum size for details_json (bytes)
_MAX_DETAILS_SIZE = 2048


def _is_entity_id_shaped(value: str) -> bool:
    """Return True when ``value`` has Home Assistant's ``domain.object_id`` shape.

    Deliberately a SHAPE check, not an existence check: the entity may legitimately
    not exist yet (boot ordering), but it must still be splittable, because that is
    all the recorder's global listener requires. Mirrors the split HA itself performs
    (`homeassistant.core.split_entity_id`): exactly one dot, non-empty on both sides.
    """
    if not value:
        return False
    parts = value.split(".")
    return len(parts) == 2 and all(parts)


class ActivityLogger:
    """Lightweight activity logging for URA coordinators.

    Writes to ura_activity_log table AND fires ura_action HA events.
    All writes go through the existing DB write queue.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the activity logger."""
        self.hass = hass
        self._dedup_cache: dict[str, float] = {}  # key -> monotonic timestamp

    async def log(
        self,
        coordinator: str,
        action: str,
        description: str,
        room: str | None = None,
        zone: str | None = None,
        importance: str = "info",
        details: dict | None = None,
        entity_id: str | None = None,
    ) -> None:
        """Log an activity to DB and fire an HA event. Never raises."""
        try:
            # Dedup check
            if not self._should_log(coordinator, action, room, description, importance):
                return

            now = dt_util.utcnow()
            timestamp = now.isoformat()

            # Cap details_json at 2KB — store None if oversized to avoid invalid JSON
            details_json: str | None = None
            if details is not None:
                try:
                    raw = json.dumps(details, default=str)
                    if len(raw) > _MAX_DETAILS_SIZE:
                        details_json = json.dumps({
                            "truncated": True,
                            "original_size": len(raw),
                        })
                    else:
                        details_json = raw
                except (TypeError, ValueError):
                    details_json = None

            # Write to DB
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is not None:
                try:
                    await database.log_activity(
                        timestamp=timestamp,
                        coordinator=coordinator,
                        action=action,
                        room=room,
                        zone=zone,
                        importance=importance,
                        description=description,
                        details_json=details_json,
                        entity_id=entity_id,
                    )
                except Exception as db_err:
                    _LOGGER.debug("Activity log DB write failed: %s", db_err)

            # Fire HA event for logbook integration
            event_data: dict[str, Any] = {
                "coordinator": coordinator,
                "action": action,
                "description": description,
                "importance": importance,
                "timestamp": timestamp,
            }
            if room is not None:
                event_data["room"] = room
            if zone is not None:
                event_data["zone"] = zone
            # ACTIVITY-LOG-BARE-SLUG-ENTITY-ID-1: only a WELL-FORMED entity_id
            # may ride the bus event.
            #
            # WHY THIS GUARD EXISTS. Home Assistant's recorder subscribes to
            # EVERY event on the bus and calls `split_entity_id()` on any
            # `entity_id` it finds. A value without a `domain.object_id` shape
            # raises `ValueError: Invalid entity ID <x>` INSIDE the recorder's
            # listener job — so a URA-internal naming slip becomes an ERROR in
            # somebody else's code path. Observed live 2026-09-16: the EVSE
            # charge-onset telemetry passes a BAY SLUG ("garage_a"), producing
            # exactly that ERROR on the running system.
            #
            # The slug is deliberately still written to the DB column above —
            # there it is useful bay identity, and it has no consumer that
            # requires entity-id shape. It is ONLY the bus event that must
            # honour HA's contract. Dropping the field is the safe failure:
            # the logbook link is lost for that row, nothing else changes.
            if entity_id is not None:
                if isinstance(entity_id, str) and _is_entity_id_shaped(entity_id):
                    event_data["entity_id"] = entity_id
                else:
                    _LOGGER.debug(
                        "Activity log: dropping malformed entity_id %r from "
                        "the ura_action event (coordinator=%s action=%s) — "
                        "HA's recorder would raise on it; the value is still "
                        "stored in the DB row",
                        entity_id, coordinator, action,
                    )

            self.hass.bus.async_fire("ura_action", event_data)

            # Signal sensor update
            async_dispatcher_send(self.hass, SIGNAL_ACTIVITY_LOGGED, {
                "coordinator": coordinator,
                "action": action,
                "description": description,
                "room": room,
                "zone": zone,
                "importance": importance,
                "timestamp": timestamp,
                "entity_id": entity_id,
            })

        except Exception as exc:
            _LOGGER.debug("ActivityLogger.log() failed (swallowed): %s", exc)

    def _should_log(
        self,
        coordinator: str,
        action: str,
        room: str | None,
        description: str,
        importance: str,
    ) -> bool:
        """Check dedup cache. Returns True if this event should be logged."""
        window = _DEDUP_WINDOWS.get(importance, 30.0)
        if window <= 0:
            return True  # Critical always logs

        key = f"{coordinator}:{action}:{room or ''}:{description}"
        now = time.monotonic()
        last = self._dedup_cache.get(key)

        if last is not None and (now - last) < window:
            return False

        self._dedup_cache[key] = now
        # Evict stale entries if cache gets large
        if len(self._dedup_cache) > 500:
            max_window = max(_DEDUP_WINDOWS.values())
            cutoff = now - max_window * 2
            self._dedup_cache = {
                k: v for k, v in self._dedup_cache.items() if v > cutoff
            }
        return True

    def clear_dedup_cache(self) -> None:
        """Clear the dedup cache. Called during daily prune."""
        self._dedup_cache.clear()

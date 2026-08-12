"""CONSOL-1 §D8 — zone_monitoring in-code tripwire.

Subscribes to state changes on the four `automation.zone{1,3}_{motion,person}_event_counter`
entities. Any state change means the counter automation ran (i.e. the
HA-side pager stack fired). Fires a MEDIUM NM alert once per counter
per day (per-day dedup) via the notification manager.

This is a POST-cycle observability probe. When the tripwire produces
zero leak notifications between ship and the next URA release, a
follow-up commit strips the notify actions from
`packages/zone_monitoring.yaml`. Auto-close by evidence, no calendar
observation window (per plan §5/§8 rev-2 #5).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, STUCK_SIGNAL_NM_HAZARD_TYPE_ZONE_MONITORING_LEAK

_LOGGER = logging.getLogger(__name__)

_TRIPWIRE_ENTITIES: tuple[str, ...] = (
    "automation.zone_1_person_event_counter",
    "automation.zone_1_motion_event_counter",
    "automation.zone_3_person_event_counter",
    "automation.zone_3_motion_event_counter",
)


class ZoneMonitoringTripwire:
    """Track HA zone_monitoring counter fires and route them through NM."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._unsub: Any = None
        # (entity_id, date) -> True. Prunes on first fire of a new date.
        self._fired_today: dict[tuple[str, date], bool] = {}

    async def async_setup(self) -> None:
        """Subscribe to state changes on the four counter automations."""
        self._unsub = async_track_state_change_event(
            self.hass, list(_TRIPWIRE_ENTITIES), self._on_state_change,
        )
        _LOGGER.info(
            "ZoneMonitoringTripwire: subscribed to %d counter automations",
            len(_TRIPWIRE_ENTITIES),
        )

    async def async_teardown(self) -> None:
        try:
            if self._unsub is not None:
                self._unsub()
                self._unsub = None
        except Exception:  # noqa: BLE001
            pass

    @callback
    def _on_state_change(self, event: Event) -> None:
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if entity_id not in _TRIPWIRE_ENTITIES:
            return
        # Ignore boot-time RestoreEntity replay (old_state is None).
        if old_state is None or new_state is None:
            return
        # Ignore no-op transitions (state unchanged AND no last_triggered
        # attribute delta). Any real fire flips last_triggered forward,
        # which triggers a state-change event even if state stays "on".
        try:
            new_lt = new_state.attributes.get("last_triggered")
            old_lt = old_state.attributes.get("last_triggered")
        except Exception:  # noqa: BLE001
            new_lt = old_lt = None
        if new_lt is None or new_lt == old_lt:
            return

        today = date.today()
        key = (entity_id, today)
        if key in self._fired_today:
            _LOGGER.debug(
                "ZoneMonitoringTripwire: %s already fired today — dedup",
                entity_id,
            )
            return
        # Prune stale dates (>1 back) to bound memory.
        self._fired_today = {
            k: v for k, v in self._fired_today.items() if k[1] == today
        }
        self._fired_today[key] = True

        _LOGGER.info(
            "ZoneMonitoringTripwire: leak detected on %s (last_triggered=%s)",
            entity_id, new_lt,
        )
        self.hass.async_create_task(self._async_emit(entity_id, new_lt))

    async def _async_emit(self, entity_id: str, last_triggered: Any) -> None:
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or not getattr(nm, "enabled", False):
            _LOGGER.debug(
                "ZoneMonitoringTripwire: NM absent — cannot emit leak for %s",
                entity_id,
            )
            return
        try:
            from .domain_coordinators.base import Severity  # local import — cycle safety

            await nm.async_notify(
                coordinator_id="zone_monitoring_tripwire",
                severity=Severity.MEDIUM,
                title="Zone monitoring pager leak",
                message=(
                    f"HA counter '{entity_id}' fired — the URA cycle "
                    "assumed this stack was quiescent. Investigate and "
                    "strip the notify action from "
                    "packages/zone_monitoring.yaml."
                ),
                hazard_type=STUCK_SIGNAL_NM_HAZARD_TYPE_ZONE_MONITORING_LEAK,
                location=entity_id,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "ZoneMonitoringTripwire: NM emit for %s raised: %s",
                entity_id, exc,
            )

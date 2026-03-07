"""Override Arrester + AC Reset for HVAC Coordinator.

Detects manual thermostat overrides, applies two-tier severity response
(severe: immediate revert after grace; normal: compromise then revert),
and resets stuck AC cycles.

v3.8.3-H2: Initial implementation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .hvac_const import (
    AC_RESET_MAX_PER_DAY,
    AC_RESET_OFF_DURATION_SECONDS,
    AC_RESET_STUCK_MINUTES,
    DEFAULT_COMPROMISE_MINUTES,
    OVERRIDE_COAST_TOLERANCE_BONUS,
    OVERRIDE_NORMAL_DELTA,
    OVERRIDE_NORMAL_GRACE_MINUTES,
    OVERRIDE_SEVERE_DELTA,
    OVERRIDE_SEVERE_GRACE_MINUTES,
)
from .hvac_zones import ZoneManager, ZoneState

_LOGGER = logging.getLogger(__name__)


class OverrideArrester:
    """Detects and responds to manual thermostat overrides.

    Event-driven via async_track_state_change_event on climate entities.
    Two-tier severity:
      - Severe (>3F from expected): 2min grace -> immediate revert
      - Normal (>1F from expected): 5min grace -> 30min compromise -> revert

    Also handles AC reset for stuck cooling/heating cycles.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
        compromise_minutes: int = DEFAULT_COMPROMISE_MINUTES,
        ac_reset_timeout: int = AC_RESET_STUCK_MINUTES,
        enabled: bool = True,
    ) -> None:
        """Initialize override arrester."""
        self.hass = hass
        self._zone_manager = zone_manager
        self._compromise_minutes = compromise_minutes
        self._ac_reset_timeout = ac_reset_timeout
        self._enabled = enabled

        # Listener unsubscribes
        self._state_unsubs: list[CALLBACK_TYPE] = []

        # Per-zone timers: zone_id -> cancel callback
        self._grace_timers: dict[str, CALLBACK_TYPE] = {}
        self._compromise_timers: dict[str, CALLBACK_TYPE] = {}
        self._reset_timers: dict[str, CALLBACK_TYPE] = {}

        # Per-zone override state
        self._override_active: dict[str, bool] = {}
        self._compromise_active: dict[str, bool] = {}

        # Energy constraint awareness
        self._energy_offset: float = 0.0
        self._energy_coast: bool = False

        # Suppression: entity_ids to ignore overrides on (during URA-initiated changes)
        self._suppressed_entities: set[str] = set()

    def setup(self) -> None:
        """Subscribe to climate entity state changes."""
        entity_ids = [
            zone.climate_entity
            for zone in self._zone_manager.zones.values()
        ]
        if not entity_ids:
            _LOGGER.debug("Override Arrester: no climate entities to watch")
            return

        self._state_unsubs.append(
            async_track_state_change_event(
                self.hass, entity_ids, self._handle_climate_change
            )
        )
        _LOGGER.info(
            "Override Arrester: watching %d climate entities", len(entity_ids)
        )

    def teardown(self) -> None:
        """Cancel all listeners and timers."""
        for unsub in self._state_unsubs:
            unsub()
        self._state_unsubs.clear()

        for cancel in self._grace_timers.values():
            cancel()
        self._grace_timers.clear()

        for cancel in self._compromise_timers.values():
            cancel()
        self._compromise_timers.clear()

        for cancel in self._reset_timers.values():
            cancel()
        self._reset_timers.clear()

    def update_energy_state(self, offset: float, coast: bool) -> None:
        """Update energy constraint state for tolerance adjustment."""
        self._energy_offset = offset
        self._energy_coast = coast

    def suppress(self, entity_id: str) -> None:
        """Suppress override detection for an entity (URA-initiated change)."""
        self._suppressed_entities.add(entity_id)

    def unsuppress(self, entity_id: str) -> None:
        """Re-enable override detection for an entity."""
        self._suppressed_entities.discard(entity_id)

    @property
    def enabled(self) -> bool:
        """Return whether the arrester is actively reverting overrides."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set arrester enabled state. Cancels in-flight timers on disable."""
        self._enabled = value
        if not value:
            # Cancel all pending timers to prevent stale reverts/compromises
            for cancel in self._grace_timers.values():
                cancel()
            self._grace_timers.clear()
            for cancel in self._compromise_timers.values():
                cancel()
            self._compromise_timers.clear()
            self._override_active.clear()
            self._compromise_active.clear()
        _LOGGER.info("Override Arrester %s", "enabled" if value else "disabled (passive mode)")

    @callback
    def _handle_climate_change(self, event: Event) -> None:
        """Handle climate entity state change — detect overrides."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None or old_state is None:
            return

        # Skip if suppressed (URA-initiated temperature change)
        if entity_id in self._suppressed_entities:
            self._suppressed_entities.discard(entity_id)
            return

        # Find which zone this entity belongs to
        zone = self._find_zone_by_entity(entity_id)
        if zone is None:
            return

        # Check for preset change to "manual" — that's the override signal
        new_preset = new_state.attributes.get("preset_mode", "")
        old_preset = old_state.attributes.get("preset_mode", "")

        # Also check for direct temperature changes while on a preset
        new_high = new_state.attributes.get("target_temp_high")
        old_high = old_state.attributes.get("target_temp_high")
        new_low = new_state.attributes.get("target_temp_low")
        old_low = old_state.attributes.get("target_temp_low")

        # Detect override: preset changed to "manual" OR temp changed while on preset
        is_override = False
        if new_preset == "manual" and old_preset != "manual":
            is_override = True
        elif new_preset != "manual" and (new_high != old_high or new_low != old_low):
            # Temperature changed but preset didn't go to manual — this is
            # our own preset change or a preset range adjustment. Ignore.
            pass

        if not is_override:
            return

        _LOGGER.info(
            "Override detected on %s (%s): preset %s->%s, temp_high %s->%s",
            zone.zone_name, entity_id, old_preset, new_preset,
            old_high, new_high,
        )

        # Use the actual old setpoints from the event (what was active before override)
        # This is more accurate than seasonal defaults since presets may differ per thermostat
        if old_high is None and old_low is None:
            _LOGGER.debug("Override: no old setpoints available to compare")
            return

        try:
            expected_cool = float(old_high) if old_high is not None else None
            expected_heat = float(old_low) if old_low is not None else None
        except (ValueError, TypeError):
            _LOGGER.debug("Override: invalid old setpoint values")
            return

        if expected_cool is None and expected_heat is None:
            return

        # Passive mode: track override but don't revert
        if not self._enabled:
            zone.override_count_today += 1
            _LOGGER.info(
                "Override detected on %s (passive mode, no revert): delta from old setpoints",
                zone.zone_name,
            )
            return

        # Widen tolerance during energy coast
        tolerance_bonus = OVERRIDE_COAST_TOLERANCE_BONUS if self._energy_coast else 0.0

        # Determine override severity
        delta = self._compute_override_delta(
            new_high, new_low,
            expected_cool or 0.0,
            expected_heat or 0.0,
        )

        if delta is None:
            return

        abs_delta = abs(delta)
        direction = "cooler" if delta < 0 else "warmer"
        zone.last_override_direction = direction

        severe_threshold = OVERRIDE_SEVERE_DELTA + tolerance_bonus
        normal_threshold = OVERRIDE_NORMAL_DELTA + tolerance_bonus

        if abs_delta >= severe_threshold:
            self._handle_severe_override(
                zone, old_preset, expected_cool, expected_heat, delta
            )
        elif abs_delta >= normal_threshold:
            self._handle_normal_override(
                zone, old_preset, expected_cool, expected_heat, delta,
                new_high, new_low,
            )
        else:
            _LOGGER.debug(
                "Override on %s within tolerance (delta=%.1fF, threshold=%.1fF)",
                zone.zone_name, abs_delta, normal_threshold,
            )

    def _handle_severe_override(
        self,
        zone: ZoneState,
        original_preset: str,
        expected_cool: float,
        expected_heat: float,
        delta: float,
    ) -> None:
        """Handle severe override (>3F): short grace then revert."""
        zone_id = zone.zone_id
        zone.override_count_today += 1
        self._override_active[zone_id] = True

        # Cancel any existing timers for this zone
        self._cancel_zone_timers(zone_id)

        grace_seconds = OVERRIDE_SEVERE_GRACE_MINUTES * 60

        _LOGGER.warning(
            "SEVERE override on %s: delta=%.1fF %s, reverting in %ds",
            zone.zone_name, abs(delta),
            zone.last_override_direction, grace_seconds,
        )

        self._grace_timers[zone_id] = async_call_later(
            self.hass,
            grace_seconds,
            lambda _now: self.hass.async_create_task(
                self._revert_override(zone, original_preset)
            ),
        )

        # NM alert
        self.hass.async_create_task(
            self._send_nm_alert(
                title=f"HVAC Override: {zone.zone_name}",
                message=(
                    f"Severe override ({abs(delta):.0f}F {zone.last_override_direction}) "
                    f"detected. Reverting to {original_preset} in "
                    f"{OVERRIDE_SEVERE_GRACE_MINUTES} minutes."
                ),
                severity="high",
            )
        )

    def _handle_normal_override(
        self,
        zone: ZoneState,
        original_preset: str,
        expected_cool: float | None,
        expected_heat: float | None,
        delta: float,
        new_high: Any,
        new_low: Any,
    ) -> None:
        """Handle normal override (1-3F): grace then compromise then revert."""
        zone_id = zone.zone_id
        zone.override_count_today += 1
        self._override_active[zone_id] = True

        # Cancel any existing timers
        self._cancel_zone_timers(zone_id)

        grace_seconds = OVERRIDE_NORMAL_GRACE_MINUTES * 60

        # Compute compromise: move each setpoint halfway toward the override
        cool_delta = (float(new_high) - expected_cool) if (new_high is not None and expected_cool is not None) else 0
        heat_delta = (float(new_low) - expected_heat) if (new_low is not None and expected_heat is not None) else 0
        compromise_cool = (expected_cool + cool_delta / 2) if expected_cool is not None else expected_cool
        compromise_heat = (expected_heat + heat_delta / 2) if expected_heat is not None else expected_heat

        _LOGGER.info(
            "Normal override on %s: delta=%.1fF %s, compromise in %ds",
            zone.zone_name, abs(delta),
            zone.last_override_direction, grace_seconds,
        )

        self._grace_timers[zone_id] = async_call_later(
            self.hass,
            grace_seconds,
            lambda _now: self.hass.async_create_task(
                self._apply_compromise(
                    zone, original_preset,
                    compromise_cool, compromise_heat,
                    expected_cool, expected_heat,
                )
            ),
        )

        # NM alert
        self.hass.async_create_task(
            self._send_nm_alert(
                title=f"HVAC Override: {zone.zone_name}",
                message=(
                    f"Override ({abs(delta):.0f}F {zone.last_override_direction}) "
                    f"detected. Compromise in {OVERRIDE_NORMAL_GRACE_MINUTES}min, "
                    f"full revert after {self._compromise_minutes}min."
                ),
                severity="medium",
            )
        )

    async def _apply_compromise(
        self,
        zone: ZoneState,
        original_preset: str,
        compromise_cool: float,
        compromise_heat: float,
        expected_cool: float,
        expected_heat: float,
    ) -> None:
        """Apply compromise temperature, then schedule full revert."""
        zone_id = zone.zone_id
        self._compromise_active[zone_id] = True

        # Remove grace timer reference
        self._grace_timers.pop(zone_id, None)

        _LOGGER.info(
            "Override compromise on %s: setting cool=%.0f heat=%.0f for %dmin",
            zone.zone_name, compromise_cool, compromise_heat,
            self._compromise_minutes,
        )

        # Set compromise temperature
        try:
            service_data: dict[str, Any] = {"entity_id": zone.climate_entity}
            service_data["target_temp_high"] = compromise_cool
            service_data["target_temp_low"] = compromise_heat
            await self.hass.services.async_call(
                "climate", "set_temperature", service_data, blocking=False,
            )
        except Exception as e:
            _LOGGER.error("Override: failed to set compromise on %s: %s",
                          zone.climate_entity, e)

        # Schedule full revert after compromise period
        compromise_seconds = self._compromise_minutes * 60
        self._compromise_timers[zone_id] = async_call_later(
            self.hass,
            compromise_seconds,
            lambda _now: self.hass.async_create_task(
                self._revert_override(zone, original_preset)
            ),
        )

    async def _revert_override(
        self, zone: ZoneState, original_preset: str,
    ) -> None:
        """Revert zone to its original preset."""
        zone_id = zone.zone_id

        # Clean up timer references
        self._grace_timers.pop(zone_id, None)
        self._compromise_timers.pop(zone_id, None)
        self._override_active[zone_id] = False
        self._compromise_active[zone_id] = False

        _LOGGER.info(
            "Override revert on %s: restoring preset %s",
            zone.zone_name, original_preset,
        )

        try:
            await self.hass.services.async_call(
                "climate",
                "set_preset_mode",
                {
                    "entity_id": zone.climate_entity,
                    "preset_mode": original_preset,
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error(
                "Override: failed to revert %s to preset %s: %s",
                zone.climate_entity, original_preset, e,
            )

    # =========================================================================
    # AC Reset — stuck cycle detection (polling, called from decision cycle)
    # =========================================================================

    async def check_ac_reset(self) -> None:
        """Check for stuck AC cycles across all zones.

        Called from the 5-minute HVAC decision cycle.
        A zone is "stuck" if actively heating/cooling for ac_reset_timeout minutes
        and current temp hasn't moved toward setpoint.
        """
        now = dt_util.now()

        for zone_id, zone in self._zone_manager.zones.items():
            if zone.ac_reset_count_today >= AC_RESET_MAX_PER_DAY:
                continue

            # Skip zones with active overrides
            if self._override_active.get(zone_id, False):
                continue

            # Only check zones actively heating or cooling
            if zone.hvac_action not in ("cooling", "heating"):
                zone.last_stuck_detected = ""
                continue

            if zone.current_temperature is None:
                continue

            # Stuck = actively running but temp hasn't reached setpoint
            is_stuck = False
            if zone.hvac_action == "cooling" and zone.target_temp_high is not None:
                if zone.current_temperature > zone.target_temp_high:
                    is_stuck = True  # Still hot despite cooling
            elif zone.hvac_action == "heating" and zone.target_temp_low is not None:
                if zone.current_temperature < zone.target_temp_low:
                    is_stuck = True  # Still cold despite heating

            if not is_stuck:
                zone.last_stuck_detected = ""
                continue

            # Track how long we've been stuck
            if not zone.last_stuck_detected:
                zone.last_stuck_detected = now.isoformat()
                continue

            stuck_since = datetime.fromisoformat(zone.last_stuck_detected)
            stuck_minutes = (now - stuck_since).total_seconds() / 60

            if stuck_minutes < self._ac_reset_timeout:
                continue

            # Stuck long enough — perform reset
            _LOGGER.warning(
                "AC Reset on %s: stuck %s for %.0fmin past setpoint, "
                "cycling off for %ds",
                zone.zone_name, zone.hvac_action, stuck_minutes,
                AC_RESET_OFF_DURATION_SECONDS,
            )

            zone.ac_reset_count_today += 1
            zone.last_stuck_detected = ""

            await self._perform_ac_reset(zone)

    async def _perform_ac_reset(self, zone: ZoneState) -> None:
        """Perform AC reset: off -> wait -> restore mode."""
        original_mode = zone.hvac_mode
        original_action = zone.hvac_action
        zone_id = zone.zone_id

        # Turn off
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": zone.climate_entity, "hvac_mode": "off"},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.error("AC Reset: failed to turn off %s: %s",
                          zone.climate_entity, e)
            return

        # Schedule restore after off duration
        self._reset_timers[zone_id] = async_call_later(
            self.hass,
            AC_RESET_OFF_DURATION_SECONDS,
            lambda _now: self.hass.async_create_task(
                self._restore_after_reset(zone, original_mode)
            ),
        )

        # NM alert
        await self._send_nm_alert(
            title=f"AC Reset: {zone.zone_name}",
            message=(
                f"Stuck {original_action} cycle detected — "
                f"cycling off for {AC_RESET_OFF_DURATION_SECONDS}s then restoring "
                f"{original_mode}. Reset #{zone.ac_reset_count_today}/{AC_RESET_MAX_PER_DAY} today."
            ),
            severity="high",
        )

    async def _restore_after_reset(
        self, zone: ZoneState, original_mode: str,
    ) -> None:
        """Restore HVAC mode after AC reset off period."""
        zone_id = zone.zone_id
        self._reset_timers.pop(zone_id, None)

        _LOGGER.info(
            "AC Reset restore on %s: setting mode back to %s",
            zone.zone_name, original_mode,
        )

        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": zone.climate_entity, "hvac_mode": original_mode},
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error(
                "AC Reset: failed to restore %s to %s: %s",
                zone.climate_entity, original_mode, e,
            )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _find_zone_by_entity(self, entity_id: str) -> ZoneState | None:
        """Find zone by climate entity ID."""
        for zone in self._zone_manager.zones.values():
            if zone.climate_entity == entity_id:
                return zone
        return None

    def _compute_override_delta(
        self,
        new_high: Any,
        new_low: Any,
        expected_cool: float,
        expected_heat: float,
    ) -> float | None:
        """Compute the largest deviation from expected setpoints.

        Returns positive if warmer (cool setpoint raised), negative if cooler.
        """
        deltas = []
        if new_high is not None:
            try:
                deltas.append(float(new_high) - expected_cool)
            except (ValueError, TypeError):
                pass
        if new_low is not None:
            try:
                deltas.append(float(new_low) - expected_heat)
            except (ValueError, TypeError):
                pass

        if not deltas:
            return None

        # Return the delta with the largest absolute value
        return max(deltas, key=abs)

    def _cancel_zone_timers(self, zone_id: str) -> None:
        """Cancel all active timers for a zone."""
        for timer_dict in (
            self._grace_timers,
            self._compromise_timers,
            self._reset_timers,
        ):
            cancel = timer_dict.pop(zone_id, None)
            if cancel:
                cancel()

    async def _send_nm_alert(
        self,
        title: str,
        message: str,
        severity: str = "high",
    ) -> None:
        """Send alert through Notification Manager."""
        from ..const import DOMAIN

        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            _LOGGER.warning("HVAC Override NM (no NM): %s — %s", title, message)
            return
        try:
            from .base import Severity

            severity_map = {
                "low": Severity.LOW,
                "medium": Severity.MEDIUM,
                "high": Severity.HIGH,
                "critical": Severity.CRITICAL,
            }
            await nm.async_notify(
                coordinator_id="hvac",
                severity=severity_map.get(severity, Severity.HIGH),
                title=title,
                message=message,
                hazard_type="hvac_override",
            )
        except Exception:
            _LOGGER.debug("HVAC Override: NM alert failed (non-fatal): %s", title)

    # =========================================================================
    # Status for sensors
    # =========================================================================

    def get_override_status(self) -> dict[str, Any]:
        """Return override status for all zones."""
        total_overrides = sum(
            z.override_count_today for z in self._zone_manager.zones.values()
        )
        total_resets = sum(
            z.ac_reset_count_today for z in self._zone_manager.zones.values()
        )
        active_overrides = sum(1 for v in self._override_active.values() if v)
        active_compromises = sum(1 for v in self._compromise_active.values() if v)

        return {
            "enabled": self._enabled,
            "overrides_today": total_overrides,
            "ac_resets_today": total_resets,
            "active_overrides": active_overrides,
            "active_compromises": active_compromises,
        }

    def get_arrester_state(self) -> str:
        """Return current arrester state for diagnostic sensor."""
        if not self._enabled:
            return "disabled"
        if any(self._compromise_active.values()):
            return "compromise"
        if self._grace_timers:
            return "grace_period"
        if any(self._override_active.values()):
            return "active"
        return "idle"

    def get_arrester_detail(self) -> dict[str, Any]:
        """Return per-zone arrester detail for diagnostic sensor."""
        zones_detail = {}
        for zone_id, zone in self._zone_manager.zones.items():
            detail: dict[str, Any] = {
                "overrides_today": zone.override_count_today,
                "ac_resets_today": zone.ac_reset_count_today,
            }
            if self._override_active.get(zone_id, False):
                detail["state"] = "override_active"
            if self._compromise_active.get(zone_id, False):
                detail["state"] = "compromise"
            if zone_id in self._grace_timers:
                detail["state"] = "grace_period"
            if "state" not in detail:
                detail["state"] = "idle"
            if zone.last_override_direction:
                detail["last_direction"] = zone.last_override_direction
            zones_detail[zone.zone_name] = detail
        return {
            "state": self.get_arrester_state(),
            "enabled": self._enabled,
            "zones": zones_detail,
            "energy_coast": self._energy_coast,
            "energy_offset": self._energy_offset,
        }

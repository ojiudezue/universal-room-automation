"""Data coordinator for Universal Room Automation."""
#
# Universal Room Automation vv5.5.7
# Build: 2026-01-02
# File: coordinator.py
# v3.2.8: Support for active state change listeners in aggregation sensors
# NEW: get_became_occupied_time() for three-tier scanner disambiguation
# FIX: Environmental sensors now read from options (user changes) with data fallback
#

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
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
    CONF_OCCUPANCY_DEBOUNCE,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_ILLUMINANCE_SENSOR,
    CONF_POWER_SENSORS,
    CONF_ENERGY_SENSOR,
    CONF_ENERGY_SENSORS,
    CONF_ELECTRICITY_RATE,
    DEFAULT_OCCUPANCY_TIMEOUT,
    DEFAULT_OCCUPANCY_DEBOUNCE,
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
    OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE,
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
    # v3.10.0: Automation chaining
    CONF_AUTOMATION_CHAINS,
    LUX_DARK_THRESHOLD,
    LUX_BRIGHT_THRESHOLD,
    TRIGGER_ENTER,
    TRIGGER_EXIT,
    TRIGGER_LUX_DARK,
    TRIGGER_LUX_BRIGHT,
    # v3.12.0: M2 coordinator signal triggers
    TRIGGER_HOUSE_STATE_PREFIX,
    TRIGGER_ENERGY_CONSTRAINT,
    TRIGGER_SAFETY_HAZARD,
    TRIGGER_SECURITY_EVENT,
    # v3.12.0: M3 AI NL Rules
    CONF_AI_RULES,
    CONF_LIGHTS,
    CONF_FANS,
    CONF_AUTO_DEVICES,
    CONF_AUTO_SWITCHES,
    CONF_CLIMATE_ENTITY,
    CONF_ROOM_NAME,
)
from .domain_coordinators.signals import (
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_ENERGY_CONSTRAINT,
    SIGNAL_SAFETY_HAZARD,
    SIGNAL_SECURITY_EVENT,
    SIGNAL_SUBSTRATE_KIND_CHANGED,
)
from .domain_coordinators.energy_billing import _get_effective_rate_kwh
from .domain_coordinators._units import energy_state_to_kwh, power_state_to_w
from .automation import RoomAutomation

_LOGGER = logging.getLogger(__name__)

# v4.5.15: 4-hour failsafe constant moved to const.DEFAULT_FAILSAFE_DURATION_SECONDS.
# Room-type-keyed durations in const.ROOM_TYPE_FAILSAFE_DURATIONS;
# resolved at runtime by `_get_failsafe_duration_seconds`.


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
        self._last_occupancy_source: str = "none"  # Track source for ble→motion re-entry
        self._last_source_reentry_time: datetime | None = None  # Cooldown for re-entry
        self._became_occupied_time: datetime | None = None  # v3.2.4: When current occupancy session started
        self._unsub_state_listeners = []

        # Debounce: require sensors active for N seconds before confirming entry
        self._occupancy_first_detected: datetime | None = None
        # v4.0.11: Configurable debounce (default 150ms). Config stores ms, convert to s.
        self._occupancy_debounce_seconds: float = entry.options.get(
            CONF_OCCUPANCY_DEBOUNCE,
            entry.data.get(CONF_OCCUPANCY_DEBOUNCE, DEFAULT_OCCUPANCY_DEBOUNCE)
        ) / 1000.0
        self._debounce_refresh_unsub = None  # cancel handle for scheduled debounce refresh

        # v4.2.0: Infrastructure room flag (always-on equipment rooms)
        merged_config = {**entry.data, **entry.options}
        room_type = merged_config.get("room_type", "generic")
        self._room_type: str = room_type  # v4.5.15: failsafe lookup
        self._infrastructure_room: bool = (room_type == "infrastructure")

        # v4.2.6: Shared timestamp for deferring first-cycle DB operations.
        # Add per-room jitter (0-60s) so 31 rooms don't all hit the 5-min mark
        # simultaneously and recreate the thundering herd.
        _now = dt_util.now() - timedelta(seconds=random.uniform(0, 60))

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

        # Fan-noise Mode-2 mitigation: ring of recent occupancy sources so the
        # room-tier fan-recheck trigger can require N consecutive mmwave-sole
        # ticks (D1 #2). Appended at end of _async_update_data.
        import collections
        self._recent_occupancy_sources: collections.deque[str] = (
            collections.deque(maxlen=10)
        )

        # v3.20.0: Room state DB backup throttle
        # v4.2.6: Initialize to now() — room state was just restored from DB, no need to save immediately
        self._last_room_state_save: datetime = _now

        # v3.22.12: Skip automation on first refresh to prevent false entry
        # triggers on reload/restart. Cleared after the first _async_update_data.
        self._skip_first_automation: bool = True

        # v4.0.7: Rate limiter for event-driven refresh (monotonic seconds)
        self._last_event_refresh: float = 0.0
        self._trailing_refresh_unsub = None  # Cancel handle for trailing-edge refresh

        # v4.0.10: Phase 3 prediction/energy query cache (5-minute TTL)
        # v4.2.6: Initialize to now() to defer first-cycle reads (5 reads/room × 31 rooms = 155 reads)
        self._last_prediction_query: datetime = _now
        self._cached_predictions: dict = {}

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
        # v4.1.0: Per-sensor baselines for multi-energy support
        # v4.2.28: Persisted to URA DB to survive restart; needs_reset tracks
        # baselines that were stale at midnight because sensor was unavailable.
        self._energy_baselines_today: dict[str, float] = {}
        self._energy_baselines_needs_reset: set[str] = set()
        self._energy_baselines_loaded: bool = False
        # Energy unit normalization cycle (Bug Class #30 on the energy device class):
        # one-shot reset gate, set after the version sentinel has been observed
        # so we only attempt the schema-version migration once per process boot.
        self._energy_baselines_schema_checked: bool = False
        # D4: dead-energy-sensor observability — rate-limited WARNING.
        # Keyed by room_id (entry_id); value = monotonic timestamp of last log.
        self._energy_sensors_dead_last_warn: float | None = None
        self._energy_sensors_dead: bool = False
        self._energy_baseline_today = 0.0  # Legacy — kept for weekly/monthly tracking
        self._energy_baseline_week = 0.0
        self._energy_baseline_month = 0.0
        self._last_week_reset = dt_util.now()
        self._last_month_reset = dt_util.now().replace(day=1)
        
        # Environmental data logging
        # v4.2.6: Initialize to now() so first-cycle writes are deferred to 5-min mark.
        # Prevents 31 rooms × 3 writes + 5 reads = 248 ops flooding the DB at startup.
        # Loses ~5 min of env/energy data after restart — trivial gap for a continuous system.
        self._last_env_log = _now
        self._last_energy_log = _now
        
        # Automation tracking
        self._last_trigger_source = None  # "motion", "presence", "door"
        self._last_trigger_entity = None  # entity_id that triggered
        self._last_trigger_time = None    # datetime
        self._last_action_description = None  # "Turned on 3 lights"
        self._last_action_entity = None   # entity_id or list
        self._last_action_type = None     # "turn_on", "turn_off", etc.
        self._last_action_time = None     # datetime
        
        # v3.10.0: Lux trigger zone tracking (dark/mid/bright)
        self._last_lux_zone: str | None = None

        # v3.12.0: M2 signal listener unsub handles
        self._unsub_signal_listeners: list = []

        # Occupancy substrate unification cycle (B-C1 fix-up): dedicated
        # unsub list for SIGNAL_SUBSTRATE_KIND_CHANGED subscription. MUST
        # NOT share storage with _unsub_signal_listeners, because
        # _update_signal_subscriptions() clears that list wholesale every
        # time options-flow saves (and also at first_refresh setup), which
        # would silently unsubscribe the substrate handler and break the
        # D3 actuation-critical path. Cleared only on first_refresh (stale
        # listener purge) and on unload (see __init__.py).
        self._unsub_substrate_listeners: list = []

        # v3.12.0: M3 AI rule conflict tracking
        self._conflict_detected: bool = False
        self._last_conflicts: list = []

        # v3.12.0 M4: Trigger execution tracking
        self._last_trigger_event: str | None = None
        self._last_trigger_time_str: str | None = None

        # v3.2.2.0 FIX: Merge entry.options with entry.data
        # entry.data = initial setup
        # entry.options = user changes via Configure button
        # options should override data!
        config = {**entry.data, **entry.options}
        
        # Automation handler
        self.automation = RoomAutomation(hass, config, self)
        
        # v4.0.10: Jitter poll interval to prevent thundering herd.
        # 31 rooms starting at the same HA restart time all poll simultaneously,
        # causing 20-39s event loop contention. 0-5s jitter spreads rooms over
        # the window. Kept small to limit occupancy timeout overshoot (max +5s).
        jitter = random.uniform(0, 5)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data.get('room_name', 'unknown')}",
            update_interval=timedelta(seconds=30 + jitter),
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

    def _get_failsafe_duration_seconds(self) -> int:
        """v4.5.15: Return the max occupancy duration before this room's
        failsafe forces vacancy.

        Closet + bathroom: 60 min (lazy auto-off; catches stuck sensor
        / fan-as-motion / forgotten light). All other room types: 4 hr
        (the original RESILIENCE-001 default).

        Pure lookup against ROOM_TYPE_FAILSAFE_DURATIONS in const.py.
        No config option introduced — keep cycle scope minimal; if
        per-room override is wanted later, add via options flow.
        """
        from .const import (
            ROOM_TYPE_FAILSAFE_DURATIONS,
            DEFAULT_FAILSAFE_DURATION_SECONDS,
        )
        return ROOM_TYPE_FAILSAFE_DURATIONS.get(
            self._room_type, DEFAULT_FAILSAFE_DURATION_SECONDS,
        )
    
    # =========================================================================
    # v3.10.0 TRIGGER DETECTION & AUTOMATION CHAINING
    # =========================================================================

    def _detect_lux_trigger(self, current_lux: float | None) -> str | None:
        """Detect lux threshold crossing with 3-zone hysteresis.

        Zones: dark (<50), mid (50-200), bright (>200).
        Returns trigger name on zone transition, None otherwise.
        """
        if current_lux is None:
            return None

        if current_lux < LUX_DARK_THRESHOLD:
            new_zone = "dark"
        elif current_lux > LUX_BRIGHT_THRESHOLD:
            new_zone = "bright"
        else:
            new_zone = "mid"

        if new_zone == self._last_lux_zone:
            return None

        old_zone = self._last_lux_zone
        self._last_lux_zone = new_zone

        if old_zone is None:
            return None  # First reading, no transition

        if new_zone == "dark":
            return TRIGGER_LUX_DARK
        elif new_zone == "bright":
            return TRIGGER_LUX_BRIGHT
        return None

    async def _fire_chained_automations(self, triggers: list[str]) -> None:
        """Fire chained HA automations for the given trigger types.

        Called after URA built-in automation completes. Fires each
        bound automation via automation.trigger.
        """
        chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
        if not chains:
            return

        room_name = self.entry.data.get("room_name", "unknown")
        tasks = []

        for trigger in triggers:
            automation_id = chains.get(trigger)
            if not automation_id:
                continue

            state = self.hass.states.get(automation_id)
            if state is None or state.state in ("unavailable", "off"):
                _LOGGER.warning(
                    "[%s] Chained automation '%s' for trigger '%s' is %s — skipping",
                    room_name, automation_id, trigger,
                    "not found" if state is None else state.state,
                )
                continue

            _LOGGER.info(
                "[%s] Firing chained automation '%s' (trigger=%s)",
                room_name, automation_id, trigger,
            )
            tasks.append(
                self.hass.services.async_call(
                    "automation", "trigger",
                    {"entity_id": automation_id},
                    blocking=False,
                )
            )

            # Activity log: chained automation trigger
            activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger:
                tasks.append(
                    activity_logger.log(
                        coordinator="room",
                        action="chain_trigger",
                        description=f"Triggered '{automation_id}' ({trigger})",
                        room=room_name,
                        entity_id=automation_id,
                    )
                )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    _LOGGER.error(
                        "[%s] Chained automation call failed: %s",
                        room_name, result,
                    )

    # =========================================================================
    # v3.12.0 M2: COORDINATOR SIGNAL TRIGGER HANDLERS
    # =========================================================================

    # =========================================================================
    # GATING MODEL FOR SIGNAL HANDLERS (documented v4.5.8)
    # =========================================================================
    # The 4 coordinator-signal handlers below have an intentional asymmetry
    # vs. the per-room occupancy/lux trigger path in _async_update_data:
    #
    #   - Occupancy/lux triggers (per-room, frequent):
    #         gated by BOTH _is_automation_enabled() AND _is_ai_automation_enabled()
    #
    #   - House-state, energy-constraint signal handlers (system-level, rare):
    #         gated by _is_ai_automation_enabled() ONLY — NOT by the master
    #         automation switch. Pausing per-room automation does not silence
    #         system-level reactions to house state or energy events.
    #
    #   - Safety, security signal handlers (critical):
    #         NOT gated by either toggle (Review fix F11). A smoke detector
    #         firing or a security event must still execute its chained
    #         automations and AI rules even if the user has paused all
    #         automation. Killing safety with the regular toggle would be
    #         a real bug.
    #
    # This is design intent, not an oversight. Test coverage in
    # quality/tests/test_v458_signal_handler_gating.py asserts the matrix
    # so future "consistency fixes" don't accidentally regress safety.
    #
    # =========================================================================

    @callback
    def _on_house_state_changed(self, payload) -> None:
        """Handle house state change signal → fire house_state_* trigger.

        Gating: AI automation toggle ONLY.

        The master `automation` switch does NOT gate this handler — house
        state transitions are system-level events (away ↔ home ↔ sleep ↔
        guest, etc.) and any chained automation or AI rule keyed on
        `house_state_*` should fire regardless of whether per-room
        automation is paused. If the user wants to silence everything
        including house-state reactions, they disable the AI automation
        toggle separately.
        """
        if isinstance(payload, dict):
            new_state = payload.get("new_state", "")
        elif hasattr(payload, "new_state"):
            new_state = payload.new_state
        else:
            new_state = str(payload)

        if not new_state:
            return

        trigger_key = f"{TRIGGER_HOUSE_STATE_PREFIX}{new_state}"
        chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
        rules = self._get_config(CONF_AI_RULES, [])
        has_matching_rule = any(r.get("trigger_type") == trigger_key for r in rules if r.get("enabled", True))
        if (trigger_key in chains or has_matching_rule) and self._is_ai_automation_enabled():
            room_name = self.entry.data.get("room_name", "unknown")
            _LOGGER.info(
                "[%s] House state → %s, firing chained automation + AI rules",
                room_name, new_state,
            )
            async def _fire_house_state():
                self._last_trigger_event = trigger_key
                self._last_trigger_time_str = dt_util.utcnow().isoformat()
                await self._fire_chained_automations([trigger_key])
                await self._execute_ai_rules([trigger_key])
            # setup/unload symmetry: dispatcher coalescer for a
            # @callback handler. Tracked via the room entry so an
            # in-flight chain is cancelled on entry reload/unload.
            # B-HIGH-2 (Review B): pass eager_start=False so the
            # coroutine starts on the loop, not synchronously in
            # this dispatcher callback. Without it, late-arriving
            # signals during teardown would eagerly start a coroutine
            # that touches popped hass.data[DOMAIN] keys and propagate
            # synchronous errors back to the dispatcher.
            self.entry.async_create_background_task(
                self.hass, _fire_house_state(),
                f"ura_fire_house_state_{self.entry.entry_id[:8]}",
                eager_start=False,
            )

    @callback
    def _on_energy_constraint(self, payload) -> None:
        """Handle energy constraint signal → fire energy_constraint trigger.

        Gating: AI automation toggle ONLY (same as _on_house_state_changed).

        Energy constraint signals fire when the energy coordinator changes
        load/shed/coast modes. These are reactive system-level signals and
        any chained automation or AI rule should fire whether or not the
        master `automation` switch is on. See the "GATING MODEL FOR SIGNAL
        HANDLERS" comment block above for the full matrix.
        """
        chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
        rules = self._get_config(CONF_AI_RULES, [])
        has_matching_rule = any(r.get("trigger_type") == TRIGGER_ENERGY_CONSTRAINT for r in rules if r.get("enabled", True))
        if (TRIGGER_ENERGY_CONSTRAINT in chains or has_matching_rule) and self._is_ai_automation_enabled():
            room_name = self.entry.data.get("room_name", "unknown")
            mode = payload.mode if hasattr(payload, "mode") else str(payload)
            _LOGGER.info(
                "[%s] Energy constraint '%s', firing chained automation + AI rules",
                room_name, mode,
            )
            async def _fire_energy():
                self._last_trigger_event = TRIGGER_ENERGY_CONSTRAINT
                self._last_trigger_time_str = dt_util.utcnow().isoformat()
                await self._fire_chained_automations([TRIGGER_ENERGY_CONSTRAINT])
                await self._execute_ai_rules([TRIGGER_ENERGY_CONSTRAINT])
            # setup/unload symmetry: tracked via the room entry.
            # B-HIGH-2: eager_start=False for dispatcher callback safety
            # (see _on_house_state_signal sibling comment above).
            self.entry.async_create_background_task(
                self.hass, _fire_energy(),
                "ura_fire_energy_constraint",
                eager_start=False,
            )

    @callback
    def _on_safety_hazard(self, payload) -> None:
        """Handle safety hazard signal → fire safety_hazard trigger.

        Gating: NEITHER toggle (Review fix F11 — DELIBERATE).

        A safety hazard signal (smoke / CO / leak / hard-fail sensor)
        must execute its chained automations and AI rules even if BOTH
        the master automation switch AND the AI automation toggle are
        off. Killing safety with a regular toggle would be a real bug —
        a user who paused automation for the night still expects the
        smoke detector's notify-and-light-the-path automation to run.
        See the "GATING MODEL FOR SIGNAL HANDLERS" comment block above.
        """
        chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
        rules = self._get_config(CONF_AI_RULES, [])
        has_matching_rule = any(r.get("trigger_type") == TRIGGER_SAFETY_HAZARD for r in rules if r.get("enabled", True))
        # Review fix F11: safety automations always fire regardless of AI toggle
        if TRIGGER_SAFETY_HAZARD in chains or has_matching_rule:
            room_name = self.entry.data.get("room_name", "unknown")
            hazard_type = payload.hazard_type if hasattr(payload, "hazard_type") else str(payload)
            _LOGGER.info(
                "[%s] Safety hazard '%s', firing chained automation + AI rules",
                room_name, hazard_type,
            )
            async def _fire_safety():
                self._last_trigger_event = TRIGGER_SAFETY_HAZARD
                self._last_trigger_time_str = dt_util.utcnow().isoformat()
                await self._fire_chained_automations([TRIGGER_SAFETY_HAZARD])
                await self._execute_ai_rules([TRIGGER_SAFETY_HAZARD])
            # setup/unload symmetry: tracked via the room entry.
            # B-HIGH-2: eager_start=False for dispatcher callback safety
            # (see _on_house_state_signal sibling comment above).
            self.entry.async_create_background_task(
                self.hass, _fire_safety(),
                "ura_fire_safety_hazard",
                eager_start=False,
            )

    @callback
    def _on_security_event(self, payload) -> None:
        """Handle security event signal → fire security_event trigger.

        Gating: NEITHER toggle (Review fix F11 — DELIBERATE, same as
        _on_safety_hazard).

        Security events (intrusion, glass break, door forced) must run
        their chained automations regardless of automation toggles —
        the user explicitly does not want a "pause automation" button
        to also disarm the security response. See the "GATING MODEL
        FOR SIGNAL HANDLERS" comment block above.
        """
        chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
        rules = self._get_config(CONF_AI_RULES, [])
        has_matching_rule = any(r.get("trigger_type") == TRIGGER_SECURITY_EVENT for r in rules if r.get("enabled", True))
        # Review fix F11: security automations always fire regardless of AI toggle
        if TRIGGER_SECURITY_EVENT in chains or has_matching_rule:
            room_name = self.entry.data.get("room_name", "unknown")
            event_type = payload.event_type if hasattr(payload, "event_type") else str(payload)
            _LOGGER.info(
                "[%s] Security event '%s', firing chained automation + AI rules",
                room_name, event_type,
            )
            async def _fire_security():
                self._last_trigger_event = TRIGGER_SECURITY_EVENT
                self._last_trigger_time_str = dt_util.utcnow().isoformat()
                await self._fire_chained_automations([TRIGGER_SECURITY_EVENT])
                await self._execute_ai_rules([TRIGGER_SECURITY_EVENT])
            # setup/unload symmetry: tracked via the room entry.
            # B-HIGH-2: eager_start=False for dispatcher callback safety
            # (see _on_house_state_signal sibling comment above).
            self.entry.async_create_background_task(
                self.hass, _fire_security(),
                "ura_fire_security_event",
                eager_start=False,
            )

    # =========================================================================
    # v3.12.0 M3: AI NL RULE EXECUTION & CONFLICT DETECTION
    # =========================================================================

    async def _execute_ai_rules(self, triggers: list[str]) -> None:
        """Execute AI rules matching fired triggers.

        Called after chained automations. Checks person filter and
        runs conflict detection before executing each rule's actions.
        """
        rules = self._get_config(CONF_AI_RULES, [])
        if not rules:
            return

        room_name = self.entry.data.get(CONF_ROOM_NAME, "unknown")
        identified_persons = self._get_identified_persons_in_room()

        # Only reset conflict state if at least one rule matches the trigger
        matching = [r for r in rules if r.get("enabled", True) and r.get("trigger_type") in triggers]
        if not matching:
            return
        self._conflict_detected = False
        self._last_conflicts = []

        for rule in matching:

            # Person filter (case-insensitive)
            person_filter = rule.get("person", "").strip()
            if person_filter:
                match = any(
                    person_filter.lower() == p.lower()
                    for p in identified_persons
                )
                if not match:
                    continue

            # Conflict detection (before execution)
            self._detect_ai_rule_conflicts(rule, rule.get("trigger_type", ""))

            _LOGGER.info(
                "[%s] Executing AI rule '%s' (trigger=%s, person='%s'): %s",
                room_name, rule.get("rule_id"), rule.get("trigger_type"),
                person_filter or "any", rule.get("description", ""),
            )

            for action in rule.get("actions", []):
                await self._execute_rule_action(action, room_name)

    # v3.12.0: Domain allowlist for AI rule service calls.
    # Only safe, device-control domains are permitted. Dangerous domains
    # (homeassistant, shell_command, recorder, script, etc.) are blocked
    # to prevent AI hallucination or prompt injection exploits.
    _AI_RULE_ALLOWED_DOMAINS: set = {
        "light", "switch", "fan", "cover", "climate", "media_player",
        "lock", "scene", "automation", "input_boolean", "input_number",
        "input_select", "input_text", "number", "select", "button",
        "humidifier", "vacuum", "water_heater", "valve",
    }

    async def _execute_rule_action(self, action: dict, room_name: str) -> None:
        """Execute a single parsed service call from an AI rule."""
        if not isinstance(action, dict):
            return
        domain = action.get("domain")
        service = action.get("service")
        target = action.get("target", {})
        if not isinstance(target, dict):
            target = {}
        raw_data = action.get("data", {})
        data = dict(raw_data) if isinstance(raw_data, dict) else {}

        if not domain or not service:
            return

        # Security: Only allow safe device-control domains
        if domain not in self._AI_RULE_ALLOWED_DOMAINS:
            _LOGGER.warning(
                "[%s] AI rule blocked: domain '%s' not in allowlist (service=%s.%s)",
                room_name, domain, domain, service,
            )
            return

        entity_id = target.get("entity_id")
        if entity_id:
            data["entity_id"] = entity_id

        try:
            await self.hass.services.async_call(domain, service, data, blocking=False)
        except Exception as err:
            _LOGGER.error(
                "[%s] AI rule action failed: %s.%s — %s", room_name, domain, service, err,
            )

    def _get_identified_persons_in_room(self) -> list[str]:
        """Get identified persons from census or BLE fallback."""
        room_name = self.entry.data.get(CONF_ROOM_NAME, "")

        # Census (cameras + BLE fusion)
        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census is not None:
            result = getattr(census, "get_room_identified_persons", lambda r: None)(room_name)
            if result is not None:
                return result

        # BLE-only fallback
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord is not None:
            return getattr(person_coord, "get_persons_in_room", lambda r: [])(room_name)

        return []

    def _detect_ai_rule_conflicts(self, rule: dict, trigger: str) -> None:
        """Detect entity conflicts between AI rule actions and URA built-in automation.

        Compares entity_ids targeted by the AI rule's parsed actions against
        entities URA's built-in automation acted on for the same trigger.
        """
        # Entities URA built-in automation targeted for this trigger
        ura_entities = set(self._get_builtin_target_entities(trigger))
        if not ura_entities:
            return

        # Entities this AI rule will target
        rule_entities = set()
        for action in rule.get("actions", []):
            target = action.get("target", {})
            entity_id = target.get("entity_id")
            if entity_id:
                if isinstance(entity_id, list):
                    rule_entities.update(entity_id)
                else:
                    rule_entities.add(entity_id)

        # Intersection = conflict
        contested = ura_entities & rule_entities
        if contested:
            conflict = {
                "rule_id": rule.get("rule_id"),
                "rule_description": rule.get("description", ""),
                "trigger": trigger,
                "contested_entities": sorted(contested),
                "timestamp": dt_util.utcnow().isoformat(),
            }
            self._last_conflicts.append(conflict)
            self._conflict_detected = True
            room_name = self.entry.data.get(CONF_ROOM_NAME, "unknown")
            _LOGGER.warning(
                "[%s] AI rule '%s' conflicts with built-in automation on: %s",
                room_name, rule.get("rule_id"), ", ".join(contested),
            )

    def _get_builtin_target_entities(self, trigger: str) -> list[str]:
        """Return entities that URA built-in automation targets for a trigger.

        Enter/lux_dark: configured lights, fans, climate
        Exit/lux_bright: configured lights, fans, auto_devices, auto_switches
        """
        entities: list[str] = []
        if trigger in (TRIGGER_ENTER, TRIGGER_LUX_DARK):
            entities.extend(self._get_config(CONF_LIGHTS, []))
            entities.extend(self._get_config(CONF_FANS, []))
            if climate := self._get_config(CONF_CLIMATE_ENTITY):
                entities.append(climate)
        elif trigger in (TRIGGER_EXIT, TRIGGER_LUX_BRIGHT):
            entities.extend(self._get_config(CONF_LIGHTS, []))
            entities.extend(self._get_config(CONF_FANS, []))
            entities.extend(self._get_config(CONF_AUTO_DEVICES, []))
            entities.extend(self._get_config(CONF_AUTO_SWITCHES, []))
        return entities

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

        # v3.20.0 D4: Clear stale listeners from any previous reload attempt
        # Prevents listener accumulation on rapid reloads
        for unsub in self._unsub_state_listeners:
            unsub()
        self._unsub_state_listeners.clear()
        for unsub in self._unsub_signal_listeners:
            unsub()
        self._unsub_signal_listeners.clear()
        # B-C1 fix-up: tear down stale substrate-listener subscriptions
        # symmetrically with _unsub_state_listeners / _unsub_signal_listeners.
        for unsub in self._unsub_substrate_listeners:
            unsub()
        self._unsub_substrate_listeners.clear()
        # v4.0.7: Cancel any pending trailing-edge refresh from rate limiter
        if self._trailing_refresh_unsub is not None:
            self._trailing_refresh_unsub()
            self._trailing_refresh_unsub = None

        # Call parent first_refresh to fetch initial data
        await super().async_config_entry_first_refresh()
        
        # NOW set up event listeners (after coordinator is fully initialized)
        # v4.0.7: Two-tier sensor tracking. Only occupancy-affecting sensors
        # trigger immediate refresh. Environmental sensors are read on the
        # 30s poll — their frequent updates were flooding the event loop
        # with ~6500 unnecessary heavy refreshes/hour across 31 rooms.

        # --- Tier 1 (immediate): sensors that affect occupancy detection ---
        motion_sensors = self._get_config(CONF_MOTION_SENSORS, []) or []
        mmwave_sensors = self._get_config(CONF_MMWAVE_SENSORS, []) or []
        occupancy_sensors = self._get_config(CONF_OCCUPANCY_SENSORS, []) or []

        tier1_sensors = list(motion_sensors) + list(mmwave_sensors) + list(occupancy_sensors)

        # Lux is Tier 1: needed for lux_dark/lux_bright automation triggers (v3.10.0)
        if lux := self._get_config(CONF_ILLUMINANCE_SENSOR):
            tier1_sensors.append(lux)

        # --- Tier 2 (poll-only): read by _async_update_data on 30s interval ---
        # Temperature, humidity, and power sensors do NOT need event listeners.
        # They are read via hass.states.get() on every refresh cycle.
        tier2_count = 0
        if self._get_config(CONF_TEMPERATURE_SENSOR):
            tier2_count += 1
        if self._get_config(CONF_HUMIDITY_SENSOR):
            tier2_count += 1
        tier2_count += len(self._get_config(CONF_POWER_SENSORS, []) or [])

        _LOGGER.debug(
            "Room %s: Tier 1 (immediate) sensors: %d %s, Tier 2 (poll-only): %d",
            room_name, len(tier1_sensors), tier1_sensors, tier2_count,
        )

        # Set up event listener for Tier 1 sensors only.
        #
        # Occupancy substrate unification cycle (D3): the room tier's
        # Tier-1 listener is moved from the prior
        # `async_track_state_change_event(tier1_sensors, ...)` over to a
        # subscription on `SIGNAL_SUBSTRATE_KIND_CHANGED` for the
        # configured room. The substrate (owned by PresenceCoordinator)
        # is now the single canonical state-change subscription set for
        # CONF-listed motion/mmwave/occupancy entities across both
        # tiers — so the room tier listens to per-kind edges from the
        # substrate instead of subscribing directly. Substrate sits
        # BENEATH both tiers; this is NOT a deprecation of the room
        # tier, and the room tier's smoothing/timeout/failsafe/camera/
        # BLE-override behavior in `_async_update_data` is UNCHANGED.
        #
        # Lux remains a direct state-change subscription — it is Tier-1
        # for room-tier latency budgeting but is NOT a presence sensor,
        # so it is not part of the substrate's CONF-list-driven
        # discovery surface.
        if tier1_sensors:
            # Pre-build set for O(1) lookup in hot callback path
            occupancy_sensor_set = set(motion_sensors + mmwave_sensors + occupancy_sensors)

            # ---- D3 inline-rate-limited refresh trigger ----
            # The body below preserves the prior `_tier1_state_changed`
            # semantics EXACTLY — 2s rate limiter + trailing-edge
            # refresh + immediate `async_refresh()` on the leading edge
            # (preserves the B-HIGH-1 / Review B, 2026-06-03 decision
            # NOT to route through `async_request_refresh()` because URA
            # does not override the DataUpdateCoordinator default 10s
            # debouncer at `super().__init__` (coordinator.py:285-290),
            # which would stack a 10s quiet period on top of the 2s
            # rate limiter and lift Tier-1 occupant-confirmation latency
            # to ~10s in burst conditions).
            def _trigger_rate_limited_refresh() -> None:
                now_mono = time.monotonic()
                if now_mono - self._last_event_refresh < 2.0:
                    if self._trailing_refresh_unsub is None:
                        remaining = 2.0 - (now_mono - self._last_event_refresh) + 0.05
                        self._trailing_refresh_unsub = async_call_later(
                            self.hass, remaining, self._trailing_refresh_callback,
                        )
                    return
                if self._trailing_refresh_unsub is not None:
                    self._trailing_refresh_unsub()
                    self._trailing_refresh_unsub = None
                self._last_event_refresh = now_mono
                self.entry.async_create_background_task(
                    self.hass, self.async_refresh(),
                    "ura_tier1_refresh",
                )

            # ---- Substrate signal handler (D3 actuation-critical path) ----
            @callback
            def _on_substrate_kind_changed(
                payload_room_name: str,
                payload_kind: str,
                payload_new_state: bool,
            ) -> None:
                """Handle SIGNAL_SUBSTRATE_KIND_CHANGED for this room.

                Substrate dispatches per-kind edges for EVERY configured
                room; filter on `payload_room_name` to react only to our
                own room. The rate limiter + immediate-refresh decision
                inside `_trigger_rate_limited_refresh()` preserves the
                pre-cycle Tier-1 reaction latency at parity.
                """
                if payload_room_name != room_name:
                    return
                _LOGGER.info(
                    "Room %s: substrate kind=%s edge -> %s",
                    room_name, payload_kind, payload_new_state,
                )
                _trigger_rate_limited_refresh()

            # B-C1 fix-up: append to dedicated substrate-listener list,
            # NOT _unsub_signal_listeners. _update_signal_subscriptions()
            # (called immediately below at first_refresh AND on every
            # options-flow save) clears _unsub_signal_listeners wholesale
            # and only rebuilds the M2 trigger/AI-rule signal set — so
            # routing the substrate sub through it would silently kill
            # the room tier's substrate edges every options save.
            self._unsub_substrate_listeners.append(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_SUBSTRATE_KIND_CHANGED,
                    _on_substrate_kind_changed,
                )
            )

            # ---- Lux direct state-change listener (preserved) ----
            # Lux is Tier-1 for latency but lives outside the substrate's
            # CONF presence-sensor lists, so it keeps its own state-change
            # subscription. Reuses the same rate-limited refresh trigger.
            lux_entity = self._get_config(CONF_ILLUMINANCE_SENSOR)
            if lux_entity:
                @callback
                def _on_lux_state_changed(event):
                    """State-change callback for the Tier-1 lux sensor."""
                    new_state = event.data.get("new_state")
                    old_state = event.data.get("old_state")
                    new_val = new_state.state if new_state else "None"
                    old_val = old_state.state if old_state else "None"
                    _LOGGER.debug(
                        "Room %s: lux %s changed %s -> %s",
                        room_name, lux_entity, old_val, new_val,
                    )
                    _trigger_rate_limited_refresh()

                self._unsub_state_listeners.append(
                    async_track_state_change_event(
                        self.hass, [lux_entity], _on_lux_state_changed,
                    )
                )

            # B-H2 fix-up: the count of substrate-routed entities is
            # motion + mmwave + occupancy only. Lux is Tier-1 for
            # latency budgeting but lives outside the substrate's
            # CONF surface — it keeps its own direct state-change
            # listener (registered below). Report lux separately so
            # post-deploy audits comparing the substrate's
            # "subscribed to N Tier-1 entities" log against this line
            # match exactly.
            substrate_routed_count = (
                len(motion_sensors)
                + len(mmwave_sensors)
                + len(occupancy_sensors)
            )
            lux_suffix = (
                " + 1 lux (direct state-change)"
                if self._get_config(CONF_ILLUMINANCE_SENSOR)
                else ""
            )
            _LOGGER.info(
                "Room %s: Event-driven mode — %d substrate-driven Tier-1 "
                "sensors (%d motion / %d mmwave / %d occupancy)%s, "
                "%d Tier 2 sensors (30s poll)",
                room_name, substrate_routed_count,
                len(motion_sensors), len(mmwave_sensors),
                len(occupancy_sensors), lux_suffix, tier2_count,
            )
            # Silence unused-name warnings for the occupancy_sensor_set
            # (kept for diagnostic parity with the pre-substrate body if
            # a future hotfix needs it).
            _ = occupancy_sensor_set
        else:
            _LOGGER.info(
                "Room %s: No motion/occupancy sensors — using 30s polling. "
                "Configure sensors for faster response.",
                room_name,
            )

        # v3.12.0 M2: Subscribe to coordinator signals for trigger/AI-rule detection.
        self._update_signal_subscriptions()

        # v3.12.0: Re-evaluate signal subscriptions when entry options change
        # (e.g., user adds chains/AI rules via config flow after startup).
        # v4.2.24 hotfix: HA 2024+ requires update_listeners to be `async def`
        # so HA can await the result. Previously decorated `@callback` (sync,
        # returns None), which caused HA's _async_save_and_notify to call
        # `async_create_task(None)` -> `TypeError: a coroutine was expected,
        # got None`. Effect: every options-flow save raised an HTTP 500 to
        # the frontend ("Unknown error occurred"), aborted the listener
        # chain (so the reload listener didn't fire), and silently dropped
        # the disk-write schedule. Async wrapper is correct shape; the
        # body is still synchronous.
        async def _on_entry_update(hass, entry) -> None:
            self._update_signal_subscriptions()

        self.entry.async_on_unload(
            self.entry.add_update_listener(_on_entry_update)
        )

    @callback
    def _update_signal_subscriptions(self) -> None:
        """Subscribe to coordinator signals based on current chains/AI rules config.

        Can be called multiple times — clears old subscriptions first.
        """
        # Clear existing signal subscriptions
        for unsub in self._unsub_signal_listeners:
            unsub()
        self._unsub_signal_listeners.clear()

        chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
        rules = self._get_config(CONF_AI_RULES, [])
        rule_triggers = {r.get("trigger_type") for r in rules if r.get("enabled", True)}
        room_name = self.entry.data.get(CONF_ROOM_NAME, "unknown")

        _signal_map = {
            SIGNAL_HOUSE_STATE_CHANGED: (
                self._on_house_state_changed,
                any(k.startswith(TRIGGER_HOUSE_STATE_PREFIX) for k in chains)
                or any(t.startswith(TRIGGER_HOUSE_STATE_PREFIX) for t in rule_triggers),
            ),
            SIGNAL_ENERGY_CONSTRAINT: (
                self._on_energy_constraint,
                TRIGGER_ENERGY_CONSTRAINT in chains or TRIGGER_ENERGY_CONSTRAINT in rule_triggers,
            ),
            SIGNAL_SAFETY_HAZARD: (
                self._on_safety_hazard,
                TRIGGER_SAFETY_HAZARD in chains or TRIGGER_SAFETY_HAZARD in rule_triggers,
            ),
            SIGNAL_SECURITY_EVENT: (
                self._on_security_event,
                TRIGGER_SECURITY_EVENT in chains or TRIGGER_SECURITY_EVENT in rule_triggers,
            ),
        }
        subscribed = 0
        for signal, (handler, needed) in _signal_map.items():
            if needed:
                self._unsub_signal_listeners.append(
                    async_dispatcher_connect(self.hass, signal, handler)
                )
                subscribed += 1
        if subscribed:
            _LOGGER.debug(
                "Room %s: Subscribed to %d coordinator signals for M2 triggers",
                room_name, subscribed,
            )

    @callback
    def _debounce_refresh_callback(self, _now=None) -> None:
        """Re-evaluate occupancy after debounce period expires."""
        self._debounce_refresh_unsub = None
        # setup/unload symmetry: tracked via the room entry.
        self.entry.async_create_background_task(
            self.hass, self.async_refresh(),
            "ura_debounce_refresh",
        )

    @callback
    def _trailing_refresh_callback(self, _now=None) -> None:
        """Trailing-edge refresh after rate limiter window expires.

        v4.0.7: Ensures the last state change in a burst is always processed
        within 2s. Without this, a motion "off" event rate-limited at t=1.5s
        wouldn't be seen until the 30s poll — delaying occupancy timeout start.
        """
        self._trailing_refresh_unsub = None
        self._last_event_refresh = time.monotonic()
        # setup/unload symmetry: tracked via the room entry.
        self.entry.async_create_background_task(
            self.hass, self.async_refresh(),
            "ura_trailing_refresh",
        )

    # NOTE: Listener cleanup is in __init__.py async_unload_entry(), NOT here.
    # async_will_remove_from_hass is an Entity lifecycle method — never called
    # on DataUpdateCoordinator subclasses. Removed in v3.12.0.

    def _is_sensor_on(self, entity_id: str) -> bool:
        """Check if a binary sensor is on."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        if state.state in ("unavailable", "unknown"):
            _LOGGER.debug(
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
    
    def _get_room_switch_state(self, suffix: str) -> bool | None:
        """Check a room-level switch state. Returns None if switch not found."""
        room_slug = self.entry.data.get('room_name', 'unknown').lower().replace(' ', '_')
        entity_id = f"switch.{room_slug}_{suffix}"
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return state.state == "on"

    def _is_automation_enabled(self) -> bool:
        """Check if automation switch is enabled."""
        # v3.20.0: ManualModeSwitch ON disables ALL automation
        manual = self._get_room_switch_state("manual_mode")
        if manual is True:
            return False
        # Original automation switch check
        auto = self._get_room_switch_state("automation")
        if auto is None:
            return True  # Default to enabled if switch not found
        return auto

    def _is_climate_automation_enabled(self) -> bool:
        """Check if climate automation switch is enabled."""
        state = self._get_room_switch_state("climate_automation")
        if state is None:
            return True  # Default to enabled if switch not found
        return state

    def _is_cover_automation_enabled(self) -> bool:
        """Check if cover automation switch is enabled."""
        state = self._get_room_switch_state("cover_automation")
        if state is None:
            return True  # Default to enabled if switch not found
        return state

    def _is_ai_automation_enabled(self) -> bool:
        """Check if AI automation switch is enabled for this room.

        v3.21.0 D7: Per-room toggle for AI rules and automation chaining.
        Review fix R2-F11: Also respect ManualMode — if manual mode is ON,
        AI automation is disabled regardless of the AI toggle.
        """
        # ManualMode overrides everything
        manual = self._get_room_switch_state("manual_mode")
        if manual is True:
            return False
        state = self._get_room_switch_state("ai_automation")
        if state is None:
            return True  # Default to enabled if switch not found
        return state

    def _is_override_occupied(self) -> bool:
        """Check if OverrideOccupied switch forces room occupied."""
        return self._get_room_switch_state("override_occupied") is True

    def _is_override_vacant(self) -> bool:
        """Check if OverrideVacant switch forces room vacant."""
        return self._get_room_switch_state("override_vacant") is True
    
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
                        _LOGGER.debug(
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
                remaining = max(0.0, self._occupancy_timeout - elapsed)
                data[STATE_TIMEOUT_REMAINING] = int(remaining)
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
        #
        # v4.5.15: failsafe duration is now room-type-keyed. Closet +
        # bathroom default to 60 min (lazy auto-off — typical use never
        # exceeds an hour; catches stuck-sensor / fan-as-motion / "light
        # left on" patterns). All other room types use 4 hr default.
        #
        # v4.5.16: failsafe now also requires a Tier 1 sensor (PIR or mmWave)
        # to be stale before firing. Previously a sleeping person whose
        # mmWave/sensor_presence stayed on through the night still hit the
        # 4-hour ceiling and got force-marked vacant for 30-60 sec before
        # the next cycle re-occupied them. That fired nightly per bedroom
        # and disrupted any automation gated on vacancy transitions.
        # `_last_motion_time` is updated by motion + mmWave + occupancy
        # sensors every cycle (coordinator.py:1353), so it's the universal
        # Tier 1 freshness timestamp. If it's fresh, occupancy is real and
        # we skip the failsafe. If it's stale, we're in the original
        # stuck-sensor / forgotten-light territory and the failsafe fires.
        if (data.get(STATE_OCCUPIED)
                and self._became_occupied_time):
            duration = (now - self._became_occupied_time).total_seconds()
            failsafe_seconds = self._get_failsafe_duration_seconds()
            if duration > failsafe_seconds:
                signal_stale = True
                signal_age = None
                if self._last_motion_time:
                    signal_age = (
                        now - self._last_motion_time
                    ).total_seconds()
                    # Stale-threshold = 2x the room's motion timeout. Bedroom
                    # 30 min, closet 4 min, etc. Wide enough for natural
                    # idle pauses; narrow enough that a truly stuck sensor
                    # still trips the failsafe.
                    #
                    # Clock-skew defense: a negative signal_age means
                    # _last_motion_time is in the future (NTP jump, manual
                    # clock change). Fall through to signal_stale=True so
                    # the failsafe still fires — better to recover from a
                    # spurious vacancy than to silently silence the
                    # failsafe forever on a pathological timestamp.
                    if 0 <= signal_age < 2 * self._occupancy_timeout:
                        signal_stale = False
                if signal_stale:
                    _LOGGER.warning(
                        "Room %s (%s): Forcing vacancy after %.1f min "
                        "(failsafe — limit %.0f min, signal stale)",
                        room_name, self._room_type,
                        duration / 60, failsafe_seconds / 60,
                    )
                    data[STATE_OCCUPIED] = False
                    data[STATE_OCCUPANCY_SOURCE] = "failsafe"
                    data[STATE_TIMEOUT_REMAINING] = 0
                    self._last_motion_time = None
                    self._failsafe_fired = True
                else:
                    # Skip failsafe — a Tier 1 sensor is still active.
                    # Debug-level because this is the common case for
                    # legitimately-occupied bedrooms during sleep.
                    _LOGGER.debug(
                        "Room %s (%s): skipping failsafe at %.1f min — "
                        "signal fresh (%.0fs ago, threshold %.0fs)",
                        room_name, self._room_type, duration / 60,
                        signal_age, 2 * self._occupancy_timeout,
                    )

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
        # v3.2.3.2: Use _get_config for power/energy sensors.
        # Power sums now route through ``power_state_to_w`` so a
        # kW-reporting source (e.g. Envoy current_power_consumption)
        # is normalized to Watts before summing — same Bug Class #30
        # sibling fix being applied to WholeHousePowerSensor. Room
        # power sensors are mostly Shelly/SPAN native Watts so the
        # change is a no-op in the common case; the helper protects
        # any future kW-reporting source. Downstream consumers of
        # STATE_POWER_CURRENT (energy_forecast RoomPowerProfile EMA,
        # EnergyWasteIdle >5W threshold, zone power total, cost/hour)
        # self-correct via EMA on the new scale; no migration needed.
        power_sensors = self._get_config(CONF_POWER_SENSORS, [])
        total_power = 0.0
        for sensor in power_sensors:
            if not sensor:
                continue
            try:
                state = self.hass.states.get(sensor)
                watts = power_state_to_w(state)
            except Exception:
                watts = None
            if watts is not None:
                total_power += watts
        data[STATE_POWER_CURRENT] = total_power
        
        # Energy accumulation — supports multiple energy sensors (v4.1.0)
        # Try plural key first, fall back to singular for backward compatibility
        energy_sensors = self._get_config(CONF_ENERGY_SENSORS, [])
        if not energy_sensors:
            singular = self._get_config(CONF_ENERGY_SENSOR)
            if singular:
                energy_sensors = [singular]

        if energy_sensors:
            # Direct energy sensors (usually TOTAL_INCREASING from smart plugs)
            # v4.2.28: Persistence + unavailable-at-midnight handling + sanity
            # guard. Previously: in-memory baselines lost on restart, and a
            # sensor that was unavailable at midnight kept its old baseline
            # forever (until a coordinator restart), producing
            # multi-day-cumulative values like "5306 kWh today" with
            # power=0W now.
            total_delta = 0.0
            midnight_reset = now.date() > self._last_energy_reset.date()

            # Lazy-load baselines from DB on first refresh.
            # v4.2.28: set flag BEFORE await to prevent concurrent re-entry
            # double-loading (Tier 1 review HIGH #1 — race-on-first-refresh).
            if not self._energy_baselines_loaded:
                self._energy_baselines_loaded = True  # Set first; await below cannot re-enter
                db = self.hass.data.get(DOMAIN, {}).get("database")
                if db is not None:
                    persisted = await db.load_room_energy_baselines(self.entry.entry_id)
                    for sid, info in persisted.items():
                        self._energy_baselines_today[sid] = info["baseline_value"]
                        if info.get("needs_reset"):
                            self._energy_baselines_needs_reset.add(sid)

                    # v4.2.28: Tier 2 review CRITICAL — if persisted baselines
                    # are from BEFORE today's midnight (URA was offline across
                    # the midnight rollover), force a midnight_reset on this
                    # update. Otherwise on a 6am restart we'd compute delta
                    # against yesterday's-midnight baseline = 24h+ of usage
                    # incorrectly attributed to "today".
                    if persisted:
                        today_midnight_utc = dt_util.as_utc(
                            dt_util.now().replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                        )
                        oldest_set_at = None
                        for info in persisted.values():
                            set_at_str = info.get("baseline_set_at")
                            if not set_at_str:
                                continue
                            try:
                                set_at_dt = dt_util.parse_datetime(set_at_str)
                            except Exception:
                                continue
                            if set_at_dt is None:
                                continue
                            set_at_utc = dt_util.as_utc(set_at_dt)
                            if oldest_set_at is None or set_at_utc < oldest_set_at:
                                oldest_set_at = set_at_utc

                        if (
                            oldest_set_at is not None
                            and oldest_set_at < today_midnight_utc
                        ):
                            # Backdate _last_energy_reset so the upcoming
                            # midnight_reset check fires; the energy loop will
                            # then reset all baselines to current_value, lose
                            # the part-of-today-before-restart energy, and
                            # start counting STATE_ENERGY_TODAY freshly. Better
                            # than reporting 24h+ accumulation.
                            self._last_energy_reset = (
                                dt_util.now() - timedelta(days=1)
                            ).replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                            _LOGGER.info(
                                "Room %s: persisted baselines are pre-midnight "
                                "(oldest=%s); forcing baseline reset on this "
                                "update — STATE_ENERGY_TODAY will start from now",
                                self._get_config(CONF_ROOM_NAME, "?"),
                                oldest_set_at.isoformat(),
                            )

                        _LOGGER.info(
                            "Room %s: loaded %d persisted energy baseline(s) from DB",
                            self._get_config(CONF_ROOM_NAME, "?"),
                            len(persisted),
                        )

            # D1 schema-version migration (Bug Class #30 fix on energy class).
            # Once per process boot, check the version sentinel and reset all
            # baselines if the persisted version pre-dates the new
            # unit-normalization read path. Without this, a Wh-stored baseline
            # minus a kWh-normalized current_value would go hugely negative
            # and silently be max(0,·)-clipped to 0 forever.
            #
            # Fix-up pass A-M1: atomic check-and-set via
            # ``migrate_energy_baselines_if_needed`` (single queued write
            # transaction) so concurrent room coordinators don't race —
            # the first one to hit the DAO performs the reset + sentinel
            # write; subsequent callers see the new sentinel and no-op.
            # Fix-up pass A-M2: transient read errors return ``None`` from
            # the underlying check; the DAO treats that as "skip migration
            # this boot" instead of spuriously firing a full reset.
            if not self._energy_baselines_schema_checked:
                self._energy_baselines_schema_checked = True
                _db_for_migration = self.hass.data.get(DOMAIN, {}).get("database")
                if _db_for_migration is not None:
                    try:
                        from .const import ENERGY_BASELINE_SCHEMA_VERSION
                        ran, deleted = await (
                            _db_for_migration.migrate_energy_baselines_if_needed(
                                ENERGY_BASELINE_SCHEMA_VERSION
                            )
                        )
                        if ran:
                            # Also clear in-memory baselines loaded above so the
                            # next read establishes a fresh baseline from the
                            # normalized current_value (else we'd carry the
                            # stale-unit value through the cycle).
                            self._energy_baselines_today.clear()
                            self._energy_baselines_needs_reset.clear()
                            _LOGGER.info(
                                "Room %s: energy baseline schema migrated "
                                "→ %d; %d legacy row(s) reset to "
                                "force kWh-normalized re-establishment",
                                self._get_config(CONF_ROOM_NAME, "?"),
                                ENERGY_BASELINE_SCHEMA_VERSION,
                                deleted,
                            )
                    except Exception as err:
                        _LOGGER.warning(
                            "Energy baseline schema migration check failed: %s",
                            err,
                        )

            db = self.hass.data.get(DOMAIN, {}).get("database")  # may be None during early startup

            # Sanity cap: if a single update reports a delta larger than this,
            # the baseline is almost certainly stale (sensor entity_id reuse,
            # SPAN circuit relabel, or missed midnight). Reset and log instead
            # of polluting STATE_ENERGY_TODAY with multi-day accumulation.
            # v4.2.28: 500 kWh accommodates legit multi-day outages on EV/solar
            # circuits (40-50 kWh/day × 5–10 days). Tier 1 review HIGH #3.
            SANE_MAX_DELTA_KWH = 500.0

            # D4: per-cycle dead-sensor accounting. If all configured energy
            # sensors are unavailable this cycle we set STATE_ENERGY_TODAY=None
            # (not 0.0) so downstream `if energy:` consumers cleanly skip
            # the room instead of treating dead-as-zero.
            dead_count = 0

            for sensor_id in energy_sensors:
                state = self.hass.states.get(sensor_id)
                sensor_available = (
                    state is not None
                    and state.state not in ("unknown", "unavailable")
                )

                if not sensor_available:
                    dead_count += 1
                    # If midnight rolled over while this sensor was offline,
                    # mark the baseline as stale. Next available read will
                    # set baseline = current_value (cleanly capturing the
                    # post-midnight start) and clear the flag.
                    if midnight_reset and sensor_id in self._energy_baselines_today:
                        self._energy_baselines_needs_reset.add(sensor_id)
                        if db is not None:
                            try:
                                await db.save_room_energy_baseline(
                                    self.entry.entry_id, sensor_id,
                                    baseline_value=self._energy_baselines_today[sensor_id],
                                    set_at=dt_util.utcnow().isoformat(),  # v4.2.28: UTC for cleanup-cutoff sortability
                                    needs_reset=True,
                                )
                            except Exception as err:
                                _LOGGER.warning(
                                    "Save needs_reset baseline failed for %s: %s",
                                    sensor_id, err,
                                )
                    continue  # No delta contribution while unavailable

                # D1 (Bug Class #30): normalize energy reading to kWh based
                # on the source entity's unit_of_measurement. A Wh-reporting
                # sensor pre-fix inflated STATE_ENERGY_TODAY 1000× and poisoned
                # cost/coverage cascades. Returns None on unparseable / dead /
                # unrecognized-uom; treat as not-contributing for this cycle.
                current_value = energy_state_to_kwh(state)
                if current_value is None:
                    continue

                first_seen = sensor_id not in self._energy_baselines_today
                stale = sensor_id in self._energy_baselines_needs_reset

                if midnight_reset or first_seen or stale:
                    old_baseline = self._energy_baselines_today.get(sensor_id)
                    self._energy_baselines_today[sensor_id] = current_value
                    self._energy_baselines_needs_reset.discard(sensor_id)
                    if stale and old_baseline is not None:
                        _LOGGER.info(
                            "Room %s: sensor %s baseline cleared (was stale=%.2f, "
                            "now=%.2f) — sensor became available after midnight",
                            self._get_config(CONF_ROOM_NAME, "?"),
                            sensor_id, old_baseline, current_value,
                        )
                    if db is not None:
                        try:
                            await db.save_room_energy_baseline(
                                self.entry.entry_id, sensor_id,
                                baseline_value=current_value,
                                set_at=dt_util.utcnow().isoformat(),  # v4.2.28: UTC for cleanup-cutoff sortability
                                needs_reset=False,
                            )
                        except Exception as err:
                            _LOGGER.warning(
                                "Save baseline failed for %s: %s", sensor_id, err,
                            )

                baseline = self._energy_baselines_today[sensor_id]
                raw_delta = current_value - baseline

                # Sanity guard: implausibly large deltas indicate baseline drift.
                # Reset baseline to current value, contribute 0 this cycle, log.
                # D1: also catches NEGATIVE drift (raw_delta < -SANE_MAX_DELTA_KWH).
                # A negative drift here means baseline-unit and current-unit
                # disagree (Bug Class #30) — e.g. legacy Wh baseline minus a
                # newly-normalized kWh current would yield a huge negative.
                # Without this branch the max(0, raw_delta) clamp at end of
                # loop silently zeros the room until midnight.
                if abs(raw_delta) > SANE_MAX_DELTA_KWH:
                    _LOGGER.warning(
                        "Room %s: sensor %s implausible delta %.1f kWh (baseline=%.1f, "
                        "current=%.1f) — resetting baseline. Likely cause: stale baseline "
                        "from before integration restart, sensor entity_id reuse, or "
                        "unit-of-measurement mismatch between baseline and current read.",
                        self._get_config(CONF_ROOM_NAME, "?"),
                        sensor_id, raw_delta, baseline, current_value,
                    )
                    self._energy_baselines_today[sensor_id] = current_value
                    if db is not None:
                        try:
                            await db.save_room_energy_baseline(
                                self.entry.entry_id, sensor_id,
                                baseline_value=current_value,
                                set_at=dt_util.utcnow().isoformat(),  # v4.2.28: UTC for cleanup-cutoff sortability
                                needs_reset=False,
                            )
                        except Exception as err:
                            _LOGGER.warning(
                                "Save sanity-reset baseline failed for %s: %s",
                                sensor_id, err,
                            )
                    continue  # No delta contribution this cycle

                # Fix-up pass A-M3: a small negative delta in (-SANE, 0)
                # is a genuine counter reset (e.g. SPAN circuit cleared
                # mid-day → reading 300 → 0). The original ``max(0,
                # raw_delta)`` clamp left the stale baseline in place so
                # the room would contribute 0 until midnight even after
                # the counter started accumulating again. Re-anchor the
                # baseline to the current value, contribute 0 this cycle,
                # debug-log. (The large-magnitude case is handled above.)
                if raw_delta < 0:
                    _LOGGER.debug(
                        "Room %s: sensor %s small negative delta %.3f kWh "
                        "(baseline=%.3f, current=%.3f) — re-anchoring (likely "
                        "counter reset).",
                        self._get_config(CONF_ROOM_NAME, "?"),
                        sensor_id, raw_delta, baseline, current_value,
                    )
                    self._energy_baselines_today[sensor_id] = current_value
                    if db is not None:
                        try:
                            await db.save_room_energy_baseline(
                                self.entry.entry_id, sensor_id,
                                baseline_value=current_value,
                                set_at=dt_util.utcnow().isoformat(),
                                needs_reset=False,
                            )
                        except Exception as err:
                            _LOGGER.warning(
                                "Save counter-reset baseline failed for %s: %s",
                                sensor_id, err,
                            )
                    continue

                total_delta += raw_delta

            if midnight_reset:
                self._last_energy_reset = now

            # D4: dead-energy-sensor observability. If EVERY configured sensor
            # was unavailable this cycle, return None so downstream truthiness
            # checks skip the room. Log WARNING rate-limited at most once
            # per hour per room (Bug Class #26 spirit). Surface state for the
            # `energy_sensors_dead` attribute on EnergyTodaySensor.
            all_dead = dead_count == len(energy_sensors) and len(energy_sensors) > 0
            self._energy_sensors_dead = all_dead
            if all_dead:
                _now_mono = time.monotonic()
                if (
                    self._energy_sensors_dead_last_warn is None
                    or (_now_mono - self._energy_sensors_dead_last_warn) >= 3600.0
                ):
                    self._energy_sensors_dead_last_warn = _now_mono
                    _LOGGER.warning(
                        "Room %s: all %d configured energy sensor(s) unavailable "
                        "this cycle — STATE_ENERGY_TODAY held as None. "
                        "(Likely SPAN circuit rename or sensor entity_id reuse.) "
                        "Sensors: %s",
                        self._get_config(CONF_ROOM_NAME, "?"),
                        len(energy_sensors),
                        list(energy_sensors),
                    )
                data[STATE_ENERGY_TODAY] = None
            else:
                data[STATE_ENERGY_TODAY] = total_delta
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

        # v3.20.0: Override switches — force occupancy state regardless of sensors
        # Review fix: also update _last_occupied_state so transitions are
        # detected correctly when override is toggled off
        if self._is_override_occupied():
            data[STATE_OCCUPIED] = True
            data[STATE_OCCUPANCY_SOURCE] = "override"
            self._last_occupied_state = True
            if not self._became_occupied_time:
                self._became_occupied_time = now
        elif self._is_override_vacant():
            data[STATE_OCCUPIED] = False
            data[STATE_OCCUPANCY_SOURCE] = "override"
            self._last_occupied_state = False
            self._became_occupied_time = None

        # === v3.22.12: Skip automation on first refresh ===
        # On reload/restart, the first refresh sees sensors and may detect
        # occupancy. Without this guard, occupied != _last_occupied_state (False)
        # triggers a full entry automation (lights on, fans on, etc.) even
        # though the room was already in that state before the reload.
        # We sync _last_occupied_state from sensor truth and skip automation.
        if self._skip_first_automation:
            self._skip_first_automation = False
            self._last_occupied_state = data[STATE_OCCUPIED]
            self._last_occupancy_source = data.get(STATE_OCCUPANCY_SOURCE, "none")
            if data[STATE_OCCUPIED] and not self._became_occupied_time:
                self._became_occupied_time = now
            elif not data[STATE_OCCUPIED]:
                self._became_occupied_time = None
            _LOGGER.info(
                "Room %s: First refresh — synced occupancy state to %s "
                "(skipped automation to prevent false trigger on restart)",
                room_name,
                data[STATE_OCCUPIED],
            )
            # Skip was_occupied-based DB logging too — no real transition happened
            was_occupied = data[STATE_OCCUPIED]

        # === Automation Logic ===
        elif self._is_automation_enabled():
            # Handle occupancy changes
            if data[STATE_OCCUPIED] != self._last_occupied_state:
                self._last_occupied_state = data[STATE_OCCUPIED]
                self._last_occupancy_source = data.get(STATE_OCCUPANCY_SOURCE, "none")
                try:
                    await self.automation.handle_occupancy_change(
                        data[STATE_OCCUPIED],
                        data
                    )
                except Exception as e:
                    _LOGGER.error("Error in occupancy automation: %s", e)

                # Activity log: occupancy entry/exit
                activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                if activity_logger:
                    occ_source = data.get(STATE_OCCUPANCY_SOURCE, "unknown")
                    occ_action = "occupancy_entry" if data[STATE_OCCUPIED] else "occupancy_exit"
                    occ_desc = (
                        f"Room occupied (source: {occ_source})"
                        if data[STATE_OCCUPIED]
                        else "Room vacated"
                    )
                    # setup/unload symmetry: tracked via the room entry.
                    self.entry.async_create_background_task(
                        self.hass,
                        activity_logger.log(
                            coordinator="room",
                            action=occ_action,
                            description=occ_desc,
                            room=room_name,
                            details={"source": occ_source},
                        ),
                        # B-MED-3: bound task name to entry_id slice
                        # (was f"ura_activity_log_{occ_action}_{room_name}"
                        # — unbounded room_name values were polluting HA's
                        # _tasks debug surface).
                        f"ura_activity_log_occ_{self.entry.entry_id[:8]}",
                    )

                # RESILIENCE-003: Verify vacancy exit — non-blocking delayed task
                if was_occupied and not data[STATE_OCCUPIED]:
                    exit_action = self._get_config(CONF_EXIT_LIGHT_ACTION, LIGHT_ACTION_TURN_OFF)
                    if exit_action == LIGHT_ACTION_TURN_OFF:
                        # setup/unload symmetry: tracked via the room
                        # entry so the delayed verify is cancelled
                        # on entry unload/reload.
                        self.entry.async_create_background_task(
                            self.hass,
                            self._delayed_exit_verify(room_name, data),
                            # B-MED-3: bound task name to entry_id slice.
                            f"ura_delayed_exit_verify_{self.entry.entry_id[:8]}",
                        )

            # v3.16: Re-trigger entry when occupancy source transitions from
            # BLE-only to a real sensor (motion/mmwave/occupancy). BLE may have
            # been holding the room "occupied" while lights were off or timed out.
            # Physical entry should ensure lights turn on.
            # 60s cooldown prevents rapid re-entry thrashing from flaky sensors.
            elif data[STATE_OCCUPIED] and self._last_occupied_state:
                current_source = data.get(STATE_OCCUPANCY_SOURCE, "none")
                prev_source = self._last_occupancy_source
                if prev_source == "ble" and current_source in (
                    "motion", "mmwave", "occupancy_sensor",
                ):
                    cooldown_ok = (
                        self._last_source_reentry_time is None
                        or (now - self._last_source_reentry_time).total_seconds() > 60
                    )
                    if cooldown_ok:
                        self._last_source_reentry_time = now
                        _LOGGER.info(
                            "Room %s: Source transition ble→%s — re-triggering entry",
                            room_name, current_source,
                        )
                        try:
                            await self.automation.handle_occupancy_change(True, data)
                        except Exception as e:
                            _LOGGER.error("Error in source-transition entry: %s", e)
                self._last_occupancy_source = current_source
            
            # Periodic automation tasks (refresh config for options flow changes)
            self.automation._refresh_config()
            try:
                # Temperature-based fan control
                # v3.20.0: Gated by ClimateAutomationSwitch
                if self._is_climate_automation_enabled():
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
                # v3.20.0: Gated by CoverAutomationSwitch
                # v4.2.22: Cover automation now also runs in the `else` branch
                # below when master automation is OFF — Option A independence.
                if self._is_cover_automation_enabled():
                    await self.automation.check_timed_cover_open()
                    await self.automation.check_timed_cover_close()

            except Exception as e:
                _LOGGER.error("Error in periodic automation: %s", e)

            # === v3.10.0: Trigger detection + automation chaining ===
            triggers_fired: list[str] = []

            # Enter/exit (from occupancy transition already detected above)
            if data[STATE_OCCUPIED] != was_occupied:
                if data[STATE_OCCUPIED]:
                    triggers_fired.append(TRIGGER_ENTER)
                else:
                    triggers_fired.append(TRIGGER_EXIT)

            # Lux threshold crossing (only if a lux sensor is configured)
            if self._get_config(CONF_ILLUMINANCE_SENSOR):
                lux_trigger = self._detect_lux_trigger(data.get(STATE_ILLUMINANCE))
                if lux_trigger:
                    triggers_fired.append(lux_trigger)

            # Fire chained automations for all triggers, then AI rules
            # v3.21.0 D7: Gated by AI automation per-room toggle
            if triggers_fired and self._is_ai_automation_enabled():
                # v3.12.0 M4: Track trigger execution
                self._last_trigger_event = ", ".join(triggers_fired)
                self._last_trigger_time_str = dt_util.utcnow().isoformat()

                try:
                    await self._fire_chained_automations(triggers_fired)
                except Exception as e:
                    _LOGGER.error("Error firing chained automations: %s", e)
                try:
                    await self._execute_ai_rules(triggers_fired)
                except Exception as e:
                    _LOGGER.error("Error executing AI rules: %s", e)
        else:
            # Even with automation disabled, track state for DB logging
            self._last_occupied_state = data[STATE_OCCUPIED]

            # v4.2.22: Cover automation runs independently of the master
            # automation switch (Option A). Timed open/close are
            # occupancy-independent (sunrise/sunset/time-based), so they
            # should still fire when a user has disabled lights/fans
            # automation but left CoverAutomationSwitch on.
            #
            # Review fix H2: respect _skip_first_automation just like the
            # master `elif` branch does — on first refresh after restart,
            # don't fire blind commands until the next cycle (sensors may
            # not have settled and dedup state is fresh).
            if (
                not self._skip_first_automation
                and self._is_cover_automation_enabled()
            ):
                self.automation._refresh_config()
                try:
                    await self.automation.check_timed_cover_open()
                    await self.automation.check_timed_cover_close()
                except Exception as e:
                    _LOGGER.error(
                        "Error in independent cover automation: %s", e
                    )

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
        
        # === Phase 2+3: Energy & Prediction Queries (cached, 5-min TTL) ===
        # v4.0.10: These DB queries were running every 30s across 31 rooms,
        # causing 3-15s of DB contention per refresh. The data changes slowly
        # (hourly/daily patterns), so a 5-minute cache eliminates ~90% of queries.
        if database:
            cache_age = (
                (now - self._last_prediction_query).total_seconds()
                if self._last_prediction_query else 999
            )
            if cache_age >= 300:
                cache = {}

                # Energy: weekly + monthly
                week_ago = now - timedelta(days=7)
                cache[STATE_ENERGY_WEEKLY] = await database.get_energy_for_period(
                    self.entry.entry_id, week_ago, now,
                )
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                cache[STATE_ENERGY_MONTHLY] = await database.get_energy_for_period(
                    self.entry.entry_id, month_start, now,
                )

                # Predictions
                prediction = await database.get_next_occupancy_prediction(self.entry.entry_id)
                if prediction:
                    cache["_next_time"] = prediction[0]
                    cache["_next_confidence"] = prediction[1]
                else:
                    cache["_next_time"] = None
                    cache["_next_confidence"] = None

                occupancy_pct = await database.get_occupancy_percentage(self.entry.entry_id, days=7)
                if occupancy_pct is not None:
                    cache[STATE_OCCUPANCY_PCT_7D] = round(occupancy_pct, 1)

                peak_hour = await database.get_peak_occupancy_hour(self.entry.entry_id, days=7)
                if peak_hour is not None:
                    import datetime as _dt
                    t = _dt.time(hour=peak_hour)
                    cache[STATE_PEAK_OCCUPANCY_TIME] = t.strftime("%I:00 %p")

                self._cached_predictions = cache
                self._last_prediction_query = now  # Set AFTER cache to ensure retry on failure

            # Apply cached values to data dict
            if STATE_ENERGY_WEEKLY in self._cached_predictions:
                data[STATE_ENERGY_WEEKLY] = self._cached_predictions[STATE_ENERGY_WEEKLY]
            if STATE_ENERGY_MONTHLY in self._cached_predictions:
                data[STATE_ENERGY_MONTHLY] = self._cached_predictions[STATE_ENERGY_MONTHLY]

            # Energy costs (computed fresh from cached energy values)
            # v4.6.8: Use TOU-aware rate via helper (EC first, room override, global, default).
            electricity_rate, _rate_src = _get_effective_rate_kwh(self.hass, room_entry=self.entry)
            if data.get(STATE_ENERGY_WEEKLY) is not None:
                data[STATE_ENERGY_COST_WEEKLY] = round(data[STATE_ENERGY_WEEKLY] * electricity_rate, 2)
            if data.get(STATE_ENERGY_MONTHLY) is not None:
                data[STATE_ENERGY_COST_MONTHLY] = round(data[STATE_ENERGY_MONTHLY] * electricity_rate, 2)
            if data.get(STATE_POWER_CURRENT) is not None:
                power_kw = data[STATE_POWER_CURRENT] / 1000.0
                data[STATE_COST_PER_HOUR] = round(power_kw * electricity_rate, 3)

            # Prediction values — next_occupancy_in recomputed each cycle (countdown)
            next_time = self._cached_predictions.get("_next_time")
            if next_time is not None:
                data[STATE_NEXT_OCCUPANCY_TIME] = next_time
                data[STATE_OCCUPANCY_CONFIDENCE] = self._cached_predictions.get("_next_confidence")
                now_aware = now.replace(tzinfo=next_time.tzinfo) if next_time.tzinfo else now
                minutes_until = int((next_time - now_aware).total_seconds() / 60)
                data[STATE_NEXT_OCCUPANCY_IN] = max(0, minutes_until)
                precool_lead = 15
                preheat_lead = 20
                data[STATE_PRECOOL_START_TIME] = next_time - timedelta(minutes=precool_lead)
                data[STATE_PREHEAT_START_TIME] = next_time - timedelta(minutes=preheat_lead)
                data[STATE_PRECOOL_LEAD_MINUTES] = precool_lead
                data[STATE_PREHEAT_LEAD_MINUTES] = preheat_lead

            if STATE_OCCUPANCY_PCT_7D in self._cached_predictions:
                data[STATE_OCCUPANCY_PCT_7D] = self._cached_predictions[STATE_OCCUPANCY_PCT_7D]
            if STATE_PEAK_OCCUPANCY_TIME in self._cached_predictions:
                data[STATE_PEAK_OCCUPANCY_TIME] = self._cached_predictions[STATE_PEAK_OCCUPANCY_TIME]

        # v3.20.0: Throttled room state DB backup (every 5 minutes)
        if (
            self._last_room_state_save is None
            or (now - self._last_room_state_save).total_seconds() > 300
        ):
            self._last_room_state_save = now
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db:
                room_id = self.entry.entry_id
                state = {
                    "became_occupied_time": (
                        self._became_occupied_time.isoformat()
                        if self._became_occupied_time
                        else None
                    ),
                    "last_occupied_state": self._last_occupied_state,
                    "occupancy_first_detected": (
                        self._occupancy_first_detected.isoformat()
                        if self._occupancy_first_detected
                        else None
                    ),
                    "failsafe_fired": self._failsafe_fired,
                    "last_trigger_source": self._last_trigger_source,
                    "last_lux_zone": self._last_lux_zone,
                    "last_timed_open_date": (
                        self.automation._last_timed_open_date
                        if hasattr(self, "automation") and self.automation
                        else None
                    ),
                    "last_timed_close_date": (
                        self.automation._last_timed_close_date
                        if hasattr(self, "automation") and self.automation
                        else None
                    ),
                }
                # v3.20.0 review fix: await directly instead of fire-and-forget
                # (Bug Class #19 — aiosqlite INSERT is sub-ms, won't block refresh)
                await db.save_room_state(room_id, state)

        self._recent_occupancy_sources.append(
            str(data.get(STATE_OCCUPANCY_SOURCE, "none"))
        )
        return data

    def recent_occupancy_sources(self) -> list[str]:
        """Return the recent-tick occupancy_source ring as a list (newest last)."""
        return list(self._recent_occupancy_sources)

    def apply_fan_recheck_release(self) -> None:
        """Force vacancy from the room-tier fan-recheck mechanism.

        Mirrors the failsafe clear path (coordinator.py:1509-1513): clears
        _last_motion_time + _became_occupied_time so the next tick sees a
        clean unoccupied state. Marks STATE_OCCUPANCY_SOURCE with the
        new "fan_recheck_release" value so HVAC + dashboards can see why.
        Does NOT touch _failsafe_fired — this is a separate mechanism and
        composes with failsafe.
        """
        if self.data is None:
            self.data = {}
        self.data[STATE_OCCUPIED] = False
        self.data[STATE_OCCUPANCY_SOURCE] = OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE
        self.data[STATE_TIMEOUT_REMAINING] = 0
        self._last_motion_time = None
        self._became_occupied_time = None
        self._last_occupied_state = False
        room_name = self.entry.data.get("room_name", "unknown")
        _LOGGER.info(
            "Room %s: fan-recheck released occupancy (mmwave drop confirmed "
            "with fan off)",
            room_name,
        )

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

        # Activity log: light on/off from set_last_action (sync method)
        activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
        if activity_logger:
            room_name = self.entry.data.get("room_name")
            entity_id = entity[0] if isinstance(entity, list) and entity else entity
            # setup/unload symmetry: tracked via the room entry.
            self.entry.async_create_background_task(
                self.hass,
                activity_logger.log(
                    coordinator="room",
                    action=f"light_{action_type}",
                    description=description,
                    room=room_name,
                    entity_id=entity_id,
                ),
                # B-MED-3: bound task name to entry_id slice.
                f"ura_activity_log_light_{self.entry.entry_id[:8]}",
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

"""Automation logic for Universal Room Automation."""
# v4.5.2 D1: PEP 563 deferred annotation evaluation. Production runs on
# Python 3.14+ where `float | None` works natively, but the dev test
# environment (Python 3.9.6) cannot compile such hints at module load,
# blocking test collection. `from __future__ import annotations` defers
# annotation evaluation to string form, restoring 3.9-compat without any
# runtime behavior change. Zero risk on 3.14+.
from __future__ import annotations

#
# Universal Room Automation vv4.5.0.4
# Build: 2026-01-04
# File: automation.py
# v3.3.1.1: Added int() cast to get_auto_off_hour to handle NumberSelector float values
# v3.2.9: Added switch support for temperature-based fans (not just humidity fans)
# v3.2.8.2: Multi-domain auto/manual devices (lights, fans, switches, input_booleans)
# v3.2.8.2: Multi-domain humidity fans (fans, switches)
#

import asyncio
import logging
import math
from collections import deque
from datetime import datetime, time, timedelta
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
    # v3.6.39: New cover open/close config
    CONF_COVER_OPEN_MODE,
    COVER_OPEN_NONE,
    COVER_OPEN_ON_ENTRY,
    COVER_OPEN_AT_TIME,
    COVER_OPEN_ON_ENTRY_AFTER_TIME,
    COVER_OPEN_AT_TIME_OR_ON_ENTRY,
    CONF_COVER_OPEN_TIME_SOURCE,
    TIME_SOURCE_SUNRISE,
    TIME_SOURCE_SPECIFIC_HOUR,
    CONF_COVER_OPEN_HOUR,
    DEFAULT_COVER_OPEN_HOUR,
    CONF_COVER_CLOSE_TIME_SOURCE,
    TIME_SOURCE_SUNSET,
    CONF_COVER_CLOSE_HOUR,
    DEFAULT_COVER_CLOSE_HOUR,
    # Light actions
    LIGHT_ACTION_NONE,
    LIGHT_ACTION_TURN_ON,
    LIGHT_ACTION_TURN_ON_IF_DARK,
    LIGHT_ACTION_TURN_OFF,
    LIGHT_ACTION_LEAVE_ON,
    # Cover actions (legacy)
    COVER_ACTION_NONE,
    COVER_ACTION_ALWAYS,
    COVER_ACTION_SMART,
    COVER_ACTION_AFTER_SUNSET,
    # Timing modes (legacy)
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
    CONF_HUMIDITY_FAN_MAX_RUNTIME,
    CONF_FAN_VACANCY_HOLD,
    DEFAULT_FAN_VACANCY_HOLD,
    DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_HUMIDITY_FAN_TIMEOUT,
    DEFAULT_HUMIDITY_FAN_MAX_RUNTIME,
    DEFAULT_HUMIDITY_FAN_HYSTERESIS,
    # Bathroom-exhaust intelligence cycle
    CONF_HUMIDITY_FAN_CONTROL_ENABLED,
    DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
    CONF_WET_ROOM,
    CONF_HUMIDITY_FAN_SPIKE_ENABLED,
    CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT,
    CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
    CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
    HUMIDITY_FAN_SPIKE_MODE_EMA,
    HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN,
    DEFAULT_HUMIDITY_FAN_SPIKE_DELTA_PCT,
    DEFAULT_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
    DEFAULT_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
    # Sleep protection
    CONF_SLEEP_PROTECTION_ENABLED,
    CONF_SLEEP_START_HOUR,
    CONF_SLEEP_END_HOUR,
    CONF_SLEEP_BYPASS_MOTION,
    CONF_SLEEP_BLOCK_COVERS,
    CONF_FAN_SLEEP_POLICY,
    FAN_SLEEP_OFF,
    FAN_SLEEP_REDUCE,
    DEFAULT_FAN_SLEEP_POLICY,
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
    STATE_MOTION_DETECTED,
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
    # v3.18.1: HVAC deconfliction
    CONF_ROOM_NAME,
    # v4.7.16.2: bedroom gate for sleep-state occupied fan trust
    CONF_ROOM_TYPE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_GENERIC,
    DOMAIN,
)
# B-L1 fix: hoisted to module top (no import cycle — fan_veto imports
# .const + .domain_coordinators.house_state, no back-reference to automation).
from .fan_veto import should_veto_comfort_fan  # noqa: E402

_LOGGER = logging.getLogger(__name__)

# v4.2.22: Cover command verification tuning.
# Hunter Douglas (and other RF-bridged covers) accept hub-level group calls
# even when individual blinds miss the RF burst. We send per-cover with pacing,
# wait for blinds to physically reach state, then re-issue to stragglers only.
COVER_PACE_SECONDS = 0.3       # delay between per-cover commands
COVER_SETTLE_SECONDS = 8.0     # wait after a batch before re-checking state
COVER_MAX_RETRIES = 2          # retry attempts for stragglers (3 total tries)
COVER_RETRY_BACKOFF_BASE = 2.0 # 2s, 4s between retries


class RoomAutomation:
    """Handles automation logic for a room."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any], coordinator) -> None:
        """Initialize room automation."""
        # v3.2.8 STARTUP BANNER
        room_name = config.get('room_name', 'Unknown')
        _LOGGER.info("Automation module initialized for room: %s", room_name)
        
        self.hass = hass
        self.config = config
        self._config_entry = coordinator.entry  # Live reference for fresh reads
        self._sleep_motion_count = 0
        self.coordinator = coordinator
        self._humidity_fan_triggered_time: datetime | None = None
        # v4.6.2.1: Max-runtime gate — set on fan on-transition, cleared on off.
        # Separate from _humidity_fan_triggered_time (min-runtime gate).
        self._humidity_on_since: datetime | None = None
        # v4.6.2.1: Suppression after max-runtime cap fires.
        self._humidity_cap_suppressed: bool = False
        # Bathroom-exhaust intelligence cycle:
        # D2 — EMA-baseline humidity-spike detection.
        self._humidity_ema: float | None = None
        self._humidity_ema_samples: int = 0
        self._humidity_ema_warmup_seen_at: datetime | None = None
        self._humidity_ema_last_sample_ts: datetime | None = None
        # D2 — `window_min` baseline-mode rolling buffer.
        self._humidity_window: deque[tuple[datetime, float]] = deque()
        # D2 — whether the active fan-on cycle was spike-triggered (drives
        # baseline-relative OFF).
        self._humidity_spike_was_trigger: bool = False
        # D3 — presence/usage-proportional post-vacancy runtime window.
        self._humidity_presence_runtime_until: datetime | None = None
        self._humidity_last_room_occupied: bool | None = None
        # v3.1.0: Shared space - track last auto-off to prevent repeated triggers
        self._last_auto_off_date: str | None = None
        # v3.1.0: Alert light state tracking
        self._alert_lights_active: bool = False
        self._alert_light_original_states: dict[str, dict] = {}
        # Warning flash dedup
        self._last_warning_date_hour: str | None = None
        # Timed cover open/close dedup
        self._last_timed_open_date: str | None = None
        self._last_timed_close_date: str | None = None
        # v4.2.22: Cover verification + straggler retry tracking.
        # Set to True while a verify-and-retry runner is active so the periodic
        # coordinator update doesn't schedule a second concurrent runner.
        self._cover_op_in_flight: bool = False
        self._cover_failures_today: int = 0
        self._cover_attempts_today: int = 0
        self._cover_failure_reset_date: str = dt_util.now().strftime("%Y-%m-%d")
        self._last_cover_failure_time: datetime | None = None
        self._last_cover_failure_entities: list[str] = []
        # Service call tracking (for automation health sensor)
        self._service_calls_today: int = 0
        self._service_failures_today: int = 0
        self._service_call_reset_date: str = dt_util.now().strftime("%Y-%m-%d")
        # v3.18.0: Fan vacancy hold tracking
        self._fan_vacancy_start: datetime | None = None
        # FIX C (fan manual-off cooldown, room-tier).
        # Symmetric to hvac_fans.py:207-217 which sets a 1h cooldown when
        # an external actor turns off an HVAC-managed fan. Room-tier had
        # no such memory, so a user off-tap on a room-owned fan was
        # re-armed on the next 30s tick. See
        # docs/planning/PLANNING_fan_manual_off_cooldown.md D1.
        self._fan_manual_off_until: datetime | None = None
        # Baseline for external-off detection: tracks whether we saw any
        # fan ON on the PREVIOUS tick, so a transition to all-off that
        # wasn't caused by our own service call is diagnosable as
        # external. False on first tick — cold-boot fan-already-off state
        # does NOT open a cooldown.
        self._last_seen_any_fan_on: bool = False
        # We turned a fan OFF ourselves this tick — used to distinguish
        # our own off-write from an external off transition. Cleared on
        # every entry to handle_temperature_based_fan_control.
        self._fan_off_issued_this_tick: bool = False
        # FIX C D2: once-per-boot HVAC-managed-mismatch WARN gate.
        self._fan_hvac_mismatch_warned: bool = False

    def is_fan_in_manual_cooldown(self) -> bool:
        """True while the room-tier fan manual-off cooldown window is live.

        Consumed by ActuatorReconciler._resolve_fan so the reconciler does
        NOT re-arm a room-owned fan that the operator just turned off
        (symmetric to hvac_fans.py's HVAC-tier cooldown). Cheap read: does
        NOT clear expired windows — expiry is handled organically by
        handle_temperature_based_fan_control on the next tick.
        """
        try:
            until = self._fan_manual_off_until
            if until is None:
                return False
            return dt_util.now() < until
        except Exception:
            return False

    async def _safe_service_call(
        self,
        domain: str,
        service: str,
        service_data: dict,
        blocking: bool = False,
        timeout: float = 5.0,
        max_retries: int = 0,
    ) -> bool:
        """Call a service with timeout, error handling, and optional retry.

        Args:
            max_retries: Number of retry attempts (0 = no retry, fire-and-forget).
                         Use max_retries=2 for critical operations (locks, exit automation).
        """
        entity_ids = service_data.get("entity_id", "unknown")
        attempts = 1 + max_retries
        # Reset daily counters
        today = dt_util.now().strftime("%Y-%m-%d")
        if today != self._service_call_reset_date:
            self._service_calls_today = 0
            self._service_failures_today = 0
            self._service_call_reset_date = today
        self._service_calls_today += 1
        for attempt in range(attempts):
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
                    "Service call timeout after %.1fs: %s.%s for %s in room %s (attempt %d/%d)",
                    timeout, domain, service, entity_ids,
                    self.config.get("room_name", "unknown"),
                    attempt + 1, attempts,
                )
            except Exception as e:
                _LOGGER.error(
                    "Service call failed: %s.%s for %s in room %s: %s (attempt %d/%d)",
                    domain, service, entity_ids,
                    self.config.get("room_name", "unknown"), e,
                    attempt + 1, attempts,
                )
            if attempt < max_retries:
                backoff = 1 * (2 ** attempt)  # 1s, 2s exponential backoff
                await asyncio.sleep(backoff)
        self._service_failures_today += 1
        return False

    # ------------------------------------------------------------------
    # v4.2.22: Cover send-with-verify + straggler retry
    # ------------------------------------------------------------------
    def _maybe_reset_cover_counters(self) -> None:
        """Reset daily cover counters if the day has rolled over.

        Review fix M1: also clear last-failure metadata so the diagnostic
        sensor doesn't show stale failure entities/timestamp from yesterday
        when failures_today is 0.
        """
        today = dt_util.now().strftime("%Y-%m-%d")
        if today != self._cover_failure_reset_date:
            self._cover_failures_today = 0
            self._cover_attempts_today = 0
            self._cover_failure_reset_date = today
            self._last_cover_failure_time = None
            self._last_cover_failure_entities = []

    def _schedule_cover_runner(
        self, runner_coro, room_name: str, label: str,
    ) -> None:
        """Schedule a cover verify-and-retry runner as a tracked background task.

        Review fixes:
          - C1: on schedule failure, reset _cover_op_in_flight so we don't
            silently lock out all future cover operations until restart.
          - H1: use entry.async_create_background_task (HA 2024.5+) so the
            runner is tracked and cancelled on entry unload, instead of
            fire-and-forget hass.async_create_task. Prevents leaked
            self-references mutating state after the entry is gone.
        """
        try:
            self._config_entry.async_create_background_task(
                self.hass, runner_coro,
                f"ura_cover_{label}_{room_name}",
            )
        except Exception as e:
            self._cover_op_in_flight = False
            try:
                runner_coro.close()
            except Exception:
                pass
            _LOGGER.warning(
                "Cover %s [%s]: failed to schedule runner: %s",
                label, room_name, e,
            )

    @staticmethod
    def _cover_at_target(state, target_state: str, cover_type: str = "shade") -> bool:
        """Check if a cover state object is at the commanded target.

        Review fix H3: HA cover entities with `current_position` attribute
        report state="open" for any position > 0. A blind partially closed
        at position=10 still reports state="open" — naive state.state
        comparison would mark it a permanent straggler. Use position with
        a 5%-tolerance window when available.

        v4.5.0.4: For venetian/tilt blinds (cover_type="tilt"), check
        `current_tilt_position` instead of `current_position`. The tilt
        action moves the slats while the blind stays at fixed position;
        `current_position` may always read 100 even when slats are fully
        closed. Pre-fix, every tilt blind looked like a permanent
        straggler because position never changed.
        """
        if state is None:
            return False
        attrs = getattr(state, "attributes", None) or {}

        # v4.5.0.4: tilt-blind verify — check tilt_position attribute first.
        if cover_type == "tilt":
            tilt_pos = attrs.get("current_tilt_position")
            if tilt_pos is not None:
                try:
                    tp = float(tilt_pos)
                except (TypeError, ValueError):
                    tp = None
                if tp is not None:
                    if target_state == "closed":
                        return tp <= 5.0
                    if target_state == "open":
                        return tp >= 95.0
            # Fallback if integration doesn't expose tilt_position: trust
            # state.state (which most tilt-capable integrations DO update).
            return state.state == target_state

        # Default (roller-shade) path — unchanged from v4.5.0.3.
        position = attrs.get("current_position")
        if position is not None:
            try:
                pos = float(position)
            except (TypeError, ValueError):
                pos = None
            if pos is not None:
                if target_state == "closed":
                    return pos <= 5.0
                if target_state == "open":
                    return pos >= 95.0
        return state.state == target_state

    async def _send_covers_with_verify(
        self,
        cover_ids: list[str],
        action: str,
        settle_seconds: float = COVER_SETTLE_SECONDS,
        max_retries: int = COVER_MAX_RETRIES,
    ) -> tuple[bool, list[str]]:
        """Send cover command per-cover, verify state after settle, retry stragglers only.

        Args:
            cover_ids: List of cover entity_ids to command.
            action: "open_cover" or "close_cover".
            settle_seconds: Time to wait after a batch before re-checking state.
            max_retries: Number of retry attempts for stragglers (in addition to
                the initial attempt). Total tries = 1 + max_retries.

        Returns:
            (all_succeeded, failed_entities). Increments
            self._cover_failures_today by the number of stragglers that never
            reached commanded state. Caller is responsible for setting any
            dedup based on the returned success flag.

        Hub-acceptance is not per-cover success — Hunter Douglas + similar
        RF-bridged hubs report success on group calls even when individual
        blinds miss the RF burst. We:
          1. send per-cover (not as a group) with pacing to ease hub queueing,
          2. wait `settle_seconds` for blinds to physically reach state,
          3. re-issue commands only to entities that didn't reach state,
          4. backoff between retries.
        """
        if action not in ("open_cover", "close_cover"):
            raise ValueError(f"Unsupported cover action: {action}")

        self._maybe_reset_cover_counters()
        target_state = "open" if action == "open_cover" else "closed"
        room_name = self.config.get("room_name", "Unknown")

        # v4.5.0.4 hotfix: dispatch tilt service for venetian blinds.
        # Pre-fix, the room form let the user pick "Venetian Blinds (Tilt)"
        # as cover_type, but `automation.py` and `_cover_at_target` ignored
        # the value entirely — every blind got `cover.open_cover` /
        # `cover.close_cover`, which raises/lowers the WHOLE blind on a
        # tilt cover, leaving slats unchanged. The dead read of
        # CONF_COVER_TYPE has been latent since the option was added.
        from .const import CONF_COVER_TYPE, COVER_TYPE_SHADE, COVER_TYPE_TILT
        cover_type = self.config.get(CONF_COVER_TYPE, COVER_TYPE_SHADE)
        if cover_type == COVER_TYPE_TILT:
            # cover.open_cover_tilt / cover.close_cover_tilt — moves slats.
            service_name = f"{action}_tilt"
        else:
            service_name = action
        # v4.2.26 (review M1): dedupe input. A misconfigured covers list
        # (same entity appearing twice) would otherwise send the command
        # twice per cycle and waste an RF burst.
        pending = list(dict.fromkeys(cover_ids))
        self._cover_attempts_today += len(pending)

        for attempt in range(max_retries + 1):
            if not pending:
                break
            if attempt > 0:
                backoff = COVER_RETRY_BACKOFF_BASE * attempt
                _LOGGER.info(
                    "Cover %s [%s]: retry %d/%d for %d straggler(s) after %.1fs: %s",
                    service_name, room_name, attempt, max_retries,
                    len(pending), backoff, pending,
                )
                await asyncio.sleep(backoff)

            # Send per-cover with pacing. Review fix M3: max_retries=0 —
            # the outer settle+verify loop is the authoritative retry path.
            # v4.2.23: blocking=False — Hunter Douglas group covers can take
            # 30-60s for all sub-blinds to settle physically, far longer
            # than any reasonable per-call timeout. blocking=True caused
            # 294 false service_failures in one Living Room session because
            # async_call awaited group settle past the 10s timeout. The
            # outer settle+verify loop is what confirms physical state, so
            # we don't need per-call blocking confirmation.
            for cover_id in pending:
                # v4.2.26 (review M3): timeout is meaningless when blocking=False
                # — async_call returns immediately. Outer settle is the gate.
                # v4.5.0.4: service_name is `<action>_tilt` for venetian.
                await self._safe_service_call(
                    "cover",
                    service_name,
                    {"entity_id": cover_id},
                    blocking=False,
                    max_retries=0,
                )
                # Pace inter-cover commands to reduce RF/hub collision.
                # Skip the trailing pause on the last cover of a batch.
                if cover_id != pending[-1]:
                    await asyncio.sleep(COVER_PACE_SECONDS)

            # Wait for blinds to physically settle, then re-evaluate.
            await asyncio.sleep(settle_seconds)

            new_pending: list[str] = []
            for cover_id in pending:
                state = self.hass.states.get(cover_id)
                if state is None:
                    # Entity vanished mid-flight; don't count as straggler.
                    continue
                if state.state in ("unavailable", "unknown"):
                    # Don't retry an offline cover; not a fixable straggler.
                    continue
                # v4.5.0.4: pass cover_type so tilt blinds verify via
                # current_tilt_position attribute instead of current_position.
                if self._cover_at_target(state, target_state, cover_type):
                    continue
                # opening/closing/partial -> still moving or stuck: retry.
                new_pending.append(cover_id)
            pending = new_pending

        success = len(pending) == 0
        if not success:
            self._cover_failures_today += len(pending)
            self._last_cover_failure_time = dt_util.now()
            self._last_cover_failure_entities = list(pending)
            _LOGGER.warning(
                "Cover %s [%s]: %d cover(s) did not reach '%s' after %d attempt(s): %s",
                service_name, room_name, len(pending), target_state,
                max_retries + 1, pending,
            )
        return success, pending

    def _refresh_config(self) -> None:
        """Refresh config from entry options (picks up options flow changes without reload)."""
        self.config = {**self._config_entry.data, **self._config_entry.options}

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
        return self.can_bypass_sleep_mode(state_data.get(STATE_MOTION_DETECTED, False))

    async def handle_occupancy_change(
        self,
        occupied: bool,
        state_data: dict[str, Any],
    ) -> None:
        """Handle occupancy state change."""
        self._refresh_config()
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

        # Covers - open if configured (v3.20.0: gated by CoverAutomationSwitch)
        if self.coordinator._is_cover_automation_enabled():
            await self._control_covers_entry(state_data)

    async def _handle_exit(self, state_data: dict[str, Any]) -> None:
        """Handle room exit automation."""
        # Light control
        await self._control_lights_exit(state_data)

        # Auto switches - turn off
        await self._control_auto_switches(False)

        # Manual switches - turn off
        await self._control_manual_switches_off()

        # Covers - close if configured (v3.20.0: gated by CoverAutomationSwitch)
        if self.coordinator._is_cover_automation_enabled():
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
                service_data["color_temp_kelvin"] = color_temp
            
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

    # =========================================================================
    # v3.6.39: Cover open/close helpers
    # =========================================================================

    # v3.20.0: Valid cover open modes for validation
    _VALID_OPEN_MODES = {
        COVER_OPEN_NONE, COVER_OPEN_ON_ENTRY, COVER_OPEN_AT_TIME,
        COVER_OPEN_ON_ENTRY_AFTER_TIME, COVER_OPEN_AT_TIME_OR_ON_ENTRY,
    }

    def _get_cover_open_mode(self) -> str:
        """Resolve cover open mode (new config with legacy fallback)."""
        mode = self.config.get(CONF_COVER_OPEN_MODE)
        if mode is not None:
            # v3.20.0 Fix 3: Validate against known modes
            if mode in self._VALID_OPEN_MODES:
                return mode
            room_name = self.config.get("room_name", "Unknown")
            _LOGGER.error(
                "Room %s: Invalid cover open mode '%s' — falling back to legacy",
                room_name, mode,
            )
        # Legacy fallback for pre-v3.6.39 entries that still have the
        # legacy CONF_ENTRY_COVER_ACTION key in entry.data. The room form
        # has not collected this CONF since v3.6.39 (the new 5-mode
        # system in CONF_COVER_OPEN_MODE replaced it). Mapping is the
        # one documented in README_v3.6.40 and verified in v4.5.4 audit:
        #   COVER_ACTION_NONE   → COVER_OPEN_NONE
        #   COVER_ACTION_ALWAYS → COVER_OPEN_ON_ENTRY (no time gate)
        #   COVER_ACTION_SMART  → COVER_OPEN_ON_ENTRY_AFTER_TIME
        action = self.config.get(CONF_ENTRY_COVER_ACTION, COVER_ACTION_NONE)
        if action == COVER_ACTION_NONE:
            return COVER_OPEN_NONE
        if action == COVER_ACTION_ALWAYS:
            return COVER_OPEN_ON_ENTRY
        return COVER_OPEN_ON_ENTRY_AFTER_TIME

    def is_cover_currently_intended_open(self, now: datetime | None = None) -> bool:
        """v4.5.9: Per-room intent predicate for HVAC cover management.

        Returns True if the room's CONF_COVER_OPEN_MODE policy says the
        room's covers SHOULD be in the open state at this moment. HVAC's
        solar-gain controller consults this before deciding whether it's
        legitimate to close a cover for solar-gain (don't close what the
        room never intended to be open) or reopen one after the solar
        window (don't open what the room intends closed).

        Mapping by mode:
          - COVER_OPEN_NONE             → False (manual-only; HVAC must not touch)
          - COVER_OPEN_ON_ENTRY         → False (occupancy-driven; HVAC can't predict
                                            future occupancy, so be conservative)
          - COVER_OPEN_AT_TIME          → True iff in time window
          - COVER_OPEN_ON_ENTRY_AFTER_TIME → True iff in time window
          - COVER_OPEN_AT_TIME_OR_ON_ENTRY → True iff in time window
        """
        if now is None:
            now = dt_util.now()
        mode = self._get_cover_open_mode()
        if mode == COVER_OPEN_NONE:
            return False
        if mode == COVER_OPEN_ON_ENTRY:
            # Room only opens on occupancy — HVAC can't second-guess that.
            return False
        # The three time-bearing modes: open during open-time, closed after.
        if mode in (
            COVER_OPEN_AT_TIME,
            COVER_OPEN_ON_ENTRY_AFTER_TIME,
            COVER_OPEN_AT_TIME_OR_ON_ENTRY,
        ):
            try:
                in_open_window = self._is_cover_open_time(now)
                past_close = self._is_cover_close_time(now)
            except Exception:
                # Defensive — if either check throws (config drift, missing
                # location for sunset calc, etc.), fall back to "not intended
                # open" so HVAC doesn't act.
                return False
            return in_open_window and not past_close
        # Unknown mode — defensive default
        return False

    def _is_cover_open_time(self, now: datetime | None = None) -> bool:
        """Check if the configured open time has been reached.

        Uses new config (CONF_COVER_OPEN_TIME_SOURCE) with legacy fallback
        to CONF_OPEN_TIMING_MODE.
        """
        if now is None:
            now = dt_util.now()
        source = self.config.get(CONF_COVER_OPEN_TIME_SOURCE)
        if source is not None:
            if source == TIME_SOURCE_SUNRISE:
                return self._is_after_sunrise(now)
            return now.hour >= int(self.config.get(
                CONF_COVER_OPEN_HOUR, DEFAULT_COVER_OPEN_HOUR
            ))

        # Legacy: use CONF_OPEN_TIMING_MODE
        timing_mode = self.config.get(CONF_OPEN_TIMING_MODE, TIMING_MODE_SUN)
        after_sunrise = self._is_after_sunrise(now)
        in_time_range = self._is_in_open_time_range(now)
        if timing_mode == TIMING_MODE_SUN:
            return after_sunrise
        if timing_mode == TIMING_MODE_TIME:
            return in_time_range
        if timing_mode == TIMING_MODE_BOTH_LATEST:
            return after_sunrise and in_time_range
        if timing_mode == TIMING_MODE_BOTH_EARLIEST:
            return after_sunrise or in_time_range
        return True

    def _is_after_sunrise(self, now: datetime) -> bool:
        """Check if current time is after sunrise + offset."""
        sunrise_offset = self.config.get(CONF_SUNRISE_OFFSET, 0)
        sunrise_time = sun.get_astral_event_date(
            self.hass, "sunrise", dt_util.start_of_local_day()
        )
        if sunrise_time is None:
            # v3.20.0 Fix 4: Default to NOT opening when location unknown (safer)
            room_name = self.config.get("room_name", "Unknown")
            _LOGGER.warning(
                "Room %s: Cannot determine sunrise (location not configured) — deferring cover open",
                room_name,
            )
            return False
        adjusted = sunrise_time + timedelta(minutes=sunrise_offset)
        return now >= adjusted

    def _is_in_open_time_range(self, now: datetime) -> bool:
        """Check if current time is within the configured open time range (legacy)."""
        start_hour = self.config.get(CONF_OPEN_TIME_START, 7)
        end_hour = self.config.get(CONF_OPEN_TIME_END, 20)
        return start_hour <= now.hour < end_hour

    def _are_covers_already_open(self) -> bool:
        """Check if all available covers are already open.

        Review fix: filter unavailable covers so they don't cause
        false negatives (unavailable != "open" would block the check).

        v4.5.6: cover_type-aware. For tilt blinds (venetians) the entity
        `state` reflects position only — slats wide open with the blind
        fully lowered still report state="closed". The gate must compare
        on `current_tilt_position` so a tilt blind with slats genuinely
        open isn't mis-detected as already-open. Thresholds match
        `_cover_at_target` (≥95 = open, ≤5 = closed) so what one helper
        calls "open" the other agrees with. Same bug class as v4.5.0.4
        (CONF_COVER_TYPE was honored by `_send_covers_with_verify` and
        `_cover_at_target` but the gate helpers were missed —
        QUALITY_CONTEXT.md Bug Class #33).
        """
        from .const import CONF_COVER_TYPE, COVER_TYPE_SHADE, COVER_TYPE_TILT
        available = self._get_available_covers()
        if not available:
            return True
        cover_type = self.config.get(CONF_COVER_TYPE, COVER_TYPE_SHADE)
        for cover_id in available:
            state = self.hass.states.get(cover_id)
            if state is None:
                return False
            if cover_type == COVER_TYPE_TILT:
                tilt = state.attributes.get("current_tilt_position")
                if tilt is None:
                    # Integration doesn't expose tilt — fall back to state.
                    if state.state != "open":
                        return False
                    continue
                try:
                    if float(tilt) < 95.0:
                        return False
                except (TypeError, ValueError):
                    if state.state != "open":
                        return False
            else:
                if state.state != "open":
                    return False
        return True

    def _are_covers_already_closed(self) -> bool:
        """Check if all available covers are already closed.

        Review fix: filter unavailable covers so they don't cause
        repeated close commands to already-closed available covers.

        v4.5.6: cover_type-aware. See _are_covers_already_open for
        rationale. Tilt blinds with slats open at tilt=97 used to be
        mis-detected as "already closed" because position=0 made
        state="closed", silently skipping timed/exit close runners.
        """
        from .const import CONF_COVER_TYPE, COVER_TYPE_SHADE, COVER_TYPE_TILT
        available = self._get_available_covers()
        if not available:
            return True
        cover_type = self.config.get(CONF_COVER_TYPE, COVER_TYPE_SHADE)
        for cover_id in available:
            state = self.hass.states.get(cover_id)
            if state is None:
                return False
            if cover_type == COVER_TYPE_TILT:
                tilt = state.attributes.get("current_tilt_position")
                if tilt is None:
                    if state.state != "closed":
                        return False
                    continue
                try:
                    if float(tilt) > 5.0:
                        return False
                except (TypeError, ValueError):
                    if state.state != "closed":
                        return False
            else:
                if state.state != "closed":
                    return False
        return True

    def _get_available_covers(self) -> list[str]:
        """v3.20.0 Fix 1: Filter covers to only available entities."""
        covers = self.config.get(CONF_COVERS, [])
        if not covers:
            return []
        available = []
        unavailable = []
        for cover_id in covers:
            state = self.hass.states.get(cover_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable.append(cover_id)
            else:
                available.append(cover_id)
        if unavailable:
            # Log-rate fix: `_get_available_covers` is called on every cover
            # op (entry/timed/HVAC), so a down integration (e.g. PowerView
            # gateway offline) flooded the log with this warning ~every
            # 1-2s. Warn only when the unavailable SET changes (goes down or
            # partially recovers), not on every call. Lazy per-instance
            # tracker — no __init__ change needed.
            unavailable_key = frozenset(unavailable)
            if getattr(self, "_last_unavailable_covers_logged", None) != unavailable_key:
                self._last_unavailable_covers_logged = unavailable_key
                room_name = self.config.get("room_name", "Unknown")
                _LOGGER.warning(
                    "Room %s: Skipping %d unavailable cover(s): %s",
                    room_name, len(unavailable), unavailable,
                )
        elif getattr(self, "_last_unavailable_covers_logged", None) is not None:
            # All covers recovered — reset so a future outage warns once again.
            self._last_unavailable_covers_logged = None
        return available

    async def _control_covers_entry(self, state_data: dict[str, Any]) -> None:
        """Control covers on occupancy entry.

        Handles modes: on_entry, on_entry_after_time, at_time_or_on_entry.
        Mode at_time is handled by check_timed_cover_open (periodic).
        """
        if self.is_sleep_mode_active() and self.config.get(CONF_SLEEP_BLOCK_COVERS, True):
            return

        mode = self._get_cover_open_mode()
        if mode == COVER_OPEN_NONE or mode == COVER_OPEN_AT_TIME:
            return

        covers = self.config.get(CONF_COVERS, [])
        if not covers:
            return

        if mode == COVER_OPEN_ON_ENTRY:
            # Open on entry regardless of time
            pass
        elif mode == COVER_OPEN_ON_ENTRY_AFTER_TIME:
            if not self._is_cover_open_time():
                return
        elif mode == COVER_OPEN_AT_TIME_OR_ON_ENTRY:
            # On entry path: always open (the at_time part is periodic)
            pass
        else:
            return

        if self._are_covers_already_open():
            return

        # v3.20.0 Fix 1: Validate cover entities before command
        available = self._get_available_covers()
        if not available:
            return

        if self._cover_op_in_flight:
            return  # a runner is still verifying a previous batch
        self._cover_op_in_flight = True

        room_name = self.config.get("room_name", "Unknown")
        _LOGGER.info("Cover open [%s]: mode=%s, opening %d cover(s)",
                      room_name, mode, len(available))
        activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")

        async def _runner() -> None:
            try:
                success, failed = await self._send_covers_with_verify(
                    available, "open_cover",
                )
                if activity_logger:
                    # Review fix M5: log the actual outcome, not just "opened N".
                    n_ok = len(available) - len(failed)
                    desc = (
                        f"Opened {n_ok}/{len(available)} cover(s) "
                        f"(entry, mode={mode})"
                    )
                    if not success:
                        desc += f" — {len(failed)} straggler(s): {failed}"
                    self.hass.async_create_task(activity_logger.log(
                        coordinator="room",
                        action="cover_open",
                        description=desc,
                        room=room_name,
                        entity_id=available[0] if available else None,
                    ))
            finally:
                self._cover_op_in_flight = False

        self._schedule_cover_runner(_runner(), room_name, "entry_open")

    async def check_timed_cover_open(self) -> None:
        """Open covers at sunrise/configured time regardless of occupancy.

        Handles modes: at_time, at_time_or_on_entry.
        Called by coordinator on each update cycle (periodic task).
        Only triggers once per day per room.

        v4.2.22: Schedules a verify-and-retry runner as a background task so
        the coordinator update cycle isn't blocked by settle delays. Dedup
        date is set only on confirmed success (state-verified, not service-
        call-acceptance). _cover_op_in_flight prevents double-scheduling.
        """
        mode = self._get_cover_open_mode()
        if mode not in (COVER_OPEN_AT_TIME, COVER_OPEN_AT_TIME_OR_ON_ENTRY):
            return

        if self.is_sleep_mode_active() and self.config.get(CONF_SLEEP_BLOCK_COVERS, True):
            return

        covers = self.config.get(CONF_COVERS, [])
        if not covers:
            return

        now = dt_util.now()
        today = now.strftime("%Y-%m-%d")
        if self._last_timed_open_date == today:
            return

        if not self._is_cover_open_time(now):
            return

        # v4.5.6: removed `_are_covers_already_open()` early-return. Timed
        # open is a deterministic schedule — fire it whether or not the
        # blinds *look* open. The verify path resolves a no-op open in
        # zero retries (cover.open_cover_tilt on already-open slats is
        # idempotent), so the cost is one extra service call per day.
        # Removing the gate also closes a Bug Class #33 hole where a
        # tilt blind with slats already open at tilt=97 would block the
        # daily open from running.

        # v3.20.0 Fix 1: Validate cover entities
        available = self._get_available_covers()
        if not available:
            return

        if self._cover_op_in_flight:
            return  # a runner is still verifying a previous batch
        self._cover_op_in_flight = True

        room_name = self.config.get("room_name", "Unknown")
        _LOGGER.info(
            "Timed cover open [%s]: opening %d cover(s) (mode=%s)",
            room_name, len(available), mode,
        )

        async def _runner() -> None:
            try:
                # Review fix M4: re-check sleep mode just before issuing
                # commands; the runner runs ~10s+ after the periodic check.
                if (
                    self.is_sleep_mode_active()
                    and self.config.get(CONF_SLEEP_BLOCK_COVERS, True)
                ):
                    return
                # v4.2.23 hotfix: set dedup BEFORE the helper runs.
                # Internal retries (3 attempts) are the daily budget; if they
                # fail (e.g. group-cover entity flaps state during async sub-
                # blind settling) we must NOT loop on the next coordinator
                # cycle. v4.2.22 set dedup only on verified success and
                # produced a 2200-event RF storm on cover.living_blinds (an
                # HA group of 10 sub-blinds). Single shot per day; failures
                # surface via _cover_failures_today on the health sensor.
                self._last_timed_open_date = today
                success, _failed = await self._send_covers_with_verify(
                    available, "open_cover",
                )
                if not success:
                    _LOGGER.warning(
                        "Timed cover open [%s]: stragglers persisted "
                        "after internal retries — not re-firing today",
                        room_name,
                    )
            finally:
                self._cover_op_in_flight = False

        self._schedule_cover_runner(_runner(), room_name, "timed_open")

    async def _control_covers_exit(self, state_data: dict[str, Any]) -> None:
        """Control covers on exit (vacancy)."""
        action = self.config.get(CONF_EXIT_COVER_ACTION, COVER_ACTION_NONE)
        if action == COVER_ACTION_NONE:
            return

        covers = self.config.get(CONF_COVERS, [])
        if not covers:
            return

        # Check if after sunset for after_sunset action
        if action == COVER_ACTION_AFTER_SUNSET:
            if not self._is_after_sunset(dt_util.now()):
                return

        # Respect manual override: skip if already closed
        if self._are_covers_already_closed():
            return

        # v3.20.0 Fix 1: Validate cover entities
        available = self._get_available_covers()
        if not available:
            return

        if self._cover_op_in_flight:
            return  # a runner is still verifying a previous batch
        self._cover_op_in_flight = True

        room_name = self.config.get("room_name", "Unknown")
        _LOGGER.info("Cover close on exit [%s]: closing %d cover(s)", room_name, len(available))
        activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")

        async def _runner() -> None:
            try:
                success, failed = await self._send_covers_with_verify(
                    available, "close_cover",
                )
                if activity_logger:
                    n_ok = len(available) - len(failed)
                    desc = f"Closed {n_ok}/{len(available)} cover(s) (exit)"
                    if not success:
                        desc += f" — {len(failed)} straggler(s): {failed}"
                    self.hass.async_create_task(activity_logger.log(
                        coordinator="room",
                        action="cover_close",
                        description=desc,
                        room=room_name,
                        entity_id=available[0] if available else None,
                    ))
            finally:
                self._cover_op_in_flight = False

        self._schedule_cover_runner(_runner(), room_name, "exit_close")

    async def check_timed_cover_close(self) -> None:
        """Close covers at sunset/configured time.

        Called by coordinator on each update cycle (periodic task).
        Only triggers once per day per room.
        """
        if not self.config.get(CONF_TIMED_CLOSE_ENABLED, False):
            return

        covers = self.config.get(CONF_COVERS, [])
        if not covers:
            return

        now = dt_util.now()
        today = now.strftime("%Y-%m-%d")

        if self._last_timed_close_date == today:
            return

        if not self._is_cover_close_time(now):
            return

        # v4.5.6: removed `_are_covers_already_closed()` early-return.
        # Timed close is a deterministic schedule — fire it whether or
        # not the blinds *look* closed. Reproducer: tilt blinds with
        # position=0 + tilt=97 (blind down, slats wide open) reported
        # state="closed" so the gate kept skipping the close all day.
        # Same bug class as v4.5.0.4's CONF_COVER_TYPE (#33) but in a
        # different helper. The verify path resolves a no-op close on
        # already-closed slats in zero retries; cost is one extra
        # service call per day per room.

        # v3.20.0 Fix 1: Validate cover entities
        available = self._get_available_covers()
        if not available:
            return

        if self._cover_op_in_flight:
            return  # a runner is still verifying a previous batch
        self._cover_op_in_flight = True

        room_name = self.config.get("room_name", "Unknown")
        _LOGGER.info(
            "Timed cover close [%s]: closing %d cover(s)",
            room_name, len(available),
        )

        async def _runner() -> None:
            try:
                # Review fix M4: re-check sleep mode (runner runs ~10s+ later).
                if (
                    self.is_sleep_mode_active()
                    and self.config.get(CONF_SLEEP_BLOCK_COVERS, True)
                ):
                    return
                # v4.2.23 hotfix: set dedup BEFORE the helper runs.
                # Internal retries (3 attempts) are the daily budget; if they
                # fail, we must NOT loop. v4.2.22 set dedup only on verified
                # success and produced a 2200-event RF storm on
                # cover.living_blinds (HA group of 10 sub-blinds whose group
                # state flaps "open"<->"closing" during async sub-blind
                # settling). Single shot per day; failures surface via
                # _cover_failures_today on the health sensor.
                self._last_timed_close_date = today
                success, _failed = await self._send_covers_with_verify(
                    available, "close_cover",
                )
                if not success:
                    _LOGGER.warning(
                        "Timed cover close [%s]: stragglers persisted "
                        "after internal retries — not re-firing today",
                        room_name,
                    )
            finally:
                self._cover_op_in_flight = False

        self._schedule_cover_runner(_runner(), room_name, "timed_close")

    def _is_cover_close_time(self, now: datetime) -> bool:
        """Check if the configured close time has been reached.

        Uses new config (CONF_COVER_CLOSE_TIME_SOURCE) with legacy fallback
        to CONF_CLOSE_TIMING_MODE.
        """
        source = self.config.get(CONF_COVER_CLOSE_TIME_SOURCE)
        if source is not None:
            if source == TIME_SOURCE_SUNSET:
                return self._is_after_sunset(now)
            return now.hour >= int(self.config.get(
                CONF_COVER_CLOSE_HOUR, DEFAULT_COVER_CLOSE_HOUR
            ))

        # Legacy: use CONF_CLOSE_TIMING_MODE
        timing_mode = self.config.get(CONF_CLOSE_TIMING_MODE, TIMING_MODE_SUN)
        after_sunset = self._is_after_sunset(now)
        after_close_time = self._is_after_close_time(now)
        if timing_mode == TIMING_MODE_SUN:
            return after_sunset
        if timing_mode == TIMING_MODE_TIME:
            return after_close_time
        if timing_mode == TIMING_MODE_BOTH_LATEST:
            return after_sunset and after_close_time
        if timing_mode == TIMING_MODE_BOTH_EARLIEST:
            return after_sunset or after_close_time
        return False

    def _is_after_sunset(self, now: datetime) -> bool:
        """Check if current time is after sunset + offset."""
        sunset_offset = self.config.get(CONF_SUNSET_OFFSET, 0)
        sunset_time = sun.get_astral_event_date(
            self.hass, "sunset", dt_util.start_of_local_day()
        )
        if sunset_time is None:
            return False
        adjusted = sunset_time + timedelta(minutes=sunset_offset)
        return now >= adjusted

    def _is_after_close_time(self, now: datetime) -> bool:
        """Check if current time is at or after the configured close hour (legacy)."""
        close_hour = int(self.config.get(CONF_CLOSE_TIME, 20))
        return now.hour >= close_hour

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

        # v3.18.1: Defer to HVAC coordinator if it's managing this room's fans
        hvac_manages = self._is_hvac_managing_fans()
        if hvac_manages:
            return

        # FIX C D2: silent-mismatch diagnostic. Room believes it should be
        # HVAC-managed (hvac_coordination_enabled=True with a
        # climate_entity), but HVAC's fan_controller._room_fans doesn't
        # include this room — most commonly because the Zone Manager
        # entry's zone_rooms list doesn't reference this room's entry_id
        # (or the zone lacks a thermostat). Emit ONCE per HA restart so
        # the config gap is discoverable without spamming the log.
        if not self._fan_hvac_mismatch_warned:
            if (
                self.config.get(CONF_HVAC_COORDINATION_ENABLED, False)
                and self.config.get(CONF_CLIMATE_ENTITY)
                and fans
            ):
                _LOGGER.warning(
                    "Room %s expects HVAC fan management "
                    "(hvac_coordination_enabled=True, climate_entity=%s) "
                    "but is not in HVAC fan_controller._room_fans — "
                    "room-tier is owning fans. Check Zone Manager "
                    "zone_rooms wiring.",
                    self.config.get("room_name", "Unknown"),
                    self.config.get(CONF_CLIMATE_ENTITY),
                )
                self._fan_hvac_mismatch_warned = True

        # FIX C D1: room-tier manual-off cooldown.
        # Symmetric to hvac_fans.py:207-217. Detect an external actor
        # turning fans off (previously any-on, now all-off, and we did
        # NOT issue an off-call this tick) and open a cooldown window.
        # While the window is live, do NOT re-arm — an operator that
        # manually killed a fan expects it to stay killed.
        # Kill switch: DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S == 0 disables.
        cooldown_s = DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S
        self._fan_off_issued_this_tick = False
        any_fan_on_now = any(
            (s := self.hass.states.get(f)) is not None and s.state == STATE_ON
            for f in fans
        )
        if cooldown_s > 0:
            if (
                self._last_seen_any_fan_on
                and not any_fan_on_now
                and self._fan_manual_off_until is None
            ):
                self._fan_manual_off_until = (
                    dt_util.now() + timedelta(seconds=cooldown_s)
                )
                _LOGGER.info(
                    "Room %s: fan turned off externally — "
                    "room-tier cooldown until %s (FIX C)",
                    self.config.get("room_name", "Unknown"),
                    self._fan_manual_off_until.isoformat(),
                )
            elif (
                self._fan_manual_off_until is not None
                and any_fan_on_now
            ):
                # Manual-on reversal — operator changed their mind.
                _LOGGER.info(
                    "Room %s: fan back on during cooldown — "
                    "room-tier cooldown cleared (FIX C)",
                    self.config.get("room_name", "Unknown"),
                )
                self._fan_manual_off_until = None
            elif (
                self._fan_manual_off_until is not None
                and dt_util.now() >= self._fan_manual_off_until
            ):
                # Window expired — clear.
                self._fan_manual_off_until = None

            # If cooldown live, skip activation. We must NOT block
            # turn-OFF paths (an in-cooldown room whose temp drops
            # below threshold should still get an off-call emitted;
            # any_fan_on_now is False in that case, so the off path
            # inside the temp branch is a no-op anyway).
            if self._fan_manual_off_until is not None:
                # Baseline update happens at end via last_seen tracking.
                self._last_seen_any_fan_on = any_fan_on_now
                return

        # v3.18.1: Fan sleep policy — reduce speed or turn off during sleep
        sleep_speed_cap = None
        if self.is_sleep_mode_active():
            policy = self.config.get(CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY)
            if policy == FAN_SLEEP_OFF:
                await self._safe_service_call(
                    "homeassistant", SERVICE_TURN_OFF, {"entity_id": fans},
                    blocking=False,
                )
                # FIX C: we owned this off. Baseline reflects our intent
                # (state read may not have propagated on blocking=False).
                self._last_seen_any_fan_on = False
                return
            elif policy == FAN_SLEEP_REDUCE:
                sleep_speed_cap = 33  # Cap at low speed during sleep

        # v3.18.0: Fan vacancy hold — don't turn off fans immediately on occupancy timeout
        # BUG 1 fix (2026-08-01 Study A, Phase 1 D0): the vacancy-hold
        # override (`occupied = True` during grace) applies ONLY when a
        # fan is already running (`any_fan_on_now`, computed above at
        # the FIX C cooldown site). The documented intent was "don't
        # turn OFF running fans immediately on timeout"; without the
        # any_fan_on_now gate, the override also ARMS turn-ONs
        # post-restart in hot vacant rooms — on boot the RAM
        # `_fan_vacancy_start` is None, the first vacant tick re-stamps
        # it, and for the next `fan_vacancy_hold` seconds this branch
        # flipped `occupied=True` so the downstream temperature branch
        # emitted a spurious fan.turn_on in an unoccupied room.
        fan_vacancy_hold = self.config.get(CONF_FAN_VACANCY_HOLD, DEFAULT_FAN_VACANCY_HOLD)
        _hold_running_fan = False
        if not occupied:
            if any_fan_on_now:
                if self._fan_vacancy_start is None:
                    self._fan_vacancy_start = dt_util.now()
                vacancy_elapsed = (dt_util.now() - self._fan_vacancy_start).total_seconds()
                if vacancy_elapsed < fan_vacancy_hold:
                    _hold_running_fan = True
                    occupied = True  # Override: hold RUNNING fans during grace period
            else:
                # No fan to hold — clear any stale stamp so a later
                # externally-lit fan doesn't inherit a phantom grace window.
                self._fan_vacancy_start = None
        else:
            self._fan_vacancy_start = None  # Reset on re-occupation

        threshold = self.config.get(CONF_FAN_TEMP_THRESHOLD, 80)
        hysteresis = 2.0  # degrees dead band to prevent rapid cycling
        # Check if fans are currently on
        any_fan_on = any(
            (s := self.hass.states.get(f)) is not None and s.state == STATE_ON
            for f in fans
        )
        # Use lower threshold for turn-off to prevent cycling
        effective_threshold = (threshold - hysteresis) if any_fan_on else threshold
        # Sleep-state occupied fan trust — companion to hvac_fans
        # _evaluate_temp_fan sleep-occupied short-circuit. FAN_SLEEP_OFF
        # (explicit user opt-out) already returned at line 1517 above.
        # FAN_SLEEP_REDUCE speed cap still applies via sleep_speed_cap.
        # Suppresses the temperature off-path while sleeping with occupant
        # present IN A BEDROOM — gate prevents spurious mid-night presence
        # in common areas (kitchen, living room, hallways) from holding
        # fans on. Rooms without an explicit room_type default to
        # ROOM_TYPE_GENERIC and safely fall through to existing behavior.
        #
        # D-AUT (2026-06-11 fan-trust state extension): this site uses the
        # per-room is_sleep_mode_active() TIME-WINDOW
        # (sleep_start_hour..sleep_end_hour), NOT the house_state machine.
        # Deliberately distinct from hvac_fans FAN_TRUST_STATES — mixing
        # the two semantics (per-room schedule vs. house aggregate) would
        # over-extend non-bedroom common-area rooms whose schedule
        # disagrees with the house state. The time-window already covers
        # the realistic bed-time hours; the hvac_fans + hvac sibling
        # cycle picks up home_night/waking for the bedroom-fan path.
        room_type = self.config.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
        sleep_occupied_hold = (
            self.is_sleep_mode_active()
            and occupied
            and room_type == ROOM_TYPE_BEDROOM
        )
        if (temperature < effective_threshold or not occupied) and not sleep_occupied_hold:
            # Turn off fans/switches if below threshold or room vacant
            # v3.2.9: Use homeassistant domain for multi-domain support
            await self._safe_service_call(
                "homeassistant",
                SERVICE_TURN_OFF,
                {"entity_id": fans},
                blocking=False,
            )
            # Activity log: fan off (only if fans were actually on)
            if any_fan_on:
                activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                if activity_logger:
                    room_name = self.config.get("room_name", "Unknown")
                    reason = "below threshold" if temperature < effective_threshold else "vacant"
                    self.hass.async_create_task(activity_logger.log(
                        coordinator="room",
                        action="fan_off",
                        description=f"Fans off ({reason}, {temperature:.0f}°F)",
                        room=room_name,
                        entity_id=fans[0] if fans else None,
                    ))
            # FIX C: we owned this off — update baseline before returning
            # so next tick doesn't mis-detect our own off as external.
            self._last_seen_any_fan_on = False
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

        # v3.18.1: Apply sleep speed cap if active
        if sleep_speed_cap is not None:
            speed_pct = min(speed_pct, sleep_speed_cap)

        if speed_pct > 0:
            # Comfort-fan house-AWAY veto (mmwave-corroboration Tier-3, D3).
            # Routes through the shared fan_veto.should_veto_comfort_fan
            # predicate — Bug-Class-#53 mitigation: every comfort-fan
            # turn_on site MUST consult the same helper. Explicitly NOT
            # applied to turn-off (line ~1742 above), humidity path
            # (handle_humidity_based_fan_control), sleep-off short-circuit
            # (line ~1683), or safety paths.
            if should_veto_comfort_fan(
                self.hass,
                self.config.get(CONF_ROOM_NAME, ""),
                self.config,
            ):
                # Baseline update mirrors the "no action" branch below.
                self._last_seen_any_fan_on = any_fan_on_now
                return
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
                # Activity log: fan on (only if fans were not already on)
                if not any_fan_on:
                    activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                    if activity_logger:
                        room_name = self.config.get("room_name", "Unknown")
                        self.hass.async_create_task(activity_logger.log(
                            coordinator="room",
                            action="fan_on",
                            description=f"Fans on at {speed_pct}% ({temperature:.0f}°F)",
                            room=room_name,
                            entity_id=fans[0] if fans else None,
                        ))
            except Exception as e:
                _LOGGER.error("Error controlling fans: %s", e)
            # FIX C: baseline reflects our intent (we just turned fans ON).
            self._last_seen_any_fan_on = True
        else:
            # No action this tick — baseline follows observed state.
            self._last_seen_any_fan_on = any_fan_on_now

    def _fan_is_actually_on(self, fans: list[str]) -> bool:
        """Return True if any entity in fans reports state 'on'.

        Uses hass.states.get — synchronous in-memory lookup, safe from any context.
        Called at the top of handle_humidity_based_fan_control to detect a fan that
        was already running when the coordinator woke (post-reload or post-restart).
        """
        for entity_id in fans:
            try:
                state = self.hass.states.get(entity_id)
                if state is not None and state.state == STATE_ON:
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    async def handle_humidity_based_fan_control(
        self,
        humidity: float | None,
        room_occupied: bool | None = None,
        automation_enabled: bool = True,
    ) -> None:
        """Control humidity fans/switches based on humidity level.

        Bathroom-exhaust intelligence cycle (D1-D4): humidity/exhaust fans are
        ALWAYS room-owned — independent of CONF_HVAC_COORDINATION_ENABLED and
        CONF_FAN_CONTROL_ENABLED. The HVAC-coord humidity path in hvac_fans.py
        has been removed. The room-tier path is now the SOLE controller (I1),
        gated only by toggle #3 (CONF_HUMIDITY_FAN_CONTROL_ENABLED) + per-knob
        enables. The orphan-fan state (toggle #1 ON + toggle #2 OFF leaving a
        humidity fan unmanaged) is eliminated by this consolidation.

        Pre-existing semantics preserved:
          v3.2.8.2 — supports both fan.* and switch.* domains.
          v4.6.2.1 — max-runtime cap, hysteresis, post-cap suppression.
          v4.6.2.3 — reload-mid-cycle anchor seeding (now also the upgrade
            migration mechanism for fans physically ON in previously-HVAC-
            managed rooms — see I1 acceptance test).

        New (this cycle):
          D2 — EMA-baseline spike detection (current >= baseline + Δ), warm-up
            fallback to the absolute threshold, baseline-relative OFF.
          D3 — presence/usage-proportional post-vacancy runtime: keeps the
            exhaust running for min(BASE + PER_MIN*occupancy_min, CAP) seconds
            after vacancy, modeled on guest_toilet_automation2.
          D4 — wet-room (CONF_WET_ROOM) gates D2/D3 default-on and exempts
            wet-room exhausts from FAN_SLEEP_OFF.
        """
        humidity_fans = self.config.get(CONF_HUMIDITY_FANS, [])
        if not humidity_fans or humidity is None:
            return

        toggle3_on = bool(self.config.get(
            CONF_HUMIDITY_FAN_CONTROL_ENABLED, DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
        ))

        # FIX B (second fix-up — D-HIGH-2): reload-seed MUST run ABOVE the
        # cap-only early-return. Previously the seed lived below it
        # (v4.6.2.3 site, automation.py:1831-ish), so on a restart with
        # toggle #3 OFF (or master-automation OFF) and the fan physically
        # ON, the anchor never got seeded and the safety cap could never
        # fire — the fan ran indefinitely. Seed first; cap-only branch
        # second.
        now_seed = dt_util.now()
        if (
            self._humidity_on_since is None
            and self._fan_is_actually_on(humidity_fans)
        ):
            _LOGGER.info(
                "humidity_fan_reload_seeding: fan already on at startup — seeding anchor"
            )
            self._humidity_on_since = now_seed
            self._humidity_fan_triggered_time = now_seed

        # FIX 3a (bathroom-exhaust intelligence) — SAFETY-CAP EXCEPTION:
        # FIX A (second fix-up — Option 2 / D-HIGH-1): also take this
        # cap-only branch when master-automation is OFF. The safety cap
        # is a universal backstop; venting/on-logic/off-threshold are
        # comfort automation and require BOTH master-automation enabled
        # AND toggle #3 ON.
        if (not toggle3_on) or (not automation_enabled):
            if self._humidity_on_since is not None:
                max_runtime_cap = self.config.get(
                    CONF_HUMIDITY_FAN_MAX_RUNTIME,
                    DEFAULT_HUMIDITY_FAN_MAX_RUNTIME,
                )
                now_cap = dt_util.now()
                elapsed_cap = (now_cap - self._humidity_on_since).total_seconds()
                if elapsed_cap >= max_runtime_cap:
                    _LOGGER.info(
                        "humidity_fan_max_runtime_exceeded (cap-only safety, "
                        "toggle3=%s automation=%s): forcing off after %.0f s "
                        "(cap %.0f s)",
                        toggle3_on, automation_enabled,
                        elapsed_cap, max_runtime_cap,
                    )
                    await self._safe_service_call(
                        "homeassistant", SERVICE_TURN_OFF,
                        {"entity_id": humidity_fans},
                        blocking=False,
                    )
                    self._humidity_on_since = None
                    self._humidity_fan_triggered_time = None
                    self._humidity_cap_suppressed = True
                    self._humidity_spike_was_trigger = False
                    self._humidity_presence_runtime_until = None
                    self._humidity_reset_baseline()
            return

        wet_room = bool(self.config.get(CONF_WET_ROOM, False))

        # v3.18.1: Fan sleep policy — turn off humidity fans during sleep if
        # policy=off, EXCEPT wet-room exhausts (D4 sleep-exemption: a 3am
        # bathroom exhaust must not be blocked by sleep policy; max-runtime
        # cap still bounds total runtime).
        if self.is_sleep_mode_active() and not wet_room:
            policy = self.config.get(CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY)
            if policy == FAN_SLEEP_OFF:
                await self._safe_service_call(
                    "homeassistant", SERVICE_TURN_OFF, {"entity_id": humidity_fans},
                    blocking=False,
                )
                self._humidity_fan_triggered_time = None
                self._humidity_on_since = None
                # D3: clear presence-runtime extension on forced sleep-off.
                self._humidity_presence_runtime_until = None
                # v4.6.4 P3a: do NOT clear `_humidity_cap_suppressed` here.
                return

        threshold = self.config.get(CONF_HUMIDITY_FAN_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD)
        timeout = self.config.get(CONF_HUMIDITY_FAN_TIMEOUT, DEFAULT_HUMIDITY_FAN_TIMEOUT)
        max_runtime = self.config.get(CONF_HUMIDITY_FAN_MAX_RUNTIME, DEFAULT_HUMIDITY_FAN_MAX_RUNTIME)
        off_threshold = threshold - DEFAULT_HUMIDITY_FAN_HYSTERESIS
        now = dt_util.now()

        # D2 — EMA spike detection state update (before the cap check so a
        # spike-armed fan still sees a fresh sample on the tick the cap fires).
        spike_enabled = bool(self.config.get(CONF_HUMIDITY_FAN_SPIKE_ENABLED, False))
        spike_delta = float(
            self.config.get(
                CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT,
                DEFAULT_HUMIDITY_FAN_SPIKE_DELTA_PCT,
            )
        )
        spike_alpha_s = float(
            self.config.get(
                CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
                DEFAULT_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
            )
        )
        spike_mode = self.config.get(
            CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
            DEFAULT_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
        )
        spike_fired = False
        if spike_enabled and spike_alpha_s > 0:
            try:
                self._humidity_update_baseline(humidity, now, spike_alpha_s, spike_mode)
                spike_fired = self._humidity_spike_should_fire(
                    humidity, now, spike_alpha_s, spike_delta, spike_mode,
                )
            except Exception as exc:  # noqa: BLE001 — never let analytics break actuation
                _LOGGER.debug("humidity_fan_spike: baseline/spike eval errored: %s", exc)
                spike_fired = False

        # v4.6.2.3 reload-mid-cycle anchor seeding moved ABOVE the cap-only
        # branch (FIX B, second fix-up) so the cap is reachable when toggle
        # #3 or master-automation is OFF. Do NOT re-seed here.

        # v4.6.2.1: Max-runtime cap — check before normal logic.
        if (
            self._humidity_on_since is not None
            and (now - self._humidity_on_since).total_seconds() >= max_runtime
        ):
            _LOGGER.info(
                "humidity_fan_max_runtime_exceeded: forcing off after %.0f s (cap %.0f s)",
                (now - self._humidity_on_since).total_seconds(),
                max_runtime,
            )
            await self._safe_service_call(
                "homeassistant", SERVICE_TURN_OFF, {"entity_id": humidity_fans},
                blocking=False,
            )
            # v4.6.4 P3c: clear anchors on cap-fire.
            self._humidity_on_since = None
            self._humidity_fan_triggered_time = None
            self._humidity_cap_suppressed = True
            self._humidity_spike_was_trigger = False
            self._humidity_presence_runtime_until = None
            # D2 — clear EMA state on fan-off so the next ON event seeds a
            # fresh baseline (no stale shower humidity bleeding into the
            # post-cap quiet period).
            self._humidity_reset_baseline()
            return

        # v4.6.2.1: Clear suppression once humidity drops below OFF threshold.
        if self._humidity_cap_suppressed:
            if humidity <= off_threshold:
                self._humidity_cap_suppressed = False
            else:
                # Still suppressed — do not re-trigger (spike does NOT bypass
                # suppression — operator-settled, Q-review.)
                return

        # v4.6.2.1: Hysteresis — fan_is_on derived from anchor.
        fan_is_on = self._humidity_fan_triggered_time is not None

        # D3 — presence/usage-proportional post-vacancy runtime book-keeping.
        # Update the vacancy edge + window timer BEFORE the OFF branch so the
        # window keeps the fan ON when humidity is already below off_threshold.
        #
        # FIX 2 (bathroom-exhaust intelligence): only ARM the window when the
        # fan is actually on. Without this, a no-shower vacancy edge armed a
        # latent window that a later unrelated fan-on cycle would inherit and
        # silently extend. Update last_room_occupied tracking ALWAYS so we
        # don't miss an edge, but only ARM when fan_is_on.
        presence_runtime_enabled = bool(
            self.config.get(CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED, False)
        )
        if presence_runtime_enabled and wet_room and room_occupied is not None:
            if fan_is_on:
                self._humidity_update_presence_runtime(now, room_occupied)
            else:
                # Keep edge-tracking current so a future fan-on cycle's
                # vacate edge fires correctly; do NOT arm the window.
                self._humidity_last_room_occupied = room_occupied

        # D2 — compose the ON trigger: absolute threshold OR spike.
        absolute_triggered = humidity >= threshold
        on_trigger = absolute_triggered or spike_fired

        if on_trigger:
            if not fan_is_on:
                self._humidity_fan_triggered_time = now
                self._humidity_on_since = now
                self._humidity_spike_was_trigger = spike_fired and not absolute_triggered
                if self._humidity_spike_was_trigger:
                    _LOGGER.info(
                        "humidity_fan_spike_triggered: baseline ≈ %s, "
                        "current %.1f%% (mode=%s)",
                        ("%.1f" % self._humidity_ema) if self._humidity_ema is not None else "n/a",
                        humidity, spike_mode,
                    )
            await self._safe_service_call(
                "homeassistant",
                SERVICE_TURN_ON,
                {"entity_id": humidity_fans},
                blocking=False,
            )
            _LOGGER.debug(
                "Turned on humidity fans — humidity at %.1f%% (spike=%s)",
                humidity, spike_fired,
            )
            return

        # D3 — keep the fan on during the post-vacancy window even when humidity
        # has dropped below OFF threshold. Window does NOT extend through the
        # max-runtime cap (the cap-branch above clears the window).
        if (
            fan_is_on
            and self._humidity_presence_runtime_until is not None
            and now < self._humidity_presence_runtime_until
        ):
            return  # presence-runtime hold

        # OFF branch — humidity at/below off_threshold OR (spike-was-trigger and
        # baseline-relative OFF condition met).
        if fan_is_on:
            spike_off_ok = False
            if self._humidity_spike_was_trigger and self._humidity_ema is not None:
                delta_off = max(spike_delta / 2.0, 1.0)  # Δ_off ≈ Δ/2
                spike_off_ok = humidity <= self._humidity_ema + delta_off

            ready_to_off = humidity <= off_threshold or spike_off_ok
            if ready_to_off:
                elapsed = (now - self._humidity_fan_triggered_time).total_seconds()
                if elapsed >= timeout:
                    await self._safe_service_call(
                        "homeassistant",
                        SERVICE_TURN_OFF,
                        {"entity_id": humidity_fans},
                        blocking=False,
                    )
                    _LOGGER.debug(
                        "Turned off humidity fans — humidity %.1f%% (spike_off=%s),"
                        " ran %.0f s",
                        humidity, spike_off_ok, elapsed,
                    )
                    self._humidity_fan_triggered_time = None
                    self._humidity_on_since = None
                    self._humidity_spike_was_trigger = False
                    self._humidity_presence_runtime_until = None
                    # D2: clear baseline state on fan-off for re-arming.
                    self._humidity_reset_baseline()
        else:
            # FIX 2 (bathroom-exhaust intelligence): no-fan, no-trigger path.
            # If a stale presence-runtime window is hanging around from a
            # prior cycle, clear it so it cannot bleed into a future fan-on
            # cycle. Tie the window's lifetime strictly to fan-on cycles.
            if self._humidity_presence_runtime_until is not None:
                self._humidity_presence_runtime_until = None

    # ------------------------------------------------------------------
    # D2/D3 helpers — humidity baseline + presence-runtime window
    # ------------------------------------------------------------------

    def _humidity_reset_baseline(self) -> None:
        """Clear EMA + window state — called on fan-off and cap-fire."""
        self._humidity_ema = None
        self._humidity_ema_samples = 0
        self._humidity_ema_warmup_seen_at = None
        self._humidity_ema_last_sample_ts = None
        self._humidity_window.clear()

    def _humidity_update_baseline(
        self,
        humidity: float,
        now: datetime,
        alpha_s: float,
        mode: str,
    ) -> None:
        """Update EMA or window-min baseline with the latest humidity sample."""
        if mode == HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN:
            self._humidity_window.append((now, humidity))
            cutoff = now - timedelta(seconds=alpha_s)
            while self._humidity_window and self._humidity_window[0][0] < cutoff:
                self._humidity_window.popleft()
            if self._humidity_ema_warmup_seen_at is None:
                self._humidity_ema_warmup_seen_at = now
            self._humidity_ema_samples += 1
            return

        # EMA mode (default).
        if self._humidity_ema is None:
            self._humidity_ema = humidity
            self._humidity_ema_warmup_seen_at = now
            self._humidity_ema_last_sample_ts = now
            self._humidity_ema_samples = 1
            return
        dt_s = max(
            (now - self._humidity_ema_last_sample_ts).total_seconds()
            if self._humidity_ema_last_sample_ts is not None
            else 0.0,
            0.0,
        )
        alpha_per_sample = 1.0 - math.exp(-dt_s / max(alpha_s, 1.0))
        alpha_per_sample = max(0.0, min(1.0, alpha_per_sample))
        self._humidity_ema = (
            alpha_per_sample * humidity
            + (1.0 - alpha_per_sample) * self._humidity_ema
        )
        self._humidity_ema_last_sample_ts = now
        self._humidity_ema_samples += 1

    def _humidity_spike_should_fire(
        self,
        humidity: float,
        now: datetime,
        alpha_s: float,
        delta_pct: float,
        mode: str,
    ) -> bool:
        """Return True iff the spike trigger should fire post-warm-up."""
        if self._humidity_ema_warmup_seen_at is None:
            return False
        warmup_required_s = max(alpha_s / 2.0, 1.0)
        elapsed = (now - self._humidity_ema_warmup_seen_at).total_seconds()
        if elapsed < warmup_required_s:
            return False
        if mode == HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN:
            if not self._humidity_window:
                return False
            baseline = min(h for _, h in self._humidity_window)
        else:
            if self._humidity_ema is None:
                return False
            baseline = self._humidity_ema
        return humidity >= baseline + delta_pct

    def _humidity_update_presence_runtime(
        self, now: datetime, room_occupied: bool,
    ) -> None:
        """Track occupied→vacant edge and arm presence-runtime window.

        Reads `_became_occupied_time` from the room coordinator (sole source of
        truth for occupancy duration; coordinator.py:152). Fires only on the
        true edge from occupied→vacant; ignores re-vacate when window already
        armed at a longer occupancy.
        """
        last = self._humidity_last_room_occupied
        self._humidity_last_room_occupied = room_occupied
        if last is None or last == room_occupied:
            return
        if not room_occupied:
            # FIX 1 (bathroom-exhaust intelligence): the coordinator clears
            # `_became_occupied_time` to None earlier in the SAME tick that we
            # observe the occupied→vacant edge (see coordinator.py:1548/1554/
            # 2148-style clears). Reading the live attr here always returned
            # None and the post-vacancy window never armed. Prefer the
            # snapshot the coordinator stashes JUST BEFORE its clear; fall
            # back to the live attr only if the snapshot is missing (e.g.
            # tests that drive the handler directly).
            became = getattr(
                self.coordinator, "_last_occupied_since_for_handler", None,
            )
            if not isinstance(became, datetime):
                became = getattr(self.coordinator, "_became_occupied_time", None)
            if not isinstance(became, datetime):
                return
            # FIX C (second fix-up): consume-and-clear the snapshot so a
            # stale prior-session anchor cannot arm an inflated window
            # on a later, unrelated vacate edge (e.g. after a
            # fan-recheck-release path that left the snapshot populated).
            try:
                self.coordinator._last_occupied_since_for_handler = None
            except Exception:  # noqa: BLE001
                pass
            occupied_seconds = max((now - became).total_seconds(), 0.0)
            base_s = int(self.config.get(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
                DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
            ))
            per_min_s = int(self.config.get(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
                DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
            ))
            cap_s = int(self.config.get(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
                DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
            ))
            occupancy_min = occupied_seconds / 60.0
            post_run_s = min(base_s + per_min_s * occupancy_min, cap_s)
            self._humidity_presence_runtime_until = now + timedelta(seconds=post_run_s)
            _LOGGER.info(
                "humidity_fan_presence_runtime: occupancy=%.1f min -> post-run %ds",
                occupancy_min, int(post_run_s),
            )

    # D8 step 1 — `should_coordinate_with_hvac` was zero-caller dead code
    # (graphify + grep confirmed). Removed in the bathroom-exhaust intelligence
    # cycle alongside the humidity-fan path consolidation. Its sole caller
    # surface (CONF_CLIMATE_ENTITY climate-state polling for "actively
    # heating/cooling") is not reused anywhere; the live `_is_hvac_managing_fans`
    # helper below remains the comfort-fan handshake.

    def _is_hvac_managing_fans(self) -> bool:
        """Check if HVAC coordinator is managing this room's fans.

        v3.18.1: When HVAC coordinator has discovered this room's fans,
        room-level fan control defers to avoid dual-control fighting.
        """
        if not self.config.get(CONF_HVAC_COORDINATION_ENABLED, False):
            return False
        mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if not mgr:
            return False
        hvac = getattr(mgr, 'coordinators', {}).get("hvac")
        if not hvac or not getattr(hvac, 'enabled', False):
            return False
        fan_ctrl = getattr(hvac, 'fan_controller', None)
        if not fan_ctrl:
            return False
        room = self.config.get(CONF_ROOM_NAME, "")
        return room in getattr(fan_ctrl, '_room_fans', {})

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
        
        if now.hour == warning_hour and now.minute >= 55:
            # Dedup: only warn once per hour window
            warning_key = f"{now.date()}-{warning_hour}"
            if self._last_warning_date_hour == warning_key:
                return
            # Check if lights are actually on
            lights = self.config.get(CONF_LIGHTS, [])
            lights_on = any(
                (s := self.hass.states.get(lid)) is not None and s.state == STATE_ON
                for lid in lights
            )
            if lights_on:
                _LOGGER.info("Shared space auto-off warning - flashing lights")
                self._last_warning_date_hour = warning_key
                await self._warning_flash()

    async def _warning_flash(self) -> None:
        """Flash lights briefly to warn of upcoming auto-off."""
        lights = self.config.get(CONF_LIGHTS, [])
        if not lights:
            return

        # Bug Class #4 fix: only flash actual light.* entities (switches don't support brightness)
        actual_lights = [e for e in lights if e.startswith("light.")]
        if not actual_lights:
            return

        try:
            # Quick dim-restore cycle (2 flashes)
            for _ in range(2):
                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_ON,
                    {"entity_id": actual_lights, "brightness": 50},
                    blocking=True,
                )
                await asyncio.sleep(0.3)
                await self._safe_service_call(
                    "light",
                    SERVICE_TURN_ON,
                    {"entity_id": actual_lights, "brightness": 255},
                    blocking=True,
                )
                await asyncio.sleep(0.3)
        except Exception as e:
            _LOGGER.error("Error during warning flash: %s", e)

    async def _shared_space_turn_off_all(self) -> None:
        """Turn off all devices in shared space."""
        # Turn off lights — Bug Class #4 fix: separate domains
        lights = self.config.get(CONF_LIGHTS, [])
        if lights:
            actual_lights = [e for e in lights if e.startswith("light.")]
            switches_as_lights = [e for e in lights if e.startswith("switch.")]
            if actual_lights:
                await self._safe_service_call(
                    "light", SERVICE_TURN_OFF,
                    {"entity_id": actual_lights}, blocking=False,
                )
            if switches_as_lights:
                await self._safe_service_call(
                    "switch", SERVICE_TURN_OFF,
                    {"entity_id": switches_as_lights}, blocking=False,
                )
            _LOGGER.debug("Shared space: turned off %d light(s), %d switch(es)",
                          len(actual_lights), len(switches_as_lights))

        # Turn off fans — Bug Class #4 fix: use homeassistant domain for mixed lists
        fans = self.config.get(CONF_FANS, [])
        if fans:
            await self._safe_service_call(
                "homeassistant",
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
                    "color_temp_kelvin": state.attributes.get("color_temp_kelvin"),
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
                elif original.get("color_temp_kelvin"):
                    service_data["color_temp_kelvin"] = original["color_temp_kelvin"]

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

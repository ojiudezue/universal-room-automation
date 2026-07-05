"""Per-room actuator reconciler — Reconcile-on-Return (v5.8.0, D2).

Re-asserts a room's LIVE-computed desired state for a SINGLE light/fan entity
when it transitions ``unavailable -> available``, so an offline actuator that
comes back doesn't stay stuck stale.

Design: ``docs/planning/PLANNING_reconcile_on_return.md``.

Hard invariants honored here (see plan §2):

* Desired state is ALWAYS recomputed live via ``resolve_desired_state`` —
  NEVER a stored snapshot.
* ZERO synchronous DB writes on the reconcile path (D2.8). Telemetry routes
  through the batched ``coordinator.activity_logger`` + ``set_last_action``
  only. This module imports NO ``database`` DAO. (Bug Class: June-2026
  optimizer write-flood.)
* Per-room cross-entity coalesce window + post-boot grace (D2.7).
* Reconciler owns its OWN ``_unsub_reconciler_listeners`` list, re-armed inside
  the room coordinator's subscription-rebuild hook (D2.9, Bug Class #50).
* Flap detector + quarantine, RAM-only, stability-proven release only — NO
  bare-timer auto-release (D2.11).
* Per-room ``Auto-Recovery`` switch (guard 9) short-circuits the service call
  when OFF but STILL computes ``would_reconcile`` (D2.12).

Scope is lights + fans ONLY. Covers and climate are out of scope (plan §6).

All imports are at module top (Bug Class #34 — no function-local imports of
dispatcher / event helpers).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Set

from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)

from .const import (
    CONF_ENTRY_LIGHT_ACTION,
    CONF_EXIT_LIGHT_ACTION,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_SLEEP_POLICY,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FAN_VACANCY_HOLD,
    CONF_FANS,
    CONF_FLAP_SENSITIVITY,
    CONF_HUMIDITY_FANS,
    CONF_LIGHT_BRIGHTNESS_PCT,
    CONF_LIGHT_CAPABILITIES,
    CONF_LIGHTS,
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHTS,
    CONF_ROOM_NAME,
    DEFAULT_FAN_SLEEP_POLICY,
    DEFAULT_FAN_VACANCY_HOLD,
    DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    DOMAIN,
    FAN_SLEEP_OFF,
    LIGHT_ACTION_NONE,
    LIGHT_ACTION_TURN_OFF,
    LIGHT_ACTION_TURN_ON,
    LIGHT_ACTION_TURN_ON_IF_DARK,
    LIGHT_CAPABILITY_BRIGHTNESS,
    LIGHT_CAPABILITY_FULL,
    RECONCILE_COALESCE_WINDOW_SECONDS,
    RECONCILE_DEBOUNCE_SECONDS,
    RECONCILE_FLAP_SENSITIVITY_BUCKETS,
    RECONCILE_FLAP_STABILITY_SECONDS,
    RECONCILE_FLAP_THRESHOLD,
    RECONCILE_FLAP_WINDOW_SECONDS,
    RECONCILE_MAX_PER_HOUR,
    RECONCILE_POST_BOOT_GRACE_SECONDS,
    RECONCILE_RING_SIZE,
    RECONCILE_UNAVAILABLE_STATES,
    STATE_ILLUMINANCE,
    STATE_OCCUPIED,
    STATE_TEMPERATURE,
)

_LOGGER = logging.getLogger(__name__)

# The actuator config keys this reconciler tracks. The tracked+opinion surface
# MUST mirror the *control* surface of the canonical entry/exit handlers, NOT
# the D1 actuator-VISIBILITY membership (which is broader).
#
# * CONF_ALERT_LIGHTS is EXCLUDED (A-CRIT-1): the canonical
#   _control_lights_entry/_control_lights_exit only ever drive CONF_LIGHTS
#   (+ CONF_NIGHT_LIGHTS in sleep mode). Alert lights are never controlled by
#   the entry/exit path, so reconciling them would fight nothing / assert a
#   state URA never computes.
# * CONF_HUMIDITY_FANS is EXCLUDED (A-CRIT-2): humidity fans are driven solely
#   by handle_humidity_based_fan_control (humidity spike / baseline / min-run
#   state machine) — temperature is irrelevant to them. The resolver has no
#   cheap live re-derivation of that state machine, so reconciling a humidity
#   fan with temperature logic would fight the humidity controller. Defer to
#   the organic humidity path.
_LIGHT_KEYS = (CONF_LIGHTS, CONF_NIGHT_LIGHTS)
_FAN_KEYS = (CONF_FANS,)


@dataclass
class DesiredState:
    """The LIVE-computed desired state for one actuator entity.

    ``state`` is "on" / "off". ``params`` carries brightness / percentage etc.
    ``has_params_to_apply`` forces a service call even when the entity is
    already in ``state`` (e.g. night-brightness must be re-applied).
    """

    state: str
    domain: str
    service: str
    params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    has_params_to_apply: bool = False


class ActuatorReconciler:
    """Per-room reconciler owned by ``UniversalRoomCoordinator``.

    One instance per ROOM config entry. Holds all reconcile state in RAM —
    nothing is persisted (no ``.storage``, no DAO). See plan §3.7.
    """

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.hass = coordinator.hass
        # Own unsub list — SEPARATE from any coordinator list (Bug Class #38,
        # D2.9). Re-armed by the coordinator's rebuild hook.
        self._unsub_reconciler_listeners: List[Callable[[], None]] = []

        # --- debounce + rate-cap (per-entity) ---
        # entity_id -> time.monotonic() float of last accepted reconcile edge.
        self._last_reconcile_edge: Dict[str, float] = {}
        # entity_id -> rolling deque of reconcile timestamps (rate cap).
        self._reconcile_times: Dict[str, Deque[float]] = {}

        # --- coalesce (per-room, single set + single timer) ---
        self._pending_reconcile: Set[str] = set()
        self._coalesce_unsub: Optional[Callable[[], None]] = None

        # --- post-boot grace ---
        # D-HIGH (clause-3 grace leak): the grace window must be active from the
        # INSTANT the reconciler is constructed / first arms its listener, NOT
        # only after a refresh tick observes boot-settle. On the RELOAD path
        # (hass.is_running == True → boot-settle born True) the old code never
        # armed grace, so a mid-flight unavailable→available dispatched a
        # service call with ZERO grace. We stamp a construction-relative age and
        # treat "grace never explicitly armed AND age < grace window" as
        # still-in-grace (see _in_post_boot_grace).
        self._grace_active: bool = False
        self._grace_unsub: Optional[Callable[[], None]] = None
        self._grace_armed_done: bool = False
        self._created_monotonic: float = self._now()

        # --- flap detector + quarantine (RAM-only, D2.11) ---
        self._flap_windows: Dict[str, Deque[float]] = {}
        self._flapping: Dict[str, Dict[str, Any]] = {}
        self._flap_last_transition_ts: Dict[str, float] = {}

        # --- diagnostics (RAM-only) ---
        self._reconciles_today: int = 0
        self._reconciles_reset_date: str = self._today()
        self._recent_reconciles: Deque[dict] = deque(maxlen=RECONCILE_RING_SIZE)
        self._reconcile_debounced_count: int = 0
        self._reconcile_coalesced_count: int = 0
        self._last_reconcile_iso: Optional[str] = None
        self._last_skip_reason: Optional[str] = None
        # entity_id -> desired_state str for currently-SKIPPED entities (D2.12).
        self._would_reconcile: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> float:
        """Monotonic seconds for ALL interval math (debounce / rate-cap / flap).

        Uses ``time.monotonic()`` — a backward wall-clock step (NTP correction,
        DST) must NOT defeat the debounce / rate-cap / flap-window guards
        (A-MED-3). Display timestamps use ``_now_iso`` (wall-clock) separately.
        """
        return time.monotonic()

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _today() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _room_name(self) -> str:
        cfg = self._config()
        return cfg.get(CONF_ROOM_NAME, "Unknown")

    def _config(self) -> Dict[str, Any]:
        entry = self.coordinator.entry
        return {**(entry.data or {}), **(entry.options or {})}

    def _flap_triple(self) -> tuple:
        """Return (threshold, window, stability) for this room.

        Honors the D2.12 ``flap_sensitivity`` named-bucket override; falls back
        to the D2.11 const defaults (== the ``normal`` bucket).
        """
        bucket = self._config().get(CONF_FLAP_SENSITIVITY)
        if bucket and bucket in RECONCILE_FLAP_SENSITIVITY_BUCKETS:
            return RECONCILE_FLAP_SENSITIVITY_BUCKETS[bucket]
        return (
            RECONCILE_FLAP_THRESHOLD,
            RECONCILE_FLAP_WINDOW_SECONDS,
            RECONCILE_FLAP_STABILITY_SECONDS,
        )

    # ------------------------------------------------------------------
    # Actuator enumeration
    # ------------------------------------------------------------------

    def _light_entities(self) -> List[str]:
        cfg = self._config()
        out: List[str] = []
        for key in _LIGHT_KEYS:
            for eid in cfg.get(key) or []:
                if eid and eid not in out:
                    out.append(eid)
        return out

    def _fan_entities(self) -> List[str]:
        cfg = self._config()
        out: List[str] = []
        for key in _FAN_KEYS:
            for eid in cfg.get(key) or []:
                if eid and eid not in out:
                    out.append(eid)
        return out

    def _tracked_entities(self) -> List[str]:
        """Union of light + fan config entities (scope: lights + fans only)."""
        out = list(self._light_entities())
        for eid in self._fan_entities():
            if eid not in out:
                out.append(eid)
        return out

    def _is_night_light(self, entity_id: str) -> bool:
        return entity_id in (self._config().get(CONF_NIGHT_LIGHTS) or [])

    def _is_fan(self, entity_id: str) -> bool:
        return entity_id in self._fan_entities()

    # ------------------------------------------------------------------
    # Lifecycle — listener registration (D2.1 / D2.9)
    # ------------------------------------------------------------------

    def async_register_listeners(self) -> None:
        """Register (or re-register) the single state-change subscription.

        Idempotent: drains any prior listener first (Bug Class #38). Called
        from the room coordinator's ``_update_signal_subscriptions`` rebuild
        hook so an in-place rebuild can't orphan the listener (Bug Class #50,
        D2.9).

        B-MED-3: because this is the re-arm path on the SAME instance, cancel
        any pending coalesce timer and clear the pending set — the tracked
        entity set may have changed, so a stale timer must not fire a resolver
        pass against entities that are no longer tracked.
        """
        self._drain_listeners()
        self._cancel_coalesce_timer()
        self._pending_reconcile.clear()
        entities = self._tracked_entities()
        if not entities:
            _LOGGER.debug(
                "ActuatorReconciler[%s]: no lights/fans configured — "
                "listener not armed",
                self._room_name(),
            )
            return
        try:
            unsub = async_track_state_change_event(
                self.hass, entities, self._handle_state_change,
            )
            self._unsub_reconciler_listeners.append(unsub)
            _LOGGER.info(
                "ActuatorReconciler[%s]: tracking %d actuator(s) for "
                "reconcile-on-return",
                self._room_name(), len(entities),
            )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "ActuatorReconciler[%s]: state-change subscription failed",
                self._room_name(), exc_info=True,
            )

    def _drain_listeners(self) -> None:
        for unsub in self._unsub_reconciler_listeners:
            try:
                unsub()
            except Exception:  # noqa: BLE001 — defensive teardown
                _LOGGER.debug(
                    "ActuatorReconciler[%s]: unsub raised during drain",
                    self._room_name(), exc_info=True,
                )
        self._unsub_reconciler_listeners.clear()

    def _cancel_coalesce_timer(self) -> None:
        """Cancel any armed coalesce timer (idempotent)."""
        if self._coalesce_unsub is not None:
            try:
                self._coalesce_unsub()
            except Exception:  # noqa: BLE001 — defensive teardown
                pass
            self._coalesce_unsub = None

    async def async_teardown(self) -> None:
        """Release the listener + cancel any pending coalesce/grace timers."""
        self._drain_listeners()
        self._cancel_coalesce_timer()
        if self._grace_unsub is not None:
            try:
                self._grace_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._grace_unsub = None
        self._pending_reconcile.clear()

    # ------------------------------------------------------------------
    # Boot-settle grace (D2.7 secondary mechanism)
    # ------------------------------------------------------------------

    def note_boot_settle_released(self) -> None:
        """Arm the post-boot grace window (once).

        Called by the coordinator when ``presence._boot_settle_done`` flips
        True. Available transitions arriving during the grace window are
        ignored as reconcile triggers (but still recorded to the flap window).
        """
        if self._grace_armed_done:
            return
        self._grace_armed_done = True
        self._grace_active = True

        @callback
        def _end_grace(_now=None) -> None:
            self._grace_active = False
            self._grace_unsub = None
            _LOGGER.debug(
                "ActuatorReconciler[%s]: post-boot grace elapsed",
                self._room_name(),
            )

        try:
            self._grace_unsub = async_call_later(
                self.hass, RECONCILE_POST_BOOT_GRACE_SECONDS, _end_grace,
            )
        except Exception:  # noqa: BLE001 — defensive
            self._grace_active = False

    def _in_post_boot_grace(self) -> bool:
        """True while the post-boot grace window suppresses reconcile triggers.

        D-HIGH (clause-3 grace leak): the grace window is EITHER explicitly
        armed (``note_boot_settle_released`` — the cold-boot path, driven off
        the refresh tick that observes ``_boot_settle_done`` flipping True) OR
        implicitly in effect for ``RECONCILE_POST_BOOT_GRACE_SECONDS`` after
        construction. The implicit clause is what covers the RELOAD path, where
        ``hass.is_running == True`` means boot-settle is born True and
        ``note_boot_settle_released`` may fire before the reconciler ever sees a
        real availability edge — leaving the old ``_grace_active``-only guard
        inert. Treating "grace not yet elapsed by construction age" as still
        in grace closes the leak on every reload.
        """
        if self._grace_active:
            return True
        if self._grace_armed_done:
            # Grace was armed and has since elapsed — no longer in grace.
            return False
        # Never explicitly armed yet: implicit construction-age grace.
        return (self._now() - self._created_monotonic) < (
            RECONCILE_POST_BOOT_GRACE_SECONDS
        )

    def _boot_settle_done(self) -> bool:
        """Read the presence coordinator's boot-settle gate (guarded)."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if mgr is None:
                # Test/degraded path: allow an injected flag on the coordinator.
                return bool(getattr(self.coordinator, "_boot_settle_done", True))
            presence = getattr(mgr, "coordinators", {}).get("presence")
            if presence is None:
                return bool(getattr(self.coordinator, "_boot_settle_done", True))
            return bool(getattr(presence, "_boot_settle_done", True))
        except Exception:  # noqa: BLE001 — defensive
            return True

    # ------------------------------------------------------------------
    # Availability-transition handler (plan §3.3 / §3.4)
    # ------------------------------------------------------------------

    @callback
    def _handle_state_change(self, event) -> None:
        """State-change callback — filter for unavailable -> available."""
        try:
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            entity_id = event.data.get("entity_id")
        except Exception:  # noqa: BLE001 — defensive
            return
        if entity_id is None or new_state is None:
            return

        old = old_state.state if old_state is not None else "unavailable"
        new = new_state.state

        # Only care about the unavailable -> available EDGE.
        became_available = (
            old in RECONCILE_UNAVAILABLE_STATES
            and new not in RECONCILE_UNAVAILABLE_STATES
        )
        if not became_available:
            return

        # D2.11: record the availability edge FIRST, BEFORE the guard chain,
        # so a boot-settle-suppressed transition still contributes to the flap
        # window and quarantine can suppress the very same event.
        self._flap_record_transition(entity_id)

        # If already quarantined: update last-transition ts and short-circuit
        # (never dispatch a service call). An availability edge RE-STARTS the
        # stability clock, so release can never happen on an edge — it is
        # single-sourced by the zero-edge poll (check_quarantine_release,
        # D-MED). D2.12: still compute would_reconcile for observability while
        # quarantined.
        if entity_id in self._flapping:
            self._flap_last_transition_ts[entity_id] = self._now()
            self._record_would_reconcile(
                entity_id, self.resolve_desired_state(entity_id)
            )
            self._record_skip(entity_id, "flapping")
            return

        # Fresh breach?
        if self._flap_should_quarantine(entity_id):
            self._flap_enter_quarantine(entity_id)
            self._record_would_reconcile(
                entity_id, self.resolve_desired_state(entity_id)
            )
            self._record_skip(entity_id, "flapping")
            return

        # Schedule the reconcile (through the guard chain + coalesce).
        self._consider_reconcile(entity_id, boot_edge=False)

    def _consider_reconcile(self, entity_id: str, boot_edge: bool) -> None:
        """Run the guard chain for ONE entity; enqueue into coalesce if ok."""
        # D2.12: compute would_reconcile FIRST (visible even if guards fail).
        preview = self.resolve_desired_state(entity_id)
        self._record_would_reconcile(entity_id, preview)

        # Guard 3b: post-boot grace window.
        if self._in_post_boot_grace() and not boot_edge:
            self._record_skip(entity_id, "boot_settle")
            return
        # Guard 3a: boot-settle gate.
        if not self._boot_settle_done():
            self._record_skip(entity_id, "boot_settle")
            return
        # Guard 2: automation enabled (manual_mode OFF).
        try:
            if not self.coordinator._is_automation_enabled():
                self._record_skip(entity_id, "manual_mode")
                return
        except Exception:  # noqa: BLE001 — defensive
            pass
        # Guard 6: active automation intent (occupancy known + data populated).
        if getattr(self.coordinator, "_skip_first_automation", False):
            self._record_skip(entity_id, "no_data")
            return
        if not (self.coordinator.data or {}):
            self._record_skip(entity_id, "no_data")
            return
        # Guard 4: debounce. A-MED-1: the debounce edge is measured from the
        # last ACCEPTED available-edge (§2 clause 4), NOT from the last
        # successful dispatch. Stamp the edge here — after the debounce check
        # passes — so a coalesced or no-op edge still advances the window.
        now = self._now()
        prior = self._last_reconcile_edge.get(entity_id)
        if prior is not None and (now - prior) < RECONCILE_DEBOUNCE_SECONDS:
            self._reconcile_debounced_count += 1
            self._record_skip(entity_id, "debounce")
            return
        self._last_reconcile_edge[entity_id] = now
        # Guard 5: per-hour rate cap.
        if self._rate_capped(entity_id, now):
            self._reconcile_debounced_count += 1
            self._record_skip(entity_id, "rate_cap")
            return
        # Guard 9 (D2.12): Auto-Recovery switch. Short-circuit before any
        # service call, but would_reconcile is already recorded above.
        if not self._auto_recovery_on():
            self._record_skip(entity_id, "auto_recovery_off")
            return

        # Passed guards — enqueue into the per-room coalesce set.
        self._enqueue_pending(entity_id)

    # ------------------------------------------------------------------
    # Coalesce (D2.7 primary mechanism)
    # ------------------------------------------------------------------

    def _enqueue_pending(self, entity_id: str) -> None:
        if self._pending_reconcile:
            # A window is already open — fold this entity in.
            if entity_id not in self._pending_reconcile:
                self._reconcile_coalesced_count += 1
            self._pending_reconcile.add(entity_id)
            return
        # First entity of a new window.
        self._pending_reconcile.add(entity_id)

        @callback
        def _fire(_now=None) -> None:
            # B-MED-2: clear the pending set SYNCHRONOUSLY inside the timer
            # callback and hand the snapshot to the task. If we cleared at the
            # top of the async pass instead, a fresh edge arriving between the
            # timer fire and the task starting would see a non-empty
            # _pending_reconcile, decline to arm a new timer, then be wiped by
            # the pass's clear — silently dropped (double-fire / lost-edge).
            self._coalesce_unsub = None
            snapshot = list(self._pending_reconcile)
            self._pending_reconcile.clear()
            self.hass.async_create_task(self._run_coalesced_pass(snapshot))

        try:
            self._coalesce_unsub = async_call_later(
                self.hass, RECONCILE_COALESCE_WINDOW_SECONDS, _fire,
            )
        except Exception:  # noqa: BLE001 — defensive: run inline
            self._coalesce_unsub = None
            snapshot = list(self._pending_reconcile)
            self._pending_reconcile.clear()
            self.hass.async_create_task(self._run_coalesced_pass(snapshot))

    async def _run_coalesced_pass(self, pending: List[str]) -> None:
        """One resolver pass over the union of the pending set (D2.7).

        ``pending`` is a snapshot captured synchronously in the timer callback
        (B-MED-2) — the live ``_pending_reconcile`` set is already cleared by
        the time this coroutine runs.
        """
        for entity_id in pending:
            try:
                await self._reconcile_one(entity_id)
            except Exception:  # noqa: BLE001 — one bad entity can't kill batch
                _LOGGER.warning(
                    "ActuatorReconciler[%s]: reconcile raised for %s",
                    self._room_name(), entity_id, exc_info=True,
                )

    async def _reconcile_one(self, entity_id: str) -> None:
        desired = self.resolve_desired_state(entity_id)
        if desired is None:
            self._record_skip(entity_id, "no_opinion")
            return
        state = self.hass.states.get(entity_id)
        # Never send to an entity that is still unavailable/unknown.
        if state is None or state.state in RECONCILE_UNAVAILABLE_STATES:
            self._record_skip(entity_id, "no_data")
            return
        current = state.state
        if current == desired.state and not desired.has_params_to_apply:
            _LOGGER.debug(
                "ActuatorReconciler[%s]: reconcile NO-OP %s (already %s)",
                self._room_name(), entity_id, desired.state,
            )
            self._clear_would_reconcile(entity_id)
            return

        payload = {"entity_id": [entity_id], **desired.params}
        await self._safe_service_call(desired.domain, desired.service, payload)

        # Telemetry — BATCHED path only (D2.8). NO synchronous DB write here.
        self._record_reconcile(entity_id, desired)
        self._clear_would_reconcile(entity_id)
        room = self._room_name()
        _LOGGER.info(
            "reconciled %s to %s because %s (room=%s, t=%s)",
            entity_id, desired.state, desired.reason, room, self._now_iso(),
        )
        try:
            self.coordinator.set_last_action(
                "reconcile",
                f"reconciled {entity_id} to {desired.state} ({desired.reason})",
                [entity_id],
            )
        except Exception:  # noqa: BLE001 — telemetry must never break reconcile
            _LOGGER.debug("set_last_action failed", exc_info=True)
        self._log_activity(entity_id, desired)

    async def _safe_service_call(
        self, domain: str, service: str, payload: dict
    ) -> None:
        """Dispatch through the room automation's guarded service call."""
        automation = getattr(self.coordinator, "automation", None)
        if automation is not None and hasattr(automation, "_safe_service_call"):
            await automation._safe_service_call(
                domain, service, payload, blocking=False,
            )
            return
        # Fallback (should not happen in production): direct call.
        await self.hass.services.async_call(
            domain, service, payload, blocking=False,
        )

    def _log_activity(self, entity_id: str, desired: DesiredState) -> None:
        """Route telemetry through the BATCHED activity logger (D2.8)."""
        try:
            activity_logger = self.hass.data.get(DOMAIN, {}).get(
                "activity_logger"
            )
            if not activity_logger:
                return
            self.hass.async_create_task(
                activity_logger.log(
                    coordinator="room",
                    action="reconcile_on_return",
                    description=(
                        f"reconciled {entity_id} to {desired.state} "
                        f"({desired.reason})"
                    ),
                    room=self._room_name(),
                    entity_id=entity_id,
                )
            )
        except Exception:  # noqa: BLE001 — telemetry must never break reconcile
            _LOGGER.debug("activity_logger.log failed", exc_info=True)

    # ------------------------------------------------------------------
    # Intent resolver (plan §3.2, D2.10 branch table)
    # ------------------------------------------------------------------

    def resolve_desired_state(self, entity_id: str) -> Optional[DesiredState]:
        """Compute the LIVE desired state for ONE entity.

        Returns ``None`` when URA has no opinion (light action NONE, no
        occupancy data, exit action not TURN_OFF, HVAC managing fans, etc).
        A ``None`` is only legal where the canonical handler would ALSO not
        act on this entity (D2.10 parity).

        Truth table (lights):
          sleep + entity in night_lights            -> on (night brightness)
          sleep + entity not in night_lights        -> off
          non-sleep + occupied + dark + action in
              {TURN_ON, TURN_ON_IF_DARK}            -> on
          non-sleep + occupied + action == TURN_ON  -> on (no dark gate)
          non-sleep + vacant + exit == TURN_OFF     -> off
          otherwise                                 -> None
        """
        data = self.coordinator.data or {}
        if STATE_OCCUPIED not in data:
            return None  # no occupancy data yet — the ONLY all-None cell

        if entity_id not in self._tracked_entities():
            return None

        if self._is_fan(entity_id):
            return self._resolve_fan(entity_id, data)
        return self._resolve_light(entity_id, data)

    def _automation(self):
        return getattr(self.coordinator, "automation", None)

    def _resolve_light(
        self, entity_id: str, data: Dict[str, Any]
    ) -> Optional[DesiredState]:
        cfg = self._config()
        automation = self._automation()
        occupied = bool(data.get(STATE_OCCUPIED))
        sleep = bool(automation.is_sleep_mode_active()) if automation else False
        night_lights = cfg.get(CONF_NIGHT_LIGHTS) or []

        domain = "switch" if entity_id.startswith("switch.") else "light"

        # SLEEP MODE.
        if sleep and night_lights:
            if entity_id in night_lights:
                params: Dict[str, Any] = {}
                capability = cfg.get(CONF_LIGHT_CAPABILITIES)
                if domain == "light" and capability in (
                    LIGHT_CAPABILITY_BRIGHTNESS, LIGHT_CAPABILITY_FULL,
                ):
                    params["brightness_pct"] = cfg.get(
                        CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
                        DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
                    )
                return DesiredState(
                    state="on", domain=domain, service="turn_on",
                    params=params, reason="sleep_night_light",
                    has_params_to_apply=bool(params),
                )
            # sleep + not a night light -> off.
            return DesiredState(
                state="off", domain=domain, service="turn_off",
                reason="sleep_non_night_off",
            )

        entry_action = cfg.get(CONF_ENTRY_LIGHT_ACTION, LIGHT_ACTION_NONE)
        exit_action = cfg.get(CONF_EXIT_LIGHT_ACTION, LIGHT_ACTION_TURN_OFF)

        if occupied:
            if entry_action == LIGHT_ACTION_NONE:
                return None
            is_dark = False
            if automation is not None:
                is_dark = automation.is_dark(data.get(STATE_ILLUMINANCE))
            should_on = entry_action == LIGHT_ACTION_TURN_ON or (
                entry_action == LIGHT_ACTION_TURN_ON_IF_DARK and is_dark
            )
            if not should_on:
                return None
            params = {}
            capability = cfg.get(CONF_LIGHT_CAPABILITIES)
            if domain == "light" and capability in (
                LIGHT_CAPABILITY_BRIGHTNESS, LIGHT_CAPABILITY_FULL,
            ):
                params["brightness_pct"] = cfg.get(CONF_LIGHT_BRIGHTNESS_PCT, 100)
            return DesiredState(
                state="on", domain=domain, service="turn_on",
                params=params, reason="entry_light_on",
            )

        # Vacant. Canonical _control_lights_exit (automation.py:699) turns off
        # CONF_LIGHTS ONLY — a night_lights-only entity is NEVER turned off on
        # exit by canonical. Mirror that set membership (A-HIGH-1): only assert
        # OFF for an entity that is actually in CONF_LIGHTS.
        regular_lights = cfg.get(CONF_LIGHTS) or []
        if exit_action == LIGHT_ACTION_TURN_OFF and entity_id in regular_lights:
            return DesiredState(
                state="off", domain=domain, service="turn_off",
                reason="exit_light_off",
            )
        return None

    def _resolve_fan(
        self, entity_id: str, data: Dict[str, Any]
    ) -> Optional[DesiredState]:
        cfg = self._config()
        automation = self._automation()

        # A-CRIT-2: humidity fans are driven ONLY by
        # handle_humidity_based_fan_control (humidity spike / baseline /
        # min-runtime state machine). Temperature is irrelevant to them and the
        # resolver has no cheap live re-derivation of that machine — defer to
        # the organic humidity path (return None).
        if entity_id in (cfg.get(CONF_HUMIDITY_FANS) or []):
            return None

        if not cfg.get(CONF_FAN_CONTROL_ENABLED, False):
            return None
        temperature = data.get(STATE_TEMPERATURE)
        if temperature is None:
            return None
        # Defer to HVAC coordinator if it's managing this room's fans.
        if automation is not None and automation._is_hvac_managing_fans():
            return None

        # A-HIGH-2: mirror the canonical handle_temperature_based_fan_control
        # sleep-policy + vacancy-hold. That handler forces fans OFF under
        # FAN_SLEEP_OFF, caps speed under FAN_SLEEP_REDUCE, and HOLDS fans on
        # during the fan_vacancy_hold window. The resolver has no live view of
        # the room's _fan_vacancy_start timer and cannot reproduce the speed
        # cap, so defer to the organic temp-fan path (return None) whenever
        # sleep mode is active OR the room is vacant (the only case where a
        # vacancy-hold window could be in effect). This keeps parity provable:
        # we only assert an opinion on the plain occupied/temperature cells
        # that the canonical handler resolves the same way.
        sleep = bool(automation.is_sleep_mode_active()) if automation else False
        if sleep:
            return None

        occupied = bool(data.get(STATE_OCCUPIED))
        if not occupied:
            # A vacancy-hold window may be in effect (canonical holds fans ON
            # during CONF_FAN_VACANCY_HOLD after occupancy timeout). We cannot
            # tell live — defer to organic.
            _vacancy_hold = cfg.get(
                CONF_FAN_VACANCY_HOLD, DEFAULT_FAN_VACANCY_HOLD
            )
            _sleep_policy = cfg.get(
                CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY
            )
            # Reference the constants so the deferral rationale stays greppable.
            _ = (_vacancy_hold, _sleep_policy, FAN_SLEEP_OFF)
            return None

        threshold = cfg.get(CONF_FAN_TEMP_THRESHOLD, 80)

        domain = "fan" if entity_id.startswith("fan.") else "homeassistant"

        if temperature < threshold:
            return DesiredState(
                state="off", domain=domain, service="turn_off",
                reason="fan_off_vacant_or_cool",
            )
        return DesiredState(
            state="on", domain=domain, service="turn_on",
            reason="fan_on_hot_occupied",
        )

    # ------------------------------------------------------------------
    # Debounce / rate-cap
    # ------------------------------------------------------------------

    def _rate_capped(self, entity_id: str, now: float) -> bool:
        times = self._reconcile_times.setdefault(entity_id, deque())
        while times and (now - times[0]) > 3600.0:
            times.popleft()
        return len(times) >= RECONCILE_MAX_PER_HOUR

    # ------------------------------------------------------------------
    # Flap detector + quarantine (D2.11)
    # ------------------------------------------------------------------

    def _flap_record_transition(self, entity_id: str) -> None:
        now = self._now()
        _threshold, window, _stability = self._flap_triple()
        w = self._flap_windows.setdefault(entity_id, deque())
        w.append(now)
        while w and (now - w[0]) > window:
            w.popleft()
        self._flap_last_transition_ts[entity_id] = now

    def _flap_should_quarantine(self, entity_id: str) -> bool:
        threshold, _window, _stability = self._flap_triple()
        w = self._flap_windows.get(entity_id)
        return bool(w) and len(w) >= threshold

    def _flap_enter_quarantine(self, entity_id: str) -> None:
        w = self._flap_windows.get(entity_id) or deque()
        self._flapping[entity_id] = {
            "since": self._now_iso(),
            "transition_count_at_entry": len(w),
        }
        _LOGGER.info(
            "ActuatorReconciler[%s]: quarantined flapping actuator %s "
            "(%d transitions)",
            self._room_name(), entity_id, len(w),
        )

    def check_quarantine_release(self) -> None:
        """Poll for stability-proven release. Call on a periodic tick.

        A quarantined entity is released iff it has been continuously
        ``available`` for the stability window (zero transitions) AND is
        currently available. On release: purge window, run ONE reconcile pass.
        """
        if not self._flapping:
            return
        now = self._now()
        _threshold, _window, stability = self._flap_triple()
        for entity_id in list(self._flapping.keys()):
            last = self._flap_last_transition_ts.get(entity_id, now)
            if (now - last) < stability:
                continue
            state = self.hass.states.get(entity_id)
            if state is None or state.state in RECONCILE_UNAVAILABLE_STATES:
                continue
            # Released.
            self._flapping.pop(entity_id, None)
            self._flap_windows.pop(entity_id, None)
            _LOGGER.info(
                "ActuatorReconciler[%s]: released %s from quarantine "
                "(stable %.0fs) — running one reconcile pass",
                self._room_name(), entity_id, now - last,
            )
            # Run exactly ONE reconcile pass; then normal behavior resumes.
            self._consider_reconcile(entity_id, boot_edge=False)

    def flapping_entities(self) -> List[dict]:
        """Diagnostic list of currently-quarantined actuators (D2.11)."""
        out: List[dict] = []
        for eid, info in self._flapping.items():
            out.append({
                "entity_id": eid,
                "since_iso": info.get("since"),
                "transition_count_at_entry": info.get(
                    "transition_count_at_entry"
                ),
            })
        return out

    def flapping_detail(self, entity_id: str) -> Optional[dict]:
        """Per-entity flapping detail for the D1 sensor details[] row."""
        info = self._flapping.get(entity_id)
        if info is None:
            return None
        return {
            "transition_count": info.get("transition_count_at_entry"),
            "since": info.get("since"),
        }

    # ------------------------------------------------------------------
    # Auto-Recovery switch (guard 9, D2.12)
    # ------------------------------------------------------------------

    def _auto_recovery_on(self) -> bool:
        """Read the per-room Auto-Recovery switch. Defaults ON if missing."""
        try:
            val = self.coordinator._get_room_switch_state("auto_recovery")
        except Exception:  # noqa: BLE001 — defensive
            return True
        if val is None:
            return True  # default ON
        return bool(val)

    # ------------------------------------------------------------------
    # Diagnostics (RAM-only; D2.4 / D2.12)
    # ------------------------------------------------------------------

    def _roll_day(self) -> None:
        today = self._today()
        if today != self._reconciles_reset_date:
            self._reconciles_reset_date = today
            self._reconciles_today = 0

    def _record_reconcile(self, entity_id: str, desired: DesiredState) -> None:
        self._roll_day()
        now = self._now()
        # Note: _last_reconcile_edge is stamped at edge-accept time in
        # _consider_reconcile (A-MED-1), NOT here.
        self._reconcile_times.setdefault(entity_id, deque()).append(now)
        self._reconciles_today += 1
        self._last_reconcile_iso = self._now_iso()
        self._recent_reconciles.append({
            "entity_id": entity_id,
            "ts_iso": self._last_reconcile_iso,
            "desired_state": desired.state,
            "reason": desired.reason,
            "result": "sent",
        })

    def _record_skip(self, entity_id: str, reason: str) -> None:
        self._last_skip_reason = reason

    def _record_would_reconcile(
        self, entity_id: str, desired: Optional[DesiredState]
    ) -> None:
        if desired is None:
            self._would_reconcile.pop(entity_id, None)
        else:
            self._would_reconcile[entity_id] = desired.state

    def _clear_would_reconcile(self, entity_id: str) -> None:
        self._would_reconcile.pop(entity_id, None)

    # --- public diagnostic getters (read by sensors) ---

    def diagnostics(self) -> dict:
        """Attributes for the D1 UnavailableEntitiesSensor extension (D2.4)."""
        self._roll_day()
        return {
            "reconciles_today": self._reconciles_today,
            "recent_reconciles": list(self._recent_reconciles),
            "reconcile_debounced_count": self._reconcile_debounced_count,
            "reconcile_coalesced_count": self._reconcile_coalesced_count,
            "flapping_entities": self.flapping_entities(),
        }

    def room_sensor_attrs(self) -> dict:
        """Attributes for the D2.12 RoomReconcileSensor."""
        self._roll_day()
        return {
            "last_reconcile": self._last_reconcile_iso,
            "reconciles_today": self._reconciles_today,
            "coalesced_count": self._reconcile_coalesced_count,
            "last_skip_reason": self._last_skip_reason,
            "would_reconcile": dict(self._would_reconcile),
        }

    @property
    def reconciles_today(self) -> int:
        self._roll_day()
        return self._reconciles_today

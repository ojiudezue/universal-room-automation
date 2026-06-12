"""Room-tier fan-recheck state machine (fan-noise Mode-2 mitigation).

When a fan running in a room could be falsely holding mmwave "occupied" in
an empty room, this mechanism pauses the fan, rechecks whether mmwave falls
with airflow stopped, and drops occupancy if the room is actually empty.

Trigger conditions (D1), BLE-tier drop-authorization gate (D1.5), BLE ladder
(D2), state machine (D3), HVAC handshake (D4), cross-rule precedence (D5),
and restart resilience (D6) are detailed in
``docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md``.

Ownership: presence-tier owns this one actuation because the trigger and
verdict consumer (room-tier ``binary_sensor.<room>_occupied``) are both
presence-adjacent. ALL fan writes still delegate through
``hvac_fans.FanController._set_fan_state`` — no new fan write callsite.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_RECHECK_ARM_DELAY_S,
    CONF_FAN_RECHECK_COOLDOWN_S,
    CONF_FAN_RECHECK_ENABLED,
    CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
    CONF_FAN_RECHECK_L2_ALLOWED,
    CONF_FAN_RECHECK_MAX_PER_HOUR,
    CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
    CONF_FAN_RECHECK_SPINDOWN_S,
    CONF_FAN_RECHECK_TRUST_SENSORS_OK,
    CONF_FAN_RECHECK_WINDOW_S,
    CONF_FANS,
    CONF_ROOM_FAN_RECHECK_ENABLED,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    DEFAULT_FAN_RECHECK_ARM_DELAY_S,
    DEFAULT_FAN_RECHECK_COOLDOWN_S,
    DEFAULT_FAN_RECHECK_ENABLED,
    DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
    DEFAULT_FAN_RECHECK_L2_ALLOWED,
    DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
    DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
    DEFAULT_FAN_RECHECK_SPINDOWN_S,
    DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK,
    DEFAULT_FAN_RECHECK_WINDOW_S,
    DEFAULT_RECHECK_FACTOR,
    DEFAULT_ROOM_FAN_RECHECK_ENABLED,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_MEDIA_ROOM,
    ROOM_TYPE_RECHECK_FACTOR,
)
from ._ble_corroboration import trustworthy_persons_in_room
from .house_state import HouseState
from .signals import (
    SIGNAL_FAN_RECHECK_FINISHED,
    SIGNAL_FAN_RECHECK_STARTED,
)

_LOGGER = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_ARMED = "armed"
STATE_PAUSED = "paused"
STATE_RESTORING = "restoring"
STATE_COOLDOWN = "cooldown"

OUTCOME_VACATED = "vacated"
OUTCOME_OCCUPIED_CONFIRMED = "occupied_confirmed"

LAYER_L1 = "L1"
LAYER_L2 = "L2"
LAYER_L3 = "L3"
LAYER_NONE = "none"

# room_type values that demand stronger confirmation (D1.5).
HIGH_STILL_RISK_ROOM_TYPES = frozenset({ROOM_TYPE_BEDROOM, ROOM_TYPE_MEDIA_ROOM})


@dataclass
class _RoomCtx:
    """Per-room runtime context."""

    room_name: str
    entry_id: str
    state: str = STATE_IDLE
    state_entered_at: Optional[datetime] = None
    snapshot: Optional[dict] = None
    attempts: deque = field(default_factory=lambda: deque(maxlen=10))
    last_outcome: Optional[str] = None
    last_attempt_at: Optional[datetime] = None
    ble_ladder_layer: str = LAYER_NONE
    timer_unsub: Optional[Any] = None


class FanRecheckManager:
    """State machine for room-tier fan-pause + clean recheck.

    Construction wires the manager but does no IO. ``async_setup`` rehydrates
    persisted state. ``shutdown`` cancels per-room timers + persists final
    state to DB.
    """

    def __init__(self, hass: HomeAssistant, presence_coord: Any) -> None:
        self.hass = hass
        self._presence = presence_coord
        self._rooms: dict[str, _RoomCtx] = {}
        self._setup_done: bool = False

    # ---- public API --------------------------------------------------------

    async def async_setup(self) -> None:
        """Rehydrate state from DB. Safe to call once after PC setup."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            _LOGGER.debug("FanRecheck: no DB available — starting cold")
            self._setup_done = True
            return
        try:
            rows = await db.get_all_fan_recheck_state()
        except Exception as exc:  # noqa: BLE001 — defensive
            _LOGGER.warning("FanRecheck: rehydrate read failed: %s", exc)
            rows = []
        for row in rows or []:
            self._restore_row(row)
        self._setup_done = True
        _LOGGER.info(
            "FanRecheck: setup complete (rehydrated %d rooms)",
            len(self._rooms),
        )

    async def shutdown(self) -> None:
        """Cancel per-room timers + persist final state."""
        for ctx in list(self._rooms.values()):
            self._cancel_timer(ctx)
            await self._persist(ctx)
        _LOGGER.info("FanRecheck: shutdown — %d rooms persisted", len(self._rooms))

    def on_room_tick(self, room_coord: Any) -> None:
        """Called by PresenceCoordinator inference loop for each room.

        Cheap eligibility check. If eligible AND state is idle, schedule
        the arm transition. The state machine only actuates from the
        timer callbacks — this method is fast and non-blocking.
        """
        if not self._setup_done:
            return
        room_name = self._room_name_of(room_coord)
        if not room_name:
            return
        ctx = self._rooms.get(room_name)
        if ctx is None:
            ctx = _RoomCtx(
                room_name=room_name,
                entry_id=room_coord.entry.entry_id,
            )
            self._rooms[room_name] = ctx

        # In-flight states evaluate their own cancellation conditions inside
        # the timer callbacks; the tick-level path only fires for idle rooms.
        if ctx.state != STATE_IDLE:
            self._evaluate_cancellation_during_tick(ctx, room_coord)
            return

        if not self._is_eligible(ctx, room_coord):
            return

        self.hass.async_create_task(
            self._enter_armed(ctx),
        )

    async def force_restore(self, room_name: str) -> None:
        """Operator escape hatch: immediate restore + cooldown."""
        ctx = self._rooms.get(room_name)
        if ctx is None:
            _LOGGER.info(
                "FanRecheck: force_restore for unknown room %s — no-op",
                room_name,
            )
            return
        if ctx.state in (STATE_IDLE, STATE_COOLDOWN):
            return
        await self._restore(ctx, outcome=OUTCOME_OCCUPIED_CONFIRMED, forced=True)

    def get_room_state(self, room_name: str) -> str:
        ctx = self._rooms.get(room_name)
        return ctx.state if ctx else STATE_IDLE

    def get_room_attrs(self, room_name: str) -> dict[str, Any]:
        ctx = self._rooms.get(room_name)
        if ctx is None:
            return {
                "fan_recheck_state": STATE_IDLE,
                "fan_recheck_last_outcome": None,
                "fan_recheck_last_attempt_iso": None,
                "fan_recheck_ble_ladder_layer": LAYER_NONE,
            }
        return {
            "fan_recheck_state": ctx.state,
            "fan_recheck_last_outcome": ctx.last_outcome,
            "fan_recheck_last_attempt_iso": (
                ctx.last_attempt_at.isoformat() if ctx.last_attempt_at else None
            ),
            "fan_recheck_ble_ladder_layer": ctx.ble_ladder_layer,
        }

    # ---- internals: eligibility -------------------------------------------

    def _is_eligible(self, ctx: _RoomCtx, room_coord: Any) -> bool:
        """Evaluate all 9 trigger conditions (D1)."""
        room_name = ctx.room_name
        merged = self._merged_config(room_coord)
        # The 7 timing knobs live on the CM entry, not the room entry.
        # Read them from the coordinator-tier accessor — anything operator-
        # tuned via the coordinator_presence options step lands here.
        timing = self._timing_config()

        # Master + per-room kill switches.
        master_enabled = self._master_enabled()
        if not master_enabled:
            return False
        if not merged.get(
            CONF_ROOM_FAN_RECHECK_ENABLED, DEFAULT_ROOM_FAN_RECHECK_ENABLED,
        ):
            return False
        # D5: operator fan-control disabled = forbidden zone for us.
        if merged.get(CONF_FAN_CONTROL_ENABLED) is False:
            return False

        # Sleep gate: never pause a fan while the house is asleep.
        # hvac_fans (v4.7.13) deliberately holds bedroom fans ON through sleep
        # despite occupancy bounce; arming a recheck here would pause that fan
        # and fight the keep-on logic.
        #
        # SLEEP-only is intentional and PRESERVED across the 2026-06-11
        # fan-trust state extension: this Mode-2 layer PAUSES the fan to
        # verify presence — exactly the wrong operation during home_night /
        # waking when people are awake, mobile, and would notice a fan
        # pause. The v4.7.13-family trust (hvac_fans + hvac) DOES extend
        # to {home_night, sleep, waking}; this pause-based mechanism
        # explicitly does NOT. See PLANNING_fan_trust_state_extension.md
        # §D-MODE2 and project_v4_7_22_fan_recheck_mode2_live.md.
        house_state = getattr(self._presence, "house_state", "")
        if house_state == HouseState.SLEEP:
            return False

        data = getattr(room_coord, "data", None) or {}
        if not data.get("occupied"):
            return False

        # Condition 2: mmwave-sole AND for N consecutive ticks.
        ticks_required = int(
            timing.get(
                CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
                DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
            )
        )
        recent = []
        if hasattr(room_coord, "recent_occupancy_sources"):
            recent = list(room_coord.recent_occupancy_sources())
        if len(recent) < ticks_required:
            return False
        if any(s != "mmwave" for s in recent[-ticks_required:]):
            return False

        # Condition 3: at least one fan entity AND one is ON.
        fans = merged.get(CONF_FANS) or []
        if isinstance(fans, str):
            fans = [fans]
        fans = [f for f in fans if f]
        if not fans:
            return False
        if not any(self._is_entity_on(f) for f in fans):
            return False

        # Condition 7: boot-settle gate.
        if not getattr(self._presence, "_boot_settle_done", True):
            return False

        # Conditions 8 + 9: EgressManager pause + manual_off_cooldown_until
        # are evaluated by FanController itself; we mirror condition 9 here
        # so we don't even try to schedule a pause for a recently-killed fan.
        if self._fan_in_manual_cooldown(room_name):
            return False

        # Condition 5: rate limit.
        max_per_hour = int(
            timing.get(
                CONF_FAN_RECHECK_MAX_PER_HOUR,
                DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
            )
        )
        if max_per_hour > 0:
            now = dt_util.now()
            self._prune_attempts(ctx, now)
            if len(ctx.attempts) >= max_per_hour:
                return False

        # Condition 4: BLE-tier drop-authorization gate (D1.5).
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord is None:
            return False

        # L1 veto applies in EVERY tier.
        l1_persons = trustworthy_persons_in_room(
            self.hass, person_coord, room_name,
        )
        if l1_persons:
            ctx.ble_ladder_layer = LAYER_L1
            return False

        # Tier classification.
        try:
            ble_tier = int(person_coord.get_ble_tier(room_name))
        except Exception:  # noqa: BLE001
            ble_tier = 0

        l2_hit_adj = self._has_trustworthy_phone_in_adjacent(person_coord, room_name)

        room_type = merged.get(CONF_ROOM_TYPE, "")

        if ble_tier == 1:
            # Tier-1 path. L3 strongest; L2 weak-authorize requires opt-in
            # AND is REJECTED for high-still-risk room_types (D1.5 dial).
            # Zone-aware L3: scan trustworthy phones across ALL rooms in the
            # same zone (not just this room). If _zone_rooms_for returns an
            # empty list (no zone tracker covers this room), fall back to
            # the room itself so we don't get a free L3-vacate from an
            # unconfigured zone (A-M1 + C2 fix).
            try:
                zone_rooms = self._zone_rooms_for(room_name) or [room_name]
                zone_persons = self._trustworthy_persons_in_zone(
                    person_coord, zone_rooms,
                )
            except Exception:  # noqa: BLE001
                zone_persons = []
            if not zone_persons:
                ctx.ble_ladder_layer = LAYER_L3
                return True
            if l2_hit_adj and merged.get(
                CONF_FAN_RECHECK_L2_ALLOWED, DEFAULT_FAN_RECHECK_L2_ALLOWED,
            ):
                if room_type in HIGH_STILL_RISK_ROOM_TYPES:
                    ctx.ble_ladder_layer = LAYER_NONE
                    return False
                ctx.ble_ladder_layer = LAYER_L2
                return True
            ctx.ble_ladder_layer = LAYER_NONE
            return False

        # Tier-2 / Tier-0: positive L2 in adjacent rooms is an UNCONDITIONAL veto.
        if l2_hit_adj:
            ctx.ble_ladder_layer = LAYER_L2
            return False

        # D1.5 high-still-risk guard also applies on the Tier-0/2 path.
        # With CONF_FAN_RECHECK_TRUST_SENSORS_OK defaulting True (v4.7.x),
        # a still napper in a bedroom or media_room would otherwise be
        # eligible to vacate without any BLE-tier protection — match the
        # Tier-1 L2 guard's semantics here. (C1 fix.)
        if room_type in HIGH_STILL_RISK_ROOM_TYPES:
            ctx.ble_ladder_layer = LAYER_NONE
            return False

        # Sensors-only authorize gate.
        if not merged.get(
            CONF_FAN_RECHECK_TRUST_SENSORS_OK,
            DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK,
        ):
            ctx.ble_ladder_layer = LAYER_NONE
            return False

        ctx.ble_ladder_layer = LAYER_NONE
        return True

    # ---- internals: state transitions -------------------------------------

    async def _enter_armed(self, ctx: _RoomCtx) -> None:
        timing = self._timing_config()
        arm_delay = int(
            timing.get(
                CONF_FAN_RECHECK_ARM_DELAY_S,
                DEFAULT_FAN_RECHECK_ARM_DELAY_S,
            )
        )
        ctx.state = STATE_ARMED
        ctx.state_entered_at = dt_util.now()
        await self._persist(ctx)
        async_dispatcher_send(
            self.hass,
            SIGNAL_FAN_RECHECK_STARTED,
            {"room": ctx.room_name, "ble_ladder_layer": ctx.ble_ladder_layer},
        )
        _LOGGER.info(
            "FanRecheck %s: armed (layer=%s, arm_delay=%ds)",
            ctx.room_name, ctx.ble_ladder_layer, arm_delay,
        )

        async def _on_arm_expiry(_now):
            ctx.timer_unsub = None
            await self._on_arm_expired(ctx)

        self._schedule_timer(ctx, arm_delay, _on_arm_expiry)

    async def _on_arm_expired(self, ctx: _RoomCtx) -> None:
        room_coord = self._room_coord_for(ctx.room_name)
        if room_coord is None:
            await self._enter_cooldown(ctx)
            return
        # Cancellation re-evaluation: if conditions no longer hold, abandon.
        if not self._still_armed_eligible(ctx, room_coord):
            await self._enter_cooldown(ctx)
            return
        await self._enter_paused(ctx, room_coord)

    async def _enter_paused(self, ctx: _RoomCtx, room_coord: Any) -> None:
        merged = self._merged_config(room_coord)
        timing = self._timing_config()
        spindown = int(
            timing.get(
                CONF_FAN_RECHECK_SPINDOWN_S,
                DEFAULT_FAN_RECHECK_SPINDOWN_S,
            )
        )
        window = int(
            timing.get(
                CONF_FAN_RECHECK_WINDOW_S,
                DEFAULT_FAN_RECHECK_WINDOW_S,
            )
        )
        # _recheck_factor still reads CONF_ROOM_TYPE from the room entry
        # (per-room property — not coordinator-tier).
        factor = self._recheck_factor(merged)
        window = int(window * factor)
        hvac_suppress = int(
            timing.get(
                CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
                DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
            )
        )

        suppress_until = (
            dt_util.now() + timedelta(seconds=hvac_suppress)
        ).isoformat()

        snapshot = await self._fan_pause(ctx.room_name, suppress_until)
        if snapshot is None:
            _LOGGER.info(
                "FanRecheck %s: no managed fan in FanController — abandoning",
                ctx.room_name,
            )
            await self._enter_cooldown(ctx)
            return

        ctx.snapshot = snapshot
        ctx.state = STATE_PAUSED
        ctx.state_entered_at = dt_util.now()
        ctx.last_attempt_at = ctx.state_entered_at
        ctx.attempts.append(ctx.state_entered_at)
        await self._persist(ctx)
        _LOGGER.info(
            "FanRecheck %s: paused (spindown=%ds, window=%ds)",
            ctx.room_name, spindown, window,
        )

        total_observe = spindown + window
        observe_start = dt_util.now() + timedelta(seconds=spindown)

        async def _on_pause_window_done(_now):
            ctx.timer_unsub = None
            await self._on_pause_window_done(ctx, observe_start)

        self._schedule_timer(ctx, total_observe, _on_pause_window_done)

    async def _on_pause_window_done(
        self, ctx: _RoomCtx, observe_start: datetime,
    ) -> None:
        room_coord = self._room_coord_for(ctx.room_name)
        outcome = OUTCOME_OCCUPIED_CONFIRMED
        if room_coord is not None:
            recent = []
            if hasattr(room_coord, "recent_occupancy_sources"):
                recent = list(room_coord.recent_occupancy_sources())
            data = getattr(room_coord, "data", None) or {}
            # If mmwave (the lone driver pre-pause) no longer drives occupancy
            # after airflow stopped, the fan was the culprit -> vacated.
            current_source = str(data.get("occupancy_source", "none"))
            presence_now = bool(data.get("presence_detected", False))
            if not presence_now and current_source != "mmwave":
                outcome = OUTCOME_VACATED
        await self._restore(ctx, outcome=outcome)

    async def _restore(
        self, ctx: _RoomCtx, outcome: str, forced: bool = False,
    ) -> None:
        ctx.state = STATE_RESTORING
        ctx.state_entered_at = dt_util.now()
        ctx.last_outcome = outcome
        await self._persist(ctx)

        await self._fan_restore(ctx.room_name, ctx.snapshot)

        if outcome == OUTCOME_VACATED and not forced:
            room_coord = self._room_coord_for(ctx.room_name)
            if room_coord is not None and hasattr(
                room_coord, "apply_fan_recheck_release",
            ):
                try:
                    room_coord.apply_fan_recheck_release()
                    room_coord.async_set_updated_data(room_coord.data)
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "FanRecheck %s: apply_fan_recheck_release failed: %s",
                        ctx.room_name, exc,
                    )

        async_dispatcher_send(
            self.hass,
            SIGNAL_FAN_RECHECK_FINISHED,
            {"room": ctx.room_name, "outcome": outcome},
        )
        _LOGGER.info(
            "FanRecheck %s: outcome=%s (forced=%s)",
            ctx.room_name, outcome, forced,
        )
        ctx.snapshot = None
        await self._enter_cooldown(ctx)

    async def _enter_cooldown(self, ctx: _RoomCtx) -> None:
        timing = self._timing_config()
        cooldown_s = int(
            timing.get(
                CONF_FAN_RECHECK_COOLDOWN_S,
                DEFAULT_FAN_RECHECK_COOLDOWN_S,
            )
        )
        ctx.state = STATE_COOLDOWN
        ctx.state_entered_at = dt_util.now()
        await self._persist(ctx)

        async def _on_cooldown_done(_now):
            ctx.timer_unsub = None
            ctx.state = STATE_IDLE
            ctx.state_entered_at = dt_util.now()
            await self._persist(ctx)
            _LOGGER.info("FanRecheck %s: cooldown done -> idle", ctx.room_name)

        self._schedule_timer(ctx, cooldown_s, _on_cooldown_done)

    # ---- cancellation during in-flight states -----------------------------

    def _evaluate_cancellation_during_tick(
        self, ctx: _RoomCtx, room_coord: Any,
    ) -> None:
        """Cancel armed/paused if L1 fires or motion/occupancy returns.

        Called from the per-tick path. Triggers async restore/abandon when
        the trigger preconditions no longer hold mid-flight.
        """
        if ctx.state not in (STATE_ARMED, STATE_PAUSED):
            return
        data = getattr(room_coord, "data", None) or {}
        if data.get("motion_detected"):
            _LOGGER.info(
                "FanRecheck %s: motion detected mid-flight — cancelling",
                ctx.room_name,
            )
            self._cancel_and_restore_async(ctx, OUTCOME_OCCUPIED_CONFIRMED)
            return
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord is not None:
            l1 = trustworthy_persons_in_room(
                self.hass, person_coord, ctx.room_name,
            )
            if l1:
                ctx.ble_ladder_layer = LAYER_L1
                _LOGGER.info(
                    "FanRecheck %s: L1 fired mid-flight — cancelling",
                    ctx.room_name,
                )
                self._cancel_and_restore_async(ctx, OUTCOME_OCCUPIED_CONFIRMED)

    def _cancel_and_restore_async(self, ctx: _RoomCtx, outcome: str) -> None:
        self._cancel_timer(ctx)
        if ctx.state == STATE_ARMED:
            self.hass.async_create_task(self._enter_cooldown(ctx))
        else:
            self.hass.async_create_task(self._restore(ctx, outcome=outcome))

    def _still_armed_eligible(self, ctx: _RoomCtx, room_coord: Any) -> bool:
        """Re-check after ARM_DELAY: master kill, fan still on, mmwave still sole."""
        merged = self._merged_config(room_coord)
        if not self._master_enabled():
            return False
        if not merged.get(
            CONF_ROOM_FAN_RECHECK_ENABLED, DEFAULT_ROOM_FAN_RECHECK_ENABLED,
        ):
            return False
        if merged.get(CONF_FAN_CONTROL_ENABLED) is False:
            return False
        # Sleep can begin during the arm delay — abort before pausing so we
        # never fight the v4.7.13 keep-fans-on-through-sleep logic. SLEEP-only
        # to match the v4.7.13 contract; WAKING is allowed.
        house_state = getattr(self._presence, "house_state", "")
        if house_state == HouseState.SLEEP:
            return False
        data = getattr(room_coord, "data", None) or {}
        if not data.get("occupied"):
            return False
        if str(data.get("occupancy_source", "none")) != "mmwave":
            return False
        fans = merged.get(CONF_FANS) or []
        if isinstance(fans, str):
            fans = [fans]
        fans = [f for f in fans if f]
        if not any(self._is_entity_on(f) for f in fans):
            return False
        return True

    # ---- helpers -----------------------------------------------------------

    def _master_enabled(self) -> bool:
        # Master is per-PresenceCoordinator. We store it under hass.data so
        # the switch entity can flip it at runtime.
        return bool(
            self.hass.data.get(DOMAIN, {}).get(
                "fan_recheck_master_enabled",
                DEFAULT_FAN_RECHECK_ENABLED,
            )
        )

    def _merged_config(self, room_coord: Any) -> dict:
        if room_coord is None or not hasattr(room_coord, "entry"):
            return {}
        return {**room_coord.entry.data, **(room_coord.entry.options or {})}

    def _timing_config(self) -> dict:
        """Return the 7 fan-recheck timing values from the CM entry options.

        The 7 timing knobs live on the CoordinatorManager entry's options
        (same entry the master ``FanRecheckEnabledSwitch`` writes to via
        its ``_mirror_options``; same entry the ``coordinator_presence``
        options step persists). PresenceCoordinator itself does NOT carry
        an ``entry`` attribute, so we resolve the CM entry by entry-type
        sweep — identical pattern to ``FanRecheckEnabledSwitch._mirror_options``.

        Falls through to ``DEFAULT_*`` from const.py for any missing key.
        Best-effort: failures return defaults (the read is non-fatal — the
        state machine continues with default timings).
        """
        out = {
            CONF_FAN_RECHECK_ARM_DELAY_S: DEFAULT_FAN_RECHECK_ARM_DELAY_S,
            CONF_FAN_RECHECK_SPINDOWN_S: DEFAULT_FAN_RECHECK_SPINDOWN_S,
            CONF_FAN_RECHECK_WINDOW_S: DEFAULT_FAN_RECHECK_WINDOW_S,
            CONF_FAN_RECHECK_COOLDOWN_S: DEFAULT_FAN_RECHECK_COOLDOWN_S,
            CONF_FAN_RECHECK_MAX_PER_HOUR: DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
            CONF_FAN_RECHECK_HVAC_SUPPRESS_S: DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
            CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS: (
                DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS
            ),
        }
        try:
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                    continue
                opts = ce.options or {}
                for key in list(out.keys()):
                    if key in opts and opts[key] is not None:
                        out[key] = opts[key]
                break
        except Exception:  # noqa: BLE001 — best-effort read; defaults preserved
            _LOGGER.debug(
                "FanRecheck: timing-config read failed; using DEFAULT_* values",
                exc_info=True,
            )
        return out

    def _is_entity_on(self, entity_id: str) -> bool:
        try:
            state = self.hass.states.get(entity_id)
        except Exception:  # noqa: BLE001
            return False
        return state is not None and state.state == "on"

    def _room_name_of(self, room_coord: Any) -> str:
        try:
            return room_coord.entry.data.get(CONF_ROOM_NAME) or room_coord.entry.data.get("room_name", "")
        except Exception:  # noqa: BLE001
            return ""

    def _room_coord_for(self, room_name: str) -> Optional[Any]:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            if (entry.data.get(CONF_ROOM_NAME) or entry.data.get("room_name")) == room_name:
                return self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        return None

    def _has_trustworthy_phone_in_adjacent(
        self, person_coord: Any, room_name: str,
    ) -> bool:
        try:
            adj = self._presence.get_adjacent_rooms(room_name)
        except Exception:  # noqa: BLE001
            adj = []
        for adj_room in adj:
            persons = trustworthy_persons_in_room(
                self.hass, person_coord, adj_room,
            )
            if persons:
                return True
        return False

    def _trustworthy_persons_in_zone(
        self, person_coord: Any, zone_rooms: list[str],
    ) -> list[str]:
        try:
            from ._ble_corroboration import trustworthy_persons_in_zone
            return trustworthy_persons_in_zone(
                self.hass, person_coord, zone_rooms,
            )
        except Exception:  # noqa: BLE001
            return []

    def _zone_rooms_for(self, room_name: str) -> list[str]:
        try:
            trackers = getattr(self._presence, "zone_trackers", {}) or {}
            for tracker in trackers.values():
                rooms = getattr(tracker, "room_names", []) or []
                if room_name in rooms:
                    return list(rooms)
        except Exception:  # noqa: BLE001
            return []
        return []

    def _recheck_factor(self, merged: dict) -> float:
        room_type = merged.get(CONF_ROOM_TYPE, "")
        return float(
            ROOM_TYPE_RECHECK_FACTOR.get(room_type, DEFAULT_RECHECK_FACTOR)
        )

    def _fan_in_manual_cooldown(self, room_name: str) -> bool:
        try:
            cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            hvac = cm.coordinators.get("hvac") if cm else None
            fan_controller = getattr(hvac, "fan_controller", None) if hvac else None
            if fan_controller is None:
                return False
            room_fan = fan_controller._room_fans.get(room_name)
            if room_fan is None:
                return False
            if not room_fan.manual_off_cooldown_until:
                return False
            # M-A3: parse via dt_util so a tz-naive stored ISO doesn't blow up
            # the tz-aware comparison against dt_util.now(). hvac_fans stores
            # dt_util.now().isoformat() (tz-aware), but be permissive.
            until = dt_util.parse_datetime(room_fan.manual_off_cooldown_until)
            if until is None:
                return False
            if until.tzinfo is None:
                until = dt_util.as_local(until)
            return dt_util.now() < until
        except Exception:  # noqa: BLE001
            return False

    async def _fan_pause(
        self, room_name: str, suppress_until_iso: str,
    ) -> Optional[dict]:
        fan_controller = self._fan_controller()
        if fan_controller is None:
            return None
        try:
            return await fan_controller.pause_for_recheck(
                room_name, suppress_until_iso,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "FanRecheck %s: pause_for_recheck failed: %s",
                room_name, exc,
            )
            return None

    async def _fan_restore(self, room_name: str, snapshot: Optional[dict]) -> None:
        fan_controller = self._fan_controller()
        if fan_controller is None:
            return
        try:
            await fan_controller.restore_after_recheck(room_name, snapshot)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "FanRecheck %s: restore_after_recheck failed: %s",
                room_name, exc,
            )

    def _fan_controller(self) -> Optional[Any]:
        cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if cm is None:
            return None
        hvac = getattr(cm, "coordinators", {}).get("hvac")
        return getattr(hvac, "fan_controller", None) if hvac else None

    def _prune_attempts(self, ctx: _RoomCtx, now: datetime) -> None:
        cutoff = now - timedelta(hours=1)
        while ctx.attempts and ctx.attempts[0] < cutoff:
            ctx.attempts.popleft()

    def _schedule_timer(self, ctx: _RoomCtx, seconds: int, callback) -> None:
        self._cancel_timer(ctx)
        ctx.timer_unsub = async_call_later(self.hass, seconds, callback)

    def _cancel_timer(self, ctx: _RoomCtx) -> None:
        if ctx.timer_unsub is not None:
            try:
                ctx.timer_unsub()
            except Exception:  # noqa: BLE001
                pass
            ctx.timer_unsub = None

    async def _persist(self, ctx: _RoomCtx) -> None:
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            return
        snapshot_json = None
        if ctx.snapshot is not None:
            try:
                snapshot_json = json.dumps(ctx.snapshot, default=str)
            except Exception:  # noqa: BLE001
                snapshot_json = None
        try:
            await db.save_fan_recheck_state({
                "room_id": ctx.entry_id,
                "state": ctx.state,
                "state_entered_at": (
                    ctx.state_entered_at.isoformat()
                    if ctx.state_entered_at else None
                ),
                "snapshot_json": snapshot_json,
                "attempts_in_hour": len(ctx.attempts),
                "last_outcome": ctx.last_outcome,
                "last_attempt_at": (
                    ctx.last_attempt_at.isoformat()
                    if ctx.last_attempt_at else None
                ),
                "ble_ladder_layer": ctx.ble_ladder_layer,
                "last_update_ts": dt_util.now().isoformat(),
            })
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "FanRecheck %s: persist failed (non-fatal): %s",
                ctx.room_name, exc,
            )

    def _restore_row(self, row: dict) -> None:
        """Rehydrate a single DB row per D6 restart resilience table."""
        entry_id = row.get("room_id")
        if not entry_id:
            return
        # Resolve room_name from entry_id.
        room_name = ""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == entry_id:
                room_name = entry.data.get(CONF_ROOM_NAME) or entry.data.get(
                    "room_name", "",
                )
                break
        if not room_name:
            return
        try:
            state = row.get("state") or STATE_IDLE
        except Exception:  # noqa: BLE001
            state = STATE_IDLE
        # ISO-string -> datetime via stdlib fromisoformat; we own the encode
        # path (always isoformat in _persist), so no need for dt_util's
        # broader parser.
        try:
            entered = (
                datetime.fromisoformat(row["state_entered_at"])
                if row.get("state_entered_at") else None
            )
        except Exception:  # noqa: BLE001
            entered = None
        snapshot = None
        if row.get("snapshot_json"):
            try:
                snapshot = json.loads(row["snapshot_json"])
            except Exception:  # noqa: BLE001
                snapshot = None
        ctx = _RoomCtx(
            room_name=room_name,
            entry_id=entry_id,
            state=STATE_IDLE,
            state_entered_at=entered,
            snapshot=snapshot,
            last_outcome=row.get("last_outcome"),
            ble_ladder_layer=row.get("ble_ladder_layer") or LAYER_NONE,
        )
        try:
            last_attempt = row.get("last_attempt_at")
            ctx.last_attempt_at = (
                datetime.fromisoformat(last_attempt) if last_attempt else None
            )
        except Exception:  # noqa: BLE001
            ctx.last_attempt_at = None
        self._rooms[room_name] = ctx

        # D6 restart-resilience matrix.
        now = dt_util.now()
        if state == STATE_PAUSED and entered is not None:
            window = DEFAULT_FAN_RECHECK_WINDOW_S * 2
            if (now - entered).total_seconds() < window:
                self.hass.async_create_task(
                    self._restore(ctx, outcome=OUTCOME_OCCUPIED_CONFIRMED),
                )
                return
            _LOGGER.warning(
                "FanRecheck %s: rehydrate paused state too old — idle",
                room_name,
            )
            ctx.state = STATE_IDLE
            ctx.snapshot = None
            return
        if state == STATE_RESTORING:
            _LOGGER.info(
                "FanRecheck %s: rehydrate restoring -> idle (restore skipped)",
                room_name,
            )
            ctx.state = STATE_IDLE
            ctx.snapshot = None
            return
        if state == STATE_COOLDOWN and entered is not None:
            elapsed = (now - entered).total_seconds()
            remaining = max(0, DEFAULT_FAN_RECHECK_COOLDOWN_S - int(elapsed))
            ctx.state = STATE_COOLDOWN
            if remaining > 0:
                async def _on_cd_done(_n, _ctx=ctx):
                    _ctx.timer_unsub = None
                    _ctx.state = STATE_IDLE
                    _ctx.state_entered_at = dt_util.now()
                    await self._persist(_ctx)
                self._schedule_timer(ctx, remaining, _on_cd_done)
            else:
                ctx.state = STATE_IDLE
            return
        if state == STATE_ARMED:
            ctx.state = STATE_IDLE
            return
        ctx.state = STATE_IDLE

"""EgressManager — v4.7.8 Egress Window HVAC Pause.

Sibling of OverrideArrester. Drives the 5-state machine:
  idle -> counting -> paused -> resume_countdown -> idle
  paused -> cooldown (manual user override) -> idle (on expiry)

Called once per HVAC decision tick under `_decision_cycle_lock`.

Persistence: every state transition writes to the `egress_state` DB table
(see database.py). On HA restart, `async_rehydrate_from_db` runs in
`HVACCoordinator.async_setup` BEFORE the periodic timer is registered, and
sets `_rehydrate_done=True`. The first tick early-returns until rehydrate
finishes (Bug Class #14 — first-tick post-restart must rehydrate before
action).

Bug-class mitigations:
- #11: dt_util.now() consistently for comparisons; ISO via .isoformat() on
  tz-aware datetimes.
- #14: user-tunable scalars (threshold_s, resume_delay_s, manual_grace_s,
  cooldown_s, enabled) snapshotted at top of async_tick; live setters write
  for the next tick.
- #19: no fire-and-forget hass.async_create_task in this module; service
  calls are awaited under the held lock.
- #21: rehydrate parses ISO strings via dt_util.parse_datetime, never
  datetime.fromisoformat.
- #23: NM dispatch gated on `not hvac.observation_mode` at the dispatch
  site, not just at the handler.
- #42: NM signal dispatch is a direct method call, not a wrapped lambda.
- #45: state lives on instance attributes (no lambda closure captures).
- #46: no async_update_entry from this module — the `is_egress_window`
  flag is read lazily by ZoneManager.update_room_conditions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from .hvac_setpoint import emit_set_preset_mode
from .hvac_const import (
    EGRESS_NM_EVENT_PAUSED,
    EGRESS_NM_EVENT_RESUMED,
    EGRESS_STATE_COOLDOWN,
    EGRESS_STATE_COUNTING,
    EGRESS_STATE_IDLE,
    EGRESS_STATE_PAUSED,
    EGRESS_STATE_RESUME_COUNTDOWN,
    HVAC_EGRESS_MANUAL_COOLDOWN_S,
    HVAC_EGRESS_MANUAL_OVERRIDE_GRACE_S,
    HVAC_EGRESS_RESUME_DELAY_MIN_MAX,
    HVAC_EGRESS_RESUME_DELAY_MIN_MIN,
    HVAC_EGRESS_THRESHOLD_MIN_MAX,
    HVAC_EGRESS_THRESHOLD_MIN_MIN,
)

_LOGGER = logging.getLogger(__name__)


class EgressManager:
    """Egress-window HVAC pause manager.

    Single instance per HVACCoordinator. Drives the per-canonical-zone
    state machine and persists every transition to the `egress_state`
    DB table.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager,
        db=None,
        threshold_min: int = 3,
        resume_delay_min: int = 1,
        enabled: bool = True,
    ) -> None:
        self._hass = hass
        self._zone_manager = zone_manager
        self._db = db  # URADatabase ref; may be None during early setup
        self._enabled = bool(enabled)
        self._threshold_min = int(threshold_min)
        self._resume_delay_min = int(resume_delay_min)
        # Per-canonical-zone runtime state. Rehydrated from DB on startup.
        # zone_id -> {mode, preset, paused_at, triggered_by_room, thermostat}
        self._paused_by_egress: dict[str, dict[str, Any]] = {}
        # zone_id -> tz-aware datetime when the egress window first observed open
        self._egress_first_open_at: dict[str, datetime] = {}
        # zone_id -> tz-aware datetime when all egress windows first observed closed
        self._egress_first_closed_at: dict[str, datetime] = {}
        # zone_id -> expiry datetime (tz-aware)
        self._cooldowns: dict[str, datetime] = {}
        # NM dedup: (zone_id, event_type) -> date.isoformat() last emitted.
        # RESTART-SAFETY-DOCTRINE-1 F16 — declared. restart: RESET WITH REASON.
        #   Reason: this is a dedupe dict, not a scalar counter — it does NOT
        #   fit the tranche-1 DailyCounter(name, persist, reason) primitive
        #   which is int-only. The audit recommends PERSIST (to prevent one
        #   duplicate NM per (zone,event) per restart in the same local day),
        #   which requires a Store instance plus a hook into the HVAC
        #   coordinator's setup/teardown lifecycle (HVACEgress has no
        #   equivalent hooks today). Impact is bounded: at most one duplicate
        #   emit per (zone,event) per restart, and the measured median restart
        #   interval (5.55h) means the same-day dedupe survives most of the
        #   duplicate window in practice. Deferred to the persist=True
        #   follow-up cycle (RESTART-SAFETY-DOCTRINE-2) alongside F8
        #   (`OverrideArrester.override_count_today`, arrester-owned).
        self._nm_emitted_today: dict[tuple[str, str], str] = {}
        # Rehydrate gate — first tick MUST early-return until True.
        self._rehydrate_done: bool = False
        # v4.7.8 fix-up B-H2 / B-H3 (Bug Class #14 / #5): the master switch
        # and both Numbers use deferred RestoreEntity (state arrives via
        # SIGNAL_HVAC_COORDINATOR_READY or async_added_to_hass which can
        # race with the initial decision cycle). Tracks which deferred
        # restores are still pending; first tick early-returns until the
        # set is empty. Items: "enabled", "threshold_min", "resume_delay_min".
        self._initial_restore_pending: set[str] = {
            "enabled",
            "threshold_min",
            "resume_delay_min",
        }
        # Owning coordinator (set by HVACCoordinator after instantiation);
        # used to read observation_mode for Bug Class #23 NM gating.
        self._hvac_coord = None

    # ------------------------------------------------------------------
    # Public properties + setters (called by switch / numbers)
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        # v4.7.8 fix-up B-H3: deferred-restore landed for the master switch.
        self._initial_restore_pending.discard("enabled")
        _LOGGER.info("EgressManager: enabled=%s", self._enabled)

    @property
    def threshold_min(self) -> int:
        return self._threshold_min

    def set_threshold_min(self, value: int) -> None:
        v = int(value)
        v = max(HVAC_EGRESS_THRESHOLD_MIN_MIN, min(HVAC_EGRESS_THRESHOLD_MIN_MAX, v))
        if v != self._threshold_min:
            self._threshold_min = v
            _LOGGER.info("EgressManager: threshold_min=%d", v)
        # v4.7.8 fix-up B-H2: deferred-restore landed for the Number.
        # Discard even when value didn't change (the restore did happen).
        self._initial_restore_pending.discard("threshold_min")

    @property
    def resume_delay_min(self) -> int:
        return self._resume_delay_min

    def set_resume_delay_min(self, value: int) -> None:
        v = int(value)
        v = max(HVAC_EGRESS_RESUME_DELAY_MIN_MIN, min(HVAC_EGRESS_RESUME_DELAY_MIN_MAX, v))
        if v != self._resume_delay_min:
            self._resume_delay_min = v
            _LOGGER.info("EgressManager: resume_delay_min=%d", v)
        # v4.7.8 fix-up B-H2: deferred-restore landed for the Number.
        self._initial_restore_pending.discard("resume_delay_min")

    @property
    def rehydrate_done(self) -> bool:
        return self._rehydrate_done

    @property
    def initial_restore_pending(self) -> bool:
        """v4.7.8 fix-up B-H2/B-H3: True iff deferred restores from at least
        one of (master switch / threshold Number / resume_delay Number) have
        not yet landed. While True, async_tick must early-return so the first
        decision cycle doesn't act on seeded defaults that the user has
        already overridden via RestoreEntity.
        """
        return bool(self._initial_restore_pending)

    def force_release_initial_restore_gate(self) -> None:
        """v4.7.8 fix-up B-H2/B-H3: emergency release of the deferred-restore
        gate. Called after a bounded wait if some entity never restored
        (e.g., user deleted the switch entity). Without this, async_tick
        would never fire after restart.
        """
        if self._initial_restore_pending:
            _LOGGER.info(
                "EgressManager: forcing initial-restore gate release "
                "(still pending=%s) — using seeded defaults",
                sorted(self._initial_restore_pending),
            )
            self._initial_restore_pending.clear()

    def set_database(self, db) -> None:
        """Late wire of DB reference if not provided at __init__."""
        self._db = db

    def set_hvac_coord(self, hvac_coord) -> None:
        """Owning coordinator (for observation_mode read)."""
        self._hvac_coord = hvac_coord

    # ------------------------------------------------------------------
    # Public read surfaces (sensors)
    # ------------------------------------------------------------------

    def zone_aggregate(self, zone_id: str) -> bool:
        """Return True iff any egress room in the zone is open past threshold."""
        return zone_id in self._paused_by_egress or zone_id in self._egress_first_open_at

    def state_label(self, zone_id: str) -> str:
        """Return current state-machine label for a canonical zone."""
        if zone_id in self._cooldowns:
            if dt_util.now() < self._cooldowns[zone_id]:
                return EGRESS_STATE_COOLDOWN
        if zone_id in self._paused_by_egress:
            if zone_id in self._egress_first_closed_at:
                return EGRESS_STATE_RESUME_COUNTDOWN
            return EGRESS_STATE_PAUSED
        if zone_id in self._egress_first_open_at:
            return EGRESS_STATE_COUNTING
        return EGRESS_STATE_IDLE

    def paused_zones(self) -> list[dict[str, Any]]:
        """Return list of currently paused zones with metadata."""
        out: list[dict[str, Any]] = []
        for zone_id, info in self._paused_by_egress.items():
            paused_at = info.get("paused_at")
            out.append({
                "zone_id": zone_id,
                "paused_at": paused_at.isoformat() if isinstance(paused_at, datetime) else paused_at,
                "triggered_by_room": info.get("triggered_by_room"),
                "saved_mode": info.get("mode"),
                "saved_preset": info.get("preset"),
            })
        return out

    def get_cooldowns(self) -> dict[str, str]:
        """Return {zone_id: cooldown_expires_at_iso}."""
        return {
            zid: expires.isoformat() if isinstance(expires, datetime) else str(expires)
            for zid, expires in self._cooldowns.items()
        }

    def get_zone_info(self, zone_id: str) -> dict[str, Any]:
        """Return per-zone attribute dict for HVACZoneEgressStateSensor."""
        info = self._paused_by_egress.get(zone_id, {})
        paused_at = info.get("paused_at")
        cooldown = self._cooldowns.get(zone_id)
        first_open = self._egress_first_open_at.get(zone_id)
        first_closed = self._egress_first_closed_at.get(zone_id)
        return {
            "paused_at": paused_at.isoformat() if isinstance(paused_at, datetime) else None,
            "triggered_by_room": info.get("triggered_by_room"),
            "saved_mode": info.get("mode"),
            "saved_preset": info.get("preset"),
            "cooldown_expires_at": cooldown.isoformat() if isinstance(cooldown, datetime) else None,
            "counting_since": first_open.isoformat() if isinstance(first_open, datetime) else None,
            "resume_countdown_since": first_closed.isoformat() if isinstance(first_closed, datetime) else None,
            "threshold_min": self._threshold_min,
            "resume_delay_min": self._resume_delay_min,
        }

    def is_paused(self, zone_id: str) -> bool:
        """True iff this zone is currently in URA-driven egress pause."""
        return zone_id in self._paused_by_egress

    # ------------------------------------------------------------------
    # Lifecycle: rehydrate from DB
    # ------------------------------------------------------------------

    async def async_rehydrate_from_db(self) -> None:
        """Restore in-memory state from the egress_state table.

        MUST be awaited from HVACCoordinator.async_setup BEFORE the
        periodic decision-cycle timer is registered. Sets the
        `_rehydrate_done` flag so `async_tick` knows it's safe to act.
        """
        if self._db is None:
            _LOGGER.info("EgressManager: rehydrate skipped — no DB ref")
            self._rehydrate_done = True
            return
        try:
            rows = await self._db.get_all_egress_state()
        except Exception:
            _LOGGER.warning("EgressManager: rehydrate read failed", exc_info=True)
            self._rehydrate_done = True
            return

        paused_n = counting_n = countdown_n = cooldown_n = 0
        for row in rows or []:
            zone_id = row.get("zone_id")
            if not zone_id:
                continue
            state = row.get("state") or ""
            # Bug Class #21: always parse via dt_util.parse_datetime
            first_open = dt_util.parse_datetime(row.get("first_open_at") or "")
            first_closed = dt_util.parse_datetime(row.get("first_closed_at") or "")
            paused_at = dt_util.parse_datetime(row.get("paused_at") or "")
            cooldown_expires = dt_util.parse_datetime(row.get("cooldown_expires_at") or "")
            saved_mode = row.get("saved_hvac_mode") or ""
            saved_preset = row.get("saved_preset_mode") or ""
            triggered = row.get("triggered_by_room") or ""
            thermostat = row.get("thermostat_entity") or ""

            if state == EGRESS_STATE_PAUSED:
                self._paused_by_egress[zone_id] = {
                    "mode": saved_mode,
                    "preset": saved_preset,
                    "paused_at": paused_at or dt_util.now(),
                    "triggered_by_room": triggered,
                    "thermostat": thermostat,
                }
                paused_n += 1
            elif state == EGRESS_STATE_COUNTING:
                if first_open is not None:
                    self._egress_first_open_at[zone_id] = first_open
                else:
                    # Conservative fallback — start fresh count.
                    self._egress_first_open_at[zone_id] = dt_util.now()
                counting_n += 1
            elif state == EGRESS_STATE_RESUME_COUNTDOWN:
                self._paused_by_egress[zone_id] = {
                    "mode": saved_mode,
                    "preset": saved_preset,
                    "paused_at": paused_at or dt_util.now(),
                    "triggered_by_room": triggered,
                    "thermostat": thermostat,
                }
                if first_closed is not None:
                    self._egress_first_closed_at[zone_id] = first_closed
                else:
                    self._egress_first_closed_at[zone_id] = dt_util.now()
                countdown_n += 1
            elif state == EGRESS_STATE_COOLDOWN:
                if cooldown_expires is not None:
                    self._cooldowns[zone_id] = cooldown_expires
                cooldown_n += 1

        _LOGGER.info(
            "EgressManager: rehydrated %d zones (%d paused, %d counting, "
            "%d resume_countdown, %d cooldown)",
            paused_n + counting_n + countdown_n + cooldown_n,
            paused_n, counting_n, countdown_n, cooldown_n,
        )
        self._rehydrate_done = True

    # ------------------------------------------------------------------
    # Decision tick
    # ------------------------------------------------------------------

    async def async_tick(self, now: datetime | None = None) -> None:
        """One pass through the state machine for every canonical HVAC zone.

        Called inside HVACCoordinator._decision_cycle_lock.
        """
        if not self._rehydrate_done:
            # First tick post-restart — wait for rehydrate.
            _LOGGER.debug("EgressManager: tick skipped — rehydrate not done")
            return

        # v4.7.8 fix-up B-H2 / B-H3: gate first tick on deferred
        # RestoreEntity callbacks for the master switch + 2 Numbers. Without
        # this, the initial cycle uses seeded defaults instead of the user's
        # saved values (e.g., threshold 5 → ticks at 3 for one cycle). The
        # bound timeout below (force release) is set in HVACCoordinator's
        # setup so the second tick at +5min never silently stalls.
        if self._initial_restore_pending:
            _LOGGER.debug(
                "EgressManager: tick skipped — initial restore pending=%s",
                sorted(self._initial_restore_pending),
            )
            return

        now = now or dt_util.now()

        # Bug Class #14: snapshot user-tunable scalars at top of tick.
        threshold_s = int(self._threshold_min) * 60
        resume_delay_s = int(self._resume_delay_min) * 60
        manual_grace_s = HVAC_EGRESS_MANUAL_OVERRIDE_GRACE_S
        cooldown_s = HVAC_EGRESS_MANUAL_COOLDOWN_S
        enabled = bool(self._enabled)

        # Sweep expired cooldowns (state-machine consistency).
        expired = [zid for zid, exp in self._cooldowns.items() if now >= exp]
        for zid in expired:
            self._cooldowns.pop(zid, None)
            await self._db_clear(zid)
            _LOGGER.info("EgressManager: cooldown expired for zone %s", zid)

        # Build canonical zones list
        try:
            from .hvac_zones import iter_canonical_hvac_zones
            zones = iter_canonical_hvac_zones(self._hass)
        except Exception:
            _LOGGER.debug("EgressManager: canonical zone iteration failed", exc_info=True)
            return

        zones_by_id = self._zone_manager.zones

        for z in zones:
            zone_id = z.get("zone_id")
            if not zone_id:
                continue
            zone_state = zones_by_id.get(zone_id)
            if zone_state is None:
                # Discovery race — skip this zone this tick.
                continue

            # ----- Aggregate egress-window state across rooms -----
            any_egress_open = False
            triggered_room: str | None = None
            for rc in zone_state.room_conditions:
                if not rc.is_egress_window:
                    continue
                if rc.window_state == "on":
                    any_egress_open = True
                    if triggered_room is None:
                        triggered_room = rc.room_name

            # ----- Disabled path -----
            if not enabled:
                # Clear counters but DO NOT auto-resume an already-paused zone.
                if zone_id in self._egress_first_open_at:
                    self._egress_first_open_at.pop(zone_id, None)
                    # v4.7.8 fix-up C-L3 / A-LOW-2: also clear the stale
                    # `counting` DB row. Without this, post-restart
                    # rehydrate restores the counter even though the
                    # feature is disabled — the next tick clears it in
                    # memory but the DB row persists until the prune.
                    await self._db_clear(zone_id)
                if (
                    zone_id in self._egress_first_closed_at
                    and zone_id not in self._paused_by_egress
                ):
                    self._egress_first_closed_at.pop(zone_id, None)
                continue

            # ----- Cooldown path -----
            if zone_id in self._cooldowns and now < self._cooldowns[zone_id]:
                continue

            # ----- Manual-override detection (zone is paused) -----
            if zone_id in self._paused_by_egress:
                paused_at = self._paused_by_egress[zone_id].get("paused_at")
                thermostat = (
                    self._paused_by_egress[zone_id].get("thermostat")
                    or zone_state.climate_entity
                )
                current_mode = None
                try:
                    st = self._hass.states.get(thermostat)
                    if st is not None:
                        current_mode = st.state
                except Exception:
                    current_mode = None
                if (
                    current_mode is not None
                    and current_mode != "off"
                    and isinstance(paused_at, datetime)
                    and (now - paused_at).total_seconds() > manual_grace_s
                ):
                    self._paused_by_egress.pop(zone_id, None)
                    self._egress_first_closed_at.pop(zone_id, None)
                    cooldown_expiry = now + timedelta(seconds=cooldown_s)
                    self._cooldowns[zone_id] = cooldown_expiry
                    await self._db_clear(zone_id)
                    await self._db_save_cooldown(zone_id, cooldown_expiry, now)
                    _LOGGER.info(
                        "EgressManager: manual override detected for zone %s "
                        "(mode=%s) — engaging 1h cooldown",
                        zone_id, current_mode,
                    )
                    continue

            # ----- Pause path (zone NOT yet paused) -----
            if zone_id not in self._paused_by_egress:
                if any_egress_open:
                    if zone_id not in self._egress_first_open_at:
                        self._egress_first_open_at[zone_id] = now
                        await self._db_save_counting(zone_id, now)
                    elapsed = (now - self._egress_first_open_at[zone_id]).total_seconds()
                    if elapsed >= threshold_s:
                        await self._engage_pause(
                            zone_id=zone_id,
                            zone_state=zone_state,
                            triggered_room=triggered_room or "",
                            now=now,
                        )
                else:
                    if zone_id in self._egress_first_open_at:
                        self._egress_first_open_at.pop(zone_id, None)
                        await self._db_clear(zone_id)
                continue

            # ----- Resume path (zone IS paused) -----
            if any_egress_open:
                # v4.7.8 fix-up A-LOW: roll triggered_by_room forward in
                # memory when the first-trigger room closes but a sibling
                # is still open. Previously the in-memory `triggered_room`
                # already reflected the new trigger but the persisted info
                # dict kept the original; sensors / paused_zones() now
                # surface the current trigger.
                if triggered_room:
                    info = self._paused_by_egress.get(zone_id, {})
                    if info.get("triggered_by_room") != triggered_room:
                        info["triggered_by_room"] = triggered_room
                if zone_id in self._egress_first_closed_at:
                    self._egress_first_closed_at.pop(zone_id, None)
                    await self._db_save_paused(zone_id, now)
            else:
                if zone_id not in self._egress_first_closed_at:
                    self._egress_first_closed_at[zone_id] = now
                    await self._db_save_resume_countdown(zone_id, now)
                elapsed = (now - self._egress_first_closed_at[zone_id]).total_seconds()
                if elapsed >= resume_delay_s:
                    await self._engage_resume(
                        zone_id=zone_id,
                        zone_state=zone_state,
                        now=now,
                    )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    async def _engage_pause(
        self,
        *,
        zone_id: str,
        zone_state,
        triggered_room: str,
        now: datetime,
    ) -> None:
        """Snapshot mode+preset and dispatch set_hvac_mode: off."""
        thermostat = zone_state.climate_entity
        if not thermostat:
            return
        prior_mode = ""
        # v4.7.8 fix-up B-M5: distinguish "preset attribute missing" (None)
        # from "preset explicitly empty". On resume, None means we have no
        # information so we don't dispatch set_preset_mode; explicit empty
        # also skips dispatch. Sentinel-free via None vs "" — both currently
        # treated identically downstream (saved_preset falsy → skip), but
        # we now log the difference.
        prior_preset: str | None = None
        try:
            st = self._hass.states.get(thermostat)
            if st is not None:
                prior_mode = st.state or ""
                _pm = st.attributes.get("preset_mode")
                prior_preset = _pm if isinstance(_pm, str) and _pm else None
        except Exception:
            _LOGGER.debug(
                "EgressManager: state read failed for %s", thermostat, exc_info=True,
            )

        if prior_mode == "off":
            _LOGGER.debug(
                "EgressManager: zone %s thermostat %s already off — no pause",
                zone_id, thermostat,
            )
            self._egress_first_open_at.pop(zone_id, None)
            await self._db_clear(zone_id)
            return

        try:
            # ARREST-COMFORT-1 D2-LOW-3 fix-up (2026-08-10): on some
            # thermostat firmware (notably Ecobee), a set_hvac_mode
            # transition can cause the device to re-emit its preset
            # defaults over a manual setpoint on the next tick — the
            # DPM apply / arrester paths cover the resulting write via
            # emit_* chokepoints. The egress pause itself is deliberately
            # UNGATED by comfort-delay grace (safety > comfort during an
            # open egress window); pending live evidence that this
            # firmware quirk actually stomps an operator hold, we do not
            # add a gate here. Revisit if operator observes a manual
            # setpoint being overridden immediately after an egress
            # pause on a comfort-qualified zone.
            await self._hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": thermostat, "hvac_mode": "off"},
                blocking=True,
            )
        except Exception:
            _LOGGER.warning(
                "EgressManager: set_hvac_mode failed for %s — keeping counter",
                thermostat, exc_info=True,
            )
            return

        self._paused_by_egress[zone_id] = {
            "mode": prior_mode,
            "preset": prior_preset,
            "paused_at": now,
            "triggered_by_room": triggered_room,
            "thermostat": thermostat,
        }
        self._egress_first_open_at.pop(zone_id, None)
        self._egress_first_closed_at.pop(zone_id, None)
        await self._db_save_paused_full(
            zone_id=zone_id,
            saved_mode=prior_mode,
            saved_preset=prior_preset,
            paused_at=now,
            triggered_by_room=triggered_room,
            thermostat=thermostat,
        )
        _LOGGER.info(
            "EgressManager: PAUSED zone %s (thermostat=%s, prior_mode=%s, "
            "prior_preset=%s, triggered_by=%s)",
            zone_id, thermostat, prior_mode, prior_preset, triggered_room,
        )
        await self._maybe_dispatch_nm(
            zone_id=zone_id,
            event=EGRESS_NM_EVENT_PAUSED,
            zone_name=zone_state.zone_name,
            triggered_room=triggered_room,
            now=now,
        )

    async def _engage_resume(
        self,
        *,
        zone_id: str,
        zone_state,
        now: datetime,
    ) -> None:
        """Restore saved mode + preset and clear pause state."""
        info = self._paused_by_egress.get(zone_id, {})
        thermostat = info.get("thermostat") or zone_state.climate_entity
        saved_mode = info.get("mode") or ""
        saved_preset = info.get("preset") or ""
        if not thermostat or not saved_mode:
            # v4.7.8 fix-up A-MED-4: WARN log on silent clear. The next
            # decision tick's "leave-off-restore" guard (hvac.py:753) will
            # catch the off zone — but only because we clear paused state
            # here. Visibility matters for debug.
            _LOGGER.warning(
                "EgressManager: zone %s resume aborted (thermostat=%s "
                "saved_mode=%s) — clearing pause state, next tick will "
                "restore from off if needed",
                zone_id, thermostat, saved_mode,
            )
            self._paused_by_egress.pop(zone_id, None)
            self._egress_first_closed_at.pop(zone_id, None)
            await self._db_clear(zone_id)
            return

        try:
            await self._hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": thermostat, "hvac_mode": saved_mode},
                blocking=True,
            )
        except Exception:
            _LOGGER.warning(
                "EgressManager: resume set_hvac_mode failed for %s",
                thermostat, exc_info=True,
            )
            return

        if saved_preset:
            try:
                # ARREST-COMFORT-1 B-MED-1 fix-up: migrate to the
                # emit_set_preset_mode chokepoint. Classification: ALLOW
                # (restoration path — this returns the thermostat to the
                # preset the operator had before URA paused it; it is not
                # a revert against a comfort-qualified manual). Passing
                # gate=None means never DEFER; still routes through the
                # chokepoint for uniform emit accounting.
                await emit_set_preset_mode(
                    self._hass,
                    thermostat,
                    saved_preset,
                    blocking=True,
                    gate=None,
                    site="egress_resume",  # ALLOW (restoration)
                    zone_id=zone_id,
                    reason="egress_resume",
                )
            except Exception:
                _LOGGER.debug(
                    "EgressManager: resume set_preset_mode failed for %s",
                    thermostat, exc_info=True,
                )

        self._paused_by_egress.pop(zone_id, None)
        self._egress_first_closed_at.pop(zone_id, None)
        await self._db_clear(zone_id)
        _LOGGER.info(
            "EgressManager: RESUMED zone %s (restored mode=%s preset=%s)",
            zone_id, saved_mode, saved_preset,
        )
        await self._maybe_dispatch_nm(
            zone_id=zone_id,
            event=EGRESS_NM_EVENT_RESUMED,
            zone_name=zone_state.zone_name,
            triggered_room="",
            now=now,
        )

    # ------------------------------------------------------------------
    # NM dispatch (LOW severity, once-per-day per zone per event)
    # ------------------------------------------------------------------

    async def _maybe_dispatch_nm(
        self,
        *,
        zone_id: str,
        event: str,
        zone_name: str,
        triggered_room: str,
        now: datetime,
    ) -> None:
        """Dispatch NM alert if not in observation mode and not deduped today."""
        # Bug Class #23: gate at dispatch site.
        if self._hvac_coord is not None and getattr(
            self._hvac_coord, "_observation_mode", False,
        ):
            return
        today = now.date().isoformat()
        key = (zone_id, event)
        if self._nm_emitted_today.get(key) == today:
            return
        self._nm_emitted_today[key] = today

        if event == EGRESS_NM_EVENT_PAUSED:
            title = f"{zone_name} HVAC paused"
            if triggered_room:
                msg = (
                    f"{zone_name} HVAC paused — egress window open in "
                    f"{triggered_room} for {self._threshold_min}+ min."
                )
            else:
                msg = f"{zone_name} HVAC paused — egress window open."
        else:
            title = f"{zone_name} HVAC resumed"
            msg = f"{zone_name} HVAC resumed — all egress windows closed."

        try:
            nm = self._hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                _LOGGER.debug("EgressManager: no NM available — %s", title)
                return
            from .base import Severity
            await nm.async_notify(
                coordinator_id="hvac",
                severity=Severity.LOW,
                title=title,
                message=msg,
                hazard_type="hvac_egress",
            )
        except Exception:
            _LOGGER.warning(
                "EgressManager: NM dispatch failed (non-fatal): %s",
                title, exc_info=True,
            )

    # ------------------------------------------------------------------
    # DB write helpers (small, awaited under the held lock)
    # ------------------------------------------------------------------

    async def _db_save(self, zone_id: str, state: str, **fields) -> None:
        """v4.7.8 fix-up A-M6: single DB-write helper consolidating the 5
        per-state writers. Builds a base dict with all NULLs, then overrides
        with non-None kwargs. Always stamps `last_update_ts` from
        ``dt_util.now()`` if the caller didn't supply one.

        Promoted error log to WARNING for state-change writes (paused /
        resume_countdown / cooldown) per Reviewer B B10; counting writes
        stay at DEBUG since they're routine high-frequency progress ticks.
        """
        if self._db is None:
            return
        row = {
            "zone_id": zone_id,
            "state": state,
            "first_open_at": None,
            "first_closed_at": None,
            "paused_at": None,
            "saved_hvac_mode": None,
            "saved_preset_mode": None,
            "triggered_by_room": None,
            "thermostat_entity": None,
            "cooldown_expires_at": None,
            "last_update_ts": dt_util.now().isoformat(),
        }
        # Translate datetimes to ISO strings; pass strings/None as-is.
        for k, v in fields.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()
            else:
                row[k] = v
        try:
            await self._db.save_egress_state(row)
        except Exception:
            # v4.7.8 fix-up B10: state-change writes warn; counting stays debug.
            if state == EGRESS_STATE_COUNTING:
                _LOGGER.debug(
                    "EgressManager: db save %s failed for %s",
                    state, zone_id, exc_info=True,
                )
            else:
                _LOGGER.warning(
                    "EgressManager: db save %s failed for %s — restart "
                    "resilience for this transition lost",
                    state, zone_id, exc_info=True,
                )

    async def _db_save_counting(self, zone_id: str, first_open_at: datetime) -> None:
        await self._db_save(
            zone_id, EGRESS_STATE_COUNTING, first_open_at=first_open_at,
        )

    async def _db_save_paused_full(
        self,
        *,
        zone_id: str,
        saved_mode: str,
        saved_preset: str | None,
        paused_at: datetime,
        triggered_by_room: str,
        thermostat: str,
    ) -> None:
        await self._db_save(
            zone_id, EGRESS_STATE_PAUSED,
            paused_at=paused_at,
            saved_hvac_mode=saved_mode,
            saved_preset_mode=saved_preset,
            triggered_by_room=triggered_by_room,
            thermostat_entity=thermostat,
        )

    async def _db_save_paused(self, zone_id: str, now: datetime) -> None:
        """Re-save paused state when window re-opens during resume countdown."""
        info = self._paused_by_egress.get(zone_id, {})
        thermostat = info.get("thermostat") or ""
        await self._db_save_paused_full(
            zone_id=zone_id,
            saved_mode=info.get("mode") or "",
            saved_preset=info.get("preset") or "",
            paused_at=info.get("paused_at") or now,
            triggered_by_room=info.get("triggered_by_room") or "",
            thermostat=thermostat,
        )

    async def _db_save_resume_countdown(
        self, zone_id: str, first_closed_at: datetime,
    ) -> None:
        info = self._paused_by_egress.get(zone_id, {})
        await self._db_save(
            zone_id, EGRESS_STATE_RESUME_COUNTDOWN,
            first_closed_at=first_closed_at,
            paused_at=info.get("paused_at"),
            saved_hvac_mode=info.get("mode"),
            saved_preset_mode=info.get("preset"),
            triggered_by_room=info.get("triggered_by_room"),
            thermostat_entity=info.get("thermostat"),
        )

    async def _db_save_cooldown(
        self,
        zone_id: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        await self._db_save(
            zone_id, EGRESS_STATE_COOLDOWN, cooldown_expires_at=expires_at,
        )

    async def _db_clear(self, zone_id: str) -> None:
        if self._db is None:
            return
        try:
            await self._db.clear_egress_state(zone_id)
        except Exception:
            _LOGGER.debug("EgressManager: db clear failed", exc_info=True)

"""Fan Controller for HVAC Coordinator.

Manages ceiling/portable fans with temperature hysteresis,
occupancy gating, energy fan_assist, and humidity triggers.

v3.8.4-H3: Initial implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_FAN_SLEEP_POLICY,
    CONF_FANS,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    CONF_SLEEP_FAN_ON_TEMP_F,
    DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S,
    DEFAULT_FAN_SLEEP_POLICY,
    DEFAULT_SLEEP_FAN_ON_TEMP_F,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
    FAN_SLEEP_NORMAL,
    FAN_SLEEP_OFF,
    FAN_SLEEP_REDUCE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_GENERIC,
    SLEEP_FAN_ON_REARM_S,
    SLEEP_FAN_ON_STAGGER_S,
)
from .hvac_const import (
    DEFAULT_FAN_ACTIVATION_DELTA,
    DEFAULT_FAN_HYSTERESIS,
    DEFAULT_FAN_MIN_RUNTIME,
    DEFAULT_FAN_VACANCY_HOLD,
    FAN_ADOPTED_VACANCY_HOLD_MULT,
    FAN_SPEED_HIGH_DELTA,
    FAN_SPEED_HIGH_PCT,
    FAN_SPEED_LOW_DELTA,
    FAN_SPEED_LOW_PCT,
    FAN_SPEED_MED_DELTA,
    FAN_SPEED_MED_PCT,
    FAN_TRUST_STATES,
)
from .hvac_zones import ZoneManager
from .signals import EnergyConstraint

# B-L1 fix: hoisted to module top (no import cycle — fan_veto imports only
# .const + .domain_coordinators.house_state, no back-reference to hvac_fans).
from ..fan_veto import should_veto_comfort_fan, is_veto_relevant  # noqa: E402
from ..fan_veto import sleep_onset_fan_target  # noqa: E402

_LOGGER = logging.getLogger(__name__)


@dataclass
class RoomFanState:
    """Tracks fan state for a single room."""

    room_name: str
    zone_id: str
    # v4.7.16.2: per-room CONF_ROOM_TYPE, used to gate the sleep-state
    # occupied fan trust to bedrooms only — prevents spurious presence
    # in common areas (kitchen, living room) from activating fans
    # mid-night. Defaults to ROOM_TYPE_GENERIC so unset rooms safely
    # don't fire the bedroom-only branch.
    room_type: str = ROOM_TYPE_GENERIC
    fan_entities: list[str] = field(default_factory=list)
    is_on: bool = False
    speed_pct: int = 0
    trigger: str = ""  # "temperature" | "fan_assist" | ""
    last_on_time: str = ""
    vacancy_detected_time: str = ""
    manual_off_cooldown_until: str = ""  # ISO datetime — skip activation until this time
    # Fan-noise Mode-2 mitigation: HVAC handshake.
    fan_recheck_suppress_until: str = ""
    # Per-room CONF_FAN_SLEEP_POLICY (off/reduce/normal).
    fan_sleep_policy: str = DEFAULT_FAN_SLEEP_POLICY
    # NOTE: humidity exhaust state was previously tracked on this dataclass
    # but is now owned exclusively by the room-tier path in automation.py
    # (see ``handle_humidity_based_fan_control``).


class FanController:
    """Manages room fans with hysteresis, occupancy gating, and energy awareness.

    Called from the HVAC decision cycle every 5 minutes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
        activation_delta: float = DEFAULT_FAN_ACTIVATION_DELTA,
        deactivation_delta: float = DEFAULT_FAN_HYSTERESIS,
        min_runtime: int = DEFAULT_FAN_MIN_RUNTIME,
    ) -> None:
        """Initialize fan controller."""
        self.hass = hass
        self._zone_manager = zone_manager
        self._activation_delta = activation_delta
        self._deactivation_delta = deactivation_delta
        self._min_runtime = min_runtime
        self._room_fans: dict[str, RoomFanState] = {}
        self._fan_assist_active: bool = False
        self._house_state: str = ""
        # feature/sleep-fans-and-flash: one-shot latch for sleep-onset
        # bedroom fan activation. Set True after firing on a
        # non-sleep -> sleep edge; cleared when house_state leaves
        # FAN_TRUST_STATES so re-entry from a fully-outside state
        # (e.g. day/away) re-arms the one-shot.
        self._sleep_onset_fired: bool = False
        # Re-arm guard timestamp (scar: 2026-08-03 06:00 spurious sleep-
        # >waking->home_day flap). Once a sleep-onset burst fires, we
        # cannot re-fire for SLEEP_FAN_ON_REARM_S even if the house
        # briefly exits FAN_TRUST_STATES and re-enters. 0 disables.
        self._sleep_onset_last_fire_at: datetime | None = None
        # hotfix/occupied-fan-off-guard (2026-08-04): per-room throttle for
        # the "fan off suppressed: room occupied" INFO log. Emit once per
        # hold-window (~10 min) per room so a long-lived dueling loop
        # doesn't paper the log with the same suppression line every tick.
        self._suppress_log_last_at: dict[str, datetime] = {}

    def discover_fans(self) -> int:
        """Discover fan entities from room config entries in HVAC zones.

        Only includes rooms that belong to a discovered HVAC zone.
        Returns count of rooms with fans.
        """
        self._room_fans.clear()

        # Build room_name -> zone_id mapping
        room_to_zone: dict[str, str] = {}
        for zone_id, zone in self._zone_manager.zones.items():
            for room_name in zone.rooms:
                room_to_zone[room_name] = zone_id

        # Scan room entries for fan entities
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue

            room_name = entry.data.get(CONF_ROOM_NAME, "")
            if not room_name or room_name not in room_to_zone:
                continue

            merged = {**entry.data, **entry.options}
            fans = merged.get(CONF_FANS, [])

            if not fans:
                continue

            fan_list = fans if isinstance(fans, list) else [fans]
            fan_list = [f for f in fan_list if f]

            if not fan_list:
                continue

            self._room_fans[room_name] = RoomFanState(
                room_name=room_name,
                zone_id=room_to_zone[room_name],
                room_type=merged.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC),
                fan_entities=fan_list,
                fan_sleep_policy=str(
                    merged.get(CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY)
                ),
            )

            _LOGGER.info(
                "HVAC Fans: %s -> %d comfort fans (zone %s)",
                room_name, len(fan_list), room_to_zone[room_name],
            )

        _LOGGER.info("HVAC Fans: Discovered fans in %d rooms", len(self._room_fans))
        return len(self._room_fans)

    async def turn_off_all_managed(self) -> None:
        """Turn off all managed fans and reset tracking state.

        Called when fan_control_enabled is toggled off so fans don't
        stay running indefinitely. Idempotent — safe to call every cycle.
        """
        for room_name, room_fan in self._room_fans.items():
            if room_fan.is_on:
                await self._set_fan_state(
                    room_fan.fan_entities, False, 0,
                    room_name=room_name, trigger_path="turn_off_all_managed",
                )
            room_fan.is_on = False
            room_fan.trigger = ""
            room_fan.speed_pct = 0
            room_fan.last_on_time = ""
            room_fan.vacancy_detected_time = ""
            room_fan.manual_off_cooldown_until = ""  # Clean reset on toggle off

    async def update(self, energy_constraint: EnergyConstraint | None, house_state: str = "") -> None:
        """Run fan control logic for all managed rooms.

        Called from the HVAC decision cycle every 5 minutes.
        """
        if not self._room_fans:
            # Still track house-state so the latch can reset even if we
            # currently have no discovered fans.
            prior_state_empty = self._house_state
            self._house_state = house_state
            if house_state not in FAN_TRUST_STATES and prior_state_empty in FAN_TRUST_STATES:
                self._sleep_onset_fired = False
            return

        # feature/sleep-fans-and-flash: detect the non-sleep -> sleep edge
        # BEFORE overwriting _house_state so the one-shot fires exactly
        # once per sleep entry. Reset the latch whenever the house is not
        # in the FAN_TRUST_STATES trio (i.e. genuinely out of the night
        # window) — that guarantees the next sleep entry re-arms the shot.
        prior_state = self._house_state
        self._house_state = house_state
        self._fan_assist_active = (
            energy_constraint is not None and energy_constraint.fan_assist
        )
        now = dt_util.now()

        if house_state not in FAN_TRUST_STATES:
            # Only clear when the house leaves the trust family entirely
            # (home_day / away etc.). Sleep <-> waking flaps stay latched
            # to defend against the 2026-08-03 06:00-class spurious
            # transitions.
            self._sleep_onset_fired = False
        # NOTE: the sleep-onset activation runs AFTER the per-room loop
        # below (see end of this method). Running it BEFORE would race
        # against the loop's own "fan turned off externally" guard —
        # setting is_on=True right before the guard reads hass.states.get
        # (which hasn't caught up with the just-dispatched turn_on) would
        # incorrectly open a manual-off cooldown on this very tick.
        # Boot-edge guard (Review A-HIGH-1 fix-up): require an OBSERVED
        # prior state. Empty prior means this is our first update() call
        # since construction — treat it as pure seeding of _house_state
        # (already assigned above) and do NOT fire, even if the house is
        # already in sleep. The NEXT genuine non-sleep -> sleep edge
        # fires normally because prior_state will be a real value.
        should_fire_sleep_onset = (
            house_state == "sleep"
            and prior_state != "sleep"
            and prior_state != ""
            and not self._sleep_onset_fired
        )

        for room_name, room_fan in self._room_fans.items():
            # Fan-noise Mode-2 mitigation: HVAC handshake. Skip this room
            # entirely while the room-tier fan-recheck mechanism holds the
            # fan paused. Don't trip external-cooldown either (the entity
            # is off because WE turned it off).
            if room_fan.fan_recheck_suppress_until:
                try:
                    suppress_until = datetime.fromisoformat(
                        room_fan.fan_recheck_suppress_until,
                    )
                    if now < suppress_until:
                        continue
                    room_fan.fan_recheck_suppress_until = ""
                except (ValueError, TypeError):
                    room_fan.fan_recheck_suppress_until = ""

            # Sync internal state with actual HA entity state.
            # Prevents stale is_on/last_on_time if external automations
            # or manual actions changed fan state while we weren't looking.
            if room_fan.is_on and not any(
                self._is_entity_on(e) for e in room_fan.fan_entities
            ):
                # v4.0.18: Fan turned off externally — set cooldown.
                # FIX C D3: promoted from inline timedelta(hours=1) to
                # DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S so HVAC-tier and
                # room-tier share one knob (kill switch: 0 = disabled).
                cooldown_until = (
                    now + timedelta(seconds=DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S)
                ).isoformat()
                room_fan.manual_off_cooldown_until = cooldown_until
                _LOGGER.info(
                    "HVAC Fans: %s turned off externally — cooldown until %s",
                    room_name, cooldown_until,
                )
                room_fan.is_on = False
                room_fan.trigger = ""
                room_fan.speed_pct = 0
                room_fan.last_on_time = ""
            # Reverse: fan turned ON externally during cooldown — clear cooldown
            elif (not room_fan.is_on and room_fan.manual_off_cooldown_until
                  and any(self._is_entity_on(e) for e in room_fan.fan_entities)):
                room_fan.manual_off_cooldown_until = ""
                room_fan.is_on = True
                room_fan.trigger = "manual"
                room_fan.last_on_time = now.isoformat()
                _LOGGER.info("HVAC Fans: %s turned on during cooldown — cooldown cleared", room_name)
            # BUG 2 fix (2026-08-01 Study A, Phase 1 D1): adopt an
            # externally-lit fan when no cooldown is pending. Without
            # this branch, a room-tier-boot-lit fan (or physical-switch
            # ON) leaves room_fan.is_on=False, so the downstream
            # vacancy-off path short-circuits — nobody owns the OFF and
            # the fan can run indefinitely in a vacant room (Study A:
            # 4h at 100%). Trigger label "external" flags this as an
            # observed, not-actuated state; the eventual OFF is a
            # normal vacancy-off, NOT interpreted as manual.
            elif (not room_fan.is_on
                  and not room_fan.manual_off_cooldown_until
                  and any(self._is_entity_on(e) for e in room_fan.fan_entities)):
                # A-L3 + B-L1: switch-domain fans have no `percentage`
                # attribute — observed_speed remains 0 in that case, which
                # is safe: line-330's `should_on and speed != room_fan.speed_pct`
                # guard means the next _evaluate_temp_fan tick that decides
                # to hold the fan on at speed X will correctly re-actuate
                # to X (0 -> X trips the change gate); switches ignore the
                # percentage arg entirely. First observed non-zero speed
                # wins in multi-fan rooms (we break on the first entity
                # that reports a usable percentage — deterministic on the
                # discover_fans ordering).
                observed_speed = 0
                for entity_id in room_fan.fan_entities:
                    try:
                        st = self.hass.states.get(entity_id)
                        if st is None or st.state != "on":
                            continue
                        pct = None
                        attrs = getattr(st, "attributes", None)
                        if attrs is not None:
                            try:
                                pct = attrs.get("percentage")
                            except Exception:  # noqa: BLE001
                                pct = None
                        # A-L2: accept numeric-string percentage too
                        # (some integrations report "66" not 66).
                        try:
                            observed_speed = int(float(pct))
                            break
                        except (TypeError, ValueError):
                            continue
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.debug(
                            "HVAC Fans: %s adopt-speed read failed for %s (%s)",
                            room_name, entity_id, exc,
                        )
                room_fan.is_on = True
                room_fan.trigger = "external"
                room_fan.speed_pct = observed_speed
                room_fan.last_on_time = now.isoformat()
                # hotfix/fan-sweep-trio (2026-08-03): externally-adopted
                # fans get the same manual-off cooldown gate a URA-lit fan
                # gets after an external OFF (lines 219-222 reuse). This
                # blocks HVAC from immediately sweeping an operator-lit
                # fan on the next tick before genuine vacancy criteria
                # accrue. Kill switch: DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S=0
                # disables (matches existing pattern).
                if DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S:
                    room_fan.manual_off_cooldown_until = (
                        now + timedelta(seconds=DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S)
                    ).isoformat()
                _LOGGER.info(
                    "HVAC Fans: %s adopted externally-lit fan (speed=%d%%, "
                    "cooldown_until=%s)",
                    room_name, observed_speed,
                    room_fan.manual_off_cooldown_until or "disabled",
                )

            zone = self._zone_manager.zones.get(room_fan.zone_id)
            if zone is None:
                continue

            # Find room condition from zone
            room_cond = None
            for rc in zone.room_conditions:
                if rc.room_name == room_name:
                    room_cond = rc
                    break

            room_temp = room_cond.temperature if room_cond else None
            occupied = room_cond.occupied if room_cond else False
            setpoint_high = zone.target_temp_high

            # Per-room policy refreshed live each cycle (operator review
            # fix-up 2026-06-11 A-M1/A-M2): RoomFanState.fan_sleep_policy is
            # populated at discover_fans() but a runtime Options Flow change
            # would not take effect until reload. Read-through from the
            # config entry each tick keeps the cached field as fallback for
            # missing/empty values; production behavior tracks the latest
            # option without requiring a coordinator reload.
            live_policy = self._resolve_live_fan_sleep_policy(room_name, room_fan)

            # Evaluate temperature fans
            if room_fan.fan_entities and setpoint_high is not None and room_temp is not None:
                should_on, trigger, speed = self._evaluate_temp_fan(
                    room_fan, room_temp, setpoint_high, occupied, now, live_policy
                )
                # v3.18.1 + fan-trust state extension (2026-06-11):
                # During the night-trust window the speed cap is HOUSE-
                # WIDE at `sleep` (everyone is sleeping; LOW everywhere is
                # the comfort contract); at `home_night`/`waking` the cap
                # is BEDROOMS-ONLY (don't LOW-cap a living-room fan during
                # late-evening TV — operator A-M1). Per-room policy:
                #   normal — no cap (operator opted out)
                #   reduce — cap at FAN_SPEED_LOW_PCT (legacy v3.18.1)
                #   off    — cap at LOW conservatively (fan SHOULDN'T be
                #            running per operator intent; if some path
                #            activated it anyway, at least cap to LOW). The
                #            room-level path in automation.py:1515 handles
                #            the explicit force-off via is_sleep_mode_active
                #            time-window. NB: automation.py:1509 returns
                #            BEFORE that branch when HVAC manages the
                #            room's fans (pre-existing dead path; backlog).
                if should_on:
                    speed = self._apply_night_trust_speed_cap(
                        room_fan, speed, live_policy,
                    )
                if should_on != room_fan.is_on or (should_on and speed != room_fan.speed_pct):
                    # Comfort-fan house-AWAY veto (mmwave-corroboration
                    # Tier-3, D3). Routes through the shared
                    # fan_veto.should_veto_comfort_fan predicate — same
                    # helper the room-tier + reconciler sites consume.
                    # Scoped to ON transitions only: OFF actuations
                    # (should_on=False), speed changes on an already-on
                    # fan, humidity fans (not in this loop), safety paths
                    # are all exempt.
                    if should_on and not room_fan.is_on:
                        # A-M1 / B-M1 hoisted early-out: skip the O(N)
                        # config-entry scan on HOME_* / SLEEP / WAKING
                        # ticks where the veto can't fire anyway.
                        merged: dict[str, Any] = {}
                        if is_veto_relevant(self.hass):
                            try:
                                for entry in self.hass.config_entries.async_entries(DOMAIN):
                                    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                                        continue
                                    if entry.data.get(CONF_ROOM_NAME) != room_name:
                                        continue
                                    merged = {**entry.data, **entry.options}
                                    break
                            except Exception as exc:  # noqa: BLE001
                                _LOGGER.debug(
                                    "HVAC Fans: %s merged-config read failed for veto (%s)",
                                    room_name, exc,
                                )
                        if merged and should_veto_comfort_fan(
                            self.hass, room_name, merged,
                        ):
                            # Skip the actuation — leave RoomFanState
                            # unchanged so a subsequent tick (after
                            # house_state transitions to HOME_* or
                            # trusted presence lands) can re-evaluate
                            # cleanly. Speed cap / vacancy anchors are
                            # unaffected.
                            continue
                    dispatched = await self._set_fan_state(
                        room_fan.fan_entities, should_on, speed,
                        room_name=room_name,
                        trigger_path=f"update:{trigger or 'vacancy_off'}",
                    )
                    # hotfix/occupied-fan-off-guard (2026-08-04): if the
                    # OFF was suppressed by the occupied-guard, leave
                    # RoomFanState UNCHANGED so subsequent ticks re-
                    # evaluate cleanly (the fan stays physically on, the
                    # controller stays consistent with it, no dueling
                    # loop). Applies only to the OFF suppression path;
                    # ON dispatches always return True.
                    if dispatched:
                        room_fan.is_on = should_on
                        room_fan.speed_pct = speed if should_on else 0
                        room_fan.trigger = trigger if should_on else ""
                        if should_on and not room_fan.last_on_time:
                            room_fan.last_on_time = now.isoformat()
                        elif not should_on:
                            room_fan.last_on_time = ""

            # D1 — Humidity fans are evaluated EXCLUSIVELY by the room-tier
            # path in automation.py::handle_humidity_based_fan_control. The
            # HVAC coordinator does NOT read or write humidity-fan state in
            # any branch (eliminates the v4.6.x dual-controller orphan: with
            # HVAC-coord ON + comfort-fan OFF, the humidity fan no longer
            # falls between owners).

        # feature/sleep-fans-and-flash: sleep-onset activation runs AFTER
        # the per-room loop so the loop's "fan turned off externally"
        # detector doesn't race the just-dispatched turn_on and open a
        # spurious manual-off cooldown. The one-shot latch is set
        # unconditionally after the call so an ineligible edge still
        # counts as "fired for this sleep session" (matches the room-tier
        # semantics — the operator will retry on the next sleep entry).
        if should_fire_sleep_onset:
            await self._sleep_onset_activation(now)
            self._sleep_onset_fired = True

    def _resolve_sleep_fan_on_temp_f(self) -> float:
        """Live-read CONF_SLEEP_FAN_ON_TEMP_F from the CM entry options.

        Mirrors the read-through pattern used by
        _resolve_live_fan_sleep_policy so an Options-Flow change takes
        effect without a coordinator reload. Missing entry or read
        failure falls back to DEFAULT_SLEEP_FAN_ON_TEMP_F. A value of
        0 disables the feature (master kill switch).
        """
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                    continue
                merged = {**entry.data, **entry.options}
                return float(
                    merged.get(
                        CONF_SLEEP_FAN_ON_TEMP_F, DEFAULT_SLEEP_FAN_ON_TEMP_F,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "HVAC Fans: sleep_fan_on_temp_f live read failed (%s); "
                "using default %.1f",
                exc, DEFAULT_SLEEP_FAN_ON_TEMP_F,
            )
        return DEFAULT_SLEEP_FAN_ON_TEMP_F

    async def _sleep_onset_activation(self, now: datetime) -> None:
        """Turn ON comfort fans in warm, occupied bedrooms at sleep entry.

        feature/sleep-fans-and-flash. Gated by:
          - CONF_SLEEP_FAN_ON_TEMP_F > 0 (master kill switch: 0 disables)
          - room_type == ROOM_TYPE_BEDROOM (bedroom-family only)
          - live occupancy (room_cond.occupied)
          - room_temp >= threshold
          - fan not already on
          - per-room fan_sleep_policy != off
        Speed is computed by ``fan_veto.sleep_onset_fan_target`` — the
        standard temp-delta ladder (FAN_SPEED_*_DELTA over
        room_temp - threshold, same thresholds as ``_compute_speed``),
        then policy-capped (reduce -> min(speed, LOW); normal -> uncapped
        ladder). Trigger label "sleep_onset" surfaces the path in logs.
        Latch (self._sleep_onset_fired) is set by the caller.
        """
        threshold = self._resolve_sleep_fan_on_temp_f()
        if threshold <= 0:
            _LOGGER.debug(
                "HVAC Fans: sleep-onset skipped — feature disabled (threshold=0)",
            )
            return

        # Re-arm guard (scar: 2026-08-03 06:00 spurious flap): if the
        # last fire is within SLEEP_FAN_ON_REARM_S, skip. Prevents a
        # dawn-class exit + re-entry from re-transitioning every
        # bedroom fan. 0 disables the guard.
        if (
            SLEEP_FAN_ON_REARM_S > 0
            and self._sleep_onset_last_fire_at is not None
        ):
            elapsed = (now - self._sleep_onset_last_fire_at).total_seconds()
            if elapsed < SLEEP_FAN_ON_REARM_S:
                _LOGGER.info(
                    "HVAC Fans: sleep-onset skipped — within re-arm window "
                    "(%.0fs < %ds)", elapsed, SLEEP_FAN_ON_REARM_S,
                )
                return

        # Collect eligible rooms first, THEN dispatch sequentially with
        # SLEEP_FAN_ON_STAGGER_S between per-room turn-ons. Simultaneous
        # multi-room transitions are the worst mmWave-radar case.
        eligible: list[tuple[str, RoomFanState, int, str, float]] = []
        for room_name, room_fan in self._room_fans.items():
            if not room_fan.fan_entities:
                continue
            # Operator contract (2026-08-03): "running fans are
            # untouchable" from the sleep-onset path — any power/speed
            # transition excites mmWave radar (the fan-transition phantom
            # class), and a fan already running is already comfortable
            # AND already radar-adapted. Skip on either the tracked
            # is_on flag OR live entity state so a physically-on fan
            # that URA hasn't adopted yet is still protected.
            if room_fan.is_on or any(
                self._is_entity_on(e) for e in room_fan.fan_entities
            ):
                continue
            # Manual-off cooldown respect (scar: THE incident — the wife's
            # manual intent being fought). Someone who turned their fan
            # OFF before bed made a choice; sleep-onset must not override
            # it. Matches _evaluate_temp_fan's semantics.
            if room_fan.manual_off_cooldown_until:
                try:
                    until = datetime.fromisoformat(
                        room_fan.manual_off_cooldown_until,
                    )
                    if now < until:
                        _LOGGER.info(
                            "HVAC Fans: sleep-onset skipped %s — manual-off "
                            "cooldown active until %s",
                            room_name, until.isoformat(),
                        )
                        continue
                except (ValueError, TypeError):
                    room_fan.manual_off_cooldown_until = ""
            zone = self._zone_manager.zones.get(room_fan.zone_id)
            if zone is None:
                continue
            room_cond = None
            for rc in zone.room_conditions:
                if rc.room_name == room_name:
                    room_cond = rc
                    break
            if room_cond is None:
                continue
            live_policy = self._resolve_live_fan_sleep_policy(room_name, room_fan)
            # Delegate the eligibility + speed decision to the shared
            # helper — same predicate the room-tier call site consumes.
            speed = sleep_onset_fan_target(
                room_config={"room_type": room_fan.room_type},
                occupied=bool(room_cond.occupied),
                room_temp=room_cond.temperature,
                threshold=threshold,
                policy=live_policy,
            )
            if speed is None or speed <= 0:
                continue
            eligible.append(
                (room_name, room_fan, speed, live_policy,
                 float(room_cond.temperature)),
            )

        if not eligible:
            return

        # Record the fire timestamp BEFORE the burst so any concurrent
        # re-entry (via a second update() call) is guarded by the
        # re-arm window.
        self._sleep_onset_last_fire_at = now
        activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")

        import asyncio as _asyncio  # local — avoid top-of-file churn
        for i, (room_name, room_fan, speed, live_policy, room_temp) in enumerate(
            eligible,
        ):
            if i > 0 and SLEEP_FAN_ON_STAGGER_S > 0:
                # Stagger between per-room fan turn-ons so mmWave radar
                # never sees a simultaneous multi-room transition.
                try:
                    await _asyncio.sleep(SLEEP_FAN_ON_STAGGER_S)
                except Exception:  # noqa: BLE001
                    pass
            try:
                await self._set_fan_state(
                    room_fan.fan_entities, True, speed,
                    room_name=room_name,
                    trigger_path="update:sleep_onset",
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error(
                    "HVAC Fans: sleep-onset activation failed for %s (%s)",
                    room_name, exc,
                )
                continue
            room_fan.is_on = True
            room_fan.speed_pct = speed
            room_fan.trigger = "sleep_onset"
            room_fan.last_on_time = now.isoformat()
            _LOGGER.info(
                "HVAC Fans: sleep-onset activated %s (temp=%.1f>=%.1f, "
                "policy=%s, speed=%d%%)",
                room_name, room_temp, threshold, live_policy, speed,
            )
            # Activity-log row (scar: invisible actuations cost hours).
            # Uses the existing fan_on shape (matches automation.py:1780).
            if activity_logger is not None:
                try:
                    self.hass.async_create_task(activity_logger.log(
                        coordinator="hvac",
                        action="fan_on",
                        description=(
                            f"Sleep-onset fan on "
                            f"({room_temp:.1f}°F >= {threshold:.1f}°F, "
                            f"policy={live_policy}, speed={speed}%, "
                            f"trigger=sleep_onset)"
                        ),
                        room=room_name,
                        entity_id=(
                            room_fan.fan_entities[0]
                            if room_fan.fan_entities else None
                        ),
                    ))
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug(
                        "HVAC Fans: activity-log write failed for %s (%s)",
                        room_name, exc,
                    )

    def _apply_night_trust_speed_cap(
        self, room_fan: RoomFanState, speed: int, live_policy: str | None,
    ) -> int:
        """Apply the v3.18.1 night-trust speed cap, scoped by state + policy.

        Cap scope (operator decision 2026-06-11):
          - sleep: house-wide (everyone is sleeping; LOW everywhere).
          - home_night / waking: BEDROOMS ONLY (no LOW-cap on a living-
            room fan during late-evening TV).
        Policy mapping:
          - normal -> no cap (operator opted out)
          - reduce -> cap at FAN_SPEED_LOW_PCT (legacy v3.18.1)
          - off    -> cap at FAN_SPEED_LOW_PCT conservatively (the
            room-level path in automation.py:1515 handles the explicit
            force-off via is_sleep_mode_active; but automation.py:1509
            returns BEFORE that branch when HVAC manages the room — a
            pre-existing dead path. Backlog: lift the early-return so
            policy=off reaches the room-level force-off for HVAC-
            managed rooms.)
        """
        if self._house_state not in FAN_TRUST_STATES:
            return speed
        cap_in_scope = (
            self._house_state == "sleep"
            or room_fan.room_type == ROOM_TYPE_BEDROOM
        )
        if not cap_in_scope:
            return speed
        policy = (live_policy or room_fan.fan_sleep_policy
                  or DEFAULT_FAN_SLEEP_POLICY)
        if policy == FAN_SLEEP_REDUCE:
            return min(speed, FAN_SPEED_LOW_PCT)
        if policy == FAN_SLEEP_OFF:
            return min(speed, FAN_SPEED_LOW_PCT)
        # FAN_SLEEP_NORMAL -> no cap
        return speed

    def _resolve_live_fan_sleep_policy(
        self, room_name: str, room_fan: RoomFanState,
    ) -> str:
        """Resolve per-room CONF_FAN_SLEEP_POLICY LIVE each cycle.

        Operator review A-M1/A-M2 fix-up 2026-06-11: discover_fans()
        caches the policy at registration, but an Options-Flow change
        wouldn't take effect until reload. Reading through to the live
        config-entry options each tick keeps RoomFanState's cached field
        as a fallback while preferring the latest user-set value.
        Read failures fall back silently to the cached field.
        """
        cached = room_fan.fan_sleep_policy or DEFAULT_FAN_SLEEP_POLICY
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                if entry.data.get(CONF_ROOM_NAME) != room_name:
                    continue
                merged = {**entry.data, **entry.options}
                live = merged.get(CONF_FAN_SLEEP_POLICY)
                if live:
                    policy = str(live)
                    # Cheap cache refresh so other call-sites that read
                    # the dataclass field see the latest policy.
                    if policy != room_fan.fan_sleep_policy:
                        room_fan.fan_sleep_policy = policy
                    return policy
                break
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "HVAC Fans: %s live policy read failed (%s); using cached %s",
                room_name, exc, cached,
            )
        return cached

    def _evaluate_temp_fan(
        self,
        room_fan: RoomFanState,
        room_temp: float,
        setpoint_high: float,
        occupied: bool,
        now: datetime,
        live_policy: str | None = None,
    ) -> tuple[bool, str, int]:
        """Evaluate whether temperature fan should be on.

        Returns (should_on, trigger_reason, speed_pct).

        v4.0.15: Occupancy gate moved BEFORE temperature triggers.
        Fans cool people, not rooms — don't activate in empty rooms.
        """
        delta = room_temp - setpoint_high

        # v4.0.18: Manual off cooldown — skip all activation triggers.
        # hotfix/fan-sweep-trio (2026-08-03): gate is scoped to `not is_on`
        # to preserve its original semantic (block URA re-activation of a
        # fan that an external actor turned OFF). The adoption branch now
        # sets manual_off_cooldown_until on an is_on=True fan as a marker;
        # returning False here for an ON fan would have the caller sweep
        # the adopted fan on the very next tick — exactly the class the
        # cycle is instrumenting against.
        if room_fan.manual_off_cooldown_until and not room_fan.is_on:
            try:
                cooldown_until = datetime.fromisoformat(room_fan.manual_off_cooldown_until)
                if now < cooldown_until:
                    return False, "", 0
                room_fan.manual_off_cooldown_until = ""
            except (ValueError, TypeError):
                room_fan.manual_off_cooldown_until = ""

        # Night-window occupied fan trust — companion to v4.7.13's OFF-side
        # vacancy-hold trust. ON-side semantics (B-H2 / B-M1 / C-3 review
        # fix-up 2026-06-11):
        #   - HOLD (fan already on): extended to FAN_TRUST_STATES so a
        #     fan that's running keeps running while at least one bedroom
        #     occupant is present at home_night/sleep/waking (mmWave drops
        #     still bodies in bed at all three flank states).
        #   - ACTIVATE (fan currently off → turn on): kept SLEEP-ONLY.
        #     The operator's request was to extend STOP control; auto-
        #     activating fans at home_night/waking was over-extension and
        #     surprises people who are awake and mobile.
        # Bedroom-only gate preserved (prevents kitchen/living-room
        # presence from holding fans on). Policy=off rooms are NEVER
        # coordinator-activated even at sleep (fixes the pre-existing
        # dueling-writers exposure with the room-level path).
        # Bidirectionality: only suppresses while `occupied` is True —
        # genuinely vacated rooms fall through to the vacancy timer below.
        # Manual-off cooldown above this block still wins.
        if (
            self._house_state in FAN_TRUST_STATES
            and occupied
            and room_fan.room_type == ROOM_TYPE_BEDROOM
        ):
            # Reviewer B fix-up B-MED-1: clear any stale vacancy anchor.
            room_fan.vacancy_detected_time = ""
            if room_fan.is_on:
                # HOLD across all three states.
                return (
                    True,
                    room_fan.trigger or f"night_trust_hold:{self._house_state}",
                    room_fan.speed_pct,
                )
            # DECISION HISTORY (this branch has no in-`_evaluate_temp_fan`
            # activation).
            # 2026-06-11 (operator, second revision): the former
            # `sleep_occupied_activate` (early-June hotfix-B add-on) was
            # REMOVED here because it started bedroom fans at LOW
            # UNCONDITIONALLY on the sleep edge, which was (a) seasonally
            # wrong (winter), and (b) fought manual-off after the
            # cooldown expired. The June-1 incident itself was an
            # OFF-side bug, addressed by the HOLD branch above.
            # 2026-08-03 (feature/sleep-fans-and-flash, operator-
            # approved REVISION): sleep-onset activation is REINTRODUCED,
            # but relocated out of `_evaluate_temp_fan` (this method's
            # FAN_TRUST_STATES trust block) and into a dedicated
            # `_sleep_onset_activation` path invoked from `update()`
            # on the non-sleep -> sleep edge only. Both
            # 2026-06-11 objections are now addressed:
            #   (a) seasonally-wrong-in-winter: activation is gated by
            #       the operator knob CONF_SLEEP_FAN_ON_TEMP_F (default
            #       72°F, 0 disables). Cool bedrooms in winter stay off.
            #   (b) fights-manual-off-after-cooldown: the v5.48.0 fan
            #       adoption + manual-off-cooldown machinery now
            #       protects manual intent (an already-on fan, whether
            #       URA-lit or externally-lit-then-adopted, is skipped
            #       — the operator contract is "running fans are
            #       untouchable"; any speed transition excites mmWave
            #       radar, and a running fan is already radar-adapted).
            # Speed = standard temp-delta ladder shared with
            # ``_compute_speed`` via fan_veto.sleep_onset_fan_target,
            # then policy-capped (reduce -> min(speed, LOW); normal
            # uncapped) — never a fixed unconditional LOW.
            # Off-before-sleep no longer stays off unconditionally;
            # instead it stays off UNLESS the room is a warm occupied
            # bedroom at sleep entry (the exact class the operator now
            # wants activated).

        # Occupancy gate: don't activate fans in unoccupied rooms
        if not occupied and not room_fan.is_on:
            room_fan.vacancy_detected_time = ""
            return False, "", 0

        # If fan is on and room becomes unoccupied, apply vacancy hold then off
        if not occupied and room_fan.is_on:
            if not room_fan.vacancy_detected_time:
                room_fan.vacancy_detected_time = now.isoformat()
            vacancy_since = datetime.fromisoformat(room_fan.vacancy_detected_time)
            vacancy_seconds = (now - vacancy_since).total_seconds()
            # v4.7.13 + fan-trust extension: Night-window zone presence
            # trust — indefinite hold while at least one zone_persons
            # member is "home". State-scoped evidence tier (B-C1 / A-H2
            # review fix-up 2026-06-11):
            #   - sleep: zone-person proxy alone is sound (`home` ⇒ in
            #     bed somewhere in the zone; zone is typically one bedroom).
            #   - home_night / waking: people roam during these flank
            #     states (kitchen, hallways, bathrooms), so the zone-
            #     person proxy alone would hold fans on in empty rooms
            #     for hours. Require ROOM_TYPE_BEDROOM as well — only
            #     bedrooms have the sensor-degeneration problem that
            #     justifies an indefinite hold here.
            # Vacancy timer is NOT cleared; if the person tracker goes
            # not-home during the trust window, vacancy expiry takes over.
            # Bidirectionality: with all trackers not-home this branch
            # falls through and the DEFAULT_FAN_VACANCY_HOLD timer fires.
            # NOTE: scoped by the FAN_TRUST_STATES gate immediately below
            # (line ~875); the bare-"sleep" literal here is the
            # evidence-tier ternary inside that gate, not a bare check.
            person_evidence_ok = (
                self._house_state == "sleep"
                or room_fan.room_type == ROOM_TYPE_BEDROOM
            )
            if self._house_state in FAN_TRUST_STATES and person_evidence_ok:
                try:
                    zone = self._zone_manager.zones.get(room_fan.zone_id)
                    if zone is not None:
                        for person_entity in (zone.zone_persons or []):
                            st = self.hass.states.get(person_entity)
                            if st is not None and st.state == "home":
                                _LOGGER.debug(
                                    "HVAC Fans: %s vacancy hold extended during "
                                    "%s (person %s home)",
                                    room_fan.room_name,
                                    self._house_state,
                                    person_entity,
                                )
                                return True, room_fan.trigger, room_fan.speed_pct
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug(
                        "HVAC Fans: %s night-trust person check errored: %s",
                        room_fan.room_name, exc,
                    )
            # hotfix/fan-sweep-trio (2026-08-03): externally-adopted fans
            # get a longer hold (FAN_ADOPTED_VACANCY_HOLD_MULT * base).
            # Rationale: something-not-URA lit this fan; give the operator
            # more grace before HVAC sweeps it off in a vacant room. Kill
            # switch: FAN_ADOPTED_VACANCY_HOLD_MULT=1.0 restores identical
            # timing to URA-lit fans. Applied via multiplier so
            # DEFAULT_FAN_VACANCY_HOLD remains the single source of truth
            # for the URA-lit path.
            # LOW-A fix-up (2026-08-03): note — a legitimate URA
            # re-actuation while the fan is adopted (trigger=="external")
            # rewrites `room_fan.trigger` to the URA reason at the
            # actuation site above (~line 406) and thereby collapses this
            # hold back to base on the next tick. That is intentional:
            # once URA re-decides to run the fan for its own reason, the
            # co-managed timing applies. The 2x hold is scoped to a fan
            # URA has NOT (yet) chosen to command.
            effective_hold = DEFAULT_FAN_VACANCY_HOLD
            if room_fan.trigger == "external":
                effective_hold = int(
                    DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT,
                )
            if vacancy_seconds >= effective_hold:
                return False, "", 0
            # Hold on during vacancy window at current speed
            return True, room_fan.trigger, room_fan.speed_pct

        # Room is occupied — clear vacancy tracking
        room_fan.vacancy_detected_time = ""

        # 1. Energy fan_assist: turn on 1F above setpoint, off 1F below setpoint
        if self._fan_assist_active:
            if delta >= 1.0:
                return True, "fan_assist", self._compute_speed(delta)
            elif delta < -1.0 and room_fan.trigger == "fan_assist":
                pass  # fall through to off
            elif room_fan.trigger == "fan_assist":
                return True, "fan_assist", self._compute_speed(max(delta, 0))

        # 2. Temperature hysteresis
        if delta >= self._activation_delta:
            return True, "temperature", self._compute_speed(delta)
        elif room_fan.is_on and room_fan.trigger == "temperature":
            off_threshold = self._activation_delta - self._deactivation_delta
            if delta <= off_threshold:
                pass  # fall through to off
            else:
                return True, "temperature", self._compute_speed(delta)

        # Min runtime check
        if room_fan.is_on and room_fan.last_on_time:
            on_since = datetime.fromisoformat(room_fan.last_on_time)
            runtime_minutes = (now - on_since).total_seconds() / 60
            if runtime_minutes < self._min_runtime:
                return True, room_fan.trigger, room_fan.speed_pct

        # Default off
        return False, "", 0

    # NOTE: previous Path B exhaust evaluator removed; exhaust automation
    # is now exclusively room-owned (see automation.py).

    def _compute_speed(self, delta: float) -> int:
        """Compute fan speed percentage from temperature delta."""
        if delta >= FAN_SPEED_HIGH_DELTA:
            return FAN_SPEED_HIGH_PCT
        if delta >= FAN_SPEED_MED_DELTA:
            return FAN_SPEED_MED_PCT
        if delta >= FAN_SPEED_LOW_DELTA:
            return FAN_SPEED_LOW_PCT
        return FAN_SPEED_LOW_PCT  # minimum speed if on

    def _is_entity_on(self, entity_id: str) -> bool:
        """Check if an entity is currently on."""
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == "on"

    def _resolve_room_occupied_slug(self, room_name: str) -> str:
        """Shared slugifier — guard and observer MUST agree on the slug
        used to derive ``binary_sensor.<slug>_occupied``. Same source as
        _record_actuation_conflict_if_occupied. Falls back to an inline
        transform if the memory_facade import fails (test harnesses).
        """
        try:
            from ..memory_facade import _slugify
            return _slugify(room_name or "")
        except Exception:  # noqa: BLE001
            return (room_name or "").lower().replace(" ", "_").replace("-", "_")

    def _read_room_occupied_state(self, room_name: str) -> str | None:
        """Return the raw state of ``binary_sensor.<slug>_occupied`` or None.

        Guarded — external state reads never raise into actuation paths.
        Returns None if the sensor doesn't exist OR is unavailable/unknown
        (guard fails open on those, per hotfix spec).
        """
        try:
            slug = self._resolve_room_occupied_slug(room_name)
            st = self.hass.states.get(f"binary_sensor.{slug}_occupied")
            if st is None:
                return None
            if st.state in ("unavailable", "unknown", None, ""):
                return None
            return st.state
        except Exception:  # noqa: BLE001
            return None

    async def _set_fan_state(
        self, entities: list[str], on: bool, speed_pct: int,
        *,
        room_name: str | None = None,
        trigger_path: str | None = None,
    ) -> bool:
        """Set fan entities on/off with speed.

        Returns True if actuation was dispatched to HA, False if the OFF
        was SUPPRESSED by the occupied-fan-off harm-stop guard (caller
        must NOT mutate room_fan.is_on when False is returned).

        hotfix/fan-sweep-trio (2026-08-03): OFF dispatches emit an
        ``actuation_conflict`` memory episode when the target room's
        occupancy binary_sensor is ``on`` at dispatch time.

        hotfix/occupied-fan-off-guard (2026-08-04): the observer becomes
        a HARM-STOP. If occupancy=='on' at dispatch time — for any house
        state, any room type — the OFF is SKIPPED (fan left as-is) and
        the actuation_conflict episode is written with attrs.suppressed=
        True (semantic flip: pre-guard the episode recorded harm done,
        now it records harm prevented). Exemptions: turn_off_all_managed
        (operator kill-switch), recheck paths (identified by callers not
        passing room_name), and rooms whose occupancy sensor is
        unavailable/unknown/missing (guard fails open — no live evidence).
        Real OFF dispatches also write an ura_activity_log 'fan_off' row
        so sweeps are visible (closes the 2026-08-04 false-PASS blind
        spot).
        """
        if not on and room_name:
            trigger_str = trigger_path or ""
            is_exempt_from_guard = trigger_str == "turn_off_all_managed"
            occ = self._read_room_occupied_state(room_name)
            if occ == "on" and not is_exempt_from_guard:
                # Guard fires — SUPPRESS the OFF. Write the episode with
                # suppressed=True so the log-of-record captures a
                # prevented conflict (the harm-stop worked).
                self._record_actuation_conflict_if_occupied(
                    room_name, trigger_path, suppressed=True,
                )
                self._log_off_suppressed_throttled(room_name, trigger_path)
                return False
            # Not suppressed — observer records harm-done for the OFF
            # against an occupied room that fell under an exemption
            # (turn_off_all_managed is exempted INSIDE the observer, so
            # the call is a no-op there). Vacant / unavailable → observer
            # sees occ != 'on' and returns without writing.
            self._record_actuation_conflict_if_occupied(room_name, trigger_path)
        for entity_id in entities:
            try:
                if on:
                    if entity_id.startswith("fan."):
                        await self.hass.services.async_call(
                            "fan", "turn_on",
                            {"entity_id": entity_id, "percentage": speed_pct},
                            blocking=False,
                        )
                    else:
                        await self.hass.services.async_call(
                            "homeassistant", "turn_on",
                            {"entity_id": entity_id},
                            blocking=False,
                        )
                else:
                    if entity_id.startswith("fan."):
                        await self.hass.services.async_call(
                            "fan", "turn_off",
                            {"entity_id": entity_id},
                            blocking=False,
                        )
                    else:
                        await self.hass.services.async_call(
                            "homeassistant", "turn_off",
                            {"entity_id": entity_id},
                            blocking=False,
                        )
            except Exception as e:
                _LOGGER.error("HVAC Fans: failed to control %s: %s", entity_id, e)
        # hotfix/occupied-fan-off-guard (2026-08-04): activity-log every
        # real OFF dispatch. Closes the 2026-08-04 blind spot — sweep
        # offs were previously invisible in the activity log (only ONs
        # from sleep-onset logged), which produced a false PASS on
        # validation. Mirrors the sleep-onset fan_on shape (line 659).
        if not on and room_name:
            self._log_fan_off_activity(room_name, trigger_path, entities)
        return True

    def _log_off_suppressed_throttled(
        self, room_name: str, trigger_path: str | None,
    ) -> None:
        """INFO log a suppressed OFF, once per hold-window per room."""
        try:
            now = dt_util.utcnow()
            last = self._suppress_log_last_at.get(room_name)
            window_s = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
            if last is not None and (now - last).total_seconds() < window_s:
                return
            self._suppress_log_last_at[room_name] = now
            _LOGGER.info(
                "HVAC Fans: fan off suppressed: room occupied "
                "(room=%s, trigger=%s)",
                room_name, trigger_path or "unknown",
            )
        except Exception:  # noqa: BLE001
            pass

    def _log_fan_off_activity(
        self,
        room_name: str,
        trigger_path: str | None,
        entities: list[str],
    ) -> None:
        """Write an ura_activity_log 'fan_off' row for a real OFF dispatch."""
        try:
            activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger is None:
                return
            entity_id = entities[0] if entities else None
            self.hass.async_create_task(activity_logger.log(
                coordinator="hvac",
                action="fan_off",
                description=(
                    f"Fan off (trigger={trigger_path or 'unknown'}, "
                    f"house_state={self._house_state or 'unknown'})"
                ),
                room=room_name,
                entity_id=entity_id,
            ))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "HVAC Fans: activity-log write failed for fan_off %s (%s)",
                room_name, exc,
            )

    def _record_actuation_conflict_if_occupied(
        self, room_name: str, trigger_path: str | None,
        *, suppressed: bool = False,
    ) -> None:
        """Emit ``actuation_conflict`` memory episode if room is occupied.

        hotfix/fan-sweep-trio (2026-08-03): observe-only writer for the
        2026-08-03 incident class (HVAC fan turn-off dispatched into an
        occupied room). Copies the fan_veto.py:_record_veto shape:
        shared slugify, DAO handles dedup, exception-contained. Missing
        DB, missing memory_facade, or absent occupancy sensor all no-op.
        """
        # LOW-A fix-up (2026-08-03): turn_off_all_managed is an operator-
        # commanded global sweep (Fan Control switch turned OFF), not a
        # controller-decided actuation into an occupied room. Suppress the
        # episode for this trigger only — controller-decided OFFs
        # (vacancy_off / sleep / veto) still emit.
        if trigger_path == "turn_off_all_managed":
            return
        try:
            # LOW-B3 fix-up (2026-08-03): use the shared memory_facade
            # slugifier (single source of truth) rather than an inline copy.
            # No import cycle: memory_facade only imports from .const +
            # stdlib (verified 2026-08-03).
            from ..memory_facade import _slugify
            slug = _slugify(room_name or "")
            occ_state = self.hass.states.get(f"binary_sensor.{slug}_occupied")
            if occ_state is None or occ_state.state != "on":
                return
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is None or not hasattr(db, "log_memory_episode"):
                return
            # House state — read via memory_facade helper if available,
            # else best-effort attribute.
            house_state = ""
            try:
                from ..fan_veto import _get_house_state as _ghs
                house_state = _ghs(self.hass) or ""
            except Exception:  # noqa: BLE001
                # Fallback: cached in-cycle house state if the helper is
                # unavailable (test harnesses may not import fan_veto).
                house_state = self._house_state or ""
            self.hass.async_create_task(
                db.log_memory_episode(
                    node_id=f"room:{slug}",
                    episode_type="actuation_conflict",
                    adjudication="unadjudicated",
                    adjudicated_by="hvac_fan_controller",
                    attrs={
                        "action": "fan_off",
                        "trigger": trigger_path or "unknown",
                        "house_state": house_state,
                        "suppressed": bool(suppressed),
                    },
                    source_ref="hvac_fans.py:_set_fan_state",
                ),
            )
        except Exception:  # noqa: BLE001 — never fail actuation on memory I/O
            pass

    def suppress_room_until(self, room_name: str, until_iso: str) -> None:
        """Set HVAC suppression window for a room (fan-recheck handshake)."""
        room_fan = self._room_fans.get(room_name)
        if room_fan is None:
            return
        room_fan.fan_recheck_suppress_until = until_iso

    def is_room_fan_on(self, room_name: str) -> bool:
        """Return whether any managed fan in this room is currently ON."""
        room_fan = self._room_fans.get(room_name)
        if room_fan is None:
            return False
        return any(self._is_entity_on(e) for e in room_fan.fan_entities)

    def snapshot_room_fan(self, room_name: str) -> dict[str, Any] | None:
        """Snapshot pre-pause attrs for restore. None if no fans in room."""
        room_fan = self._room_fans.get(room_name)
        if room_fan is None or not room_fan.fan_entities:
            return None
        snapshot: dict[str, Any] = {
            "entities": list(room_fan.fan_entities),
            "is_on": room_fan.is_on,
            "speed_pct": room_fan.speed_pct,
            "trigger": room_fan.trigger,
            "last_on_time": room_fan.last_on_time,
            "entity_attrs": {},
        }
        for entity_id in room_fan.fan_entities:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            attrs = state.attributes or {}
            snapshot["entity_attrs"][entity_id] = {
                "percentage": attrs.get("percentage"),
                "preset_mode": attrs.get("preset_mode"),
                "oscillating": attrs.get("oscillating"),
                "direction": attrs.get("direction"),
            }
        return snapshot

    async def pause_for_recheck(
        self, room_name: str, suppress_until_iso: str,
    ) -> dict[str, Any] | None:
        """Snapshot + pause a room's fan for the recheck window.

        Internal write — does NOT trip manual_off_cooldown_until (that path
        is for external operator-driven off). Returns the snapshot for the
        caller to hold + later pass to restore_after_recheck. Returns None
        if the room has no managed fans.
        """
        snapshot = self.snapshot_room_fan(room_name)
        if snapshot is None:
            return None
        room_fan = self._room_fans[room_name]
        room_fan.fan_recheck_suppress_until = suppress_until_iso
        if snapshot["is_on"]:
            await self._set_fan_state(snapshot["entities"], False, 0)
        _LOGGER.info(
            "HVAC Fans: %s paused for fan-recheck (suppress_until=%s)",
            room_name, suppress_until_iso,
        )
        return snapshot

    async def restore_after_recheck(
        self, room_name: str, snapshot: dict[str, Any] | None,
    ) -> None:
        """Restore pre-pause fan state from snapshot. Clears suppression."""
        room_fan = self._room_fans.get(room_name)
        if room_fan is None:
            return
        room_fan.fan_recheck_suppress_until = ""
        if snapshot is None:
            return
        if snapshot.get("is_on"):
            speed = int(snapshot.get("speed_pct") or 0) or 100
            # D-HIGH-1 fix: consult the comfort-fan veto BEFORE re-issuing
            # the ON restoration. If the house transitioned to AWAY during
            # the recheck window, the pre-pause snapshot must NOT be
            # blindly restored — that would turn a fan back on in an empty
            # house (Bug-Class-#53, 4th actuation site). Load the room's
            # merged config the same way the update()-path veto does.
            merged: dict[str, Any] = {}
            if is_veto_relevant(self.hass):
                try:
                    for entry in self.hass.config_entries.async_entries(DOMAIN):
                        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                            continue
                        if entry.data.get(CONF_ROOM_NAME) != room_name:
                            continue
                        merged = {**entry.data, **entry.options}
                        break
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug(
                        "HVAC Fans: %s restore-veto merged-config read failed (%s)",
                        room_name, exc,
                    )
            if merged and should_veto_comfort_fan(
                self.hass, room_name, merged,
            ):
                # Skip the restoration. Clear the local is_on snapshot so
                # RoomFanState stays consistent with the LIVE (off) entity
                # state — the fan-recheck pause already turned entities
                # OFF at pause_for_recheck, and we're choosing not to
                # re-arm them into an empty house.
                room_fan.is_on = False
                room_fan.speed_pct = 0
                room_fan.trigger = ""
                room_fan.last_on_time = ""
                _LOGGER.info(
                    "HVAC Fans: %s restore-after-recheck vetoed "
                    "(house went AWAY during recheck)", room_name,
                )
                return
            await self._set_fan_state(snapshot["entities"], True, speed)
            room_fan.is_on = True
            room_fan.speed_pct = speed
            room_fan.trigger = snapshot.get("trigger", "") or ""
            if snapshot.get("last_on_time"):
                room_fan.last_on_time = snapshot["last_on_time"]
            for entity_id, attrs in (snapshot.get("entity_attrs") or {}).items():
                preset = attrs.get("preset_mode")
                if preset:
                    try:
                        await self.hass.services.async_call(
                            "fan", "set_preset_mode",
                            {"entity_id": entity_id, "preset_mode": preset},
                            blocking=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.debug(
                            "HVAC Fans: restore set_preset_mode %s failed: %s",
                            entity_id, exc,
                        )
                oscillating = attrs.get("oscillating")
                if oscillating is not None:
                    try:
                        await self.hass.services.async_call(
                            "fan", "oscillate",
                            {"entity_id": entity_id, "oscillating": bool(oscillating)},
                            blocking=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.debug(
                            "HVAC Fans: restore oscillate %s failed: %s",
                            entity_id, exc,
                        )
                direction = attrs.get("direction")
                if direction:
                    try:
                        await self.hass.services.async_call(
                            "fan", "set_direction",
                            {"entity_id": entity_id, "direction": direction},
                            blocking=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.debug(
                            "HVAC Fans: restore set_direction %s failed: %s",
                            entity_id, exc,
                        )
        _LOGGER.info(
            "HVAC Fans: %s restored after fan-recheck (was_on=%s)",
            room_name, snapshot.get("is_on"),
        )

    def get_fan_status(self) -> dict[str, Any]:
        """Return fan status for sensor attributes."""
        active = sum(1 for r in self._room_fans.values() if r.is_on)
        now = dt_util.now()
        in_cooldown = sum(
            1 for r in self._room_fans.values()
            if r.manual_off_cooldown_until
            and datetime.fromisoformat(r.manual_off_cooldown_until) > now
        )
        return {
            "rooms_with_fans": len(self._room_fans),
            "active_fan_rooms": active,
            "fan_assist_active": self._fan_assist_active,
            "rooms_in_cooldown": in_cooldown,
        }

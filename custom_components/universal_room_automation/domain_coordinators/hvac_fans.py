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
    DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S,
    DEFAULT_FAN_SLEEP_POLICY,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    FAN_SLEEP_NORMAL,
    FAN_SLEEP_OFF,
    FAN_SLEEP_REDUCE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_GENERIC,
)
from .hvac_const import (
    DEFAULT_FAN_ACTIVATION_DELTA,
    DEFAULT_FAN_HYSTERESIS,
    DEFAULT_FAN_MIN_RUNTIME,
    DEFAULT_FAN_VACANCY_HOLD,
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
        for room_fan in self._room_fans.values():
            if room_fan.is_on:
                await self._set_fan_state(room_fan.fan_entities, False, 0)
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
            return

        self._house_state = house_state
        self._fan_assist_active = (
            energy_constraint is not None and energy_constraint.fan_assist
        )
        now = dt_util.now()

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
                        if isinstance(pct, (int, float)):
                            observed_speed = int(pct)
                            break
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.debug(
                            "HVAC Fans: %s adopt-speed read failed for %s (%s)",
                            room_name, entity_id, exc,
                        )
                room_fan.is_on = True
                room_fan.trigger = "external"
                room_fan.speed_pct = observed_speed
                room_fan.last_on_time = now.isoformat()
                _LOGGER.info(
                    "HVAC Fans: %s adopted externally-lit fan (speed=%d%%)",
                    room_name, observed_speed,
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
                    await self._set_fan_state(
                        room_fan.fan_entities, should_on, speed
                    )
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

        # v4.0.18: Manual off cooldown — skip all activation triggers
        if room_fan.manual_off_cooldown_until:
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
            # NO ACTIVATE path (operator decision 2026-06-11, second
            # revision): fan ACTUATION is temperature-driven only, never
            # house-state-driven — at sleep included. The former
            # `sleep_occupied_activate` (early-June hotfix-B add-on; the
            # June-1 incident itself was an OFF-side bug, fixed by the
            # HOLD above) started bedroom fans at LOW unconditionally,
            # which is seasonally wrong (winter) and fights manual-off
            # after the cooldown. Manual-on is one tap and the HOLD then
            # blip-protects it all night. Off-before-sleep stays off;
            # the standard temp-driven evaluation below decides starts.

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
            if vacancy_seconds >= DEFAULT_FAN_VACANCY_HOLD:
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

    async def _set_fan_state(
        self, entities: list[str], on: bool, speed_pct: int,
    ) -> None:
        """Set fan entities on/off with speed."""
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

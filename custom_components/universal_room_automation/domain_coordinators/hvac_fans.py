"""Fan Controller for HVAC Coordinator.

Manages ceiling/portable fans with temperature hysteresis,
occupancy gating, energy fan_assist, and humidity triggers.

v3.8.4-H3: Initial implementation.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_FAN_MANUAL_ON_HOLD_S,
    CONF_FAN_SLEEP_POLICY,
    CONF_FANS,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    CONF_SLEEP_FAN_ON_TEMP_F,
    DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S,
    DEFAULT_FAN_MANUAL_ON_HOLD_S,
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


def _get_fan_oracle(hass):
    """Return the FanPolicyOracle singleton from hass.data or None.

    Mirrors ``automation.py::_get_fan_oracle`` — non-throwing accessor
    used by ``_OracleISOField`` descriptors + the §5.4 locked-setter
    call sites in this module.
    """
    try:
        if hass is None:
            return None
        return hass.data.get(DOMAIN, {}).get("fan_oracle")
    except Exception:  # noqa: BLE001
        return None


def _room_key(room_name: str) -> str:
    """FAN-LAYER-2 D1 (PLAN §5.1/§5.2): shared prefixed key for the oracle ledger.

    Applies ``unicodedata.normalize("NFC", name).strip()`` so NFC vs NFD
    forms of the same visible name hash to the same row (MED-2-round-2).
    Rejects control characters (raises ValueError — surfaced via the
    build-time uniqueness gate in
    ``quality/tests/test_fan_layer_2_uniqueness_gate.py``). Colon in a
    room name is LEGAL but LOGGED (the prefix is fixed ``room:`` so
    downstream parsers split on the first colon).

    Empty-name input returns the sentinel ``room:__unkeyed__`` (never
    the bare empty string; two rooms without a name must not collide).
    """
    if not room_name:
        return "room:__unkeyed__"
    normalized = unicodedata.normalize("NFC", room_name).strip()
    if not normalized:
        return "room:__unkeyed__"
    if any(unicodedata.category(ch).startswith("C") for ch in normalized):
        _LOGGER.error(
            "fan-layer-2: rejecting room_name with control chars: %r",
            room_name,
        )
        raise ValueError(
            f"room_name contains control characters: {room_name!r}"
        )
    if ":" in normalized:
        _LOGGER.info(
            "fan-layer-2: room_name contains ':' — legal but cosmetic "
            "collision with prefix scheme (name=%r)", normalized,
        )
    return f"room:{normalized}"


def _log_hvac_fallback_warn(side: str, room_name: str) -> None:
    """HVAC-tier analogue of ``RoomAutomation._fallback_warn`` (§5.1).

    Emits when the descriptor read/write is served by the local slot
    because the oracle is unavailable — a lifecycle regression that
    should be visible in logs.
    """
    _LOGGER.warning(
        "FanPolicyOracle fallback (hvac tier): %s served from RoomFanState "
        "local slot (oracle unavailable) for room=%s — check CoordinatorManager lifecycle",
        side, room_name,
    )


class _OracleISOField:
    """Read-through descriptor: ``RoomFanState.<field>`` <-> oracle ledger.

    FAN-LAYER-2 D1 (PLAN §5.1). Presents the field as an ISO string (matching
    the pre-migration ``@dataclass`` shape) while the authoritative value
    lives on ``FanPolicyOracle.get_state(_room_key(room_name)).<oracle_field>``
    as a ``datetime | None``. Hydrate-on-read: if the oracle exists but
    returns None AND we have a local write cached, seed the oracle from
    the local slot and return the local ISO. Mirrors the RoomAutomation
    @property at ``automation.py:283-329``.
    """

    __slots__ = ("_oracle_field", "_setter_name", "_local_key")

    def __init__(self, oracle_field: str, setter_name: str, local_key: str) -> None:
        self._oracle_field = oracle_field
        self._setter_name = setter_name
        self._local_key = local_key

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        local = object.__getattribute__(obj, self._local_key)
        hass = getattr(obj, "_hass", None)
        oracle = _get_fan_oracle(hass)
        if oracle is None:
            if local:
                _log_hvac_fallback_warn("read", obj.room_name)
            return local
        try:
            key = _room_key(obj.room_name)
            dt_val = getattr(oracle.get_state(key), self._oracle_field)
            if dt_val is None:
                if local:
                    parsed = dt_util.parse_datetime(local)
                    if parsed is not None:
                        getattr(oracle, self._setter_name)(key, parsed)
                    return local
                return ""
            return dt_val.isoformat()
        except Exception:  # noqa: BLE001
            if local:
                _log_hvac_fallback_warn("read_exc", obj.room_name)
            return local

    def __set__(self, obj, value) -> None:
        # Normalize to a string for the local slot (matches pre-migration
        # ISO-string shape; empty string clears).
        as_local = value if isinstance(value, str) else ""
        object.__setattr__(obj, self._local_key, as_local)
        hass = getattr(obj, "_hass", None)
        oracle = _get_fan_oracle(hass)
        if oracle is None:
            if as_local:
                _log_hvac_fallback_warn("write", obj.room_name)
            return
        try:
            key = _room_key(obj.room_name)
            if not as_local:
                getattr(oracle, self._setter_name)(key, None)
            else:
                parsed = dt_util.parse_datetime(as_local)
                getattr(oracle, self._setter_name)(key, parsed)
        except Exception:  # noqa: BLE001
            if as_local:
                _log_hvac_fallback_warn("write_exc", obj.room_name)


class RoomFanState:
    """Tracks fan state for a single room.

    FAN-LAYER-2 (2026-08-11): dropped ``@dataclass`` sugar because two
    fields (``manual_off_cooldown_until``, ``manual_on_hold_until``) are
    now delegated to ``FanPolicyOracle`` via class-level ``_OracleISOField``
    descriptors. The dataclass-generated ``__init__`` invokes
    ``self.field = value`` on every constructed instance, which would
    flood the descriptor with pre-``_hass`` writes. This explicit
    ``__init__`` orders ``_hass`` first and seeds the two delegated
    fields via ``object.__setattr__`` into their local slots — bypassing
    the descriptor at construction. Subsequent runtime writes flow
    through the descriptor normally.

    Signature is BACKWARD-COMPATIBLE (PLAN §5.1 HIGH-1-round-2): every
    field from the pre-FAN-LAYER-2 dataclass is accepted as
    ``keyword-only`` with today's default so existing test constructors
    (10 §9 parity-gate call sites) work byte-identical, unmodified.
    """

    def __init__(
        self,
        room_name: str,
        zone_id: str,
        *,
        hass: HomeAssistant | None = None,
        # Every pre-FAN-LAYER-2 dataclass field, kw-only optional with the
        # historical default so existing test constructors don't TypeError.
        room_type: str = ROOM_TYPE_GENERIC,
        fan_entities: list[str] | None = None,
        is_on: bool = False,
        speed_pct: int = 0,
        trigger: str = "",
        last_on_time: str = "",
        vacancy_detected_time: str = "",
        manual_off_cooldown_until: str = "",
        manual_on_hold_until: str = "",
        manual_on_hold_paused_at: str = "",
        fan_recheck_suppress_until: str = "",
        fan_sleep_policy: str = DEFAULT_FAN_SLEEP_POLICY,
    ) -> None:
        # ORDERING: _hass FIRST so any subsequent descriptor access resolves
        # the oracle. object.__setattr__ bypasses the descriptor.
        object.__setattr__(self, "_hass", hass)
        self.room_name = room_name
        self.zone_id = zone_id
        self.room_type = room_type
        self.fan_entities = list(fan_entities or [])
        self.is_on = is_on
        self.speed_pct = speed_pct
        self.trigger = trigger
        self.last_on_time = last_on_time
        self.vacancy_detected_time = vacancy_detected_time
        # Seed the delegated fields via object.__setattr__ to the local slot.
        # Do NOT go through the descriptor at __init__ time — the oracle may
        # not yet be attached and even if it is, hydrate-on-read seeds it
        # lazily on first descriptor GET.
        object.__setattr__(
            self, "_manual_off_local", manual_off_cooldown_until,
        )
        object.__setattr__(
            self, "_manual_on_local", manual_on_hold_until,
        )
        self.manual_on_hold_paused_at = manual_on_hold_paused_at
        self.fan_recheck_suppress_until = fan_recheck_suppress_until
        self.fan_sleep_policy = fan_sleep_policy
    # NOTE: humidity exhaust state was previously tracked on this dataclass
    # but is now owned exclusively by the room-tier path in automation.py
    # (see ``handle_humidity_based_fan_control``).


# Descriptors applied AFTER class definition so ``__init__`` runs first
# without descriptor interference on construction.
RoomFanState.manual_off_cooldown_until = _OracleISOField(  # type: ignore[attr-defined]
    "manual_off_cooldown_until", "set_manual_off_cooldown", "_manual_off_local",
)
RoomFanState.manual_on_hold_until = _OracleISOField(  # type: ignore[attr-defined]
    "manual_on_hold_until", "set_manual_on_hold", "_manual_on_local",
)


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
        # FAN-LAYER-2 §5.4 row #14: throttle for cosmetic-only ledger cleanup.
        # NOT load-bearing — read-time expiry at _is_manual_on_hold_live +
        # _evaluate_temp_fan is the authoritative gate. See PLANNING §5.4.
        self._last_ledger_cleanup_at: datetime | None = None

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
                # FAN-LAYER-2 §5.1: hass passed so _OracleISOField descriptors
                # can resolve the FanPolicyOracle for delegated reads/writes.
                hass=self.hass,
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
        oracle = _get_fan_oracle(self.hass)
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
            # FAN-LAYER-2 §5.4 sites #1 + #2 (locked_setter_required): kill
            # switch races an in-flight URA-OFF's consult; the locked setter
            # serializes the clear behind the emitting critical section.
            if oracle is not None:
                await oracle.clear_manual_off_cooldown_locked(_room_key(room_name))
                await oracle.clear_manual_on_hold_locked(_room_key(room_name))
            else:
                # Fallback (oracle not yet attached): keep the byte-identical
                # local-slot write so behavior mirrors pre-FAN-LAYER-2.
                room_fan.manual_off_cooldown_until = ""
                room_fan.manual_on_hold_until = ""
            room_fan.manual_on_hold_paused_at = ""

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

        # FAN-LAYER-2 §5.4 row #14: cosmetic hygiene sweep, throttled to 60s
        # so per-tick cost stays bounded. NOT load-bearing — read-time
        # expiry evaluation at _is_manual_on_hold_live + _evaluate_temp_fan
        # remains the authoritative gate. See PLANNING §5.4.
        # getattr-with-default so test harnesses that bypass __init__ don't
        # AttributeError; production always initializes via __init__.
        _last_cleanup = getattr(self, "_last_ledger_cleanup_at", None)
        if (
            _last_cleanup is None
            or (now - _last_cleanup).total_seconds() > 60
        ):
            self._last_ledger_cleanup_at = now
            oracle_for_cleanup = _get_fan_oracle(self.hass)
            if oracle_for_cleanup is not None:
                try:
                    await oracle_for_cleanup.async_cleanup_expired_holds()
                except Exception:  # noqa: BLE001 — cosmetic
                    _LOGGER.debug(
                        "HVAC Fans: async_cleanup_expired_holds failed",
                        exc_info=True,
                    )

        oracle = _get_fan_oracle(self.hass)
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
                cooldown_deadline = (
                    now + timedelta(seconds=DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S)
                )
                cooldown_until = cooldown_deadline.isoformat()
                # FAN-LAYER-2 §5.4 site #3 (CANONICAL INV-FLA-T RACE): locked
                # setter serializes with any concurrent URA turn-ON emit that
                # was mid-consult when this external-OFF landed.
                # FAN-MANUAL-1 discharge (b): external OFF is a newer
                # human instruction than any live ON hold. Clear the hold
                # (§5.4 site #4).
                if oracle is not None:
                    await oracle.set_manual_off_cooldown_locked(
                        _room_key(room_name), cooldown_deadline,
                    )
                    await oracle.clear_manual_on_hold_locked(_room_key(room_name))
                else:
                    room_fan.manual_off_cooldown_until = cooldown_until
                    room_fan.manual_on_hold_until = ""
                room_fan.manual_on_hold_paused_at = ""
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
                # FAN-LAYER-2 §5.4 site #5: freshest-human-wins; locked
                # clear serializes with URA turn-OFF consult.
                if oracle is not None:
                    await oracle.clear_manual_off_cooldown_locked(_room_key(room_name))
                else:
                    room_fan.manual_off_cooldown_until = ""
                room_fan.is_on = True
                room_fan.trigger = "manual"
                room_fan.last_on_time = now.isoformat()
                # FAN-MANUAL-1: reversal IS a fresh manual-ON. Open the
                # ON hold on the purpose-named field (the OFF field is
                # OFF-only after the field split — PLANNING §5.4).
                # A-MED-1 fix-up (2026-08-10): honor per-room override.
                room_hold_s = self._resolve_live_manual_on_hold_s(room_name)
                # FAN-LAYER-2 §5.4 sites #6/#7 (CANONICAL INV-FLA-T): locked
                # setter serializes hold-open with concurrent URA OFF.
                if room_hold_s > 0:
                    hold_deadline = now + timedelta(seconds=room_hold_s)
                    if oracle is not None:
                        await oracle.set_manual_on_hold_locked(
                            _room_key(room_name), hold_deadline,
                        )
                    else:
                        room_fan.manual_on_hold_until = hold_deadline.isoformat()
                else:
                    # Kill-switch semantics (hold_s == 0): clear the hold.
                    if oracle is not None:
                        await oracle.clear_manual_on_hold_locked(_room_key(room_name))
                    else:
                        room_fan.manual_on_hold_until = ""
                _LOGGER.info(
                    "HVAC Fans: %s turned on during cooldown — cooldown "
                    "cleared, manual_on_hold_until=%s",
                    room_name,
                    room_fan.manual_on_hold_until or "disabled",
                )
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
                # FAN-MANUAL-1 (2026-08-10): adoption sets the purpose-
                # named ON hold — NOT the OFF cooldown field. Previously
                # (hotfix/fan-sweep-trio) the OFF field was overloaded as
                # an ON-marker on an `is_on=True` fan, forcing all readers
                # of `manual_off_cooldown_until` to disambiguate by
                # `is_on`. The field split ends that overload
                # (PLANNING §5.4): `manual_off_cooldown_until` is
                # OFF-only, `manual_on_hold_until` protects adopted +
                # operator-lit fans. Kill switch: hold_s == 0 disables
                # (module default OR per-room CONF_FAN_MANUAL_ON_HOLD_S).
                # A-MED-1 fix-up (2026-08-10): honor per-room override —
                # discover_fans() stored no cached knob, so we live-read.
                room_hold_s = self._resolve_live_manual_on_hold_s(room_name)
                # FAN-LAYER-2 §5.4 sites #8/#9: adopt-fan branch — same
                # INV-FLA-T race as #6/#7, different code path (originally
                # `not is_on and not cooldown and entity ON` — external
                # adoption without prior cooldown context).
                if room_hold_s > 0:
                    hold_deadline = now + timedelta(seconds=room_hold_s)
                    if oracle is not None:
                        await oracle.set_manual_on_hold_locked(
                            _room_key(room_name), hold_deadline,
                        )
                    else:
                        room_fan.manual_on_hold_until = hold_deadline.isoformat()
                else:
                    if oracle is not None:
                        await oracle.clear_manual_on_hold_locked(_room_key(room_name))
                    else:
                        room_fan.manual_on_hold_until = ""
                _LOGGER.info(
                    "HVAC Fans: %s adopted externally-lit fan (speed=%d%%, "
                    "manual_on_hold_until=%s)",
                    room_name, observed_speed,
                    room_fan.manual_on_hold_until or "disabled",
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
        # FAN-MANUAL-1 (2026-08-10): after the field split (PLANNING §5.4)
        # `manual_off_cooldown_until` is OFF-only. The `not is_on` guard
        # is now belt-and-suspenders — a well-behaved code path should
        # never set the OFF field on an ON fan — kept to defend against
        # regressions.
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
            return __import__("re").sub(r"[^a-z0-9]+","_",(room_name or "").lower()).strip("_")

    def _is_manual_on_hold_live(self, room_fan: RoomFanState) -> bool:
        """True while the room's FAN-MANUAL-1 manual-ON hold is in window.

        Guarded parse of the ISO string; malformed values are cleared
        rather than blocking OFF indefinitely.

        Mid-pause expiry fix (Review A-MED-2 / C-H1, 2026-08-10): while
        the hold is PAUSED (``manual_on_hold_paused_at`` set), it does
        NOT age — clock-time expiry is deferred until
        ``restore_after_recheck`` runs and extends ``manual_on_hold_until``
        by the paused duration. Without this guard, a hold that would
        naturally expire mid-pause was silently truncated: expiry cleared
        both fields and the extension arithmetic then had nothing to
        extend, so the operator's remaining window was lost across the
        recheck.
        """
        if not room_fan.manual_on_hold_until:
            return False
        try:
            until = datetime.fromisoformat(room_fan.manual_on_hold_until)
        except (ValueError, TypeError):
            room_fan.manual_on_hold_until = ""
            room_fan.manual_on_hold_paused_at = ""
            return False
        # Paused holds don't age — treat as live regardless of wall clock.
        if room_fan.manual_on_hold_paused_at:
            return True
        if dt_util.now() >= until:
            # Expired — clear the RAM field so subsequent reads are cheap.
            room_fan.manual_on_hold_until = ""
            room_fan.manual_on_hold_paused_at = ""
            return False
        return True

    def is_room_in_manual_on_hold(self, room_name: str) -> bool:
        """Public accessor: True if this HVAC-managed room has a live hold.

        FAN-MANUAL-1 (Review B-HIGH-1, 2026-08-10): consumed by the
        HVAC coordinator's zone-vacancy sweep + pre-arrival deactivation
        so those code paths honor INV-FMH for HVAC-owned fans (the room
        coordinator's `is_fan_in_manual_on_hold` accessor covers the
        room-tier fans only). Returns False for unknown rooms.
        """
        room_fan = self._room_fans.get(room_name)
        if room_fan is None:
            return False
        return self._is_manual_on_hold_live(room_fan)

    def _resolve_live_manual_on_hold_s(self, room_name: str) -> int:
        """Per-room CONF_FAN_MANUAL_ON_HOLD_S live read (A-MED-1 fix-up).

        Mirrors ``_resolve_live_fan_sleep_policy`` — reads through to the
        live config-entry each cycle so an Options-Flow change takes
        effect without a coordinator reload. Falls back to the module
        default on any read failure. 0 disables the hold for this room
        (per-room kill switch; matches automation.py::
        _resolve_fan_manual_on_hold_s semantics).
        """
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                if entry.data.get(CONF_ROOM_NAME) != room_name:
                    continue
                merged = {**entry.data, **entry.options}
                raw = merged.get(
                    CONF_FAN_MANUAL_ON_HOLD_S, DEFAULT_FAN_MANUAL_ON_HOLD_S,
                )
                if raw is None or raw == "":
                    return DEFAULT_FAN_MANUAL_ON_HOLD_S
                try:
                    return max(0, int(raw))
                except (TypeError, ValueError):
                    return DEFAULT_FAN_MANUAL_ON_HOLD_S
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "HVAC Fans: %s manual-ON hold-s live read failed (%s)",
                room_name, exc,
            )
        return DEFAULT_FAN_MANUAL_ON_HOLD_S

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
            # FAN-MANUAL-1 INV-FMH: single-chokepoint enforcement at the
            # HVAC-tier OFF boundary. If the room is in a manual-ON hold,
            # SUPPRESS the OFF (leave RoomFanState untouched — caller's
            # `if dispatched:` block skips the mutation, so the fan stays
            # ON and the hold window is preserved). Exemptions:
            #  - turn_off_all_managed (operator kill switch — discharge e)
            #  - recheck pause (bypasses by passing room_name=None, so
            #    control never reaches this branch — allowlisted per
            #    PLANNING ruling 2)
            # Safety-driven OFFs would need their own trigger_path here
            # to override; none exist in the current tree.
            room_fan_for_hold = self._room_fans.get(room_name)
            if (
                room_fan_for_hold is not None
                and not is_exempt_from_guard
                and self._is_manual_on_hold_live(room_fan_for_hold)
            ):
                _LOGGER.debug(
                    "HVAC Fans: %s OFF suppressed by manual-ON hold "
                    "(trigger=%s, until=%s)",
                    room_name, trigger_str or "unknown",
                    room_fan_for_hold.manual_on_hold_until,
                )
                return False
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
        

        NOTE (Review B M-2): suppressed=True is the only reachable label
        while the guard early-returns on occ!=on; suppressed=False becomes
        reachable only if the guard is ever removed.
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
        # FAN-MANUAL-1 ruling 2: if a manual-ON hold is live, record the
        # pause instant so `restore_after_recheck` can extend the hold
        # deadline by the paused duration — the operator's intent must
        # not be silently truncated by a diagnostic pause.
        if self._is_manual_on_hold_live(room_fan):
            room_fan.manual_on_hold_paused_at = dt_util.now().isoformat()
        if snapshot["is_on"]:
        # INTENTIONAL: no room_name — recheck OFFs bypass the occupied-fan
        # guard AND the fan_off activity log by design (evidence-gathering
        # pause, state restored after). Threading room_name here would
        # break the recheck window. (Review A #3, 2026-08-04.)
        # FAN-MANUAL-1: the no-room_name call also bypasses the INV-FMH
        # gate in `_set_fan_state` — this is the allowlisted trigger_path
        # per PLANNING ruling 2.
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
        # FAN-MANUAL-1 ruling 2 / FAN-LAYER-2 §5.4a site #15: R-M-W across
        # adopt-external interleave. Wrap the read → compute → write in a
        # manually-acquired per-room lock so a concurrent external-ON
        # adopt (site #6/#8) cannot bump the hold between our READ of
        # manual_on_hold_until and our WRITE of the extended deadline.
        # asyncio.Lock is NON-REENTRANT — inside the block we use the SYNC
        # oracle setter (never the _locked variant).
        if room_fan.manual_on_hold_paused_at and room_fan.manual_on_hold_until:
            oracle_rmw = _get_fan_oracle(self.hass)
            if oracle_rmw is not None:
                room_key = _room_key(room_name)
                async with oracle_rmw._get_lock(room_key):
                    ledger = oracle_rmw.get_state(room_key)
                    try:
                        paused_at = datetime.fromisoformat(
                            room_fan.manual_on_hold_paused_at,
                        )
                        # Prefer the authoritative oracle-side deadline over
                        # the local ISO shadow (they should agree, but the
                        # oracle wins on drift).
                        oracle_until = ledger.manual_on_hold_until
                        if oracle_until is not None:
                            elapsed = dt_util.now() - paused_at
                            if elapsed.total_seconds() > 0:
                                new_until = oracle_until + elapsed
                                # Sync setter INSIDE the held lock (asyncio.Lock
                                # non-reentrant — do NOT call the _locked variant).
                                oracle_rmw.set_manual_on_hold(room_key, new_until)
                                # Mirror to local slot for byte-identical log
                                # shape (subsequent descriptor read will
                                # return the same ISO from the oracle).
                                object.__setattr__(
                                    room_fan, "_manual_on_local",
                                    new_until.isoformat(),
                                )
                                _LOGGER.info(
                                    "HVAC Fans: %s manual-ON hold extended by %.0fs "
                                    "across recheck pause (until=%s)",
                                    room_name, elapsed.total_seconds(),
                                    new_until.isoformat(),
                                )
                    except (ValueError, TypeError):
                        pass
            else:
                # Fallback: no oracle — pre-FAN-LAYER-2 behavior.
                try:
                    paused_at = datetime.fromisoformat(
                        room_fan.manual_on_hold_paused_at,
                    )
                    until = datetime.fromisoformat(room_fan.manual_on_hold_until)
                    elapsed = dt_util.now() - paused_at
                    if elapsed.total_seconds() > 0:
                        room_fan.manual_on_hold_until = (
                            until + elapsed
                        ).isoformat()
                        _LOGGER.info(
                            "HVAC Fans: %s manual-ON hold extended by %.0fs "
                            "across recheck pause (until=%s)",
                            room_name, elapsed.total_seconds(),
                            room_fan.manual_on_hold_until,
                        )
                except (ValueError, TypeError):
                    pass
            room_fan.manual_on_hold_paused_at = ""
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
        # FAN-MANUAL-1: post field-split, count ON-hold rooms separately
        # so the diagnostic surface distinguishes "operator turned it off"
        # from "operator turned it on" (previously conflated in the
        # `rooms_in_cooldown` bucket via the overloaded field).
        in_manual_on_hold = 0
        for r in self._room_fans.values():
            if not r.manual_on_hold_until:
                continue
            try:
                if datetime.fromisoformat(r.manual_on_hold_until) > now:
                    in_manual_on_hold += 1
            except (ValueError, TypeError):
                continue
        return {
            "rooms_with_fans": len(self._room_fans),
            "active_fan_rooms": active,
            "fan_assist_active": self._fan_assist_active,
            "rooms_in_cooldown": in_cooldown,
            "rooms_in_manual_on_hold": in_manual_on_hold,
        }

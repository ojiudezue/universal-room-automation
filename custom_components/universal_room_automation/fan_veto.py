"""Comfort-fan house-AWAY veto helper (mmwave-corroboration Tier-3, D3).

Single shared predicate consumed by ALL THREE comfort-fan actuation sites:

    1. Room-tier: automation.py::handle_temperature_based_fan_control (turn-on)
    2. HVAC-tier: hvac_fans.py::HvacFanController.update (before _set_fan_state)
    3. Reconciler: actuator_reconciler.py::_resolve_fan (before returning "on")

Every actuation site MUST route through this predicate — that is the whole
Bug-Class-#53 ("computed-but-not-consumed") mitigation the plan calls out.
If a fourth actuation site is later added, it must also call this helper.

Truth-preserving invariant (mirrors Invariant V from the planning doc):

    If house_state ∈ {AWAY, VACATION} AND the room has no trusted presence
    (BLE-present, motion recent within occupancy_timeout, or camera-person
    for camera-covered rooms; mmWave EXCLUDED), a comfort-fan `turn_on` MUST
    be suppressed. Sleep path is untouched (disjoint predicate). Humidity
    fans / safety fans / manual actuations are untouched (they never call
    this helper — the caller guards the call site).

KILL SWITCH: CONF_COMFORT_FAN_AWAY_VETO_ENABLED=False on the room's config
→ helper returns False unconditionally → identical to pre-cycle behavior.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CAMERA_COVERED_ROOMS,
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_TIMEOUT,
    DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED,
    DEFAULT_OCCUPANCY_TIMEOUT,
    DOMAIN,
    TRACKING_STATUS_ACTIVE,
)
from .domain_coordinators.house_state import HouseState

_LOGGER = logging.getLogger(__name__)

# House states in which the veto is legal. Mirrors the plan's Invariant V.
# HOME_DAY, HOME_NIGHT, SLEEP, WAKING all imply someone is in the house —
# we do NOT suppress comfort-fan turn_on under those states.
_AWAY_STATES = frozenset({HouseState.AWAY, HouseState.VACATION})

# D-MED-2 fix (rung-1 module constant): entity-name heuristic for mmWave /
# radar / presence hybrids that operators have historically misfiled under
# CONF_MOTION_SENSORS (audit Amendment 2 — ~17 rooms with Hobeian/Tuya
# hybrids). device_class cannot distinguish mmWave from PIR (both report
# `motion` or `occupancy`) so we exclude by name. Motion sensors named for
# a specific technology (pir, ir) or bare `motion` still count.
MMWAVE_NAME_PATTERN = re.compile(
    r"(mmwave|radar|presence|ld2410|ld2412)", re.IGNORECASE
)


def is_veto_relevant(hass: HomeAssistant) -> bool:
    """Cheap early-out — True only when veto could plausibly fire.

    Callers use this BEFORE any O(N) config-entry scan or per-room
    merged-config construction, so HOME ticks don't pay for scans that
    would ultimately no-op. Fails OPEN (returns True) on any error so a
    stuck house_state read does not silently mask legitimate vetos.
    """
    try:
        return _get_house_state(hass) in _AWAY_STATES
    except Exception:  # noqa: BLE001 — defensive
        return True


def _get_house_state(hass: HomeAssistant) -> str:
    """Read house_state via the presence coordinator (matches fan-recheck pattern).

    Same accessor as presence_fan_recheck.py:373. Fails OPEN to empty string
    if presence isn't wired yet (boot transient) — that yields no veto,
    which is the safe direction.

    D-MED-1 adjudication (accepted-risk, review fix-up pass):
    Empty-string fail-open is DELIBERATE. During HA boot ordering the
    coordinator_manager / presence coordinator may not be wired yet even
    though house_state defaults to AWAY. Suppressing a legitimate
    post-restart fan (family home, HA restarting) is a worse operator
    experience than up to a few minutes of fan runtime in an empty house.
    Trip-wire for the empty-house-fan case is the D7 per-room veto counter
    (get_veto_count) — a spike there without a HOME transition proves the
    residual matters. Do not change this to fail-closed without also
    landing a boot-settle proxy that reliably distinguishes "presence not
    wired yet" from "house is actually AWAY".
    """
    try:
        mgr = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if mgr is None:
            return ""
        presence = getattr(mgr, "coordinators", {}).get("presence")
        if presence is None:
            return ""
        return getattr(presence, "house_state", "") or ""
    except Exception:  # noqa: BLE001 — defensive, fail-open
        return ""


def _boot_settle_done(hass: HomeAssistant) -> bool:
    """Mirror presence_fan_recheck.py:406-408 boot-settle gate.

    Fails OPEN (returns True) if the presence coordinator isn't wired yet
    or doesn't expose `_boot_settle_done` — same safe direction as the
    house_state read. Callers that want a veto to be suppressed during
    settle can consult this.
    """
    try:
        mgr = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if mgr is None:
            return True
        presence = getattr(mgr, "coordinators", {}).get("presence")
        if presence is None:
            return True
        return bool(getattr(presence, "_boot_settle_done", True))
    except Exception:  # noqa: BLE001 — defensive, fail-open
        return True


def _has_recent_motion(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """True if any configured motion sensor is ON or transitioned within occupancy_timeout.

    mmWave sensors are EXCLUDED (they live under CONF_MMWAVE_SENSORS, not
    CONF_MOTION_SENSORS — this predicate reads only motion). This is the
    whole point of the veto — mmWave under-fan-interference is exactly
    what we're refusing to trust for comfort-fan actuation.
    """
    motion_sensors = config.get(CONF_MOTION_SENSORS) or []
    if not motion_sensors:
        return False
    # D-MED-2 fix: strip mmWave/radar/presence hybrids that operators have
    # misfiled under CONF_MOTION_SENSORS (see MMWAVE_NAME_PATTERN). Without
    # this, a fan-interfered mmWave "on" would defeat the veto — exactly
    # the failure mode this cycle exists to prevent.
    motion_sensors = [
        eid for eid in motion_sensors
        if isinstance(eid, str) and not MMWAVE_NAME_PATTERN.search(eid)
    ]
    if not motion_sensors:
        return False
    try:
        timeout_s = int(
            config.get(CONF_OCCUPANCY_TIMEOUT, DEFAULT_OCCUPANCY_TIMEOUT)
        )
    except (TypeError, ValueError):
        timeout_s = DEFAULT_OCCUPANCY_TIMEOUT
    now = dt_util.utcnow()
    for entity_id in motion_sensors:
        try:
            state = hass.states.get(entity_id)
        except Exception as exc:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "fan_veto: motion-state read failed for %s: %s (fail-open)",
                entity_id, exc,
            )
            continue
        if state is None:
            continue
        if state.state == STATE_ON:
            return True
        # A-L1 fix + B-L2 boot-transient guard: a "recent transition" only
        # counts as motion if the CURRENT state is STATE_OFF — meaning
        # motion just ENDED within the timeout (someone was here moments
        # ago). Any other current state (unavailable, unknown, "on" — the
        # "on" case already returned above) means the transition is either
        # boot-transient noise (unavailable→off on restart) or a live
        # signal we already handled. Without this scope, a boot flip from
        # unavailable to off would spuriously read as "recent motion" for
        # the whole occupancy_timeout window post-restart.
        if state.state != STATE_OFF:
            continue
        # Recently transitioned OFF (e.g. motion just ended within timeout).
        last_changed = getattr(state, "last_changed", None)
        if last_changed is None:
            continue
        try:
            age = (now - last_changed).total_seconds()
        except Exception as exc:  # noqa: BLE001 — tz mismatch / naive dt safety
            _LOGGER.warning(
                "fan_veto: motion last_changed age calc failed for %s: %s "
                "(fail-open)", entity_id, exc,
            )
            continue
        if age <= timeout_s:
            return True
    return False


def _has_ble_present(hass: HomeAssistant, room_name: str) -> bool:
    """True if any BLE-tracked person is currently in this room.

    Delegates to person_coordinator.get_persons_in_room — the same
    primitive presence.py:_trustworthy_persons_in_room reads. We do NOT
    apply the phone-left-behind filter here: for a veto (belt-and-
    suspenders), broader trust means less suppression — the safe
    direction. Fails OPEN to "no BLE" on any lookup error.
    """
    if not room_name:
        return False
    try:
        person_coord = hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord is None:
            return False
        persons = person_coord.get_persons_in_room(room_name) or []
        if not persons:
            return False
        # D-LOW-2 fix: filter to persons whose tracker is ACTIVE. A frozen
        # tracker (STALE / LOST) would otherwise defeat the veto with a
        # stale room mapping (person_coordinator.py:167-174, 320-331). The
        # `data` dict is the same source get_room_occupants iterates —
        # field name `tracking_status`, value `TRACKING_STATUS_ACTIVE`.
        # If the coordinator doesn't expose `data` (older shape), fall
        # open to the pre-filter behavior (any-present).
        pdata = getattr(person_coord, "data", None)
        if not isinstance(pdata, dict):
            return True
        for person_name in persons:
            info = pdata.get(person_name)
            if not isinstance(info, dict):
                # Unknown shape — fail-open on this person (treat as active).
                return True
            if info.get("tracking_status", TRACKING_STATUS_ACTIVE) == \
                    TRACKING_STATUS_ACTIVE:
                return True
        return False
    except Exception as exc:  # noqa: BLE001 — defensive
        _LOGGER.warning(
            "fan_veto: BLE-present read failed for room=%s: %s (fail-open)",
            room_name, exc,
        )
        return False


def _has_camera_person(
    hass: HomeAssistant, room_name: str, config: dict[str, Any]
) -> bool:
    """True if this room is camera-covered AND a camera-person signal is ON.

    D5 (2026-08-01): coverage is now derived from CONFIG PRESENCE
    (CONF_ROOM_CAMERAS non-empty) instead of the hand-frozen
    CAMERA_COVERED_ROOMS allowlist. The allowlist is retained as an
    ADDITIVE bridge (Study A continuity) while the room-camera fusion
    cycle beds in; delete in a follow-up cycle after grep confirms zero
    remaining consumers.

    Camera-person state is read from the D3 fused sensor
    ``binary_sensor.<room_slug>_camera_person_detected`` rather than from
    the raw per-camera entities — the fusion machinery already applies
    F1/F2/F3 correlation fixes.
    """
    if not room_name:
        return False
    # CONF_DISABLE_CAMERA_PRESENCE is authoritative — respect it even if
    # room_cameras is configured.
    try:
        from .const import CONF_DISABLE_CAMERA_PRESENCE, CONF_ROOM_CAMERAS  # noqa: PLC0415
    except Exception:
        CONF_DISABLE_CAMERA_PRESENCE = "disable_camera_presence"  # type: ignore
        CONF_ROOM_CAMERAS = "room_cameras"  # type: ignore
    if config.get(CONF_DISABLE_CAMERA_PRESENCE):
        return False

    # Coverage: config presence OR legacy allowlist membership (additive).
    room_cams = config.get(CONF_ROOM_CAMERAS) or []
    covered_by_config = bool(room_cams)
    room_norm = room_name.strip().casefold()
    covered_norm = {c.strip().casefold() for c in CAMERA_COVERED_ROOMS}
    covered_by_allowlist = room_norm in covered_norm
    if not (covered_by_config or covered_by_allowlist):
        return False

    # Prefer the D3 fused sensor when this room has ROOM_CAMERAS configured
    # (fusion is active). Allowlist-only rooms without room_cameras stay on
    # the legacy per-entity read path.
    if covered_by_config:
        slug = room_name.strip().lower().replace(" ", "_")
        fused_id = f"binary_sensor.{slug}_camera_person_detected"
        try:
            fused_state = hass.states.get(fused_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "fan_veto: fused-sensor read failed for %s: %s (fail-open)",
                fused_id, exc,
            )
            fused_state = None
        if fused_state is not None:
            return fused_state.state == STATE_ON

    # Legacy fallback: read raw per-camera entities from the old key.
    cam_entities = config.get(CONF_CAMERA_PERSON_ENTITIES) or []
    for entity_id in cam_entities:
        try:
            state = hass.states.get(entity_id)
        except Exception as exc:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "fan_veto: camera-person state read failed for %s: %s "
                "(fail-open)", entity_id, exc,
            )
            continue
        if state is not None and state.state == STATE_ON:
            return True
    return False


def _room_has_trusted_presence(
    hass: HomeAssistant, room_name: str, config: dict[str, Any]
) -> bool:
    """Trusted presence = PIR-recent OR BLE-in-room OR camera-person (covered).

    mmWave is EXCLUDED by construction — the veto exists precisely because
    a mmWave-only signal is not trustworthy under fan interference.
    """
    return (
        _has_recent_motion(hass, config)
        or _has_ble_present(hass, room_name)
        or _has_camera_person(hass, room_name, config)
    )


def should_veto_comfort_fan(
    hass: HomeAssistant, room_name: str, config: dict[str, Any]
) -> bool:
    """Shared predicate — return True to SUPPRESS a comfort-fan turn_on.

    Contract:
      - Called ONLY from comfort-fan `turn_on` paths (never from
        turn_off, humidity, safety, or manual paths).
      - Kill switch: CONF_COMFORT_FAN_AWAY_VETO_ENABLED=False → returns False.
      - Fails OPEN on any internal error (returns False) — a stuck helper
        must never suppress fan actuation silently.
    """
    try:
        # A-M1 / B-M1 fix rationale — empty-config fail-open is enforced
        # AT THE CALLER, not here. The hvac_fans update() + restore paths
        # skip calling this predicate when their merged-config scan fails
        # to locate the room's entry (see `if merged and
        # should_veto_comfort_fan(...)` guards). Room-tier automation.py
        # and actuator_reconciler.py always pass a real self.config /
        # entry-derived cfg — never empty — so no defensive check is
        # needed inside the helper.
        if not config.get(
            CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
            DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED,
        ):
            return False
        # B-H1 fix: boot-settle gate. house_state boots AWAY but the
        # presence coordinator may not have completed its first pass yet,
        # so a legitimate post-restart fan (family home) would otherwise
        # be suppressed. Fail-open during settle (mirrors
        # presence_fan_recheck.py:406-408).
        if not _boot_settle_done(hass):
            return False
        house_state = _get_house_state(hass)
        if house_state not in _AWAY_STATES:
            return False
        if _room_has_trusted_presence(hass, room_name, config):
            return False
        _record_veto(hass, room_name)
        _LOGGER.info(
            "comfort fan veto (house_state=%s, room=%s) — no trusted presence",
            house_state, room_name or "?",
        )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-OPEN on any error
        _LOGGER.debug(
            "fan_veto: unexpected error evaluating veto for room=%s: %s",
            room_name, exc,
        )
        return False


# ------------------------------------------------------------------
# D7 observability — per-room veto counter surfaced via binary_sensor
# ------------------------------------------------------------------

_COUNTS_KEY = "comfort_fan_veto_counts"


def _record_veto(hass: HomeAssistant, room_name: str) -> None:
    """Increment the per-room veto counter (D7 observability)."""
    if not room_name:
        return
    try:
        bucket = hass.data.setdefault(DOMAIN, {}).setdefault(_COUNTS_KEY, {})
        bucket[room_name] = int(bucket.get(room_name, 0)) + 1
    except Exception:  # noqa: BLE001 — never fail actuation on counter I/O
        pass


def get_veto_count(hass: HomeAssistant, room_name: str) -> int:
    """Return the current per-room comfort-fan veto count (D7)."""
    try:
        bucket = hass.data.get(DOMAIN, {}).get(_COUNTS_KEY, {}) or {}
        return int(bucket.get(room_name, 0))
    except Exception:  # noqa: BLE001
        return 0

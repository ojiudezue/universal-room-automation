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
from typing import Any

from homeassistant.const import STATE_ON
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
)
from .domain_coordinators.house_state import HouseState

_LOGGER = logging.getLogger(__name__)

# House states in which the veto is legal. Mirrors the plan's Invariant V.
# HOME_DAY, HOME_NIGHT, SLEEP, WAKING all imply someone is in the house —
# we do NOT suppress comfort-fan turn_on under those states.
_AWAY_STATES = frozenset({HouseState.AWAY, HouseState.VACATION})


def _get_house_state(hass: HomeAssistant) -> str:
    """Read house_state via the presence coordinator (matches fan-recheck pattern).

    Same accessor as presence_fan_recheck.py:373. Fails OPEN to empty string
    if presence isn't wired yet (boot transient) — that yields no veto,
    which is the safe direction.
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
        except Exception:  # noqa: BLE001 — defensive
            continue
        if state is None:
            continue
        if state.state == STATE_ON:
            return True
        # Recently transitioned (e.g. off but flipped within timeout).
        last_changed = getattr(state, "last_changed", None)
        if last_changed is None:
            continue
        try:
            age = (now - last_changed).total_seconds()
        except Exception:  # noqa: BLE001 — tz mismatch / naive dt safety
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
        return bool(persons)
    except Exception:  # noqa: BLE001 — defensive
        return False


def _has_camera_person(
    hass: HomeAssistant, room_name: str, config: dict[str, Any]
) -> bool:
    """True if this room is camera-covered AND a camera-person signal is ON.

    Per PLANNING Amendment 1: only rooms in CAMERA_COVERED_ROOMS consult
    the camera leg. Uncovered rooms (no camera) — this returns False and
    the trusted-presence check falls back to PIR + BLE only.
    """
    if not room_name or room_name not in CAMERA_COVERED_ROOMS:
        return False
    cam_entities = config.get(CONF_CAMERA_PERSON_ENTITIES) or []
    for entity_id in cam_entities:
        try:
            state = hass.states.get(entity_id)
        except Exception:  # noqa: BLE001 — defensive
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
        if not config.get(
            CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
            DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED,
        ):
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

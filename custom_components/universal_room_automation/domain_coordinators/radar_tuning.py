"""Radar tuning — Phase A (URA-SENSOR-TUNING-1 Rev 2).

Scope: Hobeian ZK/ZX presence radars only (family ``zigbee_zk_zx``).
Operator chooses per-field named buckets in the room options flow;
URA sends the chosen values once on save (and on operator-triggered
re-apply). URA never writes at boot, never writes to a non-ZK/ZX
device, never writes to a field whose UI value is "Leave as is".

Falsifiable invariant (plan §Falsifiable invariant):
  URA will only send values that the operator set in URA for that
  entity. "Leave as is" = never write. No boot write. No autonomous
  reasserter.

This module has NO listener, NO retry, NO scheduled re-check. The HA
``number.*`` state is Z2M's cached last-write (plan §Measurement
findings) — URA records what it SENT, not what the device applied.
"""
from __future__ import annotations

import logging
from typing import Any

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# --- Family guard (REUSES sensor_capability.FAMILY_BY_MODEL_ID) ---
_ZK_ZX_FAMILY = "zigbee_zk_zx"

# --- Managed field catalogue (rung 1 — change requires review) ---
#
# Field -> HA number entity suffix on the SAME device as the room's
# ``presence_sensors`` binary_sensor. Z2M names these consistently
# across ZG-204ZK and ZG-204ZX firmwares (plan §Measurement findings
# cites `number.mmwave_zigbee_studya_motion_detection_sensitivity`
# etc). ``anti_interference`` deferred (Rev 2 plan Finding 6).
FIELD_MOTION_SENSITIVITY = "motion_sensitivity"
FIELD_STATIC_SENSITIVITY = "static_sensitivity"
FIELD_DETECTION_DISTANCE = "detection_distance"
FIELD_FADING_TIME = "fading_time"

MANAGED_FIELDS: tuple[str, ...] = (
    FIELD_MOTION_SENSITIVITY,
    FIELD_STATIC_SENSITIVITY,
    FIELD_DETECTION_DISTANCE,
    FIELD_FADING_TIME,
)

# Suffix of the sibling number.* entity on the same device. Match on
# ``.endswith`` of the registry entity_id — tolerates Z2M's room-token
# prefix (``mmwave_zigbee_studya_...``) without hard-coding it.
FIELD_ENTITY_SUFFIX: dict[str, str] = {
    FIELD_MOTION_SENSITIVITY: "_motion_detection_sensitivity",
    FIELD_STATIC_SENSITIVITY: "_static_detection_sensitivity",
    FIELD_DETECTION_DISTANCE: "_detection_distance",
    FIELD_FADING_TIME: "_fading_time",
}

# --- Named-bucket values (rung 1 — change requires review) ---
MOTION_SENSITIVITY_BUCKETS: dict[str, int] = {"low": 4, "medium": 6, "high": 8}
STATIC_SENSITIVITY_BUCKETS: dict[str, int] = {"low": 4, "medium": 6, "high": 8}
# Detection distance in metres; clipped to live number.* max at render time.
DETECTION_DISTANCE_BUCKETS: dict[str, float] = {
    "short": 3.0,
    "standard": 4.0,
    "long": 6.0,
}
# Hold-time after last movement (seconds). Longer = never misses a person
# (delays release when the room empties); shorter = risks releasing while
# someone is still present.
FADING_TIME_BUCKETS: dict[str, int] = {
    "short": 30,
    "standard": 60,
    "long": 120,
    "very_long": 300,
}

# --- "Leave as is" sentinel ---
# Rendered as a dropdown option; on save, the save handler OMITS the
# field entirely from the per-entity dict. Absent key = Leave-as-is =
# URA never writes. Also accepted here for defence-in-depth: if a
# saved dict ever carries this string, treat as absent.
LEAVE_AS_IS_SENTINEL = "__leave_as_is__"


def _is_leave_as_is(value: Any) -> bool:
    """Return True when ``value`` means "URA must not write this field"."""
    if value is None:
        return True
    if isinstance(value, str) and value == LEAVE_AS_IS_SENTINEL:
        return True
    return False


def resolve_zk_zx_tuning_entities(
    hass: Any, binary_sensor_entity_id: str,
) -> dict[str, str] | None:
    """Resolve the sibling ``number.*`` tuning entities for a ZK/ZX radar.

    Returns ``None`` when the family is NOT ``zigbee_zk_zx`` (ZV, PIR,
    LD2410, generic_radar, unknown). Otherwise returns a mapping of
    ``{field_name: entity_id}`` for the managed fields that exist as
    number entities on the device.

    Resolution is registry-first and performed FRESH on every call —
    no cached entity_id string (lesson from
    ``coordinator._resolve_room_switch_entity_id`` /
    ``coordinator.py:3028-3074`` and plan review Finding 11).

    Reads with try/except so a registry hiccup never raises into the
    options-flow save path.
    """
    if not isinstance(binary_sensor_entity_id, str):
        return None
    try:
        from .. import fan_veto as _fv  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — importing resolver must never raise
        return None
    try:
        family = _fv.resolve_sensor_family(hass, binary_sensor_entity_id)
    except Exception:  # noqa: BLE001
        family = None
    if family != _ZK_ZX_FAMILY:
        return None
    try:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — HA registry unavailable
        return None
    try:
        registry = er.async_get(hass)
        ent = registry.async_get(binary_sensor_entity_id)
    except Exception:  # noqa: BLE001
        return None
    if ent is None or not getattr(ent, "device_id", None):
        return None
    device_id = ent.device_id
    # Enumerate every registry entry for this device, filter to
    # domain == "number", match tracked suffixes.
    try:
        entries = er.async_entries_for_device(
            registry, device_id, include_disabled_entities=False,
        )
    except Exception:  # noqa: BLE001
        return None
    found: dict[str, str] = {}
    for e in entries or ():
        eid = getattr(e, "entity_id", None)
        if not isinstance(eid, str) or not eid.startswith("number."):
            continue
        for field, suffix in FIELD_ENTITY_SUFFIX.items():
            if field in found:
                continue
            if eid.endswith(suffix):
                found[field] = eid
                break
    return found if found else {}


def _get_number_max(hass: Any, number_entity_id: str) -> float | None:
    """Return the live ``max`` attribute of ``number_entity_id`` or None.

    Used by the options-flow to clip the detection-distance bucket
    labels/values to the device's actual firmware limit (plan D1).
    """
    try:
        state = hass.states.get(number_entity_id)
    except Exception:  # noqa: BLE001
        return None
    if state is None:
        return None
    try:
        maxv = state.attributes.get("max")
    except Exception:  # noqa: BLE001
        return None
    if maxv is None:
        return None
    try:
        return float(maxv)
    except (TypeError, ValueError):
        return None


def clipped_distance_buckets(
    hass: Any, number_entity_id: str | None,
) -> dict[str, float]:
    """Return distance buckets clipped to the live number entity max.

    If ``max`` is unavailable (entity missing / no attribute), return
    the module defaults unchanged. If ``max`` is lower than a bucket's
    nominal value, that bucket's value clips down to ``max``.
    """
    out: dict[str, float] = dict(DETECTION_DISTANCE_BUCKETS)
    if not number_entity_id:
        return out
    maxv = _get_number_max(hass, number_entity_id)
    if maxv is None:
        return out
    return {k: (min(v, maxv) if v > maxv else v) for k, v in out.items()}


def _diff_managed(
    previous: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Return ``{entity_id: {field: value}}`` for CHANGED managed fields.

    "Leave as is" (absent key or sentinel) in ``new`` is NEVER sent —
    even if ``previous`` had a value: the operator just UN-managed the
    field. Only transitions ``previous != new`` where ``new`` holds a
    real managed value are emitted.
    """
    new = new or {}
    changes: dict[str, dict[str, Any]] = {}
    for entity_id, new_fields in new.items():
        if not isinstance(entity_id, str) or not isinstance(new_fields, dict):
            continue
        prev_fields = (previous or {}).get(entity_id) or {}
        if not isinstance(prev_fields, dict):
            prev_fields = {}
        for field in MANAGED_FIELDS:
            if field not in new_fields:
                continue
            nv = new_fields.get(field)
            if _is_leave_as_is(nv):
                continue
            pv = prev_fields.get(field)
            if _is_leave_as_is(pv) or pv != nv:
                changes.setdefault(entity_id, {})[field] = nv
    return changes


async def async_send_radar_settings(
    hass: Any,
    *,
    previous_settings: dict[str, Any] | None,
    new_settings: dict[str, Any] | None,
) -> int:
    """Send ``number.set_value`` once per CHANGED managed field.

    Resolves each binary_sensor entity_id's sibling ``number.*`` fresh
    through the device registry (no cached entity_id string). Non-ZK/ZX
    binary_sensor entries in ``new_settings`` are silently ignored
    (family guard).

    Returns the count of service calls emitted. Logs each emit at INFO
    with "sent" (never "applied"/"verified" — see plan §Measurement).
    """
    changes = _diff_managed(previous_settings, new_settings)
    if not changes:
        return 0
    sent = 0
    for binary_sensor_eid, fields in changes.items():
        resolved = resolve_zk_zx_tuning_entities(hass, binary_sensor_eid)
        if not resolved:
            # Non-ZK/ZX or no managed number entities on the device.
            # Family guard: NEVER write to a non-ZK/ZX device, even if
            # the saved dict somehow holds an entry for one.
            _LOGGER.debug(
                "radar_settings: skipping non-zk/zx or no number siblings "
                "for binary_sensor=%s",
                binary_sensor_eid,
            )
            continue
        for field, value in fields.items():
            number_eid = resolved.get(field)
            if not number_eid:
                _LOGGER.debug(
                    "radar_settings: no sibling number for field=%s on %s",
                    field, binary_sensor_eid,
                )
                continue
            try:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": number_eid, "value": value},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001 — one bad entity must not break the batch
                _LOGGER.warning(
                    "radar_settings: service call failed entity=%s value=%s",
                    number_eid, value, exc_info=True,
                )
                continue
            sent += 1
            _LOGGER.info(
                "radar_settings: sent entity=%s field=%s value=%s",
                number_eid, field, value,
            )
    return sent


async def async_reapply_radar_settings(
    hass: Any, room_entry_id: str,
) -> int:
    """Service handler for ``universal_room_automation.reapply_radar_settings``.

    Forces every managed field in the room's saved ``radar_settings`` to be
    re-sent (diff computed against an EMPTY previous dict). This is the
    operator's recovery path after a factory reset or an out-of-band
    Z2M edit (plan D4).
    """
    if not isinstance(room_entry_id, str) or not room_entry_id:
        _LOGGER.warning(
            "reapply_radar_settings: missing/invalid room_entry_id",
        )
        return 0
    try:
        from homeassistant.config_entries import ConfigEntryState  # noqa: F401,PLC0415
        entry = hass.config_entries.async_get_entry(room_entry_id)
    except Exception:  # noqa: BLE001
        entry = None
    if entry is None:
        _LOGGER.warning(
            "reapply_radar_settings: unknown entry_id=%s", room_entry_id,
        )
        return 0
    # The saved radar_settings live under entry.options (preferred) or
    # entry.data (fallback). Mirrors the {data, options} merge pattern
    # used by other room reads.
    try:
        from ..const import CONF_RADAR_SETTINGS  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return 0
    options = getattr(entry, "options", {}) or {}
    data = getattr(entry, "data", {}) or {}
    saved = options.get(CONF_RADAR_SETTINGS)
    if saved is None:
        saved = data.get(CONF_RADAR_SETTINGS)
    if not isinstance(saved, dict) or not saved:
        _LOGGER.info(
            "reapply_radar_settings: entry=%s has no managed radar fields",
            room_entry_id,
        )
        return 0
    return await async_send_radar_settings(
        hass, previous_settings=None, new_settings=saved,
    )

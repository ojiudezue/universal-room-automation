"""Sensor CAPABILITY layer (SENSOR-CAPABILITY-1, D1).

Plan: ``docs/planning/PLANNING_sensor_capability_vs_role.md``.

The three CONF sensor lists (``CONF_MOTION_SENSORS`` / ``CONF_MMWAVE_SENSORS``
/ ``CONF_OCCUPANCY_SENSORS``) remain the WIRING declaration: they tell URA
what to subscribe to, and their kind labels stay ``TIER1_KINDS``-valued for
the substrate dispatch channel (I3 — see
``presence._audit_provenance_invariants``).

CAPABILITY sits above the wiring. It answers "what IS this hardware?"
(bed / mmwave / camera-presence / …) — a superset of ``TIER1_KINDS``.
Operator declares only the ambiguous cases via
``CONF_SENSOR_CAPABILITIES``; for every other entity, capability derives
1:1 from CONF-list membership so that with NO declarations, behaviour is
byte-identical to today (invariant I1).

This module is PURE: no HA imports, no I/O, no listeners. It reads a
room_config dict (as produced by ``{**entry.data, **entry.options}``) and
an entity_id and returns a ``SensorCapability`` (or ``None`` when the
entity is not wired into the room's Tier-1 sensor set).

Consumed by :mod:`sensor_role` — that module runs the role-query matrix
against a capability, per query.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from ..const import (
    CAPABILITY_KIND_BED,
    CAPABILITY_KIND_BLE_PRESENCE,
    CAPABILITY_KIND_CAMERA_PRESENCE,
    CAPABILITY_KIND_MMWAVE,
    CAPABILITY_KIND_MOTION,
    CAPABILITY_KIND_OCCUPANCY,
    CAPABILITY_KIND_PIR,
    CAPABILITY_KIND_PIR_SPLIT,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_SENSOR_CAPABILITIES,
    FAILURE_MODE_CORRELATED_BRIDGE,
    FAILURE_MODE_CORRELATED_WIRELESS,
    FAILURE_MODE_PHYSICAL_INDEPENDENT,
    FAILURE_MODE_UNKNOWN,
    TIER1_CAPABILITIES,
    TRUST_CLASS_STRONG_EVIDENCE,
    TRUST_CLASS_WEAK_WITNESS,
    TRUST_CLASS_WITNESS,
    TRUST_CLASSES,
)

# ----------------------------------------------------------------------
# CONF-list -> default (kind, trust_class, failure_mode)
# ----------------------------------------------------------------------
#
# These are the byte-identical defaults for entities appearing ONLY in a
# CONF list with no ``CONF_SENSOR_CAPABILITIES`` entry. They are the
# encoding of today's implicit rule: "the CONF list IS the kind".
#
# Trust class defaults are conservative: motion (PIR) is a "witness"
# (transitions carry corroboration weight but a stuck PIR is not
# unspoofable), mmwave/occupancy are "weak_witness" (they are the very
# sensors D2 watches for stuck behaviour).
_DEFAULT_TRUST_BY_CONF_KIND: Dict[str, str] = {
    CAPABILITY_KIND_MOTION: TRUST_CLASS_WITNESS,
    CAPABILITY_KIND_MMWAVE: TRUST_CLASS_WEAK_WITNESS,
    CAPABILITY_KIND_OCCUPANCY: TRUST_CLASS_WEAK_WITNESS,
}
_DEFAULT_FAILURE_MODE_BY_CONF_KIND: Dict[str, str] = {
    CAPABILITY_KIND_MOTION: FAILURE_MODE_UNKNOWN,
    CAPABILITY_KIND_MMWAVE: FAILURE_MODE_UNKNOWN,
    CAPABILITY_KIND_OCCUPANCY: FAILURE_MODE_UNKNOWN,
}

# Extended vocabulary defaults for operator-declared capabilities (used
# when the operator declares "kind" but omits trust_class / failure_mode).
DEFAULT_TRUST_BY_KIND: Dict[str, str] = {
    CAPABILITY_KIND_MOTION: TRUST_CLASS_WITNESS,
    CAPABILITY_KIND_MMWAVE: TRUST_CLASS_WEAK_WITNESS,
    CAPABILITY_KIND_OCCUPANCY: TRUST_CLASS_WEAK_WITNESS,
    CAPABILITY_KIND_PIR: TRUST_CLASS_WITNESS,
    CAPABILITY_KIND_PIR_SPLIT: TRUST_CLASS_WITNESS,
    CAPABILITY_KIND_BED: TRUST_CLASS_STRONG_EVIDENCE,
    CAPABILITY_KIND_CAMERA_PRESENCE: TRUST_CLASS_WITNESS,
    CAPABILITY_KIND_BLE_PRESENCE: TRUST_CLASS_WITNESS,
}
DEFAULT_FAILURE_MODE_BY_KIND: Dict[str, str] = {
    CAPABILITY_KIND_MOTION: FAILURE_MODE_UNKNOWN,
    CAPABILITY_KIND_MMWAVE: FAILURE_MODE_UNKNOWN,
    CAPABILITY_KIND_OCCUPANCY: FAILURE_MODE_UNKNOWN,
    CAPABILITY_KIND_PIR: FAILURE_MODE_UNKNOWN,
    CAPABILITY_KIND_PIR_SPLIT: FAILURE_MODE_UNKNOWN,
    CAPABILITY_KIND_BED: FAILURE_MODE_PHYSICAL_INDEPENDENT,
    CAPABILITY_KIND_CAMERA_PRESENCE: FAILURE_MODE_CORRELATED_BRIDGE,
    CAPABILITY_KIND_BLE_PRESENCE: FAILURE_MODE_CORRELATED_WIRELESS,
}

# Precedence order for CONF-list membership. Matches
# ``occupancy_substrate._KIND_PRECEDENCE`` byte-for-byte (motion → mmwave
# → occupancy). An entity appearing in multiple CONF lists resolves to
# the FIRST match in this tuple — the same precedence the substrate uses
# at ``occupancy_substrate.py:79``. See P15 in
# ``docs/planning/CATALOG_cross_correlation_primitives.md``.
_CONF_PRECEDENCE: tuple = (
    (CAPABILITY_KIND_MOTION, CONF_MOTION_SENSORS),
    (CAPABILITY_KIND_MMWAVE, CONF_MMWAVE_SENSORS),
    (CAPABILITY_KIND_OCCUPANCY, CONF_OCCUPANCY_SENSORS),
)


@dataclass(frozen=True)
class SensorCapability:
    """Immutable per-entity capability descriptor.

    Attributes:
        kind: capability vocabulary; ∈ ``TIER1_CAPABILITIES``.
        trust_class: ∈ ``TRUST_CLASSES``.
        failure_mode: ∈ ``FAILURE_MODES``.
        source: ``"conf_list"`` (derived from CONF membership) or
            ``"override"`` (operator-declared via
            ``CONF_SENSOR_CAPABILITIES``).
    """

    kind: str
    trust_class: str
    failure_mode: str
    source: str  # "conf_list" | "override"


def _conf_list_kind(
    room_config: Mapping[str, object], entity_id: str,
) -> Optional[str]:
    """Return the CONF-list-derived kind for ``entity_id`` in this room,
    or None if the entity is not in any of the three Tier-1 CONF lists.

    Precedence matches ``occupancy_substrate._KIND_PRECEDENCE``.
    """
    for kind, conf_key in _CONF_PRECEDENCE:
        try:
            entities = room_config.get(conf_key, []) or []  # type: ignore[union-attr]
        except Exception:  # pragma: no cover — defensive
            entities = []
        if entity_id in entities:
            return kind
    return None


def derive_capability(
    room_config: Mapping[str, object], entity_id: str,
) -> Optional[SensorCapability]:
    """Return the resolved capability for ``entity_id`` in ``room_config``.

    Precedence:

    1. If an operator declaration exists in
       ``room_config[CONF_SENSOR_CAPABILITIES][entity_id]``, it wins.
       Only ``"kind"`` is required — trust_class/failure_mode default per
       kind. Unknown kind / trust_class / failure_mode falls THROUGH to
       the CONF-list derivation (the override is treated as absent) so a
       malformed operator entry cannot silently take effect.
    2. Otherwise, CONF-list membership determines the kind and the
       byte-identical default trust/failure values.
    3. Otherwise, ``None`` (the entity is not part of this room's
       Tier-1 wiring — the substrate would not have subscribed to it).

    Pure: no side effects, no HA calls. Safe to call per-tick.
    """
    if not entity_id:
        return None
    overrides = {}
    try:
        raw = room_config.get(CONF_SENSOR_CAPABILITIES) or {}  # type: ignore[union-attr]
        if isinstance(raw, dict):
            overrides = raw
    except Exception:  # pragma: no cover — defensive
        overrides = {}

    override = overrides.get(entity_id) if overrides else None
    if isinstance(override, dict):
        kind = override.get("kind")
        if kind in TIER1_CAPABILITIES:
            trust = override.get("trust_class") or DEFAULT_TRUST_BY_KIND.get(
                kind, TRUST_CLASS_WITNESS,
            )
            if trust not in TRUST_CLASSES:
                trust = DEFAULT_TRUST_BY_KIND.get(kind, TRUST_CLASS_WITNESS)
            failure = (
                override.get("failure_mode")
                or DEFAULT_FAILURE_MODE_BY_KIND.get(kind, FAILURE_MODE_UNKNOWN)
            )
            return SensorCapability(
                kind=kind,
                trust_class=trust,
                failure_mode=failure,
                source="override",
            )
        # Malformed override — fall through to CONF-list derivation.

    conf_kind = _conf_list_kind(room_config, entity_id)
    if conf_kind is None:
        return None
    return SensorCapability(
        kind=conf_kind,
        trust_class=_DEFAULT_TRUST_BY_CONF_KIND[conf_kind],
        failure_mode=_DEFAULT_FAILURE_MODE_BY_CONF_KIND[conf_kind],
        source="conf_list",
    )


def validate_capabilities_payload(
    room_config: Mapping[str, object],
    payload: Mapping[str, Mapping[str, str]],
) -> list[str]:
    """Return a list of human-readable validation errors; empty = valid.

    Used by the config/options flow save handler. Enforces:

    * every entity_id is present in one of the room's three CONF lists;
    * every ``"kind"`` is in ``TIER1_CAPABILITIES``;
    * ``"trust_class"`` (if present) is in ``TRUST_CLASSES``;
    * every entry is a dict.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["sensor_capabilities must be a mapping"]
    known: set = set()
    for _kind, conf_key in _CONF_PRECEDENCE:
        try:
            known.update(room_config.get(conf_key, []) or [])  # type: ignore[union-attr]
        except Exception:  # pragma: no cover — defensive
            pass
    for entity_id, decl in payload.items():
        if not isinstance(decl, dict):
            errors.append(
                f"capability for '{entity_id}' must be a dict, got "
                f"{type(decl).__name__}"
            )
            continue
        if entity_id not in known:
            errors.append(
                f"entity '{entity_id}' is not in this room's motion / "
                f"mmwave / occupancy CONF lists — add it to the "
                f"appropriate list before declaring a capability"
            )
        kind = decl.get("kind")
        if kind is not None and kind not in TIER1_CAPABILITIES:
            errors.append(
                f"entity '{entity_id}': unknown capability kind "
                f"'{kind}' (allowed: {sorted(TIER1_CAPABILITIES)})"
            )
        trust = decl.get("trust_class")
        if trust is not None and trust not in TRUST_CLASSES:
            errors.append(
                f"entity '{entity_id}': unknown trust_class '{trust}' "
                f"(allowed: {sorted(TRUST_CLASSES)})"
            )
    return errors

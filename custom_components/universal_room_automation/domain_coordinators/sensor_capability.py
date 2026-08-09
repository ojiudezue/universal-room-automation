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

import logging
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
    FAILURE_MODES,
    TIER1_CAPABILITIES,
    TRUST_CLASS_STRONG_EVIDENCE,
    TRUST_CLASS_WEAK_WITNESS,
    TRUST_CLASS_WITNESS,
    TRUST_CLASSES,
)

_LOGGER = logging.getLogger(__name__)

# D-MEDIUM-1 (2026-08-09): kinds that would leave a motion-wired entity
# invisible to D2. The candidate loop iterates the mmwave+occupancy CONF
# lists only; the corroborator loop requires CORROBORATOR_FOR_ROOM. An
# override that maps a motion-wired entity to mmwave/occupancy is neither
# scored nor corroborates — it silently disappears. The validator rejects
# such an override.
_NON_CORROBORATOR_KINDS: frozenset = frozenset({
    CAPABILITY_KIND_MMWAVE,
    CAPABILITY_KIND_OCCUPANCY,
})

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
        # D-LOW-2 (2026-08-09): the config/options flow validator rejects
        # unknown/missing kinds, but a hand-edited .storage payload
        # bypasses that guardrail. Log a WARN so the operator can see
        # WHY their bed override "isn't taking effect".
        _LOGGER.warning(
            "sensor_capability: override for entity '%s' has invalid or "
            "missing 'kind' (%r) — falling back to CONF-list derivation. "
            "Valid kinds: %s",
            entity_id, kind, sorted(TIER1_CAPABILITIES),
        )

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
    * ``"kind"`` is REQUIRED and MUST be in ``TIER1_CAPABILITIES``
      (HIGH-A1 2026-08-09 fix-up: a missing ``kind`` used to slip past,
      then silently fall through to CONF-list derivation — no-op'ing the
      operator's declaration);
    * ``"trust_class"`` (if present) is in ``TRUST_CLASSES``;
    * ``"failure_mode"`` (if present) is in ``FAILURE_MODES``
      (MED-A2 2026-08-09 fix-up: typos would flow verbatim onto the
      dataclass and downstream corroboration logic);
    * an override MUST NOT make a ``motion``-wired entity invisible to
      D2 by mapping it to an mmwave/occupancy kind (D-MEDIUM-1
      2026-08-09 fix-up — the entity would be scored by neither loop).
    * every entry is a dict.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["sensor_capabilities must be a mapping"]
    known: set = set()
    motion_wired: set = set()
    try:
        motion_wired = set(
            room_config.get(CONF_MOTION_SENSORS, []) or [],  # type: ignore[union-attr]
        )
    except Exception:  # pragma: no cover — defensive
        motion_wired = set()
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
        if kind is None:
            errors.append(
                f"entity '{entity_id}': 'kind' is required "
                f"(allowed: {sorted(TIER1_CAPABILITIES)})"
            )
        elif kind not in TIER1_CAPABILITIES:
            errors.append(
                f"entity '{entity_id}': unknown capability kind "
                f"'{kind}' (allowed: {sorted(TIER1_CAPABILITIES)})"
            )
        elif (
            entity_id in motion_wired
            and kind in _NON_CORROBORATOR_KINDS
        ):
            # D-MEDIUM-1: motion-wired entity flipped to a non-
            # corroborator kind would be invisible to BOTH D2 loops.
            errors.append(
                f"entity '{entity_id}' is wired via "
                f"CONF_MOTION_SENSORS; declaring kind='{kind}' would "
                f"remove it from the D2 corroborator set AND leave it "
                f"outside the candidate loop (which iterates only the "
                f"mmwave / occupancy CONF lists) — the entity would "
                f"contribute nothing. Move it to the appropriate CONF "
                f"list first, or declare a corroborator-capable kind."
            )
        trust = decl.get("trust_class")
        if trust is not None and trust not in TRUST_CLASSES:
            errors.append(
                f"entity '{entity_id}': unknown trust_class '{trust}' "
                f"(allowed: {sorted(TRUST_CLASSES)})"
            )
        failure = decl.get("failure_mode")
        if failure is not None and failure not in FAILURE_MODES:
            errors.append(
                f"entity '{entity_id}': unknown failure_mode "
                f"'{failure}' (allowed: {sorted(FAILURE_MODES)})"
            )
    return errors

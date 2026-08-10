"""Sensor ROLE resolver (SENSOR-CAPABILITY-1, D2).

Plan: ``docs/planning/PLANNING_sensor_capability_vs_role.md``.

Role is a function of the QUESTION, never a property of the sensor. A
bed sensor is not "always a corroborator" — it IS a corroborator for
CORROBORATOR_FOR_ROOM and it is NOT a candidate for CANDIDATE_FOR_STUCK.
The same query surface will one day answer CREATOR_VS_EXTENDER for the
occupancy tracker's edge-creation gate.

This module is PURE (no HA imports, no I/O). It reads a room_config dict
and returns booleans. Roles are NEVER persisted across a tick (I2).

Migration status:

* v1 (this cycle): CANDIDATE_FOR_STUCK and CORROBORATOR_FOR_ROOM are
  live; the ONLY consumer wired in-cycle is
  ``coordinator._detect_duty_cycle_stuck`` per plan §3.4.
* Other consumers (fan-recheck, provenance aggregation, binary_sensor
  attrs) migrate on their own budget in later cycles.
* CREATOR_VS_EXTENDER is defined so downstream cycles have a stable
  name; the resolver returns a documented placeholder.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping, Optional

from ..const import (
    CAPABILITY_KIND_BED,
    CAPABILITY_KIND_BLE_PRESENCE,
    CAPABILITY_KIND_CAMERA_PRESENCE,
    CAPABILITY_KIND_MMWAVE,
    CAPABILITY_KIND_MOTION,
    CAPABILITY_KIND_OCCUPANCY,
    CAPABILITY_KIND_PIR,
    CAPABILITY_KIND_PIR_SPLIT,
    TRUST_CLASS_STRONG_EVIDENCE,
)
from .sensor_capability import SensorCapability, derive_capability


class RoleQuery(str, Enum):
    """Enumerated role queries.

    A string-Enum so log lines carry a stable, greppable value.
    """

    CANDIDATE_FOR_STUCK = "candidate_for_stuck"
    CORROBORATOR_FOR_ROOM = "corroborator_for_room"
    CREATOR_VS_EXTENDER = "creator_vs_extender"


# Kinds whose capability qualifies as a corroborator (independent-ish
# evidence of presence in the room). Motion / PIR / bed / camera-presence
# / BLE-presence all qualify. mmWave and generic occupancy do NOT — they
# are the very sensors D2 watches for stuck behaviour.
_CORROBORATOR_KINDS: frozenset = frozenset({
    CAPABILITY_KIND_MOTION,
    CAPABILITY_KIND_PIR,
    CAPABILITY_KIND_PIR_SPLIT,
    CAPABILITY_KIND_BED,
    CAPABILITY_KIND_CAMERA_PRESENCE,
    CAPABILITY_KIND_BLE_PRESENCE,
})

# Kinds whose capability makes them CANDIDATES for stuck-signal scoring:
# mmwave + occupancy by default. A strong_evidence trust_class DEMOTES
# an otherwise-mmwave/occupancy entity out of the candidate set (a bed
# sensor operator-declared into CONF_OCCUPANCY_SENSORS becomes a
# corroborator, not a candidate).
_STUCK_CANDIDATE_KINDS: frozenset = frozenset({
    CAPABILITY_KIND_MMWAVE,
    CAPABILITY_KIND_OCCUPANCY,
})


def resolve_role(
    room_config: Mapping[str, object],
    entity_id: str,
    query: RoleQuery,
) -> bool:
    """Return True if ``entity_id`` fulfils ``query`` in ``room_config``.

    Pure: same inputs, same output, no state (I2). Callers ask the
    question they need; the resolver walks the capability derivation
    (:func:`derive_capability`) and applies the role-query matrix.

    Unknown entity (not in this room's Tier-1 wiring) → False for every
    query.

    API contract (A-LOW-3, 2026-08-10): this resolver is well-defined
    ONLY for entities wired into one of the room's three Tier-1 CONF
    lists (``CONF_MOTION_SENSORS`` / ``CONF_MMWAVE_SENSORS`` /
    ``CONF_OCCUPANCY_SENSORS``). The config/options-flow validator
    (``validate_capabilities_payload``) rejects any
    ``CONF_SENSOR_CAPABILITIES`` override whose entity is not present in
    those lists, so the normal path is safe. A caller that BYPASSES that
    validator (e.g. by hand-editing ``.storage`` and calling this
    function on the resulting config) gets CONF-list-derived semantics:
    the override is honoured only if the entity is also wired in a CONF
    list; otherwise ``derive_capability`` returns ``None`` and every
    query answers ``False``. Do NOT rely on this function to answer
    role queries for un-wired entities.
    """
    cap: Optional[SensorCapability] = derive_capability(
        room_config, entity_id,
    )
    if cap is None:
        return False

    if query is RoleQuery.CANDIDATE_FOR_STUCK:
        # A strong_evidence entity is NEVER a candidate for stuck
        # scoring — that is exactly the discriminator that lets an
        # operator declare an mmwave/occupancy-wired entity as
        # strong_evidence and have it stop being judged for being
        # state-normal ON.
        if cap.trust_class == TRUST_CLASS_STRONG_EVIDENCE:
            return False
        return cap.kind in _STUCK_CANDIDATE_KINDS

    if query is RoleQuery.CORROBORATOR_FOR_ROOM:
        if cap.kind in _CORROBORATOR_KINDS:
            return True
        # Strong-evidence-elevated kinds (e.g. a bed sensor operator-
        # declared into CONF_OCCUPANCY_SENSORS with trust=strong_evidence)
        # also corroborate even if their capability kind is not natively
        # in _CORROBORATOR_KINDS.
        if cap.trust_class == TRUST_CLASS_STRONG_EVIDENCE:
            return True
        return False

    if query is RoleQuery.CREATOR_VS_EXTENDER:
        # v1 placeholder — this query is defined so the downstream
        # occupancy-edge cycle has a stable name to migrate to. The
        # v1 answer mirrors today's implicit rule: motion/PIR CREATE an
        # occupancy edge; mmwave/occupancy EXTEND one (they cannot
        # anchor a vacant→occupied transition without motion
        # corroboration under the current trust model). Encoded as a
        # bool: True == creator, False == extender-only. Callers using
        # this query MUST land in a later cycle.
        return cap.kind in {
            CAPABILITY_KIND_MOTION,
            CAPABILITY_KIND_PIR,
            CAPABILITY_KIND_PIR_SPLIT,
        }

    # Unknown query — defensive False (Bug Class #22 discipline: never
    # raise on enum expansion from a stale caller).
    return False

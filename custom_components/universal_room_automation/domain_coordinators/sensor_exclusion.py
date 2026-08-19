"""SensorExclusionSet — shared room-tier sensor-vote untrust primitive.

Part of the Sensor Trust / Exclusion Program (STEP). Formalises the ad-hoc
``stuck_sensors: set[str]`` local that has lived at ``coordinator.py:2498``
since P22, into a proper multi-writer object with per-client provenance and
STEP-EXCLUDE-{1..4} invariant enforcement. See
``docs/planning/PLANNING_sensor_health_surfacing.md`` §D1 for the contract.

Contract (invariants Reviewer D falsifies):

  * STEP-EXCLUDE-1 (fusion contract): if ``is_excluded(e)`` is True at
    fusion time, the sensor's vote contributes 0 to the room's motion/
    presence/occupancy legs. A non-excluded sensor's True vote MUST NOT
    be suppressed by this primitive.
  * STEP-EXCLUDE-2 (byte-identity under empty-clients): if no client
    promoted anything this tick, the fusion output is byte-identical to
    pre-cycle behaviour.
  * STEP-EXCLUDE-3 (client isolation): promotion by client A that later
    becomes ineligible MUST NOT release a promotion by client B whose
    gates still hold. Per-client release semantics.
  * STEP-EXCLUDE-4 (no zone/house propagation): this primitive is scoped
    to the room-tier fusion at ``coordinator.py:2712-2756`` ONLY. Zone /
    house / substrate consumers do NOT import this module.

The migration is BYTE-IDENTICAL for the two pre-existing writers (P22
continuous-on, STUCK-SENSOR-1 D1 dutycycle). Chatter is the first NEW
client, wired concurrently to prove the multi-writer contract.

Design decisions locked (see plan-review-2):

  * Module sibling (this file) — NOT a helper on RoomCoordinator.
    Testability + no coordinator.py bloat.
  * ``reset_tick()`` clears ALL promotions at the top of each tick.
    Every writer re-populates each tick it remains active. This
    preserves today's per-tick recompute behaviour byte-identically —
    NO sticky book, NO cross-tick state on this object.
  * Per-client bookkeeping: {entity_id -> {client -> reason}}. Release
    removes only the requesting client's entry; the entity leaves the
    set when the LAST client releases.
  * Fail-safe on unexpected shapes: every mutator swallows non-string
    inputs at debug and drops the write — this object must never raise
    into the tick-site.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, Set

_LOGGER = logging.getLogger(__name__)


class SensorExclusionSet:
    """Multi-writer, per-client-provenance room-tier exclusion set."""

    __slots__ = ("_room_name", "_by_entity")

    def __init__(self, room_name: str) -> None:
        self._room_name = room_name
        # Shape: {entity_id: {client_name: reason_str}}
        self._by_entity: Dict[str, Dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset_tick(self) -> None:
        """Clear every promotion.

        Called at tick start BEFORE any client's population loop runs.
        See coordinator.py's per-tick ordering:
        ``reset_tick() -> snapshot prev-excluded -> P22 -> STUCK-1 -> chatter``.
        """
        self._by_entity.clear()

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    def promote(self, client: str, entity_id: str, reason: str) -> None:
        """Register ``entity_id`` as excluded on behalf of ``client``.

        Idempotent per (client, entity_id): repeat calls in the same tick
        overwrite ``reason`` silently (no re-log spam). Two DIFFERENT
        clients promoting the same entity both stick — release semantics
        remove only the caller's entry.
        """
        if not isinstance(entity_id, str) or not entity_id:
            _LOGGER.debug(
                "SensorExclusionSet[%s]: promote() dropped non-str entity=%r "
                "from client=%r",
                self._room_name, entity_id, client,
            )
            return
        if not isinstance(client, str) or not client:
            _LOGGER.debug(
                "SensorExclusionSet[%s]: promote() dropped non-str client=%r "
                "for entity=%s",
                self._room_name, client, entity_id,
            )
            return
        by_client = self._by_entity.get(entity_id)
        if by_client is None:
            by_client = {}
            self._by_entity[entity_id] = by_client
        by_client[client] = str(reason) if reason is not None else ""

    def release(self, client: str, entity_id: str) -> None:
        """Remove ``client``'s promotion of ``entity_id``.

        Entity leaves ``excluded()`` iff the LAST remaining client
        released. STEP-EXCLUDE-3: a chatter release MUST NOT drop a
        concurrent stuck_dutycycle promotion.
        """
        by_client = self._by_entity.get(entity_id)
        if not by_client:
            return
        by_client.pop(client, None)
        if not by_client:
            self._by_entity.pop(entity_id, None)

    # ------------------------------------------------------------------
    # Readers (consumed at the 6 fusion sites in coordinator.py)
    # ------------------------------------------------------------------

    def is_excluded(self, entity_id: str) -> bool:
        """Return True iff at least one client currently promotes ``entity_id``."""
        return entity_id in self._by_entity

    def excluded(self) -> Set[str]:
        """Return a snapshot copy of the currently-excluded entity_ids."""
        return set(self._by_entity.keys())

    def provenance(self, entity_id: str) -> Dict[str, str]:
        """Return a copy of ``{client -> reason}`` for ``entity_id``.

        Empty dict if not excluded. Used by the diagnostic surface
        (``UnavailableEntitiesSensor``) and by tests.
        """
        by_client = self._by_entity.get(entity_id)
        if not by_client:
            return {}
        return dict(by_client)

    def clients_for(self, entity_id: str) -> Set[str]:
        """Convenience: set of client names promoting ``entity_id``."""
        by_client = self._by_entity.get(entity_id)
        if not by_client:
            return set()
        return set(by_client.keys())

    # ------------------------------------------------------------------
    # Test / diag helpers (never called on the hot path)
    # ------------------------------------------------------------------

    def entities_for_client(self, client: str) -> Set[str]:
        """Return the set of entities currently promoted by ``client``."""
        return {
            eid for eid, by_client in self._by_entity.items()
            if client in by_client
        }

    def __contains__(self, entity_id: object) -> bool:
        return isinstance(entity_id, str) and entity_id in self._by_entity

    def __iter__(self) -> Iterable[str]:
        return iter(list(self._by_entity.keys()))

    def __len__(self) -> int:
        return len(self._by_entity)

    def __repr__(self) -> str:  # pragma: no cover — debug convenience
        return (
            f"SensorExclusionSet(room={self._room_name!r}, "
            f"count={len(self._by_entity)})"
        )

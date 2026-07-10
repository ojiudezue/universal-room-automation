"""Occupancy substrate — unified per-room, per-kind raw-signal input layer.

The substrate sits BENEATH the room (``coordinator.py`` / ``RoomCoordinator``)
and zone (``presence.py`` / ``ZonePresenceTracker``) tiers as a shared raw-
signal abstraction. It is NOT a new tier and does NOT replace either of the
existing room or zone tiers; both tiers continue to apply their own legitimate
temporal smoothing on top of this common raw view (see
``PLANNING_occupancy_substrate_unification.md`` — Tier-vocabulary discipline).

Responsibilities (per planning doc D1):

1. **Discovery.** For each configured ROOM ConfigEntry (``ENTRY_TYPE_ROOM``),
   read the three CONF lists (``CONF_MOTION_SENSORS``,
   ``CONF_MMWAVE_SENSORS``, ``CONF_OCCUPANCY_SENSORS``) and produce the
   canonical ``(entity_id, room_name, kind)`` triples. NO area-sweep, NO
   substring/name heuristic. Kind is determined exclusively by which CONF
   list slot the entity is in (precedence motion → mmwave → occupancy if
   listed in multiple, with a WARN log for that defensive case).
2. **Listener registration.** One ``async_track_state_change_event``
   subscription per discovered entity. Bug Class #38: every unsub is
   captured and called on re-discovery / teardown.
3. **Per-kind raw state.** ``_raw_state[room_name][kind] -> bool``. Updated
   synchronously on every state-change callback. Unavailable / unknown
   states map to ``False`` (matches ``_handle_occupancy_change`` semantics).
4. **Publish.** On every per-kind edge, dispatch
   ``SIGNAL_SUBSTRATE_KIND_CHANGED(room_name, kind, new_state)``. Suppressed
   during the boot-settle window (``PresenceCoordinator._boot_settle_done``);
   ``_raw_state`` is still updated. At settle, the substrate emits ONE
   synthetic dispatch per ``(room, kind)`` slot whose seeded state is True
   (False slots default-False in consumers — emitting them would be a
   per-room storm).
5. **Seed on startup.** Mirrors the v4.7.18.1 B-HIGH-1 pattern: read current
   ``hass.states.get(entity_id)`` for every discovered entity and seed
   ``_raw_state`` so the first post-settle tick agrees with reality.
6. **Re-discovery.** Tear down stale listeners on every re-discovery call;
   prune ``_raw_state`` entries for entities removed from CONF lists; add
   listeners for newly-added entities.
7. **Owned by PresenceCoordinator.** Created in ``PresenceCoordinator.async_setup``
   and torn down via the coordinator's existing unsub list (see
   ``__init__.py`` instantiation site and ``async_teardown`` cleanup).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional, Set, Tuple

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    TIER1_KINDS,
)
from .signals import SIGNAL_SUBSTRATE_KIND_CHANGED

_LOGGER = logging.getLogger(__name__)

# States that mean an entity is NOT providing real data. Mirrors the
# ``_UNAVAILABLE_STATES`` set in ``presence.py`` so the substrate's
# unavailable/unknown semantics match the pre-substrate listener path
# byte-for-byte.
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})

# Declared precedence order — when the SAME entity_id is (defensively)
# listed in multiple CONF lists for the SAME room, the first match in this
# tuple wins. Plan D1 spec: motion → mmwave → occupancy.
_KIND_PRECEDENCE: tuple = ("motion", "mmwave", "occupancy")

# Map each precedence-ordered kind to its backing CONF list key.
_KIND_TO_CONF: Dict[str, str] = {
    "motion": CONF_MOTION_SENSORS,
    "mmwave": CONF_MMWAVE_SENSORS,
    "occupancy": CONF_OCCUPANCY_SENSORS,
}


class OccupancySubstrate:
    """Unified per-room, per-kind raw-signal substrate.

    Public API (matches planning doc D1):

    * ``is_kind_active(room_name, kind) -> bool``
    * ``get_room_kinds(room_name) -> Dict[str, bool]`` — stable dict with
      every TIER1_KINDS slot present (missing kinds default False).
    * ``get_all_room_kinds() -> Dict[str, Dict[str, bool]]``
    * ``subscribe(callback) -> Callable[[], None]`` — returns unsub.

    Lifecycle:

    * ``async_setup()`` — read CONF lists, build the (entity, room, kind)
      triples, seed ``_raw_state`` from ``hass.states``, register one
      state-change listener per entity. Safe to call multiple times: each
      call performs a clean re-discovery (Bug Class #38 — stale listeners
      cleaned up).
    * ``async_teardown()`` — unsub every listener and clear local state.
    * ``release_boot_settle()`` — called by the owning ``PresenceCoordinator``
      when its ``_boot_settle_done`` flag transitions ``False -> True``.
      Emits one synthetic signal per (room, kind) slot whose seeded state
      is True so consumers re-sync. False slots emit nothing (consumers
      default to False).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        # Per-room, per-kind raw bool. Initialized lazily as rooms are
        # discovered; consumers read via ``get_room_kinds`` which back-
        # fills missing kinds with False.
        self._raw_state: Dict[str, Dict[str, bool]] = {}
        # entity_id -> (room_name, kind). Single canonical classification
        # per (entity, room) — populated at discovery, consulted in the
        # state-change callback.
        self._entity_to_room_kind: Dict[str, tuple] = {}
        # All listener unsubs from ``async_track_state_change_event``.
        # Bug Class #38: cleared and re-populated on every re-discovery.
        self._unsub_listeners: list = []
        # Local edge subscribers registered via ``subscribe()``. The
        # dispatcher signal is the primary channel; this is an in-process
        # fast path for the same-coordinator zone-tier listener that wants
        # to skip the dispatcher round-trip in unit tests / future
        # refactors. Independent of the dispatcher signal — both fire.
        self._local_subscribers: list = []
        # When False, dispatched signals are SUPPRESSED but ``_raw_state``
        # is still updated. Owning ``PresenceCoordinator`` flips this via
        # ``release_boot_settle()`` once its own boot-settle gate releases.
        self._boot_settle_done: bool = False
        # One-shot INFO log when the CONF lists are empty across all rooms
        # — surfaces the "no Tier-1 sensors configured" configuration gap
        # (planning doc D5).
        self._no_conf_lists_logged: bool = False
        # F3 fix-up (B-HIGH-1): teardown sentinel. Set at the top of
        # ``async_teardown``; ``refresh_subscriptions`` short-circuits on
        # it so a late-arriving lifecycle event cannot race with teardown
        # to re-install listeners after the substrate is gone.
        self._is_torn_down: bool = False
        # F4 fix-up (B-MED-1): serialize refresh_subscriptions calls. The
        # method body between lock-acquire and return MUST remain
        # await-free; the lock acquisition IS the only await point.
        self._refresh_lock = asyncio.Lock()
        # F6 fix-up (B-MED-3): one-shot retry flag if
        # async_track_state_change_event raises during refresh.
        self._refresh_retry_pending: bool = False
        # F3 fix-up: track the retry timer unsub so async_teardown can
        # cancel it (Bug Class #19).
        self._refresh_retry_unsub: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _discover_entity_map(
        self,
    ) -> Tuple[Dict[str, Dict[str, str]], Dict[str, tuple]]:
        """Return (room_entities, entity_to_room_kind) from live config entries.

        F1 fix-up (A-MED-2): single source of truth for the CONF-list walk
        shared by ``async_setup`` and ``refresh_subscriptions``. The prior
        "byte-parallel" split invited drift (e.g. duplicate-list WARNs that
        fired at cold-boot but not at live-add). Includes the multi-list
        precedence WARN and the cross-room duplicate WARN so both paths
        diagnose identically.

        Returns:
            room_entities: {room_name: {entity_id: kind}}
            entity_to_room_kind: {entity_id: (room_name, kind)}
        """
        room_entities: Dict[str, Dict[str, str]] = {}
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception:  # noqa: BLE001 — defensive: registry mid-reload
            _LOGGER.warning(
                "OccupancySubstrate: cannot enumerate config entries",
                exc_info=True,
            )
            entries = []

        for entry in entries:
            try:
                merged = {**(entry.data or {}), **(entry.options or {})}
            except Exception:  # noqa: BLE001 — defensive
                continue
            if merged.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            room_name = merged.get(CONF_ROOM_NAME)
            if not room_name:
                continue

            per_room = room_entities.setdefault(room_name, {})
            # Walk kinds in declared precedence; first match wins.
            for kind in _KIND_PRECEDENCE:
                conf_key = _KIND_TO_CONF[kind]
                entity_ids = list(merged.get(conf_key, []) or [])
                for entity_id in entity_ids:
                    if not entity_id:
                        continue
                    if entity_id in per_room:
                        prior_kind = per_room[entity_id]
                        if prior_kind != kind:
                            _LOGGER.warning(
                                "OccupancySubstrate: entity %s appears in "
                                "multiple CONF lists for room '%s' — kept "
                                "kind=%s (precedence), ignoring kind=%s",
                                entity_id, room_name, prior_kind, kind,
                            )
                        continue
                    per_room[entity_id] = kind

        # Build entity->(room,kind) map with cross-room duplicate WARN.
        entity_to_room_kind: Dict[str, tuple] = {}
        for room_name, entity_map in room_entities.items():
            for entity_id, kind in entity_map.items():
                prior = entity_to_room_kind.get(entity_id)
                if prior is not None and prior[0] != room_name:
                    _LOGGER.warning(
                        "OccupancySubstrate: entity %s claimed by multiple "
                        "rooms — kept first claim (room=%s kind=%s), "
                        "ignoring duplicate (room=%s kind=%s)",
                        entity_id, prior[0], prior[1], room_name, kind,
                    )
                    continue
                entity_to_room_kind[entity_id] = (room_name, kind)

        return room_entities, entity_to_room_kind

    def _reset_and_seed_room_bucket(
        self,
        room_name: str,
        entity_map: Dict[str, str],
        desired_entity_to_room_kind: Dict[str, tuple],
    ) -> Dict[str, bool]:
        """Reset every kind bucket for ``room_name`` to False, then re-seed
        from live state across each entity mapped to this room.

        Returns the pre-reset snapshot so callers can compute True→False
        edges for kinds whose value flipped as a result of the reset.

        F1 fix-up (A-HIGH-1 + C-MED-1): mirrors ``async_setup`` semantics
        on every refresh. Guarantees: shrinking a CONF list clears the
        stuck-True bucket; reclassifying an entity clears the OLD-kind
        stuck-True bucket.
        """
        bucket = self._raw_state.setdefault(room_name, {})
        # Snapshot BEFORE reset so callers can dispatch True→False edges.
        pre_reset = {k: bool(bucket.get(k, False)) for k in TIER1_KINDS}
        for k in TIER1_KINDS:
            bucket[k] = False
        # Re-seed from live state across this room's FULL sensor set.
        for entity_id, _entity_kind in entity_map.items():
            # Kind for THIS room comes from the desired canonical map
            # (post cross-room duplicate filtering); an entity claimed by
            # another room contributes nothing here.
            mapping = desired_entity_to_room_kind.get(entity_id)
            if mapping is None or mapping[0] != room_name:
                continue
            _r, canonical_kind = mapping
            try:
                state = self.hass.states.get(entity_id)
            except Exception:  # pragma: no cover — defensive
                state = None
            if state is None:
                continue
            if state.state in _UNAVAILABLE_STATES:
                continue
            if state.state == "on":
                bucket[canonical_kind] = True
        return pre_reset

    async def async_setup(self) -> None:
        """Discover CONF-listed Tier-1 entities and start tracking edges.

        Safe to invoke multiple times — each call performs a clean
        re-discovery (Bug Class #38). Stale entries pruned, new entries
        seeded + subscribed. Boot-settle dispatch suppression is preserved
        across re-discovery (the flag is only flipped by
        ``release_boot_settle``).
        """
        # Tear down any prior listeners first — re-discovery support.
        self._teardown_listeners()

        # F1 fix-up (A-MED-2): shared discovery walk.
        room_entities, desired_entity_to_room_kind = self._discover_entity_map()

        # Prune stale rooms from ``_raw_state`` whose configs disappeared
        # entirely (room entry removed) so we don't keep ghost state.
        for stale_room in list(self._raw_state.keys()):
            if stale_room not in room_entities:
                self._raw_state.pop(stale_room, None)

        self._entity_to_room_kind = desired_entity_to_room_kind

        # Reset every desired room's bucket to False, then re-seed from
        # live state across each room's FULL sensor set.
        all_entity_ids: Set[str] = set(desired_entity_to_room_kind.keys())
        for room_name, entity_map in room_entities.items():
            self._reset_and_seed_room_bucket(
                room_name, entity_map, desired_entity_to_room_kind,
            )

        # Register one listener per entity. Using a single
        # ``async_track_state_change_event`` call with the full list keeps
        # the listener count at exactly N (Bug Class #38: one unsub
        # tracked).
        if all_entity_ids:
            try:
                unsub = async_track_state_change_event(
                    self.hass,
                    list(all_entity_ids),
                    self._handle_state_change,
                )
                self._unsub_listeners.append(unsub)
                _LOGGER.info(
                    "OccupancySubstrate: subscribed to %d Tier-1 entities "
                    "across %d rooms (CONF-list-driven, no area-sweep)",
                    len(all_entity_ids), len(room_entities),
                )
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.warning(
                    "OccupancySubstrate: state-change subscription failed",
                    exc_info=True,
                )
        else:
            if not self._no_conf_lists_logged:
                self._no_conf_lists_logged = True
                _LOGGER.info(
                    "OccupancySubstrate: no Tier-1 occupancy sensors "
                    "configured across any room — relying on zone tier "
                    "camera/BLE composition for occupancy. Configure "
                    "CONF_MOTION_SENSORS / CONF_MMWAVE_SENSORS / "
                    "CONF_OCCUPANCY_SENSORS per room to enable Tier-1 "
                    "substrate discovery."
                )

    async def refresh_subscriptions(self) -> None:
        """Re-enumerate ROOM entries and atomically swap the listener set.

        Substrate re-subscribe cycle (post-v5.11.0): called by
        ``PresenceCoordinator`` on ``SIGNAL_ROOM_ENTRY_LIFECYCLE``.
        Restores the pre-v4.7.24 per-room-onboarding guarantee: a room
        added WITHOUT an HA restart is event-driven immediately.

        F1/F2 fix-up (A-HIGH-1 + A-MED-3 + C-HIGH-4 + C-MED-1): the body
        MIRRORS async_setup's reset-then-seed-then-swap semantics on every
        call. Steps:

        1. Snapshot the CURRENT raw state (pre-refresh).
        2. Discover desired triples via the shared helper.
        3. Diff added/removed/reclassified. Fast-path noop when clean.
        4. For every desired room: reset every kind bucket to False and
           re-seed from live state across the room's FULL sensor set.
           This kills: shrink-a-CONF-list stuck-True, reclassify old-kind
           stuck-True, add-sensor-to-existing-room stuck-False.
        5. Atomic swap: register the NEW async_track_state_change_event
           listener BEFORE releasing the prior unsub. Repoint the
           entity->room/kind map between register and release. Order
           protects in-flight events: a new-listener event during the
           overlap sees the seeded bucket and short-circuits on
           ``prior == occupied``.
        6. Prune rooms whose entries are gone.
        7. Post boot-settle, emit synthetic edges: True→False for every
           slot the reset+re-seed FLIPPED False, and False→True for every
           slot that moved to True (subsumes the old added-rooms-only
           step 7 — covers add-sensor-to-existing-room, which was the
           C-HIGH-4 blind spot).

        F4 fix-up (B-MED-1): serialize via ``self._refresh_lock``. The
        body inside the lock MUST remain await-free — that's the
        atomicity invariant. Any future await inside requires re-audit.
        The lock acquire is the only await point.

        F3 fix-up (B-HIGH-1): honors the ``_is_torn_down`` sentinel.

        Bug Class #50 guardrail: this method is the ONLY caller that
        mutates ``self._unsub_listeners`` outside ``async_setup`` /
        ``_teardown_listeners``.
        """
        # F3: teardown-race guard. The sentinel is set at the TOP of
        # async_teardown so a late-arriving lifecycle event cannot
        # re-install listeners on a torn-down substrate.
        if self._is_torn_down:
            _LOGGER.debug(
                "OccupancySubstrate.refresh_subscriptions: substrate is "
                "torn down — skipping"
            )
            return

        # F4: serialize concurrent refresh calls. The lock acquire is the
        # ONLY await point in this method; the body below MUST stay
        # await-free to preserve the atomic-swap invariant.
        async with self._refresh_lock:
            # Re-check the teardown sentinel — a teardown may have
            # completed while we were waiting on the lock.
            if self._is_torn_down:
                return

            # ---- Step 1: snapshot pre-refresh raw state ----
            snapshot: Dict[str, Dict[str, bool]] = {
                room: {k: bool(bucket.get(k, False)) for k in TIER1_KINDS}
                for room, bucket in self._raw_state.items()
            }

            # ---- Step 2: discover via shared helper ----
            room_entities, desired_entity_to_room_kind = (
                self._discover_entity_map()
            )
            desired_rooms: Set[str] = set(room_entities.keys())

            # ---- Step 3: diff ----
            current_keys = set(self._entity_to_room_kind.keys())
            desired_keys = set(desired_entity_to_room_kind.keys())
            added = desired_keys - current_keys
            removed = current_keys - desired_keys
            reclassified = {
                e for e in (current_keys & desired_keys)
                if self._entity_to_room_kind[e]
                != desired_entity_to_room_kind[e]
            }

            if not added and not removed and not reclassified:
                _LOGGER.debug(
                    "OccupancySubstrate.refresh_subscriptions: no diff — "
                    "noop (tracked=%d entities, %d rooms)",
                    len(current_keys), len(desired_rooms),
                )
                return

            _LOGGER.info(
                "OccupancySubstrate.refresh_subscriptions: diff added=%d "
                "removed=%d reclassified=%d",
                len(added), len(removed), len(reclassified),
            )

            # ---- Step 4: reset+seed BEFORE the atomic swap ----
            # Seeding BEFORE the swap means an in-flight added-entity
            # event that hits the NEW listener AFTER swap will see
            # `prior == occupied` and short-circuit — no double dispatch.
            for room_name, entity_map in room_entities.items():
                self._reset_and_seed_room_bucket(
                    room_name, entity_map, desired_entity_to_room_kind,
                )

            # ---- Step 5: atomic swap ----
            prior_unsubs = list(self._unsub_listeners)
            new_unsub = None
            if desired_keys:
                try:
                    new_unsub = async_track_state_change_event(
                        self.hass,
                        list(desired_keys),
                        self._handle_state_change,
                    )
                except Exception:  # noqa: BLE001 — defensive
                    _LOGGER.warning(
                        "OccupancySubstrate.refresh_subscriptions: new "
                        "state-change subscription failed — keeping old "
                        "listener in place; will retry once in 30s",
                        exc_info=True,
                    )
                    # F6 (B-MED-3): schedule a single guarded retry.
                    self._schedule_refresh_retry()
                    return

            # Repoint the entity->room/kind map after the new listener is
            # up and before old are released.
            self._entity_to_room_kind = desired_entity_to_room_kind

            self._unsub_listeners = []
            if new_unsub is not None:
                self._unsub_listeners.append(new_unsub)
            for unsub in prior_unsubs:
                try:
                    unsub()
                except Exception:  # noqa: BLE001 — defensive
                    _LOGGER.debug(
                        "OccupancySubstrate.refresh_subscriptions: prior "
                        "unsub raised (non-fatal)",
                        exc_info=True,
                    )

            # ---- Step 6: prune rooms whose entries are gone ----
            for stale_room in list(self._raw_state.keys()):
                if stale_room not in desired_rooms:
                    self._raw_state.pop(stale_room, None)

            # ---- Step 7: emit synthetic edges post-settle ----
            # F2 fix-up (C-HIGH-4): compute deltas between snapshot and
            # the reset+re-seeded state for EVERY (room, kind) — this
            # subsumes the old added-rooms-only path AND covers
            # add-sensor-to-existing-room.
            if self._boot_settle_done:
                emitted_true = 0
                emitted_false = 0
                for room_name in desired_rooms:
                    bucket = self._raw_state.get(room_name, {})
                    prior_bucket = snapshot.get(room_name, {})
                    for kind in TIER1_KINDS:
                        cur = bool(bucket.get(kind, False))
                        prev = bool(prior_bucket.get(kind, False))
                        if cur == prev:
                            continue
                        self._dispatch(room_name, kind, cur)
                        if cur:
                            emitted_true += 1
                        else:
                            emitted_false += 1
                if emitted_true or emitted_false:
                    _LOGGER.info(
                        "OccupancySubstrate.refresh_subscriptions: emitted "
                        "%d True-edge and %d False-edge synthetic "
                        "dispatch(es)",
                        emitted_true, emitted_false,
                    )

    def _schedule_refresh_retry(self) -> None:
        """F6 fix-up (B-MED-3): schedule ONE guarded refresh retry.

        Uses a one-shot ``_refresh_retry_pending`` flag so a re-arm loop
        cannot form — if this retry itself fails, we log and stop (the
        next lifecycle event will re-trigger the normal path).
        """
        if self._refresh_retry_pending or self._is_torn_down:
            return
        self._refresh_retry_pending = True

        async def _retry(_now: Any) -> None:
            self._refresh_retry_pending = False
            self._refresh_retry_unsub = None
            if self._is_torn_down:
                return
            try:
                await self.refresh_subscriptions()
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "OccupancySubstrate: retry refresh_subscriptions raised",
                    exc_info=True,
                )

        try:
            self._refresh_retry_unsub = async_call_later(
                self.hass, 30, _retry,
            )
        except Exception:  # noqa: BLE001 — defensive
            self._refresh_retry_pending = False
            _LOGGER.debug(
                "OccupancySubstrate: could not schedule refresh retry",
                exc_info=True,
            )

    async def async_teardown(self) -> None:
        """Unsub every listener and clear local subscribers.

        F3 fix-up (B-HIGH-1): set ``_is_torn_down`` at the TOP so any
        in-flight ``refresh_subscriptions`` short-circuits. Also cancels
        the F6 retry timer.
        """
        self._is_torn_down = True
        # Cancel any pending refresh retry (Bug Class #19).
        if self._refresh_retry_unsub is not None:
            try:
                self._refresh_retry_unsub()
            except Exception:  # noqa: BLE001 — defensive
                pass
            self._refresh_retry_unsub = None
        self._refresh_retry_pending = False
        self._teardown_listeners()
        self._local_subscribers.clear()

    def _teardown_listeners(self) -> None:
        """Internal: tear down all state-change subscriptions (Bug Class #38)."""
        for unsub in self._unsub_listeners:
            try:
                unsub()
            except Exception:  # noqa: BLE001 — defensive teardown
                _LOGGER.debug(
                    "OccupancySubstrate: listener unsub raised during teardown",
                    exc_info=True,
                )
        self._unsub_listeners.clear()

    # ------------------------------------------------------------------
    # Boot-settle coordination (D6)
    # ------------------------------------------------------------------

    def release_boot_settle(self) -> None:
        """Flip ``_boot_settle_done`` to True and replay True-slot seeds.

        Called by the owning ``PresenceCoordinator`` when its own boot-
        settle gate releases. Emits exactly one synthetic dispatch per
        ``(room, kind)`` slot whose seeded state is True at this moment.
        False slots emit nothing — consumers default to False, and
        emitting "kind=False" on every slot would itself be a per-room
        boot-storm.
        """
        if self._boot_settle_done:
            return
        self._boot_settle_done = True
        emitted = 0
        for room_name, kinds in self._raw_state.items():
            for kind, value in kinds.items():
                if value:
                    self._dispatch(room_name, kind, True)
                    emitted += 1
        _LOGGER.info(
            "OccupancySubstrate: boot-settle released; emitted %d synthetic "
            "True-slot dispatch(es)",
            emitted,
        )

    # ------------------------------------------------------------------
    # State-change handling
    # ------------------------------------------------------------------

    @callback
    def _handle_state_change(self, event: Any) -> None:
        """State-change callback — updates ``_raw_state`` + dispatches edges.

        Guards: unavailable/unknown -> False (matches
        ``_handle_occupancy_change`` semantics). Dispatch is suppressed
        while ``_boot_settle_done`` is False (D6), but ``_raw_state`` is
        still updated so the first post-settle tick reads correctly.
        """
        try:
            entity_id = event.data.get("entity_id", "")
            new_state = event.data.get("new_state")
        except Exception:  # noqa: BLE001 — defensive
            return
        if not entity_id or new_state is None:
            return

        mapping = self._entity_to_room_kind.get(entity_id)
        if mapping is None:
            return  # Unsolicited event for an entity we no longer track.
        room_name, kind = mapping

        if new_state.state in _UNAVAILABLE_STATES:
            occupied = False
        else:
            occupied = new_state.state == "on"

        bucket = self._raw_state.setdefault(room_name, {})
        prior = bool(bucket.get(kind, False))
        bucket[kind] = occupied

        # Only dispatch on true edges to avoid spurious re-fires from
        # state-change events that don't move the per-kind bool (e.g.,
        # an unavailable->unavailable transition or an on->on attribute-
        # only update).
        if prior == occupied:
            return

        if not self._boot_settle_done:
            # D6: silently update ``_raw_state`` but suppress dispatch.
            # release_boot_settle() will fan out any True slots at settle.
            return

        self._dispatch(room_name, kind, occupied)

    def _dispatch(self, room_name: str, kind: str, new_state: bool) -> None:
        """Dispatch the per-kind edge to subscribers + the HA dispatcher.

        F8 fix-up (C-LOW-2): SINGLE-WRITER discipline — this is the only
        method that emits ``SIGNAL_SUBSTRATE_KIND_CHANGED`` and invokes
        local subscribers. ``_handle_state_change`` and
        ``refresh_subscriptions`` funnel through here so any future
        cross-cutting emit concern lands in one place.

        F8 fix-up (C-LOW-3): ``room_name`` is informational (used by the
        zone tier to route the edge back into the tracker); ``kind`` +
        ``new_state`` are the load-bearing payload.

        Bug Class #34: ``async_dispatcher_send`` is imported at module
        top (NOT function-local) — the v4.7.20.1 recurrence is one of
        the failure modes this substrate explicitly avoids.
        """
        # Local subscribers first — synchronous, no event-loop hop.
        for cb in list(self._local_subscribers):
            try:
                cb(room_name, kind, new_state)
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "OccupancySubstrate: local subscriber raised",
                    exc_info=True,
                )
        # HA dispatcher channel — this is the cross-coordinator path
        # the zone tier subscribes to.
        try:
            async_dispatcher_send(
                self.hass,
                SIGNAL_SUBSTRATE_KIND_CHANGED,
                room_name,
                kind,
                new_state,
            )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "OccupancySubstrate: async_dispatcher_send failed",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_kind_active(self, room_name: str, kind: str) -> bool:
        """Return the current raw bool for (room_name, kind), default False."""
        return bool(self._raw_state.get(room_name, {}).get(kind, False))

    def get_room_kinds(self, room_name: str) -> Dict[str, bool]:
        """Return a stable dict with every TIER1_KINDS slot present.

        Missing kinds default to False. Same shape as
        ``ZonePresenceTracker.provenance_for`` so consumers can swap in
        the substrate's view without reshaping.
        """
        stored = self._raw_state.get(room_name, {})
        return {k: bool(stored.get(k, False)) for k in TIER1_KINDS}

    def get_all_room_kinds(self) -> Dict[str, Dict[str, bool]]:
        """Return per-room per-kind view for every known room."""
        return {
            room: {k: bool(stored.get(k, False)) for k in TIER1_KINDS}
            for room, stored in self._raw_state.items()
        }

    def subscribe(
        self,
        cb: Callable[[str, str, bool], None],
    ) -> Callable[[], None]:
        """Subscribe a local callback to per-kind edges.

        Returns an unsub callable. The dispatcher signal
        ``SIGNAL_SUBSTRATE_KIND_CHANGED`` is the primary cross-coordinator
        channel; this in-process subscribe is an additional fast path for
        same-coordinator listeners and tests.
        """
        self._local_subscribers.append(cb)

        def _unsub() -> None:
            try:
                self._local_subscribers.remove(cb)
            except ValueError:
                pass

        return _unsub

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

import logging
from typing import Any, Callable, Dict, Optional, Set

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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

        # Build the per-room, per-kind set of curated entity_ids.
        # Shape: {room_name: {entity_id: kind}}. The inner dict tracks
        # the chosen kind for each entity in the room; precedence motion
        # → mmwave → occupancy if the same entity_id is listed in
        # multiple CONF lists for the same room (defensive case).
        room_entities: Dict[str, Dict[str, str]] = {}
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception:  # noqa: BLE001 — defensive: registry mid-reload
            _LOGGER.warning(
                "OccupancySubstrate: cannot enumerate config entries — "
                "discovery skipped",
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
            # Walk the kinds in declared precedence; the first match for
            # a given entity_id wins and a WARN is emitted if the same
            # entity_id was already classified under an earlier kind in
            # this same room (multi-list membership — should not happen
            # in normal configs).
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

        # Prune stale rooms from ``_raw_state`` whose configs disappeared
        # entirely (room entry removed) so we don't keep ghost state.
        for stale_room in list(self._raw_state.keys()):
            if stale_room not in room_entities:
                self._raw_state.pop(stale_room, None)

        # Reset entity classification map for the fresh discovery pass.
        self._entity_to_room_kind = {}

        # Collect all entity_ids and seed ``_raw_state`` from current
        # ``hass.states`` (v4.7.18.1 B-HIGH-1 seed pattern).
        all_entity_ids: Set[str] = set()
        total_listener_entities = 0
        for room_name, entity_map in room_entities.items():
            # Make sure every room has a stable per-kind bucket so that
            # ``get_room_kinds`` projection is consistent.
            bucket = self._raw_state.setdefault(room_name, {})
            # Re-key bucket to only include kinds we still care about.
            for k in TIER1_KINDS:
                bucket.setdefault(k, False)
            # Reset all to False before seeding so a CONF list shrink
            # doesn't leave stale True bits from a previously-tracked
            # entity that's now gone (planning D1 re-discovery clean).
            for k in TIER1_KINDS:
                bucket[k] = False
            for entity_id, kind in entity_map.items():
                # C-MEDIUM-2 fix-up: WARN on cross-room duplicate entity_id.
                # If the same entity_id was already claimed by another
                # room earlier in the iteration order, keep the first
                # claim (stable for the operator) and surface the
                # divergence loudly — the substrate cycle exists exactly
                # to surface configuration overlap, so silently losing
                # one room would defeat the point.
                prior = self._entity_to_room_kind.get(entity_id)
                if prior is not None and prior[0] != room_name:
                    _LOGGER.warning(
                        "OccupancySubstrate: entity %s claimed by multiple "
                        "rooms — kept first claim (room=%s kind=%s), "
                        "ignoring duplicate (room=%s kind=%s)",
                        entity_id, prior[0], prior[1], room_name, kind,
                    )
                    continue
                self._entity_to_room_kind[entity_id] = (room_name, kind)
                all_entity_ids.add(entity_id)
                total_listener_entities += 1
                # Seed from current state.
                try:
                    state = self.hass.states.get(entity_id)
                except Exception:  # pragma: no cover — defensive
                    state = None
                if state is None:
                    continue
                if state.state in _UNAVAILABLE_STATES:
                    continue
                is_on = state.state == "on"
                if is_on:
                    bucket[kind] = True

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
        ``PresenceCoordinator`` on ``SIGNAL_ROOM_ENTRY_LIFECYCLE``
        (dispatched from ROOM ``async_setup_entry`` / ``async_unload_entry``
        / suppressed ``_async_update_listener`` writes at ``__init__.py``
        room-lifecycle sites). Restores the pre-v4.7.24 (commit
        ``e165e1cb``) per-room-onboarding guarantee: a room added WITHOUT
        an HA restart is event-driven immediately.

        Design:
        1. Re-build the desired ``(entity_id, room_name, kind)`` triples
           from currently-LOADED ROOM entries (SAME discovery walk as
           ``async_setup`` — kept intentionally byte-parallel so future
           edits to one path force review of the other).
        2. Diff against ``self._entity_to_room_kind`` — compute
           ``added`` / ``removed`` sets.
        3. Fast-path: if the desired set equals the tracked set AND no
           kind reclassification, this is a no-op (options_updated writes
           that don't move sensor lists hit this path).
        4. Atomic swap: register the NEW ``async_track_state_change_event``
           listener over the FULL new entity list BEFORE releasing the
           prior unsub. Per-kind edge idempotence in
           ``_handle_state_change`` (``prior == occupied`` short-circuit
           at the "true edge only" gate) neutralizes duplicate delivery
           during the overlap window; ``mapping is None`` at
           ``_handle_state_change`` covers removed entities whose events
           land after the map has been repointed but before the old
           unsub fires.
        5. Seed newly-added entities from ``hass.states.get()`` (mirrors
           the v4.7.18.1 B-HIGH-1 seed pattern in ``async_setup``).
        6. Prune ``_raw_state`` rooms whose entries are gone.
        7. If ``_boot_settle_done`` is True (typical live-add case),
           dispatch synthetic True-slot edges for the newly-added room's
           kinds so consumers that missed the boot-settle release don't
           stay silent until the next real edge — mirrors
           ``release_boot_settle`` semantics for the late-add case.

        Bug Class #50 guardrail: this method is the ONLY caller that
        mutates ``self._unsub_listeners`` outside ``async_setup`` /
        ``_teardown_listeners``. It preserves the invariant that no
        external periodic rebuild path can clobber the substrate's own
        subscription list — verified 2026-07-10 grep of `_unsub_listeners`
        in presence.py: appended selectively, never wholesale-cleared
        outside async_teardown.
        """
        # ---- Step 1: rebuild desired triples (mirror async_setup) ----
        room_entities: Dict[str, Dict[str, str]] = {}
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception:  # noqa: BLE001 — defensive: registry mid-reload
            _LOGGER.warning(
                "OccupancySubstrate.refresh_subscriptions: cannot enumerate "
                "config entries — skipping",
                exc_info=True,
            )
            return

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
            for kind in _KIND_PRECEDENCE:
                conf_key = _KIND_TO_CONF[kind]
                entity_ids = list(merged.get(conf_key, []) or [])
                for entity_id in entity_ids:
                    if not entity_id:
                        continue
                    if entity_id in per_room:
                        continue  # precedence already claimed
                    per_room[entity_id] = kind

        # Build the desired (entity -> (room, kind)) map with the same
        # cross-room duplicate handling as async_setup (first claim wins,
        # WARN on duplicate).
        desired_entity_to_room_kind: Dict[str, tuple] = {}
        desired_rooms: Set[str] = set()
        for room_name, entity_map in room_entities.items():
            desired_rooms.add(room_name)
            for entity_id, kind in entity_map.items():
                prior = desired_entity_to_room_kind.get(entity_id)
                if prior is not None and prior[0] != room_name:
                    _LOGGER.warning(
                        "OccupancySubstrate.refresh_subscriptions: entity "
                        "%s claimed by multiple rooms — kept first claim "
                        "(room=%s kind=%s), ignoring (room=%s kind=%s)",
                        entity_id, prior[0], prior[1], room_name, kind,
                    )
                    continue
                desired_entity_to_room_kind[entity_id] = (room_name, kind)

        # ---- Step 2: diff ----
        current_keys = set(self._entity_to_room_kind.keys())
        desired_keys = set(desired_entity_to_room_kind.keys())
        added = desired_keys - current_keys
        removed = current_keys - desired_keys
        reclassified = {
            e for e in (current_keys & desired_keys)
            if self._entity_to_room_kind[e] != desired_entity_to_room_kind[e]
        }
        added_rooms = desired_rooms - set(self._raw_state.keys())

        # ---- Step 3: fast-path no-op ----
        if not added and not removed and not reclassified:
            _LOGGER.debug(
                "OccupancySubstrate.refresh_subscriptions: no diff — noop "
                "(tracked=%d entities, %d rooms)",
                len(current_keys), len(desired_rooms),
            )
            return

        _LOGGER.info(
            "OccupancySubstrate.refresh_subscriptions: diff added=%d "
            "removed=%d reclassified=%d added_rooms=%d",
            len(added), len(removed), len(reclassified), len(added_rooms),
        )

        # ---- Step 4: atomic swap — register NEW listener BEFORE unsub of old ----
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
                    "listener in place",
                    exc_info=True,
                )
                return

        # Repoint the entity->room/kind map BEFORE releasing the old
        # listener. During the overlap window, both listeners are
        # registered; the per-kind edge idempotence guard in
        # `_handle_state_change` (`prior == occupied` short-circuit)
        # prevents any double-dispatch. For removed entities that receive
        # an in-flight event, `mapping is None` covers them at
        # `_handle_state_change` (they're gone from the map now).
        self._entity_to_room_kind = desired_entity_to_room_kind

        # Register new unsub in the list, then release prior ones. Order
        # matters: the list carries the NEW unsub before old are released
        # so any concurrent teardown (e.g. async_teardown() racing an
        # in-flight refresh) still tears down the new one.
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

        # ---- Step 5: seed newly-added entities from hass.states ----
        # Ensure each desired room has a stable per-kind bucket and seed
        # newly-added entities' True/False from current state.
        for room_name in desired_rooms:
            bucket = self._raw_state.setdefault(room_name, {})
            for k in TIER1_KINDS:
                bucket.setdefault(k, False)

        # For added entities, seed True kinds. For reclassified entities,
        # clear the OLD kind slot's contribution isn't tractable at this
        # granularity (multiple entities can share a kind slot per room),
        # so we conservatively re-seed the NEW kind from current state.
        for entity_id in added | reclassified:
            room_name, kind = desired_entity_to_room_kind[entity_id]
            try:
                state = self.hass.states.get(entity_id)
            except Exception:  # pragma: no cover — defensive
                state = None
            if state is None:
                continue
            if state.state in _UNAVAILABLE_STATES:
                continue
            if state.state == "on":
                self._raw_state[room_name][kind] = True

        # ---- Step 6: prune rooms whose entries are gone ----
        for stale_room in list(self._raw_state.keys()):
            if stale_room not in desired_rooms:
                self._raw_state.pop(stale_room, None)

        # ---- Step 7: synthetic True-slot dispatch for newly-added rooms ----
        # If boot-settle already released (typical live-add case), fan out
        # synthetic edges for the newly-added rooms' True slots so
        # consumers don't stay silent until the next real edge. Mirrors
        # `release_boot_settle` semantics for the LATE-add case.
        if self._boot_settle_done and added_rooms:
            emitted = 0
            for room_name in added_rooms:
                for kind, value in self._raw_state.get(room_name, {}).items():
                    if value:
                        self._dispatch(room_name, kind, True)
                        emitted += 1
            if emitted:
                _LOGGER.info(
                    "OccupancySubstrate.refresh_subscriptions: emitted %d "
                    "synthetic True-slot dispatch(es) for %d added room(s)",
                    emitted, len(added_rooms),
                )

    async def async_teardown(self) -> None:
        """Unsub every listener and clear local subscribers."""
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

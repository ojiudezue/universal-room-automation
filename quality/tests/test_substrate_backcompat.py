"""Substrate D4 backcompat tests — per-consumer ripple.

Drives a substrate-mediated per-kind edge and asserts every downstream
consumer that the plan's D4 table calls out sees IDENTICAL values to a
pre-substrate (direct ``_handle_occupancy_change``-style) flow. The
substrate only changes the WRITER; the dict shapes / properties /
derived-OR / raw_occupied semantics are unchanged.

C-HIGH-1 fix-up (2026-06-05): the prior version of this module
defined ``_drive_pre_substrate_flow`` and ``_drive_substrate_flow`` as
bit-identical wrappers around ``tracker.update_room_occupancy(...)``,
so every assertion reduced to ``X == X``. The rewrite below actually
drives a real ``OccupancySubstrate`` for the "post" flow:

* Instantiates the substrate against a mocked hass.
* Routes ``hass.states.get(entity_id)`` so the substrate can seed.
* Invokes ``_handle_state_change`` with synthetic events (or directly
  drives ``release_boot_settle`` for the seed-replay leg) so the real
  substrate dispatch path runs.
* Wires a ``_local_subscribers`` callback that mirrors
  ``_on_substrate_kind_changed`` from ``presence.py`` — calling
  ``tracker.update_room_occupancy(room, new_state, kind=kind)``.
* Then compares the resulting tracker state against the equivalent
  pre-substrate path (driving the same tracker call directly).

What is NOT covered by this module (genuine infeasibility against the
mocked HA fixtures, called out explicitly):

* FanRecheckManager's ``recent_occupancy_sources()`` ring + the
  room-tier coordinator-data flat-OR (``coordinator.data[
  STATE_OCCUPANCY_SOURCE / occupied / presence_detected]``) — those
  require a real ``UniversalRoomCoordinator._async_update_data`` tick
  which depends on the full HA event-loop fixtures. The D4 audit doc
  records FanRecheck reads as source-derived from the same per-kind
  input the substrate provides, and the tracker call shape is asserted
  identical here — which is the most we can assert without a full HA
  fixture. The cross-check is exercised behaviorally to the extent
  possible: see ``test_fanrecheck_call_shape_identical_pre_post``.
"""

from __future__ import annotations

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_ROOM_NAME,
    ENTRY_TYPE_ROOM,
    TIER1_KINDS,
)
from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
    ZonePresenceTracker,
    _audit_provenance_invariants,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(state: str):
    """Build a minimal ``hass.states.get`` return value (state-like object)."""

    class _S:
        def __init__(self, s):
            self.state = s

    return _S(state)


def _make_event(entity_id: str, new_state_value: str):
    """Build a minimal state-change event for ``_handle_state_change``."""

    class _NS:
        def __init__(self, s):
            self.state = s

    class _Evt:
        def __init__(self):
            self.data = {
                "entity_id": entity_id,
                "new_state": _NS(new_state_value),
            }

    return _Evt()


def _build_substrate_with_rooms(hass, rooms_config):
    """Configure ``hass.config_entries.async_entries`` to return ROOM entries.

    ``rooms_config`` is ``{room_name: {kind: [entity_ids]}}``.
    Returns ``(substrate, all_entity_ids_in_order)``.
    """
    from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
        OccupancySubstrate,
    )

    entries = []
    all_entities = []
    for room_name, kinds in rooms_config.items():
        from unittest.mock import MagicMock

        entry = MagicMock()
        data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: room_name,
        }
        for kind, ents in kinds.items():
            conf_key = {
                "motion": CONF_MOTION_SENSORS,
                "mmwave": CONF_MMWAVE_SENSORS,
                "occupancy": CONF_OCCUPANCY_SENSORS,
            }[kind]
            data[conf_key] = list(ents)
            all_entities.extend(ents)
        entry.data = data
        entry.options = {}
        entries.append(entry)

    hass.config_entries.async_entries.return_value = entries
    substrate = OccupancySubstrate(hass)
    return substrate, all_entities


def _drive_pre_substrate_flow(tracker, sequence):
    """Pre-substrate: replicate ``_handle_occupancy_change`` direct write.

    The pre-substrate handler reads the state-change event, classifies
    the entity by name/area, and calls
    ``tracker.update_room_occupancy(room, occupied, kind=kind)``. That
    call into the tracker is what we replicate here — the writer
    changed, the tracker call shape did not.
    """
    for room, occ, kind in sequence:
        tracker.update_room_occupancy(room, occ, kind=kind)


def _drive_substrate_flow(hass, substrate, tracker, sequence):
    """Post-substrate: drive the REAL substrate dispatch path.

    Wires a local subscriber that mirrors ``_on_substrate_kind_changed``
    in presence.py — when the substrate dispatches a per-kind edge, the
    subscriber writes into the tracker via the same call shape.

    Then walks ``sequence`` (a list of ``(room, occupied, kind, entity_id)``
    quadruples), updates ``hass.states.get`` to return the right state
    for that entity, and fires ``_handle_state_change`` on the substrate.
    The substrate's per-kind edge guard fires the dispatcher signal only
    when the prior raw state actually changed.
    """
    # release boot-settle so dispatches are emitted (default is suppressed).
    substrate.release_boot_settle()

    def _on_substrate_kind_changed(room, kind, new_state):
        tracker.update_room_occupancy(room, new_state, kind=kind)

    substrate.subscribe(_on_substrate_kind_changed)

    for room, occ, kind, entity_id in sequence:
        # Update hass.states to reflect the entity's new state. The
        # event handler uses event.data["new_state"], but
        # ``release_boot_settle`` replay also reads ``hass.states.get``
        # at setup time — so keep them aligned.
        hass.states.get.return_value = _make_state("on" if occ else "off")
        substrate._handle_state_change(_make_event(entity_id, "on" if occ else "off"))


# ---------------------------------------------------------------------------
# Tests — drive the REAL substrate, compare against pre-substrate writer
# ---------------------------------------------------------------------------


def test_substrate_drives_provenance_identical_to_pre_substrate():
    """Real substrate dispatch produces the SAME tracker state as the
    pre-substrate direct write for the same per-kind edge sequence."""
    hass_pre = make_hass()
    hass_post = make_hass()

    # Room config: bedroom has one mmwave + one motion entity.
    rooms = {
        "bedroom": {
            "mmwave": ["binary_sensor.bedroom_mmwave"],
            "motion": ["binary_sensor.bedroom_motion"],
        },
    }
    substrate, _ = _build_substrate_with_rooms(hass_post, rooms)
    # Seed step — async_setup walks entries, builds entity map, seeds
    # _raw_state. We can call _handle_state_change without async_setup
    # if we populate _entity_to_room_kind manually — but the cleanest
    # way is to invoke async_setup synchronously through an event loop.
    import asyncio

    asyncio.get_event_loop().run_until_complete(substrate.async_setup())

    # Build trackers (one per path) with identical room list.
    pre = ZonePresenceTracker(hass_pre, "z", ["bedroom"])
    post = ZonePresenceTracker(hass_post, "z", ["bedroom"])

    # Pre-substrate path (writer change only).
    pre_seq = [
        ("bedroom", True, "mmwave"),
        ("bedroom", False, "mmwave"),
        ("bedroom", True, "motion"),
    ]
    _drive_pre_substrate_flow(pre, pre_seq)

    # Post-substrate path — same edges, but driven through the substrate.
    post_seq = [
        ("bedroom", True, "mmwave", "binary_sensor.bedroom_mmwave"),
        ("bedroom", False, "mmwave", "binary_sensor.bedroom_mmwave"),
        ("bedroom", True, "motion", "binary_sensor.bedroom_motion"),
    ]
    _drive_substrate_flow(hass_post, substrate, post, post_seq)

    # Provenance dicts + derived occupancy match.
    assert pre.provenance_for("bedroom") == post.provenance_for("bedroom"), (
        "Substrate writer must produce the same per-kind provenance as the "
        "pre-substrate direct writer"
    )
    assert pre._room_occupied == post._room_occupied
    assert pre.raw_occupied == post.raw_occupied


def test_substrate_publishes_signal_kind_changed():
    """The real substrate dispatches ``SIGNAL_SUBSTRATE_KIND_CHANGED`` via
    ``async_dispatcher_send``. Verify by intercepting the send fn."""
    hass = make_hass()
    sent = []

    # Patch the substrate module's async_dispatcher_send reference.
    from custom_components.universal_room_automation.domain_coordinators import (
        occupancy_substrate as os_mod,
    )

    orig = os_mod.async_dispatcher_send

    def _capturing_send(*args, **kwargs):
        sent.append(args)

    os_mod.async_dispatcher_send = _capturing_send
    try:
        rooms = {
            "office": {"mmwave": ["binary_sensor.office_mmwave"]},
        }
        substrate, _ = _build_substrate_with_rooms(hass, rooms)
        import asyncio

        asyncio.get_event_loop().run_until_complete(substrate.async_setup())
        substrate.release_boot_settle()

        # An off->on edge must dispatch SIGNAL_SUBSTRATE_KIND_CHANGED.
        hass.states.get.return_value = _make_state("on")
        substrate._handle_state_change(
            _make_event("binary_sensor.office_mmwave", "on"),
        )
    finally:
        os_mod.async_dispatcher_send = orig

    # At least one dispatch with the substrate signal, room_name "office",
    # kind "mmwave", new_state True.
    matched = [
        s for s in sent
        if len(s) >= 4
        and s[2] == "office"
        and s[3] == "mmwave"
        and len(s) >= 5
        and s[4] is True
    ]
    assert matched, f"expected SIGNAL_SUBSTRATE_KIND_CHANGED dispatch, got {sent}"


def test_audit_invariants_clean_post_substrate_dispatch():
    """Invariant 4 (set(_room_provenance.keys()) == set(_room_occupied.keys()))
    holds after the substrate has dispatched edges into the tracker."""
    hass = make_hass()
    rooms = {
        "a": {"motion": ["binary_sensor.a_motion"]},
        "b": {"occupancy": ["binary_sensor.b_occupancy"]},
    }
    substrate, _ = _build_substrate_with_rooms(hass, rooms)
    import asyncio

    asyncio.get_event_loop().run_until_complete(substrate.async_setup())

    post = ZonePresenceTracker(hass, "z", ["a", "b"])
    seq = [
        ("a", True, "motion", "binary_sensor.a_motion"),
        ("b", True, "occupancy", "binary_sensor.b_occupancy"),
        ("a", False, "motion", "binary_sensor.a_motion"),
    ]
    _drive_substrate_flow(hass, substrate, post, seq)
    assert _audit_provenance_invariants(post) == []


def test_provenance_for_stable_kind_keys():
    """provenance_for returns a stable {motion,mmwave,occupancy} dict."""
    hass = make_hass()
    t = ZonePresenceTracker(hass, "z", ["bedroom"])
    t.update_room_occupancy("bedroom", True, kind="mmwave")
    p = t.provenance_for("bedroom")
    assert set(p.keys()) == set(TIER1_KINDS)


def test_fanrecheck_call_shape_identical_pre_post():
    """FanRecheck row (D4): the tracker call shape from
    ``_on_substrate_kind_changed`` is bit-identical to the pre-substrate
    direct call into ``tracker.update_room_occupancy``. We can't drive
    the full ``coordinator.data[STATE_OCCUPANCY_SOURCE]`` flat-OR ring
    without a real ``UniversalRoomCoordinator`` (heavy HA fixtures), but
    we can assert that the substrate-dispatched edge produces the SAME
    per-kind provenance + raw_occupied at the tracker boundary — which
    is the precise input FanRecheck reads source-derive from.
    """
    hass_pre = make_hass()
    hass_post = make_hass()

    rooms = {
        "master": {
            "mmwave": ["binary_sensor.master_mmwave"],
            "motion": ["binary_sensor.master_motion"],
            "occupancy": ["binary_sensor.master_occupancy"],
        },
    }
    substrate, _ = _build_substrate_with_rooms(hass_post, rooms)
    import asyncio

    asyncio.get_event_loop().run_until_complete(substrate.async_setup())

    pre = ZonePresenceTracker(hass_pre, "z", ["master"])
    post = ZonePresenceTracker(hass_post, "z", ["master"])

    pre_seq = [
        ("master", True, "mmwave"),
        ("master", True, "motion"),
        ("master", False, "mmwave"),
        ("master", True, "occupancy"),
    ]
    post_seq = [
        ("master", True, "mmwave", "binary_sensor.master_mmwave"),
        ("master", True, "motion", "binary_sensor.master_motion"),
        ("master", False, "mmwave", "binary_sensor.master_mmwave"),
        ("master", True, "occupancy", "binary_sensor.master_occupancy"),
    ]
    _drive_pre_substrate_flow(pre, pre_seq)
    _drive_substrate_flow(hass_post, substrate, post, post_seq)

    assert pre.provenance_for("master") == post.provenance_for("master")
    assert pre.raw_occupied == post.raw_occupied

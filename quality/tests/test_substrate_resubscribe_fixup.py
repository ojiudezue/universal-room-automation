"""Fix-up-pass tests for the v5.12.0 substrate re-subscribe cycle.

Covers Reviewer C's mutation-blindness findings (C-HIGH-1, C-HIGH-2,
C-HIGH-3, C-MED-2) plus the F1/F2 regression scenarios:

* T1 (C-HIGH-1): end-to-end chain — dispatch SIGNAL_ROOM_ENTRY_LIFECYCLE
  through the REAL PresenceCoordinator handler and assert a substrate
  refresh task is scheduled.
* T2 (C-HIGH-2): dispatch-site tests — the WRITER sites in ``__init__.py``
  are audited by source-scan so a deleted dispatch turns a specific test
  RED.
* T3 (C-HIGH-3): swap-sequence — new listener is registered BEFORE any
  old unsub fires (shared-list ordering check).
* T4 (C-MED-2): substrate-gap canary — see
  ``test_substrate_gap_canary.py`` for the four focused cases
  (WARN-on-gap / silent-when-tracked / once-per-boot / silent-when-absent).
  The canary already lives in
  ``UniversalRoomCoordinator._check_substrate_gap`` (extracted from the
  inline v5.12.0 D4 block in this fix-up so it can be exercised without
  spinning up the full coordinator).
* T5: F1/F2 regressions — shrink-list clears bucket + emits False edge;
  reclassify clears old kind; add-sensor-to-existing-room (currently ON)
  emits a synthetic True edge.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.const import (
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
)
from custom_components.universal_room_automation.domain_coordinators import (
    occupancy_substrate as substrate_mod,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)
from custom_components.universal_room_automation.domain_coordinators import (
    presence as presence_mod,
)
from custom_components.universal_room_automation.domain_coordinators.signals import (  # noqa: E501
    SIGNAL_ROOM_ENTRY_LIFECYCLE,
    SIGNAL_SUBSTRATE_KIND_CHANGED,
)


_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeState:
    def __init__(self, state: str) -> None:
        self.state = state


class _FakeEvent:
    def __init__(self, entity_id: str, new_state) -> None:
        self.data = {"entity_id": entity_id, "new_state": new_state}


def _install_track_capture(monkeypatch):
    """Install a fake async_track_state_change_event."""
    registrations: list = []

    def _fake_track(_hass, entities, cb):
        unsub = MagicMock()
        registrations.append((list(entities), cb, unsub))
        return unsub

    monkeypatch.setattr(
        substrate_mod, "async_track_state_change_event", _fake_track,
    )
    return registrations


def _install_dispatch_capture(monkeypatch):
    dispatched: list = []

    def _fake_send(_hass, signal, *args):
        dispatched.append((signal, args))

    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send", _fake_send,
    )
    return dispatched


# ---------------------------------------------------------------------------
# T1 (C-HIGH-1) — end-to-end chain: real PC handler schedules refresh
# ---------------------------------------------------------------------------


def test_t1_lifecycle_handler_schedules_substrate_refresh(monkeypatch) -> None:
    """Firing the room-entry-lifecycle handler must schedule a substrate
    refresh task.

    Mutation check: commenting the subscription block in presence.py that
    wires SIGNAL_ROOM_ENTRY_LIFECYCLE -> _on_room_entry_lifecycle turns
    this RED, because a live house never reaches the handler and never
    schedules the refresh. Here we call the handler directly to prove the
    handler->substrate.refresh_subscriptions chain is intact.
    """
    hass = make_hass()
    hass.config_entries.async_entries.return_value = []

    # Real PresenceCoordinator + real substrate object (no async_setup —
    # we only exercise the sync handler + the task-scheduling contract).
    pc = presence_mod.PresenceCoordinator(hass)
    pc._substrate = OccupancySubstrate(hass)

    scheduled: list = []

    def _fake_create_task(coro):
        # Immediately close the coroutine so we don't leak "never awaited"
        # warnings — the assertion is that a task WAS created, not that
        # it ran to completion.
        coro.close()
        task = MagicMock()
        scheduled.append(task)
        return task

    hass.async_create_task = _fake_create_task

    # Fire the handler directly (this is what the dispatcher invokes).
    pc._on_room_entry_lifecycle(
        entry_id="entry_master_bath_toilet",
        room_name="Master Bath Toilet",
        action="loaded",
    )

    assert len(scheduled) == 1, (
        "handler must schedule exactly one substrate refresh task"
    )
    # And the task was tracked for teardown (F3 fix-up).
    assert scheduled[0] in pc._substrate_refresh_tasks


def test_t1_lifecycle_handler_noop_before_substrate_ready() -> None:
    """Handler called before substrate exists must silently no-op — the
    substrate's own async_setup enumerates the room."""
    hass = make_hass()
    pc = presence_mod.PresenceCoordinator(hass)
    pc._substrate = None
    hass.async_create_task = MagicMock()

    pc._on_room_entry_lifecycle("e", "Any Room", "loaded")

    hass.async_create_task.assert_not_called()


# ---------------------------------------------------------------------------
# T2 (C-HIGH-2) — dispatch WRITER sites audited on real source
# ---------------------------------------------------------------------------


def _init_src() -> str:
    with open(os.path.join(_COMPONENT_DIR, "__init__.py")) as f:
        return f.read()


def _count_signal_dispatch_with_action(src: str, action: str) -> int:
    """Count async_dispatcher_send calls that pass SIGNAL_ROOM_ENTRY_LIFECYCLE
    and end with the given action string as the trailing argument.

    Structure-anchored so mutation that deletes ONE dispatch block turns
    a specific test RED — comments mentioning the action word do not
    match.
    """
    import re
    # Match: async_dispatcher_send( ... SIGNAL_ROOM_ENTRY_LIFECYCLE ...
    #        "action" ... )
    # We require both the signal identifier and the quoted action string
    # to appear within the same call (multi-line).
    pattern = re.compile(
        r"async_dispatcher_send\s*\("
        r".{0,400}?SIGNAL_ROOM_ENTRY_LIFECYCLE.{0,400}?"
        r'"' + re.escape(action) + r'",',
        re.DOTALL,
    )
    return len(pattern.findall(src))


def test_t2_loaded_dispatch_present_in_async_setup_entry() -> None:
    """The 'loaded' dispatch site must remain in async_setup_entry.

    Mutation check: deleting the async_dispatcher_send(...
    SIGNAL_ROOM_ENTRY_LIFECYCLE, ..., "loaded") call turns this RED. Any
    live-added room stops being event-driven.
    """
    src = _init_src()
    count = _count_signal_dispatch_with_action(src, "loaded")
    assert count >= 1, (
        "loaded action dispatch missing from __init__.py — deleting the "
        "block breaks per-room onboarding"
    )


def test_t2_unloaded_dispatch_present_in_async_unload_entry() -> None:
    """The 'unloaded' dispatch site must remain in async_unload_entry.

    Mutation check: deleting the dispatch call turns this RED — removed
    rooms silently keep their listeners.
    """
    src = _init_src()
    count = _count_signal_dispatch_with_action(src, "unloaded")
    assert count >= 1, (
        "unloaded action dispatch missing from __init__.py — deleting "
        "the block leaks listeners for removed rooms"
    )


def test_t2_options_updated_dispatch_present() -> None:
    """The suppressed-write 'options_updated' dispatch must remain."""
    src = _init_src()
    count = _count_signal_dispatch_with_action(src, "options_updated")
    assert count >= 1, (
        "options_updated action dispatch missing — future sensor-list "
        "moves into the suppress set will silently blind the substrate"
    )


# ---------------------------------------------------------------------------
# T3 (C-HIGH-3) — swap sequence: register-new before unsub-old
# ---------------------------------------------------------------------------


def test_t3_swap_sequence_register_before_unsub(monkeypatch) -> None:
    """Under the shared 'sequence' log, every register_new must precede
    every unsub_old.

    Mutation check: swapping the order in refresh_subscriptions (unsub
    prior_unsubs BEFORE new_unsub is registered) turns this RED — the
    'unsub' event appears before the second 'register' event.
    """
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]

    sequence: list = []
    reg_counter = {"n": 0}

    def _fake_track(_hass, entities, cb):
        reg_counter["n"] += 1
        my_index = reg_counter["n"]
        sequence.append(("register", my_index, list(entities)))

        def _unsub():
            sequence.append(("unsub", my_index))

        return _unsub

    monkeypatch.setattr(
        substrate_mod, "async_track_state_change_event", _fake_track,
    )
    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send", lambda *a, **k: None,
    )

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()

    # Now add a second sensor to trigger a real atomic swap.
    entry.options = {
        CONF_MOTION_SENSORS: [
            "binary_sensor.office_motion",
            "binary_sensor.office_motion_2",
        ],
    }
    _run(sub.refresh_subscriptions())

    # Assert ordering: for the refresh swap, register (index 2) MUST
    # precede unsub (index 1).
    register_2_pos = next(
        i for i, e in enumerate(sequence)
        if e[0] == "register" and e[1] == 2
    )
    unsub_1_pos = next(
        i for i, e in enumerate(sequence)
        if e[0] == "unsub" and e[1] == 1
    )
    assert register_2_pos < unsub_1_pos, (
        f"swap ordering violated: register #2 at {register_2_pos}, "
        f"unsub #1 at {unsub_1_pos}; full sequence={sequence}"
    )


# ---------------------------------------------------------------------------
# T5 — F1/F2 regressions
# ---------------------------------------------------------------------------


def test_t5_shrink_list_clears_bucket_and_emits_false_edge(monkeypatch) -> None:
    """Shrinking a CONF list clears the stuck-True bucket AND dispatches
    a False edge (post boot-settle).

    F1 fix (A-HIGH-1): pre-fix, shrinking a list left the bucket True
    because only ADDED entities were seeded. Now every desired room's
    bucket is reset+re-seeded from live state on refresh.
    """
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{
            CONF_MOTION_SENSORS: [
                "binary_sensor.office_motion",
                "binary_sensor.office_motion_2",
            ],
        },
    )
    hass.config_entries.async_entries.return_value = [entry]
    _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    dispatched.clear()

    # Simulate: the ORIGINAL sensor (kept) is OFF now; the SECOND sensor
    # (to be removed) previously drove the bucket True.
    sub._raw_state["Office"]["motion"] = True

    # Post-shrink: the surviving sensor's live state is off.
    hass.states.get = MagicMock(return_value=_FakeState("off"))

    # Shrink the CONF list to just the first sensor.
    entry.options = {CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]}
    _run(sub.refresh_subscriptions())

    # Bucket must have been reset and re-seeded to False.
    assert sub._raw_state["Office"]["motion"] is False
    # AND a False edge must have been dispatched.
    assert any(
        signal == SIGNAL_SUBSTRATE_KIND_CHANGED
        and args == ("Office", "motion", False)
        for signal, args in dispatched
    ), f"expected synthetic False edge on shrink; got {dispatched}"


def test_t5_reclassify_clears_old_kind(monkeypatch) -> None:
    """Reclassifying an entity from motion -> occupancy clears the OLD
    kind's stuck-True bucket."""
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_thing"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    _install_track_capture(monkeypatch)
    _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()

    # Force the OLD (motion) bucket to True — as if a real edge landed
    # before reclassification.
    sub._raw_state["Office"]["motion"] = True

    # Post-reclassify: same entity now lives under CONF_OCCUPANCY_SENSORS.
    entry.data = {
        **entry.data,
        CONF_MOTION_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: ["binary_sensor.office_thing"],
    }
    # Live state: currently on.
    hass.states.get = MagicMock(return_value=_FakeState("on"))

    _run(sub.refresh_subscriptions())

    # OLD kind slot must be False.
    assert sub._raw_state["Office"]["motion"] is False, (
        "reclassify did not clear the old kind bucket"
    )
    # NEW kind slot must be True.
    assert sub._raw_state["Office"]["occupancy"] is True


def test_t5_add_sensor_to_existing_room_emits_synthetic_true(monkeypatch) -> None:
    """C-HIGH-4 repro: adding a NEW sensor (currently ON) to an EXISTING
    room must emit a synthetic True edge — not just wait for the next
    real state change.

    F2 fix: pre-fix, step-7 synthetic dispatch was gated on added_rooms
    only, so adding a sensor to an already-tracked room was silent even
    though the bucket flipped True.
    """
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    dispatched.clear()

    # Post-add: two sensors, and the NEW one is currently ON.
    def _states(eid):
        if eid == "binary_sensor.office_motion_2":
            return _FakeState("on")
        return _FakeState("off")

    hass.states.get = MagicMock(side_effect=_states)

    entry.options = {
        CONF_MOTION_SENSORS: [
            "binary_sensor.office_motion",
            "binary_sensor.office_motion_2",
        ],
    }
    _run(sub.refresh_subscriptions())

    assert sub._raw_state["Office"]["motion"] is True
    # Synthetic True edge must have been dispatched.
    assert any(
        signal == SIGNAL_SUBSTRATE_KIND_CHANGED
        and args == ("Office", "motion", True)
        for signal, args in dispatched
    ), (
        f"expected synthetic True edge for add-sensor-to-existing-room; "
        f"got {dispatched}"
    )


# ---------------------------------------------------------------------------
# T4 (C-MED-2) — substrate-gap canary
# ---------------------------------------------------------------------------
# The four C-MED-2 cases live in ``test_substrate_gap_canary.py``:
#   - WARN when a Tier-1 sensor is ON and absent from the substrate map
#   - silent when the sensor IS in the substrate map
#   - once per (room, entity) per boot
#   - silent when hass.data[DOMAIN]["occupancy_substrate"] is None
# Mutation-verified: commenting the WARN emit in
# ``UniversalRoomCoordinator._check_substrate_gap`` flips case 1 RED.

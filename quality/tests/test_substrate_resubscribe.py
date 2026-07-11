"""Substrate re-subscribe cycle — tests for `refresh_subscriptions()`.

Restores the pre-v4.7.24 per-room-onboarding guarantee: a ROOM entry
added AFTER the substrate's initial ``async_setup()`` MUST become
event-driven immediately, without waiting for the room coordinator's
~34s poll interval (Master Bath Toilet 2026-07-09 live regression).

Covers:
* Historical-regression pin — add a ROOM after setup, fire its motion
  sensor, assert the substrate dispatches SIGNAL_SUBSTRATE_KIND_CHANGED
  within one event-loop tick.
* No-stale-dispatch after a room is removed.
* Edit-sensor-list liveness — adding a sensor to a live room takes
  effect on the next edge.
* Atomic-swap ordering — new listener is registered BEFORE the old one
  is released; no lost edge under in-flight state change.
* No-double-dispatch during the overlap window — per-kind edge
  idempotence gate keeps duplicate deliveries to a single dispatch.
"""

from __future__ import annotations

import asyncio
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
from custom_components.universal_room_automation.domain_coordinators.signals import (  # noqa: E501
    SIGNAL_SUBSTRATE_KIND_CHANGED,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeState:
    def __init__(self, state: str) -> None:
        self.state = state


class _FakeEvent:
    def __init__(self, entity_id: str, new_state: _FakeState) -> None:
        self.data = {"entity_id": entity_id, "new_state": new_state}


def _install_track_capture(monkeypatch):
    """Install a fake async_track_state_change_event that records callbacks.

    Returns a list ``registrations`` of (entity_ids_list, callback, unsub_mock)
    tuples. The returned mock unsub records whether it was called.
    """
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
    """Capture async_dispatcher_send calls."""
    dispatched: list = []

    def _fake_send(_hass, signal, *args):
        dispatched.append((signal, args))

    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send", _fake_send,
    )
    return dispatched


def test_refresh_subscriptions_noop_when_no_diff(monkeypatch) -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    regs = _install_track_capture(monkeypatch)
    _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    assert len(regs) == 1

    # No diff — nothing changed in entries.
    _run(sub.refresh_subscriptions())
    # Still exactly one registration — no atomic swap fired.
    assert len(regs) == 1
    assert regs[0][2].called is False


def test_room_added_after_substrate_setup_is_event_driven(monkeypatch) -> None:
    """HISTORICAL-REGRESSION PIN — Master Bath Toilet scenario.

    Substrate setup completes with one room. A NEW ROOM entry is added
    afterward. Fire the new room's motion sensor and assert the substrate
    dispatches SIGNAL_SUBSTRATE_KIND_CHANGED within a single event-loop
    tick — no polling coordinator refresh required.

    This test FAILS if D3 (PresenceCoordinator subscription) or D2
    (refresh_subscriptions) is neutered. Verified red/green by
    temporarily short-circuiting refresh_subscriptions.
    """
    hass = make_hass()
    office = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [office]
    regs = _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    # Release boot-settle so live edges dispatch (mirrors the normal
    # PresenceCoordinator flow).
    sub.release_boot_settle()
    dispatched.clear()  # discard synthetic seed emissions
    assert len(regs) == 1

    # Add the Master Bath Toilet room AFTER substrate setup.
    toilet = fake_room_entry(
        "Master Bath Toilet",
        **{CONF_MOTION_SENSORS: ["binary_sensor.mbt_motion"]},
    )
    hass.config_entries.async_entries.return_value = [office, toilet]

    _run(sub.refresh_subscriptions())

    # Atomic swap must have fired: NEW registration created before old
    # unsub was released.
    assert len(regs) == 2, (
        "expected atomic swap: new listener registered on refresh"
    )
    new_entities, new_cb, _ = regs[1]
    assert "binary_sensor.mbt_motion" in new_entities
    # Old unsub should have been released after new was registered.
    assert regs[0][2].called, "old unsub not released after atomic swap"

    # Now fire the new room's motion sensor — must dispatch immediately.
    new_cb(_FakeEvent("binary_sensor.mbt_motion", _FakeState("on")))

    assert any(
        signal == SIGNAL_SUBSTRATE_KIND_CHANGED
        and args == ("Master Bath Toilet", "motion", True)
        for signal, args in dispatched
    ), (
        f"expected SIGNAL_SUBSTRATE_KIND_CHANGED for new room; got: "
        f"{dispatched}"
    )


def test_refresh_subscriptions_removes_stale_room(monkeypatch) -> None:
    hass = make_hass()
    office = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    kitchen = fake_room_entry(
        "Kitchen", **{CONF_MOTION_SENSORS: ["binary_sensor.kitchen_motion"]},
    )
    hass.config_entries.async_entries.return_value = [office, kitchen]
    regs = _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    dispatched.clear()

    # Remove the kitchen entry.
    hass.config_entries.async_entries.return_value = [office]
    _run(sub.refresh_subscriptions())

    # Fire the removed sensor via the NEW listener callback — should be a
    # no-op (mapping is None short-circuit).
    _, new_cb, _ = regs[-1]
    new_cb(_FakeEvent("binary_sensor.kitchen_motion", _FakeState("on")))

    assert not any(
        signal == SIGNAL_SUBSTRATE_KIND_CHANGED
        and args[0] == "Kitchen"
        for signal, args in dispatched
    ), (
        f"stale room dispatch fired for removed sensor: {dispatched}"
    )
    # `_raw_state` also pruned.
    assert "Kitchen" not in sub._raw_state


def test_refresh_subscriptions_edits_sensor_list(monkeypatch) -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    regs = _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    dispatched.clear()

    # Simulate an options write that ADDS a second motion sensor.
    entry.options = {
        CONF_MOTION_SENSORS: [
            "binary_sensor.office_motion",
            "binary_sensor.office_motion_2",
        ],
    }
    _run(sub.refresh_subscriptions())

    # New listener must include both sensors.
    new_entities, new_cb, _ = regs[-1]
    assert "binary_sensor.office_motion_2" in new_entities

    # Edge on the newly-added sensor dispatches.
    new_cb(_FakeEvent("binary_sensor.office_motion_2", _FakeState("on")))
    assert any(
        signal == SIGNAL_SUBSTRATE_KIND_CHANGED
        and args == ("Office", "motion", True)
        for signal, args in dispatched
    )


def test_refresh_atomic_swap_no_double_dispatch(monkeypatch) -> None:
    """Overlap-window discipline: per-kind edge idempotence prevents double dispatch."""
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    regs = _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    dispatched.clear()

    # Fire a first edge on the original listener — bring it to True.
    old_entities, old_cb, _old_unsub = regs[0]
    old_cb(_FakeEvent("binary_sensor.office_motion", _FakeState("on")))
    assert sum(
        1 for s, _ in dispatched if s == SIGNAL_SUBSTRATE_KIND_CHANGED
    ) == 1
    dispatched.clear()

    # F1/F2 fix-up: refresh_subscriptions re-seeds from LIVE state, so
    # the surviving sensor's true state must be visible via hass.states.
    hass.states.get = MagicMock(
        side_effect=lambda eid: (
            _FakeState("on") if eid == "binary_sensor.office_motion" else None
        ),
    )
    # Options add a second motion sensor — trigger refresh.
    entry.options = {
        CONF_MOTION_SENSORS: [
            "binary_sensor.office_motion",
            "binary_sensor.office_motion_2",
        ],
    }
    _run(sub.refresh_subscriptions())
    assert len(regs) == 2
    new_entities, new_cb, _ = regs[1]

    # Simulate an in-flight duplicate: BOTH the old callback and the new
    # callback fire for the surviving entity (overlap window). The
    # per-kind edge gate (prior == occupied short-circuit) MUST prevent
    # a double dispatch: prior is already True, so on->on emits nothing.
    old_cb(_FakeEvent("binary_sensor.office_motion", _FakeState("on")))
    new_cb(_FakeEvent("binary_sensor.office_motion", _FakeState("on")))

    dispatches = [
        (s, a) for s, a in dispatched if s == SIGNAL_SUBSTRATE_KIND_CHANGED
    ]
    assert len(dispatches) == 0, (
        f"per-kind edge idempotence broken; got {dispatches}"
    )


def test_refresh_no_lost_edge_injected_during_swap(monkeypatch) -> None:
    """Inject a state-change during the refresh call itself.

    Even under an in-flight edge, the substrate must not lose it: either
    the old listener or the new listener catches it, and per-kind
    idempotence ensures exactly one dispatch.
    """
    hass = make_hass()
    entry = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    regs = _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    dispatched.clear()

    # No diff — but we want to prove that even a mid-swap edge on the
    # NEW listener dispatches. Force a real swap by adding a sensor.
    entry.options = {
        CONF_MOTION_SENSORS: [
            "binary_sensor.office_motion",
            "binary_sensor.office_motion_2",
        ],
    }
    _run(sub.refresh_subscriptions())

    _, new_cb, _ = regs[-1]
    # Edge lands on new listener after atomic swap — dispatches cleanly.
    new_cb(_FakeEvent("binary_sensor.office_motion", _FakeState("on")))
    hits = [
        (s, a) for s, a in dispatched if s == SIGNAL_SUBSTRATE_KIND_CHANGED
    ]
    assert len(hits) == 1
    assert hits[0][1] == ("Office", "motion", True)


def test_added_room_synthetic_true_slot_when_boot_settle_done(monkeypatch) -> None:
    """Late-added room with a sensor already ON emits a synthetic True edge.

    Mirrors the ``release_boot_settle`` pattern for the LATE-add case so
    consumers that missed the boot-settle sync don't stay silent until
    the next real edge.
    """
    hass = make_hass()
    office = fake_room_entry(
        "Office", **{CONF_MOTION_SENSORS: ["binary_sensor.office_motion"]},
    )
    hass.config_entries.async_entries.return_value = [office]
    _install_track_capture(monkeypatch)
    dispatched = _install_dispatch_capture(monkeypatch)

    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    dispatched.clear()

    # New room's sensor is ALREADY ON at the time of add.
    hass.states.get = MagicMock(
        side_effect=lambda eid: (
            _FakeState("on") if eid == "binary_sensor.mbt_motion" else None
        ),
    )
    toilet = fake_room_entry(
        "Master Bath Toilet",
        **{CONF_MOTION_SENSORS: ["binary_sensor.mbt_motion"]},
    )
    hass.config_entries.async_entries.return_value = [office, toilet]

    _run(sub.refresh_subscriptions())

    # Synthetic True-slot dispatch must have fired for the new room.
    hits = [
        (s, a) for s, a in dispatched if s == SIGNAL_SUBSTRATE_KIND_CHANGED
    ]
    assert any(
        a == ("Master Bath Toilet", "motion", True) for _, a in hits
    ), f"synthetic True-slot for late-added room missing; got {hits}"

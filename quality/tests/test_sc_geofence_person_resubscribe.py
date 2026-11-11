"""SC-GEOFENCE-PERSON-SNAPSHOT-1 — the SC geofence arrival listener must watch
person entities added AFTER setup (and stop watching removed ones).

Drives the REAL ``SecurityCoordinator._setup_geofence_listener`` and the real
``_handle_person_state_change`` (via its observable effect: an expected
arrival registered on the sanction checker) against the lockout harness
World, whose trackers stand in for HA's event helpers.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from _lockout_harness import TZ, World, load

const = load("const")
sec = load("domain_coordinators.security")

START = datetime(2026, 11, 11, 12, 0, tzinfo=TZ)
OJI = "person.oji"
NEW = "person.newcomer"


def _rig(monkeypatch, persons):
    w = World(START, {}, entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    w.hass.data[const.DOMAIN] = {}
    for pid, st in persons.items():
        w.seed(pid, st)
    monkeypatch.setattr(sec, "async_track_state_change_event", w.track_state)
    monkeypatch.setattr(sec, "async_track_state_added_domain", w.track_added)
    monkeypatch.setattr(sec, "async_track_state_removed_domain", w.track_removed)
    sc = sec.SecurityCoordinator(w.hass, lock_entities=[], garage_entities=[])
    sc._armed_state = sec.ArmedState.ARMED_AWAY
    added: list[str] = []
    sc._sanction_checker.add_expected_arrival = (
        lambda eid, window_minutes=0: added.append(eid)
    )
    sc._setup_geofence_listener()
    return w, sc, added


def test_person_added_after_setup_is_watched(monkeypatch):
    w, sc, added = _rig(monkeypatch, {OJI: "not_home"})
    w.set_state(NEW, "not_home")  # added-domain event
    w.set_state(NEW, "home")
    assert added == [NEW]
    # the pre-existing person is still watched after the rebuild
    w.set_state(OJI, "home")
    assert added == [NEW, OJI]


def test_zero_persons_at_setup_then_one_added_is_watched(monkeypatch):
    w, sc, added = _rig(monkeypatch, {})
    assert w.added_cbs and w.removed_cbs  # subscribed despite empty set
    w.set_state(NEW, "not_home")
    w.set_state(NEW, "home")
    assert added == [NEW]


def test_removed_person_dropped_from_rebuilt_listener(monkeypatch):
    w, sc, added = _rig(monkeypatch, {OJI: "not_home", NEW: "not_home"})
    w.set_state(NEW, None)  # removed-domain event
    active = [r["ids"] for r in w.listeners if r["active"]]
    assert active == [{OJI}]
    w.set_state(OJI, "home")
    assert added == [OJI]


def test_unload_cancels_add_remove_and_person_listeners(monkeypatch):
    w, sc, added = _rig(monkeypatch, {OJI: "not_home"})
    sc._cancel_listeners()
    assert w.added_cbs == [] and w.removed_cbs == []
    assert not any(r["active"] for r in w.listeners)
    w.set_state(NEW, "not_home")
    w.set_state(NEW, "home")
    w.set_state(OJI, "home")
    assert added == []


def test_existing_persons_unchanged_behaviour(monkeypatch):
    w, sc, added = _rig(monkeypatch, {OJI: "not_home"})
    w.set_state(OJI, "home")
    assert added == [OJI]

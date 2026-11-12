"""D1 of PLANNING_lock_suspicious_arrival_hold.md: ``stale_source_arrival``.

Pure predicate over states: True iff the person reads home / a zone AND its
``source`` tracker did not change at the person's edge (missing source, no
source state, or ``person.last_changed - source.last_changed > stale_s``).
Bounds are literals (10 s), never the imported constant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from _lockout_harness import load

AE = load("arrival_edges")

T = datetime(2026, 11, 12, 11, 29, 29, tzinfo=timezone.utc)
OJI = "person.oji_udezue"
IPAD = "device_tracker.okosisipadmini6_2"
PHONE = "device_tracker.phone"


class S:
    def __init__(self, state, attrs=None, last_changed=None, last_updated=None):
        self.state = state
        self.attributes = dict(attrs or {})
        self.last_changed = last_changed
        self.last_updated = last_updated or last_changed


def getter(states):
    return states.get


def _person(state, source, lc=T):
    attrs = {"source": source} if source else {}
    return S(state, attrs, lc)


def test_stale_source_home_older_than_bound_is_stale():
    states = {OJI: _person("home", IPAD), IPAD: S("home", {}, T - timedelta(seconds=4119))}
    assert AE.stale_source_arrival(getter(states), OJI, 10.0) is True


def test_stale_source_fresh_and_boundary():
    # Real arrivals: the source changed with the person (age 0.0003 s).
    states = {OJI: _person("home", PHONE), PHONE: S("home", {}, T - timedelta(seconds=0.0003))}
    assert AE.stale_source_arrival(getter(states), OJI, 10.0) is False
    states[PHONE] = S("home", {}, T - timedelta(seconds=10))  # exactly the bound
    assert AE.stale_source_arrival(getter(states), OJI, 10.0) is False
    states[PHONE] = S("home", {}, T - timedelta(seconds=10.5))
    assert AE.stale_source_arrival(getter(states), OJI, 10.0) is True


def test_stale_source_missing_source_or_no_state():
    assert AE.stale_source_arrival(getter({OJI: _person("home", None)}), OJI, 10.0) is True
    assert AE.stale_source_arrival(getter({OJI: _person("home", IPAD)}), OJI, 10.0) is True
    undated = {OJI: _person("home", IPAD), IPAD: S("home", {}, None)}
    assert AE.stale_source_arrival(getter(undated), OJI, 10.0) is True


def test_stale_source_not_home_and_unreal_never_stale():
    for val in ("not_home", "unknown", "unavailable"):
        states = {OJI: _person(val, IPAD), IPAD: S("home", {}, T - timedelta(hours=3))}
        assert AE.stale_source_arrival(getter(states), OJI, 10.0) is False, val
    assert AE.stale_source_arrival(getter({}), OJI, 10.0) is False


def test_stale_source_zone_and_event_state():
    states = {OJI: _person("Near Home", IPAD),
              IPAD: S("Near Home", {}, T - timedelta(seconds=600))}
    assert AE.stale_source_arrival(getter(states), OJI, 10.0) is True
    # person_state (the event's new_state) wins over the stored person.
    fresh = _person("home", PHONE)
    states[PHONE] = S("home", {}, T)
    assert AE.stale_source_arrival(getter(states), OJI, 10.0, person_state=fresh) is False


def test_stale_source_reads_last_changed_not_last_updated():
    """An attribute-only refresh bumps only last_updated (F2)."""
    ipad = S("home", {}, T - timedelta(hours=3), last_updated=T)
    states = {OJI: _person("home", IPAD), IPAD: ipad}
    assert AE.stale_source_arrival(getter(states), OJI, 10.0) is True

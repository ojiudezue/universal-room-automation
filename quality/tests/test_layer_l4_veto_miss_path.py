"""LAYER-LEAK-CLEANUP-1 L4 (BUILD-MINIMAL, plan §4 D1): the five fail-open
identity vetoes resolve the REAL person entity on the miss path only.

A second install whose person entity id is not the slug of its name
(``person.oji_udezue_2`` named "Oji Udezue") used to get no veto at all,
because each site read ``person.<slug>`` by string and treated a missing
state as "not vetoed". Each test below drives the real enclosing method.

Oracles are hand-written: a ``not_home`` person is vetoed, a ``home`` one
is not, whatever the entity id is.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from test_egress_identity_producer_d2b import (  # noqa: F401 (stub fixture)
    _configure_integration_entry,
    _install_legs,
    _install_stub_modules,
    _leg,
    _make_state,
    _make_tracker,
    PersonCensus,
    _StubCameraManager,
)
from _provenance_harness import make_hass

from custom_components.universal_room_automation import person_ids
from custom_components.universal_room_automation.domain_coordinators import (
    signals as layer_signals,
)

UTC = timezone.utc


def _counters(hass):
    """The counters object production actually wrote, read straight from
    ``hass.data`` (hermetic: earlier test files may re-import ``signals``, so
    an isinstance-checking ``layer_counters`` from this file's import could
    replace it with a fresh zeroed one)."""
    dom = hass.data.get(layer_signals._LAYER_DOMAIN, {}) if isinstance(hass.data, dict) else {}
    c = dom.get(layer_signals._LAYER_COUNTERS_KEY)
    return c if c is not None else SimpleNamespace(
        person_entity_fallback_hits=0, person_entity_fallback_misses=0)
NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
FACE_SENSOR = "sensor.frigate_oji_last_camera_2"
# This house's live person set (every entity id equals its slug).
LIVE_PERSONS = ("person.ezinne", "person.oji_udezue", "person.jaya", "person.ziri")


def _person(entity_id, state, name, extra=None):
    attrs = {"friendly_name": name}
    attrs.update(extra or {})
    st = _make_state(state, NOW, attributes=attrs)
    st.entity_id = entity_id
    return st


def _world(person_states, tracked=("Oji Udezue",)):
    """Census + hass whose states map holds ``person_states`` and whose
    ``states.async_all('person')`` lists them (HA's own person entities)."""
    hass = make_hass()
    st_map = {s.entity_id: s for s in person_states}
    hass.states.get = lambda eid: st_map.get(eid)
    calls = []

    def _all(domain=None):
        # Honours the domain filter like HA's StateMachine.async_all.
        calls.append(domain)
        if domain is None:
            return list(st_map.values())
        return [s for e, s in st_map.items() if e.split(".", 1)[0] == domain]

    hass.states.async_all = _all
    _configure_integration_entry(hass, tracked=tracked)
    hass.data = {}
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    return SimpleNamespace(hass=hass, st=st_map, census=census, all_calls=calls)


# ----------------------------------------------------------------- the five sites
def _site_face_leg(w, slug):
    return w.census.is_face_leg_person_vetoed(SimpleNamespace(canonical_slug=slug))


def _site_sighting_hint(w, slug):
    return w.census.face_person_would_be_vetoed(slug)


def _site_face_latch(w, slug):
    w.st[FACE_SENSOR] = _make_state("front_door", NOW - timedelta(seconds=30))
    w.census._resolve_last_camera_entity_id = lambda s: FACE_SENSOR
    return w.census._get_face_recognized_person_names(NOW) == []


def _site_ble_trackers(w, slug):
    # Not a veto boolean: the BLE crossing producer must FIND the person's
    # trackers. "vetoed" here = the person's BLE tracker was found.
    tid = "device_tracker.oji_bermuda_tracker"
    w.st[tid] = _make_state("home", NOW, attributes={"source_type": "bluetooth_le"})
    return w.census._derive_ble_crossing_trackers() == {tid: slug}


def _site_egress(w, slug):
    tracker = _make_tracker(w.census, w.hass, interior_stems=["foyer"])
    _install_legs(w.census, {
        "front_door": [_leg("sensor.front_door_last_recognized_face", "frigate",
                            "d1", slug, NOW - timedelta(seconds=20))],
    })
    out = tracker._resolve_egress_face_identity_ex(
        "binary_sensor.front_door_person_occupancy", NOW, "exit")
    return out[3].outcome == "vetoed"


SITES = {
    "is_face_leg_person_vetoed": _site_face_leg,
    "face_person_would_be_vetoed": _site_sighting_hint,
    "_get_face_recognized_person_names": _site_face_latch,
    "_derive_ble_crossing_trackers": _site_ble_trackers,
    "_resolve_egress_face_identity_ex": _site_egress,
}
TRACKERS = {"device_trackers": ["device_tracker.oji_bermuda_tracker"]}


@pytest.mark.parametrize("site", sorted(SITES))
def test_veto_display_name_person_not_fail_open(site):
    """Person entity id differs from the slug: the site acts exactly as it
    does in the slug case (it used to fail open)."""
    w = _world([_person("person.oji_udezue_2", "not_home", "Oji Udezue", TRACKERS)])
    assert SITES[site](w, "oji_udezue") is True
    c = _counters(w.hass)
    assert c.person_entity_fallback_hits >= 1
    assert c.person_entity_fallback_misses == 0


@pytest.mark.parametrize("site", sorted(SITES))
def test_veto_slug_person_same_answer(site):
    """Slug case (this house): same answer as the display-name case."""
    w = _world([_person("person.oji_udezue", "not_home", "Oji Udezue", TRACKERS)])
    assert SITES[site](w, "oji_udezue") is True


@pytest.mark.parametrize("site", sorted(s for s in SITES if s != "_derive_ble_crossing_trackers"))
def test_veto_display_name_person_home_not_vetoed(site):
    """The fallback reads the real state: a home person is NOT vetoed."""
    w = _world([_person("person.oji_udezue_2", "home", "Oji Udezue", TRACKERS)])
    assert SITES[site](w, "oji_udezue") is False


@pytest.mark.parametrize("site", sorted(SITES))
def test_veto_ambiguous_person_keeps_fail_open(site):
    """Two person entities match the slug: no guess, today's answer (fail
    open / no trackers) and one miss counted per lookup."""
    w = _world([
        _person("person.oji_udezue_2", "not_home", "Oji Udezue", TRACKERS),
        _person("person.oji_udezue_3", "not_home", "Oji Udezue", TRACKERS),
    ])
    assert SITES[site](w, "oji_udezue") is False
    c = _counters(w.hass)
    assert c.person_entity_fallback_hits == 0
    assert c.person_entity_fallback_misses >= 1


@pytest.mark.parametrize("state", ["home", "not_home"])
@pytest.mark.parametrize("eid", LIVE_PERSONS)
def test_veto_exact_entity_byte_identical(eid, state):
    """Golden over this house's live person set: the exact id is returned,
    no person scan runs, nothing is counted, and every veto site decides
    exactly raw == not_home (today's decision)."""
    slug = eid.split(".", 1)[1]
    persons = [_person(p, state if p == eid else "home", p.split(".")[1].replace("_", " ").title(),
                       {"device_trackers": ["device_tracker.oji_bermuda_tracker"]} if p == eid else None)
               for p in LIVE_PERSONS]
    w = _world(persons, tracked=tuple(p.split(".")[1].replace("_", " ").title() for p in LIVE_PERSONS))
    assert person_ids.person_entity_for_slug(w.hass, slug) == eid
    expected = state == "not_home"
    assert _site_face_leg(w, slug) is expected
    assert _site_sighting_hint(w, slug) is expected
    assert _site_egress(w, slug) is expected
    assert w.all_calls == []
    c = _counters(w.hass)
    assert (c.person_entity_fallback_hits, c.person_entity_fallback_misses) == (0, 0)


def test_person_entity_for_slug_ambiguous_is_none():
    w = _world([
        _person("person.a_1", "home", "Oji Udezue"),
        _person("person.oji_udezue_x", "home", "Someone Else"),
        _person("person.b_1", "home", "Oji Udezue"),
    ])
    assert person_ids.person_entity_for_slug(w.hass, "oji_udezue") == "person.oji_udezue"


def test_person_entity_for_slug_no_match_returns_exact():
    w = _world([_person("person.someone", "home", "Someone")])
    assert person_ids.person_entity_for_slug(w.hass, "oji_udezue") == "person.oji_udezue"
    assert _counters(w.hass).person_entity_fallback_misses == 1


def test_person_entity_for_slug_matches_entity_id_slug():
    """Match by the entity's own id slug (no friendly name)."""
    st = _make_state("home", NOW, attributes={})
    st.entity_id = "person.Oji_Udezue"
    w = _world([st])
    assert person_ids.person_entity_for_slug(w.hass, "oji_udezue") == "person.Oji_Udezue"


def test_layer_diagnostics_expose_fallback_counters():
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    w = _world([_person("person.oji_udezue_2", "home", "Oji Udezue")])
    # Hermetic: write through the signals module this presence code itself
    # holds (counting is pinned by the tests above; this pins the exposure).
    pres_signals = PresenceCoordinator.get_layer_diagnostics.__globals__["_layer_signals"]
    c = pres_signals.layer_counters(w.hass)
    c.person_entity_fallback_hits = 1
    c.person_entity_fallback_misses = 1
    pres = object.__new__(PresenceCoordinator)
    pres.hass = w.hass
    out = PresenceCoordinator.get_layer_diagnostics(pres)
    assert out["person_entity_fallback_hits"] == 1
    assert out["person_entity_fallback_misses"] == 1


# ----------------------------------------------------------- review C additions
def test_empty_or_guest_slug_no_lookup_no_miss():
    """A nameless person entity must not match an empty slug, and an empty or
    guest slug counts no miss and runs no scan."""
    st = _make_state("not_home", NOW, attributes={})
    st.entity_id = "person.nameless"
    w = _world([st])
    assert person_ids.person_entity_for_slug(w.hass, "") == "person."
    assert person_ids.person_entity_for_slug(w.hass, "guest:bob") == "person.guest:bob"
    assert w.all_calls == []
    c = _counters(w.hass)
    assert (c.person_entity_fallback_hits, c.person_entity_fallback_misses) == (0, 0)


def test_non_person_state_never_matches():
    """A non-person state named like the person (returned by an unfiltered
    scan) is never taken as the person."""
    decoy = _make_state("not_home", NOW, attributes={"friendly_name": "Oji Udezue"})
    decoy.entity_id = "sensor.oji_udezue"
    w = _world([decoy])
    w.hass.states.async_all = lambda domain=None: [decoy]
    assert person_ids.person_entity_for_slug(w.hass, "oji_udezue") == "person.oji_udezue"


def test_scan_asks_for_person_domain():
    w = _world([_person("person.oji_udezue_2", "home", "Oji Udezue")])
    assert person_ids.person_entity_for_slug(w.hass, "oji_udezue") == "person.oji_udezue_2"
    assert w.all_calls == ["person"]


def test_slug_used_exactly_as_passed():
    """The exact id is built from the slug as passed (no slug_of): a
    mixed-case id that exists is an exact hit, no scan."""
    st = _make_state("home", NOW, attributes={})
    st.entity_id = "person.Oji_X"
    w = _world([st])
    assert person_ids.person_entity_for_slug(w.hass, "Oji_X") == "person.Oji_X"
    assert w.all_calls == []


def test_guard_taints_bare_helper_name():
    """Guard engine: a raw read through the bare helper name (transit's
    import form) in a non-member module is an R3 hit."""
    from test_person_awareness_layer_guard import _rules
    src = ("def f(hass, s):\n"
           "    return hass.states.get(person_entity_for_slug(hass, s))\n")
    assert "R3" in _rules(src)

"""FACE-ARRIVAL-REBUILD-1 D2 (plan rev 11 §3.3, §9 D2): the ONE camera_face
arrival site, `PresenceCoordinator._derive_face_arrival`, called from the
sighting emit. Sightings enter through REAL face-sensor changes; arrivals are
observed on the REAL dispatcher. FACE_ARRIVAL_INTERIOR_ENABLED ships False
(D0-P3 NO-GO); most tests flip it on to exercise the rule.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
import pytest_asyncio

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse


@pytest_asyncio.fixture
async def rig(mods, hass, monkeypatch):
    r = await R.build(mods, hass, monkeypatch,
                      persons={p: "not_home" for p in R.TRACKED})
    arrivals: list = []

    def _cap(payload):
        arrivals.append(payload)

    _cap._hass_callback = True
    r.unsubs.append(mods.dispatcher.async_dispatcher_connect(
        hass, mods.signals.SIGNAL_PERSON_ARRIVING, _cap))
    r.arrivals = arrivals
    yield r
    await R.teardown(r)


@pytest.fixture
def interior_on(mods, monkeypatch):
    monkeypatch.setattr(mods.const, "FACE_ARRIVAL_INTERIOR_ENABLED", True)


def _skips(rig):
    return dict(rig.producer.skips_by_reason)


async def _person(rig, pid, state):
    rig.hass.states.async_set(pid, state)
    await rig.hass.async_block_till_done()


@pytest.mark.asyncio
async def test_kill_switch_noop(rig):
    """Shipped default (interior arrivals off): a class (i) face gives a
    sighting and NO arrival; the skip is counted."""
    await R.face(rig, "family_room", "Oji")
    assert len(rig.sightings) == 1
    assert rig.arrivals == []
    assert _skips(rig) == {"disabled_interior": 1}


@pytest.mark.asyncio
async def test_d2_dispatch_carries_camera_face_source(rig, interior_on):
    await R.face(rig, "master_hallway", "Oji")
    (a,) = rig.arrivals
    assert a["source"] == "camera_face"
    assert a["person_entity"] == "person.oji_udezue"
    assert a["sighting"] is rig.sightings[0]
    assert a["zone"] == "Entertainment"


@pytest.mark.asyncio
async def test_home_resident_no_arrival(rig, interior_on):
    """A resident at home walking past family_room 10 times: 0 arrivals
    (v3.19 gave 10)."""
    await _person(rig, "person.oji_udezue", "home")
    p = rig.producer
    key = next(k for k, v in p._views.items() if R.FAMILY in v.picks)
    base = time.time()
    for i in range(10):
        p._emit_interior(key, "Oji", base + 70 * i, synthetic=False)
    assert len(rig.sightings) == 10
    assert rig.arrivals == []
    assert _skips(rig) == {"home": 10}


@pytest.mark.asyncio
async def test_phone_already_home_skip(rig, interior_on):
    """Face at t, the phone's home edge at t+20 s (read through the REAL
    person listener), then the rule evaluates a later copy: phone already
    home -> skipped. Also: an edge 299 s before the face skips, 301 s does
    not (literal gap 300)."""
    pres = rig.presence
    pres._last_home_edge_ts["oji_udezue"] = time.time() + 20  # edge after the face
    await R.face(rig, "family_room", "Oji")
    assert rig.arrivals == []
    assert _skips(rig)["phone_already_home"] == 1
    p = rig.producer
    key = next(k for k, v in p._views.items() if R.UPSTAIRS in v.picks)
    t = time.time() + 1000
    pres._last_home_edge_ts["oji_udezue"] = t - 299
    p._emit_interior(key, "Oji", t, synthetic=False)
    assert rig.arrivals == []
    pres._last_home_edge_ts["oji_udezue"] = t + 2000 - 301
    p._emit_interior(key, "Oji", t + 2000, synthetic=False)
    assert len(rig.arrivals) == 1


@pytest.mark.asyncio
async def test_last_home_edge_written_by_real_person_listener(rig, interior_on):
    """The writer is `_handle_geofence_change`: a live not_home -> home edge
    on the REAL bus stamps it and the D2 rule then skips the face."""
    rig.presence._subscribe_geofence()
    await _person(rig, "person.oji_udezue", "home")
    assert "oji_udezue" in rig.presence._last_home_edge_ts
    await _person(rig, "person.oji_udezue", "not_home")  # tracker flaps back
    await R.face(rig, "family_room", "Oji")
    assert [a for a in rig.arrivals if a["source"] == "camera_face"] == []
    assert _skips(rig) == {"phone_already_home": 1}


@pytest.mark.asyncio
async def test_unknown_state_fails_closed(rig, interior_on):
    for st in ("unknown", "unavailable"):
        await _person(rig, "person.jaya", st)
    await R.face(rig, "family_room", "Jaya")
    assert rig.arrivals == []
    assert _skips(rig) == {"unknown_state": 1}


@pytest.mark.asyncio
async def test_fixture_classes(rig, interior_on):
    """(i) not_home, phone later -> arrival; (ii) not_home, no phone ->
    arrival (comfort accepts; access gates reject, D3); named zone ->
    arrival; (iii)/(iv) home -> none."""
    await R.face(rig, "family_room", "Oji")              # (i)/(ii) not_home
    await _person(rig, "person.ezinne", "work")
    await R.face(rig, "master_hallway", "Ezinne")        # named zone
    await _person(rig, "person.ziri", "home")
    await R.face(rig, "upstairs_hall", "Ziri")           # (iv)
    assert sorted(a["person_entity"] for a in rig.arrivals) == [
        "person.ezinne", "person.oji_udezue"]


@pytest.mark.asyncio
async def test_egress_never_arrival(rig, interior_on):
    await R.egress(rig)
    await R.egress(rig, direction="exit", person_id="jaya")
    assert len(rig.sightings) == 2
    assert rig.arrivals == []
    assert _skips(rig) == {"not_arrival_role": 2}


@pytest.mark.asyncio
async def test_observation_mode_suppresses_arrival(rig, interior_on):
    rig.presence.observation_mode = True
    await R.face(rig, "family_room", "Oji")
    assert rig.arrivals == []
    assert _skips(rig) == {"observation_mode": 1}


@pytest.mark.asyncio
async def test_boot_window_suppresses_arrival(rig, interior_on):
    """Rule 4 in isolation: the sighting is emitted (producer boot window
    passed) but the rule's own boot gate reads a later setup time."""
    p = rig.producer
    key = next(iter(p._views))
    t = time.time()
    p._emit_interior(key, "Oji", t, synthetic=False)
    assert len(rig.arrivals) == 1
    rig.arrivals.clear()
    real = p._setup_ts
    s = rig.sightings[-1]
    p._setup_ts = t - 599           # literal: 600 s window
    rig.presence._face_arrival_cooldown.clear()
    rig.presence._derive_face_arrival(s)
    assert rig.arrivals == []
    assert _skips(rig)["boot"] == 1
    p._setup_ts = real


@pytest.mark.asyncio
async def test_arrival_debounce_per_person(rig, interior_on):
    p = rig.producer
    k1 = next(k for k, v in p._views.items() if R.FAMILY in v.picks)
    k2 = next(k for k, v in p._views.items() if R.UPSTAIRS in v.picks)
    t = time.time()
    p._emit_interior(k1, "Oji", t, synthetic=False)
    p._emit_interior(k2, "Oji", t + 599, synthetic=False)   # literal 600
    p._emit_interior(k2, "Oji", t + 601 + 60, synthetic=False)
    assert len(rig.arrivals) == 2
    assert _skips(rig) == {"debounce": 1}


@pytest.mark.asyncio
async def test_hvac_counter_matches_compound_zone(rig, interior_on):
    """`master_hallway` is in Entertainment AND Master Suite, both on HVAC
    zone_1 ("Entertainment + Master Suite"): its counter rises by ONE; the
    house-zone trackers rise once each; zone_2 is untouched."""
    z1 = SimpleNamespace(zone_name="Entertainment + Master Suite", rooms=["Family Room"],
                         camera_face_arrivals_today=0)
    z2 = SimpleNamespace(zone_name="Upstairs", rooms=["Upstairs Hall"],
                         camera_face_arrivals_today=0)
    hvac = SimpleNamespace(zone_manager=SimpleNamespace(zones={"zone_1": z1, "zone_2": z2}))
    rig.hass.data[R.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"hvac": hvac})
    await R.face(rig, "master_hallway", "Oji")
    assert len(rig.arrivals) == 1
    assert (z1.camera_face_arrivals_today, z2.camera_face_arrivals_today) == (1, 0)
    t = rig.presence._zone_trackers
    assert (t["Entertainment"]._face_arrivals_today,
            t["Master Suite"]._face_arrivals_today) == (1, 1)


@pytest.mark.asyncio
async def test_emitted_arrival_notes_producer(rig, interior_on):
    """C-L1: a dispatched arrival re-arms the face_arrival_zero anchor
    (producer._last_arrival_ts) and counts the arrival."""
    await R.face(rig, "family_room", "Oji")
    assert len(rig.arrivals) == 1
    assert rig.producer._last_arrival_ts == rig.sightings[0].ts
    assert rig.producer.arrivals_derived_today == 1

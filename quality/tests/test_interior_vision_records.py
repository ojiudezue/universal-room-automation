"""VISION-INTERIOR-SIGHTINGS-1 ship 1 (plan
docs/planning/PLANNING_vision_interior_sightings.md §7, §8b, §9.D1, §9.D5,
§9.D7): F4 UNNAMED room records and the no-model path time-lapse.

REAL hass + REAL PresenceCoordinator / PersonSightingProducer / PersonCensus
/ CameraResolver over the registry fixture extracted from the live house
(``_sighting_rig``). The producer's record build is driven through its own
production entry (``interior_tick``, the timer callback body); the twin
groups come from the REAL ship 3b pairing over that registry. Oracles are
hand-written numbers and names, never re-computed by the code under test.
"""
from __future__ import annotations

import importlib
import sys
import time
import types
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

PKG = "custom_components.universal_room_automation"
FAM_F = R.FAMILY            # Frigate person sensor, device 62f7...
FAM_P = R.FAMILY_PROTECT    # Protect person sensor, device c580...
MAS_F = R.MASTER            # Frigate, device 01df...
MAS_P = "binary_sensor.master_hallway_person_detected"   # Protect, f3dd...
FAM_KEY = "62f7b21e657126f3482121f0f49d08fc"   # min(62f7..., c580...)
MAS_KEY = "01dfad506f0741fb00d9daf9b34dee08"   # min(01df..., f3dd...)
OJI = "oji_udezue"
JAYA = "jaya"
EZ = "ezinne"


def _mod(name):
    return sys.modules[f"{PKG}.{name}"] if f"{PKG}.{name}" in sys.modules \
        else importlib.import_module(f"{PKG}.{name}")


class _PC:
    """A person coordinator whose BLE-in-room read is the REAL
    ``PersonTrackingCoordinator.persons_in_room`` (and its real
    ``get_room_occupants``) over a scripted ``data``."""

    def __init__(self, hass, data):
        cls = _mod("person_coordinator").PersonTrackingCoordinator
        self.hass = hass
        self.data = data
        self.get_room_occupants = types.MethodType(cls.get_room_occupants, self)
        self.persons_in_room = types.MethodType(cls.persons_in_room, self)


def _ble(location, status="active", conf=0.9):
    return {"location": location, "confidence": conf, "tracking_status": status}


def _room_entry(m, name, area, room_type="common_area"):
    c = m.const
    return SimpleNamespace(entry_id=f"room_{area}", data={
        c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_ROOM, c.CONF_ROOM_NAME: name,
        c.CONF_AREA_ID: area, c.CONF_ROOM_TYPE: room_type}, options={})


@pytest_asyncio.fixture
async def rig(mods, hass, monkeypatch):  # noqa: F811
    r = await R.build(mods, hass, monkeypatch)
    ents = R.entries(mods) + [
        _room_entry(mods, "Family Room", "living_room"),
        _room_entry(mods, "Master Hallway", "master_hallway", "hallway"),
    ]
    R.install_entries(hass, monkeypatch, ents)
    r.interior = [FAM_F, FAM_P, MAS_F, MAS_P]
    monkeypatch.setattr(r.census, "_get_interior_camera_entities", lambda: list(r.interior))
    r.producer._interior_registries = lambda: (r.er, r.dr)
    r.views = {}
    csh = _mod("domain_coordinators.camera_stream_health")
    cth = _mod("domain_coordinators.camera_twin_health")
    monkeypatch.setattr(csh, "entity_stream_view",
                        lambda hass_, eid, census=False: r.views.get(eid))
    r.dead = {}
    monkeypatch.setattr(cth, "physical_camera_dead",
                        lambda hass_, key: r.dead.get(key, False))
    r.pc = _PC(hass, {})
    hass.data[R.DOMAIN]["person_coordinator"] = r.pc
    for eid in r.interior:
        hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    yield r
    await R.teardown(r)


def _set(rig, readings, states=None):
    rig.census._stream_last_reading = dict(readings)
    for eid, st in (states or {}).items():
        rig.hass.states.async_set(eid, st)


def _rec(rig, room):
    rows = [x for x in rig.producer.get_room_sightings() if x.room == room]
    assert len(rows) == 1, [(x.room, x.status) for x in rig.producer.get_room_sightings()]
    return rows[0]


# ------------------------------------------------------------------ groups
@pytest.mark.asyncio
async def test_group_key_equals_canonical_key(rig):
    """The interior key of a twin group (min device id of the 3b pairing) is
    the producer's canonical camera key of the same camera (plan §7)."""
    rig.producer.interior_tick()
    keys = {g["room"]: g["group_key"] for g in rig.producer._interior_groups}
    assert keys == {"Family Room": FAM_KEY, "Master Hallway": MAS_KEY}
    fus = rig.resolver.resolve_operator_declaration([FAM_P])
    assert rig.m.resolver.canonical_camera_key(fus[0]) == FAM_KEY
    members = {g["room"]: g["members"] for g in rig.producer._interior_groups}
    assert members["Family Room"] == tuple(sorted((FAM_F, FAM_P)))


# ------------------------------------------------------------------ D1
@pytest.mark.asyncio
async def test_room_records_statuses(rig):
    """Family room NVR 2 bodies: BLE {ezinne} -> unnamed_present / 1;
    BLE {ezinne, jaya} -> confirmed; NVR 0 with BLE {jaya} -> ble_unconfirmed;
    no BLE and NVR 0 -> empty. The census result is never touched."""
    census_before = rig.census.last_result
    _set(rig, {FAM_F: 2, FAM_P: 1, MAS_F: 0, MAS_P: 0},
         {FAM_F: "on", FAM_P: "on"})
    rig.pc.data = {EZ: _ble("family_room")}
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.bodies_nvr, r.unnamed, r.status) == (2, 2, 1, "unnamed_present")
    assert (r.named, r.provenance, r.liveness) == ((EZ,), "nvr", "live")
    rig.pc.data = {EZ: _ble("family_room"), JAYA: _ble("family_room")}
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.unnamed, r.status, r.named) == (2, 0, "confirmed", (EZ, JAYA))
    _set(rig, {FAM_F: 0, FAM_P: 0, MAS_F: 0, MAS_P: 0})
    rig.pc.data = {JAYA: _ble("family_room")}
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.unnamed, r.status) == (0, 0, "ble_unconfirmed")
    assert _rec(rig, "Master Hallway").status == "empty"
    assert rig.census.last_result is census_before


@pytest.mark.asyncio
async def test_live_twin_carries_the_record(rig):
    """Frigate member released, Protect member LIVE reading 1 -> bodies 1,
    not missing (one NVR has the camera)."""
    _set(rig, {FAM_F: 0, FAM_P: 1}, {FAM_P: "on"})
    rig.views[FAM_F] = "released"
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.status, r.liveness) == (1, "unnamed_present", "live")


@pytest.mark.asyncio
async def test_no_live_member_is_missing_not_empty(rig):
    """Both members held -> missing, bodies None, liveness held (never 0).
    Every NVR lost the camera (ship 3b) -> liveness lost."""
    _set(rig, {FAM_F: 0, FAM_P: 0})
    rig.views.update({FAM_F: "held", FAM_P: "held"})
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.unnamed, r.status, r.liveness) == (None, None, "missing", "held")
    rig.dead[FAM_KEY] = True
    rig.producer.interior_tick()
    assert _rec(rig, "Family Room").liveness == "lost"
    # No reading at all (states unavailable, no view) is missing too.
    rig.views.clear()
    rig.dead.clear()
    _set(rig, {}, {FAM_F: "unavailable", FAM_P: "unknown"})
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.status, r.liveness) == (None, "missing", "no_reading")


@pytest.mark.asyncio
async def test_held_frozen_reading_not_used_on_record(rig):
    """A held Frigate member's frozen reading 3 never reaches the record;
    the LIVE Protect member's 1 does (INV-IV-MISSING)."""
    _set(rig, {FAM_F: 3, FAM_P: 1}, {FAM_F: "on", FAM_P: "on"})
    rig.views[FAM_F] = "held"
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.bodies_nvr) == (1, 1)


@pytest.mark.asyncio
async def test_named_union_dedups_ble_and_face(rig):
    """Oji BLE in the family room AND a fresh face there: named once (BLE).
    Jaya face-only in the master hallway: named there by face."""
    _set(rig, {FAM_F: 1, FAM_P: 1, MAS_F: 1, MAS_P: 0}, {FAM_F: "on", MAS_F: "on"})
    rig.pc.data = {OJI: _ble("family_room")}
    await R.face(rig, "family_room", "Oji")
    await R.face(rig, "master_hallway", "Jaya")
    rig.producer.interior_tick()
    fam = _rec(rig, "Family Room")
    assert (fam.named, fam.named_sources, fam.status) == (
        (OJI,), ((OJI, "ble"),), "confirmed")
    mas = _rec(rig, "Master Hallway")
    assert (mas.named, mas.named_sources, mas.unnamed) == ((JAYA,), ((JAYA, "face"),), 0)


@pytest.mark.asyncio
async def test_one_placement_per_slug(rig):
    """N5 repro: Ezinne BLE ACTIVE in the family room, her face in the
    master hallway 200 s ago, one guest in the master hallway -> master
    hallway named {}, unnamed 1 (not 0)."""
    _set(rig, {FAM_F: 1, MAS_F: 1}, {FAM_F: "on", MAS_F: "on"})
    rig.pc.data = {EZ: _ble("family_room")}
    await R.face(rig, "master_hallway", "Ezinne")
    rig.producer.interior_tick(now=time.time() + 200)
    mas = _rec(rig, "Master Hallway")
    assert (mas.named, mas.unnamed, mas.status) == ((), 1, "unnamed_present")
    assert _rec(rig, "Family Room").named == (EZ,)


@pytest.mark.asyncio
async def test_face_older_than_fresh_window_not_named(rig):
    """Boundary on INTERIOR_ROOM_FACE_FRESH_S (300): 299 s named, 301 s not."""
    _set(rig, {MAS_F: 1}, {MAS_F: "on"})
    await R.face(rig, "master_hallway", "Jaya")
    ts = rig.hass.states.get(R.FACE["master_hallway"]).last_changed.timestamp()
    rig.producer.interior_tick(now=ts + 299)
    assert _rec(rig, "Master Hallway").named == (JAYA,)
    rig.producer.interior_tick(now=ts + 301)
    assert _rec(rig, "Master Hallway").named == ()


@pytest.mark.asyncio
async def test_stale_resident_does_not_confirm(rig):
    """A STALE resident placed in the room does not confirm (active_only)."""
    _set(rig, {FAM_F: 1}, {FAM_F: "on"})
    rig.pc.data = {EZ: _ble("family_room", status="stale")}
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.named, r.unnamed, r.status) == ((), 1, "unnamed_present")


@pytest.mark.asyncio
async def test_phone_left_behind_person_not_named(rig, monkeypatch):
    """A resident whose phone-left-behind sensor reads on is not named (the
    one BLE-in-room read's filter, registry-resolved)."""
    bc = _mod("domain_coordinators._ble_corroboration")
    uid = f"{R.DOMAIN}_person_{JAYA}_phone_left_behind"
    reg = SimpleNamespace(async_get_entity_id=lambda d, p, u: (
        "binary_sensor.jaya_plb" if u == uid else None))
    monkeypatch.setattr(bc.er, "async_get", lambda hass_: reg)
    rig.hass.states.async_set("binary_sensor.jaya_plb", "on")
    _set(rig, {FAM_F: 1}, {FAM_F: "on"})
    rig.pc.data = {JAYA: _ble("family_room")}
    rig.producer.interior_tick()
    assert (_rec(rig, "Family Room").named, _rec(rig, "Family Room").unnamed) == ((), 1)
    rig.hass.states.async_set("binary_sensor.jaya_plb", "off")
    rig.producer.interior_tick()
    assert _rec(rig, "Family Room").named == (JAYA,)


@pytest.mark.asyncio
async def test_excluded_room_type_no_record(rig, monkeypatch):
    """A bedroom-typed room with a camera gets no record (INV-IV-SCOPE)."""
    ents = R.entries(rig.m) + [
        _room_entry(rig.m, "Family Room", "living_room"),
        _room_entry(rig.m, "Master Hallway", "master_hallway", "bedroom"),
    ]
    R.install_entries(rig.hass, monkeypatch, ents)
    _set(rig, {FAM_F: 1, MAS_F: 2}, {FAM_F: "on", MAS_F: "on"})
    rig.producer.interior_tick()
    assert sorted(r.room for r in rig.producer.get_room_sightings()) == ["Family Room"]
    assert rig.producer.interior_excluded["excluded_room_type"] == 1


@pytest.mark.asyncio
async def test_kill_no_records(mods, hass, monkeypatch):  # noqa: F811
    """INTERIOR_ROOM_RECORDS_ENABLED False: no timer, no listener, no record
    (control: True registers the timer)."""
    r = await R.build(mods, hass, monkeypatch)
    try:
        assert r.producer._interior_timer_unsub is not None
        monkeypatch.setattr(mods.const, "INTERIOR_ROOM_RECORDS_ENABLED", False)
        r.presence._setup_person_sightings()
        p = r.presence._person_sightings
        assert p._interior_timer_unsub is None
        r.census._stream_last_reading = {FAM_F: 2}
        assert p.interior_tick() == ()
        assert p.get_room_sightings() == ()
        assert p.interior_counters["record_builds"] == 0
    finally:
        await R.teardown(r)


@pytest.mark.asyncio
async def test_timer_builds_records_and_teardown_cancels(rig):
    """The producer's own interval timer runs the build; teardown removes it
    (no build after teardown)."""
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util

    _set(rig, {FAM_F: 2}, {FAM_F: "on"})
    assert rig.producer.interior_counters["record_builds"] == 0
    async_fire_time_changed(rig.hass, dt_util.utcnow() + timedelta(seconds=11))
    await rig.hass.async_block_till_done()
    assert rig.producer.interior_counters["record_builds"] >= 1
    assert _rec(rig, "Family Room").bodies == 2
    rig.producer.async_teardown()
    n = rig.producer.interior_counters["record_builds"]
    async_fire_time_changed(rig.hass, dt_util.utcnow() + timedelta(seconds=40))
    await rig.hass.async_block_till_done()
    assert rig.producer.interior_counters["record_builds"] == n


@pytest.mark.asyncio
async def test_record_build_off_inference_path(rig):
    """The build is not reachable from the presence inference / census paths:
    driving a census update and the periodic producer hook runs no build."""
    calls = []
    orig = rig.producer._interior_tick

    def _spy(now):
        calls.append(now)
        return orig(now)

    rig.producer._interior_tick = _spy
    rig.presence._handle_census_update({
        "census_count": 1, "unidentified_count": 0, "face_recognized_count": 0,
        "confidence": "high"})
    rig.producer.on_tick()
    await rig.hass.async_block_till_done()
    assert calls == []
    rig.producer.interior_tick()   # positive control: the spy is live
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_emit_unnamed_sends_no_sighting_signal(rig):
    """`_emit_unnamed` writes the store and sends nothing on
    SIGNAL_PERSON_SIGHTING (operator Q5)."""
    _set(rig, {FAM_F: 2}, {FAM_F: "on"})
    rig.producer.interior_tick()
    await rig.hass.async_block_till_done()
    assert rig.sightings == []
    assert len(rig.producer.get_room_sightings()) == 2
    with pytest.raises(ValueError):
        # Ship 2 made "description" a real kind (D3); any other kind raises.
        rig.producer._emit_unnamed("bogus", {})


@pytest.mark.asyncio
async def test_presence_delegates_and_diagnostics(rig):
    _set(rig, {FAM_F: 2}, {FAM_F: "on"})
    rig.producer.interior_tick()
    recs = rig.presence.get_room_sightings()
    assert {r.room for r in recs} == {"Family Room", "Master Hallway"}
    assert rig.presence.get_last_path_records() == ()
    diag = rig.presence.get_layer_diagnostics()["interior_vision"]
    assert diag["record_builds"] == 1 and diag["groups"] == 2
    assert diag["groups_by_liveness"] == {"live": 1, "no_reading": 1}


def test_area_evidence_copies(mods):  # noqa: F811
    """`area_evidence()` copies the per-entity readings (a later census write
    does not change a returned value) and adds the display fields."""
    census = mods.census.PersonCensus.__new__(mods.census.PersonCensus)
    census._stream_last_reading = {FAM_F: 2}
    census._last_area_contributions = {"living_room": {"max_count": 2, "platform": "frigate"}}
    census._last_house_camera_bodies = 2
    census._last_count_as_of = "2026-11-15T10:00:00+00:00"
    ev = census.area_evidence()
    census._stream_last_reading[FAM_F] = 5
    census._last_area_contributions["living_room"]["max_count"] = 9
    assert ev == {"by_entity": {FAM_F: 2},
                  "area_contributions": {"living_room": {"max_count": 2, "platform": "frigate"}},
                  "house_camera_bodies": 2, "as_of": "2026-11-15T10:00:00+00:00",
                  "discounted": ()}


# ------------------------------------------------------------- D7 trip-wire
@pytest.mark.asyncio
async def test_records_zero_tripwire_fires_at_min_ticks(rig, monkeypatch):
    """Interior bodies on 3 ticks and no record built (registries broken) ->
    one HIGH page; 2 ticks -> none."""
    sent = []

    async def _fake(hass_, **kw):
        sent.append(kw)

    monkeypatch.setattr(sys.modules[f"{PKG}.person_sighting"], "fire_stuck_signal", _fake)
    monkeypatch.setattr(rig.m.const, "INTERIOR_ZERO_MIN_TICKS", 3)

    def _broken():
        raise RuntimeError("no registry")

    rig.producer._interior_registries = _broken
    _set(rig, {FAM_F: 1}, {FAM_F: "on"})
    t0 = time.time()
    rig.producer.interior_tick(now=t0)
    rig.producer.interior_tick(now=t0 + 10)
    await rig.hass.async_block_till_done()
    assert sent == []
    rig.producer.interior_tick(now=t0 + 20)
    await rig.hass.async_block_till_done()
    assert [(s["kind"], s["severity"]) for s in sent] == [("interior_room_records_zero", "HIGH")]
    rig.producer.interior_tick(now=t0 + 30)
    await rig.hass.async_block_till_done()
    assert len(sent) == 1  # latched


@pytest.mark.asyncio
async def test_records_zero_silent_when_records_built(rig, monkeypatch):
    sent = []

    async def _fake(hass_, **kw):
        sent.append(kw)

    monkeypatch.setattr(sys.modules[f"{PKG}.person_sighting"], "fire_stuck_signal", _fake)
    monkeypatch.setattr(rig.m.const, "INTERIOR_ZERO_MIN_TICKS", 3)
    _set(rig, {FAM_F: 1}, {FAM_F: "on"})
    t0 = time.time()
    for i in range(5):
        rig.producer.interior_tick(now=t0 + 10 * i)
    await rig.hass.async_block_till_done()
    assert sent == []


# ------------------------------------------------------------------ D5
def _edge(m, f, t, w, kind="inward"):
    return m.paths.PathEdge(f, t, kind, float(w), f"camera.{f}", f"camera.{t}")


def test_path_windows_cumulative_on_live_chain(mods):  # noqa: F811
    """The live garage_a chain: door -> staircase 63 -> stairs_top 72 ->
    playroom 67 / upstairs_hall 84; staircase -> family_room 85. Entrant at
    staircase E+60, stairs_top E+130, playroom E+195 -> three hops (a per-hop
    `E + window_s` rule would drop playroom: 195 > 67)."""
    iv = _mod("interior_vision")
    edges = [_edge(mods, "door", "staircase", 63), _edge(mods, "staircase", "stairs_top", 72),
             _edge(mods, "stairs_top", "playroom", 67),
             _edge(mods, "stairs_top", "upstairs_hall", 84),
             _edge(mods, "staircase", "family_room", 85)]
    E = 1000.0
    on = {"staircase": [E + 60], "stairs_top": [E + 130], "playroom": [E + 195]}
    w = iv.chain_windows(edges, "door", E, on, 4)
    assert {k: v["first_on"] for k, v in w.items() if v["first_on"]} == {
        "staircase": E + 60, "stairs_top": E + 130, "playroom": E + 195}
    assert (w["playroom"]["open"], w["playroom"]["close"]) == (E + 130, E + 197)
    assert (w["family_room"]["open"], w["family_room"]["close"]) == (E + 60, E + 145)
    assert w["upstairs_hall"]["close"] == E + 214


def test_path_window_from_edge_window_s(mods):  # noqa: F811
    """A hop counts only inside [t_u, t_u + window_s] of its edge (boundary
    literals 63 / 64)."""
    iv = _mod("interior_vision")
    edges = [_edge(mods, "door", "staircase", 63)]
    assert iv.chain_windows(edges, "door", 0.0, {"staircase": [63.0]}, 4)["staircase"]["first_on"] == 63.0
    assert iv.chain_windows(edges, "door", 0.0, {"staircase": [64.0]}, 4)["staircase"]["first_on"] is None
    assert iv.chain_windows(edges, "door", 0.0, {"staircase": [-1.0]}, 4)["staircase"]["first_on"] is None


def test_path_chain_continues_past_missed_camera(mods):  # noqa: F811
    """Staircase missed the entrant: stairs_top's window opens at the
    staircase's cumulative bound E+63 and closes E+135; seen at E+130 ->
    hop. Max hops 1 stops after the first hop."""
    iv = _mod("interior_vision")
    edges = [_edge(mods, "door", "staircase", 63), _edge(mods, "staircase", "stairs_top", 72)]
    w = iv.chain_windows(edges, "door", 0.0, {"stairs_top": [130.0]}, 4)
    assert w["staircase"]["first_on"] is None
    assert (w["stairs_top"]["open"], w["stairs_top"]["close"], w["stairs_top"]["first_on"]) == (
        63.0, 135.0, 130.0)
    assert set(iv.chain_windows(edges, "door", 0.0, {"stairs_top": [130.0]}, 1)) == {"staircase"}


def test_inward_path_edges_excludes_approach(mods):  # noqa: F811
    """The tracker's read returns the door's inward edges only (REAL method
    over a real PathMap); unknown door / no map -> ()."""
    pm = mods.paths
    dm = pm.DoorMap(door="garage_a", edges=[
        _edge(mods, "drive", "door", 20, kind="approach"),
        _edge(mods, "door", "staircase", 63)])
    fake = SimpleNamespace(path_map=pm.PathMap(doors={"garage_a": dm}))
    read = mods.transit.EgressDirectionTracker.inward_path_edges
    got = read(fake, "garage_a")
    assert [(e.from_key, e.to_key, e.kind) for e in got] == [("door", "staircase", "inward")]
    assert read(fake, "front") == ()
    assert read(SimpleNamespace(path_map=None), "garage_a") == ()


class _Tracker:
    def __init__(self, edges, crossings=(), people=None):
        self.edges = edges
        self.crossings = list(crossings)
        self.people = people or {}

    def path_map_status(self):
        return {"path_map_doors": sorted(self.edges)}

    def inward_path_edges(self, door):
        return tuple(self.edges.get(door, ()))

    def get_crossings_since(self, t, camera=None):
        return tuple(sorted((c for c in self.crossings if c.ts >= t), key=lambda c: c.ts))

    def get_crossing(self, ref):
        for c in self.crossings:
            if c.source_ref == ref:
                return SimpleNamespace(people_count=self.people.get(ref))
        return None


def _crossing(m, ts, ref, direction="entry"):
    return m.transit.CrossingRecord(
        camera=R.GARAGE_A_FRIGATE, direction=direction, ts=ts, person_id=None,
        provenance=None, confidence=0.9, identity_confidence=None, source_ref=ref)


class _DB:
    def __init__(self):
        self.rows = []

    async def log_memory_episode(self, **kw):
        self.rows.append(kw)
        return 1


async def _path_rig(rig, extra_edges=()):
    from homeassistant.util import dt as dt_util

    fus = rig.resolver.resolve_operator_declaration([R.GARAGE_A_FRIGATE])
    door_key = rig.m.resolver.canonical_camera_key(fus[0])
    edges = [_edge(rig.m, door_key, FAM_KEY, 63), _edge(rig.m, FAM_KEY, MAS_KEY, 72),
             *extra_edges]
    tracker = _Tracker({"garage_a": edges})
    rig.hass.data[R.DOMAIN]["egress_tracker"] = tracker
    rig.db = _DB()
    rig.hass.data[R.DOMAIN]["database"] = rig.db
    rig.producer.interior_tick()      # builds groups, binds the on-edge listener
    return tracker, dt_util


async def _on(rig, eid):
    rig.hass.states.async_set(eid, "off")
    await rig.hass.async_block_till_done()
    rig.hass.states.async_set(eid, "on")
    await rig.hass.async_block_till_done()
    return rig.hass.states.get(eid).last_changed.timestamp()


@pytest.mark.asyncio
async def test_path_record_hops_rows_and_entered_via_ttl(rig):
    """An entry on the mapped door: family room first on-edge, then master
    hallway -> one path record (two hops, n from the first hop), one
    `interior_path` row; the family room record carries entered_via until
    the seed TTL (600 s after its first on-edge)."""
    tracker, dt_util = await _path_rig(rig)
    _set(rig, {FAM_F: 2, MAS_F: 1}, {})
    E = dt_util.utcnow()
    tracker.crossings.append(_crossing(rig.m, E, "egress:garage:1"))
    t_fam = await _on(rig, FAM_F)
    rig.producer.interior_tick(now=t_fam + 1)
    assert _rec(rig, "Family Room").entered_via == ("garage_a", E.isoformat())
    t_mas = await _on(rig, MAS_F)
    rig.producer.interior_tick(now=t_mas + 1)
    assert rig.producer.get_last_path_records() == ()   # window still open
    close = t_fam + 72 + 15
    rig.producer.interior_tick(now=close + 1)
    await rig.hass.async_block_till_done()
    (p,) = rig.producer.get_last_path_records()
    assert (p.source_ref, p.door, p.n, p.n_source) == ("egress:garage:1", "garage_a", 2, "first_hop")
    assert [(h[0], h[1]) for h in p.hops] == [(FAM_KEY, "Family Room"), (MAS_KEY, "Master Hallway")]
    assert [r["episode_type"] for r in rig.db.rows] == ["interior_path"]
    assert rig.db.rows[0]["source_ref"] == "egress:garage:1"
    rig.producer.interior_tick(now=t_fam + 599)
    assert _rec(rig, "Family Room").entered_via is not None
    rig.producer.interior_tick(now=t_fam + 601)
    assert _rec(rig, "Family Room").entered_via is None


@pytest.mark.asyncio
async def test_no_inward_edges_no_record(rig):
    """An entry on a door with no inward edge from its camera -> no path
    record; an exit never opens one."""
    tracker, dt_util = await _path_rig(rig)
    tracker.edges = {"garage_a": [_edge(rig.m, "other_key", FAM_KEY, 63)]}
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "egress:garage:2"))
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "egress:garage:3", "exit"))
    rig.producer.interior_tick(now=time.time() + 1000)
    assert rig.producer.get_last_path_records() == ()
    assert rig.producer._open_paths == {}
    assert rig.producer.interior_counters["entries_unmapped"] == 1


@pytest.mark.asyncio
async def test_crossing_read_once(rig):
    """A crossing is pulled once (cursor + same-ts dedup)."""
    tracker, dt_util = await _path_rig(rig)
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "egress:garage:4"))
    rig.producer.interior_tick()
    rig.producer.interior_tick()
    assert rig.producer.interior_counters["entries_mapped"] == 1


@pytest.mark.asyncio
async def test_n_source_order(rig, monkeypatch):
    """n: the crossing's people_count attribute, else the arrival record with
    the same source_ref, else the first hop's bodies_nvr."""
    tracker, dt_util = await _path_rig(rig)
    _set(rig, {FAM_F: 3}, {})
    t = dt_util.utcnow()
    tracker.crossings.append(_crossing(rig.m, t, "r1"))
    tracker.people["r1"] = 4
    hops = [(FAM_KEY, "Family Room", 1.0, 3, None)]
    assert rig.producer._path_n("r1", hops) == (4, "crossing")
    tracker.people["r1"] = None
    monkeypatch.setattr(rig.presence, "get_last_arrival_record",
                        lambda: {"source_ref": "r1", "people_count": 5})
    assert rig.producer._path_n("r1", hops) == (5, "arrival_record")
    monkeypatch.setattr(rig.presence, "get_last_arrival_record",
                        lambda: {"source_ref": "other", "people_count": 5})
    assert rig.producer._path_n("r1", hops) == (3, "first_hop")
    assert rig.producer._path_n("r1", []) == (None, None)


@pytest.mark.asyncio
async def test_path_zero_tripwire(rig, monkeypatch):
    """3 entries on mapped doors and no path record -> one LOW page."""
    sent = []

    async def _fake(hass_, **kw):
        sent.append(kw)

    monkeypatch.setattr(sys.modules[f"{PKG}.person_sighting"], "fire_stuck_signal", _fake)
    tracker, dt_util = await _path_rig(rig)
    now = time.time()
    for i in range(3):
        tracker.crossings.append(_crossing(rig.m, dt_util.utcnow() + timedelta(seconds=i), f"z{i}"))
        rig.producer.interior_tick(now=now + i)
        await rig.hass.async_block_till_done()
        if i < 2:
            assert sent == []
    assert [(s["kind"], s["severity"]) for s in sent] == [("interior_path_zero", "LOW")]


def test_no_egress_listener_added():
    """D5 pulls crossings: person_sighting.py's only R10 listener is the
    pre-existing egress listener of `async_setup` (guard scan)."""
    import _layer_guard_engine as E
    hits = [h for h in E.scan_tree(E.load_tree())[0]
            if h.file == "person_sighting.py" and h.rule == "R10"]
    assert sorted({h.symbol for h in hits}) == [
        "PersonSightingProducer.async_setup:ura_person_egress_event"]


# ------------------------------------------------------------ pure core
def test_member_liveness_table(mods):  # noqa: F811
    iv = _mod("interior_vision")
    assert iv.member_liveness(None, "on") == "live"
    assert iv.member_liveness(None, "off") == "live"
    assert iv.member_liveness(None, "unavailable") == "no_reading"
    assert iv.member_liveness(None, "unknown") == "no_reading"
    assert iv.member_liveness(None, None) == "no_reading"
    assert iv.member_liveness("held", "on") == "held"
    assert iv.member_liveness("released", "off") == "released"


def _g(key="k", room="R", members=("a", "b")):
    return {"group_key": key, "room": room, "area_id": None, "members": members,
            "physical_dead": None}


def test_face_only_name_with_no_body_is_empty_not_ble_unconfirmed(mods):  # noqa: F811
    """ble_unconfirmed needs a BLE-named resident; a face-only name with NVR
    0 is `empty`."""
    iv = _mod("interior_vision")
    live = {"a": "live", "b": "live"}
    (r,) = iv.build_room_records([_g()], {"by_entity": {"a": 0}}, live,
                                 {"R": {"jaya": "face"}}, {}, 0.0)
    assert (r["bodies"], r["status"]) == (0, "empty")
    (r,) = iv.build_room_records([_g()], {"by_entity": {"a": 0}}, live,
                                 {"R": {"jaya": "ble"}}, {}, 0.0)
    assert r["status"] == "ble_unconfirmed"


def test_vision_count_replaces_never_adds(mods):  # noqa: F811
    """INV-IV-DEDUP: a valid vision count replaces its group's NVR count
    (NVR 1, vision 3 -> 3, provenance vision; equal -> agree); a group with
    no LIVE member ignores vision (missing stays missing)."""
    iv = _mod("interior_vision")
    live = {"a": "live", "b": "held"}
    (r,) = iv.build_room_records([_g()], {"by_entity": {"a": 1, "b": 2}}, live, {}, {"k": 3}, 0.0)
    assert (r["bodies"], r["bodies_nvr"], r["bodies_vision"], r["provenance"]) == (3, 1, 3, "vision")
    (r,) = iv.build_room_records([_g()], {"by_entity": {"a": 1}}, live, {}, {"k": 1}, 0.0)
    assert r["provenance"] == "agree"
    (r,) = iv.build_room_records([_g()], {"by_entity": {"b": 2}}, {"a": "held", "b": "held"},
                                 {}, {"k": 3}, 0.0)
    assert (r["bodies"], r["status"]) == (None, "missing")


@pytest.mark.asyncio
async def test_vetoed_face_not_named(rig):
    """A face the census would veto (resident reads away) never names."""
    rig.hass.states.async_set("person.jaya", "not_home")
    _set(rig, {MAS_F: 1}, {MAS_F: "on"})
    await R.face(rig, "master_hallway", "Jaya")
    sightings = [s for s in rig.sightings if s.slug == JAYA]
    assert sightings and sightings[-1].census_would_veto is True
    rig.producer.interior_tick()
    assert (_rec(rig, "Master Hallway").named, _rec(rig, "Master Hallway").unnamed) == ((), 1)


# ------------------------------------------------------------ config extremes
@pytest.mark.asyncio
async def test_tripwire_knobs_zero_are_off(rig, monkeypatch):
    """MIN_TICKS 0 and MIN_ENTRIES 0 switch the two trip-wires off, even with
    their conditions met (records broken, open entries)."""
    sent = []

    async def _fake(hass_, **kw):
        sent.append(kw)

    monkeypatch.setattr(sys.modules[f"{PKG}.person_sighting"], "fire_stuck_signal", _fake)
    monkeypatch.setattr(rig.m.const, "INTERIOR_ZERO_MIN_TICKS", 0)
    monkeypatch.setattr(rig.m.const, "INTERIOR_TIMELAPSE_ZERO_MIN_ENTRIES", 0)
    tracker, dt_util = await _path_rig(rig)

    def _broken():
        raise RuntimeError("no registry")

    rig.producer._interior_sig = None
    rig.producer._interior_registries = _broken
    rig.producer._interior_groups = []
    _set(rig, {FAM_F: 1}, {FAM_F: "on"})
    now = time.time()
    for i in range(25):
        if i < 4:
            tracker.crossings.append(_crossing(rig.m, dt_util.utcnow() + timedelta(seconds=i), f"x{i}"))
        rig.producer.interior_tick(now=now + i)
    await rig.hass.async_block_till_done()
    assert sent == []


@pytest.mark.asyncio
async def test_timelapse_extremes_max_hops_zero_and_seed_ttl_zero(rig, monkeypatch):
    """MAX_HOPS 0: an entry on a mapped door still closes a path record, with
    no hop (no window opened); SEED_TTL 0: no `entered_via` survives past the
    hop's first on-edge."""
    monkeypatch.setattr(rig.m.const, "INTERIOR_TIMELAPSE_MAX_HOPS", 0)
    tracker, dt_util = await _path_rig(rig)
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "h0"))
    rig.producer.interior_tick(now=time.time() + 16)
    (p,) = rig.producer.get_last_path_records()
    assert (p.source_ref, p.hops, p.n, p.n_source) == ("h0", (), None, None)
    monkeypatch.setattr(rig.m.const, "INTERIOR_TIMELAPSE_MAX_HOPS", 4)
    monkeypatch.setattr(rig.m.const, "INTERIOR_TIMELAPSE_SEED_TTL_S", 0)
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "h1"))
    t_fam = await _on(rig, FAM_F)
    rig.producer.interior_tick(now=t_fam + 1)
    assert _rec(rig, "Family Room").entered_via is None


@pytest.mark.asyncio
async def test_face_fresh_zero_never_names(rig, monkeypatch):
    monkeypatch.setattr(rig.m.const, "INTERIOR_ROOM_FACE_FRESH_S", 0)
    _set(rig, {MAS_F: 1}, {MAS_F: "on"})
    await R.face(rig, "master_hallway", "Jaya")
    ts = rig.hass.states.get(R.FACE["master_hallway"]).last_changed.timestamp()
    rig.producer.interior_tick(now=ts + 1)
    assert _rec(rig, "Master Hallway").named == ()

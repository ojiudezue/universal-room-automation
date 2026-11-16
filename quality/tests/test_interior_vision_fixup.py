"""VISION-INTERIOR-SIGHTINGS-1 ship 1 fix-up (reviews A, B, C, D/G of
2026-11-15). Same REAL rig as ``test_interior_vision_records.py``; oracles
are literals.
"""
from __future__ import annotations

import sys
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse
from test_interior_vision_records import (  # noqa: F401 — fixture + helpers
    FAM_F, FAM_KEY, FAM_P, JAYA, MAS_F, MAS_KEY, MAS_P, PKG, _DB, _Tracker,
    _crossing, _edge, _mod, _on, _path_rig, _rec, _room_entry, _set, rig,
)

PLAY_F = R.PLAYROOM                                   # Frigate 1239...
PLAY_P = "binary_sensor.playroom_person_detected"     # Protect cdb4...
PLAY_KEY = "12391404210a931c8986b239cbe389ac"
STAIR = "binary_sensor.staircase_person_occupancy"    # zone-only Frigate camera


def _pages(monkeypatch):
    sent = []

    async def _fake(hass_, **kw):
        sent.append(kw)

    monkeypatch.setattr(sys.modules[f"{PKG}.person_sighting"], "fire_stuck_signal", _fake)
    return sent


def _with_playroom(rig, monkeypatch, play_type="common_area"):
    ents = R.entries(rig.m) + [
        _room_entry(rig.m, "Family Room", "living_room"),
        _room_entry(rig.m, "Master Hallway", "master_hallway", "hallway"),
        _room_entry(rig.m, "Playroom", "playroom", play_type),
    ]
    R.install_entries(rig.hass, monkeypatch, ents)
    rig.interior[:] = [FAM_F, FAM_P, MAS_F, MAS_P, PLAY_F, PLAY_P]


def _rooms(rig):
    return sorted(r.room for r in rig.producer.get_room_sightings())


# ============================================================ fix 1: rebuild
@pytest.mark.asyncio
@pytest.mark.parametrize("room_type", ["bedroom", "bathroom"])
async def test_room_type_flip_stops_records_without_restart(rig, monkeypatch, room_type):
    """Flipping Playroom to bedroom / bathroom in its room options stops its
    record on the next tick (no registry event, no restart); flipping back
    restores it (INV-IV-SCOPE)."""
    _with_playroom(rig, monkeypatch)
    _set(rig, {PLAY_F: 1}, {PLAY_F: "on"})
    rig.producer.interior_tick()
    assert "Playroom" in _rooms(rig)
    _with_playroom(rig, monkeypatch, room_type)
    rig.producer.interior_tick()
    assert "Playroom" not in _rooms(rig)
    assert rig.producer.interior_excluded["excluded_room_type"] == 1
    _with_playroom(rig, monkeypatch)
    rig.producer.interior_tick()
    assert "Playroom" in _rooms(rig)


@pytest.mark.asyncio
async def test_room_entry_added_for_an_area_rebuilds(rig, monkeypatch):
    """A new URA room for an area that had none: the next tick records it."""
    rig.interior[:] = [FAM_F, FAM_P, MAS_F, MAS_P, PLAY_F]
    rig.presence._room_area_ids = {k: v for k, v in R.ROOM_AREAS.items() if k != "Playroom"}
    rig.producer.interior_tick()
    assert "Playroom" not in _rooms(rig)
    assert rig.producer.interior_excluded["no_room"] == 1
    rig.presence._room_area_ids = dict(R.ROOM_AREAS)   # presence learns the room
    _with_playroom(rig, monkeypatch)                    # the new room entry
    rig.producer.interior_tick()
    assert "Playroom" in _rooms(rig)


@pytest.mark.asyncio
async def test_rebind_and_resolver_change_force_rebuild(rig):
    """`rebind()` (called on every room-entry lifecycle event) and a new
    resolver object (registry change) each force a group rebuild; an
    unchanged tick does not."""
    p = rig.producer
    p.interior_tick()
    calls = []
    orig = p._bind_onedge_listener

    def _spy():
        calls.append(1)
        return orig()

    p._bind_onedge_listener = _spy
    p.interior_tick()
    assert calls == []
    p.rebind()
    p.interior_tick()
    assert calls == [1]
    rig.mgr.resolver = rig.m.resolver.CameraResolver(rig.er, rig.dr)
    p.interior_tick()
    assert calls == [1, 1]


# ====================================================== fix 2: egress cache
@pytest.mark.asyncio
async def test_failed_egress_key_is_not_cached(rig):
    p = rig.producer
    p._egress_keys.clear()
    good = rig.resolver
    p._bound_resolver = None
    rig.mgr.resolver = None
    assert p._egress_key_resolved(R.GARAGE_A_FRIGATE) is None
    assert R.GARAGE_A_FRIGATE not in p._egress_keys
    assert p._egress_key(R.GARAGE_A_FRIGATE) == R.GARAGE_A_FRIGATE
    rig.mgr.resolver = good
    key = p._egress_key_resolved(R.GARAGE_A_FRIGATE)
    assert key and key != R.GARAGE_A_FRIGATE
    assert p._egress_keys[R.GARAGE_A_FRIGATE] == key


@pytest.mark.asyncio
async def test_unresolved_entry_counts_toward_path_zero(rig, monkeypatch):
    """An entry whose camera key cannot be resolved still counts toward
    `interior_path_zero` (3 entries, no path -> LOW page)."""
    sent = _pages(monkeypatch)
    tracker, dt_util = await _path_rig(rig)
    rig.producer._egress_keys.clear()
    rig.producer._bound_resolver = None
    rig.mgr.resolver = None
    for i in range(3):
        tracker.crossings.append(_crossing(rig.m, dt_util.utcnow() + timedelta(seconds=i), f"u{i}"))
        rig.producer.interior_tick(now=time.time() + i)
    await rig.hass.async_block_till_done()
    assert rig.producer.interior_counters["entries_unresolved"] == 3
    assert [(s["kind"], s["severity"]) for s in sent] == [("interior_path_zero", "LOW")]


# ================================================ fix 3: hop-less path hollow
@pytest.mark.asyncio
async def test_hopless_paths_do_not_discharge_path_zero(rig, monkeypatch):
    """Three mapped entries that each close with NO hop (the hop detector
    is dead): the wire pages; a path WITH a hop discharges and re-arms it."""
    sent = _pages(monkeypatch)
    tracker, dt_util = await _path_rig(rig)
    now = time.time()
    for i in range(3):
        tracker.crossings.append(_crossing(rig.m, dt_util.utcnow() + timedelta(seconds=i), f"h{i}"))
        rig.producer.interior_tick(now=now + i)
    rig.producer.interior_tick(now=now + 1000)        # all three close, hop-less
    await rig.hass.async_block_till_done()
    assert len(rig.producer.get_last_path_records()) == 3
    assert rig.producer.interior_counters["paths_zero_hop"] == 3
    assert [s["kind"] for s in sent] == ["interior_path_zero"]
    assert rig.producer._iv_path_zero_latched is True
    rig.producer._emit_unnamed("path", {"source_ref": "x", "door": "garage_a", "ts": 0.0,
                                        "n": 1, "n_source": "first_hop",
                                        "hops": ((FAM_KEY, "Family Room", 1.0, 1, None),)})
    assert rig.producer._iv_path_zero_latched is False
    rig.producer.interior_tick(now=now + 1001)
    await rig.hass.async_block_till_done()
    assert len(sent) == 1     # a hop record in the window keeps it silent


# ======================================== fix 4: path nodes outside groups
async def _stair_rig(rig):
    """The live garage_a shape: door -> staircase_2 (a zone-only Frigate
    camera, in no interior group) -> family room."""
    from homeassistant.util import dt as dt_util

    door_key = rig.m.resolver.canonical_camera_key(
        rig.resolver.resolve_operator_declaration([R.GARAGE_A_FRIGATE])[0])
    stair_key = rig.m.resolver.canonical_camera_key(
        rig.resolver.resolve_operator_declaration(["camera.staircase_2"])[0])
    pm = rig.m.paths
    edges = [pm.PathEdge(door_key, stair_key, "inward", 63.0, "camera.garage_a_2", "camera.staircase_2"),
             pm.PathEdge(stair_key, FAM_KEY, "inward", 72.0, "camera.staircase_2", "camera.family_room")]
    tracker = _Tracker({"garage_a": edges})
    rig.hass.data[R.DOMAIN]["egress_tracker"] = tracker
    rig.hass.data[R.DOMAIN]["database"] = _DB()
    rig.hass.states.async_set(STAIR, "off")
    await rig.hass.async_block_till_done()
    rig.producer.interior_tick()
    return tracker, dt_util, stair_key


@pytest.mark.asyncio
async def test_path_node_outside_interior_groups_is_listened(rig):
    """D-M1: the staircase camera is no interior group member but is a path
    node: its on-edge is a hop (room None), and the family room after it is
    reached through the staircase's real first-on, so an entrant at the
    family room 50 s after the staircase is recorded."""
    tracker, dt_util, stair_key = await _stair_rig(rig)
    assert STAIR not in rig.census.interior_camera_entities()
    assert rig.producer._onedge_key_by_entity[STAIR] == stair_key
    E = dt_util.utcnow()
    tracker.crossings.append(_crossing(rig.m, E, "s1"))
    t_s = await _on(rig, STAIR)
    t_f = await _on(rig, FAM_F)
    rig.producer.interior_tick(now=t_f + 1)
    rig.producer.interior_tick(now=t_s + 72 + 15 + 1)
    (p,) = rig.producer.get_last_path_records()
    assert [(h[0], h[1]) for h in p.hops] == [(stair_key, None), (FAM_KEY, "Family Room")]


def test_live_chain_repro_records_hops_when_staircase_sees_entrant(mods):  # noqa: F811
    """D-M1 repro, with the staircase now listened: entry E, staircase E+20,
    stairs_top E+50, playroom E+110 -> three hops. Without a staircase
    on-edge the plan's cumulative rule (unchanged, §9.D5) still opens
    stairs_top at E+63 and misses E+50: that residual is stated in the plan."""
    iv = _mod("interior_vision")
    edges = [_edge(mods, "door", "staircase", 63), _edge(mods, "staircase", "stairs_top", 72),
             _edge(mods, "stairs_top", "playroom", 67), _edge(mods, "staircase", "family_room", 85)]
    E = 0.0
    on = {"staircase": [E + 20], "stairs_top": [E + 50], "playroom": [E + 110]}
    got = {k: v["first_on"] for k, v in iv.chain_windows(edges, "door", E, on, 4).items()
           if v["first_on"] is not None}
    assert got == {"staircase": 20.0, "stairs_top": 50.0, "playroom": 110.0}
    on.pop("staircase")
    got = {k for k, v in iv.chain_windows(edges, "door", E, on, 4).items() if v["first_on"]}
    assert got == set()


# ================================================ fix 5: stuck counts
@pytest.mark.asyncio
async def test_census_discounted_member_never_reaches_a_record(rig):
    """D-M3: a stuck Frigate count the census discounts (3) is not live; the
    LIVE Protect twin (1) carries the record; alone it is `missing`/`stuck`."""
    _set(rig, {FAM_F: 3, FAM_P: 1}, {FAM_F: "on", FAM_P: "on"})
    rig.census._watchdog_discounted_cameras = {FAM_F}
    assert rig.census.area_evidence()["discounted"] == (FAM_F,)
    rig.producer.interior_tick()
    assert _rec(rig, "Family Room").bodies == 1
    _set(rig, {FAM_F: 3}, {FAM_P: "unavailable"})
    rig.producer.interior_tick()
    r = _rec(rig, "Family Room")
    assert (r.bodies, r.status, r.liveness) == (None, "missing", "stuck")


@pytest.mark.asyncio
async def test_discounted_member_not_in_records_zero_numerator(rig, monkeypatch):
    sent = _pages(monkeypatch)
    monkeypatch.setattr(rig.m.const, "INTERIOR_ZERO_MIN_TICKS", 2)
    rig.producer._interior_registries = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    rig.census._watchdog_discounted_cameras = {FAM_F}
    _set(rig, {FAM_F: 3}, {FAM_F: "on"})
    for i in range(4):
        rig.producer.interior_tick(now=time.time() + i)
    await rig.hass.async_block_till_done()
    assert sent == [] and len(rig.producer._iv_ticks_with_bodies) == 0


# ================================================ fix 6: fallback n
@pytest.mark.asyncio
async def test_fallback_n_is_window_max_of_first_hop(rig):
    """A M3: census reads 1 at the first build after the hop, 3 at a later
    build inside the hop's window -> n 3 (first_hop); the hop tuple keeps the
    first-on value 1."""
    tracker, dt_util = await _path_rig(rig)
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "m1"))
    _set(rig, {FAM_F: 1}, {})
    t = await _on(rig, FAM_F)
    rig.producer.interior_tick(now=t + 1)
    _set(rig, {FAM_F: 3}, {})
    rig.producer.interior_tick(now=t + 20)
    rig.producer.interior_tick(now=t + 72 + 15 + 1)
    (p,) = rig.producer.get_last_path_records()
    assert (p.n, p.n_source, p.hops[0][3]) == (3, "first_hop", 1)


# ======================================== fix 7: guard (R15 + GE07)
@pytest.mark.parametrize("call", [
    "_p._person_sightings.interior_tick()",
    "_p._person_sightings._emit_unnamed('room', ())",
    "self.hass.data['d']['census'].area_evidence()",
])
def test_guard_pins_producer_entry_points(call):
    import _layer_guard_engine as E
    tree = E.load_tree()
    rel = "domain_coordinators/security.py"
    anchor = '        """Evaluate an entry event against census data."""\n'
    assert tree[rel].count(anchor) == 1
    tree[rel] = tree[rel].replace(anchor, anchor + (
        "        _p = self.hass.data['d']['coordinator_manager'].coordinators['presence']\n"
        f"        _x = {call}\n"), 1)
    hits = [h for h in E.scan_tree(tree)[0] if h.rule == "R15" and h.file == rel]
    assert hits, call


def test_guard_class_prefix_pin_is_class_exact():
    """GE07: the `InteriorAwarenessSensor.*` pin admits that class only; a
    different class in sensor.py (also one whose name shares the prefix)
    calling `get_room_sightings` is an R15 hit."""
    import _layer_guard_engine as E
    assert E.pinned_ok("get_room_sightings", "sensor.py", "InteriorAwarenessSensor._records")
    assert not E.pinned_ok("get_room_sightings", "sensor.py", "OtherSensor._records")
    assert not E.pinned_ok("get_room_sightings", "sensor.py", "InteriorAwarenessSensorX.f")
    tree = E.load_tree()
    tree["sensor.py"] += ("\n\nclass OtherSensor:\n    def f(self, p):\n"
                          "        return p.get_room_sightings()\n")
    hits = [h.symbol for h in E.scan_tree(tree)[0] if h.rule == "R15"]
    assert hits == ["OtherSensor.f:get_room_sightings"]


def test_guard_compare_reports_unpinned_even_if_allowlisted():
    """GE05: an R15 hit is never allowlistable."""
    import _layer_guard_engine as E
    h = E.Hit("R15", "x.py", "f:get_room_sightings", 1, "unpinned_reader")
    probs = E.compare([h], {h.key: {"max": 1}}, {}, None)
    assert any(p.startswith("unpinned reader") for p in probs)


@pytest.mark.parametrize("snippet, rule", [
    # GE11: a store read from another member module is R2.
    ("def f(p):\n    return p._room_sightings\n", "R2"),
])
def test_guard_store_reads(snippet, rule):
    import _layer_guard_engine as E
    tree = E.load_tree()
    tree["probe_iv.py"] = snippet
    assert rule in {h.rule for h in E.scan_tree(tree)[0] if h.file == "probe_iv.py"}


def test_guard_inward_path_edges_is_non_person_public():
    """GE13: the tracker's two path-map reads are non-person (no R2)."""
    import _layer_guard_engine as E
    tree = E.load_tree()
    tree["probe_iv.py"] = ("def f(hass):\n    t = hass.data['d']['egress_tracker']\n"
                           "    return t.inward_path_edges('a'), t.path_door_anchors('a')\n")
    assert [h for h in E.scan_tree(tree)[0] if h.file == "probe_iv.py"] == []


# ===================================================== fix 8: switch text
def test_switch_helper_text_says_no_ai_calls_yet(mods):  # noqa: F811
    import importlib
    sw = importlib.import_module(f"{PKG}.switch")
    text = sw.InteriorVisionSwitch.HELPER_TEXT
    assert "makes no AI calls" in text and "room records" in text


# ======================================================= LOWs (A, D)
@pytest.mark.asyncio
async def test_onedge_requires_off_to_on(rig):
    """A L3 + C PS30-33: only off -> on stamps; on -> on, on -> off,
    unavailable -> on and an add (no old state) do not; an unknown entity
    does not; the stamp is the new state's last_changed."""
    from datetime import datetime, timezone
    rig.producer.interior_tick()
    ring = rig.producer._onedge_ring
    f = rig.producer._on_interior_person_state
    t0 = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)

    def ev(eid, old, new):
        mk = (lambda s: None if s is None else SimpleNamespace(state=s, last_changed=t0))
        return SimpleNamespace(data={"entity_id": eid, "old_state": mk(old), "new_state": mk(new)})

    for old, new in (("on", "on"), ("on", "off"), ("unavailable", "on"), ("unknown", "on"),
                     (None, "on"), ("off", "unavailable")):
        f(ev(FAM_F, old, new))
    f(ev("binary_sensor.not_interior", "off", "on"))
    assert len(ring) == 0
    f(ev(FAM_F, "off", "on"))
    assert ring.by_group_since(0) == {FAM_KEY: [t0.timestamp()]}


@pytest.mark.asyncio
async def test_door_choice_uses_anchors(rig):
    """A L2: an entry opens the door whose ANCHORS hold its key, even when
    another door (sorting first) has an inward edge from that key."""
    tracker, dt_util = await _path_rig(rig)
    door_key = tracker.edges["garage_a"][0].from_key
    tracker.edges["a_first"] = [_edge(rig.m, door_key, MAS_KEY, 30)]
    tracker.anchors = {"garage_a": {door_key}, "a_first": {"other"}}
    tracker.path_door_anchors = lambda d: tracker.anchors.get(d, set())
    rig.producer._interior_sig = None
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "d1"))
    rig.producer.interior_tick()
    assert rig.producer._open_paths["d1"]["door"] == "garage_a"


@pytest.mark.asyncio
async def test_numerator_counted_when_group_build_raises(rig, monkeypatch):
    """A L4: the group build raising every tick still lets the numerator
    count and the HIGH page fire; ticks are counted as tick_errors and the
    tick never raises out (C PS40b)."""
    sent = _pages(monkeypatch)
    monkeypatch.setattr(rig.m.const, "INTERIOR_ZERO_MIN_TICKS", 3)
    csh = _mod("domain_coordinators.camera_stream_health")

    def _boom(*a, **k):
        raise RuntimeError("pairing")

    monkeypatch.setattr(csh, "pure_twin_groups", _boom)
    rig.producer._interior_sig = None
    _set(rig, {FAM_F: 1}, {FAM_F: "on"})
    t0 = time.time()
    for i in range(3):
        rig.producer.interior_tick(now=t0 + i)
    await rig.hass.async_block_till_done()
    assert rig.producer.interior_counters["tick_errors"] == 3
    assert [s["kind"] for s in sent] == ["interior_room_records_zero"]


@pytest.mark.asyncio
async def test_two_groups_one_room_keeps_one(rig, monkeypatch):
    """A L7 / D-L1: a second camera group in the same room is counted
    `groups_sharing_room` and gets no record (no double count)."""
    _with_playroom(rig, monkeypatch)
    rig.m.presence  # noqa: B018
    rig.presence._room_area_ids = dict(R.ROOM_AREAS, **{"Family Room": "living_room"})
    # Re-point the playroom area to the family room's room.
    orig = rig.producer._room_for_area
    rig.producer._room_for_area = lambda a: "Family Room" if a == "playroom" else orig(a)
    rig.producer._interior_sig = None
    rig.producer.interior_tick()
    assert _rooms(rig).count("Family Room") == 1
    assert rig.producer.interior_excluded["groups_sharing_room"] == 1


@pytest.mark.asyncio
async def test_excluded_room_entities_not_in_numerator(rig, monkeypatch):
    """D-L3: an interior camera in a bedroom-typed room seeing bodies does not
    feed the records-zero numerator."""
    sent = _pages(monkeypatch)
    monkeypatch.setattr(rig.m.const, "INTERIOR_ZERO_MIN_TICKS", 2)
    _with_playroom(rig, monkeypatch, "bedroom")
    rig.interior[:] = [PLAY_F]
    _set(rig, {PLAY_F: 2}, {PLAY_F: "on"})
    for i in range(4):
        rig.producer.interior_tick(now=time.time() + i)
    await rig.hass.async_block_till_done()
    assert rig.producer.get_room_sightings() == ()
    # Only the boot tick before the first build can count (no exclusion
    # known yet); never MIN_TICKS of them.
    assert sent == [] and len(rig.producer._iv_ticks_with_bodies) <= 1


# ================================================ C MEDIUM gaps
@pytest.mark.asyncio
async def test_sensor_platform_registers_interior_awareness(mods, hass):  # noqa: F811
    """SE01 wire-in: the sensor platform adds the sensor for the integration
    entry."""
    import importlib

    from homeassistant.helpers import entity_registry as er  # noqa: F401
    sensor = importlib.import_module(f"{PKG}.sensor")
    e = SimpleNamespace(entry_id="integ", data={mods.const.CONF_ENTRY_TYPE: mods.const.ENTRY_TYPE_INTEGRATION},
                        options={})
    added: list = []

    async def _agg(*a, **k):
        return None

    import importlib as _il
    agg = _il.import_module(f"{PKG}.aggregation")
    orig = agg.async_setup_aggregation_sensors
    agg.async_setup_aggregation_sensors = _agg
    try:
        try:
            await sensor.async_setup_entry(hass, e, lambda ents, *a, **k: added.extend(ents))
        except Exception:  # noqa: BLE001 — later platform parts may need more rig
            pass
    finally:
        agg.async_setup_aggregation_sensors = orig
    assert [x.entity_id for x in added if type(x).__name__ == "InteriorAwarenessSensor"] == [
        "sensor.ura_interior_awareness"]


@pytest.mark.asyncio
async def test_teardown_lifecycle(rig):
    """PS15/PS28/PS39/PS76/PS17/PS77/PS18/PS16b: after teardown the tick
    returns the old store and builds nothing, no listener binds, an
    in-flight path-row task is cancelled (and was tracked), open paths are
    cleared, and a second teardown is a no-op."""
    import asyncio
    rig.producer.interior_tick()
    before = rig.producer.get_room_sightings()
    gate = asyncio.Event()

    class _SlowDB:
        async def log_memory_episode(self, **kw):
            await gate.wait()

    rig.hass.data[R.DOMAIN]["database"] = _SlowDB()
    rec = rig.producer._emit_unnamed("path", {"source_ref": "t", "door": "d", "ts": 0.0,
                                              "n": None, "n_source": None, "hops": ()})
    try:
        rig.producer._log_path_row(rec)
        (task,) = list(rig.producer._interior_tasks)
        rig.producer._open_paths["x"] = {}
        rig.producer.async_teardown()
        await asyncio.sleep(0)
        cancelled = task.cancelled()
    finally:
        gate.set()   # never leave a pending task behind (a mutant must fail, not hang)
        await asyncio.sleep(0)
    assert cancelled
    assert rig.producer._interior_tasks == set() and rig.producer._open_paths == {}
    n = rig.producer.interior_counters["record_builds"]
    assert rig.producer.interior_tick() == before
    assert rig.producer.interior_counters["record_builds"] == n
    rig.producer._interior_key_by_entity = {FAM_F: FAM_KEY}
    rig.producer._onedge_key_by_entity = {FAM_F: FAM_KEY}
    rig.producer._bind_onedge_listener()
    assert rig.producer._interior_state_unsub is None
    rig.producer._log_path_row(rec)
    assert rig.producer._interior_tasks == set()
    rig.producer.async_teardown()   # no-op, no raise


@pytest.mark.asyncio
async def test_path_task_tracked_until_done(rig):
    """PS77: the row task is held while pending and discarded when done."""
    tracker, dt_util = await _path_rig(rig)
    rec = rig.producer._emit_unnamed("path", {"source_ref": "k", "door": "d", "ts": 0.0,
                                              "n": None, "n_source": None, "hops": ()})
    rig.producer._log_path_row(rec)
    assert len(rig.producer._interior_tasks) == 1
    await rig.hass.async_block_till_done()
    assert rig.producer._interior_tasks == set()
    assert rig.db.rows[-1]["dedup_source_ref"] is True
    assert rig.db.rows[-1]["window_dedup"] is False


@pytest.mark.asyncio
async def test_rebuild_unsubs_previous_listener(rig):
    """PS29: a group rebuild releases the previous on-edge subscription."""
    rig.producer.interior_tick()
    released = []
    rig.producer._interior_state_unsub = lambda: released.append(1)
    rig.producer._interior_sig = None
    rig.producer.interior_tick()
    assert released == [1] and rig.producer._interior_state_unsub is not None


@pytest.mark.asyncio
async def test_path_close_pad_latest_window_and_single_emit(rig):
    """PS62/PS63/PS64/CO07: a two-hop chain (63, then 72 after the family
    room's first-on) closes at the LATEST window close + pad 15 (literal),
    not before; ticking again emits nothing more and writes one row."""
    tracker, dt_util = await _path_rig(rig)
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "c1"))
    t = await _on(rig, FAM_F)
    rig.producer.interior_tick(now=t)
    close = t + 72
    rig.producer.interior_tick(now=close + 14)
    assert rig.producer.get_last_path_records() == ()
    rig.producer.interior_tick(now=close + 15)
    await rig.hass.async_block_till_done()
    rig.producer.interior_tick(now=close + 30)
    await rig.hass.async_block_till_done()
    assert len(rig.producer.get_last_path_records()) == 1
    assert len(rig.db.rows) == 1


@pytest.mark.asyncio
async def test_path_with_silent_first_camera_records_later_hop(rig):
    """PS68: the family room saw nothing; the master hallway (window from the
    family room's bound 63 to 135) did -> one hop, no tick error."""
    tracker, dt_util = await _path_rig(rig)
    E = dt_util.utcnow()
    tracker.crossings.append(_crossing(rig.m, E, "q1"))
    rig.producer.interior_tick(now=E.timestamp())
    from homeassistant.util import dt as du
    ring = rig.producer._onedge_ring
    ring.append(E.timestamp() + 100, MAS_KEY)
    rig.producer.interior_tick(now=E.timestamp() + 135 + 16)
    (p,) = rig.producer.get_last_path_records()
    assert [h[0] for h in p.hops] == [MAS_KEY]
    assert rig.producer.interior_counters.get("tick_errors", 0) == 0
    assert du is not None


@pytest.mark.asyncio
async def test_same_ts_crossings_on_two_ticks_both_open(rig):
    """PS55: a second entry with the SAME ts arriving on a later tick still
    opens its own path."""
    tracker, dt_util = await _path_rig(rig)
    ts = dt_util.utcnow()
    tracker.crossings.append(_crossing(rig.m, ts, "same1"))
    rig.producer.interior_tick()
    tracker.crossings.append(_crossing(rig.m, ts, "same2"))
    rig.producer.interior_tick()
    assert set(rig.producer._open_paths) == {"same1", "same2"}


@pytest.mark.asyncio
async def test_records_zero_latch_rearm_prune_and_zero_knob(rig, monkeypatch):
    """PS03/PS79/PS80/PS43/PS43b/PS43c/CO10/CO12: fires once at 3 ticks;
    a record discharges; zero readings, an unavailable entity and two
    entities on one tick count right; stamps older than the window prune
    (window 1 h literal); MIN_TICKS 0 is off."""
    sent = _pages(monkeypatch)
    c = rig.m.const
    monkeypatch.setattr(c, "INTERIOR_ZERO_MIN_TICKS", 3)
    monkeypatch.setattr(c, "INTERIOR_ZERO_WINDOW_H", 1)
    p = rig.producer
    good = p._interior_registries
    p._interior_registries = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    p._interior_sig = None
    p._interior_groups = []
    t0 = time.time()
    _set(rig, {FAM_F: 0, MAS_F: 0}, {FAM_F: "on", MAS_F: "on"})
    for i in range(4):
        p.interior_tick(now=t0 + i)
    assert len(p._iv_ticks_with_bodies) == 0                 # readings 0
    _set(rig, {FAM_F: 2}, {FAM_F: "unavailable"})
    p.interior_tick(now=t0 + 5)
    assert len(p._iv_ticks_with_bodies) == 0                 # not LIVE
    _set(rig, {FAM_F: 2, MAS_F: 1}, {FAM_F: "on", MAS_F: "on"})
    p.interior_tick(now=t0 + 6)
    assert len(p._iv_ticks_with_bodies) == 1                 # one per tick
    p.interior_tick(now=t0 + 7)
    p.interior_tick(now=t0 + 8)
    await rig.hass.async_block_till_done()
    assert [s["kind"] for s in sent] == ["interior_room_records_zero"]
    p._interior_registries = good
    p._interior_sig = None
    p.interior_tick(now=t0 + 9)
    assert p._iv_records_zero_latched is False               # discharged
    p._interior_registries = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    p._interior_sig = None
    p._interior_groups = []
    p._iv_records_written.clear()
    p.interior_tick(now=t0 + 3601 + 9)                       # all stamps pruned
    assert len(p._iv_ticks_with_bodies) == 1
    monkeypatch.setattr(c, "INTERIOR_ZERO_MIN_TICKS", 0)
    for i in range(5):
        p.interior_tick(now=t0 + 3620 + i)
    await rig.hass.async_block_till_done()
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_path_zero_latch_set_once(rig, monkeypatch):
    """PS88/PS06/PS87: fires once (latched) for more entries; a hop path in
    the window keeps a later burst silent."""
    sent = _pages(monkeypatch)
    tracker, dt_util = await _path_rig(rig)
    now = time.time()
    for i in range(5):
        tracker.crossings.append(_crossing(rig.m, dt_util.utcnow() + timedelta(seconds=i), f"l{i}"))
        rig.producer.interior_tick(now=now + i)
    await rig.hass.async_block_till_done()
    assert len(sent) == 1


def test_chain_cycle_and_diamond(mods):  # noqa: F811
    """IV31/IV31b/IV33: an edge back to the door never makes the door a hop;
    a node reached at depth 1 keeps that window (not re-opened at depth 2);
    two parents at one depth union their windows."""
    iv = _mod("interior_vision")
    edges = [_edge(mods, "door", "a", 10), _edge(mods, "a", "door", 10),
             _edge(mods, "a", "b", 10), _edge(mods, "door", "b", 50)]
    w = iv.chain_windows(edges, "door", 0.0, {"a": [5.0]}, 4)
    assert "door" not in w
    assert (w["b"]["open"], w["b"]["close"], w["b"]["depth"]) == (0.0, 50.0, 1)
    d = [_edge(mods, "door", "x", 10), _edge(mods, "door", "y", 20),
         _edge(mods, "x", "z", 30), _edge(mods, "y", "z", 5)]
    w = iv.chain_windows(d, "door", 0.0, {"x": [4.0], "y": [15.0]}, 4)
    assert (w["z"]["open"], w["z"]["close"]) == (4.0, 34.0)


@pytest.mark.asyncio
async def test_tick_never_raises(rig, monkeypatch):
    """PS40/PS40b: an exception inside the build does not leave the timer
    callback and is counted."""
    def _boom(now):
        raise RuntimeError("boom")

    monkeypatch.setattr(rig.producer, "_named_by_room", _boom)
    rig.producer._on_interior_interval()
    assert rig.producer.interior_counters["tick_errors"] == 1


@pytest.mark.asyncio
async def test_stream_view_asked_with_census_flag(rig, monkeypatch):
    """PS41: the LIVE filter asks the census view (`census=True`)."""
    csh = _mod("domain_coordinators.camera_stream_health")
    seen = []
    monkeypatch.setattr(csh, "entity_stream_view",
                        lambda h, eid, census=False: seen.append(census) or
                        ("held" if census else None))
    _set(rig, {FAM_F: 2}, {FAM_F: "on"})
    rig.producer.interior_tick()
    assert seen and all(seen)
    assert _rec(rig, "Family Room").status == "missing"


def test_newest_face_wins_and_future_face_ignored(mods):  # noqa: F811
    """IV13 / IV12b: two fresh faces of one slug: the NEWEST room wins; a
    face more than 1 s in the future is not placed."""
    iv = _mod("interior_vision")
    got = iv.place_named({}, [("jaya", "A", 100.0), ("jaya", "B", 150.0), ("jaya", "C", 120.0)],
                         200.0, 300.0)
    assert got == {"jaya": ("B", "face")}
    assert iv.place_named({}, [("jaya", "A", 202.0)], 200.0, 300.0) == {}


def test_group_liveness_order_and_census_as_of(mods):  # noqa: F811
    """IV10 / IV24: held beats released beats stuck beats no_reading; the
    record carries the census as_of."""
    iv = _mod("interior_vision")
    assert iv.group_liveness(("a", "b"), {"a": "released", "b": "held"}, None, False) == "held"
    assert iv.group_liveness(("a", "b"), {"a": "no_reading", "b": "stuck"}, None, False) == "stuck"
    assert iv.group_liveness(("a",), {"a": "no_reading"}, True, False) == "lost"
    (r,) = iv.build_room_records([{"group_key": "k", "room": "R", "members": ("a",)}],
                                 {"by_entity": {"a": 1}, "as_of": "T"}, {"a": "live"}, {}, {}, 0.0)
    assert r["census_as_of"] == "T"


def test_ring_bound_and_since_boundary(mods):  # noqa: F811
    """IV35/IV36: an on-edge exactly at `since` is included; the ring keeps
    its last `maxlen`."""
    iv = _mod("interior_vision")
    ring = iv.OnEdgeRing(3)
    for t in (1.0, 2.0, 3.0, 4.0):
        ring.append(t, "k")
    assert len(ring) == 3 and ring.by_group_since(2.0) == {"k": [2.0, 3.0, 4.0]}


@pytest.mark.asyncio
async def test_group_build_edge_cases(rig):
    """PS27 / PS25 / PS96: no camera device -> excluded; a group with no
    Frigate member still records (no_still_source counted)."""
    rig.interior[:] = [FAM_F, FAM_P, MAS_F, MAS_P, "binary_sensor.not_a_camera"]
    rig.producer._interior_sig = None
    rig.producer.interior_tick()
    assert rig.producer.interior_excluded["no_camera_device"] == 1
    rig.interior[:] = [FAM_P]
    rig.producer._interior_sig = None
    _set(rig, {FAM_P: 1}, {FAM_P: "on"})
    rig.producer.interior_tick()
    assert _rec(rig, "Family Room").bodies == 1
    diag = rig.presence.get_layer_diagnostics()["interior_vision"]
    assert "no_camera_device" not in diag["groups_excluded_by_reason"]


@pytest.mark.asyncio
async def test_physical_dead_not_asked_with_live_member(rig, monkeypatch):
    """PS42: `physical_camera_dead` is consulted only for a group with no LIVE
    member."""
    cth = _mod("domain_coordinators.camera_twin_health")
    asked = []
    monkeypatch.setattr(cth, "physical_camera_dead", lambda h, k: asked.append(k) or False)
    _set(rig, {FAM_F: 1, MAS_F: 1}, {FAM_F: "on", MAS_F: "on"})
    rig.producer.interior_tick()
    assert asked == []


def test_bodies_at_and_bool_people_count(mods):  # noqa: F811
    """PS70/PS70b/PS74: reading exactly at ts is used; after the newest
    sample the last sample; a bool people_count is not n."""
    p = mods.sighting.PersonSightingProducer.__new__(mods.sighting.PersonSightingProducer)
    from collections import deque
    p._bodies_hist = {"k": deque([(10.0, 1), (20.0, 2)])}
    assert p._bodies_at("k", 10.0) == 1 and p._bodies_at("k", 25.0) == 2
    assert p._bodies_max("k", 10.0, 20.0) == 2 and p._bodies_max("k", 30.0, 40.0) is None
    p._presence = SimpleNamespace(get_crossing=lambda r: SimpleNamespace(people_count=True),
                                  get_last_arrival_record=lambda: None)
    assert p._path_n("r", [], None) == (None, None)


def test_area_evidence_never_raises(mods):  # noqa: F811
    """CC06."""
    census = mods.census.PersonCensus.__new__(mods.census.PersonCensus)

    class _Bad(dict):
        def items(self):
            raise RuntimeError("x")

    census._stream_last_reading = {}
    census._last_area_contributions = _Bad(x={})
    assert census.area_evidence() == {"by_entity": {}, "area_contributions": {},
                                      "house_camera_bodies": None, "as_of": None,
                                      "discounted": ()}


def test_persons_in_room_never_raises(mods, hass):  # noqa: F811
    """PCO04."""
    import importlib
    cls = importlib.import_module(f"{PKG}.person_coordinator").PersonTrackingCoordinator
    def _raise(r):
        raise RuntimeError("x")

    fake = SimpleNamespace(hass=hass, data={}, get_room_occupants=_raise)
    assert cls.persons_in_room(fake, "Family Room") == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("entries, expect", [
    ("room_entry_only", True),          # SW04: a room entry's key is ignored
    ("options_over_data", False),       # SW05
    ("none", True),                     # SW06
])
async def test_switch_default_source(mods, hass, monkeypatch, entries, expect):  # noqa: F811
    import importlib
    sw_mod = importlib.import_module(f"{PKG}.switch")
    C = mods.const
    room = SimpleNamespace(entry_id="r", data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_ROOM,
                                               C.CONF_INTERIOR_VISION_ENABLED: False}, options={})
    integ = SimpleNamespace(entry_id="i", data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION,
                                                C.CONF_INTERIOR_VISION_ENABLED: True},
                            options={C.CONF_INTERIOR_VISION_ENABLED: False})
    ents = {"room_entry_only": [room], "options_over_data": [room, integ], "none": []}[entries]
    monkeypatch.setattr(hass.config_entries, "async_entries", lambda d=None, *a, **k: list(ents))
    hass.data.setdefault(C.DOMAIN, {}).pop(C.INTERIOR_VISION_SWITCH_HASS_KEY, None)
    sw = sw_mod.InteriorVisionSwitch(hass, SimpleNamespace(entry_id="cm"))
    assert sw.is_on is expect
    from homeassistant.helpers.entity import EntityCategory
    assert sw.entity_category == EntityCategory.CONFIG


def test_interior_path_episode_registrations(mods):  # noqa: F811
    """CO15/CO17/CO18 and the path ring const (CO08)."""
    C = mods.const
    assert "interior_path" in C.MEMORY_EPISODE_TYPES
    assert "interior_path" in C.MEMORY_WRITER_BACKED_EPISODE_TYPES
    assert "interior_path" in C.MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT_TYPES
    assert C.INTERIOR_VISION_EXCLUDED_ROOM_TYPES == frozenset({"bedroom", "bathroom"})


@pytest.mark.asyncio
async def test_path_ring_bound(rig, monkeypatch):
    """CO08: the closed-path ring keeps INTERIOR_TIMELAPSE_RING (20)."""
    for i in range(21):
        rig.producer._emit_unnamed("path", {"source_ref": str(i), "door": "d", "ts": 0.0,
                                            "n": None, "n_source": None, "hops": ()})
    recs = rig.producer.get_last_path_records()
    assert len(recs) == 20 and recs[0].source_ref == "1"


@pytest.mark.asyncio
async def test_timer_period_is_the_record_interval(mods, hass, monkeypatch):  # noqa: F811
    """PS13: the timer runs at INTERIOR_ROOM_RECORD_INTERVAL_S (10 s)."""
    import homeassistant.helpers.event as ev
    seen = []
    orig = ev.async_track_time_interval
    monkeypatch.setattr(ev, "async_track_time_interval",
                        lambda h, cb, period, *a, **k: seen.append(period) or orig(h, cb, period, *a, **k))
    r = await R.build(mods, hass, monkeypatch)
    try:
        assert timedelta(seconds=10) in seen
    finally:
        await R.teardown(r)


def test_sensor_attrs_and_never_raises(mods):  # noqa: F811
    """SE06/SE08/SE09."""
    import importlib
    sensor = importlib.import_module(f"{PKG}.sensor")
    sig = mods.sighting
    rec = sig.RoomSighting(room="R", area_id=None, group_key="k", bodies=2, bodies_nvr=2,
                           bodies_vision=None, bodies_source="nvr", named=("a", "b"),
                           named_sources=(), unnamed=0, status="confirmed", provenance="nvr",
                           liveness="live", entered_via=None, census_as_of=None, as_of=0.0)

    def _boom():
        raise RuntimeError("x")

    for presence in (SimpleNamespace(get_room_sightings=lambda: (rec,),
                                     get_last_path_records=lambda: ()),
                     SimpleNamespace(get_room_sightings=_boom, get_last_path_records=_boom)):
        h = SimpleNamespace(data={mods.const.DOMAIN: {"coordinator_manager": SimpleNamespace(
            coordinators={"presence": presence})}})
        s = sensor.InteriorAwarenessSensor(h, SimpleNamespace(entry_id="i"))
        attrs = s.extra_state_attributes
        if presence.get_room_sightings is not _boom:
            assert attrs["rooms"]["R"]["named_count"] == 2
            assert attrs["records_as_of"] == "1970-01-01T00:00:00+00:00"
            assert s.native_value == 0
        else:
            assert s.native_value is None and attrs["rooms"] == {}


# ------------------------------------------- re-run GREEN rows (review C)
@pytest.mark.asyncio
async def test_switch_default_reads_data_when_no_option(mods, hass, monkeypatch):  # noqa: F811
    """SW05: the default merges data and options (data False, no option -> off)."""
    import importlib
    sw_mod = importlib.import_module(f"{PKG}.switch")
    C = mods.const
    integ = SimpleNamespace(entry_id="i", data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION,
                                                C.CONF_INTERIOR_VISION_ENABLED: False}, options={})
    monkeypatch.setattr(hass.config_entries, "async_entries", lambda d=None, *a, **k: [integ])
    hass.data.setdefault(C.DOMAIN, {}).pop(C.INTERIOR_VISION_SWITCH_HASS_KEY, None)
    assert sw_mod.InteriorVisionSwitch(hass, SimpleNamespace(entry_id="cm")).is_on is False


def test_knob_values_pinned(mods):  # noqa: F811
    """CO05/CO10/CO12: shipped trip-wire / ring values (literals)."""
    C = mods.const
    assert (C.INTERIOR_ZERO_MIN_TICKS, C.INTERIOR_ZERO_WINDOW_H, C.INTERIOR_ONEDGE_RING_MAX) == (20, 24, 512)


@pytest.mark.asyncio
async def test_onedge_ring_uses_ring_max(rig):
    assert rig.producer._onedge_ring._ring.maxlen == 512


@pytest.mark.asyncio
async def test_diag_counters_and_teardown_refs(rig):
    """PS05/PS94/PS16b."""
    rig.interior[:] = [FAM_F, FAM_P, MAS_F, MAS_P, "binary_sensor.not_a_camera"]
    rig.producer.interior_tick()
    rig.producer._emit_unnamed("path", {"source_ref": "z", "door": "d", "ts": 0.0,
                                        "n": None, "n_source": None, "hops": ()})
    d = rig.producer.interior_diagnostics()
    assert d["path_records"] == 1
    assert d["groups_excluded_by_reason"] == {"no_camera_device": 1}
    rig.producer.async_teardown()
    assert rig.producer._interior_timer_unsub is None
    assert rig.producer._interior_state_unsub is None


@pytest.mark.asyncio
async def test_bodies_history_length(rig, monkeypatch):
    """PS50b/PS50c: history = (MAX_HOPS x 180 + 15) / 10 + 2 = 75 builds, and it
    is re-sized when MAX_HOPS changes (1 hop -> 21)."""
    rig.producer.interior_tick()
    assert rig.producer._bodies_hist[FAM_KEY].maxlen == 75
    monkeypatch.setattr(rig.m.const, "INTERIOR_TIMELAPSE_MAX_HOPS", 1)
    rig.producer.interior_tick()
    assert rig.producer._bodies_hist[FAM_KEY].maxlen == 21


@pytest.mark.asyncio
async def test_crossing_at_cursor_read_once(rig):
    """PS55: a crossing exactly at the cursor is read once over two ticks."""
    tracker, dt_util = await _path_rig(rig)
    tracker.crossings.append(_crossing(rig.m, rig.producer._crossing_cursor, "cur"))
    rig.producer.interior_tick()
    rig.producer.interior_tick()
    assert rig.producer.interior_counters["entries_mapped"] == 1


@pytest.mark.asyncio
async def test_no_still_source_group_still_recorded(rig, monkeypatch):
    """PS96."""
    csh = _mod("domain_coordinators.camera_stream_health")
    monkeypatch.setattr(csh, "frigate_member", lambda er, g: None)
    rig.producer._interior_sig = None
    _set(rig, {FAM_F: 1}, {FAM_F: "on"})
    rig.producer.interior_tick()
    assert _rec(rig, "Family Room").bodies == 1
    assert rig.producer.interior_excluded["no_still_source"] == 2


@pytest.mark.asyncio
async def test_entry_on_two_doors_opens_one_path(rig):
    """PS59: an entry whose key anchors two mapped doors opens ONE path
    (first sorted door) and counts once."""
    tracker, dt_util = await _path_rig(rig)
    door_key = tracker.edges["garage_a"][0].from_key
    tracker.edges["b_door"] = [_edge(rig.m, door_key, MAS_KEY, 30)]
    tracker.path_door_anchors = lambda d: {door_key}
    tracker.crossings.append(_crossing(rig.m, dt_util.utcnow(), "two"))
    rig.producer.interior_tick()
    assert rig.producer.interior_counters["entries_mapped"] == 1
    assert rig.producer._open_paths["two"]["door"] == "b_door"


def test_path_door_anchors_real_method(mods):  # noqa: F811
    pm = mods.paths
    dm = pm.DoorMap(door="garage_a", edges=[], anchors=frozenset({"k1"}))
    fake = SimpleNamespace(path_map=pm.PathMap(doors={"garage_a": dm}))
    read = mods.transit.EgressDirectionTracker.path_door_anchors
    assert read(fake, "garage_a") == frozenset({"k1"})
    assert read(fake, "x") == frozenset()


def test_guard_private_store_read_is_r2_not_r1():
    """GE11."""
    import _layer_guard_engine as E
    tree = E.load_tree()
    tree["probe_iv.py"] = "def f(p):\n    return p._room_sightings, p._path_records\n"
    rules = {h.rule for h in E.scan_tree(tree)[0] if h.file == "probe_iv.py"}
    assert rules == {"R2"}


def test_guard_presence_read_list_has_interior_reads():
    """GE12: a pinned sensor method calling the presence reads through a
    presence-bound receiver is clean (on the read list, pinned)."""
    import _layer_guard_engine as E
    tree = E.load_tree()
    anchor = "    def _records(self) -> tuple:\n"
    assert tree["sensor.py"].count(anchor) == 1
    tree["sensor.py"] = tree["sensor.py"].replace(anchor, (
        "    def _probe(self, manager):\n"
        "        p = manager.coordinators['presence']\n"
        "        return p.get_room_sightings(), p.get_last_path_records()\n\n" + anchor), 1)
    hits = [h for h in E.scan_tree(tree)[0] if h.file == "sensor.py" and "_probe" in h.symbol]
    assert hits == []


@pytest.mark.asyncio
async def test_group_area_from_first_member_with_one(rig, monkeypatch):
    """PS26: the group's area is the first member (sorted) that has one."""
    sig = sys.modules[f"{PKG}.person_sighting"]
    areas = {FAM_F: "living_room", FAM_P: None}   # interior order: FAM_F first
    orig = sig.resolve_area_id_for_entity
    monkeypatch.setattr(sig, "resolve_area_id_for_entity",
                        lambda er, dr, eid: areas[eid] if eid in areas else orig(er, dr, eid))
    rig.producer._interior_sig = None
    rig.producer.interior_tick()
    assert "Family Room" in [r.room for r in rig.producer.get_room_sightings()]


@pytest.mark.asyncio
async def test_non_interior_face_never_names(rig):
    """PS36: an egress (door) sighting carrying a room is not a named face."""
    _set(rig, {MAS_F: 1}, {MAS_F: "on"})
    s = rig.m.sighting.PersonSighting(
        person_entity="person.jaya", slug=JAYA, face_name=None, camera="c", physical_camera="k",
        person_state_at_emit="home", census_would_veto=False, area_id=None,
        room="Master Hallway", house_zones=(), ts=time.time(), confidence=0.6,
        provenance="face", sighting_source="egress_entry", identity_role="attached",
        synthetic=False, person_edge_age_s=None)
    rig.producer._last_sightings["person.jaya"] = s
    rig.producer.interior_tick()
    assert _rec(rig, "Master Hallway").named == ()


@pytest.mark.asyncio
async def test_ble_slug_in_two_rooms_first_sorted_wins(rig):
    """PS37: one placement; the first room in sorted order is kept."""
    rig.pc.persons_in_room = lambda room, active_only=False: (
        ("ezinne",) if room in ("Family Room", "Master Hallway") else ())
    _set(rig, {FAM_F: 1, MAS_F: 1}, {FAM_F: "on", MAS_F: "on"})
    rig.producer.interior_tick()
    assert (_rec(rig, "Family Room").named, _rec(rig, "Master Hallway").named) == (("ezinne",), ())

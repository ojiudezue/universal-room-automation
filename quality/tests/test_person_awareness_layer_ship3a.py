"""Person-awareness layer ship 3a, phase 1 (PLANNING_person_awareness_layer_ship3.md
rev 3.2 §5 D1, D3, D4 less the census view, D5).

INV-3A-NOOP: every migrated send keeps its payload (dict equality AND key
order), its count and its order; the exit-backfill display is unchanged.

REAL Home Assistant core (phcc) and the REAL URA modules, imported fresh by
the shared sighting rig (scoped, restored at module end). Every wire-in is
driven through the method that CONTAINS the call (geofence edge handler, the
D2 face rule, the BLE tick, the census face bridge, the exit backfill, the
tracker's crossing resolver). Oracles are hand-written dict literals and
literal numbers, never the imported constants or the code under test.
"""
from __future__ import annotations

import asyncio
import importlib
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

import _sighting_rig as R
from test_interior_paths import tr  # noqa: F401 — fixture reuse (real tracker)
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"
OJI_E = "person.oji_udezue"


# ======================================================================= helpers
class _Capture:
    """A @callback dispatcher target recording every payload, in order."""

    def __init__(self):
        self.payloads: list = []
        self._hass_callback = True

    def __call__(self, payload):
        self.payloads.append(payload)


def _connect(mods, hass, signal):
    cap = _Capture()
    unsub = mods.dispatcher.async_dispatcher_connect(hass, signal, cap)
    return cap, unsub


class _State:
    def __init__(self, entity_id, state, attributes=None, last_changed=None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = dict(attributes or {})
        self.last_changed = last_changed or datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


def _geofence_event(entity_id, old, new):
    return SimpleNamespace(data={
        "entity_id": entity_id,
        "old_state": None if old is None else _State(entity_id, old),
        "new_state": None if new is None else _State(entity_id, new),
    })


def _presence(mods, hass):
    coord = mods.presence.PresenceCoordinator(hass)
    coord.handle_geofence_event = lambda pid, zone: None
    return coord


@pytest_asyncio.fixture
async def face_rig(mods, hass, monkeypatch):
    """The D2 face-rule rig (persons away, so a face is an arrival)."""
    r = await R.build(mods, hass, monkeypatch,
                      persons={p: "not_home" for p in R.TRACKED})
    cap, unsub = _connect(mods, hass, mods.signals.SIGNAL_PERSON_ARRIVING)
    r.unsubs.append(unsub)
    r.arrivals = cap.payloads
    yield r
    await R.teardown(r)


# ---- BLE producer: a REAL PersonTrackingCoordinator on a small fake hass ----
T0 = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)
OJI = "Oji Udezue"
GPS = "device_tracker.oji_phone"
IRK = "device_tracker.private_ble_device_8ce182"
BERM = "device_tracker.oji_bermuda_tracker"
AREA = "sensor.oji_udezue_area"
PROXY = "sensor.bermuda_global_active_proxy_count"


class _St:
    def __init__(self, state, attributes=None, ts=None):
        self.state = state
        self.attributes = attributes or {}
        self.last_changed = ts or T0
        self.last_updated = ts or T0


class _PCHass:
    def __init__(self):
        self.data: dict = {DOMAIN: {}}
        self.m: dict = {}
        self.states = SimpleNamespace(get=self.m.get)
        self.fired: list = []
        self.bus = SimpleNamespace(async_fire=lambda ev, data: self.fired.append((ev, data)))

    def async_create_task(self, coro, *a, **k):
        coro.close()

    def set(self, eid, state, attrs=None):
        self.m[eid] = _St(state, attrs)


class _Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def utcnow(self):
        return self.t


class _Reg:
    def async_get_entity_id(self, domain, platform, unique_id):
        if (domain, platform, unique_id) == (
                "sensor", "bermuda", "BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT"):
            return PROXY
        return None


def _make_pc_env(mods, monkeypatch):
    pc = importlib.import_module(f"{PKG}.person_coordinator")
    hass = _PCHass()
    entry = MagicMock()
    entry.data = {"tracked_persons": [OJI]}
    entry.options = {}
    entry.async_on_unload = lambda cb: None
    import homeassistant.helpers.frame as _frame
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        coord = pc.PersonTrackingCoordinator(hass, entry)
    coord.hass = hass
    coord.data = {}
    coord.integration_entry = entry
    clock = _Clock(T0)
    monkeypatch.setattr(pc, "dt_util", clock)
    monkeypatch.setattr(pc.er, "async_get", lambda _h: _Reg())
    monkeypatch.setattr(pc, "async_track_state_change_event",
                        lambda *a, **k: (lambda: None))

    async def _noop(*_a, **_k):
        return None

    coord._build_scanner_room_map = _noop
    hass.set(GPS, "home", {"source_type": "gps"})
    hass.set(IRK, "not_home", {"source_type": "bluetooth_le"})
    hass.set(BERM, "not_home", {"source_type": "bluetooth_le"})
    hass.set(OJI_E, "home", {"device_trackers": [GPS, IRK, BERM]})
    hass.set(PROXY, "55")
    hass.set(AREA, "unknown")

    async def _area(_name, *_r):
        return AREA

    coord._find_bermuda_area_sensor = _area
    coord._fleet_healthy_since = T0 - timedelta(seconds=10_000)

    async def _conf(*_a, **_k):
        return 0.9

    coord._calculate_confidence = _conf
    sent: list = []
    monkeypatch.setattr(mods.dispatcher, "async_dispatcher_send",
                        lambda h, sig, payload: sent.append((sig, payload)))
    return SimpleNamespace(pc=pc, hass=hass, coord=coord, clock=clock, sent=sent)


@pytest.fixture
def pc_env(mods, monkeypatch):
    return _make_pc_env(mods, monkeypatch)


@pytest_asyncio.fixture
async def site(request, mods, hass, monkeypatch):
    """Indirect param: the F5 producer site under test and its environment."""
    name = request.param
    ns = SimpleNamespace(name=name, rig=None, env=None)
    if name == "ble":
        ns.env = _make_pc_env(mods, monkeypatch)
    elif name == "camera_face":
        r = await R.build(mods, hass, monkeypatch,
                          persons={p: "not_home" for p in R.TRACKED})
        cap, unsub = _connect(mods, hass, mods.signals.SIGNAL_PERSON_ARRIVING)
        r.unsubs.append(unsub)
        r.arrivals = cap.payloads
        ns.rig = r
    yield ns
    if ns.rig is not None:
        await R.teardown(ns.rig)


SITES = ["geofence", "ble", "camera_face"]


async def _ble_away_then_return(env, *, room="Study A"):
    """Overrule holds 20 min (person armed away), then BLE puts Oji in a room:
    the BLE pre-arrival return path (the one BLE F5 producer)."""
    env.coord.data = await env.coord._async_update_data()
    env.clock.t = T0 + timedelta(minutes=20)
    env.coord.data = await env.coord._async_update_data()
    assert env.coord._person_was_away[OJI] is True
    env.coord._resolve_person_room = lambda area: room
    env.hass.set(AREA, "study_a")
    env.clock.t = T0 + timedelta(minutes=20, seconds=30)
    env.coord.data = await env.coord._async_update_data()


# ================================================================== D1: F5 ingest
@pytest.mark.asyncio
@pytest.mark.parametrize("site", SITES, indirect=True)
async def test_dispatch_person_arriving_payload_equal(mods, hass, monkeypatch, site):
    """INV-3A-NOOP: each migrated producer sends exactly today's dict (same
    keys, same key order, same values, `sighting` the same object), once."""
    sig = mods.signals.SIGNAL_PERSON_ARRIVING
    if site.name == "geofence":
        cap, unsub = _connect(mods, hass, sig)
        coord = _presence(mods, hass)
        coord._handle_geofence_change(_geofence_event(OJI_E, "not_home", "home"))
        unsub()
        assert cap.payloads == [{"person_entity": "person.oji_udezue", "source": "geofence"}]
        assert list(cap.payloads[0]) == ["person_entity", "source"]
    elif site.name == "ble":
        env = site.env
        await _ble_away_then_return(env)
        arr = [p for s, p in env.sent if s == "ura_person_arriving"]
        assert arr == [{"person_entity": "person.oji_udezue", "source": "ble"}]
        assert list(arr[0]) == ["person_entity", "source"]
    else:
        rig = site.rig
        monkeypatch.setattr(mods.const, "FACE_ARRIVAL_INTERIOR_ENABLED", True)
        await R.face(rig, "master_hallway", "Oji")
        (a,) = rig.arrivals
        assert list(a) == ["person_entity", "source", "sighting", "zone"]
        assert a["person_entity"] == "person.oji_udezue"
        assert a["source"] == "camera_face"
        assert a["sighting"] is rig.sightings[0]
        assert a["zone"] == "Entertainment"


@pytest.mark.asyncio
async def test_geofence_inference_trigger_order_unchanged(mods, hass):
    """INV-AWAY-LATENCY (D1 part): the direct house-state trigger still runs
    first and once per edge; the F5 send follows it synchronously (no await,
    no new hop); a departure sends no F5."""
    seq: list = []
    coord = mods.presence.PresenceCoordinator(hass)
    coord.handle_geofence_event = lambda pid, zone: seq.append(("trigger", pid, zone))

    def _f5(payload):
        seq.append(("f5", payload["source"]))

    _f5._hass_callback = True
    unsub = mods.dispatcher.async_dispatcher_connect(
        hass, mods.signals.SIGNAL_PERSON_ARRIVING, _f5)
    coord._handle_geofence_change(_geofence_event(OJI_E, "not_home", "home"))
    assert seq == [("trigger", OJI_E, "home"), ("f5", "geofence")]
    coord._handle_geofence_change(_geofence_event(OJI_E, "home", "not_home"))
    unsub()
    assert seq[2:] == [("trigger", OJI_E, "not_home")]


def test_to_signal_omits_unset(mods):
    P = mods.signals.PersonArrivingPayload
    assert P(person_entity="person.a", source="geofence").to_signal() == {
        "person_entity": "person.a", "source": "geofence"}
    assert P(person_entity="person.a", source="ble", zone="Upstairs").to_signal() == {
        "person_entity": "person.a", "source": "ble"}
    s = object()
    assert P(person_entity="person.a", source="camera_face", sighting=s).to_signal() == {
        "person_entity": "person.a", "source": "camera_face", "sighting": s, "zone": ""}
    assert P(person_entity="person.a", source="ble", ts=12.5).to_signal() == {
        "person_entity": "person.a", "source": "ble", "ts": 12.5}
    # from_signal reads ts back (additive), absent -> None.
    assert P.from_signal({"person_entity": "person.a", "source": "ble"}).ts is None
    assert P.from_signal({"person_entity": "person.a", "source": "ble", "ts": 3}).ts == 3


def test_to_signal_sighting_identity(mods):
    """`sighting` is passed through as the same object (never copied)."""
    sighting = SimpleNamespace(house_zones=("Upstairs",), nested={"a": [1]})
    d = mods.signals.PersonArrivingPayload(
        person_entity="person.a", source="camera_face", sighting=sighting,
        zone="Upstairs").to_signal()
    assert d["sighting"] is sighting


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, ""])
async def test_dispatch_rejects_missing_source(mods, hass, source):
    sig = mods.signals
    cap, unsub = _connect(mods, hass, sig.SIGNAL_PERSON_ARRIVING)
    with pytest.raises(ValueError):
        sig.dispatch_person_arriving(
            hass, sig.PersonArrivingPayload(person_entity="person.a", source=source))
    unsub()
    assert cap.payloads == []
    assert sig.layer_counters(hass).f5_sent == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("site", SITES, indirect=True)
async def test_observation_mode_still_suppresses(mods, hass, monkeypatch, site):
    sig = mods.signals.SIGNAL_PERSON_ARRIVING
    if site.name == "geofence":
        cap, unsub = _connect(mods, hass, sig)
        coord = _presence(mods, hass)
        coord.observation_mode = True
        coord._handle_geofence_change(_geofence_event(OJI_E, "not_home", "home"))
        unsub()
        assert cap.payloads == []
        # Control: the same edge with observation mode off does send.
        cap2, unsub2 = _connect(mods, hass, sig)
        coord.observation_mode = False
        coord._handle_geofence_change(_geofence_event(OJI_E, "not_home", "home"))
        unsub2()
        assert len(cap2.payloads) == 1
    elif site.name == "ble":
        env = site.env
        pres = SimpleNamespace(observation_mode=True)
        env.hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
            coordinators={"presence": pres})
        await _ble_away_then_return(env)
        assert [p for s, p in env.sent if s == "ura_person_arriving"] == []
    else:
        rig = site.rig
        monkeypatch.setattr(mods.const, "FACE_ARRIVAL_INTERIOR_ENABLED", True)
        rig.presence.observation_mode = True
        await R.face(rig, "master_hallway", "Oji")
        assert len(rig.sightings) == 1
        assert rig.arrivals == []
        assert dict(rig.producer.skips_by_reason) == {"observation_mode": 1}


@pytest.mark.asyncio
async def test_subscribe_person_arriving_payload(mods, hass):
    sig = mods.signals
    got: list = []
    unsub = sig.subscribe_person_arriving(hass, got.append)
    sig.dispatch_person_arriving(
        hass, sig.PersonArrivingPayload(person_entity="person.a", source="geofence"))
    # Delivered inline (a @callback target), before dispatch returns.
    assert got == [sig.PersonArrivingPayload(person_entity="person.a", source="geofence")]
    unsub()
    sig.dispatch_person_arriving(
        hass, sig.PersonArrivingPayload(person_entity="person.b", source="ble"))
    assert len(got) == 1

    async def _coro(_p):
        return None

    with pytest.raises(ValueError):
        sig.subscribe_person_arriving(hass, _coro)


@pytest.mark.asyncio
async def test_face_latch_register_order_and_unsub(mods, hass):
    sig = mods.signals
    calls: list = []

    def a(*args):
        calls.append(("a", args))

    def b(*args):
        calls.append(("b", args))

    hass.data.setdefault(DOMAIN, {})
    ua = sig.register_face_latch_callback(hass, a)
    ub = sig.register_face_latch_callback(hass, b)
    snap = sig.face_latch_callbacks(hass)
    assert snap == (a, b) and isinstance(snap, tuple)
    # The census bridge calls them in registration order, once each.
    census = mods.census.PersonCensus(hass, R._Mgr(MagicMock()))
    census._frigate_face_named_ring = None
    now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    census._after_face_latch("family_room", frozenset({"family_room"}), "Oji", now)
    assert [c[0] for c in calls] == ["a", "b"]
    assert calls[0][1] == ("family_room", frozenset({"family_room"}), "Oji", now)
    ua()
    assert sig.face_latch_callbacks(hass) == (b,)
    ua()  # idempotent
    ub()
    assert sig.face_latch_callbacks(hass) == ()
    assert sig._LAYER_DOMAIN == mods.const.DOMAIN


@pytest.mark.asyncio
async def test_sighting_producer_registers_and_unregisters_latch(face_rig):
    """Wire-in anchor: the producer's setup registers through the typed
    ingest, a bridge message then reaches it, and teardown unregisters."""
    m = face_rig.m
    p = face_rig.producer
    assert p._bridge_cb in m.signals.face_latch_callbacks(face_rig.hass)
    R.bridge(face_rig, "family_room", "Oji")
    assert [s.sighting_source for s in face_rig.sightings] == ["interior_pick"]
    p.async_teardown()
    assert m.signals.face_latch_callbacks(face_rig.hass) == ()


# ============================================================ D3: F3 ring + G3
NOW = datetime(2026, 11, 14, 18, 0, 0, tzinfo=timezone.utc)
DOORBELL = "binary_sensor.doorbell_lite_person_occupancy_2"
GARAGE = "binary_sensor.garage_a_person_occupancy_2"


def _tracker(mods, hass, *, now=NOW):
    t = mods.transit.EgressDirectionTracker(hass)
    t._ring_clock = lambda: now
    return t


def _rec(mods, cam, ts, *, person=None, n=None):
    return mods.transit.CrossingRecord(
        camera=cam, direction="entry", ts=ts, person_id=person, provenance=None,
        confidence=0.8, identity_confidence=None,
        source_ref=f"egress:{cam}:{ts.isoformat()}" + ("" if n is None else f"#{n}"),
    )


def _amended(mods, hass):
    return _connect(mods, hass, mods.signals.SIGNAL_EGRESS_RECORD_AMENDED)


def test_crossing_ring_age_covers_step7_windows(mods):
    # confirm 900 + pair 120 + follow-up caller delay 600 (step 7 §6.4)
    assert mods.const.EGRESS_CROSSING_RING_MAX_AGE_S >= 900 + 120 + 600


@pytest.mark.asyncio
async def test_ring_prunes_by_count_and_age(mods, hass):
    t = _tracker(mods, hass)
    recs = [_rec(mods, GARAGE, NOW - timedelta(seconds=100 - i), n=i) for i in range(34)]
    for r in recs:
        t._record_crossing(r)
    ring = list(t.get_crossings_since(NOW - timedelta(hours=1), GARAGE))
    assert len(ring) == 32                      # literal per-camera bound
    assert ring == recs[2:]                     # the two oldest dropped
    # Age (literal 1800 s): appended records at the boundary.
    t2 = _tracker(mods, hass)
    old = _rec(mods, DOORBELL, NOW - timedelta(seconds=1801))
    edge = _rec(mods, DOORBELL, NOW - timedelta(seconds=1800))
    t2._record_crossing(old)
    assert t2.get_crossings_since(NOW - timedelta(hours=1)) == ()   # pruned on append
    t2._record_crossing(edge)
    assert t2.get_crossings_since(NOW - timedelta(hours=1)) == (edge,)
    # Read prunes too: one second later the 1800 s record is past the age.
    t2._ring_clock = lambda: NOW + timedelta(seconds=1)
    assert t2.get_crossings_since(NOW - timedelta(hours=1)) == ()
    assert t2.crossing_ring_sizes() == {DOORBELL: 0}


@pytest.mark.asyncio
async def test_get_crossings_since_order(mods, hass):
    t = _tracker(mods, hass)
    a1 = _rec(mods, GARAGE, NOW - timedelta(seconds=50))
    b1 = _rec(mods, DOORBELL, NOW - timedelta(seconds=40))
    a2 = _rec(mods, GARAGE, NOW - timedelta(seconds=30))
    for r in (a1, b1, a2):
        t._record_crossing(r)
    got = t.get_crossings_since(NOW - timedelta(seconds=40))
    assert type(got) is tuple
    assert got == (b1, a2)                      # inclusive (>=), oldest first
    assert t.get_crossings_since(NOW - timedelta(seconds=60)) == (a1, b1, a2)
    assert t.get_crossings_since(NOW - timedelta(seconds=60), GARAGE) == (a1, a2)
    assert t.get_crossings_since(NOW - timedelta(seconds=39)) == (a2,)
    assert t.get_crossing(b1.source_ref) is b1
    assert t.get_crossing("egress:nope") is None


@pytest.mark.asyncio
async def test_resolve_direction_appends_ring(tr, hass, mods):  # noqa: F811
    """Wire-in anchor: the crossing resolver (enclosing method of
    `_record_crossing`) puts the bus-fired crossing into the ring."""
    from homeassistant.util import dt as dt_util
    tr._interior_neighbours_by_group = {"garage_a": ["binary_sensor.staircase_person_occupancy"]}
    tr._interior_entities = ["binary_sensor.staircase_person_occupancy"]
    ts = dt_util.utcnow()
    tr._recent_interior_events = {
        "binary_sensor.staircase_person_occupancy": [ts + timedelta(seconds=5)]}
    await tr._resolve_direction(GARAGE, ts)
    await hass.async_block_till_done()
    (rec,) = tr.get_crossings_since(ts - timedelta(seconds=1))
    assert rec is tr.get_last_crossing(GARAGE)
    assert rec.source_ref == f"egress:{GARAGE}:{ts.isoformat()}"
    # Additive record fields default (no writer in ship 3a).
    assert (rec.identity_role, dict(rec.nameable), rec.pair_state, rec.pair_partner,
            rec.identity_synthetic_corroborated) == (None, {}, None, None, False)


@pytest.mark.asyncio
async def test_ring_amend_does_not_clobber_newer(mods, hass):
    """Step 7 §6.4 worked case: R1 (Oji) then R2 (Jaya) on the doorbell."""
    t = _tracker(mods, hass)
    r1 = _rec(mods, DOORBELL, NOW - timedelta(seconds=40))
    r2 = _rec(mods, DOORBELL, NOW)
    t._record_crossing(r1)
    t._record_crossing(r2)
    cap, unsub = _amended(mods, hass)
    assert t.attach_crossing_attribute(
        r1.source_ref, {"person_id": "oji_udezue", "identity_confidence": 0.75},
        "face+ble_move", camera=DOORBELL, role="arrival_confirmed") is True
    ring = t.get_crossings_since(NOW - timedelta(hours=1), DOORBELL)
    assert (ring[0].person_id, ring[0].identity_confidence, ring[0].provenance) == (
        "oji_udezue", 0.75, "face+ble_move")
    assert ring[1] is r2                         # R2 untouched
    assert t.get_last_crossing(DOORBELL) is r2   # pointer not clobbered
    assert t.get_last_crossing() is r2
    assert t.attach_crossing_attribute(
        r2.source_ref, {"person_id": "jaya_udezue"}, None,
        camera=DOORBELL, role="arrival_confirmed") is True
    new2 = t.get_crossings_since(NOW - timedelta(hours=1), DOORBELL)[1]
    assert new2.person_id == "jaya_udezue" and new2.provenance is None
    assert t.get_last_crossing(DOORBELL) is new2 and t.get_last_crossing() is new2
    assert t.get_crossings_since(NOW - timedelta(hours=1), DOORBELL)[0].person_id == "oji_udezue"
    unsub()
    assert [p["role"] for p in cap.payloads] == ["arrival_confirmed", "arrival_confirmed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["camera", "direction", "ts", "source_ref", "confidence", "bogus"])
async def test_g3_forbidden_keys(mods, hass, key):
    t = _tracker(mods, hass)
    r = _rec(mods, GARAGE, NOW)
    t._record_crossing(r)
    cap, unsub = _amended(mods, hass)
    with pytest.raises(ValueError):
        t.attach_crossing_attribute(r.source_ref, {key: "x"}, None, camera=GARAGE, role="r")
    with pytest.raises(ValueError):
        mods.transit.amend_crossing(hass, r.source_ref, {key: "x"}, None, camera=GARAGE, role="r")
    unsub()
    assert cap.payloads == []
    assert t.get_last_crossing() is r


@pytest.mark.asyncio
async def test_g3_fires_once_found_or_not(mods, hass):
    sig = mods.signals
    t = _tracker(mods, hass)
    r = _rec(mods, GARAGE, NOW)
    t._record_crossing(r)
    cap, unsub = _amended(mods, hass)
    assert t.attach_crossing_attribute(
        r.source_ref, {"pair_state": "pending"}, None, camera=GARAGE, role="pair_resolved",
        row_id=3, payload_extra={"extra": 1}) is True
    assert cap.payloads[-1] == {"role": "pair_resolved", "source_ref": r.source_ref,
                                "row_id": 3, "person_id": None, "egress_camera": GARAGE,
                                "extra": 1}
    assert sig.layer_counters(hass).crossing_record_aged_out == 0
    # Not found (aged out): False, one send, counted.
    assert t.attach_crossing_attribute(
        "egress:gone", {}, None, camera=GARAGE, role="pair_resolved") is False
    assert sig.layer_counters(hass).crossing_record_aged_out == 1
    # No source_ref (exit backfill shape): False, one send, NOT counted.
    assert t.attach_crossing_attribute(
        None, {}, None, camera=None, role="exit_backfilled", row_id=9,
        payload_extra={"person_id": "oji_udezue"}) is False
    assert sig.layer_counters(hass).crossing_record_aged_out == 1
    unsub()
    assert len(cap.payloads) == 3
    assert cap.payloads[2] == {"role": "exit_backfilled", "source_ref": None, "row_id": 9,
                               "person_id": "oji_udezue", "egress_camera": None}
    assert sig.layer_counters(hass).g3_calls == {"pair_resolved": 2, "exit_backfilled": 1}


class _ExitDB:
    """The DAO surface the exit backfill and the two exit displays call."""

    def __init__(self, ts_iso):
        self.row = {"id": 7, "timestamp": ts_iso, "direction": "exit",
                    "person_id": None, "egress_camera": "garage_a"}

    async def find_unnamed_exit_crossings(self, t_lo_iso, t_hi_iso):
        return [] if self.row["person_id"] else [(7, self.row["timestamp"], "garage_a")]

    async def backfill_entry_exit_person_id(self, row_id, person_id, confidence):
        if row_id == 7 and self.row["person_id"] is None:
            self.row["person_id"] = person_id
            return True
        return False

    async def get_entry_exit_events_since(self, since, direction=None):
        return [dict(self.row)]


async def _exit_displays(mods, hass, monkeypatch):
    sensor = importlib.import_module(f"{PKG}.sensor")
    agg = importlib.import_module(f"{PKG}.aggregation")

    async def _noop(self):
        return None

    monkeypatch.setattr(agg.AggregationEntity, "async_added_to_hass", _noop)
    unsubs: list = []
    exited = object.__new__(sensor.PersonsExitedTodaySensor)
    exited.hass = hass
    exited._count, exited._entries, exited._last_reset, exited._restoring = 0, [], None, False
    last = object.__new__(sensor.LastPersonExitSensor)
    last.hass = hass
    last._last_exit = last._last_person_id = last._last_egress_camera = None
    for s in (exited, last):
        s.async_on_remove = unsubs.append
        s.async_write_ha_state = lambda: None
        s.async_schedule_update_ha_state = lambda *a, **k: None
        await s.async_added_to_hass()
    return exited, last, unsubs


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["tracker", "no_tracker", "no_presence"])
async def test_exit_backfill_display_equal(mods, hass, monkeypatch, case):
    """INV-3A-NOOP named exception: the backfill notice travels on
    SIGNAL_EGRESS_RECORD_AMENDED (superset payload) and both exit displays
    end exactly where the retired signal left them."""
    from homeassistant.util import dt as dt_util
    c = mods.const
    R.install_entries(hass, monkeypatch, [SimpleNamespace(
        entry_id="integ", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION}, options={})])
    cross = dt_util.utcnow().replace(microsecond=0)
    ts_iso = cross.replace(tzinfo=None).isoformat()
    db = _ExitDB(ts_iso)
    hass.data[DOMAIN] = {"database": db}
    if case in ("tracker", "no_presence"):
        hass.data[DOMAIN]["egress_tracker"] = _tracker(mods, hass)
    if case in ("tracker", "no_tracker"):
        hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
            coordinators={"presence": _presence(mods, hass)})
    exited, last, unsubs = await _exit_displays(mods, hass, monkeypatch)
    last._handle_egress_event(SimpleNamespace(data={
        "direction": "exit", "timestamp": cross.isoformat(), "person_id": None,
        "egress_camera": "garage_a"}))
    assert last.extra_state_attributes["person_id"] == "unidentified"
    cap, unsub = _amended(mods, hass)
    census = mods.census.PersonCensus(hass, R._Mgr(MagicMock()))
    await census._backfill_exit_identity("oji_udezue", cross + timedelta(seconds=60), None)
    await hass.async_block_till_done()
    unsub()
    for u in unsubs:
        u()
    assert cap.payloads == [{"role": "exit_backfilled", "source_ref": None, "row_id": 7,
                             "person_id": "oji_udezue", "egress_camera": None}]
    # Display oracle (hand-written): the row named, both displays follow.
    assert exited._entries == [{"person_id": "oji_udezue", "time": ts_iso,
                                "egress_camera": "garage_a"}]
    assert last.extra_state_attributes == {"person_id": "oji_udezue",
                                           "egress_camera": "garage_a"}


@pytest.mark.asyncio
async def test_exit_backfill_reader_ignores_other_roles(mods, hass, monkeypatch):
    """The two exit displays act on role exit_backfilled only."""
    db = _ExitDB("2026-11-14T12:00:00")
    hass.data[DOMAIN] = {"database": db}
    exited, last, unsubs = await _exit_displays(mods, hass, monkeypatch)
    before = [{"person_id": "unidentified", "time": "2026-11-14T12:00:00",
               "egress_camera": "garage_a"}]
    assert exited._entries == before
    db.row["person_id"] = "oji_udezue"   # named by someone, but no exit_backfilled notice
    mods.transit.amend_crossing(hass, None, {}, None, camera=None, role="pair_resolved")
    await hass.async_block_till_done()
    assert exited._entries == before     # not re-read
    mods.transit.amend_crossing(hass, None, {}, None, camera=None, role="exit_backfilled",
                                row_id=7, payload_extra={"person_id": "oji_udezue"})
    await hass.async_block_till_done()
    for u in unsubs:
        u()
    assert exited._entries[0]["person_id"] == "oji_udezue"


@pytest.mark.asyncio
async def test_exit_backfill_ring_untouched(mods, hass, monkeypatch):
    from homeassistant.util import dt as dt_util
    c = mods.const
    R.install_entries(hass, monkeypatch, [SimpleNamespace(
        entry_id="integ", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION}, options={})])
    cross = dt_util.utcnow().replace(microsecond=0)
    db = _ExitDB(cross.replace(tzinfo=None).isoformat())
    t = _tracker(mods, hass, now=cross)
    rec = _rec(mods, GARAGE, cross)
    t._record_crossing(rec)
    hass.data[DOMAIN] = {"database": db, "egress_tracker": t}
    census = mods.census.PersonCensus(hass, R._Mgr(MagicMock()))
    await census._backfill_exit_identity("oji_udezue", cross + timedelta(seconds=60), None)
    assert db.row["person_id"] == "oji_udezue"
    assert t.get_last_crossing() is rec and t.get_last_crossing(GARAGE) is rec
    assert t.get_crossings_since(cross - timedelta(seconds=1)) == (rec,)
    assert rec.person_id is None


class _FakeEnt:
    def __init__(self, device_id):
        self.device_id = device_id


@pytest.mark.asyncio
async def test_door_camera_device_ids_registry_only(mods, hass, monkeypatch):
    t = _tracker(mods, hass)
    t._egress_entities = [GARAGE, DOORBELL, "binary_sensor.dev_garage_a_person"]
    reg = SimpleNamespace(async_get={GARAGE: _FakeEnt("dev_garage_a"),
                                     DOORBELL: _FakeEnt(None)}.get)
    monkeypatch.setattr(mods.transit.er_helper, "async_get", lambda _h: reg)
    # The third id is not in the registry (its name looks like a device id):
    # nothing is inferred from the string.
    assert t.door_camera_device_ids() == frozenset({"dev_garage_a"})
    p = _presence(mods, hass)
    hass.data.setdefault(DOMAIN, {})["egress_tracker"] = t
    assert p.door_camera_device_ids() == frozenset({"dev_garage_a"})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["lock", "perimeter", "no_presence"])
async def test_door_entry_areas_unchanged(mods, hass, case):
    t = _tracker(mods, hass)
    t._egress_entities = [GARAGE, DOORBELL]
    t._door_group_by_stem = {"garage_a": "garage_a", "doorbell_lite": "garage_a"}
    t._interior_neighbours_by_group = {
        "garage_a": ["binary_sensor.staircase_person_occupancy"],
        "front": ["binary_sensor.foyer_person_occupancy"]}
    areas = {GARAGE: "garage", DOORBELL: "front_porch",
             "binary_sensor.staircase_person_occupancy": "staircase",
             "binary_sensor.foyer_person_occupancy": "foyer"}
    hass.data[DOMAIN] = {"egress_tracker": t}
    if case == "lock":
        hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
            coordinators={"presence": _presence(mods, hass)})
    if case in ("lock", "no_presence"):
        # The lock passes hass.data[DOMAIN]["egress_tracker"]; no presence
        # dependency on the access path.
        got = mods.arrival_edges.door_entry_areas(
            hass.data[DOMAIN]["egress_tracker"], areas.get)
        assert got == {"garage", "front_porch", "staircase", "foyer"}
        assert t.door_entry_entities() == (
            GARAGE, DOORBELL, "binary_sensor.staircase_person_occupancy",
            "binary_sensor.foyer_person_occupancy")
        assert mods.arrival_edges.door_entry_areas(None, areas.get) == set()
        assert mods.arrival_edges.door_entry_areas(SimpleNamespace(), areas.get) == set()
    else:
        pm = object.__new__(mods.perimeter.PerimeterAlertManager)
        pm.hass = hass
        pm._dual_role_cameras = {"camera.garage_a_2"}
        pm._camera_slug_stem = lambda c: "garage_a"
        pm._camera_key_for_sensor = lambda s: "garage_a"
        pm._area_of_entity = {"camera.garage_a_2": "garage",
                              "binary_sensor.staircase_person_occupancy": "staircase"}.get
        assert pm._near_areas("garage_a") == {"garage", "staircase"}
        assert t.door_neighbours_for_stem("garage_a") == (
            "binary_sensor.staircase_person_occupancy",)
        assert t.door_neighbours_for_stem("no_group") == ()


class _Boom:
    def __getattr__(self, name):
        def _raise(*a, **k):
            raise RuntimeError(name)
        return _raise


@pytest.mark.asyncio
async def test_presence_f3_delegates_never_raise(mods, hass):
    p = _presence(mods, hass)
    for tracker in (None, _Boom()):
        hass.data[DOMAIN] = {} if tracker is None else {"egress_tracker": tracker}
        assert p.get_crossings_since(NOW) == ()
        assert p.get_crossing("x") is None
        assert p.door_camera_device_ids() == frozenset()
        assert p.door_entry_entities() == ()
        assert p.door_neighbours_for_stem("garage_a") == ()
    t = _tracker(mods, hass)
    r = _rec(mods, GARAGE, NOW)
    t._record_crossing(r)
    hass.data[DOMAIN] = {"egress_tracker": t}
    assert p.get_crossings_since(NOW) == (r,)
    assert p.get_crossing(r.source_ref) is r


@pytest.mark.asyncio
async def test_crossing_store_failure_counted(tr, hass, mods, monkeypatch):  # noqa: F811
    from homeassistant.util import dt as dt_util

    def _boom(_rec):
        raise RuntimeError("store failed")

    monkeypatch.setattr(tr, "_record_crossing", _boom)
    tr._interior_entities = ["binary_sensor.staircase_person_occupancy"]
    ts = dt_util.utcnow()
    fired = []
    unsub = hass.bus.async_listen("ura_person_egress_event", lambda e: fired.append(e))
    await tr._resolve_direction(GARAGE, ts)
    await hass.async_block_till_done()
    unsub()
    assert len(fired) == 1                       # bus first, still fired
    assert mods.signals.layer_counters(hass).crossing_store_failed == 1


# ============================================== D4: owner setters + move log
@pytest.mark.asyncio
async def test_hvac_toggle_reaches_person_coordinator(mods, pc_env):
    """The HVAC pre-arrival setter writes the person coordinator's flag
    through its owner setter; the flag then gates the BLE F5 send."""
    hvac = importlib.import_module(f"{PKG}.domain_coordinators.hvac")
    env = pc_env
    env.hass.data[DOMAIN]["person_coordinator"] = env.coord
    fake_hvac = SimpleNamespace(hass=env.hass, _pre_arrival_enabled=True)
    setter = hvac.HVACCoordinator.pre_arrival_enabled.fset
    setter(fake_hvac, False)
    assert env.coord._pre_arrival_enabled is False
    await _ble_away_then_return(env)
    assert [p for s, p in env.sent if s == "ura_person_arriving"] == []
    setter(fake_hvac, True)
    assert env.coord._pre_arrival_enabled is True


@pytest.mark.asyncio
async def test_note_face_equal(face_rig):
    """The sighting writes the zone's last-face fields through note_face:
    the same two values as before (slug, the sighting time in UTC)."""
    await R.face(face_rig, "master_hallway", "Oji")
    (s,) = face_rig.sightings
    tr = face_rig.presence._zone_trackers["Master Suite"]
    from homeassistant.util import dt as dt_util
    assert tr._last_face_recognized == "oji_udezue"
    assert tr._last_face_time == dt_util.utc_from_timestamp(s.ts)
    other = face_rig.presence._zone_trackers["Study"]
    assert other._last_face_recognized == "" and other._last_face_time is None


async def _move(env, room, *, at):
    env.coord._resolve_person_room = lambda area: room
    env.hass.set(AREA, room.lower().replace(" ", "_"))
    env.clock.t = at
    env.coord.data = await env.coord._async_update_data()


@pytest.mark.asyncio
async def test_location_moves_since_plain_tuple_inclusive(mods, pc_env):
    env = pc_env
    env.coord._moves_created_at = T0 - timedelta(hours=1)
    await _move(env, "Study A", at=T0)
    assert env.coord.location_moves_since(T0 - timedelta(hours=1)) == ()   # from unknown
    t1 = T0 + timedelta(seconds=30)
    await _move(env, "Kitchen", at=t1)
    t2 = T0 + timedelta(seconds=60)
    await _move(env, "Living Room", at=t2)
    got = env.coord.location_moves_since(t1)
    assert type(got) is tuple
    PM = env.pc.PersonMove
    assert got == (PM("person.oji_udezue", "Study A", "Kitchen", t1, "bermuda"),
                   PM("person.oji_udezue", "Kitchen", "Living Room", t2, "bermuda"))
    assert env.coord.location_moves_since(t1 + timedelta(microseconds=1)) == got[1:]
    with pytest.raises(AttributeError):
        got[0].to_room = "x"  # frozen NamedTuple


@pytest.mark.asyncio
async def test_location_moves_truncated_since(mods, pc_env, monkeypatch):
    env = pc_env
    sig = mods.signals
    monkeypatch.setattr(mods.const, "PERSON_LOCATION_MOVES_MAX", 3)
    c = env.coord
    c._moves_created_at = T0 - timedelta(hours=1)
    env.hass.set("person.oji_udezue", "home")
    # Empty log, t before creation: True (RAM, restart / reload), even not full.
    assert c.location_moves_truncated_since(T0 - timedelta(hours=2)) is True
    for i in range(2):
        c._log_location_move(OJI, f"r{i}", f"r{i+1}", T0 + timedelta(seconds=i))
    assert c.location_moves_truncated_since(T0 + timedelta(seconds=5)) is False   # not full
    # Not full and oldest (T0) newer than t, t after creation: complete -> False.
    assert c.location_moves_truncated_since(T0 - timedelta(seconds=1)) is False
    c._log_location_move(OJI, "r2", "r3", T0 + timedelta(seconds=2))
    c._log_location_move(OJI, "r3", "r4", T0 + timedelta(seconds=3))           # evicts r0
    assert c.location_moves_size() == 3
    assert c.location_moves_truncated_since(T0) is True             # full, oldest (T0+1) > T0
    assert c.location_moves_truncated_since(T0 + timedelta(seconds=1)) is False   # == oldest
    assert c.location_moves_truncated_since(T0 - timedelta(hours=2)) is True      # before creation
    assert sig.layer_counters(env.hass).moves_truncated == 3


@pytest.mark.asyncio
async def test_location_moves_age_pruned(mods, pc_env):
    """Literal 1800 s age bound, applied on read."""
    env = pc_env
    c = env.coord
    c._moves_created_at = T0 - timedelta(hours=2)
    env.hass.set("person.oji_udezue", "home")
    c._log_location_move(OJI, "a", "b", T0 - timedelta(seconds=1801))
    c._log_location_move(OJI, "b", "c", T0 - timedelta(seconds=1800))
    env.clock.t = T0
    got = c.location_moves_since(T0 - timedelta(hours=1))
    assert [(m.from_room, m.to_room) for m in got] == [("b", "c")]


@pytest.mark.asyncio
async def test_location_moves_mirror_bus_event(mods, pc_env):
    env = pc_env
    env.coord._moves_created_at = T0 - timedelta(hours=1)
    await _move(env, "Study A", at=T0)
    await _move(env, "Kitchen", at=T0 + timedelta(seconds=30))
    await _move(env, "Kitchen", at=T0 + timedelta(seconds=60))    # no move: no event, no log
    events = [d for ev, d in env.hass.fired if ev == "ura_person_location_change"]
    moves = env.coord.location_moves_since(T0 - timedelta(hours=1))
    assert [(m.from_room, m.to_room, m.ts) for m in moves] == [
        (d["previous_location"], d["current_location"], d["timestamp"]) for d in events]
    assert len(moves) == 1
    # Unresolved person entity: the event still fires, no move, counted.
    del env.hass.m["person.oji_udezue"]
    env.hass.m["person.oji_udezue_other"] = _St("home")
    env.coord._log_location_move(OJI, "Kitchen", "Den", T0 + timedelta(seconds=90))
    assert env.coord.location_moves_size() == 1
    assert mods.signals.layer_counters(env.hass).move_unresolved_person == 1


@pytest.mark.asyncio
async def test_min_confidence_table(mods, hass):
    p = _presence(mods, hass)
    assert p.min_confidence("security") == 0.9
    assert p.min_confidence("notification") == 0.75
    assert p.min_confidence("display") == 0.0
    assert p.min_confidence("comfort") is None
    assert p.min_confidence("house_state") is None
    assert p.min_confidence("Security") is None
    assert p.min_confidence(None) is None


# ===================================================== D5: layer diagnostics
@pytest.mark.asyncio
async def test_layer_diagnostics_counts(mods, hass):
    sig = mods.signals
    p = _presence(mods, hass)
    hass.data.setdefault(DOMAIN, {})
    base = p.get_layer_diagnostics()
    assert base["f5_sent"] == {} and base["g3_calls"] == {}
    for src in ("geofence", "ble", "camera_face"):
        sig.dispatch_person_arriving(hass, sig.PersonArrivingPayload(
            person_entity="person.a", source=src))
    t = _tracker(mods, hass)
    t._record_crossing(_rec(mods, GARAGE, NOW))
    hass.data[DOMAIN]["egress_tracker"] = t
    mods.transit.amend_crossing(hass, None, {}, None, camera=None, role="exit_backfilled")
    d = p.get_layer_diagnostics()
    assert d["f5_sent"] == {"ble": 1, "camera_face": 1, "geofence": 1}
    assert d["g3_calls"] == {"exit_backfilled": 1}
    assert d["ring_sizes"] == {GARAGE: 1}
    assert d["crossing_record_aged_out"] == 0 and d["crossing_store_failed"] == 0
    assert d["move_log_size"] == 0 and d["move_unresolved_person"] == 0
    # D2 (G1) is not built in ship 3a phase 1: its counters read 0.
    assert d["g1_subscribers"] == 0 and d["edges_truncated"] == 0
    assert d["moves_truncated"] == 0


def _cm_entry(mods, data_extra=None, options=None):
    c = mods.const
    return SimpleNamespace(entry_id="cm", data={
        c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_COORDINATOR_MANAGER, **(data_extra or {})},
        options=dict(options or {}))


@pytest.mark.asyncio
async def test_diagnostics_download_contains_layer(mods, hass):
    diag = importlib.import_module(f"{PKG}.diagnostics")
    p = _presence(mods, hass)
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": p})
    mods.signals.dispatch_person_arriving(hass, mods.signals.PersonArrivingPayload(
        person_entity="person.a", source="geofence"))
    out = await diag.async_get_config_entry_diagnostics(hass, _cm_entry(mods))
    assert list(out) == ["person_awareness_layer"]
    assert out["person_awareness_layer"]["f5_sent"] == {"geofence": 1}
    c = mods.const
    room = SimpleNamespace(entry_id="r", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_ROOM}, options={})
    assert await diag.async_get_config_entry_diagnostics(hass, room) == {}
    zone = SimpleNamespace(entry_id="z", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_ZONE_MANAGER},
                           options={})
    assert await diag.async_get_config_entry_diagnostics(hass, zone) == {}


@pytest.mark.asyncio
async def test_diagnostics_download_has_no_config_entry_data(mods, hass):
    import json
    diag = importlib.import_module(f"{PKG}.diagnostics")
    p = _presence(mods, hass)
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": p})
    entry = _cm_entry(mods, {"api_key_fake": "sk-FAKE-123456"},
                      {"access_token_fake": "tok-FAKE-987654"})
    out = await diag.async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(out, default=str)
    for needle in ("api_key_fake", "sk-FAKE-123456", "access_token_fake",
                   "tok-FAKE-987654", "coordinator_manager", "entry_type"):
        assert needle not in text

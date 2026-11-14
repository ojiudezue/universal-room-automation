"""PHONE-LEFT-BEHIND-CAMERA-LEG-1 (operator ruling A 2026-11-13: display only).

Plan: docs/planning/PLANNING_phone_left_behind_camera_leg.md rev 2.

- D1: `PersonPhoneLeftBehindSensor` publishes the person's last sighting from
  `PresenceCoordinator.get_last_person_sighting` as attributes; `is_on` never
  reads it (INV-1 verdict identity, INV-2 no trust read).
- D2: `PersonLikelyNextRoomSensor` camera attributes read the same store.
- D3: the named branch of `TransitValidator._camera_sightings` is retired;
  `validate_transition` is unchanged for unidentified-only history (INV-3).

REAL production modules (imported fresh inside `_sighting_rig`'s import scope,
so no donor stub leaks in or out). Oracles are hand-derived: the develop
verdict ladder is re-written below from the plan's description of develop
with the legacy camera leg forced None (its value on every live tick).

Accepted limit (review A-L1 / A-L2): that oracle shares the plan's assumption
that the legacy leg is always None. Develop differed only for a camera entity
carrying a `person_id` / `face_id` / `label` attribute equal to the person's
display name with face recognition on (measured 0 of 102 person entities), so
the oracle cannot catch a divergence on that unreachable input.
"""
from __future__ import annotations

import importlib
import itertools
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import _sighting_rig as rig

PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"
OJI = "person.oji_udezue"
NOW_UTC = datetime(2026, 11, 13, 18, 0, 0, tzinfo=timezone.utc)
NOW_TS = NOW_UTC.timestamp()


@pytest.fixture
def m():
    with rig.import_real_modules(purge_tainted=True) as ns:
        ns.bs = importlib.import_module(f"{PKG}.binary_sensor")
        ns.sensor = importlib.import_module(f"{PKG}.sensor")
        ns.pc = importlib.import_module(f"{PKG}.person_coordinator")
        yield ns


# --------------------------------------------------------------- helpers
def _clock(m, monkeypatch, *, hour=12, utc=NOW_UTC, module=None):
    """Pin dt_util in the module under test (scoped by monkeypatch)."""
    real = m.bs.dt_util
    state = {"utc": utc}
    fake = SimpleNamespace(
        now=lambda: datetime(2026, 11, 13, hour, 0, 0),
        utcnow=lambda: state["utc"],
        utc_from_timestamp=real.utc_from_timestamp,
        parse_datetime=real.parse_datetime,
    )
    monkeypatch.setattr(module or m.bs, "dt_util", fake)
    return state


def _sighting(m, *, age_s=60.0, source="interior", veto=False, camera="binary_sensor.family_room_person_occupancy",
              room="Family Room", person=OJI):
    return m.sighting.PersonSighting(
        person_entity=person, slug=person.split(".", 1)[1], face_name="Oji",
        camera=camera, physical_camera="dev_family", person_state_at_emit="home",
        census_would_veto=veto, area_id="living_room", room=room,
        house_zones=("Entertainment",), ts=NOW_TS - age_s, confidence=0.6,
        provenance="face", sighting_source=source, identity_role=None,
        synthetic=False, person_edge_age_s=None,
    )


class _Calls:
    def __init__(self):
        self.n = 0


def _presence(m, sightings: dict, calls: _Calls | None = None):
    """Real `PresenceCoordinator.get_last_person_sighting` over a real
    producer's store."""
    producer = m.sighting.PersonSightingProducer(SimpleNamespace(data={}), None)
    producer._last_sightings.update(sightings)
    holder = SimpleNamespace(_person_sightings=producer)
    real = types.MethodType(m.presence.PresenceCoordinator.get_last_person_sighting, holder)
    if calls is None:
        holder.get_last_person_sighting = real
    else:
        def counted(pe):
            calls.n += 1
            return real(pe)
        holder.get_last_person_sighting = counted
    return holder


def _manager(presence):
    return SimpleNamespace(coordinators={"presence": presence} if presence is not None else {})


def _plb(m, data: dict):
    hass = SimpleNamespace(data={DOMAIN: data})
    return m.bs.PersonPhoneLeftBehindSensor(hass, SimpleNamespace(), "Oji Udezue", OJI)


def _firing_data(m, *, sightings=None, presence=True, tv=True):
    """Every develop gate passes: BLE in an unoccupied room, census 0."""
    d = {
        "person_coordinator": SimpleNamespace(
            data={"Oji Udezue": {"location": "Office"}},
            _is_room_occupied=lambda room: False,
        ),
        "census": SimpleNamespace(last_result=SimpleNamespace(house=SimpleNamespace(total_persons=0))),
    }
    if tv:
        d["transit_validator"] = object()
    if presence:
        d["coordinator_manager"] = _manager(_presence(m, sightings or {}))
    return d


# --------------------------------------------------- independent oracle
def _develop_verdict(*, hour, pc_present, loc, occupied, census, tv_present):
    """Develop's ladder (binary_sensor.py 2098-2201 @ develop) with the
    legacy camera leg = None, written from the plan, not from the code."""
    if hour >= 22 or hour < 7:
        return False
    if not pc_present:
        return None
    if not loc or loc in ("unknown", "away"):
        return False
    if loc not in ("home", "unknown", "away") and occupied:
        return False
    if census is not None and census > 0:
        return False
    if not tv_present:
        return None
    return True


STORES = ("empty", "interior", "egress_entry", "egress_exit", "vetoed", "old23h")


def _store(m, kind):
    if kind == "empty":
        return {}
    if kind == "interior":
        return {OJI: _sighting(m, age_s=60)}
    if kind == "egress_entry":
        return {OJI: _sighting(m, age_s=60, source="egress_entry")}
    if kind == "egress_exit":
        return {OJI: _sighting(m, age_s=60, source="egress_exit")}
    if kind == "vetoed":
        return {OJI: _sighting(m, age_s=60, veto=True)}
    return {OJI: _sighting(m, age_s=23 * 3600)}


# ======================================================== D1 verdict
def test_verdict_identity_cross_product(m, monkeypatch):
    mismatches = []
    for hour, pc_present, loc, occupied, census, store, presence, tv in itertools.product(
        (6, 12, 22), (True, False), (None, "unknown", "away", "home", "Office"),
        (True, False), (None, 0, 2), STORES, (True, False), (True, False),
    ):
        _clock(m, monkeypatch, hour=hour)
        data = {}
        if pc_present:
            pdata = {"location": loc} if loc is not None else {}
            data["person_coordinator"] = SimpleNamespace(
                data={"Oji Udezue": pdata}, _is_room_occupied=lambda r, o=occupied: o,
            )
        if census is not None:
            data["census"] = SimpleNamespace(
                last_result=SimpleNamespace(house=SimpleNamespace(total_persons=census)))
        if tv:
            data["transit_validator"] = object()
        if presence:
            data["coordinator_manager"] = _manager(_presence(m, _store(m, store)))
        got = _plb(m, data).is_on
        want = _develop_verdict(hour=hour, pc_present=pc_present, loc=loc, occupied=occupied,
                                census=census, tv_present=tv)
        if got is not want:
            mismatches.append((hour, pc_present, loc, occupied, census, store, presence, tv, got, want))
    assert not mismatches, mismatches[:10]


def test_fresh_sighting_does_not_change_verdict(m, monkeypatch):
    """INV-2 discriminator: a 1-minute-old interior sighting with every other
    gate firing still reads `on` (rev 1's design read `off` here)."""
    _clock(m, monkeypatch, hour=12)
    assert _plb(m, _firing_data(m, sightings={})).is_on is True
    assert _plb(m, _firing_data(m, sightings={OJI: _sighting(m, age_s=60)})).is_on is True


def test_transit_validator_missing_returns_none(m, monkeypatch):
    _clock(m, monkeypatch, hour=12)
    assert _plb(m, _firing_data(m, tv=False)).is_on is None
    assert _plb(m, _firing_data(m, tv=True)).is_on is True


# ===================================================== D1 attributes
def test_attributes_from_last_sighting(m, monkeypatch):
    _clock(m, monkeypatch)
    s = _sighting(m, age_s=1860)
    attrs = _plb(m, _firing_data(m, sightings={OJI: s})).extra_state_attributes
    assert attrs["camera_leg"] == "display_only"
    assert attrs["last_camera_sighting_at"] == "2026-11-13T17:29:00+00:00"
    assert "hours_since_camera_sighting" not in attrs  # review A-M1: no moving age
    assert attrs["last_sighting_source"] == "interior"
    assert attrs["last_sighting_camera"] == "binary_sensor.family_room_person_occupancy"
    assert attrs["last_sighting_room"] == "Family Room"
    assert attrs["last_sighting_census_veto"] is False
    assert "phone_left_behind_hours" not in attrs


def test_attributes_static_between_polls_no_age(m, monkeypatch):
    """Review A-M1: between sightings the WHOLE attribute dict must not move
    (HA writes a state row on any attribute change). Polls at +30 s, +20 min
    and +3 h after the first read must return an identical dict."""
    clock = _clock(m, monkeypatch)
    sensor = _plb(m, _firing_data(m, sightings={OJI: _sighting(m, age_s=120)}))
    first = sensor.extra_state_attributes
    assert "hours_since_camera_sighting" not in first
    for later_s in (30, 1200, 10800):
        clock["utc"] = NOW_UTC + timedelta(seconds=later_s)
        assert sensor.extra_state_attributes == first, later_s


def test_sighting_at_static_between_polls(m, monkeypatch):
    clock = _clock(m, monkeypatch)
    sensor = _plb(m, _firing_data(m, sightings={OJI: _sighting(m, age_s=120)}))
    first = sensor.extra_state_attributes["last_camera_sighting_at"]
    clock["utc"] = NOW_UTC + timedelta(seconds=30)
    second = sensor.extra_state_attributes["last_camera_sighting_at"]
    assert first == second == "2026-11-13T17:58:00+00:00"


def test_sighting_at_is_recorded(m):
    combined = m.bs.PersonPhoneLeftBehindSensor._Entity__combined_unrecorded_attributes
    assert "last_camera_sighting_at" not in combined


def test_exit_and_vetoed_shown_with_source(m, monkeypatch):
    _clock(m, monkeypatch)
    s = _sighting(m, age_s=60, source="egress_exit", veto=True, camera="binary_sensor.garage_a_person_detected",
                  room=None)
    attrs = _plb(m, _firing_data(m, sightings={OJI: s})).extra_state_attributes
    assert attrs["last_sighting_source"] == "egress_exit"
    assert attrs["last_sighting_census_veto"] is True
    assert attrs["last_sighting_camera"] == "binary_sensor.garage_a_person_detected"


def test_presence_missing_attrs_null(m, monkeypatch):
    _clock(m, monkeypatch)
    attrs = _plb(m, _firing_data(m, presence=False)).extra_state_attributes
    assert attrs["camera_leg"] == "display_only"
    for k in ("last_camera_sighting_at", "last_sighting_source",
              "last_sighting_camera", "last_sighting_room", "last_sighting_census_veto"):
        assert attrs[k] is None, k
    assert "hours_since_camera_sighting" not in attrs


def test_other_persons_sighting_not_shown(m, monkeypatch):
    _clock(m, monkeypatch)
    jaya = _sighting(m, person="person.jaya")
    attrs = _plb(m, _firing_data(m, sightings={"person.jaya": jaya})).extra_state_attributes
    assert attrs["last_camera_sighting_at"] is None


# ============================================ wire-in anchor (D1 key)
@pytest.mark.asyncio
async def test_key_matches_producer_emit(m, monkeypatch):
    """Real `PersonSightingProducer._emit` writes the store; the real sensors
    are built by `async_setup_entry`'s loop from the live config shape
    (entry.data display names, options person ids) and read it back."""
    _clock(m, monkeypatch)
    const = m.const

    async def _no_aggregation(*_a, **_k):
        return None

    agg = importlib.import_module(f"{PKG}.aggregation")
    monkeypatch.setattr(agg, "async_setup_aggregation_binary_sensors", _no_aggregation)

    census = SimpleNamespace(
        _face_suppressed_now=lambda: False,
        _get_tracked_person_slugs=lambda: ["oji_udezue", "jaya"],
        _get_face_name_aliases=lambda: [],
        _canonicalizer_ambiguity_warned=set(),
        face_person_would_be_vetoed=lambda slug: False,
        last_result=None,
    )
    census._face_alias_target = types.MethodType(m.census.PersonCensus._face_alias_target, census)
    census._canonical_person_slug = types.MethodType(m.census.PersonCensus._canonical_person_slug, census)

    shared: dict = {}
    hass = SimpleNamespace(data={DOMAIN: shared}, states=SimpleNamespace(get=lambda eid: None),
                           verify_event_loop_thread=lambda _name: None)
    holder = SimpleNamespace(_face_arrival_cooldown={})
    producer = m.sighting.PersonSightingProducer(hass, holder, now_fn=lambda: NOW_TS)
    holder._person_sightings = producer
    holder.get_last_person_sighting = types.MethodType(
        m.presence.PresenceCoordinator.get_last_person_sighting, holder)
    shared.update({
        "census": census,
        "transit_validator": object(),
        "coordinator_manager": _manager(holder),
    })

    entry = SimpleNamespace(
        entry_id="integration",
        data={const.CONF_ENTRY_TYPE: const.ENTRY_TYPE_INTEGRATION,
              const.CONF_TRACKED_PERSONS: ["Oji Udezue", "Jaya"]},
        options={const.CONF_TRACKED_PERSONS: [OJI, "person.jaya"]},
    )
    added: list = []
    await m.bs.async_setup_entry(hass, entry, lambda ents, *a, **k: added.extend(ents))
    plb = {e._person_id: e for e in added if isinstance(e, m.bs.PersonPhoneLeftBehindSensor)}
    assert set(plb) == {"Oji Udezue", "Jaya"}

    emitted = producer._emit(
        slug="Oji", face_name="Oji", camera="binary_sensor.family_room_person_occupancy",
        physical_camera="dev_family", area_id="living_room", room="Family Room",
        house_zones=("Entertainment",), ts=NOW_TS - 120, confidence=0.6,
        provenance="face", sighting_source="interior", identity_role=None,
        synthetic=False, person_edge_age_s=None, name_is_slug=False,
    )
    assert emitted is not None and emitted.person_entity == OJI

    oji = plb["Oji Udezue"].extra_state_attributes
    assert oji["last_camera_sighting_at"] == "2026-11-13T17:58:00+00:00"
    assert oji["last_sighting_camera"] == "binary_sensor.family_room_person_occupancy"
    assert plb["Jaya"].extra_state_attributes["last_camera_sighting_at"] is None


# ======================================================== D2 NextRoom
def _next_room(m, data):
    hass = SimpleNamespace(data={DOMAIN: data}, states=SimpleNamespace(get=lambda eid: None))
    entry = SimpleNamespace(entry_id="integration", data={}, options={})
    # aggregation.py:388 passes the part after the dot; live entry.data holds
    # display names, so the id here is "Oji Udezue".
    return m.sensor.PersonLikelyNextRoomSensor(hass, entry, "Oji Udezue")


def _with_prediction(data):
    async def _predict(person, room):
        return {"next_room": "Kitchen", "confidence": 0.7, "alternatives": []}

    data["pattern_learner"] = SimpleNamespace(predict_next_room=_predict)
    data["person_coordinator"] = SimpleNamespace(data={"Oji Udezue": {"location": "Office"}})
    return data


@pytest.mark.asyncio
async def test_next_room_camera_attrs_from_sighting(m, monkeypatch):
    _clock(m, monkeypatch, module=m.sensor)
    data = _with_prediction({"coordinator_manager": _manager(_presence(m, {OJI: _sighting(m, age_s=600)}))})
    s = _next_room(m, data)
    await s.async_update()
    attrs = s.extra_state_attributes
    assert attrs["camera_last_seen"] == "2026-11-13T17:50:00+00:00"
    assert attrs["camera_last_room"] == "Family Room"
    assert attrs["transit_camera_validated"] is True


@pytest.mark.asyncio
async def test_next_room_no_prediction_no_fetch(m, monkeypatch):
    _clock(m, monkeypatch, module=m.sensor)
    calls = _Calls()
    data = {"coordinator_manager": _manager(_presence(m, {OJI: _sighting(m)}, calls))}
    s = _next_room(m, data)
    await s.async_update()
    attrs = s.extra_state_attributes
    assert calls.n == 0
    assert "camera_last_seen" not in attrs


@pytest.mark.asyncio
async def test_next_room_window_applied_at_attribute_read(m, monkeypatch):
    """Review B2: a sighting that ages past the 4 h window between updates is
    hidden at the next attribute read, with no new update."""
    clock = _clock(m, monkeypatch, module=m.sensor)
    data = _with_prediction({"coordinator_manager": _manager(_presence(m, {OJI: _sighting(m, age_s=14000)}))})
    s = _next_room(m, data)
    await s.async_update()
    assert s.extra_state_attributes["transit_camera_validated"] is True
    clock["utc"] = NOW_UTC + timedelta(seconds=401)  # age 14401 s > 14400 s
    attrs = s.extra_state_attributes
    assert attrs["transit_camera_validated"] is False
    assert attrs["camera_last_seen"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("age_s, shown", [(14399, True), (14400, True), (14401, False)])
async def test_next_room_sighting_older_than_window_hidden(m, monkeypatch, age_s, shown):
    _clock(m, monkeypatch, module=m.sensor)
    data = _with_prediction({"coordinator_manager": _manager(_presence(m, {OJI: _sighting(m, age_s=age_s)}))})
    s = _next_room(m, data)
    await s.async_update()
    assert s.extra_state_attributes["transit_camera_validated"] is shown


# ================================================= D3 legacy store
class _State:
    def __init__(self, entity_id, attributes):
        self.entity_id = entity_id
        self.state = "on"
        self.attributes = attributes


def _validator(m, face_on=True):
    v = m.transit.TransitValidator.__new__(m.transit.TransitValidator)
    v.hass = SimpleNamespace(data={DOMAIN: {}})
    v._camera_sightings = {}
    v._face_recognition_enabled = face_on
    v._entity_to_physical = {}
    v._last_physical_sighting = {}
    v._protect_entity_set = set()
    return v


def test_legacy_writer_ignores_name_attributes(m):
    v = _validator(m, face_on=True)
    for attrs in ({"person_id": "Oji Udezue"}, {"face_id": "jaya"}, {"label": "Ezinne"}):
        v._on_camera_state_change(SimpleNamespace(data={"new_state": _State("binary_sensor.cam_a", attrs)}))
    assert list(v._camera_sightings) == ["unidentified"]
    assert len(v._camera_sightings["unidentified"]) == 3
    assert all(s["person_id"] == "unidentified" for s in v._camera_sightings["unidentified"])


@pytest.mark.asyncio
async def test_validate_transition_golden_unidentified_only(m, monkeypatch):
    """INV-3 golden, values derived by hand from develop's rules
    (path_confirmed +0.10, implausible -0.15, rule 2 closest-timed)."""
    t0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
    cams = ["binary_sensor.hall_person"]

    def tr(pid, ts):
        return SimpleNamespace(person_id=pid, timestamp=ts)

    def sight(ts, cam="binary_sensor.hall_person", room="Hall"):
        return {"camera_entity_id": cam, "timestamp": ts, "room": room, "person_id": "unidentified"}

    async def run(face_on, sightings, transition, concurrent=None, now=t0):
        v = _validator(m, face_on=face_on)
        monkeypatch.setattr(v, "_get_shared_space_cameras", lambda: list(cams))
        monkeypatch.setattr(m.transit.dt_util, "now", lambda: now)
        v._camera_sightings = {"unidentified": list(sightings)} if sightings else {}
        r = await v.validate_transition(transition, concurrent)
        return (r.path_validated, r.path_confidence_delta, sorted(r.checkpoint_rooms),
                r.path_method, r.identity_status, r.camera_person_id)

    # 1. one unidentified sighting in window -> confirmed.
    assert await run(True, [sight(t0 + timedelta(seconds=30))], tr("Oji Udezue", t0)) == (
        True, 0.10, ["Hall"], "path_confirmed", "unidentified", None)
    # 2. same, face recognition off -> identity unavailable.
    assert await run(False, [sight(t0 + timedelta(seconds=30))], tr("Oji Udezue", t0)) == (
        True, 0.10, ["Hall"], "path_confirmed", "unavailable", None)
    # 3. sighting outside window but camera active in last 10 min -> implausible.
    assert await run(True, [sight(t0 - timedelta(seconds=300))], tr("Oji Udezue", t0)) == (
        False, -0.15, [], "path_implausible", "unavailable", None)
    # 4. nothing at all -> no_camera_data.
    assert await run(True, [], tr("Oji Udezue", t0)) == (
        False, 0.0, [], "no_camera_data", "unavailable", None)
    # 5. two concurrent transitions, one sighting nearest Jaya's -> Oji gets none.
    oji, jaya = tr("Oji Udezue", t0), tr("Jaya", t0 + timedelta(seconds=60))
    one = [sight(t0 + timedelta(seconds=58))]
    assert await run(True, one, oji, [jaya]) == (
        False, 0.0, ["Hall"], "no_camera_data", "unidentified", None)
    assert await run(True, one, jaya, [oji]) == (
        True, 0.0, ["Hall"], "path_plausible", "unidentified", None)
    # 6. two sightings for two transitions -> plausible.
    two = [sight(t0 + timedelta(seconds=10)), sight(t0 + timedelta(seconds=50))]
    assert await run(True, two, oji, [jaya]) == (
        True, 0.0, ["Hall"], "path_plausible", "unidentified", None)


@pytest.mark.asyncio
async def test_next_room_window_zero_never_shown(m, monkeypatch):
    _clock(m, monkeypatch, module=m.sensor)
    monkeypatch.setattr(m.const, "NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S", 0)
    data = _with_prediction({"coordinator_manager": _manager(_presence(m, {OJI: _sighting(m, age_s=0)}))})
    s = _next_room(m, data)
    await s.async_update()
    # age 0 is not older than a 0 window, so only the explicit <= 0 off
    # switch hides it.
    assert s.extra_state_attributes["transit_camera_validated"] is False


# ============================== review C-M1 / C-L1 (read-side deletions)
@pytest.mark.asyncio
async def test_validate_transition_ignores_named_sighting_key(m, monkeypatch):
    """C-M1 (M20): a NAMED, in-window, shared-camera sighting stored under the
    person's own key must not be read. Only the "unidentified" key is used, so
    the result is the no-sighting golden. Activity check pinned False so the
    oracle is no_camera_data (develop's named lookup would give path_confirmed)."""
    t0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
    v = _validator(m, face_on=True)
    monkeypatch.setattr(v, "_get_shared_space_cameras", lambda: ["binary_sensor.hall_person"])
    monkeypatch.setattr(v, "_are_shared_space_cameras_active", lambda _c: False)
    monkeypatch.setattr(m.transit.dt_util, "now", lambda: t0)
    v._camera_sightings = {"Oji Udezue": [{
        "camera_entity_id": "binary_sensor.hall_person",
        "timestamp": t0 + timedelta(seconds=30),
        "room": "Hall",
        "person_id": "Oji Udezue",
    }]}
    r = await v.validate_transition(SimpleNamespace(person_id="Oji Udezue", timestamp=t0), None)
    assert (r.path_validated, r.path_confidence_delta, r.checkpoint_rooms,
            r.path_method, r.identity_status, r.camera_person_id) == (
        False, 0.0, [], "no_camera_data", "unavailable", None)


def test_correlator_face_match_rule_retired(m):
    """C-M1 (M23): a sighting whose person_id equals the transition's must not
    short-circuit to path_plausible. Rule 2 (closest-timed) assigns the single
    sighting to Jaya (2 s away vs 58 s), so Oji gets no_camera_data."""
    t0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
    v = _validator(m, face_on=True)
    oji = SimpleNamespace(person_id="Oji Udezue", timestamp=t0)
    jaya = SimpleNamespace(person_id="Jaya", timestamp=t0 + timedelta(seconds=60))
    named = [{"camera_entity_id": "binary_sensor.hall_person",
              "timestamp": t0 + timedelta(seconds=58), "room": "Hall",
              "person_id": "Oji Udezue"}]
    assert v._correlate_sighting_to_transition(oji, [jaya], named) == "no_camera_data"
    assert v._correlate_sighting_to_transition(jaya, [oji], named) == "path_plausible"


@pytest.mark.parametrize("bad_ts", ["x", None, object()])
def test_sighting_attributes_malformed_ts_all_null(m, bad_ts):
    """C-L1 (M16): a sighting with an unparseable ts yields the all-None shape
    instead of raising inside extra_state_attributes."""
    s = SimpleNamespace(ts=bad_ts, sighting_source="interior",
                        camera="binary_sensor.family_room_person_occupancy",
                        room="Family Room", census_veto=False)
    assert m.bs.PersonPhoneLeftBehindSensor._sighting_attributes(s) == {
        "camera_leg": "display_only",
        "last_camera_sighting_at": None,
        "last_sighting_source": None,
        "last_sighting_camera": None,
        "last_sighting_room": None,
        "last_sighting_census_veto": None,
    }

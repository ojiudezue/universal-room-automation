"""FACE-ARRIVAL-REBUILD-1 D1 (plan rev 11 §3.1-§3.2, §9 D1, §9A step 4): the
person-sighting producer.

REAL hass + REAL PresenceCoordinator (its ``_setup_person_sightings`` builds
the producer, exactly as ``async_setup`` does) + REAL PersonCensus (its MQTT
face bridge ``_on_frigate_face_msg`` is the source-(a) entry point) + REAL
CameraResolver over the registry extracted from the live house. Sources enter
through their production entry points: the census bridge, real face-sensor
state changes, a real ``ura_person_egress_event`` on the bus. Oracles are hand
written (slugs, zones, counts), never re-computed by the code under test.
"""
from __future__ import annotations

import time
from datetime import timedelta

import pytest
import pytest_asyncio

import _sighting_rig as R


@pytest.fixture(scope="module")
def mods():
    with R.import_real_modules() as ns:
        yield ns


@pytest_asyncio.fixture
async def hass():
    from pytest_homeassistant_custom_component.common import async_test_home_assistant

    async with async_test_home_assistant(load_registries=False) as real_hass:
        yield real_hass
        await real_hass.async_block_till_done()
        await real_hass.async_stop(force=True)


@pytest_asyncio.fixture
async def rig(mods, hass, monkeypatch):
    r = await R.build(mods, hass, monkeypatch)
    yield r
    await R.teardown(r)


def _only(rig):
    assert len(rig.sightings) == 1, [
        (s.slug, s.sighting_source, s.physical_camera) for s in rig.sightings]
    return rig.sightings[0]


# ------------------------------------------------------------ source (a) / (b)
@pytest.mark.asyncio
async def test_bridge_only_name_after_edge_emits(rig):
    """Source (a) alone, the name landing 45 s after the person edge with the
    person sensor already OFF: one sighting, synthetic, edge age about 45 s
    (the deleted v3.19 edge-read could never see this case)."""
    hass = rig.hass
    hass.states.async_set(R.FAMILY, "on")
    await hass.async_block_till_done()
    hass.states.async_set(R.FAMILY, "off")
    await hass.async_block_till_done()
    off_ts = hass.states.get(R.FAMILY).last_changed.timestamp()
    from unittest.mock import patch
    from homeassistant.util import dt as dt_util
    later = dt_util.utc_from_timestamp(off_ts + 45)
    with patch.object(rig.m.census.dt_util, "utcnow", lambda: later):
        R.bridge(rig, "family_room", "Oji")
    await hass.async_block_till_done()
    s = _only(rig)
    assert (s.slug, s.person_entity, s.sighting_source) == (
        "oji_udezue", "person.oji_udezue", "interior_pick")
    assert s.synthetic is True
    assert s.person_edge_age_s == pytest.approx(45, abs=1)
    assert s.camera == R.FAMILY
    assert s.house_zones == ("Entertainment",)
    assert s.room == "Family Room"


@pytest.mark.asyncio
async def test_sensor_change_only_emits(rig):
    await R.face(rig, "family_room", "Jaya")
    s = _only(rig)
    assert (s.slug, s.synthetic, s.face_name) == ("jaya", False, "Jaya")
    assert s.ts == pytest.approx(
        rig.hass.states.get(R.FACE["family_room"]).last_changed.timestamp())


@pytest.mark.asyncio
async def test_bridge_and_sensor_dedup_single_emit(rig):
    R.bridge(rig, "family_room", "Oji")
    await R.face(rig, "family_room", "Oji")
    s = _only(rig)
    assert s.synthetic is True  # first source wins


@pytest.mark.asyncio
async def test_debounce_fixed_window_not_sliding(rig):
    """Copies at +0, +40, +80 s: the window is fixed at the first emit, so
    +80 (past 60 s from +0) emits again; under a sliding window +40 would
    have pushed the end to +100 and +80 would be swallowed."""
    p = rig.producer
    base = time.time()
    key = next(iter(p._views))
    view = p._views[key]
    for dt_s in (0, 40, 80):
        p._emit_interior(key, "Oji", base + dt_s, synthetic=False)
    assert [round(s.ts - base) for s in rig.sightings] == [0, 80]
    assert view.picks


@pytest.mark.asyncio
async def test_multi_stem_message_single_emit(rig):
    """One message whose stems alias ONE physical camera gives one sighting."""
    p = rig.producer
    p._on_bridge("family_room", frozenset({"family_room", "family_room_alias"}), "Oji",
                 R.dt_now())
    await rig.hass.async_block_till_done()
    _only(rig)
    assert p.counters.get("multi_pick_messages", 0) == 0


@pytest.mark.asyncio
async def test_n_suffix_pick_resolves_without_flag(rig):
    """`_person_occupancy_2` picks resolve and emit (no `_N` skip, no flag)."""
    diag = rig.producer.diagnostics()
    assert R.UPSTAIRS in diag["face_sighting_picks_resolved"]
    assert R.PLAYROOM in diag["face_sighting_picks_resolved"]
    await R.face(rig, "upstairs_hall", "Ziri")
    await R.face(rig, "playroom", "Jaya")
    assert sorted((s.slug, s.room) for s in rig.sightings) == [
        ("jaya", "Playroom"), ("ziri", "Upstairs Hall")]


@pytest.mark.asyncio
async def test_ura_fused_room_pick_resolves_via_room_cameras(rig):
    """The URA fused Study B pick resolves through its room's room_cameras
    (staircase) and a staircase face emits with room Study B, zone Study."""
    assert R.STUDY_FUSED in rig.producer.diagnostics()["face_sighting_picks_resolved"]
    await R.face(rig, "staircase", "Oji")
    s = _only(rig)
    assert (s.camera, s.room, s.house_zones) == (R.STUDY_FUSED, "Study B", ("Study",))


@pytest.mark.asyncio
async def test_ura_fused_pick_room_cameras_empty_unresolved(rig):
    diag = rig.producer.diagnostics()
    assert diag["face_sighting_picks_unresolved"][R.GARAGE_FUSED] == "room_cameras_empty"


@pytest.mark.asyncio
async def test_unresolvable_pick_reported_not_guessed(mods, hass, monkeypatch):
    rig = await R.build(mods, hass, monkeypatch, zones={
        "Z": ["binary_sensor.no_such_camera_person_occupancy", R.GARAGE_FUSED]})
    try:
        diag = rig.producer.diagnostics()
        assert diag["face_sighting_picks_resolved"] == []
        assert diag["face_sighting_picks_unresolved"] == {
            "binary_sensor.no_such_camera_person_occupancy": "no_fusion",
            R.GARAGE_FUSED: "room_cameras_empty",
        }
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_protect_pick_walks_to_frigate_twin_face(mods, hass, monkeypatch):
    """A Protect pick (no face name of its own) walks pick -> physical camera
    -> the Frigate twin's face sensor."""
    rig = await R.build(mods, hass, monkeypatch, zones={"Den": [R.FAMILY_PROTECT]})
    try:
        await R.face(rig, "family_room", "Oji")
        s = _only(rig)
        assert (s.camera, s.house_zones) == (R.FAMILY_PROTECT, ("Den",))
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_rebind_on_ha_started_and_options_update(mods, hass, monkeypatch):
    """Frigate loads after URA: no faces at first (registry empty), resolved
    at EVENT_HOMEASSISTANT_STARTED; a pick added later is bound on the next
    presence tick."""
    rig = await R.build(mods, hass, monkeypatch, setup=False)
    try:
        good = rig.resolver
        rig.mgr.resolver = mods.resolver.CameraResolver(R._ER([]), R._DR([]))
        from homeassistant.core import CoreState
        hass.set_state(CoreState.not_running)
        rig.presence._setup_person_sightings()
        p = rig.presence._person_sightings
        p._setup_ts = time.time() - 700
        assert p.diagnostics()["face_sighting_picks_resolved"] == []
        rig.mgr.resolver = good
        hass.set_state(CoreState.running)
        hass.bus.async_fire("homeassistant_started")
        await hass.async_block_till_done()
        assert R.FAMILY in p.diagnostics()["face_sighting_picks_resolved"]
        # options update: a new zone pick appears; next tick binds it.
        zm = hass.config_entries.async_get_entry("zm")
        zm.options["zones"]["Garage"] = {"zone_cameras": [R.GARAGE_A_FRIGATE]}
        assert R.GARAGE_A_FRIGATE not in p.diagnostics()["face_sighting_picks_resolved"]
        p.on_tick()
        assert R.GARAGE_A_FRIGATE in p.diagnostics()["face_sighting_picks_resolved"]
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_unpicked_camera_silent(rig):
    await R.face(rig, "garage_a", "Oji")
    R.bridge(rig, "garage_a", "Oji")
    await rig.hass.async_block_till_done()
    assert rig.sightings == []


@pytest.mark.asyncio
async def test_boot_restore_not_a_sighting(mods, hass, monkeypatch):
    """A restored face sensor (unavailable -> name) and an egress crossing
    inside the boot window give no sighting."""
    rig = await R.build(mods, hass, monkeypatch)
    try:
        hass.states.async_set(R.FACE["family_room"], "unavailable")
        await hass.async_block_till_done()
        await R.face(rig, "family_room", "Jaya")
        assert rig.sightings == []
        rig.producer._setup_ts = time.time()  # inside the boot window
        await R.face(rig, "master_hallway", "Jaya")
        await R.egress(rig)
        assert rig.sightings == []
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_boot_exclusion_drops_before_boot_end_keeps_after(rig):
    """Literal boundary: boot_end = setup + 600 s; ts = boot_end - 1 dropped,
    boot_end + 1 kept (behavioural, via the one emit function)."""
    p = rig.producer
    setup = 1_800_000_000.0
    p._setup_ts = setup
    key = next(iter(p._views))
    p._emit_interior(key, "Oji", setup + 599, synthetic=False)
    assert rig.sightings == []
    p._emit_interior(key, "Oji", setup + 601, synthetic=False)
    assert len(rig.sightings) == 1


# ------------------------------------------------------------------ source (c)
@pytest.mark.asyncio
async def test_egress_face_provenance_sighting(rig):
    await R.egress(rig, identity_provenance="face")
    s = _only(rig)
    assert (s.sighting_source, s.slug, s.room, s.house_zones, s.provenance) == (
        "egress_entry", "oji_udezue", "Garage A", ("Back Hallway",), "face")
    assert s.identity_role == "attached"


@pytest.mark.asyncio
async def test_egress_ble_provenance_silent(rig):
    await R.egress(rig, identity_provenance="ble", identity_confidence=0.72)
    await R.egress(rig, identity_provenance=None)
    assert rig.sightings == []
    assert rig.producer.diagnostics()["egress_non_face_skipped"] == 2


@pytest.mark.asyncio
async def test_egress_exit_sighting_never_arrival(rig):
    await R.egress(rig, direction="exit", identity_provenance="ble+face",
                   identity_confidence=0.95)
    s = _only(rig)
    assert (s.sighting_source, s.provenance) == ("egress_exit", "ble+face")


@pytest.mark.asyncio
async def test_ambiguous_egress_silent(rig):
    await R.egress(rig, direction="ambiguous")
    await R.egress(rig, person_id=None, identity_provenance=None)
    assert rig.sightings == []


@pytest.mark.asyncio
async def test_backfill_not_a_sighting(rig):
    """Exit backfill dispatches SIGNAL_EGRESS_EXIT_BACKFILLED, never the egress
    bus event, so it can never become a sighting."""
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    async_dispatcher_send(rig.hass, rig.m.signals.SIGNAL_EGRESS_EXIT_BACKFILLED,
                          {"row_id": 1, "person_id": "oji_udezue"})
    await rig.hass.async_block_till_done()
    assert rig.sightings == []


@pytest.mark.asyncio
async def test_egress_provenance_copied_not_recomputed(rig):
    await R.egress(rig, identity_confidence=0.9, identity_synthetic_corroborated=True)
    s = _only(rig)
    assert (s.confidence, s.synthetic, s.provenance) == (0.9, True, "face")


@pytest.mark.asyncio
async def test_egress_boot_window_not_a_sighting(rig):
    rig.producer._setup_ts = time.time()
    await R.egress(rig)
    assert rig.sightings == []
    assert rig.producer.counters["boot_dropped"] == 1


@pytest.mark.asyncio
async def test_door_pick_and_egress_dedup(mods, hass, monkeypatch):
    """The same recognition through a door pick (Garage A Frigate) and that
    door's egress crossing gives ONE sighting."""
    rig = await R.build(mods, hass, monkeypatch, zones={"Garage": [R.GARAGE_A_FRIGATE]})
    try:
        await R.face(rig, "garage_a", "Oji")
        await R.egress(rig)
        s = _only(rig)
        assert s.sighting_source == "interior_pick"
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_protect_pick_and_frigate_egress_one_key(mods, hass, monkeypatch):
    """Pick = the Protect leg of Garage A, crossing = the Frigate leg: one
    canonical key, so one sighting (two under the old physical_camera_id)."""
    rig = await R.build(mods, hass, monkeypatch, zones={"Garage": [R.GARAGE_A_PROTECT]})
    try:
        await R.face(rig, "garage_a", "Oji")
        await R.egress(rig, egress_camera=R.GARAGE_A_FRIGATE)
        s = _only(rig)
        assert s.camera == R.GARAGE_A_PROTECT
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_canonical_camera_key_same_for_all_legs(rig):
    res = rig.resolver
    key = rig.m.resolver.canonical_camera_key
    a = res.resolve_operator_declaration([R.GARAGE_A_FRIGATE])
    b = res.resolve_operator_declaration([R.GARAGE_A_PROTECT])
    assert len(a) == 1 and len(b) == 1
    assert key(a[0]) == key(b[0])
    assert a[0].physical_camera_id != b[0].physical_camera_id  # why the helper exists
    devs = sorted(s.device_id for s in a[0].sources)
    assert key(a[0]) == devs[0]


# ------------------------------------------------------------- filters / data
@pytest.mark.asyncio
async def test_face_suppressed_silent(mods, hass, monkeypatch):
    rig = await R.build(mods, hass, monkeypatch, strict=True)
    try:
        rig.census.set_face_drill_forced(hass, True)
        R.bridge(rig, "family_room", "Oji")
        await R.face(rig, "master_hallway", "Oji")
        await R.egress(rig)
        assert rig.sightings == []
        assert rig.producer.counters["suppressed"] >= 2
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_unmapped_name_counted_not_emitted(rig):
    await R.face(rig, "family_room", "Bob")
    assert rig.sightings == []
    assert rig.producer.diagnostics()["face_sighting_unmapped_names"] == 1


@pytest.mark.asyncio
async def test_unmapped_passthrough_name_not_emitted(rig):
    """The mapper passes unknown names through lowercased ("stranger"): that is
    NOT a tracked slug, so it is unmapped, as is an ambiguous head ("")."""
    await R.face(rig, "family_room", "Stranger")
    assert rig.sightings == []


@pytest.mark.asyncio
async def test_guest_slug_not_a_resident_sighting(rig):
    await R.face(rig, "family_room", "Ojini")
    assert rig.sightings == []
    assert rig.producer.counters["guest_names"] == 1


@pytest.mark.asyncio
async def test_oji_maps_without_alias(rig):
    await R.face(rig, "family_room", "Oji")
    assert _only(rig).person_entity == "person.oji_udezue"


@pytest.mark.asyncio
async def test_master_hallway_two_zones(rig):
    await R.face(rig, "master_hallway", "Ezinne")
    assert _only(rig).house_zones == ("Entertainment", "Master Suite")


@pytest.mark.asyncio
async def test_interior_confidence_is_medium(rig):
    await R.face(rig, "family_room", "Oji")
    assert _only(rig).confidence == 0.6


@pytest.mark.asyncio
async def test_not_home_face_sighting_carries_census_veto(rig):
    rig.hass.states.async_set("person.jaya", "not_home")
    await R.face(rig, "family_room", "Jaya")
    s = _only(rig)
    assert (s.person_state_at_emit, s.census_would_veto) == ("not_home", True)


@pytest.mark.asyncio
async def test_last_sighting_accessor_upgrades_not_reemits(rig):
    R.bridge(rig, "family_room", "Oji")
    first = rig.presence.get_last_person_sighting("person.oji_udezue")
    assert first.synthetic is True
    await R.face(rig, "family_room", "Oji")
    assert len(rig.sightings) == 1
    upgraded = rig.presence.get_last_person_sighting("person.oji_udezue")
    assert upgraded.synthetic is False and upgraded.ts == first.ts
    assert rig.presence.get_last_person_sightings() == {"person.oji_udezue": upgraded}


@pytest.mark.asyncio
async def test_census_reload_keeps_callback(mods, hass, monkeypatch):
    """A rebuilt census (integration reload) reads the SAME hass.data list,
    so the presence registration survives."""
    rig = await R.build(mods, hass, monkeypatch)
    try:
        new_census = mods.census.PersonCensus(hass, rig.mgr)
        hass.data[R.DOMAIN]["census"] = new_census
        rig.census = new_census
        R.bridge(rig, "family_room", "Oji")
        await hass.async_block_till_done()
        assert len(rig.sightings) == 1
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_tracker_face_fields_updated(rig):
    await R.face(rig, "master_hallway", "Ezinne")
    from datetime import datetime
    for z in ("Entertainment", "Master Suite"):
        t = rig.presence._zone_trackers[z]
        assert t._last_face_recognized == "ezinne"
        assert isinstance(t._last_face_time, datetime)
        assert t._last_face_time.isoformat()


@pytest.mark.asyncio
async def test_teardown_unsubscribes_all(rig):
    p = rig.producer
    assert p._bridge_cb in rig.hass.data[R.DOMAIN]["face_latch_callbacks"]
    p.async_teardown()
    assert rig.hass.data[R.DOMAIN]["face_latch_callbacks"] == []
    await R.face(rig, "family_room", "Oji")
    await R.egress(rig)
    R.bridge(rig, "family_room", "Oji")
    assert rig.sightings == []
    assert rig.presence.get_last_person_sightings() == {}


@pytest.mark.asyncio
async def test_kill_switch_noop(mods, hass, monkeypatch):
    """FACE_SIGHTING_ENABLED False: no callback, no ring, no listener, no
    sighting (INV-NOOP)."""
    monkeypatch.setattr(mods.const, "FACE_SIGHTING_ENABLED", False)
    rig = await R.build(mods, hass, monkeypatch)
    try:
        assert rig.census._frigate_face_named_ring is None
        assert rig.hass.data[R.DOMAIN].get("face_latch_callbacks", []) == []
        R.bridge(rig, "family_room", "Oji")
        await R.face(rig, "family_room", "Oji")
        await R.egress(rig)
        assert rig.sightings == []
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_two_cameras_same_person_two_sightings(rig):
    """The debounce key includes the physical camera: the same person on two
    different cameras inside 60 s gives two sightings."""
    await R.face(rig, "family_room", "Oji")
    await R.face(rig, "upstairs_hall", "Oji")
    assert sorted(s.camera for s in rig.sightings) == sorted([R.FAMILY, R.UPSTAIRS])


@pytest.mark.asyncio
async def test_presence_async_setup_builds_producer(mods, hass, monkeypatch):
    """Wire-in anchor: PresenceCoordinator.async_setup (not the helper) builds
    the producer; a face then emits. async_teardown removes it."""
    rig = await R.build(mods, hass, monkeypatch, setup=False)
    try:
        await rig.presence.async_setup()
        p = rig.presence._person_sightings
        assert p is not None
        p._setup_ts = time.time() - 700
        await R.face(rig, "family_room", "Oji")
        assert len(rig.sightings) == 1
        await rig.presence.async_teardown()
        assert rig.presence._person_sightings is None
        assert hass.data[R.DOMAIN]["face_latch_callbacks"] == []
        await R.face(rig, "family_room", "Jaya")
        assert len(rig.sightings) == 1
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_registry_rebuild_and_periodic_retry_rebind(mods, hass, monkeypatch):
    """Trigger 1: a rebuilt resolver (registry update) is observed on the next
    tick and the picks re-resolve. Trigger 4: an unresolved pick is retried
    every FACE_SIGHTING_PICK_RERESOLVE_S (add-only)."""
    rig = await R.build(mods, hass, monkeypatch, setup=False)
    try:
        good = rig.resolver
        rig.mgr.resolver = mods.resolver.CameraResolver(R._ER([]), R._DR([]))
        rig.presence._setup_person_sightings()
        p = rig.presence._person_sightings
        assert p.diagnostics()["face_sighting_picks_resolved"] == []
        rig.mgr.resolver = good                       # registry rebuilt
        p._last_retry_ts = time.time()                # retry NOT due: only trigger 1
        p.on_tick()
        assert R.FAMILY in p.diagnostics()["face_sighting_picks_resolved"]
        # Trigger 4: Garage A gets cameras; the resolver is unchanged, so only
        # the retry can bind it, and only after the period.
        hass.config_entries.async_get_entry("room_garage_a").options[
            mods.const.CONF_ROOM_CAMERAS] = [R.GARAGE_A_FRIGATE]
        now = time.time()
        p._last_retry_ts = now
        p.on_tick(now + 299)                          # literal: period 300
        assert R.GARAGE_FUSED not in p.diagnostics()["face_sighting_picks_resolved"]
        p.on_tick(now + 301)
        assert R.GARAGE_FUSED in p.diagnostics()["face_sighting_picks_resolved"]
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_egress_sighting_ts_is_crossing_time(rig):
    """C-L3: the egress sighting carries the event's crossing timestamp,
    not processing time."""
    from homeassistant.util import dt as dt_util
    rig.producer._setup_ts = time.time() - 3600
    crossing = dt_util.utcnow() - __import__("datetime").timedelta(seconds=120)
    await R.egress(rig, timestamp=crossing.isoformat())
    s = _only(rig)
    assert abs(s.ts - crossing.timestamp()) < 0.001

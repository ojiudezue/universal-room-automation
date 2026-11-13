"""Person sightings Phase 1, review A fix-up (docs/reviews/code-review/
v_person_sightings_p1_A.md): A1 trip-wire denominator window, A2 the
operator's Face Recognition switch, A3 attribute-only updates, A4 the
day-boundary debounce prune, A6/A7/A8 input hygiene, and the D5 retired-flag
lint. REAL hass + REAL presence / census / resolver (the shared rig);
hand-written oracles, literal boundaries.
"""
from __future__ import annotations

import ast
import pathlib
import time

import pytest
import pytest_asyncio

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse


def _pages_fixture(mods, monkeypatch):
    pages: list = []

    async def _fake_fire(hass_, kind, key, diagnosis, remedy="", severity=None, **kw):
        pages.append((kind, severity))
        return True

    monkeypatch.setattr(mods.sighting, "fire_stuck_signal", _fake_fire)
    return pages


async def _faces(rig, n, name="Oji", camera="family_room"):
    for _ in range(n):
        R.bridge(rig, camera, name)
    await rig.hass.async_block_till_done()


async def _tick(rig):
    await rig.presence._periodic_inference()
    await rig.hass.async_block_till_done()


# ----------------------------------------------------------------- A1
@pytest.mark.asyncio
async def test_a1_restart_boot_window_faces_do_not_page(mods, hass, monkeypatch):
    """Repro 1: right after a restart (producer setup = now), a healthy hook,
    10 named resident faces on a picked camera inside the 600 s boot window
    (all boot-dropped by the producer), one tick -> no page."""
    rig = await R.build(mods, hass, monkeypatch, past_boot=False)
    pages = _pages_fixture(mods, monkeypatch)
    try:
        await _faces(rig, 10)
        assert rig.sightings == []
        assert rig.producer.counters["boot_dropped"] >= 1
        await _tick(rig)
        assert pages == []
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_a1_presence_resetup_does_not_page(mods, hass, monkeypatch):
    """Repro 2: past boot the producer emits normally; presence re-runs
    `_setup_person_sightings` (entry reload; the census ring survives); the
    next tick must not page on the old ring entries."""
    rig = await R.build(mods, hass, monkeypatch)
    pages = _pages_fixture(mods, monkeypatch)
    try:
        await _faces(rig, 10)
        assert len(rig.sightings) == 1
        rig.presence._setup_person_sightings()
        assert rig.presence._person_sightings is not rig.producer
        await _tick(rig)
        assert pages == []
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_a1_denominator_boundary_literal(mods, hass, monkeypatch):
    """Hook dead, setup S: 10 faces at S+599 never count; 10 at S+601 page
    (the boundary is S + 600, literal)."""
    from unittest.mock import patch
    from homeassistant.util import dt as dt_util
    rig = await R.build(mods, hass, monkeypatch)
    pages = _pages_fixture(mods, monkeypatch)
    try:
        hass.data[R.DOMAIN]["face_latch_callbacks"].clear()
        p = rig.producer
        S = time.time() - 650
        p._setup_ts = S
        with patch.object(rig.m.census.dt_util, "utcnow",
                          lambda: dt_util.utc_from_timestamp(S + 599)):
            await _faces(rig, 10)
        p.check_tripwires(S + 640)
        await hass.async_block_till_done()
        assert pages == []
        with patch.object(rig.m.census.dt_util, "utcnow",
                          lambda: dt_util.utc_from_timestamp(S + 601)):
            await _faces(rig, 10)
        p.check_tripwires(S + 640)
        await hass.async_block_till_done()
        assert pages == [("face_sighting_zero", "HIGH")]
    finally:
        await R.teardown(rig)


# ----------------------------------------------------------------- A2
@pytest.fixture
def interior_on(mods, monkeypatch):
    monkeypatch.setattr(mods.const, "FACE_ARRIVAL_INTERIOR_ENABLED", True)


@pytest.mark.asyncio
async def test_a2_switch_off_no_sighting_no_arrival_no_display(
        mods, hass, monkeypatch, interior_on):
    """Face Recognition switch OFF: a face sensor change and a bridge message
    on a picked camera give no sighting, no camera_face arrival, no zone
    last-face write. Flipped ON (as the SIGNAL_URA_FACE_RECOGNITION_CHANGED
    handler does), the same face emits and arrives."""
    rig = await R.build(mods, hass, monkeypatch, face_recognition=False,
                        persons={p: "not_home" for p in R.TRACKED})
    arrivals: list = []

    def _cap(payload):
        arrivals.append(payload)

    _cap._hass_callback = True
    rig.unsubs.append(mods.dispatcher.async_dispatcher_connect(
        hass, mods.signals.SIGNAL_PERSON_ARRIVING, _cap))
    try:
        await R.face(rig, "family_room", "Oji")
        R.bridge(rig, "master_hallway", "Jaya")
        await hass.async_block_till_done()
        assert rig.sightings == []
        assert arrivals == []
        assert rig.producer.counters["face_recognition_off"] == 2
        t = rig.presence._zone_trackers["Entertainment"]
        assert (t._last_face_recognized, t._last_face_time) == ("", None)
        rig.presence._face_recognition_enabled = True
        await R.face(rig, "family_room", "Ezinne")
        assert [s.slug for s in rig.sightings] == ["ezinne"]
        assert [a["source"] for a in arrivals] == ["camera_face"]
        assert t._last_face_recognized == "ezinne"
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_a2_switch_off_egress_sighting_writes_no_zone_display(mods, hass, monkeypatch):
    """Egress sightings are the transit validator's identity, not the
    presence face path: they still emit, but the zone last-face display
    stays untouched while the switch is OFF."""
    rig = await R.build(mods, hass, monkeypatch, face_recognition=False)
    try:
        await R.egress(rig, identity_provenance="face")
        assert [s.sighting_source for s in rig.sightings] == ["egress_entry"]
        t = rig.presence._zone_trackers["Back Hallway"]
        assert (t._last_face_recognized, t._last_face_time) == ("", None)
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_a2_switch_off_tripwire_silent(mods, hass, monkeypatch):
    """Switch OFF: faces flow through the census but no sighting is expected,
    so the zero-sighting trip-wire must not page."""
    rig = await R.build(mods, hass, monkeypatch, face_recognition=False)
    pages = _pages_fixture(mods, monkeypatch)
    try:
        await _faces(rig, 12)
        await _tick(rig)
        assert pages == []
    finally:
        await R.teardown(rig)


# ----------------------------------------------------------------- A3
@pytest.mark.asyncio
async def test_a3_attribute_only_update_is_not_a_sighting(mods, hass, monkeypatch):
    """A recognition dropped by a gate (switch OFF) does not stamp the
    debounce; a later attribute-only update (same state, old last_changed)
    must not emit a sighting with the stale ts."""
    rig = await R.build(mods, hass, monkeypatch, face_recognition=False)
    try:
        await R.face(rig, "family_room", "Oji")
        assert rig.sightings == []
        rig.presence._face_recognition_enabled = True
        hass.states.async_set(R.FACE["family_room"], "Oji", {"score": 0.91})
        await hass.async_block_till_done()
        assert rig.sightings == []
        await R.face(rig, "family_room", "Jaya")  # a real change still emits
        assert [s.slug for s in rig.sightings] == ["jaya"]
    finally:
        await R.teardown(rig)


# ----------------------------------------------------------------- A4
@pytest.mark.asyncio
async def test_a4_day_change_prunes_only_expired_keys(mods, hass, monkeypatch):
    """The first transition of a new day keeps live debounce keys (arrival
    600 s, sighting 60 s, literals) and drops expired / unknown ones."""
    rig = await R.build(mods, hass, monkeypatch)
    try:
        pres = rig.presence
        now = time.time()
        pres._face_arrival_cooldown.clear()
        pres._face_arrival_cooldown.update({
            ("arrival", "oji_udezue"): now - 100,          # live (< 600)
            ("arrival", "jaya"): now - 601,                # expired
            ("sighting", "oji_udezue", "cam1"): now - 10,  # live (< 60)
            ("sighting", "jaya", "cam1"): now - 61,        # expired
            "person.x:Zone": now,                          # legacy shape
        })
        pres._transition_reset_date = "1999-01-01"
        await pres._count_transition()
        assert set(pres._face_arrival_cooldown) == {
            ("arrival", "oji_udezue"), ("sighting", "oji_udezue", "cam1")}
    finally:
        await R.teardown(rig)


# ------------------------------------------------------------ A6 / A7 / A8
def test_a6_unhashable_source_fails_closed(mods):
    from custom_components.universal_room_automation import arrival_edges as ae
    assert ae.arrival_source_needs_corroboration(["camera_face"]) is True
    assert ae.arrival_source_needs_corroboration({"x": 1}) is True
    assert ae.arrival_source_needs_corroboration("geofence") is False
    assert ae.arrival_source_needs_corroboration(None) is False


@pytest.mark.asyncio
async def test_a7_zero_identity_confidence_preserved(rig_default):
    await R.egress(rig_default, identity_provenance="face", identity_confidence=0.0)
    assert [s.confidence for s in rig_default.sightings] == [0.0]


@pytest_asyncio.fixture
async def rig_default(mods, hass, monkeypatch):
    r = await R.build(mods, hass, monkeypatch)
    yield r
    await R.teardown(r)


def test_a8_bool_lag_rejected(mods):
    paths = mods.paths
    ctx = paths.ValidationContext(
        live_groups={"garage_a"},
        resolve_node=lambda e: (e.split(".", 1)[1], e),
        egress_keys_by_group={"garage_a": {"b"}},
        exterior_keys={"a"},
        detached_doors=set(),
        buffer_s=180.0,
        default_window_s=30.0,
    )
    spec = {"schema_version": 1, "doors": {"garage_a": {"edges": [
        {"from": "camera.a", "to": "camera.b", "kind": "approach", "lag_p90_s": True}]}}}
    with pytest.raises(paths.PathMapError, match="rule 8"):
        paths.validate(spec, ctx)
    spec["doors"]["garage_a"]["edges"][0]["lag_p90_s"] = 1
    pmap, _w = paths.validate(spec, ctx)
    assert pmap.edge_count == 1


# ------------------------------------------------------------ D5 lint (L5)
def test_retired_flag_unread():
    """LINT ONLY (Bug Class #62, plan L5): not test authority. The retired
    FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED has no reader outside its
    definition in const.py. Behavioural authority:
    test_person_sighting.py::test_n_suffix_pick_resolves_without_flag."""
    pkg = (pathlib.Path(__file__).resolve().parents[2] / "custom_components"
           / "universal_room_automation")
    hits = []
    for path in sorted(pkg.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            name = getattr(node, "id", None) or getattr(node, "attr", None)
            if name == "FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED" and not (
                    path.name == "const.py" and isinstance(node.ctx, ast.Store)):
                hits.append(f"{path.relative_to(pkg)}:{node.lineno}")
    assert hits == []

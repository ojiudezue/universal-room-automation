"""Census deconfliction CD1 (PLANNING_census_deconfliction.md §3.3, §4, CD1).

Pure-function tests load ``census_deconflict.py`` by path (no HA). Census
tests drive the REAL ``PersonCensus._async_update_census_locked`` through the
replay harness (``_census_vision_harness``: real HA core, real census, real
dispatcher, real presence). Oracles are literals.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import _census_vision_harness as H
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

_PATH = (Path(__file__).resolve().parents[2] / "custom_components"
         / "universal_room_automation" / "census_deconflict.py")


def _load():
    name = "_ura_census_deconflict_under_test"
    spec = importlib.util.spec_from_file_location(name, _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


D = _load()


def _trust(guests, identified=2):
    return D.TrustFields(identified_count=identified,
                         identified_persons=tuple(f"p{i}" for i in range(identified)),
                         unidentified_count=guests, total_persons=identified + guests)


# Hand-built case table (§3.3): (guest_cam, guest_vis) -> case, agreement.
CASES = [
    (1, 1, "A", "both_agree"),
    (0, 3, "B", "disagree"),
    (0, 1, "B", "close"),
    (3, 0, "C", "disagree"),
    (2, 1, "C", "close"),
    (2, None, "D", "single_source"),
]


@pytest.mark.parametrize("cam,vis,case,agr", CASES)
def test_awareness_equals_trust_until_lead(cam, vis, case, agr):
    """INV-P2-AWARE-DECONFLICT: F-LEAD off -> aware_guests == guest_cam."""
    trust = _trust(cam)
    t, aw = D.deconflict_house(trust, guest_vis=vis, vision_leads=False, flag_min=1)
    assert t is trust
    assert (aw.aware_guests, aw.aware_total, aw.case, aw.aware_agreement) == (
        cam, 2 + cam, case, agr)
    assert aw.count_provenance == ("agree" if case == "A" else "camera")
    assert aw.aware_identified == ("p0", "p1")


@pytest.mark.parametrize("cam,vis,case,agr", CASES)
def test_awareness_follows_vision_once_lead(cam, vis, case, agr):
    _t, aw = D.deconflict_house(_trust(cam), guest_vis=vis, vision_leads=True,
                                flag_min=1)
    expected = cam if vis is None else vis
    assert (aw.aware_guests, aw.case, aw.aware_agreement) == (expected, case, agr)
    assert aw.count_provenance == {"A": "agree", "D": "camera"}.get(case, "vision")


def test_flag_min_extremes():
    """Config extremes: flag 0 (equality still agrees), flag 5 (a gap of 4
    is still case A)."""
    _t, aw = D.deconflict_house(_trust(2), guest_vis=2, vision_leads=False, flag_min=0)
    assert aw.case == "A"
    _t, aw = D.deconflict_house(_trust(2), guest_vis=3, vision_leads=False, flag_min=0)
    assert (aw.case, aw.aware_agreement) == ("B", "disagree")
    _t, aw = D.deconflict_house(_trust(0), guest_vis=4, vision_leads=True, flag_min=5)
    assert (aw.case, aw.aware_guests, aw.count_provenance) == ("A", 4, "agree")


def test_guest_side_max_not_sum():
    """INV-DEDUP / estimator gate 9: R = 2, U_gr = 1, M_cam = 3, T = 0.
    As guest-side terms: U_gr 1, M_cam - R = 1, T - R floor 0. Max -> 1
    guest, total 3; a sum would give 2 guests, total 4."""
    _t, aw = D.deconflict_house(
        _trust(1), guest_vis=0, vision_leads=True, flag_min=1,
        extra_guest_terms={"guest_room": 1, "camera_max": 3 - 2},
    )
    assert (aw.aware_guests, aw.aware_total) == (1, 3)
    # Property over small grids: always the max of the present terms.
    for a in range(4):
        for b in range(4):
            for c in (None, 0, 2):
                got = D.guest_terms_max({"x": a, "y": b, "z": c})
                assert got == max(v for v in (a, b, c) if v is not None)
    assert D.guest_terms_max({"x": None}) is None


def test_agreement_values_match_const(mods):
    c = mods.const
    assert (D.AGREEMENT_BOTH, D.AGREEMENT_CLOSE, D.AGREEMENT_DISAGREE,
            D.AGREEMENT_SINGLE) == (c.CENSUS_AGREEMENT_BOTH, c.CENSUS_AGREEMENT_CLOSE,
                                    c.CENSUS_AGREEMENT_DISAGREE, c.CENSUS_AGREEMENT_SINGLE)


# ------------------------------------------------------------ census wiring
async def _world(mods, hass, monkeypatch, freezer, *, fake=None,  # noqa: F811
                 lead=False):
    freezer.move_to(H.START)
    w = await H.build(mods, hass, monkeypatch)
    if fake is not None:
        hass.data[H.DOMAIN][mods.const.CROSSING_VISION_HASS_KEY] = fake
    monkeypatch.setattr(mods.const, "CROSSING_VISION_AWARENESS_VISION_LEADS", lead)
    return w


async def _tick(w, *, fam="1", mas="0", ble=None, persons=None, face=None):
    hass = w.hass
    hass.states.async_set(H.FAM_COUNT, fam)
    hass.states.async_set(H.MAS_COUNT, mas)
    hass.states.async_set(H.R.FAMILY, "on" if fam not in ("0", "unavailable") else (
        "unavailable" if fam == "unavailable" else "off"))
    hass.states.async_set(H.R.MASTER, "on" if mas not in ("0", "unavailable") else (
        "unavailable" if mas == "unavailable" else "off"))
    for pid, st in (persons or {}).items():
        hass.states.async_set(pid, st)
    if face is not None:
        hass.states.async_set(H.R.FACE["family_room"], face)
    w.pc.data = {k: {"location": v} for k, v in (ble or {}).items()}
    await hass.async_block_till_done()
    await w.census._async_update_census_locked()
    await hass.async_block_till_done()
    return w.census.last_result.house


@pytest.mark.asyncio
async def test_census_publishes_awareness_from_ledger(mods, hass, monkeypatch,  # noqa: F811
                                                      freezer):
    fake = H.FakeVision(3)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake, lead=True)
    try:
        house = await _tick(w, fam="1", ble={"oji_udezue": "living_room"},
                            persons={H.OJI: "home", H.EZ: "not_home"})
        assert (house.identified_count, house.unidentified_count) == (1, 0)
        assert (house.aware_guests, house.aware_total, house.count_provenance,
                house.aware_agreement) == (3, 4, "vision", "disagree")
        assert house.aware_identified == ["oji_udezue"]
        assert (house.aware_vision_status, house.aware_ledger_state) == ("ok", "known")
        [call] = fake.calls
        assert call == {"resident_term": 1, "camera_bodies": 1,
                        "camera_input_dark": False}
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_camera_bodies_counts_face_labelled_person(mods, hass, monkeypatch,  # noqa: F811
                                                         freezer):
    """One body on the family-room camera with a fresh face: the ledger is
    handed bodies 1 while the Frigate pre-cancel scalar reads 0."""
    fake = H.FakeVision(0)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake)
    try:
        await _tick(w, fam="1", face="Oji", persons={H.OJI: "home"})
        assert w.census._last_camera_total_pre_cancel == 0
        assert fake.calls[-1]["camera_bodies"] == 1
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_camera_bodies_none_when_all_platforms_unavailable(  # noqa: F811
    mods, hass, monkeypatch, freezer,
):
    fake = H.FakeVision(0)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake)
    try:
        await _tick(w, fam="2", mas="0")
        assert fake.calls[-1]["camera_bodies"] == 2
        await _tick(w, fam="unavailable", mas="unavailable")
        assert fake.calls[-1]["camera_bodies"] is None
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_no_interior_cameras_bodies_none(mods, hass, monkeypatch,  # noqa: F811
                                               freezer):
    """Review A-MED-3: no configured interior camera -> the ledger is
    handed bodies None (absent source = missing, never 0); the trust
    view's camera_total stays 0 as on develop."""
    fake = H.FakeVision(0)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake)
    try:
        monkeypatch.setattr(w.census, "_get_interior_camera_entities", lambda: [])
        house = await _tick(w, fam="2", mas="1")
        assert fake.calls[-1]["camera_bodies"] is None
        assert house.unidentified_count == 0
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_xval_off_all_unavailable_bodies_none(mods, hass, monkeypatch,  # noqa: F811
                                                    freezer):
    """Review A-MED-3: cross-validation off and no configured entity
    available -> bodies None (that path now flags every platform
    unavailable for the ledger copy); one available -> its count."""
    fake = H.FakeVision(0)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake)
    try:
        monkeypatch.setattr(w.census, "_is_cross_validation_enabled", lambda: False)
        # The harness hass has no loaded entity registry; this path only
        # reads device ids from it (none = no per-device dedup).
        cc_mod = sys.modules[type(w.census).__module__]
        monkeypatch.setattr(cc_mod, "er", SimpleNamespace(
            async_get=lambda _h: SimpleNamespace(async_get=lambda _e: None)))
        await _tick(w, fam="2", mas="0")
        assert fake.calls[-1]["camera_bodies"] == 2
        await _tick(w, fam="unavailable", mas="unavailable")
        assert fake.calls[-1]["camera_bodies"] is None
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_resident_term_reads_presence_residents(mods, hass, monkeypatch,  # noqa: F811
                                                      freezer):
    """R = max(presence residents home, identified_count): a resident home
    with no BLE (phone off) still counts; presence missing -> identified."""
    fake = H.FakeVision(0)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake)
    try:
        await _tick(w, fam="0")
        assert fake.calls[-1]["resident_term"] == 0  # no manager
        pres = SimpleNamespace(get_residents_home_count=lambda: 2)
        hass.data[H.DOMAIN]["coordinator_manager"] = SimpleNamespace(
            coordinators={"presence": pres})
        await _tick(w, fam="1", ble={"oji_udezue": "living_room"})
        assert fake.calls[-1]["resident_term"] == 2
        pres.get_residents_home_count = lambda: 1 / 0
        await _tick(w, fam="1", ble={"oji_udezue": "living_room"})
        assert fake.calls[-1]["resident_term"] == 1  # error -> identified
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_missing_vision_object_case_d(mods, hass, monkeypatch, freezer):  # noqa: F811
    w = await _world(mods, hass, monkeypatch, freezer, fake=None, lead=True)
    try:
        hass.data[H.DOMAIN].pop(mods.const.CROSSING_VISION_HASS_KEY, None)
        house = await _tick(w, fam="2")
        assert house.unidentified_count == 2
        assert (house.aware_guests, house.count_provenance, house.aware_agreement,
                house.aware_vision_status) == (2, "camera", "single_source", "switch_off")
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_estimate_exception_case_d(mods, hass, monkeypatch, freezer):  # noqa: F811
    class _Boom(H.FakeVision):
        def census_tick(self, **kw):
            raise RuntimeError("ledger down")

    w = await _world(mods, hass, monkeypatch, freezer, fake=_Boom(9), lead=True)
    try:
        house = await _tick(w, fam="2")
        assert (house.aware_guests, house.count_provenance,
                house.aware_agreement) == (2, "camera", "single_source")
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_unhealthy_ledger_is_missing_not_zero(mods, hass, monkeypatch,  # noqa: F811
                                                    freezer):
    """Rule 5: guest_vis 50 but healthy False -> case D (the camera value),
    never vision's 50 even with F-LEAD on."""
    w = await _world(mods, hass, monkeypatch, freezer,
                     fake=H.FakeVision(50, healthy=False), lead=True)
    try:
        house = await _tick(w, fam="2")
        assert (house.aware_guests, house.aware_agreement,
                house.aware_vision_status) == (2, "single_source", "dark")
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_property_zone_unchanged(mods, hass, monkeypatch, freezer):  # noqa: F811
    w = await _world(mods, hass, monkeypatch, freezer, fake=H.FakeVision(5), lead=True)
    try:
        await _tick(w, fam="1")
        prop = w.census.last_result.property_exterior
        assert prop.aware_guests is None and prop.aware_total is None
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_same_face_as_leg_and_ble_counts_once(mods, hass, monkeypatch,  # noqa: F811
                                                    freezer):
    """INV-DEDUP (named): the same resident on BLE and a fresh face on the
    family-room camera is ONE identified person in both views."""
    w = await _world(mods, hass, monkeypatch, freezer, fake=H.FakeVision(0))
    try:
        house = await _tick(w, fam="1", face="Oji", ble={"oji_udezue": "living_room"},
                            persons={H.OJI: "home"})
        assert house.identified_count == 1
        assert house.aware_identified == house.identified_persons
        assert house.aware_total == 1
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_no_vision_identity_provenance_stamped(mods, hass, monkeypatch,  # noqa: F811
                                                     freezer):
    """INV-P2-IDENTITY: the identified count / persons are the same whatever
    the ledger says (0 vs 50, F-LEAD on); vision never adds a name."""
    out = []
    for gv in (0, 50):
        w = await _world(mods, hass, monkeypatch, freezer, fake=H.FakeVision(gv), lead=True)
        try:
            house = await _tick(w, fam="2", ble={"oji_udezue": "living_room"},
                                persons={H.OJI: "home"})
            out.append((house.identified_count, list(house.identified_persons),
                        list(house.aware_identified)))
        finally:
            await H.R.teardown(w.rig)
    assert out[0] == out[1] == (1, ["oji_udezue"], ["oji_udezue"])
    assert mods.const.IDENTITY_PROVENANCE_VISION  # KEEP + DOCUMENT, unused


@pytest.mark.asyncio
async def test_get_house_census_awareness_reads_aware_fields(  # noqa: F811
    mods, hass, monkeypatch, freezer,
):
    w = await _world(mods, hass, monkeypatch, freezer, fake=H.FakeVision(4), lead=True)
    try:
        await _tick(w, fam="1", ble={"oji_udezue": "living_room"}, persons={H.OJI: "home"})
        p = w.presence
        a = p.get_house_census("awareness")
        t = p.get_house_census("trust")
        assert (a.view, a.identified, a.unidentified_or_guests, a.total,
                a.provenance, a.agreement, a.vision_status, a.ledger_state) == (
            "awareness", 1, 4, 5, "vision", "disagree", "ok", "known")
        assert (t.view, t.identified, t.unidentified_or_guests, t.total,
                t.provenance, t.vision_status) == ("trust", 1, 0, 1, "camera", None)
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_boot_seed_ignores_vision_sensors(mods, hass, monkeypatch):  # noqa: F811
    """INV-P2-AWAY-LATENCY choke point 4: the presence boot seed reads the
    trust identified sensor, never the awareness entities (at 50)."""
    rig = await H.R.build(mods, hass, monkeypatch, setup=False)
    try:
        hass.data[H.DOMAIN].pop("census", None)
        hass.states.async_set(
            "sensor.universal_room_automation_identified_persons_in_house", "2")
        hass.states.async_set("sensor.ura_census_people_around", "50")
        hass.states.async_set("sensor.ura_census_guests_around", "50")
        await hass.async_block_till_done()
        seen = []
        real = rig.presence._run_inference

        async def _spy(trigger):
            seen.append((trigger, rig.presence._census_count))
            await real(trigger)

        rig.presence._run_inference = _spy
        await rig.presence.async_setup()
        assert seen[0] == ("startup", 2)
        await rig.presence.async_teardown()
    finally:
        await H.R.teardown(rig)


@pytest.mark.asyncio
async def test_dark_latch_reaches_ledger(mods, hass, monkeypatch, freezer):  # noqa: F811
    """Review C H1 (hop 1, CC07): once the REAL camera-dark hysteresis
    latches on a blind fleet, the next census_tick hands the ledger
    camera_input_dark=True (never a hard-coded False)."""
    fake = H.FakeVision(0)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake)
    try:
        await _tick(w, fam="0", mas="0")
        assert fake.calls[-1]["camera_input_dark"] is False
        for _ in range(12):
            freezer.tick(30)
            await _tick(w, fam="unavailable", mas="unavailable")
            if w.census._camera_input_dark_latched:
                break
        assert w.census._camera_input_dark_latched is True
        freezer.tick(30)
        await _tick(w, fam="unavailable", mas="unavailable")
        assert fake.calls[-1]["camera_input_dark"] is True
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_resident_term_identified_above_presence(mods, hass, monkeypatch,  # noqa: F811
                                                       freezer):
    """Review C M2 (CC03): presence says 0 residents home but the census
    identifies one person (BLE): R = max(0, 1) = 1, so that identified
    person is never counted as a ledger guest."""
    fake = H.FakeVision(0)
    w = await _world(mods, hass, monkeypatch, freezer, fake=fake)
    try:
        hass.data[H.DOMAIN]["coordinator_manager"] = SimpleNamespace(
            coordinators={"presence": SimpleNamespace(get_residents_home_count=lambda: 0)})
        house = await _tick(w, fam="1", ble={"oji_udezue": "living_room"})
        assert house.identified_count == 1
        assert fake.calls[-1]["resident_term"] == 1
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_boot_seed_from_manager_reads_trust_total(mods, hass, monkeypatch):  # noqa: F811
    """Review C M3 (AW5): the boot seed from the census manager's
    last_result reads trust total_persons (2), never aware_total (50)."""
    rig = await H.R.build(mods, hass, monkeypatch, setup=False)
    try:
        hass.data[H.DOMAIN].pop("census", None)
        hass.data[H.DOMAIN]["camera_integration_manager"] = SimpleNamespace(
            last_result=SimpleNamespace(house=SimpleNamespace(
                total_persons=2, aware_total=50, aware_guests=48)))
        seen = []
        real = rig.presence._run_inference

        async def _spy(trigger):
            seen.append((trigger, rig.presence._census_count))
            await real(trigger)

        rig.presence._run_inference = _spy
        await rig.presence.async_setup()
        assert seen[0] == ("startup", 2)
        await rig.presence.async_teardown()
    finally:
        hass.data[H.DOMAIN].pop("camera_integration_manager", None)
        await H.R.teardown(rig)

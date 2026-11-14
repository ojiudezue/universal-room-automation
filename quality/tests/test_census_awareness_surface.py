"""Census deconfliction CD2 (awareness entities) + CD3 (downgrade switch,
class set) + INV-P2-AWARE-NO-TRUST surface checks.

REAL HA core, REAL census / presence / sensor / binary_sensor / switch
modules (shared sighting-rig scope), census driven through the replay
harness. Oracles are literals.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import _census_vision_harness as H
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

PKG = "custom_components.universal_room_automation"
SWITCH = "switch.ura_crossing_vision_census_authority"
PEOPLE = "sensor.ura_census_people_around"
GUESTS = "sensor.ura_census_guests_around"


def _sensor_mod():
    return importlib.import_module(f"{PKG}.sensor")


async def _world(mods, hass, monkeypatch, freezer, *, gv=3, healthy=True,  # noqa: F811
                 lead=False, switch="on", classes=frozenset({"display"})):
    freezer.move_to(H.START)
    w = await H.build(mods, hass, monkeypatch)
    hass.data[H.DOMAIN][mods.const.CROSSING_VISION_HASS_KEY] = H.FakeVision(
        gv, healthy=healthy)
    monkeypatch.setattr(mods.const, "CROSSING_VISION_AWARENESS_VISION_LEADS", lead)
    monkeypatch.setattr(mods.const, "CROSSING_VISION_CONSUMER_CLASSES", classes)
    if switch is not None:
        hass.states.async_set(SWITCH, switch)
    hass.data[H.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": w.presence}, house_state="home_day")
    return w


async def _tick(w, fam="2", mas="0"):
    hass = w.hass
    hass.states.async_set(H.FAM_COUNT, fam)
    hass.states.async_set(H.MAS_COUNT, mas)
    hass.states.async_set(H.R.FAMILY, "on" if fam != "0" else "off")
    hass.states.async_set(H.R.MASTER, "on" if mas != "0" else "off")
    hass.states.async_set(H.OJI, "home")
    w.pc.data = {"oji_udezue": {"location": "living_room"}}
    await hass.async_block_till_done()
    await w.census._async_update_census_locked()
    await hass.async_block_till_done()
    return w.census.last_result.house


def _entities(hass):
    s = _sensor_mod()
    entry = SimpleNamespace(entry_id="integ", data={}, options={})
    return (s.URACensusPeopleAroundSensor(hass, entry),
            s.URACensusGuestsAroundSensor(hass, entry))


# ------------------------------------------------------------------- CD2
@pytest.mark.asyncio
async def test_awareness_entities_equal_trust_dark(mods, hass, monkeypatch,  # noqa: F811
                                                   freezer):
    """Dark default (F-LEAD off): the awareness entities equal the trust
    values (people = persons_in_house, guests = unidentified) although the
    ledger says 3 guests; the disagreement shows in the attributes."""
    w = await _world(mods, hass, monkeypatch, freezer, gv=3)
    try:
        house = await _tick(w, fam="2")
        assert (house.identified_count, house.unidentified_count,
                house.total_persons) == (1, 1, 2)
        people, guests = _entities(hass)
        assert (people.native_value, guests.native_value) == (2, 1)
        assert people.entity_id == PEOPLE and guests.entity_id == GUESTS
        assert people.extra_state_attributes == {
            "count_provenance": "camera", "aware_agreement": "disagree",
            "vision_status": "ok", "ledger_state": "known"}
        assert set(people._unrecorded_attributes) == {
            "count_provenance", "aware_agreement", "vision_status", "ledger_state"}
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_awareness_entities_follow_vision_after_lead(mods, hass, monkeypatch,  # noqa: F811
                                                           freezer):
    w = await _world(mods, hass, monkeypatch, freezer, gv=3, lead=True)
    try:
        await _tick(w, fam="2")
        people, guests = _entities(hass)
        assert (people.native_value, guests.native_value) == (4, 3)
        assert people.extra_state_attributes["count_provenance"] == "vision"
        s = _sensor_mod()
        entry = SimpleNamespace(entry_id="integ", data={}, options={})
        # The trust entity does not move.
        assert s.URAPersonsInHouseSensor(hass, entry).native_value == 2
        assert s.URAUnidentifiedPersonsInHouseSensor(hass, entry).native_value == 1
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_awareness_entities_never_unknown(mods, hass, monkeypatch, freezer):  # noqa: F811
    w = await _world(mods, hass, monkeypatch, freezer, gv=3, lead=True)
    try:
        people, guests = _entities(hass)
        hass.data[H.DOMAIN].pop("census", None)
        assert (people.native_value, guests.native_value) == (0, 0)  # no census
        hass.data[H.DOMAIN]["census"] = w.census
        await _tick(w, fam="2")
        hass.data[H.DOMAIN].pop("coordinator_manager")
        # No presence: the census trust values (the camera estimate).
        assert (people.native_value, guests.native_value) == (2, 1)
        assert people.extra_state_attributes["vision_status"] is None
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_sensor_platform_registers_awareness_entities(mods, hass, monkeypatch):  # noqa: F811
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    s = _sensor_mod()
    agg = importlib.import_module(f"{PKG}.aggregation")
    c = mods.const

    async def _no_agg(*_a, **_k):
        return None

    # The whole-house aggregation block needs room coordinators; it runs
    # before the census list and is not under test here.
    monkeypatch.setattr(agg, "async_setup_aggregation_sensors", _no_agg)
    entry = MockConfigEntry(domain=c.DOMAIN, entry_id="integ_plat", data={
        c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION})
    entry.add_to_hass(hass)
    added: list = []
    await s.async_setup_entry(hass, entry, lambda ents, *a, **k: added.extend(ents))
    ids = {getattr(e, "entity_id", None) for e in added}
    assert {PEOPLE, GUESTS} <= ids


# ------------------------------------------------------------------- CD3
@pytest.mark.asyncio
@pytest.mark.parametrize("classes", [frozenset({"display"}),
                                     frozenset({"display", "notification"})],
                         ids=["display", "full_legal"])
async def test_switch_off_reads_trust(mods, hass, monkeypatch, freezer, classes):  # noqa: F811
    """Downgrade: switch OFF with F-LEAD on and classes promoted -> every
    class reads trust; the awareness entities show the trust values."""
    w = await _world(mods, hass, monkeypatch, freezer, gv=3, lead=True,
                     switch="off", classes=classes)
    try:
        await _tick(w, fam="2")
        for cls in ("display", "notification"):
            assert w.presence.view_for_class(cls) == "trust"
        people, guests = _entities(hass)
        assert (people.native_value, guests.native_value) == (2, 1)
        assert people.extra_state_attributes["vision_status"] is None
        hass.states.async_set(SWITCH, "on")
        assert (people.native_value, guests.native_value) == (4, 3)
        assert w.presence.view_for_class("notification") == (
            "awareness" if "notification" in classes else "trust")
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
async def test_ledger_unknown_awareness_is_camera(mods, hass, monkeypatch, freezer):  # noqa: F811
    """Config extreme: ledger unknown (guest_vis None) with F-LEAD on ->
    case D, the camera value, vision_status unknown_ledger."""
    w = await _world(mods, hass, monkeypatch, freezer, gv=None, lead=True)
    try:
        hass.data[H.DOMAIN][mods.const.CROSSING_VISION_HASS_KEY].ledger_state = "unknown"
        await _tick(w, fam="2")
        people, guests = _entities(hass)
        assert (people.native_value, guests.native_value) == (2, 1)
        assert people.extra_state_attributes["vision_status"] == "unknown_ledger"
    finally:
        await H.R.teardown(w.rig)


async def _restore_cases(sw_mod, C, hass, cases):
    class _St:
        def __init__(self, s):
            self.state = s

    sw = None
    for last, expect in cases:
        sw = sw_mod.CrossingVisionCensusAuthoritySwitch(hass, MagicMock())
        sw.async_write_ha_state = lambda: None

        async def _last(_v=last):
            return _St(_v) if _v is not None else None

        sw.async_get_last_state = _last
        hass.data.setdefault(C.DOMAIN, {})[C.CROSSING_VISION_AUTHORITY_HASS_KEY] = (
            not expect)
        await sw.async_added_to_hass()
        assert sw.is_on is expect, last
    return sw


@pytest.mark.asyncio
async def test_authority_switch_no_camera_install_defaults_off(mods, hass):  # noqa: F811
    """Operator 2026-11-14: no camera entity in the registry -> default OFF;
    a stored on / off wins. A disabled camera does not count."""
    from homeassistant.helpers import entity_registry as er

    sw_mod = importlib.import_module(f"{PKG}.switch")
    C = mods.const
    reg = er.async_get(hass)
    if not hasattr(reg, "entities"):  # bare test hass: load it
        await reg.async_load()
    # The module-scoped hass may carry cameras from earlier rigs: disable
    # them for this test and restore them afterwards.
    parked = [e.entity_id for e in list(reg.entities.values())
              if e.domain == "camera" and e.disabled_by is None]
    for eid in parked:
        reg.async_update_entity(eid, disabled_by=er.RegistryEntryDisabler.USER)
    try:
        reg.async_get_or_create(
            "camera", "test", "disabled_cam", suggested_object_id="disabled_cam",
            disabled_by=er.RegistryEntryDisabler.USER)
        sw = await _restore_cases(sw_mod, C, hass, (
            ("on", True), ("off", False), ("unavailable", False),
            ("unknown", False), (None, False)))
    finally:
        for eid in parked:
            reg.async_update_entity(eid, disabled_by=None)
    assert sw._attr_name == "Vision Assisted Census"
    assert sw.extra_state_attributes == {"description": (
        "Show people counts that include AI vision of door crossings. "
        "Off uses sensors only. Never affects Away, security or locks.")}


@pytest.mark.asyncio
async def test_authority_switch_default_on_restore_only_off(mods, hass):  # noqa: F811
    """Camera install (one enabled camera entity): default ON; a stored
    on / off wins."""
    from homeassistant.helpers import entity_registry as er

    sw_mod = importlib.import_module(f"{PKG}.switch")
    C = mods.const
    reg = er.async_get(hass)
    if not hasattr(reg, "entities"):  # bare test hass: load it
        await reg.async_load()
    reg.async_get_or_create(
        "camera", "test", "front_cam", suggested_object_id="front_cam")
    sw = await _restore_cases(sw_mod, C, hass, (
        ("on", True), ("off", False), ("unavailable", True),
        ("unknown", True), (None, True)))
    assert sw.entity_id == SWITCH
    await sw.async_turn_off()
    assert sw.is_on is False
    await sw.async_turn_on()
    assert sw.is_on is True
    hass.data[C.DOMAIN].pop(C.CROSSING_VISION_AUTHORITY_HASS_KEY)
    assert sw.is_on is True  # unset = the shipped default


@pytest.mark.asyncio
async def test_switch_platform_registers_authority_switch(mods, hass):  # noqa: F811
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    sw_mod = importlib.import_module(f"{PKG}.switch")
    C = mods.const
    e = MockConfigEntry(domain=C.DOMAIN, entry_id="cm_auth", data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_COORDINATOR_MANAGER})
    e.add_to_hass(hass)
    added: list = []
    await sw_mod.async_setup_entry(hass, e, lambda ents, *a, **k: added.extend(ents))
    hits = [x for x in added if type(x).__name__ == "CrossingVisionCensusAuthoritySwitch"]
    assert len(hits) == 1 and hits[0].entity_id == SWITCH


# ------------------------------------------- INV-P2-AWARE-NO-TRUST readers
@pytest.mark.asyncio
@pytest.mark.parametrize("gv", [0, 50, None], ids=["vis0", "vis50", "visNone"])
async def test_excluded_consumers_never_read_vision(mods, hass, monkeypatch,  # noqa: F811
                                                    freezer, gv):
    """Awareness values 0 / 50 / None at the census result, the read API
    and the awareness entity STATES (F-LEAD on, classes {display,
    notification}, switch ON): the existing census sensors (values and
    attributes), CensusMismatchSensor and the presence AWAY inputs equal the
    no-vision run."""
    async def _observe(vision):
        w = await _world(mods, hass, monkeypatch, freezer, gv=vision, lead=True,
                         classes=frozenset({"display", "notification"}))
        try:
            if vision is None:
                hass.data[H.DOMAIN].pop(mods.const.CROSSING_VISION_HASS_KEY)
            await _tick(w, fam="2")
            if vision is not None:
                hass.states.async_set(PEOPLE, str(1 + vision))
                hass.states.async_set(GUESTS, str(vision))
            s = _sensor_mod()
            entry = SimpleNamespace(entry_id="integ", data={}, options={})
            trust = [s.URAPersonsInHouseSensor(hass, entry),
                     s.URAIdentifiedPersonsInHouseSensor(hass, entry),
                     s.URAUnidentifiedPersonsInHouseSensor(hass, entry),
                     s.URATotalPersonsOnPropertySensor(hass, entry)]
            values = [t.native_value for t in trust]
            attrs = {k: v for k, v in trust[0].extra_state_attributes.items()
                     if k not in ("count_as_of",)}
            hass.states.async_set("sensor.universal_room_automation_persons_in_house",
                                  str(values[0]))
            hass.states.async_set("sensor.universal_room_automation_census_confidence",
                                  "high")
            bs = importlib.import_module(f"{PKG}.binary_sensor")
            mm = bs.CensusMismatchSensor(hass, SimpleNamespace(entry_id="integ",
                                                               data={}, options={}))
            p = w.presence
            presence = (p._census_count, p._unidentified_count,
                        p._face_recognized_count, p._census_camera_input_dark)
            return values, attrs, mm.is_on, presence
        finally:
            await H.R.teardown(w.rig)

    with_vision = await _observe(gv)
    hass.states.async_remove(PEOPLE)
    hass.states.async_remove(GUESTS)
    baseline = await _observe(None)
    assert with_vision == baseline

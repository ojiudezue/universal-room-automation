"""PERSON-AWARENESS-READ-API-1 ship 1 (RA1-RA5).

Plan: docs/planning/PLANNING_person_awareness_read_api.md.

REAL Home Assistant core (phcc) and the REAL URA modules (imported fresh by
the shared sighting rig, scoped and restored). Oracles are hand-derived:
the slugs are written out literally (``oji_udezue``), the thresholds are the
literal doctrine values (0.75 / 0.9, manual §5.5), never the imported
constants.

Config shapes (INV-ID-ONE-RULE):
  * DISPLAY: the config-flow form, ``entry.data["tracked_persons"]`` holds
    display names (``'Oji Udezue'``), no options.
  * LIVE: ``entry.data`` display names AND ``entry.options`` entity ids
    (``'person.oji_udezue'``); the merged read takes the options (the
    live install as of 2026-10-24, see test_census_ble_over_face).
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import _sighting_rig as R
from test_interior_paths import tr  # noqa: F401 — fixture reuse (real tracker)
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"

OJI, EZ = "Oji Udezue", "Ezinne Udezue"
OJI_E, EZ_E = "person.oji_udezue", "person.ezinne_udezue"
# Hand-written oracle: the URA slugs every residual must return.
SLUGS = ["oji_udezue", "ezinne_udezue"]

CONFIGS = {
    "display": ({"tracked_persons": [OJI, EZ]}, {}),
    "live_entity": ({"tracked_persons": [OJI, EZ]},
                    {"tracked_persons": [OJI_E, EZ_E]}),
}


def _ids():
    return importlib.import_module(f"{PKG}.person_ids")


def _integ(mods, data, options):
    c = mods.const
    return SimpleNamespace(
        entry_id="integ",
        data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION, **data},
        options=dict(options),
    )


def _census(mods, hass):
    er_, dr_ = R.registries()
    mgr = R._Mgr(mods.resolver.CameraResolver(er_, dr_, state_getter=hass.states.get))
    census = mods.census.PersonCensus(hass, mgr)
    hass.data.setdefault(DOMAIN, {})["census"] = census
    return census


# ---------------------------------------------------------------- RA4 rule
def test_slug_of_display_of_roundtrip(mods):
    ids = _ids()
    assert ids.slug_of("Oji Udezue") == "oji_udezue"
    assert ids.slug_of("person.oji_udezue") == "oji_udezue"
    assert ids.slug_of("  person.oji_udezue ") == "oji_udezue"
    assert ids.slug_of("oji_udezue") == "oji_udezue"
    assert ids.slug_of(None) == ""
    assert ids.slug_of("   ") == ""
    assert ids.display_of("oji_udezue") == "Oji Udezue"
    assert ids.display_of("person.ezinne_udezue") == "Ezinne Udezue"
    for s in SLUGS:
        assert ids.slug_of(ids.display_of(s)) == s
    assert ids.tracked_person_entity_id("Oji Udezue") == "person.oji_udezue"
    assert ids.tracked_person_entity_id("person.oji_udezue") == "person.oji_udezue"
    # REUSE: the person coordinator's rule IS this rule (one object).
    pc = importlib.import_module(f"{PKG}.person_coordinator")
    assert pc.tracked_person_entity_id is ids.tracked_person_entity_id


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", sorted(CONFIGS))
@pytest.mark.parametrize("residual", ["A", "B", "C", "D"])
async def test_residuals_same_slug_display_and_entity_config(
    mods, hass, monkeypatch, cfg, residual,
):
    data, options = CONFIGS[cfg]
    R.install_entries(hass, monkeypatch, [_integ(mods, data, options)])
    census = _census(mods, hass)
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)

    if residual == "A":
        assert census._get_tracked_person_slugs() == SLUGS

    elif residual == "B":
        # Oji's phone is on the guest SSID. It is a family tracker only if
        # the tracked entry resolves to person.oji_udezue -> 0 guests.
        data_ssid = {mods.const.CONF_GUEST_VLAN_SSID: "Revel"}
        R.install_entries(hass, monkeypatch, [_integ(mods, {**data, **data_ssid}, options)])
        hass.states.async_set(OJI_E, "home", {"device_trackers": ["device_tracker.oji_phone"]})
        hass.states.async_set(EZ_E, "home", {"device_trackers": []})
        hass.states.async_set("device_tracker.oji_phone", "home", {
            "source_type": "router", "essid": "Revel", "host_name": "zz-phone-b7",
        })
        assert census._get_wifi_guest_count(dt_util_now()) == 0

    elif residual == "C":
        face = "sensor.frigate_oji_last_camera_2"
        monkeypatch.setattr(
            census, "_resolve_last_camera_entity_id",
            lambda slug: face if str(slug).lower().startswith("oji") else None,
        )
        hass.states.async_set(face, "garage_a")
        hass.states.async_set(OJI_E, "home")
        assert census._get_face_recognized_person_names(dt_util_now()) == ["oji_udezue"]

    else:  # D
        mgr = mods.perimeter.PerimeterAlertManager.__new__(
            mods.perimeter.PerimeterAlertManager)
        mgr.hass = hass
        assert mgr._tracked_person_slugs() == SLUGS
    del now


def dt_util_now():
    from homeassistant.util import dt as dt_util
    return dt_util.utcnow()


# ---------------------------------------------------------------- RA3 table
@pytest.mark.asyncio
async def test_class_thresholds_unchanged(mods, hass, monkeypatch):
    """0.75 (notification naming) and 0.9 (security floor) equal develop at
    both call sites. Literals, not the constants."""
    # Site 1: EgressDirectionTracker._arrival_departure_notify.
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    hass.data[DOMAIN] = {"notification_manager": nm}
    t = mods.transit.EgressDirectionTracker(hass)
    titles = []
    for conf in (0.75, 0.7499, 0.7, 0.6):
        nm.async_notify.reset_mock()
        t._arrival_departure_notify("entry", "oji_udezue", conf)
        await hass.async_block_till_done()
        titles.append(nm.async_notify.await_args.kwargs["title"])
    assert titles == ["Oji Udezue arrived", "Someone arrived",
                      "Someone arrived", "Someone arrived"]

    # Site 2: PerimeterAlertManager._known_identity_for (security floor),
    # through the real census tracked list (display-name config).
    R.install_entries(hass, monkeypatch, [_integ(mods, *CONFIGS["display"])])
    _census(mods, hass)
    mgr = mods.perimeter.PerimeterAlertManager.__new__(mods.perimeter.PerimeterAlertManager)
    mgr.hass = hass
    edge = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    got = {}
    for conf in (0.9, 0.8999):
        mgr._recent_egress_identity = {"garage_a": [(edge, "oji_udezue", conf, False)]}
        got[conf] = mgr._known_identity_for("garage_a", edge)
    assert got[0.9] == ("oji_udezue", 0.9, "egress_event")
    assert got[0.8999] is None
    # The doctrine floor holds even when the perimeter knob is set below it
    # (the knob is clamped up to 0.9, manual §5.5(a)).
    monkeypatch.setattr(mods.perimeter, "PERIMETER_EGRESS_KNOWN_MIN_CONF", 0.8)
    mgr._recent_egress_identity = {"garage_a": [(edge, "oji_udezue", 0.85, False)]}
    assert mgr._known_identity_for("garage_a", edge) is None
    mgr._recent_egress_identity = {"garage_a": [(edge, "oji_udezue", 0.9, False)]}
    assert mgr._known_identity_for("garage_a", edge) == ("oji_udezue", 0.9, "egress_event")


def test_consumer_class_table_values(mods):
    t = mods.const.CONSUMER_CLASS_MIN_CONFIDENCE
    assert dict(t) == {"security": 0.9, "notification": 0.75, "display": 0.0}
    with pytest.raises(TypeError):
        t["security"] = 0.5  # read-only doctrine


def test_consumer_classes_rejects_illegal(mods):
    c = mods.const
    with pytest.raises(ValueError):
        c.validate_consumer_classes({"security"}, {"display", "notification"})
    with pytest.raises(ValueError):
        c.validate_consumer_classes({"display", "comfort"}, {"display", "notification"})
    assert c.validate_consumer_classes({"display"}, {"display", "notification"}) == {"display"}
    # The shipped set is legal (else the import would have raised).
    assert c.CROSSING_VISION_CONSUMER_CLASSES == frozenset({"display"})
    assert c.CROSSING_VISION_LEGAL_CONSUMER_CLASSES == frozenset({"display", "notification"})


# ---------------------------------------------------------------- RA2
SWITCH = "switch.ura_crossing_vision_census_authority"
CLASS_SETS = [frozenset(), frozenset({"display"}), frozenset({"display", "notification"}),
              frozenset({"security", "display", "house_state", "comfort", "hvac"})]
SWITCH_VALUES = [None, "on", "off", "unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("class_set", CLASS_SETS, ids=lambda s: "+".join(sorted(s)) or "empty")
@pytest.mark.parametrize("switch", SWITCH_VALUES, ids=str)
async def test_view_for_class_security_always_trust(mods, hass, monkeypatch, class_set, switch):
    monkeypatch.setattr(mods.const, "CROSSING_VISION_CONSUMER_CLASSES", class_set)
    if switch is not None:
        hass.states.async_set(SWITCH, switch)
    p = mods.presence.PresenceCoordinator(hass)
    for cls in ("house_state", "security", "hvac", "comfort", "", "Display",
                "suggestion", None, 3):
        assert p.view_for_class(cls) == "trust", (cls, class_set, switch)


@pytest.mark.asyncio
async def test_view_for_class_display_follows_class_set(mods, hass, monkeypatch):
    p = mods.presence.PresenceCoordinator(hass)
    monkeypatch.setattr(mods.const, "CROSSING_VISION_CONSUMER_CLASSES", frozenset({"display"}))
    assert p.view_for_class("display") == "trust"  # switch missing
    hass.states.async_set(SWITCH, "on")
    assert p.view_for_class("display") == "awareness"
    assert p.view_for_class("notification") == "trust"  # legal, not active
    hass.states.async_set(SWITCH, "off")
    assert p.view_for_class("display") == "trust"
    hass.states.async_set(SWITCH, "on")
    monkeypatch.setattr(mods.const, "CROSSING_VISION_CONSUMER_CLASSES",
                        frozenset({"display", "notification"}))
    assert p.view_for_class("notification") == "awareness"
    monkeypatch.setattr(mods.const, "CROSSING_VISION_CONSUMER_CLASSES", frozenset())
    assert p.view_for_class("display") == "trust"


# ---------------------------------------------------------------- RA1
def _house(mods, **kw):
    base = dict(zone="house", identified_count=2, identified_persons=list(SLUGS),
                unidentified_count=1, total_persons=3, confidence="high",
                source_agreement="close", frigate_count=3, unifi_count=2,
                timestamp=datetime(2026, 11, 13, 11, 59, 30))
    base.update(kw)
    return mods.census.CensusZoneResult(**base)


@pytest.mark.asyncio
async def test_get_house_census_trust_equals_last_result(mods, hass, monkeypatch):
    R.install_entries(hass, monkeypatch, [_integ(mods, *CONFIGS["live_entity"])])
    census = _census(mods, hass)
    prop = _house(mods, zone="property", identified_count=0, identified_persons=[],
                  unidentified_count=1, total_persons=1)
    census._last_result = mods.census.FullCensusResult(
        house=_house(mods), property_exterior=prop, total_on_property=4,
        ble_persons=list(SLUGS), face_persons=[], persons_outside=1,
    )
    p = mods.presence.PresenceCoordinator(hass)
    p._census_count = 99  # never read by the API
    v = p.get_house_census("trust")
    assert (v.view, v.identified, v.unidentified_or_guests, v.total, v.agreement,
            v.as_of) == ("trust", 2, 1, 3, "close", datetime(2026, 11, 13, 11, 59, 30))
    a = p.get_house_census("awareness")
    assert (a.view, a.identified, a.unidentified_or_guests, a.total, a.provenance) == (
        "awareness", 2, 1, 3, "camera")
    with pytest.raises(Exception):
        v.total = 5  # frozen


@pytest.mark.asyncio
async def test_get_house_census_missing_census_none(mods, hass):
    p = mods.presence.PresenceCoordinator(hass)
    assert p.get_house_census("trust") is None  # no DOMAIN data
    hass.data[DOMAIN] = {}
    assert p.get_house_census("trust") is None  # no census
    hass.data[DOMAIN]["census"] = SimpleNamespace(last_result=None)
    assert p.get_house_census("awareness") is None  # no result yet

    class _Boom:
        @property
        def last_result(self):
            raise RuntimeError("boom")
    hass.data[DOMAIN]["census"] = _Boom()
    assert p.get_house_census("trust") is None  # never raises


# ---------------------------------------------------------------- RA5
@pytest.mark.asyncio
async def test_get_last_crossing_matches_bus_event(tr, hass, mods):  # noqa: F811
    from homeassistant.util import dt as dt_util
    cam = "binary_sensor.garage_a_person_occupancy_2"
    tr._interior_neighbours_by_group = {"garage_a": ["binary_sensor.staircase_person_occupancy"]}
    tr._interior_entities = ["binary_sensor.staircase_person_occupancy"]
    p = mods.presence.PresenceCoordinator(hass)
    assert tr.get_last_crossing() is None
    assert p.get_last_crossing() is None
    t = dt_util.utcnow()
    tr._recent_interior_events = {"binary_sensor.staircase_person_occupancy": [t + timedelta(seconds=5)]}
    fired = []
    unsub = hass.bus.async_listen("ura_person_egress_event", lambda e: fired.append(dict(e.data)))
    await tr._resolve_direction(cam, t)
    await hass.async_block_till_done()
    unsub()
    assert len(fired) == 1
    ev = fired[0]
    rec = tr.get_last_crossing()
    assert rec is not None
    assert (rec.camera, rec.direction, rec.ts.isoformat(), rec.person_id,
            rec.provenance, rec.confidence, rec.identity_confidence) == (
        ev["egress_camera"], ev["direction"], ev["timestamp"], ev["person_id"],
        ev["identity_provenance"], ev["confidence"], ev["identity_confidence"])
    assert rec.direction == "entry"
    assert rec.source_ref == f"egress:{cam}:{t.isoformat()}"
    assert tr.get_last_crossing(cam) is rec
    assert tr.get_last_crossing("binary_sensor.garage_b_person_occupancy") is None
    # Presence wrapper reads the same record.
    assert p.get_last_crossing() is rec
    assert p.get_last_crossing(cam) is rec
    assert p.get_last_arrival_record() is None


# ---------------------------------------------------------------- fix-up (reviews A/B/C)
def _identity_resolution(mods, direction="entry"):
    """A resolved identity: Oji at 0.8 by BLE+face (hand-written oracle)."""
    res = mods.transit.EgressResolution(
        outcome="attached", direction=direction, agreement="agree",
        slug="oji_udezue", identity_confidence=0.8, provenance="ble+face",
    )
    return ("oji_udezue", 0.8, "agree", res)


async def _cross_with_identity(tr, hass, mods, monkeypatch):  # noqa: F811
    from homeassistant.util import dt as dt_util
    cam = "binary_sensor.garage_a_person_occupancy_2"
    tr._interior_neighbours_by_group = {"garage_a": ["binary_sensor.staircase_person_occupancy"]}
    tr._interior_entities = ["binary_sensor.staircase_person_occupancy"]
    monkeypatch.setattr(tr, "_resolve_egress_face_identity_ex",
                        lambda *a, **k: _identity_resolution(mods))
    t = dt_util.utcnow()
    tr._recent_interior_events = {"binary_sensor.staircase_person_occupancy": [t + timedelta(seconds=5)]}
    fired = []
    unsub = hass.bus.async_listen("ura_person_egress_event", lambda e: fired.append(dict(e.data)))
    await tr._resolve_direction(cam, t)
    await hass.async_block_till_done()
    unsub()
    return cam, t, fired


@pytest.mark.asyncio
async def test_crossing_record_with_identity_equals_bus_event(tr, hass, mods, monkeypatch):  # noqa: F811
    """Review C must-fix 1: the identity half of the CrossingRecord."""
    cam, t, fired = await _cross_with_identity(tr, hass, mods, monkeypatch)
    assert len(fired) == 1
    ev = fired[0]
    rec = tr.get_last_crossing(cam)
    # Hand oracle first, then equality with the bus event.
    assert (rec.person_id, rec.identity_confidence, rec.provenance, rec.direction) == (
        "oji_udezue", 0.8, "ble+face", "entry")
    assert (rec.person_id, rec.identity_confidence, rec.provenance) == (
        ev["person_id"], ev["identity_confidence"], ev["identity_provenance"])
    assert rec.source_ref == f"egress:{cam}:{t.isoformat()}"


@pytest.mark.asyncio
async def test_record_crossing_failure_does_not_break_notify(tr, hass, mods, monkeypatch):  # noqa: F811
    """Reviews A-L2 / B-L1: the observational store cannot break the emit."""
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    hass.data[DOMAIN]["notification_manager"] = nm

    def _boom(_rec):
        raise RuntimeError("store failed")
    monkeypatch.setattr(tr, "_record_crossing", _boom)
    _cam, _t, fired = await _cross_with_identity(tr, hass, mods, monkeypatch)
    assert len(fired) == 1
    assert nm.async_notify.await_args.kwargs["title"] == "Oji Udezue arrived"


class _FakeTracker:
    def __init__(self, result=None, exc=None):
        self.calls, self._result, self._exc = [], result, exc

    def get_last_crossing(self, camera=None):
        self.calls.append(camera)
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.mark.asyncio
async def test_presence_get_last_crossing_wrapper(mods, hass):
    """Review C must-fix 2: PresenceCoordinator.get_last_crossing."""
    p = mods.presence.PresenceCoordinator(hass)
    hass.data.pop(DOMAIN, None)
    assert p.get_last_crossing() is None  # no DOMAIN data
    hass.data[DOMAIN] = {}
    assert p.get_last_crossing("binary_sensor.x") is None  # no tracker
    sentinel = object()
    fake = _FakeTracker(result=sentinel)
    hass.data[DOMAIN]["egress_tracker"] = fake
    assert p.get_last_crossing("binary_sensor.garage_a_person_occupancy_2") is sentinel
    assert p.get_last_crossing() is sentinel
    assert fake.calls == ["binary_sensor.garage_a_person_occupancy_2", None]
    hass.data[DOMAIN]["egress_tracker"] = _FakeTracker(exc=RuntimeError("boom"))
    assert p.get_last_crossing("binary_sensor.x") is None  # never raises


@pytest.mark.asyncio
async def test_get_house_census_view_normalisation(mods, hass, monkeypatch):
    R.install_entries(hass, monkeypatch, [_integ(mods, *CONFIGS["live_entity"])])
    census = _census(mods, hass)
    prop = _house(mods, zone="property", identified_count=0, identified_persons=[],
                  unidentified_count=1, total_persons=1)
    census._last_result = mods.census.FullCensusResult(
        house=_house(mods), property_exterior=prop, total_on_property=4,
        ble_persons=list(SLUGS), face_persons=[], persons_outside=1,
    )
    p = mods.presence.PresenceCoordinator(hass)
    assert p.get_house_census("awareness").view == "awareness"
    for bad in ("AWARENESS", "aware", "bogus", "", None):
        v = p.get_house_census(bad)
        assert (v.view, v.identified, v.unidentified_or_guests, v.total) == (
            "trust", 2, 1, 3), bad


@pytest.mark.asyncio
async def test_view_for_class_error_reads_trust(mods, hass, monkeypatch):
    monkeypatch.setattr(mods.const, "CROSSING_VISION_CONSUMER_CLASSES", frozenset({"display"}))
    hass.states.async_set(SWITCH, "on")
    p = mods.presence.PresenceCoordinator(hass)
    assert p.view_for_class("display") == "awareness"  # precondition: promoted

    class _States:
        def get(self, _eid):
            raise RuntimeError("state machine down")
    p.hass = SimpleNamespace(states=_States(), data=hass.data)
    assert p.view_for_class("display") == "trust"


def test_const_import_time_class_validation_runs(mods):
    """The module-level validate_consumer_classes(...) call: load a fresh,
    unregistered copy of const with an illegal class promoted; the load
    must raise. (Shadows the module's `frozenset` name for this copy only.)"""
    import importlib.util
    import sys
    real = frozenset

    class _promote_security(real):  # subscriptable like frozenset[str]
        def __new__(cls, *args):
            s = real(*args)
            return real(s | {"security"}) if s == real({"display"}) else s

    name = "_ura_const_validation_probe"
    spec = importlib.util.spec_from_file_location(name, mods.const.__file__)
    probe = importlib.util.module_from_spec(spec)
    probe.__dict__["frozenset"] = _promote_security
    try:
        with pytest.raises(ValueError, match="security"):
            spec.loader.exec_module(probe)
    finally:
        sys.modules.pop(name, None)


def test_slug_of_entity_id_capitals_and_spaces(mods):
    ids = _ids()
    assert ids.slug_of("person.Oji_Udezue") == "oji_udezue"
    assert ids.slug_of(" person.oji ") == "oji"
    assert ids.slug_of("person. oji") == "oji"


@pytest.mark.asyncio
async def test_canonical_person_slug_public(mods, hass, monkeypatch):
    """Plan RA4 makes the face first-name mapper public (ship 2 consumers)."""
    R.install_entries(hass, monkeypatch, [_integ(mods, *CONFIGS["live_entity"])])
    census = _census(mods, hass)
    assert census.canonical_person_slug("Oji") == "oji_udezue"
    assert census.canonical_person_slug("Oji Udezue") == "oji_udezue"
    assert census.canonical_person_slug(None) == ""

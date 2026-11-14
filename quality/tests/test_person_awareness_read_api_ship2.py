"""PERSON-AWARENESS-READ-API-1 ship 2 (RA6-RA10), INV-RA-BYTE-IDENTICAL.

Plan: docs/planning/PLANNING_person_awareness_read_api.md §5 ship 2.

Every migrated reader keeps its output under the live config (display names in
``entry.data``, entity ids in ``entry.options``). Each test drives the REAL
production function (real modules, imported fresh by the sighting rig, scoped
and restored) and compares it with a hand-written literal oracle (the old
inline expression written out by hand, never re-run from production code).
The per-site mutation drills are listed in the README draft
(docs/readmes/README_person_awareness_read_api_ship2_DRAFT.md).
"""
from __future__ import annotations

import ast
import importlib
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"
_ROOT = pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"


def _m(name):
    return importlib.import_module(f"{PKG}.{name}")


class _States:
    def __init__(self, states=None):
        self.map = dict(states or {})
        self.reads: list[str] = []

    def get(self, eid):
        self.reads.append(eid)
        v = self.map.get(eid)
        if v is None:
            return None
        if isinstance(v, str):
            return SimpleNamespace(state=v, attributes={})
        return v


def _hass(states=None, data=None):
    return SimpleNamespace(states=_States(states), data={DOMAIN: dict(data or {})})


# =========================================================================
# RA9 — the id copies
# =========================================================================
@pytest.mark.parametrize("name, want", [
    ("Oji Udezue", "oji_udezue"),
    ("Ziri", "ziri"),
    (" Oji ", "_oji_"),  # no strip: frozen legacy rule
    ("person.Oji Udezue", "person.oji_udezue"),  # no prefix handling
    ("", ""),
])
def test_entity_key_slug_is_the_frozen_legacy_rule(mods, name, want):
    assert _m("person_ids").entity_key_slug(name) == want


def test_entity_key_slug_none_raises_like_the_inline_copies(mods):
    with pytest.raises(AttributeError):
        _m("person_ids").entity_key_slug(None)


def _ptc(mods, overruled, states, location="away"):
    pc_mod = _m("person_coordinator")
    pc = pc_mod.PersonTrackingCoordinator.__new__(pc_mod.PersonTrackingCoordinator)
    pc.hass = _hass(states)
    pc._gps_home_overruled = frozenset(overruled)
    pc._ble_leads_enabled = lambda: True
    pc.get_person_location = lambda name: location
    return pc


@pytest.mark.parametrize("entry", ["Oji Udezue", "person.oji_udezue"])
def test_effective_person_state_overrule_matches_display_and_entity_entry(mods, entry):
    """RA9 (Review A A-I1): the display entry (live) is byte-identical; an
    entity-id entry used to build ``person.person.oji_udezue`` and never
    matched, so the overrule silently did nothing."""
    pc = _ptc(mods, [entry], {"person.oji_udezue": "home"})
    assert pc.effective_person_state("person.oji_udezue") == "not_home"
    # location not away -> raw state
    pc2 = _ptc(mods, [entry], {"person.oji_udezue": "home"}, location="Office")
    assert pc2.effective_person_state("person.oji_udezue") == "home"


def test_find_person_entity_display_and_entity_entry(mods):
    pc = _ptc(mods, [], {"person.oji_udezue": "home"})
    assert pc._find_person_entity("Oji Udezue") == "person.oji_udezue"
    assert pc._find_person_entity("person.oji_udezue") == "person.oji_udezue"
    assert pc._find_person_entity("Nobody") is None


def test_arrival_edges_slug_rules_unchanged(mods):
    ae = _m("arrival_edges")
    new = SimpleNamespace(state="home")
    old = SimpleNamespace(state="not_home")
    assert ae.live_arrival_slug({"entity_id": "person.oji_udezue",
                                 "new_state": new, "old_state": old}) == "oji_udezue"
    assert ae.live_arrival_slug({"entity_id": "person.Ziri",
                                 "new_state": new, "old_state": old}) == "ziri"
    assert ae.live_arrival_slug({"entity_id": "",
                                 "new_state": new, "old_state": old}) is None
    lc = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    rec = {"method": "bermuda", "location": "Foyer", "previous_location": "Garage",
           "bermuda_area": "foyer", "last_changed": lc}
    pc_data = {"Oji Udezue": rec}
    assert ae.bermuda_arrival_into(pc_data, "oji_udezue", {"foyer"}, lc.timestamp(), 120.0, 0.0)
    assert not ae.bermuda_arrival_into(pc_data, "ezinne", {"foyer"}, lc.timestamp(), 120.0, 0.0)
    stamps: dict = {}
    assert ae.record_bermuda_moves(pc_data, stamps) == {"oji_udezue"}
    assert list(stamps) == ["oji_udezue"]


@pytest.mark.parametrize("value, want", [
    ("person.oji_udezue", "oji udezue"),
    ("Oji Udezue", "oji udezue"),
    ("oji_udezue", "oji udezue"),
    ("", ""),
    (None, ""),
])
def test_music_person_key_unchanged(mods, value, want):
    assert _m("music_following")._person_key(value) == want


def test_notification_person_name_display_fallback(mods):
    nm_mod = _m("domain_coordinators.notification_manager")
    nm = nm_mod.NotificationManager.__new__(nm_mod.NotificationManager)
    nm.hass = _hass({"person.ziri": SimpleNamespace(state="home",
                                                    attributes={"friendly_name": "Ziri U"})})
    assert nm._get_person_name("person.oji_udezue") == "Oji Udezue"
    assert nm._get_person_name("person.ziri") == "Ziri U"
    assert nm._get_person_name(None) == "someone"


def test_perimeter_followup_person_name(mods):
    pa = mods.perimeter.PerimeterAlertManager.__new__(mods.perimeter.PerimeterAlertManager)
    pa.hass = _hass({})
    assert pa._followup_person_name("oji_udezue") == "Oji Udezue"


def test_phone_left_behind_unique_id_and_lookups_share_the_key(mods):
    bs = _m("binary_sensor")
    s = bs.PersonPhoneLeftBehindSensor(_hass(), SimpleNamespace(entry_id="e"),
                                       "Oji Udezue", "person.oji_udezue")
    assert s._attr_unique_id == f"{DOMAIN}_person_oji_udezue_phone_left_behind"


@pytest.mark.parametrize("reader", ["presence", "ble_corroboration"])
def test_phone_left_behind_readers_look_up_the_same_unique_id(mods, monkeypatch, reader):
    asked: list[str] = []

    class _Reg:
        def async_get_entity_id(self, domain, platform, unique_id):
            asked.append(unique_id)
            return "binary_sensor.plb_oji"

    from homeassistant.helpers import entity_registry as er
    monkeypatch.setattr(er, "async_get", lambda _h: _Reg())
    hass_ = _hass({"binary_sensor.plb_oji": "on"})
    if reader == "presence":
        pres = mods.presence.PresenceCoordinator.__new__(mods.presence.PresenceCoordinator)
        pres.hass = hass_
        assert pres._phone_left_behind_on("Oji Udezue") is True
    else:
        bc = _m("domain_coordinators._ble_corroboration")
        monkeypatch.setattr(bc.er, "async_get", lambda _h: _Reg())
        assert bc.phone_trustworthy(hass_, "Oji Udezue") is False
    assert asked == [f"{DOMAIN}_person_oji_udezue_phone_left_behind"]


def test_transit_notify_title_name(mods, monkeypatch):
    """The arrival/departure title name is display_of(slug) == the old
    ``replace('_', ' ').title()`` for every slug the census produces."""
    ids = _m("person_ids")
    for slug, want in (("oji_udezue", "Oji Udezue"), ("ziri", "Ziri"), ("jaya", "Jaya")):
        assert ids.display_of(slug) == want


# =========================================================================
# RA10 — one F5 payload type
# =========================================================================
def test_person_arriving_payload_from_signal_dict_and_object(mods):
    P = mods.signals.PersonArrivingPayload
    sighting = object()
    d = P.from_signal({"person_entity": "person.oji_udezue", "source": "camera_face",
                       "sighting": sighting, "zone": "Upstairs"})
    o = P.from_signal(SimpleNamespace(person_entity="person.oji_udezue", source="camera_face",
                                      sighting=sighting, zone="Upstairs"))
    assert d == o == P("person.oji_udezue", "camera_face", sighting, "Upstairs")
    assert P.from_signal({"person_entity": "person.x", "source": "ble"}) == P("person.x", "ble", None, "")
    assert P.from_signal({}) == P("", None, None, "")
    assert P.from_signal(SimpleNamespace(person_entity="person.x")) == P("person.x", None, None, "")
    assert P.from_signal(None) is None
    assert P.from_signal(object()) is None
    assert P.from_signal({"person_entity": None}).person_entity is None  # verbatim


def _lock_regime_probe(mods):
    """Real SecurityLockRegime.on_person_arriving up to its first
    payload-dependent call (the PC listener), recorded."""
    lr = _m("domain_coordinators.security_lock_regime")
    regime = lr.LockRegimeController.__new__(lr.LockRegimeController)
    regime._torn_down = False
    seen: list = []

    def _ensure():
        seen.append("listener")
        raise _Stop()

    regime._ensure_pc_listener = _ensure
    return regime, seen


class _Stop(Exception):
    pass


@pytest.mark.parametrize("payload, reaches", [
    ({"person_entity": "person.oji_udezue", "source": "ble"}, True),
    (SimpleNamespace(person_entity="person.oji_udezue", source="ble"), True),
    ({"person_entity": ""}, False),
    (SimpleNamespace(person_entity=None), False),
    (object(), False),
    (None, False),
])
def test_lock_regime_reads_the_normalised_payload(mods, payload, reaches):
    regime, seen = _lock_regime_probe(mods)
    if reaches:
        with pytest.raises(_Stop):
            regime.on_person_arriving(payload)
    else:
        regime.on_person_arriving(payload)
    assert seen == (["listener"] if reaches else [])


@pytest.mark.parametrize("payload, want", [
    ({"person_entity": "person.oji_udezue", "source": "geofence"}, "person.oji_udezue"),
    (SimpleNamespace(person_entity="person.oji_udezue", source="geofence"), "person.oji_udezue"),
    ({"source": "geofence"}, None),
    (object(), None),
])
def test_security_arrival_handler_reads_person_from_either_shape(mods, payload, want):
    sec_mod = mods.security
    sc = sec_mod.SecurityCoordinator.__new__(sec_mod.SecurityCoordinator)
    sc._lock_regime = None
    sc._enabled = True
    sc._observation_mode = False
    asked: list = []

    def _cfg(key):
        asked.append(key)
        return False  # stop right after the person read

    sc._get_signal_config = _cfg
    type(sc).observation_mode = property(lambda self: False)
    sc._handle_person_arriving_signal(payload)
    assert (len(asked) == 1) is (want is not None)


# =========================================================================
# RA8 — F1 per-zone helper
# =========================================================================
def test_persons_home_for_trust_order_and_strict_home(mods):
    pc_mod = _m("person_coordinator")
    h = _hass({"person.a": "home", "person.b": "not_home", "person.c": "home",
               "person.d": "unknown"})
    assert pc_mod.persons_home_for_trust(h, ["person.c", "person.b", "person.a", "person.d", "person.x"]) == ["person.c", "person.a"]
    assert pc_mod.persons_home_for_trust(h, None) == []
    assert pc_mod.persons_home_for_trust(h, []) == []
    h.states.reads.clear()
    assert pc_mod.first_person_home_for_trust(h, ["person.b", "person.a", "person.c"]) == "person.a"
    assert h.states.reads == ["person.b", "person.a"]  # short-circuits
    assert pc_mod.first_person_home_for_trust(h, ["person.b"]) is None


def test_persons_home_for_trust_routes_through_the_overrule(mods):
    pc_mod = _m("person_coordinator")
    pc = SimpleNamespace(effective_person_state=lambda eid: "not_home" if eid == "person.a" else "home")
    h = _hass({"person.a": "home", "person.b": "home"}, {"person_coordinator": pc})
    assert pc_mod.persons_home_for_trust(h, ["person.a", "person.b"]) == ["person.b"]


def test_zone_has_home_person(mods):
    hz = _m("domain_coordinators.hvac_zones")
    zm = hz.ZoneManager.__new__(hz.ZoneManager)
    h = _hass({"person.a": "not_home", "person.b": "home"})
    assert zm.zone_has_home_person(SimpleNamespace(zone_persons=["person.a", "person.b"]), h) is True
    assert zm.zone_has_home_person(SimpleNamespace(zone_persons=["person.a"]), h) is False
    assert zm.zone_has_home_person(SimpleNamespace(zone_persons=None), h) is False


def test_get_residents_home_zone_persons_form_has_no_plb_cut(mods):
    pres = mods.presence.PresenceCoordinator.__new__(mods.presence.PresenceCoordinator)
    pres.hass = _hass({"person.a": "home", "person.b": "not_home"})
    pres._phone_left_behind_on = lambda _n: True  # would cut everyone on the no-arg form
    assert pres.get_residents_home(zone_persons=["person.a", "person.b"]) == frozenset({"person.a"})
    assert pres.get_residents_home(zone_persons=[]) == frozenset()


# =========================================================================
# RA7 — F2 readers on the one census read
# =========================================================================
def _zone_result(mods, *, total, identified, unidentified, confidence="high"):
    c = mods.const
    return mods.census.CensusZoneResult(
        zone="house", identified_count=identified, identified_persons=[],
        unidentified_count=unidentified, total_persons=total, confidence=confidence,
        source_agreement=c.CENSUS_AGREEMENT_SINGLE, frigate_count=total, unifi_count=0,
    )


def _census_with(house):
    return SimpleNamespace(last_result=SimpleNamespace(house=house))


def test_census_view_domain_is_the_integration_domain(mods):
    assert _m("census_view")._DOMAIN == mods.const.DOMAIN == "universal_room_automation"


def test_presence_reexports_the_one_view_type(mods):
    assert mods.presence.HouseCensusView is _m("census_view").HouseCensusView


def test_unidentified_persons_sensor_golden(mods):
    sensor_mod = _m("sensor")
    s = sensor_mod.UnidentifiedPersonsSensor.__new__(sensor_mod.UnidentifiedPersonsSensor)
    s.hass = _hass(data={"census": _census_with(_zone_result(mods, total=5, identified=2, unidentified=3))})
    assert s.native_value == 3
    assert s.extra_state_attributes == {
        "camera_total": 5, "identified_count": 2, "unidentified_count": 3,
        "data_scope": "house_level",
        "note": "Per-zone unidentified count deferred until per-zone camera data available",
    }
    s.hass = _hass()
    assert s.native_value is None
    assert s.extra_state_attributes["camera_total"] is None
    s.hass = _hass(data={"census": SimpleNamespace(last_result=None)})
    assert s.native_value is None


def test_zone_guest_count_sensor_golden(mods):
    agg = _m("aggregation")
    s = agg.ZoneGuestCountSensor.__new__(agg.ZoneGuestCountSensor)
    s.zone = "Upstairs"
    s.hass = _hass(data={"census": _census_with(_zone_result(mods, total=4, identified=3, unidentified=1, confidence="medium"))})
    assert s.native_value == 1
    assert s.extra_state_attributes == {"camera_total": 4, "identified_count": 3,
                                        "unidentified_count": 1, "zone": "Upstairs",
                                        "confidence": "medium"}
    s.hass = _hass()
    assert s.native_value == 0
    assert s.extra_state_attributes["confidence"] == "none"


def test_unexpected_person_sensor_golden(mods):
    bs = _m("binary_sensor")
    s = bs.URAUnexpectedPersonSensor.__new__(bs.URAUnexpectedPersonSensor)
    pc = SimpleNamespace(data={"a": {"tracking_status": "active"}, "b": {"tracking_status": "stale"}})
    s.hass = _hass(data={"census": _census_with(_zone_result(mods, total=2, identified=1, unidentified=1)),
                         "person_coordinator": pc})
    assert s.is_on is True
    assert (s._camera_total, s._ble_total) == (2, 1)
    assert s.extra_state_attributes["camera_total"] == 2
    assert s.extra_state_attributes["guest_count"] == 1
    s.hass = _hass(data={"census": _census_with(_zone_result(mods, total=2, identified=2, unidentified=0)),
                         "person_coordinator": pc})
    assert s.is_on is False
    # result missing -> totals reset, off; census missing -> off, totals kept
    s.hass = _hass(data={"census": SimpleNamespace(last_result=None), "person_coordinator": pc})
    assert s.is_on is False and (s._camera_total, s._ble_total) == (0, 0)
    s._camera_total = 9
    s.hass = _hass(data={"person_coordinator": pc})
    assert s.is_on is False and s._camera_total == 9


def test_phone_left_behind_census_step_golden(mods):
    bs = _m("binary_sensor")
    s = bs.PersonPhoneLeftBehindSensor(_hass(), SimpleNamespace(entry_id="e"),
                                       "Oji Udezue", "person.oji_udezue")
    pc = SimpleNamespace(data={"Oji Udezue": {"location": "Office"}}, _is_room_occupied=lambda r: False)
    base = {"person_coordinator": pc, "transit_validator": object()}
    import homeassistant.util.dt as dt_util
    noon = datetime(2026, 11, 13, 12, 0, tzinfo=dt_util.get_default_time_zone())
    orig = dt_util.now
    dt_util.now = lambda *_a, **_k: noon
    try:
        s.hass = _hass(data={**base, "census": _census_with(_zone_result(mods, total=1, identified=1, unidentified=0))})
        assert s.is_on is False  # census sees a body -> suppressed
        s.hass = _hass(data={**base, "census": _census_with(_zone_result(mods, total=0, identified=0, unidentified=0))})
        assert s.is_on is True
        s.hass = _hass(data=base)
        assert s.is_on is True
    finally:
        dt_util.now = orig
    s.hass = _hass(data={**base, "census": _census_with(_zone_result(mods, total=3, identified=3, unidentified=0))})
    assert s.extra_state_attributes["census_persons_in_house"] == 3
    s.hass = _hass(data=base)
    assert s.extra_state_attributes["census_persons_in_house"] is None


def test_room_identified_persons_reads_ble_room_only(mods):
    coord_mod = _m("coordinator")
    c = coord_mod.UniversalRoomCoordinator.__new__(coord_mod.UniversalRoomCoordinator)
    c.entry = SimpleNamespace(data={mods.const.CONF_ROOM_NAME: "Study B"})
    census = SimpleNamespace(get_room_identified_persons=lambda r: ["should_not_be_read"])
    pc = SimpleNamespace(get_persons_in_room=lambda r: ["Oji Udezue"] if r == "Study B" else [])
    c.hass = _hass(data={"census": census, "person_coordinator": pc})
    assert c._get_identified_persons_in_room() == ["Oji Udezue"]
    c.hass = _hass(data={"census": census})
    assert c._get_identified_persons_in_room() == []


# =========================================================================
# RA6 — public PersonCensus surface (thin delegates)
# =========================================================================
_DELEGATES = [
    ("tracked_person_slugs", "_get_tracked_person_slugs", ()),
    ("face_suppressed_now", "_face_suppressed_now", ()),
    ("known_face_guests", "_get_known_face_guests", ()),
    ("resolve_face_legs", "_resolve_face_legs", ("garage_a",)),
    ("resolve_ble_legs", "_resolve_ble_legs", ("ts", "entry")),
    ("consume_ble_arriving_legs", "_consume_ble_arriving_legs", ("oji_udezue",)),
    ("egress_identity_enabled", "_is_egress_identity_enabled", ()),
    ("egress_identity_failsafe_strict", "_is_egress_identity_failsafe_strict", ()),
    ("face_producer_live", "_is_face_producer_live", ()),
    ("register_ble_transition_listeners", "_register_ble_transition_listeners", ()),
    ("refresh_ble_crossing_listeners", "_refresh_ble_crossing_listeners", ()),
]


@pytest.mark.parametrize("public, private, args", _DELEGATES, ids=[d[0] for d in _DELEGATES])
def test_public_census_method_delegates_to_private(mods, public, private, args):
    PC = mods.census.PersonCensus
    c = PC.__new__(PC)
    sentinel = object()
    calls: list = []
    setattr(c, private, lambda *a: calls.append(a) or sentinel)
    assert getattr(c, public)(*args) is sentinel
    assert calls == [args]


def test_public_census_note_outcome_and_counters(mods):
    from collections import deque
    PC = mods.census.PersonCensus
    c = PC.__new__(PC)
    got: list = []
    c._note_egress_identity_outcome = got.append
    c.note_egress_identity_outcome("attached")
    assert got == ["attached"]
    c._ble_legs_abstained_count = 2
    c.note_ble_leg_abstained()
    assert c._ble_legs_abstained_count == 3
    c._face_dropped_stale_count = 0
    c.note_face_dropped_stale()
    assert c._face_dropped_stale_count == 1
    assert not hasattr(c, "_face_dropped_producer_down_leg_count")
    c.note_face_dropped_producer_down(3)
    c.note_face_dropped_producer_down(2)
    assert c._face_dropped_producer_down_leg_count == 5
    c._egress_identity_boost_events = deque()
    c.note_egress_identity_boost(12.5)
    assert list(c._egress_identity_boost_events) == [12.5]
    assert c.egress_identity_boost_events() is c._egress_identity_boost_events
    c.set_egress_identity_agreement_class("both_agree")
    assert c._egress_identity_agreement_class_last == "both_agree"
    rec = {"person": "oji_udezue"}
    c.set_egress_identity_last_attach(rec)
    assert c.egress_identity_last_attach() is rec
    # readers on an object missing the store keep the old getattr defaults
    bare = PC.__new__(PC)
    assert bare.egress_identity_last_attach() == {}
    assert bare.egress_identity_outcomes() is None
    assert bare.frigate_face_named_ring() is None
    assert bare.ble_tracker_slug_map() == {}


# --------------------------------------------------- the no-private guard
# Display-only census diagnostics the census diagnostics sensor dumps as
# attributes (sensor.py). Deferred, not migrated (ship 2 README "not done"):
# one getattr per counter, display class, no producer. Exact (file, name)
# pairs with COUNTS so the list can only shrink.
_ALLOWED_DISPLAY_READS = {
    ("sensor.py", n): 1 for n in (
        "_last_enhanced_area_contributions", "_camera_manager", "_last_count_as_of",
        "_last_ble_cancel_enabled", "_egress_identity_agreement_class_last",
        "_frigate_face_last_latched", "_last_area_raw_max_pre_cancel", "_last_ble_by_area",
        "_last_camera_total_pre_cancel", "_last_raw_pre_dedup_sum",
        "_peak_refresh_suppressed_count", "_face_lookup_missing_count",
        "_face_dropped_ble_overrule_count", "_last_peak_age_seconds", "_egress_face_ids",
        "_last_area_contributions", "_last_stuck_cameras", "_ble_edge_dropped_invalid_count",
        "_ble_departing_edge_seen_count", "_ble_legs_produced_count",
        "_ble_legs_attached_count", "_ble_legs_abstained_count",
        "_ble_exit_backfilled_count", "_ble_exit_edge_no_match_count",
        "_ble_exit_ambiguity_abstain_count", "_ble_exit_flap_aborted_count",
        "_ble_exit_backfill_noop_count", "_ble_exit_per_slug_cooldown_skipped_count",
        "_ble_exit_row_contention_retry_count", "_ble_exit_row_lost_count",
        "_ble_exit_identity_disabled_skip_count", "_frigate_face_latch",
        "_frigate_face_msg_seen_count", "_frigate_face_msg_face_count",
        "_frigate_face_msg_dropped_count", "_frigate_face_msg_retained_count",
        "_ble_tracker_slug_map",
    )
}


def _census_private_names(src: str) -> set[str]:
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PersonCensus")
    names: set[str] = set()
    for n in ast.walk(cls):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("_") \
                and not n.name.startswith("__"):
            names.add(n.name)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" \
                and n.attr.startswith("_") and not n.attr.startswith("__") \
                and isinstance(n.ctx, ast.Store):
            names.add(n.attr)
    return names


def _private_census_reads(module_src: str, private: set[str]) -> list[tuple[int, str]]:
    """(line, name) of every PRIVATE PersonCensus member reached through a
    receiver whose source text names a census (``census``, ``census_ref``,
    ``self._census`` ...): attribute access, and getattr / hasattr / setattr
    with a constant name."""
    hits: list[tuple[int, str]] = []
    for n in ast.walk(ast.parse(module_src)):
        if isinstance(n, ast.Attribute) and n.attr in private \
                and "census" in ast.unparse(n.value).lower():
            hits.append((n.lineno, n.attr))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in ("getattr", "hasattr", "setattr") and len(n.args) >= 2 \
                and isinstance(n.args[1], ast.Constant) and n.args[1].value in private \
                and "census" in ast.unparse(n.args[0]).lower():
            hits.append((n.lineno, n.args[1].value))
    return hits


def test_no_private_census_reads_outside_module():
    """RA6: no module outside camera_census.py reaches a PersonCensus private
    (method call, counter write, getattr) except the listed display-only
    diagnostics. AST-based; the allowlist is exact and must not go stale."""
    private = _census_private_names((_ROOT / "camera_census.py").read_text())
    assert len(private) > 100  # the visitor found the class (anti-vacuous)
    found: dict[tuple[str, str], int] = {}
    for path in sorted(_ROOT.rglob("*.py")):
        if path.name == "camera_census.py":
            continue
        rel = str(path.relative_to(_ROOT))
        for _line, name in _private_census_reads(path.read_text(), private):
            found[(rel, name)] = found.get((rel, name), 0) + 1
    unexpected = {k: v for k, v in found.items() if v > _ALLOWED_DISPLAY_READS.get(k, 0)}
    assert not unexpected, f"private census reads outside camera_census.py: {unexpected}"
    stale = sorted(k for k in _ALLOWED_DISPLAY_READS if k not in found)
    assert not stale, f"allowlist entries no longer hit (remove them): {stale}"


@pytest.mark.parametrize("snippet, want", [
    ("x = census._get_tracked_person_slugs()", [(1, "_get_tracked_person_slugs")]),
    ("census_ref._ble_legs_abstained_count += 1", [(1, "_ble_legs_abstained_count")]),
    ("v = getattr(census, '_egress_identity_last_attach', {})", [(1, "_egress_identity_last_attach")]),
    ("h = hasattr(self._census, '_resolve_face_legs')", [(1, "_resolve_face_legs")]),
    ("x = census.tracked_person_slugs()", []),
    ("x = other._get_tracked_person_slugs()", []),
])
def test_private_census_detector_controls(snippet, want):
    """Anti-hollow: the detector flags known-bad shapes and not good ones."""
    private = {"_get_tracked_person_slugs", "_ble_legs_abstained_count",
               "_egress_identity_last_attach", "_resolve_face_legs"}
    assert _private_census_reads(snippet, private) == want


# ----------------------------------------------- RA9 own unique-id builders
def test_routine_status_and_mf_follow_unique_ids(mods):
    sensor_mod = _m("sensor")
    switch_mod = _m("switch")
    entry = SimpleNamespace(entry_id="e", data={}, options={})
    rs = sensor_mod.PersonRoutineStatusSensor(_hass(), entry, "Oji Udezue")
    assert rs._attr_unique_id == f"{DOMAIN}_person_oji_udezue_routine_status"
    sw = switch_mod.MFPersonFollowSwitch(_hass(), entry, "Oji Udezue")
    assert sw._attr_unique_id == f"{DOMAIN}_mf_person_follow_oji_udezue"


# ----------------------------------------------- RA10 music handler
@pytest.mark.parametrize("payload, want", [
    ({"person_entity": "person.oji_udezue", "zone": "Upstairs"}, "person.oji_udezue in zone Upstairs"),
    (SimpleNamespace(person_entity="person.oji_udezue", zone="Upstairs"), "person.oji_udezue in zone Upstairs"),
    ({"person_entity": "person.oji_udezue"}, "person.oji_udezue in zone unknown"),
    ({"zone": "Upstairs"}, None),
    (object(), None),
])
def test_music_arrival_handler_reads_the_normalised_payload(mods, caplog, payload, want):
    mf_mod = _m("domain_coordinators.music_following")
    mf = mf_mod.MusicFollowingCoordinator.__new__(mf_mod.MusicFollowingCoordinator)
    mf._enabled = True
    mf.__dict__["observation_mode"] = False
    import logging
    with caplog.at_level(logging.DEBUG, logger=mf_mod._LOGGER.name):
        mf._handle_person_arriving(payload)
    msgs = [r.getMessage() for r in caplog.records if "Person arriving" in r.getMessage()]
    if want is None:
        assert msgs == []
    else:
        assert len(msgs) == 1 and want in msgs[0]

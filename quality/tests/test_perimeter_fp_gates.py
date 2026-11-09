"""PERIMETER-FP-STREET-NOISE-1 (v5.107.0) — D1-D6, D10/D10.5 behavioural tests.

Plan: docs/planning/PLANNING_perimeter_fp_build_2026_11.md (rev 2).
Harness: the module-level stubs of test_perimeter_alert_nm_routing (same
_perimeter binding, same scheduler fake). Every test drives the REAL
production entry points (`async_setup`, `_async_handle_perimeter_trigger`,
`_on_perimeter_event`, `_rescan_siblings`, the captured listeners). Expected
values are written by hand from the plan, never computed by the code under
test. Boundary values are literals, not imported constants.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_perimeter_alert_nm_routing import (  # noqa: E402
    _const,
    _perimeter,
    _make_hass,
    _run,
    _scheduled,
    Severity,
    PerimeterAlertManager,
)
from custom_components.universal_room_automation import perimeter_fp_gates as _gates  # noqa: E402

UT_CAM = "camera.utilities_ptz_high_resolution_channel"
UT_F2 = "binary_sensor.utilities_ptz_person_occupancy_2"
UT_PR = "binary_sensor.utilities_ptz_person_detected"
UT_ZONE = "binary_sensor.utilities_ptz_property_person_occupancy"
UT_ZONE_2 = "binary_sensor.utilities_ptz_property_person_occupancy_2"
UT_KEY = "utilities_ptz"

RP_CAM = "camera.rear_ptz_high_resolution_channel"
RP_F2 = "binary_sensor.rear_ptz_person_occupancy_2"
RP_PR = "binary_sensor.rear_ptz_person_detected"
RP_KEY = "rear_ptz"

DB_CAM = "camera.doorbell_lite"
DB_F2 = "binary_sensor.doorbell_lite_person_occupancy_2"
DB_PR = "binary_sensor.doorbell_lite_person_detected"
DB_VEH = "binary_sensor.doorbell_lite_vehicle_detected"
DB_ANI = "binary_sensor.doorbell_lite_animal_detected"
DB_KEY = "doorbell_lite"

GA_CAM = "camera.garage_a_2"
GA_PR = "binary_sensor.garage_a_person_detected"
FA_CAM = "camera.front_door_aerial"
FA_PR = "binary_sensor.front_door_aerial_person_detected"
FS_CAM = "camera.front_side_ptz"
FS_PR = "binary_sensor.front_side_ptz_person_detected"

LEGS = {
    UT_CAM: [(UT_F2, "frigate2"), (UT_PR, "protect")],
    RP_CAM: [(RP_F2, "frigate2"), (RP_PR, "protect")],
    DB_CAM: [(DB_F2, "frigate2"), (DB_PR, "protect")],
    GA_CAM: [(GA_PR, "protect")],
    FA_CAM: [(FA_PR, "protect")],
    FS_CAM: [(FS_PR, "protect")],
}
VEH = {DB_CAM: [(DB_VEH, "protect")]}
ANI = {DB_CAM: [(DB_ANI, "protect")]}


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    """Freeze the production clock at 14:00 (outside the burst night window,
    so the burst gate never interferes) — boundary tests need exact ages."""
    fixed = _perimeter.dt_util.now().replace(hour=14, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    monkeypatch.setattr(_perimeter.dt_util, "utcnow", lambda: fixed)


class _St:
    def __init__(self, state, attrs=None, last_changed=None):
        self.state = state
        self.attributes = attrs or {}
        self.last_changed = last_changed


def _now():
    return _perimeter.dt_util.now()


def _build(
    perimeter=(RP_CAM,), egress=(), zones=None, house_state="away",
    extra_opts=None, live=True, legs=None,
):
    """MockHass with resolver legs per camera + subscription recorder."""
    hass, nm = _make_hass(house_state=house_state, perimeter_cameras=list(perimeter))
    legs = legs or LEGS
    entry = hass.config_entries.async_entries.return_value[0]
    entry.options[_const.CONF_EGRESS_CAMERAS] = list(egress)
    if zones is not None:
        entry.options[_const.CONF_PERIMETER_ZONE_SENSORS] = list(zones)
    entry.options.update(extra_opts or {})
    cam_mgr = hass.data[_const.DOMAIN]["camera_manager"]

    def _resolve(cam_id):
        first = legs.get(cam_id, [(f"binary_sensor.{cam_id[7:]}_person_occupancy", "frigate")])[0][0]
        return [SimpleNamespace(
            person_binary_sensor=first, platform="", entity_id=first,
        )]

    cam_mgr.resolve_camera_entity = _resolve

    class _Resolver:
        def resolve_detection_legs(self, cam, family, stem_aliases=None):
            src = {"person": legs, "vehicle": VEH, "animal": ANI}[family]
            return [SimpleNamespace(entity_id=e, engine=g, integration="", device_id="")
                    for (e, g) in src.get(cam, [])]

    cam_mgr._get_resolver = lambda: _Resolver()
    if live:
        for lst in legs.values():
            for e, _g in lst:
                hass._states[e] = _St("off")
        for z in zones or []:
            hass._states[z] = _St("off")
    return hass, nm


def _setup(hass, monkeypatch):
    subs: list = []

    def _rec(h, entities, cb):
        subs.append((list(entities), cb))
        return MagicMock()

    monkeypatch.setattr(_perimeter, "async_track_state_change_event", _rec)
    mgr = PerimeterAlertManager(hass)
    _run(mgr.async_setup())
    mgr._setup_time = None  # past boot settle
    return mgr, subs


def _subscribed(subs, idx=0):
    return set(subs[idx][0])


def _edge(eid):
    return SimpleNamespace(data={
        "entity_id": eid, "new_state": _St("on"), "old_state": _St("off"),
    })


def _sev(nm, i=-1):
    return nm.async_notify.await_args_list[i].kwargs["severity"]


async def _drive(mgr, eid, during=None, fire_delays=(8,)):
    """Run the handler, let it reach a hold, optionally inject edges (their
    own handlers run to completion WHILE the first is still held), then
    fire hold timers whose delay is in `fire_delays`. Bounded: a handler
    that never finishes fails the test instead of hanging it."""
    _scheduled.clear()
    t = asyncio.create_task(mgr._async_handle_perimeter_trigger(eid))
    for _ in range(10):
        await asyncio.sleep(0)
    if during:
        pending: list = []
        real = mgr.hass.async_create_task
        mgr.hass.async_create_task = lambda coro: pending.append(coro) or MagicMock()
        during()
        mgr.hass.async_create_task = real
        for c in pending:
            if asyncio.iscoroutine(c):
                await asyncio.wait_for(c, 2)
    for delay, cb in list(_scheduled):
        if delay in fire_delays:
            cb(None)
    await asyncio.wait_for(t, 2)


# =========================================================================
# helpers (pure)
# =========================================================================

@pytest.mark.parametrize("eng,fam", [
    ("frigate", "frigate"), ("frigate2", "frigate"), ("protect", "protect"),
    ("protect2", "protect"), ("legacy", "legacy"), ("legacy2", "legacy2"),
    ("", ""), (None, ""),
])
def test_nvr_family_exact(eng, fam):
    assert _gates.nvr_family(eng) == fam


@pytest.mark.parametrize("text,desc,verdict", [
    ("PERSON: YES\nA man at the gate.", "A man at the gate.", "YES"),
    ("PERSON: NO\nEmpty driveway.", "Empty driveway.", "NO"),
    ("PERSON: no.\nEmpty.", "Empty.", "NO"),
    ("\n  person: Unsure\nDark.", "Dark.", "UNSURE"),
    ("Person: maybe\nHmm.", "Hmm.", "UNSURE"),
    ("A cat on the lawn.", "A cat on the lawn.", "UNSURE"),
    ("", None, "UNSURE"),
    (None, None, "UNSURE"),
])
def test_vlm_verdict_parse(text, desc, verdict):
    assert _gates.parse_vlm_verdict(text) == (desc, verdict)


def test_agreement_tracker_window_and_persistence():
    t0 = _now()
    tr = _gates.AgreementTracker(window_n=3, pair_window_s=60)
    for i in range(4):
        tr.open_sample("cam", t0 + timedelta(minutes=i), "protect", i % 2 == 0)
    tr.finalize_due(t0 + timedelta(minutes=10))
    assert tr.samples("cam") == 3  # window 3 keeps the newest three
    assert tr.rate("cam") == pytest.approx(1 / 3)
    # forward scan: other family at +30 s corroborates, same family does not
    tr.open_sample("c2", t0, "protect", False)
    tr.note_fire("c2", "protect", t0 + timedelta(seconds=30))
    tr.finalize_due(t0 + timedelta(seconds=61))
    assert tr.rate("c2") == 0.0
    tr.open_sample("c3", t0, "protect", False)
    tr.note_fire("c3", "frigate", t0 + timedelta(seconds=30))
    tr.finalize_due(t0 + timedelta(seconds=61))
    assert tr.rate("c3") == 1.0
    # restart round-trip
    tr2 = _gates.AgreementTracker(window_n=3, pair_window_s=60)
    assert tr2.load_dict(tr.to_dict()) is True
    assert tr2.samples("cam") == 3 and tr2.rate("c3") == 1.0
    # corrupt -> empty, not eligible
    tr3 = _gates.AgreementTracker(window_n=3, pair_window_s=60)
    assert tr3.load_dict({"outcomes": {"cam": "garbage"}}) is False
    assert tr3.samples("cam") == 0


# =========================================================================
# D1 zone legs
# =========================================================================

def test_zone_sensors_empty_byte_identical(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,), zones=None)
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {UT_F2, UT_PR}
    assert mgr._zone_map == {} and mgr._zone_key_overrides == {}


def test_zone_leg_replaces_camera_frigate_leg(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE])
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {UT_ZONE, UT_PR}
    # Live zone ids are bare-named but Frigate-2 sourced (HomeLab 2026-11-08):
    # the zone inherits the dropped camera leg's host tag.
    assert mgr._sensor_engine[UT_ZONE] == "frigate2"
    assert _gates.nvr_family(mgr._sensor_engine[UT_ZONE]) == "frigate"
    assert mgr._sensor_to_camera[UT_ZONE] == UT_CAM
    assert mgr._sensor_platforms[UT_ZONE] == "frigate"


def test_zone_leg_bare_and_suffixed(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE_2])
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {UT_ZONE_2, UT_PR}
    assert mgr._sensor_engine[UT_ZONE_2] == "frigate2"
    assert mgr._camera_key_for_sensor(UT_ZONE_2) == UT_KEY


@pytest.mark.parametrize("cam,legs,zone", [
    ("camera.g5_bullet", [("binary_sensor.g5_bullet_person_occupancy_2", "frigate2"),
                          ("binary_sensor.g5_bullet_person_detected", "protect")],
     "binary_sensor.g5_bullet_property_person_occupancy"),
    ("camera.rear_ptz_high_resolution_channel", [(RP_F2, "frigate2"), (RP_PR, "protect")],
     "binary_sensor.rear_ptz_property_person_occupancy"),
    ("camera.utilities_ptz_high_resolution_channel", [(UT_F2, "frigate2"), (UT_PR, "protect")],
     "binary_sensor.utilities_ptz_property_person_occupancy"),
    ("camera.front_side_ptz", [("binary_sensor.front_side_ptz_person_occupancy_2", "frigate2"),
                               ("binary_sensor.front_side_ptz_person_detected", "protect")],
     "binary_sensor.front_side_ptz_property_person_occupancy"),
    ("camera.doorbell_lite", [(DB_F2, "frigate2"), (DB_PR, "protect")],
     "binary_sensor.doorbell_lite_property_person_occupancy"),
    ("camera.front_door_aerial", [("binary_sensor.front_door_aerial_person_occupancy_2", "frigate2"),
                                  (FA_PR, "protect")],
     "binary_sensor.front_door_aerial_property_person_occupancy"),
    ("camera.madrone_g6_entry", [("binary_sensor.madrone_g6_entry_person_occupancy_2", "frigate2"),
                                 ("binary_sensor.madrone_g6_entry_person_detected", "protect")],
     "binary_sensor.madrone_g6_entry_property_person_occupancy"),
])
def test_live_zone_ids_map_and_tag_frigate2(monkeypatch, cam, legs, zone):
    """The seven live zone ids (HomeLab Phase 1, 2026-11-08)."""
    hass, _nm = _build(perimeter=(cam,), zones=[zone], legs={cam: legs})
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {zone, legs[1][0]}
    assert mgr._sensor_engine[zone] == "frigate2"
    key = legs[0][0][len("binary_sensor."):-len("_person_occupancy_2")]
    assert mgr._camera_key_for_sensor(zone) == key


def test_zone_bare_host_falls_back_to_suffix_rule(monkeypatch):
    bare = "binary_sensor.sonoffwindow_person_occupancy"
    zone = "binary_sensor.sonoffwindow_property_person_occupancy"
    hass, _nm = _build(perimeter=("camera.sonoffwindow",), zones=[zone],
                       legs={"camera.sonoffwindow": [(bare, "frigate")]})
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {zone}
    assert mgr._sensor_engine[zone] == "frigate"


def test_zone_no_2_sibling_warn_suppressed(monkeypatch, caplog):
    bare = "binary_sensor.sonoffwindow_person_occupancy"
    zone = "binary_sensor.sonoffwindow_property_person_occupancy"
    hass, _nm = _build(perimeter=("camera.sonoffwindow",), zones=[zone],
                       legs={"camera.sonoffwindow": [(bare, "frigate")]})
    with caplog.at_level(logging.WARNING):
        _setup(hass, monkeypatch)
    assert "no `_2` sibling" not in caplog.text


def test_no_2_sibling_warn_still_fires_unzoned(monkeypatch, caplog):
    bare = "binary_sensor.sonoffwindow_person_occupancy"
    hass, _nm = _build(perimeter=("camera.sonoffwindow",),
                       legs={"camera.sonoffwindow": [(bare, "frigate")]})
    with caplog.at_level(logging.WARNING):
        _setup(hass, monkeypatch)
    assert "no `_2` sibling" in caplog.text


def test_zone_no_unique_match_keeps_camera_leg(monkeypatch):
    stray = "binary_sensor.street_property_person_occupancy"
    hass, _nm = _build(perimeter=(UT_CAM,), zones=[stray])
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {UT_F2, UT_PR}  # coverage kept, not lost
    assert stray not in mgr._sensor_to_camera


def test_zone_map_alias_rung(monkeypatch):
    monkeypatch.setitem(_perimeter._EXTERIOR_CAMERA_KEY_ALIASES_LC, "yardzone", UT_KEY)
    z = "binary_sensor.yardzone_person_occupancy"
    hass, _nm = _build(perimeter=(UT_CAM,), zones=[z])
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {z, UT_PR}
    assert mgr._camera_key_for_sensor(z) == UT_KEY


def test_zone_leg_camera_key_all_sites(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE])
    mgr, subs = _setup(hass, monkeypatch)
    # key collapse (cooldown / in-flight / burst / linker feed / capture)
    assert mgr._camera_key_for_sensor(UT_ZONE) == UT_KEY
    # linker allowlist built during wiring holds the camera key only
    assert UT_KEY in mgr._perimeter_allowlist
    assert "utilities_ptz_property" not in mgr._perimeter_allowlist
    # snapshot URL: Frigate cache is keyed by the CAMERA name, not the zone
    mgr._frigate_last_event_id[UT_KEY] = ("1700000000.1-abc", _perimeter.dt_util.utcnow())
    url, delay = mgr._resolve_snapshot_url_and_delay(UT_ZONE)
    assert url == "/api/frigate/notifications/1700000000.1-abc/snapshot.jpg"
    assert delay == 0
    # edge capture buffer keyed by camera key
    mgr._snapshot_kill_legacy_url = False
    mgr._maybe_start_edge_capture(UT_ZONE)
    assert UT_KEY in mgr._edge_captures
    # liveness index
    assert mgr._person_legs_by_key[UT_KEY] == {UT_ZONE, UT_PR}


def test_zone_overlay_installed_before_wiring(monkeypatch, caplog):
    hass, _nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE])
    with caplog.at_level(logging.WARNING):
        _setup(hass, monkeypatch)
    text = caplog.text
    assert ">1 camera key" not in text          # F7 tripwire quiet
    assert "no `_2` sibling" not in text       # D1 item 7
    assert "NOT a superset" not in text        # D1 item 6


def test_rescan_siblings_keeps_zone_exclusion(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE])
    mgr, subs = _setup(hass, monkeypatch)
    before = len(subs)
    infos = mgr._resolve_camera_infos(_const.CONF_PERIMETER_CAMERAS)
    mgr._rescan_siblings(infos)
    added = [e for ents, _cb in subs[before:] for e in ents]
    assert UT_F2 not in added
    assert UT_F2 not in mgr._sensor_to_camera


def test_nvr_family_sibling_check(monkeypatch):
    """Zone leg (frigate) + a leftover frigate2 fire = same family: NOT
    corroboration; + Protect = corroboration."""
    fixed = _now().replace(hour=2)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    hass, nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE])
    mgr, _subs = _setup(hass, monkeypatch)
    mgr._recent_alerts_by_camera[UT_KEY] = [fixed - timedelta(minutes=5)]
    mgr._recent_fires[UT_KEY] = [("frigate2", fixed)]
    _run(mgr._async_handle_perimeter_trigger(UT_ZONE))
    assert mgr._last_burst_decision[UT_KEY]["sibling_corroborated"] is False
    assert _sev(nm) == Severity.LOW
    mgr._last_alert.clear()
    mgr._recent_fires[UT_KEY] = [("protect", fixed)]
    _run(mgr._async_handle_perimeter_trigger(UT_ZONE))
    assert mgr._last_burst_decision[UT_KEY]["sibling_corroborated"] is True
    assert _sev(nm) == Severity.CRITICAL


# =========================================================================
# D2 frigate_events cache
# =========================================================================

# Shape of a real Frigate 0.14 `frigate/events` MQTT payload as bridged to
# the `frigate_events` bus by automations.yaml:6578-6595 (fields per the
# Frigate MQTT docs). NOT captured live this cycle — see README.
_FRIGATE_PAYLOAD = {
    "type": "update",
    "before": {},
    "after": {
        "id": "1731070000.123456-ab12cd", "camera": "utilities_ptz",
        "label": "person", "score": 0.81, "top_score": 0.84,
        "box": [120, 40, 210, 300], "current_zones": [],
        "entered_zones": ["utilities_ptz_property"], "stationary": False,
    },
}


def _frigate_cb(hass):
    for c in hass.bus.async_listen.call_args_list:
        if c.args[0] == _perimeter.FRIGATE_EVENTS_BUS_EVENT:
            return c.args[1]
    raise AssertionError("frigate_events listener not registered")


def test_frigate_event_cache_fields_from_fixture(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    _frigate_cb(hass)(SimpleNamespace(data=_FRIGATE_PAYLOAD))
    rec = mgr._frigate_event_cache[UT_KEY]
    assert rec["id"] == "1731070000.123456-ab12cd"
    assert rec["score"] == 0.81 and rec["top_score"] == 0.84
    assert rec["box"] == [120, 40, 210, 300]
    assert rec["current_zones"] == [] and rec["entered_zones"] == ["utilities_ptz_property"]
    assert rec["stationary"] is False and rec["type"] == "update"
    stats = mgr.frigate_bus_stats()[UT_KEY]
    assert stats["frigate_events_24h"] == 1
    # id cache for the snapshot readers is untouched in shape
    assert mgr._frigate_last_event_id[UT_KEY][0] == "1731070000.123456-ab12cd"


def test_frigate_event_cache_missing_keys(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    _frigate_cb(hass)(SimpleNamespace(data={
        "type": "new", "after": {"id": "x", "camera": "UTILITIES_PTZ", "label": "person"},
    }))
    rec = mgr._frigate_event_cache[UT_KEY]
    assert rec["entered_zones"] is None and rec["score"] is None


def test_frigate_bus_silent_warn(monkeypatch, caplog):
    monkeypatch.setattr(_perimeter, "PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES", 3)
    hass, _nm = _build(perimeter=(RP_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            mgr._on_perimeter_event(_edge(RP_F2))
        assert "ZERO frigate_events" not in caplog.text
        mgr._on_perimeter_event(_edge(RP_PR))  # protect edge never counts
        assert "ZERO frigate_events" not in caplog.text
        mgr._on_perimeter_event(_edge(RP_F2))
    assert caplog.text.count("ZERO frigate_events") == 1


def test_frigate_bus_not_silent_when_bus_alive(monkeypatch, caplog):
    monkeypatch.setattr(_perimeter, "PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES", 1)
    hass, _nm = _build(perimeter=(RP_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    _frigate_cb(hass)(SimpleNamespace(data={
        "type": "new", "after": {"id": "x", "camera": "rear_ptz", "label": "person"},
    }))
    with caplog.at_level(logging.WARNING):
        mgr._on_perimeter_event(_edge(RP_F2))
    assert "ZERO frigate_events" not in caplog.text


# =========================================================================
# D3 zone agreement
# =========================================================================

def _d3(monkeypatch, entered, age_s=2, enforce=True, zoned=True, camera="utilities_ptz"):
    hass, nm = _build(
        perimeter=(UT_CAM,), zones=[UT_ZONE] if zoned else None,
        extra_opts={_const.CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE: enforce},
    )
    mgr, _subs = _setup(hass, monkeypatch)
    after = {"id": "e1", "camera": camera, "label": "person"}
    if entered is not ...:
        after["entered_zones"] = entered
    _frigate_cb(hass)(SimpleNamespace(data={"type": "update", "after": after}))
    mgr._frigate_event_cache[UT_KEY]["received_at"] = _now() - timedelta(seconds=age_s)
    _run(mgr._async_handle_perimeter_trigger(UT_PR))
    return mgr, nm


def test_zone_agreement_outside_zone_enforced(monkeypatch):
    mgr, nm = _d3(monkeypatch, [])
    assert _sev(nm) == Severity.LOW
    d = mgr._last_gate_decisions[UT_KEY]["zone_agreement"]
    assert d["would_demote"] is True and d["demoted"] is True


def test_zone_agreement_off_is_shadow(monkeypatch):
    mgr, nm = _d3(monkeypatch, [], enforce=False)
    assert _sev(nm) == Severity.CRITICAL
    d = mgr._last_gate_decisions[UT_KEY]["zone_agreement"]
    assert d["would_demote"] is True and d["demoted"] is False


def test_zone_agreement_in_zone_case_insensitive(monkeypatch):
    mgr, nm = _d3(monkeypatch, ["Utilities_PTZ_Property"])
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[UT_KEY]["zone_agreement"]["reason"] == "in_zone"


@pytest.mark.parametrize("age,expected", [(19, Severity.LOW), (20, Severity.LOW), (21, Severity.CRITICAL), (25, Severity.CRITICAL)])
def test_zone_agreement_freshness_boundary(monkeypatch, age, expected):
    _mgr, nm = _d3(monkeypatch, [], age_s=age)
    assert _sev(nm) == expected


def test_zone_agreement_missing_field_and_unzoned(monkeypatch):
    mgr, nm = _d3(monkeypatch, ...)
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[UT_KEY]["zone_agreement"]["reason"] == "entered_zones_missing"
    mgr2, nm2 = _d3(monkeypatch, [], zoned=False)
    assert _sev(nm2) == Severity.CRITICAL
    assert "zone_agreement" not in mgr2._last_gate_decisions.get(UT_KEY, {})


def test_zone_agreement_no_event(monkeypatch):
    hass, nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE],
                      extra_opts={_const.CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE: True})
    mgr, _subs = _setup(hass, monkeypatch)
    _run(mgr._async_handle_perimeter_trigger(UT_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[UT_KEY]["zone_agreement"]["reason"] == "no_frigate_event"


def test_zone_agreement_exemption(monkeypatch):
    monkeypatch.setattr(PerimeterAlertManager, "_exemption_shields", lambda self, *a: True)
    mgr, nm = _d3(monkeypatch, [])
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[UT_KEY]["zone_agreement"]["reason"] == "classification_transition_exemption"


# =========================================================================
# D4 burst all day (constant NOT flipped this build; the code path works)
# =========================================================================

def test_burst_demote_daytime_when_not_night_only(monkeypatch):
    fixed = _now().replace(hour=13)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    monkeypatch.setattr(_perimeter, "PERIMETER_BURST_NIGHT_ONLY", False)
    hass, nm = _build(perimeter=(RP_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    mgr._last_alert.clear()
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.LOW
    assert mgr._last_burst_decision[RP_KEY]["reason"] == "burst_isolated"


def test_burst_night_only_flipped_on_d4a_go():
    assert _const.PERIMETER_BURST_NIGHT_ONLY is False
    assert _perimeter.PERIMETER_BURST_NIGHT_ONLY is False


def test_burst_demote_daytime_with_shipped_constant(monkeypatch):
    """No monkeypatch of the constant: the shipped default demotes a
    13:00 isolated repeat (literal hour, not the window constant)."""
    fixed = _now().replace(hour=13)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    hass, nm = _build(perimeter=(RP_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    mgr._recent_alerts_by_camera[RP_KEY] = [fixed - timedelta(minutes=10)]
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.LOW
    mgr._last_alert.clear()
    mgr._recent_fires[RP_KEY] = [("frigate2", fixed)]
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.CRITICAL  # sibling-corroborated repeat


# =========================================================================
# D5 single source
# =========================================================================

def _d5(monkeypatch, enforce=True, samples=20, rate_true=20, extra=None):
    hass, nm = _build(perimeter=(RP_CAM,), extra_opts={
        _const.CONF_PERIMETER_SINGLE_SOURCE_DEMOTE: enforce, **(extra or {}),
    })
    mgr, subs = _setup(hass, monkeypatch)
    outcomes = [True] * rate_true + [False] * (samples - rate_true)
    mgr._agreement.load_dict({"outcomes": {RP_KEY: outcomes}})
    return hass, nm, mgr


def test_single_source_switch_off_no_timer_byte_identical(monkeypatch):
    calls = []
    _hass, nm, mgr = _d5(monkeypatch, enforce=False)
    real = _perimeter.async_call_later
    monkeypatch.setattr(_perimeter, "async_call_later",
                        lambda h, d, cb: (calls.append(d), real(h, d, cb))[1])
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert 8 not in calls  # no settle timer
    d = mgr._last_gate_decisions[RP_KEY]["single_source"]
    assert d["would_demote"] is True and d["reason"] == "shadow"


def test_single_source_demotes_protect_only(monkeypatch):
    _hass, nm, mgr = _d5(monkeypatch)
    _run(_drive(mgr, RP_PR))
    assert nm.async_notify.await_count == 1
    assert _sev(nm) == Severity.LOW
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "single_source"
    assert RP_KEY not in mgr._dispatch_in_flight


def test_single_source_sibling_during_settle_one_notify(monkeypatch):
    _hass, nm, mgr = _d5(monkeypatch)
    # real ingress, +5 s into the settle; its handler runs while held
    _run(_drive(mgr, RP_PR, during=lambda: mgr._on_perimeter_event(_edge(RP_F2))))
    assert nm.async_notify.await_count == 1
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "corroborated_settle"


def test_single_source_frigate_leg_unavailable_not_eligible(monkeypatch):
    hass, nm, mgr = _d5(monkeypatch)
    hass._states[RP_F2] = _St("unavailable")
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "single_nvr"


@pytest.mark.parametrize("samples,true_n,expected", [
    (20, 12, Severity.LOW),       # 0.60 == threshold
    (100, 59, Severity.CRITICAL),  # 0.59
    (19, 19, Severity.CRITICAL),   # 19 samples
])
def test_single_source_eligibility_boundaries(monkeypatch, samples, true_n, expected):
    _hass, nm, mgr = _d5(monkeypatch, samples=samples, rate_true=true_n)
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == expected


def test_single_source_repeat_daytime_night_only_unchanged(monkeypatch):
    """H2 discriminator: 13:00, NIGHT_ONLY=True, prior alert 10 min ago."""
    fixed = _now().replace(hour=13)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    monkeypatch.setattr(_perimeter, "PERIMETER_BURST_NIGHT_ONLY", True)
    _hass, nm, mgr = _d5(monkeypatch)
    mgr._recent_alerts_by_camera[RP_KEY] = [fixed - timedelta(minutes=10)]
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "not_first_alert"


def test_single_source_lookback_corroborated(monkeypatch):
    _hass, nm, mgr = _d5(monkeypatch)
    mgr._recent_fires[RP_KEY] = [("frigate2", _now() - timedelta(seconds=30))]
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "corroborated_lookback"


def test_single_source_teardown_during_settle(monkeypatch):
    _hass, nm, mgr = _d5(monkeypatch)

    async def _go():
        _scheduled.clear()
        t = asyncio.create_task(mgr._async_handle_perimeter_trigger(RP_PR))
        for _ in range(10):
            await asyncio.sleep(0)
        assert RP_KEY in mgr._dispatch_in_flight  # H1: held before the await
        await mgr.async_teardown()
        await asyncio.wait_for(t, 2)
    _run(_go())
    assert nm.async_notify.await_count == 0
    assert RP_KEY not in mgr._dispatch_in_flight
    assert mgr._pending_holds == {}
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "dropped_teardown"


def test_single_source_samples_recorded_from_alerts(monkeypatch):
    """Tracker wire-in: alerts open samples; the agreement timer finalises."""
    _hass, _nm, mgr = _d5(monkeypatch, enforce=False, samples=0, rate_true=0)
    _scheduled.clear()
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert mgr._agreement.has_pending
    later = _now() + timedelta(seconds=61)
    mgr._agreement.finalize_due(later)
    assert mgr._agreement.samples(RP_KEY) == 1
    assert mgr._agreement.rate(RP_KEY) == 0.0


def test_single_source_forward_fire_marks_corroborated(monkeypatch):
    _hass, _nm, mgr = _d5(monkeypatch, enforce=False, samples=0, rate_true=0)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    mgr._on_perimeter_event(_edge(RP_F2))  # real _record_leg_fire hook
    mgr._agreement.finalize_due(_now() + timedelta(seconds=61))
    assert mgr._agreement.rate(RP_KEY) == 1.0


def test_single_source_config_extremes(monkeypatch):
    # threshold 1.01 -> never eligible
    monkeypatch.setattr(_perimeter, "PERIMETER_SS_MIN_AGREEMENT", 1.01)
    _hass, nm, mgr = _d5(monkeypatch)
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    # threshold 0, settle 0, min samples 0 (clamped to 1)
    monkeypatch.setattr(_perimeter, "PERIMETER_SS_MIN_AGREEMENT", 0)
    monkeypatch.setattr(_perimeter, "PERIMETER_SS_SETTLE_S", 0)
    monkeypatch.setattr(_perimeter, "PERIMETER_SS_MIN_SAMPLES", 0)
    _hass, nm, mgr = _d5(monkeypatch, samples=1, rate_true=0)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.LOW
    _hass, nm, mgr = _d5(monkeypatch, samples=0, rate_true=0)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.CRITICAL  # 0 samples < clamped 1


def test_agreement_store_round_trip_and_corrupt(monkeypatch):
    stores = {}

    class _Store:
        def __init__(self, hass, ver, key):
            self.key = key
            self.saved = None

        async def async_load(self):
            return stores.get("data")

        def async_delay_save(self, fn, delay):
            stores["data"] = fn()
            stores["delay"] = delay

    import sys
    mod = SimpleNamespace(Store=_Store)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", mod)
    _hass, _nm, mgr = _d5(monkeypatch, enforce=False, samples=0, rate_true=0)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    mgr._agreement.note_fire(RP_KEY, "frigate", _now())
    mgr._agreement_note_fire(RP_KEY, "frigate2", _now() + timedelta(seconds=61))
    assert stores["delay"] == 30
    assert stores["data"]["outcomes"][RP_KEY] == [True]
    # restart: a new manager loads it
    _hass2 = _build(perimeter=(RP_CAM,))[0]
    m2 = PerimeterAlertManager(_hass2)
    _run(m2._async_load_agreement())
    assert m2._agreement.samples(RP_KEY) == 1 and m2._agreement_load_ok is True
    stores["data"] = {"outcomes": []}
    m3 = PerimeterAlertManager(_hass2)
    _run(m3._async_load_agreement())
    assert m3._agreement.samples(RP_KEY) == 0 and m3._agreement_load_ok is False


# =========================================================================
# D6 VLM gate
# =========================================================================

def _d6(monkeypatch, mode, verdict_text, tier="frigate_event", path="/media/ura/snapshots/rear_ptz_x.jpg"):
    hass, nm = _build(perimeter=(RP_CAM,), extra_opts={
        _const.CONF_PERIMETER_VLM_GATE: mode,
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [RP_PR],
    })
    mgr, _subs = _setup(hass, monkeypatch)
    prompts = []

    async def _svc(domain, service, data, **kw):
        prompts.append(data["message"])
        return {"response_text": verdict_text}

    hass.services.async_call = _svc

    async def _cap(_eid):
        mgr._last_snapshot_capture[RP_KEY] = {"path": path, "engine": tier}
        return path
    mgr._await_edge_capture = _cap
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    monkeypatch.setattr(pe.os.path, "exists", lambda p: True)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    return mgr, nm, prompts


def test_vlm_gate_off_exact_prompt_and_message(monkeypatch):
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    mgr, nm, prompts = _d6(monkeypatch, "off", "A man.")
    assert prompts == [pe._DEFAULT_PROMPT]
    msg = nm.async_notify.await_args.kwargs["message"]
    assert msg.endswith("\n\nA man.")
    assert _sev(nm) == Severity.CRITICAL
    assert "vlm" not in mgr._last_gate_decisions.get(RP_KEY, {})


def test_vlm_gate_enforce_no_frigate_event_demotes(monkeypatch):
    mgr, nm, prompts = _d6(monkeypatch, "enforce", "PERSON: NO\nEmpty driveway.")
    assert _sev(nm) == Severity.LOW
    msg = nm.async_notify.await_args.kwargs["message"]
    assert msg.endswith("\n\nEmpty driveway.") and "PERSON:" not in msg
    assert mgr._last_gate_decisions[RP_KEY]["vlm"]["demoted"] is True


def test_vlm_gate_enforce_live_grab_unchanged(monkeypatch):
    mgr, nm, _p = _d6(monkeypatch, "enforce", "PERSON: NO\nEmpty.", tier="live_grab")
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["vlm"]["reason"] == "untrusted_tier"


def test_vlm_gate_tier_must_match_returned_path(monkeypatch):
    hass_path = "/media/ura/snapshots/rear_ptz_x.jpg"
    hass, nm = _build(perimeter=(RP_CAM,), extra_opts={
        _const.CONF_PERIMETER_VLM_GATE: "enforce",
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [RP_PR],
    })
    mgr, _s = _setup(hass, monkeypatch)

    async def _svc(*a, **kw):
        return {"response_text": "PERSON: NO\nx"}
    hass.services.async_call = _svc

    async def _cap(_eid):
        mgr._last_snapshot_capture[RP_KEY] = {"path": "/other.jpg", "engine": "frigate_event"}
        return hass_path
    mgr._await_edge_capture = _cap
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    monkeypatch.setattr(pe.os.path, "exists", lambda p: True)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.CRITICAL


@pytest.mark.parametrize("text", ["Person: maybe\nHmm", "PERSON: UNSURE\nx", "PERSON: YES\nx", ""])
def test_vlm_gate_enforce_non_no_unchanged(monkeypatch, text):
    _mgr, nm, _p = _d6(monkeypatch, "enforce", text)
    assert _sev(nm) == Severity.CRITICAL


def test_vlm_gate_timeout_unchanged_base_message(monkeypatch):
    hass, nm = _build(perimeter=(RP_CAM,), extra_opts={
        _const.CONF_PERIMETER_VLM_GATE: "enforce",
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [RP_PR],
    })
    mgr, _s = _setup(hass, monkeypatch)

    async def _svc(*a, **kw):
        raise asyncio.TimeoutError()
    hass.services.async_call = _svc

    async def _cap(_eid):
        return "/media/ura/snapshots/rear_ptz_x.jpg"
    mgr._await_edge_capture = _cap
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    monkeypatch.setattr(pe.os.path, "exists", lambda p: True)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert "\n\n" not in nm.async_notify.await_args.kwargs["message"]


def test_vlm_gate_shadow_records_and_strips(monkeypatch):
    mgr, nm, _p = _d6(monkeypatch, "shadow", "PERSON: NO\nEmpty.")
    assert _sev(nm) == Severity.CRITICAL
    d = mgr._last_gate_decisions[RP_KEY]["vlm"]
    assert d["would_demote"] is True and d["demoted"] is False
    assert "PERSON:" not in nm.async_notify.await_args.kwargs["message"]


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_vlm_gate_vehicle_path_untouched(monkeypatch, mode):
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    hass, nm = _build(perimeter=(RP_CAM,), house_state="away", extra_opts={
        _const.CONF_PERIMETER_VLM_GATE: mode,
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: ["binary_sensor.rear_ptz_vehicle_detected"],
        _const.CONF_PERIMETER_VEHICLE_HOURS_START: 0,
        _const.CONF_PERIMETER_VEHICLE_HOURS_END: 0,
    })
    mgr, _s = _setup(hass, monkeypatch)
    prompts = []

    async def _svc(domain, service, data, **kw):
        prompts.append(data["message"])
        return {"response_text": "PERSON: NO\nA car."}
    hass.services.async_call = _svc

    async def _cap(_eid):
        return "/media/ura/snapshots/rear_ptz_v.jpg"
    mgr._await_edge_capture = _cap
    monkeypatch.setattr(pe.os.path, "exists", lambda p: True)
    _run(mgr._async_handle_vehicle_trigger("binary_sensor.rear_ptz_vehicle_detected"))
    assert prompts == [pe._DEFAULT_PROMPT]
    kw = nm.async_notify.await_args.kwargs
    assert kw["message"].endswith("\n\nPERSON: NO\nA car.")
    assert kw["severity"] == Severity.HIGH


# =========================================================================
# D10 role-aware egress suppression + D10.3 vehicle skip
# =========================================================================

def _egress_cb(subs, sensor):
    for ents, cb in subs:
        if sensor in ents and cb.__name__ == "_on_egress_state_change":
            return cb
    raise AssertionError(f"no egress listener for {sensor}")


def _d10(monkeypatch, gate=False):
    hass, nm = _build(
        perimeter=(DB_CAM, FA_CAM, FS_CAM), egress=(DB_CAM, FA_CAM, GA_CAM),
        extra_opts={_const.CONF_PERIMETER_EGRESS_KNOWN_XCORR_GATE: gate},
    )
    mgr, subs = _setup(hass, monkeypatch)
    return hass, nm, mgr, subs


def test_egress_self_not_suppressed(monkeypatch):
    _h, nm, mgr, subs = _d10(monkeypatch)
    _egress_cb(subs, DB_PR)(_edge(DB_PR))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert nm.async_notify.await_count == 1


def test_egress_dual_role_cross_stamp_not_suppressed(monkeypatch):
    _h, nm, mgr, subs = _d10(monkeypatch)
    _egress_cb(subs, FA_PR)(_edge(FA_PR))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert nm.async_notify.await_count == 1


def test_egress_only_stamp_suppresses_dual_role(monkeypatch):
    _h, nm, mgr, subs = _d10(monkeypatch)
    _egress_cb(subs, GA_PR)(_edge(GA_PR))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert nm.async_notify.await_count == 0
    assert mgr._last_suppression[DB_KEY]["reason"] == "egress_suppression"


def test_egress_other_still_suppresses(monkeypatch):
    """Perimeter-only camera: any egress stamp suppresses (today)."""
    _h, nm, mgr, subs = _d10(monkeypatch)
    _egress_cb(subs, DB_PR)(_edge(DB_PR))
    _run(mgr._async_handle_perimeter_trigger(FS_PR))
    assert nm.async_notify.await_count == 0


def test_egress_perimeter_only_byte_identical(monkeypatch):
    hass, nm = _build(perimeter=(FS_CAM,), egress=(GA_CAM,))
    mgr, subs = _setup(hass, monkeypatch)
    assert mgr._dual_role_cameras == set()
    assert mgr._unsub_egress_identity is None
    _egress_cb(subs, GA_PR)(_edge(GA_PR))
    _run(mgr._async_handle_perimeter_trigger(FS_PR))
    assert nm.async_notify.await_count == 0


def test_dual_role_vehicle_leg_skipped(monkeypatch):
    _h, _nm, _mgr, subs = _d10(monkeypatch)
    all_ents = {e for ents, cb in subs for e in ents}
    assert DB_VEH not in all_ents
    assert DB_ANI in all_ents


def test_vehicle_leg_kept_for_perimeter_only(monkeypatch):
    hass, _nm = _build(perimeter=(DB_CAM,), egress=())
    _mgr, subs = _setup(hass, monkeypatch)
    assert DB_VEH in {e for ents, _cb in subs for e in ents}


# =========================================================================
# D10.5 egress identity / xcorr gate
# =========================================================================

class _Census:
    def __init__(self, legs=None):
        self.legs = legs or []

    def _get_tracked_person_slugs(self):
        return ["oji_udezue", "jaya_udezue"]

    def _get_known_face_guests(self):
        return []

    def _canonical_person_slug(self, n):
        return str(n).lower()

    def _resolve_face_legs(self, stem):
        return list(self.legs)


def _leg(slug, conf, age_s=0):
    return SimpleNamespace(canonical_slug=slug, confidence=conf,
                           last_changed=_now() - timedelta(seconds=age_s))


def _d105(monkeypatch, legs=None, corroborate=True, f2_state="off"):
    hass, nm = _build(perimeter=(DB_CAM,), egress=(DB_CAM,))
    hass._states[DB_F2] = _St(f2_state)
    hass.data[_const.DOMAIN]["census"] = _Census(legs)
    mgr, subs = _setup(hass, monkeypatch)
    if corroborate:
        mgr._recent_fires[DB_KEY] = [("frigate2", _now() - timedelta(seconds=4))]
    return hass, nm, mgr


def _reason(mgr):
    return mgr._last_gate_decisions[DB_KEY]["egress_identity"]["reason"]


def test_egress_gate_known_egress_event_demotes(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch)
    cb = [c.args[1] for c in hass.bus.async_listen.call_args_list
          if c.args[0] == "ura_person_egress_event"][0]
    monkeypatch.setattr(_perimeter.dt_util, "parse_datetime",
                        lambda s: _now() - timedelta(seconds=3), raising=False)
    cb(SimpleNamespace(data={"egress_camera": DB_PR, "timestamp": "x",
                             "person_id": "oji_udezue", "identity_confidence": 0.9}))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW and _reason(mgr) == "egress_known_person"


def test_egress_gate_protect_named_09_demotes(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", 0.9)])
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW and _reason(mgr) == "egress_known_person"


def test_egress_gate_face_only_pages(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL and _reason(mgr) == "egress_unknown_corroborated"


def _with_ble(hass, slug_name, age_s=10):
    pc = SimpleNamespace(data={slug_name: {
        "method": "bermuda", "location": "foyer",
        "last_changed": _now() - timedelta(seconds=age_s),
    }})
    hass.data[_const.DOMAIN]["person_coordinator"] = pc


def test_egress_gate_face_plus_ble_agree_demotes(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _with_ble(hass, "Oji Udezue")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW and _reason(mgr) == "egress_known_person"
    inputs = mgr._last_gate_decisions[DB_KEY]["egress_identity"]["inputs"]
    assert inputs["known"][2] == "face+ble"


def test_egress_gate_face_plus_person_tracker_demotes(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    hass._states["person.oji_udezue"] = _St("home", last_changed=_now() - timedelta(seconds=30))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW


@pytest.mark.parametrize("age,expected", [(119, Severity.LOW), (120, Severity.LOW), (121, Severity.CRITICAL)])
def test_egress_gate_nonface_window_boundary(monkeypatch, age, expected):
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _with_ble(hass, "Oji Udezue", age_s=age)
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == expected


def test_egress_gate_face_a_ble_b_pages(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _with_ble(hass, "Jaya Udezue")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_ble_only_unchanged(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, legs=[])
    _with_ble(hass, "Oji Udezue")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL and _reason(mgr) == "egress_unknown_corroborated"


def test_egress_gate_latched_name_ignored(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", 0.95, age_s=300)])
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_doctrine_floor(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_EGRESS_KNOWN_MIN_CONF", 0.5)
    _h, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", 0.75)])
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_uncorroborated_low_after_settle(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, corroborate=False)
    _run(_drive(mgr, DB_PR))
    assert _sev(nm) == Severity.LOW and _reason(mgr) == "egress_uncorroborated"


def test_egress_gate_corroborated_during_settle_pages_once(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, corroborate=False)
    _run(_drive(mgr, DB_PR, during=lambda: mgr._on_perimeter_event(_edge(DB_F2))))
    assert nm.async_notify.await_count == 1
    assert _sev(nm) == Severity.CRITICAL and _reason(mgr) == "egress_unknown_corroborated"


def test_egress_gate_single_nvr_waiver(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, corroborate=False, f2_state="unavailable")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL and _reason(mgr) == "xcorr_waived_single_nvr"


def test_egress_gate_teardown_discharge(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, corroborate=False)

    async def _go():
        _scheduled.clear()
        t = asyncio.create_task(mgr._async_handle_perimeter_trigger(DB_PR))
        for _ in range(10):
            await asyncio.sleep(0)
        assert DB_KEY in mgr._dispatch_in_flight
        await mgr.async_teardown()
        await asyncio.wait_for(t, 2)
    _run(_go())
    assert nm.async_notify.await_count == 0
    assert DB_KEY not in mgr._dispatch_in_flight


def test_egress_gate_switch_off_is_d10_1(monkeypatch):
    hass, nm = _build(perimeter=(DB_CAM,), egress=(DB_CAM,), extra_opts={
        _const.CONF_PERIMETER_EGRESS_KNOWN_XCORR_GATE: False})
    hass.data[_const.DOMAIN]["census"] = _Census([_leg("oji_udezue", 0.95)])
    mgr, _s = _setup(hass, monkeypatch)
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL and _reason(mgr) == "gate_off"


def test_egress_gate_wait_knob_holds_then_rechecks(monkeypatch):
    """Wait ships 0; the knob still works: hold, then re-check identity."""
    monkeypatch.setattr(_perimeter, "PERIMETER_EGRESS_IDENTITY_WAIT_S", 90)
    census = _Census([])
    hass, nm = _build(perimeter=(DB_CAM,), egress=(DB_CAM,))
    hass.data[_const.DOMAIN]["census"] = census
    mgr, _s = _setup(hass, monkeypatch)
    mgr._recent_fires[DB_KEY] = [("frigate2", _now())]

    def _name_arrives():
        census.legs = [_leg("oji_udezue", 0.92)]
    _run(_drive(mgr, DB_PR, during=_name_arrives, fire_delays=(90,)))
    assert _sev(nm) == Severity.LOW


def test_egress_gate_wait_zero_schedules_nothing(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch)
    _scheduled.clear()
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert 90 not in [d for d, _cb in _scheduled]


# =========================================================================
# Surfaces
# =========================================================================

def test_gate_decision_stats_surface(monkeypatch):
    mgr, _nm = _d3(monkeypatch, [])
    st = mgr.gate_decision_stats()
    assert st["gate_decisions_by_camera"][UT_KEY]["zone_agreement"]["reason"] == "outside_property_zone"
    assert UT_ZONE in st["zone_map"]
    assert UT_KEY in st["frigate_bus_by_camera"]

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


def _run(coro, timeout=5):  # noqa: F811 — review C: a stuck hold FAILS, never hangs
    return asyncio.run(asyncio.wait_for(coro, timeout))

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
    # PERIMETER-GATE-EVIDENCE D1: the frozen clock is 14:00, so the sun is
    # up; demote tests need daylight (night = no demote by design).
    hass._states["sun.sun"] = _St("above_horizon", {"elevation": 35.0})
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
# PERIMETER-FRIGATE-MQTT-DIRECT-1: perimeter consumes FrigateEventIngress
# =========================================================================
def _fi_mod():
    # Order-independence: bind to the frigate_ingress namespace that THIS
    # perimeter_alert's get_frigate_ingress actually closes over. A sibling
    # file can leave a different `...frigate_ingress` object in sys.modules,
    # whose FrigateEventIngress fails perimeter's isinstance check.
    return SimpleNamespace(**_perimeter.get_frigate_ingress.__globals__)


def _with_ingress(hass):
    fi = _fi_mod()
    ing = fi.FrigateEventIngress(hass)
    hass.data[_const.DOMAIN][fi.FRIGATE_INGRESS_HASS_KEY] = ing
    return ing


def _mqtt(ing, payload: dict):
    import json as _json
    ing._on_mqtt_events(
        SimpleNamespace(payload=_json.dumps(payload), retain=False), "mqtt:frigate2",
    )


def test_perimeter_registers_on_ingress_mqtt_feeds_caches(monkeypatch):
    """Wire-in anchor for `register_frigate_consumer(self.hass, "perimeter",
    ...)` in PerimeterAlertManager.async_setup."""
    hass, _nm = _build(perimeter=(UT_CAM,))
    ing = _with_ingress(hass)
    mgr, _subs = _setup(hass, monkeypatch)
    assert not any(
        c.args and c.args[0] == _perimeter.FRIGATE_EVENTS_BUS_EVENT
        for c in hass.bus.async_listen.call_args_list
    )
    # C-8: registered under its own name (a collision would drop a consumer).
    assert set(ing._consumers) == {"perimeter"}
    _mqtt(ing, _FRIGATE_PAYLOAD)
    assert mgr._frigate_last_event_id[UT_KEY][0] == "1731070000.123456-ab12cd"
    assert mgr._frigate_event_cache[UT_KEY]["entered_zones"] == ["utilities_ptz_property"]
    assert mgr.frigate_bus_stats()[UT_KEY]["frigate_events_24h"] == 1
    _mqtt(ing, {**_FRIGATE_PAYLOAD, "type": "end"})
    assert mgr._frigate_ended_event_id[UT_KEY] == "1731070000.123456-ab12cd"
    _run(mgr.async_teardown())
    assert ing._consumers == {}


def test_silent_warn_needs_both_sources_silent(monkeypatch, caplog):
    """D4 discriminator: bridge automation gone (bus silent), MQTT live ->
    no WARN. Under the pre-cycle bus-only listener this case WARNs."""
    monkeypatch.setattr(_perimeter, "PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES", 1)
    hass, _nm = _build(perimeter=(RP_CAM,))
    ing = _with_ingress(hass)
    mgr, _subs = _setup(hass, monkeypatch)
    _mqtt(ing, {"type": "new", "after": {"id": "x", "camera": "rear_ptz", "label": "person"}})
    with caplog.at_level(logging.WARNING):
        mgr._on_perimeter_event(_edge(RP_F2))
    assert "ZERO frigate_events" not in caplog.text
    assert ing.diag_stats()["frigate_ingress_bus_24h"] == 0
    assert ing.diag_stats()["frigate_ingress_mqtt_24h"] == 1


def test_silent_warn_both_silent_names_prefixes(monkeypatch, caplog):
    monkeypatch.setattr(_perimeter, "PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES", 1)
    hass, _nm = _build(perimeter=(RP_CAM,))
    ing = _with_ingress(hass)
    ing._mqtt_subs[("frigate2", "events")] = lambda: None
    mgr, _subs = _setup(hass, monkeypatch)
    with caplog.at_level(logging.WARNING):
        mgr._on_perimeter_event(_edge(RP_F2))
    assert caplog.text.count("ZERO frigate_events messages from any source") == 1
    assert "MQTT frigate2/events" in caplog.text


def test_gate_decision_stats_carries_ingress_attrs(monkeypatch):
    hass, _nm = _build(perimeter=(UT_CAM,))
    ing = _with_ingress(hass)
    mgr, _subs = _setup(hass, monkeypatch)
    _mqtt(ing, _FRIGATE_PAYLOAD)
    ing._on_mqtt_events(SimpleNamespace(payload="bad", retain=False), "mqtt:frigate2")
    stats = mgr.gate_decision_stats()
    assert stats["frigate_ingress_mqtt_24h"] == 2
    assert stats["frigate_ingress_bus_24h"] == 0
    assert stats["frigate_ingress_mqtt_bad_payload"] == 1
    assert stats["frigate_ingress_dedup_dropped"] == 0


def test_perimeter_replay_byte_identical_dual_source(monkeypatch):
    """D3 INV-3 on the real consumer: bus-only (legacy listener) vs ingress
    with both sources fed the D0 live fixture -> identical perimeter state,
    arrival-time stamps excluded (plan rev 2 M1)."""
    import json as _json
    from pathlib import Path as _P

    pairs = _json.loads(
        (_P(__file__).parent / "fixtures" / "frigate_events_mqtt_live.json").read_text()
    )["pairs"]

    def _snap(mgr):
        return (
            {k: v[0] for k, v in mgr._frigate_last_event_id.items()},
            dict(mgr._frigate_ended_event_id),
            {k: {f: x for f, x in r.items() if f != "received_at"}
             for k, r in mgr._frigate_event_cache.items()},
            {k: len(v) for k, v in mgr._frigate_bus_times.items()},
        )

    hass_a, _ = _build(perimeter=(UT_CAM,))
    mgr_a, _ = _setup(hass_a, monkeypatch)
    for p in pairs:
        _frigate_cb(hass_a)(SimpleNamespace(data=p["bus_data"]))

    hass_b, _ = _build(perimeter=(UT_CAM,))
    ing = _with_ingress(hass_b)
    mgr_b, _ = _setup(hass_b, monkeypatch)
    for p in pairs:
        ing._on_mqtt_events(
            SimpleNamespace(payload=p["mqtt_payload"], retain=False), "mqtt:frigate2",
        )
        ing._on_bus(SimpleNamespace(data=p["bus_data"]))

    snap_a = _snap(mgr_a)
    assert snap_a[0] == {"g5_bullet": "1794235499.715034-xn7uuc",
                         "kitchen_panel": "1794236552.741517-acdwi1"}
    assert _snap(mgr_b) == snap_a
    assert ing.dedup_dropped["bus"] == 16


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


def test_burst_night_only_ships_true_option_c():
    """Review A-M3 option C: code path ships, flag stays night-only until a
    daytime-only re-sample."""
    assert _const.PERIMETER_BURST_NIGHT_ONLY is True
    assert _perimeter.PERIMETER_BURST_NIGHT_ONLY is True


def test_burst_demote_daytime_with_shipped_constant(monkeypatch):
    """No monkeypatch of the constant: with the shipped default a 13:00
    isolated repeat is NOT burst-demoted (literal hour)."""
    fixed = _now().replace(hour=13)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    hass, nm = _build(perimeter=(RP_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    mgr._recent_alerts_by_camera[RP_KEY] = [fixed - timedelta(minutes=10)]
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_burst_decision[RP_KEY]["reason"] == "outside_night_window"


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
    asyncio.run(asyncio.wait_for(_go(), 5))
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


def _d105(monkeypatch, legs=None, corroborate=True, f2_state="off", booted_s=3600):
    hass, nm = _build(perimeter=(DB_CAM,), egress=(DB_CAM,), extra_opts={
        "tracked_persons": ["person.oji_udezue", "person.jaya_udezue"]})
    hass._states[DB_F2] = _St(f2_state)
    hass.data[_const.DOMAIN]["census"] = _Census(legs)
    # Doorbell lives in "Front Porch"; nothing else has an area.
    monkeypatch.setattr(PerimeterAlertManager, "_area_of_entity",
                        lambda self, e: "front_porch" if e == DB_CAM else "")
    mgr, subs = _setup(hass, monkeypatch)
    mgr._fp_setup_ts = _now().timestamp() - booted_s
    mgr._subs = subs
    if corroborate:
        mgr._recent_fires[DB_KEY] = [("frigate2", _now() - timedelta(seconds=4))]
    return hass, nm, mgr


def _person_cb(mgr):
    for ents, cb in mgr._subs:
        if "person.oji_udezue" in ents:
            return cb
    raise AssertionError("person arrival listener not registered")


def _person_edge(slug, old, new):
    return SimpleNamespace(data={
        "entity_id": f"person.{slug}",
        "old_state": None if old is None else _St(old),
        "new_state": _St(new),
    })


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


def _fire_egress_09(hass, monkeypatch, synthetic, pid="oji_udezue"):
    cb = [c.args[1] for c in hass.bus.async_listen.call_args_list
          if c.args[0] == "ura_person_egress_event"][0]
    monkeypatch.setattr(_perimeter.dt_util, "parse_datetime",
                        lambda s: _now() - timedelta(seconds=3), raising=False)
    cb(SimpleNamespace(data={"egress_camera": DB_PR, "timestamp": "x",
                             "person_id": pid, "identity_confidence": 0.9,
                             "identity_synthetic_corroborated": synthetic}))


def test_c4_live_egress_match_wins_over_synthetic(monkeypatch):
    """Review C-4: a live 0.9 for one resident and a synthetic 0.9 (with a
    real arrival edge) for another in the same window -> the live match is
    the known identity."""
    hass, nm, mgr = _d105(monkeypatch)
    _person_cb(mgr)(_person_edge("jaya_udezue", "not_home", "home"))
    _fire_egress_09(hass, monkeypatch, True, pid="jaya_udezue")
    _fire_egress_09(hass, monkeypatch, False, pid="oji_udezue")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW
    assert tuple(mgr._last_gate_decisions[DB_KEY]["egress_identity"]["inputs"]["known"]) == (
        "oji_udezue", 0.9, "egress_event")


def test_egress_gate_synthetic_09_without_arrival_pages(monkeypatch):
    """v5.108.1 review B-M1: a 0.9 egress identity that needed a synthetic
    MQTT latch leg is not two-camera face corroboration -> no demote."""
    hass, nm, mgr = _d105(monkeypatch)
    _fire_egress_09(hass, monkeypatch, True)
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert _reason(mgr) == "egress_unknown_corroborated"


def test_egress_gate_synthetic_09_with_arrival_demotes(monkeypatch):
    """...but it still demotes with the 120 s non-face arrival edge."""
    hass, nm, mgr = _d105(monkeypatch)
    _person_cb(mgr)(_person_edge("oji_udezue", "not_home", "home"))
    _fire_egress_09(hass, monkeypatch, True)
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW and _reason(mgr) == "egress_known_person"
    known = mgr._last_gate_decisions[DB_KEY]["egress_identity"]["inputs"]["known"]
    # C-10: the fallback match carries the doctrine floor (0.9), no more.
    assert tuple(known) == ("oji_udezue", 0.9, "egress_synthetic+person_tracker")


def test_egress_gate_live_09_flag_false_still_demotes(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch)
    _fire_egress_09(hass, monkeypatch, False)
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


def _with_ble(hass, slug_name, age_s=10, location="Front Porch", prev="away"):
    pc = SimpleNamespace(data={slug_name: {
        "method": "bermuda", "location": location, "bermuda_area": location,
        "previous_location": prev,
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
    """Real arrival: live not_home -> home edge via the registered listener."""
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _person_cb(mgr)(_person_edge("oji_udezue", "not_home", "home"))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW
    assert mgr._last_gate_decisions[DB_KEY]["egress_identity"]["inputs"]["known"][2] == "face+person_tracker"


def test_egress_gate_tracker_home_without_arrival_edge_pages(monkeypatch):
    """`person.*` reads home with a fresh last_changed but no live
    not_home -> home edge (restore / flap) -> NOT an arrival."""
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    hass._states["person.oji_udezue"] = _St("home", last_changed=_now() - timedelta(seconds=30))
    _person_cb(mgr)(_person_edge("oji_udezue", None, "home"))           # restore
    _person_cb(mgr)(_person_edge("oji_udezue", "unavailable", "home"))  # flap
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_tracker_not_home_to_zone_pages(monkeypatch):
    """not_home -> named zone is not an arrival edge (shared arrival_edges
    rule, LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1 drill H3)."""
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _person_cb(mgr)(_person_edge("oji_udezue", "not_home", "Work"))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_non_bermuda_record_pages(monkeypatch):
    """Only a Bermuda-method record is a BLE arrival (drill H9)."""
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _with_ble(hass, "Oji Udezue")
    hass.data[_const.DOMAIN]["person_coordinator"].data["Oji Udezue"]["method"] = "gps"
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_restart_within_window_pages(monkeypatch):
    """HA restarted 60 s ago: both a tracker edge and a Bermuda move inside
    the post-boot exclusion are ignored -> page."""
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)], booted_s=60)
    _person_cb(mgr)(_person_edge("oji_udezue", "not_home", "home"))
    _with_ble(hass, "Oji Udezue", age_s=30)
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


@pytest.mark.parametrize("booted,expected", [(599, Severity.CRITICAL), (601, Severity.LOW)])
def test_egress_gate_boot_exclusion_boundary(monkeypatch, booted, expected):
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)], booted_s=booted)
    _person_cb(mgr)(_person_edge("oji_udezue", "not_home", "home"))  # at now
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == expected


def test_egress_gate_interior_room_hop_pages(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _with_ble(hass, "Oji Udezue", location="Kitchen", prev="Family Room")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_ble_no_move_pages(monkeypatch):
    """Bermuda record already at the porch, no transition -> not arrival."""
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _with_ble(hass, "Oji Udezue", prev="Front Porch")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_near_area_includes_configured_neighbours(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    monkeypatch.setattr(PerimeterAlertManager, "_area_of_entity",
                        lambda self, e: {DB_CAM: "front_porch",
                                         "camera.foyer": "foyer"}.get(e, ""))
    # LOCK-ENTRY-AREAS-WRONG-OBJECT-1: a REAL EgressDirectionTracker at its
    # real key, and a REAL TransitValidator at its own key (which has no
    # door-group surface) -- a consumer reading the wrong key goes RED.
    from custom_components.universal_room_automation import (  # noqa: PLC0415
        transit_validator as _tv_mod,
    )
    tracker = _tv_mod.EgressDirectionTracker(None)
    tracker._door_group_by_stem = {DB_KEY: "front"}
    tracker._interior_neighbours_by_group = {"front": ["camera.foyer"]}
    hass.data[_const.DOMAIN]["egress_tracker"] = tracker
    hass.data[_const.DOMAIN]["transit_validator"] = _tv_mod.TransitValidator(None)
    assert mgr._near_areas(DB_KEY) == {"front_porch", "foyer"}
    _with_ble(hass, "Oji Udezue", location="Foyer", prev="away")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW


def test_egress_gate_known_min_conf_over_one_disables(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_EGRESS_KNOWN_MIN_CONF", 1.01)
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None), _leg("oji_udezue", 0.99)])
    _with_ble(hass, "Oji Udezue")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


def test_egress_gate_nonface_window_zero_disables(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S", 0)
    hass, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", None)])
    _with_ble(hass, "Oji Udezue", age_s=0)
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


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
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert _sev(nm) == Severity.LOW and _reason(mgr) == "egress_uncorroborated"


def test_egress_gate_settle_knob_independent_of_d5(monkeypatch):
    """Review A-M4: a D5 settle of 0 does not change D10.5's settle."""
    monkeypatch.setattr(_perimeter, "PERIMETER_SS_SETTLE_S", 0)
    _h, nm, mgr = _d105(monkeypatch, corroborate=False)
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert 20 in [d for d, _cb in _scheduled]


def test_egress_gate_corroborated_during_settle_pages_once(monkeypatch):
    _h, nm, mgr = _d105(monkeypatch, corroborate=False)
    _run(_drive(mgr, DB_PR, during=lambda: mgr._on_perimeter_event(_edge(DB_F2)),
                fire_delays=(20,)))
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



# =========================================================================
# Fix-up pass (reviews A/B)
# =========================================================================

def test_zone_agreement_skipped_on_zone_leg_edge(monkeypatch):
    """A-M2: the zone sensor's own edge is never demoted by D3."""
    hass, nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE],
                      extra_opts={_const.CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE: True})
    mgr, _subs = _setup(hass, monkeypatch)
    _frigate_cb(hass)(SimpleNamespace(data={"type": "new", "after": {
        "id": "e1", "camera": "utilities_ptz", "label": "person", "entered_zones": []}}))
    _run(mgr._async_handle_perimeter_trigger(UT_ZONE))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[UT_KEY]["zone_agreement"]["reason"] == "zone_leg_edge"


def test_rescan_late_leg_reaches_liveness(monkeypatch):
    """A-L1 / B-LOW-1: a leg found by _rescan_siblings feeds _families_live."""
    hass, _nm = _build(perimeter=(RP_CAM,), legs={RP_CAM: [(RP_PR, "protect")]})
    mgr, _subs = _setup(hass, monkeypatch)
    assert mgr._families_live(RP_KEY) == {"protect"}
    hass._states[RP_F2] = _St("off")
    late = {RP_CAM: [(RP_PR, "protect"), (RP_F2, "frigate2")]}

    class _R:
        def resolve_detection_legs(self, cam, family, stem_aliases=None):
            src = late if family == "person" else {}
            return [SimpleNamespace(entity_id=e, engine=g, integration="", device_id="")
                    for (e, g) in src.get(cam, [])]
    hass.data[_const.DOMAIN]["camera_manager"]._get_resolver = lambda: _R()
    mgr._rescan_siblings(mgr._resolve_camera_infos(_const.CONF_PERIMETER_CAMERAS))
    assert mgr._families_live(RP_KEY) == {"protect", "frigate"}


def test_agreement_load_keeps_in_memory_samples():
    tr = _gates.AgreementTracker(window_n=10, pair_window_s=60)
    t0 = _now()
    tr.open_sample("cam", t0, "protect", True)
    tr.finalize_due(t0 + timedelta(seconds=61))
    assert tr.load_dict({"outcomes": {"cam": [False, False]}}) is True
    assert list(tr._outcomes["cam"]) == [False, False, True]


def test_agreement_flushed_on_teardown(monkeypatch):
    saved = {}

    class _Store:
        def __init__(self, *a):
            pass

        async def async_load(self):
            return None

        def async_delay_save(self, fn, delay):
            pass

        async def async_save(self, data):
            saved["data"] = data

    import sys
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", SimpleNamespace(Store=_Store))
    hass, _nm = _build(perimeter=(RP_CAM,))
    mgr, _subs = _setup(hass, monkeypatch)
    mgr._agreement.load_dict({"outcomes": {RP_KEY: [True, False]}})
    _run(mgr.async_teardown())
    assert saved["data"]["outcomes"][RP_KEY] == [True, False]


def test_diag_gate_attributes_unrecorded():
    import importlib
    sensor_mod = importlib.import_module("custom_components.universal_room_automation.sensor")
    un = sensor_mod.ExteriorOpenTracksDiagnosticSensor._unrecorded_attributes
    for k in ("gate_decisions_by_camera", "agreement_by_camera",
              "frigate_bus_by_camera", "zone_map"):
        assert k in un



# =========================================================================
# Review C fix-up: per-site test authority
# =========================================================================

# ---- D10.5 egress-event identity (K3/K4/K5) and face-leg membership (K7)

def _egress_cb_for(hass):
    return [c.args[1] for c in hass.bus.async_listen.call_args_list
            if c.args[0] == "ura_person_egress_event"][0]


@pytest.mark.parametrize("pid,conf,lag_s,camera,expected", [
    ("oji_udezue", 0.9, 3, DB_PR, Severity.LOW),              # control: known, fresh
    ("oji_udezue", 0.9, 16, DB_PR, Severity.CRITICAL),        # K3: outside +-15 s
    ("oji_udezue", 0.9, -16, DB_PR, Severity.CRITICAL),       # K3: future side
    ("delivery_guy", 0.95, 3, DB_PR, Severity.CRITICAL),      # K4: not a resident
    ("oji_udezue", 0.89, 3, DB_PR, Severity.CRITICAL),        # K5: below 0.9 floor
    ("oji_udezue", 0.9, 3, DB_CAM, Severity.LOW),             # N17: camera.* key
])
def test_egress_event_identity_matrix(monkeypatch, pid, conf, lag_s, camera, expected):
    hass, nm, mgr = _d105(monkeypatch)
    monkeypatch.setattr(_perimeter.dt_util, "parse_datetime",
                        lambda s_: _now() - timedelta(seconds=lag_s), raising=False)
    _egress_cb_for(hass)(SimpleNamespace(data={
        "egress_camera": camera, "timestamp": "x",
        "person_id": pid, "identity_confidence": conf}))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == expected


def test_face_leg_unknown_slug_pages(monkeypatch):
    """K7: a scored 0.95 face leg naming someone NOT tracked / not a known
    guest is not 'known'."""
    _h, nm, mgr = _d105(monkeypatch, legs=[_leg("stranger_x", 0.95)])
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL


# ---- W15/W16/W17/W18: shipped defaults through an un-patched manager

def test_shipped_defaults_pinned():
    assert _const.DEFAULT_PERIMETER_ZONE_AGREEMENT_DEMOTE is False
    assert _const.DEFAULT_PERIMETER_SINGLE_SOURCE_DEMOTE is False
    assert _const.DEFAULT_PERIMETER_VLM_GATE == "off"
    assert _const.DEFAULT_PERIMETER_EGRESS_KNOWN_XCORR_GATE is True


def test_default_d3_off_through_manager(monkeypatch):
    hass, nm = _build(perimeter=(UT_CAM,), zones=[UT_ZONE])  # no switch key
    mgr, _subs = _setup(hass, monkeypatch)
    _frigate_cb(hass)(SimpleNamespace(data={"type": "update", "after": {
        "id": "e", "camera": "utilities_ptz", "label": "person", "entered_zones": []}}))
    _run(mgr._async_handle_perimeter_trigger(UT_PR))
    assert _sev(nm) == Severity.CRITICAL
    d = mgr._last_gate_decisions[UT_KEY]["zone_agreement"]
    assert d["would_demote"] is True and d["enforce"] is False


def test_default_d5_off_through_manager(monkeypatch):
    hass, nm = _build(perimeter=(RP_CAM,))  # no switch key
    mgr, _subs = _setup(hass, monkeypatch)
    mgr._agreement.load_dict({"outcomes": {RP_KEY: [True] * 20}})
    _scheduled.clear()
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "shadow"


def test_default_d6_off_through_manager(monkeypatch):
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    hass, nm = _build(perimeter=(RP_CAM,), extra_opts={
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [RP_PR]})
    mgr, _s = _setup(hass, monkeypatch)
    prompts = []

    async def _svc(domain, service, data, **kw):
        prompts.append(data["message"])
        return {"response_text": "PERSON: NO\nEmpty."}
    hass.services.async_call = _svc

    async def _cap(_eid):
        mgr._last_snapshot_capture[RP_KEY] = {"path": "/x.jpg", "engine": "frigate_event"}
        return "/x.jpg"
    mgr._await_edge_capture = _cap
    monkeypatch.setattr(pe.os.path, "exists", lambda p_: True)
    _run(mgr._async_handle_perimeter_trigger(RP_PR))
    assert prompts == [pe._DEFAULT_PROMPT]
    assert _sev(nm) == Severity.CRITICAL


# ---- D1c / D1d: `_2` safety net and legacy fallback keep the exclusion

SW_CAM = "camera.sonoffwindow"
SW_BARE = "binary_sensor.sonoffwindow_person_occupancy"
SW_2 = "binary_sensor.sonoffwindow_person_occupancy_2"
SW_PR = "binary_sensor.sonoffwindow_person_detected"
SW_ZONE = "binary_sensor.sonoffwindow_property_person_occupancy"


def test_zone_excludes_2_safety_net_leg(monkeypatch):
    """D1c: base bare, its `_2` sibling exists only in hass.states."""
    hass, _nm = _build(perimeter=(SW_CAM,), zones=[SW_ZONE],
                       legs={SW_CAM: [(SW_BARE, "frigate"), (SW_PR, "protect")]})
    hass._states[SW_2] = _St("off")
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {SW_ZONE, SW_PR}


def test_zone_excludes_legacy_fallback_leg(monkeypatch):
    """D1d: resolver unavailable (early boot / kill switch) -> legacy
    fallback (base + `_2` + Protect probe) must still drop the Frigate legs."""
    hass, _nm = _build(perimeter=(SW_CAM,), zones=[SW_ZONE],
                       legs={SW_CAM: [(SW_BARE, "frigate")]})
    hass._states[SW_2] = _St("off")
    hass._states[SW_PR] = _St("off")
    hass.data[_const.DOMAIN]["camera_manager"]._get_resolver = lambda: None
    mgr, subs = _setup(hass, monkeypatch)
    assert _subscribed(subs) == {SW_ZONE, SW_PR}


def test_zone_excludes_legacy_fallback_kill_switch(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_MULTI_ENGINE_LEGS_ENABLED", False)
    hass, _nm = _build(perimeter=(SW_CAM,), zones=[SW_ZONE],
                       legs={SW_CAM: [(SW_BARE, "frigate")]})
    hass._states[SW_2] = _St("off")
    mgr, subs = _setup(hass, monkeypatch)
    assert SW_BARE not in _subscribed(subs) and SW_2 not in _subscribed(subs)
    assert SW_ZONE in _subscribed(subs)


# ---- D1q / D1r: equal-length stem tie between two cameras -> no match

def test_zone_map_tie_between_cameras_no_match(monkeypatch):
    a, b = "camera.front_high_resolution_channel", "camera.front"
    a_leg = "binary_sensor.front_person_occupancy_2"
    b_leg = "binary_sensor.front_person_detected"
    zone = "binary_sensor.front_property_person_occupancy"
    hass, _nm = _build(perimeter=(a, b), zones=[zone],
                       legs={a: [(a_leg, "frigate2")], b: [(b_leg, "protect")]})
    mgr, subs = _setup(hass, monkeypatch)
    assert zone not in _subscribed(subs)
    assert a_leg in _subscribed(subs)
    assert mgr._zone_map == {}


# ---- D1v: family vs engine string (frigate vs frigate2)

def test_nvr_family_frigate_vs_frigate2_not_corroboration(monkeypatch):
    fixed = _now().replace(hour=2)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    hass, nm = _build(perimeter=(SW_CAM,), zones=[SW_ZONE],
                      legs={SW_CAM: [(SW_BARE, "frigate"), (SW_PR, "protect")]})
    mgr, _subs = _setup(hass, monkeypatch)
    assert mgr._sensor_engine[SW_ZONE] == "frigate"
    mgr._recent_alerts_by_camera["sonoffwindow"] = [fixed - timedelta(minutes=5)]
    mgr._recent_fires["sonoffwindow"] = [("frigate2", fixed)]
    _run(mgr._async_handle_perimeter_trigger(SW_ZONE))
    assert mgr._last_burst_decision["sonoffwindow"]["sibling_corroborated"] is False
    assert _sev(nm) == Severity.LOW


# ---- D6g / D6h: verdict prompt wiring + exception fail-open

def test_vlm_shadow_sends_verdict_prompt(monkeypatch):
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    # PERIMETER-GATE-EVIDENCE D3 ships dark (ask knob default False after
    # the D0-B no-go): shadow keeps today's prompt; knob on -> location prompt.
    _mgr, _nm, prompts = _d6(monkeypatch, "shadow", "PERSON: NO\nEmpty.")
    assert prompts == [pe._VERDICT_PROMPT]
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK", True)
    _mgr, _nm, prompts = _d6(monkeypatch, "shadow", "PERSON: NO\nEmpty.")
    assert prompts == [pe._VERDICT_LOCATION_PROMPT]


def test_enrich_with_verdict_exception_is_unsure(monkeypatch):
    import custom_components.universal_room_automation.perimeter_enrichment as pe

    async def _boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(pe, "enrich_dispatched_alert", _boom)
    assert asyncio.run(pe.enrich_with_verdict(None, "/x", "e")) == (None, "UNSURE")


# ---- INV-FP-EXEMPTION: D5 (D5af), D6 (D6f), D10.5 (E9)

def _shield(monkeypatch):
    monkeypatch.setattr(PerimeterAlertManager, "_exemption_shields", lambda self, *a: True)


def test_exemption_shields_single_source(monkeypatch):
    _shield(monkeypatch)
    _hass, nm, mgr = _d5(monkeypatch)
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "classification_transition_exemption"


def test_exemption_shields_vlm(monkeypatch):
    _shield(monkeypatch)
    mgr, nm, _p = _d6(monkeypatch, "enforce", "PERSON: NO\nEmpty.")
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["vlm"]["reason"] == "classification_transition_exemption"


def test_exemption_shields_egress_identity(monkeypatch):
    _shield(monkeypatch)
    _h, nm, mgr = _d105(monkeypatch, legs=[_leg("oji_udezue", 0.95)])
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert _reason(mgr) == "classification_transition_exemption"


# ---- E6 / E14 / D5i

def test_egress_known_rechecked_after_settle(monkeypatch):
    census = _Census([])
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    hass.data[_const.DOMAIN]["census"] = census

    def _named():
        census.legs = [_leg("oji_udezue", 0.92)]
    _run(_drive(mgr, DB_PR, during=_named, fire_delays=(20,)))
    assert _sev(nm) == Severity.LOW and _reason(mgr) == "egress_known_person"


def _adjacent_linker(hass, active=True):
    lk = MagicMock()
    lk.find_owning_track = MagicMock(return_value=None)
    lk.has_recent_adjacent_activity = MagicMock(return_value=active)
    lk.smart_alerts_enabled = True
    hass.data[_const.DOMAIN]["exterior_track_linker"] = lk
    return lk


def test_egress_adjacency_corroborates(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    _adjacent_linker(hass)
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert _sev(nm) == Severity.CRITICAL and _reason(mgr) == "egress_unknown_corroborated"


def test_single_source_settle_adjacency_recheck(monkeypatch):
    hass, nm, mgr = _d5(monkeypatch)
    _adjacent_linker(hass)
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "adjacent_activity"


# ---- D5p: exception after the held key is taken releases it

def test_held_key_released_when_finish_raises(monkeypatch):
    _hass, nm, mgr = _d5(monkeypatch)

    def _boom(_eid):
        raise RuntimeError("snapshot resolver blew up")
    mgr._resolve_snapshot_url_and_delay = _boom
    with pytest.raises(RuntimeError):
        _run(_drive(mgr, RP_PR))
    assert RP_KEY not in mgr._dispatch_in_flight
    # camera NOT silenced: the next edge dispatches
    mgr._resolve_snapshot_url_and_delay = lambda _eid: (None, 0)
    _run(_drive(mgr, RP_PR))
    assert nm.async_notify.await_count == 1


# ---- W5-W12: real entity wiring

def _integration_entry(opts=None):
    e = MagicMock()
    e.data = {_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_INTEGRATION}
    e.options = dict(opts or {})
    e.entry_id = "int1"
    return e


def _platform_entities(module_name, opts=None):
    import importlib
    mod = importlib.import_module(f"custom_components.universal_room_automation.{module_name}")
    added: list = []
    hass = MagicMock()
    hass.data = {_const.DOMAIN: {}}
    asyncio.run(mod.async_setup_entry(hass, _integration_entry(opts), lambda ents, *a, **k: added.extend(ents)))
    return {getattr(e, "entity_id", ""): e for e in added}


@pytest.mark.parametrize("eid,key,default", [
    ("switch.ura_perimeter_zone_agreement_demote", "perimeter_zone_agreement_demote", False),
    ("switch.ura_perimeter_single_source_demote", "perimeter_single_source_demote", False),
    ("switch.ura_perimeter_egress_known_xcorr_gate", "perimeter_egress_known_xcorr_gate", True),
])
def test_gate_switches_registered_with_keys(eid, key, default):
    ents = _platform_entities("switch")
    sw = ents[eid]
    assert sw.is_on is default                      # default with empty options
    sw._entry.options = {key: not default}
    assert sw.is_on is (not default)                # reads exactly this key


def test_vlm_select_registered_with_key_and_options():
    ents = _platform_entities("select")
    sel = ents["select.ura_perimeter_vlm_gate"]
    assert sel._attr_options == ["off", "shadow", "enforce"]
    assert sel.current_option == "off"
    sel._entry.options = {"perimeter_vlm_gate": "shadow"}
    assert sel.current_option == "shadow"


def test_diag_sensor_merges_gate_stats(monkeypatch):
    import importlib
    sensor_mod = importlib.import_module("custom_components.universal_room_automation.sensor")
    s_ = sensor_mod.ExteriorOpenTracksDiagnosticSensor.__new__(
        sensor_mod.ExteriorOpenTracksDiagnosticSensor)
    lk = MagicMock()
    lk.open_tracks_snapshot.return_value = {}
    lk.census_counts.return_value = {}
    mgr = SimpleNamespace(gate_decision_stats=lambda: {
        "gate_decisions_by_camera": {"cam": {"vlm": {"reason": "x"}}}})
    s_.hass = SimpleNamespace(data={_const.DOMAIN: {
        "exterior_track_linker": lk, "perimeter_alert_manager": mgr}})
    attrs = s_.extra_state_attributes
    assert attrs["gate_decisions_by_camera"] == {"cam": {"vlm": {"reason": "x"}}}


# =========================================================================
# PERIMETER-GATE-EVIDENCE (Part A) pure helpers: D1 is_daylight, D3 parser
# =========================================================================

@pytest.mark.parametrize("elev,min_deg,expected", [
    (0.0, 0.0, True), (-0.01, 0.0, False), (35.0, 0.0, True),
    ("12.5", 0.0, True), (None, 0.0, False), ("abc", 0.0, False),
    (True, 0.0, False), (89.0, 90.0, False), (-5.0, -6.0, True),
    (10.0, "bad", False), (float("nan"), 0.0, False),
])
def test_is_daylight_threshold_and_none(elev, min_deg, expected):
    assert _gates.is_daylight(elev, min_deg) is expected


@pytest.mark.parametrize("text,expected", [
    ("PERSON: YES\nLOCATION: STREET\nA man walks", ("A man walks", "YES", "STREET")),
    ("PERSON: NO\nA dog", ("A dog", "NO", "UNSURE")),
    ("**Person:** yes\n**Location:** property\nOn the patio.",
     ("On the patio.", "YES", "PROPERTY")),
    ("PERSON: YES\n\n  location: unsure\nDark yard.", ("Dark yard.", "YES", "UNSURE")),
    ("PERSON: YES\nLOCATION: road\nx", ("x", "YES", "UNSURE")),
    ("PERSON: YES\nA man.\nLOCATION: STREET", ("A man.\nLOCATION: STREET", "YES", "UNSURE")),
    ("PERSON: YES\nLOCATION: STREET", (None, "YES", "STREET")),
    ("LOCATION: STREET\nPERSON: YES", ("LOCATION: STREET\nPERSON: YES", "UNSURE", "UNSURE")),
    ("A cat.", ("A cat.", "UNSURE", "UNSURE")),
    ("", (None, "UNSURE", "UNSURE")),
    (None, (None, "UNSURE", "UNSURE")),
])
def test_parse_vlm_verdicts_table(text, expected):
    assert _gates.parse_vlm_verdicts(text) == expected


def test_parse_vlm_verdict_unchanged():
    """Today's parser is untouched by D3 (its output on a 2-line reply keeps
    the LOCATION line in the text — which is why D3 has its own parser)."""
    assert _gates.parse_vlm_verdict("PERSON: YES\nLOCATION: STREET\nA man") == (
        "LOCATION: STREET\nA man", "YES")
    assert _gates.parse_vlm_verdict("PERSON: NO\nA dog") == ("A dog", "NO")

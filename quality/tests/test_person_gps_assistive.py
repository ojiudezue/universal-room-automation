"""PERSON-BLE-WINS-OVER-STALE-GPS-1 — GPS assistive, BLE leads.

Plan: docs/planning/PLANNING_presence_gps_assistive.md (rev 3).

Every test drives the REAL production code (PersonTrackingCoordinator,
the seven §6b trust readers, the presence switch). Oracles are hand-derived
literals from the plan's per-row table (§4.5): the 10-24 tuple
(person.state home, GPS home, WiFi MISSING, both BLE trackers not_home,
proxy count 55 armed) -> ACTIVE / away / away_ble_silent_only / 0.82; any
other tuple -> exactly what develop produced.

The HVAC night-trust and activity-log sites live in the sibling file
`test_person_gps_assistive_hvac.py` (they need the W1-B HVAC harness).
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.frame")

PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"
T0 = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)

OJI = "Oji Udezue"
OJI_ENTITY = "person.oji_udezue"
GPS = "device_tracker.oji_phone"
IRK = "device_tracker.private_ble_device_8ce182"
BERM = "device_tracker.oji_bermuda_tracker"
ROUTER = "device_tracker.oji_router"
AREA = "sensor.oji_udezue_area"
PROXY = "sensor.bermuda_global_active_proxy_count"


def _pc():
    return importlib.import_module(f"{PKG}.person_coordinator")


def _const():
    return importlib.import_module(f"{PKG}.const")


# Modules these tests drive. Sibling files install hand-made stubs (some
# MagicMock) for several of them at COLLECTION time; for the duration of
# each test we make sure the real on-disk module is what `sys.modules`
# serves, then put back exactly what was there (scoped, restored: no
# permanent sys.modules surgery).
_REAL_MODULES = (
    (PKG, "universal_room_automation/__init__.py", "async_unload_entry"),
    (f"{PKG}.domain_coordinators", "domain_coordinators/__init__.py", None),
    (f"{PKG}.const", "universal_room_automation/const.py", "BLE_LEADS_ARM_S"),
    (f"{PKG}.person_coordinator", "person_coordinator.py", "person_state_for_trust"),
    (f"{PKG}.domain_coordinators.hvac_const", "hvac_const.py", "DEFAULT_FAN_VACANCY_HOLD"),
    (f"{PKG}.domain_coordinators.hvac_zones", "hvac_zones.py", "ZoneManager"),
    (f"{PKG}.domain_coordinators.hvac_fans", "hvac_fans.py", "FanController"),
    (f"{PKG}.aggregation", "aggregation.py", "ZoneAnyoneBinarySensor"),
    (f"{PKG}.camera_census", "camera_census.py", "PersonCensus"),
    (f"{PKG}.switch", "universal_room_automation/switch.py", "PresenceBleLeadsEnabledSwitch"),
)


def _is_real(mod, suffix, attr):
    """Real = the on-disk file, fully executed (a sibling may register a
    spec'd-but-unexecuted module that has __file__ and nothing else)."""
    from unittest.mock import Mock
    if mod is None or isinstance(mod, Mock):
        return False
    f = getattr(mod, "__file__", None)
    if not (isinstance(f, str) and f.replace("\\", "/").endswith(suffix)):
        return False
    return attr is None or attr in vars(mod)


@pytest.fixture(autouse=True)
def _real_modules():
    replaced: dict = {}
    _missing = object()
    for name, suffix, attr in _REAL_MODULES:
        cur = sys.modules.get(name)
        if _is_real(cur, suffix, attr):
            continue
        replaced[name] = cur if cur is not None else _missing
        sys.modules.pop(name, None)
    before = set(sys.modules)
    try:
        if replaced:
            for name, _suffix, _attr in _REAL_MODULES:
                importlib.import_module(name)
        yield
    finally:
        if replaced:
            for name in set(sys.modules) - before:
                if name.startswith(PKG):
                    sys.modules.pop(name, None)
            for name, prev in replaced.items():
                if prev is _missing:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = prev


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _St:
    def __init__(self, state, attributes=None, last_updated=None):
        self.state = state
        self.attributes = attributes or {}
        self.last_changed = last_updated or T0
        self.last_updated = last_updated or T0


class _States:
    def __init__(self):
        self.m: dict = {}

    def get(self, eid):
        return self.m.get(eid)


class _Hass:
    def __init__(self):
        self.data: dict = {DOMAIN: {}}
        self.states = _States()
        self.bus = SimpleNamespace(async_fire=lambda *a, **k: None)

    def async_create_task(self, coro, *a, **k):
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass

    def set(self, eid, state, attrs=None, last_updated=None):
        self.states.m[eid] = _St(state, attrs, last_updated)


class _Clock:
    """Scoped stand-in for person_coordinator.dt_util (module attribute)."""

    def __init__(self, now):
        self.t = now

    def now(self):
        return self.t

    def utcnow(self):
        return self.t


class _Reg:
    def __init__(self, eid):
        self.eid = eid

    def async_get_entity_id(self, domain, platform, unique_id):
        if (domain, platform, unique_id) == (
            "sensor", "bermuda", "BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT",
        ):
            return self.eid
        return None


class _Track:
    """Records async_track_state_change_event registrations."""

    def __init__(self):
        self.subs: list = []
        self.unsub_calls = 0

    def __call__(self, hass, entity_ids, cb):
        self.subs.append((list(entity_ids), cb))

        def _unsub():
            self.unsub_calls += 1
        return _unsub


@pytest.fixture
def env(monkeypatch):
    """A real PersonTrackingCoordinator on a fake hass, clock + registry +
    listener factory scoped through monkeypatch (restored on teardown)."""
    pc = _pc()
    hass = _Hass()
    entry = MagicMock()
    entry.data = {"tracked_persons": [OJI]}
    entry.options = {}
    unload_cbs: list = []
    entry.async_on_unload = lambda cb: unload_cbs.append(cb)
    import homeassistant.helpers.frame as _frame
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        coord = pc.PersonTrackingCoordinator(hass, entry)
    coord.hass = hass
    coord.data = {}
    coord.integration_entry = entry
    coord._pre_arrival_enabled = False
    clock = _Clock(T0)
    monkeypatch.setattr(pc, "dt_util", clock)
    reg = _Reg(PROXY)
    monkeypatch.setattr(pc.er, "async_get", lambda _h: reg)
    track = _Track()
    monkeypatch.setattr(pc, "async_track_state_change_event", track)

    async def _noop(*_a, **_k):
        return None

    coord._build_scanner_room_map = _noop
    ns = SimpleNamespace(pc=pc, hass=hass, coord=coord, clock=clock, reg=reg,
                         track=track, entry=entry, unload_cbs=unload_cbs)
    return ns


def _tuple_1024(hass, *, irk="not_home", berm="not_home", gps="home",
                wifi=None, person="home", proxy="55", with_ble=True,
                with_gps=True):
    """The 10-24 evidence tuple, each axis overridable."""
    trackers = []
    if with_gps:
        hass.set(GPS, gps, {"source_type": "gps"})
        trackers.append(GPS)
    if with_ble:
        hass.set(IRK, irk, {"source_type": "bluetooth_le"})
        hass.set(BERM, berm, {"source_type": "bluetooth_le"})
        trackers += [IRK, BERM]
    if wifi is not None:
        hass.set(ROUTER, wifi, {"source_type": "router"})
        trackers.append(ROUTER)
    hass.set(OJI_ENTITY, person, {"device_trackers": trackers})
    if proxy is not None:
        hass.set(PROXY, proxy)


def _bermuda_branch(coord, hass):
    """Site 1: a Bermuda area sensor exists but resolves no room."""
    hass.set(AREA, "unknown")

    async def _area(_name):
        return AREA
    coord._find_bermuda_area_sensor = _area


def _no_bermuda_branch(coord):
    """Site 2: no Bermuda area sensor at all."""
    async def _none(_name):
        return None
    coord._find_bermuda_area_sensor = _none


def _tick(coord):
    return asyncio.run(coord._async_update_data())


def _arm(env, seconds=400):
    """Fleet healthy since `seconds` before the clock (armed if >= 360)."""
    env.coord._fleet_healthy_since = env.clock.t - timedelta(seconds=seconds)


def _row(result):
    return result[OJI]


# ---------------------------------------------------------------------------
# D1 — the gate (both sites), fleet guard, boot latch
# ---------------------------------------------------------------------------


def test_frozen_gps_home_ble_not_home_goes_away(env):
    """Site 1 anchor. The 10-24 tuple on an armed fleet -> away 0.82."""
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    row = _row(_tick(env.coord))
    assert row["location"] == "away"
    assert row["tracking_status"] == "active"
    assert row["tracking_reason"] == "away_ble_silent_only"
    assert row["confidence"] == 0.82
    assert row["tracker_sources"]["gps"] == "home"
    assert env.coord._person_was_away[OJI] is True
    assert env.coord._gps_home_overruled == frozenset({OJI})


def test_no_bermuda_branch_twin_site(env):
    """Site 2 anchor (no Bermuda sensor): identical outcome to site 1."""
    _tuple_1024(env.hass)
    _no_bermuda_branch(env.coord)
    _arm(env)
    row = _row(_tick(env.coord))
    assert (row["location"], row["tracking_status"], row["tracking_reason"],
            row["confidence"]) == ("away", "active", "away_ble_silent_only", 0.82)
    assert env.coord._gps_home_overruled == frozenset({OJI})


@pytest.mark.parametrize("branch", ["bermuda", "no_bermuda"])
def test_one_ble_tracker_home_keeps_home(env, branch):
    _tuple_1024(env.hass, irk="home")
    (_bermuda_branch(env.coord, env.hass) if branch == "bermuda"
     else _no_bermuda_branch(env.coord))
    _arm(env)
    row = _row(_tick(env.coord))
    assert row["location"] == "home"
    assert row["tracking_reason"] == "home_ble_silent"
    assert row["confidence"] == 0.75
    assert env.coord._gps_home_overruled == frozenset()


@pytest.mark.parametrize("bad", ["unavailable", "unknown"])
def test_ble_unavailable_keeps_home_ialpha(env, bad):
    """A BLE tracker with no opinion never votes away (I-alpha)."""
    _tuple_1024(env.hass, berm=bad)
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    row = _row(_tick(env.coord))
    assert row["location"] == "home"
    assert env.coord._gps_home_overruled == frozenset()


def test_wifi_home_witness_keeps_home(env):
    """WiFi home is a home witness: row 2 home 0.85 (BLE silent, fleet
    live is irrelevant here: the matrix degrades silent->indeterminate on
    empty data, so row 3 0.80)."""
    _tuple_1024(env.hass, wifi="home")
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    row = _row(_tick(env.coord))
    assert row["location"] == "home"
    assert row["confidence"] == 0.80
    assert row["tracking_reason"] == "home_ble_silent"


def test_row4_unchanged_wifi_not_home(env):
    """Row 4 (GPS home + WiFi not_home) dropped per operator: unchanged."""
    _tuple_1024(env.hass, wifi="not_home")
    _no_bermuda_branch(env.coord)
    _arm(env)
    row = _row(_tick(env.coord))
    assert row["location"] == "home"
    assert row["confidence"] == 0.5
    assert row["tracking_reason"] == "anomalous_gps_stale_local_gone"


@pytest.mark.parametrize("branch", ["bermuda", "no_bermuda"])
def test_no_ble_tracker_keeps_home(env, branch):
    _tuple_1024(env.hass, with_ble=False)
    (_bermuda_branch(env.coord, env.hass) if branch == "bermuda"
     else _no_bermuda_branch(env.coord))
    _arm(env)
    row = _row(_tick(env.coord))
    assert row["location"] == "home"
    assert env.coord._gps_home_overruled == frozenset()


@pytest.mark.parametrize("gps_case", ["unknown", "missing"])
def test_fallback_home_without_witness_overruled(env, gps_case):
    """person.state home with GPS unknown / no GPS tracker (HA aggregation
    is the only home source) + BLE away-evidence -> away."""
    if gps_case == "unknown":
        _tuple_1024(env.hass, gps="unavailable")
    else:
        _tuple_1024(env.hass, with_gps=False)
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    row = _row(_tick(env.coord))
    assert row["location"] == "away"
    assert row["tracking_reason"] == "away_ble_silent_only"
    assert row["confidence"] == 0.82


def test_side_effects_match_s3_arm(env):
    """The overrule produces exactly the S3 else-arm side effects."""
    # Reference: S3 arm driven by person.state not_home on a twin coord.
    _tuple_1024(env.hass, person="not_home")
    _bermuda_branch(env.coord, env.hass)
    ref = _row(_tick(env.coord))
    ref_state = (dict(env.coord._person_lost_since),
                 dict(env.coord._lost_away_since),
                 dict(env.coord._person_was_away))
    assert ref["location"] == "away" and ref["tracking_status"] == "active"
    # Reset and drive the overrule.
    env.coord._person_lost_since.clear()
    env.coord._lost_away_since.clear()
    env.coord._person_was_away.clear()
    env.coord.data = {}
    _tuple_1024(env.hass, person="home")
    _arm(env)
    got = _row(_tick(env.coord))
    assert (got["location"], got["tracking_status"]) == ("away", "active")
    assert env.coord._person_lost_since == {OJI: T0} == ref_state[0]
    assert env.coord._lost_away_since == {OJI: T0} == ref_state[1]
    assert env.coord._person_was_away == {OJI: True} == ref_state[2]
    assert got["method"] == ref["method"] == "person_state"


def test_pre_arrival_fires_on_ble_return_after_overrule(env, monkeypatch):
    """Q3: an overrule arms BLE pre-arrival; the next BLE room fix fires
    SIGNAL_PERSON_ARRIVING."""
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    env.coord._pre_arrival_enabled = True
    env.coord.data = _tick(env.coord)
    assert env.coord._person_was_away[OJI] is True
    sent = []
    import homeassistant.helpers.dispatcher as _disp
    monkeypatch.setattr(_disp, "async_dispatcher_send",
                        lambda hass, sig, payload: sent.append((sig, payload)))
    # BLE re-acquires the phone in a room.
    env.hass.set(AREA, "study_a")
    env.coord._resolve_person_room = lambda area: "Study A"

    async def _conf(*_a, **_k):
        return 0.9
    env.coord._calculate_confidence = _conf
    env.clock.t = T0 + timedelta(seconds=30)
    row = _row(_tick(env.coord))
    assert row["location"] == "Study A"
    assert len(sent) == 1
    assert sent[0][1] == {"person_entity": OJI_ENTITY, "source": "ble"}


@pytest.mark.parametrize("count", ["0", "unavailable", "unknown", "abc"])
def test_fleet_dead_keeps_home(env, count):
    """F1: all proxies dead (or unreadable) -> byte-identical home."""
    _tuple_1024(env.hass, proxy=count)
    _bermuda_branch(env.coord, env.hass)
    _arm(env, seconds=10_000)
    row = _row(_tick(env.coord))
    assert row["location"] == "home"
    assert row["tracking_reason"] == "home_ble_silent"
    assert env.coord._fleet_healthy_since is None


@pytest.mark.parametrize("count,expect", [("29", "home"), ("30", "away"),
                                          ("31", "away")])
def test_fleet_below_floor_keeps_home(env, count, expect):
    """Floor 30 inclusive (literal boundary, not the imported constant)."""
    _tuple_1024(env.hass, proxy=count)
    _bermuda_branch(env.coord, env.hass)
    _arm(env, seconds=10_000)
    assert _row(_tick(env.coord))["location"] == expect


@pytest.mark.parametrize("held,expect", [(359, "home"), (360, "away"),
                                         (361, "away")])
def test_arm_window_boundary(env, held, expect):
    """Count 31 held 359 s -> home; 360 s -> away (literal boundary)."""
    _tuple_1024(env.hass, proxy="31")
    _bermuda_branch(env.coord, env.hass)
    _arm(env, seconds=held)
    assert _row(_tick(env.coord))["location"] == expect


def test_unsampled_dip_resets_latch_via_listener(env):
    """F1 dip: armed; listener sees 0 then 55 sixty seconds later with no
    tick between; the next tick must NOT overrule until 360 s after the 55."""
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _arm(env, seconds=10_000)
    env.coord.data = _tick(env.coord)          # registers the listener
    assert _row(env.coord.data)["location"] == "away"
    assert len(env.track.subs) == 1
    ids, cb = env.track.subs[0]
    assert ids == [PROXY]
    # Dip between ticks (the sensor reads 55 again by the next tick).
    env.clock.t = T0 + timedelta(seconds=5)
    cb(SimpleNamespace(data={"new_state": _St("0")}))
    env.clock.t = T0 + timedelta(seconds=65)
    cb(SimpleNamespace(data={"new_state": _St("55")}))
    env.clock.t = T0 + timedelta(seconds=90)
    assert _row(_tick(env.coord))["location"] == "home"
    env.clock.t = T0 + timedelta(seconds=65 + 359)
    assert _row(_tick(env.coord))["location"] == "home"
    env.clock.t = T0 + timedelta(seconds=65 + 360)
    assert _row(_tick(env.coord))["location"] == "away"


def test_boot_latch_keeps_home(env):
    """F3: fresh process, empty data, count 55, trackers not_home, GPS home
    -> home for the first 360 s; away at 360 s."""
    assert env.coord._fleet_healthy_since is None
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    assert _row(_tick(env.coord))["location"] == "home"
    env.clock.t = T0 + timedelta(seconds=359)
    assert _row(_tick(env.coord))["location"] == "home"
    env.clock.t = T0 + timedelta(seconds=360)
    assert _row(_tick(env.coord))["location"] == "away"


def test_boot_latch_one_tracker_recovers_keeps_home(env):
    """F3 second half: ONE tracker re-reads home at 100 s -> still home
    after 360 s (the fastest-recovering tracker governs)."""
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    assert _row(_tick(env.coord))["location"] == "home"
    env.clock.t = T0 + timedelta(seconds=100)
    env.hass.set(BERM, "home", {"source_type": "bluetooth_le"})
    _tick(env.coord)
    env.clock.t = T0 + timedelta(seconds=400)
    assert _row(_tick(env.coord))["location"] == "home"


def test_proxy_entity_missing_rule_off(env):
    """No Bermuda proxy entity in the registry -> rule off (home)."""
    env.reg.eid = None
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _arm(env, seconds=10_000)
    assert _row(_tick(env.coord))["location"] == "home"
    assert env.coord._fleet_healthy_since is None
    assert env.track.subs == []


def test_listener_unsubscribed_on_unload(env):
    """R2-2: the unsub reaches entry.async_on_unload AND async_teardown;
    release is idempotent across both paths."""
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _tick(env.coord)
    assert len(env.track.subs) == 1
    assert len(env.unload_cbs) == 1
    asyncio.run(env.coord.async_teardown())
    assert env.track.unsub_calls == 1
    for cb in env.unload_cbs:
        cb()
    assert env.track.unsub_calls == 1


def test_listener_registers_on_late_bermuda_load(env):
    """R2-2: Bermuda loads after URA -> the first tick that resolves the
    entity subscribes, once; a later unload still releases it."""
    env.reg.eid = None
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _tick(env.coord)
    assert env.track.subs == []
    env.reg.eid = PROXY
    env.clock.t = T0 + timedelta(seconds=30)
    _tick(env.coord)
    env.clock.t = T0 + timedelta(seconds=60)
    _tick(env.coord)
    assert len(env.track.subs) == 1
    assert len(env.unload_cbs) == 1
    env.unload_cbs[0]()
    assert env.track.unsub_calls == 1


def test_overruled_set_assigned_once_after_loop(env):
    """R2-1: during the tick (at an await between persons) readers see the
    PREVIOUS tick's complete set; the new set lands once, after the loop."""
    env.coord.tracked_persons = [OJI, "Ezinne"]
    _tuple_1024(env.hass)
    env.hass.set("person.ezinne", "not_home", {"device_trackers": []})
    env.hass.set(AREA, "unknown")
    _arm(env)
    prev = frozenset({"Previous Tick"})
    env.coord._gps_home_overruled = prev
    seen = []

    async def _area(name):
        seen.append((name, env.coord._gps_home_overruled))
        await asyncio.sleep(0)
        return AREA
    env.coord._find_bermuda_area_sensor = _area
    _tick(env.coord)
    assert seen == [(OJI, prev), ("Ezinne", prev)]
    assert isinstance(env.coord._gps_home_overruled, frozenset)
    assert env.coord._gps_home_overruled == frozenset({OJI})


def test_overruled_set_kept_on_update_failed(env):
    """UpdateFailed keeps the previous set (matches the kept self.data)."""
    prev = frozenset({OJI})
    env.coord._gps_home_overruled = prev
    _tuple_1024(env.hass)

    async def _boom(*_a, **_k):
        raise RuntimeError("scanner map failed")
    env.coord._build_scanner_room_map = _boom
    with pytest.raises(Exception):
        _tick(env.coord)
    assert env.coord._gps_home_overruled is prev


def test_fleet_armed_literal_boundaries(env):
    """Unit boundary on `_fleet_armed` with literal seconds."""
    c = env.coord
    c._fleet_healthy_since = None
    assert c._fleet_armed(T0) is False
    c._fleet_healthy_since = T0
    assert c._fleet_armed(T0 + timedelta(seconds=359)) is False
    assert c._fleet_armed(T0 + timedelta(seconds=360)) is True
    assert c._fleet_armed(T0 + timedelta(seconds=361)) is True


# ---------------------------------------------------------------------------
# D2 — switch
# ---------------------------------------------------------------------------


def _presence_with_switch(hass, on: bool):
    pres = SimpleNamespace(_ble_leads_enabled=on)
    hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": pres})
    return pres


@pytest.mark.parametrize("branch", ["bermuda", "no_bermuda"])
def test_switch_off_restores_gps_proof(env, branch):
    """INV-3: switch OFF -> the overrule tuple stays home (develop)."""
    _presence_with_switch(env.hass, False)
    _tuple_1024(env.hass)
    (_bermuda_branch(env.coord, env.hass) if branch == "bermuda"
     else _no_bermuda_branch(env.coord))
    _arm(env, seconds=10_000)
    row = _row(_tick(env.coord))
    assert row["location"] == "home"
    assert row["tracking_reason"] == "home_ble_silent"
    assert env.coord._gps_home_overruled == frozenset()


def test_switch_on_explicit_overrules(env):
    """Discriminator for the switch test: the same tuple with the switch
    present and ON overrules."""
    _presence_with_switch(env.hass, True)
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    assert _row(_tick(env.coord))["location"] == "away"


def test_switch_off_effective_state_raw(env):
    """Switch flipped OFF after an overrule tick: effective state is raw
    immediately (no 30 s wait for the next tick)."""
    pres = _presence_with_switch(env.hass, True)
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    env.coord.data = _tick(env.coord)
    assert env.coord.effective_person_state(OJI_ENTITY) == "not_home"
    pres._ble_leads_enabled = False
    assert env.coord.effective_person_state(OJI_ENTITY) == "home"


def test_ble_leads_switch_restore_off_fast_and_deferred(monkeypatch):
    """The new switch restores OFF on both paths (fast + deferred READY),
    and backs `_ble_leads_enabled` / `_ble_leads_suppressed_since`."""
    sw_mod = importlib.import_module(f"{PKG}.switch")
    import homeassistant.helpers.dispatcher as _disp

    async def _noop(self):
        return None
    # Neutralise the parents' async_added_to_hass (RestoreEntity needs the
    # restore-state store); whatever classes the switch module bound.
    cls = sw_mod.PresenceBleLeadsEnabledSwitch
    # Setting it on the first parent after the base class makes super()
    # resolve there (real HA or a sibling's stub alike); restored on exit.
    monkeypatch.setattr(cls.__mro__[2], "async_added_to_hass", _noop,
                        raising=False)
    monkeypatch.setattr(_disp, "async_dispatcher_connect",
                        lambda *a, **k: (lambda: None))

    def _make(hass):
        sw = sw_mod.PresenceBleLeadsEnabledSwitch(hass, MagicMock())
        sw.hass = hass
        sw.async_write_ha_state = lambda: None
        sw.async_on_remove = lambda _cb: None

        async def _last():
            return _St("off", {"suppressed_since": "2026-10-24T10:00:00+00:00"})
        sw.async_get_last_state = _last
        return sw

    # Fast path: presence present.
    hass = _Hass()
    pres = SimpleNamespace(_ble_leads_enabled=True,
                           _ble_leads_suppressed_since=None)
    hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": pres})
    sw = _make(hass)
    assert sw.is_on is True
    asyncio.run(sw.async_added_to_hass())
    assert pres._ble_leads_enabled is False
    assert pres._ble_leads_suppressed_since == "2026-10-24T10:00:00+00:00"
    assert sw.is_on is False
    assert sw._attr_unique_id == f"{DOMAIN}_presence_ble_leads_enabled"
    assert sw._attr_name == "BLE Leads Home/Away"
    # Deferred path: presence missing at restore, READY lands later.
    hass2 = _Hass()
    mgr = SimpleNamespace(coordinators={})
    hass2.data[DOMAIN]["coordinator_manager"] = mgr
    sw2 = _make(hass2)
    asyncio.run(sw2.async_added_to_hass())
    pres2 = SimpleNamespace(_ble_leads_enabled=True,
                            _ble_leads_suppressed_since=None)
    mgr.coordinators["presence"] = pres2
    sw2._handle_presence_ready()
    assert pres2._ble_leads_enabled is False
    assert pres2._ble_leads_suppressed_since == "2026-10-24T10:00:00+00:00"


# ---------------------------------------------------------------------------
# D1b — effective_person_state + the §6b trust readers
# ---------------------------------------------------------------------------


def _overruled_pc(env, raw="home"):
    """Drive a real overrule tick so the coordinator holds Oji overruled,
    then register it in hass.data where the trust wrapper finds it."""
    _tuple_1024(env.hass, person=raw)
    _bermuda_branch(env.coord, env.hass)
    _arm(env)
    env.coord.data = _tick(env.coord)
    env.hass.data[DOMAIN]["person_coordinator"] = env.coord
    return env.coord


@pytest.mark.parametrize("raw", ["home", "not_home", "study_a", "unknown", None])
def test_effective_state_only_differs_when_overruled(env, raw):
    pc = env.pc
    coord = env.coord
    env.hass.data[DOMAIN]["person_coordinator"] = coord
    # Not overruled: raw verbatim for every raw state (incl. missing entity).
    if raw is None:
        env.hass.states.m.pop(OJI_ENTITY, None)
    else:
        env.hass.set(OJI_ENTITY, raw, {"device_trackers": []})
    coord._gps_home_overruled = frozenset()
    assert coord.effective_person_state(OJI_ENTITY) == raw
    assert pc.person_state_for_trust(env.hass, OJI_ENTITY) == raw
    # Overruled AND URA location away -> not_home.
    coord._gps_home_overruled = frozenset({OJI})
    coord.data = {OJI: {"location": "away"}}
    assert coord.effective_person_state(OJI_ENTITY) == "not_home"
    # Overruled but URA location not away (cross-check) -> raw.
    coord.data = {OJI: {"location": "home"}}
    assert coord.effective_person_state(OJI_ENTITY) == raw
    # Another person is unaffected.
    env.hass.set("person.ezinne", "home", {})
    coord.data = {OJI: {"location": "away"}}
    assert coord.effective_person_state("person.ezinne") == "home"


def test_effective_state_fallback_no_coordinator(env):
    pc = env.pc
    env.hass.set(OJI_ENTITY, "home", {})
    env.hass.data[DOMAIN].pop("person_coordinator", None)
    assert pc.person_state_for_trust(env.hass, OJI_ENTITY) == "home"
    assert pc.person_state_for_trust(env.hass, "person.ghost") is None
    # A non-coordinator object (MagicMock) never leaks a non-str value.
    env.hass.data[DOMAIN]["person_coordinator"] = MagicMock()
    assert pc.person_state_for_trust(env.hass, OJI_ENTITY) == "home"
    # hass without .data at all -> raw.
    bare = SimpleNamespace(states=env.hass.states)
    assert pc.person_state_for_trust(bare, OJI_ENTITY) == "home"


class _Zone(SimpleNamespace):
    pass


def _agg_fake_self(env, house_state, presence=None):
    zone = _Zone(zone_id="zone_1", zone_name="Entertainment",
                 zone_persons=[OJI_ENTITY])
    hvac = SimpleNamespace(_zone_manager=SimpleNamespace(zones={"zone_1": zone}))
    coords = {"hvac": hvac}
    if presence is not None:
        coords["presence"] = presence
    env.hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
        house_state=house_state, coordinators=coords)
    fake = MagicMock()
    fake.hass = env.hass
    fake.zone = "Entertainment"
    fake._get_zone_coordinators = lambda: []
    return fake


class _FiredPresence:
    _ble_leads_enabled = True

    def should_veto_due_to_reliable_signals(self, **kw):
        return SimpleNamespace(fired=True, reason="zone_persons_home")


@pytest.mark.parametrize("site", ["sleep", "nonsleep"])
def test_zone_persons_home_veto_uses_effective_state(env, site):
    """aggregation zone_persons_home veto (both sites): raw home -> veto;
    overruled -> no veto."""
    agg = importlib.import_module(f"{PKG}.aggregation")
    cls = agg.ZoneAnyoneBinarySensor
    fn = (cls._sleep_person_fallback_occupied if site == "sleep"
          else cls._nonsleep_person_fallback_occupied)
    house = "sleep" if site == "sleep" else "home_day"
    # Not overruled: person.state home -> fallback engages.
    env.hass.set(OJI_ENTITY, "home", {})
    env.hass.data[DOMAIN]["person_coordinator"] = env.coord
    fake = _agg_fake_self(env, house, presence=_FiredPresence())
    assert fn(fake) is True
    # Overruled tick -> the same raw "home" no longer vetoes.
    _overruled_pc(env)
    fake = _agg_fake_self(env, house, presence=_FiredPresence())
    assert env.hass.states.get(OJI_ENTITY).state == "home"
    assert fn(fake) is False


def test_hvac_zone_has_home_person_effective(env):
    hz = importlib.import_module(f"{PKG}.domain_coordinators.hvac_zones")
    zone = _Zone(zone_persons=[OJI_ENTITY])
    env.hass.set(OJI_ENTITY, "home", {})
    env.hass.data[DOMAIN]["person_coordinator"] = env.coord
    assert hz.ZoneManager.zone_has_home_person(None, zone, env.hass) is True
    _overruled_pc(env)
    assert hz.ZoneManager.zone_has_home_person(None, zone, env.hass) is False


def test_hvac_fans_night_hold_effective(env):
    """hvac_fans night vacancy hold: raw home extends the hold; an
    overruled person does not."""
    hf = importlib.import_module(f"{PKG}.domain_coordinators.hvac_fans")
    hc = importlib.import_module(f"{PKG}.domain_coordinators.hvac_const")
    c = _const()

    def _run():
        zone = _Zone(zone_id="z1", target_temp_high=74.0,
                     zone_persons=[OJI_ENTITY], rooms=[], room_conditions=[])
        zm = SimpleNamespace(zones={"z1": zone})
        ctrl = hf.FanController(env.hass, zm)
        ctrl._house_state = "sleep"
        rf = hf.RoomFanState(
            room_name="master_bedroom", zone_id="z1",
            room_type=c.ROOM_TYPE_BEDROOM, fan_entities=["fan.master"],
            is_on=True, speed_pct=33, trigger="temperature",
            last_on_time=datetime.now().isoformat(),
            fan_sleep_policy=c.FAN_SLEEP_REDUCE,
        )
        rf.vacancy_detected_time = (
            datetime.now() - timedelta(seconds=hc.DEFAULT_FAN_VACANCY_HOLD + 60)
        ).isoformat()
        should_on, _t, _s = ctrl._evaluate_temp_fan(
            rf, room_temp=72.0, setpoint_high=74.0, occupied=False,
            now=datetime.now(),
        )
        return should_on

    env.hass.set(OJI_ENTITY, "home", {})
    env.hass.data[DOMAIN]["person_coordinator"] = env.coord
    assert _run() is True
    _overruled_pc(env)
    assert _run() is False


def test_face_latch_drops_overruled_person(env):
    """camera_census stale-face latch: an overruled person is dropped from
    the face-recognized list; a raw-home person is kept."""
    cc = importlib.import_module(f"{PKG}.camera_census")
    now = datetime.now(timezone.utc)

    def _census():
        env.hass.set("sensor.frigate_oji_last_camera_2", "front_door",
                     last_updated=now - timedelta(seconds=30))
        env.hass.config_entries = SimpleNamespace(async_entries=lambda _d: [
            SimpleNamespace(data={cc.CONF_ENTRY_TYPE: cc.ENTRY_TYPE_INTEGRATION,
                                  "tracked_persons": [OJI_ENTITY]}, options={}),
        ])
        census = object.__new__(cc.PersonCensus)
        census.hass = env.hass
        census._frigate_person_last_camera_map = {
            "oji": "sensor.frigate_oji_last_camera_2"}
        return census

    env.hass.set(OJI_ENTITY, "home", {})
    env.hass.data[DOMAIN]["person_coordinator"] = env.coord
    assert "oji_udezue" in _census()._get_face_recognized_person_names(now)
    _overruled_pc(env)
    assert env.hass.states.get(OJI_ENTITY).state == "home"
    assert "oji_udezue" not in _census()._get_face_recognized_person_names(now)


# ---------------------------------------------------------------------------
# R2-2 — the unload path releases the listener before the pop
# ---------------------------------------------------------------------------


def test_unload_entry_tears_down_person_coordinator_listener(env):
    """Drive the REAL integration-entry `async_unload_entry`: the person
    coordinator's proxy listener is released (async_teardown) while the
    coordinator is still registered, then the reference is popped."""
    init_mod = importlib.import_module(PKG)
    const = _const()
    _tuple_1024(env.hass)
    _bermuda_branch(env.coord, env.hass)
    _tick(env.coord)
    assert len(env.track.subs) == 1 and env.track.unsub_calls == 0
    order = []
    real_teardown = env.coord.async_teardown

    async def _spy_teardown():
        order.append(("teardown",
                      "person_coordinator" in env.hass.data[DOMAIN]))
        await real_teardown()
    env.coord.async_teardown = _spy_teardown
    env.hass.data[DOMAIN]["person_coordinator"] = env.coord

    async def _unload_platforms(entry, platforms):
        return True
    env.hass.config_entries = SimpleNamespace(
        async_unload_platforms=_unload_platforms,
        async_entries=lambda *a, **k: [],
    )
    entry = MagicMock()
    entry.data = {const.CONF_ENTRY_TYPE: const.ENTRY_TYPE_INTEGRATION}
    entry.entry_id = "integration_entry"
    asyncio.run(init_mod.async_unload_entry(env.hass, entry))
    assert order == [("teardown", True)]
    assert env.track.unsub_calls == 1
    assert "person_coordinator" not in env.hass.data[DOMAIN]

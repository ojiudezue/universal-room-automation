"""CENSUS-BLE-OVER-FACE-1 — the census face latch follows BLE Leads.

Plan: docs/planning/PLANNING_census_ble_over_face.md (rev 4).

Drives the REAL PersonCensus._get_face_recognized_person_names and the
REAL _apply_enhanced_house_census (incl. the real BLE area-cancel in
_get_unrecognized_camera_count and the real ceiling clamp), against a REAL
PersonTrackingCoordinator whose effective_person_state is reached through
the real person_state_for_trust wrapper. Live config shape: the
integration entry carries display names in `data["tracked_persons"]`
(what person_coordinator reads) and `person.<slug>` ids in
`options["tracked_persons"]` (what the census merges and reads), exactly
as core.config_entries on 2026-10-24.

Oracles are hand-derived (plan §3 / §4.3 arithmetic), not re-computed by
the code under test.
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
T0 = datetime(2026, 10, 24, 20, 0, 0, tzinfo=timezone.utc)

OJI = "Oji Udezue"
OJI_ENTITY = "person.oji_udezue"
OJI_FACE = "sensor.frigate_oji_last_camera_2"
GPS = "device_tracker.oji_phone"
IRK = "device_tracker.private_ble_device_8ce182"
BERM = "device_tracker.oji_bermuda_tracker"
AREA = "sensor.oji_udezue_area"
PROXY = "sensor.bermuda_global_active_proxy_count"

_REAL_MODULES = (
    (f"{PKG}.const", "universal_room_automation/const.py",
     "CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS"),
    (f"{PKG}.person_coordinator", "person_coordinator.py",
     "person_state_for_trust"),
    (f"{PKG}.camera_census", "camera_census.py", "PersonCensus"),
)


def _is_real(mod, suffix, attr):
    from unittest.mock import Mock
    if mod is None or isinstance(mod, Mock):
        return False
    f = getattr(mod, "__file__", None)
    if not (isinstance(f, str) and f.replace("\\", "/").endswith(suffix)):
        return False
    return attr is None or attr in vars(mod)


@pytest.fixture(autouse=True)
def _real_modules():
    """Serve the real on-disk modules for each test; restore afterwards
    (scoped: no permanent sys.modules surgery)."""
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
            for name, _s, _a in _REAL_MODULES:
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


def _mod(name):
    return importlib.import_module(f"{PKG}.{name}")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _St:
    def __init__(self, state, attributes=None, last_changed=None):
        self.state = state
        self.attributes = attributes or {}
        self.last_changed = last_changed or T0
        self.last_updated = last_changed or T0


class _States:
    def __init__(self):
        self.m: dict = {}

    def get(self, eid):
        return self.m.get(eid)


class _Entry:
    def __init__(self, data, options):
        self.data = data
        self.options = options


class _ConfigEntries:
    def __init__(self, entries):
        self._e = entries

    def async_entries(self, _domain=None):
        return self._e


class _Hass:
    def __init__(self, entries):
        self.data: dict = {DOMAIN: {}}
        self.states = _States()
        self.config_entries = _ConfigEntries(entries)
        self.bus = SimpleNamespace(async_fire=lambda *a, **k: None)

    def async_create_task(self, coro, *a, **k):
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass

    def set(self, eid, state, attrs=None, last_changed=None):
        self.states.m[eid] = _St(state, attrs, last_changed)


def _integration_entry(cc):
    """Live shape (2026-10-24): names in data, person ids in options."""
    return _Entry(
        {
            cc.CONF_ENTRY_TYPE: cc.ENTRY_TYPE_INTEGRATION,
            "tracked_persons": ["Ezinne", OJI, "Jaya", "Ziri"],
        },
        {
            "tracked_persons": [
                "person.ezinne", OJI_ENTITY, "person.jaya", "person.ziri",
            ],
        },
    )


def _pc_coord(hass, entry):
    pc = _mod("person_coordinator")
    import homeassistant.helpers.frame as _frame
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        coord = pc.PersonTrackingCoordinator(hass, entry)
    coord.hass = hass
    coord.integration_entry = entry
    coord.data = {}
    return coord


def _presence_switch(hass, on: bool):
    """Backing field of switch BLE Leads Home/Away (read by
    PersonTrackingCoordinator._ble_leads_enabled)."""
    pres = SimpleNamespace(_ble_leads_enabled=on)
    hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": pres},
    )
    return pres


def _census(hass):
    cc = _mod("camera_census")
    census = object.__new__(cc.PersonCensus)
    census.hass = hass
    census._frigate_person_last_camera_map = {"oji": OJI_FACE}
    census._face_dropped_ble_overrule_count = 0
    return census


@pytest.fixture
def world():
    """Oji overruled by BLE (GPS home, BLE not_home) and URA location away;
    Ezinne + Jaya BLE-located in the kitchen; a fresh 'Oji' face."""
    cc = _mod("camera_census")
    entry = _integration_entry(cc)
    hass = _Hass([entry])
    coord = _pc_coord(hass, entry)
    hass.data[DOMAIN]["person_coordinator"] = coord
    pres = _presence_switch(hass, True)
    hass.set(OJI_ENTITY, "home", {"device_trackers": []})  # GPS-led raw home
    hass.set(OJI_FACE, "family_room", last_changed=T0 - timedelta(seconds=60))
    coord._gps_home_overruled = frozenset({OJI})
    coord.data = {
        OJI: {"location": "away", "tracking_status": "active"},
        "Ezinne": {"location": "Kitchen", "tracking_status": "active"},
        "Jaya": {"location": "Kitchen", "tracking_status": "active"},
    }
    census = _census(hass)
    return SimpleNamespace(hass=hass, coord=coord, pres=pres, census=census,
                           cc=cc)


def _faces(w):
    return w.census._get_face_recognized_person_names(T0)


# ---------------------------------------------------------------------------
# D1 — the guard
# ---------------------------------------------------------------------------


def test_census_face_dropped_when_ble_overruled(world):
    assert _faces(world) == []
    assert world.census._face_dropped_ble_overrule_count == 1


def test_census_face_kept_when_ble_leads_off(world):
    world.pres._ble_leads_enabled = False
    assert _faces(world) == ["oji_udezue"]
    assert world.census._face_dropped_ble_overrule_count == 0


def test_census_face_kept_when_flag_false(world, monkeypatch):
    monkeypatch.setattr(world.cc._ura_const,
                        "CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS", False)
    pc = _mod("person_coordinator")
    calls: list = []
    real = pc.person_state_for_trust

    def _spy(hass, eid):
        calls.append(eid)
        return real(hass, eid)

    monkeypatch.setattr(pc, "person_state_for_trust", _spy)
    assert _faces(world) == ["oji_udezue"]
    assert calls == []
    assert world.census._face_dropped_ble_overrule_count == 0


def test_census_helper_called_when_flag_true(world, monkeypatch):
    """Twin of the flag-False test: the spy IS reached when True, so the
    flag-False `calls == []` is not vacuous."""
    pc = _mod("person_coordinator")
    calls: list = []
    real = pc.person_state_for_trust

    def _spy(hass, eid):
        calls.append(eid)
        return real(hass, eid)

    monkeypatch.setattr(pc, "person_state_for_trust", _spy)
    assert _faces(world) == []
    assert calls == [OJI_ENTITY]


def test_census_face_kept_when_not_overruled(world):
    world.coord._gps_home_overruled = frozenset()
    assert _faces(world) == ["oji_udezue"]
    assert world.census._face_dropped_ble_overrule_count == 0


def test_census_face_kept_when_overruled_but_location_not_away(world):
    """Overrule set holds Oji but URA location is not away (one-tick lag):
    the helper returns raw, so the face is admitted (errs to today)."""
    world.coord.data[OJI] = {"location": "Study A", "tracking_status": "active"}
    assert _faces(world) == ["oji_udezue"]
    assert world.census._face_dropped_ble_overrule_count == 0


def test_census_face_dropped_raw_not_home_unchanged(world):
    """Kid shape: raw person.state not_home drops as today and is NOT
    counted as a BLE-overrule drop."""
    world.hass.set(OJI_ENTITY, "not_home", {"device_trackers": []})
    world.coord._gps_home_overruled = frozenset()
    assert _faces(world) == []
    assert world.census._face_dropped_ble_overrule_count == 0


def test_census_raw_not_home_and_overruled_not_counted(world):
    """raw not_home AND overruled: dropped via raw; counter stays 0 (the
    counter condition requires raw != not_home)."""
    world.hass.set(OJI_ENTITY, "not_home", {"device_trackers": []})
    assert _faces(world) == []
    assert world.census._face_dropped_ble_overrule_count == 0


def test_census_face_fail_open_no_person_coordinator(world):
    world.hass.data[DOMAIN].pop("person_coordinator")
    assert _faces(world) == ["oji_udezue"]
    assert world.census._face_dropped_ble_overrule_count == 0


def test_census_face_fail_open_helper_raises(world, monkeypatch):
    pc = _mod("person_coordinator")

    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(pc, "person_state_for_trust", _boom)
    assert _faces(world) == ["oji_udezue"]


def test_counter_accumulates_within_tick(world):
    """Two calls without a reset count 2 (the census tick resets it)."""
    _faces(world)
    _faces(world)
    assert world.census._face_dropped_ble_overrule_count == 2


def test_census_face_dropped_via_real_overrule_tick(world, monkeypatch):
    """End to end: the overrule set comes from a REAL person tick on the
    10-24 tuple (GPS home, both BLE trackers not_home, fleet armed)."""
    pc = _mod("person_coordinator")
    hass, coord = world.hass, world.coord
    coord._gps_home_overruled = frozenset()
    coord.data = {}
    clock = SimpleNamespace(now=lambda: T0, utcnow=lambda: T0)
    monkeypatch.setattr(pc, "dt_util", clock)

    class _Reg:
        def async_get_entity_id(self, domain, platform, unique_id):
            if unique_id == "BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT":
                return PROXY
            return None

    monkeypatch.setattr(pc.er, "async_get", lambda _h: _Reg())
    monkeypatch.setattr(pc, "async_track_state_change_event",
                        lambda *a, **k: (lambda: None))
    # Narrow person_coordinator to Oji only for its tick.
    coord.tracked_persons = [OJI]
    coord._pre_arrival_enabled = False

    async def _noop(*_a, **_k):
        return None

    async def _area(_name):
        return AREA

    coord._build_scanner_room_map = _noop
    coord._find_bermuda_area_sensor = _area
    hass.set(AREA, "unknown")
    hass.set(GPS, "home", {"source_type": "gps"})
    hass.set(IRK, "not_home", {"source_type": "bluetooth_le"})
    hass.set(BERM, "not_home", {"source_type": "bluetooth_le"})
    hass.set(OJI_ENTITY, "home", {"device_trackers": [GPS, IRK, BERM]})
    hass.set(PROXY, "55")
    coord._fleet_healthy_since = T0 - timedelta(seconds=400)
    coord.data = asyncio.run(coord._async_update_data())
    assert coord._gps_home_overruled == frozenset({OJI})
    assert _faces(world) == []
    assert world.census._face_dropped_ble_overrule_count == 1


# ---------------------------------------------------------------------------
# Enclosing method — _apply_enhanced_house_census (identity + body maths)
# ---------------------------------------------------------------------------

_CAM = "binary_sensor.family_room_person_occupancy"
_CAM_COUNT = "sensor.family_room_person_count"


def _wire_enhanced(w, *, cam_count: int, cam_area: str):
    """Real area-cancel + clamp; camera manager / hold-decay stubbed."""
    census = w.census
    cc = w.cc
    w.hass.set(_CAM_COUNT, str(cam_count))
    cam_info = SimpleNamespace(entity_id=_CAM, person_count_sensor=_CAM_COUNT,
                               area_id=cam_area)
    census._camera_manager = SimpleNamespace(
        get_platform_for_camera=lambda _e: cc.CAMERA_PLATFORM_FRIGATE,
        _camera_by_entity={_CAM: cam_info},
    )
    census._get_interior_camera_entities = lambda: [_CAM]
    census._resolve_face_entity_id = lambda _base: None  # per-camera face unknown
    census._build_room_to_area_id_map = lambda: {"Kitchen": "kitchen",
                                                 "Family Room": "family_room"}
    census._get_ble_cancel_enabled = lambda: True
    census._apply_hold_decay = lambda raw, _zone, _now: (raw, False, 0)
    census._get_wifi_guest_count = lambda _now=None: 0
    census._face_suppressed_now = lambda: False
    census._get_egress_face_ids_fresh = lambda _now: set()
    census._get_egress_guest_ids_fresh = lambda _now: set()
    census._last_ble_cancelled_count = 0
    raw = cc.CensusZoneResult(
        zone="house", identified_count=0, identified_persons=[],
        unidentified_count=0, total_persons=cam_count, confidence="high",
        source_agreement="single_source", frigate_count=cam_count,
        unifi_count=0,
    )
    return raw


def _enhanced(w, raw):
    ble = w.census._get_ble_persons()
    return w.census._apply_enhanced_house_census(raw, ble, T0)


def _norm(w, name):
    return w.census._canonical_person_slug(name)


def test_enhanced_identity_excludes_overruled(world):
    """3 bodies in family_room, Ezinne + Jaya BLE in the kitchen (the 10-24
    D0 shape). Oji's name leaves identified_persons / face list and the
    third body becomes unidentified: id 2, ceiling 3, unid 1 (plan §4.3)."""
    raw = _wire_enhanced(world, cam_count=3, cam_area="family_room")
    res = _enhanced(world, raw)
    assert _norm(world, "oji_udezue") not in res.identified_persons
    assert res.face_recognized_persons == []
    assert res.identified_count == 2
    assert res.unidentified_count == 1
    assert res.total_persons == 3


def test_enhanced_identity_includes_oji_when_switch_off(world):
    """Same world, switch off: today's result id 3, unid 0."""
    world.pres._ble_leads_enabled = False
    raw = _wire_enhanced(world, cam_count=3, cam_area="family_room")
    res = _enhanced(world, raw)
    assert _norm(world, "oji_udezue") in res.identified_persons
    assert res.face_recognized_persons == ["oji_udezue"]
    assert res.identified_count == 3
    assert res.unidentified_count == 0


def test_counter_kept_out_of_recorder():
    """The per-tick counter rides the every-tick persons_in_house sensor;
    it must be excluded from the recorder (plan D1)."""
    sensor = importlib.import_module(f"{PKG}.sensor")
    assert sensor.URAPersonsInHouseSensor._unrecorded_attributes == frozenset(
        {"face_dropped_ble_overrule_count"}
    )


def test_body_kept_absorbed_by_colocated_ble_resident(world):
    """2 bodies in the kitchen camera, Ezinne + Jaya BLE in the kitchen:
    area-cancel absorbs both, pre_cancel 2, id 2 -> unid 0. The dropped
    name never hides or adds a body."""
    raw = _wire_enhanced(world, cam_count=2, cam_area="kitchen")
    res = _enhanced(world, raw)
    assert res.identified_count == 2
    assert res.camera_unrecognized == 0
    assert res.unidentified_count == 0
    assert res.total_persons == 2

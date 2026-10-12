"""OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 —
docs/planning/PLANNING_occupancy_source_follows_capability.md Rev 2.

Invariant under test (plan §4): the radar-sourced INPUT to each fan-noise
trust gate is a pure function of the capability of the SET of Tier-1
entities on this tick — invariant under moving an entity between CONF
lists, override wins over family both ways, unknown / bed / PIR /
occupancy-kind entities are NOT radar.

Every test drives PRODUCTION code: the real coordinator methods bound onto
a minimal stub, real slices of ``_async_update_data`` compiled from
coordinator.py and executed (same technique as test_mmwave_fan_demotion),
the real PresenceCoordinator, the real FanRecheckManager and the real
``fan_veto.resolve_sensor_family`` over a scoped registry fake. Oracles are
hand-derived literals. Modules load under a private ``ura_`` alias package
(restored by conftest SUITE-HYGIENE-1); every other patch goes through
``monkeypatch``.
"""

from __future__ import annotations

import asyncio
import collections
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_URA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_occ_src_cap_pkg"


def _load():
    if f"{_PKG}.coordinator" not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA_ROOT)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA_ROOT / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    names = (
        "const", "fan_veto", "domain_coordinators.sensor_capability",
        "domain_coordinators.hvac_fans",
        "domain_coordinators.presence_fan_recheck",
        "domain_coordinators.presence", "coordinator", "binary_sensor",
    )
    return [importlib.import_module(f"{_PKG}.{n}") for n in names]


CONST, FV, SC, HF, FR, PR, CO, BS = _load()
DOMAIN = CONST.DOMAIN
RADAR = CONST.STATE_RADAR_SOLE_TICK

# Entities (shapes from AUDIT_motion_sensors_live_models.md 2026-10-11).
ZK = "binary_sensor.studya_zk_presence"
ZX = "binary_sensor.master_zx_presence"
ZV = "binary_sensor.media_zv_presence_2"
MS_OCC = "binary_sensor.mmwave_motion_lux_matter_wifi_media_occupancy"
MS_MOT = "binary_sensor.media_sensor_presence_motion"
BED = "binary_sensor.bed_presence_bed_occupied_left_slow"
PIR = "binary_sensor.pir_hall_motion"
NL = "binary_sensor.third_reality_nightlight_occupancy"
FAN = "fan.media"

MODELS = {
    ZK: ("ZG-204ZK", "24Ghz human presence sensor"),
    ZX: ("ZG-204ZX", "24Ghz millimeter wave and T&H sensor"),
    ZV: ("ZG-204ZV", "Millimeter wave motion detection"),
    MS_OCC: ("16897", "Smart Presence Sensor"),     # Meross MS600 Matter
    MS_MOT: (None, "ms600 9.0.0"),                  # meross_lan motion bit
    BED: (None, "esp32-c3-devkitm-1"),              # unknown family
    PIR: ("SNZB-03P", "Motion sensor"),
    NL: ("3RSNL02043Z", "Night light"),             # unknown family
}


@pytest.fixture(autouse=True)
def _aware_clock(monkeypatch):
    """Sibling files leave dt_util patched; pin tz-aware wall time
    (scoped by monkeypatch)."""
    for mod in {id(FR.dt_util): FR.dt_util, id(HF.dt_util): HF.dt_util,
                id(PR.dt_util): PR.dt_util}.values():
        monkeypatch.setattr(mod, "now", lambda: datetime.now(timezone.utc))
        monkeypatch.setattr(mod, "utcnow", lambda: datetime.now(timezone.utc))
    yield


def _routing(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        SC, "OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED", enabled,
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _State:
    def __init__(self, state, attrs=None):
        self.state = state
        self.attributes = dict(attrs or {})
        self.last_changed = None


class _Entry:
    def __init__(self, entry_id, data, options=None):
        self.entry_id = entry_id
        self.data = dict(data)
        self.options = dict(options or {})


def _install_registry(monkeypatch, models=None):
    """Scoped device/entity registry fake -> drives the REAL
    fan_veto.resolve_sensor_family (copied from
    test_fan_noise_running_rejection)."""
    models = dict(MODELS if models is None else models)
    ent_reg = types.SimpleNamespace(
        async_get=lambda eid: (
            types.SimpleNamespace(device_id=f"dev::{eid}")
            if eid in models else None
        ),
    )
    dev_reg = types.SimpleNamespace(
        async_get=lambda did: (
            types.SimpleNamespace(
                model_id=models[did[5:]][0], model=models[did[5:]][1],
            )
            if did.startswith("dev::") and did[5:] in models else None
        ),
    )
    er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
    er_mod.async_get = lambda hass: ent_reg
    dr_mod = types.ModuleType("homeassistant.helpers.device_registry")
    dr_mod.async_get = lambda hass: dev_reg
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", er_mod,
    )
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.device_registry", dr_mod,
    )
    helpers = sys.modules.get("homeassistant.helpers")
    if helpers is not None:
        monkeypatch.setattr(helpers, "entity_registry", er_mod, raising=False)
        monkeypatch.setattr(helpers, "device_registry", dr_mod, raising=False)


# ---------------------------------------------------------------------------
# Room-coordinator stub carrying the REAL production methods
# ---------------------------------------------------------------------------

_BOUND = (
    "_get_config", "_is_sensor_on", "_fusion_filter_active", "is_radar",
    "_live_on_set", "_radar_sole_on_set", "any_radar_bearing_on_now",
    "recent_radar_sole_ring", "recent_occupancy_sources",
    "_evaluate_mmwave_demoted_latch",
)


class _RoomCoord:
    pass


def _entry(room, *, presence=(), motion=(), occupancy=(), caps=None,
           extra=None):
    data = {
        CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM,
        CONST.CONF_ROOM_NAME: room,
        "room_name": room,
        CONST.CONF_MMWAVE_SENSORS: list(presence),
        CONST.CONF_MOTION_SENSORS: list(motion),
        CONST.CONF_OCCUPANCY_SENSORS: list(occupancy),
    }
    if caps:
        data[CONST.CONF_SENSOR_CAPABILITIES] = dict(caps)
    data.update(extra or {})
    return _Entry(f"entry_{room}", data)


def _room_coord(hass, entry):
    r = _RoomCoord()
    r.hass = hass
    r.entry = entry
    for name in _BOUND:
        setattr(r, name, getattr(CO.UniversalRoomCoordinator, name).__get__(r))
    r._exclusion_set = types.SimpleNamespace(is_excluded=lambda s: False)
    r._recent_occupancy_sources = collections.deque(maxlen=10)
    r._recent_radar_sole_ring = collections.deque(maxlen=10)
    r._mmwave_demoted_latch = False
    r._actuator_reconciler = None
    r.data = {}
    return r


def _hass(states):
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.states.get = lambda eid: states.get(eid)
    return hass


def _world(monkeypatch, on=(), room="Media", **conf):
    _install_registry(monkeypatch)
    states = {e: _State("on" if e in on else "off") for e in MODELS}
    hass = _hass(states)
    entry = _entry(room, **conf)
    hass.config_entries.async_entries = lambda domain=None: [entry]
    return hass, states, _room_coord(hass, entry)


def _sole(r):
    """The producer helper the tick calls, over the room's three lists."""
    g = r._get_config
    return r._radar_sole_on_set(
        g(CONST.CONF_MOTION_SENSORS, []), g(CONST.CONF_MMWAVE_SENSORS, []),
        g(CONST.CONF_OCCUPANCY_SENSORS, []),
    )


# ---------------------------------------------------------------------------
# Production-slice harness (compiled from coordinator.py, executed)
# ---------------------------------------------------------------------------

def _slice(start: str, end: str):
    src = (_URA_ROOT / "coordinator.py").read_text(encoding="utf-8")
    assert src.count(start) == 1, f"slice start marker moved: {start!r}"
    i = src.index(start)
    j = src.index(end, i)
    out = []
    for ln in src[i:j].splitlines():
        out.append(ln[8:] if ln.startswith("        ") else ln.strip())
    return compile("\n".join(out), str(_URA_ROOT / "coordinator.py"), "exec")


_PRODUCER = _slice(
    "        # OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 D1b: per-tick capability",
    "        # ---- Substrate-gap canary",
)
_RINGS = _slice(
    "        self._recent_occupancy_sources.append(",
    "        # Reconcile-on-Return (v5.8.0",
)
_D2 = _slice(
    "        # === mmWave fan-corroboration Tier-3 D2 — DEMOTION consumer ===",
    "        # Always populate ble_persons even when occupied by other sources",
)


def _fan_on_presence(hass, room, fan_on=True):
    tracker = MagicMock()
    tracker._fan_on_since = (
        {room: datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)}
        if fan_on else {}
    )
    tracker._fan_off_at = {}
    presence = MagicMock()
    presence.tracker_for_room = MagicMock(return_value=tracker)
    mgr = MagicMock()
    mgr.coordinators = {"presence": presence}
    hass.data[DOMAIN]["coordinator_manager"] = mgr


def _tick(r, *, grace_hold=False):
    """Run the production producer slice (D1b stamp + latch clear + latch
    suppression) and the production ring-append slice for one tick.
    Detections are computed exactly like _async_update_data:3473-3488."""
    g = r._get_config
    motion = g(CONST.CONF_MOTION_SENSORS, [])
    mmwave = g(CONST.CONF_MMWAVE_SENSORS, [])
    occ = g(CONST.CONF_OCCUPANCY_SENSORS, [])
    on = lambda lst: any(  # noqa: E731
        r._is_sensor_on(s) for s in r._fusion_filter_active(lst)
    )
    md, pdet, od = on(motion), on(mmwave), on(occ)
    if grace_hold:
        md = pdet = od = False
    data: dict = {}
    # List label exactly as coordinator.py:3831-3841 (motion > mmwave > occ).
    data[CONST.STATE_OCCUPANCY_SOURCE] = (
        "motion" if md else "mmwave" if pdet else
        "occupancy_sensor" if od else "none"
    )
    ns = dict(vars(CO))
    ns.update(
        self=r, data=data, grace_hold=grace_hold, motion_sensors=motion,
        mmwave_sensors=mmwave, occupancy_sensors=occ, motion_detected=md,
        presence_detected=pdet, occupancy_detected=od,
        any_sensor_active=md or pdet or od, room_name=r.entry.data["room_name"],
        now=datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc),
    )
    exec(_PRODUCER, ns)
    exec(_RINGS, {"self": r, "data": data, **vars(CO)})
    data["_any_sensor_active"] = ns["any_sensor_active"]
    return data


# ===========================================================================
# D1 — producer, is_radar, rings
# ===========================================================================

def test_combined_sensor_only_tick_radar_sole_true(monkeypatch):
    """MS600 Matter occupancy filed under occupancy_sensors, alone -> True
    (device-family arm: model '16897' -> generic_radar)."""
    _h, _s, r = _world(monkeypatch, on={MS_OCC}, occupancy=[MS_OCC])
    assert _sole(r) is True
    assert _tick(r)[RADAR] is True


def test_zk_only_tick_radar_sole_true(monkeypatch):
    """ZK in presence_sensors, alone -> True by CONF-list kind, even with
    an UNKNOWN device family (registry has no entry for it)."""
    models = dict(MODELS)
    models.pop(ZK)
    _h, _s, r = _world(monkeypatch, on={ZK}, presence=[ZK])
    _install_registry(monkeypatch, models)
    assert FV.resolve_sensor_family(r.hass, ZK) == "unknown"
    assert _sole(r) is True


def test_combined_sensor_plus_zv_not_radar_sole(monkeypatch):
    """Finding 3 sole-source: MS600 (occupancy list) + ZV (motion) both on
    -> False, although a radar is on."""
    _h, _s, r = _world(
        monkeypatch, on={MS_OCC, ZV}, occupancy=[MS_OCC], motion=[ZV],
    )
    assert _sole(r) is False
    # ...and the same on-set with the radar in presence_sensors: the LIST
    # label says "motion" -> not radar-sole either (no regression).
    _h, _s, r2 = _world(
        monkeypatch, on={ZK, ZV}, presence=[ZK], motion=[ZV],
    )
    assert _tick(r2)[RADAR] is False


def test_bed_sensor_not_radar_sole(monkeypatch):
    """Finding 4 / Master Bedroom guard: bed presence firing (occupancy
    list, unknown family) -> False; ZX present but off."""
    _h, _s, r = _world(
        monkeypatch, on={BED}, room="Master Bedroom",
        presence=[ZX], occupancy=[BED],
    )
    assert r.is_radar(BED) is False
    assert _sole(r) is False
    assert r.any_radar_bearing_on_now() is False
    # Night-light occupancy (unknown family, occupancy list) -> not radar.
    _h, _s, r2 = _world(monkeypatch, on={NL}, occupancy=[NL])
    assert r2.is_radar(NL) is False and _sole(r2) is False


def test_pir_override_declassifies_family_radar(monkeypatch):
    """Override wins over family: kind 'pir' on a family-radar -> False."""
    _h, _s, r = _world(
        monkeypatch, on={MS_OCC}, occupancy=[MS_OCC],
        caps={MS_OCC: {"kind": "pir"}},
    )
    assert SC.validate_capabilities_payload(
        r.entry.data, {MS_OCC: {"kind": "pir"}},
    ) == []
    assert r.is_radar(MS_OCC) is False
    assert _sole(r) is False


def test_mmwave_override_promotes_occupancy_entity(monkeypatch):
    """Override wins the other way: kind 'mmwave' on an occupancy-list
    unknown-family entity -> True (legal under D-MEDIUM-1)."""
    _h, _s, plain = _world(monkeypatch, on={NL}, occupancy=[NL])
    assert plain.is_radar(NL) is False
    _h, _s, r = _world(
        monkeypatch, on={NL}, occupancy=[NL],
        caps={NL: {"kind": "mmwave"}},
    )
    assert SC.validate_capabilities_payload(
        r.entry.data, {NL: {"kind": "mmwave"}},
    ) == []
    assert r.is_radar(NL) is True
    assert _sole(r) is True


@pytest.mark.parametrize("on_set, expected", [
    ({MS_OCC}, True),
    ({MS_OCC, ZV}, False),
    ({MS_OCC, BED}, False),
])
def test_filing_permutation_same_on_set_same_verdict(
    monkeypatch, on_set, expected,
):
    """Finding 11: same on-set, every filing of MS_OCC across the three
    CONF lists -> identical verdict."""
    others = {ZV: "motion", BED: "occupancy"}
    verdicts = []
    for key in ("presence", "motion", "occupancy"):
        lists = {"presence": [], "motion": [], "occupancy": []}
        lists[key].append(MS_OCC)
        for e in on_set - {MS_OCC}:
            lists[others[e]].append(e)
        _h, _s, r = _world(monkeypatch, on=on_set, **lists)
        verdicts.append(_tick(r)[RADAR])
    assert verdicts == [expected] * 3


def test_is_radar_fail_closed_on_exception(monkeypatch):
    _h, _s, r = _world(monkeypatch, on={MS_OCC}, occupancy=[MS_OCC])

    def _boom(hass, eid):
        raise RuntimeError("registry exploded")
    monkeypatch.setattr(FV, "resolve_sensor_family", _boom)
    assert FV.is_radar_entity(r.hass, r.entry.data, MS_OCC) is False
    assert r.is_radar(MS_OCC) is False
    assert _sole(r) is False


def test_radar_sole_written_every_tick(monkeypatch):
    """The key is stamped on EVERY tick — nothing on, and grace_hold."""
    _h, states, r = _world(monkeypatch, on=set(), presence=[ZK])
    d = _tick(r)
    assert RADAR in d and d[RADAR] is False
    states[ZK] = _State("on")
    assert _tick(r)[RADAR] is True
    d = _tick(r, grace_hold=True)
    assert RADAR in d and d[RADAR] is False


def test_rings_same_length_always(monkeypatch):
    _h, states, r = _world(monkeypatch, on={ZK}, presence=[ZK], motion=[ZV])
    seq = []
    for i in range(13):
        states[ZV] = _State("on" if i % 3 == 0 else "off")
        seq.append(_tick(r)[RADAR])
        assert len(r.recent_radar_sole_ring()) == len(
            r.recent_occupancy_sources()
        )
    assert r.recent_radar_sole_ring() == seq[-10:]
    assert seq[:4] == [False, True, True, False]


# ===========================================================================
# D2 — D2 gate + flap latch (coordinator.py)
# ===========================================================================

class _D2Self:
    """Other D2 legs pinned open; the radar-sole conjunct is under test."""

    def __init__(self, hass):
        self.hass = hass
        self._occupancy_timeout = 60
        self._last_pir_motion_time = None
        self._last_motion_time = None
        self._became_occupied_time = None
        self._last_occupied_since_for_handler = None
        self._mmwave_fan_demoted_last_tick = False
        self._mmwave_fan_demoted_since = None
        self._mmwave_fan_demotions_since_boot = 0
        self._mmwave_demoted_latch = False
        self._ble_only_hold_since = None

        class _E:
            data = {"room_name": "Media"}
        self.entry = _E()

    def _d2_boot_settle_done(self):
        return True

    def _d2_debounce_elapsed(self, now):
        return True

    def _d2_motion_sensors_present(self):
        return True

    def _d2_house_state_allows(self):
        return True


def _run_d2(data):
    hass = MagicMock()
    presence = MagicMock()
    presence.is_room_mmwave_fan_demoted = MagicMock(return_value=True)
    tracker = MagicMock()
    tracker._fan_on_since = {}
    tracker._fan_interference_hold_until = {}
    presence.tracker_for_room = MagicMock(return_value=tracker)
    fr = MagicMock()
    fr.get_room_state = MagicMock(return_value="idle")
    fr.is_recheck_eligible = MagicMock(return_value=False)
    presence._fan_recheck_manager = fr
    mgr = MagicMock()
    mgr.coordinators = {"presence": presence}
    hass.data = {DOMAIN: {"coordinator_manager": mgr}}
    me = _D2Self(hass)
    ns = dict(vars(CO))
    ns.update(
        self=me, data=data, room_name="Media",
        now=datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc),
        async_dispatcher_send=lambda *a, **k: None,
    )
    exec(_D2, ns)
    return me


def test_d2_fires_on_combined_sensor_only_tick():
    """Radar-sole tick whose LIST label is 'occupancy_sensor' -> demotes."""
    data = {CONST.STATE_OCCUPIED: True,
            CONST.STATE_OCCUPANCY_SOURCE: "occupancy_sensor", RADAR: True}
    me = _run_d2(data)
    assert data[CONST.STATE_OCCUPIED] is False
    assert me._mmwave_demoted_latch is True


def test_d2_does_not_fire_on_mmwave_label_when_not_radar_sole():
    """Sole-source at the D2 gate: label 'mmwave' but a ZV co-fires
    (radar_sole False) -> no demotion."""
    data = {CONST.STATE_OCCUPIED: True,
            CONST.STATE_OCCUPANCY_SOURCE: "mmwave", RADAR: False}
    _run_d2(data)
    assert data[CONST.STATE_OCCUPIED] is True


def test_latch_does_not_oscillate_in_occupancy_list_radar_room(monkeypatch):
    """Radar filed under occupancy_sensors, fan on, no BLE: the latch is
    NOT cleared tick after tick (presence_detected is False every tick)."""
    hass, _s, r = _world(monkeypatch, on={MS_OCC}, occupancy=[MS_OCC])
    _fan_on_presence(hass, "Media")
    r._mmwave_demoted_latch = True
    for _ in range(6):
        _tick(r)
        assert r._mmwave_demoted_latch is True


def test_latch_still_clears_when_radar_goes_off(monkeypatch):
    hass, states, r = _world(monkeypatch, on={MS_OCC}, occupancy=[MS_OCC])
    _fan_on_presence(hass, "Media")
    r._mmwave_demoted_latch = True
    states[MS_OCC] = _State("off")
    _tick(r)
    assert r._mmwave_demoted_latch is False


def test_latch_suppresses_on_capability_radar_sole(monkeypatch):
    """ZK (presence list) + MS600 (occupancy list), latched: the old
    predicate (presence and not occupancy) would NOT suppress; capability
    radar-sole does. Latch-clear verdict is the same under both."""
    hass, _s, r = _world(
        monkeypatch, on={ZK, MS_OCC}, presence=[ZK], occupancy=[MS_OCC],
    )
    _fan_on_presence(hass, "Media")
    r._mmwave_demoted_latch = True
    d = _tick(r)
    assert r._mmwave_demoted_latch is True
    assert d["_any_sensor_active"] is False


# ===========================================================================
# D3 — presence-side fan-interference gate
# ===========================================================================

def _presence_world(monkeypatch, on, kinds, **conf):
    hass, _s, _r = _world(monkeypatch, on=on, **conf)
    coord = PR.PresenceCoordinator(hass)
    tracker = PR.ZonePresenceTracker(hass, "z1", ["Media"])
    coord._zone_trackers = {"z1": tracker}
    tracker._fan_on_rooms.add("Media")
    tracker._fan_on_since["Media"] = (
        datetime.now(timezone.utc) - timedelta(seconds=900)
    )
    for k in kinds:     # what the substrate (CONF-list kind) would stamp
        tracker.update_room_occupancy("Media", True, kind=k)
    return coord


def test_fan_interference_rooms_includes_occupancy_list_radar(monkeypatch):
    coord = _presence_world(
        monkeypatch, {MS_OCC}, ["occupancy"], occupancy=[MS_OCC],
    )
    assert coord._compute_fan_interference_rooms() == ["Media"]


def test_is_room_mmwave_fan_demoted_covers_occupancy_list_radar(monkeypatch):
    coord = _presence_world(
        monkeypatch, {MS_OCC}, ["occupancy"], occupancy=[MS_OCC],
    )
    assert coord.house_state not in ("sleep", "waking", "home_night")
    # Same snapshot refresh as _run_inference (presence.py ~:5768).
    coord._mmwave_fan_demoted_snapshot = frozenset(
        coord._compute_mmwave_fan_demoted_rooms()
    )
    assert coord.is_room_mmwave_fan_demoted("Media") is True


def test_fan_interference_rooms_excludes_bed_and_mixed(monkeypatch):
    bed = _presence_world(
        monkeypatch, {BED}, ["occupancy"], presence=[ZX], occupancy=[BED],
    )
    assert bed._compute_fan_interference_rooms() == []
    mixed = _presence_world(
        monkeypatch, {ZK, ZV}, ["mmwave", "motion"], presence=[ZK],
        motion=[ZV],
    )
    assert mixed._compute_fan_interference_rooms() == []
    zk = _presence_world(monkeypatch, {ZK}, ["mmwave"], presence=[ZK])
    assert zk._compute_fan_interference_rooms() == ["Media"]


# ===========================================================================
# D4 — recheck (real FanRecheckManager over the real-method room coord)
# ===========================================================================

def _recheck_world(monkeypatch, *, on, room_type="generic", **conf):
    _install_registry(monkeypatch)
    states = {e: _State("on" if e in on else "off") for e in MODELS}
    states[FAN] = _State("on", {"percentage": 66})
    hass = _hass(states)
    entry = _entry("Media", extra={
        "fans": [FAN], "room_type": room_type,
        CONST.CONF_ROOM_FAN_RECHECK_ENABLED: True,
        CONST.CONF_FAN_RECHECK_TRUST_SENSORS_OK: True,
    }, **conf)
    entry.options = {CONST.CONF_ROOM_FAN_MODE: CONST.FAN_MODE_FOLLOW_THERMOSTAT}
    cm = _Entry("cm", {"entry_type": CONST.ENTRY_TYPE_COORDINATOR_MANAGER})
    hass.config_entries.async_entries = lambda domain=None: [entry, cm]
    rc = _room_coord(hass, entry)
    rc.data = {CONST.STATE_OCCUPIED: True}

    class _PC:
        def get_ble_tier(self, room):
            return 0

        def get_persons_in_room(self, room):
            return []

    hass.data = {DOMAIN: {
        entry.entry_id: rc, "person_coordinator": _PC(),
        "fan_recheck_master_enabled": True,
        "coordinator_manager": MagicMock(coordinators={}),
    }}
    monkeypatch.setattr(FR, "trustworthy_persons_in_room", lambda *a, **k: [])
    monkeypatch.setattr(FR, "async_dispatcher_send", lambda *a, **k: None)
    presence = types.SimpleNamespace(
        house_state="home_day", _boot_settle_done=True,
        get_adjacent_rooms=lambda r: [], zone_trackers={},
    )
    mgr = FR.FanRecheckManager(hass, presence)
    mgr._setup_done = True
    return mgr, rc, states


def _fill(rc, n=3):
    for _ in range(n):
        d = _tick(rc)
        d[CONST.STATE_OCCUPIED] = True
        rc.data = d


def _eligible(mgr, rc):
    ctx = FR._RoomCtx(room_name="Media", entry_id=rc.entry.entry_id)
    return mgr._is_eligible(ctx, rc)


def test_recheck_arms_on_combined_sensor_only_history(monkeypatch):
    """Media shape: MS600 Matter occupancy (presence list) + its motion bit
    (motion list) both on -> LIST label 'motion' every tick (recheck blind
    pre-cycle), capability radar-sole every tick -> eligible."""
    mgr, rc, _s = _recheck_world(
        monkeypatch, on={MS_OCC, MS_MOT}, presence=[MS_OCC], motion=[MS_MOT],
    )
    _fill(rc)
    assert rc.recent_occupancy_sources()[-3:] == ["motion"] * 3
    assert rc.recent_radar_sole_ring()[-3:] == [True] * 3
    assert _eligible(mgr, rc) is True


def test_recheck_arms_gb1_shape_only_when_zv_quiet(monkeypatch):
    """GB1 shape: MS600 occupancy + motion bit + a ZV. Radar-sole ticks
    arm; one ZV tick in the window vetoes."""
    mgr, rc, states = _recheck_world(
        monkeypatch, on={MS_OCC, MS_MOT}, presence=[MS_OCC],
        motion=[MS_MOT, ZV],
    )
    _fill(rc)
    assert _eligible(mgr, rc) is True
    states[ZV] = _State("on")
    _fill(rc, 1)
    assert _eligible(mgr, rc) is False
    assert mgr._veto_counts["Media"]["not_radar_sole"] == 1


def test_recheck_still_vetoes_on_motion_mixed_history(monkeypatch):
    mgr, rc, _s = _recheck_world(monkeypatch, on={ZK}, presence=[ZK])
    rc._recent_radar_sole_ring.extend([True, False, True])
    assert _eligible(mgr, rc) is False
    assert mgr._veto_counts["Media"]["not_radar_sole"] == 1


def test_recheck_vetoes_capability_bootstrap_pre_warmup(monkeypatch):
    mgr, rc, _s = _recheck_world(monkeypatch, on={ZK}, presence=[ZK])
    _fill(rc, 2)                       # N = 3 (DEFAULT history ticks)
    # The label ring alone would be long enough under the old gate.
    rc._recent_occupancy_sources.extend(["mmwave"] * 5)
    assert _eligible(mgr, rc) is False
    assert mgr._veto_counts["Media"]["capability_bootstrap"] == 1
    # A coordinator without the ring fails CLOSED (no hasattr fallback).
    del rc.recent_radar_sole_ring
    assert _eligible(mgr, rc) is False
    assert mgr._veto_counts["Media"]["capability_bootstrap"] == 2


def test_still_armed_eligible_combined_sensor_live_tick(monkeypatch):
    mgr, rc, _s = _recheck_world(
        monkeypatch, on={MS_OCC, MS_MOT}, presence=[MS_OCC], motion=[MS_MOT],
    )
    ctx = FR._RoomCtx(room_name="Media", entry_id=rc.entry.entry_id)
    rc.data = {CONST.STATE_OCCUPIED: True,
               CONST.STATE_OCCUPANCY_SOURCE: "motion", RADAR: True}
    assert mgr._still_armed_eligible(ctx, rc) is True
    rc.data = {CONST.STATE_OCCUPIED: True,
               CONST.STATE_OCCUPANCY_SOURCE: "mmwave", RADAR: False}
    assert mgr._still_armed_eligible(ctx, rc) is False


def _pause_outcome(monkeypatch, mgr, rc):
    seen = []

    async def _restore(ctx, outcome, forced=False):
        seen.append(outcome)
    monkeypatch.setattr(mgr, "_restore", _restore)
    ctx = FR._RoomCtx(room_name="Media", entry_id=rc.entry.entry_id)
    _run(mgr._on_pause_window_done(ctx, datetime.now(timezone.utc)))
    return seen[0]


def test_vacated_defensive_gate_reads_live_on_set(monkeypatch):
    """ZK room (covered today): radar off after the pause -> VACATED; ZK
    still on while the label reads 'timeout' -> NOT vacated."""
    mgr, rc, states = _recheck_world(monkeypatch, on=set(), presence=[ZK])
    rc.data = {CONST.STATE_OCCUPANCY_SOURCE: "timeout",
               CONST.STATE_PRESENCE_DETECTED: False}
    assert _pause_outcome(monkeypatch, mgr, rc) == FR.OUTCOME_VACATED
    states[ZK] = _State("on")
    assert _pause_outcome(monkeypatch, mgr, rc) == (
        FR.OUTCOME_OCCUPIED_CONFIRMED
    )


def test_vacated_defensive_gate_occupancy_list_radar_still_firing_not_vacated(
    monkeypatch,
):
    """MS600 in occupancy_sensors still on after the pause: label
    'occupancy_sensor', presence_detected False (old gate -> VACATED) ->
    NOT vacated under capability."""
    mgr, rc, _s = _recheck_world(
        monkeypatch, on={MS_OCC}, occupancy=[MS_OCC],
    )
    rc.data = {CONST.STATE_OCCUPANCY_SOURCE: "occupancy_sensor",
               CONST.STATE_PRESENCE_DETECTED: False}
    assert _pause_outcome(monkeypatch, mgr, rc) == (
        FR.OUTCOME_OCCUPIED_CONFIRMED
    )


def test_vacated_defensive_gate_bed_on_does_not_block_vacate(monkeypatch):
    """Bed occupancy is not radar: radar off + bed on -> VACATED."""
    mgr, rc, _s = _recheck_world(
        monkeypatch, on={BED}, presence=[ZX], occupancy=[BED],
    )
    rc.data = {CONST.STATE_OCCUPANCY_SOURCE: "occupancy_sensor",
               CONST.STATE_PRESENCE_DETECTED: False}
    assert _pause_outcome(monkeypatch, mgr, rc) == FR.OUTCOME_VACATED


def test_room_families_covers_radar_in_occupancy_sensors(monkeypatch):
    """Finding 6: MS600-only room with the radar in occupancy_sensors gets
    the generic_radar factor 1.5, not 1.0; a bed (unknown) is ignored."""
    mgr, rc, _s = _recheck_world(
        monkeypatch, on=set(), occupancy=[MS_OCC, BED],
    )
    merged = {**rc.entry.data, **rc.entry.options}
    assert mgr._family_factor(merged, {}, "Media") == 1.5


def test_room_families_respects_pir_override(monkeypatch):
    """The is_radar filter: a family-radar declassified by a pir override
    does not set the window."""
    mgr, rc, _s = _recheck_world(
        monkeypatch, on=set(), occupancy=[MS_OCC],
        caps={MS_OCC: {"kind": "pir"}},
    )
    merged = {**rc.entry.data, **rc.entry.options}
    assert mgr._family_factor(merged, {}, "Media") == 1.0


# ===========================================================================
# D5 — list labels unchanged on the display surface
# ===========================================================================

def test_occupancy_source_attribute_preserves_list_label():
    coord = types.SimpleNamespace(
        data={CONST.STATE_OCCUPANCY_SOURCE: "occupancy_sensor", RADAR: True},
        _became_occupied_time=None, _last_occupied_state=True,
        _occupancy_first_detected=None, _failsafe_fired=False,
        _last_trigger_source="occupancy", _last_lux_zone=None,
        automation=None,
    )
    me = types.SimpleNamespace(coordinator=coord)
    attrs = BS.OccupiedBinarySensor.extra_state_attributes.fget(me)
    assert attrs["occupancy_source"] == "occupancy_sensor"


# ===========================================================================
# D6 — kill switch
# ===========================================================================

def test_kill_switch_disables_capability_routing_all_six_sites(monkeypatch):
    """Routing OFF: each site returns its pre-cycle verdict on a fixture
    where capability and list label disagree."""
    _routing(monkeypatch, False)
    # (1) D2 gate: radar-sole tick labelled 'occupancy_sensor' -> no demote.
    data = {CONST.STATE_OCCUPIED: True,
            CONST.STATE_OCCUPANCY_SOURCE: "occupancy_sensor", RADAR: True}
    _run_d2(data)
    assert data[CONST.STATE_OCCUPIED] is True
    # (2) latch clear: occupancy-list radar -> clears (old 'mmwave_off').
    hass, _s, r = _world(monkeypatch, on={MS_OCC}, occupancy=[MS_OCC])
    _fan_on_presence(hass, "Media")
    r._mmwave_demoted_latch = True
    _tick(r)
    assert r._mmwave_demoted_latch is False
    # (3) latch suppression: ZK + MS600(occ) -> NOT suppressed.
    hass, _s, r = _world(
        monkeypatch, on={ZK, MS_OCC}, presence=[ZK], occupancy=[MS_OCC],
    )
    _fan_on_presence(hass, "Media")
    r._mmwave_demoted_latch = True
    assert _tick(r)["_any_sensor_active"] is True
    # (4) presence gate: occupancy-list radar -> not flagged.
    coord = _presence_world(
        monkeypatch, {MS_OCC}, ["occupancy"], occupancy=[MS_OCC],
    )
    assert coord._compute_fan_interference_rooms() == []
    # (5) eligibility history: Media shape -> vetoed on the label.
    mgr, rc, _s = _recheck_world(
        monkeypatch, on={MS_OCC, MS_MOT}, presence=[MS_OCC], motion=[MS_MOT],
    )
    _fill(rc)
    assert _eligible(mgr, rc) is False
    assert mgr._veto_counts["Media"]["not_mmwave_sole"] == 1
    # (6) still-armed: label 'motion' -> False.
    ctx = FR._RoomCtx(room_name="Media", entry_id=rc.entry.entry_id)
    rc.data = {CONST.STATE_OCCUPIED: True,
               CONST.STATE_OCCUPANCY_SOURCE: "motion", RADAR: True}
    assert mgr._still_armed_eligible(ctx, rc) is False
    # (7) VACATED: occupancy-list radar still on -> VACATED (old gate).
    mgr, rc, _s = _recheck_world(
        monkeypatch, on={MS_OCC}, occupancy=[MS_OCC],
    )
    rc.data = {CONST.STATE_OCCUPANCY_SOURCE: "occupancy_sensor",
               CONST.STATE_PRESENCE_DETECTED: False}
    assert _pause_outcome(monkeypatch, mgr, rc) == FR.OUTCOME_VACATED
    # (8) family factor: occupancy-list radar ignored -> 1.0.
    merged = {**rc.entry.data, **rc.entry.options}
    assert mgr._family_factor(merged, {}, "Media") == 1.0


@pytest.mark.parametrize("routing", [True, False])
def test_kill_switch_presence_list_radar_same_verdict(monkeypatch, routing):
    """D6b: when the only radar is filed in presence_sensors, both toggle
    values give the same verdict at every recheck site."""
    _routing(monkeypatch, routing)
    mgr, rc, states = _recheck_world(monkeypatch, on={ZK}, presence=[ZK])
    _fill(rc)
    assert _eligible(mgr, rc) is True
    ctx = FR._RoomCtx(room_name="Media", entry_id=rc.entry.entry_id)
    assert mgr._still_armed_eligible(ctx, rc) is True
    states[ZK] = _State("off")
    rc.data = {CONST.STATE_OCCUPANCY_SOURCE: "timeout",
               CONST.STATE_PRESENCE_DETECTED: False}
    assert _pause_outcome(monkeypatch, mgr, rc) == FR.OUTCOME_VACATED
    merged = {**rc.entry.data, **rc.entry.options}
    assert mgr._family_factor(merged, {}, "Media") == 2.0

"""HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1 — SLEEP-mask fix, 5-min resident
BLE memory, AWAY observability.

Plan: docs/planning/PLANNING_house_state_sleep_mask_ble_memory_observability.md
Rev 2 (a0cd40412). Tier 3.

FALSIFIABLE INVARIANTS UNDER TEST (plan §2, restated in tracker-mode terms)
---------------------------------------------------------------------------
Definitions: sleep_zone(z) <=> z.mode == SLEEP; away_pinned(z) <=>
z._override == AWAY; night_raw(z) = z._ble_occupied OR (z._has_sensors AND
(some room r occupied OR a camera in its timeout)). Rev 2.1: the Rev 2
fan-phantom breaker is DROPPED (stress test P5) — no fan test anywhere.
N = decay_timeout, I = 30 s person tick, T = 60 s presence tick.

INV-SLEEP-NOT-EMPTY  The NOBODY-HOME branch (and path β, review D-M3)
    never returns AWAY while some zone has sleep_zone(z) AND night_raw(z).
    night_raw's room limb = tracker room view OR the LIVE `on` state of any
    Tier-1 sensor registered to the room (review D-H1: the tracker view is
    lossy in multi-sensor rooms).
    Scope limits (NOT guaranteed, review D S-1/S-2):
      - path α (ledger #12): three ACTIVE-away trackers + a dead-phone
        sleeper (LOST, out of the denominator) + healthy cameras -> α
        returns AWAY over a raw-occupied pinned zone (Rev 4 guard A, parked);
      - PICK 1 carve-out: an away_pinned zone counts as empty (a mistaken
        house AWAY override then `auto` leaves zones AWAY-pinned).
INV-EMPTY-REACHES-AWAY  With the house empty (census 0, trackers away or
    silent) and every zone's night_raw (SLEEP) / mode (otherwise) clear,
    AWAY is proposed on the next tick.
INV-BLE-SEEN-NOT-AWAY  A resident whose last Bermuda room fix is younger
    than N is never counted away by α or β, unless phone_left_behind is on.
INV-NO-BLE-HOLD  D2 never extends a hold beyond last fix + N + I + T.
INV-BYTE-ID  With no SLEEP-mode tracker and no STALE person every infer()
    return is identical to today (permitted delta: veto_path="nobody_home"
    on the FIRING return only). Both kill constants False -> identical in
    all states.
INV-SLEEP-HOLD-BOUNDED (Rev 2.1, AUDIT_census_arc_and_away_holistic.md
    §P5) With census_count == 0, house state SLEEP, and night_raw true only
    through rooms occupied by sensors (no fan test anywhere), (a) nobody-home
    never returns AWAY while any pinned zone has an occupied room, and (b)
    the house is out of SLEEP by the first inference tick at or after the
    end of the sleep window plus the SLEEP/WAKING dwell, via WAKING or via
    AWAY if the room cleared. Falsified by a tick at local 06:00 + 2 min with
    SLEEP, census 0, raw occupied, no override, state still SLEEP; or by a
    nobody-home AWAY with a pinned zone whose room is occupied.
    Trip-wire: SLEEP still held only by raw occupancy with census 0 more
    than SLEEP_RAW_HOLD_NM_BOUND_S (5400 s) after the sleep window ENDS
    (i.e. (b) failed) fires ONE stuck-signal NM per episode; an overnight
    raw hold inside the window never fires.
INV-COUNTER-MATCHES-LOG  away_entries_today == COUNT of house_state_log
    rows with state='away' AND previous_state<>'away' since local midnight
    (naive UTC bound), incl. after a restart.

Every test drives PRODUCTION code: the real PresenceCoordinator._run_inference
with real ZonePresenceTracker objects, the real PersonCoordinator
._async_update_data (D2 chain), the real _dispatch_house_state_change, the
real UniversalRoomDatabase DAO over a temp sqlite file, the real
PresenceHouseStateSensor. Oracles are hand-derived literals. Modules load
under a private ``ura_`` alias package (restored by conftest
SUITE-HYGIENE-1); every other patch goes through ``monkeypatch``.

Per-site mutation drills: quality/tests/test_house_state_sleep_mask_mutation_drills.py
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

_URA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_sleepmask_pkg"


_POLLUTABLE = ("homeassistant", "aiosqlite")


def _load():
    """Import the alias package against a FRESH copy of homeassistant /
    aiosqlite.

    Suite-order hygiene (validator name-diff 2026-10-18): earlier test files
    both replace ``sys.modules`` entries with hand-made stubs (e.g.
    ``homeassistant.util.dt`` without DEFAULT_TIME_ZONE) AND overwrite
    attributes on REAL modules (DataUpdateCoordinator, SensorEntity), and
    conftest restores only sys.modules values, not package attributes.
    So: hide EVERY entry of those namespaces, import the alias stack (it
    re-imports clean library modules from site-packages and binds them),
    then put every original entry back exactly as it was. Nothing in
    sys.modules is permanently changed (DoD 8); only the alias package and
    its private bindings persist.
    """
    if f"{_PKG}.domain_coordinators.presence" in sys.modules:
        return _import_names()
    saved = {
        k: v for k, v in sys.modules.items()
        if k.split(".")[0] in _POLLUTABLE
    }
    for k in saved:
        del sys.modules[k]
    try:
        return _import_names()
    finally:
        for k in [k for k in sys.modules if k.split(".")[0] in _POLLUTABLE]:
            del sys.modules[k]
        sys.modules.update(saved)


def _import_names():
    if f"{_PKG}.domain_coordinators.presence" not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA_ROOT)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA_ROOT / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    names = (
        "const", "fan_veto", "domain_coordinators.house_state",
        "domain_coordinators.presence", "person_coordinator", "database",
        "perimeter_alert", "sensor",
    )
    return [importlib.import_module(f"{_PKG}.{n}") for n in names]


CONST, FV, HSM, PR, PC, DB, PA, SE = _load()
DOMAIN = CONST.DOMAIN
HS = HSM.HouseState
ZPM = PR.ZonePresenceMode
ACTIVE = CONST.TRACKING_STATUS_ACTIVE
STALE = CONST.TRACKING_STATUS_STALE
LOST = CONST.TRACKING_STATUS_LOST
_DT = PR.dt_util  # homeassistant.util.dt (shared module object)

T0 = datetime(2026, 10, 18, 2, 0, 0, tzinfo=timezone.utc)   # 02:00, in sleep hours
DAY = datetime(2026, 10, 18, 14, 0, 0, tzinfo=timezone.utc)  # 14:00, day


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self, t):
        self.t = t

    def advance(self, seconds):
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    c = _Clock(T0)
    monkeypatch.setattr(_DT, "now", lambda *a, **k: c.t)
    monkeypatch.setattr(_DT, "utcnow", lambda: c.t)
    monkeypatch.setattr(_DT, "DEFAULT_TIME_ZONE", timezone.utc)
    return c


class _State:
    def __init__(self, state, attrs=None, last_changed=None):
        self.state = state
        self.attributes = dict(attrs or {})
        self.last_changed = last_changed


class _Entry:
    def __init__(self, entry_id, data, options=None):
        self.entry_id = entry_id
        self.data = dict(data)
        self.options = dict(options or {})


def _room_entry(room, *, presence=(), motion=(), occupancy=()):
    return _Entry(f"entry_{room}", {
        CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM,
        CONST.CONF_ROOM_NAME: room,
        CONST.CONF_MMWAVE_SENSORS: list(presence),
        CONST.CONF_MOTION_SENSORS: list(motion),
        CONST.CONF_OCCUPANCY_SENSORS: list(occupancy),
    })


# Device models for the scoped registry fake (shapes from
# AUDIT_motion_sensors_live_models.md / SENSOR_FLEET_CLASSES.md).
_MODELS = {
    "binary_sensor.wig_master_zx_occupancy": ("ZG-204ZX", "24Ghz millimeter wave and T&H sensor"),
    "binary_sensor.wig_upstairs_zx_occupancy": ("ZG-204ZX", "24Ghz millimeter wave and T&H sensor"),
    "binary_sensor.pir_jaya_motion": ("SNZB-03P", "Motion sensor"),
}


def _install_registry(monkeypatch, phone_left_behind=None):
    """Scoped entity/device registry fake (monkeypatch-restored).

    Drives the REAL fan_veto.resolve_sensor_family (ZX filed under
    occupancy_sensors resolves to a radar family) and the REAL
    `_phone_trustworthy` registry lookup (unique_id -> entity_id).
    """
    plb = dict(phone_left_behind or {})

    def _get_entity_id(domain, platform, unique_id):
        return plb.get(unique_id)

    ent_reg = types.SimpleNamespace(
        async_get=lambda eid: (
            types.SimpleNamespace(device_id=f"dev::{eid}")
            if eid in _MODELS else None
        ),
        async_get_entity_id=_get_entity_id,
    )
    dev_reg = types.SimpleNamespace(
        async_get=lambda did: (
            types.SimpleNamespace(
                model_id=_MODELS[did[5:]][0], model=_MODELS[did[5:]][1],
            )
            if did.startswith("dev::") and did[5:] in _MODELS else None
        ),
    )
    er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
    er_mod.async_get = lambda hass: ent_reg
    dr_mod = types.ModuleType("homeassistant.helpers.device_registry")
    dr_mod.async_get = lambda hass: dev_reg
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", er_mod)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.device_registry", dr_mod)
    helpers = sys.modules.get("homeassistant.helpers")
    if helpers is not None:
        monkeypatch.setattr(helpers, "entity_registry", er_mod, raising=False)
        monkeypatch.setattr(helpers, "device_registry", dr_mod, raising=False)


def _close(coro, *a, **k):
    try:
        coro.close()
    except Exception:  # noqa: BLE001
        pass
    return MagicMock()


class World:
    """A PresenceCoordinator over real trackers + a real HouseStateMachine."""

    def __init__(self, monkeypatch, *, zones, entries=(), states=None,
                 state=HS.SLEEP, census=0, camera_dark=False,
                 phone_left_behind=None):
        _install_registry(monkeypatch, phone_left_behind)
        self.states = dict(states or {})
        self.entries = list(entries)
        self.dispatched = []
        self.db_rows = []
        hass = MagicMock()
        hass.states.get = lambda eid: self.states.get(eid)
        hass.config_entries.async_entries = lambda domain=None: list(self.entries)
        hass.async_create_task = _close
        hass.async_create_background_task = _close
        hass.is_running = True
        sm = HSM.HouseStateMachine(initial_state=state)
        sm._state_since = _DT.utcnow() - timedelta(hours=2)
        manager = MagicMock()
        manager.house_state_machine = sm
        manager.coordinators = {}
        world = self

        async def _noop_coro():
            return None

        class _FakeDB:
            def log_house_state_change(self, **kw):
                # Recorded at schedule time (hass.async_create_task closes
                # the coroutine in this harness).
                world.db_rows.append(kw)
                return _noop_coro()

            def __getattr__(self, name):
                return lambda *a, **k: _noop_coro()

        hass.data = {DOMAIN: {"coordinator_manager": manager}}
        self.hass, self.sm, self.manager = hass, sm, manager
        coord = PR.PresenceCoordinator(hass, sleep_start_hour=23, sleep_end_hour=6)
        coord._enabled = True
        coord._boot_settle_done = True
        coord._census_count = census
        coord._unidentified_count = 0
        coord._census_camera_input_dark = camera_dark
        self.coord = coord
        manager.presence = coord
        manager.coordinators = {"presence": coord}
        self.trackers = {}
        for zname, rooms in zones.items():
            t = PR.ZonePresenceTracker(hass, zname, list(rooms))
            t.mark_has_sensors()
            for r in rooms:
                t.update_room_occupancy(r, False)
            self.trackers[zname] = t
        coord._zone_trackers = self.trackers
        # Real `_discover_room_sensors` (CONF lists -> tracker.register_entity)
        # over a substrate stub reporting no live kinds; the tests drive the
        # per-kind provenance explicitly below.
        coord._substrate = types.SimpleNamespace(get_room_kinds=lambda r: {})
        coord._discover_room_sensors()
        if state == HS.SLEEP:
            for t in self.trackers.values():
                t.set_sleep(True)

        def _send(_hass, signal, *args):
            world.dispatched.append((signal, args))

        monkeypatch.setattr(PR, "async_dispatcher_send", _send)
        self._FakeDB = _FakeDB

    def with_db(self):
        self.hass.data[DOMAIN]["database"] = self._FakeDB()
        return self

    def occupy(self, zone, room, kind="mmwave"):
        self.trackers[zone].update_room_occupancy(room, True, kind=kind)

    def clear(self, zone, room):
        """The room really empties: every registered sensor reads off and
        the tracker gets the off-edge."""
        t = self.trackers[zone]
        for eid, r in t._entity_to_room.items():
            if r == room:
                self.states[eid] = _State("off")
        t.update_room_occupancy(room, False)

    def fan_on(self, zone, room):
        self.trackers[zone]._fan_on_rooms.add(room)

    def persons(self, data):
        pc = MagicMock()
        pc.data = data
        pc._lost_away_since = {}
        self.hass.data[DOMAIN]["person_coordinator"] = pc
        return pc

    def tick(self):
        _run(self.coord._run_inference("test"))
        return self.sm.state


class SubstrateWorld(World):
    """World + a REAL OccupancySubstrate (sleep-mask Rev 3.1 R3.1.8).

    Dict-backed ``hass.states``; ``async_track_state_change_event`` patched
    to capture the substrate's callback; the substrate's
    ``async_dispatcher_send`` routed to the REAL
    ``coord._on_substrate_kind_changed`` (so the tracker is never written
    directly); real ``_discover_room_sensors`` over the real substrate;
    ``release_boot_settle()`` before any event. ``fire(entity, state)``
    builds the event (``state=None`` = entity removed from HA).
    """

    def __init__(self, monkeypatch, **kw):
        super().__init__(monkeypatch, **kw)
        SUB = importlib.import_module(
            f"{_PKG}.domain_coordinators.occupancy_substrate")
        self.SUB = SUB
        self.callbacks = []
        self.unsubbed = []
        self.edges = []
        self.retries = []
        self.fail_subscribe = 0
        world = self

        def _track(_hass, entities, cb):
            if world.fail_subscribe:
                world.fail_subscribe -= 1
                raise RuntimeError("subscribe failed")
            world.callbacks.append(cb)

            def _unsub():
                world.unsubbed.append(cb)

            return _unsub

        def _send(_hass, _signal, room, kind, new_state):
            world.edges.append((room, kind, new_state))
            world.coord._on_substrate_kind_changed(room, kind, new_state)

        def _later(_hass, _delay, cb):
            world.retries.append(cb)
            return lambda: None

        monkeypatch.setattr(SUB, "async_track_state_change_event", _track)
        monkeypatch.setattr(SUB, "async_dispatcher_send", _send)
        monkeypatch.setattr(SUB, "async_call_later", _later)
        self.sub = SUB.OccupancySubstrate(self.hass)
        _run(self.sub.async_setup())
        self.coord._substrate = self.sub
        for t in self.trackers.values():
            t._entity_to_room.clear()
        self.coord._discover_room_sensors()

    def release(self):
        self.sub.release_boot_settle()
        return self

    def fire(self, entity, new_state):
        old = self.states.get(entity)
        if new_state is None:
            self.states.pop(entity, None)
            ns = None
        else:
            ns = _State(new_state)
            self.states[entity] = ns
        event = types.SimpleNamespace(data={
            "entity_id": entity, "old_state": old, "new_state": ns,
        })
        self.callbacks[-1](event)

    def refresh(self):
        _run(self.sub.refresh_subscriptions())


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Jaya repro shapes (this house): Jaya Bedroom LD2410 + ZK in presence_sensors.
JAYA_LD = "binary_sensor.jaya_3_presence"
JAYA_ZK = "binary_sensor.mmwave_zigbee_jaya_presence"
JAYA_PIR = "binary_sensor.pir_jaya_motion"
MASTER_ZX = "binary_sensor.master_zx_presence"


def _jaya_world(monkeypatch, *, fan=True, pir_on=False, camera_dark=True,
                kind="mmwave", state=HS.SLEEP):
    states = {JAYA_LD: _State("on"), JAYA_ZK: _State("on"),
              JAYA_PIR: _State("on" if pir_on else "off")}
    entries = [_room_entry("Jaya Bedroom", presence=[JAYA_LD, JAYA_ZK],
                           motion=[JAYA_PIR])]
    w = World(monkeypatch, zones={"Upstairs": ["Jaya Bedroom"],
                                  "Back Hallway": ["Guest Bedroom 1"]},
              entries=entries, states=states, camera_dark=camera_dark,
              state=state)
    w.occupy("Upstairs", "Jaya Bedroom", kind=kind)
    if pir_on:
        w.occupy("Upstairs", "Jaya Bedroom", kind="motion")
    if fan:
        w.fan_on("Upstairs", "Jaya Bedroom")
    return w


# ===========================================================================
# D1 — SLEEP-mask fix (drives _run_inference with real trackers)
# ===========================================================================

def test_nobody_home_blocked_in_sleep_when_zone_raw_occupied(monkeypatch, clock):
    """Fix vs bug: zones pinned by set_sleep(True), census 0, a real room
    occupancy update on a NON radar-sole room (PIR). Expected: not AWAY,
    veto_path 'none'. Old code: AWAY via nobody-home."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")})
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    assert w.trackers["Master Suite"].mode == ZPM.SLEEP
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"
    assert w.coord._nobody_home_zone_input is True


def test_nobody_home_fires_in_sleep_when_all_raw_clear(monkeypatch, clock):
    """Discharge: same setup with all rooms clear -> AWAY on that tick,
    veto_path 'nobody_home' (INV-EMPTY-REACHES-AWAY)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])])
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path == "nobody_home"
    assert w.coord._nobody_home_zone_input is False


def test_radar_only_sleeper_with_fan_on_holds(monkeypatch, clock):
    """Rev 2.1 (stress test P5, breaker dropped): Jaya's room is radar-only
    (LD2410 + ZK) with the fan on, Frigate dark, census 0 -> SLEEP holds.
    The Rev 2 fan-loop breaker would have returned AWAY here."""
    w = _jaya_world(monkeypatch, fan=True)
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"
    assert w.coord._nobody_home_zone_input is True


def test_zone_sleep_pin_survives_home_override_raw_limb_applies(monkeypatch, clock):
    """R2 M2: house SLEEP inferred (zones pinned), then a HOME_DAY override.
    Zones stay SLEEP-pinned (only 'auto' clears them) and the raw limb
    applies outside house SLEEP — keyed on tracker mode, not house state."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")})
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    w.coord.set_house_state_override("home_day")
    assert w.sm.state == HS.HOME_DAY
    assert w.trackers["Master Suite"].mode == ZPM.SLEEP
    assert w.tick() == HS.HOME_DAY
    assert w.coord._veto_path == "none"
    assert w.coord._nobody_home_zone_input is True


def test_zone_away_override_carve_out(monkeypatch, clock):
    """PICK 1 default (carve-out): a zone under a manual AWAY override with
    its radar on, house SLEEP, census 0 -> AWAY (the zone counts empty)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX])],
              states={MASTER_ZX: _State("on")})
    w.occupy("Master Suite", "Master Bedroom", kind="mmwave")
    t = w.trackers["Master Suite"]
    t.clear_override()
    t.set_override(ZPM.AWAY)  # stale manual AWAY override, no new edge
    assert t.mode == ZPM.AWAY and t.raw_occupied is True
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path == "nobody_home"


def test_nobody_home_non_sleep_byte_identical(monkeypatch, clock):
    """INV-BYTE-ID: no SLEEP-mode tracker -> the D1 input equals the masked
    `any_zone_occupied` and the infer() outcome is unchanged (occupied
    zone -> no AWAY; empty -> AWAY). Daytime, HOME_DAY."""
    clock.t = DAY
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")}, state=HS.HOME_DAY)
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    assert w.tick() == HS.HOME_DAY
    assert w.coord._nobody_home_zone_input is True
    w.clear("Master Suite", "Master Bedroom")
    assert w.tick() == HS.AWAY
    assert w.coord._nobody_home_zone_input is False


def test_infer_byte_identical_when_input_equals_masked():
    """INV-BYTE-ID at the engine: for every (census, any_zone_occupied,
    current_state) the result with any_zone_occupied_for_empty equal to the
    masked value (or None) equals the result without it."""
    for census in (0, 1):
        for occ in (False, True):
            for cur in (HS.HOME_DAY, HS.SLEEP, HS.AWAY):
                a = PR.StateInferenceEngine()
                b = PR.StateInferenceEngine()
                c = PR.StateInferenceEngine()
                ra = a.infer(census, cur, occ, now=DAY)
                rb = b.infer(census, cur, occ, now=DAY,
                             any_zone_occupied_for_empty=occ)
                rc = c.infer(census, cur, occ, now=DAY,
                             any_zone_occupied_for_empty=None)
                assert ra == rb == rc
                assert a._veto_path == b._veto_path == c._veto_path


def test_already_away_tick_keeps_veto_path_none(monkeypatch, clock):
    """R2 M3: the already-AWAY return keeps veto_path 'none' (the v8 card
    must not stay red for the whole AWAY)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])])
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path == "nobody_home"
    clock.advance(60)
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path == "none"


def test_kill_constant_false_restores_masked_behaviour(monkeypatch, clock):
    monkeypatch.setattr(PR, "PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP", False)
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")})
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    assert w.tick() == HS.AWAY  # today's masked behaviour
    assert w.coord._nobody_home_zone_input is None


def test_night_raw_helper_error_counts_room_occupied(monkeypatch, clock):
    """A raising room view counts the zone OCCUPIED (fail toward holding
    SLEEP)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])])

    def _boom(self):
        raise RuntimeError("room view exploded")

    monkeypatch.setattr(PR.ZonePresenceTracker, "_room_occupied", property(_boom))
    assert w.coord._zone_night_raw(w.trackers["Master Suite"]) is True


def test_night_raw_ble_and_camera_limbs(monkeypatch, clock):
    """The BLE tier and the camera tier each hold SLEEP on their own."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])])
    t = w.trackers["Master Suite"]
    t.update_ble_presence(True)
    assert w.tick() == HS.SLEEP
    t.update_ble_presence(False)
    t.update_camera_detection("camera.master_person", True)
    assert w.tick() == HS.SLEEP
    t.update_camera_detection("camera.master_person", False)
    clock.advance(10_000)  # past the camera occupancy timeout
    assert w.tick() == HS.AWAY


def test_room_in_no_zone_does_not_hold(monkeypatch, clock):
    """A room in no zone (Wigton Gym) contributes nothing (as by day)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Gym", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")})
    w.trackers["Master Suite"].update_room_occupancy("Gym", True, kind="motion")
    assert w.tick() == HS.AWAY


# --- Review D-H1: multi-sensor rooms (tracker view is lossy) ---------------

MASTER_ZV = "binary_sensor.master_zv_presence_2"
JAYA_LD2 = "binary_sensor.jaya_ld2410_b_presence"


@pytest.mark.per_entity_on_only
def test_two_kind_room_zv_pulse_then_clear_keeps_zx_sleeper(monkeypatch, clock):
    """ZX (presence) holds a still sleeper; ZV (motion) pulses on a
    roll-over then clears. Rev 3 D4b: the motion off-edge clears ONLY the
    motion kind, so the tracker still holds the room (the review D-H1
    defect line is inverted) -> SLEEP holds (no nobody-home AWAY)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX],
                                   motion=[MASTER_ZV])],
              states={MASTER_ZX: _State("on"), MASTER_ZV: _State("off")})
    w.occupy("Master Suite", "Master Bedroom", kind="mmwave")
    w.states[MASTER_ZV] = _State("on")
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    w.states[MASTER_ZV] = _State("off")
    w.trackers["Master Suite"].update_room_occupancy(
        "Master Bedroom", False, kind="motion")   # kind-specific clear (D4b)
    assert w.trackers["Master Suite"].raw_occupied is True   # defect gone
    assert w.trackers["Master Suite"].provenance_for("Master Bedroom") == {
        "motion": False, "mmwave": True, "occupancy": False}
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"


@pytest.mark.per_entity_off_only
def test_two_kind_room_zv_pulse_then_clear_keeps_zx_sleeper_switch_off(monkeypatch, clock):
    """Kill-switch anchor (dad3bf6e7 version): switch off -> the off-edge
    wipes the whole room (the defect) and the D-H1 live-sensor limb holds
    SLEEP through the ZX still reading on."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX],
                                   motion=[MASTER_ZV])],
              states={MASTER_ZX: _State("on"), MASTER_ZV: _State("off")})
    w.occupy("Master Suite", "Master Bedroom", kind="mmwave")
    w.states[MASTER_ZV] = _State("on")
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    w.states[MASTER_ZV] = _State("off")
    w.trackers["Master Suite"].update_room_occupancy(
        "Master Bedroom", False, kind="motion")   # the lossy full-room wipe
    assert w.trackers["Master Suite"].raw_occupied is False   # the defect
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"


@pytest.mark.per_entity_on_only
def test_same_kind_two_sensor_room_one_off_keeps_sleeper(monkeypatch, clock):
    """Two radars of the SAME kind (LD2410 + second LD2410 in
    presence_sensors), both on; one goes off. Driven through the REAL
    substrate (the tracker alone cannot know about same-kind siblings):
    D4a keeps the kind on (no dispatch), so SLEEP holds."""
    w = SubstrateWorld(
        monkeypatch, zones={"Upstairs": ["Jaya Bedroom"]},
        entries=[_room_entry("Jaya Bedroom", presence=[JAYA_LD, JAYA_LD2])],
        states={JAYA_LD: _State("on"), JAYA_LD2: _State("on")}).release()
    assert w.trackers["Upstairs"].raw_occupied is True
    n_edges = len(w.edges)
    w.fire(JAYA_LD2, "off")
    assert len(w.edges) == n_edges          # no (room, mmwave, False) edge
    assert w.sub.get_room_kinds("Jaya Bedroom")["mmwave"] is True
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"


@pytest.mark.per_entity_off_only
def test_same_kind_two_sensor_room_one_off_keeps_sleeper_switch_off(monkeypatch, clock):
    """Kill-switch anchor (dad3bf6e7 version). Two radars of the SAME kind (LD2410 + ZK in presence_sensors): one
    drops, the substrate's last-writer kind reports False and the tracker
    wipes the room, but the other radar is still on -> SLEEP holds."""
    w = World(monkeypatch, zones={"Upstairs": ["Jaya Bedroom"]},
              entries=[_room_entry("Jaya Bedroom", presence=[JAYA_LD, JAYA_LD2])],
              states={JAYA_LD: _State("on"), JAYA_LD2: _State("off")})
    w.occupy("Upstairs", "Jaya Bedroom", kind="mmwave")
    w.trackers["Upstairs"].update_room_occupancy(
        "Jaya Bedroom", False, kind="mmwave")
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"


@pytest.mark.per_entity_on_only
def test_multi_sensor_room_really_empty_still_reaches_away(monkeypatch, clock):
    """Discharge, substrate-driven: both sensors of a two-kind room go off
    -> False edges -> AWAY via nobody-home."""
    w = SubstrateWorld(
        monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
        entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX],
                             motion=[MASTER_ZV])],
        states={MASTER_ZX: _State("on"), MASTER_ZV: _State("on")}).release()
    w.fire(MASTER_ZV, "off")
    assert w.tick() == HS.SLEEP
    w.fire(MASTER_ZX, "off")
    assert ("Master Bedroom", "mmwave", False) in w.edges
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path == "nobody_home"


def test_tracker_view_alone_holds_room(monkeypatch, clock):
    """The tracker limb is load-bearing on its own: a room the tracker holds
    with no live `on` sensor (fan-interference hold extension, seeded
    provenance) still holds SLEEP."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX])],
              states={MASTER_ZX: _State("off")})
    t = w.trackers["Master Suite"]
    t._fan_interference_hold_until["Master Bedroom"] = (
        clock.t + timedelta(seconds=300)
    )
    assert w.coord._zone_night_rooms(t) == ["Master Bedroom"]
    assert w.tick() == HS.SLEEP


@pytest.mark.per_entity_on_only
def test_unavailable_sibling_and_foreign_room_do_not_hold(monkeypatch, clock):
    """Substrate-driven: an unavailable registered sensor contributes off,
    and a sensor mapped to a room outside the zone never reaches this
    tracker (the tracker drops a room it does not own)."""
    w = SubstrateWorld(
        monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
        entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX, JAYA_LD2]),
                 _room_entry("Gym", presence=["binary_sensor.elsewhere"])],
        states={MASTER_ZX: _State("on"), JAYA_LD2: _State("off"),
                "binary_sensor.elsewhere": _State("on")}).release()
    w.fire(MASTER_ZX, "unavailable")
    t = w.trackers["Master Suite"]
    assert w.sub.get_room_kinds("Master Bedroom")["mmwave"] is False
    assert t.raw_occupied is False
    assert "Gym" not in t._room_provenance       # foreign room never lands
    assert w.tick() == HS.AWAY


@pytest.mark.per_entity_off_only
def test_live_limb_ignores_unavailable_and_other_rooms(monkeypatch, clock):
    """Only `on` counts (unavailable is not occupancy), and a sensor
    registered to a room outside the zone never holds it."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX])],
              states={MASTER_ZX: _State("unavailable")})
    t = w.trackers["Master Suite"]
    t.register_entity("binary_sensor.elsewhere", "Gym")
    w.states["binary_sensor.elsewhere"] = _State("on")
    assert w.coord._zone_night_rooms(t) == []
    assert w.tick() == HS.AWAY


# --- Review D-M1 / B-M1: label captured before the await ---------------------

def test_concurrent_tick_cannot_overwrite_away_branch(monkeypatch, clock):
    """Tick 1 fires nobody-home and awaits the decision log; a concurrent
    tick (now already AWAY -> label 'none') runs inside that await. The
    dispatch must still record 'nobody_home' (counter attribute AND the D7
    episode payload)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])]).with_db()
    mw = importlib.import_module(f"{_PKG}.memory_writers")
    d7 = []
    monkeypatch.setattr(mw, "write_house_state_transition",
                        lambda hass, **kw: d7.append(kw["snapshot"]["veto_path"]))
    inner = []

    class _Logger:
        async def log_decision(self, decision):
            if not inner:
                inner.append(1)
                await w.coord._run_inference("concurrent")

    w.coord.decision_logger = _Logger()
    assert w.tick() == HS.AWAY
    assert inner == [1]
    assert w.coord._veto_path == "none"          # the concurrent tick's mirror
    assert w.coord._last_away_branch == "nobody_home"
    assert d7 == ["nobody_home"]


# --- Review D-M3: β indoor input with sleep exemption OFF --------------------

def test_beta_with_sleep_exempt_off_does_not_away_pinned_sleeper(monkeypatch, clock):
    """lost_away_sleep_exempt=False (legal options-flow value), SLEEP,
    camera fleet dark (α skipped), the one tracked resident ACTIVE away,
    an untracked sleeper's radar on, census 0 -> β must not fire."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", presence=[MASTER_ZX])],
              states={MASTER_ZX: _State("on")}, camera_dark=True)
    w.occupy("Master Suite", "Master Bedroom", kind="mmwave")
    w.coord._cm_entry_cache = _Entry("cm", {
        CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_COORDINATOR_MANAGER,
        CONST.CONF_LOST_AWAY_SLEEP_EXEMPT: False,
    })
    w.coord._indoor_clear_consecutive_ticks = 5
    w.persons({"oji": {"location": "away", "tracking_status": ACTIVE,
                       "tracking_reason": "away_gps"}})
    for _ in range(4):
        assert w.tick() == HS.SLEEP
        assert w.coord._veto_path == "none"
        clock.advance(60)


# --- D1b wake-time discharge + trip-wire (Rev 2.1, P5) ----------------------

def _raw_held_world(monkeypatch, *, zones_state=HS.SLEEP):
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")}, state=zones_state)
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    return w


def test_sleep_leaves_after_window_with_raw_occupancy(monkeypatch, clock):
    """INV-SLEEP-HOLD-BOUNDED (b): SLEEP, census 0, raw occupied, no
    override. At 06:00 + 2 min (after the 90 s raw WAKING gate) the house
    has left SLEEP. Before 06:00 it holds."""
    w = _raw_held_world(monkeypatch)
    clock.t = datetime(2026, 10, 18, 5, 58, tzinfo=timezone.utc)
    assert w.tick() == HS.SLEEP
    clock.advance(60)
    assert w.tick() == HS.SLEEP  # 05:59, still a sleep hour
    clock.advance(60)
    w.tick()                      # 06:00
    clock.advance(60)
    w.tick()                      # 06:01
    clock.advance(60)
    assert w.tick() != HS.SLEEP   # 06:02
    assert w.sm.state in (HS.WAKING, HS.HOME_DAY)


def test_infer_wake_disjunct_engine_level():
    """D1b at the engine: SLEEP, census 0, masked zones empty, raw true,
    hour 07 -> WAKING; same inputs at 03:00 -> None (held); raw None
    (kill switch) at 07 -> AWAY via nobody-home (today)."""
    seven = datetime(2026, 10, 18, 7, 0, tzinfo=timezone.utc)
    three = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)
    e = PR.StateInferenceEngine()
    assert e.infer(0, HS.SLEEP, False, now=seven,
                   any_zone_occupied_for_empty=True) == HS.WAKING
    assert e.infer(0, HS.SLEEP, False, now=three,
                   any_zone_occupied_for_empty=True) is None
    assert e.infer(0, HS.SLEEP, False, now=seven) == HS.AWAY
    # Only SLEEP: a HOME_DAY house with the same inputs is unchanged (None).
    assert e.infer(0, HS.HOME_DAY, False, now=seven,
                   any_zone_occupied_for_empty=True) is None
    # Only SLEEP: an AWAY house whose zones are SLEEP-pinned by a manual
    # zone override must not be pulled to ARRIVING by the disjunct.
    assert e.infer(0, HS.AWAY, False, now=seven,
                   any_zone_occupied_for_empty=True) is None


def _capture_stuck(monkeypatch):
    fired = []
    mod = importlib.import_module(f"{_PKG}.domain_coordinators._stuck_signal_nm")

    async def _fake(hass, kind, key, diagnosis, remedy="", **kw):
        fired.append((kind, key, diagnosis))
        fired_kw.append(kw)
        return True

    fired_kw = []
    _capture_stuck.kw = fired_kw

    monkeypatch.setattr(mod, "fire_stuck_signal", _fake)
    return fired


def _pending(w):
    w.pending = []

    def _sched(coro, *a, **k):
        if getattr(coro, "__qualname__", "").endswith("_fake"):
            w.pending.append(coro)
        else:
            coro.close()
        return MagicMock()

    return _sched


def _drive_hold(w, clock, minutes):
    for _ in range(minutes):
        w.tick()
        clock.advance(60)
        while getattr(w, "pending", None):
            _run(w.pending.pop(0))


def _block_transitions(w):
    """Simulate a FAILED D1b discharge: the state machine refuses every
    transition, so SLEEP is held past the window end."""
    w.sm.transition = lambda *a, **k: False


def test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound(monkeypatch, clock):
    """SLEEP still raw-held with census 0 more than 5400 s after the 06:00
    window end -> exactly one NM (window end + 90 min = 07:30)."""
    fired = _capture_stuck(monkeypatch)
    w = _raw_held_world(monkeypatch)
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    clock.t = datetime(2026, 10, 18, 5, 50, tzinfo=timezone.utc)
    _drive_hold(w, clock, 100)     # 05:50 .. 07:29
    assert fired == []
    _drive_hold(w, clock, 3)       # 07:30, 07:31, 07:32
    assert len(fired) == 1
    kind, key, diag = fired[0]
    assert kind == "sleep_raw_hold" and key == ("house",)
    assert "Master Bedroom" in diag
    # Review A-M2 / B-L2: HIGH (MEDIUM reaches no channel live).
    assert _capture_stuck.kw[0].get("severity") == "HIGH"
    _drive_hold(w, clock, 30)      # same episode -> no repeat
    assert len(fired) == 1


def test_sleep_raw_hold_tripwire_silent_during_sleep_window(monkeypatch, clock):
    """An overnight raw-only hold (23:00 -> 05:59) is NORMAL: no NM."""
    fired = _capture_stuck(monkeypatch)
    w = _raw_held_world(monkeypatch)
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    clock.t = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)
    _drive_hold(w, clock, 7 * 60)  # through 05:59
    assert fired == []


def test_sleep_raw_hold_tripwire_not_when_census_positive(monkeypatch, clock):
    fired = _capture_stuck(monkeypatch)
    w = _raw_held_world(monkeypatch)
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    w.coord._census_count = 1
    clock.t = datetime(2026, 10, 18, 5, 50, tzinfo=timezone.utc)
    _drive_hold(w, clock, 200)
    assert fired == []


def test_sleep_raw_hold_tripwire_kill_switch_zero(monkeypatch, clock):
    fired = _capture_stuck(monkeypatch)
    monkeypatch.setattr(PR, "SLEEP_RAW_HOLD_NM_BOUND_S", 0)
    w = _raw_held_world(monkeypatch)
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    clock.t = datetime(2026, 10, 18, 5, 50, tzinfo=timezone.utc)
    _drive_hold(w, clock, 200)
    assert fired == []


def test_sleep_raw_hold_tripwire_episode_resets_when_room_clears(monkeypatch, clock):
    """One NM per episode; the latch resets when the hold ends, so a NEW
    raw-only hold past the bound pages again."""
    fired = _capture_stuck(monkeypatch)
    w = _raw_held_world(monkeypatch)
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    clock.t = datetime(2026, 10, 18, 7, 31, tzinfo=timezone.utc)
    _drive_hold(w, clock, 2)
    assert len(fired) == 1
    w.clear("Master Suite", "Master Bedroom")
    _drive_hold(w, clock, 1)       # not held (raw clear) -> episode ends
    w.states[JAYA_PIR] = _State("on")
    w.occupy("Master Suite", "Master Bedroom", kind="motion")
    _drive_hold(w, clock, 2)       # new episode, still past the bound
    assert len(fired) == 2


def test_sleep_raw_hold_tripwire_skips_override_2130_early_bedtime(monkeypatch, clock):
    """Review A-M1: a 21:30 house SLEEP override (early bedtime) over a
    census-0 raw hold must not page (the window has not started; D1b
    cannot release an override)."""
    fired = _capture_stuck(monkeypatch)
    clock.t = datetime(2026, 10, 18, 21, 30, tzinfo=timezone.utc)
    w = _raw_held_world(monkeypatch, zones_state=HS.HOME_EVENING)
    w.hass.async_create_task = _pending(w)
    w.coord.set_house_state_override("sleep")
    assert w.sm.state == HS.SLEEP and w.sm.is_overridden
    _drive_hold(w, clock, 60)      # 21:30 .. 22:29
    assert fired == []


def test_sleep_raw_hold_tripwire_skips_override_1400_nap(monkeypatch, clock):
    """Review D-M2: a 14:00 nap (house SLEEP override over HOME_DAY, ZX on,
    census 0) holds SLEEP correctly and never pages."""
    fired = _capture_stuck(monkeypatch)
    clock.t = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
    w = _raw_held_world(monkeypatch, zones_state=HS.HOME_DAY)
    w.hass.async_create_task = _pending(w)
    w.coord.set_house_state_override("sleep")
    _drive_hold(w, clock, 150)
    assert fired == []
    assert w.sm.state == HS.SLEEP


def test_sleep_raw_hold_tripwire_anchors_at_sleep_entry(monkeypatch, clock):
    """Anchor = max(window end, SLEEP entry). Inferred SLEEP entered at
    06:30 (after the 06:00 end): at 07:45 the hold is 75 min from entry ->
    no page (window-end anchoring would page at 07:30); at 08:01 -> 91 min
    from entry -> page."""
    fired = _capture_stuck(monkeypatch)
    w = _raw_held_world(monkeypatch)
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    w.sm._state_since = datetime(2026, 10, 18, 6, 30, tzinfo=timezone.utc)
    clock.t = datetime(2026, 10, 18, 7, 0, tzinfo=timezone.utc)
    _drive_hold(w, clock, 46)      # 07:00 .. 07:45
    assert fired == []
    _drive_hold(w, clock, 16)      # .. 08:01
    assert len(fired) == 1


def test_sleep_raw_hold_tripwire_non_wrapping_window_rolls_back_a_day(monkeypatch, clock):
    """Review C M5b: non-wrapping window 01->07, now 00:30 (not a sleep
    hour, BEFORE today's 07:00 end). window_end must roll back to
    yesterday 07:00, so a SLEEP entered yesterday 22:00 is 150 min past
    max(window end, entry) and pages. Without the roll the anchor is
    today 07:00 (future) and nothing fires."""
    fired = _capture_stuck(monkeypatch)
    w = _raw_held_world(monkeypatch)
    w.coord._inference_engine.sleep_start_hour = 1
    w.coord._inference_engine.sleep_end_hour = 7
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    w.sm._state_since = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)
    clock.t = datetime(2026, 10, 18, 0, 30, tzinfo=timezone.utc)
    _drive_hold(w, clock, 1)
    assert len(fired) == 1


def test_fire_stuck_signal_severity_kwarg(monkeypatch, clock):
    """The shared NM path: default stays MEDIUM (byte-identical for other
    callers); severity='HIGH' reaches the notifier as HIGH."""
    mod = importlib.import_module(f"{_PKG}.domain_coordinators._stuck_signal_nm")
    nm_mod = importlib.import_module(f"{_PKG}.domain_coordinators.notification_manager")
    sent = []

    class _NM:
        async def async_notify(self, **kw):
            sent.append(kw["severity"])

    hass = MagicMock()
    hass.data = {DOMAIN: {"notification_manager": _NM()}}
    monkeypatch.setattr(mod, "_kill_switch_on", lambda h: True)
    monkeypatch.setattr(mod, "_write_stuck_anomaly", lambda *a, **k: _noop())
    mod._LATCHES.clear()
    assert _run(mod.fire_stuck_signal(hass, "k1", ("a",), "d")) is True
    assert _run(mod.fire_stuck_signal(hass, "k2", ("a",), "d",
                                      severity="HIGH")) is True
    assert sent == [nm_mod.Severity.MEDIUM, nm_mod.Severity.HIGH]
    mod._LATCHES.clear()


async def _noop():
    return None


# --- periodic registration (discharge isolation) --------------------------

def _setup_with_capture(monkeypatch, discovery_raises):
    calls = []

    def _track(hass, cb, interval):
        handle = MagicMock(name="unsub_periodic")
        calls.append((cb, interval, handle))
        return handle

    monkeypatch.setattr(PR, "async_track_time_interval", _track)
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_entries = lambda domain=None: []
    hass.async_create_task = _close
    hass.async_create_background_task = _close
    hass.is_running = True
    coord = PR.PresenceCoordinator(hass)
    if discovery_raises:
        def _raise():
            raise RuntimeError("discovery exploded")
        monkeypatch.setattr(coord, "_build_room_area_map", _raise)
    asyncio.run(coord.async_setup())
    periodic = [c for c in calls if getattr(c[0], "__func__", None)
                is PR.PresenceCoordinator._periodic_inference]
    return coord, periodic


def test_periodic_registered_when_discovery_raises(monkeypatch, clock):
    coord, periodic = _setup_with_capture(monkeypatch, discovery_raises=True)
    assert len(periodic) == 1
    assert periodic[0][1] == timedelta(seconds=60)
    assert periodic[0][2] in coord._unsub_listeners


def test_periodic_cancelled_on_unload_and_not_double_registered(monkeypatch, clock):
    coord, periodic = _setup_with_capture(monkeypatch, discovery_raises=False)
    assert len(periodic) == 1
    handle = periodic[0][2]
    asyncio.run(coord.async_teardown())
    handle.assert_called_once_with()
    assert handle not in coord._unsub_listeners


# ===========================================================================
# D2 — STALE counts as home (chained through the REAL PersonCoordinator)
# ===========================================================================

class _PersonHarness:
    """Real PersonCoordinator._async_update_data with the Bermuda area
    state scripted per tick. Registry-heavy helpers are stubbed; the STALE
    / ACTIVE / LOST classification is production code."""

    def __init__(self, world, names, decay, bermuda=True):
        pc = object.__new__(PC.PersonTrackingCoordinator)
        pc.hass = world.hass
        pc.tracked_persons = list(names)
        pc.decay_timeout = decay
        pc.data = None
        pc._person_was_away = {}
        pc._person_lost_since = {}
        pc._lost_away_since = {}
        pc._entity_missing_noted = set()
        pc._pre_arrival_enabled = False
        pc._min_away_minutes = 15
        pc._last_snapshot_time = _DT.now()
        pc._SNAPSHOT_INTERVAL_SECONDS = 900
        pc._scanner_to_rooms = {}
        pc._area_id_to_room = {}
        pc._direct_ble_rooms = set()

        async def _noop(*a, **k):
            return None

        async def _area(name):
            return f"sensor.{name}_area" if bermuda else None

        async def _conf(*a, **k):
            return 0.9

        pc._build_scanner_room_map = _noop
        pc._find_bermuda_area_sensor = _area
        pc._resolve_person_room = lambda area: area
        pc._calculate_confidence = _conf
        pc._log_person_room_change = _noop
        pc._ble_fleet_live = lambda now: True
        world.hass.bus.async_fire = lambda *a, **k: None
        world.hass.data[DOMAIN]["person_coordinator"] = pc
        self.pc, self.world = pc, world

    def tick(self):
        self.pc.data = _run(self.pc._async_update_data())
        return self.pc.data


def _d2_world(monkeypatch, clock, *, decay=300, kill=None):
    """Daytime, HOME_DAY; an indoor zone is occupied so nobody-home never
    fires and path α alone decides (α ignores zones, ledger #12). Oji is
    away (no BLE); Jaya is the BLE resident whose fix drops out."""
    clock.t = DAY
    if kill is not None:
        monkeypatch.setattr(PR, "PRESENCE_STALE_RESIDENT_COUNTS_HOME", kill)
    w = World(monkeypatch, zones={"Living": ["Living Room"]},
              entries=[_room_entry("Living Room", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")}, state=HS.HOME_DAY)
    w.occupy("Living", "Living Room", kind="motion")
    w.states["person.jaya"] = _State("not_home")
    w.states["person.oji"] = _State("not_home")
    w.states["sensor.oji_area"] = _State("unknown")
    w.states["sensor.jaya_area"] = _State("Study A")
    h = _PersonHarness(w, ["jaya", "oji"], decay)
    return w, h


def _run_dropout(w, h, clock, *, flicker_cycles=0, horizon=1500):
    """Bermuda resolves Jaya; optionally flickers resolved/unresolved for
    `flicker_cycles` 60 s cycles; then stops resolving. Person ticks every
    30 s, presence ticks every 60 s. Returns (last_fix, away_at)."""
    last_fix = None
    for _ in range(flicker_cycles):
        w.states["sensor.jaya_area"] = _State("Study A")
        h.tick()
        last_fix = clock.t
        w.tick()
        clock.advance(30)
        w.states["sensor.jaya_area"] = _State("unknown")
        h.tick()
        assert w.tick() == HS.HOME_DAY, "flicker gap flipped AWAY"
        clock.advance(30)
    w.states["sensor.jaya_area"] = _State("Study A")
    h.tick()
    last_fix = clock.t
    w.states["sensor.jaya_area"] = _State("unknown")
    elapsed = 0
    while elapsed <= horizon:
        clock.advance(30)
        elapsed += 30
        h.tick()
        if elapsed % 60 == 0:
            if w.tick() == HS.AWAY:
                return last_fix, clock.t
    return last_fix, None


def test_stale_resident_blocks_alpha(monkeypatch, clock):
    """Fix vs bug: Jaya STALE in Study A, Oji away -> α not AWAY,
    stale_counted_home=['jaya']. Old code: AWAY with jaya excluded."""
    w, h = _d2_world(monkeypatch, clock)
    h.tick()
    clock.advance(30)
    w.states["sensor.jaya_area"] = _State("unknown")
    data = h.tick()
    assert data["jaya"]["tracking_status"] == STALE
    assert w.tick() == HS.HOME_DAY
    assert w.coord._stale_counted_home == ["jaya"]
    assert "jaya" not in w.coord._excluded_persons
    assert w.coord._tracked_persons_count_trusted == 2
    assert w.coord._all_tracked_persons_away is False


def test_stale_resident_blocks_beta(monkeypatch, clock):
    """β shares α's denominator: camera fleet dark (α skipped), indoor
    clear debounced, census 0, outdoor zone occupied so nobody-home is
    blocked -> β would fire on 'all away'; the STALE resident holds it."""
    clock.t = DAY
    w = World(monkeypatch, zones={"Outside": ["Porch"]},
              entries=[_room_entry("Porch", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")}, state=HS.HOME_DAY,
              camera_dark=True)
    w.occupy("Outside", "Porch", kind="motion")
    monkeypatch.setattr(w.coord, "_outdoor_zone_names_snapshot", lambda: {"Outside"})
    w.coord._indoor_clear_consecutive_ticks = 5
    w.states["person.jaya"] = _State("not_home")
    w.states["person.oji"] = _State("not_home")
    w.states["sensor.oji_area"] = _State("unknown")
    w.states["sensor.jaya_area"] = _State("Study A")
    h = _PersonHarness(w, ["jaya", "oji"], 300)
    h.tick()
    clock.advance(30)
    w.states["sensor.jaya_area"] = _State("unknown")
    assert h.tick()["jaya"]["tracking_status"] == STALE
    assert w.tick() == HS.HOME_DAY
    assert w.coord._veto_path == "none"
    # Control: with D2 off, β fires on the same tick shape.
    monkeypatch.setattr(PR, "PRESENCE_STALE_RESIDENT_COUNTS_HOME", False)
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path in ("lost_admitted", "lost_admitted_immediate")


def test_stale_hold_ends_after_decay_timeout(monkeypatch, clock):
    w, h = _d2_world(monkeypatch, clock)
    last_fix, away_at = _run_dropout(w, h, clock)
    assert away_at is not None
    held = (away_at - last_fix).total_seconds()
    assert 300 <= held <= 390, held   # N .. N + I + T


def test_stale_flicker_hold_bounded_by_last_fix(monkeypatch, clock):
    """R2 M1: alternate resolved/unresolved (no flap on the gaps), then stop
    resolving -> AWAY proposed by last fix + N + I + T (300+30+60)."""
    w, h = _d2_world(monkeypatch, clock)
    last_fix, away_at = _run_dropout(w, h, clock, flicker_cycles=5)
    assert away_at is not None
    held = (away_at - last_fix).total_seconds()
    assert 300 <= held <= 390, held


@pytest.mark.parametrize("decay,lo,hi", [
    (0, 0, 90), (60, 60, 150), (300, 300, 390), (900, 900, 990),
])
def test_stale_hold_config_extremes(monkeypatch, clock, decay, lo, hi):
    """decay_timeout ∈ {0, 60, 300, 900}: AWAY lands in [N, N + I + T] after
    the last fix; N = 0 makes D2 inert (STALE never assigned)."""
    w, h = _d2_world(monkeypatch, clock, decay=decay)
    last_fix, away_at = _run_dropout(w, h, clock, horizon=1500)
    assert away_at is not None
    held = (away_at - last_fix).total_seconds()
    assert lo <= held <= hi, (decay, held)


def test_kill_constant_false_excludes_stale(monkeypatch, clock):
    w, h = _d2_world(monkeypatch, clock, kill=False)
    h.tick()
    clock.advance(30)
    w.states["sensor.jaya_area"] = _State("unknown")
    assert h.tick()["jaya"]["tracking_status"] == STALE
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path == "active"
    assert w.coord._stale_counted_home == []
    assert w.coord._excluded_persons["jaya"].startswith("tracking_status=stale")


def test_d2_preserves_phone_left_behind_precedence(monkeypatch, clock):
    """R2 M1 anchor: STALE + phone_left_behind=on -> excluded with the
    phone_left_behind reason; not counted home."""
    clock.t = DAY
    uid = f"{DOMAIN}_person_jaya_phone_left_behind"
    w = World(monkeypatch, zones={"Living": ["Living Room"]},
              entries=[_room_entry("Living Room", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on"),
                      "binary_sensor.jaya_plb": _State("on")},
              state=HS.HOME_DAY,
              phone_left_behind={uid: "binary_sensor.jaya_plb"})
    w.occupy("Living", "Living Room", kind="motion")
    w.persons({
        "jaya": {"location": "Study A", "tracking_status": STALE,
                 "tracking_reason": "bermuda"},
        "oji": {"location": "away", "tracking_status": ACTIVE,
                "tracking_reason": "away_gps"},
    })
    assert w.tick() == HS.AWAY
    assert w.coord._excluded_persons["jaya"].startswith("phone_left_behind=on")
    assert w.coord._stale_counted_home == []


def test_reliable_signal_lists_aligned_with_stale(monkeypatch, clock):
    """Row 3.2 g: person_tracking_active signals fed to the shared veto
    helper carry STALE as trusted, aligned with the phone list."""
    w, h = _d2_world(monkeypatch, clock)
    captured = {}
    real = w.coord.should_veto_due_to_reliable_signals

    def _spy(reliable_signals, transient_signals, state_context):
        if state_context.get("scope") == "house_inference":
            captured["sig"] = [(s.kind, s.value) for s in reliable_signals]
        return real(reliable_signals=reliable_signals,
                    transient_signals=transient_signals,
                    state_context=state_context)

    monkeypatch.setattr(w.coord, "should_veto_due_to_reliable_signals", _spy)
    h.tick()
    clock.advance(30)
    w.states["sensor.jaya_area"] = _State("unknown")
    h.tick()
    w.tick()
    sig = captured["sig"]
    phone = [v for k, v in sig if k == "person_phone_trustworthy"]
    track = [v for k, v in sig if k == "person_tracking_active"]
    assert phone == [True, True]       # sorted: jaya, oji
    assert track == [True, True]       # jaya STALE now counts


def test_perimeter_persons_home_counts_stale(monkeypatch, clock):
    """Row 3.2 a: NM perimeter severity input persons_home counts a STALE
    resident (2 trusted, was 1)."""
    w, h = _d2_world(monkeypatch, clock)
    h.tick()
    clock.advance(30)
    w.states["sensor.jaya_area"] = _State("unknown")
    h.tick()
    w.tick()
    pam = object.__new__(PA.PerimeterAlertManager)
    pam.hass = w.hass
    assert PA.PerimeterAlertManager._get_persons_home(pam) == 2


def test_signal_consensus_with_stale_resident(monkeypatch, clock):
    """Row 3.2 b: HVAC 'Wait for Presence' reads presence._signal_consensus.
    With a STALE resident the 'phones away + zones occupied' −0.4 term is
    absent. Camera fleet dark keeps α out of both runs, so the ONLY delta
    between D2 on and off is that term (oracle: 0.4)."""
    def _consensus(kill):
        w = World(monkeypatch, zones={"Living": ["Living Room"]},
                  entries=[_room_entry("Living Room", motion=[JAYA_PIR])],
                  states={JAYA_PIR: _State("on")}, state=HS.HOME_DAY,
                  camera_dark=True)
        w.occupy("Living", "Living Room", kind="motion")
        monkeypatch.setattr(PR, "PRESENCE_STALE_RESIDENT_COUNTS_HOME", kill)
        w.persons({
            "jaya": {"location": "Study A", "tracking_status": STALE,
                     "tracking_reason": "bermuda"},
            "oji": {"location": "away", "tracking_status": ACTIVE,
                    "tracking_reason": "away_gps"},
        })
        w.tick()
        return w.coord._signal_consensus, w.coord._signal_consensus_inputs

    clock.t = DAY
    on, on_inputs = _consensus(True)
    off, off_inputs = _consensus(False)
    assert on_inputs["all_tracked_persons_away"] is False
    assert off_inputs["all_tracked_persons_away"] is True
    assert on - off == pytest.approx(0.4)


def test_stale_not_restored_across_restart(monkeypatch, clock):
    """R2 L4: a fresh PersonCoordinator (restart) has no old fix, so an
    unresolved first tick is NOT STALE — the memory fails toward pre-D2."""
    w, h = _d2_world(monkeypatch, clock)
    h.tick()  # fix before restart
    clock.advance(30)
    h2 = _PersonHarness(w, ["jaya", "oji"], 300)  # restart: data=None
    w.states["sensor.jaya_area"] = _State("unknown")
    data = h2.tick()
    assert data["jaya"]["tracking_status"] == ACTIVE
    assert data["jaya"]["location"] == "away"
    assert w.tick() == HS.AWAY


# ===========================================================================
# D3 — observability
# ===========================================================================

def test_last_away_branch_nobody_home(monkeypatch, clock):
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])]).with_db()
    assert w.tick() == HS.AWAY
    assert w.coord._last_away_branch == "nobody_home"
    assert w.coord.get_away_entries_today() == 1
    assert len(w.db_rows) == 1 and w.db_rows[0]["state"] == "away"


def test_last_away_branch_active(monkeypatch, clock):
    w, h = _d2_world(monkeypatch, clock, kill=False)
    w.with_db()
    h.tick()
    clock.advance(30)
    w.states["sensor.jaya_area"] = _State("unknown")
    h.tick()
    assert w.tick() == HS.AWAY
    assert w.coord._last_away_branch == "active"


@pytest.mark.parametrize("source", ["override_adapter", "boot_settle_override"])
def test_last_away_branch_override_and_boot_settle_override(monkeypatch, clock, source):
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              state=HS.HOME_DAY).with_db()
    w.coord._veto_path = "active"  # stale inference label must NOT leak
    w.coord._dispatch_house_state_change(HS.HOME_DAY, HS.AWAY, "override_set",
                                         1.0, source=source)
    assert w.coord._last_away_branch == "override"
    assert w.coord.get_away_entries_today() == 1
    assert len(w.db_rows) == 1


def test_no_restore_branch_value_emitted(monkeypatch, clock):
    """No 'restore' branch exists: the only values are the engine labels
    and 'override'; an away->away dispatch (no entry) records nothing."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              state=HS.HOME_DAY).with_db()
    w.coord._dispatch_house_state_change(HS.AWAY, HS.AWAY, "x", 1.0,
                                         source="override_adapter")
    assert w.coord._last_away_branch is None
    assert w.coord.get_away_entries_today() == 0
    assert "restore" not in PR.PresenceCoordinator._AWAY_BRANCH_FOR_SOURCE.values()


@pytest.mark.parametrize("gate", ["boot_settle", "observation_mode"])
def test_gated_dispatch_not_counted(monkeypatch, clock, gate):
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              state=HS.HOME_DAY).with_db()
    if gate == "boot_settle":
        w.coord._boot_settle_done = False
    else:
        w.coord.observation_mode = True
    w.coord._dispatch_house_state_change(HS.HOME_DAY, HS.AWAY, "t", 0.9)
    assert w.coord.get_away_entries_today() == 0
    assert w.coord._last_away_branch is None
    assert w.db_rows == []


def test_away_entries_today_getter_zero_after_local_midnight(monkeypatch, clock):
    """At 00:00:05 local with no transition since midnight the attribute
    reads 0 regardless of the periodic tick phase (R2 L2)."""
    tz = ZoneInfo("America/Chicago")
    monkeypatch.setattr(_DT, "DEFAULT_TIME_ZONE", tz)
    clock.t = datetime(2026, 10, 17, 23, 50, tzinfo=tz)
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              state=HS.HOME_DAY).with_db()
    w.coord._dispatch_house_state_change(HS.HOME_DAY, HS.AWAY, "t", 0.9)
    assert w.coord.get_away_entries_today() == 1
    clock.t = datetime(2026, 10, 18, 0, 0, 5, tzinfo=tz)
    assert w.coord.get_away_entries_today() == 0
    # The next entry today starts again at 1.
    w.coord._dispatch_house_state_change(HS.ARRIVING, HS.AWAY, "t", 0.9)
    assert w.coord.get_away_entries_today() == 1


def test_periodic_rolls_away_count_at_midnight(monkeypatch, clock):
    tz = ZoneInfo("America/Chicago")
    monkeypatch.setattr(_DT, "DEFAULT_TIME_ZONE", tz)
    clock.t = datetime(2026, 10, 17, 23, 50, tzinfo=tz)
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              state=HS.HOME_DAY)
    w.occupy("Master Suite", "Master Bedroom", kind="motion")  # no new AWAY
    w.coord._dispatch_house_state_change(HS.HOME_DAY, HS.AWAY, "t", 0.9)
    clock.t = datetime(2026, 10, 18, 0, 1, tzinfo=tz)
    _run(w.coord._periodic_inference())
    assert w.coord._away_entries_today == 0
    assert w.coord._away_count_date == "2026-10-18"


# --- hydration against a REAL database --------------------------------------

def _make_db(tmp_path):
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _sched
    hass.async_create_task = _sched
    hass.is_stopping = False
    return DB.UniversalRoomDatabase(hass)


async def _with_db(db, fn):
    await db.initialize()
    await db.start_write_worker()
    try:
        return await fn()
    finally:
        if db._write_task is not None and not db._write_task.done():
            db._write_task.cancel()
            try:
                await db._write_task
            except BaseException:  # noqa: BLE001
                pass


def _insert_rows(db, rows):
    conn = sqlite3.connect(db.db_file)
    conn.executemany(
        "INSERT INTO house_state_log (timestamp, state, confidence, trigger, "
        "previous_state) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# 2026-10-18 local (CDT, UTC-5): local midnight = 2026-10-18T05:00:00 UTC.
_HYDRATE_ROWS = [
    ("2026-10-18T04:59:59.999999", "away", 0.9, "t", "home_night"),  # yesterday local
    ("2026-10-18T05:00:00", "away", 0.9, "t", "sleep"),             # exactly B, no µs
    ("2026-10-18T09:00:00.100000", "away", 0.9, "t", "away"),       # away->away, excluded
    ("2026-10-18T12:00:00.100000", "away", 0.9, "t", None),         # NULL previous counts
    ("2026-10-18T13:00:00.100000", "home_day", 0.9, "t", "away"),   # not away
    ("2026-10-19T01:00:00.000000", "away", 0.9, "t", "home_day"),   # 20:00 CDT 10-18
    ("2026-10-18T19:00:00.100000", "home_evening", 0.9, "t", "home_day"),  # not away (Bug Class #63 discriminator)
]


def test_away_count_hydration_naive_utc_bound_includes_boundary_row(monkeypatch, clock, tmp_path):
    """A 20:00 CDT restart hydrates only rows from local midnight; the row
    stamped exactly at B with zero microseconds is included; away->away
    and the pre-midnight row are excluded. Oracle: 3 (rows 2, 4, 6); a
    dropped state filter would also count row 7 (home_evening)."""
    tz = ZoneInfo("America/Chicago")
    monkeypatch.setattr(_DT, "DEFAULT_TIME_ZONE", tz)
    clock.t = datetime(2026, 10, 18, 20, 0, tzinfo=tz)
    db = _make_db(tmp_path)
    coord = PR.PresenceCoordinator(MagicMock())

    async def _go():
        _insert_rows(db, _HYDRATE_ROWS)
        await coord._hydrate_away_entries_today(db)

    _run(_with_db(db, _go))
    assert coord._away_entries_today == 3
    assert coord.get_away_entries_today() == 3


def test_away_count_excludes_away_to_away_rows(monkeypatch, clock, tmp_path):
    db = _make_db(tmp_path)

    async def _go():
        _insert_rows(db, [
            ("2026-10-18T06:00:00.1", "away", 0.9, "t", "away"),
            ("2026-10-18T06:01:00.1", "away", 0.9, "t", "away"),
            ("2026-10-18T06:02:00.1", "away", 0.9, "t", "home_day"),
        ])
        return await db.count_house_state_changes_since(
            "2026-10-18T05:00:00", state="away", exclude_same_previous=True,
        )

    assert _run(_with_db(db, _go)) == 1


def test_count_since_default_sql_unchanged(monkeypatch, clock, tmp_path):
    """No kwargs -> every row since the bound, all states (the original
    _transitions_today semantics). Oracle: 6 of the 7 rows (>= bound)."""
    db = _make_db(tmp_path)

    async def _go():
        _insert_rows(db, _HYDRATE_ROWS)
        return await db.count_house_state_changes_since("2026-10-18T05:00:00")

    assert _run(_with_db(db, _go)) == 6


def test_setup_hydrates_away_entries_today(monkeypatch, clock):
    """Call-site anchor: async_setup calls the hydration with the naive
    UTC local-midnight bound and the away/entry kwargs."""
    tz = ZoneInfo("America/Chicago")
    monkeypatch.setattr(_DT, "DEFAULT_TIME_ZONE", tz)
    clock.t = datetime(2026, 10, 18, 20, 0, tzinfo=tz)
    calls = []

    class _DBFake:
        async def count_house_state_changes_since(self, since_iso, **kw):
            calls.append((since_iso, kw))
            return 7 if kw.get("state") == "away" else 2

    monkeypatch.setattr(PR, "async_track_time_interval",
                        lambda *a, **k: MagicMock())
    hass = MagicMock()
    hass.data = {DOMAIN: {"database": _DBFake()}}
    hass.config_entries.async_entries = lambda domain=None: []
    hass.async_create_task = _close
    hass.async_create_background_task = _close
    hass.is_running = True
    coord = PR.PresenceCoordinator(hass)
    asyncio.run(coord.async_setup())
    assert ("2026-10-18T05:00:00", {"state": "away",
                                    "exclude_same_previous": True}) in calls
    assert coord.get_away_entries_today() == 7


# --- guest_reason -------------------------------------------------------------

def _guest_world(monkeypatch, clock, *, room_fires, unid_fires, override=False):
    clock.t = DAY
    w = World(monkeypatch, zones={"Back Hallway": ["Guest Bedroom 1"]},
              entries=[_room_entry("Guest Bedroom 1", motion=[JAYA_PIR])],
              states={JAYA_PIR: _State("on")}, state=HS.HOME_DAY)
    w.occupy("Back Hallway", "Guest Bedroom 1", kind="motion")
    w.coord._guest_detection_enabled = True
    if room_fires:
        w.coord._guest_room_state = {"Guest Bedroom 1": {
            "first_seen": DAY - timedelta(minutes=45),
            "current_occupancy_known": False, "threshold_min": 30}}
        monkeypatch.setattr(w.coord, "_is_known_person_in_room", lambda r: False)
    if unid_fires:
        monkeypatch.setattr(w.coord, "_guest_gate_armed",
                            lambda **k: True)
    if override:
        w.sm.set_override(HS.GUEST)
    return w


def test_guest_reason_room_precedes_unidentified(monkeypatch, clock):
    w = _guest_world(monkeypatch, clock, room_fires=True, unid_fires=True)
    w.tick()
    assert w.coord._guest_reason == "guest_room:Guest Bedroom 1"


def test_guest_reason_unidentified_and_none(monkeypatch, clock):
    w = _guest_world(monkeypatch, clock, room_fires=False, unid_fires=True)
    w.tick()
    assert w.coord._guest_reason == "unidentified_corroborator_only"
    w2 = _guest_world(monkeypatch, clock, room_fires=False, unid_fires=False)
    w2.tick()
    assert w2.coord._guest_reason == "none"


def test_guest_reason_override(monkeypatch, clock):
    w = _guest_world(monkeypatch, clock, room_fires=False, unid_fires=False,
                     override=True)
    w.tick()
    assert w.coord._guest_reason == "override"


# --- sensor surface -------------------------------------------------------------

def _sensor_attrs(w):
    s = object.__new__(SE.PresenceHouseStateSensor)
    s.hass = w.hass
    return s.extra_state_attributes


def test_unrecorded_attributes_set(monkeypatch, clock):
    assert SE.PresenceHouseStateSensor._unrecorded_attributes == frozenset(
        {"stale_counted_home", "nobody_home_zone_input"}
    )
    # HA's recorder strips exactly the merged set (Entity base + class).
    s = object.__new__(SE.PresenceHouseStateSensor)
    merged = s._Entity__combined_unrecorded_attributes if hasattr(
        s, "_Entity__combined_unrecorded_attributes") else None
    if merged is not None:
        assert {"stale_counted_home", "nobody_home_zone_input"} <= set(merged)
    # The REAL HA Entity base (bound at alias import), not a sibling stub.
    assert any(
        c.__name__ == "Entity" and c.__module__ == "homeassistant.helpers.entity"
        for c in SE.PresenceHouseStateSensor.__mro__
    )


def test_sensor_publishes_d3_attributes(monkeypatch, clock):
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", motion=[JAYA_PIR])]).with_db()
    w.manager.house_state = w.sm.state
    assert w.tick() == HS.AWAY
    w.manager.house_state = w.sm.state
    a = _sensor_attrs(w)
    assert a["last_away_branch"] == "nobody_home"
    assert a["away_entries_today"] == 1
    assert a["guest_reason"] == "none"
    assert a["stale_counted_home"] == []
    assert a["nobody_home_zone_input"] is False
    assert a["last_away_at"] == T0.isoformat()


# ===========================================================================
# Wigton-shape fixture (plan §9.2) — no interior cameras, no BLE room
# trackers, 1 enrolled phone (omonele), ZX radars in occupancy_sensors,
# no URA fans; zones Back hallway / Entertainment Zone / Master Suite /
# Upstairs Zone + Gym in no zone. omonele's tracker pinned `unknown` -> LOST
# via the REAL PersonCoordinator (S0: α starved, β sleep-exempt, census 0).
# ===========================================================================

WIG_MASTER = "binary_sensor.wig_master_zx_occupancy"
WIG_UP = "binary_sensor.wig_upstairs_zx_occupancy"
WIG_MASTER_ZV = "binary_sensor.wig_master_zv_presence_2"


def _wigton(monkeypatch, clock, *, master_on=False, up_on=False,
            person_state="unknown"):
    states = {WIG_MASTER: _State("on" if master_on else "off"),
              WIG_UP: _State("on" if up_on else "off"),
              "person.omonele": _State(person_state)}
    entries = [
        _room_entry("Master Bedroom", occupancy=[WIG_MASTER]),
        _room_entry("Upstairs Bedroom", occupancy=[WIG_UP]),
        _room_entry("Gym"),
    ]
    w = World(monkeypatch, zones={
        "Back hallway": ["Back Hall"],
        "Entertainment Zone": ["Media Room"],
        "Master Suite": ["Master Bedroom"],
        "Upstairs Zone": ["Upstairs Bedroom"],
    }, entries=entries, states=states)
    if master_on:
        w.occupy("Master Suite", "Master Bedroom", kind="occupancy")
    if up_on:
        w.occupy("Upstairs Zone", "Upstairs Bedroom", kind="occupancy")
    h = _PersonHarness(w, ["omonele"], 300, bermuda=False)
    h.tick()
    return w, h


def test_wigton_shape_sleep_loop_suppressed(monkeypatch, clock):
    """S0, SLEEP, Master Suite ZX occupied -> no AWAY over 30 ticks,
    veto_path 'none'. Old code: AWAY via nobody_home."""
    w, h = _wigton(monkeypatch, clock, master_on=True)
    assert h.pc.data["omonele"]["tracking_status"] == LOST
    for _ in range(30):
        h.tick()
        assert w.tick() == HS.SLEEP
        assert w.coord._veto_path == "none"
        assert w.coord._tracked_persons_count_trusted == 0  # S0: α starved
        clock.advance(60)


def test_wigton_shape_empty_still_reaches_away(monkeypatch, clock):
    w, h = _wigton(monkeypatch, clock)
    assert w.tick() == HS.AWAY
    assert w.coord._veto_path == "nobody_home"


def test_wigton_shape_zx_room_with_fan_on_holds(monkeypatch, clock):
    """Rev 2.1: no breaker — a ZX-only room (occupancy_sensors) with a URA
    fan on still holds SLEEP (a real sleeper is never blanked)."""
    w, h = _wigton(monkeypatch, clock, up_on=True)
    w.fan_on("Upstairs Zone", "Upstairs Bedroom")
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"


def test_wigton_shape_sleep_ends_via_waking(monkeypatch, clock):
    """INV-SLEEP-HOLD-BOUNDED (b) on the Wigton shape: S0, ZX holding the
    Master Suite all night -> out of SLEEP after 06:00 (WAKING)."""
    w, h = _wigton(monkeypatch, clock, master_on=True)
    clock.t = datetime(2026, 10, 18, 5, 55, tzinfo=timezone.utc)
    states = []
    for _ in range(10):
        h.tick()
        states.append(w.tick())
        clock.advance(60)
    assert HS.WAKING in states or HS.HOME_DAY in states


def test_wigton_shape_tripwire_full_night_silent_then_fires_past_window(monkeypatch, clock):
    """Wigton S0 (census 0, ZX holding Master Suite): a full night held by
    raw occupancy fires NO NM; a SLEEP still held past window end + bound
    (discharge failed) fires exactly once."""
    fired = _capture_stuck(monkeypatch)
    w, h = _wigton(monkeypatch, clock, master_on=True)
    w.hass.async_create_task = _pending(w)
    _block_transitions(w)
    clock.t = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)
    _drive_hold(w, clock, 7 * 60)        # 23:00 .. 05:59
    assert fired == [] and w.sm.state == HS.SLEEP
    _drive_hold(w, clock, 90)            # 06:00 .. 07:29
    assert fired == []
    _drive_hold(w, clock, 5)             # past 07:30
    assert len(fired) == 1


def test_wigton_shape_multi_sensor_master_rollover_holds(monkeypatch, clock):
    """Review D-H1 on the Wigton shape: Master has a ZG-204ZV (motion) and a
    ZG-204ZX (presence). A sleeper's roll-over pulses the ZV on then off
    every few minutes all night; the ZX stays on. S0 (census 0, omonele
    LOST) -> SLEEP holds the whole night, no nobody-home AWAY."""
    w, h = _wigton(monkeypatch, clock)
    t = w.trackers["Master Suite"]
    t.register_entity(WIG_MASTER_ZV, "Master Bedroom")
    w.states[WIG_MASTER] = _State("on")
    w.states[WIG_MASTER_ZV] = _State("off")
    w.occupy("Master Suite", "Master Bedroom", kind="occupancy")
    clock.t = datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc)
    for _ in range(60):
        w.states[WIG_MASTER_ZV] = _State("on")
        w.occupy("Master Suite", "Master Bedroom", kind="motion")
        assert w.tick() == HS.SLEEP
        clock.advance(60)
        w.states[WIG_MASTER_ZV] = _State("off")
        t.update_room_occupancy("Master Bedroom", False, kind="motion")
        h.tick()
        assert w.tick() == HS.SLEEP, "roll-over flipped AWAY"
        assert w.coord._veto_path == "none"
        clock.advance(60)


@pytest.mark.per_entity_on_only
def test_wigton_shape_multi_sensor_master_ends_via_waking(monkeypatch, clock):
    """INV-SLEEP-HOLD-BOUNDED (b), Rev 3: the ZV off-edge clears only the
    motion kind, so the tracker keeps the room (defect line inverted); past
    06:00 the house leaves SLEEP via WAKING, and after HOME_DAY with the ZX
    still on and census 0 there is NO nobody-home AWAY (the daytime half
    the dad3bf6e7 NOTE left open)."""
    w, h = _wigton(monkeypatch, clock)
    t = w.trackers["Master Suite"]
    t.register_entity(WIG_MASTER_ZV, "Master Bedroom")
    w.states[WIG_MASTER] = _State("on")
    w.states[WIG_MASTER_ZV] = _State("off")
    t.update_room_occupancy("Master Bedroom", True, kind="occupancy")
    t.update_room_occupancy("Master Bedroom", True, kind="motion")
    t.update_room_occupancy("Master Bedroom", False, kind="motion")
    assert t.raw_occupied is True           # D4b: defect gone
    clock.t = datetime(2026, 10, 18, 5, 58, tzinfo=timezone.utc)
    states = []
    for _ in range(12):
        h.tick()
        states.append(w.tick())
        clock.advance(60)
    first_exit = next(s_ for s_ in states if s_ != HS.SLEEP)
    assert first_exit == HS.WAKING
    assert HS.HOME_DAY in states
    assert HS.AWAY not in states            # daytime half closed


@pytest.mark.per_entity_off_only
def test_wigton_shape_multi_sensor_master_ends_via_waking_switch_off(monkeypatch, clock):
    """INV-SLEEP-HOLD-BOUNDED (b) when the tracker view was WIPED by a ZV
    off-edge but the ZX still holds: past 06:00 the WAKING gate sees the
    same night signal and the house leaves SLEEP."""
    w, h = _wigton(monkeypatch, clock)
    t = w.trackers["Master Suite"]
    t.register_entity(WIG_MASTER_ZV, "Master Bedroom")
    w.states[WIG_MASTER] = _State("on")
    w.states[WIG_MASTER_ZV] = _State("off")
    t.update_room_occupancy("Master Bedroom", True, kind="motion")
    t.update_room_occupancy("Master Bedroom", False, kind="motion")
    assert t.raw_occupied is False          # tracker view lost the room
    clock.t = datetime(2026, 10, 18, 5, 58, tzinfo=timezone.utc)
    states = []
    for _ in range(8):
        h.tick()
        states.append(w.tick())
        clock.advance(60)
    # SLEEP is left via WAKING (not via a nobody-home AWAY from SLEEP).
    assert HS.WAKING in states
    first_exit = next(s for s in states if s != HS.SLEEP)
    assert first_exit == HS.WAKING
    # NOTE (carded ZONE-TRACKER-PER-SENSOR-WIPE-1, out of scope): once the
    # zones unpin, daytime nobody-home reads the same lossy tracker view and
    # may go AWAY with the ZX still on — the pre-existing daytime half of
    # review D-H1, deliberately not changed by this cycle.


def test_wigton_shape_no_bermuda_inert(monkeypatch, clock):
    """D2 on/off give identical results (STALE needs a Bermuda fix)."""
    def _trace(kill):
        monkeypatch.setattr(PR, "PRESENCE_STALE_RESIDENT_COUNTS_HOME", kill)
        clock.t = DAY
        out = []
        for ps in ("unknown", "not_home", "home"):
            w, h = _wigton(monkeypatch, clock, master_on=True, person_state=ps)
            w.sm._state = HS.HOME_DAY
            for t in w.trackers.values():
                t.set_sleep(False)
            for _ in range(3):
                h.tick()
                out.append((ps, h.pc.data["omonele"]["tracking_status"],
                            w.tick(), w.coord._veto_path,
                            tuple(w.coord._stale_counted_home)))
                clock.advance(60)
        return out

    on = _trace(True)
    off = _trace(False)
    assert on == off
    assert all(row[1] != STALE for row in on)


def test_wigton_shape_observability_without_cameras_or_ble(monkeypatch, clock):
    w, h = _wigton(monkeypatch, clock)
    w.with_db()
    assert w.tick() == HS.AWAY
    assert w.coord._last_away_branch == "nobody_home"
    assert w.coord.get_away_entries_today() == 1
    assert w.coord._guest_reason == "none"
    assert w.coord._stale_counted_home == []

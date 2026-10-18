"""Sleep-mask cycle Rev 3 / 3.1 / 3.2 — per-sensor zone occupancy (D4) and the
D1 simplification, behind ``const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED``.

Plan: docs/planning/PLANNING_house_state_sleep_mask_ble_memory_observability.md
§R3.2 (binding) > §R3.1 > §R3. Tier 3.

FALSIFIABLE INVARIANTS UNDER TEST
---------------------------------
E(r) = entities the substrate maps to room r; on(e) <=> state == "on"
(unavailable / unknown / missing = off); room_raw(r) <=> any e in E(r) on;
tracker_room(r) = ZonePresenceTracker._room_occupied[r].

INV-ZONE-ROOM-TRUTH (switch on, boot-settle released AND the release
    reconcile ran, no refresh in flight): after the substrate callback for
    any state change of any e in E(r), room_raw(r) => tracker_room(r); and,
    with no fan-interference hold, tracker_room(r) => room_raw(r).
INV-NO-STUCK-THROUGH-REMOVAL: an entity deleted from HA (callback payload
    None), a sensor removed from CONF (options-save refresh with the NEW
    map) and a room entry deleted (async_remove_entry -> "removed" refresh)
    each stop contributing within one callback / refresh. Exceptions: a
    disabled room (non-goal) and a rename (ZONE-ROOM-NAME-DRIFT-1).
INV-NIGHT-RAW-EQUALS-RAW (switch on): _zone_night_raw(t) == t.raw_occupied
    for every tracker state (helper raising counts occupied).
INV-BYTE-ID-SINGLE: one sensor per (room, kind) -> identical dispatches /
    tracker states (no sibling read, pop semantics).
INV-KILL-BYTE-ID: switch False -> every dispatch, tracker state, inference
    result and NM identical to the reviewed branch dad3bf6e7.
INV-NO-EMPTY-HOUSE-HOLD-WHEN-ALPHA-LIVE: alpha reads no zone term; D4d pages
    the observable remainder (Frigate dark, every trusted tracker away,
    census 0, no BLE, a Tier-1 holder) once per episode past 7200 s.

All tests drive PRODUCTION code (real OccupancySubstrate, real
PresenceCoordinator / ZonePresenceTracker, real async_remove_entry over a
real HA config-entries manager). Harness reused from
test_house_state_sleep_mask_ble_memory.py (World / SubstrateWorld).
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import test_house_state_sleep_mask_ble_memory as SM
from test_house_state_sleep_mask_ble_memory import clock  # noqa: F401 — fixture

PR, CONST, HS, ZPM = SM.PR, SM.CONST, SM.HS, SM.ZPM
_State, _Entry, _room_entry = SM._State, SM._Entry, SM._room_entry
World, SubstrateWorld, _run = SM.World, SM.SubstrateWorld, SM._run
SUB = importlib.import_module(f"{SM._PKG}.domain_coordinators.occupancy_substrate")
SWITCH = "ZONE_OCCUPANCY_PER_ENTITY_ENABLED"

ON = pytest.mark.per_entity_on_only
OFF = pytest.mark.per_entity_off_only

ZX = "binary_sensor.master_zx_presence"
ZK = "binary_sensor.master_zk_presence"
ZV = "binary_sensor.master_zv_presence_2"
PIR = "binary_sensor.master_pir_motion"
DAY = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


def _master(monkeypatch, *, presence=(ZX, ZK), motion=(ZV,), on=(), state=HS.SLEEP,
            release=True, **kw):
    states = {e: _State("on" if e in on else "off")
              for e in (*presence, *motion)}
    w = SubstrateWorld(
        monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
        entries=[_room_entry("Master Bedroom", presence=list(presence),
                             motion=list(motion))],
        states=states, state=state, **kw)
    if release:
        w.release()
    return w


def _prov(w, room="Master Bedroom", zone="Master Suite"):
    return dict(w.trackers[zone]._room_provenance.get(room, {}))


# ===========================================================================
# D4a — substrate per-kind OR (`_kind_on_now`)
# ===========================================================================

@ON
def test_substrate_same_kind_sibling_off_keeps_kind_on(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX, ZK))
    n = len(w.edges)
    w.fire(ZK, "off")
    assert len(w.edges) == n                       # no dispatch
    assert w.sub.get_room_kinds("Master Bedroom")["mmwave"] is True
    assert w.trackers["Master Suite"].raw_occupied is True


@ON
def test_substrate_same_kind_last_off_dispatches_false(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX, ZK))
    w.fire(ZK, "off")
    w.fire(ZX, "off")
    assert w.edges[-1] == ("Master Bedroom", "mmwave", False)
    assert [e for e in w.edges if e[2] is False] == [
        ("Master Bedroom", "mmwave", False)]
    assert w.trackers["Master Suite"].raw_occupied is False


@ON
def test_substrate_unavailable_sibling_does_not_clear_kind(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX, ZK))
    n = len(w.edges)
    w.fire(ZK, "unavailable")
    w.fire(ZK, "unknown")
    assert len(w.edges) == n
    assert w.sub.get_room_kinds("Master Bedroom")["mmwave"] is True


def _single_entity_script(monkeypatch, switch):
    monkeypatch.setattr(CONST, SWITCH, switch)
    w = _master(monkeypatch, presence=(ZX,), motion=(PIR,), on=())
    for ent, st in [(ZX, "on"), (ZX, "on"), (PIR, "on"), (ZX, "unavailable"),
                    (ZX, "on"), (PIR, "unknown"), (ZX, "off"), (PIR, "on"),
                    (PIR, "off"), (ZX, "on"), (ZX, "off")]:
        w.fire(ent, st)
    return list(w.edges), _prov(w), w.sub.get_room_kinds("Master Bedroom")


def test_substrate_single_entity_dispatch_sequence_identical(monkeypatch, clock):
    """INV-BYTE-ID-SINGLE oracle (R2-9): the same script, one entity per
    (room, kind), run with the switch ON and OFF in one test — identical
    dispatches, tracker provenance and substrate kinds."""
    on = _single_entity_script(monkeypatch, True)
    off = _single_entity_script(monkeypatch, False)
    assert on == off
    assert on[1] == {}                       # last event cleared -> {} shape


@ON
def test_seed_and_live_share_kind_on_now(monkeypatch, clock):
    """The seed (async_setup) and the live handler apply ONE rule. Seed with
    ZX unavailable, ZK on, ZV unknown, PIR off; then drive the live path to
    the same states and compare both with `_kind_on_now` over the map."""
    states = {ZX: _State("unavailable"), ZK: _State("on"),
              ZV: _State("unknown"), PIR: _State("off")}
    w = SubstrateWorld(
        monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
        entries=[_room_entry("Master Bedroom", presence=[ZX, ZK],
                             motion=[ZV, PIR])],
        states=states).release()
    emap = w.sub._entity_to_room_kind
    seeded = w.sub.get_room_kinds("Master Bedroom")
    assert seeded == {"motion": False, "mmwave": True, "occupancy": False}
    assert seeded == {k: w.sub._kind_on_now("Master Bedroom", k, emap)
                      for k in CONST.TIER1_KINDS}
    w.fire(ZX, "on")
    w.fire(ZK, "off")
    w.fire(PIR, "on")
    live = w.sub.get_room_kinds("Master Bedroom")
    assert live == {"motion": True, "mmwave": True, "occupancy": False}
    assert live == {k: w.sub._kind_on_now("Master Bedroom", k, emap)
                    for k in CONST.TIER1_KINDS}


@OFF
def test_kill_constant_false_restores_last_writer(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX, ZK))
    w.fire(ZK, "off")
    assert w.edges[-1] == ("Master Bedroom", "mmwave", False)   # last-writer
    assert w.sub.get_room_kinds("Master Bedroom")["mmwave"] is False


@ON
def test_callback_before_state_store_uses_payload(monkeypatch, clock):
    """The event entity's state comes from the PAYLOAD: a fake that fires
    before updating its store still turns the kind on."""
    w = _master(monkeypatch, presence=(ZX,), motion=(), on=())
    event = types.SimpleNamespace(data={
        "entity_id": ZX, "old_state": _State("off"), "new_state": _State("on")})
    assert w.states[ZX].state == "off"           # store not yet updated
    w.callbacks[-1](event)
    assert w.edges[-1] == ("Master Bedroom", "mmwave", True)


# ===========================================================================
# D4b — tracker: an off-edge clears only its kind
# ===========================================================================

def _tracker():
    return PR.ZonePresenceTracker(MagicMock(), "Master Suite", ["Master Bedroom"])


@ON
def test_tracker_kind_off_clears_only_that_kind(monkeypatch, clock):
    t = _tracker()
    t.update_room_occupancy("Master Bedroom", True, kind="mmwave")
    t.update_room_occupancy("Master Bedroom", True, kind="motion")
    t.update_room_occupancy("Master Bedroom", False, kind="motion")
    assert t._room_occupied["Master Bedroom"] is True
    assert t.provenance_for("Master Bedroom") == {
        "motion": False, "mmwave": True, "occupancy": False}


def test_tracker_kind_none_false_still_full_clears(monkeypatch, clock):
    t = _tracker()
    t.update_room_occupancy("Master Bedroom", True, kind="mmwave")
    t.update_room_occupancy("Master Bedroom", True, kind=None)   # tier1 sentinel
    t.update_room_occupancy("Master Bedroom", False)             # legacy
    assert t._room_provenance["Master Bedroom"] == {}
    assert t._room_occupied["Master Bedroom"] is False


@ON
def test_tier1_sentinel_survives_kind_specific_false(monkeypatch, clock):
    t = _tracker()
    t.update_room_occupancy("Master Bedroom", True, kind=None)
    t.update_room_occupancy("Master Bedroom", False, kind="motion")
    assert t._room_occupied["Master Bedroom"] is True
    t.update_room_occupancy("Master Bedroom", False)             # kind=None clears
    assert t._room_occupied["Master Bedroom"] is False


@ON
def test_last_kind_popped_only_when_room_empty(monkeypatch, clock):
    t = _tracker()
    t.update_room_occupancy("Master Bedroom", True, kind="mmwave")
    t.update_room_occupancy("Master Bedroom", True, kind="motion")
    t.update_room_occupancy("Master Bedroom", False, kind="mmwave")
    # the room is still occupied (motion), so the diagnostic is kept
    assert t._last_kind_per_room.get("Master Bedroom") == "motion"
    t.update_room_occupancy("Master Bedroom", False, kind="motion")
    assert "Master Bedroom" not in t._last_kind_per_room


@OFF
def test_tracker_kill_constant_false_full_clear(monkeypatch, clock):
    t = _tracker()
    t.update_room_occupancy("Master Bedroom", True, kind="mmwave")
    t.update_room_occupancy("Master Bedroom", True, kind="motion")
    t.update_room_occupancy("Master Bedroom", False, kind="motion")
    assert t._room_provenance["Master Bedroom"] == {}
    assert t._room_occupied["Master Bedroom"] is False


def test_single_sensor_provenance_shape_identical(monkeypatch, clock):
    """R2-7: a single-sensor room's off-edge leaves `{}` in BOTH states."""
    t = _tracker()
    t.update_room_occupancy("Master Bedroom", True, kind="mmwave")
    t.update_room_occupancy("Master Bedroom", False, kind="mmwave")
    assert t._room_provenance["Master Bedroom"] == {}
    assert t.to_dict()["rooms_provenance"] == {"Master Bedroom": {}}


# ===========================================================================
# D4c — discharges
# ===========================================================================

@ON
def test_deleted_entity_while_on_releases_room(monkeypatch, clock):
    w = _master(monkeypatch, presence=(ZX,), motion=(), on=(ZX,))
    assert w.trackers["Master Suite"].raw_occupied is True
    w.fire(ZX, None)                                  # removed from HA
    assert w.edges[-1] == ("Master Bedroom", "mmwave", False)
    assert w.trackers["Master Suite"].raw_occupied is False


@ON
def test_removed_room_true_kinds_get_false_edges(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX, ZV))
    w.entries[:] = []                                 # room entry deleted
    w.refresh()
    falses = sorted(e for e in w.edges if e[2] is False)
    assert falses == [("Master Bedroom", "mmwave", False),
                      ("Master Bedroom", "motion", False)]
    assert w.trackers["Master Suite"].raw_occupied is False


@ON
def test_options_save_removing_on_sensor_releases_room(monkeypatch, clock):
    w = _master(monkeypatch, presence=(ZX,), motion=(PIR,), on=(ZX,))
    w.entries[0].options = {CONST.CONF_MMWAVE_SENSORS: []}      # remove the ZX
    w.refresh()
    assert ("Master Bedroom", "mmwave", False) in w.edges
    assert w.sub.get_room_kinds("Master Bedroom")["mmwave"] is False
    assert w.trackers["Master Suite"].raw_occupied is False


@ON
def test_options_save_adding_on_sensor_sets_kind(monkeypatch, clock):
    w = _master(monkeypatch, presence=(ZX,), motion=(), on=())
    w.states[ZK] = _State("on")
    w.entries[0].options = {CONST.CONF_MMWAVE_SENSORS: [ZX, ZK]}
    w.refresh()
    assert ("Master Bedroom", "mmwave", True) in w.edges
    assert w.trackers["Master Suite"].raw_occupied is True


@ON
def test_boot_settle_replay_unchanged(monkeypatch, clock):
    """Release replays the same True slots as before AND the trackers equal
    the substrate per kind afterwards (no longer pins the defect)."""
    w = _master(monkeypatch, on=(ZX,), release=False)
    w.coord._boot_settle_done = False
    w.coord._release_boot_settle("test")
    assert w.edges == [("Master Bedroom", "mmwave", True)]
    t = w.trackers["Master Suite"]
    assert {k: bool(_prov(w).get(k)) for k in CONST.TIER1_KINDS} == \
        w.sub.get_room_kinds("Master Bedroom")


@ON
def test_release_clears_kind_that_went_off_during_settle(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX,), release=False)
    assert w.trackers["Master Suite"].raw_occupied is True     # seeded True
    w.fire(ZX, "off")                                          # during settle
    assert w.edges == []                                       # suppressed
    assert w.trackers["Master Suite"].raw_occupied is True     # stale
    w.coord._boot_settle_done = False
    w.coord._release_boot_settle("test")
    assert w.trackers["Master Suite"].raw_occupied is False


@ON
def test_release_reconcile_removed_room_during_settle(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX,), release=False)
    assert w.trackers["Master Suite"].raw_occupied is True
    w.entries[:] = []
    w.refresh()                                                # pre-settle
    assert w.edges == []
    w.coord._boot_settle_done = False
    w.coord._release_boot_settle("test")
    assert w.trackers["Master Suite"].raw_occupied is False


@ON
def test_release_reconcile_writes_only_differing_slots(monkeypatch, clock):
    """L1: only differing slots are written; a tracker room the substrate
    never walked (sensor-less zone) gets NO write and stays UNKNOWN."""
    w = _master(monkeypatch, on=(ZX,), release=False)
    ghost = PR.ZonePresenceTracker(w.hass, "Ghost Zone", ["Renamed Room"])
    w.coord._zone_trackers["Ghost Zone"] = ghost
    assert ghost.mode == ZPM.UNKNOWN
    calls = []
    real = PR.ZonePresenceTracker.update_room_occupancy

    def _spy(self, room, occupied, kind=None):
        calls.append((self.zone_name, room, occupied, kind))
        return real(self, room, occupied, kind=kind)

    monkeypatch.setattr(PR.ZonePresenceTracker, "update_room_occupancy", _spy)
    w.fire(ZX, "off")
    calls.clear()
    w.coord._boot_settle_done = False
    w.coord._release_boot_settle("test")
    assert calls == [("Master Suite", "Master Bedroom", False, "mmwave")]
    assert ghost.mode == ZPM.UNKNOWN


@ON
def test_release_reconcile_exception_does_not_abort_tick(monkeypatch, clock):
    w = _master(monkeypatch, on=(ZX,), release=False)
    w.coord._boot_settle_done = False
    w.coord._census_count = 1                  # real_input release in-tick

    def _boom():
        raise RuntimeError("reconcile exploded")

    monkeypatch.setattr(w.coord, "_reconcile_trackers_to_substrate", _boom)
    w.coord._nobody_home_zone_input = "sentinel"
    w.tick()                                   # must not raise
    assert w.coord._boot_settle_done is True
    assert w.coord._nobody_home_zone_input is not "sentinel"   # tick finished


@ON
def test_refresh_subscribe_failure_leaves_state_untouched(monkeypatch, clock):
    w = _master(monkeypatch, presence=(ZX,), motion=(PIR,), on=(ZX,))
    raw_before = {r: dict(b) for r, b in w.sub._raw_state.items()}
    map_before = dict(w.sub._entity_to_room_kind)
    prov_before = _prov(w)
    w.entries[0].options = {CONST.CONF_MMWAVE_SENSORS: []}
    w.fail_subscribe = 1
    w.refresh()
    assert w.sub._raw_state == raw_before
    assert w.sub._entity_to_room_kind == map_before
    assert _prov(w) == prov_before
    assert len(w.retries) == 1


@ON
def test_refresh_retry_after_failure_emits_edges(monkeypatch, clock):
    w = _master(monkeypatch, presence=(ZX,), motion=(PIR,), on=(ZX,))
    w.entries[0].options = {CONST.CONF_MMWAVE_SENSORS: []}
    w.fail_subscribe = 1
    w.refresh()
    assert w.trackers["Master Suite"].raw_occupied is True
    _run(w.retries[0](None))                   # the one retry succeeds
    assert ("Master Bedroom", "mmwave", False) in w.edges
    assert w.sub.get_room_kinds("Master Bedroom")["mmwave"] is False
    assert w.trackers["Master Suite"].raw_occupied is False


# --- R3.1.4: room deletion through a REAL HA config-entries manager ----------

_CLEAN_ENV = "URA_R3_REAL_HA_CLEAN_INTERPRETER"
_POISON_SKIPS: list = []


def _load_ura_init():
    """The REAL URA __init__.py under the cycle's alias package, imported
    against a fresh homeassistant namespace (suite-order hygiene; restored
    afterwards). Its async_remove_entry does its dispatcher import at CALL
    time, so it talks to the same HA as the real hass below."""
    name = f"{SM._PKG}._ura_init"
    if name in sys.modules:
        return sys.modules[name]
    saved = {k: v for k, v in sys.modules.items()
             if k.split(".")[0] in ("homeassistant", "aiosqlite")}
    for k in saved:
        del sys.modules[k]
    try:
        spec = importlib.util.spec_from_file_location(
            name, str(SM._URA_ROOT / "__init__.py"))
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = SM._PKG
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k in [k for k in sys.modules if k.split(".")[0] in ("homeassistant", "aiosqlite")]:
            del sys.modules[k]
        sys.modules.update(saved)


@ON
def test_room_delete_via_config_entries_async_remove_releases_kinds(request):
    """R3.1.4: ``hass.config_entries.async_remove`` on a REAL HA manager
    calls URA's real ``async_remove_entry`` AFTER the entry has left the
    manager; the "removed" lifecycle refresh then sends False edges for the
    deleted room's True kinds and the tracker releases it."""
    try:
        from pytest_homeassistant_custom_component.common import (  # noqa: PLC0415
            MockConfigEntry, MockModule, async_test_home_assistant, mock_integration,
        )
        from homeassistant.helpers.dispatcher import async_dispatcher_connect  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"phcc unavailable: {exc}")
    init = _load_ura_init()
    sig = importlib.import_module(f"{SM._PKG}.domain_coordinators.signals")

    async def _go():
        with contextlib.ExitStack():
            pass
        async with async_test_home_assistant() as hass:
            try:
                mock_integration(hass, MockModule(
                    CONST.DOMAIN, async_remove_entry=init.async_remove_entry))
                entry = MockConfigEntry(domain=CONST.DOMAIN, data={
                    CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM,
                    CONST.CONF_ROOM_NAME: "Master Bedroom",
                    "room_name": "Master Bedroom",
                    CONST.CONF_MMWAVE_SENSORS: [ZX],
                })
                entry.add_to_hass(hass)
                hass.states.async_set(ZX, "on")
                edges, callbacks = [], []
                orig_track = SUB.async_track_state_change_event
                orig_send = SUB.async_dispatcher_send
                tracker = PR.ZonePresenceTracker(hass, "Master Suite", ["Master Bedroom"])
                coord = PR.PresenceCoordinator(hass)
                coord._zone_trackers = {"Master Suite": tracker}

                def _track(_h, entities, cb):
                    callbacks.append(cb)
                    return lambda: None

                def _send(_h, _s, room, kind, value):
                    edges.append((room, kind, value))
                    tracker.update_room_occupancy(room, value, kind=kind)

                SUB.async_track_state_change_event = _track
                SUB.async_dispatcher_send = _send
                try:
                    sub = SUB.OccupancySubstrate(hass)
                    await sub.async_setup()
                    coord._substrate = sub
                    sub.release_boot_settle()
                    assert tracker.raw_occupied is True
                    unsub = async_dispatcher_connect(
                        hass, sig.SIGNAL_ROOM_ENTRY_LIFECYCLE,
                        coord._on_room_entry_lifecycle)
                    await hass.config_entries.async_remove(entry.entry_id)
                    await hass.async_block_till_done()
                    unsub()
                finally:
                    SUB.async_track_state_change_event = orig_track
                    SUB.async_dispatcher_send = orig_send
                assert ("Master Bedroom", "mmwave", False) in edges
                assert tracker.raw_occupied is False
            finally:
                await hass.async_block_till_done()
                await hass.async_stop(force=True)

    try:
        asyncio.run(_go())
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001 — poisoned in-process HA
        if os.environ.get(_CLEAN_ENV):
            raise
        _POISON_SKIPS.append(request.node.nodeid)
        pytest.skip(f"R3-REAL-HA-POISONED ({type(exc).__name__}: {exc}); "
                    "executed by test_zz_real_ha_clean_interpreter")


# ===========================================================================
# D4d — house held out of AWAY by room sensors alone
# ===========================================================================

def _d4d_world(monkeypatch, clock, *, person=None, state=HS.HOME_DAY,
               camera_dark=True, census=0):
    clock.t = DAY
    w = World(monkeypatch, zones={"Living": ["Living Room"]},
              entries=[_room_entry("Living Room", presence=[ZX])],
              states={ZX: _State("on")}, state=state,
              camera_dark=camera_dark, census=census)
    w.occupy("Living", "Living Room", kind="mmwave")
    w.persons(person or {"oji": {"location": "away", "tracking_status":
                                 CONST.TRACKING_STATUS_ACTIVE,
                                 "tracking_reason": "away_gps"}})
    w.hass.async_create_task = SM._pending(w)
    # The diagnosis reads `on` entities through the substrate's map.
    w.coord._substrate._entity_to_room_kind = {ZX: ("Living Room", "mmwave")}
    return w


@ON
def test_zone_hold_all_away_fires_once_past_bound(monkeypatch, clock):
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock)
    SM._drive_hold(w, clock, 121)        # 120 min of held ticks after the stamp
    assert fired == []
    SM._drive_hold(w, clock, 2)
    assert len(fired) == 1
    kind, key, diag = fired[0]
    assert kind == "zone_hold_all_away" and key == ("house",)
    assert "Living Room" in diag and ZX in diag
    assert SM._capture_stuck.kw[0].get("severity") == "HIGH"
    SM._drive_hold(w, clock, 30)
    assert len(fired) == 1
    assert w.sm.state == HS.HOME_DAY


@ON
def test_zone_hold_all_away_silent_with_stale_resident(monkeypatch, clock):
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock, person={
        "oji": {"location": "away", "tracking_status": CONST.TRACKING_STATUS_ACTIVE},
        "jaya": {"location": "Study A", "tracking_status": CONST.TRACKING_STATUS_STALE},
    })
    SM._drive_hold(w, clock, 200)
    assert fired == []


@ON
def test_zone_hold_all_away_silent_under_override(monkeypatch, clock):
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock)
    w.sm.set_override(HS.HOME_DAY)
    SM._drive_hold(w, clock, 200)
    assert fired == []


@ON
def test_zone_hold_all_away_silent_in_sleep(monkeypatch, clock):
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock, state=HS.SLEEP)
    w.sm.transition = lambda *a, **k: False
    clock.t = datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc)
    SM._drive_hold(w, clock, 200)
    assert [f for f in fired if f[0] == "zone_hold_all_away"] == []


@ON
def test_zone_hold_all_away_rearms_after_clear(monkeypatch, clock):
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock)
    SM._drive_hold(w, clock, 123)
    assert len(fired) == 1
    w.clear("Living", "Living Room")
    w.sm.transition = lambda *a, **k: False   # keep HOME_DAY while clear
    SM._drive_hold(w, clock, 1)
    w.states[ZX] = _State("on")
    w.occupy("Living", "Living Room", kind="mmwave")
    SM._drive_hold(w, clock, 123)
    assert len(fired) == 2


@ON
def test_zone_hold_all_away_bound_zero_disables(monkeypatch, clock):
    fired = SM._capture_stuck(monkeypatch)
    monkeypatch.setattr(CONST, "ZONE_HOLD_ALL_AWAY_NM_BOUND_S", 0)
    w = _d4d_world(monkeypatch, clock)
    SM._drive_hold(w, clock, 300)
    assert fired == []


@ON
def test_d4d_clock_resets_on_blip(monkeypatch, clock):
    """A single non-held tick (census blip) restarts the 7200 s clock."""
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock)
    SM._drive_hold(w, clock, 100)
    w.coord._census_count = 1
    SM._drive_hold(w, clock, 1)
    w.coord._census_count = 0
    SM._drive_hold(w, clock, 110)        # 110 min after the blip: < bound
    assert fired == []
    SM._drive_hold(w, clock, 13)
    assert len(fired) == 1


@ON
def test_d4d_silent_when_camera_fleet_live(monkeypatch, clock):
    """Coverage (R3.1.7): with Frigate healthy alpha discharges first (the
    house goes AWAY), so there is never a hold to page."""
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock, camera_dark=False)
    SM._drive_hold(w, clock, 200)
    assert w.sm.state == HS.AWAY
    assert fired == []


@ON
def test_wigton_shape_zone_hold_trip_wire_inert_when_alpha_starved(monkeypatch, clock):
    """Stated gap (WIGTON-STUCK-ZX-NO-PAGE-1): no trusted tracker -> inert."""
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock, person={
        "omonele": {"location": "unknown",
                    "tracking_status": CONST.TRACKING_STATUS_LOST}})
    SM._drive_hold(w, clock, 300)
    assert fired == []


@OFF
def test_d4d_silent_when_kill_switch_off(monkeypatch, clock):
    fired = SM._capture_stuck(monkeypatch)
    w = _d4d_world(monkeypatch, clock)
    SM._drive_hold(w, clock, 300)
    assert fired == []


# ===========================================================================
# Kill switch (R3.1.1, INV-KILL-BYTE-ID)
# ===========================================================================

@OFF
def test_kill_switch_off_dh1_repro_holds_sleep(monkeypatch, clock):
    """Switch off, D1 on: ZX holds, ZV pulses then clears through the REAL
    substrate -> the tracker is wiped (last-writer + full clear) and the
    D-H1 live limb still holds SLEEP."""
    w = _master(monkeypatch, presence=(ZX,), motion=(ZV,), on=(ZX,))
    w.fire(ZV, "on")
    w.fire(ZV, "off")
    assert w.trackers["Master Suite"].raw_occupied is False      # wiped
    assert w.tick() == HS.SLEEP
    assert w.coord._veto_path == "none"


@OFF
def test_kill_switch_off_matches_branch_trace(monkeypatch, clock):
    """Scripted sequence under the switch off == the dad3bf6e7 behaviour,
    hand-derived: last-writer per (room, kind) and full-room clears."""
    w = _master(monkeypatch, on=(ZX, ZK, ZV))
    t = w.trackers["Master Suite"]
    w.fire(ZK, "off")                       # last-writer: mmwave False
    assert w.edges[-1] == ("Master Bedroom", "mmwave", False)
    assert _prov(w) == {}                   # full-room clear (ZV still on!)
    w.fire(ZX, "unavailable")               # mmwave False -> False: no edge
    assert w.edges[-1] == ("Master Bedroom", "mmwave", False)
    w.fire(ZK, "on")
    assert w.edges[-1] == ("Master Bedroom", "mmwave", True)
    w.fire(ZX, None)                        # deleted: early return, no edge
    assert w.edges[-1] == ("Master Bedroom", "mmwave", True)
    assert t.raw_occupied is True
    assert w.tick() == HS.SLEEP


# ===========================================================================
# INV-NIGHT-RAW-EQUALS-RAW, R3-F1
# ===========================================================================

@ON
def test_night_raw_equals_raw_occupied_property(monkeypatch, clock):
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"]},
              entries=[_room_entry("Master Bedroom", presence=[ZX])],
              states={ZX: _State("on")})
    import itertools
    for ble, has_s, has_ble, room_on, cam, hold in itertools.product(
            (False, True), repeat=6):
        t = PR.ZonePresenceTracker(w.hass, "Z", ["Master Bedroom"])
        t._ble_occupied = ble
        t._has_sensors = has_s
        t._has_ble_sensors = has_ble
        if room_on:
            t._room_provenance["Master Bedroom"] = {"mmwave": True}
        else:
            t._room_provenance["Master Bedroom"] = {}
        if cam:
            t._camera_last_seen["camera.x"] = clock.t
        if hold:
            t._fan_interference_hold_until["Master Bedroom"] = (
                clock.t + timedelta(seconds=60))
        assert w.coord._zone_night_raw(t) == t.raw_occupied, (
            ble, has_s, has_ble, room_on, cam, hold)


@ON
def test_manual_occupied_zone_override_does_not_force_waking_gate(monkeypatch, clock):
    """R3-F1: SLEEP, one zone manually overridden OCCUPIED with raw clear,
    census 1, 06:01 -> the WAKING gate's raw input stays False, so no
    WAKING before the gate's sustained window (the forcing line is off)."""
    w = World(monkeypatch, zones={"Master Suite": ["Master Bedroom"],
                                  "Den": ["Den"]},
              entries=[_room_entry("Master Bedroom", presence=[ZX])],
              states={ZX: _State("off")}, census=1)
    w.trackers["Den"].set_override(ZPM.OCCUPIED)
    clock.t = datetime(2026, 10, 18, 6, 1, tzinfo=timezone.utc)
    states = []
    for _ in range(3):
        states.append(w.tick())
        clock.advance(60)
    assert HS.WAKING not in states
    assert w.coord._first_positive_zone_occupied_since is None


# ===========================================================================
# Lints (R3.2.2)
# ===========================================================================

_URA = SM._URA_ROOT


def test_zone_per_entity_switch_read_by_attribute():
    """The switch is read ONLY as `<const alias>.ZONE_OCCUPANCY_PER_ENTITY_
    ENABLED`, never imported by name, and only from the three modules the
    plan names; tests never patch it on those modules."""
    readers = set()
    for path in _URA.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        const_aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    assert a.name != SWITCH, f"name import of the switch in {path}"
                    if a.name == "const":
                        const_aliases.add(a.asname or "const")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == SWITCH:
                assert isinstance(node.value, ast.Name), path
                assert node.value.id in const_aliases, (path, node.value.id)
                readers.add(path.name)
            if (isinstance(node, ast.Name) and node.id == SWITCH
                    and isinstance(node.ctx, ast.Load)):
                pytest.fail(f"bare-name read of the switch in {path}")
    assert readers == {"presence.py", "occupancy_substrate.py", "__init__.py"}
    tests = Path(__file__).resolve().parent
    bad = []
    for path in tests.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        for mod in ("PR", "SUB", "presence", "occupancy_substrate", "INIT", "init"):
            if f'setattr({mod}, "{SWITCH}"' in src:
                bad.append(path.name)
    assert bad == []


def test_switch_off_markers_partition():
    """Every test in the touched files carries at most one switch marker, and
    the off-only anchor set is non-empty."""
    files = [Path(__file__), Path(SM.__file__)]
    off_only = 0
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                marks = set()
                for d in node.decorator_list:
                    txt = ast.unparse(d)
                    if "per_entity_on_only" in txt or txt == "ON":
                        marks.add("on")
                    if "per_entity_off_only" in txt or txt == "OFF":
                        marks.add("off")
                assert len(marks) <= 1, (path.name, node.name)
                off_only += "off" in marks
    assert off_only > 0


def test_zz_real_ha_clean_interpreter():
    """Runs LAST: if the real-HA deletion test was skipped because the
    in-process HA was poisoned by an earlier module, re-run it in a clean
    interpreter and require a pass."""
    if os.environ.get(_CLEAN_ENV) or not _POISON_SKIPS:
        return
    import subprocess  # noqa: PLC0415
    repo = SM._URA_ROOT.parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env[_CLEAN_ENV] = "1"
    env["PYTHONPATH"] = str(repo / "quality")
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"{os.path.abspath(__file__)}::test_room_delete_via_config_entries_async_remove_releases_kinds",
         "-q", "-p", "no:cacheprovider"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]

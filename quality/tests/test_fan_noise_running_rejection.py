"""Fan-noise running rejection — PLANNING_fan_noise_running_rejection.md Rev 2.

C1a  VACATED recheck leaves the fan off through the HVAC discharge path;
     a live manual-ON hold wins.
C2   fan-immune witness by capability + device-model radar safety net
     (D2 ``_d2_motion_sensors_present`` and ``fan_veto._has_recent_motion``).
C3   Part A last-known-good fan belief across unavailable edges;
     Part B ActuatorReconciler flap quarantine vetoes the recheck arm.
C4   per-family recheck window, cooldown 900, rehydrate fixes.

Every test drives PRODUCTION code (real FanController, real
FanRecheckManager, real ``_handle_fan_change`` / ``_d2_motion_sensors_present``
/ ``should_veto_comfort_fan`` / ``resolve_sensor_family``). Oracles are
hand-derived literals. The modules load under a private ``ura_`` alias
package (restored by conftest SUITE-HYGIENE-1); every other sys.modules /
attribute patch goes through ``monkeypatch`` and is undone per test.
"""

from __future__ import annotations

import asyncio
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
_PKG = "ura_fan_noise_rev2_pkg"


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
        "domain_coordinators.presence", "coordinator",
    )
    return [importlib.import_module(f"{_PKG}.{n}") for n in names]


CONST, FV, SC, HF, FR, PR, CO = _load()
DOMAIN = CONST.DOMAIN


_decay_timers: list = []


@pytest.fixture(autouse=True)
def _aware_clock(monkeypatch):
    """Sibling test files leave `dt_util.now` patched (naive / frozen).
    Production's clock is tz-aware wall time — pin that for each test,
    scoped by monkeypatch (restored afterwards)."""
    _decay_timers.clear()

    def _later(hass, secs, cb):
        rec = {"secs": secs, "cb": cb, "cancelled": False}
        _decay_timers.append(rec)

        def _unsub():
            rec["cancelled"] = True
        return _unsub

    monkeypatch.setattr(PR, "async_call_later", _later)
    for mod in {id(FR.dt_util): FR.dt_util, id(HF.dt_util): HF.dt_util}.values():
        monkeypatch.setattr(mod, "now", lambda: datetime.now(timezone.utc))
        monkeypatch.setattr(mod, "utcnow", lambda: datetime.now(timezone.utc))
    yield


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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


# ---------------------------------------------------------------------------
# Device / entity registry fakes (drive the REAL resolve_sensor_family)
# ---------------------------------------------------------------------------

def _install_registry(monkeypatch, models: dict):
    """models: entity_id -> (model_id, model). Scoped via monkeypatch."""
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


# ===========================================================================
# C1a — FanController.restore_after_recheck(leave_off=...)
# ===========================================================================

def _fan_world(fan_on=True, room="Study A", fan="fan.study_a"):
    """Real FanController with one HVAC-owned ("Follow thermostat") room."""
    hass = MagicMock()
    hass.data = {}
    states = {fan: _State("on" if fan_on else "off", {"percentage": 66})}
    entries = [_Entry(f"entry_{room}", {
        "entry_type": "room", "room_name": room, "fans": [fan],
        "room_type": "generic",
    }, {CONST.CONF_ROOM_FAN_MODE: CONST.FAN_MODE_FOLLOW_THERMOSTAT})]
    hass.states.get = lambda eid: states.get(eid)
    hass.config_entries.async_entries = lambda domain=None: list(entries)
    log: list = []

    async def _svc(domain, service, data=None, blocking=False, **kw):
        log.append((domain, service, dict(data or {})))

    hass.services.async_call = _svc
    hass.async_create_task = lambda c: c.close() if hasattr(c, "close") else None
    zone = MagicMock()
    zone.rooms = [room]
    zone.target_temp_high = 74.0
    rc = MagicMock()
    rc.room_name = room
    rc.temperature = 70.0     # below threshold: temp path wants nothing
    rc.occupied = False
    zone.room_conditions = [rc]
    zm = MagicMock()
    zm.zones = {"z1": zone}
    fc = HF.FanController(hass=hass, zone_manager=zm)
    fc.discover_fans()
    rf = fc._room_fans[room]
    rf.is_on, rf.speed_pct, rf.trigger = True, 66, "temperature"
    rf.last_on_time = "2026-10-11T10:00:00+00:00"
    return fc, hass, states, log, rf


def _on_writes(log, fan="fan.study_a"):
    return [
        (d, s) for (d, s, data) in log
        if data.get("entity_id") == fan and s == "turn_on"
    ]


def test_vacated_takes_leave_off_discharge_branch():
    """C1a anchor: leave_off=True clears is_on/speed/trigger/last_on_time
    and the suppress-until, and issues NO ON write."""
    fc, _h, states, log, rf = _fan_world()
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    states["fan.study_a"] = _State("off", {"percentage": 0})
    assert rf.fan_recheck_suppress_until
    n = len(log)
    _run(fc.restore_after_recheck("Study A", snap, leave_off=True))
    assert _on_writes(log[n:]) == []
    assert rf.is_on is False
    assert rf.speed_pct == 0
    assert rf.trigger == ""
    assert rf.last_on_time == ""
    assert rf.fan_recheck_suppress_until == ""


def test_occupied_confirmed_restore_still_turns_fan_on():
    """Control: the normal restore (leave_off False) re-issues the ON."""
    fc, _h, states, log, rf = _fan_world()
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    states["fan.study_a"] = _State("off", {"percentage": 0})
    n = len(log)
    _run(fc.restore_after_recheck("Study A", snap))
    assert _on_writes(log[n:]) == [("fan", "turn_on")]
    assert rf.is_on is True


def test_vacated_does_not_open_manual_off_cooldown():
    """Finding 1: after a leave-off restore, the next update() with the
    entity live-OFF must NOT take the 'turned off externally' branch."""
    fc, _h, states, _log, rf = _fan_world()
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    states["fan.study_a"] = _State("off", {"percentage": 0})
    _run(fc.restore_after_recheck("Study A", snap, leave_off=True))
    _run(fc.update(None, "home_day"))
    assert rf.manual_off_cooldown_until == ""
    assert rf.is_on is False


def test_without_leave_off_discharge_update_opens_cooldown():
    """Discriminator for the test above: had the restore been SKIPPED
    (Rev 1), is_on stays True and update() books a fake manual-OFF."""
    fc, _h, states, _log, rf = _fan_world()
    _run(fc.pause_for_recheck("Study A", "2000-01-01T00:00:00+00:00"))
    states["fan.study_a"] = _State("off", {"percentage": 0})
    _run(fc.update(None, "home_day"))
    assert rf.manual_off_cooldown_until != ""


def test_manual_on_hold_lands_during_pause_forces_restore():
    """Finding 2: a manual-ON hold that lands DURING the pause wins over
    a VACATED leave-off — the fan is restored ON and the hold end is not
    extended."""
    fc, _h, states, log, rf = _fan_world()
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    assert rf.manual_on_hold_paused_at == ""          # no hold at pause
    states["fan.study_a"] = _State("off", {"percentage": 0})
    hold_until = (HF.dt_util.now() + timedelta(minutes=30)).isoformat()
    rf.manual_on_hold_until = hold_until
    n = len(log)
    _run(fc.restore_after_recheck("Study A", snap, leave_off=True))
    assert _on_writes(log[n:]) == [("fan", "turn_on")]
    assert rf.is_on is True
    assert rf.manual_on_hold_until == hold_until


def test_vacated_discharges_suppress_until_and_hold_paused_at():
    """Finding 2 backstop: hold live AT pause (paused_at stamped). A
    leave-off restore clears paused_at WITHOUT extending the hold end,
    restores ON (operator intent), and clears the suppress-until."""
    fc, _h, states, log, rf = _fan_world()
    hold_until = (HF.dt_util.now() + timedelta(minutes=30)).isoformat()
    rf.manual_on_hold_until = hold_until
    snap = _run(fc.pause_for_recheck("Study A", "2099-01-01T00:00:00+00:00"))
    assert rf.manual_on_hold_paused_at != ""
    rf.manual_on_hold_paused_at = (
        HF.dt_util.now() - timedelta(minutes=10)
    ).isoformat()                                     # 10 min paused
    states["fan.study_a"] = _State("off", {"percentage": 0})
    _run(fc.restore_after_recheck("Study A", snap, leave_off=True))
    assert rf.manual_on_hold_paused_at == ""
    assert rf.manual_on_hold_until == hold_until      # NOT +10 min
    assert rf.fan_recheck_suppress_until == ""
    assert _on_writes(log) == [("fan", "turn_on")]


# ---------------------------------------------------------------------------
# C1a / C3 Part B / C4 — FanRecheckManager over a real FanController
# ---------------------------------------------------------------------------

class _RoomCoord:
    def __init__(self, entry, data=None, sources=None, reconciler=None):
        self.entry = entry
        self.data = data or {
            "occupied": True, "occupancy_source": "mmwave",
            "presence_detected": True, "motion_detected": False,
        }
        self._sources = sources or ["mmwave", "mmwave", "mmwave"]
        self._actuator_reconciler = reconciler
        self.released = 0

    def recent_occupancy_sources(self):
        return list(self._sources)

    def apply_fan_recheck_release(self):
        self.released += 1

    def async_set_updated_data(self, data):
        pass


class _PersonCoord:
    def get_ble_tier(self, room):
        return 0

    def get_persons_in_room(self, room):
        return []


def _recheck_world(monkeypatch, *, room="Study A", room_type="generic",
                   presence_sensors=(), cm_options=None, fan_on=True,
                   reconciler=None, models=None):
    fc, hass, states, log, rf = _fan_world(fan_on=fan_on, room=room)
    entry = hass.config_entries.async_entries()[0]
    entry.data.update({
        "room_type": room_type,
        CONST.CONF_MMWAVE_SENSORS: list(presence_sensors),
        CONST.CONF_ROOM_FAN_RECHECK_ENABLED: True,
        CONST.CONF_FAN_RECHECK_TRUST_SENSORS_OK: True,
    })
    cm = _Entry("cm", {"entry_type": CONST.ENTRY_TYPE_COORDINATOR_MANAGER},
                cm_options or {})
    all_entries = [entry, cm]
    hass.config_entries.async_entries = lambda domain=None: list(all_entries)
    rc = _RoomCoord(entry, reconciler=reconciler)
    cmgr = MagicMock()
    hvac = MagicMock()
    hvac.fan_controller = fc
    cmgr.coordinators = {"hvac": hvac}
    hass.data = {DOMAIN: {
        "coordinator_manager": cmgr,
        entry.entry_id: rc,
        "person_coordinator": _PersonCoord(),
        "fan_recheck_master_enabled": True,
    }}
    tasks: list = []
    hass.async_create_task = lambda c: tasks.append(c)
    timers: list = []
    monkeypatch.setattr(
        FR, "async_call_later",
        lambda h, secs, cb: (timers.append((secs, cb)), (lambda: None))[1],
    )
    monkeypatch.setattr(FR, "async_dispatcher_send", lambda *a, **k: None)
    monkeypatch.setattr(
        FR, "trustworthy_persons_in_room", lambda *a, **k: [],
    )
    _install_registry(monkeypatch, models or {})
    presence = types.SimpleNamespace(
        house_state="home_day", _boot_settle_done=True,
        get_adjacent_rooms=lambda r: [], zone_trackers={},
    )
    mgr = FR.FanRecheckManager(hass, presence)
    mgr._setup_done = True
    return mgr, fc, hass, states, log, rf, rc, timers, tasks


def _drain(tasks):
    while tasks:
        c = tasks.pop(0)
        if asyncio.iscoroutine(c):
            _run(c)


def test_fan_recheck_restore_leave_off_on_vacated(monkeypatch):
    """C1a wire-in anchor through the enclosing ``_restore``: a VACATED
    verdict reaches the real FanController with leave_off — zero ON
    writes, is_on cleared, room released."""
    mgr, fc, hass, states, log, rf, rc, _t, tasks = _recheck_world(monkeypatch)
    ctx = FR._RoomCtx(room_name="Study A", entry_id=rc.entry.entry_id)
    mgr._rooms["Study A"] = ctx
    ctx.snapshot = _run(fc.pause_for_recheck(
        "Study A", "2099-01-01T00:00:00+00:00",
    ))
    states["fan.study_a"] = _State("off", {"percentage": 0})
    n = len(log)
    _run(mgr._restore(ctx, outcome=FR.OUTCOME_VACATED))
    _drain(tasks)
    assert _on_writes(log[n:]) == []
    assert rf.is_on is False
    assert rc.released == 1
    assert ctx.state == FR.STATE_COOLDOWN


def test_fan_recheck_occupied_confirmed_restores_on(monkeypatch):
    mgr, fc, hass, states, log, rf, rc, _t, tasks = _recheck_world(monkeypatch)
    ctx = FR._RoomCtx(room_name="Study A", entry_id=rc.entry.entry_id)
    mgr._rooms["Study A"] = ctx
    ctx.snapshot = _run(fc.pause_for_recheck(
        "Study A", "2099-01-01T00:00:00+00:00",
    ))
    states["fan.study_a"] = _State("off", {"percentage": 0})
    n = len(log)
    _run(mgr._restore(ctx, outcome=FR.OUTCOME_OCCUPIED_CONFIRMED))
    _drain(tasks)
    assert _on_writes(log[n:]) == [("fan", "turn_on")]
    assert rc.released == 0


def test_forced_vacated_restore_turns_fan_on(monkeypatch):
    """forced=True (operator force_restore) never takes leave_off."""
    mgr, fc, hass, states, log, rf, rc, _t, tasks = _recheck_world(monkeypatch)
    ctx = FR._RoomCtx(room_name="Study A", entry_id=rc.entry.entry_id)
    mgr._rooms["Study A"] = ctx
    ctx.snapshot = _run(fc.pause_for_recheck(
        "Study A", "2099-01-01T00:00:00+00:00",
    ))
    states["fan.study_a"] = _State("off", {"percentage": 0})
    n = len(log)
    _run(mgr._restore(ctx, outcome=FR.OUTCOME_VACATED, forced=True))
    _drain(tasks)
    assert _on_writes(log[n:]) == [("fan", "turn_on")]


def _eligible(mgr, rc):
    ctx = FR._RoomCtx(room_name="Study A", entry_id=rc.entry.entry_id)
    return mgr._is_eligible(ctx, rc)


def test_recheck_eligible_baseline(monkeypatch):
    """Control: the world below is eligible with no hold / no quarantine."""
    mgr, *_rest = _recheck_world(monkeypatch)
    rc = _rest[5]
    assert _eligible(mgr, rc) is True


def test_manual_on_hold_live_vetoes_recheck_arm(monkeypatch):
    mgr, fc, hass, states, log, rf, rc, _t, _k = _recheck_world(monkeypatch)
    # The reader's clock (FR.dt_util) — sibling test files patch dt_util.
    rf.manual_on_hold_until = (
        FR.dt_util.now() + timedelta(minutes=30)
    ).isoformat()
    assert _eligible(mgr, rc) is False
    assert mgr._veto_counts["Study A"]["manual_on_hold_live"] == 1


def test_expired_manual_on_hold_does_not_veto(monkeypatch):
    mgr, fc, hass, states, log, rf, rc, _t, _k = _recheck_world(monkeypatch)
    rf.manual_on_hold_until = (
        FR.dt_util.now() - timedelta(seconds=1)
    ).isoformat()
    assert _eligible(mgr, rc) is True


class _Reconciler:
    def __init__(self, flapping):
        self._flap = list(flapping)

    def flapping_entities(self):
        return [{"entity_id": e} for e in self._flap]


def test_recheck_does_not_arm_against_quarantined_fan(monkeypatch):
    mgr, *_r = _recheck_world(
        monkeypatch, reconciler=_Reconciler(["fan.study_a"]),
    )
    rc = _r[5]
    assert _eligible(mgr, rc) is False
    assert mgr._veto_counts["Study A"]["fan_quarantined"] == 1


def test_quarantine_of_other_entity_does_not_veto(monkeypatch):
    mgr, *_r = _recheck_world(
        monkeypatch, reconciler=_Reconciler(["fan.elsewhere"]),
    )
    assert _eligible(mgr, _r[5]) is True


# ---------------------------------------------------------------------------
# C4 — family factor, cooldown, rehydrate
# ---------------------------------------------------------------------------

_ZK = ("ZG-204ZK", "24Ghz human presence sensor")
_ZX = ("ZG-204ZX", "24Ghz millimeter wave and T&H sensor")
_LD = (None, "HLK-LD2410")
_ZV = ("ZG-204ZV", "Millimeter wave motion detection")


def _pause_seconds(monkeypatch, **kw):
    mgr, fc, hass, states, log, rf, rc, timers, _k = _recheck_world(
        monkeypatch, **kw,
    )
    ctx = FR._RoomCtx(room_name="Study A", entry_id=rc.entry.entry_id)
    mgr._rooms["Study A"] = ctx
    _run(mgr._enter_paused(ctx, rc))
    return timers[-1][0]


def test_family_factor_zk_scales_window(monkeypatch):
    # spindown 30 + window 60 x room 1.0 x ZK 2.0 = 150
    assert _pause_seconds(
        monkeypatch, presence_sensors=["binary_sensor.zk"],
        models={"binary_sensor.zk": _ZK},
    ) == 150


def test_family_factor_ld24xx_bedroom(monkeypatch):
    # spindown 30 + window 60 x bedroom 2.0 x LD24xx 3.0 = 390
    assert _pause_seconds(
        monkeypatch, room_type="bedroom",
        presence_sensors=["binary_sensor.ld"],
        models={"binary_sensor.ld": _LD},
    ) == 390


def test_family_factor_unknown_defaults_1_0(monkeypatch):
    assert _pause_seconds(
        monkeypatch, presence_sensors=["binary_sensor.esp"],
        models={"binary_sensor.esp": (None, "esp32-c3-devkitm-1")},
    ) == 90


def test_family_scaling_kill_switch_off(monkeypatch):
    assert _pause_seconds(
        monkeypatch, presence_sensors=["binary_sensor.zk"],
        models={"binary_sensor.zk": _ZK},
        cm_options={CONST.CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED: False},
    ) == 90


_GENERIC = (None, "Human_Presence_Sensor")   # Screek -> generic_radar 1.5
_ESP = (None, "esp32-c3-devkitm-1")         # unknown


def test_family_factor_is_max_over_recognised_families(monkeypatch):
    # LD24xx (x3) + ZK (x2), either order -> x3: 30 + 60 x 3 = 210.
    for order in (["binary_sensor.ld", "binary_sensor.zk"],
                  ["binary_sensor.zk", "binary_sensor.ld"]):
        assert _pause_seconds(
            monkeypatch, presence_sensors=order,
            models={"binary_sensor.ld": _LD, "binary_sensor.zk": _ZK},
        ) == 210


def test_family_factor_jaya_shape_unknown_ignored(monkeypatch):
    # [esp32 (unknown), ZK] -> ZK x2 (majority-with-unknown gave 1.0).
    assert _pause_seconds(
        monkeypatch, presence_sensors=["binary_sensor.esp", "binary_sensor.zk"],
        models={"binary_sensor.esp": _ESP, "binary_sensor.zk": _ZK},
    ) == 150


def test_family_factor_master_bedroom_shape_zx_beats_generic(monkeypatch):
    # [generic x1.5, generic x1.5, ZX x2] -> x2 (majority gave 1.5 = 120).
    assert _pause_seconds(
        monkeypatch,
        presence_sensors=["binary_sensor.g1", "binary_sensor.g2",
                          "binary_sensor.zx"],
        models={"binary_sensor.g1": _GENERIC, "binary_sensor.g2": _GENERIC,
                "binary_sensor.zx": _ZX},
    ) == 150


def test_cooldown_default_is_900(monkeypatch):
    assert CONST.DEFAULT_FAN_RECHECK_COOLDOWN_S == 900
    mgr, fc, hass, states, log, rf, rc, timers, _k = _recheck_world(monkeypatch)
    ctx = FR._RoomCtx(room_name="Study A", entry_id=rc.entry.entry_id)
    _run(mgr._enter_cooldown(ctx))
    assert timers[-1][0] == 900


def _rehydrate(monkeypatch, row_state, age_s, **kw):
    mgr, fc, hass, states, log, rf, rc, timers, tasks = _recheck_world(
        monkeypatch, **kw,
    )
    entered = (HF.dt_util.now() - timedelta(seconds=age_s)).isoformat()
    mgr._restore_row({
        "room_id": rc.entry.entry_id, "state": row_state,
        "state_entered_at": entered,
    })
    ctx = mgr._rooms["Study A"]
    return ctx, timers, tasks


@pytest.mark.parametrize("age_s,expect_resume", [
    (300, True), (479, True), (481, False),
])
def test_rehydrate_paused_respects_effective_window(
    monkeypatch, age_s, expect_resume,
):
    """ZK bedroom: window 60 x 2.0 x 2.0 = 240 -> stale threshold 480 s
    (the constant-based threshold was 120 s)."""
    ctx, _timers, tasks = _rehydrate(
        monkeypatch, FR.STATE_PAUSED, age_s, room_type="bedroom",
        presence_sensors=["binary_sensor.zk"],
        models={"binary_sensor.zk": _ZK},
    )
    resumed = len(tasks) == 1 and getattr(tasks[0], "cr_code", None) is not None \
        and tasks[0].cr_code.co_name == "_restore"
    for t in tasks:
        t.close()
    assert resumed is expect_resume


def test_cooldown_rehydrate_reads_live_knob(monkeypatch):
    """Live CM cooldown 1200, entered 1000 s ago -> 200 s remain. (With
    the default 900 the room would already be idle.)"""
    ctx, timers, _tasks = _rehydrate(
        monkeypatch, FR.STATE_COOLDOWN, 1000,
        cm_options={CONST.CONF_FAN_RECHECK_COOLDOWN_S: 1200},
    )
    assert ctx.state == FR.STATE_COOLDOWN
    assert timers and 199 <= timers[-1][0] <= 200


def test_cooldown_rehydrate_default_expired_goes_idle(monkeypatch):
    ctx, timers, _tasks = _rehydrate(monkeypatch, FR.STATE_COOLDOWN, 1000)
    assert ctx.state == FR.STATE_IDLE
    assert timers == []


# ===========================================================================
# C2 — fan-immune witness + model-id safety net
# ===========================================================================

_GAME_ZV = "binary_sensor.0xa4c1382e60e05225_presence"


def test_fan_immune_witness_zv_default_motion():
    cfg = {CONST.CONF_MOTION_SENSORS: [_GAME_ZV]}
    assert SC.is_fan_immune_witness(cfg, _GAME_ZV) is True


def test_fan_immune_witness_mmwave_declared():
    eid = "binary_sensor.radar"
    assert SC.is_fan_immune_witness(
        {CONST.CONF_MMWAVE_SENSORS: [eid]}, eid,
    ) is False
    assert SC.is_fan_immune_witness(
        {CONST.CONF_MOTION_SENSORS: [eid],
         CONST.CONF_SENSOR_CAPABILITIES: {eid: {"kind": "mmwave"}}}, eid,
    ) is False
    assert SC.is_fan_immune_witness(
        {CONST.CONF_MOTION_SENSORS: [eid],
         CONST.CONF_SENSOR_CAPABILITIES: {eid: {"kind": "pir"}}}, eid,
    ) is True
    assert SC.is_fan_immune_witness({}, eid) is False


@pytest.mark.parametrize("kind,immune", [
    ("motion", True), ("pir", True), ("pir_split", True), ("bed", True),
    ("camera_presence", True), ("ble_presence", True),
    ("mmwave", False), ("occupancy", False),
])
def test_fan_immune_witness_kind_membership(kind, immune):
    eid = "binary_sensor.x"
    cfg = {CONST.CONF_MOTION_SENSORS: [eid],
           CONST.CONF_SENSOR_CAPABILITIES: {eid: {"kind": kind}}}
    assert SC.is_fan_immune_witness(cfg, eid) is immune


def test_family_for_model_uses_model_when_model_id_missing():
    assert SC.family_for_model(None, "HLK-LD2410") == "ld24xx"
    assert SC.family_for_model("ZG-204ZK", None) == "zigbee_zk_zx"
    assert SC.family_for_model("ZG-204ZV", None) == "zigbee_zv"
    assert SC.family_for_model(None, "ms600 9.0.0") == "generic_radar"
    assert SC.family_for_model(None, None) == "unknown"


def test_safety_net_filters_misfiled_radar_by_model_id(monkeypatch):
    hass = MagicMock()
    hass.data = {}
    _install_registry(monkeypatch, {
        "binary_sensor.zk_in_motion": _ZK,
        _GAME_ZV: _ZV,
    })
    cfg = {CONST.CONF_MOTION_SENSORS: ["binary_sensor.zk_in_motion", _GAME_ZV]}
    assert FV.is_fan_immune_motion_witness(
        hass, cfg, "binary_sensor.zk_in_motion",
    ) is False
    assert FV.is_fan_immune_motion_witness(hass, cfg, _GAME_ZV) is True
    # One registry read per entity per boot: cached on hass.data.
    assert hass.data[DOMAIN]["_sensor_family_cache"] == {
        "binary_sensor.zk_in_motion": "zigbee_zk_zx", _GAME_ZV: "zigbee_zv",
    }


def test_registry_miss_is_not_cached(monkeypatch):
    hass = MagicMock()
    hass.data = {}
    _install_registry(monkeypatch, {})
    assert FV.resolve_sensor_family(hass, "binary_sensor.late") == "unknown"
    assert "binary_sensor.late" not in hass.data[DOMAIN]["_sensor_family_cache"]


class _D2Self:
    """Minimal fake carrying what `_d2_motion_sensors_present` reads."""

    def __init__(self, hass, data, options=None):
        self.hass = hass
        self.entry = _Entry("e", data, options)
        self._d2_no_pir_logged = False

    def _get_config(self, key, default=None):
        return self.entry.options.get(key, self.entry.data.get(key, default))


def _d2_present(hass, data, options=None):
    return CO.UniversalRoomCoordinator._d2_motion_sensors_present(
        _D2Self(hass, data, options),
    )


def test_d2_motion_sensors_present_game_room_zv_declared_pir(monkeypatch):
    """C2 AC: Game Room (ZV declared kind: pir) -> D2 reachable (True);
    the name-regex version returned False."""
    hass = MagicMock()
    hass.data = {}
    _install_registry(monkeypatch, {_GAME_ZV: _ZV})
    data = {"room_name": "Game Room", CONST.CONF_MOTION_SENSORS: [_GAME_ZV]}
    opts = {CONST.CONF_SENSOR_CAPABILITIES: {_GAME_ZV: {"kind": "pir"}}}
    assert _d2_present(hass, data, opts) is True


def test_d2_zv_only_room_without_override_is_reachable(monkeypatch):
    hass = MagicMock()
    hass.data = {}
    eid = "binary_sensor.occupancy_lux_temp_humidity_hobeian_dining_presence"
    _install_registry(monkeypatch, {eid: _ZV})
    assert _d2_present(
        hass, {"room_name": "Dining", CONST.CONF_MOTION_SENSORS: [eid]},
    ) is True


def test_d2_safety_net_misfiled_radar_fail_closed(monkeypatch):
    hass = MagicMock()
    hass.data = {}
    eid = "binary_sensor.study_radar_occupancy"
    _install_registry(monkeypatch, {eid: _ZK})
    assert _d2_present(
        hass, {"room_name": "Study A", CONST.CONF_MOTION_SENSORS: [eid]},
    ) is False


def test_d2_declared_mmwave_override_fail_closed(monkeypatch):
    hass = MagicMock()
    hass.data = {}
    eid = "binary_sensor.weird_motion"
    _install_registry(monkeypatch, {eid: (None, "unknown-thing")})
    assert _d2_present(
        hass, {"room_name": "X", CONST.CONF_MOTION_SENSORS: [eid]},
        {CONST.CONF_SENSOR_CAPABILITIES: {eid: {"kind": "mmwave"}}},
    ) is False


def _veto_hass(house_state, states):
    hass = MagicMock()
    presence = MagicMock()
    presence.house_state = house_state
    presence._boot_settle_done = True
    person = MagicMock()
    person.get_persons_in_room = MagicMock(return_value=[])
    person.data = {}
    mgr = MagicMock()
    mgr.coordinators = {"presence": presence}
    hass.data = {DOMAIN: {"coordinator_manager": mgr,
                          "person_coordinator": person}}
    hass.states.get = lambda eid: states.get(eid)
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


def test_fan_veto_zv_motion_witness_defeats_away_veto(monkeypatch):
    hass = _veto_hass(FV.HouseState.AWAY, {_GAME_ZV: _State("on")})
    _install_registry(monkeypatch, {_GAME_ZV: _ZV})
    cfg = {CONST.CONF_MOTION_SENSORS: [_GAME_ZV],
           CONST.CONF_OCCUPANCY_TIMEOUT: 300}
    assert FV.should_veto_comfort_fan(hass, "Game Room", cfg) is False


def test_fan_veto_misfiled_radar_on_does_not_defeat_veto(monkeypatch):
    eid = "binary_sensor.study_radar_occupancy"
    hass = _veto_hass(FV.HouseState.AWAY, {eid: _State("on")})
    _install_registry(monkeypatch, {eid: _ZK})
    cfg = {CONST.CONF_MOTION_SENSORS: [eid],
           CONST.CONF_OCCUPANCY_TIMEOUT: 300}
    assert FV.should_veto_comfort_fan(hass, "Study A", cfg) is True


# ===========================================================================
# C3 Part A — last-known-good fan belief in _handle_fan_change
# ===========================================================================

class _Tracker:
    def __init__(self, room, fans):
        self.room_names = {room}
        self._fan_on_rooms = set()
        self._fan_on_since = {}
        self._fan_off_at = {}
        self._fan_last_transition = {}
        self._fan_entity_to_room = {f: room for f in fans}


class _Presence:
    """Fake self for the unbound real `_handle_fan_change`."""

    def __init__(self, tracker, states):
        self._zone_trackers = {"z": tracker}
        self.hass = MagicMock()
        self.hass.states.get = lambda eid: states.get(eid)
        self._fan_known_good = {}


def _ev(eid, old, new, pct=None):
    return types.SimpleNamespace(data={
        "entity_id": eid,
        "old_state": _State(old, {"percentage": pct}) if old else None,
        "new_state": _State(new, {"percentage": pct}),
    })


def _fire(p, ev):
    PR.PresenceCoordinator._handle_fan_change(p, ev)


def _snapshot(t, p):
    return (
        set(t._fan_on_rooms), dict(t._fan_on_since), dict(t._fan_off_at),
        dict(t._fan_last_transition),
    )


def test_fan_belief_held_through_unavailable_edge():
    """C3 Part A anchor: a 100-edge on<->unavailable flap leaves all four
    belief maps exactly as they were after the real ON edge."""
    room, fan = "Media", "fan.media"
    t = _Tracker(room, [fan])
    states = {fan: _State("on")}
    p = _Presence(t, states)
    _fire(p, _ev(fan, "off", "on", 33))
    before = _snapshot(t, p)
    assert room in t._fan_on_rooms
    for i in range(50):
        _fire(p, _ev(fan, "on", "unavailable"))
        _fire(p, _ev(fan, "unavailable", "on", 33))
    assert _snapshot(t, p) == before


def test_fan_on_rooms_membership_stable_during_flap_storm():
    """Belief-stability metric (Finding 8): unknown<->off flapping on an
    OFF fan never adds the room or writes a retro-phantom _fan_off_at."""
    room, fan = "Patio", "fan.patio"
    t = _Tracker(room, [fan])
    p = _Presence(t, {fan: _State("off")})
    _fire(p, _ev(fan, "on", "off", 0))    # known-good off
    t._fan_off_at.clear()
    t._fan_last_transition.clear()
    for _ in range(20):
        _fire(p, _ev(fan, "off", "unknown"))
        _fire(p, _ev(fan, "unknown", "off", 0))
    assert room not in t._fan_on_rooms
    assert t._fan_off_at == {}
    assert t._fan_last_transition == {}


def test_wall_switch_power_on_through_unavailable_blip_still_stamps():
    """off -> unavailable -> on with known-good off = a real power-on."""
    room, fan = "Game Room", "fan.game"
    t = _Tracker(room, [fan])
    p = _Presence(t, {fan: _State("on")})
    _fire(p, _ev(fan, "on", "off", 0))
    t._fan_last_transition.clear()
    _fire(p, _ev(fan, "off", "unavailable"))
    assert room not in t._fan_on_rooms
    _fire(p, _ev(fan, "unavailable", "on", 33))
    assert room in t._fan_on_rooms
    assert room in t._fan_on_since
    assert room in t._fan_last_transition


def test_unknown_prior_belief_return_from_unavailable_is_a_transition():
    """No known-good yet (unavailable since boot): the first readable
    state is admitted as a transition (pre-C3 behaviour)."""
    room, fan = "Jaya", "fan.jaya"
    t = _Tracker(room, [fan])
    p = _Presence(t, {fan: _State("on")})
    _fire(p, _ev(fan, "unavailable", "on", 33))
    assert room in t._fan_on_rooms
    assert room in t._fan_last_transition


def test_unavailable_sibling_keeps_room_on_belief():
    """Two fans: A known-good on then unavailable; B turns off. The room
    stays fan-on (A's last known-good), no retro-phantom write."""
    room = "Master Bedroom"
    a, b = "fan.mb_a", "fan.mb_b"
    t = _Tracker(room, [a, b])
    states = {a: _State("on"), b: _State("on")}
    p = _Presence(t, states)
    _fire(p, _ev(a, "off", "on", 33))
    _fire(p, _ev(b, "off", "on", 33))
    states[a] = _State("unavailable")
    _fire(p, _ev(a, "on", "unavailable"))
    t._fan_off_at.clear()
    states[b] = _State("off")
    _fire(p, _ev(b, "on", "off", 0))
    assert room in t._fan_on_rooms
    assert t._fan_off_at == {}


def test_discovery_seeds_known_good_so_boot_on_fan_flap_is_held(monkeypatch):
    """Wire-in anchor for the discovery seed (real `_discover_room_fans`):
    a fan ON at discovery that then blips unavailable -> on is NOT a new
    transition (no `_fan_last_transition` stamp)."""
    room, fan = "Study A", "fan.study_a"
    t = _Tracker(room, [fan])
    states = {fan: _State("on")}
    p = _Presence(t, states)
    p._fan_known_good = {}
    p._fan_listener_unsub = None
    p._unsub_listeners = []
    entry = _Entry("e1", {
        CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM,
        CONST.CONF_ROOM_NAME: room, CONST.CONF_FANS: [fan],
    })
    p.hass.config_entries.async_entries = lambda domain=None: [entry]
    monkeypatch.setattr(
        PR, "async_track_state_change_event", lambda *a, **k: (lambda: None),
    )
    PR.PresenceCoordinator._discover_room_fans(p)
    assert p._fan_known_good == {fan: True}
    assert room in t._fan_on_rooms
    _fire(p, _ev(fan, "on", "unavailable"))
    _fire(p, _ev(fan, "unavailable", "on", 33))
    assert t._fan_last_transition == {}


# ===========================================================================
# C4 kill-switch surface — CM options step (rung 2)
# ===========================================================================

def _options_flow(options):
    cf = importlib.import_module(f"{_PKG}.config_flow")
    flow = cf.UniversalRoomAutomationOptionsFlow.__new__(
        cf.UniversalRoomAutomationOptionsFlow,
    )
    entry = _Entry("cm", {"entry_type": CONST.ENTRY_TYPE_COORDINATOR_MANAGER},
                   options)
    flow._config_entry = entry
    flow.hass = MagicMock()
    flow.hass.data = {}
    return flow


def _advanced_section_keys(result):
    import voluptuous as vol  # noqa: PLC0415
    schema = result["data_schema"].schema
    for key, val in schema.items():
        if str(getattr(key, "schema", key)) == "fan_recheck_advanced":
            inner = getattr(val, "schema", None)
            inner = getattr(inner, "schema", inner)
            return {
                str(k.schema): (k.default() if callable(k.default)
                                else k.default)
                for k in inner if isinstance(k, vol.Optional)
            }
    raise AssertionError("fan_recheck_advanced section missing")


def test_options_form_offers_family_scaling_default_on():
    flow = _options_flow({})
    result = _run(flow.async_step_coordinator_presence(None))
    keys = _advanced_section_keys(result)
    assert keys[CONST.CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED] is True
    assert keys[CONST.CONF_FAN_RECHECK_COOLDOWN_S] == 900


def test_options_submit_flattens_family_scaling_to_top_level():
    flow = _options_flow({CONST.CONF_FAN_RECHECK_COOLDOWN_S: 1200})
    captured = {}
    flow.async_create_entry = lambda title, data: captured.update(data) or data
    _run(flow.async_step_coordinator_presence({
        "fan_recheck_advanced": {
            CONST.CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED: False,
        },
    }))
    assert captured[CONST.CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED] is False
    assert captured[CONST.CONF_FAN_RECHECK_COOLDOWN_S] == 1200


# ===========================================================================
# Review fix B-1 — suppress window covers the whole (family-scaled) pause
# ===========================================================================

def test_long_pause_not_booked_as_manual_off(monkeypatch):
    """Config boundary: window 180 x bedroom 2.0 x ZK 2.0 = 720 s + spindown
    30 > hvac_suppress 600. At pause + 760 s the HVAC tier must still be
    suppressed (no fake manual-OFF cooldown)."""
    mgr, fc, hass, states, log, rf, rc, timers, _k = _recheck_world(
        monkeypatch, room_type="bedroom",
        presence_sensors=["binary_sensor.zk"],
        models={"binary_sensor.zk": _ZK},
        cm_options={CONST.CONF_FAN_RECHECK_WINDOW_S: 180},
    )
    ctx = FR._RoomCtx(room_name="Study A", entry_id=rc.entry.entry_id)
    mgr._rooms["Study A"] = ctx
    t0 = datetime.now(timezone.utc)
    monkeypatch.setattr(HF.dt_util, "now", lambda: t0)
    monkeypatch.setattr(FR.dt_util, "now", lambda: t0)
    _run(mgr._enter_paused(ctx, rc))
    assert timers[-1][0] == 750
    until = datetime.fromisoformat(rf.fan_recheck_suppress_until)
    assert (until - t0).total_seconds() == 810      # 30 + 720 + 60
    states["fan.study_a"] = _State("off", {"percentage": 0})
    later = t0 + timedelta(seconds=760)
    monkeypatch.setattr(HF.dt_util, "now", lambda: later)
    _run(fc.update(None, "home_day"))
    assert rf.manual_off_cooldown_until == ""


# ===========================================================================
# Review fix A-M2 / B-2 — held belief decays after the unavailable TTL
# ===========================================================================

def test_held_belief_decays_after_unavailable_ttl():
    """A fan that dies while ON (stays unavailable) loses the held ON belief
    after FAN_BELIEF_UNAVAILABLE_TTL_S: room leaves _fan_on_rooms, its
    _fan_on_since is popped (D2 'fan_off' latch-clear reads that) and a
    _fan_off_at retro-phantom stamp is written."""
    room, fan = "Media", "fan.media"
    t = _Tracker(room, [fan])
    states = {fan: _State("on")}
    p = _Presence(t, states)
    _fire(p, _ev(fan, "off", "on", 33))
    states[fan] = _State("unavailable")
    _fire(p, _ev(fan, "on", "unavailable"))
    assert room in t._fan_on_rooms              # held inside the TTL
    assert len(_decay_timers) == 1 and _decay_timers[0]["secs"] == 120
    _decay_timers[0]["cb"](None)
    assert room not in t._fan_on_rooms
    assert room not in t._fan_on_since
    assert room in t._fan_off_at
    assert p._fan_known_good[fan] is False


def test_flap_shorter_than_ttl_keeps_belief():
    room, fan = "Media", "fan.media"
    t = _Tracker(room, [fan])
    states = {fan: _State("on")}
    p = _Presence(t, states)
    _fire(p, _ev(fan, "off", "on", 33))
    _fire(p, _ev(fan, "on", "unavailable"))
    _fire(p, _ev(fan, "unavailable", "on", 33))  # back inside the TTL
    assert _decay_timers[0]["cancelled"] is True
    _decay_timers[0]["cb"](None)                 # a late fire is a no-op
    assert room in t._fan_on_rooms
    assert room in t._fan_on_since


def test_rediscovery_cancels_pending_decay(monkeypatch):
    room, fan = "Study A", "fan.study_a"
    t = _Tracker(room, [fan])
    states = {fan: _State("on")}
    p = _Presence(t, states)
    p._fan_listener_unsub = None
    p._unsub_listeners = []
    _fire(p, _ev(fan, "off", "on", 33))
    _fire(p, _ev(fan, "on", "unavailable"))
    p.hass.config_entries.async_entries = lambda domain=None: []
    monkeypatch.setattr(
        PR, "async_track_state_change_event", lambda *a, **k: (lambda: None),
    )
    PR.PresenceCoordinator._discover_room_fans(p)
    assert _decay_timers[0]["cancelled"] is True


# ===========================================================================
# Review fix A-M1 — firmware bump / unmapped radar never re-admitted
# ===========================================================================

def test_ms600_firmware_bump_still_radar():
    assert SC.family_for_model(None, "ms600 9.0.1") == "generic_radar"
    assert SC.family_for_model(None, "MS600 10.2") == "generic_radar"


def test_ms600_firmware_bump_excluded_from_d2(monkeypatch):
    hass = MagicMock()
    hass.data = {}
    eid = "binary_sensor.mmwave_motion_lux_meross_wifi_mediaroom_sensor_presence_motion"
    _install_registry(monkeypatch, {eid: (None, "ms600 9.0.1")})
    assert _d2_present(
        hass, {"room_name": "Media", CONST.CONF_MOTION_SENSORS: [eid]},
    ) is False


def test_unknown_esp32_named_presence_falls_back_to_name_exclusion(monkeypatch):
    hass = MagicMock()
    hass.data = {}
    eid = "binary_sensor.office_radar_presence"
    _install_registry(monkeypatch, {eid: (None, "esp32-c3-devkitm-1")})
    cfg = {CONST.CONF_MOTION_SENSORS: [eid]}
    assert FV.is_fan_immune_motion_witness(hass, cfg, eid) is False
    # Control: an unknown-model sensor with a plain name stays a witness.
    plain = "binary_sensor.office_pir_occupancy"
    _install_registry(monkeypatch, {plain: (None, "esp32-c3-devkitm-1")})
    assert FV.is_fan_immune_motion_witness(
        hass, {CONST.CONF_MOTION_SENSORS: [plain]}, plain,
    ) is True


def test_unrecognised_family_warns_once_per_room(monkeypatch, caplog):
    mgr, fc, hass, states, log, rf, rc, timers, _k = _recheck_world(
        monkeypatch, presence_sensors=["binary_sensor.esp"],
        models={"binary_sensor.esp": _ESP},
    )
    merged = {**rc.entry.data, **rc.entry.options}
    timing = mgr._timing_config()
    with caplog.at_level("WARNING"):
        assert mgr._family_factor(merged, timing, "Study A") == 1.0
        assert mgr._family_factor(merged, timing, "Study A") == 1.0
    warns = [r for r in caplog.records if "family not recognised" in r.getMessage()]
    assert len(warns) == 1


def test_rehydrate_paused_threshold_covers_long_spindown(monkeypatch):
    """Review A-L1: spindown 90 / window 30 -> pause is 120 s; the old
    2 x window = 60 s threshold dropped a live pause at 70 s."""
    ctx, _timers, tasks = _rehydrate(
        monkeypatch, FR.STATE_PAUSED, 70,
        cm_options={CONST.CONF_FAN_RECHECK_SPINDOWN_S: 90,
                    CONST.CONF_FAN_RECHECK_WINDOW_S: 30},
    )
    names = [getattr(getattr(t, "cr_code", None), "co_name", "") for t in tasks]
    for t in tasks:
        t.close()
    assert names == ["_restore"]


def test_rediscovery_drops_known_good_of_unavailable_fan(monkeypatch):
    """Review A-L2: known-good ON, then re-discovery while the fan is
    unavailable -> entry dropped, so its later return 'on' is a real
    transition (re-discovery already cleared the room's belief maps)."""
    room, fan = "Study A", "fan.study_a"
    t = _Tracker(room, [fan])
    states = {fan: _State("unavailable")}
    p = _Presence(t, states)
    p._fan_known_good = {fan: True}
    p._fan_listener_unsub = None
    p._unsub_listeners = []
    entry = _Entry("e1", {
        CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM,
        CONST.CONF_ROOM_NAME: room, CONST.CONF_FANS: [fan],
    })
    p.hass.config_entries.async_entries = lambda domain=None: [entry]
    monkeypatch.setattr(
        PR, "async_track_state_change_event", lambda *a, **k: (lambda: None),
    )
    PR.PresenceCoordinator._discover_room_fans(p)
    assert fan not in p._fan_known_good
    _fire(p, _ev(fan, "unavailable", "on", 33))
    assert room in t._fan_on_rooms

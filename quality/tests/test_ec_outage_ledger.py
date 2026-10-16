"""EC-OUTAGE-LEDGER (Stage L of PLANNING_ec_storm_and_blind_decisions.md).

Drives production code: the real `UniversalRoomDatabase` (schema created by
its own `initialize()`, never hand-copied DDL), the real `OutageLedger`, and
the real `EnergyCoordinator._decision_cycle_body` / `async_teardown`.
Oracles are literal: calendar summaries are the live strings read from
`calendar.main_panel_wall_enphase_cloud_hacs_system_event_history` on
2026-10-16 for the 2026-09-16 outage; the alert is the live WIY payload.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from custom_components.universal_room_automation.database import (
    UniversalRoomDatabase,
)
from custom_components.universal_room_automation.domain_coordinators import (
    energy_outage_ledger as L,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    BatteryStrategy,
)

DOMAIN = "universal_room_automation"
CDT = timezone(timedelta(hours=-5))
NWS = "sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts"
CAL = "calendar.main_panel_wall_enphase_cloud_hacs_system_event_history"
GE = "switch.enpower_482348004678_grid_enabled"
GS = "binary_sensor.enpower_482348004678_grid_status"

OFFGRID = "Your system is now off grid or disconnected from the grid."
ONGRID = "Your system is now connected to the grid."
GEN_ON = "Your generator is now turned on as per Automatic profile"
GEN_OFF = "Your generator is now turned off."
REBOOT = "Gateway rebooted"


def _alert(aid="d39a0907-7955-f998-4def-f28ae2509698", ends="2026-10-16T19:00:00-05:00"):
    return {
        "Event": "Wind Advisory", "ID": aid, "Type": "Update", "NWSCode": "WIY",
        "Status": "Actual", "Severity": "Moderate", "Certainty": "Likely",
        "Sent": "2026-10-16T10:26:00-05:00", "Onset": "2026-10-16T10:26:00-05:00",
        "Expires": ends, "Ends": ends, "AreasAffected": "Travis; Hays",
    }


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class _State:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class _States:
    def __init__(self):
        self.d = {}

    def get(self, eid):
        return self.d.get(eid)


class _FakeDB:
    """Captures log_activity calls; awaited by the hass task collector."""

    def __init__(self):
        self.rows = []
        self.query_rows = []

    async def log_activity(self, **kw):
        self.rows.append(kw)

    async def query_activities(self, **kw):
        self.last_query = kw
        return {"rows": list(self.query_rows)}


class _Hass:
    def __init__(self, db=None):
        self.data = {DOMAIN: {"database": db}} if db is not None else {}
        self.states = _States()
        self.tasks = []
        self.services = SimpleNamespace(async_call=None)

    def async_create_task(self, coro):
        t = asyncio.ensure_future(coro)
        self.tasks.append(t)
        return t

    async def drain(self):
        while self.tasks:
            t = self.tasks.pop(0)
            await t


def _rows(db, action=None, witness=None):
    out = [r for r in db.rows if action is None or r["action"] == action]
    if witness is not None:
        out = [r for r in out if json.loads(r["details_json"]).get("witness") == witness]
    return out


def _tick(ledger, now, alerts=None, local=None, decision=None):
    ledger.record_tick(
        now=now, alerts=alerts, nws_entity=NWS, decision=decision,
        decision_age_s=0.0, soc=55, local_readings=local or {},
    )


NOW = datetime(2026, 10, 16, 12, 0, tzinfo=CDT)


async def _seeded(hass):
    """A ledger whose cross-boot alert seed has run (production path)."""
    led = L.OutageLedger(hass)
    await led._seed_alerts(NOW)
    return led


# --------------------------------------------------------------------------
# D-L0: prune exemption (real DB, real schema)
# --------------------------------------------------------------------------
def _make_db(tmp_path):
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)
    hass.async_create_background_task = lambda coro, name=None: asyncio.ensure_future(coro)
    hass.async_create_task = lambda coro, name=None: asyncio.ensure_future(coro)
    return UniversalRoomDatabase(hass)


@pytest_asyncio.fixture
async def real_db(tmp_path):
    db = _make_db(tmp_path)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        yield db
    finally:
        await db.stop_write_worker()


def _seed(db_file, action, importance, days_old):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO ura_activity_log (timestamp, coordinator, action, importance,"
            " description) VALUES (?, 'energy', ?, ?, 'seed')",
            (ts, action, importance),
        )
        conn.commit()
    finally:
        conn.close()


def _actions(db_file):
    conn = sqlite3.connect(db_file)
    try:
        return sorted(
            (a, i) for a, i in conn.execute("SELECT action, importance FROM ura_activity_log")
        )
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_prune_keeps_ledger_rows(real_db):
    db = real_db
    for action in ("nws_alert", "grid_outage", "inclement_code_drift", "inclement_memory_cleared"):
        _seed(db.db_file, action, "info", 40)
        _seed(db.db_file, action, "notable", 40)
    await db.prune_activity_log()
    left = _actions(db.db_file)
    assert len(left) == 8
    assert ("nws_alert", "info") in left and ("nws_alert", "notable") in left
    assert ("grid_outage", "info") in left and ("grid_outage", "notable") in left


@pytest.mark.asyncio
async def test_prune_still_deletes_other_rows(real_db):
    db = real_db
    _seed(db.db_file, "reserve_write", "notable", 40)   # > 30 d -> deleted
    _seed(db.db_file, "reserve_write", "info", 8)       # > 7 d  -> deleted
    _seed(db.db_file, "reserve_write", "notable", 8)    # < 30 d -> kept
    _seed(db.db_file, "nws_alert", "info", 8)           # ledger -> kept
    await db.prune_activity_log()
    assert _actions(db.db_file) == [("nws_alert", "info"), ("reserve_write", "notable")]


def test_ledger_exemption_rejects_bad_identifier():
    from custom_components.universal_room_automation.database import (
        _render_ledger_exemption,
    )
    assert _render_ledger_exemption(()) == ""
    with pytest.raises(ValueError):
        _render_ledger_exemption(("x'); DROP TABLE t; --",))


@pytest.mark.asyncio
async def test_query_activities_action_filter(real_db):
    db = real_db
    _seed(db.db_file, "grid_outage", "notable", 1)
    _seed(db.db_file, "reserve_write", "notable", 1)
    res = await db.query_activities(action="grid_outage")
    assert [r["action"] for r in res["rows"]] == ["grid_outage"]
    res_all = await db.query_activities()
    assert len(res_all["rows"]) == 2


@pytest.mark.asyncio
async def test_ledger_row_round_trips_through_real_db(real_db):
    """End-to-end: an nws_alert row written by the ledger lands in the real
    table through the production log_activity DAO, with its payload."""
    db = real_db
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, alerts=[_alert()])
    await hass.drain()
    res = await db.query_activities(action="nws_alert", columns=("details_json", "importance"))
    assert len(res["rows"]) == 1
    d = json.loads(res["rows"][0]["details_json"])
    assert d["NWSCode"] == "WIY" and d["id"] == "d39a0907-7955-f998-4def-f28ae2509698"
    assert d["ura_class"] is None and d["local"] == "unknown"
    assert res["rows"][0]["importance"] == "notable"


# --------------------------------------------------------------------------
# D-L1: nws_alert rows
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_alert_ledger_one_row_per_id():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, alerts=[_alert("A"), _alert("B")])
    _tick(led, NOW + timedelta(minutes=5), alerts=[_alert("A"), _alert("B")])
    await hass.drain()
    assert sorted(json.loads(r["details_json"])["id"] for r in _rows(db, "nws_alert")) == ["A", "B"]
    assert all(r["entity_id"] == NWS for r in db.rows)


@pytest.mark.asyncio
async def test_alert_ledger_seen_set_pruned():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, alerts=[_alert("A", ends="2026-10-16T12:30:00-05:00")])
    assert "A" in led._seen_alerts
    # Left the feed but not yet ended: kept (a feed blip must not re-log).
    _tick(led, NOW + timedelta(minutes=5), alerts=[])
    assert "A" in led._seen_alerts
    _tick(led, NOW + timedelta(minutes=10), alerts=[_alert("A", ends="2026-10-16T12:30:00-05:00")])
    # Left the feed and ended: pruned.
    _tick(led, NOW + timedelta(minutes=31), alerts=[])
    assert "A" not in led._seen_alerts
    await hass.drain()
    assert len(_rows(db, "nws_alert")) == 1


@pytest.mark.asyncio
async def test_alert_ledger_unavailable_feed_writes_nothing_and_keeps_set():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, alerts=[_alert("A", ends="2026-10-16T12:01:00-05:00")])
    _tick(led, NOW + timedelta(hours=2), alerts=None)
    assert "A" in led._seen_alerts
    await hass.drain()
    assert len(db.rows) == 1


@pytest.mark.asyncio
async def test_alert_ledger_no_database_does_not_mark_seen():
    hass = _Hass(None)
    led = await _seeded(hass)
    _tick(led, NOW, alerts=[_alert("A")])
    assert led._seen_alerts == {}


# --------------------------------------------------------------------------
# D-L2(ii): local corroboration
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_outage_local_only_never_opens_episode():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    dec = SimpleNamespace(tier="watch", hold_depth="partial_hold", reserve_floor=50)
    for i, r in enumerate([False, True, True, None, True, False]):
        _tick(led, NOW + timedelta(minutes=5 * i), alerts=[_alert("A")],
              local={GE: r}, decision=dec)
    await hass.drain()
    rows = _rows(db, "grid_outage")
    assert len(rows) == 1
    d = json.loads(rows[0]["details_json"])
    assert d["witness"] == "local_only"
    assert d["hold_depth"] == "partial_hold" and d["reserve_floor"] == 50
    assert d["active_alert_ids"] == ["A"] and d["soc"] == 55
    assert _rows(db, "grid_outage", witness="cloud") == []


@pytest.mark.asyncio
async def test_outage_witness_none_is_not_a_transition():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    # Baseline True (off-grid); a None between two Trues must not read as a
    # False -> True transition.
    for i, r in enumerate([True, None, True, None, True]):
        _tick(led, NOW + timedelta(minutes=5 * i), local={GE: r})
    assert led._local_last[GE] is True
    await hass.drain()
    assert _rows(db, "grid_outage") == []


@pytest.mark.asyncio
async def test_outage_witness_boot_sets_baseline_silently():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, local={GE: True})
    _tick(led, NOW + timedelta(minutes=5), local={GE: True})
    await hass.drain()
    assert _rows(db, "grid_outage") == []


@pytest.mark.asyncio
async def test_outage_local_sensors_tracked_independently():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, local={GE: False, GS: None})
    _tick(led, NOW + timedelta(minutes=5), local={GE: True, GS: False})
    _tick(led, NOW + timedelta(minutes=10), local={GE: True, GS: True})
    await hass.drain()
    assert [r["entity_id"] for r in _rows(db, "grid_outage")] == [GE, GS]


# --------------------------------------------------------------------------
# D-L2(i): cloud sweep
# --------------------------------------------------------------------------
def _ev(t, summary):
    return {"start": t.isoformat(), "end": (t + timedelta(minutes=1)).isoformat(),
            "summary": summary}


SEP16 = datetime(2026, 9, 16, 12, 39, 26, tzinfo=CDT)
SWEEP_NOW = datetime(2026, 9, 17, 9, 0, tzinfo=CDT)


def _calendar_events():
    return [
        _ev(SEP16 - timedelta(hours=3), REBOOT),
        _ev(SEP16, OFFGRID),
        _ev(datetime(2026, 9, 16, 12, 43, 18, tzinfo=CDT), GEN_ON),
        _ev(datetime(2026, 9, 16, 12, 52, 3, tzinfo=CDT), GEN_OFF),
        _ev(datetime(2026, 9, 16, 12, 57, 59, tzinfo=CDT), ONGRID),
    ]


def _registry(monkeypatch, entries):
    from homeassistant.helpers import entity_registry as er
    reg = SimpleNamespace(entities={e[0]: SimpleNamespace(entity_id=e[0], platform=e[1])
                                    for e in entries})
    monkeypatch.setattr(er, "async_get", lambda hass: reg)


def _sweep_hass(events, db=None):
    db = db or _FakeDB()
    hass = _Hass(db)
    calls = []

    async def _call(domain, service, data, blocking=False, return_response=False):
        calls.append((domain, service, data, blocking, return_response))
        return {data["entity_id"]: {"events": list(events)}}

    hass.services.async_call = _call
    hass.calls = calls
    hass.states.d[CAL] = _State("off")
    return hass, db


@pytest.mark.asyncio
async def test_outage_sweep_substring_match(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev"), ("calendar.other_system_event_history", "google")])
    hass, db = _sweep_hass(_calendar_events() + [
        _ev(SEP16 + timedelta(hours=5), "NOTICE: SYSTEM IS NOW OFF GRID (manual)"),
    ])
    led = await _seeded(hass)
    n = await led.sweep(SWEEP_NOW)
    await hass.drain()
    assert n == 2
    rows = _rows(db, "grid_outage", witness="cloud")
    assert len(rows) == 2
    d = json.loads(rows[0]["details_json"])
    assert d["summary"] == OFFGRID
    assert d["event_start_utc"] == "2026-09-16T17:39:26+00:00"
    assert rows[0]["timestamp"] == "2026-09-16T17:39:26+00:00"
    assert d["ongrid_at"] == "2026-09-16T12:57:59-05:00"
    assert [g["summary"] for g in d["generator_events"]] == [GEN_ON, GEN_OFF]
    assert rows[0]["entity_id"] == CAL
    # The service call shape (entity service with response, 48 h window).
    dom, svc, data, blocking, rr = hass.calls[0]
    assert (dom, svc, blocking, rr) == ("calendar", "get_events", True, True)
    assert data["end_date_time"] - data["start_date_time"] == timedelta(hours=48)


def test_classify_calendar_summary_literals():
    assert L.classify_calendar_summary(OFFGRID) == "offgrid"
    assert L.classify_calendar_summary(ONGRID) == "ongrid"
    assert L.classify_calendar_summary(GEN_OFF) == "generator"
    assert L.classify_calendar_summary(REBOOT) is None
    assert L.classify_calendar_summary(None) is None


@pytest.mark.asyncio
async def test_outage_sweep_gateway_reboot_writes_nothing(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass([_ev(SEP16, REBOOT), _ev(SEP16, ONGRID), _ev(SEP16, GEN_ON)])
    assert await L.OutageLedger(hass).sweep(SWEEP_NOW) == 0
    await hass.drain()
    assert db.rows == []


@pytest.mark.asyncio
async def test_outage_sweep_dedups_across_sweeps(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass(_calendar_events())
    led = await _seeded(hass)
    assert await led.sweep(SWEEP_NOW) == 1
    assert await led.sweep(SWEEP_NOW + timedelta(hours=6)) == 0
    await hass.drain()
    assert len(_rows(db, "grid_outage", witness="cloud")) == 1


@pytest.mark.asyncio
async def test_outage_sweep_dedups_across_boots(monkeypatch):
    """A fresh ledger (new boot) seeds its seen-set from rows already in the DB."""
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    db = _FakeDB()
    db.query_rows = [{"details_json": json.dumps(
        {"witness": "cloud", "event_start_utc": "2026-09-16T17:39:26+00:00"})}]
    hass, _ = _sweep_hass(_calendar_events(), db=db)
    assert await L.OutageLedger(hass).sweep(SWEEP_NOW) == 0
    assert db.last_query["action"] == "grid_outage"
    await hass.drain()
    assert db.rows == []


@pytest.mark.asyncio
async def test_outage_sweep_marks_local_corroboration(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass(_calendar_events())
    led = await _seeded(hass)
    _tick(led, SEP16 - timedelta(minutes=10), local={GE: False})
    _tick(led, SEP16 + timedelta(minutes=3), local={GE: True})
    await led.sweep(SWEEP_NOW)
    await hass.drain()
    d = json.loads(_rows(db, "grid_outage", witness="cloud")[0]["details_json"])
    assert d["corroborated_by_local"] is True


@pytest.mark.asyncio
async def test_outage_sweep_local_outside_tolerance_not_corroborated(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass(_calendar_events())
    led = await _seeded(hass)
    _tick(led, SEP16 - timedelta(minutes=30), local={GE: False})
    _tick(led, SEP16 + timedelta(minutes=11), local={GE: True})
    await led.sweep(SWEEP_NOW)
    await hass.drain()
    d = json.loads(_rows(db, "grid_outage", witness="cloud")[0]["details_json"])
    assert d["corroborated_by_local"] is False


@pytest.mark.asyncio
async def test_outage_sweep_embeds_nearest_decision(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass(_calendar_events())
    led = await _seeded(hass)
    _tick(led, SEP16 - timedelta(hours=1),
          decision=SimpleNamespace(tier="warn", hold_depth="full_hold", reserve_floor=80))
    _tick(led, SEP16 + timedelta(hours=1),
          decision=SimpleNamespace(tier="none", hold_depth="allow_discharge", reserve_floor=20))
    await led.sweep(SWEEP_NOW)
    await hass.drain()
    d = json.loads(_rows(db, "grid_outage", witness="cloud")[0]["details_json"])
    assert d["inclement_decision"]["hold_depth"] == "full_hold"
    assert d["inclement_decision"]["reserve_floor"] == 80


@pytest.mark.asyncio
@pytest.mark.parametrize("entries,count", [
    ([], 0),
    ([(CAL, "enphase_ev"), ("calendar.b_system_event_history", "enphase_ev")], 2),
    ([(CAL, "enphase_envoy")], 0),
    ([("calendar.main_panel_events", "enphase_ev")], 0),
])
async def test_outage_sweep_calendar_unresolved(monkeypatch, caplog, entries, count):
    _registry(monkeypatch, entries)
    hass, db = _sweep_hass(_calendar_events())
    led = await _seeded(hass)
    with caplog.at_level("WARNING"):
        assert await led.sweep(SWEEP_NOW) == 0
        assert await led.sweep(SWEEP_NOW) == 0
    msgs = [r.getMessage() for r in caplog.records if "calendar not resolved" in r.getMessage()]
    assert msgs == [f"outage sweep: calendar not resolved (found {count})"]
    assert hass.calls == []
    assert db.rows == []


@pytest.mark.asyncio
async def test_outage_sweep_calendar_unavailable_skips(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass(_calendar_events())
    hass.states.d[CAL] = _State("unavailable")
    assert await L.OutageLedger(hass).sweep(SWEEP_NOW) == 0
    assert hass.calls == []


@pytest.mark.asyncio
async def test_outage_sweep_failure_isolated(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass([])

    async def _boom(*a, **k):
        raise RuntimeError("calendar exploded")

    hass.services.async_call = _boom
    led = await _seeded(hass)
    assert await led.sweep(SWEEP_NOW) == 0
    # Timeout path: the call never returns within the timeout.
    monkeypatch.setattr(L, "OUTAGE_SWEEP_TIMEOUT_S", 0.01)

    async def _hang(*a, **k):
        await asyncio.sleep(5)

    hass.services.async_call = _hang
    assert await led.sweep(SWEEP_NOW) == 0
    await hass.drain()
    assert db.rows == []
    assert led._cloud_seen == set()


# --------------------------------------------------------------------------
# Scheduling + teardown (real async_teardown)
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_outage_sweep_task_cancelled_on_unload(monkeypatch):
    import importlib
    # Production does `from homeassistant.helpers.event import ...`, which
    # resolves through sys.modules (a sibling file may have stubbed it).
    ev_mod = importlib.import_module("homeassistant.helpers.event")
    handles = []

    def _later(hass, delay, cb):
        h = MagicMock(name=f"later{delay}")
        handles.append(("later", delay, cb, h))
        return h

    def _interval(hass, cb, interval):
        h = MagicMock(name="interval")
        handles.append(("interval", interval, cb, h))
        return h

    monkeypatch.setattr(ev_mod, "async_call_later", _later)
    monkeypatch.setattr(ev_mod, "async_track_time_interval", _interval)
    hass = _Hass(_FakeDB())
    led = await _seeded(hass)
    assert led.arm() is True
    assert led.arm() is True  # idempotent: no second pair of handles
    assert [(k, d) for k, d, _c, _h in handles] == [
        ("later", 300), ("interval", timedelta(hours=24))]
    gate = asyncio.Event()

    async def _slow_sweep(now=None):
        await gate.wait()

    led.sweep = _slow_sweep
    handles[0][2](None)  # initial timer fires -> sweep task spawned
    await asyncio.sleep(0)
    task = led._sweep_task
    assert task is not None and not task.done()

    # Drive the REAL EnergyCoordinator.async_teardown cancel wiring.
    class _Shell(EnergyCoordinator):
        def __init__(self):
            pass

    c = _Shell()
    c._decision_timer_unsub = None
    c._outage_ledger = led

    class _StopTeardown(Exception):
        pass

    def _stop(*_a, **_k):
        raise _StopTeardown

    c._solar_follow_timer_unsub = None
    c._solar_follow = None
    c._tou_boundary_unsub = None
    c._peak_import_history = None
    c._save_evse_state = _stop  # stop after the cancel block; rest is not under test
    with pytest.raises(_StopTeardown):
        await c.async_teardown()
    await asyncio.sleep(0)
    assert task.cancelled()
    handles[0][3].assert_not_called()  # initial timer already fired
    handles[1][3].assert_called_once()
    assert led._initial_unsub is None and led._interval_unsub is None


def test_outage_ledger_cancel_before_initial_fire(monkeypatch):
    import importlib
    # Production does `from homeassistant.helpers.event import ...`, which
    # resolves through sys.modules (a sibling file may have stubbed it).
    ev_mod = importlib.import_module("homeassistant.helpers.event")
    hs = []
    monkeypatch.setattr(ev_mod, "async_call_later",
                        lambda h, d, cb: hs.append(MagicMock()) or hs[-1])
    monkeypatch.setattr(ev_mod, "async_track_time_interval",
                        lambda h, cb, i: hs.append(MagicMock()) or hs[-1])
    led = L.OutageLedger(_Hass(_FakeDB()))
    led.arm()
    led.cancel()
    led.cancel()  # safe twice
    hs[0].assert_called_once()
    hs[1].assert_called_once()


def test_outage_sweep_disabled_when_interval_zero(monkeypatch):
    monkeypatch.setattr(L, "OUTAGE_SWEEP_INTERVAL_H", 0)
    assert L.OutageLedger(_Hass(_FakeDB())).arm() is False


@pytest.mark.asyncio
async def test_async_setup_arms_outage_ledger():
    """Call-site anchor for `_arm_outage_ledger` in async_setup: drive the
    real async_setup far enough to pass the arm call."""
    class _Shell(EnergyCoordinator):
        def __init__(self):
            pass

    armed = []
    c = _Shell()
    c.hass = _Hass(_FakeDB())
    c._decision_timer_unsub = None
    c._solar_follow = None
    c._decision_interval = 5

    async def _restore(now):
        return None

    c._restore_all_sequential = _restore
    c._register_solar_follow_timer = lambda: None
    c._unsub_listeners = []
    c._outage_ledger = SimpleNamespace(arm=lambda: armed.append(True))
    c._write_verifier = object()

    class _Stop(Exception):
        pass

    def _stop(*_a, **_k):
        raise _Stop

    c._optimizer_intent_unsub = None
    import custom_components.universal_room_automation.domain_coordinators.energy as E
    orig_track = E.async_track_time_interval
    orig_conn = E.async_dispatcher_connect
    E.async_track_time_interval = lambda *a, **k: (lambda: None)
    calls = {"n": 0}

    def _conn(*a, **k):
        calls["n"] += 1
        if calls["n"] >= 2:  # the optimizer-intent subscribe follows the arm
            raise _Stop
        return lambda: None

    E.async_dispatcher_connect = _conn
    try:
        with pytest.raises(_Stop):
            await c.async_setup()
    finally:
        E.async_track_time_interval = orig_track
        E.async_dispatcher_connect = orig_conn
    assert armed == [True]


# --------------------------------------------------------------------------
# Hook placement: the REAL _decision_cycle_body (enclosing-method anchor)
# --------------------------------------------------------------------------
class _CycleShell(EnergyCoordinator):
    def __init__(self):  # bypass heavy init
        pass


class _Stop(Exception):
    pass


def _battery_stub(hass, decision_dict, inc_dec=None, inc_at=None):
    b = SimpleNamespace()
    b.hass = hass
    b._inclement_config = lambda: {"nws_alerts_entity": NWS}
    b._read_nws_alerts = types.MethodType(BatteryStrategy._read_nws_alerts, b)
    b._last_inclement_decision = inc_dec
    b._last_inclement_decision_at = inc_at
    b.battery_soc = None
    b._get_entity = lambda key, default=None, **k: GE if key == "grid_enabled" else default
    b.determine_mode = lambda *a, **k: dict(decision_dict)
    b._offpeak_drain_branch_target = None
    return b


def _cycle(hass, battery, verifier=None):
    c = _CycleShell()
    c.hass = hass
    c._battery = battery
    c._ev = SimpleNamespace(current_charging_load_w=lambda: 0)
    c._tou = SimpleNamespace(get_current_period=lambda *a: "peak",
                             get_season=lambda *a: "summer",
                             check_period_transition=lambda: None)
    c._maybe_reset_daily = lambda: None
    c._soc_untrusted_from_battery = lambda: True
    c._stamp_ev_start_soc_verdict = lambda v: None
    c._ev_start_hold_label = lambda **k: None
    c._outage_ledger = L.OutageLedger(hass)
    c._write_verifier = verifier

    async def _acct(*a):
        return None

    async def _noop():
        return None

    c._account_arbitrage_cycle = _acct
    c._refresh_arbitrage_status_cache = _noop

    def _halt():
        raise _Stop  # halt the body right after the ledger hook's zone

    c._is_any_evse_charging = _halt
    return c


@pytest.mark.asyncio
async def test_ledger_logs_alerts_during_grid_disconnect_return():
    """determine_mode's grid-disconnect early return yields a bare decision
    (no actions, no fresh inclement decision); the hook still logs."""
    db = _FakeDB()
    hass = _Hass(db)
    hass.states.d[NWS] = _State("1", {"Alerts": [_alert("A")]})
    b = _battery_stub(hass, {"mode": "grid_disconnected", "reason": "grid off",
                             "actions": []})
    c = _cycle(hass, b)
    await c._outage_ledger._seed_alerts(NOW)
    await c._decision_cycle_body()
    await hass.drain()
    rows = _rows(db, "nws_alert")
    assert len(rows) == 1
    assert json.loads(rows[0]["details_json"])["decision_age_s"] is None


@pytest.mark.asyncio
async def test_ledger_logs_alerts_while_fully_blind():
    db = _FakeDB()
    hass = _Hass(db)
    hass.states.d[NWS] = _State("2", {"Alerts": [_alert("A"), _alert("B")]})
    stale = datetime.now(timezone.utc) - timedelta(hours=3)
    b = _battery_stub(
        hass, {"mode": "blind", "reason": "fully blind", "actions": [], "soc": None},
        inc_dec=SimpleNamespace(tier="watch", hold_depth="partial_hold", reserve_floor=50),
        inc_at=stale,
    )
    c = _cycle(hass, b)
    await c._outage_ledger._seed_alerts(NOW)
    await c._decision_cycle_body()
    await hass.drain()
    rows = _rows(db, "nws_alert")
    assert sorted(json.loads(r["details_json"])["id"] for r in rows) == ["A", "B"]
    age = json.loads(rows[0]["details_json"])["decision_age_s"]
    assert 10700 < age < 10900  # ~3 h stale, and the row says so


@pytest.mark.asyncio
async def test_decision_cycle_feeds_local_witnesses():
    """Both local legs reach the ledger through the real body: grid_enabled
    via WriteVerifier._grid_outage_active, grid_status via the derived
    sibling entity."""
    db = _FakeDB()
    hass = _Hass(db)
    hass.states.d[GS] = _State("on")
    b = _battery_stub(hass, {"mode": "x", "reason": "", "actions": []})
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    verifier = WriteVerifier.__new__(WriteVerifier)
    verifier.hass = hass
    hass.states.d[GE] = _State("on")
    c = _cycle(hass, b, verifier=verifier)
    await c._decision_cycle_body()
    assert c._outage_ledger._local_last == {"grid_enabled": False, GS: False}
    hass.states.d[GE] = _State("off")
    hass.states.d[GS] = _State("off")
    await c._decision_cycle_body()
    await hass.drain()
    assert sorted(r["entity_id"] for r in _rows(db, "grid_outage", witness="local_only")) == [
        GS, "grid_enabled"]


@pytest.mark.asyncio
async def test_outage_local_readings_unknown_states_are_none():
    hass = _Hass(_FakeDB())
    hass.states.d[GS] = _State("unavailable")
    c = _cycle(hass, _battery_stub(hass, {}))
    assert c._outage_local_readings() == {GS: None}  # no verifier -> grid_enabled leg inert


# --------------------------------------------------------------------------
# B-HIGH-1: timer callbacks must run ON the event loop (real HA timers)
# --------------------------------------------------------------------------
def test_sweep_timer_callbacks_are_ha_callbacks():
    from homeassistant.core import is_callback
    led = L.OutageLedger(_Hass(_FakeDB()))
    assert is_callback(led._spawn_sweep)
    assert is_callback(led._on_initial)


@pytest.mark.asyncio
async def test_real_timers_run_the_sweep_on_the_loop():
    """Real HomeAssistant + real async_call_later / async_track_time_interval
    + time travel: the initial timer and the interval timer each spawn a
    sweep task that runs on the loop thread. Without @callback HA dispatches
    them to an executor thread and `async_create_task` raises there, so the
    sweep never runs."""
    import threading
    from pytest_homeassistant_custom_component.common import (
        async_fire_time_changed,
        async_test_home_assistant,
    )
    from homeassistant.util import dt as dt_util

    async with async_test_home_assistant() as hass:
        led = await _seeded(hass)
        ran = []
        loop_thread = threading.get_ident()

        async def _rec(now=None):
            ran.append(threading.get_ident())

        led.sweep = _rec
        assert led.arm() is True
        try:
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=301))
            await hass.async_block_till_done()
            assert ran == [loop_thread]
            async_fire_time_changed(
                hass, dt_util.utcnow() + timedelta(hours=24, seconds=5))
            await hass.async_block_till_done()
            assert ran == [loop_thread, loop_thread]
        finally:
            led.cancel()
            await hass.async_stop(force=True)


# --------------------------------------------------------------------------
# A-M1 / B-LOW-1 / A-L2: cross-boot alert seed, retry, cloud seed retry
# --------------------------------------------------------------------------
class _ScriptedDB(_FakeDB):
    """query_activities answers from a script (results or futures)."""

    def __init__(self, script):
        super().__init__()
        self.script = list(script)
        self.queries = []

    async def query_activities(self, **kw):
        self.queries.append(kw)
        item = self.script.pop(0) if self.script else {"rows": [], "page_size": 200}
        if isinstance(item, asyncio.Future):
            return await item
        return item


def _alert_row(aid, ends="2026-10-16T19:00:00-05:00"):
    return {"id": 1, "details_json": json.dumps(
        {"id": aid, "Ends": ends, "Expires": ends, "NWSCode": "WIY"})}


@pytest.mark.asyncio
async def test_alert_seed_dedups_across_boots():
    db = _ScriptedDB([{"rows": [_alert_row("A")], "page_size": 200}])
    hass = _Hass(db)
    led = await _seeded(hass)
    assert db.queries[0]["action"] == "nws_alert"
    assert db.queries[0]["since"] == (NOW - timedelta(hours=72)).isoformat()
    _tick(led, NOW, alerts=[_alert("A"), _alert("B")])
    await hass.drain()
    assert [json.loads(r["details_json"])["id"] for r in _rows(db, "nws_alert")] == ["B"]


@pytest.mark.asyncio
async def test_alert_pass_waits_for_seed():
    gate = asyncio.get_running_loop().create_future()
    db = _ScriptedDB([gate])
    hass = _Hass(db)
    led = L.OutageLedger(hass)
    _tick(led, NOW, alerts=[_alert("A")])  # spawns the seed, writes nothing
    await asyncio.sleep(0)
    assert db.rows == [] and led._alerts_seeded is False
    _tick(led, NOW + timedelta(minutes=5), alerts=[_alert("A")])  # still in flight
    await asyncio.sleep(0)
    assert len(db.queries) == 1  # no second seed task while one is in flight
    gate.set_result({"rows": [], "page_size": 200})
    await hass.drain()
    assert led._alerts_seeded is True
    _tick(led, NOW + timedelta(minutes=10), alerts=[_alert("A")])
    await hass.drain()
    assert len(_rows(db, "nws_alert")) == 1


@pytest.mark.asyncio
async def test_alert_seed_failure_is_retried_then_proceeds_unseeded(caplog):
    err = {"rows": [], "error": "database is locked"}
    db = _ScriptedDB([err, err, err])
    hass = _Hass(db)
    led = L.OutageLedger(hass)
    _tick(led, NOW, alerts=[_alert("A")])
    await hass.drain()
    assert led._alerts_seeded is False and led._alert_seed_attempts == 1
    _tick(led, NOW + timedelta(minutes=5), alerts=[_alert("A")])
    await hass.drain()
    assert led._alerts_seeded is False and led._alert_seed_attempts == 2
    assert db.rows == []
    with caplog.at_level("WARNING"):
        _tick(led, NOW + timedelta(minutes=10), alerts=[_alert("A")])
        await hass.drain()
    assert led._alerts_seeded is True and led._alert_seed_attempts == 3
    assert any("seed failed 3 times" in r.getMessage() for r in caplog.records)
    _tick(led, NOW + timedelta(minutes=15), alerts=[_alert("A")])
    await hass.drain()
    assert len(_rows(db, "nws_alert")) == 1


@pytest.mark.asyncio
async def test_alert_seed_no_database_counts_attempt():
    led = L.OutageLedger(_Hass(None))
    assert await led._seed_alerts(NOW) is False
    assert led._alerts_seeded is False and led._alert_seed_attempts == 1


@pytest.mark.asyncio
async def test_seed_reads_all_pages():
    db = _ScriptedDB([
        {"rows": [_alert_row("A")], "page_size": 1, "next_cursor": 9},
        {"rows": [_alert_row("B")], "page_size": 1, "next_cursor": 8},
        {"rows": [], "page_size": 1, "next_cursor": None},
    ])
    led = await _seeded(_Hass(db))
    assert set(led._seen_alerts) == {"A", "B"}
    assert [q["cursor"] for q in db.queries] == [None, 9, 8]


@pytest.mark.asyncio
async def test_arm_starts_alert_seed(monkeypatch):
    import importlib
    ev_mod = importlib.import_module("homeassistant.helpers.event")
    monkeypatch.setattr(ev_mod, "async_call_later", lambda h, d, cb: MagicMock())
    monkeypatch.setattr(ev_mod, "async_track_time_interval", lambda h, cb, i: MagicMock())
    db = _ScriptedDB([{"rows": [_alert_row("A")], "page_size": 200}])
    hass = _Hass(db)
    led = L.OutageLedger(hass)
    led.arm()
    await hass.drain()
    assert led._alerts_seeded is True and "A" in led._seen_alerts
    led.cancel()


@pytest.mark.asyncio
async def test_cloud_seed_failure_retried_next_sweep(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    db = _ScriptedDB([{"rows": [], "error": "locked"}, {"rows": [], "page_size": 200}])
    hass, _ = _sweep_hass(_calendar_events(), db=db)
    led = L.OutageLedger(hass)
    assert await led.sweep(SWEEP_NOW) == 0
    assert led._cloud_seeded is False and db.rows == []
    assert await led.sweep(SWEEP_NOW) == 1
    assert led._cloud_seeded is True


@pytest.mark.asyncio
async def test_query_activities_reports_error(real_db, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _boom():
        raise RuntimeError("disk I/O error")
        yield  # pragma: no cover

    monkeypatch.setattr(real_db, "_db_read", _boom)
    res = await real_db.query_activities(action="nws_alert")
    assert res["rows"] == [] and "disk I/O error" in res["error"]
    monkeypatch.undo()
    assert "error" not in await real_db.query_activities(action="nws_alert")


# --------------------------------------------------------------------------
# A-L1: per-sensor minimum gap between local_only rows (30 min, rung 1)
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_local_only_min_gap_per_sensor():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    # Off-grid edges at +1, +3, +30 (29 min after the +1 row: suppressed)
    # and +31 (exactly 30 min after: written).
    seq = [(0, False), (1, True), (2, False), (3, True), (4, False),
           (30, True), (30.5, False), (31, True)]
    for m, r in seq:
        _tick(led, NOW + timedelta(minutes=m), local={GE: r})
    await hass.drain()
    rows = _rows(db, "grid_outage", witness="local_only")
    assert [r["timestamp"] for r in rows] == [
        (NOW + timedelta(minutes=1)).isoformat(),
        (NOW + timedelta(minutes=31)).isoformat(),
    ]
    assert json.loads(rows[0]["details_json"])["suppressed_since_last"] == 0
    assert json.loads(rows[1]["details_json"])["suppressed_since_last"] == 2
    # Suppressed edges still feed cloud corroboration.
    assert len(led._local_obs) == 4


@pytest.mark.asyncio
async def test_local_only_min_gap_is_per_sensor_not_global():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, local={GE: False, GS: False})
    _tick(led, NOW + timedelta(minutes=1), local={GE: True})
    _tick(led, NOW + timedelta(minutes=2), local={GS: True})
    await hass.drain()
    assert [r["entity_id"] for r in _rows(db, "grid_outage")] == [GE, GS]

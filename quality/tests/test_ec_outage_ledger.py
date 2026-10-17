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

import sys

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Import isolation (round 4). This file drives the REAL homeassistant +
# aiosqlite + URA modules. Many sibling files install stubs for those names
# in sys.modules (often with setdefault, never restored), so:
#   * importing real modules at collection time would leak them into every
#     file collected after this one (their setdefault stubs become no-ops);
#   * a stub installed by an earlier file would replace e.g.
#     `homeassistant.core.callback` with an identity function here.
# Therefore nothing real is imported at module top level. A module-scoped
# autouse fixture purges the affected namespaces, imports the real modules,
# binds the names below, and on teardown restores sys.modules EXACTLY
# (removes every key it added, puts back every key it replaced or purged).
# ---------------------------------------------------------------------------
_ISOLATED_PREFIXES = ("homeassistant", "custom_components", "aiosqlite")
UniversalRoomDatabase = None
L = None
EnergyCoordinator = None
BatteryStrategy = None
_CycleShell = None


def _purge(name: str, mod) -> bool:
    """Purge every URA module (an earlier file may have imported it against
    stubs) and every NON-REAL homeassistant/aiosqlite entry (a stub has no
    real file-backed spec). Real HA modules stay, so identities are shared
    with the pytest-homeassistant plugin (re-importing it breaks freezegun).
    """
    if not any(name == p or name.startswith(p + ".") for p in _ISOLATED_PREFIXES):
        return False
    if name == "custom_components" or name.startswith("custom_components."):
        return True
    if not isinstance(mod, types.ModuleType):
        return True
    spec = getattr(mod, "__spec__", None)
    origin = getattr(spec, "origin", None) if spec is not None else None
    return not (origin and os.path.exists(str(origin)))


_REPAIRED_HA_MODULES = (
    "homeassistant.core",
    "homeassistant.helpers.event",
    "homeassistant.helpers.entity_registry",
    "homeassistant.util.dt",
)


_MISSING = object()


def _package_module_attrs():
    """{(package name, attr): module} for every module-valued attribute of
    every isolated-namespace package. Importing `a.b.c` binds `c` on package
    `a.b`; removing `a.b.c` from sys.modules does NOT unbind it. A stale
    binding makes `from a.b import c` (and `mock.patch("a.b.c.x")`, which
    walks attributes) see a different object than `sys.modules["a.b.c"]`.
    """
    out = {}
    for name, mod in list(sys.modules.items()):
        if not isinstance(mod, types.ModuleType):
            continue
        if not any(name == p or name.startswith(p + ".") for p in _ISOLATED_PREFIXES):
            continue
        try:
            items = list(vars(mod).items())
        except TypeError:
            continue
        for attr, val in items:
            if isinstance(val, types.ModuleType):
                out[(name, attr)] = val
    return out


def _restore_package_module_attrs(before):
    after = _package_module_attrs()
    for key, val in after.items():
        if before.get(key, _MISSING) is val:
            continue
        pkg = sys.modules.get(key[0])
        if pkg is None:
            continue
        if key in before:
            setattr(pkg, key[1], before[key])
        else:
            delattr(pkg, key[1])
    for key, val in before.items():
        pkg = sys.modules.get(key[0])
        if key not in after and pkg is not None:
            setattr(pkg, key[1], val)


def _trace_fingerprint():
    mods = {}
    for name in _REPAIRED_HA_MODULES:
        m = sys.modules.get(name)
        if m is not None:
            mods[name] = {a: id(v) for a, v in vars(m).items()}
    pkg_attrs = {f"{p}.{a}": id(v) for (p, a), v in _package_module_attrs().items()}
    return {
        "sys.modules": {k: id(v) for k, v in sys.modules.items()},
        "package attrs": pkg_attrs,
        **mods,
    }


def _trace_diff(a, b):
    out = []
    for key in sorted(set(a) | set(b)):
        da, db = a.get(key, {}), b.get(key, {})
        for k in sorted(set(da) | set(db)):
            if da.get(k) != db.get(k):
                out.append(key + ":" + k)
    return out[:40]


def _repair_real_ha_modules(importlib, repairs):
    """Append (module, attr, previous_value) to ``repairs`` per repaired attribute.

    "Defined by the module" is read from a PRISTINE copy executed from HA's
    own source file (registered under a private name; removed on teardown).
    For each such attribute whose live value is not from the real module, the
    ORIGINAL object is recovered from any real HA module that imported it
    before the patch (keeps class identity, e.g. `Event`), else the pristine
    copy's object is used.
    """
    import importlib.util as _iu
    for modname in _REPAIRED_HA_MODULES:
        mod = importlib.import_module(modname)
        spec = _iu.spec_from_file_location(
            modname.rsplit(".", 1)[0] + "._ledger_pristine_" + modname.rsplit(".", 1)[1],
            mod.__spec__.origin,
        )
        pristine = _iu.module_from_spec(spec)
        sys.modules[spec.name] = pristine  # dataclasses need it registered
        spec.loader.exec_module(pristine)
        for attr, pval in vars(pristine).items():
            if attr.startswith("__") or getattr(pval, "__module__", None) != spec.name:
                continue  # not an object this module defines
            cur = getattr(mod, attr, _MISSING)
            if getattr(cur, "__module__", None) == modname:
                continue  # still the real one
            orig = next((
                getattr(m, attr) for n, m in list(sys.modules.items())
                if n.startswith("homeassistant") and n != spec.name
                and getattr(getattr(m, attr, None), "__module__", None) == modname
                and getattr(getattr(m, attr, None), "__name__", None) == attr
            ), None)
            repairs.append((mod, attr, cur))
            setattr(mod, attr, orig if orig is not None else pval)


@pytest.fixture(scope="module", autouse=True)
def _real_module_isolation():
    global UniversalRoomDatabase, L, EnergyCoordinator, BatteryStrategy, _CycleShell
    snapshot = dict(sys.modules)
    pkg_attrs_before = _package_module_attrs()
    trace_before = _trace_fingerprint()
    for name, mod in list(sys.modules.items()):
        if _purge(name, mod):
            del sys.modules[name]
    import importlib
    # Earlier files replace attributes ON the real HA modules and never put
    # them back (e.g. `ha_core.callback = lambda f: f`, a stub
    # `homeassistant.core.Event` from `_install_ha_stubs`, no-op timer helpers,
    # a fake `entity_registry.async_get`, a patched `dt.utcnow`). For every
    # real HA module this file exercises, restore EVERY attribute that the
    # module defines but whose current value no longer comes from it, for
    # the duration of this module, then put back exactly what was there.
    repairs: list = []
    try:
        _repair_real_ha_modules(importlib, repairs)
        UniversalRoomDatabase = importlib.import_module(
            "custom_components.universal_room_automation.database",
        ).UniversalRoomDatabase
        L = importlib.import_module(
            "custom_components.universal_room_automation.domain_coordinators."
            "energy_outage_ledger",
        )
        EnergyCoordinator = importlib.import_module(
            "custom_components.universal_room_automation.domain_coordinators.energy",
        ).EnergyCoordinator
        BatteryStrategy = importlib.import_module(
            "custom_components.universal_room_automation.domain_coordinators."
            "energy_battery",
        ).BatteryStrategy

        class _Cycle(EnergyCoordinator):
            def __init__(self):  # bypass heavy init
                pass

        _CycleShell = _Cycle
        yield
    finally:
        for mod, attr, val in reversed(repairs):
            # leave the environment exactly as we found it
            if val is _MISSING:
                delattr(mod, attr)
            else:
                setattr(mod, attr, val)
        for name in [n for n in sys.modules if n not in snapshot]:
            del sys.modules[name]
        sys.modules.update(snapshot)
        _restore_package_module_attrs(pkg_attrs_before)
        UniversalRoomDatabase = L = EnergyCoordinator = BatteryStrategy = None
        _CycleShell = None
    # Leave-no-trace check (round 6): the four HA modules' attribute
    # identities and the sys.modules key->object map must be exactly as found.
    diff = _trace_diff(trace_before, _trace_fingerprint())
    assert not diff, f"outage-ledger fixture left a trace: {diff}"

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


def _db_now():
    """The clock prune_activity_log reads (database.py's dt_util.utcnow).

    Seeds are aged against the SAME clock, so the test does not depend on
    whether an earlier file replaced `homeassistant.util.dt.utcnow`.
    """
    return sys.modules[UniversalRoomDatabase.__module__].dt_util.utcnow()


def _seed(db_file, action, importance, days_old):
    ts = (_db_now() - timedelta(days=days_old)).isoformat()
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
    # EC storm Stage B D-B2: the row now carries the product-table class/tier.
    assert d["ura_class"] == "notice" and d["ura_tier"] == "notice"
    assert d["local"] == "unknown"
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
    # Aged against the clock _outage_ledger_tick reads (energy's dt_util).
    from homeassistant.util import dt as _ha_dt
    stale = _ha_dt.now() - timedelta(hours=3)
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

    # load_registries=False: the registries are not under test, and an
    # earlier file may have replaced entity_registry.async_get on the real
    # module with a fake that has no async_load.
    async with async_test_home_assistant(load_registries=False) as hass:
        led = await _seeded(hass)
        ran = []
        loop_thread = threading.get_ident()

        async def _rec(now=None):
            ran.append(threading.get_ident())

        led.sweep = _rec
        assert led.arm() is True
        try:
            # Wall clock, not dt_util.utcnow: an earlier file may have replaced
            # utcnow on the real module; phcc compares against time.time().
            async_fire_time_changed(hass, datetime.now(timezone.utc) + timedelta(seconds=301))
            await hass.async_block_till_done()
            assert ran == [loop_thread]
            async_fire_time_changed(
                hass, datetime.now(timezone.utc) + timedelta(hours=24, seconds=5))
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


# --------------------------------------------------------------------------
# Review C survivors (S1-S16): discriminating tests
# --------------------------------------------------------------------------
def _no_end_alert(aid):
    a = _alert(aid)
    a.pop("Ends")
    a.pop("Expires")
    return a


@pytest.mark.asyncio
async def test_s1_present_alert_without_end_is_not_relogged():
    """A still-present alert with no end (or a past end) stays in the seen-set."""
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    past = _alert("P", ends="2026-10-16T11:00:00-05:00")  # already ended, still in feed
    for m in (0, 5, 10):
        _tick(led, NOW + timedelta(minutes=m), alerts=[_no_end_alert("N"), past])
    await hass.drain()
    assert sorted(json.loads(r["details_json"])["id"] for r in _rows(db, "nws_alert")) == ["N", "P"]


@pytest.mark.asyncio
async def test_s2_seen_alert_hard_ceiling(monkeypatch):
    monkeypatch.setattr(L, "OUTAGE_LEDGER_MAX_SEEN", 2)
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    _tick(led, NOW, alerts=[_alert("A"), _alert("B"), _alert("C")])  # all future-ended
    _tick(led, NOW + timedelta(minutes=5), alerts=[_alert("C")])
    assert len(led._seen_alerts) == 2
    assert "C" in led._seen_alerts  # a present key is never evicted
    assert "A" not in led._seen_alerts  # oldest-inserted absent key evicted first


@pytest.mark.asyncio
async def test_s3_cloud_seed_attempt_cap_then_sweeps_unseeded(monkeypatch, caplog):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    err = {"rows": [], "error": "locked"}
    db = _ScriptedDB([err, err, err])
    hass, _ = _sweep_hass(_calendar_events(), db=db)
    led = L.OutageLedger(hass)
    assert await led.sweep(SWEEP_NOW) == 0
    assert led._cloud_seed_attempts == 1
    assert await led.sweep(SWEEP_NOW) == 0
    assert led._cloud_seed_attempts == 2
    with caplog.at_level("WARNING"):
        assert await led.sweep(SWEEP_NOW) == 1  # 3rd failure: proceed unseeded
    assert led._cloud_seed_attempts == 3 and led._cloud_seeded is True
    assert any("seed failed 3 times" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_s4_cloud_seen_ceiling(monkeypatch):
    monkeypatch.setattr(L, "OUTAGE_LEDGER_MAX_SEEN", 1)
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    later = SEP16 + timedelta(hours=2)
    hass, db = _sweep_hass(_calendar_events() + [_ev(later, OFFGRID)])
    led = L.OutageLedger(hass)
    assert await led.sweep(SWEEP_NOW) == 2
    assert led._cloud_seen == {later.astimezone(timezone.utc).isoformat()}


@pytest.mark.asyncio
async def test_s5_suppressed_count_resets_after_each_row():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    seq = [(0, False), (1, True), (2, False), (3, True), (4, False),   # 1 suppressed
           (31, True), (32, False), (61, True)]                       # rows at 31, 61
    for m, r in seq:
        _tick(led, NOW + timedelta(minutes=m), local={GE: r})
    await hass.drain()
    counts = [json.loads(r["details_json"])["suppressed_since_last"]
              for r in _rows(db, "grid_outage", witness="local_only")]
    assert counts == [0, 1, 0]


@pytest.mark.asyncio
async def test_s6_false_none_true_is_one_transition():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    for i, r in enumerate([False, None, True]):
        _tick(led, NOW + timedelta(minutes=5 * i), local={GE: r})
    await hass.drain()
    rows = _rows(db, "grid_outage", witness="local_only")
    assert len(rows) == 1
    assert rows[0]["timestamp"] == (NOW + timedelta(minutes=10)).isoformat()


@pytest.mark.asyncio
async def test_s7_ongrid_generator_window_and_sort(monkeypatch):
    """Unsorted input; an on-grid event BEFORE the outage (must not be picked);
    a generator event before and one after the window (must be excluded)."""
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    t = SEP16
    events = [
        _ev(datetime(2026, 9, 16, 12, 57, 59, tzinfo=CDT), ONGRID),
        _ev(datetime(2026, 9, 16, 12, 52, 3, tzinfo=CDT), GEN_OFF),
        _ev(t, OFFGRID),
        _ev(datetime(2026, 9, 16, 15, 0, 0, tzinfo=CDT), GEN_ON),      # after reconnect
        _ev(datetime(2026, 9, 16, 9, 0, 0, tzinfo=CDT), ONGRID),       # before outage
        _ev(datetime(2026, 9, 16, 12, 43, 18, tzinfo=CDT), GEN_ON),
        _ev(datetime(2026, 9, 16, 8, 0, 0, tzinfo=CDT), GEN_OFF),      # before outage
        _ev(datetime(2026, 9, 16, 18, 0, 0, tzinfo=CDT), ONGRID),      # later reconnect
    ]
    hass, db = _sweep_hass(events)
    await L.OutageLedger(hass).sweep(SWEEP_NOW)
    await hass.drain()
    d = json.loads(_rows(db, "grid_outage", witness="cloud")[0]["details_json"])
    assert d["ongrid_at"] == "2026-09-16T12:57:59-05:00"
    assert d["generator_events"] == [
        {"start": "2026-09-16T12:43:18-05:00", "summary": GEN_ON},
        {"start": "2026-09-16T12:52:03-05:00", "summary": GEN_OFF},
    ]


@pytest.mark.asyncio
async def test_s8_sweep_timeout_bounds_a_hung_calendar(monkeypatch):
    _registry(monkeypatch, [(CAL, "enphase_ev")])
    hass, db = _sweep_hass([])
    monkeypatch.setattr(L, "OUTAGE_SWEEP_TIMEOUT_S", 0.05)
    never = asyncio.Event()

    async def _hang(*a, **k):
        await never.wait()

    hass.services.async_call = _hang
    led = L.OutageLedger(hass)
    # Must return on its own via the sweep timeout, well inside 2 s.
    assert await asyncio.wait_for(led.sweep(SWEEP_NOW), timeout=2) == 0


@pytest.mark.asyncio
async def test_s9_database_gone_after_seed_marks_nothing_seen():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    hass.data[DOMAIN]["database"] = None
    _tick(led, NOW, alerts=[_alert("A")])
    assert "A" not in led._seen_alerts
    hass.data[DOMAIN]["database"] = db
    _tick(led, NOW + timedelta(minutes=5), alerts=[_alert("A")])
    await hass.drain()
    assert len(_rows(db, "nws_alert")) == 1


@pytest.mark.asyncio
async def test_s10_cross_boot_alert_dedup_through_real_db(real_db):
    """Boot 1 writes through the real DAO; boot 2 seeds from the real table,
    whose query filters coordinator='energy' AND action='nws_alert'. A decoy
    row from another coordinator must not suppress alert B."""
    _seed(real_db.db_file, "nws_alert", "notable", 0)  # coordinator 'energy', no id: ignored
    conn = sqlite3.connect(real_db.db_file)
    conn.execute(
        "INSERT INTO ura_activity_log (timestamp, coordinator, action, importance,"
        " description, details_json) VALUES (?, 'presence', 'nws_alert', 'notable', 'x', ?)",
        (datetime.now(timezone.utc).isoformat(), json.dumps({"id": "B"})),
    )
    conn.commit()
    conn.close()
    now = datetime.now(timezone.utc)
    hass1 = _Hass(real_db)
    led1 = L.OutageLedger(hass1)
    await led1._seed_alerts(now)
    _tick(led1, now, alerts=[_alert("A")])
    await hass1.drain()
    stored = await real_db.query_activities(action="nws_alert", coordinator="energy",
                                            columns=("coordinator", "details_json"))
    assert [json.loads(r["details_json"]).get("id") for r in stored["rows"]
            if r["details_json"]].count("A") == 1
    hass2 = _Hass(real_db)
    led2 = L.OutageLedger(hass2)
    assert await led2._seed_alerts(now) is True
    _tick(led2, now, alerts=[_alert("A"), _alert("B")])
    await hass2.drain()
    after = await real_db.query_activities(action="nws_alert", coordinator="energy",
                                           columns=("details_json",))
    ids = sorted(json.loads(r["details_json"]).get("id") for r in after["rows"]
                 if r["details_json"])
    assert ids == ["A", "B"]


@pytest.mark.asyncio
async def test_s11_expires_fallback_keeps_unexpired_alert():
    db = _FakeDB()
    hass = _Hass(db)
    led = await _seeded(hass)
    a = _alert("E")
    a.pop("Ends")
    a["Expires"] = "2026-10-16T13:00:00-05:00"
    _tick(led, NOW, alerts=[a])
    _tick(led, NOW + timedelta(minutes=5), alerts=[])   # left the feed, not expired
    assert "E" in led._seen_alerts
    _tick(led, NOW + timedelta(minutes=10), alerts=[a])
    await hass.drain()
    assert len(_rows(db, "nws_alert")) == 1


@pytest.mark.asyncio
async def test_s13_only_one_sweep_in_flight():
    hass = _Hass(_FakeDB())
    led = L.OutageLedger(hass)
    gate = asyncio.Event()
    calls = []

    async def _slow(now=None):
        calls.append(1)
        await gate.wait()

    led.sweep = _slow
    led._spawn_sweep()
    first = led._sweep_task
    led._spawn_sweep()
    await asyncio.sleep(0)
    assert led._sweep_task is first and calls == [1]
    gate.set()
    await hass.drain()


@pytest.mark.asyncio
async def test_s14_cancel_stops_in_flight_alert_seed(monkeypatch):
    import importlib
    ev_mod = importlib.import_module("homeassistant.helpers.event")
    monkeypatch.setattr(ev_mod, "async_call_later", lambda h, d, cb: MagicMock())
    monkeypatch.setattr(ev_mod, "async_track_time_interval", lambda h, cb, i: MagicMock())
    gate = asyncio.get_running_loop().create_future()
    hass = _Hass(_ScriptedDB([gate]))
    led = L.OutageLedger(hass)
    led.arm()
    await asyncio.sleep(0)
    seed = led._alert_seed_task
    assert seed is not None and not seed.done()
    led.cancel()
    await asyncio.sleep(0)
    assert seed.cancelled()
    assert led._alert_seed_task is None


@pytest.mark.asyncio
async def test_s15_tick_threads_soc_and_decision_into_rows():
    db = _FakeDB()
    hass = _Hass(db)
    b = _battery_stub(
        hass, {"mode": "x", "reason": "", "actions": []},
        inc_dec=SimpleNamespace(tier="watch", hold_depth="partial_hold", reserve_floor=50),
        inc_at=datetime.now(timezone.utc),
    )
    b.battery_soc = 55
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    verifier = WriteVerifier.__new__(WriteVerifier)
    verifier.hass = hass
    c = _cycle(hass, b, verifier=verifier)
    await c._outage_ledger._seed_alerts(NOW)
    hass.states.d[GE] = _State("on")
    await c._decision_cycle_body()
    hass.states.d[GE] = _State("off")
    await c._decision_cycle_body()
    await hass.drain()
    rows = _rows(db, "grid_outage", witness="local_only")
    assert len(rows) == 1
    d = json.loads(rows[0]["details_json"])
    assert d["soc"] == 55
    assert (d["tier"], d["hold_depth"], d["reserve_floor"]) == ("watch", "partial_hold", 50)


def test_s16_energy_coordinator_init_builds_the_ledger():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    coord = EnergyCoordinator(
        hass=hass, reserve_soc=20, decision_interval=10,
        entity_config={}, tou_engine=MagicMock(name="tou_engine"),
    )
    assert isinstance(coord._outage_ledger, L.OutageLedger)
    assert coord._outage_ledger.hass is hass


# ===========================================================================
# EC storm Stage B — enclosing-method anchors for the three new per-tick
# hooks in the REAL `_decision_cycle_body` (`_inclement_rows_tick`,
# `_storm_guard_tick`, `_grid_buy_notify_tick`). Deleting a CALL in the body
# turns one of these RED. Lives here to reuse this file's module-isolation
# fixture and cycle harness.
# ===========================================================================
_SG = "switch.main_panel_wall_iq_gateway_hacs_storm_guard"


def _stage_b_setup(hass, **battery_attrs):
    b = _battery_stub(hass, {"mode": "self_consumption", "reason": "r",
                             "actions": []})
    b._inclement_pending_rows = []
    b._tick_grid_buy = None
    b._storm_guard_state = None
    for k, v in battery_attrs.items():
        setattr(b, k, v)
    c = _cycle(hass, b)
    nm = []

    async def _nm(**kw):
        nm.append(kw)
    c._send_nm_alert = _nm
    c._nm = nm
    c._storm_guard_eid = _SG
    return c, b


async def _stage_b_body(c, hass):
    await c._outage_ledger._seed_alerts(NOW)
    try:
        await c._decision_cycle_body()
    except _Stop:
        pass
    await hass.drain()


@pytest.mark.asyncio
async def test_cycle_body_drains_inclement_rows():
    db = _FakeDB()
    hass = _Hass(db)
    c, b = _stage_b_setup(hass, _inclement_pending_rows=[
        ("inclement_code_drift", "drift WSW", {"event": "Winter Storm Warning",
                                               "code": "WSW", "kind": "observed_code"}),
    ])
    await _stage_b_body(c, hass)
    rows = _rows(db, "inclement_code_drift")
    assert len(rows) == 1
    assert json.loads(rows[0]["details_json"])["code"] == "WSW"
    assert b._inclement_pending_rows == []


@pytest.mark.asyncio
async def test_cycle_body_runs_storm_guard_tripwire():
    db = _FakeDB()
    saved = []

    async def _save(ev):
        saved.append(ev)
    db.save_anomaly_event = _save
    hass = _Hass(db)
    c, b = _stage_b_setup(hass)
    hass.states.d[_SG] = _State("off")
    await _stage_b_body(c, hass)
    assert b._storm_guard_state == "off" and c._nm == []
    hass.states.d[_SG] = _State("on")
    await _stage_b_body(c, hass)
    assert len(c._nm) == 1 and c._nm[0]["title"] == "Enphase Storm Guard is on"
    assert [e.type for e in saved] == ["energy.storm_guard_enabled"]


@pytest.mark.asyncio
async def test_cycle_body_runs_grid_buy_notify():
    db = _FakeDB()
    hass = _Hass(db)
    c, b = _stage_b_setup(hass)
    await _stage_b_body(c, hass)          # first tick after setup: seeds, no buy
    b._tick_grid_buy = {"leg": "polygon", "alert_id": "svw",
                        "event": "Severe Thunderstorm Warning", "target": 90,
                        "forecast_confirmed": False}
    await _stage_b_body(c, hass)
    assert len(c._nm) == 1 and c._nm[0]["severity"] == "low"
    await _stage_b_body(c, hass)          # same episode → no second NM
    assert len(c._nm) == 1


@pytest.mark.asyncio
async def test_async_setup_runs_legacy_threat_list_check():
    """EC storm Stage B D-B5 call-site anchor: async_setup calls
    `_check_legacy_threat_list` (the repair-issue check)."""
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
    checked = []
    c._check_legacy_threat_list = lambda: checked.append(True)

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
    assert armed == [True] and checked == [True]

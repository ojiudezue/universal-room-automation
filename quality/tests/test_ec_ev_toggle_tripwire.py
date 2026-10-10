"""EC-EV-TOGGLE-TRIPWIRE-1 — behavioral tests.

Verifies the strategy EV-toggle flip-flop detector:
  (a) N+1 strategy toggles in <1h on one EVSE -> exactly one alert.
  (b) Toggles spread beyond the window -> no alert.
  (c) 4th/5th same-day toggle after first alert -> still one alert (latch).
  (d) Rolling into the next local day -> can alert again.
  (e) Plug toggles never count.
  (f) Force-charge-active toggles never count (exclusion).
  (g) Constant 0 disables (kill switch).
  (h) An exception inside the alert path does not propagate.

Wire-in anchor: `test_wire_in_through_execute_service_action` drives the
REAL `EnergyCoordinator._execute_service_action` method so a strategy
turn_on routed through the actuation path triggers the trip-wire. See
the mutation-drill note at the bottom.
"""
from __future__ import annotations

import asyncio
import types as _types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

import zoneinfo  # noqa: E402

from homeassistant.util import dt as dt_util  # noqa: E402

from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy as _e,
    energy_const as _ec,
    energy_write_verify as _wv,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
    SmartPlugController,
)


# ----- helpers -------------------------------------------------------------

class _StubActivityLogger:
    def __init__(self):
        self.calls: list[dict] = []

    async def log(self, **kw):
        self.calls.append(kw)


class _StubDatabase:
    def __init__(self):
        self.events: list = []

    async def save_anomaly_event(self, ev):
        self.events.append(ev)


class _Hass:
    def __init__(self, activity_logger=None, database=None):
        self.data = {DOMAIN: {}}
        if activity_logger is not None:
            self.data[DOMAIN]["activity_logger"] = activity_logger
        if database is not None:
            self.data[DOMAIN]["database"] = database
        self._states = {}
        self.states = MagicMock()
        self.states.get = lambda eid: self._states.get(eid)
        self.services = MagicMock()
        self._nm_calls: list = []

        async def _async_call(domain, svc, data, blocking=False):
            return None
        self.services.async_call = _async_call

    def async_create_task(self, coro, name=None):
        try:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
            if loop is not None and loop.is_running():
                return loop.create_task(coro)
            fresh = asyncio.new_event_loop()
            try:
                fresh.run_until_complete(coro)
            finally:
                fresh.close()
        except Exception:
            if hasattr(coro, "close"):
                try: coro.close()
                except Exception: pass


def _bind_verifier(hass, nm_sink: list):
    """Build a slim object with the fields `note_ev_toggle` + its
    helpers touch, and bind the real methods onto it. Avoids the heavy
    WriteVerifier.__init__ which pulls in oracle wiring we don't need."""
    coord_stub = _types.SimpleNamespace()

    async def _send_nm_alert(**kw):
        nm_sink.append(kw)
    coord_stub._send_nm_alert = _send_nm_alert
    coord_stub._battery = None  # _oracle_entity_for returns None safely

    v = _types.SimpleNamespace(
        hass=hass,
        _coord=coord_stub,
        _ev_toggle_stamps={},
        _ev_toggle_alarm_date={},
        _nm_trip_date_by_surface={},
    )
    v.note_ev_toggle = _wv.WriteVerifier.note_ev_toggle.__get__(v, type(v))
    v._emit_anomaly = _wv.WriteVerifier._emit_anomaly.__get__(v, type(v))
    v._maybe_fire_nm = _wv.WriteVerifier._maybe_fire_nm.__get__(v, type(v))
    v._oracle_entity_for = _wv.WriteVerifier._oracle_entity_for.__get__(v, type(v))
    return v


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ----- (a) exactly one alert on third toggle in window --------------------

def test_a_three_toggles_in_window_one_alert():
    db = _StubDatabase()
    hass = _Hass(database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)
    t0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    # Default max=2, window=3600 -> alert on 3rd toggle.
    _run(v.note_ev_toggle("evse_a", "charger_on", ["arbitrage"], now=t0))
    _run(v.note_ev_toggle("evse_a", "charger_off", ["arbitrage"], now=t0 + timedelta(seconds=600)))
    assert db.events == [] and nm == []
    _run(v.note_ev_toggle("evse_a", "charger_on", ["arbitrage"], now=t0 + timedelta(seconds=1200)))
    assert len(db.events) == 1
    assert db.events[0].type == "ev_toggle_tripwire"
    assert len(nm) == 1
    assert "evse_a" in nm[0]["title"]


# ----- (b) toggles beyond window never alert -----------------------------

def test_b_toggles_outside_window_no_alert():
    db = _StubDatabase()
    hass = _Hass(database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)
    t0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    _run(v.note_ev_toggle("evse_a", "charger_on", None, now=t0))
    _run(v.note_ev_toggle("evse_a", "charger_off", None, now=t0 + timedelta(seconds=3700)))
    _run(v.note_ev_toggle("evse_a", "charger_on", None, now=t0 + timedelta(seconds=7400)))
    assert db.events == [] and nm == []


# ----- (c) latch: subsequent same-day toggles do not re-alert -------------

def test_c_latch_same_day_single_alert():
    db = _StubDatabase()
    hass = _Hass(database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)
    t0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        _run(v.note_ev_toggle("evse_a", "charger_on", None,
                              now=t0 + timedelta(seconds=i * 300)))
    assert len(db.events) == 1
    assert len(nm) == 1


# ----- (d) next local day -> can alert again -----------------------------

def test_d_next_day_resets_latch(monkeypatch):
    """Rollover driven ONLY through the injected `now` — no manual
    writes to the latch dicts. Day 1 at 12:00 LOCAL (CDT), day 2 at
    12:00 LOCAL — the 24h gap evicts day-1 stamps via the rolling
    window and the local-day latch rolls to a new key naturally."""
    tz = zoneinfo.ZoneInfo("America/Chicago")
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", tz)
    db = _StubDatabase()
    hass = _Hass(database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)

    # Day 1 — local noon.
    day1_local = datetime(2026, 10, 5, 12, 0, tzinfo=tz)
    t0 = day1_local.astimezone(timezone.utc)
    for i in range(3):
        _run(v.note_ev_toggle("evse_a", "charger_on", None,
                              now=t0 + timedelta(seconds=i * 300)))
    assert len(db.events) == 1
    assert len(nm) == 1

    # Day 2 — local noon next day. +24h evicts day-1 stamps via the
    # 1h rolling window; LOCAL date key advances from 10-05 → 10-06.
    day2_local = datetime(2026, 10, 6, 12, 0, tzinfo=tz)
    t1 = day2_local.astimezone(timezone.utc)
    for i in range(3):
        _run(v.note_ev_toggle("evse_a", "charger_on", None,
                              now=t1 + timedelta(seconds=i * 300)))
    assert len(db.events) == 2, "anomaly must fire again on new local day"
    assert len(nm) == 2, "NM must fire again on new local day"


# ----- (d2) local-vs-UTC day boundary reproducer -------------------------

def test_d2_late_local_night_then_next_local_morning_fires_nm(monkeypatch):
    """A-MED-1 / B-LOW-1 reproducer. 23:00 local 10-05 CDT = 04:00Z 10-06;
    next flip-flop at 10:00 local 10-06 CDT = 15:00Z 10-06. Both are
    UTC date 10-06 (would have suppressed NM under the old UTC latch)
    but LOCAL dates 10-05 and 10-06 (so NM must fire on day 2)."""
    tz = zoneinfo.ZoneInfo("America/Chicago")
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", tz)
    db = _StubDatabase()
    hass = _Hass(database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)

    # Trip on local 10-05 23:00.
    t_night = datetime(2026, 10, 5, 23, 0, tzinfo=tz).astimezone(timezone.utc)
    for i in range(3):
        _run(v.note_ev_toggle("evse_a", "charger_on", None,
                              now=t_night + timedelta(seconds=i * 300)))
    assert len(db.events) == 1
    assert len(nm) == 1

    # Next local morning 10-06 10:00 — same UTC date (10-06), different local date.
    t_morning = datetime(2026, 10, 6, 10, 0, tzinfo=tz).astimezone(timezone.utc)
    for i in range(3):
        _run(v.note_ev_toggle("evse_a", "charger_on", None,
                              now=t_morning + timedelta(seconds=i * 300)))
    assert len(db.events) == 2, "second local day must emit a new anomaly"
    assert len(nm) == 2, (
        "NM must fire on the second local day (would be suppressed "
        "under the old UTC-keyed latch — repro of A-MED-1 / B-LOW-1)"
    )
    # Metadata (A LOW-1 / B LOW-3): hazard/location are EV-scoped.
    assert nm[-1]["hazard_type"] == "ev_toggle_tripwire"
    assert nm[-1]["location"] == "evse_a"


# ----- (e) plug toggles never count --------------------------------------
# Plug toggles never reach `note_ev_toggle` because the tap only invokes
# it when kind=="ev". This test exercises the TAP (through the real
# `_log_charger_actuation`) to prove plug targets don't fire the counter.

def test_e_plug_toggles_never_counted():
    hass = _Hass(activity_logger=_StubActivityLogger(), database=_StubDatabase())
    nm: list = []
    v = _bind_verifier(hass, nm)

    ev = EVChargerController(hass)
    plugs = SmartPlugController(
        hass,
        plug_entities=["switch.plug_a"],
        plug_config={"switch.plug_a": {}},
    )
    holder = _types.SimpleNamespace(
        hass=hass, _ev=ev, _smart_plugs=plugs, _write_verifier=v,
    )
    holder._execute_service_action = (
        _e.EnergyCoordinator._execute_service_action.__get__(holder, type(holder))
    )
    holder._log_charger_actuation = (
        _e.EnergyCoordinator._log_charger_actuation.__get__(holder, type(holder))
    )

    spec_on = {"service": "switch.turn_on", "target": "switch.plug_a", "data": {}}
    spec_off = {"service": "switch.turn_off", "target": "switch.plug_a", "data": {}}
    _run(holder._execute_service_action(spec_on))
    _run(holder._execute_service_action(spec_off))
    _run(holder._execute_service_action(spec_on))
    assert v._ev_toggle_stamps == {}
    assert hass.data[DOMAIN]["database"].events == []


# ----- (f) force-charge toggles never count ------------------------------

def test_f_force_charge_toggles_excluded():
    hass = _Hass(activity_logger=_StubActivityLogger(), database=_StubDatabase())
    nm: list = []
    v = _bind_verifier(hass, nm)

    ev = EVChargerController(hass)
    ev._evse = {"evse_a": {"switch": "switch.evse_a"}}
    # Force-charge active far in the future.
    ev._force_charge_until = datetime.now(timezone.utc) + timedelta(hours=4)

    plugs = SmartPlugController(hass, plug_entities=[], plug_config={})
    holder = _types.SimpleNamespace(
        hass=hass, _ev=ev, _smart_plugs=plugs, _write_verifier=v,
    )
    holder._execute_service_action = (
        _e.EnergyCoordinator._execute_service_action.__get__(holder, type(holder))
    )
    holder._log_charger_actuation = (
        _e.EnergyCoordinator._log_charger_actuation.__get__(holder, type(holder))
    )

    for spec in (
        {"service": "switch.turn_on", "target": "switch.evse_a", "data": {}},
        {"service": "switch.turn_off", "target": "switch.evse_a", "data": {}},
        {"service": "switch.turn_on", "target": "switch.evse_a", "data": {}},
    ):
        _run(holder._execute_service_action(spec))

    assert v._ev_toggle_stamps == {}
    assert hass.data[DOMAIN]["database"].events == []


# ----- (g) kill switch (constant 0 disables) -----------------------------

def test_g_kill_switch_disables(monkeypatch):
    monkeypatch.setattr(_ec, "DEFAULT_EV_TOGGLE_TRIPWIRE_MAX_PER_H", 0)
    db = _StubDatabase()
    hass = _Hass(database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)
    t0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    for i in range(10):
        _run(v.note_ev_toggle("evse_a", "charger_on", None,
                              now=t0 + timedelta(seconds=i * 60)))
    assert db.events == [] and nm == []


# ----- (h) exceptions never propagate ------------------------------------

def test_h_exception_in_alert_path_swallowed(monkeypatch):
    hass = _Hass(database=None)  # no database -> harmless path
    nm: list = []
    v = _bind_verifier(hass, nm)

    async def _boom(*a, **k):
        raise RuntimeError("induced")
    # Force the NM path to raise after threshold crossed.
    v._maybe_fire_nm = _boom
    t0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        # Must NOT raise.
        _run(v.note_ev_toggle("evse_a", "charger_on", None,
                              now=t0 + timedelta(seconds=i * 60)))


# ----- WIRE-IN ANCHOR -----------------------------------------------------
# Drives real `_execute_service_action` → `_log_charger_actuation` →
# `WriteVerifier.note_ev_toggle` and asserts the alert fires. Mutation
# drill: delete the `self._write_verifier.note_ev_toggle(...)` dispatch
# block in `_log_charger_actuation` → this test MUST turn RED.

def test_wire_in_through_execute_service_action():
    db = _StubDatabase()
    hass = _Hass(activity_logger=_StubActivityLogger(), database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)

    ev = EVChargerController(hass)
    ev._evse = {"evse_a": {"switch": "switch.evse_a"}}
    # Force-charge NOT active.
    ev._force_charge_until = None
    plugs = SmartPlugController(hass, plug_entities=[], plug_config={})

    holder = _types.SimpleNamespace(
        hass=hass, _ev=ev, _smart_plugs=plugs, _write_verifier=v,
    )
    holder._execute_service_action = (
        _e.EnergyCoordinator._execute_service_action.__get__(holder, type(holder))
    )
    holder._log_charger_actuation = (
        _e.EnergyCoordinator._log_charger_actuation.__get__(holder, type(holder))
    )

    # Three transitions in the window — the dedupe suppresses idempotent
    # repeats, so we alternate on/off/on to produce three real toggles.
    for spec in (
        {"service": "switch.turn_on", "target": "switch.evse_a", "data": {}},
        {"service": "switch.turn_off", "target": "switch.evse_a", "data": {}},
        {"service": "switch.turn_on", "target": "switch.evse_a", "data": {}},
    ):
        _run(holder._execute_service_action(spec))

    assert len(v._ev_toggle_stamps.get("evse_a", [])) >= 3, (
        "wire-in: note_ev_toggle must have been invoked by the tap"
    )
    assert len(db.events) == 1, (
        "wire-in: an ev_toggle_tripwire anomaly must be emitted "
        "end-to-end through _execute_service_action"
    )
    assert db.events[0].type == "ev_toggle_tripwire"


# ----- (i) idempotent turn_on repeats are deduped BEFORE the tap ---------

def test_i_repeated_same_action_counts_once():
    """A LOW-3: `_log_charger_actuation`'s per-target edge cache
    suppresses unchanged repeats, so `note_ev_toggle` sees only the
    first in a run of identical turn_on calls (so idempotent off-peak
    ensure-on re-issues cannot inflate the toggle count — Bug Class
    #43)."""
    db = _StubDatabase()
    hass = _Hass(activity_logger=_StubActivityLogger(), database=db)
    nm: list = []
    v = _bind_verifier(hass, nm)

    ev = EVChargerController(hass)
    ev._evse = {"evse_a": {"switch": "switch.evse_a"}}
    ev._force_charge_until = None
    plugs = SmartPlugController(hass, plug_entities=[], plug_config={})
    holder = _types.SimpleNamespace(
        hass=hass, _ev=ev, _smart_plugs=plugs, _write_verifier=v,
    )
    holder._execute_service_action = (
        _e.EnergyCoordinator._execute_service_action.__get__(holder, type(holder))
    )
    holder._log_charger_actuation = (
        _e.EnergyCoordinator._log_charger_actuation.__get__(holder, type(holder))
    )

    spec_on = {"service": "switch.turn_on", "target": "switch.evse_a", "data": {}}
    for _ in range(5):
        _run(holder._execute_service_action(spec_on))

    stamps = v._ev_toggle_stamps.get("evse_a", [])
    assert len(stamps) == 1, (
        f"idempotent turn_on repeats must dedupe before note_ev_toggle "
        f"(got {len(stamps)} stamps)"
    )
    assert db.events == []  # one stamp, below threshold

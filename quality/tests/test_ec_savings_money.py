"""EC-COST-AND-FORECAST-MATH-1 Build 1 — savings money + physics.

Spec: docs/planning/PLANNING_ec_savings_and_tomorrow_forecast.md rev 5 §13.

  D1  arbitrage savings accrue at DISCHARGE time on a B2 inventory basis
  D2  peak-avoidance credits zero battery kWh in every period (INV-SAV-1)
  D6  grid cost/hr priced on the EFFECTIVE import rate
  D7  forecasted import = max(consumption - production, 0)

Every test drives production code (real PeakAvoidanceTracker, real
EnergyCoordinator methods, real TOURateEngine, real UniversalRoomDatabase).
Oracles are hand-derived from literal rates below — never from the code
under test. The test rate table is local (not PEC_TOU_RATES) so a change to
the built-in table cannot move an oracle.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import homeassistant.util.dt as dt_util  # real HA (.venv-ha)

from custom_components.universal_room_automation.domain_coordinators.energy import (
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
    ArbitrageInventory,
    PeakAvoidanceTracker,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

# ---------------------------------------------------------------------------
# Literal rate fixture (shoulder-shaped). Effective = base + 0.022546 +
# 0.019930 = base + 0.042476.
#   off_peak base 0.043481 -> effective 0.085957 ; export 0.043481
#   mid_peak base 0.086442 -> effective 0.128918
# ---------------------------------------------------------------------------
_FIXED = {
    "service_availability": 32.50,
    "delivery_per_kwh": 0.022546,
    "transmission_per_kwh": 0.019930,
}


def _table(off_import=0.043481, mid_import=0.086442, export=0.043481):
    season = {
        "months": list(range(1, 13)),
        "periods": {
            "off_peak": {
                "hours": [(0, 17), (21, 24)],
                "import_rate": off_import,
                "export_rate": export,
            },
            "mid_peak": {
                "hours": [(17, 21)],
                "import_rate": mid_import,
                "export_rate": export,
            },
        },
    }
    return {"shoulder": season}


def _engine(**kw) -> TOURateEngine:
    return TOURateEngine(rate_table=_table(**kw), fixed_charges=dict(_FIXED))


_MID = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)   # hour 18 -> mid_peak
_OFF = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)    # hour 2  -> off_peak
_DOMAIN = "universal_room_automation"


class _FakeDB:
    """Records arbitrage rows + a dict-backed energy_state store."""

    def __init__(self, state=None, aged=None):
        self.rows: list[dict] = []
        self.state: dict[str, str] = dict(state or {})
        # keys whose stored value is "older than max_age"
        self.aged: set[str] = set(aged or ())
        self.saves: list[str] = []

    async def save_arbitrage_cycle(self, **kw):
        self.rows.append(kw)

    async def save_energy_state(self, key, value):
        self.saves.append(key)
        self.state[key] = value

    async def restore_energy_state(self, key):
        return self.state.get(key)

    async def restore_energy_state_with_age(self, key, max_age_hours=10.0):
        if key in self.aged:
            return None
        return self.state.get(key)


def _mk_ec(db=None, soc=50.0, cap=40.0, tou=None, inventory=None):
    c = EnergyCoordinator.__new__(EnergyCoordinator)
    c.hass = SimpleNamespace(data={_DOMAIN: {"database": db}})
    c._tou = tou or _engine()
    c._battery = SimpleNamespace(
        battery_soc=soc,
        _get_entity=lambda key: None,
        solar_production_w=None,
        battery_power_w=None,
    )
    c._cached_battery_capacity_kwh = cap
    c._arb_inventory = inventory if inventory is not None else ArbitrageInventory()
    c._arb_inventory_loaded = inventory is not None
    c._arb_inventory_changed_ticks = 0
    c._peak_avoidance = PeakAvoidanceTracker(MagicMock())
    c._savings_baselines_loaded = True
    c._billing = SimpleNamespace(_get_net_power=lambda: None)
    return c


def _tick(**kw):
    base = {
        "elapsed_h": 5 / 60,
        "charge_kwh_grid": 0.0,
        "charge_kwh_solar": 0.0,
        "charge_kwh_unsplit": 0.0,
        "discharge_kwh": 0.0,
        "battery_served_kwh": 0.0,
    }
    base.update(kw)
    return base


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _drive_pa(c, monkeypatch, now, *, solar_w, battery_w, net_kw, period):
    """Drive the ENCLOSING method _accumulate_peak_avoidance at `now`."""
    c._battery.solar_production_w = solar_w
    c._battery.battery_power_w = battery_w
    c._billing = SimpleNamespace(_get_net_power=lambda: net_kw)
    # Resolve dt exactly as production does AT CALL TIME
    # (`from homeassistant.util import dt`): a sibling file may have rebound
    # homeassistant.util.dt after this module's top-level import, so patching
    # the collection-time `dt_util` would miss the object production reads.
    from homeassistant.util import dt as _live_dtu
    monkeypatch.setattr(_live_dtu, "now", lambda *a, **k: now)
    _run(c._accumulate_peak_avoidance(period, "shoulder"))


# ---------------------------------------------------------------------------
# D1 — inventory basis + discharge accrual
# ---------------------------------------------------------------------------


def test_arbitrage_discharge_accrual_inventory_basis():
    """§D1 Verify: 15 grid kWh @0.085957 + 5 solar kWh @0.043481 = 20 kWh,
    $1.506760 (avg 0.075338). Mid-peak 5 kW x 5 min = 0.416667 kWh served
    at effective 0.128918 -> 0.416667 x (0.128918 - 0.075338/0.9)."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, cap=40.0, inventory=ArbitrageInventory())
    # charge via the real apply path (grid at off-peak effective, solar at
    # off-peak export) — rates come from the engine at the charge tick.
    _run(c._apply_arbitrage_tick(
        _tick(charge_kwh_grid=15.0, charge_kwh_solar=5.0), "off_peak",
        "shoulder", _OFF,
    ))
    assert c._arb_inventory.kwh == pytest.approx(20.0)
    assert c._arb_inventory.cost_usd == pytest.approx(1.506760, abs=1e-6)
    assert db.rows == []  # charge ticks write no savings row

    served = 5.0 * 5 / 60
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=served, battery_served_kwh=served), "mid_peak",
        "shoulder", _MID,
    ))
    assert len(db.rows) == 1
    row = db.rows[0]
    expected = 0.4166667 * (0.128918 - 0.0753380 / 0.9)
    assert row["savings"] == pytest.approx(expected, abs=1e-6)
    assert row["savings"] == pytest.approx(0.018837, abs=1e-5)
    assert row["accrual"] == "discharge"
    assert row["kwh_charged"] == 0.0
    assert row["kwh_discharged"] == pytest.approx(0.4166667, abs=1e-6)
    assert row["basis_source"] == "inventory"
    assert row["displaced_rate"] == pytest.approx(0.128918, abs=1e-9)
    assert row["off_peak_rate"] == pytest.approx(0.075338, abs=1e-6)
    # inventory dropped by the discharged kWh at the average basis
    assert c._arb_inventory.kwh == pytest.approx(20.0 - 0.4166667, abs=1e-6)
    assert c._arb_inventory.cost_usd == pytest.approx(
        1.506760 - 0.4166667 * 0.075338, abs=1e-5,
    )


def test_arbitrage_discharge_grid_only_basis_discriminates_b1():
    """§D1 discriminating Verify: grid-only inventory (avg 0.085957) books
    0.416667 x (0.128918 - 0.085957/0.9) = $0.01392."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(20.0, 20.0 * 0.085957))
    served = 0.4166667
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=served, battery_served_kwh=served), "mid_peak",
        "shoulder", _MID,
    ))
    assert db.rows[0]["savings"] == pytest.approx(
        0.4166667 * (0.128918 - 0.085957 / 0.9), abs=1e-6,
    )
    assert db.rows[0]["savings"] == pytest.approx(0.013916, abs=1e-5)


def test_arbitrage_base_rate_spread_clamps_no_row():
    """A base-rate-vs-effective mix (basis above displaced/RTE) clamps to 0
    and writes no row."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(10.0, 10.0 * 0.12))
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=0.5, battery_served_kwh=0.5), "mid_peak",
        "shoulder", _MID,
    ))
    assert db.rows == []
    assert c._arb_inventory.kwh == pytest.approx(9.5)


def test_discharge_savings_clamped_at_zero():
    from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
        discharge_savings_usd,
    )
    assert discharge_savings_usd(1.0, 0.10, 0.12, 0.9) == 0.0
    assert discharge_savings_usd(1.0, 0.128918, 0.06, 0.9) == pytest.approx(
        0.128918 - 0.06 / 0.9)


def test_arbitrage_charge_split_grid_solar():
    """§D1 Verify: charge 4 kW + net import 1.5 kW -> grid 1.5, solar 2.5.
    Exporting (net -2 kW) -> grid 0, solar 4. Driven through the real
    tracker (the single integrator)."""
    t = PeakAvoidanceTracker(MagicMock())
    t0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    assert t.accumulate(now=t0, solar_kw=3.0, battery_power_kw=4.0,
                        net_import_kw=1.5, effective_rate=0.1) is None
    tick = t.accumulate(now=t0 + timedelta(hours=1), solar_kw=3.0,
                        battery_power_kw=4.0, net_import_kw=1.5,
                        effective_rate=0.1)
    assert tick["charge_kwh_grid"] == pytest.approx(1.5)
    assert tick["charge_kwh_solar"] == pytest.approx(2.5)
    tick2 = t.accumulate(now=t0 + timedelta(hours=2), solar_kw=7.0,
                         battery_power_kw=4.0, net_import_kw=-2.0,
                         effective_rate=0.1)
    assert tick2["charge_kwh_grid"] == pytest.approx(0.0)
    assert tick2["charge_kwh_solar"] == pytest.approx(4.0)


def test_arbitrage_inventory_fills_on_grid_only_charge(monkeypatch):
    """F1: solar 0, house 0.5 kW, charge 5 kW, net +5.5 kW, served 0. The
    served noise-floor gate must NOT block the fill: inv grows by 5 x dt at
    the off-peak effective rate. Driven through _accumulate_peak_avoidance."""
    c = _mk_ec(soc=100.0, cap=40.0, inventory=ArbitrageInventory())
    _drive_pa(c, monkeypatch, _OFF, solar_w=0.0, battery_w=5000.0,
              net_kw=5.5, period="off_peak")
    _drive_pa(c, monkeypatch, _OFF + timedelta(minutes=5), solar_w=0.0,
              battery_w=5000.0, net_kw=5.5, period="off_peak")
    assert c._arb_inventory.kwh == pytest.approx(5.0 * 5 / 60, abs=1e-9)
    assert c._arb_inventory.cost_usd == pytest.approx(
        5.0 * 5 / 60 * 0.085957, abs=1e-9,
    )


def test_arbitrage_inventory_net_none_books_offpeak_basis(monkeypatch):
    """net unknown during a charge: kWh go in at the off-peak effective
    basis (no split possible), and discharge still drains."""
    c = _mk_ec(soc=100.0, inventory=ArbitrageInventory())
    # mid-peak clock so a wrongly-used live import rate (0.128918) differs
    # from the off-peak basis (0.085957)
    _drive_pa(c, monkeypatch, _MID, solar_w=0.0, battery_w=6000.0,
              net_kw=None, period="mid_peak")
    _drive_pa(c, monkeypatch, _MID + timedelta(minutes=10), solar_w=0.0,
              battery_w=6000.0, net_kw=None, period="mid_peak")
    kwh = 6.0 * 10 / 60
    assert c._arb_inventory.kwh == pytest.approx(kwh)
    assert c._arb_inventory.cost_usd == pytest.approx(kwh * 0.085957, abs=1e-9)
    # discharge with net unknown still drains (no savings row possible)
    _drive_pa(c, monkeypatch, _MID + timedelta(minutes=15), solar_w=0.0,
              battery_w=-3000.0, net_kw=None, period="mid_peak")
    assert c._arb_inventory.kwh == pytest.approx(kwh - 3.0 * 5 / 60)


def test_arbitrage_grid_charge_priced_at_live_effective_rate():
    """Grid kWh are booked at the effective import rate OF THEIR CHARGE
    TICK (here mid_peak 0.128918), not the off-peak rate (#63 guard: the
    two coincide for ordinary off-peak charging)."""
    c = _mk_ec(soc=100.0, inventory=ArbitrageInventory())
    _run(c._apply_arbitrage_tick(_tick(charge_kwh_grid=2.0), "mid_peak",
                                 "shoulder", _MID))
    assert c._arb_inventory.cost_usd == pytest.approx(2.0 * 0.128918, abs=1e-9)


def test_apply_tick_restores_inventory_before_first_apply():
    """Wire-in: the first applied tick loads the persisted inventory first
    (5 kWh @ 0.06) and accrues against IT, not an empty/seeded one."""
    db = _FakeDB({"arbitrage_inventory": json.dumps(
        {"kwh": 5.0, "cost_usd": 0.30, "updated_at": "x"})})
    c = _mk_ec(db=db, soc=100.0, cap=40.0)
    assert c._arb_inventory_loaded is False
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=1.0, battery_served_kwh=1.0), "mid_peak",
        "shoulder", _MID,
    ))
    assert db.rows[0]["basis_source"] == "inventory"
    assert db.rows[0]["savings"] == pytest.approx(0.128918 - 0.06 / 0.9, abs=1e-6)
    assert c._arb_inventory.kwh == pytest.approx(4.0)


def test_arbitrage_offpeak_discharge_zero_but_drains_inventory():
    # Solar-cheap basis 0.043481: an off-peak spread (0.085957 -
    # 0.043481/0.9 > 0) WOULD be positive, so only the period gate keeps
    # the row out.
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0,
               inventory=ArbitrageInventory(10.0, 10.0 * 0.043481))
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=1.0, battery_served_kwh=1.0), "off_peak",
        "shoulder", _OFF,
    ))
    assert db.rows == []
    assert c._arb_inventory.kwh == pytest.approx(9.0)
    assert c._arb_inventory.cost_usd == pytest.approx(9.0 * 0.043481)


def test_arbitrage_empty_inventory_fallback():
    """Empty inventory -> off-peak effective basis, basis_source
    'empty_fallback'. 1 kWh at mid 0.128918 - 0.085957/0.9."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(0.05, 0.001))
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=1.0, battery_served_kwh=1.0), "mid_peak",
        "shoulder", _MID,
    ))
    assert db.rows[0]["basis_source"] == "empty_fallback"
    assert db.rows[0]["savings"] == pytest.approx(
        0.128918 - 0.085957 / 0.9, abs=1e-6,
    )


def test_arbitrage_inventory_restore_and_seed():
    """Restore a valid key verbatim; missing / corrupt / aged -> seed
    SOC x capacity (40% x 40 = 16 kWh) at the off-peak effective basis."""
    good = json.dumps({"kwh": 7.5, "cost_usd": 0.6, "updated_at": "x"})
    c = _mk_ec(db=_FakeDB({"arbitrage_inventory": good}), soc=40.0, cap=40.0)
    _run(c._ensure_arbitrage_inventory_loaded(_OFF))
    assert (c._arb_inventory.kwh, c._arb_inventory.cost_usd) == (7.5, 0.6)

    for db in (
        _FakeDB(),
        _FakeDB({"arbitrage_inventory": "{not json"}),
        _FakeDB({"arbitrage_inventory": good}, aged={"arbitrage_inventory"}),
    ):
        c = _mk_ec(db=db, soc=40.0, cap=40.0)
        _run(c._ensure_arbitrage_inventory_loaded(_OFF))
        assert c._arb_inventory.kwh == pytest.approx(16.0)
        assert c._arb_inventory.cost_usd == pytest.approx(16.0 * 0.085957)


def test_arbitrage_inventory_soc_cap_scales_cost():
    """SOC cap 10 kWh (25% x 40) on 14 kWh / $1.12 -> 10 kWh / $0.80."""
    c = _mk_ec(soc=25.0, cap=40.0, inventory=ArbitrageInventory(14.0, 1.12))
    _run(c._apply_arbitrage_tick(_tick(discharge_kwh=0.0), "off_peak",
                                 "shoulder", _OFF))
    assert c._arb_inventory.kwh == pytest.approx(10.0)
    assert c._arb_inventory.cost_usd == pytest.approx(0.80)


def test_arbitrage_inventory_survives_midnight(monkeypatch):
    """No midnight reset: inventory carries across a local-date change."""
    c = _mk_ec(soc=100.0, inventory=ArbitrageInventory(12.0, 1.0))
    t1 = datetime(2026, 11, 2, 23, 55, tzinfo=timezone.utc)
    _drive_pa(c, monkeypatch, t1, solar_w=0.0, battery_w=0.0, net_kw=1.0,
              period="off_peak")
    _drive_pa(c, monkeypatch, t1 + timedelta(minutes=10), solar_w=0.0,
              battery_w=0.0, net_kw=1.0, period="off_peak")
    assert c._arb_inventory.kwh == pytest.approx(12.0)
    assert c._arb_inventory.cost_usd == pytest.approx(1.0)


def test_arbitrage_no_charge_time_savings_after_cutover():
    """INV-SAV-1: an arbitrage CHARGE tick with rising SOC writes no row."""
    db = _FakeDB()
    c = _mk_ec(db=db)
    c._arbitrage_prev_soc = 40.0
    _run(c._account_arbitrage_cycle(
        {"arbitrage_phase": "charge", "soc": 45.0}, "off_peak", "shoulder",
    ))
    assert db.rows == []
    assert c._arbitrage_prev_soc == 45.0


def test_arbitrage_cutover_key_written_once():
    db = _FakeDB({"arbitrage_discharge_cutover_ts": "2026-11-01T00:00:00+00:00"})
    c = _mk_ec(db=db)
    _run(c._ensure_arbitrage_inventory_loaded(_OFF))
    assert db.state["arbitrage_discharge_cutover_ts"] == "2026-11-01T00:00:00+00:00"
    db2 = _FakeDB()
    c2 = _mk_ec(db=db2)
    _run(c2._ensure_arbitrage_inventory_loaded(_OFF))
    first = db2.state["arbitrage_discharge_cutover_ts"]
    assert first
    c2._arb_inventory_loaded = False
    _run(c2._ensure_arbitrage_inventory_loaded(_OFF + timedelta(hours=3)))
    assert db2.state["arbitrage_discharge_cutover_ts"] == first
    assert db2.saves.count("arbitrage_discharge_cutover_ts") == 1


def test_arbitrage_follows_tou_rate_change_without_restart():
    """INV-RATE-1: swapping the engine schedule moves the next accrual."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(20.0, 20 * 0.085957))
    c._tou = _engine(mid_import=0.20)  # mid effective 0.242476
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=1.0, battery_served_kwh=1.0), "mid_peak",
        "shoulder", _MID,
    ))
    assert db.rows[0]["savings"] == pytest.approx(
        0.242476 - 0.085957 / 0.9, abs=1e-6,
    )


def test_arbitrage_inventory_persist_cadence():
    """Persist on every 3rd CHANGED tick (no per-tick flood); idle ticks
    do not count."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(5.0, 0.4))
    for _ in range(2):
        _run(c._apply_arbitrage_tick(_tick(charge_kwh_grid=0.1), "off_peak",
                                     "shoulder", _OFF))
    _run(c._apply_arbitrage_tick(_tick(), "off_peak", "shoulder", _OFF))
    assert "arbitrage_inventory" not in db.saves
    _run(c._apply_arbitrage_tick(_tick(charge_kwh_grid=0.1), "off_peak",
                                 "shoulder", _OFF))
    assert db.saves.count("arbitrage_inventory") == 1
    saved = json.loads(db.state["arbitrage_inventory"])
    assert saved["kwh"] == pytest.approx(5.3)


def test_arbitrage_inventory_saved_at_unload():
    db = _FakeDB()
    c = _mk_ec(db=db, inventory=ArbitrageInventory(3.0, 0.3))
    for name in (
        "_save_evse_state", "_save_power_profiles", "_save_circuit_state",
        "_save_energy_baselines", "_save_envoy_cache",
        "_save_midnight_snapshot", "_save_load_shedding_level",
    ):
        async def _noop():
            return None
        setattr(c, name, _noop)
    c._peak_import_history = []
    _run(c._async_persist_state())
    assert json.loads(db.state["arbitrage_inventory"])["kwh"] == 3.0


# ---------------------------------------------------------------------------
# D2 — peak-avoidance double-count guard
# ---------------------------------------------------------------------------


def _pa_hour(period, *, solar_kw, battery_kw, net_kw, rate):
    t = PeakAvoidanceTracker(MagicMock())
    base = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
    for i in range(13):
        t.accumulate(now=base + timedelta(minutes=5 * i), solar_kw=solar_kw,
                     battery_power_kw=battery_kw, net_import_kw=net_kw,
                     effective_rate=rate, period=period)
    return t


def test_peak_avoidance_zero_battery_credit_all_periods():
    for period in ("mid_peak", "peak", "off_peak"):
        t = _pa_hour(period, solar_kw=0.0, battery_kw=-5.0, net_kw=0.0, rate=0.128918)
        assert t.peak_avoidance_today == 0.0, period
        # kWh avoided is still counted (display), only $ is zero
        assert t.kwh_avoided_today == pytest.approx(5.0, abs=1e-6)
    # solar-served credit unchanged: 2 kW x 1 h x 0.128918
    t = _pa_hour("mid_peak", solar_kw=2.0, battery_kw=-1.0, net_kw=0.0, rate=0.128918)
    assert t.peak_avoidance_today == pytest.approx(0.2578, abs=1e-4)


def test_savings_total_no_double_count_displaced_tick(monkeypatch):
    """INV-SAV-1 end to end: one displaced tick, 5 kW battery-served, 0
    solar -> PA +$0 and arbitrage +0.416667 x (0.128918 - 0.085957/0.9)."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(20.0, 20 * 0.085957))
    _drive_pa(c, monkeypatch, _MID, solar_w=0.0, battery_w=-5000.0,
              net_kw=0.0, period="mid_peak")
    _drive_pa(c, monkeypatch, _MID + timedelta(minutes=5), solar_w=0.0,
              battery_w=-5000.0, net_kw=0.0, period="mid_peak")
    assert c._peak_avoidance.peak_avoidance_today == 0.0
    assert len(db.rows) == 1
    assert db.rows[0]["savings"] == pytest.approx(
        0.4166667 * (0.128918 - 0.085957 / 0.9), abs=1e-6,
    )


# ---------------------------------------------------------------------------
# DB — migration + readers (real UniversalRoomDatabase, real migration)
# ---------------------------------------------------------------------------


async def _real_db(tmp_path, pre_ddl: str | None = None, legacy_rows=()):
    import os
    import sqlite3
    from custom_components.universal_room_automation.const import (
        DATABASE_DIR, DATABASE_NAME,
    )
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass

    if pre_ddl is not None:
        d = os.path.join(str(tmp_path), DATABASE_DIR)
        os.makedirs(d, exist_ok=True)
        con = sqlite3.connect(os.path.join(d, DATABASE_NAME))
        con.execute(pre_ddl)
        for r in legacy_rows:
            con.execute(
                "INSERT INTO arbitrage_cycles (timestamp, soc_before, "
                "soc_after, kwh_charged, off_peak_rate, displaced_rate, "
                "round_trip_efficiency, savings, season) VALUES "
                "(?,?,?,?,?,?,?,?,?)", r,
            )
        con.commit()
        con.close()
    db = UniversalRoomDatabase(StubHass(config_dir=str(tmp_path)))
    assert await db.initialize()
    await db.start_write_worker()
    return db


async def _drain(db):
    for _ in range(40):
        if db._write_queue.empty():
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.05)


_LEGACY_DDL = """CREATE TABLE arbitrage_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    soc_before REAL, soc_after REAL,
    kwh_charged REAL NOT NULL,
    off_peak_rate REAL NOT NULL,
    displaced_rate REAL NOT NULL,
    round_trip_efficiency REAL NOT NULL DEFAULT 0.90,
    savings REAL NOT NULL,
    season TEXT)"""


@pytest.mark.asyncio
async def test_arbitrage_cycles_migration_adds_columns(tmp_path):
    """Pre-existing legacy table + row -> production migration adds the 3
    columns; legacy row reads accrual='charge'. Re-init is idempotent."""
    import aiosqlite
    db = await _real_db(
        tmp_path, _LEGACY_DDL,
        [("2026-10-30T23:00:00+00:00", 40, 50, 4.0, 0.08, 0.12, 0.9, 0.0005, "shoulder")],
    )
    try:
        async with aiosqlite.connect(db.db_file) as con:
            cols = {r[1]: r for r in await (await con.execute(
                "PRAGMA table_info(arbitrage_cycles)")).fetchall()}
            assert {"accrual", "kwh_discharged", "basis_source"} <= set(cols)
            acc = await (await con.execute(
                "SELECT accrual FROM arbitrage_cycles")).fetchall()
            assert acc == [("charge",)]
    finally:
        await db.stop_write_worker()
    # idempotent second initialize
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass
    db2 = UniversalRoomDatabase(StubHass(config_dir=str(tmp_path)))
    assert await db2.initialize()


@pytest.mark.asyncio
async def test_arbitrage_readers_discharge_rows(tmp_path):
    """F4: today/cycle `kwh_discharged`; last_cycle + pace filter."""
    now = dt_util.utcnow()
    legacy_ts = (now - timedelta(hours=2)).isoformat()
    db = await _real_db(
        tmp_path, _LEGACY_DDL,
        [(legacy_ts, 40, 50, 4.0, 0.08, 0.12, 0.9, 0.0005, "shoulder")],
    )
    try:
        for i, (kwh, sav) in enumerate(((0.4, 0.02), (0.3, 0.015))):
            await db.save_arbitrage_cycle(
                timestamp=(now - timedelta(minutes=30 - i)).isoformat(),
                soc_before=None, soc_after=None, kwh_charged=0.0,
                off_peak_rate=0.075, displaced_rate=0.128918,
                round_trip_efficiency=0.9, savings=sav, season="shoulder",
                accrual="discharge", kwh_discharged=kwh,
                basis_source="inventory",
            )
        # a later legacy charge row: the newest id overall is NOT discharge
        await db.save_arbitrage_cycle(
            timestamp=(now - timedelta(minutes=5)).isoformat(),
            soc_before=50, soc_after=51, kwh_charged=0.4, off_peak_rate=0.08,
            displaced_rate=0.12, round_trip_efficiency=0.9, savings=0.0001,
            season="shoulder",
        )
        await _drain(db)
        since = (now - timedelta(hours=6)).isoformat()
        today = await db.query_arbitrage_savings_since(since, accrual="discharge")
        assert today["savings"] == pytest.approx(0.035)
        assert today["kwh_discharged"] == pytest.approx(0.7)
        # A1/B3: two discharge rows on ONE local day = 1 cycle, 2 ticks.
        assert today["cycles"] == 1
        assert today["rows"] == 2
        unfiltered = await db.query_arbitrage_savings_since(since)
        assert unfiltered["savings"] == pytest.approx(0.0356)
        total = await db.query_arbitrage_savings_total()
        assert total["kwh_charged"] == pytest.approx(4.4)
        assert total["kwh_discharged"] == pytest.approx(0.7)
        assert total["savings"] == pytest.approx(0.0356)
        last = await db.query_arbitrage_last_cycle(accrual="discharge")
        assert last["accrual"] == "discharge"
        assert last["kwh_discharged"] == pytest.approx(0.3)
        assert last["basis_source"] == "inventory"
        pace = await db.query_arbitrage_pace_recent(days=7, accrual="discharge")
        assert pace["avg_savings_per_day"] == pytest.approx(0.035)
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_arbitrage_sums_never_reprice_stored_rates(tmp_path):
    """INV-RATE-1: sums return SUM(savings) only. A row whose stored rate
    columns imply a different value still sums to its `savings`."""
    db = await _real_db(tmp_path)
    try:
        await db.save_arbitrage_cycle(
            timestamp=dt_util.utcnow().isoformat(), soc_before=None,
            soc_after=None, kwh_charged=0.0, off_peak_rate=0.01,
            displaced_rate=9.99, round_trip_efficiency=0.9, savings=0.0123,
            season="shoulder", accrual="discharge", kwh_discharged=1.0,
            basis_source="inventory",
        )
        await _drain(db)
        since = (dt_util.utcnow() - timedelta(hours=1)).isoformat()
        assert (await db.query_arbitrage_savings_since(
            since, accrual="discharge"))["savings"] == pytest.approx(0.0123)
        assert (await db.query_arbitrage_savings_total())["savings"] == pytest.approx(0.0123)
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_refresh_cache_filters_discharge_accrual():
    """Wire-in: _refresh_arbitrage_status_cache passes accrual='discharge'
    to today/cycle/last/pace and none to total."""
    calls: dict[str, object] = {}

    class _DB:
        async def query_arbitrage_savings_since(self, since, accrual=None):
            calls.setdefault("since", []).append(accrual)
            return {"savings": 1.0}

        async def query_arbitrage_savings_total(self):
            calls["total"] = True
            return {}

        async def query_arbitrage_last_cycle(self, accrual=None):
            calls["last"] = accrual
            return None

        async def query_arbitrage_pace_recent(self, days=7, accrual=None):
            calls["pace"] = accrual
            return {}

    c = _mk_ec(db=_DB())
    c._arbitrage_status_cache = {}
    c.__dict__["_billing"] = SimpleNamespace(get_status=lambda: {})
    await c._refresh_arbitrage_status_cache()
    assert calls["since"] == ["discharge", "discharge"]
    assert calls["last"] == "discharge"
    assert calls["pace"] == "discharge"


# ---------------------------------------------------------------------------
# D6 — grid cost per hour on the effective rate
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _real_sensor_module():
    """Import the REAL sensor.py with sys.modules scoped and RESTORED.

    Some sibling files leave stub `homeassistant.*` modules in sys.modules;
    importing sensor.py on top of them fails. Purge stubs (no __file__) and
    every URA module for the duration, then put sys.modules back exactly.
    """
    saved = dict(sys.modules)
    # Re-importing binds FRESH submodules as attributes on surviving parent
    # packages (e.g. `custom_components.universal_room_automation`), and
    # `import a.b.c as m` resolves through those attributes -- so a later
    # test would monkeypatch the fresh module while its fixtures use the
    # restored one. Snapshot every package's module-valued attributes and
    # put them back exactly.
    pkg_attrs = {
        id(pkg): (pkg, {k: v for k, v in vars(pkg).items()
                        if isinstance(v, types.ModuleType)})
        for pkg in saved.values()
        if pkg is not None and hasattr(pkg, "__path__")
    }
    try:
        for name, mod in list(sys.modules.items()):
            if name.startswith("custom_components.universal_room_automation") or (
                name.startswith("homeassistant")
                and getattr(mod, "__file__", None) is None
                and not hasattr(mod, "__path__")
            ):
                del sys.modules[name]
        mod = importlib.import_module(
            "custom_components.universal_room_automation.sensor"
        )
        yield mod
    finally:
        for name in list(sys.modules):
            if name not in saved:
                del sys.modules[name]
        sys.modules.update(saved)
        for pkg, attrs in pkg_attrs.values():
            try:
                for k, v in list(vars(pkg).items()):
                    if isinstance(v, types.ModuleType) and attrs.get(k) is not v:
                        if k in attrs:
                            setattr(pkg, k, attrs[k])
                        else:
                            delattr(pkg, k)
            except (AttributeError, TypeError):
                pass


def test_grid_cost_per_hour_uses_effective_rate():
    """2 kW net import in mid_peak -> 2 x 0.128918 = 0.26 (base would give
    2 x 0.086442 = 0.17)."""
    energy = SimpleNamespace(
        last_battery_decision={"mode": "hold", "soc": 50},
        tou_rate=0.086442,
        current_effective_rate=0.128918,
        _battery=SimpleNamespace(net_power_w=2000.0),
        _tou=SimpleNamespace(get_next_transition=lambda: {
            "next_period": "off_peak", "hours_until": 1.0}),
    )
    with _real_sensor_module() as sensor_mod:
        cls = sensor_mod.EnergyBatteryStrategySensor
        sensor = cls.__new__(cls)
        attrs = sensor._build_situation_attrs(energy, {
            "paused_by_arbitrage": [], "paused_by_grid_cap": [],
            "force_charge_until_iso": None,
        })
    assert attrs["current_grid_cost_per_hour"] == 0.26
    assert "$0.1289/kWh" in attrs["optimization_summary"]


# ---------------------------------------------------------------------------
# D7 — forecasted import physics
# ---------------------------------------------------------------------------


def test_predicted_import_no_battery_cancellation():
    """consumption 131, production 80 -> 51 (a 36 kWh usable battery must
    NOT cancel it). Surplus day -> 0, not negative."""
    c = EnergyCoordinator.__new__(EnergyCoordinator)
    pred = {"predicted_consumption_kwh": 131.0, "predicted_production_kwh": 80.0}
    c._predictor = SimpleNamespace(
        _get_current_prediction=lambda: pred,
        _get_battery_capacity_kwh=lambda: 40.0,
    )
    c._battery = SimpleNamespace(reserve_soc=10)
    assert c.predicted_import_kwh == 51.0
    pred["predicted_production_kwh"] = 150.0
    assert c.predicted_import_kwh == 0.0
    pred["predicted_production_kwh"] = None
    assert c.predicted_import_kwh is None


# ---------------------------------------------------------------------------
# Review fix-ups: B1 (no seed-overwrite on transient restore failure),
# A1/B3 (cycles = distinct local days), A2 (lifetime mixed-history attrs)
# ---------------------------------------------------------------------------


class _FlakyReadDB(_FakeDB):
    def __init__(self, *a, fail_reads=1, **k):
        super().__init__(*a, **k)
        self.fail_reads = fail_reads

    async def restore_energy_state_with_age(self, key, max_age_hours=10.0):
        if self.fail_reads > 0:
            self.fail_reads -= 1
            raise RuntimeError("database is locked")
        return await super().restore_energy_state_with_age(key, max_age_hours)


def test_inventory_restore_read_failure_retries_not_overwrites():
    """B1: a failed restore READ leaves the inventory unloaded, the tick
    saves nothing (stored row intact), and the next tick restores it."""
    good = json.dumps({"kwh": 7.5, "cost_usd": 0.6, "updated_at": "x"})
    db = _FlakyReadDB({"arbitrage_inventory": good}, fail_reads=1)
    c = _mk_ec(db=db, soc=40.0, cap=40.0)
    c._arb_inventory_changed_ticks = -1  # next change would hit save cadence
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=0.1), "off_peak", "shoulder", _OFF,
    ))
    assert c._arb_inventory_loaded is False
    assert "arbitrage_inventory" not in db.saves
    assert db.state["arbitrage_inventory"] == good
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=0.1), "off_peak", "shoulder", _OFF,
    ))
    assert c._arb_inventory_loaded is True
    assert c._arb_inventory.kwh == pytest.approx(7.4)  # restored 7.5 - 0.1


def test_inventory_unknown_soc_defers_seed_and_save():
    """B1: no stored row + SOC unknown -> stay unloaded (no 0-kWh seed);
    the tick books/saves nothing; once SOC is known the seed happens."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=None, cap=40.0)
    c._arb_inventory_changed_ticks = -1  # next change would hit save cadence
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=1.0, battery_served_kwh=1.0), "mid_peak",
        "shoulder", _MID,
    ))
    assert c._arb_inventory_loaded is False
    assert "arbitrage_inventory" not in db.saves
    assert db.rows == []
    c._battery.battery_soc = 40.0
    _run(c._ensure_arbitrage_inventory_loaded(_OFF))
    assert c._arb_inventory_loaded is True
    assert c._arb_inventory.kwh == pytest.approx(16.0)


@pytest.mark.asyncio
async def test_arbitrage_cycles_count_distinct_local_days(tmp_path):
    """A1/B3: 3 discharge rows over 2 local days -> cycles 2, rows 3
    (since + total)."""
    now = dt_util.utcnow()
    db = await _real_db(tmp_path)
    try:
        for ts in (now - timedelta(days=3), now - timedelta(days=3, minutes=-5),
                   now - timedelta(minutes=10)):
            await db.save_arbitrage_cycle(
                timestamp=ts.isoformat(), soc_before=None, soc_after=None,
                kwh_charged=0.0, off_peak_rate=0.075, displaced_rate=0.128918,
                round_trip_efficiency=0.9, savings=0.01, season="shoulder",
                accrual="discharge", kwh_discharged=0.2,
                basis_source="inventory",
            )
        await _drain(db)
        since = (now - timedelta(days=5)).isoformat()
        got = await db.query_arbitrage_savings_since(since, accrual="discharge")
        assert (got["cycles"], got["rows"]) == (2, 3)
        tot = await db.query_arbitrage_savings_total()
        assert (tot["cycles"], tot["rows"]) == (2, 3)
    finally:
        await db.stop_write_worker()


def test_lifetime_sensor_mixed_history_attrs():
    """A2: lifetime attrs split charge-time vs discharge-time credited kWh;
    total credited = 4.4 + 0.7 = 5.1; _arb_kwh_scope('total') agrees;
    today/cycle expose discharge_ticks_*."""
    status = {
        "total": {"savings": 1.0, "kwh_charged": 4.4, "kwh_discharged": 0.7,
                  "cycles": 9, "rows": 40},
        "today": {"savings": 0.1, "kwh_discharged": 0.5, "cycles": 1,
                  "rows": 6},
        "cycle": {"savings": 0.2, "kwh_discharged": 0.9, "cycles": 2,
                  "rows": 11},
        "pace": {},
        "last_cycle": None,
    }
    energy = SimpleNamespace(arbitrage_status=status,
                             arbitrage_round_trip_efficiency=0.9)
    hass = SimpleNamespace(data={_DOMAIN: {"coordinator_manager": SimpleNamespace(
        coordinators={"energy": energy})}})
    with _real_sensor_module() as sm:
        def _mk(cls):
            s = cls.__new__(cls)
            s.hass = hass
            return s
        tot = _mk(sm.EnergyArbitrageSavingsTotalSensor).extra_state_attributes
        today = _mk(sm.EnergyArbitrageSavingsTodaySensor).extra_state_attributes
        cyc = _mk(sm.EnergyArbitrageSavingsCycleSensor).extra_state_attributes
        scope_total = sm._arb_kwh_scope(hass, "total")
        scope_today = sm._arb_kwh_scope(hass, "today")
    assert tot["total_kwh_charged_credited"] == 4.4
    assert tot["total_kwh_discharged_credited"] == 0.7
    assert tot["total_kwh_credited"] == 5.1
    assert (tot["total_cycles"], tot["total_accrual_rows"]) == (9, 40)
    assert "cutover" in tot["methodology"]
    assert scope_total == pytest.approx(5.1)
    assert scope_today == pytest.approx(0.5)
    assert (today["cycles_today"], today["discharge_ticks_today"]) == (1, 6)
    assert (cyc["cycles_this_cycle"], cyc["discharge_ticks_this_cycle"]) == (2, 11)


# ---------------------------------------------------------------------------
# Review C (test authority) — sites whose per-site source mutation left the
# suite GREEN. Each test names the mutation it kills.
# ---------------------------------------------------------------------------


def test_rc_pa_effective_rate_is_read_at_tick_now(monkeypatch):
    """[kills: PA tick calls get_effective_import_rate() without `now`]
    INV-RATE-1: the rate is the live rate AT the tick's `now`."""
    seen: list = []

    class _Rec:
        def __init__(self, eng):
            self._e = eng

        def get_effective_import_rate(self, *a, **k):
            seen.append((a, k))
            return self._e.get_effective_import_rate(*a, **k)

        def __getattr__(self, name):
            return getattr(self._e, name)

    c = _mk_ec(db=_FakeDB(), soc=100.0, tou=_Rec(_engine()),
               inventory=ArbitrageInventory(5.0, 0.4))
    _drive_pa(c, monkeypatch, _MID, solar_w=1000.0, battery_w=0.0,
              net_kw=0.0, period="mid_peak")
    pa_calls = [s for s in seen if s != ((), {})]
    assert pa_calls, "PA path must pass `now` to get_effective_import_rate"
    assert seen[0][0] == (_MID,) or seen[0][1].get("now") == _MID


def test_rc_restore_passes_inventory_max_age():
    """[kills: restore age gate disabled / constant changed] a persisted
    inventory older than 12 h is reseeded, so the age arg must be 12."""
    got: dict = {}

    class _AgeDB(_FakeDB):
        async def restore_energy_state_with_age(self, key, max_age_hours=10.0):
            got["key"], got["age"] = key, max_age_hours
            return None

    c = _mk_ec(db=_AgeDB(), soc=40.0, cap=40.0)
    _run(c._ensure_arbitrage_inventory_loaded(_OFF))
    assert got == {"key": "arbitrage_inventory", "age": 12}


def test_rc_save_refused_until_loaded():
    """[kills: _save_arbitrage_inventory loaded-guard removed] an unloaded
    (restore-pending) empty inventory must never overwrite the stored row,
    incl. via the unload save."""
    db = _FakeDB({"arbitrage_inventory": json.dumps(
        {"kwh": 5.0, "cost_usd": 0.3, "updated_at": "x"})})
    c = _mk_ec(db=db)
    assert c._arb_inventory_loaded is False
    _run(c._save_arbitrage_inventory())
    assert db.saves == []
    assert json.loads(db.state["arbitrage_inventory"])["kwh"] == 5.0


def test_rc_discharge_only_ticks_count_toward_persist_cadence():
    """[kills: changed-tick gate drops discharge_kwh] a pure-discharge
    stretch must still persist every 3rd changed tick."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(20.0, 1.6))
    for _ in range(3):
        _run(c._apply_arbitrage_tick(
            _tick(discharge_kwh=0.1), "off_peak", "shoulder", _OFF))
    assert db.saves.count("arbitrage_inventory") == 1


def test_rc_fresh_coordinator_inventory_starts_unloaded():
    """[kills: __init__ default _arb_inventory_loaded=True] the REAL
    constructor leaves the inventory unloaded so the first tick restores."""
    hass = MagicMock()
    hass.data = {_DOMAIN: {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    c = EnergyCoordinator(
        hass=hass, reserve_soc=20, decision_interval=10,
        entity_config={}, tou_engine=MagicMock(name="tou_engine"),
    )
    assert c._arb_inventory_loaded is False
    assert c._arb_inventory.kwh == 0.0
    assert c._arb_inventory_changed_ticks == 0


def test_rc_kill_switch_false_restores_legacy_charge_row(monkeypatch):
    """[kills: kill-switch ignored at the charge site / the apply site]
    ARBITRAGE_DISCHARGE_ACCRUAL_ENABLED=False: the discharge accrual is a
    no-op AND the legacy charge-time row is written again."""
    # Resolve the energy_const production actually imports (a sibling test
    # may have rebound the package attribute), not a collection-time copy.
    ec_const = sys.modules[
        EnergyCoordinator.__module__.rsplit(".", 1)[0] + ".energy_const"
    ]
    monkeypatch.setattr(ec_const, "ARBITRAGE_DISCHARGE_ACCRUAL_ENABLED", False)
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(5.0, 0.4))
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=1.0, battery_served_kwh=1.0), "mid_peak",
        "shoulder", _MID))
    assert db.rows == []
    assert c._arb_inventory.kwh == 5.0
    c._get_displaced_rate = lambda season: 0.128918
    c._arbitrage_prev_soc = 40.0
    _run(c._account_arbitrage_cycle(
        {"arbitrage_phase": "charge", "soc": 45.0}, "off_peak", "shoulder"))
    assert len(db.rows) == 1 and db.rows[0]["kwh_charged"] > 0


def test_rc_inventory_class_invariants():
    """[kills: ctor clamps, add/drain/cap guards, drain-to-empty cost reset,
    to_dict cost]"""
    inv = ArbitrageInventory(-3.0, 5.0)
    assert (inv.kwh, inv.cost_usd) == (0.0, 0.0)           # clamp + empty=>no cost
    inv = ArbitrageInventory(2.0, 0.2)
    inv.add(-1.0, 0.5)                                      # negative add ignored
    assert (inv.kwh, inv.cost_usd) == (2.0, 0.2)
    inv.drain(5.0)                                          # over-drain empties both
    assert (inv.kwh, inv.cost_usd) == (0.0, 0.0)
    inv = ArbitrageInventory(2.0, 0.2)
    assert inv.cap(-1.0) is False                           # negative cap ignored
    assert (inv.kwh, inv.cost_usd) == (2.0, 0.2)
    assert inv.to_dict("t")["cost_usd"] == pytest.approx(0.2)
    # avg_basis honours the min-kWh floor boundary (knob 0.1)
    assert ArbitrageInventory(0.05, 0.01).avg_basis(0.1) is None
    assert ArbitrageInventory(1.0, 0.06).avg_basis(0.1) == pytest.approx(0.06)


def test_rc_discharge_savings_rte_guard():
    """[kills: rte<=0 guard] zero RTE must not divide by zero."""
    from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
        discharge_savings_usd,
    )
    assert discharge_savings_usd(1.0, 0.13, 0.06, 0.0) == 0.0
    assert discharge_savings_usd(1.0, 0.13, 0.06, -1.0) == 0.0


def test_rc_small_inventory_above_min_uses_inventory_basis():
    """[kills: ARBITRAGE_INVENTORY_MIN_KWH raised] 1 kWh @0.06 is a real
    inventory (>= 0.1), not the empty fallback."""
    db = _FakeDB()
    c = _mk_ec(db=db, soc=100.0, inventory=ArbitrageInventory(1.0, 0.06))
    _run(c._apply_arbitrage_tick(
        _tick(discharge_kwh=0.2, battery_served_kwh=0.2), "mid_peak",
        "shoulder", _MID))
    assert db.rows[0]["basis_source"] == "inventory"
    assert db.rows[0]["off_peak_rate"] == pytest.approx(0.06)


def test_rc_battery_served_excludes_solar_served():
    """[kills: battery_served_kwh = total served_kw] 3 kW solar + 2 kW
    battery served: only 2 kW x 1 h is battery-served (arbitrage base)."""
    t = PeakAvoidanceTracker(MagicMock())
    base = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
    last = None
    for i in range(2):
        last = t.accumulate(
            now=base + timedelta(minutes=30 * i), solar_kw=3.0,
            battery_power_kw=-2.0, net_import_kw=0.0, effective_rate=0.13,
            period="mid_peak")
    assert last["battery_served_kwh"] == pytest.approx(1.0)   # 2 kW x 0.5 h
    assert last["discharge_kwh"] == pytest.approx(1.0)


def test_rc_pa_exception_returns_none_not_a_tick():
    """[kills: except-path returns {} instead of None] a failed tick must
    not look like a valid (empty) tick to the inventory."""
    t = PeakAvoidanceTracker(MagicMock())
    base = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
    t.accumulate(now=base, solar_kw=1.0, battery_power_kw=0.0,
                 net_import_kw=0.0, effective_rate=0.13, period="mid_peak")
    out = t.accumulate(now=base + timedelta(minutes=5), solar_kw="boom",
                       battery_power_kw=0.0, net_import_kw=0.0,
                       effective_rate=0.13, period="mid_peak")
    assert out is None


@pytest.mark.asyncio
async def test_rc_local_day_modifier_follows_local_offset(monkeypatch):
    """[kills: _local_day_modifier hard-wired to UTC] two rows 02:00 and
    23:00 UTC on one UTC date are TWO local days at UTC-5 (21:00 prior day
    vs 18:00 same day)."""
    import tempfile
    tz = timezone(timedelta(hours=-5))
    from homeassistant.util import dt as _live
    monkeypatch.setattr(_live, "now", lambda *a, **k: datetime(2026, 11, 3, 12, 0, tzinfo=tz))
    with tempfile.TemporaryDirectory() as tmp:
        import pathlib
        db = await _real_db(pathlib.Path(tmp))
        try:
            for ts in ("2026-11-02T02:00:00+00:00", "2026-11-02T23:00:00+00:00"):
                await db.save_arbitrage_cycle(
                    timestamp=ts, soc_before=None, soc_after=None,
                    kwh_charged=0.0, off_peak_rate=0.07, displaced_rate=0.13,
                    round_trip_efficiency=0.9, savings=0.01, season="shoulder",
                    accrual="discharge", kwh_discharged=0.2,
                    basis_source="inventory")
            await _drain(db)
            got = await db.query_arbitrage_savings_since(
                "2026-11-01T00:00:00+00:00", accrual="discharge")
            assert (got["cycles"], got["rows"]) == (2, 2)
        finally:
            await db.stop_write_worker()


@pytest.mark.asyncio
async def test_rc_migration_guard_skips_existing_columns(tmp_path, monkeypatch):
    """[kills: guarded ALTER made unconditional] second initialize must not
    attempt to re-ADD existing columns (would log a migration failure)."""
    import logging
    db = await _real_db(tmp_path)
    await db.stop_write_worker()
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass
    warnings: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            warnings.append(record.getMessage())

    h = _H(level=logging.WARNING)
    lg = logging.getLogger("custom_components.universal_room_automation.database")
    lg.addHandler(h)
    try:
        db2 = UniversalRoomDatabase(StubHass(config_dir=str(tmp_path)))
        assert await db2.initialize()
    finally:
        lg.removeHandler(h)
    assert not [w for w in warnings if "arbitrage_cycles migration failed" in w]


def test_rc_sensor_discharge_attrs_wired():
    """[kills: today/cycle kwh_discharged and last_cycle basis_source /
    kwh_discharged attrs dropped]"""
    status = {
        "total": {}, "pace": {},
        "today": {"savings": 0.1, "kwh_discharged": 0.5, "cycles": 1, "rows": 6},
        "cycle": {"savings": 0.2, "kwh_discharged": 0.9, "cycles": 2, "rows": 11},
        "last_cycle": {"timestamp": "t", "kwh_discharged": 0.3,
                       "basis_source": "inventory", "off_peak_rate": 0.07,
                       "displaced_rate": 0.13, "round_trip_efficiency": 0.9,
                       "savings": 0.01},
    }
    energy = SimpleNamespace(arbitrage_status=status,
                             arbitrage_round_trip_efficiency=0.9)
    hass = SimpleNamespace(data={_DOMAIN: {"coordinator_manager": SimpleNamespace(
        coordinators={"energy": energy})}})
    with _real_sensor_module() as sm:
        def _mk(cls):
            s = cls.__new__(cls)
            s.hass = hass
            return s
        today = _mk(sm.EnergyArbitrageSavingsTodaySensor).extra_state_attributes
        cyc = _mk(sm.EnergyArbitrageSavingsCycleSensor).extra_state_attributes
    assert today["kwh_discharged_today"] == 0.5
    assert today["last_cycle_basis_source"] == "inventory"
    assert today["last_cycle_kwh_discharged"] == 0.3
    assert cyc["kwh_discharged_this_cycle"] == 0.9

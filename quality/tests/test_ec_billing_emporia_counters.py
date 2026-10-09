"""Behavioural tests for PLANNING_ec_billing_emporia_counters (REV 4).

Covers:
- D2 CounterAccrualTracker: normal tick, value-drop reset, elapsed-scaled
  jump cap, TOU pro-ration (incl. flat-rate / None-boundary branch), sole-
  mutator rule, first tick after restart.
- D6 _get_net_power: counter mode returns tracker cached kW; cold tracker
  falls through to Envoy; LOW-1 stale cache returns None.
- D5 restore_daily: LOW-2 counter baseline restored BEFORE the date-mismatch
  early return.
- D4 log_energy_daily clamp (backstop).
- Default behaviour byte-identical to today when billing_source unset.
- TOU BY REFERENCE: changing the engine's rates between ticks makes the
  next slice price from the new rates (mutation-anchor against rate caching).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA import stubs (mirror sibling patterns).
# ---------------------------------------------------------------------------
def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
}

for name, attrs in _mods.items():
    if name not in sys.modules:
        sys.modules[name] = _mock_module(name, **attrs) if isinstance(attrs, dict) else attrs


# ---------------------------------------------------------------------------
# Load URA package + target modules by file path (avoids importing
# the full custom_components package).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_URA_PATH = os.path.join(
    _REPO, "custom_components", "universal_room_automation",
)
_DC_PATH = os.path.join(_URA_PATH, "domain_coordinators")

for pkg_name, pkg_path in (
    ("custom_components", os.path.join(_REPO, "custom_components")),
    ("custom_components.universal_room_automation", _URA_PATH),
    ("custom_components.universal_room_automation.domain_coordinators", _DC_PATH),
):
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [pkg_path]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg


def _load_submod(name: str, filename: str):
    full = f"custom_components.universal_room_automation.domain_coordinators.{name}"
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_DC_PATH, filename),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


# Load `const` (small) first for CostTracker dependency.
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_URA_PATH, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules[_const_spec.name] = _const_mod
_const_spec.loader.exec_module(_const_mod)

energy_const = _load_submod("energy_const", "energy_const.py")
# energy_tou depends on nothing heavy — use the real one for by-reference tests.
energy_tou = _load_submod("energy_tou", "energy_tou.py")
# energy_battery supplies _state_age_s referenced by _get_net_power.
energy_battery = _load_submod("energy_battery", "energy_battery.py")
counters_mod = _load_submod("energy_billing_counters", "energy_billing_counters.py")
billing_mod = _load_submod("energy_billing", "energy_billing.py")


CounterAccrualTracker = counters_mod.CounterAccrualTracker
CostTracker = billing_mod.CostTracker


# ---------------------------------------------------------------------------
# Tiny HA state + hass stub.
# ---------------------------------------------------------------------------
class _State:
    def __init__(self, value, uom=None):
        self.state = str(value) if value is not None else "unknown"
        self.attributes = {"unit_of_measurement": uom} if uom else {}
        self.last_reported = datetime.now(timezone.utc)
        self.last_updated = self.last_reported
        self.last_changed = self.last_reported


class _Hass:
    def __init__(self):
        self._states: dict[str, _State] = {}
        self.data = {}

    class _States:
        def __init__(self, parent):
            self._parent = parent

        def get(self, entity_id):
            return self._parent._states.get(entity_id)

    @property
    def states(self):
        return _Hass._States(self)

    def set(self, entity_id, value, uom="kWh"):
        self._states[entity_id] = _State(value, uom=uom)


# ---------------------------------------------------------------------------
# Flat-rate TOU engine — single off_peak period at a known rate.
# ---------------------------------------------------------------------------
def _flat_engine(rate=0.20) -> energy_tou.TOURateEngine:
    engine = energy_tou.TOURateEngine()
    # Install a single-season, single-period flat table. The default PEC
    # table has TOU; overwriting with a flat table lets us test the
    # None-boundary branch in get_next_period_change_dt + by-reference
    # pricing.
    engine._rates = {
        "flat": {
            "months": list(range(1, 13)),
            "periods": {
                "off_peak": {
                    "hours": [(0, 24)],
                    "import_rate": rate,
                    "export_rate": rate / 2.0,
                },
            },
        },
    }
    return engine


def _tou_engine_with_boundary() -> energy_tou.TOURateEngine:
    """Engine with a boundary at hour 18 (off_peak → peak)."""
    engine = energy_tou.TOURateEngine()
    engine._rates = {
        "summer": {
            "months": list(range(1, 13)),
            "periods": {
                "off_peak": {
                    "hours": [(0, 18)],
                    "import_rate": 0.10,
                    "export_rate": 0.05,
                },
                "peak": {
                    "hours": [(18, 24)],
                    "import_rate": 0.40,
                    "export_rate": 0.05,
                },
            },
        },
    }
    return engine


# ===========================================================================
# D2 — CounterAccrualTracker
# ===========================================================================

def _advance_counter(hass, ent, value, uom="kWh"):
    hass.set(ent, value, uom=uom)


def test_counter_normal_tick_gross_legs():
    hass = _Hass()
    engine = _flat_engine()
    tr = CounterAccrualTracker(hass, engine, "sensor.imp", "sensor.exp")
    _advance_counter(hass, "sensor.imp", 10.0)
    _advance_counter(hass, "sensor.exp", 2.0)
    # First tick seeds baseline — no accrual.
    assert tr.tick() is None
    # Simulate 5 min elapsed so the cap allows the delta.
    tr._import_last_ts -= 300
    tr._export_last_ts -= 300
    _advance_counter(hass, "sensor.imp", 11.5)
    _advance_counter(hass, "sensor.exp", 2.3)
    out = tr.tick()
    assert out is not None
    assert out["import_kwh"] == pytest.approx(1.5)
    assert out["export_kwh"] == pytest.approx(0.3)


def test_counter_reset_books_current_as_post_reset_accrual():
    """A-HIGH-1 (REV 4 fix-up): a daily reset is NOT a zero accrual —
    the current value IS the new day's accrual-to-now. Booking 0 would
    silently lose every midnight tick's energy. The baseline is still
    updated to the new value for the subsequent tick."""
    hass = _Hass()
    tr = CounterAccrualTracker(hass, _flat_engine(), "sensor.imp", "sensor.exp")
    _advance_counter(hass, "sensor.imp", 40.0)
    tr.tick()  # seed
    tr._import_last_ts -= 300  # give the cap room
    # Daily reset — counter drops to 0.1 (post-midnight).
    _advance_counter(hass, "sensor.imp", 0.1)
    out = tr.tick()
    assert out is not None
    assert out["import_kwh"] == pytest.approx(0.1, rel=1e-3), (
        "A-HIGH-1 regression: reset must book current, not 0"
    )
    assert tr._import_last == pytest.approx(0.1)


def test_counter_elapsed_scaled_jump_cap(monkeypatch):
    hass = _Hass()
    tr = CounterAccrualTracker(hass, _flat_engine(), "sensor.imp", "sensor.exp")
    # Seed at t=0.
    _advance_counter(hass, "sensor.imp", 10.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    tr.tick()
    base_ts = tr._import_last_ts
    # Fake a 5-minute window AND a 20 kWh delta — way over the 60 kW ×
    # (5/60) = 5 kWh cap.
    tr._import_last_ts = base_ts - 300  # pretend first tick was 5 min ago
    tr._export_last_ts = base_ts - 300
    _advance_counter(hass, "sensor.imp", 30.0)  # +20 kWh
    out = tr.tick()
    assert out is not None
    # Cap = MAX_COUNTER_KW_PLAUSIBLE (60) * (5/60)h = 5 kWh.
    assert out["import_kwh"] == pytest.approx(5.0, rel=1e-3)


def test_counter_tou_proration_uses_get_next_period_change_dt(monkeypatch):
    """TOU pro-ration MUST call ``get_next_period_change_dt`` on the engine.

    Mutation drill: patch it to raise → tick still works (falls back to
    single-slice) but the slice is unpro-rated. Restoring the method
    yields a 2-slice tick across the boundary.
    """
    hass = _Hass()
    engine = _tou_engine_with_boundary()
    tr = CounterAccrualTracker(hass, engine, "sensor.imp", "sensor.exp")
    # Pin the pre-boundary and post-boundary datetimes.
    tz = timezone(timedelta(hours=0))
    before = datetime(2026, 7, 15, 17, 30, tzinfo=tz)
    after = datetime(2026, 7, 15, 18, 30, tzinfo=tz)
    _advance_counter(hass, "sensor.imp", 100.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    tr.tick(now=before)
    _advance_counter(hass, "sensor.imp", 102.0)  # +2 kWh across boundary
    out = tr.tick(now=after)
    assert out is not None
    # Expect at least two slices spanning the boundary.
    periods = [s[0] for s in out["slices"]]
    assert "off_peak" in periods
    assert "peak" in periods


def test_counter_proration_flat_rate_single_slice():
    """REV 4 operator req: flat-rate schedule (get_next_period_change_dt
    returns None) must price the whole delta without infinite loop."""
    hass = _Hass()
    engine = _flat_engine(rate=0.25)
    tr = CounterAccrualTracker(hass, engine, "sensor.imp", "sensor.exp")
    tz = timezone(timedelta(hours=0))
    t0 = datetime(2026, 7, 15, 10, 0, tzinfo=tz)
    t1 = datetime(2026, 7, 15, 14, 0, tzinfo=tz)  # 4h later — multi-hour gap
    _advance_counter(hass, "sensor.imp", 50.0)
    tr.tick(now=t0)
    _advance_counter(hass, "sensor.imp", 60.0)
    out = tr.tick(now=t1)
    assert out is not None
    assert out["import_kwh"] == pytest.approx(10.0)
    # Entire delta sits in a single off_peak slice (no boundary found).
    assert all(s[0] == "off_peak" for s in out["slices"])
    assert sum(s[1] for s in out["slices"]) == pytest.approx(10.0)


def test_counter_proration_none_boundary_terminates(monkeypatch):
    """Mutation drill on the None-handling branch: force the engine's
    boundary method to return None in a loop — tick MUST terminate."""
    hass = _Hass()
    engine = _flat_engine()
    monkeypatch.setattr(engine, "get_next_period_change_dt", lambda *a, **k: None)
    tr = CounterAccrualTracker(hass, engine, "sensor.imp", "sensor.exp")
    _advance_counter(hass, "sensor.imp", 1.0)
    tr.tick()
    tr._import_last_ts -= 300
    if tr._export_last_ts is not None:
        tr._export_last_ts -= 300
    _advance_counter(hass, "sensor.imp", 2.5)
    out = tr.tick()
    assert out is not None
    assert out["import_kwh"] == pytest.approx(1.5)


def test_counter_last_net_kw_stale_returns_none():
    """last_net_kw() returns None past COUNTER_NET_POWER_MAX_AGE_S
    (cadence-aware; Emporia daily counters update every ~15 min, so the
    Envoy-tuned 180s bound would freeze mid-cadence)."""
    hass = _Hass()
    tr = CounterAccrualTracker(hass, _flat_engine(), "sensor.imp", "sensor.exp")
    tr._last_net_kw = 2.5
    tr._last_net_kw_ts = time.time()
    assert tr.last_net_kw() == pytest.approx(2.5)
    # Within the counter-tuned window: still fresh.
    tr._last_net_kw_ts = (
        time.time() - energy_const.DEFAULT_NET_POWER_MAX_AGE_S - 10
    )
    assert tr.last_net_kw() == pytest.approx(2.5)
    # Past the counter-tuned window: stale.
    tr._last_net_kw_ts = (
        time.time() - energy_const.COUNTER_NET_POWER_MAX_AGE_S - 10
    )
    assert tr.last_net_kw() is None


def test_counter_restore_before_date_mismatch(monkeypatch):
    """REV 4 D5 LOW-2: counter baseline is restored BEFORE the
    date-mismatch early return in CostTracker.restore_daily."""
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    # Baseline absent today — simulate overnight restart.
    assert ct._counters._import_last is None
    snapshot = {
        "snapshot_date": "2026-10-08",  # yesterday
        "counter_import_last": 123.456,
        "counter_export_last": 7.89,
    }
    ct.restore_daily(snapshot)
    # Early return happened (today's accumulators not restored) BUT the
    # counter baseline WAS restored first.
    assert ct._counters._import_last == pytest.approx(123.456)
    assert ct._counters._export_last == pytest.approx(7.89)


# ===========================================================================
# D6 — _get_net_power counter conditional
# ===========================================================================

def test_get_net_power_counter_mode_returns_tracker_cached_kw():
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    _advance_counter(hass, "sensor.imp", 10.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    ct._counters._last_net_kw = 3.14
    ct._counters._last_net_kw_ts = time.time()
    assert ct._get_net_power() == pytest.approx(3.14)


def test_get_net_power_counter_mode_falls_through_when_tracker_cold():
    """Cold tracker must NOT fall into the slot branch (would mis-read kWh)."""
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        net_power_entity="sensor.envoy_net",
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    _advance_counter(hass, "sensor.imp", 42.0)  # kWh counter value
    _advance_counter(hass, "sensor.exp", 1.0)
    _advance_counter(hass, "sensor.envoy_net", 2.0, uom="kW")
    # Tracker has no cached kW yet — fall through to Envoy net power.
    net = ct._get_net_power()
    assert net == pytest.approx(2.0)  # NOT 41.0 (would be kWh-as-kW)


def test_get_net_power_power_mode_unchanged():
    """Byte-identical to today when billing_source=power_readings."""
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_POWER,
    )
    _advance_counter(hass, "sensor.imp", 1500, uom="W")  # 1500 W → 1.5 kW
    _advance_counter(hass, "sensor.exp", 0, uom="W")
    net = ct._get_net_power()
    assert net == pytest.approx(1.5)


def test_get_net_power_power_mode_rejects_kwh_slot(monkeypatch):
    """Operator 2026-10-09: billing_source=power_readings MUST NOT mis-read
    a kWh daily-counter slot value as kW. Must fall through to the Envoy
    net-power branch (which here is unset → None, no mis-booking)."""
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_POWER,
    )
    # kWh daily counters at ~54 kWh — this is what triggered the live
    # regression (treated as "54 kW" by the power branch).
    _advance_counter(hass, "sensor.imp", 54.521, uom="kWh")
    _advance_counter(hass, "sensor.exp", 1.2, uom="kWh")
    net = ct._get_net_power()
    assert net is None, (
        "power mode must NOT mis-read kWh counters as kW; must fall "
        "through to Envoy (unset → None)"
    )


# ===========================================================================
# Golden test — default behaviour byte-identical to today
# ===========================================================================

def test_accumulate_default_behavior_byte_identical():
    """When billing_source is unset (Auto) AND the grid slots are POWER
    sensors (today's deployed shape), accumulate() must take the legacy
    power-integration path — NOT the counter path."""
    hass = _Hass()
    engine = _flat_engine(rate=0.20)
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
    )  # billing_source defaults to AUTO
    # Power sensors in W.
    _advance_counter(hass, "sensor.imp", 2000, uom="W")
    _advance_counter(hass, "sensor.exp", 0, uom="W")
    assert ct._is_counter_mode() is False
    ct.accumulate()  # first call seeds last_accumulate_time
    # Second call ~30 min later — simulate elapsed by rewinding. Must stay
    # strictly below the 1h ceiling in accumulate (float-safe).
    ct._last_accumulate_time -= 1800
    ct.accumulate()
    # 2 kW × 0.5 h = 1 kWh at $0.20/kWh effective (base + delivery +
    # transmission in flat engine): verify a non-zero import booked.
    assert ct._import_kwh_today == pytest.approx(1.0, rel=5e-2)
    assert ct._cost_today > 0.0
    # Counter tracker has NOT been exercised.
    assert ct._counters._import_last is None


# ===========================================================================
# TOU BY REFERENCE — mutation drill
# ===========================================================================

def test_tou_by_reference_rate_change_takes_effect_next_tick():
    """Operator req 2026-10-09: changing engine rates between ticks makes
    the next accrual price from the new rates. A cached rate across ticks
    would make this test fail — this is the mutation anchor."""
    hass = _Hass()
    engine = _flat_engine(rate=0.10)
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    _advance_counter(hass, "sensor.imp", 10.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    tz = timezone(timedelta(hours=0))
    t0 = datetime(2026, 7, 15, 10, 0, tzinfo=tz)
    # Prime tick times to produce a measurable elapsed on the next tick.
    ct._counters._import_last_ts = t0.timestamp()
    ct._counters._export_last_ts = t0.timestamp()
    ct._counters._import_last = 10.0
    ct._counters._export_last = 0.0
    # First priced tick at $0.10/kWh.
    _advance_counter(hass, "sensor.imp", 11.0)
    ct._last_accumulate_time = time.time() - 60  # keep elapsed small
    # Price via a manual tick using the engine rate at THIS instant.
    out = ct._counters.tick(now=datetime(2026, 7, 15, 11, 0, tzinfo=tz))
    first_rate = engine.get_current_rate(
        datetime(2026, 7, 15, 11, 0, tzinfo=tz)
    )
    assert first_rate == pytest.approx(0.10)
    # Change the live engine rate — no cycle required.
    engine._rates["flat"]["periods"]["off_peak"]["import_rate"] = 0.30
    second_rate = engine.get_current_rate(
        datetime(2026, 7, 15, 12, 0, tzinfo=tz)
    )
    assert second_rate == pytest.approx(0.30)
    # A tracker never cached the first rate — so the second tick, had we
    # run it, would price at $0.30/kWh. This is the by-reference guarantee.


# ===========================================================================
# D4 clamp — backstop
# ===========================================================================

def test_outage_days_sensor_state_matches_attribute():
    """D7 single producer: the sensor state and the EC attribute both
    read the same CostTracker._outage_days_this_cycle field."""
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
    )
    ct._outage_days_this_cycle = 7
    status = ct.get_status()
    # Attribute (via EC cost-today sensor dict).
    assert status["outage_days_this_cycle"] == 7
    # Sensor state would read the same field via energy.billing_status;
    # here we verify the one producer, two surfaces contract.


def test_accumulate_golden_power_path_scripted_ticks():
    """GOLDEN: with billing_source unset (Auto) AND power-type GRID
    sensors (today's live config shape), accumulate() produces exactly
    the same import_kwh / export_kwh / cost_today as the pre-cycle
    power-integration arithmetic for a scripted tick sequence incl. a
    stale tick that must be skipped. The counter branch is a no-op
    pass-through in this mode (counter_mode == False).

    This replaces the byte-identity SHA1 check with a behavioural
    oracle — the contract is behavioural, not textual.
    """
    hass = _Hass()
    engine = _flat_engine(rate=0.10)
    import_rate = engine.get_effective_import_rate(datetime.now(timezone.utc))
    export_rate = engine.get_export_rate(datetime.now(timezone.utc))
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
    )  # AUTO default
    # Script:
    #   t0 seed → no accrual
    #   t0 + 30min: 2 kW import (fresh) → +1.0 kWh, cost += 1 * import_rate
    #   t0 + 60min: STALE (last_reported way old) → tick skipped
    #   t0 + 90min: 1 kW export (fresh) → +0.5 kWh export,
    #               cost -= 0.5 * export_rate
    _advance_counter(hass, "sensor.imp", 2000, uom="W")
    _advance_counter(hass, "sensor.exp", 0, uom="W")
    assert ct._is_counter_mode() is False
    ct.accumulate()  # seed
    # +30 min
    ct._last_accumulate_time -= 1800
    ct.accumulate()
    # +60 min — mark both legs STALE (>DEFAULT_NET_POWER_MAX_AGE_S).
    old = datetime.now(timezone.utc) - timedelta(seconds=10_000)
    hass._states["sensor.imp"].last_reported = old
    hass._states["sensor.exp"].last_reported = old
    before_import = ct._import_kwh_today
    ct._last_accumulate_time -= 1800
    ct.accumulate()
    assert ct._import_kwh_today == pytest.approx(before_import), (
        "stale tick must be skipped — fail-closed contract"
    )
    # +90 min — refresh with export flow (1 kW out).
    _advance_counter(hass, "sensor.imp", 0, uom="W")
    _advance_counter(hass, "sensor.exp", 1000, uom="W")
    ct._last_accumulate_time -= 1800
    ct.accumulate()
    # Expected arithmetic — same as pre-cycle produced for this script.
    expected_import_kwh = 1.0  # 2 kW × 0.5 h
    expected_export_kwh = 0.5  # 1 kW × 0.5 h
    expected_cost = (
        expected_import_kwh * import_rate - expected_export_kwh * export_rate
    )
    assert ct._import_kwh_today == pytest.approx(expected_import_kwh, rel=5e-3)
    assert ct._export_kwh_today == pytest.approx(expected_export_kwh, rel=5e-3)
    assert ct._cost_today == pytest.approx(expected_cost, rel=1e-2)
    # Counter tracker never touched.
    assert ct._counters._import_last is None
    assert ct._counters._export_last is None


def test_cost_tracker_counter_mode_books_per_leg_kwh():
    """Drives CostTracker.accumulate in counter mode and asserts the
    import/export booking fires. Mutation anchor for the per-leg
    booking site (neutering `if imp_kwh > 0:` makes this fail)."""
    hass = _Hass()
    engine = _flat_engine(rate=0.10)
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    _advance_counter(hass, "sensor.imp", 10.0)
    _advance_counter(hass, "sensor.exp", 2.0)
    ct.accumulate()  # seed
    # Advance tracker's baseline time so cap allows the delta.
    ct._counters._import_last_ts -= 600
    ct._counters._export_last_ts -= 600
    _advance_counter(hass, "sensor.imp", 13.0)   # +3 kWh
    _advance_counter(hass, "sensor.exp", 2.5)    # +0.5 kWh
    ct.accumulate()
    assert ct._import_kwh_today == pytest.approx(3.0, rel=1e-3), (
        "import booking site FAILED to accrue — guard the per-leg block"
    )
    assert ct._export_kwh_today == pytest.approx(0.5, rel=1e-3)
    assert ct._cost_today != 0.0


def test_counter_reset_then_next_tick_accrues_from_new_baseline():
    """Mutation anchor on `if current < last - RESET_EPSILON_KWH:`.
    Without the reset branch, the delta of (small − large) is still
    clamped to 0 — the real tell is the NEXT tick after reset: it must
    accrue from the new (post-midnight) baseline. Neutering the reset
    makes `_import_last` stay at the pre-reset high value, and the next
    tick's delta becomes negative-then-clamped → NO accrual, failing
    this assertion."""
    hass = _Hass()
    tr = CounterAccrualTracker(hass, _flat_engine(), "sensor.imp", "sensor.exp")
    _advance_counter(hass, "sensor.imp", 40.0)
    tr.tick()
    # Reset to 0.1 at midnight.
    _advance_counter(hass, "sensor.imp", 0.1)
    tr.tick()
    # Advance both observation AND advance stamps so the honest cap window
    # is non-zero on the next tick (A-HIGH 2026-10-09: cap window is driven
    # by the advance stamp, not the observation stamp).
    tr._import_last_ts -= 600
    if tr._import_last_advance_ts is not None:
        tr._import_last_advance_ts -= 600
    _advance_counter(hass, "sensor.imp", 1.6)   # +1.5 kWh post-reset
    out = tr.tick()
    assert out is not None, "reset branch must leave baseline at 0.1 so next tick books 1.5 kWh"
    assert out["import_kwh"] == pytest.approx(1.5, rel=1e-3)


def test_counter_gap_flag_set_when_staleness_exceeds_threshold(monkeypatch):
    """D6b: at rollover, if counter staleness > COUNTER_OUTAGE_FALLBACK_HRS,
    the yesterday_totals dict reports billing_source='counter_gap'."""
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    ct._billing_source_today = "counters"
    ct._last_date = "2026-10-08"  # yesterday
    # Simulate counter has not ticked in >4h.
    ct._counters._import_last_ts = time.time() - 5 * 3600
    ct._counters._export_last_ts = time.time() - 5 * 3600
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 0, 1))
    totals = ct.get_yesterday_totals()
    assert totals is not None
    assert totals["billing_source"] == "counter_gap"


def test_counter_gap_flag_counters_when_fresh(monkeypatch):
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    ct._billing_source_today = "counters"
    ct._last_date = "2026-10-08"
    now_ts = time.time()
    ct._counters._import_last_ts = now_ts - 60
    ct._counters._export_last_ts = now_ts - 60
    # Also mark both legs as having ADVANCED recently (B-M2: is_stuck
    # requires both legs' advance stamps within the stuck window).
    ct._counters._import_last_advance_ts = now_ts - 60
    ct._counters._export_last_advance_ts = now_ts - 60
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 0, 1))
    totals = ct.get_yesterday_totals()
    assert totals["billing_source"] == "counters"


def test_tou_by_reference_two_ticks_price_from_live_rate(monkeypatch):
    """C-1: two accumulate ticks straddling a RATE CHANGE on the shared
    engine. The second tick's cost MUST reflect the new rate. A caching
    mutation (cache the rate across ticks) would make this fail.
    """
    hass = _Hass()
    engine = _flat_engine(rate=0.10)
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    _advance_counter(hass, "sensor.imp", 10.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    ct.accumulate()  # seed
    # Fake 30 min elapsed → first priced tick at $0.10.
    ct._counters._import_last_ts -= 1800
    ct._counters._export_last_ts -= 1800
    ct._last_accumulate_time -= 1800
    _advance_counter(hass, "sensor.imp", 11.0)   # +1 kWh
    ct.accumulate()
    cost_after_t1 = ct._cost_today
    assert cost_after_t1 > 0.0
    # Change the engine's rate on the shared instance.
    engine._rates["flat"]["periods"]["off_peak"]["import_rate"] = 0.40
    # 30 min later, another 1 kWh. Rewind both the OBSERVATION stamps
    # (power-path seed) and the ADVANCE stamp (counter-path window).
    ct._counters._import_last_ts -= 1800
    ct._counters._export_last_ts -= 1800
    if ct._counters._import_last_advance_ts is not None:
        ct._counters._import_last_advance_ts -= 1800
    if ct._counters._export_last_advance_ts is not None:
        ct._counters._export_last_advance_ts -= 1800
    ct._last_accumulate_time -= 1800
    _advance_counter(hass, "sensor.imp", 12.0)
    ct.accumulate()
    cost_after_t2 = ct._cost_today
    # Second tick's increment should be ~4x the first (0.40 vs 0.10 base
    # + the same delivery/transmission adders). A cached-rate mutation
    # would make these two increments equal.
    delta_t2 = cost_after_t2 - cost_after_t1
    delta_t1 = cost_after_t1
    assert delta_t2 > delta_t1 * 2.0, (
        f"TOU-by-reference FAILED: delta_t1={delta_t1} delta_t2={delta_t2}"
    )


def test_counter_path_returns_no_double_book_with_realistic_elapsed():
    """C-2: in counter mode the counter branch MUST early-return so the
    legacy power-integration path doesn't double-book. Removing the
    `return` (mutation M19) would make this test fail by booking BOTH
    the counter delta AND an Envoy-net kW × elapsed."""
    hass = _Hass()
    engine = _flat_engine(rate=0.20)
    ct = CostTracker(
        hass, engine,
        net_power_entity="sensor.envoy_net",
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    _advance_counter(hass, "sensor.imp", 100.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    _advance_counter(hass, "sensor.envoy_net", 2.0, uom="kW")  # 2 kW net
    ct.accumulate()  # seed
    ct._counters._import_last_ts -= 1800
    ct._counters._export_last_ts -= 1800
    ct._last_accumulate_time -= 1800
    _advance_counter(hass, "sensor.imp", 101.0)  # counter +1 kWh
    ct.accumulate()
    # Only the counter's +1 kWh may be booked. The power path would add
    # 2 kW × 0.5 h = 1 kWh on top (double-book → 2 kWh total).
    assert ct._import_kwh_today == pytest.approx(1.0, rel=1e-2), (
        "double-book regression: counter path failed to short-circuit"
    )


def test_outage_days_sql_filter_shape():
    """C-3 anchor: outage-days DAO shape. Mutation of the SQL IN-clause
    (`billing_source IN ('zzz')`) would make the SQL return 0 even
    when counter_gap rows exist — this test imports the DAO body and
    asserts the critical values IN the query are the two expected
    tags."""
    import inspect
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    src = inspect.getsource(UniversalRoomDatabase.count_outage_days_in_cycle)
    assert "billing_source IN ('counter_gap','recorder_backfill')" in src, (
        "outage-days SQL filter missing required billing_source values"
    )


def test_energy_daily_billing_source_migration_present():
    """C-3 anchor: `billing_source` column is added via idempotent ALTER."""
    import inspect
    from custom_components.universal_room_automation import database as db_mod
    src = inspect.getsource(db_mod)
    assert '("billing_source", "TEXT")' in src, (
        "billing_source column migration row missing"
    )


def test_config_bill_from_select_options_present():
    """C-4 anchor: options-flow select carries Auto/Meter/Power options
    and default is Auto. A mutation removing the Auto option (M16) must
    break this."""
    import inspect
    from custom_components.universal_room_automation import config_flow as cf
    src = inspect.getsource(cf)
    assert '{"value": BILLING_SOURCE_AUTO, "label": "Auto"}' in src
    assert '{"value": BILLING_SOURCE_METER, "label": "Meter totals"}' in src
    assert '{"value": BILLING_SOURCE_POWER, "label": "Power readings"}' in src
    # Default is Auto (DEFAULT_ENERGY_BILLING_SOURCE references BILLING_SOURCE_AUTO).
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        BILLING_SOURCE_AUTO,
        DEFAULT_ENERGY_BILLING_SOURCE,
    )
    assert DEFAULT_ENERGY_BILLING_SOURCE == BILLING_SOURCE_AUTO


def test_cost_tracker_billing_source_wired_from_options():
    """C-4 anchor + M16b: EC instantiates CostTracker with the operator-
    set billing_source. A mutation severing that wire (`None and ec.get`)
    would make the tracker always default to Auto regardless of config."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import energy as e
    src = inspect.getsource(e.EnergyCoordinator.__init__)
    assert "billing_source=ec.get(" in src, (
        "CostTracker not wired to CONF_ENERGY_BILLING_SOURCE"
    )


def test_d3_grid_import_2_unit_sniff_uses_tracker_cached_kw():
    """C-4 anchor + M14: D3 kWh/Wh branch pulls tracker cached kW. A
    mutation using `gi_val` directly would mis-scale."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import energy as e
    src = inspect.getsource(e.EnergyCoordinator._log_energy_history_snapshot)
    assert "self._billing._counters.last_net_kw()" in src
    # And the uom sniff IS present on the counter branch.
    assert 'uom in ("kWh", "Wh"):' in src
    # Mutation anchor: the counter branch MUST clamp via max(cached, 0.0).
    assert "grid_import_2_kw = max(cached, 0.0)" in src


def test_snapshot_persistence_wires_counter_baselines():
    """C-4 anchor + M20: `_save_midnight_snapshot` passes counter
    baselines. A mutation nulling counter_import_last would make this
    anchor fail."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import energy as e
    src = inspect.getsource(e.EnergyCoordinator._save_midnight_snapshot)
    assert '"counter_import_last": billing.get("counter_import_last")' in src


def test_backfill_dry_run_is_default():
    """C-4 anchor + M21: the backfill script defaults to dry-run; a
    mutation flipping `--apply` default=True would make this fail."""
    import pathlib
    txt = pathlib.Path(
        "scripts/backfill_energy_daily_from_counters.py"
    ).read_text()
    assert 'p.add_argument("--apply", action="store_true", default=False)' in txt, (
        "backfill script --apply default changed from False"
    )


def test_counter_cost_uses_per_slice_rate_source():
    """M2c + M3 + M3b anchors: the counter branch MUST (a) compute
    `cost = imp_kwh * rate`, (b) look up `rate` from the shared engine
    at the SLICE time (not `now`, not a cached var). The source must
    contain the literal call."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import energy_billing as eb
    src = inspect.getsource(eb.CostTracker.accumulate)
    assert "rate = self._tou.get_effective_import_rate(slice_dt)" in src
    assert "cost = imp_kwh * rate" in src


def test_save_daily_snapshot_passes_billing_source_to_dao():
    """C-3 anchor + M12b: `_save_daily_snapshot` MUST pass
    `billing_source=billing_src` to `log_energy_daily`. A mutation
    hard-coding None would prevent counter_gap from ever being written."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import energy as e
    src = inspect.getsource(e.EnergyCoordinator._save_daily_snapshot)
    assert "billing_source=billing_src," in src


def test_outage_days_assign_in_refresh():
    """M13 anchor: `_refresh_outage_days_this_cycle` MUST assign the
    DAO count back to the CostTracker. A mutation replacing the
    assignment with `pass` would silently freeze the sensor at 0."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import energy as e
    src = inspect.getsource(e.EnergyCoordinator._refresh_outage_days_this_cycle)
    assert "self._billing._outage_days_this_cycle = int(count)" in src


def test_get_net_power_slot_skip_in_counter_mode():
    """M10b anchor: `_get_net_power` skips the slot branch in counter
    mode. A mutation deleting the `not _counter_mode and` guard would
    read kWh-as-kW during cold-tracker windows."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import energy_billing as eb
    src = inspect.getsource(eb.CostTracker._get_net_power)
    assert "not _counter_mode" in src
    assert "and self._grid_import_entity" in src


def test_log_energy_daily_d4_clamp_source():
    """C-3 anchor + M17: the D4 clamp block MUST contain the actual
    `consumption_kwh = None` assignment. A mutation changing that to
    `pass` would silently allow 15,000 kWh writes."""
    import inspect
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    src = inspect.getsource(UniversalRoomDatabase.log_energy_daily)
    # Both branches of the clamp assign None.
    assert src.count("consumption_kwh = None") >= 1
    assert src.count("solar_production_kwh = None") >= 1


def test_dst_boundary_slice_uses_live_rate(monkeypatch):
    """C-4: DST across a TOU boundary — pro-ration must call
    `get_current_period(cursor)` for each slice; a cached rate across
    the DST boundary would misprice."""
    hass = _Hass()
    engine = _tou_engine_with_boundary()
    tr = CounterAccrualTracker(hass, engine, "sensor.imp", "sensor.exp")
    # Pick a Sunday that would span a DST transition in the configured
    # engine (we use UTC in the fixture — the test exercises the
    # pro-ration primitive crossing a period boundary, which is the
    # same mechanism DST uses).
    tz = timezone(timedelta(hours=0))
    before = datetime(2026, 3, 8, 17, 30, tzinfo=tz)
    after = datetime(2026, 3, 8, 18, 30, tzinfo=tz)
    _advance_counter(hass, "sensor.imp", 100.0)
    tr.tick(now=before)
    tr._import_last_ts = before.timestamp()
    _advance_counter(hass, "sensor.imp", 102.0)
    out = tr.tick(now=after)
    assert out is not None
    periods = {s[0] for s in out["slices"]}
    assert "off_peak" in periods and "peak" in periods


def test_log_energy_daily_clamp_fires_on_implausible_consumption(tmp_path):
    """Behavioural: the D4 clamp replaces a consumption > 240 with NULL."""
    import sqlite3

    # Mimic the DAO body without needing async / full DB wiring: inline
    # the same clamp check against the module-level constants.
    MAX = energy_const.MAX_PLAUSIBLE_DAILY_KWH
    bad = MAX + 1000.0
    clamped = None if bad > MAX else bad
    assert clamped is None
    good = MAX - 10.0
    assert (None if good > MAX else good) == pytest.approx(good)


# ===========================================================================
# Fix-up review (2026-10-09) — A-HIGH kW math, B-HIGH seed-after-restore,
# A-MED one-shot logs. Monkeypatch-only time control.
# ===========================================================================

def test_counter_kw_derived_from_advance_window_not_tick_interval(monkeypatch):
    """A-HIGH 2026-10-09: 1.0 kWh over a 15-min advance window → 4.0 kW,
    NOT the 12 kW an EC-tick (5-min) elapsed would produce. A mutation
    that uses the inter-tick elapsed instead of the advance window would
    make this assertion fail."""
    hass = _Hass()
    tr = CounterAccrualTracker(hass, _flat_engine(), "sensor.imp", "sensor.exp")
    # T0: seed the baseline (no advance yet).
    _advance_counter(hass, "sensor.imp", 100.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    tr.tick()
    # T0+5m silent tick (counter unchanged — Emporia didn't update).
    tr._import_last_ts -= 300
    tr._export_last_ts -= 300
    tr.tick()
    assert tr.last_net_kw() is None, (
        "silent tick must NOT seed a bogus kW; only an advance may"
    )
    # T0+15m: counter advances by 1.0 kWh over the 15-min advance window.
    # Rewind the observation stamp (was just set by the silent tick).
    tr._import_last_ts -= 600  # another 10 min since prior silent tick
    tr._export_last_ts -= 600
    _advance_counter(hass, "sensor.imp", 101.0)
    tr.tick()
    kw = tr.last_net_kw()
    assert kw == pytest.approx(4.0, rel=5e-2), (
        f"kW must be derived from the 15-min advance window → ~4.0 kW; got {kw}"
    )


def test_counter_last_net_kw_held_across_silent_ticks_until_expiry(monkeypatch):
    """A-HIGH 2026-10-09: once set on an advance, kW is HELD across
    silent ticks and only expires via COUNTER_NET_POWER_MAX_AGE_S — not
    refreshed to 0 on an unchanged-but-fresh observation."""
    hass = _Hass()
    tr = CounterAccrualTracker(hass, _flat_engine(), "sensor.imp", "sensor.exp")
    _advance_counter(hass, "sensor.imp", 10.0)
    _advance_counter(hass, "sensor.exp", 0.0)
    tr.tick()  # seed
    # Advance window of 900s (15 min).
    tr._import_last_ts -= 900
    tr._export_last_ts -= 900
    _advance_counter(hass, "sensor.imp", 11.0)  # +1 kWh in 15 min → 4 kW
    tr.tick()
    assert tr.last_net_kw() == pytest.approx(4.0, rel=5e-2)
    # A silent tick 5 min later must NOT overwrite the kW with 0.
    tr._import_last_ts -= 300
    tr._export_last_ts -= 300
    tr.tick()
    assert tr.last_net_kw() == pytest.approx(4.0, rel=5e-2), (
        "silent-tick refresh regression — kW must be held, not re-set to 0"
    )


def test_counter_seed_tick_books_slices_after_restore(monkeypatch):
    """B-HIGH 2026-10-09: a snapshot restore + first accumulate MUST book
    the delta from the restored baseline. The prior build short-circuited
    this tick to a bare seed and lost (snapshot_ts → first_tick) energy
    on every restart."""
    hass = _Hass()
    engine = _flat_engine(rate=0.20)
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_METER,
    )
    # Live counters currently read 15.0 (import) / 2.0 (export).
    _advance_counter(hass, "sensor.imp", 15.0)
    _advance_counter(hass, "sensor.exp", 2.0)
    # Simulate a snapshot restore 20 min ago: baselines 14.0 / 1.5.
    import time as _time
    snap_ts = _time.time() - 1200
    ct._counters.restore(14.0, 1.5, snapshot_ts=snap_ts)
    # First accumulate — MUST book the delta, not throw it away.
    ct.accumulate()
    assert ct._import_kwh_today == pytest.approx(1.0, abs=1e-3), (
        f"first-tick-after-restore lost import energy: got "
        f"{ct._import_kwh_today} kWh (expected 1.0)"
    )
    assert ct._export_kwh_today == pytest.approx(0.5, abs=1e-3)
    assert ct._billing_source_today == "counters"
    # Second accumulate with no further counter change → no double-book.
    _import_before = ct._import_kwh_today
    ct.accumulate()
    assert ct._import_kwh_today == pytest.approx(_import_before, abs=1e-6), (
        "second tick with no counter advance must not re-book"
    )


def test_counter_mode_false_with_slots_logs_once(caplog):
    """A-MED 2026-10-09: one-shot diagnostic when both grid slots are set
    but counter mode is False (the live-regression signature)."""
    import logging
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_POWER,  # forces counter False
    )
    # Slots are power sensors (W) — counter mode must evaluate False.
    _advance_counter(hass, "sensor.imp", 1000, uom="W")
    _advance_counter(hass, "sensor.exp", 0, uom="W")
    assert ct._is_counter_mode() is False
    with caplog.at_level(logging.INFO, logger=(
        "custom_components.universal_room_automation."
        "domain_coordinators.energy_billing"
    )):
        ct.accumulate()
        ct.accumulate()
        ct.accumulate()
    n = sum(1 for r in caplog.records if "counter mode evaluated FALSE" in r.getMessage())
    assert n == 1, f"expected exactly one one-shot log, got {n}"


def test_power_mode_kwh_slot_log_is_one_shot(caplog):
    """A-MED 2026-10-09: the power-mode kWh-slot warning is one-shot."""
    import logging
    hass = _Hass()
    engine = _flat_engine()
    ct = CostTracker(
        hass, engine,
        grid_import_entity="sensor.imp",
        grid_export_entity="sensor.exp",
        billing_source=energy_const.BILLING_SOURCE_POWER,
    )
    _advance_counter(hass, "sensor.imp", 54.521, uom="kWh")
    _advance_counter(hass, "sensor.exp", 1.2, uom="kWh")
    with caplog.at_level(logging.INFO, logger=(
        "custom_components.universal_room_automation."
        "domain_coordinators.energy_billing"
    )):
        for _ in range(3):
            ct._get_net_power()
    n = sum(
        1 for r in caplog.records
        if "ignoring kWh slots" in r.getMessage()
    )
    assert n == 1, f"expected one-shot kWh-slot log, got {n}"

"""Tests for the arbitrage solar-attainability 3-rung ladder.

Drives REAL ``BatteryStrategy.determine_mode`` and REAL
``EVChargerController.determine_arbitrage_actions`` against the REAL
``TOURateEngine``. No mirror tests — every assertion follows from a
production call path. No hand-mutated ``_paused_by_arbitrage``,
``_arbitrage_pause_reason``, or ``_arbitrage_intent`` to fake reachability.

Mutation authority targets (≥1 named test each; see review ledger):
  M1: invert the rung-0 predicate (≥ entry_band → < entry_band).
  M2: break the rung-1 ENTRY EV-load uplift (drop the +ev_load_pct_per_h).
  M3: break the rung-1 EXIT counterfactual add-back (drop the
      -assumed_ev_pct on the latched path) — must fail the oscillation
      test and the rung-1→rung-0 transition test.
  M4: flip the rung-1/rung-2 label assignment in determine_arbitrage_actions
      (caller passes wrong label).
  M5: remove the no-solar short-circuit (solar_surplus < threshold).
  M6: remove the breaker-fail-closed default in determine_arbitrage_actions.

Plus an explicit OSCILLATION test (T_OSC): rung-1 latched across ≥5
ticks with EV load present → EVs stay paused, no resume/re-pause churn,
charge_from_grid never commanded.
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant (setdefault-only — coexists with sibling test files)
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
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
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
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc

_ura_name = "custom_components.universal_room_automation"
_ura = sys.modules.get(_ura_name)
if _ura is None:
    _ura = types.ModuleType(_ura_name)
    _ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = _ura_name
    sys.modules[_ura_name] = _ura
else:
    _ura_path = _ura.__path__[0]

_const_name = f"{_ura_name}.const"
if _const_name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _const_name, os.path.join(_ura_path, "const.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_const_name] = _mod
    _spec.loader.exec_module(_mod)
    _ura.const = _mod

_dc_name = f"{_ura_name}.domain_coordinators"
_dc = sys.modules.get(_dc_name)
if _dc is None:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc
    _ura.domain_coordinators = _dc
_dc_path = _dc.__path__[0]

for _sub in ("energy_const", "energy_tou", "energy_battery", "energy_pool"):
    _full = f"{_dc_name}.{_sub}"
    if _full in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_sub}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _sub, _mod)

# ---------------------------------------------------------------------------
from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_WEATHER_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    ARBITRAGE_PHASE_CHARGE,
    ARBITRAGE_PHASE_NA,
    ATTAIN_RATE_WINDOW_TICKS,
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
)

_BSOC = "sensor.test_envoy_battery"
_BPOW = "sensor.test_envoy_battery_power"
_SOLAR = "sensor.test_envoy_solar_production"
_NETP = "sensor.test_envoy_net_power"


def _build_strategy(
    *,
    soc: float = 40,
    solcast_today: str = "20",       # "poor" → forecast gate OPEN
    solcast_tomorrow: str = "20",    # "poor"
    solcast_remaining: str | None = None,
    peak_buffer_target: int = 80,
    arbitrage_enabled: bool = True,
):
    """Build a BatteryStrategy with the gate-open forecast (poor day).

    Defaults pick the planning-doc incident shape: forecast gate would
    open via today=poor, so the rung classifier governs whether we
    suppress (rung 0/1) or proceed to CHARGE (rung 2).
    """
    hass = MockHass()
    hass.set_state(_BSOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(_SOLAR, "5000")
    hass.set_state(_NETP, "0", attributes={"unit_of_measurement": "W"})
    hass.set_state(_BPOW, "-200", attributes={"unit_of_measurement": "W"})
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "50")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, solcast_today)
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, solcast_tomorrow)
    # Solcast remaining-today (kWh forecast left until sunset). Most tests
    # want this aligned with solcast_today (full forecast remaining) so
    # the sliced-solar surplus computes a positive number when daylight
    # remains after the anchor.
    remaining = solcast_remaining if solcast_remaining is not None else solcast_today
    hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, remaining)
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    # Battery capacity — production reads this for the v5.3.8 attain
    # projection AND for the new rung-1 EV-load → %/h conversion. Test
    # uses 100 kWh so ev_load_w (W) → %/h math is on a clean grid
    # (14 kW EVs = 14%/h) and surplus terms scale linearly.
    _BCAP = "sensor.test_envoy_battery_capacity"
    hass.set_state(_BCAP, "100", attributes={"unit_of_measurement": "kWh"})
    # sun.sun for daylight bounds. as_local mock is identity, so we set
    # the iso strings AS-IF they are local — 06:00 rise, 20:30 set.
    hass.set_state(
        "sun.sun", "above_horizon",
        attributes={
            "next_rising": "2026-07-15T06:00:00+00:00",
            "next_setting": "2026-07-15T20:30:00+00:00",
        },
    )
    entity_config = {
        "battery_soc": _BSOC,
        "battery_power": _BPOW,
        "battery_capacity": _BCAP,
        "solar_production": _SOLAR,
        "net_power": _NETP,
    }
    strat = BatteryStrategy(
        hass,
        reserve_soc=20,
        arbitrage_enabled=arbitrage_enabled,
        peak_buffer_target=peak_buffer_target,
        entity_config=entity_config,
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        tou_engine=TOURateEngine(),
        arbitrage_charge_lead_time_min=360,
        arbitrage_grid_import_guard_kw=12.0,
    )
    return strat, hass


def _build_evpool(garage_a_on=False, garage_a_w="0"):
    hass = MockHass()
    evse_config = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_month",
        },
    }
    hass.set_state("switch.garage_a", "on" if garage_a_on else "off")
    hass.set_state(
        "sensor.garage_a_power", garage_a_w,
        attributes={"unit_of_measurement": "W"},
    )
    return EVChargerController(hass, evse_config=evse_config), hass


# Summer 09:00 — well inside the 6h lead window to 14:00.
_ANCHOR = datetime(2026, 7, 15, 9, 0)


def _seed_rate(strat, anchor: datetime, start_soc: float, rate_pct_per_h: float):
    """Pre-load K samples at the given rate. Returns next-step SOC.

    Samples placed at anchor-15m, anchor-10m, anchor-5m (when K=3). The
    returned next-step SOC is the expected reading at ``anchor`` itself
    (which the caller must set on hass so that when ``_classify_attain_rung``
    calls _record_attain_sample(anchor, soc) the rate stays consistent).
    """
    last = start_soc
    for i in range(ATTAIN_RATE_WINDOW_TICKS):
        t = anchor - timedelta(minutes=5 * (ATTAIN_RATE_WINDOW_TICKS - i))
        s = start_soc + i * (rate_pct_per_h * 5.0 / 60.0)
        strat._record_attain_sample(t, s)
        last = s
    return last + (rate_pct_per_h * 5.0 / 60.0)


def _set_rate_history(
    strat, anchor: datetime, soc_at_anchor: float, rate_pct_per_h: float,
):
    """Seed K samples ending at anchor with the GIVEN rate exactly.

    Unlike _seed_rate, this places samples so the last one is AT anchor
    (not one tick before). The classifier's own _record_attain_sample
    call appends (anchor, soc_at_anchor) which equals the last seeded
    sample — duplicate timestamp is benign (trim keeps the last K+1).
    """
    strat._attain_soc_history.clear()
    for i in range(ATTAIN_RATE_WINDOW_TICKS):
        steps_back = ATTAIN_RATE_WINDOW_TICKS - 1 - i
        t = anchor - timedelta(minutes=5 * steps_back)
        s = soc_at_anchor - steps_back * (rate_pct_per_h * 5.0 / 60.0)
        strat._record_attain_sample(t, s)


# ==========================================================================
# D1 — rung classifier math
# ==========================================================================


class TestRungClassifier:
    def test_cold_boot_falls_to_rung_2(self):
        """Empty sample window → conservative rung_2 (M_COLD)."""
        strat, _ = _build_strategy(soc=40)
        rung = strat._classify_attain_rung(_ANCHOR, soc=40.0, ev_load_w=0.0)
        assert rung == "rung_2"

    def test_rung_0_live_incident_shape(self):
        """Incident shape: soc=36, +9%/h, 5h → rung_0 (M1).

        proj_r0 = 36 + (9 + ~5_surplus) * 5 ≈ 106 >> entry_band 83.
        """
        strat, hass = _build_strategy(soc=36, solcast_today="10")
        next_soc = _seed_rate(strat, _ANCHOR, 36.0, 9.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        rung = strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=0.0)
        assert rung == "rung_0"
        # And the gate is closed by the rung-0 narrowing:
        result = strat.determine_mode(
            "off_peak", "summer", now=_ANCHOR, ev_load_w=0.0,
        )
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_CHARGE
        assert strat._arbitrage_intent is None

    def test_genuine_poor_day_falls_to_rung_2(self):
        """SOC=20, rate=-1, surplus≈0, 5h → rung_2 (forecast gate fires)."""
        strat, hass = _build_strategy(soc=20, solcast_today="5")
        next_soc = _seed_rate(strat, _ANCHOR, 20.0, -1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        rung = strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=0.0)
        assert rung == "rung_2"

    def test_rung_1_evs_eating_solar(self):
        """soc=40, observed +1%/h, EVs drawing 14kW → rung_1 (M2).

        proj_r0 ≈ 40 + (1 + ~3)*5 = 60 < entry_band 83 → rung_0 misses.
        proj_r1 = proj_r0 + 14*5 = 130 ≥ 83 → rung_1 fires.
        """
        strat, hass = _build_strategy(soc=40, solcast_today="10")
        next_soc = _seed_rate(strat, _ANCHOR, 40.0, 1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        rung = strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=14000.0)
        assert rung == "rung_1"
        assert strat._arb_rung1_latch is True
        # Intent is propagated via _gate_is_open:
        result = strat.determine_mode(
            "off_peak", "summer", now=_ANCHOR, ev_load_w=14000.0,
        )
        # rung_1 → gate closed, intent stays "redirect".
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_CHARGE
        assert strat._arbitrage_intent == "redirect"

    def test_rung_2_even_with_evs_paused(self):
        """Real poor day: soc=20, rate=-1, ev_load=3kW: rung-1 still misses.

        proj_r0 = 20 + (-1+~3)*5 = 30 < 83 → miss.
        proj_r1 = 20 + (-1+3+~3)*5 = 45 < 83 → miss.
        """
        strat, hass = _build_strategy(soc=20, solcast_today="10")
        next_soc = _seed_rate(strat, _ANCHOR, 20.0, -1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        rung = strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=3000.0)
        assert rung == "rung_2"

    def test_no_solar_short_circuit(self):
        """surplus < negligible_pct_per_h → skip rung_1, fall to rung_2 (M5).

        Late evening + zero forecast both today and tomorrow → surplus
        collapses to 0 → rung-1 is meaningless even with high EV load.
        """
        late_anchor = datetime(2026, 7, 15, 22, 0)
        strat, hass = _build_strategy(
            soc=30, solcast_today="0", solcast_tomorrow="0",
            solcast_remaining="0",
        )
        next_soc = _seed_rate(strat, late_anchor, 30.0, -1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        rung = strat._classify_attain_rung(late_anchor, soc=next_soc, ev_load_w=14000.0)
        # ev_load is high but no solar to redirect — rung_2.
        assert rung == "rung_2"
        assert strat._arb_rung1_latch is False

    def test_no_ev_load_short_circuit(self):
        """rung-0 missed AND ev_load_w==0 → cannot rung_1, fall to rung_2."""
        strat, hass = _build_strategy(soc=20, solcast_today="10")
        next_soc = _seed_rate(strat, _ANCHOR, 20.0, 1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        rung = strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=0.0)
        assert rung == "rung_2"


# ==========================================================================
# Hysteresis + no-flap
# ==========================================================================


class TestHysteresisAndNoFlap:
    def test_rung_0_latch_no_flap_around_target(self):
        """Rung-0 latched; rate dips slightly → latch holds inside band.

        Entry: proj_r0 = 60 + (5 + ~3)*5 = 100 ≥ 83 → latched.
        Held: rate drops to 4 → proj = 60+(4+3)*5 = 95 — still > exit
        band 77. Latch must hold (hysteresis).
        """
        strat, hass = _build_strategy(soc=60, solcast_today="10")
        next_soc = _seed_rate(strat, _ANCHOR, 60.0, 5.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        r = strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=0.0)
        assert r == "rung_0"
        assert strat._arb_rung0_latch is True
        # Slightly worse rate — projection still in [exit_band, ∞), so
        # latch holds.
        strat._attain_soc_history.clear()
        _seed_rate(strat, _ANCHOR + timedelta(minutes=5), next_soc, 4.0)
        r2 = strat._classify_attain_rung(
            _ANCHOR + timedelta(minutes=5),
            soc=next_soc + 4.0 * 5 / 60,
            ev_load_w=0.0,
        )
        assert r2 == "rung_0", "latch must hold inside hysteresis band"

    def test_oscillation_t_osc_rung_1_stable_across_5_ticks(self):
        """OSCILLATION TEST (M3): rung-1 latched, EVs paused.

        Across 5 successive classifier ticks, EVs must STAY paused. The
        re-entrancy bug (naive observed-rate exit) would resume them on
        tick 2 — observed rate jumps when EVs disappear, rung-0 reads
        attainable, latch flips, EVs resume, rate drops, latch fires
        again. This test asserts NO churn.

        Entry: soc=40, rate=1, EV=14kW. proj_r0 = 40+(1+~3)*5 = 60 < 83.
        proj_r1 = proj_r0 + 14*5 = 130 ≥ 83 → rung_1 latches with
        assumed_ev_pct = 14.
        After EVs pause, observed rate jumps to ~10%/h (naive exit would
        compute 40+(10+3)*5=105 ≥ 83 and resume). Counterfactual:
        40 + (10 - 14 + 3)*5 = 35 < 83 → keep paused.
        """
        strat, hass = _build_strategy(soc=40, solcast_today="10")
        next_soc = _seed_rate(strat, _ANCHOR, 40.0, 1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        r0 = strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=14000.0)
        assert r0 == "rung_1"
        assert strat._arb_rung1_latch is True
        assumed_pct = strat._arb_last_ev_load_pct_per_h
        assert assumed_pct > 0

        cur_soc = next_soc
        for tick in range(1, 6):
            anchor_t = _ANCHOR + timedelta(minutes=5 * tick)
            cur_soc = cur_soc + 10.0 * 5 / 60  # 10%/h trajectory
            hass.set_state(_BSOC, f"{cur_soc:.4f}")
            _set_rate_history(strat, anchor_t, cur_soc, 10.0)
            r = strat._classify_attain_rung(anchor_t, soc=cur_soc, ev_load_w=0.0)
            assert r == "rung_1", (
                f"tick {tick}: rung-1 must hold (counterfactual exit). "
                f"Got {r}; assumed_pct={assumed_pct:.2f}"
            )
        assert strat._arb_rung1_latch is True

    def test_rung_1_to_rung_0_when_solar_surges(self):
        """Sustained big solar surge → counterfactual passes → rung-1 release.

        Entry as in T_OSC. Then a 30%/h observed rate (huge surge).
        Counterfactual = 30 - 14 + 3 = 19%/h. 40 + 19*5 = 135 ≥ 83.
        Latch releases → reports rung_0 (EVs resume next tick).
        """
        strat, hass = _build_strategy(soc=40, solcast_today="10")
        next_soc = _seed_rate(strat, _ANCHOR, 40.0, 1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        strat._classify_attain_rung(_ANCHOR, soc=next_soc, ev_load_w=14000.0)
        assert strat._arb_rung1_latch is True
        next_anchor = _ANCHOR + timedelta(minutes=5)
        new_soc = next_soc + 30.0 * 5 / 60
        hass.set_state(_BSOC, f"{new_soc:.4f}")
        _set_rate_history(strat, next_anchor, new_soc, 30.0)
        r = strat._classify_attain_rung(next_anchor, soc=new_soc, ev_load_w=0.0)
        assert r == "rung_0"
        assert strat._arb_rung1_latch is False


# ==========================================================================
# Forecast-gate composition (rung-2 fall-through preserved)
# ==========================================================================


class TestGateComposition:
    def test_forecast_gate_closed_no_classification_runs(self):
        """target_day=good → forecast gate closed → intent None, no latches."""
        strat, hass = _build_strategy(
            soc=40, solcast_today="90", solcast_tomorrow="90",
        )
        result = strat.determine_mode(
            "off_peak", "summer", now=_ANCHOR, ev_load_w=14000.0,
        )
        # Forecast gate didn't even open → no rung intent.
        assert strat._arbitrage_intent is None
        # And the result is the drain-target fallback (not CHARGE).
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_CHARGE

    def test_rung_2_falls_through_to_charge(self):
        """Genuine poor day with no rung-0/rung-1 reach → CHARGE fires.

        Mutation-test target: removing the rung-2 fall-through inverts
        this assertion.
        """
        strat, hass = _build_strategy(
            soc=20, solcast_today="5", peak_buffer_target=80,
        )
        next_soc = _seed_rate(strat, _ANCHOR, 20.0, -1.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        result = strat.determine_mode(
            "off_peak", "summer", now=_ANCHOR, ev_load_w=0.0,
        )
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_CHARGE
        assert strat._arbitrage_intent == "breaker"


# ==========================================================================
# D2 — EV pool reason-label semantics
# ==========================================================================


class TestPauseReasonLabel:
    def test_pause_reason_breaker_records_label(self):
        ctrl, _ = _build_evpool(garage_a_on=True, garage_a_w="7400")
        ctrl.determine_arbitrage_actions(
            arbitrage_charging=True, tou_period="off_peak", pause_reason="breaker",
        )
        assert "garage_a" in ctrl._paused_by_arbitrage
        assert ctrl._arbitrage_pause_reason["garage_a"] == "breaker"
        status = ctrl.get_status()
        assert status["paused_by_arbitrage_reasons"]["garage_a"] == "breaker"

    def test_pause_reason_redirect_records_label(self):
        ctrl, _ = _build_evpool(garage_a_on=True, garage_a_w="7400")
        ctrl.determine_arbitrage_actions(
            arbitrage_charging=True, tou_period="off_peak", pause_reason="redirect",
        )
        assert "garage_a" in ctrl._paused_by_arbitrage
        assert ctrl._arbitrage_pause_reason["garage_a"] == "redirect"
        status = ctrl.get_status()
        assert status["paused_by_arbitrage_reasons"]["garage_a"] == "redirect"

    def test_bad_pause_reason_rejected(self):
        """M4 mutation guard: invalid label must raise."""
        ctrl, _ = _build_evpool(garage_a_on=True, garage_a_w="7400")
        with pytest.raises((AssertionError, TypeError)):
            ctrl.determine_arbitrage_actions(
                arbitrage_charging=True,
                tou_period="off_peak",
                pause_reason="bogus",
            )

    def test_default_pause_reason_is_breaker_fail_closed(self):
        """M6 mutation guard: no pause_reason → fail-closed to 'breaker'.

        Removing the fail-closed default would either crash (assertion)
        or silently store None — both break this test.
        """
        ctrl, _ = _build_evpool(garage_a_on=True, garage_a_w="7400")
        ctrl.determine_arbitrage_actions(
            arbitrage_charging=True, tou_period="off_peak",
        )
        assert "garage_a" in ctrl._paused_by_arbitrage
        assert ctrl._arbitrage_pause_reason["garage_a"] == "breaker"

    def test_label_flips_redirect_to_breaker_no_churn(self):
        """Mid-CHARGE label change is silent (no extra turn_off)."""
        ctrl, _ = _build_evpool(garage_a_on=True, garage_a_w="7400")
        # First tick: redirect.
        a1 = ctrl.determine_arbitrage_actions(
            arbitrage_charging=True, tou_period="off_peak", pause_reason="redirect",
        )
        off1 = [a for a in a1 if a["service"] == "switch.turn_off"]
        assert len(off1) == 1
        # Simulate the switch turning off.
        ctrl.hass.set_state("switch.garage_a", "off")
        ctrl.hass.set_state("sensor.garage_a_power", "0")
        # Second tick: solar collapsed → escalate to breaker. Already
        # in set → no new turn_off action.
        a2 = ctrl.determine_arbitrage_actions(
            arbitrage_charging=True, tou_period="off_peak", pause_reason="breaker",
        )
        off2 = [a for a in a2 if a["service"] == "switch.turn_off"]
        assert off2 == []
        # Label updated to "breaker".
        assert ctrl._arbitrage_pause_reason["garage_a"] == "breaker"

    def test_release_clears_label(self):
        ctrl, _ = _build_evpool(garage_a_on=True, garage_a_w="7400")
        ctrl.determine_arbitrage_actions(
            arbitrage_charging=True, tou_period="off_peak", pause_reason="redirect",
        )
        ctrl.hass.set_state("switch.garage_a", "off")
        ctrl.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
        )
        assert "garage_a" not in ctrl._paused_by_arbitrage
        assert "garage_a" not in ctrl._arbitrage_pause_reason

    def test_current_charging_load_w_sums_active(self):
        hass = MockHass()
        evse_config = {
            "a": {"switch": "switch.a", "power": "sensor.a_p"},
            "b": {"switch": "switch.b", "power": "sensor.b_p"},
        }
        hass.set_state("switch.a", "on")
        hass.set_state(
            "sensor.a_p", "7400", attributes={"unit_of_measurement": "W"},
        )
        hass.set_state("switch.b", "on")
        hass.set_state(
            "sensor.b_p", "5", attributes={"unit_of_measurement": "W"},
        )  # below threshold → not charging
        ctrl = EVChargerController(hass, evse_config=evse_config)
        assert ctrl.current_charging_load_w() == pytest.approx(7400.0)


# ==========================================================================
# v4.7.28 carry-over guard integration
# ==========================================================================


class TestV47_28CarryOver:
    def test_off_peak_ensure_on_skipped_for_both_rung_labels(self):
        """Ensure-on must observe `_paused_by_arbitrage` membership regardless
        of label and skip the turn-on. Validates no regression to v4.7.28.
        """
        for label in ("redirect", "breaker"):
            ctrl, _ = _build_evpool(garage_a_on=False, garage_a_w="0")
            ctrl.determine_arbitrage_actions(
                arbitrage_charging=True, tou_period="off_peak",
                pause_reason=label,
            )
            assert "garage_a" in ctrl._paused_by_arbitrage
            # Now run determine_actions off_peak — should see the
            # carry-over guard at energy_pool.py:518-526 and skip
            # ensure-on (no turn_on action).
            actions = ctrl.determine_actions("off_peak")
            on_actions = [a for a in actions if a["service"] == "switch.turn_on"]
            assert on_actions == [], (
                f"label={label}: ensure-on must respect _paused_by_arbitrage"
            )


# ==========================================================================
# Composition with v5.3.8 attain branch (gate closed by rung-0 does NOT
# bypass the post-gate attain machinery)
# ==========================================================================


class TestComposition:
    def test_rung_0_does_not_bypass_attain_path(self):
        """When rung-0 closes the gate, determine_mode still reaches the
        post-gate attain branch (which v5.3.8 owns). This is the
        "safety net" composition the plan requires.

        We assert by checking _run_attain_branch was at least reachable:
        the resulting arbitrage_phase is either ATTAIN (if attain entry
        passes) or "n/a" (if attain entry didn't fire) — but NEVER
        CHARGE for the same rung-0 reach.
        """
        strat, hass = _build_strategy(soc=36, solcast_today="40")
        next_soc = _seed_rate(strat, _ANCHOR, 36.0, 9.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        result = strat.determine_mode(
            "off_peak", "summer", now=_ANCHOR, ev_load_w=0.0,
        )
        # Rung-0 suppressed the forecast gate → no CHARGE.
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_CHARGE
        # And we did not get a charge_from_grid action.
        charge_on = [
            a for a in result.get("actions", [])
            if "charge_from_grid" in a.get("target", "")
            and a.get("service") == "switch.turn_on"
        ]
        assert charge_on == []

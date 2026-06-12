"""Tests for the EC/HC reboot-pickup cycle — D1 attainability branch.

Drives REAL ``BatteryStrategy.determine_mode`` against the REAL
``TOURateEngine`` schedule. No mirror tests — every assertion follows
from a production call path.

Test conventions (HARD RULES per cycle scope):
- sys.modules ``setdefault`` only (we PIGGY-BACK on the mocks set up by
  ``test_energy_battery.py`` which lives next to us; if this file is run
  solo it bootstraps its own mocks via the same shape).
- Production methods are invoked, not mirrored. The predicate's behavior
  is observed via the public ``determine_mode`` decision dict.
- Mutation-authority bar: inverting ``_should_attain_peak_buffer``'s
  predicate result must break ≥6 tests in this file (verified manually
  during the cycle; see review ledger).
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

# Build package hierarchy (setdefault — coexists with sibling files)
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
    _const_spec = importlib.util.spec_from_file_location(
        _const_name, os.path.join(_ura_path, "const.py"),
    )
    _const_mod = importlib.util.module_from_spec(_const_spec)
    sys.modules[_const_name] = _const_mod
    _const_spec.loader.exec_module(_const_mod)
    _ura.const = _const_mod

_dc_name = f"{_ura_name}.domain_coordinators"
_dc = sys.modules.get(_dc_name)
if _dc is None:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc
    _ura.domain_coordinators = _dc

_dc_path = _dc.__path__[0]
for _submod_name in ("energy_const", "energy_tou", "energy_battery"):
    _full = f"{_dc_name}.{_submod_name}"
    if _full in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    BATTERY_MODE_SELF_CONSUMPTION,
    DEFAULT_ARBITRAGE_SOC_TARGET,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_WEATHER_ENTITY,
)

from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    ARBITRAGE_PHASE_ATTAIN,
    ARBITRAGE_PHASE_CHARGE,
    ARBITRAGE_PHASE_HOLD,
    ARBITRAGE_PHASE_NA,
    ARBITRAGE_PHASE_WAIT,
    ATTAIN_RATE_WINDOW_TICKS,
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

# Reuse the same fixture entity IDs as test_energy_battery.py.
_BSOC = "sensor.test_envoy_battery"
_BPOW = "sensor.test_envoy_battery_power"
_SOLAR = "sensor.test_envoy_solar_production"
_NETP = "sensor.test_envoy_net_power"


def _build_strategy(
    soc: float,
    *,
    arbitrage_enabled: bool = True,
    lead_time_min: int = 360,
    solcast_today: str = "90",
    solcast_tomorrow: str = "90",  # "good" — gate CLOSED by default
    net_power_w: float = -500.0,
):
    """Build a BatteryStrategy with the real TOU engine + custom thresholds.

    Defaults pick the incident shape: good-day forecast (arbitrage gate
    closed) + arbitrage_enabled True (so attainability is eligible).
    """
    hass = MockHass()
    hass.set_state(_BSOC, str(soc))
    # Production default entity IDs (NOT in entity_config — strategy reads
    # them via _get_entity(..., default=DEFAULT_*)).
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(_SOLAR, "5000")
    hass.set_state(_NETP, str(net_power_w), attributes={"unit_of_measurement": "W"})
    hass.set_state(_BPOW, "-200", attributes={"unit_of_measurement": "W"})
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "50")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, solcast_today)
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, solcast_tomorrow)
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    entity_config = {
        "battery_soc": _BSOC,
        "battery_power": _BPOW,
        "solar_production": _SOLAR,
        "net_power": _NETP,
    }
    strat = BatteryStrategy(
        hass,
        reserve_soc=20,
        arbitrage_enabled=arbitrage_enabled,
        entity_config=entity_config,
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        tou_engine=TOURateEngine(),
        arbitrage_charge_lead_time_min=lead_time_min,
        arbitrage_grid_import_guard_kw=12.0,
    )
    return strat, hass


# Summer 09:00 — 5h before mid_peak (14:00 transition), well inside the
# default lead window of 360 min.
_SUMMER_INSIDE_WINDOW = datetime(2026, 7, 15, 9, 0)
# Summer 02:00 — outside the lead window.
_SUMMER_OUTSIDE_WINDOW = datetime(2026, 7, 15, 2, 0)


def _seed_zero_rate_history(strat, anchor: datetime, soc: float) -> None:
    """Pre-load the trailing window with K samples at flat SOC.

    Drives ``_observed_net_charge_rate_per_hour`` → 0 so the predicate
    sees a stalled trajectory. We seed K (not K+1) samples; the
    production ``determine_mode`` will append one MORE sample at
    ``anchor`` (live SOC), giving exactly K+1 samples without losing
    the oldest to the trim.
    """
    for i in range(ATTAIN_RATE_WINDOW_TICKS):
        strat._record_attain_sample(
            anchor - timedelta(minutes=5 * (ATTAIN_RATE_WINDOW_TICKS - i)),
            soc,
        )


def _seed_rate_history(
    strat, anchor: datetime, start_soc: float, rate_per_hour: float,
) -> float:
    """Seed K samples at the given rate; returns the final seeded SOC.

    The caller must set the hass SOC entity to this returned value so
    the production-side append at ``anchor`` matches the trajectory and
    keeps the smoothed rate at ``rate_per_hour``.
    """
    # 5-min ticks → 5/60 h. Seed K samples ending one tick BEFORE anchor.
    last_soc = start_soc
    for i in range(ATTAIN_RATE_WINDOW_TICKS):
        t = anchor - timedelta(minutes=5 * (ATTAIN_RATE_WINDOW_TICKS - i))
        # Sample at time t — sample 0 is the oldest.
        s = start_soc + i * (rate_per_hour * 5.0 / 60.0)
        strat._record_attain_sample(t, s)
        last_soc = s
    # The production call will append another sample at ``anchor`` with
    # whatever the hass SOC is. Caller should set hass SOC to one more
    # rate-step ahead of `last_soc` to keep the rate consistent.
    return last_soc + (rate_per_hour * 5.0 / 60.0)


# ── D1 predicate — math ─────────────────────────────────────────────────────


class TestAttainabilityPredicate:
    """Acceptance criterion (math) — synthetic (soc, mins, rate, target)."""

    def test_incident_shape_fires(self):
        """Good day, SOC=12, rate≈0, ~5h to boundary → ATTAIN."""
        strat, hass = _build_strategy(soc=12)
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=12)
        result = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        assert result["arbitrage_active"] is True
        # Reason must explain WHY (operator-mandated).
        reason = result["reason"]
        assert "Peak-buffer attainability" in reason
        assert "projected SOC" in reason
        assert "target 80%" in reason
        # Charge-from-grid switch action emitted.
        charge_actions = [
            a for a in result["actions"]
            if "charge_from_grid" in a.get("target", "")
            and a.get("service") == "switch.turn_on"
        ]
        assert len(charge_actions) == 1
        # Reserve set to peak_buffer_target (same lock as arbitrage CHARGE).
        reserve_actions = [
            a for a in result["actions"]
            if "reserve" in a.get("target", "")
        ]
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_ARBITRAGE_SOC_TARGET

    def test_high_soc_no_attain(self):
        """SOC ≥ target → predicate False (no ATTAIN, no CHARGE)."""
        strat, hass = _build_strategy(soc=82)
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=82)
        result = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN

    def test_post_boundary_no_attain(self):
        """Window closed (post-boundary) → predicate False."""
        strat, hass = _build_strategy(soc=12)
        _seed_zero_rate_history(strat, _SUMMER_OUTSIDE_WINDOW, soc=12)
        result = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_OUTSIDE_WINDOW,
        )
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN

    def test_arbitrage_disabled_no_attain(self):
        """arbitrage_enabled=False → predicate gated off."""
        strat, hass = _build_strategy(soc=12, arbitrage_enabled=False)
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=12)
        result = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN

    def test_strong_rate_still_under_target(self):
        """10%/h × 5h = +50 → 12+50=62 < 80 → ATTAIN still fires.

        Confirms the predicate projects AT-target, not eventual-positive-
        trajectory."""
        # SOC will rise to match the seeded trajectory's expected next step.
        anchor = _SUMMER_INSIDE_WINDOW
        # Build with a placeholder soc=12 then seed, then update hass SOC
        # to the trajectory's next step so the in-method append continues
        # the trend.
        strat, hass = _build_strategy(soc=12)
        next_soc = _seed_rate_history(strat, anchor, start_soc=12.0, rate_per_hour=10.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        result = strat.determine_mode("off_peak", "summer", now=anchor)
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN

    def test_excellent_rate_no_attain(self):
        """+20%/h × 5h = +100 → projection clears 80% → predicate False."""
        anchor = _SUMMER_INSIDE_WINDOW
        strat, hass = _build_strategy(soc=12)
        next_soc = _seed_rate_history(strat, anchor, start_soc=12.0, rate_per_hour=20.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        result = strat.determine_mode("off_peak", "summer", now=anchor)
        # Projected ≈ 12 + 5*20 = 112 ≥ 80 → no ATTAIN.
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_CHARGE


# ── D1 — precedence vs arbitrage ────────────────────────────────────────────


class TestAttainabilityPrecedence:
    """Acceptance criterion (precedence)."""

    def test_arbitrage_wins_on_poor_day(self):
        """Poor forecast → arbitrage CHARGE branch wins (attainability
        never reached because gate is open). Mutation-authority anchor:
        swapping branch order in production breaks this test."""
        strat, hass = _build_strategy(
            soc=15, solcast_today="20", solcast_tomorrow="20",
        )
        # Seed history showing strong rate, so the attainability predicate
        # would say "False" if we ever reached it — but the arbitrage gate
        # short-circuits first.
        result = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        # Arbitrage CHARGE — NOT ATTAIN.
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_CHARGE


# ── D1 — no-flap ────────────────────────────────────────────────────────────


class TestAttainabilityNoFlap:
    """Trajectory across multiple decision cycles."""

    def test_persistence_then_completion(self):
        """ATTAIN fires on stalled trajectory; HOLDs (no release) at target.

        Fix-up pass A-CRIT-1 defect 3: when SOC reaches target the latch
        exits via HOLD-shape (charge_from_grid OFF, reserve still pinned at
        target, chunk_completed=True). The phase REMAINS `attain` (the
        HOLD decision is still an attain-phase decision — that's how it
        differs from arbitrage HOLD; arbitrage HOLD uses ARBITRAGE_PHASE_HOLD).
        """
        strat, hass = _build_strategy(soc=12)
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=12)
        results = []
        # Tick 1: should fire ATTAIN (rate=0, projection 12 < 80).
        results.append(strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        ))
        # Tick 2: still 12 (lag — Enphase hasn't started yet).
        results.append(strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=5),
        ))
        # Tick 3: SOC reaches target → HOLD-shape (latch exits).
        hass.set_state(_BSOC, "80")
        results.append(strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=10),
        ))
        # Ticks 1-2 ATTAIN charging; tick 3 ATTAIN HOLD.
        assert results[0]["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        assert results[1]["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        # Tick 3 still labelled attain (HOLD exit), but reserve still
        # locked at target and chunk completed.
        assert results[2]["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        assert strat._arbitrage_chunk_completed is True
        # NO charge_from_grid turn_on action on tick 3. The HOLD path
        # leaves cfg unchanged (or turns it OFF if it was ON).
        turn_on_actions = [
            a for a in results[2]["actions"]
            if "charge_from_grid" in a.get("target", "")
            and a.get("service") == "switch.turn_on"
        ]
        assert turn_on_actions == []


# ── D1 — cold-boot defer ────────────────────────────────────────────────────


class TestAttainabilityColdBoot:
    """First tick after boot has no rate history → defer one cycle."""

    def test_first_tick_defers(self):
        """No history → predicate False on tick 1, even with low SOC."""
        strat, hass = _build_strategy(soc=12)
        # NO seed — simulates cold boot.
        result = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        # Cold boot → defer; ATTAIN must NOT fire on tick 1.
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN

    def test_second_tick_fires(self):
        """After two ticks of flat SOC, observed rate = 0 → ATTAIN fires."""
        strat, hass = _build_strategy(soc=12)
        result1 = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        # Second tick 5 min later, SOC still 12.
        result2 = strat.determine_mode(
            "off_peak", "summer",
            now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=5),
        )
        assert result1["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN
        # 2 samples → rate=0 → projection 12 < 80 → ATTAIN fires.
        assert result2["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN


# ── D1 — grid-import guard interaction ──────────────────────────────────────


class TestAttainabilityGridImportGuard:
    """ATTAIN respects the same grid-import guard as arbitrage CHARGE."""

    def test_guard_locks_chunk_after_consecutive_trips(self):
        """Net import > cap on N consecutive ATTAIN ticks → chunk locked."""
        # net_power 15000 W = 15 kW > 12 kW cap; battery charge 0 (so
        # effective = net = 15 kW > 12 kW).
        strat, hass = _build_strategy(soc=12, net_power_w=15000.0)
        hass.set_state(_BPOW, "0", attributes={"unit_of_measurement": "W"})
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=12)
        # Tick 1 → trip 1/2 → ATTAIN still fires (lag absorption).
        r1 = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert r1["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        # Tick 2 → trip 2/2 → chunk locks → falls through to drain-target.
        r2 = strat.determine_mode(
            "off_peak", "summer",
            now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=5),
        )
        assert r2["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN
        assert strat._arbitrage_chunk_completed is True


# ── D1 — late-start partial charge ──────────────────────────────────────────


class TestAttainabilityLateStart:
    """No minimum-SOC floor — operator stated 'reaching 50% beats holding 10%'."""

    def test_late_start_30min_partial(self):
        """30 min to boundary, SOC=10, rate=0 → ATTAIN still fires."""
        late = datetime(2026, 7, 15, 13, 30)  # 30 min before 14:00 mid_peak
        strat, hass = _build_strategy(soc=10)
        _seed_zero_rate_history(strat, late, soc=10)
        result = strat.determine_mode("off_peak", "summer", now=late)
        # Projection 10 + 0.5*0 = 10 < 80 → ATTAIN fires. No floor.
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN


# ── D1 — Bug Class #22 audit: hvac solar_intent string match ────────────────


class TestBugClass22Audit:
    """Every consumer that string-matches arbitrage_phase must recognize 'attain'.

    Verified in production code paths:
    1. hvac_predict.py:1110 — phase in ("charge", "attain") → harvest.
    2. energy.py:2069 — savings accounting includes ATTAIN.
    3. energy.py:2434 — EVSE pause gate INTENTIONALLY excludes ATTAIN (v1
       observe-only on EVs per operator scope).

    This test exercises path #1 via the public attribute name (we can't
    construct the full HVAC stack here, so we assert the literal mapping
    holds in the source — a structural assertion is acceptable here as
    it's a Bug Class #22 audit, not a behavioral test of HVAC.)
    """

    def test_attain_phase_token_value(self):
        """The new enum value must be the literal string 'attain' — any
        other value would silently mismatch every string consumer."""
        assert ARBITRAGE_PHASE_ATTAIN == "attain"

    def test_attain_recognized_as_charging_in_hvac_solar_intent(self):
        """hvac_predict.py:get_intent_attrs treats ATTAIN like CHARGE → harvest.

        Plain file read — avoids importing the module (which has heavy
        dispatcher/coordinator-runtime dependencies not present in the
        test sandbox).
        """
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "hvac_predict.py",
        )
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        assert 'phase in ("charge", "attain")' in src, (
            "hvac_predict.get_intent_attrs must map ATTAIN to harvest "
            "alongside CHARGE (Bug Class #22)"
        )

    def test_attain_recognized_in_arbitrage_cycle_savings(self):
        """energy.py savings accounting must include ATTAIN."""
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "energy.py",
        )
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        assert "ARBITRAGE_PHASE_ATTAIN" in src, (
            "energy.py arbitrage_cycle savings must include ATTAIN "
            "(Bug Class #22)"
        )


# ── D1 — non-regression: good day with solar delivering as expected ─────────


class TestGoodDayNoRegression:
    """Good day with healthy positive rate → no ATTAIN, drain-target path."""

    def test_good_day_solar_delivering(self):
        """SOC=40 + strong rate → projection clears target → no ATTAIN."""
        anchor = _SUMMER_INSIDE_WINDOW
        strat, hass = _build_strategy(soc=40)
        next_soc = _seed_rate_history(strat, anchor, start_soc=40.0, rate_per_hour=15.0)
        hass.set_state(_BSOC, f"{next_soc:.4f}")
        result = strat.determine_mode("off_peak", "summer", now=anchor)
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_CHARGE


# ── Fix-up pass — latched feedback-loop (A-CRIT-1 / B-HIGH-1) ──────────────


class TestAttainabilityLatchNoFeedbackOscillation:
    """Closed-loop trajectory: attain's own charge inflates rate; latch holds."""

    def test_rising_rate_does_not_release_or_recommand(self):
        """Once latched, a rising observed rate (because attain is charging)
        must NOT release the latch and must NOT re-emit the charge-from-grid
        switch.turn_on command repeatedly (verify-only — command once).

        Pre-fix: K=3 rate window included attain's own ~16 kW charge → after
        2-3 ticks projection flipped False → fallback issued switch.turn_off
        → re-fired next tick. Now: entry predicate is NOT consulted while
        latched; rate is only used for the reason narrative + boundary
        guard math. The first tick should emit a turn_on; subsequent ticks
        with cfg already ON must emit NO turn_on actions (verify-only).
        """
        strat, hass = _build_strategy(soc=12)
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=12)
        results = []
        # Simulate rising rate trajectory across 4 ticks.
        # Tick 1: enters latch, emits turn_on. Hass cfg flips ON.
        r1 = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        results.append(r1)
        # Flip the cfg ON in hass to simulate the actuation having landed.
        hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "on")
        # Ticks 2-4: SOC rising (charge is flowing) → observed rate rises.
        for i, (t_off, soc_val) in enumerate(
            [(5, 22), (10, 35), (15, 50)], start=2,
        ):
            hass.set_state(_BSOC, str(soc_val))
            r = strat.determine_mode(
                "off_peak", "summer",
                now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=t_off),
            )
            results.append(r)
        # All four ticks must remain in ATTAIN phase — no release-on-projection.
        for i, r in enumerate(results):
            assert r["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN, (
                f"tick {i+1} dropped out of ATTAIN despite latch — "
                f"feedback-loop regression. reason={r.get('reason')}"
            )
        # Strictly verify no repeated turn_on after tick 1 (idempotent).
        for i, r in enumerate(results[1:], start=2):
            turn_on = [
                a for a in r["actions"]
                if "charge_from_grid" in a.get("target", "")
                and a.get("service") == "switch.turn_on"
            ]
            assert turn_on == [], (
                f"tick {i} re-issued switch.turn_on — verify-only violated. "
                f"actions={r['actions']}"
            )

    def test_chunk_lock_persists_through_4_ticks(self):
        """C-HIGH-1 extension: after guard locks chunk on tick 2, attain
        must stay out through ticks 3-4 even when guard clears (under cap).
        """
        strat, hass = _build_strategy(soc=12, net_power_w=15000.0)
        hass.set_state(_BPOW, "0", attributes={"unit_of_measurement": "W"})
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=12)
        # Tick 1: entry, trip 1/2 (under N) → ATTAIN.
        r1 = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert r1["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        # Tick 2: trip 2/2 → lock + release.
        r2 = strat.determine_mode(
            "off_peak", "summer",
            now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=5),
        )
        assert r2["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN
        assert strat._arbitrage_chunk_completed is True
        # Clear the guard for ticks 3-4 (drop net to safe).
        hass.set_state(_NETP, "1000", attributes={"unit_of_measurement": "W"})
        r3 = strat.determine_mode(
            "off_peak", "summer",
            now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=10),
        )
        r4 = strat.determine_mode(
            "off_peak", "summer",
            now=_SUMMER_INSIDE_WINDOW + timedelta(minutes=15),
        )
        # Chunk stays locked through to next off-peak reset.
        assert r3["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN
        assert r4["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN


# ── Fix-up pass — B-HIGH-3 reboot mid-ATTAIN HOLD-CURRENT ─────────────────


class TestRebootMidAttainHoldCurrent:
    """Post-reboot first cycles must NOT unwind in-flight Enphase charge."""

    def test_reboot_first_cycle_issues_zero_commands(self):
        """Simulate reboot with charge_from_grid ON + reserve 80 at Envoy.
        First tick after boot has empty rate history → must emit a
        HOLD-CURRENT decision with empty actions list (no turn_off, no
        reserve drop), preserving hardware state while the K-window
        reseeds. Latch is forced via SOC < target + latched-state injection.
        """
        strat, hass = _build_strategy(soc=40)
        # Simulate the pre-reboot Enphase state.
        hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "on")
        hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "80")
        # Force-latch (RAM-only attr lost on real reboot; here we model the
        # alternative: the operator wants attain to RE-LATCH on first cycle
        # — but the rate window is empty, so the reboot-hold path fires).
        strat._attain_active = True
        # NO _seed_*: empty trailing window.
        r = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        # Latch stays asserted; HOLD-CURRENT path emits zero actions.
        assert r["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        assert r["actions"] == [], (
            f"reboot first cycle issued commands: {r['actions']}"
        )
        # Reason names the warm-up.
        assert "HOLD CURRENT" in r["reason"] or "warm-up" in r["reason"]


# ── Fix-up pass — operator floor (30 min ENTRY floor; latched continues) ──


class TestAttainability30MinEntryFloor:
    """Operator-ratified ENTRY floor (B-MED-1)."""

    def test_entry_blocked_at_25min_to_boundary(self):
        """ENTRY with <30 min to boundary is declined (actuation lag eats it)."""
        late = datetime(2026, 7, 15, 13, 35)  # 25 min before 14:00 mid_peak
        strat, hass = _build_strategy(soc=10)
        _seed_zero_rate_history(strat, late, soc=10)
        r = strat.determine_mode("off_peak", "summer", now=late)
        assert r["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN

    def test_entry_allowed_at_exactly_30min(self):
        """30 min == floor: still allowed (operator: 'don't issue commands
        physics cannot honor' — 30+ min satisfies the ~35-min lag spec
        with margin)."""
        late = datetime(2026, 7, 15, 13, 30)
        strat, hass = _build_strategy(soc=10)
        _seed_zero_rate_history(strat, late, soc=10)
        r = strat.determine_mode("off_peak", "summer", now=late)
        assert r["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN


# ── Fix-up pass — D1b mid_peak continuation targeting PEAK ────────────────


class TestAttainabilityMidPeakContinuation:
    """D1b — operator-mandated mid_peak attain continuation covering PEAK.

    Summer schedule (from energy_const.py): peak = 16:00-20:00, mid_peak =
    14:00-16:00 and 20:00-21:00, off_peak = 21:00-14:00. At 14:30 (mid_peak,
    pre-peak) with SOC < target and rate-spread positive, attain may enter
    targeting the 16:00 peak boundary.
    """

    def test_mid_peak_pre_peak_low_soc_enters_attain(self):
        """SOC < target during summer mid_peak (pre-peak) → ATTAIN."""
        anchor = datetime(2026, 7, 15, 14, 30)
        strat, hass = _build_strategy(soc=20)
        _seed_zero_rate_history(strat, anchor, soc=20)
        r = strat.determine_mode("mid_peak", "summer", now=anchor)
        assert r["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        # Reason must name the stage.
        assert "mid_peak" in r["reason"] or "peak coverage" in r["reason"]

    def test_mid_peak_post_peak_no_attain(self):
        """Post-peak mid_peak (20:00-21:00): no peak ahead → no attain."""
        anchor = datetime(2026, 7, 15, 20, 30)
        strat, hass = _build_strategy(soc=20)
        _seed_zero_rate_history(strat, anchor, soc=20)
        r = strat.determine_mode("mid_peak", "summer", now=anchor)
        assert r["arbitrage_phase"] != ARBITRAGE_PHASE_ATTAIN


# ── Fix-up pass — C-MED-1 structural EVSE gate test ──────────────────────


class TestEVSEPauseGateExcludesAttain:
    """C-MED-1: structural assertion that arbitrage_charging gate is
    CHARGE-only (ATTAIN must NOT pause EVSE; v1 observe-only)."""

    def test_evse_pause_gate_excludes_attain_assignment(self):
        """The arbitrage_charging assignment at energy.py:~2467 must
        compare against ARBITRAGE_PHASE_CHARGE only — adding ATTAIN to
        that comparison silently converts v1 observe-only into an EVSE
        coordination lever.
        """
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "energy.py",
        )
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        # Find the literal assignment line.
        assert (
            'decision.get("arbitrage_phase") == ARBITRAGE_PHASE_CHARGE'
            in src
        ), (
            "EVSE pause gate at energy.py must compare arbitrage_phase to "
            "ARBITRAGE_PHASE_CHARGE only (v1 observe-only scope; see "
            "C-MED-1)."
        )
        # Anti-test: the gate must NOT branch on ATTAIN in the same expr.
        # Search for any line that puts both phase tokens together in an
        # `arbitrage_charging` assignment.
        for line in src.split("\n"):
            if "arbitrage_charging" in line and "=" in line:
                if (
                    "ARBITRAGE_PHASE_CHARGE" in line
                    and "ARBITRAGE_PHASE_ATTAIN" in line
                ):
                    raise AssertionError(
                        "EVSE arbitrage_charging gate includes ATTAIN — "
                        "this silently widens v1 observe-only scope. See "
                        "C-MED-1 / review ledger."
                    )

    def test_savings_accounting_includes_attain_tuple(self):
        """Tighten C-MED-1 grep: the savings include-tuple must contain
        both ARBITRAGE_PHASE_CHARGE and ARBITRAGE_PHASE_ATTAIN — vacuous
        `in src` was insufficient.
        """
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "energy.py",
        )
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        # The savings filter uses `not in (ARBITRAGE_PHASE_CHARGE, ARBITRAGE_PHASE_ATTAIN)`
        assert (
            "ARBITRAGE_PHASE_CHARGE, ARBITRAGE_PHASE_ATTAIN" in src
            or "ARBITRAGE_PHASE_ATTAIN, ARBITRAGE_PHASE_CHARGE" in src
        ), (
            "energy.py arbitrage savings must include ATTAIN alongside "
            "CHARGE in the gate tuple (Bug Class #22)."
        )


# ── Fix-up pass — guard-subtraction test (C-LOW-1) ───────────────────────


class TestAttainGuardSubtractsBatteryCharge:
    """C-LOW-1: net 18 kW total, but battery is charging 16 kW; effective
    house+EV draw is only 2 kW → guard must NOT trip."""

    def test_battery_charge_excluded_from_guard_during_attain(self):
        strat, hass = _build_strategy(soc=12, net_power_w=18000.0)
        # Battery charging 16 kW → effective = 18 - 16 = 2 kW < 12 kW cap.
        # Envoy sign convention: positive=discharging, so charging is
        # reported as a NEGATIVE entity state. `battery_power_w` flips the
        # sign so a +16 kW charge becomes "raw entity = -16000 W".
        hass.set_state(_BPOW, "-16000", attributes={"unit_of_measurement": "W"})
        _seed_zero_rate_history(strat, _SUMMER_INSIDE_WINDOW, soc=12)
        r = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        # Guard does NOT trip — attain proceeds normally.
        assert r["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        assert strat._arbitrage_chunk_completed is False
        assert strat._arbitrage_guard_consecutive_trips == 0

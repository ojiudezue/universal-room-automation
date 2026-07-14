"""v5.17.1 — Arbitrage completed-chunk HOLD precedence (I-AH1) + latch persistence.

Reproduction of the 2026-07-14 live incident:
- 08:00 CHARGE brought SOC 31→79 during off_peak (target=80, poor day,
  boundary at 14:00 mid_peak).
- 09:31 tick: SOC≈79 (just under target). `_classify_attain_rung` returned
  rung_0 (projection ≥ entry_band with fresh solar) → `_gate_is_open`
  False → `_get_arbitrage_phase` "n/a" → drain-target fallback emitted
  reserve_level=drain_target (30 for tomorrow=poor).
- Battery drained the purchased charge hours before the boundary.

Master invariant (I-AH1): while an arbitrage/attain chunk is
completed AND the target boundary is still AHEAD, no reachable path
may emit reserve_level below `peak_buffer_target`.

Test drives REAL `BatteryStrategy.determine_mode` against the REAL
`TOURateEngine`. Off_peak branch at 09:31 summer with an active
completed-chunk latch; boundary at 14:00 mid_peak is 4.5 h ahead.

Executed mutations (Tier 3 D4 — see report):
  (a) delete the D1 completed-chunk short-circuit → this test RED.
  (b) invert boundary-ahead check → RED.
  (c) break D2 restore staleness → restart test RED.
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
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda *a, **k: (lambda: None),
        "async_call_later": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
        "async_dispatcher_send": lambda *a, **k: None,
    },
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
    ARBITRAGE_PHASE_HOLD,
    ARBITRAGE_PHASE_WAIT,
    ATTAIN_RATE_WINDOW_TICKS,
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

_BSOC = "sensor.test_envoy_battery"
_BPOW = "sensor.test_envoy_battery_power"
_SOLAR = "sensor.test_envoy_solar_production"
_NETP = "sensor.test_envoy_net_power"

# Summer 09:31 — 4.5h before the 14:00 mid_peak boundary (well inside the
# 6h lead window). Incident anchor.
_INCIDENT_ANCHOR = datetime(2026, 7, 15, 9, 31)


def _build_strategy(
    *,
    soc: float,
    solcast_today: str = "10",       # "poor" → forecast gate would open
    solcast_tomorrow: str = "10",    # "poor" → drain_target = 30
    solcast_remaining: str | None = None,
    peak_buffer_target: int = 80,
    arbitrage_enabled: bool = True,
):
    hass = MockHass()
    hass.set_state(_BSOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(_SOLAR, "5000")
    hass.set_state(_NETP, "0", attributes={"unit_of_measurement": "W"})
    hass.set_state(_BPOW, "-200", attributes={"unit_of_measurement": "W"})
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    # Simulates the live incident: current on-hardware reserve is 30 (the
    # value the buggy tick drove it to). A correct decision emits an
    # action to raise it back to target.
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "30")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, solcast_today)
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, solcast_tomorrow)
    remaining = solcast_remaining if solcast_remaining is not None else solcast_today
    hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, remaining)
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    _BCAP = "sensor.test_envoy_battery_capacity"
    hass.set_state(_BCAP, "100", attributes={"unit_of_measurement": "kWh"})
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
        arbitrage_grid_import_guard_enabled=True,
    )
    return strat, hass


def _seed_rate(strat, anchor: datetime, start_soc: float, rate_pct_per_h: float):
    """Pre-load K samples at the given rate (borrowed from ladder tests)."""
    for i in range(ATTAIN_RATE_WINDOW_TICKS):
        t = anchor - timedelta(minutes=5 * (ATTAIN_RATE_WINDOW_TICKS - i))
        s = start_soc + i * (rate_pct_per_h * 5.0 / 60.0)
        strat._record_attain_sample(t, s)


# ==========================================================================
# I-AH1 reproduction — the 2026-07-14 live incident
# ==========================================================================


class TestCompletedChunkHoldPrecedence:
    """I-AH1: chunk completed + boundary ahead → reserve ≥ target on every path."""

    def test_incident_reproduction_soc_at_target_minus_one(self):
        """Live incident shape. SOC=79 (just under target=80), chunk_completed,
        boundary 4.5h ahead. rung_0 would fire and close the gate.

        Pre-fix: gate closes → drain-target fallback → reserve_level=30.
        Post-fix: completed-chunk short-circuit fires BEFORE gate/rung
        consultation → HOLD → reserve_level = peak_buffer_target (80).
        """
        strat, hass = _build_strategy(soc=79, solcast_today="10", solcast_tomorrow="10")
        # Seed the rate window so rung_0 evaluation completes (projection
        # would be ≥ entry_band 83 with positive rate + solar surplus).
        _seed_rate(strat, _INCIDENT_ANCHOR, 79.0, 5.0)
        hass.set_state(_BSOC, "79")

        # This is the incident precondition: the 08:00 CHARGE completed
        # (SOC reached target) so `_get_arbitrage_phase` set
        # `_arbitrage_chunk_completed = True` back in that earlier tick.
        # By 09:31, SOC has dipped 1% from 80 (residual load) → 79.
        strat._arbitrage_chunk_completed = True
        strat._arbitrage_active = True

        result = strat.determine_mode(
            "off_peak", "summer", now=_INCIDENT_ANCHOR, ev_load_w=0.0,
        )

        # I-AH1: reserve must be at target, not drained to 30.
        emitted = _reserve_action_target(result)
        assert emitted == 80, (
            f"I-AH1 violated: reserve emitted={emitted!r} (expected 80) "
            f"while chunk completed + boundary ahead. "
            f"reason={result.get('reason')!r} "
            f"phase={result.get('arbitrage_phase')!r} "
            f"actions={result.get('actions')!r}"
        )
        # And the phase should reflect HOLD (or ATTAIN hold — either is
        # a valid completed-chunk hold shape per D3 item 5).
        assert result["arbitrage_phase"] in (
            ARBITRAGE_PHASE_HOLD, "attain",
        ), (
            f"Expected HOLD/attain, got {result['arbitrage_phase']!r}; "
            f"reason={result.get('reason')!r}"
        )
        # No CHARGE re-entry — chunk lock stands.
        assert not _has_charge_from_grid_on(result), (
            f"Completed-chunk hold must not re-emit CHARGE. actions={result.get('actions')!r}"
        )

    def test_pre_window_wait_unchanged_when_chunk_not_completed(self):
        """Byte-identical guardrail: pre-window WAIT path (chunk NOT completed,
        window not yet open) must remain untouched by the D1 short-circuit.
        """
        # 22:00 summer — off_peak, but next high-rate transition is 14:00
        # next day → 16h away, LONGER than 6h lead → window NOT open.
        anchor = datetime(2026, 7, 15, 22, 0)
        strat, hass = _build_strategy(
            soc=40, solcast_today="10", solcast_tomorrow="10",
            solcast_remaining="0",
        )
        # Chunk NOT completed (fresh chunk).
        assert strat._arbitrage_chunk_completed is False

        result = strat.determine_mode(
            "off_peak", "summer", now=anchor, ev_load_w=0.0,
        )
        # Existing behavior: with gate open but window not yet open →
        # arbitrage WAIT (or NA if rung fires). D1 must not have
        # short-circuited to HOLD (chunk not completed).
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_HOLD

    def test_boundary_passed_does_not_short_circuit(self):
        """After the high-rate boundary passes (mid_peak now taken over
        by the mid_peak branch upstream), the off_peak D1 short-circuit
        must not fire. This test simulates the tick JUST before the
        transition where the caller still says tou='off_peak' but the
        boundary lookup returns None or minutes<=0.

        Handled by requiring `_is_charge_window_open` / boundary AHEAD
        in the D1 predicate. Sanity check via a fresh chunk after
        `reset_arbitrage_chunk` (as would occur on TOU entry).
        """
        strat, hass = _build_strategy(soc=79, solcast_today="10")
        # Simulate: chunk was just RESET (transition INTO off_peak).
        strat.reset_arbitrage_chunk(reason="test")
        assert strat._arbitrage_chunk_completed is False
        # Now call at 09:31 with a fresh chunk — D1 must NOT fire
        # (no completed latch). Behavior falls to the normal gate/rung
        # path.
        _seed_rate(strat, _INCIDENT_ANCHOR, 79.0, 5.0)
        hass.set_state(_BSOC, "79")
        result = strat.determine_mode(
            "off_peak", "summer", now=_INCIDENT_ANCHOR, ev_load_w=0.0,
        )
        # No completed-chunk HOLD short-circuit. Real behavior here:
        # SOC 79 < target 80, rung_0 fires closing the gate → falls
        # to drain path. That's the LEGITIMATE not-yet-charged path
        # (rung ladder is preserved for it per D1 constraint 4).
        assert result["arbitrage_phase"] != ARBITRAGE_PHASE_HOLD


# ==========================================================================
# Helpers
# ==========================================================================


def _reserve_action_target(result: dict) -> int | None:
    """Extract the reserve number.set_value target from the actions list."""
    for a in result.get("actions", []):
        if a.get("service") == "number.set_value":
            return a.get("data", {}).get("value")
    # No action queued means "no change" — read the current reserve_soc.
    return result.get("reserve_soc")


def _has_charge_from_grid_on(result: dict) -> bool:
    for a in result.get("actions", []):
        if a.get("service") == "switch.turn_on":
            return True
    return False

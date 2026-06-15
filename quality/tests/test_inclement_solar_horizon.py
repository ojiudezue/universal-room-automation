"""D2 — SolarHorizon tests (FIN-2 surplus-based recoverability + FIN-3 rung gate).

Key invariants:
- FIN-3: off_peak callers short-circuit to recoverable=None and MUST NOT call
  battery._expected_solar_surplus_pct (mock asserts not-called).
- FIN-2: recoverable iff surplus_pct >= permitted_discharge_pct + margin, and
  the surplus comes from _expected_solar_surplus_pct (which nets house load),
  NOT raw solcast_remaining.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import sys
import os
import types
import importlib

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_NOW = datetime(2026, 6, 11, 14, 0, 0)

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": lambda fn: fn},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: _NOW, "now": lambda: _NOW,
        "as_local": lambda dt: dt, "UTC": None,
    },
}
for name, attrs in _mods.items():
    sys.modules.setdefault(name, _mock_module(name, **attrs))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
sys.modules["custom_components.universal_room_automation"] = _ura
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc
for _submod_name in ("energy_const", "inclement"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from custom_components.universal_room_automation.domain_coordinators.inclement import (
    compute_solar_horizon,
)


class FakeBattery:
    """Minimal battery exposing the surplus / tomorrow / daylight reads."""

    def __init__(self, surplus_pct=0.0, tomorrow="good",
                 sunrise_h=6, sunset_h=20):
        self._surplus_pct = surplus_pct
        self._tomorrow = tomorrow
        self._sunrise_h = sunrise_h
        self._sunset_h = sunset_h
        # mock so tests can assert call / not-called
        self._expected_solar_surplus_pct = MagicMock(return_value=surplus_pct)

    def classify_tomorrow_solar(self):
        return self._tomorrow

    def _daylight_bounds(self, anchor):
        sunrise = anchor.replace(hour=self._sunrise_h, minute=0, second=0, microsecond=0)
        sunset = anchor.replace(hour=self._sunset_h, minute=0, second=0, microsecond=0)
        return sunrise, sunset


def _expires(hours_from_now):
    return _NOW + timedelta(hours=hours_from_now)


# ---------------------------------------------------------------------------
# FIN-3 — off_peak short-circuit
# ---------------------------------------------------------------------------


def test_off_peak_caller_returns_recoverable_None_short_circuits_surplus_call():
    bat = FakeBattery(surplus_pct=99.0)
    h = compute_solar_horizon(
        bat, "off_peak", _NOW, current_soc=80, alert_expires_at=_expires(3),
    )
    assert h.recoverable is None
    assert h.reason == "off_peak_skip"
    bat._expected_solar_surplus_pct.assert_not_called()


# ---------------------------------------------------------------------------
# FIN-2 — surplus-based recoverability for mid_peak / peak
# ---------------------------------------------------------------------------


def test_mid_peak_recoverable_true_when_surplus_exceeds_permitted_plus_margin():
    # soc=80, floor=50 → permitted=30; margin=5 → need surplus>=35. Give 40.
    bat = FakeBattery(surplus_pct=40.0)
    h = compute_solar_horizon(
        bat, "mid_peak", _NOW, current_soc=80, alert_expires_at=_expires(4),
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is True
    assert h.permitted_discharge_pct == 30.0
    bat._expected_solar_surplus_pct.assert_called_once()


def test_mid_peak_recoverable_false_when_surplus_only_matches_permitted_no_margin():
    # permitted=30, surplus exactly 30 → 30 >= 30+5 is False (margin load-bearing).
    bat = FakeBattery(surplus_pct=30.0, tomorrow="poor")
    h = compute_solar_horizon(
        bat, "mid_peak", _NOW, current_soc=80, alert_expires_at=_expires(4),
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is False


def test_peak_recoverable_false_when_surplus_zero_post_sunset():
    bat = FakeBattery(surplus_pct=0.0, tomorrow="poor")
    h = compute_solar_horizon(
        bat, "peak", _NOW, current_soc=80, alert_expires_at=_expires(2),
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is False


def test_overnight_fallback_recoverable_when_tomorrow_good_and_expires_before_sunrise_window():
    # surplus short today, but tomorrow good AND alert expires overnight before
    # tomorrow's sunrise + 2h → overnight fallback recovers.
    bat = FakeBattery(surplus_pct=0.0, tomorrow="good")
    # Alert expires at 03:00 tomorrow; tomorrow sunrise=06:00 → +2h=08:00.
    expires = (_NOW + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    h = compute_solar_horizon(
        bat, "peak", _NOW, current_soc=80, alert_expires_at=expires,
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is True
    assert h.reason == "overnight_fallback_tomorrow_good"


def test_overnight_fallback_not_taken_when_tomorrow_poor():
    bat = FakeBattery(surplus_pct=0.0, tomorrow="poor")
    expires = (_NOW + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    h = compute_solar_horizon(
        bat, "peak", _NOW, current_soc=80, alert_expires_at=expires,
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is False


@pytest.mark.parametrize("tomorrow", ["moderate", "poor", "unknown", "fair"])
def test_overnight_fallback_NOT_taken_for_non_good_excellent_classes(tomorrow):
    # A-HIGH-1 — only {good, excellent} enable the overnight fallback. The real
    # classify_tomorrow_solar() domain is {excellent, good, moderate, poor,
    # unknown}; "fair" does not exist and "moderate" must NOT over-permit.
    bat = FakeBattery(surplus_pct=0.0, tomorrow=tomorrow)
    expires = (_NOW + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    h = compute_solar_horizon(
        bat, "peak", _NOW, current_soc=80, alert_expires_at=expires,
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is False


@pytest.mark.parametrize("tomorrow", ["good", "excellent"])
def test_overnight_fallback_taken_for_good_and_excellent(tomorrow):
    # A-HIGH-1 — both good and excellent enable the overnight fallback.
    bat = FakeBattery(surplus_pct=0.0, tomorrow=tomorrow)
    expires = (_NOW + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    h = compute_solar_horizon(
        bat, "peak", _NOW, current_soc=80, alert_expires_at=expires,
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is True
    assert h.reason == "overnight_fallback_tomorrow_good"


def test_post_sunset_peak_watch_today_not_recoverable():
    # A-MED-3 — when `now` is already past today's sunset (no sun left today),
    # the today-path must NOT inflate the risk window to tomorrow's ~24h-out
    # sunset. today_recoverable is forced False; only the overnight fallback can
    # rescue. With tomorrow=poor it stays not-recoverable, and the surplus helper
    # is never called for the (now-impossible) today projection.
    now_post_sunset = _NOW.replace(hour=21, minute=0)  # sunset_h=20 → past dusk
    bat = FakeBattery(surplus_pct=99.0, tomorrow="poor", sunset_h=20)
    h = compute_solar_horizon(
        bat, "peak", now_post_sunset, current_soc=80,
        alert_expires_at=now_post_sunset + timedelta(hours=2),
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    assert h.recoverable is False
    assert h.reason == "post_sunset_no_recovery_today"
    bat._expected_solar_surplus_pct.assert_not_called()


def test_uses_expected_solar_surplus_pct_helper_not_raw_solcast_remaining():
    # Reviewer A's correctness guard — the surplus must come from the helper.
    bat = FakeBattery(surplus_pct=40.0)
    # If the code read raw solcast_remaining it would not call this mock.
    compute_solar_horizon(
        bat, "mid_peak", _NOW, current_soc=80, alert_expires_at=_expires(4),
        partial_hold_reserve_floor=50, surplus_margin_pct=5,
    )
    bat._expected_solar_surplus_pct.assert_called_once()
    # And the window is min(expires, sunset)-now in minutes (positive int).
    args = bat._expected_solar_surplus_pct.call_args[0]
    assert args[0] == _NOW
    assert isinstance(args[1], int) and args[1] > 0

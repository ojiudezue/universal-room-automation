"""Behavioral tests for the HVAC post-peak coast release.

The mirror of the v4.7.29 battery day-boundary fix, applied to the HVAC
energy-constraint logic in ``EnergyCoordinator._update_hvac_constraint``:

  - Summer mid_peak is bracketed (pre-peak / peak / post-peak). Coasting is
    correct PRE-peak but wasteful POST-peak (off_peak imminent), so the coast
    must RELEASE to normal in summer post-peak mid_peak.
  - Shoulder/winter mid_peak IS the top rate (no peak ahead ever), so they
    must keep coasting — the season gate protects that.
  - The peak-period coast and all other branches are unaffected.

The real method body is extracted from energy.py source and exec'd as a
module-level function (the established pattern from
``test_v4_6_9_energy_recent_decisions.py``) so the test drives the real
production code, not a hand-copied reimplementation (Bug Class #44 fixture
authority). The TOU engine is mocked so season / peak-ahead are controlled
inputs — those primitives are exhaustively covered in test_day_boundary_tou.py.
"""

from __future__ import annotations

import os
import sys
import types
import logging
from unittest.mock import MagicMock

import pytest

_ENERGY_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
    "domain_coordinators", "energy.py",
)

_DC_PKG = "custom_components.universal_room_automation.domain_coordinators"


def _extract_update_hvac_constraint() -> types.FunctionType:
    """Extract and compile the real _update_hvac_constraint method body.

    Only reads source + compiles — no sys.modules mutation. The function-local
    imports the method performs (.signals, homeassistant.helpers.dispatcher)
    are stubbed per-test via the autouse `_stub_local_imports` fixture, which
    restores sys.modules on teardown so this suite's known order-dependent
    isolation is not worsened (Review C4).
    """
    with open(_ENERGY_PY, "r") as fh:
        src = fh.read()
    start = src.index("    def _update_hvac_constraint(")
    end = src.index("\n    def _update_energy_situation(", start)
    method_src = src[start:end]
    dedented = "\n".join(
        line[4:] if len(line) >= 4 else line
        for line in method_src.splitlines()
    ) + "\n"

    exec_globals: dict = {
        "_LOGGER": logging.getLogger("test.hvac_coast"),
        "Any": object,
        "__package__": _DC_PKG,
        "__name__": f"{_DC_PKG}.energy",
    }
    exec(compile(dedented, "<_update_hvac_constraint>", "exec"), exec_globals)
    return exec_globals["_update_hvac_constraint"]


_UPDATE_HVAC_CONSTRAINT = _extract_update_hvac_constraint()


@pytest.fixture(autouse=True)
def _stub_local_imports(monkeypatch):
    """Install stubs for the method's function-local imports, with teardown
    restore via monkeypatch (Review C4 — no leaked sys.modules entries)."""
    sig_mod = types.ModuleType(f"{_DC_PKG}.signals")
    sig_mod.EnergyConstraint = lambda **kw: ("constraint", kw)
    sig_mod.SIGNAL_ENERGY_CONSTRAINT = "signal_energy_constraint"
    monkeypatch.setitem(sys.modules, f"{_DC_PKG}.signals", sig_mod)

    disp_mod = types.ModuleType("homeassistant.helpers.dispatcher")
    disp_mod.async_dispatcher_send = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.dispatcher", disp_mod)
    yield


def _make_coord(season: str, peak_ahead: bool, solar_class: str = "poor") -> MagicMock:
    """Build a minimal coordinator stub with real-valued attributes."""
    coord = MagicMock()
    coord.hass = MagicMock()

    coord._battery = MagicMock()
    coord._battery.battery_soc = 80
    coord._battery.classify_solar_day.return_value = solar_class

    coord._tou = MagicMock()
    coord._tou.get_season.return_value = season
    coord._tou.peak_ahead_before_offpeak.return_value = peak_ahead
    coord._tou.get_next_transition.return_value = {"hours_until": 1.0}

    coord._cached_forecast_high = None
    coord._cached_forecast_low = None
    coord._cached_apparent_forecast_high = None

    coord._load_shedding_enabled = False
    coord._load_shedding_active_level = 0

    coord._constraint_shed_offset = 4.0
    coord._constraint_coast_offset = 2.0
    coord._constraint_precool_offset = -2.0
    coord._constraint_preheat_offset = 2.0
    coord._preheat_temp_threshold = 40.0

    coord._hvac_constraint_mode = "normal"
    coord._hvac_constraint_offset = 0.0
    coord._hvac_constraint_reason = ""
    coord._last_published_constraint = None  # force the publish path to run

    coord._record_decision = MagicMock()
    return coord


def _run(coord, tou_period: str) -> None:
    _UPDATE_HVAC_CONSTRAINT(coord, tou_period)


class TestSummerPostPeakCoastRelease:
    def test_summer_post_peak_midpeak_releases_to_normal(self):
        # 20:00-21:00 summer, off_peak imminent (no peak ahead) → release.
        coord = _make_coord(season="summer", peak_ahead=False, solar_class="poor")
        _run(coord, "mid_peak")
        assert coord._hvac_constraint_mode == "normal"
        assert coord._hvac_constraint_reason == "normal conditions"

    def test_summer_post_peak_very_poor_also_releases(self):
        coord = _make_coord(season="summer", peak_ahead=False, solar_class="very_poor")
        _run(coord, "mid_peak")
        assert coord._hvac_constraint_mode == "normal"


class TestCoastPreservedWhereCorrect:
    def test_summer_pre_peak_midpeak_still_coasts(self):
        # Peak still ahead → coasting is correct (save before peak).
        coord = _make_coord(season="summer", peak_ahead=True, solar_class="poor")
        _run(coord, "mid_peak")
        assert coord._hvac_constraint_mode == "coast"
        assert coord._hvac_constraint_reason == "mid-peak poor solar"

    def test_shoulder_midpeak_still_coasts(self):
        # Shoulder mid_peak is the top rate (no peak ahead ever) → must coast.
        coord = _make_coord(season="shoulder", peak_ahead=False, solar_class="poor")
        _run(coord, "mid_peak")
        assert coord._hvac_constraint_mode == "coast"
        assert coord._hvac_constraint_reason == "mid-peak poor solar"

    def test_winter_midpeak_still_coasts(self):
        coord = _make_coord(season="winter", peak_ahead=False, solar_class="poor")
        _run(coord, "mid_peak")
        assert coord._hvac_constraint_mode == "coast"

    def test_summer_peak_period_still_coasts(self):
        # The peak branch is independent of the post-peak gate.
        coord = _make_coord(season="summer", peak_ahead=False, solar_class="poor")
        _run(coord, "peak")
        assert coord._hvac_constraint_mode == "coast"
        assert coord._hvac_constraint_reason == "peak TOU period"


class TestNonCoastBranchesUnaffected:
    def test_summer_post_peak_good_solar_is_normal_not_coast(self):
        # Good solar never hit the mid_peak coast branch regardless of the gate.
        coord = _make_coord(season="summer", peak_ahead=False, solar_class="good")
        _run(coord, "mid_peak")
        assert coord._hvac_constraint_mode == "normal"

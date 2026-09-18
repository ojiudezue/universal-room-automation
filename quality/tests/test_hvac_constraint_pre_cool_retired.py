"""Behavioral + source-anchored test that the EC `pre_cool` mode is
retired: `_update_hvac_constraint` never emits `mode="pre_cool"` for
the off_peak + low-SOC + good-solar window (the sole prior emitter).
Instead the mode falls through to `normal` — leaving Path A eligible
via the `mode == "normal"` gate in hvac_predict.

Mutation anchor: re-adding the deleted `elif` branch in energy.py
would land `mode == "pre_cool"` here → RED.
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
        "_LOGGER": logging.getLogger("test.pre_cool_retired"),
        "Any": object,
        "__package__": _DC_PKG,
        "__name__": f"{_DC_PKG}.energy",
    }
    exec(compile(dedented, "<_update_hvac_constraint>", "exec"), exec_globals)
    return exec_globals["_update_hvac_constraint"]


_UPDATE_HVAC_CONSTRAINT = _extract_update_hvac_constraint()


@pytest.fixture(autouse=True)
def _stub_local_imports(monkeypatch):
    sig_mod = types.ModuleType(f"{_DC_PKG}.signals")
    sig_mod.EnergyConstraint = lambda **kw: ("constraint", kw)
    sig_mod.SIGNAL_ENERGY_CONSTRAINT = "signal_energy_constraint"
    monkeypatch.setitem(sys.modules, f"{_DC_PKG}.signals", sig_mod)

    disp_mod = types.ModuleType("homeassistant.helpers.dispatcher")
    disp_mod.async_dispatcher_send = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.dispatcher", disp_mod)
    yield


def _make_coord(soc: int, solar_class: str) -> MagicMock:
    coord = MagicMock()
    coord.hass = MagicMock()

    coord._battery = MagicMock()
    coord._battery.battery_soc = soc
    coord._battery.classify_solar_day.return_value = solar_class

    coord._tou = MagicMock()
    coord._tou.get_season.return_value = "summer"
    coord._tou.peak_ahead_before_offpeak.return_value = False
    coord._tou.get_next_transition.return_value = {"hours_until": 6.0}

    # High enough forecast_low that the pre_heat branch does NOT fire
    # (branch requires forecast_low < preheat_temp_threshold AND soc>50).
    coord._cached_forecast_high = None
    coord._cached_forecast_low = 70.0
    coord._cached_apparent_forecast_high = None

    coord._load_shedding_enabled = False
    coord._load_shedding_active_level = 0

    coord._constraint_shed_offset = 4.0
    coord._constraint_coast_offset = 2.0
    coord._constraint_precool_offset = -2.0  # tombstoned but still initialized
    coord._constraint_preheat_offset = 2.0
    coord._preheat_temp_threshold = 40.0

    coord._hvac_constraint_mode = "normal"
    coord._hvac_constraint_offset = 0.0
    coord._hvac_constraint_reason = ""
    coord._last_published_constraint = None

    coord._record_decision = MagicMock()
    return coord


class TestPreCoolRetired:
    def test_off_peak_low_soc_good_solar_is_normal_not_pre_cool(self):
        # This is the exact input shape the retired branch consumed.
        coord = _make_coord(soc=45, solar_class="good")
        _UPDATE_HVAC_CONSTRAINT(coord, "off_peak")
        assert coord._hvac_constraint_mode == "normal"
        assert coord._hvac_constraint_mode != "pre_cool"

    def test_off_peak_low_soc_excellent_solar_is_normal_not_pre_cool(self):
        coord = _make_coord(soc=30, solar_class="excellent")
        _UPDATE_HVAC_CONSTRAINT(coord, "off_peak")
        assert coord._hvac_constraint_mode == "normal"
        assert coord._hvac_constraint_mode != "pre_cool"

    def test_source_no_longer_emits_pre_cool_mode(self):
        with open(_ENERGY_PY, "r") as fh:
            src = fh.read()
        # No line in _update_hvac_constraint assigns mode="pre_cool".
        assert 'self._hvac_constraint_mode = "pre_cool"' not in src

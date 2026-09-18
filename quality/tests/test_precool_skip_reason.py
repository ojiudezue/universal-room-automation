"""Tier-1 additive observability: pre_cool_skip_reason string exposes
WHY Path A pre-cool did NOT fire. Card: HVAC-PRECOOL-SKIP-REASON-OBS-1.

Reuses HA-mock env priming from test_v5_7_1_energy_precool. Uses its own
loader that fully stubs hvac_setpoint (sibling's stub is incomplete).
"""

import importlib.util
import os
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

# Import sibling to install HA mock modules (side-effect).
import test_v5_7_1_energy_precool as _sib  # noqa: F401


_DC_NAME = (
    "custom_components.universal_room_automation.domain_coordinators"
)
_DC_PATH = _sib._dc_path


def _install_stubs():
    def _mock(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    async def _emit_stub(*a, **k):
        return None

    def _guard_stub(*a, **k):
        return None

    sys.modules[f"{_DC_NAME}.hvac_override"] = _mock(
        f"{_DC_NAME}.hvac_override",
        OverrideArrester=type("OverrideArrester", (), {}),
    )
    sys.modules[f"{_DC_NAME}.hvac_preset"] = _mock(
        f"{_DC_NAME}.hvac_preset",
        PresetManager=type("PresetManager", (), {}),
    )
    sys.modules[f"{_DC_NAME}.hvac_zones"] = _mock(
        f"{_DC_NAME}.hvac_zones",
        ZoneManager=type("ZoneManager", (), {}),
    )
    sys.modules[f"{_DC_NAME}.hvac_setpoint"] = _mock(
        f"{_DC_NAME}.hvac_setpoint",
        apply_setpoint_guards=_guard_stub,
        emit_set_temperature=_emit_stub,
        emit_set_preset_mode=_emit_stub,
    )
    sys.modules[f"{_DC_NAME}.signals"] = _mock(
        f"{_DC_NAME}.signals",
        EnergyConstraint=type("EnergyConstraint", (), {}),
    )


def _load_predictor_cls():
    _install_stubs()
    full = f"{_DC_NAME}.hvac_predict"
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_DC_PATH, "hvac_predict.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod.HVACPredictor


HVACPredictor = _load_predictor_cls()


def _make_pred():
    hass = MagicMock()
    hass.data = {}
    zm = MagicMock()
    zm.zones = {}
    pm = MagicMock()
    pm.current_season = "summer"
    return HVACPredictor(
        hass=hass, zone_manager=zm, preset_manager=pm,
        override_arrester=MagicMock(), net_power_entity=None,
    )


def _make_constraint(soc=98, forecast_high=92, mode="normal"):
    c = MagicMock()
    c.soc = soc
    c.forecast_high_temp = forecast_high
    c.mode = mode
    return c


_UNSET = object()


def _eval(pred, *, net_power=-800.0, constraint=_UNSET, hour=13,
          season="summer", triggered_today=False, active=False):
    pred._get_net_power = MagicMock(return_value=net_power)
    pred._preset_manager.current_season = season
    pred._pre_cool_triggered_today = triggered_today
    pred._pre_cool_active = active
    if constraint is _UNSET:
        constraint = _make_constraint()
    now = datetime(2026, 6, 11, hour, 0, 0)
    result = pred._should_energy_precool(constraint, now)
    return result, pred.pre_cool_skip_reason


def test_no_constraint():
    p = _make_pred()
    r, why = _eval(p, constraint=None)
    assert r is False and why == "no_constraint"


def test_off_season():
    p = _make_pred()
    r, why = _eval(p, season="winter")
    assert r is False and why == "off_season"


def test_outside_window():
    p = _make_pred()
    r, why = _eval(p, hour=8)
    assert r is False and why == "outside_window"


def test_no_pv_surplus():
    p = _make_pred()
    r, why = _eval(p, net_power=-100.0)
    assert r is False and why == "no_pv_surplus"


def test_mode_non_normal():
    p = _make_pred()
    r, why = _eval(p, constraint=_make_constraint(mode="coast"))
    assert r is False and why == "mode_coast"


def test_already_today():
    p = _make_pred()
    r, why = _eval(p, triggered_today=True)
    assert r is False and why == "already_today"


def test_soc_unknown_cool_day():
    p = _make_pred()
    r, why = _eval(
        p, constraint=_make_constraint(soc=None, forecast_high=70),
    )
    assert r is False and why == "soc_unknown_cool_day"


def test_soc_below_floor():
    p = _make_pred()
    r, why = _eval(
        p, constraint=_make_constraint(soc=50, forecast_high=70),
    )
    assert r is False and why == "soc_below_floor"


def test_firing_empty_reason():
    p = _make_pred()
    r, why = _eval(
        p, constraint=_make_constraint(soc=60, forecast_high=95),
    )
    assert r is True and why == ""


def test_active_reengagement_empty_reason():
    p = _make_pred()
    r, why = _eval(p, active=True)
    assert r is True and why == ""

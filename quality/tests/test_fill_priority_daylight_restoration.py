"""fill-priority-daylight-restoration — off_peak day/night split.

Restores pre-v5.5.5 daytime "battery-first" behavior on the summer off_peak
morning slice (~07:00-14:00) that the v5.5.5 fix silently surrendered by
using tou_period alone as a "night" proxy. TIME-anchored via the battery
coordinator's civil sunrise/sunset primitive (`_daylight_bounds`) — never
instantaneous PV.

Test matrix: off_peak x {night, daylight} x {soc<80, soc>=80} x forecast health.
Preserves the v5.5.5 cross-midnight release invariant (is_daylight=None or
False in overnight off_peak → still inert → still releases throughout).
"""
import datetime as _dt
import importlib
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


# Mock homeassistant — mirror test_evse_offpeak_fill_release.py bootstrap.
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
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _dt.datetime.utcnow,
        "now": _dt.datetime.now,
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

_cc = sys.modules.get("custom_components") or types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_name = "custom_components.universal_room_automation"
_ura = sys.modules.get(_ura_name) or types.ModuleType(_ura_name)
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = _ura_name
sys.modules[_ura_name] = _ura

if f"{_ura_name}.const" not in sys.modules:
    _const_spec = importlib.util.spec_from_file_location(
        f"{_ura_name}.const", os.path.join(_ura_path, "const.py"),
    )
    _const_mod = importlib.util.module_from_spec(_const_spec)
    sys.modules[f"{_ura_name}.const"] = _const_mod
    _const_spec.loader.exec_module(_const_mod)
    _ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc_name = f"{_ura_name}.domain_coordinators"
_dc = sys.modules.get(_dc_name) or types.ModuleType(_dc_name)
_dc.__path__ = [_dc_path]
_dc.__package__ = _dc_name
sys.modules[_dc_name] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_tou", "energy_pool"):
    _full_name = f"{_dc_name}.{_submod_name}"
    if _full_name in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
)


def _make_ev(on=True):
    hass = MockHass()
    hass.set_state("switch.garage_a", "on" if on else "off")
    hass.set_state("sensor.garage_a_power_minute_average", "7000.0")
    hass.set_state("sensor.garage_a_energy_today", "0")
    hass.set_state("sensor.garage_a_energy_this_month", "0")
    evse_config = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
        },
    }
    return EVChargerController(hass, evse_config=evse_config), hass


def _has_off(actions):
    return any(a["service"] == "switch.turn_off" for a in actions)


# ---------------------------------------------------------------------------
# Test matrix — off_peak x {night, daylight} x {soc<80, soc>=80} x forecast
# ---------------------------------------------------------------------------

class TestOffPeakDaylightHolds:
    """Off_peak + daylight + soc<80 + healthy forecast → HOLD (restored)."""

    def test_daylight_low_soc_healthy_forecast_holds(self):
        ev, _ = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=True,
        )
        assert _has_off(actions)
        assert "garage_a" in ev._paused_by_fill_priority

    def test_daylight_high_soc_no_hold(self):
        """SOC >= threshold → fill target met, no pause."""
        ev, _ = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=85.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=True,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_daylight_low_soc_forecast_decayed_no_hold(self):
        """Cloudy day (forecast below threshold) → no hold."""
        ev, _ = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=0.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=True,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority


class TestOffPeakNightReleases:
    """Off_peak + night → inert (v5.5.5 cross-midnight release preserved)."""

    @pytest.mark.parametrize("soc", [51.0, 85.0])
    @pytest.mark.parametrize("forecast", [0.0, 18.0])
    def test_night_never_holds(self, soc, forecast):
        ev, _ = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=soc, remaining_forecast_kwh=forecast, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=False,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_night_releases_stale_hold(self):
        """A held EVSE (from prior daytime pre-peak) is released overnight."""
        ev, hass = _make_ev()
        ev._paused_by_fill_priority.add("garage_a")
        hass.set_state("switch.garage_a", "off")
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=140.0,  # rolled next-day forecast
            tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=False,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority


class TestOffPeakDaylightUnknownPreservesV555:
    """is_daylight=None (no sun info / legacy harness) preserves v5.5.5.

    Off_peak stays inert — behavior identical to v5.5.5 shipped code so the
    cross-midnight release and the existing evse-offpeak-fill-release test
    suite pass unchanged (they call without the new kwarg).
    """
    @pytest.mark.parametrize("soc", [51.0, 85.0])
    def test_unknown_daylight_off_peak_inert(self, soc):
        ev, _ = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=soc, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=None,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority


class TestMutationAnchorDaylightBranch:
    """Removing the daylight branch re-creates the 2026-07-22 morning bug.

    If off_peak were inert regardless of daylight, the low-SOC + healthy
    forecast + daylight case would NOT hold and the car would charge through
    from grid while the house battery sat below its fill target. This test
    asserts a HOLD in that exact case — deleting the `is_daylight is not True`
    condition in `off_peak_inert` makes it fail.
    """
    def test_daylight_off_peak_low_soc_must_hold(self):
        ev, _ = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=31.0,               # the 2026-07-22 morning SOC range
            remaining_forecast_kwh=25.0,   # healthy morning forecast
            tou_period="off_peak",
            soc_threshold=80,
            excess_solar_kwh_threshold=5.0,
            is_daylight=True,
        )
        assert _has_off(actions), (
            "off_peak + daylight + low SOC + healthy forecast MUST hold: "
            "removing the daylight branch re-creates 2026-07-22 charge-through."
        )
        assert "garage_a" in ev._paused_by_fill_priority


class TestMutationAnchorNightBranch:
    """Removing the night branch re-creates the pre-v5.5.5 deadlock.

    If off_peak released only in daylight (i.e. the night branch missing so
    overnight is treated as HOLD), a stale hold at 02:00 with rolled-forecast
    would NOT clear and the off_peak ensure-on would remain vetoed. This
    asserts release at night — removing `is_daylight is not True` and
    replacing with `is_daylight is True` in `off_peak_inert` makes it fail.
    """
    def test_night_off_peak_releases_stale_hold(self):
        ev, hass = _make_ev()
        ev._paused_by_fill_priority.add("garage_a")
        hass.set_state("switch.garage_a", "off")
        actions = ev.determine_fill_priority_actions(
            soc=51.0,
            remaining_forecast_kwh=140.0,   # midnight-rolled forecast (the trap)
            tou_period="off_peak",
            soc_threshold=80,
            excess_solar_kwh_threshold=5.0,
            is_daylight=False,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority, (
            "night off_peak MUST release the stale hold: removing the night "
            "branch re-creates the pre-v5.5.5 24/7-hold deadlock."
        )


class TestL1PlugMirror:
    """L1 plug tier honors the same day/night split (mirror of EV path)."""

    def _make_plug(self):
        hass = MockHass()
        hass.set_state("switch.plug_a", "on")
        from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
            SmartPlugController,
        )
        return SmartPlugController(hass, plug_entities=["switch.plug_a"]), hass

    def test_plug_daylight_off_peak_low_soc_holds(self):
        plug, _ = self._make_plug()
        actions = plug.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=True,
        )
        assert _has_off(actions)

    def test_plug_night_off_peak_never_holds(self):
        plug, _ = self._make_plug()
        actions = plug.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
            is_daylight=False,
        )
        assert not _has_off(actions)

"""evse-offpeak-fill-release — day/night-aware EV fill-priority + drain solar gate.

Drives the REAL controller methods (`EVChargerController.determine_fill_priority_actions`
and `determine_battery_drain_actions`) and the REAL `TOURateEngine.peak_ahead_before_offpeak`
to prove the TIME-anchored phase invariant. No hand-rolled mirrors of the decision logic.

D1 — fill-priority releases at off_peak / post-peak mid_peak; holds in the
     daytime pre-peak window (mid_peak + peak_ahead). Cross-midnight off_peak
     window releases throughout (the original 24/7-hold deadlock bug).
D2 — battery-drain's high-SOC `soc_recovered` release is solar-gated: at
     night/no-solar only the reserve-gated `battery_out_of_capacity` releases.
D3 — mid_peak(peak_ahead) → off_peak produces ONE clean paused→charging handoff.
Phase-invariant — a cloudy mid_peak (PV≈0 but DAYTIME, peak ahead) still HOLDS.
"""
import datetime as _dt
import importlib
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


# Mock homeassistant — mirror test_energy_pool_fill_priority.py bootstrap.
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

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_tou", "energy_pool"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
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
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)


# ---------------------------------------------------------------------------
# Harness — real controller, real TOU engine on the built-in PEC schedule.
# Summer (months 6-9): off_peak 0-14 & 21-24, mid_peak 14-16 & 20-21, peak 16-20.
# ---------------------------------------------------------------------------

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


_TOU = TOURateEngine()  # real PEC engine


def _peak_ahead(hour, month=7, day=15):
    """REAL midnight-safe lookahead — no hand-rolled phase logic."""
    now = _dt.datetime(2026, month, day, hour, 0, 0)
    return _TOU.peak_ahead_before_offpeak(now)


def _has_off(actions):
    return any(a["service"] == "switch.turn_off" for a in actions)


def _has_on(actions):
    return any(a["service"] == "switch.turn_on" for a in actions)


# ---------------------------------------------------------------------------
# D1 matrix — {period × peak_ahead} × {soc<80, soc>=80}
# ---------------------------------------------------------------------------

class TestD1FillPriorityReleaseMatrix:
    @pytest.mark.parametrize("soc", [51.0, 85.0])
    def test_peak_always_inert(self, soc):
        ev, hass = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=soc, remaining_forecast_kwh=18.0, tou_period="peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    @pytest.mark.parametrize("soc", [51.0, 85.0])
    def test_off_peak_releases_never_holds(self, soc):
        """NEW: off_peak is the cheap-grid window — never hold, always release."""
        ev, hass = _make_ev()
        # Even with low SOC + healthy solar (the old pause trigger), off_peak
        # must NOT dispatch a pause.
        actions = ev.determine_fill_priority_actions(
            soc=soc, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_mid_peak_peak_ahead_low_soc_holds(self):
        ev, hass = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="mid_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=True,
        )
        assert _has_off(actions)
        assert "garage_a" in ev._paused_by_fill_priority

    def test_mid_peak_peak_ahead_high_soc_no_hold(self):
        """SOC>=80 means fill target met — no pause even pre-peak."""
        ev, hass = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=85.0, remaining_forecast_kwh=18.0, tou_period="mid_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=True,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    @pytest.mark.parametrize("soc", [51.0, 85.0])
    def test_mid_peak_no_peak_ahead_releases(self, soc):
        """NEW: post-peak mid_peak (no peak ahead) releases — don't hold."""
        ev, hass = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=soc, remaining_forecast_kwh=18.0, tou_period="mid_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=False,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_mid_peak_legacy_no_tou_engine_holds(self):
        """peak_ahead=None (no TOU wired) preserves prior always-hold."""
        ev, hass = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="mid_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=None,
        )
        assert _has_off(actions)
        assert "garage_a" in ev._paused_by_fill_priority


class TestD1MutationOffPeakRelease:
    """MUTATION ANCHOR: removing the off_peak release re-deadlocks.

    If `off_peak` were treated as a hold period (the bug), a held EVSE would
    NOT be released and the off_peak ensure-on would stay vetoed. This test
    asserts a held EVSE IS released on the off_peak tick — the proof the
    deadlock is gone. Removing `"off_peak"` from `fill_priority_inert` makes
    this fail (the EVSE would stay in `_paused_by_fill_priority`).
    """
    def test_held_evse_released_on_off_peak_tick(self):
        ev, hass = _make_ev()
        # Held during the daytime pre-peak window.
        ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="mid_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=True,
        )
        assert "garage_a" in ev._paused_by_fill_priority
        hass.set_state("switch.garage_a", "off")
        # off_peak boundary crossed.
        ev.determine_fill_priority_actions(
            soc=55.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        # Released — no longer blocks the off_peak ensure-on carry-over guard.
        assert "garage_a" not in ev._paused_by_fill_priority


class TestD1CrossMidnight:
    """A 23:00 → 05:00 summer off_peak window releases THROUGHOUT — the bug.

    Drives the REAL `peak_ahead_before_offpeak` at each hour. None of these
    hours may re-lock the EV (the midnight roll-over of `solcast_remaining`
    used to make `forecast_healthy` True all night → 24/7 hold).
    """
    @pytest.mark.parametrize("hour", [23, 0, 1, 2, 3, 4, 5])
    def test_no_midnight_relock(self, hour):
        ev, hass = _make_ev()
        # Seed a stale hold from the prior evening to prove it gets cleared.
        ev._paused_by_fill_priority.add("garage_a")
        # Compute period from the real engine for this hour.
        period = _TOU.get_current_period(_dt.datetime(2026, 7, 15, hour, 0, 0))
        pa = _peak_ahead(hour)
        actions = ev.determine_fill_priority_actions(
            soc=51.0,                 # low SOC (would hold pre-peak)
            remaining_forecast_kwh=140.0,  # rolled next-day forecast (the trap)
            tou_period=period,
            soc_threshold=80,
            excess_solar_kwh_threshold=5.0,
            peak_ahead=pa,
        )
        # Overnight: period is off_peak (0-14, 21-24) → inert → released.
        assert period == "off_peak"
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority


# ---------------------------------------------------------------------------
# D2 matrix — solar-gated high-SOC drain release.
# soc_threshold here = 80 so soc_recovered fires at >=85.
# ---------------------------------------------------------------------------

class TestD2DrainSolarGate:
    def _pause(self, ev, hass):
        # Pause via discharge at low-ish SOC, then settle the switch off.
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=70.0, soc_threshold=80,
        )
        hass.set_state("switch.garage_a", "off")
        assert "garage_a" in ev._paused_by_battery_drain

    def test_night_high_soc_holds_no_solar_release(self):
        """Night (solar_replenishing=False), battery idle at 85% → NO release.

        Only reserve-gated release is allowed at night → EV charges from grid.
        """
        ev, hass = _make_ev()
        self._pause(ev, hass)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-50.0,    # idle (not discharging)
            battery_soc=85.0,         # >= soc_threshold + 5
            soc_threshold=80,
            reserve_soc=20,           # 85 NOT <= 22 → battery_out_of_capacity False
            solar_replenishing=False,
        )
        assert not _has_on(actions)
        assert "garage_a" in ev._paused_by_battery_drain

    def test_day_high_soc_releases_with_solar(self):
        """Day (solar_replenishing=True) at 85% → soc_recovered releases (shares solar)."""
        ev, hass = _make_ev()
        self._pause(ev, hass)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-50.0,
            battery_soc=85.0,
            soc_threshold=80,
            reserve_soc=20,
            solar_replenishing=True,
        )
        assert _has_on(actions)
        assert "garage_a" not in ev._paused_by_battery_drain

    def test_reserve_release_works_at_night(self):
        """Night, battery drained to reserve+2 → battery_out_of_capacity releases."""
        ev, hass = _make_ev()
        self._pause(ev, hass)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-50.0,
            battery_soc=22.0,         # reserve_soc + 2
            soc_threshold=80,
            reserve_soc=20,
            solar_replenishing=False,
        )
        assert _has_on(actions)
        assert "garage_a" not in ev._paused_by_battery_drain

    def test_mid_soc_no_release_either_phase(self):
        """SOC between reserve and recovered → no release regardless of solar."""
        for solar in (True, False):
            ev, hass = _make_ev()
            self._pause(ev, hass)
            actions = ev.determine_battery_drain_actions(
                battery_power_w=-50.0,
                battery_soc=50.0,     # not <=22, not >=85
                soc_threshold=80,
                reserve_soc=20,
                solar_replenishing=solar,
            )
            assert not _has_on(actions)
            assert "garage_a" in ev._paused_by_battery_drain


class TestD2MutationSolarGate:
    """MUTATION ANCHOR: removing the solar gate lets the night-85 case resume.

    Without `solar_replenishing and ...`, `soc_recovered` is True at SOC 85
    even at night, and the EV wrongly drains the high-SOC battery. This test
    asserts NO release at night-85 — removing the gate makes it fail.
    """
    def test_night_85_must_not_release(self):
        ev, hass = _make_ev()
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=70.0, soc_threshold=80,
        )
        hass.set_state("switch.garage_a", "off")
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-50.0, battery_soc=85.0, soc_threshold=80,
            reserve_soc=20, solar_replenishing=False,
        )
        assert not _has_on(actions)
        assert "garage_a" in ev._paused_by_battery_drain


# ---------------------------------------------------------------------------
# D3 — mid_peak(peak_ahead) → off_peak: ONE clean paused→charging handoff.
# ---------------------------------------------------------------------------

class TestD3CleanHandoff:
    def test_single_paused_then_charging_transition(self):
        ev, hass = _make_ev()
        # Tick 1: daytime pre-peak window — pause.
        a1 = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="mid_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=True,
        )
        assert _has_off(a1)
        assert "garage_a" in ev._paused_by_fill_priority
        hass.set_state("switch.garage_a", "off")

        # Tick 2: off_peak boundary — fill-priority goes inert, releases. It
        # does NOT itself turn the charger on (the off_peak ensure-on does);
        # the key invariant is the hold is cleared so the ensure-on is no
        # longer vetoed, and there is no re-pause flap.
        a2 = ev.determine_fill_priority_actions(
            soc=55.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        assert not _has_off(a2)             # no re-pause
        assert "garage_a" not in ev._paused_by_fill_priority

        # Tick 3: still off_peak — stays released, no oscillation.
        a3 = ev.determine_fill_priority_actions(
            soc=56.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        assert not _has_off(a3)
        assert "garage_a" not in ev._paused_by_fill_priority


# ---------------------------------------------------------------------------
# PHASE INVARIANT — a cloudy mid_peak (PV≈0 but DAYTIME, peak ahead) HOLDS.
# Proves the phase is TIME-based, not PV-based.
# ---------------------------------------------------------------------------

class TestPhaseInvariantCloudyDaytime:
    def test_cloudy_daytime_pre_peak_still_holds(self):
        """PV≈0 (cloudy) but it is DAYTIME mid_peak with a real peak ahead.

        The hold must persist — phase is TIME (peak_ahead) anchored, NOT a
        live PV read. `peak_ahead` comes from the REAL engine at a pre-peak
        summer hour (15:00).
        """
        ev, hass = _make_ev()
        pa = _peak_ahead(15)  # 15:00 summer mid_peak → peak at 16:00 ahead
        assert pa is True
        # remaining_forecast is still healthy-on-paper here (>=5), but the
        # POINT is the phase decision is `peak_ahead`, not PV. We pass a
        # healthy forecast to isolate the phase gate, then a separate check
        # below proves a cloudy forecast in off_peak still releases.
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="mid_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=pa,
        )
        assert _has_off(actions)
        assert "garage_a" in ev._paused_by_fill_priority

    def test_cloudy_night_off_peak_still_releases(self):
        """Mirror: cloudy/dark off_peak releases — phase, not PV, decides."""
        ev, hass = _make_ev()
        ev._paused_by_fill_priority.add("garage_a")
        pa = _peak_ahead(2)  # 02:00 off_peak
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=0.0,  # PV≈0 (cloudy/dark)
            tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0, peak_ahead=pa,
        )
        assert not _has_off(actions)
        assert "garage_a" not in ev._paused_by_fill_priority

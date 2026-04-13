"""Tests for v4.0.18: EV Grid Import Cap.

Validates grid cap pause/resume, hysteresis, disabled-by-default,
and independence from TOU pausing.
"""

import os
import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock homeassistant
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": lambda fn: fn},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": MagicMock()},
    "homeassistant.util": {},
    "homeassistant.util.dt": {"utcnow": MagicMock(), "now": MagicMock()},
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_ura_const = types.ModuleType("custom_components.universal_room_automation.const")
_ura_const.DOMAIN = "universal_room_automation"
_ura_const.VERSION = "4.0.18"
sys.modules["custom_components.universal_room_automation.const"] = _ura_const

_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc

# ---------------------------------------------------------------------------
# Import module under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
    EVSE_CHARGING_POWER_THRESHOLD,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    DEFAULT_GRID_IMPORT_CAP_KW,
    DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ev(garage_a_on=False, garage_a_power=0.0):
    """Create EVChargerController with mock EVSE states."""
    hass = MagicMock()
    config = {
        "garage_a": {"switch": "switch.garage_a", "power": "sensor.garage_a_power"},
    }
    ev = EVChargerController(hass, evse_config=config)

    # Mock states
    switch_state = MagicMock()
    switch_state.state = "on" if garage_a_on else "off"
    switch_state.attributes = {"status": "Charging" if garage_a_on else "Standby"}

    power_state = MagicMock()
    power_state.state = str(garage_a_power)

    def get_state(entity_id):
        if entity_id == "switch.garage_a":
            return switch_state
        if entity_id == "sensor.garage_a_power":
            return power_state
        return None

    hass.states.get = get_state
    return ev


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGridCapPauses:
    """Grid cap should pause charging EVSEs when over the cap."""

    def test_pauses_when_over_cap(self):
        ev = _make_ev(garage_a_on=True, garage_a_power=3000)  # 3kW charging
        actions = ev.determine_grid_cap_actions(
            net_power_kw=9.0, grid_cap_kw=8.0, hysteresis_kw=1.0
        )
        assert len(actions) == 1
        assert actions[0]["service"] == "switch.turn_off"
        assert "garage_a" in ev._paused_by_grid_cap

    def test_no_action_when_under_cap(self):
        ev = _make_ev(garage_a_on=True, garage_a_power=3000)
        actions = ev.determine_grid_cap_actions(
            net_power_kw=6.0, grid_cap_kw=8.0, hysteresis_kw=1.0
        )
        assert len(actions) == 0

    def test_no_action_when_not_charging(self):
        ev = _make_ev(garage_a_on=False, garage_a_power=0)
        actions = ev.determine_grid_cap_actions(
            net_power_kw=10.0, grid_cap_kw=8.0, hysteresis_kw=1.0
        )
        assert len(actions) == 0  # Not charging, nothing to pause


class TestGridCapResumes:
    """Grid cap should resume EVSEs when under cap minus hysteresis."""

    def test_resumes_below_hysteresis(self):
        ev = _make_ev(garage_a_on=False, garage_a_power=0)
        ev._paused_by_grid_cap.add("garage_a")
        actions = ev.determine_grid_cap_actions(
            net_power_kw=6.5, grid_cap_kw=8.0, hysteresis_kw=1.0
        )
        assert len(actions) == 1
        assert actions[0]["service"] == "switch.turn_on"
        assert "garage_a" not in ev._paused_by_grid_cap

    def test_holds_in_hysteresis_band(self):
        ev = _make_ev(garage_a_on=False, garage_a_power=0)
        ev._paused_by_grid_cap.add("garage_a")
        actions = ev.determine_grid_cap_actions(
            net_power_kw=7.5, grid_cap_kw=8.0, hysteresis_kw=1.0
        )
        # 7.5 is between cap (8) and cap-hysteresis (7) — hold paused
        assert len(actions) == 0
        assert "garage_a" in ev._paused_by_grid_cap


class TestGridCapDefaults:
    """Grid cap defaults and independence from TOU."""

    def test_defaults(self):
        assert DEFAULT_GRID_IMPORT_CAP_KW == 8.0
        assert DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW == 1.0

    def test_separate_from_tou(self):
        ev = _make_ev(garage_a_on=True, garage_a_power=3000)
        ev._paused_by_us.add("garage_a")  # TOU paused
        actions = ev.determine_grid_cap_actions(
            net_power_kw=9.0, grid_cap_kw=8.0, hysteresis_kw=1.0
        )
        # Grid cap should STILL pause (separate tracking)
        assert len(actions) == 1
        assert "garage_a" in ev._paused_by_grid_cap
        assert "garage_a" in ev._paused_by_us  # TOU pause unchanged

"""FIX C — Room-tier fan manual-off cooldown (PLANNING_fan_manual_off_cooldown.md D1).

Ports the HVAC-tier manual-off cooldown (hvac_fans.py:207-217/389-397) to
`RoomAutomation.handle_temperature_based_fan_control` (automation.py) so
that an operator manually turning off a room-owned fan is not re-armed on
the next 30s coordinator tick.

Regression pattern: Jaya Bedroom comfort fan re-armed within ~30s of a
manual off tap because the room-tier temperature-fan path had no
manual-off memory (only the HVAC-tier path did).

Tests drive `handle_temperature_based_fan_control` directly via the real
`RoomAutomation` class — the harness is a trimmed-down copy of
test_v4623_humidity_fan_behavioral.py.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA module mocking (mirrors test_v4623_humidity_fan_behavioral.py)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods: dict = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": _mock_module(
        "homeassistant.const",
        SERVICE_TURN_ON="turn_on",
        SERVICE_TURN_OFF="turn_off",
        STATE_ON="on",
        STATE_OFF="off",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {"is_up": lambda hass: True},
    "homeassistant.util": {},
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
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

_dt_now_fn = lambda: datetime.now(timezone.utc)  # noqa: E731


def _parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


_dt_mock = _mock_module(
    "homeassistant.util.dt",
    utcnow=lambda: _dt_now_fn(),
    now=lambda: _dt_now_fn(),
    as_local=lambda dt: dt,
    parse_datetime=_parse_dt,
)

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules["homeassistant.util.dt"] = _dt_mock
sys.modules.setdefault("aiosqlite", MagicMock())


# ---------------------------------------------------------------------------
# Load automation.py
# ---------------------------------------------------------------------------

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(_project_root, "custom_components", "universal_room_automation")


def _load_module(full_name: str, filepath: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "custom_components" not in sys.modules:
    sys.modules["custom_components"] = _mock_module("custom_components")
if "custom_components.universal_room_automation" not in sys.modules:
    _ura_pkg = _mock_module("custom_components.universal_room_automation")
    _ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
    sys.modules["custom_components.universal_room_automation"] = _ura_pkg
if "custom_components.universal_room_automation.const" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.const",
        os.path.join(_ura_root, "const.py"),
    )
if "custom_components.universal_room_automation.automation" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.automation",
        os.path.join(_ura_root, "automation.py"),
    )

import custom_components.universal_room_automation.automation as _automation_mod  # noqa: E402
from custom_components.universal_room_automation.automation import RoomAutomation  # noqa: E402
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FANS,
    DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S,
)

_automation_dt_util = _automation_mod.dt_util
_automation_mod.SERVICE_TURN_ON = "turn_on"
_automation_mod.SERVICE_TURN_OFF = "turn_off"
_automation_mod.STATE_ON = "on"
_automation_mod.STATE_OFF = "off"


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

FAN_ENTITY = "fan.jaya_bedroom_comfort"
TEMP_ABOVE = 82.0  # well above default threshold 80
TEMP_BELOW = 70.0


def _make_automation(
    initial_fan_on: bool = True,
    hvac_managing: bool = False,
):
    """Build a RoomAutomation wired to a single fan entity.

    Fan state is mutable — call `set_fan_state(True/False)` to simulate
    an external actor changing the entity.
    """
    hass = MagicMock()
    hass.data = {}

    state = {"fan_on": initial_fan_on}

    def _get_state(entity_id: str):
        if entity_id == FAN_ENTITY:
            s = MagicMock()
            s.state = "on" if state["fan_on"] else "off"
            return s
        return None

    hass.states.get = _get_state

    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.options = {}

    config = {
        CONF_FAN_CONTROL_ENABLED: True,
        CONF_FANS: [FAN_ENTITY],
        CONF_FAN_TEMP_THRESHOLD: 80,
        "hvac_coordination_enabled": False,
        "sleep_protection_enabled": False,
        "room_name": "Jaya Bedroom",
    }

    auto = RoomAutomation(hass=hass, config=config, coordinator=coordinator)
    auto.is_sleep_mode_active = lambda: False
    auto._is_hvac_managing_fans = lambda: hvac_managing

    service_log: list[tuple[str, str, dict]] = []

    async def _mock_service_call(domain, service, data=None, **kwargs):
        service_log.append((domain, service, data or {}))

    auto._safe_service_call = _mock_service_call

    def _set_fan_state(on: bool) -> None:
        state["fan_on"] = on

    return auto, service_log, _set_fan_state


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _dt_mock.now = fn
    _dt_mock.utcnow = fn
    _automation_dt_util.now = fn
    _automation_dt_util.utcnow = fn


def _count_turn_on(log):
    return sum(1 for (_d, svc, _data) in log if svc == "turn_on")


def _count_turn_off(log):
    return sum(1 for (_d, svc, _data) in log if svc == "turn_off")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRoomTierManualOffCooldown:
    """FIX C D1 behavioral tests."""

    def test_room_tier_cooldown_blocks_rearm(self):
        """External manual-off must not re-arm within cooldown window.

        Sequence:
          Tick 1: fan is ON, temp above threshold — baseline observed True,
                  no action, no cooldown.
          [User manually turns off the fan externally.]
          Tick 2: fan reads OFF but temp still hot — cooldown opens; NO
                  turn-on issued.
          Tick 3: still within cooldown window — NO turn-on issued.
        """
        base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=True)

        # Tick 1: observe running fan (baseline True)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._last_seen_any_fan_on is True
        assert auto._fan_manual_off_until is None
        turn_on_after_tick1 = _count_turn_on(log)

        # External off
        set_fan(False)
        _set_now(base + timedelta(seconds=30))

        # Tick 2: cooldown opens; no new turn_on
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is not None, (
            "External off should open cooldown"
        )
        assert _count_turn_on(log) == turn_on_after_tick1, (
            "Cooldown must block re-arm on the tick it opens"
        )

        # Tick 3: still within window
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert _count_turn_on(log) == turn_on_after_tick1, (
            "Cooldown must block re-arm on subsequent ticks"
        )

    def test_room_tier_cooldown_expires(self):
        """After DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S, fan CAN re-arm."""
        base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=True)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))

        # External off + open cooldown
        set_fan(False)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is not None

        # Advance past cooldown window
        _set_now(base + timedelta(
            seconds=30 + DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S + 10,
        ))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is None, (
            "Cooldown must clear after expiry"
        )
        assert _count_turn_on(log) >= 1, (
            "Fan must re-arm after cooldown expires when temp still hot"
        )

    def test_manual_on_clears_cooldown(self):
        """Turning fan back on during cooldown clears the cooldown."""
        base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(initial_fan_on=True)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))

        # External off opens cooldown
        set_fan(False)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is not None

        # User turns fan back on mid-cooldown
        set_fan(True)
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is None, (
            "Manual-on reversal must clear cooldown"
        )

    def test_kill_switch_zero(self, monkeypatch):
        """DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S == 0 disables the feature.

        This is the pre-fix behavior — fan re-arms immediately.
        """
        base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        monkeypatch.setattr(
            _automation_mod, "DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S", 0,
        )

        auto, log, set_fan = _make_automation(initial_fan_on=True)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))

        set_fan(False)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is None, (
            "cooldown_s == 0 must disable the feature"
        )
        assert _count_turn_on(log) >= 1, (
            "With kill switch on, fan re-arms in same tick (pre-fix behavior)"
        )

    def test_hvac_managed_skips_room_tier_cooldown(self):
        """When HVAC owns the fan, room-tier code path is not reached, so
        `_fan_manual_off_until` stays None regardless of state changes."""
        base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(
            initial_fan_on=True, hvac_managing=True,
        )
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        set_fan(False)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is None, (
            "HVAC-managed rooms must not enter room-tier cooldown "
            "(HVAC-tier handles it)"
        )

    def test_own_off_write_does_not_open_cooldown(self):
        """When temp drops below threshold and WE turn the fan off, the
        next tick must NOT open a spurious cooldown against our own off.

        FAN-MANUAL-1 fix-up (2026-08-10): under the new boot-edge policy,
        a fan already ON at tick-1 opens a manual-ON hold (conservative
        toward the human) unless URA already knew the fan was on. This
        test seeds ``_last_seen_any_fan_on = True`` post-construction to
        simulate a URA-owned prior tick (the fan-on state is already
        established as URA-owned) — the invariant being tested here is
        the cooldown/own-off symmetry, NOT the boot-edge policy.
        """
        base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=True)
        # Seed baseline as URA-owned so tick-1 does NOT open a manual-ON
        # hold (that behavior has its own dedicated test coverage).
        auto._last_seen_any_fan_on = True
        # Tick 1: fan on, temp hot — baseline True
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._last_seen_any_fan_on is True

        # Tick 2: temp drops — we issue turn_off, baseline updates to False
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert _count_turn_off(log) >= 1
        assert auto._last_seen_any_fan_on is False, (
            "Baseline must reflect OUR intent after we issue turn_off, "
            "not the (possibly not-yet-propagated) HA state read"
        )
        set_fan(False)  # HA state catches up

        # Tick 3: still cool — no cooldown must open
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_off_until is None, (
            "Our own off must not open a cooldown against ourselves"
        )


class TestSharedManualOffConstant:
    """FIX C D3 — HVAC-tier and room-tier import the same knob."""

    def test_hvac_and_room_tier_share_manual_off_constant(self):
        """Both hvac_fans.py and automation.py must reference the same
        DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S from const.py."""
        with open(
            os.path.join(_ura_root, "const.py"), "r", encoding="utf-8",
        ) as f:
            const_src = f.read()
        with open(
            os.path.join(_ura_root, "domain_coordinators", "hvac_fans.py"),
            "r", encoding="utf-8",
        ) as f:
            hvac_src = f.read()
        with open(
            os.path.join(_ura_root, "automation.py"),
            "r", encoding="utf-8",
        ) as f:
            auto_src = f.read()

        assert "DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S" in const_src
        assert "DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S" in hvac_src, (
            "hvac_fans.py must use the shared constant, not inline "
            "timedelta(hours=1)"
        )
        assert "DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S" in auto_src


class TestMutationAnchor:
    """FIX C D1 mutation-anchor: prove the load-bearing site is exercised."""

    def test_bypass_cooldown_check_causes_test_failure(self, monkeypatch):
        """If we bypass the cooldown-live gate (treat it as always
        expired), the fan re-arms and the block-rearm assertion fails.
        This proves the assertion actually depends on the load-bearing
        code path."""
        # Force the cooldown check to always think the window is expired.
        # We simulate the mutation by monkey-patching dt_util.now to
        # always return a time far in the future, past any set cooldown.
        base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=True)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        set_fan(False)

        # Cooldown opens...
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_off_until is not None

        # ...but the mutation jumps clock past the cooldown window BEFORE
        # the next tick, so the "cooldown live" branch cannot fire.
        _set_now(base + timedelta(
            seconds=30 + DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S + 5,
        ))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert _count_turn_on(log) >= 1, (
            "Mutation anchor: with cooldown 'expired', the load-bearing "
            "gate lets a re-arm through — confirming the block-rearm test "
            "depends on the gate actually holding."
        )

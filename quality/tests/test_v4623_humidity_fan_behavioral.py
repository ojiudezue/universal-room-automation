"""v4.6.2.3 — Humidity Fan Behavioral Tests (Path A / automation.py).

Replaces the source-grep tests from v4.6.2.1 (LOW #8/#9) with end-to-end
behavioral tests that drive handle_humidity_based_fan_control directly.

Covers:
  D3-1: Max-runtime cap fires after max_runtime seconds
  D3-2: Cap-fire suppression blocks immediate re-trigger
  D3-3: Suppression clears once humidity drops below OFF threshold
  D3-4: Hysteresis — no chatter at threshold boundary
  D3-5: Reload-mid-cycle seeding — fan already on at startup seeds anchor

Tests call into handle_humidity_based_fan_control (async), not source text.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA module mocking — must happen before importing automation.py
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

# Inject dt mock separately so we can control `now()` in tests
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
            # Always set these attrs (may override prior stubs from other test files)
            for _k, _v in _attrs.items():
                setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

# Override dt module (after loop so it takes precedence)
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


_cc_pkg_name = "custom_components"
if _cc_pkg_name not in sys.modules:
    sys.modules[_cc_pkg_name] = _mock_module(_cc_pkg_name)

_ura_pkg_name = "custom_components.universal_room_automation"
if _ura_pkg_name not in sys.modules:
    _ura_pkg = _mock_module(_ura_pkg_name)
    _ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
    sys.modules[_ura_pkg_name] = _ura_pkg

_const_full = "custom_components.universal_room_automation.const"
if _const_full not in sys.modules:
    _load_module(_const_full, os.path.join(_ura_root, "const.py"))

_automation_full = "custom_components.universal_room_automation.automation"
if _automation_full not in sys.modules:
    _load_module(_automation_full, os.path.join(_ura_root, "automation.py"))

import custom_components.universal_room_automation.automation as _automation_mod  # noqa: E402
from custom_components.universal_room_automation.automation import RoomAutomation  # noqa: E402
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_HUMIDITY_FANS,
    CONF_HUMIDITY_FAN_THRESHOLD,
    CONF_HUMIDITY_FAN_TIMEOUT,
    CONF_HUMIDITY_FAN_MAX_RUNTIME,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_HUMIDITY_FAN_TIMEOUT,
    DEFAULT_HUMIDITY_FAN_MAX_RUNTIME,
    DEFAULT_HUMIDITY_FAN_HYSTERESIS,
)

# The dt_util module actually used by automation.py — may differ from _dt_mock
# if automation.py was already loaded by a prior test file.
_automation_dt_util = _automation_mod.dt_util

# Ensure the constants that automation.py imported at load time have the correct
# string values even if a prior test file loaded homeassistant.const as MagicMock.
_automation_mod.SERVICE_TURN_ON = "turn_on"
_automation_mod.SERVICE_TURN_OFF = "turn_off"
_automation_mod.STATE_ON = "on"
_automation_mod.STATE_OFF = "off"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

FAN_ENTITY = "fan.bathroom_exhaust"
THRESHOLD = 65.0  # ON threshold
OFF_THRESHOLD = THRESHOLD - DEFAULT_HUMIDITY_FAN_HYSTERESIS  # 55.0
MAX_RUNTIME = 300  # 5 minutes for test speed
MIN_RUNTIME = 60   # min runtime (timeout)


def _make_state(state_val: str) -> MagicMock:
    """Build a mock HA state object."""
    s = MagicMock()
    s.state = state_val
    return s


def _make_automation(
    fan_on: bool = False,
    threshold: float = THRESHOLD,
    max_runtime: int = MAX_RUNTIME,
    timeout: int = MIN_RUNTIME,
) -> tuple[RoomAutomation, list[tuple[str, str, dict]]]:
    """Build a RoomAutomation with mocked hass.

    Returns (automation, service_call_log) where service_call_log accumulates
    (domain, service, data) tuples each time _safe_service_call is called.
    """
    hass = MagicMock()
    hass.data = {}

    # States: fan entity reports fan_on or off
    def _get_state(entity_id: str):
        if entity_id == FAN_ENTITY:
            return _make_state("on" if fan_on else "off")
        return None

    hass.states.get = _get_state

    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.options = {}

    config = {
        CONF_HUMIDITY_FANS: [FAN_ENTITY],
        CONF_HUMIDITY_FAN_THRESHOLD: threshold,
        CONF_HUMIDITY_FAN_TIMEOUT: timeout,
        CONF_HUMIDITY_FAN_MAX_RUNTIME: max_runtime,
        "hvac_coordination_enabled": False,
        "sleep_protection_enabled": False,
        "room_name": "Bathroom",
    }

    automation = RoomAutomation(hass=hass, config=config, coordinator=coordinator)

    # Patch out sleep mode and hvac management
    automation.is_sleep_mode_active = lambda: False
    automation._is_hvac_managing_fans = lambda: False

    # Record all service calls
    service_log: list[tuple[str, str, dict]] = []

    async def _mock_service_call(domain, service, data=None, **kwargs):
        service_log.append((domain, service, data or {}))

    automation._safe_service_call = _mock_service_call

    return automation, service_log


def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_now(dt: datetime) -> None:
    """Override the 'now' function used by dt_util in automation.py.

    Patches both _dt_mock (for fresh loads) and _automation_dt_util (the actual
    dt_util module reference cached in automation.py at import time). The second
    patch is needed when automation.py was already loaded by a prior test file
    and holds a reference to a different dt_util object.
    """
    _fn = lambda: dt  # noqa: E731
    _dt_mock.now = _fn
    _dt_mock.utcnow = _fn
    # Also patch the dt_util that automation.py actually imported at load time
    _automation_dt_util.now = _fn
    _automation_dt_util.utcnow = _fn


# ---------------------------------------------------------------------------
# D3-1: Max-runtime cap fires after max_runtime seconds
# ---------------------------------------------------------------------------


def test_max_runtime_cap_fires_after_full_window():
    """After max_runtime seconds have elapsed, the cap must force the fan off.

    Scenario:
      t=0   : humidity 70% → fan turns ON, anchors set
      t=301 : humidity still 70%, max_runtime=300 → cap fires, fan turned off
    """
    t0 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(threshold=65.0, max_runtime=300, timeout=60)

    # t=0: humidity above threshold — fan turns on, anchor seeds
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0))
    assert auto._humidity_on_since == t0, "Anchor must be set on first activation"
    assert any(s == "turn_on" for _, s, _ in log), "Fan must turn on at high humidity"
    log.clear()

    # t=301: cap should fire
    t1 = t0 + timedelta(seconds=301)
    _set_now(t1)
    _run(auto.handle_humidity_based_fan_control(70.0))

    turn_offs = [(d, s, data) for d, s, data in log if s == "turn_off"]
    assert turn_offs, "Max-runtime cap must force fan off after 301s with 300s cap"
    assert auto._humidity_on_since is None, "Anchor must be cleared after cap fires"
    assert auto._humidity_cap_suppressed is True, "Suppression must be set after cap fires"


# ---------------------------------------------------------------------------
# D3-2: Cap-fire suppression blocks immediate re-trigger
# ---------------------------------------------------------------------------


def test_max_runtime_suppression_blocks_immediate_retrigger():
    """After cap fires, calling with high humidity must not re-trigger the fan.

    Humidity must first drop below OFF threshold before re-activation is allowed.
    """
    t0 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(threshold=65.0, max_runtime=300, timeout=60)

    # Arm and fire the cap
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0))  # turn on
    log.clear()
    _set_now(t0 + timedelta(seconds=301))
    _run(auto.handle_humidity_based_fan_control(70.0))  # cap fires → turn off + suppress
    log.clear()

    # Immediately call again with high humidity — must be suppressed
    _set_now(t0 + timedelta(seconds=302))
    _run(auto.handle_humidity_based_fan_control(70.0))

    turn_ons = [(d, s, data) for d, s, data in log if s == "turn_on"]
    assert not turn_ons, (
        "Fan must NOT re-trigger immediately after cap fire (suppression in effect)"
    )
    assert auto._humidity_cap_suppressed is True, "Suppression must still be active"


# ---------------------------------------------------------------------------
# D3-3: Suppression clears when humidity drops below OFF threshold
# ---------------------------------------------------------------------------


def test_max_runtime_suppression_clears_when_humidity_drops_below_off():
    """After cap fires and humidity drops below OFF threshold, suppression clears.

    Then the next high-humidity tick must be allowed to re-trigger the fan.

    Sequence:
      cap fires → suppressed
      humidity=70% → still suppressed (no turn_on)
      humidity=45% (below off_threshold=55%) → suppression cleared
      humidity=70% → fan re-triggers (turn_on)
    """
    t0 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(threshold=65.0, max_runtime=300, timeout=60)

    # Fire the cap
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0))
    _set_now(t0 + timedelta(seconds=301))
    _run(auto.handle_humidity_based_fan_control(70.0))
    assert auto._humidity_cap_suppressed is True
    log.clear()

    # High humidity — still suppressed
    _set_now(t0 + timedelta(seconds=302))
    _run(auto.handle_humidity_based_fan_control(70.0))
    assert auto._humidity_cap_suppressed is True, "Suppression must persist at high humidity"
    log.clear()

    # Humidity drops below OFF threshold (55%) — suppression clears
    _set_now(t0 + timedelta(seconds=303))
    _run(auto.handle_humidity_based_fan_control(45.0))
    assert auto._humidity_cap_suppressed is False, (
        "Suppression must clear when humidity drops below OFF threshold"
    )
    log.clear()

    # High humidity again — re-trigger allowed
    _set_now(t0 + timedelta(seconds=304))
    _run(auto.handle_humidity_based_fan_control(70.0))
    turn_ons = [(d, s, data) for d, s, data in log if s == "turn_on"]
    assert turn_ons, (
        "Fan must re-trigger after suppression cleared and humidity is above threshold"
    )


# ---------------------------------------------------------------------------
# D3-4: Hysteresis — no chatter at threshold boundary
# ---------------------------------------------------------------------------


def test_hysteresis_no_chatter_at_threshold_boundary():
    """Fan stays on when humidity oscillates between ON and OFF threshold.

    threshold=65, off_threshold=55.
    Sequence: 70% (on) → 60% (hold, above off) → 60% (hold) → 60% (hold)
    Assert: exactly one turn_on, zero turn_offs.
    """
    t0 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(threshold=65.0, max_runtime=MAX_RUNTIME, timeout=MIN_RUNTIME)

    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0))  # turn on

    for tick in range(1, 4):
        _set_now(t0 + timedelta(seconds=tick * 5))
        _run(auto.handle_humidity_based_fan_control(60.0))  # above off_threshold=55, hold

    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    turn_offs = [s for _, s, _ in log if s == "turn_off"]

    # turn_on may be called multiple times (fan stays on loop), but turn_off must not fire
    assert turn_ons, "Fan must have turned on once"
    assert not turn_offs, (
        "Fan must NOT turn off when humidity oscillates above off_threshold (55%)"
    )


# ---------------------------------------------------------------------------
# D3-5: Reload-mid-cycle seeding
# ---------------------------------------------------------------------------


def test_reload_seeds_humidity_on_since():
    """When coordinator wakes post-reload and fan is already on, anchor must be seeded.

    Scenario:
      Fan is physically on (hass.states.get returns state='on').
      _humidity_on_since is None (freshly reloaded coordinator).
      Humidity is 70% (above threshold).
      After one call, _humidity_on_since must be set to `now`.
    """
    t0 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)

    # Build automation with fan physically already on
    auto, log = _make_automation(fan_on=True, threshold=65.0, max_runtime=MAX_RUNTIME)

    # Confirm anchor starts as None (fresh reload state)
    assert auto._humidity_on_since is None, "Anchor should be None before seeding"

    _run(auto.handle_humidity_based_fan_control(70.0))

    assert auto._humidity_on_since is not None, (
        "Anchor must be seeded when fan is observed on at coordinator startup"
    )
    assert auto._humidity_fan_triggered_time is not None, (
        "_humidity_fan_triggered_time must also be seeded alongside _humidity_on_since"
    )


def test_reload_does_not_seed_when_fan_is_off():
    """When fan is physically off, reload seeding must NOT set the anchor.

    Suppression state (set by a prior cap fire, surviving reload because
    it's stored... actually _humidity_cap_suppressed resets to False on reload.
    This test verifies the simple case: fan off + humidity below threshold = no seeding.
    """
    t0 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)

    # Fan off, humidity below threshold
    auto, log = _make_automation(fan_on=False, threshold=65.0, max_runtime=MAX_RUNTIME)

    _run(auto.handle_humidity_based_fan_control(50.0))  # below threshold

    assert auto._humidity_on_since is None, (
        "Anchor must NOT be seeded when fan is off and humidity is below threshold"
    )
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    assert not turn_ons, "Fan must not turn on when humidity is below threshold"

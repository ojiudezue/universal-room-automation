"""Bathroom exhaust — occupancy-dwell + resend-fix behavioral tests.

Covers the bathroom-exhaust occupancy-and-resend cycle (2026-10-14):

* D1 — humidity venting is decoupled from the room master-automation
  switch (``humidity_venting_enabled`` drops ``automation_enabled`` arg).
* D2 — transition-gated ``turn_on`` + capped re-assert + external
  manual-OFF window (state-change listener).  No untransitioned ``turn_off``
  spam on repeat sleep ticks / off-threshold ticks.
* D3 — occupancy-dwell "number-2" trigger on raw occupancy / motion
  sensor's continuous ON-run; dwell-OFF branch for no-humidity rooms;
  dwell HOLDS the fan on while occupied; presence-runtime window arms
  regardless of ``wet_room`` when dwell fires.

The harness drives ``handle_humidity_based_fan_control`` end-to-end.
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

_captured_track_cbs: list = []


def _track_state_change_event(hass, entities, cb):
    _captured_track_cbs.append((tuple(entities), cb))
    return _mock_cls()


_ha_mods: dict = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "Context": lambda **kw: types.SimpleNamespace(
            id="ulid", parent_id=kw.get("parent_id"), user_id=kw.get("user_id"),
        ),
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
        "async_track_state_change_event": _track_state_change_event,
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
# Load the REAL custom_components.universal_room_automation package by
# pointing the package stub's ``__path__`` at the on-disk directory so
# ``from .cover_ownership`` and friends resolve.
# ---------------------------------------------------------------------------

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.abspath(os.path.join(
    _project_root, "custom_components", "universal_room_automation",
))

_cc_pkg_name = "custom_components"
if _cc_pkg_name not in sys.modules:
    _cc_pkg = _mock_module(_cc_pkg_name)
    _cc_pkg.__path__ = [os.path.abspath(os.path.join(_project_root, "custom_components"))]
    sys.modules[_cc_pkg_name] = _cc_pkg
else:
    sys.modules[_cc_pkg_name].__path__ = [
        os.path.abspath(os.path.join(_project_root, "custom_components")),
    ]

_ura_pkg_name = "custom_components.universal_room_automation"
if _ura_pkg_name not in sys.modules:
    _ura_pkg = _mock_module(_ura_pkg_name)
    _ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
    _ura_pkg.__path__ = [_ura_root]
    sys.modules[_ura_pkg_name] = _ura_pkg
else:
    sys.modules[_ura_pkg_name].__path__ = [_ura_root]


def _load_module(full_name: str, filepath: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_const_full = "custom_components.universal_room_automation.const"
if _const_full not in sys.modules:
    _load_module(_const_full, os.path.join(_ura_root, "const.py"))

_automation_full = "custom_components.universal_room_automation.automation"
if _automation_full not in sys.modules:
    _load_module(_automation_full, os.path.join(_ura_root, "automation.py"))


import custom_components.universal_room_automation.automation as _automation_mod  # noqa: E402
from custom_components.universal_room_automation.automation import RoomAutomation  # noqa: E402
from custom_components.universal_room_automation._humidity_gate import (  # noqa: E402
    humidity_venting_enabled,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_HUMIDITY_FANS,
    CONF_HUMIDITY_FAN_THRESHOLD,
    CONF_HUMIDITY_FAN_TIMEOUT,
    CONF_HUMIDITY_FAN_MAX_RUNTIME,
    CONF_HUMIDITY_FAN_CONTROL_ENABLED,
    CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED,
    CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_WET_ROOM,
    CONF_FAN_SLEEP_POLICY,
    FAN_SLEEP_OFF,
    HUMIDITY_FAN_REASSERT_INTERVAL_S,
    HUMIDITY_FAN_MANUAL_OFF_RESPECT_S,
    DEFAULT_HUMIDITY_FAN_HYSTERESIS,
)

_automation_dt_util = _automation_mod.dt_util
_automation_mod.SERVICE_TURN_ON = "turn_on"
_automation_mod.SERVICE_TURN_OFF = "turn_off"
_automation_mod.STATE_ON = "on"
_automation_mod.STATE_OFF = "off"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

FAN_ENTITY = "fan.bathroom_exhaust"
RAW_SENSOR = "binary_sensor.bath_occupancy"
THRESHOLD = 65.0


def _mkstate(state: str, last_changed: datetime | None = None, context=None):
    s = MagicMock()
    s.state = state
    s.last_changed = last_changed or _dt_now_fn()
    s.context = context
    s.entity_id = None
    return s


def _make(
    *,
    fan_on: bool = False,
    raw_state: str = "off",
    raw_last_changed: datetime | None = None,
    dwell_enabled: bool = True,
    dwell_s: int = 60,
    wet_room: bool = False,
    presence_runtime: bool = True,
    threshold: float = THRESHOLD,
    max_runtime: int = 3600,
    timeout: int = 60,
    sleep: bool = False,
):
    hass = MagicMock()
    hass.data = {}

    states = {
        FAN_ENTITY: _mkstate("on" if fan_on else "off"),
        RAW_SENSOR: _mkstate(raw_state, raw_last_changed or _dt_now_fn()),
    }
    hass.states.get = lambda entity_id: states.get(entity_id)

    config = {
        CONF_HUMIDITY_FANS: [FAN_ENTITY],
        CONF_HUMIDITY_FAN_THRESHOLD: threshold,
        CONF_HUMIDITY_FAN_TIMEOUT: timeout,
        CONF_HUMIDITY_FAN_MAX_RUNTIME: max_runtime,
        CONF_HUMIDITY_FAN_CONTROL_ENABLED: True,
        CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED: dwell_enabled,
        CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S: dwell_s,
        CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED: presence_runtime,
        CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S: 60,
        CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S: 30,
        CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S: 600,
        CONF_OCCUPANCY_SENSORS: [RAW_SENSOR],
        CONF_WET_ROOM: wet_room,
        CONF_FAN_SLEEP_POLICY: FAN_SLEEP_OFF,
        "hvac_coordination_enabled": False,
        "sleep_protection_enabled": False,
        "room_name": "Bathroom",
    }
    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.data = dict(config)
    coordinator.entry.options = {}
    auto = RoomAutomation(hass=hass, config=config, coordinator=coordinator)
    auto.is_sleep_mode_active = (lambda: True) if sleep else (lambda: False)
    auto._is_hvac_managing_fans = lambda: False

    log: list = []

    async def _svc(domain, service, data=None, blocking=False, context=None, **_):
        log.append((domain, service, dict(data or {}), context))

    auto._safe_service_call = _svc
    return auto, log, states


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _dt_mock.now = fn
    _dt_mock.utcnow = fn
    _automation_dt_util.now = fn
    _automation_dt_util.utcnow = fn


# ---------------------------------------------------------------------------
# D1 — venting decoupled from master-automation
# ---------------------------------------------------------------------------

def test_humidity_venting_enabled_signature_drops_automation_arg():
    """D1 finding #10 — ``humidity_venting_enabled`` takes ONE arg."""
    # Call with the only remaining positional and verify behavior.
    assert humidity_venting_enabled(False) is True
    assert humidity_venting_enabled(True) is False
    # Two-arg call must raise (back-compat kw dropped).
    with pytest.raises(TypeError):
        humidity_venting_enabled(False, True)  # type: ignore[call-arg]


def test_humidity_venting_runs_with_master_off():
    """D1 — ``automation_enabled=True`` (skip_first inverse) + high humidity fires."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make()
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons, "D1: high humidity must fire turn_on regardless of master switch"


# ---------------------------------------------------------------------------
# D2 — transition-gated ON, re-assert, manual-off, transition-gated OFF
# ---------------------------------------------------------------------------

def test_humidity_fan_turn_on_only_on_transition():
    """D2 — 20 ticks above threshold → exactly 1 ``turn_on``."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, states = _make()
    for i in range(20):
        _set_now(t0 + timedelta(seconds=i * 30))
        # Simulate fan actually turning on after first emission.
        states[FAN_ENTITY] = _mkstate("on" if i >= 1 else "off")
        _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert len(turn_ons) == 1, f"D2: expected 1 turn_on, got {len(turn_ons)}: {log}"


def test_humidity_fan_reassert_on_actual_off():
    """D2 — anchor says ON but fan actually OFF → re-assert every 180 s."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, states = _make()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    # Fan reports OFF despite anchor ON (relay drop).
    for i in range(1, 5):
        _set_now(t0 + timedelta(seconds=i * HUMIDITY_FAN_REASSERT_INTERVAL_S))
        _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert len(turn_ons) >= 2, (
        f"D2: expected re-asserts at reassert interval, got {len(turn_ons)}: {log}"
    )


def test_humidity_fan_no_reassert_when_actually_on():
    """D2 — anchor ON and fan actually ON → zero re-asserts."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, states = _make()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    states[FAN_ENTITY] = _mkstate("on")
    for i in range(1, 10):
        _set_now(t0 + timedelta(seconds=i * HUMIDITY_FAN_REASSERT_INTERVAL_S))
        _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert len(turn_ons) == 1, f"D2: should not re-assert when fan is actually on: {log}"


def test_humidity_fan_sleep_off_no_spam_when_already_off():
    """D2 finding #6 — sleep-off emits ``turn_off`` ONCE, not every tick."""
    t0 = datetime(2026, 10, 14, 3, 0, 0, tzinfo=timezone.utc)
    auto, log, _ = _make(sleep=True, wet_room=False, fan_on=False)
    # Anchor is None, fan is off — sleep policy should NOT emit turn_off.
    for i in range(5):
        _set_now(t0 + timedelta(seconds=i * 30))
        _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        f"D2 finding #6: no turn_off while fan already off; got {turn_offs}"
    )


def test_humidity_fan_manual_off_from_state_change_listener():
    """D2 finding #5 — external on→off (non-URA context) arms the window."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, states = _make()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    assert auto._humidity_fan_triggered_time is not None
    # Simulate external off: build a state_changed event with foreign context.
    ev = types.SimpleNamespace()
    ev.data = {
        "new_state": _mkstate("off", context=types.SimpleNamespace(parent_id=None)),
        "old_state": _mkstate("on"),
    }
    ev.context = types.SimpleNamespace(parent_id=None, id="external-ulid", user_id="someone")
    auto._on_humidity_fan_state_change(ev)
    assert auto._humidity_fan_manual_off_until is not None
    assert auto._humidity_fan_triggered_time is None, (
        "External OFF must clear anchors"
    )
    # Within the window, high humidity must NOT re-trigger.
    _set_now(t0 + timedelta(seconds=5))
    log.clear()
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == [], (
        f"D2 finding #5: manual-OFF window must block re-trigger; got {turn_ons}"
    )


def test_humidity_fan_unavailable_not_manual():
    """D2 finding #5 — on→unavailable does NOT arm the manual-OFF window."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, _ = _make()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    ev = types.SimpleNamespace()
    ev.data = {
        "new_state": _mkstate("unavailable"),
        "old_state": _mkstate("on"),
    }
    ev.context = types.SimpleNamespace(parent_id=None)
    auto._on_humidity_fan_state_change(ev)
    assert auto._humidity_fan_manual_off_until is None, (
        "unavailable is a relay drop; must not arm manual-OFF window"
    )


# ---------------------------------------------------------------------------
# D3 — occupancy-dwell + no-humidity rooms
# ---------------------------------------------------------------------------

def test_humidity_fan_dwell_fires_in_rooms_without_humidity_sensor():
    """D3 — raw sensor ON >= dwell_s with humidity=None → fan ON."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    # Raw sensor turned ON 61 s ago.
    raw_lc = t0 - timedelta(seconds=61)
    auto, log, _ = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons, f"D3: dwell satisfied + humidity=None must fire turn_on; got {log}"
    assert auto._humidity_dwell_fan_on_at is not None


def test_humidity_fan_no_crash_when_humidity_none():
    """Rev 2 finding #7 — tick with humidity=None exercises every reader."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, _, _ = _make()
    # Must not raise.
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=False, automation_enabled=True))


def test_humidity_fan_dwell_uses_raw_sensor_not_room_timer():
    """Rev 2 finding #4 — room-occupied=True 10 min but raw sensor OFF → no fire."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, _ = _make(raw_state="off", raw_last_changed=t0 - timedelta(seconds=600), dwell_s=60)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == [], "Dwell must gate on raw-sensor ON-run, not URA room-occupied"


def test_humidity_fan_dwell_hold_blocks_humidity_off_while_occupied():
    """Rev 2 finding #2 — dwell holds the fan ON; humidity-OFF branch is blocked."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    # Dwell fires (raw sensor ON ≥ dwell_s), fan comes on.
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, states = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60, timeout=1)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    log.clear()
    # Humidity collapses below off_threshold while STILL occupied.
    _set_now(t0 + timedelta(seconds=200))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=True, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        f"Rev 2 #2: dwell + occupied must block humidity-OFF; got {log}"
    )


def test_humidity_fan_dwell_off_when_window_expires_no_humidity():
    """Rev 2 finding #1 — presence-runtime window expired + vacant + humidity=None → OFF."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    # Dwell satisfied → fan on by dwell.
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, states = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at is not None
    # Simulate: room vacates, presence-runtime window arms.
    states[RAW_SENSOR] = _mkstate("off", t0 + timedelta(seconds=120))
    _set_now(t0 + timedelta(seconds=121))
    states[FAN_ENTITY] = _mkstate("on")
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=False, automation_enabled=True))
    # Force window expiration.
    auto._humidity_presence_runtime_until = t0 + timedelta(seconds=120)
    _set_now(t0 + timedelta(seconds=300))
    log.clear()
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=False, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs, f"Rev 2 #1: dwell-OFF branch must emit turn_off; got {log}"
    assert auto._humidity_dwell_fan_on_at is None, "Dwell anchor must clear on off-emit"


def test_humidity_fan_dwell_disabled_no_fire():
    """D3 — dwell_enabled=False → raw sensor ON forever does nothing."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, _ = _make(
        raw_state="on", raw_last_changed=t0 - timedelta(seconds=600),
        dwell_enabled=False,
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == []


def test_humidity_fan_dwell_single_actuation_regardless_of_source():
    """D3 — humidity + dwell satisfied same tick → single turn_on."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=120)
    auto, log, _ = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert len(turn_ons) == 1

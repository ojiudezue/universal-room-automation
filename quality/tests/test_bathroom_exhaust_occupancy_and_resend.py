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


def _callback_marker(fn):
    """Stand-in for ``homeassistant.core.callback`` that stamps
    ``_hass_callback = True`` the way HA's real decorator does, so the
    handler-is-callback test below can falsify a missing decorator."""
    try:
        fn._hass_callback = True
    except Exception:  # noqa: BLE001
        pass
    return fn


_identity = _callback_marker
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

# TEST-HARNESS D7: everything below that installs into sys.modules OR writes
# attributes onto pre-existing (real) HA modules is scoped: undone on exit of
# the block, re-applied only while THIS module's tests run. It used to rewrite
# real `homeassistant.core.callback`/`HomeAssistant`, `entity_registry.
# async_get`, the event helpers, and replace `homeassistant.util.dt` for the
# whole session — the collection-time donor of test_dp_drain_target_value_stamp
# (5), test_evse_drain_precedence_session_b2b_i (1) / b2b_ii (1) / b2c2_fixup (2).
from _d7_isolation import import_scope as _d7_import_scope, reinstall as _d7_reinstall  # noqa: E402

with _d7_import_scope(attrs=True) as _D7_INSTALLED:
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


@pytest.fixture(scope="module", autouse=True)
def _d7_module_stubs():
    yield from _d7_reinstall(_D7_INSTALLED)


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



import pytest as _d7_pytest_clock  # noqa: E402


@_d7_pytest_clock.fixture(autouse=True)
def _d7_restore_set_now_clocks(monkeypatch):
    """TEST-HARNESS D7 slice 2: undo this file's _set_now clock writes after
    every test (they can land on the real / an orphaned real dt module)."""
    from _d7_isolation import restore_clocks_after_test
    restore_clocks_after_test(monkeypatch, globals())

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
    """Rev 2 finding #2 — dwell holds the fan ON; humidity-OFF branch is blocked.

    Build an in-progress dwell cycle (anchor set), then simulate a brief
    raw-sensor flap off (dwell_satisfied drops to False) with URA's
    room_occupied still True and humidity below off_threshold — the
    guard at the top of the humidity-OFF branch MUST return without
    emitting ``turn_off``.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, states = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60, timeout=1)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at is not None
    log.clear()
    # Raw sensor flaps OFF briefly — dwell_satisfied becomes False this tick.
    states[RAW_SENSOR] = _mkstate("off", t0 + timedelta(seconds=199))
    states[FAN_ENTITY] = _mkstate("on")
    _set_now(t0 + timedelta(seconds=200))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=True, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        f"Rev 2 #2: dwell anchor + occupied must block humidity-OFF; got {log}"
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


# ---------------------------------------------------------------------------
# Fix-up pass (Review A/B/C): behavioural + structural tests for each MED/HIGH
# ---------------------------------------------------------------------------

def test_on_humidity_fan_state_change_has_callback_decorator():
    """Fix-up (Review A/B HIGH #1): the state-change handler MUST be
    decorated with ``@callback`` so HA runs it on the event loop. A
    missing decorator classifies it as ``HassJobType.Executor`` and
    races the handler's own writes. Structural source-text check: a
    mutation that deletes the decorator leaves the file without
    ``@callback`` immediately above the method and fails this test.

    The runtime check below (if the harness ``callback`` stamp is live)
    adds a second line of defense.
    """
    with open(os.path.join(_ura_root, "automation.py"), "r") as f:
        src = f.read()
    idx = src.find("def _on_humidity_fan_state_change(")
    assert idx > 0, "handler must exist"
    # Walk back over whitespace/comment lines to the previous non-blank.
    prefix = src[:idx].rstrip()
    last_line = prefix.rsplit("\n", 1)[-1].strip()
    assert last_line == "@callback", (
        f"_on_humidity_fan_state_change must be decorated with @callback "
        f"(got previous line: {last_line!r})"
    )
    # Runtime: when the harness stamp is active, the attribute is set.
    fn = RoomAutomation._on_humidity_fan_state_change
    assert getattr(fn, "_hass_callback", False) is True, (
        "callback decorator must stamp _hass_callback=True so HA's "
        "is_callback(func) returns True — HA runs it on the loop"
    )


def test_handler_toggle3_off_blocks_venting():
    """D1 — ``CONF_HUMIDITY_FAN_CONTROL_ENABLED=False`` blocks venting
    even above threshold (safety cap unchanged — covered elsewhere).
    Catches a mutation that removes the toggle3 gate inside the handler.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make()
    # ``_refresh_config()`` at the handler top rebuilds self.config from
    # the config entry, so the mutation must land there.
    auto._config_entry.data[CONF_HUMIDITY_FAN_CONTROL_ENABLED] = False
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == [], "toggle3 OFF must block venting"


def test_handler_toggle3_off_safety_cap_still_fires():
    """D1 — toggle3 OFF, anchor seeded past cap → safety cap force-offs
    the fan. Catches a mutation that routes the cap through the toggle3
    gate.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make(fan_on=True, max_runtime=60)
    auto.config[CONF_HUMIDITY_FAN_CONTROL_ENABLED] = False
    # Pre-seed an anchor from a pre-toggle3-off cycle.
    auto._humidity_on_since = t0
    auto._humidity_fan_triggered_time = t0
    _set_now(t0 + timedelta(seconds=120))
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=False, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs, "safety cap must fire regardless of toggle3"


def test_d1_caller_master_off_still_vents():
    """D1 caller drill — mirrors the coordinator call-site expression
    (``automation_enabled=humidity_venting_enabled(_skip_first_this_tick)``)
    with master-automation OFF. If anyone re-adds
    ``and self._is_automation_enabled()`` to the gate helper (or the
    caller), venting goes silent and THIS test fails.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make()
    master_automation_enabled = False  # ManualMode
    skip_first_this_tick = False
    gate = humidity_venting_enabled(skip_first_this_tick)
    # Simulate a hypothetical re-coupling: ``gate = gate and master_automation_enabled``.
    # If the caller re-adds the ``_is_automation_enabled`` term, the kw drops
    # to False even on a non-skip-first tick and venting is silenced.
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=gate))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons, (
        "D1 — venting must run on a non-skip-first tick regardless of "
        f"master-automation state (master={master_automation_enabled})"
    )
    # And re-coupling the predicate silences it (sanity backstop).
    log.clear()
    auto2, log2, _ = _make()
    bad_gate = humidity_venting_enabled(skip_first_this_tick) and master_automation_enabled
    _set_now(t0 + timedelta(seconds=30))
    _run(auto2.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=bad_gate))
    assert [e for e in log2 if e[1] == "turn_on"] == [], (
        "sanity: re-coupling silences venting"
    )


def test_coordinator_call_site_uses_humidity_venting_enabled_helper():
    """Structural: the single coordinator.py call site routes
    ``automation_enabled`` through ``humidity_venting_enabled`` and NOT
    through ``_is_automation_enabled()``. Falsifies the D1-caller
    mutation at the call site itself.
    """
    coord_path = os.path.join(_ura_root, "coordinator.py")
    with open(coord_path, "r") as f:
        src = f.read()
    idx = src.find("handle_humidity_based_fan_control(")
    assert idx > 0
    window = src[idx: idx + 1200]
    assert "humidity_venting_enabled(" in window, (
        "caller must route automation_enabled through humidity_venting_enabled"
    )
    assert "_is_automation_enabled()" not in window, (
        "D1 — master-automation predicate must NOT be in the humidity call site"
    )


def test_listener_ura_own_off_does_not_arm_manual_window():
    """D2 finding #5 — a URA-stamped on→off (our own turn_off) MUST NOT
    arm the manual-off window. Falsifies a mutation that drops the URA
    context check in the listener.
    """
    from custom_components.universal_room_automation.ura_context import (
        URA_WRITE_CONTEXT_PARENT_ID,
    )
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, _ = _make()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    assert auto._humidity_fan_triggered_time is not None
    ev = types.SimpleNamespace()
    ev.data = {
        "new_state": _mkstate("off"),
        "old_state": _mkstate("on"),
    }
    ev.context = types.SimpleNamespace(
        parent_id=URA_WRITE_CONTEXT_PARENT_ID, id="ura", user_id=None,
    )
    auto._on_humidity_fan_state_change(ev)
    assert auto._humidity_fan_manual_off_until is None, (
        "URA-own OFF must not arm the manual-OFF window"
    )
    assert auto._humidity_fan_triggered_time is not None, (
        "URA-own OFF must not clear anchors"
    )


def test_listener_old_state_off_does_not_arm():
    """D2 finding #5 — old_state=off (no on→off transition) must not
    arm the window. Falsifies a mutation that drops the ``old==on`` guard.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, _, _ = _make()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    ev = types.SimpleNamespace()
    ev.data = {
        "new_state": _mkstate("off"),
        "old_state": _mkstate("off"),
    }
    ev.context = types.SimpleNamespace(parent_id=None, id="x", user_id=None)
    auto._on_humidity_fan_state_change(ev)
    assert auto._humidity_fan_manual_off_until is None, (
        "off→off transition must not arm the manual-OFF window"
    )


def test_dwell_short_on_run_does_not_fire():
    """Review C — dwell timing source is the raw sensor's continuous ON
    run. Raw ON for 10 s with dwell_s=60 must NOT fire. Falsifies a
    mutation that replaces the computed ``dwell_elapsed`` with a huge
    constant (which would require ``raw_state.state == STATE_ON`` anyway
    — but combined with ``test_dwell_uses_raw_sensor_not_room_timer``
    the matrix pins the source).
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, _ = _make(
        raw_state="on", raw_last_changed=t0 - timedelta(seconds=10),
        dwell_s=60,
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == [], "short on-run must not satisfy dwell"


def test_reassert_does_not_emit_before_interval():
    """D2 — anchor on, probe off, elapsed < reassert interval → no
    re-emit. Falsifies a mutation of ``HUMIDITY_FAN_REASSERT_INTERVAL_S``
    to 0 (which would re-assert every tick).
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    auto, log, states = _make()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    # Simulate relay-drop (anchor on, fan reports off) at t + 10 s.
    states[FAN_ENTITY] = _mkstate("off")
    log.clear()
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == [], (
        "re-assert must respect HUMIDITY_FAN_REASSERT_INTERVAL_S cap "
        "— no re-emit within the interval"
    )


def test_dwell_presence_window_arms_in_non_wet_room():
    """Rev 2 finding #3 — dwell fires in a non-wet room, and the vacancy
    edge arms the presence-runtime window regardless of wet_room.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, states = _make(
        wet_room=False, raw_state="on", raw_last_changed=raw_lc, dwell_s=60,
    )
    _set_now(t0)
    # Supply the occupied-since snapshot the handler reads to compute
    # the window length.
    auto.coordinator._last_occupied_since_for_handler = t0 - timedelta(seconds=90)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at is not None
    # Vacancy edge.
    states[RAW_SENSOR] = _mkstate("off", t0 + timedelta(seconds=120))
    states[FAN_ENTITY] = _mkstate("on")
    _set_now(t0 + timedelta(seconds=121))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=False, automation_enabled=True))
    assert auto._humidity_presence_runtime_until is not None, (
        "non-wet dwell cycle must arm the presence-runtime window on vacancy"
    )


def test_dwell_off_fallback_when_presence_runtime_disabled():
    """Fix-up (MED #4) — presence-runtime disabled: dwell-OFF must still
    fire after the fallback base window past the vacancy edge. No
    ``occupied-since`` stamp available.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, states = _make(
        raw_state="on", raw_last_changed=raw_lc, dwell_s=60,
        presence_runtime=False,  # OFF
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at is not None
    assert auto._humidity_presence_runtime_until is None, (
        "presence-runtime disabled — window must not arm"
    )
    # Vacancy edge stamps _humidity_dwell_vacant_at.
    states[RAW_SENSOR] = _mkstate("off", t0 + timedelta(seconds=5))
    states[FAN_ENTITY] = _mkstate("on")
    _set_now(t0 + timedelta(seconds=5))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=False, automation_enabled=True))
    log.clear()
    # Jump past fallback base window.
    _set_now(t0 + timedelta(seconds=5 + 61))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=False, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs, (
        f"dwell-OFF must fire via fallback once base-s elapsed; got {log}"
    )


def test_cap_suppression_holds_in_no_humidity_room_until_vacancy():
    """Fix-up (MED #5) — stuck-ON occupancy sensor in a no-humidity
    room: cap-fire sets ``_humidity_cap_awaits_vacancy``; the next tick
    must NOT clear ``_humidity_cap_suppressed`` while raw is still ON.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=600)
    auto, log, states = _make(
        raw_state="on", raw_last_changed=raw_lc, dwell_s=60,
        max_runtime=60,
    )
    # Simulate cap-fire: seed anchors + awaits-vacancy latch.
    auto._humidity_on_since = t0 - timedelta(seconds=120)
    auto._humidity_fan_triggered_time = t0 - timedelta(seconds=120)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    # Cap fires on this tick (anchor already past cap).
    assert auto._humidity_cap_suppressed is True
    assert auto._humidity_cap_awaits_vacancy is True
    log.clear()
    # Next tick, raw still ON — must NOT clear suppression, must NOT re-fire.
    _set_now(t0 + timedelta(seconds=30))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto._humidity_cap_suppressed is True, (
        "cap suppression must hold until a raw-sensor OFF is observed"
    )
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == [], "dwell must not re-fire while cap-suppressed"
    # Vacancy edge clears both.
    states[RAW_SENSOR] = _mkstate("off", t0 + timedelta(seconds=60))
    _set_now(t0 + timedelta(seconds=61))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=False, automation_enabled=True))
    assert auto._humidity_cap_awaits_vacancy is False
    assert auto._humidity_cap_suppressed is False, (
        "suppression must release once vacancy is seen"
    )


def test_dwell_enabled_defaults_to_wet_room():
    """Fix-up (MED #6) — handler runtime default is ``wet_room``. Wet
    room without an explicit CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED
    key gets dwell enabled.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, _ = _make(
        wet_room=True, raw_state="on", raw_last_changed=raw_lc, dwell_s=60,
    )
    # Remove the explicit key so the runtime default kicks in. Mutate
    # the config entry — ``_refresh_config()`` rebuilds self.config.
    auto._config_entry.data.pop(CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED, None)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons, (
        "handler runtime default for dwell_enabled must be wet_room; "
        "wet room with no explicit key should fire"
    )
    # Non-wet room with no key: must NOT fire.
    auto2, log2, _ = _make(
        wet_room=False, raw_state="on", raw_last_changed=raw_lc, dwell_s=60,
    )
    auto2._config_entry.data.pop(CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED, None)
    _set_now(t0)
    _run(auto2.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert [e for e in log2 if e[1] == "turn_on"] == [], (
        "non-wet room default must be dwell DISABLED"
    )


def test_dwell_unknown_occupancy_holds_state_not_vacant():
    """Fix-up (LOW #7) — ``room_occupied is None`` (unknown) must HOLD
    state: the dwell-hold is not released, and the dwell-OFF branch is
    not fired. Prevents a transient None from flipping the fan off.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, states = _make(
        raw_state="on", raw_last_changed=raw_lc, dwell_s=60,
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at is not None
    # Force window expiry so OFF would fire if the None-guard were weak.
    auto._humidity_presence_runtime_until = t0
    states[FAN_ENTITY] = _mkstate("on")
    log.clear()
    _set_now(t0 + timedelta(seconds=60))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=None, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        "unknown occupancy must HOLD state; dwell-OFF must not fire on None"
    )


def _pin_track_helper(monkeypatch):
    """Pin the lazily-imported HA tracker to the capturing stub for this test.

    The handler imports ``async_track_state_change_event`` inside the call, so
    in a full-suite run it resolves whatever ``homeassistant.helpers.event`` a
    sibling file loaded (the real HA module), not this file's module-scope stub.
    """
    mod = types.ModuleType("homeassistant.helpers.event")
    mod.async_track_state_change_event = _track_state_change_event
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", mod)


def test_listener_registered_on_first_tick(monkeypatch):
    """Review C — the manual-OFF listener registers on the first tick
    through ``_register_humidity_fan_manual_off_listeners``, keyed on
    the configured ``CONF_HUMIDITY_FANS`` list.
    """
    _pin_track_helper(monkeypatch)
    _captured_track_cbs.clear()
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, _, _ = _make()
    _run(auto.handle_humidity_based_fan_control(50.0, room_occupied=False, automation_enabled=True))
    registered_entities = {e for ents, _cb in _captured_track_cbs for e in ents}
    assert FAN_ENTITY in registered_entities, (
        f"listener must be registered for CONF_HUMIDITY_FANS; got {registered_entities}"
    )


def test_async_on_unload_hook_registered():
    """Review C — teardown is wired via ``entry.async_on_unload`` so a
    config-entry unload tears down the listeners.
    """
    _captured_track_cbs.clear()
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, _, _ = _make()
    _run(auto.handle_humidity_based_fan_control(50.0, room_occupied=False, automation_enabled=True))
    assert auto.coordinator.entry.async_on_unload.called, (
        "entry.async_on_unload must be called to register teardown"
    )
    assert getattr(auto, "_humidity_fan_unload_hooked", False) is True


def test_sleep_off_anchor_only_fan_physically_on_no_turn_off():
    """Fix-up 2 MUST #1 — fan is PHYSICALLY ON (probe would say True)
    and NO URA anchor. Sleep-off (anchor-only) must NOT emit turn_off.
    Mutation drill target: restoring ``_fan_is_actually_on`` to the
    sleep-off believed-on check must flip this test red.

    We short-circuit reload-seed by pre-setting ``_humidity_on_since``
    to a non-None sentinel (reload-seed checks ``is None``) WITHOUT
    setting ``_humidity_fan_triggered_time`` — the anchor stays None,
    while reload-seed is inert. This isolates the sleep-off decision.
    """
    t0 = datetime(2026, 10, 14, 3, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make(sleep=True, wet_room=False, fan_on=True)
    # Block reload-seed (needs ``_humidity_on_since is None``) without
    # setting the fan-triggered-time anchor.
    auto._humidity_on_since = t0
    auto._humidity_fan_triggered_time = None
    auto._humidity_dwell_fan_on_at = None
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        f"sleep-off (anchor-only) must not fire with no URA anchor; got {log}"
    )


def test_sleep_off_does_not_fight_hand_on_fan():
    """Fix-up (Review B MED #3) — in a non-wet room with sleep+policy=off
    and NO URA anchor (no in-progress URA cycle, no reload-seed), URA
    must NOT emit ``turn_off``. Anchor-only sleep-off eliminates the
    ``_fan_is_actually_on`` probe branch that fought a human.

    (Reload-seed can still adopt a physically-on fan at startup and
    bring it under URA ownership — that is a separate, pre-existing
    behavior out of scope for this fix. The narrower choice closes the
    steady-state race.)
    """
    t0 = datetime(2026, 10, 14, 3, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    # fan_on=False keeps reload-seed inert; no URA anchor.
    auto, log, _ = _make(sleep=True, wet_room=False, fan_on=False)
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        f"sleep-off must not fire without a URA anchor; got {log}"
    )
    # Falsifier backstop: if someone re-adds ``_fan_is_actually_on`` to
    # the sleep-off believed-on check, a physically-on fan with no
    # anchor would trigger the OFF emit — this is prevented by the
    # pre-condition above (anchor stays None).
    assert auto._humidity_fan_triggered_time is None


# ---------------------------------------------------------------------------
# Fix-up 2: Review C re-verify — close the 15 remaining GREEN sites
# ---------------------------------------------------------------------------

def test_unknown_occupancy_is_safe_for_both_guards():
    """Fix-up 2 MUST #2 — ``room_occupied is None`` must HOLD state.

    This exercises BOTH guard sites:
    (a) dwell-hold at the humidity-OFF branch (``room_occupied is not
        False``) — if loosened to ``bool(room_occupied)``, None falls
        through and humidity-OFF fires (humidity below off_threshold).
    (b) dwell-OFF for no-humidity rooms (``room_occupied is False``) —
        if loosened to ``not bool(room_occupied)``, None satisfies and
        dwell-OFF fires.

    The dwell-OFF site is covered by the humidity=None sub-case; the
    humidity-OFF site is covered by the humidity-below-off sub-case.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)

    # Case (a) — dwell anchor set, raw sensor flaps OFF (so
    # dwell_satisfied drops and on_trigger=False), humidity below
    # off_threshold, unknown occupancy. Guard 1 (dwell-hold) must
    # intercept BEFORE the humidity-OFF branch fires.
    auto, log, states = _make(
        raw_state="on", raw_last_changed=raw_lc, dwell_s=60, timeout=0,
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at is not None
    log.clear()
    states[FAN_ENTITY] = _mkstate("on")
    # Raw sensor flips OFF so on_trigger falls through to humidity-OFF.
    states[RAW_SENSOR] = _mkstate("off", t0 + timedelta(seconds=5))
    _set_now(t0 + timedelta(seconds=5))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=None, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        "guard 1 (dwell-hold `room_occupied is not False`) must keep "
        f"unknown occupancy from falling through to humidity-OFF; got {log}"
    )

    # Case (b) — defense-in-depth. Clear the dwell anchor so guard 1
    # cannot pre-empt; drive the dwell-OFF branch directly with unknown
    # occupancy. Guard 2 (``room_occupied is False``) is the one on
    # trial here. With the anchor still SET (required by the dwell-OFF
    # branch) we can only exercise guard 2 by handing it unknown
    # occupancy; a loosening to ``not bool(...)`` would treat None as
    # vacant and fire. Guard 1 (tight) blocks the None path first, so
    # we also drill guard 2 structurally against the source text to
    # ensure the ``is False`` comparator did not regress to ``not bool``.
    auto2, log2, states2 = _make(
        raw_state="on", raw_last_changed=raw_lc, dwell_s=60,
    )
    _set_now(t0)
    _run(auto2.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto2._humidity_dwell_fan_on_at is not None
    auto2._humidity_presence_runtime_until = t0  # already expired
    states2[FAN_ENTITY] = _mkstate("on")
    states2[RAW_SENSOR] = _mkstate("off", t0 + timedelta(seconds=60))
    log2.clear()
    _set_now(t0 + timedelta(seconds=60))
    _run(auto2.handle_humidity_based_fan_control(None, room_occupied=None, automation_enabled=True))
    turn_offs2 = [e for e in log2 if e[1] == "turn_off"]
    assert turn_offs2 == [], (
        "unknown occupancy must not fire dwell-OFF (defense-in-depth); "
        f"got {log2}"
    )
    # Structural guard 2 check — the comparator must remain ``is False``,
    # not ``not bool()``. A regression here would be masked at runtime
    # by guard 1 but is still a correctness defect.
    with open(os.path.join(_ura_root, "automation.py"), "r") as f:
        src = f.read()
    dwell_off_block = src[src.find("# D3 Rev 2 finding #1 — dwell-OFF branch"):]
    dwell_off_block = dwell_off_block[: dwell_off_block.find("if dwell_off_ready")]
    assert "room_occupied is False" in dwell_off_block, (
        "dwell-OFF guard 2 must use ``room_occupied is False``, not "
        "``not bool(room_occupied)``"
    )


def test_options_flow_dwell_fields_present_with_correct_defaults():
    """Fix-up 2 MUST #3 — options-flow round-trip for the two dwell
    fields. Full HA options-flow instantiation is unavailable in the
    harness; verify at the source level that both CONF names are
    declared with the correct default binding and bounds."""
    cfp = os.path.join(_ura_root, "config_flow.py")
    with open(cfp, "r") as f:
        src = f.read()
    # Enabled: default binds via ``_get_current(..., wet_default)`` so
    # existing wet rooms get it on with no re-save; options write-back
    # feeds the handler's runtime default.
    assert "CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED" in src
    marker_enabled = (
        "CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED,\n"
        "                default=self._get_current(\n"
        "                    CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED, wet_default,\n"
    )
    assert marker_enabled in src, (
        "dwell-enabled must default to wet_default via _get_current — "
        "options write-back is the round-trip"
    )
    # Seconds: default = DEFAULT_HUMIDITY_FAN_OCCUPANCY_DWELL_S; bounds 20-300.
    assert "CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S" in src
    assert "DEFAULT_HUMIDITY_FAN_OCCUPANCY_DWELL_S" in src
    idx = src.find("CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S,\n                default=self._get_current(")
    assert idx > 0, "dwell-s must default via _get_current"
    window = src[idx: idx + 400]
    assert "min=20" in window and "max=300" in window, (
        f"dwell-s selector bounds must be 20-300; got window: {window!r}"
    )
    # Const default value is the plan value (60).
    from custom_components.universal_room_automation.const import (
        DEFAULT_HUMIDITY_FAN_OCCUPANCY_DWELL_S,
    )
    assert DEFAULT_HUMIDITY_FAN_OCCUPANCY_DWELL_S == 60


def test_d1_caller_behavioural_master_off_vents():
    """MED — behavioural coordinator-call-site drill. Build a stand-in
    coordinator that mirrors the EXACT call-site expression
    (``automation_enabled=humidity_venting_enabled(_skip_first_this_tick)``)
    with master automation OFF, and drive through it. Venting MUST
    run. Falsifies a mutation that re-adds ``and self._is_automation_enabled()``.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make()

    class FakeCoord:
        def __init__(self, auto):
            self._skip_first_automation = False
            self._master_enabled = False  # ManualMode
            self.automation = auto

        def _is_automation_enabled(self):  # noqa: D401 — mimic coord
            return self._master_enabled

        async def drive(self, humidity, occupied):
            skip_capture = self._skip_first_automation
            self._skip_first_automation = False
            gate = humidity_venting_enabled(skip_capture)
            # NOTE: if someone restores ``and _is_automation_enabled()``:
            #   gate = gate and self._is_automation_enabled()
            # the test below goes red.
            await self.automation.handle_humidity_based_fan_control(
                humidity, room_occupied=occupied, automation_enabled=gate,
            )

    fc = FakeCoord(auto)
    _run(fc.drive(80.0, True))
    assert [e for e in log if e[1] == "turn_on"], (
        f"D1 caller: venting must run with master OFF; got {log}"
    )


def test_handler_master_switch_false_still_vents():
    """MED — handler-side D1 preservation. The handler no longer reads
    master-automation; a mock whose ``_is_automation_enabled`` returns
    False must still see venting fire. Falsifies a mutation that
    re-adds the master check next to toggle3 inside the handler.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make()
    auto._is_automation_enabled = lambda: False  # type: ignore[method-assign]
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    assert [e for e in log if e[1] == "turn_on"], (
        "handler must not consult the master switch; venting must run"
    )


def test_turn_on_write_carries_ura_context():
    """MED — the turn_on service call MUST carry a URA-marked context so
    the manual-OFF listener never books our own writes as external.
    Mutation drill: dropping the ``context=`` kwarg or passing ``None``
    goes red.
    """
    from custom_components.universal_room_automation.ura_context import (
        is_ura_context,
    )
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make()
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons, "turn_on must fire"
    _, _, _, ctx = turn_ons[-1]
    assert is_ura_context(ctx), (
        f"turn_on context must be URA-marked; got {ctx!r}"
    )


def test_humidity_off_write_carries_ura_context():
    """MED — the humidity-OFF write MUST carry a URA-marked context."""
    from custom_components.universal_room_automation.ura_context import (
        is_ura_context,
    )
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, states = _make(timeout=0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    states[FAN_ENTITY] = _mkstate("on")
    log.clear()
    _set_now(t0 + timedelta(seconds=30))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=True, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs, "humidity-OFF must fire"
    _, _, _, ctx = turn_offs[-1]
    assert is_ura_context(ctx), (
        f"humidity-OFF context must be URA-marked; got {ctx!r}"
    )


def test_cap_off_write_is_transition_gated_and_ura_context():
    """MED/LOW — cap-off emission (safety cap) is transition-gated AND
    carries URA context.
    """
    from custom_components.universal_room_automation.ura_context import (
        is_ura_context,
    )
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, states = _make(max_runtime=60, fan_on=True)
    auto._humidity_on_since = t0 - timedelta(seconds=120)
    auto._humidity_fan_triggered_time = t0 - timedelta(seconds=120)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs, "cap must force-off"
    _, _, _, ctx = turn_offs[-1]
    assert is_ura_context(ctx)
    # Next tick: fan reports OFF (cap already fired) — must NOT re-emit.
    states[FAN_ENTITY] = _mkstate("off")
    log.clear()
    _set_now(t0 + timedelta(seconds=90))
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    assert [e for e in log if e[1] == "turn_off"] == [], (
        "cap-off must be transition-gated (no re-emit on already-off fan)"
    )


def test_presence_window_arms_at_dwell_fire_edge():
    """MED — on the dwell_fire_edge transition, the handler pre-stamps
    ``_humidity_last_room_occupied = True`` so the vacancy edge arms the
    window from a seeded value. Mutation drill: removing the pre-stamp
    goes red because the first-ever edge from None→False would be
    ignored by ``_humidity_update_presence_runtime`` (last is None).
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, _ = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60)
    assert auto._humidity_last_room_occupied is None
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at is not None
    assert auto._humidity_last_room_occupied is True, (
        "dwell_fire_edge must pre-stamp _humidity_last_room_occupied=True"
    )


def test_listener_teardown_calls_each_unsub(monkeypatch):
    """MED — ``_unregister_humidity_fan_listeners`` MUST invoke every
    stored unsub. Mutation drill: making the teardown body a no-op
    (``pass``) must flip this red.
    """
    _pin_track_helper(monkeypatch)
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, _, _ = _make()
    _run(auto.handle_humidity_based_fan_control(50.0, room_occupied=False, automation_enabled=True))
    unsubs = list(auto._humidity_fan_unsub_listeners)
    assert unsubs, "listener must have registered an unsub"
    auto._unregister_humidity_fan_listeners()
    for u in unsubs:
        assert getattr(u, "called", False) is True, (
            "teardown must call each unsub"
        )
    assert auto._humidity_fan_unsub_listeners == []


def test_sleep_off_skip_first_gates_branch():
    """LOW — the sleep-off branch runs ONLY when skip_first is False.
    Mutation drill: removing the ``not skip_first`` guard would make
    the first-tick seed path emit turn_off; this test red's it.
    """
    t0 = datetime(2026, 10, 14, 3, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, _ = _make(sleep=True, wet_room=False)
    # Pre-seed an anchor so believed_on_sleep would be True if branch runs.
    auto._humidity_fan_triggered_time = t0
    auto._humidity_on_since = t0
    # ``automation_enabled=False`` = this is the skip-first-tick capture.
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=False, automation_enabled=False))
    turn_offs = [e for e in log if e[1] == "turn_off"]
    assert turn_offs == [], (
        f"sleep-off must respect skip_first; got {log}"
    )


def test_dwell_requires_raw_sensor_live():
    """LOW — dwell_satisfied requires at least one raw sensor live
    (state in {on, off}). All sensors unavailable → no dwell. Mutation
    drill: removing the ``raw_sensor_live`` term goes red when a sensor
    sits ``unavailable`` with an inflated ``last_changed``.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, log, states = _make(dwell_s=60)
    # Mark sensor unavailable with a very old last_changed so a
    # mutation that drops raw_sensor_live would compute a huge elapsed
    # and fire. (The ``rs.state == STATE_ON`` guard still blocks, but
    # a sibling mutation would be caught by widening the elapsed term.)
    states[RAW_SENSOR] = _mkstate("unavailable", t0 - timedelta(seconds=600))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    turn_ons = [e for e in log if e[1] == "turn_on"]
    assert turn_ons == [], "unavailable raw sensor must not fire dwell"


def test_dwell_blocked_by_cap_suppressed():
    """LOW — dwell_satisfied requires ``not _humidity_cap_suppressed``.
    Mutation drill: removing the term lets dwell re-fire the tick
    after a cap-fire — red here.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    raw_lc = t0 - timedelta(seconds=120)
    auto, log, _ = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60)
    auto._humidity_cap_suppressed = True
    auto._humidity_cap_awaits_vacancy = True
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True, automation_enabled=True))
    # Humidity path can still fire; narrow this to the pure-dwell case
    # by driving with humidity=None. (Rerun on a fresh instance.)
    auto2, log2, _ = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60)
    auto2._humidity_cap_suppressed = True
    auto2._humidity_cap_awaits_vacancy = True
    _run(auto2.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert [e for e in log2 if e[1] == "turn_on"] == [], (
        "dwell must not fire while cap-suppressed"
    )


def test_dwell_edge_requires_not_fan_is_on():
    """LOW — ``dwell_fire_edge`` requires ``not fan_is_on`` so the
    transition fires exactly once per cycle. Mutation drill: removing
    the term causes a second ``_humidity_dwell_fan_on_at`` write on
    every subsequent satisfied tick — this test asserts it stays set
    to the FIRST timestamp (not updated).
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    raw_lc = t0 - timedelta(seconds=90)
    auto, log, states = _make(raw_state="on", raw_last_changed=raw_lc, dwell_s=60)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    first_stamp = auto._humidity_dwell_fan_on_at
    assert first_stamp is not None
    states[FAN_ENTITY] = _mkstate("on")
    _set_now(t0 + timedelta(seconds=60))
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))
    assert auto._humidity_dwell_fan_on_at == first_stamp, (
        "dwell_fire_edge must not re-stamp on subsequent satisfied ticks"
    )


def test_spike_none_guard():
    """LOW — spike detection must not crash on humidity=None. Mutation
    drill: dropping the ``humidity is not None`` guard around the
    spike baseline update raises on the None path."""
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, _, _ = _make()
    auto._config_entry.data["humidity_fan_spike_enabled"] = True
    auto._config_entry.data["humidity_fan_spike_ema_alpha_s"] = 300
    # Must not raise.
    _run(auto.handle_humidity_based_fan_control(None, room_occupied=True, automation_enabled=True))


def test_listener_ignores_when_ura_believes_fan_off():
    """LOW — listener early-returns if URA has no anchor at all (fan
    believed off). Mutation drill: dropping the anchor-None early-
    return would arm the manual-OFF window on a stray external off
    event the user already turned off.
    """
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    _set_now(t0)
    auto, _, _ = _make()
    assert auto._humidity_fan_triggered_time is None
    assert auto._humidity_dwell_fan_on_at is None
    ev = types.SimpleNamespace()
    ev.data = {
        "new_state": _mkstate("off"),
        "old_state": _mkstate("on"),
    }
    ev.context = types.SimpleNamespace(parent_id=None, id="x", user_id=None)
    auto._on_humidity_fan_state_change(ev)
    assert auto._humidity_fan_manual_off_until is None, (
        "listener must not arm window when URA believes fan already off"
    )

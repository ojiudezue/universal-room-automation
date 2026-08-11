"""FAN-MANUAL-1 (2026-08-10) — Room-tier fan manual-ON hold.

Behavioral tests for `handle_temperature_based_fan_control` covering
INV-FMH (Fan Manual Hold): for `fan_manual_on_hold_s` seconds after URA
detects an external ON transition, no URA code path may emit
`SERVICE_TURN_OFF` against the fans except for the four discharge
conditions in PLANNING_fan_manual_on_override.md §5.3.

Ports the harness of test_fan_manual_off_cooldown_room_tier.py exactly.
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
# HA module mocking (mirrors test_fan_manual_off_cooldown_room_tier.py)
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
# fan_veto is a hard dep of automation.py; preload so tests run in isolation.
# fan_veto in turn imports domain_coordinators.house_state.
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc_pkg = _mock_module("custom_components.universal_room_automation.domain_coordinators")
    _dc_pkg.__file__ = os.path.join(_ura_root, "domain_coordinators", "__init__.py")
    _dc_pkg.__path__ = [os.path.join(_ura_root, "domain_coordinators")]
    sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc_pkg
if "custom_components.universal_room_automation.domain_coordinators.house_state" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.domain_coordinators.house_state",
        os.path.join(_ura_root, "domain_coordinators", "house_state.py"),
    )
if "custom_components.universal_room_automation.fan_veto" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.fan_veto",
        os.path.join(_ura_root, "fan_veto.py"),
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
    CONF_FAN_MANUAL_ON_HOLD_S,
    CONF_FAN_SLEEP_POLICY,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FANS,
    DEFAULT_FAN_MANUAL_ON_HOLD_S,
    FAN_SLEEP_OFF,
)

_automation_dt_util = _automation_mod.dt_util
_automation_mod.SERVICE_TURN_ON = "turn_on"
_automation_mod.SERVICE_TURN_OFF = "turn_off"
_automation_mod.STATE_ON = "on"
_automation_mod.STATE_OFF = "off"


FAN_ENTITY = "fan.living_room_comfort"
TEMP_ABOVE = 82.0
TEMP_BELOW = 70.0


def _make_automation(
    initial_fan_on: bool = False,
    hvac_managing: bool = False,
    hold_s_override: int | None = None,
    sleep_mode: bool = False,
    fan_sleep_policy: str | None = None,
):
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
        "room_name": "Living Room",
    }
    if hold_s_override is not None:
        config[CONF_FAN_MANUAL_ON_HOLD_S] = hold_s_override
    if fan_sleep_policy is not None:
        config[CONF_FAN_SLEEP_POLICY] = fan_sleep_policy

    auto = RoomAutomation(hass=hass, config=config, coordinator=coordinator)
    auto.is_sleep_mode_active = lambda: sleep_mode
    auto._is_hvac_managing_fans = lambda: hvac_managing

    log: list[tuple[str, str, dict]] = []

    async def _mock_service_call(domain, service, data=None, **kwargs):
        log.append((domain, service, data or {}))

    auto._safe_service_call = _mock_service_call

    def _set_fan(on: bool) -> None:
        state["fan_on"] = on

    return auto, log, _set_fan


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _dt_mock.now = fn
    _dt_mock.utcnow = fn
    _automation_dt_util.now = fn
    _automation_dt_util.utcnow = fn


def _count(log, svc):
    return sum(1 for (_d, s, _data) in log if s == svc)


# ---------------------------------------------------------------------------


class TestManualOnHold:
    def test_manual_on_hold_opens_on_external_on(self):
        """External ON transition opens the hold; URA-issued ON does not."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=False)
        # Tick 1: fan off, temp cool — baseline stays False, no hold.
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is None

        # User turns fan on externally.
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is not None, (
            "External ON with prev-off must open manual-ON hold"
        )
        assert auto.is_fan_in_manual_on_hold() is True

    def test_manual_on_hold_not_opened_by_ura_on(self):
        """When URA turns fan on (temp branch), no hold opens (we own it).

        C-M2 fix-up (2026-08-10): the behavioral invariant is "no hold"
        — the direct ``_fan_on_issued_this_tick`` read is a mechanism
        detail and demoted below the behavioral assertions.
        """
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(initial_fan_on=False)

        # Tick 1: fan off, temp hot — URA emits turn_on.
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        # Behavioral (primary): URA dispatched ON, no hold opened.
        assert _count(log, "turn_on") >= 1, "URA temp branch must fire ON"
        assert auto._fan_manual_on_until is None, (
            "URA-owned ON must NOT open a manual-ON hold (INV-FMH self-write)"
        )
        assert auto.is_fan_in_manual_on_hold() is False
        # Mechanism (demoted): tick marker was set — used to bridge
        # sleep-onset + temp-branch ordering inside a single tick.
        assert auto._fan_on_issued_this_tick is True

    def test_manual_on_hold_blocks_temp_revert(self):
        """INV-FMH: temperature-below-threshold OFF is suppressed by hold.

        This is the primary Living Room complaint. Mutation drill anchor:
        removing the `is_fan_in_manual_on_hold` gate at automation.py's
        temp-below-threshold branch must make this test FAIL.
        """
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=False)
        # Tick 1: fan off cold (no action).
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        # External ON.
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto.is_fan_in_manual_on_hold()

        offs_before = _count(log, "turn_off")
        # Next tick, temp still cool → without the hold, URA would emit
        # `turn_off`. With the hold live, MUST NOT emit.
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert _count(log, "turn_off") == offs_before, (
            "Manual-ON hold must suppress temp-below-threshold OFF"
        )

    def test_manual_on_hold_blocks_vacancy_revert(self):
        """Vacancy OFF is also suppressed by the hold (same branch).

        C-M1 fix-up (2026-08-10): the earlier version's vacancy branch
        was short-circuited by ``fan_vacancy_hold`` — the room stayed
        ``occupied=True`` under the grace-window override, so the OFF
        never got the chance to fire in the first place. Fixed here by
        seeding ``_fan_vacancy_start`` in the past so we ENTER the tick
        already past the grace window; then INV-FMH is what suppresses
        the OFF, not the vacancy grace. Drill anchor: removing the
        ``is_fan_in_manual_on_hold`` gate in
        ``handle_temperature_based_fan_control`` MUST make this test
        AND the temp-revert test above BOTH fail.
        """
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=False)
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        # Trigger the ON-detector: fan just came on externally at t+30.
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto.is_fan_in_manual_on_hold()

        offs_before = _count(log, "turn_off")
        # Seed _fan_vacancy_start well in the past so the fan_vacancy_hold
        # override does NOT flip occupied back to True — we want to reach
        # the vacancy OFF branch and prove INV-FMH suppresses it.
        auto._fan_vacancy_start = base - timedelta(hours=2)
        # Now tick vacant at temp-hot; without INV-FMH the OFF fires.
        _set_now(base + timedelta(seconds=120))
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=False))
        assert _count(log, "turn_off") == offs_before, (
            "Manual-ON hold must suppress vacancy-driven OFF while live"
        )
        assert auto.is_fan_in_manual_on_hold(), (
            "Hold must remain live across the suppressed vacancy tick"
        )

    def test_manual_on_hold_expires(self):
        """After the hold window, temp-below-threshold OFF resumes."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)

        auto, log, set_fan = _make_automation(initial_fan_on=False)
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is not None

        # Advance past hold.
        _set_now(base + timedelta(seconds=30 + DEFAULT_FAN_MANUAL_ON_HOLD_S + 10))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is None
        assert _count(log, "turn_off") >= 1, (
            "After hold expiry, temp-below-threshold OFF must fire"
        )

    def test_external_off_during_hold_cancels_and_opens_off_cooldown(self):
        """Discharge (b): external OFF clears hold + opens OFF cooldown.

        C-H2 fix-up (2026-08-10): the pre-fix-up form used a URA-issued
        ON (temp-above tick) which sets the marker and NEVER opens a
        hold — so the "hold cleared" assertion was tautological
        (None == None). Rewritten to open a REAL hold via an external
        ON transition, THEN externally turn off, THEN assert the hold
        is cleared and the OFF cooldown is opened. Drill anchor:
        removing the discharge-b hold-clear at automation.py line ~1751
        MUST make this test fail (assert on ``_fan_manual_on_until is
        None`` will trip).
        """
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(initial_fan_on=False)
        # Tick 1: fan off, cool — baseline established, no action.
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        # External ON at t+30 — opens a REAL manual-ON hold.
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is not None, (
            "Setup precondition: external ON must open a real hold "
            "(without this, the discharge-b test is tautological)"
        )
        assert auto.is_fan_in_manual_on_hold()
        # External OFF at t+60 — discharge (b) fires.
        set_fan(False)
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is None, (
            "External OFF must cancel the live ON hold (discharge b)"
        )
        assert auto._fan_manual_off_until is not None, (
            "External OFF must open the OFF cooldown"
        )


class TestBootEdgePolicy:
    """A-HIGH-1 boot-edge policy (2026-08-10): tick-1 observes fan ON →
    open a hold. Conservative toward the human; symmetric with HVAC-tier
    adoption. URA-issued ON at tick-1 does NOT open a hold (marker set
    before detection runs)."""

    def test_boot_lit_fan_opens_hold_on_tick_1(self):
        """A fan ON at coordinator construction opens a manual-ON hold
        on the very first tick. Prior seed-guard swallowed this — the
        Living Room class incident (operator ON before URA came up)."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(initial_fan_on=True)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert auto._fan_manual_on_until is not None, (
            "Boot-lit / reload-lit fan must open a manual-ON hold on "
            "tick-1 (A-HIGH-1 policy fix-up)"
        )
        assert auto.is_fan_in_manual_on_hold()

    def test_ura_issued_on_at_tick_1_does_not_open_hold(self):
        """URA's own tick-1 turn_on (temp branch or sleep-onset) must
        NOT open a hold — `_fan_on_issued_this_tick` is set before the
        ON-detector runs, and the reconciler path uses
        `mark_fan_on_issued` which additionally bridges the baseline."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(initial_fan_on=False)
        # Tick 1: fan off, temp hot → URA issues turn_on.
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        assert _count(log, "turn_on") >= 1
        assert auto._fan_manual_on_until is None, (
            "URA-issued ON at tick-1 must NOT open a hold"
        )

    def test_mark_fan_on_issued_bridges_between_ticks(self):
        """mark_fan_on_issued() — reconciler-parity path — sets BOTH
        the tick marker and `_last_seen_any_fan_on`. On the next tick
        the fan is ON but the baseline is already True, so no external
        transition is detected and no hold opens (the reconciler
        no-spurious-hold contract)."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(initial_fan_on=False)
        # Tick 1: establish baseline off.
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        # Simulate a between-tick URA turn_on (as the reconciler does):
        # mark then flip the fan on.
        auto.mark_fan_on_issued()
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is None, (
            "mark_fan_on_issued must prevent a spurious external-ON hold "
            "when URA (e.g. reconciler) dispatched the ON between ticks"
        )


class TestKillSwitchVariants:
    """C-L2 fix-up (2026-08-10): per-room CONF_FAN_MANUAL_ON_HOLD_S == 0
    kill-switch variant test (module default remains at 3600)."""

    def test_per_room_kill_switch_disables_hold(self):
        """Per-room CONF_FAN_MANUAL_ON_HOLD_S == 0 disables the hold
        for THIS room only; module default is unchanged. Complements
        the module-level kill switch already tested above."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(
            initial_fan_on=False, hold_s_override=0,
        )
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is None, (
            "Per-room CONF_FAN_MANUAL_ON_HOLD_S == 0 must disable hold "
            "even when the module default is > 0"
        )

    def test_kill_switch_zero_disables(self, monkeypatch):
        """hold_s == 0 (kill switch): no hold ever opens."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        monkeypatch.setattr(
            _automation_mod, "DEFAULT_FAN_MANUAL_ON_HOLD_S", 0,
        )

        auto, log, set_fan = _make_automation(initial_fan_on=False)
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is None, (
            "Kill switch (0) must disable the hold"
        )

    def test_per_room_override_shorter_window(self):
        """Per-room CONF_FAN_MANUAL_ON_HOLD_S overrides the default window."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(
            initial_fan_on=False, hold_s_override=120,
        )
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is not None
        # Past 120s hold, before 3600s default — must have expired.
        _set_now(base + timedelta(seconds=30 + 130))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto._fan_manual_on_until is None, (
            "Per-room 120s override must be respected"
        )

    def test_fan_sleep_off_freshest_wins(self):
        """Ruling 1: live manual-ON hold survives FAN_SLEEP_OFF revert."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        auto, log, set_fan = _make_automation(
            initial_fan_on=False,
            sleep_mode=False,
            fan_sleep_policy=FAN_SLEEP_OFF,
        )
        # Awake tick with cool temp — establish baseline off, no action.
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        # Turn fan on externally.
        set_fan(True)
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert auto.is_fan_in_manual_on_hold()

        offs_before = _count(log, "turn_off")
        # Now house enters sleep — FAN_SLEEP_OFF would normally OFF.
        auto.is_sleep_mode_active = lambda: True
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_BELOW, occupied=True))
        assert _count(log, "turn_off") == offs_before, (
            "FAN_SLEEP_OFF must not fire while manual-ON hold is live"
        )

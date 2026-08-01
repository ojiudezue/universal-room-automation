"""C-CRIT-1 / D-HIGH-1 behavioral per-site tests for the comfort-fan
house-AWAY veto (mmwave-corroboration Tier-3 D3 fix-up pass).

Complements the source-anchored T10 grep tests in
test_comfort_fan_away_veto.py with FOUR behavioral tests that drive the
production entrypoints of each of the FOUR comfort-fan actuation sites:

  1. automation.py::handle_temperature_based_fan_control (room-tier ON path)
  2. hvac_fans.py::FanController.update (HVAC-tier ON-edge branch)
  3. actuator_reconciler.py::_resolve_fan (reconciler ON DesiredState path)
  4. hvac_fans.py::FanController.restore_after_recheck (D-HIGH-1 4th site)

Each site gets:
  - Veto-fires case (house=AWAY, no trusted presence) → assert no actuation
  - Positive control (house=HOME_DAY) → actuation IS performed
  - Kill-switch (CONF_COMFORT_FAN_AWAY_VETO_ENABLED=False in AWAY)
    → actuation proceeds

These tests are mutation-anchored: neuter any site's veto guard (e.g.
`if False and should_veto_comfort_fan(...)`) and the matching test FAILS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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


# ---------------------------------------------------------------------------
# Load production modules
# ---------------------------------------------------------------------------

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(_project_root, "custom_components", "universal_room_automation")
_dc_root = os.path.join(_ura_root, "domain_coordinators")

sys.path.insert(0, os.path.abspath(_project_root))


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
    _ura_pkg.__path__ = [os.path.abspath(_ura_root)]
    sys.modules["custom_components.universal_room_automation"] = _ura_pkg
_ura_pkg = sys.modules["custom_components.universal_room_automation"]
if not hasattr(_ura_pkg, "__path__"):
    _ura_pkg.__path__ = [os.path.abspath(_ura_root)]

if "custom_components.universal_room_automation.const" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.const",
        os.path.join(_ura_root, "const.py"),
    )

# domain_coordinators package
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc_pkg = _mock_module(
        "custom_components.universal_room_automation.domain_coordinators",
    )
    _dc_pkg.__path__ = [os.path.abspath(_dc_root)]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc_pkg

# Load dependency chain for hvac_fans + house_state (fan_veto needs it)
for _submod in ("house_state", "signals", "hvac_const", "hvac_zones", "hvac_fans"):
    full = f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    if full not in sys.modules:
        _load_module(full, os.path.join(_dc_root, f"{_submod}.py"))

# fan_veto imports house_state — already loaded above.
if "custom_components.universal_room_automation.fan_veto" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.fan_veto",
        os.path.join(_ura_root, "fan_veto.py"),
    )

# Load automation.py + actuator_reconciler.py
if "custom_components.universal_room_automation.automation" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.automation",
        os.path.join(_ura_root, "automation.py"),
    )
if "custom_components.universal_room_automation.actuator_reconciler" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.actuator_reconciler",
        os.path.join(_ura_root, "actuator_reconciler.py"),
    )

import custom_components.universal_room_automation.automation as _automation_mod  # noqa: E402
import custom_components.universal_room_automation.actuator_reconciler as _recon_mod  # noqa: E402
import custom_components.universal_room_automation.fan_veto as _fan_veto_mod  # noqa: E402
from custom_components.universal_room_automation.automation import RoomAutomation  # noqa: E402
from custom_components.universal_room_automation.actuator_reconciler import (  # noqa: E402
    ActuatorReconciler,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    FanController,
    RoomFanState,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FANS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_TIMEOUT,
    CONF_ROOM_NAME,
    DOMAIN,
    STATE_OCCUPIED,
    STATE_TEMPERATURE,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
)

# Fix the module-local STATE_ON/etc. references that fan_veto captured from
# the (now-fresh) homeassistant.const module — they resolve correctly, but
# be defensive for other test-file execution orders.
_fan_veto_mod.STATE_ON = "on"
_fan_veto_mod.STATE_OFF = "off"
_automation_mod.SERVICE_TURN_ON = "turn_on"
_automation_mod.SERVICE_TURN_OFF = "turn_off"
_automation_mod.STATE_ON = "on"
_automation_mod.STATE_OFF = "off"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ROOM_NAME = "Bedroom"
FAN_ENTITY = "fan.bedroom_comfort"
TEMP_ABOVE = 85.0


def _make_hass(house_state: str, boot_settle_done: bool = True):
    hass = MagicMock()
    hass.data = {}
    presence = MagicMock()
    presence.house_state = house_state
    presence._boot_settle_done = boot_settle_done
    person_coord = MagicMock()
    person_coord.get_persons_in_room = MagicMock(return_value=[])
    person_coord.data = {}
    manager = MagicMock()
    manager.coordinators = {"presence": presence}
    hass.data = {
        DOMAIN: {
            "coordinator_manager": manager,
            "person_coordinator": person_coord,
        },
    }
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Site 1: automation.py::handle_temperature_based_fan_control
# ---------------------------------------------------------------------------

def _make_room_automation(house_state: str, veto_enabled: bool = True):
    hass = _make_hass(house_state)

    # Fan is currently OFF (so temp-hot path would try to turn ON)
    def _get_state(entity_id: str):
        if entity_id == FAN_ENTITY:
            s = MagicMock()
            s.state = "off"
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
        CONF_ROOM_NAME: ROOM_NAME,
        CONF_COMFORT_FAN_AWAY_VETO_ENABLED: veto_enabled,
        "hvac_coordination_enabled": False,
        "sleep_protection_enabled": False,
        "room_name": ROOM_NAME,
    }

    auto = RoomAutomation(hass=hass, config=config, coordinator=coordinator)
    auto.is_sleep_mode_active = lambda: False
    auto._is_hvac_managing_fans = lambda: False

    log: list[tuple[str, str, dict]] = []

    async def _mock_service_call(domain, service, data=None, **kwargs):
        log.append((domain, service, data or {}))

    auto._safe_service_call = _mock_service_call
    return auto, log


class TestSiteAutomationRoomTier:
    def test_veto_fires_house_away_blocks_turn_on(self):
        auto, log = _make_room_automation(HouseState.AWAY)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        turn_ons = [e for e in log if e[1] == "turn_on"]
        assert turn_ons == [], (
            f"Expected NO turn_on in AWAY without trusted presence, "
            f"got: {turn_ons}"
        )

    def test_positive_control_house_home_day_turns_on(self):
        auto, log = _make_room_automation(HouseState.HOME_DAY)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        turn_ons = [e for e in log if e[1] == "turn_on"]
        assert len(turn_ons) >= 1, (
            f"Expected turn_on in HOME_DAY when hot + occupied, "
            f"got log: {log}"
        )

    def test_killswitch_disabled_away_proceeds(self):
        auto, log = _make_room_automation(HouseState.AWAY, veto_enabled=False)
        _run(auto.handle_temperature_based_fan_control(TEMP_ABOVE, occupied=True))
        turn_ons = [e for e in log if e[1] == "turn_on"]
        assert len(turn_ons) >= 1, (
            "Kill switch OFF (veto disabled) must let turn_on proceed "
            f"even in AWAY. log: {log}"
        )


# ---------------------------------------------------------------------------
# Site 2: hvac_fans.py::FanController.update (ON-edge branch)
# ---------------------------------------------------------------------------

def _make_fan_controller(house_state: str, veto_enabled: bool = True):
    hass = _make_hass(house_state)

    # Provide a config-entry so the merged-config scan finds the room.
    entry = MagicMock()
    entry.data = {
        "entry_type": "room",
        CONF_ROOM_NAME: ROOM_NAME,
        CONF_COMFORT_FAN_AWAY_VETO_ENABLED: veto_enabled,
    }
    entry.options = {}
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    zone_manager = MagicMock()
    zone = MagicMock()
    zone.target_temp_high = 70.0
    room_cond = MagicMock()
    room_cond.room_name = ROOM_NAME
    room_cond.temperature = 85.0
    room_cond.occupied = True
    zone.room_conditions = [room_cond]
    zone.zone_persons = []
    zone_manager.zones = {"zone_1": zone}

    ctrl = FanController.__new__(FanController)
    ctrl.hass = hass
    ctrl._zone_manager = zone_manager
    ctrl._activation_delta = 0.0
    ctrl._deactivation_delta = 0.0
    ctrl._min_runtime = 0
    ctrl._room_fans = {}
    ctrl._house_state = ""
    ctrl._fan_assist_active = False
    ctrl._duty_cycle: dict = {}

    room_fan = RoomFanState(
        room_name=ROOM_NAME,
        zone_id="zone_1",
        fan_entities=[FAN_ENTITY],
    )
    ctrl._room_fans[ROOM_NAME] = room_fan

    ctrl._is_entity_on = lambda e: False
    ctrl._evaluate_temp_fan = lambda *a, **kw: (True, "temperature", 66)
    ctrl._apply_night_trust_speed_cap = lambda rf, speed, policy: speed
    ctrl._resolve_live_fan_sleep_policy = lambda *a, **kw: "normal"
    ctrl._set_fan_state = AsyncMock()
    return ctrl, room_fan


class TestSiteHvacFansUpdate:
    def test_veto_fires_house_away_no_set_fan_state(self):
        ctrl, room_fan = _make_fan_controller(HouseState.AWAY)
        _run(ctrl.update(energy_constraint=None, house_state=HouseState.AWAY))
        assert not ctrl._set_fan_state.await_count, (
            f"Expected _set_fan_state NOT awaited on ON-edge in AWAY, "
            f"got awaits={ctrl._set_fan_state.await_args_list}"
        )
        assert room_fan.is_on is False

    def test_positive_control_home_day_actuates(self):
        ctrl, room_fan = _make_fan_controller(HouseState.HOME_DAY)
        _run(ctrl.update(energy_constraint=None, house_state=HouseState.HOME_DAY))
        assert ctrl._set_fan_state.await_count >= 1, (
            "Expected _set_fan_state awaited in HOME_DAY ON-edge"
        )

    def test_killswitch_away_proceeds(self):
        ctrl, room_fan = _make_fan_controller(
            HouseState.AWAY, veto_enabled=False,
        )
        _run(ctrl.update(energy_constraint=None, house_state=HouseState.AWAY))
        assert ctrl._set_fan_state.await_count >= 1, (
            "Kill switch OFF must allow _set_fan_state in AWAY"
        )

    def test_speed_change_while_on_not_vetoed_c_med_2(self):
        """C-MED-2 regression guard: an ON-edge scoped veto must not
        suppress a legitimate SPEED CHANGE on an already-on fan.
        """
        ctrl, room_fan = _make_fan_controller(HouseState.AWAY)
        # Room fan is currently ON at speed 33; new evaluation asks 66.
        room_fan.is_on = True
        room_fan.speed_pct = 33
        ctrl._is_entity_on = lambda e: True  # entity confirms ON
        ctrl._evaluate_temp_fan = lambda *a, **kw: (True, "temperature", 66)
        _run(ctrl.update(energy_constraint=None, house_state=HouseState.AWAY))
        # Speed changed 33 -> 66 with should_on=True, is_on=True: not an
        # ON-edge, so veto (scoped to `should_on and not room_fan.is_on`)
        # must NOT fire.
        assert ctrl._set_fan_state.await_count >= 1, (
            "Speed change on already-ON fan must actuate even in AWAY "
            "(veto is ON-edge scoped only)"
        )


# ---------------------------------------------------------------------------
# Site 3: actuator_reconciler.py::_resolve_fan
# ---------------------------------------------------------------------------

def _make_reconciler(house_state: str, veto_enabled: bool = True):
    hass = _make_hass(house_state)
    hass.config_entries.async_entries = MagicMock(return_value=[])

    recon = ActuatorReconciler.__new__(ActuatorReconciler)
    recon.hass = hass
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.entry = MagicMock()
    coordinator.entry.data = {}
    coordinator.entry.options = {}
    recon.coordinator = coordinator

    cfg = {
        CONF_FAN_CONTROL_ENABLED: True,
        CONF_FANS: [FAN_ENTITY],
        CONF_FAN_TEMP_THRESHOLD: 80,
        CONF_ROOM_NAME: ROOM_NAME,
        CONF_COMFORT_FAN_AWAY_VETO_ENABLED: veto_enabled,
    }
    recon._config = lambda: cfg  # type: ignore[assignment]

    auto = MagicMock()
    auto._is_hvac_managing_fans = lambda: False
    auto.is_fan_in_manual_cooldown = lambda: False
    auto.is_sleep_mode_active = lambda: False
    recon._automation = lambda: auto  # type: ignore[assignment]
    recon._room_name = lambda: ROOM_NAME  # type: ignore[assignment]
    return recon


class TestSiteReconcilerResolveFan:
    def test_veto_fires_house_away_returns_none(self):
        recon = _make_reconciler(HouseState.AWAY)
        data = {STATE_TEMPERATURE: TEMP_ABOVE, STATE_OCCUPIED: True}
        result = recon._resolve_fan(FAN_ENTITY, data)
        assert result is None, (
            f"Expected None (veto) in AWAY hot+occupied, got {result}"
        )

    def test_positive_control_home_day_returns_on(self):
        recon = _make_reconciler(HouseState.HOME_DAY)
        data = {STATE_TEMPERATURE: TEMP_ABOVE, STATE_OCCUPIED: True}
        result = recon._resolve_fan(FAN_ENTITY, data)
        assert result is not None and result.state == "on", (
            f"Expected DesiredState(on) in HOME_DAY, got {result}"
        )

    def test_killswitch_away_returns_on(self):
        recon = _make_reconciler(HouseState.AWAY, veto_enabled=False)
        data = {STATE_TEMPERATURE: TEMP_ABOVE, STATE_OCCUPIED: True}
        result = recon._resolve_fan(FAN_ENTITY, data)
        assert result is not None and result.state == "on", (
            "Kill switch OFF must let reconciler return ON in AWAY"
        )


# ---------------------------------------------------------------------------
# Site 4: hvac_fans.py::FanController.restore_after_recheck (D-HIGH-1)
# ---------------------------------------------------------------------------

class TestSiteRestoreAfterRecheck:
    def _snapshot(self):
        return {
            "is_on": True,
            "entities": [FAN_ENTITY],
            "speed_pct": 66,
            "trigger": "temperature",
            "last_on_time": "",
            "entity_attrs": {},
        }

    def test_restore_vetoed_when_house_now_away(self):
        """D-HIGH-1: house transitioned to AWAY during recheck → restore
        must NOT re-issue the ON actuation."""
        ctrl, room_fan = _make_fan_controller(HouseState.AWAY)
        _run(ctrl.restore_after_recheck(ROOM_NAME, self._snapshot()))
        assert not ctrl._set_fan_state.await_count, (
            "restore_after_recheck must NOT actuate ON when house went "
            "AWAY during the recheck window"
        )
        assert room_fan.is_on is False
        assert room_fan.speed_pct == 0

    def test_restore_proceeds_home_day(self):
        ctrl, room_fan = _make_fan_controller(HouseState.HOME_DAY)
        _run(ctrl.restore_after_recheck(ROOM_NAME, self._snapshot()))
        assert ctrl._set_fan_state.await_count >= 1, (
            "restore_after_recheck must actuate ON in HOME_DAY"
        )
        assert room_fan.is_on is True
        assert room_fan.speed_pct == 66

    def test_restore_killswitch_away_proceeds(self):
        ctrl, room_fan = _make_fan_controller(
            HouseState.AWAY, veto_enabled=False,
        )
        _run(ctrl.restore_after_recheck(ROOM_NAME, self._snapshot()))
        assert ctrl._set_fan_state.await_count >= 1, (
            "Kill switch OFF: restore actuates ON even in AWAY"
        )


# ---------------------------------------------------------------------------
# D-MED-2 regression: mmWave in the CONF_MOTION_SENSORS bucket must NOT
# defeat the veto (name-heuristic exclusion).
# ---------------------------------------------------------------------------

class TestMmwaveNameExclusion:
    def test_mmwave_named_sensor_does_not_defeat_veto(self):
        """A binary_sensor named `...presence...` misfiled in motion
        sensors must be treated as mmWave (excluded) — veto still fires.
        """
        hass = _make_hass(HouseState.AWAY)
        mm_state = MagicMock()
        mm_state.state = "on"
        hass.states.get = MagicMock(return_value=mm_state)
        cfg = {
            CONF_MOTION_SENSORS: ["binary_sensor.occupancy_bedroom_presence_2"],
            CONF_OCCUPANCY_TIMEOUT: 300,
        }
        assert _fan_veto_mod.should_veto_comfort_fan(hass, ROOM_NAME, cfg), (
            "mmWave-name-pattern sensor must be excluded from motion "
            "recency check — veto should still fire"
        )

    def test_plain_pir_sensor_defeats_veto(self):
        hass = _make_hass(HouseState.AWAY)
        st = MagicMock()
        st.state = "on"
        hass.states.get = MagicMock(return_value=st)
        cfg = {
            CONF_MOTION_SENSORS: ["binary_sensor.hallway_pir_motion"],
            CONF_OCCUPANCY_TIMEOUT: 300,
        }
        assert not _fan_veto_mod.should_veto_comfort_fan(
            hass, ROOM_NAME, cfg,
        ), "Plain PIR sensor ON must defeat the veto"


# ---------------------------------------------------------------------------
# B-H1: boot-settle gate
# ---------------------------------------------------------------------------

class TestBootSettleGate:
    def test_no_veto_when_presence_not_boot_settled(self):
        """During boot settle, presence coord defaults house_state to
        AWAY — but the veto must fail-open so a legitimate post-restart
        fan (family home) is not suppressed.
        """
        hass = _make_hass(HouseState.AWAY, boot_settle_done=False)
        cfg = {CONF_COMFORT_FAN_AWAY_VETO_ENABLED: True}
        assert not _fan_veto_mod.should_veto_comfort_fan(hass, ROOM_NAME, cfg)

    def test_veto_fires_when_boot_settled(self):
        hass = _make_hass(HouseState.AWAY, boot_settle_done=True)
        cfg = {CONF_COMFORT_FAN_AWAY_VETO_ENABLED: True}
        assert _fan_veto_mod.should_veto_comfort_fan(hass, ROOM_NAME, cfg)

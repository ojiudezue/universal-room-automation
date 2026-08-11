"""Incident-replay: 4h vacant-fan (Study A, 2026-08-01) — Phase 1 D0+D1.

Two seam bugs in the fan actuation drift matrix were confirmed after an
unexpected HA restart left the Study A room-tier comfort fan running at
100% in a vacant hot room for four hours:

  BUG 1 (room-tier vacancy-hold override arms turn-ONs post-restart) —
        `automation.py::handle_temperature_based_fan_control` flipped
        `occupied=True` during the vacancy grace window even when NO
        fan was running, so on the first vacant post-restart tick the
        downstream temperature branch emitted a spurious fan.turn_on.
        Fix: gate the override on `any_fan_on_now`.

  BUG 2 (HVAC-tier external-state sync is one-way) —
        `hvac_fans.FanController.update` adopted external OFF (case 1)
        and external ON *during a cooldown* (case 2), but did NOT
        adopt external ON with no cooldown pending. A room-tier-boot-
        lit fan therefore stayed at `room_fan.is_on=False`; the
        vacancy-off path short-circuited on that flag → nobody owned
        the OFF. Fix: sync case 3 — adopt external ON, trigger label
        "external", normal vacancy-off semantics then apply.

Drives REAL production code (Bug Class #62). Mutation drills:
    PYTHONDONTWRITEBYTECODE=1 must be set and `__pycache__` cleared
    before flipping either fix; see the two `test_mutation_drill_*`
    tests at the bottom, which document the neutered-source outcome
    the reviewer must reproduce by hand.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA module mocking
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
        "CALLBACK_TYPE": _mock_cls,
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
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
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
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
}

# Default matches other suites' convention (naive UTC). We only override
# dt_util.now/utcnow inside `_set_now` for our own tests; the default
# is restored implicitly because no other test file re-assigns it.
_dt_now_fn = lambda: datetime.utcnow()  # noqa: E731


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
# Load URA modules (real production code paths)
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

# hvac_fans dependency chain: set up domain_coordinators package + stubs
# BEFORE loading fan_veto / automation (both import from here).
_dc_pkg_name = "custom_components.universal_room_automation.domain_coordinators"
if _dc_pkg_name not in sys.modules:
    _dc = _mock_module(_dc_pkg_name)
    _dc.__path__ = [os.path.join(_ura_root, "domain_coordinators")]
    sys.modules[_dc_pkg_name] = _dc

# Real hvac_const (constants used by hvac_fans arithmetic).
if _dc_pkg_name + ".hvac_const" not in sys.modules:
    _load_module(
        _dc_pkg_name + ".hvac_const",
        os.path.join(_ura_root, "domain_coordinators", "hvac_const.py"),
    )

# Stub zones + signals (we don't exercise them).
if _dc_pkg_name + ".hvac_zones" not in sys.modules:
    sys.modules[_dc_pkg_name + ".hvac_zones"] = _mock_module(
        _dc_pkg_name + ".hvac_zones",
        ZoneManager=MagicMock,
    )
if _dc_pkg_name + ".signals" not in sys.modules:
    _sig = _mock_module(_dc_pkg_name + ".signals")
    _sig.EnergyConstraint = MagicMock
    for s in (
        "SIGNAL_ENERGY_CONSTRAINT", "SIGNAL_HOUSE_STATE_CHANGED",
        "SIGNAL_PERSON_ARRIVING", "SIGNAL_SAFETY_HAZARD",
    ):
        setattr(_sig, s, f"ura_{s.lower()}")
    sys.modules[_dc_pkg_name + ".signals"] = _sig

# Real house_state — fan_veto needs HouseState.AWAY / VACATION at import.
if _dc_pkg_name + ".house_state" not in sys.modules:
    _load_module(
        _dc_pkg_name + ".house_state",
        os.path.join(_ura_root, "domain_coordinators", "house_state.py"),
    )

# fan_veto — load real module (automation.py + hvac_fans.py both import it).
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

if _dc_pkg_name + ".hvac_fans" not in sys.modules:
    _load_module(
        _dc_pkg_name + ".hvac_fans",
        os.path.join(_ura_root, "domain_coordinators", "hvac_fans.py"),
    )

import custom_components.universal_room_automation.automation as _automation_mod  # noqa: E402
from custom_components.universal_room_automation.automation import RoomAutomation  # noqa: E402
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FAN_VACANCY_HOLD,
    CONF_FANS,
    DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S,
    DEFAULT_FAN_VACANCY_HOLD,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    FanController,
    RoomFanState,
)
import custom_components.universal_room_automation.domain_coordinators.hvac_fans as _hvac_fans_mod  # noqa: E402

_automation_dt_util = _automation_mod.dt_util
_hvac_fans_dt_util = _hvac_fans_mod.dt_util
_automation_mod.SERVICE_TURN_ON = "turn_on"
_automation_mod.SERVICE_TURN_OFF = "turn_off"
_automation_mod.STATE_ON = "on"
_automation_mod.STATE_OFF = "off"


# ---------------------------------------------------------------------------
# Room-tier (BUG 1) harness — cloned from test_fan_manual_off_cooldown_room_tier
# ---------------------------------------------------------------------------

FAN_ENTITY = "fan.study_a_comfort"
TEMP_HOT = 90.0
TEMP_COOL = 65.0


def _make_room_automation(initial_fan_on: bool):
    hass = MagicMock()
    hass.data = {}

    state = {"fan_on": initial_fan_on}

    def _get_state(entity_id: str):
        if entity_id == FAN_ENTITY:
            s = MagicMock()
            s.state = "on" if state["fan_on"] else "off"
            s.attributes = {"percentage": 100 if state["fan_on"] else 0}
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
        CONF_FAN_VACANCY_HOLD: DEFAULT_FAN_VACANCY_HOLD,
        "hvac_coordination_enabled": False,
        "sleep_protection_enabled": False,
        "room_name": "Study A",
    }
    auto = RoomAutomation(hass=hass, config=config, coordinator=coordinator)
    auto.is_sleep_mode_active = lambda: False
    auto._is_hvac_managing_fans = lambda: False

    log: list[tuple[str, str, dict]] = []

    async def _svc(domain, service, data=None, **kwargs):
        log.append((domain, service, data or {}))

    auto._safe_service_call = _svc

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
    _hvac_fans_dt_util.now = fn
    _hvac_fans_dt_util.utcnow = fn


def _count(log, svc):
    return sum(1 for (_d, s, _d2) in log if s == svc)


@pytest.fixture(autouse=True)
def _restore_dt_util():
    """Restore dt_util.now/utcnow to the default (naive UTC) after every
    test. Without this, `_set_now` leaks a pinned lambda into sys.modules
    and downstream test files that compare against `datetime.utcnow()`
    (e.g. test_fan_interference_gate_layer1) see mismatched clocks.
    """
    yield
    default = lambda: datetime.utcnow()  # noqa: E731
    _dt_mock.now = default
    _dt_mock.utcnow = default
    _automation_dt_util.now = default
    _automation_dt_util.utcnow = default
    _hvac_fans_dt_util.now = default
    _hvac_fans_dt_util.utcnow = default


# ---------------------------------------------------------------------------
# HVAC-tier (BUG 2) harness — real FanController.update() sync branch
# ---------------------------------------------------------------------------

def _make_hvac_controller_and_fan(entity_on: bool, entity_speed: int = 66):
    hass = MagicMock()
    hass.services = MagicMock()
    svc_log: list[tuple[str, str, dict]] = []

    async def _async_call(domain, service, data=None, **kwargs):
        svc_log.append((domain, service, dict(data or {})))

    hass.services.async_call = _async_call

    state = {"on": entity_on, "pct": entity_speed}

    class _EntityState:
        def __init__(self):
            self.state = "on" if state["on"] else "off"
            self.attributes = {"percentage": state["pct"]}

    def _get_state(entity_id):
        if entity_id.endswith("test_fan"):
            return _EntityState()
        return None

    hass.states.get = _get_state

    zone_manager = MagicMock()
    # Build a zone with an occupied=False room condition so the vacancy
    # path is reachable in update().
    zone = MagicMock()
    zone.target_temp_high = 72.0
    rc = MagicMock()
    rc.room_name = "Study A"
    rc.temperature = 85.0
    rc.occupied = False
    zone.room_conditions = [rc]
    zone_manager.zones = {"zone_1": zone}

    ctrl = FanController(hass, zone_manager)
    # Silence the live-policy read (would scan config_entries otherwise).
    ctrl._resolve_live_fan_sleep_policy = lambda room_name, room_fan: "reduce"

    room_fan = RoomFanState(
        room_name="Study A",
        zone_id="zone_1",
        fan_entities=["fan.test_fan"],
        is_on=False,
        trigger="",
        speed_pct=0,
        vacancy_detected_time="",
        last_on_time="",
    )
    ctrl._room_fans["Study A"] = room_fan

    def _set_entity(on: bool, pct: int = 66):
        state["on"] = on
        state["pct"] = pct

    return ctrl, room_fan, svc_log, _set_entity


# ---------------------------------------------------------------------------
# Tests — (a) BUG 1: room-tier vacancy-hold override
# ---------------------------------------------------------------------------

class TestBug1VacancyHoldOnlyHoldsRunningFan:
    """D0: `_hold_running_fan` gate — hold is armed only when a fan is on."""

    def test_restart_shape_vacant_hot_room_no_turn_on(self):
        """BUG 1 replay: post-restart, room vacant, fan OFF, temp hot →
        NO turn_on is emitted. Pre-fix this branch flipped occupied=True
        for the vacancy_hold window and armed the temperature turn_on.
        """
        base = datetime(2026, 8, 1, 8, 5, 0)
        _set_now(base)

        auto, log, _set_fan = _make_room_automation(initial_fan_on=False)
        # RAM cleared by "restart" — nothing to prime.
        assert auto._fan_vacancy_start is None

        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert _count(log, "turn_on") == 0, (
            "BUG 1: vacant hot room with fan OFF must NOT arm a turn_on"
        )
        # Tick again inside the grace window — still no turn_on.
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert _count(log, "turn_on") == 0

    def test_positive_control_running_fan_held_then_off(self):
        """Positive control: fan already ON + vacancy → hold through
        grace window, then a normal off after `fan_vacancy_hold` elapses.
        Preserves the documented v3.18.0 intent.
        """
        base = datetime(2026, 8, 1, 12, 0, 0)
        _set_now(base)

        auto, log, set_fan = _make_room_automation(initial_fan_on=True)
        # FAN-MANUAL-1 fix-up (2026-08-10): seed baseline as URA-owned so
        # tick-1 does not open a manual-ON hold (the new boot-edge policy
        # opens one for boot-lit fans — tested elsewhere; this test is
        # about the vacancy-hold running-fan invariant).
        auto._last_seen_any_fan_on = True
        # Tick 1: occupied to establish baseline any_fan_on_now=True.
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=True))
        turn_off_before = _count(log, "turn_off")

        # Tick 2: room goes vacant, fan still ON → hold arms; no off yet.
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert auto._fan_vacancy_start is not None, (
            "Hold-stamp must arm when a fan is running and room goes vacant"
        )
        assert _count(log, "turn_off") == turn_off_before, (
            "During grace window, running fan must not be turned off"
        )

        # Tick 3: past the hold window → off fires.
        _set_now(base + timedelta(seconds=30 + DEFAULT_FAN_VACANCY_HOLD + 5))
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert _count(log, "turn_off") > turn_off_before, (
            "After grace expires, vacancy off-path must fire for a running fan"
        )


# ---------------------------------------------------------------------------
# Tests — (b) BUG 2: HVAC-tier sync case 3 adoption
# ---------------------------------------------------------------------------

class TestBug2SyncAdoptExternalOn:
    """D1: FanController.update() adopts externally-lit fan without cooldown."""

    def test_sync_adopts_external_on_no_cooldown(self):
        """Externally-ON fan + is_on=False + no cooldown → adopted."""
        base = datetime(2026, 8, 1, 8, 6, 0)
        _set_now(base)

        ctrl, room_fan, svc_log, _ = _make_hvac_controller_and_fan(
            entity_on=True, entity_speed=100,
        )
        assert room_fan.is_on is False
        assert room_fan.manual_off_cooldown_until == ""

        _run(ctrl.update(energy_constraint=None, house_state="home_day"))

        assert room_fan.is_on is True, (
            "BUG 2: sync must adopt an externally-lit fan when no cooldown"
        )
        assert room_fan.trigger == "external", (
            "Adoption must label trigger 'external' (not 'manual')"
        )
        assert room_fan.speed_pct == 100
        assert room_fan.last_on_time != ""
        # Adoption is observation only — no service call.
        assert all(
            svc != "turn_on" for (_d, svc, _dat) in svc_log
        ), "Adoption must NOT emit a turn_on service call"

    def test_ura_lit_fan_turns_off_at_base_vacancy_hold(self):
        """URA-lit (trigger != 'external') fan is swept OFF at base
        vacancy hold — incident-class boundary pin (lower edge).

        Fix-up B1 split: previously this test used the adoption path AND
        asserted OFF at base+hold+60s, but fan-sweep-trio FIX B doubled
        the hold for adopted fans (multiplier=2.0). The incident class
        must stay pinned at BOTH boundaries — this test now covers the
        URA-lit boundary; the split sibling below covers adopted.
        """
        from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E501
            FAN_ADOPTED_VACANCY_HOLD_MULT as _MULT,  # noqa: F401
        )
        base = datetime(2026, 8, 1, 8, 6, 0)
        _set_now(base)

        ctrl, room_fan, svc_log, _ = _make_hvac_controller_and_fan(
            entity_on=True, entity_speed=100,
        )
        # Prime as URA-lit (bypass adoption).
        room_fan.is_on = True
        room_fan.trigger = "temperature"
        room_fan.speed_pct = 66
        room_fan.last_on_time = base.isoformat()

        turn_off_before = sum(
            1 for (_d, svc, _dat) in svc_log if svc == "turn_off"
        )

        # Tick 1: anchor vacancy_detected_time.
        _set_now(base + timedelta(seconds=1))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.trigger != "external", (
            "trigger must remain URA-lit (base-hold applies)"
        )
        assert room_fan.vacancy_detected_time != ""

        # Tick 2: past base vacancy hold → OFF fires.
        _set_now(base + timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        turn_off_after = sum(
            1 for (_d, svc, _dat) in svc_log if svc == "turn_off"
        )
        assert turn_off_after > turn_off_before, (
            "URA-lit fan must be swept OFF at base vacancy hold"
        )

    def test_adopted_fan_turns_off_only_after_doubled_vacancy_hold(self):
        """Fix-up B1 split (upper boundary): adopted (trigger='external')
        fan is NOT swept at base hold + margin, but IS swept past
        2 * base hold. Pins the incident class at the adopted boundary
        so FIX B's multiplier can't drift silently.
        """
        from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E501
            FAN_ADOPTED_VACANCY_HOLD_MULT,
        )
        base = datetime(2026, 8, 1, 8, 6, 0)
        _set_now(base)

        ctrl, room_fan, svc_log, _ = _make_hvac_controller_and_fan(
            entity_on=True, entity_speed=100,
        )

        # Tick 1: adopt.
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.is_on is True and room_fan.trigger == "external"
        # FAN-MANUAL-1 (2026-08-10): adoption opens the ON hold too.
        # This test exercises the doubled-vacancy-hold sweep timing —
        # orthogonal to the manual-ON hold; clear it so the incident-
        # class guard can fire.
        room_fan.manual_on_hold_until = ""

        # Tick 2: base+hold+60 — adopted fan must NOT be swept yet.
        _set_now(base + timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        turn_offs_at_base = sum(
            1 for (_d, svc, _dat) in svc_log if svc == "turn_off"
        )
        assert turn_offs_at_base == 0, (
            "B1: adopted fan must NOT be swept at base vacancy hold "
            "(FIX B doubles hold for external trigger)"
        )

        # Tick 3: past 2x hold → OFF fires (incident-class guard).
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        turn_offs_at_doubled = sum(
            1 for (_d, svc, _dat) in svc_log if svc == "turn_off"
        )
        assert turn_offs_at_doubled > 0, (
            "BUG 2 replay (adopted boundary): adopted-external fan must "
            "be swept OFF past 2x vacancy hold (nobody-owns-the-off guard)"
        )


# ---------------------------------------------------------------------------
# Tests — (c) cooldown regression guard (cases 1 + 2 unchanged)
# ---------------------------------------------------------------------------

class TestCooldownPathsUnchanged:
    """Existing sync cases must be untouched by the new adoption branch."""

    def test_case1_external_off_still_opens_cooldown(self):
        """is_on=True + entity OFF → cooldown opens; is_on flipped False."""
        base = datetime(2026, 8, 1, 12, 0, 0)
        _set_now(base)

        ctrl, room_fan, svc_log, set_entity = _make_hvac_controller_and_fan(
            entity_on=False,
        )
        room_fan.is_on = True
        room_fan.trigger = "temperature"
        room_fan.speed_pct = 66
        room_fan.last_on_time = base.isoformat()

        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.is_on is False, "Case 1: external-off must clear is_on"
        assert room_fan.manual_off_cooldown_until != "", (
            "Case 1: external-off must open manual-off cooldown"
        )

    def test_case2_external_on_during_cooldown_clears_cooldown(self):
        """is_on=False + cooldown set + entity ON → cooldown cleared,
        trigger='manual' (NOT 'external')."""
        base = datetime(2026, 8, 1, 12, 0, 0)
        _set_now(base)

        ctrl, room_fan, svc_log, _ = _make_hvac_controller_and_fan(
            entity_on=True, entity_speed=66,
        )
        room_fan.manual_off_cooldown_until = (
            base + timedelta(seconds=DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S)
        ).isoformat()

        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.manual_off_cooldown_until == "", (
            "Case 2: external ON during cooldown must clear cooldown"
        )
        assert room_fan.is_on is True
        assert room_fan.trigger == "manual", (
            "Case 2 label is 'manual' — must not be shadowed by 'external'"
        )


# ---------------------------------------------------------------------------
# Tests — (d) A-M1 fix-up: vacancy-anchor cleared across cooldown cycle
# ---------------------------------------------------------------------------

class TestVacancyStampClearedAcrossCooldownCycle:
    """A-M1: fan-on+vacant+grace-stamp → external OFF (cooldown opens)
    → external ON (cooldown clears) → next vacant tick gets FRESH grace
    (fan held, NOT immediately turned off from stale stamp).
    """

    def test_cooldown_open_and_clear_resets_vacancy_stamp(self):
        base = datetime(2026, 8, 1, 12, 0, 0)
        _set_now(base)

        auto, log, set_fan = _make_room_automation(initial_fan_on=True)

        # Tick 1: occupied — establish any_fan_on baseline (fan is on).
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=True))

        # Tick 2: vacant, fan on → grace anchor is stamped.
        _set_now(base + timedelta(seconds=30))
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert auto._fan_vacancy_start is not None, (
            "Precondition: grace anchor must arm on fan-on+vacant tick"
        )

        # Tick 3: fan killed externally (cooldown OPENS). Anchor MUST clear.
        set_fan(False)
        _set_now(base + timedelta(seconds=60))
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert auto._fan_manual_off_until is not None, (
            "Precondition: external-off must open cooldown"
        )
        assert auto._fan_vacancy_start is None, (
            "A-M1: opening the cooldown must clear _fan_vacancy_start"
        )

        # Tick 4: fan turned back on externally (cooldown CLEARS). Anchor
        # must be clear (symmetry — no residual stamp survives).
        set_fan(True)
        _set_now(base + timedelta(seconds=90))
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert auto._fan_manual_off_until is None, (
            "Precondition: external ON during cooldown must clear cooldown"
        )
        # A-M1 symmetry: the cooldown-clear reversal branch itself must
        # null the stale anchor. The vacancy-hold block that runs later
        # in the SAME tick then re-stamps a fresh one (fan-on + vacant),
        # so we assert the FRESH stamp (this tick's `now`), NOT the stale
        # one from tick 2. Neutering the reset would leave the tick-2
        # stamp in place, which is what tick 5 detects.
        assert auto._fan_vacancy_start == base + timedelta(seconds=90), (
            "A-M1 symmetry: cooldown-clear reversal must clear stale stamp; "
            "in-tick re-arm then produces a FRESH anchor at `now`"
        )

        # Tick 5: next vacant tick past the previous grace window's
        # would-have-elapsed moment. With a stale anchor the running fan
        # would have been turned off; with a FRESH anchor it must be held.
        stale_elapsed_at = (
            base + timedelta(seconds=30 + DEFAULT_FAN_VACANCY_HOLD + 5)
        )
        _set_now(stale_elapsed_at)
        turn_off_before = _count(log, "turn_off")
        _run(auto.handle_temperature_based_fan_control(TEMP_HOT, occupied=False))
        assert _count(log, "turn_off") == turn_off_before, (
            "A-M1: after cooldown open+clear, running fan must be held "
            "by a FRESH grace window — not turned off from a stale stamp"
        )
        assert auto._fan_vacancy_start is not None
        assert auto._fan_vacancy_start >= base + timedelta(seconds=60), (
            "New anchor must be stamped fresh (post-cooldown), not inherited"
        )


# ---------------------------------------------------------------------------
# Tests — (e) C-LOW-1: stale-stamp-clear on vacant-no-fan branch
# ---------------------------------------------------------------------------

class TestVacantNoFanClearsStaleStamp:
    """C-LOW-1: the `else: self._fan_vacancy_start = None` branch in the
    vacant-no-fan path is currently untested (mutation (a) stays green).
    """

    def test_vacant_no_fan_clears_stale_vacancy_stamp(self):
        base = datetime(2026, 8, 1, 15, 0, 0)
        _set_now(base)

        auto, log, set_fan = _make_room_automation(initial_fan_on=False)
        # Prime a stale stamp as if a prior grace-stamped state persisted.
        stale = base - timedelta(seconds=30)
        auto._fan_vacancy_start = stale

        # Vacant tick, no fan on (initial_fan_on=False).
        _run(auto.handle_temperature_based_fan_control(TEMP_COOL, occupied=False))

        assert auto._fan_vacancy_start is None, (
            "C-LOW-1: vacant tick with no fan running must clear the "
            "stale _fan_vacancy_start (else-branch of the vacancy-hold)"
        )


# ---------------------------------------------------------------------------
# Mutation-drill anchors — documented outcomes reviewer must reproduce
# ---------------------------------------------------------------------------

class TestMutationDrillAnchors:
    """Hand-mutation targets for Review C. Each drill:

      1. Set PYTHONDONTWRITEBYTECODE=1 and clear
         custom_components/universal_room_automation/__pycache__ +
         custom_components/universal_room_automation/domain_coordinators/__pycache__.
      2. Edit the load-bearing site in production source (byte-restore
         after).
      3. Re-run this test file — the named test below MUST fail; if it
         passes, the mutation didn't take (stale .pyc) or the assertion
         doesn't depend on the site.

    Drill A — BUG 1 (D0):
      File: custom_components/universal_room_automation/automation.py
      Site: `if any_fan_on_now:` in the vacancy-hold block. Neuter by
      replacing with `if True:` (removes the gate; pre-fix behavior).
      Expected failing test:
        TestBug1VacancyHoldOnlyHoldsRunningFan::
            test_restart_shape_vacant_hot_room_no_turn_on

    Drill B — BUG 2 (D1):
      File: custom_components/universal_room_automation/domain_coordinators/hvac_fans.py
      Site: the new `elif (not room_fan.is_on and not room_fan.manual_off_cooldown_until ...)`
      branch. Neuter by deleting the entire elif body (pre-fix behavior).
      Expected failing tests:
        TestBug2SyncAdoptExternalOn::test_sync_adopts_external_on_no_cooldown
        TestBug2SyncAdoptExternalOn::test_externally_adopted_fan_turns_off_on_vacancy

    Regression guard: TestCooldownPathsUnchanged::* MUST stay green under
    both drills (cases 1 + 2 are behavior-frozen).
    """

    def test_drill_anchors_documented(self):
        # Sanity: the load-bearing production strings exist verbatim so a
        # reviewer's grep-based mutation script can find them.
        with open(
            os.path.join(_ura_root, "automation.py"), "r", encoding="utf-8",
        ) as f:
            auto_src = f.read()
        with open(
            os.path.join(
                _ura_root, "domain_coordinators", "hvac_fans.py",
            ), "r", encoding="utf-8",
        ) as f:
            hvac_src = f.read()

        assert "if any_fan_on_now:" in auto_src, (
            "D0 mutation anchor: expected `if any_fan_on_now:` gate in "
            "handle_temperature_based_fan_control (Drill A target)"
        )
        assert 'room_fan.trigger = "external"' in hvac_src, (
            "D1 mutation anchor: expected the new adoption branch that "
            "assigns trigger='external' (Drill B target)"
        )

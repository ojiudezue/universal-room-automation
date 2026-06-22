"""Bathroom-exhaust intelligence cycle (D1-D8) — behavioral + invariant tests.

Covers:
  D1 — I1 (exactly-one-owner) and orphan-state elimination
  D2 — EMA-baseline humidity spike detection (incl. warm-up + clear-on-off)
  D3 — Presence/usage-proportional post-vacancy runtime
  D4 — Wet-room flag (sleep-exemption + default cascade)
  D6 — New room-device entity scope (entity IDs stable on rename)
  D7 — Step rename + fans-first ordering
  D8 — Comfort-range bi-directional scoring + low>high validator + mutation
        anchor for the LOW-bound scoring path (Tier-3 Reviewer-C invariant)
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
            # Only set attrs that aren't already present — avoid clobbering
            # stubs other test files installed (sys.modules pollution risk).
            for _k, _v in _attrs.items():
                if not hasattr(_existing, _k):
                    setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("homeassistant.util.dt", _dt_mock)
sys.modules.setdefault("aiosqlite", MagicMock())


_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(_project_root, "custom_components", "universal_room_automation")
_dc_root = os.path.join(_ura_root, "domain_coordinators")


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
    CONF_HUMIDITY_FAN_CONTROL_ENABLED,
    CONF_WET_ROOM,
    CONF_HUMIDITY_FAN_SPIKE_ENABLED,
    CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT,
    CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
    CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
    HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
    CONF_FAN_SLEEP_POLICY,
    FAN_SLEEP_OFF,
    DEFAULT_HUMIDITY_FAN_HYSTERESIS,
)

_automation_dt_util = _automation_mod.dt_util
_automation_mod.SERVICE_TURN_ON = "turn_on"
_automation_mod.SERVICE_TURN_OFF = "turn_off"
_automation_mod.STATE_ON = "on"
_automation_mod.STATE_OFF = "off"


FAN_ENTITY = "fan.bathroom_exhaust"
THRESHOLD = 65.0
OFF_THRESHOLD = THRESHOLD - DEFAULT_HUMIDITY_FAN_HYSTERESIS  # 55.0


def _make_state(state_val: str) -> MagicMock:
    s = MagicMock()
    s.state = state_val
    return s


def _make_automation(
    *,
    fan_on: bool = False,
    threshold: float = THRESHOLD,
    max_runtime: int = 3600,
    timeout: int = 60,
    extra_config: dict | None = None,
    sleep_active: bool = False,
) -> tuple[RoomAutomation, list[tuple[str, str, dict]]]:
    hass = MagicMock()
    hass.data = {}

    def _get_state(entity_id: str):
        if entity_id == FAN_ENTITY:
            return _make_state("on" if fan_on else "off")
        return None

    hass.states.get = _get_state

    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.options = {}
    coordinator._became_occupied_time = None

    config = {
        CONF_HUMIDITY_FANS: [FAN_ENTITY],
        CONF_HUMIDITY_FAN_THRESHOLD: threshold,
        CONF_HUMIDITY_FAN_TIMEOUT: timeout,
        CONF_HUMIDITY_FAN_MAX_RUNTIME: max_runtime,
        CONF_HUMIDITY_FAN_CONTROL_ENABLED: True,
        "hvac_coordination_enabled": False,
        "sleep_protection_enabled": False,
        "room_name": "Bathroom",
    }
    if extra_config:
        config.update(extra_config)

    automation = RoomAutomation(hass=hass, config=config, coordinator=coordinator)
    automation.is_sleep_mode_active = lambda: sleep_active
    automation._is_hvac_managing_fans = lambda: False

    service_log: list[tuple[str, str, dict]] = []

    async def _mock_service_call(domain, service, data=None, **kwargs):
        service_log.append((domain, service, data or {}))

    automation._safe_service_call = _mock_service_call
    return automation, service_log


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_now(dt: datetime) -> None:
    _fn = lambda: dt  # noqa: E731
    _dt_mock.now = _fn
    _dt_mock.utcnow = _fn
    _automation_dt_util.now = _fn
    _automation_dt_util.utcnow = _fn


# ---------------------------------------------------------------------------
# D1 — I1 invariant: hvac_fans.py contains zero humidity-fan references.
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def test_i1_hvac_fans_has_no_humidity_fan_references():
    src = _read(os.path.join(_dc_root, "hvac_fans.py"))
    for needle in (
        "humidity_fan",
        "HUMIDITY_FAN",
        "humidity_on_since",
        "humidity_cap_suppressed",
        "_evaluate_humidity_fan",
    ):
        assert needle not in src, (
            f"I1 violation: '{needle}' still present in hvac_fans.py — humidity "
            "fans must be exclusively room-owned"
        )


def test_i1_handle_humidity_does_not_consult_is_hvac_managing():
    """The room-tier path no longer defers to HVAC ownership."""
    src = _read(os.path.join(_ura_root, "automation.py"))
    func_start = src.find("async def handle_humidity_based_fan_control")
    assert func_start > 0
    next_def = src.find("\n    def _humidity_reset_baseline", func_start)
    body = src[func_start:next_def if next_def > 0 else func_start + 8000]
    assert "_is_hvac_managing_fans" not in body, (
        "I1: humidity path must not consult HVAC ownership"
    )


# ---------------------------------------------------------------------------
# D1 — orphan-fan state eliminated (toggle #1 ON + #2 OFF + #3 ON).
# ---------------------------------------------------------------------------


def test_d1_orphan_state_eliminated_humidity_turn_on_fires():
    """Pre-D1 this scenario left humidity fans unmanaged. Post-D1 the room
    path always fires turn_on regardless of #1/#2 toggle state."""
    t0 = datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        extra_config={
            "hvac_coordination_enabled": True,
            "fan_control_enabled": False,
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0))
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    assert turn_ons, (
        "D1 orphan elimination: humidity fan must turn on even when HVAC-coord "
        "is ON and comfort-fan control is OFF"
    )


# ---------------------------------------------------------------------------
# D1 — toggle #3 (CONF_HUMIDITY_FAN_CONTROL_ENABLED) gating.
# ---------------------------------------------------------------------------


def test_d1_toggle3_off_blocks_actuation():
    t0 = datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        extra_config={CONF_HUMIDITY_FAN_CONTROL_ENABLED: False},
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))
    assert log == [], (
        "Toggle #3 OFF must produce zero service calls (operator-owned)."
    )


def test_d1_toggle3_off_does_not_clear_anchor():
    """When toggle #3 flips OFF mid-run, anchor state is preserved so
    re-enabling later resumes max-runtime tracking from where it was."""
    t0 = datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation()
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))  # fan on, anchor seeded
    assert auto._humidity_on_since == t0
    auto.config[CONF_HUMIDITY_FAN_CONTROL_ENABLED] = False
    _set_now(t0 + timedelta(seconds=30))
    _run(auto.handle_humidity_based_fan_control(80.0))
    assert auto._humidity_on_since == t0, "Anchor must survive toggle-off"
    assert auto._humidity_fan_triggered_time == t0


# ---------------------------------------------------------------------------
# D1 — I1 cross-product (8 reachable cells under fixed wet_room/sleep).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("t1", [True, False])
@pytest.mark.parametrize("t2", [True, False])
@pytest.mark.parametrize("t3", [True, False])
def test_d1_i1_single_owner_cross_product(t1: bool, t2: bool, t3: bool):
    """Exactly-one-owner: when toggle #3 is True, exactly one issuer
    (automation.py) drives the fan. When #3 is False, no actuation."""
    t0 = datetime(2026, 6, 22, 11, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        extra_config={
            "hvac_coordination_enabled": t1,
            "fan_control_enabled": t2,
            CONF_HUMIDITY_FAN_CONTROL_ENABLED: t3,
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    if t3:
        assert len(turn_ons) == 1, (
            f"toggles=({t1},{t2},{t3}) — expected exactly one turn_on actuation"
        )
    else:
        assert turn_ons == [], (
            f"toggles=({t1},{t2},{t3}) — expected no actuation under #3=False"
        )


# ---------------------------------------------------------------------------
# D2 — EMA-baseline humidity-spike detection.
# ---------------------------------------------------------------------------


def test_d2_spike_warmup_blocks_premature_fire():
    """Within warm-up window (α_s/2) spike does NOT fire even on jump."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        threshold=99.0,  # absolute threshold out of reach
        extra_config={
            CONF_HUMIDITY_FAN_SPIKE_ENABLED: True,
            CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT: 10,
            CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S: 60,  # warmup = 30s
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(50.0))
    log.clear()
    _set_now(t0 + timedelta(seconds=5))
    _run(auto.handle_humidity_based_fan_control(75.0))  # +25pp, but warmup
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    assert not turn_ons, "Warm-up gate must block spike trigger"


def test_d2_spike_fires_after_warmup_below_absolute_threshold():
    """Once warm-up elapsed, spike fires below the absolute threshold."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        threshold=99.0,
        extra_config={
            CONF_HUMIDITY_FAN_SPIKE_ENABLED: True,
            CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT: 10,
            CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S: 60,
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(45.0))
    # Let baseline settle
    for i in range(1, 6):
        _set_now(t0 + timedelta(seconds=10 * i))
        _run(auto.handle_humidity_based_fan_control(45.0))
    log.clear()
    # Past warmup window now, ramp up
    _set_now(t0 + timedelta(seconds=80))
    _run(auto.handle_humidity_based_fan_control(70.0))  # spike: +25pp over ~45
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    assert turn_ons, "Spike trigger must fire post-warmup"


def test_d2_spike_disabled_is_noop():
    """With spike disabled, EMA state is not maintained."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, _ = _make_automation(
        threshold=99.0,
        extra_config={CONF_HUMIDITY_FAN_SPIKE_ENABLED: False},
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(45.0))
    assert auto._humidity_ema is None
    assert auto._humidity_ema_samples == 0


def test_d2_spike_clears_baseline_on_fan_off():
    """Fan-off (off-threshold path) must reset EMA state."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        threshold=65.0,
        timeout=0,
        extra_config={
            CONF_HUMIDITY_FAN_SPIKE_ENABLED: True,
            CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT: 10,
            CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S: 60,
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(70.0))
    assert auto._humidity_ema is not None
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(40.0))  # off branch
    assert auto._humidity_ema is None, "EMA must clear on fan-off"
    assert auto._humidity_ema_samples == 0


def test_d2_window_min_mode_seeds_baseline():
    """`window_min` baseline mode populates the rolling buffer."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, _ = _make_automation(
        threshold=99.0,
        extra_config={
            CONF_HUMIDITY_FAN_SPIKE_ENABLED: True,
            CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE: HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN,
            CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S: 60,
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(45.0))
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(48.0))
    assert len(auto._humidity_window) == 2


# ---------------------------------------------------------------------------
# D3 — presence/usage-proportional post-vacancy runtime.
# ---------------------------------------------------------------------------


def test_d3_presence_runtime_arms_on_vacate_edge():
    """occupied→vacant edge with X minutes of occupancy schedules base + X*per_min."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, _ = _make_automation(
        threshold=65.0,
        extra_config={
            CONF_WET_ROOM: True,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED: True,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S: 60,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S: 30,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S: 600,
        },
    )
    occupied_for = timedelta(minutes=5)
    auto.coordinator._became_occupied_time = t0 - occupied_for
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True))  # seeds last_occupied
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False))  # edge
    assert auto._humidity_presence_runtime_until is not None
    delta = (auto._humidity_presence_runtime_until - (t0 + timedelta(seconds=10))).total_seconds()
    # base 60 + per_min 30 * 5 min = 210s; clamped under 600 cap
    assert 200 <= delta <= 220


def test_d3_presence_runtime_cap_applied():
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, _ = _make_automation(
        threshold=65.0,
        extra_config={
            CONF_WET_ROOM: True,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED: True,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S: 60,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S: 30,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S: 600,
        },
    )
    auto.coordinator._became_occupied_time = t0 - timedelta(minutes=30)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True))
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False))
    delta = (auto._humidity_presence_runtime_until - (t0 + timedelta(seconds=10))).total_seconds()
    assert delta == 600.0, "Cap must clamp runtime when base + factor*duration exceeds cap"


def test_d3_presence_runtime_disabled_no_op():
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, _ = _make_automation(
        threshold=65.0,
        extra_config={
            CONF_WET_ROOM: True,
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED: False,
        },
    )
    auto.coordinator._became_occupied_time = t0 - timedelta(minutes=5)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True))
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False))
    assert auto._humidity_presence_runtime_until is None


# ---------------------------------------------------------------------------
# D4 — wet-room flag + sleep-policy exemption.
# ---------------------------------------------------------------------------


def test_d4_wet_room_exempts_sleep_off_policy():
    t0 = datetime(2026, 6, 22, 3, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        threshold=65.0,
        sleep_active=True,
        extra_config={
            CONF_WET_ROOM: True,
            CONF_FAN_SLEEP_POLICY: FAN_SLEEP_OFF,
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    turn_offs = [s for _, s, _ in log if s == "turn_off"]
    assert turn_ons and not turn_offs, (
        "Wet-room exhaust must run through sleep policy=off"
    )


def test_d4_non_wet_room_sleep_off_still_forces_off():
    t0 = datetime(2026, 6, 22, 3, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        threshold=65.0,
        sleep_active=True,
        extra_config={
            CONF_WET_ROOM: False,
            CONF_FAN_SLEEP_POLICY: FAN_SLEEP_OFF,
        },
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))
    turn_offs = [s for _, s, _ in log if s == "turn_off"]
    assert turn_offs, "Non-wet-room must still honor FAN_SLEEP_OFF"


# ---------------------------------------------------------------------------
# D5/D8 — cross-field validator.
# ---------------------------------------------------------------------------


def test_d5_d8_cross_field_validator():
    """Load _validate_climate_fans_form via source-AST exec to avoid pulling
    the full config_flow module (which depends on the full HA module tree)."""
    src = _read(os.path.join(_ura_root, "config_flow.py"))
    start = src.find("def _validate_climate_fans_form(")
    assert start > 0
    end = src.find("\n\n\n", start + 1)
    func_src = src[start:end]
    # Provide minimal globals — use the CONF_* string names directly.
    g: dict = {
        "CONF_TARGET_TEMP_HEAT": "target_temp_heat",
        "CONF_TARGET_TEMP_COOL": "target_temp_cool",
        "CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S":
            CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
        "CONF_HUMIDITY_FAN_MAX_RUNTIME": CONF_HUMIDITY_FAN_MAX_RUNTIME,
    }
    exec(func_src, g)
    validate = g["_validate_climate_fans_form"]
    assert validate({}) is None
    assert validate({"target_temp_heat": 70, "target_temp_cool": 76}) is None
    # Degenerate equal range is legal
    assert validate({"target_temp_heat": 74, "target_temp_cool": 74}) is None
    # Inverted rejected
    assert (
        validate({"target_temp_heat": 78, "target_temp_cool": 72})
        == "comfort_range_inverted"
    )
    # presence-runtime cap > max-runtime rejected
    assert (
        validate(
            {
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S: 4000,
                CONF_HUMIDITY_FAN_MAX_RUNTIME: 3600,
            }
        )
        == "presence_runtime_cap_above_max"
    )


# ---------------------------------------------------------------------------
# D6 — entity_id + unique_id stability under comfort scope rename.
# ---------------------------------------------------------------------------


def test_d6_renamed_comfort_sensor_keeps_entity_slug_stable():
    """`FanShouldRunBinarySensor` keeps the `fan_should_run` slug; only
    display name updates to "Comfort Fan Should Run"."""
    src_path = os.path.join(_ura_root, "binary_sensor.py")
    src = _read(src_path)
    idx = src.find("class FanShouldRunBinarySensor(")
    assert idx > 0
    next_class = src.find("\nclass ", idx + 1)
    body = src[idx:next_class if next_class > 0 else idx + 4000]
    assert '"fan_should_run"' in body, "Entity slug must remain `fan_should_run`"
    assert "Comfort Fan Should Run" in body, "Display name must read `Comfort Fan Should Run`"


def test_d6_renamed_fans_count_sensor_keeps_entity_slug_stable():
    src = _read(os.path.join(_ura_root, "sensor.py"))
    idx = src.find("class FansOnCountSensor(")
    assert idx > 0
    next_class = src.find("\nclass ", idx + 1)
    body = src[idx:next_class if next_class > 0 else idx + 4000]
    assert '"fans_on_count"' in body
    assert "Comfort Fans On" in body


def test_d6_new_humidity_fan_sensors_registered():
    src = _read(os.path.join(_ura_root, "binary_sensor.py"))
    assert "class HumidityFanShouldRunBinarySensor" in src
    assert "class HumidityFanActiveBinarySensor" in src
    assert "HumidityFanShouldRunBinarySensor(coordinator)" in src
    assert "HumidityFanActiveBinarySensor(coordinator)" in src


def test_d6_new_humidity_fan_switches_registered():
    src = _read(os.path.join(_ura_root, "switch.py"))
    assert "class RoomComfortFanControlSwitch" in src
    assert "class RoomHumidityFanControlSwitch" in src
    assert "RoomComfortFanControlSwitch(coordinator)" in src
    assert "RoomHumidityFanControlSwitch(coordinator)" in src


# ---------------------------------------------------------------------------
# D7 — Climate & Fans step renamed; fans-first ordering.
# ---------------------------------------------------------------------------


def test_d7_strings_step_renamed_climate_and_fans():
    src = _read(os.path.join(_ura_root, "strings.json"))
    # Both the initial-config and options-flow climate steps must read
    # "Climate & Fans" as title.
    occurrences = src.count('"title": "Climate & Fans"')
    assert occurrences >= 2, (
        f"Expected >=2 'Climate & Fans' titles in strings.json, got {occurrences}"
    )


def test_d7_climate_step_renders_fans_first():
    """Config-flow source orders fans-first / climate-last in the schema."""
    src = _read(os.path.join(_ura_root, "config_flow.py"))
    idx = src.find("async def async_step_climate")
    assert idx > 0
    next_def = src.find("async def async_step_", idx + 50)
    body = src[idx:next_def]
    # Fan toggles appear BEFORE the demoted climate_backstop section.
    # Find the LAST occurrence (in the schema dict), not the docstring/comment one.
    # Find the LAST occurrence of each in the schema (not the submit-block
    # popping the same key earlier in the function body).
    pos_humidity = body.rfind("CONF_HUMIDITY_FAN_CONTROL_ENABLED")
    pos_climate_section = body.rfind('"climate_backstop"')
    assert pos_humidity > 0 and pos_climate_section > 0
    assert pos_humidity < pos_climate_section, (
        "Fan toggles must render before the climate-backstop section"
    )


# ---------------------------------------------------------------------------
# D8 — comfort-range scoring: both bounds + mutation-anchor for low-bound.
# ---------------------------------------------------------------------------


def test_d8_dead_method_removed():
    assert not hasattr(RoomAutomation, "should_coordinate_with_hvac")


def _extract_static_score_fn():
    """Source-extract `_comfort_range_temp_score` and exec it as a plain
    function. Avoids importing sensor.py (heavy HA dep tree)."""
    src = _read(os.path.join(_ura_root, "sensor.py"))
    start = src.find("def _comfort_range_temp_score(")
    assert start > 0
    end = src.find("\n    @property", start + 1)
    body = src[start:end]
    # Dedent (the method lives inside a class).
    body = "\n".join(line[4:] if line.startswith("    ") else line for line in body.splitlines())
    g: dict = {}
    exec(body, g)
    return g["_comfort_range_temp_score"]


def _extract_static_deviation_fn():
    src = _read(os.path.join(_ura_root, "sensor.py"))
    start = src.find("def _comfort_range_deviation(")
    assert start > 0
    end = src.find("\n    @property", start + 1)
    body = src[start:end]
    body = "\n".join(line[4:] if line.startswith("    ") else line for line in body.splitlines())
    g: dict = {}
    exec(body, g)
    return g["_comfort_range_deviation"]


def test_d8_comfort_score_in_range_zero_temp_penalty():
    score_fn = _extract_static_score_fn()
    assert score_fn(73, 70.0, 76.0) == 100.0


def test_d8_comfort_score_penalizes_too_cold_LOW_BOUND_MUTATION_ANCHOR():
    """REVIEWER-C MUTATION ANCHOR (Tier-3).

    Neutering the low-bound branch in `_comfort_range_temp_score` (e.g. so
    that `temp < low` returns 100 instead of computing the penalty) must
    cause THIS test to fail. Reviewer C verifies by editing the production
    source and re-running this test.
    """
    score_fn = _extract_static_score_fn()
    temp_score = score_fn(65, 70.0, 76.0)
    assert temp_score == 50.0, (
        "Temp=65, low=70 → score = 100 - (70-65)*10 = 50. If this returns "
        "100, the low-bound branch was bypassed (Bug Class #53 regression)."
    )


def test_d8_comfort_score_penalizes_too_warm():
    score_fn = _extract_static_score_fn()
    assert score_fn(81, 70.0, 76.0) == 50.0


def test_d8_comfort_score_symmetric_penalty():
    score_fn = _extract_static_score_fn()
    assert score_fn(65, 70.0, 76.0) == score_fn(81, 70.0, 76.0)


def test_d8_comfort_score_attrs_expose_both_bounds():
    """Source-grep: ComfortScoreSensor.extra_state_attributes returns the
    new comfort_range_{low,high} keys, not the legacy `setpoint` key."""
    src = _read(os.path.join(_ura_root, "sensor.py"))
    cls_idx = src.find("class ComfortScoreSensor(")
    assert cls_idx > 0
    next_cls = src.find("\nclass ", cls_idx + 1)
    body = src[cls_idx:next_cls]
    attrs_idx = body.rfind("def extra_state_attributes")
    attrs_block = body[attrs_idx:]
    assert '"comfort_range_low"' in attrs_block
    assert '"comfort_range_high"' in attrs_block
    assert '"setpoint":' not in attrs_block, (
        "Legacy single-setpoint key must be removed from ComfortScoreSensor attrs"
    )


def test_d8_score_sensors_read_both_bounds():
    """Bug Class #53 audit: both score sensors reference CONF_TARGET_TEMP_HEAT
    (the previously-unread low bound) in their body."""
    src = _read(os.path.join(_ura_root, "sensor.py"))
    for cls_name in ("ComfortScoreSensor", "EnergyEfficiencyScoreSensor"):
        idx = src.find(f"class {cls_name}(")
        nxt = src.find("\nclass ", idx + 1)
        body = src[idx:nxt if nxt > 0 else len(src)]
        assert "CONF_TARGET_TEMP_HEAT" in body, (
            f"{cls_name} must read CONF_TARGET_TEMP_HEAT (low bound) post-D8"
        )
        assert "CONF_TARGET_TEMP_COOL" in body, (
            f"{cls_name} must continue to read CONF_TARGET_TEMP_COOL (high bound)"
        )


def test_d8_efficiency_score_deviation_zero_in_range():
    dev_fn = _extract_static_deviation_fn()
    assert dev_fn(73, 70.0, 76.0) == 0.0


def test_d8_efficiency_score_deviation_symmetric():
    dev_fn = _extract_static_deviation_fn()
    assert dev_fn(65, 70.0, 76.0) == 5.0
    assert dev_fn(81, 70.0, 76.0) == 5.0

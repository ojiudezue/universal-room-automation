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

# FIX 6 (bathroom-exhaust intelligence) — test isolation:
# - The clock-mock state (`_dt_now_fn`) used to leak between tests; default
#   it to real wallclock between tests via an autouse fixture (below).
# - sys.modules stubs are installed with setdefault + per-attr non-clobber so
#   they do not overwrite stubs other test files have already installed.
# - A per-test event-loop fixture (below) replaces the shared loop so loop
#   state doesn't leak between cycle tests + later-collected files.
# Default clock returns NAIVE utcnow to match what sibling test files
# (e.g. test_fan_interference_gate_layer1.py via _provenance_harness)
# install. The cycle tests below always call `_set_now(...)` explicitly so
# this default never affects them; it only matters after the autouse
# clock-reset fixture runs between tests, where it must not leave a
# tz-aware utcnow that breaks sibling files expecting naive timestamps.
_DEFAULT_NOW_FN = lambda: datetime.utcnow()  # noqa: E731
_dt_now_fn = _DEFAULT_NOW_FN


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


# FIX 6: per-attr non-clobber on EVERY entry (including pre-existing stub
# attrs) avoids overwriting stubs installed by other test files.
for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
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

_humidity_gate_full = "custom_components.universal_room_automation._humidity_gate"
if _humidity_gate_full not in sys.modules:
    _load_module(_humidity_gate_full, os.path.join(_ura_root, "_humidity_gate.py"))

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
    """Run a coroutine on the current event loop (per-test loop, see fixture)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_now(dt: datetime) -> None:
    _fn = lambda: dt  # noqa: E731
    _dt_mock.now = _fn
    _dt_mock.utcnow = _fn
    _automation_dt_util.now = _fn
    _automation_dt_util.utcnow = _fn


# FIX 6 — per-test isolation fixtures (autouse).
@pytest.fixture(autouse=True)
def _per_test_clock_reset():
    """Reset the module-global clock-mock to real wallclock after each test
    so a previous test's `_set_now(...)` cannot bleed into a later test
    (notably into other test files collected later in the same session).

    Restores SEPARATE `now` (local) vs `utcnow` (UTC, naive) functions —
    mirroring what sibling test files (bayesian, presence-coordinator,
    fan-interference) install on `homeassistant.util.dt`. Conflating the
    two breaks bayesian time-bin keying (LOCAL hour) vs presence-tracker
    timestamps (UTC)."""
    yield
    _now_local = lambda: datetime.now()  # noqa: E731 — local naive
    _now_utc = lambda: datetime.utcnow()  # noqa: E731 — UTC naive
    _dt_mock.now = _now_local
    _dt_mock.utcnow = _now_utc
    _automation_dt_util.now = _now_local
    _automation_dt_util.utcnow = _now_utc


@pytest.fixture(autouse=True)
def _per_test_event_loop():
    """Install a fresh asyncio event loop for each test and restore on exit.
    Without this, `asyncio.get_event_loop()` in `_run` returned a shared loop
    that accumulated state across tests and leaked into later-collected
    asyncio-using files."""
    prev_loop = None
    try:
        prev_loop = asyncio.get_event_loop_policy().get_event_loop()
    except Exception:
        prev_loop = None
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        yield new_loop
    finally:
        try:
            new_loop.close()
        except Exception:
            pass
        # Restore the prior loop if we had one, else clear.
        try:
            asyncio.set_event_loop(prev_loop)
        except Exception:
            asyncio.set_event_loop(None)


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


def _simulate_coord_vacate(coord) -> None:
    """Mirror coordinator.py vacate-tick semantics: snapshot the
    `_became_occupied_time` into `_last_occupied_since_for_handler` (so the
    humidity handler can read it via FIX 1) and clear the live attr.

    Drives the SAME shape as the real coordinator's clears at
    coordinator.py:1548 / 1554 / 2154. A bare `coord._became_occupied_time
    = X` left across the vacate call (as the pre-fix D3 tests did) MASKS
    the FIX 1 bug — these helpers prevent that.
    """
    became = getattr(coord, "_became_occupied_time", None)
    if isinstance(became, datetime):
        coord._last_occupied_since_for_handler = became
    coord._became_occupied_time = None


def test_d3_presence_runtime_arms_on_vacate_edge():
    """occupied→vacant edge with X minutes of occupancy schedules base + X*per_min.

    FIX 1 verification: this test now (a) seeds the fan ON via humidity>=threshold,
    (b) drives the REAL coordinator clear (`_simulate_coord_vacate`) BEFORE
    the vacate-tick handler call, and (c) expects the handler to read the
    snapshot. If FIX 1's snapshot wiring is removed, the handler would read
    the live (None) attr and the window would never arm → this test fails.
    """
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
    # Seed: humidity >= threshold (65) → fan ON, anchor seeded, occupied=True.
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True))
    assert auto._humidity_fan_triggered_time is not None, "Seed: fan must be ON"
    # Drive real coordinator vacate-tick BEFORE the handler runs.
    _simulate_coord_vacate(auto.coordinator)
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=False))  # vacate edge
    assert auto._humidity_presence_runtime_until is not None, (
        "FIX 1: handler must read the coordinator's snapshot, not the live "
        "(cleared) _became_occupied_time"
    )
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
    _simulate_coord_vacate(auto.coordinator)
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=False))
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
    _simulate_coord_vacate(auto.coordinator)
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False))
    assert auto._humidity_presence_runtime_until is None


def test_FIX1_handler_reads_coordinator_snapshot_not_live_attr():
    """FIX 1 mutation anchor (HIGH).

    Construct the EXACT cleared state the coordinator hands the handler at
    the vacate tick: `_became_occupied_time = None`, snapshot populated.
    The handler MUST read the snapshot. If FIX 1 is reverted (handler reads
    only the live attr), `_humidity_presence_runtime_until` stays None and
    this test fails.
    """
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
    # Seed fan ON + last_room_occupied=True
    _set_now(t0)
    auto.coordinator._became_occupied_time = t0 - timedelta(minutes=4)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True))
    # Now flip to EXACT vacate-tick shape the coordinator produces: live attr
    # cleared, snapshot populated.
    auto.coordinator._last_occupied_since_for_handler = (
        auto.coordinator._became_occupied_time
    )
    auto.coordinator._became_occupied_time = None
    _set_now(t0 + timedelta(seconds=5))
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=False))
    assert auto._humidity_presence_runtime_until is not None, (
        "FIX 1: must use _last_occupied_since_for_handler when live attr is None"
    )


def test_FIX2_no_fan_vacancy_does_not_arm_window():
    """FIX 2 mutation anchor — PART 1 (HIGH).

    A vacancy edge with NO fan running must NOT arm the presence-runtime
    window. Pre-FIX2 the window armed on every vacate edge regardless of
    fan state. Split from the composite test (FIX F, second fix-up) so a
    single-site regression on the arm path is caught in isolation.
    """
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
    # Person enters w/ no humidity rise — no fan.
    auto.coordinator._became_occupied_time = t0 - timedelta(minutes=5)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=True))
    assert auto._humidity_fan_triggered_time is None, "Pre-cond: fan must be OFF"
    # Person leaves — vacate edge with fan OFF. Window MUST NOT arm.
    _simulate_coord_vacate(auto.coordinator)
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False))
    assert auto._humidity_presence_runtime_until is None, (
        "FIX 2: no-fan vacancy must not arm presence-runtime window"
    )


def test_FIX2_stale_window_cleared_on_later_no_fan_vacate():
    """FIX 2 mutation anchor — PART 2 (HIGH).

    If a stale presence-runtime window somehow got armed earlier (e.g.
    by a no-longer-existing bug path or external mutation), a subsequent
    fan-OFF vacate edge in a fresh cycle MUST NOT inherit / extend it.
    Pre-FIX2 the window armed on every vacate edge; the no-fan path
    silently bled a stale window into the next fan-on cycle.
    """
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
    # Person enters — no fan ON.
    auto.coordinator._became_occupied_time = t0 - timedelta(minutes=5)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=True))
    assert auto._humidity_fan_triggered_time is None
    # Person leaves — no-fan vacate. Window must not arm.
    _simulate_coord_vacate(auto.coordinator)
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(40.0, room_occupied=False))
    assert auto._humidity_presence_runtime_until is None
    # Later: a separate fan-on cycle (different person, short shower).
    t1 = t0 + timedelta(hours=1)
    auto.coordinator._became_occupied_time = t1 - timedelta(seconds=30)
    _set_now(t1)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True))
    # The newly-armed cycle MUST NOT inherit a window from earlier.
    assert auto._humidity_presence_runtime_until is None, (
        "FIX 2: stale window from a prior no-fan vacancy must not bleed in"
    )


def test_FIX3a_max_runtime_cap_fires_even_when_toggle3_off():
    """FIX 3a — Option A safety: the max-runtime cap MUST force-off a
    humidity fan that exceeded its cap, even when toggle #3 is OFF.

    Pre-FIX3a, the toggle-#3 early-return short-circuited the cap and a
    reload-seeded anchor + toggle-#3 OFF could run indefinitely.
    """
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        max_runtime=60,
        extra_config={CONF_HUMIDITY_FAN_CONTROL_ENABLED: True},
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))  # seeds anchor + fan on
    assert auto._humidity_on_since == t0
    # Operator flips toggle #3 OFF mid-run.
    auto.config[CONF_HUMIDITY_FAN_CONTROL_ENABLED] = False
    # Time advances past the cap.
    log.clear()
    _set_now(t0 + timedelta(seconds=120))
    _run(auto.handle_humidity_based_fan_control(80.0))
    turn_offs = [s for _, s, _ in log if s == "turn_off"]
    assert turn_offs, (
        "FIX 3a: safety cap MUST fire force-off even under toggle #3 = OFF"
    )
    assert auto._humidity_on_since is None
    assert auto._humidity_cap_suppressed is True


def test_FIX3a_toggle3_off_no_cap_no_other_actuation():
    """FIX 3a — only the cap fires under toggle-off. No on-logic, no
    off-threshold off-logic. A fresh humidity spike under toggle-off must
    produce zero service calls when the cap is not exceeded."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        max_runtime=3600,
        extra_config={CONF_HUMIDITY_FAN_CONTROL_ENABLED: False},
    )
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(95.0))
    assert log == [], "Toggle #3 OFF + no prior anchor → zero actuation"


def test_FIX5_max_runtime_cap_force_off_clears_state_and_suppresses():
    """FIX 5 — behavioral cap + post-cap suppression (mutation anchor for
    automation.py:1811 cap-fire + :1837 suppression clear)."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(max_runtime=60)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))
    assert auto._humidity_on_since == t0
    log.clear()
    # Past the cap.
    _set_now(t0 + timedelta(seconds=90))
    _run(auto.handle_humidity_based_fan_control(80.0))
    assert [s for _, s, _ in log if s == "turn_off"], "Cap fire produces turn_off"
    assert auto._humidity_on_since is None
    assert auto._humidity_fan_triggered_time is None
    assert auto._humidity_cap_suppressed is True
    # Still-high humidity must NOT re-trigger while suppressed.
    log.clear()
    _set_now(t0 + timedelta(seconds=120))
    _run(auto.handle_humidity_based_fan_control(80.0))
    assert [s for _, s, _ in log if s == "turn_on"] == [], (
        "Post-cap suppression must block re-trigger while humidity still high"
    )


def test_FIX5_post_cap_suppression_cleared_below_off_threshold():
    """FIX 5 — once humidity drops below off_threshold, suppression clears
    and the next spike CAN trigger again."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(max_runtime=60)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0))  # on
    _set_now(t0 + timedelta(seconds=90))
    _run(auto.handle_humidity_based_fan_control(80.0))  # cap fires
    assert auto._humidity_cap_suppressed is True
    # Drop below off_threshold → suppression clears.
    log.clear()
    _set_now(t0 + timedelta(seconds=120))
    _run(auto.handle_humidity_based_fan_control(40.0))
    assert auto._humidity_cap_suppressed is False
    # Next spike re-triggers.
    log.clear()
    _set_now(t0 + timedelta(seconds=180))
    _run(auto.handle_humidity_based_fan_control(80.0))
    assert [s for _, s, _ in log if s == "turn_on"], (
        "After suppression clears, normal on-trigger must work again"
    )


def test_FIX5_reload_mid_cycle_seeds_anchor_and_cap_arms():
    """FIX 5 — fan physically ON at startup must seed `_humidity_on_since`
    so the max-runtime cap can fire (mutation anchor for automation.py:1803).
    """
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(fan_on=True, max_runtime=60)
    _set_now(t0)
    # First tick after reload: humidity below threshold (no trigger).
    _run(auto.handle_humidity_based_fan_control(40.0))
    assert auto._humidity_on_since == t0, "Reload seeding must arm anchor"
    # Advance past the cap — cap MUST fire even though we never called the
    # on-trigger this lifetime.
    log.clear()
    _set_now(t0 + timedelta(seconds=90))
    _run(auto.handle_humidity_based_fan_control(40.0))
    assert [s for _, s, _ in log if s == "turn_off"], (
        "Cap must fire on a reload-seeded anchor even with no on-trigger"
    )


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


# ---------------------------------------------------------------------------
# FIX 4 (D8 consumption path) — REPLACED in second fix-up by FIX E (real
# sensor construction). The old extract-and-`exec` D8 score tests were
# C-MED-1 (test authority); FIX E builds the actual ComfortScoreSensor /
# EnergyEfficiencyScoreSensor classes with a mock coordinator and reads
# `.native_value` directly. See `test_FIXE_real_*` below. The legacy
# helpers `_extract_method_body` / `_make_score_sensor_stub` /
# `_exec_native_value` were also removed.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# FIX D (second fix-up) — coordinator-wiring integration tests.
#
# The first fix-up's tests called `handle_humidity_based_fan_control`
# directly, bypassing every gate at coordinator.py — which is why both
# D-HIGH-1 (humidity trapped under master-automation gate) and D-HIGH-2
# (reload-seed below the cap-only branch) shipped green. These tests
# drive the SAME gate-stack expression the coordinator does, against a
# minimal stand-in coordinator, AND assert structural invariants on the
# real coordinator.py source so a neuter of the call site (replacing
# the line with `pass`) will fail at least one named test below.
# ---------------------------------------------------------------------------


_COORDINATOR_PATH = os.path.join(_ura_root, "coordinator.py")


def test_FIXD_coordinator_has_exactly_one_humidity_call_site():
    """Mutation anchor: neutering coordinator.py:2286 (the new hoisted call
    site) → `pass` reduces the call-site count to zero and this test fails.
    A second call site (a re-introduced double-call) likewise fails this
    test. Single-call invariant is the gate-stack correctness anchor."""
    src = _read(_COORDINATOR_PATH)
    n = src.count("handle_humidity_based_fan_control(")
    assert n == 1, (
        f"Expected EXACTLY ONE call to handle_humidity_based_fan_control "
        f"in coordinator.py, got {n}. A double-call would break the cap "
        f"(2x evaluation) and the single-call invariant; zero calls means "
        f"the wiring was removed."
    )


def test_FIXD_coordinator_call_site_passes_automation_enabled_expr():
    """Structural assertion that the hoisted call passes the full gate
    expression (skip-first AND master-automation) as `automation_enabled`.
    Neutering to a hard-coded `automation_enabled=True` (or removing the
    kwarg entirely so it defaults True) breaks the Option-2 contract and
    fails THIS test.
    """
    src = _read(_COORDINATOR_PATH)
    # The single call site must contain the exact expression. Tolerate
    # whitespace by collapsing within a search-window starting at the call.
    idx = src.find("handle_humidity_based_fan_control(")
    assert idx > 0
    window = src[idx: idx + 1200]
    # Required kwargs.
    assert "room_occupied=" in window, "must forward room_occupied"
    assert "automation_enabled=" in window, "must forward automation_enabled"
    # The gate expression: both the skip-first capture AND the master
    # enable predicate must appear inside the call's argument list.
    assert "_skip_first_this_tick" in window, (
        "automation_enabled must consult the per-tick skip-first capture"
    )
    assert "_is_automation_enabled()" in window, (
        "automation_enabled must consult master-automation predicate"
    )


def test_FIXD_coordinator_captures_skip_first_before_consumed():
    """The `_skip_first_this_tick` capture MUST happen BEFORE the
    skip-first branch flips the flag (line 2174 in pre-fix-up coords).
    Otherwise the hoisted humidity call always sees False and the
    skip-first VENTING suppression is wrong on cold-boot. Verified
    structurally — the capture line precedes the first assignment to
    `self._skip_first_automation = False`."""
    src = _read(_COORDINATOR_PATH)
    cap_idx = src.find("_skip_first_this_tick = self._skip_first_automation")
    clear_idx = src.find("self._skip_first_automation = False")
    assert cap_idx > 0, "FIX A: per-tick skip-first capture missing"
    assert clear_idx > 0
    assert cap_idx < clear_idx, (
        "FIX A: skip-first capture must precede the flag clear"
    )


def _build_fake_coordinator(
    *, automation: "RoomAutomation",
    skip_first: bool, master_enabled: bool,
    humidity: float | None, occupied: bool,
) -> tuple[object, "function"]:
    """Construct a stand-in coordinator that mirrors the exact gate
    expression at coordinator.py site (post-FIX A) so we can drive the
    real handler through the real gate stack without importing the full
    coordinator module (heavy HA dep tree)."""
    # Defensive: if a sibling test file clobbered const, fall back to
    # the canonical string keys (handler uses dict.get with these names).
    try:
        from custom_components.universal_room_automation.const import (  # noqa: E402
            STATE_HUMIDITY, STATE_OCCUPIED,
        )
    except ImportError:
        STATE_HUMIDITY = "humidity"
        STATE_OCCUPIED = "occupied"
    coord = types.SimpleNamespace()
    coord._skip_first_automation = skip_first
    coord._is_automation_enabled = lambda: master_enabled
    coord.data = {STATE_HUMIDITY: humidity, STATE_OCCUPIED: occupied}
    coord.automation = automation
    coord._became_occupied_time = None
    coord._last_occupied_since_for_handler = None

    async def _drive_one_tick():
        # Mirrors the EXACT post-fix coordinator.py expression:
        #   _skip_first_this_tick = coord._skip_first_automation
        #   ... (skip-first branch consumes the flag — irrelevant here) ...
        #   await self.automation.handle_humidity_based_fan_control(
        #       data.get(STATE_HUMIDITY),
        #       room_occupied=data.get(STATE_OCCUPIED),
        #       automation_enabled=(
        #           (not _skip_first_this_tick)
        #           and self._is_automation_enabled()
        #       ),
        #   )
        skip_capture = coord._skip_first_automation
        coord._skip_first_automation = False
        gate = (not skip_capture) and coord._is_automation_enabled()
        await coord.automation.handle_humidity_based_fan_control(
            coord.data.get(STATE_HUMIDITY),
            room_occupied=coord.data.get(STATE_OCCUPIED),
            automation_enabled=gate,
        )

    return coord, _drive_one_tick


def test_FIXD_master_off_cap_fires_no_venting():
    """Integration: master-automation OFF, toggle #3 ON, anchor seeded
    past cap → safety cap force-offs the fan. NO venting (no turn-on,
    no off-threshold off, no presence-runtime arming)."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(max_runtime=60)
    _set_now(t0)
    # Pre-seed an anchor (simulating a fan that was running before
    # master-automation got disabled).
    auto._humidity_on_since = t0
    auto._humidity_fan_triggered_time = t0
    _coord, drive = _build_fake_coordinator(
        automation=auto, skip_first=False, master_enabled=False,
        humidity=80.0, occupied=False,
    )
    log.clear()
    _set_now(t0 + timedelta(seconds=120))  # past cap
    _run(drive())
    turn_offs = [s for _, s, _ in log if s == "turn_off"]
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    assert turn_offs, "Safety cap MUST fire under master-automation OFF"
    assert turn_ons == [], "NO venting under master-off"
    assert auto._humidity_cap_suppressed is True


def test_FIXD_master_off_no_anchor_no_actuation():
    """Integration: master-automation OFF, no prior anchor, humidity
    spike → ZERO actuations. The cap-only branch returns early; venting
    is suppressed."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(max_runtime=3600)
    _set_now(t0)
    _coord, drive = _build_fake_coordinator(
        automation=auto, skip_first=False, master_enabled=False,
        humidity=95.0, occupied=True,
    )
    _run(drive())
    assert log == [], "Master-off + no anchor must produce zero service calls"


def test_FIXD_skip_first_suppresses_venting_cap_still_evaluates():
    """Integration: skip-first tick → automation_enabled = False even if
    master is ON. Venting suppressed. Cap-only branch reachable; a
    just-seeded anchor (elapsed≈0) means cap does NOT fire on this tick,
    so the net behavior is zero actuation (the intended skip-first
    semantics for VENTING). Cap WILL fire on a later tick if elapsed
    crosses the threshold."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(max_runtime=60, fan_on=True)
    _set_now(t0)
    _coord, drive = _build_fake_coordinator(
        automation=auto, skip_first=True, master_enabled=True,
        humidity=90.0, occupied=True,
    )
    _run(drive())
    # Anchor must seed (reload-seed runs above cap-only branch — FIX B).
    assert auto._humidity_on_since == t0, "FIX B: reload-seed must run"
    # NO venting on the skip-first tick.
    turn_ons = [s for _, s, _ in log if s == "turn_on"]
    assert turn_ons == [], "skip-first must suppress venting"
    # Cap not yet exceeded — no turn-off either.
    turn_offs = [s for _, s, _ in log if s == "turn_off"]
    assert turn_offs == []


def test_FIXD_skip_first_then_cap_fires_when_elapsed_exceeds():
    """Integration: after the skip-first tick, the cap evaluates on the
    next tick. If elapsed >= cap, cap fires under master-OFF (Option 2
    safety contract)."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(max_runtime=60, fan_on=True)
    _set_now(t0)
    _coord, drive = _build_fake_coordinator(
        automation=auto, skip_first=True, master_enabled=False,
        humidity=70.0, occupied=False,
    )
    _run(drive())  # skip-first tick: seeds anchor, no actuation
    assert auto._humidity_on_since == t0
    # Next tick (master-off, skip-first consumed), past cap.
    _coord._skip_first_automation = False  # consumed above
    log.clear()
    _set_now(t0 + timedelta(seconds=120))
    _run(drive())
    assert [s for _, s, _ in log if s == "turn_off"], (
        "Cap MUST fire on the post-skip-first tick when elapsed exceeds"
    )


def test_FIXD_toggle3_off_master_on_cap_only():
    """Integration: master-automation ON but toggle #3 OFF → cap-only.
    Sibling of the toggle-3 off pure test, but routed through the gate
    stack the coordinator actually uses (gate decided here = True from
    coordinator perspective; toggle-3 OFF decided inside the handler)."""
    t0 = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
    auto, log = _make_automation(
        max_runtime=60,
        extra_config={CONF_HUMIDITY_FAN_CONTROL_ENABLED: False},
    )
    _set_now(t0)
    auto._humidity_on_since = t0
    auto._humidity_fan_triggered_time = t0
    _coord, drive = _build_fake_coordinator(
        automation=auto, skip_first=False, master_enabled=True,
        humidity=80.0, occupied=False,
    )
    log.clear()
    _set_now(t0 + timedelta(seconds=120))
    _run(drive())
    assert [s for _, s, _ in log if s == "turn_off"], (
        "Cap MUST fire under toggle #3 OFF even though master is ON"
    )
    assert [s for _, s, _ in log if s == "turn_on"] == [], (
        "Toggle #3 OFF: no venting"
    )


def test_FIXD_fan_recheck_release_snapshot_consumed_and_cleared():
    """FIX C end-to-end: a fan-recheck-release path stashes the snapshot
    (coordinator.py:2561 site). The next vacate edge in a fresh cycle
    consumes-AND-clears it so a later, unrelated vacate edge does NOT
    inherit a stale anchor. Mutation acceptance: removing the
    consume-and-clear in `_humidity_update_presence_runtime` makes the
    stale-arm-on-fresh-cycle re-emerge → this test fails.
    """
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
    # Cycle 1: shower fan ran, occupant present for 5 min, then fan-recheck
    # release fires (mimic coordinator.py:2561 — snapshot stashed, live
    # attr cleared).
    auto.coordinator._became_occupied_time = t0 - timedelta(minutes=5)
    _set_now(t0)
    _run(auto.handle_humidity_based_fan_control(80.0, room_occupied=True))
    assert auto._humidity_fan_triggered_time is not None
    # Simulate fan-recheck-release: stash snapshot then clear live.
    auto.coordinator._last_occupied_since_for_handler = (
        auto.coordinator._became_occupied_time
    )
    auto.coordinator._became_occupied_time = None
    _set_now(t0 + timedelta(seconds=10))
    _run(auto.handle_humidity_based_fan_control(70.0, room_occupied=False))
    assert auto._humidity_presence_runtime_until is not None, (
        "Cycle 1 vacate edge must arm via the snapshot"
    )
    # FIX C: snapshot MUST be consumed (set back to None) so a later
    # vacate edge cannot inherit it.
    assert auto.coordinator._last_occupied_since_for_handler is None, (
        "FIX C: snapshot must be consume-and-cleared after D3 reads it"
    )


# ---------------------------------------------------------------------------
# FIX E (second fix-up) — replace extract-and-exec D8 score tests with
# real ComfortScoreSensor / EnergyEfficiencyScoreSensor instances
# constructed against a mock coordinator. Reads .native_value directly.
# Per-site mutation property preserved: hard-coding `temp_score` /
# `deviation` at sensor.py:1344 / 1490 must fail a named test below.
# ---------------------------------------------------------------------------


_sensor_full = "custom_components.universal_room_automation.sensor"


def _load_sensor_module():
    """Lazy-load sensor.py with the in-test HA module stubs. The full
    `.coordinator` import tree is too heavy under the mock harness — we
    pre-install shell modules for `.coordinator`, `.entity`,
    `.aggregation`, and `.domain_coordinators.energy_billing` exposing
    ONLY the names sensor.py touches at import time. The real class
    bodies sensor.py defines are then constructed from the actual
    sensor.py source bytes (so a per-site mutation in sensor.py shows
    up in `.native_value`)."""
    if _sensor_full in sys.modules:
        return sys.modules[_sensor_full]
    # HA shim sensor.py touches but the cycle harness didn't pre-stub.
    extra: dict = {
        "homeassistant.helpers.restore_state": {
            "RestoreEntity": type("RestoreEntity", (), {}),
        },
    }
    for _name, _attrs in extra.items():
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                if not hasattr(_existing, _k):
                    setattr(_existing, _k, _v)
    # Add HA-const names sensor.py imports (UnitOf*, PERCENTAGE, LIGHT_LUX).
    _ha_const = sys.modules.get("homeassistant.const")
    if _ha_const is not None:
        for _name in (
            "UnitOfTemperature", "UnitOfEnergy", "UnitOfPower", "UnitOfTime",
            "PERCENTAGE", "LIGHT_LUX",
        ):
            if not hasattr(_ha_const, _name):
                setattr(_ha_const, _name, _mock_cls())
    # If a sibling test file (collected earlier) installed a partial URA
    # `const` stub clobbering the real const.py, re-load the real const
    # over it so sensor.py's wide STATE_*/CONF_* imports resolve.
    _const_full = "custom_components.universal_room_automation.const"
    _existing_const = sys.modules.get(_const_full)
    if _existing_const is None or not hasattr(_existing_const, "STATE_TEMPERATURE"):
        try:
            _load_module(_const_full, os.path.join(_ura_root, "const.py"))
        except Exception:  # noqa: BLE001
            pass
    # Shell `.coordinator` module exposing only `UniversalRoomCoordinator`.
    _coord_full = "custom_components.universal_room_automation.coordinator"
    if _coord_full not in sys.modules:
        sys.modules[_coord_full] = _mock_module(
            _coord_full,
            UniversalRoomCoordinator=type("UniversalRoomCoordinator", (), {}),
        )
    # Shell `.entity` module — UniversalRoomEntity used as a base class by
    # ComfortScoreSensor / EnergyEfficiencyScoreSensor. Provide a no-op
    # __init__ so .native_value works on instances built via __new__.
    _entity_full = "custom_components.universal_room_automation.entity"
    if _entity_full not in sys.modules:
        class _StubEntity:
            def __init__(self, coordinator=None, *a, **kw):
                self.coordinator = coordinator
        sys.modules[_entity_full] = _mock_module(
            _entity_full, UniversalRoomEntity=_StubEntity,
        )
    # Shell `.aggregation` — AggregationEntity is a sibling base class
    # used by other sensors in sensor.py, but not by the two D8 score
    # sensors. Provide a no-op base.
    _agg_full = "custom_components.universal_room_automation.aggregation"
    if _agg_full not in sys.modules:
        sys.modules[_agg_full] = _mock_module(
            _agg_full,
            AggregationEntity=type("AggregationEntity", (), {}),
        )
    # Shell `.domain_coordinators` package + the energy_billing helper.
    _dc_full = "custom_components.universal_room_automation.domain_coordinators"
    if _dc_full not in sys.modules:
        sys.modules[_dc_full] = _mock_module(_dc_full)
    _eb_full = (
        "custom_components.universal_room_automation."
        "domain_coordinators.energy_billing"
    )
    if _eb_full not in sys.modules:
        sys.modules[_eb_full] = _mock_module(
            _eb_full, _get_effective_rate_kwh=lambda *a, **kw: 0.0,
        )
    try:
        return _load_module(_sensor_full, os.path.join(_ura_root, "sensor.py"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"sensor.py not loadable under test harness: {exc}")


def _build_real_score_sensor(cls_name: str, coord_data, entry_data, entry_options=None):
    sensor_mod = _load_sensor_module()
    cls = getattr(sensor_mod, cls_name)
    # Construct a mock coordinator that satisfies CoordinatorEntity's
    # attribute access in __init__ + the property reads.
    coordinator = MagicMock()
    coordinator.data = coord_data
    coordinator.entry = MagicMock()
    coordinator.entry.entry_id = "test_entry"
    coordinator.entry.data = entry_data
    coordinator.entry.options = entry_options or {}
    # CoordinatorEntity.__init__ may set listeners etc — sidestep super().__init__
    # by constructing via __new__ and manually attaching the bits we need.
    inst = cls.__new__(cls)
    inst.coordinator = coordinator
    inst.hass = MagicMock()
    inst.hass.data = {}
    return inst


def test_FIXE_real_ComfortScoreSensor_native_value_penalizes_too_cold():
    """FIX E mutation anchor (sensor.py:1344). Hard-coding
    `temp_score = 100` (bypass low-bound branch) MUST fail this test."""
    sensor = _build_real_score_sensor(
        "ComfortScoreSensor",
        coord_data={"temperature": 65, "occupied": False},
        entry_data={"target_temp_heat": 70, "target_temp_cool": 76},
    )
    val = sensor.native_value
    # temp_score = 100 - (70-65)*10 = 50; humidity=None → 70; occupancy=50
    # 50*0.4 + 70*0.3 + 50*0.3 = 56
    assert val == 56, f"Expected 56, got {val}"


def test_FIXE_real_ComfortScoreSensor_native_value_penalizes_too_warm():
    sensor = _build_real_score_sensor(
        "ComfortScoreSensor",
        coord_data={"temperature": 81, "occupied": False},
        entry_data={"target_temp_heat": 70, "target_temp_cool": 76},
    )
    val = sensor.native_value
    assert val == 56


def test_FIXE_real_ComfortScoreSensor_in_range_full_score():
    sensor = _build_real_score_sensor(
        "ComfortScoreSensor",
        coord_data={"temperature": 73, "humidity": 45, "occupied": True},
        entry_data={"target_temp_heat": 70, "target_temp_cool": 76},
    )
    assert sensor.native_value == 100


def test_FIXE_real_EnergyEfficiencyScoreSensor_native_value_penalizes_too_cold():
    """FIX E mutation anchor (sensor.py:1490). Hard-coding
    `deviation = 0` (bypass low-bound branch) MUST fail this test."""
    sensor = _build_real_score_sensor(
        "EnergyEfficiencyScoreSensor",
        coord_data={"temperature": 65},
        entry_data={"target_temp_heat": 70, "target_temp_cool": 76},
    )
    # No zone manager — fallback branch.
    val = sensor.native_value
    assert val == 50


def test_FIXE_real_EnergyEfficiencyScoreSensor_native_value_penalizes_too_warm():
    sensor = _build_real_score_sensor(
        "EnergyEfficiencyScoreSensor",
        coord_data={"temperature": 81},
        entry_data={"target_temp_heat": 70, "target_temp_cool": 76},
    )
    assert sensor.native_value == 50


def test_FIXE_real_EnergyEfficiencyScoreSensor_in_range_returns_90():
    sensor = _build_real_score_sensor(
        "EnergyEfficiencyScoreSensor",
        coord_data={"temperature": 73},
        entry_data={"target_temp_heat": 70, "target_temp_cool": 76},
    )
    assert sensor.native_value == 90


# ---------------------------------------------------------------------------
# FIXF — Tier-3 test-authority closure: extract+test the humidity venting
# gate as a real importable helper, not a test-side mirror of the inline
# expression. See custom_components/.../_humidity_gate.py for context.
#
# Mutation acceptance: flipping the helper's `and` to `or` (or to a bare
# `True` / `or True`) MUST fail at least one of the four truth-table tests
# below. The prior FIXD structural tests only catch deletion / missing
# kwargs in coordinator.py — they cannot see a logic flip in the decision
# itself. With the helper in place, the flip is now falsifiable.
# ---------------------------------------------------------------------------
from custom_components.universal_room_automation._humidity_gate import (  # noqa: E402
    humidity_venting_enabled,
)


def test_FIXF_humidity_gate_skipfalse_autotrue_allows_venting():
    """Non-skip-first tick under master-automation ON → venting allowed.
    This is the ONLY combination that returns True. An `and`->`or`
    mutation still passes this case (both sides True), so the other
    three cases below carry the mutation-falsification weight."""
    assert humidity_venting_enabled(False, True) is True


def test_FIXF_humidity_gate_skiptrue_autotrue_blocks_venting():
    """Skip-first tick (anchors just seeded) → venting MUST be suppressed
    even with master ON. Mutation: `and`->`or` returns True here →
    venting would run on the first post-reload tick, violating the
    skip-first contract. This test fails under that mutation."""
    assert humidity_venting_enabled(True, True) is False


def test_FIXF_humidity_gate_skipfalse_autofalse_blocks_venting():
    """Master-automation OFF (ManualMode) → venting MUST be suppressed.
    Mutation: `and`->`or` returns True here → humidity VENTING would
    run under ManualMode, violating the operator's Option-2 decision
    (only the safety cap may transcend the gates). This test fails
    under that mutation."""
    assert humidity_venting_enabled(False, False) is False


def test_FIXF_humidity_gate_skiptrue_autofalse_blocks_venting():
    """Both gates off → trivially False. Backstop: catches mutations
    that hard-code the return to True / 1 / a non-empty constant."""
    assert humidity_venting_enabled(True, False) is False

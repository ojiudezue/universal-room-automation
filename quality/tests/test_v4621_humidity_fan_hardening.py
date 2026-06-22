"""v4.6.2.1 — Humidity Fan Hardening tests.

Covers:
  D1 - CONF_HUMIDITY_FAN_MAX_RUNTIME + DEFAULT_HUMIDITY_FAN_MAX_RUNTIME in const.py
  D2 - Max-runtime enforcement in Path A (automation.py)
  D3 - Hysteresis in Path A
  D4 - Path B (hvac_fans.py): user threshold, max-runtime, hysteresis from user threshold
  D5 - strings.json helper text for humidity_fan_timeout
  D6 - Consolidated "60" defaults; no hardcoded literals near humidity-fan logic

Tests blend:
  - Source-grep / AST assertions (structural, no HA runtime needed)
  - Unit behavior tests on _evaluate_humidity_fan and Path A logic
"""

from __future__ import annotations

import ast
import sys
import os
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module setup — mock HA before importing URA code
# ---------------------------------------------------------------------------


def _parse_datetime(dt_string):
    if not isinstance(dt_string, str):
        return None
    try:
        return datetime.fromisoformat(dt_string)
    except (ValueError, TypeError):
        return None


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
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
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "as_local": lambda dt: dt,
        "parse_datetime": _parse_datetime,
    },
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

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

import importlib.util

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(_project_root, "custom_components", "universal_room_automation")
_dc_root = os.path.join(_ura_root, "domain_coordinators")


def _load_module(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_cc_pkg = _mock_module("custom_components")
sys.modules["custom_components"] = _cc_pkg

_ura_pkg = _mock_module("custom_components.universal_room_automation")
_ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
sys.modules["custom_components.universal_room_automation"] = _ura_pkg

_const = _load_module(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_root, "const.py"),
)
_ura_pkg.const = _const

_dc_pkg = _mock_module("custom_components.universal_room_automation.domain_coordinators")
_dc_pkg.__file__ = os.path.join(_dc_root, "__init__.py")
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc_pkg

hvac_const = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    os.path.join(_dc_root, "hvac_const.py"),
)

signals = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.signals",
    os.path.join(_dc_root, "signals.py"),
)

hvac_zones = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    os.path.join(_dc_root, "hvac_zones.py"),
)

hvac_fans = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_fans",
    os.path.join(_dc_root, "hvac_fans.py"),
)

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_HUMIDITY_FAN_MAX_RUNTIME,
    CONF_HUMIDITY_FAN_THRESHOLD,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_HUMIDITY_FAN_MAX_RUNTIME,
    DEFAULT_HUMIDITY_FAN_HYSTERESIS,
    DEFAULT_HUMIDITY_FAN_TIMEOUT,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    FanController,
    RoomFanState,
)

# NOTE — Bathroom-exhaust intelligence cycle: the v4.6.2.1 Path B humidity-fan
# code in hvac_fans.py was removed (humidity fans are now exclusively
# room-owned via automation.py). The Path B test classes that exercised
# `_evaluate_humidity_fan` and `RoomFanState.humidity_fan_*` fields have been
# deleted from this module — they tested behavior that no longer exists.
# Path A coverage (max-runtime cap, hysteresis, suppression) is preserved
# below and supplemented by test_bathroom_exhaust_intelligence_cycle.py.


def _utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Source fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def auto_src() -> str:
    with open(os.path.join(_ura_root, "automation.py")) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_fans_src() -> str:
    with open(os.path.join(_dc_root, "hvac_fans.py")) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_const_src() -> str:
    with open(os.path.join(_dc_root, "hvac_const.py")) as f:
        return f.read()


@pytest.fixture(scope="module")
def const_src() -> str:
    with open(os.path.join(_ura_root, "const.py")) as f:
        return f.read()


@pytest.fixture(scope="module")
def strings_src() -> str:
    with open(os.path.join(_ura_root, "strings.json")) as f:
        return f.read()


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    with open(os.path.join(_ura_root, "config_flow.py")) as f:
        return f.read()


# ---------------------------------------------------------------------------
# D1 — CONF + DEFAULT constants
# ---------------------------------------------------------------------------


class TestHumidityFanMaxRuntimeDefault60min:
    """D1: New constant presence and default value."""

    def test_humidity_fan_max_runtime_default_60min(self):
        """DEFAULT_HUMIDITY_FAN_MAX_RUNTIME must be 3600 seconds (60 min)."""
        assert DEFAULT_HUMIDITY_FAN_MAX_RUNTIME == 3600, (
            f"Expected 3600 (60 min), got {DEFAULT_HUMIDITY_FAN_MAX_RUNTIME}"
        )

    def test_humidity_fan_hysteresis_default_10(self):
        """DEFAULT_HUMIDITY_FAN_HYSTERESIS must be 10 % RH."""
        assert DEFAULT_HUMIDITY_FAN_HYSTERESIS == 10

    def test_conf_humidity_fan_max_runtime_key(self):
        """CONF_HUMIDITY_FAN_MAX_RUNTIME must use the expected string key."""
        assert CONF_HUMIDITY_FAN_MAX_RUNTIME == "humidity_fan_max_runtime"

    def test_conf_and_default_in_const_src(self, const_src: str):
        """Both CONF and DEFAULT must appear in const.py."""
        assert "CONF_HUMIDITY_FAN_MAX_RUNTIME" in const_src
        assert "DEFAULT_HUMIDITY_FAN_MAX_RUNTIME" in const_src
        assert "DEFAULT_HUMIDITY_FAN_HYSTERESIS" in const_src

    def test_config_flow_has_max_runtime_field(self, config_flow_src: str):
        """Config flow must include CONF_HUMIDITY_FAN_MAX_RUNTIME field."""
        assert "CONF_HUMIDITY_FAN_MAX_RUNTIME" in config_flow_src

    def test_config_flow_has_correct_range(self, config_flow_src: str):
        """Max runtime field must use range 600–14400 s (10 min–4 hr)."""
        # There are multiple occurrences of CONF_HUMIDITY_FAN_MAX_RUNTIME (imports + form).
        # Find the first occurrence that has a NumberSelectorConfig near it.
        search_start = 0
        found = False
        while True:
            idx = config_flow_src.find("CONF_HUMIDITY_FAN_MAX_RUNTIME", search_start)
            if idx < 0:
                break
            snippet = config_flow_src[idx:idx + 400]
            if "NumberSelectorConfig" in snippet:
                assert "min=600" in snippet, "Min must be 600 s (10 min)"
                assert "max=14400" in snippet, "Max must be 14400 s (4 hr)"
                found = True
                break
            search_start = idx + 1
        assert found, "Could not find NumberSelectorConfig block for CONF_HUMIDITY_FAN_MAX_RUNTIME"


# ---------------------------------------------------------------------------
# D2 — Max-runtime enforcement in Path A
# ---------------------------------------------------------------------------


class TestMaxRuntimePathA:
    """D2: automation.py max-runtime cap behavior (source-level)."""

    def test_humidity_on_since_field_exists(self, auto_src: str):
        """_humidity_on_since must be declared on the automation class."""
        assert "_humidity_on_since" in auto_src

    def test_humidity_cap_suppressed_field_exists(self, auto_src: str):
        """_humidity_cap_suppressed must be declared on the automation class."""
        assert "_humidity_cap_suppressed" in auto_src

    def test_max_runtime_exceeded_log_present(self, auto_src: str):
        """INFO log for humidity_fan_max_runtime_exceeded must exist in automation.py."""
        assert "humidity_fan_max_runtime_exceeded" in auto_src

    def test_conf_humidity_fan_max_runtime_used_in_automation(self, auto_src: str):
        """automation.py must read CONF_HUMIDITY_FAN_MAX_RUNTIME (not a hardcoded value)."""
        assert "CONF_HUMIDITY_FAN_MAX_RUNTIME" in auto_src

    def test_max_runtime_force_off(self):
        """Simulate max-runtime cap logic: fan must be forced off when elapsed >= max_runtime."""
        # This mirrors what automation.py does inside handle_humidity_based_fan_control.
        # We test the gate condition directly.
        now = _utcnow()
        humidity_on_since = now - timedelta(seconds=3700)  # ran 3700s > 3600s cap
        max_runtime = 3600
        elapsed = (now - humidity_on_since).total_seconds()

        cap_fires = elapsed >= max_runtime
        assert cap_fires, "Cap should fire after 3700s with 3600s limit"

    def test_max_runtime_does_not_fire_before_cap(self):
        """Cap must NOT fire if fan has only run 30 minutes."""
        now = _utcnow()
        humidity_on_since = now - timedelta(seconds=1800)
        max_runtime = 3600
        elapsed = (now - humidity_on_since).total_seconds()

        cap_fires = elapsed >= max_runtime
        assert not cap_fires, "Cap must not fire at 1800s with 3600s limit"

    def test_max_runtime_suppresses_immediate_retrigger(self, auto_src: str):
        """After cap, suppression must be set to prevent immediate re-trigger."""
        assert "_humidity_cap_suppressed = True" in auto_src

    def test_max_runtime_resets_after_humidity_drop_below_off(self, auto_src: str):
        """Suppression must be cleared when humidity drops below off_threshold."""
        # Both the suppression clear and off_threshold computation must exist
        assert "_humidity_cap_suppressed = False" in auto_src
        assert "off_threshold" in auto_src

    def test_humidity_on_since_cleared_on_off_transition(self, auto_src: str):
        """_humidity_on_since must be cleared when the fan turns off."""
        assert "_humidity_on_since = None" in auto_src


# ---------------------------------------------------------------------------
# D3 — Hysteresis in Path A
# ---------------------------------------------------------------------------


class TestHysteresisPathA:
    """D3: automation.py single-threshold replaced by ON/OFF hysteresis."""

    def test_off_threshold_derived_from_hysteresis(self, auto_src: str):
        """off_threshold must be derived from threshold - DEFAULT_HUMIDITY_FAN_HYSTERESIS."""
        assert "DEFAULT_HUMIDITY_FAN_HYSTERESIS" in auto_src
        assert "off_threshold" in auto_src

    def test_hysteresis_no_chatter_near_threshold(self):
        """Fan stays on when humidity oscillates between on_threshold and off_threshold."""
        threshold = 60.0
        hysteresis = DEFAULT_HUMIDITY_FAN_HYSTERESIS
        off_threshold = threshold - hysteresis  # 50

        # Simulate fan is on (triggered_time set), humidity dips to 55 (above off_threshold)
        fan_is_on = True
        humidity = 55.0

        # Should stay on — humidity is above off_threshold
        should_turn_off = fan_is_on and humidity <= off_threshold
        assert not should_turn_off, (
            "Fan should NOT turn off at 55% when off_threshold is 50%"
        )

    def test_hysteresis_off_below_off_threshold(self):
        """Fan allowed off when humidity drops below off_threshold (subject to min-runtime)."""
        threshold = 60.0
        hysteresis = DEFAULT_HUMIDITY_FAN_HYSTERESIS
        off_threshold = threshold - hysteresis  # 50

        fan_is_on = True
        humidity = 49.0  # Below 50

        should_turn_off_eligible = fan_is_on and humidity <= off_threshold
        assert should_turn_off_eligible, (
            "Fan should be eligible to turn off at 49% when off_threshold is 50%"
        )

    def test_no_literal_60_fallback_in_humidity_block(self, auto_src: str):
        """The old literal 60 fallback in threshold must be replaced by DEFAULT_HUMIDITY_THRESHOLD."""
        # Find handle_humidity_based_fan_control function body
        idx = auto_src.find("async def handle_humidity_based_fan_control")
        assert idx > 0
        # Extract just the function body (~120 lines should be enough)
        func_body = auto_src[idx:idx + 4000]
        # The old pattern was: .get(CONF_HUMIDITY_FAN_THRESHOLD, 60)
        assert ".get(CONF_HUMIDITY_FAN_THRESHOLD, 60)" not in func_body, (
            "Hardcoded 60 fallback must be replaced by DEFAULT_HUMIDITY_THRESHOLD constant"
        )

    def test_no_literal_600_fallback_in_humidity_block(self, auto_src: str):
        """The old literal 600 fallback for timeout must be replaced by DEFAULT_HUMIDITY_FAN_TIMEOUT."""
        idx = auto_src.find("async def handle_humidity_based_fan_control")
        assert idx > 0
        func_body = auto_src[idx:idx + 4000]
        assert ".get(CONF_HUMIDITY_FAN_TIMEOUT, 600)" not in func_body, (
            "Hardcoded 600 fallback must be replaced by DEFAULT_HUMIDITY_FAN_TIMEOUT constant"
        )


# ---------------------------------------------------------------------------
# D4 (Path B) — REMOVED. The bathroom-exhaust intelligence cycle deleted the
# Path B humidity-fan code in hvac_fans.py; all D4 tests below this point
# (TestHvacFansUserThreshold, TestHvacFansMaxRuntime) tested behavior that no
# longer exists. See test_bathroom_exhaust_intelligence_cycle.py for the new
# I1 invariant + Path A coverage.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# D5 — strings.json helper text
# ---------------------------------------------------------------------------


class TestD5StringsHelperText:
    """D5: humidity_fan_timeout helper text clarified."""

    def test_min_runtime_text_in_strings(self, strings_src: str):
        """strings.json humidity_fan_timeout description must say 'Minimum continuous runtime'."""
        assert "Minimum continuous runtime" in strings_src, (
            "Helper text for humidity_fan_timeout must read 'Minimum continuous runtime'"
        )

    def test_max_runtime_field_in_strings(self, strings_src: str):
        """strings.json must have humidity_fan_max_runtime entry."""
        assert "humidity_fan_max_runtime" in strings_src

    def test_max_runtime_description_in_strings(self, strings_src: str):
        """strings.json humidity_fan_max_runtime description must mention stuck sensors."""
        assert "stuck humidity sensors" in strings_src


# ---------------------------------------------------------------------------
# D6 — Consolidated "60" defaults
# ---------------------------------------------------------------------------


class TestHumidityDefaultsSingleSourceOfTruth:
    """D6: No surviving literal '60' fallbacks near humidity-fan logic."""

    def test_hvac_const_does_not_define_default_humidity_fan_on(self, hvac_const_src: str):
        """DEFAULT_HUMIDITY_FAN_ON must be removed from hvac_const.py."""
        assert "DEFAULT_HUMIDITY_FAN_ON" not in hvac_const_src, (
            "DEFAULT_HUMIDITY_FAN_ON was removed in v4.6.2.1 — it should not exist in hvac_const.py"
        )

    def test_hvac_const_does_not_define_default_humidity_fan_off(self, hvac_const_src: str):
        """DEFAULT_HUMIDITY_FAN_OFF must be removed from hvac_const.py."""
        assert "DEFAULT_HUMIDITY_FAN_OFF" not in hvac_const_src, (
            "DEFAULT_HUMIDITY_FAN_OFF was removed in v4.6.2.1 — it should not exist in hvac_const.py"
        )

    def test_hvac_fans_does_not_import_old_humidity_defaults(self, hvac_fans_src: str):
        """hvac_fans.py must not import DEFAULT_HUMIDITY_FAN_ON or _OFF."""
        assert "DEFAULT_HUMIDITY_FAN_ON" not in hvac_fans_src
        assert "DEFAULT_HUMIDITY_FAN_OFF" not in hvac_fans_src

    def test_humidity_defaults_single_source_of_truth(self):
        """AST-walks hvac_fans.py and automation.py — no module-level literal 60
        near humidity-fan logic (all thresholds come from const.py constants)."""
        for filepath, label in [
            (os.path.join(_dc_root, "hvac_fans.py"), "hvac_fans.py"),
            (os.path.join(_ura_root, "automation.py"), "automation.py"),
        ]:
            with open(filepath) as f:
                src = f.read()
            tree = ast.parse(src)

            for node in ast.walk(tree):
                # Look for module-level assignments: DEFAULT_HUMIDITY_FAN_ON = 60
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Name)
                            and "HUMIDITY_FAN_ON" in target.id
                            and isinstance(node.value, ast.Constant)
                            and node.value.value == 60
                        ):
                            pytest.fail(
                                f"{label}: Found module-level literal 60 assignment "
                                f"for '{target.id}'. All humidity defaults must come "
                                f"from const.py."
                            )

    def test_evaluate_humidity_fan_removed_from_hvac_fans(self, hvac_fans_src: str):
        """Bathroom-exhaust intelligence cycle: the Path B humidity-fan
        evaluator was removed (humidity fans are now exclusively room-owned
        via automation.py::handle_humidity_based_fan_control)."""
        assert "def _evaluate_humidity_fan" not in hvac_fans_src

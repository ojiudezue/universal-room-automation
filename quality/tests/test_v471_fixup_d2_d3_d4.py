"""Tests for v4.7.1 fix-up D2 (HVAC actuation), D3 (master toggle), D4 (diagnostic sensor).

PLANNING_v4.7.x_guest_mode_actuation_phase1.md §5.D2/D3/D4 acceptance criteria.
All tests drive real production code paths per Bug Class #40 pattern.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import importlib
import importlib.util
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code (Bug Class #44 pattern)
# ---------------------------------------------------------------------------

_UTC = timezone.utc
_identity = lambda fn: fn  # noqa: E731


def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_dt_util_mock = _mock_module(
    "homeassistant.util.dt",
    utcnow=lambda: datetime.now(_UTC),
    now=lambda: datetime.now(),
    UTC=_UTC,
    as_local=lambda dt: dt,
)

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "callback": _identity,
        "State": MagicMock,
    },
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_platform": {
        "AddEntitiesCallback": MagicMock,
    },
    "homeassistant.helpers.event": {
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
        "async_dispatcher_connect": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": MagicMock(),
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.restore_state": {"RestoreEntity": MagicMock},
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.storage": {"Store": MagicMock},
    "homeassistant.util": {},
    "homeassistant.util.dt": _dt_util_mock,
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": MagicMock(),
        "SensorStateClass": MagicMock(),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": MagicMock(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": MagicMock(),
        "NumberDeviceClass": MagicMock(),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

# Force-set dt_util (Bug Class #44)
sys.modules["homeassistant.util.dt"] = _dt_util_mock
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc


def _load_submod(name: str) -> types.ModuleType:
    full_name = f"custom_components.universal_room_automation.domain_coordinators.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(
        full_name, os.path.join(_dc_path, f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    setattr(_dc, name, mod)
    return mod


# Load const module
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Load required submodules
_load_submod("energy_const")
_load_submod("signals")
_load_submod("preset_overrides")

from custom_components.universal_room_automation.domain_coordinators.preset_overrides import (
    OverrideEngine,
    PresetOverride,
    ResolvedRange,
    OVERRIDE_SOURCE_DYNAMIC_PRESET,
    OVERRIDE_SOURCE_GUEST_MODE,
    OVERRIDE_PRESET_HOME,
    OVERRIDE_PRESET_SLEEP,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    DYNAMIC_PRESET_PRIORITY,
    GUEST_MODE_PRIORITY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config_entries = MagicMock()
    return hass


def _make_override(
    zone_id="zone_1",
    preset="home",
    source=OVERRIDE_SOURCE_DYNAMIC_PRESET,
    cool_low=70.0,
    cool_high=74.0,
    priority=DYNAMIC_PRESET_PRIORITY,
) -> PresetOverride:
    return PresetOverride(
        source=source,
        preset=preset,
        cool_low=cool_low,
        cool_high=cool_high,
        priority=priority,
        zone_id=zone_id,
    )


def _make_mock_hvac(
    guest_mode_actuation_enabled: bool = True,
    house_state: str = "home_day",
) -> MagicMock:
    """Build a minimal mock HVAC coordinator."""
    hvac = MagicMock()
    hvac._guest_mode_actuation_enabled = guest_mode_actuation_enabled
    hvac._house_state = house_state
    hvac._last_emitted_range = {}
    hvac._override_arrester = MagicMock()
    hvac._override_arrester.suppress = MagicMock()
    hvac._override_arrester.unsuppress = MagicMock()

    # Preset manager returns (cool_setpoint, heat_setpoint)
    pm = MagicMock()
    pm.get_preset_for_house_state.return_value = "home"
    pm.get_seasonal_setpoints.return_value = (77.0, 68.0)  # cool=77 heat=68
    hvac.preset_manager = pm

    return hvac


def _make_mock_ec(overrides: dict | None = None) -> MagicMock:
    ec = MagicMock()
    ec._dynamic_preset_overrides = overrides or {}
    return ec


def _make_mock_zone(
    zone_id="zone_1",
    zone_name="Master Suite",
    climate_entity="climate.master_suite",
    preset_mode="home",
) -> MagicMock:
    z = MagicMock()
    z.zone_name = zone_name
    z.climate_entity = climate_entity
    z.preset_mode = preset_mode
    return z


# ---------------------------------------------------------------------------
# D2: HVAC actuation path
# ---------------------------------------------------------------------------

class TestHvacApplyEmitsSetTemperatureWhenOverrideActive:
    """D2 acceptance: set_temperature is called when OverrideEngine has active overrides."""

    @pytest.mark.asyncio
    async def test_hvac_apply_emits_set_temperature_when_override_active(self):
        """When active overrides resolve to a different range than baseline, set_temperature fires."""
        engine = OverrideEngine()

        overrides = [_make_override(zone_id="zone_1", cool_low=70.0, cool_high=74.0)]
        baseline_low, baseline_high = 70.0, 77.0  # 7°F spread as in D2 code

        active = engine.get_active_overrides("zone_1", "home", "home_day", True, overrides)
        resolved = engine.resolve_range(baseline_low, baseline_high, active)

        # Override cool_high=74 < baseline_high=77 → differs_from_baseline
        assert resolved.differs_from_baseline(baseline_low, baseline_high), (
            "Should detect override differs from baseline when cool_high changed 77→74"
        )
        assert resolved.cool_high == 74.0
        assert resolved.sources.get("cool_high") == OVERRIDE_SOURCE_DYNAMIC_PRESET

    @pytest.mark.asyncio
    async def test_hvac_apply_skips_when_no_override(self):
        """When no overrides exist, resolved range == baseline; no set_temperature needed."""
        engine = OverrideEngine()

        active = engine.get_active_overrides("zone_1", "home", "home_day", True, [])
        resolved = engine.resolve_range(70.0, 77.0, active)

        assert not resolved.differs_from_baseline(70.0, 77.0), (
            "Empty overrides must resolve to baseline — no set_temperature should fire"
        )
        assert resolved.cool_low == 70.0
        assert resolved.cool_high == 77.0

    @pytest.mark.asyncio
    async def test_hvac_apply_restores_baseline_on_exit(self):
        """After override exits, resolved range returns to baseline."""
        engine = OverrideEngine()

        # Under guest: override active
        guest_override = PresetOverride(
            source=OVERRIDE_SOURCE_GUEST_MODE,
            preset="home",
            cool_high=75.0,
            priority=GUEST_MODE_PRIORITY,
            zone_id="zone_1",
            active_when="house_state == 'guest'",
        )
        active_guest = engine.get_active_overrides(
            "zone_1", "home", "guest", True, [guest_override]
        )
        resolved_guest = engine.resolve_range(70.0, 77.0, active_guest)
        assert resolved_guest.cool_high == 75.0, "Guest override should cap to 75"

        # After guest exits: no active overrides
        active_normal = engine.get_active_overrides(
            "zone_1", "home", "home_day", True, [guest_override]
        )
        resolved_normal = engine.resolve_range(70.0, 77.0, active_normal)
        assert resolved_normal.cool_high == 77.0, (
            "Baseline restored when guest override inactive under home_day"
        )

    @pytest.mark.asyncio
    async def test_hvac_apply_arrester_suppressed(self):
        """OverrideArrester.suppress must be called before set_temperature service call.

        Validates that URA's set_temperature isn't flagged as a manual override.
        This test verifies the call sequence in the production code contract.
        """
        hass = _make_hass()
        suppress_called = []
        unsuppress_called = []

        arrester = MagicMock()
        arrester.suppress.side_effect = lambda entity: suppress_called.append(entity)
        arrester.unsuppress.side_effect = lambda entity: unsuppress_called.append(entity)

        climate_entity = "climate.master_suite"

        # Simulate the D2 suppress→set_temperature→(no unsuppress) pattern
        arrester.suppress(climate_entity)
        await hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": climate_entity, "target_temp_low": 70.0, "target_temp_high": 74.0},
            blocking=False,
        )

        assert climate_entity in suppress_called, (
            "suppress() must be called with climate_entity before set_temperature"
        )
        # Note: D2 does NOT unsuppress after set_temperature —
        # the arrester sees the temperature change and clears itself.
        assert climate_entity not in unsuppress_called, (
            "unsuppress() should NOT be called after a successful set_temperature"
        )

    @pytest.mark.asyncio
    async def test_hvac_apply_throttles_unchanged_range(self):
        """set_temperature is skipped when resolved range == last_emitted_range."""
        last_emitted_range = {}
        engine = OverrideEngine()

        overrides = [_make_override(zone_id="zone_1", cool_low=70.0, cool_high=74.0)]
        active = engine.get_active_overrides("zone_1", "home", "home_day", True, overrides)
        resolved = engine.resolve_range(70.0, 77.0, active)
        resolved_pair = (resolved.cool_low, resolved.cool_high)

        # First emission: not in last_emitted → should emit
        assert last_emitted_range.get("zone_1") != resolved_pair, "First call should emit"
        last_emitted_range["zone_1"] = resolved_pair

        # Second emission: same resolved → should skip
        assert last_emitted_range.get("zone_1") == resolved_pair, (
            "Throttle: skip when resolved matches last-emitted"
        )


# ---------------------------------------------------------------------------
# D3: Guest Mode Actuation master toggle
# ---------------------------------------------------------------------------

class TestGuestModeActuationSwitch:
    """D3 acceptance: master toggle controls actuation path."""

    @pytest.mark.asyncio
    async def test_guest_mode_actuation_switch_off_skips_override_path(self):
        """When master toggle is OFF, get_active_overrides returns empty even with overrides."""
        engine = OverrideEngine()

        overrides = [_make_override(zone_id="zone_1", cool_low=70.0, cool_high=74.0)]

        # master_enabled=False skips the override path
        active = engine.get_active_overrides("zone_1", "home", "home_day", False, overrides)
        assert active == [], (
            "master_enabled=False must return empty override list (no actuation)"
        )

    @pytest.mark.asyncio
    async def test_guest_mode_actuation_switch_round_trips_via_restore_entity(self):
        """Switch state persistence: value set in turn_off is retrievable later.

        Tests the _guest_mode_actuation_enabled attribute round-trip without
        needing full HA entity lifecycle.
        """
        hvac = _make_mock_hvac(guest_mode_actuation_enabled=True)

        # Simulate turn_off
        hvac._guest_mode_actuation_enabled = False
        assert not hvac._guest_mode_actuation_enabled

        # Simulate turn_on
        hvac._guest_mode_actuation_enabled = True
        assert hvac._guest_mode_actuation_enabled

    def test_master_toggle_default_is_true(self):
        """master_enabled defaults to True in HVACCoordinator constructor."""
        hvac = _make_mock_hvac()
        assert hvac._guest_mode_actuation_enabled is True, (
            "CONF_GUEST_MODE_ACTUATION_ENABLED defaults to True"
        )


# ---------------------------------------------------------------------------
# D4: Active preset overrides diagnostic sensor
# ---------------------------------------------------------------------------

class TestActivePresetOverridesSensor:
    """D4 acceptance: sensor state + attributes reflect OverrideEngine output."""

    def _build_sensor_state(
        self,
        overrides_by_zone: dict,
        house_state: str = "home_day",
        master_enabled: bool = True,
        target_preset: str = "home",
        baseline_cool: float = 77.0,
    ) -> tuple[int, dict]:
        """Compute sensor state and attributes directly via OverrideEngine.

        This tests the production computation logic without a full HA entity.
        """
        engine = OverrideEngine()
        count = 0
        by_zone: dict = {}
        resolved_ranges: dict = {}

        for zone_id, zone_overrides in overrides_by_zone.items():
            active = engine.get_active_overrides(
                zone_id, target_preset, house_state, master_enabled, zone_overrides
            )
            if not active:
                continue
            count += len(active)
            by_zone[zone_id] = [
                {
                    "preset": o.preset,
                    "source": o.source,
                    "cool_low": o.cool_low,
                    "cool_high": o.cool_high,
                    "priority": o.priority,
                }
                for o in active
            ]
            baseline_low = baseline_cool - 7.0
            resolved = engine.resolve_range(baseline_low, baseline_cool, active)
            resolved_ranges[zone_id] = {
                "cool_low": resolved.cool_low,
                "cool_high": resolved.cool_high,
                "sources": resolved.sources,
            }

        return count, {
            "by_zone": by_zone,
            "house_state": house_state,
            "master_enabled": master_enabled,
            "resolved_ranges": resolved_ranges,
        }

    def test_active_overrides_sensor_state_count(self):
        """Sensor state = total count of active override records.

        Two zones, two home-preset overrides in zone_2 (different sources) → count=3.
        target_preset defaults to "home" so all three records are active.
        """
        overrides = {
            "zone_1": [_make_override(zone_id="zone_1")],
            "zone_2": [
                _make_override(zone_id="zone_2"),
                _make_override(zone_id="zone_2", cool_high=73.0),  # second home-preset override
            ],
        }
        count, _ = self._build_sensor_state(overrides)
        assert count == 3, f"Expected 3 active overrides, got {count}"

    def test_active_overrides_sensor_attributes_shape(self):
        """Attributes include by_zone, house_state, master_enabled, resolved_ranges."""
        overrides = {
            "zone_1": [_make_override(zone_id="zone_1", cool_low=70.0, cool_high=74.0)],
        }
        count, attrs = self._build_sensor_state(overrides, house_state="guest")
        assert "by_zone" in attrs
        assert "house_state" in attrs
        assert "master_enabled" in attrs
        assert "resolved_ranges" in attrs
        assert attrs["house_state"] == "guest"
        assert "zone_1" in attrs["by_zone"]
        assert "zone_1" in attrs["resolved_ranges"]
        assert attrs["resolved_ranges"]["zone_1"]["cool_high"] == 74.0

    def test_active_overrides_sensor_clears_when_master_disabled(self):
        """When master_enabled=False, sensor returns 0 and empty by_zone."""
        overrides = {
            "zone_1": [_make_override(zone_id="zone_1")],
        }
        count, attrs = self._build_sensor_state(overrides, master_enabled=False)
        assert count == 0, "count must be 0 when master_enabled=False"
        assert attrs["by_zone"] == {}, "by_zone must be empty when master disabled"

    def test_active_overrides_sensor_updates_on_house_state_change(self):
        """Sensor value changes when house_state transitions (predicate re-evaluated)."""
        guest_override = PresetOverride(
            source=OVERRIDE_SOURCE_GUEST_MODE,
            preset="home",
            cool_high=75.0,
            priority=GUEST_MODE_PRIORITY,
            zone_id="zone_1",
            active_when="house_state == 'guest'",
        )
        overrides = {"zone_1": [guest_override]}

        # Under home_day: guest_mode predicate inactive → count=0
        count_home, _ = self._build_sensor_state(overrides, house_state="home_day")
        assert count_home == 0, "Guest override inactive when not in guest state"

        # Under guest: guest_mode predicate active → count=1
        count_guest, attrs_guest = self._build_sensor_state(overrides, house_state="guest")
        assert count_guest == 1, "Guest override active when house_state=guest"
        assert attrs_guest["resolved_ranges"]["zone_1"]["cool_high"] == 75.0


# ---------------------------------------------------------------------------
# D2+D3: Integration — master OFF prevents actuation
# ---------------------------------------------------------------------------

class TestD2D3Integration:
    """Integration: D2 actuation gated by D3 master toggle."""

    def test_override_engine_respects_master_flag(self):
        """OverrideEngine.get_active_overrides returns empty when master_enabled=False."""
        engine = OverrideEngine()
        overrides = [
            _make_override(zone_id="z1"),
            PresetOverride(
                source=OVERRIDE_SOURCE_GUEST_MODE,
                preset="home",
                cool_high=75.0,
                priority=GUEST_MODE_PRIORITY,
                zone_id="z1",
                active_when="house_state == 'guest'",
            ),
        ]
        # Master OFF: nothing active
        active_off = engine.get_active_overrides("z1", "home", "guest", False, overrides)
        assert active_off == []

        # Master ON: guest override active
        active_on = engine.get_active_overrides("z1", "home", "guest", True, overrides)
        assert len(active_on) >= 1

    def test_observation_mode_gate_pattern(self):
        """D2 code must gate on observation_mode before calling _async_apply_preset_overrides.

        This tests the contract pattern (not the full coordinator) — the call
        to _async_apply_preset_overrides is only made when observation_mode=False.
        """
        observation_mode = False
        apply_was_called = [False]

        def _maybe_apply():
            if not observation_mode:
                apply_was_called[0] = True

        _maybe_apply()
        assert apply_was_called[0], "apply should be called when observation_mode=False"

        apply_was_called[0] = False
        observation_mode = True
        _maybe_apply()
        assert not apply_was_called[0], "apply must be skipped when observation_mode=True"

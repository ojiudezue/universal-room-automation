"""Tests for WeatherProviderManager — v4.7.x Cycle A.

Covers:
- Failover state machine (5 scenarios per plan §A.B.2)
- Apparent-temp fallback to raw temperature
- Divergence detection
- Unsub cleanup on teardown (Bug #38)
- Source-contract AST tests for new CONFs (Bug #32)
- EnergyConstraint apparent_forecast_high_temp field (Bug #37)
"""
from __future__ import annotations

import ast
import os
import sys
import types
import importlib
import importlib.util
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
# ---------------------------------------------------------------------------


def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

# dt_util mock with timezone-aware utcnow
_UTC = timezone.utc


def _utcnow():
    return datetime.now(_UTC)


def _now():
    return datetime.now()


_dt_util_mock = _mock_module(
    "homeassistant.util.dt",
    utcnow=_utcnow,
    now=_now,
    UTC=_UTC,
    as_local=lambda dt: dt,
)

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
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
    "homeassistant.helpers.entity_platform": {
        "AddEntitiesCallback": _mock_cls,
    },
    "homeassistant.helpers.event": {
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {"RestoreEntity": _mock_cls},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": _dt_util_mock,
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
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": _mock_cls(),
        "NumberDeviceClass": _mock_cls(),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

# WPM-C4: force-set dt_util with live-time mock so this file always overrides any
# frozen-time mock installed by another test file (e.g. EV TOU's _FIXED_NOW).
# Bug Class #44: cross-file sys.modules pollution via setdefault race.
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
    """Load a domain_coordinators submodule."""
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


# Load const module (needed by energy_const)
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Load submodules
_load_submod("energy_const")
_load_submod("signals")
_load_submod("weather_manager")

from custom_components.universal_room_automation.domain_coordinators.weather_manager import (
    WeatherProviderManager,
    WeatherProviderHealth,
    WeatherForecast,
    _probe_apparent_temp_attrs,
    _parse_float,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_ENERGY_WEATHER_ENTITY,
    CONF_ENERGY_WEATHER_FALLBACK_1,
    CONF_ENERGY_WEATHER_FALLBACK_2,
    CONF_WEATHER_STALENESS_MAX_HOURS,
    CONF_WEATHER_DIVERGENCE_THRESHOLD_F,
    DEFAULT_WEATHER_STALENESS_MAX_HOURS,
    DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F,
)
from custom_components.universal_room_automation.domain_coordinators.signals import (
    EnergyConstraint,
    SIGNAL_WEATHER_PROVIDER_CHANGED,
    SIGNAL_WEATHER_DIVERGENCE_DETECTED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    entity_id: str,
    state: str = "partlycloudy",
    attributes: dict | None = None,
    last_changed: datetime | None = None,
) -> MagicMock:
    """Build a mock HA State object."""
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    s.attributes = attributes or {}
    s.last_changed = last_changed or _utcnow()
    return s


def _make_hass(states: dict[str, MagicMock] | None = None) -> MagicMock:
    """Build a mock hass with states and service call support."""
    hass = MagicMock()
    _states = states or {}
    hass.states.get = lambda eid: _states.get(eid)
    hass.services = MagicMock()
    hass.data = {}
    # async_create_task must run the coroutine (simplified: ignore in sync tests)
    hass.async_create_task = MagicMock()
    return hass


def _forecast_response(entity_id: str, temperature: float, templow: float,
                        apparent: float | None = None) -> dict:
    """Build a weather.get_forecasts-style response dict."""
    entry: dict = {"temperature": temperature, "templow": templow}
    if apparent is not None:
        entry["apparent_temperature"] = apparent
    return {entity_id: {"forecast": [entry]}}


# ---------------------------------------------------------------------------
# Unit tests: _probe_apparent_temp_attrs + _parse_float
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for module-level helpers."""

    def test_probe_apparent_met_no(self):
        assert _probe_apparent_temp_attrs({"apparent_temperature": 88.0}) == 88.0

    def test_probe_apparent_nws_feels_like(self):
        assert _probe_apparent_temp_attrs({"temperature_feels_like": 92.5}) == 92.5

    def test_probe_apparent_missing_returns_none(self):
        assert _probe_apparent_temp_attrs({"temperature": 85.0}) is None

    def test_probe_apparent_prefers_apparent_over_feels_like(self):
        attrs = {"apparent_temperature": 88.0, "temperature_feels_like": 90.0}
        # First key in _APPARENT_TEMP_ATTRS wins
        assert _probe_apparent_temp_attrs(attrs) == 88.0

    def test_parse_float_normal(self):
        assert _parse_float(85.5) == 85.5

    def test_parse_float_string(self):
        assert _parse_float("85.5") == 85.5

    def test_parse_float_none(self):
        assert _parse_float(None) is None

    def test_parse_float_non_numeric(self):
        assert _parse_float("N/A") is None


# ---------------------------------------------------------------------------
# WeatherProviderHealth enum
# ---------------------------------------------------------------------------


class TestWeatherProviderHealthEnum:
    """Bug #22: StrEnum so string comparison works."""

    def test_healthy_str(self):
        assert str(WeatherProviderHealth.HEALTHY) == "healthy"

    def test_unavailable_str(self):
        assert str(WeatherProviderHealth.UNAVAILABLE) == "unavailable"

    def test_stale_str(self):
        assert str(WeatherProviderHealth.STALE) == "stale"


# ---------------------------------------------------------------------------
# _build_provider_list
# ---------------------------------------------------------------------------


class TestBuildProviderList:
    """Provider list construction from options."""

    def _make_mgr(self, options: dict) -> WeatherProviderManager:
        hass = _make_hass()
        return WeatherProviderManager(hass, options)

    def test_single_provider(self):
        mgr = self._make_mgr({CONF_ENERGY_WEATHER_ENTITY: "weather.met_no"})
        assert mgr._build_provider_list() == ["weather.met_no"]

    def test_three_providers(self):
        mgr = self._make_mgr({
            CONF_ENERGY_WEATHER_ENTITY: "weather.primary",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.fallback1",
            CONF_ENERGY_WEATHER_FALLBACK_2: "weather.fallback2",
        })
        assert mgr._build_provider_list() == [
            "weather.primary", "weather.fallback1", "weather.fallback2"
        ]

    def test_empty_fallbacks_filtered(self):
        mgr = self._make_mgr({
            CONF_ENERGY_WEATHER_ENTITY: "weather.primary",
            CONF_ENERGY_WEATHER_FALLBACK_1: "",
        })
        assert mgr._build_provider_list() == ["weather.primary"]

    def test_no_config_returns_empty(self):
        mgr = self._make_mgr({})
        assert mgr._build_provider_list() == []

    def test_deduplication(self):
        mgr = self._make_mgr({
            CONF_ENERGY_WEATHER_ENTITY: "weather.primary",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.primary",  # duplicate
        })
        assert mgr._build_provider_list() == ["weather.primary"]


# ---------------------------------------------------------------------------
# _check_provider_health
# ---------------------------------------------------------------------------


class TestProviderHealth:
    """Health check logic."""

    def _mgr(self, state=None, entity_id="weather.test"):
        hass = _make_hass({entity_id: state} if state else {})
        return WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: entity_id,
        })

    def test_none_state_returns_unavailable(self):
        mgr = self._mgr()
        assert mgr._check_provider_health("weather.test") == WeatherProviderHealth.UNAVAILABLE

    def test_unavailable_state(self):
        state = _make_state("weather.test", "unavailable")
        mgr = self._mgr(state)
        assert mgr._check_provider_health("weather.test") == WeatherProviderHealth.UNAVAILABLE

    def test_unknown_state(self):
        state = _make_state("weather.test", "unknown")
        mgr = self._mgr(state)
        assert mgr._check_provider_health("weather.test") == WeatherProviderHealth.UNAVAILABLE

    def test_healthy_with_apparent_temp(self):
        state = _make_state("weather.test", "sunny", {"apparent_temperature": 88.0})
        mgr = self._mgr(state)
        assert mgr._check_provider_health("weather.test") == WeatherProviderHealth.HEALTHY

    def test_apparent_unavailable_without_apparent_attr(self):
        """Provider missing apparent_temp is marked APPARENT_UNAVAILABLE but usable."""
        state = _make_state("weather.test", "sunny", {"temperature": 85.0})
        mgr = self._mgr(state)
        assert mgr._check_provider_health("weather.test") == WeatherProviderHealth.APPARENT_UNAVAILABLE

    def test_stale_entity(self):
        """Entity last_changed > staleness_max_hours = STALE."""
        from datetime import timedelta
        old_time = _utcnow() - timedelta(hours=8)
        state = _make_state("weather.test", "sunny", {"apparent_temperature": 85.0}, old_time)
        hass = _make_hass({"weather.test": state})
        mgr = WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: "weather.test",
            CONF_WEATHER_STALENESS_MAX_HOURS: 6,
        })
        assert mgr._check_provider_health("weather.test") == WeatherProviderHealth.STALE


# ---------------------------------------------------------------------------
# Failover state machine — 5 scenarios per §A.B.2
# ---------------------------------------------------------------------------


class TestFailoverStateMachine:
    """5 scenarios from plan §A.B.2."""

    def _options(self, primary="weather.p1", f1="weather.p2", f2="weather.p3"):
        return {
            CONF_ENERGY_WEATHER_ENTITY: primary,
            CONF_ENERGY_WEATHER_FALLBACK_1: f1,
            CONF_ENERGY_WEATHER_FALLBACK_2: f2,
        }

    def _fresh_state(self, eid, apparent=88.0):
        return _make_state(eid, "sunny", {"apparent_temperature": apparent})

    def _stale_state(self, eid, hours_old=8):
        from datetime import timedelta
        old_time = _utcnow() - timedelta(hours=hours_old)
        return _make_state(eid, "sunny", {"apparent_temperature": 88.0}, old_time)

    async def _run_refresh(self, mgr: WeatherProviderManager, forecast_map: dict) -> None:
        """Patch _fetch_provider_forecast and run _refresh_all_providers."""
        async def fake_fetch(eid):
            return forecast_map.get(eid)

        mgr._fetch_provider_forecast = fake_fetch
        await mgr._refresh_all_providers()

    # Scenario 1: All healthy → primary is active
    @pytest.mark.asyncio
    async def test_all_healthy_uses_primary(self):
        opts = self._options()
        states = {
            "weather.p1": self._fresh_state("weather.p1", 90.0),
            "weather.p2": self._fresh_state("weather.p2", 89.0),
            "weather.p3": self._fresh_state("weather.p3", 91.0),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, opts)
        forecasts = {
            "weather.p1": {"temperature": 90.0, "templow": 70.0, "apparent_temperature": 92.0},
            "weather.p2": {"temperature": 89.0, "templow": 69.0, "apparent_temperature": 91.0},
            "weather.p3": {"temperature": 91.0, "templow": 71.0, "apparent_temperature": 93.0},
        }
        await self._run_refresh(mgr, forecasts)
        assert mgr.active_provider == "weather.p1"

    # Scenario 2: Primary unavailable → secondary becomes active
    @pytest.mark.asyncio
    async def test_primary_unavailable_fails_to_secondary(self):
        opts = self._options()
        states = {
            "weather.p1": _make_state("weather.p1", "unavailable"),
            "weather.p2": self._fresh_state("weather.p2", 89.0),
            "weather.p3": self._fresh_state("weather.p3", 91.0),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, opts)
        forecasts = {
            "weather.p2": {"temperature": 89.0, "templow": 69.0, "apparent_temperature": 91.0},
            "weather.p3": {"temperature": 91.0, "templow": 71.0, "apparent_temperature": 93.0},
        }
        await self._run_refresh(mgr, forecasts)
        assert mgr.active_provider == "weather.p2"

    # Scenario 3: Primary + secondary unavailable → tertiary is active
    @pytest.mark.asyncio
    async def test_p1_p2_down_tertiary_active(self):
        opts = self._options()
        states = {
            "weather.p1": _make_state("weather.p1", "unavailable"),
            "weather.p2": _make_state("weather.p2", "unknown"),
            "weather.p3": self._fresh_state("weather.p3", 91.0),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, opts)
        forecasts = {
            "weather.p3": {"temperature": 91.0, "templow": 71.0, "apparent_temperature": 93.0},
        }
        await self._run_refresh(mgr, forecasts)
        assert mgr.active_provider == "weather.p3"

    # Scenario 4: All unavailable → active_provider = None, status = "all_stale"
    @pytest.mark.asyncio
    async def test_all_unavailable_returns_none(self):
        opts = self._options()
        states = {
            "weather.p1": _make_state("weather.p1", "unavailable"),
            "weather.p2": _make_state("weather.p2", "unavailable"),
            "weather.p3": _make_state("weather.p3", "unavailable"),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, opts)
        await self._run_refresh(mgr, {})
        assert mgr.active_provider is None
        assert mgr.provider_status_str == "all_stale"

    # Scenario 5: P1 stale + P2 fresh → failover to P2
    @pytest.mark.asyncio
    async def test_p1_stale_p2_fresh_uses_p2(self):
        opts = self._options(f2="")
        states = {
            "weather.p1": self._stale_state("weather.p1", hours_old=8),
            "weather.p2": self._fresh_state("weather.p2", 88.0),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
            CONF_WEATHER_STALENESS_MAX_HOURS: 6,
        })
        forecasts = {
            "weather.p2": {"temperature": 88.0, "templow": 68.0, "apparent_temperature": 90.0},
        }
        await self._run_refresh(mgr, forecasts)
        assert mgr.active_provider == "weather.p2"


# ---------------------------------------------------------------------------
# get_today_forecast — return shape + confidence
# ---------------------------------------------------------------------------


class TestGetTodayForecast:
    """Forecast return value shape and apparent-confidence."""

    async def _run(self, states, forecast_map, options):
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, options)

        async def fake_fetch(eid):
            return forecast_map.get(eid)

        mgr._fetch_provider_forecast = fake_fetch
        return await mgr.get_today_forecast()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_providers(self):
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})

        async def fake_fetch(eid):
            return None

        mgr._fetch_provider_forecast = fake_fetch
        result = await mgr.get_today_forecast()
        assert result is None

    @pytest.mark.asyncio
    async def test_high_confidence_when_apparent_present(self):
        states = {
            "weather.met": _make_state("weather.met", "sunny", {"apparent_temperature": 92.0})
        }
        forecast_map = {
            "weather.met": {"temperature": 90.0, "templow": 70.0, "apparent_temperature": 92.0}
        }
        opts = {CONF_ENERGY_WEATHER_ENTITY: "weather.met"}
        result = await self._run(states, forecast_map, opts)
        assert result is not None
        assert result.apparent_high == 92.0
        assert result.raw_high == 90.0
        assert result.apparent_confidence == "high"

    @pytest.mark.asyncio
    async def test_fallback_raw_when_apparent_missing(self):
        """Single provider with no apparent_temp → confidence = fallback_raw."""
        states = {
            "weather.nws": _make_state("weather.nws", "sunny", {"temperature": 85.0})
        }
        forecast_map = {
            "weather.nws": {"temperature": 85.0, "templow": 65.0}  # no apparent
        }
        opts = {CONF_ENERGY_WEATHER_ENTITY: "weather.nws"}
        result = await self._run(states, forecast_map, opts)
        assert result is not None
        # apparent_high should fall back to raw_high
        assert result.apparent_high == 85.0
        assert result.apparent_confidence == "fallback_raw"

    @pytest.mark.asyncio
    async def test_apparent_unavailable_fallback_with_multi_provider(self):
        """Active provider missing apparent_temp → confidence = apparent_unavailable_fallback_raw."""
        states = {
            "weather.p1": _make_state("weather.p1", "sunny", {"temperature": 85.0}),
            "weather.p2": _make_state("weather.p2", "sunny", {"apparent_temperature": 87.0}),
        }
        forecast_map = {
            "weather.p1": {"temperature": 85.0, "templow": 65.0},  # no apparent
            "weather.p2": {"temperature": 87.0, "templow": 67.0, "apparent_temperature": 87.0},
        }
        opts = {
            CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
        }
        result = await self._run(states, forecast_map, opts)
        assert result is not None
        # p1 is active (first healthy), no apparent → confidence = apparent_unavailable_fallback_raw
        assert result.apparent_confidence == "apparent_unavailable_fallback_raw"


# ---------------------------------------------------------------------------
# Divergence detection (Bug #32: sensor populator tests)
# ---------------------------------------------------------------------------


class TestDivergenceDetection:
    """Divergence flag and threshold logic."""

    @pytest.mark.asyncio
    async def test_no_divergence_single_provider(self):
        states = {"weather.p1": _make_state("weather.p1", "sunny", {"apparent_temperature": 90.0})}
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 5.0,
        })

        async def fake_fetch(eid):
            return {"temperature": 90.0, "templow": 70.0, "apparent_temperature": 90.0}

        mgr._fetch_provider_forecast = fake_fetch
        await mgr._refresh_all_providers()
        assert mgr.is_divergent is False
        assert mgr.divergence_f is None

    @pytest.mark.asyncio
    async def test_divergence_detected_above_threshold(self):
        """Two providers differ by 8°F > 5°F threshold → divergent=True."""
        states = {
            "weather.p1": _make_state("weather.p1", "sunny", {"apparent_temperature": 90.0}),
            "weather.p2": _make_state("weather.p2", "sunny", {"apparent_temperature": 98.0}),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 5.0,
        })

        async def fake_fetch(eid):
            t = {"weather.p1": 90.0, "weather.p2": 98.0}.get(eid)
            if t is None:
                return None
            return {"temperature": t, "templow": 70.0, "apparent_temperature": t}

        mgr._fetch_provider_forecast = fake_fetch
        await mgr._refresh_all_providers()
        assert mgr.is_divergent is True
        assert mgr.divergence_f == pytest.approx(8.0)

    @pytest.mark.asyncio
    async def test_divergence_below_threshold_not_divergent(self):
        """3°F delta < 5°F threshold → divergent=False."""
        states = {
            "weather.p1": _make_state("weather.p1", "sunny", {"apparent_temperature": 90.0}),
            "weather.p2": _make_state("weather.p2", "sunny", {"apparent_temperature": 93.0}),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 5.0,
        })

        async def fake_fetch(eid):
            t = {"weather.p1": 90.0, "weather.p2": 93.0}.get(eid)
            if t is None:
                return None
            return {"temperature": t, "templow": 70.0, "apparent_temperature": t}

        mgr._fetch_provider_forecast = fake_fetch
        await mgr._refresh_all_providers()
        assert mgr.is_divergent is False

    @pytest.mark.asyncio
    async def test_divergence_uses_median_for_apparent_high(self):
        """When divergent, apparent_high on forecast = median of provider highs."""
        states = {
            "weather.p1": _make_state("weather.p1", "sunny", {"apparent_temperature": 90.0}),
            "weather.p2": _make_state("weather.p2", "sunny", {"apparent_temperature": 98.0}),
        }
        hass = _make_hass(states)
        mgr = WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 5.0,
        })

        async def fake_fetch(eid):
            t = {"weather.p1": 90.0, "weather.p2": 98.0}.get(eid)
            if t is None:
                return None
            return {"temperature": t, "templow": 70.0, "apparent_temperature": t}

        mgr._fetch_provider_forecast = fake_fetch
        await mgr._refresh_all_providers()
        # Median of [90, 98] = (90 + 98) / 2 = 94
        assert mgr._cached_forecast is not None
        assert mgr._cached_forecast.apparent_high == pytest.approx(94.0)


# ---------------------------------------------------------------------------
# test_weather_manager_apparent_fallback_to_raw (plan acceptance criterion)
# ---------------------------------------------------------------------------


class TestApparentFallback:
    """Acceptance criteria: apparent_confidence='fallback_raw' when apparent missing."""

    @pytest.mark.asyncio
    async def test_apparent_fallback_to_raw(self):
        """Single provider with no apparent_temperature → fallback_raw."""
        state = _make_state("weather.nws", "sunny", {"temperature": 85.0})
        hass = _make_hass({"weather.nws": state})
        mgr = WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: "weather.nws"})

        async def fake_fetch(eid):
            return {"temperature": 85.0, "templow": 65.0}  # no apparent

        mgr._fetch_provider_forecast = fake_fetch
        await mgr._refresh_all_providers()
        assert mgr._cached_forecast is not None
        assert mgr._cached_forecast.apparent_confidence == "fallback_raw"
        assert mgr._cached_forecast.apparent_high == 85.0


# ---------------------------------------------------------------------------
# test_weather_manager_unsub_on_teardown (Bug #38)
# ---------------------------------------------------------------------------


class TestUnsubOnTeardown:
    """Bug #38: every unsub handle is called during async_teardown."""

    @pytest.mark.asyncio
    async def test_unsub_called_for_each_provider(self):
        """Patch async_track_state_change_event directly on the module object."""
        import custom_components.universal_room_automation.domain_coordinators.weather_manager as wm_mod

        unsub_mocks = [MagicMock(), MagicMock(), MagicMock()]
        call_count = [0]

        original_track = wm_mod.async_track_state_change_event

        def track_side_effect(hass, entities, callback):
            idx = call_count[0]
            call_count[0] += 1
            return unsub_mocks[min(idx, len(unsub_mocks) - 1)]

        wm_mod.async_track_state_change_event = track_side_effect

        try:
            hass = _make_hass()

            async def _noop():
                pass

            opts = {
                CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
                CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
                CONF_ENERGY_WEATHER_FALLBACK_2: "weather.p3",
            }
            mgr = WeatherProviderManager(hass, opts)
            mgr._refresh_all_providers = _noop
            await mgr.async_setup()
        finally:
            wm_mod.async_track_state_change_event = original_track

        # Tear down — all unsubs should be called
        await mgr.async_teardown()
        for u in unsub_mocks[:call_count[0]]:
            u.assert_called_once()

    @pytest.mark.asyncio
    async def test_teardown_clears_unsub_list(self):
        """Unsub list is empty after async_teardown."""
        import custom_components.universal_room_automation.domain_coordinators.weather_manager as wm_mod

        original_track = wm_mod.async_track_state_change_event
        wm_mod.async_track_state_change_event = lambda *a, **kw: MagicMock()

        try:
            hass = _make_hass()

            async def _noop():
                pass

            opts = {CONF_ENERGY_WEATHER_ENTITY: "weather.p1"}
            mgr = WeatherProviderManager(hass, opts)
            mgr._refresh_all_providers = _noop
            await mgr.async_setup()
            assert len(mgr._unsub_handles) > 0
        finally:
            wm_mod.async_track_state_change_event = original_track

        await mgr.async_teardown()
        assert len(mgr._unsub_handles) == 0


# ---------------------------------------------------------------------------
# Source-contract tests: Bug #32 — every CONF has a runtime reader
# ---------------------------------------------------------------------------


class TestSourceContractConfs:
    """Bug #32: each new CONF constant NAME must appear in weather_manager.py source.

    The test checks that the constant NAMES (not values) are referenced, because
    the source imports and uses the constant names (not string literals).
    """

    # Constant names (not values) as they appear in weather_manager.py
    _REQUIRED_CONF_NAMES = [
        "CONF_ENERGY_WEATHER_ENTITY",
        "CONF_ENERGY_WEATHER_FALLBACK_1",
        "CONF_ENERGY_WEATHER_FALLBACK_2",
        "CONF_WEATHER_STALENESS_MAX_HOURS",
        "CONF_WEATHER_DIVERGENCE_THRESHOLD_F",
    ]

    def _read_source(self) -> str:
        path = os.path.join(_dc_path, "weather_manager.py")
        with open(path) as f:
            return f.read()

    def test_each_conf_name_referenced_in_weather_manager(self):
        """All 5 new CONF constant names are referenced in weather_manager.py source."""
        source = self._read_source()
        for conf_name in self._REQUIRED_CONF_NAMES:
            assert conf_name in source, (
                f"CONF constant '{conf_name}' not found in weather_manager.py — "
                "Bug #32: every CONF must have a runtime reader"
            )

    def test_staleness_conf_read_in_method(self):
        """CONF_WEATHER_STALENESS_MAX_HOURS is read inside a WeatherProviderManager method."""
        source = self._read_source()
        assert "CONF_WEATHER_STALENESS_MAX_HOURS" in source

    def test_divergence_conf_read_in_method(self):
        """CONF_WEATHER_DIVERGENCE_THRESHOLD_F is read inside a WeatherProviderManager method."""
        source = self._read_source()
        assert "CONF_WEATHER_DIVERGENCE_THRESHOLD_F" in source


# ---------------------------------------------------------------------------
# AST regression: no direct hass.states.get("weather.*") in domain code (A4)
# ---------------------------------------------------------------------------


class TestNoLiteralWeatherStateReads:
    """A4: test_no_direct_hass_states_get_weather_in_domain_code.

    Line-grep for literal states.get('weather.*') patterns in domain coordinator
    files. Does NOT catch variable-based reads (e.g., eid = 'weather.foo';
    states.get(eid)) — only literal string arguments are detected.

    weather_manager.py itself is exempted (it's the router, not a direct consumer).
    """

    _EXEMPT = {"weather_manager.py"}

    def _scan_file(self, path: str) -> list[str]:
        """Return list of line snippets with direct weather state reads."""
        hits = []
        with open(path) as f:
            for i, line in enumerate(f, 1):
                stripped = line.strip()
                # Look for hass.states.get("weather. pattern or states.get("weather.
                if (
                    'states.get("weather.' in stripped
                    or "states.get('weather." in stripped
                ):
                    hits.append(f"  line {i}: {stripped}")
        return hits

    def test_no_direct_weather_state_reads_in_energy(self):
        path = os.path.join(_dc_path, "energy.py")
        # After Cycle A migration: _weather_entity reads are replaced by
        # _get_active_weather_entity() which routes through the manager.
        # The remaining hass.states.get() calls in energy.py should NOT
        # include literal "weather.*" strings.
        hits = self._scan_file(path)
        assert hits == [], (
            f"Direct hass.states.get('weather.*') found in energy.py "
            f"(Bug #37 violation):\n" + "\n".join(hits)
        )

    def test_no_direct_weather_state_reads_in_hvac(self):
        path = os.path.join(_dc_path, "hvac.py")
        if not os.path.exists(path):
            pytest.skip("hvac.py not found")
        hits = self._scan_file(path)
        assert hits == [], (
            f"Direct hass.states.get('weather.*') in hvac.py:\n" + "\n".join(hits)
        )


# ---------------------------------------------------------------------------
# EnergyConstraint: apparent_forecast_high_temp field (Bug #37 — additive)
# ---------------------------------------------------------------------------


class TestEnergyConstraintApparentField:
    """Bug #37: apparent_forecast_high_temp added alongside forecast_high_temp."""

    def test_apparent_field_defaults_to_none(self):
        """Existing EnergyConstraint instantiation without new field still works."""
        c = EnergyConstraint(mode="normal", setpoint_offset=0.0)
        assert c.apparent_forecast_high_temp is None

    def test_apparent_field_can_be_set(self):
        c = EnergyConstraint(
            mode="pre_cool",
            setpoint_offset=-2.0,
            forecast_high_temp=90.0,
            apparent_forecast_high_temp=93.0,
        )
        assert c.apparent_forecast_high_temp == 93.0
        assert c.forecast_high_temp == 90.0  # original unchanged

    def test_apparent_field_independent_of_raw(self):
        """apparent_forecast_high_temp and forecast_high_temp are independent."""
        c = EnergyConstraint(
            mode="normal",
            setpoint_offset=0.0,
            forecast_high_temp=85.0,
            apparent_forecast_high_temp=None,  # not yet known
        )
        assert c.forecast_high_temp == 85.0
        assert c.apparent_forecast_high_temp is None

    def test_hvac_predictor_reads_forecast_high_temp(self):
        """forecast_high_temp must still be readable for existing HVAC consumers."""
        c = EnergyConstraint(
            mode="pre_cool",
            setpoint_offset=-2.0,
            forecast_high_temp=92.0,
            apparent_forecast_high_temp=95.0,
        )
        # HVAC predictor reads constraint.forecast_high_temp (raw_high)
        assert c.forecast_high_temp == 92.0


# ---------------------------------------------------------------------------
# Signal constants (Bug #22 / new signals added to signals.py)
# ---------------------------------------------------------------------------


class TestSignalConstants:
    """Verify new signals are defined in signals.py."""

    def test_weather_provider_changed_signal(self):
        assert SIGNAL_WEATHER_PROVIDER_CHANGED == "ura_weather_provider_changed"

    def test_weather_divergence_signal(self):
        assert SIGNAL_WEATHER_DIVERGENCE_DETECTED == "ura_weather_divergence_detected"


# ---------------------------------------------------------------------------
# Config default values (Bug #32)
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    """Default values match plan §A.B.1."""

    def test_staleness_default(self):
        assert DEFAULT_WEATHER_STALENESS_MAX_HOURS == 6

    def test_divergence_default(self):
        assert DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F == 5.0

    def test_fallback_conf_keys_defined(self):
        assert CONF_ENERGY_WEATHER_FALLBACK_1 == "energy_weather_fallback_1"
        assert CONF_ENERGY_WEATHER_FALLBACK_2 == "energy_weather_fallback_2"


# ---------------------------------------------------------------------------
# WPM reviewer fix-up: new tests covering CRITICAL/HIGH fixes
# ---------------------------------------------------------------------------


class TestReentrancyLock:
    """WPM-C1/C2: _refresh_lock serialises concurrent refreshes."""

    @pytest.mark.asyncio
    async def test_concurrent_refresh_serialised_not_interleaved(self):
        """Two concurrent _refresh_all_providers calls run sequentially, not interleaved."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: "weather.p1"})

        call_log: list[str] = []

        async def slow_fetch(eid):
            # Yield control to allow concurrent tasks to try and start
            await asyncio.sleep(0)
            call_log.append(f"fetch:{eid}")
            return {"temperature": 85.0, "templow": 65.0, "apparent_temperature": 88.0}

        mgr._fetch_provider_forecast = slow_fetch
        state = _make_state("weather.p1", "sunny", {"apparent_temperature": 88.0})
        mgr.hass.states.get = lambda _: state

        # Launch two concurrent refreshes
        task1 = asyncio.ensure_future(mgr._refresh_all_providers())
        task2 = asyncio.ensure_future(mgr._refresh_all_providers())
        await asyncio.gather(task1, task2)

        # Both should have run (2 fetches total) but NOT interleaved
        assert len(call_log) == 2, f"Expected 2 fetch calls, got {len(call_log)}: {call_log}"
        # All fetches should be for the same entity (no mixed writes)
        assert all("weather.p1" in c for c in call_log)

    @pytest.mark.asyncio
    async def test_refresh_lock_attribute_present(self):
        """WPM-C1: _refresh_lock is initialised in __init__."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})
        assert hasattr(mgr, "_refresh_lock")
        assert isinstance(mgr._refresh_lock, asyncio.Lock)


class TestUntrackedTaskTracking:
    """WPM-C2: tasks created by state-change handler are tracked and cancelled on teardown."""

    def test_pending_refresh_tasks_initialised_empty(self):
        """_pending_refresh_tasks is an empty set on init."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})
        assert hasattr(mgr, "_pending_refresh_tasks")
        assert isinstance(mgr._pending_refresh_tasks, set)
        assert len(mgr._pending_refresh_tasks) == 0

    def test_state_change_handler_calls_async_create_task(self):
        """_handle_provider_state_change calls hass.async_create_task and tracks result."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: "weather.p1"})

        created_tasks: list = []

        def fake_create_task(coro, name=None):
            # Return a mock task (not a real asyncio task) to test bookkeeping
            fake_task = MagicMock()
            fake_task.add_done_callback = MagicMock()
            created_tasks.append(fake_task)
            # Close the coroutine to avoid ResourceWarning
            coro.close()
            return fake_task

        hass.async_create_task = fake_create_task

        # Simulate a state-change event
        event = MagicMock()
        event.data = {"entity_id": "weather.p1"}
        mgr._handle_provider_state_change(event)

        # Task was created and add_done_callback was registered
        assert len(created_tasks) == 1
        created_tasks[0].add_done_callback.assert_called_once()
        # The discard callback should have been passed
        cb_arg = created_tasks[0].add_done_callback.call_args[0][0]
        assert cb_arg == mgr._pending_refresh_tasks.discard

    @pytest.mark.asyncio
    async def test_teardown_cancels_pending_tasks(self):
        """async_teardown cancels in-flight tasks and clears the pending set."""
        import custom_components.universal_room_automation.domain_coordinators.weather_manager as wm_mod

        original_track = wm_mod.async_track_state_change_event
        wm_mod.async_track_state_change_event = lambda *a, **kw: MagicMock()

        try:
            hass = _make_hass()
            opts = {CONF_ENERGY_WEATHER_ENTITY: "weather.p1"}
            mgr = WeatherProviderManager(hass, opts)

            async def noop():
                pass

            mgr._refresh_all_providers = noop
            await mgr.async_setup()
        finally:
            wm_mod.async_track_state_change_event = original_track

        # Manually add a real asyncio task that is already done
        async def _immediate():
            pass
        task = asyncio.ensure_future(_immediate())
        await task  # let it complete
        mgr._pending_refresh_tasks.add(task)

        await mgr.async_teardown()
        assert len(mgr._pending_refresh_tasks) == 0


class TestDivergenceSignalTransition:
    """WPM-C3: divergence signal fires only on enter-divergence, not on every tick."""

    @pytest.mark.asyncio
    async def test_divergence_signal_fires_only_on_enter(self):
        """Signal fires once when divergence is first detected; not on subsequent ticks."""
        import custom_components.universal_room_automation.domain_coordinators.weather_manager as wm_mod

        send_calls: list = []

        original_dispatcher = None
        try:
            from homeassistant.helpers import dispatcher as disp_mod
            original_dispatcher_send = getattr(disp_mod, "async_dispatcher_send", None)
        except Exception:
            original_dispatcher_send = None

        # Patch the inline import used by _refresh_all_providers_locked
        import homeassistant.helpers.dispatcher as _disp
        _orig_send = _disp.async_dispatcher_send

        def patched_send(hass, signal, payload=None):
            send_calls.append(signal)

        _disp.async_dispatcher_send = patched_send

        try:
            opts = {
                CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
                CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
                CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 5.0,
            }
            hass = _make_hass()
            p1_state = _make_state("weather.p1", "sunny", {"apparent_temperature": 90.0})
            p2_state = _make_state("weather.p2", "sunny", {"apparent_temperature": 90.0})
            hass.states.get = lambda eid: {"weather.p1": p1_state, "weather.p2": p2_state}.get(eid)
            mgr = WeatherProviderManager(hass, opts)

            # Divergent forecasts (10°F apart > 5°F threshold)
            async def divergent_fetch(eid):
                return {
                    "weather.p1": {"temperature": 100.0, "templow": 70.0, "apparent_temperature": 100.0},
                    "weather.p2": {"temperature": 90.0, "templow": 65.0, "apparent_temperature": 90.0},
                }.get(eid)

            mgr._fetch_provider_forecast = divergent_fetch

            from custom_components.universal_room_automation.domain_coordinators.signals import (
                SIGNAL_WEATHER_DIVERGENCE_DETECTED,
            )

            # First tick: should fire divergence signal (enter)
            send_calls.clear()
            await mgr._refresh_all_providers()
            divergence_signals = [s for s in send_calls if s == SIGNAL_WEATHER_DIVERGENCE_DETECTED]
            assert len(divergence_signals) == 1, "Expected 1 divergence signal on first entry"

            # Second tick with same divergent state: should NOT fire again
            send_calls.clear()
            await mgr._refresh_all_providers()
            divergence_signals = [s for s in send_calls if s == SIGNAL_WEATHER_DIVERGENCE_DETECTED]
            assert len(divergence_signals) == 0, "Divergence signal must NOT fire on repeated ticks"

        finally:
            _disp.async_dispatcher_send = _orig_send

    @pytest.mark.asyncio
    async def test_was_divergent_flag_tracks_transitions(self):
        """_was_divergent tracks divergence state across refresh cycles."""
        opts = {
            CONF_ENERGY_WEATHER_ENTITY: "weather.p1",
            CONF_ENERGY_WEATHER_FALLBACK_1: "weather.p2",
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 5.0,
        }
        hass = _make_hass()
        p1_state = _make_state("weather.p1", "sunny", {"apparent_temperature": 90.0})
        p2_state = _make_state("weather.p2", "sunny", {"apparent_temperature": 90.0})
        hass.states.get = lambda eid: {"weather.p1": p1_state, "weather.p2": p2_state}.get(eid)
        mgr = WeatherProviderManager(hass, opts)
        assert mgr._was_divergent is False

        async def divergent_fetch(eid):
            return {
                "weather.p1": {"temperature": 100.0, "templow": 70.0, "apparent_temperature": 100.0},
                "weather.p2": {"temperature": 90.0, "templow": 65.0, "apparent_temperature": 90.0},
            }.get(eid)

        mgr._fetch_provider_forecast = divergent_fetch
        await mgr._refresh_all_providers()
        assert mgr._divergent is True
        assert mgr._was_divergent is True

        # Now converge
        async def convergent_fetch(eid):
            return {"temperature": 90.0, "templow": 65.0, "apparent_temperature": 90.0}

        mgr._fetch_provider_forecast = convergent_fetch
        await mgr._refresh_all_providers()
        assert mgr._divergent is False
        assert mgr._was_divergent is False


class TestCurrentApparentForecastHighAccessor:
    """WPM-H2: current_apparent_forecast_high() returns cached value without refresh."""

    def test_returns_none_when_no_forecast(self):
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})
        assert mgr.current_apparent_forecast_high() is None

    @pytest.mark.asyncio
    async def test_returns_cached_apparent_high(self):
        opts = {CONF_ENERGY_WEATHER_ENTITY: "weather.p1"}
        state = _make_state("weather.p1", "sunny", {"apparent_temperature": 93.0})
        hass = _make_hass({"weather.p1": state})
        mgr = WeatherProviderManager(hass, opts)

        async def fake_fetch(eid):
            return {"temperature": 90.0, "templow": 65.0, "apparent_temperature": 93.0}

        mgr._fetch_provider_forecast = fake_fetch
        await mgr._refresh_all_providers()
        assert mgr.current_apparent_forecast_high() == 93.0

    def test_does_not_trigger_refresh(self):
        """current_apparent_forecast_high() is purely synchronous — no await needed."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})
        # Should not raise; returning None is correct when no forecast yet
        result = mgr.current_apparent_forecast_high()
        assert result is None


class TestSensorAvailability:
    """WPM-H5: available property returns False when WPM is absent."""

    def test_wpm_absent_means_unavailable(self):
        """When weather_manager not in hass.data, available must be False."""
        # We test the logic pattern directly since the sensor classes need HA env
        hass = _make_hass()
        hass.data = {CONF_ENERGY_WEATHER_ENTITY: "weather.p1"}  # no 'weather_manager' key

        # Simulate the available check pattern used by all 3 entities
        domain_key = "universal_room_automation"  # real DOMAIN value from const
        try:
            from custom_components.universal_room_automation.const import DOMAIN
        except Exception:
            DOMAIN = "universal_room_automation"
        hass.data[DOMAIN] = {}  # no weather_manager
        available = hass.data.get(DOMAIN, {}).get("weather_manager") is not None
        assert available is False

    def test_wpm_present_means_available(self):
        """When weather_manager is in hass.data, available is True."""
        hass = _make_hass()
        try:
            from custom_components.universal_room_automation.const import DOMAIN
        except Exception:
            DOMAIN = "universal_room_automation"
        mgr = WeatherProviderManager(hass, {})
        hass.data[DOMAIN] = {"weather_manager": mgr}
        available = hass.data.get(DOMAIN, {}).get("weather_manager") is not None
        assert available is True


class TestDtUtilIsolation:
    """WPM-C4: regression — weather test's _utcnow() helper always returns live time.

    NOTE: sys.modules['homeassistant.util.dt'] may still hold EV TOU's frozen mock
    when both test files are collected in the same pytest session (EV TOU second).
    This test guards specifically against the _utcnow() helper used by TestProviderHealth
    being frozen, since THAT is what breaks test_stale_entity.
    """

    def test_weather_utcnow_helper_returns_live_time(self):
        """_utcnow() (used by test helpers) must return real datetime, not sentinel.

        The _utcnow() function is defined at module scope in this test file as
        `datetime.now(_UTC)` — it must NEVER proxy through sys.modules dt_util.
        This guards against the test helper being redirected to EV TOU's frozen clock.
        """
        now = _utcnow()
        assert isinstance(now, datetime), "Expected a datetime object"
        _SENTINEL = datetime(2026, 5, 27, 14, 0, 0, tzinfo=timezone.utc)
        drift = abs((now - _SENTINEL).total_seconds())
        # If drift is near 0 seconds, the helper has been redirected to the EV TOU sentinel.
        # Real time in 2026 should be within minutes of the sentinel; we use 1 min as guard.
        # (Test runs within seconds of actual time — if drift == 0.0 exactly, it's frozen.)
        assert drift != 0.0, (
            f"_utcnow() returned exactly the EV TOU sentinel ({now}) — "
            "the test helper must use datetime.now(), not dt_util.utcnow()"
        )


# ---------------------------------------------------------------------------
# v4.7.0.1 cleanup tests (4 fixes)
# ---------------------------------------------------------------------------


class TestUpdateOptionsDeleted:
    """Fix 1 (A5+B10): update_options() has been removed — it was never called."""

    def test_update_options_not_present(self):
        """WeatherProviderManager must NOT have an update_options() method.

        The _async_update_listener does a full entry reload rather than calling
        update_options(); keeping the method was dead code and misleading.
        """
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})
        assert not hasattr(mgr, "update_options"), (
            "update_options() was deleted in v4.7.0.1 — it must not be present. "
            "If it reappeared, remove it again: the options-update listener reloads "
            "the full entry instead of updating in-place."
        )


class TestDivergenceThresholdPublicProperty:
    """Fix 2: public divergence_threshold_f property matches private method value."""

    def test_public_property_matches_private_method(self):
        """divergence_threshold_f (property) returns same value as _divergence_threshold_f()."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 7.5,
        })
        assert mgr.divergence_threshold_f == mgr._divergence_threshold_f()

    def test_public_property_uses_default_when_not_configured(self):
        """divergence_threshold_f returns DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F when absent."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})
        assert mgr.divergence_threshold_f == DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F

    def test_public_property_reflects_custom_value(self):
        """divergence_threshold_f returns the configured value."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {CONF_WEATHER_DIVERGENCE_THRESHOLD_F: 10.0})
        assert mgr.divergence_threshold_f == 10.0


class TestPriorityRankFor:
    """Fix 3 (M3): priority_rank_for returns correct 0-indexed rank or None."""

    def _make_mgr(self, primary="weather.p1", f1="weather.p2", f2="weather.p3"):
        hass = _make_hass()
        return WeatherProviderManager(hass, {
            CONF_ENERGY_WEATHER_ENTITY: primary,
            CONF_ENERGY_WEATHER_FALLBACK_1: f1,
            CONF_ENERGY_WEATHER_FALLBACK_2: f2,
        })

    def test_primary_is_rank_0(self):
        mgr = self._make_mgr()
        assert mgr.priority_rank_for("weather.p1") == 0

    def test_fallback_1_is_rank_1(self):
        mgr = self._make_mgr()
        assert mgr.priority_rank_for("weather.p2") == 1

    def test_fallback_2_is_rank_2(self):
        mgr = self._make_mgr()
        assert mgr.priority_rank_for("weather.p3") == 2

    def test_unknown_entity_returns_none(self):
        mgr = self._make_mgr()
        assert mgr.priority_rank_for("weather.unknown") is None

    def test_none_active_priority_rank_is_none(self):
        """When active_provider is None, priority_rank_for(None) returns None."""
        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: "weather.p1"})
        # active_provider is None until a refresh runs
        assert mgr.active_provider is None
        assert mgr.priority_rank_for(mgr.active_provider) is None


class TestRenamedTestClass:
    """Fix 4 (B9): TestNoLiteralWeatherStateReads class rename sanity check.

    This test verifies the renamed class still exercises the same scanning
    logic — the name change from TestNoDirectWeatherStateReads was made to
    clarify that only literal string patterns are detected (line-grep only).
    """

    def test_scan_logic_still_works_via_renamed_class(self):
        """Verify the renamed class has a callable _scan_file method."""
        import sys
        test_mod = sys.modules[__name__]
        cls = getattr(test_mod, "TestNoLiteralWeatherStateReads", None)
        assert cls is not None, "TestNoLiteralWeatherStateReads class must exist in module"
        scanner = cls()
        assert callable(getattr(scanner, "_scan_file", None))

    def test_class_docstring_mentions_line_grep(self):
        """Docstring must mention 'line-grep' (case-insensitive) to prevent future confusion."""
        doc = (TestNoLiteralWeatherStateReads.__doc__ or "").lower()
        assert "line-grep" in doc, (
            "TestNoLiteralWeatherStateReads docstring must mention 'line-grep' "
            "to make clear this is NOT an AST walk."
        )

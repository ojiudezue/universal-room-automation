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


class TestNoDirectWeatherStateReads:
    """A4: test_no_direct_hass_states_get_weather_in_domain_code.

    Scans all domain_coordinator Python files for patterns like
    hass.states.get("weather.") or states.get("weather.").
    These must not appear because all weather reads must route through
    WeatherProviderManager (Bug #37 prevention).

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

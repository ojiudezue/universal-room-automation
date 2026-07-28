"""Tests for the weather.get_forecasts service migration (2026-07-27).

Verifies the predicted-energy family sources daily forecast highs from the
`weather.get_forecasts` service (HA 2024.4+) instead of the removed
`weather.forecast` state attribute.

Follows the source-level + isolated-behavioral pattern used by
test_predicted_energy_tomorrow.py (avoids importing aggregation.py directly,
which pulls the full URA import graph).
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import textwrap
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Bootstrap HA stubs (side-effect import — installs homeassistant.* stubs).
import test_data_pipeline  # noqa: F401,E402


AGG_SRC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "aggregation.py",
)
WEATHER_ENTITY = "weather.test"
FAKE_FORECAST = [
    {"datetime": "2026-07-27", "temperature": 97, "templow": 78},
    {"datetime": "2026-07-28", "temperature": 98, "templow": 79},
    {"datetime": "2026-07-29", "temperature": 96, "templow": 77},
]


def _agg_src() -> str:
    with open(AGG_SRC_PATH) as f:
        return f.read()


def _extract_helpers():
    """Extract the three forecast helper methods from AggregationEntity and
    bind them to a bare stand-in class so tests can drive them without
    importing the full aggregation module (which pulls the URA import graph)."""
    src = _agg_src()
    tree = ast.parse(src)
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "AggregationEntity"
    )
    wanted = {
        "_refresh_forecast_cache",
        "_get_forecast_temp",
        "_get_forecast_temp_tomorrow",
    }
    method_nodes = [
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted
    ]
    ttl_assign = next(
        n for n in cls.body
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "FORECAST_CACHE_TTL_S"
            for t in n.targets
        )
    )
    # Build a synthetic module body: import deps + class with the methods.
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="homeassistant.util",
                names=[ast.alias(name="dt", asname="dt_util")],
                level=0,
            ),
            ast.Assign(
                targets=[ast.Name(id="DOMAIN", ctx=ast.Store())],
                value=ast.Constant(value="universal_room_automation"),
            ),
            ast.Assign(
                targets=[ast.Name(id="CONF_WEATHER_ENTITY", ctx=ast.Store())],
                value=ast.Constant(value="weather_entity"),
            ),
            ast.Assign(
                targets=[ast.Name(id="_LOGGER", ctx=ast.Store())],
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="__import__", ctx=ast.Load()),
                                attr="__call__",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Constant(value="logging")],
                            keywords=[],
                        ),
                        attr="getLogger",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Constant(value="test_forecast")],
                    keywords=[],
                ),
            ),
            ast.ClassDef(
                name="_Bound",
                bases=[],
                keywords=[],
                body=[ttl_assign, *method_nodes],
                decorator_list=[],
            ),
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    ns: dict = {}
    exec(compile(module, AGG_SRC_PATH, "exec"), ns)
    return ns["_Bound"]


_Bound = _extract_helpers()


def _make_entity(hass):
    ent = _Bound.__new__(_Bound)
    ent.hass = hass
    entry = MagicMock()
    entry.options = {}
    entry.data = {"weather_entity": WEATHER_ENTITY}
    ent.entry = entry
    # _get_config is used by the helpers; provide the minimal impl.
    ent._get_config = lambda key, default=None: entry.options.get(
        key, entry.data.get(key, default)
    )
    return ent


def _make_hass(service_response=None, current_temp=89, service_side_effect=None):
    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()

    call_count = {"n": 0}

    async def _call(*args, **kwargs):
        call_count["n"] += 1
        if service_side_effect is not None:
            raise service_side_effect
        return service_response

    hass.services.async_call = _call
    hass._forecast_service_calls = call_count

    state = MagicMock()
    state.attributes = {"temperature": current_temp}
    hass.states.get = lambda eid: state if eid == WEATHER_ENTITY else None
    return hass


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. Service response drives day_offset lookup
# ---------------------------------------------------------------------------

def test_forecast_temp_uses_get_forecasts_service():
    hass = _make_hass(
        service_response={WEATHER_ENTITY: {"forecast": FAKE_FORECAST}}
    )
    ent = _make_entity(hass)
    _run(ent._refresh_forecast_cache())

    assert ent._get_forecast_temp(0) == 97
    assert ent._get_forecast_temp(1) == 98
    assert ent._get_forecast_temp_tomorrow() == 98
    assert ent._get_forecast_temp(0, field="templow") == 78


# ---------------------------------------------------------------------------
# 2. Fallback when service returns empty
# ---------------------------------------------------------------------------

def test_forecast_temp_falls_back_to_current_on_empty():
    hass = _make_hass(service_response={WEATHER_ENTITY: {"forecast": []}})
    ent = _make_entity(hass)
    _run(ent._refresh_forecast_cache())

    assert ent._get_forecast_temp(0) == 89
    assert ent._get_forecast_temp(1) == 89


def test_forecast_temp_falls_back_when_service_raises():
    hass = _make_hass(service_side_effect=RuntimeError("boom"))
    ent = _make_entity(hass)
    _run(ent._refresh_forecast_cache())

    assert ent._get_forecast_temp(0) == 89
    assert ent._get_forecast_temp(1) == 89


# ---------------------------------------------------------------------------
# 3. Cache: service is not called on every read
# ---------------------------------------------------------------------------

def test_forecast_fetch_is_cached():
    hass = _make_hass(
        service_response={WEATHER_ENTITY: {"forecast": FAKE_FORECAST}}
    )
    ent = _make_entity(hass)
    _run(ent._refresh_forecast_cache())
    _run(ent._refresh_forecast_cache())
    _run(ent._refresh_forecast_cache())
    assert hass._forecast_service_calls["n"] == 1

    # Age cache past TTL -> refresh again.
    cache = hass.data["universal_room_automation"]["_forecast_cache"]
    cache["time"] = cache["time"] - timedelta(
        seconds=_Bound.FORECAST_CACHE_TTL_S + 1
    )
    _run(ent._refresh_forecast_cache())
    assert hass._forecast_service_calls["n"] == 2


# ---------------------------------------------------------------------------
# 4. Source-level: every predicted-* async_update refreshes the cache
# ---------------------------------------------------------------------------

def test_predicted_async_updates_call_refresh():
    src = _agg_src()
    for cls in (
        "PredictedEnergyTodaySensor",
        "PredictedEnergyWeekSensor",
        "PredictedEnergyMonthSensor",
        "PredictedEnergyTomorrowSensor",
        "PredictedCostTodaySensor",
        "PredictedCostWeekSensor",
        "PredictedCostMonthSensor",
        "PredictedCostTomorrowSensor",
        "PredictedCoolingNeedSensor",
        "PredictedHeatingNeedSensor",
    ):
        idx = src.find(f"class {cls}")
        assert idx != -1, f"missing class {cls}"
        end = src.find("\nclass ", idx + 1)
        body = src[idx:end if end != -1 else len(src)]
        assert "await self._refresh_forecast_cache()" in body, (
            f"{cls} must refresh the forecast cache via async_update"
        )


def test_no_stale_forecast_attribute_reads():
    """Guard: the old `state.attributes.get('forecast', ...)` path must be
    gone — that attribute was removed in HA 2024.4."""
    src = _agg_src()
    assert 'attributes.get("forecast"' not in src, (
        "aggregation.py still reads the deprecated 'forecast' state attribute"
    )

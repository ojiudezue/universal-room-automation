"""Tests for the additive PredictedEnergyTomorrowSensor family (2026-07-27).

Additive display-only forecast for a dashboard "Net Tomorrow" tile.
Mirrors the today/week/month PredictedEnergy* pattern; adds a "tomorrow"
period to db.predict_energy that keys similar-day lookup on tomorrow's
weekday + tomorrow's forecast high temp.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# Bootstrap package path (mirrors test_data_pipeline.py:80-91).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

# Reuse the homeassistant.* stub bootstrap from test_data_pipeline (avoids
# duplicating the ~50-line stub block; loading that module triggers its
# import-time sys.modules.setdefault calls).
import test_data_pipeline  # noqa: F401,E402  — side-effect import for HA stubs


# ---------------------------------------------------------------------------
# D1: sensor class exists + is registered in the aggregation setup list
# ---------------------------------------------------------------------------


def _agg_src() -> str:
    with open(os.path.join(_ura_path, "aggregation.py")) as f:
        return f.read()


def test_predicted_energy_tomorrow_registers():
    """PredictedEnergyTomorrowSensor + PredictedCostTomorrowSensor must be
    defined AND appear in the aggregation setup entity list so they get
    added to Home Assistant on entry setup."""
    src = _agg_src()
    assert "class PredictedEnergyTomorrowSensor" in src
    assert "class PredictedCostTomorrowSensor" in src
    # Registered in the setup list (same block as the today/week/month family).
    assert "PredictedEnergyTomorrowSensor(hass, entry)" in src
    assert "PredictedCostTomorrowSensor(hass, entry)" in src
    # Unique ID / entity ID contract for the dashboard tile.
    assert 'f"{DOMAIN}_predicted_energy_tomorrow"' in src
    assert 'f"{DOMAIN}_predicted_cost_tomorrow"' in src


def test_predicted_energy_tomorrow_uses_tomorrow_forecast_helper():
    """Sensor async_update must source temp via _get_forecast_temp_tomorrow
    (NOT the today helper) and call db.predict_energy with period='tomorrow'."""
    src = _agg_src()
    # Isolate the class body.
    idx = src.find("class PredictedEnergyTomorrowSensor")
    end = src.find("\nclass ", idx + 1)
    body = src[idx:end]
    assert "_get_forecast_temp_tomorrow()" in body, (
        "must use the tomorrow forecast helper, not the today one"
    )
    assert 'db.predict_energy("tomorrow"' in body
    # Sanity: does NOT accidentally call the today path.
    assert 'db.predict_energy("day"' not in body


# ---------------------------------------------------------------------------
# D2: db.predict_energy("tomorrow") keys on tomorrow's weekday
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_predict_energy_tomorrow_targets_tomorrows_weekday(tmp_path):
    """The "tomorrow" period must pass (now + 1 day).weekday() to
    get_energy_for_similar_days, not now.weekday(). This is the core
    guarantee that distinguishes tomorrow's forecast from today's."""
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )

    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)
    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)
    hass.async_create_background_task = _sched
    hass.async_create_task = _sched
    db = UniversalRoomDatabase(hass)

    # Bypass data-sufficiency + similar-days DB reads; capture the day_of_week
    # argument that predict_energy passes downstream.
    captured: dict = {}

    async def _fake_days():
        return 60  # > MIN_DATA_DAYS_PREDICTION

    async def _fake_similar(day_of_week, temp_low, temp_high, limit=10):
        captured["day_of_week"] = day_of_week
        captured["temp_low"] = temp_low
        captured["temp_high"] = temp_high
        # Return 3+ rows with varying net_energy so the mean/stdev path succeeds.
        return [
            {"net_energy": 20.0, "grid_import": 25, "solar_export": 5, "avg_temp": 75, "avg_occupancy": 3},
            {"net_energy": 22.0, "grid_import": 27, "solar_export": 5, "avg_temp": 76, "avg_occupancy": 3},
            {"net_energy": 24.0, "grid_import": 29, "solar_export": 5, "avg_temp": 77, "avg_occupancy": 3},
        ]

    db.get_days_of_energy_data = _fake_days
    db.get_energy_for_similar_days = _fake_similar

    value, confidence = _run(db.predict_energy("tomorrow", forecast_temp=75.0))

    assert value is not None, "3 seeded similar days should yield a prediction"
    assert confidence > 0
    expected_dow = (datetime.utcnow() + timedelta(days=1)).weekday()
    assert captured["day_of_week"] == expected_dow, (
        f"predict_energy('tomorrow') must key on tomorrow's weekday "
        f"({expected_dow}), got {captured['day_of_week']}"
    )
    # Temp window is tomorrow's forecast +/- 10.
    assert captured["temp_low"] == 65.0
    assert captured["temp_high"] == 85.0


def test_predict_energy_day_still_uses_today_weekday(tmp_path):
    """Regression guard: the existing 'day' period MUST still key on today's
    weekday (the 'tomorrow' addition is purely additive)."""
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )

    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)
    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)
    hass.async_create_background_task = _sched
    hass.async_create_task = _sched
    db = UniversalRoomDatabase(hass)

    captured: dict = {}

    async def _fake_days():
        return 60

    async def _fake_similar(day_of_week, temp_low, temp_high, limit=10):
        captured["day_of_week"] = day_of_week
        return [
            {"net_energy": 10.0}, {"net_energy": 11.0}, {"net_energy": 12.0},
        ]

    db.get_days_of_energy_data = _fake_days
    db.get_energy_for_similar_days = _fake_similar

    _run(db.predict_energy("day", forecast_temp=75.0))
    assert captured["day_of_week"] == datetime.utcnow().weekday()

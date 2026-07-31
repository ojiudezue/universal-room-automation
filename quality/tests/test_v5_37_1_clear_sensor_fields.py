"""v5.37.1 — generalized clear-checkbox pattern on the room-options
`sensors` step.

v5.37.0 shipped `clear_water_leak_sensor` as a single BooleanSelector to
work around the unclearable optional single-entity EntitySelector pattern
(current-value default + empty-submission rejection + omission-refill).
v5.37.1 consolidates that mechanism across all four single-entity
optional selectors on the step (temperature, humidity, illuminance,
water_leak) into ONE multi-select `clear_sensor_fields` control.

Save-handler contract (unchanged shape, extended coverage):
  - "temperature" in clear_sensor_fields → merged[CONF_TEMPERATURE_SENSOR] = ""
  - "humidity"    → merged[CONF_HUMIDITY_SENSOR] = ""
  - "illuminance" → merged[CONF_ILLUMINANCE_SENSOR] = ""
  - "water_leak"  → merged[CONF_WATER_LEAK_SENSOR] = ""
  - Any other options / sensor values preserved via {**options, **user_input}
  - Empty selection (default) → nothing cleared

Tests drive the REAL async_step_sensors save-handler code path (no reimpls).
"""

from __future__ import annotations

import importlib

_cbcf = importlib.import_module("test_cycle_b_config_flow")

_make_options_flow = _cbcf._make_options_flow
_schema_field = _cbcf._schema_field

import pytest

# Import const via the same path the harness uses (avoids the URA
# package __init__.py chain which needs a live HA install).
from const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_HUMIDITY_SENSOR,
    CONF_ILLUMINANCE_SENSOR,
    CONF_MOTION_SENSORS,
    CONF_TEMPERATURE_SENSOR,
    CONF_WATER_LEAK_SENSOR,
    ENTRY_TYPE_ROOM,
)


def _submit(**overrides):
    """Minimal user_input for the sensors step (needs at least one
    occupancy sensor to pass the guard)."""
    user_input = {
        CONF_MOTION_SENSORS: ["binary_sensor.motion_test"],
    }
    user_input.update(overrides)
    return user_input


class TestClearSensorFieldsSave:
    """The save-handler translates `clear_sensor_fields` selections into
    explicit empty-string options overrides for the paired CONF keys."""

    @pytest.mark.asyncio
    async def test_clear_temperature_only(self):
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={
                CONF_TEMPERATURE_SENSOR: "sensor.room_temp",
                CONF_HUMIDITY_SENSOR: "sensor.room_hum",
                CONF_ILLUMINANCE_SENSOR: "sensor.room_lux",
                CONF_WATER_LEAK_SENSOR: "binary_sensor.room_leak",
            },
        )
        result = await flow.async_step_sensors(user_input=_submit(
            clear_sensor_fields=["temperature"],
        ))
        assert result["type"] == "create_entry"
        data = result["data"]
        # Cleared field written as EMPTY (options wins the merge over data).
        assert data[CONF_TEMPERATURE_SENSOR] == ""
        # Others preserved.
        assert data[CONF_HUMIDITY_SENSOR] == "sensor.room_hum"
        assert data[CONF_ILLUMINANCE_SENSOR] == "sensor.room_lux"
        assert data[CONF_WATER_LEAK_SENSOR] == "binary_sensor.room_leak"
        # UI-only control not persisted.
        assert "clear_sensor_fields" not in data

    @pytest.mark.asyncio
    async def test_clear_multiple_fields(self):
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={
                CONF_TEMPERATURE_SENSOR: "sensor.room_temp",
                CONF_HUMIDITY_SENSOR: "sensor.room_hum",
                CONF_ILLUMINANCE_SENSOR: "sensor.room_lux",
                CONF_WATER_LEAK_SENSOR: "binary_sensor.room_leak",
            },
        )
        result = await flow.async_step_sensors(user_input=_submit(
            clear_sensor_fields=["humidity", "illuminance", "water_leak"],
        ))
        assert result["type"] == "create_entry"
        data = result["data"]
        assert data[CONF_TEMPERATURE_SENSOR] == "sensor.room_temp"
        assert data[CONF_HUMIDITY_SENSOR] == ""
        assert data[CONF_ILLUMINANCE_SENSOR] == ""
        assert data[CONF_WATER_LEAK_SENSOR] == ""

    @pytest.mark.asyncio
    async def test_no_clear_selection_preserves_all(self):
        """Empty/absent clear list → no fields cleared."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={
                CONF_TEMPERATURE_SENSOR: "sensor.room_temp",
                CONF_HUMIDITY_SENSOR: "sensor.room_hum",
                CONF_ILLUMINANCE_SENSOR: "sensor.room_lux",
                CONF_WATER_LEAK_SENSOR: "binary_sensor.room_leak",
            },
        )
        result = await flow.async_step_sensors(user_input=_submit(
            clear_sensor_fields=[],
        ))
        assert result["type"] == "create_entry"
        data = result["data"]
        assert data[CONF_TEMPERATURE_SENSOR] == "sensor.room_temp"
        assert data[CONF_HUMIDITY_SENSOR] == "sensor.room_hum"
        assert data[CONF_ILLUMINANCE_SENSOR] == "sensor.room_lux"
        assert data[CONF_WATER_LEAK_SENSOR] == "binary_sensor.room_leak"

    @pytest.mark.asyncio
    async def test_unknown_clear_value_ignored(self):
        """Unknown value in the list is silently ignored (defensive)."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={CONF_TEMPERATURE_SENSOR: "sensor.room_temp"},
        )
        result = await flow.async_step_sensors(user_input=_submit(
            clear_sensor_fields=["bogus"],
        ))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_TEMPERATURE_SENSOR] == "sensor.room_temp"


class TestClearSensorFieldsSchema:
    """The schema exposes `clear_sensor_fields` and no longer exposes the
    legacy `clear_water_leak_sensor` checkbox (superseded)."""

    @pytest.mark.asyncio
    async def test_schema_exposes_clear_sensor_fields(self):
        flow = _make_options_flow(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM})
        result = await flow.async_step_sensors(user_input=None)
        assert _schema_field(result, "clear_sensor_fields") is not None

    @pytest.mark.asyncio
    async def test_schema_drops_legacy_water_leak_checkbox(self):
        flow = _make_options_flow(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM})
        result = await flow.async_step_sensors(user_input=None)
        assert _schema_field(result, "clear_water_leak_sensor") is None

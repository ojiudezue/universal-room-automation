"""HVAC Batch D fix-up 1 — the Fan Mode field in the REAL config / options
flows (review items M33 / A5, M34, M35).

Drives ``UniversalRoomAutomationOptionsFlow.async_step_climate`` and
``UniversalRoomAutomationConfigFlow.async_step_climate`` (pattern:
``test_hvac_vacancy_hold_ui_defaults``) and the module helper
``_zone_name_has_thermostat``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.universal_room_automation import config_flow as _cf
from custom_components.universal_room_automation.const import (
    CONF_ROOM_FAN_MODE,
    CONF_ZONE,
    FAN_MODE_FOLLOW_THERMOSTAT as FOLLOW,
    FAN_MODE_OFF as OFF,
    FAN_MODE_ROOM_TEMPERATURE as ROOMT,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _StubEntry:
    def __init__(self, options=None, data=None, entry_id="r1"):
        self.entry_id = entry_id
        self.options = dict(options or {})
        self.data = dict(data or {})


def _hass_with_zones(zones: dict):
    zm = MagicMock()
    zm.data = {"entry_type": "zone_manager"}
    zm.options = {"zones": zones}
    hass = MagicMock()
    hass.config_entries.async_entries = lambda domain=None: [zm]
    return hass


_IN_ZONE = {"Upstairs": {"zone_thermostat": "climate.up", "zone_rooms": ["r1"]}}
_NO_ZONE = {"Upstairs": {"zone_thermostat": "climate.up", "zone_rooms": ["other"]}}


def _options_flow(options, zones):
    flow = _cf.UniversalRoomAutomationOptionsFlow(_StubEntry(options=options))
    flow.hass = _hass_with_zones(zones)
    return flow


def _fan_mode_field(result):
    for marker, value in result["data_schema"].schema.items():
        if getattr(marker, "schema", None) == CONF_ROOM_FAN_MODE:
            default = marker.default() if callable(marker.default) else marker.default
            options = [o["value"] for o in value.config["options"]]
            return default, options
    raise AssertionError("room_fan_mode not in the climate schema")


# ---------------------------------------------------------------------------
# M33 — options form: offered modes + not-in-zone fallback display
# ---------------------------------------------------------------------------

def test_options_form_in_zone_offers_three_modes_and_shows_stored():
    flow = _options_flow({CONF_ROOM_FAN_MODE: FOLLOW}, _IN_ZONE)
    default, options = _fan_mode_field(_run(flow.async_step_climate(None)))
    assert options == [FOLLOW, ROOMT, OFF]
    assert default == FOLLOW


def test_options_form_not_in_zone_shows_room_temperature_for_stored_follow():
    flow = _options_flow({CONF_ROOM_FAN_MODE: FOLLOW}, _NO_ZONE)
    default, options = _fan_mode_field(_run(flow.async_step_climate(None)))
    assert options == [ROOMT, OFF]
    assert default == ROOMT


# ---------------------------------------------------------------------------
# A5 — saving the unchanged not-in-zone display keeps the stored value
# ---------------------------------------------------------------------------

def _submit(flow, mode):
    captured = {}

    def _create(*, title, data):
        captured.update(data)
        return {"type": "create_entry", "data": data}

    flow.async_create_entry = _create
    _run(flow.async_step_climate({CONF_ROOM_FAN_MODE: mode}))
    return captured


def test_options_save_keeps_stored_follow_outside_a_zone():
    flow = _options_flow({CONF_ROOM_FAN_MODE: FOLLOW}, _NO_ZONE)
    saved = _submit(flow, ROOMT)
    assert saved[CONF_ROOM_FAN_MODE] == FOLLOW


def test_options_save_writes_the_chosen_mode_normally():
    flow = _options_flow({CONF_ROOM_FAN_MODE: FOLLOW}, _IN_ZONE)
    assert _submit(flow, ROOMT)[CONF_ROOM_FAN_MODE] == ROOMT
    flow2 = _options_flow({CONF_ROOM_FAN_MODE: FOLLOW}, _NO_ZONE)
    assert _submit(flow2, OFF)[CONF_ROOM_FAN_MODE] == OFF


# ---------------------------------------------------------------------------
# M34 — `_zone_name_has_thermostat` (new-room flow: no entry id yet)
# ---------------------------------------------------------------------------

def test_zone_name_has_thermostat():
    hass = _hass_with_zones({
        "Upstairs": {"zone_thermostat": "climate.up"},
        "Patio": {},
    })
    assert _cf._zone_name_has_thermostat(hass, "Upstairs") is True
    assert _cf._zone_name_has_thermostat(hass, "Patio") is False
    assert _cf._zone_name_has_thermostat(hass, "Nowhere") is False
    assert _cf._zone_name_has_thermostat(hass, None) is False


# ---------------------------------------------------------------------------
# M35 — new-room flow: speed step only for "Room temperature"; offered modes
# ---------------------------------------------------------------------------

def _config_flow(zone_name, zones):
    flow = _cf.UniversalRoomAutomationConfigFlow()
    flow.hass = _hass_with_zones(zones)
    flow._data = {CONF_ZONE: zone_name}
    flow.async_step_fan_speeds = AsyncMock(return_value={"step_id": "fan_speeds"})
    flow.async_step_sleep_protection = AsyncMock(return_value={"step_id": "sleep"})
    return flow


@pytest.mark.parametrize("mode,step", [
    (ROOMT, "fan_speeds"), (FOLLOW, "sleep"), (OFF, "sleep"),
])
def test_new_room_speed_step_only_for_room_temperature(mode, step):
    flow = _config_flow("Upstairs", {"Upstairs": {"zone_thermostat": "climate.up"}})
    result = _run(flow.async_step_climate({CONF_ROOM_FAN_MODE: mode}))
    assert result["step_id"] == step
    assert flow._data[CONF_ROOM_FAN_MODE] == mode


def test_new_room_form_offers_follow_only_with_a_thermostat_zone():
    flow = _config_flow("Upstairs", {"Upstairs": {"zone_thermostat": "climate.up"}})
    default, options = _fan_mode_field(_run(flow.async_step_climate(None)))
    assert options == [FOLLOW, ROOMT, OFF] and default == OFF
    flow2 = _config_flow("Patio", {"Patio": {}})
    _d, options2 = _fan_mode_field(_run(flow2.async_step_climate(None)))
    assert options2 == [ROOMT, OFF]

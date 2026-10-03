"""Shared helpers for ROOM-TYPE-TRIMMED-MENU-1 tests.

Drive the REAL ``UniversalRoomAutomationOptionsFlow`` handlers (pattern:
test_hvac_batch_d_config_flow) with a stub entry + MagicMock hass.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import voluptuous as vol

from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    ENTRY_TYPE_ROOM,
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class StubEntry:
    def __init__(self, data=None, options=None, entry_id="r1"):
        self.entry_id = entry_id
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.title = "Room"


def make_hass():
    hass = MagicMock()
    hass.config_entries.async_entries = lambda domain=None: []
    hass.services.async_services = lambda: {}
    hass.states.async_entity_ids = lambda domain=None: []
    hass.states.get = lambda eid: None
    return hass


def make_flow(room_type=None, data=None, options=None, adv=False):
    base = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Room"}
    if room_type is not None:
        base[CONF_ROOM_TYPE] = room_type
    base.update(data or {})
    flow = cf.UniversalRoomAutomationOptionsFlow(StubEntry(data=base, options=options))
    flow.hass = make_hass()
    flow.context = {"show_advanced_options": adv}
    return flow


def menu(flow):
    return run(flow.async_step_init())["menu_options"]


def schema_keys(result, top_level_only=False) -> set:
    """Keys rendered by a form result (descends into sections)."""
    schema = result["data_schema"]
    if top_level_only:
        return {getattr(m, "schema", m) for m in schema.schema}
    return set(cf._collect_schema_defaults(schema))


def render(flow, step):
    return run(getattr(flow, f"async_step_{step}")(None))


def owned_keys(flow, step) -> tuple[set, dict]:
    if step in cf._MENU_ONLY_ROOM_STEPS:
        defaults: dict = {}
    else:
        defaults = run(flow._render_step_schema(step))
        assert defaults is not None, f"factory render of {step} failed"
    return flow._step_owned_keys(step, defaults), defaults


def nondefault(default):
    """A value that differs from ``default`` (render does not validate)."""
    if isinstance(default, bool):
        return not default
    if isinstance(default, (int, float)):
        return default + 7
    if isinstance(default, list):
        return ["sensor.seeded"]
    if isinstance(default, dict):
        return {"k": "v"}
    if isinstance(default, str) and default:
        return default + "_seeded"
    if default is vol.UNDEFINED or default is None or default == "":
        return "sensor.seeded"
    return "sensor.seeded"

"""FORM-CONDITIONAL-FIELDS-1 (D2) — shared harness for the form tests.

Renders the REAL step handlers of both flows with stub entries and a
MagicMock hass (pattern: ``_room_menu_helpers``), and builds what the HA
frontend submits for a form:

1. each field's marker ``default`` (or ``suggested_value``), walking sections;
2. section fields nested under their section key, as the frontend does;
3. a second variant that OMITS every section dict (never expanded).

``visible=`` omission (D2 step 3) ships with release 2; release 1 has no
``visible`` marker, so nothing is omitted for it.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import voluptuous as vol

from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE_MANAGER,
    ROOM_TYPE_BEDROOM,
)

COMP = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"
STRING_FILES = ("strings.json", "translations/en.json")


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class StubEntry:
    def __init__(self, data=None, options=None, entry_id="e1"):
        self.entry_id = entry_id
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.title = "Entry"


def make_hass():
    hass = MagicMock()
    hass.config_entries.async_entries = lambda domain=None: []
    hass.services.async_services = lambda: {}
    hass.states.async_entity_ids = lambda domain=None: []
    hass.states.get = lambda eid: None
    hass.states.async_all = lambda domain=None: []
    return hass


ENTRY_DATA = {
    "room": {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Room",
             CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM},
    "integration": {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION},
    "cm": {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER},
    "zm": {CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER, "zones": {"Z": {}}},
}


def options_flow(kind, options=None, data=None, hass=None):
    base = dict(ENTRY_DATA[kind])
    base.update(data or {})
    flow = cf.UniversalRoomAutomationOptionsFlow(StubEntry(data=base, options=options))
    flow.hass = hass or make_hass()
    flow.context = {}
    flow._selected_zone_name = "Z"
    return flow


def config_flow(data=None):
    flow = cf.UniversalRoomAutomationConfigFlow() if hasattr(
        cf, "UniversalRoomAutomationConfigFlow") else cf.ConfigFlow()
    flow.hass = make_hass()
    flow.context = {}
    flow._data = dict(data or {CONF_ROOM_NAME: "Room", CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM})
    return flow


def walk(schema, section=None, out=None) -> dict:
    """{field_key: section_key_or_None} for a step schema."""
    out = {} if out is None else out
    for marker, val in cf._schema_items(schema).items():
        key = str(getattr(marker, "schema", marker))
        if cf._is_section(val):
            walk(val.schema, key, out)
        else:
            out[key] = section
    return out


def _form(result, step):
    return (
        isinstance(result, dict)
        and result.get("step_id") == step
        and result.get("data_schema") is not None
        and str(result.get("type")).endswith("form")
    )


def render_all() -> dict:
    """{(flow, step): {key: section}} for every step that renders a form."""
    out: dict = {}
    oflow_names = sorted(
        n for n in dir(cf.UniversalRoomAutomationOptionsFlow) if n.startswith("async_step_")
    )
    for kind in ENTRY_DATA:
        for name in oflow_names:
            step = name[len("async_step_"):]
            if ("options", step) in out:
                continue
            try:
                res = run(getattr(options_flow(kind), name)(None))
            except Exception:  # noqa: BLE001 — a step that needs more context
                continue
            if _form(res, step):
                out[("options", step)] = walk(res["data_schema"])
    cfl = config_flow()
    cflow_cls = type(cfl)
    for name in sorted(n for n in dir(cflow_cls) if n.startswith("async_step_")):
        step = name[len("async_step_"):]
        try:
            res = run(getattr(config_flow(), name)(None))
        except Exception:  # noqa: BLE001
            continue
        if _form(res, step):
            out[("config", step)] = walk(res["data_schema"])
    return out


def load_strings():
    return {rel: json.loads((COMP / rel).read_text()) for rel in STRING_FILES}


def label_of(blob, flow, step, key, section):
    st = blob[flow]["step"].get(step, {})
    if section:
        sec = st.get("sections", {}).get(section)
        if not isinstance(sec, dict):
            return None, None
        return sec.get("data", {}).get(key), sec.get("data_description", {}).get(key)
    return st.get("data", {}).get(key), st.get("data_description", {}).get(key)


# --- D2 harness: what the frontend submits --------------------------------

def _marker_value(marker):
    default = getattr(marker, "default", vol.UNDEFINED)
    if default is not vol.UNDEFINED:
        return default() if callable(default) else default
    desc = getattr(marker, "description", None)
    if isinstance(desc, dict) and desc.get("suggested_value") not in (None, vol.UNDEFINED):
        return desc["suggested_value"]
    return vol.UNDEFINED


def frontend_submit(schema, *, omit_sections: bool = False) -> dict:
    """What the frontend sends for an untouched form.

    Fields with a value are nested under their section key; a field with
    no default / suggested value is left out (an untouched empty field).
    ``omit_sections=True`` leaves every section dict out (never expanded).
    """
    out: dict = {}
    for marker, val in cf._schema_items(schema).items():
        key = str(getattr(marker, "schema", marker))
        if cf._is_section(val):
            if omit_sections:
                continue
            inner = frontend_submit(val.schema)
            out[key] = inner
            continue
        v = _marker_value(marker)
        if v is not vol.UNDEFINED:
            out[key] = v
    return out


_PKG = "custom_components.universal_room_automation"


def real_ura():
    """The REAL integration package (another test file may have parked a bare
    stub in ``sys.modules``; same recipe as test_zone_house_advanced_fields)."""
    import importlib
    import sys

    cached = sys.modules.get(_PKG)
    if cached is not None and hasattr(cached, "_async_update_listener"):
        return cached
    saved = {k: v for k, v in sys.modules.items()
             if k == _PKG or k.startswith(_PKG + ".")}
    parent = sys.modules.get("custom_components")
    _missing = object()
    saved_attr = getattr(parent, "universal_room_automation", _missing)
    for k in saved:
        del sys.modules[k]
    try:
        real = importlib.import_module(_PKG)
    finally:
        for k in [k for k in sys.modules if k == _PKG or k.startswith(_PKG + ".")]:
            del sys.modules[k]
        sys.modules.update(saved)
        # The import bound the REAL package as an attribute of the shared
        # ``custom_components`` package; ``import a.b.c as x`` resolves via
        # that attribute, so put the previous binding back (no leak into
        # later files).
        if parent is not None:
            if saved_attr is _missing:
                try:
                    delattr(parent, "universal_room_automation")
                except AttributeError:
                    pass
            else:
                parent.universal_room_automation = saved_attr
    return real


class ReloadCounter:
    """A config-entries fake that applies HA core's write rule and drives the
    REAL ``_async_update_listener``.

    HA only calls update listeners when the options actually change
    (homeassistant/config_entries.py:2470-2480 on HA 2026.2.3). Every
    ``async_reload`` the listener schedules is counted.
    """

    def __init__(self, entry):
        self.ura = real_ura()
        self.entry = entry
        self.reloads = 0
        self.hass = MagicMock()
        snapshot_key = {
            "room": "room_last_applied_options",
            "integration": "integration_last_applied_options",
            "cm": "cm_last_applied_options",
        }
        self.hass.data = {self.ura.DOMAIN: {
            v: {entry.entry_id: dict(entry.options)} for v in snapshot_key.values()
        }}

        def _reload(entry_id):
            self.reloads += 1
            return None

        self.hass.config_entries.async_reload = _reload
        self.hass.async_create_task = lambda coro, *a, **k: (
            coro.close() if hasattr(coro, "close") else None
        )

    def save(self, new_options: dict) -> None:
        if dict(self.entry.options) == dict(new_options):
            return  # HA core short-circuit: no listener runs
        self.entry.options = dict(new_options)
        orig = self.ura._dispatch_integration_key_signals
        self.ura._dispatch_integration_key_signals = lambda h, e, keys: set(keys)
        try:
            run(self.ura._async_update_listener(self.hass, self.entry))
        finally:
            self.ura._dispatch_integration_key_signals = orig


def section_keys(schema) -> set:
    return {
        str(getattr(m, "schema", m))
        for m, v in cf._schema_items(schema).items() if cf._is_section(v)
    }

"""Shared harness for the presence provenance-split cycle test modules.

Mirrors the bootstrap pattern at the top of
``quality/tests/test_presence_coordinator.py`` so the new test modules
can ``from _provenance_harness import ...`` without duplicating the
~120-line homeassistant-mocking preamble.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
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
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
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

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        existing = sys.modules.get(_name)
        if existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for k, v in _attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in (
    "signals", "house_state", "base", "coordinator_diagnostics",
    "manager", "presence",
):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)


def make_hass():
    """Return a MagicMock HomeAssistant with the bare minimum surface."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.states.async_all.return_value = []
    hass.states.get = MagicMock(return_value=None)
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries.return_value = []
    return hass


def fake_room_entry(room_name: str, **conf):
    """Build a mock ConfigEntry returning ENTRY_TYPE_ROOM data for room_name.

    conf supports any of CONF_MMWAVE_SENSORS / CONF_MOTION_SENSORS /
    CONF_OCCUPANCY_SENSORS / CONF_FANS.
    """
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
    )
    entry = MagicMock()
    entry.data = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
        CONF_ROOM_NAME: room_name,
        **conf,
    }
    entry.options = {}
    entry.entry_id = f"entry_{room_name}"
    return entry

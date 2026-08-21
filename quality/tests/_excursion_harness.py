"""Shared HA-mock + URA-module bootstrap for the excursion cycle tests.

Import-time side effect: registers Home Assistant mock modules into
sys.modules so the URA HVAC modules load, then force-loads them.
Idempotent — repeat imports are no-op.

Fixes C-H2 (test-order fragility). Pre-cycle, individual excursion test
files imported ``test_hvac_excursion_lease_ac14_behavioural`` (or
``test_override_arrester_ttl_suppression``) purely for its module-level
harness side effects. Collecting the tests in a different order (e.g.
alphabetical on some platforms) put the depended-on file second, its
harness code hadn't run, and 7 collection errors cascaded while
pytest's exit status still went to 0 for the run that reported "green".

This helper collapses that chain: one bootstrap, one place, no test
file depends on another for HA mocks or module identity.

Not a test module (leading underscore) so pytest collection ignores it.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock


_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."),
)
_URA_ROOT = os.path.join(
    _PROJECT_ROOT, "custom_components", "universal_room_automation",
)


def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _install_ha_mocks() -> None:
    """Register HA mocks if not already present. add-once semantics —
    a real HA install or a prior sibling's mock is left alone."""
    _identity = lambda fn: fn  # noqa: E731

    def _parse_dt(s):
        if not isinstance(s, str):
            return None
        try:
            return datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    _mocks = {
        "homeassistant": {},
        "homeassistant.core": {
            "HomeAssistant": MagicMock, "callback": _identity,
            "Event": MagicMock, "State": MagicMock, "CALLBACK_TYPE": object,
        },
        "homeassistant.config_entries": {"ConfigEntry": MagicMock},
        "homeassistant.const": {
            "SERVICE_TURN_ON": "turn_on", "SERVICE_TURN_OFF": "turn_off",
            "STATE_ON": "on", "STATE_OFF": "off",
            "STATE_UNAVAILABLE": "unavailable", "STATE_UNKNOWN": "unknown",
        },
        "homeassistant.helpers": {},
        "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
        "homeassistant.helpers.entity": {
            "DeviceInfo": dict, "EntityCategory": MagicMock(),
        },
        "homeassistant.helpers.entity_platform": {
            "AddEntitiesCallback": MagicMock,
        },
        "homeassistant.helpers.event": {
            "async_track_state_change_event": MagicMock(),
            "async_track_time_interval": lambda hass, cb, interval: MagicMock(),
            "async_call_later": lambda hass, delay, cb: MagicMock(),
        },
        "homeassistant.helpers.dispatcher": {
            "async_dispatcher_connect": lambda hass, s, c: MagicMock(),
            "async_dispatcher_send": lambda hass, s, d=None: None,
        },
        "homeassistant.helpers.storage": {"Store": MagicMock},
        "homeassistant.helpers.update_coordinator": {
            "DataUpdateCoordinator": MagicMock, "UpdateFailed": Exception,
        },
        "homeassistant.helpers.selector": MagicMock(),
        "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
        "homeassistant.helpers.sun": {"is_up": lambda hass: True},
        "homeassistant.util": {},
        "homeassistant.util.dt": {
            "utcnow": lambda: datetime.now(timezone.utc),
            "now": lambda: datetime.now(timezone.utc),
            "as_local": lambda d: d,
            "parse_datetime": _parse_dt,
        },
        "homeassistant.components": {},
        "homeassistant.components.recorder": {"get_instance": MagicMock()},
        "homeassistant.components.recorder.history": {
            "get_significant_states": MagicMock(),
        },
        "homeassistant.components.sensor": {
            "SensorEntity": type("SensorEntity", (), {}),
            "SensorDeviceClass": MagicMock(), "SensorStateClass": MagicMock(),
        },
        "homeassistant.components.binary_sensor": {
            "BinarySensorEntity": type("BinarySensorEntity", (), {}),
            "BinarySensorDeviceClass": MagicMock(),
        },
        "homeassistant.components.button": {
            "ButtonEntity": type("ButtonEntity", (), {}),
        },
    }
    for name, attrs in _mocks.items():
        existing = sys.modules.get(name)
        if existing is None:
            if isinstance(attrs, dict):
                sys.modules[name] = _mock_module(name, **attrs)
            else:
                sys.modules[name] = attrs
        elif isinstance(existing, types.ModuleType) and isinstance(attrs, dict):
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)

    sys.modules.setdefault("aiosqlite", MagicMock())


def _install_ura_package_shells() -> None:
    if "custom_components" not in sys.modules:
        pkg = _mock_module("custom_components")
        pkg.__path__ = [os.path.join(_PROJECT_ROOT, "custom_components")]
        sys.modules["custom_components"] = pkg
    else:
        existing = sys.modules["custom_components"]
        if not getattr(existing, "__path__", None):
            existing.__path__ = [os.path.join(_PROJECT_ROOT, "custom_components")]

    ura_name = "custom_components.universal_room_automation"
    if ura_name not in sys.modules:
        pkg = _mock_module(ura_name)
        pkg.__file__ = os.path.join(_URA_ROOT, "__init__.py")
        pkg.__path__ = [_URA_ROOT]
        sys.modules[ura_name] = pkg
    else:
        existing = sys.modules[ura_name]
        if not getattr(existing, "__path__", None):
            existing.__path__ = [_URA_ROOT]
        if not getattr(existing, "__file__", None):
            existing.__file__ = os.path.join(_URA_ROOT, "__init__.py")

    dc_name = f"{ura_name}.domain_coordinators"
    if dc_name not in sys.modules:
        pkg = _mock_module(dc_name)
        pkg.__file__ = os.path.join(_URA_ROOT, "domain_coordinators", "__init__.py")
        pkg.__path__ = [os.path.join(_URA_ROOT, "domain_coordinators")]
        sys.modules[dc_name] = pkg


def _real_load(full_name: str, rel_path: str) -> types.ModuleType:
    """Force a real load of a URA submodule; reuse if already real-loaded."""
    existing = sys.modules.get(full_name)
    if (
        existing is not None
        and isinstance(existing, types.ModuleType)
        and isinstance(getattr(existing, "__file__", None), str)
        and os.path.isfile(existing.__file__)
    ):
        return existing
    path = os.path.join(_URA_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(full_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_BOOTSTRAPPED = False


def bootstrap():
    """Idempotent one-shot bootstrap. Returns the loaded module handles."""
    global _BOOTSTRAPPED
    _install_ha_mocks()
    _install_ura_package_shells()

    _real_load(
        "custom_components.universal_room_automation.const",
        "const.py",
    )
    _real_load(
        "custom_components.universal_room_automation.domain_coordinators.house_state",
        "domain_coordinators/house_state.py",
    )
    _real_load(
        "custom_components.universal_room_automation.fan_veto",
        "fan_veto.py",
    )
    for leaf, rel in [
        ("signals", "domain_coordinators/signals.py"),
        ("hvac_const", "domain_coordinators/hvac_const.py"),
        ("base", "domain_coordinators/base.py"),
        ("hvac_zones", "domain_coordinators/hvac_zones.py"),
        ("hvac_fans", "domain_coordinators/hvac_fans.py"),
        ("hvac_covers", "domain_coordinators/hvac_covers.py"),
        ("hvac_egress", "domain_coordinators/hvac_egress.py"),
        ("hvac_preset", "domain_coordinators/hvac_preset.py"),
        ("hvac_setpoint", "domain_coordinators/hvac_setpoint.py"),
        ("hvac_override", "domain_coordinators/hvac_override.py"),
        ("hvac_predict", "domain_coordinators/hvac_predict.py"),
        ("hvac_excursion", "domain_coordinators/hvac_excursion.py"),
    ]:
        _real_load(
            f"custom_components.universal_room_automation.domain_coordinators.{leaf}",
            rel,
        )
    _real_load(
        "custom_components.universal_room_automation.domain_coordinators.hvac",
        "domain_coordinators/hvac.py",
    )
    _BOOTSTRAPPED = True

    return {
        "hvac": sys.modules[
            "custom_components.universal_room_automation.domain_coordinators.hvac"
        ],
        "hvac_override": sys.modules[
            "custom_components.universal_room_automation.domain_coordinators.hvac_override"
        ],
        "hvac_predict": sys.modules[
            "custom_components.universal_room_automation.domain_coordinators.hvac_predict"
        ],
        "hvac_egress": sys.modules[
            "custom_components.universal_room_automation.domain_coordinators.hvac_egress"
        ],
        "hvac_excursion": sys.modules[
            "custom_components.universal_room_automation.domain_coordinators.hvac_excursion"
        ],
    }

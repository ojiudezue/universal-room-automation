"""Composition-safe bootstrap for tests that import `energy.py`.

D3 (PLANNING_energy_pause_release_hygiene.md): the v5.15.0 cycle could
not import `energy.py` from tests because the quality-suite HA stubs
lacked `homeassistant.helpers.dispatcher.async_dispatcher_connect` /
`async_dispatcher_send` (added by v5.12.0 substrate resubscribe). This
module installs the missing stubs plus the minimal siblings `energy.py`
depends on, guarded against re-execution and scoped so other test
files' bootstraps are not clobbered.

Usage (from a test file):

    from _energy_bootstrap import bootstrap_energy_imports
    bootstrap_energy_imports()
    from custom_components.universal_room_automation.domain_coordinators \
        import energy  # noqa: E402

The bootstrap is idempotent — safe to call from multiple test files in
the same pytest process.
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


_BOOTSTRAPPED = False


def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _identity(fn):  # HA callback decorator stand-in
    return fn


def bootstrap_energy_imports() -> None:
    """Install HA stubs required to import `energy.py`. Idempotent."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    # Dispatch-recording sink so tests can assert on sent signals.
    dispatched: list[tuple[str, tuple]] = []

    def _async_dispatcher_connect(hass, signal, target):
        # Return a no-op unsubscribe callable — matches HA contract shape.
        return lambda: None

    def _async_dispatcher_send(hass, signal, *args):
        dispatched.append((signal, args))

    # Preserve any existing homeassistant modules from other test bootstraps.
    def _set_if_missing(name: str, mod: types.ModuleType) -> None:
        sys.modules.setdefault(name, mod)

    _set_if_missing("homeassistant", _mock_module("homeassistant"))
    _set_if_missing("homeassistant.core", _mock_module(
        "homeassistant.core",
        HomeAssistant=MagicMock,
        callback=_identity,
    ))
    _set_if_missing("homeassistant.config_entries", _mock_module(
        "homeassistant.config_entries", ConfigEntry=MagicMock,
    ))
    _set_if_missing("homeassistant.const", _mock_module("homeassistant.const"))
    _set_if_missing("homeassistant.helpers", _mock_module("homeassistant.helpers"))

    # Dispatcher stub — the D3 gap. Install missing symbols on any
    # existing stub without clobbering other tests' additions.
    disp = sys.modules.get("homeassistant.helpers.dispatcher")
    if disp is None:
        disp = _mock_module("homeassistant.helpers.dispatcher")
        sys.modules["homeassistant.helpers.dispatcher"] = disp
    if not hasattr(disp, "async_dispatcher_connect"):
        disp.async_dispatcher_connect = _async_dispatcher_connect
    if not hasattr(disp, "async_dispatcher_send"):
        disp.async_dispatcher_send = _async_dispatcher_send
    if not hasattr(disp, "dispatcher_connect"):
        disp.dispatcher_connect = _async_dispatcher_connect
    if not hasattr(disp, "dispatcher_send"):
        disp.dispatcher_send = _async_dispatcher_send
    # Expose the recorded-sends buffer so tests can inspect it.
    disp._test_dispatched = dispatched  # noqa: SLF001

    _set_if_missing("homeassistant.helpers.device_registry", _mock_module(
        "homeassistant.helpers.device_registry", DeviceInfo=dict,
    ))
    _set_if_missing("homeassistant.helpers.entity", _mock_module(
        "homeassistant.helpers.entity",
        DeviceInfo=dict, EntityCategory=MagicMock(),
    ))
    _set_if_missing("homeassistant.helpers.entity_platform", _mock_module(
        "homeassistant.helpers.entity_platform", AddEntitiesCallback=MagicMock,
    ))
    # event helper — energy.py uses async_track_time_interval
    ev = sys.modules.get("homeassistant.helpers.event")
    if ev is None:
        ev = _mock_module("homeassistant.helpers.event")
        sys.modules["homeassistant.helpers.event"] = ev
    if not hasattr(ev, "async_track_time_interval"):
        ev.async_track_time_interval = lambda hass, cb, interval: (lambda: None)
    if not hasattr(ev, "async_call_later"):
        ev.async_call_later = lambda hass, delay, cb: (lambda: None)
    if not hasattr(ev, "async_track_state_change_event"):
        ev.async_track_state_change_event = lambda hass, entities, cb: (lambda: None)
    if not hasattr(ev, "async_track_point_in_time"):
        ev.async_track_point_in_time = lambda hass, cb, when: (lambda: None)

    _set_if_missing("homeassistant.helpers.update_coordinator", _mock_module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=MagicMock, UpdateFailed=Exception,
    ))
    _set_if_missing("homeassistant.helpers.selector",
                    _mock_module("homeassistant.helpers.selector"))
    _set_if_missing("homeassistant.helpers.entity_registry", _mock_module(
        "homeassistant.helpers.entity_registry", async_get=MagicMock(),
    ))
    _set_if_missing("homeassistant.helpers.sun",
                    _mock_module("homeassistant.helpers.sun"))
    _set_if_missing("homeassistant.helpers.restore_state", _mock_module(
        "homeassistant.helpers.restore_state", RestoreEntity=object,
    ))
    _set_if_missing("homeassistant.util", _mock_module("homeassistant.util"))

    _set_if_missing("homeassistant.util.dt", _mock_module(
        "homeassistant.util.dt",
        utcnow=lambda: datetime.now(timezone.utc),
        now=lambda: datetime.now(),
        as_local=lambda dt: dt,
        parse_datetime=lambda s: (
            datetime.fromisoformat(s) if s else None
        ),
        UTC=timezone.utc,
    ))
    _set_if_missing("homeassistant.components",
                    _mock_module("homeassistant.components"))
    _set_if_missing("homeassistant.components.sensor", _mock_module(
        "homeassistant.components.sensor",
        SensorEntity=type("SensorEntity", (), {}),
        SensorDeviceClass=MagicMock(),
        SensorStateClass=MagicMock(),
    ))
    _set_if_missing("homeassistant.components.binary_sensor", _mock_module(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=type("BinarySensorEntity", (), {}),
        BinarySensorDeviceClass=MagicMock(),
    ))
    _set_if_missing("homeassistant.components.button", _mock_module(
        "homeassistant.components.button",
        ButtonEntity=type("ButtonEntity", (), {}),
    ))

    sys.modules.setdefault("aiosqlite", MagicMock())

    # Build package hierarchy so relative imports resolve.
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", ".."),
    )
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    cc = sys.modules.get("custom_components")
    if cc is None or not hasattr(cc, "__path__"):
        cc = types.ModuleType("custom_components")
        cc.__path__ = [os.path.join(project_root, "custom_components")]
        sys.modules["custom_components"] = cc

    ura_name = "custom_components.universal_room_automation"
    ura = sys.modules.get(ura_name)
    if ura is None or not hasattr(ura, "__path__"):
        ura = types.ModuleType(ura_name)
        ura_path = os.path.join(cc.__path__[0], "universal_room_automation")
        ura.__path__ = [ura_path]
        ura.__package__ = ura_name
        sys.modules[ura_name] = ura

    _BOOTSTRAPPED = True

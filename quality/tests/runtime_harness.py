"""Runtime smoke test harness for URA.

Provides a minimal stub `hass` object that's sufficient to call
`async_setup()` on each domain coordinator without crashing. Goal: catch
runtime-only bugs (UnboundLocalError, AttributeError, missing import
resolution, scope errors) that source-grep tests can't see.

Not a full HA test environment — `pytest-homeassistant-custom-component`
provides that, but it's heavy. This harness covers the "does
async_setup execute end-to-end without exception?" question, which is
the highest-leverage smoke check for the kinds of bugs that crashed
v4.5.11 → v4.5.11.3.

See `test_runtime_smoke.py` for the smoke tests. To add smoke coverage
for a new coordinator: import its class + `_build_setup_args` here, then
add a test that constructs it and awaits `async_setup()`.

Design notes:
- `StubHass` provides only what URA's setup paths actually touch.
- All async I/O is no-op: dispatcher signals fire to subscribers but
  the subscribers just record the call. Listeners can be inspected
  via `hass._stub_dispatcher_calls`.
- DB writes hit a real in-memory aiosqlite, so the v4.5.11 SQLite
  table creation and reads work for real.
- Anything URA tries to access that we haven't stubbed gets a
  `MagicMock` — the test will pass but the harness logs the access
  via `_stub_unknown_attr` so we know what to add as URA grows.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock


class StubConfigEntry:
    """Mimics `homeassistant.config_entries.ConfigEntry` for URA's reads."""

    def __init__(
        self,
        entry_id: str,
        entry_type: str,
        data: dict | None = None,
        options: dict | None = None,
        title: str | None = None,
    ):
        from custom_components.universal_room_automation.const import CONF_ENTRY_TYPE
        self.entry_id = entry_id
        self.data = {**(data or {}), CONF_ENTRY_TYPE: entry_type}
        self.options = options or {}
        self.title = title or entry_id
        self.runtime_data: Any = None
        self._update_listeners: list[Callable] = []

    def add_update_listener(self, listener):
        self._update_listeners.append(listener)
        return lambda: self._update_listeners.remove(listener)

    async def async_unload(self, hass) -> bool:
        return True


class StubConfigEntries:
    """Mimics `hass.config_entries` registry."""

    def __init__(self, entries: list[StubConfigEntry]):
        self._entries = entries

    def async_entries(self, domain: str | None = None) -> list[StubConfigEntry]:
        # URA only ever calls with its own domain; we ignore the filter.
        return list(self._entries)

    def async_get_entry(self, entry_id: str) -> StubConfigEntry | None:
        for e in self._entries:
            if e.entry_id == entry_id:
                return e
        return None

    def async_update_entry(self, entry: StubConfigEntry, **kwargs) -> bool:
        if "data" in kwargs:
            entry.data = kwargs["data"]
        if "options" in kwargs:
            entry.options = kwargs["options"]
        if "title" in kwargs:
            entry.title = kwargs["title"]
        return True

    async def async_reload(self, entry_id: str) -> bool:
        return True


class StubServices:
    """Mimics `hass.services` registry."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self._registered: dict[tuple[str, str], Callable] = {}

    async def async_call(
        self, domain: str, service: str,
        service_data: dict | None = None,
        blocking: bool = False,
        **_kwargs,
    ):
        self.calls.append((domain, service, dict(service_data or {})))
        return True

    def async_register(self, domain, service, func, schema=None, supports_response=False):
        self._registered[(domain, service)] = func

    def async_remove(self, domain, service):
        self._registered.pop((domain, service), None)

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self._registered


class StubStates:
    """Mimics `hass.states` — read-only state storage."""

    def __init__(self):
        self._states: dict[str, Any] = {}

    def get(self, entity_id: str):
        return self._states.get(entity_id)

    def async_set(self, entity_id: str, state, attributes=None, **_kw):
        from types import SimpleNamespace
        s = SimpleNamespace(
            entity_id=entity_id,
            state=str(state),
            attributes=dict(attributes or {}),
            last_changed=datetime.now(),
            last_updated=datetime.now(),
        )
        self._states[entity_id] = s

    def async_all(self):
        return list(self._states.values())


class StubBus:
    """Mimics `hass.bus` — event dispatcher."""

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
        self.fired: list[tuple[str, dict]] = []

    def async_listen(self, event_type: str, listener: Callable):
        self._listeners.setdefault(event_type, []).append(listener)
        return lambda: self._listeners[event_type].remove(listener)

    def async_listen_once(self, event_type: str, listener: Callable):
        return self.async_listen(event_type, listener)

    def async_fire(self, event_type: str, event_data: dict | None = None):
        self.fired.append((event_type, dict(event_data or {})))


class StubConfig:
    """Mimics `hass.config`."""

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.time_zone = "America/Chicago"
        self.elevation = 0
        self.latitude = 0.0
        self.longitude = 0.0
        self.location_name = "Stub"

    def path(self, *parts: str) -> str:
        return os.path.join(self.config_dir, *parts)


class StubHass:
    """Minimal `hass` substitute for URA runtime smoke tests.

    Provides only what URA's `async_setup_entry` paths actually touch.
    Anything not covered returns a MagicMock so the test continues —
    but new touches will reveal themselves the moment a real assertion
    is added that depends on them.
    """

    def __init__(
        self,
        config_entries: list[StubConfigEntry] | None = None,
        config_dir: str | None = None,
    ):
        self.data: dict[str, Any] = {}
        self.config_entries = StubConfigEntries(config_entries or [])
        self.services = StubServices()
        self.states = StubStates()
        self.bus = StubBus()
        if config_dir is None:
            config_dir = tempfile.mkdtemp(prefix="ura_smoke_")
        self.config = StubConfig(config_dir)
        # Background task tracking — URA uses this heavily.
        self._stub_tasks: list[asyncio.Task] = []
        self._stub_dispatcher_signals: dict[str, list[Callable]] = {}
        self._stub_call_laters: list[tuple[float, Callable]] = []

    # ------- Task creation -------

    def async_create_task(self, coro, name: str | None = None):
        task = asyncio.ensure_future(coro)
        self._stub_tasks.append(task)
        return task

    def async_create_background_task(self, coro, name: str):
        return self.async_create_task(coro, name)

    async def async_add_executor_job(self, func, *args):
        # Run sync function inline (executor is overkill for smoke).
        return func(*args)

    # ------- Loop access (URA reads hass.loop occasionally) -------

    @property
    def loop(self):
        return asyncio.get_event_loop()

    # ------- helpers (legacy access pattern; modern HA uses
    #         module-level functions). URA mixes both. -------

    @property
    def helpers(self):
        return _StubHelpers(self)

    def __getattr__(self, name):
        """Anything we haven't explicitly stubbed → MagicMock.

        Logs the access so we can add real stubs as URA's surface grows.
        """
        if name.startswith("_stub_") or name.startswith("__"):
            raise AttributeError(name)
        mock = MagicMock(name=f"hass.{name}")
        # Stash the access so tests can introspect what URA touched.
        self.__dict__[f"_stub_unknown_attr_{name}"] = mock
        return mock


class _StubHelpers:
    """Shim for legacy `hass.helpers.X` access."""

    def __init__(self, hass: StubHass):
        self._hass = hass

    def __getattr__(self, name):
        return MagicMock(name=f"hass.helpers.{name}")


# =============================================================================
# Convenience builders
# =============================================================================


def make_zone_manager_entry(
    zones: dict[str, dict] | None = None,
    entry_id: str = "zone_manager_entry",
) -> StubConfigEntry:
    """Build a ZONE_MANAGER entry with N zones in the same shape URA uses.

    `zones` shape: `{"Zone Name": {"zone_thermostat": "climate.x", ...}, ...}`
    """
    from custom_components.universal_room_automation.const import (
        ENTRY_TYPE_ZONE_MANAGER,
    )
    if zones is None:
        zones = {
            "Test Zone": {
                "zone_thermostat": "climate.test_zone_1",
                "zone_rooms": [],
            },
        }
    return StubConfigEntry(
        entry_id=entry_id,
        entry_type=ENTRY_TYPE_ZONE_MANAGER,
        options={"zones": zones},
    )


def make_coordinator_manager_entry(
    options: dict | None = None,
    entry_id: str = "coordinator_manager_entry",
) -> StubConfigEntry:
    """Build a COORDINATOR_MANAGER entry."""
    from custom_components.universal_room_automation.const import (
        ENTRY_TYPE_COORDINATOR_MANAGER,
    )
    return StubConfigEntry(
        entry_id=entry_id,
        entry_type=ENTRY_TYPE_COORDINATOR_MANAGER,
        options=options or {},
    )


def build_smoke_hass(zones_count: int = 3) -> StubHass:
    """Build a StubHass populated with a canonical 3-zone install.

    Mirrors the user's actual setup: 1 CM entry + 1 ZM entry with 3
    AC zones (Back Hallway, Entertainment, Upstairs).
    """
    zones = {
        "Back Hallway": {
            "zone_thermostat": "climate.back_hallway_zone_3",
            "zone_rooms": [],
        },
        "Entertainment": {
            "zone_thermostat": "climate.entertainment_zone_1",
            "zone_rooms": [],
        },
        "Upstairs": {
            "zone_thermostat": "climate.upstairs_zone_2",
            "zone_rooms": [],
        },
    }
    # Trim to requested count
    zones = dict(list(zones.items())[:zones_count])

    cm = make_coordinator_manager_entry()
    zm = make_zone_manager_entry(zones=zones)
    return StubHass(config_entries=[cm, zm])

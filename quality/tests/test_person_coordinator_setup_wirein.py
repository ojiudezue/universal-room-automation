"""Wire-in anchor: the integration entry's REAL `async_setup_entry` builds the
person coordinator through `_async_start_person_coordinator` (fleet-memory
Store load before the first refresh; PLANNING_ble_rearm_and_fleet_fraction
rev 2 §2.2 MEDIUM-2, review C finding 1).

Drives `async_setup_entry` on the runtime harness's StubHass. The helper is
replaced by a recorder that raises a BaseException sentinel (setup's
`except Exception` blocks cannot swallow it), so setup stops exactly at the
person-coordinator site. Reverting the call site to the old inline
construct + first refresh (or deleting it) means the recorder is never
reached -> RED.
"""
from __future__ import annotations

import asyncio
import importlib

import pytest

pytest.importorskip("homeassistant.helpers.frame")

from runtime_harness import StubConfigEntry, StubHass  # noqa: E402


class _Reached(BaseException):
    pass


@pytest.fixture(autouse=True)
def _real_homeassistant_modules():
    """Order-independence: earlier files may leave hand-made stubs of
    `homeassistant.*` modules (e.g. a `homeassistant.helpers.event` without
    `async_track_time_change`) in sys.modules. For this test only, swap any
    non-file-backed homeassistant module for the real one, then put back
    exactly what was there (scoped, restored)."""
    import sys
    from unittest.mock import Mock

    def _stub(mod):
        f = getattr(mod, "__file__", None)
        return isinstance(mod, Mock) or not (isinstance(f, str) and f.endswith(".py"))

    pkg = "custom_components.universal_room_automation"

    def _ours(n):
        return n == pkg or n.startswith(pkg + ".")

    def _ha(n):
        return n == "homeassistant" or n.startswith("homeassistant.")

    # HA stubs are swapped for the real modules; the URA package is always
    # re-imported fresh against them (siblings leave partial URA stubs too).
    saved = {n: m for n, m in sys.modules.items()
             if (_ha(n) and _stub(m)) or _ours(n)}
    for n in saved:
        sys.modules.pop(n, None)
    before = set(sys.modules)
    try:
        importlib.import_module("homeassistant.helpers.event")
        importlib.import_module(pkg)
        yield
    finally:
        for n in set(sys.modules) - before:
            if _ha(n) or _ours(n):
                sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_setup_entry_starts_person_coordinator_via_helper(monkeypatch):
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    calls = []

    async def _recorder(hass, entry):
        calls.append(entry)
        raise _Reached()

    monkeypatch.setattr(init_mod, "_async_start_person_coordinator", _recorder)
    wd = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._loop_stall_watchdog"
    )
    monkeypatch.setattr(wd, "install", lambda _hass: None)
    hass = StubHass()
    entry = StubConfigEntry(
        "integ", const.ENTRY_TYPE_INTEGRATION,
        data={const.CONF_TRACKED_PERSONS: ["person.oji_udezue"]},
    )
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_setup_entry(hass, entry))
    assert calls == [entry]


@pytest.mark.parametrize("given, want", [
    (["person.oji_udezue", "person.ziri"], ["Oji Udezue", "Ziri"]),  # options form
    (["Oji Udezue", "ezinne"], ["Oji Udezue", "Ezinne"]),  # display / bare name
])
def test_setup_entry_rewrites_tracked_persons_to_display_names(monkeypatch, given, want):
    """PERSON-AWARENESS-READ-API-1 RA9: setup converts the tracked_persons
    entries to display names through person_ids.display_of before the person
    coordinator starts; the result equals the old inline ``.title()`` rule
    for both config forms (hand-written oracle)."""
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    seen = []

    async def _recorder(hass, entry):
        seen.append(list(entry.data[const.CONF_TRACKED_PERSONS]))
        raise _Reached()

    monkeypatch.setattr(init_mod, "_async_start_person_coordinator", _recorder)
    wd = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._loop_stall_watchdog"
    )
    monkeypatch.setattr(wd, "install", lambda _hass: None)
    hass = StubHass()
    entry = StubConfigEntry(
        "integ", const.ENTRY_TYPE_INTEGRATION,
        data={const.CONF_TRACKED_PERSONS: list(given)},
    )
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_setup_entry(hass, entry))
    assert seen == [want]


def test_setup_entry_wires_census_ble_listeners_through_public_api(monkeypatch):
    """PERSON-AWARENESS-READ-API-1 RA6 wire-in anchor: setup registers the
    census BLE-transition listeners once and re-derives them on
    homeassistant_started, through the PUBLIC PersonCensus methods."""
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    calls = []

    class _FakeCensus:
        def __init__(self, hass, mgr):
            pass

        def register_ble_transition_listeners(self):
            calls.append("register")
            return []

        def refresh_ble_crossing_listeners(self):
            calls.append("refresh")
            return 0

    class _FakeMgr:
        def __init__(self, hass):
            pass

        async def async_discover(self, **_kw):
            return None

    async def _recorder(hass, entry):
        raise _Reached()

    monkeypatch.setattr(init_mod, "PersonCensus", _FakeCensus)
    monkeypatch.setattr(init_mod, "CameraIntegrationManager", _FakeMgr)
    monkeypatch.setattr(init_mod, "_async_start_person_coordinator", _recorder)
    wd = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._loop_stall_watchdog"
    )
    monkeypatch.setattr(wd, "install", lambda _hass: None)
    hass = StubHass()
    entry = StubConfigEntry(
        "integ", const.ENTRY_TYPE_INTEGRATION,
        data={const.CONF_TRACKED_PERSONS: ["person.oji_udezue"]},
    )
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_setup_entry(hass, entry))
    assert calls == ["register"]
    for cb in list(hass.bus._listeners.get("homeassistant_started", [])):
        cb(None)
    assert calls == ["register", "refresh"]

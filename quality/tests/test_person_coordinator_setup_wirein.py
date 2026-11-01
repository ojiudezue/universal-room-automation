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
# Scoped real-module fixture (autouse): siblings leave partial package stubs.
from test_person_gps_assistive import _real_modules  # noqa: E402,F401


class _Reached(BaseException):
    pass


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

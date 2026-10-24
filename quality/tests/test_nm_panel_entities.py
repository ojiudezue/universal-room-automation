"""Halo S1b D-S1b-4: panel channel entities + PresenceCoordinator.get_room_zone.

Runs in a CLEAN interpreter (subprocess) against the REAL Home Assistant
package and the REAL URA modules, because ~200 fake-HA test modules mutate
``homeassistant.*`` at import time in a full-suite process (see
test_runtime_smoke.py D4b). The subprocess script drives the real entity
classes: RestoreEntity last-state -> value -> pushed into a recording NM.
Only ``RestoreEntity.async_added_to_hass`` (registry plumbing) and
``async_write_ha_state`` are replaced inside the subprocess.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_SCRIPT = textwrap.dedent(r'''
    import asyncio, sys
    from types import SimpleNamespace
    sys.path.insert(0, ROOT)
    from homeassistant.helpers.restore_state import RestoreEntity
    from custom_components.universal_room_automation import nm_panel_entities as m
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    async def _noop(self):
        return None
    RestoreEntity.async_added_to_hass = _noop

    class NM:
        def __init__(self):
            self.enabled_calls = []
            self.ttl_calls = []
        async def async_set_panel_channel_enabled(self, v):
            self.enabled_calls.append(v)
        def set_panel_lease_ttl_min(self, v):
            self.ttl_calls.append(v)

    def make(cls, nm, last):
        hass = SimpleNamespace(data={"universal_room_automation": {"notification_manager": nm}})
        ent = cls(hass, SimpleNamespace(data={}, options={}))
        async def _last():
            return None if last is None else SimpleNamespace(state=last)
        ent.async_get_last_state = _last
        ent.async_write_ha_state = lambda: None
        return ent

    async def main():
        case = CASE
        if case == "switch":
            nm = NM(); sw = make(m.NMPanelChannelSwitch, nm, "on")
            assert sw.entity_id == "switch.ura_nm_panel_channel", sw.entity_id
            assert sw.unique_id == "universal_room_automation_nm_panel_channel"
            await sw.async_added_to_hass()
            assert sw.is_on is True and nm.enabled_calls == [True], nm.enabled_calls
            await sw.async_turn_off()
            assert sw.is_on is False and nm.enabled_calls == [True, False]
            nm2 = NM(); sw2 = make(m.NMPanelChannelSwitch, nm2, None)
            await sw2.async_added_to_hass()
            assert sw2.is_on is False and nm2.enabled_calls == [False]
        elif case == "number":
            nm = NM(); n = make(m.NMPanelLeaseTtlNumber, nm, "12")
            assert n.entity_id == "number.ura_nm_panel_lease_ttl_min", n.entity_id
            assert (n.native_min_value, n.native_max_value) == (1, 240)
            await n.async_added_to_hass()
            assert n.native_value == 12.0 and nm.ttl_calls == [12.0], nm.ttl_calls
            await n.async_set_native_value(45)
            assert nm.ttl_calls == [12.0, 45.0]
            for bad in ("unavailable", "500", None):
                nmb = NM(); nb = make(m.NMPanelLeaseTtlNumber, nmb, bad)
                await nb.async_added_to_hass()
                assert nb.native_value == 30.0 and nmb.ttl_calls == [30.0], (bad, nmb.ttl_calls)
        elif case == "zone":
            p = SimpleNamespace(_room_to_zone={"Kitchen": "Downstairs"})
            assert PresenceCoordinator.get_room_zone(p, "Kitchen") == "Downstairs"
            assert PresenceCoordinator.get_room_zone(p, "Master") is None
            assert PresenceCoordinator.get_room_zone(p, "") is None
        print("OK")

    asyncio.run(main())
''')


def _run(case: str) -> subprocess.CompletedProcess:
    script = _SCRIPT.replace("ROOT", repr(ROOT), 1).replace("CASE", repr(case), 1)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True,
        cwd=ROOT, env=env, timeout=120,
    )


@pytest.mark.parametrize("case", ["switch"])
def test_panel_switch_restores(case):
    res = _run(case)
    assert res.returncode == 0 and res.stdout.strip().endswith("OK"), res.stderr[-3000:]


@pytest.mark.parametrize("case", ["number"])
def test_panel_ttl_number_restores(case):
    res = _run(case)
    assert res.returncode == 0 and res.stdout.strip().endswith("OK"), res.stderr[-3000:]


def test_presence_get_room_zone_getter():
    res = _run("zone")
    assert res.returncode == 0 and res.stdout.strip().endswith("OK"), res.stderr[-3000:]

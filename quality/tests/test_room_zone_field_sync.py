"""ROOM-ZONE-FIELD-NO-SYNC-1 — room CONF_ZONE → ZM CONF_ZONE_ROOMS sync.

Problem: room setup wrote the room's CONF_ZONE but the ZM entry's per-zone
CONF_ZONE_ROOMS index (consumed by presence.py:3044, hvac_zones.py:270)
never learned about it — so newly-zoned rooms showed up as Unzoned on any
zone-side enumeration and the operator had to add them by hand.

Fix: `_sync_room_zone_to_zm` propagates room→ZM on both the room-
reconfigure save site (`async_step_basic_setup`) and at `async_setup_entry`
(covers the initial-create path + boot drift).

Tests below are MUTATION-ANCHORED: the wire-in test neuters the sync call
inside `async_step_basic_setup` and asserts the specific behavioral test
fails — a bare grep is not a wire-in test (see feedback_hollow_test_anchors).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import types
from unittest.mock import MagicMock

_cbcf = importlib.import_module("test_cycle_b_config_flow")
_cf = _cbcf._cf
_FakeConfigEntry = _cbcf._FakeConfigEntry
_make_options_flow = _cbcf._make_options_flow

# Constants — pulled from the already-loaded config_flow module (which
# imported them from .const at load time) to avoid executing the real
# `custom_components.universal_room_automation.__init__` (which pulls
# `homeassistant` and blows up under the mocked harness).
CONF_ENTRY_TYPE = _cf.CONF_ENTRY_TYPE
CONF_ROOM_NAME = _cf.CONF_ROOM_NAME
CONF_ZONE = _cf.CONF_ZONE
CONF_ZONE_ROOMS = _cf.CONF_ZONE_ROOMS
ENTRY_TYPE_ROOM = _cf.ENTRY_TYPE_ROOM
ENTRY_TYPE_ZONE_MANAGER = _cf.ENTRY_TYPE_ZONE_MANAGER


# ---------------------------------------------------------------------------
# Fake hass with a wired async_update_entry that records + mutates entries.
# ---------------------------------------------------------------------------

class _FakeEntries:
    def __init__(self, entries):
        self._entries = list(entries)
        self.updates = []  # (entry, data, options)

    def async_entries(self, _domain=None):
        return list(self._entries)

    def async_get_entry(self, entry_id):
        for e in self._entries:
            if e.entry_id == entry_id:
                return e
        return None

    def async_update_entry(self, entry, data=None, options=None, title=None):
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)
        if title is not None:
            entry.title = title
        self.updates.append((entry, data, options))
        return True


class _FakeHass:
    def __init__(self, entries):
        self.config_entries = _FakeEntries(entries)
        self.states = MagicMock()
        self.services = MagicMock()


def _room(entry_id, zone_name, name="Test Room"):
    return _FakeConfigEntry(
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: name,
            CONF_ZONE: zone_name,
        },
        options={CONF_ZONE: zone_name} if zone_name else {},
        entry_id=entry_id,
    )


def _zm_entry(zones_map):
    """zones_map: {zone_name: [room_entry_id, ...]}."""
    zones = {
        zn: {CONF_ZONE_ROOMS: list(rooms)}
        for zn, rooms in zones_map.items()
    }
    return _FakeConfigEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER},
        options={"zones": zones},
        entry_id="zm_entry",
    )


def _get_zm_rooms(zm, zone_name):
    return list(
        (zm.options.get("zones", {}) or {})
        .get(zone_name, {})
        .get(CONF_ZONE_ROOMS, [])
    )


# ---------------------------------------------------------------------------
# Direct helper tests — the arithmetic of the sync.
# ---------------------------------------------------------------------------

class TestSyncHelperArithmetic:
    def test_upsert_adds_room_to_new_zone(self):
        room = _room("room_a", "Zone1")
        zm = _zm_entry({"Zone1": [], "Zone2": []})
        hass = _FakeHass([room, zm])
        assert _cf._sync_room_zone_to_zm(hass, room, old_zone=None) is True
        assert _get_zm_rooms(zm, "Zone1") == ["room_a"]
        assert _get_zm_rooms(zm, "Zone2") == []

    def test_zone_change_moves_room(self):
        # Room now belongs to Zone2; ZM still has it in Zone1.
        room = _room("room_a", "Zone2")
        zm = _zm_entry({"Zone1": ["room_a"], "Zone2": []})
        hass = _FakeHass([room, zm])
        assert _cf._sync_room_zone_to_zm(hass, room, old_zone="Zone1") is True
        assert _get_zm_rooms(zm, "Zone1") == []
        assert _get_zm_rooms(zm, "Zone2") == ["room_a"]

    def test_none_zone_removes_from_all(self):
        room = _room("room_a", "")  # cleared
        zm = _zm_entry({"Zone1": ["room_a"], "Zone2": []})
        hass = _FakeHass([room, zm])
        assert _cf._sync_room_zone_to_zm(hass, room, old_zone="Zone1") is True
        assert _get_zm_rooms(zm, "Zone1") == []
        assert _get_zm_rooms(zm, "Zone2") == []

    def test_idempotent_when_already_in_sync(self):
        room = _room("room_a", "Zone1")
        zm = _zm_entry({"Zone1": ["room_a"], "Zone2": []})
        hass = _FakeHass([room, zm])
        assert _cf._sync_room_zone_to_zm(hass, room, old_zone="Zone1") is False
        assert hass.config_entries.updates == []

    def test_defensive_dedup_removes_stray_duplicates(self):
        # Room correctly in Zone1 per room.CONF_ZONE, but ZM has it BOTH
        # in Zone1 AND in Zone2 (drift). Sync must clear Zone2.
        room = _room("room_a", "Zone1")
        zm = _zm_entry({"Zone1": ["room_a"], "Zone2": ["room_a"]})
        hass = _FakeHass([room, zm])
        assert _cf._sync_room_zone_to_zm(hass, room, old_zone=None) is True
        assert _get_zm_rooms(zm, "Zone1") == ["room_a"]
        assert _get_zm_rooms(zm, "Zone2") == []

    def test_no_zm_entry_no_op(self):
        room = _room("room_a", "Zone1")
        hass = _FakeHass([room])
        assert _cf._sync_room_zone_to_zm(hass, room, old_zone=None) is False


# ---------------------------------------------------------------------------
# Wire-in anchor test — the reconfigure save site calls the sync.
#
# Mutation-anchored: this test PASSES with the wire-in in place, and FAILS
# (the ZM stays stale) if the `_sync_room_zone_to_zm(...)` call inside
# `async_step_basic_setup` is neutered. Verified by mutation drill in the
# build report.
# ---------------------------------------------------------------------------

class TestBasicSetupSaveWiresSync:
    def test_reconfigure_zone_change_propagates_to_zm(self):
        # Existing state: room is in Zone1 in both the room entry AND the ZM.
        pre_room = _room("room_a", "Zone1")
        zm = _zm_entry({"Zone1": ["room_a"], "Zone2": []})
        hass = _FakeHass([pre_room, zm])

        # Options flow bound to the pre_room entry.
        flow = _make_options_flow(
            data=dict(pre_room.data),
            options=dict(pre_room.options),
            hass=hass,
        )
        # Point the flow at the SAME entry object the fake registry sees so
        # async_update_entry mutations land on our reference.
        flow._config_entry = pre_room
        flow.async_abort = lambda **_kw: {"type": "abort"}

        # Operator submits a zone change Zone1 → Zone2.
        user_input = {
            CONF_ROOM_NAME: "Test Room",
            CONF_ZONE: "Zone2",
        }
        asyncio.new_event_loop().run_until_complete(
            flow.async_step_basic_setup(user_input)
        )
        # Room entry: CONF_ZONE now Zone2 in both data + options.
        assert pre_room.data.get(CONF_ZONE) == "Zone2"
        assert pre_room.options.get(CONF_ZONE) == "Zone2"
        # ZM: room moved out of Zone1 into Zone2.
        assert _get_zm_rooms(zm, "Zone1") == []
        assert _get_zm_rooms(zm, "Zone2") == ["room_a"]

    def test_no_zone_change_is_idempotent_on_zm(self):
        # Room already correctly in Zone1 in ZM; operator saves with no
        # zone change → no ZM write.
        pre_room = _room("room_a", "Zone1")
        zm = _zm_entry({"Zone1": ["room_a"]})
        hass = _FakeHass([pre_room, zm])

        flow = _make_options_flow(
            data=dict(pre_room.data),
            options=dict(pre_room.options),
            hass=hass,
        )
        flow._config_entry = pre_room
        flow.async_abort = lambda **_kw: {"type": "abort"}

        user_input = {
            CONF_ROOM_NAME: "Test Room",
            CONF_ZONE: "Zone1",
        }
        asyncio.new_event_loop().run_until_complete(
            flow.async_step_basic_setup(user_input)
        )
        # ZM entry received no update (only the room entry did).
        zm_updates = [u for u in hass.config_entries.updates if u[0] is zm]
        assert zm_updates == []

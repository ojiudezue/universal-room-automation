"""HVAC Batch D (v5.103.24) — the per-room "Fan Mode" select, its one-time
migration, and the options-flow dropdown.

Operator ruling (option C): ONE per-room Fan Mode replaces "Enable
HVAC-Managed Fans" + "Enable Comfort Fan Control":

    Follow thermostat -> HVAC tier       (only offered in an HVAC zone)
    Room temperature  -> room tier
    Off               -> nobody (person-owned)

The REAL production code is exercised without importing the heavy platform /
__init__ modules: the class / helper sources are extracted from the files and
exec'd against the REAL const module (the pattern
``test_room_rename_writethrough`` uses for ``__init__`` helpers). Wire-in of
those pieces into their platforms is pinned by source anchors at the bottom.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_URA = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)


def _load_const():
    name = "ura_batch_d_fanmode_const"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(_URA / "const.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load_const()
FOLLOW, ROOMT, OFF = (
    C.FAN_MODE_FOLLOW_THERMOSTAT, C.FAN_MODE_ROOM_TEMPERATURE, C.FAN_MODE_OFF,
)


def _extract(path: Path, start: str, end: str) -> str:
    src = path.read_text()
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


def _const_ns() -> dict:
    return {k: getattr(C, k) for k in dir(C) if not k.startswith("__")}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _Entry:
    def __init__(self, entry_id, data, options=None):
        self.entry_id = entry_id
        self.data = dict(data)
        self.options = dict(options or {})


class _ConfigEntries:
    """Holds the entries and applies async_update_entry like HA does."""

    def __init__(self, entries):
        self._entries = list(entries)

    def async_entries(self, domain=None):
        return list(self._entries)

    def async_update_entry(self, entry, *, data=None, options=None):
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)
        return True


def _zm_entry(zones: dict) -> _Entry:
    return _Entry("zm", {"entry_type": "zone_manager"}, {"zones": zones})


def _hass(entries):
    hass = MagicMock()
    hass.config_entries = _ConfigEntries(entries)
    return hass


# ---------------------------------------------------------------------------
# The select — the REAL RoomFanModeSelect class body.
# ---------------------------------------------------------------------------

class _BaseEntity:
    """Stand-in for UniversalRoomEntity: unique_id / name / hass only."""

    def __init__(self, coordinator, entity_type, name):
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{entity_type}"
        self._attr_name = name
        self.writes = 0

    def async_write_ha_state(self):
        self.writes += 1


def _select_cls():
    src = _extract(
        _URA / "select.py",
        "class RoomFanModeSelect(",
        "\n# ============================================================================\n"
        "# v3.6.0-c1: House State Override Selects",
    )
    ns = _const_ns()
    ns.update({
        "UniversalRoomEntity": _BaseEntity,
        "SelectEntity": object,
        "EntityCategory": MagicMock(),
        "_LOGGER": logging.getLogger("test.batch_d.select"),
    })
    exec(src, ns)  # noqa: S102
    return ns["RoomFanModeSelect"]


RoomFanModeSelect = _select_cls()


def _select_for(room_entry, zones):
    hass = _hass([_zm_entry(zones), room_entry])
    coord = MagicMock()
    coord.hass = hass
    coord.entry = room_entry
    return RoomFanModeSelect(coord), hass


_IN_ZONE = {"Upstairs": {"zone_thermostat": "climate.up", "zone_rooms": ["r1"]}}
_NO_ZONE = {"Patio": {"zone_rooms": ["r1"]}}  # a zone without a thermostat


def test_select_offers_follow_thermostat_only_in_an_hvac_zone():
    room = _Entry("r1", {"room_name": "Guest Bedroom 2"}, {C.CONF_ROOM_FAN_MODE: OFF})
    sel, _ = _select_for(room, _IN_ZONE)
    assert sel.options == [FOLLOW, ROOMT, OFF]
    sel2, _ = _select_for(room, _NO_ZONE)
    assert sel2.options == [ROOMT, OFF]
    assert sel._attr_unique_id == "r1_room_fan_mode"
    assert sel._attr_translation_key == "room_fan_mode"


@pytest.mark.parametrize("mode", [FOLLOW, ROOMT, OFF])
def test_select_shows_the_stored_mode(mode):
    room = _Entry("r1", {"room_name": "X"}, {C.CONF_ROOM_FAN_MODE: mode})
    sel, _ = _select_for(room, _IN_ZONE)
    assert sel.current_option == mode


def test_select_invalid_follow_thermostat_falls_back_to_room_temperature():
    """Room removed from its zone: the stored "Follow thermostat" shows as
    "Room temperature" (what the room tier runs) and is NOT rewritten, so
    re-adding the room to a zone restores it."""
    room = _Entry("r1", {"room_name": "X"}, {C.CONF_ROOM_FAN_MODE: FOLLOW})
    sel, _ = _select_for(room, _NO_ZONE)
    assert sel.current_option == ROOMT
    assert room.options[C.CONF_ROOM_FAN_MODE] == FOLLOW
    sel2, _ = _select_for(room, _IN_ZONE)
    assert sel2.current_option == FOLLOW


def test_select_rejects_follow_thermostat_outside_an_hvac_zone():
    room = _Entry("r1", {"room_name": "X"}, {C.CONF_ROOM_FAN_MODE: OFF})
    sel, _ = _select_for(room, _NO_ZONE)
    asyncio.new_event_loop().run_until_complete(sel.async_select_option(FOLLOW))
    assert room.options[C.CONF_ROOM_FAN_MODE] == OFF
    assert sel.writes == 0


def test_select_persists_across_restart():
    """The choice lives in the room entry's options: a NEW entity instance
    (what HA builds after a restart) reads it back."""
    room = _Entry("r1", {"room_name": "Guest Bedroom 2"}, {C.CONF_ROOM_FAN_MODE: FOLLOW})
    sel, _ = _select_for(room, _IN_ZONE)
    asyncio.new_event_loop().run_until_complete(sel.async_select_option(OFF))
    assert room.options[C.CONF_ROOM_FAN_MODE] == OFF
    assert sel.writes == 1
    after_restart, _ = _select_for(room, _IN_ZONE)
    assert after_restart.current_option == OFF
    # ...and every fan writer now reads the room as person-owned.
    assert C.fan_owner({**room.data, **room.options}) is None


# ---------------------------------------------------------------------------
# The one-time migration — the REAL __init__._migrate_room_fan_mode.
# ---------------------------------------------------------------------------

def _migrate_fn():
    src = _extract(
        _URA / "__init__.py",
        "def _migrate_room_fan_mode(",
        "\nasync def async_setup_entry(",
    )
    ns = _const_ns()
    ns.update({
        "HomeAssistant": object,
        "ConfigEntry": object,
        "_LOGGER": logging.getLogger("test.batch_d.migrate"),
    })
    exec(src, ns)  # noqa: S102
    return ns["_migrate_room_fan_mode"]


_migrate = _migrate_fn()

# The 12 fan rooms, hand-transcribed from the live `.storage`
# (core.config_entries, 2026-09-29): (data, options, in an HVAC zone).
# Every one sits in an HVAC zone. Expected = the operator's migration table.
LIVE_FAN_ROOMS = {
    "Study A": ({"hvac_coordination_enabled": True, "fan_control_enabled": True}, {"fan_control_enabled": True}, FOLLOW),
    "Guest Bedroom 2": ({"hvac_coordination_enabled": False, "fan_control_enabled": True}, {"fan_control_enabled": False}, OFF),
    "Living Room": ({"hvac_coordination_enabled": True, "fan_control_enabled": True}, {"fan_control_enabled": True}, FOLLOW),
    "Master Bedroom": ({"hvac_coordination_enabled": True, "fan_control_enabled": True}, {}, FOLLOW),
    "Guest Bedroom 1": ({"hvac_coordination_enabled": False, "fan_control_enabled": True}, {"fan_control_enabled": True}, ROOMT),
    "Breakfast Nook": ({"hvac_coordination_enabled": False, "fan_control_enabled": False}, {"fan_control_enabled": False}, OFF),
    "Kitchen": ({"hvac_coordination_enabled": True, "fan_control_enabled": True}, {"fan_control_enabled": True}, FOLLOW),
    "Game Room": ({"hvac_coordination_enabled": True, "fan_control_enabled": True}, {"fan_control_enabled": True}, FOLLOW),
    "Ziri Bedroom (Bedroom 5)": ({"hvac_coordination_enabled": False, "fan_control_enabled": True}, {"fan_control_enabled": False}, OFF),
    "Jaya Bedroom": ({"hvac_coordination_enabled": False, "fan_control_enabled": False}, {"fan_control_enabled": True}, ROOMT),
    "Media": ({"hvac_coordination_enabled": False, "fan_control_enabled": False}, {}, OFF),
    "Exercise Room": ({"hvac_coordination_enabled": False, "fan_control_enabled": False}, {"fan_control_enabled": False}, OFF),
}


def test_migration_of_the_live_fan_rooms():
    zone_rooms = [f"id_{n}" for n in LIVE_FAN_ROOMS]
    zm = _zm_entry({"All": {"zone_thermostat": "climate.z", "zone_rooms": zone_rooms}})
    rooms = {}
    for name, (data, opts, _exp) in LIVE_FAN_ROOMS.items():
        rooms[name] = _Entry(
            f"id_{name}",
            {"entry_type": "room", "room_name": name, **data}, opts,
        )
    hass = _hass([zm, *rooms.values()])
    got = {n: _migrate(hass, e) for n, e in rooms.items()}
    assert got == {n: exp for n, (_d, _o, exp) in LIVE_FAN_ROOMS.items()}
    for name, e in rooms.items():
        assert e.options[C.CONF_ROOM_FAN_MODE] == LIVE_FAN_ROOMS[name][2]
        # legacy keys left readable (one release)
        assert "hvac_coordination_enabled" in e.data


def test_migration_follow_becomes_room_temperature_outside_a_zone():
    room = _Entry("r9", {"entry_type": "room", "room_name": "Loft",
                         "hvac_coordination_enabled": True,
                         "fan_control_enabled": True})
    hass = _hass([_zm_entry({}), room])
    assert _migrate(hass, room) == ROOMT


def test_migration_is_one_time_and_skips_non_rooms():
    room = _Entry("r1", {"entry_type": "room", "room_name": "X",
                         "hvac_coordination_enabled": True},
                  {C.CONF_ROOM_FAN_MODE: OFF})
    hass = _hass([_zm_entry(_IN_ZONE), room])
    assert _migrate(hass, room) is None
    assert room.options[C.CONF_ROOM_FAN_MODE] == OFF
    zm = _zm_entry({})
    assert _migrate(_hass([zm]), zm) is None


def test_migration_keeps_a_fan_mode_stored_only_in_entry_data():
    """Fix-up 1 (HIGH): a NEW room's config flow writes Fan Mode into
    entry.DATA (no legacy toggles). The migration must not overwrite it
    with the legacy-derived "off"."""
    room = _Entry("r1", {"entry_type": "room", "room_name": "New",
                         C.CONF_ROOM_FAN_MODE: ROOMT})
    hass = _hass([_zm_entry(_IN_ZONE), room])
    assert _migrate(hass, room) is None
    assert C.CONF_ROOM_FAN_MODE not in room.options
    assert C.fan_owner({**room.data, **room.options}) == "room"


# ---------------------------------------------------------------------------
# Options-flow dropdown — the REAL config_flow._fan_mode_selector.
# ---------------------------------------------------------------------------

def test_options_flow_dropdown_lists_only_possible_modes():
    from homeassistant.helpers import selector  # real HA
    src = _extract(
        _URA / "config_flow.py",
        "def _fan_mode_selector(",
        "\ndef _zone_name_has_thermostat(",
    )
    ns = _const_ns()
    ns["selector"] = selector
    exec(src, ns)  # noqa: S102
    in_zone = ns["_fan_mode_selector"](True).config["options"]
    no_zone = ns["_fan_mode_selector"](False).config["options"]
    assert [o["value"] for o in in_zone] == [FOLLOW, ROOMT, OFF]
    assert [o["label"] for o in in_zone] == [
        "Follow thermostat", "Room temperature", "Off",
    ]
    assert [o["value"] for o in no_zone] == [ROOMT, OFF]


# ---------------------------------------------------------------------------
# Wire-in anchors (glue that is not cheaply drivable without HA setup).
# ---------------------------------------------------------------------------

def test_wire_in_anchors():
    select_src = (_URA / "select.py").read_text()
    assert "async_add_entities([RoomFanModeSelect(coordinator)])" in select_src
    init_src = (_URA / "__init__.py").read_text()
    setup = init_src[init_src.index("async def async_setup_entry("):]
    assert "_migrate_room_fan_mode(hass, entry)" in setup[:6000]
    suppress = init_src[init_src.index("_ROOM_SUPPRESS_KEYS: frozenset[str] = frozenset({"):]
    assert "_CONF_ROOM_FAN_MODE," in suppress[:3000]
    switch_src = (_URA / "switch.py").read_text()
    assert "RoomComfortFanControlSwitch(coordinator)" not in switch_src
    cf = (_URA / "config_flow.py").read_text()
    assert "CONF_ROOM_FAN_MODE, default=FAN_MODE_OFF," in cf
    assert "CONF_ROOM_FAN_MODE, default=_mode_now," in cf
    assert "vol.Optional(CONF_FAN_CONTROL_ENABLED" not in cf
    assert "vol.Optional(CONF_HVAC_COORDINATION_ENABLED" not in cf


def test_climate_automation_no_longer_gates_the_room_tier_fan_path():
    """Fix-up 1 (operator ruling 2026-09-29): the coordinator calls the
    room-tier temperature fan handler with NO enclosing Climate Automation
    gate — the Fan Mode (inside the handler) alone decides."""
    import ast
    src = (_URA / "coordinator.py").read_text()
    tree = ast.parse(src)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", None) == "handle_temperature_based_fan_control"
    ]
    assert calls, "the room-tier fan handler call site is gone"
    for call in calls:
        node = call
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.If):
                assert "climate_automation" not in ast.unparse(node.test)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                break
    assert "_is_climate_automation_enabled" not in src
    switch_src = (_URA / "switch.py").read_text()
    assert "ClimateAutomationSwitch(coordinator)" not in switch_src
    assert "class ClimateAutomationSwitch" not in switch_src


def test_fan_mode_select_is_enabled_by_default_with_an_icon():
    assert RoomFanModeSelect._attr_entity_registry_enabled_default is True
    assert RoomFanModeSelect._attr_icon == "mdi:fan-auto"


def test_migration_ignores_the_retired_climate_automation_switch():
    """The migration derives Fan Mode only from the two legacy toggles —
    never from the old Climate Automation switch (many were switched off on
    2026-09-29 as a stop-gap)."""
    src = _extract(
        _URA / "__init__.py",
        "def _migrate_room_fan_mode(",
        "\nasync def async_setup_entry(",
    )
    assert "climate_automation" not in src
    room = _Entry("r1", {"entry_type": "room", "room_name": "X",
                         "fan_control_enabled": True})
    hass = _hass([_zm_entry({}), room])
    hass.states.get = lambda eid: MagicMock(state="off")  # any switch "off"
    assert _migrate(hass, room) == ROOMT


def test_translations_carry_the_exact_labels():
    import json
    for rel in ("strings.json", "translations/en.json"):
        t = json.loads((_URA / rel).read_text())
        st = t["entity"]["select"]["room_fan_mode"]
        assert st["name"] == "Fan Mode"
        assert st["state"] == {
            "follow_thermostat": "Follow thermostat",
            "room_temperature": "Room temperature",
            "off": "Off",
        }
        opts_step = t["options"]["step"]["climate"]
        assert opts_step["data"]["room_fan_mode"] == "Fan mode"
        assert opts_step["data_description"]["room_fan_mode"].startswith(
            "Who controls this room's comfort fan"
        )
        assert "hvac_coordination_enabled" not in opts_step["data"]
        assert "fan_control_enabled" not in opts_step["data"]


def test_select_is_a_control_not_configuration():
    """Operator 2026-09-29: Fan Mode sits in the device page's Controls card
    (where Climate Automation was), so it must carry no entity_category."""
    room = _Entry("r1", {"room_name": "Guest Bedroom 2"}, {C.CONF_ROOM_FAN_MODE: OFF})
    sel, _ = _select_for(room, _IN_ZONE)
    assert sel._attr_entity_category is None

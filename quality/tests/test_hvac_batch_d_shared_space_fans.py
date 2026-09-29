"""HVAC Batch D fix-up 1 — B-M2 / A8 (OPERATOR-PENDING, separate commit).

The scheduled shared-space auto-off (`RoomAutomation._shared_space_turn_off_all`)
turned off the room's comfort fans regardless of the Fan Mode. Now:
  * Fan Mode "Off" (person-owned): the room's comfort fans are left alone;
  * a fan another room drives under "Follow thermostat" (Breakfast Nook ->
    Kitchen's shared fan) is never turned off by this room.
Lights and switches are unaffected. Drives the REAL method (private-package
loader: order-independent).
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_URA = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_batch_d_shared_pkg"


def _load():
    if f"{_PKG}.automation" not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    return (
        importlib.import_module(f"{_PKG}.const"),
        importlib.import_module(f"{_PKG}.automation"),
    )


C, A = _load()
SHARED = "fan.151732606487193_fan"


class _Entry:
    def __init__(self, name, mode, fans):
        self.entry_id = f"id_{name}"
        self.data = {"entry_type": "room", "room_name": name, "fans": list(fans)}
        self.options = {C.CONF_ROOM_FAN_MODE: mode}


def _room(name, mode, fans, others=()):
    hass = MagicMock()
    entries = [_Entry(name, mode, fans), *others]
    hass.config_entries.async_entries = lambda domain=None: list(entries)
    config = {
        "room_name": name, "fans": list(fans), "lights": ["light.l1"],
        C.CONF_ROOM_FAN_MODE: mode,
    }
    auto = A.RoomAutomation(hass=hass, config=config, coordinator=MagicMock())
    log: list = []

    async def _svc(domain, service, data=None, **kw):
        log.append((domain, service, dict(data or {})))

    auto._safe_service_call = _svc
    return auto, log


def _fan_offs(log):
    out = []
    for dom, svc, data in log:
        if svc != "turn_off":
            continue
        ids = data.get("entity_id")
        ids = ids if isinstance(ids, list) else [ids]
        out += [i for i in ids if i.startswith("fan.")]
    return out


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.parametrize("mode,expect_off", [
    (C.FAN_MODE_ROOM_TEMPERATURE, True),
    (C.FAN_MODE_FOLLOW_THERMOSTAT, True),
    (C.FAN_MODE_OFF, False),
])
def test_shared_space_auto_off_follows_fan_mode(mode, expect_off):
    auto, log = _room("Game Room", mode, ["fan.game"])
    _run(auto._shared_space_turn_off_all())
    assert (_fan_offs(log) == ["fan.game"]) is expect_off
    # lights are unaffected by the Fan Mode
    assert any(d == "light" and s == "turn_off" for d, s, _ in log)


def test_shared_space_auto_off_skips_another_rooms_hvac_owned_fan():
    """Breakfast Nook (Fan Mode "Room temperature" here, to prove the
    cross-room rule on its own) shares Kitchen's fan; Kitchen is "Follow
    thermostat" -> the nook's auto-off must not turn it off."""
    kitchen = _Entry("Kitchen", C.FAN_MODE_FOLLOW_THERMOSTAT, [SHARED])
    auto, log = _room(
        "Breakfast Nook", C.FAN_MODE_ROOM_TEMPERATURE, [SHARED, "fan.nook"],
        others=(kitchen,),
    )
    _run(auto._shared_space_turn_off_all())
    assert _fan_offs(log) == ["fan.nook"]


def test_shared_fan_is_turned_off_when_the_other_room_does_not_own_it():
    kitchen = _Entry("Kitchen", C.FAN_MODE_ROOM_TEMPERATURE, [SHARED])
    auto, log = _room(
        "Breakfast Nook", C.FAN_MODE_ROOM_TEMPERATURE, [SHARED],
        others=(kitchen,),
    )
    _run(auto._shared_space_turn_off_all())
    assert _fan_offs(log) == [SHARED]

"""FAN-RECHECK-FORM-RESTORE-REVERT-1 — options win over RestoreEntity at add.

An options-flow save reloads the entry; RestoreEntity dumps the pre-save
state on removal, so an unconditional restore in async_added_to_hass
reverts the just-saved form value (live: Garage A options False, switches
'on'). Fix: when the conf key is PRESENT in {**data, **options}, options
win; restore only covers the key-absent case.

Drives the REAL entity classes' async_added_to_hass (instances built via
__new__ to skip CoordinatorEntity wiring; only the HA base-class
async_added_to_hass hooks are no-op'd, scoped by monkeypatch).
Keys and values are hardcoded literals (not imported constants).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.universal_room_automation import switch as sw

DOMAIN = "universal_room_automation"

pytestmark = pytest.mark.asyncio


async def _noop(self):  # base-class add hooks
    return None


_SWITCHES = (
    sw.FanRecheckEnabledSwitch,
    sw.RoomFanRecheckEnabledSwitch,
    sw.RoomFanRecheckL2AllowedSwitch,
    sw._RoomBooleanOptionSwitch,
)


@pytest.fixture
def _no_base_hooks(monkeypatch):
    # Patch every base in each switch's actual MRO (robust to sibling test
    # files that stub homeassistant modules in sys.modules); scoped+restored.
    for cls in _SWITCHES:
        for base in cls.__mro__[1:]:
            if base is object or base in _SWITCHES:
                continue
            monkeypatch.setattr(base, "async_added_to_hass", _noop, raising=False)


def _entry(options, data=None):
    return SimpleNamespace(options=options, data=data or {})


def _last(state):
    async def _get():
        return None if state is None else SimpleNamespace(state=state)
    return _get


async def _add_master(options, restored):
    ent = sw.FanRecheckEnabledSwitch.__new__(sw.FanRecheckEnabledSwitch)
    ent.hass = SimpleNamespace(data={})
    ent._entry = _entry(options)
    ent._conf_key = "fan_recheck_enabled"
    ent._is_on = "SENTINEL"
    ent.async_get_last_state = _last(restored)
    ent.async_write_ha_state = MagicMock()
    await ent.async_added_to_hass()
    return ent


async def _add_room(cls, key, options, restored):
    ent = cls.__new__(cls)
    ent.coordinator = SimpleNamespace(entry=_entry(options))
    ent._conf_key = key
    ent._attr_is_on = "SENTINEL"
    ent.async_get_last_state = _last(restored)
    await ent.async_added_to_hass()
    return ent


# --- Site 1: FanRecheckEnabledSwitch (master) -------------------------------

@pytest.mark.parametrize("opt,restored", [(False, "on"), (True, "off")])
async def test_master_options_win_over_restore(_no_base_hooks, opt, restored):
    ent = await _add_master({"fan_recheck_enabled": opt}, restored)
    assert ent._is_on is opt
    assert ent.hass.data[DOMAIN]["fan_recheck_master_enabled"] is opt
    ent.async_write_ha_state.assert_called_once()


@pytest.mark.parametrize("restored,expected", [("on", True), ("off", False)])
async def test_master_restore_when_key_absent(_no_base_hooks, restored, expected):
    ent = await _add_master({}, restored)
    assert ent._is_on is expected
    assert ent.hass.data[DOMAIN]["fan_recheck_master_enabled"] is expected


# --- Sites 2-4: per-room switches --------------------------------------------

_ROOM_CASES = [
    pytest.param(sw.RoomFanRecheckEnabledSwitch, "room_fan_recheck_enabled",
                 id="room_enabled"),
    pytest.param(sw.RoomFanRecheckL2AllowedSwitch, "fan_recheck_l2_allowed",
                 id="room_l2_allowed"),
    pytest.param(sw.RoomHumidityFanControlSwitch, "humidity_fan_control_enabled",
                 id="room_boolean_option"),
]


@pytest.mark.parametrize("cls,key", _ROOM_CASES)
@pytest.mark.parametrize("opt,restored", [(False, "on"), (True, "off")])
async def test_room_options_win_over_restore(_no_base_hooks, cls, key, opt, restored):
    ent = await _add_room(cls, key, {key: opt}, restored)
    assert ent._attr_is_on is opt


@pytest.mark.parametrize("cls,key", _ROOM_CASES)
@pytest.mark.parametrize("restored,expected", [("on", True), ("off", False)])
async def test_room_restore_when_key_absent(_no_base_hooks, cls, key, restored, expected):
    ent = await _add_room(cls, key, {}, restored)
    assert ent._attr_is_on is expected

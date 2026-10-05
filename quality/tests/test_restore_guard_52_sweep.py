"""Bug Class #52 guard sweep (RESTORE-UNAVAILABLE-OFF-SWEEP-1).

LIVE EVIDENCE: on 2026-10-03 the house was down 61 min across a crash-shutdown
(v5.103.37); when it came back, every RestoreEntity whose last saved state was
``unavailable`` and whose restore path lacked a #52 guard was coerced to its
``last_state.state == "on"`` evaluation (i.e. False). The most visible symptom
was ``switch.ura_hvac_coordinator_zone_sweep`` — a default-ON switch that had
been ON continuously for 10 days — coming back OFF and staying OFF.

This test file sweeps every remaining unguarded RestoreEntity restore in
``switch.py`` by driving the REAL class's ``async_added_to_hass`` with mocked
``async_get_last_state`` returning each of unavailable / unknown / None / off /
on. The pattern mirrors ``test_reconcile_on_return.py::_load_real_auto_recovery_switch``
so a single AST load-and-exec harness is reused per class.
"""

from __future__ import annotations

import ast
import asyncio
import logging as _logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_SWITCH_SRC_PATH = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "universal_room_automation"
    / "switch.py"
)
_SWITCH_SRC = _SWITCH_SRC_PATH.read_text()
_TREE = ast.parse(_SWITCH_SRC)


class _Base:
    """Mocked UniversalRoomEntity base — captures coordinator and provides
    ``async_get_last_state`` / ``async_write_ha_state`` so the extracted class
    body can be exec'd without the full HA runtime.
    """

    def __init__(self, coordinator=None, *a, **k):
        if coordinator is not None:
            self.coordinator = coordinator
        self._last_state_stub = None

    async def async_added_to_hass(self):
        return None

    async def async_get_last_state(self):
        return self._last_state_stub

    def async_write_ha_state(self):
        return None


class _SwitchEntity:
    def async_write_ha_state(self):
        return None


class _RestoreEntity:
    """Base for classes that inherit (SwitchEntity, RestoreEntity) directly
    (not via UniversalRoomEntity). Provides async_get_last_state via a
    ``_last_state_stub`` attribute set on the instance."""

    async def async_added_to_hass(self):
        return None

    async def async_get_last_state(self):
        return getattr(self, "_last_state_stub", None)


def _load_class(class_name: str):
    """Compile and return the REAL class body from switch.py under mocked bases."""
    node = next(
        n for n in _TREE.body
        if isinstance(n, ast.ClassDef) and n.name == class_name
    )
    src = ast.get_source_segment(_SWITCH_SRC, node)
    ns = {
        "UniversalRoomEntity": _Base,
        "SwitchEntity": _SwitchEntity,
        "RestoreEntity": _RestoreEntity,
        "_LOGGER": _logging.getLogger(f"test.{class_name}"),
        # some restore paths call hass.states.get / services — we never reach
        # them in the pure async_added_to_hass path exercised here, but keep
        # the names defined so the module compiles.
        "DeviceInfo": MagicMock,
        "DOMAIN": "universal_room_automation",
        "VERSION": "test",
        "EntityCategory": MagicMock(),
        "HomeAssistant": MagicMock,
        "ConfigEntry": MagicMock,
    }
    exec(compile(src, f"switch_{class_name}", "exec"), ns)
    return ns[class_name]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# HVACZoneSweepSwitch (default ON) — the live-evidence incident site.
# ---------------------------------------------------------------------------

def _hvac_zone_sweep_restore_result(last_state):
    Switch = _load_class("HVACZoneSweepSwitch")
    hass = MagicMock()
    entry = MagicMock()
    sw = Switch(hass, entry)
    sw._last_state_stub = last_state
    # ``_update_zones`` touches the HVAC coordinator; stub it.
    sw._update_zones = lambda: None
    _run(sw.async_added_to_hass())
    return sw._is_on


def test_hvac_zone_sweep_unavailable_last_state_stays_on():
    """Incident site: default-ON sweep came back OFF after v5.103.37 crash."""
    assert _hvac_zone_sweep_restore_result(MagicMock(state="unavailable")) is True
    assert _hvac_zone_sweep_restore_result(MagicMock(state="unknown")) is True
    assert _hvac_zone_sweep_restore_result(None) is True
    assert _hvac_zone_sweep_restore_result(MagicMock(state="off")) is False
    assert _hvac_zone_sweep_restore_result(MagicMock(state="on")) is True


# ---------------------------------------------------------------------------
# SecurityDelegateLightsSwitch (default ON)
# ---------------------------------------------------------------------------

def _security_delegate_restore_result(last_state):
    Switch = _load_class("SecurityDelegateLightsSwitch")
    # Not a UniversalRoomEntity subclass — construct via its own __init__
    # which takes (hass).
    hass = MagicMock()
    sw = Switch(hass)
    sw._last_state_stub = last_state
    # Replace the coordinator sync so we don't need the real coordinator wiring.
    sync_called = []
    sw._sync_to_coordinator = lambda: sync_called.append(True)
    _run(sw.async_added_to_hass())
    return sw._is_on, sync_called


def test_security_delegate_lights_unavailable_last_state_stays_on():
    on_result, _ = _security_delegate_restore_result(MagicMock(state="unavailable"))
    assert on_result is True
    unknown_result, _ = _security_delegate_restore_result(MagicMock(state="unknown"))
    assert unknown_result is True
    off_result, _ = _security_delegate_restore_result(MagicMock(state="off"))
    assert off_result is False
    on_result, _ = _security_delegate_restore_result(MagicMock(state="on"))
    assert on_result is True


# ---------------------------------------------------------------------------
# AutomationSwitch (default ON) — per-room automation master.
# ---------------------------------------------------------------------------

def _room_switch_restore_result(class_name: str, last_state):
    Switch = _load_class(class_name)
    coord = MagicMock()
    coord.entry.data = {"room_name": "Bedroom"}
    sw = Switch(coord)
    sw._last_state_stub = last_state
    _run(sw.async_added_to_hass())
    return sw._attr_is_on


def test_automation_switch_unavailable_last_state_stays_on():
    assert _room_switch_restore_result("AutomationSwitch", MagicMock(state="unavailable")) is True
    assert _room_switch_restore_result("AutomationSwitch", MagicMock(state="unknown")) is True
    assert _room_switch_restore_result("AutomationSwitch", MagicMock(state="off")) is False
    assert _room_switch_restore_result("AutomationSwitch", MagicMock(state="on")) is True


# ---------------------------------------------------------------------------
# CoverAutomationSwitch (default ON).
# ---------------------------------------------------------------------------

def test_cover_automation_switch_unavailable_last_state_stays_on():
    assert _room_switch_restore_result("CoverAutomationSwitch", MagicMock(state="unavailable")) is True
    assert _room_switch_restore_result("CoverAutomationSwitch", MagicMock(state="unknown")) is True
    assert _room_switch_restore_result("CoverAutomationSwitch", MagicMock(state="off")) is False
    assert _room_switch_restore_result("CoverAutomationSwitch", MagicMock(state="on")) is True


# ---------------------------------------------------------------------------
# AiAutomationSwitch (default ON).
# ---------------------------------------------------------------------------

def test_ai_automation_switch_unavailable_last_state_stays_on():
    assert _room_switch_restore_result("AiAutomationSwitch", MagicMock(state="unavailable")) is True
    assert _room_switch_restore_result("AiAutomationSwitch", MagicMock(state="unknown")) is True
    assert _room_switch_restore_result("AiAutomationSwitch", MagicMock(state="off")) is False
    assert _room_switch_restore_result("AiAutomationSwitch", MagicMock(state="on")) is True


# ---------------------------------------------------------------------------
# InfrastructureRoomSwitch (default from room type; may be ON).
# ---------------------------------------------------------------------------

def test_infrastructure_room_switch_unavailable_last_state_preserves_default_on():
    Switch = _load_class("InfrastructureRoomSwitch")
    coord = MagicMock()
    coord.entry.data = {"room_name": "AV Closet"}
    # Default = True (infrastructure room)
    coord._infrastructure_room = True

    def _result(last_state):
        sw = Switch(coord)
        sw._last_state_stub = last_state
        _run(sw.async_added_to_hass())
        return sw._attr_is_on

    assert _result(MagicMock(state="unavailable")) is True
    assert _result(MagicMock(state="unknown")) is True
    assert _result(MagicMock(state="off")) is False
    assert _result(MagicMock(state="on")) is True


# ---------------------------------------------------------------------------
# Override pair + ManualMode (default OFF, behaviour-neutral but guarded for
# consistency). Positive restore still works; unavailable keeps default OFF.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", ["OverrideOccupiedSwitch", "OverrideVacantSwitch", "ManualModeSwitch"])
def test_default_off_room_switches_unavailable_last_state_stays_off(class_name):
    assert _room_switch_restore_result(class_name, MagicMock(state="unavailable")) is False
    assert _room_switch_restore_result(class_name, MagicMock(state="unknown")) is False
    assert _room_switch_restore_result(class_name, MagicMock(state="on")) is True
    assert _room_switch_restore_result(class_name, MagicMock(state="off")) is False


# ---------------------------------------------------------------------------
# Guard-presence counter-proof: production source does contain the membership
# guard for each class above (so the behavioural tests are not vacuously
# green on a trivial restore path).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "class_name",
    [
        "HVACZoneSweepSwitch",
        "SecurityDelegateLightsSwitch",
        "AutomationSwitch",
        "OverrideOccupiedSwitch",
        "OverrideVacantSwitch",
        "CoverAutomationSwitch",
        "ManualModeSwitch",
        "AiAutomationSwitch",
        "InfrastructureRoomSwitch",
    ],
)
def test_restore_guard_present_in_source(class_name):
    """Each class's extracted body carries the ('on', 'off') membership guard."""
    node = next(
        n for n in _TREE.body
        if isinstance(n, ast.ClassDef) and n.name == class_name
    )
    body = ast.get_source_segment(_SWITCH_SRC, node)
    assert 'last_state.state in ("on", "off")' in body, (
        f"{class_name}: Bug Class #52 membership guard missing from async_added_to_hass"
    )

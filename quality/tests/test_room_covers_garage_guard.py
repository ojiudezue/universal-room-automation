"""Tests for ROOM-COVERS-NO-GARAGE-DOOR-GUARD-1.

Verifies the room-tier cover automation refuses to open/close covers whose
``device_class`` is ``garage`` or ``gate`` (Security-owned) at every
writer path, and that a co-resident shade in the same room still actuates.

Two guard sites are exercised so a per-site mutation drill can neuter
either independently:

  1. ``automation._get_available_covers``  — filters garage/gate covers
     out of the pre-computed list handed to every writer path.
  2. ``automation._send_covers_with_verify`` — defence-in-depth at the
     choke point in case a direct caller bypasses the pre-filter.

Mutation drill (per Tier-1 build brief):
  * Neuter guard at (1): edit ``_get_available_covers`` to remove the
    ``is_security_owned_cover`` skip → ``test_get_available_covers_filters_garage_and_gate``
    goes red. Restore + clear ``__pycache__`` to recover green.
  * Neuter guard at (2): edit ``_send_covers_with_verify`` to remove the
    ``is_security_owned_cover`` filter block →
    ``test_send_covers_with_verify_refuses_garage_direct`` goes red.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Reuse the module-level HA-shim scaffolding from test_cover_verify.
# Importing it registers the stub modules in sys.modules and loads the
# real ``automation`` + ``const`` under ``custom_components.universal_room_automation``.
import test_cover_verify as _cv  # noqa: F401  (side effects)

_automation = sys.modules["custom_components.universal_room_automation.automation"]
RoomAutomation = _automation.RoomAutomation


# ---------------------------------------------------------------------------
# State/registry shim: extends _FakeState with a device_class attribute.
# ---------------------------------------------------------------------------

class _FakeState:
    def __init__(self, state: str, device_class: str | None = None):
        self.state = state
        self.attributes = {"device_class": device_class} if device_class else {}


class _FakeStates:
    def __init__(self):
        self._map: dict[str, _FakeState] = {}

    def set(self, entity_id: str, state: str, device_class: str | None = None):
        self._map[entity_id] = _FakeState(state, device_class)
        # Mirror into the registry stub so the choke-point registry-only
        # guard also sees the device_class.
        _REGISTRY_DEVICE_CLASS[entity_id] = device_class

    def get(self, entity_id: str):
        return self._map.get(entity_id)


_REGISTRY_DEVICE_CLASS: dict[str, str | None] = {}


def _install_stub_entity_registry():
    """Register a fake entity_registry backed by ``_REGISTRY_DEVICE_CLASS``.

    ``cover_ownership.is_security_owned_cover_by_registry`` (used at the
    ``_send_covers_with_verify`` choke point) consults the registry
    exclusively so it doesn't perturb scripted state sequences. Tests
    populate ``_REGISTRY_DEVICE_CLASS`` per entity_id.
    """
    er_mod = sys.modules.get("homeassistant.helpers.entity_registry")
    if er_mod is None:
        import types
        er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
        sys.modules["homeassistant.helpers.entity_registry"] = er_mod

    class _Entry:
        def __init__(self, device_class):
            self.device_class = device_class
            self.original_device_class = device_class

    class _Reg:
        def async_get(self, entity_id):
            dc = _REGISTRY_DEVICE_CLASS.get(entity_id)
            return _Entry(dc) if dc is not None else None

    def _async_get(_hass):
        return _Reg()

    er_mod.async_get = _async_get


_install_stub_entity_registry()

# Re-import cover_ownership after the entity_registry stub is in place.
if "custom_components.universal_room_automation.cover_ownership" in sys.modules:
    importlib.reload(
        sys.modules["custom_components.universal_room_automation.cover_ownership"]
    )
else:
    _cv._load("cover_ownership")


def _make_automation(covers, fake_states):
    hass = MagicMock()
    hass.states = fake_states
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value=None)
    hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
    hass.data = {}

    coordinator = MagicMock()
    entry = MagicMock()
    entry.data = {"room_name": "Garage A", "covers": covers}
    entry.options = {}
    coordinator.entry = entry

    config = {"room_name": "Garage A", "covers": covers}
    automation = RoomAutomation(hass, config, coordinator)
    automation._config_entry = entry
    return automation, hass


# ---------------------------------------------------------------------------
# Guard site 1: _get_available_covers
# ---------------------------------------------------------------------------

def test_get_available_covers_filters_garage_and_gate():
    """Garage + gate covers are dropped from the available list; shade stays."""
    garage = "cover.konnected_f0f5bd523b00_garage_door"
    gate = "cover.driveway_gate"
    shade = "cover.garage_a_shade"
    states = _FakeStates()
    states.set(garage, "closed", device_class="garage")
    states.set(gate, "closed", device_class="gate")
    states.set(shade, "closed", device_class="shade")

    automation, _hass = _make_automation([garage, gate, shade], states)
    available = automation._get_available_covers()

    assert available == [shade]


def test_get_available_covers_logs_garage_skip_once(caplog):
    """A garage cover is INFO-logged the first time it's skipped, not on repeats."""
    import logging
    garage = "cover.garage_door"
    shade = "cover.window_shade"
    states = _FakeStates()
    states.set(garage, "closed", device_class="garage")
    states.set(shade, "closed", device_class="shade")

    automation, _hass = _make_automation([garage, shade], states)

    with caplog.at_level(logging.INFO,
                        logger="custom_components.universal_room_automation.automation"):
        automation._get_available_covers()
        automation._get_available_covers()
        automation._get_available_covers()

    skip_logs = [
        r for r in caplog.records
        if "skipping Security-owned cover" in r.getMessage() and garage in r.getMessage()
    ]
    assert len(skip_logs) == 1, f"expected one INFO skip log, got {len(skip_logs)}"


# ---------------------------------------------------------------------------
# Guard site 2: _send_covers_with_verify (defence-in-depth choke point)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_covers_with_verify_refuses_garage_direct():
    """A garage cover handed directly to the choke point is not sent."""
    garage = "cover.garage_door"
    shade = "cover.window_shade"
    states = _FakeStates()
    states.set(garage, "open", device_class="garage")
    # Shade already at target ("open") so verify passes on first attempt
    # — we only care that exactly one service call was made and only for
    # the shade (garage was filtered before dispatch).
    states.set(shade, "open", device_class="shade")

    automation, hass = _make_automation([garage, shade], states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            [garage, shade], "open_cover",
        )

    assert success is True
    assert failed == []
    # Exactly one service call — for the shade, NOT the garage.
    assert hass.services.async_call.call_count == 1
    called_entity = hass.services.async_call.call_args_list[0].args[2]["entity_id"]
    assert called_entity == shade


@pytest.mark.asyncio
async def test_send_covers_with_verify_all_garage_is_noop():
    """A batch of only garage covers is a no-op success, zero service calls."""
    garage_a = "cover.garage_a_door"
    garage_b = "cover.garage_b_door"
    states = _FakeStates()
    states.set(garage_a, "closed", device_class="garage")
    states.set(garage_b, "closed", device_class="garage")

    automation, hass = _make_automation([garage_a, garage_b], states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            [garage_a, garage_b], "close_cover",
        )

    assert success is True
    assert failed == []
    assert hass.services.async_call.call_count == 0


# ---------------------------------------------------------------------------
# End-to-end: shade in a garage room still actuates on entry/exit/timed paths.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shade_in_garage_room_still_actuates_via_available():
    """The shade survives filtering and reaches the service call."""
    garage = "cover.garage_door"
    shade = "cover.garage_shade"
    states = _FakeStates()
    states.set(garage, "open", device_class="garage")
    # Shade already at target so the verify loop passes first try.
    states.set(shade, "open", device_class="shade")

    automation, hass = _make_automation([garage, shade], states)
    available = automation._get_available_covers()
    assert available == [shade]

    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            available, "open_cover",
        )
    assert success is True
    assert failed == []
    assert hass.services.async_call.call_count == 1
    assert hass.services.async_call.call_args_list[0].args[2]["entity_id"] == shade

"""D3-AREA-INHERIT — UniversalRoomEntity durably inherits room area on add.

The area is stamped on the SHARED room device via
``dr.async_update_device(device_id, area_id=...)`` from
``UniversalRoomEntity.async_added_to_hass`` — the durable, non-deprecated
API (see entity.py comment for HA source citations). This is a
BASE-CLASS behavior; every URA per-room entity (D3 fused camera sensor,
temperature sensor, etc.) inherits it. The room device is created by the
FIRST-registering platform (Platform.SENSOR precedes Platform.BINARY_SENSOR
in __init__.py PLATFORMS), so testing the base-class path via a sensor.py
entity is the correct proof that D3 (and every sibling) gets the area.

Guarantees pinned:
- Fresh device (area_id=None) with CONF_AREA_ID set  →  async_update_device
  is invoked with the configured area_id.
- Existing device with area_id already set (operator manual assignment)
  →  async_update_device is NOT called (only-when-unset).
- CONF_AREA_ID unset  →  async_update_device is NOT called (kill switch).
- No use of the deprecated ``suggested_area`` kwarg anywhere in the write.

Behavioral tests drive UniversalRoomEntity.async_added_to_hass against a
stubbed device registry + coordinator. One demoted source anchor guards
the presence of the async_update_device call site.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

_HERE = os.path.dirname(__file__)
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_REPO_ROOT = Path(_REPO)

_ENTITY_TEXT = (
    _REPO_ROOT / "custom_components/universal_room_automation/entity.py"
).read_text()


# ---------------------------------------------------------------------------
# Demoted source anchor: guards the durable-API call site exists at all.
# Behavioral tests below pin the value/precondition semantics.
# ---------------------------------------------------------------------------

def test_source_anchor_uses_async_update_device_not_suggested_area():
    """Durable API: must use async_update_device(area_id=...), NOT the
    deprecated DeviceInfo.suggested_area (breaks in HA 2026.9)."""
    assert "dev_reg.async_update_device(device.id, area_id=" in _ENTITY_TEXT
    # Deprecated-path guard: ensure the call itself does NOT pass
    # ``suggested_area=`` and the DeviceInfo constructor doesn't set it.
    # (Comments in the file may reference the name to explain why we
    # avoid it — that's fine.)
    assert "suggested_area=" not in _ENTITY_TEXT, (
        "Do not pass suggested_area anywhere — HA 2026.9 removes it "
        "(device_registry.py:446-452, :1342-1357)."
    )


# ---------------------------------------------------------------------------
# Behavioral: drive UniversalRoomEntity.async_added_to_hass through a
# real sensor.py-platform entity (TemperatureSensor) — proves the
# first-registering-platform / base-class path carries the fix.
# ---------------------------------------------------------------------------

def _import():
    sys.path.insert(0, os.path.join(_REPO, "custom_components"))
    try:
        from universal_room_automation import entity as ent_mod  # noqa: PLC0415
        from universal_room_automation import sensor as sensor_mod  # noqa: PLC0415
        from universal_room_automation.const import DOMAIN  # noqa: PLC0415
        return ent_mod, sensor_mod, DOMAIN
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"URA entity/sensor modules not importable: {e}")


class _StubDevice:
    def __init__(self, area_id=None):
        self.id = "device_room_test"
        self.area_id = area_id


class _StubDevReg:
    def __init__(self, device):
        self._device = device
        self.update_calls: list[tuple[str, dict]] = []

    def async_get_device(self, identifiers=None, **_kw):
        return self._device

    def async_update_device(self, device_id, **kw):
        # Record the call. Contract: MUST NOT be passed suggested_area
        # (that path is deprecated and logs a break warning).
        assert "suggested_area" not in kw, (
            "Base-class area write must not use deprecated suggested_area"
        )
        self.update_calls.append((device_id, kw))
        if "area_id" in kw and self._device is not None:
            self._device.area_id = kw["area_id"]


class _Entry:
    def __init__(self, area_id=None, room_name="Living Room"):
        self.entry_id = "entry_test_d3"
        self.data = {"room_name": room_name}
        if area_id is not None:
            self.data["area_id"] = area_id
        self.options = {}


class _Coord:
    def __init__(self, entry):
        self.entry = entry
        self.data = {}
        self.last_update_success = True

    def _get_room_area(self):
        # Mirrors coordinator._get_room_area (options over data).
        return (
            self.entry.options.get("area_id")
            or self.entry.data.get("area_id")
            or None
        )

    def async_add_listener(self, *_a, **_k):
        return lambda: None


def _make_entity(sensor_mod, coord):
    """Bypass CoordinatorEntity base __init__ (poisoned in full-suite runs)
    and directly set the fields UniversalRoomEntity.__init__ populates,
    plus what async_added_to_hass reads. This lets us exercise
    async_added_to_hass end-to-end even when sys.modules has a narrow
    CoordinatorEntity stub."""
    cls = sensor_mod.TemperatureSensor
    ent = cls.__new__(cls)
    ent.coordinator = coord
    return ent


def _install_device_registry(monkeypatch, ent_mod, dev_reg):
    # UniversalRoomEntity.async_added_to_hass imports device_registry
    # lazily inside the method. Provide a stub module that returns our
    # fake registry from async_get.
    import types  # noqa: PLC0415
    fake_hass_helpers = types.ModuleType("homeassistant.helpers.device_registry")
    fake_hass_helpers.async_get = lambda _hass: dev_reg  # noqa: ARG005
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.device_registry", fake_hass_helpers,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _NoopHass:
    """Minimal hass surface — async_added_to_hass on our stubbed entity
    doesn't invoke CoordinatorEntity chained logic (we monkeypatch
    super().async_added_to_hass)."""
    pass


def _neutered_super_added(monkeypatch, ent_mod):
    """Ensure super().async_added_to_hass() resolves to a no-op.

    In a full-suite run the CoordinatorEntity may be a narrow stub with
    no ``async_added_to_hass``. Install a no-op on the direct parent so
    the base-class super() chain resolves cleanly. In prod the real
    CoordinatorEntity supplies its own method (we don't need it to run
    for this fix's semantics)."""
    async def _noop(self):
        return None
    parent = ent_mod.UniversalRoomEntity.__mro__[1]
    if parent is object:
        return
    monkeypatch.setattr(parent, "async_added_to_hass", _noop, raising=False)


def test_fresh_device_inherits_configured_area(monkeypatch):
    ent_mod, sensor_mod, DOMAIN = _import()
    _neutered_super_added(monkeypatch, ent_mod)
    device = _StubDevice(area_id=None)
    dev_reg = _StubDevReg(device)
    _install_device_registry(monkeypatch, ent_mod, dev_reg)

    entry = _Entry(area_id="living_room")
    coord = _Coord(entry)
    ent = _make_entity(sensor_mod, coord)
    ent.hass = _NoopHass()

    _run(ent.async_added_to_hass())

    assert len(dev_reg.update_calls) == 1, (
        f"Expected exactly one async_update_device call, got "
        f"{dev_reg.update_calls!r}"
    )
    device_id, kw = dev_reg.update_calls[0]
    assert device_id == "device_room_test"
    assert kw == {"area_id": "living_room"}
    assert device.area_id == "living_room"


def test_existing_device_area_preserved(monkeypatch):
    """Only-when-unset: operator-set device.area_id must not be clobbered."""
    ent_mod, sensor_mod, DOMAIN = _import()
    _neutered_super_added(monkeypatch, ent_mod)
    device = _StubDevice(area_id="operator_moved_this_room")
    dev_reg = _StubDevReg(device)
    _install_device_registry(monkeypatch, ent_mod, dev_reg)

    entry = _Entry(area_id="config_says_something_else")
    coord = _Coord(entry)
    ent = _make_entity(sensor_mod, coord)
    ent.hass = _NoopHass()

    _run(ent.async_added_to_hass())

    assert dev_reg.update_calls == [], (
        "Must not overwrite an existing device.area_id (registry wins)"
    )
    assert device.area_id == "operator_moved_this_room"


def test_no_conf_area_is_noop(monkeypatch):
    """Kill switch: CONF_AREA_ID unset → no async_update_device call."""
    ent_mod, sensor_mod, DOMAIN = _import()
    _neutered_super_added(monkeypatch, ent_mod)
    device = _StubDevice(area_id=None)
    dev_reg = _StubDevReg(device)
    _install_device_registry(monkeypatch, ent_mod, dev_reg)

    entry = _Entry(area_id=None)
    coord = _Coord(entry)
    ent = _make_entity(sensor_mod, coord)
    ent.hass = _NoopHass()

    _run(ent.async_added_to_hass())

    assert dev_reg.update_calls == []
    assert device.area_id is None


def test_options_overrides_data_for_area(monkeypatch):
    ent_mod, sensor_mod, DOMAIN = _import()
    _neutered_super_added(monkeypatch, ent_mod)
    device = _StubDevice(area_id=None)
    dev_reg = _StubDevReg(device)
    _install_device_registry(monkeypatch, ent_mod, dev_reg)

    entry = _Entry(area_id="stale_area")
    entry.options = {"area_id": "moved_room"}
    coord = _Coord(entry)
    ent = _make_entity(sensor_mod, coord)
    ent.hass = _NoopHass()

    _run(ent.async_added_to_hass())

    assert len(dev_reg.update_calls) == 1
    _, kw = dev_reg.update_calls[0]
    assert kw == {"area_id": "moved_room"}

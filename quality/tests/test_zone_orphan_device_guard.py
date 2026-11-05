"""ZONE-ORPHAN-DEVICE-REMOVE-GUARD-1 — zone-device cleanup must not delete live devices.

Both zone-device cleanup sites in ``__init__.async_setup_entry`` (v3.5.3
integration-entry orphan sweep + v3.6.0-c2.1 Zone Manager slug sweep) route
through ``_remove_orphan_zone_devices``. A zone device whose id is missing from
a (possibly transiently incomplete) active-zone set is removed ONLY when no
entity — enabled or disabled — still points at it.

Behavioural: drives the real helper with fake device/entity registries
patched onto the real HA registry modules (scoped via monkeypatch).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

DOMAIN = "universal_room_automation"


class _FakeDevReg:
    def __init__(self, devices):
        self.devices = {d.id: d for d in devices}
        self.removed: list[str] = []

    def async_remove_device(self, device_id):
        self.removed.append(device_id)
        self.devices.pop(device_id, None)


def _dev(dev_id, *identifiers):
    return SimpleNamespace(id=dev_id, identifiers=set(identifiers))


@pytest.fixture
def run_cleanup(monkeypatch):
    ura = importlib.import_module("custom_components.universal_room_automation")
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    def _run(devices, entities_by_device, is_orphan):
        dev_reg = _FakeDevReg(devices)
        calls = {}

        def _entries_for_device(_ent_reg, device_id, include_disabled_entities=False):
            calls[device_id] = include_disabled_entities
            ents = entities_by_device.get(device_id, [])
            if not include_disabled_entities:
                ents = [e for e in ents if not e.get("disabled")]
            return ents

        monkeypatch.setattr(
            dr, "async_entries_for_config_entry",
            lambda reg, entry_id: list(reg.devices.values()),
        )
        monkeypatch.setattr(er, "async_get", lambda hass: object())
        monkeypatch.setattr(er, "async_entries_for_device", _entries_for_device)
        n = ura._remove_orphan_zone_devices(
            object(), dev_reg, "entry1", is_orphan, "zone device",
        )
        return dev_reg, n, calls

    return _run


def test_zone_device_with_entity_survives_missing_id(run_cleanup):
    dev = _dev("d1", (DOMAIN, "zone_Upstairs"))
    reg, n, _ = run_cleanup([dev], {"d1": [{"entity_id": "sensor.x"}]}, lambda i: True)
    assert reg.removed == []
    assert n == 0


def test_empty_zone_device_with_missing_id_is_removed(run_cleanup):
    dev = _dev("d1", (DOMAIN, "zone_Ghost"))
    reg, n, _ = run_cleanup([dev], {}, lambda i: True)
    assert reg.removed == ["d1"]
    assert n == 1


def test_disabled_only_entity_counts_as_present(run_cleanup):
    dev = _dev("d1", (DOMAIN, "zone_Upstairs"))
    reg, n, calls = run_cleanup(
        [dev], {"d1": [{"entity_id": "sensor.x", "disabled": True}]}, lambda i: True,
    )
    assert reg.removed == []
    assert calls == {"d1": True}


def test_zone_manager_never_removed(run_cleanup):
    dev = _dev("zm", (DOMAIN, "zone_manager"))
    reg, n, calls = run_cleanup([dev], {}, lambda i: True)
    assert reg.removed == []
    assert calls == {}


def test_active_zone_not_removed_even_if_empty(run_cleanup):
    dev = _dev("d1", (DOMAIN, "zone_Upstairs"))
    reg, _, _ = run_cleanup([dev], {}, lambda i: i != "zone_Upstairs")
    assert reg.removed == []


def test_three_tuple_identifiers_do_not_crash(run_cleanup):
    bond = _dev("b", ("bond", "hub", "dev"), ("x",))
    ghost = _dev("g", (DOMAIN, "zone_Ghost"))
    reg, n, _ = run_cleanup([bond, ghost], {}, lambda i: True)
    assert reg.removed == ["g"]


def test_device_with_two_orphan_ids_removed_once(run_cleanup):
    dev = _dev("d1", (DOMAIN, "zone_A"), (DOMAIN, "zone_B"))
    reg, n, _ = run_cleanup([dev], {}, lambda i: True)
    assert reg.removed == ["d1"]
    assert n == 1

"""ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 D3 R5 — NM memory conditioning
reads the room's humidity sensor by registry id, driven through the REAL
``NotificationManager.async_notify`` (the enclosing method of the call)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.universal_room_automation import room_entities as re_mod
from custom_components.universal_room_automation.const import DOMAIN


def _nm_module():
    # Imported lazily (not at collection): test_notification_manager.py
    # installs its HA mocks at collection time and breaks if the real
    # module was imported before it (order-robustness, both orders).
    from custom_components.universal_room_automation.domain_coordinators import (
        notification_manager,
    )
    return notification_manager


class _Reg:
    def __init__(self, rows):
        self.rows = rows

    def async_get_entity_id(self, domain, platform, uid):
        return self.rows.get((domain, uid))


class _States:
    def __init__(self, rows):
        self.rows = rows

    def get(self, eid):
        v = self.rows.get(eid)
        return SimpleNamespace(state=v, attributes={}) if v is not None else None


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    re_mod.reset_counters()
    yield
    re_mod.reset_counters()


def _nm(monkeypatch, live_humidity_id):
    foyer = SimpleNamespace(
        entry_id="e_foyer", title="Foyer",
        data={"entry_type": "room", "room_name": "Foyer"}, options={},
    )
    reg = _Reg({("sensor", "e_foyer_humidity"): "sensor.foyer_foyer_humidity"})
    monkeypatch.setattr(re_mod, "_registry", lambda _h: reg)
    facade = MagicMock()
    facade.baseline = AsyncMock(return_value=SimpleNamespace(
        verdict="ok", value={"mean": 50.0, "sd": 2.0},
    ))
    hass = MagicMock()
    hass.config_entries.async_entries = lambda _d=None: [foyer]
    hass.states = _States({
        "switch.ura_memory_nm_conditioning": "on",
        live_humidity_id: "50.5",
    })
    hass.data = {DOMAIN: {"memory_facade": facade}}
    nm = _nm_module().NotificationManager(hass, {"notification_manager_enabled": True})
    return nm


async def _notify(nm):
    await nm.async_notify(
        "test", _nm_module().Severity.MEDIUM, "Humidity high", "msg",
        hazard_type="high_humidity", location="Foyer",
    )


@pytest.mark.asyncio
async def test_humidity_conditioning_reads_registry_id(monkeypatch, caplog):
    """Foyer's humidity sensor is sensor.foyer_foyer_humidity (registry);
    sensor.foyer_humidity does not exist. Conditioning demotes MEDIUM->LOW
    only if it reads the registry id."""
    nm = _nm(monkeypatch, "sensor.foyer_foyer_humidity")
    caplog.set_level(logging.INFO, logger=_nm_module().__name__)
    await _notify(nm)
    assert any("demoting MEDIUM->LOW" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_slug_id_alone_does_not_condition(monkeypatch, caplog):
    """Discriminator: with only the slug-shaped id present, no demotion."""
    nm = _nm(monkeypatch, "sensor.foyer_humidity")
    caplog.set_level(logging.INFO, logger=_nm_module().__name__)
    await _notify(nm)
    assert not any(
        "demoting MEDIUM->LOW" in r.getMessage() for r in caplog.records
    )

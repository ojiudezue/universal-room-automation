"""ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 fix pass (review C tests + B
persisted page latch)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from custom_components.universal_room_automation import room_entities as re_mod
from quality.tests.test_room_entities import (  # noqa: F401
    _entry,
    _make_hass,
    _registry_patch,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _MemStore:
    """Persisted store stand-in: survives reset_counters (a restart)."""

    saved: dict = {}

    def __init__(self, _hass=None):
        pass

    async def async_load(self):
        return dict(_MemStore.saved) or None

    async def async_save(self, data):
        _MemStore.saved = dict(data)


@pytest.fixture
def pages(monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )

    calls: list = []

    async def _fake_fire(hass, kind, key, diagnosis, **kw):
        calls.append((kind, key, kw))
        return True

    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _fake_fire)
    _MemStore.saved = {}
    monkeypatch.setattr(re_mod, "_store", lambda h: _MemStore())
    return calls


def test_name_match_is_exact():
    """M03: 'Bath' must not match 'Bathroom'."""
    hass = _make_hass(rooms=[], extra_entries=[_entry("e_br", "Bathroom")])
    assert re_mod.room_entry_id_for_name(hass, "Bath") is None
    assert re_mod.room_entry_id_for_name(hass, "Bathroom") == "e_br"


def test_non_room_entry_ignored():
    """M13: a non-room entry with the same room_name is never matched."""
    zone = SimpleNamespace(entry_id="e_zone", title="Den",
                           data={"entry_type": "zone_manager", "room_name": "Den"},
                           options={})
    hass = _make_hass(rooms=[], extra_entries=[zone])
    assert re_mod.room_entry_id_for_name(hass, "Den") is None


def test_unknown_slug_miss_counted():
    """M17: R3/R4 path — an unknown node slug is a counted miss."""
    hass = _make_hass()
    assert re_mod.resolve_room_entity_id_for_slug(
        hass, "no_such_room", "binary_sensor", "occupied") is None
    assert re_mod.room_entity_resolve_misses[
        ("slug:no_such_room", "occupied")] == 1


def test_warn_on_second_miss_not_first(caplog):
    """M12."""
    hass = _make_hass()
    caplog.set_level(logging.WARNING, logger=re_mod.__name__)
    re_mod.resolve_room_entity_id(hass, "e_x", "binary_sensor", "occupied")
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    re_mod.resolve_room_entity_id(hass, "e_x", "binary_sensor", "occupied")
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_hit_resets_consecutive_misses(caplog):
    """M16: miss, hit, miss -> no WARN (the run restarted at the hit)."""
    hass = _make_hass(rooms=[])
    caplog.set_level(logging.WARNING, logger=re_mod.__name__)
    re_mod.resolve_room_entity_id(hass, "e_x", "binary_sensor", "occupied")
    hass._reg.add("binary_sensor", "e_x_occupied", "binary_sensor.x_occupied")
    assert re_mod.resolve_room_entity_id(
        hass, "e_x", "binary_sensor", "occupied") == "binary_sensor.x_occupied"
    hass._reg.by_uid.clear()
    re_mod.resolve_room_entity_id(hass, "e_x", "binary_sensor", "occupied")
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_house_status_fallback_count_and_labels():
    """M21/M45."""
    from custom_components.universal_room_automation import house_status

    hass = _make_hass()
    re_mod.note_name_fallback_read("Foyer", "co2", "sensor.foyer_co2")
    re_mod.note_name_fallback_read("Foyer", "co2", "sensor.foyer_co2")
    fields = {f.label: f for f in house_status.health(hass).fields}
    assert fields["room entity name fallbacks"].value == "2"
    assert fields["room entity misses"].value == "0"
    assert fields["room entity misses"].problem is False


def test_page_kind_and_severity(pages):
    """M19: the trip-wire page is kind room_entity_unresolved, HIGH."""
    hass = SimpleNamespace()
    assert _run(re_mod._page_once(hass, "2026-11-19", "d")) is True
    assert pages == [("room_entity_unresolved", ("total",),
                      {"remedy": "Reload the room entry, or check the entity "
                       "registry.", "severity": "HIGH"})]


def test_restart_same_day_no_second_page(pages):
    """B-LOW: a restart (RAM latches cleared) on the same day does not page
    again; the next day does."""
    hass = SimpleNamespace()
    assert _run(re_mod._page_once(hass, "2026-11-19", "d")) is True
    re_mod.reset_counters()  # restart: RAM latch gone, store kept
    assert _run(re_mod._page_once(hass, "2026-11-19", "d")) is False
    assert len(pages) == 1
    assert _run(re_mod._page_once(hass, "2026-11-20", "d")) is True
    assert len(pages) == 2

"""ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 D2 — HVAC fan guard + observer.

The occupied fan-off guard (`FanController._read_room_occupied_state`) and the
conflict observer (`_record_actuation_conflict_if_occupied`) read the room's
occupied sensor by registry unique_id ``{entry_id}_occupied``, never by a slug
built from the room name. Drives the REAL `FanController.update` ->
`_set_fan_state` path through the shared sweep-trio harness.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import quality.tests.test_fan_sweep_trio as _sweep_trio  # noqa: F401
from quality.tests.test_fan_sweep_trio import (  # noqa: F401 — autouse fixture
    _ura_room_entities_registry,
)

from custom_components.universal_room_automation import room_entities as _re_mod
from custom_components.universal_room_automation.domain_coordinators import (
    hvac_fans as _hvac_fans_mod,
)

import pytest as _d7_pytest_clock  # noqa: E402

_make_controller = _sweep_trio._make_controller

# Literals (not the imported constants): DEFAULT_FAN_VACANCY_HOLD 600 s x
# FAN_ADOPTED_VACANCY_HOLD_MULT 2.0, plus 60 s margin.
_PAST_ADOPTED_HOLD_S = 1260


@_d7_pytest_clock.fixture(autouse=True)
def _d7_restore_set_now_clocks(monkeypatch):
    from _d7_isolation import restore_clocks_after_test
    restore_clocks_after_test(monkeypatch, globals())


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _hvac_fans_mod.dt_util.now = fn
    _hvac_fans_mod.dt_util.utcnow = fn


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _drive_vacancy_off(ctrl, room_fan):
    """Adopt the external ON, clear the orthogonal manual-ON hold, then step
    past the doubled adopted vacancy hold so the HVAC-tier OFF is attempted."""
    base = datetime(2026, 8, 4, 19, 0, 0)
    _set_now(base)
    _run(ctrl.update(energy_constraint=None, house_state="home_evening"))
    assert room_fan.trigger == "external"
    room_fan.manual_on_hold_until = ""
    _set_now(base + timedelta(seconds=_PAST_ADOPTED_HOLD_S))
    _run(ctrl.update(energy_constraint=None, house_state="home_evening"))


def _offs(svc_log):
    return [c for c in svc_log if c[1] == "turn_off"]


def _conflicts(writes):
    return [w for w in writes if w.get("episode_type") == "actuation_conflict"]


def test_guard_uses_registry_not_slug_foyer():
    """Live shape: Foyer's occupied sensor is binary_sensor.foyer_foyer_occupied;
    binary_sensor.foyer_occupied does not exist. Old code read the slug id
    (None), failed open and wrote the OFF."""
    ctrl, room_fan, svc_log, writes = _make_controller(
        entity_on=True, entity_speed=100, occupied=False, occ_binary_on=True,
        room_name="Foyer", room_slug="foyer",
        occ_entity_id="binary_sensor.foyer_foyer_occupied",
        entry_id="entry_foyer",
    )
    assert ctrl.hass.states.get("binary_sensor.foyer_occupied") is None
    _drive_vacancy_off(ctrl, room_fan)
    assert _offs(svc_log) == []
    assert room_fan.is_on is True
    rows = _conflicts(writes)
    assert len(rows) == 1
    assert rows[0]["attrs"].get("suppressed") is True
    assert rows[0]["node_id"] == "room:foyer"


def test_guard_media_room_shape_blocks_off():
    """Media -> binary_sensor.media_room_occupied (not media_occupied)."""
    ctrl, room_fan, svc_log, writes = _make_controller(
        entity_on=True, entity_speed=100, occupied=False, occ_binary_on=True,
        room_name="Media", room_slug="media",
        occ_entity_id="binary_sensor.media_room_occupied",
        entry_id="entry_media",
    )
    _drive_vacancy_off(ctrl, room_fan)
    assert _offs(svc_log) == []


def test_observer_agrees_with_guard_jaya_title():
    """Jaya: title 'Jaya Bedroom (Bedroom 4)', room_name 'Jaya Bedroom',
    occupied id binary_sensor.jaya_bedroom_bedroom_4_occupied. Guard and
    observer share one lookup: exactly one suppressed row, room_name slug."""
    ctrl, room_fan, svc_log, writes = _make_controller(
        entity_on=True, entity_speed=100, occupied=False, occ_binary_on=True,
        room_name="Jaya Bedroom", room_slug="jaya_bedroom",
        occ_entity_id="binary_sensor.jaya_bedroom_bedroom_4_occupied",
        entry_id="entry_jaya",
    )
    _drive_vacancy_off(ctrl, room_fan)
    assert _offs(svc_log) == []
    assert [r["node_id"] for r in _conflicts(writes)] == ["room:jaya_bedroom"]


def test_guard_survives_rename_before_reload():
    """Renamed in options, not reloaded: no entry carries the old name, but
    RoomFanState carries the entry id, so the guard still blocks the OFF."""
    ctrl, room_fan, svc_log, _writes = _make_controller(
        entity_on=True, entity_speed=100, occupied=False, occ_binary_on=True,
        entry_id="entry_study_a",
    )
    renamed = MagicMock()
    renamed.entry_id = "entry_study_a"
    renamed.data = {"entry_type": "room", "room_name": "Study A"}
    renamed.options = {"room_name": "Office", "room_fan_mode": "follow_thermostat"}
    ctrl.hass.config_entries.async_entries = lambda _d=None: [renamed]
    _drive_vacancy_off(ctrl, room_fan)
    assert _offs(svc_log) == []


def test_entry_lookup_by_room_name_when_state_has_no_entry_id():
    """No entry id on RoomFanState: the entry is found by exact room_name."""
    ctrl, room_fan, svc_log, _writes = _make_controller(
        entity_on=True, entity_speed=100, occupied=False, occ_binary_on=True,
        room_name="Media", room_slug="media",
        occ_entity_id="binary_sensor.media_room_occupied",
        entry_id="entry_media",
    )
    room_fan.entry_id = None
    entry = MagicMock()
    entry.entry_id = "entry_media"
    entry.data = {"entry_type": "room", "room_name": "Media"}
    entry.options = {"room_fan_mode": "follow_thermostat"}
    ctrl.hass.config_entries.async_entries = lambda _d=None: [entry]
    _drive_vacancy_off(ctrl, room_fan)
    assert _offs(svc_log) == []


def test_registry_miss_fails_open_and_is_counted():
    """No registry row: today's fail-open (OFF proceeds, no row); counted."""
    ctrl, room_fan, svc_log, writes = _make_controller(
        entity_on=True, entity_speed=100, occupied=False, occ_binary_on=True,
        entry_id="entry_study_a",
    )
    ctrl.hass.__dict__["_ura_test_entity_registry"] = (
        _sweep_trio._FakeEntityRegistry()
    )
    _drive_vacancy_off(ctrl, room_fan)
    assert len(_offs(svc_log)) >= 1
    assert _conflicts(writes) == []
    assert _re_mod.room_entity_resolve_misses.get(
        ("entry_study_a", "occupied"), 0,
    ) >= 1


def test_discover_fans_carries_entry_id():
    """discover_fans fills RoomFanState.entry_id from the room entry it scans
    (the setup-path site; the guard reads it at actuation)."""
    ctrl, _room_fan, _svc, _w = _make_controller(entity_on=False)
    zone = MagicMock()
    zone.rooms = ["Foyer"]
    ctrl._zone_manager.zones = {"zone_1": zone}
    entry = MagicMock()
    entry.entry_id = "entry_foyer"
    entry.data = {
        "entry_type": "room", "room_name": "Foyer", "fans": ["fan.foyer"],
    }
    entry.options = {}
    ctrl.hass.config_entries.async_entries = lambda _d=None: [entry]
    ctrl.discover_fans()
    assert ctrl._room_fans["Foyer"].entry_id == "entry_foyer"

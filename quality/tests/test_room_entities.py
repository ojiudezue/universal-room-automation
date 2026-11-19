"""ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 — registry resolver + readers.

INV-RE: every in-scope reader obtains exactly
``entity_registry.async_get_entity_id(domain, DOMAIN, f"{entry_id}_{key}")``
or None (counted), never an id built from the room name.

Fixture ``fixtures/room_registry_live_2026_11_19.json`` is the live install's
47 rooms (read-only from .storage, entry ids hashed). The slug-built oracle
(``binary_sensor.<slug>_occupied``) is derived independently in this file
with its own regex, not by calling production code.
"""

from __future__ import annotations

import json
import logging
import os
import re
from types import SimpleNamespace

import pytest

from custom_components.universal_room_automation import room_entities as re_mod
from custom_components.universal_room_automation.const import DOMAIN

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "room_registry_live_2026_11_19.json",
)
with open(_FIXTURE) as _f:
    LIVE = json.load(_f)
ROOMS = LIVE["rooms"]
KEYS = LIVE["keys"]
LEARNED = {"occupied": "binary_sensor", "temperature": "sensor",
           "humidity": "sensor", "unavailable_entities": "sensor"}

# The 10 live rooms whose occupied id is NOT the slug shape (plan §0.1 / R3-1).
MISMATCHED = {
    "Foyer", "Guest Bedroom 1 Bathroom", "Guest Bedroom 2",
    "Guest Bedroom 2 Hallway", "Jaya Bedroom", "Master Bath Toilet",
    "Master Closet", "Master Hallway", "Media", "Up Guestbedroom Closet",
}


def _oracle_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


class FakeRegistry:
    def __init__(self) -> None:
        self.by_uid: dict[tuple[str, str, str], str] = {}

    def add(self, domain, uid, entity_id) -> None:
        self.by_uid[(domain, DOMAIN, uid)] = entity_id

    def async_get_entity_id(self, domain, platform, unique_id):
        return self.by_uid.get((domain, platform, unique_id))


class FakeStates:
    def __init__(self) -> None:
        self.by_id: dict[str, SimpleNamespace] = {}

    def set(self, entity_id, state, **attrs) -> None:
        self.by_id[entity_id] = SimpleNamespace(
            entity_id=entity_id, state=state, attributes=attrs,
        )

    def get(self, entity_id):
        return self.by_id.get(entity_id)


def _entry(entry_id, room_name, title=None, options=None):
    return SimpleNamespace(
        entry_id=entry_id, title=title or room_name,
        data={"entry_type": "room", "room_name": room_name},
        options=options or {},
    )


def _make_hass(rooms=ROOMS, extra_entries=()):
    reg = FakeRegistry()
    entries = []
    for r in rooms:
        entries.append(_entry(r["entry_id"], r["room_name"], r["title"]))
        for key, domain in KEYS.items():
            if r["entities"].get(key):
                reg.add(domain, f"{r['entry_id']}_{key}", r["entities"][key])
    entries.extend(extra_entries)
    tasks: list = []
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda _d=None: entries),
        states=FakeStates(),
        data={DOMAIN: {}},
        async_create_task=lambda coro: (tasks.append(coro), coro.close()),
    )
    hass._reg = reg
    hass._tasks = tasks
    hass._entries = entries
    return hass


@pytest.fixture(autouse=True)
def _registry_patch(monkeypatch):
    re_mod.reset_counters()
    monkeypatch.setattr(re_mod, "_registry", lambda h: h._reg)
    yield
    re_mod.reset_counters()


def _room(name):
    return next(r for r in ROOMS if r["room_name"] == name)


# ---------------------------------------------------------------- D1 --------


def test_live_47_room_fixture_all_keys():
    hass = _make_hass()
    assert len(ROOMS) == 47
    n = 0
    for r in ROOMS:
        for key, domain in LEARNED.items():
            got = re_mod.resolve_room_entity_id(hass, r["entry_id"], domain, key)
            assert got == r["entities"][key], (r["room_name"], key)
            n += 1
    assert n == 188
    assert sum(re_mod.room_entity_resolve_misses.values()) == 0
    # The test discriminates: the slug oracle gets 37/47 occupied.
    slug_hits = [
        r["room_name"] for r in ROOMS
        if r["entities"]["occupied"]
        == f"binary_sensor.{_oracle_slug(r['room_name'])}_occupied"
    ]
    assert len(slug_hits) == 37
    assert {r["room_name"] for r in ROOMS} - set(slug_hits) == MISMATCHED


def test_golden_37_matching_rooms_byte_identical():
    """Only proven code supersedes correct code: for the 37 rooms whose old
    slug-built id was right, every new path returns that same id."""
    hass = _make_hass()
    for r in ROOMS:
        old = f"binary_sensor.{_oracle_slug(r['room_name'])}_occupied"
        if r["room_name"] in MISMATCHED:
            continue
        slug = _oracle_slug(r["room_name"])
        assert re_mod.resolve_room_entity_id(
            hass, r["entry_id"], "binary_sensor", "occupied") == old
        assert re_mod.resolve_room_entity_id_for_slug(
            hass, slug, "binary_sensor", "occupied") == old
        eid = re_mod.room_entry_id_for_name(hass, r["room_name"])
        assert re_mod.resolve_room_entity_id(
            hass, eid, "binary_sensor", "occupied") == old


@pytest.mark.parametrize("name,expected", [
    ("Foyer", "binary_sensor.foyer_foyer_occupied"),
    ("Media", "binary_sensor.media_room_occupied"),
    ("Jaya Bedroom", "binary_sensor.jaya_bedroom_bedroom_4_occupied"),
    ("Guest Bedroom 2", "binary_sensor.upstairs_guest_bedroom_occupied"),
])
def test_mismatched_room_shapes(name, expected):
    hass = _make_hass()
    r = _room(name)
    assert r["entities"]["occupied"] == expected
    slug = _oracle_slug(name)
    assert re_mod.resolve_room_entity_id_for_slug(
        hass, slug, "binary_sensor", "occupied") == expected
    assert f"binary_sensor.{slug}_occupied" != expected


def test_renamed_entity_id():
    hass = _make_hass()
    r = _room("Study A")
    hass._reg.add("binary_sensor", f"{r['entry_id']}_occupied",
                  "binary_sensor.office_custom_name")
    assert re_mod.resolve_room_entity_id(
        hass, r["entry_id"], "binary_sensor", "occupied",
    ) == "binary_sensor.office_custom_name"


def test_renamed_room_name():
    e = _entry("e_ren", "Old Den", options={"room_name": "New Den"})
    hass = _make_hass(rooms=[], extra_entries=[e])
    assert re_mod.room_entry_id_for_name(hass, "New Den") == "e_ren"
    assert re_mod.room_entry_id_for_name(hass, "Old Den") is None
    assert re_mod.room_entry_id_for_slug(hass, "new_den") == "e_ren"


def test_title_not_matched():
    hass = _make_hass()
    jaya = _room("Jaya Bedroom")
    assert jaya["title"] != jaya["room_name"]
    assert re_mod.room_entry_id_for_name(hass, jaya["title"]) is None
    assert re_mod.room_entry_id_for_name(hass, "Jaya Bedroom") == jaya["entry_id"]


def test_slug_tie_returns_none():
    a = _entry("e_a", "Study-A2")
    b = _entry("e_b", "Study A2")
    hass = _make_hass(rooms=[], extra_entries=[a, b])
    assert re_mod.resolve_room_entity_id_for_slug(
        hass, "study_a2", "binary_sensor", "occupied") is None
    assert re_mod.room_entity_resolve_misses == {
        ("slug_ambiguous:study_a2", "*"): 1,
    }


def test_miss_counts_and_warns_once(caplog):
    hass = _make_hass()
    caplog.set_level(logging.WARNING, logger=re_mod.__name__)
    for _ in range(3):
        assert re_mod.resolve_room_entity_id(
            hass, "e_missing", "binary_sensor", "occupied") is None
    assert re_mod.room_entity_resolve_misses[("e_missing", "occupied")] == 3
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1


def test_no_entry_id_is_counted_miss_never_built():
    hass = _make_hass()
    assert re_mod.resolve_room_entity_id(
        hass, None, "binary_sensor", "occupied") is None
    assert re_mod.room_entity_resolve_misses[("", "occupied")] == 1


# ---------------------------------------------------------------- D5 --------


def _set_clock(monkeypatch, t):
    monkeypatch.setattr(re_mod.time, "monotonic", lambda: t)


def test_no_page_in_boot_window(monkeypatch):
    hass = _make_hass()
    _set_clock(monkeypatch, 1000.0)
    re_mod.resolve_room_entity_id(hass, "e_missing", "binary_sensor", "occupied")
    _set_clock(monkeypatch, 1599.0)  # 599 s after first call
    re_mod.resolve_room_entity_id(hass, "e_missing", "binary_sensor", "occupied")
    assert hass._tasks == []


def test_trip_wire_once_per_day(monkeypatch):
    hass = _make_hass()
    _set_clock(monkeypatch, 1000.0)
    re_mod.resolve_room_entity_id(hass, "e_ok_first", "binary_sensor", "x")
    _set_clock(monkeypatch, 1600.0)  # exactly 600 s
    for _ in range(5):
        re_mod.resolve_room_entity_id(
            hass, "e_missing", "binary_sensor", "occupied")
    assert len(hass._tasks) == 1
    monkeypatch.setattr(re_mod, "_local_day", lambda: "2099-01-02")
    re_mod.resolve_room_entity_id(hass, "e_missing", "binary_sensor", "occupied")
    assert len(hass._tasks) == 2


def test_fallback_reads_never_page(monkeypatch):
    hass = _make_hass()
    _set_clock(monkeypatch, 1000.0)
    re_mod.resolve_room_entity_id(hass, ROOMS[0]["entry_id"], "binary_sensor",
                                  "occupied")
    _set_clock(monkeypatch, 5000.0)
    for _ in range(3):
        re_mod.note_name_fallback_read("Foyer", "co2", "sensor.foyer_co2")
    assert hass._tasks == []
    assert re_mod.room_entity_name_fallback_reads[("Foyer", "co2")] == 3
    assert sum(re_mod.room_entity_resolve_misses.values()) == 0


def test_house_status_health_shows_misses():
    from custom_components.universal_room_automation import house_status

    hass = _make_hass()
    re_mod.resolve_room_entity_id(hass, "e_missing", "binary_sensor", "occupied")
    fields = {f.label: f for f in house_status.health(hass).fields}
    assert fields["room entity misses"].value.startswith("1")
    assert fields["room entity misses"].problem is True


# ------------------------------------------------- R3 / R4 / R5 readers ----


def _states_for(hass, room, occ="on", temp="72.5", hum="48"):
    hass.states.set(room["entities"]["occupied"], occ)
    hass.states.set(room["entities"]["temperature"], temp)
    hass.states.set(room["entities"]["humidity"], hum)


def test_jaya_samples_all_signals():
    from custom_components.universal_room_automation import memory_baseline

    hass = _make_hass()
    _states_for(hass, _room("Jaya Bedroom"))
    got = memory_baseline._room_samples(hass, "jaya_bedroom")
    assert got == {"occupied": 1.0, "temperature": 72.5, "humidity": 48.0}


def test_resolving_rooms_unchanged_study_a():
    """Study A's ids are the slug shape: same three samples old code read."""
    from custom_components.universal_room_automation import memory_baseline

    hass = _make_hass()
    hass.states.set("binary_sensor.study_a_occupied", "off")
    hass.states.set("sensor.study_a_temperature", "70")
    hass.states.set("sensor.study_a_humidity", "40")
    assert _room("Study A")["entities"]["temperature"] == "sensor.study_a_temperature"
    got = memory_baseline._room_samples(hass, "study_a")
    assert got == {"occupied": 0.0, "temperature": 70.0, "humidity": 40.0}


def test_slug_tie_leaves_rooms_unsampled():
    from custom_components.universal_room_automation import memory_baseline

    a = _entry("e_a", "Study-A2")
    b = _entry("e_b", "Study A2")
    hass = _make_hass(rooms=[], extra_entries=[a, b])
    hass._reg.add("binary_sensor", "e_a_occupied", "binary_sensor.study_a2_occupied")
    hass.states.set("binary_sensor.study_a2_occupied", "on")
    assert memory_baseline._room_samples(hass, "study_a2") == {}


def test_live_sample_registry_id_for_mismatched_room():
    from custom_components.universal_room_automation.memory_facade import (
        MemoryFacade,
    )

    hass = _make_hass()
    _states_for(hass, _room("Media"), occ="on", temp="75", hum="51")
    me = SimpleNamespace(hass=hass)
    assert MemoryFacade._resolve_live_sample(me, "media", "occupied") == 1.0
    assert MemoryFacade._resolve_live_sample(me, "media", "temperature") == 75.0
    assert MemoryFacade._resolve_live_sample(me, "media", "humidity") == 51.0


def test_live_sample_other_signal_counted_fallback():
    from custom_components.universal_room_automation.memory_facade import (
        MemoryFacade,
    )

    hass = _make_hass()
    hass.states.set("sensor.media_co2", "800")
    me = SimpleNamespace(hass=hass)
    assert MemoryFacade._resolve_live_sample(me, "media", "co2") == 800.0
    assert re_mod.room_entity_name_fallback_reads[("slug:media", "co2")] == 1
    assert sum(re_mod.room_entity_resolve_misses.values()) == 0


def test_nm_humidity_reads_registry_id():
    from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
        conditioning_live_entity_id,
    )

    hass = _make_hass()
    foyer = _room("Foyer")
    got = conditioning_live_entity_id(hass, "Foyer", "humidity", "foyer")
    assert got == foyer["entities"]["humidity"]
    assert got != "sensor.foyer_humidity"
    assert sum(re_mod.room_entity_name_fallback_reads.values()) == 0


def test_nm_co2_fallback_counted_not_missed():
    from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
        conditioning_live_entity_id,
    )

    hass = _make_hass()
    got = conditioning_live_entity_id(hass, "Foyer", "co2", "foyer")
    assert got == "sensor.foyer_co2"
    assert re_mod.room_entity_name_fallback_reads[("Foyer", "co2")] == 1
    assert sum(re_mod.room_entity_resolve_misses.values()) == 0


# ------------------------------------------- R6 / R7 / R8 counted fallbacks --


def test_fan_veto_slug_fallback_counted():
    from custom_components.universal_room_automation import fan_veto

    hass = _make_hass(rooms=[])
    hass.states.set("binary_sensor.den_camera_person_detected", "off")
    fan_veto._has_camera_person(hass, "Den", {"room_cameras": ["camera.den"]})
    assert re_mod.room_entity_name_fallback_reads[
        ("Den", "camera_person_detected")] == 1


def test_fan_veto_registry_hit_not_counted():
    from custom_components.universal_room_automation import fan_veto

    hass = _make_hass()
    fused = _room("Foyer")["entities"]["camera_person_detected"]
    hass.states.set(fused, "off")

    class _ER:
        @staticmethod
        def async_get(_h):
            return hass._reg

    import homeassistant.helpers as _hh
    orig = _hh.entity_registry.async_get
    _hh.entity_registry.async_get = _ER.async_get
    try:
        fan_veto._has_camera_person(hass, "Foyer", {"room_cameras": ["camera.f"]})
    finally:
        _hh.entity_registry.async_get = orig
    assert re_mod.room_entity_name_fallback_reads == {}


def _coord_stub(hass, entry_id="e_den", room_name="Den"):
    return SimpleNamespace(
        hass=hass,
        entry=SimpleNamespace(entry_id=entry_id, data={"room_name": room_name}),
        _switch_entity_id_cache={},
        _switch_entity_id_miss_count={},
    )


def test_room_switch_resolver_fallback_counted(monkeypatch):
    from custom_components.universal_room_automation.coordinator import (
        UniversalRoomCoordinator,
    )
    import homeassistant.helpers.entity_registry as er

    hass = _make_hass(rooms=[])
    monkeypatch.setattr(er, "async_get", lambda _h: hass._reg)
    hass.states.set("switch.den_automation", "on")
    stub = _coord_stub(hass)
    got = UniversalRoomCoordinator._resolve_room_switch_entity_id(stub, "automation")
    assert got == "switch.den_automation"
    assert re_mod.room_entity_name_fallback_reads[("e_den", "automation")] == 1


def test_room_switch_resolver_registry_hit_not_counted(monkeypatch):
    from custom_components.universal_room_automation.coordinator import (
        UniversalRoomCoordinator,
    )
    import homeassistant.helpers.entity_registry as er

    hass = _make_hass(rooms=[])
    hass._reg.add("switch", "e_den_automation", "switch.den_den_automation")
    monkeypatch.setattr(er, "async_get", lambda _h: hass._reg)
    stub = _coord_stub(hass)
    got = UniversalRoomCoordinator._resolve_room_switch_entity_id(stub, "automation")
    assert got == "switch.den_den_automation"
    assert re_mod.room_entity_name_fallback_reads == {}


def test_override_switch_helper_fallback_counted():
    from custom_components.universal_room_automation import switch as sw

    coord = SimpleNamespace(
        entry=SimpleNamespace(entry_id="e_den", data={"room_name": "Den"}),
        _resolve_room_switch_entity_id=lambda _s: None,
    )
    assert sw._room_switch_entity_id(coord, "override_vacant") == (
        "switch.den_override_vacant"
    )
    assert re_mod.room_entity_name_fallback_reads[("e_den", "override_vacant")] == 1

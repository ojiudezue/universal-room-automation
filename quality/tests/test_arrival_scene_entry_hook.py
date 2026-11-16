"""Arc step 8 §10.1: the welcome-scene read in the room entry path.

PLANNING_identity_actions_v6.md §5.5 (rev 3.2 L6): the day / evening caller
of ``RoomAutomation._maybe_activate_slot_scene`` asks the music engine
(``hass.data[DOMAIN].get("music_following")``) ``arrival_scene_for(<room
entry_id>)`` before the room's slot scene; None (no engine, or D3's decision
logic not built) leaves the entry path byte-identical. The sleep caller never
reads it. After a returned scene the entry path reports
``note_arrival_scene_result(room, applied)``.

Every test drives the REAL ``_control_lights_entry`` (the enclosing method of
both callers) through the sibling harness ``make_room`` and asserts on the
service calls it emits. Oracles are written by hand from the plan.
"""
from __future__ import annotations

import importlib

import pytest

from test_lighting_slice_c_manual_hold import (  # noqa: F401
    M,
    _real_modules,
    _run,
    make_room,
)

DOMAIN = "universal_room_automation"


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_modules(_real_modules):  # noqa: F811
    yield


class FakeEngine:
    def __init__(self, scene=None, raises=False):
        self.scene = scene
        self.raises = raises
        self.asked: list = []
        self.notes: list = []

    def arrival_scene_for(self, room_entry_id):
        self.asked.append(room_entry_id)
        if self.raises:
            raise RuntimeError("boom")
        return self.scene

    def note_arrival_scene_result(self, room_entry_id, result):
        self.notes.append((room_entry_id, result))


def _room(slot_scene=None, sleep=False, night_lights=None, sleep_scene=None,
          entry_id="room_master"):
    const = M["const"]
    cfg = {
        const.CONF_LIGHTS: ["light.a"],
        const.CONF_NIGHT_LIGHTS: list(night_lights or []),
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON,
    }
    if slot_scene:
        cfg[const.CONF_LIGHT_SCENE_DAY] = slot_scene
    if sleep_scene:
        cfg[const.CONF_LIGHT_SCENE_SLEEP] = sleep_scene
    room = make_room(config=cfg, occupied=True, sleep=sleep, entry_id=entry_id)
    room.auto.is_dark = lambda _lux=None: False          # day slot
    room.auto.is_sleep_lighting_active = lambda: bool(sleep)
    for s in ("scene.day_scene", "scene.welcome", "scene.sleep_scene"):
        room.hass.set_state(s, "scening")
    return room


def _scene_calls(room):
    return [c.data.get("entity_id") for c in room.hass.services.calls
            if c.domain == "scene" and c.service == "turn_on"]


def _all_calls(room):
    return [(c.domain, c.service, c.data) for c in room.hass.services.calls]


def _engine(room, engine):
    room.hass.data[DOMAIN]["music_following"] = engine
    return engine


def test_entry_override_replaces_slot_scene():
    room = _room(slot_scene="scene.day_scene")
    eng = _engine(room, FakeEngine(scene="scene.welcome"))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == ["scene.welcome"]          # one call, the welcome
    assert eng.asked == ["room_master"]                     # room key = entry_id
    assert eng.notes == [("room_master", "applied")]


def test_welcome_without_slot_scene():
    room = _room(slot_scene=None)
    _engine(room, FakeEngine(scene="scene.welcome"))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == ["scene.welcome"]
    # The per-light path did not run as well.
    assert not [c for c in room.hass.services.calls if c.domain == "light"]


def test_engine_returns_none_is_byte_identical_to_no_engine():
    a = _room(slot_scene="scene.day_scene")
    _run(a.auto._control_lights_entry({}))
    b = _room(slot_scene="scene.day_scene")
    eng = _engine(b, FakeEngine(scene=None))
    _run(b.auto._control_lights_entry({}))
    assert _all_calls(a) == _all_calls(b)
    assert _scene_calls(b) == ["scene.day_scene"]
    assert eng.notes == []          # no override, no result note


def test_no_profile_no_scene_byte_identical_per_light_path():
    a = _room(slot_scene=None)
    _run(a.auto._control_lights_entry({}))
    b = _room(slot_scene=None)
    _engine(b, FakeEngine(scene=None))
    _run(b.auto._control_lights_entry({}))
    assert _all_calls(a) == _all_calls(b)
    assert _scene_calls(b) == []


def test_engine_failure_falls_back_to_slot_scene():
    room = _room(slot_scene="scene.day_scene")
    eng = _engine(room, FakeEngine(raises=True))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == ["scene.day_scene"]
    assert eng.notes == []


def test_non_scene_value_ignored():
    room = _room(slot_scene="scene.day_scene")
    _engine(room, FakeEngine(scene="light.not_a_scene"))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == ["scene.day_scene"]


def test_manual_hold_blocks_welcome_and_notes_hold():
    room = _room(slot_scene="scene.day_scene")
    eng = _engine(room, FakeEngine(scene="scene.welcome"))
    room.auto.light_hold_allowed = lambda ents, direction: []   # every light held
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == []
    assert eng.notes == [("room_master", "hold")]


def test_unavailable_welcome_retries_slot_scene():
    """D3 review B2: the slot scene applies (not per-light)."""
    room = _room(slot_scene="scene.day_scene")
    room.hass.set_state("scene.welcome", "unavailable")
    eng = _engine(room, FakeEngine(scene="scene.welcome"))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == ["scene.day_scene"]
    assert eng.notes == [("room_master", "fallback_applied")]
    assert not [c for c in room.hass.services.calls if c.domain == "light"]


def test_both_scenes_unavailable_per_light():
    room = _room(slot_scene="scene.day_scene")
    room.hass.set_state("scene.welcome", "unavailable")
    room.hass.set_state("scene.day_scene", "unavailable")
    eng = _engine(room, FakeEngine(scene="scene.welcome"))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == []
    assert eng.notes == [("room_master", "fallback_failed")]
    assert [c for c in room.hass.services.calls if c.domain == "light"]


def test_unavailable_welcome_no_slot_scene_per_light():
    room = _room(slot_scene=None)
    room.hass.set_state("scene.welcome", "unavailable")
    eng = _engine(room, FakeEngine(scene="scene.welcome"))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == []
    assert eng.notes == [("room_master", "fallback_failed")]


def test_one_scene_call_per_entry():
    room = _room(slot_scene="scene.day_scene")
    _engine(room, FakeEngine(scene="scene.welcome"))
    _run(room.auto._control_lights_entry({}))
    assert len(_scene_calls(room)) == 1


def test_sleep_caller_never_reads_override():
    room = _room(sleep=True, night_lights=["light.n"], sleep_scene="scene.sleep_scene")
    eng = _engine(room, FakeEngine(scene="scene.welcome"))
    _run(room.auto._control_lights_entry({}))
    assert eng.asked == []
    assert _scene_calls(room) == ["scene.sleep_scene"]


def test_real_engine_stub_returns_none_until_d3():
    mf = importlib.import_module(f"custom_components.{DOMAIN}.music_following")
    from unittest.mock import MagicMock
    engine = mf.MusicFollowing(MagicMock(), {}, MagicMock())
    assert engine.arrival_scene_for("room_master") is None
    assert engine.note_arrival_scene_result("room_master", "applied") is None
    room = _room(slot_scene="scene.day_scene")
    _engine(room, engine)
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == ["scene.day_scene"]


def test_missing_welcome_scene_entity_notes_unavailable():
    room = _room(slot_scene="scene.day_scene")
    eng = _engine(room, FakeEngine(scene="scene.not_created"))
    _run(room.auto._control_lights_entry({}))
    assert _scene_calls(room) == ["scene.day_scene"]
    assert eng.notes == [("room_master", "fallback_applied")]


def test_hold_and_unavailable_reasons_differ_same_room():
    """§5.5: the engine must tell scene_skipped_hold from
    scene_skipped_unavailable; both fall back to the per-light path."""
    held = _room(slot_scene="scene.day_scene")
    e1 = _engine(held, FakeEngine(scene="scene.welcome"))
    held.auto.light_hold_allowed = lambda ents, direction: []
    _run(held.auto._control_lights_entry({}))
    gone = _room(slot_scene="scene.day_scene")
    gone.hass.set_state("scene.welcome", "unknown")
    e2 = _engine(gone, FakeEngine(scene="scene.welcome"))
    _run(gone.auto._control_lights_entry({}))
    assert e1.notes == [("room_master", "hold")]
    assert e2.notes == [("room_master", "fallback_applied")]   # retried, unlike hold
    assert _scene_calls(held) == []


def test_scene_call_raising_notes_error_and_runs_per_light_path():
    """Review C M1: the fourth reason. scene.turn_on raising with a welcome
    scene set reports ``error`` and returns False, so the per-light path runs."""
    room = _room(slot_scene="scene.day_scene")
    eng = _engine(room, FakeEngine(scene="scene.welcome"))
    real = room.auto._safe_service_call

    async def _boom(domain, service, data, *a, **k):
        if domain == "scene":
            raise RuntimeError("scene service down")
        return await real(domain, service, data, *a, **k)

    room.auto._safe_service_call = _boom
    _run(room.auto._control_lights_entry({}))
    # The slot-scene retry raises too (same scene service): fallback failed.
    assert eng.notes == [("room_master", "fallback_failed")]
    assert [c.data.get("entity_id") for c in room.hass.services.calls
            if c.domain == "light" and c.service == "turn_on"] != []

"""Arc step 8 D3 welcome scene: the engine's decision (``arrival_scene_for`` /
``note_arrival_scene_result``), PLANNING_identity_actions_v6.md rev 3.6.1 §5.6,
INV-V6-SCENE-ROOM. Intents are opened by the REAL residency producer
(``_arrival_rig``). The entry path's B2 slot retry is pinned in
``test_arrival_scene_entry_hook.py`` (it drives ``_control_lights_entry``).
"""
from __future__ import annotations

import types

import pytest
import pytest_asyncio

from test_music_following_repair import hass, mods  # noqa: F401
import _arrival_rig as A
from _arrival_rig import EZ, EZ_EID, OJI, OJI_EID, T0

H = 3600.0


@pytest_asyncio.fixture
async def r(hass, mods, tmp_path):  # noqa: F811
    rig = await A.make(hass, mods, tmp_path)
    A.set_profile(rig, OJI_EID, auto_music=False, auto_scene=True, welcome_scene="scene.oji")
    A.set_profile(rig, EZ_EID, auto_music=False, auto_scene=True, welcome_scene="scene.ez")
    try:
        yield rig
    finally:
        await rig.mf.async_teardown()
        await rig.db.stop_write_worker()


async def scene_names(r, person=OJI_EID):
    return [a["outcome"] for a in await A.outcomes(r, "welcome_scene") if a["person"] == person]


async def arrive(r, who=OJI_EID, start=T0 + 1000):
    await A.trip(r, who, 4 * H, start=start)


@pytest.mark.asyncio
async def test_entry_override_replaces_slot_scene(r):
    await arrive(r)
    assert r.mf.arrival_scene_for(r.master) == "scene.oji"
    r.mf.note_arrival_scene_result(r.master, "applied")
    await A.drain(r)
    assert await scene_names(r) == ["scene_applied"]


@pytest.mark.asyncio
async def test_scene_confirmed_when_placed(r):
    await arrive(r)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "applied")
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    assert await scene_names(r) == ["scene_applied", "scene_confirmed"]


@pytest.mark.asyncio
async def test_scene_unconfirmed_counted(r):
    await arrive(r)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "applied")
    A.Timers.fire_all(r.timers)
    await A.drain(r)
    assert "scene_unconfirmed" in await scene_names(r)


@pytest.mark.asyncio
async def test_hold_stays_per_light_no_retry(r):
    await arrive(r)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "hold")
    await A.drain(r)
    assert await scene_names(r) == ["scene_skipped_hold"]


@pytest.mark.asyncio
async def test_unavailable_welcome_retries_slot_scene(r):
    await arrive(r)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "fallback_applied")
    await A.drain(r)
    assert await scene_names(r) == ["scene_fallback_slot"]


@pytest.mark.asyncio
async def test_both_scenes_unavailable_per_light(r):
    await arrive(r)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "fallback_failed")
    await A.drain(r)
    assert await scene_names(r) == ["scene_fallback_failed"]


@pytest.mark.asyncio
async def test_scene_tracked_person_blocks(r):
    await arrive(r)
    r.layer.locations[EZ] = "Master Bedroom"
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await scene_names(r) == ["scene_skipped_occupied"]


@pytest.mark.asyncio
async def test_scene_guests_block(r):
    await arrive(r)
    r.presence.census = A.census(2)
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await scene_names(r) == ["scene_skipped_guests"]


@pytest.mark.asyncio
async def test_scene_one_unidentified_allowed(r):
    await arrive(r)
    r.presence.census = A.census(1)
    assert r.mf.arrival_scene_for(r.master) == "scene.oji"


@pytest.mark.asyncio
async def test_scene_no_near_rule_first_walker_gets_scene(r):
    await arrive(r)
    r.layer.locations[OJI] = "Kitchen"         # nobody placed in the master yet
    assert r.mf.arrival_scene_for(r.master) == "scene.oji"


@pytest.mark.asyncio
async def test_scene_ambiguous_two_owner_intents(r):
    await arrive(r)
    await arrive(r, EZ_EID, start=T0 + 1100)
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await scene_names(r) == ["scene_skipped_ambiguous"]
    assert await scene_names(r, EZ_EID) == ["scene_skipped_ambiguous"]


@pytest.mark.asyncio
async def test_scene_rooms_default_bedrooms_only(r):
    await arrive(r)
    assert r.mf.arrival_scene_for(r.bath) is None
    await A.drain(r)
    assert await scene_names(r) == []          # a bathroom: no outcome
    assert r.mf.arrival_scene_for(r.master) == "scene.oji"


@pytest.mark.asyncio
async def test_scene_shared_gates(r):
    await arrive(r)
    r.mf.update_house_state("sleep")
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await scene_names(r) == ["scene_skipped_sleep"]


@pytest.mark.asyncio
async def test_scene_quiet_hours(r):
    await arrive(r)
    r.hass.data[A.DOMAIN]["notification_manager"] = types.SimpleNamespace(
        is_quiet_hours_active=lambda: True)
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await scene_names(r) == ["scene_skipped_quiet"]


@pytest.mark.asyncio
async def test_scene_toggle_off_mid_window(r):
    await arrive(r)
    A.set_profile(r, OJI_EID, auto_scene=False)
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await scene_names(r) == ["scene_skipped_toggled_off"]


@pytest.mark.asyncio
async def test_scene_gap(r):
    await arrive(r)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "applied")
    A.Timers.fire_all(r.timers)
    await A.drain(r)
    await A.trip(r, OJI_EID, 1000)
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert "scene_skipped_gap" in await scene_names(r)


@pytest.mark.asyncio
async def test_scene_window_expired(r):
    await arrive(r)
    await A.window_end(r)
    assert await scene_names(r) == ["scene_window_expired"]
    assert r.mf.arrival_scene_for(r.master) is None   # no intent after the window


@pytest.mark.asyncio
async def test_scene_entry_missed_counted(r):
    await arrive(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    r.layer.locations[OJI] = "Kitchen"
    await A.window_end(r)
    assert await scene_names(r) == ["scene_entry_missed"]


@pytest.mark.asyncio
async def test_scene_independent_of_music_outcome(r):
    A.set_profile(r, OJI_EID, auto_music=True)
    r.world.play("master")                         # music skips: playing
    await arrive(r)
    assert "skipped_playing" in await A.names(r)
    assert r.mf.arrival_scene_for(r.master) == "scene.oji"


@pytest.mark.asyncio
async def test_engine_never_calls_scene_turn_on(r):
    await arrive(r)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "applied")
    await A.window_end(r)
    assert not [c for c in r.world.calls if c[0] == "scene"]


@pytest.mark.asyncio
async def test_scene_lost_restart_counted(r):
    await arrive(r)
    await r.mf.async_teardown()
    r.mf._arrival_init_state()
    r.mf._wall = r.wall
    r.mf._call_later = r.timers
    r.mf.async_start_arrival_actions()
    await A.drain(r)
    assert "scene_lost_restart" in await scene_names(r)

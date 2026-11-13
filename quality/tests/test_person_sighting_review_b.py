"""Person sightings Phase 1, review B fix-up (docs/reviews/code-review/
v_person_sightings_p1_B.md): B-M1 room-camera rebind on the room lifecycle
signal, B-L1 setup isolation, B-L2 face-recognition handler on the loop,
B-L3 serialised path-map loads. REAL hass + REAL presence / producer /
census / resolver (the shared rig); hand-written oracles.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

STUDY_ONLY = {"Study": [R.STUDY_FUSED]}


def _retarget_study(hass, mods, cams):
    hass.config_entries.async_get_entry("room_study_b").options[
        mods.const.CONF_ROOM_CAMERAS] = list(cams)


# ----------------------------------------------------------------- B-M1
@pytest.mark.asyncio
async def test_bm1_room_cameras_edit_rebinds_via_lifecycle_signal(mods, hass, monkeypatch):
    """Study B's fused pick is bound to the staircase. The operator replaces
    the staircase with the playroom camera in Study B's room options; the
    room lifecycle signal (options_updated) fires. The old camera's faces stop
    emitting, the new camera's faces emit as Study B, and the D4 denominator
    joins the new camera's census faces. Driven through the REAL subscription
    registered by PresenceCoordinator.async_setup."""
    rig = await R.build(mods, hass, monkeypatch, zones=STUDY_ONLY, setup=False)
    try:
        await rig.presence.async_setup()
        p = rig.presence._person_sightings
        p._setup_ts = time.time() - 700
        await R.face(rig, "staircase", "Oji")
        assert [(s.camera, s.room) for s in rig.sightings] == [(R.STUDY_FUSED, "Study B")]
        rig.sightings.clear()

        _retarget_study(hass, mods, [R.PLAYROOM])
        mods.dispatcher.async_dispatcher_send(
            hass, mods.signals.SIGNAL_ROOM_ENTRY_LIFECYCLE,
            "room_study_b", "Study B", "options_updated",
        )
        await hass.async_block_till_done()

        await R.face(rig, "staircase", "Jaya")
        assert rig.sightings == []                      # old camera unbound
        await R.face(rig, "playroom", "Ezinne")
        assert [(s.slug, s.camera, s.room) for s in rig.sightings] == [
            ("ezinne", R.STUDY_FUSED, "Study B")]
        # Denominator joins through the refreshed map: 3 playroom census
        # faces (resident Oji) are counted; staircase faces are not.
        for _ in range(3):
            R.bridge(rig, "playroom", "Oji")
        R.bridge(rig, "staircase", "Oji")
        await hass.async_block_till_done()
        assert p._denominator(time.time(), 3600.0) == 3
    finally:
        await rig.presence.async_teardown()
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_bm1_lifecycle_rebind_without_substrate(mods, hass, monkeypatch):
    """The enclosing handler rebinds even when the substrate is not built
    (the rebind sits before the substrate guard)."""
    rig = await R.build(mods, hass, monkeypatch, zones=STUDY_ONLY)
    try:
        assert rig.presence._substrate is None
        _retarget_study(hass, mods, [R.PLAYROOM])
        rig.presence._on_room_entry_lifecycle("room_study_b", "Study B", "options_updated")
        await R.face(rig, "playroom", "Oji")
        assert [(s.camera, s.room) for s in rig.sightings] == [(R.STUDY_FUSED, "Study B")]
    finally:
        await R.teardown(rig)


# ----------------------------------------------------------------- B-L1
@pytest.mark.asyncio
async def test_bl1_sighting_setup_failure_keeps_later_subscriptions(mods, hass, monkeypatch):
    """`_setup_person_sightings` raising must not skip the census subscription
    registered after it in the shared discovery block."""
    rig = await R.build(mods, hass, monkeypatch, setup=False)
    seen: list = []

    def _boom():
        raise RuntimeError("sighting setup failed")

    async def _census(*a, **k):
        seen.append(a)

    monkeypatch.setattr(rig.presence, "_setup_person_sightings", _boom)
    monkeypatch.setattr(rig.presence, "_handle_census_update", _census)
    try:
        await rig.presence.async_setup()
        mods.dispatcher.async_dispatcher_send(hass, mods.signals.SIGNAL_CENSUS_UPDATED, {})
        await hass.async_block_till_done()
        assert len(seen) == 1
    finally:
        await rig.presence.async_teardown()
        await R.teardown(rig)


# ----------------------------------------------------------------- B-L2
@pytest.mark.asyncio
async def test_bl2_face_recognition_flip_applies_on_the_loop(mods, hass, monkeypatch):
    """The switch flip is applied synchronously at dispatch (no executor hop):
    read right after async_dispatcher_send, before yielding to the loop."""
    rig = await R.build(mods, hass, monkeypatch, setup=False)
    try:
        await rig.presence.async_setup()
        assert rig.presence._face_recognition_enabled is True
        integ = hass.config_entries.async_get_entry("integ")
        integ.options[mods.const.CONF_FACE_RECOGNITION_ENABLED] = False
        mods.dispatcher.async_dispatcher_send(
            hass, mods.const.SIGNAL_URA_FACE_RECOGNITION_CHANGED)
        assert rig.presence._face_recognition_enabled is False
        await hass.async_block_till_done()
        # Teardown releases the subscription (Bug Class #38).
        await rig.presence.async_teardown()
        integ.options[mods.const.CONF_FACE_RECOGNITION_ENABLED] = True
        mods.dispatcher.async_dispatcher_send(
            hass, mods.const.SIGNAL_URA_FACE_RECOGNITION_CHANGED)
        await hass.async_block_till_done()
        assert rig.presence._face_recognition_enabled is False
    finally:
        await rig.presence.async_teardown()
        await R.teardown(rig)


# ----------------------------------------------------------------- B-L3
@pytest.mark.asyncio
async def test_bl3_path_map_loads_are_serialised(mods, hass, monkeypatch):
    """A button load and a debounced re-validation load overlapping: the
    second waits for the first (never two loads inside the read at once)."""
    c = mods.const
    integ = SimpleNamespace(entry_id="integ", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION},
                            options={})
    R.install_entries(hass, monkeypatch, [integ])
    er_, dr_ = R.registries()
    hass.data[R.DOMAIN] = {"camera_manager": R._Mgr(
        mods.resolver.CameraResolver(er_, dr_, state_getter=hass.states.get))}
    t = mods.transit.EgressDirectionTracker(hass)
    real = mods.loader.load_validated_json
    state = {"active": 0, "max": 0, "calls": 0}

    async def _slow(*a, **k):
        state["active"] += 1
        state["calls"] += 1
        state["max"] = max(state["max"], state["active"])
        try:
            for _ in range(5):
                await asyncio.sleep(0)
            return await real(*a, **k)
        finally:
            state["active"] -= 1

    monkeypatch.setattr(mods.loader, "load_validated_json", _slow)
    try:
        t._spawn_path_map_load()                       # debounced re-validation
        await asyncio.gather(t.async_load_path_map(), *list(t._path_map_tasks))
        assert state["calls"] == 2
        assert state["max"] == 1
    finally:
        await t.async_teardown()

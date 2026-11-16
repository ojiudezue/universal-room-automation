"""Arc step 8 engine: review C test-gap pass (docs/reviews/code-review/
v_step8_engine_review_C.md). Each test drives the REAL engine path through the
real residency producer (``_arrival_rig``) and goes RED on the review's exact
source mutation (row numbers in the docstrings). Oracles are hand-derived.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from test_music_following_repair import GP, hass, mods  # noqa: F401
import _arrival_rig as A
from _arrival_rig import EZ, EZ_EID, JAYA, JAYA_EID, OJI, OJI_EID, PICK, T0

H = 3600.0
MASTER = "media_player.master_bedroom_sonos_2"
STUDY3, STUDY5 = "media_player.study_a_3", "media_player.study_a_5"
STOP_FEATURE = 4096

_STAMP_TERMINALS = {
    "departure_paused", "departure_kept_returned", "departure_kept_shared",
    "departure_kept_occupied", "departure_kept_not_ours", "departure_kept_group",
    "departure_kept_other_playing", "departure_kept_toggled_off",
    "stamp_cleared_reversed", "stamp_cleared_not_ours",
}


@pytest_asyncio.fixture
async def r(hass, mods, tmp_path):  # noqa: F811
    rig = await A.make(hass, mods, tmp_path)
    try:
        yield rig
    finally:
        rig.clock.hold = False
        rig.clock.release()
        await rig.mf.async_teardown()
        await rig.db.stop_write_worker()


@pytest.fixture
def fired(monkeypatch):
    out = []

    async def fake(hass, kind, key, diagnosis="", remedy="", severity=None, **_k):
        out.append(kind)
        return True
    nm = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm")
    monkeypatch.setattr(nm, "fire_stuck_signal", fake)
    return out


def _eids(c):
    v = c[2].get("entity_id")
    return [v] if isinstance(v, str) else list(v or [])


def _calls(r, service, eid=MASTER):
    return [c for c in A.ura_calls(r, service) if eid in _eids(c)]


def _plays(r):
    return [e for c in A.ura_calls(r, "play_media") for e in _eids(c)]


async def _rows(r, who=OJI_EID, *types_):
    return [(a["outcome"], a["subtype"]) for a in await A.outcomes(r, *types_)
            if a["person"] == who]


async def _started(r, who=OJI_EID, start=T0 + 1000):
    await A.trip(r, who, 4 * H, start=start)
    assert "started" in await A.names(r, who)


async def _handed_off(r):
    await _started(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    await A.window_end(r)
    assert "arrived" in await A.names(r)


def _jaya_on_study(r):
    """Jaya's bedroom plays on Study A: native study_a_3, MA twin study_a_5."""
    entry = r.hass.config_entries.async_get_entry(r.jaya_room)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_player": STUDY3})


def _occupy(r, room, onset_ts):
    r.rooms[room].data["occupied"] = True
    r.rooms[room].onset = datetime.fromtimestamp(onset_ts, tz=timezone.utc)


def _register(r, service, handler, extra=None):
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv
    schema = {vol.Required("entity_id"): cv.entity_ids}
    schema.update(extra or {})
    r.hass.services.async_register("media_player", service, handler, schema=vol.Schema(schema))


async def _restart_reload(r):
    """CM reload shape (domain_coordinators/music_following.py: async_teardown
    then async_start_arrival_actions on the SAME engine, no state re-init)."""
    await r.mf.async_teardown()
    r.mf.async_start_arrival_actions()
    await A.drain(r)


# ===================================================================== HIGH
# --------------------------------------------------- gate 2 (#004-#008)

@pytest.mark.asyncio
async def test_gate2_no_presence_opens_no_intent(r):
    """#004: no presence coordinator -> skipped_no_presence, no intent row."""
    r.wall.t = T0 + 1000
    A._feed(r, OJI_EID, "home", "not_home")
    await A.drain(r)
    r.hass.data[A.DOMAIN]["coordinator_manager"].coordinators["presence"] = None
    await A.come_home(r, OJI_EID, T0 + 1000 + 4 * H)
    assert r.mf._arrival_counts.get("skipped_no_presence") == 1
    assert await A.names(r) == [] and not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_gate2_unresolved_resident_set_opens_no_intent(r):
    """#005: the producer stamps resident_set_resolved False (resident set
    not resolvable yet) -> skipped_no_rooms."""
    r.presence._residency._residents_fn = lambda: None
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.presence._residency.last_event[OJI_EID].resident_set_resolved is False
    assert r.mf._arrival_counts.get("skipped_no_rooms") == 1
    assert await A.names(r) == []


@pytest.mark.asyncio
async def test_gate2_untracked_person_opens_no_intent(r, monkeypatch):
    """#006: the record was produced while Oji was a resident; by the gate
    he is no longer one of the layer's tracked_persons (pc_key None)."""
    r.presence._residency._residents_fn = lambda: frozenset({OJI_EID, EZ_EID, JAYA_EID})
    monkeypatch.setattr(A.Layer, "tracked_persons", property(lambda s: [EZ, JAYA]))
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf._arrival_counts.get("skipped_no_rooms") == 1
    assert await A.names(r) == []


@pytest.mark.asyncio
async def test_gate2_both_actions_off_opens_no_intent(r):
    """#007: rooms set, auto_music and auto_scene both off."""
    A.set_profile(r, OJI_EID, auto_music=False, auto_scene=False)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf._arrival_counts.get("skipped_no_rooms") == 1
    assert await A.names(r) == []


@pytest.mark.asyncio
async def test_gate2_no_own_rooms_opens_no_intent(r):
    """#008: auto_music on, no bedroom and no bathroom."""
    A.set_profile(r, OJI_EID, rooms_bedroom=[], rooms_bathroom=[])
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf._arrival_counts.get("skipped_no_rooms") == 1
    assert await A.names(r) == []


# ------------------------------------------------- never interrupt (#099)

@pytest.mark.asyncio
async def test_never_interrupts_music_playing_on_the_ma_twin_only(r):
    """#099: the MA twin plays (the user's music via MA) while the native
    reads idle: skipped_playing, no play_media."""
    _jaya_on_study(r)
    r.hass.states.async_set(STUDY5, "playing", {"supported_features": GP})
    assert r.hass.states.get(STUDY3).state == "idle"
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert ("skipped_playing", "") in await _rows(r, JAYA_EID)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_grouped_ma_twin_skips_start(r):
    """#103 (LOW): the MA twin is grouped, the native is not."""
    _jaya_on_study(r)
    r.hass.states.async_set(STUDY5, "idle", {"supported_features": GP,
                                             "group_members": [STUDY5, "media_player.kitchen_5"]})
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert ("skipped_grouped", "") in await _rows(r, JAYA_EID)
    assert not A.ura_calls(r, "play_media")


# ---------------------------------------------------- group self (#104)

@pytest.mark.asyncio
async def test_solo_player_listing_itself_is_not_grouped(r):
    """#104: a solo player whose group_members is [itself] starts."""
    sp = r.world.speakers["master"]
    sp.group = [MASTER]
    r.world.push(sp)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("started", "") in await _rows(r)
    assert _plays(r) == [MASTER]


# --------------------------------------------- start_failed + wires (#113 #357 #359)

@pytest.mark.asyncio
async def test_play_media_raising_is_start_failed_and_releases_claims(r):
    """#113: play_media raises -> start_failed with the error type; the
    room and player claims are released; no stamp."""
    import voluptuous as vol

    async def boom(call):
        raise RuntimeError("speaker refused")
    _register(r, "play_media", boom, {vol.Required("media_content_id"): str,
                                      vol.Required("media_content_type"): str})
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("start_failed", "RuntimeError") in await _rows(r)
    assert r.mf._arrival_inflight_rooms == set() and r.mf._arrival_inflight_players == set()
    assert OJI_EID not in r.mf._arrival_stamps


@pytest.mark.asyncio
async def test_arrival_music_failing_tripwire(r, fired):
    """#357: three start_failed in 24 h fire arrival_music_failing."""
    r.world.speakers["master"].never_plays = True
    for i in range(3):
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
        await A.window_end(r)
    assert [o for o, _ in await _rows(r)].count("start_failed") == 3
    await r.mf.async_arrival_tripwires(r.db)
    assert "arrival_music_failing" in fired


@pytest.mark.asyncio
async def test_arrival_music_failing_below_threshold_quiet(r, fired):
    """Boundary: two start_failed do not fire."""
    r.world.speakers["master"].never_plays = True
    for i in range(2):
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
        await A.window_end(r)
    await r.mf.async_arrival_tripwires(r.db)
    assert "arrival_music_failing" not in fired


@pytest.mark.asyncio
async def test_arrival_entry_missed_tripwire(r, fired):
    """#359: three scene_entry_missed in 7 days fire arrival_entry_missed."""
    A.set_profile(r, OJI_EID, auto_music=False, auto_scene=True, welcome_scene="scene.oji")
    for i in range(3):
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
        r.layer.locations[OJI] = "Master Bedroom"
        r.layer.fire()
        await A.drain(r)
        r.layer.locations[OJI] = "Kitchen"
        await A.window_end(r)
    names = [o for o, _ in await _rows(r, OJI_EID, "welcome_scene")]
    assert names.count("scene_entry_missed") == 3
    await r.mf.async_arrival_tripwires(r.db)
    assert "arrival_entry_missed" in fired


@pytest.mark.asyncio
async def test_welcome_scene_failing_counts_fallback_failed(r, fired):
    """#358 (LOW): three scene_fallback_failed in 24 h fire welcome_scene_failing."""
    A.set_profile(r, OJI_EID, auto_music=False, auto_scene=True, welcome_scene="scene.oji")
    for i in range(3):
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
        assert r.mf.arrival_scene_for(r.master) == "scene.oji"
        r.mf.note_arrival_scene_result(r.master, "fallback_failed")
        await A.window_end(r)
    await r.mf.async_arrival_tripwires(r.db)
    assert "welcome_scene_failing" in fired


# ----------------------------------------------- teardown (#389 #392 #393)

@pytest.mark.asyncio
async def test_reload_then_same_person_arrives_opens_a_new_intent(r):
    """#392: a CM reload (teardown + start on the same engine) with an open
    intent; the same person's next arrival opens an intent, not
    intent_duplicate."""
    await _started(r)
    assert OJI_EID in r.mf._arrival_intents
    await _restart_reload(r)
    await A.trip(r, OJI_EID, 2 * H, start=r.wall.t + 60)
    assert (await A.names(r)).count("intent_opened") == 2
    assert not r.mf._arrival_counts.get("intent_duplicate")


@pytest.mark.asyncio
async def test_reload_drops_the_stamp_departure_does_not_pause(r):
    """#393: after a CM reload the pre-reload stamp is gone: the person's
    departure pauses nothing and writes no departure outcome."""
    await _started(r)
    await _restart_reload(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert not _calls(r, "media_pause")
    names = await A.names(r)
    assert "departed_during_wait" not in names and "departure_paused" not in names


@pytest.mark.asyncio
async def test_teardown_cancels_the_player_listener(r):
    """#389: after teardown the stamped player's state listener is gone: a
    foreign write no longer touches the (dropped) stamp."""
    await _started(r)
    stamp = r.mf._arrival_stamps[OJI_EID]
    assert stamp.player_unsub is not None
    await r.mf.async_teardown()
    assert stamp.player_unsub is None
    sp = r.world.speakers["master"]
    sp.content = "spotify:track:phone"
    r.world.push(sp)                                   # fresh (foreign) context
    await A.drain(r)
    assert not stamp.not_ours_seen and not stamp.reversed_seen


# ---------------------------------------------------- stamp end (#276)

@pytest.mark.asyncio
async def test_departure_paused_ends_the_stamp_final_timer_is_inert(r):
    """#276: after departure_paused the stamp ends; the departure wait's
    final timer then finds nothing (one stamp terminal, one pause)."""
    await _handed_off(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert ("departure_paused", "") in await _rows(r)
    assert OJI_EID not in r.mf._arrival_stamps
    await A.window_end(r)                               # the final departure timer
    terms = [o for o, _ in await _rows(r) if o in _STAMP_TERMINALS]
    assert terms == ["departure_paused"]
    assert len(_calls(r, "media_pause")) == 1


# ------------------------------------------- scene terminal (#306 #307 #314 #315 #217)

def _scene_only(r, who=OJI_EID, scene="scene.oji"):
    A.set_profile(r, who, auto_music=False, auto_scene=True, welcome_scene=scene)


@pytest.mark.asyncio
async def test_scene_confirmed_after_window_end_pops_the_intent(r):
    """#306 + #217: applied while not placed (pending_confirm); the window
    ends (the intent is kept for the confirm); a tick confirms; the terminal
    pops the intent (no leak blocking the next arrival)."""
    _scene_only(r)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf.arrival_scene_for(r.master) == "scene.oji"
    r.mf.note_arrival_scene_result(r.master, "applied")
    intent = r.mf._arrival_intents[OJI_EID]
    r.mf._on_window_timer(OJI_EID, intent.ref)          # the window timer only
    await A.drain(r)
    assert r.mf._arrival_intents.get(OJI_EID) is intent
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    assert [o for o, _ in await _rows(r, OJI_EID, "welcome_scene")] == [
        "scene_applied", "scene_confirmed"]
    assert OJI_EID not in r.mf._arrival_intents


@pytest.mark.asyncio
async def test_scene_end_is_idempotent(r):
    """#307: a second terminal on a decided intent writes nothing."""
    _scene_only(r)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    intent = r.mf._arrival_intents[OJI_EID]
    r.mf._scene_end(intent, "scene_skipped_hold")
    r.mf._scene_end(intent, "scene_unconfirmed")
    await A.drain(r)
    assert await _rows(r, OJI_EID, "welcome_scene") == [("scene_skipped_hold", "")]


@pytest.mark.asyncio
async def test_bedroom_reentry_after_decision_asks_no_second_scene(r):
    """#315: a decided intent (hold) is not re-decided on a second bedroom
    entry inside the window (no second welcome scene)."""
    _scene_only(r)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf.arrival_scene_for(r.master) == "scene.oji"
    r.mf.note_arrival_scene_result(r.master, "hold")
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await _rows(r, OJI_EID, "welcome_scene") == [("scene_skipped_hold", "")]


@pytest.mark.asyncio
async def test_music_only_intent_never_decides_a_scene(r):
    """#314: a music-only intent (scene_on False) is not a scene candidate."""
    await _started(r)
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await A.outcomes(r, "welcome_scene") == []


# =================================================================== MEDIUM
# ----------------------------------------------------- gate 3b DB path

async def _restart_fresh(r):
    from test_arrival_music import _restart
    await _restart(r)


@pytest.mark.asyncio
async def test_db_path_other_persons_departure_row_does_not_count(r):
    """#032: only Ezinne has a departure row; Oji's return after a restart
    (no RAM left_at) is departure_missing."""
    await A.depart(r, EZ_EID, T0 + 1000)
    await _restart_fresh(r)
    await A.come_home(r, OJI_EID, r.wall.t + 2 * H, old="not_home")
    assert r.mf._arrival_counts.get("skipped_not_counted_return:departure_missing") == 1
    assert "intent_opened" not in await A.names(r)


@pytest.mark.asyncio
async def test_db_path_short_absence_3599(r, monkeypatch, mods):  # noqa: F811
    """#030: DB row 3599 s before the edge, min away 3600 -> short_absence."""
    monkeypatch.setattr(mods.const, "ARRIVAL_MIN_AWAY_S", 3600)
    await A.depart(r, OJI_EID, T0 + 1000)
    await _restart_fresh(r)
    await A.come_home(r, OJI_EID, T0 + 1000 + 3599)
    assert r.mf._arrival_counts.get("skipped_not_counted_return:short_absence") == 1
    assert "intent_opened" not in await A.names(r)


@pytest.mark.asyncio
async def test_db_path_boundary_3600_passes(r, monkeypatch, mods):  # noqa: F811
    """#031: exactly min away -> passes (>=)."""
    monkeypatch.setattr(mods.const, "ARRIVAL_MIN_AWAY_S", 3600)
    await A.depart(r, OJI_EID, T0 + 1000)
    await _restart_fresh(r)
    await A.come_home(r, OJI_EID, T0 + 1000 + 3600)
    assert "intent_opened" in await A.names(r)


@pytest.mark.asyncio
async def test_db_path_newest_departure_row_wins(r):
    """#034 (LOW): depart, return, depart again; after a restart the newest
    departure (after the arrival row) passes gate 3b."""
    await A.depart(r, OJI_EID, T0 + 1000)
    await A.come_home(r, OJI_EID, T0 + 1000 + 2 * H)
    await A.depart(r, OJI_EID, T0 + 1000 + 3 * H)
    await _restart_fresh(r)
    await A.come_home(r, OJI_EID, r.wall.t + 2 * H)
    assert (await A.names(r)).count("intent_opened") == 2


# ------------------------------------------------------ target / pick

@pytest.mark.asyncio
async def test_bedroom_with_player_wins_over_bathroom_with_player(r):
    """#044: both an own bedroom (Study A) and an own bathroom (the master)
    have players: the bedroom is the target."""
    A.set_profile(r, OJI_EID, rooms_bedroom=[r.ids["Study A"]], rooms_bathroom=[r.master])
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    opened = [a for a in await A.outcomes(r) if a["outcome"] == "intent_opened"]
    assert opened[0]["target_room"] == r.ids["Study A"]
    assert not _calls(r, "play_media")


@pytest.mark.asyncio
async def test_no_usable_pick_is_skipped_no_media(r):
    """#079: no music configured -> skipped_no_media, no play_media."""
    A.set_profile(r, OJI_EID, music_default=None)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("skipped_no_media", "") in await _rows(r)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_dark_room_plays_the_evening_pick(r):
    """#080: the TARGET room's dark read selects the evening pick."""
    evening = dict(PICK, media_content_id="library://playlist/evening")
    day = dict(PICK, media_content_id="library://playlist/day")
    A.set_profile(r, OJI_EID, music_vary_time=True, music_day=day, music_evening=evening)
    r.rooms[r.master].automation = types.SimpleNamespace(
        is_sleep_mode_active=lambda: False, is_dark=lambda _lux=None: True)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    calls = _calls(r, "play_media")
    assert [c[2]["media_content_id"] for c in calls] == ["library://playlist/evening"]


# --------------------------------------------------------- zone fallback

def _jaya_zone(r, mods, zone_player):  # noqa: F811
    entry = r.hass.config_entries.async_get_entry(r.jaya_room)
    data = dict(entry.data)
    data.pop("room_media_player", None)
    data["zone"] = "Upstairs"
    data["area_id"] = "no_speaker_area"
    r.hass.config_entries.async_update_entry(entry, data=data, options={})
    mods.MockConfigEntry(domain=A.DOMAIN, data={
        "entry_type": "zone", "zone_name": "Upstairs",
        "zone_player_entity": zone_player}).add_to_hass(r.hass)
    for who in (OJI, EZ):
        r.layer.locations[who] = "Study A"


@pytest.mark.asyncio
async def test_zone_player_room_unresolved_skips(r, mods):  # noqa: F811
    """#085: the zone player (utility, no URA room has its area) -> no start."""
    _jaya_zone(r, mods, "media_player.utility_3")
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert ("skipped_no_player", "zone_room_unresolved") in await _rows(r, JAYA_EID)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_zone_room_backstop_blocks(r, mods):  # noqa: F811
    """#089: the zone player's room (Kitchen) reads occupied 30 min before
    the arrival, nobody placed there -> skipped_occupied backstop."""
    _jaya_zone(r, mods, "media_player.kitchen_3")
    r.layer.locations[JAYA] = "Study A"
    _occupy(r, r.ids["Kitchen"], T0 + 1000 + 2 * H - 1800)
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert ("skipped_occupied", "backstop") in await _rows(r, JAYA_EID)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_zone_room_backstop_skipped_for_own_placement(r, mods):  # noqa: F811
    """#090: Jaya herself placed in the zone room: its occupancy is hers."""
    _jaya_zone(r, mods, "media_player.kitchen_3")
    r.layer.locations[JAYA] = "Kitchen"
    _occupy(r, r.ids["Kitchen"], T0 + 1000 + 2 * H - 1800)
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert ("started", "") in await _rows(r, JAYA_EID)


# ---------------------------------------------------- claims / hazard / volume

@pytest.mark.asyncio
async def test_ma_claim_released_second_start_on_same_twin(r):
    """#097: the MA twin's in-flight claim is released after the start: a
    later start on the same player still starts."""
    _jaya_on_study(r)
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    await A.window_end(r)
    assert _plays(r) == [STUDY5]
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000 + 6 * H)
    assert [o for o, _ in await _rows(r, JAYA_EID)].count("started") == 2
    assert _plays(r) == [STUDY5, STUDY5]


@pytest.mark.asyncio
async def test_hazard_stop_reaches_an_arrival_started_player(r):
    """#106: the room's player is re-configured after the arrival start; the
    hazard stop still reaches the speaker the arrival started."""
    await _started(r)
    entry = r.hass.config_entries.async_get_entry(r.master)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_player": STUDY3})
    assert MASTER not in r.mf.configured_players()
    await r.mf.async_hazard_stop("smoke")
    await A.drain(r)
    assert len(_calls(r, "media_stop")) == 1
    assert r.world.state("master") == "idle"


@pytest.mark.asyncio
async def test_volume_scale_applied_and_clamped(r):
    """#111: 0.8 x 1.5 = 1.2 clamps to 1.0."""
    A.set_profile(r, OJI_EID, music_volume=0.8)
    entry = r.hass.config_entries.async_get_entry(r.master)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_volume_scale": 1.5})
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert [c[2]["volume_level"] for c in _calls(r, "volume_set")] == [1.0]


@pytest.mark.asyncio
async def test_volume_scale_below_one(r):
    """#111: 0.5 x 0.8 = 0.4."""
    A.set_profile(r, OJI_EID, music_volume=0.5)
    entry = r.hass.config_entries.async_get_entry(r.master)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_volume_scale": 0.8})
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert [c[2]["volume_level"] for c in _calls(r, "volume_set")] == [0.4]


# ----------------------------------------------------------- ownership

@pytest.mark.asyncio
async def test_foreign_write_on_the_played_ma_twin_ends_ownership(r):
    """#163: the start plays on the MA twin; a foreign content change on the
    twin alone ends ownership: no window-end stop."""
    _jaya_on_study(r)
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert r.mf._arrival_stamps[JAYA_EID].play_eid == STUDY5
    st = r.hass.states.get(STUDY5)
    r.hass.states.async_set(STUDY5, "playing",
                            dict(st.attributes, media_content_id="spotify:track:phone"))
    await A.drain(r)
    await A.window_end(r)
    assert ("wait_ended_not_ours", "") in await _rows(r, JAYA_EID)
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.parametrize("change", [{"volume": 0.0}, {"state": "standby"}])
@pytest.mark.asyncio
async def test_foreign_mute_or_standby_is_reversed(r, change):
    """#160 / #161 (LOW): volume 0 and standby by hand are reversals."""
    await _started(r)
    sp = r.world.speakers["master"]
    for k, v in change.items():
        setattr(sp, k, v)
    r.world.push(sp)
    await A.drain(r)
    assert ("reversed", "") in await _rows(r)


# --------------------------------------------------------- window end

@pytest.mark.asyncio
async def test_pause_only_player_window_end_pauses(r):
    """#234: no STOP feature (but other features) -> media_pause."""
    r.world.features[MASTER] = GP
    r.world.push(r.world.speakers["master"])
    await _started(r)
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_pause") in await _rows(r)
    assert len(_calls(r, "media_pause")) == 1 and not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_no_features_reported_window_end_stops(r):
    """#236: supported_features 0 -> media_stop (the default)."""
    r.world.features[MASTER] = 0
    r.world.push(r.world.speakers["master"])
    await _started(r)
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)
    assert len(_calls(r, "media_stop")) == 1


@pytest.mark.asyncio
async def test_stop_failure_still_records_the_outcome(r):
    """#241 (LOW): the window-end stop raising is swallowed; the outcome is
    still written and the stamp claim released."""
    async def boom(call):
        raise RuntimeError("stop refused")
    _register(r, "media_stop", boom)
    await _started(r)
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)


@pytest.mark.asyncio
async def test_stop_watch_ends_the_stamp(r):
    """#245 / #247: the ARRIVAL_REVERSAL_S watch timer ends the stamp; a
    later arrival in the room is not stopped_then_arrived."""
    await _started(r)
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)
    assert OJI_EID in r.mf._arrival_stamps            # watching
    await A.window_end(r)                              # the watch timer
    assert OJI_EID not in r.mf._arrival_stamps
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    assert "stopped_then_arrived" not in await A.names(r)


def _move(who_eid, to_room):
    return types.SimpleNamespace(
        person_entity=who_eid, from_room="Kitchen", to_room=to_room,
        ts=datetime.fromtimestamp(T0 + 1000 + 4 * H + 300, tz=timezone.utc))


@pytest.mark.asyncio
async def test_move_log_other_persons_move_is_not_reach(r):
    """#250: Ezinne's move into the master bath is not Oji's reach."""
    await _started(r)
    r.layer.moves.append(_move(EZ_EID, "Master Bath"))
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)


@pytest.mark.asyncio
async def test_move_log_move_into_non_own_room_is_not_reach(r):
    """#251: Oji's move into the Study (not his) is not reach."""
    await _started(r)
    r.layer.moves.append(_move(OJI_EID, "Study A"))
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)


async def _ez_handed_off_stamp(r, room_name):
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r, EZ_EID)
    r.layer.locations[EZ] = room_name
    r.layer.fire()
    await A.drain(r)
    await A.window_end(r)
    assert "arrived" in await A.names(r, EZ_EID)
    r.layer.locations[EZ] = "Kitchen"
    stamp = r.mf._arrival_stamps[EZ_EID]
    assert stamp.handed_off and not stamp.done


@pytest.mark.asyncio
async def test_coowner_handed_off_stamp_in_suite_keeps(r):
    """#256: Ezinne's handed-off stamp plays in Oji's suite (the master);
    Oji's start on his Study at window end is kept (co_owner)."""
    A.set_profile(r, OJI_EID, rooms_bedroom=[r.ids["Study A"]], rooms_bathroom=[r.master])
    await _ez_handed_off_stamp(r, "Master Bedroom")
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + 6 * H)
    assert "started" in await A.names(r)
    await A.window_end(r)
    assert ("wait_kept_occupied", "co_owner") in await _rows(r)
    assert not _calls(r, "media_stop", STUDY5) and not _calls(r, "media_stop", STUDY3)


@pytest.mark.asyncio
async def test_coowner_waiting_stamp_does_not_keep(r):
    """#257: Ezinne's stamp is still waiting (not handed off): it is no
    listener; Oji's start is stopped at his window end."""
    A.set_profile(r, OJI_EID, rooms_bedroom=[r.ids["Study A"]], rooms_bathroom=[r.master])
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r, EZ_EID)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1100)
    assert "started" in await A.names(r)
    intent = r.mf._arrival_intents[OJI_EID]
    r.mf._on_window_timer(OJI_EID, intent.ref)
    await A.drain(r)
    assert "wait_expired_stopped" in await A.names(r)
    assert "wait_kept_occupied" not in await A.names(r)


@pytest.mark.asyncio
async def test_coowner_stamp_outside_suite_does_not_keep(r):
    """#258: Ezinne's handed-off stamp plays in a room outside Oji's suite."""
    A.set_profile(r, EZ_EID, rooms_bedroom=[r.jaya_room], rooms_bathroom=[])
    await _ez_handed_off_stamp(r, "Jaya Bedroom")
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + 6 * H)
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)


@pytest.mark.asyncio
async def test_observation_or_coordinator_off_mid_window(r):
    """#135 / #136 (LOW): the window end re-reads coordinator and observation."""
    await _started(r)
    r.wrapper.observation_mode = True
    await A.window_end(r)
    assert ("wait_ended_toggled_off", "observation") in await _rows(r)
    r.wrapper.observation_mode = False
    await _started(r, JAYA_EID, start=T0 + 1000 + 6 * H)
    A.set_cm(r, music_following_coordinator_enabled=False)
    await A.window_end(r)
    assert ("wait_ended_toggled_off", "coordinator") in await _rows(r, JAYA_EID)


# ------------------------------------------------------------ departure

@pytest.mark.asyncio
async def test_other_persons_arrival_is_not_this_persons_return(r):
    """#280: Ezinne's arrival during Oji's departure wait does not count as
    Oji's return: the pause happens when the suite empties."""
    await A.depart(r, EZ_EID, T0 + 500)                # Ezinne away all along
    await _handed_off(r)
    _occupy(r, r.master, T0)
    dep = r.wall.t + H
    await A.depart(r, OJI_EID, dep)
    await A.come_home(r, EZ_EID, dep + 60)              # Ezinne returns after dep
    assert r.presence._residency.last_event[EZ_EID].edge_ts > dep
    r.rooms[r.master].data["occupied"] = False
    r.layer.fire()
    await A.drain(r)
    assert ("departure_paused", "") in await _rows(r)
    assert len(_calls(r, "media_pause")) == 1


@pytest.mark.asyncio
async def test_departure_without_presence_fails_closed(r):
    """#283 (LOW): no presence coordinator at the departure check ->
    departure_kept_returned truncated (never a blind pause)."""
    await _handed_off(r)
    r.hass.data[A.DOMAIN]["coordinator_manager"].coordinators["presence"] = None
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert ("departure_kept_returned", "truncated") in await _rows(r)
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_edge_read_error_fails_closed(r):
    """#284 (LOW): the return-edge read raises -> truncated, no pause."""
    await _handed_off(r)

    def boom(*_a, **_k):
        raise RuntimeError("ring gone")
    r.presence.get_person_edges_since = boom
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert ("departure_kept_returned", "truncated") in await _rows(r)
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_reversal_during_departure_wait_clears_stamp(r):
    """#288 (LOW): a hand pause while the departure wait is armed ->
    stamp_cleared_reversed (not departure_kept_not_ours)."""
    await _handed_off(r)
    _occupy(r, r.master, T0)
    await A.depart(r, OJI_EID, r.wall.t + H)
    sp = r.world.speakers["master"]
    sp.state = "paused"
    r.world.push(sp)
    await A.drain(r)
    assert ("stamp_cleared_reversed", "") in await _rows(r)


@pytest.mark.asyncio
async def test_departure_pause_failure_still_records_the_outcome(r):
    """#301 (LOW): media_pause raising is swallowed; departure_paused is
    recorded and the stamp ends."""
    async def boom(call):
        raise RuntimeError("pause refused")
    _register(r, "media_pause", boom)
    await _handed_off(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert ("departure_paused", "") in await _rows(r)
    assert OJI_EID not in r.mf._arrival_stamps


# ------------------------------------------------------------ restart sweep

@pytest.mark.asyncio
async def test_sweep_ignores_an_intent_with_a_terminal(r):
    """#348 / #349: a window that ended (wait_expired_stopped) before the
    restart is neither wait_lost_restart nor departure_stamp_lost_restart."""
    await _started(r)
    await A.window_end(r)
    await A.window_end(r)                               # the stop watch ends
    await _restart_fresh(r)
    names = await A.names(r)
    assert "wait_lost_restart" not in names
    assert "departure_stamp_lost_restart" not in names


@pytest.mark.asyncio
async def test_sweep_ignores_an_intent_outside_the_window(r):
    """#342: an opened intent with no terminal, opened more than window +
    extra before the restart, is not reported lost."""
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    await r.mf.async_teardown()
    real = r.db.read_memory_episodes_by_type

    async def only_opened(t, since=None):
        out = await real(t, since)
        return [x for x in out if (x["attrs"] or {}).get("outcome") == "intent_opened"]
    r.db.read_memory_episodes_by_type = only_opened
    r.wall.t += 2 * H                                   # > 900 + 3600 after the open
    r.mf._arrival_init_state()
    r.mf._wall = r.wall
    r.mf._call_later = r.timers
    r.mf.async_start_arrival_actions()
    await A.drain(r)
    r.db.read_memory_episodes_by_type = real
    names = await A.names(r)
    assert "intent_lost_restart" not in names and "wait_lost_restart" not in names


# ------------------------------------------------------------ registry / flag

@pytest.mark.asyncio
async def test_disabled_ma_twin_is_never_the_play_target(r):
    """#419: the MA twin is disabled in the registry -> play on the native."""
    from homeassistant.helpers import entity_registry as er
    _jaya_on_study(r)
    er.async_get(r.hass).async_update_entity(
        STUDY5, disabled_by=er.RegistryEntryDisabler.USER)
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert _plays(r) == [STUDY3]


@pytest.mark.asyncio
async def test_scene_only_profile_is_opted_in(r):
    """#379: no profile has auto_music, one has auto_scene -> opted in (the
    writer health check keeps checking the arrival types)."""
    for who in (OJI_EID, EZ_EID, JAYA_EID):
        A.set_profile(r, who, auto_music=False, auto_scene=False)
    A.set_profile(r, OJI_EID, auto_scene=True, welcome_scene="scene.oji")
    assert r.mf.arrival_opted_in() is True
    r.db.hass.data = r.hass.data
    stats = await r.db.run_memory_writer_health_check(triggered_by="manual")
    assert "welcome_scene" not in stats["switch_off_types"]


@pytest.mark.asyncio
async def test_teardown_drops_its_own_opt_in_flag(r):
    """#397: teardown removes the flag this engine published."""
    from custom_components.universal_room_automation import const
    key = const.ARRIVAL_ACTIONS_OPTED_IN_HASS_KEY
    assert key in r.hass.data[A.DOMAIN]
    await r.mf.async_teardown()
    assert key not in r.hass.data[A.DOMAIN]


@pytest.mark.asyncio
async def test_teardown_keeps_another_engines_flag(r):
    """#398: a flag published by another engine instance is left alone."""
    from custom_components.universal_room_automation import const
    key = const.ARRIVAL_ACTIONS_OPTED_IN_HASS_KEY
    flag_cls = type(r.hass.data[A.DOMAIN][key])
    other = flag_cls(types.SimpleNamespace(arrival_opted_in=lambda: True))
    r.hass.data[A.DOMAIN][key] = other
    await r.mf.async_teardown()
    assert r.hass.data[A.DOMAIN].get(key) is other


# ====================================================================== LOW

@pytest.mark.asyncio
async def test_coordinator_off_at_gate1_writes_no_row(r):
    """#001: the coordinator switch off -> skipped_master_off, no intent row."""
    A.set_cm(r, music_following_coordinator_enabled=False)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf._arrival_counts.get("skipped_master_off") == 1
    assert await A.names(r) == []


@pytest.mark.parametrize("missing,sub", [
    ("counted", "not_counted"), ("source_stale", "stale_source"), ("in_boot_window", "boot")])
@pytest.mark.asyncio
async def test_record_missing_flag_fails_closed(r, missing, sub):
    """#010 / #012 / #014: a record without the flag attribute fails closed."""
    fields = dict(kind="arrival", person=OJI_EID, edge_ts=T0 + 5 * H, old_state="not_home",
                  resident_set_resolved=True, counted=True, source_stale=False,
                  in_boot_window=False)
    del fields[missing]
    await r.mf._async_arrival(types.SimpleNamespace(**fields))
    assert r.mf._arrival_counts.get(f"skipped_not_counted_return:{sub}") == 1
    assert await A.names(r) == []


@pytest.mark.asyncio
async def test_gap_boundary_exactly_one_hour_starts(r):
    """#077: a second start exactly ARRIVAL_MIN_GAP_S (3600 s) after the
    first is allowed (strictly less is the gap)."""
    await _started(r)
    t1 = r.mf._arrival_last_music[OJI_EID]
    await A.window_end(r)
    await A.window_end(r)
    await A.trip(r, OJI_EID, 3000, start=t1 + 600)
    assert r.wall.t == t1 + 3600
    assert [o for o, _ in await _rows(r)].count("started") == 2


@pytest.mark.asyncio
async def test_last_arrival_action_tracks_the_latest_outcome(r):
    """#365 (LOW): the display read returns the last outcome row."""
    await _started(r)
    assert r.mf.last_arrival_action(OJI_EID)["outcome"] == "started"
    await A.window_end(r)
    assert r.mf.last_arrival_action(OJI_EID)["outcome"] == "wait_expired_stopped"


@pytest.mark.asyncio
async def test_scene_toggle_needs_a_welcome_scene(r):
    """#139 (LOW): auto_scene on but no welcome scene -> toggled off."""
    A.set_profile(r, OJI_EID, auto_music=False, auto_scene=True, welcome_scene="")
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert await _rows(r, OJI_EID, "welcome_scene") == [("scene_skipped_toggled_off", "")]


@pytest.mark.asyncio
async def test_non_scene_welcome_value_returns_none(r):
    """#326 (LOW): a welcome value that is not a scene entity is never returned."""
    _scene_only(r, scene="light.not_a_scene")
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert r.mf.arrival_scene_for(r.master) is None


@pytest.mark.asyncio
async def test_placement_in_own_bathroom_is_not_entry_missed(r):
    """#190 (LOW): placed only in his own bathroom (not a bedroom) ->
    scene_window_expired, not scene_entry_missed."""
    _scene_only(r)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    r.layer.locations[OJI] = "Master Bath"
    r.layer.fire()
    await A.drain(r)
    r.layer.locations[OJI] = "Kitchen"
    await A.window_end(r)
    assert await _rows(r, OJI_EID, "welcome_scene") == [("scene_window_expired", "")]


@pytest.mark.asyncio
async def test_confirm_timeout_reads_placement_itself(r):
    """#338 (LOW): placed in the room with no tick; the confirm timer's own
    read confirms."""
    _scene_only(r)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    r.mf.arrival_scene_for(r.master)
    r.mf.note_arrival_scene_result(r.master, "applied")
    r.layer.locations[OJI] = "Master Bedroom"          # no fire(): no tick
    intent = r.mf._arrival_intents[OJI_EID]
    r.mf._scene_confirm_timeout(intent)
    await A.drain(r)
    assert [o for o, _ in await _rows(r, OJI_EID, "welcome_scene")] == [
        "scene_applied", "scene_confirmed"]


@pytest.mark.asyncio
async def test_teardown_cancels_inflight_start_task(r):
    """#391 (LOW): teardown cancels an in-flight start task (held verify):
    no arrival task outlives the teardown."""
    r.wall.t = T0 + 1000
    A._feed(r, OJI_EID, "home", "not_home")
    await A.drain(r)
    r.clock.hold = True
    r.wall.t = T0 + 1000 + 4 * H
    A._feed(r, OJI_EID, "not_home", "home")
    from test_music_following_repair import until
    await until(lambda: r.clock.waiters, n=2000)
    tasks = [t for t in r.mf._arrival_tasks if not t.done()]
    assert tasks
    await asyncio.wait_for(r.mf.async_teardown(), timeout=2)
    assert all(t.done() for t in tasks)

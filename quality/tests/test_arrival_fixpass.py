"""Arc step 8 engine fix pass (reviews A+G, B, D of f7277a07; orchestrator
rulings 2026-11-15). Real residency producer, real MusicFollowing, real
speaker simulator (``_arrival_rig``). Oracles are hand-derived.

Ownership (orchestrator default, pending operator confirmation): music is
ours from a successful start until a write to the played entity carrying a
context music following did not create.
"""
from __future__ import annotations

import asyncio
import types
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from test_music_following_repair import hass, mods, until  # noqa: F401
import _arrival_rig as A
from _arrival_rig import EZ, EZ_EID, JAYA_EID, OJI, OJI_EID, T0

H = 3600.0
MASTER = "media_player.master_bedroom_sonos_2"


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


def _eids(c):
    v = c[2].get("entity_id")
    return [v] if isinstance(v, str) else list(v or [])


def _calls(r, service, eid=MASTER):
    return [c for c in A.ura_calls(r, service) if eid in _eids(c)]


async def _rows(r, who=OJI_EID):
    return [(a["outcome"], a["subtype"]) for a in await A.outcomes(r) if a["person"] == who]


async def _started(r, who=OJI_EID):
    await A.trip(r, who, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r, who)


async def _handed_off(r):
    await _started(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    await A.window_end(r)
    assert "arrived" in await A.names(r)


def _foreign(r, speaker="master", **changes):
    """A write by someone else (phone, MA UI, the device's own update):
    a fresh HA context."""
    sp = r.world.speakers[speaker]
    for k, v in changes.items():
        setattr(sp, k, v)
    r.world.push(sp)


async def _spin(n=60):
    for _ in range(n):
        await asyncio.sleep(0)


async def _arrive_held(r, who, at):
    """Depart + return with the verify sleep HELD (no drain: it would block)."""
    r.wall.t = at - 4 * H
    A._feed(r, who, "home", "not_home")
    await A.drain(r)
    r.clock.hold = True
    r.wall.t = at
    A._feed(r, who, "not_home", "home")
    await until(lambda: r.clock.waiters, n=2000)


async def _release(r):
    r.clock.hold = False
    r.clock.release()
    await A.drain(r)


# ============================================================ ownership (G-1/D1)

@pytest.mark.asyncio
async def test_window_end_stops_with_the_context_rule_alone(r):
    """ARRIVAL_OURS_ATTR None (shipped): no foreign write since the start ->
    the window-end stop is ACTIVE (was withheld, wait_kept_unverified)."""
    await _started(r)
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)
    assert len(_calls(r, "media_stop")) == 1


@pytest.mark.asyncio
async def test_foreign_context_track_change_ends_ownership_no_stop(r):
    """A content change written with a non-URA context (a track change, a
    podcast from the phone) ends ownership: no stop at window end."""
    await _started(r)
    _foreign(r, content="spotify:track:other")
    await A.drain(r)
    await A.window_end(r)
    assert ("wait_ended_not_ours", "") in await _rows(r)
    assert not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_foreign_pause_is_reversed_idle_is_not_ours(r):
    await _started(r)
    _foreign(r, state="idle")
    await A.drain(r)
    assert ("wait_ended_not_ours", "") in await _rows(r)
    assert not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_position_only_write_keeps_ownership(r):
    """An attribute-only write that changes only media_position (named in
    ARRIVAL_OWNERSHIP_IGNORED_ATTRS) is not a change of what plays."""
    await _started(r)
    st = r.hass.states.get(MASTER)
    attrs = dict(st.attributes)
    attrs["media_position"] = 99
    r.hass.states.async_set(MASTER, st.state, attrs)          # fresh context
    await A.drain(r)
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)


@pytest.mark.asyncio
async def test_ura_context_volume_write_keeps_ownership(r):
    """A write made by music following's own call (recorded context id)
    does not end ownership."""
    await _started(r)
    await r.mf._call("media_player", "volume_set",
                     {"entity_id": MASTER, "volume_level": 0.4})
    await A.drain(r)
    stamp = r.mf._arrival_stamps[OJI_EID]
    assert not stamp.not_ours_seen and not stamp.reversed_seen
    await A.window_end(r)
    assert ("wait_expired_stopped", "media_stop") in await _rows(r)


@pytest.mark.asyncio
async def test_unrecorded_ura_marked_context_ends_ownership(r):
    """A URA-marked context music following did not create (another URA
    writer) is NOT one of the recorded ids: it ends ownership."""
    import importlib
    ctx = importlib.import_module("custom_components.universal_room_automation.ura_context")
    await _started(r)
    sp = r.world.speakers["master"]
    sp.content = "tts://announcement"
    r.world.push(sp, ctx.ura_write_context())
    await A.drain(r)
    await A.window_end(r)
    assert not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_music_following_transfer_keeps_ownership_foreign_group_ends_it(r):
    """Handed off; a real music-following "play in both rooms" move joins
    Study A to the master (the join writes the master with MF's context):
    ownership holds and the departure reads the group (departure_kept_group),
    not "not ours"."""
    from test_music_following_repair import move, set_area
    await _handed_off(r)
    r.mf.apply_config({"mf_follow_mode": "extend"})
    set_area(r, "Study A")
    r.layer.locations[OJI] = "Study A"
    assert await move(r, "Master Bedroom", "Study A") in ("success", "success_nudged")
    await A.drain(r)
    stamp = r.mf._arrival_stamps[OJI_EID]
    assert not stamp.done and not stamp.not_ours_seen and not stamp.reversed_seen
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert ("departure_kept_group", "") in await _rows(r)
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_foreign_write_after_handoff_clears_stamp_no_pause(r):
    await _handed_off(r)
    _foreign(r, content="spotify:track:phone")
    await A.drain(r)
    assert ("stamp_cleared_not_ours", "") in await _rows(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_pauses_with_the_context_rule_alone(r):
    """ARRIVAL_OURS_ATTR None: the departure pause is ACTIVE."""
    await _handed_off(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert ("departure_paused", "") in await _rows(r)
    assert len(_calls(r, "media_pause")) == 1


@pytest.mark.asyncio
async def test_ours_attr_set_both_conditions_must_hold(r, monkeypatch, mods):  # noqa: F811
    """ARRIVAL_OURS_ATTR set: no foreign write (context holds) but the stamped
    value changed (a URA-context write) -> not ours, no stop."""
    monkeypatch.setattr(mods.const, "ARRIVAL_OURS_ATTR", "media_content_id")
    await _started(r)
    sp = r.world.speakers["master"]
    sp.content = "library://playlist/other"
    await r.mf._call("media_player", "volume_set", {"entity_id": MASTER, "volume_level": 0.3})
    await A.drain(r)
    await A.window_end(r)
    assert ("wait_ended_not_ours", "") in await _rows(r)
    assert not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_concurrent_ticks_send_exactly_one_pause(r):
    """Reviews A-1 / D1: two ticks racing on a departure-armed stamp. The
    stamp is claimed (acting) before the pause await, so one pause and one
    outcome."""
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv
    await _handed_off(r)
    r.rooms[r.master].data["occupied"] = True
    r.rooms[r.master].onset = datetime.fromtimestamp(T0, tz=timezone.utc)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert not _calls(r, "media_pause")

    async def slow_pause(call):
        r.world._rec(call)
        for _ in range(5):
            await asyncio.sleep(0)
        sp = r.world.by_entity[MASTER]
        sp.state = "paused"
        r.world.push(sp, call.context)
    r.hass.services.async_register("media_player", "media_pause", slow_pause,
                                   schema=vol.Schema({vol.Required("entity_id"): cv.entity_ids}))
    r.rooms[r.master].data["occupied"] = False
    await asyncio.gather(r.mf._arrival_tick(), r.mf._arrival_tick())
    await A.drain(r)
    assert len(_calls(r, "media_pause")) == 1
    assert [o for o, _ in await _rows(r)].count("departure_paused") == 1


@pytest.mark.asyncio
async def test_window_end_stop_claims_stamp_departure_ignored(r):
    """Review B-L3: a departure while the window-end stop is in flight is
    ignored (the stop watch is armed before the await); one terminal."""
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv
    await _started(r)
    gate = asyncio.Event()

    async def slow_stop(call):
        # The device echoes idle with OUR context at once, then the call
        # returns late: a tick in between must not record "not ours".
        r.world._rec(call)
        sp = r.world.by_entity[MASTER]
        sp.state = "idle"
        r.world.push(sp, call.context)
        await gate.wait()
    r.hass.services.async_register("media_player", "media_stop", slow_stop,
                                   schema=vol.Schema({vol.Required("entity_id"): cv.entity_ids}))
    r.timers.fire_all()
    await until(lambda: _calls(r, "media_stop"), n=2000)
    r.wall.t += 60
    A._feed(r, OJI_EID, "home", "not_home")
    await _spin()
    gate.set()
    await A.drain(r)
    names = [o for o, _ in await _rows(r)]
    assert "wait_expired_stopped" in names and "departed_during_wait" not in names
    assert "wait_ended_not_ours" not in names
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_window_end_stop_with_reversal_zero_departure_ignored(r, monkeypatch, mods):  # noqa: F811
    """Config extreme ARRIVAL_REVERSAL_S 0 (no stop watch): the departure in
    the stop's await is still ignored (the stamp is claimed), then the stamp
    ends; no pause ever."""
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv
    monkeypatch.setattr(mods.const, "ARRIVAL_REVERSAL_S", 0)
    await _started(r)
    gate = asyncio.Event()

    async def slow_stop(call):
        r.world._rec(call)
        await gate.wait()
    r.hass.services.async_register("media_player", "media_stop", slow_stop,
                                   schema=vol.Schema({vol.Required("entity_id"): cv.entity_ids}))
    r.timers.fire_all()
    await until(lambda: _calls(r, "media_stop"), n=2000)
    r.wall.t += 60
    A._feed(r, OJI_EID, "home", "not_home")
    await _spin()
    gate.set()
    await A.drain(r)
    names = [o for o, _ in await _rows(r)]
    assert names.count("wait_expired_stopped") == 1 and "departed_during_wait" not in names
    assert OJI_EID not in r.mf._arrival_stamps
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_window_end_own_ours_check_without_a_tick(r):
    """The window end's own ownership read (no tick ran after the foreign
    write): no stop."""
    await _started(r)

    async def no_tick():
        return None
    r.mf._arrival_tick = no_tick
    _foreign(r, content="spotify:track:phone")
    await A.drain(r)
    await A.window_end(r)
    assert ("wait_ended_not_ours", "") in await _rows(r)
    assert not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_departure_own_ours_check_without_a_tick(r):
    """The departure wait's final check reads ownership itself."""
    await _handed_off(r)
    r.rooms[r.master].data["occupied"] = True
    await A.depart(r, OJI_EID, r.wall.t + H)

    async def no_tick():
        return None
    r.mf._arrival_tick = no_tick
    _foreign(r, content="spotify:track:phone")
    await A.drain(r)
    r.rooms[r.master].data["occupied"] = False
    await A.window_end(r)                          # the departure wait's end
    assert ("departure_kept_not_ours", "") in await _rows(r)
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_two_concurrent_departure_checks_one_pause(r):
    """The departure check's own claim (no tick involved)."""
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv
    await _handed_off(r)
    r.rooms[r.master].data["occupied"] = True
    await A.depart(r, OJI_EID, r.wall.t + H)

    async def slow_pause(call):
        r.world._rec(call)
        for _ in range(5):
            await asyncio.sleep(0)
    r.hass.services.async_register("media_player", "media_pause", slow_pause,
                                   schema=vol.Schema({vol.Required("entity_id"): cv.entity_ids}))
    r.rooms[r.master].data["occupied"] = False
    stamp = r.mf._arrival_stamps[OJI_EID]
    await asyncio.gather(r.mf._departure_check(stamp, final=False),
                         r.mf._departure_check(stamp, final=False))
    await A.drain(r)
    assert len(_calls(r, "media_pause")) == 1


# ================================================================ hazard (B-H1)

@pytest.mark.asyncio
async def test_hazard_block_skips_start(r):
    r.mf._hazard_until = r.mf._monotonic() + 1000
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("skipped_hazard", "before_play") in await _rows(r)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_hazard_during_play_media_stops_the_start(r):
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv

    async def play_then_smoke(call):
        r.world._rec(call)
        sp = r.world.by_entity[MASTER]
        sp.content, sp.state = call.data["media_content_id"], "playing"
        r.world.push(sp, call.context)
        r.mf._hazard_until = r.mf._monotonic() + 1000     # smoke while in flight
    r.hass.services.async_register(
        "media_player", "play_media", play_then_smoke,
        schema=vol.Schema({vol.Required("entity_id"): cv.entity_ids,
                           vol.Required("media_content_id"): str,
                           vol.Required("media_content_type"): str}))
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    rows = await _rows(r)
    assert ("skipped_hazard", "during_start") in rows and ("started", "") not in rows
    assert len(_calls(r, "media_stop")) == 1
    assert OJI_EID not in r.mf._arrival_stamps


@pytest.mark.asyncio
async def test_hazard_stop_in_verify_window_cancels_start(r):
    await _arrive_held(r, OJI_EID, T0 + 1000 + 4 * H)
    await r.mf.async_hazard_stop("smoke")
    await _release(r)
    rows = await _rows(r)
    assert ("skipped_hazard", "verify") in rows and ("started", "") not in rows
    assert r.world.state("master") == "idle"
    assert OJI_EID not in r.mf._arrival_stamps


# ============================================================ shared suite (D4)

@pytest.mark.asyncio
async def test_live_repro_ezinne_in_bath_oji_arrives_no_start(r):
    """Review D4 live repro: Ezinne in the Master Bath (BLE-placed), the
    bedroom vacant, Oji's GPS edge fires -> no music in the master."""
    r.layer.locations[EZ] = "Master Bath"
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("skipped_occupied", "tracked_person") in await _rows(r)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_suite_backstop_bath_occupied_long(r):
    t_a = T0 + 1000 + 4 * H
    r.rooms[r.bath].data["occupied"] = True
    r.rooms[r.bath].onset = datetime.fromtimestamp(t_a - 1800, tz=timezone.utc)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("skipped_occupied", "backstop") in await _rows(r)


@pytest.mark.asyncio
async def test_suite_window_end_ezinne_in_bath_keeps(r):
    await _started(r)
    r.layer.locations[EZ] = "Master Bath"
    await A.window_end(r)
    assert ("wait_kept_occupied", "tracked_person") in await _rows(r)
    assert not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_suite_window_end_bath_occupied_keeps(r):
    await _started(r)
    r.rooms[r.bath].data["occupied"] = True
    await A.window_end(r)
    assert ("wait_kept_occupied", "room_occupied") in await _rows(r)
    assert not _calls(r, "media_stop")


@pytest.mark.asyncio
async def test_suite_departure_ezinne_in_bath_kept_shared(r):
    await _handed_off(r)
    r.layer.locations[EZ] = "Master Bath"
    await A.depart(r, OJI_EID, r.wall.t + H)
    await A.window_end(r)                       # the departure wait's end
    assert ("departure_kept_shared", "") in await _rows(r)
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_suite_departure_bath_occupied_kept_occupied(r):
    await _handed_off(r)
    r.rooms[r.bath].data["occupied"] = True
    await A.depart(r, OJI_EID, r.wall.t + H)
    await A.window_end(r)
    assert ("departure_kept_occupied", "") in await _rows(r)
    assert not _calls(r, "media_pause")


@pytest.mark.asyncio
async def test_suite_is_owners_rooms_not_unrelated_rooms(r):
    """Jaya's room is no owner's master-suite room: Jaya placed there does
    not block Oji's master start."""
    r.layer.locations["Jaya"] = "Jaya Bedroom"
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("started", "") in await _rows(r)


# ================================================================== groups (D2/D3)

@pytest.mark.asyncio
async def test_start_skips_grouped_idle_player(r):
    sp = r.world.speakers["master"]
    sp.group = [MASTER, "media_player.kitchen_3"]
    r.world.push(sp)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("skipped_grouped", "") in await _rows(r)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_window_end_grouped_by_music_following_kept_group(r):
    """The master joined to the kitchen by music following's own call
    (ownership holds): the window-end stop would stop both rooms ->
    wait_kept_group, no stop."""
    await _started(r)
    await r.mf._call("media_player", "join",
                     {"entity_id": MASTER, "group_members": ["media_player.kitchen_3"]})
    await A.drain(r)
    await A.window_end(r)
    assert ("wait_kept_group", "") in await _rows(r)
    assert not _calls(r, "media_stop")


# ================================================================ in flight (B-M1/D7)

@pytest.mark.asyncio
async def test_joint_arrival_one_start_per_room(r):
    """Oji's start is in flight (verify wait held); Ezinne (co-owner) arrives
    -> skipped_playing subtype inflight; one play_media."""
    r.wall.t = T0 + 100
    A._feed(r, EZ_EID, "home", "not_home")
    await A.drain(r)
    await _arrive_held(r, OJI_EID, T0 + 1000 + 4 * H)
    r.wall.t = T0 + 1001 + 4 * H
    A._feed(r, EZ_EID, "not_home", "home")
    await until(lambda: r.mf._arrival_counts.get("skipped_playing:inflight"), n=2000)
    await _release(r)
    assert ("skipped_playing", "inflight") in await _rows(r, EZ_EID)
    assert len(A.ura_calls(r, "play_media")) == 1
    assert list(r.mf._arrival_stamps) == [OJI_EID]


@pytest.mark.asyncio
async def test_two_rooms_one_player_one_start(r):
    """Jaya's bedroom configured with the master's player (legal): while
    Oji's start holds the player, Jaya's start in another room is refused."""
    entry = r.hass.config_entries.async_get_entry(r.jaya_room)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_player": MASTER})
    r.wall.t = T0 + 100
    A._feed(r, JAYA_EID, "home", "not_home")
    await A.drain(r)
    await _arrive_held(r, OJI_EID, T0 + 1000 + 4 * H)
    r.wall.t = T0 + 1001 + 4 * H
    A._feed(r, JAYA_EID, "not_home", "home")
    await until(lambda: r.mf._arrival_counts.get("skipped_playing:inflight"), n=2000)
    await _release(r)
    assert ("skipped_playing", "inflight") in await _rows(r, JAYA_EID)
    assert len(A.ura_calls(r, "play_media")) == 1


@pytest.mark.asyncio
async def test_departure_during_verify_runs_after_the_start(r):
    """Review A-6: a departure record that lands in the verify wait is not
    dropped: once started, the wait ends departed_during_wait and the
    departure wait arms."""
    await _arrive_held(r, OJI_EID, T0 + 1000 + 4 * H)
    r.wall.t += 5
    A._feed(r, OJI_EID, "home", "not_home")
    await _spin()
    await _release(r)
    names = [o for o, _ in await _rows(r)]
    assert "started" in names and "departed_during_wait" in names
    assert "departure_paused" in names           # nobody in the suite: one pause
    assert len(_calls(r, "media_pause")) == 1


@pytest.mark.asyncio
async def test_window_timer_during_start_runs_after_start(r):
    """Review D8: the window timer fires while the start is in flight (a
    window shorter than the verify wait); the window end runs once the start
    resolves, so the started music still gets exactly one wait terminal."""
    await _arrive_held(r, OJI_EID, T0 + 1000 + 4 * H)
    r.timers.fire_all()                       # the window end, during verify
    await _spin()
    await _release(r)
    rows = await A.outcomes(r, "arrival_music")
    terms = [a["outcome"] for a in rows if a["person"] == OJI_EID
             and a["outcome"] not in ("intent_opened", "started")]
    assert terms == ["wait_expired_stopped"]
    assert OJI_EID not in r.mf._arrival_intents


@pytest.mark.asyncio
async def test_duplicate_arrival_while_opening_counted_once(r):
    """Review A-7: a second arrival record while the first intent is still
    being opened (its target-room read is in flight) is intent_duplicate."""
    real = r.mf._target_room
    gate = asyncio.Event()

    async def slow(prof):
        await gate.wait()
        return await real(prof)
    r.mf._target_room = slow
    r.wall.t = T0 + 100
    A._feed(r, OJI_EID, "home", "not_home")
    await A.drain(r)
    r.wall.t = T0 + 100 + 4 * H
    A._feed(r, OJI_EID, "not_home", "home")
    await _spin()
    rec = r.presence._residency.last_event[OJI_EID]
    r.mf._on_person_edge(rec)                 # the same record delivered twice
    await _spin()
    gate.set()
    await A.drain(r)
    assert (await A.names(r)).count("intent_opened") == 1
    assert r.mf._arrival_counts.get("intent_duplicate") == 1


# ============================================================= MA twin at start

@pytest.mark.asyncio
async def test_arrival_start_prefers_the_live_7_twin(r):
    """MF-MA-TWIN-WIIM-UUID-1: Jaya's bedroom player is a WiiM whose live
    registry shape (study_a) has a dead _5 and a live _7 twin: the start
    plays on the _7."""
    from test_music_following_repair import GP, _speaker_device
    from test_mf_ma_twin_wiim_uuid import STUDY_7, STUDY_W, _add_live_twin  # noqa: F401
    entry = r.hass.config_entries.async_get_entry(r.jaya_room)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_player": "media_player.study_a_3"})
    _add_live_twin(r, "study_a", "media_player.study_a_3", STUDY_W, "study_a_7", STUDY_7,
                   dead_eid="media_player.study_a_5")
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    plays = [e for c in A.ura_calls(r, "play_media") for e in _eids(c)]
    assert plays == ["media_player.study_a_7"]


# ==================================================================== D10 / D5 / D6

@pytest.mark.asyncio
async def test_unavailable_bedroom_player_falls_back_to_next_own_room(r):
    """Review D10: the master player reads unavailable; Oji's next own room
    with an available player is used (here a second bedroom with Study A's
    player)."""
    A.set_profile(r, OJI_EID, rooms_bedroom=[r.master, r.ids["Study A"]])
    sp = r.world.speakers["master"]
    sp.entities.remove(MASTER)
    r.hass.states.async_set(MASTER, "unavailable", {})
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    rows = [a for a in await A.outcomes(r) if a["outcome"] == "intent_opened"]
    assert rows[0]["target_room"] == r.ids["Study A"]
    assert [e for c in A.ura_calls(r, "play_media") for e in _eids(c)][0] in (
        "media_player.study_a_3", "media_player.study_a_5")


@pytest.mark.asyncio
async def test_zone_fallback_player_room_must_pass(r, mods):  # noqa: F811
    """Review D5: Jaya's bedroom has no own player; its zone player (the
    kitchen speaker, area kitchen) is used only when the Kitchen passes the
    same checks: Ezinne placed in the Kitchen blocks it."""
    MockConfigEntry = mods.MockConfigEntry
    entry = r.hass.config_entries.async_get_entry(r.jaya_room)
    data = dict(entry.data)
    data.pop("room_media_player", None)
    data["zone"] = "Upstairs"
    data["area_id"] = "no_speaker_area"
    r.hass.config_entries.async_update_entry(entry, data=data, options={})
    MockConfigEntry(domain=A.DOMAIN, data={
        "entry_type": "zone", "zone_name": "Upstairs",
        "zone_player_entity": "media_player.kitchen_3"}).add_to_hass(r.hass)
    r.layer.locations[EZ] = "Kitchen"
    r.layer.locations[OJI] = "Study A"
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert ("skipped_occupied", "tracked_person") in await _rows(r, JAYA_EID)
    assert not A.ura_calls(r, "play_media")
    # Nobody in the kitchen -> it starts on the zone player.
    r.layer.locations[EZ] = "Study A"
    r.mf._arrival_intents.clear()
    r.mf._arrival_last_music.clear()
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000 + 6 * H)
    assert ("started", "") in await _rows(r, JAYA_EID)


@pytest.mark.asyncio
async def test_restore_edge_no_departure_since_setup_fails_closed(r):
    """Review D6: Ziri-shaped repro. Departure row written, restart, the
    person reads home with no event; hours later a restore `unknown -> home`
    (counted=True: no real transition since setup) must not start music."""
    from test_arrival_music import _restart
    await A.depart(r, OJI_EID, T0 + 1000)
    await _restart(r)
    r.hass.states.async_set(OJI_EID, "home", {})        # flipped while URA was down
    r.wall.t += 3 * H
    A._feed(r, OJI_EID, "home", "unknown")
    r.wall.t += 60
    A._feed(r, OJI_EID, "unknown", "home")
    await A.drain(r)
    rec = r.presence._residency.last_event[OJI_EID]
    assert rec.counted is True and rec.old_state == "unknown"
    assert "intent_opened" not in await A.names(r)
    assert r.mf._arrival_counts.get("skipped_not_counted_return:departure_missing") == 1


# ======================================================= scene: bedroom first (A-5/D9)

@pytest.mark.asyncio
async def test_shared_bath_entry_consumes_no_scene_outcome(r):
    A.set_profile(r, OJI_EID, auto_scene=True, welcome_scene="scene.oji")
    A.set_profile(r, EZ_EID, auto_scene=True, welcome_scene="scene.ez")
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 1000)
    assert r.mf.arrival_scene_for(r.bath) is None
    await A.drain(r)
    scene_rows = await A.outcomes(r, "welcome_scene")
    assert scene_rows == []
    # The bedroom then still decides (both open -> ambiguous, as planned).
    assert r.mf.arrival_scene_for(r.master) is None
    await A.drain(r)
    assert [a["outcome"] for a in await A.outcomes(r, "welcome_scene")].count(
        "scene_skipped_ambiguous") == 2


# =========================================================== A-4 / B-L1 / B-L2 / B-L4

@pytest.mark.asyncio
async def test_room_sleep_clock_labelled_skipped_sleep_room(r):
    r.rooms[r.master].automation = types.SimpleNamespace(
        is_sleep_mode_active=lambda: True, is_dark=lambda _lux=None: False)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert ("skipped_sleep", "room") in await _rows(r)


@pytest.mark.asyncio
async def test_pc_listener_released_after_handoff_without_departure(r):
    await _handed_off(r)
    assert r.layer.listeners == []
    assert not r.mf._arrival_stamps[OJI_EID].done
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert len(r.layer.listeners) <= 1


@pytest.mark.asyncio
async def test_teardown_flag_blocks_spawns_timers_and_listener(r):
    await _started(r)
    await r.mf.async_teardown()
    r.mf._on_pc_update()
    r.mf._on_person_edge(types.SimpleNamespace(kind="arrival", person=OJI_EID))
    assert r.mf._arrival_tasks == set()
    assert r.layer.listeners == []
    n = len(r.timers.pending)
    r.mf._schedule_later(5, lambda _now: None)
    assert len(r.timers.pending) == n
    assert r.mf.async_start_arrival_actions() is True    # a restart clears it
    assert r.mf._arrival_torn_down is False


@pytest.mark.asyncio
async def test_teardown_cancels_timers_before_its_await_and_leaks_no_listener(r):
    """Review B-L2: with a window-end stop in flight, teardown cancels every
    intent timer BEFORE it awaits the arrival tasks, and the cancelled task's
    cleanup cannot re-register the person-coordinator listener."""
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv
    await _started(r)
    A.set_profile(r, OJI_EID, auto_scene=True, welcome_scene="scene.oji")
    gate = asyncio.Event()

    async def slow_stop(call):
        r.world._rec(call)
        await gate.wait()
    r.hass.services.async_register("media_player", "media_stop", slow_stop,
                                   schema=vol.Schema({vol.Required("entity_id"): cv.entity_ids}))
    # Ezinne has an open intent (a live window timer) while Oji's stop hangs.
    n0 = len(r.timers.pending)
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 2000)
    ez_timers = [p for p in r.timers.pending[n0:] if not p[2]]
    assert ez_timers and EZ_EID in r.mf._arrival_intents
    r.timers.pending[0][1](None)                 # Oji's window end -> the stop hangs
    await until(lambda: _calls(r, "media_stop"), n=2000)
    td = asyncio.ensure_future(r.mf.async_teardown())
    await _spin(5)
    assert all(p[2] for p in ez_timers)           # cancelled before the await returns
    gate.set()
    await td
    assert r.layer.listeners == []


@pytest.mark.asyncio
async def test_arrival_outcome_does_not_notify_transfer_listeners(r):
    seen = []
    r.mf.add_diagnostic_listener(lambda: seen.append(1))
    await _started(r)
    await A.window_end(r)
    assert seen == []


@pytest.mark.asyncio
async def test_arrival_rows_have_their_own_switch(r, monkeypatch, mods):  # noqa: F811
    monkeypatch.setattr(mods.const, "MF_EPISODE_LOG_PERSIST", False)
    await _started(r)
    assert "intent_opened" in await A.names(r)
    monkeypatch.setattr(mods.const, "ARRIVAL_EPISODE_LOG_PERSIST", False)
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 1000)
    assert await A.names(r, EZ_EID) == []


# ===================================================================== B-M2

@pytest.mark.asyncio
async def test_writer_health_checks_arrival_types_only_when_opted_in(r):
    r.db.hass.data = r.hass.data
    stats = await r.db.run_memory_writer_health_check(triggered_by="manual")
    assert "arrival_music" in stats["counts"] and "arrival_music" not in stats["switch_off_types"]
    for who in (OJI_EID, EZ_EID, JAYA_EID):
        A.set_profile(r, who, auto_music=False, auto_scene=False)
    stats = await r.db.run_memory_writer_health_check(triggered_by="manual")
    assert {"arrival_music", "welcome_scene"} <= set(stats["switch_off_types"])
    assert "arrival_music" not in stats["zero_row_types"]
    A.set_profile(r, OJI_EID, auto_music=True)
    A.set_cm(r, music_on_arrival_start=False)
    stats = await r.db.run_memory_writer_health_check(triggered_by="manual")
    assert "arrival_music" in stats["switch_off_types"]


@pytest.mark.asyncio
async def test_departure_twin_of_same_speaker_is_not_something_else(r):
    """Without ARRIVAL_OURS_ATTR, the played MA twin's native entity reading
    playing is the same physical speaker playing ours: the departure pause
    still acts (not departure_kept_other_playing)."""
    entry = r.hass.config_entries.async_get_entry(r.jaya_room)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_player": "media_player.study_a_3"})
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    stamp = r.mf._arrival_stamps[JAYA_EID]
    assert stamp.play_eid == "media_player.study_a_5" and stamp.native == "media_player.study_a_3"
    assert r.hass.states.get("media_player.study_a_3").state == "playing"
    r.layer.locations["Jaya"] = "Jaya Bedroom"
    r.layer.fire()
    await A.drain(r)
    await A.depart(r, JAYA_EID, r.wall.t + H)
    assert ("departure_paused", "") in await _rows(r, JAYA_EID)


@pytest.mark.asyncio
async def test_room_claim_holds_when_the_room_player_changes_mid_start(r):
    """The ROOM claim (made before the first await) is what stops a second
    start in the same room when the room's player resolves differently for
    the second start (the room's speaker re-configured while Oji's start is
    in flight): one play_media, Ezinne skipped inflight."""
    r.wall.t = T0 + 100
    A._feed(r, EZ_EID, "home", "not_home")
    await A.drain(r)
    await _arrive_held(r, OJI_EID, T0 + 1000 + 4 * H)
    entry = r.hass.config_entries.async_get_entry(r.master)
    r.hass.config_entries.async_update_entry(
        entry, options={"room_media_player": "media_player.kitchen_3"})
    r.wall.t = T0 + 1001 + 4 * H
    A._feed(r, EZ_EID, "not_home", "home")
    await until(lambda: r.mf._arrival_counts.get("skipped_playing:inflight"), n=2000)
    await _release(r)
    assert ("skipped_playing", "inflight") in await _rows(r, EZ_EID)
    assert len(A.ura_calls(r, "play_media")) == 1


@pytest.mark.asyncio
async def test_min_away_zero_also_turns_off_the_restore_rule(r, monkeypatch, mods):  # noqa: F811
    """Config extreme: ARRIVAL_MIN_AWAY_S 0 = flags only (the knob note):
    the D6 restore rule is part of gate 3b, so it is off too."""
    from test_arrival_music import _restart
    monkeypatch.setattr(mods.const, "ARRIVAL_MIN_AWAY_S", 0)
    await A.depart(r, OJI_EID, T0 + 1000)
    await _restart(r)
    r.hass.states.async_set(OJI_EID, "home", {})
    r.wall.t += 3 * H
    A._feed(r, OJI_EID, "home", "unknown")
    r.wall.t += 60
    A._feed(r, OJI_EID, "unknown", "home")
    await A.drain(r)
    assert "intent_opened" in await A.names(r)

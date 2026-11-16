"""Arc step 8 D2 arrival music + D4 departure pause (PLANNING_identity_actions_v6.md
rev 3.6.1 §5.4-§5.9, §6 INV-V6-*). Every arrival / flap / return drives the REAL
residency producer and tracker (``_arrival_rig``); oracles are hand-derived from
the plan, never recomputed by the engine.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from test_music_following_repair import hass, mods  # noqa: F401
import _arrival_rig as A
from _arrival_rig import EZ, EZ_EID, JAYA, JAYA_EID, OJI, OJI_EID, T0

H = 3600.0


@pytest_asyncio.fixture
async def r(hass, mods, tmp_path):  # noqa: F811
    rig = await A.make(hass, mods, tmp_path)
    try:
        yield rig
    finally:
        await rig.mf.async_teardown()
        await rig.db.stop_write_worker()


@pytest.fixture
def ours_t(monkeypatch, mods):  # noqa: F811
    """D2 B0 branch T fixture: the player keeps reporting the pick's id."""
    monkeypatch.setattr(mods.const, "ARRIVAL_OURS_ATTR", "media_content_id")


def _eids(c):
    v = c[2].get("entity_id")
    return [v] if isinstance(v, str) else list(v or [])


def started_on(r, eid):
    return [c for c in A.ura_calls(r, "play_media") if eid in _eids(c)]


# --------------------------------------------------------------------- start

@pytest.mark.asyncio
async def test_counted_edge_starts_in_own_room_before_entry(r):
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r)
    calls = started_on(r, "media_player.master_bedroom_sonos_2")
    assert len(calls) == 1 and calls[0][2]["media_content_id"] == "library://playlist/7"
    assert set(calls[0][2]) == {"entity_id", "media_content_id", "media_content_type"}
    assert r.world.state("master") == "playing"       # before he reaches the room


@pytest.mark.asyncio
async def test_ble_only_person_edge_starts(r):
    await A.trip(r, JAYA_EID, 2 * H, start=T0 + 1000)
    assert "started" in await A.names(r, JAYA_EID)
    assert started_on(r, "media_player.garage_b_3")


@pytest.mark.asyncio
async def test_no_f5_read_ble_f5_no_second_intent(r, mods):  # noqa: F811
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    sig = mods.pkg.domain_coordinators.signals if hasattr(mods.pkg, "domain_coordinators") else None
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    import importlib
    signals = sig or importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.signals")
    async_dispatcher_send(r.hass, signals.SIGNAL_PERSON_ARRIVING,
                          {"person_entity": OJI_EID, "source": "ble"})
    await A.drain(r)
    assert (await A.names(r)).count("intent_opened") == 1
    assert len(A.ura_calls(r, "play_media")) == 1


@pytest.mark.asyncio
async def test_face_alone_opens_no_intent(r):
    import importlib
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    signals = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.signals")
    r.hass.states.async_set(OJI_EID, "not_home", {})
    for src in ("camera_face", "camera_egress", "geofence"):
        async_dispatcher_send(r.hass, signals.SIGNAL_PERSON_ARRIVING,
                              {"person_entity": OJI_EID, "source": src})
    await A.drain(r)
    assert await A.names(r) == []
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_one_subscription_arrival_and_departure(r):
    # Exactly one residency subscriber from the engine; teardown removes it.
    assert r.mf._edge_unsub is not None
    assert r.mf.async_start_arrival_actions() is False       # idempotent
    await r.mf.async_teardown()
    assert r.mf._edge_unsub is None
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert await A.names(r) == []


@pytest.mark.asyncio
async def test_subscribe_person_edges_only_no_raw_connect(r, mods):  # noqa: F811
    """The Music Following coordinator's setup connects no F5 listener and
    (re)makes the engine's one residency subscription (CM reload path)."""
    import importlib
    signals = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.signals")
    disp = importlib.import_module("homeassistant.helpers.dispatcher")
    await r.mf.async_teardown()
    assert r.mf._edge_unsub is None

    def n_listeners(sig):
        data = r.hass.data.get(disp.DATA_DISPATCHER, {}) or {}
        return len(data.get(sig, {}) or {})
    f5_before = n_listeners(signals.SIGNAL_PERSON_ARRIVING)
    res_before = n_listeners(signals.SIGNAL_RESIDENCY_EVENT)
    coord = mods.dc.MusicFollowingCoordinator(r.hass)
    await coord.async_setup()
    assert n_listeners(signals.SIGNAL_PERSON_ARRIVING) == f5_before
    assert n_listeners(signals.SIGNAL_RESIDENCY_EVENT) == res_before + 1
    assert r.mf._edge_unsub is not None
    coord._cancel_listeners()
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r)


@pytest.mark.asyncio
async def test_gps_flap_counted_true_short_absence_opens_no_intent(r):
    await A.trip(r, OJI_EID, 40, start=T0 + 1000)
    rec = r.presence._residency.last_event[OJI_EID]
    assert rec.kind == "arrival" and rec.counted is True     # counted passes the flap
    assert await A.names(r) == []
    assert r.mf._arrival_counts.get("skipped_not_counted_return:short_absence") == 1
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_min_away_boundary_literals(r):
    await A.trip(r, OJI_EID, 899, start=T0 + 1000)
    assert await A.names(r) == []
    await A.trip(r, EZ_EID, 900, start=T0 + 1000)
    assert "started" in await A.names(r, EZ_EID)


@pytest.mark.asyncio
async def test_uncounted_return_no_departure_seen_opens_no_intent(r):
    # restore unknown -> home with the last real home 3 min before: not counted.
    await A.trip(r, OJI_EID, 300, start=T0 + 1000)    # a real home at T0+1300
    r.mf._arrival_intents.clear()
    r.wall.t = T0 + 2000
    A._feed(r, OJI_EID, "home", "unknown")
    r.wall.t = T0 + 2180
    A._feed(r, OJI_EID, "unknown", "home")
    await A.drain(r)
    assert r.presence._residency.last_event[OJI_EID].counted is False
    assert "intent_opened" not in await A.names(r)
    assert r.mf._arrival_counts.get("skipped_not_counted_return:not_counted") == 1


@pytest.mark.asyncio
async def test_stale_source_edge_opens_no_intent(r):
    await A.depart(r, OJI_EID, T0 + 1000)
    await A.come_home(r, OJI_EID, T0 + 1000 + 4 * H, stale=True)
    assert r.presence._residency.last_event[OJI_EID].source_stale is True
    assert await A.names(r) == []
    assert r.mf._arrival_counts.get("skipped_not_counted_return:stale_source") == 1


@pytest.mark.asyncio
async def test_boot_window_edge_fails_closed_counted_in_digest(r):
    await A.trip(r, OJI_EID, 950, start=T0 - 1000)   # returns 50 s after setup... inside 600 s
    await A.trip(r, EZ_EID, 300, start=T0 + 10)
    assert await A.names(r) == []
    assert r.mf._arrival_counts.get("skipped_not_counted_return:boot", 0) >= 1
    assert "skipped_not_counted_return:boot" in r.mf.digest_section()


@pytest.mark.asyncio
async def test_multi_day_return_past_ring_starts_via_left_at(r, monkeypatch, mods):  # noqa: F811
    # Persistence off: only the tracker's left_at can show the absence.
    monkeypatch.setattr(mods.const, "RESIDENCY_EVENT_LOG_PERSIST", False)
    await A.depart(r, OJI_EID, T0 + 1000)
    t = T0 + 1100
    for i in range(40):                               # push Oji out of the 32-ring
        await A.depart(r, EZ_EID, t)
        await A.come_home(r, EZ_EID, t + 30)
        t += 60
    assert all(e.person != OJI_EID for e in r.presence._residency.recent)
    await A.come_home(r, OJI_EID, T0 + 1000 + 48 * H)
    assert "started" in await A.names(r)


async def _restart(r):
    """RAM loss: a new tracker and a new engine on the same DB."""
    await r.mf.async_teardown()
    r.wall.t += 700
    r.presence = r.Presence(r.hass, r.wall)
    r.hass.data[A.DOMAIN]["coordinator_manager"].coordinators["presence"] = r.presence
    r.mf._arrival_init_state()
    r.mf._wall = r.wall
    r.mf._call_later = r.timers
    r.mf.async_start_arrival_actions()
    await A.drain(r)
    r.wall.t += 700                                  # out of the new boot window


@pytest.mark.asyncio
async def test_multi_day_return_after_restart_starts_via_persisted_row(r):
    await A.depart(r, OJI_EID, T0 + 1000)
    await _restart(r)
    await A.come_home(r, OJI_EID, r.wall.t + 4 * 24 * H)
    assert "started" in await A.names(r)


@pytest.mark.asyncio
async def test_arrival_row_after_departure_row_fails_closed(r):
    await A.depart(r, OJI_EID, T0 + 1000)
    await A.come_home(r, OJI_EID, T0 + 1000 + 40)     # short flap: an arrival row after D
    await _restart(r)
    await A.come_home(r, OJI_EID, r.wall.t + 2 * H, old="not_home")
    assert "intent_opened" not in await A.names(r)
    assert r.mf._arrival_counts.get("skipped_not_counted_return:departure_missing") == 1


@pytest.mark.asyncio
async def test_departure_missing_fails_closed(r):
    await _restart(r)
    await A.come_home(r, OJI_EID, r.wall.t + 10, old="not_home")
    assert r.mf._arrival_counts.get("skipped_not_counted_return:departure_missing") == 1


@pytest.mark.asyncio
async def test_departure_read_error_fails_closed(r):
    await A.depart(r, OJI_EID, T0 + 1000)
    await _restart(r)

    async def boom(*_a, **_k):
        raise RuntimeError("db down")
    r.db.read_memory_episodes_by_type = boom
    await A.come_home(r, OJI_EID, r.wall.t + 2 * H)
    assert r.mf._arrival_counts.get("skipped_not_counted_return:departure_read_failed") == 1


@pytest.mark.asyncio
async def test_min_away_zero_uses_flags_only(r, monkeypatch, mods):  # noqa: F811
    monkeypatch.setattr(mods.const, "ARRIVAL_MIN_AWAY_S", 0)
    await A.trip(r, OJI_EID, 40, start=T0 + 1000)
    assert "started" in await A.names(r)


@pytest.mark.asyncio
async def test_min_away_3600_blocks_two_hour_short(r, monkeypatch, mods):  # noqa: F811
    monkeypatch.setattr(mods.const, "ARRIVAL_MIN_AWAY_S", 3600)
    await A.trip(r, OJI_EID, 3599, start=T0 + 1000)
    assert await A.names(r) == []


@pytest.mark.asyncio
async def test_window_zero_opens_no_intent(r, monkeypatch, mods):  # noqa: F811
    monkeypatch.setattr(mods.const, "ARRIVAL_WINDOW_S", 0)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert await A.names(r) == []


@pytest.mark.asyncio
async def test_duplicate_intent_counted(r):
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    await A.trip(r, OJI_EID, 2 * H)
    assert (await A.names(r)).count("intent_opened") == 1
    assert r.mf._arrival_counts.get("intent_duplicate") == 1


@pytest.mark.asyncio
async def test_master_off_and_observation_skip(r):
    A.set_cm(r, music_on_arrival_start=False)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    A.set_cm(r, music_on_arrival_start=True)
    r.wrapper.observation_mode = True
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 1000)
    assert await A.names(r) == [] and await A.names(r, EZ_EID) == []
    assert r.mf._arrival_counts.get("skipped_master_off") == 2


@pytest.mark.asyncio
async def test_target_room_bedroom_first_then_bathroom(r):
    # Bedroom with no player -> bathroom has none either -> skipped_no_player.
    A.set_profile(r, OJI_EID, rooms_bedroom=[r.ids["Master Bath"]], rooms_bathroom=[r.master])
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert started_on(r, "media_player.master_bedroom_sonos_2")


@pytest.mark.asyncio
async def test_no_player_room_skips(r):
    A.set_profile(r, OJI_EID, rooms_bedroom=[r.bath], rooms_bathroom=[])
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "skipped_no_player" in await A.names(r)


@pytest.mark.asyncio
async def test_tracked_person_in_room_blocks(r):
    r.layer.locations[EZ] = "Master Bedroom"
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    names = await A.outcomes(r)
    assert [(a["outcome"], a["subtype"]) for a in names if a["outcome"] != "intent_opened"] == [
        ("skipped_occupied", "tracked_person")]


@pytest.mark.asyncio
async def test_guests_detected_blocks(r):
    r.presence.census = A.census(2)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "skipped_guests" in await A.names(r)
    assert r.presence.census_reads == ["comfort"]


@pytest.mark.asyncio
async def test_one_unidentified_is_the_arriver_starts(r):
    r.presence.census = A.census(1)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r)


@pytest.mark.asyncio
async def test_guest_house_state_blocks(r):
    r.mf.update_house_state("guest")
    r.presence.census = A.census(0)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "skipped_guests" in await A.names(r)


@pytest.mark.asyncio
async def test_census_none_fails_open_counted(r):
    r.presence.census = None
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    rows = [a for a in await A.outcomes(r) if a["outcome"] == "started"]
    assert rows and rows[0].get("census_unavailable") is True


def _occupy(r, room, onset_ts):
    from datetime import datetime, timezone
    r.rooms[room].data["occupied"] = True
    r.rooms[room].onset = datetime.fromtimestamp(onset_ts, tz=timezone.utc)


@pytest.mark.asyncio
async def test_backstop_blocks_long_occupant(r):
    t_a = T0 + 1000 + 4 * H
    _occupy(r, r.master, t_a - 1800)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("skipped_occupied", "backstop") in rows


@pytest.mark.asyncio
async def test_backstop_boundary_479_starts(r):
    _occupy(r, r.master, T0 + 1000 + 4 * H - 479)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r)


@pytest.mark.asyncio
async def test_backstop_boundary_480_blocks(r):
    _occupy(r, r.master, T0 + 1000 + 4 * H - 480)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("skipped_occupied", "backstop") in rows


@pytest.mark.asyncio
async def test_backstop_zero_starts(r, monkeypatch, mods):  # noqa: F811
    monkeypatch.setattr(mods.const, "ARRIVAL_OCCUPIED_BACKSTOP_S", 0)
    _occupy(r, r.master, T0)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r)


@pytest.mark.asyncio
async def test_short_occupancy_nobody_placed_starts(r):
    t_a = T0 + 1000 + 4 * H
    _occupy(r, r.master, t_a - 180)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r)


@pytest.mark.asyncio
async def test_own_placement_skips_backstop(r):
    t_a = T0 + 1000 + 4 * H
    _occupy(r, r.master, t_a - 1200)
    r.layer.locations[OJI] = "Master Bedroom"
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    n = await A.names(r)
    assert "started" in n and "arrived" in n


@pytest.mark.asyncio
async def test_never_interrupts_native_or_ma_playing(r):
    r.world.play("master")
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "skipped_playing" in await A.names(r)
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_playing_group_member_counts_as_playing(r):
    r.world.speakers["master"].group = ["media_player.master_bedroom_sonos_2", "media_player.kitchen_3"]
    r.world.push(r.world.speakers["master"])
    r.world.play("kitchen")
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "skipped_playing" in await A.names(r)


@pytest.mark.asyncio
async def test_quiet_and_sleep_skip(r):
    import types
    r.hass.data[A.DOMAIN]["notification_manager"] = types.SimpleNamespace(
        is_quiet_hours_active=lambda: True)
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    del r.hass.data[A.DOMAIN]["notification_manager"]
    r.mf.update_house_state("waking")
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 1000)
    assert "skipped_quiet" in await A.names(r)
    assert "skipped_sleep" in await A.names(r, EZ_EID)


@pytest.mark.asyncio
async def test_paused_room_skips(r):
    r.rooms[r.master].enabled = False
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "skipped_paused" in await A.names(r)


@pytest.mark.asyncio
async def test_gap_per_person(r):
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    await A.window_end(r)
    r.world.speakers["master"].state = "idle"
    r.world.push(r.world.speakers["master"])
    await A.trip(r, OJI_EID, 1000)                   # within ARRIVAL_MIN_GAP_S of the start
    assert "skipped_gap" in await A.names(r)


@pytest.mark.asyncio
async def test_toggle_off_before_start_skips(r):
    """auto_music turned off after the intent opened, before the start."""
    real = r.mf._target_room

    async def flip_then(prof):
        out = await real(prof)
        A.set_profile(r, OJI_EID, auto_music=False)
        return out
    r.mf._target_room = flip_then
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("skipped_toggled_off", "auto_music") in rows
    assert not A.ura_calls(r, "play_media")


@pytest.mark.asyncio
async def test_volume_scale_clamped(r):
    A.set_profile(r, OJI_EID, music_volume=1.0)
    entry = r.hass.config_entries.async_get_entry(r.master)
    r.hass.config_entries.async_update_entry(entry, options={"room_media_volume_scale": 1.5})
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    vols = [c[2]["volume_level"] for c in A.ura_calls(r, "volume_set")]
    assert vols and vols[-1] == 1.0


@pytest.mark.asyncio
async def test_verify_on_player_state(r):
    r.world.speakers["master"].never_plays = True
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert "start_failed" in await A.names(r)
    assert OJI_EID not in r.mf._arrival_stamps


@pytest.mark.asyncio
async def test_no_bonus_joins(r):
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    assert not A.ura_calls(r, "join")


@pytest.mark.asyncio
async def test_callback_sync_schedules_only(r):
    import inspect
    assert not inspect.iscoroutinefunction(r.mf._on_person_edge)
    before = len(r.mf._arrival_tasks)
    rec = type("R", (), {"kind": "arrival", "person": OJI_EID})()
    r.mf._on_person_edge(rec)
    assert len(r.mf._arrival_tasks) == before + 1
    await A.drain(r)


# ---------------------------------------------------------------------- wait

async def _started(r, who=OJI_EID):
    await A.trip(r, who, 4 * H, start=T0 + 1000)
    assert "started" in await A.names(r, who)


@pytest.mark.asyncio
async def test_arrived_within_window_keeps_playing(r, ours_t):
    await _started(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    await A.window_end(r)
    assert "arrived" in await A.names(r)
    assert not A.ura_calls(r, "media_stop") and r.world.state("master") == "playing"


@pytest.mark.asyncio
async def test_arrived_in_own_bathroom(r, ours_t):
    await _started(r)
    r.layer.locations[OJI] = "Master Bath"
    r.layer.fire()
    await A.drain(r)
    await A.window_end(r)
    assert "arrived" in await A.names(r)
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_window_end_stops_when_never_reached(r, ours_t):
    await _started(r)
    await A.window_end(r)
    assert "wait_expired_stopped" in await A.names(r)
    assert [e for c in A.ura_calls(r, "media_stop") for e in _eids(c)] == [
        "media_player.master_bedroom_sonos_2"]


@pytest.mark.asyncio
async def test_window_end_context_rule_stops_without_ours_attr(r):
    """Fix pass (G-1): ARRIVAL_OURS_ATTR None no longer withholds the stop;
    the context ownership rule decides (no foreign write -> stop)."""
    await _started(r)
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("wait_expired_stopped", "media_stop") in rows
    assert len(A.ura_calls(r, "media_stop")) == 1


@pytest.mark.asyncio
async def test_window_end_final_read_late_seen(r, ours_t):
    """In the own bathroom at window end with no listener pass since."""
    await _started(r)
    r.layer.locations[OJI] = "Master Bath"          # no fire(): no listener pass
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("arrived", "late_seen") in rows
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_window_end_move_log_late_seen_not_stopped(r, ours_t):
    import types
    from datetime import datetime, timezone
    await _started(r)
    r.layer.moves.append(types.SimpleNamespace(
        person_entity=OJI_EID, from_room="Kitchen", to_room="Master Bath",
        ts=datetime.fromtimestamp(T0 + 1000 + 4 * H + 300, tz=timezone.utc)))
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("arrived", "late_seen") in rows
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_window_end_truncated_location_decides(r, ours_t):
    import types
    from datetime import datetime, timezone
    await _started(r)
    r.layer.moves.append(types.SimpleNamespace(
        person_entity=OJI_EID, from_room="Kitchen", to_room="Master Bath",
        ts=datetime.fromtimestamp(T0 + 1000 + 4 * H + 300, tz=timezone.utc)))
    r.layer.moves_truncated = True
    await A.window_end(r)
    assert "wait_expired_stopped" in await A.names(r)


@pytest.mark.asyncio
async def test_window_end_kept_when_coowner_listening(r, ours_t):
    await _started(r)
    r.layer.locations[EZ] = "Master Bedroom"
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("wait_kept_occupied", "tracked_person") in rows
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_two_owner_intents_music_once_coowner_arrived(r, ours_t):
    await _started(r)
    await A.trip(r, EZ_EID, 4 * H, start=T0 + 1100)
    assert "skipped_playing" in await A.names(r, EZ_EID)
    # Ezinne's own intent has no stamp; a co-owner who reached R is a listener.
    r.mf._arrival_intents[EZ_EID].music = "arrived"
    r.mf._arrival_intents[EZ_EID].target_room = r.master
    r.timers.pending[0][1](None)                  # Oji's window end only
    await A.drain(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r) if a["person"] == OJI_EID]
    assert ("wait_kept_occupied", "co_owner") in rows
    assert len(A.ura_calls(r, "play_media")) == 1


@pytest.mark.asyncio
async def test_window_end_kept_when_room_occupied_any_onset(r, ours_t):
    await _started(r)
    _occupy(r, r.master, T0)                      # occupied since before t_a
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("wait_kept_occupied", "room_occupied") in rows
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_toggle_off_mid_window_skips(r, ours_t):
    await _started(r)
    A.set_profile(r, OJI_EID, auto_music=False)
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("wait_ended_toggled_off", "auto_music") in rows
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_room_paused_mid_window_skips_stop(r, ours_t):
    await _started(r)
    r.rooms[r.master].enabled = False
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("wait_ended_toggled_off", "paused") in rows
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_master_off_mid_window_skips_stop(r, ours_t):
    await _started(r)
    A.set_cm(r, music_on_arrival_start=False)
    await A.window_end(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("wait_ended_toggled_off", "master") in rows


@pytest.mark.asyncio
async def test_reversed_between_updates_seen_by_state_listener(r, ours_t):
    await _started(r)
    sp = r.world.speakers["master"]
    sp.state = "paused"
    r.world.push(sp)                              # by hand (no URA context)
    sp.state = "playing"
    r.world.push(sp)
    await A.drain(r)
    await A.window_end(r)
    assert "reversed" in await A.names(r)
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_not_ours_ends_wait_no_stop(r, ours_t):
    await _started(r)
    r.world.play("master", content="podcast://episode/1")
    await A.drain(r)
    await A.window_end(r)
    assert "wait_ended_not_ours" in await A.names(r)
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_stopped_then_arrived_counted(r, ours_t):
    await _started(r)
    await A.window_end(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    assert "stopped_then_arrived" in await A.names(r)


@pytest.mark.asyncio
async def test_departure_during_wait_one_outcome_one_pause(r, ours_t):
    await _started(r)
    await A.depart(r, OJI_EID, r.wall.t + 420)
    await A.window_end(r)
    n = await A.names(r)
    assert "departed_during_wait" in n and "wait_expired_stopped" not in n
    assert len(A.ura_calls(r, "media_pause")) <= 1
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_listener_removed_when_no_waits_and_at_teardown(r, ours_t):
    await _started(r)
    assert len(r.layer.listeners) == 1
    await r.mf.async_teardown()
    assert r.layer.listeners == []


@pytest.mark.asyncio
async def test_player_listener_removed_at_terminal_and_teardown(r, ours_t):
    await _started(r)
    stamp = r.mf._arrival_stamps[OJI_EID]
    assert stamp.player_unsub is not None
    r.world.play("master", content="podcast://x")
    await A.drain(r)
    assert stamp.done and stamp.player_unsub is None
    # Teardown (review C #389: this test used to stop at the terminal case).
    await _started(r, JAYA_EID)
    live = r.mf._arrival_stamps[JAYA_EID]
    assert live.player_unsub is not None
    await r.mf.async_teardown()
    assert live.player_unsub is None
    r.world.play("garage_b", content="podcast://y")     # a foreign write
    await A.drain(r)
    assert not live.not_ours_seen and not live.reversed_seen


@pytest.mark.asyncio
async def test_window_end_move_read_uses_aware_datetime(r, ours_t):
    await _started(r)
    await A.window_end(r)      # Layer asserts an aware datetime on both reads
    assert "wait_expired_stopped" in await A.names(r)


# ------------------------------------------------------------------ hand-off

@pytest.mark.asyncio
async def test_no_step8_call_after_arrived(r, ours_t):
    await _started(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    before = list(r.world.calls)
    r.layer.locations[OJI] = "Kitchen"
    r.layer.fire()
    await A.window_end(r)
    assert r.world.calls == before


@pytest.mark.asyncio
async def test_handoff_music_following_transfers_when_enabled(r, ours_t):
    from test_music_following_repair import move, set_area
    await _started(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    set_area(r, "Study A")
    r.layer.locations[OJI] = "Study A"
    out = await move(r, "Master Bedroom", "Study A")
    assert out in ("success", "success_nudged")
    assert r.world.state("study_a") == "playing"


@pytest.mark.asyncio
async def test_handoff_stays_when_music_following_off(r, ours_t):
    from test_music_following_repair import move
    await _started(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    r.mf.disable_for_person(OJI)
    r.mf.disable_for_person(OJI_EID)
    r.layer.locations[OJI] = "Study A"
    out = await move(r, "Master Bedroom", "Study A")
    assert out == "person_not_enabled" and r.world.state("master") == "playing"


# ------------------------------------------------------------- D4 departure

async def _handed_off(r):
    await _started(r)
    r.layer.locations[OJI] = "Master Bedroom"
    r.layer.fire()
    await A.drain(r)
    await A.window_end(r)


@pytest.mark.asyncio
async def test_departure_pauses_when_room_empties_after_exit(r, ours_t):
    await _handed_off(r)
    _occupy(r, r.master, T0)
    await A.depart(r, OJI_EID, r.wall.t + H)      # Oji STALE in the master
    assert not A.ura_calls(r, "media_pause")
    r.rooms[r.master].data["occupied"] = False
    r.layer.fire()
    await A.drain(r)
    assert "departure_paused" in await A.names(r)
    assert [e for c in A.ura_calls(r, "media_pause") for e in _eids(c)] == [
        "media_player.master_bedroom_sonos_2"]


@pytest.mark.asyncio
async def test_departing_person_stale_ble_excluded(r, ours_t):
    await _handed_off(r)
    r.layer.locations[OJI] = "Master Bedroom"      # his own stale location
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert "departure_paused" in await A.names(r)


@pytest.mark.asyncio
async def test_departure_wait_ends_kept_occupied(r, ours_t):
    await _handed_off(r)
    _occupy(r, r.master, T0)
    await A.depart(r, OJI_EID, r.wall.t + H)
    await A.window_end(r)                          # the departure wait's end
    assert "departure_kept_occupied" in await A.names(r)
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_never_pauses_others(r, ours_t):
    await _handed_off(r)
    r.layer.locations[EZ] = "Master Bedroom"
    await A.depart(r, OJI_EID, r.wall.t + H)
    await A.window_end(r)
    assert "departure_kept_shared" in await A.names(r)
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_flap_departure_then_return_does_not_pause(r, ours_t):
    await _handed_off(r)
    _occupy(r, r.master, T0)
    t = r.wall.t + H
    await A.depart(r, OJI_EID, t)
    await A.come_home(r, OJI_EID, t + 40)
    r.rooms[r.master].data["occupied"] = False
    r.layer.fire()
    await A.drain(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("departure_kept_returned", "edge") in rows
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_return_check_truncated_fails_closed(r, ours_t):
    await _handed_off(r)
    r.presence.person_edges_truncated_since = lambda t: True
    await A.depart(r, OJI_EID, r.wall.t + H)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("departure_kept_returned", "truncated") in rows


@pytest.mark.asyncio
async def test_departure_grouped_player_kept_group(r, ours_t):
    await _handed_off(r)
    # The group is formed by music following's own call (its context is
    # recorded), so ownership holds and the group check decides.
    await r.mf._call("media_player", "join", {
        "entity_id": "media_player.master_bedroom_sonos_2",
        "group_members": ["media_player.kitchen_3"]})
    await A.drain(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert "departure_kept_group" in await A.names(r)
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_toggle_off_during_wait(r, ours_t):
    await _handed_off(r)
    _occupy(r, r.master, T0)
    await A.depart(r, OJI_EID, r.wall.t + H)
    A.set_profile(r, OJI_EID, auto_music=False)
    r.rooms[r.master].data["occupied"] = False
    r.layer.fire()
    await A.drain(r)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("departure_kept_toggled_off", "auto_music") in rows
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_room_paused_kept(r, ours_t):
    await _handed_off(r)
    r.rooms[r.master].enabled = False
    await A.depart(r, OJI_EID, r.wall.t + H)
    rows = [(a["outcome"], a["subtype"]) for a in await A.outcomes(r)]
    assert ("departure_kept_toggled_off", "paused") in rows


@pytest.mark.asyncio
async def test_departure_pause_knob_false(r, ours_t, monkeypatch, mods):  # noqa: F811
    monkeypatch.setattr(mods.const, "ARRIVAL_MUSIC_DEPARTURE_PAUSE", False)
    await _handed_off(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert "departure_kept_toggled_off" in await A.names(r)
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_context_rule_pauses_without_ours_attr(r):
    """Fix pass (G-1): the departure pause is active under the context rule."""
    await _handed_off(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert "departure_paused" in await A.names(r)
    assert len(A.ura_calls(r, "media_pause")) == 1


@pytest.mark.asyncio
async def test_stamp_cleared_on_user_pause(r, ours_t):
    await _handed_off(r)
    sp = r.world.speakers["master"]
    sp.state = "paused"
    r.world.push(sp)
    await A.drain(r)
    assert "stamp_cleared_reversed" in await A.names(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_after_handoff_transfer_not_ours(r, ours_t):
    from test_music_following_repair import move, set_area
    await _handed_off(r)
    set_area(r, "Study A")
    r.layer.locations[OJI] = "Study A"
    await move(r, "Master Bedroom", "Study A")
    await A.drain(r)
    await A.depart(r, OJI_EID, r.wall.t + H)
    n = await A.names(r)
    assert "stamp_cleared_not_ours" in n or "departure_kept_not_ours" in n
    assert not A.ura_calls(r, "media_pause")


@pytest.mark.asyncio
async def test_departure_wait_is_room_timeout_plus_margin(r, ours_t):
    await _handed_off(r)
    entry = r.hass.config_entries.async_get_entry(r.master)
    r.hass.config_entries.async_update_entry(entry, options={"occupancy_timeout": 500})
    _occupy(r, r.master, T0)
    n_before = len(r.timers.pending)
    await A.depart(r, OJI_EID, r.wall.t + H)
    delays = [p[0] for p in r.timers.pending[n_before:]]
    assert 800.0 in delays


@pytest.mark.asyncio
async def test_no_named_exit_arm(r, ours_t):
    import importlib
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    signals = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.signals")
    await _handed_off(r)
    async_dispatcher_send(r.hass, signals.SIGNAL_EGRESS_RECORD_AMENDED,
                          {"role": "exit_backfilled", "person_id": "oji_udezue"})
    await A.drain(r)
    assert r.mf._arrival_stamps[OJI_EID].departure is None


# ------------------------------------------------------------------ restart

@pytest.mark.asyncio
async def test_wait_lost_restart_leaves_music(r, ours_t):
    await _started(r)
    await _restart(r)
    n = await A.names(r)
    assert "wait_lost_restart" in n and "departure_stamp_lost_restart" in n
    assert not A.ura_calls(r, "media_stop")


@pytest.mark.asyncio
async def test_intent_lost_restart_counted(r):
    r.world.speakers["master"].never_plays = False
    await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000)
    # forge a crash before the start decision: drop the start outcome rows
    rows = [a for a in await A.outcomes(r) if a["outcome"] == "intent_opened"]
    assert rows
    ref = rows[0]["intent_ref"]
    await r.mf.async_teardown()
    # a fresh DB copy of only the opened row
    r.mf._arrival_init_state()
    r.mf._wall = r.wall
    r.mf._call_later = r.timers
    real = r.db.read_memory_episodes_by_type

    async def only_opened(t, since=None):
        out = await real(t, since)
        return [x for x in out if (x["attrs"] or {}).get("outcome") == "intent_opened"]
    r.db.read_memory_episodes_by_type = only_opened
    r.mf.async_start_arrival_actions()
    await A.drain(r)
    r.db.read_memory_episodes_by_type = real
    out = [a for a in await A.outcomes(r) if a.get("intent_ref") == ref]
    assert "intent_lost_restart" in [a["outcome"] for a in out]


@pytest.mark.asyncio
async def test_every_intent_ends_counted(r, ours_t):
    await _started(r)
    await A.window_end(r)
    rows = await A.outcomes(r, "arrival_music")
    terminals = [a for a in rows if a["outcome"] not in ("intent_opened", "started")]
    assert len(terminals) == 1


# --------------------------------------------------------------- trip-wires

@pytest.mark.asyncio
async def test_zero_fire_tripwire(r, monkeypatch):
    fired = []

    async def fake(hass, kind, key, diagnosis="", remedy="", severity=None, **_k):
        fired.append((kind, severity))
        return True
    import importlib
    nm = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm")
    monkeypatch.setattr(nm, "fire_stuck_signal", fake)
    r.world.speakers["master"].never_plays = True
    for i in range(10):
        A.set_profile(r, OJI_EID)
        r.mf._arrival_last_music.clear()
        r.mf._arrival_intents.clear()
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
    out = await r.mf.async_arrival_tripwires(r.db)
    assert "arrival_action_zero" in out
    assert ("arrival_action_zero", "HIGH") in fired


@pytest.mark.asyncio
async def test_stop_premature_tripwire(r, monkeypatch, ours_t):
    fired = []

    async def fake(hass, kind, key, diagnosis="", remedy="", severity=None, **_k):
        fired.append(kind)
        return True
    import importlib
    nm = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm")
    monkeypatch.setattr(nm, "fire_stuck_signal", fake)
    for i in range(3):
        r.mf._arrival_last_music.clear()
        r.mf._arrival_intents.clear()
        r.world.speakers["master"].state = "idle"
        r.world.push(r.world.speakers["master"])
        r.layer.locations[OJI] = "Kitchen"
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
        await A.window_end(r)
        r.layer.locations[OJI] = "Master Bedroom"
        r.layer.fire()
        await A.drain(r)
    await r.mf.async_arrival_tripwires(r.db)
    assert "arrival_stop_premature" in fired


@pytest.mark.asyncio
async def test_guest_block_tripwire(r, monkeypatch):
    fired = []

    async def fake(hass, kind, key, diagnosis="", remedy="", severity=None, **_k):
        fired.append((kind, severity))
        return True
    import importlib
    nm = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm")
    monkeypatch.setattr(nm, "fire_stuck_signal", fake)
    r.presence.census = A.census(3)
    for i in range(10):
        r.mf._arrival_intents.clear()
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
    await r.mf.async_arrival_tripwires(r.db)
    assert ("arrival_guest_block_high", "MEDIUM") in fired


@pytest.mark.asyncio
async def test_census_unavailable_tripwire(r, monkeypatch, ours_t):
    fired = []

    async def fake(hass, kind, key, diagnosis="", remedy="", severity=None, **_k):
        fired.append(kind)
        return True
    import importlib
    nm = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm")
    monkeypatch.setattr(nm, "fire_stuck_signal", fake)
    r.presence.census = A.census(0)
    r.mf._guests()                                   # the census has produced a result
    r.presence.census = None
    for i in range(3):
        r.mf._arrival_last_music.clear()
        r.mf._arrival_intents.clear()
        r.world.speakers["master"].state = "idle"
        r.world.push(r.world.speakers["master"])
        await A.trip(r, OJI_EID, 4 * H, start=T0 + 1000 + i * 6 * H)
    await r.mf.async_arrival_tripwires(r.db)
    assert "arrival_census_unavailable" in fired


@pytest.mark.asyncio
async def test_nightly_health_check_runs_tripwires(r, monkeypatch):
    seen = []

    async def spy(db=None):
        seen.append(db)
        return {}
    monkeypatch.setattr(r.mf, "async_arrival_tripwires", spy)
    await r.mf.async_nightly_health_check(r.db)
    assert seen == [r.db]

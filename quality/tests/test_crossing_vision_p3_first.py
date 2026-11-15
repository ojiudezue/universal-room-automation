"""Crossing vision Phase 3, first set: P3-D1, P3-D5, P3-D8
(docs/planning/PLANNING_crossing_vision.md @ 50bffd62, Phase 3).

Same REAL rig as test_crossing_vision_shadow (real HA core, bus, timers,
service registry, a real UniversalRoomDatabase with its own DDL; llmvision
stubbed at the service boundary). P3-D8 drives the REAL eval tick
(``_on_ledger_eval`` -> ``_held_inputs`` -> the REAL
``camera_stream_health.input_room_stuck_excluded`` -> the REAL room getter
``UniversalRoomCoordinator.camera_input_room_stuck_excluded`` over a REAL
``SensorExclusionSet``). Oracles are literal values from the plan.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
from datetime import timedelta

import pytest

from test_crossing_vision_shadow import (  # noqa: F401 - fixture + helper reuse
    FRONT_EGRESS,
    GARAGE_EGRESS,
    _ok_reply,
    _now,
    cross,
    ended_crossing,
    frigate,
    hass,
    mods,
    rig,
    fire_cross_nowait,
    rows,
    settle,
)
from test_crossing_ledger_wiring import _Room, _Substrate  # noqa: E402

_PKG = "custom_components.universal_room_automation"


# =================================================================== P3-D1
@pytest.mark.asyncio
async def test_error_row_carries_error_text(rig):
    rig.llm.reply = RuntimeError("provider down: 502 bad gateway")
    await ended_crossing(rig, "ev-err")
    [row] = rows(rig)
    assert row["outcome"] == "error"
    assert row["error"] == "provider down: 502 bad gateway"


@pytest.mark.asyncio
async def test_error_text_truncated(rig):
    """Row bound = CROSSING_VISION_ERROR_TEXT_MAX_CHARS (the adapter's own
    200 cut sits upstream, so the row bound is shown at 10)."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_ERROR_TEXT_MAX_CHARS", 10)
    rig.llm.reply = RuntimeError("abcdefghijKLMNOPQRST")
    await ended_crossing(rig, "ev-trunc")
    [row] = rows(rig)
    assert row["error"] == "abcdefghij"


@pytest.mark.asyncio
async def test_error_text_default_bound_200(rig):
    rig.llm.reply = RuntimeError("x" * 250)
    await ended_crossing(rig, "ev-200")
    [row] = rows(rig)
    assert row["error"] == "x" * 200


@pytest.mark.asyncio
async def test_ok_row_has_no_error_key(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 0.05)
    await ended_crossing(rig, "ev-ok")
    rig.llm.reply = ("sleep", 1.0)
    await ended_crossing(rig, "ev-to", camera="front_door_aerial",
                         egress=FRONT_EGRESS)
    await asyncio.sleep(0.1)
    await settle(rig)
    got = {r["outcome"]: r for r in rows(rig)}
    assert set(got) == {"ok", "timeout"}
    assert "error" not in got["ok"]
    assert "error" not in got["timeout"]


# =================================================================== P3-D5
def _db_rows_iso(day_offset_s):
    """UTC isoformat strings around today's LOCAL midnight (writer shape)."""
    from homeassistant.util import dt as dt_util

    mid = dt_util.as_utc(dt_util.start_of_local_day())
    return [(mid + timedelta(seconds=s)).isoformat() for s in day_offset_s]


async def _seed(rig, node, *, ended_at, outcome="ok", started_at=None,
                episode_type="crossing_vision_shadow"):
    rid = await rig.db.log_memory_episode(
        node_id=node, episode_type=episode_type,
        attrs={"outcome": outcome}, source_ref=node,
        started_at=started_at or ended_at, ended_at=ended_at,
        dedup_source_ref=False, window_dedup=False,
    )
    assert rid is not None


async def _restart(rig, *, await_rehydrate=True):
    """Simulated HA restart: the producer is torn down and a NEW one set up
    on the same hass + DB (RAM counter starts at 0)."""
    await rig.cv.async_teardown()
    cv2 = rig.mods.cv.CrossingVisionShadow(rig.hass)
    rig.cv = cv2  # the rig fixture tears down whatever rig.cv is
    await cv2.async_setup()
    if await_rehydrate and cv2._cap_rehydrate_task is not None:
        await cv2._cap_rehydrate_task
    return cv2


@pytest.mark.asyncio
async def test_dao_reports_error_distinct_from_empty(rig, tmp_path):
    db = rig.db
    assert await db.count_memory_episodes_by_type_ended_between(
        "crossing_vision_shadow", "2000-01-01T00:00:00+00:00",
        "2100-01-01T00:00:00+00:00", ("ok",)) == (0, True)
    rig.monkeypatch.setattr(db, "db_file", str(tmp_path / "no_dir" / "x.db"))
    assert await db.count_memory_episodes_by_type_ended_between(
        "crossing_vision_shadow", "2000-01-01T00:00:00+00:00",
        "2100-01-01T00:00:00+00:00", ("ok",)) == (0, False)


@pytest.mark.asyncio
async def test_rehydrate_ignores_yesterday_and_non_call_rows(rig):
    before, at, after, late = _db_rows_iso((-1, 0, 1, 3600))
    await _seed(rig, "y", ended_at=before)                    # yesterday
    await _seed(rig, "t0", ended_at=at)                       # 00:00:00 local
    await _seed(rig, "t1", ended_at=after, outcome="blank")
    await _seed(rig, "t2", ended_at=late, outcome="error")
    await _seed(rig, "t3", ended_at=late, outcome="timeout")
    await _seed(rig, "t4", ended_at=late, outcome="unparseable")
    await _seed(rig, "t5", ended_at=late, outcome="refused")
    for i, o in enumerate(("no_frigate_event", "skipped_cap", "skipped_busy",
                           "clustered", "no_clip_url")):
        await _seed(rig, f"n{i}", ended_at=late, outcome=o)
    await _seed(rig, "led", ended_at=late,
                episode_type="crossing_vision_ledger")
    from homeassistant.util import dt as dt_util

    tomorrow = dt_util.as_utc(dt_util.start_of_local_day(
        dt_util.now().date() + timedelta(days=1))).isoformat()
    await _seed(rig, "tmr", ended_at=tomorrow)               # next local day
    cv = await _restart(rig)
    assert cv._calls_today == 6
    assert cv.diag_status()["crossing_vision_today"]["calls"] == 6


@pytest.mark.asyncio
async def test_rehydrate_counts_by_ended_at_not_started_at(rig):
    yesterday, today = _db_rows_iso((-30, 30))
    # Crossing yesterday, call (row end) today -> counted.
    await _seed(rig, "a1", started_at=yesterday, ended_at=today)
    await _seed(rig, "a2", started_at=yesterday, ended_at=today)
    # Started today, ended "yesterday" (synthetic) -> not counted. Counts
    # differ by key (by ended_at 2, by started_at 1), so neither equals the
    # other by coincidence.
    await _seed(rig, "b", started_at=today, ended_at=yesterday)
    cv = await _restart(rig)
    assert cv._calls_today == 2


@pytest.mark.asyncio
async def test_cap_counter_rehydrated_from_today_rows(rig):
    [today] = _db_rows_iso((60,))
    for i in range(3):
        await _seed(rig, f"c{i}", ended_at=today)
    cv = await _restart(rig)
    assert (cv._calls_today, cv._cap_hold) == (3, False)
    assert cv.diag_status()["crossing_vision_cap_rehydrate"] == {
        "state": "ok", "cap_hold": False, "cap_rehydrate_failed": 0}


@pytest.mark.asyncio
async def test_cap_holds_across_simulated_restart(rig):
    """Cap 2: two calls, restart, the next crossing is skipped_cap with no
    call (a RAM-only counter would allow it)."""
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 2
    await ended_crossing(rig, "ev-r1", offset_s=-300)
    await ended_crossing(rig, "ev-r2", camera="front_door_aerial",
                         egress=FRONT_EGRESS, offset_s=-200)
    assert len(rig.llm.calls) == 2
    await settle(rig)
    await _restart(rig)
    await ended_crossing(rig, "ev-r3", offset_s=0)
    assert len(rig.llm.calls) == 2
    assert [r["outcome"] for r in rows(rig)] == ["ok", "ok", "skipped_cap"]


@pytest.mark.asyncio
async def test_rehydrate_slow_db_no_calls_until_done(rig):
    """The listener is live at once with the counter AT the cap: a crossing
    during the read is skipped_cap (no call); once the read returns 0 the
    next crossing calls."""
    gate = asyncio.Event()
    real = rig.db.count_memory_episodes_by_type_ended_between

    async def _slow(*a, **k):
        await gate.wait()
        return await real(*a, **k)

    rig.monkeypatch.setattr(rig.db, "count_memory_episodes_by_type_ended_between",
                            _slow)
    cv = await _restart(rig, await_rehydrate=False)
    assert cv._cap_hold is True
    # No wait on background tasks here: the rehydrate task IS one.
    e = _now(rig) - timedelta(seconds=300)
    s = e.timestamp() + 2
    frigate(rig, "ev-s1", "garage_a", s)
    frigate(rig, "ev-s1", "garage_a", s, typ="end", end=s + 8)
    fire_cross_nowait(rig, GARAGE_EGRESS, e)
    for _ in range(3):
        await rig.hass.async_block_till_done()
        await asyncio.sleep(0.01)
    assert rig.llm.calls == []
    assert [r["outcome"] for r in rows(rig)] == ["skipped_cap"]
    assert cv._cap_rehydrate_state == "pending"
    gate.set()
    await cv._cap_rehydrate_task
    assert cv._cap_hold is False
    await ended_crossing(rig, "ev-s2", camera="front_door_aerial",
                         egress=FRONT_EGRESS)
    assert len(rig.llm.calls) == 1


@pytest.mark.asyncio
async def test_rehydrate_error_retries_once_then_cap(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_CAP_REHYDRATE_RETRY_S", 0.01)
    attempts = []

    async def _fail(*a, **k):
        attempts.append(1)
        return 0, False

    rig.monkeypatch.setattr(rig.db, "count_memory_episodes_by_type_ended_between",
                            _fail)
    cv = await _restart(rig)
    assert len(attempts) == 2
    assert cv._cap_hold is True
    assert cv.diag_status()["crossing_vision_cap_rehydrate"] == {
        "state": "failed", "cap_hold": True, "cap_rehydrate_failed": 1}
    [page] = [p for p in rig.pages
              if p["kind"] == "crossing_vision_cap_rehydrate_failed"]
    assert page["severity"] == "LOW"
    await ended_crossing(rig, "ev-f1")
    assert rig.llm.calls == []
    assert [r["outcome"] for r in rows(rig)] == ["skipped_cap"]


@pytest.mark.asyncio
async def test_rehydrate_second_try_success_releases(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_CAP_REHYDRATE_RETRY_S", 0.01)
    answers = [(0, False), (4, True)]

    async def _flaky(*a, **k):
        return answers.pop(0)

    rig.monkeypatch.setattr(rig.db, "count_memory_episodes_by_type_ended_between",
                            _flaky)
    cv = await _restart(rig)
    assert (cv._calls_today, cv._cap_hold) == (4, False)
    assert not [p for p in rig.pages
                if p["kind"] == "crossing_vision_cap_rehydrate_failed"]


@pytest.mark.asyncio
async def test_rehydrate_timeout_counts_as_failure(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_CAP_REHYDRATE_TIMEOUT_S", 0.01)
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_CAP_REHYDRATE_RETRY_S", 0.01)

    async def _hang(*a, **k):
        await asyncio.sleep(5)
        return 0, True

    rig.monkeypatch.setattr(rig.db, "count_memory_episodes_by_type_ended_between",
                            _hang)
    cv = await _restart(rig)
    assert cv._cap_hold is True and cv._cap_rehydrate_state == "failed"


@pytest.mark.asyncio
async def test_failed_hold_ends_at_local_midnight(rig):
    """A failed rehydration holds the counter at the cap only until the next
    local day (the day roll clears the hold)."""
    from types import SimpleNamespace

    from homeassistant.util import dt as real_dt

    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_CAP_REHYDRATE_RETRY_S", 0.01)

    async def _fail(*a, **k):
        return 0, False

    rig.monkeypatch.setattr(rig.db, "count_memory_episodes_by_type_ended_between",
                            _fail)
    cv = await _restart(rig)
    assert cv._cap_hold is True
    shim = SimpleNamespace(
        now=lambda *a, **k: real_dt.now(*a, **k) + timedelta(days=1),
        utcnow=real_dt.utcnow, parse_datetime=real_dt.parse_datetime,
    )
    rig.monkeypatch.setattr(rig.mods.cv, "dt_util", shim)
    await ended_crossing(rig, "ev-mid")
    assert len(rig.llm.calls) == 1


@pytest.mark.asyncio
async def test_rehydrate_cap_zero_extreme(rig):
    """Config extreme: cap 0 -> INV-OFF (no call, no row) whatever the
    rehydration state; cap 200 (max) with 199 rows today allows ONE call."""
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 0
    await ended_crossing(rig, "ev-z")
    assert rig.llm.calls == [] and rows(rig) == []
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 200
    [today] = _db_rows_iso((60,))
    for i in range(199):
        await _seed(rig, f"m{i}", ended_at=today)
    cv = await _restart(rig)
    assert cv._calls_today == 199
    await ended_crossing(rig, "ev-m1", offset_s=-300)
    await ended_crossing(rig, "ev-m2", camera="front_door_aerial",
                         egress=FRONT_EGRESS)
    assert len(rig.llm.calls) == 1
    assert [r["outcome"] for r in rows(rig)][-2:] == ["ok", "skipped_cap"]


@pytest.mark.asyncio
async def test_rehydrate_for_old_day_discarded_after_midnight(rig):
    """A read that started before local midnight and returns after it is
    for the OLD day: discarded (new day = counter 0, no hold)."""
    from types import SimpleNamespace

    from homeassistant.util import dt as real_dt

    gate = asyncio.Event()

    async def _slow(*a, **k):
        await gate.wait()
        return 7, True

    rig.monkeypatch.setattr(rig.db, "count_memory_episodes_by_type_ended_between",
                            _slow)
    cv = await _restart(rig, await_rehydrate=False)
    for _ in range(5):
        await asyncio.sleep(0)
    shim = SimpleNamespace(
        now=lambda *a, **k: real_dt.now(*a, **k) + timedelta(days=1),
        utcnow=real_dt.utcnow, parse_datetime=real_dt.parse_datetime,
    )
    rig.monkeypatch.setattr(rig.mods.cv, "dt_util", shim)
    gate.set()
    await cv._cap_rehydrate_task
    assert (cv._calls_today, cv._cap_hold) == (0, False)


@pytest.mark.asyncio
async def test_teardown_cancels_pending_rehydrate(rig):
    gate = asyncio.Event()

    async def _block(*a, **k):
        await gate.wait()
        return 0, True

    rig.monkeypatch.setattr(rig.db, "count_memory_episodes_by_type_ended_between",
                            _block)
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TEARDOWN_GATHER_S", 30)
    cv = await _restart(rig, await_rehydrate=False)
    task = cv._cap_rehydrate_task
    await asyncio.sleep(0)
    t0 = asyncio.get_running_loop().time()
    await cv.async_teardown()
    # Cancelled by teardown itself, not by the 30 s gather bound.
    assert asyncio.get_running_loop().time() - t0 < 5
    assert task.done() and task.cancelled()


# =================================================================== P3-D8
RADAR = "binary_sensor.media_matter_occupancy"


def _stuck_room(mods, *, dead=None, stuck_kinds=None, listed=()):
    """A room stand-in carrying the REAL room getter (bound from
    UniversalRoomCoordinator) over a REAL SensorExclusionSet, plus the S1/S2
    getters of test_crossing_ledger_wiring._Room (stream view None unless
    ``dead`` says so) and the label map ``get_stuck_sensor_kinds``."""
    coord = importlib.import_module(f"{_PKG}.coordinator")
    sx = importlib.import_module(f"{_PKG}.domain_coordinators.sensor_exclusion")

    class _StuckRoom(_Room):
        camera_input_room_stuck_excluded = (
            coord.UniversalRoomCoordinator.camera_input_room_stuck_excluded)
        camera_input_room_quarantined = (
            coord.UniversalRoomCoordinator.camera_input_room_quarantined)
        get_stuck_sensor_kinds = coord.UniversalRoomCoordinator.get_stuck_sensor_kinds
        _house_state_value = coord.UniversalRoomCoordinator._house_state_value

        def _get_config(self, key, default=None):
            return self.cfg.get(key, default)

    room = _StuckRoom(dead or {})
    room.cfg = {mods.const.CONF_MMWAVE_SENSORS: list(listed)}
    room.hass = None  # set by _install / the caller
    room._exclusion_set = sx.SensorExclusionSet("Media")
    room._stuck_sensor_kinds = dict(stuck_kinds or {})
    return room


def _install(rig, room, eids):
    D = rig.C.DOMAIN
    # A known, non-sleep house state unless the test sets one (an unknown
    # state keeps P22 holding, fail closed).
    if "coordinator_manager" not in rig.hass.data[D]:
        _set_house_state(rig, "away")
    rig.hass.data[D]["occupancy_substrate"] = _Substrate(set(eids))
    rig.hass.data[D]["room_entry_media"] = room
    room.hass = rig.hass
    rig.cv._ledger.empty_reset_s = 0


def _state(rig, R=1):
    rig.cv.census_tick(resident_term=R, camera_bodies=0, camera_input_dark=False)
    rig.cv._on_ledger_eval(None)
    return rig.cv.ledger_state


@pytest.mark.asyncio
async def test_stuck_excluded_on_input_does_not_hold(rig):
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "known"
    d = rig.cv.ledger_diag()
    assert d["held"] == []
    assert (d["held_ignored_stuck"], d["held_ignored_stuck_count"]) == ([RADAR], 1)


@pytest.mark.asyncio
async def test_act_chatter_excluded_does_not_hold(rig):
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote("chatter", RADAR, "physics_violation")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "known"


@pytest.mark.asyncio
async def test_promoted_dutycycle_excluded_does_not_hold(rig):
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote("stuck_dutycycle", RADAR, "dutycycle_stuck")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "known"


@pytest.mark.asyncio
async def test_dutycycle_label_without_exclusion_still_holds(rig):
    """A sleeper: duty-cycle LABEL in the stuck-kind map, not promoted."""
    room = _stuck_room(rig.mods, stuck_kinds={RADAR: "dutycycle"})
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    d = rig.cv.ledger_diag()
    assert (d["held"], d["held_ignored_stuck"]) == ([RADAR], [])


@pytest.mark.asyncio
async def test_shadow_chatter_still_holds(rig):
    """Chatter in shadow mode: labelled `chatter` in the kind map, never
    promoted into the exclusion set."""
    room = _stuck_room(rig.mods, stuck_kinds={RADAR: "chatter"})
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]


@pytest.mark.asyncio
@pytest.mark.parametrize("dead_state", ["unavailable", "unknown"])
async def test_dead_input_still_holds_even_if_stuck_excluded(rig, dead_state):
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, dead_state)  # no known-good: held
    assert _state(rig) == "unknown"
    d = rig.cv.ledger_diag()
    assert (d["held"], d["held_ignored_stuck"]) == ([RADAR], [])


@pytest.mark.asyncio
async def test_stream_dead_on_input_still_holds_even_if_stuck_excluded(rig):
    """Reads `on` but its camera stream is dead (view HELD): dead, holds."""
    room = _stuck_room(rig.mods, dead={RADAR: True})
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]


@pytest.mark.asyncio
async def test_ignored_input_last_good_on_holds_when_it_dies(rig):
    """While ignored its `on` stays the last known-good reading (it was
    `off` before), so when it then goes unavailable it holds (dead input
    rule)."""
    room = _stuck_room(rig.mods)
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "off")
    assert _state(rig) == "known"
    assert rig.cv._last_good[RADAR] == "off"
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    rig.hass.states.async_set(RADAR, "on")
    rig.cv._ledger.set_unknown("test")
    assert _state(rig) == "known"
    assert rig.cv._last_good[RADAR] == "on"
    rig.cv._ledger.set_unknown("test")
    rig.hass.states.async_set(RADAR, "unavailable")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]


@pytest.mark.asyncio
async def test_camera_stream_client_only_still_holds(rig):
    """Excluded only by the camera-stream client (S1), view None this
    sample: not a stuck client, so a live `on` still holds."""
    csh = importlib.import_module(f"{_PKG}.domain_coordinators.camera_stream_health")
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote(csh.EXCLUSION_CLIENT, RADAR, "stream_dead")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]


@pytest.mark.asyncio
async def test_stuck_getter_failure_keeps_holding(rig):
    room = _stuck_room(rig.mods)
    from types import SimpleNamespace

    def _boom(_eid):
        raise RuntimeError("exclusion set broken")

    room._exclusion_set = SimpleNamespace(clients_for=_boom,
                                          is_excluded=lambda _e: True)
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]


@pytest.mark.asyncio
async def test_ignores_stuck_kill_switch_restores_rule(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK",
                            False)
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    d = rig.cv.ledger_diag()
    assert (d["held"], d["held_ignored_stuck"]) == ([RADAR], [])


@pytest.mark.asyncio
async def test_stuck_clients_knob_empty_extreme(rig):
    """Config extreme: an empty stuck-client set = nothing is ignored."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_ANCHOR_STUCK_CLIENTS",
                            frozenset())
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"


@pytest.mark.asyncio
async def test_held_ignored_stuck_listed(rig):
    """Two inputs: the stuck one is listed as ignored, the live sleeper
    radar keeps holding; the anchor-zero page names both lists."""
    other = "binary_sensor.jaya_zk_presence"
    texts = []

    async def _fire(hass_, kind, key, diagnosis, remedy="", now=None,
                    title_override=None, exclusion_engaged=False, severity=None):
        texts.append({"kind": kind, "diagnosis": diagnosis})
        return True

    rig.monkeypatch.setattr(rig.mods.stuck, "fire_stuck_signal", _fire)
    room = _stuck_room(rig.mods)
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR, other})
    rig.hass.states.async_set(RADAR, "on")
    rig.hass.states.async_set(other, "on")
    assert _state(rig) == "unknown"
    d = rig.cv.ledger_diag()
    assert (d["held"], d["held_ignored_stuck"]) == ([other], [RADAR])
    rig.cv._ledger.anchor_zero_s = 1e-6
    await asyncio.sleep(0.001)
    _state(rig)
    await settle(rig)
    [page] = [t for t in texts if t["kind"] == "crossing_ledger_anchor_zero"]
    assert other in page["diagnosis"]
    assert f"Ignored as stuck (room-excluded): {RADAR}." in page["diagnosis"]


@pytest.mark.asyncio
async def test_house_wrapper_folds_rooms(rig):
    """The module wrapper asks every room: one room's stuck exclusion wins;
    no room answering = False."""
    csh = importlib.import_module(f"{_PKG}.domain_coordinators.camera_stream_health")
    assert csh.input_room_stuck_excluded(rig.hass, RADAR) is False
    _set_house_state(rig, "away")
    room_a = _stuck_room(rig.mods)  # does not list it: no opinion
    room_b = _stuck_room(rig.mods)
    room_a.hass = room_b.hass = rig.hass
    room_b._exclusion_set.promote("stuck_dutycycle", RADAR, "dutycycle_stuck")
    rig.hass.data[rig.C.DOMAIN]["room_a"] = room_a
    assert csh.input_room_stuck_excluded(rig.hass, RADAR) is False
    rig.hass.data[rig.C.DOMAIN]["room_b"] = room_b
    assert csh.input_room_stuck_excluded(rig.hass, RADAR) is True
    assert csh.input_room_stuck_excluded(rig.hass, "") is False


# ------------------------------------------------ review fix-ups (D-M1, D-L1)
class _Presence:
    def __init__(self, hs):
        self.house_state = hs


def _set_house_state(rig, hs):
    from types import SimpleNamespace

    rig.hass.data[rig.C.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": _Presence(hs)})


@pytest.mark.asyncio
@pytest.mark.parametrize("hs", ["sleep", "waking", "home_night"])
async def test_p22_still_occupant_holds_while_asleep(rig, hs):
    """D-M1: a still sleeper's radar P22-excluded at 4 h keeps holding in
    SLEEP / WAKING / HOME_NIGHT."""
    _set_house_state(rig, hs)
    room = _stuck_room(rig.mods, listed=[RADAR])
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]


@pytest.mark.asyncio
async def test_p22_same_input_releases_while_away(rig):
    _set_house_state(rig, "away")
    room = _stuck_room(rig.mods, listed=[RADAR])
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "known"
    assert rig.cv.ledger_diag()["held_ignored_stuck"] == [RADAR]


@pytest.mark.asyncio
async def test_dutycycle_promoted_still_releases_while_asleep(rig):
    """The sleep gate is on the P22 client only."""
    _set_house_state(rig, "sleep")
    room = _stuck_room(rig.mods, listed=[RADAR])
    room._exclusion_set.promote("stuck_dutycycle", RADAR, "dutycycle_stuck")
    # Also P22-excluded: only the P22 client is dropped in SLEEP.
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "known"


@pytest.mark.asyncio
async def test_p22_hold_states_knob_empty_releases_in_sleep(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_ANCHOR_P22_HOLD_STATES",
                            frozenset())
    _set_house_state(rig, "sleep")
    room = _stuck_room(rig.mods, listed=[RADAR])
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room, {RADAR})
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "known"


@pytest.mark.asyncio
async def test_two_room_input_needs_every_room_to_exclude(rig):
    """D-L1: the input is listed in rooms A and B; A P22-excludes it, B
    counts it live -> it holds. Once B excludes it too, it releases."""
    room_a = _stuck_room(rig.mods, listed=[RADAR])
    room_b = _stuck_room(rig.mods, listed=[RADAR])
    room_a._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    _install(rig, room_a, {RADAR})
    rig.hass.data[rig.C.DOMAIN]["room_entry_b"] = room_b
    room_b.hass = rig.hass
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]
    room_b._exclusion_set.promote("chatter", RADAR, "physics_violation")
    assert _state(rig) == "known"


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,secret", [
    ("Request failed: 400 for url https://gen.example/v1/x?key=AIzaSyABC123&alt=json",
     "AIzaSyABC123"),
    ("Incorrect API key provided: sk-proj-AbC_123-xyz. See docs", "AbC_123-xyz"),
    ("401 Unauthorized, header Authorization: Bearer eyJhbGciOi.payload.sig",
     "eyJhbGciOi.payload.sig"),
])
async def test_error_text_scrubbed(rig, raw, secret):
    rig.llm.reply = RuntimeError(raw)
    await ended_crossing(rig, "ev-scrub")
    [row] = rows(rig)
    assert secret not in row["error"]
    assert "[redacted]" in row["error"]


@pytest.mark.asyncio
async def test_call_time_gate_reads_hold(rig):
    """A1 (defence in depth): a request scheduled before a hold is set is
    skipped at call time while the hold is on (no call)."""
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 2
    frigate(rig, "ev-ct", "garage_a", s)  # event still open: request waits
    await cross(rig, GARAGE_EGRESS, e)
    assert rig.llm.calls == [] and rows(rig) == []
    rig.cv._cap_hold = True
    frigate(rig, "ev-ct", "garage_a", s, typ="end", end=s + 8)
    await settle(rig)
    assert rig.llm.calls == []
    assert [r["outcome"] for r in rows(rig)] == ["skipped_cap"]


@pytest.mark.asyncio
async def test_p22_holds_when_house_state_unknown(rig):
    """No coordinator manager / presence (boot): P22 fails CLOSED."""
    room = _stuck_room(rig.mods, listed=[RADAR])
    room._exclusion_set.promote("p22_continuous", RADAR, "continuous_on")
    D = rig.C.DOMAIN
    rig.hass.data[D]["occupancy_substrate"] = _Substrate({RADAR})
    rig.hass.data[D]["room_entry_media"] = room
    room.hass = rig.hass
    rig.cv._ledger.empty_reset_s = 0
    rig.hass.data[D].pop("coordinator_manager", None)
    rig.hass.states.async_set(RADAR, "on")
    assert _state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]
    _set_house_state(rig, None)  # presence present, state not set
    assert _state(rig) == "unknown"

"""Crossing ledger wiring (PLANNING_crossing_vision.md P2-D3).

Same REAL rig as test_crossing_vision_shadow (real HA core, real bus /
dispatcher / timers, real UniversalRoomDatabase, llmvision stubbed at the
service boundary). Ledger rows are read back from memory_episodes. Each
test drives the producer method that CONTAINS the wiring (egress listener,
_run, the eval tick, the dispatcher listeners), never a helper alone.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_crossing_vision_shadow import (  # noqa: F401 — fixture + helper reuse
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
    rows,
    settle,
)


def ledger_rows(rig):
    conn = sqlite3.connect(rig.db.db_file)
    try:
        return [
            {"node": n, "src": s, **json.loads(a)}
            for n, a, s in conn.execute(
                "SELECT node_id, attrs_json, source_ref FROM memory_episodes "
                "WHERE episode_type = ? ORDER BY id",
                ("crossing_vision_ledger",),
            )
        ]
    finally:
        conn.close()


def terms(rig):
    return [r for r in ledger_rows(rig) if r["kind"] == "term"]


def ensure_substrate(rig):
    rig.hass.data[rig.C.DOMAIN].setdefault("occupancy_substrate", _Substrate(()))


async def make_known(rig, R=1):
    """Ledger known with L = R through the REAL census_tick + eval tick
    (window 0 for the instant anchor). A substrate with an empty Tier-1 map
    is installed when none is (no substrate blocks the anchor, ruling Q2)."""
    ensure_substrate(rig)
    rig.cv._ledger.empty_reset_s = 0
    assert rig.cv.census_tick(resident_term=R, camera_bodies=0,
                              camera_input_dark=False) == (None, True)
    rig.cv._on_ledger_eval(None)
    await settle(rig)
    rig.cv._ledger.empty_reset_s = 10 ** 9  # no further anchor in the test
    # The anchor is dated an hour back so the test crossings (E = now -
    # 45 s .. -300 s) are not "late" terms.
    rig.cv._ledger.last_anchor_ts -= 3600
    assert rig.cv.ledger_state == "known" and rig.cv._ledger.L == R


async def flush(rig):
    rig.cv._on_ledger_eval(None)
    await settle(rig)


def _applied(rig):
    return [(t["direction"], t["n"], t["term_source"]) for t in terms(rig)
            if t["applied"]]


# ------------------------------------------------- every outcome -> a term
OUTCOME_CASES = {
    "ok": ("reply", _ok_reply(frames=(1, 3, 1, 0), total=3), ("entry", 3, "vision")),
    "blank": ("reply", _ok_reply(frames=(0, 0, 0, 0), total=0), ("entry", 2, "camera")),
    "unparseable": ("reply", {"response_text": "not json"}, ("entry", 2, "camera")),
    "refused": ("reply", {"structured_response": {}}, ("entry", 2, "camera")),
    "error": ("reply", RuntimeError("provider down"), ("entry", 2, "camera")),
    "no_frigate_event": ("no_event", None, ("entry", 2, "camera")),
    "skipped_cap": ("cap", None, ("entry", 2, "camera")),
    "no_clip_url": ("no_clip", None, ("entry", 2, "camera")),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(OUTCOME_CASES))
async def test_every_outcome_yields_one_term_or_documented_none(rig, case):
    kind, reply, expected = OUTCOME_CASES[case]
    await make_known(rig, R=1)
    if kind == "reply":
        rig.llm.reply = reply
        await ended_crossing(rig, f"ev-{case}", peak=2)
    elif kind == "no_event":
        await cross(rig, GARAGE_EGRESS, _now(rig) - timedelta(seconds=45), peak=2)
        await settle(rig)
    elif kind == "cap":
        rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 1
        rig.cv._calls_today = 1
        await ended_crossing(rig, "ev-cap", peak=2)
    else:  # no_clip: an unsafe event id -> no clip reference
        await ended_crossing(rig, "ev/../bad", peak=2)
    await flush(rig)
    assert [r["outcome"] for r in rows(rig)] == [case]
    assert _applied(rig) == [expected]
    assert rig.cv._ledger.L == 1 + expected[1]


@pytest.mark.asyncio
async def test_skipped_busy_yields_camera_term(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_MAX_CONCURRENT", 1)
    await make_known(rig, R=0)
    e = _now(rig) - timedelta(seconds=45)
    frigate(rig, "ev-open", "garage_a", e.timestamp() + 1)
    await cross(rig, GARAGE_EGRESS, e, peak=1)
    frigate(rig, "ev-front", "front_door_aerial", e.timestamp() + 2, typ="end",
            end=e.timestamp() + 9)
    await cross(rig, FRONT_EGRESS, e + timedelta(seconds=1), direction="exit", peak=3)
    await settle(rig)
    await flush(rig)
    assert [r["outcome"] for r in rows(rig)] == ["skipped_busy"]
    assert _applied(rig) == [("exit", 3, "camera")]


@pytest.mark.asyncio
async def test_cluster_folds_into_primary_term(rig):
    """Two same-direction crossings sharing one call: ONE term with the
    vision count; the clustered member adds none."""
    await make_known(rig, R=0)
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    rig.llm.reply = _ok_reply(frames=(1, 2, 2, 0), total=2)
    frigate(rig, "ev-cl", "garage_a", s)
    k1 = await cross(rig, GARAGE_EGRESS, e, peak=1)
    await cross(rig, "binary_sensor.doorbell_lite_person_occupancy",
                e + timedelta(seconds=20), peak=1)
    frigate(rig, "ev-cl", "garage_a", s, typ="end", end=s + 30)
    await settle(rig)
    await flush(rig)
    [t] = [t for t in terms(rig) if t["applied"]]
    assert (t["crossing_key"], t["n"], t["term_source"]) == (k1, 2, "vision")
    assert rig.cv._ledger.L == 2


@pytest.mark.asyncio
async def test_cluster_mixed_direction_per_member_camera_terms(rig):
    await make_known(rig, R=0)
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-mix", "garage_a", s)
    await cross(rig, GARAGE_EGRESS, e, peak=2)
    await cross(rig, "binary_sensor.doorbell_lite_person_occupancy",
                e + timedelta(seconds=20), direction="exit", peak=1)
    frigate(rig, "ev-mix", "garage_a", s, typ="end", end=s + 30)
    await settle(rig)
    await flush(rig)
    assert sorted(_applied(rig)) == [("entry", 2, "camera"), ("exit", 1, "camera")]
    assert rig.cv._ledger.L == 1


@pytest.mark.asyncio
async def test_late_joiner_other_direction_gets_own_term(rig):
    await make_known(rig, R=0)
    k1 = await ended_crossing(rig, "ev-done", peak=1)
    e1 = rig.cv._requests[0].e_ts
    await cross(rig, "binary_sensor.doorbell_lite_person_occupancy",
                e1 + timedelta(seconds=30), direction="exit", peak=1)
    await cross(rig, "binary_sensor.doorbell_lite_person_occupancy",
                e1 + timedelta(seconds=40), direction="entry", peak=1)
    await settle(rig)
    await flush(rig)
    assert _applied(rig) == [("entry", 2, "vision"), ("exit", 1, "camera")]
    assert k1 in [t["crossing_key"] for t in terms(rig)]


@pytest.mark.asyncio
async def test_run_exception_still_applies_camera_term(rig):
    await make_known(rig, R=0)
    rig.monkeypatch.setattr(rig.mods.cv, "parse_vision_response",
                            lambda *a, **k: 1 / 0)
    await ended_crossing(rig, "ev-boom", peak=3)
    await flush(rig)
    assert _applied(rig) == [("entry", 3, "camera")]


@pytest.mark.asyncio
async def test_switch_off_sets_unknown(rig):
    await make_known(rig, R=1)
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_SWITCH_HASS_KEY] = False
    await ended_crossing(rig, "ev-off", peak=2)
    # The crossing itself (before any eval or census tick) sets unknown.
    assert rig.cv.ledger_state == "unknown"
    await flush(rig)
    assert rig.cv.ledger_state == "unknown"
    assert rig.cv._ledger.unknown_reason == "switch_off"
    assert terms(rig) == [] and rows(rig) == []
    assert rig.cv.census_tick(resident_term=1, camera_bodies=0,
                              camera_input_dark=False) == (None, False)
    assert rig.cv.vision_status(True) == "switch_off"
    assert rig.cv.diag_status()["crossing_ledger"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_switch_off_eval_tick_sets_unknown(rig):
    """The eval tick re-reads the switch: off -> unknown, no anchor."""
    await make_known(rig, R=1)
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_SWITCH_HASS_KEY] = False
    rig.cv._ledger.empty_reset_s = 0
    await flush(rig)
    assert rig.cv.ledger_state == "unknown"


@pytest.mark.asyncio
async def test_kill_and_cap_zero_set_unknown(rig):
    await make_known(rig, R=1)
    rig.monkeypatch.setattr(rig.C, "LLMVISION_ENRICHMENT_KILL", True)
    await flush(rig)
    assert (rig.cv.ledger_state, rig.cv._ledger.unknown_reason) == ("unknown", "kill")
    rig.monkeypatch.setattr(rig.C, "LLMVISION_ENRICHMENT_KILL", False)
    await make_known(rig, R=1)
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 0
    await flush(rig)
    assert (rig.cv.ledger_state, rig.cv._ledger.unknown_reason) == ("unknown", "cap_zero")


# ---------------------------------------------------------- batched rows
@pytest.mark.asyncio
async def test_ledger_episode_per_term_batched(rig):
    await make_known(rig, R=0)
    assert [r["kind"] for r in ledger_rows(rig)] == ["anchor"]
    spawned = []
    real_spawn = rig.cv._spawn

    def _spy(coro, **kw):
        spawned.append(getattr(coro, "__qualname__", ""))
        return real_spawn(coro, **kw)

    rig.monkeypatch.setattr(rig.cv, "_spawn", _spy)
    await cross(rig, GARAGE_EGRESS, _now(rig) - timedelta(seconds=45), peak=1)
    await cross(rig, FRONT_EGRESS, _now(rig) - timedelta(seconds=300),
                direction="exit", peak=1)
    await settle(rig)
    assert [r["kind"] for r in ledger_rows(rig)] == ["anchor"]  # buffered
    writes_before = [s for s in spawned if "_flush_ledger_events" in s]
    await flush(rig)
    writes = [s for s in spawned if "_flush_ledger_events" in s]
    assert len(writes) - len(writes_before) == 1  # ONE write task per tick
    rows_ = terms(rig)
    assert [(r["direction"], r["l_before"], r["l_after"]) for r in rows_] == [
        ("entry", 0, 1), ("exit", 1, 0)]
    assert all(r["src"] == r["crossing_key"] for r in rows_)
    assert rows_[0]["node"].startswith("ledger:term:")


# ------------------------------------------------------- feed listeners
@pytest.mark.asyncio
async def test_substrate_rising_edge_blocks_anchor(rig, mods):
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from custom_components.universal_room_automation.domain_coordinators import (
        signals,
    )

    ensure_substrate(rig)
    rig.cv._ledger.empty_reset_s = 0
    rig.cv.census_tick(resident_term=1, camera_bodies=0, camera_input_dark=False)
    async_dispatcher_send(rig.hass, signals.SIGNAL_SUBSTRATE_KIND_CHANGED,
                          "Study B", "motion", True)
    await rig.hass.async_block_till_done()
    rig.cv._on_ledger_eval(None)
    assert rig.cv.ledger_state == "unknown"  # the edge failed the sample
    # A falling edge is not a rising edge: the next sample anchors.
    async_dispatcher_send(rig.hass, signals.SIGNAL_SUBSTRATE_KIND_CHANGED,
                          "Study B", "motion", False)
    await rig.hass.async_block_till_done()
    rig.cv.census_tick(resident_term=1, camera_bodies=0, camera_input_dark=False)
    rig.cv._on_ledger_eval(None)
    assert rig.cv.ledger_state == "known"


def _departure(person, edge_ts):
    return SimpleNamespace(kind="departure", person=person, edge_ts=edge_ts)


@pytest.mark.asyncio
async def test_residency_departure_reconciles(rig, mods):
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from custom_components.universal_room_automation.domain_coordinators import (
        signals,
    )

    await make_known(rig, R=0)
    rig.cv._ledger.L = rig.cv._ledger.L_raw = 2
    rig.cv._ledger.reconcile_delay_s = 0.0
    rig.cv._ledger.reconcile_lag_s = 0.01
    t_e = _now(rig).timestamp()
    async_dispatcher_send(rig.hass, signals.SIGNAL_RESIDENCY_EVENT,
                          _departure("person.oji_udezue", t_e))
    # An arrival record is ignored.
    async_dispatcher_send(rig.hass, signals.SIGNAL_RESIDENCY_EVENT,
                          SimpleNamespace(kind="arrival", person="person.ezinne",
                                          edge_ts=t_e))
    await asyncio.sleep(0.1)
    await settle(rig)
    assert rig.cv._ledger.L == 1
    await flush(rig)
    [rec] = [r for r in ledger_rows(rig) if r["kind"] == "reconcile"]
    assert (rec["applied"], rec["person"], rec["l_before"], rec["l_after"]) == (
        True, "person.oji_udezue", 2, 1)


@pytest.mark.asyncio
async def test_superseded_departure_cancels_old_timer(rig, mods):
    """Two departures of one person: only the newer is judged, at ITS due
    time. The older timer (due first) must not judge the newer departure
    before its exit outcome lands."""
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from custom_components.universal_room_automation.domain_coordinators import (
        signals,
    )

    await make_known(rig, R=0)
    rig.cv._ledger.L = rig.cv._ledger.L_raw = 3
    rig.cv._ledger.reconcile_delay_s = 0.3
    rig.cv._ledger.reconcile_lag_s = 0.0
    now = _now(rig).timestamp()
    async_dispatcher_send(rig.hass, signals.SIGNAL_RESIDENCY_EVENT,
                          _departure("person.oji_udezue", now - 0.25))
    async_dispatcher_send(rig.hass, signals.SIGNAL_RESIDENCY_EVENT,
                          _departure("person.oji_udezue", now))
    await asyncio.sleep(0.15)
    # The exit crossing's term lands between the two due times.
    await cross(rig, FRONT_EGRESS, _now(rig) - timedelta(seconds=1),
                direction="exit", peak=1)
    assert rig.cv._ledger.L == 2
    await asyncio.sleep(0.3)
    await settle(rig)
    assert rig.cv._ledger.L == 2  # the exit cancelled the reconcile


@pytest.mark.asyncio
async def test_teardown_unsubscribes_ledger_feeds(rig, mods):
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from custom_components.universal_room_automation.domain_coordinators import (
        signals,
    )

    await make_known(rig, R=0)
    rig.cv._ledger.L = rig.cv._ledger.L_raw = 2
    rig.cv._ledger.reconcile_delay_s = 0.2
    rig.cv._ledger.reconcile_lag_s = 0.01
    async_dispatcher_send(rig.hass, signals.SIGNAL_RESIDENCY_EVENT,
                          _departure("person.oji_udezue", _now(rig).timestamp()))
    await rig.hass.async_block_till_done()
    assert list(rig.cv._reconcile_timers) == ["person.oji_udezue"]
    await rig.cv.async_teardown()
    assert rig.cv._reconcile_timers == {}
    await asyncio.sleep(0.4)
    await rig.hass.async_block_till_done()
    assert rig.cv._ledger.L == 2  # the cancelled timer never judged
    # Feeds unsubscribed: an edge and a departure after teardown do nothing.
    async_dispatcher_send(rig.hass, signals.SIGNAL_SUBSTRATE_KIND_CHANGED,
                          "Study B", "motion", True)
    async_dispatcher_send(rig.hass, signals.SIGNAL_RESIDENCY_EVENT,
                          _departure("person.ezinne", _now(rig).timestamp()))
    await rig.hass.async_block_till_done()
    assert rig.cv._ledger._edge_since_sample is False
    assert rig.cv._ledger.pending_people() == ["person.oji_udezue"]
    # Review B-L2: the real dispatcher holds no listener of this instance
    # for either feed (the early `_torn_down` returns above cannot tell).
    from homeassistant.helpers.dispatcher import DATA_DISPATCHER

    table = rig.hass.data.get(DATA_DISPATCHER, {})
    for sig in (signals.SIGNAL_SUBSTRATE_KIND_CHANGED,
                signals.SIGNAL_RESIDENCY_EVENT):
        owners = [getattr(t, "__self__", None) for t in table.get(sig, {})]
        assert rig.cv not in owners, sig


@pytest.mark.asyncio
async def test_dispatcher_feeds_registered_before_teardown(rig, mods):
    """Positive control for the B-L2 oracle: while set up, both feeds are
    in the dispatcher table with this instance as owner."""
    from homeassistant.helpers.dispatcher import DATA_DISPATCHER

    from custom_components.universal_room_automation.domain_coordinators import (
        signals,
    )

    table = rig.hass.data.get(DATA_DISPATCHER, {})
    for sig in (signals.SIGNAL_SUBSTRATE_KIND_CHANGED,
                signals.SIGNAL_RESIDENCY_EVENT):
        owners = [getattr(t, "__self__", None) for t in table.get(sig, {})]
        assert rig.cv in owners, sig


@pytest.mark.asyncio
async def test_eval_interval_registered_and_runs(rig):
    """The tracked anchor interval is real: firing time forward runs it."""
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    ensure_substrate(rig)
    rig.cv._ledger.empty_reset_s = 0
    rig.cv.census_tick(resident_term=1, camera_bodies=0, camera_input_dark=False)
    async_fire_time_changed(
        rig.hass, dt_util.utcnow() + timedelta(seconds=61))
    await rig.hass.async_block_till_done()
    assert rig.cv.ledger_state == "known"


# ---------------------------------------------------------- trip-wires
@pytest.mark.asyncio
async def test_stuck_ledger_pages_once(rig):
    await make_known(rig, R=0)
    rig.cv._ledger.L = rig.cv._ledger.L_raw = 2
    rig.cv._ledger.stuck_s = 1e-6
    for _ in range(5):
        rig.cv.census_tick(resident_term=0, camera_bodies=0, camera_input_dark=False)
        await flush(rig)
        await asyncio.sleep(0.001)
    stuck = [p for p in rig.pages if p["kind"] == "crossing_ledger_stuck"]
    assert len(stuck) == 1 and stuck[0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_anchor_zero_pages(rig):
    rig.cv._ledger.anchor_zero_s = 1e-6
    rig.cv.census_tick(resident_term=1, camera_bodies=1, camera_input_dark=False)
    rig.cv._on_ledger_eval(None)  # enable edge: rebase
    await asyncio.sleep(0.001)
    for _ in range(3):
        await flush(rig)
    pages = [p for p in rig.pages if p["kind"] == "crossing_ledger_anchor_zero"]
    assert len(pages) == 1 and pages[0]["severity"] == "LOW"


@pytest.mark.asyncio
async def test_anchor_independent_of_house_state(rig):
    """Wiring twin of the pure test: the house reading AWAY or HOME makes no
    difference to the anchor (the predicate reads no house state)."""
    ensure_substrate(rig)
    results = []
    for house in ("away", "home_day"):
        rig.hass.data[rig.C.DOMAIN]["coordinator_manager"] = SimpleNamespace(
            house_state=house, coordinators={})
        rig.hass.states.async_set("sensor.ura_presence_house_state", house)
        rig.cv._ledger.set_unknown("test")
        rig.cv._ledger.empty_reset_s = 0
        rig.cv.census_tick(resident_term=1, camera_bodies=0, camera_input_dark=False)
        rig.cv._on_ledger_eval(None)
        results.append((rig.cv.ledger_state, rig.cv._ledger.L))
    assert results == [("known", 1), ("known", 1)]


@pytest.mark.asyncio
async def test_open_tracks_sensor_carries_ledger_diag_unrecorded(rig):
    """The diagnostic attribute reaches the Outside: Open Tracks sensor and
    is kept out of the recorder."""
    sensor = rig.mods.sensor
    cls = next(c for c in vars(sensor).values()
               if isinstance(c, type) and "crossing_vision_today"
               in getattr(c, "_unrecorded_attributes", ()))
    assert "crossing_ledger" in cls._unrecorded_attributes
    diag = rig.cv.diag_status()["crossing_ledger"]
    assert set(diag) >= {"state", "L", "L_raw", "last_anchor", "residue_last",
                         "terms_today", "reconciled_today"}


@pytest.mark.asyncio
async def test_anchor_zero_clock_restarts_on_enable(rig):
    """A long switch-off is not an anchor drought: the enable edge restarts
    the anchor-zero clock (no page at the first tick after turning on)."""
    rig.cv._on_ledger_eval(None)
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_SWITCH_HASS_KEY] = False
    await flush(rig)
    rig.cv._ledger.anchor_zero_s = 86400
    rig.cv._ledger.setup_ts -= 10 * 86400  # off for ten days
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_SWITCH_HASS_KEY] = True
    await flush(rig)
    assert [p for p in rig.pages if p["kind"] == "crossing_ledger_anchor_zero"] == []


# ----------------------------------------------------- CD3 trip-wires
@pytest.mark.asyncio
@pytest.mark.parametrize("persist_n,expect", [(5, 1), (6, 0), (0, 0)])
async def test_disagree_persist_pages(rig, persist_n, expect):
    """Five `ok` crossings at the garage door where vision counts 2 and the
    camera 1 (case B): PERSIST_N 5 pages once (and not again on the next
    evaluation), 6 does not, 0 = off."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_DISAGREE_PERSIST_N", persist_n)
    for i in range(5):
        await ended_crossing(rig, f"ev-dis-{i}", offset_s=-70.0 * i, peak=1)
    assert [r["agreement_case"] for r in rows(rig)] == ["B"] * 5
    await rig.cv.async_evaluate_tripwires()
    await rig.cv.async_evaluate_tripwires()
    pages = [p for p in rig.pages if p["kind"] == "crossing_vision_disagree"]
    assert len(pages) == expect
    if expect:
        assert pages[0]["key"] == ("garage_a",)
        # Review B-M1: MEDIUM reaches no channel; the page is HIGH.
        assert pages[0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_bar_regression_pages_only_after_flip(rig):
    """Drift bar a regressed (10 independent anchors, residue 2 each):
    no page while F-LEAD is off; one HIGH "revert F-LEAD" page after the
    flip, not repeated while it stays regressed."""
    now = _now(rig).timestamp()
    for i in range(10):
        rig.cv._anchor_residues.append((now - 60 * i, 2))
    await rig.cv.async_evaluate_tripwires()
    assert [p for p in rig.pages if p["kind"] == "crossing_vision_flead_regression"] == []
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_AWARENESS_VISION_LEADS", True)
    await rig.cv.async_evaluate_tripwires()
    await rig.cv.async_evaluate_tripwires()
    pages = [p for p in rig.pages if p["kind"] == "crossing_vision_flead_regression"]
    assert len(pages) == 1 and pages[0]["severity"] == "HIGH"
    assert rig.cv.flead_regression(now) == ["a_drift"]


@pytest.mark.asyncio
async def test_flead_regression_bars_hold_no_page(rig):
    """Bars holding (residue 0 on 10 anchors, ledger known all week): no page
    after the flip. Known share below 0.9 over a full week -> e_known."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_AWARENESS_VISION_LEADS", True)
    now = _now(rig).timestamp()
    for i in range(10):
        rig.cv._anchor_residues.append((now - 60 * i, 0))
    week = 7 * 86400
    for i in range(100):
        rig.cv._known_samples.append((now - week - 10 + i * (week / 100), True))
    assert rig.cv.flead_regression(now) == []
    await rig.cv.async_evaluate_tripwires()
    assert [p for p in rig.pages if p["kind"] == "crossing_vision_flead_regression"] == []
    rig.cv._known_samples.clear()
    for i in range(100):
        rig.cv._known_samples.append((now - week - 10 + i * (week / 100), i % 5 != 0))
    assert rig.cv.flead_regression(now) == ["e_known"]


@pytest.mark.asyncio
async def test_eval_tick_records_independent_anchor_residues(rig):
    """The bar-a input is fed by the real eval tick: an independent anchor
    with a residue is recorded; a back-to-back one is not."""
    await make_known(rig, R=0)
    rig.cv._ledger.L = rig.cv._ledger.L_raw = 2
    rig.cv._ledger._changed_since_anchor = True
    rig.cv._ledger.empty_reset_s = 0
    rig.cv.census_tick(resident_term=0, camera_bodies=0, camera_input_dark=False)
    await flush(rig)
    rig.cv.census_tick(resident_term=0, camera_bodies=0, camera_input_dark=False)
    await flush(rig)
    assert [res for _t, res in rig.cv._anchor_residues] == [2]
    assert rig.cv._known_samples and rig.cv._known_samples[-1][1] is True


# --------------------------------------------- held inputs (P2-D2 step 2)
class _Substrate:
    def __init__(self, eids):
        self.eids = frozenset(eids)

    def tier1_entity_ids(self):
        return self.eids


class _Room:
    """A room coordinator stand-in exposing only the S1 getter."""

    def __init__(self, dead):
        self.dead = dict(dead)

    def camera_input_stream_dead(self, eid):
        return self.dead.get(eid)


RADAR = "binary_sensor.radar_gb1"
PIR = "binary_sensor.pir_hall"
PANEL = "binary_sensor.panel_person"


def _eval_anchor_state(rig, R=1):
    ensure_substrate(rig)
    rig.cv.census_tick(resident_term=R, camera_bodies=0, camera_input_dark=False)
    rig.cv._on_ledger_eval(None)
    return rig.cv.ledger_state


@pytest.mark.asyncio
async def test_held_set_from_substrate_map_and_lkg(rig):
    """The REAL eval tick builds `held` from the substrate's Tier-1 map,
    hass.states and the RAM last-known-good map: a radar on holds; the same
    radar unavailable still holds (last good on); a PIR off then unavailable
    does not; a panel whose camera stream reads dead (S1 getter) holds with
    no good reading. Only when every holder releases does the anchor fire."""
    from custom_components.universal_room_automation.domain_coordinators import (
        occupancy_substrate as osub,
    )

    D = rig.C.DOMAIN
    # The REAL substrate's getter over its (room, kind) map.
    sub = osub.OccupancySubstrate(rig.hass)
    sub._entity_to_room_kind = {RADAR: ("Guest Bedroom 1", "mmwave"),
                                PIR: ("Hall", "motion"),
                                PANEL: ("Kitchen", "occupancy")}
    rig.hass.data[D]["occupancy_substrate"] = sub
    room = _Room({PANEL: True})
    rig.hass.data[D]["room_entry_x"] = room
    rig.cv._ledger.empty_reset_s = 0
    rig.hass.states.async_set(RADAR, "on")
    rig.hass.states.async_set(PIR, "off")
    rig.hass.states.async_set(PANEL, "off")
    assert _eval_anchor_state(rig) == "unknown"
    assert set(rig.cv.ledger_diag()["held"]) == {RADAR, PANEL}
    rig.hass.states.async_set(RADAR, "unavailable")
    rig.hass.states.async_set(PIR, "unavailable")
    room.dead[PANEL] = False  # stream back; panel reads off (good)
    assert _eval_anchor_state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == [RADAR]  # dead, last good on
    rig.hass.states.async_set(RADAR, "off")
    assert _eval_anchor_state(rig) == "known"
    assert rig.cv.ledger_diag()["held"] == []


@pytest.mark.asyncio
async def test_no_substrate_blocks_anchor(rig):
    """Ruling Q2: no occupancy substrate = no Tier-1 map = unknown, not
    empty: the anchor stays blocked and the pseudo-holder is shown. Once a
    substrate (empty map) appears, the anchor fires."""
    D = rig.C.DOMAIN
    rig.hass.data[D].pop("occupancy_substrate", None)
    rig.cv._ledger.empty_reset_s = 0
    for _ in range(3):
        rig.cv.census_tick(resident_term=1, camera_bodies=0,
                           camera_input_dark=False)
        rig.cv._on_ledger_eval(None)
    assert rig.cv.ledger_state == "unknown"
    assert rig.cv.ledger_diag()["held"] == ["tier1_map_unavailable"]
    rig.hass.data[D]["occupancy_substrate"] = _Substrate(())
    assert _eval_anchor_state(rig) == "known"


class _BrokenSubstrate:
    def tier1_entity_ids(self):
        raise RuntimeError("map not built")


@pytest.mark.asyncio
async def test_substrate_getter_error_blocks_anchor(rig):
    rig.hass.data[rig.C.DOMAIN]["occupancy_substrate"] = _BrokenSubstrate()
    rig.cv._ledger.empty_reset_s = 0
    assert _eval_anchor_state(rig) == "unknown"
    assert rig.cv.ledger_diag()["held"] == ["tier1_map_unavailable"]


@pytest.mark.asyncio
async def test_torn_down_substrate_blocks_anchor(rig):
    sub = _Substrate(())
    sub._is_torn_down = True
    rig.hass.data[rig.C.DOMAIN]["occupancy_substrate"] = sub
    rig.cv._ledger.empty_reset_s = 0
    assert _eval_anchor_state(rig) == "unknown"


GHOST = "binary_sensor.mmwave_zigbee_gameroom_presence"


@pytest.mark.asyncio
async def test_tier1_entity_never_in_registry_ignored_and_flagged(rig, caplog):
    """Sweep finding: a Tier-1 entity with no registry entry and no state
    (the live Exercise Room ghost) is ignored for the held set (the anchor
    fires), listed and counted on the diagnostics, and logged once. A
    registered entity with no state (restored-missing) still holds."""
    from homeassistant.helpers import entity_registry as er

    D = rig.C.DOMAIN
    reg = er.async_get(rig.hass)
    if not hasattr(reg, "entities"):  # the bare test hass never loaded it
        await reg.async_load()
    kept = reg.async_get_or_create("binary_sensor", "test", "kept_radar_uid",
                                   suggested_object_id="kept_radar")
    rig.hass.data[D]["occupancy_substrate"] = _Substrate({GHOST})
    rig.cv._ledger.empty_reset_s = 0
    caplog.set_level("WARNING")
    assert _eval_anchor_state(rig) == "known"
    diag = rig.cv.ledger_diag()
    assert (diag["held"], diag["tier1_not_in_registry"],
            diag["tier1_not_in_registry_count"]) == ([], [GHOST], 1)
    for _ in range(2):
        _eval_anchor_state(rig)
    assert sum(GHOST in r.getMessage() for r in caplog.records) == 1
    # A registry entity with no state is NOT a ghost: held (no good reading).
    rig.cv._ledger.set_unknown("test")
    rig.hass.data[D]["occupancy_substrate"] = _Substrate({GHOST, kept.entity_id})
    assert _eval_anchor_state(rig) == "unknown"
    diag = rig.cv.ledger_diag()
    assert diag["held"] == [kept.entity_id]
    assert diag["tier1_not_in_registry"] == [GHOST]


@pytest.mark.asyncio
async def test_stuck_not_paged_while_held(rig):
    D = rig.C.DOMAIN
    await make_known(rig, R=0)
    rig.cv._ledger.L = rig.cv._ledger.L_raw = 2
    rig.cv._ledger.stuck_s = 1e-6
    rig.hass.data[D]["occupancy_substrate"] = _Substrate({RADAR})
    rig.hass.states.async_set(RADAR, "on")
    for _ in range(5):
        rig.cv.census_tick(resident_term=0, camera_bodies=0, camera_input_dark=False)
        await flush(rig)
        await asyncio.sleep(0.001)
    assert [p for p in rig.pages if p["kind"] == "crossing_ledger_stuck"] == []


def _capture_text(rig):
    texts = []

    async def _fire(hass_, kind, key, diagnosis, remedy="", now=None,
                    title_override=None, exclusion_engaged=False,
                    severity=None):
        texts.append({"kind": kind, "diagnosis": diagnosis,
                      "severity": severity})
        return True

    rig.monkeypatch.setattr(rig.mods.stuck, "fire_stuck_signal", _fire)
    return texts


@pytest.mark.asyncio
async def test_anchor_zero_names_dead_holder(rig):
    """The anchor-zero page names the holders seen since the last anchor,
    dead ones first ("a dead input is faulty equipment")."""
    D = rig.C.DOMAIN
    dead_eid = "binary_sensor.z_dead_motion"  # sorts after the radar
    texts = _capture_text(rig)
    sub = _Substrate({RADAR})
    rig.hass.data[D]["occupancy_substrate"] = sub
    rig.hass.states.async_set(RADAR, "on")
    rig.hass.states.async_set(dead_eid, "unavailable")  # never good: held
    rig.cv._ledger.anchor_zero_s = 3600.0
    for i in range(3):
        if i == 1:  # the dead input joins the map: seen fewer times
            sub.eids = frozenset({RADAR, dead_eid})
        rig.cv.census_tick(resident_term=1, camera_bodies=0, camera_input_dark=False)
        await flush(rig)
    assert rig.cv._holder_counts == {RADAR: 3, dead_eid: 2}
    rig.cv._ledger.anchor_zero_s = 1e-6
    await asyncio.sleep(0.001)
    rig.cv.census_tick(resident_term=1, camera_bodies=0, camera_input_dark=False)
    await flush(rig)
    [page] = [t for t in texts if t["kind"] == "crossing_ledger_anchor_zero"]
    assert page["severity"] == "LOW"
    text = page["diagnosis"]
    assert f"{dead_eid} (dead)" in text and RADAR in text
    assert text.index(dead_eid) < text.index(RADAR)  # dead first


@pytest.mark.asyncio
async def test_anchor_zero_silent_without_census_tick(rig):
    """Enhanced census off: no census_tick ever -> no anchor-zero page; the
    cause is named in the diagnostics."""
    rig.cv._ledger.anchor_zero_s = 1e-6
    for _ in range(3):
        await flush(rig)
        await asyncio.sleep(0.001)
    assert [p for p in rig.pages if p["kind"] == "crossing_ledger_anchor_zero"] == []
    assert rig.cv.ledger_diag()["anchor_zero_suppressed"] == "no_census_tick"


@pytest.mark.asyncio
async def test_lift_row_written_from_census_tick(rig):
    """The arrival-floor lift produced inside census_tick reaches a
    `crossing_vision_ledger` row (kind lift) with the next batch."""
    await make_known(rig, R=1)
    rig.cv.census_tick(resident_term=2, camera_bodies=1, camera_input_dark=False)
    assert rig.cv._ledger.L == 2
    await flush(rig)
    [lift] = [r for r in ledger_rows(rig) if r["kind"] == "lift"]
    assert (lift["n"], lift["l_before"], lift["l_after"]) == (1, 1, 2)
    assert rig.cv.ledger_diag()["open_credits"][0][1] == 1


@pytest.mark.asyncio
async def test_resident_arrival_then_entry_term_counted_once_wired(rig):
    """W1 through the real producer: B's arrival (R 1 -> 2) before B's own
    garage entry term: L = 2, guest_vis 0."""
    await make_known(rig, R=1)
    rig.cv.census_tick(resident_term=2, camera_bodies=1, camera_input_dark=False)
    rig.llm.reply = _ok_reply(frames=(1, 1, 0, 0), total=1)
    await ended_crossing(rig, "ev-b", peak=1)
    await flush(rig)
    assert rig.cv._ledger.L == 2
    assert rig.cv.census_tick(resident_term=2, camera_bodies=1,
                              camera_input_dark=False) == (0, True)
    [t] = [t for t in terms(rig) if t["applied"]]
    assert t["credit_consumed"] == 1


# ------------------------------------------------ review C fix-up (H1-M5)
@pytest.mark.asyncio
async def test_dark_fleet_through_census_tick_blocks_anchor(rig):
    """Review C H1 (hop 2, CV30): census_tick(camera_input_dark=True)
    reports unhealthy and the anchor does not fire on a blind fleet
    (bodies read 0); the same sample lit anchors."""
    ensure_substrate(rig)
    rig.cv._ledger.empty_reset_s = 0
    for _ in range(3):
        assert rig.cv.census_tick(resident_term=1, camera_bodies=0,
                                  camera_input_dark=True) == (None, False)
        rig.cv._on_ledger_eval(None)
    assert rig.cv.ledger_state == "unknown"
    assert rig.cv.vision_status(False) == "unknown_ledger"
    assert rig.cv.census_tick(resident_term=1, camera_bodies=0,
                              camera_input_dark=False) == (None, True)
    rig.cv._on_ledger_eval(None)
    assert rig.cv.ledger_state == "known"


@pytest.mark.asyncio
async def test_flush_writes_each_row_once(rig):
    """Review C H2 (CV59): two consecutive flushes after one term write
    exactly one term row; the buffer is empty after the first."""
    await make_known(rig, R=0)
    await cross(rig, GARAGE_EGRESS, _now(rig) - timedelta(seconds=45), peak=1)
    await settle(rig)
    await flush(rig)
    assert rig.cv._ledger_events == []
    await flush(rig)
    await flush(rig)
    assert len(terms(rig)) == 1
    assert [r["kind"] for r in ledger_rows(rig)] == ["anchor", "term"]


@pytest.mark.asyncio
async def test_disagree_window_ages_out_samples(rig):
    """Review C M4 (CV72): five disagreements older than the window
    (3600 s here) never page."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_DISAGREE_WINDOW_S", 3600)
    now = rig.cv._epoch()
    for i in range(5):
        rig.cv._disagree.append((now - 3700 - i, "garage_a"))
    await rig.cv.async_evaluate_tripwires()
    assert [p for p in rig.pages if p["kind"] == "crossing_vision_disagree"] == []
    assert len(rig.cv._disagree) == 0


@pytest.mark.asyncio
async def test_disagree_rearms_after_falling_under_bar(rig):
    """Review C M4 (CV70): a group pages, its samples age out (count under
    the bar re-arms it), five new disagreements page again."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_DISAGREE_WINDOW_S", 3600)
    now = rig.cv._epoch()
    for i in range(5):
        rig.cv._disagree.append((now - 10 - i, "garage_a"))
    await rig.cv.async_evaluate_tripwires()
    rig.cv._disagree.clear()
    await rig.cv.async_evaluate_tripwires()  # under the bar: re-armed
    for i in range(5):
        rig.cv._disagree.append((now - i, "garage_a"))
    await rig.cv.async_evaluate_tripwires()
    pages = [p for p in rig.pages if p["kind"] == "crossing_vision_disagree"]
    assert len(pages) == 2


@pytest.mark.asyncio
async def test_flead_regression_rearms_when_bars_hold(rig):
    """Review C M4 (CV75): regressed -> one page; bars hold -> re-armed;
    regressed again -> a second page."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_AWARENESS_VISION_LEADS", True)
    now = rig.cv._epoch()

    def _residues(v):
        rig.cv._anchor_residues.clear()
        for i in range(10):
            rig.cv._anchor_residues.append((now - 60 * i, v))

    _residues(2)
    await rig.cv.async_evaluate_tripwires()
    _residues(0)
    await rig.cv.async_evaluate_tripwires()
    _residues(2)
    await rig.cv.async_evaluate_tripwires()
    pages = [p for p in rig.pages if p["kind"] == "crossing_vision_flead_regression"]
    assert len(pages) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("residues,expect", [
    ([1] * 10, ["a_drift"]),          # zero share 0 alone (|x| <= 1)
    ([0] * 9 + [2], ["a_drift"]),     # max-abs alone (zero share 0.9)
    ([2] * 9, []),                      # under 10 anchors: not judged
    ([0] * 8 + [1, -1], []),           # both bars hold (0.8, |x| <= 1)
], ids=["zero_share_only", "max_abs_only", "min_anchors", "holds"])
async def test_drift_bar_clauses_separately(rig, residues, expect):
    """Review C M4 (CV76 / CV77 / CV79): each drift clause trips alone."""
    now = rig.cv._epoch()
    for i, v in enumerate(residues):
        rig.cv._anchor_residues.append((now - 60 * i, v))
    assert rig.cv.flead_regression(now) == expect


@pytest.mark.asyncio
async def test_clustered_member_primary_left_ring_gets_camera_term(rig):
    """Review C M5 (CV02): the matched event was analysed by a primary
    that has left the request ring: the new member is recorded clustered
    and still gets its own camera term."""
    await make_known(rig, R=0)
    await ended_crossing(rig, "ev-gone", peak=1)
    e1 = rig.cv._requests[0].e_ts
    rig.cv._requests.clear()
    k2 = await cross(rig, GARAGE_EGRESS, e1 + timedelta(seconds=1), peak=1)
    await settle(rig)
    await flush(rig)
    assert [r["outcome"] for r in rows(rig)][-1] == "clustered"
    mine = [t for t in terms(rig) if t["crossing_key"] == k2]
    assert [(t["applied"], t["direction"], t["n"], t["term_source"])
            for t in mine] == [(True, "entry", 1, "camera")]


@pytest.mark.asyncio
async def test_producer_anchor_window_is_15_minutes(rig):
    """Operator 2026-11-14: the producer's ledger anchors after 15 min
    (900 s) of passing samples, not 14 (the window the real producer was
    built with; literal oracle, never the imported constant)."""
    led = rig.cv._ledger
    t0 = rig.cv._epoch()
    for minute in range(15):
        led.census_tick(t0 + 60 * minute, 1, 0, False)
        assert led.evaluate(t0 + 60 * minute, ()) == [], minute
    led.census_tick(t0 + 900, 1, 0, False)
    assert [e.kind for e in led.evaluate(t0 + 900, ())] == ["anchor"]

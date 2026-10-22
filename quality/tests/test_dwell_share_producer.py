"""Hourly dwell_share producer (PREDICT-MODEL-DWELL-MIGRATION-1, plan D3).

I1: every row's predicted value is the share frozen at the first tick inside
the hour, from a model whose trained_until_utc <= start(H); no row when that
capture did not happen or the hour has too few samples. I2: at most one row
per (room, hour), one batch per tick, nothing while the flag is off.

Oracles are hand-stated shares / fractions; boundaries use literals. Ticks are
driven through ``_dwell_tick`` (raises) or through the callback the runner
actually registered with ``async_track_time_change`` (wire-in anchor).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from occ_dwell_helpers import default_tz, fetch, make_real_db, real_package, seed

from custom_components.universal_room_automation.const import DOMAIN

UTC = timezone.utc
CHI = "America/Chicago"


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    import importlib

    global dt_util, rdm, const
    with real_package():
        dt_util = importlib.import_module("homeassistant.util.dt")
        rdm = importlib.import_module(
            "custom_components.universal_room_automation.room_dwell_model")
        const = importlib.import_module(
            "custom_components.universal_room_automation.const")
        yield


@pytest.fixture(autouse=True)
def _utc_tz():
    with default_tz("UTC"):
        yield


class _DB:
    def __init__(self, actual=None):
        # {(since, until): [(room_id, bucket, occ, n), ...]}
        self.actual = actual or {}
        self.reads: list[tuple[str, str]] = []
        self.batches: list[list[tuple]] = []

    async def get_room_occupied_share_by_hour(self, since, until):
        self.reads.append((since, until))
        return list(self.actual.get((since, until), []))

    async def save_prediction_results_batch(self, rows):
        self.batches.append(list(rows))

    @property
    def rows(self):
        return [r for b in self.batches for r in b]


def _entry(eid, kind="room"):
    return SimpleNamespace(entry_id=eid, data={"entry_type": kind})


def _hass(db, entries=None):
    entries = entries if entries is not None else [
        _entry("E1"), _entry("E2"), _entry("ZM", "zone_manager")]
    return SimpleNamespace(
        data={DOMAIN: {"database": db}},
        config_entries=SimpleNamespace(async_entries=lambda _d: entries),
    )


def _model(rows, trained_until, tz=UTC):
    m = rdm.RoomDwellModel()
    m.apply(rdm.RoomDwellModel.build(rows, tz),
            now_utc=datetime(2026, 10, 21, 3, 40, tzinfo=UTC),
            window_days=56, trained_until_utc=trained_until)
    return m


# Wednesday 2026-10-14 cells (same weekday as 2026-10-21):
#   E1 10:00 -> 3/12 = 0.25, E2 10:00 -> 6/12 = 0.5, E1 11:00 -> 12/12 = 1.0
_CELLS = [("E1", "2026-10-14T10", 3, 12), ("E2", "2026-10-14T10", 6, 12),
          ("E1", "2026-10-14T11", 12, 12)]
_TRAINED = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)
_W10 = ("2026-10-21T10:00:00", "2026-10-21T11:00:00")


def _runner(db, model, entries=None):
    r = rdm.RoomDwellModelRunner(_hass(db, entries))
    r.model = model
    return r


async def _tick(runner, at: datetime):
    with patch.object(dt_util, "utcnow", return_value=at):
        await runner._dwell_tick()


def _at(h, m=2, day=21, month=10, year=2026):
    return datetime(year, month, day, h, m, tzinfo=UTC)


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scores_previous_hour_with_frozen_value():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12),
                     ("E2", "2026-10-21T10", 0, 12)]})
    r = _runner(db, _model(_CELLS, _TRAINED))
    await _tick(r, _at(10))
    assert db.reads == [] and db.batches == []        # nothing to score yet
    await _tick(r, _at(11))
    assert db.reads == [_W10]
    assert len(db.batches) == 1
    assert sorted(db.rows) == [
        ("E1", "2026-10-21T10:00:00+00:00", "dwell_share", "0.25", 12,
         "0.75", -0.5),
        ("E2", "2026-10-21T10:00:00+00:00", "dwell_share", "0.5", 12,
         "0.0", 0.5),
    ]
    # D2 persistence input
    assert r.last_hour_fraction("E1") == pytest.approx(0.75)
    assert r.last_hour_fraction("E2") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_registered_callback_scores(monkeypatch):
    """Wire-in anchor: the callback async_start registers is the producer."""
    from homeassistant.helpers import event as ha_event

    calls = []

    def _tc(_hass, cb, **kw):
        calls.append((cb, kw))
        return MagicMock()

    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    hass = _hass(db, [_entry("E1")])
    with patch.object(ha_event, "async_track_time_change", _tc), \
            patch.object(ha_event, "async_call_later", MagicMock()):
        runner = await rdm.async_setup_room_dwell_model(hass)
    runner.model = _model(_CELLS, _TRAINED)
    tick_cb = [cb for cb, kw in calls if kw == {"minute": 2, "second": 0}]
    assert len(tick_cb) == 1
    for at in (_at(10), _at(11)):
        with patch.object(dt_util, "utcnow", return_value=at):
            await tick_cb[0](at)
    assert [row[:4] for row in db.rows] == [
        ("E1", "2026-10-21T10:00:00+00:00", "dwell_share", "0.25")]
    await runner.async_stop()


@pytest.mark.asyncio
async def test_no_row_when_model_trained_past_hour_start():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    # trained 1 s past the hour start: in-sample, must not freeze
    r = _runner(db, _model(_CELLS, datetime(2026, 10, 21, 10, 0, 1, tzinfo=UTC)))
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    assert db.rows == [] and db.reads == []
    assert r.skipped_freeze >= 1


@pytest.mark.asyncio
async def test_trained_exactly_at_hour_start_freezes():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    r = _runner(db, _model(_CELLS, datetime(2026, 10, 21, 10, 0, tzinfo=UTC)))
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    assert [row[0] for row in db.rows] == ["E1"]


@pytest.mark.asyncio
async def test_no_freeze_without_trained_until():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    r = _runner(db, _model(_CELLS, None))
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    assert db.rows == [] and r.skipped_freeze >= 1


@pytest.mark.asyncio
async def test_no_freeze_before_first_refresh():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    m = rdm.RoomDwellModel()             # never refreshed
    m.trained_until_utc = _TRAINED       # isolate the has_model conjunct
    m._cells = {"E1": {(10, "weekday"): [3, 12]}}
    r = _runner(db, m)
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    assert db.rows == [] and r.skipped_freeze >= 1


@pytest.mark.asyncio
async def test_refresh_mid_hour_keeps_frozen():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    r = _runner(db, _model(_CELLS, _TRAINED), [_entry("E1")])
    await _tick(r, _at(10))
    # A refresh during H changes the cell to 1.0 ...
    r.model = _model([("E1", "2026-10-14T10", 12, 12)], _TRAINED)
    # ... and a second tick inside H (clock adjustment) must not re-freeze.
    await _tick(r, _at(10, 2))
    await _tick(r, _at(11))
    assert [row[3] for row in db.rows] == ["0.25"]


@pytest.mark.asyncio
async def test_same_tick_twice_one_row():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    r = _runner(db, _model(_CELLS, _TRAINED), [_entry("E1")])
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    await _tick(r, _at(11))
    assert len(db.batches) == 1 and len(db.rows) == 1


@pytest.mark.asyncio
async def test_clock_back_refreeze_does_not_double_score():
    """Clock moves back into H after H was scored: H is re-frozen by the
    10:02 re-fire, but the same-hour guard stops a second row for H."""
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    r = _runner(db, _model(_CELLS, _TRAINED), [_entry("E1")])
    for at in (_at(10), _at(11), _at(10), _at(11)):
        await _tick(r, at)
    stamps = [row[1] for row in db.rows]
    assert stamps.count("2026-10-21T10:00:00+00:00") == 1


@pytest.mark.asyncio
async def test_stopped_runner_callback_writes_nothing():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12)]})
    r = _runner(db, _model(_CELLS, _TRAINED), [_entry("E1")])
    await _tick(r, _at(10))
    await r.async_stop()
    with patch.object(dt_util, "utcnow", return_value=_at(11)):
        await r._async_dwell_tick(_at(11))
    assert db.rows == [] and db.reads == []
    # a new runner scores once after its own freeze
    r2 = _runner(db, _model(_CELLS, _TRAINED), [_entry("E1")])
    await _tick(r2, _at(10))
    await _tick(r2, _at(11))
    assert len(db.rows) == 1


@pytest.mark.asyncio
async def test_fall_back_hour_two_rows_distinct_utc():
    with default_tz(CHI) as tz:
        # Sunday 2026-10-25 01:00 CDT = 06Z: cell (1, weekend) share 0.5
        cells = [("E1", "2026-10-25T06", 6, 12)]
        trained = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
        w6 = ("2026-11-01T06:00:00", "2026-11-01T07:00:00")
        w7 = ("2026-11-01T07:00:00", "2026-11-01T08:00:00")
        db = _DB({w6: [("E1", "2026-11-01T06", 12, 12)],
                  w7: [("E1", "2026-11-01T07", 0, 12)]})
        r = _runner(db, _model(cells, trained, tz), [_entry("E1")])
        for h in (6, 7, 8):
            await _tick(r, _at(h, day=1, month=11))
    assert [(row[1], row[3], row[5]) for row in db.rows] == [
        ("2026-11-01T06:00:00+00:00", "0.5", "1.0"),
        ("2026-11-01T07:00:00+00:00", "0.5", "0.0"),
    ]


@pytest.mark.asyncio
async def test_spring_forward_no_gap_error():
    with default_tz(CHI) as tz:
        # 2027-03-14 (Sunday): 07Z = 01:00 CST, 08Z = 03:00 CDT
        cells = [("E1", "2027-03-07T07", 3, 12),    # Sun 01:00 CST -> 0.25
                 ("E1", "2027-03-07T09", 9, 12)]    # Sun 03:00 CST -> 0.75
        trained = datetime(2027, 3, 14, 6, 0, tzinfo=UTC)
        w7 = ("2027-03-14T07:00:00", "2027-03-14T08:00:00")
        w8 = ("2027-03-14T08:00:00", "2027-03-14T09:00:00")
        db = _DB({w7: [("E1", "2027-03-14T07", 0, 12)],
                  w8: [("E1", "2027-03-14T08", 12, 12)]})
        r = _runner(db, _model(cells, trained, tz), [_entry("E1")])
        for h in (7, 8, 9):
            await _tick(r, _at(h, day=14, month=3, year=2027))
    assert [(row[1], row[3]) for row in db.rows] == [
        ("2027-03-14T07:00:00+00:00", "0.25"),
        ("2027-03-14T08:00:00+00:00", "0.75"),
    ]


@pytest.mark.parametrize("value,expected", [(14, 14), (0, 0), (15, 2), (-1, 2)])
def test_tick_minute_out_of_range_clamped(value, expected, caplog):
    regs = []
    r = rdm.RoomDwellModelRunner(_hass(_DB()))
    with patch.object(const, "DWELL_SHARE_TICK_MINUTE", value):
        r._register_dwell_tick(lambda _h, _cb, **kw: regs.append(kw) or MagicMock())
    assert regs == [{"minute": expected, "second": 0}]
    warned = any("DWELL_SHARE_TICK_MINUTE" in m for m in caplog.messages)
    assert warned is (value != expected)


@pytest.mark.asyncio
async def test_min_samples_gate():
    db = _DB({_W10: [("E1", "2026-10-21T10", 5, 5),
                     ("E2", "2026-10-21T10", 6, 6)]})
    r = _runner(db, _model(_CELLS, _TRAINED))
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    assert [row[0] for row in db.rows] == ["E2"]
    assert r.last_hour_fraction("E1") is None


@pytest.mark.asyncio
async def test_row_shape():
    db = _DB({_W10: [("E1", "2026-10-21T10", 4, 12)]})
    r = _runner(db, _model(_CELLS, _TRAINED), [_entry("E1")])
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    (row,) = db.rows
    room_id, ts, ptype, pred, conf, actual, err = row
    assert room_id == "E1"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:00:00\+00:00", ts)
    assert ptype == "dwell_share"
    assert (pred, actual) == ("0.25", "0.3333")
    assert conf == 12                       # cell sample count, not 0-1
    assert err == pytest.approx(-0.0833)    # signed expected - actual


@pytest.mark.asyncio
async def test_flag_off_no_tick():
    from homeassistant.helpers import event as ha_event

    tc = MagicMock()
    with patch.object(const, "DWELL_SHARE_PRODUCER_ENABLED", False), \
            patch.object(ha_event, "async_track_time_change", tc), \
            patch.object(ha_event, "async_call_later", MagicMock()):
        runner = await rdm.async_setup_room_dwell_model(_hass(_DB()))
    assert [c.kwargs for c in tc.call_args_list] == [
        {"hour": 3, "minute": 40, "second": 0}]
    assert runner._unsub_dwell_tick is None


@pytest.mark.asyncio
async def test_unsub_on_stop():
    unsub = MagicMock()
    r = rdm.RoomDwellModelRunner(_hass(_DB()))
    r._register_dwell_tick(lambda _h, _cb, **kw: unsub)
    await r.async_stop()
    unsub.assert_called_once_with()
    assert r._unsub_dwell_tick is None


@pytest.mark.asyncio
async def test_room_set_is_room_entries_only():
    db = _DB({_W10: [("E1", "2026-10-21T10", 9, 12),
                     ("ZM", "2026-10-21T10", 9, 12)]})
    cells = _CELLS + [("ZM", "2026-10-14T10", 6, 12)]
    r = _runner(db, _model(cells, _TRAINED),
                [_entry("E1"), _entry("ZM", "zone_manager")])
    await _tick(r, _at(10))
    await _tick(r, _at(11))
    assert [row[0] for row in db.rows] == ["E1"]


@pytest.mark.asyncio
async def test_dao_against_production_schema(tmp_path):
    """Real DB (database.py DDL), real DAO read, real batch writer."""
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, "INSERT INTO environmental_data (room_id, timestamp, occupied) "
             "VALUES (?, ?, ?)",
         [("E1", f"2026-10-21T10:{m:02d}:01.000000", 1 if m < 30 else 0)
          for m in range(0, 60, 5)]
         + [("E1", "2026-10-21T11:00:01.000000", 1)])  # next hour: excluded
    r = _runner(db, _model(_CELLS, _TRAINED), [_entry("E1")])
    await db.start_write_worker()
    try:
        await _tick(r, _at(10))
        await _tick(r, _at(11))
    finally:
        await db.stop_write_worker()
    got = fetch(db, "SELECT room_id, prediction_timestamp, prediction_type, "
                    "predicted_value, confidence, actual_value, error_value, "
                    "person_id FROM prediction_results")
    assert got == [("E1", "2026-10-21T10:00:00+00:00", "dwell_share", "0.25",
                    12.0, "0.5", -0.25, None)]

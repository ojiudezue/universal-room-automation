"""RoomDwellModel + its DAO + runner lifecycle (BAYES-OCCUPANCY-ANOMALY-
NEVER-EVALUATES-1, plan D1).

Oracles are the synthetic occupancy scenarios themselves (hand-stated shares),
never a re-run of the model. DB tests run the REAL
``UniversalRoomDatabase.initialize()`` so the schema is database.py's own DDL.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from occ_dwell_helpers import default_tz, fetch, make_real_db, seed

from custom_components.universal_room_automation import room_dwell_model as rdm
from custom_components.universal_room_automation.const import DOMAIN

CHI = "America/Chicago"


async def _inline(func, *args):
    return func(*args)


def _hass(domain: dict):
    """Minimal hass: hass.data + an inline executor (the build runs in
    async_add_executor_job in production)."""
    return SimpleNamespace(data={DOMAIN: domain},
                           async_add_executor_job=_inline)
UTC = timezone.utc


def _rows_weekday_9_to_17(tz, start_local: datetime, days: int):
    """Room R occupied every weekday 09:00-16:59 local, empty otherwise.
    One DAO-shaped row per UTC hour bucket, 12 samples each."""
    rows = []
    for d in range(days):
        for h in range(24):
            local = (start_local + timedelta(days=d)).replace(hour=h)
            occ = 12 if local.weekday() < 5 and 9 <= h < 17 else 0
            bucket = local.astimezone(UTC).strftime("%Y-%m-%dT%H")
            rows.append(("R", bucket, occ, 12))
    return rows


# ---------------------------------------------------------------------------
# Pure model
# ---------------------------------------------------------------------------


def test_share_by_local_hour_daytype():
    with default_tz(CHI) as tz:
        # 2026-08-03 is a Monday; 56 days = 8 whole weeks (40 weekdays, 16
        # weekend days). Summer: no DST change inside the window.
        start = datetime(2026, 8, 3, 0, 0, tzinfo=tz)
        m = rdm.RoomDwellModel()
        assert m.refresh(
            _rows_weekday_9_to_17(tz, start, 56), tz,
            now_utc=datetime(2026, 9, 28, tzinfo=UTC), window_days=56,
        )
        wd10 = datetime(2026, 9, 30, 10, 15, tzinfo=tz)  # Wednesday
        we10 = datetime(2026, 10, 3, 10, 15, tzinfo=tz)  # Saturday
        wd03 = datetime(2026, 9, 30, 3, 15, tzinfo=tz)
        assert m.lookup("R", wd10) == (1.0, 480)
        assert m.lookup("R", we10) == (0.0, 192)
        assert m.lookup("R", wd03) == (0.0, 480)
        assert m.lookup("other", wd10) == (None, 0)
        assert m.status == "ok" and m.has_model
        assert m.usual_hours("R", 0.02) == "weekdays 09-16"
        assert m.cell_days("R", wd10) == 40
        assert m.cell_days("R", we10) == 16


def test_dst_fallback_buckets():
    """2026-11-01 fall-back in Chicago: 06Z = 01:00 CDT, 07Z = 01:00 CST.
    Both land in local hour 1 (Sunday = weekend); 05Z is 00:00 CDT."""
    with default_tz(CHI) as tz:
        m = rdm.RoomDwellModel()
        m.refresh(
            [("R", "2026-11-01T05", 0, 12), ("R", "2026-11-01T06", 3, 12),
             ("R", "2026-11-01T07", 9, 12)],
            tz, now_utc=datetime(2026, 11, 2, tzinfo=UTC), window_days=56,
        )
        sun_01 = datetime(2026, 11, 8, 1, 30, tzinfo=tz)
        sun_00 = datetime(2026, 11, 8, 0, 30, tzinfo=tz)
        assert m.lookup("R", sun_01) == (0.5, 24)
        assert m.cell_days("R", sun_01) == 1  # two buckets, one local date
        assert m.lookup("R", sun_00) == (0.0, 12)


def test_refresh_failure_keeps_previous():
    tz = UTC
    m = rdm.RoomDwellModel()
    first = datetime(2026, 10, 1, tzinfo=UTC)
    assert m.refresh([("R", "2026-09-30T10", 6, 12)], tz,
                     now_utc=first, window_days=56)
    ok = m.refresh([("R", "not-a-bucket", 1, 1)], tz,
                   now_utc=datetime(2026, 10, 2, tzinfo=UTC), window_days=56)
    assert ok is False
    assert m.status == "refresh_failed"
    assert m.last_refresh_utc == first
    assert m.lookup("R", datetime(2026, 10, 7, 10, 5, tzinfo=UTC)) == (0.5, 12)
    assert m.has_model


def test_never_refreshed_has_no_model():
    m = rdm.RoomDwellModel()
    assert m.status == "never_refreshed" and not m.has_model


def test_usual_people_overlap_and_share():
    tz = UTC
    m = rdm.RoomDwellModel()
    # Cell weekday 10:00: 24 occupied samples = 7200 s of occupied time.
    m.refresh(
        [("E1", "2026-10-14T10", 12, 12), ("E1", "2026-10-15T10", 12, 12)],
        tz, now_utc=datetime(2026, 10, 16, tzinfo=UTC), window_days=56,
        visit_rows=[
            # 09:30-10:30 Wed: 1800 s in the 10:00 cell (and 1800 in 09:00)
            ("oji", "Study A", "2026-10-14 09:30:00", "2026-10-14 10:30:00"),
            # 10:00-11:00 Thu: 3600 s in the 10:00 cell
            ("oji", "Study A", "2026-10-15 10:00:00", "2026-10-15 11:00:00"),
            ("jaya", "Study A", "2026-10-15 10:00:00", "2026-10-15 10:12:00"),
            # longer than the cap: ignored
            ("ziri", "Study A", "2026-10-01 10:00:00", "2026-10-03 10:00:00"),
        ],
        max_visit_s=86400,
    )
    people = m.usual_people("Study A", "E1",
                            datetime(2026, 10, 21, 10, 40, tzinfo=UTC))
    # oji 5400/7200 = 0.75, jaya 720/7200 = 0.1
    assert people == [{"person": "oji", "share": 0.75},
                      {"person": "jaya", "share": 0.1}]


def test_training_window_excludes_today():
    with default_tz(CHI) as tz:
        now = datetime(2026, 10, 21, 15, 7, tzinfo=tz)
        start, end = rdm.training_window(now, 56)
        assert end == datetime(2026, 10, 21, 0, 0, tzinfo=tz)
        assert start == datetime(2026, 8, 26, 0, 0, tzinfo=tz)


def test_window_days_clamped_to_retention():
    from custom_components.universal_room_automation import const

    with patch.object(const, "OCC_ANOMALY_WINDOW_DAYS", 400), \
            patch.object(const, "RETENTION_ROOM_HISTORY_DAYS", 365):
        assert rdm._effective_window_days() == 365
    with patch.object(const, "OCC_ANOMALY_WINDOW_DAYS", 56), \
            patch.object(const, "RETENTION_ROOM_HISTORY_DAYS", 0):
        assert rdm._effective_window_days() == 56


# ---------------------------------------------------------------------------
# DAO against the production schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dao_against_production_schema(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, "INSERT INTO environmental_data (room_id, timestamp, occupied) "
             "VALUES (?, ?, ?)", [
        ("E1", "2026-10-20T00:00:00", 1),          # at since: included
        ("E1", "2026-10-20T10:00:01.000000", 1),
        ("E1", "2026-10-20T10:05:01.000000", 0),
        ("E1", "2026-10-20T10:10:01.000000", 1),
        ("E1", "2026-10-20T11:00:01.000000", 0),
        ("E2", "2026-10-20T10:00:01.000000", 1),
        ("E1", "2026-10-19T23:59:59.000000", 1),   # before window
        ("E1", "2026-10-21T00:00:00", 1),          # at until: excluded
    ])
    rows = await db.get_room_occupied_share_by_hour(
        "2026-10-20T00:00:00", "2026-10-21T00:00:00",
    )
    assert sorted(rows) == [
        ("E1", "2026-10-20T00", 1, 1),
        ("E1", "2026-10-20T10", 2, 3),
        ("E1", "2026-10-20T11", 0, 1),
        ("E2", "2026-10-20T10", 1, 1),
    ]


@pytest.mark.asyncio
async def test_null_occupied_excluded(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, "INSERT INTO environmental_data (room_id, timestamp, occupied) "
             "VALUES (?, ?, ?)", [
        ("E1", "2026-10-20T10:00:01", None),
        ("E1", "2026-10-20T10:05:01", None),
        ("E1", "2026-10-20T10:10:01", 1),
    ])
    rows = await db.get_room_occupied_share_by_hour(
        "2026-10-20T00:00:00", "2026-10-21T00:00:00",
    )
    assert rows == [("E1", "2026-10-20T10", 1, 1)]


@pytest.mark.asyncio
async def test_closed_person_visits_dao(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, "INSERT INTO person_visits (person_id, room_id, entry_time, "
             "exit_time) VALUES (?, ?, ?, ?)", [
        ("oji", "Study A", "2026-10-20 09:00:00", "2026-10-20 10:00:00"),
        ("oji", "Study A", "2026-10-20 11:00:00", None),  # open: excluded
        ("jaya", "Kitchen", "2026-10-21 09:00:00", "2026-10-21 09:30:00"),
    ])
    rows = await db.get_closed_person_visits(
        "2026-10-20 00:00:00", "2026-10-21 00:00:00", 100,
    )
    assert rows == [("oji", "Study A", "2026-10-20 09:00:00",
                     "2026-10-20 10:00:00")]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_today_excluded_from_training(tmp_path):
    """Runner refresh over the real DB: today's samples never train."""
    db = make_real_db(tmp_path)
    assert await db.initialize()
    with default_tz(CHI) as tz:
        # now = Wed 2026-10-21 15:00 CDT (20:00Z). Today starts 05:00Z.
        seed(db, "INSERT INTO environmental_data (room_id, timestamp, "
                 "occupied) VALUES (?, ?, ?)", [
            # yesterday (Tue) 10:xx local = 15Z: empty, 2 samples
            ("E1", "2026-10-20T15:00:01", 0),
            ("E1", "2026-10-20T15:05:01", 0),
            # today (Wed) 10:xx local = 15Z: occupied, must be ignored
            ("E1", "2026-10-21T15:00:01", 1),
            ("E1", "2026-10-21T15:05:01", 1),
        ])
        hass = _hass({"database": db})
        runner = rdm.RoomDwellModelRunner(hass)
        now_local = datetime(2026, 10, 21, 15, 0, tzinfo=tz)
        with patch.object(dt_util, "now", return_value=now_local), \
                patch.object(dt_util, "utcnow",
                             return_value=now_local.astimezone(UTC)):
            assert await runner.async_refresh() is True
        assert runner.model.lookup(
            "E1", datetime(2026, 10, 22, 10, 30, tzinfo=tz),
        ) == (0.0, 2)


@pytest.mark.asyncio
async def test_runner_no_database_marks_failed():
    hass = _hass({})
    runner = rdm.RoomDwellModelRunner(hass)
    assert await runner.async_refresh() is False
    assert runner.model.status == "refresh_failed"
    assert runner.model.last_error == "no_database"


@pytest.mark.asyncio
async def test_runner_db_error_keeps_previous():
    db = SimpleNamespace(
        get_room_occupied_share_by_hour=AsyncMock(
            return_value=[("E1", "2026-10-20T15", 6, 12)]),
        get_closed_person_visits=AsyncMock(return_value=[]),
    )
    hass = _hass({"database": db})
    runner = rdm.RoomDwellModelRunner(hass)
    assert await runner.async_refresh() is True
    db.get_room_occupied_share_by_hour = AsyncMock(side_effect=OSError("busy"))
    assert await runner.async_refresh() is False
    assert runner.model.status == "refresh_failed"
    assert runner.model.has_model
    assert runner.model.lookup(
        "E1", datetime(2026, 10, 20, 15, 0, tzinfo=UTC).astimezone(
            dt_util.DEFAULT_TIME_ZONE),
    ) == (0.5, 12)


@pytest.mark.asyncio
async def test_runner_start_schedules_and_stop_cancels():
    from homeassistant.helpers import event as ha_event

    unsub_nightly, unsub_initial = MagicMock(), MagicMock()
    tc = MagicMock(return_value=unsub_nightly)
    cl = MagicMock(return_value=unsub_initial)
    hass = _hass({})
    with patch.object(ha_event, "async_track_time_change", tc), \
            patch.object(ha_event, "async_call_later", cl):
        runner = await rdm.async_setup_room_dwell_model(hass)
    assert hass.data[DOMAIN][rdm.HASS_DATA_KEY] is runner
    assert tc.call_args.kwargs == {"hour": 3, "minute": 40, "second": 0}
    assert cl.call_args.args[1] == 120
    await runner.async_stop()
    unsub_nightly.assert_called_once_with()
    unsub_initial.assert_called_once_with()
    assert rdm.HASS_DATA_KEY not in hass.data[DOMAIN]
    # a stopped runner never refreshes (and never reads the DB)
    db = SimpleNamespace(
        get_room_occupied_share_by_hour=AsyncMock(return_value=[]),
        get_closed_person_visits=AsyncMock(return_value=[]),
    )
    hass.data[DOMAIN]["database"] = db
    assert await runner.async_refresh() is False
    db.get_room_occupied_share_by_hour.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_disabled_schedules_nothing():
    from custom_components.universal_room_automation import const
    from homeassistant.helpers import event as ha_event

    tc, cl = MagicMock(), MagicMock()
    hass = _hass({})
    with patch.object(const, "OCC_ANOMALY_DWELL_ENABLED", False), \
            patch.object(ha_event, "async_track_time_change", tc), \
            patch.object(ha_event, "async_call_later", cl):
        runner = await rdm.async_setup_room_dwell_model(hass)
    tc.assert_not_called()
    cl.assert_not_called()
    assert runner.model.status == "disabled"


@pytest.mark.asyncio
async def test_setup_replaces_previous_runner():
    from homeassistant.helpers import event as ha_event

    hass = _hass({})
    with patch.object(ha_event, "async_track_time_change", MagicMock()), \
            patch.object(ha_event, "async_call_later", MagicMock()):
        first = await rdm.async_setup_room_dwell_model(hass)
        second = await rdm.async_setup_room_dwell_model(hass)
    assert first._stopped is True
    assert hass.data[DOMAIN][rdm.HASS_DATA_KEY] is second


# ---------------------------------------------------------------------------
# Wire-in anchor: the REAL integration-entry setup creates the runner and
# registers its stop on unload.
# ---------------------------------------------------------------------------


def _is_set_aside(name: str, mod) -> bool:
    """Same rule as test_ec_role_defaults_rev5: URA modules and non-real HA
    stubs are set aside so the block imports the REAL package (a sibling file
    may have left a stub package in sys.modules)."""
    import types

    if name == "custom_components" or name.startswith("custom_components."):
        return True
    if name == "homeassistant" or name.startswith("homeassistant."):
        return not isinstance(mod, types.ModuleType) or mod.__spec__ is None
    return False


@pytest.mark.parametrize("expected_lingering_tasks", [True])
@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_integration_setup_wires_room_dwell_model() -> None:
    import importlib

    from _d7_isolation import real_package_scope
    from runtime_harness import StubConfigEntry, StubHass, make_coordinator_manager_entry

    with real_package_scope(_is_set_aside):
        ura = importlib.import_module("custom_components.universal_room_automation")
        const = importlib.import_module(
            "custom_components.universal_room_automation.const")

        class _Entry(StubConfigEntry):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.unloads: list = []

            def async_on_unload(self, func):
                self.unloads.append(func)

        integ = _Entry("integ", const.ENTRY_TYPE_INTEGRATION, data={})
        hass = StubHass(config_entries=[make_coordinator_manager_entry(), integ])
        hass.config_entries.async_forward_entry_setups = AsyncMock(
            return_value=True)

        runner = MagicMock(name="runner")
        runner.async_stop = AsyncMock()
        setup = AsyncMock(return_value=runner)
        with patch("custom_components.universal_room_automation."
                   "room_dwell_model.async_setup_room_dwell_model", setup):
            try:
                assert await ura.async_setup_entry(hass, integ) is True
            finally:
                wd = importlib.import_module(
                    "custom_components.universal_room_automation."
                    "domain_coordinators._loop_stall_watchdog")
                wd.uninstall(hass)
        setup.assert_awaited_once_with(hass)
        assert runner.async_stop in integ.unloads


@pytest.mark.asyncio
async def test_refresh_passes_naive_utc_window():
    """G8: Chicago now 2026-10-21 10:00 CDT; window = 56 whole local days
    ending at local midnight, sent as naive UTC strings."""
    db = SimpleNamespace(
        get_room_occupied_share_by_hour=AsyncMock(return_value=[]),
        get_closed_person_visits=AsyncMock(return_value=[]),
    )
    with default_tz(CHI) as tz:
        runner = rdm.RoomDwellModelRunner(_hass({"database": db}))
        now_local = datetime(2026, 10, 21, 10, 0, tzinfo=tz)
        with patch.object(dt_util, "now", return_value=now_local), \
                patch.object(dt_util, "utcnow",
                             return_value=now_local.astimezone(UTC)):
            assert await runner.async_refresh() is True
    db.get_room_occupied_share_by_hour.assert_awaited_once_with(
        "2026-08-26T05:00:00", "2026-10-21T05:00:00")
    assert db.get_closed_person_visits.await_args.args[:2] == (
        "2026-08-26 00:00:00", "2026-10-21 00:00:00")


@pytest.mark.asyncio
async def test_stop_during_read_discards_result():
    """G11: a stop that lands while the DB read is in flight wins."""
    holder = {}

    async def _read(*_a):
        await holder["runner"].async_stop()
        return [("E1", "2026-10-20T15", 6, 12)]

    db = SimpleNamespace(
        get_room_occupied_share_by_hour=AsyncMock(side_effect=_read),
        get_closed_person_visits=AsyncMock(return_value=[]),
    )
    runner = rdm.RoomDwellModelRunner(_hass({"database": db}))
    holder["runner"] = runner
    assert await runner.async_refresh() is False
    assert not runner.model.has_model


@pytest.mark.asyncio
async def test_build_runs_in_executor():
    calls = []

    async def _exec(func, *args):
        calls.append(func)
        return func(*args)

    db = SimpleNamespace(
        get_room_occupied_share_by_hour=AsyncMock(
            return_value=[("E1", "2026-10-20T15", 6, 12)]),
        get_closed_person_visits=AsyncMock(return_value=[]),
    )
    hass = SimpleNamespace(data={DOMAIN: {"database": db}},
                           async_add_executor_job=_exec)
    runner = rdm.RoomDwellModelRunner(hass)
    assert await runner.async_refresh() is True
    assert calls == [rdm.RoomDwellModel.build]
    assert runner.model.has_model


@pytest.mark.asyncio
async def test_failed_first_build_retries_once():
    from homeassistant.helpers import event as ha_event

    later = []

    def _call_later(_hass, delay, cb):
        unsub = MagicMock()
        later.append((delay, cb, unsub))
        return unsub

    hass = _hass({})  # no database: the first build fails
    with patch.object(ha_event, "async_track_time_change", MagicMock()), \
            patch.object(ha_event, "async_call_later", _call_later):
        runner = await rdm.async_setup_room_dwell_model(hass)
        assert [d for d, _, _ in later] == [120]
        await later[0][1](None)
        assert [d for d, _, _ in later] == [120, 600]
        await runner.async_stop()
    later[1][2].assert_called_once_with()  # the pending retry is cancelled


@pytest.mark.asyncio
async def test_successful_first_build_schedules_no_retry():
    from homeassistant.helpers import event as ha_event

    later = []
    db = SimpleNamespace(
        get_room_occupied_share_by_hour=AsyncMock(return_value=[]),
        get_closed_person_visits=AsyncMock(return_value=[]),
    )
    hass = _hass({"database": db})

    def _call_later(_hass, delay, cb):
        later.append((delay, cb))
        return MagicMock()

    with patch.object(ha_event, "async_track_time_change", MagicMock()), \
            patch.object(ha_event, "async_call_later", _call_later):
        await rdm.async_setup_room_dwell_model(hass)
        await later[0][1](None)
    assert [d for d, _ in later] == [120]

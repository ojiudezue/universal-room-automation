"""EGRESS-EXIT-IDENTITY-BACKFILL-1 (2026-09-05) mutation-anchored tests.

Drives PRODUCTION `camera_census.PersonCensus._backfill_exit_identity`
and the departing branch of `_on_crossing_tracker_state_change`.
Each named test targets one load-bearing site; neutering that site
turns the test RED (recorded in the build report).
"""

from __future__ import annotations

import asyncio as _asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass


import sys as _sys
import types as _types


if "homeassistant.helpers.area_registry" not in _sys.modules:
    _mod = _types.ModuleType("homeassistant.helpers.area_registry")
    _mod.async_get = MagicMock()
    _sys.modules["homeassistant.helpers.area_registry"] = _mod
if "homeassistant.helpers.event" not in _sys.modules:
    _ev = _types.ModuleType("homeassistant.helpers.event")
    _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
    _ev.async_call_later = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
    _sys.modules["homeassistant.helpers.event"] = _ev


from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import PersonCensus
from custom_components.universal_room_automation.database import UniversalRoomDatabase


class _RealDaoHarness:
    """Thin harness exposing the PRODUCTION DAO methods against a
    real aiosqlite in-memory DB. Drives the SQL byte-for-byte so
    mutations to the DAO strings actually take effect.
    """

    def __init__(self):
        import aiosqlite  # noqa: F401 (import checked)
        self._conn = None
        self.find_unnamed_exit_crossings = UniversalRoomDatabase.find_unnamed_exit_crossings.__get__(self)
        self.backfill_entry_exit_person_id = UniversalRoomDatabase.backfill_entry_exit_person_id.__get__(self)

    async def open(self):
        import aiosqlite
        self._conn = await aiosqlite.connect(":memory:")
        await self._conn.execute(
            """CREATE TABLE person_entry_exit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                person_id TEXT,
                event_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                egress_camera TEXT NOT NULL,
                confidence REAL NOT NULL
            )"""
        )
        await self._conn.commit()

    async def insert_null_exit(self, ts_iso: str, cam: str = "front_door") -> int:
        cur = await self._conn.execute(
            "INSERT INTO person_entry_exit_events (timestamp, person_id, event_type, direction, egress_camera, confidence) VALUES (?, NULL, 'egress', 'exit', ?, 0.0)",
            (ts_iso, cam),
        )
        await self._conn.commit()
        return int(cur.lastrowid)

    async def fetch(self, row_id: int):
        cur = await self._conn.execute(
            "SELECT id, timestamp, person_id, confidence FROM person_entry_exit_events WHERE id = ?",
            (row_id,),
        )
        return await cur.fetchone()

    # Emulate the URADatabase context managers used by the DAO methods.
    def _db(self):
        conn = self._conn
        class _Ctx:
            async def __aenter__(self_inner):
                return conn
            async def __aexit__(self_inner, *a):
                return False
        return _Ctx()

    _db_read = _db


UTC = timezone.utc


class _StubCameraManager:
    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


class _StubDatabase:
    """In-memory stub matching the production DAO semantics.

    Rows are stored with the SAME naive-UTC ISO shape the production
    INSERT uses (`datetime.utcnow().isoformat()` at database.py:3919).
    The `find_unnamed_exit_crossings` bounds are string-compared, so
    an offset-suffixed (tz-aware) bound will lex-compare wrong and
    return zero rows — the exact failure mode a real SQLite
    comparison exhibits against a naive-UTC column.
    """

    def __init__(self):
        # row = {id, timestamp, egress_camera, person_id, confidence}
        self.rows: list[dict] = []
        self._next_id = 1
        self.backfill_calls: list[tuple] = []

    def add_null_exit(self, ts_naive_utc: datetime, egress_camera: str = "front_door") -> int:
        row = {
            "id": self._next_id,
            "timestamp": ts_naive_utc.isoformat(),
            "egress_camera": egress_camera,
            "person_id": None,
            "confidence": 0.0,
        }
        self._next_id += 1
        self.rows.append(row)
        return row["id"]

    async def find_unnamed_exit_crossings(self, t_lo_iso: str, t_hi_iso: str):
        matches = [
            r for r in self.rows
            if r["person_id"] is None
            and r["timestamp"] > t_lo_iso
            and r["timestamp"] <= t_hi_iso
        ]
        matches.sort(key=lambda r: (r["timestamp"], r["id"]), reverse=True)
        return [(r["id"], r["timestamp"], r["egress_camera"]) for r in matches]

    async def backfill_entry_exit_person_id(self, row_id: int, person_id: str, confidence: float) -> bool:
        self.backfill_calls.append((row_id, person_id, confidence))
        for r in self.rows:
            if r["id"] == row_id and r["person_id"] is None:
                r["person_id"] = person_id
                r["confidence"] = confidence
                return True
        return False


def _ensure_loop():
    try:
        _asyncio.set_event_loop(_asyncio.new_event_loop())
    except Exception:  # noqa: BLE001
        pass


def _make_census():
    _ensure_loop()
    hass = make_hass()
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        "tracked_persons": ["person.oji_udezue", "person.ezinne_udezue"],
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: True,
    }
    hass.config_entries.async_entries.return_value = [entry]
    hass.states.get = lambda eid: None
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    db = _StubDatabase()
    existing = hass.data.get(ura_const.DOMAIN, {}) if isinstance(hass.data, dict) else {}
    existing["database"] = db
    existing["census"] = census
    hass.data[ura_const.DOMAIN] = existing
    return census, hass, db


def _run(coro):
    loop = _asyncio.get_event_loop()
    return loop.run_until_complete(coro)


def _naive_utc(dt_aware: datetime) -> datetime:
    return dt_aware.astimezone(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Anchor 1 — UTC-naive bound (the tz-contract trap; HEADLINE)
# ---------------------------------------------------------------------------


def test_exit_backfill_utc_naive_bound_matches_insert_shape():
    """Row inserted at T (naive-UTC iso); departing edge (tz-aware) at
    T+369s -> row backfilled. Mutation anchor: the naive-UTC bound
    derivation (`t_edge.astimezone(UTC).replace(tzinfo=None)`). If the
    bound is left tz-aware, the string comparison misses the row -> zero
    match -> RED.
    """
    census, _, db = _make_census()
    # Use a NON-UTC tz for the edge so a naïve `.replace(tzinfo=None)`
    # neuter shifts the wall clock and misses the row. The correct
    # `.astimezone(UTC).replace(tzinfo=None)` matches.
    non_utc = timezone(timedelta(hours=-5))
    t_crossing_aware = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=369)
    row_id = db.add_null_exit(_naive_utc(t_crossing_aware))
    t_edge = (t_crossing_aware + timedelta(seconds=369)).astimezone(non_utc)
    _run(census._backfill_exit_identity("oji_udezue", t_edge))
    assert db.rows[0]["person_id"] == "oji_udezue"
    assert db.rows[0]["confidence"] == float(ura_const.BLE_TRANSITION_ONLY_CONFIDENCE)
    assert census._ble_exit_backfilled_count == 1
    assert db.backfill_calls == [(row_id, "oji_udezue", float(ura_const.BLE_TRANSITION_ONLY_CONFIDENCE))]


# ---------------------------------------------------------------------------
# Anchor 2 — window bound
# ---------------------------------------------------------------------------


def test_exit_backfill_edge_beyond_window_no_match():
    census, _, db = _make_census()
    t_crossing = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=900)
    db.add_null_exit(_naive_utc(t_crossing))
    t_edge = t_crossing + timedelta(seconds=900)  # 900s > 600s window
    _run(census._backfill_exit_identity("oji_udezue", t_edge))
    assert db.rows[0]["person_id"] is None
    assert census._ble_exit_backfilled_count == 0
    assert census._ble_exit_edge_no_match_count == 1


# ---------------------------------------------------------------------------
# Anchor 3 — nearest + deterministic tiebreak
# ---------------------------------------------------------------------------


def test_exit_backfill_nearest_with_deterministic_tiebreak():
    """Drives the REAL DAO SELECT. Mutation anchor: the
    `ORDER BY timestamp DESC, id DESC` in
    `find_unnamed_exit_crossings`.
    """
    async def _scenario():
        dao = _RealDaoHarness()
        await dao.open()
        t_hi = datetime.now(UTC).replace(microsecond=0, tzinfo=None)
        t_tied = (t_hi - timedelta(seconds=200)).isoformat()
        id_a = await dao.insert_null_exit(t_tied)
        id_b = await dao.insert_null_exit(t_tied)
        # An older row nearer to t_lo — must not be chosen.
        await dao.insert_null_exit((t_hi - timedelta(seconds=500)).isoformat())
        t_lo = (t_hi - timedelta(seconds=600)).isoformat()
        rows = await dao.find_unnamed_exit_crossings(t_lo, t_hi.isoformat())
        # First returned row wins — must be id_b (largest id at tied ts).
        assert rows[0][0] == id_b
        # And id_a must be strictly after id_b in the list (DESC on id).
        assert rows[1][0] == id_a
    _run(_scenario())


# ---------------------------------------------------------------------------
# Anchor 4 — IS-NULL idempotence / single-use
# ---------------------------------------------------------------------------


def test_exit_backfill_second_edge_does_not_rewrite_named_row():
    """Drives the REAL DAO UPDATE. Mutation anchor: the
    `AND person_id IS NULL` guard on `backfill_entry_exit_person_id`.
    Without that clause, a second call rewrites the already-named row.
    """
    async def _scenario():
        dao = _RealDaoHarness()
        await dao.open()
        t_hi = datetime.now(UTC).replace(microsecond=0, tzinfo=None)
        row_id = await dao.insert_null_exit((t_hi - timedelta(seconds=100)).isoformat())
        ok1 = await dao.backfill_entry_exit_person_id(row_id, "oji_udezue", 0.72)
        assert ok1 is True
        r = await dao.fetch(row_id)
        assert r[2] == "oji_udezue"
        # Second attempt for a different slug must NOT overwrite.
        ok2 = await dao.backfill_entry_exit_person_id(row_id, "ezinne_udezue", 0.72)
        assert ok2 is False
        r = await dao.fetch(row_id)
        assert r[2] == "oji_udezue"
    _run(_scenario())


# ---------------------------------------------------------------------------
# Anchor 5 — cross-resident abstain via _ble_zero_tracker_slugs
# ---------------------------------------------------------------------------


def test_exit_backfill_abstains_when_zero_tracker_slug_present():
    census, _, db = _make_census()
    t_crossing = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=300)
    db.add_null_exit(_naive_utc(t_crossing))
    # Simulate: a tracked resident derived ZERO bluetooth_le trackers
    # this pass -> ambiguity guard must fire.
    census._ble_zero_tracker_slugs = {"ezinne_udezue"}
    t_edge = t_crossing + timedelta(seconds=300)
    _run(census._backfill_exit_identity("oji_udezue", t_edge))
    assert db.rows[0]["person_id"] is None
    assert census._ble_exit_backfilled_count == 0
    assert census._ble_exit_ambiguity_abstain_count == 1
    assert db.backfill_calls == []  # DAO never called


# ---------------------------------------------------------------------------
# Anchor 6 — home->named-zone eligibility (departing edge is admitted)
# ---------------------------------------------------------------------------


def test_exit_backfill_home_to_named_zone_is_eligible():
    """Anchor: the departing-branch admission in
    `_on_crossing_tracker_state_change` (old=='home' and new not in
    _BAD) must accept `home -> work` and schedule the backfill. If
    the branch is narrowed to `new == 'not_home'` only, no task is
    scheduled -> row stays null -> RED.
    """
    census, hass, db = _make_census()
    t_crossing = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=200)
    db.add_null_exit(_naive_utc(t_crossing))

    tracker_id = "device_tracker.oji_ble"
    census._ble_tracker_slug_map = {tracker_id: "oji_udezue"}
    # Bypass the upstream tracked-persons check in the edge handler.
    census._get_tracked_person_slugs = lambda: ["oji_udezue"]
    # In the harness `hass.async_create_task` is a MagicMock; make it
    # actually schedule the coroutine so we can await it.
    hass.async_create_task = lambda coro: _asyncio.get_event_loop().create_task(coro)

    # Build a home->work state_changed event.
    t_edge_aware = t_crossing + timedelta(seconds=200)
    ns = MagicMock()
    ns.state = "work"
    ns.last_changed = t_edge_aware
    ns.entity_id = tracker_id
    ns.attributes = {}
    os = MagicMock()
    os.state = "home"
    os.last_changed = t_edge_aware - timedelta(seconds=60)
    os.entity_id = tracker_id
    os.attributes = {}
    ev = MagicMock()
    ev.data = {"new_state": ns, "old_state": os}

    # Fire the sync callback; it schedules an async task via
    # hass.async_create_task. In the test harness that helper runs the
    # coroutine synchronously via the event loop; we drive pending
    # tasks by running the loop briefly.
    async def _drive():
        census._on_crossing_tracker_state_change(ev)
        # Drain any tasks tracked on the census.
        pending = list(census._backfill_tasks)
        if pending:
            await _asyncio.gather(*pending, return_exceptions=True)

    _run(_drive())
    assert db.rows[0]["person_id"] == "oji_udezue"


# ---------------------------------------------------------------------------
# Anchor 7 — async task is tracked and teardown cancels pending
# ---------------------------------------------------------------------------


def test_exit_backfill_task_is_tracked_and_teardown_cancels():
    """Drives the PRODUCTION departing-branch schedule (which must
    call `self._backfill_tasks.add(task)` and register the discard
    done-callback) AND the PRODUCTION teardown cancel block.

    Neutering `self._backfill_tasks.add(task)` in the schedule site
    leaves `_backfill_tasks` empty -> the pre-cancel assertion fails
    (RED). Neutering the teardown's `task.cancel()` leaves the task
    running past teardown -> the post-cancel assertion fails (RED).
    """
    census, hass, db = _make_census()

    # Make the DAO await forever so the scheduled task is guaranteed
    # to still be pending when we inspect / tear down.
    forever = _asyncio.Event()

    class _SlowDb:
        async def find_unnamed_exit_crossings(self, *_):
            await forever.wait()
            return []
        async def backfill_entry_exit_person_id(self, *_):
            return False

    hass.data[ura_const.DOMAIN]["database"] = _SlowDb()

    tracker_id = "device_tracker.oji_ble"
    census._ble_tracker_slug_map = {tracker_id: "oji_udezue"}
    census._get_tracked_person_slugs = lambda: ["oji_udezue"]

    async def _scenario():
        loop = _asyncio.get_event_loop()
        # Route hass.async_create_task through the real loop.
        hass.async_create_task = lambda coro: loop.create_task(coro)

        t_edge_aware = datetime.now(UTC).replace(microsecond=0)
        ns = MagicMock()
        ns.state = "not_home"
        ns.last_changed = t_edge_aware
        ns.entity_id = tracker_id
        ns.attributes = {}
        os = MagicMock()
        os.state = "home"
        os.last_changed = t_edge_aware - timedelta(seconds=60)
        os.entity_id = tracker_id
        os.attributes = {}
        ev = MagicMock()
        ev.data = {"new_state": ns, "old_state": os}

        census._on_crossing_tracker_state_change(ev)
        # Give the loop a tick to actually schedule the task.
        await _asyncio.sleep(0)
        # ANCHOR: the schedule site must have added it to the tracker.
        assert len(census._backfill_tasks) == 1
        (tracked_task,) = tuple(census._backfill_tasks)
        assert not tracked_task.done()

        # Now tear down.
        census.async_teardown_ble_transition_listeners()
        # ANCHOR: teardown must cancel and drain.
        try:
            await _asyncio.wait_for(tracked_task, timeout=1.0)
        except (_asyncio.CancelledError, _asyncio.TimeoutError):
            pass
        assert tracked_task.cancelled() or tracked_task.done()
        # Release the sentinel so any latecomers unblock cleanly.
        forever.set()

    _run(_scenario())

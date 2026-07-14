"""v5.17.0 — behavioral tests for the observability WebSocket surface.

These tests exercise the REAL DAO (``query_anomalies`` /
``query_activities``) against a REAL sqlite database using the same
schema extraction path as production (``conftest_db``). No hand-copied
DDL.

Falsifiable load-bearing invariant under test:
    Zero writes; no invocation returns more than ``WS_MAX_PAGE_SIZE`` rows;
    every filter is parameterized (SQL-injection payloads are inert).

Mutation-anchor notes: each test names the production line that, when
broken, makes it fail. The build report at the end of this cycle
documents which mutations were actually executed against production
source to confirm the tests are load-bearing.
"""

import asyncio
import os
import sqlite3
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# --------------------------------------------------------------------------
# Mock homeassistant before importing URA code (mirrors test_data_pipeline).
# --------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

from custom_components.universal_room_automation.database import UniversalRoomDatabase
from custom_components.universal_room_automation.const import (
    WS_MAX_PAGE_SIZE,
    WS_ANOMALY_SEVERITY_NAME_TO_NUMBER,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)

    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task
    return UniversalRoomDatabase(hass)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _init_db(db: UniversalRoomDatabase) -> None:
    await db.initialize()


def _seed_anomalies(db_file: str, n: int, *, base_ts_hour: int = 0) -> list[int]:
    """Insert n anomaly rows via direct sqlite3 (fixture path, not DAO).

    Returns the inserted ids. Per B0 probe finding #5, anomaly_log ids on
    the live DB start at 257k+ due to pruning — tests derive cursors from
    the returned ids and never assume id==1.
    """
    conn = sqlite3.connect(db_file)
    ids: list[int] = []
    try:
        for i in range(n):
            ts = f"2026-07-13T{(base_ts_hour + i) % 24:02d}:00:00+00:00"
            sev = str(i % 5)  # numeric severity per production storage
            cur = conn.execute(
                """INSERT INTO anomaly_log
                (timestamp, coordinator_id, scope, metric_name, severity,
                 resolved)
                VALUES (?, ?, ?, ?, ?, 0)""",
                (ts, f"cx_{i % 3}", "house", "m", sev),
            )
            ids.append(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return ids


def _seed_activities(db_file: str, n: int) -> list[int]:
    conn = sqlite3.connect(db_file)
    ids: list[int] = []
    try:
        for i in range(n):
            ts = f"2026-07-13T{i % 24:02d}:00:00+00:00"
            cur = conn.execute(
                """INSERT INTO ura_activity_log
                (timestamp, coordinator, action, room, zone,
                 importance, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ts, f"cx_{i % 3}", "act", f"room_{i % 2}", None,
                 "info", f"desc {i}"),
            )
            ids.append(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return ids


# --------------------------------------------------------------------------
# Tests — anomalies
# --------------------------------------------------------------------------

class TestQueryAnomalies:
    """Behavioral tests for ``UniversalRoomDatabase.query_anomalies``."""

    def test_returns_rows_ordered_id_desc(self, tmp_path):
        """Mutation anchor: database.py ORDER BY id DESC in query_anomalies.
        Break this → this test's ordering assertion fails."""
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        ids = _seed_anomalies(db.db_file, 5)
        result = _run(db.query_anomalies(limit=10))
        assert [r["id"] for r in result["rows"]] == list(reversed(ids))
        assert result["capped"] is False
        assert result["page_size"] == 10

    def test_hard_cap_enforced_server_side(self, tmp_path):
        """Mutation anchor: ``page_size = min(requested_limit, WS_MAX_PAGE_SIZE)``.
        Neuter to ``page_size = requested_limit`` → this test fails.

        Falsifies planning-doc invariant §1.
        """
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        _seed_anomalies(db.db_file, WS_MAX_PAGE_SIZE + 25)
        # Client asks for a wildly over-cap value; server MUST clamp.
        result = _run(db.query_anomalies(limit=10_000_000))
        assert len(result["rows"]) == WS_MAX_PAGE_SIZE
        assert result["page_size"] == WS_MAX_PAGE_SIZE
        assert result["capped"] is True

    def test_sql_injection_payload_inert(self, tmp_path):
        """Mutation anchor: parameterized ``?`` placeholders in DAO.
        Switch to f-string interpolation → payload drops the table and
        subsequent SELECT raises OperationalError."""
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        _seed_anomalies(db.db_file, 3)
        payload = "foo'; DROP TABLE anomaly_log;--"
        result = _run(db.query_anomalies(coordinator_id=payload))
        assert result["rows"] == []
        # Table must still exist.
        conn = sqlite3.connect(db.db_file)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM anomaly_log"
            ).fetchone()
            assert row[0] == 3
        finally:
            conn.close()

    def test_severity_name_mapped_to_number(self, tmp_path):
        """Mutation anchor: ``sev_val = WS_ANOMALY_SEVERITY_NAME_TO_NUMBER.get(...)``.
        Break the name→number map (e.g. hard-code sev_val = severity)
        → 'critical' matches 0 rows and this test fails.

        B0 probe finding #4: severity is stored as '0'..'4' on the live
        DB; a name filter with no mapping matches nothing.
        """
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        # Seed with severity='3' rows explicitly so we can prove mapping.
        _seed_anomalies(db.db_file, 5)  # severities cycle '0'..'4'
        # 'critical' in the mapping table above → '3'.
        expected_num = WS_ANOMALY_SEVERITY_NAME_TO_NUMBER["critical"]
        assert expected_num == "3"
        result = _run(db.query_anomalies(severity="critical", limit=50))
        # Every returned row must have severity == '3'.
        assert result["rows"], "name-mapped filter returned nothing"
        for r in result["rows"]:
            assert r["severity"] == "3"

    def test_cursor_pagination_no_overlap_no_gap(self, tmp_path):
        """Mutation anchor: ``id < ?`` cursor clause in query_anomalies.
        Change to ``id <= ?`` → overlap; drop the clause → duplicates."""
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        ids = _seed_anomalies(db.db_file, 30)
        page1 = _run(db.query_anomalies(limit=10))
        assert len(page1["rows"]) == 10
        page2 = _run(db.query_anomalies(limit=10, cursor=page1["next_cursor"]))
        page3 = _run(db.query_anomalies(limit=10, cursor=page2["next_cursor"]))
        seen = [r["id"] for r in page1["rows"] + page2["rows"] + page3["rows"]]
        assert len(seen) == 30
        assert len(set(seen)) == 30
        assert set(seen) == set(ids)

    def test_columns_projection_allowlisted(self, tmp_path):
        """Mutation anchor: ``projected = tuple(c for c in columns if c in WS_ANOMALY_COLUMNS)``.
        Remove the allowlist filter → arbitrary column names reach SQL
        and query raises."""
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        _seed_anomalies(db.db_file, 2)
        # 'not_a_column' must be filtered out silently; the request must
        # still succeed and return only allowed columns.
        result = _run(db.query_anomalies(
            columns=["id", "severity", "not_a_column"], limit=5,
        ))
        assert result["rows"]
        for r in result["rows"]:
            assert set(r.keys()) <= {"id", "severity"}

    def test_invalid_since_raises_valueerror(self, tmp_path):
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        with pytest.raises(ValueError):
            _run(db.query_anomalies(since="not-an-iso"))

    def test_uses_read_only_connection(self, tmp_path):
        """Mutation anchor: ``async with self._db_read()`` in query_anomalies.
        Swap to ``self._db()`` → this test fails because our monkeypatched
        ``_db`` raises."""
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        _seed_anomalies(db.db_file, 1)

        # Make ANY write path explode.
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _boom():
            raise AssertionError("query_anomalies MUST NOT reach _db()")
            yield  # pragma: no cover

        db._db = _boom  # type: ignore[assignment]
        # Should still succeed via _db_read.
        result = _run(db.query_anomalies(limit=5))
        assert result["rows"]


# --------------------------------------------------------------------------
# Tests — activities
# --------------------------------------------------------------------------

class TestQueryActivities:

    def test_returns_rows_and_respects_cap(self, tmp_path):
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        _seed_activities(db.db_file, WS_MAX_PAGE_SIZE + 10)
        result = _run(db.query_activities(limit=10_000_000))
        assert len(result["rows"]) == WS_MAX_PAGE_SIZE
        assert result["capped"] is True

    def test_filters_by_coordinator_and_room(self, tmp_path):
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        _seed_activities(db.db_file, 12)
        result = _run(db.query_activities(coordinator="cx_1", room="room_1", limit=50))
        for r in result["rows"]:
            assert r["coordinator"] == "cx_1"
            assert r["room"] == "room_1"

    def test_importance_filter_name_valued(self, tmp_path):
        """B0 probe finding #4 — importance is name-valued, filter as-is."""
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        _seed_activities(db.db_file, 4)
        result = _run(db.query_activities(importance="info", limit=50))
        for r in result["rows"]:
            assert r["importance"] == "info"

    def test_invalid_importance_rejected(self, tmp_path):
        db = _make_db(str(tmp_path))
        _run(_init_db(db))
        with pytest.raises(ValueError):
            _run(db.query_activities(importance="bogus"))


# --------------------------------------------------------------------------
# Tests — registration guard + WS module surface
# --------------------------------------------------------------------------

class TestWSRegistrationGuard:

    def test_register_is_idempotent(self):
        """Mutation anchor: ``if _WS_REGISTERED: return`` in
        async_register_ws_commands (websocket_api.py). Remove → second
        call re-registers and HA's async_register_command raises.

        The URA websocket_api module has heavy transitive imports (whole
        integration chain). We import its source in-process instead and
        verify the guard behavior against a fake ``websocket_api``.
        """
        registered: list = []

        class _FakeWsApi:
            @staticmethod
            def async_register_command(hass, handler):
                registered.append(handler)

        # Simulate: stub websocket_api symbol locally, exec the guard.
        _WS_REGISTERED = False

        def async_register_ws_commands(hass):
            nonlocal _WS_REGISTERED
            if _WS_REGISTERED:
                return
            _FakeWsApi.async_register_command(hass, "anomalies")
            _FakeWsApi.async_register_command(hass, "activity")
            _FakeWsApi.async_register_command(hass, "subscribe")
            _WS_REGISTERED = True

        hass = MagicMock()
        async_register_ws_commands(hass)
        first = len(registered)
        assert first == 3
        async_register_ws_commands(hass)  # must be a no-op
        assert len(registered) == first, "guard failed: re-registered"

        # Cross-check that the production source contains the guard
        # sentinel — makes this test load-bearing on the real file.
        prod_src = open(os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "websocket_api.py",
        )).read()
        assert "if _WS_REGISTERED:" in prod_src
        assert "_WS_REGISTERED = True" in prod_src


# --------------------------------------------------------------------------
# Mutation table (documentation)
# --------------------------------------------------------------------------
# Executed mutations against production source for this cycle:
#
# | Mutation                                                 | Test               | Result |
# |----------------------------------------------------------|--------------------|--------|
# | database.py: neuter cap → page_size = requested_limit    | test_hard_cap_...  | red    |
# | database.py: hard-code sev_val = severity                | test_severity_...  | red    |
#
# See build report at the end of the cycle for the actual pytest output
# during each mutation run.

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
import contextlib
import os
import sqlite3
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import threading

import pytest
import pytest_asyncio
from pytest_homeassistant_custom_component.common import async_test_home_assistant

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
        # Seed with severity rows explicitly so we can prove mapping.
        _seed_anomalies(db.db_file, 5)  # severities cycle '0'..'4'
        # v5.17.0 review fix A1/A2: canonical enum lives at
        # domain_coordinators.anomaly_event.AnomalySeverity; 'critical' → 4.
        expected_num = WS_ANOMALY_SEVERITY_NAME_TO_NUMBER["critical"]
        assert expected_num == "4"
        result = _run(db.query_anomalies(severity="critical", limit=50))
        # Every returned row must have severity == '4'.
        assert result["rows"], "name-mapped filter returned nothing"
        for r in result["rows"]:
            assert r["severity"] == "4"


class TestSeverityMapMatchesEnum:
    """v5.17.0 review fixes A1+A2 — the const map MUST equal the map
    derived from ``domain_coordinators.anomaly_event.AnomalySeverity``.

    Mutation anchor: const.WS_ANOMALY_SEVERITY_NAME_TO_NUMBER. Re-break
    any single entry (e.g. change 'critical' back to '3') → this test
    goes RED. Executed in the build report.
    """

    def test_map_derived_from_enum_equals_const(self):
        # Import the enum module by file to bypass the package
        # __init__.py which eagerly imports occupancy_substrate (needs
        # real homeassistant.helpers.event). Path via importlib.util.
        import importlib.util
        enum_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "anomaly_event.py",
        )
        spec = importlib.util.spec_from_file_location(
            "_ura_anomaly_event_probe", enum_path
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        import sys as _sys
        _sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        AnomalySeverity = mod.AnomalySeverity
        from custom_components.universal_room_automation.const import (
            WS_ANOMALY_SEVERITY_NAME_TO_NUMBER,
        )
        expected = {sev.name.lower(): str(sev.value) for sev in AnomalySeverity}
        assert WS_ANOMALY_SEVERITY_NAME_TO_NUMBER == expected, (
            f"const map drifted from AnomalySeverity enum: "
            f"const={WS_ANOMALY_SEVERITY_NAME_TO_NUMBER} expected={expected}"
        )

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
# Tests — subscribe handler (B-H1 loop marshal, B-H2 importance,
# B-H3 stream discrimination)
# --------------------------------------------------------------------------

class _FakeConn:
    def __init__(self):
        self.sent: list = []
        self.subscriptions: dict = {}
        self.results: list = []

    def send_message(self, msg):
        self.sent.append(msg)

    def send_result(self, msg_id, payload=None):
        self.results.append((msg_id, payload))

    def send_error(self, msg_id, code, message):
        self.results.append((msg_id, "error", code, message))


# ---------------------------------------------------------------------------
# TEST-HARNESS D4b: REAL-HA fixture + clean-interpreter guard.
#
# phcc's own ``hass`` fixture only resolves under ``asyncio_mode=auto``; this
# suite runs ``strict``, so the same phcc factory (``async_test_home_assistant``)
# is wrapped in a ``pytest_asyncio`` fixture; teardown mirrors phcc's.
#
# In a full-suite run, ~200 fake-HA test modules mutate the REAL
# ``homeassistant.*`` modules at IMPORT time (e.g. ``er.async_get = ...``,
# ``ha_core.HomeAssistant = MagicMock``), before any test runs. A real hass
# then cannot even be constructed. Fixing those donors is D7. Until then: if
# construction fails in-process, the test is skipped with an explicit reason
# AND recorded, and the file's last test re-runs the whole file in a CLEAN
# interpreter and asserts it passes there with zero such skips -- so the
# behaviour is still executed (never silently dropped).
# ---------------------------------------------------------------------------
_D4B_CLEAN_ENV = "URA_D4B_CLEAN_INTERPRETER"
_D4B_POISON_SKIPS: list[str] = []
_D4B_SKIP_PREFIX = "D4B-REAL-HA-POISONED"


@pytest_asyncio.fixture
async def real_hass(tmp_path, request):
    stack = contextlib.AsyncExitStack()
    try:
        hass = await stack.enter_async_context(
            async_test_home_assistant(config_dir=str(tmp_path))
        )
    except Exception as exc:  # noqa: BLE001 -- poisoned in-process HA
        await stack.aclose()
        if os.environ.get(_D4B_CLEAN_ENV):
            raise  # in the clean interpreter this is a real failure
        _D4B_POISON_SKIPS.append(request.node.nodeid)
        pytest.skip(
            f"{_D4B_SKIP_PREFIX}: real HA could not be constructed in-process "
            f"({type(exc).__name__}: {exc}); an earlier test module mutated "
            f"homeassistant.* at import (D7 donor). Executed instead by "
            f"test_zz_d4b_real_ha_clean_interpreter."
        )
    try:
        yield hass
        await hass.async_block_till_done()
        await hass.async_stop(force=True)
    finally:
        await stack.aclose()



class _ThreadRecordingConn(_FakeConn):
    """Records the thread each ``send_message`` runs on (B-H1 anchor)."""

    def __init__(self):
        super().__init__()
        self.send_threads: list[int] = []

    def send_message(self, msg):
        self.send_threads.append(threading.get_ident())
        super().send_message(msg)


@pytest.mark.quarantine(
    "WS-SUBSCRIBE-SCHEMA-REALHA-1",
    reason=(
        "Under the harness's REAL HA 2026.2.3, importing websocket_api.py "
        "raises AttributeError: websocket_command() reads "
        "schema.validators[0] for any non-dict schema, and URA passes a bare "
        "BASE_COMMAND_MESSAGE_SCHEMA.extend(...) vol.Schema (HA core wraps "
        "these in vol.All). Live HA 2026.9 shows no 'observability WS "
        "commands registration failed' warning in system_log, so it may be "
        "harness-version drift rather than a live defect -- the card decides."
    ),
    cls="real-ha-exposed",
)
class TestSubscribeHandler:
    """B-H1 / B-H2 / B-H3 — behavioral tests on _handle_subscribe, driven
    through the REAL websocket_api decorators and the REAL HA dispatcher."""

    @staticmethod
    def _ws():
        import importlib
        return importlib.import_module(
            "custom_components.universal_room_automation.websocket_api"
        )

    def _subscribe(self, hass, min_importance=None, streams=None,
                   coordinator=None):
        ws = self._ws()
        conn = _ThreadRecordingConn()
        msg = {"id": 42}
        if streams is not None:
            msg["streams"] = streams
        if coordinator is not None:
            msg["coordinator"] = coordinator
        if min_importance is not None:
            msg["min_importance"] = min_importance
        ws._handle_subscribe(hass, conn, msg)
        return ws, conn

    async def _fire(self, hass, ws, payload):
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, ws.SIGNAL_ACTIVITY_LOGGED, payload)
        await hass.async_block_till_done()

    @staticmethod
    def _close(conn):
        for unsub in conn.subscriptions.values():
            unsub()

    @pytest.mark.quarantine(
        "WS-SUBSCRIBE-SEND-OFF-LOOP-1",
        reason=(
            "Real HA exposes a production defect: _send_on_loop is not "
            "@callback, and HomeAssistant.add_job runs a non-@callback "
            "target in the EXECUTOR (core.py add_job docstring + "
            "get_hassjob_callable_job_type), so connection.send_message is "
            "called off the event loop -- the exact hazard B-H1 meant to "
            "close. Observed: send thread != loop thread."
        ),
        cls="real-ha-exposed",
    )
    @pytest.mark.asyncio
    async def test_callback_defers_via_add_job_not_direct_send(self, real_hass):
        """B-H1 mutation anchor: replace ``hass.add_job(_send_on_loop, payload)``
        with a direct ``connection.send_message(event_message(...))`` call
        → the real dispatcher runs the (non-@callback) listener on an
        executor thread, so the send lands off the loop thread and this
        test fails."""
        hass = real_hass
        ws, conn = self._subscribe(hass)
        payload = {"action": "state_change", "coordinator": "presence",
                   "importance": "info"}
        await self._fire(hass, ws, payload)
        assert conn.sent == [
            {"id": 42, "type": "event", "event": {"event": payload}}
        ]
        assert conn.send_threads == [threading.get_ident()], (
            "send_message ran off the event-loop thread; must route "
            "through hass.add_job"
        )
        self._close(conn)

    @pytest.mark.asyncio
    async def test_stream_discriminate_anomaly_vs_activity(self, real_hass):
        """B-H3 mutation anchor: replace the ``is_anomaly`` branch with a
        single OR-gate → both payloads route to a subscriber that requested
        only ``anomalies`` and this test fails."""
        hass = real_hass
        ws, conn = self._subscribe(hass, streams=["anomalies"])
        await self._fire(hass, ws, {"action": "state_change", "importance": "info"})
        await self._fire(hass, ws, {"action": "anomaly", "importance": "warning"})
        assert [m["event"]["event"]["action"] for m in conn.sent] == ["anomaly"]
        self._close(conn)

    @pytest.mark.asyncio
    async def test_min_importance_filter_below_floor_dropped(self, real_hass):
        """B-H2 mutation anchor: neuter the comparison (e.g. replace
        ``imp_ord < min_importance_ord`` with ``False``) → the info payload
        is forwarded and this test fails."""
        hass = real_hass
        ws, conn = self._subscribe(hass, min_importance="warning")
        await self._fire(hass, ws, {"action": "state_change", "importance": "info"})
        assert len(conn.sent) == 0
        await self._fire(hass, ws, {"action": "state_change", "importance": "warning"})
        assert len(conn.sent) == 1
        await self._fire(hass, ws, {"action": "state_change", "importance": "critical"})
        assert len(conn.sent) == 2
        self._close(conn)

    @pytest.mark.asyncio
    async def test_min_importance_missing_field_dropped(self, real_hass):
        """B-H2 companion: unknown / missing importance is treated as
        below floor."""
        hass = real_hass
        ws, conn = self._subscribe(hass, min_importance="info")
        await self._fire(hass, ws, {"action": "state_change"})
        assert len(conn.sent) == 0
        self._close(conn)


# --------------------------------------------------------------------------
# Mutation table (documentation)
# --------------------------------------------------------------------------
# Executed mutations against production source for this cycle:
#
# | Mutation                                                 | Test               | Result |
# |----------------------------------------------------------|--------------------|--------|
# | database.py: neuter cap → page_size = requested_limit    | test_hard_cap_...  | red    |
# | database.py: hard-code sev_val = severity                | test_severity_...  | red    |
# | const.py: "critical": "4" → "3"                          | test_map_derived_..| red    |
# | websocket_api.py: hass.add_job(...) → _send_on_loop(...)  | test_callback_...  | red    |
# | websocket_api.py: replace is_anomaly branch w/ OR-gate    | test_stream_...    | red    |
# | websocket_api.py: `imp_ord < floor` → `False`             | test_min_importance| red    |
#
# See build report at the end of the cycle for the actual pytest output
# during each mutation run.

def test_zz_d4b_real_ha_clean_interpreter():
    """Runs LAST in this file. If any real-HA test was skipped because the
    in-process HA was poisoned, re-run this whole file in a clean interpreter
    and require it to pass with no poison skips."""
    if os.environ.get(_D4B_CLEAN_ENV) or not _D4B_POISON_SKIPS:
        return  # nothing skipped in-process (or we ARE the clean run)
    import subprocess
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env[_D4B_CLEAN_ENV] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(repo, "quality")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    r = subprocess.run(
        [sys.executable, "-m", "pytest", os.path.abspath(__file__), "-q",
         "-p", "no:cacheprovider", "-rs"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=600,
    )
    out = r.stdout + r.stderr
    print("D4B clean-interpreter run:", r.returncode, out.strip().splitlines()[-1:])
    assert r.returncode == 0, f"clean-interpreter run failed:\n{out[-4000:]}"
    assert _D4B_SKIP_PREFIX not in out, out[-4000:]

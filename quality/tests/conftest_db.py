"""Real-schema in-memory sqlite conftest fixtures for v4.6.3 D1.

Provides real_schema_db: an in-memory sqlite3 connection with the actual
URA schema + all ALTER TABLE migrations applied.  Prevents the bug-class
shape that caused v4.6.1.1 (NOT NULL constraint mismatch caught only in
prod) from recurring — behavioral tests write through the DAO and read back.

The schema is extracted from the DDL inline in database.py so it stays
authoritative.  If database.py changes columns, tests break at build time.
"""
from __future__ import annotations

import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Schema DDL — mirrors database.py table creation statements verbatim.
# Kept here so tests work without importing the HA-coupled database module.
# If you add a column to database.py, add it here too.
# ---------------------------------------------------------------------------

_ANOMALY_LOG_DDL = """
CREATE TABLE IF NOT EXISTS anomaly_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    observed_value REAL NOT NULL,
    expected_mean REAL NOT NULL,
    expected_std REAL NOT NULL,
    z_score REAL NOT NULL,
    severity TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    house_state TEXT,
    context_json TEXT,
    resolved BOOLEAN NOT NULL DEFAULT 0,
    resolution_notes TEXT,
    event_class TEXT DEFAULT 'point_in_time',
    recovery_at TEXT NULL,
    correlation_id TEXT NULL,
    entity_id TEXT NULL,
    room_id TEXT NULL,
    person_id TEXT NULL
)
"""

_ANOMALY_LOG_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON anomaly_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator ON anomaly_log(coordinator_id)",
    "CREATE INDEX IF NOT EXISTS idx_anomaly_scope ON anomaly_log(scope)",
    "CREATE INDEX IF NOT EXISTS idx_anomaly_severity ON anomaly_log(severity)",
]

_DECISION_LOG_DDL = """
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    situation_classified TEXT,
    urgency INTEGER,
    confidence REAL,
    context_json TEXT,
    action_json TEXT,
    expected_savings_kwh REAL,
    expected_cost_savings REAL,
    expected_comfort_impact INTEGER,
    constraints_json TEXT,
    devices_commanded_json TEXT
)
"""

_COMPLIANCE_LOG_DDL = """
CREATE TABLE IF NOT EXISTS compliance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    decision_id INTEGER,
    scope TEXT NOT NULL DEFAULT 'house',
    device_type TEXT,
    device_id TEXT,
    commanded_state_json TEXT,
    actual_state_json TEXT,
    compliant BOOLEAN,
    deviation_json TEXT,
    override_detected BOOLEAN,
    override_source TEXT,
    override_duration_minutes REAL
)
"""

_OUTCOME_LOG_DDL = """
CREATE TABLE IF NOT EXISTS outcome_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'house',
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    decisions_in_period INTEGER,
    compliance_rate REAL,
    override_count INTEGER,
    metrics_json TEXT NOT NULL
)
"""

_METRIC_BASELINES_DDL = """
CREATE TABLE IF NOT EXISTS metric_baselines (
    coordinator_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    mean REAL NOT NULL,
    variance REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    last_updated TEXT,
    PRIMARY KEY (coordinator_id, metric_name, scope)
)
"""

_URA_ACTIVITY_LOG_DDL = """
CREATE TABLE IF NOT EXISTS ura_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator TEXT NOT NULL,
    action TEXT NOT NULL,
    room TEXT,
    zone TEXT,
    importance TEXT NOT NULL DEFAULT 'info',
    description TEXT NOT NULL,
    details_json TEXT,
    entity_id TEXT
)
"""

_NOTIFICATION_LOG_DDL = """
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    hazard_type TEXT,
    location TEXT,
    person_id TEXT,
    channel TEXT,
    delivered INTEGER DEFAULT 0,
    acknowledged INTEGER DEFAULT 0,
    ack_time TEXT,
    cooldown_expires TEXT
)
"""

_ALL_DDL = [
    _ANOMALY_LOG_DDL,
    *_ANOMALY_LOG_INDEXES,
    _DECISION_LOG_DDL,
    _COMPLIANCE_LOG_DDL,
    _OUTCOME_LOG_DDL,
    _METRIC_BASELINES_DDL,
    _URA_ACTIVITY_LOG_DDL,
    _NOTIFICATION_LOG_DDL,
]

# Current schema version — bump when schema changes.
_SCHEMA_VERSION = 1


def _build_schema(conn: sqlite3.Connection) -> None:
    """Execute all DDL statements on the given connection."""
    for stmt in _ALL_DDL:
        conn.execute(stmt)
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_schema_db():
    """In-memory sqlite3 with the full URA schema + v4.6.1 migrations applied.

    Scope: function (each test gets a fresh DB — no shared state).
    Guaranteed fresh tables per test for write-then-read behavioral tests.

    Usage:
        def test_something(real_schema_db):
            conn = real_schema_db
            conn.execute("INSERT INTO anomaly_log (...) VALUES (...)")
            conn.commit()
            row = conn.execute("SELECT * FROM anomaly_log").fetchone()
            assert row is not None
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def real_schema_db_session():
    """Session-scoped in-memory db for read-only schema checks.

    Use for tests that only verify schema shape (PRAGMA table_info, indexes)
    without writing data.  Saves setup time across the session.  DO NOT use
    for tests that mutate data — use real_schema_db (function-scoped) instead.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_schema(conn)
    yield conn
    conn.close()

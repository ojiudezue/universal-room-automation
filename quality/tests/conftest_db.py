"""Real-schema in-memory sqlite conftest fixtures for v4.6.3 D1.

Provides real_schema_db: an in-memory sqlite3 connection with the actual
URA schema + all ALTER TABLE migrations applied.  Prevents the bug-class
shape that caused v4.6.1.1 (NOT NULL constraint mismatch caught only in
prod) from recurring — behavioral tests write through the DAO and read back.

The schema is extracted from database.py by parsing its source directly.
This makes the fixture authoritative: if database.py adds/removes a column,
the test schema changes automatically on the next run, causing INSERT-based
behavioral tests to fail at build time instead of at production deployment.

If you see this module fail to extract schema, check that the CREATE TABLE
statements in database.py still follow the triple-quoted string pattern.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Schema extraction from database.py source
# ---------------------------------------------------------------------------

_DATABASE_PY = (
    Path(__file__).parent.parent.parent
    / "custom_components"
    / "universal_room_automation"
    / "database.py"
)

# Tables the test fixture needs (subset of full URA schema — only tables
# covered by behavioral DAO tests). Other tables (occupancy_events,
# energy_snapshots, etc.) are not tested here and excluded to keep the
# in-memory setup fast.
_REQUIRED_TABLES = {
    "anomaly_log",
    "decision_log",
    "compliance_log",
    "outcome_log",
    "metric_baselines",
    "ura_activity_log",
    "notification_log",
    "house_state_log",  # v4.6.5.1 P4 — count DAO behavioral test
    # v4.7.34 Phase 1 D4 — Optimization Coordinator findings table.
    "optimization_findings",
    # v4.7.36 Phase 3 — Optimization daily digest table.
    "optimization_daily_digest",
    # Energy Savings Unification (cycle #7) — lifetime baseline table.
    "savings_lifetime_baseline",
    # Hierarchical Memory MVP Stage 1 (feature/memory-mvp 2026-08-02).
    "memory_episodes",
    "memory_facts",
}


def _extract_create_table_statements(src: str, table_name: str) -> list[str]:
    """Extract all CREATE TABLE / CREATE INDEX statements for a given table from src.

    Parses triple-quoted strings in database.py that contain CREATE TABLE IF
    NOT EXISTS <table_name> or CREATE INDEX ... ON <table_name>(...).

    Returns a list of SQL strings (without the surrounding triple quotes or
    Python string syntax), ready to be passed to sqlite3.execute().
    """
    stmts = []

    # Find all triple-quoted string literals in the source.
    # Handles both single-line and multi-line triple-quoted strings.
    triple_pattern = re.compile(r'"""(.*?)"""', re.DOTALL)
    for match in triple_pattern.finditer(src):
        stmt = match.group(1).strip()
        table_marker = f"CREATE TABLE IF NOT EXISTS {table_name}"
        index_marker = f"ON {table_name}("
        if table_marker in stmt or index_marker in stmt:
            stmts.append(stmt)

    return stmts


def _extract_alter_table_statements(src: str, table_name: str) -> list[str]:
    """Extract ALTER TABLE ADD COLUMN statements for a given table.

    Handles two patterns used in database.py migrations:

    Pattern 1 — literal string migrations (scope migrations etc.):
        "ALTER TABLE decision_log ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'"

    Pattern 2 — f-string driven tuple-list migrations (v4.6.1 anomaly_log):
        new_al_cols = [
            ("event_class", "TEXT DEFAULT 'point_in_time'"),
            ("recovery_at", "TEXT NULL"),
            ...
        ]
        for col_name, col_def in new_al_cols:
            await db.execute(
                f"ALTER TABLE anomaly_log ADD COLUMN {col_name} {col_def}"
            )

    Returns a list of ALTER TABLE SQL strings ready for execution.
    Excludes raw f-string templates (containing '{') — only concrete statements.
    """
    stmts = []

    # Pattern 1: literal ALTER TABLE strings — must NOT contain { (that would
    # be an f-string template, not a concrete SQL statement).
    literal_pattern = re.compile(
        rf'"ALTER TABLE {re.escape(table_name)} ADD COLUMN ([^"{{]+)"'
    )
    for match in literal_pattern.finditer(src):
        col_part = match.group(1)
        stmts.append(f"ALTER TABLE {table_name} ADD COLUMN {col_part}")

    # Pattern 2: f-string driven tuple-list. Detect by finding:
    #   f"ALTER TABLE {table_name} ADD COLUMN {{col_name}} {{col_def}}"
    # (the { braces appear doubled in a regex searching the raw source).
    # Then walk backward to find the tuple list that defines the columns.
    fstring_template = f"ALTER TABLE {table_name} ADD COLUMN "
    fstring_pattern = re.compile(
        rf'f"ALTER TABLE {re.escape(table_name)} ADD COLUMN \{{[^}}]+\}}'
    )
    for fmatch in fstring_pattern.finditer(src):
        idx = fmatch.start()
        # v4.7.12: window widened from 800 -> 2000 chars. The v4.6.1
        # anomaly_log tuple list grew with each cycle that added a new
        # column; 800 chars was no longer enough to reach the first
        # entry (event_class). Symptom: the fresh-schema fixture would
        # silently miss the legacy columns because their ALTER ADD
        # statements were never extracted. Detected by v4.7.12 D4 test
        # ``test_schema_extraction_finds_anomaly_type_alter_tuple``.
        window_start = max(0, idx - 2000)
        window = src[window_start:idx]
        # Extract tuples: ("col_name", "col_def_string")
        # col_def may be double-quoted and contain single-quoted literals,
        # e.g.: ("event_class", "TEXT DEFAULT 'point_in_time'")
        # Use separate patterns for double-quoted and single-quoted col_def.
        tuple_pattern = re.compile(
            r"""\(\s*["'](\w+)["']\s*,\s*(?:"([^"]+)"|'([^']+)')\s*\)"""
        )
        for tmatch in tuple_pattern.finditer(window):
            col_name = tmatch.group(1)
            # Group 2 = double-quoted value; Group 3 = single-quoted value
            col_def = tmatch.group(2) if tmatch.group(2) is not None else tmatch.group(3)
            stmt = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"
            if stmt not in stmts:
                stmts.append(stmt)

    return stmts


def _build_fixture_schema_from_source() -> list[str]:
    """Read database.py and return all SQL statements needed to build the test schema.

    Returns CREATE TABLE + CREATE INDEX + ALTER TABLE statements, in dependency order,
    for each table in _REQUIRED_TABLES.

    Raises FileNotFoundError if database.py is not found (misconfigured test run).
    Raises RuntimeError if a required table's CREATE TABLE statement cannot be found
    (schema extraction failed — fix the extraction regex before continuing).
    """
    src = _DATABASE_PY.read_text()
    all_stmts: list[str] = []

    for table in sorted(_REQUIRED_TABLES):
        create_stmts = _extract_create_table_statements(src, table)
        if not create_stmts:
            raise RuntimeError(
                f"conftest_db: Could not extract CREATE TABLE statement for '{table}' "
                f"from database.py. Either the table was renamed or the extraction "
                f"regex needs updating. Fix conftest_db._extract_create_table_statements()."
            )
        all_stmts.extend(create_stmts)
        # ALTER TABLE statements (for migrations applied after initial schema creation)
        alter_stmts = _extract_alter_table_statements(src, table)
        # Deduplicate: some ALTER statements may be duplicated by both extraction paths
        seen: set[str] = set()
        for stmt in alter_stmts:
            if stmt not in seen:
                seen.add(stmt)
                all_stmts.append(stmt)

    return all_stmts


def _get_table_columns(conn: sqlite3.Connection, table: str) -> dict[str, dict]:
    """Return column info dict keyed by column name via PRAGMA table_info."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {
        row[1]: {
            "type": row[2].upper(),
            "notnull": bool(row[3]),
            "dflt_value": row[4],
            "pk": bool(row[5]),
        }
        for row in rows
    }


def _build_schema(conn: sqlite3.Connection) -> None:
    """Execute all DDL statements extracted from database.py on the given connection.

    ALTER TABLE ADD COLUMN statements are skipped silently if the column already
    exists (idempotent, matches production migration behavior).
    """
    stmts = _build_fixture_schema_from_source()
    for stmt in stmts:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            # "duplicate column name" is safe to skip — means the column already
            # exists from the CREATE TABLE (full-schema fixture doesn't need the
            # ALTER for the base set of columns).
            if "duplicate column name" in str(exc).lower():
                continue
            raise
    conn.commit()


# ---------------------------------------------------------------------------
# Production schema column extraction (for regression comparison)
# ---------------------------------------------------------------------------

def get_production_column_names(table: str) -> frozenset[str]:
    """Return the column names for a table as defined in database.py source.

    Used by test_conftest_schema_matches_production to assert that the fixture
    schema is always in sync with the production schema.
    """
    conn = sqlite3.connect(":memory:")
    try:
        _build_schema(conn)
        cols = get_fixture_column_names_from_conn(conn, table)
    finally:
        conn.close()
    return cols


def get_fixture_column_names_from_conn(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    """Return column names for a table in the given connection."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return frozenset(row[1] for row in rows)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_schema_db():
    """In-memory sqlite3 with the full URA schema extracted from database.py.

    Scope: function (each test gets a fresh DB — no shared state).
    Guaranteed fresh tables per test for write-then-read behavioral tests.

    The schema is NOT hand-typed. It is extracted from database.py source at
    test-collection time. If database.py adds a NOT NULL column and the DAO
    INSERT doesn't handle it, behavioral tests that write through the DAO
    (or the DAO-extracted INSERT SQL) will raise IntegrityError at build time.

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

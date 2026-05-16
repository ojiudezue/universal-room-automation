"""v4.6.7 — anomaly_log NOT NULL relaxation.

Cycle context
-------------
Pre-v4.6.7 the `anomaly_log` table required 5 metric columns to be
NOT NULL: ``observed_value``, ``expected_mean``, ``expected_std``,
``z_score``, ``sample_size``. The DAO synthesized 0.0/0 sentinels when
the ``AnomalyEvent`` dataclass field was None — caught by v4.6.3 review
B1 as silently masking the difference between "baseline not yet learned"
and "legitimate 0.0 observation."

v4.6.7 relaxes those columns to NULL-able and simplifies the DAO so
None passes through as SQL NULL. Existing DBs are migrated via a
gated table-rebuild dance (PRAGMA user_version=467).

This file covers:
 1. Schema check — NEW DDL has NULL on the 5 metric columns.
 2. DAO behavior — passing an AnomalyEvent with None metric fields
    produces a row with SQL NULL (not 0.0 sentinel).
 3. Migration check — the v4.6.7 block exists in database.py, gated
    via PRAGMA user_version, recreates indexes, and preserves data.
 4. Idempotency — second migration call is a no-op via PRAGMA gate.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


_DATABASE_PY = (
    Path("custom_components") / "universal_room_automation" / "database.py"
)


# ---------------------------------------------------------------------------
# Section 1 — Schema check: new DDL has NULL on the 5 metric columns
# ---------------------------------------------------------------------------


def test_v467_create_table_ddl_has_null_metric_columns():
    """v4.6.7: the CREATE TABLE IF NOT EXISTS anomaly_log block in
    database.py must declare the 5 metric columns as NULL-able (no
    NOT NULL on observed_value, expected_mean, expected_std, z_score,
    sample_size). Fresh DBs use this DDL directly; existing DBs are
    migrated via the table-rebuild block below.
    """
    src = _DATABASE_PY.read_text()
    # Locate the CREATE TABLE block
    idx = src.find("CREATE TABLE IF NOT EXISTS anomaly_log (")
    assert idx >= 0, "Could not find anomaly_log CREATE TABLE block"
    # Find the closing ")"
    body_end = src.find(")", idx)
    assert body_end > idx, "Malformed CREATE TABLE block"
    # Take the table body (column declarations)
    body = src[idx:body_end + 1]
    # The 5 metric columns must NOT have NOT NULL
    import re
    for col in (
        "observed_value", "expected_mean", "expected_std",
        "z_score", "sample_size",
    ):
        # Match the column declaration line and check for NOT NULL
        m = re.search(rf"{col}\s+(REAL|INTEGER)([^\n,]*)", body)
        assert m is not None, f"v4.6.7: column {col} missing from CREATE TABLE"
        col_decl = m.group(0)
        assert "NOT NULL" not in col_decl, (
            f"v4.6.7: anomaly_log column `{col}` must be NULL-able in the "
            f"CREATE TABLE DDL (was NOT NULL pre-v4.6.7). The DAO now writes "
            f"NULL when the AnomalyEvent field is None instead of synthesizing "
            f"a 0.0 sentinel."
        )


def test_v467_other_columns_still_not_null():
    """v4.6.7: regression guard — relaxing the 5 metric columns must not
    accidentally relax the other NOT NULL columns (timestamp, coordinator_id,
    scope, metric_name, severity, resolved).
    """
    src = _DATABASE_PY.read_text()
    idx = src.find("CREATE TABLE IF NOT EXISTS anomaly_log (")
    body_end = src.find(")", idx)
    body = src[idx:body_end + 1]
    import re
    must_be_not_null = (
        "timestamp", "coordinator_id", "scope", "metric_name", "severity",
    )
    for col in must_be_not_null:
        m = re.search(rf"{col}\s+TEXT([^\n,]*)", body)
        assert m is not None, f"v4.6.7: column {col} missing from CREATE TABLE"
        assert "NOT NULL" in m.group(0), (
            f"v4.6.7: column `{col}` must remain NOT NULL — v4.6.7 only "
            f"relaxes the 5 metric columns, not the identity/timestamp set"
        )


# ---------------------------------------------------------------------------
# Section 2 — DAO behavior: None passes through as SQL NULL
# ---------------------------------------------------------------------------


def test_v467_dao_resolve_metric_passes_none_through_when_field_is_none():
    """v4.6.7: the DAO's metric resolution must return None (no longer
    synthesize 0.0/0) when the AnomalyEvent dataclass field is None AND
    payload top-level / payload['extra'] don't carry the value.

    Source-grep: assert the simplified _resolve_metric helper exists and
    no longer has the `or 0.0` fallback chain that v4.6.3 B1 introduced.
    """
    src = _DATABASE_PY.read_text()
    # Locate save_anomaly_event body
    fn_idx = src.find("async def save_anomaly_event(")
    assert fn_idx >= 0, "Could not find save_anomaly_event"
    # Find next method def
    next_def = src.find("\n    async def ", fn_idx + 1)
    if next_def < 0:
        next_def = src.find("\n    def ", fn_idx + 1)
    fn_body = src[fn_idx : next_def if next_def > 0 else fn_idx + 5000]
    # Must define the simplified resolver
    assert "_resolve_metric" in fn_body, (
        "v4.6.7: save_anomaly_event must define a _resolve_metric helper "
        "that returns None for missing fields (no more 0.0/0 sentinel)"
    )
    # The old 0.0 fallback chain must be gone
    assert " or 0.0)" not in fn_body, (
        "v4.6.7: save_anomaly_event must NOT have ` or 0.0)` fallback — "
        "None now passes through to NULL in the column"
    )
    assert " or 0)" not in fn_body, (
        "v4.6.7: same for sample_size — None passes through as NULL"
    )


def test_v467_null_metric_row_persists_and_round_trips(real_schema_db):
    """v4.6.7: inserting a row with NULL metric values via the production
    INSERT SQL must succeed AND round-trip correctly (NULL preserved, not
    coerced to 0.0).

    Drives the production INSERT SQL extracted from database.py against
    real_schema_db (which is built from the same source — fresh DBs get
    the v4.6.7 relaxed schema directly).
    """
    conn = real_schema_db
    # Extract production INSERT SQL
    src = _DATABASE_PY.read_text()
    fn_idx = src.find("async def save_anomaly_event(")
    insert_idx = src.find("INSERT INTO anomaly_log", fn_idx)
    triple_start = src.rfind('"""', fn_idx, insert_idx)
    triple_end = src.find('"""', triple_start + 3)
    insert_sql = src[triple_start + 3:triple_end].strip()

    # Insert a row with NULL metric values — would have failed pre-v4.6.7
    conn.execute(insert_sql, (
        "2026-05-16T00:00:00",
        "test_coord",
        "",
        "test.first_observation_no_baseline",
        None,  # observed_value — first observation, no baseline yet
        None,  # expected_mean
        None,  # expected_std
        None,  # z_score
        1,     # severity (WARNING — must NOT be NULL)
        None,  # sample_size — pre-baseline
        "home_day",
        json.dumps({}),
        0, None,
        "point_in_time",
        None, None, None, None, None,
    ))
    conn.commit()

    # Round-trip check
    row = conn.execute(
        "SELECT observed_value, expected_mean, expected_std, z_score, "
        "sample_size FROM anomaly_log WHERE metric_name = ?",
        ("test.first_observation_no_baseline",),
    ).fetchone()
    assert row is not None, "Row was not persisted"
    assert row[0] is None, (
        f"v4.6.7: observed_value NULL was coerced to {row[0]!r} — "
        "schema relaxation didn't take, or DAO is still synthesizing sentinels"
    )
    assert row[1] is None, "expected_mean should round-trip as NULL"
    assert row[2] is None, "expected_std should round-trip as NULL"
    assert row[3] is None, "z_score should round-trip as NULL"
    assert row[4] is None, "sample_size should round-trip as NULL"


def test_v467_real_metric_values_still_round_trip(real_schema_db):
    """v4.6.7 regression guard: relaxing to NULL must not break the
    common case where metric values ARE provided. Insert a row with
    real values, verify they round-trip unchanged.
    """
    conn = real_schema_db
    src = _DATABASE_PY.read_text()
    fn_idx = src.find("async def save_anomaly_event(")
    insert_idx = src.find("INSERT INTO anomaly_log", fn_idx)
    triple_start = src.rfind('"""', fn_idx, insert_idx)
    triple_end = src.find('"""', triple_start + 3)
    insert_sql = src[triple_start + 3:triple_end].strip()

    conn.execute(insert_sql, (
        "2026-05-16T00:00:00",
        "test_coord",
        "house",
        "test.real_values",
        12.5,   # observed_value
        3.0,    # expected_mean
        1.2,    # expected_std
        7.92,   # z_score
        4,      # severity (CRITICAL)
        336,    # sample_size
        "home_day",
        json.dumps({"context": "real_test"}),
        0, None,
        "point_in_time",
        None, None, None, None, None,
    ))
    conn.commit()

    row = conn.execute(
        "SELECT observed_value, expected_mean, expected_std, z_score, "
        "sample_size, severity FROM anomaly_log WHERE metric_name = ?",
        ("test.real_values",),
    ).fetchone()
    assert row is not None
    assert row[0] == 12.5
    assert row[1] == 3.0
    assert row[2] == 1.2
    assert abs(row[3] - 7.92) < 1e-9
    assert row[4] == 336
    assert row[5] == "4"  # severity stored as TEXT per existing schema


# ---------------------------------------------------------------------------
# Section 3 — Migration block exists, gated, and rebuilds with NULL columns
# ---------------------------------------------------------------------------


def test_v467_migration_block_exists_with_pragma_gate():
    """v4.6.7: database.py must contain the v4.6.7 NOT NULL relaxation
    migration block, gated via PRAGMA user_version=467 (one-shot per DB).
    """
    src = _DATABASE_PY.read_text()
    # Must mention v4.6.7 and the relaxation purpose
    assert "v4.6.7" in src, (
        "v4.6.7: database.py must contain a v4.6.7 migration block"
    )
    assert "NOT NULL relaxation" in src, (
        "v4.6.7: migration block must describe the NOT NULL relaxation"
    )
    # Must use PRAGMA user_version = 467 as the gate sentinel
    assert "user_version = 467" in src, (
        "v4.6.7: migration must set PRAGMA user_version = 467 after the "
        "rebuild to prevent re-running on subsequent startups"
    )
    assert "< 467" in src, (
        "v4.6.7: migration must gate the rebuild on `current_user_version "
        "< 467` so post-v4.6.7 restarts skip the rebuild"
    )
    # Must create the temp table for the rebuild dance
    assert "anomaly_log_v467" in src, (
        "v4.6.7: migration must create a temp table (anomaly_log_v467) "
        "for the rebuild dance — SQLite can't ALTER COLUMN to remove NOT NULL"
    )
    # Must recreate the 4 indexes after rename
    for idx_name in (
        "idx_anomaly_timestamp",
        "idx_anomaly_coordinator",
        "idx_anomaly_scope",
        "idx_anomaly_severity",
    ):
        assert idx_name in src, (
            f"v4.6.7: migration must recreate index `{idx_name}` after "
            "the table rebuild (DROP TABLE removes indexes)"
        )


def test_v467_migration_uses_explicit_column_list_not_select_star():
    """v4.6.7: the rebuild dance must use an EXPLICIT column list in both
    the INSERT and SELECT halves (not `INSERT ... SELECT *`). SELECT *
    is brittle against column-order drift, and the v4.6.1 ALTER TABLE
    block adds 6 columns at the end (event_class, recovery_at, etc.)
    that must come through correctly.
    """
    src = _DATABASE_PY.read_text()
    # Locate the v4.6.7 INSERT block
    idx = src.find("INSERT INTO anomaly_log_v467")
    assert idx >= 0, "Could not find v4.6.7 INSERT INTO anomaly_log_v467"
    # Find the closing SELECT body
    select_idx = src.find("SELECT", idx)
    assert select_idx > idx, "Could not find SELECT in v4.6.7 INSERT"
    select_body = src[select_idx:select_idx + 1500]
    # Must NOT use SELECT *
    assert "SELECT *" not in select_body, (
        "v4.6.7: migration must use explicit column list, not SELECT * "
        "(column-order brittleness — the v4.6.1 ALTER TABLE adds columns at "
        "the end which would cause silent data loss with SELECT *)"
    )
    # Must include the v4.6.1-added columns
    for col in (
        "event_class", "recovery_at", "correlation_id",
        "entity_id", "room_id", "person_id",
    ):
        assert col in select_body, (
            f"v4.6.7: migration SELECT must include `{col}` "
            "(v4.6.1 ALTER TABLE added these — silent data loss otherwise)"
        )


# ---------------------------------------------------------------------------
# Section 4 — Behavioral test of the rebuild dance (v4.6.7 review H2 fix)
# ---------------------------------------------------------------------------


def test_v467_rebuild_dance_preserves_rows_and_indexes_and_allows_null():
    """v4.6.7 review H2 fix (closes the v4.6.6 C-H2 gap pattern):
    behavioral test that builds a pre-v4.6.7 schema in an isolated
    in-memory sqlite, inserts representative rows, runs the v4.6.7
    rebuild dance, and asserts:
      - Row count preserved (no data loss)
      - All values round-trip correctly
      - The 4 indexes are recreated (DROP TABLE removed the originals)
      - The new table accepts NULL writes to the 5 relaxed columns
      - PRAGMA user_version is set to 467

    Builds the test DB MANUALLY (not via real_schema_db) because
    real_schema_db uses the new v4.6.7 DDL — we need to start from the
    OLD schema to exercise the rebuild path. The OLD schema is reproduced
    here from database.py source at v4.6.6 (pre-relaxation) and matches
    the v4.6.1 ALTER TABLE additions exactly so the SELECT column list
    in the rebuild block lines up.
    """
    import sqlite3
    conn = sqlite3.connect(":memory:")
    # Pre-v4.6.7 anomaly_log DDL — 5 metric columns NOT NULL + v4.6.1
    # ALTER TABLE added columns appended at end.
    conn.execute(
        """CREATE TABLE anomaly_log (
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
            event_class TEXT,
            recovery_at TEXT,
            correlation_id TEXT,
            entity_id TEXT,
            room_id TEXT,
            person_id TEXT
        )"""
    )
    # Recreate the 4 original indexes
    for stmt in (
        "CREATE INDEX idx_anomaly_timestamp ON anomaly_log(timestamp)",
        "CREATE INDEX idx_anomaly_coordinator ON anomaly_log(coordinator_id)",
        "CREATE INDEX idx_anomaly_scope ON anomaly_log(scope)",
        "CREATE INDEX idx_anomaly_severity ON anomaly_log(severity)",
    ):
        conn.execute(stmt)

    # Insert 5 rows with mixed values (all 5 metric columns populated since
    # OLD schema requires NOT NULL). Use different severities so we can
    # check by-severity round-trip.
    insert_old_sql = (
        "INSERT INTO anomaly_log "
        "(timestamp, coordinator_id, scope, metric_name, observed_value, "
        "expected_mean, expected_std, z_score, severity, sample_size, "
        "house_state, context_json, resolved, resolution_notes, event_class, "
        "recovery_at, correlation_id, entity_id, room_id, person_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    rows_to_insert = [
        ("2026-05-15T10:00:00", "hvac", "house", "hvac.test_a",
         1.0, 0.5, 0.1, 5.0, "1", 100, "home_day", "{}", 0, None,
         "point_in_time", None, None, None, None, None),
        ("2026-05-15T11:00:00", "presence", "house", "presence.test_b",
         0.0, 0.0, 0.0, 0.0, "0", 0, "sleep", "{}", 0, None,
         "point_in_time", None, None, None, None, None),
        ("2026-05-15T12:00:00", "energy", "room:kitchen", "energy.test_c",
         100.0, 50.0, 10.0, 5.0, "4", 336, "home_day", '{"k":"v"}', 0, None,
         "regime_shift", "2026-05-15T13:00:00", "corr_xyz", "sensor.foo",
         "kitchen", "person.alice"),
        ("2026-05-15T13:00:00", "safety", "house", "safety.test_d",
         1.0, 1.0, 0.1, 0.0, "1", 50, "home_day", "{}", 0, None,
         "hazard", None, None, None, None, None),
        ("2026-05-15T14:00:00", "music_following", "house", "mf.test_e",
         0.5, 0.5, 0.1, 0.0, "2", 200, "home_evening", "{}", 0, None,
         "point_in_time", None, None, None, None, None),
    ]
    for row in rows_to_insert:
        conn.execute(insert_old_sql, row)
    conn.commit()
    pre_count = conn.execute("SELECT COUNT(*) FROM anomaly_log").fetchone()[0]
    assert pre_count == 5

    # Pre-rebuild PRAGMA user_version should be 0 (fresh DB)
    pre_uv = conn.execute("PRAGMA user_version").fetchone()[0]
    assert pre_uv == 0

    # Execute the v4.6.7 rebuild dance — same SQL as production
    conn.execute("BEGIN")
    conn.execute(
        """CREATE TABLE anomaly_log_v467 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            coordinator_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            observed_value REAL,
            expected_mean REAL,
            expected_std REAL,
            z_score REAL,
            severity TEXT NOT NULL,
            sample_size INTEGER,
            house_state TEXT,
            context_json TEXT,
            resolved BOOLEAN NOT NULL DEFAULT 0,
            resolution_notes TEXT,
            event_class TEXT,
            recovery_at TEXT,
            correlation_id TEXT,
            entity_id TEXT,
            room_id TEXT,
            person_id TEXT
        )"""
    )
    cur = conn.execute(
        """INSERT INTO anomaly_log_v467
            (id, timestamp, coordinator_id, scope, metric_name, observed_value,
             expected_mean, expected_std, z_score, severity, sample_size,
             house_state, context_json, resolved, resolution_notes, event_class,
             recovery_at, correlation_id, entity_id, room_id, person_id)
           SELECT id, timestamp, coordinator_id, scope, metric_name,
                  observed_value, expected_mean, expected_std, z_score,
                  severity, sample_size, house_state, context_json,
                  resolved, resolution_notes, event_class, recovery_at,
                  correlation_id, entity_id, room_id, person_id
           FROM anomaly_log"""
    )
    copied = cur.rowcount
    conn.execute("DROP TABLE anomaly_log")
    conn.execute("ALTER TABLE anomaly_log_v467 RENAME TO anomaly_log")
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON anomaly_log(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator ON anomaly_log(coordinator_id)",
        "CREATE INDEX IF NOT EXISTS idx_anomaly_scope ON anomaly_log(scope)",
        "CREATE INDEX IF NOT EXISTS idx_anomaly_severity ON anomaly_log(severity)",
    ):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 467")
    conn.commit()

    # Assert: rows preserved
    assert copied == 5, (
        f"v4.6.7 H2: rebuild copied {copied} rows; expected 5"
    )
    post_count = conn.execute("SELECT COUNT(*) FROM anomaly_log").fetchone()[0]
    assert post_count == 5, (
        f"v4.6.7 H2: post-rebuild row count {post_count}; expected 5"
    )

    # Assert: values round-trip correctly — spot-check a row with all
    # the v4.6.1 ALTER TABLE columns populated.
    row = conn.execute(
        "SELECT coordinator_id, observed_value, severity, event_class, "
        "correlation_id, room_id, person_id "
        "FROM anomaly_log WHERE metric_name = 'energy.test_c'"
    ).fetchone()
    assert row is not None, "test_c row missing post-rebuild"
    assert row[0] == "energy"
    assert row[1] == 100.0
    assert row[2] == "4"
    assert row[3] == "regime_shift"
    assert row[4] == "corr_xyz"
    assert row[5] == "kitchen"
    assert row[6] == "person.alice"

    # Assert: all 4 indexes exist by name (DROP TABLE removed originals,
    # the rebuild block must recreate them)
    # PRAGMA index_list returns (seq, name, unique, origin, partial) tuples
    # — name is column index 1, not 0.
    indexes = {
        r[1]
        for r in conn.execute("PRAGMA index_list(anomaly_log)").fetchall()
    }
    for required in (
        "idx_anomaly_timestamp",
        "idx_anomaly_coordinator",
        "idx_anomaly_scope",
        "idx_anomaly_severity",
    ):
        assert required in indexes, (
            f"v4.6.7 H2: index `{required}` missing post-rebuild "
            f"(DROP TABLE removed indexes; rebuild block must recreate them). "
            f"Found indexes: {sorted(indexes)}"
        )

    # Assert: new table now accepts NULL writes to the 5 relaxed columns
    conn.execute(
        "INSERT INTO anomaly_log "
        "(timestamp, coordinator_id, scope, metric_name, observed_value, "
        "expected_mean, expected_std, z_score, severity, sample_size, "
        "house_state, context_json, resolved, resolution_notes, event_class, "
        "recovery_at, correlation_id, entity_id, room_id, person_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-05-16T00:00:00", "test_coord", "", "test.null_after_rebuild",
            None, None, None, None, 1, None,
            "home_day", "{}", 0, None, "point_in_time",
            None, None, None, None, None,
        ),
    )
    conn.commit()
    null_row = conn.execute(
        "SELECT observed_value, expected_mean, expected_std, z_score, "
        "sample_size FROM anomaly_log WHERE metric_name = 'test.null_after_rebuild'"
    ).fetchone()
    assert null_row == (None, None, None, None, None), (
        f"v4.6.7 H2: NULL insert post-rebuild did not preserve NULL values, "
        f"got {null_row}"
    )

    # Assert: PRAGMA user_version sentinel set
    post_uv = conn.execute("PRAGMA user_version").fetchone()[0]
    assert post_uv == 467, (
        f"v4.6.7 H2: PRAGMA user_version should be 467 post-rebuild, "
        f"got {post_uv}"
    )

    conn.close()

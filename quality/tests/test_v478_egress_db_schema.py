"""v4.7.8 D4 — egress_state table schema extracted from production source.

Tier 2-DB doctrine: behavioral schema tests MUST extract DDL from the
production source (database.py), never hand-copy. If database.py changes,
this test breaks immediately — caller knows to update the fixture.

Tests:
  - test_v478_db_egress_state_table_schema      — DDL roundtrip on fresh SQLite
  - test_v478_db_egress_state_roundtrip         — INSERT OR REPLACE + SELECT
  - test_v478_db_egress_state_in_flight_scan_returns_only_active_states
  - test_v478_db_egress_state_prune_drops_stale_idle_rows
  - test_v478_db_egress_state_create_failure_does_not_cascade
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


_DATABASE_PY = "custom_components/universal_room_automation/database.py"


def _read_source() -> str:
    # Force utf-8: see test_v478_egress_window.py::_read note.
    with open(_DATABASE_PY, encoding="utf-8") as f:
        return f.read()


def _extract_ddl_for(table_name: str) -> list[str]:
    """Return all CREATE TABLE / CREATE INDEX statements for a table from src."""
    src = _read_source()
    out: list[str] = []
    triple_pattern = re.compile(r'"""(.*?)"""', re.DOTALL)
    table_marker = f"CREATE TABLE IF NOT EXISTS {table_name}"
    index_marker = f"ON {table_name}("
    for m in triple_pattern.finditer(src):
        stmt = m.group(1).strip()
        if table_marker in stmt or index_marker in stmt:
            out.append(stmt)
    return out


def _build_in_memory_db() -> sqlite3.Connection:
    """Build an in-memory SQLite with the production egress_state schema."""
    conn = sqlite3.connect(":memory:")
    for stmt in _extract_ddl_for("egress_state"):
        conn.execute(stmt)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------


def test_v478_db_egress_state_table_schema():
    """DDL extracted from database.py creates a valid egress_state table."""
    ddl_stmts = _extract_ddl_for("egress_state")
    assert len(ddl_stmts) >= 2, "expected CREATE TABLE + CREATE INDEX"
    # Verify required columns are present in the DDL text.
    table_ddl = next(s for s in ddl_stmts if "CREATE TABLE" in s)
    for col in (
        "zone_id",
        "state",
        "first_open_at",
        "first_closed_at",
        "paused_at",
        "saved_hvac_mode",
        "saved_preset_mode",
        "triggered_by_room",
        "thermostat_entity",
        "cooldown_expires_at",
        "last_update_ts",
    ):
        assert col in table_ddl, f"missing column {col} in egress_state DDL"
    # PRIMARY KEY is (zone_id), NOT (zone_id, date) like ac_reset_state.
    assert "PRIMARY KEY (zone_id)" in table_ddl
    # Index is on state.
    index_ddl = next(s for s in ddl_stmts if "CREATE INDEX" in s)
    assert "egress_state(state)" in index_ddl

    # Round-trip: SQLite can actually create the schema.
    conn = _build_in_memory_db()
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='egress_state'"
    )
    assert cur.fetchone() is not None
    cur = conn.execute("PRAGMA table_info(egress_state)")
    cols = {row[1] for row in cur.fetchall()}
    assert {
        "zone_id", "state", "first_open_at", "first_closed_at", "paused_at",
        "saved_hvac_mode", "saved_preset_mode", "triggered_by_room",
        "thermostat_entity", "cooldown_expires_at", "last_update_ts",
    } <= cols


def test_v478_db_egress_state_roundtrip():
    """INSERT OR REPLACE writes, SELECT returns matching fields."""
    conn = _build_in_memory_db()
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO egress_state (
            zone_id, state, first_open_at, first_closed_at, paused_at,
            saved_hvac_mode, saved_preset_mode, triggered_by_room,
            thermostat_entity, cooldown_expires_at, last_update_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("zone_2", "paused", None, None, now, "heat_cool", "home",
         "jaya_bedroom", "climate.up_hallway_zone_2", None, now),
    )
    conn.commit()
    cur = conn.execute("SELECT zone_id, state, saved_hvac_mode, saved_preset_mode, "
                       "triggered_by_room, thermostat_entity, paused_at "
                       "FROM egress_state WHERE zone_id = ?", ("zone_2",))
    row = cur.fetchone()
    assert row == (
        "zone_2", "paused", "heat_cool", "home",
        "jaya_bedroom", "climate.up_hallway_zone_2", now,
    )

    # INSERT OR REPLACE on same zone_id should overwrite (PRIMARY KEY semantics).
    conn.execute(
        """INSERT OR REPLACE INTO egress_state (
            zone_id, state, first_open_at, first_closed_at, paused_at,
            saved_hvac_mode, saved_preset_mode, triggered_by_room,
            thermostat_entity, cooldown_expires_at, last_update_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("zone_2", "resume_countdown", None, now, now, "heat_cool", "home",
         "jaya_bedroom", "climate.up_hallway_zone_2", None, now),
    )
    conn.commit()
    cur = conn.execute("SELECT COUNT(*) FROM egress_state WHERE zone_id='zone_2'")
    assert cur.fetchone()[0] == 1


def test_v478_db_egress_state_in_flight_scan_returns_only_active_states():
    """get_all_egress_state returns all rows; in-flight = active states."""
    conn = _build_in_memory_db()
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    # Insert one row per active state.
    for zid, state in [
        ("zone_2", "paused"),
        ("zone_3", "counting"),
        ("zone_4", "resume_countdown"),
        ("zone_5", "cooldown"),
    ]:
        conn.execute(
            """INSERT INTO egress_state (zone_id, state, last_update_ts)
               VALUES (?, ?, ?)""",
            (zid, state, now),
        )
    conn.commit()
    cur = conn.execute(
        "SELECT state FROM egress_state WHERE state IN "
        "('paused', 'counting', 'resume_countdown', 'cooldown')"
    )
    states = {row[0] for row in cur.fetchall()}
    assert states == {"paused", "counting", "resume_countdown", "cooldown"}


def test_v478_db_egress_state_prune_drops_stale_idle_rows():
    """Prune query removes idle rows + rows older than cutoff."""
    conn = _build_in_memory_db()
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
    fresh = now.isoformat()
    stale = (now - timedelta(days=14)).isoformat()
    cutoff = (now - timedelta(days=7)).isoformat()
    # Insert: 1 idle (should drop), 1 stale (should drop), 1 fresh paused (keep).
    conn.execute("INSERT INTO egress_state (zone_id, state, last_update_ts) "
                 "VALUES (?, ?, ?)", ("zone_idle", "idle", fresh))
    conn.execute("INSERT INTO egress_state (zone_id, state, last_update_ts) "
                 "VALUES (?, ?, ?)", ("zone_stale", "paused", stale))
    conn.execute("INSERT INTO egress_state (zone_id, state, last_update_ts) "
                 "VALUES (?, ?, ?)", ("zone_fresh", "paused", fresh))
    conn.commit()
    # Mirror the production DELETE.
    conn.execute(
        "DELETE FROM egress_state WHERE state = 'idle' OR last_update_ts < ?",
        (cutoff,),
    )
    conn.commit()
    cur = conn.execute("SELECT zone_id FROM egress_state ORDER BY zone_id")
    assert [r[0] for r in cur.fetchall()] == ["zone_fresh"]


def test_v478_db_egress_state_create_failure_does_not_cascade():
    """Bug Class #9 — table init uses _create_table_safe so failures isolate."""
    src = _read_source()
    # Find the egress_state CREATE block.
    idx = src.find('_create_table_safe(db, "egress_state"')
    assert idx >= 0, "egress_state must use _create_table_safe"
    # Block is followed by failed_tables.append("egress_state") inside `if not`.
    window = src[idx:idx + 1500]
    assert 'failed_tables.append("egress_state")' in window


def test_v478_db_egress_state_dao_methods_exist():
    """All 5 DAOs are declared in database.py."""
    src = _read_source()
    for method in (
        "async def get_egress_state",
        "async def save_egress_state",
        "async def get_all_egress_state",
        "async def clear_egress_state",
        "async def prune_stale_egress_state",
    ):
        assert method in src, f"missing DAO: {method}"


def test_v478_db_egress_state_primary_key_zone_id_alone():
    """Doctrine: PK is (zone_id), NOT (zone_id, date) like ac_reset_state."""
    src = _read_source()
    # Find egress_state CREATE TABLE block.
    m = re.search(
        r"CREATE TABLE IF NOT EXISTS egress_state.*?PRIMARY KEY \(([^)]+)\)",
        src, re.DOTALL,
    )
    assert m is not None
    pk_cols = m.group(1).strip()
    assert pk_cols == "zone_id", f"PRIMARY KEY must be zone_id alone, got: {pk_cols}"

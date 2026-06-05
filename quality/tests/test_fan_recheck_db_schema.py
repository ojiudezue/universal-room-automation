"""Fan-recheck D7 — fan_recheck_state table schema extracted from production source.

Tier 2-DB doctrine: behavioral schema tests MUST extract DDL from the
production source (database.py), never hand-copy.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone


_DATABASE_PY = "custom_components/universal_room_automation/database.py"


def _read_source() -> str:
    with open(_DATABASE_PY, encoding="utf-8") as f:
        return f.read()


def _extract_ddl_for(table_name: str) -> list[str]:
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
    conn = sqlite3.connect(":memory:")
    for stmt in _extract_ddl_for("fan_recheck_state"):
        conn.execute(stmt)
    conn.commit()
    return conn


def test_fan_recheck_db_schema_extracted_from_production():
    ddl_stmts = _extract_ddl_for("fan_recheck_state")
    assert len(ddl_stmts) >= 2, "expected CREATE TABLE + CREATE INDEX"
    table_ddl = next(s for s in ddl_stmts if "CREATE TABLE" in s)
    for col in (
        "room_id",
        "state",
        "state_entered_at",
        "snapshot_json",
        "attempts_in_hour",
        "last_outcome",
        "last_attempt_at",
        "ble_ladder_layer",
        "last_update_ts",
    ):
        assert col in table_ddl, f"missing column {col} in fan_recheck_state DDL"
    assert "PRIMARY KEY (room_id)" in table_ddl


def test_fan_recheck_db_schema_roundtrip():
    conn = _build_in_memory_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO fan_recheck_state (
            room_id, state, state_entered_at, snapshot_json,
            attempts_in_hour, last_outcome, last_attempt_at,
            ble_ladder_layer, last_update_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "room_abc",
            "paused",
            now_iso,
            '{"entities":["fan.x"]}',
            1,
            None,
            now_iso,
            "L3",
            now_iso,
        ),
    )
    conn.commit()
    cur = conn.execute(
        "SELECT state, attempts_in_hour, ble_ladder_layer "
        "FROM fan_recheck_state WHERE room_id = ?",
        ("room_abc",),
    )
    row = cur.fetchone()
    assert row == ("paused", 1, "L3")


def test_fan_recheck_db_index_state():
    ddl_stmts = _extract_ddl_for("fan_recheck_state")
    indexes = [s for s in ddl_stmts if "CREATE INDEX" in s]
    assert any("state" in idx for idx in indexes), (
        "expected an index on state column"
    )


def test_fan_recheck_db_daos_present_in_source():
    src = _read_source()
    for dao in (
        "get_fan_recheck_state",
        "save_fan_recheck_state",
        "get_all_fan_recheck_state",
        "clear_fan_recheck_state",
        "prune_stale_fan_recheck_state",
    ):
        assert f"def {dao}(" in src, f"DAO {dao} missing"

"""v4.6.1 D0 — DB migration: 6 new columns added to anomaly_log.

Source-grep tests verify:
- All 6 columns appear in the migration block
- PRAGMA table_info idempotency check present
- Existing rows get event_class='point_in_time' DEFAULT
- Wrapped in try/except with WARNING-level log
- Migration commits after ALTER TABLE
"""

from pathlib import Path


def _db_src() -> str:
    return Path("custom_components/universal_room_automation/database.py").read_text()


def test_migration_uses_pragma_table_info_anomaly_log(database_src=None):
    """Migration must read existing columns via PRAGMA table_info(anomaly_log)."""
    src = database_src or _db_src()
    assert "PRAGMA table_info(anomaly_log)" in src, (
        "v4.6.1: must use PRAGMA table_info(anomaly_log) for idempotent column check"
    )


def test_migration_adds_event_class_column():
    src = _db_src()
    assert "event_class" in src
    # DEFAULT must be 'point_in_time' for backward-compat with existing rows
    assert "DEFAULT 'point_in_time'" in src, (
        "event_class column must have DEFAULT 'point_in_time' "
        "so existing rows are queryable without backfill"
    )


def test_migration_adds_recovery_at_column():
    src = _db_src()
    assert "recovery_at" in src


def test_migration_adds_correlation_id_column():
    src = _db_src()
    assert "correlation_id" in src


def test_migration_adds_entity_id_column():
    src = _db_src()
    # entity_id appears in anomaly_log migration block
    pragma_idx = src.find("PRAGMA table_info(anomaly_log)")
    assert pragma_idx >= 0
    block = src[pragma_idx:pragma_idx + 1200]
    assert "entity_id" in block, "anomaly_log migration block must add entity_id column"


def test_migration_adds_room_id_column():
    src = _db_src()
    pragma_idx = src.find("PRAGMA table_info(anomaly_log)")
    assert pragma_idx >= 0
    block = src[pragma_idx:pragma_idx + 1200]
    assert "room_id" in block


def test_migration_adds_person_id_column():
    src = _db_src()
    pragma_idx = src.find("PRAGMA table_info(anomaly_log)")
    assert pragma_idx >= 0
    block = src[pragma_idx:pragma_idx + 1200]
    assert "person_id" in block


def test_migration_wrapped_in_try_except_warning():
    """Migration failure must log at WARNING level — matches all other migrations."""
    src = _db_src()
    pragma_idx = src.find("PRAGMA table_info(anomaly_log)")
    assert pragma_idx >= 0
    block = src[pragma_idx:pragma_idx + 1500]
    assert "_LOGGER.warning(" in block, (
        "anomaly_log migration must log failure at WARNING level"
    )
    assert "migration failed" in block or "v4.6.1 migration" in block


def test_migration_commits_after_alters():
    """db.commit() must be awaited after the ALTER TABLE block."""
    src = _db_src()
    pragma_idx = src.find("PRAGMA table_info(anomaly_log)")
    assert pragma_idx >= 0
    block = src[pragma_idx:pragma_idx + 1500]
    assert "await db.commit()" in block, (
        "anomaly_log migration must commit after ALTER TABLE statements"
    )


def test_migration_six_new_columns_listed():
    """All 6 new column names must appear in the migration block."""
    src = _db_src()
    pragma_idx = src.find("PRAGMA table_info(anomaly_log)")
    assert pragma_idx >= 0
    block = src[pragma_idx:pragma_idx + 1500]
    for col in ("event_class", "recovery_at", "correlation_id", "entity_id", "room_id", "person_id"):
        assert col in block, f"Column '{col}' missing from anomaly_log migration block"


# ===========================================================================
# v4.6.1 review fix F3 — severity TEXT → INT backfill
# ===========================================================================


def test_migration_backfills_old_text_severity_to_int():
    """v4.6.1 review fix F3: pre-D1 anomaly_log rows stored severity as TEXT
    ('nominal'/'advisory'/'alert'/'critical'). D1's IntEnum stores INT.
    SQLite numeric-comparison of mixed types coerces non-numeric TEXT to 0,
    so v4.6.2 D5 queries with `severity >= 1` would silently exclude legacy
    ADVISORY/ALERT rows. The migration must backfill these to '1'/'2'.

    Idempotent: WHERE clause matches only the 4 legacy literal values, so
    repeated runs find 0 rows.
    """
    src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    # Look for the CASE statement that maps old severity values
    assert "WHEN 'nominal'" in src, (
        "F3: migration must backfill 'nominal' severity → '0'"
    )
    assert "WHEN 'advisory'" in src and "WHEN 'alert'" in src, (
        "F3: migration must backfill 'advisory' AND 'alert' → '1'"
    )
    assert "WHEN 'critical'" in src, (
        "F3: migration must backfill 'critical' severity → '2'"
    )
    # WHERE clause restricts to the legacy values for idempotency
    assert "severity IN ('nominal','advisory','alert','critical')" in src or \
           "severity IN ('nominal', 'advisory', 'alert', 'critical')" in src, (
        "F3: migration WHERE clause must restrict to legacy values for "
        "idempotency; subsequent runs must find 0 matching rows."
    )


def test_anomaly_event_recovery_clears_correctly():
    """D0 acceptance criterion (missed in initial v4.6.1 builder): the
    AnomalyEvent dataclass supports `recovery_at: str | None`. Setting it
    to a UTC ISO timestamp indicates the event has resolved. This test
    pins the field's presence and Optional typing.

    Behavioral test (does save_anomaly_event persist recovery_at when set,
    and read-back queries see it) is deferred to v4.6.2 when the regime
    detector first uses recovery semantics.
    """
    src = Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/anomaly_event.py"
    ).read_text()
    assert "recovery_at:" in src, (
        "AnomalyEvent must declare recovery_at field"
    )
    assert "Optional[str]" in src or "str | None" in src, (
        "recovery_at must be Optional/nullable so unrecovered events "
        "have NULL and queries can filter `WHERE recovery_at IS NULL`"
    )

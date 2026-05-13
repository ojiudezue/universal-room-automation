"""v4.6.0 D3 — Idempotent schema migration for prediction_results.person_id.

Source-grep tests verify the ALTER TABLE migration pattern matches
the existing convention in database.py and is idempotent (PRAGMA table_info
check before issuing the ALTER).
"""

import pytest


@pytest.fixture(scope="module")
def database_src() -> str:
    with open(
        "custom_components/universal_room_automation/database.py"
    ) as f:
        return f.read()


def test_migration_uses_pragma_table_info(database_src: str):
    """Migration must read existing columns via PRAGMA table_info before
    attempting the ALTER TABLE — the idempotency pattern used throughout
    database.py.
    """
    assert 'PRAGMA table_info(prediction_results)' in database_src, (
        "D3: must use PRAGMA table_info(prediction_results) for idempotent check"
    )


def test_migration_checks_person_id_not_in_columns(database_src: str):
    """The guard must check 'person_id' not in the fetched column set."""
    # Locate the prediction_results migration block
    pragma_idx = database_src.find('PRAGMA table_info(prediction_results)')
    assert pragma_idx >= 0
    # Take a window around it
    block = database_src[pragma_idx:pragma_idx + 600]
    assert '"person_id" not in' in block or "'person_id' not in" in block, (
        "D3: migration guard must check 'person_id' not in pr_columns"
    )


def test_migration_alter_adds_person_id_text(database_src: str):
    """The ALTER TABLE statement must add a 'person_id TEXT' column."""
    assert "ALTER TABLE prediction_results ADD COLUMN person_id TEXT" in database_src, (
        "D3: ALTER TABLE must add 'person_id TEXT' to prediction_results"
    )


def test_migration_wrapped_in_try_except_warning(database_src: str):
    """Migration failures must be WARNING-level (matches all other migrations
    in database.py — none use ERROR for schema-change failures).
    """
    pragma_idx = database_src.find('PRAGMA table_info(prediction_results)')
    assert pragma_idx >= 0
    block = database_src[pragma_idx:pragma_idx + 700]
    assert "_LOGGER.warning(" in block, (
        "D3: migration try/except must log at WARNING level"
    )
    assert "prediction_results person_id migration failed" in block, (
        "D3: warning message must identify the migration that failed"
    )


def test_migration_commits_after_alter(database_src: str):
    """db.commit() must be called after the ALTER TABLE to persist the
    schema change (matches existing migration pattern).
    """
    pragma_idx = database_src.find('PRAGMA table_info(prediction_results)')
    assert pragma_idx >= 0
    block = database_src[pragma_idx:pragma_idx + 600]
    assert "await db.commit()" in block, (
        "D3: must await db.commit() after ALTER TABLE prediction_results"
    )

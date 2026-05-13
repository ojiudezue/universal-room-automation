"""v4.6.2 D4 — regime_cell_state table schema migration tests.

Source-grep tests verify:
- Table DDL exists with correct columns
- PRIMARY KEY (person_id, time_bin, day_type)
- Migration uses PRAGMA table_info (idempotency)
- upsert DAO uses INSERT OR REPLACE
- get DAO uses _db_read() not _db()
"""

from pathlib import Path


def _db_src() -> str:
    return Path("custom_components/universal_room_automation/database.py").read_text()


def test_regime_cell_state_table_defined():
    src = _db_src()
    assert "regime_cell_state" in src, (
        "database.py must define regime_cell_state table"
    )


def test_regime_cell_state_has_required_columns():
    src = _db_src()
    idx = src.find("regime_cell_state")
    assert idx >= 0
    # Find the CREATE TABLE block
    create_idx = src.find("CREATE TABLE IF NOT EXISTS regime_cell_state", idx - 200)
    if create_idx < 0:
        create_idx = src.find("regime_cell_state", idx)
    block = src[create_idx: create_idx + 600]
    for col in (
        "person_id",
        "time_bin",
        "day_type",
        "unacknowledged_consecutive",
        "last_evaluated_at",
        "last_magnitude_bucket",
    ):
        assert col in block, (
            f"regime_cell_state must declare column '{col}'"
        )


def test_regime_cell_state_primary_key():
    src = _db_src()
    idx = src.find("CREATE TABLE IF NOT EXISTS regime_cell_state")
    if idx < 0:
        idx = src.find("regime_cell_state")
    assert idx >= 0
    block = src[idx: idx + 600]
    assert "PRIMARY KEY" in block, (
        "regime_cell_state must declare a PRIMARY KEY"
    )
    # The composite PK must reference all three key columns
    pk_idx = block.find("PRIMARY KEY")
    pk_clause = block[pk_idx: pk_idx + 80]
    assert "person_id" in pk_clause and "time_bin" in pk_clause and "day_type" in pk_clause, (
        "PRIMARY KEY must be (person_id, time_bin, day_type)"
    )


def test_migration_uses_pragma_table_info_regime_cell_state():
    """Migration must use PRAGMA table_info(regime_cell_state) for idempotency."""
    src = _db_src()
    assert "PRAGMA table_info(regime_cell_state)" in src, (
        "Must use PRAGMA table_info(regime_cell_state) for idempotent migration"
    )


def test_migration_wrapped_in_try_except_warning():
    src = _db_src()
    idx = src.find("PRAGMA table_info(regime_cell_state)")
    assert idx >= 0
    # The WARNING log appears after the CREATE TABLE block; use a wider window
    block = src[max(0, idx - 200): idx + 1200]
    assert "_LOGGER.warning(" in block, (
        "regime_cell_state migration must log failure at WARNING level"
    )


def test_upsert_uses_insert_or_replace():
    src = _db_src()
    assert "async def upsert_regime_cell_state(" in src, (
        "upsert_regime_cell_state DAO must exist"
    )
    idx = src.find("async def upsert_regime_cell_state(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 1000]
    assert "INSERT OR REPLACE" in block, (
        "upsert_regime_cell_state must use INSERT OR REPLACE for idempotent upsert"
    )


def test_get_regime_cell_state_uses_db_read():
    """get_regime_cell_state must use _db_read() for WAL-concurrent access."""
    src = _db_src()
    assert "async def get_regime_cell_state(" in src, (
        "get_regime_cell_state DAO must exist"
    )
    idx = src.find("async def get_regime_cell_state(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 1000]
    assert "_db_read()" in block, (
        "get_regime_cell_state must use _db_read() not _db()"
    )


def test_upsert_regime_cell_state_commits():
    """upsert_regime_cell_state must await db.commit()."""
    src = _db_src()
    idx = src.find("async def upsert_regime_cell_state(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 1000]
    assert "await db.commit()" in block, (
        "upsert_regime_cell_state must commit the write"
    )

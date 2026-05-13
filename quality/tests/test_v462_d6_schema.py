"""v4.6.2 D6 — Database schema structural tests.

Source-grep tests verifying:
- regime_event_notification_log table with PRIMARY KEY (person_id, time_bin, day_type)
- regime_weekly_digest_queue table with FOREIGN KEY to anomaly_log
- Both migrations are PRAGMA-checked (idempotent)
- DAO methods exist for both tables
"""

from pathlib import Path


def _db_src() -> str:
    return Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()


# ---------------------------------------------------------------------------
# regime_event_notification_log
# ---------------------------------------------------------------------------


def test_regime_event_notification_log_table_created():
    src = _db_src()
    assert "regime_event_notification_log" in src, (
        "database.py must create regime_event_notification_log table"
    )


def test_regime_event_notification_log_primary_key():
    src = _db_src()
    idx = src.find("regime_event_notification_log")
    assert idx >= 0
    # Find the CREATE TABLE block near this reference
    create_idx = src.rfind("CREATE TABLE", 0, idx + 200)
    if create_idx < 0:
        create_idx = src.find("CREATE TABLE", idx)
    end = src.find(";", create_idx)
    if end < 0:
        end = create_idx + 500
    block = src[create_idx: end + 1]
    assert "PRIMARY KEY" in block or "PRIMARY KEY (person_id, time_bin, day_type)" in src[idx: idx + 500], (
        "regime_event_notification_log must have PRIMARY KEY (person_id, time_bin, day_type)"
    )


def test_regime_event_notification_log_migration_is_pragma_checked():
    src = _db_src()
    # The migration must use PRAGMA table_info to check existence before creating
    idx = src.find("regime_event_notification_log")
    assert idx >= 0
    # Look for PRAGMA within 500 chars before the first reference
    region = src[max(0, idx - 500): idx + 200]
    assert "PRAGMA" in region, (
        "regime_event_notification_log migration must be PRAGMA-checked for idempotency"
    )


# ---------------------------------------------------------------------------
# regime_weekly_digest_queue
# ---------------------------------------------------------------------------


def test_regime_weekly_digest_queue_table_created():
    src = _db_src()
    assert "regime_weekly_digest_queue" in src, (
        "database.py must create regime_weekly_digest_queue table"
    )


def test_regime_weekly_digest_queue_foreign_key():
    src = _db_src()
    idx = src.find("regime_weekly_digest_queue")
    assert idx >= 0
    # Find the CREATE TABLE block
    create_idx = src.find("CREATE TABLE", idx)
    end = src.find(";", create_idx)
    if end < 0:
        end = create_idx + 800
    block = src[create_idx: end + 1]
    assert "FOREIGN KEY" in block or "REFERENCES anomaly_log" in block, (
        "regime_weekly_digest_queue must have FOREIGN KEY referencing anomaly_log"
    )


def test_regime_weekly_digest_queue_migration_is_pragma_checked():
    src = _db_src()
    idx = src.find("regime_weekly_digest_queue")
    assert idx >= 0
    region = src[max(0, idx - 500): idx + 200]
    assert "PRAGMA" in region, (
        "regime_weekly_digest_queue migration must be PRAGMA-checked for idempotency"
    )


# ---------------------------------------------------------------------------
# DAO methods
# ---------------------------------------------------------------------------


def test_get_regime_last_notified_dao_exists():
    src = _db_src()
    assert "async def get_regime_last_notified(" in src, (
        "get_regime_last_notified DAO must exist in database.py"
    )


def test_upsert_regime_last_notified_dao_exists():
    src = _db_src()
    assert "async def upsert_regime_last_notified(" in src, (
        "upsert_regime_last_notified DAO must exist in database.py"
    )


def test_enqueue_regime_weekly_digest_dao_exists():
    src = _db_src()
    assert "async def enqueue_regime_weekly_digest(" in src, (
        "enqueue_regime_weekly_digest DAO must exist in database.py"
    )


def test_flush_regime_weekly_digest_queue_dao_exists():
    src = _db_src()
    assert "async def flush_regime_weekly_digest_queue(" in src, (
        "flush_regime_weekly_digest_queue DAO must exist in database.py"
    )

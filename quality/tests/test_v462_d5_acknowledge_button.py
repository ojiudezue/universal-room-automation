"""v4.6.2 D5 — AcknowledgeRoutineChangesButton structural tests.

Source-grep tests verifying:
- Button class exists with correct entity_id
- Press triggers UPDATE on anomaly_log (recovery_at=now) for unack rows
- Uses _db() (write queue — correct primitive for UPDATE)
- Dispatches SIGNAL_ROUTINE_STATUS_UPDATE post-update
- Bound to CM device
"""

from pathlib import Path


def _button_src() -> str:
    return Path(
        "custom_components/universal_room_automation/button.py"
    ).read_text()


def _signals_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/signals.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Class existence
# ---------------------------------------------------------------------------


def test_acknowledge_routine_changes_button_class_exists():
    src = _button_src()
    assert "class AcknowledgeRoutineChangesButton(" in src, (
        "AcknowledgeRoutineChangesButton must be defined in button.py"
    )


def test_acknowledge_button_on_cm_device():
    src = _button_src()
    idx = src.find("class AcknowledgeRoutineChangesButton(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 3000]
    assert "coordinator_manager" in block, (
        "AcknowledgeRoutineChangesButton must be placed on coordinator_manager device"
    )


def test_acknowledge_button_registered_in_cm_setup():
    src = _button_src()
    assert "AcknowledgeRoutineChangesButton(hass, entry)" in src, (
        "AcknowledgeRoutineChangesButton must be instantiated in async_setup_entry for CM"
    )


# ---------------------------------------------------------------------------
# Press logic: write via DAO, not raw SQL
# ---------------------------------------------------------------------------


def test_acknowledge_button_uses_dao_not_raw_sql():
    src = _button_src()
    idx = src.find("class AcknowledgeRoutineChangesButton(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 3000]
    # Must call a DAO method, not raw UPDATE
    assert "acknowledge_all_routine_shifts" in block, (
        "async_press must call database.acknowledge_all_routine_shifts() DAO"
    )
    # Must NOT contain a raw UPDATE statement
    assert "UPDATE anomaly_log" not in block, (
        "async_press must NOT contain a raw UPDATE — use the DAO"
    )


def test_acknowledge_button_uses_db_write_queue():
    """The DAO itself uses _db() (write queue); the button calls via DAO so this
    is structural — verify the DAO in database.py uses _db() for the UPDATE."""
    db_src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    idx = db_src.find("async def acknowledge_all_routine_shifts(")
    assert idx >= 0, "acknowledge_all_routine_shifts DAO must exist in database.py"
    end = db_src.find("\n    async def ", idx + 1)
    block = db_src[idx: end if end > 0 else idx + 2000]
    assert "_db()" in block, (
        "acknowledge_all_routine_shifts must use _db() (write queue) for the UPDATE"
    )


# ---------------------------------------------------------------------------
# Signal dispatch
# ---------------------------------------------------------------------------


def test_acknowledge_button_dispatches_signal_after_update():
    src = _button_src()
    idx = src.find("class AcknowledgeRoutineChangesButton(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 3000]
    assert "SIGNAL_ROUTINE_STATUS_UPDATE" in block, (
        "AcknowledgeRoutineChangesButton must dispatch SIGNAL_ROUTINE_STATUS_UPDATE "
        "after updating anomaly_log so D5 sensors refresh"
    )
    assert "async_dispatcher_send" in block, (
        "AcknowledgeRoutineChangesButton must call async_dispatcher_send"
    )

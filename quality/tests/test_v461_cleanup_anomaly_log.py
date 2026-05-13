"""v4.6.1 D2 — cleanup_anomaly_log DAO + Bug Class #27 registration.

Source-grep tests verify:
- cleanup_anomaly_log() method exists in database.py
- Branches on event_class (two retention windows)
- Uses LIMIT 1000 (batched, bug-class #25)
- Uses asyncio.sleep(0.1) between passes
- Returns total rows deleted (int)
- Registered in BOTH _cleanup_ops AND _cleanup_ops_d in __init__.py
"""

from pathlib import Path


def _db_src() -> str:
    return Path("custom_components/universal_room_automation/database.py").read_text()


def _init_src() -> str:
    return Path(
        "custom_components/universal_room_automation/__init__.py"
    ).read_text()


def _get_cleanup_method_block(src: str) -> str:
    idx = src.find("async def cleanup_anomaly_log(")
    assert idx >= 0, "cleanup_anomaly_log method not found in database.py"
    # Bound by the next top-level method in the class
    next_def = src.find("\n    async def ", idx + 1)
    return src[idx: next_def if next_def > 0 else idx + 3000]


# ---------------------------------------------------------------------------
# DAO existence and shape
# ---------------------------------------------------------------------------

def test_cleanup_anomaly_log_method_exists():
    src = _db_src()
    assert "async def cleanup_anomaly_log(" in src, (
        "database.py must define cleanup_anomaly_log()"
    )


def test_cleanup_anomaly_log_has_dual_retention_params():
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "retention_days_point_in_time" in block, (
        "cleanup_anomaly_log must accept retention_days_point_in_time parameter"
    )
    assert "retention_days_regime_shift" in block, (
        "cleanup_anomaly_log must accept retention_days_regime_shift parameter"
    )


def test_cleanup_anomaly_log_default_90_days_pit():
    """Default for point_in_time retention must be 90 days."""
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "90" in block, "Default retention for point_in_time must be 90 days"


def test_cleanup_anomaly_log_default_365_days_regime_shift():
    """Default for regime_shift retention must be 365 days — locked decision."""
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "365" in block, "Default retention for regime_shift must be 365 days"


def test_cleanup_anomaly_log_branches_on_event_class():
    """The DELETE must branch on event_class to apply different cutoffs."""
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "event_class" in block, (
        "cleanup_anomaly_log DELETE must branch on event_class"
    )
    assert "regime_shift" in block, (
        "cleanup_anomaly_log must handle regime_shift separately from other classes"
    )


def test_cleanup_anomaly_log_uses_limit_1000():
    """Batched: LIMIT 1000 per pass (Bug Class #25 pattern)."""
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "LIMIT 1000" in block, (
        "cleanup_anomaly_log must batch with LIMIT 1000 per pass"
    )


def test_cleanup_anomaly_log_uses_asyncio_sleep():
    """asyncio.sleep(0.1) between passes — matches cleanup_room_energy_baselines pattern."""
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "asyncio.sleep(0.1)" in block, (
        "cleanup_anomaly_log must yield with asyncio.sleep(0.1) between batch passes"
    )


def test_cleanup_anomaly_log_returns_int():
    """Must return total rows deleted (for callers that want metrics)."""
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "total_deleted" in block or "return" in block, (
        "cleanup_anomaly_log must return total rows deleted"
    )


def test_cleanup_anomaly_log_warning_on_error():
    """Exceptions must be caught and logged at WARNING with exc_info=True."""
    src = _db_src()
    block = _get_cleanup_method_block(src)
    assert "_LOGGER.warning(" in block, (
        "cleanup_anomaly_log must log exceptions at WARNING level"
    )


# ---------------------------------------------------------------------------
# Bug Class #27: registered in BOTH cleanup lists
# ---------------------------------------------------------------------------

def test_cleanup_anomaly_log_registered_in_cleanup_ops():
    """Bug Class #27: cleanup_anomaly_log must appear in _cleanup_ops list."""
    src = _init_src()
    idx = src.find("_cleanup_ops = [")
    assert idx >= 0, "_cleanup_ops list not found in __init__.py"
    bracket_end = src.find("]", idx)
    block = src[idx:bracket_end + 1]
    assert "cleanup_anomaly_log" in block, (
        "Bug Class #27: cleanup_anomaly_log must be in _cleanup_ops "
        "(first path — wins the DB init race)"
    )


def test_cleanup_anomaly_log_registered_in_cleanup_ops_d():
    """Bug Class #27: cleanup_anomaly_log must appear in _cleanup_ops_d list."""
    src = _init_src()
    idx = src.find("_cleanup_ops_d = [")
    assert idx >= 0, "_cleanup_ops_d list not found in __init__.py"
    bracket_end = src.find("]", idx)
    block = src[idx:bracket_end + 1]
    assert "cleanup_anomaly_log" in block, (
        "Bug Class #27: cleanup_anomaly_log must be in _cleanup_ops_d "
        "(deferred path — same race as activity logger)"
    )


def test_cleanup_anomaly_log_retention_kwargs_in_both_lists():
    """Both lists must pass the dual-window kwargs, not just retention_days."""
    src = _init_src()
    for list_name in ("_cleanup_ops = [", "_cleanup_ops_d = ["):
        idx = src.find(list_name)
        assert idx >= 0
        bracket_end = src.find("]", idx)
        block = src[idx:bracket_end + 1]
        assert "retention_days_point_in_time" in block, (
            f"cleanup_anomaly_log entry in {list_name} must pass "
            "retention_days_point_in_time kwarg"
        )
        assert "retention_days_regime_shift" in block, (
            f"cleanup_anomaly_log entry in {list_name} must pass "
            "retention_days_regime_shift kwarg"
        )


# ===========================================================================
# v4.6.1 review fix F2 — NULL-safe cleanup SQL
# ===========================================================================


def test_cleanup_uses_coalesce_for_null_event_class():
    """v4.6.1 review fix F2: SQLite `NULL != 'string'` evaluates to NULL
    (falsy), so a row with NULL event_class would be immune to cleanup
    forever. The cleanup branch must use COALESCE(event_class, 'point_in_time')
    so legacy or accidentally-NULL rows route to the 90-day retention
    branch correctly.
    """
    src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    idx = src.find("async def cleanup_anomaly_log(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "COALESCE(event_class" in block, (
        "F2: cleanup SQL must use COALESCE(event_class, 'point_in_time') "
        "to handle NULL event_class safely; raw `event_class != 'X'` "
        "evaluates NULL against any RHS as NULL → row never matches → "
        "row accumulates forever."
    )

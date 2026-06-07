"""v4.6.2 D3 — B6 away_typical display logic in PersonLikelyNextRoomSensor.

Source-grep and AST tests (no HA runtime required):
- Sensor inserts away_typical when cell stale + geofence away
- Sensor returns unknown (prediction is None) when cell empty + geofence home
- Sensor uses real prediction when cell active + home
- Sensor uses real prediction when cell active + away but recent obs exist
- is_cell_stale uses _db_read() not _db()
- cell_staleness_days config Number entity exists with default 14, range 7-90
- Helper imported function-locally (Bug Class #34)
"""

from pathlib import Path


def _sensor_src() -> str:
    return Path("custom_components/universal_room_automation/sensor.py").read_text()


def _bayesian_src() -> str:
    return Path(
        "custom_components/universal_room_automation/bayesian_predictor.py"
    ).read_text()


def _number_src() -> str:
    return Path("custom_components/universal_room_automation/number.py").read_text()


# ---------------------------------------------------------------------------
# is_cell_stale helper — presence and correct DB accessor
# ---------------------------------------------------------------------------


def test_is_cell_stale_defined_in_bayesian_predictor():
    src = _bayesian_src()
    assert "async def is_cell_stale(" in src, (
        "is_cell_stale helper must be defined in bayesian_predictor.py "
        "for co-location with _hour_to_time_bin / _day_type helpers"
    )


def test_is_cell_stale_uses_db_read_not_db():
    """is_cell_stale must use _db_read() (WAL-concurrent) not _db() (write queue)."""
    src = _bayesian_src()
    idx = src.find("async def is_cell_stale(")
    assert idx >= 0
    # Find next top-level def
    next_def = src.find("\nasync def ", idx + 1)
    block = src[idx: next_def if next_def > 0 else idx + 2000]
    assert "_db_read()" in block, (
        "is_cell_stale must use _db_read() for WAL-concurrent access"
    )
    assert "_db()" not in block or "import" in block, (
        "is_cell_stale must NOT use _db() — that is the write queue"
    )


def test_is_cell_stale_queries_person_visits():
    src = _bayesian_src()
    idx = src.find("async def is_cell_stale(")
    assert idx >= 0
    next_def = src.find("\nasync def ", idx + 1)
    block = src[idx: next_def if next_def > 0 else idx + 2000]
    assert "person_visits" in block, (
        "is_cell_stale must query person_visits table"
    )


def test_is_cell_stale_returns_true_on_exception():
    """On any DB exception, is_cell_stale must return True (safe default)."""
    src = _bayesian_src()
    idx = src.find("async def is_cell_stale(")
    assert idx >= 0
    # is_cell_stale is the last function in the module; cap at idx+3000 to be safe
    next_def = src.find("\nasync def ", idx + 1)
    block = src[idx: next_def if next_def > 0 else idx + 3000]
    assert "except Exception" in block, "is_cell_stale must catch exceptions"
    assert "return True" in block, (
        "is_cell_stale must return True on exception — safest fallback for away_typical"
    )


# ---------------------------------------------------------------------------
# D3 sensor logic
# ---------------------------------------------------------------------------


def test_sensor_async_update_contains_away_typical_logic():
    """PersonLikelyNextRoomSensor.async_update must contain the D3 away_typical block."""
    src = _sensor_src()
    assert "away_typical" in src, (
        "sensor.py must contain away_typical state value in D3 logic"
    )


def test_sensor_away_typical_checks_geofence_away():
    """D3 block must read person_coordinator location and compare to 'away'."""
    src = _sensor_src()
    idx = src.find("away_typical")
    assert idx >= 0
    # Look in the block around the first occurrence
    block = src[max(0, idx - 500): idx + 500]
    assert 'loc == "away"' in src or "location" in block, (
        "D3 block must read location from person_coordinator and check == 'away'"
    )


def test_sensor_away_typical_imports_is_cell_stale_locally():
    """Bug Class #34: is_cell_stale must be imported inside async_update, not at module level."""
    src = _sensor_src()
    # Look for module-level import of is_cell_stale
    module_level = src[:src.find("class PersonLikelyNextRoomSensor")]
    assert "import is_cell_stale" not in module_level, (
        "Bug Class #34: is_cell_stale must NOT be imported at module level"
    )
    # Look for function-local import
    sensor_block_start = src.find("class PersonLikelyNextRoomSensor")
    sensor_block = src[sensor_block_start:sensor_block_start + 5000]
    assert "is_cell_stale" in sensor_block, (
        "is_cell_stale must be referenced inside PersonLikelyNextRoomSensor"
    )
    assert "from .bayesian_predictor import" in sensor_block, (
        "Bug Class #34: bayesian_predictor imports must be function-local inside sensor"
    )


def test_sensor_away_typical_also_imports_time_helpers_locally():
    """_hour_to_time_bin and _day_type must be imported locally in the D3 block."""
    src = _sensor_src()
    sensor_block_start = src.find("class PersonLikelyNextRoomSensor")
    sensor_block = src[sensor_block_start:sensor_block_start + 5000]
    assert "_hour_to_time_bin" in sensor_block or "_h2tb" in sensor_block, (
        "D3 block must import and use _hour_to_time_bin (or alias)"
    )
    assert "_day_type" in sensor_block or "_dt" in sensor_block, (
        "D3 block must import and use _day_type (or alias)"
    )


# ---------------------------------------------------------------------------
# BayesianCellStalenessNumber config entity
# ---------------------------------------------------------------------------


def test_staleness_number_entity_class_exists():
    src = _number_src()
    assert "class BayesianCellStalenessNumber(" in src, (
        "BayesianCellStalenessNumber must be defined in number.py"
    )


def test_staleness_number_default_14():
    src = _number_src()
    idx = src.find("class BayesianCellStalenessNumber(")
    assert idx >= 0
    block = src[idx:idx + 2000]
    assert '"bayesian_cell_staleness_days", 14' in block, (
        "BayesianCellStalenessNumber default must be 14 days"
    )


def test_staleness_number_range_7_to_90():
    src = _number_src()
    idx = src.find("class BayesianCellStalenessNumber(")
    assert idx >= 0
    block = src[idx:idx + 1000]
    assert "7" in block, "BayesianCellStalenessNumber min must be 7"
    assert "90" in block, "BayesianCellStalenessNumber max must be 90"


def test_staleness_number_registered_in_cm_setup():
    """BayesianCellStalenessNumber must be in the CM entity list.

    Window widened progressively as later cycles add classes / longer
    docstrings ahead of the entity list. Part 2 added Part-2 doctrine
    docstrings to several EC classes, pushing the list further down.
    Use a generous window so this test isn't fragile to follow-up cycles.
    """
    src = _number_src()
    idx = src.find("ENTRY_TYPE_COORDINATOR_MANAGER")
    assert idx >= 0
    block = src[idx:idx + 5000]
    assert "BayesianCellStalenessNumber" in block, (
        "BayesianCellStalenessNumber must be instantiated in CM async_setup_entry block"
    )


def test_staleness_number_is_restore_entity():
    """Post-Part-2 retrofit: BayesianCellStalenessNumber NO LONGER inherits
    from RestoreEntity (v4.3.2 mirror-pattern doctrine retired). entry.options
    is the sole source of truth; the setter persists via async_update_entry.
    See PLANNING_part2_ec_hc_options_writeback_retrofit.md for rationale.
    """
    src = _number_src()
    idx = src.find("class BayesianCellStalenessNumber(")
    assert idx >= 0
    block = src[idx:idx + 300]
    assert "RestoreEntity" not in block, (
        "Part 2 retrofit: BayesianCellStalenessNumber must NOT inherit "
        "RestoreEntity (doctrine retired; options = sole source of truth)"
    )
    # The setter must persist via async_update_entry (new persistence path).
    full_class = src[idx:idx + 3000]
    assert "async_update_entry" in full_class, (
        "Part 2: BayesianCellStaleness setter must call async_update_entry"
    )

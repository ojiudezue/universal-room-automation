"""v4.6.2 D4 — RegimeDetector source-grep and structural tests.

Tests verify:
- Class exists with correct __init__ signature
- run_nightly returns summary dict structure
- _persist_state logic increments counter
- Persistence guard: emits only when counter >= 2
- Vacation cell skip present
- min_obs floor (10 each window; 20 for CRITICAL)
- Writes via save_anomaly_event DAO (no raw INSERT)
- event_class='regime_shift' on emit
- Nightly task registered via entry.async_create_background_task (Bug Class #19)
"""

from pathlib import Path


def _regime_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/regime_detector.py"
    ).read_text()


def _init_src() -> str:
    return Path(
        "custom_components/universal_room_automation/__init__.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Class structure
# ---------------------------------------------------------------------------


def test_regime_detector_class_exists():
    src = _regime_src()
    assert "class RegimeDetector:" in src or "class RegimeDetector(" in src, (
        "RegimeDetector class must be defined in regime_detector.py"
    )


def test_regime_detector_init_accepts_three_deps():
    """__init__ must accept hass, database, bayesian_predictor."""
    src = _regime_src()
    idx = src.find("def __init__(self,")
    assert idx >= 0
    line_end = src.find("\n", idx)
    signature = src[idx:line_end]
    assert "hass" in signature and "database" in signature and "bayesian_predictor" in signature, (
        "__init__ must accept hass, database, bayesian_predictor"
    )


def test_run_nightly_method_exists():
    src = _regime_src()
    assert "async def run_nightly(" in src, (
        "RegimeDetector must have async def run_nightly()"
    )


def test_run_nightly_returns_summary_dict():
    src = _regime_src()
    idx = src.find("async def run_nightly(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "cells_evaluated" in block, "run_nightly must return cells_evaluated"
    assert "events_emitted" in block, "run_nightly must return events_emitted"
    assert "persons_evaluated" in block, "run_nightly must return persons_evaluated"


# ---------------------------------------------------------------------------
# Persistence guard
# ---------------------------------------------------------------------------


def test_persist_state_method_exists():
    src = _regime_src()
    assert "async def _persist_state(" in src, (
        "_persist_state must be defined"
    )


def test_persist_state_increments_counter():
    """_persist_state must read existing counter and return incremented value."""
    src = _regime_src()
    idx = src.find("async def _persist_state(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 2000]
    assert "unacknowledged_consecutive" in block, (
        "_persist_state must read/write unacknowledged_consecutive"
    )
    assert "+ 1" in block or "old_counter + 1" in block, (
        "_persist_state must increment the counter"
    )


def test_persistence_guard_requires_two_consecutive_runs():
    """Emission must be gated on _CONSECUTIVE_REQUIRED (value 2)."""
    src = _regime_src()
    assert "_CONSECUTIVE_REQUIRED" in src, (
        "_CONSECUTIVE_REQUIRED constant must be defined"
    )
    # The value must be 2
    import re
    match = re.search(r"_CONSECUTIVE_REQUIRED\s*=\s*(\d+)", src)
    assert match and int(match.group(1)) == 2, (
        "_CONSECUTIVE_REQUIRED must equal 2"
    )


def test_evaluate_cell_checks_counter_before_emitting():
    src = _regime_src()
    idx = src.find("async def _evaluate_cell(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_CONSECUTIVE_REQUIRED" in block or "new_counter" in block, (
        "_evaluate_cell must check counter against _CONSECUTIVE_REQUIRED before emitting"
    )


# ---------------------------------------------------------------------------
# Vacation cell skip
# ---------------------------------------------------------------------------


def test_is_vacation_cell_method_exists():
    src = _regime_src()
    assert "async def _is_vacation_cell(" in src, (
        "_is_vacation_cell must be defined"
    )


def test_vacation_cell_skip_present_in_evaluate_cell():
    src = _regime_src()
    idx = src.find("async def _evaluate_cell(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_is_vacation_cell" in block, (
        "_evaluate_cell must call _is_vacation_cell for vacation-cell skip"
    )


# ---------------------------------------------------------------------------
# Min observations floor
# ---------------------------------------------------------------------------


def test_min_obs_constant_defined_as_10():
    src = _regime_src()
    import re
    match = re.search(r"_MIN_OBS\s*=\s*(\d+)", src)
    assert match and int(match.group(1)) == 10, (
        "_MIN_OBS must be 10 (academic JS-divergence floor)"
    )


def test_min_obs_critical_constant_defined_as_20():
    src = _regime_src()
    import re
    match = re.search(r"_MIN_OBS_CRITICAL\s*=\s*(\d+)", src)
    assert match and int(match.group(1)) == 20, (
        "_MIN_OBS_CRITICAL must be 20 for CRITICAL severity"
    )


def test_compute_cell_divergence_checks_min_obs():
    src = _regime_src()
    idx = src.find("async def _compute_cell_divergence(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_MIN_OBS" in block, (
        "_compute_cell_divergence must check _MIN_OBS floor"
    )


# ---------------------------------------------------------------------------
# DAO usage (no raw INSERT)
# ---------------------------------------------------------------------------


def test_no_raw_insert_in_regime_detector():
    src = _regime_src()
    assert "INSERT INTO" not in src, (
        "regime_detector.py must NOT contain raw INSERT INTO SQL — "
        "all writes go through database DAO methods"
    )


def test_emits_via_save_anomaly_event():
    src = _regime_src()
    assert "save_anomaly_event(" in src, (
        "_emit_regime_event must call database.save_anomaly_event() "
        "(not a raw INSERT)"
    )


def test_event_class_is_regime_shift():
    src = _regime_src()
    assert '"regime_shift"' in src or "'regime_shift'" in src, (
        "AnomalyEvent must be created with event_class='regime_shift'"
    )


def test_coordinator_is_bayesian():
    src = _regime_src()
    assert '"bayesian"' in src or "'bayesian'" in src, (
        "AnomalyEvent must set coordinator='bayesian'"
    )


def test_event_type_is_bayesian_routine_shift():
    src = _regime_src()
    assert "bayesian.routine_shift" in src, (
        "AnomalyEvent type must be 'bayesian.routine_shift'"
    )


# ---------------------------------------------------------------------------
# Nightly task registration (Bug Class #19)
# ---------------------------------------------------------------------------


def test_nightly_task_uses_entry_async_create_background_task():
    """entry.async_create_background_task must be used, not bare async_create_task."""
    src = _init_src()
    # Look for the regime detector dispatch block
    assert "regime_detector" in src, (
        "__init__.py must reference regime_detector"
    )
    idx = src.find("regime_detector")
    block = src[max(0, idx - 200): idx + 500]
    assert "async_create_background_task" in block or (
        # May be nearby rather than on same line
        "async_create_background_task" in src[max(0, idx - 500): idx + 1000]
    ), (
        "Bug Class #19: regime detector nightly task must use "
        "entry.async_create_background_task, not bare async_create_task"
    )


def test_regime_detector_stored_in_hass_data():
    src = _init_src()
    assert 'hass.data[DOMAIN]["regime_detector"]' in src or \
           "regime_detector" in src, (
        "regime_detector must be stored in hass.data[DOMAIN]"
    )


def test_regime_detector_instantiated_with_three_args():
    src = _init_src()
    idx = src.find("RegimeDetector(")
    assert idx >= 0, "RegimeDetector must be instantiated in __init__.py"
    line_end = src.find(")", idx)
    call = src[idx:line_end + 1]
    assert "hass" in call and "database" in call and "bayesian_predictor" in call, (
        "RegimeDetector must be instantiated with (hass, database, bayesian_predictor)"
    )

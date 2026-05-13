"""v4.6.2 D7 — accuracy-shift consumer inside RegimeDetector.

Source-grep tests verify:
- _compute_cell_accuracy_drop method exists
- Reads prediction_results via _db_read()
- Compares recent 7d to baseline 30d
- Emits when drop >= 30pp AND both windows >= 5 predictions
- Combined severity = max(js, accuracy)
- Payload source field documents signal origin
"""

from pathlib import Path


def _regime_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/regime_detector.py"
    ).read_text()


# ---------------------------------------------------------------------------
# _compute_cell_accuracy_drop method
# ---------------------------------------------------------------------------


def test_compute_cell_accuracy_drop_method_exists():
    src = _regime_src()
    assert "async def _compute_cell_accuracy_drop(" in src, (
        "_compute_cell_accuracy_drop must be defined in RegimeDetector"
    )


def test_accuracy_drop_reads_prediction_results():
    src = _regime_src()
    idx = src.find("async def _compute_cell_accuracy_drop(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "prediction_results" in block, (
        "_compute_cell_accuracy_drop must query prediction_results table"
    )


def test_accuracy_drop_uses_db_read():
    """D7 must use _db_read() for WAL-concurrent access."""
    src = _regime_src()
    idx = src.find("async def _compute_cell_accuracy_drop(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_db_read()" in block, (
        "_compute_cell_accuracy_drop must use _db_read() not _db()"
    )


def test_accuracy_drop_filters_next_room_prediction_type():
    src = _regime_src()
    idx = src.find("async def _compute_cell_accuracy_drop(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "next_room" in block, (
        "_compute_cell_accuracy_drop must filter prediction_type='next_room'"
    )


def test_accuracy_drop_compares_7d_to_30d():
    """Recent 7d vs baseline 30d (excluding recent 7d)."""
    src = _regime_src()
    idx = src.find("async def _compute_cell_accuracy_drop(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "7" in block and "30" in block, (
        "_compute_cell_accuracy_drop must use 7d and 30d windows"
    )


def test_accuracy_drop_threshold_is_0_30():
    """Drop threshold must be 30 percentage points (0.30 fractional)."""
    src = _regime_src()
    assert "_ACCURACY_DROP_THRESHOLD" in src, (
        "_ACCURACY_DROP_THRESHOLD constant must be defined"
    )
    import re
    match = re.search(r"_ACCURACY_DROP_THRESHOLD\s*=\s*([\d.]+)", src)
    assert match and abs(float(match.group(1)) - 0.30) < 1e-9, (
        "_ACCURACY_DROP_THRESHOLD must be 0.30"
    )


def test_accuracy_drop_min_predictions_is_5():
    """Both windows must have >= 5 predictions."""
    src = _regime_src()
    assert "_MIN_PREDICTIONS" in src, (
        "_MIN_PREDICTIONS constant must be defined"
    )
    import re
    match = re.search(r"_MIN_PREDICTIONS\s*=\s*(\d+)", src)
    assert match and int(match.group(1)) == 5, (
        "_MIN_PREDICTIONS must be 5"
    )


# ---------------------------------------------------------------------------
# Combined severity and payload
# ---------------------------------------------------------------------------


def test_combined_severity_is_max_of_js_and_accuracy():
    src = _regime_src()
    # The _evaluate_cell method combines the two signals
    idx = src.find("async def _evaluate_cell(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "js_bucket" in block or "acc_bucket" in block, (
        "_evaluate_cell must separately track js and accuracy buckets"
    )
    # Must pick the higher severity
    assert "severity_rank" in block or "max" in block or (
        "js_bucket" in block and "acc_bucket" in block
    ), (
        "Combined severity must be max of JS and accuracy signals"
    )


def test_payload_source_field_present():
    """Payload must contain 'source' key documenting signal origin."""
    src = _regime_src()
    assert '"source"' in src or "'source'" in src, (
        "AnomalyEvent payload must contain 'source' field"
    )


def test_payload_source_values_cover_three_cases():
    """source must be 'js_divergence' | 'accuracy_drop' | 'combined'."""
    src = _regime_src()
    assert "js_divergence" in src, "source='js_divergence' must be possible"
    assert "accuracy_drop" in src, "source='accuracy_drop' must be possible"
    assert "combined" in src, "source='combined' must be possible"


def test_accuracy_drop_imports_dt_util_locally():
    """Bug Class #34: dt_util must be imported function-locally in _compute_cell_accuracy_drop."""
    src = _regime_src()
    idx = src.find("async def _compute_cell_accuracy_drop(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    # Function-local import inside the method body
    assert "from homeassistant.util import dt" in block, (
        "Bug Class #34: dt_util must be imported function-locally in "
        "_compute_cell_accuracy_drop, not at module level"
    )

"""v4.6.0 D3 — save_next_room_prediction_result() DB helper.

Source-grep + pure-Python math tests verify:
- Helper exists with correct signature
- Uses prediction_type='next_room'
- Inserts person_id into the query
- Brier math correctness (pure Python, no HA imports)
"""

import pytest


@pytest.fixture(scope="module")
def database_src() -> str:
    with open(
        "custom_components/universal_room_automation/database.py"
    ) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Signature and existence
# ---------------------------------------------------------------------------


def test_helper_exists(database_src: str):
    """save_next_room_prediction_result must exist in database.py."""
    assert "async def save_next_room_prediction_result(" in database_src, (
        "D3: save_next_room_prediction_result helper must exist in database.py"
    )


def test_helper_has_person_id_param(database_src: str):
    """Helper signature must include person_id parameter."""
    helper_start = database_src.find("async def save_next_room_prediction_result(")
    assert helper_start >= 0
    paren_end = database_src.find(")", helper_start)
    sig = database_src[helper_start:paren_end + 1]
    assert "person_id" in sig, (
        "D3: helper must have person_id parameter"
    )


def test_helper_has_predicted_room_param(database_src: str):
    """Helper signature must include predicted_room parameter."""
    helper_start = database_src.find("async def save_next_room_prediction_result(")
    assert helper_start >= 0
    paren_end = database_src.find(")", helper_start)
    sig = database_src[helper_start:paren_end + 1]
    assert "predicted_room" in sig, (
        "D3: helper must have predicted_room parameter"
    )


def test_helper_has_error_value_param(database_src: str):
    """Helper signature must include error_value (Brier score) parameter."""
    helper_start = database_src.find("async def save_next_room_prediction_result(")
    assert helper_start >= 0
    paren_end = database_src.find(")", helper_start)
    sig = database_src[helper_start:paren_end + 1]
    assert "error_value" in sig, (
        "D3: helper must have error_value parameter for Brier score"
    )


# ---------------------------------------------------------------------------
# DB insert correctness
# ---------------------------------------------------------------------------


def test_prediction_type_is_next_room(database_src: str):
    """Helper must insert prediction_type='next_room'."""
    helper_start = database_src.find("async def save_next_room_prediction_result(")
    assert helper_start >= 0
    next_def = database_src.find("\n    async def ", helper_start + 100)
    body = database_src[helper_start:next_def if next_def > 0 else helper_start + 3000]
    assert '"next_room"' in body, (
        "D3: INSERT must use prediction_type='next_room'"
    )


def test_person_id_included_in_insert(database_src: str):
    """person_id must appear in the INSERT column list and VALUES."""
    helper_start = database_src.find("async def save_next_room_prediction_result(")
    assert helper_start >= 0
    next_def = database_src.find("\n    async def ", helper_start + 100)
    body = database_src[helper_start:next_def if next_def > 0 else helper_start + 3000]
    assert "person_id" in body, (
        "D3: INSERT must include person_id column"
    )


def test_helper_uses_predicted_value_json_param(database_src: str):
    """predicted_value_json must be passed directly (caller pre-encodes JSON)."""
    helper_start = database_src.find("async def save_next_room_prediction_result(")
    assert helper_start >= 0
    next_def = database_src.find("\n    async def ", helper_start + 100)
    body = database_src[helper_start:next_def if next_def > 0 else helper_start + 3000]
    assert "predicted_value_json" in body, (
        "D3: helper must use predicted_value_json (caller provides pre-encoded JSON)"
    )


def test_helper_error_on_failure(database_src: str):
    """Failures must be logged at ERROR level (matches save_prediction_result
    convention — DB write failures are higher severity than schema migrations).
    """
    helper_start = database_src.find("async def save_next_room_prediction_result(")
    assert helper_start >= 0
    next_def = database_src.find("\n    async def ", helper_start + 100)
    body = database_src[helper_start:next_def if next_def > 0 else helper_start + 3000]
    assert "_LOGGER.error(" in body, (
        "D3: save_next_room_prediction_result must log failures at ERROR level"
    )


# ---------------------------------------------------------------------------
# Brier math correctness (pure Python, no HA imports)
# ---------------------------------------------------------------------------


def test_brier_score_formula_hit():
    """When top1 hit (actual == predicted): brier = (confidence - 1.0)^2."""
    confidence = 0.67
    top1_hit = 1.0
    brier = (confidence - top1_hit) ** 2
    expected = (0.67 - 1.0) ** 2
    assert abs(brier - expected) < 1e-9
    assert abs(brier - 0.1089) < 1e-4


def test_brier_score_formula_miss():
    """When top1 miss (actual != predicted): brier = (confidence - 0.0)^2."""
    confidence = 0.67
    top1_hit = 0.0
    brier = (confidence - top1_hit) ** 2
    expected = 0.67 ** 2
    assert abs(brier - expected) < 1e-9
    assert abs(brier - 0.4489) < 1e-4


def test_brier_perfect_prediction():
    """Perfect prediction: confidence=1.0, hit=1.0 → brier=0.0."""
    confidence = 1.0
    top1_hit = 1.0
    brier = (confidence - top1_hit) ** 2
    assert brier == 0.0


def test_brier_confident_wrong():
    """Confident but wrong: confidence=0.9, hit=0.0 → brier=0.81."""
    confidence = 0.9
    top1_hit = 0.0
    brier = (confidence - top1_hit) ** 2
    assert abs(brier - 0.81) < 1e-9


def test_brier_uniform_miss():
    """Uncertain miss: confidence=0.25, hit=0.0 → brier=0.0625."""
    confidence = 0.25
    top1_hit = 0.0
    brier = (confidence - top1_hit) ** 2
    assert abs(brier - 0.0625) < 1e-9

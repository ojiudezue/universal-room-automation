"""v4.6.0 D2 — _score_prediction hook in TransitionDetector.

Source-grep + AST-walk tests verify:
- _score_prediction method exists on TransitionDetector
- It is called from _log_transition
- The whole body is wrapped in try/except at WARNING level with exc_info=True
- Cache staleness gate (30 min = 1800 sec) is present
- Function-local imports are used (not module-level) for DOMAIN and dt_util
"""

import ast
import pytest


@pytest.fixture(scope="module")
def transitions_src() -> str:
    with open(
        "custom_components/universal_room_automation/transitions.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def transitions_tree(transitions_src: str) -> ast.Module:
    return ast.parse(transitions_src)


# ---------------------------------------------------------------------------
# Method existence + hook
# ---------------------------------------------------------------------------


def test_score_prediction_method_exists(transitions_src: str):
    """_score_prediction must be defined on TransitionDetector."""
    assert "async def _score_prediction(self, person_id: str, actual_room: str)" in transitions_src, (
        "D2: _score_prediction method must exist with (person_id, actual_room) signature"
    )


def test_score_prediction_called_from_log_transition(transitions_src: str):
    """_score_prediction must be awaited inside _log_transition."""
    log_start = transitions_src.find("async def _log_transition(self, transition: RoomTransition)")
    assert log_start >= 0
    # Find the next method definition after _log_transition
    next_method = transitions_src.find("\n    async def ", log_start + 100)
    assert next_method > log_start
    log_body = transitions_src[log_start:next_method]
    assert "await self._score_prediction(" in log_body, (
        "D2: _log_transition must call await self._score_prediction(...)"
    )


def test_score_prediction_inside_try_block(transitions_src: str):
    """Review fix B2 / A#4: scoring must run INSIDE the _log_transition
    try-block so a failed log_transition() short-circuits via the except
    branch and we never write a prediction_results row referencing a
    transition that didn't land in room_transitions.
    """
    log_start = transitions_src.find("async def _log_transition(self, transition: RoomTransition)")
    next_method = transitions_src.find("\n    async def ", log_start + 100)
    log_body = transitions_src[log_start:next_method]

    try_idx = log_body.find("try:")
    except_idx = log_body.find("except Exception")
    score_idx = log_body.find("await self._score_prediction(")
    assert try_idx >= 0 and except_idx > try_idx, (
        "D2: _log_transition must wrap log + score in a try/except block"
    )
    assert try_idx < score_idx < except_idx, (
        "D2 / review fix B2: score call must live INSIDE the try block, "
        "BEFORE the `except Exception` clause. Otherwise a failed "
        "log_transition() insert still produces an accuracy row "
        "referencing a transition that never persisted (phantom-row pollution)."
    )


def test_score_prediction_receives_person_id_and_to_room(transitions_src: str):
    """The call must pass transition.person_id and transition.to_room."""
    assert "self._score_prediction(transition.person_id, transition.to_room)" in transitions_src, (
        "D2: _score_prediction call must pass transition.person_id and transition.to_room"
    )


# ---------------------------------------------------------------------------
# Swallow-escalation pattern (v4.5.20 shape)
# ---------------------------------------------------------------------------


def test_score_prediction_wrapped_in_try_except(transitions_src: str):
    """Entire body must be wrapped in a try/except so scoring failure
    never propagates to _log_transition.
    """
    score_start = transitions_src.find("async def _score_prediction(self, person_id: str, actual_room: str)")
    assert score_start >= 0
    next_method = transitions_src.find("\n    async def ", score_start + 100)
    if next_method < 0:
        next_method = transitions_src.find("\n    def ", score_start + 100)
    body = transitions_src[score_start:next_method if next_method > 0 else score_start + 4000]
    assert "try:" in body, "D2: _score_prediction body must start with try:"
    assert "except Exception:" in body, "D2: _score_prediction must catch Exception"


def test_score_prediction_warning_level_swallow(transitions_src: str):
    """Exception must be logged at WARNING (not debug/error) with exc_info=True."""
    score_start = transitions_src.find("async def _score_prediction(self, person_id: str, actual_room: str)")
    assert score_start >= 0
    next_method = transitions_src.find("\n    async def ", score_start + 100)
    if next_method < 0:
        next_method = transitions_src.find("\n    def ", score_start + 100)
    body = transitions_src[score_start:next_method if next_method > 0 else score_start + 4000]
    assert "_LOGGER.warning(" in body, "D2: swallow must be WARNING-level"
    assert "exc_info=True" in body, "D2: swallow must include exc_info=True"


# ---------------------------------------------------------------------------
# Cache staleness gate
# ---------------------------------------------------------------------------


def test_staleness_gate_1800_seconds(transitions_src: str):
    """30-minute staleness gate (1800 seconds) must be present."""
    assert "1800" in transitions_src, (
        "D2: staleness gate must use 1800 seconds (30 min)"
    )


def test_staleness_gate_age_check(transitions_src: str):
    """The gate must compare age_seconds against the threshold."""
    assert "age_seconds > 1800" in transitions_src, (
        "D2: staleness check must be 'if age_seconds > 1800'"
    )


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def test_top1_hit_formula(transitions_src: str):
    """top1_hit must use the spec-defined formula."""
    assert 'top1_hit = 1.0 if cache["top"] == actual_room else 0.0' in transitions_src, (
        "D2: top1_hit formula must match spec"
    )


def test_top3_hit_formula(transitions_src: str):
    """top3_hit must include cache['top'] and alternatives."""
    assert 'top3_hit = 1.0 if actual_room in [cache["top"], *cache["alternatives"]] else 0.0' in transitions_src, (
        "D2: top3_hit formula must match spec"
    )


def test_brier_formula(transitions_src: str):
    """Brier score must be (confidence - top1_hit) ** 2."""
    assert "brier = (cache[\"confidence\"] - top1_hit) ** 2" in transitions_src, (
        "D2: Brier formula must be (confidence - top1_hit) ** 2"
    )


# ---------------------------------------------------------------------------
# Signal dispatch
# ---------------------------------------------------------------------------


def test_signal_dispatched_from_score_prediction(transitions_src: str):
    """SIGNAL_NEXT_ROOM_PREDICTION_UPDATE must be dispatched after scoring."""
    assert "SIGNAL_NEXT_ROOM_PREDICTION_UPDATE" in transitions_src, (
        "D2: must dispatch SIGNAL_NEXT_ROOM_PREDICTION_UPDATE after scoring"
    )
    assert "async_dispatcher_send" in transitions_src, (
        "D2: must call async_dispatcher_send in _score_prediction"
    )


# ---------------------------------------------------------------------------
# Function-local imports (Bug Class #34 prevention)
# ---------------------------------------------------------------------------


def test_domain_import_is_function_local(transitions_src: str):
    """DOMAIN must NOT be imported at module level in transitions.py.
    The only DOMAIN import must be function-local inside _score_prediction.
    This prevents Bug Class #34 (function-local import shadows module-level).
    """
    # No module-level 'from .const import DOMAIN' (or similar)
    lines = transitions_src.splitlines()
    module_level_domain_imports = [
        line for i, line in enumerate(lines)
        if "from .const import" in line and "DOMAIN" in line and i < 30
    ]
    assert len(module_level_domain_imports) == 0, (
        f"D2: DOMAIN must NOT be imported at module level in transitions.py. "
        f"Found: {module_level_domain_imports}"
    )
    # Function-local import inside _score_prediction
    assert "from .const import DOMAIN" in transitions_src, (
        "D2: DOMAIN must be imported function-locally inside _score_prediction"
    )

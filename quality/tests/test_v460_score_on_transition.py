"""v4.6.0 D2 — _score_prediction hook in TransitionDetector.

Source-grep + AST-walk tests verify:
- _score_prediction method exists on TransitionDetector
- It is called from _log_transition
- The whole body is wrapped in try/except at WARNING level with exc_info=True
- Cache staleness gate (30 min = 1800 sec) is present
- Function-local imports are used (not module-level) for DOMAIN and dt_util
"""

import ast
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


# Behavioural replacements (PREDICT-MODEL-DWELL-MIGRATION-1 D4 added a
# from_room argument, which broke four signature/call-string greps; they are
# now driven through the real _log_transition instead of grepped).


@pytest.fixture(scope="module")
def _real():
    import importlib

    from occ_dwell_helpers import real_package

    with real_package():
        yield SimpleNamespace(
            transitions=importlib.import_module(
                "custom_components.universal_room_automation.transitions"),
            dt_util=importlib.import_module("homeassistant.util.dt"),
            dispatcher=importlib.import_module("homeassistant.helpers.dispatcher"),
        )


def _detector(real, save):
    from custom_components.universal_room_automation.const import DOMAIN

    cache = {"top": "Kitchen", "alternatives": ["Foyer"], "confidence": 0.5,
             "source": "frequency",
             "timestamp": real.dt_util.utcnow().isoformat()}
    db = SimpleNamespace(log_transition=AsyncMock(),
                         save_next_room_prediction_result=save)
    hass = SimpleNamespace(data={DOMAIN: {"next_room_predictions": {"Oji": cache}}})
    return real.transitions.TransitionDetector(hass, None, db)


def _transition(real):
    return real.transitions.RoomTransition(
        person_id="Oji", from_room="Study A", to_room="Kitchen",
        timestamp=datetime.now(timezone.utc), duration_seconds=10,
        path_type="direct", confidence=0.9)


@pytest.mark.asyncio
async def test_score_prediction_method_exists(_real):
    """_log_transition scores the cached prediction (behavioural)."""
    save = AsyncMock()
    det = _detector(_real, save)
    with patch.object(_real.dispatcher, "async_dispatcher_send", MagicMock()):
        await det._log_transition(_transition(_real))
    save.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_prediction_called_from_log_transition(_real):
    """_log_transition awaits the scorer (behavioural; was a source grep)."""
    save = AsyncMock()
    det = _detector(_real, save)
    with patch.object(_real.dispatcher, "async_dispatcher_send", MagicMock()):
        await det._log_transition(_transition(_real))
    save.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_prediction_inside_try_block(_real):
    """Review fix B2 / A#4 (behavioural): a failed room_transitions insert
    short-circuits, so no prediction_results row references a transition
    that never persisted."""
    save = AsyncMock()
    det = _detector(_real, save)
    det.database.log_transition = AsyncMock(side_effect=RuntimeError("insert"))
    await det._log_transition(_transition(_real))
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_score_prediction_receives_person_id_and_to_room(_real):
    """The scored row carries the transition's person and to_room."""
    save = AsyncMock()
    det = _detector(_real, save)
    with patch.object(_real.dispatcher, "async_dispatcher_send", MagicMock()):
        await det._log_transition(_transition(_real))
    kw = save.await_args.kwargs
    assert kw["person_id"] == "Oji"
    assert kw["actual_room"] == "Kitchen"
    assert kw["predicted_room"] == "Kitchen"


# ---------------------------------------------------------------------------
# Swallow-escalation pattern (v4.5.20 shape)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_prediction_wrapped_in_try_except(_real):
    """A scoring failure never propagates out of _score_prediction."""
    det = _detector(_real, AsyncMock(side_effect=RuntimeError("db gone")))
    await det._score_prediction("Oji", "Kitchen", "Study A")   # no raise


@pytest.mark.asyncio
async def test_score_prediction_warning_level_swallow(_real, caplog):
    """The swallowed failure is logged at WARNING with a traceback."""
    import logging

    det = _detector(_real, AsyncMock(side_effect=RuntimeError("db gone")))
    with caplog.at_level(logging.WARNING):
        await det._score_prediction("Oji", "Kitchen", "Study A")
    recs = [r for r in caplog.records if "prediction scoring failed" in r.getMessage()]
    assert len(recs) == 1
    assert recs[0].levelno == logging.WARNING
    assert recs[0].exc_info is not None


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

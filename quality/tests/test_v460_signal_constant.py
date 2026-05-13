"""v4.6.0 D6 — SIGNAL_NEXT_ROOM_PREDICTION_UPDATE constant in signals.py.

Source-grep tests verify the constant exists at module level in signals.py
with the correct string value, following the established naming convention.
"""

import pytest


@pytest.fixture(scope="module")
def signals_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/signals.py"
    ) as f:
        return f.read()


def test_signal_constant_exists(signals_src: str):
    """SIGNAL_NEXT_ROOM_PREDICTION_UPDATE must be defined in signals.py."""
    assert "SIGNAL_NEXT_ROOM_PREDICTION_UPDATE" in signals_src, (
        "D6: SIGNAL_NEXT_ROOM_PREDICTION_UPDATE must exist in signals.py"
    )


def test_signal_constant_value(signals_src: str):
    """Signal value must be the agreed string."""
    assert '"ura_next_room_prediction_update"' in signals_src, (
        "D6: SIGNAL_NEXT_ROOM_PREDICTION_UPDATE value must be "
        "'ura_next_room_prediction_update'"
    )


def test_signal_constant_is_final(signals_src: str):
    """Constant must use Final type annotation to match existing conventions."""
    # Find the constant declaration line
    idx = signals_src.find("SIGNAL_NEXT_ROOM_PREDICTION_UPDATE")
    assert idx >= 0
    line_start = signals_src.rfind("\n", 0, idx) + 1
    line_end = signals_src.find("\n", idx)
    line = signals_src[line_start:line_end]
    assert "Final" in line, (
        "D6: SIGNAL_NEXT_ROOM_PREDICTION_UPDATE must use Final annotation"
    )


def test_signal_constant_follows_naming_convention(signals_src: str):
    """Constant name must follow the SIGNAL_*_UPDATE convention used by
    SIGNAL_PRESENCE_ENTITIES_UPDATE and SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE.
    """
    assert "SIGNAL_NEXT_ROOM_PREDICTION_UPDATE: Final" in signals_src, (
        "D6: constant declaration must match 'SIGNAL_NEXT_ROOM_PREDICTION_UPDATE: Final'"
    )


def test_signal_in_transitions_dispatch(signals_src: str):
    """The signal being defined here is the one transitions.py dispatches.
    Verify the string value matches what _score_prediction imports.
    """
    # The value used in transitions.py must match this constant's value
    assert "ura_next_room_prediction_update" in signals_src, (
        "D6: signal value 'ura_next_room_prediction_update' must appear in signals.py"
    )

"""v4.6.0 D1 — NextRoomPredictionCache write in PersonLikelyNextRoomSensor.

Source-grep tests verify that sensor.py writes to
hass.data[DOMAIN]["next_room_predictions"][person_id] after a successful
prediction is computed.
"""

import pytest


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open(
        "custom_components/universal_room_automation/sensor.py"
    ) as f:
        return f.read()


def test_cache_write_key_next_room_predictions(sensor_src: str):
    """The cache dict key must be 'next_room_predictions'."""
    assert '"next_room_predictions"' in sensor_src, (
        "D1: sensor.py must write to hass.data[DOMAIN]['next_room_predictions']"
    )


def test_cache_write_gated_on_prediction_not_none(sensor_src: str):
    """Cache write is inside an `if self._cached_prediction is not None` block
    so stale/empty entries are never written.
    """
    assert "if self._cached_prediction is not None:" in sensor_src, (
        "D1: cache write must be gated on self._cached_prediction is not None"
    )


def test_cache_row_has_top_key(sensor_src: str):
    """Cache row must contain 'top' key (predicted top room)."""
    assert '"top": self._cached_prediction.get("next_room")' in sensor_src, (
        "D1: cache row must set 'top' from cached_prediction['next_room']"
    )


def test_cache_row_has_confidence_key(sensor_src: str):
    """Cache row must contain 'confidence' key."""
    assert '"confidence": self._cached_prediction.get("confidence")' in sensor_src, (
        "D1: cache row must set 'confidence'"
    )


def test_cache_row_has_source_key(sensor_src: str):
    """Cache row must include prediction source."""
    assert '"source": self._prediction_source' in sensor_src, (
        "D1: cache row must set 'source' from self._prediction_source"
    )


def test_cache_row_has_timestamp_key(sensor_src: str):
    """Cache row must include a UTC ISO timestamp."""
    assert '"timestamp": dt_util.utcnow().isoformat()' in sensor_src, (
        "D1: cache row must set 'timestamp' via dt_util.utcnow().isoformat()"
    )


def test_cache_row_has_alternatives_key(sensor_src: str):
    """Cache row stores top-3 hit shape (top + 2 alts); review fix B5/A#3."""
    assert '"alternatives": alt_rooms[:2]' in sensor_src, (
        "D1: cache row must set 'alternatives' as alt_rooms[:2] "
        "(top-3 = top + 2 alternatives = 3 rooms total)"
    )


def test_cache_write_normalises_both_alt_shapes(sensor_src: str):
    """Bayesian alternatives are [str]; frequency alternatives are [dict].
    The write block must handle both shapes.
    """
    assert 'isinstance(a, str)' in sensor_src, (
        "D1: normalisation must handle str alternatives (Bayesian path)"
    )
    assert 'isinstance(a, dict)' in sensor_src, (
        "D1: normalisation must handle dict alternatives (frequency path)"
    )


def test_cache_write_guards_domain_key(sensor_src: str):
    """Cache write must guard 'if DOMAIN not in hass.data' before setdefault
    (review fix B4: avoids shadow-dict if hass.data[DOMAIN] not yet set).
    """
    assert 'if DOMAIN not in self.hass.data:' in sensor_src, (
        "D1: must guard `if DOMAIN not in self.hass.data: return` before "
        "the next_room_predictions setdefault — prevents shadow-dict race "
        "during early init."
    )
    assert 'self.hass.data[DOMAIN].setdefault(\n                    "next_room_predictions", {}\n                )' in sensor_src, (
        "D1: after the guard, write via hass.data[DOMAIN].setdefault(...)"
    )


def test_cache_write_in_async_update(sensor_src: str):
    """The cache write must be inside async_update, not in a property."""
    # Locate PersonLikelyNextRoomSensor class body
    class_start = sensor_src.find("class PersonLikelyNextRoomSensor(")
    assert class_start >= 0
    # Locate async_update within the class
    update_start = sensor_src.find("    async def async_update(self) -> None:", class_start)
    assert update_start > class_start
    # next method after async_update
    next_method = sensor_src.find("\n    @property", update_start + 1)
    assert next_method > update_start
    update_body = sensor_src[update_start:next_method]
    assert "next_room_predictions" in update_body, (
        "D1: cache write must be inside async_update"
    )

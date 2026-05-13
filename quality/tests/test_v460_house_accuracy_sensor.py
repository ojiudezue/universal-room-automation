"""v4.6.0 D5 — HouseNextRoomAccuracySensor tests.

Source-grep tests verify:
- Class exists with correct base classes
- Aggregation uses sum(hits)/sum(predictions), NOT mean of per-person rates
- Subscribes to SIGNAL_NEXT_ROOM_PREDICTION_UPDATE without person_id filter
- async_on_remove wrapping (Bug Class #38)
- Required attributes are exposed
"""

import pytest


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open("custom_components/universal_room_automation/sensor.py") as f:
        return f.read()


def _house_class_body(sensor_src: str) -> str:
    """Extract the HouseNextRoomAccuracySensor class body."""
    class_start = sensor_src.find("class HouseNextRoomAccuracySensor(")
    assert class_start >= 0, "HouseNextRoomAccuracySensor class not found"
    class_end = sensor_src.find("\nclass ", class_start + 1)
    return sensor_src[class_start:class_end if class_end > 0 else class_start + 10000]


# ---------------------------------------------------------------------------
# Class structure
# ---------------------------------------------------------------------------


def test_class_exists(sensor_src: str):
    """HouseNextRoomAccuracySensor class must exist in sensor.py."""
    assert "class HouseNextRoomAccuracySensor(" in sensor_src, (
        "D5: HouseNextRoomAccuracySensor class must be defined in sensor.py"
    )


def test_class_base_classes(sensor_src: str):
    """Class must extend AggregationEntity and SensorEntity."""
    assert "class HouseNextRoomAccuracySensor(AggregationEntity, SensorEntity):" in sensor_src, (
        "D5: HouseNextRoomAccuracySensor must extend AggregationEntity, SensorEntity"
    )


def test_entity_category_is_diagnostic(sensor_src: str):
    """Must be DIAGNOSTIC entity category."""
    body = _house_class_body(sensor_src)
    assert "EntityCategory.DIAGNOSTIC" in body, (
        "D5: HouseNextRoomAccuracySensor must use EntityCategory.DIAGNOSTIC"
    )


def test_unique_id(sensor_src: str):
    """Unique ID must be the agreed house-wide constant."""
    body = _house_class_body(sensor_src)
    # unique_id is set as f"{DOMAIN}_house_next_room_accuracy"
    assert "_house_next_room_accuracy" in body, (
        "D5: unique_id must include '_house_next_room_accuracy'"
    )


def test_device_is_cm_device_info(sensor_src: str):
    """Must land on the Coordinator Manager device via _cm_device_info()."""
    body = _house_class_body(sensor_src)
    assert "_cm_device_info()" in body, (
        "D5: HouseNextRoomAccuracySensor must use _cm_device_info()"
    )


# ---------------------------------------------------------------------------
# Aggregate math — sum of hits / sum of predictions, NOT mean of rates
# ---------------------------------------------------------------------------


def test_aggregate_uses_sum_not_mean(sensor_src: str):
    """Aggregate top-1 rate must be sum(hits)/sum(predictions).

    Using statistics.mean or mean() over per-person rates would introduce
    small-n bias. Assert that statistics.mean is not imported and
    that no standalone mean() call exists outside comments/docstrings.
    """
    body = _house_class_body(sensor_src)
    assert "statistics.mean" not in body, (
        "D5: must NOT use statistics.mean to combine per-person rates"
    )
    # Strip docstrings and comments, then check for mean( calls.
    # Docstrings are delimited by triple-quotes; strip them before scanning.
    import re
    stripped = re.sub(r'""".*?"""', '', body, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", '', stripped, flags=re.DOTALL)
    # Remove inline comments
    stripped = re.sub(r'#[^\n]*', '', stripped)
    mean_calls = re.findall(r'\bmean\s*\(', stripped)
    assert len(mean_calls) == 0, (
        f"D5: found mean() call in HouseNextRoomAccuracySensor code (not in docstring) — "
        f"aggregate must be sum(hits)/sum(predictions). Matches: {mean_calls}"
    )


def test_aggregate_formula_uses_total_hits_and_predictions(sensor_src: str):
    """Aggregate calculation must reference total_hits and total_predictions."""
    body = _house_class_body(sensor_src)
    assert "total_hits" in body, (
        "D5: must accumulate total_hits across all persons"
    )
    assert "total_predictions" in body, (
        "D5: must accumulate total_predictions across all persons"
    )
    assert "total_hits / total_predictions" in body, (
        "D5: aggregate rate must be total_hits / total_predictions"
    )


# ---------------------------------------------------------------------------
# Signal subscription — Bug Class #38
# ---------------------------------------------------------------------------


def test_subscribes_via_async_on_remove(sensor_src: str):
    """async_added_to_hass must wrap dispatcher_connect with async_on_remove."""
    body = _house_class_body(sensor_src)
    assert "async_on_remove(" in body, (
        "D5: subscription must be wrapped with self.async_on_remove (Bug Class #38)"
    )
    assert "async_dispatcher_connect" in body, (
        "D5: must subscribe via async_dispatcher_connect"
    )


def test_subscribes_to_next_room_signal(sensor_src: str):
    """Must subscribe to SIGNAL_NEXT_ROOM_PREDICTION_UPDATE."""
    body = _house_class_body(sensor_src)
    assert "SIGNAL_NEXT_ROOM_PREDICTION_UPDATE" in body, (
        "D5: must subscribe to SIGNAL_NEXT_ROOM_PREDICTION_UPDATE"
    )


def test_handle_update_no_person_id_filter(sensor_src: str):
    """_handle_update must refresh on ANY person's signal (no person_id filter).

    HouseNextRoomAccuracySensor aggregates all persons — it should not filter
    by person_id as PersonNextRoomAccuracySensor does.
    """
    body = _house_class_body(sensor_src)
    handle_start = body.find("def _handle_update(")
    assert handle_start >= 0, "D5: _handle_update method must exist"
    handle_end = body.find("\n    @", handle_start + 1)
    if handle_end < 0:
        handle_end = body.find("\n    async def ", handle_start + 1)
    handle_body = body[handle_start:handle_end if handle_end > 0 else handle_start + 400]
    # Should NOT check person_id against self._person_id (no such attribute on house sensor)
    assert "self._person_id" not in handle_body, (
        "D5: _handle_update must NOT filter by person_id — house sensor refreshes on all"
    )


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def test_extra_state_attributes_keys(sensor_src: str):
    """extra_state_attributes must expose the required keys."""
    body = _house_class_body(sensor_src)
    for key in (
        "per_person_accuracy",
        "total_predictions_7d",
        "total_predictions_24h",
        "brier_score",
        "oldest_prediction_ts",
    ):
        assert f'"{key}"' in body, (
            f"D5: extra_state_attributes must include key '{key}'"
        )


def test_per_person_accuracy_is_dict(sensor_src: str):
    """per_person_accuracy must be built as a dict keyed by person_id."""
    body = _house_class_body(sensor_src)
    assert "per_person" in body, (
        "D5: per-person breakdown dict must be built in async_update"
    )


def test_none_when_no_predictions(sensor_src: str):
    """native_value must return None when total_predictions == 0."""
    body = _house_class_body(sensor_src)
    assert '"top1_hit_rate": None' in body, (
        "D5: top1_hit_rate must be set to None when no predictions exist"
    )


# ===========================================================================
# Review fixes B1 / B3 — DB-read primitive + sync schedule-update
# ===========================================================================


def test_d5_uses_db_read_not_write_queue(sensor_src: str):
    """Review fix B1 (CRITICAL): D5 must use database._db_read() for reads."""
    class_start = sensor_src.find("class HouseNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end] if class_end > class_start else sensor_src[class_start:]
    assert "database._db_read()" in class_body, (
        "D5: must call database._db_read() (WAL-concurrent read), not _db()"
    )
    assert "database._db()" not in class_body, (
        "D5: database._db() (write queue) must NOT appear — see review B1"
    )


def test_d5_uses_async_schedule_update(sensor_src: str):
    """Review fix B3 (HIGH): D5 _handle_update must use
    async_schedule_update_ha_state(force_refresh=True), not async_create_task.
    """
    class_start = sensor_src.find("class HouseNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end] if class_end > class_start else sensor_src[class_start:]
    assert "self.async_schedule_update_ha_state(force_refresh=True)" in class_body, (
        "D5 _handle_update: must use self.async_schedule_update_ha_state(force_refresh=True)"
    )
    assert "async_create_task" not in class_body, (
        "D5: must not spawn untracked tasks from _handle_update"
    )

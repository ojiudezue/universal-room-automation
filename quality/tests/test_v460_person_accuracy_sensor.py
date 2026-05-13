"""v4.6.0 D4 — PersonNextRoomAccuracySensor tests.

Source-grep and AST tests verify:
- Class exists with correct base classes
- async_update queries prediction_results filtered by prediction_type='next_room' and person_id
- async_added_to_hass subscribes via async_on_remove(async_dispatcher_connect(...))
- Native value returns None (not 0.0) when no predictions
- 30-second cache window is present
- No statistics.mean used to combine rates
"""

import ast
import pytest


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open("custom_components/universal_room_automation/sensor.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def sensor_tree(sensor_src: str) -> ast.Module:
    return ast.parse(sensor_src)


# ---------------------------------------------------------------------------
# Class structure
# ---------------------------------------------------------------------------


def test_class_exists(sensor_src: str):
    """PersonNextRoomAccuracySensor class must exist in sensor.py."""
    assert "class PersonNextRoomAccuracySensor(" in sensor_src, (
        "D4: PersonNextRoomAccuracySensor class must be defined in sensor.py"
    )


def test_class_base_classes(sensor_src: str):
    """Class must extend AggregationEntity and SensorEntity."""
    assert "class PersonNextRoomAccuracySensor(AggregationEntity, SensorEntity):" in sensor_src, (
        "D4: PersonNextRoomAccuracySensor must extend AggregationEntity, SensorEntity"
    )


def test_entity_category_is_diagnostic(sensor_src: str):
    """Must be DIAGNOSTIC entity category."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "EntityCategory.DIAGNOSTIC" in class_body, (
        "D4: PersonNextRoomAccuracySensor must use EntityCategory.DIAGNOSTIC"
    )


def test_enabled_by_default(sensor_src: str):
    """Must be entity_registry_enabled_default = True (not hidden by default)."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "_attr_entity_registry_enabled_default = True" in class_body, (
        "D4: PersonNextRoomAccuracySensor must be enabled by default"
    )


def test_unique_id_pattern(sensor_src: str):
    """Unique ID must follow the per-person naming convention."""
    assert "next_room_accuracy" in sensor_src, (
        "D4: unique_id must include 'next_room_accuracy'"
    )
    assert 'f"{DOMAIN}_person_{person_id.lower()}_next_room_accuracy"' in sensor_src, (
        "D4: unique_id must be f'{DOMAIN}_person_{person_id.lower()}_next_room_accuracy'"
    )


def test_device_is_cm_device_info(sensor_src: str):
    """Must use _cm_device_info() for the Coordinator Manager device."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "_cm_device_info()" in class_body, (
        "D4: PersonNextRoomAccuracySensor must use _cm_device_info()"
    )


# ---------------------------------------------------------------------------
# async_update DB query
# ---------------------------------------------------------------------------


def test_async_update_queries_next_room_type(sensor_src: str):
    """async_update must filter by prediction_type = 'next_room'."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "prediction_type = 'next_room'" in class_body, (
        "D4: async_update must filter WHERE prediction_type = 'next_room'"
    )


def test_async_update_filters_by_person_id(sensor_src: str):
    """async_update must include person_id in the WHERE clause."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "person_id = ?" in class_body, (
        "D4: async_update must filter by person_id"
    )


def test_async_update_has_7day_window(sensor_src: str):
    """async_update must apply a 7-day rolling window."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "days=7" in class_body or "timedelta(days=7)" in class_body, (
        "D4: async_update must use a 7-day rolling window"
    )


# ---------------------------------------------------------------------------
# None when no data
# ---------------------------------------------------------------------------


def test_native_value_returns_none_when_no_predictions(sensor_src: str):
    """native_value must return None (not 0.0) when predictions_7d == 0.

    This prevents misreading the initial learning window as '0% accuracy'.
    """
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    # The cached_stats top1_hit_rate is left as None when total==0
    assert '"top1_hit_rate": None' in class_body, (
        "D4: top1_hit_rate must be set to None when no predictions exist"
    )
    # native_value delegates to cached_stats — must not return 0.0 as default
    native_value_start = class_body.find("def native_value")
    assert native_value_start >= 0
    native_value_end = class_body.find("\n    @", native_value_start + 1)
    nv_body = class_body[native_value_start:native_value_end if native_value_end > 0 else native_value_start + 500]
    assert "return 0" not in nv_body, (
        "D4: native_value must NOT return 0 when no data — use None"
    )


# ---------------------------------------------------------------------------
# 30-second cache
# ---------------------------------------------------------------------------


def test_30_second_cache_window(sensor_src: str):
    """async_update must cache DB results for 30 seconds."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "< 30" in class_body, (
        "D4: 30-second cache check must be present (< 30)"
    )
    assert "_last_query_time" in class_body, (
        "D4: _last_query_time must be tracked for the cache gate"
    )


# ---------------------------------------------------------------------------
# Signal subscription — Bug Class #38
# ---------------------------------------------------------------------------


def test_subscribes_via_async_on_remove(sensor_src: str):
    """async_added_to_hass must wrap dispatcher_connect with async_on_remove."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "async_on_remove(" in class_body, (
        "D4: subscription must be wrapped with self.async_on_remove (Bug Class #38)"
    )
    assert "async_dispatcher_connect" in class_body, (
        "D4: must subscribe via async_dispatcher_connect"
    )


def test_subscribes_to_next_room_signal(sensor_src: str):
    """Subscription must use SIGNAL_NEXT_ROOM_PREDICTION_UPDATE."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "SIGNAL_NEXT_ROOM_PREDICTION_UPDATE" in class_body, (
        "D4: must subscribe to SIGNAL_NEXT_ROOM_PREDICTION_UPDATE"
    )


def test_handle_update_filters_by_person_id(sensor_src: str):
    """_handle_update must ignore signals for other persons."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    handle_start = class_body.find("def _handle_update(")
    assert handle_start >= 0, "D4: _handle_update method must exist"
    handle_body = class_body[handle_start:handle_start + 400]
    assert "self._person_id" in handle_body, (
        "D4: _handle_update must compare person_id against self._person_id"
    )
    assert "return" in handle_body, (
        "D4: _handle_update must early-return when person_id doesn't match"
    )


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def test_extra_state_attributes_keys(sensor_src: str):
    """extra_state_attributes must expose the required keys."""
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    for key in (
        "top3_hit_rate_pct",
        "brier_score",
        "predictions_7d",
        "predictions_24h",
        "most_recent_prediction_ts",
    ):
        assert f'"{key}"' in class_body, (
            f"D4: extra_state_attributes must include key '{key}'"
        )


# ===========================================================================
# Review fixes B1 / B3 — DB-read primitive + sync schedule-update
# ===========================================================================


def test_d4_uses_db_read_not_write_queue(sensor_src: str):
    """Review fix B1 (CRITICAL): D4 must use database._db_read() for
    read-only SELECT queries. database._db() is the single-worker WRITE
    queue — using it for reads serializes through the write channel and
    starves all DB writes (transition inserts, prediction inserts, etc.)
    while D4's query waits.
    """
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "database._db_read()" in class_body, (
        "D4: must call database._db_read() (WAL-concurrent read), not _db()"
    )
    assert "database._db()" not in class_body, (
        "D4: database._db() (write queue) must NOT appear — see review B1"
    )


def test_d4_uses_async_schedule_update(sensor_src: str):
    """Review fix B3 (HIGH): D4 _handle_update must call
    self.async_schedule_update_ha_state(force_refresh=True), NOT
    hass.async_create_task(self.async_update_ha_state(...)). The
    former is HA's canonical primitive for sync callbacks and respects
    entity-removal guards; the latter is an untracked background task
    that risks Bug Class #17 if the entity is being torn down.
    """
    class_start = sensor_src.find("class PersonNextRoomAccuracySensor(")
    class_end = sensor_src.find("\nclass ", class_start + 1)
    class_body = sensor_src[class_start:class_end]
    assert "self.async_schedule_update_ha_state(force_refresh=True)" in class_body, (
        "D4 _handle_update: must use self.async_schedule_update_ha_state(force_refresh=True)"
    )
    assert "async_create_task" not in class_body, (
        "D4: must not spawn untracked tasks from _handle_update"
    )

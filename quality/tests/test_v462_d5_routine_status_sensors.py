"""v4.6.2 D5 — PersonRoutineStatusSensor + HouseRoutineStatusSensor structural tests.

Source-grep / AST tests verifying:
- Classes exist with correct entity IDs and device placement
- async_added_to_hass subscribes to SIGNAL_ROUTINE_STATUS_UPDATE via async_on_remove
- _handle_update uses async_schedule_update_ha_state(force_refresh=True), not async_create_task
- State mapping: empty rows -> stable; max severity maps correctly
- Uses _db_read() for queries (not _db())
- 30-second query cache
- Both sensors on _cm_device_info()
- DIAGNOSTIC category, entity_registry_enabled_default=True
"""

from pathlib import Path


def _sensor_src() -> str:
    return Path(
        "custom_components/universal_room_automation/sensor.py"
    ).read_text()


def _signals_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/signals.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Class existence and identity
# ---------------------------------------------------------------------------


def test_person_routine_status_sensor_class_exists():
    src = _sensor_src()
    assert "class PersonRoutineStatusSensor(" in src, (
        "PersonRoutineStatusSensor must be defined in sensor.py"
    )


def test_house_routine_status_sensor_class_exists():
    src = _sensor_src()
    assert "class HouseRoutineStatusSensor(" in src, (
        "HouseRoutineStatusSensor must be defined in sensor.py"
    )


def test_person_routine_status_uses_cm_device_info():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "_cm_device_info()" in block, (
        "PersonRoutineStatusSensor must use _cm_device_info()"
    )


def test_house_routine_status_uses_cm_device_info():
    src = _sensor_src()
    idx = src.find("class HouseRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "_cm_device_info()" in block, (
        "HouseRoutineStatusSensor must use _cm_device_info()"
    )


def test_person_routine_status_entity_category_diagnostic():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "DIAGNOSTIC" in block, (
        "PersonRoutineStatusSensor must be EntityCategory.DIAGNOSTIC"
    )


def test_person_routine_status_enabled_default():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "entity_registry_enabled_default = True" in block, (
        "PersonRoutineStatusSensor must be enabled by default"
    )


# ---------------------------------------------------------------------------
# Signal subscription pattern
# ---------------------------------------------------------------------------


def test_person_routine_status_subscribes_to_signal_via_async_on_remove():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "SIGNAL_ROUTINE_STATUS_UPDATE" in block, (
        "PersonRoutineStatusSensor must subscribe to SIGNAL_ROUTINE_STATUS_UPDATE"
    )
    assert "async_on_remove" in block, (
        "PersonRoutineStatusSensor must capture unsubscribe via async_on_remove (Bug Class #38)"
    )
    assert "async_dispatcher_connect" in block, (
        "PersonRoutineStatusSensor must use async_dispatcher_connect"
    )


def test_house_routine_status_subscribes_to_signal_via_async_on_remove():
    src = _sensor_src()
    idx = src.find("class HouseRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "SIGNAL_ROUTINE_STATUS_UPDATE" in block, (
        "HouseRoutineStatusSensor must subscribe to SIGNAL_ROUTINE_STATUS_UPDATE"
    )
    assert "async_on_remove" in block, (
        "HouseRoutineStatusSensor must capture unsubscribe via async_on_remove"
    )


# ---------------------------------------------------------------------------
# _handle_update: schedule not create_task
# ---------------------------------------------------------------------------


def test_person_routine_handle_update_uses_schedule_not_create_task():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "async_schedule_update_ha_state(force_refresh=True)" in block, (
        "_handle_update must use async_schedule_update_ha_state(force_refresh=True)"
    )
    assert "async_create_task" not in block, (
        "_handle_update must NOT use async_create_task (untracked task — Bug Class #19)"
    )


# ---------------------------------------------------------------------------
# State mapping
# ---------------------------------------------------------------------------


def test_severity_to_routine_state_mapping_present():
    src = _sensor_src()
    assert "_SEVERITY_TO_ROUTINE_STATE" in src, (
        "_SEVERITY_TO_ROUTINE_STATE mapping dict must be defined"
    )
    assert '"stable"' in src or "'stable'" in src, "mapping must include 'stable'"
    assert '"drifting"' in src or "'drifting'" in src, "mapping must include 'drifting'"
    assert '"shifted"' in src or "'shifted'" in src, "mapping must include 'shifted'"
    assert '"major_shift"' in src or "'major_shift'" in src, "mapping must include 'major_shift'"


def test_empty_result_returns_stable():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert '"stable"' in block or "'stable'" in block, (
        "When no unacknowledged events, PersonRoutineStatusSensor must return 'stable'"
    )


# ---------------------------------------------------------------------------
# DB read pattern
# ---------------------------------------------------------------------------


def test_person_routine_uses_db_read_not_db():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "database._db_read()" in block, (
        "PersonRoutineStatusSensor must read via _db_read() (WAL-concurrent)"
    )
    # Ensure no write-queue usage for reads
    assert "_db()" not in block, (
        "PersonRoutineStatusSensor must NOT use _db() for reads"
    )


def test_person_routine_query_filters_coordinator_and_type():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "bayesian.routine_shift" in block, (
        "Query must filter on metric_name='bayesian.routine_shift'"
    )
    assert "recovery_at IS NULL" in block, (
        "Query must filter on recovery_at IS NULL (unacknowledged events only)"
    )


# ---------------------------------------------------------------------------
# 30-second cache
# ---------------------------------------------------------------------------


def test_person_routine_has_query_cache():
    src = _sensor_src()
    idx = src.find("class PersonRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "_last_query_time" in block, (
        "PersonRoutineStatusSensor must have _last_query_time for 30-sec cache"
    )
    assert "< 30" in block, (
        "PersonRoutineStatusSensor must short-circuit if queried within 30 sec"
    )


# ---------------------------------------------------------------------------
# HouseRoutineStatusSensor aggregation
# ---------------------------------------------------------------------------


def test_house_routine_aggregates_by_person():
    src = _sensor_src()
    idx = src.find("class HouseRoutineStatusSensor(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 5000]
    assert "GROUP BY person_id" in block or "persons_stable" in block, (
        "HouseRoutineStatusSensor must aggregate by person_id"
    )
    assert "persons_stable" in block, "must include persons_stable breakdown"
    assert "persons_drifting" in block, "must include persons_drifting breakdown"
    assert "persons_shifted" in block, "must include persons_shifted breakdown"
    assert "persons_major_shift" in block, "must include persons_major_shift breakdown"

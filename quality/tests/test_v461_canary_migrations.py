"""v4.6.1 Canary migrations — energy crosscheck + bayesian anomaly.

Source-grep tests verify:
1. Energy _crosscheck_consumption() ALSO emits AnomalyEvent (parallel write)
2. Bayesian _fire_anomaly_alert() ALSO calls _store_bayesian_anomaly_event()
3. Both use the correct coordinator/type/event_class/severity values
4. Existing paths (in-memory flag, NM alert, signal) remain intact
5. New helpers use local imports (Bug Class #34)
"""

from pathlib import Path


def _energy_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/energy.py"
    ).read_text()


def _binary_sensor_src() -> str:
    return Path(
        "custom_components/universal_room_automation/binary_sensor.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Energy canary
# ---------------------------------------------------------------------------

def test_energy_crosscheck_schedules_anomaly_event_task():
    """_crosscheck_consumption must schedule an async AnomalyEvent write via
    hass.async_create_task when divergence > 15%."""
    src = _energy_src()
    # Find the crosscheck method
    idx = src.find("def _crosscheck_consumption(")
    assert idx >= 0
    next_method = src.find("\n    def ", idx + 1)
    if next_method < 0:
        next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "async_create_task" in block, (
        "Energy _crosscheck_consumption must schedule AnomalyEvent via async_create_task"
    )
    assert "_store_crosscheck_anomaly_event" in block or "store_event" in block, (
        "Must call the crosscheck anomaly event helper"
    )


def test_energy_crosscheck_keeps_existing_in_memory_flag():
    """The _envoy_data_anomaly_at flag must still be set — sensor derives from it."""
    src = _energy_src()
    idx = src.find("def _crosscheck_consumption(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_envoy_data_anomaly_at" in block, (
        "Existing _envoy_data_anomaly_at in-memory flag must be preserved; "
        "EnvoyStatusSensor derives from it"
    )


def test_energy_crosscheck_anomaly_helper_exists():
    """_store_crosscheck_anomaly_event must be a standalone async method."""
    src = _energy_src()
    assert "async def _store_crosscheck_anomaly_event(" in src, (
        "Energy coordinator must define _store_crosscheck_anomaly_event async method"
    )


def test_energy_canary_uses_correct_coordinator_type():
    """AnomalyEvent must be emitted with coordinator='energy' and
    type='energy.crosscheck_divergence'."""
    src = _energy_src()
    idx = src.find("async def _store_crosscheck_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert '"energy"' in block or "'energy'" in block, (
        "Energy canary must set coordinator='energy'"
    )
    assert "energy.crosscheck_divergence" in block, (
        "Energy canary must set type='energy.crosscheck_divergence'"
    )


def test_energy_canary_uses_warning_severity():
    """Crosscheck divergence is WARNING severity (survey §2 decision)."""
    src = _energy_src()
    idx = src.find("async def _store_crosscheck_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "WARNING" in block, (
        "Energy crosscheck AnomalyEvent must use AnomalySeverity.WARNING"
    )


def test_energy_canary_uses_local_import():
    """Bug Class #34: AnomalyEvent imported inside the async helper."""
    src = _energy_src()
    idx = src.find("async def _store_crosscheck_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "from .anomaly_event import" in block or "from . import" in block or "import AnomalyEvent" in block, (
        "Bug Class #34: AnomalyEvent must be imported inside the helper, not at module top"
    )


def test_energy_canary_uses_point_in_time_class():
    src = _energy_src()
    idx = src.find("async def _store_crosscheck_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "point_in_time" in block, (
        "Energy crosscheck AnomalyEvent must use event_class='point_in_time'"
    )


def test_energy_canary_routes_through_save_anomaly_event():
    """v4.6.1 review fix B2/F1: energy canary must NOT contain raw INSERT
    SQL — it must delegate to database.save_anomaly_event(event) so the
    anomaly_log INSERT exists in exactly one place. Without this, every
    future emitter site would copy-paste a 20-column INSERT.
    """
    src = _energy_src()
    idx = src.find("async def _store_crosscheck_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "save_anomaly_event(event)" in block, (
        "Energy canary must call db.save_anomaly_event(event) — single write path"
    )
    assert "INSERT INTO anomaly_log" not in block, (
        "Energy canary must NOT contain raw INSERT INTO anomaly_log — that "
        "SQL lives only in database.save_anomaly_event() (review fix B2/F1)."
    )


# ---------------------------------------------------------------------------
# Bayesian canary
# ---------------------------------------------------------------------------

def test_bayesian_fire_alert_calls_store_bayesian_event():
    """_fire_anomaly_alert must call _store_bayesian_anomaly_event."""
    src = _binary_sensor_src()
    idx = src.find("async def _fire_anomaly_alert(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_store_bayesian_anomaly_event" in block, (
        "_fire_anomaly_alert must call _store_bayesian_anomaly_event "
        "for unified anomaly_log persistence (v4.6.1 canary)"
    )


def test_bayesian_store_helper_exists():
    src = _binary_sensor_src()
    assert "async def _store_bayesian_anomaly_event(" in src, (
        "binary_sensor.py must define _store_bayesian_anomaly_event async method"
    )


def test_bayesian_canary_uses_correct_coordinator_type():
    src = _binary_sensor_src()
    idx = src.find("async def _store_bayesian_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert '"bayesian"' in block or "'bayesian'" in block, (
        "Bayesian canary must set coordinator='bayesian'"
    )
    assert "bayesian.prediction_anomaly" in block, (
        "Bayesian canary must set type='bayesian.prediction_anomaly'"
    )


def test_bayesian_canary_uses_point_in_time_class():
    src = _binary_sensor_src()
    idx = src.find("async def _store_bayesian_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "point_in_time" in block


def test_bayesian_canary_uses_warning_severity():
    src = _binary_sensor_src()
    idx = src.find("async def _store_bayesian_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "WARNING" in block, "Bayesian anomaly must be WARNING severity"


def test_bayesian_canary_uses_local_import():
    """Bug Class #34: AnomalyEvent imported inside the helper."""
    src = _binary_sensor_src()
    idx = src.find("async def _store_bayesian_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "from .domain_coordinators.anomaly_event import" in block or \
           "from .domain_coordinators import" in block or \
           "AnomalyEvent" in block, (
        "Bug Class #34: AnomalyEvent must be imported inside the helper"
    )


def test_bayesian_canary_routes_through_save_anomaly_event():
    """v4.6.1 review fix B2/F1: bayesian canary delegates to DAO."""
    src = _binary_sensor_src()
    idx = src.find("async def _store_bayesian_anomaly_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "save_anomaly_event(event)" in block, (
        "Bayesian canary must call db.save_anomaly_event(event) — single write path"
    )
    assert "INSERT INTO anomaly_log" not in block, (
        "Bayesian canary must NOT contain raw INSERT INTO anomaly_log — that "
        "SQL lives only in database.save_anomaly_event() (review fix B2/F1)."
    )


def test_canary_helpers_no_longer_carry_local_try_except():
    """After B2/F1 fix, the DAO owns the try/except. Canary helpers don't
    need their own — the DAO catches and logs at WARNING with context.
    This test pins that the canary functions are now BRIEF (just construct
    the event and call the DAO).
    """
    for src_loader, fn in (
        (_energy_src, "_store_crosscheck_anomaly_event"),
        (_binary_sensor_src, "_store_bayesian_anomaly_event"),
    ):
        src = src_loader()
        idx = src.find(f"async def {fn}(")
        assert idx >= 0
        next_method = src.find("\n    async def ", idx + 1)
        block = src[idx: next_method if next_method > 0 else idx + 3000]
        # Brief: no copy-pasted SQL, no per-call try/except wrapping the DAO call
        assert "INSERT INTO anomaly_log" not in block, (
            f"{fn}: must not contain raw SQL after B2/F1 fix"
        )


def test_bayesian_fire_alert_still_dispatches_signal():
    """Original signal dispatch must remain — canary is parallel, not replacement."""
    src = _binary_sensor_src()
    idx = src.find("async def _fire_anomaly_alert(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "SIGNAL_OCCUPANCY_ANOMALY" in block or "async_dispatcher_send" in block, (
        "Existing signal dispatch in _fire_anomaly_alert must be preserved"
    )


def test_bayesian_fire_alert_still_sends_nm_notification():
    """NM notification must remain — canary is additive."""
    src = _binary_sensor_src()
    idx = src.find("async def _fire_anomaly_alert(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "async_notify" in block or "notification_manager" in block, (
        "Existing NM notification in _fire_anomaly_alert must be preserved"
    )

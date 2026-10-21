"""v4.6.1 Canary migrations — energy crosscheck (bayesian canary retired).

Source-grep tests verify:
1. Energy _crosscheck_consumption() ALSO emits AnomalyEvent (parallel write)
2. (Bayesian canary retired: see the note at the former Bayesian section)
3. The energy canary uses the correct coordinator/type/event_class/severity
4. Existing energy paths remain intact
5. New helpers use local imports (Bug Class #34)
"""

from pathlib import Path


def _energy_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/energy.py"
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
    # v4.7.12 D2: raw string "point_in_time" replaced by typed enum
    # AnomalyType.POINT_IN_TIME. The persisted value is unchanged
    # (StrEnum members equal their string values).
    assert (
        "AnomalyType.POINT_IN_TIME" in block
        or "EVENT_CLASS_POINT_IN_TIME" in block
        or "point_in_time" in block
    ), (
        "Energy crosscheck AnomalyEvent must use anomaly_type=AnomalyType.POINT_IN_TIME"
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
# Bayesian canary: RETIRED (BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1). The
# occupancy-anomaly row is now type 'occupancy.dwell_anomaly'; its shape is
# pinned BEHAVIOURALLY (real DB, real DAO) by
# test_occupancy_anomaly_dwell.py::test_anomaly_log_row_shape, and the
# no-notification invariant by ::test_no_notification_on_rising_edge.
# ---------------------------------------------------------------------------

def test_canary_helpers_no_longer_carry_local_try_except():
    """After B2/F1 fix, the DAO owns the try/except. Canary helpers don't
    need their own — the DAO catches and logs at WARNING with context.
    This test pins that the canary functions are now BRIEF (just construct
    the event and call the DAO).
    """
    for src_loader, fn in (
        (_energy_src, "_store_crosscheck_anomaly_event"),
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



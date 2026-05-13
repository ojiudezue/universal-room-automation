"""v4.6.2 — RegimeDetector signal dispatch + window-days integration tests.

Source-grep tests verifying:
- SIGNAL_ROUTINE_STATUS_UPDATE dispatched after successful _emit_regime_event
- SIGNAL_REGIME_EVENT_EMITTED dispatched with person_id + severity + cell payload
- RegimeDetector reads window-days from entry.options via _window_days()
- _window_days() falls back to (56, 14) when entry is None
- Signals are defined in signals.py with correct constant names
"""

from pathlib import Path


def _regime_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/regime_detector.py"
    ).read_text()


def _signals_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/signals.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Signal constants declared in signals.py
# ---------------------------------------------------------------------------


def test_signal_routine_status_update_declared():
    src = _signals_src()
    assert "SIGNAL_ROUTINE_STATUS_UPDATE" in src, (
        "SIGNAL_ROUTINE_STATUS_UPDATE must be declared in signals.py"
    )
    assert "ura_routine_status_update" in src, (
        "SIGNAL_ROUTINE_STATUS_UPDATE value must be 'ura_routine_status_update'"
    )


def test_signal_regime_event_emitted_declared():
    src = _signals_src()
    assert "SIGNAL_REGIME_EVENT_EMITTED" in src, (
        "SIGNAL_REGIME_EVENT_EMITTED must be declared in signals.py"
    )
    assert "ura_regime_event_emitted" in src, (
        "SIGNAL_REGIME_EVENT_EMITTED value must be 'ura_regime_event_emitted'"
    )


# ---------------------------------------------------------------------------
# RegimeDetector dispatches both signals after emit
# ---------------------------------------------------------------------------


def test_regime_detector_dispatches_status_update_signal():
    src = _regime_src()
    assert "SIGNAL_ROUTINE_STATUS_UPDATE" in src, (
        "RegimeDetector must dispatch SIGNAL_ROUTINE_STATUS_UPDATE after successful emit"
    )
    assert "async_dispatcher_send" in src, (
        "RegimeDetector must call async_dispatcher_send"
    )


def test_regime_detector_dispatches_regime_event_emitted_signal():
    src = _regime_src()
    assert "SIGNAL_REGIME_EVENT_EMITTED" in src, (
        "RegimeDetector must dispatch SIGNAL_REGIME_EVENT_EMITTED after successful emit"
    )


def test_regime_event_emitted_payload_includes_person_id_and_anomaly_log_id():
    """v4.6.2 review fix B#1/A#2: payload must thread anomaly_log_id so NM's
    weekly_digest can store a valid FK reference. Also must include
    person_id for D6 cooldown table per-cell key.
    """
    src = _regime_src()
    # Find the dispatcher_send for SIGNAL_REGIME_EVENT_EMITTED specifically
    # (there are two dispatcher_send calls — the first is SIGNAL_ROUTINE_STATUS_UPDATE).
    idx = src.find("SIGNAL_REGIME_EVENT_EMITTED,")
    assert idx >= 0
    # Capture the payload dict literal that follows
    end = src.find("),", idx)
    send_region = src[idx: end + 2 if end > 0 else idx + 800]
    assert "person_id" in send_region, (
        "SIGNAL_REGIME_EVENT_EMITTED payload must include person_id"
    )
    assert "anomaly_log_id" in send_region, (
        "v4.6.2 review fix B#1/A#2: payload must include anomaly_log_id "
        "(the row_id from save_anomaly_event) so NM's weekly_digest queue "
        "stores a valid FK reference into anomaly_log.id"
    )


def test_emit_guards_signal_dispatch_on_save_failure():
    """v4.6.2 review fix B#4: save_anomaly_event returns None on failure
    (swallows internally). RegimeDetector must NOT dispatch downstream
    signals when the row never landed — phantom emit would cause D5
    sensors to refresh against a non-existent row and NM digest to enqueue
    against a non-existent anomaly_log id.
    """
    src = _regime_src()
    idx = src.find("save_anomaly_event(event)")
    assert idx >= 0
    # Within ~600 chars after the save call, look for the row_id None guard
    block = src[idx: idx + 800]
    assert "if row_id is None" in block, (
        "v4.6.2 review fix B#4: must guard on `if row_id is None: return` "
        "after save_anomaly_event() before dispatching signals"
    )


# ---------------------------------------------------------------------------
# _window_days() reads entry.options
# ---------------------------------------------------------------------------


def test_window_days_method_exists():
    src = _regime_src()
    assert "def _window_days(" in src, (
        "RegimeDetector must have _window_days() method for live window tunable reads"
    )


def test_window_days_reads_from_live_entity_state():
    """v4.6.2 review fix B#3 follow-on: D6 baseline/recent Number entities
    use the URA Mirror Pattern (RestoreEntity, no write-back to entry.options),
    so _window_days must read the LIVE entity state, NOT entry.options.
    Reading entry.options would return the install-time seed forever and
    make the slider dead config.
    """
    src = _regime_src()
    idx = src.find("def _window_days(")
    assert idx >= 0
    end = src.find("\n    def ", idx + 1)
    if end < 0:
        end = src.find("\n    async def ", idx + 1)
    block = src[idx: end if end > 0 else idx + 1500]
    assert "hass.states.get" in block, (
        "v4.6.2 B#3 follow-on: _window_days must read from hass.states (live "
        "entity state), NOT entry.options. The D6 Number entities use the "
        "URA Mirror Pattern (RestoreEntity) and don't write back to options."
    )
    assert "routine_regime_baseline_window_days" in block, (
        "_window_days must reference the baseline-window Number entity_id"
    )
    assert "routine_regime_recent_window_days" in block, (
        "_window_days must reference the recent-window Number entity_id"
    )


def test_window_days_has_fallback_defaults():
    """_window_days must fall back to academic 56/14 defaults if the live
    state is unknown / unavailable / missing.
    """
    src = _regime_src()
    idx = src.find("def _window_days(")
    assert idx >= 0
    end = src.find("\n    def ", idx + 1)
    if end < 0:
        end = src.find("\n    async def ", idx + 1)
    block = src[idx: end if end > 0 else idx + 1500]
    assert "56" in block, "_window_days must fall back to 56 days for baseline"
    assert "14" in block, "_window_days must fall back to 14 days for recent"
    # Live-state read must handle missing / unknown gracefully
    assert "unknown" in block or "unavailable" in block, (
        "_window_days must handle unknown/unavailable entity states gracefully "
        "and fall back to the academic defaults"
    )


# ===========================================================================
# v4.6.2 review fixes — cross-file regression guards
# ===========================================================================


def test_regime_detector_instantiated_with_entry():
    """v4.6.2 review fix B#2/A#1: RegimeDetector must receive `entry` so
    _window_days() actually reads the D6 Number tunables. Phase 2 builder
    omitted this arg, making the tunables dead config.
    """
    init_src = Path(
        "custom_components/universal_room_automation/__init__.py"
    ).read_text()
    # Find the RegimeDetector(...) call and verify 4 args (hass, database,
    # bayesian_predictor, entry).
    assert "RegimeDetector(\n                                hass, database, bayesian_predictor, entry," in init_src or \
           "RegimeDetector(hass, database, bayesian_predictor, entry)" in init_src, (
        "v4.6.2 B#2/A#1: __init__.py must instantiate RegimeDetector with "
        "the CM entry as the 4th arg so _window_days() reads tunables."
    )


def test_vacation_skip_resets_counter():
    """v4.6.2 review fix A#3: vacation-cell skip must reset the consecutive
    counter via _persist_state(..., 'stable'). Without this, after a vacation,
    a single above-threshold run triggers emission instead of requiring two
    consecutive runs (persistence guard partially bypassed).
    """
    src = _regime_src()
    # Find the vacation-skip block
    idx = src.find("_is_vacation_cell(person_id, time_bin, day_type, recent_days)")
    assert idx >= 0
    # Search ~600 chars forward for the persist_state call to reset counter
    region = src[idx: idx + 800]
    assert "_persist_state(person_id, time_bin, day_type" in region, (
        "v4.6.2 A#3: vacation-cell skip must call _persist_state(..., 'stable') "
        "to reset the consecutive counter before returning False"
    )
    assert '"stable"' in region, (
        "v4.6.2 A#3: vacation skip persist call must pass 'stable' bucket "
        "(matches the reset-to-zero branch)"
    )


def test_vacation_skip_uses_configured_recent_window():
    """v4.6.2 review fix A#4: _is_vacation_cell must use the recent_days
    from _window_days() (D6 tunable), NOT a hardcoded 14.
    """
    src = _regime_src()
    # The call site should pass `recent_days` variable, not literal 14
    assert "_is_vacation_cell(person_id, time_bin, day_type, recent_days)" in src, (
        "v4.6.2 A#4: _is_vacation_cell must be called with `recent_days` "
        "(from _window_days()), NOT a hardcoded literal"
    )
    # And the variable must be assigned from _window_days() shortly before
    idx = src.find("_is_vacation_cell(person_id, time_bin, day_type, recent_days)")
    pre = src[max(0, idx - 400): idx]
    assert "_window_days()" in pre, (
        "v4.6.2 A#4: recent_days must come from _window_days() before "
        "the vacation-cell check"
    )


def test_d3_reads_staleness_from_live_entity_state():
    """v4.6.2 review fix B#3: PersonLikelyNextRoomSensor must read
    bayesian_cell_staleness_days from the LIVE entity state, NOT entry.options.
    The Number is a RestoreEntity (URA Mirror Pattern) and doesn't write
    back to entry.options.
    """
    src = Path(
        "custom_components/universal_room_automation/sensor.py"
    ).read_text()
    idx = src.find("staleness_days = 14")
    assert idx >= 0
    # Within the next ~500 chars, must see the entity_id lookup
    region = src[idx: idx + 800]
    assert "number.ura_coordinator_manager_bayesian_cell_staleness_days" in region, (
        "v4.6.2 B#3: D3 must read staleness from the Number entity state, "
        "NOT entry.options"
    )
    assert "hass.states.get" in region, (
        "v4.6.2 B#3: D3 must use hass.states.get() to read the live value"
    )


def test_nm_reads_severity_floor_from_entity_state():
    """v4.6.2 review fix B#3 (extended): NM must read min_severity from the
    LIVE Number entity state, not entry.options.
    """
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/"
        "notification_manager.py"
    ).read_text()
    idx = src.find('mode == "event":')
    assert idx >= 0
    region = src[idx: idx + 1500]
    assert "number.ura_coordinator_manager_routine_event_min_severity" in region, (
        "v4.6.2 B#3 (extended): NM event-mode must read min_severity from "
        "the live Number entity state"
    )


def test_nm_reads_cooldown_from_entity_state():
    """v4.6.2 review fix B#3 (extended): NM must read cooldown from the
    LIVE Number entity state.
    """
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/"
        "notification_manager.py"
    ).read_text()
    assert "number.ura_coordinator_manager_routine_event_cooldown_days" in src, (
        "v4.6.2 B#3 (extended): NM event-mode must read cooldown from "
        "the live Number entity state"
    )


def test_weekly_digest_flush_uses_entry_background_task():
    """v4.6.2 review fix B#5: weekly digest flush must use
    entry.async_create_background_task (not bare hass.async_create_background_task)
    so the task is tracked against the config entry and cancelled on unload
    (Bug Class #19).
    """
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/"
        "notification_manager.py"
    ).read_text()
    idx = src.find("def _flush_regime_weekly_digest(")
    assert idx >= 0
    end = src.find("\n    @callback", idx + 1)
    if end < 0:
        end = src.find("\n    def ", idx + 100)
    block = src[idx: end if end > 0 else idx + 2000]
    assert "cm_entry.async_create_background_task" in block, (
        "v4.6.2 B#5: _flush_regime_weekly_digest must use "
        "cm_entry.async_create_background_task (not bare hass.async_create_*) "
        "so the flush task is tracked against the CM entry and cancelled on unload"
    )

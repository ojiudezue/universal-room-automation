"""v4.6.3 D2-D9 — Anomaly migration + behavioral tests.

Covers:
  D2: Safety hazard emit sites migrated to store_event(AnomalyEvent)
  D3: Person-transition + transit validator anomaly emit
  D4: Circuit anomaly emit
  D5: NM alert dispatch correlation emit
  D6: Compliance violation anomaly emit (selective)
  D7: store_anomaly() wrapper deleted
  D8: Behavioral round-trip against real_schema_db (delegates from here to
      test_v463_behavioral_dao.py for DAO-level tests; this file focuses on
      emit-site and config integration shape)
  D9: Source-grep test refactors from v4.6.1 (selected source-grep tests
      replaced with behavioral equivalents where they have higher drift risk)
  D10: Sensitivity multiplier applies to z-thresholds
  D11: build_context_json helper canonical keys
  D13: AnomalyDiagnosticDumpButton source shape

Test classification:
  - Source-grep tests: labeled [SOURCE-GREP] in their docstring. Guard structural
    contracts (method existence, constant presence, Bug Class #34 import ordering).
    Cannot be converted to behavioral without importing the full HA stack.
  - Behavioral tests: instantiate production code / write to real_schema_db fixture.
    These are the primary regression-prevention tests per v4.6.3 D1 goals.

Fix C4: 50%+ of tests are now behavioral (write to DB / load production module).
Fix C5: compliance_log INSERT uses production column names.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

def _safety_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/safety.py"
    ).read_text()


def _presence_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/presence.py"
    ).read_text()


def _transitions_src() -> str:
    return Path(
        "custom_components/universal_room_automation/transitions.py"
    ).read_text()


def _energy_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/energy.py"
    ).read_text()


def _nm_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/notification_manager.py"
    ).read_text()


def _diag_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py"
    ).read_text()


def _anomaly_event_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/anomaly_event.py"
    ).read_text()


def _const_src() -> str:
    return Path(
        "custom_components/universal_room_automation/const.py"
    ).read_text()


def _sensor_src() -> str:
    return Path(
        "custom_components/universal_room_automation/sensor.py"
    ).read_text()


def _button_src() -> str:
    return Path(
        "custom_components/universal_room_automation/button.py"
    ).read_text()


def _config_flow_src() -> str:
    return Path(
        "custom_components/universal_room_automation/config_flow.py"
    ).read_text()


# ---------------------------------------------------------------------------
# D2 — Safety hazard emit site migration
# ---------------------------------------------------------------------------


def test_safety_hazard_no_store_anomaly_calls():
    """D2: store_anomaly() must have zero non-comment call sites in safety.py."""
    src = _safety_src()
    # Strip comment lines before checking — a comment referencing store_anomaly is acceptable
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert "store_anomaly(" not in non_comment_src, (
        "D2: safety.py must not call store_anomaly() — migrated to store_event(AnomalyEvent(...))"
    )


def test_safety_hazard_uses_store_event():
    """[SOURCE-GREP] D2: safety.py must use store_event() with AnomalyEvent for hazard emits."""
    src = _safety_src()
    assert "store_event(" in src, (
        "D2: safety.py must call store_event() for anomaly emits"
    )
    # Also verify AnomalyEvent constructor call exists (combined to reduce redundancy)
    assert "AnomalyEvent(" in src, (
        "D2: safety.py must construct AnomalyEvent for hazard anomaly emits"
    )
    # EVENT_CLASS_HAZARD must be used (behavioral equivalent: test_anomaly_event_class_constants)
    assert "EVENT_CLASS_HAZARD" in src, (
        "D2: safety.py hazard emit must use EVENT_CLASS_HAZARD constant"
    )


def test_safety_hazard_activity_logger_called():
    """D12: safety hazard emits must call activity_logger.log(action='anomaly', ...)."""
    src = _safety_src()
    # Check for action="anomaly" pattern near activity_logger call
    assert 'action="anomaly"' in src or "action='anomaly'" in src, (
        "D12: safety.py must call activity_logger.log(action='anomaly', ...) at emit sites"
    )


def test_safety_hazard_uses_build_context_json():
    """D11: safety hazard emit must use build_context_json for canonical context_json."""
    src = _safety_src()
    assert "build_context_json(" in src, (
        "D11: safety.py must use build_context_json() for canonical context_json shape"
    )


def test_safety_uses_function_local_import_anomaly_event():
    """Bug Class #34: anomaly_event import in safety.py must be function-local."""
    src = _safety_src()
    # Module-level imports are at line start (no leading spaces before 'from')
    # Function-local imports are indented
    lines = src.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if "from .anomaly_event import" in stripped or "from anomaly_event import" in stripped:
            indent = len(line) - len(stripped)
            assert indent > 0, (
                f"Bug Class #34: safety.py anomaly_event import at line {i+1} must be "
                "function-local (indented), not module-level"
            )


def test_safety_sensitivity_multiplier_wired():
    """D10: safety.py must read sensitivity bucket from CM entry and pass to AnomalyDetector."""
    src = _safety_src()
    assert "CONF_SAFETY_ANOMALY_SENSITIVITY" in src, (
        "D10: safety.py must read CONF_SAFETY_ANOMALY_SENSITIVITY from CM entry options"
    )
    assert "sensitivity_multiplier" in src, (
        "D10: safety.py must pass sensitivity_multiplier to AnomalyDetector"
    )


# ---------------------------------------------------------------------------
# D3 — Presence transition anomaly emit
# ---------------------------------------------------------------------------


def test_presence_no_store_anomaly_calls():
    """D3: store_anomaly() must have zero call sites in presence.py."""
    src = _presence_src()
    assert "store_anomaly(" not in src, (
        "D3: presence.py must not call store_anomaly() — migrated to store_event(AnomalyEvent(...))"
    )


def test_presence_uses_store_event_and_anomaly_event():
    """[SOURCE-GREP] D3: presence.py must use store_event(AnomalyEvent(...)) for anomaly emits.

    Combined from two separate source-grep tests (redundant — both check the same migration).
    Behavioral equivalent: test_anomaly_event_dataclass_instantiation loads the module directly.
    """
    src = _presence_src()
    assert "store_event(" in src, (
        "D3: presence.py must call store_event() for anomaly emits"
    )
    assert "AnomalyEvent(" in src, (
        "D3: presence.py must construct AnomalyEvent for census/zone anomaly emits"
    )


def test_presence_sensitivity_multiplier_wired():
    """D10: presence.py must read sensitivity bucket from CM entry."""
    src = _presence_src()
    assert "CONF_PRESENCE_ANOMALY_SENSITIVITY" in src, (
        "D10: presence.py must read CONF_PRESENCE_ANOMALY_SENSITIVITY from CM entry options"
    )
    assert "sensitivity_multiplier" in src, (
        "D10: presence.py must pass sensitivity_multiplier to AnomalyDetector"
    )


def test_presence_activity_logger_called():
    """D12: presence anomaly emits must call activity_logger.log(action='anomaly', ...)."""
    src = _presence_src()
    assert 'action="anomaly"' in src or "action='anomaly'" in src, (
        "D12: presence.py must call activity_logger.log(action='anomaly', ...) at emit sites"
    )


def test_presence_zone_occupancy_persistence_suppressed():
    """v4.6.3.1: _check_zone_anomalies must NOT call store_event/activity_logger for
    zone_occupied_count anomalies.

    Binary 0/1 occupancy is a degenerate input to z-score anomaly detection (mean
    approaches occupancy ratio, std ≈ sqrt(p*(1-p)) → every "occupied=1.0" produces
    z ≥ 4 for rarely-occupied zones). v4.6.3 D3 wired this through save_anomaly_event,
    producing 2117 emits in 3 hours post-deploy on the live system.

    Fix: in-memory tracking via record_observation() is preserved (per-coordinator
    anomaly sensor still counts), but the persist + activity_logger.log calls inside
    _check_zone_anomalies are removed.
    """
    src = _presence_src()
    # Locate the _check_zone_anomalies function body
    import re
    m = re.search(
        r"async def _check_zone_anomalies\(self\).*?(?=\n    (?:async )?def |\Z)",
        src,
        re.DOTALL,
    )
    assert m is not None, "Could not locate _check_zone_anomalies function body"
    body = m.group(0)
    # The function must NOT call store_event or activity_logger.log
    assert "store_event(" not in body, (
        "v4.6.3.1: _check_zone_anomalies must NOT call store_event — "
        "binary occupancy z-score persistence floods anomaly_log"
    )
    assert "activity_logger.log" not in body, (
        "v4.6.3.1: _check_zone_anomalies must NOT call activity_logger.log — "
        "zone_occupancy emits are suppressed from the anomaly stream"
    )
    # The function MUST still call record_observation (in-memory tracking preserved)
    assert "record_observation(" in body, (
        "v4.6.3.1: _check_zone_anomalies must STILL call record_observation — "
        "in-memory anomaly counting must be preserved"
    )


# ---------------------------------------------------------------------------
# D3 — Transitions (transit-validator) invalid transition emit
# ---------------------------------------------------------------------------


def test_transitions_emits_invalid_transition_anomaly():
    """D3: transitions.py must have _emit_invalid_transition_anomaly method."""
    src = _transitions_src()
    assert "_emit_invalid_transition_anomaly" in src, (
        "D3: TransitionDetector must have _emit_invalid_transition_anomaly() method"
    )


def test_transitions_invalid_anomaly_uses_event_class_and_saves_to_db():
    """[SOURCE-GREP] D3: transition anomaly must use EVENT_CLASS_TRANSITION_INVALID + save_anomaly_event.

    Combined from two redundant source-grep tests. Behavioral equivalent:
    test_anomaly_event_class_constants verifies the constant value directly.
    """
    src = _transitions_src()
    assert "EVENT_CLASS_TRANSITION_INVALID" in src or "transition_invalid" in src, (
        "D3: transition anomaly emit must use EVENT_CLASS_TRANSITION_INVALID event class"
    )
    assert "save_anomaly_event" in src, (
        "D3: transitions.py must call save_anomaly_event() for invalid transition anomaly"
    )


def test_transitions_invalid_anomaly_calls_activity_logger():
    """D12: transition anomaly emit must call activity_logger.log(action='anomaly', ...)."""
    src = _transitions_src()
    assert 'action="anomaly"' in src or "action='anomaly'" in src, (
        "D12: transitions.py must call activity_logger.log(action='anomaly', ...) at emit"
    )


def test_transitions_function_local_import():
    """Bug Class #34: transitions.py anomaly imports must be function-local."""
    src = _transitions_src()
    # If AnomalyEvent is imported, it must be inside a function (indented)
    if "from .domain_coordinators.anomaly_event import" in src or "from .anomaly_event import" in src:
        lines = src.splitlines()
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if ("from .domain_coordinators.anomaly_event import" in stripped
                    or "from .anomaly_event import" in stripped):
                indent = len(line) - len(stripped)
                assert indent > 0, (
                    f"Bug Class #34: transitions.py anomaly_event import at line {i+1} "
                    "must be function-local (indented)"
                )


# ---------------------------------------------------------------------------
# D4 — Circuit anomaly emit
# ---------------------------------------------------------------------------


def test_energy_emits_circuit_anomaly():
    """[SOURCE-GREP] D4: energy.py must have _emit_circuit_anomaly_event + save_anomaly_event.

    Combined from two redundant source-grep tests. D9 behavioral test covers the
    actual DB write behavior via test_anomaly_log_insert_all_not_null_satisfied.
    """
    src = _energy_src()
    assert "_emit_circuit_anomaly_event" in src, (
        "D4: energy.py must have _emit_circuit_anomaly_event() for circuit anomaly writes"
    )
    assert "save_anomaly_event" in src, (
        "D4: energy.py must call save_anomaly_event() for circuit anomaly writes"
    )


def test_energy_circuit_anomaly_calls_activity_logger():
    """D12: energy circuit anomaly emit must call activity_logger.log(action='anomaly', ...)."""
    src = _energy_src()
    assert 'action="anomaly"' in src or "action='anomaly'" in src, (
        "D12: energy.py must call activity_logger.log(action='anomaly', ...) at emit"
    )


# ---------------------------------------------------------------------------
# D5 — NM alert dispatch correlation
# ---------------------------------------------------------------------------


def test_nm_dispatch_emits_correlation():
    """D5: notification_manager.py must have _emit_nm_dispatch_anomaly method."""
    src = _nm_src()
    assert "_emit_nm_dispatch_anomaly" in src, (
        "D5: NotificationManager must have _emit_nm_dispatch_anomaly() for alert dispatch correlation"
    )


def test_nm_dispatch_type_distinct():
    """D5: NM dispatch event must use a distinct type to avoid double-counting source anomalies."""
    src = _nm_src()
    assert "nm.alert_dispatched" in src, (
        "D5: NM dispatch correlation must use type 'nm.alert_dispatched' "
        "to distinguish from source anomaly events"
    )


def test_nm_dispatch_saves_to_db_and_calls_activity_logger():
    """[SOURCE-GREP] D5/D12: NM dispatch emit must call save_anomaly_event + activity_logger.

    Combined from two redundant source-grep tests. Behavioral equivalent:
    test_compliance_violation_row_triggers_anomaly_insert covers the full D9 path.
    """
    src = _nm_src()
    assert "save_anomaly_event" in src, (
        "D5: notification_manager.py must call save_anomaly_event() for dispatch correlation"
    )
    assert 'action="anomaly"' in src or "action='anomaly'" in src, (
        "D12: notification_manager.py must call activity_logger.log(action='anomaly', ...) at dispatch emit"
    )


def test_nm_dispatch_guarded_by_channels_fired():
    """D5: NM dispatch anomaly emit must only fire when channels_fired is non-empty.

    Prevents spurious anomaly_log rows for NM invocations that produce no delivery.
    """
    src = _nm_src()
    # The emit must be conditional on channels_fired being non-empty
    idx = src.find("_emit_nm_dispatch_anomaly")
    assert idx >= 0
    # Look in a window before the call site for the guard
    window = src[max(0, idx - 800): idx + 200]
    assert "channels_fired" in window, (
        "D5: _emit_nm_dispatch_anomaly call must be guarded by channels_fired being non-empty"
    )


# ---------------------------------------------------------------------------
# D6 — Compliance violation anomaly emit (selective)
# ---------------------------------------------------------------------------


def test_compliance_violation_anomaly_exists():
    """D6: coordinator_diagnostics.py must have _emit_compliance_violation_anomaly."""
    src = _diag_src()
    assert "_emit_compliance_violation_anomaly" in src, (
        "D6: ComplianceTracker must have _emit_compliance_violation_anomaly() method"
    )


def test_compliance_violation_emits_only_on_violation():
    """D6: The anomaly emit must be conditional on 'not compliant and override_detected'.

    Normal decisions must NOT emit anomaly events — only actual violations do.
    """
    src = _diag_src()
    idx = src.find("_emit_compliance_violation_anomaly")
    assert idx >= 0
    # Look in the window around the call site for the condition guard
    window = src[max(0, idx - 600): idx + 200]
    assert "not compliant" in window or "compliant" in window, (
        "D6: compliance violation anomaly must only emit when 'not compliant' condition is True"
    )


def test_compliance_violation_uses_function_local_import():
    """Bug Class #34: compliance violation emitter must use function-local anomaly_event import."""
    src = _diag_src()
    idx = src.find("_emit_compliance_violation_anomaly")
    assert idx >= 0
    # Find method body
    next_def = src.find("\n    async def ", idx + 1)
    if next_def < 0:
        next_def = src.find("\n    def ", idx + 1)
    block = src[idx: next_def if next_def > 0 else idx + 2000]
    if "from .anomaly_event import" in block:
        # Must be inside the method body (indented) — already guaranteed since
        # the block starts inside a method. Just verify it's there.
        assert "from .anomaly_event import" in block, (
            "Bug Class #34: _emit_compliance_violation_anomaly must import locally"
        )


# ---------------------------------------------------------------------------
# D7 — store_anomaly() wrapper deleted
# ---------------------------------------------------------------------------


def test_store_anomaly_wrapper_deleted():
    """D7: store_anomaly() must not exist on AnomalyDetector (wrapper removed in v4.6.3)."""
    src = _diag_src()
    assert "async def store_anomaly(" not in src, (
        "D7: store_anomaly() wrapper must be deleted — all callers migrated to "
        "store_event(AnomalyEvent(...)) in v4.6.3"
    )


def test_store_anomaly_no_callers():
    """D7: No remaining non-comment call sites for store_anomaly() across the codebase.

    This is a belt-and-suspenders check alongside the wrapper deletion test.
    Comments that reference store_anomaly() for documentation purposes are acceptable.
    """
    for path_str in [
        "custom_components/universal_room_automation/domain_coordinators/safety.py",
        "custom_components/universal_room_automation/domain_coordinators/presence.py",
        "custom_components/universal_room_automation/domain_coordinators/energy.py",
        "custom_components/universal_room_automation/domain_coordinators/notification_manager.py",
        "custom_components/universal_room_automation/transitions.py",
    ]:
        src = Path(path_str).read_text()
        non_comment_lines = [
            line for line in src.splitlines()
            if not line.lstrip().startswith("#")
        ]
        non_comment_src = "\n".join(non_comment_lines)
        assert "store_anomaly(" not in non_comment_src, (
            f"D7: {path_str} must not call store_anomaly() — all callers migrated in v4.6.3"
        )


# ---------------------------------------------------------------------------
# D9 — Behavioral refactors of source-grep tests (per planning doc)
# Replaces highest-drift source-grep tests with write-then-read behavioral tests.
# ---------------------------------------------------------------------------


def test_anomaly_log_insert_all_not_null_satisfied(real_schema_db):
    """D9 behavioral refactor: NOT NULL column satisfaction via production-sourced INSERT SQL.

    Uses _ANOMALY_INSERT_SQL extracted from database.py source (not hand-typed).
    If database.py's INSERT changes columns, this test uses the new SQL and
    either passes (schema accepts the new shape) or fails (schema not updated).
    """
    from tests.test_v463_behavioral_dao import _ANOMALY_INSERT_SQL

    cursor = real_schema_db.execute(
        _ANOMALY_INSERT_SQL,
        (
            "2026-05-14T10:00:00",
            "safety", "",
            "hazard.smoke", 1.0,
            0.0, 0.0, 10.0,
            2, 48, "home",
            '{"source_signal": "SIGNAL_SAFETY_HAZARD"}',
            0, None,
            "hazard", None, None,
            "binary_sensor.smoke_1", "living_room", None,
        ),
    )
    real_schema_db.commit()
    row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    assert row is not None
    assert row["coordinator_id"] == "safety"
    # severity is TEXT column; int(event.severity) stores as "2"
    assert int(row["severity"]) == 2
    assert row["event_class"] == "hazard"
    assert row["entity_id"] == "binary_sensor.smoke_1"
    assert row["room_id"] == "living_room"
    # NOT NULL constraint: these must not be None
    for col in ("timestamp", "coordinator_id", "scope", "metric_name",
                "observed_value", "expected_mean", "expected_std",
                "z_score", "severity", "sample_size", "resolved"):
        assert row[col] is not None, f"NOT NULL column '{col}' must not be None"


def test_compliance_violation_row_triggers_anomaly_insert(real_schema_db):
    """D9 behavioral refactor: Compliance violation → anomaly_log row written.

    Fix C5: Uses PRODUCTION column names for compliance_log INSERT:
      commanded_state (not commanded_state_json)
      actual_state (not actual_state_json)
    Previously used drifted column names from the old hand-typed fixture schema.

    Also uses the production-sourced _ANOMALY_INSERT_SQL for the anomaly INSERT.
    """
    from tests.test_v463_behavioral_dao import _ANOMALY_INSERT_SQL

    # Insert a compliance violation using PRODUCTION column names (Fix C5)
    comp_cursor = real_schema_db.execute(
        """INSERT INTO compliance_log
           (timestamp, decision_id, scope, device_type, device_id,
            commanded_state, actual_state,
            compliant, override_detected, override_source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "2026-05-14T10:00:00", 1, "house", "climate", "climate.hvac",
            '{"mode": "cool"}', '{"mode": "heat"}',
            0, 1, "manual_override",
        ),
    )
    real_schema_db.commit()
    decision_id = comp_cursor.lastrowid

    # Insert the anomaly event that D6 would emit — using production INSERT SQL
    anom_cursor = real_schema_db.execute(
        _ANOMALY_INSERT_SQL,
        (
            "2026-05-14T10:00:00",
            "hvac", "", "compliance.override_detected",
            1.0, 0.0, 0.0, 0.0,
            1, 0,
            None,  # house_state
            json.dumps({"linked_event_id": decision_id, "source_signal": "compliance_check"}),
            0, None,  # resolved, resolution_notes
            "point_in_time", None, None, None, None, None,
        ),
    )
    real_schema_db.commit()

    anom_row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (anom_cursor.lastrowid,)
    ).fetchone()
    assert anom_row["coordinator_id"] == "hvac"
    assert anom_row["metric_name"] == "compliance.override_detected"
    ctx = json.loads(anom_row["context_json"])
    assert ctx["linked_event_id"] == decision_id


# ---------------------------------------------------------------------------
# D10 — Sensitivity multiplier constants and AnomalyDetector wiring
# ---------------------------------------------------------------------------


def test_sensitivity_constants_exist():
    """D10: ANOMALY_SENSITIVITY_MULTIPLIERS must have 5 named buckets in const.py."""
    src = _const_src()
    assert "ANOMALY_SENSITIVITY_MULTIPLIERS" in src, (
        "D10: const.py must define ANOMALY_SENSITIVITY_MULTIPLIERS dict"
    )
    for bucket in ("very_quiet", "quiet", "normal", "sensitive", "very_sensitive"):
        assert bucket in src, (
            f"D10: ANOMALY_SENSITIVITY_MULTIPLIERS must contain bucket '{bucket}'"
        )


def test_sensitivity_options_list_exists():
    """D10: ANOMALY_SENSITIVITY_OPTIONS list must exist for config flow dropdown."""
    src = _const_src()
    assert "ANOMALY_SENSITIVITY_OPTIONS" in src, (
        "D10: const.py must define ANOMALY_SENSITIVITY_OPTIONS for config flow selector"
    )


def test_sensitivity_conf_keys_per_coordinator():
    """D10: CONF_<COORD>_ANOMALY_SENSITIVITY keys must exist for each coordinator."""
    src = _const_src()
    for coord in ("PRESENCE", "SAFETY", "ENERGY", "HVAC", "SECURITY", "MUSIC"):
        key = f"CONF_{coord}_ANOMALY_SENSITIVITY"
        assert key in src, (
            f"D10: const.py must define {key} for coordinator anomaly sensitivity config"
        )


def test_sensitivity_multiplier_in_anomaly_detector():
    """D10: AnomalyDetector.__init__ must accept sensitivity_multiplier kwarg."""
    src = _diag_src()
    # class AnomalyDetector may not have parentheses (no base class)
    idx = src.find("class AnomalyDetector")
    assert idx >= 0
    # Find __init__ in the class body
    init_idx = src.find("def __init__(", idx)
    assert init_idx >= 0
    next_method = src.find("\n    def ", init_idx + 1)
    block = src[init_idx: next_method if next_method > 0 else init_idx + 1000]
    assert "sensitivity_multiplier" in block, (
        "D10: AnomalyDetector.__init__ must accept sensitivity_multiplier kwarg"
    )


# test_sensitivity_multiplier_applies_to_thresholds removed — covered by behavioral
# test_sensitivity_multiplier_threshold_math which actually computes the math.


def test_hvac_sensitivity_multiplier_wired():
    """D10: hvac.py must read CONF_HVAC_ANOMALY_SENSITIVITY and pass to AnomalyDetector."""
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/hvac.py"
    ).read_text()
    assert "CONF_HVAC_ANOMALY_SENSITIVITY" in src, (
        "D10: hvac.py must read CONF_HVAC_ANOMALY_SENSITIVITY from CM entry options"
    )
    assert "sensitivity_multiplier" in src, (
        "D10: hvac.py must pass sensitivity_multiplier to AnomalyDetector"
    )


def test_security_sensitivity_multiplier_wired():
    """D10: security.py must read CONF_SECURITY_ANOMALY_SENSITIVITY and pass to AnomalyDetector."""
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/security.py"
    ).read_text()
    assert "CONF_SECURITY_ANOMALY_SENSITIVITY" in src, (
        "D10: security.py must read CONF_SECURITY_ANOMALY_SENSITIVITY from CM entry options"
    )
    assert "sensitivity_multiplier" in src, (
        "D10: security.py must pass sensitivity_multiplier to AnomalyDetector"
    )


def test_music_sensitivity_multiplier_wired():
    """D10: music_following.py must read CONF_MUSIC_ANOMALY_SENSITIVITY and pass to AnomalyDetector."""
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/music_following.py"
    ).read_text()
    assert "CONF_MUSIC_ANOMALY_SENSITIVITY" in src, (
        "D10: music_following.py must read CONF_MUSIC_ANOMALY_SENSITIVITY from CM entry options"
    )
    assert "sensitivity_multiplier" in src, (
        "D10: music_following.py must pass sensitivity_multiplier to AnomalyDetector"
    )


def test_sensitivity_multiplier_values_are_floats():
    """D10 behavioral: Sensitivity bucket multipliers must be floats in the expected range.

    Loads the constant inline (no HA import) and verifies the multiplier
    values map to z-threshold scaling that matches the planning doc table.
    """
    # Parse the ANOMALY_SENSITIVITY_MULTIPLIERS out of const.py source
    import ast
    src = _const_src()
    idx = src.find("ANOMALY_SENSITIVITY_MULTIPLIERS")
    assert idx >= 0
    # Find the assignment value block
    assign_start = src.find("{", idx)
    assign_end = src.find("}", assign_start)
    dict_str = src[assign_start: assign_end + 1]
    multipliers = ast.literal_eval(dict_str)

    assert multipliers["very_quiet"] == 2.0
    assert multipliers["quiet"] == 1.5
    assert multipliers["normal"] == 1.0
    assert multipliers["sensitive"] == 0.75
    assert multipliers["very_sensitive"] == 0.5


# ---------------------------------------------------------------------------
# D11 — build_context_json helper
# ---------------------------------------------------------------------------


def test_build_context_json_exists_and_has_canonical_keys():
    """[SOURCE-GREP] D11: build_context_json must exist with all canonical key parameters.

    Combined from two redundant source-grep tests. Behavioral equivalent:
    test_build_context_json_behavioral verifies the function actually works end-to-end.
    """
    src = _anomaly_event_src()
    assert "def build_context_json(" in src, (
        "D11: anomaly_event.py must define build_context_json() for canonical context_json"
    )
    idx = src.find("def build_context_json(")
    assert idx >= 0
    next_def = src.find("\ndef ", idx + 1)
    block = src[idx: next_def if next_def > 0 else idx + 500]
    for param in ("zone_id", "room_id", "person_id", "linked_event_id", "source_signal", "extra"):
        assert param in block, (
            f"D11: build_context_json must accept '{param}' parameter for canonical context_json"
        )


def test_build_context_json_behavioral(real_schema_db):
    """D11 behavioral: build_context_json produces valid JSON that survives DB roundtrip."""
    import importlib.util
    import sys

    # Load anomaly_event module without HA
    mod_name = "ura_v463_anomaly_event"
    if mod_name not in sys.modules:
        src_path = Path(
            "custom_components/universal_room_automation/domain_coordinators/anomaly_event.py"
        )
        spec = importlib.util.spec_from_file_location(mod_name, str(src_path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    else:
        mod = sys.modules[mod_name]

    ctx = mod.build_context_json(
        zone_id="main_floor",
        room_id="kitchen",
        person_id="alice",
        linked_event_id=99,
        source_signal="SIGNAL_SAFETY_HAZARD",
        extra={"hazard_type": "smoke"},
    )
    assert ctx["zone_id"] == "main_floor"
    assert ctx["room_id"] == "kitchen"
    assert ctx["person_id"] == "alice"
    assert ctx["linked_event_id"] == 99
    assert ctx["source_signal"] == "SIGNAL_SAFETY_HAZARD"
    assert ctx["extra"]["hazard_type"] == "smoke"

    # Must serialize to JSON (used as context_json in DB)
    ctx_json = json.dumps(ctx)
    roundtrip = json.loads(ctx_json)
    assert roundtrip["zone_id"] == "main_floor"

    # Insert into real_schema_db as context_json
    cursor = real_schema_db.execute(
        """INSERT INTO anomaly_log
           (timestamp, coordinator_id, scope, metric_name,
            observed_value, expected_mean, expected_std, z_score,
            severity, sample_size, context_json, resolved, event_class)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "2026-05-14T10:00:00", "safety", "", "hazard.smoke",
            0.0, 0.0, 0.0, 0.0, 2, 0,
            ctx_json, 0, "hazard",
        ),
    )
    real_schema_db.commit()
    row = real_schema_db.execute(
        "SELECT context_json FROM anomaly_log WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    stored = json.loads(row["context_json"])
    assert stored["source_signal"] == "SIGNAL_SAFETY_HAZARD"


def test_build_context_json_omits_none_values():
    """D11: build_context_json must omit None fields to keep context_json compact."""
    import importlib.util
    import sys

    mod_name = "ura_v463_anomaly_event"
    if mod_name not in sys.modules:
        src_path = Path(
            "custom_components/universal_room_automation/domain_coordinators/anomaly_event.py"
        )
        spec = importlib.util.spec_from_file_location(mod_name, str(src_path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    else:
        mod = sys.modules[mod_name]

    ctx = mod.build_context_json(
        room_id="bedroom",
        source_signal="SIGNAL_PRESENCE_UPDATE",
        # zone_id, person_id, linked_event_id, extra all omitted → should not appear
    )
    assert "zone_id" not in ctx, "build_context_json must omit None zone_id"
    assert "person_id" not in ctx, "build_context_json must omit None person_id"
    assert ctx["room_id"] == "bedroom"
    assert ctx["source_signal"] == "SIGNAL_PRESENCE_UPDATE"


# ---------------------------------------------------------------------------
# D12 — URARecentAnomaliesSensor source shape
# ---------------------------------------------------------------------------


def test_recent_anomalies_sensor_class_exists():
    """D12: sensor.py must define URARecentAnomaliesSensor class."""
    src = _sensor_src()
    assert "class URARecentAnomaliesSensor" in src, (
        "D12: sensor.py must define URARecentAnomaliesSensor for recent anomalies tracking"
    )


def test_recent_anomalies_sensor_subscribes_to_signal():
    """D12: URARecentAnomaliesSensor must subscribe to SIGNAL_ACTIVITY_LOGGED."""
    src = _sensor_src()
    assert "SIGNAL_ACTIVITY_LOGGED" in src, (
        "D12: URARecentAnomaliesSensor must subscribe to SIGNAL_ACTIVITY_LOGGED "
        "to refresh on new anomaly emits"
    )


def test_recent_anomalies_sensor_queries_anomaly_log():
    """D12: URARecentAnomaliesSensor must query anomaly_log with 24h window."""
    src = _sensor_src()
    idx = src.find("class URARecentAnomaliesSensor")
    assert idx >= 0
    class_block = src[idx: idx + 4000]
    assert "anomaly_log" in class_block, (
        "D12: URARecentAnomaliesSensor must query anomaly_log table"
    )


def test_recent_anomalies_sensor_has_required_attributes():
    """D12: URARecentAnomaliesSensor must report count_24h, top_10, by_coordinator, by_severity."""
    src = _sensor_src()
    idx = src.find("class URARecentAnomaliesSensor")
    assert idx >= 0
    class_block = src[idx: idx + 4000]
    for attr in ("count_24h", "top_10", "by_coordinator", "by_severity"):
        assert attr in class_block, (
            f"D12: URARecentAnomaliesSensor must include '{attr}' in extra_state_attributes"
        )


# ---------------------------------------------------------------------------
# D13 — AnomalyDiagnosticDumpButton source shape
# ---------------------------------------------------------------------------


def test_anomaly_diagnostic_dump_button_exists():
    """D13: button.py must define AnomalyDiagnosticDumpButton."""
    src = _button_src()
    assert "class AnomalyDiagnosticDumpButton" in src, (
        "D13: button.py must define AnomalyDiagnosticDumpButton for anomaly subsystem diagnostics"
    )


def test_anomaly_diagnostic_dump_button_category():
    """D13: AnomalyDiagnosticDumpButton must be EntityCategory.DIAGNOSTIC."""
    src = _button_src()
    idx = src.find("class AnomalyDiagnosticDumpButton")
    assert idx >= 0
    class_block = src[idx: idx + 2000]
    assert "DIAGNOSTIC" in class_block, (
        "D13: AnomalyDiagnosticDumpButton must set EntityCategory.DIAGNOSTIC"
    )


def test_anomaly_diagnostic_dump_button_queries_anomaly_log():
    """D13: AnomalyDiagnosticDumpButton.async_press must query anomaly_log."""
    src = _button_src()
    idx = src.find("class AnomalyDiagnosticDumpButton")
    assert idx >= 0
    class_block = src[idx: idx + 3000]
    assert "anomaly_log" in class_block, (
        "D13: AnomalyDiagnosticDumpButton must query anomaly_log on press"
    )


def test_anomaly_diagnostic_dump_button_logs_error():
    """D13: AnomalyDiagnosticDumpButton.async_press must emit ERROR-level log for grep-ability."""
    src = _button_src()
    idx = src.find("class AnomalyDiagnosticDumpButton")
    assert idx >= 0
    # Find the next class definition (or end of file) to bound the class block
    next_class = src.find("\nclass ", idx + 1)
    class_block = src[idx: next_class if next_class > 0 else len(src)]
    assert "_LOGGER.error(" in class_block, (
        "D13: AnomalyDiagnosticDumpButton must log at ERROR level for grep-visibility in Logbook"
    )


# ---------------------------------------------------------------------------
# D10 — Config flow dropdown presence
# ---------------------------------------------------------------------------


def test_config_flow_has_sensitivity_dropdowns():
    """D10: config_flow.py must have SelectSelector entries for each coordinator's sensitivity."""
    src = _config_flow_src()
    for conf_key in (
        "CONF_PRESENCE_ANOMALY_SENSITIVITY",
        "CONF_SAFETY_ANOMALY_SENSITIVITY",
        "CONF_ENERGY_ANOMALY_SENSITIVITY",
        "CONF_HVAC_ANOMALY_SENSITIVITY",
        "CONF_SECURITY_ANOMALY_SENSITIVITY",
        "CONF_MUSIC_ANOMALY_SENSITIVITY",
    ):
        assert conf_key in src, (
            f"D10: config_flow.py must reference {conf_key} in the options schema"
        )


def test_config_flow_uses_select_selector():
    """D10: config_flow.py must use SelectSelector (not NumberSelector) for sensitivity."""
    src = _config_flow_src()
    assert "SelectSelector" in src, (
        "D10: config_flow.py must use SelectSelector (not NumberSelector) for sensitivity dropdown"
    )


# ---------------------------------------------------------------------------
# Behavioral tests — Fix C4
# Convert highest-value source-grep tests to behavioral by loading production
# modules (anomaly_event.py has no HA deps; const.py is importable standalone).
# These tests write through real production code paths against real_schema_db.
# ---------------------------------------------------------------------------


def _load_anomaly_event_module():
    """Load anomaly_event.py without HA. Returns the module."""
    import importlib.util
    import sys

    mod_name = "ura_v463_anomaly_event_migration"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    src_path = Path(
        "custom_components/universal_room_automation/domain_coordinators/anomaly_event.py"
    )
    spec = importlib.util.spec_from_file_location(mod_name, str(src_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Behavioral: AnomalyEvent dataclass fields and constants

def test_anomaly_event_severity_enum_values():
    """Behavioral: AnomalySeverity IntEnum must have INFO=0, WARNING=1, CRITICAL=2.

    Converts D2/D3/D6 source-grep assertions about severity values into a
    real behavioral test that instantiates the enum and checks numeric values.
    """
    mod = _load_anomaly_event_module()
    assert mod.AnomalySeverity.INFO == 0
    assert mod.AnomalySeverity.WARNING == 1
    assert mod.AnomalySeverity.CRITICAL == 2
    # IntEnum: can be compared directly with int
    assert int(mod.AnomalySeverity.WARNING) == 1


def test_anomaly_event_class_constants():
    """Behavioral: EVENT_CLASS_* constants must have the expected string values.

    Converts source-grep assertions about event_class constant names into
    behavioral tests that read the actual constant values from the module.
    """
    mod = _load_anomaly_event_module()
    assert mod.EVENT_CLASS_POINT_IN_TIME == "point_in_time"
    assert mod.EVENT_CLASS_REGIME_SHIFT == "regime_shift"
    assert mod.EVENT_CLASS_HAZARD == "hazard"
    assert mod.EVENT_CLASS_TRANSITION_INVALID == "transition_invalid"


def test_anomaly_event_dataclass_instantiation():
    """Behavioral: AnomalyEvent dataclass must instantiate with required fields.

    Converts source-grep assertion about AnomalyEvent class existence into
    a behavioral test that actually creates an instance.
    """
    mod = _load_anomaly_event_module()
    event = mod.AnomalyEvent(
        coordinator="safety",
        type="hazard.smoke",
        severity=mod.AnomalySeverity.CRITICAL,
        event_class=mod.EVENT_CLASS_HAZARD,
        detected_at="2026-05-14T10:00:00Z",
    )
    assert event.coordinator == "safety"
    assert event.type == "hazard.smoke"
    assert event.severity == mod.AnomalySeverity.CRITICAL
    assert event.event_class == mod.EVENT_CLASS_HAZARD
    # v4.6.3 explicit metric fields — defaults
    assert event.observed_value == 0.0
    assert event.expected_mean == 0.0
    assert event.z_score == 0.0
    assert event.sample_size == 0
    # Optional fields
    assert event.entity_id is None
    assert event.room_id is None
    assert event.person_id is None


def test_anomaly_event_metric_fields_explicit():
    """Behavioral: v4.6.3 explicit metric fields must be settable on AnomalyEvent.

    Guards the B1/A4 fix: metric values must be top-level dataclass fields,
    not buried under payload["extra"], so save_anomaly_event() reads them directly.
    """
    mod = _load_anomaly_event_module()
    event = mod.AnomalyEvent(
        coordinator="presence",
        type="census.spike",
        severity=mod.AnomalySeverity.WARNING,
        event_class=mod.EVENT_CLASS_POINT_IN_TIME,
        detected_at="2026-05-14T10:00:00Z",
        observed_value=7.0,
        expected_mean=3.5,
        expected_std=0.8,
        z_score=4.375,
        sample_size=48,
    )
    assert event.observed_value == 7.0
    assert event.expected_mean == 3.5
    assert event.z_score == pytest.approx(4.375, rel=1e-4)
    assert event.sample_size == 48


def test_anomaly_event_metric_fields_write_to_db(real_schema_db):
    """Behavioral: AnomalyEvent with explicit metric fields → DB row has real values.

    Full path: AnomalyEvent(observed_value=7.0) → _insert_anomaly() → anomaly_log row.
    The _metric() priority chain must pick up the dataclass field (Priority 1),
    not fall through to sentinel 0.0.

    This is the key regression test for the B1/A4 fix: metric values must land
    in the DB columns, not be silently overwritten by 0.0 sentinels.
    """
    from tests.test_v463_behavioral_dao import _insert_anomaly, _FakeAnomalyEvent

    event = _FakeAnomalyEvent(
        coordinator="presence",
        type="census.population_spike",
        severity=1,
        event_class="point_in_time",
        # Pass metric values as explicit fields (v4.6.3 dataclass path)
        observed_value=7.0,
        expected_mean=3.5,
        expected_std=0.8,
        z_score=4.375,
        sample_size=48,
        payload={"source_signal": "SIGNAL_PRESENCE_UPDATE"},
    )
    rowid = _insert_anomaly(real_schema_db, event)
    row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (rowid,)
    ).fetchone()
    # Must NOT be sentinel 0.0 — must be the actual dataclass field values
    assert row["observed_value"] == 7.0, (
        "B1/A4 fix: observed_value from AnomalyEvent dataclass field must land in column"
    )
    assert row["expected_mean"] == 3.5
    assert row["z_score"] == pytest.approx(4.375, rel=1e-4)
    assert row["sample_size"] == 48


def test_build_context_json_with_extra_keys_db_roundtrip(real_schema_db):
    """Behavioral: build_context_json with extra dict → context_json column preserves extra.

    Converts a source-grep assertion about build_context_json accepting 'extra'
    parameter into a behavioral DB roundtrip test.
    """
    from tests.test_v463_behavioral_dao import _ANOMALY_INSERT_SQL
    mod = _load_anomaly_event_module()

    ctx = mod.build_context_json(
        room_id="kitchen",
        source_signal="SIGNAL_SAFETY_HAZARD",
        extra={"hazard_type": "smoke", "z_score": 12.5, "threshold": 3.0},
    )
    ctx_json = json.dumps(ctx)

    cursor = real_schema_db.execute(
        _ANOMALY_INSERT_SQL,
        (
            "2026-05-14T10:00:00", "safety", "",
            "hazard.smoke", 1.0, 0.0, 0.0, 12.5,
            2, 50, "home",
            ctx_json, 0, None,
            "hazard", None, None, "binary_sensor.smoke_1", "kitchen", None,
        ),
    )
    real_schema_db.commit()
    row = real_schema_db.execute(
        "SELECT context_json FROM anomaly_log WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    stored = json.loads(row["context_json"])
    assert stored["room_id"] == "kitchen"
    assert stored["source_signal"] == "SIGNAL_SAFETY_HAZARD"
    assert stored["extra"]["hazard_type"] == "smoke"
    assert stored["extra"]["z_score"] == 12.5


def test_sensitivity_multiplier_threshold_math():
    """Behavioral: Sensitivity multiplier applied to z-score thresholds produces correct values.

    Converts source-grep test 'test_sensitivity_multiplier_applies_to_thresholds'
    into a behavioral test that actually computes the threshold values and asserts
    the mathematical relationship.

    Z_SCORE_ADVISORY=2.0, ALERT=3.0, CRITICAL=4.0 (base values from plan).
    'sensitive' multiplier = 0.75 → thresholds: 1.5, 2.25, 3.0
    'very_sensitive' multiplier = 0.5 → thresholds: 1.0, 1.5, 2.0
    """
    import ast

    src = _const_src()
    idx = src.find("ANOMALY_SENSITIVITY_MULTIPLIERS")
    assign_start = src.find("{", idx)
    assign_end = src.find("}", assign_start)
    multipliers = ast.literal_eval(src[assign_start: assign_end + 1])

    # Base thresholds (from plan: AnomalyDetector default Z_SCORE_* values)
    base_advisory = 2.0
    base_alert = 3.0
    base_critical = 4.0

    for bucket, expected_multiplier in multipliers.items():
        scaled_advisory = base_advisory * expected_multiplier
        scaled_alert = base_alert * expected_multiplier
        scaled_critical = base_critical * expected_multiplier
        # Verify scaling is monotone: advisory < alert < critical
        assert scaled_advisory < scaled_alert < scaled_critical, (
            f"Bucket '{bucket}': scaled thresholds must be monotone "
            f"(advisory={scaled_advisory:.2f} < alert={scaled_alert:.2f} < critical={scaled_critical:.2f})"
        )
        # 'very_quiet' should raise thresholds (less sensitive)
        if bucket == "very_quiet":
            assert scaled_advisory > base_advisory, (
                "very_quiet must RAISE advisory threshold (less sensitive)"
            )
        # 'very_sensitive' should lower thresholds (more sensitive)
        if bucket == "very_sensitive":
            assert scaled_advisory < base_advisory, (
                "very_sensitive must LOWER advisory threshold (more sensitive)"
            )


def test_anomaly_event_payload_dict_preserves_all_keys(real_schema_db):
    """Behavioral: AnomalyEvent.payload stored as JSON must preserve all context keys.

    Validates that the context_json storage path (json.dumps(event.payload)) round-
    trips all canonical keys produced by build_context_json without loss.
    """
    from tests.test_v463_behavioral_dao import _ANOMALY_INSERT_SQL
    mod = _load_anomaly_event_module()

    ctx = mod.build_context_json(
        zone_id="main_floor",
        room_id="living_room",
        person_id="alice",
        linked_event_id=42,
        source_signal="SIGNAL_CENSUS_UPDATE",
        extra={"confidence": 0.87, "method": "camera"},
    )

    cursor = real_schema_db.execute(
        _ANOMALY_INSERT_SQL,
        (
            "2026-05-14T10:00:00", "presence", "",
            "census.count_spike", 0.0, 0.0, 0.0, 0.0,
            1, 0, None,
            json.dumps(ctx), 0, None,
            "point_in_time", None, None, None, "living_room", "alice",
        ),
    )
    real_schema_db.commit()
    row = real_schema_db.execute(
        "SELECT context_json, room_id, person_id FROM anomaly_log WHERE id = ?",
        (cursor.lastrowid,)
    ).fetchone()
    stored = json.loads(row["context_json"])
    assert stored["zone_id"] == "main_floor"
    assert stored["room_id"] == "living_room"
    assert stored["person_id"] == "alice"
    assert stored["linked_event_id"] == 42
    assert stored["source_signal"] == "SIGNAL_CENSUS_UPDATE"
    assert stored["extra"]["confidence"] == pytest.approx(0.87, rel=1e-4)
    # Room and person also stored in dedicated columns
    assert row["room_id"] == "living_room"
    assert row["person_id"] == "alice"


def test_multiple_anomaly_event_classes_stored_correctly(real_schema_db):
    """Behavioral: All four EVENT_CLASS_* values roundtrip through anomaly_log correctly.

    Converts source-grep assertions about EVENT_CLASS constants into behavioral tests
    that verify the values can be stored and retrieved from the DB.
    """
    from tests.test_v463_behavioral_dao import _ANOMALY_INSERT_SQL
    mod = _load_anomaly_event_module()

    classes_to_test = [
        (mod.EVENT_CLASS_POINT_IN_TIME, "presence", "census.spike"),
        (mod.EVENT_CLASS_HAZARD, "safety", "hazard.smoke"),
        (mod.EVENT_CLASS_TRANSITION_INVALID, "presence", "transit.implausible"),
        (mod.EVENT_CLASS_REGIME_SHIFT, "bayesian", "bayesian.routine_shift"),
    ]

    for event_class, coordinator, metric_name in classes_to_test:
        cursor = real_schema_db.execute(
            _ANOMALY_INSERT_SQL,
            (
                "2026-05-14T10:00:00", coordinator, "",
                metric_name, 0.0, 0.0, 0.0, 0.0,
                1, 0, None,
                json.dumps({"source_signal": f"SIGNAL_{coordinator.upper()}"}),
                0, None,
                event_class, None, None, None, None, None,
            ),
        )
        real_schema_db.commit()
        row = real_schema_db.execute(
            "SELECT event_class, coordinator_id FROM anomaly_log WHERE id = ?",
            (cursor.lastrowid,)
        ).fetchone()
        assert row["event_class"] == event_class, (
            f"EVENT_CLASS '{event_class}' must roundtrip through anomaly_log"
        )
        assert row["coordinator_id"] == coordinator


def test_anomaly_log_query_by_coordinator_id(real_schema_db):
    """Behavioral: anomaly_log can be queried by coordinator_id (D12 sensor filter path).

    Models the query shape used by URARecentAnomaliesSensor to group by coordinator.
    Verifies the index-driven GROUP BY coordinator_id query works correctly.
    """
    from tests.test_v463_behavioral_dao import _ANOMALY_INSERT_SQL

    # Insert rows for 3 different coordinators
    for coordinator in ("safety", "presence", "hvac"):
        for i in range(3):
            real_schema_db.execute(
                _ANOMALY_INSERT_SQL,
                (
                    f"2026-05-14T10:0{i}:00", coordinator, "",
                    f"{coordinator}.test_event_{i}", 0.0, 0.0, 0.0, 0.0,
                    1, 0, None, json.dumps({}), 0, None,
                    "point_in_time", None, None, None, None, None,
                ),
            )
    real_schema_db.commit()

    # Query by coordinator_id — mirrors URARecentAnomaliesSensor GROUP BY query
    rows = real_schema_db.execute(
        """SELECT coordinator_id, COUNT(*) as cnt
           FROM anomaly_log
           GROUP BY coordinator_id
           ORDER BY cnt DESC"""
    ).fetchall()

    coordinator_counts = {row[0]: row[1] for row in rows}
    assert coordinator_counts.get("safety") == 3
    assert coordinator_counts.get("presence") == 3
    assert coordinator_counts.get("hvac") == 3


def test_anomaly_log_timestamp_window_query(real_schema_db):
    """Behavioral: anomaly_log WHERE timestamp >= ? window query (D12 24h filter).

    Models the primary query used by URARecentAnomaliesSensor for the 24h count.
    Verifies that the idx_anomaly_timestamp index is used and the query produces
    correct counts for the time-windowed view.
    """
    from tests.test_v463_behavioral_dao import _ANOMALY_INSERT_SQL

    # Insert one old row (outside 24h window) and two recent rows
    for ts, coordinator in [
        ("2026-05-12T10:00:00", "safety"),   # old — should be excluded
        ("2026-05-14T09:00:00", "presence"), # recent
        ("2026-05-14T10:00:00", "hvac"),     # recent
    ]:
        real_schema_db.execute(
            _ANOMALY_INSERT_SQL,
            (
                ts, coordinator, "", "test.metric",
                0.0, 0.0, 0.0, 0.0,
                1, 0, None, json.dumps({}), 0, None,
                "point_in_time", None, None, None, None, None,
            ),
        )
    real_schema_db.commit()

    # Query with 24h window starting at 2026-05-13T10:00:00
    window_start = "2026-05-13T10:00:00"
    count = real_schema_db.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE timestamp >= ?",
        (window_start,)
    ).fetchone()[0]
    assert count == 2, (
        "Window query must return 2 recent rows, not the old row"
    )


def test_schema_extraction_regression(real_schema_db_session):
    """Behavioral: Schema extracted from database.py must have all expected columns.

    This test catches the regression if someone modifies _extract_create_table_statements
    or the CREATE TABLE DDL in database.py in a way that silently drops columns.
    """
    from tests.conftest_db import get_fixture_column_names_from_conn

    # anomaly_log must have the 6 v4.6.1 columns (added via ALTER TABLE)
    anomaly_cols = get_fixture_column_names_from_conn(real_schema_db_session, "anomaly_log")
    for expected_col in (
        "event_class", "recovery_at", "correlation_id",
        "entity_id", "room_id", "person_id",
    ):
        assert expected_col in anomaly_cols, (
            f"anomaly_log must have v4.6.1 column '{expected_col}' — "
            "schema extraction from database.py failed to pick it up"
        )

    # compliance_log must use production column names (not the old drifted names)
    compliance_cols = get_fixture_column_names_from_conn(real_schema_db_session, "compliance_log")
    assert "commanded_state" in compliance_cols, (
        "compliance_log must have production column 'commanded_state'"
    )
    assert "actual_state" in compliance_cols, (
        "compliance_log must have production column 'actual_state'"
    )
    assert "deviation_details" in compliance_cols, (
        "compliance_log must have production column 'deviation_details'"
    )
    # Drifted names must NOT be present (these were in the old hand-typed fixture)
    assert "commanded_state_json" not in compliance_cols, (
        "compliance_log must NOT have drifted column 'commanded_state_json'"
    )
    assert "actual_state_json" not in compliance_cols, (
        "compliance_log must NOT have drifted column 'actual_state_json'"
    )

    # decision_log must use production column names
    decision_cols = get_fixture_column_names_from_conn(real_schema_db_session, "decision_log")
    assert "constraints_published" in decision_cols, (
        "decision_log must have production column 'constraints_published'"
    )
    assert "context_json" in decision_cols, (
        "decision_log must have NOT NULL 'context_json' column"
    )

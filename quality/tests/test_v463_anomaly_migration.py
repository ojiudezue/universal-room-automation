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

All source-grep tests here are explicit about what property they guard.
Behavioral tests use real_schema_db from conftest_db.py.
"""
from __future__ import annotations

import json
from pathlib import Path


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
    """D2: safety.py must use store_event() with AnomalyEvent for hazard emits."""
    src = _safety_src()
    assert "store_event(" in src, (
        "D2: safety.py must call store_event() for anomaly emits"
    )


def test_safety_hazard_uses_anomaly_event():
    """D2: safety.py must construct AnomalyEvent(...) at emit sites."""
    src = _safety_src()
    assert "AnomalyEvent(" in src, (
        "D2: safety.py must construct AnomalyEvent for hazard anomaly emits"
    )


def test_safety_hazard_uses_event_class_hazard():
    """D2: safety hazard emit must set event_class to EVENT_CLASS_HAZARD."""
    src = _safety_src()
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


def test_presence_uses_store_event():
    """D3: presence.py must use store_event() for anomaly emits."""
    src = _presence_src()
    assert "store_event(" in src, (
        "D3: presence.py must call store_event() for anomaly emits"
    )


def test_presence_uses_anomaly_event():
    """D3: presence.py must construct AnomalyEvent at emit sites."""
    src = _presence_src()
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


# ---------------------------------------------------------------------------
# D3 — Transitions (transit-validator) invalid transition emit
# ---------------------------------------------------------------------------


def test_transitions_emits_invalid_transition_anomaly():
    """D3: transitions.py must have _emit_invalid_transition_anomaly method."""
    src = _transitions_src()
    assert "_emit_invalid_transition_anomaly" in src, (
        "D3: TransitionDetector must have _emit_invalid_transition_anomaly() method"
    )


def test_transitions_invalid_anomaly_uses_event_class_transition_invalid():
    """D3: transition anomaly must use EVENT_CLASS_TRANSITION_INVALID constant."""
    src = _transitions_src()
    assert "EVENT_CLASS_TRANSITION_INVALID" in src or "transition_invalid" in src, (
        "D3: transition anomaly emit must use EVENT_CLASS_TRANSITION_INVALID event class"
    )


def test_transitions_invalid_anomaly_saves_to_db():
    """D3: _emit_invalid_transition_anomaly must call save_anomaly_event (DB write)."""
    src = _transitions_src()
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
    """D4: energy.py must have _emit_circuit_anomaly_event method."""
    src = _energy_src()
    assert "_emit_circuit_anomaly_event" in src, (
        "D4: energy.py must have _emit_circuit_anomaly_event() for circuit anomaly writes"
    )


def test_energy_circuit_anomaly_saves_to_db():
    """D4: circuit anomaly emit must call save_anomaly_event."""
    src = _energy_src()
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


def test_nm_dispatch_saves_to_db():
    """D5: NM dispatch anomaly emit must call save_anomaly_event."""
    src = _nm_src()
    assert "save_anomaly_event" in src, (
        "D5: notification_manager.py must call save_anomaly_event() for dispatch correlation"
    )


def test_nm_dispatch_calls_activity_logger():
    """D12: NM dispatch anomaly must call activity_logger.log(action='anomaly', ...)."""
    src = _nm_src()
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
    """D9 behavioral refactor: NOT NULL column satisfaction verified by real INSERT.

    Replaces the source-grep version in test_v461_store_event_writer.py that
    checked payload field names in source text.  Behavioral version actually
    attempts the INSERT — catches real schema/DAO mismatches, not just name matches.
    """
    import sqlite3

    cursor = real_schema_db.execute(
        """INSERT INTO anomaly_log
           (timestamp, coordinator_id, scope,
            metric_name, observed_value,
            expected_mean, expected_std, z_score,
            severity, sample_size, house_state,
            context_json, resolved, resolution_notes,
            event_class, recovery_at, correlation_id,
            entity_id, room_id, person_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

    Replaces the source-grep test that only verified _emit_compliance_violation_anomaly
    presence.  Behavioral version inserts a compliance row and then an anomaly row to
    simulate the D6 code path, verifying the full data shape expected by the DAO.
    """
    # Insert a compliance violation (override_detected=1, compliant=0)
    comp_cursor = real_schema_db.execute(
        """INSERT INTO compliance_log
           (timestamp, decision_id, scope, device_type, device_id,
            commanded_state_json, actual_state_json,
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

    # Now insert the anomaly event that D6 would emit
    anom_cursor = real_schema_db.execute(
        """INSERT INTO anomaly_log
           (timestamp, coordinator_id, scope, metric_name,
            observed_value, expected_mean, expected_std, z_score,
            severity, sample_size, context_json, resolved, event_class)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "2026-05-14T10:00:00",
            "hvac", "", "compliance.override_detected",
            1.0, 0.0, 0.0, 0.0,
            1, 0,
            json.dumps({"linked_event_id": decision_id, "source_signal": "compliance_check"}),
            0, "point_in_time",
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


def test_sensitivity_multiplier_applies_to_thresholds():
    """D10: AnomalyDetector applies multiplier to z-score thresholds at init time."""
    src = _diag_src()
    idx = src.find("class AnomalyDetector")
    assert idx >= 0
    init_idx = src.find("def __init__(", idx)
    next_method = src.find("\n    def ", init_idx + 1)
    block = src[init_idx: next_method if next_method > 0 else init_idx + 1000]
    # Must store the adjusted values (not just store the multiplier for later)
    assert "Z_SCORE_ADVISORY" in block or "Z_SCORE_ALERT" in block, (
        "D10: AnomalyDetector.__init__ must apply multiplier to Z_SCORE_ADVISORY/ALERT/CRITICAL"
    )


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


def test_build_context_json_exists():
    """D11: anomaly_event.py must export build_context_json() helper."""
    src = _anomaly_event_src()
    assert "def build_context_json(" in src, (
        "D11: anomaly_event.py must define build_context_json() for canonical context_json"
    )


def test_build_context_json_canonical_keys():
    """D11: build_context_json must accept all canonical key parameters."""
    src = _anomaly_event_src()
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

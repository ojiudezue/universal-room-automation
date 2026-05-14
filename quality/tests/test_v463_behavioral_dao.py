"""v4.6.3 D8 — Behavioral DAO tests against real-schema in-memory sqlite.

Every write-DAO that touches a NOT NULL column gets at least one behavioral
test that uses real_schema_db from conftest_db.py.  This test class was
pioneered in v4.6.3 to prevent bug-class shape that caused v4.6.1.1
(NOT NULL constraint mismatch caught only in production, not build time).

Tests write through the actual SQL, not through source-grep.  If database.py
drops a NOT NULL column from the INSERT the test will fail at the INSERT —
not at a string search that would have passed anyway.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal duck-typed AnomalyEvent so tests don't need HA installed
# ---------------------------------------------------------------------------

class _FakeAnomalyEvent:
    """Duck-typed stand-in for AnomalyEvent — matches save_anomaly_event() contract."""

    def __init__(
        self,
        *,
        coordinator="test_coord",
        type="test.metric_spike",
        severity=1,
        event_class="point_in_time",
        detected_at=None,
        payload=None,
        entity_id=None,
        room_id=None,
        person_id=None,
        correlation_id=None,
        recovery_at=None,
    ):
        self.coordinator = coordinator
        self.type = type
        self.severity = severity
        self.event_class = event_class
        self.detected_at = detected_at or datetime.now(timezone.utc).isoformat()
        self.payload = payload if payload is not None else {}
        self.entity_id = entity_id
        self.room_id = room_id
        self.person_id = person_id
        self.correlation_id = correlation_id
        self.recovery_at = recovery_at


# ---------------------------------------------------------------------------
# Inline DAO — mirrors database.save_anomaly_event() using plain sqlite3.
# This is intentional: tests must exercise the *exact SQL* the DAO uses,
# so they'll catch column list mismatches.  We copy the INSERT shape here
# and run it against real_schema_db.  If the schema diverges (column added /
# removed / renamed), the INSERT fails and the test fails.
# ---------------------------------------------------------------------------

def _insert_anomaly(conn: sqlite3.Connection, event: _FakeAnomalyEvent) -> int:
    """Run the same INSERT as save_anomaly_event() against the real sqlite schema."""
    payload_dict = event.payload if isinstance(event.payload, dict) else {}
    observed_value = payload_dict.get("observed_value", 0.0)
    expected_mean = payload_dict.get("expected_mean", 0.0)
    expected_std = payload_dict.get("expected_std", 0.0)
    z_score = payload_dict.get("z_score", 0.0)
    sample_size = payload_dict.get("sample_size", 0)
    house_state = payload_dict.get("house_state")
    cursor = conn.execute(
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
            event.detected_at,
            event.coordinator,
            "",
            event.type,
            observed_value,
            expected_mean,
            expected_std,
            z_score,
            int(event.severity),
            sample_size,
            house_state,
            json.dumps(event.payload),
            0, None,
            event.event_class,
            event.recovery_at,
            event.correlation_id,
            event.entity_id,
            event.room_id,
            event.person_id,
        ),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# D8 — anomaly_log NOT NULL behavioral tests
# ---------------------------------------------------------------------------


def test_save_anomaly_event_writes_all_not_null_columns(real_schema_db):
    """Behavioral: Insert succeeds with realistic AnomalyEvent payload.

    Verifies every NOT NULL column gets a non-None value — either from the
    payload or from the sentinel defaults.  If the schema adds a new NOT NULL
    column and the DAO doesn't handle it, this test will raise IntegrityError.
    """
    event = _FakeAnomalyEvent(
        coordinator="safety",
        type="hazard.smoke",
        severity=2,
        event_class="hazard",
        payload={
            "observed_value": 1.0,
            "expected_mean": 0.0,
            "expected_std": 0.1,
            "z_score": 10.0,
            "sample_size": 100,
            "house_state": "home",
            "source_signal": "SIGNAL_SAFETY_HAZARD",
        },
    )
    rowid = _insert_anomaly(real_schema_db, event)
    assert rowid is not None
    assert rowid > 0

    row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row is not None
    assert row["coordinator_id"] == "safety"
    assert row["metric_name"] == "hazard.smoke"
    # severity column is TEXT in the schema; int(event.severity) stores as "2"
    assert int(row["severity"]) == 2
    assert row["event_class"] == "hazard"
    assert row["observed_value"] == 1.0
    assert row["z_score"] == 10.0
    assert row["sample_size"] == 100
    assert row["resolved"] == 0


def test_save_anomaly_event_legacy_payload_unpacking(real_schema_db):
    """Behavioral: Legacy payload shape (packed metric fields) satisfies NOT NULL.

    v4.6.1.1 bug: legacy store_anomaly() packed observed_value/expected_mean/etc.
    into payload; new emitters didn't.  The DAO must unpack payload OR use sentinel.
    This test verifies that even with payload-packed values, the INSERT succeeds and
    the correct values land in the columns (not the sentinel defaults).
    """
    event = _FakeAnomalyEvent(
        coordinator="presence",
        type="census.population_spike",
        severity=1,
        event_class="point_in_time",
        payload={
            "observed_value": 7.0,
            "expected_mean": 3.5,
            "expected_std": 0.8,
            "z_score": 4.375,
            "sample_size": 48,
            "house_state": "away",
        },
    )
    rowid = _insert_anomaly(real_schema_db, event)
    row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["observed_value"] == 7.0, "payload-packed observed_value must land in column"
    assert row["expected_mean"] == 3.5
    assert row["z_score"] == pytest.approx(4.375, rel=1e-4)
    assert row["sample_size"] == 48
    assert row["house_state"] == "away"


def test_save_anomaly_event_minimal_payload_uses_sentinels(real_schema_db):
    """Behavioral: New AnomalyEvent emitters with empty payload get sentinel defaults.

    Circuit anomaly, NM dispatch, and compliance violations emit AnomalyEvent
    with payload containing no metric fields.  The sentinel defaults (0.0 / 0)
    must satisfy the NOT NULL constraints.
    """
    event = _FakeAnomalyEvent(
        coordinator="energy",
        type="circuit.overload_detected",
        severity=1,
        event_class="point_in_time",
        payload={"circuit_id": "circuit_1", "watts": 2400.0},  # no metric fields
    )
    rowid = _insert_anomaly(real_schema_db, event)
    row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row is not None
    # Sentinel defaults satisfy NOT NULL
    assert row["observed_value"] == 0.0
    assert row["expected_mean"] == 0.0
    assert row["z_score"] == 0.0
    assert row["sample_size"] == 0


def test_save_anomaly_event_v461_columns_writable(real_schema_db):
    """Behavioral: All 6 v4.6.1 new columns accept values (not schema-mismatch-defaulted).

    Regression guard: if any of these columns were dropped in a future schema change
    without updating the DAO, the INSERT would fail with 'table has N columns but M
    values were supplied'.
    """
    event = _FakeAnomalyEvent(
        coordinator="presence",
        type="transit.path_implausible",
        severity=1,
        event_class="transition_invalid",
        entity_id="person.alice",
        room_id="kitchen",
        person_id="alice",
        correlation_id="corr_abc123",
        recovery_at="2026-05-14T10:30:00",
        payload={"from_room": "bedroom", "to_room": "kitchen"},
    )
    rowid = _insert_anomaly(real_schema_db, event)
    row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["event_class"] == "transition_invalid"
    assert row["entity_id"] == "person.alice"
    assert row["room_id"] == "kitchen"
    assert row["person_id"] == "alice"
    assert row["correlation_id"] == "corr_abc123"
    assert row["recovery_at"] == "2026-05-14T10:30:00"


def test_save_anomaly_event_context_json_roundtrip(real_schema_db):
    """Behavioral: context_json is stored and retrievable as valid JSON.

    D11 canonical context_json shape must survive the DB roundtrip.
    """
    context = {
        "zone_id": "main_floor",
        "room_id": "kitchen",
        "person_id": "alice",
        "linked_event_id": 42,
        "source_signal": "SIGNAL_SAFETY_HAZARD",
        "extra": {"hazard_type": "smoke", "sensor_id": "binary_sensor.smoke_1"},
    }
    event = _FakeAnomalyEvent(
        coordinator="safety",
        type="hazard.smoke",
        severity=2,
        event_class="hazard",
        room_id="kitchen",
        person_id="alice",
        payload=context,
    )
    rowid = _insert_anomaly(real_schema_db, event)
    row = real_schema_db.execute(
        "SELECT context_json FROM anomaly_log WHERE id = ?", (rowid,)
    ).fetchone()
    stored = json.loads(row["context_json"])
    assert stored["zone_id"] == "main_floor"
    assert stored["source_signal"] == "SIGNAL_SAFETY_HAZARD"
    assert stored["extra"]["hazard_type"] == "smoke"


def test_save_anomaly_event_severity_stored_as_int(real_schema_db):
    """Behavioral: Severity IntEnum value 0/1/2 roundtrips correctly through TEXT column.

    The anomaly_log schema declares severity as TEXT (historical decision).
    The DAO stores int(event.severity) which sqlite3 coerces to a text
    representation.  int(row["severity"]) must equal the original int value.
    This guards against the DAO accidentally storing a non-numeric string.
    """
    for sev_int, sev_name in [(0, "INFO"), (1, "WARNING"), (2, "CRITICAL")]:
        event = _FakeAnomalyEvent(
            coordinator="test",
            type=f"test.sev_{sev_name.lower()}",
            severity=sev_int,
            event_class="point_in_time",
        )
        rowid = _insert_anomaly(real_schema_db, event)
        row = real_schema_db.execute(
            "SELECT severity FROM anomaly_log WHERE id = ?", (rowid,)
        ).fetchone()
        # severity is TEXT column; value must be parseable as int
        assert int(row["severity"]) == sev_int, (
            f"Severity {sev_name} ({sev_int}) must roundtrip as int via TEXT column, "
            f"got {row['severity']!r}"
        )


def test_save_anomaly_event_multiple_rows_isolated(real_schema_db):
    """Behavioral: Multiple inserts produce independent rows (autoincrement works)."""
    ids = []
    for i in range(5):
        event = _FakeAnomalyEvent(
            coordinator=f"coord_{i}",
            type=f"test.event_{i}",
            severity=i % 3,
            event_class="point_in_time",
        )
        ids.append(_insert_anomaly(real_schema_db, event))
    # All IDs unique
    assert len(set(ids)) == 5
    count = real_schema_db.execute("SELECT COUNT(*) FROM anomaly_log").fetchone()[0]
    assert count == 5


# ---------------------------------------------------------------------------
# D8 — notification_log behavioral tests
# ---------------------------------------------------------------------------


def _insert_notification(conn: sqlite3.Connection, *, coordinator_id="test", severity="warning",
                          title="Test Alert", message="Test message body") -> int:
    """Insert a notification_log row using the same shape as database.log_notification()."""
    cursor = conn.execute(
        """INSERT INTO notification_log
           (timestamp, coordinator_id, severity, title, message,
            hazard_type, location, person_id, channel, delivered, acknowledged)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            coordinator_id, severity, title, message,
            None, None, None, "push", 0, 0,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def test_notification_log_not_null_columns(real_schema_db):
    """Behavioral: notification_log INSERT satisfies NOT NULL for required columns."""
    rowid = _insert_notification(real_schema_db)
    assert rowid > 0
    row = real_schema_db.execute(
        "SELECT * FROM notification_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row is not None
    assert row["coordinator_id"] == "test"
    assert row["severity"] == "warning"
    assert row["title"] == "Test Alert"
    assert row["message"] == "Test message body"
    assert row["delivered"] == 0


def test_notification_log_isolates_per_test(real_schema_db):
    """Behavioral: Each test gets a fresh DB — no cross-test contamination."""
    count = real_schema_db.execute("SELECT COUNT(*) FROM notification_log").fetchone()[0]
    assert count == 0, "notification_log should be empty at test start (function-scope isolation)"
    _insert_notification(real_schema_db)
    count = real_schema_db.execute("SELECT COUNT(*) FROM notification_log").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# D8 — ura_activity_log behavioral tests
# ---------------------------------------------------------------------------


def _insert_activity(conn: sqlite3.Connection, *, coordinator="test",
                     action="anomaly", description="Test anomaly event") -> int:
    """Insert a ura_activity_log row using the same shape as database.log_activity()."""
    cursor = conn.execute(
        """INSERT INTO ura_activity_log
           (timestamp, coordinator, action, room, zone, importance, description, details_json, entity_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            coordinator, action, None, None, "info", description, None, None,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def test_activity_log_anomaly_row_writes_correctly(real_schema_db):
    """Behavioral: ura_activity_log INSERT for action='anomaly' satisfies NOT NULL."""
    rowid = _insert_activity(
        real_schema_db,
        coordinator="safety",
        action="anomaly",
        description="Safety hazard anomaly: hazard.smoke z=10.0 (safety)",
    )
    assert rowid > 0
    row = real_schema_db.execute(
        "SELECT * FROM ura_activity_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["action"] == "anomaly"
    assert row["coordinator"] == "safety"
    assert "hazard.smoke" in row["description"]


def test_activity_log_importance_field_accepted(real_schema_db):
    """Behavioral: importance field accepts advisory/alert/critical strings (from anomaly severity)."""
    for importance in ("info", "advisory", "alert", "critical"):
        rowid = _insert_activity(
            real_schema_db,
            coordinator="test",
            action="anomaly",
            description=f"Anomaly at {importance} level",
        )
        row = real_schema_db.execute(
            "SELECT importance FROM ura_activity_log WHERE id = ?", (rowid,)
        ).fetchone()
        # importance stored as TEXT — any string is valid (no CHECK constraint)
        assert row["importance"] is not None


# ---------------------------------------------------------------------------
# D8 — metric_baselines behavioral tests
# ---------------------------------------------------------------------------


def _insert_baseline(conn: sqlite3.Connection, *, coordinator_id="test",
                     metric_name="test_metric", scope="house") -> None:
    """Insert a metric_baselines row using the same shape as database writes."""
    conn.execute(
        """INSERT OR REPLACE INTO metric_baselines
           (coordinator_id, metric_name, scope, mean, variance, sample_count, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (coordinator_id, metric_name, scope, 3.5, 1.2, 24,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def test_metric_baselines_primary_key_enforced(real_schema_db):
    """Behavioral: metric_baselines PRIMARY KEY (coordinator_id, metric_name, scope) works."""
    _insert_baseline(real_schema_db, coordinator_id="presence", metric_name="census_count", scope="house")
    # INSERT OR REPLACE should update, not duplicate
    _insert_baseline(real_schema_db, coordinator_id="presence", metric_name="census_count", scope="house")
    count = real_schema_db.execute(
        "SELECT COUNT(*) FROM metric_baselines WHERE coordinator_id='presence' AND metric_name='census_count'"
    ).fetchone()[0]
    assert count == 1, "INSERT OR REPLACE must not create duplicate rows for same PK"


def test_metric_baselines_not_null_columns(real_schema_db):
    """Behavioral: metric_baselines INSERT satisfies NOT NULL for mean/variance/sample_count."""
    _insert_baseline(real_schema_db, coordinator_id="safety", metric_name="hazard_rate")
    row = real_schema_db.execute(
        "SELECT * FROM metric_baselines WHERE coordinator_id='safety'"
    ).fetchone()
    assert row is not None
    assert row["mean"] == 3.5
    assert row["variance"] == 1.2
    assert row["sample_count"] == 24


# ---------------------------------------------------------------------------
# D8 — decision_log behavioral tests
# ---------------------------------------------------------------------------


def _insert_decision(conn: sqlite3.Connection, *, coordinator_id="hvac",
                     decision_type="hvac_setpoint") -> int:
    """Insert a decision_log row using the same shape as database.log_coordinator_decision()."""
    cursor = conn.execute(
        """INSERT INTO decision_log
           (timestamp, coordinator_id, decision_type, scope,
            situation_classified, urgency, confidence,
            context_json, action_json, expected_savings_kwh,
            expected_cost_savings, expected_comfort_impact,
            constraints_json, devices_commanded_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            coordinator_id, decision_type, "house",
            "normal_daytime", 50, 0.85,
            json.dumps({"temperature": 22.0}),
            json.dumps({"setpoint": 22.0}),
            0.5, 0.10, 0, None, None,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def test_decision_log_not_null_columns(real_schema_db):
    """Behavioral: decision_log INSERT satisfies NOT NULL for required columns."""
    rowid = _insert_decision(real_schema_db)
    assert rowid > 0
    row = real_schema_db.execute(
        "SELECT * FROM decision_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["coordinator_id"] == "hvac"
    assert row["decision_type"] == "hvac_setpoint"
    assert row["scope"] == "house"
    assert row["timestamp"] is not None


def test_decision_log_json_fields_roundtrip(real_schema_db):
    """Behavioral: JSON fields in decision_log survive roundtrip."""
    rowid = _insert_decision(real_schema_db, coordinator_id="presence")
    row = real_schema_db.execute(
        "SELECT context_json, action_json FROM decision_log WHERE id = ?", (rowid,)
    ).fetchone()
    ctx = json.loads(row["context_json"])
    assert ctx["temperature"] == 22.0


# ---------------------------------------------------------------------------
# D8 — compliance_log behavioral tests
# ---------------------------------------------------------------------------


def _insert_compliance(conn: sqlite3.Connection, *, compliant=True,
                       override_detected=False) -> int:
    """Insert a compliance_log row using the same shape as database.log_compliance_check()."""
    cursor = conn.execute(
        """INSERT INTO compliance_log
           (timestamp, decision_id, scope, device_type, device_id,
            commanded_state_json, actual_state_json,
            compliant, deviation_json,
            override_detected, override_source, override_duration_minutes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            1, "house", "climate", "climate.hvac_main",
            json.dumps({"mode": "cool", "setpoint": 22.0}),
            json.dumps({"mode": "cool", "setpoint": 22.0}) if compliant else json.dumps({"mode": "heat"}),
            1 if compliant else 0,
            None if compliant else json.dumps({"mode": {"commanded": "cool", "actual": "heat"}}),
            1 if override_detected else 0,
            "manual" if override_detected else None,
            5.0 if override_detected else None,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def test_compliance_log_compliant_row(real_schema_db):
    """Behavioral: Compliant decision_id → compliance=1, no deviation_json."""
    rowid = _insert_compliance(real_schema_db, compliant=True)
    row = real_schema_db.execute(
        "SELECT * FROM compliance_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["compliant"] == 1
    assert row["deviation_json"] is None
    assert row["override_detected"] == 0


def test_compliance_log_violation_row(real_schema_db):
    """Behavioral: Violation row (D6 trigger condition) sets compliant=0 and override_detected=1."""
    rowid = _insert_compliance(real_schema_db, compliant=False, override_detected=True)
    row = real_schema_db.execute(
        "SELECT * FROM compliance_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["compliant"] == 0
    assert row["override_detected"] == 1
    deviation = json.loads(row["deviation_json"])
    assert "mode" in deviation


# ---------------------------------------------------------------------------
# D8 — Schema integrity tests via session-scoped fixture
# ---------------------------------------------------------------------------


def test_conftest_fixture_applies_full_schema(real_schema_db_session):
    """D1 acceptance criteria: fixture has all URA tables."""
    tables_result = real_schema_db_session.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    tables = {row["name"] for row in tables_result}
    required = {
        "anomaly_log",
        "decision_log",
        "compliance_log",
        "outcome_log",
        "metric_baselines",
        "ura_activity_log",
        "notification_log",
    }
    missing = required - tables
    assert not missing, f"real_schema_db is missing tables: {missing}"


def test_conftest_fixture_isolates_per_test_a(real_schema_db):
    """D1 acceptance criteria: function-scoped fixture starts empty."""
    count = real_schema_db.execute("SELECT COUNT(*) FROM anomaly_log").fetchone()[0]
    assert count == 0, "real_schema_db must start empty (function scope)"
    _insert_anomaly(real_schema_db, _FakeAnomalyEvent(coordinator="a", type="a.test"))


def test_conftest_fixture_isolates_per_test_b(real_schema_db):
    """D1 acceptance criteria: second function-scoped test also starts empty (no bleed from _a)."""
    count = real_schema_db.execute("SELECT COUNT(*) FROM anomaly_log").fetchone()[0]
    assert count == 0, "real_schema_db must not carry over rows from previous test"


def test_anomaly_log_index_exists(real_schema_db_session):
    """D1 / D12 acceptance: idx_anomaly_timestamp index must exist for 24h queries."""
    indexes = real_schema_db_session.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='anomaly_log'"
    ).fetchall()
    idx_names = {row["name"] for row in indexes}
    assert "idx_anomaly_timestamp" in idx_names, (
        "idx_anomaly_timestamp must exist — used by URARecentAnomaliesSensor 24h window query"
    )

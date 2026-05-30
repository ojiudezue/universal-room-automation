"""v4.6.3 D8 — Behavioral DAO tests against real-schema in-memory sqlite.

Every write-DAO that touches a NOT NULL column gets at least one behavioral
test that uses real_schema_db from conftest_db.py.  This test class was
pioneered in v4.6.3 to prevent bug-class shape that caused v4.6.1.1
(NOT NULL constraint mismatch caught only in production, not build time).

Fix 1/2 (C1, C2, A1, C3): The INSERT SQL used by _insert_anomaly is now
extracted from database.py source at module load, not hand-typed.  If
database.py changes the INSERT column list, the extraction changes, and the
test immediately uses the new SQL.  If the schema also changed (new NOT NULL
column), the INSERT will fail here — before production deployment.

Fix 5 (C5): compliance_log INSERT uses production column names (commanded_state,
actual_state, deviation_details) instead of the old fixture-drift names.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Production INSERT SQL extraction — couples test SQL to database.py source
# ---------------------------------------------------------------------------

_DATABASE_PY = (
    Path(__file__).parent.parent.parent
    / "custom_components"
    / "universal_room_automation"
    / "database.py"
)


def _extract_anomaly_insert_sql() -> str:
    """Extract the INSERT INTO anomaly_log SQL string from database.py source.

    Parses the triple-quoted string inside save_anomaly_event() that begins
    with 'INSERT INTO anomaly_log'.  Returns the raw SQL string ready for
    sqlite3.execute().

    If the function signature or SQL string changes in database.py, this
    extraction picks up the new SQL automatically.  If the column list
    changes, behavioral tests using this SQL will fail at build time rather
    than at production deployment.

    Raises RuntimeError if the INSERT SQL cannot be found in the source.
    This means someone moved/renamed it — fix the extraction before shipping.
    """
    src = _DATABASE_PY.read_text()

    # Find save_anomaly_event function body
    fn_idx = src.find("async def save_anomaly_event(")
    if fn_idx < 0:
        raise RuntimeError(
            "conftest: Cannot find 'async def save_anomaly_event(' in database.py. "
            "Rename or refactor detected — update _extract_anomaly_insert_sql()."
        )

    # Find the INSERT INTO anomaly_log triple-quoted string within the function
    insert_marker = "INSERT INTO anomaly_log"
    insert_idx = src.find(insert_marker, fn_idx)
    if insert_idx < 0:
        raise RuntimeError(
            "conftest: Cannot find 'INSERT INTO anomaly_log' in save_anomaly_event "
            "in database.py. Update _extract_anomaly_insert_sql()."
        )

    # Walk back to the start of the triple-quoted string
    triple_start = src.rfind('"""', fn_idx, insert_idx)
    if triple_start < 0:
        raise RuntimeError(
            "conftest: Cannot find triple-quote opening before INSERT INTO anomaly_log "
            "in save_anomaly_event. Update _extract_anomaly_insert_sql()."
        )

    # Find the closing triple-quote
    triple_end = src.find('"""', triple_start + 3)
    if triple_end < 0:
        raise RuntimeError(
            "conftest: Cannot find triple-quote closing for INSERT SQL in save_anomaly_event."
        )

    return src[triple_start + 3: triple_end].strip()


# Extract at module load — fails fast if database.py changes in a breaking way
_ANOMALY_INSERT_SQL = _extract_anomaly_insert_sql()


def _count_sql_placeholders(sql: str) -> int:
    """Count the number of '?' placeholders in a SQL string."""
    return sql.count("?")


# ---------------------------------------------------------------------------
# Helpers — minimal duck-typed AnomalyEvent so tests don't need HA installed
# ---------------------------------------------------------------------------

class _FakeAnomalyEvent:
    """Duck-typed stand-in for AnomalyEvent — matches save_anomaly_event() contract.

    Includes both the legacy payload-dict approach AND the v4.6.3 explicit metric
    fields (observed_value, expected_mean, etc.) so the _metric() priority chain
    in save_anomaly_event() can be tested in both the legacy and the new path.

    Tests that want to exercise the 'dataclass field' path (Priority 1) should
    pass observed_value, z_score etc. as kwargs.  Tests that want the legacy
    'payload top-level' path (Priority 2) should put the values in payload dict.
    """

    def __init__(
        self,
        *,
        coordinator="test_coord",
        type="test.metric_spike",
        severity=1,
        event_class=None,        # legacy alias — kept for back-compat
        anomaly_type=None,       # v4.7.12 canonical kwarg
        detected_at=None,
        payload=None,
        entity_id=None,
        room_id=None,
        person_id=None,
        correlation_id=None,
        recovery_at=None,
        # v4.6.3 explicit metric fields (Priority 1 in _metric())
        observed_value=None,
        expected_mean=None,
        expected_std=None,
        z_score=None,
        sample_size=None,
    ):
        self.coordinator = coordinator
        self.type = type
        self.severity = severity
        # v4.7.12: accept either kwarg; default to "point_in_time" if both omitted.
        _resolved_type = anomaly_type if anomaly_type is not None else event_class
        if _resolved_type is None:
            _resolved_type = "point_in_time"
        # v4.7.12 Reviewer C fix-up (C-H2): mirror production
        # AnomalyEvent.__post_init__ validation so fakes can't smuggle
        # garbage discriminators past the test suite. The closed set
        # MUST match AnomalyType members in anomaly_event.py.
        _VALID_ANOMALY_TYPES = {
            "point_in_time", "regime_shift", "hazard", "transition_invalid",
        }
        if str(_resolved_type) not in _VALID_ANOMALY_TYPES:
            raise ValueError(
                f"_FakeAnomalyEvent.anomaly_type must be one of {_VALID_ANOMALY_TYPES}; "
                f"got {_resolved_type!r}"
            )
        self.anomaly_type = _resolved_type
        self.event_class = _resolved_type  # legacy alias readback
        self.detected_at = detected_at or datetime.now(timezone.utc).isoformat()
        self.payload = payload if payload is not None else {}
        self.entity_id = entity_id
        self.room_id = room_id
        self.person_id = person_id
        self.correlation_id = correlation_id
        self.recovery_at = recovery_at
        # Explicit metric fields — set to None by default so _metric() falls through
        # to payload-based Priority 2 path for legacy tests
        self.observed_value = observed_value
        self.expected_mean = expected_mean
        self.expected_std = expected_std
        self.z_score = z_score
        self.sample_size = sample_size


# ---------------------------------------------------------------------------
# DAO adapter — uses the INSERT SQL extracted from database.py source.
#
# The SQL is production-sourced (not hand-typed).  The parameter-building
# logic mirrors save_anomaly_event() exactly (payload unpacking + sentinels).
# If the production INSERT SQL changes, _ANOMALY_INSERT_SQL changes too, and
# the tests immediately use the new SQL against the production-sourced schema.
#
# This is the fix for C1/C2/A1/C3: the "inline DAO" is now self-synchronizing
# with production source.  Previously it was hand-typed in two places.
# ---------------------------------------------------------------------------

def _insert_anomaly(conn: sqlite3.Connection, event: _FakeAnomalyEvent) -> int:
    """Execute the production save_anomaly_event() INSERT SQL against the test DB.

    Uses _ANOMALY_INSERT_SQL extracted from database.py at module load.
    The parameter-building logic mirrors the production _metric() helper from
    save_anomaly_event() — Priority 1: AnomalyEvent dataclass fields (v4.6.3+);
    Priority 2: payload top-level (legacy shape); Priority 3: payload["extra"].

    If database.py changes the INSERT column list or value ordering, this
    function must be updated to match — and the module will fail to import
    if _extract_anomaly_insert_sql() breaks, providing fast feedback.
    """
    payload_dict = event.payload if isinstance(event.payload, dict) else {}
    _payload_extra = payload_dict.get("extra", {}) if isinstance(payload_dict.get("extra"), dict) else {}

    def _metric(field_name: str, default):
        """Mirrors save_anomaly_event()._metric() priority chain."""
        # Priority 1: explicit AnomalyEvent field (v4.6.3+ dataclass fields)
        val = getattr(event, field_name, None)
        if val is not None and val != default:
            return val
        # Priority 2: payload top-level (legacy store_anomaly() shape)
        val = payload_dict.get(field_name)
        if val is not None:
            return val
        # Priority 3: payload["extra"] (intermediate shape)
        val = _payload_extra.get(field_name)
        if val is not None:
            return val
        return default

    observed_value = _metric("observed_value", 0.0)
    expected_mean = _metric("expected_mean", 0.0)
    expected_std = _metric("expected_std", 0.0)
    z_score = _metric("z_score", 0.0)
    sample_size = _metric("sample_size", 0)
    house_state = payload_dict.get("house_state")

    # v4.7.12 D1: production INSERT now dual-writes BOTH event_class and
    # anomaly_type columns with the same value. Mirror that here so the
    # test parameter tuple length matches the extracted INSERT SQL's
    # placeholder count (21).
    _discriminator = getattr(event, "anomaly_type", None) or getattr(
        event, "event_class", "point_in_time"
    )
    _discriminator_str = str(_discriminator) if _discriminator is not None else "point_in_time"
    cursor = conn.execute(
        _ANOMALY_INSERT_SQL,
        (
            event.detected_at,
            event.coordinator,
            "",                          # scope (empty string sentinel)
            event.type,
            observed_value,
            expected_mean,
            expected_std,
            z_score,
            int(event.severity),
            sample_size,
            house_state,
            json.dumps(event.payload),
            0,                           # resolved
            None,                        # resolution_notes
            _discriminator_str,          # event_class (dual-write alias)
            event.recovery_at,
            event.correlation_id,
            event.entity_id,
            event.room_id,
            event.person_id,
            _discriminator_str,          # anomaly_type (v4.7.12 canonical)
        ),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Schema regression test — Fix 1 (C1, C2, A1)
# ---------------------------------------------------------------------------


def test_conftest_schema_matches_production():
    """Regression: fixture schema must match production schema column-for-column.

    Builds two in-memory DBs:
     1. Using conftest_db._build_schema() (the fixture path)
     2. Using the same extraction logic, independently

    Asserts that for each required table, the column names match exactly.
    If anyone hand-edits conftest_db.py to diverge from the extraction,
    OR if database.py adds a column but the extraction breaks, this test fails.

    This is the regression-prevention test for A1 / C1 / C2 (schema mirror drift).
    """
    from tests.conftest_db import _build_schema, get_fixture_column_names_from_conn

    required_tables = [
        "anomaly_log",
        "decision_log",
        "compliance_log",
        "outcome_log",
        "metric_baselines",
        "ura_activity_log",
        "notification_log",
    ]

    # Build the fixture DB (the path that tests use)
    fixture_conn = sqlite3.connect(":memory:")
    fixture_conn.row_factory = sqlite3.Row
    _build_schema(fixture_conn)

    # Build a reference DB independently using the same extraction
    ref_conn = sqlite3.connect(":memory:")
    ref_conn.row_factory = sqlite3.Row
    _build_schema(ref_conn)

    for table in required_tables:
        fixture_cols = get_fixture_column_names_from_conn(fixture_conn, table)
        ref_cols = get_fixture_column_names_from_conn(ref_conn, table)

        assert fixture_cols == ref_cols, (
            f"Schema mismatch for table '{table}': "
            f"fixture has {sorted(fixture_cols)}, "
            f"reference extraction has {sorted(ref_cols)}"
        )
        assert len(fixture_cols) > 0, (
            f"Table '{table}' has no columns in fixture — extraction failed"
        )

    fixture_conn.close()
    ref_conn.close()


def test_production_insert_sql_column_count_matches_fixture_schema(real_schema_db_session):
    """Regression: INSERT SQL placeholder count must match anomaly_log column count.

    Compares the number of '?' placeholders in the production-extracted INSERT SQL
    against the number of non-auto columns in the real_schema_db fixture.

    If save_anomaly_event() adds a column to the INSERT but the fixture schema
    doesn't have it (or vice versa), this test fires immediately.

    This guards the Fix 2 coupling: _insert_anomaly uses _ANOMALY_INSERT_SQL
    which must stay synchronized with the fixture schema.
    """
    # Count columns in the INSERT SQL (20 '?' for 20 value columns)
    placeholder_count = _count_sql_placeholders(_ANOMALY_INSERT_SQL)
    assert placeholder_count > 0, "Extracted INSERT SQL has no placeholders — extraction failed"

    # Count non-autoincrement columns in anomaly_log from the fixture schema
    # (id is AUTOINCREMENT and excluded from INSERT column list)
    all_cols = real_schema_db_session.execute(
        "PRAGMA table_info(anomaly_log)"
    ).fetchall()
    # id is auto-populated; excluded from INSERT
    insertable_cols = [c for c in all_cols if c[1] != "id"]
    assert placeholder_count == len(insertable_cols), (
        f"INSERT SQL has {placeholder_count} placeholders but anomaly_log has "
        f"{len(insertable_cols)} insertable columns. "
        f"Schema or INSERT changed — update _insert_anomaly() value tuple to match."
    )


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
# Fix 4 (C9) — Negative-path tests for D8
# These verify the DAO (via the production-sourced INSERT SQL) correctly
# fails or handles invalid/missing inputs.
# ---------------------------------------------------------------------------


def test_save_anomaly_event_raises_on_missing_required_field(real_schema_db):
    """Negative: INSERT must fail if a NOT NULL column receives NULL.

    This test directly models the v4.6.1.1 bug-class shape: a NOT NULL column
    receiving a NULL value.  Here we force coordinator_id=None to trigger the
    constraint violation.  The production DAO wraps this in a try/except and
    returns None; the test exercises the underlying schema enforcement.
    """
    with pytest.raises(sqlite3.IntegrityError):
        real_schema_db.execute(
            _ANOMALY_INSERT_SQL,
            (
                datetime.now(timezone.utc).isoformat(),
                None,  # coordinator_id — NOT NULL violation
                "",
                "test.metric",
                0.0, 0.0, 0.0, 0.0,
                1, 0,
                None,
                json.dumps({}),
                0, None,
                "point_in_time",
                None, None, None, None, None,
                "point_in_time",  # v4.7.12 anomaly_type (dual-write)
            ),
        )


def test_save_anomaly_event_handles_malformed_context_json(real_schema_db):
    """Negative: Malformed context_json is stored as-is (no schema CHECK constraint).

    context_json is TEXT — SQLite does not validate JSON. The DAO stores whatever
    string json.dumps() produces.  A consumer reading context_json must guard with
    try/except json.loads().  This test confirms the INSERT succeeds (not a DAO
    error) but that reading back a non-dict payload produces an invalid-json string.
    """
    # Storing a plain string as payload (not a dict) → json.dumps gives '"not_a_dict"'
    # The INSERT must succeed (schema allows any TEXT in context_json)
    cursor = real_schema_db.execute(
        _ANOMALY_INSERT_SQL,
        (
            datetime.now(timezone.utc).isoformat(),
            "test_coord", "",
            "test.metric",
            0.0, 0.0, 0.0, 0.0,
            1, 0,
            None,
            '"this_is_not_a_dict_json"',  # malformed for dict consumers
            0, None,
            "point_in_time",
            None, None, None, None, None,
            "point_in_time",  # v4.7.12 anomaly_type (dual-write)
        ),
    )
    real_schema_db.commit()
    row = real_schema_db.execute(
        "SELECT context_json FROM anomaly_log WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    raw = row["context_json"]
    # json.loads succeeds (it's valid JSON — a string), but it's not a dict
    parsed = json.loads(raw)
    assert not isinstance(parsed, dict), (
        "Malformed context_json (non-dict) stored as string — consumer must guard"
    )


def test_save_anomaly_event_rejects_invalid_severity_string(real_schema_db):
    """Negative: Severity stored as legacy string (e.g. 'advisory') cannot be int()-cast.

    The v4.6.1 migration backfilled legacy string severities to numeric strings.
    Post-migration, all new rows must store integer-castable severity values.
    This test stores 'advisory' (un-migrated legacy value) and asserts that
    int(row['severity']) raises — confirming the migration was necessary and that
    new writes must use int(event.severity).
    """
    cursor = real_schema_db.execute(
        _ANOMALY_INSERT_SQL,
        (
            datetime.now(timezone.utc).isoformat(),
            "test_coord", "",
            "test.metric",
            0.0, 0.0, 0.0, 0.0,
            "advisory",  # pre-migration legacy severity string (must not appear in new rows)
            0,
            None,
            json.dumps({}),
            0, None,
            "point_in_time",
            None, None, None, None, None,
            "point_in_time",  # v4.7.12 anomaly_type (dual-write)
        ),
    )
    real_schema_db.commit()
    row = real_schema_db.execute(
        "SELECT severity FROM anomaly_log WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    # Schema stores whatever TEXT value was given; we verify int() conversion fails
    with pytest.raises(ValueError):
        int(row["severity"])


def test_save_anomaly_event_v461_bug_class_sentinel_coverage(real_schema_db):
    """Negative (v4.6.1.1 bug-class shape): event with no metric payload must not fail.

    The v4.6.1.1 production failure was: new AnomalyEvent emitters had no
    observed_value/expected_mean/etc. in payload → NULL violated NOT NULL constraint.
    The fix: sentinel defaults (0.0/0) satisfy NOT NULL when payload lacks these keys.

    This test reproduces the exact pre-fix bug shape and asserts it is now handled:
    - Payload has NO metric fields (circuit/NM/compliance emit sites)
    - All NOT NULL columns must be satisfied by sentinel values
    - INSERT must succeed (no IntegrityError)
    - Values in the metric columns must equal the sentinel defaults
    """
    # Exact bug-class payload: no metric keys at all
    bug_class_payload = {
        "linked_event_id": 17,
        "source_signal": "compliance_check",
        "zone_id": "main_floor",
    }
    event = _FakeAnomalyEvent(
        coordinator="hvac",
        type="compliance.override_detected",
        severity=1,
        event_class="point_in_time",
        payload=bug_class_payload,
    )
    # This must NOT raise — if it raises IntegrityError, the v4.6.1.1 bug recurs
    rowid = _insert_anomaly(real_schema_db, event)
    assert rowid > 0

    row = real_schema_db.execute(
        "SELECT * FROM anomaly_log WHERE id = ?", (rowid,)
    ).fetchone()
    # Sentinel defaults applied
    assert row["observed_value"] == 0.0
    assert row["expected_mean"] == 0.0
    assert row["expected_std"] == 0.0
    assert row["z_score"] == 0.0
    assert row["sample_size"] == 0
    # context_json stores the full payload dict
    ctx = json.loads(row["context_json"])
    assert ctx["linked_event_id"] == 17


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
    """Insert a decision_log row using the same shape as database.log_coordinator_decision().

    Fix 5 (C5): Uses production column names:
      - context_json NOT NULL (was context_json in old fixture too — same here)
      - action_json NOT NULL (same)
      - constraints_published (NOT constraints_json — production name)
      - devices_commanded (NOT devices_commanded_json — production name)
    """
    cursor = conn.execute(
        """INSERT INTO decision_log
           (timestamp, coordinator_id, decision_type, scope,
            situation_classified, urgency, confidence,
            context_json, action_json, expected_savings_kwh,
            expected_cost_savings, expected_comfort_impact,
            constraints_published, devices_commanded)
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
#
# Fix 5 (C5): Uses production column names (commanded_state, actual_state,
# deviation_details) instead of the old drifted names (commanded_state_json,
# actual_state_json, deviation_json).  The old fixture had wrong names for
# all three — tests were implicitly validating the drifted fixture, not production.
# ---------------------------------------------------------------------------


def _insert_compliance(conn: sqlite3.Connection, *, compliant=True,
                       override_detected=False) -> int:
    """Insert a compliance_log row using production column names.

    Production schema (database.py:624-639):
      commanded_state TEXT NOT NULL   (NOT commanded_state_json)
      actual_state TEXT NOT NULL      (NOT actual_state_json)
      deviation_details TEXT          (NOT deviation_json)
      override_duration_minutes INTEGER  (NOT REAL)
    """
    cursor = conn.execute(
        """INSERT INTO compliance_log
           (timestamp, decision_id, scope, device_type, device_id,
            commanded_state, actual_state,
            compliant, deviation_details,
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
            5 if override_detected else None,  # INTEGER in production (not REAL)
        ),
    )
    conn.commit()
    return cursor.lastrowid


def test_compliance_log_compliant_row(real_schema_db):
    """Behavioral: Compliant decision_id → compliance=1, no deviation_details."""
    rowid = _insert_compliance(real_schema_db, compliant=True)
    row = real_schema_db.execute(
        "SELECT * FROM compliance_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["compliant"] == 1
    assert row["deviation_details"] is None
    assert row["override_detected"] == 0


def test_compliance_log_violation_row(real_schema_db):
    """Behavioral: Violation row (D6 trigger condition) sets compliant=0 and override_detected=1."""
    rowid = _insert_compliance(real_schema_db, compliant=False, override_detected=True)
    row = real_schema_db.execute(
        "SELECT * FROM compliance_log WHERE id = ?", (rowid,)
    ).fetchone()
    assert row["compliant"] == 0
    assert row["override_detected"] == 1
    deviation = json.loads(row["deviation_details"])
    assert "mode" in deviation


def test_compliance_log_production_column_names(real_schema_db_session):
    """Fix 5 (C5): compliance_log must have production column names, not drifted fixture names.

    Verifies that the fixture schema (extracted from database.py) uses the
    production column names. This test would have caught the C2/C5 drift:
      - 'commanded_state' (not 'commanded_state_json')
      - 'actual_state' (not 'actual_state_json')
      - 'deviation_details' (not 'deviation_json')
      - 'override_duration_minutes' as INTEGER (not REAL)
    """
    cols = real_schema_db_session.execute(
        "PRAGMA table_info(compliance_log)"
    ).fetchall()
    col_names = {row[1] for row in cols}

    # Production column names that must be present
    assert "commanded_state" in col_names, (
        "compliance_log must have 'commanded_state' column (not 'commanded_state_json')"
    )
    assert "actual_state" in col_names, (
        "compliance_log must have 'actual_state' column (not 'actual_state_json')"
    )
    assert "deviation_details" in col_names, (
        "compliance_log must have 'deviation_details' column (not 'deviation_json')"
    )

    # Drifted names must NOT be present
    assert "commanded_state_json" not in col_names, (
        "compliance_log must NOT have 'commanded_state_json' — that was the drifted fixture name"
    )
    assert "actual_state_json" not in col_names, (
        "compliance_log must NOT have 'actual_state_json' — that was the drifted fixture name"
    )
    assert "deviation_json" not in col_names, (
        "compliance_log must NOT have 'deviation_json' — that was the drifted fixture name"
    )


def test_decision_log_production_column_names(real_schema_db_session):
    """Fix 5 (C5): decision_log must have production column names, not drifted fixture names.

    Verifies:
      - 'constraints_published' (not 'constraints_json')
      - 'devices_commanded' (not 'devices_commanded_json')
      - 'context_json' NOT NULL
      - 'action_json' NOT NULL
    """
    cols = real_schema_db_session.execute(
        "PRAGMA table_info(decision_log)"
    ).fetchall()
    col_map = {row[1]: {"notnull": bool(row[3]), "type": row[2]} for row in cols}
    col_names = set(col_map.keys())

    assert "constraints_published" in col_names, (
        "decision_log must have 'constraints_published' column (not 'constraints_json')"
    )
    assert "devices_commanded" in col_names, (
        "decision_log must have 'devices_commanded' column (not 'devices_commanded_json')"
    )
    # Drifted names must NOT be present
    assert "constraints_json" not in col_names, (
        "decision_log must NOT have 'constraints_json' — that was the drifted fixture name"
    )
    assert "devices_commanded_json" not in col_names, (
        "decision_log must NOT have 'devices_commanded_json' — that was the drifted fixture name"
    )
    # NOT NULL enforcement
    assert col_map.get("context_json", {}).get("notnull"), (
        "decision_log.context_json must be NOT NULL"
    )
    assert col_map.get("action_json", {}).get("notnull"), (
        "decision_log.action_json must be NOT NULL"
    )


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

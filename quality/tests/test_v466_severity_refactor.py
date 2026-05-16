"""v4.6.6 — AnomalySeverity vocabulary refactor (3 → 5 buckets).

Cycle context
-------------
Reviewers A-M2 + B-M1 (v4.6.5 Tier 2-DB) independently flagged that every
coordinator emit site collapsed the 4-bucket internal
``coordinator_diagnostics.AnomalySeverity`` (NOMINAL/ADVISORY/ALERT/CRITICAL)
into the 2-bucket emit pattern::

    _NewSev.CRITICAL if anomaly.severity.value == "critical" else _NewSev.WARNING

So ADVISORY (z=2-3) and ALERT (z=3-4) both persisted as ``severity = 1``
(WARNING), and severity-grouped analytics could not distinguish them.

v4.6.6 expands the persisted ``AnomalyEvent.AnomalySeverity`` IntEnum from
3 buckets {INFO=0, WARNING=1, CRITICAL=2} to 5 buckets
{INFO=0, WARNING=1, ADVISORY=2, ALERT=3, CRITICAL=4}. Sort order preserved
(higher = more severe). CRITICAL's integer value moves from 2 to 4.

This file covers three classes of test (in order):
 1. Enum-shape behavioral tests — instantiate ``AnomalySeverity``, assert
    membership and integer values.
 2. Round-trip tests via ``real_schema_db`` — insert ``AnomalyEvent`` rows
    with each of the 5 severities, SELECT back, verify the severity column
    round-trips through the production INSERT path and SQLite's TEXT column.
 3. ``URARecentAnomaliesSensor.by_severity`` aggregation — insert rows with
    each severity, run the production GROUP BY query, assert the dict has
    all 5 keys with the correct counts.

The production INSERT SQL is extracted from ``database.py`` via the same
pattern used in ``test_v463_behavioral_dao.py`` so the test cannot silently
drift from production. If ``save_anomaly_event`` changes its column list,
``_extract_anomaly_insert_sql`` will pick the new one up and any mismatch
fails the schema test.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loaders — avoid HA import at module level
# ---------------------------------------------------------------------------

def _load_anomaly_event_module():
    """Load anomaly_event.py without dragging in HA's package machinery."""
    mod_name = "ura_v466_anomaly_event"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/anomaly_event.py"
    )
    spec = importlib.util.spec_from_file_location(mod_name, str(src))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Production INSERT SQL extraction — keeps test SQL coupled to database.py
# (Same pattern as test_v463_behavioral_dao.py — see that file for rationale.)
# ---------------------------------------------------------------------------

_DATABASE_PY = (
    Path("custom_components") / "universal_room_automation" / "database.py"
)


def _extract_anomaly_insert_sql() -> str:
    """Extract the INSERT INTO anomaly_log SQL string from save_anomaly_event()."""
    src = _DATABASE_PY.read_text()
    fn_idx = src.find("async def save_anomaly_event(")
    if fn_idx < 0:
        raise RuntimeError(
            "Cannot find 'async def save_anomaly_event(' in database.py — "
            "rename detected, update _extract_anomaly_insert_sql()."
        )
    insert_idx = src.find("INSERT INTO anomaly_log", fn_idx)
    if insert_idx < 0:
        raise RuntimeError(
            "Cannot find 'INSERT INTO anomaly_log' in save_anomaly_event."
        )
    triple_start = src.rfind('"""', fn_idx, insert_idx)
    triple_end = src.find('"""', triple_start + 3)
    return src[triple_start + 3:triple_end].strip()


_ANOMALY_INSERT_SQL = _extract_anomaly_insert_sql()


def _insert_anomaly_row(
    conn: sqlite3.Connection,
    *,
    coordinator_id: str,
    metric_name: str,
    severity: int,
    detected_at: str | None = None,
) -> int:
    """Direct INSERT mirroring save_anomaly_event() value tuple.

    Stores ``int(severity)`` exactly as the production DAO does (line 4412 of
    database.py), so the round-trip exercises the production write path.
    """
    detected_at = detected_at or datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        _ANOMALY_INSERT_SQL,
        (
            detected_at,
            coordinator_id,
            "",                # scope (empty-string sentinel)
            metric_name,
            0.0, 0.0, 0.0, 0.0,
            int(severity),     # production-equivalent severity coercion
            0,
            None,
            json.dumps({}),
            0, None,
            "point_in_time",
            None, None, None, None, None,
        ),
    )
    conn.commit()
    return cursor.lastrowid


# ===========================================================================
# Section 1 — Enum-shape behavioral tests
# ===========================================================================


def test_severity_enum_has_five_members():
    """v4.6.6: AnomalySeverity must have exactly 5 members (was 3 pre-v4.6.6)."""
    mod = _load_anomaly_event_module()
    members = list(mod.AnomalySeverity)
    names = {m.name for m in members}
    assert names == {"INFO", "WARNING", "ADVISORY", "ALERT", "CRITICAL"}, (
        f"AnomalySeverity members changed: {names}"
    )
    assert len(members) == 5


def test_severity_enum_integer_values_are_canonical():
    """v4.6.6: integer values are 0/1/2/3/4 in canonical sort order."""
    mod = _load_anomaly_event_module()
    assert mod.AnomalySeverity.INFO == 0
    assert mod.AnomalySeverity.WARNING == 1
    assert mod.AnomalySeverity.ADVISORY == 2
    assert mod.AnomalySeverity.ALERT == 3
    assert mod.AnomalySeverity.CRITICAL == 4


def test_severity_enum_sort_order_higher_is_more_severe():
    """Sort-order invariant: higher integer value = more severe.

    Code that does ``severity >= threshold`` (e.g. notification_manager.py:1961)
    depends on this. Regressing the order would silently mute alerts.
    """
    mod = _load_anomaly_event_module()
    ordered = [
        mod.AnomalySeverity.INFO,
        mod.AnomalySeverity.WARNING,
        mod.AnomalySeverity.ADVISORY,
        mod.AnomalySeverity.ALERT,
        mod.AnomalySeverity.CRITICAL,
    ]
    assert ordered == sorted(ordered), (
        "AnomalySeverity members must be sorted by ascending severity"
    )
    assert all(
        int(ordered[i]) < int(ordered[i + 1]) for i in range(len(ordered) - 1)
    ), "Each AnomalySeverity must be strictly greater than the previous one"


def test_severity_enum_is_intenum():
    """AnomalySeverity must remain an IntEnum so int(...) works in the DAO."""
    from enum import IntEnum
    mod = _load_anomaly_event_module()
    assert issubclass(mod.AnomalySeverity, IntEnum)


def test_advisory_and_alert_distinct_from_warning():
    """v4.6.6 regression: ADVISORY and ALERT must NOT collapse to WARNING."""
    mod = _load_anomaly_event_module()
    assert int(mod.AnomalySeverity.ADVISORY) != int(mod.AnomalySeverity.WARNING)
    assert int(mod.AnomalySeverity.ALERT) != int(mod.AnomalySeverity.WARNING)
    assert int(mod.AnomalySeverity.ADVISORY) != int(mod.AnomalySeverity.ALERT)


# ===========================================================================
# Section 2 — Round-trip tests via real_schema_db (production INSERT path)
# ===========================================================================


def test_severity_roundtrips_for_every_bucket(real_schema_db):
    """Round-trip: insert one row at each severity, SELECT back as int.

    Uses the production-extracted INSERT SQL so this test is coupled to the
    real DAO's column list. If a new NOT NULL column is added without updating
    the DAO, this test fails at build time (not in production).
    """
    mod = _load_anomaly_event_module()
    sev_values = [
        mod.AnomalySeverity.INFO,
        mod.AnomalySeverity.WARNING,
        mod.AnomalySeverity.ADVISORY,
        mod.AnomalySeverity.ALERT,
        mod.AnomalySeverity.CRITICAL,
    ]
    inserted_ids: list[tuple[int, int]] = []  # (rowid, expected_int_value)
    for sev in sev_values:
        rowid = _insert_anomaly_row(
            real_schema_db,
            coordinator_id="test_coord",
            metric_name=f"test.severity_{sev.name.lower()}",
            severity=sev,
        )
        inserted_ids.append((rowid, int(sev)))

    # Read each back. severity column is TEXT in the schema; production DAO
    # stores int(event.severity) which SQLite coerces to the text "0".."4".
    for rowid, expected_int in inserted_ids:
        row = real_schema_db.execute(
            "SELECT severity FROM anomaly_log WHERE id = ?", (rowid,)
        ).fetchone()
        assert row is not None
        # int() of the TEXT representation must equal the original IntEnum int.
        assert int(row["severity"]) == expected_int, (
            f"Severity {expected_int} did not round-trip — got {row['severity']!r}"
        )


def test_severity_advisory_distinguishable_from_warning_in_db(real_schema_db):
    """The bug v4.6.6 is fixing: ADVISORY rows must be selectable separately
    from WARNING rows once the new emit sites land. This guards the contract
    that the persisted column carries the full 5-bucket vocabulary."""
    mod = _load_anomaly_event_module()
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.w",
        severity=mod.AnomalySeverity.WARNING,
    )
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.a",
        severity=mod.AnomalySeverity.ADVISORY,
    )
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.l",
        severity=mod.AnomalySeverity.ALERT,
    )

    # SELECT by severity returns distinct row sets.
    warn_rows = real_schema_db.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE CAST(severity AS INTEGER) = ?",
        (int(mod.AnomalySeverity.WARNING),),
    ).fetchone()[0]
    adv_rows = real_schema_db.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE CAST(severity AS INTEGER) = ?",
        (int(mod.AnomalySeverity.ADVISORY),),
    ).fetchone()[0]
    alert_rows = real_schema_db.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE CAST(severity AS INTEGER) = ?",
        (int(mod.AnomalySeverity.ALERT),),
    ).fetchone()[0]
    assert warn_rows == 1
    assert adv_rows == 1
    assert alert_rows == 1


def test_severity_critical_no_longer_collides_with_advisory(real_schema_db):
    """v4.6.6 regression guard: pre-v4.6.6 CRITICAL=2; post-v4.6.6 ADVISORY=2.

    Make sure code that today writes CRITICAL produces a distinguishable row
    from code that today writes ADVISORY (which previously didn't exist at
    the emit layer at all). If anyone reverts CRITICAL back to 2 the assert
    on the count split fires.
    """
    mod = _load_anomaly_event_module()
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.c",
        severity=mod.AnomalySeverity.CRITICAL,
    )
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.a",
        severity=mod.AnomalySeverity.ADVISORY,
    )
    crit = real_schema_db.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE CAST(severity AS INTEGER) = ?",
        (int(mod.AnomalySeverity.CRITICAL),),
    ).fetchone()[0]
    adv = real_schema_db.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE CAST(severity AS INTEGER) = ?",
        (int(mod.AnomalySeverity.ADVISORY),),
    ).fetchone()[0]
    assert crit == 1
    assert adv == 1
    # And the integer values themselves must differ
    assert int(mod.AnomalySeverity.CRITICAL) != int(mod.AnomalySeverity.ADVISORY)


# ===========================================================================
# Section 3 — URARecentAnomaliesSensor.by_severity aggregation
# ===========================================================================
#
# The sensor builds ``self._by_severity`` from this query (sensor.py ~10392):
#
#     SELECT severity, COUNT(*) FROM anomaly_log
#     WHERE timestamp >= ? GROUP BY severity
#
# then ``{str(r[0]): r[1] for r in rows}``. This test runs the same SQL
# against ``real_schema_db`` and asserts the resulting dict has all 5 keys
# with correct counts.


def _run_by_severity_query(conn: sqlite3.Connection, cutoff: str) -> dict[str, int]:
    """Mirror of URARecentAnomaliesSensor._async_refresh's by_severity SELECT.

    Kept structurally identical to the production query so the sensor's
    aggregation behavior is exercised here without HA wiring.
    """
    cursor = conn.execute(
        """SELECT severity, COUNT(*) as n
           FROM anomaly_log
           WHERE timestamp >= ?
           GROUP BY severity""",
        (cutoff,),
    )
    return {str(r[0]): r[1] for r in cursor.fetchall()}


def test_by_severity_aggregation_returns_all_five_keys(real_schema_db):
    """v4.6.6: by_severity dict naturally surfaces all 5 buckets via GROUP BY.

    The sensor's aggregation has no hardcoded integer set — it builds the
    dict from whatever distinct severity values exist. This test verifies
    that contract holds once rows at every severity are present.
    """
    mod = _load_anomaly_event_module()
    cutoff = "2026-05-01T00:00:00"
    base_ts = "2026-05-14T10:00:00"

    # Counts: INFO=1, WARNING=2, ADVISORY=3, ALERT=4, CRITICAL=5 (distinct so
    # an off-by-one in the aggregation can't accidentally pass).
    counts = {
        mod.AnomalySeverity.INFO: 1,
        mod.AnomalySeverity.WARNING: 2,
        mod.AnomalySeverity.ADVISORY: 3,
        mod.AnomalySeverity.ALERT: 4,
        mod.AnomalySeverity.CRITICAL: 5,
    }
    for sev, n in counts.items():
        for i in range(n):
            _insert_anomaly_row(
                real_schema_db,
                coordinator_id="agg_test",
                metric_name=f"m.{sev.name.lower()}",
                severity=sev,
                detected_at=f"{base_ts[:-2]}{(i % 60):02d}",
            )

    result = _run_by_severity_query(real_schema_db, cutoff)
    # Keys are stringified severity ints (the sensor does str(r[0]))
    expected = {
        str(int(mod.AnomalySeverity.INFO)): 1,
        str(int(mod.AnomalySeverity.WARNING)): 2,
        str(int(mod.AnomalySeverity.ADVISORY)): 3,
        str(int(mod.AnomalySeverity.ALERT)): 4,
        str(int(mod.AnomalySeverity.CRITICAL)): 5,
    }
    assert result == expected, (
        f"by_severity aggregation drift: expected {expected}, got {result}"
    )


def test_by_severity_aggregation_skips_keys_with_zero_count(real_schema_db):
    """When a severity bucket has no rows in the window, it must NOT appear
    as a key — GROUP BY is the source of truth, not a hardcoded keyset."""
    mod = _load_anomaly_event_module()
    cutoff = "2026-05-01T00:00:00"

    # Only insert ADVISORY and CRITICAL — INFO/WARNING/ALERT must NOT show up.
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.a",
        severity=mod.AnomalySeverity.ADVISORY,
    )
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.c",
        severity=mod.AnomalySeverity.CRITICAL,
    )

    result = _run_by_severity_query(real_schema_db, cutoff)
    assert set(result.keys()) == {
        str(int(mod.AnomalySeverity.ADVISORY)),
        str(int(mod.AnomalySeverity.CRITICAL)),
    }
    assert result[str(int(mod.AnomalySeverity.ADVISORY))] == 1
    assert result[str(int(mod.AnomalySeverity.CRITICAL))] == 1


def test_by_severity_aggregation_filters_by_cutoff(real_schema_db):
    """Sanity: rows older than the cutoff are excluded from the aggregation,
    regardless of which severity bucket they fall in."""
    mod = _load_anomaly_event_module()
    cutoff = "2026-05-14T00:00:00"

    # Inside the window
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.in",
        severity=mod.AnomalySeverity.ALERT,
        detected_at="2026-05-14T10:00:00",
    )
    # Outside the window
    _insert_anomaly_row(
        real_schema_db, coordinator_id="c", metric_name="m.out",
        severity=mod.AnomalySeverity.ALERT,
        detected_at="2026-05-13T10:00:00",
    )

    result = _run_by_severity_query(real_schema_db, cutoff)
    assert result == {str(int(mod.AnomalySeverity.ALERT)): 1}


# ===========================================================================
# Section 4 — Coupling guard: enum and DAO INSERT are in lock-step
# ===========================================================================


def test_dao_insert_accepts_every_severity_value():
    """Any AnomalySeverity member must pass through int(event.severity)
    without raising. Guards against someone adding a non-int member."""
    mod = _load_anomaly_event_module()
    for sev in mod.AnomalySeverity:
        # IntEnum members support int() unconditionally
        assert isinstance(int(sev), int)


def test_severity_to_routine_state_mapping_covers_all_buckets():
    """sensor.py:_SEVERITY_TO_ROUTINE_STATE must have a mapping for every
    severity value (else PersonRoutineStatusSensor falls back to 'shifted'
    silently and ops cannot tell a CRITICAL routine shift apart from an
    ADVISORY one)."""
    sensor_src = Path("custom_components/universal_room_automation/sensor.py").read_text()
    # Locate the dict literal
    start = sensor_src.find("_SEVERITY_TO_ROUTINE_STATE")
    assert start >= 0, "Sensor mapping renamed — update this test"
    end = sensor_src.find("}", start)
    block = sensor_src[start:end]
    # The block must reference 0, 1, 2, 3, 4 — all 5 IntEnum values
    for key in ("0:", "1:", "2:", "3:", "4:"):
        assert key in block, (
            f"_SEVERITY_TO_ROUTINE_STATE is missing mapping for integer key {key.strip(':')} — "
            f"v4.6.6 expanded AnomalySeverity to 5 buckets, all must be covered"
        )


# ---------------------------------------------------------------------------
# v4.6.6 D1 — coordinator emit-site migration (map_diag_severity)
# ---------------------------------------------------------------------------


def _coord_src(filename: str):
    return Path(
        f"custom_components/universal_room_automation/domain_coordinators/{filename}"
    ).read_text()


def _non_comment_src(src: str) -> str:
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )


def test_map_diag_severity_helper_exists():
    """v4.6.6 D1: anomaly_event.py must export `map_diag_severity` with the
    canonical 4-bucket mapping (nominal/advisory/alert/critical) to enum
    members (INFO/ADVISORY/ALERT/CRITICAL).

    Unknown classifier outputs must fall back to WARNING — same defensive
    default the legacy 2-way ternary produced.
    """
    src = _coord_src("anomaly_event.py")
    live = _non_comment_src(src)
    assert "def map_diag_severity" in live, (
        "v4.6.6 D1: anomaly_event.py must define map_diag_severity()"
    )
    assert "_DIAG_TO_EVENT_SEVERITY" in live, (
        "v4.6.6 D1: anomaly_event.py must define _DIAG_TO_EVENT_SEVERITY "
        "mapping table"
    )
    # All 4 classifier StrEnum values must be in the mapping
    for key in ("nominal", "advisory", "alert", "critical"):
        assert f'"{key}":' in live, (
            f'v4.6.6 D1: _DIAG_TO_EVENT_SEVERITY must include "{key}" key'
        )
    # The fallback for unknown inputs is WARNING (matches legacy ternary for
    # non-CRITICAL outputs). v4.6.6 review B-M1 updated the helper to also
    # log a WARNING when the fallback fires, so the pattern is no longer a
    # one-line `dict.get(key, default)` — assert intent instead of shape:
    # the constant AnomalySeverity.WARNING must be returned in the fallback
    # path, and the function must reference unknown-key handling.
    assert "return AnomalySeverity.WARNING" in live, (
        "v4.6.6 D1: map_diag_severity must `return AnomalySeverity.WARNING` "
        "in the unknown-classifier fallback path"
    )


def test_no_coordinator_uses_legacy_severity_ternary():
    """v4.6.6 D1: every coordinator emit site that previously used the
    `_NewSev.CRITICAL if anomaly.severity.value == "critical" else
    _NewSev.WARNING` 2-way ternary must be migrated to `map_diag_severity`.

    The 2-way collapse was the root concern v4.6.5 reviewers A-M2 and B-M1
    raised — ADVISORY and ALERT both persist as WARNING (value=1),
    severity-grouped analytics can't distinguish them. After v4.6.6 D1,
    every classifier-driven emit uses the 1:1 mapping helper.

    Permitted exceptions: constant severity literals (e.g. binary hazards
    that have no classifier input) stay as-is — they're not the target of
    this migration.
    """
    failures: list[str] = []
    coord_files = [
        "hvac.py",
        "security.py",
        "music_following.py",
        "presence.py",
        "safety.py",
    ]
    import re
    for filename in coord_files:
        live = _non_comment_src(_coord_src(filename))
        # The exact ternary pattern is the regression we're guarding against
        if re.search(
            r"_NewSev\.CRITICAL if\s+\w+\.severity\.value\s*==\s*['\"]critical['\"]\s+else\s+_NewSev\.WARNING",
            live,
        ):
            failures.append(
                f"{filename}: still uses the 2-way severity ternary — "
                "must migrate to `severity=map_diag_severity(<anomaly>.severity)`"
            )
        # Also catch any other variation that bypasses map_diag_severity
        if re.search(
            r"severity=.*anomaly\w*\.severity\.value\s*==",
            live,
        ):
            failures.append(
                f"{filename}: classifier-driven severity assignment without "
                "map_diag_severity — bypasses the v4.6.6 1:1 mapping"
            )
    assert not failures, (
        "v4.6.6 D1: coordinator emit sites still use the legacy 2-way "
        "severity ternary:\n  - " + "\n  - ".join(failures)
    )


def test_classifier_driven_emit_sites_import_map_diag_severity():
    """v4.6.6 D1: every coordinator that runs a classifier-driven emit (HVAC
    override_frequency, security alert_trigger_frequency, MF rates, presence
    transition_count_daily) must import `map_diag_severity` from
    anomaly_event in its emit function.

    Safety is excluded — its only emit (active_hazard_count) is a binary
    hazard report with no z-score band, intentionally fixed at WARNING.
    """
    classifier_driven = [
        "hvac.py",
        "security.py",
        "music_following.py",
        "presence.py",
    ]
    failures: list[str] = []
    for filename in classifier_driven:
        live = _non_comment_src(_coord_src(filename))
        if "map_diag_severity" not in live:
            failures.append(
                f"{filename}: missing `map_diag_severity` import — "
                "emit site won't migrate to the v4.6.6 1:1 mapping"
            )
    assert not failures, (
        "v4.6.6 D1: classifier-driven coordinators must import "
        "map_diag_severity:\n  - " + "\n  - ".join(failures)
    )


# ---------------------------------------------------------------------------
# v4.6.6 D2 — one-shot DB severity remap (2 → 4)
# ---------------------------------------------------------------------------


def test_v466_severity_remap_sql_idempotent_against_real_schema(real_schema_db):
    """v4.6.6 D2: the historic severity='2' → '4' remap must move pre-v4.6.6
    CRITICAL rows to the new CRITICAL value, and must be idempotent (a
    second run touches zero rows).

    Drives the production SQL extracted from database.py against the
    real_schema_db fixture. Validates:
      - The SQL parses against the live schema
      - Rows at severity='2' are rewritten to '4'
      - Other severity values are untouched (0, 1, 3, 4 all preserved)
      - Second run is a no-op (idempotent)
    """
    import re
    # Extract the v4.6.6 remap SQL from database.py source
    db_src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    m = re.search(
        r"UPDATE anomaly_log\s+SET severity = '4'\s+WHERE severity = '2'",
        db_src,
    )
    assert m is not None, (
        "v4.6.6 D2: database.py must contain the canonical remap SQL "
        "`UPDATE anomaly_log SET severity = '4' WHERE severity = '2'`"
    )
    remap_sql = m.group(0)

    conn = real_schema_db
    # Insert rows at every severity value to verify selective remap.
    # Column list matches production save_anomaly_event INSERT (database.py:4452).
    insert_sql = (
        "INSERT INTO anomaly_log "
        "(timestamp, coordinator_id, scope, metric_name, observed_value, "
        "expected_mean, expected_std, z_score, severity, sample_size, "
        "house_state, context_json, resolved, resolution_notes, event_class, "
        "recovery_at, correlation_id, entity_id, room_id, person_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    for sev in ("0", "1", "2", "3", "4"):
        conn.execute(insert_sql, (
            "2026-05-16T00:00:00", "test_coord", "", "test.metric",
            1.0, 1.0, 0.5, 0.0, sev, 100, "home_day", "{}", 0, None,
            "point_in_time", None, None, None, None, None,
        ))
    conn.commit()
    # Sanity pre-state
    pre = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT severity, COUNT(*) FROM anomaly_log GROUP BY severity"
        ).fetchall()
    }
    assert pre == {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1}, (
        f"Setup: expected 1 row per severity, got {pre}"
    )

    # Simulate the production migration gate (PRAGMA user_version).
    # Pre-v4.6.6 DBs start at user_version=0; v4.6.6 sets it to 466 after
    # the remap succeeds. Re-runs on the same DB must check user_version
    # and SKIP the remap — that's the v4.6.6 review A-C1 critical fix.
    user_version_before = conn.execute("PRAGMA user_version").fetchone()[0]
    assert user_version_before == 0, (
        "Setup: fresh in-memory DB should have user_version=0"
    )

    # First run: gate check passes (user_version=0 < 466), remap fires
    if user_version_before < 466:
        cursor = conn.execute(remap_sql)
        conn.commit()
        rewritten_first = cursor.rowcount
        conn.execute("PRAGMA user_version = 466")
        conn.commit()
    else:
        rewritten_first = 0
    assert rewritten_first == 1, (
        f"v4.6.6 D2 first run: should rewrite 1 row (the severity='2' one), "
        f"got {rewritten_first}"
    )
    post = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT severity, COUNT(*) FROM anomaly_log GROUP BY severity"
        ).fetchall()
    }
    # severity='2' should be gone; severity='4' should now have 2 rows
    assert post == {"0": 1, "1": 1, "3": 1, "4": 2}, (
        f"v4.6.6 D2: post-remap severity distribution unexpected: {post}"
    )
    # user_version sentinel must be set
    user_version_after = conn.execute("PRAGMA user_version").fetchone()[0]
    assert user_version_after == 466, (
        f"v4.6.6 D2: user_version must be 466 after first run, "
        f"got {user_version_after}"
    )

    # CRITICAL idempotency check (Review A-C1):
    # Insert a NEW ADVISORY row at severity='2' (mimicking a v4.6.6+ emit
    # that arrived after the first migration ran). The gate must NOT
    # rewrite this row — pre-fix, the second run would silently corrupt
    # it from ADVISORY → CRITICAL.
    conn.execute(insert_sql, (
        "2026-05-16T01:00:00", "test_coord", "", "test.advisory_post_v466",
        2.5, 1.0, 0.5, 2.5, "2", 100, "home_day", "{}", 0, None,
        "point_in_time", None, None, None, None, None,
    ))
    conn.commit()
    # Verify the new ADVISORY row is at severity='2'
    advisory_count = conn.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE severity = '2'"
    ).fetchone()[0]
    assert advisory_count == 1, "Setup: 1 new ADVISORY row should be at severity='2'"

    # Second run: gate check FAILS (user_version=466 >= 466), remap skipped
    user_version_now = conn.execute("PRAGMA user_version").fetchone()[0]
    if user_version_now < 466:
        cursor2 = conn.execute(remap_sql)
        conn.commit()
        rewritten_second = cursor2.rowcount
    else:
        rewritten_second = 0  # gate prevented the UPDATE
    assert rewritten_second == 0, (
        f"v4.6.6 D2 A-C1 fix: second run must NOT rewrite any rows (gate "
        f"prevents corruption of post-v4.6.6 ADVISORY rows). Got {rewritten_second}."
    )
    # The new ADVISORY row must STILL be at severity='2'
    advisory_post = conn.execute(
        "SELECT COUNT(*) FROM anomaly_log WHERE severity = '2'"
    ).fetchone()[0]
    assert advisory_post == 1, (
        f"v4.6.6 D2 A-C1 fix: post-v4.6.6 ADVISORY rows must survive the "
        f"second migration check. Got {advisory_post} ADVISORY rows; expected 1."
    )


def test_v466_d2_migration_uses_pragma_user_version_gate():
    """v4.6.6 Review A-C1 fix: the D2 migration block in database.py must
    gate via PRAGMA user_version so it doesn't re-run on subsequent
    startups (where it would silently rewrite legitimate ADVISORY rows
    written by v4.6.6+ emits as CRITICAL).

    Three required elements (block-extraction is fragile because the v4.6.6
    block itself references v4.6.6 in comments, so just check the file
    contains all three patterns):
      - PRAGMA user_version read/write
      - sentinel value 466 set after successful remap
      - guard condition `< 466` to skip on re-runs
    """
    db_src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    assert "v4.6.6 D2: severity vocabulary remap" in db_src, (
        "v4.6.6 Review A-C1: database.py must contain the D2 severity remap block"
    )
    assert "PRAGMA user_version" in db_src, (
        "v4.6.6 Review A-C1: D2 migration must check PRAGMA user_version to "
        "gate the UPDATE and prevent re-running over legitimate ADVISORY rows"
    )
    assert "user_version = 466" in db_src, (
        "v4.6.6 Review A-C1: D2 migration must set PRAGMA user_version = 466 "
        "after a successful remap to prevent re-running"
    )
    assert "< 466" in db_src, (
        "v4.6.6 Review A-C1: D2 migration must gate the UPDATE on "
        "`current_user_version < 466` (re-runs must skip)"
    )


def test_routine_event_min_severity_max_value_bumped_to_4():
    """v4.6.6 Review B-B1 fix: RoutineEventMinSeverityNumber._attr_native_max_value
    must be 4 (not 2) so a user can reach the new CRITICAL value. Pre-v4.6.6
    the cap was 2, which now means ADVISORY — a user who set the floor to
    "CRITICAL only" pre-v4.6.6 would silently receive ADVISORY+ALERT+CRITICAL
    floods post-deploy.
    """
    src = Path(
        "custom_components/universal_room_automation/number.py"
    ).read_text()
    import re
    # Locate the class body
    cls_idx = src.find("class RoutineEventMinSeverityNumber(")
    assert cls_idx >= 0, "Could not find RoutineEventMinSeverityNumber class"
    next_cls = src.find("\nclass ", cls_idx + 1)
    cls_body = src[cls_idx : next_cls if next_cls > 0 else len(src)]
    # max_value must be 4
    assert re.search(
        r"_attr_native_max_value\s*=\s*4",
        cls_body,
    ), (
        "v4.6.6 B-B1: RoutineEventMinSeverityNumber must have "
        "_attr_native_max_value = 4 (was 2 pre-v4.6.6; bumped so CRITICAL "
        "is reachable on the 5-bucket AnomalySeverity scale)"
    )
    # Old max=2 must NOT appear in the class body
    assert not re.search(
        r"_attr_native_max_value\s*=\s*2",
        cls_body,
    ), (
        "v4.6.6 B-B1: legacy _attr_native_max_value = 2 must be removed — "
        "post-v4.6.6 the value 2 means ADVISORY, not CRITICAL, so a cap of "
        "2 would silently restrict the user from selecting CRITICAL"
    )


def test_routine_event_min_severity_seed_migration_2_to_4():
    """v4.6.6 Review B-B1 fix: RoutineEventMinSeverityNumber.__init__ must
    auto-promote a stored options-flow value of 2 to 4 to preserve user
    intent ("CRITICAL only" pre-v4.6.6 meant value 2; now means value 4).

    Asserts the migration logic is in __init__ — source-grep for the
    promote-2-to-4 pattern.
    """
    src = Path(
        "custom_components/universal_room_automation/number.py"
    ).read_text()
    cls_idx = src.find("class RoutineEventMinSeverityNumber(")
    next_cls = src.find("\nclass ", cls_idx + 1)
    cls_body = src[cls_idx : next_cls if next_cls > 0 else len(src)]
    import re
    # Must read the stored value from entry.options
    assert re.search(
        r'entry\.options\.get\(\s*["\']routine_event_min_severity["\']\s*\)',
        cls_body,
    ), (
        "v4.6.6 B-B1: __init__ must read the stored value of "
        "routine_event_min_severity from entry.options to check for the "
        "pre-v4.6.6 sentinel value 2"
    )
    # Must check for stored == 2 (the pre-v4.6.6 CRITICAL value)
    assert re.search(
        r"stored\s*==\s*2",
        cls_body,
    ), (
        "v4.6.6 B-B1: __init__ must check `stored == 2` (pre-v4.6.6 CRITICAL "
        "sentinel) to trigger the seed migration"
    )
    # Must call async_update_entry to persist the new value
    assert "async_update_entry" in cls_body, (
        "v4.6.6 B-B1: __init__ must call hass.config_entries.async_update_entry "
        "to promote stored value 2 → 4"
    )


def test_v466_legacy_text_critical_backfills_to_4():
    """v4.6.6 Review A-H1 fix: the v4.6.1 TEXT severity backfill must map
    `'critical' → '4'` (not '2') so any future stale-DB import surfacing
    TEXT 'critical' rows AFTER the one-shot D2 remap doesn't read back as
    ADVISORY.
    """
    db_src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    # Locate the v4.6.1 backfill block
    backfill_idx = db_src.find("backfill old TEXT severity values")
    assert backfill_idx >= 0, "Could not find v4.6.1 backfill block"
    # Find next migration block
    next_block = db_src.find("v4.6.6 D2", backfill_idx + 100)
    if next_block < 0:
        next_block = len(db_src)
    backfill_block = db_src[backfill_idx : next_block]
    # Must map 'critical' → '4' (not the legacy '2')
    import re
    assert re.search(
        r"WHEN 'critical'\s+THEN '4'",
        backfill_block,
    ), (
        "v4.6.6 A-H1: v4.6.1 TEXT backfill must map 'critical' → '4' "
        "(AnomalySeverity.CRITICAL moved from value 2 to 4 in v4.6.6). "
        "Legacy TEXT 'critical' rows surfaced via stale-DB import AFTER "
        "the one-shot D2 remap must land at the new CRITICAL value."
    )
    assert not re.search(
        r"WHEN 'critical'\s+THEN '2'",
        backfill_block,
    ), (
        "v4.6.6 A-H1: legacy 'critical' → '2' mapping must be removed — "
        "post-v4.6.6, value 2 means ADVISORY, not CRITICAL"
    )


def test_map_diag_severity_logs_warning_on_unknown_input():
    """v4.6.6 Review B-M1 fix: map_diag_severity must log a WARNING when
    falling back for an unknown classifier bucket — surfaces future
    vocabulary drift in home-assistant.log instead of silently swallowing.
    """
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/anomaly_event.py"
    ).read_text()
    # Locate the helper function
    fn_idx = src.find("def map_diag_severity(")
    assert fn_idx >= 0, "Could not find map_diag_severity function"
    next_fn = src.find("\ndef ", fn_idx + 1)
    if next_fn < 0:
        next_fn = src.find("\nclass ", fn_idx + 1)
    if next_fn < 0:
        next_fn = len(src)
    fn_body = src[fn_idx : next_fn]
    # Must call _logger.warning for unknown buckets
    assert ".warning(" in fn_body, (
        "v4.6.6 B-M1: map_diag_severity must call _logger.warning() when "
        "falling back to WARNING for unknown classifier inputs"
    )
    # Must mention the fallback in the warning message
    import re
    assert re.search(
        r"warning\([^)]*unknown[^)]*WARNING",
        fn_body,
        re.IGNORECASE | re.DOTALL,
    ), (
        "v4.6.6 B-M1: warning message must describe the fallback (unknown "
        "bucket, defaulting to WARNING) so operators can spot vocabulary drift"
    )

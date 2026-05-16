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

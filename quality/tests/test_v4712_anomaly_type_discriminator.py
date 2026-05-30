"""v4.7.12 D1-D4 — AnomalyType discriminator cycle tests.

Tests cover:
 - AnomalyType StrEnum surface (4 members, no extras).
 - Legacy EVENT_CLASS_* constants alias to AnomalyType members.
 - AnomalyEvent.__post_init__ accepts strings and rejects unknowns.
 - AnomalyEvent requires the anomaly_type kwarg (no default).
 - __all__ exports AnomalyType + legacy aliases.
 - Fresh-schema fixture has BOTH event_class AND anomaly_type columns.
 - v4.7.12 backfill migration copies event_class -> anomaly_type idempotently.
 - save_anomaly_event dual-writes both columns.
 - Resolution order prefers event.anomaly_type over event.event_class.
 - AST scans: every emit site uses anomaly_type= kwarg; zero raw strings.
 - regime_detector is the SOLE AnomalyType.REGIME_SHIFT emitter.
 - Schema extraction parses the new anomaly_type ALTER tuple from production.

The behavioral DB-touching tests share the real_schema_db fixture extracted
from production database.py (Bug Class #44 — no hand-copied DDL).
"""
from __future__ import annotations

import ast
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

# Python 3.9 compatibility: StrEnum is 3.11+. Mirror the production shim
# in domain_coordinators/anomaly_event.py.
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover — only fires on Python <3.11
    from enum import Enum as _Enum

    class StrEnum(str, _Enum):  # type: ignore[no-redef]
        def __str__(self) -> str:
            return str(self.value)


# ---------------------------------------------------------------------------
# Module loading helpers — load anomaly_event.py without HA installed.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_ANOMALY_EVENT_PY = (
    _REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "anomaly_event.py"
)
_DATABASE_PY = (
    _REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "database.py"
)
_CC_ROOT = _REPO_ROOT / "custom_components" / "universal_room_automation"


def _load_anomaly_event_module():
    mod_name = "ura_v4712_anomaly_event"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(_ANOMALY_EVENT_PY))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# AnomalyType enum surface
# ---------------------------------------------------------------------------

def test_anomaly_type_enum_members():
    """v4.7.12 D1: AnomalyType has exactly 4 members, no extras."""
    from enum import Enum as _Enum

    mod = _load_anomaly_event_module()
    # StrEnum subclass check is brittle when the production shim and the
    # test shim are imported separately (Python <3.11 case). Assert the
    # structural contract instead: it's an Enum, it's a str subclass, and
    # the four expected members are present with the expected values.
    assert issubclass(mod.AnomalyType, _Enum)
    assert issubclass(mod.AnomalyType, str)
    names = {m.name for m in mod.AnomalyType}
    assert names == {"POINT_IN_TIME", "REGIME_SHIFT", "HAZARD", "TRANSITION_INVALID"}
    values = {str(m) for m in mod.AnomalyType}
    assert values == {"point_in_time", "regime_shift", "hazard", "transition_invalid"}


def test_legacy_event_class_constants_alias_to_enum():
    """v4.7.12 D1: legacy EVENT_CLASS_* constants are AnomalyType members."""
    mod = _load_anomaly_event_module()
    assert mod.EVENT_CLASS_POINT_IN_TIME is mod.AnomalyType.POINT_IN_TIME
    assert mod.EVENT_CLASS_REGIME_SHIFT is mod.AnomalyType.REGIME_SHIFT
    assert mod.EVENT_CLASS_HAZARD is mod.AnomalyType.HAZARD
    assert mod.EVENT_CLASS_TRANSITION_INVALID is mod.AnomalyType.TRANSITION_INVALID
    # StrEnum members equal their string values — back-compat preserved.
    assert mod.EVENT_CLASS_POINT_IN_TIME == "point_in_time"
    assert mod.EVENT_CLASS_HAZARD == "hazard"


def test_anomaly_event_post_init_accepts_string():
    """v4.7.12 D1: legacy raw-string callers still work — coerced to enum."""
    mod = _load_anomaly_event_module()
    ev = mod.AnomalyEvent(
        coordinator="energy",
        type="energy.crosscheck_divergence",
        severity=mod.AnomalySeverity.WARNING,
        anomaly_type="point_in_time",  # legacy raw string
        detected_at="2026-05-30T10:00:00",
    )
    assert ev.anomaly_type is mod.AnomalyType.POINT_IN_TIME
    # event_class property alias mirrors anomaly_type during dual-write window.
    assert ev.event_class is mod.AnomalyType.POINT_IN_TIME


def test_anomaly_event_post_init_rejects_unknown():
    """v4.7.12 D1: unknown discriminator strings raise ValueError at write time."""
    mod = _load_anomaly_event_module()
    with pytest.raises(ValueError, match="AnomalyType"):
        mod.AnomalyEvent(
            coordinator="bayesian",
            type="bayesian.prediction_anomaly",
            severity=mod.AnomalySeverity.WARNING,
            anomaly_type="not_a_real_class",  # drift — must raise
            detected_at="2026-05-30T10:00:00",
        )


def test_anomaly_event_post_init_rejects_none():
    """v4.7.12 C-M1 fix-up: ``anomaly_type=None`` raises TypeError.

    Pre-fix-up, None slipped past ``isinstance(None, str)`` (False),
    the dataclass kept ``self.anomaly_type = None``, and the production
    DAO defaulted it to "point_in_time" — defeating "never rely on the
    default." Now: rejected at construction with TypeError.
    """
    mod = _load_anomaly_event_module()
    with pytest.raises(TypeError, match="AnomalyType or str"):
        mod.AnomalyEvent(
            coordinator="x",
            type="x.y",
            severity=mod.AnomalySeverity.INFO,
            anomaly_type=None,  # type: ignore[arg-type]
            detected_at="2026-05-30T10:00:00",
        )


def test_anomaly_event_requires_anomaly_type_kwarg():
    """v4.7.12 D2 contract: anomaly_type is a required field (no default)."""
    mod = _load_anomaly_event_module()
    with pytest.raises(TypeError):
        # Missing anomaly_type — dataclass must raise TypeError.
        mod.AnomalyEvent(  # type: ignore[call-arg]
            coordinator="x",
            type="x.y",
            severity=mod.AnomalySeverity.INFO,
            detected_at="2026-05-30T10:00:00",
        )


# ---------------------------------------------------------------------------
# Module export surface (D3)
# ---------------------------------------------------------------------------

def test_anomaly_type_in_module_all():
    """v4.7.12 D3: AnomalyType + legacy aliases in __all__."""
    mod = _load_anomaly_event_module()
    assert hasattr(mod, "__all__")
    assert "AnomalyType" in mod.__all__
    for legacy in (
        "EVENT_CLASS_POINT_IN_TIME",
        "EVENT_CLASS_REGIME_SHIFT",
        "EVENT_CLASS_HAZARD",
        "EVENT_CLASS_TRANSITION_INVALID",
    ):
        assert legacy in mod.__all__


def test_anomaly_type_importable_from_public_path():
    """v4.7.12 D3: AnomalyType is the canonical import path for v4.7.13+ consumers."""
    from enum import Enum as _Enum

    mod = _load_anomaly_event_module()
    # The module attribute access mirrors the production import statement
    # `from custom_components.universal_room_automation.domain_coordinators.anomaly_event
    #  import AnomalyType`. Structural-only checks because the local StrEnum
    # shim and any cross-module StrEnum may not be the same class on <3.11.
    AnomalyType = getattr(mod, "AnomalyType")
    assert issubclass(AnomalyType, _Enum)
    assert issubclass(AnomalyType, str)


# ---------------------------------------------------------------------------
# Schema extraction (Bug Class #44 — production source as fixture authority)
# ---------------------------------------------------------------------------

def test_schema_extraction_finds_anomaly_type_alter_tuple():
    """v4.7.12 D4: conftest_db parser must find the new anomaly_type tuple.

    Bug Class #44 lesson: test fixtures extract schema from production source,
    never hand-copy. The parser in quality/tests/conftest_db.py must pick up
    the new ('anomaly_type', 'TEXT DEFAULT \\'point_in_time\\'') entry.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    try:
        from tests.conftest_db import _extract_alter_table_statements
    finally:
        sys.path.pop(0)
    src = _DATABASE_PY.read_text()
    stmts = _extract_alter_table_statements(src, "anomaly_log")
    # Expect both legacy event_class AND new anomaly_type tuples extracted.
    assert any("anomaly_type" in s for s in stmts), (
        "conftest_db._extract_alter_table_statements did not find the v4.7.12 "
        "anomaly_type tuple — fix the parser before relying on it."
    )
    assert any("event_class" in s for s in stmts), (
        "Legacy event_class tuple still extracted during dual-write window."
    )


def test_fresh_schema_has_both_columns(real_schema_db):
    """v4.7.12 D1: fresh-install schema includes BOTH event_class AND anomaly_type."""
    conn = real_schema_db
    cols = {row[1] for row in conn.execute("PRAGMA table_info(anomaly_log)").fetchall()}
    assert "event_class" in cols, "Legacy event_class column missing (dual-write window)"
    assert "anomaly_type" in cols, "v4.7.12 anomaly_type column missing"


def test_fresh_vs_upgrade_schema_column_order_identical():
    """v4.7.12 A1 fix-up: fresh CREATE TABLE + ALTER chain must match upgrade ALTER chain.

    Planning doc §10 invariant: "Fresh-install CREATE TABLE produces a row
    layout identical to an upgrade-installed table." The pre-fix-up code
    embedded ``anomaly_type`` in the base CREATE TABLE at column 16 while
    leaving the v4.6.1 ALTER tuple list to add the legacy alias columns
    (event_class, recovery_at, ...) AFTER it. Upgrade installs landed
    anomaly_type at the END (column 22). The two paths diverged.

    Fix: drop anomaly_type from base CREATE TABLE; let the ALTER chain
    seat it last in BOTH paths. This test compares PRAGMA table_info
    ordering of a fresh-install simulation against an upgrade simulation.
    """
    # Fresh install: real_schema_db builds CREATE + ALTERs in one pass —
    # mirrors what the integration does on a brand-new HA instance.
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent))
    try:
        from tests.conftest_db import _build_schema
    finally:
        _sys.path.pop(0)

    fresh_conn = sqlite3.connect(":memory:")
    fresh_conn.row_factory = sqlite3.Row
    _build_schema(fresh_conn)
    fresh_cols = [
        row[1]
        for row in fresh_conn.execute("PRAGMA table_info(anomaly_log)").fetchall()
    ]
    fresh_conn.close()

    # Upgrade install simulation: build the *pre-v4.6.1* base table
    # (no event_class, no recovery_at, no anomaly_type ...) then apply
    # the v4.6.1 ALTER tuple list in production order.
    upgrade_conn = sqlite3.connect(":memory:")
    upgrade_conn.row_factory = sqlite3.Row
    upgrade_conn.execute(
        """CREATE TABLE anomaly_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            coordinator_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            observed_value REAL,
            expected_mean REAL,
            expected_std REAL,
            z_score REAL,
            severity TEXT NOT NULL,
            sample_size INTEGER,
            house_state TEXT,
            context_json TEXT,
            resolved BOOLEAN NOT NULL DEFAULT 0,
            resolution_notes TEXT
        )"""
    )
    # Replay v4.6.1 ALTER tuple list in production order (database.py:~1241).
    for col_name, col_def in (
        ("event_class", "TEXT DEFAULT 'point_in_time'"),
        ("recovery_at", "TEXT NULL"),
        ("correlation_id", "TEXT NULL"),
        ("entity_id", "TEXT NULL"),
        ("room_id", "TEXT NULL"),
        ("person_id", "TEXT NULL"),
        ("anomaly_type", "TEXT DEFAULT 'point_in_time'"),
    ):
        upgrade_conn.execute(
            f"ALTER TABLE anomaly_log ADD COLUMN {col_name} {col_def}"
        )
    upgrade_conn.commit()
    upgrade_cols = [
        row[1]
        for row in upgrade_conn.execute("PRAGMA table_info(anomaly_log)").fetchall()
    ]
    upgrade_conn.close()

    assert fresh_cols == upgrade_cols, (
        "Fresh-install vs upgrade-install anomaly_log column ordering diverged.\n"
        f"  fresh:   {fresh_cols}\n"
        f"  upgrade: {upgrade_cols}"
    )
    # Belt-and-suspenders: anomaly_type lands last in BOTH paths.
    assert fresh_cols[-1] == "anomaly_type", (
        f"anomaly_type must be the last column; got {fresh_cols!r}"
    )


# ---------------------------------------------------------------------------
# Backfill migration behavior
# ---------------------------------------------------------------------------

# Minimal stand-in for the v4.7.12 migration block (mirrors the production
# logic so we can test it without a full async aiosqlite stack).
_BACKFILL_SQL = (
    "UPDATE anomaly_log "
    "SET anomaly_type = COALESCE(event_class, 'point_in_time') "
    "WHERE anomaly_type IS NULL OR anomaly_type = 'point_in_time'"
)


def _run_backfill_once(conn: sqlite3.Connection) -> int:
    cur = conn.execute("PRAGMA user_version")
    uv = cur.fetchone()[0]
    if uv >= 4712:
        return 0
    cur = conn.execute(_BACKFILL_SQL)
    rowcount = cur.rowcount if cur.rowcount >= 0 else 0
    conn.execute("PRAGMA user_version = 4712")
    conn.commit()
    return rowcount


def _insert_legacy_row(
    conn: sqlite3.Connection,
    event_class_val: str = "point_in_time",
    timestamp: str = "2026-05-30T10:00:00",
) -> int:
    # Use the production INSERT shape WITHOUT the new anomaly_type column
    # (simulates a pre-v4.7.12 emit that only wrote event_class).
    cur = conn.execute(
        """INSERT INTO anomaly_log
           (timestamp, coordinator_id, scope, metric_name,
            observed_value, expected_mean, expected_std, z_score,
            severity, sample_size, house_state, context_json,
            resolved, resolution_notes, event_class,
            recovery_at, correlation_id, entity_id, room_id, person_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            timestamp, "test_coord", "", "test.metric",
            None, None, None, None,
            1, None, None, "{}",
            0, None, event_class_val,
            None, None, None, None, None,
        ),
    )
    conn.commit()
    return cur.lastrowid


def test_migration_backfill_copies_event_class_to_anomaly_type(real_schema_db):
    """v4.7.12 D1: backfill copies event_class into anomaly_type for legacy rows."""
    conn = real_schema_db
    # Simulate legacy state: rows with event_class set but anomaly_type defaulted.
    rid_pit = _insert_legacy_row(conn, "point_in_time")
    rid_rs = _insert_legacy_row(conn, "regime_shift")
    rid_hz = _insert_legacy_row(conn, "hazard")

    # Reset user_version to simulate a pre-v4.7.12 DB.
    conn.execute("PRAGMA user_version = 467")
    conn.commit()

    backfilled = _run_backfill_once(conn)
    assert backfilled >= 1, "Backfill must update at least the legacy-shape rows"

    for rid, expected in (
        (rid_pit, "point_in_time"),
        (rid_rs, "regime_shift"),
        (rid_hz, "hazard"),
    ):
        row = conn.execute(
            "SELECT event_class, anomaly_type FROM anomaly_log WHERE id = ?",
            (rid,),
        ).fetchone()
        assert row["anomaly_type"] == expected, (
            f"row id={rid}: anomaly_type must equal event_class after backfill"
        )

    # PRAGMA user_version sentinel set.
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    assert uv == 4712


def test_migration_idempotent_under_user_version_gate(real_schema_db):
    """v4.7.12 D1: backfill is a no-op on second run (PRAGMA user_version gate)."""
    conn = real_schema_db
    rid = _insert_legacy_row(conn, "regime_shift")
    conn.execute("PRAGMA user_version = 467")
    conn.commit()

    first = _run_backfill_once(conn)
    second = _run_backfill_once(conn)
    assert second == 0, "Second migration run must be a no-op"
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    assert uv == 4712


# ---------------------------------------------------------------------------
# DAO dual-write behavior
# ---------------------------------------------------------------------------

def test_fake_anomaly_event_rejects_invalid_anomaly_type():
    """v4.7.12 C-H2 fix-up: _FakeAnomalyEvent mirrors production validation.

    Reviewer C found that ``_FakeAnomalyEvent.__init__`` did not validate
    its ``anomaly_type`` against the AnomalyType closed set — letting
    tests smuggle garbage discriminators through the helper-based test
    paths even though the production ``AnomalyEvent.__post_init__`` would
    reject the same value. With the fix-up, the helper now raises
    ``ValueError`` on unknown values, mirroring the production contract.
    """
    from tests.test_v463_behavioral_dao import _FakeAnomalyEvent

    with pytest.raises(ValueError, match="anomaly_type"):
        _FakeAnomalyEvent(anomaly_type="banana")


def test_save_anomaly_event_dual_writes_both_columns(real_schema_db):
    """v4.7.12 D1: save_anomaly_event writes the same value to both columns."""
    from tests.test_v463_behavioral_dao import _insert_anomaly, _FakeAnomalyEvent

    event = _FakeAnomalyEvent(
        coordinator="safety",
        type="hazard.smoke",
        severity=4,
        anomaly_type="hazard",
    )
    row_id = _insert_anomaly(real_schema_db, event)
    row = real_schema_db.execute(
        "SELECT event_class, anomaly_type FROM anomaly_log WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert row["event_class"] == "hazard"
    assert row["anomaly_type"] == "hazard"
    assert row["event_class"] == row["anomaly_type"]


def test_insert_anomaly_helper_resolution_order_or_semantics(
    real_schema_db,
):
    """v4.7.12 C-H1 fix-up: test the TEST-HELPER ``_insert_anomaly`` resolution.

    Honest naming: this test exercises ``_insert_anomaly`` in
    ``test_v463_behavioral_dao.py``, NOT the production DAO. The helper's
    resolution chain is:

        _discriminator = (
            getattr(event, "anomaly_type", None)
            or getattr(event, "event_class", None)
        )

    which is the ``or`` short-circuit — distinct from the production DAO's
    explicit ``is None`` chain at ``database.py:4765-4769``. Both forms
    agree when one attr is non-None and the other is None; they diverge
    only on falsy-but-not-None values (the empty string), which no caller
    constructs. We assert the agreement case (anomaly_type wins, both
    columns get its value via dual-write).

    The PRODUCTION resolution order is covered separately by
    ``test_save_anomaly_event_production_resolution_prefers_anomaly_type``.
    """
    from tests.test_v463_behavioral_dao import _insert_anomaly, _FakeAnomalyEvent

    event = _FakeAnomalyEvent(
        coordinator="bayesian",
        type="bayesian.routine_shift",
        severity=3,
        anomaly_type="regime_shift",
    )
    # Force event_class to a different value so the resolution order is
    # observable. The _FakeAnomalyEvent's __init__ keeps them in sync; we
    # override after construction.
    event.event_class = "point_in_time"
    row_id = _insert_anomaly(real_schema_db, event)
    row = real_schema_db.execute(
        "SELECT event_class, anomaly_type FROM anomaly_log WHERE id = ?",
        (row_id,),
    ).fetchone()
    # Both columns get the anomaly_type value (test-side mirrors prod DAO).
    assert row["anomaly_type"] == "regime_shift"
    assert row["event_class"] == "regime_shift"


def test_save_anomaly_event_production_resolution_prefers_anomaly_type():
    """v4.7.12 C-H1 fix-up: drive the REAL ``save_anomaly_event`` resolution.

    Reviewer C found that the original
    ``test_save_anomaly_event_resolution_prefers_anomaly_type_over_event_class``
    test used the test-helper ``_insert_anomaly`` rather than the production
    DAO. The two are subtly different (helper uses ``or``, production uses
    ``is None``). This test extracts the production resolution block from
    ``database.py`` by AST and exec()s it against duck-typed events with
    the discriminating attributes disagreeing — confirming the production
    code path picks ``anomaly_type`` over ``event_class``.

    This is source-authoritative (Bug Class #44): if the resolution block
    in ``save_anomaly_event`` changes, this test executes the NEW code.
    """
    src = _DATABASE_PY.read_text()
    # Locate the resolution block inside save_anomaly_event. We narrow
    # using two anchors that bracket the production resolution chain
    # (see database.py:~4756-4770).
    head = src.find("async def save_anomaly_event(")
    assert head >= 0, "save_anomaly_event not found in database.py"
    body_end = src.find("\n    async def ", head + 1)
    body = src[head:body_end if body_end > 0 else head + 8000]
    anchor = '_discriminator = getattr(event, "anomaly_type"'
    start = body.find(anchor)
    assert start >= 0, (
        "Could not locate '_discriminator = getattr(event, \"anomaly_type\"' "
        "anchor in save_anomaly_event body — production resolution block "
        "moved or was restructured. Update this test."
    )
    # Walk backward to the start of the line so we capture the leading
    # indent. textwrap.dedent then strips the uniform indent across all
    # lines, leaving column-0 statements ready for compile()/exec().
    line_start = body.rfind("\n", 0, start) + 1
    end_anchor = body.find("try:", start)
    assert end_anchor > start, (
        "Could not find 'try:' terminator after _discriminator block — "
        "production DAO restructured."
    )
    # Walk back to the line start of the 'try:' to avoid splitting it.
    end_line_start = body.rfind("\n", 0, end_anchor) + 1
    resolution_block = body[line_start:end_line_start]
    import textwrap
    resolution_block = textwrap.dedent(resolution_block)

    class _Evt:
        anomaly_type = "regime_shift"
        event_class = "point_in_time"  # disagrees with anomaly_type

    ns = {"event": _Evt()}
    exec(compile(resolution_block, "<production_resolution>", "exec"), ns, ns)
    assert ns["_discriminator_str"] == "regime_shift", (
        "Production resolution chain must prefer anomaly_type over event_class; "
        f"got _discriminator_str={ns['_discriminator_str']!r}"
    )

    # Also verify the None fallback to event_class.
    class _EvtOnlyLegacy:
        anomaly_type = None
        event_class = "hazard"

    ns2 = {"event": _EvtOnlyLegacy()}
    exec(compile(resolution_block, "<production_resolution>", "exec"), ns2, ns2)
    assert ns2["_discriminator_str"] == "hazard", (
        "Production resolution chain must fall back to event_class when "
        f"anomaly_type is None; got {ns2['_discriminator_str']!r}"
    )

    # And the final default-to-point_in_time fallback.
    class _EvtNone:
        anomaly_type = None
        event_class = None

    ns3 = {"event": _EvtNone()}
    exec(compile(resolution_block, "<production_resolution>", "exec"), ns3, ns3)
    assert ns3["_discriminator_str"] == "point_in_time", (
        "Production resolution must default to 'point_in_time' when both "
        f"attrs are None; got {ns3['_discriminator_str']!r}"
    )


# ---------------------------------------------------------------------------
# AST drift prevention — D2 acceptance criteria
# ---------------------------------------------------------------------------

# Files that legitimately construct AnomalyEvent in production. Anything else
# under custom_components/ that calls AnomalyEvent(...) and DOESN'T appear
# here would either be new (add it) or unexpected (the drift-detection test
# catches it).
_EMIT_FILES = [
    _CC_ROOT / "binary_sensor.py",
    _CC_ROOT / "__init__.py",
    _CC_ROOT / "transitions.py",
    _CC_ROOT / "domain_coordinators" / "hvac.py",
    _CC_ROOT / "domain_coordinators" / "energy.py",
    _CC_ROOT / "domain_coordinators" / "regime_detector.py",
    _CC_ROOT / "domain_coordinators" / "coordinator_diagnostics.py",
    _CC_ROOT / "domain_coordinators" / "presence.py",
    _CC_ROOT / "domain_coordinators" / "security.py",
    _CC_ROOT / "domain_coordinators" / "notification_manager.py",
    _CC_ROOT / "domain_coordinators" / "music_following.py",
    _CC_ROOT / "domain_coordinators" / "safety.py",
]


def _iter_anomaly_event_calls(path: Path):
    """Yield ast.Call nodes that construct AnomalyEvent in `path`."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # AnomalyEvent(...) — bare Name reference
        if isinstance(func, ast.Name) and func.id == "AnomalyEvent":
            yield node
        # ae.AnomalyEvent(...) — Attribute reference (rare; some imports do this)
        elif isinstance(func, ast.Attribute) and func.attr == "AnomalyEvent":
            yield node


def test_all_anomaly_event_callers_use_anomaly_type_kwarg():
    """v4.7.12 D2: every AnomalyEvent(...) emit uses anomaly_type=, never event_class=."""
    offenders = []
    for path in _EMIT_FILES:
        if not path.exists():
            continue
        for call in _iter_anomaly_event_calls(path):
            kw_names = {kw.arg for kw in call.keywords if kw.arg}
            if "anomaly_type" not in kw_names:
                offenders.append(f"{path.name}:{call.lineno} missing anomaly_type=")
            if "event_class" in kw_names:
                offenders.append(f"{path.name}:{call.lineno} uses legacy event_class=")
    assert not offenders, (
        "v4.7.12 D2 drift detected — every AnomalyEvent(...) call must pass "
        "anomaly_type= (not event_class=). Offenders:\n  " + "\n  ".join(offenders)
    )


def test_no_raw_string_anomaly_type_in_production():
    """v4.7.12 D2: anomaly_type= RHS is a Name or Attribute, never a raw string."""
    offenders = []
    for path in _EMIT_FILES:
        if not path.exists():
            continue
        for call in _iter_anomaly_event_calls(path):
            for kw in call.keywords:
                if kw.arg != "anomaly_type":
                    continue
                v = kw.value
                # Acceptable: Attribute (AnomalyType.X) or Name (legacy alias)
                if isinstance(v, ast.Attribute):
                    continue
                if isinstance(v, ast.Name):
                    continue
                # Anything else (Constant string, BinOp, Call, etc.) is drift.
                offenders.append(
                    f"{path.name}:{kw.lineno} anomaly_type= has non-typed value "
                    f"({type(v).__name__})"
                )
    assert not offenders, (
        "v4.7.12 D2 drift — anomaly_type= must reference AnomalyType.* or the "
        "legacy EVENT_CLASS_* alias, never a raw string. Offenders:\n  "
        + "\n  ".join(offenders)
    )


def test_regime_shift_sole_emitter_unchanged():
    """v4.7.12 D2: regime_detector.py is the SOLE AnomalyType.REGIME_SHIFT emit site.

    Protects v4.7.13+ scoping — adding a new REGIME_SHIFT emitter is a
    cycle-level decision, not an in-place edit. If a future cycle wants
    to add another REGIME_SHIFT site, update this allowlist explicitly.
    """
    sole_allowed = {"regime_detector.py"}
    offenders = []
    for path in _EMIT_FILES:
        if not path.exists():
            continue
        for call in _iter_anomaly_event_calls(path):
            for kw in call.keywords:
                if kw.arg != "anomaly_type":
                    continue
                v = kw.value
                # AnomalyType.REGIME_SHIFT — attribute form
                if (
                    isinstance(v, ast.Attribute)
                    and v.attr == "REGIME_SHIFT"
                ):
                    if path.name not in sole_allowed:
                        offenders.append(
                            f"{path.name}:{kw.lineno} emits AnomalyType.REGIME_SHIFT "
                            f"— only {sole_allowed} may do so"
                        )
                # Legacy alias EVENT_CLASS_REGIME_SHIFT — name form
                if (
                    isinstance(v, ast.Name)
                    and v.id == "EVENT_CLASS_REGIME_SHIFT"
                ):
                    if path.name not in sole_allowed:
                        offenders.append(
                            f"{path.name}:{kw.lineno} emits EVENT_CLASS_REGIME_SHIFT "
                            f"— only {sole_allowed} may do so"
                        )
    assert not offenders, (
        "v4.7.12 D2 scope guard — REGIME_SHIFT emitter list expanded outside "
        f"the allowlist {sole_allowed}. Offenders:\n  " + "\n  ".join(offenders)
    )

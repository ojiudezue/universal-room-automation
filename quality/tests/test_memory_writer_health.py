"""MEMORY-WRITERS-SILENT-DROP-1 D3 — weekly writer-health trip-wire.

Covers:
  * A writer-backed episode_type with zero rows in 7d fires a WARNING
    log AND exactly one anomaly row via `save_anomaly_event`.
  * An exempt type with zero rows does NOT fire an anomaly.
  * A writer-backed type with rows does NOT fire an anomaly.
  * The weekly cadence guard suppresses a repeat run within 7d.

The test exercises the method as a plain Python callable against a
minimal fake URADatabase that supplies the three touchpoints the method
needs: ``_db()`` async context manager, ``save_anomaly_event``, and the
RAM cadence timestamp.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

import importlib.util as _import_util  # noqa: E402
import sys as _sys  # noqa: E402
import types as _types  # noqa: E402
from unittest.mock import MagicMock as _MagicMock  # noqa: E402

_URA_DIR = Path(__file__).resolve().parents[2] / (
    "custom_components/universal_room_automation"
)


# Mirror the loader shim used in test_memory_writers.py so a mocked
# parent package from an earlier test doesn't block us.
for _k in list(_sys.modules.keys()):
    if (
        _k == "custom_components.universal_room_automation"
        or _k.startswith("custom_components.universal_room_automation.")
    ):
        if isinstance(_sys.modules[_k], _MagicMock):
            del _sys.modules[_k]

_pkg_name = "custom_components.universal_room_automation"
if _pkg_name not in _sys.modules:
    _pkg = _types.ModuleType(_pkg_name)
    _pkg.__path__ = [str(_URA_DIR)]
    _sys.modules[_pkg_name] = _pkg
if "custom_components" not in _sys.modules:
    _cc = _types.ModuleType("custom_components")
    _cc.__path__ = [str(_URA_DIR.parent)]
    _sys.modules["custom_components"] = _cc


def _load_by_path(fq_name, path):
    spec = _import_util.spec_from_file_location(fq_name, str(path))
    mod = _import_util.module_from_spec(spec)
    _sys.modules[fq_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load const so the method under test can import constants from it.
# Fix-up #5: a sibling test (test_memory_writers.py) also runs this
# same ``_load_by_path`` against ``const.py`` during ITS module import,
# which overwrites ``sys.modules[_pkg_name + ".const"]`` with a FRESH
# module object. If pytest's collection import order puts the sibling
# AFTER this file, the local ``_const`` captured here points to a stale
# module while production (``from .const import ...``) resolves to the
# newer one. Monkeypatching ``_const`` then silently misses.
#
# Fix: always resolve ``_const`` from ``sys.modules`` at CALL time, so
# the test and production share the exact same module object regardless
# of collection order.
_load_by_path(f"{_pkg_name}.const", _URA_DIR / "const.py")


def _const():  # noqa: N802 — read as attribute, not function in call sites
    return _sys.modules[f"{_pkg_name}.const"]


class _Cursor:
    def __init__(self, row, rows=None):
        self._row = row
        self._rows = rows if rows is not None else []

    async def fetchone(self):
        return self._row

    async def fetchall(self):
        return self._rows


class _FakeDBConn:
    """Yields counts from a prepared mapping ``{(ep_type, since): count}``.

    The method under test issues:
        SELECT COUNT(*) FROM memory_episodes
        WHERE episode_type = ? AND started_at >= ?
    """

    def __init__(self, counts_by_type, house=None):
        self._counts = counts_by_type
        self._house = house  # sqlite3 connection holding house_state_log

    async def execute(self, _sql, params):
        if "house_state_log" in _sql:
            # Review B-L4: house-absence read runs real SQL on a real
            # sqlite house_state_log (None = empty table -> no proof).
            if self._house is None:
                return _Cursor(None, [])
            rows = self._house.execute(_sql, params).fetchall()
            return _Cursor(rows[0] if rows else None, rows)
        ep_type = params[0]
        count = self._counts.get(ep_type, 0)
        return _Cursor((count,))


class _FakeURADatabase:
    """Stand-in that implements the surface the method consumes."""

    def __init__(self, counts_by_type, house=None):
        self._counts_by_type = counts_by_type
        self._house = house
        self.anomaly_events: list = []
        self._last_memory_writer_health_check_ts = None
        # Fix-up #7: minimal energy_state key/value surface so the
        # production code's persist/restore round-trip can execute.
        self._energy_state: dict[str, str] = {}

    @asynccontextmanager
    async def _db(self):
        yield _FakeDBConn(self._counts_by_type, self._house)

    async def _memory_writer_house_absent_throughout(self, since_utc):
        return await _db_class()._memory_writer_house_absent_throughout(self, since_utc)

    async def save_anomaly_event(self, event):
        self.anomaly_events.append(event)

    async def save_energy_state(self, key: str, value: str) -> None:
        self._energy_state[key] = value

    async def restore_energy_state(self, key: str):
        return self._energy_state.get(key)


# Bind the real method off the production URADatabase class and invoke
# it as a free function against the fake. Avoids rebuilding
# URADatabase's full __init__.
def _db_class():
    db_mod = _sys.modules.get(f"{_pkg_name}.database")
    if db_mod is None or not hasattr(db_mod, "URADatabase"):
        _bind_method()
        db_mod = _sys.modules[f"{_pkg_name}.database"]
    return getattr(db_mod, "URADatabase", None) or getattr(db_mod, "UniversalRoomDatabase")


def _bind_method():
    # Lazy-load database.py by file path to avoid full HA runtime.
    # NOTE: database.py imports HA bits; we rely on the test harness
    # (`bootstrap_energy_imports`) to pre-stub those. If the import
    # fails under this harness we skip the suite with a clear reason.
    try:
        db_mod = _load_by_path(
            f"{_pkg_name}.database", _URA_DIR / "database.py",
        )
    except Exception as e:  # pragma: no cover — harness guard
        pytest.skip(f"database.py not loadable in this test harness: {e}")
    cls = getattr(db_mod, "URADatabase", None) or getattr(
        db_mod, "UniversalRoomDatabase",
    )
    return cls.run_memory_writer_health_check


@pytest.mark.asyncio
async def test_zero_row_writer_backed_type_fires_anomaly(caplog):
    run = _bind_method()
    # All writer-backed types return 0 rows.
    counts = {t: 0 for t in _const().MEMORY_WRITER_BACKED_EPISODE_TYPES}
    db = _FakeURADatabase(counts)
    with caplog.at_level(logging.WARNING):
        stats = await run(db, cadence_days=7, triggered_by="nightly")
    assert stats is not None
    expected = sorted(
        t for t in _const().MEMORY_WRITER_BACKED_EPISODE_TYPES
        if t not in _const().MEMORY_WRITER_HEALTH_EXEMPT_TYPES
    )
    assert stats["zero_row_types"] == expected
    # One anomaly event per silent writer.
    assert len(db.anomaly_events) == len(expected)
    assert all(
        getattr(e, "coordinator", None) == "memory_writer_health"
        for e in db.anomaly_events
    )
    # WARNING line present.
    assert any(
        "memory_writer_health" in rec.message
        and "0 rows" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_nonzero_writer_backed_type_does_not_fire(caplog):
    run = _bind_method()
    counts = {t: 3 for t in _const().MEMORY_WRITER_BACKED_EPISODE_TYPES}
    db = _FakeURADatabase(counts)
    with caplog.at_level(logging.WARNING):
        stats = await run(db, cadence_days=7, triggered_by="nightly")
    assert stats is not None
    assert stats["zero_row_types"] == []
    assert db.anomaly_events == []


@pytest.mark.asyncio
async def test_exempt_type_with_zero_rows_does_not_fire(monkeypatch):
    run = _bind_method()
    # Pick one real writer-backed type and exempt it; set its count to 0
    # and give the others nonzero rows. Expectation: no anomaly fires.
    writer_types = list(_const().MEMORY_WRITER_BACKED_EPISODE_TYPES)
    assert writer_types, "test precondition"
    exempt_type = writer_types[0]
    monkeypatch.setattr(
        _const(), "MEMORY_WRITER_HEALTH_EXEMPT_TYPES",
        frozenset({exempt_type}),
    )
    counts = {t: 5 for t in writer_types}
    counts[exempt_type] = 0
    db = _FakeURADatabase(counts)
    stats = await run(db, cadence_days=7, triggered_by="nightly")
    assert stats is not None
    assert exempt_type not in stats["zero_row_types"]
    assert db.anomaly_events == []


@pytest.mark.asyncio
async def test_cadence_guard_skips_repeat_within_window():
    run = _bind_method()
    db = _FakeURADatabase({t: 1 for t in _const().MEMORY_WRITER_BACKED_EPISODE_TYPES})
    first = await run(db, cadence_days=7, triggered_by="nightly")
    assert first is not None
    second = await run(db, cadence_days=7, triggered_by="nightly")
    assert second is None, (
        "Within 7d the nightly path must no-op; got a second real run."
    )


# ----------------------------------------------------------------------
# Person sightings review B-L4: a crossing-only writer (egress outcome) is
# not paged when house_state_log proves the house was away/vacation for the
# whole 7-day window. Real sqlite house_state_log; naive-UTC timestamps as
# log_house_state_change writes them.
# ----------------------------------------------------------------------

_EGRESS = "egress_identity_outcome"


def _house(con, rows):
    """rows: [(days_ago, state)] -> house_state_log on ``con``, whose schema
    is extracted from production database.py (conftest_db.real_schema_db;
    review C-M4: never hand-typed DDL)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for days_ago, state in rows:
        con.execute(
            "INSERT INTO house_state_log (timestamp, state, confidence) VALUES (?, ?, 1.0)",
            ((now - timedelta(days=days_ago)).isoformat(), state),
        )
    return con


def _counts_only_egress_silent():
    counts = {t: 4 for t in _const().MEMORY_WRITER_BACKED_EPISODE_TYPES}
    counts[_EGRESS] = 0
    return counts


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [
    [(10, "away")],                                   # away since before the window
    [(10, "away"), (3, "vacation")],                  # away -> vacation inside it
    [(9, "vacation")],
])
async def test_bl4_house_absent_whole_window_suppresses_egress_page(rows, real_schema_db):
    run = _bind_method()
    db = _FakeURADatabase(_counts_only_egress_silent(), house=_house(real_schema_db, rows))
    stats = await run(db, cadence_days=7, triggered_by="nightly")
    assert stats["zero_row_types"] == []
    assert stats["absence_suppressed_types"] == [_EGRESS]
    assert db.anomaly_events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [
    [],                                               # no proof at all
    [(10, "home_day")],                               # home the whole week
    [(10, "away"), (2, "home_evening")],              # came home inside the window
    [(6, "away")],                                    # no row BEFORE the window
    [(10, "home_day"), (6.9, "away")],                # left after the window began
])
async def test_bl4_house_not_proven_absent_pages_egress(rows, real_schema_db):
    run = _bind_method()
    db = _FakeURADatabase(_counts_only_egress_silent(), house=_house(real_schema_db, rows))
    stats = await run(db, cadence_days=7, triggered_by="nightly")
    assert stats["zero_row_types"] == [_EGRESS]
    assert stats["absence_suppressed_types"] == []
    assert len(db.anomaly_events) == 1


@pytest.mark.asyncio
async def test_bl4_absence_never_suppresses_other_writers(real_schema_db):
    """Only crossing-only types are exempt: house_state_transition silent in an
    away week still pages."""
    run = _bind_method()
    counts = _counts_only_egress_silent()
    counts["house_state_transition"] = 0
    db = _FakeURADatabase(counts, house=_house(real_schema_db, [(10, "away")]))
    stats = await run(db, cadence_days=7, triggered_by="nightly")
    assert stats["zero_row_types"] == ["house_state_transition"]
    assert stats["absence_suppressed_types"] == [_EGRESS]

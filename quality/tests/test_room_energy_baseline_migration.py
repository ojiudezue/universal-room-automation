"""Tests for D1 migration: room_energy_baselines schema-version reset.

Verifies that on first boot of code with a newer
ENERGY_BASELINE_SCHEMA_VERSION:
- existing rows are reset exactly once
- the sentinel version row is written
- a subsequent boot does NOT re-reset
- the negative-drift sanity guard branch is reachable (sibling D1 fix
  to coordinator.py:1912 SANE_MAX_DELTA_KWH)

Tests drive production source — they call the DAO directly and grep the
coordinator for the abs(raw_delta) negative-delta guard rather than
re-implementing the migration logic.
"""
import importlib.util
import os
import sys
import types
from datetime import datetime

import pytest


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Minimal HA mocks so the REAL production database module is importable.
# Suite convention (see test_data_pipeline.py): install with
# sys.modules.setdefault — cooperative across test files, never REPLACES a
# module another file already owns. (A prior version of this file ASSIGNED
# over custom_components...const and poisoned ~107 unrelated tests.)
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


sys.modules.setdefault("homeassistant", _mock_module("homeassistant"))
sys.modules.setdefault(
    "homeassistant.core",
    _mock_module("homeassistant.core", HomeAssistant=type("HomeAssistant", (), {})),
)
sys.modules.setdefault("homeassistant.util", _mock_module("homeassistant.util"))
sys.modules.setdefault(
    "homeassistant.util.dt",
    _mock_module(
        "homeassistant.util.dt",
        utcnow=lambda: datetime.utcnow(),
        now=lambda: datetime.now(),
        as_local=lambda dt: dt,
    ),
)

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_REPO, "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [os.path.join(_REPO, "custom_components", "universal_room_automation")]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load_const():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "const.py",
    )
    spec = importlib.util.spec_from_file_location("_ura_const_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_const = _load_const()


# ---------------------------------------------------------------------------
# Constants present + plausible
# ---------------------------------------------------------------------------

def test_schema_version_constant_defined():
    assert hasattr(_const, "ENERGY_BASELINE_SCHEMA_VERSION")
    assert isinstance(_const.ENERGY_BASELINE_SCHEMA_VERSION, int)
    assert _const.ENERGY_BASELINE_SCHEMA_VERSION >= 2


def test_schema_version_sentinel_keys_defined():
    assert _const.ENERGY_BASELINE_VERSION_ROOM_ID == "__schema_version__"
    assert isinstance(_const.ENERGY_BASELINE_VERSION_SENSOR_ID, str)
    assert _const.ENERGY_BASELINE_VERSION_SENSOR_ID


# ---------------------------------------------------------------------------
# DAO methods exist on the production database class
# ---------------------------------------------------------------------------

def test_dao_methods_present():
    """The 3 new DAO methods must exist on URADatabase (or equivalent)."""
    db_path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "database.py",
    )
    with open(db_path, encoding="utf-8") as fh:
        src = fh.read()
    assert "async def get_energy_baseline_schema_version" in src
    assert "async def set_energy_baseline_schema_version" in src
    assert "async def reset_all_room_energy_baselines" in src


def test_reset_excludes_sentinel_row():
    """The reset DAO must NOT delete the schema-version sentinel row.

    Without this, every boot would re-fire the migration.
    """
    db_path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "database.py",
    )
    with open(db_path, encoding="utf-8") as fh:
        src = fh.read()
    # The DELETE must guard against the sentinel row.
    # Find the reset method body.
    start = src.find("async def reset_all_room_energy_baselines")
    assert start > 0
    end = src.find("\n    async def ", start + 1)
    body = src[start:end if end > 0 else len(src)]
    assert "WHERE NOT" in body, "reset DAO must exclude sentinel row"
    assert "ENERGY_BASELINE_VERSION_ROOM_ID" in body


# ---------------------------------------------------------------------------
# Coordinator wires the migration on first refresh
# ---------------------------------------------------------------------------

def test_coordinator_runs_migration_once():
    coord_path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "coordinator.py",
    )
    with open(coord_path, encoding="utf-8") as fh:
        src = fh.read()
    assert "_energy_baselines_schema_checked" in src, (
        "coordinator must track that the schema check has run"
    )
    # Set flag BEFORE the await, mirrors the _energy_baselines_loaded race-fix
    # pattern at coordinator.py:1771 (Tier 1 review HIGH #1 idiom).
    idx = src.find("if not self._energy_baselines_schema_checked")
    assert idx > 0
    next_set = src.find("self._energy_baselines_schema_checked = True", idx)
    next_await = src.find("await", idx)
    assert next_set > 0 and next_await > 0 and next_set < next_await, (
        "schema_checked must be set TRUE before the first await to "
        "prevent concurrent re-entry double-migration"
    )


def test_coordinator_calls_dao_methods():
    """Fix-up pass A-M1: coordinator must use the atomic
    ``migrate_energy_baselines_if_needed`` DAO, not per-coordinator
    check-then-reset (which races and wipes earlier rooms' baselines).
    """
    coord_path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "coordinator.py",
    )
    with open(coord_path, encoding="utf-8") as fh:
        src = fh.read()
    assert "migrate_energy_baselines_if_needed" in src, (
        "coordinator must use the atomic single-write migration DAO"
    )


# ---------------------------------------------------------------------------
# Behavioral test: migration runs once, cleanup spares the sentinel
# (fix-up pass C-M3: replace source-grep with real sqlite drive-through)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migration_dao_is_atomic_and_runs_once(tmp_path):
    """Drive ``migrate_energy_baselines_if_needed`` against a real sqlite file.

    Verifies:
    - First call resets non-sentinel rows + writes sentinel (ran=True).
    - Second call no-ops (ran=False) — proves the sentinel survives.
    - The sentinel row is NOT counted in the reset rowcount when absent
      pre-migration (we only count user rows).
    """
    import aiosqlite

    db_path = tmp_path / "ura_test.db"

    # Bootstrap the schema + seed legacy rows directly via aiosqlite.
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS room_energy_baselines (
                room_id TEXT NOT NULL,
                sensor_id TEXT NOT NULL,
                baseline_value REAL NOT NULL,
                baseline_set_at TEXT NOT NULL,
                needs_reset INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (room_id, sensor_id)
            )"""
        )
        await db.executemany(
            """INSERT INTO room_energy_baselines
               (room_id, sensor_id, baseline_value, baseline_set_at, needs_reset)
               VALUES (?, ?, ?, ?, ?)""",
            [
                ("room_a", "sensor.a", 12.3, "2026-06-08T00:00:00+00:00", 0),
                ("room_b", "sensor.b", 4.5, "2026-06-08T00:00:00+00:00", 0),
            ],
        )
        await db.commit()

    # Minimal stand-in implementing just the queue context managers + DAO.
    class _MiniDB:
        def __init__(self, p):
            self._p = p

        def _db(self):
            return self._cm()

        def _db_read(self):
            return self._cm()

        def _cm(_self):
            class _Ctx:
                async def __aenter__(self_inner):
                    self_inner._conn = await aiosqlite.connect(_self._p)
                    return self_inner._conn

                async def __aexit__(self_inner, *exc):
                    await self_inner._conn.close()
            return _Ctx()

    # Drive the REAL production DAO (HA is installed in the test env —
    # same import pattern as test_data_pipeline.py:93). The unbound method
    # only needs ``self._db()``, which _MiniDB provides. No source-exec,
    # no sys.modules stubbing (a prior version of this test replaced the
    # real const module in sys.modules and poisoned ~107 unrelated tests).
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    migrate = UniversalRoomDatabase.migrate_energy_baselines_if_needed

    mini = _MiniDB(db_path)
    ran1, deleted1 = await migrate(mini, target_version=2)
    assert ran1 is True
    assert deleted1 == 2  # both legacy rows wiped

    # Sentinel row written?
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT baseline_value FROM room_energy_baselines WHERE room_id = ?",
            ("__schema_version__",),
        )
        row = await cur.fetchone()
        assert row is not None
        assert int(row[0]) == 2

    # Second call must NO-OP (the sentinel is now at target).
    ran2, deleted2 = await migrate(mini, target_version=2)
    assert ran2 is False
    assert deleted2 == 0


@pytest.mark.asyncio
async def test_cleanup_spares_sentinel_row(tmp_path):
    """Fix-up pass A-H1: cleanup must NOT delete the schema-version sentinel.

    Without this, the sentinel ages out after 90 days and every boot
    re-fires the migration.
    """
    import aiosqlite

    db_path = tmp_path / "ura_cleanup.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS room_energy_baselines (
                room_id TEXT NOT NULL,
                sensor_id TEXT NOT NULL,
                baseline_value REAL NOT NULL,
                baseline_set_at TEXT NOT NULL,
                needs_reset INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (room_id, sensor_id)
            )"""
        )
        # Old sentinel + old user row, both past the cleanup cutoff.
        await db.executemany(
            """INSERT INTO room_energy_baselines
               (room_id, sensor_id, baseline_value, baseline_set_at, needs_reset)
               VALUES (?, ?, ?, ?, ?)""",
            [
                ("__schema_version__", "energy_baseline_version",
                 2.0, "2020-01-01T00:00:00+00:00", 0),
                ("room_old", "sensor.x", 1.0, "2020-01-01T00:00:00+00:00", 0),
            ],
        )
        await db.commit()

    # Drive the REAL production cleanup DAO (not a hand-copied SQL clone —
    # fixture authority: if the production WHERE clause regresses, this
    # test must fail).
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    cleanup = UniversalRoomDatabase.cleanup_room_energy_baselines

    class _MiniDB:
        def __init__(self, p):
            self._p = p

        def _db(_self):
            class _Ctx:
                async def __aenter__(self_inner):
                    self_inner._conn = await aiosqlite.connect(_self._p)
                    return self_inner._conn

                async def __aexit__(self_inner, *exc):
                    await self_inner._conn.close()
            return _Ctx()

    deleted = await cleanup(_MiniDB(db_path), retention_days=90)
    assert deleted == 1, "exactly the stale user row is deleted"
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT room_id FROM room_energy_baselines ORDER BY room_id"
        )
        rows = await cur.fetchall()
    assert [r[0] for r in rows] == ["__schema_version__"], (
        "cleanup must spare the sentinel"
    )


# ---------------------------------------------------------------------------
# Sanity guard now catches negative drift (D1 hazard)
# ---------------------------------------------------------------------------

def test_sanity_guard_catches_negative_drift():
    """coordinator.py:1912 region now uses abs(raw_delta) > SANE_MAX_DELTA_KWH."""
    coord_path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "coordinator.py",
    )
    with open(coord_path, encoding="utf-8") as fh:
        src = fh.read()
    # Old single-sided guard `raw_delta > SANE_MAX_DELTA_KWH` MUST be gone,
    # replaced by abs(...) two-sided form.
    assert "abs(raw_delta) > SANE_MAX_DELTA_KWH" in src, (
        "negative-drift hazard from D1 baseline-unit mismatch must be guarded"
    )

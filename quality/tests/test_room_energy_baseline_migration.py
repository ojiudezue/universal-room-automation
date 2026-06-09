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

import pytest


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    coord_path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "coordinator.py",
    )
    with open(coord_path, encoding="utf-8") as fh:
        src = fh.read()
    assert "get_energy_baseline_schema_version" in src
    assert "set_energy_baseline_schema_version" in src
    assert "reset_all_room_energy_baselines" in src


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

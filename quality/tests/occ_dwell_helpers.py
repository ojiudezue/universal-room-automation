"""Shared helpers for the occupancy dwell-model tests (no fixtures, no
sys.modules surgery). The real ``UniversalRoomDatabase.initialize()`` builds
the schema, so every table comes from database.py's own DDL."""
from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock


def make_real_db(tmp_path):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )

    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)
    hass.is_stopping = False
    hass.data = {}

    def _schedule(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule
    hass.async_create_task = _schedule
    return UniversalRoomDatabase(hass)


def seed(db, sql: str, rows: list[tuple]) -> None:
    """Fixture seeding straight into the production-built table."""
    conn = sqlite3.connect(db.db_file)
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def fetch(db, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db.db_file)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def is_set_aside(name: str, mod) -> bool:
    """Same rule as test_ec_role_defaults_rev5: every URA module and every
    non-real HA stub is set aside, so the block imports the REAL package
    (files collected earlier leave partial stubs in sys.modules)."""
    import types

    if name == "custom_components" or name.startswith("custom_components."):
        return True
    if name == "homeassistant" or name.startswith("homeassistant."):
        return not isinstance(mod, types.ModuleType) or mod.__spec__ is None
    return False


RELOAD_HA_MODULES = (
    "homeassistant.helpers.update_coordinator",
)


@contextmanager
def real_package():
    """Module-scoped real-package scope (``_d7_isolation``); restores
    sys.modules exactly on exit."""
    import importlib
    import sys

    from _d7_isolation import real_package_scope

    with real_package_scope(is_set_aside):
        # Some files collected earlier overwrite attributes of REAL HA
        # modules (e.g. ``update_coordinator.DataUpdateCoordinator =
        # MagicMock`` or a bare class). Re-execute those modules in place;
        # real_package_scope(attrs=True) puts every attribute back on exit,
        # so other files see exactly what they had.
        for name in RELOAD_HA_MODULES:
            mod = sys.modules.get(name)
            if mod is not None and getattr(mod, "__spec__", None) is not None:
                importlib.reload(mod)
        yield


@contextmanager
def default_tz(name: str):
    """Set HA's default time zone for the block, then restore it."""
    import importlib

    dt_util = importlib.import_module("homeassistant.util.dt")
    prev = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(dt_util.get_time_zone(name))
    try:
        yield dt_util.DEFAULT_TIME_ZONE
    finally:
        dt_util.set_default_time_zone(prev)

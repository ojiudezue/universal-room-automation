"""Shared helpers for the occupancy dwell-model tests (no fixtures, no
sys.modules surgery). The real ``UniversalRoomDatabase.initialize()`` builds
the schema, so every table comes from database.py's own DDL."""
from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util


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


@contextmanager
def default_tz(name: str):
    """Set HA's default time zone for the block, then restore it."""
    prev = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(dt_util.get_time_zone(name))
    try:
        yield dt_util.DEFAULT_TIME_ZONE
    finally:
        dt_util.set_default_time_zone(prev)

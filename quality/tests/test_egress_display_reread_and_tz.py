"""BLE mop-up (2026-09-05) — two low-severity fixes from v5.96.1 reviews.

- EGRESS-EXIT-DISPLAY-REREAD-1: after a successful exit-identity backfill
  in camera_census, SIGNAL_EGRESS_EXIT_BACKFILLED fires and
  PersonsExitedTodaySensor re-reads its display list from DB so the
  backfilled person_id appears without waiting for a restart.

- EGRESS-SENSOR-READER-TZ-OVERCOUNT-1: the "today" window used to restore
  the count/list from DB must be computed in the column's convention
  (naive-UTC), not local-midnight. Otherwise UTC-5 opens the window at
  19:00 the prior day and over-counts.
"""

from __future__ import annotations

import asyncio as _asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

import sys as _sys
import types as _types

if "homeassistant.helpers.restore_state" not in _sys.modules:
    _rs = _types.ModuleType("homeassistant.helpers.restore_state")
    class _RestoreEntity:  # noqa: D401
        """Stub RestoreEntity."""
    _rs.RestoreEntity = _RestoreEntity
    _sys.modules["homeassistant.helpers.restore_state"] = _rs

import homeassistant.helpers.update_coordinator as _uc  # type: ignore
if not hasattr(_uc, "CoordinatorEntity"):
    class _CoordinatorEntityMeta(type):
        def __getitem__(cls, item):
            return cls
    class _CoordinatorEntity(metaclass=_CoordinatorEntityMeta):
        def __init__(self, *a, **kw):
            pass
    _uc.CoordinatorEntity = _CoordinatorEntity
if not hasattr(_uc, "DataUpdateCoordinator"):
    _uc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
if not hasattr(_uc, "UpdateFailed"):
    _uc.UpdateFailed = Exception

if "homeassistant.helpers.area_registry" not in _sys.modules:
    _mod = _types.ModuleType("homeassistant.helpers.area_registry")
    _mod.async_get = MagicMock()
    _sys.modules["homeassistant.helpers.area_registry"] = _mod
if "homeassistant.helpers.event" not in _sys.modules:
    _ev = _types.ModuleType("homeassistant.helpers.event")
    _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
    _ev.async_call_later = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_change = lambda *a, **kw: (lambda: None)
    _sys.modules["homeassistant.helpers.event"] = _ev

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import sensor as sensor_mod
from custom_components.universal_room_automation.sensor import (
    PersonsExitedTodaySensor,
)
from custom_components.universal_room_automation.domain_coordinators.signals import (
    SIGNAL_EGRESS_EXIT_BACKFILLED,
)


UTC = timezone.utc


def _ensure_loop():
    try:
        _asyncio.set_event_loop(_asyncio.new_event_loop())
    except Exception:  # noqa: BLE001
        pass


def _run(coro):
    loop = _asyncio.get_event_loop()
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Stub DB shared across the two sensor tests
# ---------------------------------------------------------------------------

class _StubDatabase:
    def __init__(self):
        self.rows: list[dict] = []
        self.since_calls: list[str] = []

    def add(self, ts_naive_utc_iso: str, direction: str, person_id, cam="front_door"):
        self.rows.append({
            "person_id": person_id,
            "timestamp": ts_naive_utc_iso,
            "direction": direction,
            "egress_camera": cam,
        })

    async def get_entry_exit_events_since(self, since, direction: str):
        since_str = since.isoformat() if hasattr(since, "isoformat") else str(since)
        self.since_calls.append(since_str)
        return [
            {"person_id": r["person_id"], "timestamp": r["timestamp"], "egress_camera": r["egress_camera"]}
            for r in self.rows
            if r["direction"] == direction and r["timestamp"] >= since_str
        ]


def _make_exit_sensor(hass, db):
    """Skip __init__ (AggregationEntity is heavy) — just wire attrs the
    two methods under test read."""
    s = object.__new__(PersonsExitedTodaySensor)
    s.hass = hass
    s._count = 0
    s._entries = []
    s._last_reset = None
    s._restoring = False
    # write_ha_state is a no-op in this harness
    s.async_write_ha_state = lambda: None
    # async_on_remove is provided by HA Entity base; not present on our
    # object.__new__ stub — no-op accept.
    s.async_on_remove = lambda unsub: None
    return s


# ---------------------------------------------------------------------------
# T1 — Fix 2: TZ boundary. A row timestamped BEFORE local midnight (in the
# column's naive-UTC convention) MUST be excluded. Under the buggy
# local-midnight bound at UTC-5, both rows would be included ("today"
# would start at 19:00 the prior day).
# ---------------------------------------------------------------------------

def test_persons_exited_today_uses_naive_utc_boundary():
    _ensure_loop()
    hass = make_hass()
    db = _StubDatabase()
    hass.data[ura_const.DOMAIN] = {"database": db}

    # Local now = 2026-09-05 10:00 America/Chicago (UTC-5).
    # Local midnight = 2026-09-05 00:00 CDT = 2026-09-05 05:00 UTC.
    # In the DB's naive-UTC column convention, today_start = "2026-09-05T05:00:00".
    fake_local_now = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    expected_since_naive_utc = "2026-09-05T05:00:00"

    # A row from 2026-09-05 03:00 UTC-naive (which IS 2026-09-04 22:00 local,
    # i.e. YESTERDAY local) — MUST be excluded.
    db.add("2026-09-05T03:00:00", "exit", "person.oji_udezue")
    # A row from 2026-09-05 06:00 UTC-naive (2026-09-05 01:00 local today) — MUST be included.
    db.add("2026-09-05T06:00:00", "exit", "person.ezinne_udezue")

    s = _make_exit_sensor(hass, db)

    # Patch dt_util.now in the sensor module to our fixed local now.
    orig_now = sensor_mod.dt_util.now
    sensor_mod.dt_util.now = lambda: fake_local_now
    try:
        _run(s._async_reread_exits())
    finally:
        sensor_mod.dt_util.now = orig_now

    # The `since` handed to the DAO MUST be naive-UTC local-midnight,
    # NOT the buggy local-midnight-in-local-tz.
    assert db.since_calls, "DAO not called"
    assert db.since_calls[-1] == expected_since_naive_utc, (
        f"boundary handed to DAO was {db.since_calls[-1]!r}, "
        f"expected {expected_since_naive_utc!r}. RED means the old "
        f"local-midnight bound is back."
    )
    # And the resulting entries reflect only the post-midnight-UTC-naive row.
    persons = [e["person_id"] for e in s._entries]
    assert persons == ["person.ezinne_udezue"], (
        f"expected only the after-boundary row; got {persons}. Old bug "
        f"would include the pre-boundary row too."
    )


# ---------------------------------------------------------------------------
# T2 — Fix 1: the re-read path itself updates _entries from DB when the
# backfilled row becomes named. RED if the re-read method / handler is
# removed (attr will be missing).
# ---------------------------------------------------------------------------

def test_persons_exited_today_reread_reflects_backfilled_person_id():
    _ensure_loop()
    hass = make_hass()
    db = _StubDatabase()
    hass.data[ura_const.DOMAIN] = {"database": db}

    fake_local_now = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    # A single exit AFTER the naive-UTC boundary. Start unnamed
    # (the bus-time state), then simulate the backfill by mutating the row.
    db.add("2026-09-05T06:00:00", "exit", None)

    s = _make_exit_sensor(hass, db)
    # Simulate the bus-fire state: _entries already recorded as "unidentified".
    s._entries = [{
        "person_id": "unidentified",
        "time": "2026-09-05T06:00:00",
        "egress_camera": "front_door",
    }]

    # Backfill happens — the DB row gets a name.
    db.rows[0]["person_id"] = "person.oji_udezue"

    # The re-read method MUST exist (fix 1) and MUST refresh from DB.
    assert hasattr(s, "_async_reread_exits"), (
        "PersonsExitedTodaySensor missing _async_reread_exits — the "
        "backfill-display-reread wiring is gone."
    )

    orig_now = sensor_mod.dt_util.now
    sensor_mod.dt_util.now = lambda: fake_local_now
    try:
        _run(s._async_reread_exits())
    finally:
        sensor_mod.dt_util.now = orig_now

    persons = [e["person_id"] for e in s._entries]
    assert persons == ["person.oji_udezue"], (
        f"expected the backfilled name to appear in _entries; got {persons}"
    )


# ---------------------------------------------------------------------------
# T3 — Fix 1 (producer side): after a successful backfill in camera_census,
# SIGNAL_EGRESS_EXIT_BACKFILLED fires with the row_id + person_id.
# ---------------------------------------------------------------------------

class _StubCameraManager:
    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


class _BackfillOnlyDB:
    """Just enough surface to drive the backfill call path."""

    def __init__(self):
        self._row = {"id": 7, "person_id": None}

    async def find_unnamed_exit_crossings(self, t_lo_iso, t_hi_iso):
        return [(self._row["id"], "2026-09-05T06:00:00", "front_door")]

    async def backfill_entry_exit_person_id(self, row_id, person_id, confidence):
        if self._row["id"] == row_id and self._row["person_id"] is None:
            self._row["person_id"] = person_id
            return True
        return False


def test_backfill_success_dispatches_signal():
    from custom_components.universal_room_automation.camera_census import PersonCensus

    _ensure_loop()
    hass = make_hass()

    # Record dispatcher sends
    sent: list[tuple] = []

    from homeassistant.helpers import dispatcher as _hd_mod
    orig_send = getattr(_hd_mod, "async_dispatcher_send", None)

    def _capture(_hass, signal, *args):
        sent.append((signal, args))

    _hd_mod.async_dispatcher_send = _capture

    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        "tracked_persons": ["person.oji_udezue"],
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: True,
    }
    hass.config_entries.async_entries.return_value = [entry]
    hass.states.get = lambda eid: None

    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    db = _BackfillOnlyDB()
    existing = hass.data.get(ura_const.DOMAIN, {}) if isinstance(hass.data, dict) else {}
    existing["database"] = db
    hass.data[ura_const.DOMAIN] = existing

    # Drive the backfill directly. Args match the production signature.
    try:
        # Direct-call path: tracker_id=None skips wait+flap gates.
        _run(census._backfill_exit_identity(
            "person.oji_udezue",
            datetime(2026, 9, 5, 6, 10, 0),
            None,
        ))
    finally:
        if orig_send is not None:
            _hd_mod.async_dispatcher_send = orig_send

    matches = [s for s in sent if s[0] == SIGNAL_EGRESS_EXIT_BACKFILLED]
    assert matches, (
        f"SIGNAL_EGRESS_EXIT_BACKFILLED not dispatched; sent={sent}. "
        f"RED means the display-reread dispatcher call is gone."
    )
    payload = matches[-1][1][0]
    assert payload == {"row_id": 7, "person_id": "person.oji_udezue"}, (
        f"payload mismatch: {payload}"
    )


# ---------------------------------------------------------------------------
# T4 — Fix 3 (per-site TZ anchor): PersonsExitedTodaySensor's INITIAL-RESTORE
# path (async_added_to_hass) must hand the DAO a naive-UTC bound. RED if that
# site's `.astimezone(timezone.utc)` is reverted to local-naive midnight.
# ---------------------------------------------------------------------------

def _ensure_event_helpers():
    """The `from homeassistant.helpers.event import async_track_time_change`
    inside async_added_to_hass runs at call time; ensure the harness stub
    exposes it (another test may have swapped in a different stub)."""
    import homeassistant.helpers.event as _ev
    if not hasattr(_ev, "async_track_time_change"):
        _ev.async_track_time_change = lambda *a, **kw: (lambda: None)
    if not hasattr(_ev, "async_track_state_change_event"):
        _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)


def _install_agg_noop():
    from custom_components.universal_room_automation import aggregation as _agg
    _orig = _agg.AggregationEntity.async_added_to_hass

    async def _noop(self):
        return None
    _agg.AggregationEntity.async_added_to_hass = _noop
    return _agg, _orig


def _restore_agg(_agg, _orig):
    _agg.AggregationEntity.async_added_to_hass = _orig


def test_persons_exited_today_initial_restore_uses_naive_utc_boundary():
    _ensure_loop()
    hass = make_hass()
    db = _StubDatabase()
    hass.data[ura_const.DOMAIN] = {"database": db}

    fake_local_now = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    expected_since_naive_utc = "2026-09-05T05:00:00"

    # Pre-boundary row (yesterday LOCAL, before naive-UTC midnight cut) — MUST be excluded.
    db.add("2026-09-05T03:00:00", "exit", "person.a")
    # Post-boundary row — MUST be included.
    db.add("2026-09-05T06:00:00", "exit", "person.b")

    s = _make_exit_sensor(hass, db)

    _ensure_event_helpers()
    _agg, _orig = _install_agg_noop()
    orig_now = sensor_mod.dt_util.now
    sensor_mod.dt_util.now = lambda: fake_local_now
    try:
        _run(s.async_added_to_hass())
    finally:
        sensor_mod.dt_util.now = orig_now
        _restore_agg(_agg, _orig)

    assert db.since_calls, "DAO not called on initial restore"
    assert db.since_calls[-1] == expected_since_naive_utc, (
        f"initial-restore boundary was {db.since_calls[-1]!r}, "
        f"expected {expected_since_naive_utc!r}. RED means the "
        f"PersonsExitedToday initial-restore site's naive-UTC conversion is gone."
    )
    assert s._count == 1, (
        f"expected count=1 (only post-boundary row), got {s._count}. "
        f"Old bug would count both rows."
    )
    # Live-shape normalization: dict keys must be {person_id, time, egress_camera}
    # and unnamed rows default to "unidentified" — assert the shape here.
    assert s._entries and set(s._entries[0].keys()) == {"person_id", "time", "egress_camera"}, (
        f"restore did not normalize to live shape; got keys "
        f"{set(s._entries[0].keys()) if s._entries else None}"
    )


def test_persons_entered_today_initial_restore_uses_naive_utc_boundary():
    from custom_components.universal_room_automation.sensor import (
        PersonsEnteredTodaySensor,
    )

    _ensure_loop()
    hass = make_hass()
    db = _StubDatabase()
    hass.data[ura_const.DOMAIN] = {"database": db}

    fake_local_now = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    expected_since_naive_utc = "2026-09-05T05:00:00"

    db.add("2026-09-05T03:00:00", "entry", "person.a")  # pre-boundary
    db.add("2026-09-05T06:00:00", "entry", None)         # post-boundary, unnamed

    s = object.__new__(PersonsEnteredTodaySensor)
    s.hass = hass
    s._count = 0
    s._entries = []
    s._last_reset = None
    s._restoring = False
    s._egress_identities_stamped = 0
    s.async_write_ha_state = lambda: None
    # async_on_remove is provided by HA Entity base; harness hass doesn't
    # inject one, so provide a permissive stub that just calls the unsub
    # provider so the listener registration path executes.
    s.async_on_remove = lambda unsub: None

    _ensure_event_helpers()
    _agg, _orig = _install_agg_noop()
    orig_now = sensor_mod.dt_util.now
    sensor_mod.dt_util.now = lambda: fake_local_now
    try:
        _run(s.async_added_to_hass())
    finally:
        sensor_mod.dt_util.now = orig_now
        _restore_agg(_agg, _orig)

    assert db.since_calls, "DAO not called on initial restore"
    assert db.since_calls[-1] == expected_since_naive_utc, (
        f"initial-restore boundary was {db.since_calls[-1]!r}, "
        f"expected {expected_since_naive_utc!r}. RED means the "
        f"PersonsEnteredToday initial-restore site's naive-UTC conversion is gone."
    )
    assert s._count == 1, (
        f"expected count=1 (only post-boundary row); got {s._count}"
    )
    # Live-shape + unnamed → "unidentified".
    assert s._entries[0]["person_id"] == "unidentified", (
        f"unnamed DB row must normalize to 'unidentified'; got "
        f"{s._entries[0]['person_id']!r}"
    )
    assert set(s._entries[0].keys()) == {"person_id", "time", "egress_camera"}

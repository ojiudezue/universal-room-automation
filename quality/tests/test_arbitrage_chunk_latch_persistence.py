"""v5.17.1 D2 — arbitrage chunk-latch restart persistence.

Exercises `EnergyCoordinator._restore_wv_state`'s new
`arbitrage_chunk_latch` restore block. Uses the same fake-DB /
stub-coordinator idiom as `test_energy_write_verification.py`.

Behavior contract:
  - completed=True + boundary AHEAD + matching live boundary → restore
    `_arbitrage_chunk_completed=True` (first tick HOLDs at target).
  - completed=True + boundary PASSED → dropped (stale).
  - boundary mismatch (>1h from live) → dropped.
  - completed=False → dropped.
  - fresh RAM latch already True → no clobber.

Executed mutation (c) from Tier-3 plan: break the staleness check
(remove `parsed_bnd <= now_utc` gate) → the "boundary passed" test
turns RED. Verified by inspection in the fix report.
"""
from __future__ import annotations

import importlib
import json as _json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# Reuse the mock-homeassistant bootstrap from the sibling arbitrage test.
# (setdefault-based; safe on shared session.)
from test_arbitrage_completed_chunk_hold_precedence import (  # noqa: F401
    _mock_module,
)

# Patch in richer dt utilities the latch restore needs (parse_datetime, UTC).
# The sibling test's setdefault-based bootstrap only stubs `utcnow`/`now`/
# `as_local`; without `parse_datetime` and `UTC` the latch restore's
# `try/except Exception` swallows all restores and every D2 assertion
# spuriously "passes" by no-op. Force real implementations here.
_dt_mod = sys.modules["homeassistant.util.dt"]
from datetime import timezone as _tz_module
from datetime import datetime as _dt


def _utcnow():
    return _dt.now(_tz_module.utc)


def _parse_datetime(s):
    if not s:
        return None
    try:
        # datetime.fromisoformat handles "+00:00" suffixes on 3.11+; for 3.9
        # we normalize the trailing "Z".
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return _dt.fromisoformat(s)
    except (ValueError, TypeError):
        return None


_dt_mod.utcnow = _utcnow
_dt_mod.now = _utcnow
_dt_mod.parse_datetime = _parse_datetime
_dt_mod.UTC = _tz_module.utc


class _FakeDB:
    def __init__(self, payloads):
        self._payloads = payloads
        self.calls = []

    async def restore_energy_state_with_age(self, key, max_age_hours):
        self.calls.append((key, max_age_hours))
        entry = self._payloads.get(key)
        if entry is None:
            return None
        json_str, age_h = entry
        if age_h > max_age_hours:
            return None
        return json_str


class _FakeBatteryForLatch:
    def __init__(self, live_boundary_dt=None):
        # WV fields (helper still runs its wv restore block against these)
        self._last_reserve_level = None
        self._last_reserve_level_at = None
        self._last_charge_from_grid_command = None
        self._last_charge_from_grid_command_at = None
        self._last_storage_mode_command = None
        self._last_storage_mode_command_at = None
        # Latch fields
        self._arbitrage_chunk_completed = False
        self._arbitrage_active = False
        self._live_boundary_dt = live_boundary_dt

    def _attain_target_boundary(self, now, tou_period):
        if self._live_boundary_dt is None:
            return (None, None, None)
        delta = (self._live_boundary_dt - now).total_seconds()
        return (self._live_boundary_dt, "mid_peak", int(delta // 60))


def _make_coord(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )

    class _Stub:
        pass

    stub = _Stub()
    stub.hass = hass
    stub._restore_wv_state = EnergyCoordinator._restore_wv_state.__get__(stub, _Stub)
    return stub


@pytest.fixture
def hass():
    return MagicMock()


@pytest.mark.asyncio
async def test_d2_restore_fresh_latch_within_boundary(hass):
    """completed=True + boundary AHEAD + matching live → restored."""
    from homeassistant.util import dt as dt_util
    now_utc = dt_util.utcnow()
    boundary = now_utc + timedelta(hours=4)
    payload = _json.dumps({
        "completed": True, "boundary_iso": boundary.isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 0.1)})
    battery = _FakeBatteryForLatch(live_boundary_dt=boundary)
    stub = _make_coord(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is True
    assert battery._arbitrage_active is True


@pytest.mark.asyncio
async def test_d2_drop_when_boundary_passed(hass):
    """completed=True but persisted boundary is in the PAST → dropped
    (staleness). Mutation (c): removing the past-boundary check makes
    THIS test go RED (assertion below flips)."""
    from homeassistant.util import dt as dt_util
    now_utc = dt_util.utcnow()
    boundary = now_utc - timedelta(hours=2)  # passed
    payload = _json.dumps({
        "completed": True, "boundary_iso": boundary.isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 0.1)})
    # Live boundary matches the persisted one exactly (delta=0, so the
    # mismatch guard cannot catch this) — the boundary-PASSED check is
    # the only line of defense. Mutation (c) neuters that check, and
    # this test then turns RED (latch would be resurrected post-boundary).
    battery = _FakeBatteryForLatch(live_boundary_dt=boundary)
    stub = _make_coord(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is False


@pytest.mark.asyncio
async def test_d2_drop_when_live_boundary_mismatch(hass):
    """Persisted boundary vs live boundary differ > 1h → dropped."""
    from homeassistant.util import dt as dt_util
    now_utc = dt_util.utcnow()
    persisted = now_utc + timedelta(hours=4)
    live = now_utc + timedelta(hours=10)  # different chunk entirely
    payload = _json.dumps({
        "completed": True, "boundary_iso": persisted.isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 0.1)})
    battery = _FakeBatteryForLatch(live_boundary_dt=live)
    stub = _make_coord(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is False


@pytest.mark.asyncio
async def test_d2_drop_when_completed_false(hass):
    """completed=False → nothing to restore."""
    from homeassistant.util import dt as dt_util
    now_utc = dt_util.utcnow()
    payload = _json.dumps({
        "completed": False,
        "boundary_iso": (now_utc + timedelta(hours=4)).isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 0.1)})
    battery = _FakeBatteryForLatch(
        live_boundary_dt=now_utc + timedelta(hours=4),
    )
    stub = _make_coord(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is False


@pytest.mark.asyncio
async def test_d2_no_clobber_when_ram_latch_true(hass):
    """Fresh live latch already True → restore must not clobber."""
    from homeassistant.util import dt as dt_util
    now_utc = dt_util.utcnow()
    boundary = now_utc + timedelta(hours=4)
    payload = _json.dumps({
        "completed": True, "boundary_iso": boundary.isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 0.1)})
    battery = _FakeBatteryForLatch(live_boundary_dt=boundary)
    battery._arbitrage_chunk_completed = True  # already set by live tick
    battery._arbitrage_active = False  # left alone by no-clobber path
    stub = _make_coord(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is True
    # No-clobber path did NOT flip _arbitrage_active.
    assert battery._arbitrage_active is False


@pytest.mark.asyncio
async def test_d2_stale_row_dropped_by_staleness_gate(hass):
    """Row older than max_age_hours → DAO returns None → nothing restored."""
    from homeassistant.util import dt as dt_util
    now_utc = dt_util.utcnow()
    payload = _json.dumps({
        "completed": True,
        "boundary_iso": (now_utc + timedelta(hours=4)).isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 11.0)})  # 11h stale
    battery = _FakeBatteryForLatch(
        live_boundary_dt=now_utc + timedelta(hours=4),
    )
    stub = _make_coord(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is False

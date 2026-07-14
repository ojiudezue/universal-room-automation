"""v5.17.1 part-3 seam anchors — EVSE-hold clamp, eager latch persist, tz-normalize.

Each test targets a specific line-range seam in energy.py from the part-1
fix-up. The test drives the production code path directly (isolated unit,
no full-coordinator bootstrap) and pairs 1:1 with an executed mutation
recorded in the fix report.

Seams:
  - Seam #3 EVSE-hold append clamp (energy.py:3045-3057)
  - Seam #4 Eager latch persist edge trigger (energy.py:3163-3179)
  - Seam #5 Restore tz-normalization for naive persisted boundary (energy.py:1440-1471)
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# Reuse the mock-homeassistant bootstrap from the sibling arbitrage test —
# it wires custom_components + energy_battery + energy_tou into sys.modules
# via setdefault, so importing it here is idempotent.
from test_arbitrage_completed_chunk_hold_precedence import (  # noqa: F401
    _mock_module,
)

# Patch in richer dt utilities that the tz-normalize seam needs.
_dt_mod = sys.modules["homeassistant.util.dt"]
from datetime import timezone as _tz_module
from datetime import datetime as _dt


def _utcnow():
    return _dt.now(_tz_module.utc)


def _parse_datetime(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return _dt.fromisoformat(s)
    except (ValueError, TypeError):
        return None


_dt_mod.utcnow = _utcnow
_dt_mod.now = _utcnow
_dt_mod.parse_datetime = _parse_datetime
_dt_mod.UTC = _tz_module.utc


# ---------------------------------------------------------------------------
# Seam #3 — EVSE-hold append clamp (energy.py:3045-3057)
# ---------------------------------------------------------------------------


class _FakeBattery:
    """Minimal battery stub for _apply_evse_battery_hold isolation."""

    def __init__(self, desired: int | None = 80):
        self._last_reserve_level_desired = desired
        self._last_reserve_level = None
        self._last_reserve_level_at = None

    def _get_entity(self, key, default, role=None):
        return default


class _CoordShell:
    """Shell that owns _apply_evse_battery_hold bound to a fake battery."""

    def __init__(self, evse_hold_soc: int, battery: _FakeBattery):
        self._evse_hold_soc = evse_hold_soc
        self._battery = battery


def test_seam3_evse_hold_append_clamps_up_to_strategy_desired():
    """Append-path clamp: hold_soc=45 + strategy_desired=80 → emits 80.

    Mutation: remove the clamp (append raw _evse_hold_soc). RED because
    the appended action carries 45, not 80.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    battery = _FakeBattery(desired=80)
    shell = _CoordShell(evse_hold_soc=45, battery=battery)
    # Bind the production method to the shell (no full-coordinator setup).
    apply = EnergyCoordinator._apply_evse_battery_hold.__get__(
        shell, _CoordShell,
    )
    # Decision has NO existing reserve action → append path fires.
    decision = {"reason": "test", "soc": 79, "actions": []}
    out = apply(decision)
    reserve_actions = [
        a for a in out["actions"]
        if a.get("service") == "number.set_value"
    ]
    assert len(reserve_actions) == 1
    emitted = reserve_actions[0]["data"]["value"]
    assert emitted == 80, (
        f"Seam #3: append path emitted {emitted!r} (expected 80 — clamped "
        f"up to strategy desired). Raw _evse_hold_soc leaked through."
    )


def test_seam3_evse_hold_append_no_desired_falls_back_to_hold_soc():
    """No _last_reserve_level_desired → append raw hold_soc (unchanged
    guardrail: only the clamp itself is exercised)."""
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    battery = _FakeBattery(desired=None)
    shell = _CoordShell(evse_hold_soc=45, battery=battery)
    apply = EnergyCoordinator._apply_evse_battery_hold.__get__(
        shell, _CoordShell,
    )
    decision = {"reason": "test", "soc": 79, "actions": []}
    out = apply(decision)
    reserve_actions = [
        a for a in out["actions"]
        if a.get("service") == "number.set_value"
    ]
    assert reserve_actions[0]["data"]["value"] == 45


# ---------------------------------------------------------------------------
# Seam #4 — Eager latch persist edge trigger (energy.py:3163-3179)
# ---------------------------------------------------------------------------


class _EagerShell:
    """Shell that reproduces the eager-persist edge-detect block."""

    def __init__(self, hass, battery, last_completed=False):
        self.hass = hass
        self._battery = battery
        self._last_arbitrage_chunk_completed = last_completed
        self._save_calls = 0

    async def _save_evse_state(self):
        self._save_calls += 1

    def run_edge_check(self):
        """Replicates the production block at energy.py:3163-3183 exactly.

        (Structurally reproduced here because pulling the full
        `_async_decision_cycle` requires the whole coordinator surface.
        Any drift here would show up in the code review — the block is
        3 lines and load-bearing.)
        """
        _completed_now = bool(
            getattr(self._battery, "_arbitrage_chunk_completed", False)
        )
        _last_completed = getattr(
            self, "_last_arbitrage_chunk_completed", False,
        )
        if _completed_now and not _last_completed:
            self.hass.async_create_task(self._save_evse_state())
        self._last_arbitrage_chunk_completed = _completed_now


def _load_energy_source():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", "energy.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _extract_eager_block(src: str) -> str:
    """Extract the eager-persist block (marked by the v5.17.1 B-MED-1 comment).

    Returns the executable body between the marker and its `except`. Then
    the body is exec'd with local `self` = shell.
    """
    marker = "eager-persist the arbitrage chunk"
    start = src.find(marker)
    assert start != -1, "eager-persist marker missing from energy.py"
    # Find the `try:` that follows the comment block.
    try_idx = src.find("try:", start)
    assert try_idx != -1
    # Extract until matching `except Exception`.
    except_idx = src.find("except Exception:", try_idx)
    assert except_idx != -1
    body = src[try_idx + len("try:"):except_idx]
    import textwrap
    return textwrap.dedent(body)


def test_seam4_eager_persist_fires_on_charge_to_hold_edge():
    """CHARGE→HOLD edge (False→True) must schedule save immediately.

    Mutation: delete the async_create_task line in the production block.
    RED because save_calls stays 0. The test EXEC's the on-disk production
    block, so a source mutation propagates directly.
    """
    src = _load_energy_source()
    body = _extract_eager_block(src)
    loop = asyncio.new_event_loop()
    try:
        hass = MagicMock()

        def _create_task(coro):
            loop.run_until_complete(coro)

        hass.async_create_task = _create_task
        battery = types.SimpleNamespace(_arbitrage_chunk_completed=True)
        shell = _EagerShell(hass, battery, last_completed=False)
        # Bind logger + exec production block against shell.
        import logging
        exec(
            body,
            {"_LOGGER": logging.getLogger("seam4"), "getattr": getattr},
            {"self": shell},
        )
        assert shell._save_calls == 1, (
            f"Seam #4: CHARGE→HOLD edge did not schedule save. "
            f"save_calls={shell._save_calls}"
        )
    finally:
        loop.close()


def test_seam4_eager_persist_no_double_fire_on_steady_state():
    """After the edge, staying HOLD (True→True) must NOT re-schedule."""
    src = _load_energy_source()
    body = _extract_eager_block(src)
    loop = asyncio.new_event_loop()
    try:
        hass = MagicMock()
        hass.async_create_task = lambda coro: loop.run_until_complete(coro)
        battery = types.SimpleNamespace(_arbitrage_chunk_completed=True)
        shell = _EagerShell(hass, battery, last_completed=True)
        import logging
        exec(
            body,
            {"_LOGGER": logging.getLogger("seam4"), "getattr": getattr},
            {"self": shell},
        )
        assert shell._save_calls == 0, (
            "Seam #4: steady-state HOLD spuriously re-persisted."
        )
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Seam #5 — Restore tz-normalization for NAIVE persisted boundary
# (energy.py:1440-1471)
# ---------------------------------------------------------------------------


class _FakeDB:
    def __init__(self, payloads):
        self._payloads = payloads

    async def restore_energy_state_with_age(self, key, max_age_hours):
        entry = self._payloads.get(key)
        if entry is None:
            return None
        json_str, age_h = entry
        if age_h > max_age_hours:
            return None
        return json_str


class _FakeBatteryForLatch:
    def __init__(self, live_boundary_dt=None):
        # WV fields
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
        return (self._live_boundary_dt, "mid_peak", 240)


def _make_coord_shell(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )

    class _Stub:
        pass

    stub = _Stub()
    stub.hass = hass
    stub._restore_wv_state = EnergyCoordinator._restore_wv_state.__get__(stub, _Stub)
    return stub


@pytest.mark.asyncio
async def test_seam5_restore_handles_naive_persisted_boundary_ahead():
    """NAIVE boundary_iso (no tz) that is AHEAD of now → restored.

    Mutation: strip the tz-normalize branch (assume tz-aware). RED
    because comparing naive parsed_bnd vs tz-aware utcnow() raises
    TypeError → the try/except swallows and no restore happens →
    _arbitrage_chunk_completed stays False.
    """
    # Force tz-aware utcnow independent of prior tests' monkey-patches
    # (some sibling test files patch `dt_util.utcnow` to `datetime.utcnow`
    # which returns naive — that would defeat the tz-mismatch we exercise).
    from homeassistant.util import dt as dt_util
    dt_util.utcnow = _utcnow  # tz-aware
    dt_util.parse_datetime = _parse_datetime
    dt_util.UTC = _tz_module.utc
    now_utc = dt_util.utcnow()
    # NAIVE iso — no tz suffix. 4h ahead of now (in UTC clock terms).
    boundary_naive = (now_utc + timedelta(hours=4)).replace(tzinfo=None)
    payload = _json.dumps({
        "completed": True,
        "boundary_iso": boundary_naive.isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 0.1)})
    # Live boundary matches (naive) so identity check would pass.
    battery = _FakeBatteryForLatch(
        live_boundary_dt=now_utc + timedelta(hours=4),
    )
    stub = _make_coord_shell(MagicMock())
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is True, (
        "Seam #5: naive persisted boundary in the future was NOT restored "
        "— tz-normalize branch likely stripped."
    )


@pytest.mark.asyncio
async def test_seam5_restore_naive_persisted_boundary_passed_still_dropped():
    """NAIVE boundary in the PAST → still dropped (stale). Guards against
    a mutation that skips the compare entirely."""
    from homeassistant.util import dt as dt_util
    dt_util.utcnow = _utcnow
    dt_util.parse_datetime = _parse_datetime
    dt_util.UTC = _tz_module.utc
    now_utc = dt_util.utcnow()
    boundary_naive = (now_utc - timedelta(hours=2)).replace(tzinfo=None)
    payload = _json.dumps({
        "completed": True,
        "boundary_iso": boundary_naive.isoformat(),
    })
    db = _FakeDB({"arbitrage_chunk_latch": (payload, 0.1)})
    battery = _FakeBatteryForLatch(
        live_boundary_dt=now_utc - timedelta(hours=2),
    )
    stub = _make_coord_shell(MagicMock())
    await stub._restore_wv_state(db, battery, None, 10.0)
    assert battery._arbitrage_chunk_completed is False, (
        "Seam #5: naive passed boundary was resurrected — staleness gate broken."
    )

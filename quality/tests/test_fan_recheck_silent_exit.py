"""Fan-recheck silent-exit invariant tests.

Regression pin (evidence 2026-07-19 00:37Z Living Room): an armed cycle
emitted ``fan_recheck_arm`` and NOTHING else — no outcome, no cancel, and
``fan_recheck_state.last_attempt_at`` stayed frozen at the July-13 cycle.
So an armed cycle exited via a path that neither wrote a terminal
activity row nor bumped ``last_attempt_at`` on the state row.

Invariant this file pins:
    Every transition OUT of ARMED / PAUSED / RESTORING MUST
      (a) emit exactly one terminal ``fan_recheck_outcome`` OR
          ``fan_recheck_cancel`` activity row, AND
      (b) set ``ctx.last_attempt_at`` to a value strictly newer than
          it was at arm-time.

Table-driven so a future ARMED-exit path added without a terminal
emitter fails a specific row here.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from test_fan_recheck_mode2_cycle import (
    _FakeConfigEntries,
    _build_world,
    _drain_tasks,
    _load_fan_recheck_module,
)
from test_fan_recheck_observability import _SpyActivityLogger, _install_spy


def _terminal_rows(spy):
    return [
        c for c in spy.calls
        if c.get("action") in ("fan_recheck_outcome", "fan_recheck_cancel")
    ]


# ---------------------------------------------------------------------------
# A3 — snapshot None (the most likely silent path for the 07-19 Living Room)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arm_expired_no_managed_fan_emits_terminal_and_bumps_ts():
    """ARMED -> _enter_paused -> FanController has no managed row for the
    room. Pre-fix: silently entered cooldown. Post-fix: single terminal
    ``fan_recheck_cancel`` row with reason ``no_managed_fan`` + bump."""
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    hass.config_entries = _FakeConfigEntries(
        [hass._fan_recheck_cm_entry, rc.entry]
    )
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    spy = _install_spy(hass)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    assert ctx.state == mod.STATE_ARMED
    before_ts = ctx.last_attempt_at

    # Drop the FanController's managed row so pause_for_recheck returns None.
    fc._room_fans.pop("exercise", None)

    await mgr._on_arm_expired(ctx)
    await _drain_tasks(hass)

    terminal = _terminal_rows(spy)
    assert len(terminal) == 1, (
        f"expected one terminal row, got {len(terminal)}: {terminal}"
    )
    row = terminal[0]
    assert row["action"] == "fan_recheck_cancel"
    assert row["details"]["reason"] == "no_managed_fan"
    assert ctx.last_attempt_at is not None
    assert before_ts is None or ctx.last_attempt_at > before_ts


# ---------------------------------------------------------------------------
# Shutdown-while-in-flight (A6 + P5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_while_armed_emits_terminal_and_bumps_ts():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    assert ctx.state == mod.STATE_ARMED
    before_ts = ctx.last_attempt_at
    await mgr.shutdown()
    await _drain_tasks(hass)
    terminal = _terminal_rows(spy)
    assert len(terminal) == 1
    row = terminal[0]
    assert row["action"] == "fan_recheck_cancel"
    assert row["details"]["reason"] == "shutdown_in_armed"
    assert ctx.last_attempt_at is not None
    assert before_ts is None or ctx.last_attempt_at > before_ts


@pytest.mark.asyncio
async def test_shutdown_while_paused_emits_terminal():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    hass.config_entries = _FakeConfigEntries(
        [hass._fan_recheck_cm_entry, rc.entry]
    )
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    spy = _install_spy(hass)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    await mgr._enter_paused(ctx, rc)
    spy.calls.clear()  # drop the arm row; focus on shutdown
    await mgr.shutdown()
    await _drain_tasks(hass)
    terminal = _terminal_rows(spy)
    assert len(terminal) == 1
    assert terminal[0]["details"]["reason"] == "shutdown_in_paused"


# ---------------------------------------------------------------------------
# Rehydrate silent paths (A7 / P7 / P8)
# ---------------------------------------------------------------------------


def _make_rehydrate_row(entry_id, state, entered_iso=None, last_attempt_iso=None):
    return {
        "room_id": entry_id,
        "state": state,
        "state_entered_at": entered_iso,
        "snapshot_json": None,
        "attempts_in_hour": 0,
        "last_outcome": None,
        "last_attempt_at": last_attempt_iso,
        "ble_ladder_layer": "none",
    }


@pytest.mark.asyncio
async def test_rehydrate_armed_emits_terminal():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    # Prime the DB rows so async_setup rehydrates directly.
    db.rows = {rc.entry.entry_id: _make_rehydrate_row(rc.entry.entry_id, mod.STATE_ARMED)}
    await mgr.async_setup()
    await _drain_tasks(hass)
    terminal = _terminal_rows(spy)
    assert any(
        r["details"].get("reason") == "rehydrate_armed" for r in terminal
    ), terminal
    ctx = mgr._rooms["exercise"]
    assert ctx.state == mod.STATE_IDLE
    assert ctx.last_attempt_at is not None


@pytest.mark.asyncio
async def test_rehydrate_restoring_emits_terminal():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    db.rows = {rc.entry.entry_id: _make_rehydrate_row(rc.entry.entry_id, mod.STATE_RESTORING)}
    await mgr.async_setup()
    await _drain_tasks(hass)
    terminal = _terminal_rows(spy)
    assert any(
        r["details"].get("reason") == "rehydrate_restoring" for r in terminal
    ), terminal


@pytest.mark.asyncio
async def test_rehydrate_stale_paused_emits_terminal():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    # entered a very long time ago -> stale-PAUSED branch (elapsed > window*2)
    stale_entered = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    db.rows = {
        rc.entry.entry_id: _make_rehydrate_row(
            rc.entry.entry_id, mod.STATE_PAUSED, entered_iso=stale_entered
        )
    }
    await mgr.async_setup()
    await _drain_tasks(hass)
    terminal = _terminal_rows(spy)
    assert any(
        r["details"].get("reason") == "rehydrate_stale_paused"
        for r in terminal
    ), terminal


# ---------------------------------------------------------------------------
# Existing ARMED-cancel paths now bump last_attempt_at (regression pin
# on the timestamp-bump half of the invariant).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_motion_midflight_armed_bumps_last_attempt_at():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    assert ctx.state == mod.STATE_ARMED
    before_ts = ctx.last_attempt_at
    rc.data["motion_detected"] = True
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert ctx.last_attempt_at is not None
    assert before_ts is None or ctx.last_attempt_at > before_ts


@pytest.mark.asyncio
async def test_arm_expired_ineligible_bumps_last_attempt_at():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    hass.config_entries = _FakeConfigEntries(
        [hass._fan_recheck_cm_entry, rc.entry]
    )
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    spy = _install_spy(hass)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    before_ts = ctx.last_attempt_at
    # Make _still_armed_eligible return False (turn the fan off).
    hass.states.set("fan.exercise", "off")
    await mgr._on_arm_expired(ctx)
    await _drain_tasks(hass)
    cancel_rows = [
        c for c in spy.calls if c.get("action") == "fan_recheck_cancel"
    ]
    assert any(
        r["details"].get("reason") == "arm_expired_ineligible"
        for r in cancel_rows
    )
    assert ctx.last_attempt_at is not None
    assert before_ts is None or ctx.last_attempt_at > before_ts


# ---------------------------------------------------------------------------
# Table-driven invariant: enumerate every ARMED-exit transition and assert
# EACH one produces exactly one terminal activity row.
#
# Any future ARMED-exit path added without a terminal emitter should fail a
# specific row here rather than silently regress the observability contract.
# ---------------------------------------------------------------------------


async def _drive_arm_expired_no_room_coord(mod, hass, mgr, rc, fc, spy):
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    # Empty config_entries -> _room_coord_for returns None.
    hass.config_entries = _FakeConfigEntries([hass._fan_recheck_cm_entry])
    spy.calls.clear()
    await mgr._on_arm_expired(ctx)
    await _drain_tasks(hass)
    return "arm_expired_no_room_coord"


async def _drive_arm_expired_ineligible(mod, hass, mgr, rc, fc, spy):
    hass.config_entries = _FakeConfigEntries(
        [hass._fan_recheck_cm_entry, rc.entry]
    )
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    hass.states.set("fan.exercise", "off")
    spy.calls.clear()
    await mgr._on_arm_expired(ctx)
    await _drain_tasks(hass)
    return "arm_expired_ineligible"


async def _drive_arm_expired_no_managed_fan(mod, hass, mgr, rc, fc, spy):
    hass.config_entries = _FakeConfigEntries(
        [hass._fan_recheck_cm_entry, rc.entry]
    )
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    fc._room_fans.pop("exercise", None)
    spy.calls.clear()
    await mgr._on_arm_expired(ctx)
    await _drain_tasks(hass)
    return "no_managed_fan"


async def _drive_motion_midflight_armed(mod, hass, mgr, rc, fc, spy):
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    spy.calls.clear()
    rc.data["motion_detected"] = True
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    return "motion"


async def _drive_l1_midflight_armed(mod, hass, mgr, rc, fc, spy):
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    spy.calls.clear()
    pc = hass.data["universal_room_automation"]["person_coordinator"]
    pc.room_persons["exercise"] = ["operator"]
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    return "ble_l1"


async def _drive_shutdown_armed(mod, hass, mgr, rc, fc, spy):
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    spy.calls.clear()
    await mgr.shutdown()
    await _drain_tasks(hass)
    return "shutdown_in_armed"


ARMED_EXIT_DRIVERS = [
    ("arm_expired_no_room_coord", _drive_arm_expired_no_room_coord),
    ("arm_expired_ineligible", _drive_arm_expired_ineligible),
    ("no_managed_fan", _drive_arm_expired_no_managed_fan),
    ("motion_midflight", _drive_motion_midflight_armed),
    ("l1_midflight", _drive_l1_midflight_armed),
    ("shutdown_in_armed", _drive_shutdown_armed),
]


@pytest.mark.parametrize("label,driver", ARMED_EXIT_DRIVERS)
@pytest.mark.asyncio
async def test_every_armed_exit_emits_exactly_one_terminal_row(label, driver):
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    reason = await driver(mod, hass, mgr, rc, fc, spy)
    terminal = _terminal_rows(spy)
    assert len(terminal) == 1, (
        f"[{label}] expected exactly one terminal row, got "
        f"{len(terminal)}: {[r.get('action') for r in terminal]}"
    )
    assert terminal[0]["details"].get("reason") == reason, (
        f"[{label}] expected reason={reason!r}, "
        f"got {terminal[0]['details'].get('reason')!r}"
    )
    ctx = mgr._rooms["exercise"]
    assert ctx.last_attempt_at is not None, (
        f"[{label}] last_attempt_at was not bumped"
    )

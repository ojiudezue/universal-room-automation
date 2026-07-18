"""Fan-recheck observability cycle tests.

Covers the 2026-07-18 build:
  - Per-tick evaluation counter increments on every idle-tick eligibility call
  - Veto reason counters increment per rejection reason (master_off, sleep_state,
    room_disabled, ble_l1, high_still_risk, ...)
  - ura_activity_log rows written on ARM, OUTCOME (both types), and CANCEL
  - Zero-DB-write-on-veto guard: a vetoed eligibility tick does NOT write a row
  - Aggregate cross-room counters

Reuses the module loader + fixtures from ``test_fan_recheck_mode2_cycle`` so
we don't rebuild the HA stub scaffolding.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from test_fan_recheck_mode2_cycle import (
    _FakeConfigEntries,
    _build_world,
    _drain_tasks,
    _load_fan_recheck_module,
)


class _SpyActivityLogger:
    """Captures every activity_logger.log() call for assertion."""

    def __init__(self):
        self.calls = []

    async def log(self, **kwargs):
        self.calls.append(dict(kwargs))


def _install_spy(hass):
    spy = _SpyActivityLogger()
    hass.data["universal_room_automation"]["activity_logger"] = spy
    return spy


# ============================================================================
# Per-tick evaluation counter — the denominator
# ============================================================================


@pytest.mark.asyncio
async def test_eval_counter_increments_each_idle_tick():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    for _ in range(4):
        mgr.on_room_tick(rc)
        await _drain_tasks(hass)
        # After the first eligible tick the room transitions ARMED; drop back
        # to idle so subsequent ticks re-enter _is_eligible.
        mgr._rooms["exercise"].state = mod.STATE_IDLE
    attrs = mgr.get_room_attrs("exercise")
    assert attrs["fan_recheck_eval_count"] == 4


# ============================================================================
# Veto reason counters
# ============================================================================


@pytest.mark.asyncio
async def test_veto_master_off_counts():
    mod, hass, mgr, rc, fc, pc, db = _build_world(master_enabled=False)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    attrs = mgr.get_room_attrs("exercise")
    assert attrs["fan_recheck_veto_counts"].get("master_off") == 2
    assert attrs["fan_recheck_eval_count"] == 2


@pytest.mark.asyncio
async def test_veto_sleep_state_counts():
    mod, hass, mgr, rc, fc, pc, db = _build_world(house_state="sleep")
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    attrs = mgr.get_room_attrs("exercise")
    assert attrs["fan_recheck_veto_counts"].get("sleep_state") == 1


@pytest.mark.asyncio
async def test_veto_room_disabled_counts():
    mod, hass, mgr, rc, fc, pc, db = _build_world(room_opt_in=False)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"].get(
        "room_disabled"
    ) == 1


@pytest.mark.asyncio
async def test_veto_no_fan_on_counts():
    mod, hass, mgr, rc, fc, pc, db = _build_world(with_fan_on=False)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"].get(
        "no_fan_on"
    ) == 1


@pytest.mark.asyncio
async def test_veto_ble_l1_counts():
    mod, hass, mgr, rc, fc, pc, db = _build_world(person_in_room=True)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"].get(
        "ble_l1"
    ) == 1


@pytest.mark.asyncio
async def test_veto_high_still_risk_counts():
    """Tier-1 bedroom with L2 hit forced L3-only — high_still_risk veto."""
    mod, hass, mgr, rc, fc, pc, db = _build_world(
        ble_tier=1,
        l2_adjacent_present=True,
        l2_allowed=True,
        room_type="bedroom",
    )
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    counts = mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"]
    assert counts.get("high_still_risk") == 1


@pytest.mark.asyncio
async def test_veto_boot_settle_counts():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    mgr._presence._boot_settle_done = False
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"].get(
        "boot_settle"
    ) == 1


# ============================================================================
# ura_activity_log — ARM row
# ============================================================================


@pytest.mark.asyncio
async def test_arm_writes_activity_log_row():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_ARMED
    arm_rows = [c for c in spy.calls if c.get("action") == "fan_recheck_arm"]
    assert len(arm_rows) == 1
    row = arm_rows[0]
    assert row["coordinator"] == "room"
    assert row["room"] == "exercise"
    assert row["details"]["room"] == "exercise"
    assert row["details"]["ble_ladder_layer"] in ("L1", "L2", "L3", "none")
    assert row["details"]["arm_delay_s"] == 60


# ============================================================================
# ura_activity_log — OUTCOME rows (vacated + occupied_confirmed)
# ============================================================================


@pytest.mark.asyncio
async def test_outcome_vacated_writes_activity_log_row():
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
    rc.data["presence_detected"] = False
    rc.data["occupancy_source"] = "none"
    await mgr._on_pause_window_done(ctx, datetime.now(timezone.utc))
    await _drain_tasks(hass)
    outcome_rows = [
        c for c in spy.calls if c.get("action") == "fan_recheck_outcome"
    ]
    assert len(outcome_rows) == 1
    assert outcome_rows[0]["details"]["outcome"] == mod.OUTCOME_VACATED
    assert outcome_rows[0]["details"]["forced"] is False


@pytest.mark.asyncio
async def test_outcome_occupied_confirmed_writes_activity_log_row():
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
    # mmwave persists -> occupied_confirmed
    await mgr._on_pause_window_done(ctx, datetime.now(timezone.utc))
    await _drain_tasks(hass)
    outcome_rows = [
        c for c in spy.calls if c.get("action") == "fan_recheck_outcome"
    ]
    assert len(outcome_rows) == 1
    assert (
        outcome_rows[0]["details"]["outcome"]
        == mod.OUTCOME_OCCUPIED_CONFIRMED
    )


# ============================================================================
# ura_activity_log — CANCEL rows
# ============================================================================


@pytest.mark.asyncio
async def test_motion_midflight_writes_cancel_activity_row():
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    spy = _install_spy(hass)
    await mgr.async_setup()
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert mgr.get_room_state("exercise") == mod.STATE_ARMED
    rc.data["motion_detected"] = True
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    cancel_rows = [
        c for c in spy.calls if c.get("action") == "fan_recheck_cancel"
    ]
    assert len(cancel_rows) == 1
    assert cancel_rows[0]["details"]["reason"] == "motion"


# ============================================================================
# Write-flood regression guard — vetoed tick MUST NOT write a DB activity row
# ============================================================================


@pytest.mark.asyncio
async def test_vetoed_tick_writes_zero_activity_rows():
    """Bug Class #52 hygiene: eligibility vetoes are per-tick and must not
    write to the durable activity log (a per-tick writer here would flood the
    DB write queue). Only state transitions (arm/outcome/cancel) log.
    """
    mod, hass, mgr, rc, fc, pc, db = _build_world(master_enabled=False)
    spy = _install_spy(hass)
    await mgr.async_setup()
    for _ in range(50):
        mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    assert spy.calls == [], (
        f"expected zero activity rows on vetoed ticks, got {len(spy.calls)}"
    )
    # But the RAM counter did increment — confirming the guard is about the DB,
    # not about observability itself.
    assert (
        mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"]["master_off"]
        == 50
    )
    assert mgr.get_room_attrs("exercise")["fan_recheck_eval_count"] == 50


# ============================================================================
# Aggregate cross-room counters
# ============================================================================


@pytest.mark.asyncio
async def test_aggregate_counters_sum_across_rooms():
    mod, hass, mgr, rc, fc, pc, db = _build_world(master_enabled=False)
    await mgr.async_setup()
    # Simulate a second room by writing directly into the counters — the
    # aggregate helper is a pure sum over the RAM maps.
    mgr._eval_counts["exercise"] = 3
    mgr._eval_counts["living_room"] = 5
    mgr._veto_counts["exercise"]["master_off"] = 3
    mgr._veto_counts["living_room"]["master_off"] = 4
    mgr._veto_counts["living_room"]["sleep_state"] = 1
    agg = mgr.get_aggregate_counters()
    assert agg["fan_recheck_eval_count_total"] == 8
    assert agg["fan_recheck_veto_counts_total"] == {
        "master_off": 7,
        "sleep_state": 1,
    }
    assert agg["fan_recheck_rooms_tracked"] == 2

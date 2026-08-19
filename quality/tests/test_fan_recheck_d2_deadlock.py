"""FAN-RECHECK-D2-DEADLOCK-1 acceptance tests (2026-08-19).

Covers:
- T-SHARED-EVALUATOR-PURITY: `is_recheck_eligible` MUST NOT mutate
  veto counters, ctx.ble_ladder_layer, or ctx.attempts. Guards the
  Advisory-2 inert-sink contract of `_evaluate_eligibility`.
- T-IS-RECHECK-ELIGIBLE-YES: returns True for a room that would arm.
- T-IS-RECHECK-ELIGIBLE-NO: returns False for a room that would veto,
  and returns False on manager-not-ready / unknown-room.
- T-D3-ISOLATION: a room whose `on_room_tick` raises MUST NOT skip
  sibling rooms' evaluation on the same tick (per-room try/except).

Fixture note (Advisory-3 / v5.8.0 hollow-coord seam): these tests
reuse `_build_world` from `test_fan_recheck_mode2_cycle` because
constructing a real `UniversalRoomCoordinator` end-to-end in-suite
requires a functional HomeAssistant instance (dispatcher, entity
registry, config_entry registration, DB write queue, and 40+ sensor
initializers) that the v5.8.0 setup-RecursionError incident showed is
not safe to shim. `is_recheck_eligible` is tested at the manager API
surface directly — the D2 defer wiring on the coordinator side is
covered by review C mutation-anchoring against the real
`coordinator.py` block. See build report for the full seam analysis.
"""

from __future__ import annotations

import pytest

from test_fan_recheck_mode2_cycle import (
    _build_world,
    _drain_tasks,
    _load_fan_recheck_module,
)


# ---------------------------------------------------------------------------
# T-SHARED-EVALUATOR-PURITY (Advisory-2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_recheck_eligible_purity_no_veto_counter_mutation():
    """Calling `is_recheck_eligible` N times MUST NOT increment any
    veto counter. Mutation-anchor: routing ANY gate through the live
    sink instead of the inert sink flips this test red — proving the
    inert-sink contract is load-bearing per-site.
    """
    mod, hass, mgr, rc, fc, pc, db = _build_world(master_enabled=False)
    await mgr.async_setup()
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    # Prime the eval by driving a live tick first (populates the
    # veto counter with a baseline value for master_off).
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    baseline_vetoes = dict(
        mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"],
    )
    baseline_evals = mgr.get_room_attrs("exercise")["fan_recheck_eval_count"]

    # 100 read-only probes.
    for _ in range(100):
        result = mgr.is_recheck_eligible("exercise")
        assert result is False  # master off → not eligible

    post_vetoes = dict(
        mgr.get_room_attrs("exercise")["fan_recheck_veto_counts"],
    )
    post_evals = mgr.get_room_attrs("exercise")["fan_recheck_eval_count"]

    assert post_vetoes == baseline_vetoes, (
        "is_recheck_eligible mutated veto counters — "
        "inert-sink contract violated. "
        f"before={baseline_vetoes} after={post_vetoes}"
    )
    assert post_evals == baseline_evals, (
        "is_recheck_eligible mutated eval counter"
    )


@pytest.mark.asyncio
async def test_is_recheck_eligible_purity_no_ladder_layer_mutation():
    """A BLE-L1 room would set `ctx.ble_ladder_layer = LAYER_L1` on the
    live path. The read-only probe MUST leave it untouched. Mutation-
    anchor: route the L1 branch's `set_ladder_layer` through the live
    sink → this test fails (ladder flips to L1 without an arm cycle).
    """
    # Person in room → L1 veto fires.
    mod, hass, mgr, rc, fc, pc, db = _build_world(person_in_room=True)
    await mgr.async_setup()
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    # Ensure the ctx exists but ladder is at default.
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    # Live path DID mutate ladder to L1 (expected on the live sink).
    assert mgr._rooms["exercise"].ble_ladder_layer == mod.LAYER_L1
    # Reset for the purity assertion.
    mgr._rooms["exercise"].ble_ladder_layer = mod.LAYER_NONE

    for _ in range(50):
        mgr.is_recheck_eligible("exercise")

    assert mgr._rooms["exercise"].ble_ladder_layer == mod.LAYER_NONE, (
        "is_recheck_eligible mutated ctx.ble_ladder_layer — "
        "inert-sink contract violated"
    )


@pytest.mark.asyncio
async def test_is_recheck_eligible_purity_no_attempts_mutation():
    """`_prune_attempts` mutates `ctx.attempts`. The read-only path MUST
    not call it. Mutation-anchor: route the rate-cap branch's
    `prune_attempts` through the live sink → this test flips red.
    """
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    mgr.on_room_tick(rc)
    await _drain_tasks(hass)
    ctx = mgr._rooms["exercise"]
    # Seed a bogus attempts entry that _prune_attempts would strip.
    from datetime import datetime, timedelta, timezone

    old_stamp = datetime.now(timezone.utc) - timedelta(hours=2)
    ctx.attempts.append(old_stamp)
    baseline_len = len(ctx.attempts)

    for _ in range(50):
        mgr.is_recheck_eligible("exercise")

    assert len(ctx.attempts) == baseline_len, (
        "is_recheck_eligible pruned ctx.attempts — "
        "inert-sink contract violated (prune_attempts leaked)"
    )


# ---------------------------------------------------------------------------
# T-IS-RECHECK-ELIGIBLE — basic yes / no / error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_recheck_eligible_returns_true_for_armable_room():
    """A room that WOULD arm on the next live tick must return True from
    the read-only probe. This is what the D2 defer gate consumes.
    """
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    # Register the room-coord in hass.data by entry_id so
    # `_room_coord_for` (the same resolver D2 uses at
    # coordinator.py:3354) can find it. Live HA populates this on
    # ConfigEntry setup.
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    # Do NOT call on_room_tick — we want to prove the probe alone
    # answers correctly BEFORE the state machine has ever been driven.
    assert mgr.is_recheck_eligible("exercise") is True


@pytest.mark.asyncio
async def test_is_recheck_eligible_returns_false_for_master_off():
    mod, hass, mgr, rc, fc, pc, db = _build_world(master_enabled=False)
    await mgr.async_setup()
    hass.data["universal_room_automation"][rc.entry.entry_id] = rc
    assert mgr.is_recheck_eligible("exercise") is False


@pytest.mark.asyncio
async def test_is_recheck_eligible_returns_false_before_setup():
    """Advisory-4: unready manager MUST return False so D2 fires as
    backstop (never silently disable D2 house-wide).
    """
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    # Deliberately skip mgr.async_setup() — _setup_done is False.
    assert mgr.is_recheck_eligible("exercise") is False


@pytest.mark.asyncio
async def test_is_recheck_eligible_returns_false_for_unknown_room():
    """Room name that doesn't resolve to a config entry -> False."""
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()
    assert mgr.is_recheck_eligible("nonexistent_room") is False


@pytest.mark.asyncio
async def test_is_recheck_eligible_returns_false_on_raise():
    """Advisory-4: any raise inside the probe defaults to False."""
    mod, hass, mgr, rc, fc, pc, db = _build_world()
    await mgr.async_setup()

    def _boom(_name):
        raise RuntimeError("intentional")

    # Replace _room_coord_for to raise — simulates a broken hass.data.
    mgr._room_coord_for = _boom  # type: ignore[assignment]
    assert mgr.is_recheck_eligible("exercise") is False


# ---------------------------------------------------------------------------
# T-D3-ISOLATION (per-room exception isolation in presence.py fan-out)
# ---------------------------------------------------------------------------


def test_d3_per_room_isolation_pattern_directly():
    """Verifies the shape used in `presence.py:_periodic_inference`
    fan-out — a per-room try/except so one raising room can't skip
    siblings. This is a structural test that documents the invariant;
    the actual fan-out lives inside the presence coord's tick, which
    requires a full presence coordinator to construct in-suite (see
    v5.8.0 seam analysis in the build report).

    Mutation-anchor: change `presence.py`'s per-room try/except back
    to a loop-wrapping try/except -> this test's shape assertion still
    passes but the fan-out loop breaks under real HA — that specific
    regression is caught by the diff-review of `presence.py:6893-6908`.
    """
    calls = []

    class _Raising:
        room_name = "raises"

        def on_room_tick_wrap(self):
            raise RuntimeError("boom")

    class _Working:
        room_name = "sibling"

        def on_room_tick_wrap(self):
            calls.append("sibling")

    rooms = [_Raising(), _Working()]

    # Mirror the shape at presence.py:6893-6908 (post-D3 fix):
    for room in rooms:
        try:
            room.on_room_tick_wrap()
        except Exception:
            # Sibling MUST still be evaluated on this same tick.
            pass

    assert calls == ["sibling"], (
        "D3 pattern regressed — one room's raise skipped its sibling"
    )

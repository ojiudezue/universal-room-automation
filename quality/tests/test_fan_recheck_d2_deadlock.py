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


def _load_fan_recheck_helper():
    """Import ``_run_fan_recheck_tick_for_rooms`` from presence.py.

    presence.py has heavy transitive imports (const, signals, house_state,
    hvac_const, _ble_corroboration, etc.) — we've already stubbed those
    for `_load_fan_recheck_module`. Reuse that stub environment and then
    load presence.py just enough to extract the module-level helper.
    Because the helper is defined near the top of the file (right after
    ``_LOGGER = logging.getLogger(__name__)``), we don't need the rest
    of the module to execute; we exec only the helper's source block.
    """
    _load_fan_recheck_module()  # sets up ura stub + HA stubs
    from pathlib import Path
    import re

    ROOT = Path(__file__).resolve().parents[2]
    src_path = (
        ROOT
        / "custom_components/universal_room_automation/domain_coordinators/presence.py"
    )
    text = src_path.read_text()
    # Extract the helper source (module-level def) — anchored by name.
    m = re.search(
        r"^def _run_fan_recheck_tick_for_rooms\(.*?(?=^def |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert m, "helper _run_fan_recheck_tick_for_rooms not found in presence.py"
    helper_src = m.group(0)
    # Provide only the two names the helper closes over: logging + Any.
    import logging as _logging
    from typing import Any as _Any

    ns: dict = {
        "logging": _logging,
        "Any": _Any,
        "_LOGGER": _logging.getLogger("ura.presence.helper_test"),
    }
    exec(compile(helper_src, str(src_path), "exec"), ns)
    return ns["_run_fan_recheck_tick_for_rooms"]


def test_d3_helper_isolates_raising_room_from_siblings(caplog):
    """T-D3-ISOLATION (real, not hollow — F-C-2 fix-up 2026-08-19).

    Drive ``_run_fan_recheck_tick_for_rooms`` (the extracted helper
    inside production ``presence.py``) with 3 rooms; the middle room's
    tick raises. Assert:
      (a) rooms 1 AND 3 STILL have their tick_fn invoked (behavioral
          isolation proof),
      (b) the raising room is logged at WARNING with its room name,
      (c) helper does not propagate the exception.

    Mutation-anchor drill (recorded in build report): moving the
    ``try/except`` OUTSIDE the ``for`` loop (i.e. reverting to the
    pre-D3 all-rooms-wrapper shape) makes assertion (a) fail because
    rooms after the raiser are skipped.
    """
    import logging as _logging

    helper = _load_fan_recheck_helper()

    calls: list[str] = []

    class _Room:
        def __init__(self, name: str, should_raise: bool = False) -> None:
            self.room_name = name
            self._raise = should_raise

    def tick_fn(room):
        calls.append(room.room_name)
        if getattr(room, "_raise", False):
            raise RuntimeError(f"boom-{room.room_name}")

    rooms = [_Room("first"), _Room("middle", should_raise=True), _Room("third")]

    # Route WARNING through caplog on the same logger name the helper uses.
    test_logger = _logging.getLogger("d3_isolation_test")
    with caplog.at_level(_logging.WARNING, logger="d3_isolation_test"):
        helper(rooms, tick_fn, logger=test_logger)

    # (a) all three rooms attempted — the middle raise did NOT skip "third".
    assert calls == ["first", "middle", "third"], (
        f"D3 isolation broken — expected all rooms ticked, got {calls}. "
        "If 'third' is missing, the raise from 'middle' skipped its sibling."
    )
    # (b) WARNING log names the raising room.
    warnings = [
        r for r in caplog.records
        if r.levelno == _logging.WARNING and "on_room_tick failed" in r.getMessage()
    ]
    assert warnings, "no WARNING log emitted for the raising room"
    assert any("middle" in r.getMessage() for r in warnings), (
        f"WARNING log did not name the raising room: {[r.getMessage() for r in warnings]}"
    )
    # (c) implicit — if the helper propagated, we would not have reached here.


def test_d3_helper_no_rooms_is_noop():
    helper = _load_fan_recheck_helper()
    # Should not raise, should not log.
    helper([], lambda _r: (_ for _ in ()).throw(RuntimeError("unreachable")))

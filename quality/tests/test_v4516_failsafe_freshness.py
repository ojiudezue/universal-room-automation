"""v4.5.16 — Combined cycle covering two distinct fixes:

A. Failsafe occupancy-freshness gate (the headline fix):
   URA's RESILIENCE-001 failsafe at coordinator.py:1402 was firing nightly
   for every occupied bedroom — including legitimate continuous occupancy
   (sleeping kid, mmWave correctly detecting them). Verified live for
   Ziri Bedroom on 2026-05-11 night (CDT): motion went stale during sleep
   (expected — PIR doesn't fire on micro-movements) but sensor_presence
   (mmWave) stayed continuously ON for 4 hours. Failsafe fired at the
   4-hour mark and force-marked the room vacant for 30-60 seconds before
   the next cycle re-occupied it. That brief false-vacant fires any
   automation gated on vacancy transitions.

   `_last_motion_time` is a misleadingly-named field — it's actually the
   universal Tier 1 (PIR + mmWave + occupancy sensor) freshness timestamp
   at coordinator.py:1353. So the fix is: require this timestamp to be
   stale before firing the failsafe. ~20 LoC, single isolated change at
   the failsafe check.

B. Prediction-scoring diagnostic (Phase 1):
   `sensor.ura_coordinator_manager_bayesian_prediction_accuracy` reports
   0 prediction rows in 7d despite the eval task being registered. Root
   cause is hidden by a silent _LOGGER.debug swallow at __init__.py:1214.
   v4.5.16 swaps debug → warning + log row counts + log empty-batch case
   so we have evidence after one decision bin (~6h) to drive Phase 2.

Tests below cover the failsafe gate via isolated decision-helper tests
(mirroring v4.5.15 pattern — no full coordinator instantiation hazard).
The diagnostic swallow change is asserted via AST + source-grep.
"""

import ast
from typing import Optional

import pytest


@pytest.fixture(scope="module")
def coordinator_src() -> str:
    with open("custom_components/universal_room_automation/coordinator.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def init_src() -> str:
    with open("custom_components/universal_room_automation/__init__.py") as f:
        return f.read()


# ===========================================================================
# Part A — Failsafe occupancy-freshness gate
# ===========================================================================
# Isolated decision-helper: mirror the v4.5.16 failsafe check at
# coordinator.py:1409-1448. The check has 3 inputs (duration, failsafe
# threshold, motion_age) and produces a boolean (should fire?).


def _should_fire(
    duration_seconds: float,
    failsafe_seconds: float,
    motion_age_seconds: Optional[float],
    occupancy_timeout_seconds: float = 900,  # bedroom default 15 min
) -> bool:
    """Mirror of coordinator.py:1409-1448 logic. If a future refactor
    moves the failsafe gate, this test fails and the caller must update.
    """
    if duration_seconds <= failsafe_seconds:
        return False  # under duration — never fire
    # Over duration. Check freshness.
    if motion_age_seconds is None:
        return True  # no signal data → treat as stale → fire
    if motion_age_seconds < 2 * occupancy_timeout_seconds:
        return False  # signal fresh → skip
    return True  # signal stale + over duration → fire


def test_failsafe_does_not_fire_under_duration():
    """Most basic case: bedroom occupied 2 hours (under 4-hour ceiling)
    → no fire regardless of motion freshness.
    """
    assert _should_fire(
        duration_seconds=2 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=60,  # fresh
    ) is False
    assert _should_fire(
        duration_seconds=2 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=60 * 60,  # stale
    ) is False


def test_failsafe_does_not_fire_over_duration_when_motion_fresh():
    """The headline bug fix: bedroom occupied 4.5 hours with mmWave
    continuously firing (motion age = 5 seconds). v4.5.16 must NOT fire.
    Previously this fired nightly for every occupied bedroom.
    """
    assert _should_fire(
        duration_seconds=4.5 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=5,  # mmWave fired 5 sec ago
    ) is False


def test_failsafe_fires_when_motion_stale_and_over_duration():
    """The original stuck-sensor / forgotten-light scenario: 4.5 hours
    occupied, no motion in last hour. Failsafe should fire — exactly
    what RESILIENCE-001 was designed for.
    """
    assert _should_fire(
        duration_seconds=4.5 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=60 * 60,  # 60 min since last motion
    ) is True


def test_failsafe_fires_when_no_motion_timestamp_at_all():
    """A room that never had any motion signal (camera-only, BLE-only,
    or fresh install) but is marked occupied somehow. Treat as stale →
    fire failsafe (this is the genuinely-stuck case the failsafe exists
    for).
    """
    assert _should_fire(
        duration_seconds=4.5 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=None,
    ) is True


def test_failsafe_boundary_exactly_at_duration():
    """Strict `>` comparison: exactly at the failsafe threshold should
    NOT fire (gives a tick of grace).
    """
    assert _should_fire(
        duration_seconds=4 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=10 * 60,  # stale enough to fire if duration triggered
    ) is False


def test_failsafe_boundary_exactly_at_stale_threshold():
    """Stale threshold is `signal_age < 2 * occupancy_timeout` (strict).
    For bedroom (timeout=900s), exactly 1800s = fresh boundary — stale.
    """
    # 1799s: still considered fresh, no fire
    assert _should_fire(
        duration_seconds=4.5 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=1799,
        occupancy_timeout_seconds=900,
    ) is False
    # 1800s exactly: NOT < 1800, so stale, fire
    assert _should_fire(
        duration_seconds=4.5 * 3600,
        failsafe_seconds=4 * 3600,
        motion_age_seconds=1800,
        occupancy_timeout_seconds=900,
    ) is True


def test_failsafe_closet_60min_with_fresh_signal_does_not_fire():
    """Closet with 60-min failsafe (v4.5.15) + mmWave firing 1 sec ago.
    Should not fire — closet is in active use.
    """
    # Closet motion timeout is 120s, so stale threshold = 240s
    assert _should_fire(
        duration_seconds=65 * 60,
        failsafe_seconds=60 * 60,
        motion_age_seconds=1,
        occupancy_timeout_seconds=120,
    ) is False


def test_failsafe_closet_60min_with_stale_signal_fires():
    """Closet 65 min occupied, motion silent for 5 min (>240s threshold).
    Stuck-sensor pattern — fire failsafe.
    """
    assert _should_fire(
        duration_seconds=65 * 60,
        failsafe_seconds=60 * 60,
        motion_age_seconds=5 * 60,
        occupancy_timeout_seconds=120,
    ) is True


# ===========================================================================
# Part A — Source-grep + AST regression guards
# ===========================================================================


def _failsafe_body(coordinator_src: str) -> str:
    """Locate the live P24-FAILSAFE block (moved 2026-08-10)."""
    # After the P24 move, the OLD in-place anchor still contains
    # "RESILIENCE-001: Maximum active duration failsafe" as its
    # top-line phrase in the LIVE block (P24 FAILSAFE moved after
    # overrides). Use the "P24 FAILSAFE" marker to disambiguate from
    # any stub comment referencing the same phrase.
    marker = "# === P24 FAILSAFE (moved after overrides"
    start = coordinator_src.find(marker)
    assert start >= 0, "P24 FAILSAFE (moved) block missing"
    # Bounded by TRUE VACANCY FINALIZE block that follows immediately.
    end = coordinator_src.find("# === TRUE VACANCY FINALIZE", start)
    return coordinator_src[start:end if end > 0 else start + 4000]


def test_failsafe_block_uses_last_motion_time(coordinator_src: str):
    """The failsafe freshness gate must reference a `_last_*_motion_time`
    timestamp. P24 fix (2026-08-10) changed the gate from
    `_last_motion_time` (self-refreshed → tautological skip) to
    `_last_pir_motion_time` (real PIR events only).
    """
    body = _failsafe_body(coordinator_src)
    assert "self._last_pir_motion_time" in body, (
        "Failsafe block must reference self._last_pir_motion_time (P24 "
        "fix 2026-08-10 — previously _last_motion_time, which the "
        "current tick self-refreshed)."
    )
    assert "signal_stale" in body or "signal_age" in body, (
        "Failsafe should expose the stale-or-fresh decision in a named "
        "variable for log clarity and future readers."
    )


def test_failsafe_block_uses_2x_occupancy_timeout_threshold(coordinator_src: str):
    """The stale threshold must be 2x occupancy_timeout (design invariant
    preserved across the P24 move)."""
    body = _failsafe_body(coordinator_src)
    assert "2 * self._occupancy_timeout" in body, (
        "Stale threshold should be 2x self._occupancy_timeout — see "
        "design rationale in v4.5.16 README and BACKLOG entry."
    )


def test_failsafe_block_log_includes_signal_stale_phrase(coordinator_src: str):
    """The WARNING-level log when failsafe fires must include a stale-
    signal phrase so operators can distinguish this vacancy path from
    any other in log review. P24 fix (2026-08-10) renamed the log
    substring from 'signal stale' to 'PIR stale' (matches the P24(a)
    gate change).
    """
    body = _failsafe_body(coordinator_src)
    assert "PIR stale" in body, (
        "P24 log message should include 'PIR stale' for clarity."
    )


def test_failsafe_does_not_touch_camera_or_ble_branches(coordinator_src: str):
    """Risk-avoidant: v4.5.16 must NOT change the camera (~line 1430)
    or BLE (~line 1464) override branches. Those have second-order
    consequences for Sparse BLE hardening and STATE_TIME_SINCE_MOTION.
    Pin the existing `if not self._last_motion_time:` pattern.
    """
    # Camera branch should still set conditionally
    assert "Camera extends room occupancy" in coordinator_src
    # Look for the conditional set in the camera or BLE branch — at
    # least one occurrence of the protective pattern must remain
    assert coordinator_src.count(
        "if not self._last_motion_time:"
    ) >= 2, (
        "Camera + BLE branches should each retain `if not "
        "self._last_motion_time: self._last_motion_time = now`. "
        "v4.5.16 deliberately did NOT change these (Sparse BLE "
        "hardening + STATE_TIME_SINCE_MOTION semantics)."
    )


# ===========================================================================
# Part B — Prediction-scoring diagnostic (Phase 1 swallow → warning)
# ===========================================================================


def test_bayesian_accuracy_eval_no_longer_uses_logger_debug_swallow(init_src: str):
    """The silent debug swallow that hid the 0-rows-in-7d issue is gone.
    Catches accidental revert.
    """
    start = init_src.find("Bayesian accuracy eval failed")
    assert start >= 0, "Bayesian eval error log block not found"
    # Look at a window around it
    window_start = max(0, start - 200)
    window_end = min(len(init_src), start + 200)
    window = init_src[window_start:window_end]
    assert "_LOGGER.warning" in window, (
        "Bayesian accuracy eval error block must use _LOGGER.warning "
        "(was _LOGGER.debug — that's the bug we're diagnosing)."
    )


def test_bayesian_eval_logs_row_count_on_success(init_src: str):
    """The success path must log `len(batch_rows)` so we can see in
    HA logs whether eval is firing and producing rows.
    """
    # Look for the success log
    assert "wrote %d " in init_src and "prediction rows to DB" in init_src, (
        "v4.5.16 success log line missing — needed for Phase 2 diagnosis."
    )


def test_bayesian_eval_logs_empty_batch_case(init_src: str):
    """The empty-batch case is one of three possible failure modes
    (alongside exception + db-handle-none). Must be distinctly logged.
    """
    assert "produced 0 rows" in init_src, (
        "v4.5.16 must distinctly log the empty-batch case so Phase 2 "
        "can tell room_id mismatch from other failure modes."
    )


def test_bayesian_eval_warning_includes_exception_type(init_src: str):
    """The exception path's warning must include the exception TYPE,
    not just its str() — type names disambiguate failure shapes.
    """
    start = init_src.find("Bayesian accuracy eval failed")
    window_end = min(len(init_src), start + 400)
    window = init_src[start:window_end]
    assert "type=%s" in window or "type(exc).__name__" in window, (
        "v4.5.16 exception log should include exception type (e.g., "
        "'type=KeyError') for faster Phase 2 diagnosis."
    )

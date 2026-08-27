"""EVSE-SOLAR-IDLE-DERESERVE-1 — narrow parked-reservation fix.

Anchors D1 / D2 / D4 of docs/planning/PLANNING_evse_solar_idle_dereserve.md
(D3 write-churn latch was removed per Reviewer A: harmful — abdicated
control if a long-idle bay's limit was externally raised — and useless —
the deadband already swallows the idempotent MIN re-write).

Fixtures/harness are reused from test_solar_follow_amps (same MockHass/
MockState + _Harness contract). Import that module first so the sys.modules
shim is installed before we import the SolarFollowController symbols here.

Run with PYTHONDONTWRITEBYTECODE=1 (mutation-anchor discipline; see
feedback_mutation_verification_pycache_staleness).
"""

# Bootstrap the HA mock shim and the SolarFollow harness.
from test_solar_follow_amps import _Harness, _run, LIMIT_A, LIMIT_B  # noqa: F401

from datetime import datetime, timedelta, timezone

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    SolarFollowController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    SOLAR_FOLLOW_MIN_AMPS,
    SOLAR_FOLLOW_PHASES,
    SOLAR_FOLLOW_IDLE_DERESERVE_TICKS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _refresh_power(h, evse_id, power_w, age_s=10):
    """Update a bay's power sensor with a fresh timestamp (so it's non-stale)."""
    ent = f"sensor.{evse_id}_power_minute_average"
    now = datetime.now(timezone.utc)
    st = h.hass._states[ent]
    st.state = str(power_w)
    st.last_updated = now - timedelta(seconds=age_s)
    st.last_reported = now - timedelta(seconds=age_s)


def _refresh_grid(h, grid_w, age_s=30):
    """Refresh the primary grid sensor timestamp so it stays fresh across ticks."""
    from test_solar_follow_amps import PRIMARY

    now = datetime.now(timezone.utc)
    st = h.hass._states[PRIMARY]
    st.state = str(grid_w)
    st.last_updated = now - timedelta(seconds=age_s)
    st.last_reported = now - timedelta(seconds=age_s)


def _set_charging(h, evse_id, charging):
    h.hass.set_state(
        f"switch.{evse_id}",
        "on" if charging else "off",
        attributes={"status": "charging" if charging else "idle"},
    )


# ---------------------------------------------------------------------------
# INV-IDLE-1 — de-reserve, and it moves the number (discriminating).
# ---------------------------------------------------------------------------


def test_idle_bay_dereserved_after_threshold_and_lifts_drawing_allocation():
    """Two bays: A drawing, B idle for >= threshold ticks.

    Discriminator: compute a_per_drawing under the FIXED code vs. the
    (hypothetical) unfixed code (parked_w still counts B). The two numbers
    differ by SOLAR_FOLLOW_MIN_AMPS per de-reserved bay — assert BOTH so a
    silent revert changes the assertion, not just the pass/fail.

    Anchors D2 `parked_w = n_reserved * MIN * 240 * PHASES` where
    `n_reserved = n_eligible - n_drawing - len(long_idle)`.
    """
    # Grid = -4000 W; A drawing 1000 W → S ≈ 5000 W. A held at 48 A so
    # every tick is a DOWN-step (immediate write, no up-gate). Fixed target
    # (n_reserved=0): a_total = 5000//240 = 20. Unfixed target
    # (n_reserved=1): a_total = (5000-1440)//240 = 14. The two numbers
    # differ, so the test discriminates.
    h = _Harness(
        active=("garage_a", "garage_b"),
        grid_w=-4000.0,
        a_charging=True, b_charging=False,
        a_current=48, b_current=48,
        a_power=1000, b_power=0,
        power_age_s_a=10, power_age_s_b=10,
    )
    h.sf._original_amps["garage_a"] = 48.0

    # Run threshold-1 ticks; B is idle but not yet long-idle. Both
    # allocations agree on 14 A during this phase (n_reserved=1).
    for _ in range(SOLAR_FOLLOW_IDLE_DERESERVE_TICKS - 1):
        _refresh_grid(h, -4000.0)
        _refresh_power(h, "garage_a", 1000)
        _refresh_power(h, "garage_b", 0)
        _run(h.sf._tick())
    assert h.written("garage_a")[-1] == 14
    # Not long-idle yet.
    assert "garage_b" not in {
        eid for eid in h.sf._notdraw_ticks
        if h.sf._notdraw_ticks[eid] >= SOLAR_FOLLOW_IDLE_DERESERVE_TICKS
    }

    # One more tick — B crosses the threshold. Fixed path drops the
    # reservation → A's write jumps from 14 to 20.
    _refresh_grid(h, -4000.0)
    _refresh_power(h, "garage_a", 1000)
    _refresh_power(h, "garage_b", 0)
    _run(h.sf._tick())

    assert h.sf._notdraw_ticks["garage_b"] >= SOLAR_FOLLOW_IDLE_DERESERVE_TICKS

    # Independent oracle for the two allocations (S = -grid + A add-back).
    s_eligible = 4000.0 + 1000.0
    a_fixed_expected = int(max(s_eligible - 0, 0) // (240 * SOLAR_FOLLOW_PHASES))
    a_unfixed_expected = int(
        max(s_eligible - SOLAR_FOLLOW_MIN_AMPS * 240 * SOLAR_FOLLOW_PHASES, 0)
        // (240 * SOLAR_FOLLOW_PHASES)
    )
    assert a_fixed_expected > a_unfixed_expected, (
        a_fixed_expected, a_unfixed_expected,
    )
    assert h.written("garage_a")[-1] == a_fixed_expected
    assert h.written("garage_a")[-1] > a_unfixed_expected


# ---------------------------------------------------------------------------
# INV-IDLE-2 — counter resets on resume.
# ---------------------------------------------------------------------------


def test_counter_resets_when_idle_bay_resumes_drawing():
    """A idle to threshold; then A starts drawing → counter clears → re-reserved."""
    h = _Harness(
        active=("garage_a", "garage_b"),
        grid_w=-2000.0,
        a_charging=False, b_charging=True,
        a_current=48, b_current=48,
        a_power=0, b_power=5000,
    )
    h.sf._original_amps["garage_b"] = 48.0
    for _ in range(SOLAR_FOLLOW_IDLE_DERESERVE_TICKS):
        _refresh_grid(h, -2000.0)
        _refresh_power(h, "garage_a", 0)
        _refresh_power(h, "garage_b", 5000)
        _run(h.sf._tick())
    assert h.sf._notdraw_ticks.get("garage_a", 0) >= SOLAR_FOLLOW_IDLE_DERESERVE_TICKS

    # A resumes drawing.
    _set_charging(h, "garage_a", True)
    _refresh_grid(h, -2000.0)
    _refresh_power(h, "garage_a", 5000)
    _refresh_power(h, "garage_b", 5000)
    _run(h.sf._tick())
    # Counter cleared for A.
    assert h.sf._notdraw_ticks.get("garage_a", 0) == 0


# ---------------------------------------------------------------------------
# INV-IDLE-3 — no membership change on the idle path (byte-identity intent).
# ---------------------------------------------------------------------------


def test_idle_dereserve_does_not_discard_or_turn_off():
    """A long-idle bay stays in _excess_solar_active and issues no switch.turn_off."""
    h = _Harness(
        active=("garage_a", "garage_b"),
        grid_w=-2000.0,
        a_charging=True, b_charging=False,
        a_current=48, b_current=48,
        a_power=5000, b_power=0,
    )
    h.sf._original_amps["garage_a"] = 48.0
    for _ in range(SOLAR_FOLLOW_IDLE_DERESERVE_TICKS + 2):
        _refresh_grid(h, -2000.0)
        _refresh_power(h, "garage_a", 5000)
        _refresh_power(h, "garage_b", 0)
        _run(h.sf._tick())
    # Membership preserved.
    assert "garage_b" in h.ev._excess_solar_active
    # No switch.turn_off issued to either bay.
    for call in h.writes.calls:
        assert not (
            call[0] == "switch" and call[1] == "turn_off"
        ), f"unexpected turn_off: {call}"


# ---------------------------------------------------------------------------
# Kill-switch — huge threshold reverts to today's parked_w.
# ---------------------------------------------------------------------------


def test_kill_switch_huge_threshold_reverts_to_pre_cycle_behavior():
    """With SOLAR_FOLLOW_IDLE_DERESERVE_TICKS set enormously large, no bay
    ever crosses; parked_w is identical to today's formula and A's amps
    match the unfixed baseline exactly."""
    # NOTE: other tests in the suite re-exec the energy_pool module and
    # replace sys.modules[...], so the module we import at file scope may
    # not be the module the SolarFollowController *class* actually resolves
    # its globals against. Patch the class's live module directly.
    import sys
    h = _Harness(
        active=("garage_a", "garage_b"),
        grid_w=-4000.0,
        a_charging=True, b_charging=False,
        a_current=48, b_current=48,
        a_power=1000, b_power=0,
    )
    # Suite pollution: other tests re-exec energy_pool and replace
    # sys.modules; the SolarFollowController._tick closure still resolves
    # SOLAR_FOLLOW_IDLE_DERESERVE_TICKS from the ORIGINAL module's
    # __dict__ (its function __globals__). Patch that dict directly.
    tick_globals = type(h.sf)._tick.__globals__
    original = tick_globals["SOLAR_FOLLOW_IDLE_DERESERVE_TICKS"]
    tick_globals["SOLAR_FOLLOW_IDLE_DERESERVE_TICKS"] = 10_000_000
    try:
        h.sf._original_amps["garage_a"] = 48.0
        for _ in range(20):  # well past the real threshold of 10
            _refresh_grid(h, -4000.0)
            _refresh_power(h, "garage_a", 1000)
            _refresh_power(h, "garage_b", 0)
            _run(h.sf._tick())

        # No long_idle set formed → n_reserved unchanged from today.
        long_idle = {
            eid for eid, n in h.sf._notdraw_ticks.items() if n >= 10_000_000
        }
        assert long_idle == set()

        # Reproduce the pre-cycle formula (n_reserved=1) → 14 A.
        s_eligible = 4000.0 + 1000.0
        parked_pre = 1 * SOLAR_FOLLOW_MIN_AMPS * 240 * SOLAR_FOLLOW_PHASES
        a_pre = int(max(s_eligible - parked_pre, 0) // (240 * SOLAR_FOLLOW_PHASES))
        assert h.written("garage_a")[-1] == a_pre
    finally:
        tick_globals["SOLAR_FOLLOW_IDLE_DERESERVE_TICKS"] = original


# ---------------------------------------------------------------------------
# stale_power bays are NOT counted as idle (dead sensor ≠ finished car).
# ---------------------------------------------------------------------------


def test_stale_power_bay_is_not_dereserved():
    """A charging bay whose power sensor is stale is HELD, and its idle
    counter never increments — its reservation is preserved."""
    h = _Harness(
        active=("garage_a", "garage_b"),
        grid_w=-2000.0,
        a_charging=True, b_charging=True,
        a_current=48, b_current=48,
        a_power=5000, b_power=5000,
        power_age_s_a=10, power_age_s_b=10,
    )
    h.sf._original_amps["garage_a"] = 48.0

    # Make B's power sensor stale for many ticks. It goes to stale_power
    # for the first few ticks (until SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS
    # drops the stale hold and it becomes non-drawing). Even then, only
    # THAT tick begins the idle counter — long before SOLAR_FOLLOW_IDLE_DERESERVE_TICKS.
    for _ in range(3):  # keep well within STALE_HOLD_MAX_TICKS
        _refresh_grid(h, -2000.0)
        _refresh_power(h, "garage_a", 5000, age_s=10)
        _refresh_power(h, "garage_b", 5000, age_s=999)  # stale
        _run(h.sf._tick())

    # Idle counter for B is 0 while it's in stale_power.
    assert h.sf._notdraw_ticks.get("garage_b", 0) == 0


# ---------------------------------------------------------------------------
# B-MED-2 — claim-loss clears the idle counter (re-eligibility fresh window).
# ---------------------------------------------------------------------------


def test_reclaimed_bay_gets_fresh_idle_observation_window():
    """A bay driven past the idle threshold, then removed from
    _excess_solar_active (claim loss — e.g. a peak-drop de-claim), then
    re-added, MUST start its counter from 0 so it gets the full
    SOLAR_FOLLOW_IDLE_DERESERVE_TICKS observation window before being
    de-reserved again. Otherwise a re-plugged car would be de-reserved
    instantly, starved before it can ramp — the exact hazard the
    knob's comment warns against.

    Anchors the claim-loss prune inside `_notdraw_ticks` maintenance.
    Mutation-anchor: neuter the `k not in _active_now` clause of the
    prune → this test goes RED (counter stays at threshold, bay
    arrives instantly long-idle on tick 1 after re-claim).
    """
    h = _Harness(
        active=("garage_a", "garage_b"),
        grid_w=-2000.0,
        a_charging=True, b_charging=False,
        a_current=48, b_current=48,
        a_power=5000, b_power=0,
    )
    h.sf._original_amps["garage_a"] = 48.0

    # Drive B past the threshold — it is now long-idle.
    for _ in range(SOLAR_FOLLOW_IDLE_DERESERVE_TICKS + 1):
        _refresh_grid(h, -2000.0)
        _refresh_power(h, "garage_a", 5000)
        _refresh_power(h, "garage_b", 0)
        _run(h.sf._tick())
    assert h.sf._notdraw_ticks.get("garage_b", 0) >= SOLAR_FOLLOW_IDLE_DERESERVE_TICKS

    # Claim loss: B leaves _excess_solar_active. To EXCLUSIVELY exercise
    # the early-safe-site claim-loss prune (and not the downstream
    # eligible-set prune that runs later in _tick), we also force the tick
    # to take an early-return path — mark the grid sensor unavailable so
    # `_read_grid_watts` returns None and _tick returns via _handle_blind.
    # Under the fix, the early prune runs BEFORE the grid read, so the
    # counter is cleared. Under a mutation that drops the claim-loss
    # clause from the early prune, the counter persists through this
    # tick (there's no later eligible-set prune, since we early-return).
    h.ev._excess_solar_active.discard("garage_b")
    primary_state = h.hass._states["sensor.mains_test_primary"]
    primary_state.state = "unavailable"
    _refresh_power(h, "garage_a", 5000)
    _refresh_power(h, "garage_b", 0)
    _run(h.sf._tick())
    # Counter cleared by the CLAIM-LOSS prune at the early-safe site.
    assert h.sf._notdraw_ticks.get("garage_b", 0) == 0

    # Grid recovers; B is re-claimed. On this first tick back, it must
    # NOT already be long-idle (counter starts at 0 → 1, well below
    # threshold). This is the ramp-up-hazard guard.
    h.ev._excess_solar_active.add("garage_b")
    _refresh_grid(h, -2000.0)
    _refresh_power(h, "garage_a", 5000)
    _refresh_power(h, "garage_b", 0)
    _run(h.sf._tick())
    assert h.sf._notdraw_ticks.get("garage_b", 0) == 1
    assert h.sf._notdraw_ticks["garage_b"] < SOLAR_FOLLOW_IDLE_DERESERVE_TICKS

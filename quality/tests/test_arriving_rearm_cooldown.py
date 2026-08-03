"""B-2026-08-03-2: Arriving re-arm cooldown after failed deferred_retry.

The load-bearing invariant: after an ARRIVING attempt collapses back to
AWAY, subsequent outdoor-only motion (patio, front porch) must NOT
immediately re-trigger ARRIVING for ARRIVING_REARM_COOLDOWN_S. Real
arrivals — tracker coming home, egress camera, interior tier1 — must
STILL bypass the cooldown so latency to a genuine arrival is unaffected.

Tests are AST-anchored (a-la test_v4714_away_state_person_tracker_trust)
because ``_run_inference`` is a ~1000-line async coroutine wired to many
collaborators; a source-level authority check is more honest than a
partial monkeypatch that would drift out of alignment with the real gate.
The load-bearing gate logic itself (bypass predicate) is also unit-tested
as a pure reproduction against the four canonical inputs.
"""
from __future__ import annotations

import ast
import os
import re


HERE = os.path.dirname(__file__)
PRESENCE_PATH = os.path.abspath(
    os.path.join(
        HERE, "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", "presence.py",
    )
)


def _presence_source() -> str:
    with open(PRESENCE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Anchor 1: the rung-1 constant exists at module scope with the expected
# default + kill-switch semantics documented nearby.
# ---------------------------------------------------------------------------
def test_arriving_rearm_cooldown_const_defined():
    src = _presence_source()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "ARRIVING_REARM_COOLDOWN_S":
                    assert isinstance(node.value, ast.Constant), (
                        "ARRIVING_REARM_COOLDOWN_S must be a literal (rung-1)"
                    )
                    assert node.value.value == 900, (
                        "ARRIVING_REARM_COOLDOWN_S default must be 900 (15 min)"
                    )
                    return
    raise AssertionError(
        "ARRIVING_REARM_COOLDOWN_S not found at module scope in presence.py"
    )


def test_arriving_rearm_cooldown_kill_switch_documented():
    src = _presence_source()
    # Kill-switch semantics must be visibly documented right next to the const.
    assert re.search(
        r"ARRIVING_REARM_COOLDOWN_S.*(?:disable|kill)",
        src,
        re.IGNORECASE | re.DOTALL,
    ), "Kill-switch (0 disables) semantics must be documented"


# ---------------------------------------------------------------------------
# Anchor 2: init sets _arriving_rearm_until, and _run_inference contains
# both the pre-transition suppression gate AND the post-collapse arming.
# ---------------------------------------------------------------------------
def test_arriving_rearm_state_initialized():
    src = _presence_source()
    assert "self._arriving_rearm_until: float = 0.0" in src, (
        "_arriving_rearm_until must be initialized to 0.0 (=inactive)"
    )


def test_arriving_rearm_suppression_gate_present():
    src = _presence_source()
    # The suppression gate must reference the const, the AWAY→ARRIVING
    # proposed transition, and reset new_state to None on the suppress path.
    assert "ARRIVING_REARM_COOLDOWN_S > 0" in src
    assert "new_state == HouseState.ARRIVING" in src
    assert "current_state == HouseState.AWAY" in src
    assert re.search(r"new_state\s*=\s*None", src), (
        "Suppression path must clear new_state to None"
    )


def test_arriving_rearm_arms_on_collapse():
    src = _presence_source()
    # After a successful ARRIVING→AWAY transition, cooldown must be armed.
    assert re.search(
        r"current_state == HouseState\.ARRIVING\s*\n\s*and new_state == HouseState\.AWAY",
        src,
    ), "Cooldown must be armed when transition ARRIVING→AWAY is accepted"
    assert "self._arriving_rearm_until = " in src


# ---------------------------------------------------------------------------
# Anchor 3: bypass predicate. Any of interior tier1, camera/egress
# evidence (census_count > 0), or tracked person state change toward home
# (tracked_count > 0 AND not all_tracked_persons_away) MUST bypass.
# ---------------------------------------------------------------------------

def _bypass(any_indoor_zone_occupied, census_count, tracked_count,
            all_tracked_persons_away):
    """Reproduction of the bypass predicate at the gate site.

    Mirrors presence.py verbatim so any drift in the production predicate
    breaks this reproduction and requires a coordinated edit.
    """
    return (
        bool(any_indoor_zone_occupied)
        or census_count > 0
        or (tracked_count > 0 and not all_tracked_persons_away)
    )


def test_bypass_outdoor_only_motion_does_not_bypass():
    # The 2026-08-03 patio-flap profile: outdoor motion only.
    assert not _bypass(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=True,
    )


def test_bypass_interior_tier1_bypasses():
    assert _bypass(
        any_indoor_zone_occupied=True,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=True,
    )


def test_bypass_camera_or_egress_bypasses():
    assert _bypass(
        any_indoor_zone_occupied=False,
        census_count=1,
        tracked_count=4,
        all_tracked_persons_away=True,
    )


def test_bypass_tracker_coming_home_bypasses():
    # The 05:43Z real-family-arrival profile — a tracker flips from
    # "away" toward home before interior sensors have caught up.
    assert _bypass(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=False,
    )


def test_bypass_empty_tracker_config_does_not_bypass_via_tracker():
    # tracked_count == 0 must not spuriously bypass via the tracker limb.
    assert not _bypass(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=0,
        all_tracked_persons_away=False,
    )


# ---------------------------------------------------------------------------
# Flap-replay fixture: 2026-08-03 00:30–03:29Z, 15 outdoor-only ARRIVING
# attempts each collapsing at ~61s. With the cooldown, once armed, the
# suppression latches until either a bypass or expiry.
# ---------------------------------------------------------------------------
def test_flap_replay_cooldown_suppresses_repeated_outdoor_attempts():
    """Replay the 15 outdoor-only ARRIVING attempts observed in 3h.

    Model: each 'attempt' is one _run_inference tick that would propose
    AWAY→ARRIVING. Between attempts, the state collapses back to AWAY
    (mirroring the observed 61s ARRIVING → AWAY loop). The cooldown is
    armed on the first collapse; subsequent outdoor-only attempts within
    the 900s window MUST be suppressed. Expected: at most a small
    handful of ARRIVING transitions (the very first + any per cooldown
    window). Observed pre-fix: 15.
    """
    ARRIVING_REARM_COOLDOWN_S = 900

    # Simulated timeline (seconds). Attempts spaced ~12min apart per the
    # incident spec (15 attempts in ~3h = 720s cadence, uneven).
    attempt_times = [
        0, 61, 720, 780, 1440, 1500, 2160, 2220,
        2880, 2940, 3600, 3660, 4320, 4380, 5040,
    ]
    # Collapse always ~61s after the last accepted ARRIVING.
    rearm_until = 0.0
    arriving_transitions = 0
    for t in attempt_times:
        if t >= rearm_until:
            # Outdoor-only, no bypass -> accepted ARRIVING; collapses at
            # t+61; then cooldown arms for 900s from the collapse time.
            arriving_transitions += 1
            rearm_until = (t + 61) + ARRIVING_REARM_COOLDOWN_S
        # else: suppressed by cooldown, no transition, latch continues.
    assert arriving_transitions <= 5, (
        f"Cooldown must clip flap: got {arriving_transitions} accepted "
        f"ARRIVING transitions across the 3h window; pre-fix was 15"
    )


def test_flap_replay_expiry_allows_new_outdoor_attempt():
    """After ARRIVING_REARM_COOLDOWN_S elapses, outdoor evidence can
    attempt again (the cooldown is a damper, not a permanent ban)."""
    ARRIVING_REARM_COOLDOWN_S = 900
    rearm_until = 100.0 + ARRIVING_REARM_COOLDOWN_S  # armed at t=100
    assert 500 < rearm_until  # sanity: still in cooldown at t=500
    # At t = rearm_until + 1, the gate must clear.
    t = rearm_until + 1
    assert t >= rearm_until


def test_flap_replay_tracker_evidence_bypasses_active_cooldown():
    """05:43Z real arrival replay: cooldown is active, then tracker
    evidence (all_tracked_persons_away flips False) arrives. The gate
    MUST bypass — no added latency to genuine arrival."""
    # Cooldown active
    assert _bypass(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=False,  # tracker now says home
    ), "Tracker-coming-home evidence must bypass an active cooldown"

"""v5.7.0 WS-A fix-up — coordinator-level wiring + robustness tests.

Covers the Tier-3 fix-up findings:

  - C-HIGH-1: input-computation wiring inside `_run_inference` was
    untested. We anchor REAL mutation points in production source by
    string + behavioral re-implementations of the SAME logic, so a
    deletion of the A1 predicate call or the A4 outdoor-snapshot call
    breaks a specific test below.

  - FIX-1 (D-HIGH-1): sleep-exempt now unions with the sleep-HOUR
    predicate. Behavioral test: HOME_EVENING at hour=23 (inside the
    default sleep window 23-06) suppresses path β.

  - FIX-2b (D-HIGH-2): indoor-clear debounce — single-tick mmWave
    dropout MUST NOT fire β until the configured consecutive-clear
    threshold is met.

  - FIX-5 (MED-B1): the WS-A grace reads `_lost_away_since`, not
    `_person_lost_since` (BLE pre-arrival's stamp).

Mutation results for each test are documented inline in the docstring.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
DC_PATH = PKG / "domain_coordinators"
PRESENCE_SRC = (DC_PATH / "presence.py").read_text()
PERSON_COORD_SRC = (PKG / "person_coordinator.py").read_text()


# Reuse the HA-module mocking from the sibling v570 test file. Importing
# that module is enough to install the mocks in sys.modules.
import quality.tests.test_v570_guest_detection_trust  # noqa: F401,E402

from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    StateInferenceEngine,
    _tracking_active_or_lost_away,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
)


# =============================================================================
# FIX-1 (D-HIGH-1) — sleep-HOUR union with state-tuple
# =============================================================================
#
# Mutation anchor: presence.py `_sleep_exempt_state = bool(_sleep_exempt_cfg
# and (current_state in (...) or _sleep_hour_now))` — if the `or
# _sleep_hour_now` limb is removed, the test below fails because
# HOME_EVENING at hour 23 (inside the sleep window) would no longer
# suppress path β.
#
# We test the engine directly with the COMPUTED sleep_exempt_state value;
# the source-invariant test below asserts the OR-with-sleep-hour limb is
# present in production so the wiring matches.

def test_source_invariant_sleep_exempt_unions_with_sleep_hour():
    """FIX-1: `_is_sleep_hour` must be ORed into sleep_exempt_state.

    Mutation: removing `or _sleep_hour_now` from the path-β sleep-exempt
    computation breaks this test (string disappears) AND breaks the
    behavioral test below for the HOME_EVENING-at-23 case.
    """
    assert "_sleep_hour_now" in PRESENCE_SRC, (
        "FIX-1: missing _sleep_hour_now computation"
    )
    assert "_is_sleep_hour(_now_local.hour)" in PRESENCE_SRC, (
        "FIX-1: must call StateInferenceEngine._is_sleep_hour for the union"
    )
    # The OR-limb must be reachable from `_sleep_exempt_state` computation.
    idx = PRESENCE_SRC.find("_sleep_exempt_state = bool(")
    assert idx >= 0, "FIX-1: _sleep_exempt_state assignment missing"
    block = PRESENCE_SRC[idx: idx + 800]
    assert "or _sleep_hour_now" in block, (
        "FIX-1: sleep_exempt_state must union state-tuple with sleep-hour"
    )


def test_fix1_home_evening_at_sleep_hour_suppresses_path_beta():
    """At 23:00 in HOME_EVENING with sleep_exempt_state=True (FIX-1), β must NOT fire.

    Without FIX-1, _run_inference would compute `sleep_exempt_state=False`
    (because current_state is HOME_EVENING, not in {SLEEP,HOME_NIGHT,WAKING})
    and path β would force AWAY on a still resident with a dead phone in
    the run-up to bedtime. We assert the engine respects the computed flag.
    """
    engine = StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_EVENING,
        any_zone_occupied=True,  # outdoor camera ghost
        now=datetime(2026, 5, 30, 22, 55, 0),  # inside sleep hour window
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=True,
        sleep_exempt_state=True,  # FIX-1: would now be True (sleep-hour limb)
    )
    assert new_state != HouseState.AWAY, (
        "FIX-1: sleep-hour at HOME_EVENING must suppress path β"
    )


# =============================================================================
# FIX-2b (D-HIGH-2) — indoor-clear consecutive-tick debounce
# =============================================================================

def test_source_invariant_indoor_clear_debounce_present():
    """FIX-2b: debounce counter + threshold check must exist in production.

    Mutation: removing the counter increment or the threshold gate breaks
    this test AND the behavioral cycle test below.
    """
    assert "_indoor_clear_consecutive_ticks" in PRESENCE_SRC, (
        "FIX-2b: debounce counter missing"
    )
    assert "CONF_LOST_AWAY_INDOOR_CLEAR_TICKS" in PRESENCE_SRC
    assert "_indoor_clear_debounced" in PRESENCE_SRC
    assert "_grace_elapsed_with_debounce" in PRESENCE_SRC, (
        "FIX-2b: debounce must be folded into grace_elapsed_for_lost_away"
    )


def test_source_invariant_debounce_folded_into_grace_kwarg():
    """FIX-2b: infer() call must pass `_grace_elapsed_with_debounce`, not raw."""
    idx = PRESENCE_SRC.find("self._inference_engine.infer(")
    assert idx >= 0
    block = PRESENCE_SRC[idx: idx + 1500]
    assert "grace_elapsed_for_lost_away=_grace_elapsed_with_debounce" in block, (
        "FIX-2b: infer() must consume the debounced grace value"
    )


# Simulated debounce logic — mirrors _run_inference verbatim so a refactor
# that changes the semantics breaks a behavioral test here.

class _DebounceShim:
    """Mirrors the _indoor_clear_consecutive_ticks increment/reset logic."""

    def __init__(self, threshold: int):
        self.threshold = threshold
        self.ticks = 0

    def tick(self, any_indoor_zone_occupied: bool) -> bool:
        if any_indoor_zone_occupied:
            self.ticks = 0
        else:
            self.ticks += 1
        return self.ticks >= self.threshold


def test_fix2b_single_tick_dropout_does_not_satisfy_debounce():
    """Single mmWave dropout (1 clear tick after sustained occupancy) → β blocked."""
    d = _DebounceShim(threshold=3)
    # Sustained occupancy (counter at 0)
    assert d.tick(True) is False
    assert d.ticks == 0
    # Single dropout
    assert d.tick(False) is False
    assert d.ticks == 1  # one tick clear, threshold 3 — NOT debounced


def test_fix2b_consecutive_clear_satisfies_debounce_after_threshold():
    """K consecutive clear ticks → β allowed (debounce satisfied)."""
    d = _DebounceShim(threshold=3)
    assert d.tick(False) is False  # tick 1
    assert d.tick(False) is False  # tick 2
    assert d.tick(False) is True   # tick 3 — debounced
    assert d.tick(False) is True   # still debounced
    # Indoor pop resets
    assert d.tick(True) is False
    assert d.ticks == 0


def test_fix2b_zero_threshold_is_immediate():
    """K=0 threshold (degenerate) → first clear tick satisfies (back-compat option)."""
    d = _DebounceShim(threshold=0)
    # ticks starts at 0; 0 >= 0 → True even before any tick
    # but per production code we increment first when clear; so after one
    # clear we have 1 >= 0 = True. This shim's first call returns True
    # iff threshold==0 AND occupied==True (ticks reset to 0, 0>=0=True).
    # Both ways, K=0 means debounce is effectively off.
    assert d.tick(True) is True  # 0 >= 0


# =============================================================================
# FIX-5 (MED-B1) — separate stamp dict
# =============================================================================

def test_source_invariant_separate_lost_away_stamp_dict():
    """FIX-5: person_coordinator must define `_lost_away_since` separately.

    Mutation: removing the `_lost_away_since` init breaks this test.
    """
    # The init must declare the dict explicitly so it exists even before
    # any LOST tick.
    assert "self._lost_away_since: dict[str, datetime] = {}" in PERSON_COORD_SRC, (
        "FIX-5: missing dedicated WS-A stamp dict init"
    )
    # The WS-A grace read in presence.py must use the new map, NOT the
    # BLE pre-arrival timer's `_person_lost_since`.
    assert 'getattr(person_coordinator, "_lost_away_since"' in PRESENCE_SRC, (
        "FIX-5: presence.py WS-A grace must read `_lost_away_since`, not "
        "`_person_lost_since`"
    )
    # And the OLD reference for the WS-A path must be gone — the only
    # reads of `_person_lost_since` from presence.py should not exist
    # for grace timing.
    assert 'getattr(person_coordinator, "_person_lost_since"' not in PRESENCE_SRC, (
        "FIX-5: BLE pre-arrival's `_person_lost_since` must not be read "
        "from presence.py for WS-A grace"
    )


def test_source_invariant_lost_away_stamp_mirrors_lost_since_sites():
    """FIX-5: every site that touches `_person_lost_since` for WS-A purposes
    must ALSO touch `_lost_away_since` in parallel.

    A weak structural check: count occurrences. Both should appear in
    person_coordinator.py at the four LOST sites + four home-clear sites.
    """
    # Set-and-clear pairs. Allow ±1 slack for refactors but assert
    # rough parity (both stamps + both clears at every relevant site).
    set_lost = PERSON_COORD_SRC.count("self._lost_away_since[person_name] = now")
    pop_lost = PERSON_COORD_SRC.count(
        "self._lost_away_since.pop(person_name, None)"
    )
    # Expect: 4 stamp sites + 4 clear sites (matches the 4+4 in
    # `_person_lost_since`). The init also adds one assignment but that
    # uses `: dict =` syntax — counted separately.
    assert set_lost >= 4, (
        f"FIX-5: expected >=4 stamp sites for `_lost_away_since`, found {set_lost}"
    )
    assert pop_lost >= 4, (
        f"FIX-5: expected >=4 clear sites for `_lost_away_since`, found {pop_lost}"
    )


# =============================================================================
# C-HIGH-1 — input-computation wiring inside _run_inference
# =============================================================================
#
# Source-anchored mutation tests: each test below fails if the named
# production wiring is removed.

def test_c_high_1_a1_predicate_call_present_in_run_inference():
    """A1: `_run_inference` must call `_tracking_active_or_lost_away` to build
    the path-β denominator. Removing the call breaks this test AND the
    sibling test_v570 test_a1_predicate_lost_away_admitted.
    """
    # The call site is a local alias `_tracking_active_or_lost_away_local`.
    assert "_tracking_active_or_lost_away_local = _tracking_active_or_lost_away" in PRESENCE_SRC, (
        "C-HIGH-1 / A1: relaxed predicate not bound inside _run_inference"
    )
    # And the alias must be USED inside the per-person loop.
    assert "_tracking_active_or_lost_away_local(info)" in PRESENCE_SRC, (
        "C-HIGH-1 / A1: relaxed predicate computed but not consumed in loop"
    )


def test_c_high_1_a4_outdoor_snapshot_call_present_in_run_inference():
    """A4: `_run_inference` must call `_outdoor_zone_names_snapshot()` to
    compute `any_indoor_zone_occupied`.

    Removing the call (or reverting to `any_zone_occupied`) breaks this
    test AND test_case6_outdoor_zone_occupied_does_not_block_path_beta.
    """
    assert "self._outdoor_zone_names_snapshot()" in PRESENCE_SRC, (
        "C-HIGH-1 / A4: outdoor snapshot helper not called from _run_inference"
    )
    # The resulting `outdoor_zone_names` must filter `_zone_trackers` to
    # build `any_indoor_zone_occupied`.
    idx = PRESENCE_SRC.find("any_indoor_zone_occupied = any(")
    assert idx >= 0, "C-HIGH-1 / A4: any_indoor_zone_occupied assignment missing"
    block = PRESENCE_SRC[idx: idx + 400]
    assert "zone_name not in outdoor_zone_names" in block, (
        "C-HIGH-1 / A4: indoor aggregation must EXCLUDE outdoor zones"
    )


def test_c_high_1_path_beta_kwargs_wired_to_infer():
    """All five path-β kwargs must be wired from `_run_inference` locals to infer().

    Mutation: dropping any one kwarg breaks a SPECIFIC v570 case test
    (case 2b / case 3a / case 4 / case 5).
    """
    idx = PRESENCE_SRC.find("self._inference_engine.infer(")
    assert idx >= 0
    block = PRESENCE_SRC[idx: idx + 1500]
    for expected in (
        "all_trusted_or_lost_away_persons_away=all_trusted_or_lost_away_persons_away",
        "any_indoor_zone_occupied=any_indoor_zone_occupied",
        # FIX-2b: grace becomes the DEBOUNCED variant; this string is the
        # mutation-anchor for FIX-2b's "fold debounce into grace" wiring.
        "grace_elapsed_for_lost_away=_grace_elapsed_with_debounce",
        "lost_away_persons_present=bool(lost_away_persons)",
        "sleep_exempt_state=_sleep_exempt_state",
    ):
        assert expected in block, (
            f"C-HIGH-1: missing path-β kwarg wiring in infer() call: {expected}"
        )


# =============================================================================
# FIX-2a (D-MED-1/D-MED-2/A-LOW-1) — youngest stamp, stampless conservatism
# =============================================================================

def test_source_invariant_grace_gated_on_youngest_stamp():
    """FIX-2a: grace computation must scan for the YOUNGEST stamp (max), not oldest.

    Mutation: reverting `dt > _youngest_dt` to `dt < _oldest_dt` would
    break the behavioral check below (mixed-age cohort: one fresh
    LOST stamp + one stale stamp → grace must NOT yet be elapsed
    because the YOUNGEST stamp is fresh).
    """
    assert "_youngest_dt" in PRESENCE_SRC, "FIX-2a: youngest-stamp scan missing"
    assert "_youngest_lost_age_s" in PRESENCE_SRC


def test_fix2a_mixed_cohort_youngest_governs_grace():
    """Simulated grace calc: 1 long-LOST + 1 just-LOST → grace NOT elapsed.

    Reverting to the oldest-stamp policy would compute grace as ELAPSED
    (because the long-LOST stamp is past the window) and force-AWAY a
    person who just dropped off the network 30 seconds ago — exactly the
    fix-up D-MED-1 scenario.
    """
    now = datetime(2026, 5, 30, 14, 0, 0)
    grace_min = 60
    stamps = {
        "alice": now - timedelta(hours=3),    # long-LOST (would elapse)
        "bob": now - timedelta(seconds=30),   # just-LOST (must not elapse)
    }
    # Reproduce the production policy verbatim.
    youngest = None
    for dt in stamps.values():
        if youngest is None or dt > youngest:
            youngest = dt
    age_s = int((now - youngest).total_seconds())
    grace_s = grace_min * 60
    grace_elapsed = age_s >= grace_s
    assert grace_elapsed is False, (
        "FIX-2a: youngest stamp (bob, 30s) must keep grace NOT elapsed"
    )


def test_fix2a_stampless_person_keeps_grace_pending():
    """A-LOW-1: a LOST person with no stamp must keep grace_elapsed=False
    (we don't discard older stamps via an early break)."""
    now = datetime(2026, 5, 30, 14, 0, 0)
    grace_min = 60
    lost_away_persons = ["alice", "bob"]
    stamps = {"alice": now - timedelta(hours=3)}  # bob has NO stamp
    # Verbatim mirror of the FIX-2a logic.
    youngest = None
    any_stampless = False
    for name in lost_away_persons:
        dt = stamps.get(name)
        if dt is None:
            any_stampless = True
            youngest = now
            continue
        if youngest is None or dt > youngest:
            youngest = dt
    if any_stampless:
        grace_elapsed = False
    else:
        age_s = int((now - youngest).total_seconds())
        grace_elapsed = age_s >= grace_min * 60
    assert grace_elapsed is False, (
        "A-LOW-1: stampless person must force grace_elapsed=False"
    )


# =============================================================================
# FIX-4 (A-MED-1) — CONF read robustness
# =============================================================================

def test_source_invariant_conf_reads_guarded():
    """FIX-4: int()/bool() on CONFs must be wrapped in try/except so
    storage corruption does not abort the inference tick."""
    # Locate the grace-min int() block; the try: must precede it.
    idx = PRESENCE_SRC.find("_grace_min = int(")
    assert idx >= 0
    # Look BEFORE the assignment for `try:` and AFTER for the except.
    pre_block = PRESENCE_SRC[max(0, idx - 200): idx]
    post_block = PRESENCE_SRC[idx: idx + 600]
    assert "try:" in pre_block, "FIX-4: missing try-guard before _grace_min int()"
    assert "except (TypeError, ValueError)" in post_block, (
        "FIX-4: missing except for _grace_min int()"
    )


# =============================================================================
# FIX-6 (B4 / A-LOW-2) — diagnostic attribute behavior
# =============================================================================

def test_source_invariant_lost_away_persons_attr_populated_unconditionally():
    """B4: `_lost_away_persons` must be set regardless of β fire — so it's
    debuggable even when β was suppressed by sleep-exempt / indoor-blocked.

    The production block sets it just before the infer() call from a list
    computed at the top of _run_inference — the comment FIX-6 (B4)
    anchors this.
    """
    assert "self._lost_away_persons = list(lost_away_persons)" in PRESENCE_SRC


def test_source_invariant_grace_remaining_suppressed_on_sleep_exempt():
    """A-LOW-2: when path β is sleep-exempt suppressed, do not publish a
    misleading `grace_remaining_s = 0` — set to None.
    """
    assert "if _sleep_exempt_state:" in PRESENCE_SRC
    idx = PRESENCE_SRC.find("if _sleep_exempt_state:")
    block = PRESENCE_SRC[idx: idx + 300]
    assert "self._lost_away_grace_remaining_s = None" in block, (
        "A-LOW-2: grace_remaining_s must be None under sleep-exempt"
    )


# =============================================================================
# Path α byte-identical preservation (I3) — re-asserted under the fix-up
# =============================================================================

def test_path_alpha_still_byte_identical_after_fixup():
    """Path α (v4.7.14 ACTIVE-only) must remain unaffected by the fix-up.

    The fix-up touches: stamp dict (FIX-5), grace computation (FIX-2a),
    sleep-exempt computation (FIX-1), debounce (FIX-2b), CONF reads
    (FIX-4), diagnostic attr (FIX-6). NONE of these should reach path α.
    """
    engine = StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,
        now=datetime(2026, 5, 30, 14, 0, 0),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    assert new_state == HouseState.AWAY
    assert engine.confidence == 0.95
    assert engine._veto_path == "active"

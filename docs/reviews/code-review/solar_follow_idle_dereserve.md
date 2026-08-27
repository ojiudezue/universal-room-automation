# Code Review — EVSE-SOLAR-IDLE-DERESERVE-1 (Tier 2, 2 framing-disjoint + fix-up)

Branch: feature/solar-follow-idle-dereserve @ 896e71a4a (off develop). Reviewers: A (correctness/lifecycle), B (test-authority via mutation).
**Verdict: SHIP after fix-up.**

## The change
Marginal-benefit-narrowed replacement for the parked Tier-3 discard-and-move stop-conditions plan. A bay
idle (~0 draw) for >= SOLAR_FOLLOW_IDLE_DERESERVE_TICKS (10) stops counting in the solar-follow parked
floor (energy_pool.py parked_w), so a charging sibling gets the full surplus (~1.44-2.88 kW it was losing
to a finished/absent bay). The bay STAYS in _excess_solar_active — no discard, no oscillator, no consumer
ripple. In-memory counter; conservative on restart.

## Reviews
- **A (correctness/lifecycle): FIX-REQUIRED** — core CLEAN (parked_w truth-tabled, counter lifecycle
  INV-IDLE-1/2/3 PASS, kill-switch byte-identical). All findings on D3 (the write-churn latch): A-HIGH-1
  (latch abdicates control — an externally-raised limit on a latched idle bay never corrected), A-MED-1
  (counters survive de/re-claim), A-MED-2 (stale exemption bounded, comment overclaims), A-LOW-3 (D3 buys
  ~nothing — deadband already prevents churn).
- **B (test-authority): SHIP** — 5 load-bearing sites mutation-anchored; the 14->20 discriminator genuine
  (both numbers real, degeneracy-guarded); INV-IDLE-3 byte-identity independently verified; kill-switch
  anchor load-bearing; zero new failures. Findings: B-MED-1 (D3 untested), B-MED-2 (re-eligibility prune
  untested).

## Fix-up (896e71a4a) — resolution was a SIMPLIFICATION
- **DELETED D3 entirely** (`_long_idle_written` latch + skip + set + clear + discard). Resolves A-HIGH-1,
  A-LOW-2/3, B-MED-1, B-LOW-2. The deadband already prevents the churn D3 targeted; A proved D3 fires
  ~never on the happy path and is harmful when it does. grep-clean.
- **Claim-loss counter clear** at energy_pool.py:4055-4067 (before the early returns) — a re-claimed bay
  gets a fresh 10-tick observation. New test test_reclaimed_bay_gets_fresh_idle_observation_window,
  mutation-anchored (RED on neuter: "assert 11 == 0"). Resolves A-MED-1, B-MED-2.
- **Comments**: stale exemption bounded to ~STALE_HOLD_MAX_TICKS+IDLE_DERESERVE_TICKS (A-MED-2); kill-switch
  never <= 0 (A-LOW-1).

## Orchestrator independent verification (before ship)
- D3 grep-clean across the component.
- Claim-leg byte-identity re-confirmed: 4 hunks at 3704/3764/4049/4220, none intersect 1584-1687.
- Re-ran the parked_w mutation (drop `- len(long_idle)`) by hand -> test_idle_bay_dereserved... RED
  (assert 14 == 20); restored clean.
- Pre-deploy name-diff: the only failures are the pre-existing evse_drain_precedence wall-clock/
  order-pollution family (SUITE-ORDER-POLLUTION-1); zero solar_follow/idle_dereserve failures.

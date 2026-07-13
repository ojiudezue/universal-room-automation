# Tier 3 Review — EV charge-start dead-band cycle

**Build:** `93e8dd05` · **Fix-up:** `853827b0` · **Reviews:** 4 framing-disjoint (A/B/C/D, parallel) + focused completeness re-pass (E) · **Date:** 2026-07-12/13
**Plan:** `docs/planning/PLANNING_ev_charge_start_deadband.md` · **Baseline tag:** `pre-review-ev-deadband`

**Invariant (INV-EV-DEADBAND):** during off_peak, once the battery is at/above its planned floor F and not discharging beyond noise, no URA gate may keep an EV charging device (L2 EVSE or designated L1 plug) off >1 decision cycle — absent grid-charge/breaker, load-shed, grid-cap, operator-off. Symmetric duty: no over-release (EV must not drain protected battery charge, any period).

## Summary statistics

| Severity | Found | Fixed | Deferred (tracked) |
|---|---:|---:|---:|
| CRITICAL | 0 | — | — |
| HIGH | 8 (A:1, B:3, C:3, D:2 introduced/pre-existing overlap w/ A+B; D-HIGH-3 distinct) | 7 in `853827b0` | 1 (D-HIGH-3, follow-up cycle) |
| MED | 7 (A:2, B:3, C:1, E:1) | 5 | 2 (B-M2 accepted-with-period-gate; E-MED-1 follow-up) |
| LOW | 8 | 3 | 5 (documented, display/defensive only) |

All four initial reviews returned **FIX-FIRST**; Pass E on the fix-up returned **SHIP**.

## The convergent findings (framing disjointness proof)

1. **Floor re-derivation blindness (A-HIGH-1 = B-H3 = D-HIGH-2).** The build's accessor mirrored only the fallback drain-target path; the emitter can park HIGHER (inclement partial_hold clamp `energy_battery.py:3145-3146`; arbitrage/attain `peak_buffer_target`). Repro: partial_hold night parks battery 45–60, F said 22 → no release leg reachable → the exact dead band the cycle exists to close, re-created. **Fixed:** floor now sourced from the emitter's authoritative last commanded reserve — new `_last_reserve_level` stamped in `_result()` (the single chokepoint all decision branches return through, same value commanded to Enphase), exposed via `current_park_floor()`, composed in module-level `compose_release_floor(battery, tou_period)` consumed by BOTH energy.py drain call sites.
2. **Period-blind sticky (B-H1 = D-HIGH-1, INTRODUCED by build).** F is a night-park concept but the drain check runs every tick all periods; sticky suppressed the drain pause through peak discharge, and `ev_battery_drain_soc=40` + unknown class made the drain rule permanently dead. **Fixed:** F substitution + sticky gated on `off_peak`; other periods = pre-fix static-reserve semantics.
3. **One-sided sticky (B-H2).** Suppressed pause from F+2 down to 0. **Fixed:** banded F−2 ≤ SOC ≤ F+2; pause re-arms below the band.
4. **Call-site composition had ZERO test authority (C-HIGH-1/2/3, Bug Class #60 stub-mirror).** Tests re-implemented `max()` in-test; C proved 3 of the builder's claimed mutation anchors false (GREEN mutations at both call sites + the plug solar kwarg). **Fixed:** composition extracted into `compose_release_floor` (production call sites are single-line consumers); 12-row mutation table all RED post-fix-up (see below). Disclosed limitation: `energy.py` itself is unimportable in the test harness (HA-stub gap), so call-site authority is via the extracted-helper construction — a coordinator-tick harness is a filed follow-up.

## Mutation table (post-fix-up, all RED, restore verified byte-identical)

12 sites: EV/plug call-site floor revert, plug solar-kwarg drop, EV/plug release +2→+0, compose park-neuter, compose always-offpeak, EV/plug sticky off_peak-gate drop, EV/plug sticky band one-siding, park-floor accessor fallthrough. Each anchored by a NAMED test in `quality/tests/test_energy_pool_drain_release.py` (43 tests). **Orchestrator independently re-ran the park-neuter mutation:** 2 named tests RED (`test_park_floor_returns_last_commanded_reserve`, `test_park_floor_captures_arbitrage_peak_buffer`), restore clean, 43/43 green.

## Pass E (completeness on the fix-up's new surface) — SHIP

- All 16 `_result()` sites enumerated: every reachable branch emits `reserve_level` except grid-disconnect BACKUP (E-LOW-1, fails safe both directions).
- **Zero-tick staleness:** `determine_mode` runs before both drain dispatches in the same cycle (incl. the startup cycle at energy.py:780) — no restart blindness window.
- Period contract: only `peak|mid_peak|off_peak`; unknown → static+no-sticky (pre-fix fallthrough).
- Arbitrage park 80 during off_peak grid-charge: release at SOC≤82 is the *intended* cheap-grid behavior; battery defended by commanded reserve; not over-release.
- Old accessor has zero remaining decision consumers (fallback + display only).

## Deferred / follow-ups (tracked)

- **D-HIGH-3 (pre-existing, own cycle):** three pause sets (`_paused_by_us`, `_paused_by_fill_priority`, `_paused_by_grid_cap`) have their ONLY release path behind a config toggle; toggle-off while paused pins the device across restarts (DB restore re-adds ≤10h). One toggle flip defeats this cycle's promise. Repro in Review D output.
- **E-MED-1 (pre-existing):** EVSE-battery-hold overlay (energy.py:2614) parks reserve outside `_result()` → `current_park_floor()` under-reports during multi-EVSE holds (starvation direction, self-clears).
- Coordinator-tick test harness (unblocks direct energy.py import in tests) — closes the C-HIGH-1 compensating-construction gap end-to-end.
- E-LOW-1 (backup-mode reserve_level), E-LOW-2 (`or`-chaining on display attr; falsy-0), A-LOW-3 (divergent failure semantics documented).

## Bug-class notes

- Bug Class **#53** recurrence: the cycle reconciling two floors initially missed the third (emitter park values) — caught only because framings A, B, D attacked it from arithmetic, integration, and invariant-falsification angles respectively. The durable fix pattern: **never re-derive an emitter's value in parallel; read the emitter's actual emission.**
- Bug Class **#60** recurrence (4th consecutive cycle with a test-authority HIGH): builder-authored tests mirrored the composition in-test and *claimed* mutation anchoring in docstrings that Review C demonstrated false. Recommendation: builders must RUN their claimed mutations before handoff (add to ura-builder protocol).
- B-M3 honesty note: "byte-identical at excellent class" acceptance criterion was false as written (sticky intentionally removes a pre-existing 1-tick flap); plan corrected.

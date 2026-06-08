# Code Review — Day-Boundary-Blind TOU Decision Fix

**Cycle:** summer mid_peak hold gated on peak-ahead + new `peak_ahead_before_offpeak` primitive + `get_next_transition` season-wrap hardening
**Tier:** Tier 2-DB — **operator-elevated** (regression-prone: battery-strategy decision with battery↔grid↔cost ripple + touches a shared primitive, the TOU engine). Per standing policy (CLAUDE.md, 2026-06-08).
**Baseline tag:** `pre-review-day-boundary-tou` · **Commits:** `64671d1` (build), `816fa31` (fix-up)
**Date:** 2026-06-08

## Framings + verdicts
| Review | Risk axis | Verdict |
|---|---|---|
| A | Correctness + edge cases (helper walk: hour/season/midnight/DST boundaries, SOC None/==reserve, None-engine) | **SHIP** |
| B | Cross-coordinator + precedence + no-flap (reserve-write oscillation, EVSE/arbitrage seam, get_next_transition consumers) | **SHIP** |
| C | Test fixture authority + day/cycle-boundary coverage | **FIX-THEN-SHIP** → fixed |

**0 CRITICAL, 0 HIGH across all three.** Review B's standout finding: the fix *removes* two reserve-write storms (at the 20:00 and 21:00 boundaries) — strict improvement, no new oscillation surface (the existing 2-unit reserve deadband covers the single hold↔discharge flip).

## Findings + disposition
| ID | Sev | Review | Finding | Disposition |
|---|---|---|---|---|
| C-M1 | MED | C | None-engine legacy fallback branch untested | **FIXED** — `with_tou_engine=False` test added |
| C-M3 | MED | C | SOC-at-reserve "summer, post-peak" low-SOC reason untested | **FIXED** — test added |
| C-M2 | MED | C | Exact boundary hours (14/16/20/21) untested | **FIXED** — `TestPeakAheadBoundaryHours` (4 cases) |
| D4/F1 | MED | C | Bug class not registered | **FIXED** — Bug Class #51 filed in QUALITY_CONTEXT.md |
| A-L1 | LOW | A | Redundant `season=="summer"` clause in hold guard | **FIXED** — dropped |
| C-L2/L3 | LOW | C | Hardcoded shoulder/winter months + Sep-30 (fixture drift) | **FIXED** — derived from PEC_TOU_RATES |
| C-L4 | LOW | C | Dead `_STORAGE` walrus | **FIXED** — removed |
| A-M1/B-L | LOW | A,B | Docstring: caller-contract + why get_next_high_rate_transition can't be reused | **FIXED** — docstring extended |
| **B-MED** | MED | B | `_apply_evse_battery_hold` (`energy.py:~2199`) can re-hold the battery + cause reason↔action divergence if an EVSE is charging during post-peak | **DEFERRED** — pre-existing, not introduced here; tracked for a separate cycle + live-validation watch |
| A-L2 | LOW | A | SOC None → reserve 100 (pre-existing) | DEFERRED — pre-existing, separate hardening |
| A/C | LOW | A,C | DST-day explicit test, get_next_transition default-path warning | DEFERRED — no behavioral risk (PEC DST falls in non-peak season) |

## Bug class frequency
| Class | Count |
|---|---|
| #51 Day-Boundary-Blind TOU Decision (NEW) | 1 (the fix target) |
| #44 Fixture authority | 0 new (tests comply; hardened further) |

## Validation
py_compile clean; no conflict markers; **17** cycle tests pass; full-suite baseline-diff = **zero new failures** (39 pre-existing). 710 battery/tou/energy tests pass.

## Disposition
0 CRIT / 0 HIGH; all MED + actionable LOW fixed in-cycle; 1 pre-existing MED + minor LOWs deferred with tracking. **Ready for deploy** (awaiting operator go-ahead). Post-restart Review D: confirm during the next summer post-peak mid_peak (20:00–21:00 CDT) that the battery discharges (`current_battery_discharge`>0, grid import drops) and the strategy reason reads "summer, post-peak"; pre-peak (14:00–16:00) still holds — and watch the deferred `_apply_evse_battery_hold` interaction.

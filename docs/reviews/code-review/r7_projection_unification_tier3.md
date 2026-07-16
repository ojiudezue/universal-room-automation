# R7 Projection Unification — Tier-3 Review Record

**Cycle:** Net-energy program R7 (plan: `docs/planning/PLANNING_net_energy_program_R1_R7_R2.md`; chain R1→R7→R2)
**Build commit:** `ec60f1e2` — 5 SOC-at-boundary projection sites in `energy_battery.py` unified behind new `EnergyProjector.project_soc_at_boundary` (`energy_projector.py`), kill switch `R7_USE_UNIFIED_PROJECTOR` (rung-1 module constant).
**Fix-up commit:** `a305928b`
**Baseline tag:** `pre-review-r7` (= f9467b18)
**Date:** 2026-07-16
**Protocol:** Tier 3 — four framing-disjoint reviews. Motivation: Bug Class #53 at projection scale; the 07-15 11:20 ladder-vs-attain divergence was live evidence of independent projection implementations drifting.

## Verdicts

| Review | Framing | Verdict |
|---|---|---|
| A | Local correctness (per-site arithmetic vs pre-R7, parity fidelity) | SHIP |
| B | Integration + state-machine (I-AH1, I-BH1/2, lifecycle, kill switch, exceptions) | SHIP |
| C | Test authority via executed mutation (13 mutations) | **FIX-FIRST** |
| D | Adversarial completeness (I-R7 whole-surface enumeration, diff-blind) | SHIP |

## Invariant proofs

- **Byte-identity (A, B):** all 5 sites hand-verified against `git show pre-review-r7` — solar-bound, extra_rate signs (counterfactual −assumed_ev, entry +ev_load), mins/60, surplus placement. The raw-vs-clamped asymmetry (attain consumes `raw_soc_pct`, rung consumes clamped `soc_pct`) confirmed as FAITHFUL preservation: v5.17.4's clamp was rung-only. Kill-switch fallbacks verbatim. Parity tests use `==` (not approx) with independent in-test reimplementations verified against pre-R7 source.
- **I-AH1 / I-BH1/2 (B):** HOLD short-circuits untouched by the diff; blind-hold decisions made by upstream guards before any projection line — primitive None-return cannot alter them; exception propagation byte-identical.
- **I-R7 singleton (D):** whole-surface enumeration (all domain_coordinators + sensor.py + database.py) found ZERO leaks. `energy_forecast.py battery_full_time` adjudicated out-of-family (different math shape, observability-only, predates R7 — now documented in the primitive docstring). All 9 exempt lines verified dead-on-sighted-path or fallback-only.
- **Adjudications (D):** observability rider not built → NOT an I-NE3 violation today (every displayed projection is the value the decision consumed); recommend R7.1. Missing temporal 24h diff test → static parity grid + mutations dominate for a stateless primitive; accepted.

## Findings ledger

| id | sev | class | finding | disposition |
|---|---|---|---|---|
| C-HIGH-1 (=A-MED-1 =D-MED-1 =D-LOW-1) | HIGH | Cosmetic enforcement guard | Grep-singleton guard evaded by executed renamed spelling (`soc_now + net_rate * remaining_hours`) — GREEN in production; regexes anchored to literal names; scanned only energy_battery.py; exempt marker honored unconditionally incl. comments. Three reviewers converged independently. | **FIXED `a305928b`** — full AST rewrite: BinOp shape scan across ALL domain_coordinators, identifier-substring matching, structural `ast.If` exemption, marker count pinned at 9, 5 positive/negative self-tests incl. both evasive spellings. Zero false positives on legit code. |
| C-HIGH-2 | HIGH | Untested load-bearing wiring (Bug Class #53 family) | Swapping either attain site raw→clamped left FULL suite at baseline; the "RAW consumed" guarantee was primitive-isolated, never pinned at the call site. | **FIXED `a305928b`** — new `test_r7_attain_raw_consumption.py`: 4 behavioral tests driving `_should_attain_peak_buffer` + latched hold-current through `determine_mode` with raw>100 scenarios. M7/M7b re-executed RED. |
| C-LOW-1 | LOW | Zero behavioral coverage at hold-current site | Sentinel-poisoning the site failed only the isolated parity test. | Closed by the same new behavioral tests |
| C-LOW-2 | LOW | Fallback arithmetic-level coverage | Kill-switch-False fully green (M8); gross fallback drift caught (6 ladder tests), subtle drift (2× surplus) survives. | Accepted — fallback is one-release rollback path; delete fallbacks next release rather than test them |
| A-LOW-1 | LOW | Latent divergence for future callers | Primitive `mins=None` → silent zero-horizon where pre-R7 inline TypeError'd. Dead today (all sites guard mins). | Documented in docstring (fix-up §3) |
| D-LOW-2 | LOW | Docstring overclaim | Kill-switch rollback still requires energy_projector.py to import (unconditional module import). | Docstring corrected |
| D-LOW-3 | LOW | Second-model documentation | battery_full_time is a deliberate out-of-family SOC-trajectory model. | Docstring note added |

## Summary statistics

| Severity | Found | Fixed | Accepted/Documented |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 2 | 2 | 0 |
| MEDIUM | 0 (all MED convergences absorbed into C-HIGH-1) | — | — |
| LOW | 5 | 1 | 4 |

## Mutation campaign (C, 13 executed + fix-up 4 + orchestrator 1)

Build-round: 8 RED (primitive sentinel per site, solar-bound removal, clamp widening, surplus drop, sign flip, field swap), M8 kill-switch-False GREEN-as-required, 3 adversarial GREENs → the two HIGHs. Fix-up round: M7, M7b, M10 (evasive spelling), energy.py-scope probe — all RED. **Orchestrator independent verification:** M7 (hold-current `raw_soc_pct`→`soc_pct` at energy_battery.py:3553) re-executed personally — `test_attain_hold_current_publishes_raw_projection_over_100` FAILED as specified; restore verified via clean git diff; 22/22 green.

## Bug-class notes

- **Cosmetic enforcement guard** (C-HIGH-1): a CI guard that only catches the exact spelling it was written against provides false confidence — worse than no guard. Sibling of R1's self-referential-test class. QUALITY_CONTEXT candidate: "enforcement tests must include positive self-tests proving they catch a realistic evasion."
- Three framings (A regex-blindspot, C executed evasion, D scope gap) independently converged on the same guard from different angles — the framing-disjoint protocol working exactly as designed.

## Deviations from plan (accounting)

1. Observability rider (attain_reason carries projected_soc + horizon) NOT built → **R7.1 follow-on** (with widened-guard maintenance and fallback deletion).
2. Temporal 24h diff test not built → adjudicated dominated by static parity + mutations (D).
3. Defensive primitive-None rescues retained at 4 sites (dead, expression-identical) → accepted belt-and-braces.

## Ship state

All four framings resolved to SHIP after fix-up. **R7 authorized to ride the next deploy window with R1 shadow + v5.17.6.** No-behavior-change contract proven; live validation is trivial (no new behavior): confirm rung/attain attrs still populate post-restart and zero URA ERRORs referencing energy_projector. R2 (net-aware class widener + buy-sizing scope) is next, gated on R1's 14-day shadow observation.

# R1 Consumption Estimator v1 — Tier-3 Review Record

**Cycle:** Net-energy program R1 (plan: `docs/planning/PLANNING_net_energy_program_R1_R7_R2.md`)
**Build commit:** `db1fcf5e` — EV-decomposed consumption estimator v1 (base temp/season regression + EV constant), shadow mode
**Date:** 2026-07-16
**Protocol:** Tier 3 — four framing-disjoint reviews (A local correctness, B integration/lifecycle, C mutation execution, D adversarial completeness). A/B on `ura-reviewer-std` (opus); C/D on session model.

## Build summary

- Base regression fit on 2025-only (EV-free era): n=271 masked days, MAE 16.82, R² 0.41. Coefficients in `CONSUMPTION_REGRESSION_V1` (energy_const.py, rung-1 reviewed constant).
- EV term: single constant 18.58 kWh/day gated on `EV_ERA_START=2026-03-01` (operator "parsimony" directive after the original single-fit holdout FAILED at MAE 23.80 — year-over-year EV level shift).
- Combined holdout (2026-05-01..07-15, n=57): **MAE 16.06, passes ≤20 invariant**.
- EV extraction validated vs 15-min ground truth (5 days, MAE 6.5 kWh, bias +4.4).
- Shadow-only: `CONF_R1_ESTIMATOR_SHADOW_ONLY=True`; legacy DOW arm retained as consumed path (deliberate plan deviation — keeps I-NE6 rollback-as-constant true).
- DB: additive `energy_daily.predicted_consumption_source` column (PRAGMA-guarded, NULL-safe).

## Verdicts

| Review | Framing | Verdict |
|---|---|---|
| A | Local correctness (arithmetic, units, boundaries, fit reproducibility) | SHIP |
| B | Integration + lifecycle (shadow gate, restart, DB, rollback, cross-coordinator) | SHIP |
| C | Test authority via executed per-site mutation | **FIX-FIRST** |
| D | Adversarial completeness (I-NE4/I-NE6/I-NE1, diff-blind) | SHIP |

## Findings ledger

| id | sev | class | finding | disposition |
|---|---|---|---|---|
| C-1 (=A-1) | HIGH | Self-referential test / missing anchor | `_compute_v1` runtime arithmetic never anchored to an independent oracle: backtest re-derives from constants via test-local `_predict`; other tests use `_compute_v1` as its own expected value. Executed mutations M7 (EV term ×2) and M8 (season one-hot collapsed to all-summer) passed the FULL suite green. | **FIXED in fix-up** — parity test anchoring production `_compute_v1` to independent `_predict` across 4 seasons + EV-era pair + hot/cold temps; M7/M8 re-executed RED |
| C-2 | HIGH | Silent NULL / untested DAO write (Bug Class #53-adjacent: computed-but-not-verified persistence) | No test drives `log_energy_daily`'s `predicted_consumption_source` write; NULLing it (M11) left suite green. Marker is I-NE5's load-bearing gate for R2 — silent NULL would dormantly brick R2. | **FIXED in fix-up** — DAO round-trip test; M11 re-executed RED |
| D-MED-1 | MEDIUM (latent, shadow-off path) | Cross-arm contamination | On flip day, v1 output is multiplied by `_adjustment_factor` — trained on LEGACY errors; constants were validated raw. Would silently shift v1 ~±15% and contaminate the 14-day shadow comparison. | **DEFERRED by design** — named R2-flip prerequisite (reset/exempt factor); noted in `CONSUMPTION_REGRESSION_V1` docstring |
| A-3 | LOW | Methodology | EV term estimated on Mar–Jul 2026, overlapping the May–Jul holdout — mild optimistic bias in reported combined MAE. Base regression is clean (2025-only). | Accepted, documented here; R2's backtest-as-CI is the real gate |
| A-2 | LOW | Latent unit assumption | `_get_current_temperature` assumes °F with no unit check; degree-day form is more unit-sensitive than legacy. Correct on this deployment. | Backlog (commercialization hardening) |
| C-3 | MEDIUM (note) | Seasonal coverage | Backtest holdout is summer-only; `hdd_coeff` protected only via fit-reproducibility test. | Parity test now covers a 35°F case; acceptable |
| C-4 | MEDIUM (note) | Pre-existing untested clamp | `max(0.1,…)` output clamp (v3.7.12) mutation-green. Predates cycle. | Hygiene backlog |
| B-8 | LOW | Fit/runtime season-bucket parity | Verified identical (DJF/MAM/JJA/SON) by A; parity test now locks it. | Closed |
| B-9 / A-note | LOW | Date-attribution semantics | Daily snapshot pairs yesterday's actual with the latest prediction+marker (pre-existing). R2 self-scoring must not assume marker describes yesterday's forecast. | Carry into R2 plan |
| D-LOW-1 | LOW | Plan deviation (benign) | DOW arm retained instead of removed — improves rollback. | Recorded (plan-completion accounting) |

## Summary statistics

| Severity | Found | Fixed | Deferred (named) |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 2 | 2 | 0 |
| MEDIUM | 3 | 0 | 3 (D-MED-1 → R2 flip prereq; C-3 covered by parity; C-4 backlog) |
| LOW | 5 | 1 (B-8) | 4 |

## Bug-class notes

- **Self-referential test anchor** (C-1) recurs — sibling of the false-mutation-anchor class from v5.17.1. The pattern: tests that call the unit-under-test to generate their own expected values prove nothing. QUALITY_CONTEXT candidate.
- Builder's 4 claimed mutation anchors ALL re-confirmed RED by C — first cycle since the worktree-discipline/executed-mutation directives with zero false anchors.

## Invariant proofs (D)

- **I-NE4** shadow supremacy: HOLDS — single call site for `_estimate_consumption`; all consumers read `_get_current_prediction()`; `_compute_v1` is pure (no shared-state reads/advances); field-by-field diff of legacy arm vs pre-commit is arithmetically identical.
- **I-NE6** rollback-as-constant: HOLDS — nullable ADD COLUMN, all 4 readers use explicit column lists, deques stay warm on both paths.
- **I-NE1** blind-hold/inclement supremacy: HOLDS — zero hits in energy_battery/energy_pool/energy_tou.

## Ship state

**Fix-up commit `799854e5`** — added Test F (parametrized parity, 4 seasons + EV-era pair + hot/cold), Test G (backtest via production `_compute_v1`), DAO round-trip tests; D-MED-1 flip-prereq line in `CONSUMPTION_REGRESSION_V1` docstring. Builder re-executed M7/M8/M11 → all RED; md5 restores verified. Target file 16 passed; full suite matches 36F/14E baseline.

**Orchestrator independent verification (Tier-3 mandatory):** M7 (`base_kwh + 2*ev_kwh` at energy_forecast.py:295) re-executed personally on disk with pycache cleared → **5 failed** (`test_compute_v1_matches_local_predict` d1/d2/d3/d5 + `test_backtest_calls_production_compute_v1`), restored byte-identical (empty git diff), suite green (16 passed).

→ **Shadow-mode deploy authorized with next deploy window** (rides with v5.17.6). Live validation = 14-day shadow observation (predicted_consumption_source rows non-NULL within 48h, shadow MAE tracked) per plan phase gate; R2 flip requires D-MED-1 resolution.

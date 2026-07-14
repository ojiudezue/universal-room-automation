# Review record — v5.17.2: rung/gate observability + write-verify STALE retirement

**Commits:** 3517edab (attrs + solar_attain phase) + a0cca9e1 (STATUS_STALE retirement). Baseline tag `pre-review-v5.17.2`.
**Protocol:** Tier 2, framings A+B on ura-reviewer-std (Opus). Both verdicts **SHIP**; zero findings above LOW.

| ID | Sev | Finding | Outcome |
|---|---|---|---|
| A-1 | LOW | dead `_proj` read on rung_1 reason branch | cosmetic, deferred |
| A-2 | LOW | storage_mode desired lags one tick after oracle flap | fail-safe by None-guard, no change |
| B1-B6 | LOW/info | fast-path scope, alarm integrity both directions, persistence round-trip, revival supersession, type coherence, boot None-safety | all verified clean |

**Executed verifications:** A ran both critical truth-table cells (genuine reversion still alarms; convergence retires + freezes) + 486-test subset; B executed desire-None-no-retire and restored-record-retires-second-sweep probes. Decision-inertness proven (actions/reserve computed before display params; gate stamp assignment-only in all 5 return branches; per-tick rung cache prevents double-stamp).
**Operator-visible note:** the live stale "reverted" record retires on the sweep AFTER the first post-boot decision tick (~15-30 min), by design (desire=None at boot never retires).
**Truth table (retirement):** reached only on mismatch; desire None→reverted; desire==commanded→reverted+alarm; desire≠commanded ∧ ==oracle→STALE; ∧ ≠oracle→reverted.

# Code Review — EV Off-Peak Proactive Charging + Pause-State Persistence

**Cycle:** EV off-peak proactive charging (resume-only → ensure-on) + 5-set pause-state persistence
**Tier:** 2-DB (operator-elevated — trust-hierarchy ripple across energy ↔ EVSE persistence ↔ TOU precedence)
**Cycle commit:** `2d5e24c` (implementation + tests)
**Pre-review baseline tag:** `pre-review-ev-offpeak`
**Reviews:** 3 parallel, framing-disjoint (plan §7)
**Date:** 2026-06-07

> **Provenance note (No-Fabrication):** the three reviewer agents ran in the
> prior session turn; their verbatim outputs are not in this session's
> context. The dispositions below are reconstructed from (a) the recorded
> dispatch synthesis (counts, verdicts, fix/defer decision) and (b) the
> authoritative fix-up diff, which names each finding it addresses inline.
> Each FIXED row cites the file:line where the fix landed so the record is
> verifiable against the tree, not memory.

---

## Review framings

| Review | Risk axis | Verdict |
|---|---|---|
| **A** | Persistence correctness — KV round-trip, staleness gate, tz-aware save/restore, no-DELETE, 5-set parity | FIX-THEN-SHIP |
| **B** | Behavior / precedence / no-flap — off-peak ensure-on, guard precedence, hold-set lifecycle, idempotent re-issue, classifier read sites | FIX-THEN-SHIP |
| **C** | Surfaces + test authority — sensor attr round-trip, widened-semantics docs, test fixtures drive production paths | SHIP |

---

## Summary statistics

| Severity | Found | Fixed in-cycle | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 1 | 1 | 0 |
| MEDIUM | 2 | 2 | 0 |
| LOW | ~7 | 7 | 3 (genuine non-issues / doc-only nits) |

All CRITICAL/HIGH/MEDIUM fixed before deploy. No new test failures vs the committed-cycle baseline (full-suite diff: 39 == 39, identical names — all pre-existing order-dependent flakiness + `activity_logger` import errors documented in `2d5e24c`).

---

## Findings — FIXED

| ID | Sev | Review | Finding | Bug class | Fix (file:line) |
|---|---|---|---|---|---|
| **F1** | HIGH | A | Force-charge KV (`ev_force_charge_until`) not cleared when `_force_charge_until` auto-expires to `None`; stale future-ISO row lingered, with only the `parsed > utcnow()` restore future-check as the (fragile) guard against re-honoring it. | Stale persisted intent (#7) | `energy.py` `_save_evse_state` — added `else:` writing `""` empty-string sentinel on expiry; restore-side `if fc_iso:` treats `""` as falsy. |
| **B-MED-1** | MED | B | `_classify_evse` had no token for URA's off-peak proactive turn-on intent — sensor hid it behind generic `charging`/`idle`. Operator decision 1 requires widened-`_ev_tou_enabled` semantics surfaced at read sites. | Read-site semantic drift | `energy_pool.py` `_classify_evse` — added `offpeak_proactive_on` branch, positioned AFTER `excess_solar` (operator-preferred precedence on dual membership), above charging/idle fallbacks. |
| **B-MED-2** | MED | B | Peak-branch `_proactive_offpeak_holds.discard` sat AFTER the `excess_solar`/`force_charge` `continue` short-circuits → hold-set leaked across peak when either won the iteration. | Hold-set leak / stale membership | `energy_pool.py` — moved `discard` to the TOP of the `peak`/`mid_peak` branch, before any `continue`. |
| **B-LOW-1** | LOW | B | Battery-strategy sensor `expected_action` for off-peak transition still described battery-only behavior; didn't mention proactive EV turn-on. | Stale user-facing text | `sensor.py` `EnergyBatteryStrategySensor` — expanded off-peak `expected_action` string. |
| **B-LOW-2** | LOW | B | Legacy bare `else` would trigger proactive turn-on for ANY unexpected `tou_period` string. | Unsafe default branch | `energy_pool.py` — `else:` → `elif tou_period == "off_peak":` + explicit unknown-period `else: continue` no-op (cites `energy_tou.py:37` `_VALID_PERIODS`). |
| **B-LOW-3** | LOW | B | Dual membership of `_excess_solar_active` + `_proactive_offpeak_holds` was intentional but undocumented. | Undocumented invariant | `energy_pool.py` — comment at the `.add` site explaining precedence resolution in `_classify_evse`. |
| **B-LOW-4** | LOW | B | Force-charge off-peak path did not discard a prior-tick proactive hold (asymmetric vs the 2a carry-over-guard cleanup). | Hold-set leak | `energy_pool.py` — `discard` added inside the `if force_charge_active:` branch before `continue`. |
| **F3** | LOW | A | Staleness gate on grid_cap/drain KV reads needed a note that it's defense-in-depth (sets re-derived every tick from live inputs). | Doc-only | `energy.py` `_restore_evse_state` — comment. |
| **F8** | LOW | A | Planning text claimed "KV wins over Switch RestoreEntity on conflict"; actual runtime ordering is Switch-attr-fast-path-wins, KV-durable-fallback. Doc-vs-code mismatch (code correct). | Doc-vs-code mismatch | `energy.py` — corrected the restore-ordering comment (cites `switch.py:802-854`). |
| **C-LOW-2** | LOW | C | Test-only `_parse_datetime` helper uses `datetime.fromisoformat` (production uses `dt_util.parse_datetime`) without a marker. | Test fidelity | `test_ev_offpeak_proactive.py:111` — `# noqa` annotating the intentional test-only divergence. |

**Fix-up tests added** (`test_ev_offpeak_proactive.py`, +8): classifier proactive branch + precedence (3), unknown/empty TOU period no-op (2), force-charge KV empty-string sentinel on expiry + restore-treats-empty-as-none (3).

---

## Findings — DEFERRED

| ID | Sev | Review | Finding | Why deferred |
|---|---|---|---|---|
| **F2** | LOW | A | (no-fix-needed) flagged a possible naive-vs-aware datetime path. | Verified non-issue — all saves go through `dt_util.now().isoformat()` (aware) and all restores through `dt_util.parse_datetime`; no naive path exists. |
| **C-LOW-1** | LOW | C | Test fixture authority nit — one harness assertion gate could bind more tightly to production schema. | Genuine non-issue: gates are 2-line and comments already cite the production `file:line` they mirror. Not worth churn. |
| **C-LOW-3** | LOW | C | Second minor test-fidelity nit (same class as C-LOW-1). | Same rationale. |

Deferral count = 3, all LOW, all genuine non-issues / doc-only — within the ≤6 cap (Fix-LOWs-in-cycle rule honored: every actionable LOW fixed; only no-op nits deferred).

---

## Bug class frequency

| Bug class | Count this cycle |
|---|---|
| Stale persisted intent (#7) | 1 (F1) |
| Hold-set leak / stale membership | 2 (B-MED-2, B-LOW-4) |
| Read-site semantic drift | 1 (B-MED-1) |
| Unsafe default branch | 1 (B-LOW-2) |
| Doc/text drift (user-facing + planning) | 3 (B-LOW-1, F3, F8) |
| Undocumented invariant | 1 (B-LOW-3) |
| Test fidelity | 1 fixed (C-LOW-2) + 2 deferred |

**No new bug class recommended for QUALITY_CONTEXT.md** — F1 is a recurrence of stale-persisted-intent (#7); the hold-set-leak findings are localized lifecycle bugs in new code, not a generalizable pattern beyond the existing membership-set discipline.

---

## Disposition

- All HIGH + MEDIUM fixed and re-verified (py_compile clean, no conflict markers, 73 cycle tests pass, full-suite zero-new-failures).
- Fix-up committed on `feature/ev-offpeak-proactive`.
- **Next:** pre-deploy zero-bugs gate → await operator deploy.sh go-ahead → post-restart Review D live validation (write observed results back into README).

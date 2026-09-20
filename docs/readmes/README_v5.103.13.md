# v5.103.13 — HVAC receives the EC constraint at boot (restart-day pre-cool restored)

**Card:** `HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1` · Tier 2-DB (3 framing-disjoint reviews + fix-up + orchestrator mutation-verify)

## Problem (surfaced live by the v5.103.12 `pre_cool_skip_reason` obs)
Post-restart, the HVAC coordinator's `_energy_constraint` stayed `None` until the first EC **mode change** (evening coast), because: EC is set up before HVAC (`CoordinatorManager` sequential), so EC's boot decision cycle dispatched `SIGNAL_ENERGY_CONSTRAINT(normal)` **before** HVAC subscribed (fire-and-forget, no replay), and the EC only re-dispatches on a *change*. Consequence: Path A afternoon pre-cool (`_should_energy_precool`, surplus-only) received `constraint=None` and was **disabled from boot until the evening coast** — a restart-morning misses the whole 10am–2pm pre-cool window. (Bug Class #5 boot ordering.)

## Fix
- **Producer-owned builder:** extracted the `EnergyConstraint(...)` construction into `EnergyCoordinator._build_energy_constraint()`; both the dispatch site and a new `current_energy_constraint()` route through it (single source of truth, no payload drift). `max_runtime` is frozen via `_hvac_constraint_max_runtime` to match the dispatched payload.
- **HVAC pulls at setup:** right after subscribing, HVAC calls `energy.current_energy_constraint()` and seeds `_handle_energy_constraint()` — ordering-proof (EC fully set up by then) and idempotent (a later real signal just re-applies). Fully guarded: no-manager / no-energy / None / exception → debug-log no-op = old behavior.
- **D7 dwell continuity preserved:** the mode sensor's resume-if-same restore now also resumes when `restored_mode == live_mode` (the boot-pull now stamps `_since`, which previously suppressed the D7 restore) — so `energy_constraint_duration_s` no longer zeros mid-coast on restart.
- Nits: builder `solar_class` defaults to `"unknown"` (not None) on exception; "ordering-tolerant" comment corrected.

## Review ledger
A (payload parity) SHIP · B (boot lifecycle/idempotency) SHIP + caught the D7-dwell regression (fixed) · C (test authority) FIX-REQUIRED — the initial tests were hollow (source-greps / exec-of-text); fix-up replaced them with 8 behavioral tests. **Orchestrator independently mutation-verified on the shipping code (cache-clean):** neutering the pull REDs `test_pull_seeds_hvac_from_energy_coordinator`; dropping `setpoint_offset` from the builder REDs `test_current_energy_constraint_returns_full_payload`.

## Validated 2026-09-18 (post-restart at ~16:07 CDT, during evening coast, running v5.103.13)

| Criterion | Result | Observed |
|---|---|---|
| HVAC holds the EC constraint at boot (the fix) | **PASS** | `sensor.ura_hvac_coordinator_mode`: `energy_constraint_mode=coast`, `energy_offset=2`, `pre_cool_skip_reason=outside_window` — **not** `no_constraint`. Pre-fix this would be `no_constraint`/offset 0 until the 8pm coast→normal change; the pull delivered coast/+2 at setup. |
| Constraint-driven behavior live at boot | **PASS** | `energy_offset=2` applied (coast setpoint-widening active immediately, not deferred to a mode change). |
| D7 dwell continuity survives restart-during-coast (B-MED-1) | **PASS** | `energy_constraint_since=16:00:36 CDT` (the *actual* coast start, restored — not the 16:07 restart time), `energy_constraint_duration_s=743` (~12 min continuous). The pull's `utcnow` stamp did not clobber it — resume-if-same held. |
| Zero URA ERROR | **PASS** | system-log ERROR filter = 0. |

Note: this restart happened to land during coast (a real mode), so a normal dispatch could also deliver it — but the pull is what made HVAC hold the constraint *at setup* (offset applied immediately + dwell restored); the `outside_window` reason confirms the predictor received the object, not `None`. The restart-morning `normal`-window case (the original failure) is the same code path, proven by the mutation-anchored boot-ordering test.

## Rollback
`git revert` the merge — the pull is additive + fully guarded.

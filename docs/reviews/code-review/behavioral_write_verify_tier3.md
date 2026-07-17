# Behavioral Write-Verify — Tier-3 Review Record

**Cycle:** EC headline — conduct verification + pending-write watchdog + D3 command trail
**Plan:** `docs/planning/PLANNING_behavioral_write_verify.md` (4 ratified decisions, D2 retry ladder + stand-down, retry freshness constraint, B0 probe reports)
**Commits:** build `1fabce77`; fix-up 1 `d881bcde`; fix-up 2 `0e97e20f`
**Baseline tag:** `pre-review-write-verify` (= 914b2a9e)
**Date:** 2026-07-17
**Protocol:** Tier 3 — A/B (ura-reviewer-std), C mutation + D completeness (session model), D re-pass after fix-up, orchestrator mutation verification.

## Verdicts

| Pass | Verdict |
|---|---|
| A local correctness | SHIP (2 LOW) — sign convention verified correct end-to-end |
| B integration/state-machine | FIX-FIRST (2 HIGH, 1 MED) |
| C mutation execution (13 mutations) | FIX-FIRST (test gaps only; builder anchors all corroborated) |
| D adversarial completeness | FIX-FIRST (3 HIGH) |
| D re-pass (post fix-up 1) | FIX-FIRST (1 new HIGH — the N+1th site) |
| Final state (post fix-up 2 + orchestrator verification) | **SHIP** |

## Findings ledger (all fixed unless noted)

| id | sev | finding | fix |
|---|---|---|---|
| D-HIGH-1 | HIGH | Conduct check blind during EVSE battery hold — exception (d) compared PRE-overlay desire vs POST-overlay commanded → exempt every tick; battery could drain into car unalarmed | `_effective_reserve_desired` (max of strategy desire, evse hold, inclement floor from REAL state) threads through exception (d), watchdog, force_redispatch payload, cool-off probe (`d881bcde`) |
| D-HIGH-2 | HIGH | Watchdog inert for stuck HOLD writes (motivating 07-16 fixture unreachable) — same root | Same fix |
| D-HIGH-3 | HIGH | Stand-down cosmetic: `_result` re-dispatched same value every 5-min tick; triple alarm families | Stand-down gate at `_result` reserve-append + self_heal_starvation suppression during pending episode (`d881bcde`) |
| D2-HIGH-1 | HIGH | **N+1th site (D re-pass):** EVSE-hold overlay runs AFTER `_result`, re-emitted hold value bypassing the new gate | `_standdown_pinned_on` gate in BOTH overlay branches (`0e97e20f`) |
| B-HIGH-1 | HIGH | Inclement exception read invented attr `_inclement_partial_hold_active` (doesn't exist) → silently inert; false alarms during legit storm holds | Reads real `_last_inclement_decision.hold_depth` (`d881bcde`) |
| B-HIGH-2 | HIGH | Test fixture invented the same fictional attribute — green-lit inert code | Fixture mirrors real InclementDecision fields (`d881bcde`) |
| C-M6b | HIGH | Ladder spacing lower bound untested (collapse to consecutive ticks shipped green) | Inter-attempt spacing gate + test (`d881bcde`) |
| C-M8 | HIGH | D3 command_trail truthfulness untested (lying trail shipped green) | Three-distinct-witnesses test (`d881bcde`) |
| B-MED-1 / D-MED-1 | MED | `_reserve_hold_owner` invented → hold_owner trail permanently None (the operator-confusion deliverable) | `_resolve_hold_owner` from real state (`d881bcde`) |
| D-MED-2 | MED | Cool-off probe dispatched pre-overlay desire — would clobber active hold 61→15 | Effective-desire threading (`d881bcde`) |
| D-MED-3 | MED | Grid-outage backup discharge false-fired conduct ALERT | Outage exception via real `grid_enabled` witness (`d881bcde`) |
| D2-MED-1 | MED | Inclement exception (e) was blanket — blind window below the inclement floor itself | Narrowed to `soc >= inc_floor − deadband`; below-floor now fires (`0e97e20f`) |
| D2-MED-2 | MED | Grid witness unavailable was alarm-permissive; witness flaps correlated with Envoy/outage | Abstain whole conduct check when witness configured-but-unavailable (`0e97e20f`) |
| D-MED-4 / C-M10 | MED | Severity hardcoded WARNING; ALERT/HIGH/CRITICAL only payload strings | Real AnomalySeverity mapping + per-attempt test. Note: enum has no HIGH bucket — attempt-2 lands at ALERT enum with HIGH payload string (documented) |
| C-M11 | MED | Kill-switch-off left suite red (11 failures) | Switch-aware tests + explicit disabled-silent tests (`d881bcde`) |
| C-M12 | MED | Power-blind abstain untested | Test added (`d881bcde`) |
| A-LOW-1 | LOW | Ladder collapse on pre-aged divergence | Spacing gate (same as C-M6b) |
| D2-LOW-1 | LOW | write_reverted double-fire with pending ladder | Suppressed during pending episode; `write_verification_failed` retained (distinct meaning) (`0e97e20f`) |
| A-NIT-1, D2-NIT-1 | LOW | Confusing `or self` fallback; contradictory force_redispatch docstring | Both fixed |

Deviation #2 (force_redispatch bypasses breaker safety) — **verified SAFE by B**: reserve excluded from breaker gating by design; targets the cloud write leg correctly.

## Summary statistics

| Severity | Found | Fixed | Accepted/Documented |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 8 | 8 | 0 |
| MEDIUM | 8 | 8 | 0 |
| LOW/NIT | 5 | 4 | 1 (post-restart ladder re-arm, bounded by spacing gate — plan non-goal, documented) |

## Mutation campaign

Build: 5 anchors RED. C: 13 executed (2 builder re-confirmations, 4 GREENs → findings). Fix-up 1: 7 RED. Fix-up 2: 2 RED. **Orchestrator verification:** (1) conduct exception reverted to pre-overlay desire → `test_conduct_uses_effective_desire_under_evse_hold` RED; (2) overlay gate neutered (`return False`) → `test_evse_overlay_honors_standdown_gate` RED. Both restores byte-identical (clean git diff), 34/34 green.

## Bug-class notes

- **Invented-attribute getattr** (B-HIGH-1/2, D-MED-1): defensive `getattr(obj, "name", None)` on an unverified name converts a crash into silent inertness — worse. The builder honestly flagged it (deviation #4) and reviews confirmed both names fictional. QUALITY_CONTEXT candidate: "getattr-with-default on unverified attribute names = silent-inert code; verify the name exists or let it crash."
- **Pre-overlay vs post-overlay ledger split** (all three D-HIGHs + the re-pass HIGH): when an overlay mutates a command after the strategy stamps its desire, every consumer of "what does the system want" must choose a side explicitly. Sibling of Bug Class #53 at ledger scale.
- The D re-pass finding the N+1th site after a SHIP-quality fix-up re-validates the Tier-3 "re-run D after fixes" mandate (precedent: v5.5.3).

## Suite state

Final: 36F / 6930P / 33 skipped / 14E — exact pre-existing baseline, zero new failures. Write-verify test file: 34 tests.

## Ship state

**Awaiting operator deploy checkpoint (Tier-3 mandatory).** Live validation plan: post-deploy, D3 `command_trail` attrs populate on `sensor.ura_energy_coordinator_battery_strategy` (commanded/hardware/cloud with ages); conduct + watchdog silent through a clean day (no false NM); the next organic Enphase wedge (3 this week) exercises the ladder. README to be written at deploy.

# Enphase Cloud-Reliance D2 — Tier-3 Review Record

**Cycle:** cloud-reliance program (plan: `docs/planning/PLANNING_enphase_cloud_reliance.md`).
D0 (consumption-surface audit) + D1 (enphase_ev v4.0.0 upgrade) executed 2026-07-16/17;
this record covers **D2** (SOC divergence detection + `soc_resolution` observability + cloud-lag surfacing)
and **D3** (dropout posture — verified no-op).
**Commits:** build `63362276`; fix-up 1 `b48e9bc5`; fix-up 2 `a3457bb1`; fix-up 3 `2c1ce3fc`
**Date:** 2026-07-17
**Protocol:** Tier 3 (operator elevation) — A/B (ura-reviewer-std), C mutation + D completeness, D re-pass, orchestrator mutation verification.

## Verdicts

| Pass | Verdict |
|---|---|
| A local correctness | FIX-FIRST (2 HIGH) — verified the wrong-leg claim CORRECT |
| B integration/lifecycle | SHIP w/ doc fix (1 doc-HIGH, 2 MED) — verified blind-abstain deliberate; D3 no-op re-verified |
| C mutation (9 executed) | FIX-FIRST (4 survivors → 5 test specs) |
| D completeness | FIX-FIRST (1 CRITICAL, 2 HIGH, 1 MED) |
| D re-pass (post fix-up) | SHIP (+1 MED, folded in same hour) |
| Orchestrator verification | Caught 1 survivor the fix-up missed (install-site unanchored) → fix-up 2 |

## Findings ledger (all fixed)

| id | sev | finding | fix |
|---|---|---|---|
| D-CRIT-1 | CRITICAL | NM plumbing production no-op — `_fire_d2_nm` getattr'd `_coord`/`coordinator`, neither exists on BatteryStrategy; the motivating 07-16 fixture would detect and alert NOBODY. Invented-attribute class, 2nd cycle running. | Real backref `self._battery._coord = self` + invocation test (`b48e9bc5`) |
| ORCH-1 | HIGH | Install SITE unanchored — orchestrator neutered energy.py:279 → all 21 tests green (test wired the fake directly). Read path pinned, wiring wasn't. | Real-coordinator-construction test anchoring the install line; mutation RED (`a3457bb1`) |
| D-MED-2 (re-pass) | MED | Backref installed inside WriteVerifier try-block — unrelated import failure would silently resurrect dead-NM. | Moved above the try (`2c1ce3fc`) |
| D-HIGH-1 | HIGH | Shared dwell timer regime-overloaded: clear-branch seeded it during convergence → instant-fire on outage-recovery transient AND instant-clear. | Split above/below timers, both detectors (`b48e9bc5`) |
| D-HIGH-2 = A-HIGH-1 | HIGH | No cloud staleness gate — detector compared values the resolver itself rejects (>600s); could false-fire or suppress. | Age gate reusing `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S` + tier-consistency gate (only evaluate when resolver served primary; literal "envoy" verified against the actual stamp by D re-pass) (`b48e9bc5`) |
| A-HIGH-2 | HIGH | Dwell mutation-anchor test was an order-dependent flake (sibling-test `utcnow` monkeypatch leakage) — non-authoritative acceptance oracle. | Now-injection (single time snapshot per evaluation) + pinned clocks w/ teardown; 3× flake-free runs (`b48e9bc5`) |
| D-MED-1 | MED | Per-day latch was once-EVER for standing divergence (edge-triggered fire). | Fire per confirmed tick; date latch dedups (matches the write-verify pattern the plan cited) (`b48e9bc5`) |
| B-HIGH-1 | HIGH (doc) | Docstring claimed "once per decision tick"; hook actually runs per get_status RENDER (sensor/hvac_predict/diagnostics). Behavior safe (wall-clock dwell + latch); claim corrected. | Doc fix (`b48e9bc5`) |
| B-MED-1 | MED | Divergence depended on sibling evaluator's instance-var write ordering. | Re-reads snapshot itself (`b48e9bc5`) |
| A-MED-1 | MED | Wall-clock dwell unguarded against clock steps. | `max(0,...)` clamp + documented (`b48e9bc5`) |
| C M3/M4/M5/M8/M9 | MED | 5 untested surfaces: per-day latch, bidirectional abs(), age truthfulness, wrong-leg discrimination, get_status wiring. | 7 new tests; all 9 fix-up mutations RED deterministically (`b48e9bc5`) |
| B-LOW-1 | LOW | Kill-switch left `_active` stuck mid-alert. | Cleared in kill-switch branch (`b48e9bc5`) |

Verified-clean highlights: builder's wrong-leg claim (direct cloud-oracle reads) CORRECT (A); blind-abstain
preserving active alerts is deliberate load-bearing behavior with a do-not-clean-up comment (B); W-4
coexistence non-colliding (different channels/dedup) (B, D); D3 genuinely covered by the existing 3-strike
per-episode alert — no code, verified twice (B, D).

## Summary statistics

| Severity | Found | Fixed |
|---|---|---|
| CRITICAL | 1 | 1 |
| HIGH | 6 (incl. 1 doc, 1 orchestrator) | 6 |
| MEDIUM | 7 | 7 |
| LOW | 1 | 1 |

## Mutation campaign

Build: 4 RED. C: 9 executed (5 RED incl. 2 builder re-confirmations, 4 survivors → findings).
Fix-up 1: 9 RED deterministic (3× runs). Orchestrator: 2 executed (backref read — RED pre-check;
install site — GREEN → ORCH-1 → anchored → RED). Final suite: 36F/6952P/14E = baseline, D2 file 21/21 ×3 flake-free.

## Bug-class notes

- **Invented-attribute getattr, 2nd consecutive cycle** (D-CRIT-1 after write-verify's B-HIGH-1) — now
  unambiguously a QUALITY_CONTEXT bug class: "getattr-with-default on unverified attribute names converts
  crashes into silent inertness; verify the name or let it crash."
- **Read-path-pinned / install-site-unpinned** (ORCH-1): a test that wires the dependency directly proves the
  consumer, not the wiring. Anchor construction paths, not just method bodies.
- **Sibling-test monkeypatch leakage** breaking mutation-anchor determinism (A-HIGH-2) — wall-clock test
  family, second occurrence (v5.17.1 precedent).

## Ship state

**Awaiting operator deploy checkpoint.** Rides the next release (with EVSE drain-precedence if its reviews
complete in time, else alone). Live validation plan: `soc_resolution` attr populates with tier + ages;
divergence detector silent through a clean day; next cloud-vs-local split (25-pp class) fires exactly one
WARNING NM/day.

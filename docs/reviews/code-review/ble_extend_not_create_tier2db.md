# BLE Extend-Not-Create — Tier 2-DB Review Record

**Cycle:** universal recent-motion/chain confirmation for BLE room occupancy — fixes the
2026-07-17 Master Bathroom strobe (Bermuda iPhone flap × Tier-1 direct-BLE unconditional
bypass). Branch `build/ble-extend-not-create`: 93ea13a4 (build, tag pre-review-ble-extend)
+ 5cf0e6b7 (fix-up) + 2c65e780 (close-out).
**Protocol:** 3 framing-disjoint reviews + focused B re-look on the fix-up + orchestrator
mutation verification. **Final verdict: SHIP** (awaiting deploy window — no-restarts order).

## Findings ledger

| ID | Sev | Finding (bug class) | Found by | Resolution |
|---|---|---|---|---|
| B-HIGH-1 | HIGH | Build silently bounded the still-body sleep hold at 2×timeout for direct-BLE rooms — contradicted the operator-ratified invariant ("still-body purpose survives untouched"); repro: sleeper vacated at T0+60min, HVAC retreat | B | FIXED 5cf0e6b7: chain predicate (`_last_occupied_state` prev-tick verified at all 5 mutation sites) — extend indefinite, create rejected; sleep-hold pin test + M3 mutation anchor |
| C-CRIT-1 | CRITICAL (test-only) | Camera-block SHA guard tautological — C PROVED it by editing the camera block and watching the guard pass (3rd self-referential-anchor occurrence in 3 cycles) | A suspected, C proved | FIXED: frozen literal sha256 |
| B-MED-1 (re-look) | MED | "Bounded by the 4h failsafe" is illusory for BLE holds — failsafe requires occupied=True where BLE ticks read False; pre-existing, but the new comment repeated the myth with a wrong line cite | B re-look | FIXED 2c65e780: truthful comment + plan-doc correction; forgotten-phone mitigation = PersonPhoneLeftBehindSensor |
| B-MED-1 (orig) | MED | Extend path only tested within-window — the B-HIGH-1 regression was invisible to the suite | B | FIXED: sleep-hold pin (chain past window HELD; chain broken REJECTED) |
| B-MED-2 | MED | Lifecycle not exercised across real ticks | B | FIXED: 5-tick chain test (harness limits documented in-file) |
| B-LOW-1 (re-look) | LOW | Tier-2 rooms GAIN an indefinite chain hold (previously self-released at 2×timeout) — intended uniform semantics | B re-look | ACCEPTED + shared-scanner room added to live checklist |
| A-LOW-1 | LOW | Negative clock-skew now rejects (old Tier-2 admitted) — intentional hardening | A | Documented in plan |
| C-LOW-1 | LOW | MULTIPLIER>0 guard technically dead code (arithmetic implies it) | C | Comment marks readability role; kill semantics tested via T5 |
| B-LOW-2 | LOW | Comment line-anchors drift | B re-look | FIXED: anchors replaced with grep instruction |

**Stats:** 1 HIGH + 1 test-CRIT found/fixed · 3 MED fixed · 5 LOW (3 fixed, 2 accepted).

## Adversarial verification
- C executed 9 mutations (builder's M1/M2 + 7 own): all invariant legs red except the dead
  guard (documented); fixture extraction fails LOUDLY on anchor rename; camera-guard
  tautology proven by real camera-block edit.
- Orchestrator: independent chain-leg mutation (3 tests RED incl. sleep-hold pin), restore
  verified, predicate + writer-sites read personally.
- B re-look falsifications: failsafe-zombie (double-guarded), grace_hold↔chain
  mutual-resurrection (impossible — both are readers; BLE block skipped when grace holds),
  warm-chain flap (bounded by per-tick BLE presence; not worse than pre-fix Tier-1).

## Bug-class notes for QUALITY_CONTEXT
- **Self-referential test anchor: 3rd occurrence (promote to numbered class).** Ships-OFF
  tautology (BAEC), T8 camera SHA (this cycle) — the pattern: a guard that derives its
  expectation from the artifact it guards.
- **Invariant-narrowing-by-fix** (B-HIGH-1): a fix for the failure direction of a
  primitive can silently narrow its success direction; the review framing that catches it
  is lifecycle (B), not correctness (A) — keep framings disjoint.
- **Illusory-backstop documentation** (B-MED-1): comments citing a safety net must be
  verified against the net's actual precondition.

## Live validation (queued for next sanctioned restart)
- Master Bathroom cold Bermuda flap ⇒ ZERO `light_turn_on source=ble` rows in ura_activity_log.
- Master Bedroom still-body night hold intact (chain leg).
- One shared-scanner (Tier-2) room watched for phone-left-behind over-hold.
- Suite: 17/17 cycle tests; filter 1541/5 pre-existing; full suite 36F/14E envelope.

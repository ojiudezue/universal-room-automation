# Plan Review 2 — STEP D1 (shared exclusion primitive) + D2 (physics chatter client)

**Doc under review:** `docs/planning/PLANNING_sensor_health_surfacing.md` (post-3-MED fix-up 2026-08-19).
**Companion of record:** `docs/reviews/code-review/step_chatter_plan_review.md` (Plan Review 1 — PLAN-NEEDS-FIXES, 3 MED / 2 LOW).
**Tier:** 3 (operator-elevated 2026-08-19). This is the second plan review per Tier-3 discipline; framing = **adversarial build-prediction** ("what will the builder get wrong reading this?"), disjoint from Plan Review 1's framing of adversarial completeness of REUSED/NEW + definition safety.
**Verdict:** **PLAN-NEEDS-FIXES** — one MED (build-prediction ambiguity in §D1.1 failure-branch semantics) + two LOW. No CRIT / HIGH. Fixes are in-plan (doc-only), <30 min.

**M-MED-1 / M-MED-2 / M-MED-3 resolution verdict:** all three fixes landed correctly and are precise enough to build against — with the single carve-out on the failure-branch clause of §D1.1 (below). Details in §1.

---

## 1. Confirmation that the three MEDs from Plan Review 1 landed correctly

### M-MED-1 (§D1.1 release-scan interaction) — LARGELY FIXED, one residual build-prediction ambiguity

Re-read `coordinator.py:2480-2708` end-to-end and cross-checked against §D1.1.

**Verified correct in the fix:**
- Point 1 (source-of-truth): plan correctly designates STUCK-SENSOR-1's own `_dutycycle_excluded_last_tick` / `_dutycycle_excluded_now` as authoritative for the recovered-NM release scan; `SensorExclusionSet` is the fusion-time gate only. This preserves the B-MED-1 (2026-08-13) guard semantics — the release-scan diff computation at :2669 continues to read STUCK-1's own book, not `SensorExclusionSet.provenance()`. A builder following this contract will NOT regress the v5.75.0 recovered-NM shape.
- Point 2 (ordering): `reset_tick()` at tick start, BEFORE the `_prev_excluded` snapshot at :2533 AND before P22's initial population at :2498. Verified: the shipped ordering is P22(:2498) → `_d2_completed_cleanly=False`(:2532) → `_prev_excluded` snapshot(:2533) → `_dutycycle_excluded_now={}`(:2534) → D1 promotion(:2567-2569). Reset-tick must fire before :2498. The plan is unambiguous on this.
- Point 4 (byte-identity check): the delegation to `ledger_golden_replay` — recovered_stuck_signal row count and shape must match pre-cycle — is the right authoritative check; Reviewer A owns it. No builder confusion here.
- Point 5 (chatter at this seam): STUCK-SENSOR-1's `_dutycycle_excluded_*` fields are strictly disjoint from chatter's `_chattering_entities` book. Client isolation of the release scans follows.

**Residual ambiguity (M2-MED-1 below):** Point 3 conflates two different flavors of "preservation" on the D2-detector-raise failure branch — see §2.

### M-MED-2 (provenance classifier — `(kind, provider)` allow-list, NOT bare `device_class`) — FIXED CORRECTLY

Re-read §D2 point 1 in the amended plan.
- The allow-list is authored as an explicit `CHATTER_PROVENANCE_ALLOWLIST` rung-1 module constant. Allow rows and Deny rows are enumerated by `(kind, provider)`. Camera-family, groups (`provider="group"`), and bed multi-state are explicit DENIES.
- Classifier order is **unambiguous**: "camera-family entities matched via integration-domain (`frigate`, `unifi_protect`) or entity_id substring (`camera_motion`, `binarygroup_camera_`) BEFORE the motion-provider allow rule fires." Builder cannot get the ordering wrong from a straight read.
- `binarygroup_camera_motion_zone1` (which has `device_class=motion`) is denied because the `binarygroup_camera_` substring / `provider="group"` deny rule fires before the motion-provider allow rule. Explicit Reviewer-C fixture is required per §D2 acceptance criteria — that fixture pinning is the correct anti-regression instrument.
- Silent-default is DENY (unknown device families are not scored → cannot be false-quarantined). This is the correct default and the plan states it explicitly.

Builder-prediction test: a builder implementing "match by `_KIND_TO_CONF` bucket + provider tag, with integration-domain / entity_id substring fallback matched FIRST" from this spec would produce the correct classifier. The camera-motion group cannot slip through under the amended spec.

### M-MED-3 (K + per-family T_floor defaults + kill-switch on the knob ladder) — FIXED CORRECTLY

§5 now carries:
- `CHATTER_BURST_K` — rung-1, own row, in the D0-recommended gap 5..150, kill-switch semantics `K=10**9` documented.
- `CHATTER_T_FLOOR_DEFAULTS` — rung-1, own row, per-family concrete values (PIR 2.0s / mmWave 1.5s / opener/ratgdo 3.0s / reed 1.0s) with the non-circular ladder restated, and per-sensor `T_floor=0` kill switch documented.
- `CHATTER_OBSERVATION_WINDOW_S` — rung-1, own row.
- `CHATTER_PROVENANCE_ALLOWLIST` — rung-1, own row.
- Per-entity `T_floor` override via existing `sensor_capability` — rung-2, correctly separated.

Builder can implement rung-1 module constants from these rows without guessing. ✅.

---

## 2. Build-prediction findings

### M2-MED-1 — §D1.1 point 3 conflates bookkeeping-preservation and fusion-engagement-preservation on the D2-failure branch

**Where:** `docs/planning/PLANNING_sensor_health_surfacing.md` §D1.1 point 3, current text:

> The `_d2_completed_cleanly` guard preserved AND extended. The mid-detector exception guard at :2698-2705 — which on partial failure PRESERVES the engaged exclusion set to avoid a spurious mass-recovered-NM storm — MUST be extended: on the failure branch, STUCK-SENSOR-1's mirror writes into `SensorExclusionSet` for THIS tick are ALSO preserved (i.e. do NOT call `release("stuck_dutycycle", e)` in the failure branch). The invariant a builder must preserve: on partial D2 detector failure, previous tick's promotions remain, the recovered-NM scan is skipped, AND the fusion gate stays engaged for STUCK-SENSOR-1's entities.

**The problem — two contradictory readings survive this text:**

Pre-cycle behavior on D2-detector raise, verified in `coordinator.py:2646-2707`:
- The `try` body at :2567-2569 never runs → `stuck_sensors.add(s)` for D1 entities never happens → local `stuck_sensors` this tick contains ONLY the P22 set.
- The fusion sites at :2712/2719/2726/2740/2748/2756 read the local `stuck_sensors` → **fusion this tick excludes only P22 entities. D1 exclusions from the previous tick are NOT applied to fusion on the failure tick.**
- The bookkeeping restore at :2704-2707 (`_dutycycle_excluded_last_tick = _prev_excluded`, `_dutycycle_excluded_now = {s: now for s in _prev_excluded}`) rebuilds STUCK-1's *own* book so next tick's release scan (`_prev_excluded - _dutycycle_excluded_now`) computes an honest diff. That restore does NOT affect this tick's fusion — it happens after :2712 has already read `stuck_sensors`.

Reading A of the plan (bookkeeping-only preservation, matches pre-cycle):
- On the failure branch, do NOT call `release("stuck_dutycycle", e)` into `SensorExclusionSet` (matches text). Also do NOT call `promote("stuck_dutycycle", e)` on the failure branch — because `SensorExclusionSet` was cleared at `reset_tick()` and the promotion loop never ran.
- Result: `SensorExclusionSet` is empty for D1 entities this failure tick. Fusion excludes only P22 entities. **BYTE-IDENTICAL to pre-cycle.** STEP-EXCLUDE-2 holds strictly.
- STUCK-1's own `_dutycycle_excluded_*` restore continues as today → release scan next tick is honest.

Reading B (fusion re-engagement, the "fusion gate stays engaged for STUCK-SENSOR-1's entities" clause taken literally):
- On the failure branch, mirror-promote `_prev_excluded` into `SensorExclusionSet` for the D2-raise tick so the fusion re-engages D1 exclusions.
- Result: fusion this tick excludes P22 + prev-tick D1 entities. **BEHAVIORAL CHANGE** from pre-cycle (arguably safer — fewer transient vote drops on a transient detector fault), but STEP-EXCLUDE-2 (byte-identity) is violated on the D2-raise codepath. Reviewer A's `ledger_golden_replay` byte-identity assertion would flag it if a failure-tick fixture is present; if not, the drift ships silently and Reviewer D's D1.1 completeness pass finds it in the invariant surface.

Both readings survive the current text. A builder — under Auto Mode, or the ura-builder subagent — will pick one. The two readings ship materially different behavior on the "detector transiently raised" codepath.

**Ask:** §D1.1 point 3 must PICK ONE and say why. Recommendation: **Reading A (bookkeeping-only preservation, matches pre-cycle byte-identity strictly)** — because:
1. The B-MED-1 guard's original intent was to prevent a *recovered-NM storm*, not to add fusion engagement on the failure tick. Adding fusion re-engagement is a NEW behavior orthogonal to B-MED-1.
2. STEP-EXCLUDE-2 byte-identity is a load-bearing acceptance criterion; a behavioral change to the D2-raise codepath breaks it without an explicit exemption.
3. If the operator prefers Reading B (safer transient behavior), it should be a NAMED separate deliverable in a follow-up cycle with its own fixture (a "D2-raise fusion preservation" acceptance test), not smuggled in under the STEP D1 formalization.

Concrete rewrite for §D1.1 point 3 (drop-in):

> **`_d2_completed_cleanly` guard preserved, byte-identically.** The mid-detector exception guard at :2698-2705 preserves STUCK-SENSOR-1's OWN bookkeeping fields (`_dutycycle_excluded_last_tick`, `_dutycycle_excluded_now`) so the next tick's release-scan diff remains honest — this is the B-MED-1 semantics, unchanged. The `SensorExclusionSet` MIRROR is NOT re-populated on the failure branch (because the D1 promotion loop never ran and `reset_tick()` cleared the set at tick start) → this tick's fusion excludes only P22 entities, matching pre-cycle byte-identically. Builder MUST NOT add a compensating `promote("stuck_dutycycle", e)` in the failure branch — doing so is a behavioral change (fusion re-engagement) outside this cycle's scope. Reviewer A's `ledger_golden_replay` proves byte-identity on the D2-raise codepath if a failure-tick fixture is present; if not present, add one (a fixture where `_detect_duty_cycle_stuck` raises mid-loop for one tick) — this is now a required D1.1 acceptance fixture.

Add an explicit line to §D6 wire-in test 6: mutation-verify that the failure branch does NOT call `promote("stuck_dutycycle", e)` into `SensorExclusionSet` — a mutation adding such a promote MUST red a NAMED byte-identity test.

**Blocking?** Yes for build dispatch under Tier 3. This is a real ambiguity that would produce two different shipped behaviors under Auto Mode. Doc-only fix, <15 min.

### L-LOW-A — "Prefer the module OR helper class in coordinator.py" leaves location decision to builder in D1 and D2

Two instances:
- §D1 line 177: "new module `custom_components/universal_room_automation/domain_coordinators/sensor_exclusion.py` OR helper class in `coordinator.py`. Prefer the module — easier to test, keeps coordinator lean, matches sibling architecture."
- §D2 line 223: "new `ChatterDetector` in `coordinator.py` (or `domain_coordinators/chatter_detector.py` — prefer module for testability)."

Per FAN-MANUAL-1 precedent, plans that offer options where one is correct create builder churn. The rationale in both spots strongly favors the module; the plan should just SAY "new module" and drop the alternative. `sensor_role.py` / `sensor_capability.py` set the sibling precedent already.

**Ask:** replace "OR / (or … — prefer)" with the definitive picks in both places.

**Blocking?** No. But under Tier 3, the plan-review discipline is to close every avoidable ambiguity.

### L-LOW-B — Substrate `subscribe()` teardown for `ChatterDetector` is not spelled out

§3.1 line 109 says `OccupancySubstrate.subscribe(cb)` at `occupancy_substrate.py:764-783` is REUSED, and cites "Bug Class #38 discipline inherited" — but that citation is specifically about not re-registering a new `async_track_state_change_event`, not about the subscribe/unsubscribe lifecycle. The plan does not state:
- Whether `substrate.subscribe(cb)` returns an unsubscribe callable that must be stored.
- Where the unsubscribe is called on RoomCoordinator teardown / config-entry unload.
- Whether a room-entry reload (individual room entries CAN reload; the CM reload-suppression covers the parent) risks leaking a stale `ChatterDetector` callback into the substrate's subscriber list.

Bug Class #38's shape (dispatcher subscription-cleanup trap) applies here even though the citation framed it narrowly.

**Ask:** §D2 add one line: "`ChatterDetector` stores the unsubscribe callable returned by `substrate.subscribe(cb)` and calls it on `RoomCoordinator.async_will_remove_from_hass()` (or equivalent teardown hook). Reviewer B verifies no leaked subscribers survive a room-entry reload — add a lifecycle test."

**Blocking?** No. But the Tier-3 Reviewer B charter already owns "async / lifecycle / restart semantics", so this is more a plan-completeness patch than a blocker; still worth naming so the builder wires teardown in-cycle instead of Reviewer B catching it as a HIGH.

---

## 3. Tier-3 completeness spot-checks

- **Falsifiable invariant stated for Reviewer D:** yes, at plan top and restated in §9. Falsifiable, discriminating, quantitative (sub-`T_floor` event count).
- **Parked-plan triggers this cycle would fire:** `STUCK-SENSOR-1` and `SENSOR-CAPABILITY-1` are explicitly re-parented under STEP (§3.3 + §11); no unlisted parked plan is triggered. `SUBSTRATE-STUCK-FILTER-1` and `STUCK-D2-DEMOTION-ROLE-MIGRATE-1` are correctly deferred with explicit rationale (§0.5, §10). The sibling detector cards (`CHATTER-CAMERA-CONFIDENCE-FLAP-1`, `SENSOR-MULTISTATE-FAULT-1`) are named at §D2 point 1 for coverage-limit follow-up. ✅.
- **D1/D2-together vs stuck-migration-deferred cut still correct:** yes — Plan Review 1 §4 verified the demotion-role-migration touches the LATCH not the exclusion PROMOTION, so it does not gate D1. Confirmed by re-read of `_promote_dutycycle_to_exclusion` at `:2141-2187`.
- **Listener-driven detection (fixes prior Nyquist-blind CRIT):** yes, `substrate.subscribe(cb)` at :764-783 is the correct mechanism per §D2 algorithm step 1. Teardown gap is L-LOW-B above.
- **Anti-hollow test mandate:** §D6 requires per-site source mutation with `PYTHONDONTWRITEBYTECODE=1` + cleared `__pycache__` (feedback_mutation_verification_pycache_staleness compliant), for the 4 chatter drills + 6 consumer sites + 1 release-scan failure branch (11 mutations, named-test reds required). Test 5 (parameterized over 6 consumer sites) drives real production. Test 6 pins §D1.1 failure branch. **Anti-hollow mandate satisfied.** Note: acceptance-test fabrication of `_chattering_entities = {"sentinel"}` (D6 test 2) is a wire-in-only stub, correctly scoped — the definition-anchored discriminator fixtures (D0 fixture: ratgdo positives + 30 physical negatives + camera group must-exclude) drive real production per §D2 acceptance criteria and INV-CHATTER-2.
- **Options-offered-where-one-is-correct:** the two module-vs-inline calls (L-LOW-A) are the only instances; the M-MED-2 amendment closed the classifier one. No other unresolved options survive.
- **Config-boundary / combinatorial testing per Tier-3 requirement:** §9 Review D charter (vi) explicitly names `K=1`, `K=0`, `T_floor=0`, `T_floor` absurdly large, per-sensor `T_floor=0` × genuinely-broken sensor. ✅.

---

## 4. Items that PASSED without change request

- M-MED-2 provenance classifier: fully specified — allow-list `(kind, provider)` tuples, deny-list explicit, ordering unambiguous, silent-default DENY, Reviewer-C fixture pinning of `binarygroup_camera_motion_zone1` and a hypothetical mislabeled Frigate entity.
- M-MED-3 K + T_floor: fully specified on the knob ladder with concrete values and kill-switch semantics.
- L-LOW-1 (Plan Review 1 stale "DEFERRED" marker on INV-CHATTER-2): fixed at §2.2 line 87.
- L-LOW-2 (Plan Review 1 sequencing/§11 phrasing): the joint-ship recommendation is now clean at §11.
- Fail-safe try/except around `ChatterDetector` and the callsite exception swallow (§D2 line 332) mirrors the shipped STUCK-1 D2 pattern at :2543 — no new fail-open regression surface.
- Producer/Consumer sections (§7) are complete and correctly separate trust-decision consumers from display consumers.
- Files-changed table (§8) is consistent with §3 REUSED / NEW ledger — no unexpected touches to `database.py`, `notification_manager.py`, `occupancy_substrate.py`, `_stuck_signal_nm.py`, `actuator_reconciler.py`. Matches shared-primitive scope.

---

## 5. Summary

| Severity | Count | Blocking for Tier-3 build dispatch? |
|---|---|---|
| CRIT | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 (M2-MED-1: §D1.1 point 3 failure-branch preservation ambiguity) | Yes — pick Reading A or B in the plan; do not leave to builder. |
| LOW | 2 (L-LOW-A module-vs-inline; L-LOW-B subscribe teardown) | No, but recommended to close under Tier-3 discipline. |

**Verdict: PLAN-NEEDS-FIXES.** Apply M2-MED-1 (recommend Reading A + add failure-branch mutation drill to §D6) plus L-LOW-A / L-LOW-B in-plan. No rescoping; ~30 min of doc edits. Then PLAN-READY for Tier-3 build dispatch under the §9 four-framing-disjoint protocol.

**Resolution of the three original MEDs — CONFIRMED:**
- M-MED-1 (release-scan interaction): correctly resolved on ordering, source-of-truth, and byte-identity; the residual failure-branch clause (M2-MED-1) is a narrower carve-out, not a re-open of the original finding.
- M-MED-2 (provenance classifier): fully resolved.
- M-MED-3 (K + T_floor on the knob ladder): fully resolved.

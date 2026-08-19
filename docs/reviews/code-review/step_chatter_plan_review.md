# Plan Review — STEP D1 (shared exclusion primitive) + D2 (physics chatter client)

**Doc under review:** `docs/planning/PLANNING_sensor_health_surfacing.md`
**Companions cross-checked:** `RESEARCH_sensor_chatter_definition_prior_art.md`, `PROBE_sensor_chatter_definition_handcheck.md`
**Tier:** 2-DB (operator-elevated, shared-primitive scope)
**Reviewer framing:** adversarial completeness — verify with greps, not trust; discriminate exclusion-primitive byte-identity + chatter-definition safety before build dispatch.
**Verdict:** **PLAN-NEEDS-FIXES** (3 MEDIUM, 2 LOW). No blocking CRIT/HIGH. Fixes are in-plan (no rescoping) and can be resolved in <1h of doc edits.

**Exclusion-primitive byte-identity verdict:** **PLAUSIBLE — with one under-specified interaction with the D1-release scan (M-MED-1) that must be clarified in the plan before build.**

**Definition-safety verdict:** **SAFE — un-fakeable criterion holds by construction on the blind-time-gated class; the provenance-gate coverage limit is real but correctly scoped (siblings carded), pending one classification-mechanism clarification (M-MED-2).**

---

## 1. Verification of the 6 filter sites + writers (Plan §0.1, §3.1)

Independently re-greped `stuck_sensors` in `coordinator.py`:

| Claim | Line | Verified |
|---|---|---|
| motion_detected filter | 2712 | ✅ `if sensor and sensor not in stuck_sensors` |
| presence_detected filter | 2719 | ✅ same shape |
| occupancy_detected filter | 2726 | ✅ same shape |
| any_sensor_active motion leg | 2740 | ✅ `... and sensor not in stuck_sensors and self._is_sensor_on(sensor)` |
| any_sensor_active presence leg | 2748 | ✅ same |
| any_sensor_active occupancy leg | 2756 | ✅ same |
| P22 writer (initial set) | 2498 | ✅ `stuck_sensors = self._p22_stuck_sensor_set(now)` |
| STUCK-SENSOR-1 D1 writer | 2569 | ✅ `stuck_sensors.add(s)` guarded by `_promote_dutycycle_to_exclusion` |
| Scope: no zone/house/HVAC read of `stuck_sensors` | — | ✅ grep across `domain_coordinators/`, `presence.py`, `hvac.py`, `sensor.py` — the only cross-file readers are DISPLAY-only aggregators in `sensor.py` (`:2355 attrs["stuck_sensors"]`, `:4834-4889` house-tier aggregator) and they read `_stuck_sensor_kinds` (the diagnostic map), NOT the fusion set itself. STEP-EXCLUDE-4 scope is real. |

**Additionally verified (not in plan) — the release-scan machinery.** `_dutycycle_excluded_last_tick` / `_dutycycle_excluded_now` at coordinator :341-344 and :2523-2705 (esp. B-MED-1 fix-up guard `_d2_completed_cleanly`) form a stateful per-tick reconciliation between the previous tick's engaged set and the current tick's engaged set — recovered-NM emission depends on it. This is NOT called out in the plan and drives M-MED-1 below.

**No existing `SensorExclusion*` or `chatter*` code found** in `custom_components/` (all `flap`/`chatter`-family hits are actuator-side and unrelated). §3.2 NEW justification for the primitive stands.

---

## 2. Un-fakeable definition — safety verdict

- Probe doc `PROBE_..._handcheck.md`:127-198 corroborates §D2's three amendments. GO-with-amendments is the correct read — literal single-event form was NO-GO on the D0 hand-check (misses at small `T_floor`, false-fires 153/286 sensors). Amendments correctly derived.
- **Provenance gate correctly derived** (Probe:78-82 + 185-189): applies ONLY to sensors gated by a single physical hardware blind-time (PIR / mmWave / opener / reed). Camera/AI, aggregates, bed multistate are undefined for the criterion — correctly excluded, correctly carded as separate detectors (`CHATTER-CAMERA-CONFIDENCE-FLAP-1`, `SENSOR-MULTISTATE-FAULT-1`).
- **Coverage-hole check:** could a *real chattering* sensor be **wrongly excluded** by the gate? Yes — a chattering camera-AI or a chattering aggregate would be missed by this detector. This is not a definition bug (their physics doesn't admit a sub-`T_floor` criterion); it is a scope limit and the plan correctly cards siblings for it. Not blocking.
- Could a *non-blind-time* sensor be **wrongly included**? By construction no — the gate is a positive inclusion filter. But this depends on a reliable classification mechanism (see M-MED-2 below).
- **`T_floor` non-circular** (§D2 point 2, Probe:136-142): ladder is device-class default → datasheet/Zigbee min-report override → learned p1-p5 from a KNOWN-HEALTHY DIFFERENT reference unit. Never from suspect's own history. Non-circular. Good.
- **K discriminates by kind, not by rate** (§D2 point 3): K counts sub-floor impossibility events (>0 real, ≈0 healthy) not transitions. Preserves the "never a raw rate" operator constraint — a busy hallway PIR firing thousands of times above its floor earns zero penalty. Confirmed by probe:198 ("every healthy sensor in the ...").
- **Listener-driven, not per-tick sampled** (§D2 algorithm, `substrate.subscribe()` at `occupancy_substrate.py:764-783` — verified): fixes the prior build's Nyquist-blind per-tick CRIT. Good.
- **Chatter's independence from SENSOR-CAPABILITY-1** (§0.2): confirmed. The detector's dependencies are `substrate.subscribe`, `_d2_boot_settle_done`, and a device-class classifier. Corroborator role (`resolve_role`) is NOT consumed. `sensor_capability` is used ONLY as an *optional* per-hardware override rung (§5) — build can ship with device-class defaults alone. Feasibility claim holds.

---

## 3. Falsifiable invariants & fixture discrimination

- STEP-EXCLUDE-{1..4} + INV-CHATTER-{1,3,4} are stated in falsifiable form. INV-CHATTER-2 shape is fixed and now anchored by the D0 fixture list (ratgdo positives + 30 physical negatives + camera group must-exclude) at §D2 "Live acceptance fixture" — this discriminates: identical or higher raw rate on the healthy side, but sub-floor event count `==0` vs `>150`. Genuine discriminator.
- The discriminating fixture requirement ("same raw rate, opposite outcomes") is met because "raw rate" and "sub-floor event count" are decoupled by construction. Reviewer D will falsify STEP-EXCLUDE-{1..4} across every consumer + every client (Bug Class #53).
- Boot-settle gate + fail-safe try/except pattern mirror shipped STUCK-SENSOR-1 D2 shape at :2543. No regression surface introduced.

---

## 4. Sequencing (D1+D2 together; stuck-migration + siblings deferred)

- Correct cut. Shipping D1 alone would prove the multi-writer contract with only pre-existing writers (P22 + STUCK-SENSOR-1 D1) — a formalization without a NEW writer test. Chatter is the first independent NEW writer that validates the client-isolation contract (STEP-EXCLUDE-3). Ship-together also lets Reviewer C run the per-client-release mutation drill against genuinely-two-client fixtures.
- Deferring `STUCK-D2-DEMOTION-ROLE-MIGRATE-1` is correct — it affects the demotion LATCH not the exclusion PROMOTION (verified — the D1 promotion `_promote_dutycycle_to_exclusion` at :2141-2187 does its own corroborator arithmetic and does not depend on the outstanding `_d2_motion_sensors_present` role migration).
- Deferring `SUBSTRATE-STUCK-FILTER-1` is correct — plan explicitly acknowledges the residual seam (§0.5) inherited from STUCK-SENSOR-1.

---

## 5. Findings

### M-MED-1 — Release-scan interaction with `reset_tick()` is not specified in the plan

The plan (§D1 API) introduces `reset_tick()` to clear tick-scoped promotions at tick start and requires each writer to re-promote what it wants. But `coordinator.py:2523-2705` maintains a stateful per-tick reconciliation for STUCK-SENSOR-1 D1 releases:

- `_prev_excluded = set(self._dutycycle_excluded_last_tick)` snapshotted BEFORE the D2 detector runs.
- Recovered-NM emission scans `_prev_excluded - set(self._dutycycle_excluded_now)` at :2669.
- The mid-detector exception guard (`self._d2_completed_cleanly`, B-MED-1 fix-up dated 2026-08-13) exists specifically to prevent a mass-release NM storm on partial detector failure.

The plan says the migration is "byte-identical" but does not spell out:
1. Whether `SensorExclusionSet.provenance()` becomes the source-of-truth for STUCK-SENSOR-1's `_dutycycle_excluded_now` snapshot (in which case the release-scan must be re-plumbed to read from provenance), OR the local `_dutycycle_excluded_now` remains authoritative and `SensorExclusionSet` is a downstream mirror.
2. When `reset_tick()` runs relative to the `_prev_excluded` snapshot at :2533 and to the `_d2_completed_cleanly` guard.
3. How `SensorExclusionSet.release("stuck_dutycycle", ...)` interacts with the fail-open "preserve engaged exclusion set" branch at :2698-2705.

**Ask:** in §D1, add a subsection "Interaction with STUCK-SENSOR-1 D1's release-scan" (~15 lines) that fixes the ordering and names the source-of-truth. Recommend: local `_dutycycle_excluded_now` stays authoritative for STUCK-SENSOR-1's own recovered-NM emission (single-writer, single-owner), and `SensorExclusionSet.promote/release` is the fusion-time gate only. The B-MED-1 guard MUST NOT be regressed.

**Blocking?** No — the plan is buildable; a builder who misses this ships a recovered-NM regression. Fix is a plan-doc paragraph, not a rescoping.

### M-MED-2 — Classification mechanism for the provenance gate is under-specified

§D2 point 1 says the criterion applies only to "PIR / mmWave / opener (ratgdo) device classes" — but does not spell out the exact classifier the builder should use. Options implicit in the plan:
- HA `device_class` attribute on the entity — but many URA-in-scope entities have inconsistent/missing device_class (e.g. `binarygroup_camera_motion_zone1` HAS `device_class=motion` and would slip past a naive filter).
- URA-side `sensor_capability` mapping — but plan says capability is an *optional* override rung.
- An explicit URA allow-list keyed by `_KIND_TO_CONF` bucket + entity-attribute heuristics.

The founding negative-example in the plan (`binarygroup_camera_motion_zone1` 14,216 sub-0.5s events working AS DESIGNED) IS itself a `motion` device-class entity — so `device_class=='motion'` alone would false-fire on it.

**Ask:** §D2 point 1, add one paragraph naming the exact classification mechanism (recommend: URA-side allow-list of `(kind, provider_regex_or_capability)` tuples, defaulting to PIR/mmWave/opener, with a documented deny-list for camera-motion / aggregate / bed_state / multistate). Reviewer C must include a fixture asserting `binarygroup_camera_motion_zone1` is CLASSIFIED as camera-family and not scored, regardless of its `device_class`.

**Blocking?** No — but a builder shipping only `device_class=='motion'` would false-quarantine the biggest false-positive class in the D0 dataset (camera groups) and the coverage-hole check would fail on Live Validation.

### M-MED-3 — K on the knob ladder is not explicit in §5

§5 table has `CHATTER_RELEASE_QUIET_S` and `CHATTER_QUARANTINE_ENABLED` explicitly, then a catch-all row "Any per-edge / per-window / per-dwell chatter thresholds — TBD per D0 research — Rung 1 by default". K is technically covered, but K is called out in §D2 point 3 as "build-time knob, rung-1" — it deserves its own row so reviewers can verify the rung. Also, T_floor per-family DEFAULTS (the "1-3s band" from probe:163) belong on the ladder explicitly.

**Ask:** in §5, promote K and per-family T_floor defaults into named rows (Rung 1 module const), with kill-switch semantics for `T_floor=0 per sensor` restated in the row.

**Blocking?** No — LOW-adjacent MEDIUM; makes reviewer / builder job easier.

### L-LOW-1 — INV-CHATTER-2 says "DEFERRED" while the plan body has the fixture

INV-CHATTER-2 at §2.2 reads "DEFERRED to the research doc" — but §D2 now carries the concrete fixture list (positives, negatives, must-excludes). Update INV-CHATTER-2 to reflect that the fixture is now specified in §D2 (post-hand-check) and drop the DEFERRED marker. The doc's own top-line ("The chatter DEFINITION is TBD-pending that research") at :10 is likewise stale and should be updated to "GROUNDED + HAND-CHECKED (D0 GO-with-amendments)".

### L-LOW-2 — §0.4 sequencing recommendation vs §11 operator-decisions phrasing

§0.4 recommends D1+D2 together and §11 says operator decision "None". Fine, but §11 point 1 phrasing "STEP D1 + D2 ship in one cycle (§0.4); D0 (research + probe) blocks D2 not D1" is somewhat ambiguous about whether D1 could technically ship WITHOUT D2 (yes, but the plan doesn't want it to). One-line clarification: "recommendation is joint ship; splitting would require Reviewer A to re-verify the client-isolation contract with only pre-existing writers and would defer STEP-EXCLUDE-3 validation."

---

## 6. Items that PASSED review (no fix requested)

- Feasibility claim: chatter has no dependency on SENSOR-CAPABILITY-1 (verified — only substrate.subscribe + boot-settle + classifier).
- STEP-EXCLUDE-4 scope claim (grep-verified: no zone/house/HVAC reader of `stuck_sensors`).
- Corroboration REMOVED from chatter detection AND release (§D4) — physics-based un-fakeable criterion makes corroboration net-negative; two failure modes correctly enumerated (anchor-is-broken, no-PIR rooms).
- Fail-safe try/except mirroring shipped STUCK-SENSOR-1 D2 pattern at :2543.
- Auto-release symmetry with `ActuatorReconciler.check_quarantine_release` at `actuator_reconciler.py:949-1000` (unavailable-during-release check preserved).
- Per-day NM latch + explicit recovered-NM discharge (`feedback_suppression_needs_discharge` compliant).
- D6 wire-in drills (per-site source mutation with `PYTHONDONTWRITEBYTECODE=1` + cleared `__pycache__`, per `feedback_mutation_verification_pycache_staleness`).
- Files-changed table matches §3 REUSED / NEW ledger; no unexpected DB/notification/substrate writes.
- Institutional-context section is thorough (grep evidence for every REUSED / NEW addition, 6 prior planning docs consulted, memory bodies cited).

---

## 7. Summary

| Severity | Count | Blocking? |
|---|---|---|
| CRIT | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 3 (M-MED-1, M-MED-2, M-MED-3) | No — plan-doc edits only |
| LOW | 2 (L-LOW-1, L-LOW-2) | No |

**Verdict: PLAN-NEEDS-FIXES.** Apply M-MED-1..3 + L-LOW-1..2 in-plan; then PLAN-READY for build dispatch under Tier 2-DB (three framing-disjoint reviews + Live). No rescoping required. Exclusion-primitive byte-identity is achievable given M-MED-1 clarification; chatter definition is safe by construction given M-MED-2 classifier spec.

Operator may consider Tier-3 elevation (fourth adversarial-completeness reviewer) given (a) the two prior DO-NOT-SHIP reviews on the initial scope and (b) the shared-primitive's blast radius across all rooms simultaneously — but this plan clears the Tier 2-DB bar as written once the fixes above land.

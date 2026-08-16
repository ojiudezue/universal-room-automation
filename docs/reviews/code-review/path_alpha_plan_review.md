# Plan Review — PATH-ALPHA LOST dissolution + memory writers (rev-2)

**Plan under review:** `docs/planning/PLANNING_path_alpha_lost_dissolution.md` @ commit `22c2863b3` (develop).
**Reviewer:** Adversarial Tier-2-DB plan review (framing-disjoint completeness + adversarial build-prediction, run solo).
**Date:** 2026-08-16.
**Verdict:** **CHANGES REQUESTED — do not dispatch to build until CRITs C1-C3 are resolved in-plan.**

The plan is well-scoped and the memory-boundary rationale is durable, but the D1 consumer inventory is a hypothesis the plan hasn't finished checking against source. An independent re-enumeration surfaced one falsifiable-invariant leak (person_state == "unknown" mis-classified as case-(a)) that a builder following the "one-line stamp swap" framing WILL introduce, plus two under-specified surfaces (path-β fate, BLE_SILENT display chain) where the plan hands the builder a choice where the correct answer is neither of the two obvious ones. Every CRIT is fixable inside the plan.

---

## Independent D1 consumer re-enumeration — delta vs plan

Ran `git grep -n "TRACKING_STATUS_\|tracking_status\|_tracking_active"` across the integration. Every hit inspected; delta vs plan's Institutional-Context listing:

| Site | Plan status | Reality |
|---|---|---|
| `aggregation.py:5286` default init `= TRACKING_STATUS_LOST` | Listed | OK; recomputed each tick, restart-safe. |
| `aggregation.py:5490-5525` — the elif chain that CLASSIFIES tick→status | **Not listed** | **BLE_SILENT arm missing.** See C2. |
| `aggregation.py:5531 / :5552 / :5554` — display/icon selectors | Plan says "add icon" at :5566 only | **Selectors at :5552-:5555 are `if ACTIVE / elif STALE`; BLE_SILENT falls through to no display arm.** See C2. |
| `aggregation.py:5187/:5242/:5908/:5933` — string-literal "active"/"lost" gates | Not listed | Attr consumers; behave as "not-active" for BLE_SILENT — safe by default but should be catalogued in the D1 artifact. |
| `binary_sensor.py:1556/:1578` — `== "active"` gates | Not listed | Same — safe default but must appear in D1 artifact. |
| `camera_census.py:2334` — `in (STALE, LOST)` tuple | Listed | Needs BLE_SILENT added to tuple; plan asserts but doesn't call out as required edit. |
| `fan_veto.py:233` — `== ACTIVE` | Listed | Post-cycle, ACTIVE fires from person_state-away too. See H1 (semantic redefinition risk). |
| `sensor.py:3017-3088` — writer + attr surface | Listed | OK. |
| `presence.py:169` (def `_tracking_active_or_lost_away`) + :5085 alias + :5147-5182 path-β denominator block + :5171-5182 `lost_away_persons` sensor attr | Plan: "may deprecate" | See C1 — the entire path-β block is not "byte-identical without helper"; it must either be deleted (with attr retirement + test migration) or retained with a different predicate. Plan must pick. |
| `presence.py:5136` log format string `f"tracking_status={info.get('tracking_status','unknown')}"` — feeds excluded_persons reason map | Not listed | Now emits `tracking_status=ble_silent` — feeds guest-FP diagnostic classifier at :5758 (D3's target). Confirm D3's ~5 LoC covers the new value. |
| `presence.py:294` in person_coordinator — `if tracking_status == TRACKING_STATUS_LOST` gate on lost-duration tracking | Listed as edit site | After the fix, that branch's caller stamps ACTIVE — the LOST-gate may be dead. See L1. |
| `person_coordinator.py:168` — "person entity not found" branch stamps LOST | Listed as edit site (`:168`) | Plan §Case-(c) implies this stays LOST. Explicit disposition needed. |
| `person_coordinator.py:394-432` — "no Bermuda sensor at all" branch (NOT the `area_sensor exists, no room` branch at :370) | Listed as `:428` | **Fires for BOTH home and away paths but has a SINGLE stamp at :428.** Plan's "one-line change" framing under-counts: this branch needs a conditional split (home → BLE_SILENT, away → ACTIVE), not a swap. See C3. |
| Tests: `test_v570_fixup_wiring.py`, `test_v570_guest_detection_trust.py`, `test_census_ble_cancel_unrecognized.py`, `test_cycle4_slim.py`, `test_v4714_1_forgotten_phone_hotfix.py` | Not listed | Test-migration for `_tracking_active_or_lost_away` deletion + BLE_SILENT enum absent from Deliverables. See M2. |

**Bottom line: plan's D1 inventory is directionally right but the elif-chain in aggregation.py, the four-way conditional split at :394-432, the log-string-fed guest-FP feed, and the test migration are not in the file list. The D1 artifact acceptance criterion ("second-pass reviewer greps find zero new hits") will fail without adding these to the enumeration up-front.**

---

## Critical findings (must fix in plan before build dispatch)

### C1 — I-α leak: `person_state == "unknown"` currently stamps LOST-away, will stamp ACTIVE-away post-fix, inflating trusted denominator with no actual away evidence

**Where.** `person_coordinator.py:352` and `:394` both branch as `if person_state.state == "home": ... else: ...` with `else` treated as "away". The HA `person.*` entity state can be `home`, `not_home`, `unknown`, or a zone name. **`unknown` and any zone-name that is not "home"** currently fall into the else branch and get stamped LOST with `location="away"` and `confidence=0.9`.

Post-fix (per plan §Case-(a) source 1), that else branch stamps `TRACKING_STATUS_ACTIVE` with `location="away", confidence=0.9`, `method="person_state"`. Every consumer that trusts ACTIVE-away — including path-α's new denominator — will count an "unknown"-state person as confidently away.

**Why this falsifies I-α.** I-α requires case-(a) to mean "unambiguous 'away' adjudication from ANY case-(a) source." `person_state == "unknown"` is unambiguously **no signal**, not "away" — it's exactly the case-(c) LOST condition the plan §Case-(c) already names ("no companion GPS input either — person entity itself is unknown"), but the classification code at :352/:394 does not distinguish it.

**Repro (legal config, reachable):** one-person install; HA companion app disabled or backgrounded such that `person.<name>` entity reports `unknown` (common on iOS after long background); Bermuda has no fix (fresh boot or BLE outage). Post-fix, path-α reads `all_tracked_persons_away == True` from ONE tracker whose actual location signal is `unknown`. House inference flips to away with confidence 0.9. Physical person is home.

**Fix required in plan:** rewrite §Case-(a) source 1 and §Case-(c) to specify the classification branches EXPLICITLY:
- `person_state.state == "home"` → BLE_SILENT (or LOST-narrowed per H2 below)
- `person_state.state == "not_home"` OR `person_state.state` matches a non-home zone → ACTIVE-away
- `person_state.state in ("unknown", "unavailable", None)` → LOST (case-c)

Then instruct the builder to convert BOTH else branches at :370-389/:422-432 from `if home / else` to a three-way conditional. This is not the "one-line stamp swap" the plan currently claims.

### C2 — BLE_SILENT is not consumer-complete in `aggregation.py`

**Where.** `aggregation.py:5490-5525` is the tick-driven CLASSIFIER that reads `person_info["tracking_status"]` and sets `self._tracking_status`. Its elif chain currently handles only ACTIVE/STALE/LOST. Adding BLE_SILENT to `person_coordinator` writes without adding an arm here means BLE_SILENT will (a) never be assigned by the classifier at :5490-5525 (a re-derivation from confidence/last_update — see :5490 onward), or (b) round-trip to the display selectors at :5552-:5555 which only test `== ACTIVE` and `== STALE` (BLE_SILENT gets no state/icon).

**Fix required in plan:** D2's file list must include the aggregation.py classifier block (:5490-:5525) AND the display selectors (:5531/:5552/:5554/:5566) as REQUIRED edits, not just "add icon at :5566." Alternatively, adopt H2 below and delete the enum entirely.

### C3 — Path-β fate is under-specified; "byte-identical without helper" is impossible

**Where.** `presence.py:5147-5182` builds `relaxed_persons` explicitly by iterating `person_data` and calling `_tracking_active_or_lost_away_local(info)` at :5162, then exposes `lost_away_persons` as a sensor attribute (:5171-5182). Plan §Ripple accounting says "DEPRECATE + delete" the helper and Review B expects "byte-identical without helper." Those two statements are inconsistent: if the helper's semantics move into path-α (case-(a) folded in), the RELAXED denominator becomes empty-of-purpose and the block should be deleted (with `lost_away_persons` sensor attribute retired and any dashboard consumer updated). If the block is retained with a different predicate, its behavior changes — not byte-identical.

**Fix required in plan:** pick one and state it as a D2 subtask:
- **(a) DELETE path-β block entirely** (5147-5182) + delete helper + retire `lost_away_persons` attr + migrate/remove `test_v570_fixup_wiring.py` cases that assert on it. State this as a Deliverable line, not a Ripple note.
- **(b) RETAIN path-β with a substitute predicate** — enumerate the predicate and describe when path-β fires that path-α wouldn't. Given the plan's argument that case-(a) is folded into path-α, this option should be justified or dropped.

Builder following the current wording will guess.

---

## High findings (fix in plan; not ship-blockers if resolved)

### H1 — Semantic redefinition of `TRACKING_STATUS_ACTIVE` is not called out as a consumer risk

`const.py:167` reads `TRACKING_STATUS_ACTIVE = "active"    # Recently updated by Bermuda`. Post-cycle, ACTIVE also fires from `person_state`-derived confident locations with no Bermuda involvement whatsoever. That is a semantic widening every "ACTIVE ⇒ has-a-Bermuda-fix" consumer must be re-checked against.

- `fan_veto.py:222-234` explicitly documents `ACTIVE` as the "trustworthiness signal" and only fires in AWAY/VACATION — plan says "correct by construction," which is true only because the house_state gate closes the loop. Reviewer must not miss that ACTIVE-via-person_state is now a fan_veto participant.
- The `method` attribute distinguishes `bermuda` vs `person_state` vs `bermuda_decay` — any dashboard filter that assumed ACTIVE implies method=bermuda breaks silently.

**Fix in plan:** add to D2 file-touch list: update `const.py:167-169` comments to document the new ACTIVE / STALE / (BLE_SILENT?) / LOST-narrowed semantics; add an Acceptance line "no consumer conflates ACTIVE with `method=bermuda`" so review A checks it.

### H2 — BLE_SILENT is design-optional and grows the vocabulary the plan itself argued against

For every consumer that matters to invariant I-α (the trusted denominator), BLE_SILENT and LOST-narrowed behave IDENTICALLY: both are excluded. The plan's stated marginal value is dashboard observability (an icon distinct from LOST). That value is achievable without an enum addition, by carrying an `identity_reason` or `tracking_reason` attribute alongside `tracking_status`.

Costs of the enum addition (as C2 shows): every string-literal consumer (`== "active"`, `in ("stale", "lost")`, elif chains, sensor attr writers, tests) must be swept and updated. The plan's own §Design choice #1 argument against "many enums" applies here.

**Marginal-benefit decomposition (per CLAUDE.md):** simplest alternative — case-(b) stays LOST (semantically "location-uncertain" merged with case-(c) "identity-uncertain"), and a `tracking_reason` string attribute captures the finer distinction for the dashboard. Zero enum growth, zero consumer sweep for BLE_SILENT, D1 shrinks materially.

**Fix in plan:** either (a) justify the enum explicitly against the attr-only alternative in a §"Why BLE_SILENT is worth the sweep" subsection; or (b) collapse to attr-only and update D2 accordingly. Reviewer preference is (b).

### H3 — `tracker_trust_excluded` (D6) writer trigger is per-tick diff; I-M bound is unverified

Trigger is diff of `self._excluded_persons` at `presence.py:5207` vs. prior snapshot. `_excluded_persons` is REBUILT EVERY presence tick (:5097 initialization, :5207 assignment). Any input flap that flips a person in/out of the exclusion map — Bermuda burp, `_phone_trustworthy` transient — writes an EDGE row.

Pathological days that reproduce today:
- Bermuda flapping ACTIVE ↔ no-fix at 30s intervals during a range-boundary walk → 2 edges per burp per person → 4 persons × 60 flips/hour = ~10K rows/day, not "~10/day."
- Phone-left-behind detector flapping (documented pattern in the fan-noise / mmWave-shake incident family) → similar.

Plan's I-M claim "~10/day worst case" is unsubstantiated. Fix must specify a rate-limit: e.g. require the exclusion state persist ≥K ticks (or ≥T seconds) before writing an edge (per Bug Class "Suppression Needs a Discharge" — the debounce must be discharge-safe on the trailing edge). Test fixture must fire the trigger 60× in a synthetic minute and assert row-count ≤ N (I-M literal).

### H4 — `house_state_transition` (D7) writer boot behavior unspecified

Plan says "mirrors house_state_log's own edge semantics." But `house_state_log` accepts boot-time transitions (RestoreEntity → computed value on the first post-boot tick can look like a state change). Plan does not specify:
- Whether the first transition-per-restart is suppressed (boot-storm guard) or emitted with a `trigger="boot"` marker.
- Whether the `gate_inputs` snapshot at boot (before other coordinators have populated) is meaningful or partially-null.

Fix in plan: add an explicit boot-behavior clause under D7 acceptance + a fixture that restarts mid-day and asserts the boot-emission is suppressed OR distinguishably tagged.

---

## Medium findings

### M1 — I-α source list wording is internally inconsistent

I-α item 3 names "Bermuda-STALE with last-known `location=='away'`" (POST-classification stamp). Item 2 names "Bermuda-LOST with `person_state=='away'`" — but that combination NO LONGER STAMPS LOST after the fix; it stamps ACTIVE. Restate I-α in terms of the pre-classification signal conditions (which HA/Bermuda inputs are true at read time), consistently — otherwise it's technically vacuous in one clause.

### M2 — Test migration is not a Deliverable

`quality/tests/test_v570_fixup_wiring.py` and `test_v570_guest_detection_trust.py` reference `_tracking_active_or_lost_away` and the WS-A1 relaxed-denominator surface. `test_census_ble_cancel_unrecognized.py`, `test_cycle4_slim.py`, `test_v4714_1_forgotten_phone_hotfix.py` reference TRACKING_STATUS_* constants. Deleting the helper (C3(a)) or adding BLE_SILENT (H2 unless collapsed) requires test edits. Add a Deliverable line "D-tests: migrate `_tracking_active_or_lost_away` callers + add BLE_SILENT-vs-LOST-narrowed fixture coverage."

### M3 — `_person_was_away` and `_lost_away_since` bookkeeping preservation is not called out

The BLE pre-arrival machinery (`person_coordinator.py:248-285`) depends on `_person_was_away` being set at :391 in the away-stamping branch. A builder rewriting :370-389 to stamp ACTIVE could easily forget the flag write. Add a "must preserve" note under D2 with a mutation-drill acceptance: neuter the `_person_was_away = True` write at :391 and confirm a specific test reddens.

### M4 — Log-string-fed guest-FP diagnostic classifier (D3) coverage

`presence.py:5136` builds the reason string `f"tracking_status={info.get('tracking_status','unknown')}"` — post-cycle this emits `tracking_status=ble_silent`. D3 says "~5 LoC" for the diagnostic classifier at :5758. Confirm the classifier is enumerating exact-match strings (not substring-match on "lost") so BLE_SILENT and LOST-narrowed both feed correctly.

### M5 — `person_coordinator.py:168` (person-entity-not-found) disposition

Plan enumerates it as a writer site but does not disposition it in §Case-(a)/(b)/(c). Explicit statement needed: this branch stays LOST (case-c) because both identity and location are unknown. One line in the plan; forestalls a builder question.

---

## Low findings

### L1 — `person_coordinator.py:294` (`if tracking_status == TRACKING_STATUS_LOST`) may be dead post-fix

The gate at :294 fires inside the Bermuda-area-resolved branch where :228 has just stamped ACTIVE. Post-fix, the gate at :294 checking LOST inside a branch that stamped ACTIVE is dead. Either delete or comment.

### L2 — `const.py:167-169` comments not in file-touch list

See H1 — add to D2's file list.

### L3 — Non-goal wording

Non-goal "Does NOT rename `TRACKING_STATUS_ACTIVE`" is true, but the semantic widening (H1) is a change in what ACTIVE means. Consider adding "DOES semantically widen ACTIVE to include person_state-derived confident locations; the string identifier is unchanged."

---

## Falsifiable-invariant D-completeness check

Re-enumerated the reachable configuration space against I-α:

- **Single-person install:** OK if C1 fixed.
- **Multi-person mixed sources:** OK if D1 covers all four case-(a) source types + the case-(c) unknown split.
- **Brand-new install (zero Bermuda fixes ever):** OK; falls into the no-Bermuda-sensor branch at :392 → case-(a) via person_state if state=="not_home"; case-(c) if state=="unknown". Depends on C1 fix.
- **Restart re-hydration:** aggregation.py :5286 defaults to LOST at construction; tick recomputes. Safe. D7 boot-transient is H4.
- **Phone-left-behind × case-(a):** phone_trustworthy filter runs BEFORE the tracking filter in the ACTIVE denominator; excluded persons are excluded regardless of ACTIVE-via-person_state. Safe.
- **Guest-mode arm/disarm:** D3 rider covers the residual reason-string; unclear whether guest-detection consumers key on "lost" substring — needs to be checked against the guest-FP fix wiring audit at build time. Adjacent to M4.

**I-α holds IF C1, C2, C3 are resolved.** As written, I-α is falsified by C1's unknown-state repro.

---

## Suggested plan patch (minimum diff to unblock dispatch)

1. **Restructure §Case-(a) sources to enumerate person_state values explicitly** ("home" / "not_home" / zone-name / "unknown" / "unavailable") and state the stamp for each. Adopt C1 fix.
2. **Replace §"Ripple accounting" bullet on `_tracking_active_or_lost_away`** with a D2 sub-deliverable that either deletes the path-β block wholesale (5147-5182 + helper + attr + tests) OR retains it with a specified predicate. Adopt C3(a).
3. **Add to D2 file-touch list:** `aggregation.py` classifier block (:5490-:5525), display selectors (:5531/:5552/:5554), `const.py:167-169` comments, log-string check at `presence.py:5136`.
4. **Decide BLE_SILENT vs. attr-only** per H2 and update the enum discussion + all downstream consumer edits accordingly.
5. **Add rate-limit clause to D6** per H3 (min-hold before edge write, plus a fixture asserting row-count under flap).
6. **Add boot-behavior clause to D7** per H4.
7. **Add D-tests deliverable** per M2.
8. **Restate I-α** per M1.
9. **Add one-line dispositions** for :168 (M5) and preservation notes for `_person_was_away` (M3).

Ship-blocker set: C1, C2, C3. Everything else is fixable at build-time review but cheaper to fix in the plan now.

---

## Reviewer's summary

Plan is 80% there. The strategic direction (dissolve LOST by re-stamping case-(a) at the source rather than adding relaxed-denominator machinery downstream) is right, the memory-boundary rationale is durable and worth keeping in the corpus, and the four writers are within-intent per the vision/architecture docs. The 20% that isn't done is the D1 completeness: an independent grep + a hostile look at `person_state`'s value space produces one certain invariant leak (C1), and the "one-line stamp swap" framing conceals two other under-specified surfaces the builder will guess wrong on (C2, C3). Fix those three in the plan, address the H-tier attribute-vs-enum question, dispatch to build.

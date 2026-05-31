# PLANNING v4.7.15.1 — Refactor Pattern A to Consume v4.7.14.1 H1/H2/H3 Surfaces + Update Source Invariants

**Tier:** 2-DB (operator-elevated — three parallel reviewers with disjoint framings)
**Status:** Planning — institutional context verified against the integration worktree
**Predecessors merged:** v4.7.14 (shipped), v4.7.14.1 (shipped), v4.7.15 D1-D6 (shipped)
**Integration base:** `/tmp/ura-v4715-1-integration` @ branch `integration-v4715` @ SHA `d654114`
**Master link doc:** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` — UPDATE in D0 to add v4.7.15.1 to the cycle list
**Estimated size:** ~80-120 LoC production (mostly deletions/consolidation) + ~50 LoC test updates
**Successor (out of scope):** v4.7.16 room-level Pattern F + density weighting (already on a sibling branch — do NOT touch here)

---

## 0. Institutional context — verified before scoping

Every assertion below was verified by reading the integration base worktree in this session. Cite `file:line` for every architectural claim. Where a claim could not be verified deterministically, marked `[verify in build]`.

### 0.1 Integration base SHA + branch state

- Worktree: `/tmp/ura-v4715-1-integration`
- Branch: `integration-v4715`
- SHA: `d654114`
- Composition: `develop + v4.7.14.1 + v4.7.15` merged, with the predicted `__init__` field-block "include both" conflict resolved.
- v4.7.15.1 will build off this base. The cycle does NOT re-introduce conflicts; it consolidates the parallel paths that the merge necessarily left in.

### 0.2 v4.7.14.1 H1/H2/H3 surfaces (verified file:line in integration base)

| Surface | Location (integration base) | Verified |
|---|---|---|
| H1 — `census_count == 0` clause added to `infer()` veto predicate | `presence.py` — `StateInferenceEngine.infer()` body, veto branch — string `"all_tracked_persons_away and unidentified_count == 0 and census_count == 0"` present | YES |
| H2 — `_phone_trustworthy(person_name)` helper | `presence.py:2267-2293` (inline `def` inside `_run_inference`). Resolves entity_id via entity registry by unique_id `f"{DOMAIN}_person_{slug}_phone_left_behind"`. Fail-OPEN on missing entity (sensor disabled by default per `binary_sensor.py:988`). | YES |
| H3 — `_tracking_active(info)` helper | `presence.py:2295-2306` (inline `def`). Returns `info.get("tracking_status", TRACKING_STATUS_ACTIVE) == TRACKING_STATUS_ACTIVE`. Default-ACTIVE keeps the v4.7.14 baseline for older-shape entries. | YES |
| `_tracked_persons_count` (raw, pre-v4.7.14.1 semantic) | `presence.py:2364` — `self._tracked_persons_count = tracked_count_raw` | YES |
| `_tracked_persons_count_trusted` (post-filter) | `presence.py:2365` — `self._tracked_persons_count_trusted = tracked_count` | YES |
| `_excluded_persons` (dict `{name: reason}`) | `presence.py:2369` — `self._excluded_persons = dict(excluded_persons)` | YES |
| `tracked_count_raw` / filtered `tracked_count` flow | `presence.py:2318-2350` — per-name loop populates `trustworthy_persons` + `excluded_persons` with precedence: `phone_left_behind` reason wins over `tracking_status` reason when both fire | YES |
| Veto-fired INFO log (A-M1/A-M3 enriched) | `presence.py:2467-2494` — log is gated on `all_tracked_persons_away AND unidentified_count == 0 AND census_count == 0 AND any_zone_occupied AND new_state == AWAY AND current_state != AWAY` — gate is post-filter | YES |

### 0.3 v4.7.15 D1 shared helper — current state (verified file:line in integration base)

- Definition: `presence.py:728-857` — `def should_veto_due_to_reliable_signals(self, *, reliable_signals, transient_signals, state_context) -> VetoDecision:`
- Dispatch by `scope` string: `"house_inference"` (Pattern A, lines 756-772), `"zone_aggregator"` (Patterns B+C, 774-802), `"waking_transition"` (Pattern D, 804-820), `"guest_exit"` (Pattern E, 822-842), unknown fall-through returns `VetoDecision(False, 0.0, "", scope)` (line 857).
- **Pattern A as currently shipped (lines 755-772) — verbatim signature:**
  ```python
  if scope == "house_inference":
      all_away = any(s.kind == "person_tracker_away" and s.value for s in reliable_signals)
      any_home = any(s.kind == "person_tracker_home" and s.value for s in reliable_signals)
      unid = next((s.count for s in transient_signals if s.kind == "unidentified_person_count"), 0)
      if tracked_count > 0 and all_away and not any_home and unid == 0:
          return VetoDecision(True, 0.95, "all_tracked_persons_away (no guests)", scope)
      return VetoDecision(False, 0.0, "", scope)
  ```
- **Critical gap:** Pattern A does NOT consume `census_count`, `phone_left_behind`, or `tracking_status`. It is a faithful reimplementation of v4.7.14's *pre-v4.7.14.1* veto. This is exactly the gap Reviewer C of v4.7.14.1 surfaced as C4 (merge-order recommendation) — see `docs/reviews/code-review/v4.7.14.1_review_C_test_authority_merge_risk.md:340-489`.

### 0.4 Parallel Pattern A invocation added by v4.7.15 fix-up (verified)

- Site: `presence.py:2496-2528` (inside `_run_inference`, after the inline v4.7.14.1 veto block at 2467-2494, after `infer()` returns at 2449-2456).
- Behaviour: builds `ReliableSignal/TransientSignal` from the *raw* `all_tracked_persons_away` + post-filter `tracked_count`, calls the shared helper, writes the result to `self._last_veto_decision` IFF `house_inference_decision.fired` is True. **Pure diagnostic side-effect — does NOT change `new_state`.**
- The fix-up comment at `presence.py:2502-2504` literally says: *"v4.7.14.1 hotfix surfaces (H1/H2/H3 — phone-left-behind, tracking_status, census_count predicate) are NOT yet plumbed through the helper; v4.7.15.1 will refactor Pattern A to consume them per Reviewer C C3."*
- **This is the parallel path v4.7.15.1 D1 consolidates.**

### 0.5 Reviewer C of v4.7.14.1 — explicit instruction for this cycle

`docs/reviews/code-review/v4.7.14.1_review_C_test_authority_merge_risk.md` — §C4 "v4.7.15 merge-order recommendation" (lines 340-489). Verbatim instructions to the v4.7.15.1 builder (item numbers from §C4):

1. *"Update v4.7.15 D1 Pattern A to consume the H1/H2/H3 surfaces."*
   - Add transient signal kind `"census_count"`; treat `> 0` as veto-blocking. (H1)
   - Accept reliable signals of kind `"person_phone_trustworthy"` (per-person boolean); count only `True`. (H2)
   - Accept reliable signals of kind `"person_tracking_active"` (per-person boolean); count only `True`. (H3)
   - Preserve the `tracked_count > 0` fail-safe guard against the FILTERED count, not raw.
2. *"Reduce the v4.7.14.1 inline helpers to one-liners"* — the `_phone_trustworthy` / `_tracking_active` local `def`s in `_run_inference` (`presence.py:2267-2306`) become **input builders** for the helper. Production semantics are unchanged.
3. *"Update the v4.7.14.1 cycle tests"* at `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:485-506, 666-676` — the source-string invariants that look for `_phone_trustworthy` / `_tracking_active` literal substrings will fail after extraction. Reviewer C §C1 calls these the **deliberate trip-wires** — they exist precisely to force this cycle to update them.
4. *"Re-run BOTH cycles' tests"* after extraction — H1/H2/H3 functional assertions on `engine.infer(...)` MUST still pass (they're production-direct); v4.7.15 helper Pattern A tests get expanded; all 24 v4.7.14 baseline tests + all 17 v4.7.2 D5/B1 tests must still pass.

### 0.6 Currently-failing tests on the integration base

Per operator brief — to be re-verified by the builder in `/tmp/ura-v4715-1-integration` via:

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_v4715_*.py -q
```

| Test | Location | Root cause | Fix surface |
|---|---|---|---|
| `TestSiblingCyclePreservation::test_v4714_inference_engine_veto_branch_intact` | `quality/tests/test_v4715_universalize_veto.py:777-780` | Asserts the literal substring `"all_tracked_persons_away and unidentified_count == 0"` in `PRESENCE_SRC`. v4.7.14.1 H1 changed the production line to `"all_tracked_persons_away and unidentified_count == 0 and census_count == 0"`. The OLD substring is no longer a standalone line — it's a prefix of the new line. **Whether Python's `in` operator finds it depends on whether the production code keeps the prefix as a contiguous substring**, which it does (the `and census_count == 0` is appended). So this test may actually PASS as-is — **`[verify in build]`** by running the test on the integration base and recording actual pass/fail. If it passes, leave the assertion as a prefix-match (still proves v4.7.14 backbone present); if it fails (e.g., due to line break / whitespace), tighten the assertion to the post-v4.7.14.1 string. | D2 — update invariant to mirror post-merge canonical truth |
| `TestD3WakingSustainedSignal::test_waking_transition_uses_helper` | `test_v4715_universalize_veto.py:573-578` | Slices `body = PRESENCE_SRC[idx: idx + 12000]` starting at `async def _run_inference`. The WAKING gate landed at `presence.py:2540-2566` — `2540 - 2212 = 328` source lines after `_run_inference` start; at avg ~80 chars/line that's ~26 KB into the function — **well past the 12000-char window**. The assertion `"waking_transition" in body` returns False because the substring is outside the slice. v4.7.14.1's H2+H3 helpers (~1400 chars inserted between 2245-2306) compounded the offset. | D3 — widen window to 30000 chars (covers full `_run_inference` body post-merge with headroom) OR refactor to search the whole `PRESENCE_SRC` from a tighter anchor |
| `TestD3GuestExitPersistence::test_guest_exit_uses_helper` | `test_v4715_universalize_veto.py:585-590` | Same root cause as above — GUEST exit gate at `presence.py:2591-2607` is past the 12000-char window. | D3 — same window-widen |
| `TestD3GuestExitPersistence::test_guest_exit_reuses_guest_persistence_seconds` | `test_v4715_universalize_veto.py:592-595` | Same root cause — assertion text appears in the helper body and the `_run_inference` GUEST exit block, both past the 12000-char window. | D3 — same window-widen |

The three D3 failures share ONE root cause: the source-string window in the tests was sized against the v4.7.15-only function body length. v4.7.14.1's insertion of `_phone_trustworthy` + `_tracking_active` + the per-name filter loop pushed every downstream assertion target past the window. v4.7.14.1's Reviewer C §C3 already widened the v4.7.2 D5 / B1 tests' windows (7000→9000) for the same reason; the v4.7.15 cycle author didn't anticipate the compounding because v4.7.14.1 was on a sibling branch.

**Verification step in build:** before refactoring Pattern A, run the failing tests with `--tb=long` to confirm the root cause matches the analysis here. If a fourth, unexpected failure mode emerges, surface it before proceeding.

### 0.7 What is NOT a v4.7.15.1 concern

- v4.7.14.1 H1/H2/H3 *semantics* are canonical truth. Do NOT change them.
- v4.7.15 D2 (zone aggregator non-sleep Layer 3) is unchanged.
- v4.7.15 D3 GUEST exit + WAKING gate semantics are unchanged (only the test-window covering them needs widening).
- v4.7.15 D4 relocation of `check_zone_occupancy_confidence` is unchanged.
- v4.7.15 D5 `signal_consensus` calculation + sensor + mirror attribute is unchanged.
- v4.7.15 D6 HVAC + compliance defer gates are unchanged.
- v4.7.16 Pattern F (room-level weighted veto) — not added. The unknown-scope fall-through at `presence.py:844-857` continues to deliberately return `fired=False` for `scope="room_level_weighted"` per the comment block. **DO NOT ADD PATTERN F.**

### 0.8 Docs / memory consulted

- `docs/planning/PLANNING_v4.7.14.1_forgotten_phone_hotfix.md` — read in full (Sections 0-3, all of H1/H2/H3 acceptance + fixture authority section).
- `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md` — D1 helper signature, dataclass, acceptance criteria (lines 122-286 read this session).
- `docs/reviews/code-review/v4.7.14.1_review_C_test_authority_merge_risk.md` — read in full. §C1 (test fixture authority hybrid), §C4 (merge-order instructions to v4.7.15.1) are the load-bearing sections.
- `docs/reviews/code-review/v4.7.14.1_review_A_correctness.md` and `v4.7.14.1_review_B_signal_chain.md` — both pass-through APPROVE per file titles; spot-checked.
- Integration worktree source files cited inline above with file:line.
- Memory: `feedback_db_sensitive_3x_targeted_reviews.md` (Tier 2-DB protocol), `feedback_pre_deploy_zero_bugs_gate.md` (zero-bugs gate is mandatory), `feedback_no_soak.md` (no soak watching).

---

## 1. Cycle goal — one sentence

Make v4.7.15's shared Pattern A helper consume v4.7.14.1's H1/H2/H3 trust filters so the canonical Bug Class #48 veto logic lives in ONE place — the shared helper — with the v4.7.14.1 inline filters reduced to input builders, and re-baseline the v4.7.15 source-invariant tests against the post-merge production reality.

## 2. Scope summary

| Deliverable | Layer | Net new | Reuses |
|---|---|---|---|
| D0 | Update master link doc + planning bookkeeping | doc-only | `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` |
| D1 | Refactor Pattern A in shared helper to consume H1/H2/H3 surfaces + collapse the parallel diagnostic invocation | ~40 LoC delta in `presence.py` (mostly conversion of dict-comp + signal extension; net likely slight deletion) | v4.7.14.1's `_phone_trustworthy` / `_tracking_active` (now inputs to helper); v4.7.15 helper Pattern A shape |
| D2 | Update source-invariant tests in `TestSiblingCyclePreservation` to match post-v4.7.14.1 production string | ~5 LoC `test_v4715_universalize_veto.py` | `PRESENCE_SRC` substring assertions |
| D3 | Widen D3 helper-test source window to cover post-merge `_run_inference` length | ~6 LoC `test_v4715_universalize_veto.py` | `TestD3WakingSustainedSignal`, `TestD3GuestExitPersistence` |
| D4 | Delete now-redundant v4.7.14.1 local mirror tests (H2/H3 mirrors) and replace with direct production-helper calls or behavioral assertions | ~30 LoC delta in `quality/tests/test_v4714_1_forgotten_phone_hotfix.py` | Existing source-level invariants stay; mirror `_phone_trustworthy` / `_tracking_active` defs in test file are removed |
| Tests | New: Pattern A expanded-contract tests covering census_count, person_phone_trustworthy, person_tracking_active | ~50 LoC `test_v4715_universalize_veto.py` | Existing fixtures, `ReliableSignal` / `TransientSignal` dataclasses |
| **Total** | **~80-120 LoC prod + ~50 LoC test** | | |

**REUSE vs NEW.** All four deliverables are consolidation. No new CONF_*, no new sensors, no new switches, no new constants, no new entity surfaces. Existing v4.7.14.1 `_tracked_persons_count` / `_tracked_persons_count_trusted` / `_excluded_persons` and existing v4.7.15 `_last_veto_decision` / `_wake_blocked_ticks` / `_guest_exit_quiet_since` and existing `VetoDecision` / `ReliableSignal` / `TransientSignal` dataclasses are all reused as-is.

---

## 3. Deliverables

### D0 — Bookkeeping (planning only)

**Update** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` to add v4.7.15.1 to the cycle list with a 2-3 line summary: "consolidates v4.7.14.1 H1/H2/H3 into v4.7.15 Pattern A; re-baselines source invariants; Tier 2-DB." If the master link doc does not exist on the integration base, create it as a stub with v4.7.13 / v4.7.14 / v4.7.14.1 / v4.7.15 / v4.7.15.1 entries and add a TBD line for v4.7.16. **`[verify in build]`** — operator brief says "create alongside or in D0".

#### Acceptance Criteria — D0

- **Verify:** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` exists post-build and references v4.7.15.1 with cycle scope + Tier classification.
- **Verify:** This planning doc (PLANNING_v4.7.15.1_*.md) is committed to the cycle branch.

---

### D1 — Refactor Pattern A to consume v4.7.14.1 H1/H2/H3 surfaces

**Why.** Today the integration base has TWO places where the Bug Class #48 house-inference veto logic lives:
1. **Authoritative path** (drives `new_state`): inline at `presence.py:2256-2369` (v4.7.14.1's filtered `all_tracked_persons_away`) + `presence.py:` inside `StateInferenceEngine.infer()` (v4.7.14.1's H1 predicate). This is the path the production transition consumes.
2. **Diagnostic-only path** (writes `_last_veto_decision` for the sensor attribute): `presence.py:2496-2528` (the v4.7.15 fix-up parallel invocation), calling the shared helper with the v4.7.14-era signal set.

The shared helper's Pattern A does NOT incorporate v4.7.14.1's tightenings. v4.7.15.1 D1 brings the helper to parity, then **deletes the parallel invocation** because it is now redundant with the authoritative path also feeding the helper.

#### D1.1 — Extend Pattern A signal taxonomy

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`
**Site:** `should_veto_due_to_reliable_signals` Pattern A branch at lines 755-772.

**New signal kinds accepted** (no new dataclasses — just additional `kind` string values in existing `ReliableSignal` / `TransientSignal`):

| Signal type | Existing kinds | NEW kinds added |
|---|---|---|
| `ReliableSignal` | `person_tracker_away`, `person_tracker_home`, `zone_persons_home` | `person_phone_trustworthy` (boolean, per-person — one signal per tracked person) — H2 carrier; `person_tracking_active` (boolean, per-person — one signal per tracked person) — H3 carrier |
| `TransientSignal` | `unidentified_person_count`, `camera_person_detected`, `mmwave_occupied`, `pir_motion` | `census_count` (int) — H1 carrier |

**Pattern A logic after extension** (conceptual; builder writes the exact code):

```python
if scope == "house_inference":
    # H2 + H3 derive the TRUSTED tracked count.
    phone_trust = [s.value for s in reliable_signals if s.kind == "person_phone_trustworthy"]
    track_active = [s.value for s in reliable_signals if s.kind == "person_tracking_active"]
    # Per-person AND: phone_trustworthy AND tracking_active. The caller passes
    # one of each kind per tracked person (parallel order). If neither list is
    # populated, fall back to pre-v4.7.14.1 behavior (count all as trusted) so
    # callers that haven't been migrated continue to work.
    if phone_trust or track_active:
        # Length parity check: if lists are mismatched, fail-CONSERVATIVE
        # (count zero trusted, veto cannot fire).
        if len(phone_trust) == len(track_active) and len(phone_trust) > 0:
            trusted_count = sum(1 for p, t in zip(phone_trust, track_active) if p and t)
        else:
            trusted_count = 0
    else:
        trusted_count = int(state_context.get("tracked_count", 0))

    all_away = any(s.kind == "person_tracker_away" and s.value for s in reliable_signals)
    any_home = any(s.kind == "person_tracker_home" and s.value for s in reliable_signals)
    unid = next((s.count for s in transient_signals
                 if s.kind == "unidentified_person_count"), 0)
    # H1: census_count == 0 required for veto to fire.
    census = next((s.count for s in transient_signals
                   if s.kind == "census_count"), 0)

    if (trusted_count > 0 and all_away and not any_home
            and unid == 0 and census == 0):
        return VetoDecision(
            True, 0.95,
            "all_tracked_persons_away (no guests, no census, "
            f"trusted={trusted_count})",
            scope,
        )
    return VetoDecision(False, 0.0, "", scope)
```

**Key design points** (each must be reviewed):
- **Parallel-list contract for H2/H3.** Caller passes one `person_phone_trustworthy` and one `person_tracking_active` signal *per tracked person*, in the same order. The helper does positional zip. This is more compact than per-person scoped signals; alternative is a single composite per-person carrier — **`[verify in build]`** whether the builder prefers a named tuple (e.g., add a `subject` field to `ReliableSignal`). If the builder picks a different shape, surface to reviewers explicitly.
- **Fail-conservative on list mismatch.** Length mismatch → trusted_count = 0 → veto cannot fire. Preferred over silent misalignment.
- **Backward compat for callers without H2/H3.** When phone_trust + track_active are both empty (e.g., the v4.7.13 zone aggregator caller, which never has per-person trust data), Pattern A falls back to `state_context["tracked_count"]`. This preserves existing helper-call sites in `aggregation.py` (none for Pattern A today, but defensive).
- **`tracked_count > 0` fail-safe** now reads the FILTERED count, per Reviewer C C4 item 1d.

#### D1.2 — Authoritative path feeds the helper (replace parallel diagnostic invocation)

**Current state:** `presence.py:2496-2528` calls `should_veto_due_to_reliable_signals` with a stale signal set, purely to populate `_last_veto_decision`. The authoritative `new_state` is still set by `_inference_engine.infer()` at line 2449.

**Target state:** The authoritative path AND the diagnostic path become ONE call. Strategy:

1. Build the full signal set (H1 census + H2 phone trust + H3 tracking active + existing person_tracker_away/home + unidentified) BEFORE `infer()` is called.
2. Call `should_veto_due_to_reliable_signals(scope="house_inference", ...)` once. Result is `house_inference_decision`.
3. Pass `house_inference_decision.fired` *and* the engine's `infer()` result through the same decision branch. Specifically:
   - If `house_inference_decision.fired` is True, the engine's veto branch SHOULD also fire (because `infer()` still has H1's `census_count == 0` predicate locally for backward compat). They should AGREE. **Verify via test** that they agree on the full v4.7.14.1 + v4.7.15 D3 test corpus.
   - Write the helper result to `self._last_veto_decision` unconditionally (so non-firing scope diagnostics are preserved).
4. Delete the parallel invocation at lines 2496-2528 once the consolidated call is in place.

**Critical preservation requirements** (Reviewer B will hammer on these):

- The veto-fired INFO log at `presence.py:2467-2494` must continue to fire on exactly the same condition. The log enriches with `excluded_persons` + `tracked_count` (trusted) + `away_person_ids` — these come from the inline filter block at `presence.py:2318-2350`, which D1 KEEPS but reduces to "build the signal lists and the `_tracked_persons_count_trusted` / `_excluded_persons` diagnostics."
- The dispatcher payload shape (`old_state, new_state, trigger, confidence`) at the `SIGNAL_HOUSE_STATE_CHANGED` dispatch site MUST NOT change. Reviewer B verifies via the existing `test_v4714_dispatcher_payload_shape_unchanged` test at `test_v4715_universalize_veto.py:786-794`.
- `_tracked_persons_count` / `_tracked_persons_count_trusted` / `_excluded_persons` instance fields MUST continue to populate every cycle. The diagnostic sensor reads these.

#### D1.3 — Reduce `_phone_trustworthy` / `_tracking_active` to input builders

**File:** `presence.py`
**Sites:** inline `def`s at lines 2267-2293 (`_phone_trustworthy`) and 2295-2306 (`_tracking_active`).

**Per Reviewer C §C4 item 2:** these become input builders. The PRODUCTION SEMANTICS are unchanged — they continue to do exactly what v4.7.14.1 designed them to do. The change is purely structural:

- Keep both functions in place (do NOT delete from `_run_inference`).
- Their results are now used to build `ReliableSignal("person_phone_trustworthy", value)` and `ReliableSignal("person_tracking_active", value)` entries, in deterministic person-name order, that are passed into the consolidated helper call.
- The per-name filter loop at `presence.py:2327-2342` is preserved: it still populates `excluded_persons` + `trustworthy_persons` for the diagnostic surfaces. The `tracked_count = len(trustworthy_persons)` field becomes `tracked_count` in `state_context` for the helper (which now uses the post-filter count even in fallback mode for safety).

**Why we keep both the inline filter loop AND the helper trusted_count derivation:** The inline loop computes the per-person `excluded_persons` reason map (which the INFO log + diagnostic sensor consume). The helper's trusted_count derivation is the authoritative gate. Both compute over the same data and MUST agree — D1 includes an assertion (DEBUG log + counter) that detects disagreement to catch builder errors. **`[verify in build]`** whether the assertion should be a hard `assert` (test environments) or a soft DEBUG log (production); pick whichever the existing presence.py pattern uses.

#### Acceptance Criteria — D1

- **Verify:** Pattern A in `should_veto_due_to_reliable_signals` accepts `census_count` (transient), `person_phone_trustworthy` (reliable), `person_tracking_active` (reliable) signal kinds.
- **Verify:** Pattern A fires `VetoDecision(True, 0.95, ...)` ONLY when ALL of: `trusted_count > 0`, `all_away`, `not any_home`, `unid == 0`, **`census == 0`**.
- **Verify:** Pattern A's fall-back behavior when `person_phone_trustworthy` / `person_tracking_active` lists are empty is unchanged from the v4.7.15 pre-D1 shape (uses `state_context["tracked_count"]`).
- **Verify:** Pattern A length-mismatch fail-conservative branch returns `fired=False` (cannot accidentally veto on misaligned input).
- **Verify:** The parallel diagnostic invocation at `presence.py:2496-2528` is DELETED; a single helper call now drives both the diagnostic surface and runs in agreement with `_inference_engine.infer()`'s authoritative `new_state`.
- **Verify:** `_phone_trustworthy` / `_tracking_active` inline `def`s remain — they ONLY change role (from filter predicates to input builders).
- **Verify:** `_tracked_persons_count` (raw), `_tracked_persons_count_trusted`, `_excluded_persons` diagnostic fields continue to populate every cycle with v4.7.14.1 semantics.
- **Verify:** The veto-fired INFO log at `presence.py:2467-2494` fires on exactly the v4.7.14.1 condition; log message format unchanged.
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` attribute `tracked_persons_count` = raw count (e.g., 4); `tracked_persons_count_trusted` = filtered count; `last_veto_decision.fired` = True when veto fires; `last_veto_decision.reason` includes `"trusted={n}"`.
- **Test:** `test_pattern_a_fires_when_census_zero_and_unid_zero_and_all_trusted_away` (new) — drives the helper directly with full v4.7.14.1 signal set.
- **Test:** `test_pattern_a_does_not_fire_when_census_positive` (new) — H1 enforcement at the helper layer.
- **Test:** `test_pattern_a_excludes_phone_left_behind_from_trusted` (new) — H2 at the helper layer.
- **Test:** `test_pattern_a_excludes_stale_lost_tracking_from_trusted` (new) — H3 at the helper layer.
- **Test:** `test_pattern_a_falls_back_to_state_context_tracked_count_when_per_person_lists_empty` (new) — backward compat.
- **Test:** `test_pattern_a_length_mismatch_fails_conservative` (new) — H2 and H3 list length mismatch → no veto.
- **Test:** `test_pattern_a_trusted_count_zero_does_not_veto` (new) — all persons excluded → fail-safe.
- **Test:** `test_run_inference_helper_and_engine_agree_on_veto` (new) — assert that for the v4.7.14.1 + v4.7.15 D3 test corpus, helper Pattern A and engine `infer()` veto branch agree on every input.
- **Test:** `test_v4714_1_h1_h2_h3_tests_still_pass` (rerun) — `test_v4714_1_forgotten_phone_hotfix.py` 27/27 pass (after D4 mirror replacement).
- **Test:** `test_v4714_baseline_24_pass` (rerun) — `test_v4714_away_state_person_tracker_trust.py` 24/24 pass.
- **Test:** `test_v472_d5_b1_17_pass` (rerun) — `test_v472_feature_b_guest_signal.py` 17/17 pass.
- **Test:** `test_dispatcher_payload_shape_unchanged` (existing) — Reviewer B's primary signal-chain check.
- **Live:** After restart, `sensor.ura_presence_coordinator_presence_house_state` attribute `last_veto_decision` populated within 1 inference cycle; in calm AWAY state shows `{fired: false, scope: house_inference, confidence: 0.0}` OR `{fired: true, scope: house_inference, confidence: 0.95, reason: "all_tracked_persons_away (no guests, no census, trusted=4)"}` depending on actual state. **Negative live test:** when operator's phone is at home but person is at work (Gap B), `last_veto_decision.reason` shows `trusted=3` (not 4); `excluded_persons` attribute lists the forgotten-phone person with reason `phone_left_behind=on`.

---

### D2 — Update v4.7.15 source-invariant tests for post-merge canonical truth

**File:** `quality/tests/test_v4715_universalize_veto.py`
**Site:** `TestSiblingCyclePreservation::test_v4714_inference_engine_veto_branch_intact` (lines 777-780).

**Change:** The OLD assertion text `"all_tracked_persons_away and unidentified_count == 0"` is technically a substring of the NEW production line `"all_tracked_persons_away and unidentified_count == 0 and census_count == 0"`, so Python's `in` operator should still find it. **`[verify in build]`** by running the test in `/tmp/ura-v4715-1-integration`. Two outcomes:

- **Outcome A (test PASSES):** the substring is still found. Leave the assertion in place but ADD a second assertion targeting the v4.7.14.1 H1 string: `assert "and census_count == 0" in PRESENCE_SRC, "v4.7.14.1 H1 census predicate must remain"`. This way the test enforces both the v4.7.14 backbone AND the v4.7.14.1 tightening.
- **Outcome B (test FAILS):** something about formatting / line wrap breaks the substring. Replace the assertion with the post-v4.7.14.1 canonical string `"all_tracked_persons_away and unidentified_count == 0 and census_count == 0"`.

Per the operator brief, this is "NOT papering over a bug — the v4.7.14.1 H1 fix is the canonical truth now." The test docstring MUST capture this rationale to prevent a future reviewer from re-narrowing the assertion.

#### Acceptance Criteria — D2

- **Verify:** `TestSiblingCyclePreservation::test_v4714_inference_engine_veto_branch_intact` PASSES on the integration base post-D1+D2.
- **Verify:** Test docstring explicitly cites v4.7.14.1 H1 as the reason for the predicate's current shape.
- **Verify:** No other `TestSiblingCyclePreservation` test fails post-D2.
- **Test:** Direct re-run: `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4715_universalize_veto.py::TestSiblingCyclePreservation -q` → 5/5 pass (or current class size — `[verify in build]`).

---

### D3 — Widen `_run_inference` source-window for D3 helper tests

**File:** `quality/tests/test_v4715_universalize_veto.py`
**Sites:** `TestD3WakingSustainedSignal::test_waking_transition_uses_helper` (line 573-578), `TestD3GuestExitPersistence::test_guest_exit_uses_helper` (line 585-590), `TestD3GuestExitPersistence::test_guest_exit_reuses_guest_persistence_seconds` (line 592-595), `TestD3WakingSustainedSignal::test_run_inference_tracks_sustained_occupancy` (line 565-571, defensive).

**Change:** widen `body = PRESENCE_SRC[idx: idx + 12000]` to `body = PRESENCE_SRC[idx: idx + 30000]` in all four tests. **`[verify in build]`** the exact required size by reading `len(PRESENCE_SRC[idx: idx + N])` until the assertion target is found; 30000 is a safe upper bound based on the integration-base function body (`_run_inference` runs from line 2212 to past line 2650, ~440 source lines × ~60 chars/line avg = ~26-28 KB).

**Rationale to bake into docstrings:** Per Reviewer C C3 of v4.7.14.1, source-string window widening is the established pattern when feature inserts push assertion targets downstream. v4.7.14.1 already widened the v4.7.2 D5 / B1 tests' windows from 6000→9000 / 7000→9000 for the same reason. v4.7.15 D3's 12000 window was sized against a `_run_inference` that did NOT contain v4.7.14.1's H2/H3 helpers. The widening here is honest re-baselining against post-merge reality, not a relaxation of the semantic claim.

**Hard upper bound:** ensure `body` slice doesn't accidentally include `async def _run_inference` of a SECOND occurrence (would only matter if presence.py contains two functions with that prefix — `[verify in build]` via grep; almost certainly only one).

#### Acceptance Criteria — D3

- **Verify:** All four widened tests PASS on the integration base post-fix.
- **Verify:** Each widened test has an updated docstring citing the post-v4.7.14.1 merge as the reason for the window growth.
- **Verify:** AST regression test (NEW) — `test_run_inference_only_defined_once` — asserts `PRESENCE_SRC.count("async def _run_inference")` == 1, so the widened window cannot accidentally span two function bodies.
- **Test:** Direct re-run: `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4715_universalize_veto.py::TestD3WakingSustainedSignal quality/tests/test_v4715_universalize_veto.py::TestD3GuestExitPersistence -q` → all pass.

---

### D4 — Delete now-redundant v4.7.14.1 local mirror tests

**File:** `quality/tests/test_v4714_1_forgotten_phone_hotfix.py`
**Sites:**
- Mirror function `_phone_trustworthy` at `test_v4714_1_forgotten_phone_hotfix.py:298-305` (per Reviewer C §C1 table).
- Mirror function `_tracking_active` at `test_v4714_1_forgotten_phone_hotfix.py:514-516`.
- Source-string invariants at lines 485-506 (`test_h2_filter_present_in_source`, `test_h2_filter_references_phone_left_behind_entity`, `test_h2_filter_uses_hass_states_get`) and 666-676 (`test_h3_filter_references_tracking_status`, `test_h3_imports_tracking_status_active`).

**Per Reviewer C §C4 item 3 + §C1 explicit guidance:**

1. The mirror function `_phone_trustworthy` in the test file: REPLACE with direct calls to production. Since `_phone_trustworthy` is still defined inline in `_run_inference` (D1.3 keeps it as input builder), the simplest replacement is to either:
   - (a) extract the production `_phone_trustworthy` into a module-level helper on `PresenceCoordinator` so tests can import + call it (Reviewer C C1's preferred long-term form), OR
   - (b) keep it inline in `_run_inference` but write behavioral tests against the AUTHORITATIVE PATH (D1 consolidated helper call) — assertion: when `binary_sensor.<person>_phone_left_behind` is `on` for one tracked person, the helper Pattern A's `trusted_count` is 1 less than `tracked_count`, and `excluded_persons` lists the person.
   - **Pick (b)** — it's cheaper, aligns with Bug Class #44 (test drives production code), and avoids exposing a new public API. `[verify in build]` if the existing test fixture supports easy invocation of the production helper; if not, fall to (a).

2. Source-string invariants at lines 485-506 and 666-676: per Reviewer C §C1, these are **deliberate trip-wires** designed to fail when v4.7.15 D1 extracts the shared helper. Update them to point at the new home of the logic:
   - `test_h2_filter_present_in_source` — replace literal `"_phone_trustworthy"` search with `"person_phone_trustworthy"` (the helper's new signal kind) AND keep a presence-check for `_phone_trustworthy` (still defined as input builder).
   - `test_h2_filter_references_phone_left_behind_entity` — unchanged (production code still resolves the entity_id).
   - `test_h2_filter_uses_hass_states_get` — unchanged (the input builder still reads `hass.states.get(...)`).
   - `test_h3_filter_references_tracking_status` — unchanged.
   - `test_h3_imports_tracking_status_active` — unchanged.

3. The H1 tests in `test_v4714_1_forgotten_phone_hotfix.py` (the production-direct `engine.infer()` calls) are UNTOUCHED — they're Bug Class #44 compliant already (Reviewer C §C1 "Why H1 is clean").

**Reviewer C explicit quote:** *"the source-level invariants will deliberately trip when v4.7.15 D1 extracts the shared helper, forcing the v4.7.15 builder to update them."* — `v4.7.14.1_review_C_test_authority_merge_risk.md:118`. D4 is the execution of this instruction.

#### Acceptance Criteria — D4

- **Verify:** `_phone_trustworthy` and `_tracking_active` mirror function `def`s removed from `test_v4714_1_forgotten_phone_hotfix.py`.
- **Verify:** Behavioral assertions replacing them drive the production code path (either the helper directly or the consolidated `_run_inference` invocation in a fixture).
- **Verify:** Source-string invariants updated to point at the post-D1 production structure (helper signal kind `person_phone_trustworthy` / `person_tracking_active`) AND the still-extant input-builder `_phone_trustworthy` / `_tracking_active` `def`s.
- **Verify:** All 27/27 v4.7.14.1 cycle tests pass after D4 update. Specifically the H2/H3 behavioural tests now assert against the production helper's `trusted_count` / `excluded_persons` output instead of mirror return values.
- **Test:** `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4714_1_forgotten_phone_hotfix.py -q` → 27/27 pass.
- **Test:** AST regression — search for `def _phone_trustworthy(` and `def _tracking_active(` in `test_v4714_1_forgotten_phone_hotfix.py` should return ZERO matches (mirrors deleted).

---

## 4. Out of scope (explicit)

- **DO NOT change** v4.7.14.1 H1/H2/H3 semantics. The production logic at `presence.py:2256-2369` and the `census_count == 0` predicate in `infer()` remain canonical.
- **DO NOT touch** v4.7.15 D2 (zone aggregator Layer 3 non-sleep), D4 (`check_zone_occupancy_confidence` relocation), D5 (`signal_consensus` sensor + mirror), D6 (HVAC + compliance defer gates).
- **DO NOT add Pattern F** (room-level weighted veto). The unknown-scope fall-through at `presence.py:844-857` deliberately returns `fired=False` for `scope="room_level_weighted"`. v4.7.16 owns Pattern F; the comment block at 844-856 is load-bearing — do not delete or amend.
- **DO NOT touch** `aggregation.py` D2 Pattern C path. Zone-aggregator does not (yet) consume H2/H3 — phone-trust / tracking-active are house-inference scope only. v4.7.15.1 does not extend the zone scope.
- **DO NOT** propose new CONF_* — none verified, none needed. All four new signal kinds are internal helper-protocol strings, not operator-facing.
- **DO NOT** add new sensors or switches. All diagnostic surfaces v4.7.15.1 needs already exist (`last_veto_decision`, `tracked_persons_count`, `tracked_persons_count_trusted`, `excluded_persons`).
- **DO NOT touch** `config_flow.py`.

---

## 5. Bug-class watchlist

| Class | Risk in this cycle | Mitigation |
|---|---|---|
| #22 (enum mismatch) | New signal `person_phone_trustworthy` value type — must be strictly boolean, never `None`/`"on"`/`"off"` string. | Input builder converts `_phone_trustworthy(name)` (bool) directly; type-asserted in helper. Test for non-boolean inputs → fail-conservative. |
| #33 (sibling helpers skipped) | We're consolidating two paths into one. Reviewer A explicitly tasked with sibling-helper sweep — confirm no THIRD caller of v4.7.14.1's filter logic exists. | Grep `phone_left_behind` and `tracking_status` across all `domain_coordinators/*.py`. Document hits. |
| #38 (untracked unsub) | None — no new listeners. | N/A |
| #42 (lambda + async_create_task) | None — no new scheduling. | N/A |
| #44 (test fixture authority / sys.modules pollution) | **PRIMARY**. D4 removes hybrid mirrors. Replacement tests must drive PRODUCTION code, not new shadow re-implementations. | Reviewer C tasked specifically with verifying behavioral assertions drive the consolidated helper call, not a new mirror. |
| #46 (lazy derivation / canonical UI surface) | D1 consolidation must not silently change the value of any persisted diagnostic field. | Existing `_tracked_persons_count` (raw) preserved verbatim per `presence.py:2364`. |
| #47 (lazy canonical UI surface violation) | None — no new entity persistence. | N/A |
| **#48 (transient-vs-reliable)** | THIS IS THE CYCLE'S CONTINUATION. Pattern A becomes the authoritative locus of the trust hierarchy. | All four deliverables build the canonical Bug Class #48 helper. v4.7.16 will plug in Pattern F against this; v4.8.x BLE will plug a Pattern G; none should need to re-derive H1/H2/H3. |

---

## 6. Tier 2-DB review framing

Per CLAUDE.md Tier 2-DB protocol and `feedback_db_sensitive_3x_targeted_reviews.md`. Three parallel reviewers, three explicit disjoint framings. Run them in parallel after build; framings cannot share blind spots.

### Reviewer A — Correctness of refactored Pattern A + filtered tracked_count flow + source-invariant honesty

- D1's per-person zip contract for `person_phone_trustworthy` + `person_tracking_active` is correct for ALL caller scenarios (4 tracked persons, 0 tracked persons, 1 with mismatch length).
- The fall-back to `state_context["tracked_count"]` when both per-person lists are empty preserves v4.7.15 baseline behavior (zone aggregator Patterns B/C still pass).
- `trusted_count` derivation in the helper agrees with the inline `len(trustworthy_persons)` in `_run_inference` for every input in the v4.7.14.1 test corpus.
- The H1 `census_count == 0` predicate in Pattern A is byte-equivalent to v4.7.14.1's inline H1 predicate.
- D2 source-invariant update is honest — the new assertion captures the v4.7.14.1 H1 truth, not weasel-words around a regression. Reviewer A independently re-derives the post-merge canonical predicate string and compares against the test text.
- **Sibling-helper sweep:** grep `phone_left_behind` and `tracking_status` across `custom_components/universal_room_automation/domain_coordinators/`. Any third caller of the filter logic that should also consume the helper? File as MEDIUM if found (NOT scope creep into v4.7.15.1).

### Reviewer B — Signal-chain integrity + diagnostic surface preservation + D3 helper-test fixes

- The deleted parallel diagnostic invocation at `presence.py:2496-2528` and the new consolidated call together preserve `_last_veto_decision` updates on every cycle. Specifically: `_last_veto_decision` must still update when the helper does NOT fire (so the diagnostic surface shows `fired: false` recently, not a stale fired-true from minutes ago).
- The veto-fired INFO log at `presence.py:2467-2494` still fires on exactly the v4.7.14.1 condition; the enriched payload (`excluded_persons`, `tracked_count` trusted, `away_person_ids`) is preserved byte-for-byte.
- `SIGNAL_HOUSE_STATE_CHANGED` dispatcher payload shape unchanged. `test_v4714_dispatcher_payload_shape_unchanged` still PASSES.
- Re-test: WAKING gate (`presence.py:2540-2566`) and GUEST exit gate (`presence.py:2574-2615`) write `_last_veto_decision` correctly even after the consolidated house-inference call — i.e., the order of helper calls per cycle matches (house-inference first, then WAKING if applicable, then GUEST exit if applicable). The LAST write wins per cycle; this preserves v4.7.15's design.
- D3 window-widen choice (12000 → 30000) is justified — Reviewer B independently computes `len(PRESENCE_SRC[_run_inference_idx:])` and confirms 30000 covers but does not over-cover.
- D3 AST regression test (`test_run_inference_only_defined_once`) is sound.
- Cross-coordinator: nothing in `coordinator_diagnostics.py`, `hvac.py`, or `aggregation.py` reads `_last_veto_decision` directly. **`[verify in build]`** by grep; if anything does, ensure that consumer still receives a consistent post-D1 value.

### Reviewer C — Test fixture authority (Bug Class #44) + integration-branch merge fidelity

- D4 mirror deletions: the replacement behavioral assertions in `test_v4714_1_forgotten_phone_hotfix.py` drive production code, not a new shadow re-implementation. Reviewer C reads every replaced test line-by-line and confirms the assertion target is a production attribute / sensor / helper return value — NEVER a test-file `def`.
- D4 source-invariant updates: the new assertion strings (`person_phone_trustworthy`, `person_tracking_active`) actually appear in production source — verified by Reviewer C grepping the integration base.
- Integration-branch merge fidelity: D1's consolidation introduces NO new semantic drift from v4.7.14.1. Reviewer C re-runs the full v4.7.14.1 test suite (27 tests) AND the v4.7.14 baseline (24 tests) AND the v4.7.2 D5/B1 suite (17 tests) AND the v4.7.15 suite (per its size) on the post-D1+D2+D3+D4 branch. Total green count documented in the review.
- Pre/post `presence.py` line counts captured — D1 is "mostly deletion + consolidation"; if the net delta is +50+ LoC, Reviewer C raises a question about whether D1.2's consolidation actually consolidated.
- Fixture authority: D1's helper Pattern A test fixtures construct `ReliableSignal` and `TransientSignal` from production imports (not test-file shadow dataclasses). `[verify in build]` whether the test file already imports these — if not, the import path must be added per Reviewer C's standing rule.

**Run the three reviews in PARALLEL.** Different framings cannot share blind spots.

**Fix CRITICAL/HIGH from any review before deploy.** Re-verify after fix-up. Re-run all the test suites listed above + the pre-deploy zero-bugs gate.

---

## 7. Pre-deploy zero-bugs gate (MANDATORY)

Per `feedback_pre_deploy_zero_bugs_gate.md` — user-coined after v4.7.4.3 shipped with merge-conflict markers. Run BEFORE every `./scripts/deploy.sh`:

1. **Grep conflict markers** across the whole repo:
   ```bash
   grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/ quality/ docs/planning/PLANNING_v4.7.15.1*.md docs/readmes/README_v4.7.15.1.md
   ```
   Zero matches required (excluding `quality/` tests that legitimately reference the markers as strings — verify by `[verify in build]`).

2. **`py_compile` every changed file:**
   ```bash
   python3 -m py_compile custom_components/universal_room_automation/domain_coordinators/presence.py
   python3 -m py_compile $(git diff --name-only develop..HEAD -- '*.py')
   ```
   All exit 0.

3. **Cycle tests + sibling suites:**
   ```bash
   PYTHONPATH=quality python3 -m pytest \
     quality/tests/test_v4715_universalize_veto.py \
     quality/tests/test_v4714_1_forgotten_phone_hotfix.py \
     quality/tests/test_v4714_away_state_person_tracker_trust.py \
     quality/tests/test_v472_feature_b_guest_signal.py \
     -q
   ```
   All green.

4. **Suite-baseline-diff:** `git diff pre-review-v4.7.15.1..HEAD -- quality/tests/` — the diff should ONLY show v4.7.15.1's planned test changes (D2 + D3 widens + D4 mirror deletions + D1 new helper tests). Anything else surfaces as a separate review item.

5. **Full pytest suite baseline:** if size permits, run the full `quality/tests/` suite and confirm net new failures = 0 (greens may increase from D1's added tests; reds must NOT increase).

If any gate fails, STOP, investigate, do not deploy.

---

## 8. README requirements (v4.7.15.1 — small cycle, operator-runbook still required)

Create `docs/readmes/README_v4.7.15.1.md` before deploy. Per memory `feedback_verify_hacs_install.md` + Tier 2-DB extra-robust requirements, the README must include:

| Section | Required content |
|---|---|
| One-paragraph summary | "v4.7.15.1 consolidates v4.7.14.1's H1/H2/H3 trust filters into v4.7.15's shared Pattern A helper. No new operator-facing behavior; runtime semantics are unchanged. Diagnostic surface gains consistency: `last_veto_decision` is now populated by the same code path that drives the authoritative house-state transition." |
| Operator runbook | 1. Confirm HACS shows `update.universal_room_automation_update.installed_version = "v4.7.15.1"` after install. 2. Confirm `update.universal_room_automation_update.installed_version` matches `latest_version`. 3. Verify `sensor.ura_presence_coordinator_presence_house_state` attributes `tracked_persons_count`, `tracked_persons_count_trusted`, `excluded_persons`, `last_veto_decision` all present and updating each inference tick. 4. Confirm `sensor.ura_presence_coordinator_house_state_confidence = 0.95` during a confirmed-AWAY window. |
| Pre-deploy snapshot procedure | Snapshot the count of `last_veto_decision.fired = true` events over a 1h window from `sensor.ura_presence_coordinator_presence_house_state` attribute history. Post-deploy diff must be ±25% (because the cycle does not change firing semantics; it consolidates HOW they're computed). |
| Post-deploy validation procedure (specific entity IDs + expected values) | 1. Within 10 min of restart: `sensor.ura_presence_coordinator_presence_house_state.attributes.last_veto_decision` is a dict with keys `fired, confidence, reason, scope`. 2. `last_veto_decision.scope` is one of `"house_inference"`, `"waking_transition"`, `"guest_exit"`, or `""`. 3. `tracked_persons_count_trusted <= tracked_persons_count` always (Reviewer A invariant). 4. If `excluded_persons` is non-empty, every reason value is one of `"phone_left_behind=on"` or starts with `"tracking_status="`. |
| Rollback procedure | 1. HACS download v4.7.15 (the immediate predecessor). 2. Restart HA. 3. Verify `update.universal_room_automation_update.installed_version = "v4.7.15"`. 4. Confirm `sensor.ura_presence_coordinator_presence_house_state` still publishes `last_veto_decision` (v4.7.15 also writes this — the surface predates v4.7.15.1). 5. v4.7.15's parallel-path behavior re-emerges; not a regression, just less consolidated. |
| Live validation checklist | Pass criteria: (a) zero new ERROR log entries in `journald`/`ha_get_logs(source="system_service", slug="core")` after restart referencing `presence.py` or `should_veto_due_to_reliable_signals`; (b) all four `TestSiblingCyclePreservation` tests pass against the deployed binary if the operator runs the test suite locally; (c) operator's known forgotten-phone scenario (Gap B from v4.7.14.1) still produces a correctly-attributed `excluded_persons` entry. |
| Known limitations | (a) The v4.7.14.1 in-test mirror functions are removed; tests now drive production code via behavioral assertions. Any reviewer expecting to find `_phone_trustworthy` in `test_v4714_1_forgotten_phone_hotfix.py` should be aware the function moved to a production-direct assertion. (b) v4.7.16's Pattern F is unchanged — it still falls through to `fired=False` for `scope="room_level_weighted"`. |
| Cross-cycle reference | Predecessor: v4.7.15 (D1-D6 shipped). Sibling: v4.7.16 (room-level Pattern F, separate cycle). Bug Class #48. Reviewer C of v4.7.14.1 §C4 (load-bearing instruction). |

---

## 9. Plan completion tracking

Per CLAUDE.md "Plan Completion Tracking — MANDATORY": after build, document explicitly what from D1-D4 was completed vs deferred. Specifically:

- If D1.1 list-mismatch fail-conservative branch was simplified or omitted → state why + where tracked.
- If D4's preferred "(b)" behavioral assertion approach was downgraded to "(a)" public-helper extraction → state why + impact.
- If any v4.7.14.1 source-string invariant could not be updated cleanly and was deleted instead → state why + impact.
- If Reviewer A's sibling-helper sweep found a third caller → state where filed for v4.7.16 / future cycle.

---

## 10. Verification checklist (one-page summary for the validator)

Pre-deploy:
- [ ] `presence.py` has the consolidated D1 Pattern A signal taxonomy (census_count, person_phone_trustworthy, person_tracking_active).
- [ ] Parallel diagnostic invocation at `presence.py:2496-2528` (pre-D1) is DELETED.
- [ ] Inline `_phone_trustworthy` / `_tracking_active` `def`s are PRESERVED as input builders.
- [ ] `_tracked_persons_count` / `_tracked_persons_count_trusted` / `_excluded_persons` populate every cycle.
- [ ] `test_v4715_universalize_veto.py::TestSiblingCyclePreservation` passes (D2).
- [ ] `test_v4715_universalize_veto.py::TestD3WakingSustainedSignal` + `TestD3GuestExitPersistence` pass (D3).
- [ ] `test_v4714_1_forgotten_phone_hotfix.py` mirrors removed; 27/27 still pass (D4).
- [ ] `test_v4714_away_state_person_tracker_trust.py` 24/24 still pass.
- [ ] `test_v472_feature_b_guest_signal.py` 17/17 still pass.
- [ ] Pre-deploy zero-bugs gate items 1-5 (Section 7) all clean.
- [ ] Three Tier 2-DB reviews complete with framings A/B/C, CRITICAL/HIGH all fixed.
- [ ] `docs/readmes/README_v4.7.15.1.md` exists and meets Section 8 requirements.
- [ ] `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` updated to include v4.7.15.1.

Live (Review D, post-restart):
- [ ] HACS `installed_version = "v4.7.15.1"` matches `latest_version`.
- [ ] `sensor.ura_presence_coordinator_presence_house_state` publishes `last_veto_decision` with the four expected keys within 1 inference cycle.
- [ ] No new `ERROR` log entries referencing `presence.py` or `should_veto_due_to_reliable_signals`.
- [ ] Forgotten-phone scenario (Gap B): `excluded_persons` contains the forgotten-phone person with reason `"phone_left_behind=on"`.
- [ ] `tracked_persons_count_trusted <= tracked_persons_count` always.
- [ ] No new `compliance_log` violations attributable to D1's signal-chain change (Reviewer B's post-deploy negative check).

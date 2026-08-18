# GUEST-CENSUS — Review C (Tier 2-DB, framing: test fixture authority + hollow-anchor hunting)

- Branch: `feature/guest-census` (worktree `.claude/worktrees/guest-census-build`)
- Commits reviewed: `eae92423c..c7c308a53` (D1, D2, D3, D2b + collateral)
- Reviewer framing: test fixture authority. Does every load-bearing behavioural change have a test that DRIVES production code (not echoes it), and does every source-shape anchor survive drill variants 1 (comment-out) AND 7 (delete)?
- Date: 2026-08-16

---

## Verdict: **SHIP WITH FIX-UP** (2 MEDIUMs, 1 LOW; no CRITICAL/HIGH)

The clamp arithmetic (the rev-1 → rev-2 discriminator) is correctly guarded by real behavioural tests and survives per-site mutation. The D2b exit-predicate change is guarded by three behavioural tests plus explicit-negative source shape. The collateral test rewrites are, on inspection, protective — they include explicit negative assertions against the pre-D2b shape resurfacing. However, D3 (registry-based guest-room resolution) is guarded ENTIRELY by source-grep tests, one of which (`test_unresolvable_room_warns`) is a confirmed hollow anchor (passes under a delete-the-call mutation), and one D2 assertion (`test_confidence_bump_when_both_gates_fire`) is exposed to the same class. Fix these two and re-run.

---

## Per-test collateral-rewrite assessment

For each rewrite: (a) what the ORIGINAL asserted at `develop`; (b) what the REWRITE asserts on the cycle tip; (c) whether the original's protective intent is preserved or a negative-against-resurfacing has been added.

### 1. `quality/tests/test_v472_feature_b_guest_signal.py::TestD5RunInferenceOr::test_additive_or_present`

- **Original (develop)**: asserted `"or guest_room_gate_armed" in body OR "guest_room_gate_armed or" in body` — protective intent: the composition of `guest_armed` factors in the Path B (sustained-room) gate.
- **Rewrite (tip)**: asserts `"guest_armed = guest_room_gate_armed" in body`.
- **Assessment — ACCEPTABLE (with a nit)**: the exact-substring assertion is stronger than a `contains("guest_room_gate_armed")` — it forbids the LHS from being preceded by `unid_gate_armed or `, i.e. any dual-source composition returns to the old shape and this substring is no longer present. So the assertion IS effectively a negative against the pre-D2 shape resurfacing. The rename ("test_additive_or_present" → still asserts the D2 shape) is misleading; docstring update covers it.
- **Nit (LOW-1)**: for symmetry with the sibling `TestD5ExitConditionGuard` rewrite, add an explicit `assert "unid_gate_armed or" not in body[:same_slice]` — belt-and-braces and unambiguous to future readers.

### 2. `quality/tests/test_v472_feature_b_guest_signal.py::TestD5ExitConditionGuard::test_exit_predicate_is_room_only`

- **Original (develop)**: asserted `"unidentified_count == 0 and not guest_gate_armed" in body` — protective intent: v4.7.2 D5 combined-condition exit predicate is present.
- **Rewrite (tip)**: asserts the new predicate present AND adds explicit `assert "unidentified_count == 0 and not guest_gate_armed" not in body`.
- **Assessment — EXEMPLARY**: intent is intentionally inverted (D2b decouples), and the rewrite includes an explicit negative against the old shape resurfacing. Drill D2b-M1 (restoring the old conjunct) flips this test.

### 3. `quality/tests/test_v4622_guest_mode_hardening.py::test_guest_gate_exit_is_immediate`

- **Original (develop)**: asserted BOTH `"current_state == HouseState.GUEST and unidentified_count == 0"` present AND `"unidentified_count == 0 and not guest_gate_armed"` present (v4.7.2 D5 combined exit).
- **Rewrite (tip)**: asserts `"current_state == HouseState.GUEST and not guest_gate_armed"` present AND explicit negative that the old census conjunct is absent.
- **Assessment — EXEMPLARY**: same protective pattern as (2). Docstring records the historical intent and the mechanism of the D1-residual-latches-GUEST bug. Drill D2b-M1 flips this test too.

**Summary of the collateral rewrites**: no coverage silently dropped. (2) and (3) are correctly-shaped inversions with explicit negatives. (1) has an implicit negative via strict exact-substring; a paired explicit `not in` would match the sibling pattern.

---

## New-test authority assessment (`test_guest_census_correctness.py`, 19 tests)

Split by whether the test DRIVES production code or inspects source:

### Behavioural (drive production code) — GOOD

- `test_clamp_tonight_live_shape`, `test_clamp_repaired_defenses_preserves_guest`, `test_clamp_partial_cancel_preserves_guest`, `test_clamp_no_op_when_within_ceiling`, `test_clamp_zero_held_no_unidentified` — all construct `PersonCensus`, stub `_get_unrecognized_camera_count` + `_apply_hold_decay`, and drive `_apply_enhanced_house_census`. Assertions are on returned `CensusZoneResult`.
- `test_pre_cancel_scalar_published_at_step2` — constructs `PersonCensus`, stubs `hass.states.get` to produce a real per-area max, invokes `_get_unrecognized_camera_count()`, and asserts the four G2 attributes were populated. Behavioural.
- `test_d2b_guest_exits_when_room_clears_even_if_unidentified_stuck`, `test_d2b_real_guest_holds_when_room_still_occupied`, `test_d2b_guest_non_terminal_from_room_clear` — instantiate `StateInferenceEngine` and drive `infer(...)`. Assertions on returned `HouseState`. Behavioural.

**Load-bearing rev-1 vs rev-2 discriminator (`test_clamp_repaired_defenses_preserves_guest`)** — verified independently by re-deriving the arithmetic under the rev-1 bug (ceiling = `camera_unrecognized` = 1 → clamp min(5, max(1,4)) = 4, guest suppressed) vs the rev-2 fix (ceiling = pre_cancel = 5 → clamp min(5, max(5,4)) = 5, guest preserved). Drill D1-M1 flips exactly this test.

### Source-shape (grep-based) — MIXED

- D2 shape tests (`test_home_like_guest_armed_is_room_only`, `test_inside_guest_branch_unchanged`): exact-substring on unique LHS patterns. Both include an explicit negative for the pre-D2 substring. Acceptable — behavioural D2b tests further exercise the composed predicate through `infer()`.
- D2 confidence test (`test_confidence_bump_when_both_gates_fire`): asserts `"0.95" in <400-char block>` starting from a unique surrounding pattern. **See MED-2 below.**
- D3 tests (`test_discover_uses_registry_lookup`, `test_unresolvable_room_warns`, `test_entity_to_name_reverse_map_populated`, `test_handler_uses_reverse_map_not_slug_loop`, `test_reconfigure_clears_entity_map`, `test_entity_to_name_init_in_ctor`, `test_d2b_exit_predicate_source_shape`): ENTIRELY source-shape. **See MED-1 and observation below.**

---

## Mutation drill results (7 drills, all restore-verified)

Environment: `PYTHONDONTWRITEBYTECODE=1`, cwd = worktree, `git checkout --` after each drill, final `git status --porcelain custom_components/` is empty.

| # | Drill | Target file | Expected fail | Actual |
|---|---|---|---|---|
| 1 | D1-M1: ceiling → `camera_unrecognized` (POST-cancel) | camera_census.py | `test_clamp_repaired_defenses_preserves_guest` | FAIL — `guest suppressed: total=4 (POST-cancel ceiling bug — plan-review P1)` |
| 2 | D1-M2: `total = additive_total` (delete clamp) | camera_census.py | `test_clamp_tonight_live_shape` | FAIL — `expected clamp to 6, got 10` |
| 3 | D1-M3: delete `_last_camera_total_pre_cancel = ...` publication | camera_census.py | `test_pre_cancel_scalar_published_at_step2` | FAIL — `assert 0 == 2` |
| 4 | D2-M1: `guest_armed = unid_gate_armed or guest_room_gate_armed` (revert) | presence.py | `test_home_like_guest_armed_is_room_only` | FAIL — negative assertion fires |
| 5 | D2b-M1: restore `... and unidentified_count == 0 and not guest_gate_armed` | presence.py | `test_d2b_guest_exits_when_room_clears_even_if_unidentified_stuck` | 3 FAIL — behavioural (2) + source-shape (1) |
| 6 | D3-M1: restore `f"binary_sensor.{room_slug}_occupied"` | presence.py | `test_discover_uses_registry_lookup` | FAIL — `async_get_entity_id` positive assertion fires (negative would also fire) |
| 7 | D3-M2: delete WARNING block | presence.py | `test_unresolvable_room_warns` | FAIL — both substrings absent |

All 7 canonical drills flip only the expected tests. Restoration clean.

### Adversarial variant-7 drill (grep-anchor hollow-out) — CONFIRMS MED-1

Additional drill on `test_unresolvable_room_warns`: replaced the WARNING block with `pass  # _LOGGER.warning "skipping registration" HOLLOW-DRILL` (deletes the CALL but leaves the two grepped substrings in a comment). Result: **test PASSED** (1 passed in 0.16s). The anchor is hollow — a code-change that removes the observable behaviour (the warning) while incidentally leaving the substrings in a comment is not caught. Restored, `git status` clean.

---

## Findings

### MED-1 — Hollow anchor: `test_unresolvable_room_warns` (Bug Class: hollow test anchor, variant 7)

**File**: `quality/tests/test_guest_census_correctness.py:399-404`
**Evidence**: variant-7 drill above.
**Why it matters**: D3 is a fragility-fix that also introduced a NEW LOUD failure mode (WARNING on registry miss). The test that guards the LOUD-ness passes when the warning is silently removed. A future refactor that swaps `_LOGGER.warning` for a bare `continue` (recovering the pre-D3 silent behaviour that the plan explicitly rejected) would not be caught.
**Recommended fix**: replace with behavioural test — construct a `PresenceCoordinator` with a room whose unique_id is not in the registry, call `_discover_guest_rooms()` inside a `caplog.at_level("WARNING")` block, assert a log record was emitted with the room name in the message and that the room was NOT registered in `_guest_room_state`. This gets both the WARNING and the `continue` in one behavioural check.

### MED-2 — Same class: `test_confidence_bump_when_both_gates_fire` (Bug Class: hollow test anchor, variant 7)

**File**: `quality/tests/test_guest_census_correctness.py:354-360`
**Evidence**: assertion is `"0.95" in <400-char slice>`. The literal `0.95` is trivially satisfied by any comment containing `0.95` (e.g. `# NOTE: 0.95 removed`) even if the actual assignment is neutered to `_d5_guest_confidence = 0.9`.
**Why it matters**: D2's confidence-layering change is the observable that downstream sensors expose. A silent regression to `0.9` under both gates is exactly the kind of numeric drift a source-shape test should catch but doesn't.
**Recommended fix**: behavioural — invoke the coordinator branch (or extract the confidence-selection helper) and assert `_d5_guest_confidence == 0.95` when both gate booleans are True. If extracting the helper is too invasive for this cycle, upgrade the source test to a regex: `re.search(r"guest_room_gate_armed and unid_gate_armed:\s*\n\s*_d5_guest_confidence:?\s*(?:float)?\s*=\s*0\.95", ...)` — matches the assignment shape, not any `0.95` in-scope.

### LOW-1 — Symmetry nit on the rewritten `test_additive_or_present`

See collateral assessment (1) above. Add `assert "unid_gate_armed or" not in body[:1500]` for parity with the sibling `TestD5ExitConditionGuard` rewrite. Not blocking.

### Observation (non-blocking) — D3 has zero behavioural coverage

Every D3 test is source-shape. There is no test that constructs a `PresenceCoordinator`, seeds an entity registry with a `f"{entry_id}_occupied"` unique_id, calls `_discover_guest_rooms`, fires a state-change on the resolved entity_id, and asserts the reverse-map handler routes correctly. This is beyond the review-C fix-up scope and D3 is not the load-bearing arithmetic of the cycle, but it is a coverage gap worth logging for the next cycle. Symptom risk: a reconfigure-without-restart that leaves a stale entity_id in `_guest_room_entity_to_name` would misroute an occupancy signal to a renamed room — no test would catch it today.

---

## Suite integrity

- Cycle-scoped tests (3 files, 101 tests) — PASS (`101 passed, 1 warning in 0.27s`), independently re-run.
- **Full-suite baseline claim NOT INDEPENDENTLY VERIFIED.** Builder reported `develop 9160/26 → tip 9179/26` with an empty name-diff. I launched a full-suite run on the worktree tip during this review; at 25 minutes elapsed it had not completed (output pipe buffered behind `tail -15` — normal for the full URA suite on this host). Per operator standing guidance ("this host deadlocks under concurrent pytest"), I did NOT launch the develop-baseline run concurrently, and I chose not to serialize a second ~30-min run to finish this review. The +19 test delta matches the 19 new tests in `test_guest_census_correctness.py` (arithmetically consistent with the builder's claim), but this is inference from cardinality, not name-diff verification. Recommend an explicit `ura-validator` full-suite pair (develop then tip, sequential) as the deploy gate.
- Environment hygiene: no stale pytest processes pre-drill (`pgrep -fl pytest` empty). `PYTHONDONTWRITEBYTECODE=1` used for all drills (per repo hygiene rule "Mutation-verify .pyc staleness"). All 7 drills restored; final `git status --porcelain custom_components/` empty.

---

## Bug-class rollup

| Class | Count |
|---|---|
| Hollow test anchor (variant 7 — grep substrings survive comment/no-op) | 2 (MED-1, MED-2) |
| Test-shape parity nit | 1 (LOW-1) |

Recommend flagging bug-class "hollow anchor via grep substring in comment" as a durable review-C target for future cycles — the D3 group in this cycle used the same grep-substring pattern six times; two were unlucky enough that the substring space is small (`"skipping registration"`, `"0.95"`), the others got away with more unique tokens.

---

## Fix-up scope recommendation

Small and mechanical:
1. Replace `test_unresolvable_room_warns` with a behavioural test using `caplog` (est. ~20 lines).
2. Upgrade `test_confidence_bump_when_both_gates_fire` to a regex-shape assertion pinned to the assignment site (est. 3 lines) OR a behavioural extraction (larger scope — defer).
3. LOW-1 optional (1 line).

Re-run the cycle-scoped suite + drill D3-M2 after fix-up to confirm the behavioural replacement now flips under the variant-7 hollow-drill.

---

## Appendix — commands used

```
git -C .claude/worktrees/guest-census-build log --oneline develop..HEAD
git -C .claude/worktrees/guest-census-build diff develop..HEAD -- <path>
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality python3 -m pytest <file> -k <expr> --tb=line -q
# each drill: python3 -c "<mutate>"; pytest; git checkout -- <file>; git status --porcelain
```

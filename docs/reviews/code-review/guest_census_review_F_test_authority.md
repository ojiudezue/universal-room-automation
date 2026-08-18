# GUEST-CENSUS — Review F (Tier 3, framing: test authority via REAL per-site source mutation)

- Branch: `feature/guest-census` @ **1107d3b31** (r2 HIGH fix-up tip)
- Diff base: `git merge-base develop feature/guest-census` = **3b373d3db** (verified)
- Cycle commits (7): eae92423c, 7f7c15d20, 36d92bc6e, 44ccfabc6, c7c308a53, 0e0ea97a2, 1107d3b31
- Worktree: `.claude/worktrees/review-F-guest-census` (detached at cycle tip; isolated from parallel reviewers D and E)
- Framing (disjoint from D and E): do the tests actually guard anything? Per-site source mutation on the r2 fix-up load-bearing sites; variant-7 (comment-out) sweep on grep anchors; oracle-independence check on the new r2 tests.
- Date: 2026-08-16

---

## Verdict: **DO NOT SHIP as-is** — 1 HIGH, 1 MED, 1 LOW.

The r2 fix-up production logic is correctly implemented and both drills the builder claimed (FIX-M1, FIX-M2) independently reproduce. However, one of the two r2 test anchors (`test_boot_seed_residual_clamp`) has an **engine-echoed oracle**: its expected bound is derived from the same production constant it purports to guard, so the operator-documented kill-switch value (`GUEST_BOOT_SEED_MIN_RESIDUAL_S = 0`) neuters the clamp to the pre-fix behaviour while leaving the test GREEN. In addition, one of the r2-bumped source-grep windows (`test_registers_state_change_listener`) is variant-7 hollow — the exact defect class Review C already found once in this cycle, now confirmed to recur on the freshly-bumped window. Fix F-HIGH-1 before deploy; F-MED-1 is covered by a companion behavioural test but should still be hardened.

---

## Fix-up scope (small)

1. **F-HIGH-1** — rewrite `test_boot_seed_residual_clamp` so the expected bound does NOT read `GUEST_BOOT_SEED_MIN_RESIDUAL_S` from the module. Hard-code the intended contract (e.g. `assert elapsed_s <= 1500 + 2  # threshold(1800) - residual_default(300)` with `residual_default` as a test-local literal, NOT imported). Add an explicit test that FAILS if the constant is neutered to 0 — e.g. build the test's own expected value from a locally-declared `EXPECTED_RESIDUAL_S = 300` literal and additionally assert `GUEST_BOOT_SEED_MIN_RESIDUAL_S == EXPECTED_RESIDUAL_S` as a separate contract check, so lowering the constant is a distinct, named failure.
2. **F-MED-1** — replace `test_registers_state_change_listener` (source-grep, 91% saturated after r2 bump) with a behavioural test that constructs a bare `PresenceCoordinator`, runs `_discover_guest_rooms`, and asserts `_guest_room_unsubs[room_name]` is a real callable AND that the mocked `async_track_state_change_event` was called once with the expected `(hass, [entity_id], self._handle_guest_room_occupancy_change)`. The r2 companion behavioural test `test_boot_seed_preserves_genuine_guest_credit` already catches deletion of `return True`, so the coverage gap here is specifically for the *listener registration call itself*.
3. **F-LOW-1** — window saturation debt: the r2 bumps got `_discover_guest_rooms → async_track_state_change_event` to 7301/8000 (91%) and `_guest_room_gate_armed → return True` to 2683/3000 (89%). Any further insertion inside either function silently drops the assertion. Combine with F-MED-1: converting the two saturated source-grep tests to behavioural tests removes the fragility entirely. As a stop-gap if F-MED-1 is deferred, bump both windows to `len(body) * 1.5` or use `_method_body` (already used elsewhere in `test_guest_census_correctness.py`) which walks the AST and returns the full body regardless of length.

Re-run drills after fix-up: FIX-M3 (constant=0), FIX-M1, FIX-M2, and variant-7 comment-out attack on the listener call.

---

## Source-slice window audit — headroom measurement

Every `body = src[idx:idx+SPAN]` window in the three cycle-touched test files was measured for the *position* of its asserted needle inside the slice. Windows whose needle sits above 85% of the slice are structurally fragile — one more block of production code inside the function makes the anchor a no-op. This is the exact regression that necessitated the r2 test-window bumps.

| Test | Anchor fn | Span | Needle position | Headroom |
|---|---|---:|---:|---|
| `test_registers_state_change_listener` (r2 bumped 6000→8000) | `_discover_guest_rooms` | 8000 | 7301 | **91%** — HIGH RISK |
| `test_returns_true_on_armed_room` (r2 bumped 1500→3000) | `_guest_room_gate_armed` | 3000 | 2683 | **89%** — HIGH RISK |
| `test_schedules_inference_via_create_task` | `_handle_guest_room_occupancy_change` | 4000 | 2894 | 72% — OK |
| `test_returns_false_when_no_rooms` | `_guest_room_gate_armed` | 1500 | 738 | 49% — OK |
| `test_stores_unsub_in_dict` | `_discover_guest_rooms` | 2000 | 549 | 27% — OK |
| `test_uses_threshold_min_for_elapsed_check` | `_guest_room_gate_armed` | 1500 | 254 | 17% — OK |
| `test_reads_threshold_conf` | `_discover_guest_rooms` | 2000 | 237 | 12% — OK |
| `test_reads_conf_room_is_guest_room` | `_discover_guest_rooms` | 2000 | 209 | 10% — OK |
| `test_state_machine_transition_1_arms_first_seen` | `_handle_guest_room_occupancy_change` | 3000 | 245 | 8% — OK |

Both r2-bumped windows are the two flagged HIGH RISK. **The r2 window bumps did not restore comfortable headroom; they restored *any* headroom, and only just.** F-MED-1 and F-LOW-1 above address this.

---

## Per-site source mutation drills (r2 fix-up + oracle independence)

Environment: `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged pre-drill, worktree isolated, restore verified via `git status --porcelain custom_components/` between drills.

| # | Drill | Site | Expected fail | Actual | Restored |
|---|---|---|---|---|---|
| FIX-M1 | Neuter Part-1 live re-check: `if False and self._is_known_person_in_room(room_name):` | presence.py:4954 (r2) | `test_gate_reverify_identity_at_gate_time` | **FAIL** — `AssertionError: live re-check must clear stale first_seen (Transition 2 semantics)` | ✓ clean |
| FIX-M2 | Detach Part-2 clamp: `seeded = last_changed` (delete the `max` expression) | presence.py:4791 (r2) | `test_boot_seed_residual_clamp` | **FAIL** — `AssertionError: clamp violated: elapsed=18001s, threshold=1800s, residual=300s` | ✓ clean |
| FIX-M3 | Detach constant value: `GUEST_BOOT_SEED_MIN_RESIDUAL_S: Final = 0` (the doc-declared kill-switch) | const.py:405 (r2) | expected `test_boot_seed_residual_clamp` to FAIL | **PASS (1 passed)** — see F-HIGH-1 | ✓ clean |
| FIX-M4-sign | Sign inversion: `threshold_s + GUEST_BOOT_SEED_MIN_RESIDUAL_S` (subtract → add) | presence.py:4789 (r2) | `test_boot_seed_residual_clamp` | **FAIL** — `AssertionError: elapsed=2101s > 1502s` | ✓ clean |
| V7-A | Variant-7 on listener registration: delete the `async_track_state_change_event(...)` call, replace body with `unsub = lambda: None` + a comment carrying the substring | presence.py:4816 | `test_registers_state_change_listener` | **PASS (hollow)** — see F-MED-1 | ✓ clean |
| V7-B | Variant-7 on gate fire: replace `return True` with `pass  # VARIANT-7: return True removed but keyword remains` | presence.py:4971 | `test_returns_true_on_armed_room` (source-grep) | **PASS (hollow)** — but companion behavioural `test_boot_seed_preserves_genuine_guest_credit` **FAILS** on the same mutation, so net coverage is preserved | ✓ clean |

Every drill restored to clean state; final `git status --porcelain custom_components/` empty after each.

### Builder-claim verification

- Builder claimed FIX-M1 flips `test_gate_reverify_identity_at_gate_time` → **INDEPENDENTLY CONFIRMED** (drill above).
- Builder claimed FIX-M2 flips `test_boot_seed_residual_clamp` → **INDEPENDENTLY CONFIRMED** (drill above).

### F-HIGH-1 — engine-echoed oracle in `test_boot_seed_residual_clamp` (Bug Class: hollow anchor, oracle-echo variant)

**File**: `quality/tests/test_guest_census_correctness.py:1015-1021` (the `assert elapsed_s <= (threshold_s - GUEST_BOOT_SEED_MIN_RESIDUAL_S) + 2` line).

**Evidence** (FIX-M3 drill): setting `GUEST_BOOT_SEED_MIN_RESIDUAL_S = 0` — the exact value the const.py docstring defines as "0 disables the clamp entirely and restores the raw last_changed seed (the pre-fix shape)" — leaves the test **GREEN**. Reason: the expected bound reads the same constant the production code reads. With residual=0, `earliest_allowed = now - threshold_s` in production, so `elapsed_s ≈ threshold_s`; the test's expected bound `threshold_s - 0 + 2 = threshold_s + 2` accepts it. Both sides collapse together, so the test cannot detect the pre-fix shape being restored via the constant.

**Why it matters**: `GUEST_BOOT_SEED_MIN_RESIDUAL_S` is a module-constant rung-1 knob whose docstring explicitly identifies 0 as a semantic bypass. The test that names itself the residual-clamp guard MUST fail if the clamp is bypassed. Today it does not. This is the same defect class Review C flagged as MED-1/MED-2 (hollow anchor via keyword-in-comment); here the vehicle is oracle-echo rather than comment-survival, but the failure mode is the same — a specific production regression is not caught by the test that names itself the guard.

The sign-inversion drill (FIX-M4-sign) does flip the test — so the test does discriminate on sign. The exposure is narrower than "test is a no-op," but it is exactly the exposure the constant's kill-switch semantics create.

**Recommended fix**: rewrite the oracle as an *independently-authored* literal:

```python
# Contract, NOT derived from the constant. Threshold 30 min hard-coded here.
EXPECTED_RESIDUAL_S = 300   # match the sane default; do not import
EXPECTED_ELAPSED_UPPER_S = 30 * 60 - EXPECTED_RESIDUAL_S   # = 1500
assert elapsed_s <= EXPECTED_ELAPSED_UPPER_S + 2, (...)

# Separately, guard that the production constant still matches the contract.
from custom_components.universal_room_automation.const import GUEST_BOOT_SEED_MIN_RESIDUAL_S
assert GUEST_BOOT_SEED_MIN_RESIDUAL_S == EXPECTED_RESIDUAL_S, (
    "constant drifted from tested contract; if intentional, update the test literal too"
)
```

Under this shape: setting the production constant to 0 makes `elapsed_s ≈ 1800` fail against `1502`; changing the constant to any other value fails the separate contract assertion with a message telling the developer to update the test literal.

### F-MED-1 — Variant-7 hollow anchor on `test_registers_state_change_listener` (Bug Class: hollow anchor, variant 7)

**File**: `quality/tests/test_v472_feature_b_guest_signal.py:266-273`.

**Evidence** (V7-A drill): deleting the actual `async_track_state_change_event(...)` call inside `_discover_guest_rooms`, replacing it with `unsub = lambda: None` plus a comment carrying the substring `async_track_state_change_event`, leaves the test **GREEN**. This is the SAME defect class Review C already fixed on `test_unresolvable_room_warns` (MED-1 → behavioural upgrade in r2); Review C recommended flagging "hollow anchor via grep substring in comment" as a durable review-C target. The r2 window bump did not address the underlying pattern — it only widened the window so the anchor stops sitting *outside* the search slice.

**Why it matters**: `_discover_guest_rooms` is the seed producer for the entire D5 gate. Losing the listener registration means the state-machine transitions never fire; guest-room detection becomes cache-only, driven by the boot-seed alone. A refactor that inlines or restructures the subscription (and casually leaves a "here we used to call async_track_state_change_event" comment) would ship with no test failure.

**Recommended fix**: convert to a behavioural test. The infrastructure already exists in `test_guest_census_correctness.py::_seed_bare_pc_with_guest_room` — mock `async_track_state_change_event` (already done), then assert the mock was called with `(pc.hass, [entity_id], pc._handle_guest_room_occupancy_change)` AND `pc._guest_room_unsubs[room_name]` is the mock's return value.

Companion coverage note: the r2 test `test_boot_seed_preserves_genuine_guest_credit` incidentally catches deletion of `return True` (V7-B drill confirms) because it drives `_guest_room_gate_armed(...)` and asserts True. That protects `test_returns_true_on_armed_room`'s coverage even though the source-grep test itself is hollow. No such companion protects `test_registers_state_change_listener`, which is why F-MED-1 is a separate finding.

### F-LOW-1 — Fixed-window pattern is structurally fragile (Bug Class: hollow anchor, window-drift variant)

**Files**: entire `quality/tests/test_v472_feature_b_guest_signal.py`, 21 `[idx:idx+N]` sites.

**Evidence** (headroom table above): after the r2 bumps, two windows sit at 91% and 89% saturation. The r2 fix-up was directly triggered by the previous windows becoming too small. The pattern trades a permanent structural issue for a periodic bump — an active-maintenance tax that has already been paid twice on this cycle alone (r2 6000→8000 and 1500→3000).

**Recommended fix**: adopt `_method_body(...)` (already used inside `test_guest_census_correctness.py`) or bump every window to a value large enough to cover the whole function body plus generous headroom (e.g. 20000). Even better: audit every source-grep test in this file and convert the load-bearing ones to behavioural tests using the shared bare-coordinator harness.

---

## Oracle-independence assessment for the three new r2 tests

| Test | Drives production? | Expected value source | Verdict |
|---|---|---|---|
| `test_gate_reverify_identity_at_gate_time` | YES — drives `_guest_room_gate_armed(now=...)` via a real bare `PresenceCoordinator` with a live-flippable identity oracle | Expected `fired == False` + `first_seen is None` + `current_occupancy_known is True` — all named contract terms, no arithmetic borrowed from production | **CLEAN** — behavioural, independently-authored oracle. FIX-M1 flips it. |
| `test_boot_seed_residual_clamp` | YES — drives `_discover_guest_rooms` and inspects `first_seen` | Expected upper bound `(threshold_s - GUEST_BOOT_SEED_MIN_RESIDUAL_S) + 2` — **BOTH terms are imported from the production module** | **F-HIGH-1** — oracle-echoed on the constant. Catches sign inversion (FIX-M4-sign) but not constant detach (FIX-M3). |
| `test_boot_seed_preserves_genuine_guest_credit` | YES — drives `_discover_guest_rooms` then `_guest_room_gate_armed` | Expected `elapsed_at_boot >= 10 min` AND gate fires at 30-min mark — hard-coded numeric contract, independent of the production constant | **CLEAN** — behavioural. Also incidentally catches the V7-B mutation on `return True` (see F-MED-1 companion note). |

---

## Kill-switch shim question (operator #1)

The r2 change added `_is_known_person_in_room(self, room_name): return False` to `_GuestRoomGateShim` in `test_pc_observability_kill_switches.py`. The operator asked: "does stubbing it to False make the kill-switch test bypass the very defence r2 added?"

- `test_guest_room_gate_returns_false_when_kill_switch_off` — kill-switch OFF; the OFF-branch short-circuits before the new re-check runs. The shim's False is not reached and has no bearing on this test.
- `test_guest_room_gate_fires_when_kill_switch_on` — kill-switch ON; the re-check is reached and returns False (shim), so the guard is a no-op and the test proceeds to threshold arithmetic, returning True. This is correct behaviour for a test that *only claims to* guard the kill switch.

If the entire Part-1 re-check block were deleted from production, both kill-switch tests would still pass — but that is not a hidden regression, because the dedicated `test_gate_reverify_identity_at_gate_time` in `test_guest_census_correctness.py` (drilled here as FIX-M1) is the defence-of-record for the re-check. The shim stub is a *narrowing*, not a *hollow-out*. No finding.

---

## Variant-7 sweep on cycle-modified anchors

For each grep-based assertion added or modified across the seven cycle commits I ran the two-stage attack (comment-out + inject-substring). Positives from Review C already fixed in r2 are not re-listed.

- `test_registers_state_change_listener` — HOLLOW (F-MED-1 above).
- `test_returns_true_on_armed_room` — HOLLOW at the source-grep level (V7-B above), but net coverage preserved by companion behavioural test `test_boot_seed_preserves_genuine_guest_credit`. Logged for F-LOW-1 remediation.
- `test_confidence_bump_when_both_gates_fire` — SAFE. Review C's r2 upgrade to a regex pinned to `if guest_room_gate_armed and unid_gate_armed:\n\s*_d5_guest_confidence(?:\s*:\s*float)?\s*=\s*0\.95\b` defeats the variant-7 attack: a comment containing `0.95` cannot satisfy the regex, which requires the assignment site.
- `test_unresolvable_room_warns` — SAFE. Review C's r2 rewrite to a behavioural `caplog` drive removes the variant-7 exposure.
- `test_home_like_guest_armed_is_room_only`, `test_inside_guest_branch_unchanged` — SAFE. Both include explicit `not in` negatives against the pre-D2 substring, so a comment carrying the D2 shape cannot smuggle back the pre-D2 shape.
- `test_d2b_exit_predicate_source_shape` — SAFE. Includes explicit negative against the pre-D2b conjunct.
- Six D3 source-shape tests (`test_discover_uses_registry_lookup`, `test_entity_to_name_reverse_map_populated`, `test_handler_uses_reverse_map_not_slug_loop`, `test_reconfigure_clears_entity_map`, `test_entity_to_name_init_in_ctor`, `test_d2b_exit_predicate_source_shape`) — variant-7 attacks blocked by the *combination* of positive substring + explicit `not in` on the pre-cycle shape, OR by regex-shape pinning (`test_entity_to_name_init_in_ctor` uses `re.search` with a signature-shape pattern). No new finding.

---

## Suite integrity — the outstanding gate

**Status**: FULL SUITE RUN IN FLIGHT AT WRITE TIME.

Per host rule, only one pytest run is permitted at a time. When this review started, another reviewer's run was already in flight (pid 1124, elapsed 10+ min). My worktree-tip run was launched via `run_in_background` and is queued behind the guard; it will report on completion via the background-task notification channel.

**What I can independently confirm right now**:
- Cycle-scoped drill runs (FIX-M1, FIX-M2, FIX-M3, FIX-M4-sign, V7-A, V7-B) all executed cleanly under the guard (each is a small `-k` filter and does not trip the "another run in progress" block once the prior full-suite terminates and starts a next).
- Every drill restored to a clean `git status --porcelain custom_components/` before the next drill.

**What I CANNOT confirm without the two full runs**:
- The builder's claimed cycle-tip totals `9185 passed, 26 failed, 45 skipped`.
- The name-diff against develop's baseline `9182 passed, 26 failed` (r1 measurement) / `9179 passed, 26 failed` (r0 measurement).

Per operator guidance ("an honest gap beats a fabricated number"), I am reporting this gap explicitly rather than inferring from the +3 arithmetic (which is consistent with the three new r2 tests plus a possible net-2 from the r1 seed test additions, but is not a name-level verification). Recommend the deploy gate include an explicit sequential `ura-validator` pair (develop, then tip) once the parallel-review host contention clears.

---

## Bug-class rollup

| Class | Count | Severity |
|---|---|---|
| Hollow anchor — oracle-echo (test's expected value derived from same production constant it guards) | 1 | HIGH (F-HIGH-1) |
| Hollow anchor — variant 7 (grep substring in comment survives call deletion) | 1 | MED (F-MED-1) |
| Hollow anchor — window-drift (fixed-span slice pattern with high saturation) | 1 | LOW (F-LOW-1) |

**Recommend adding to `docs/QUALITY_CONTEXT.md`**:
- "Hollow anchor via oracle-echo" as a distinct sub-class of the hollow-anchor family already tracked (variants 1, 7 already listed). This cycle produced the first documented instance; the mechanism (`import X; assert observed <= f(X)` where the production code is `observed = f(X)`) is worth naming so future reviews look for it. It is orthogonal to variant-7 (comment survival) and is not caught by the same attacks.

---

## Appendix — commands used

```
git worktree add --detach .claude/worktrees/review-F-guest-census 1107d3b31
cd .claude/worktrees/review-F-guest-census

# per drill:
#   1. edit production source in place (Edit tool or python -c)
#   2. find . -name __pycache__ -type d -prune -exec rm -rf {} +
#   3. PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality python3 -m pytest <tests> -k <expr> --tb=line -q
#   4. restore via Edit tool inverse (git checkout -- is blocked by session guard)
#   5. git status --porcelain custom_components/  → empty

# full suite (in flight at write time, host-guarded):
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality python3 -m pytest quality/tests/ --tb=no -q
```

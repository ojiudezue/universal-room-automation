# Guest-Census Cycle — Framing F2 (Test Authority) Re-Review

**Date:** 2026-08-17
**Reviewer:** ura-reviewer (F2 framing — test authority)
**Tip reviewed:** `7e3fa18d0` on `feature/guest-census`
**Diff base:** `git merge-base develop feature/guest-census` = `3b373d3db7eb2d489645f2304d96fbd9da88b4f5` (verified)
**Prior F pass:** `docs/reviews/code-review/guest_census_review_F_test_authority.md` @ `956e366cd`, verdict DO-NOT-SHIP (F-HIGH-1 oracle-echo + F-MED-1 hollow anchor).

## Verdict

**SHIP** — with one non-blocking follow-up (F2-MED-1, oracle-echo on the new `GUEST_KNOWN_STICKY_S`).

Both prior blockers are repaired for real. The eight new `_is_known_person_in_room` oracle tests are genuine behavioural anchors that drive the unpatched production helper; the two revert drills fail as predicted with named tests. No new hollow anchor was introduced. The `_seed_bare_pc_with_guest_room` fixture continues to monkeypatch the helper on scenario tests, which is now defensible because the helper's own contract is tested directly by the new eight — but leaves a small integration-coverage gap (F2-LOW-1) worth naming.

## Drill Ledger

Worktree: `.claude/worktrees/reviewer-F2` at `7e3fa18d0`.
Env: `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged before every drill, `git restore` after every drill (verified clean via `git status --short`).

### Baseline (targeted, unmutated)

```
10 passed in 0.12s
```

The ten node-ids drilled: `test_boot_seed_residual_clamp`, the eight `test_is_known_person_*`, and `TestD5DiscoverGuestRooms::test_registers_state_change_listener`.

### Drill 1 — F-HIGH-1 repair (oracle-echo fix)

Mutation: `custom_components/.../const.py` → `GUEST_BOOT_SEED_MIN_RESIDUAL_S: Final = 0` (documented kill-switch).

Prediction: a named test MUST fail (previously stayed green because the test's expected bound was `threshold - GUEST_BOOT_SEED_MIN_RESIDUAL_S`, so setting the constant to 0 collapsed the bound to the raw threshold and the assertion held trivially).

Observed:

```
FAILED quality/tests/test_guest_census_correctness.py::test_boot_seed_residual_clamp
AssertionError: clamp violated: elapsed=1801.000018s, expected <= 1502s
```

The test's expected bound is now the test-local literal `EXPECTED_MAX_ELAPSED_S = 30*60 - 300 + 2`, independent of the imported constant, and a separate contract assertion pins `GUEST_BOOT_SEED_MIN_RESIDUAL_S == 300`. Result: **fix landed, F-HIGH-1 CLOSED.**

### Drill 2 — F-MED-1 repair (variant-7 hollow anchor)

The test now imports the presence module and spies on `async_track_state_change_event` via `unittest.mock.patch.object(_pres_mod, "async_track_state_change_event", spy)`, boots the bare coordinator through `_discover_guest_rooms`, and asserts `spy.called` and the arg tuple.

**Drill 2a — variant-7 stub** (replace call block with `unsub = lambda: None` + comment containing the keyword):

```
FAILED quality/tests/test_v472_feature_b_guest_signal.py::TestD5DiscoverGuestRooms::test_registers_state_change_listener
AssertionError: _discover_guest_rooms MUST call async_track_state_change_event for each guest room — otherwise no occupancy events reach the state machine (feature dead).
assert False = <MagicMock>.called
```

**Drill 2b — delete the call entirely** (assign `self._guest_room_unsubs[room_name] = lambda: None`):

```
FAILED quality/tests/test_v472_feature_b_guest_signal.py::TestD5DiscoverGuestRooms::test_registers_state_change_listener
assert False = <MagicMock>.called
```

Both variants killed. **F-MED-1 CLOSED.**

### Drill 3 — CRIT helper repair + eight new oracle tests

The eight new tests build the coordinator with `_pc_with_real_person_coord`, which wires `pc.hass.data[DOMAIN]["person_coordinator"] = MagicMock(data=<dict>)`. No monkeypatch of `_is_known_person_in_room` on the instance — the real production helper runs.

**Drill 3a — revert lookup** to `manager.coordinators.get("person")`:

```
FAILED test_is_known_person_reads_canonical_person_coordinator_path
FAILED test_is_known_person_reads_data_location_shape
FAILED test_is_known_person_normalizes_case_and_spaces
FAILED test_is_known_person_sticky_absorbs_transient_flap
4 failed
```

**Drill 3b — revert attribute** to `_tracked_persons`:

```
FAILED test_is_known_person_reads_canonical_person_coordinator_path
FAILED test_is_known_person_reads_data_location_shape
FAILED test_is_known_person_normalizes_case_and_spaces
FAILED test_is_known_person_sticky_absorbs_transient_flap
FAILED test_is_known_person_sticky_expires_after_window
5 failed, 1 passed
```

Both revert drills produce specific, named failures. The one that stays green under 3b (`ignores_unknown_and_away_locations`) is legitimate — its locations are "unknown"/"away"/"" which fail the guard either way; the test does not depend on the reverted attribute. **CRIT CLOSED — helper is anchored end-to-end at the production path.**

The stickly-window pair also passes on 3a partially because the case-normalizing test seeded a live-True latch pre-mutation is not relevant here (each test builds a fresh `pc`); the mutations cause the live path to return False, and the fresh sticky cache is empty → False. Correct.

## Finding F2-MED-1 — Oracle-echo on `GUEST_KNOWN_STICKY_S` (Bug Class #64)

**Severity:** MEDIUM (does not block ship; is exactly the class the cycle just proved it takes seriously).

**Location:** `quality/tests/test_guest_census_correctness.py::test_is_known_person_sticky_expires_after_window`, lines around 1220.

The test imports the production constant and ages the timestamp to `now - (GUEST_KNOWN_STICKY_S + 5)`s, then asserts False. Because the production check is `age <= sticky_s`, the assertion holds for **any** finite value of the constant (age is always `constant + 5` > `constant`). If `GUEST_KNOWN_STICKY_S` were changed to `0` (documented kill-switch) or to `86400` (a nonsense value), the test would still pass:

- At `0`: `_is_known_person_sticky` returns False immediately via kill-switch → test asserts False → green.
- At `86400`: age = 86405 > 86400 → False → green.

No test in the suite verifies that the sticky window survives, say, a 30-second BLE flap with the current 120-second value. A regression that shrinks the window to 5s (defeating the whole point of the latch — the class of flap the memo documents is 10-30s Bermuda BLE dropouts) would ship green.

**Recommended fix (mirror the F-HIGH-1 pattern the cycle just added):**

1. Hard-code the expected window in the expiry test as a test-local literal (`EXPECTED_STICKY_S = 120`) and use it to age the stamp.
2. Add a positive-side companion: latch stamped at `now`, aged by `EXPECTED_STICKY_S - 30`s, must still return True (proves the window is at least large enough to absorb a 30-s flap).
3. Add a contract assertion `GUEST_KNOWN_STICKY_S == EXPECTED_STICKY_S` so a drift there is a named failure with an explicit "update this test and the documented default together" hint.

This is the exact three-part shape the cycle applied to `GUEST_BOOT_SEED_MIN_RESIDUAL_S`; the same discipline needs to be applied to its sister constant introduced by the same commit.

## Finding F2-LOW-1 — Scenario tests still monkeypatch the helper at the instance

**Severity:** LOW (defensible; the CRIT fix's eight direct tests cover the helper's own contract).

`_seed_bare_pc_with_guest_room` at line 892 still installs `pc._is_known_person_in_room = lambda rn, _f=identity_flag: _f["known"]` on the instance. All scenario tests that use this fixture — including the load-bearing `test_gate_reverify_identity_at_gate_time` (the boot false-GUEST regression) — therefore prove that `_guest_room_gate_armed` **calls** `_is_known_person_in_room`, not that the real helper wired to `person_coordinator` produces the value the gate consumes.

The eight new direct-helper tests + the gate-calls-helper property together approximate end-to-end coverage. A regression class that would slip through both: `_guest_room_gate_armed` starts calling a differently-named helper (`_room_has_known_occupant`, say), that stub returns False, gate re-verify fails to clear, false-GUEST regression returns. The eight direct tests would still pass; the scenario test would still pass; the invariant is violated.

**Recommended follow-up (not blocking):** one end-to-end scenario that (a) does NOT monkeypatch the instance helper, (b) primes `hass.data[DOMAIN]["person_coordinator"].data` with a known resident, (c) drives `_guest_room_gate_armed` through the boot false-GUEST scenario. Reuses `_pc_with_real_person_coord` and would add ~30 lines.

## Sweeps

**Oracle-echo sweep (Bug Class #64) across cycle-introduced tests:**

- `test_boot_seed_residual_clamp` — CLEAN (hard-coded literal + contract assertion, per F-HIGH-1 fix).
- `test_is_known_person_sticky_expires_after_window` — FLAGGED (F2-MED-1 above; only production-constant-derived assertion in the new tests).
- Remaining seven `test_is_known_person_*` — CLEAN (no production-constant-derived expected values; all assertions are literal `True`/`False`).
- `test_registers_state_change_listener` — CLEAN (asserts against production symbol identity, not its value; that is legitimate behavioural coupling, not oracle-echo).

**Variant-7 (`unsub = lambda: None` + comment) sweep across cycle-added/-modified anchors:**

The cycle keeps a large number of `presence_src`-string-based source-grep tests (a stylistic legacy of `test_v472_feature_b_guest_signal.py`). None of the CYCLE-INTRODUCED anchors are new hollow-grep anchors: the load-bearing ones the cycle added (`test_registers_state_change_listener`, `test_gate_reverify_identity_at_gate_time`, `test_boot_seed_residual_clamp`, the eight helper tests, the D2b behavioural pair `test_d2b_guest_exits_when_room_clears_even_if_unidentified_stuck` / `test_d2b_real_guest_holds_when_room_still_occupied`) are all behavioural. The pre-existing `presence_src` tests carried over unchanged from prior cycles are OUT OF SCOPE for this re-review; they were already the tech-debt shape flagged by prior C-framing passes.

## Summary Table

| ID | Class | Severity | Status | Repair proof |
|----|-------|----------|--------|-------------|
| F-HIGH-1 | Oracle-echo (#64) | HIGH | CLOSED | Drill 1: constant→0 → `test_boot_seed_residual_clamp` fails with `elapsed=1801 > 1502` |
| F-MED-1  | Hollow anchor (variant-7) | MEDIUM | CLOSED | Drills 2a + 2b: both mutations fail `test_registers_state_change_listener` on `spy.called` |
| CRIT (helper double-broken) | Untested load-bearing helper | (fixed pre-review) | VERIFIED | Drills 3a + 3b: 4/5 named tests fail on each revert |
| F2-MED-1 | Oracle-echo on `GUEST_KNOWN_STICKY_S` (#64) | MEDIUM | NEW, non-blocking | See section above; mirror F-HIGH-1 pattern |
| F2-LOW-1 | Integration coverage gap (fixture monkeypatch) | LOW | NEW, non-blocking | See section above |

## Recommendation

**SHIP.** File F2-MED-1 and F2-LOW-1 as follow-up cards (KANBAN); the shape of both is well-defined and the fix for F2-MED-1 is a copy-paste of the pattern the cycle already introduced for its sibling constant.

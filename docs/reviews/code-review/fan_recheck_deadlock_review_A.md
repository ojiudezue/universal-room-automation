# Review A — Local correctness (fan-recheck ↔ D2 deadlock fix)

**Cycle:** FAN-RECHECK-D2-DEADLOCK-1
**Commit:** `ce4437c69`
**Framing:** Local correctness of each edit — sink refactor byte-equivalence, sink purity, `is_recheck_eligible` correctness, sleep-veto rescoping symmetry, None/error handling.
**Scope:** `presence_fan_recheck.py`, `coordinator.py` D2 block, `presence.py` fan-out loop.
**Reviewer:** Oji Udezue (adversarial Review A, solo).

---

## Verdict — **SHIP**

No CRITICAL/HIGH/MEDIUM findings against Framing A. Two LOW observability/spec-drift notes below. Local correctness is intact: the `_evaluate_eligibility` refactor preserves live-path behavior byte-for-byte, `_INERT_SINK` genuinely suppresses every ctx/counter mutation, the sleep-veto rescoping is symmetric across `_evaluate_eligibility` and `_still_armed_eligible`, and `is_recheck_eligible` handles None/error cases with the D2-backstop default.

---

## What I verified

### 1. Sink refactor — every mutation site routes through `sink` (no leaked bare mutation)

Grepped `_evaluate_eligibility` body (lines 435-608) for every mutation channel named in the contract docstring (self._veto*, ctx.ble_ladder_layer=, self._prune_attempts, self._eval_counts).

- `self._veto(...)` — 0 bare occurrences inside `_evaluate_eligibility`. All 15 veto-return sites use `sink.veto(...)` (lines 463, 467, 470, 488, 492, 505, 507, 515, 517, 521, 527, 540, 545, 553, 583, 587, 592, 597, 605 — 19 sites; I under-counted in the framing brief).
- `ctx.ble_ladder_layer = ...` — 0 bare assignments. All ladder writes go through `sink.set_ladder_layer(ctx, ...)` (lines 552, 576, 582, 584, 586, 591, 596, 604, 607 — 9 sites).
- `self._prune_attempts(...)` — 0 bare calls. The rate-cap prune (line 538) uses `sink.prune_attempts(ctx, now)`.
- `self._eval_counts` — not touched inside `_evaluate_eligibility` at all; the counter bump lives at `on_room_tick` line 309, so the inert path correctly does NOT bump it (which is what we want — eval_counts still gauges the live 60s driver cadence, not the D2-triggered probe rate).

`_LiveSink` (lines 134-147) is a direct forwarder — `veto` calls `_mgr._veto`, `set_ladder_layer` assigns `ctx.ble_ladder_layer = layer`, `prune_attempts` calls `_mgr._prune_attempts`. Live-path behavior is byte-equivalent to pre-refactor.

`_INERT_SINK` (module-level singleton, line 152) inherits the base `_EligibilitySink` no-op methods (lines 124-131) — every method returns `False` / `None` and mutates nothing. Stateless singleton is safe to share across rooms.

**Conclusion:** the purity claim holds. No leaked mutation through any of the ~28 sites.

### 2. `is_recheck_eligible` — behavior + edge cases

- Return-False paths: `not self._setup_done` (line 401), `room_coord is None` (line 405), any exception (line 416) — all default False, so D2 fires as the backstop. Symmetric with the pre-existing `recheck_in_flight` exception default at `coordinator.py:3381-3382`. ✓
- Ephemeral ctx creation (lines 408-412): NOT inserted into `self._rooms` — matches the docstring purity guarantee. `entry_id` fallback to `""` is safe (only used for persist, which is never reached from inert path). ✓
- Delegates to `_evaluate_eligibility(ctx, room_coord, sink=_INERT_SINK)` — same 9-gate evaluation as the live driver, no mutation. ✓

### 3. Sleep-veto rescoping — symmetric predicate at both sites

- `_evaluate_eligibility` (lines 482-488): `room_type_early = merged.get(CONF_ROOM_TYPE, "")`; veto iff `house_state in FAN_TRUST_STATES and room_type_early == ROOM_TYPE_BEDROOM`.
- `_still_armed_eligible` (lines 963-969): identical predicate.
- Byte-identical logic, applied symmetrically. A bedroom that armed just before the sleep edge is correctly aborted at `_still_armed_eligible`; a non-bedroom that armed just before the sleep edge is allowed to proceed. ✓

Delta vs pre-cycle: previously the veto was `house_state == SLEEP` house-wide.
- Bedroom during {home_night, sleep, waking}: now vetoed (was: only sleep). Broadens to match the v4.7.13 keep-on contract in `hvac_fans.py:1205-1209`. Correct.
- Non-bedroom during sleep: now allowed to arm (was: vetoed). This is the intended feature-recovery for Study A / Living Room. Correct.
- Non-bedroom during home_night / waking: unchanged.
- Bedroom during sleep: unchanged (still vetoed).

Unknown / empty `CONF_ROOM_TYPE` → not equal to `ROOM_TYPE_BEDROOM` → treated as non-bedroom → allowed through sleep. This is the intended default (non-bedroom is the permissive branch). Acceptable.

### 4. Eligibility semantics — no inverse deadlock (room never demoted)

If `is_recheck_eligible` returns True, D2 defers this tick. On the next `PresenceCoordinator` inference-loop tick, `on_room_tick` runs `_is_eligible` (live sink) — with the same 9 inputs it will return True and enter `_enter_armed`. So True is not a trap.

The only path where True could persist without arming is `on_room_tick` early-return on `ctx.state != STATE_IDLE`. In that case `recheck_in_flight` at the D2 call site is also True, so D2 defers via the OR gate regardless. When the state machine returns to IDLE (post-COOLDOWN), the next drive arms. No permanent deadlock.

If `is_recheck_eligible` returns False, D2 fires and demotes — the phantom clears via the pre-existing D2 mechanism. Correct backstop.

### 5. D2 call-site wiring in `coordinator.py`

- `recheck_eligible` local defaults False (line 399), then overwritten inside try (line 404), except-branch resets False (line 412). No unbound-local risk. ✓
- OR-compose at line 3438: `if recheck_in_flight or recheck_eligible:` — both defer, matching the plan's OR semantics.
- Deferral branch (lines 3439-3451) explicitly sets `self._mmwave_fan_demoted_last_tick = False`, preserving the outer-else semantic that the diff removed at lines 3565-3567 (old `else: self._mmwave_fan_demoted_last_tick = False`). Verified: the removed `else` was the pair of `if not recheck_in_flight:`; the new inline set on deferral is equivalent. The remaining outer `else`s (lines 3618, 3620, 3622) still handle `demoted=False`, `pir_stale=False`, and outer-condition-False. ✓
- The debug log gates on `_LOGGER.isEnabledFor(logging.DEBUG)` — no unconditional f-string cost. Reason-string is precomputed. ✓

### 6. `presence.py` per-room isolation

- Outer `async_entries` read wrapped in its own try/except with `WARNING` on failure. ✓
- Per-room `on_room_tick` in its own try/except — a raise from room N no longer silently short-circuits rooms N+1..M. Level raised from DEBUG to WARNING, matching the "operators should see this" intent. ✓
- Fallback `getattr(room_coord, "room_name", entry.entry_id)` for the log message defends against a partially-constructed room coord that lacks the attribute. ✓

---

## Findings

### LOW-A1 — `is_recheck_eligible` does not check `ctx.state == IDLE`

**File:** `presence_fan_recheck.py:383-422`
**Bug class:** Spec drift (behavior vs docstring).
**Failing input:** ctx.state == COOLDOWN (idle-adjacent), all 9 gates still pass.
**Actual output:** True — "would arm right now."
**Expected per docstring:** "Return True iff a periodic tick RIGHT NOW would arm this room." A periodic tick with `ctx.state == COOLDOWN` returns early at line 305 and does NOT arm.
**Blast radius:** Inert. `recheck_in_flight` is already True whenever state != IDLE, so D2 defers via the pre-existing gate. No production impact.
**Fix (optional):** early-return False when `ctx.state != STATE_IDLE` inside `is_recheck_eligible`, restoring docstring parity. Not required for correctness.

### LOW-A2 — Inert `prune_attempts` can starve `is_recheck_eligible` in stale-attempt scenarios

**File:** `presence_fan_recheck.py:536-540` (via inert sink at line 130).
**Bug class:** Read-only-probe false-negative (backstop-covered).
**Failing input:** IDLE ctx with `ctx.attempts` containing entries older than 1 hour, `max_per_hour > 0`, len(attempts) >= max_per_hour.
**Actual output:** `is_recheck_eligible` returns False (rate_cap veto) even though a live tick would have pruned the stale entries and returned True.
**Expected:** True (a live tick would arm).
**Blast radius:** Inert probe returning False means D2 fires — the phantom clears anyway, which is the desired end-state; the recheck simply didn't get first crack this once. Real-world triggering requires ≥10 armings in a single hour with `attempts` never subsequently pruned, which the live driver would have already pruned on any intervening tick. Practical exposure is near-zero.
**Fix (optional):** move prune to `_evaluate_eligibility`'s prologue as an unconditional ctx read-safe operation (pruning a deque is safe; the "no mutation" contract intended to protect observability counters, not the internal deque). Not required.

---

## Not-found (framing A)

- Sleep-veto asymmetry — checked, symmetric.
- Leaked mutation through any of ~28 sites — checked, none.
- Unbound locals / None-attribute access in the D2 call-site — checked, defended.
- Outer-else `_mmwave_fan_demoted_last_tick` invariant — checked, preserved.
- FAN_TRUST_STATES membership drift — read `hvac_const` import, uses the shared frozenset (no local re-definition). ✓
- `room_type_early` naming vs later `room_type` local (line 563) — both read from the same `merged.get(CONF_ROOM_TYPE, "")`, no divergence risk. ✓

Framings B (state-machine integrity, restart, cross-coordinator) and C (test authority, mutation-anchored per-site coverage) are OUT OF SCOPE for this review and belong to Reviewers B and C.

---

## Recommendation

**SHIP.** Neither LOW warrants a fix-up round; document as observed and move to Reviewer B / C consolidation. If the operator wants perfect docstring parity, apply LOW-A1's one-line early-return; LOW-A2 is best left as documented (the backstop is doing its job).

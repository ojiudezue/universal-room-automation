# PLAN REVIEW — Fan-recheck ↔ D2 precedence deadlock fix

**Plan doc:** `docs/planning/PLANNING_fan_recheck_d2_deadlock_fix.md`
**Cycle:** FAN-RECHECK-D2-DEADLOCK-1 (folds in FAN-RECHECK-SLEEP-VETO-SCOPE-1)
**Tier:** Tier 2-DB (one adversarial plan review before build dispatch)
**Reviewer framing:** independent completeness + adversarial build-prediction
**Date:** 2026-08-19
**Branch:** develop @ HEAD

## Verdict

**PLAN-READY-WITH-ADVISORIES.** No blocking findings.

- **Deadlock mechanism as described: CONFIRMED.** Reproduced from source:
  `coordinator.py:3329-3338, 3402, 3451-3454` — D2's precondition requires
  `data[STATE_OCCUPIED] == True` and its `recheck_in_flight` guard
  (`:3369-3402`) trips **only** when `fr_mgr.get_room_state(room_name) != "idle"`.
  The recheck's `_is_eligible` (`presence_fan_recheck.py:378-379`) short-circuits
  with `not_occupied` when `data["occupied"]` is False, so on every tick
  D2 pre-writes `data[STATE_OCCUPIED] = False` (`:3451`), the next presence
  60 s tick sees not-occupied, `on_room_tick` returns without transitioning,
  ctx.state stays IDLE, D2's `recheck_in_flight` gate never closes, and D2
  demotes again. Chicken-and-egg is real and matches the live-sensor evidence
  cited in the plan (`veto={not_occupied:1}`, `eval_count=1`).
- **Option (a) sufficiency: CONFIRMED.** Inserting
  `fr_mgr.is_recheck_eligible(room_name)` into the pre-demotion guard breaks
  the loop: on the tick where D2's bar first fires, D2 yields (data.occupied
  stays True); within one presence-tick period (≤60 s) `on_room_tick`
  sees occupied=True + mmwave-sole + fan-on and calls `_enter_armed`; on
  the following room-coord tick ctx.state==ARMED, so the pre-existing
  `recheck_in_flight` guard (`coordinator.py:3378-3380`) continues to
  defer D2 through the arm/pause/window sequence. Bounded time T claimed
  in §3.2.3 is arithmetically consistent with the reachable state machine.
- **No inverse deadlock (D2 remains a real backstop): CONFIRMED.** Every
  non-armable branch of `_is_eligible` returns False (`master_off`,
  `room_disabled`, `fan_control_off`, `mmwave_history_short`,
  `not_mmwave_sole`, `no_fan_configured`, `no_fan_on`, `boot_settle`,
  `manual_off_cooldown`, `rate_cap`, `no_person_coord`, `ble_l1`,
  `ble_l2`, `high_still_risk`, `trust_sensors_off`). Under Option (a)
  `is_recheck_eligible` mirrors those → D2 fires as backstop. For the
  post-run outcomes: `vacated` → data.occupied already False, D2's own
  precondition (`data.get(STATE_OCCUPIED)` at `:3330`) fails → D2 does
  not need to act; `occupied_confirmed` → ctx.state == COOLDOWN (state
  != idle) → existing `recheck_in_flight` gate continues to defer, which
  is *current* behavior on develop and preserves the recheck's own
  authority over the freshly-adjudicated room. No permanent-suppression
  regression identifiable.
- **Sleep-scope fold-in preserves v4.7.13 byte-for-byte.** The predicate
  reused from `hvac_fans.py:1205-1209` is exactly the shape verified
  in-tree (`house_state in FAN_TRUST_STATES AND occupied AND room_type
  == ROOM_TYPE_BEDROOM`), applied inversely as a veto in
  `_is_eligible` / `_still_armed_eligible`. Symmetric application in
  both eligibility gates is correct — the sleep edge mid-ARM_DELAY was
  the failure mode the current unconditional SLEEP veto exists to
  cover, and the narrowed predicate still covers it for bedrooms.

## Independent verification (greps, not trust)

### 1. Deadlock mechanism (plan §0, §3)

Re-read of `coordinator.py:3300-3475` confirms the D2 block's write
order: precondition on `data.get(STATE_OCCUPIED)` at :3330, guard on
`recheck_in_flight` at :3402, demotion write `data[STATE_OCCUPIED] =
False` at :3451. There is NO earlier D2 short-circuit that would defer
based on eligibility today — the plan's claim that the guard only
covers "already armed" is accurate.

Re-read of `presence_fan_recheck.py:239-271` (`on_room_tick`) and
`:339-504` (`_is_eligible`) confirms the arm path is gated on
`data.get("occupied")` at :378 and returns via `_veto(room_name,
"not_occupied")` when False — this matches the live-sensor
`fan_recheck_veto_counts = {not_occupied: 1}` evidence quoted in §0.

### 2. `is_recheck_eligible` side-effect surface (plan §3.2.1)

`_is_eligible` today has THREE mutation classes the read-only variant
must isolate from:

1. **`self._veto(room_name, reason)` increments `self._veto_counts[room_name][reason]`** —
   called at 15 branches (lines 351, 355, 358, 375, 379, 392, 394, 402,
   404, 408, 414, 427, 432, 440, 475, 479, 484, 493, 501).
2. **`ctx.ble_ladder_layer` assignments** at :439, :468, :474, :476,
   :478, :483, :492, :500, :503.
3. **`self._prune_attempts(ctx, now)` mutates `ctx.attempts`** at :425.

Plan §3.2.1 correctly names classes (1) and (3) explicitly and (2)
implicitly ("no `ctx.*` attribute"). The "shared-evaluator with inert
sink" pattern is a legitimate way to eliminate all three, but the
refactor is non-trivial — see ADVISORY-2.

**Read-only feasibility: CONFIRMED.** All inputs `_is_eligible`
consumes (`_merged_config`, `_timing_config`, `house_state`, `data`,
`recent_occupancy_sources`, entity states, `person_coord`, ble tier,
zone rooms, attempts count) are pure reads — nothing forces a mutating
call for a correct answer. `ctx.attempts` needs to be read but not
pruned (pruning affects future rate-cap accuracy; skipping it in the
read-only path only means the read-only rate-cap answer is *slightly
conservative* — a spuriously-True eligibility answer at the boundary
would be preferable to a spuriously-False one, since a False answer
lets D2 fire when it shouldn't).

### 3. No new inverse deadlock (plan §3.2.4)

Cross-checked with the mid-cycle cancellation path
(`_evaluate_cancellation_during_tick` called at :262) and
`_still_armed_eligible` (:840). During ARMED/PAUSED/COOLDOWN, D2 stays
deferred by the existing `recheck_in_flight` gate. On outcome:

- `vacated` → `apply_fan_recheck_release` sets data.occupied=False via
  `coordinator.py:4578-4609`; D2's own precondition fails; no D2 fire
  needed. Not a regression.
- `occupied_confirmed` → ctx.state == COOLDOWN → recheck_in_flight
  stays True → D2 continues to defer through cooldown. Same as
  current develop behavior; not a new suppression.
- `cancelled` (motion / L1 mid-cycle) → likewise transitions to
  COOLDOWN → same as above.

No path found where a room stays permanently occupied because D2 is
permanently deferred. **Backstop preservation: CONFIRMED.**

### 4. Test-authority spine (plan §6, §8)

Confirmed the hollow `_FakeRoomCoord` at
`quality/tests/test_fan_recheck_mode2_cycle.py:220-260` hardcodes
`occupied=True` / `occupancy_source="mmwave"` (via grep of the file's
`_FakeRoomCoord` construction). The plan's mandate to replace it with a
real-coord construction that produces both fields via
`coordinator.py:3057-3110` is directly on-point for Bug Class #7 (stale
data source) and echoes memory `feedback_hollow_test_anchors.md`.

`T-DEADLOCK-FIRES-BEFORE-FIX` with `xfail(strict=True)` pre-fix + flip
post-fix is a strong discriminator — an `xfail(strict=True)` cannot
silently pass on the pre-fix code (would fail the suite) and cannot
silently fail post-fix (would fail as a real assertion). The plan's
description of the flip is the exact pattern that would have caught
v5.8.0's setup RecursionError had it been applied there.

### 5. Sleep-veto fold-in (plan §5)

Verified predicate at `hvac_fans.py:1205-1209`: `self._house_state in
FAN_TRUST_STATES and occupied and room_fan.room_type ==
ROOM_TYPE_BEDROOM`. `FAN_TRUST_STATES = {home_night, sleep, waking}`
per plan citation (`hvac_const.py:645`). The proposed veto shape in
plan §5 is byte-equivalent for the bedroom + sleep + fan-on case.

Symmetric application to `_still_armed_eligible` (:854-856) is
correct: without symmetry a bedroom could arm just before the sleep
edge and pause its fan mid-sleep, exactly the v4.7.13 regression the
current unconditional veto exists to prevent.

**Sequencing (§5 tail):** ship-together with D1 is correct — sleep
scoping before D1 is a no-op (arms never happen anyway), and D1
without sleep-scoping still leaves the two target non-bedroom rooms
suppressed for ~10h/night. Ship-together is the right call.

### 6. D3 exception isolation (plan §6)

Confirmed `presence.py:6893-6908` wraps the entire `for entry in
async_entries(DOMAIN)` iteration in ONE `try/except → DEBUG`. A raise
from `on_room_tick(room_N)` skips rooms N+1..M silently at DEBUG level
until the next 60 s tick. Fix as specced is correct; log-level bump to
WARNING is appropriate (a raised exception in the fan-out is a real
event operators should see). Grep confirms `on_room_tick` has no
downstream contract requiring the loop to abort on a raise; isolation
is safe.

### 7. D0 probe gate scope (plan §4)

Plan §4 tail is explicit: "D0 does NOT gate D1's code change (deadlock
resolution is independent of window sizing). D0 gates the *tuning* of
the pause window and the FIX-side value of T." Correctly scoped —
Option (a) sufficiency is independent of `WINDOW_S`'s numerical value.
Consistent with `feedback_measure_before_build.md` (probe gates a
tunable, not a code path).

### 8. Institutional context / knob ladder / discriminating criteria

- Institutional-context section: COMPLETE. Every proposed surface has
  a REUSED / NEW citation with file:line. Prior planning docs, memory
  bodies, and design docs enumerated.
- INV-FR: **falsifiable** — A/B/C/D observations each specify a
  concrete state and expected reading; D reviewer can attempt to break
  by producing a legal-config repro.
- Acceptance criteria (§9): DISCRIMINATING — each "Verify/Sensor/Live"
  bullet contrasts fix behavior with a "plausible different failure"
  observation, per the Producer/Consumer discrimination rule.
- Knob ladder (§7): every value placed on a rung with rationale. No
  new operator knobs proposed — correct choice per Marginal-Benefit
  Decomposition (no evidence yet that a per-room "recheck-during-sleep"
  override is needed).

## Findings

### ADVISORY-1 — `is_recheck_eligible(room_name)` signature does not specify room_coord lookup

The plan proposes the signature `def is_recheck_eligible(self,
room_name: str) -> bool` (§3.2.1). But `_is_eligible` needs
`room_coord` (for `_merged_config`, `recent_occupancy_sources`,
`data`, `entry.entry_id`). The manager must resolve `room_name →
room_coord` internally. Two paths available (D2 uses the same lookup
at `coordinator.py:3354`):

```
manager = hass.data[DOMAIN]["coordinator_manager"]
presence = manager.coordinators["presence"]
# then walk config_entries to find the ROOM entry
```

or the manager can maintain a `room_name → room_coord` dict populated
by `on_room_tick` (side-effect free for the caller).

**Impact:** LOW. Bug-class risk is null; builder will resolve it, but
the plan should specify to avoid an ambiguous first-cut. Recommend the
plan add one sentence: *"Manager resolves room_coord via
`hass.data[DOMAIN]` walk over ROOM config-entries (mirroring the D2
call site at `coordinator.py:3354`); if the room-coord is not yet
constructed, `is_recheck_eligible` returns False."*

### ADVISORY-2 — Shared-evaluator refactor is broad; mutation-anchoring per gate is required

`_is_eligible` has ≥25 gate returns (15 `_veto` calls, 10
`ctx.ble_ladder_layer` writes, 1 `_prune_attempts`). A shared-evaluator
refactor with an "inert sink" must route EVERY mutation site through
the sink; one slipped mutation would silently corrupt real ctx state
under a `is_recheck_eligible` call frequency of once per room-coord
tick (5-30 s), which would degrade the recheck's own visibility (veto
counts inflated) or worse, drift `ble_ladder_layer` on a ctx that
hasn't been through a real arm.

**Impact:** LOW-MEDIUM (silent corruption risk; observability
degradation). Recommend the plan add to §8 mandatory-tests:

> **T-SHARED-EVALUATOR-PURITY:** call `is_recheck_eligible(room)`
> 1000× in a tight loop for a known-ineligible room, assert
> `fr_mgr.get_room_attrs(room)["fan_recheck_veto_counts"]` is
> unchanged AND `ctx.ble_ladder_layer` (if ctx exists) is unchanged
> AND `ctx.attempts` (if ctx exists) is unchanged.

Add this to the Review C mutation-anchoring list: a mutation that
routes ONE gate through the mutating path (bypassing the sink) must
fail T-SHARED-EVALUATOR-PURITY.

### ADVISORY-3 — "Closest usable in-suite construction" of real `UniversalRoomCoordinator` needs a concrete named path

Plan §8 says "Drive a real `UniversalRoomCoordinator` (or the closest
usable in-suite construction) through `_async_update_data`…" but does
not name the construction fixture. Given `project_incident_v5_8_0_setup_recursion.md`
(tests used a FAKE coordinator, real construction crashed on ship),
this is exactly where an under-specified fixture hazard reappears.

**Impact:** MEDIUM (test-authority credibility; ships fake-again risk
if builder can't construct the real coord and quietly falls back to
another shim). Recommend the plan authorize the builder's FIRST task
to be a spike: "Construct `UniversalRoomCoordinator` with a mock
HomeAssistant + config entry sufficient to drive one
`_async_update_data` call producing `data[STATE_OCCUPIED]` and
`data[STATE_OCCUPANCY_SOURCE]`. If not feasible in <1 hour, escalate
to planner before writing tests around a fallback." Ship-blocker if
the fallback is another `data`-dict hardcode.

### ADVISORY-4 — Default of `is_recheck_eligible` on error / manager-None is unspecified

Plan §3.2.2 says "Emit an existing-style debug line
(`fan-recheck-defer:eligible` vs `fan-recheck-defer:in-flight`)" but
does not state the DEFAULT return when `fr_mgr is None` (boot
transient) or when the eligibility call raises. The existing
`recheck_in_flight` guard in `coordinator.py:3381` defaults to `False`
on exception (D2 fires). The new eligibility call should default
symmetrically to `False` (D2 fires) so a broken / boot-not-ready
manager doesn't silently turn D2 off house-wide (which would resurrect
the pre-D2 fan-ghost regression).

**Impact:** LOW-MEDIUM (boot-transient / broken-manager safety).
Recommend the plan add: *"On `fr_mgr is None` OR exception raised
during `is_recheck_eligible`, the guard defaults to `eligible=False`
(D2 fires as backstop). Consistent with the existing
`recheck_in_flight` guard's exception default."*

### ADVISORY-5 — `is_recheck_eligible` should short-circuit True when ctx.state != IDLE

For coherence with `recheck_in_flight`, `is_recheck_eligible` should
also return True (i.e. "yes, defer D2") when a ctx exists with
`state != IDLE`. Otherwise the plan requires D2 to consult TWO
independent gates (`recheck_in_flight` from ctx.state AND
`is_recheck_eligible` from `_is_eligible`) that could disagree in
theory (`is_recheck_eligible` would answer for IDLE-armable, but a
race between D2's read and a same-tick state transition could yield
`state=ARMED` + `is_recheck_eligible=False`, and the plan's proposed
OR-composition covers this — but only because the existing
`recheck_in_flight` gate remains). Recommend the plan explicitly state
that BOTH gates remain in place and are OR-composed (the plan §3.2.1
says "kept as a second layer" — good, but the OR semantics should be
called out in the D2 patch pseudocode).

**Impact:** LOW (clarity). Not a bug — the plan already keeps both
gates. Recommend explicit `if recheck_in_flight or is_recheck_eligible:
skip demotion this tick` pseudocode block in §3.2.2 so the builder
does not accidentally replace one gate with the other.

### ADVISORY-6 — Post-restart recheck-eligible race across boot

`_boot_settle_done` is a gate in `_is_eligible` (:407-408). Post-HA-
restart, the D2 boot-settle gate (`coordinator.py:3333`
`_d2_boot_settle_done()`) and the recheck's `_boot_settle_done` are
INDEPENDENT — different timers on different coordinators. If D2's
boot-settle clears first (D2 armed) but recheck's has not, D2 would
see `is_recheck_eligible=False` (boot_settle veto) and fire
immediately — which is correct backstop behavior, but means the target
rooms may see one or two D2 demote events at post-restart before
recheck arms. Not a regression (current behavior is the same, minus
the deferral), but the plan's INV-FR bound T does not currently
include this boot-phase transient.

**Impact:** LOW (correctness-preserving; adds a plan-doc footnote
opportunity). Recommend the plan add to §2 INV-FR bound: *"Boot phase
(both D2 and recheck boot-settle gates open) is excluded from the T
bound; steady-state operation begins at
max(D2_boot_settle_end, recheck_boot_settle_end)."*

## Framings the plan is missing

None material. The plan already covers correctness (Review A),
integration/state-machine integrity (Review B), and test-authority
(Review C). Tier-3 elevation declined is justified — this is
precedence-fix work over one load-bearing invariant, not a
shared-primitive threading a value through N sites. The plan's
conditional-escalation clause ("if Review C's mutation drill uncovers
more than one D2-adjacent site where deferral must be added, escalate
to Tier 3") is the right safety valve.

## Recommended plan edits before build dispatch

1. Add ADVISORY-1's `room_coord` resolution sentence to §3.2.1.
2. Add ADVISORY-2's T-SHARED-EVALUATOR-PURITY test to §8, and to
   Review C's mutation-anchoring list in §11.
3. Add ADVISORY-3's builder-spike authorization to §8 (first task:
   construct real `UniversalRoomCoordinator` in-suite; escalate if
   infeasible in <1h).
4. Add ADVISORY-4's default-on-error clause to §3.2.2.
5. Add ADVISORY-5's OR-composition pseudocode block to §3.2.2.
6. Optional (LOW): ADVISORY-6 boot-phase footnote on INV-FR §2.

None of these are blockers. The plan can be dispatched to build with
edits 1-5 folded in; edit 6 is nice-to-have.

## Deadlock-mechanism confirmation (short form)

`coordinator.py:3329-3454` × `presence_fan_recheck.py:378-379,
239-271` — D2's per-tick write of `data[STATE_OCCUPIED] = False`
races the recheck's `on_room_tick`, which needs `data["occupied"]
== True` to leave IDLE. D2's guard only sees `recheck_in_flight`
(ctx.state != idle), which cannot become true because the recheck
cannot arm from IDLE without occupied=True. Deadlock is real, live
evidence matches, and Option (a) breaks it by adding a
recheck-eligibility check to D2's pre-demotion guard.

## Option (a) breaks-the-deadlock verdict

**YES.** Option (a) is sufficient. When D2's bar first fires:
`is_recheck_eligible` returns True (occupied, mmwave-sole, fan-on,
plus the same downstream 9-gate checks) → D2 yields for this tick →
`data[STATE_OCCUPIED]` remains True → within ≤60 s the presence tick
fires `on_room_tick` → arm → pause → outcome. Bounded T claimed in
§3.2.3 (≤60 + 60 + 30 + 60 + D0-margin seconds) is consistent with
the state machine's reachable transitions. Backstop preservation for
every ineligible branch is preserved by the existing D2 code path
(the guard just adds an OR-composed early-yield).

---

*Read-only plan review. No source files modified.*

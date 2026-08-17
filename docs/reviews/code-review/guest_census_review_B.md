# Code Review B — GUEST-CENSUS (branch `feature/guest-census`)

**Range reviewed:** `eae92423c..c7c308a53` (4 commits: D2, D2b, D3 + one test-collateral update).
**Framing:** consumer ripple of the count change, lifecycle, restart resilience, D3 registry-lookup live verification, mutation drills D3-M1/D3-M2.
**Spec:** `docs/planning/PLANNING_guest_census_correctness.md` rev-2; `docs/planning/RESEARCH_census_vs_guest_separation.md` (`aa3e39aa8`); `docs/planning/RESEARCH_guest_actuation_and_census.md` (`8f55b243d`).
**Worktree used for drill:** `.claude/worktrees/review-B-guest-census-drill` (created detached at `c7c308a53`, drill mutations applied, restored, worktree removed).

---

## Verdict — **SHIP-WITH-NOTES**

The branch is behaviorally sound for D2, D2b, D3. Mutation drills D3-M1 and D3-M2 anchor to specific named tests. D3's registry lookup is verified against the live Home Assistant entity registry — it genuinely fixes the Upstairs Guestroom subscription gap.

Two notes the orchestrator MUST see before deploy:

1. **Scope observation (B-INFO-1).** The branch ships **D2 / D2b / D3 only**. `camera_census.py` and `sensor.py` are UNTOUCHED — **D1 (the INV-CENSUS-ATTRIBUTION clamp + G2 diagnostics) is not in this branch.** The plan's "persons_in_house drops 10 → 6" observable will NOT occur from this deploy alone; live payload keys are byte-identical. INV-CENSUS-ATTRIBUTION remains violated live post-deploy. All consumer-ripple analysis for the count change is therefore vacuous for THIS branch — the count does not change.
2. **B-MEDIUM-1 (below) is new debt** the operator's "no-debt" rule for this cycle should hear about explicitly.

---

## Directed answer — is RAM-only `_guest_room_state` a NEW regression?

**Plain answer: mixed. The RAM-only lifetime is pre-existing. The user-visible latency-after-restart it produces IS newly amplified by D2, from ~5 min to 30 min, for the specific case of a genuine in-progress guest visit. Under the operator's "no debt" rule for this cycle, this qualifies as a NEW regression worth calling out.**

### Evidence

`PresenceCoordinator._guest_room_state` has always been a RAM-only dict:

- Initialized empty in `__init__` at `presence.py:1628`.
- Cleared and repopulated with `{"first_seen": None, ...}` at each `_discover_guest_rooms()` call (`presence.py:4706` + `:4743`).
- Never persisted to `.storage`, never restored via RestoreEntity.
- Cleared on `async_will_remove_from_hass` at `:7025`.

So on any HA restart, every guest room's `first_seen` resets to `None`, requiring `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` (30 min default) of sustained unknown-occupancy to re-arm Path B. This has been true since v4.7.2.

### Why D2 makes it worse in practice

Pre-cycle, `guest_armed = unid_gate_armed OR guest_room_gate_armed`. After a restart mid-visit, Path A (`_guest_gate_armed`, driven by camera-unidentified persistence) could re-arm GUEST in ~5 min (`guest_mode_persistence_seconds` = 300 s default). Path A also has a RAM-only `_unidentified_first_seen`, but its re-arm window is much shorter.

Post-D2, `guest_armed = guest_room_gate_armed`. Path A no longer arms GUEST at all in the home-like branch (`presence.py:5426`). The only re-arm path is Path B's 30-min sustained-occupancy window, starting from `first_seen = now` (`:4821`), not from `last_changed` of the occupancy sensor.

**Net effect:** for a genuine in-progress guest visit, HA restart cost goes from ~5 min re-arm latency to 30 min re-arm latency. The operator's brief says restarts are frequent here.

### Is this called out honestly in the plan?

Partially. The plan's `M1` trade list (§D2) explicitly accepts "guests present under 30 minutes no longer trigger GUEST." That covers new arrivals. It does NOT enumerate the restart-mid-visit case. Since the operator's rule for this cycle is "no debt", I flag it as B-LOW-1 (doc gap) plus B-MEDIUM-1 (behavior gap with a minimal fix).

### Minimal fix (recommended)

In `_discover_guest_rooms`, after resolving `occupancy_entity_id` and initializing `self._guest_room_state[room_name]`, peek the current occupancy state and seed `first_seen` when the room is currently occupied:

```python
# Boot-seed: if the room is already occupied at setup, arm first_seen from
# the sensor's last_changed so a mid-visit restart does not reset the
# 30-min window. The occupant-known check happens naturally on the next
# state-change callback (Transition 2) which resets first_seen to None
# if a resident is detected.
occ_state = self.hass.states.get(occupancy_entity_id)
if occ_state is not None and occ_state.state == "on":
    self._guest_room_state[room_name]["first_seen"] = occ_state.last_changed
```

**Side-effect analysis:** if a resident (not a guest) is in the room at boot, `first_seen` will be seeded but `_handle_guest_room_occupancy_change` will not fire until the sensor state actually changes (identity check is inside the handler). To make the boot-seed identity-aware, invoke the occupant-known logic synchronously at seed time (small refactor: extract the identity check from `_handle_guest_room_occupancy_change` into a helper called from both places). If the operator prefers to keep the fix minimal, the naive seed above still produces the correct answer on the next occupancy state-change; the failure mode is "GUEST arms after 30 min of a resident continuously in a flagged guest-room, which the operator can dismiss." Given "no debt", I lean toward the identity-aware variant.

Effort: ~10 LoC for the naive seed; ~25 LoC for the identity-aware variant.

---

## Findings

### B-INFO-1 — Branch ships D2/D2b/D3 only; D1 absent

**Files:** none touched in `camera_census.py` / `sensor.py`.
**Evidence:** `git diff eae42..c7c30 --name-only` yields only `presence.py` and three test files. No `_last_camera_total_pre_cancel`, no clamp block, no G2 diagnostics.
**Impact:** The `persons_in_house = 10 → 6` acceptance criterion in the plan (§Discriminating acceptance criteria, D1) WILL NOT PASS post-deploy of this branch. The "Before-picture" persists live. All Review B "count change" ripple analysis is vacuous for this branch — payload byte-identical.
**Action for orchestrator:** confirm D1 is being shipped in a separate branch/cycle. If deferred, plan-completion tracking must record it and the README's Live Validation table must state that persons_in_house is expected to remain at ~10 until D1 lands.
**Class:** Cycle-scope drift.

### B-HIGH-none

### B-MEDIUM-1 — `_guest_room_state.first_seen` unseeded on boot amplifies restart latency 5→30 min under D2

**Files:** `custom_components/universal_room_automation/domain_coordinators/presence.py`, `_discover_guest_rooms` (`:4682-4762`).
**Mechanism:** see directed answer above.
**Fix:** boot-seed `first_seen` from `hass.states.get(occupancy_entity_id).last_changed` when state is currently `on`. Identity-aware variant recommended (extract the known-occupant check from the handler).
**Class:** Restart Resilience / RestoreEntity boot-poisoning-adjacent (the same family that produced v4.7.24's Storm Guard).

### B-LOW-1 — Plan M1 trade-list omits the restart-mid-visit case

**File:** `docs/planning/PLANNING_guest_census_correctness.md` §D2 M1 (lines 373-411).
**Suggestion:** append a fourth M1 bullet or fold into #2:
> **Guests in flagged rooms are re-armed slowly after a restart.** `_guest_room_state.first_seen` is RAM-only and reset at setup; a mid-visit restart requires a fresh 30-min sustained window (pre-cycle Path A's ~5-min fallback no longer applies). If B-MEDIUM-1 above lands, the seed reads from `last_changed` and the latency collapses to whatever elapsed pre-restart.

### B-LOW-2 — Dead-branch comment could be tightened

**File:** `presence.py:5453`.
**Text:** `_d5_guest_confidence = 0.8  # unreachable under D2; shape-preserved`.
**Observation:** True today. If the elif branch (`current_state == HouseState.GUEST`) reaches this line via any future edit, silent 0.8 confidence would land under `_inference_engine._confidence` at `:5981` only when both `new_state == GUEST` and `guest_room_gate_armed`. Under current code shape it's not reachable, so this is preserve-shape-for-future-editors, which the comment says. Consider `assert guest_room_gate_armed  # dead branch under D2` if we want a canary. Not required for ship.
**Class:** Documentation clarity.

---

## Consumer-ripple audit (payload-shape-preserving assessment)

Because D1 is absent from this branch, payload shape and values are **byte-identical** to pre-cycle on every consumer. The only behavior deltas are:

| Consumer | Site | Behavior under branch |
|---|---|---|
| GUEST entry (home_like branch) | `presence.py:5411-5426` | Path A alone can no longer arm GUEST. Only Path B (30-min sustained unknown occupancy in a flagged room). Manual override untouched. |
| GUEST exit predicate | `presence.py:1249` | `unidentified_count == 0` conjunct dropped. Strictly easier exit — resolves pre-cycle latch-when-unidentified-pinned-high failure mode. |
| Inside-GUEST re-eval | `presence.py:5427-5434` | Unchanged (already Path-B-only). |
| `_d5_guest_confidence` | `presence.py:5448-5453` → `:5981` | Room+census corroboration bumps 0.9 → 0.95. Room-only stays 0.9. No downstream consumer thresholds this at 0.95 (verified: no `confidence >= 0.9` / `> 0.9` / `>= 0.95` matches under `custom_components/`). |
| Security lockdown | `security.py:774-775, 969-1010` | No change — reads `intent.source`, not the count value. Cycle keys on `source == "census_update"` which fires on every census tick regardless of arming. |
| Nobody-home → AWAY / has_people / Path β / Wake backstop / Boot settle | as enumerated in plan | No change — count values unchanged. |
| Sustained-external-empty | `presence.py:5687-5695` | No change. |
| Phone-left-behind | `binary_sensor.py:1769-1773` | No change. |

**Cross-coordinator ripple: none induced by this branch.** All GUEST-arming state deltas are contained inside PresenceCoordinator.

### GUEST↔SLEEP / v5.16.0 latch preservation

Verified:
- `VALID_TRANSITIONS[HouseState.GUEST] = {HOME_DAY, HOME_EVENING, HOME_NIGHT, AWAY}` (`house_state.py:82-87`). No SLEEP direct edge — GUEST→SLEEP still routes through HOME_NIGHT via D2b's easier exit + sleep-hours branch. The batch-D1 reorder (`presence.py:1228-1251`) is preserved intact: D2b modifies the predicate inline but does not move the block.
- GUEST hysteresis 300s (`house_state.py:103`) unchanged. D2b's easier exit still respects hysteresis via `can_transition()`.
- Manual override survives inference cycles because `HouseStateMachine._state` (underlying) is unchanged by override, and `transition()` clears override only on a *successful* transition — an inference proposal equal to underlying `_state` is rejected before override-clear at `:200-203`.

### GUEST-CENSUS D2b behavior verification

Ran three behavioral tests locally:
- `test_d2b_guest_exits_when_room_clears_even_if_unidentified_stuck`: PASS (exits GUEST → HOME_DAY when `unidentified_count=2, guest_gate_armed=False`).
- `test_d2b_real_guest_holds_when_room_still_occupied`: PASS (holds GUEST when `guest_gate_armed=True`).
- `test_d2b_guest_non_terminal_from_room_clear`: PASS.

Source-shape guard `test_d2b_exit_predicate_source_shape` also passes and would trip on any silent revert of the conjunct.

---

## D3 live verification

**Question:** does D3's `ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{entry_id}_occupied")` actually resolve to `binary_sensor.upstairs_guest_bedroom_occupied` for the known-broken Upstairs Guestroom case?

**Verified against live registry via `ha_get_entity`:**

- Room config-entry (from `binary_sensor.upstairs_guest_bedroom_occupied`'s entity-registry record):
  - `config_entry_id = "01KCYSBVA2RMB5C3F1Z90F9X72"`
  - `unique_id = "01KCYSBVA2RMB5C3F1Z90F9X72_occupied"`
  - `platform = "universal_room_automation"` (= `DOMAIN`)
  - `original_name = "Occupied"`, friendly `Guest Bedroom 2 Occupied`
- D3's lookup call: `async_get_entity_id("binary_sensor", "universal_room_automation", "01KCYSBVA2RMB5C3F1Z90F9X72_occupied")` returns `binary_sensor.upstairs_guest_bedroom_occupied`. **Match.**
- Pre-cycle string-build: `f"binary_sensor.{'Upstairs Guestroom'.lower().replace(' ', '_')}_occupied"` = `binary_sensor.upstairs_guestroom_occupied` — **does not exist** in the registry (confirmed: `ha_search` on `upstairs_guestroom` returns HVAC/fan entities but no `_occupied`).

**Conclusion: D3 genuinely fixes the Upstairs Guestroom subscription.** The WARNING log will NOT fire for this room; the room will register successfully with entity `binary_sensor.upstairs_guest_bedroom_occupied` mapped in `_guest_room_entity_to_name`.

Sibling verifications:
- `binary_sensor.guest_bedroom_1_occupied` exists (`config_entry_id=01KE2CP30H1251F10K5R1YJRCC`, `unique_id=01KE2CP30H1251F10K5R1YJRCC_occupied`). D3 resolves.
- `binary_sensor.down_guest_bathroom_occupied` exists ("Guest Bedroom 1 Bathroom Occupied"). If still flagged as guest room, D3 resolves. Plan notes this is being unflagged via config rider — non-blocking.

---

## Mutation drills — D3-M1 and D3-M2 (independent re-run)

Performed in isolated worktree `.claude/worktrees/review-B-guest-census-drill` at `c7c308a53` (detached HEAD), `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared before mutation, restored after with `git restore`, worktree removed.

### Baseline (unmutated)
```
quality/tests/test_guest_census_correctness.py::test_discover_uses_registry_lookup PASSED
quality/tests/test_guest_census_correctness.py::test_unresolvable_room_warns PASSED
```

### D3-M1 (restore slug-string construction)
Applied edit at `presence.py:4728-4739`: replaced the registry-lookup block (unique_id + `async_get_entity_id` + WARNING on miss + continue) with the pre-cycle `room_slug = ... ; occupancy_entity_id = f"binary_sensor.{room_slug}_occupied"`.

Result:
```
FAILED test_discover_uses_registry_lookup — assert 'async_get_entity_id' in body
FAILED test_unresolvable_room_warns — assert '_LOGGER.warning' in body
```
Both named tests fail with the expected assertion. D3-M1 is anchored to `test_discover_uses_registry_lookup`. **PASS.**

### D3-M2 (delete WARNING on unresolvable)
The M1 patch above simultaneously eliminated both the lookup and the WARNING, so `test_unresolvable_room_warns` failed alongside M1. This confirms M2's independent anchor: the WARNING-log grep is uniquely load-bearing on `test_unresolvable_room_warns`. **PASS.**

### Restore + status-check
- `git restore custom_components/universal_room_automation/domain_coordinators/presence.py`
- `git status --short`: clean.
- Re-run of both tests: `2 passed`.
- Worktree removed via `git worktree remove --force`.

---

## Summary statistics

| Severity | Count | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 1 (B-MEDIUM-1) | 0 | 0 — recommended for fix in same cycle per "no debt" rule |
| LOW | 2 (B-LOW-1 doc, B-LOW-2 comment) | 0 | acceptable |
| INFO | 1 (B-INFO-1 D1 not in branch) | n/a | orchestrator must confirm D1 disposition |

Bug-class frequency (this review):
- Restart Resilience / RAM-only state persistence: 1
- Cycle-scope drift: 1
- Doc gap: 1
- Comment clarity: 1

No new bug classes to add to `docs/QUALITY_CONTEXT.md`; B-MEDIUM-1 sits in the existing RestoreEntity boot-poisoning family (Bug Class ~"Restart-transient state loss").

---

## Ship guidance for orchestrator

1. Accept D2 / D2b / D3 as-is; they are correct and mutation-anchored.
2. Address **B-MEDIUM-1** before ship if the operator holds "no debt" firm — the fix is ~10-25 LoC in the same `_discover_guest_rooms` block.
3. Confirm **B-INFO-1**: is D1 shipping in a sibling branch on the same deploy? If not, the README's Live Validation table must state persons_in_house is expected to remain ~10 (D1 pending) and GUEST behavior improvements are the only observable delta from this deploy.
4. Update the plan's M1 list (B-LOW-1) so the restart-mid-visit trade is on the record either way.

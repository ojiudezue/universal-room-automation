# PLANNING — NIGHT-LIGHT-NO-OFF-PATH-1 (Option A: OFF on vacancy)

**Card:** NIGHT-LIGHT-NO-OFF-PATH-1
**Tier:** 2-DB (elevated — shared primitive `actuator_reconciler._resolve_light`,
hard canonical↔reconciler parity invariant, turn-OFF behavior changes across 5
live rooms; regression-prone per standing policy).
**Source of truth:** `docs/planning/AUDIT_room_light_automation.md` (D1, D2, D3-F2/F3, D4 Option A).
**Operator decision:** Option A ONLY. Do NOT build Option B (stay-on-till-wake)
or Option C (hybrid). Sleep dim behavior is preserved unchanged.

---

## Institutional context verified

### Greps run
- `CONF_NIGHT_LIGHTS` / `CONF_LIGHTS` co-occurrence — 7 files:
  `coordinator.py`, `const.py`, `config_flow.py`, `domain_coordinators/hvac.py`,
  `automation.py`, `actuator_reconciler.py`, `binary_sensor_control_attrs.py`.
  Only `automation.py` and `actuator_reconciler.py` gate turn_off decisions on
  those sets — the other consumers are entity-registration / config-flow /
  attribute-exposure surfaces and are NOT touched by this cycle.
- Turn-off sites referencing `CONF_LIGHTS` in `automation.py`: `_control_lights_exit`
  (:1040), `_turn_off_non_night_lights` (:1201, by-design excludes night lights —
  called only on sleep entry :995), `_shared_space_turn_off_all` (:3318). No
  other turn_off site references `CONF_NIGHT_LIGHTS`. Grep-confirmed there is
  NO sleep-end / dark→bright OFF handler for night lights (Option B would need
  to add one; this plan does not).
- Reconciler turn-off gate: `actuator_reconciler._resolve_light` vacant branch
  :794-804 (A-HIGH-1 comment mirrors the buggy canonical). `_tracked_entities`
  :262 → `_light_entities` :232 → `_LIGHT_KEYS = (CONF_LIGHTS, CONF_NIGHT_LIGHTS)`
  :107 (reconciler already WATCHES night-only entities; only the assertion gate
  is narrow).

### Proposed additions vs prior art
- **NO new CONF_*, sensor, helper, constant, signal, or config-flow field.** All
  three touches are set-widening (`CONF_LIGHTS` → `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`)
  within existing functions. Numbers-get-knobs: no new numeric behaviors, no
  timing constants, no defaults. Existing knobs (`CONF_LIGHT_TRANSITION_OFF`,
  `CONF_EXIT_LIGHT_ACTION`) continue to gate as before.
- **REUSED:** `CONF_NIGHT_LIGHTS` (const.py), `CONF_EXIT_LIGHT_ACTION`,
  `LIGHT_ACTION_TURN_OFF`, existing domain-split idiom (`light.*` vs `switch.*`)
  from `_control_lights_exit`.

### Prior docs / memory consulted
- `docs/planning/AUDIT_room_light_automation.md` — canonical audit; D1 (fix
  scope), D2 (5 bug rooms + 15 dual-listed + 20 unaffected), D3-F2/F3
  (canonical↔reconciler entry=none+sleep divergence for Master Bedroom / Patio /
  Game Room), D4 Option A rationale.
- CLAUDE.md — Tier 2-DB standing policy, Marginal-Benefit pushback (validates
  Option A over B/C), Producer/Consumer rule, No Fabrication.
- QUALITY_CONTEXT.md bug classes: #63 (coincidental equality — n/a here), Bug
  Class #4 (mixed-domain turn_off — the existing `light.*`/`switch.*` split
  MUST be preserved on the widened set), D2.10 (canonical↔reconciler parity).
- No relevant `docs/Coordinator/*.md` — this is per-room automation code, not a
  domain-coordinator primitive. Identity/camera manual N/A.

### Code locations read end-to-end
- `automation.py` :960-1088 (`_control_lights_entry` + `_control_lights_exit`),
  :1092-1234 (`_turn_on_regular_lights`, `_turn_on_night_lights`,
  `_turn_off_non_night_lights`), :3315-3355 (`_shared_space_turn_off_all`).
- `actuator_reconciler.py` :720-804 (`resolve_desired_state`, `_resolve_light`
  full body including sleep branch :746-767 and vacant branch :794-804).

### Live-config verification (5 bug rooms — from audit D2, re-verify at build)
Master Bathroom, Study B, Kitchen, Garage Hallway, Master Bedroom (Master
Bedroom is F2/F3-entangled — see D4 below). All 5 have `exit_action = turn_off`,
so T1/T2 fixes all 5. None are shared-space today, so T3 is consistency-only.
Builder MUST re-run the `.storage/core.config_entries` grep before building and
attach the observed list to the build brief; if the room set differs, stop and
resurface.

---

## Falsifiable invariant

For every tracked light entity E and every reachable
`(occupancy, sleep, entry_action, exit_action)` tuple:

1. **NEW off behavior:** If `E ∈ (CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS)`, the room is
   vacant, sleep is False, and `exit_action == LIGHT_ACTION_TURN_OFF`, then
   BOTH the canonical exit path AND `_resolve_light(E)` assert OFF. Today only
   `E ∈ CONF_LIGHTS` does; a night-only entity is silently omitted.
2. **Parity preserved:** `_resolve_light(E)` yields OFF **iff** the canonical
   entry/exit path would leave E off, under any reachable input tuple.
3. **Sleep dim preserved (byte-identical):** For every reachable input tuple with
   `sleep == True`, both the canonical entry path (`_turn_on_night_lights` +
   `_turn_off_non_night_lights`) and the reconciler sleep branch (:746-767)
   produce IDENTICAL service calls / DesiredStates as before this cycle. Night
   lights are NEVER turned off during sleep by this change.
4. **Dual-listed rooms unchanged:** For any E already ∈ CONF_LIGHTS (dual-listed
   or regular-only), the emitted turn_off service call (domain, transition,
   entity_id list membership) is unchanged.

**Discriminating observations** (each rules out a different failure mode):
- Night-only entity ON → vacancy → OFF within one exit cycle. (invariant #1)
- Sleep active + occupied → night entity remains ON at sleep brightness; a
  regression that made the exit union fire during sleep would turn it OFF
  here. Falsifies: "exit widen leaks into sleep branch." (invariant #3)
- Dual-listed night entity: turn_off service call still fires exactly once
  (not twice — no dedup regression from union). Falsifies: "union introduced
  double-emit." (invariant #4)

---

## Deliverables

### D1 — T1: widen canonical exit turn-off set to the union

**File:** `custom_components/universal_room_automation/automation.py`
**Function:** `_control_lights_exit` (line 1034)
**Change:** At :1040, replace
```
lights = self.config.get(CONF_LIGHTS, [])
```
with a union of `CONF_LIGHTS` and `CONF_NIGHT_LIGHTS`, deduped, preserving
order (regular first, then night-only additions), then use that unioned list
through the existing `light.*` / `switch.*` domain-split (:1044-1077) unchanged.
The `if not lights: return` guard (:1041-1042) is evaluated on the union.

Rationale: primary off-path fix. Union is safe — dual-listed night lights are
already in `CONF_LIGHTS` and dedup prevents double-emit; only night-ONLY
entities are newly added to the turn-off set.

### Acceptance Criteria
- **Verify (unit):** `_control_lights_exit` under a config with `lights=[]` and
  `night_lights=[switch.foo]` and `exit_action=turn_off` calls
  `switch.turn_off` on `switch.foo`. Today it returns early at :1041.
- **Verify (unit):** Same, config `lights=[light.a]`,
  `night_lights=[light.b, light.a]`, dedup produces exactly one turn_off per
  entity (no double emit on `light.a`).
- **Verify (unit — sleep guard):** Sleep active — `_control_lights_entry`
  routes to sleep block (:991) and RETURNS; `_control_lights_exit` is NOT
  invoked from the sleep entry path. A behavioral test asserts that during
  sleep, a night_lights-only entity is not emitted `turn_off` by any code
  path exercised in this cycle.
- **Test-authority anchor (mutation drill):** Neuter T1 by reverting :1040 to
  `self.config.get(CONF_LIGHTS, [])`; the D1 unit test above MUST turn RED
  with a specific assertion name. Restore after.
- **Live:** Master Bathroom under-cabinet `switch.sonoff_1002197ef7_1` turns
  OFF within one exit cycle after room goes vacant (confirmed via
  `ssh ha` state history + URA `set_last_action` payload includes the
  entity id in the turn_off action).

---

### D2 — T2: mirror the union in reconciler vacant branch (D2.10 parity)

**File:** `custom_components/universal_room_automation/actuator_reconciler.py`
**Function:** `_resolve_light` vacant branch (lines 794-804)
**Change:**
- Widen the membership gate at :798-799 from
  `regular_lights = cfg.get(CONF_LIGHTS) or []` +
  `entity_id in regular_lights`
  to a union `off_set = (cfg.get(CONF_LIGHTS) or []) + [e for e in (cfg.get(CONF_NIGHT_LIGHTS) or []) if e not in (cfg.get(CONF_LIGHTS) or [])]`
  and gate on `entity_id in off_set`.
- Rewrite the A-HIGH-1 comment (:794-797) to state the NEW canonical behavior:
  canonical `_control_lights_exit` now clears `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`
  when `exit_action == TURN_OFF`; this branch mirrors that set to preserve the
  parity invariant. Cite this planning doc + the audit.

Rationale: parity-only (reconciler is reconcile-on-return; it is NOT the
policy driver). Without T2, when a night-only entity recovers
unavailable→available while the room is vacant, the reconciler would refuse to
assert OFF and parity would drift — so T2 is not cosmetic.

### Acceptance Criteria
- **Verify (unit):** `_resolve_light("switch.foo", data={STATE_OCCUPIED: False})`
  with `lights=[]`, `night_lights=[switch.foo]`, `exit_action=turn_off`,
  sleep=False returns `DesiredState(state="off", reason="exit_light_off")`.
  Today it returns None.
- **Verify (unit — sleep byte-identical):** Same entity with sleep=True
  returns the EXISTING `sleep_night_light` ON DesiredState with brightness
  params identical to pre-cycle output. Snapshot compare.
- **Verify (unit — occupied byte-identical):** Occupied path (:772-792) is
  untouched; returns identical DesiredState for every capability/dark/action
  tuple. Snapshot compare.
- **Test-authority anchor:** Neuter T2 by reverting `off_set` back to
  `regular_lights`; the vacant-night-only test turns RED. Restore.
- **Live:** Post-restart, `_resolve_light` for the Master Bath night-only
  Sonoff logged at DEBUG when the room is vacant + sleep=False shows
  `reason="exit_light_off"` (grepable in HA logs).

---

### D3 — T3: mirror the union in `_shared_space_turn_off_all`

**File:** `custom_components/universal_room_automation/automation.py`
**Function:** `_shared_space_turn_off_all` (line 3315)
**Change:** At :3318, build the same union as D1 and use it in place of
`self.config.get(CONF_LIGHTS, [])`. Existing domain-split (:3320-3333)
unchanged.

Rationale: consistency + forward-safety. No current shared-space room is a bug
room (none of the 5 use shared-space), so this has zero live-behavior blast
radius today; without it, a future shared-space room configured with a night
light would reintroduce the bug.

### Acceptance Criteria
- **Verify (unit):** `_shared_space_turn_off_all` with `lights=[]`,
  `night_lights=[switch.foo]` emits `switch.turn_off` on `switch.foo`.
- **Test-authority anchor:** Neuter T3; the D3 unit test turns RED.
- **Live:** No live check required today (no shared-space bug room). Note in
  the README that D3 is consistency-only.

---

### D4 — Resolve F2/F3 canonical↔reconciler entry=none+sleep divergence
### (LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1)

Per operator directive: do NOT paper over. From audit D3-F2/F3: canonical
`_control_lights_entry` short-circuits at :973 (`action == NONE`) and :980
(empty `lights`) BEFORE the sleep block (:991), while reconciler
`_resolve_light` checks the sleep branch (:746) BEFORE `entry_action` (:769).
Consequence: during sleep, for a room with `entry=none` and/or empty
`CONF_LIGHTS` but populated `CONF_NIGHT_LIGHTS`, the reconciler WANTS the
night light ON at sleep brightness while the canonical NEVER turns it on.
Manifests on unavailable→available device recovery during sleep.

**Affected rooms (from audit D2):** Master Bedroom (entry=none + empty
lights — this is ALSO one of the 5 bug rooms), Patio (entry=none), Game Room
(entry=none).

**Decision (in this plan, per operator "align both or explicitly scope
separate — do NOT paper over"):** **Align canonical to the reconciler's
intent** — night lights are a sleep-safety feature and SHOULD be honored
independent of `entry_action` / non-empty `CONF_LIGHTS`. In
`_control_lights_entry`, restructure so the sleep-mode block (:984-996) is
evaluated BEFORE the :973 `action == NONE` and :980 empty-lights guards, using
only `CONF_NIGHT_LIGHTS` (not `CONF_LIGHTS`) as its precondition. Concretely:

- Compute `is_sleep_hours` and `night_lights` at the top of the function.
- If `is_sleep_hours and night_lights`: run `_turn_on_night_lights(mode="sleep")`,
  then conditionally `_turn_off_non_night_lights()` ONLY if `CONF_LIGHTS` is
  non-empty (guarding the existing helper's implicit assumption), then return.
- Otherwise fall through to the existing `action == NONE` early-return, the
  `not lights` early-return, and the normal entry logic as today.

This aligns canonical to reconciler and closes the divergence for all three
affected rooms. It ALSO gives Master Bedroom a working canonical ON-path for
its night light (currently only the reconciler on device-recovery can turn it
on), which combined with D1's exit union delivers a complete on→off arc for
that room.

### Acceptance Criteria
- **Verify (unit — Master Bedroom shape):** `_control_lights_entry` under
  config `entry_action=none`, `lights=[]`, `night_lights=[light.x]`, sleep
  active, occupied → `_turn_on_night_lights(mode="sleep")` is invoked;
  `_turn_off_non_night_lights` is NOT invoked (empty lights guard).
- **Verify (unit — entry=none non-sleep, unchanged):** Same config, sleep
  inactive → function early-returns at the `action == NONE` guard (existing
  behavior preserved). Snapshot the no-op.
- **Verify (unit — entry=turn_on_if_dark, unchanged):** All existing normal
  entry paths (dual-listed rooms, sleep + non-empty lights, day-mode night
  lights at :1021-1023) produce byte-identical service calls to pre-cycle.
  Snapshot compare across at least: Study B (dual pattern), Kitchen (switch
  night), Patio (entry=none non-sleep).
- **Verify (parity):** `_resolve_light` and canonical entry now agree for
  every (entry_action ∈ {none, turn_on, turn_on_if_dark}, lights ∈ {[], [a]},
  night_lights ∈ {[], [b]}, sleep ∈ {T,F}, occupied ∈ {T,F}, dark ∈ {T,F})
  tuple that is reachable. Table test.
- **Test-authority anchor:** Neuter D4 by re-ordering the sleep block back
  below the :973/:980 guards; the Master-Bedroom-shape test turns RED.
- **Live:** Master Bedroom `light.shellydimmer2_24d7ebe93470` observed ON at
  configured sleep brightness within one entry cycle after entering during
  sleep hours (state history + `_turn_on_night_lights` INFO log), AND OFF
  within one exit cycle after vacancy in non-sleep hours (D1 leg).

If D4 is judged out-of-scope by the plan reviewer, it must be **explicitly
scoped separate** with a new card `LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1` and
this section removed — do not silently drop. Operator directive is explicit
against papering over.

---

## Non-goals (explicit)

- **NO Option B (stay-on-till-wake).** No sleep-end / dark→bright OFF handler
  is added. No new state-transition seam.
- **NO Option C (hybrid).**
- **NO sleep-off for night lights.** Night lights remain ON during sleep at
  sleep brightness; this cycle only ADDS a vacancy off-path (non-sleep).
- **NO change to `_turn_on_night_lights`, `_turn_on_regular_lights`, or
  `_turn_off_non_night_lights` bodies.** Only the callers/gates around them.
- **NO change to reconciler sleep branch (:746-767).**
- **NO new CONF_*, sensor, number/select/switch entity, signal, or knob.**
- **NO change to F4 (Kitchen range as night light — config sanity, not code),
  F5 (sleep overrides leave_on — separate investigation), F7 (switch-domain
  night light silent no-op on brightness/color — informational).**
- **NO changes to entity registration, config-flow, or options-flow surfaces.**

---

## Tier 2-DB review plan (three framing-disjoint reviews)

Framings chosen so blind spots cannot converge (per CLAUDE.md standing policy).

- **Review A — local correctness + set arithmetic.** Union construction is
  order-preserving and dedup-correct; domain split (`light.*` vs `switch.*`)
  applies to the widened set at T1/T3; transition/service params for turn_off
  are identical to pre-cycle for dual-listed entities; `if not lights: return`
  guards evaluate on the union at T1 and (via `off_set`) T2; no None-vs-[]
  hazards; no double-emit when the same entity appears in both lists.
- **Review B — parity + sleep/entry interaction + no-flap.** Canonical exit
  and reconciler vacant branch clear IDENTICAL sets after D1+D2 (parity
  invariant). Sleep branch is byte-identical (invariant #3). D4's re-ordering
  in `_control_lights_entry` does NOT alter any non-sleep or non-night code
  path (snapshot). No new turn_off emissions during sleep. Restart:
  RestoreEntity + reconcile-on-return still converges the widened set on
  device recovery; no flap between canonical exit turning off and reconciler
  re-asserting ON.
- **Review C — per-site mutation test authority + independent enumeration.**
  For each of T1, T2, T3, D4: reviewer edits production source to neuter that
  single site (bypass the union, revert the ordering) and confirms a
  SPECIFIC named test fails; restores. Reviewer independently re-greps
  turn_off emission sites gated by `CONF_LIGHTS`/`CONF_NIGHT_LIGHTS` to
  confirm this plan enumerates them all (no 5th site hiding). Reviewer
  independently re-verifies the 5 bug rooms from live `.storage/core.config_entries`.

**Plan review (one adversarial pass, per CLAUDE.md Tier-2 plan-review rule)
BEFORE build dispatch:** verifies (a) emission-site enumeration re-run with
independent grep; (b) invariant is falsifiable as stated; (c) D4 decision is
consciously in scope OR carded out; (d) acceptance criteria discriminate the
fix from plausible different failures.

**Live validation (Review D):** after deploy + restart, write observed
results back into `README_v<version>.md` per CLAUDE.md "Record Live Validation
Back Into the README" mandate. Table: one row per acceptance-criteria "Live:"
bullet, PASS/FAIL with the concrete evidence (entity_id, state, timestamp,
log line, DB row).

---

## Risk register (short)

- **R1: silent dedup regression on dual-listed rooms** — mitigated by explicit
  order-preserving dedup + Review A snapshot + invariant #4 test.
- **R2: reconciler asserts OFF on a night-only entity during a race with a
  legitimate canonical ON** — reconciler runs reconcile-on-return only, and
  only when occupancy is vacant; canonical ON runs on entry (occupied). The
  two cannot both fire on the same edge. Verified by re-reading edge handler
  gate (:441-447 per audit). Review B re-verifies.
- **R3: D4 re-ordering breaks a normal-entry code path** — mitigated by
  Review A snapshot across dual-listed / Kitchen / Patio / Study B
  configurations and by the "byte-identical for non-sleep or non-night-only"
  invariant.
- **R4: 5-room live blast-radius mis-scoped** — builder re-runs the
  live-config query before building and stops if it drifts from the audit's
  5. Reviewer C re-verifies independently.

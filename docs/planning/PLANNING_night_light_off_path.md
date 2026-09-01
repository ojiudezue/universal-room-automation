# PLANNING — NIGHT-LIGHT-NO-OFF-PATH-1 (Rev 3: night lights behave like any occupancy light)

**Rev 3 (2026-09-01) — OPERATOR CORRECTION, supersedes Rev 2's sleep-gate premise.**
Rev 2 kept night lights ON through sleep and sleep-GATED the vacancy-off paths
(off_set collapsed to `CONF_LIGHTS` under sleep). The operator's binding correction
(2026-09-01) inverts that premise:

> *"Night lights must behave like ANY normal occupancy light — ON when the room is
> occupied AND dark (existing turn_on_if_dark / sleep-dim entry), and OFF when
> occupancy clears, ALWAYS — including during sleep. Just like all lights would if
> they're turned on."*

Consequences for the plan:

- The vacancy-off set is now the **UNCONDITIONAL** union
  `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS` at every emission site (D1/D2/D3/D5). The
  sleep gate is REMOVED — it was the whole load-bearing premise of Rev 2 and it
  is now WRONG.
- The reconciler SLEEP branch (`_resolve_light` :746-767) becomes
  **occupancy-aware**: during sleep, a night-light is asserted ON at sleep
  brightness ONLY when the room is occupied; when vacant during sleep, the
  branch returns OFF (or falls through so the vacant branch clears it). This
  resolves the sleep-branch-vs-vacant-branch flap that motivated Rev 2's sleep
  gate — no gate is needed because both sides now agree on OFF-when-vacant.
- **D4 is DROPPED** entirely. Rev 2's hoisted sleep block forced night lights ON
  during sleep for entry=none rooms (Master Bedroom / Patio / Game Room); the
  operator does NOT want that. F2/F3 entry=none behavior is left as-is. If the
  canonical↔reconciler entry=none+sleep divergence is still worth resolving on
  its own terms, that is carded separately as `LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1`
  and NOT bundled into this cycle.
- D1 (canonical entry) is UNTOUCHED: `_turn_on_night_lights` on the existing
  `turn_on_if_dark`/sleep-dim entry path stays as it is. The ON side is already
  correct per the operator's description.
- Rev 2 review findings C1/C2/A1/B-HIGH-1/B-MED-1 are all voided — they were
  correct GIVEN Rev 2's premise (night lights stay on through sleep), and the
  premise itself is what changed.

This Rev 3 therefore delivers the SIMPLER change Rev 1 tried and Rev 2 walked
back: unconditional union on the vacancy-off path in all four emission sites,
plus the reconciler sleep branch made occupancy-aware, plus the D6 consumer
widen. No hoisted entry block, no sleep gate on the vacancy-off set.

**Card:** NIGHT-LIGHT-NO-OFF-PATH-1
**Tier:** 2-DB (elevated — shared primitive `actuator_reconciler._resolve_light`,
canonical↔reconciler parity invariant across FOUR emission sites, turn-OFF
behavior changes across 5 live rooms; regression-prone per standing policy).
**Source of truth:** `docs/planning/AUDIT_room_light_automation.md` + operator
correction 2026-09-01.
**Operator decision:** night lights are treated as normal occupancy lights on
the exit path; ON while occupied+dark (or sleep-brightness while occupied+sleep),
OFF on every vacancy regardless of sleep.

---

## Institutional context verified

### Greps run (2026-09-01, re-verified for Rev 3)

- `CONF_NIGHT_LIGHTS` / `CONF_LIGHTS` co-occurrence — 7 files:
  `coordinator.py`, `const.py`, `config_flow.py`, `domain_coordinators/hvac.py`,
  `automation.py`, `actuator_reconciler.py`, `binary_sensor_control_attrs.py`.
- **Turn-off emission sites gated by `CONF_LIGHTS` (the enumeration Rev 3 must
  widen — re-greped independently):**
  - `automation.py::_control_lights_exit` (:1034) — canonical exit off path.
  - `automation.py::_shared_space_turn_off_all` (:3315) — shared-space
    consolidated off.
  - `actuator_reconciler.py::_resolve_light` vacant branch (:794-804) —
    reconcile-on-return OFF assertion.
  - `domain_coordinators/hvac.py::_execute_vacancy_sweep` (:3296) — HVAC
    ZONE-vacancy sweep iterates `CONF_LIGHTS` and emits `turn_off`.
  - **Completeness (Review C axis — no 5th).** Grep of the whole
    `custom_components/universal_room_automation/` tree for `turn_off` calls or
    OFF-assertions gated on `CONF_LIGHTS` returns only the four above, plus
    `_turn_off_non_night_lights` (:1201, called only from the existing
    sleep-entry path :995 — by-design excludes night lights and is UNCHANGED
    by this cycle, i.e. `_turn_off_non_night_lights` continues to enforce the
    "regular-only" semantics its name promises). Reviewer C must independently
    re-run this grep and confirm no 5th emitter.
- Consumer/companion sites reading `CONF_LIGHTS` for exit-time DECISIONS
  (not emitters, but branch on the same set — must be widened for consistency):
  - `coordinator.py::_get_builtin_target_entities(TRIGGER_EXIT)` (:1141-1145) —
    AI-rule vs built-in conflict detector; enumerates entities URA's built-in
    exit automation is expected to target.
  - `automation.py::check_auto_off_warning` (:3197) + `_warning_flash`
    (:3255) — shared-space auto-off T-5 warning + flash cycle.
- Reconciler sleep branch: `actuator_reconciler.py:746-767`. Today the branch
  asserts night_light ON whenever `sleep and entity_id in night_lights`
  regardless of occupancy — this is the behavior the operator does NOT want.
  Rev 3 makes it occupancy-aware (see D2b).
- Reconciler `_LIGHT_KEYS = (CONF_LIGHTS, CONF_NIGHT_LIGHTS)` (:107); night-only
  entities are ALREADY watched — only the assertion gates in the vacant branch
  and the sleep branch are wrong.

### Proposed additions vs prior art

- **NO new CONF_*, sensor, helper, constant, signal, or config-flow field.** All
  touches are set-widening (`CONF_LIGHTS` → `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`,
  unconditional) within existing functions, plus one occupancy check added to
  the reconciler sleep branch (`if occupied:` around the existing
  `sleep_night_light` return). No knob added — see A2 for the one open decision
  (`_warning_flash` behavior on switch-domain night-only entities).
- **REUSED:** `CONF_NIGHT_LIGHTS`, `CONF_LIGHTS`, `CONF_EXIT_LIGHT_ACTION`,
  `LIGHT_ACTION_TURN_OFF`, `STATE_OCCUPIED`, existing domain-split idiom
  (`light.*` vs `switch.*`), existing dedup patterns.

### Prior docs / memory consulted

- `docs/planning/AUDIT_room_light_automation.md` — canonical audit; D1 (fix
  scope), D2 (5 bug rooms + 15 dual-listed + ~20 unaffected), F2/F3
  (canonical↔reconciler entry=none+sleep divergence — now DEFERRED to a
  separate card, not this cycle).
- CLAUDE.md — Tier 2-DB standing policy, Marginal-Benefit pushback (Rev 3
  aligns: the simpler unconditional-union design captures the whole benefit
  once the operator's real intent is on the table; Rev 2's sleep gate was
  ingredient risk in service of a premise the operator did not hold),
  Producer/Consumer rule (both check DIRECTIONS — the reconciler sleep branch
  is a PRODUCER of a competing ON-desire that Rev 2 tried to reconcile via a
  gate; Rev 3 fixes the producer instead), FAN-MANUAL-1 (why the HVAC zone
  sweep must be enumerated as a 4th emission site).
- QUALITY_CONTEXT.md bug classes: Bug Class #4 (mixed-domain turn_off — the
  existing `light.*`/`switch.*` split MUST be preserved on the widened set),
  D2.10 (canonical↔reconciler parity — Rev 3 preserves parity because both
  sides now clear the SAME unconditional union under vacancy, and both sides
  agree OFF-when-vacant under sleep).
- Memory: "coincidental equality masks a concept split" — Rev 2 treated
  vacancy-off and sleep-safety as a coupled concept; the operator correction
  factors them apart (vacancy is vacancy; sleep-brightness is an ON-side
  concern for the OCCUPIED case only).
- No relevant `docs/Coordinator/*.md` — per-room automation code, not a
  domain-coordinator primitive. Identity/camera manual N/A.

### Code locations read end-to-end

- `automation.py` :942-1088 (`_control_lights_entry` + `_control_lights_exit`),
  :1133-1234 (`_turn_on_night_lights`, `_turn_off_non_night_lights`),
  :3197-3315 (`check_auto_off_warning`, `_warning_flash`,
  `_shared_space_turn_off_all`).
- `actuator_reconciler.py` :735-804 (`_resolve_light` full body — sleep branch
  :746-767, occupied branch :772-792, vacant branch :794-804).
- `hvac.py` :3272-3355 (`_execute_vacancy_sweep`, per-room lights loop and
  fan-manual-hold guard).
- `coordinator.py` :1129-1147 (`_get_builtin_target_entities`).

### Live-config verification (5 bug rooms — from audit D2, re-verify at build)

Master Bathroom, Study B, Kitchen, Garage Hallway, Master Bedroom. All 5 have
`exit_action = turn_off` — D1 fixes all 5 on the exit path. Master Bedroom is
also a reconciler-recovery beneficiary of D2. None are shared-space today, so
D3 is consistency-only. Builder MUST re-run the `.storage/core.config_entries`
grep before building and attach the observed list to the build brief; if the
room set differs, stop and resurface.

---

## Falsifiable invariant

For every tracked light entity E and every reachable
`(occupancy, sleep, entry_action, exit_action, dark)` tuple:

1. **Unconditional vacancy OFF (the primary invariant Rev 3 introduces).** If
   `E ∈ (CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS)`, the room is vacant, and
   `exit_action == LIGHT_ACTION_TURN_OFF`, then EVERY vacancy-off emission
   site (`_control_lights_exit`, `_resolve_light` vacant branch,
   `_shared_space_turn_off_all`, `_execute_vacancy_sweep`) asserts OFF on E —
   INCLUDING under `is_sleep_mode_active() == True`. Today only
   `E ∈ CONF_LIGHTS` is asserted OFF at any of these sites; night-only entities
   are silently omitted.
2. **Occupancy-gated sleep ON (the reconciler sleep branch is now
   occupancy-aware).** For `E ∈ CONF_NIGHT_LIGHTS` under
   `is_sleep_mode_active() == True`: the reconciler sleep branch returns the
   `sleep_night_light` ON DesiredState ONLY when `occupied == True`. When
   `occupied == False` under sleep, the branch does NOT re-assert ON; the
   entity falls to the vacant-branch OFF (invariant #1). This closes the flap
   hazard that Rev 2's sleep gate existed to prevent, WITHOUT keeping the
   night light on through sleep.
3. **Canonical↔reconciler parity preserved (vacant side).** The canonical
   `_control_lights_exit` and `_resolve_light` vacant branch clear
   IDENTICAL sets under every reachable input tuple. Since both use the
   same unconditional union, parity is byte-identical on the OFF path.
4. **Entry (ON) path unchanged.** `_control_lights_entry`,
   `_turn_on_night_lights`, `_turn_on_regular_lights`, and
   `_turn_off_non_night_lights` bodies are byte-identical to pre-cycle. The
   existing turn_on_if_dark / sleep-dim entry behavior for night lights is
   preserved (this is the "ON when occupied AND dark" leg the operator
   explicitly keeps).
5. **Dual-listed rooms unchanged emission shape.** For any E already ∈
   `CONF_LIGHTS` (dual-listed or regular-only), the emitted `turn_off` service
   call (domain, transition, entity_id list membership, single emission per
   cycle) is byte-identical to pre-cycle. No double emit from the union.
6. **~20 no-night-light rooms unchanged.** For any room with empty
   `CONF_NIGHT_LIGHTS`, the widened `off_set = CONF_LIGHTS ∪ [] = CONF_LIGHTS`,
   so every emission is byte-identical to pre-cycle.

**Discriminating observations** (each rules out a different failure mode; each
distinguishes the fix from a plausible different failure per operator rule):

- **Non-sleep vacancy on a night-only entity:** ON → vacancy → OFF within one
  exit cycle. Distinguishes fix from pre-cycle behavior (silent no-op) and from
  a "widened but still gated" partial fix. (invariant #1, non-sleep leg)
- **SLEEP + vacancy on a night-only entity (the DISCRIMINATING criterion for
  Rev 3):** sleep active + room vacant → the night-only entity receives EXACTLY
  ONE `turn_off` service call across the cycle (from whichever emission site
  fires first — canonical exit on the vacancy edge, or the reconciler vacant
  branch on reconcile-on-return), and the reconciler sleep branch does NOT
  re-assert ON in the same or subsequent tick. Distinguishes Rev 3's fix from
  Rev 2's sleep-gated design (which would have emitted ZERO turn_offs here and
  kept the night light on) AND from a broken variant that flaps (canonical OFF
  followed by reconciler ON followed by canonical OFF...). Falsifiable
  observation: night-light entity state in `states` table transitions to `off`
  once and STAYS off for the duration of vacancy under sleep.
- **SLEEP + occupied on a night-only entity:** sleep active + room occupied →
  reconciler sleep branch returns `sleep_night_light` ON (unchanged from
  pre-cycle for the occupied case). Distinguishes "occupancy-aware" from
  "occupancy-blind OFF-during-sleep" (which would break the ON leg the operator
  wants to keep).
- **Dual-listed night entity, non-sleep vacancy:** `turn_off` service call fires
  exactly once per cycle (not twice — no dedup regression from union). (invariant #5)
- **No-night-light room, any tuple:** service call set byte-identical to
  pre-cycle (snapshot comparison against a hand-authored pre-change baseline).
  (invariant #6)

---

## Deliverables

### D1 — Widen canonical exit turn-off set to the UNCONDITIONAL union

**File:** `custom_components/universal_room_automation/automation.py`
**Function:** `_control_lights_exit` (line 1034)
**Change:** At :1040, compute the unconditional union:
```
regular = self.config.get(CONF_LIGHTS, []) or []
night   = self.config.get(CONF_NIGHT_LIGHTS, []) or []
off_set = list(regular) + [e for e in night if e not in regular]  # order-preserving dedup
```
Substitute `off_set` for `lights` through the existing `light.*` / `switch.*`
domain-split (:1044-1077) unchanged. The `if not off_set: return` guard
(:1041-1042, evaluated on `off_set`) preserves the empty-config no-op.

**No sleep gate** (this is the Rev 3 correction). The exit path is reachable
during sleep via sleep-bypass (`can_bypass_sleep_mode` at :886 fires when
`motion_count >= CONF_SLEEP_BYPASS_MOTION`, then vacancy). Under Rev 3 that
reachable path SHOULD turn the night light off — that is the whole point of
the operator's correction. No gate is added.

Bug Class #4 preserved: the widened set still passes through the same
domain-split so `light.*` and `switch.*` entries are batched separately.

### Acceptance Criteria

- **Verify (unit — non-sleep, night-only OFF):** `_control_lights_exit` under a
  config with `lights=[]`, `night_lights=[switch.foo]`, `exit_action=turn_off`,
  `is_sleep_mode_active()==False` calls `switch.turn_off` on `switch.foo`.
  Today it returns early at :1041.
- **Verify (unit — sleep, night-only OFF — DISCRIMINATING for Rev 3):** Same
  config, `is_sleep_mode_active()==True`, vacancy driven via post-bypass path
  → `switch.turn_off` called on `switch.foo` exactly once. Distinguishes Rev 3
  from Rev 2's sleep-gated design (Rev 2 would emit ZERO here).
- **Verify (unit — dedup):** `lights=[light.a]`, `night_lights=[light.b, light.a]`
  → exactly one `turn_off` per entity (no double emit on `light.a`); order
  preserved (`light.a` before `light.b`).
- **Verify (unit — no-night-light room byte-identical):** `lights=[light.a]`,
  `night_lights=[]` → emitted service_data byte-identical to pre-cycle
  (snapshot vs hand-authored baseline).
- **Test-authority anchor (mutation drill, hollow-anchor guard):** Neuter the
  union by reverting :1040 to `self.config.get(CONF_LIGHTS, [])`; both the
  non-sleep AND sleep night-only tests MUST turn RED with named behavioral
  assertions on `hass.services.async_call('switch','turn_off', {...})`.
  Restore after each drill. Anchors are behavioral (service-call assertions),
  NOT source greps.
- **Live:** Master Bathroom under-cabinet `switch.sonoff_1002197ef7_1` turns
  OFF within one exit cycle after room goes vacant, in BOTH sleep hours and
  non-sleep hours. Confirmed via `ssh ha` state history + URA
  `set_last_action` payload showing the entity id in the turn_off action.
  **Sleep-hours leg is the load-bearing operator-facing observation** —
  distinguishes fix from Rev 2's design.

---

### D2 — Reconciler: (a) widen vacant branch to union; (b) make sleep branch occupancy-aware

**File:** `custom_components/universal_room_automation/actuator_reconciler.py`

**D2a — Vacant branch union (`_resolve_light` :794-804):**
```
regular = cfg.get(CONF_LIGHTS) or []
night   = cfg.get(CONF_NIGHT_LIGHTS) or []
off_set = list(regular) + [e for e in night if e not in regular]
if exit_action == LIGHT_ACTION_TURN_OFF and entity_id in off_set:
    return DesiredState(state="off", domain=domain, service="turn_off",
                        reason="exit_light_off")
```
Rewrite the A-HIGH-1 comment (:794-797) to reflect the NEW canonical behavior:
`_control_lights_exit` now clears `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`
unconditionally when `exit_action == TURN_OFF`; this branch mirrors that set.
Cite this planning doc + the audit + operator correction 2026-09-01.

**D2b — Sleep branch becomes occupancy-aware (`_resolve_light` :746-767):**
Today the sleep branch asserts `sleep_night_light` ON whenever
`sleep and entity_id in night_lights`, regardless of occupancy — this is why
Rev 2 needed a sleep gate on the canonical OFF path (to avoid a flap). Rev 3
fixes the producer instead: gate the ON-assertion on occupancy so
sleep+vacant+night-only falls through to the vacant branch below (where D2a's
union will now assert OFF).

Concretely, add `occupied = bool(data.get(STATE_OCCUPIED))` (already computed
at :740; reuse) and change the sleep branch to:
```
if sleep and night_lights:
    if entity_id in night_lights:
        if occupied:
            # existing sleep_night_light ON return (params + brightness_pct
            # + DesiredState) — BYTE-IDENTICAL to pre-cycle for this cell
            return DesiredState(state="on", domain=domain, service="turn_on",
                                params=params, reason="sleep_night_light",
                                has_params_to_apply=bool(params))
        # sleep + night_light + VACANT: fall through to the vacant branch
        # so D2a's unconditional union asserts OFF. Do NOT return here.
    else:
        # sleep + not a night light -> off (unchanged, pre-cycle behavior).
        return DesiredState(state="off", domain=domain, service="turn_off",
                            reason="sleep_non_night_off")
```
Note the structural change: the existing `sleep + not a night light -> off`
return moves into the `else` arm (unchanged behavior). The `sleep + night +
vacant` case now falls through instead of returning ON.

**Rationale:** Parity is the invariant; the operator-correct behavior is that
night lights OFF on vacancy always. Rev 2 tried to preserve parity by adding a
sleep gate on the OFF-emitters — that kept night lights ON through sleep,
which is what the operator rejects. Rev 3 preserves parity by fixing the
reconciler sleep branch so both sides agree on OFF-when-vacant. The sleep
branch STILL asserts ON when occupied — the operator explicitly keeps that
(existing `_turn_on_night_lights(mode="sleep")` behavior at automation.py:994).

**No flap risk:** on the vacancy edge under sleep, canonical exit emits OFF
(D1) and the reconciler vacant branch would emit OFF (D2a); both agree. On
the subsequent reconcile tick the sleep branch's `if occupied:` gate is FALSE
(the room is vacant), so no competing ON-desire is produced. Under
sleep-post-bypass RE-occupancy, the sleep branch's ON-assertion fires
(occupied=True) and canonical entry's `_turn_on_night_lights(mode="sleep")`
also fires — they agree ON, no flap.

### Acceptance Criteria

- **Verify (unit — D2a, non-sleep night-only OFF):**
  `_resolve_light("switch.foo", data={STATE_OCCUPIED: False})` with
  `lights=[]`, `night_lights=[switch.foo]`, `exit_action=turn_off`, sleep=False
  returns `DesiredState(state="off", reason="exit_light_off")`. Today returns None.
- **Verify (unit — D2b, sleep + occupied byte-identical):** Same entity,
  `data={STATE_OCCUPIED: True}`, sleep=True → returns the `sleep_night_light`
  ON DesiredState with brightness params IDENTICAL to pre-cycle output.
  Snapshot vs hand-authored baseline. This is the "keep the ON leg" assertion.
- **Verify (unit — D2b, sleep + VACANT + night-only — DISCRIMINATING for Rev 3):**
  `data={STATE_OCCUPIED: False}`, sleep=True, `lights=[]`,
  `night_lights=[switch.foo]`, `exit_action=turn_off` → returns
  `DesiredState(state="off", reason="exit_light_off")` (falls through sleep
  branch to D2a's vacant branch). Rev 2 would have returned
  `sleep_night_light` ON here — this test discriminates Rev 3 from Rev 2.
- **Verify (unit — sleep + vacant + regular unchanged):** `data={STATE_OCCUPIED:
  False}`, sleep=True, `light.a ∈ CONF_LIGHTS`, `light.a ∉ CONF_NIGHT_LIGHTS`
  → returns `sleep_non_night_off` (unchanged behavior via the new `else`
  arm). Snapshot vs pre-cycle.
- **Verify (unit — occupied+non-sleep entry byte-identical):** Occupied
  branch (:772-792) untouched; returns identical DesiredState for every
  capability/dark/action tuple. Snapshot vs hand-authored baseline.
- **Test-authority anchor (three drills):**
  (a) revert D2a union → sleep+vacant+night-only test AND non-sleep+vacant+
  night-only test both turn RED.
  (b) revert D2b's occupancy gate (i.e. return `sleep_night_light` ON
  regardless of occupancy) → sleep+VACANT+night-only test turns RED asserting
  a specific competing ON-DesiredState was returned.
  (c) drop D2b's fall-through (add `return None` after the sleep branch)
  → sleep+vacant+night-only test turns RED (no OFF-DesiredState returned).
  Restore after each. All anchors are behavioral assertions on the returned
  DesiredState object, not source greps.
- **Live:** Post-restart, `_resolve_light` DEBUG log for the Master Bath
  night-only Sonoff:
  - room vacant + sleep=True: shows `reason="exit_light_off"` (not
    `sleep_night_light`).
  - room occupied + sleep=True: shows `reason="sleep_night_light"`.
  - room vacant + sleep=False: shows `reason="exit_light_off"`.

---

### D3 — Widen `_shared_space_turn_off_all` + companions

**File:** `custom_components/universal_room_automation/automation.py`

**D3a — turn-off emitter (`_shared_space_turn_off_all`, :3315):** at :3318,
build the SAME unconditional union `off_set` as D1 and use it in place of
`self.config.get(CONF_LIGHTS, [])`. Existing domain-split (:3320-3333)
unchanged.

**D3b — companions (`check_auto_off_warning` :3197 + `_warning_flash` :3255):**
both read `CONF_LIGHTS` to compute `lights_on` and to build the flash target
set. Widen both to the SAME unconditional union `off_set` so:
- `check_auto_off_warning`'s "any light on?" gate includes night-only entities.
- `_warning_flash`'s target list includes night-only entities.

**A2 (open decision — Rev 3 must resolve, per operator prompt).**
`_warning_flash` (:3255) currently turns lights ON at full brightness for the
warning cycle. On a switch-domain night-only entity this manifests as an
OFF→ON→OFF cycle at whatever the switch is (usually mains). Two options:

- **Option A2-gate:** exclude switch-domain night-only entities from the flash
  target set (they are still counted in the warning `lights_on` check, still
  turned OFF at the end, but not cycled ON as part of the flash). Rationale:
  the flash's intent is a visual "you're about to lose lights" nudge; a
  night-only mains-switch light being flashed ON at full brightness is
  potentially jarring in a shared space at low-light hours.
- **Option A2-accept:** flash all widened targets including switch-domain
  night-only entities. Transient (few seconds); document in the README.

**Rev 3 decision:** Option **A2-gate**. Rationale: the union principle applies
to the OFF path (the operator's correction); the flash is a UX-side effect
whose "flash a switch at full brightness" behavior is a documented weakness
even for regular switch-domain lights and should not be extended to night-only
entities without operator input. Gate is one line
(`if e in regular_lights: include in flash_set`); the target set differs from
the OFF set by exactly the switch-domain night-only entities. Zero live blast
today (no shared-space room is a bug room). If operator prefers A2-accept,
that is a one-line revert in the Rev-3 build brief before dispatch.

### Acceptance Criteria

- **Verify (unit — D3a):** `_shared_space_turn_off_all` with `lights=[]`,
  `night_lights=[switch.foo]`, non-sleep → emits `switch.turn_off` on
  `switch.foo`. Sleep → also emits `switch.turn_off` (unconditional per Rev 3).
- **Verify (unit — D3b warning `lights_on`):** shared space, `lights=[]`,
  `night_lights=[light.b]` currently ON → warning gate fires (was silently
  missing pre-cycle).
- **Verify (unit — D3b A2-gate flash target):** `lights=[]`,
  `night_lights=[switch.night, light.night_dim]` currently ON, in the T-5
  window → `_warning_flash` target list INCLUDES `light.night_dim` (light
  domain, safe to flash) and EXCLUDES `switch.night` (switch-domain night-only
  entity — A2-gate). Both entities are still turned OFF at auto-off time
  (D3a).
- **Test-authority anchor:** four drills — revert D3a union, revert D3b
  warning widen, revert D3b flash widen, revert A2-gate (include switch-domain
  night-only in flash target) — each specific test turns RED. Restore.
- **Live:** No live check required today (no shared-space bug room). Note in
  the README that D3 is consistency-only; document A2-gate rationale.

---

### D4 — DROPPED (Rev 3)

Rev 2's D4 hoisted the sleep block in `_control_lights_entry` above the
`action == NONE` and empty-lights guards so that entry=none rooms would turn
their night lights ON during sleep. The operator's correction rejects the
premise (night lights should behave like normal occupancy lights; F2/F3
entry=none behavior is left as-is). D4 is DROPPED entirely in Rev 3.

The canonical↔reconciler entry=none+sleep divergence (Master Bedroom / Patio
/ Game Room) is NOT resolved by this cycle. If it is still worth resolving on
its own terms, it is carded separately as `LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1`;
that card explicitly does NOT force night lights ON on entry=none rooms.
Under Rev 3's changes, D2b's occupancy-aware sleep branch means the
reconciler no longer forces night_light ON during sleep-vacancy for those
rooms either — the divergence surface is narrower after Rev 3 than before,
which may make the separate card lower-priority or moot.

**Non-goal:** this cycle does NOT touch `_control_lights_entry`,
`_turn_on_night_lights`, `_turn_off_non_night_lights`, or their call sites.
The existing turn_on_if_dark / sleep-dim entry path for night lights is
preserved BYTE-IDENTICAL — this is the "ON when occupied AND dark" leg the
operator explicitly keeps.

---

### D5 — HVAC zone-vacancy sweep: unconditional union

**File:** `custom_components/universal_room_automation/domain_coordinators/hvac.py`
**Function:** `_execute_vacancy_sweep` (:3272), lights loop at :3296-3310.

**Change:** apply the identical unconditional-union `off_set` construction to
the per-room lights loop at :3296. Under Rev 3, the sweep turns off both
regular and night-only entities on zone vacancy, regardless of sleep — this
matches the operator's correction (a zone-vacancy sweep at 02:00 SHOULD turn
off a hallway night-only light if that hallway's room is vacant, because
that is exactly the "OFF on vacancy always" invariant).

Domain-split (`domain = entity_id.split(".")[0]`) applies to the widened set.
The existing observation-mode guard (:3281) and the fan-manual-hold guard
(:3319, lights-independent) are unchanged.

**Rev 2 objected on grounds that a 02:00 sweep would kill hallway night
lights — that objection is voided by the operator's correction. Under Rev 3,
"kill hallway night lights on zone vacancy at 02:00" is the DESIRED behavior.**

### Acceptance Criteria

- **Verify (unit — non-sleep sweep):** `_execute_vacancy_sweep` on a zone
  containing a room with `lights=[]`, `night_lights=[switch.hall_night]`,
  non-sleep → `switch.turn_off` called on `switch.hall_night`.
- **Verify (unit — sleep sweep — DISCRIMINATING for Rev 3):** Same room,
  sleep active → `switch.turn_off` called on `switch.hall_night` (Rev 2 would
  have emitted zero calls). Distinguishes Rev 3 from Rev 2.
- **Verify (unit — observation-mode + fan-manual-hold guards unchanged):**
  observation-mode return at :3281 and fan-manual-hold behavior unchanged;
  the lights widen is orthogonal.
- **Test-authority anchor:** revert D5 union → both non-sleep AND sleep
  sweep tests turn RED. Restore.
- **Live:** on the next zone-level vacancy sweep involving a night-only
  entity (Master Bedroom is such a room in a zone), state history shows the
  entity going OFF via the HVAC sweep path (grep `HVAC: Vacancy sweep` DEBUG
  line for the entity id) — in both sleep and non-sleep hours.

---

### D6 — Widen exit-target consumer (coordinator.py:1141-1145)

**File:** `custom_components/universal_room_automation/coordinator.py`
**Function:** `_get_builtin_target_entities(TRIGGER_EXIT)` (:1129, exit branch
at :1141-1145).

**Change:** widen the exit branch's `CONF_LIGHTS` read to the SAME unconditional
union used by D1's exit path. This is a CONSUMER (invariant-side), not a
turn-off emitter — it enumerates what URA's built-in exit automation will
target so the AI-rule vs built-in conflict detector can flag contested
entities. If D1 widens without D6, an AI rule targeting a night-only entity
on exit would silently escape conflict detection.

Enter/lux_dark branch (:1136-1140) is UNCHANGED — this cycle does not alter
entry-side targets (D4 is dropped). Enumerated as an explicit non-change.

### Acceptance Criteria

- **Verify (unit):** `_get_builtin_target_entities(TRIGGER_EXIT)` on a config
  with `lights=[light.a]`, `night_lights=[light.b, light.a]` returns
  `[light.a, light.b]` (dedup applied), plus fans/auto_devices/auto_switches
  unchanged.
- **Verify (unit — non-change):** `_get_builtin_target_entities(TRIGGER_ENTER)`
  under the same config returns the pre-cycle set (still `CONF_LIGHTS`-only
  for lights).
- **Test-authority anchor:** revert D6 to `CONF_LIGHTS`-only on exit; the
  AI-rule-conflict test for a night-only entity targeting turns RED. Restore.
- **Live:** No live check required (conflict-detection is a static analysis
  surface).

---

## Non-goals (explicit)

- **NO change to `_control_lights_entry`**, `_turn_on_night_lights`,
  `_turn_on_regular_lights`, or `_turn_off_non_night_lights` bodies. The ON
  path for night lights (entry, sleep-dim entry, dark-gated entry) is
  BYTE-IDENTICAL to pre-cycle.
- **NO sleep gate on any vacancy-off emission site.** Rev 2's sleep gate is
  explicitly REMOVED.
- **NO forced night-light ON during sleep for entry=none rooms.** Rev 2's D4
  is DROPPED. F2/F3 entry=none behavior is left as-is; if resolved separately,
  it goes on card `LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1`.
- **NO change to the reconciler occupied branch (:772-792).**
- **NO change to `_get_builtin_target_entities(TRIGGER_ENTER)`** — D6 is
  exit-only.
- **NO Option B (stay-on-till-wake), NO Option C (hybrid).**
- **NO new CONF_*, sensor, number/select/switch entity, signal, or knob.**
- **NO change to F4 (Kitchen range as night light — config sanity), F5 (sleep
  overrides leave_on — separate investigation), F7 (switch-domain night light
  silent no-op on brightness/color — informational).**
- **NO changes to entity registration, config-flow, or options-flow surfaces.**
- **A2 decision:** switch-domain night-only entities are EXCLUDED from
  `_warning_flash`'s ON-cycle target set (still turned OFF by D3a). If
  operator prefers to flash them too, revert A2 in the build brief.

---

## Tier 2-DB review plan (three framing-disjoint reviews)

Framings chosen so blind spots cannot converge (per CLAUDE.md standing policy).

- **Review A — local correctness + set arithmetic + occupancy-aware sleep
  branch.** Union construction is order-preserving and dedup-correct across
  D1/D2a/D3/D5; domain split (`light.*` vs `switch.*`) applies to the widened
  set at D1/D3a/D3b/D5; transition/service params for turn_off are identical
  to pre-cycle for dual-listed entities; `if not off_set: return` guards
  evaluate on the widened set; no None-vs-[] hazards; no double-emit when the
  same entity appears in both lists. D2b's structural rewrite of the sleep
  branch preserves the `sleep_non_night_off` return byte-identically in the
  `else` arm, adds the `if occupied:` gate cleanly, and the fall-through case
  actually reaches the vacant branch (no early return leaking).
- **Review B — parity + no-flap + supersession + Rev-2-premise scrub.**
  Canonical exit and reconciler vacant branch clear IDENTICAL sets after
  D1+D2a. The reconciler sleep branch and canonical exit AGREE on the
  sleep+vacant+night-only case (both → OFF) — no flap possible.
  Reconciler sleep+occupied+night-only case matches canonical entry
  (`_turn_on_night_lights(mode="sleep")`) — both → ON at sleep brightness. On
  restart, RestoreEntity + reconcile-on-return converges the widened set on
  device recovery. No stale Rev-2 sleep-gate residue anywhere (grep for
  `is_sleep_mode_active` inside the affected functions post-cycle; only pre-
  existing uses should remain — no new gate in D1/D2a/D3/D5). SUPERSESSION
  scan (per CLAUDE.md post-ship rule, but run pre-ship as a Review-B pass):
  the A-HIGH-1 comment at :794-797 is superseded → rewrite (D2a); no other
  KEEP+WIRE or KEEP+DOCUMENT items expected; enumerate any found.
- **Review C — per-site mutation test authority + independent completeness
  enumeration.** For each of D1, D2a, D2b (three sub-drills), D3a, D3b (three
  sub-drills including A2-gate), D5, D6: reviewer edits production source to
  neuter that single site and confirms a SPECIFIC named test fails; restores.
  Every anchor is a behavioral turn_off / DesiredState emission assertion,
  NOT a source grep. Reviewer independently re-greps turn_off emission sites
  gated by `CONF_LIGHTS`/`CONF_NIGHT_LIGHTS` to confirm this plan enumerates
  them all (no 5th emitter — the "four emission sites" claim is a Review-C
  falsifiable). Reviewer independently re-verifies the 5 bug rooms from live
  `.storage/core.config_entries`. Reviewer confirms the NO-night-light room
  set (~20 rooms per audit) is byte-identical pre/post via a snapshot on at
  least three representative configs.

**Plan review (one adversarial pass BEFORE build dispatch, per Tier 2 rule):**
verifies (a) all four emission sites re-greped independently and no 5th
found; (b) invariant #1 (unconditional vacancy OFF) is falsifiable via the
sleep+vacancy DISCRIMINATING criterion at every emission site; (c) D2b's
occupancy-aware sleep branch actually prevents flap under the reachable
sleep-post-bypass-vacancy path (walk the tick sequence); (d) D4 is truly
dropped (no residual entry-path changes hiding in D1/D6); (e) acceptance
criteria discriminate Rev 3's fix from Rev 2's design and from pre-cycle;
(f) A2 decision is defensible or explicitly flagged for operator toggle.

**Live validation (Review D):** after deploy + restart, write observed
results back into `README_v<version>.md` per CLAUDE.md "Record Live
Validation Back Into the README" mandate. Table: one row per acceptance
"Live:" bullet, PASS/FAIL with concrete evidence (entity_id, state,
timestamp, log line, DB row). The SLEEP + vacancy leg on the Master Bath
under-cabinet Sonoff is the load-bearing operator-facing observation and
MUST be validated with a concrete state-history transition.

---

## L1 — Hollow-anchor guard

Applies to every "Test-authority anchor" bullet above. Explicit rules:

1. **Anchors are behavioral, NOT source-grep.** Each anchor asserts the
   OBSERVABLE emission (`hass.services.async_call` service_data, or the
   returned `DesiredState` object for reconciler tests), not the presence of
   a code token.
2. **Acceptance-snapshot baselines** (invariant #4/#5/#6 byte-identical
   assertions, D2b sleep+occupied byte-identical, D2b sleep+non-night unchanged)
   are captured on the **PRE-change tree** (git worktree pinned to the
   pre-cycle commit) OR hand-authored from first principles referencing
   pre-cycle line numbers. They MUST NOT be generated by running the
   post-change code and recording its output as "expected" — that would
   tautologically pass.
3. Each mutation drill's RED assertion names the specific behavior it
   protects (e.g. `assert_turn_off_emitted_for('switch.foo', domain='switch')`,
   not `assert_test_xyz_ran`).
4. Bytecode cache discipline: run drills with `PYTHONDONTWRITEBYTECODE=1` and
   clear `__pycache__` between mutations (per `feedback_mutation_verification_pycache_staleness`).
5. Reviewer C's independent enumeration is the check that this discipline
   held — a hollow anchor is a Review-C blocker.

---

## Risk register (short)

- **R1: silent dedup regression on dual-listed rooms.** Mitigated by explicit
  order-preserving dedup + Review A snapshot + invariant #5 test.
- **R2: reconciler sleep-branch rewrite loses the sleep+non-night-only OFF
  behavior.** D2b restructures the sleep branch — the `sleep_non_night_off`
  return moves into an `else` arm. Mitigated by: (a) the D2b "sleep + vacant
  + regular unchanged" acceptance test asserts snapshot equality against a
  hand-authored pre-cycle baseline; (b) Review A snapshot; (c) mutation
  drill (b) proves the ON gate is load-bearing on the occupied+night case
  without perturbing the regular case.
- **R3: canonical↔reconciler flap on the vacancy edge under sleep.** Walked
  in Review B tick sequence: canonical exit emits OFF (D1), reconciler
  vacant branch would emit OFF (D2a), reconciler sleep branch's `if occupied:`
  is False so no competing ON. No flap.
- **R4: 5-room live blast-radius mis-scoped.** Builder re-runs the
  live-config query before building and stops if it drifts from the audit's
  5. Reviewer C re-verifies independently.
- **R5: HVAC sweep behavior change surprises operator.** The sweep now turns
  off night-only entities on zone vacancy including sleep hours. This IS the
  operator's stated intent, but call it out explicitly in the README's Live
  Validation table so it is not a stealth behavior change.
- **R6: A2 decision (switch-domain night-only excluded from flash) surprises
  a shared-space room in the future.** Mitigated by A2 being one-line
  reversible; document in the README.
- **R7 (Rev 3): 4-site drift.** With D1/D2a/D3/D5 all applying the same
  unconditional union independently, a future edit to one site could drop
  the union silently. Mitigated by Reviewer C's independent re-grep of
  turn_off-on-`CONF_NIGHT_LIGHTS` sites as a standing check; consider a
  `_light_off_set(config)` helper in a future refactor cycle if drift is
  observed (NOT this cycle — Marginal-Benefit pushback: helper adds a
  shared primitive to be reviewed for one-line duplication in four places;
  keep it inline until drift is measured).

---

## Rev 3 changelog (2026-09-01)

Rev 3 supersedes Rev 2. Mapping of operator-correction points to sections
changed:

| Correction | Section(s) |
|---|---|
| Vacancy-off unconditional union, no sleep gate | D1, D2a, D3, D5, invariants #1/#3 |
| Reconciler sleep branch occupancy-aware | D2b, invariant #2, R3 walked |
| Drop D4 hoisted sleep entry block | D4 (dropped), non-goals |
| Keep entry ON path (turn_on_if_dark / sleep-dim) byte-identical | invariant #4, non-goals |
| Preserve light.*/switch.* split, dedup, dual-listed byte-identity | D1/D2a/D3/D5, invariants #5/#6, Review A |
| A2 warning-flash decision (gate switch-domain night-only) | D3b, non-goals, R6 |
| Completeness — no 5th emission site | Institutional context greps, Review C, plan-review checklist |

**Rev 2 findings voided:** C1/C2 (sleep gate CRITICAL — premise reversed),
A1 / B-HIGH-1 / B-MED-1 (all downstream of Rev 2's stays-on-during-sleep
premise). Any Rev 2 review artifact should be re-read with the operator
correction in mind before citing.

**Invariant #1 re-verified under Rev 3:** in every reachable tuple with
`occupancy == False` and `exit_action == LIGHT_ACTION_TURN_OFF`, all four
emission sites evaluate `off_set = CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS` and a
night-only entity IS a member of the emitted turn_off list. Under sleep
this is now the DESIRED behavior. The reconciler sleep branch (D2b) does
not compete because its ON-assertion is gated on `occupied == True`.
Invariant holds.

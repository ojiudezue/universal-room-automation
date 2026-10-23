# PLANNING — Night lights under house Sleep in every room that has them

Card: **NIGHT-LIGHTS-HOUSE-SLEEP-ALL-ROOMS-1** (Tier 2-DB by standing policy: regression-prone change to a light-choice predicate read by three controllers). Status: plan, not reviewed. No version is assigned here.

Operator ask (2026-10-23): "Powder/guest toilet lights all coming on at night... Ezinne also reported full lights in master bath at 1am", then "I like the fix. Do it". The fix: when the HOUSE state is `sleep`, an entry into a room that has `night_lights` turns on only those night lights (sleep slot brightness/colour) and not the main lights, whatever the room's `sleep_protection_enabled` switch says. Covers, fan sleep policy, the bedroom fan hold and the motion-count wake bypass stay on the per-room switch and clock (REV 2.5, operator 2026-09-30). Rooms without night lights behave as today.

Mandatory reading done for this plan: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (§2 house-state inference, §7 house-state transitions, §10 corrections ledger, in particular #11 and #17 on house Sleep) and `docs/architecture/SENSOR_FLEET_CLASSES.md`, read in full. This cycle consumes `house_state == sleep` as an input and changes nothing in how it is produced, how sensors are classed or how occupancy is computed. No ledger claim is re-asserted. Contradictions found between doc and code: none in the surfaces this plan touches.

---

## 0. Institutional context verified

### 0.1 Prior-art scan (code, plans, analysis): REUSE or BUILD for each piece

| Piece | Verdict | Evidence |
|---|---|---|
| Light-choice predicate "is it sleep for lights?" | **REUSED, widened**: `RoomAutomation.is_sleep_lighting_active` at `automation.py:1251-1265` | Already returns `house_state == sleep` OR clock, but only behind `CONF_SLEEP_PROTECTION_ENABLED` (`automation.py:1260`). That one line is the defect. |
| House-state read | **REUSED**: `_read_current_house_state()` (called at `automation.py:1263` and `:1278`) | No new reader. |
| Night-light-only entry branch (scene + per-light + non-night sweep) | **REUSED** unchanged: `automation.py:1470-1482` | Already the operator's wanted behaviour for protection-on rooms. |
| Non-night sweep | **REUSED** unchanged: `_turn_off_non_night_lights` `automation.py:1992-2027`, gated by the manual hold `light_hold_allowed` (`automation.py:790`) | See §5. |
| Reconciler parity | **REUSED** unchanged: `actuator_reconciler.py:807` reads the same predicate, sleep branch `:817-858` (`sleep_night_light`, `sleep_non_night_off`), manual hold honoured at `:672-680` | |
| Entry-set resolver (lights_on_entry / dark-only) | **REUSED** unchanged: `lighting/resolver.py:92-132` `effective_entry_set`; `is_sleep_hours and night` returns night lights only at `:119-121` | |
| Room Lights master switch (manual "turn on") | **REUSED** unchanged: `switch.py:5418` `RoomLightsSwitch.async_turn_on` reads the same predicate | Behaviour change for 10 rooms, see §4 and operator question Q2. |
| Narrow helper `_house_state_is_sleep` (v5.103.42) | **KEEP**, becomes dead for the main-light decision; its two night-light-only call sites (`automation.py:1525`, `actuator_reconciler.py:887-891`) stay as harmless fallbacks | §3, bucket "KEEP + DOCUMENT". |
| Kill switch | **NEW** module constant `NIGHT_LIGHTS_HOUSE_SLEEP_ALL_ROOMS_ENABLED` | `grep -n "HOUSE_SLEEP\|NIGHT_LIGHT.*ENABLED\|SLEEP_LIGHTING" const.py` returned nothing. |
| New CONF_*, entity, sensor, signal, config-flow field | **None** | Not needed. |

Greps run (this session):
```
grep -n "is_sleep_lighting_active\|is_sleep_hours\|_house_state_is_sleep\|can_bypass_sleep_mode\|_turn_off_non_night_lights\|sleep_non_night_off\|lights_on_entry\|night_light\|sleep_protection" automation.py
grep -rn "is_sleep_lighting_active\|_house_state_is_sleep\|can_bypass_sleep_mode\|sleep_non_night_off\|_turn_off_non_night_lights\|is_sleep_hours\|is_sleep_mode_active\|should_execute_automation" custom_components/universal_room_automation/
grep -n "HOUSE_SLEEP\|NIGHT_LIGHT.*ENABLED\|SLEEP_LIGHTING" const.py            -> no hits
grep -rln "is_sleep_lighting_active\|_house_state_is_sleep" quality/tests
```

Prior plans consulted: `PLANNING_room_dialog_cleanup_and_lighting_roles.md` (REV 2.5 rulings, line 1: house Sleep chooses night lights only; manual hold on in every room), `PLANNING_night_light_action_selector.md`, `PLANNING_night_light_off_path.md` (reconciler occupancy-aware sleep branch), `AUDIT_room_light_automation.md` (skim), `PLANNING_house_state_sleep_mask_ble_memory_observability.md` (house-state producer, skim). Memory: `reference_presence_state_of_play`, `reference_sensor_fleet_classes`, `feedback_config_first_before_code`, `feedback_marginal_benefit_pushback`.

### 0.2 Config-first check

Per-room fix exists: set `sleep_protection_enabled=true` (done for Powder on 10-23). That drags in cover blocking, fan sleep policy, the bedroom fan hold and the clock-gated exit/motion behaviour, which the operator does not want in hallways, pantries, the dining room and so on. No knob selects "night lighting only". Code is needed; the change is one predicate line plus a kill switch.

### 0.3 Rooms affected (live `core.config_entries`, 47 rooms)

| Group | Count | Rooms |
|---|---|---|
| Night lights, protection OFF: **behaviour changes** | **10** | Butler Pantry, Dining Room, Kitchen Hallway, Kitchen Hallway Garage, Living Room, Master Closet, Receiving Room, Stair Closet, Staircase, Study B |
| Night lights, protection ON: already behave this way | 12 | Exercise Room, Garage Hallway, Kitchen, Kitchen Pantry, Laundry, Master Bath Toilet, Master Bathroom, Master Bedroom, Patio, Powder (since 10-23), Study A, Ziri Bathroom |
| No night lights: no change | 25 | incl. Oji Vanity, Guest Bedroom 1/2 Bathroom, Media Room Closet, AV Closet |

Living Room and Staircase have `entry_light_action = none`, so for them entry already never lights the mains; the visible change there is only the reconciler and the Room Lights switch (§4). **Oji Vanity has no night lights**, so this card does not fix it; it still lights full at night. Operator question Q3.

---

## 1. Falsifiable invariant

> **I1.** With the kill switch on, for any room R with a non-empty `night_lights`, while `house_state == sleep` (read at decision time), no URA automatic light controller (canonical entry `_control_lights_entry`, the reconciler `_resolve_light`, or a slot scene) turns ON an entity in `CONF_LIGHTS \ CONF_NIGHT_LIGHTS` for R, whatever `sleep_protection_enabled`, `entry_light_action`, `lights_on_entry` / `lights_on_entry_dark_only`, `night_lights_by_day`, illuminance or the motion-bypass count say.
>
> **I2.** Nothing other than light choice changes: for every room, `is_sleep_mode_active()` returns the same value as before for every (config, time, house state), so covers, fans, exit skip, the fan sleep policy, the bedroom fan hold and `can_bypass_sleep_mode` / `should_execute_automation` are unchanged. For rooms with no night lights, every light write is byte-identical.

Example break to test: Dining Room (`night_lights` set, protection off, `turn_on_if_dark`), house `sleep`, lux 0, 03:00 → today mains turn on (I1 broken); after fix only night lights at the sleep slot.

Explicit carve-out: manual action. A person flipping a main light (or the Room Lights switch, see Q2) is not covered by I1.

---

## 2. Producer and consumer checks

### Producer: `is_sleep_lighting_active()` (`automation.py:1251`)
- Today: `clock_sleep OR (protection_on AND house_state == "sleep")`, fail-open to clock on read exception.
- After: `clock_sleep OR (house_state == "sleep" AND (protection_on OR (KILL_SWITCH AND night_lights non-empty)))`.
  - The `night_lights` guard is not needed for correctness, since every consumer already ANDs with night lights (`automation.py:1470`, `actuator_reconciler.py:817`, `resolver.py:119`). It is still required, so that I2's "byte-identical for no-night-light rooms" holds by construction and a future consumer cannot silently widen.
- Dependency health: `house_state` comes from the presence `StateInferenceEngine` (PRESENCE doc §2). SLEEP needs census present plus the sleep window, or an override. Known producer hazards are in the doc (sleep-mask cycle, §2 / ledger #17) and affect *when* the house is in sleep, not this predicate. If the house fails to reach SLEEP, this fix simply does not engage (same as protection-on rooms today). A false SLEEP during the evening would dim 10 more rooms; that is the same blast radius protection-on rooms already accept.

### Consumers (all read the one predicate, so parity holds automatically)

| # | Site | Use | Effect of widening |
|---|---|---|---|
| C1 | `automation.py:1453` → `:1470-1482` entry sleep branch | trust (actuation) | Night-light-only + slot scene `LIGHT_SLOT_SLEEP` (`:1475`) + `_turn_off_non_night_lights` |
| C2 | `actuator_reconciler.py:807` → `:817-858` | trust (actuation) | Occupied night light ON at sleep params; **every non-night light asserted OFF (`sleep_non_night_off`), occupied or not**, subject to the manual hold (`:672-680`) |
| C3 | `actuator_reconciler.py:942` `effective_entry_set(is_sleep_hours=sleep)` | trust | Unreachable when sleep and night lights (C2 returns first); unchanged |
| C4 | `switch.py:5418` `RoomLightsSwitch.async_turn_on` | operator action | Under house sleep the switch turns on **night lights only** in the 10 rooms (Q2) |
| C5 | `automation.py:1525`, `actuator_reconciler.py:887-891` `_house_state_is_sleep` | night-light params | Now unreachable for night-light rooms in house sleep (C1/C2 capture first); kept as fallback |

Not consumers (clock-only, must stay byte-identical; confirmed via grep): `is_sleep_mode_active` at `automation.py:1305, 1344, 2441, 2523, 2567, 2699, 2989, 3112, 3572, 4200`; `actuator_reconciler.py:1061` (fans); `aggregation.py:776` `_is_sleep_hours` (house-level, separate).

---

## 3. Emission and decision sites (Bug Class #53 check)

All light-ON emission paths for a room under house sleep:
1. Canonical entry `_control_lights_entry` (`automation.py:1440`): sleep branch C1. ✔ via predicate.
2. Slot scene `_maybe_activate_slot_scene(LIGHT_SLOT_SLEEP, ...)` `automation.py:1475`: inside C1. ✔. The non-sleep slot scene path (`automation.py:1577` area, `resolve_slot(is_sleep_hours=False)`) is after the sleep return. ✔ unreachable.
3. Reconciler `_resolve_light`: C2. ✔.
4. Sleep-gate path in `handle_occupancy_change` (`automation.py:1368-1403`): clock-gated, night lights only. Unchanged and not reachable for protection-off rooms.
5. `RoomLightsSwitch` C4: manual. Changes (Q2).
6. AI / house-state rules light writes (`test_lighting_slice_d_house_state.py:298-316` cover the hold): not part of entry; out of scope (non-goal N4). The builder **must grep** `async_turn_on`/`light.turn_on` across `domain_coordinators/` and `lighting/` for any other per-room entry-light writer and list it in the build report with a verdict.
7. HVAC zone sweeps / pre-arrival: they turn lights OFF and do not turn them on (PRESENCE doc §5 paused-rooms note). Builder re-verifies.

---

## 4. Decisions

### D-a Wake bypass (`can_bypass_sleep_mode`, `automation.py:1303-1312`)
Finding (verified): the motion-count bypass **never lights mains in a night-light room even today**. Bypass only flips `should_execute_automation` (`:1342-1348`) to True. Entry then reads `is_sleep_lighting_active()`, which is still True (the clock leg), so it takes the night-light-only branch at `:1470`. The bypass only releases covers and auto switches. In practice the light "wakes" when house state leaves `sleep` (WAKING/HOME_*) or by manual action.

**Recommendation (default): no new wake mechanism.** Under house sleep with protection off, nothing automatic lights mains. Waking is via the house-state exit (the next entry or reconcile after WAKING lights normally) or a manual switch, which the manual hold protects (D-b). This matches protection-on rooms exactly. A motion-count bypass for protection-off rooms would add a second per-room counter path (marginal benefit small, given the room already has night lights for safe walking). It is parked with this trigger: operator reports being stuck in dim light and wanting motion to wake a specific room. **Operator question Q1.**

### D-b Should `_turn_off_non_night_lights` run for these rooms?
Yes, run it. Weighing:
- **For running it:** without it, a main light left on from the evening stays on in a "sleep" room, and the reconciler (C2) asserts `sleep_non_night_off` anyway. Skipping it in canonical would make canonical and the reconciler disagree, and they would fight (I1 parity). Protection-on rooms already run it.
- **The manual-light worry is already handled by the manual hold:** `light_hold_allowed(..., "off")` (`automation.py:2000`, `:790-795`) blocks URA's OFF on any light a person turned ON while the room is occupied, until the room empties. The reconciler honours the same hold (`actuator_reconciler.py:672-680`). The hold is on by default in every room (REV 2.5 ruling 2). So someone who turns on the Dining Room chandelier at 02:00 keeps it while they're there. Once the room empties the hold is released (`release_light_holds_on_vacancy`, `automation.py:1366`), and the next entry gets night lights only. That is the intended outcome.
- Residual: a main light switched on **from outside the room** (app/dashboard) while the room is empty has no hold, and the reconciler may turn it off during house sleep. Same as protection-on rooms today; accepted, listed in non-goals.

### D-c Reconciler
No reconciler code change. It reads the same predicate (`:807`), so it asserts what canonical does. The builder must confirm by test (T3) that, for a protection-off night-light room under house sleep, canonical's emitted set equals the reconciler's per-entity desired state, cell for cell (occupied/vacant × night/main × dark/light).

### D-d `_house_state_is_sleep` helper
KEEP + DOCUMENT: update its docstring (`automation.py:1267-1276`) to say the main-light authority now follows house sleep for night-light rooms, and that the helper is a fallback for night-light params only. No deletion this cycle.

---

## 5. Deliverables

### D1 — Widen the predicate behind a kill switch
In `is_sleep_lighting_active` (`automation.py:1251`), replace the `CONF_SLEEP_PROTECTION_ENABLED` early return with: protection on → today's behaviour; protection off → return `house_state == sleep` only if `NIGHT_LIGHTS_HOUSE_SLEEP_ALL_ROOMS_ENABLED` and `CONF_NIGHT_LIGHTS` is non-empty; otherwise False. Keep the fail-open exception arm. Update the docstrings at `:1252-1257`, `:1268-1276`, `:1284-1289` to state the REV 2.5 widening (light choice only), and `actuator_reconciler.py:779` truth table comment.

**Acceptance criteria**
- **Verify:** Dining-Room-like config (night lights, protection off, `turn_on_if_dark`, lux 0), house `sleep`, 03:00: entry turns on only night lights with `_nl_params(cfg,"sleep",...)` params and does not turn on mains. Under the plausible *different* failure (predicate widened but slot scene path bypassed, or the reconciler not following), the reconciler log shows `sleep_non_night_off` vs a canonical main ON (flapping). Under the fix both agree, so the discriminator is "no main ON in either controller".
- **Verify:** same config, house `home_night`: behaviour byte-identical to today (mains on if dark).
- **Verify:** kill switch False ⇒ every test in the old suite passes unchanged, including the pre-cycle form of `test_sleep_disabled_switch_still_off_under_house_sleep`.
- **Verify (I2):** `is_sleep_mode_active()` unchanged across a (protection on/off) × (clock in/out) × (house sleep/not) grid; covers/fans untouched.
- **Verify:** room with no night lights, protection off, house sleep → `is_sleep_lighting_active()` False; entry writes identical to pre-cycle.
- **Test:** `test_nl_house_sleep_protection_off_night_lights_only` (entry), `test_nl_house_sleep_protection_off_lights_on_entry_explicit` (`lights_on_entry` contains a main → still excluded), `test_nl_house_sleep_dark_only_and_by_day_irrelevant`, `test_nl_house_sleep_slot_scene_sleep_used`, `test_nl_house_sleep_no_night_lights_unchanged`, `test_nl_house_sleep_kill_switch_off_restores_old`, `test_is_sleep_mode_active_grid_unchanged`. `test_sleep_disabled_switch_still_off_under_house_sleep` (`test_lighting_slice_d_house_state.py:274`) is **rewritten deliberately**: it asserts today's opposite behaviour. Split it into "no-night-light room still off" + "night-light room now on". Record the rewrite in the review doc; do not just flip an assertion.
- **Live:** see D3.

### D2 — Parity and hold tests (no production change expected)
- **Test T3:** `test_nl_house_sleep_reconciler_canonical_parity`: for each cell (occupied/vacant × night/main entity × dark/bright × protection off), reconciler `_resolve_light` desired state matches what canonical emitted (reuse the harness pattern in `test_night_light_rule_parity.py` / `test_nightlight_red_reconcile_parity.py`).
- **Test:** `test_nl_house_sleep_manual_main_on_survives_while_occupied`: a person turns a main light ON while occupied under house sleep, and neither `_turn_off_non_night_lights` nor the reconciler turns it off until vacancy. Mutation anchor: drop the `light_hold_allowed` call at `automation.py:2000` and the test must go RED.
- **Test:** `test_nl_house_sleep_room_lights_switch_night_only` (C4) asserts whatever Q2 decides.
- **Mutation anchors (framing C):** (a) revert the predicate's new arm, and the entry test plus T3 go RED; (b) remove the `night_lights` guard, and `test_nl_house_sleep_no_night_lights_unchanged` must still hold. If it stays green, document that the guard is defence-in-depth (the predicate-level check). The test that must go red is `test_is_sleep_lighting_active_no_nl_false` (direct predicate assertion).

### D3 — Live validation (post-restart, first night in house sleep)
- **Live:** `sensor.<house_state>` = `sleep` (house-state sensor). Then pick the first entry recorded in any of the 10 rooms (e.g. Dining Room, Butler Pantry, Kitchen Hallway, Study B). Recorder shows the room's night light entity ON with brightness/colour matching the sleep slot and **no** OFF→ON transition on any `CONF_LIGHTS \ CONF_NIGHT_LIGHTS` entity for that room while house = sleep. The discriminator against "the room just wasn't entered" is that the room's occupancy sensor shows an occupied edge in the same window.
- **Live:** Powder (protection on since 10-23) and Master Bath Toilet unchanged: night lights only (control group).
- **Live:** one no-night-light room (e.g. Oji Vanity or Guest Bedroom 1 Bathroom) unchanged: its main light still turns on at entry in house sleep. This proves no-NL byte-identity and is expected; Oji Vanity is Q3.
- **Live:** no `sleep_non_night_off` reconciler skip/flap loop for those rooms (reconciler diagnostics `_record_skip` / reason counts), and covers in the 10 rooms did not change behaviour (no new cover writes vs the previous night).
- One-shot recorder query at disposition, not a soak.

---

## 6. Knobs

| Number / switch | Name | Rung | Why | Kill semantics |
|---|---|---|---|---|
| Kill switch | `NIGHT_LIGHTS_HOUSE_SLEEP_ALL_ROOMS_ENABLED` (const.py, default `True`) | 1 (module const) | Behaviour toggle that should need review to flip; a per-room opt-out already exists in spirit (remove the room's night lights or set entry to none) | `False` restores pre-cycle exactly |
| Per-room opt-out | none new | — | Parsimonious room config; if a room must keep mains at night, remove its night lights. Revisit if the operator asks (Q4) | — |

No other behavioural numbers are introduced.

---

## 7. Non-goals
- N1. No change to `is_sleep_mode_active`, covers (`CONF_SLEEP_BLOCK_COVERS`), fan sleep policy, the bedroom fan hold, exit-skip or `can_bypass_sleep_mode` / `CONF_SLEEP_BYPASS_MOTION` (REV 2.5).
- N2. No change to rooms without night lights (incl. Oji Vanity, Q3).
- N3. No change to house-state inference (when SLEEP is entered or left).
- N4. No change to AI / house-state rule light writes, HVAC light sweeps or Away leave-on.
- N5. No new per-room CONF or options-flow field.
- N6. Remote (out-of-room) manual main-light ONs during house sleep may be turned off by the reconciler (same as protection-on rooms today).
- N7. No deletion of `_house_state_is_sleep`.

## 8. Tier
**Tier 2-DB (3 framing-disjoint reviews + live validation)** by the 2026-06-08 standing policy: a shared light-choice predicate read by canonical, the reconciler and a switch entity, i.e. a two-controller parity seam. It is not Tier 3: the change is not cost/safety (lights only), there is one predicate site, and the kill switch is a constant. Suggested framings: A = predicate correctness + config combinatorics (protection × night lights × lights_on_entry × dark_only × by_day × kill switch); B = canonical ↔ reconciler parity, manual-hold interplay, no flap, house-state transitions mid-occupancy (sleep→waking while occupied); C = mutation-anchored test authority (§D2 anchors). Plan review: one adversarial pass before build.

## 9. Operator questions (recommended defaults)
- **Q1 Wake under house sleep, protection off:** recommend **nothing automatic wakes the mains; leaving house sleep or a manual switch does.** This matches protection-on rooms (whose motion bypass does not light mains today either, see D-a).
- **Q2 Room Lights master switch (`switch.py:5418`) in the 10 rooms during house sleep:** today it would turn on night lights only (same as protection-on rooms). Recommend **keep that**, for consistency, and because the physical wall switch still gives full light. The alternative is to make the master switch always mean "all lights", which is a separate small change and would also alter the 12 protection-on rooms.
- **Q3 Oji Vanity (no night lights):** recommend the operator assigns a night light to it (config, no code). Otherwise it keeps lighting fully at night.
- **Q4 Per-room opt-out from this widening:** recommend **none** (parsimony); a room that should keep mains at night can drop its night lights.

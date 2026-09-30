# Plan review — PLANNING_room_dialog_cleanup_and_lighting_roles.md (ROOM-LIGHTING-SETUP-REDESIGN-1)

Reviewer: ura-reviewer (adversarial plan pass, one review). Date: 2026-09-29. Read-only; greps against develop working tree.

**Verdict: REVISE.** The design rule and ranking match the operator's scope (kanban.data.yaml:30566-30567). But the plan's central invariant ("every room behaves identically") is broken by its own D1 darkness change. Its consumer map leaves out the second light emitter (actuator_reconciler). Its migration anchor points at an unrelated function.

## Findings

1. **HIGH — D1 sun fallback breaks the invariant (#63 / behaviour drift).** `automation.py:933-937`: `is_dark(None)` returns **False**. So a room with no lux sensor and `entry_light_action=turn_on_if_dark` never turns lights on today. With the fallback order (lux, then borrowed lux, then sun), that room starts turning lights on after dusk. Stale or unavailable lux also flips from "not dark" to "sun decides". Either declare this an intended, operator-approved change (and drop it from the invariant), or put the sun fallback behind a per-room role that defaults to off.
2. **HIGH — two `is_dark` call sites; the plan names one (#53).** `automation.py:1032` and `actuator_reconciler.py:794`. The reconciler has its own entry-action and darkness path (`actuator_reconciler.py:748-813`: night lights, `CONF_ENTRY_LIGHT_ACTION`, and the exit union `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`). The new pieces must reach the reconciler too: per-light entry roles, dark-only, leave-on-when-empty, the D2 hold and the D4 house-state gates. If they don't, the reconciler will "correct" lights back and undo them. It needs to go into D1, D2, D4 and the producer/consumer table.
3. **HIGH — the producer/consumer map is incomplete.** Readers the plan leaves out:
   - `domain_coordinators/hvac.py:5700-5720` (`CONF_NIGHT_LIGHTS`)
   - `coordinator.py:1225-1236` (AI-rule conflict union of LIGHTS, NIGHT_LIGHTS, AUTO_DEVICES and AUTO_SWITCHES)
   - `binary_sensor_control_attrs.py:28` (`control_night_lights` attr)
   - `aggregation.py:1428` (`CONF_ALERT_LIGHTS`, read options→data)
   - `actuator_reconciler.py` (12 refs)
   - `automation.py:1282-1320` (legacy AUTO/MANUAL_SWITCHES fallback)

   The keys are unchanged, so these still work. But a per-light role list the reconciler and the AI-conflict union don't know about is #53.
4. **HIGH — the migration anchor is wrong, and "migration" is under-defined.** `config_flow.py:3063 async_step_migration` creates the *integration* entry, not a room migration. `ConfigFlow.VERSION = 1` (`config_flow.py:748`), and `__init__.py` has no `async_migrate_entry`. The plan also says "keys unchanged" while adding new role lists that "override when non-empty". The correct design is **no stored-data migration at all**:
   - New keys are absent, which means the global `CONF_ENTRY/EXIT_LIGHT_ACTION` applies.
   - The invariant proof becomes a **resolver-equivalence test**: for absent keys, `effective_entry_set(cfg)` equals today's set across a config matrix. A byte-identity check on the options dict proves nothing.

   Remove the invented `sensor.<room>_config_schema_version`. If a real migration is kept, it must not seed `CONF_LIGHTS_ON_ENTRY := CONF_LIGHTS`. Seeding it would turn night lights and switch-as-light entries into entry roles and change the entry set.
5. **HIGH — "pickers restricted to enumerated devices" can silently drop saved values.** `CONF_NIGHT_LIGHTS` is **not** required to be a subset of `CONF_LIGHTS`. They are separate lists, and the code treats them as a union (`actuator_reconciler.py:109`, `coordinator.py:1231`, `automation.py:1053-1054`). `CONF_ALERT_LIGHTS` is also independent. Suppose the Lighting picker's `include_entities` is built from `CONF_LIGHTS`: an existing night or alert light outside it gets filtered out, and the next save drops it. That breaks the invariant.

   Filter from the union of LIGHTS, NIGHT_LIGHTS, ALERT_LIGHTS and the currently stored value. HA side: `EntitySelectorConfig(include_entities=[...])` is rebuilt every time `async_step_*` runs, so a dynamic list works. It must be sourced from the **in-flight** options state (the edits already made in the Devices step during this session), not `entry.options`. No existing `include_entities` usage is in `config_flow.py`, so this is a new pattern and needs a round-trip test.
6. **HIGH — D2 prior-art claim is too narrow.** There is no light hold *ledger*, but there are related controls:
   - A per-room `ManualModeSwitch` (`switch.py:5199`), enforced as reconciler Guard 2 (`actuator_reconciler.py:496`).
   - `SecurityDelegateLightsSwitch` (`switch.py:4941`).
   - The fan external-ON detector with the "our own write mis-labelled external" hazard (`actuator_reconciler.py:628-630`).

   D2 must say how the light hold composes with manual_mode. D2 and D3 must also reuse the fan self-write discrimination; otherwise URA's own `light.turn_on` gets noted as manual. D3 (`switch.<room>_lights`) must not be confused with `manual_mode`. In the same section, the plan says the listener is "already present for other purposes" without naming it. Name it.
7. **MEDIUM — D1 per-light feature summary has no data source.** `CONF_LIGHT_CAPABILITIES` is ONE room-level enum (`basic`/`brightness`/`full`, `const.py:870,891-893`), not per light. A per-light summary needs live `supported_color_modes` reads. Either say that, or render one room-level line.
8. **MEDIUM — D1 "one wait time… already exists" is unverified.** No light-exit-wait key found. The nearest key is `CONF_OCCUPANCY_TIMEOUT` (`const.py:398`), which drives occupancy for every consumer, not just lights. "Consolidating" into it would change HVAC, fan and presence behaviour. Name the actual key(s), or make `CONF_LIGHT_EXIT_WAIT_S` new with default 0 (no extra delay).
9. **MEDIUM — D4 overlaps existing behaviour.** Sleep hours already mean "night lights only, others off" (`automation.py:1018-1027`, clock-based `is_sleep_mode_active`, `:903-916`). The plan's HouseState=Sleep rule is a second sleep source that can disagree with the room's clock window. Define precedence. "Away ⇒ all room lights off" is a NEW house-wide actuator. It needs its own boot-settle gate, because a restart drops Sleep and flips Home→Away transients (memory: no restart during sleep). It also needs a no-flap test. Guest values are unspecified beyond names.
10. **MEDIUM — knob ladder bloat.** Per-room Numbers for the exit wait (×2), the illuminance threshold, the holds (×2) and D5 slots (3 slots × 2) come to roughly 10+ entities × ~40 rooms, which cuts against the parsimonious-room-config rule. `CONF_ILLUMINANCE_THRESHOLD` is already a config-flow field, so a Number for it creates the "Number fields = form fields" dual-writer trap. Recommendation: module-const defaults plus config-flow fields. Add a Number only where the operator actually tunes by observation, and show the knob inventory before build.
11. **MEDIUM — acceptance criteria don't discriminate.** The D8 byte-identity test passes trivially when nothing is migrated (see finding 4). D5's "14:00/20:00/23:30" tests are wall-clock-coupled (a known bug family). Inject the clock. Add a test for the no-lux, `turn_on_if_dark`, after-dusk room. It is the one case that separates "invariant holds" from finding 1.
12. **LOW — D8 sweep method.** "grep EntitySelector" misses role fields written with `cv.multi_select` or boolean toggles. Per scope_2026_09_29, the list must include Auto-On/Off, Auto-Off-Only, Auto and Manual Devices. Check the sweep covers every edit-path step listed at `config_flow.py:1862-2918`, not only Devices and Notifications.
13. **LOW — tier.** The work adds a new light oracle, a second emitter path in the reconciler and a new house-state actuator, which is cross-coordinator ripple. Declare it Tier 2-DB (three framings) explicitly instead of "2 + a third for D8". The D2/D3 pair arguably deserves Tier 3's per-site mutation pass, because the failure mode is one missed emitter.

## Build-prediction (what the builder will get wrong)
- Wire `is_dark_effective` only into `automation.py`, leaving the reconciler on `is_dark` (finding 2).
- Build `include_entities` from `entry.options[CONF_LIGHTS]`, which drops night and alert lights on save (finding 5).
- Implement the "migration" in `async_step_migration`, or seed the new role lists from `CONF_LIGHTS` (finding 4).
- Note URA's own light writes as manual in D2 (finding 6).
- Fold the light wait into `CONF_OCCUPANCY_TIMEOUT` (finding 8).

## Must-fix before build
Findings 1–6 in the plan text, plus corrected acceptance tests per finding 11.

---

## REV 2 / 2.1 re-review (2026-09-29)

**Verdict: REVISE.** F2, F4, F5 and F6-composition are fixed. F3 is fixed for config readers. Three gaps remain open. Two are new: the emitter list and the name of the lux key. The third is that the dropped timer is still in the plan body.

### F-fix verification
| F | Status | Evidence |
|---|---|---|
| F1 | FIXED | Invariant restated; kill-switch `CONF_LIGHT_DARK_USE_SUN_FALLBACK` (plan:130); D0 found 2 rooms (plan:301). See R2-3 for the D0 counting gap. |
| F2 | FIXED | Both sites `automation.py:933` and `actuator_reconciler.py:794` wired (plan:155) and drilled by mutation (plan:266). |
| F3 | FIXED (config readers) | Table plan:103-115 matches my greps (hvac.py:5700-5720, coordinator.py:1225-1236, control_attrs:28, aggregation.py:1428, reconciler, automation.py:1282-1320). |
| F4 | FIXED | No migration and no schema sensor (plan:233, :297); resolver-equivalence proof. |
| F5 | FIXED | `include_entities` = LIGHTS ∪ NIGHT ∪ ALERT ∪ stored value, taken from the in-flight flow state (plan:147). |
| F6 | PARTIAL | Composes with ManualModeSwitch disjunctively (plan:176). Reuses fan self-write discrimination (plan:174). SecurityDelegateLightsSwitch composition is cited but never stated. The self-write reuse covers only the room's own writes; see R2-1. |
| F8 | SUPERSEDED by REV 2.1 | The removal is incomplete; see R2-2. |

### New or remaining findings
- **R2-1 HIGH — the emitter list is incomplete, and the D2 listener will mistake other coordinators' writes for manual changes (#53).** Plan:118 lists only the automation.py entry/exit and reconciler emitters. Other code also calls `light.turn_on/turn_off`:
  - `domain_coordinators/notification_manager.py:2378-2460` (alert flash and restore)
  - `aggregation.py:1468-1487` (alert-light emitter)
  - the security delegate-lights path (`switch.py:4941` gate)

  The D2 `state_changed` listener watches CONF_LIGHTS ∪ NIGHT_LIGHTS (plan:174). An alert light that is also a room light gets flashed and restored by NM, and each of those changes would open a manual hold, so room automation stops for the hold duration. Required: a cross-coordinator self-write mark, meaning context-id or a shared "URA-issued" stamp, not just the room-local fan pattern. List these emitters and state whether each one consults the hold or is exempt from it.
- **R2-2 HIGH — the plan body still requires the dropped `CONF_LIGHT_EXIT_WAIT_S`.** The banner (plan:1) says it overrides, but these lines still define or consume it:
  - plan:21 (F8 row)
  - plan:86 (prior-art row)
  - plan:114 (consumer table)
  - plan:142 (D1 field 7)
  - plan:226 (D7 "bypass CONF_LIGHT_EXIT_WAIT_S")
  - plan:249 (knob table)

  D7 now has nothing to bypass. Rewrite it in terms of the occupancy timeout, or drop D7. A builder reading D1 field 7 will build the timer. Strike these lines; a banner is not enough.
- **R2-3 MEDIUM — the D0 count misses rooms whose lux sensor is present but unavailable or stale.** Evaluation order step 1 is "fresh" lux, else fall through to the sun (plan:150-152). So a room with a lux sensor that is unavailable, or stale by the Bug Class #7 rule, is also affected, both today and whenever a sensor drops. D0 counted only rooms with no sensor at all. Either count those rooms too (the current-unavailable live read), or accept it in the invariant text.
- **R2-4 MEDIUM — the lux key name in the resolver is wrong.** Plan:150 uses `CONF_LUX_ENTITY`, which does not exist. The real key is `CONF_ILLUMINANCE_SENSOR` (`const.py:862`). The staleness rule is asserted, not cited. Name the existing freshness helper at file:line, or say it is NEW. Today `is_dark` takes a raw value with no freshness check.
- **R2-5 LOW — the D3 fallback is inconsistent.** It turns on `CONF_LIGHTS_ON_ENTRY` "or CONF_LIGHTS if empty" (plan:190), which leaves out night lights. The resolver-equivalence default (entry set = LIGHTS + night lights in day mode, `automation.py:1051-1054`) should be the single definition that D3 uses.

### Must-fix
R2-1 and R2-2. R2-3 and R2-4 are one-line plan edits.

### REV 2.2 (Away optional-off boolean)
- **R2-6 HIGH — D4 contradicts REV 2.2.** Plan:206 still says "HouseState=Away: all room lights off". That is the unconditional house-wide rule REV 2.2 replaces. The matrix test (plan:211) and the no-flap and boot-settle tests (plan:212-213) are written against it. Required edits:
  - Rewrite D4's Away bullet: on Away, only lights in `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` are turned off, and only when the new per-room boolean is True. Everything else follows the normal vacancy/exit path, with no new Away actuation.
  - Add the boolean to the producer/consumer table (both emitter sites: automation exit and the reconciler exit union) and to the knob table.
  - Add a test that the boolean is ignored when the leave-on list is empty.
  - Add a test for boolean False: Away leaves the exempt lights on.
  - Keep the boot-settle and no-flap tests, now scoped to this narrower action.
  - State whether the D2 manual hold vetoes this Away turn-off. Otherwise a manually-held exempt light has undefined precedence.

**Updated verdict: REVISE.** Must-fix: R2-1, R2-2, R2-6. R2-3 and R2-4 are one-line edits.

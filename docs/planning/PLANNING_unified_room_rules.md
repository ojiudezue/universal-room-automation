# PLANNING: unified room rules (described and chained)

Card: AI-ROOM-RULES-TRUST-REPAIR-1. Parent: AUDIT-ROOM-AI-AUTOMATION-CHAINING-MUSIC-1.
Related: MUSIC-FOLLOWING-TRANSFER-REPAIR-1 (same observability pattern), PERSON-PROFILE-PREFERENCES-1.
Plan review: `docs/reviews/plan-review/PLANREVIEW_unified_room_rules.md`.

## 0. Charter (operator 2026-11-13, verbatim)

- "No shadow mode... Treat the reformulations as full blown mission critical feature that must work on day 1. My
  trust just means get it right and make sure it's tested well. No delays. This is where our features die and are not
  switched on."
- "The thing to build into the 3 feature, now 2 is observability and logs that allow diagnostics and tuning. Maybe
  room memory entries as well to extend the memory feature."
- "AI feature UI should be well considered. Smart and simple to approach. Sounds like there may be modification to
  the [options flow] menu and the toggles? Key"
- Paid `ai_task` call for live validation: approved on `ai_task.claude_ai_task`. "Make sure we're using the right
  model and cost that will achieve results."

What that means: a room rule is one record however it was authored (described in words, or "run this automation
when X"). It is saved only when it compiled to valid actions, the person sees a preview written by code from those
actions, and once saved and switched on it runs. Every evaluation is logged with its reason.

## 1. Institutional context verified

Read completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10; no ledger claim re-asserted) and
`SENSOR_FLEET_CLASSES.md`; person enter/exit now consumes `ura_person_location_change`. HVAC code is not touched
(the climate block stays). Also read: the plan review, the board card (all `operator_*` fields,
`FINDING_ai_task_schema_2026_11_13`, `amendment_pending`, `fix_round_scope`), `ARCHITECTURE_hierarchical_memory.md`
§4, §8, `AUDIT_room_memory_and_coordinator_request_apis_2026_10_21.md`, `PLANNING_v3.10.0_AI_AUTOMATION.md`, memories
on labels, configurability clarity, F1-F5, hollow anchors, wire-in anchors. Code on develop 3e17310a.

| Piece | Verdict | Where |
|---|---|---|
| Rule store | REUSE | `CONF_AI_RULES` (read `coordinator.py:1166`; options then data fallback `config_flow.py:15064-15068`) |
| Chain store | REUSE as legacy input | `CONF_AUTOMATION_CHAINS` (`coordinator.py:871`); 0 rooms use it live |
| Executors | MERGE | `_fire_chained_automations` `coordinator.py:865` (unguarded `automation.trigger` `:897`), `_execute_ai_rules` `:1160` |
| Guards | REUSE (move) | `_execute_rule_action` `:1215`: allowlist `:1208/:1234`, climate `:1259`, security cover `:1279`, light hold `:1295-1300`, URA context stamp |
| Switch gate | REUSE, made explicit | `_is_ai_automation_enabled` `:3253` (manual mode wins `:3261`); gated callers `:1017, :1058, :5455`; safety `:1096` and security `:1134` bypass it |
| Room switch | REUSE, relabel | `switch.<room>_ai_automation` `switch.py:5720-5755` (RestoreEntity, default on) |
| Person in room | REUSE | `get_persons_in_room` `person_coordinator.py:2202`; person event `:1059-1068` |
| Person key | REUSE | `music_following._person_key` `music_following.py:44` |
| Darkness | REUSE | `automation.is_dark` `automation.py:1325` (falls back to `lighting/darkness.is_dark_fallback` `:128`) |
| LLM structure | REUSE pattern | `OPTIMIZER_LLM_STRUCTURE` `const.py:5534`, parser `_extract_findings_list` `optimization_llm.py:976` |
| Parsers (two) | MERGE | init `config_flow.py:3184` + `:3309`; options `:15246` + `:15368`; prompt list `:3263-3287` |
| Prompt | REUSE + EDIT | `AI_RULE_PARSING_PROMPT` `const.py:4532` |
| ai_task entity | NEW knob | today the call passes no entity (`config_flow.py:3238`), so HA's default AI Task entity is used |
| Status sensor | REUSE + FIX | `AIAutomationStatusSensor` `sensor.py:2884`; conflict binary sensor `binary_sensor.py:1503` |
| Manual change detector | REUSE | `ActuatorReconciler._note_manual_light_change` `actuator_reconciler.py:500` (non-URA on/off edge of a room light while occupied) |
| Memory writer, digest, page, nightly | REUSE | `database.log_memory_episode` `database.py:10686`; `MEMORY_EPISODE_TYPES` `const.py:6092`; `_build_optimizer_digest_section` `notification_manager.py:5788` (called `:5640`); `fire_stuck_signal` `_stuck_signal_nm.py:165`; `nightly_maintenance.py` op list |
| Menus | RESTRUCTURE | `async_step_automation_chaining` `config_flow.py:14919`, `async_step_ai_rules` `:15018`, `_STEP_EXTRA_OWNED_KEYS` / `_MENU_ONLY_ROOM_STEPS` `:3845-3855`, strings `strings.json:629-633, 2154-2232` |
| Rule compiler module, preview renderer, condition set | NEW | grep `rule_compiler`, `render_rule_preview`, `RULE_CONDITION` in package = 0 |

Config-first: the Exercise Room rule has no actions (every parse failed on the rejected `object` selector), so no
switch or setting makes it run. Code is needed.

## 2. Identity model and consumer class

Person-scoped rules consume F4-shaped per-person room location from dense BLE (the PersonCoordinator room-change
event) plus F1. No F2, F3 or F5. Consumer class: comfort and convenience. Rules may target `lock` and `cover`
behind the existing guards; this plan does not widen what a rule may act on.

## 3. Falsifiable invariants

- **INV-R1 (one gate).** Every service call issued because of a rule passes through `_execute_rule_action`, which
  applies the allowlist, the climate block, the security-owned cover block, and the light manual-hold oracle for
  `light`/`switch` on/off (the compiler rejects `toggle` for those domains). Break it with any rule-derived
  `async_call` outside that function.
- **INV-R2 (no unparsed rule).** A rule with zero valid actions is never saved, executed or counted active.
- **INV-R3 (switch semantics).** A rule on a room trigger, house state or energy trigger never runs while the room's
  Room Rules switch is off or Manual Mode is on. A rule on a safety-hazard or security-event trigger runs regardless.
- **INV-R4 (honest preview).** The confirmation text and each rule's list label are a pure function of the stored
  validated trigger, person, conditions and actions. LLM text never appears as the description of what a rule does.
- **INV-R5 (person rules fire on the person).** A person-scoped enter or exit rule fires on that person's room
  change event for this room, and never for another person.
- **INV-R6 (one decision each).** Every rule matched by a trigger produces exactly one decision (fire or a named
  skip) in the log, the stats and room memory.

## 4. Producer and consumer checks

**Producer: compiled actions.** Fire check: zero successful parses ever (schema rejected live, HTTP 500).
**Producer: person room.** Healthy (8,126 transitions in 14 days); emits on change, display names.
**Producer: triggers.** Occupancy enter/exit `coordinator.py:5444-5448`; signal triggers subscribe only when a rule
needs them (`:1786-1823`). **Executor fire check:** 0 chain fires, 0 rule fires in 30 days; chains in 0 rooms.
**Consumers:** actions reach devices (trust); status sensor, conflict sensor, activity rows, episodes, digest
(display). Forward trace: trigger -> match -> switch gate -> person -> conditions -> gate -> call -> decision record ->
reversal watch -> digest and trip-wire.

## 5. Emission and decision sites

Rule-derived calls: `coordinator.py:897` (chain) and `:1346` (inside `_execute_rule_action`). Callers: `:1026-1027`,
`:1068-1069`, `:1107-1108`, `:1145-1146`, `:5462/:5466` (review re-enumeration confirmed complete). Rule readers:
`coordinator.py:1015, 1056, 1094, 1132, 1166, 1787`, `sensor.py:2903-2918`, `binary_sensor.py:1503-1508`. Writers:
`config_flow.py:3006-3015, 3115-3132, 14965-14978, 15064-15079`, `ai_rule_delete`. After the build, `:897` is gone and
every caller calls `_run_room_rules(triggers, event=None)`. The builder re-greps and pastes the lists in the README.

## 6. Deliverables

### D1: one compiler, provider-portable structure
`rule_compiler.py` holds the single parser, validator and preview renderer, used by the options flow (the two old
copies go). Structure: text fields `actions_json` (JSON array), `conditions_json` (JSON array, may be empty),
`unsupported` (plain text naming anything the description asked for that the rule cannot express), `summary`
(stored as secondary text only). Parse with the `_extract_findings_list` precedence, `json.loads`, then strict checks:
- **Room entity set**, defined once by `room_entity_set(entry)` = the room's configured devices + its climate entity
  + every entity in its HA area (the prompt list at `config_flow.py:3263-3287`). The same set feeds the prompt and
  validation. Exemption: `automation.*` and `scene.*` targets may be any existing entity of that domain.
- **Allowlist:** `_AI_RULE_ALLOWED_DOMAINS`, minus `climate`. `toggle` rejected for `light` and `switch`.
- **Data keys:** `ROOM_RULE_DATA_KEYS` (rung 1), per domain: light `brightness_pct`, `color_temp_kelvin`,
  `rgb_color`, `color_name`, `transition`; fan `percentage`, `preset_mode`, `oscillating`, `direction`;
  media_player `volume_level`, `media_content_id`, `media_content_type`, `source`; cover `position`, `tilt_position`;
  automation `skip_condition`; input_*/number/select `value`, `option`. An unknown key rejects the rule (no silent
  drop) with the key named.
- **Timeout:** the call is wrapped in `asyncio.timeout(RULE_PARSE_TIMEOUT_S)`.
- **Entity:** `CONF_ROOM_RULES_AI_TASK_ENTITY` (§8).
- **Test:** `test_rule_compiler_structure_has_only_text_fields`, `test_rule_compiler_parses_nested_and_flat`,
  `test_rule_compiler_rejects_entity_outside_room_set`, `test_rule_compiler_allows_any_automation_target`,
  `test_rule_compiler_volume_level_and_fan_percentage_kept` (one case per domain key list),
  `test_rule_compiler_rejects_unknown_key_by_name`, `test_rule_compiler_rejects_light_toggle`,
  `test_rule_compiler_timeout_returns_parse_failed`.
- **Discriminates:** the old `object` structure fails the first test; a fan rule at 50 percent keeps `percentage`.

### D2: conditions (fixes HIGH-5)
A small set, checked in `_run_room_rules` before actions, each from data the room already has:
`after_dark` (`automation.is_dark`), `time_window` (local start/end, may cross midnight), `house_state_in` (list of
house states). A description needing anything else (weather, another room, a sensor value) comes back in
`unsupported`, and the form refuses to save and names it. Why three: they cover the common phrasing ("after dark",
"between 7 and 9", "when we're home / asleep") and each reads one existing value; a general condition language would
repeat HA automations, which the "run an automation" path already reaches.
- **Test:** `test_rule_condition_after_dark_false_skips`, `test_rule_condition_time_window_crosses_midnight`,
  `test_rule_condition_house_state`, `test_rule_form_refuses_unsupported_and_names_it`.

### D3: never store an unparsed rule; honest preview (fixes HIGH-3, MEDIUM-5)
Save is refused on a parse failure, zero actions or a non-empty `unsupported`; the typed text is kept. The preview is
`render_rule_preview(rule, hass)`: trigger, person, conditions and each action with entity friendly names and data in
plain words, e.g. "When Oji enters Exercise Room, after dark: turn on Exercise Lamp at 40 percent." If the room's
Room Rules switch is off, the preview step shows "Room rules are off in this room" with a checkbox "Turn them on"
(default on); saving with it checked calls `switch.turn_on` on the switch resolved by unique id
`{entry_id}_ai_automation`.
- **Test:** `test_rule_preview_renders_from_actions_not_summary` (LLM summary says "after dark", actions have no
  condition: preview omits "after dark"), `test_rule_form_refuses_unparsed`, `test_rule_save_turns_switch_on_when_checked`.

### D4: one record, one executor, explicit gates (fixes HIGH-1, MEDIUM-1, MEDIUM-2, LOW-1, LOW-2, LOW-3)
Read-time adapter (stored config not rewritten): `{rule_id, source: "described"|"automation", trigger (stored key
`trigger_type`), person, conditions, enabled, actions}`. A legacy chain entry becomes source `automation`, action
`automation.trigger` with `skip_condition` from the rule (default False: the automation's own conditions apply; HA's
default is True, so this is a behaviour change, repeated in the README). `_run_room_rules(triggers, event=None)`
replaces both executors and decides in this order: match, switch gate, person, conditions, then every action through
`_execute_rule_action`. Switch gate: triggers in `ROOM_RULE_SWITCH_EXEMPT_TRIGGERS` = {safety hazard, security event}
skip it; all others need the switch on and Manual Mode off (skip reasons `switch_off`, `manual_mode`). Automation
rules run first (old chain order); calls stay non-blocking as today. `_last_conflicts` keeps reset-per-evaluation
semantics, so the conflict binary sensor clears on the next clean evaluation. No reader filters on the old
`chain_trigger` activity action (grep 0); it becomes `rule_fire`. Honest limit in the docstring: an automation, script
or scene a rule triggers runs its own actions outside URA's gates.
- **Test:** `test_rules_automation_goes_through_gate`, `test_rules_automation_off_skipped`,
  `test_rules_safety_fires_with_switch_off`, `test_rules_security_fires_with_manual_mode`,
  `test_rules_enter_skipped_with_switch_off`, `test_rules_enter_skipped_with_manual_mode`,
  `test_rules_conflict_sensor_clears_on_clean_evaluation`, `test_rules_light_respects_manual_hold`,
  `test_rules_cover_security_owned_blocked`, `test_rules_climate_blocked`, `test_rules_kill_switch_default_is_unified`.
  All drive the real coordinator with a recording services fake (domain, service, data, target, context).
- **Test (Review C):** mutate each guard, the switch gate, the exempt set and the automation routing one at a time.

### D5: person rules (fixes HIGH-4)
Person-scoped `enter`/`exit` rules trigger on `ura_person_location_change` (one bus listener per room, added only
when the room has such a rule): `enter` when `current_location` is this room, `exit` when `previous_location` is,
person matched with `_person_key` on both sides; the person comes from the event, not a lookup. Rules with no person
keep the occupancy edge. Person-scoped rules on other triggers keep the `get_persons_in_room` check.
- **Test:** `test_rule_person_enter_fires_on_person_event`, `test_rule_person_exit_fires_on_person_event`,
  `test_rule_person_other_person_no_fire`, `test_rule_person_enter_not_fired_by_occupancy_edge`.
- **Discriminates:** under the old code, the enter rule at the occupancy instant with BLE not yet in the room skips.

### D6: observability (operator requirement)
1. **Decision log.** One INFO line per matched rule, prefix `Room rule decision`: room, rule_id, source, trigger,
   person (from event or lookup), outcome (`fired` or skip reason), guard that blocked, conditions evaluated with
   values (e.g. `after_dark=false lux=180`), actions issued, ms.
2. **Stats.** `AIAutomationStatusSensor` (renamed "Room Rules", three words or fewer) states `active`, `off`,
   `manual_mode`, `needs_parse`, `none`. Attribute `rules`: per rule `preview`, `status` (`active` / `off` /
   `needs_parse` / `disabled`), `fires`, `skips_by_reason` (every skip name: `switch_off`, `manual_mode`,
   `person_absent`, `condition_false`, `gate_blocked:<guard>`, `automation_off`), `last_fire`, `last_skip_reason`,
   `reversals`, counted since start, plus `knobs`.
3. **Accuracy from implicit reversal.** For `RULE_REVERSAL_WINDOW_S` after a rule action: for room lights, a person's
   opposite change booked by `_note_manual_light_change` (`actuator_reconciler.py:500`) is a reversal (one added call
   from that site to `coordinator.note_rule_reversal_candidate`); for other domains, a one-shot state listener on the
   targets with the same `is_ura_context` test. New sensor `sensor.ura_room_rules_accuracy` ("Room Rules Accuracy",
   CM device): percent of fires not reversed over 7 days, nightly from room memory; attributes per rule.
4. **Digest.** `_build_room_rules_digest_section` beside `:5788`, called at `:5640`, e.g. "Room rules, last 24 h: 9
   ran, 2 skipped (person_absent), 1 undone by hand (Exercise lamp). 1 rule needs a re-parse."
5. **Zero-fire trip-wire.** Nightly op `run_room_ai_health_check` (shared with music following; whichever ships second
   adds its half): an enabled, parsed rule older than `RULE_ZERO_FIRE_DAYS` with at least one evaluation and zero
   fires pages `fire_stuck_signal` kind `room_rule_silent` naming the rule and its top skip reason. Safety and security
   rules and rules never evaluated do not page.
- **Test:** `test_rule_decision_log_line_fields`, `test_rule_reversal_light_turned_off_by_person`,
  `test_rule_own_action_not_reversal`, `test_rules_digest_section`, `test_rule_silent_tripwire_pages_after_skips`,
  `test_rule_silent_tripwire_quiet_for_safety_and_unevaluated`.

### D7: room memory episodes (Tier 2-DB trigger: new persisted record shape)
- `room_rule_decision`: one row per matched rule evaluation; node `room:<slug>`; attrs = the D6 decision fields;
  `source_ref` `rule:<rule_id>:<ts>`; `window_dedup=False`, `dedup_source_ref=True`. Volume: rules are new; at about
  10 rules firing a few times a day, under 100 rows a day (`ROOM_RULE_EPISODE_LOG_PERSIST`, rung 1, is the off switch).
- `room_rule_reversal`: one row per reversal.
- Both added to `MEMORY_EPISODE_TYPES`. `room_rule_decision` goes into `MEMORY_WRITER_BACKED_EPISODE_TYPES` and into
  `MEMORY_WRITER_HEALTH_EXEMPT_TYPES` with the reason "a house with no enabled rules writes none; the per-rule
  trip-wire (D6.5) is the zero-fire health check at the right granularity". This is a deliberate partial decline of
  the house-wide writer check.
- Query: `memory_query` `episodes` / `narrative` on `room:<slug>`.
- **Compactor:** parked. A `room_rule_reliability` fact per rule (fires, reversals, top skip, 30 days). Revival:
  PERSON-PROFILE-PREFERENCES-1 build, or a rule with a reversal rate above 10 percent over 7 days.
- **Test:** `test_rule_episode_per_decision`, `test_rule_episode_types_registered`,
  `test_rule_episode_two_fires_in_ten_seconds_both_written`. Fixtures use production DDL.

### D8: migration and lifecycle (fixes MEDIUM-3, MEDIUM-4)
Rules are read from options, then data (the existing fallback). Every write (add, re-parse, edit, delete) goes to
options with the full list; a rule found only in `entry.data` (the Exercise Room rule `6a932dd2`) is copied into the
options list on its first edit, and the data copy is then ignored. It shows `needs_parse` and never runs until
re-parsed. Rule authoring leaves the initial room-creation flow (it wrote into `entry.data`); rules are added from the
room's options. Saving rules reloads the room entry (the existing options listener), which re-runs the signal
subscription builder (`:1786-1823`) and the D5 person listener.
- **Test:** `test_migration_data_only_rule_is_inert_and_flagged`, `test_reparse_writes_options_not_data`,
  `test_new_energy_rule_subscribed_after_options_save` (no restart), `test_legacy_chain_dict_becomes_automation_rules`.

### D9: tests and docs
Delete inline replicas in `test_ai_automation.py` and `test_automation_chaining.py`; keep real-path anchors
(`test_room_covers_garage_guard.py`, `test_hvac_w1a_site_migration.py`, `test_lighting_slice_c_manual_hold.py`).
Update the coordinator doc for room rules, `PLANNING_v3.10.0_AI_AUTOMATION.md` pointer, strings and translations.

### D10: live validation (approved paid call on `ai_task.claude_ai_task`)
Re-parse the Exercise Room rule, and add "when Oji enters after dark, turn on the lamp".
- **Live:** parse returns actions (no 500); preview names the lamp and "after dark"; status `active`; on Oji's
  entry after dark the lamp turns on and one `room_rule_decision` row with `fired` appears; by day a row with
  `condition_false`; another person's entry writes no fire; turning the lamp off by hand within 2 minutes writes a
  `room_rule_reversal` row; the digest shows the line next morning.
- **Discriminates:** a bypass path writes no decision row; an unparsed rule shows `needs_parse`.

## 7. UI (room options)

Before: two room menu entries, "Automation Chaining" (four submenus of automation pickers by trigger group) and "AI
Rules" (Add, View); rules can also be added during room creation; the room switch is called "AI Automation".

After: one entry, one switch name, three plain actions.
```
Room menu
  ...
  Room rules                                   (replaces "Automation Chaining" and "AI Rules")
    Describe a rule
        "What should happen?" (text)  e.g. "When Oji walks in after dark, turn on the lamp at 40%"
        "Only for" (person, optional)
        -> Check your rule (preview written from what will actually run)
           "When Oji enters Exercise Room, after dark: turn on Exercise Lamp at 40%."
           [ ] Turn on room rules in this room      (shown only when they are off; default checked)
           Save / Change the wording
    Run an automation
        "When" (enter, exit, dark, bright, house state, energy, safety, security)
        "Only for" (person, optional)
        "Automation" (picker)
        "Use the automation's own conditions" (on)
        -> Check your rule -> Save
    Your rules
        list, one line each: "<preview> - Active, ran 2 h ago" / "Off" / "Needs re-check" / "Never ran: <top skip>"
        pick one -> Turn off or on / Re-check from its wording / Change the wording / Delete
```
Room switch: display name "Room Rules" (entity id unchanged). Helper sentence: "On: this room's rules run. Off:
they pause, except rules for smoke, leaks and security, which always run. Manual mode pauses them too." Labels follow
the style guide: short phrases, plain words, no "AI", "parse", "trigger" or "chain" in labels; "Re-check" replaces
"re-parse". The CM gets one field, "Rule writing model" (AI Task entity picker, §8), in the Coordinator settings.

## 8. Model choice for rule writing

Today the call names no entity, so HA's default AI Task entity answers. `ai_task.claude_ai_task` is configured with
`claude-haiku-4-5` (max_tokens 4096, thinking budget 1024) and is also the Optimization Coordinator default
(`DEFAULT_OPTIMIZER_LLM_TASK_ENTITY` `const.py:5459`), so changing that entity's model changes OC cost.
Estimate per parse: about 3-5k input tokens (prompt + room entity list) and up to about 2k output (JSON + thinking).
List prices (Anthropic API): Haiku 4.5 $1 / $5 per million in / out, so about 1-1.5 cents a parse; Sonnet 5.5 $2 / $10,
about 2-3 cents. Parses happen once per save or re-check, a handful a month, so cost does not decide it; correctness of
the JSON against the room entity list does. Recommendation: a dedicated AI Task subentry for URA rules on a current
Sonnet-class model (the operator adds it in HA; I do not change HA config), selected through the new knob
`CONF_ROOM_RULES_AI_TASK_ENTITY` (rung 2, CM options; empty = HA default entity). This keeps OC on Haiku and its cost
unchanged. Day-1 default if the subentry does not exist yet: `ai_task.claude_ai_task`, with the D10 parse as the check;
if Haiku produces a wrong or rejected parse there, switch the knob.

## 9. Numbers get knobs

| Knob | Rung | Default | Why / kill semantics |
|---|---|---|---|
| `CONF_ROOM_RULES_AI_TASK_ENTITY` | 2 NEW | `ai_task.claude_ai_task` | which model writes rules; empty = HA default |
| `skip_condition` per automation rule | 2 (rule field) | False | automation's own conditions apply |
| `ROOM_RULE_SWITCH_EXEMPT_TRIGGERS` | 1 | safety, security | rules that run with the switch off; review-gated |
| `ROOM_RULE_DATA_KEYS` | 1 | per D1 | which data each domain may carry |
| `RULE_PARSE_TIMEOUT_S` | 1 | 30 | form never hangs |
| `RULE_REVERSAL_WINDOW_S` | 1 | 120 | accuracy window; 0 = off |
| `RULE_ZERO_FIRE_DAYS` | 1 | 7 | trip-wire age; 0 = off |
| `ROOM_RULE_EPISODE_LOG_PERSIST` | 1 | True | room memory writes |
| `ROOM_RULES_UNIFIED_EXECUTOR` | 1 | True | back to two paths if needed; a test pins True |

`RULE_CONFLICTS_KEEP` and `RULE_STATUS_FIRES_WINDOW_DAYS` from the earlier draft are dropped: conflicts keep their
reset semantics (no bound needed) and counts are since start, with 7-day numbers coming from room memory.

## 10. Non-goals

Shadow or would-have-done mode, approve/undo. Writing HA automations. Rule suggestions from behaviour. Widening the
domain allowlist. Routing a triggered automation's inner calls through URA gates. New DB tables. Conditions beyond
the three in D2. Rewriting stored options in place outside the edit path.

## 11. Tier

Tier 2-DB: new persisted episode shapes and a new person-event subscription, plus operator ruling. Reviews: A =
compiler, validation, conditions, person match; B = executor integration, switch gate per trigger class,
subscriptions, options save and reload, migration; C = per-site mutation; plus framing D (INV-R1 has the
one-missed-site shape: re-enumerate every rule-derived call, pre-existing code included) and framing G (works day 1,
UI simple, no shadow). Not full Tier 3: no cost or HVAC control path; guards move unchanged. Live validation (D10) and
README write-back required.

## 12. Plan-review findings disposition

Fixed: HIGH-1 (D4, INV-R3), HIGH-2 (D1), HIGH-3 (D3, INV-R4), HIGH-4 (D5), HIGH-5 (D2); MEDIUM-1, MEDIUM-2 (D4, D1),
MEDIUM-3, MEDIUM-4 (D8), MEDIUM-5 (D3 turn-on checkbox); LOW-1, LOW-2, LOW-3, LOW-5 (D4); LOW-4 (card title) is a board
edit outside this plan's scope and is left to the coordinator. Opportunity 1 (one authoring form) taken in §7;
opportunity 2 (zero-fire) taken in D6. Declined: none.

## 13. Plan completion tracking

The build README lists D1-D10 as done, deferred (reason, card) or dropped. Carry-outs: compactor fact (D7 parked);
per-person preferences (PERSON-PROFILE-PREFERENCES-1); routing triggered automations through gates (parked).

## 14. Open questions for the operator

1. Add a dedicated Sonnet-class AI Task subentry for rule writing? Recommended: yes; until then rules use
   `ai_task.claude_ai_task`.
2. Automation rules honour the automation's own conditions by default (HA default skips them). Recommended: honour.
3. Remove rule authoring from new-room setup (rules are added from the room's options). Recommended: yes.
4. Leave the Room Rules switch as is in rooms without rules (off in 31 of 47); the save step offers to turn it on.
   Recommended: yes.

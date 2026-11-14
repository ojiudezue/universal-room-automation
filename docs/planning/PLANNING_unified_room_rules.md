# PLANNING: unified room rules (AI-described and chained)

Card: AI-ROOM-RULES-TRUST-REPAIR-1. Parent: AUDIT-ROOM-AI-AUTOMATION-CHAINING-MUSIC-1.
Related: MUSIC-FOLLOWING-TRANSFER-REPAIR-1, TRUST-APPROVE-UNDO-DIGEST-1, PERSON-PROFILE-PREFERENCES-1.
Written 2026-11-13 by ura-planner. One clean build spec. Design history (not a spec):
`DESIGN_reimagine_room_ai_chaining_music_2026_11_13.md`.

## 0. Charter (operator 2026-11-13, verbatim)

- "No shadow mode... Treat the reformulations as full blown mission critical feature that must work on day 1. My
  trust just means get it right and make sure it's tested well. No delays. This is where our features die and are not
  switched on."
- "We will fix the AI automation and the AI [chaining] and music following. We will not retire them."
- "Part of what we have to do is to figure if we can improve and simplify those three features."

Consequences: no shadow, offer or probation mode. A parsed, enabled rule runs. Trust = correct parse, one executor
with every guard, real-path tests, a live rule. Decision rows are observability only.

## 1. Institutional context verified

Read in full: CLAUDE.md, the design doc, the audit, the board cards (incl. `FINDING_ai_task_schema_2026_11_13`),
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` (complete; person-in-room comes from the BLE
resolver they describe; no §10 claim re-asserted). HVAC state-of-play not required: the climate block is kept
unchanged and no HVAC code is touched. Prior plans: `PLANNING_v3.10.0_AI_AUTOMATION.md` (design still matches code).
Memory: F1-F5 model, extend-don't-rebuild, hollow test anchors, numbers get knobs, wire-in anchors.

Prior-art scan (re-grepped on develop 00f678b9), REUSE or NEW per piece:

| Piece | Verdict | Where |
|---|---|---|
| AI rule store | REUSE | `CONF_AI_RULES` (room options; read `coordinator.py:1166`) |
| Chain store | REUSE | `CONF_AUTOMATION_CHAINS` dict trigger -> automation id (`coordinator.py:871`) |
| Trigger fan-out | REUSE | `coordinator.py:5462-5466` (room triggers), `:1014-1146` (house_state, energy, safety, security), subscriptions `:1786-1823` |
| Executor guards | REUSE (move, not rewrite) | `_execute_rule_action` `coordinator.py:1215`: allowlist `_AI_RULE_ALLOWED_DOMAINS` `:1208`, climate block, security-owned cover block (`cover_ownership.is_security_owned_cover`), LightPolicyOracle manual hold, `ura_ctx_kwargs` stamp |
| Chain executor | FOLD IN | `_fire_chained_automations` `coordinator.py:865` (state check, activity log `chain_trigger` `:905-915`) |
| Person in room | REUSE | `_get_identified_persons_in_room` `coordinator.py:1354` -> `person_coordinator.get_persons_in_room` `person_coordinator.py:2202` (alias of `get_room_occupants` `:2131`, display names) |
| Person matching | REUSE | `music_following._person_key` `music_following.py:44` |
| LLM structure pattern | REUSE | `OPTIMIZER_LLM_STRUCTURE` `const.py:5534` (text field holding a JSON array) and its parser `_extract_findings_list` `domain_coordinators/optimization_llm.py:976` (nested-vs-flat precedence, `json.loads`) |
| Rule prompt | REUSE + EDIT | `AI_RULE_PARSING_PROMPT` `const.py:4532` |
| Parsers (two copies) | MERGE | `config_flow.py:3184` `_parse_rule_with_ai_init` + `:3309` validator; `config_flow.py:15246` `_parse_rule_with_ai` + `:15368` validator |
| ai_task entity choice | REUSE | `_discover_ai_task_entities` `config_flow.py:10680` |
| Status sensor | REUSE + FIX | `AIAutomationStatusSensor` `sensor.py:2884` |
| Room AI switch | REUSE | `switch.<room>_ai_automation` (`switch.py:5723-5753`) |
| Decision log | REUSE | `activity_logger.log(...)` (as used at `coordinator.py:905-915`); no new table |
| Rule record shape, compiler module | NEW | grep `RoomRule`, `rule_compiler` in package = 0; a module holding the merged parser, validator and record adapter |

Verified fact: the current `object` + `multiple` structure is rejected live (HTTP 500 "OpenAI output schema requires
explicitly defined object fields at $.properties.actions.items"); same class as the v5.2.1 Anthropic 400 recorded at
`const.py:5523-5531`. So every rule parse has failed, which is why the one live rule (Exercise Room `6a932dd2`) is
stored `needs_parsing: true`, `actions: []`.

Config-first: the AI toggle is off in Exercise Room, but turning it on cannot help: the rule has no actions. Code is
needed.

## 2. Identity model and consumer class

A person-scoped rule consumes per-person room presence from dense BLE (PersonCoordinator room resolution; F4 shaped
from BLE, plus F1 for the tracked set). Consumer class: comfort/convenience for most domains. Rules may target
`lock` and `cover`; those stay behind the existing guards (security-owned covers blocked). This plan does not widen
what a rule may act on. It does not read F2, F3 or F5.

## 3. Falsifiable invariants

- **INV-R1 (one gate).** Every service call issued because of a room rule, whichever way it was authored, passes
  through one function that applies the allowlist, the climate block, the security-owned cover block and the light
  manual-hold oracle, in that order. Break it by finding any reachable call site that issues a rule-derived
  `hass.services.async_call` outside that function.
- **INV-R2 (no unparsed active rule).** No rule with zero valid actions is ever counted active or executed; the
  status sensor never reads `active` while any enabled rule is unparsed.
- **INV-R3 (person filter matches).** A rule scoped to `person.x` fires when person x is in the room per
  `get_persons_in_room`, in either id form, and never fires when only someone else is.

## 4. Producer and consumer checks

**Producer: parsed actions.** Fire check: zero successful parses ever on this HA (schema rejected). After D1 the
parse is measured on the live call in D7. **Producer: person in room.** `person_coordinator.get_room_occupants`
returns display names from the BLE resolver (healthy; same source as music following, 8,126 transitions in 14 d).
**Producer: triggers.** Room enter/exit fire through `coordinator.py:5462-5466`; signal triggers subscribe only
when a rule or chain needs them (`:1786-1823`), so D3's adapter must feed the same subscription check.
**Fire check, executor:** 0 chain fires and 0 AI fires in 30 days (audit). Chains configured in 0 rooms.
**Consumers:** executor actions reach real devices (trust); status sensor and activity rows are display. Forward
trace: trigger -> rule match -> person filter -> gate -> service call -> activity row. Every link is in scope.

## 5. Emission-site enumeration

Rule-derived service calls today: `coordinator.py:898` (`automation.trigger`, chain path, no guards) and the call
inside `_execute_rule_action` (`coordinator.py:1215` onward, guarded). Callers: `:1026-1027`, `:1068-1069`,
`:1107-1108`, `:1145-1146`, `:5462-5466`. After the build, `:898` is gone and all callers call one entry
`_run_room_rules(trigger)`. Builder re-greps `async_call` in `coordinator.py` and lists every site in the README.

## 6. Deliverables

### D1: one rule compiler, provider-portable structure
New module `rule_compiler.py` holds the single parser and validator used by both the init flow and the options flow
(the two copies are deleted). Structure follows `OPTIMIZER_LLM_STRUCTURE`: one field `actions_json` (text, multiline)
holding a JSON array, plus `summary` (text, one plain sentence of what the rule does). Parse with the
`_extract_findings_list` precedence (nested `data` first, then flat), `json.loads`, then strict validation: each item
has string `domain` and `service`, `target.entity_id` string or list of existing entities in this room's entity set,
`data` an object, domain in the allowlist and not `climate`, keys limited to the existing data-key allowlist next to
`OPTIMIZER_LLM_STRUCTURE` (`const.py` ~5495-5517) where applicable. The ai_task entity is the existing configured one.
- **Verify:** both flows import the same function (grep shows one definition).
- **Test:** `test_rule_compiler_parses_text_json_array`, `test_rule_compiler_rejects_climate_and_unknown_entity`,
  `test_rule_compiler_nested_and_flat_response`, `test_rule_compiler_structure_has_no_object_selector` (asserts the
  `structure` sent to `ai_task.generate_data` contains only `text` selectors).
- **Discriminates:** the old structure fails the last test; a valid parse with a foreign room entity fails validation.

### D2: never store an unparsed rule
Save is refused when the parse fails or validates to zero actions: the form shows `ai_parse_failed` with the reason
and keeps the typed text. The init-flow fallback that stored `needs_parsing` (`config_flow.py:3120-3133`) is deleted.
Before save the form shows the compiled `summary` and the action list in plain words for confirmation.
- **Test:** `test_rule_form_refuses_unparsed`, `test_rule_form_keeps_text_on_failure`, `test_rule_preview_lists_actions`.

### D3: one rule record and one executor
Record (read-time adapter, stored config not rewritten): `{rule_id, source: "ai"|"chain", trigger, person, enabled,
summary, actions[]}`. A chain entry `trigger -> automation.x` maps to source `chain`, action
`{domain: automation, service: trigger, target: {entity_id}, data: {skip_condition: <knob>}}`. One entry point
`_run_room_rules(triggers)` replaces both `_fire_chained_automations` and `_execute_ai_rules`; it keeps the chain's
order guarantee (chain-sourced rules first), the chain's "automation off or missing" skip, conflict detection
(`_last_conflicts` bounded to the last 20), and runs every action through `_execute_rule_action`.
Honest limit kept in the docstring: an automation or script triggered by a rule runs its own actions outside URA's
gates (the existing D2-LOW-1 note); the climate block covers direct calls only.
- **Verify:** INV-R1 grep: no `async_call` for rule actions outside `_execute_rule_action`.
- **Test:** `test_rules_chain_goes_through_gate`, `test_rules_chain_off_automation_skipped`,
  `test_rules_signal_subscription_from_adapter`, `test_rules_ai_light_respects_manual_hold`,
  `test_rules_cover_security_owned_blocked`, `test_rules_climate_blocked` (all drive the real coordinator methods
  with a recording services fake asserting domain, service, data, target and the context kwarg).
- **Test (Review C):** mutate each guard and the chain routing one at a time; each turns a named test red.

### D4: person filter fixed
Compare `_person_key(rule.person)` to `_person_key(p)` for each `get_persons_in_room` result. One shared helper
(import from `music_following`; when the person-awareness read API ships its one-id rule, both move together).
- **Test:** `test_rule_person_entity_id_matches_display_name`, `test_rule_person_other_occupant_no_fire`,
  `test_rule_person_empty_room_no_fire`.
- **Discriminates:** old code compares `person.oji_udezue` to `Oji Udezue` and fails the first test.

### D5: honest status and decision rows
`AIAutomationStatusSensor` states: `active` (at least one enabled, parsed rule and the room switch on), `off` (switch
off), `needs_parse` (any enabled rule has no actions), `none`. Attributes: `rules_total`, `rules_unparsed`,
`fires_7d`, `last_fire`, `last_fire_rule`, `last_skip_reason`. One activity-log row per matched rule evaluation:
`action="rule_fire"` or `action="rule_skip"` with reason (`switch_off`, `person_absent`, `gate_blocked:<guard>`,
`automation_off`). Rows go through the existing activity logger (batched queue), no new table.
- **Test:** `test_status_needs_parse_never_active`, `test_rule_fire_writes_activity_row`, `test_rule_skip_reason_row`.

### D6: migration of stored rules
On room setup, the adapter reads both keys. The Exercise Room rule (`needs_parsing`, empty actions) surfaces as
`needs_parse`, is never executed, and the options flow offers "Re-parse rule" using its stored description through
D1. The `needs_parsing` key is ignored after that (treated as unparsed if actions are empty). Chains: none stored
live; adapter covers the shape.
- **Test:** `test_migration_needs_parsing_rule_is_inert_and_flagged`, `test_migration_reparse_replaces_actions`,
  `test_migration_chain_dict_becomes_chain_rules` (fixtures copied from the live stored shape).

### D7: live validation
With the operator's ok for the paid call: re-parse the Exercise Room rule (or a new simple rule, e.g. "when I enter
after dark, turn on the lamp"), turn on the room AI switch, walk in.
- **Live:** parse returns actions (no 500); status `active`; light changes; one `rule_fire` activity row with the rule
  id; a person-scoped rule fires for that person and not for another; a chain to a test automation fires once and
  writes a row.
- **Discriminates:** a rule that ran through a bypass path writes no `rule_fire` row; an unparsed rule shows
  `needs_parse`, not `active`.

### D8: tests replace replicas, docs
Delete the inline replicas in `test_ai_automation.py` and `test_automation_chaining.py` (keep any case worth keeping as
a real-path test). Keep the existing real-path anchors (`test_room_covers_garage_guard.py`,
`test_hvac_w1a_site_migration.py`, `test_lighting_slice_c_manual_hold.py`). Update `PLANNING_v3.10.0_AI_AUTOMATION.md`
pointer and the coordinator doc for room rules.

## 7. Numbers get knobs

| Knob | Rung | Default | Why / kill semantics |
|---|---|---|---|
| `skip_condition` per chain rule | 2 (room options) | False | honour the automation's own conditions; True = old bypass |
| `RULE_CONFLICTS_KEEP` | 1 | 20 | memory bound for `_last_conflicts` |
| `RULE_STATUS_FIRES_WINDOW_DAYS` | 1 | 7 | window for `fires_7d` |
| `RULE_PARSE_TIMEOUT_S` | 1 | 30 | form never hangs on a slow provider |
| `ROOM_RULES_UNIFIED_EXECUTOR` | 1 | True | kill switch to the pre-change two-path behaviour, review-gated |

## 8. Non-goals

Shadow or would-have-done mode, approve/undo, weekly digest (TRUST-APPROVE-UNDO-DIGEST-1). Writing HA automations.
Rule suggestions from behaviour. Widening the domain allowlist. Routing chained automations' inner climate calls
through HVAC funnels (parked upgrade). New DB tables. Rewriting stored options in place.

## 9. Tier

Tier 2-DB strength by operator ruling: three framing-disjoint reviews, A = parse, validation and person match
correctness, B = executor integration, trigger subscriptions, options-update and reload lifecycle, migration of stored
shapes, C = per-site source mutation on every guard and the chain route. INV-R1 has the one-missed-site shape, so
add a Tier 3 element: a framing D adversarial completeness pass that re-enumerates every rule-derived call site,
including pre-existing code. Framing G (goal fidelity) is mandatory. Live validation and README write-back required.
Full Tier 3 not warranted: no cost or HVAC control path changes, and the guards are moved, not rewritten.

## 10. Plan completion tracking

The build README lists D1-D8 as done, deferred (reason, card) or dropped. Known carry-outs: approve/undo and digest
(TRUST-APPROVE-UNDO-DIGEST-1); per-person rule preferences (PERSON-PROFILE-PREFERENCES-1); chained climate routing
(parked).

## 11. Open questions for the operator

1. OK to make the paid `ai_task` call for D7, and on which entity (default `ai_task.claude_ai_task`)?
2. Chains: default `skip_condition: False` (automation's own conditions apply). Agree?
3. The room AI switch is off in 31 of 47 rooms. Leave as is, or turn it on house-wide once rules work? Plan leaves it.

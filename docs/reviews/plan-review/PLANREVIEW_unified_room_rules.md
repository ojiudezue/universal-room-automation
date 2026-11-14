# Plan review: PLANNING_unified_room_rules.md (AI-ROOM-RULES-TRUST-REPAIR-1)

Reviewed on develop @ 434a7aae, 2026-11-13. Plan review, not code review. No pytest run. I read the
plan, the card (operator_2026_11_13_decision, _mission_critical, FINDING_ai_task_schema_2026_11_13,
delivery_2026_11_13) and the cited code. I did not read the HVAC or presence state-of-play docs: no HVAC
code is touched, and the person-presence findings below rest only on the cited person_coordinator code.

**Verdict: FIX-PLAN.** The plan has no CRITICAL findings, and its INV-R1 call-site enumeration is
correct. Five HIGH findings remain. Three are goal-fidelity gaps: rules that save cleanly can still fail
to do what the operator said. Two are spec ambiguities that a builder will resolve wrongly.

---

## Framing 1: adversarial completeness and build-prediction

### Re-enumeration (independent greps)

Rule-derived service calls, the whole package (`grep -n async_call`, `_execute_rule_action`,
`_fire_chained`, `CONF_AI_RULES`, `CONF_AUTOMATION_CHAINS` across `*.py`, `domain_coordinators/`,
`services.yaml`):

| Site | What | Guards today |
|---|---|---|
| `coordinator.py:897` | `automation.trigger` (chain) | none (only the state on/off check at :884) |
| `coordinator.py:1346` | inside `_execute_rule_action` | allowlist :1234, climate :1259, security cover :1279, light hold :1300 |

Callers: `:1026-1027`, `:1068-1069`, `:1107-1108`, `:1145-1146`, `:5462/:5466`. No button, service,
or `services.yaml` path and no other module calls either executor. **The plan's §5 list is complete.**
Rule readers: `coordinator.py:1015,1056,1094,1132,1166,1787`, `sensor.py:2903-2918`,
`binary_sensor.py:1503-1508` (conflict binary sensor). Writers: `config_flow.py:3006-3015` (init chains),
`:3115-3132` (init rules, including the needs_parsing fallback), `:14965-14978` (options chains),
`:15064-15079` (options rules), plus the `ai_rule_delete` step.

The plan's guard order (allowlist, climate, cover, hold) matches the code. The REUSE citations hold:
`_person_key` `music_following.py:44`, `_extract_findings_list` `optimization_llm.py:976`,
`OPTIMIZER_LLM_STRUCTURE` `const.py:5534`, `_discover_ai_task_entities` `config_flow.py:10680`. The
structure pattern matches: one `text` multiline field with a JSON string, read container-first and
then `json.loads`.

### Findings

**HIGH-1. The AI switch gate is not uniform across triggers, and the plan's single entry point would
erase that difference.** `coordinator.py:1017` (house_state), `:1058` (energy) and `:5455` (room
triggers) require `_is_ai_automation_enabled()`. Safety `:1096-1097` and security `:1134-1135`
deliberately fire **regardless of the switch** (Review fix F11). `_is_ai_automation_enabled` also
returns False under ManualMode (`:3261`). D3's single `_run_room_rules(triggers)` and D5's `switch_off`
skip reason do not say where the gate lives. A builder who moves the gate inside `_run_room_rules` will
silently drop the safety and security exemption. The plan must state the gate per trigger class, add a
test for each (`test_rules_safety_fires_with_switch_off`, `test_rules_enter_skipped_with_manual_mode`),
and give D5 a `manual_mode` skip reason.

**HIGH-2. "Room entity set" is undefined, and the data-key allowlist would remove data from legitimate
rules.** D1 says targets must be "existing entities in this room's entity set" and that keys are limited
to `OPTIMIZER_LLM_SERVICE_DATA_ALLOWED_KEYS` (`const.py:5496`) "where applicable."
(a) Two different sets exist today. The prompt list (`config_flow.py:3263-3287`: configured devices
plus the climate entity plus every entity in the HA area) and the validator (`:3329-3333`: any entity
that exists in HA) do not agree. The plan must name the prompt list as the set and say that the chain
target, any `automation.*`, is exempt.
(b) That allowlist has no `volume_level`, yet the prompt itself requires it (`const.py:4553`). It also
lacks fan `percentage`, `oscillating` and `direction`, `media_content_id`, `source`, `color_name`, and
the chain record's own `skip_condition` (D3). If the allowlist is applied, "set the fan to 50%" saves
and then runs with its data stripped, or the chain record fails its own validator. Rules would look
like they work and still do the wrong thing. Fix: a rule-specific key allowlist per domain, as a
rung-1 constant, with rejection rather than silent dropping, and a test per domain.

**HIGH-3 (build-prediction). D2's summary must not come from the LLM.** D1 makes `summary` an LLM
output field, and D2 shows it for confirmation. The model can write "turns on the lamp when you enter
after dark" while `actions_json` holds a bare `light.turn_on`. The confirmation would then state
something false, which is the exact trust failure this card exists to fix. The preview must be rendered
by code from the validated actions (domain, service, entity friendly names, data). The LLM summary can
be shown as secondary text at most. The test must discriminate:
`test_rule_preview_renders_from_actions_not_summary`.

**MEDIUM-1. `_last_conflicts` semantics change without a named consumer.** Today the list is reset on
every matching evaluation (`coordinator.py:1177-1178`). The plan says "bounded to the last 20", which
reads as accumulating. `binary_sensor.py:1503` (`_conflict_detected`) is a consumer the plan does not
list. Accumulating would make that binary sensor sticky. The plan should state whether the reset stays,
or that the binary sensor clears on the next clean evaluation, and test it.

**MEDIUM-2. The manual-hold gate covers only `light|switch` with `turn_on|turn_off`
(`coordinator.py:1295-1299`).** `light.toggle`, `scene.turn_on` (scenes holding lights) and
`automation.trigger` all skip it. INV-R1 says "applies ... the light manual-hold oracle", which
overstates it. Either reword INV-R1 to "applies when the domain/verb is gated", or have the compiler
reject `toggle` for light and switch. The rejection is cheap and closes one bypass. Note scene and
chain in the honest-limit docstring next to D2-LOW-1.

**MEDIUM-3. D6 does not name where the Exercise Room rule is stored or what "both keys" means.** The
init flow writes rules into `self._data`, which becomes `entry.data` (`config_flow.py:3130-3132`). The
options flow reads options and falls back to data (`:15064-15068`). The Re-parse step must use that
same fallback and write to options. Otherwise it creates a second list and the old rule stays in
`entry.data`. "Both keys" should be spelled out (`CONF_AI_RULES` plus `CONF_AUTOMATION_CHAINS`, read
from options then data). The new Re-parse step also needs `strings.json` and translations entries, and
the plan does not list them.

**MEDIUM-4. Signal subscriptions after an options change.** The adapter must feed `:1786-1788`. The
plan does not check that adding a rule (an options update) re-runs that subscription builder through
the room reload or in-place path. Name the path and test it: a newly added `energy_constraint` rule is
subscribed without a restart.

**LOW-1.** The plan's record calls the field `trigger`, but stored rules use `trigger_type`. Say so
explicitly in the adapter spec.
**LOW-2.** Chain execution changes from parallel `gather` with `blocking=False` (`:895-920`) to
sequential calls through the gate. That is fine, but the plan should say order and non-blocking are
kept.
**LOW-3.** The `chain_trigger` activity action is replaced by `rule_fire`. State that no reader filters
on `chain_trigger` (I found none in the package).
**LOW-4.** The card title still says "shadow would-have-done log", which contradicts
`delivery_2026_11_13`. Retitle it on the board.
**LOW-5.** `skip_condition` default False is a behaviour change: HA's `automation.trigger` default is
True, so today conditions are skipped. The knob table says this correctly. Repeat it in the README.

Knob ladder: every number has a rung and a reason. `RULE_PARSE_TIMEOUT_S` needs a named call site, the
`ai_task` call wrapped in `asyncio.timeout`. The `ROOM_RULES_UNIFIED_EXECUTOR` kill switch keeps the
unguarded chain path reachable. It should come with a test proving the default path is the unified one.

---

## Framing G: goal fidelity

Operator's goal: rules that work on day 1 when switched on, with AI rules and chaining fixed and
simplified, and no shadow mode. The plan honours "no shadow". The merge is real: one record, one
executor, one row type. The two authoring flows are now just two inputs to it. The items below fail
the day-1 test anyway.

**HIGH-4. Person-scoped `enter` and `exit` rules are likely never to fire, even after the D4 fix.** The
trigger is the occupancy transition (`coordinator.py:5444-5448`, mmWave or motion). The person filter
reads BLE room resolution at that instant (`person_coordinator.py:2172-2186`, exact room match and
confidence ≥0.3). On `enter`, BLE typically resolves after occupancy, so the person is not yet in the
room and the rule skips with `person_absent`. On `exit`, the person has already left or is about to,
so a rule like "when Oji leaves, turn off X" cannot match. D4's tests are static and cannot catch this.
The fix improves on the plan: a person-scoped rule should trigger on the person's room transition event
(`ura_person_location_change`, the event music following already consumes), with the person carried in
the event, not looked up afterwards. Alternatively, measure first: a recorder probe of occupancy-on
versus BLE-room-arrival lag over 14 days. Add `test_rule_person_enter_fires_on_person_transition`.

**HIGH-5. Rules have no conditions, so ordinary sentences compile to wrong rules.** The plan's own D7
example, "when I enter after dark, turn on the lamp", cannot be expressed. The record is trigger plus
person plus actions. "After dark" is dropped, and the lamp turns on at every entry. Together with HIGH-3
this produces a rule that the operator confirms and then distrusts. The minimum: the compiler returns
`unsupported_conditions` (an extra text field), and the form refuses the save or names what was dropped.
Better, for the same cost: a small condition set the executor already has data for (`lux_dark`/
time-of-day window, house_state in {...}, person present), checked in `_run_room_rules`. Pick one in
the plan. Do not leave it to the LLM.

**MEDIUM-5. Switched off by default means the feature never runs.** The room switch is off in 31 of 47
rooms (§11 Q3), including the one room with a live rule. Under "this is where our features die and are
not switched on", a rule saved in a room whose switch is off should either turn the switch on with the
save (shown in the confirmation) or block the save with a clear message. Leaving it as an open question
reproduces the failure the operator described.

**Opportunities (not defects):** (1) Chains could be authored as natural-language rules ("on enter,
run automation X"), so there is one authoring form, not two. (2) The D5 `fires_7d` and `last_skip_reason`
attributes plus a zero-fire NM trip-wire per enabled rule (fire-check rule) would make silence visible
in code.

No risk reduction in the plan changes what is delivered. The non-goals (approve/undo, digest) are carded.

---

## Summary

| Sev | Count | IDs |
|---|---|---|
| CRITICAL | 0 | |
| HIGH | 5 | HIGH-1 switch-gate per trigger, HIGH-2 entity set and key allowlist, HIGH-3 LLM-written preview, HIGH-4 person enter/exit timing, HIGH-5 no conditions |
| MEDIUM | 5 | conflicts semantics, hold-gate scope, D6 storage location, subscription refresh, switch-off default |
| LOW | 5 | |

Verdict: **FIX-PLAN**. Fix HIGH-1 through HIGH-5 in the plan, then dispatch the build.

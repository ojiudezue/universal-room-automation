# Room rules (described rules and "run an automation")

Card AI-ROOM-RULES-TRUST-REPAIR-1, plan `docs/planning/PLANNING_unified_room_rules.md`. Replaces the v3.10 automation
chaining and v3.12 AI rules executors (`PLANNING_v3.10.0_AI_AUTOMATION.md` is historical). Code wins over this doc.

## One record

A rule is one record in `CONF_AI_RULES` (room entry options; read options then data):
`{rule_id, source: "described" | "automation", trigger_type, person, conditions, actions, enabled, description,
summary, created_at, automation_entity?, skip_condition?}`. Legacy `CONF_AUTOMATION_CHAINS` bindings are read by the
adapter (`rule_compiler.adapt_rules`) as `automation` rules (`automation.trigger`, `skip_condition` False: the
automation's own conditions apply; HA's default is True). Stored config is not rewritten except on the edit path, which
writes the full list to options and folds the chains in. A rule with no well-formed action, a `needs_parsing` flag, or
one that lives only in `entry.data` (the retired room-creation flow) is `needs_parse` and never runs.

## Authoring (room options, "Room rules")

- **Describe a rule**: text + When + Only for. `rule_compiler.compile_rule` makes ONE `ai_task.generate_data` call
  (TEXT-only structure `ROOM_RULE_STRUCTURE`: `actions_json`, `conditions_json`, `unsupported`, `summary`) on the
  entity in `CONF_ROOM_RULES_AI_TASK_ENTITY` (CM options, "Rule writing model", default `ai_task.claude_ai_task`;
  empty = HA default), inside `asyncio.timeout(RULE_PARSE_TIMEOUT_S)`. Strict validation: targets in
  `room_entity_set` (configured devices + climate + HA area; `automation.*` / `scene.*` may be any existing entity),
  allowlist minus climate, no `toggle` on light/switch, data keys per `ROOM_RULE_DATA_KEYS` (unknown key rejects).
  Failure kinds: `model_unavailable` (call failed / entity unavailable / timeout; wording kept, names the model),
  `parse_failed`, `unsupported` (named). Nothing is saved on a failure.
- **Run an automation**: When + Only for + automation + "Use the automation's own conditions". No model call.
- **Check your rule**: preview written by code from the stored record (`render_rule_preview`; the LLM summary is never
  shown as what the rule does). If the room's Room Rules switch is off, a "Turn on room rules" box (default on) turns
  the switch (registry unique id `{entry_id}_ai_automation`) on with the save.
- **Your rules**: preview + status; turn off/on, re-check from its wording, change the wording, delete.

## Running (`UniversalRoomCoordinator._run_room_rules`)

Callers: occupancy enter/exit and lux edges (`_async_update_data`, inside the master-automation branch), house state,
energy, safety, security signal handlers, and the person room-change listener. Order per rule: match, switch gate,
person, conditions, actions. Every action goes through `_execute_rule_action` (allowlist, climate block,
security-owned cover block, light manual-hold oracle). Switch gate: `ROOM_RULE_SWITCH_EXEMPT_TRIGGERS` (safety,
security) always run; others need Manual Mode off (`manual_mode`) and the Room Rules switch on (`switch_off`).
Conditions: `after_dark` (`automation.is_dark`), `time_window` (local, may cross midnight), `house_state_in`.
Person-scoped enter/exit rules fire only on `ura_person_location_change` for this room (person from the event, matched
with `person_ids.slug_of`; one bus listener per room, only when such a rule exists); other person-scoped rules check
`get_persons_in_room`. Saved rules never call the model, so they keep running while it is unavailable. Kill switch
`ROOM_RULES_UNIFIED_EXECUTOR` (False = old two paths, still through the gate). Honest limit: an automation, script or
scene a rule triggers runs its own actions outside URA's gates.

## Observability

- One INFO `Room rule decision` line per matched rule (room, rule_id, source, trigger, person, outcome, guard,
  conditions with values, actions, ms) and one `room_rule_decision` memory row (`room:<slug>`).
- `sensor.<room>_ai_automation_status` ("Room Rules Status"): `none` / `manual_mode` / `off` / `needs_parse` /
  `active`; attribute `rules` (preview, status, fires, skips_by_reason, last_fire, last_skip_reason, reversals; since
  start; unrecorded).
- Reversal within `RULE_REVERSAL_WINDOW_S`: a person's opposite change of a room light (from
  `ActuatorReconciler._note_manual_light_change`) or a non-URA change of another target -> `room_rule_reversal` row.
  `sensor.ura_room_rules_accuracy` (CM device): 7-day percent not reversed, nightly.
- Digest line (NM): "Room rules, last 24 h: ...".
- Nightly `run_room_ai_health_check`: accuracy roll-up + `room_rule_silent` HIGH page for an enabled, parsed,
  non-safety rule older than `RULE_ZERO_FIRE_DAYS` with evaluations and zero fires.

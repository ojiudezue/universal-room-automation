# Closure plan review: unified room rules (2026-11-20)

Plan `docs/planning/PLANNING_unified_room_rules.md` (51bbba77) vs `PLANREVIEW_unified_room_rules.md` (900e51f9).
Framings: completeness, build-prediction, goal fidelity. HVAC/presence state-of-play docs not reopened: plan touches
neither HVAC control nor presence producers; it consumes `ura_person_location_change` only.

**Verdict: PLAN-FIX-REQUIRED** (one HIGH, small edit).

## Prior HIGH closures
HIGH-1..5 closed in spec text: D4/INV-R3 (gate per trigger, `manual_mode` reason, tests), D1 (room entity set +
per-domain `ROOM_RULE_DATA_KEYS`, reject not drop), D3/INV-R4 (code-rendered preview, discriminating test), D5
(person event; fields `person_id/previous_location/current_location` confirmed `person_coordinator.py:1123-1137`),
D2 (three conditions + `unsupported` refusal). Semantics still hold on develop.

## Findings
- **HIGH: no AI-unavailable degrade path.** D3 refuses save on any parse failure; it does not separate "model
  unavailable" (API locked until 12-01, ANTHROPIC-API-USAGE-LIMIT-OC-LLM-1) from "could not understand". Add: an
  explicit `model_unavailable` form error naming the entity, typed text kept, stats/status unaffected for stored
  rules, test `test_rule_compiler_ai_task_error_is_model_unavailable`. D10 cannot run on `ai_task.claude_ai_task`
  before 12-01: state the pre-12-01 validation (stubbed compiler in-suite + "Run an automation" path live, which needs
  no LLM; or another `ai_task` entity via the knob) and defer the paid-parse rows to 12-01.
- **MEDIUM: stale anchors** (develop moved ~+38..+590 lines): `_fire_chained_automations` now `coordinator.py:903`
  (call `:936`), `_execute_ai_rules :1198`, `_execute_rule_action :1253`, `_is_ai_automation_enabled :3834`
  (manual `:3842`), room trigger gate `:6043`, energy `:1096`, safety `:1133-1146`; options parser `config_flow.py:15686`
  (call `:15732`), init parser `:3237/:3286`; `_person_key` `music_following.py:68`. Builder must re-grep.
- **LOW: prior art.** Knob picker should reuse `_discover_ai_task_entities` (`config_flow.py:11114`); person match
  should call `person_ids.slug_of` directly, not a private music_following helper.
- **LOW:** room match on the event's `current_location` is a room display name; specify comparison against the
  entry's own room name (URA-owned data, registry rule satisfied).

# URA v5.2.1 — Optimization LLM structured-output schema hotfix

**Release date:** 2026-06-09
**Tier:** Hotfix (Tier 1) — isolated to the Phase-2 LLM tier I/O; verified live against the Anthropic backend before ship.
**Trigger:** Post-deploy validation of v5.1.0/v5.2.0 surfaced an Anthropic 400 in the `optimization_llm` log:
`output_config.format.schema: For 'object' type, 'additionalProperties: true' is not supported. Please set 'additionalProperties' to false`.

## Root cause
`OPTIMIZER_LLM_STRUCTURE` used the HA `ai_task` `object` selector (`{"object": {"multiple": True}}`) for the `findings` list. HA's `ai_task` converts that to a free-form object schema (`additionalProperties: true`), which Anthropic's strict structured-output API rejects. Result: every LLM-tier invocation on `ai_task.claude_ai_task` failed with a 400. At L1 Shadow this degraded gracefully (the tier caught it and returned no findings; the deterministic tier was unaffected), so no behavioral harm — but the LLM path was non-functional.

## Fix
- `OPTIMIZER_LLM_STRUCTURE` now returns `findings_json` — a **`text` field holding a JSON-array string** — plus `reasoning` (text). This avoids the free-form object schema entirely and is provider-portable (no per-backend object-schema quirks). **Verified live against `ai_task.claude_ai_task`** before coding: the JSON-string structure is accepted and returns `{"findings_json": "[{...}]", "reasoning": "..."}`.
- `_extract_findings_list` now `json.loads` the `findings_json` string (graceful empty on malformed JSON), with backward-compat for a plain `findings` list.
- Test helper `_llm_make_response` updated to emit the production `findings_json` shape, so all 19 LLM tests drive the real parse path (#44). New regression test `test_optimizer_llm_findings_json_string_parsed` covers the string-parse, malformed-string, and legacy-list cases.

## Validation
- 85/85 optimizer tests pass (was 84 + 1 new).
- Live: the corrected structure was confirmed accepted by Anthropic via a direct `ai_task.generate_data` probe.

## Live Validation (Review D) — post-restart
- **Verify:** the `ai_task.generate_data failed ... additionalProperties` WARNING no longer appears in the `optimization_llm` log after a cycle fires the LLM tier.
- **Verify:** `optimization_findings` gains `created_by=tier2_llm` rows once a finding-set delta triggers an LLM cycle (L1 Shadow — scored, not actuated).

| Criterion | Observed | Source |
|---|---|---|
| (TBD post-deploy) | | |

# AUDIT: does AI Task make the Optimization Coordinator better? (OC-AI-TASK-LEVERAGE-1)

Date: 2026-11-14 02:10 CST. Read-only probe (ura-prober). No LLM calls made. Window: 14 d to 2026-11-14 08:06 UTC.
Sources: URA DB `optimization_findings` / `optimizer_shadow_samples` (ssh ha sqlite3 -readonly), `~/ha-config/.storage/core.config_entries`, recorder `states`, code at cited file:line.

## Verdict
AI Task is NOT the lever. The failures are DESIGN-limited (deterministic tier-1 noise, no graded feedback) and INPUT-limited (the LLM is fed a corpus that hides the facts it then complains about). A better model would not fix either. Structured output is already used. Highest leverage: dedup/persist tier-1 problems and grade the shadow (redesign card), then fix the corpus the model sees (context-pack card).

## 1. Where OC fails (numbers)
Findings, 14 d: 1,357 rows (1,389 all-time since 10-20) (`optimization_findings`).
| Bucket | Rows | Note |
|---|---|---|
| tier1 room | 788 | |
| tier1 house | 503 | |
| tier2_llm (house 41, room 25) | 66 | 4.9% of volume reach/come from the LLM tier |
| outcome shadow_dry_run | 1,141 | never acted |
| below_confidence_gate | 171 | |
| advisory_only | 77 | |
| proposed_action_json non-null | 0 (all rows) | zero findings ever proposed an action; nothing to execute or grade |
| action_class set | 0 / 1,357 | |
| optimizer_shadow_samples | 0 rows | the track record is empty (schema: observed_at, dimension, target_id, matched) |

Tier-1 is repeats: 387 distinct (description,target) among 1,357 rows (3.5x repetition). Top repeaters: "1 lock(s) unlocked while house state is sleep" x225, "Master Bedroom motion/mmwave active but occupancy sensors report clear" x154, "...unlocked ... away" x95, mmwave gameroom "stuck missing" x41, Guest Bedroom 1 temp x31, `meta cycle_ok` x28. By dimension x severity: comfort/medium 450, security_posture/high 349, sensor_health/high 322, occupancy_accuracy/low 154. Findings/day rose 61 (11-09) to 322 (11-13): volume growing, not shrinking.

LLM tier calls: there is NO call log, counter, latency or token table (grep of `optimization_llm.py` shows only `_LOGGER` lines; `_premium_invocations` is in-memory, seeded from findings rows at :503). Zero-finding calls leave no trace. Journal grep over 3 d returned 0 lines (HA logs not reachable that way here), so error rate, latency and tokens are UNKNOWN. What is measurable: 66 LLM findings across 61 distinct cycles in 14 d, 0.73 mean confidence (0.35-0.85); 10 critical + 2 shadow_dry_run critical; cap is 24 premium calls/24 h (`const.py` DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H, ~5548). Newest tier2_llm row is 2026-11-09 01:33 UTC while tier-1 kept producing; no LLM findings in 5 days. Cause UNKNOWN (delta gate `optimization_llm.py:324-345`, cap, or parse-empty `:405-415` all return [] silently). That silence is itself a finding (no zero-fire trip-wire). Note `ai_task.claude_ai_task` state changes 288 times since 11-06 in the recorder, but other consumers share the entity, so this is not attributable to OC.

Config actually in force: URA options carry no `optimizer_llm_*` keys (grep of core.config_entries), so defaults apply: entity `ai_task.claude_ai_task`, triage entity "" (no local triage tier active). Claude AI Task subentry: claude-haiku-4-5, max_tokens 4096, thinking_budget 1024, prompt_caching automatic, web_search/web_fetch/code_execution on (core.config_entries, ai_task_data subentry). Ollama AI Task qwen3:4b-instruct exists but is unused by OC.

## 2. Failure classes
| Class | Evidence | Limit |
|---|---|---|
| Corpus hides what the model then flags | 41 of 66 LLM rows mention truncation/empty/"cannot identify": e.g. 293392 "findings corpus truncated (0 of 31 recent findings shown), blocking diagnostic visibility"; 293354 "findings_recent truncated to 0/29"; 293507, 293440; 293394/293497 "Bayesian accuracy tracking empty". Corpus hard cap = 8000 tok x 3 chars = 24 KB (`const.py` ~5563-5564; `optimization_llm.py:94-95`), trims `findings_recent` first (:221). The model reports the trimming as a defect. Card OPT-META (kanban.data.yaml ~120-127) records 9/9 critical META findings false in 30 d | INPUT |
| LLM misreads absence as failure | 291056, 291386, 293366, 293470: "All 27/28 rooms occupied=false on Friday 14:23 ... occupancy logic failed system-wide" (critical, 0.85, shadow_dry_run). The snapshot gave per-room score/occupied flags but no house state/who-is-home, and the operator was travelling (memory 10-14, 11-09) so empty rooms were correct. 6 rows contain "occupied=false" | INPUT |
| Score-only reasoning | 293486, 293375, 291380: "Garage B score 70, lowest" with no cause. The model sees scores, not the underlying dead sensors (garageb temp/hum unavailable x17 each in tier-1 rows). Tier-1 already knew; the LLM re-derives a vaguer version | INPUT + DESIGN |
| Deterministic repeats | 3.5x row repetition; lock-unlocked-in-sleep x225 with no dedup across cycles; never-fires dedup resets on restart (kanban residual 10-21 on OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1) | DESIGN |
| Never acts, never graded | 0 proposed actions, 0 action_class, 0 shadow samples. Validator checks only the current 5-min cycle for rows >=15 min old (OC-SHADOW-SAMPLES-EMPTY-1 problem text, kanban.data.yaml ~1437). Operator 10-16: shadow was a deliberate trust withhold due to noise (:1361) | DESIGN |
| Model-limited | I found no row where the stated fact was in the snapshot and the model got it wrong. Haiku-4.5 outputs are well-formed and coherent; errors are inference from missing facts. Weak evidence only: nothing was graded, so absence of model-limited cases cannot be proven | (none shown) |

Producer/consumer: tier-1 producer = deterministic rules in `optimization.py`; LLM producer = `optimization_llm.py` run_cycle; both feed `_consider_apply` chokepoint (:416-431) and consumers are the advisory/NM page path and `shadow_dry_run` log. Forward trace: no finding reaches an action (0 proposed_action_json), so no producer drives anything.

## 3. Structured output
Yes, uses ai_task `structure` (`optimization_llm.py:911-922`). Schema `OPTIMIZER_LLM_STRUCTURE` (`const.py` ~5622) is one `text` field `findings_json` holding a JSON-array STRING plus `reasoning`. Reason (v5.2.1, 216f1a1b): the `object` selector produced `additionalProperties: true`, rejected by Anthropic with a 400. So the schema enforces only "a string"; inner fields are validated by hand-written `_parse_findings` (:1011) / `json.loads` in `_extract_findings_list` (:976-1001). Parse-failure evidence: none measurable (warning "findings_json was not valid JSON" is log-only, logs unreachable; DB has 66 well-formed LLM rows, all fields populated). Possible improvement: a nested schema with explicit object/array selectors that avoids free-form `object` could enforce enums; no data says parse failure is a real loss today.

## 4. Verdict and levers
Is AI Task (model, structure, context) the lever? Context is a lever, model and structure are not.
1. Redesign card (OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1, first slice, absorbs OC-SHADOW-SAMPLES-EMPTY-1): persistent dedup of tier-1 problems (1,357 rows to roughly 387 distinct) and a validator that scores findings against later ground truth. Without a graded signal no model can be judged or promoted. Highest value, no LLM cost.
2. Context-pack card (OC-CONTEXT-PACK-1, PLANNING_oc_live_eval_and_context_pack.md): give the LLM the facts it lacks (house state/who is home, the already-known tier-1 reasons, never trimming findings_recent to 0, the HVAC/house invariants), and stop it from critiquing its own corpus. Also add a lightweight call log (cycles, empty returns, parse errors, tokens) and a zero-fire trip-wire; investigate the 11-09 LLM silence.
3. This card (OC-AI-TASK-LEVERAGE-1): do not spend on a model swap yet. Re-enter after (1) and (2) produce a graded set.

Out-of-scope paid bake-off must answer what the data cannot: (a) whether a stronger model (Sonnet/Opus vs Haiku-4.5, with/without thinking) diagnoses the 6-8 known incidents correctly once context is fixed (M1-M8 per the planning doc); (b) real token/latency/cost per call (not logged); (c) schema-enforced nested output vs string-JSON parse reliability; (d) whether qwen3:4b triage can gate calls without losing true positives. Only (a) needs the context pack first, otherwise it measures the same input defect.

Falsifier I tried: find an LLM row where the needed fact was present in the corpus and the model still erred. Not found (nothing graded; the 41 truncation rows and the empty-room rows trace to missing inputs). A bake-off producing such rows would overturn the INPUT-limited conclusion.

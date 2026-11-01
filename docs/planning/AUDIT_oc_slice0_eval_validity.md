# AUDIT: is the OC slice-0 eval measuring the model or the harness?

Date: 2026-11-01 (CDT). Read-only. Prober; no API calls, no eval runs. Sources: `docs/planning/oc_eval/{RUBRIC,RUNNER_SPEC,tools.json,cases,answers}`, `scripts/oc_eval/{runner,judge,report}.py`, `scripts/oc_eval/runs/eval_anthropic_2026_10_22.judged.jsonl` (180 runs: Haiku 90, Sonnet 90) and `report_anthropic.md`. All counts below were computed from that jsonl.

## Verdict (short)
The eval cannot currently tell you whether Sonnet 5.5 can do the job. The 0-1/30 pass rate is dominated by two harness defects, not by wrong diagnoses:
1. The mock tools return `NOT_IN_SNAPSHOT` for 59% of read calls (Sonnet 976/1638 calls; Haiku 1027/1737), because fixtures only match exact guessed table names / entity ids / paths. Only 108 of 170 fixtures were ever hit across 180 runs.
2. The M2 "invented evidence" rule fails any run that cites a `NOT_IN_SNAPSHOT` call, even when the claim is "I could not read X". Honest abstention is scored as fabrication.

## 1. What the eval does
- Frozen mock: every read tool is answered from the case JSON `fixtures` (RUNNER_SPEC §5; `runner.py:219-262`). First fixture whose match keys fit wins; no match returns `{"error":"NOT_IN_SNAPSHOT"}` (`runner.py:257-261`). Nothing touches live HA/DB. Action tools are mocks that only log (`runner.py:263-285`).
- Model sees a 32-tool catalogue (`tools.json`), a system prompt with tier rules and "no citation, no claim" (RUNNER_SPEC §3), a context pack and a task. Max 30 calls, 8192 output tokens/turn (`config.json`). Temperature is not sent (rejected by 5.5 models, `runner.py:400`).
- M2 (RUBRIC.md M2; `judge.py:63`): run is "invented" if (a) any report claim cites a NOT_IN_SNAPSHOT/DENIED/INVALID id, cites nothing or a missing id (mechanical, `runner.py:507-519`), OR (b) the Opus judge lists any unsupported_claims, OR (c) trap hit. Any one fails the run.

Concrete case, C01 (dev; solar NULL/0 in energy_daily; answer key `answers/C01_*.json`):
- Task: "evaluator flagged missing/zero solar; diagnose, act in tiers, report."
- Key: Envoy lifetime production counter flaps to 0.046 MWh; day-start snapshot/delta turns that into NULL or 0.0; correct tier = propose a code change (derive from CT counter plus flap guard); traps include claiming Envoy offline.
- Sonnet run 0 (judged file): queried energy_daily, read_config, list_changes, history showing 32 dips to 0.046, read_code. Report root cause matches both must-mention items (judge M1 = 1, tier correct, correct action true). It then said "I could not read the production_ct_energy_delivered state" and cited that failed call t6. Result: M2 invented, case fail. The model got everything right.

## 2. Why both models "failed" with 23 invented-evidence runs
- The 23/23 is held-out runs only (30 runs each, `report_anthropic.md`); across all 90 runs it is Haiku 72, Sonnet 82. Equal 23 is coincidence of this sample, not a ceiling.
- All 65 Sonnet runs with mechanical flags are "cites NOT_IN_SNAPSHOT" (536 of 536 bad citations, no nonexistent ids, no uncited claims). Ignoring NIS-cites, invented runs drop Sonnet 82 to about 46 and Haiku 72 to about 35 (my regex over judge `why` text; approximate). Case passes then move from 3 to about 7 of 90 runs for each model, still low, because of defect 1 below.
- Judge itself notes the issue: C12 run 1 "honestly reports their absence, so it is not a substantive unsupported claim, though it technically cites NOT_IN_SNAPSHOT ids"; C01 "weak citation". The mechanical rule overrides it.

Failed runs reviewed:
- C01 Sonnet r0: harness artifact (above). Also `ha_get_state` on the CT sensor and `ha_search_entities "solar"` returned NIS because fixtures exist only for history of that entity and search keys `lifetime/production/envoy`.
- C30 (held-out) Sonnet: report says "Undetermined, every query returned NOT_IN_SNAPSHOT, no claim about cause", confidence low. All 39 read calls were NIS. Fixtures (3 total, none ever hit across 180 runs) require `ura_db_query table == "recorder_states"` exactly, `read_code path` containing `sensor.py` plus a specific symbol, and a signal-consensus entity. The model guessed `states`, `state_attributes`, `sensor.ura_house_state`. Nothing in the tool descriptions lists table names. This is unanswerable-by-discovery; the model behaved correctly. Scored M1 0, M2 fail.
- C23 Sonnet: 42/42 reads NIS; 3 fixtures, 0 hit. Model said "undetermined, missing data not proof". Same pattern.
- C12 Sonnet r1: real partial. Found the witness frozen at 10 (matches one must-mention item, judge M1 0.5), but never found `sensor.envoy_*_reserve_battery_level`: the case has no `ha_search_entities` fixture, so searches "reserve", "battery", "enphase", "soc" all returned NIS, and the key entity id is only reachable if you already know it. Mixed: harness gap prevents the second must-mention item.
- Real model-side weakness exists but is minor: 27 INVALID_ARGUMENTS calls (Sonnet) / 25 (Haiku), 3+1 tool_call_cap/invalid-report endings for Sonnet, which cost M6 (clean runs 73%).

Answerability: 25 of 30 cases have no `ha_search_entities` fixture; fixtures hit only 108/170 overall. Held-out cases with under 60% fixture utilisation: C11 (1/5), C14 (3/6), C30 (0/3). Per-case NIS share among Sonnet reads ranges from 8/35 (C16) to 100% (C23, C30). Where fixtures match (C07: two Sonnet runs pass; C04 and C13 produce no invented flags), the harness does score a pass, so the scoring path works.

Other validity caveats (RUNNER_SPEC §9 also admits some): many fixtures are "reconstructed" or "paraphrase" (e.g. C01 code read is a paraphrase, `freeze_quality` medium); the judge is a single Opus pass with no human spot-check recorded; N=10 held-out.

## 3. Ranked fixes (expected impact on a valid measurement)
1. Make absence-claims legal in M2: a claim may cite a NIS result when its text is an absence statement; only fail when the claim asserts a positive fact from a NIS/DENIED result. Biggest single correction (about 36 runs per model).
2. Make every case discoverable: add generic `ha_search_entities`, `ura_db_query` table-list/schema, and `read_code` path-list fixtures per case (or a `list_tables`/`list_paths` hint), and loosen matching (case-insensitive substring on table, path suffix, glob entity ids). Target: NIS rate on first-guess reads under 20%. Return a helpful NIS (`did_you_mean` / valid tables) instead of a bare error.
3. Fixture coverage audit: every fixture should be reachable by at least one natural query; C23, C30, C11, C14, C18, C28 first. Drop or rewrite held-out cases that are unanswerable.
4. Two-stage scoring: report "answerable-run" M1 separately (runs where the key fixtures were hit), so capability and coverage are separated.
5. Fix tool-schema friction (27 INVALID_ARGUMENTS) and raise/clarify the 30-call cap given the high NIS waste.
6. Re-run Sonnet and Haiku on the repaired harness, with human spot-check of M2 failures as RUBRIC already requires, before concluding anything about the model or abandoning the agent design. Do not call this eval before then.

## Falsification note
What would disprove "harness defect": Sonnet failing on a case where fixtures are hit and the key evidence returned. Counterexamples exist (e.g. C12 partial, C06 with M1+M2 flags), so some real weakness may remain; I did not review those transcripts, so model capability is unknown, not proven good.

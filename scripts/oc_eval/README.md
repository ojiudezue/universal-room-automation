# OC slice-0 eval runner

Implements `docs/planning/oc_eval/RUNNER_SPEC.md` and `RUBRIC.md`. Every tool call is answered
from the case's frozen snapshot; nothing here touches live Home Assistant, the URA DB, ssh or
the board. Network goes only to the Anthropic Messages API and the Ollama host in `config.json`.

| File | Role |
|---|---|
| `config.json` | Models, Ollama URL, run defaults, judge, **price table (operator fills; null = TBD)** |
| `runner.py` | Preflight (leakage + structure), identical prompt/tools per model, mock tool engine, per-run JSONL |
| `judge.py` | Opus 5.5 judge (M1, M2, M3/M7 assist) + final per-run metrics -> `*.judged.jsonl` |
| `report.py` | Held-out / dev / all tables with 90% Wilson intervals, model bar, per-case matrix, Ollama hardware |
| `runs/` | Run logs (gitignored) |

## Commands

```bash
python3 scripts/oc_eval/runner.py --preflight
python3 scripts/oc_eval/runner.py --dry-run --model qwen3:4b-instruct --case C01   # one case, one Ollama model, no judge
pip install anthropic   # needed only for Anthropic models and the judge
export ANTHROPIC_API_KEY=...   # read from env only; never written anywhere
python3 scripts/oc_eval/runner.py                       # all full_eval_models x all cases x 3 runs
python3 scripts/oc_eval/judge.py scripts/oc_eval/runs/eval_<stamp>.jsonl
python3 scripts/oc_eval/report.py scripts/oc_eval/runs/eval_<stamp>.judged.jsonl
```

## Behaviour notes

- Fixture match keys that name an argument the called tool does not have are skipped (multi-tool
  fixtures, e.g. `entity_id_any` + `statistic_id_any` for `ha_get_history`/`recorder_statistics`).
  A call without `symbol`/`section` matches on the other keys alone.
- Run ends: `submit_report` (valid), invalid report twice, 30-call cap, same call+args 3 times
  (loop), 15-min wall, empty response twice (one retry), or a text reply with no tool call.
  Only the first is clean.
- Mechanical M2 pre-check: citing a nonexistent id or a NOT_IN_SNAPSHOT/DENIED/INVALID result, or
  a claim with no citation, counts as invented evidence regardless of the judge.
- Ollama: `num_ctx` is always sent (32768). Thinking is not disabled (spec: log it separately);
  `message.thinking` is logged under `ollama.thinking_log` and never sent back.
- Cost is `TBD` until every price for that model is filled. Haiku runs that cross a 100k prompt
  stay `TBD` until `input_over_100k_multiplier` is filled.
- Ollama output is not bit-reproducible at a fixed seed (two dry runs of C01 diverged); that is
  why the spec runs each case 3 times.

## Preflight status (2026-10-21)

C03 is blocked: its leakage keyword `retune` appears in `tools.json` (`request_fix` P4 "bounded
knob retune"). Fix the keyword or the description before the full run.

## Ollama empty responses (investigated 2026-10-21)

Two causes, both reproduced against 192.168.13.62 (Ollama 0.40.8):
1. **No `num_ctx`**: models default to their full trained context (qwen3:4b-instruct loaded at
   262144 ctx = 43 GB, 13 GB in VRAM + CPU offload, 50 s load). `qwen3.5:9b` via `/api/generate`
   without `num_ctx` produced nothing in 300 s (client timeout, nothing in `/api/ps`). With
   `num_ctx: 8192` it loaded in 15 s.
2. **Thinking**: qwen3.5 has the `thinking` capability and thinks by default. Output goes to
   `message.thinking` (or `thinking` on `/api/generate`), and `content`/`response` stays `""`
   until thinking ends; with a small `num_predict` it ends with `done_reason: length` and empty
   content. A client reading only `response` sees an empty reply.
`/api/chat` with tools, `num_ctx` set and `think: false` returned a proper `tool_calls` reply from
`qwen3.5:9b` in 3 s.

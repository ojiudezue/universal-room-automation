# Review D: crossing vision P3-D2 + P3-D3 (00cd94cef, base 056c69993)

Framing D, adversarial completeness. Verdict: **SHIP**. MEDIUM-1 can be fixed in-cycle.

## Invariants
| Invariant | Result | Evidence |
|---|---|---|
| INV-DIR-GATE | PASS | Terms come only from member `direction`, which is the tracker's value (`crossing_ledger.py:187`; ambiguous members are dropped). Vision direction reaches only the row attributes (`crossing_vision.py` `_record`) and G3 `amend_crossing`, which sets only the 4 amendable keys (`transit_validator.py:991`). The only `SIGNAL_EGRESS_RECORD_AMENDED` listeners are at `sensor.py:5142` and `sensor.py:5299`, and both return early unless role is `exit_backfilled`. The 4 new fields have no reader outside crossing_vision. `person_sighting.py:1614/1717` does not read them. Entry/exit crossings never join an ambiguous-primary request (the `continue` added in the cluster loop). |
| Cost bound | PASS by design | The limit is cap + REPEAT_DAILY_MAX, not cap: repeats have their own budget. Rehydrate filters on `call_kind`, and COALESCE handles old rows. While `_cap_hold` is set, repeats are blocked. With MAX_CONCURRENT 0, every primary records `skipped_busy` and repeats are skipped. |
| Privacy | PASS | The recording window goes through the same `analyze_crossing_frames` and HA Frigate proxy path to the same provider. |
| Coverage of resolved crossings | PASS on 11-16 | 54 crossings is under the cap of 93, so the cap displaced nothing. Concurrency contention (each window request holds a slot about 38 s, MAX_CONCURRENT 2) is not quantified. That needs per-crossing timestamps from the audit. |

## Findings
- **MEDIUM-1, scorer pollution.** A repeat row shares `source_ref` and `started_at` with its primary (`_record_repeat`). `scripts/grading/make_grade_batch.py:204` does `limit 1` with no `call_kind` filter, and `:225` builds a dict keyed by `started_at`. So for about 20% of `ok` crossings the grader can read the repeat row instead of the primary, and the direction scoring is that record's only consumer. Fix: filter `coalesce(json_extract(attrs_json,'$.call_kind'),'primary')='primary'`.
- **LOW-1, cost semantics.** Lowering the cap to 1 mid-day still allows up to 15 repeats. Only cap 0 stops them. Document this on the knob.
- **LOW-2, counter going negative.** In `_run_repeat`, a None reply after local midnight runs `_today["repeats"] -= 1` and `_repeats_today -= 1` against counters that have already rolled over. The result is -1, which allows one extra repeat that day.

Note: the tree guard flagged another agent's mutation of crossing_vision.py during my run (it shares this worktree). Afterwards `git status` was clean and the 3 files gave 200 passed.

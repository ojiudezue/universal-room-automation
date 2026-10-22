# predict-dwell migration (e86707305): Review C (mutation test authority)

Diff base ca81bc8fc..e86707305. 73 single-site source mutations, one at a time, `-p no:cacheprovider`, PYTHONDONTWRITEBYTECODE=1, pycache cleared per run, restored in try/finally, `git status` clean after.
Note: test_optimization_coordinator.py has 10 failures in the unmutated tree (registration/handshake/veto, unrelated); D7 drills ran with `-k "prediction_accuracy or next_room or skill or optimizer_next"` to avoid false RED.

## GREEN on neuter (untested sites)
| SEV | Site | Mutation | Result |
|---|---|---|---|
| HIGH | room_dwell_model.py `_refresh` -> `model.apply(..., trained_until_utc=end.astimezone(utc))` | drop the kwarg | 22 passed. Tests call `model.apply(trained_until_utc=)` directly; nothing proves the real refresh stamps it. Dropped in prod = trained_until None = no freeze ever = zero dwell_share rows, silently (I1 gate fails closed). Needs a test driving the runner refresh, then a tick. |
| MED | optimization.py D7 `next_total >= MIN_SAMPLES` clause | delete | 9 passed. Under-sampled skill noise could raise a finding. |
| MED | sensor.py away-typical fallback `predicted_from_room = current_room` (and its stamp) | delete | 16 passed. Fallback path loses I4 gate unnoticed. |
| LOW | transitions.py dispatch of SIGNAL_NEXT_ROOM_PREDICTION_UPDATE on skip | delete | 29 passed. |
| LOW | room_dwell_model `top_cells` `k <= 0` guard | delete | 41 passed (negative k would slice all but last). |
| LOW | `_ranked_cells` tie-break | drop | 31 passed; determinism untested. |
| LOW | `_frozen` stale-key prune | delete | 22 passed; only a memory-bound. |
| n/a | `dedupe_flaps` `window_s <= 0` early return | delete | equivalent mutant (`gap < 0` never true). Not a finding. |

## RED (named test), all other sites
Freeze: trained>hour gate, trained None, has_model, once/hour; score: same-hour guard, guard-before-await, min_n, sign, confidence=cell_n, stamp, window, batch write, last_hour_fraction; stopped guard; DST local conv; room-entries-only; kill switch; minute clamp; tick registration; unsub on stop; apply stores trained; forecast blend/DST; prune type filter + cutoff (test_prunes_all_types); retention 45 const + nightly wiring; I4 gate/None checks/counters/from_room arg; D7 comparator (<= and <), not-None, person_id read, baseline surfaced, MIN_SKILL const; skill helpers (per-person, sign, dedupe cmp, brier, majority); Bayesian stats; sensor dedupe/order/skip_ratio; D2 kill switches/weights/top_cells knob; D4 primary switch, current_room stamp, Bayesian-skip, away exclusion.

## Fixtures
Production DDL: `make_real_db` -> `UniversalRoomDatabase.initialize()`; seed/fetch via sqlite3 on that file. No hand-copied DDL. Prune test uses literals, not the constant. OK.

## Verdict: FIX-REQUIRED
Must-fix: the HIGH refresh->trained_until wiring test. Should-fix: the two MEDs (D7 sample gate, fallback stamp). LOWs optional.

## Fix-up disposition (builder, 2026-10-21, after tag pre-review-v5.103.85)
| Finding | Disposition | Anchor test (RED on neuter, drilled) |
|---|---|---|
| HIGH refresh -> trained_until_utc | FIXED (test): real `async_refresh`, then two ticks -> one dwell_share row | `test_dwell_share_producer.py::test_real_refresh_then_tick_writes_row` |
| MED D7 `next_total >= MIN_SAMPLES` | FIXED (test): occupancy volume 120 lifts under-learned; 49 next-room rows stay quiet, 50 fire | `test_optimization_coordinator.py::test_next_room_sample_gate_independent_of_occupancy_volume` |
| MED fallback from-room stamp | FIXED (test): primary call raises, frequency fallback predicts, cache carries `current_room` | `test_next_room_current_room.py::test_frequency_fallback_stamps_from_room` |
| LOW dispatch on skip | FIXED (test) | `test_skip_dispatches_update_signal` |
| LOW top_cells k<=0 | FIXED (test, negative k) | `test_top_cells_negative_k_and_tie_break` |
| LOW tie-break | FIXED (test) | `test_top_cells_negative_k_and_tie_break` |
| LOW frozen prune | FIXED (test) | `test_stale_frozen_hours_pruned` |

Also: two more `test_v460_score_on_transition.py` source greps broke on the `_log_transition` signature change and were converted to behavioural tests (`test_score_prediction_called_from_log_transition`, `test_score_prediction_inside_try_block`; the latter drilled RED by not awaiting the insert).

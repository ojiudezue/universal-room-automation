# Review C — test authority (per-site source mutation): lock suspicious-arrival hold

Branch `feature/lock-suspicious-arrival-hold` @ 96998b57; diff base `origin/master...HEAD` (merge-base 3e5cf29a).
Suite under test: `test_arrival_edges.py`, `test_lock_arrival_hold.py`, `test_lock_arrival_hold_real_ha.py`,
`test_lock_arrival_hold_replay.py` (36 tests, all green unmutated). Method: ONE production edit per row, bytecode cleared
(`PYTHONDONTWRITEBYTECODE=1`, `python -B`, `-p no:cacheprovider`, `-m ""`), run the 4 files, restore in a `finally`, `git status --short` clean
after the whole drill (verified twice). 79 mutations. Drill script: scratchpad `lockhold_C/drill.py` (not committed).

Disclosure: the mandatory PRESENCE state-of-play doc (1017 lines) was NOT read end to end in this mechanical pass; no finding here asserts any
presence-doc claim. Findings rest on the diff and test source only.

## RED rows (specific named test fails): 57 of 79

| Site | Mutation | Caught by |
|---|---|---|
| AE1 threshold compare | -> False / -> True / sign flipped / `>=` | `test_stale_source_home_older_than_bound_is_stale`, `..._fresh_and_boundary`, `test_fresh_source_releases_same_callback` |
| AE2 missing `source` attr -> stale | -> False | `test_stale_source_missing_source_or_no_state` (unit only, see F1) |
| AE3 source has no state | -> False | `test_stale_source_missing_source_or_no_state`, `test_replay_real_instant_blips_never_unlock` |
| AE4 last_changed missing | -> False | `test_stale_source_missing_source_or_no_state` |
| AE5 `person_state` param (F2) | ignored | `test_stale_source_zone_and_event_state` |
| AE6 / AE7 not-arrived / None person | guard flipped | `test_stale_source_not_home_and_unreal_never_stale` |
| AE9 / AE9b source `last_updated` for `last_changed` | | `test_stale_source_reads_last_changed_not_last_updated`, `test_fresh_source_releases_same_callback` |
| `_should_hold` H<=0 gate | removed | `test_hold_zero_releases_blip_like_develop`, `test_hold_zero_is_develop_golden` |
| `_should_hold` boot exemption | removed | `test_boot_window_edge_not_held` |
| `_should_hold` old==new | removed | `test_proximity_synthetic_hold_already_home_noop` |
| `_should_hold` never holds | | 17 tests incl. `test_blip_pair_noop_garage` |
| `_start_hold` call_later / due / store | removed / no H / not stored | `test_stale_persisting_confirms_at_h_edge_ts`, `test_teardown_cancels_holds`, `test_blip_pair_noop_*` |
| same-state keep (F1) | falls to drop | `test_attribute_only_event_keeps_hold` |
| revert cancel | removed / hold not dropped | `test_blip_pair_noop_garage`, `test_blip_pair_noop_away_stamp`, `test_two_gps_dropout_held_and_dropped` |
| other-value old_val restore | removed | `test_hold_cancel_by_other_value` |
| `_on_hold_confirm` replay | skipped; now-ts; cfg `{}` (F7); slot not cleared; counter | `test_stale_persisting_confirms_at_h_edge_ts`, `test_confirm_rereads_config`, `test_snapshot_hold_counters` |
| confirm proximity replay | removed / radius check removed | `test_proximity_confirm_rereads_distance` |
| D3 `_apply_arrival` gate | removed / stale branch removed / counter | `test_geofence_signal_dropped_while_stale`, `test_geofence_signal_before_state_listener`, `test_held_face_recheck_blocked_while_stale` |
| D4 proximity gate | removed / H>0 gate / synthetic never started / sid not attached / attach-but-release | `test_proximity_blip_held_and_dropped`, `test_proximity_synthetic_hold_already_home_noop`, `test_hold_zero_is_develop_golden` |
| synthetic edge_ts from person.last_changed | now | `test_proximity_synthetic_hold_already_home_noop` |
| away-dwell deferral | removed | `test_away_dwell_deferred_during_hold` |
| teardown cancel | removed / unsub only / clear only | `test_teardown_cancels_holds` |
| `_process_person_edge` stamps | `_arrival_edges` now; `_last_real` now; live-slug old/new swapped | `test_stale_persisting_confirms_at_h_edge_ts`, `test_attribute_only_event_keeps_hold` |
| diag/counters | held_edges, arrival_holds | `test_snapshot_hold_counters`, `test_blip_pair_noop_garage` |
| consts / number / suppress | default 5->0/30, stale 10->1e9/1e-4, number default/max/conf_key, NO_LIVE_ATTR key, SUPPRESS key | `test_arrival_hold_number_roundtrip`, `test_arrival_hold_number_set_is_read_live`, `test_arrival_hold_key_in_reload_suppress_and_no_live_attr`, `test_replay_real_instant_blips_never_unlock` |

## GREEN rows (suite stays 36 passed): 22 of 79

| # | Site (production line) | Mutation | Verdict |
|---|---|---|---|
| G1 | D3 H>0 gate, `_apply_arrival` | removed | **UNTESTED, MEDIUM.** With H=0 and a stale-reading person, D3 would drop the signal and nothing replays: a lock never releases. Breaks INV-H4 (H=0 = develop). `test_hold_zero_*` does not drive a stale signal at H=0. |
| G2 | D3 boot exemption, `_apply_arrival` | removed | **UNTESTED, MEDIUM.** Only the `_should_hold` boot exemption has a test. |
| G3 | D4 boot exemption, proximity | removed | **UNTESTED, MEDIUM.** Same. |
| G4 | D3 `person in self._held_edges` branch | removed | **UNTESTED, MEDIUM.** The stale branch masks it unless the source goes fresh mid-hold; that case (signal must still drop, the confirm replays it) is not driven. |
| G5 | `_process_person_edge` `_arrival_counts(..., edge_ts)` | now-ts | **UNTESTED, MEDIUM** (INV-H5 for the P1 window; only the `_arrival_edges` and `_last_real` stamps are anchored). |
| G6 | `_process_person_edge` `_away_on_person(..., edge_ts)` | now-ts | **UNTESTED, MEDIUM** (INV-H5 for the away-lock outing stamp). `test_blip_pair_noop_away_stamp` covers the cancel path only. |
| G7 | synthetic hold adopts real edge's `old_val` (F1/F6) | removed | **UNTESTED, MEDIUM.** |
| G8 | `_start_synthetic_hold` pre-edge value from `_last_real` / `synthetic=True` flag | `old=current`; flag False | **UNTESTED, MEDIUM** (same F6 path as G7). |
| G9 | `_should_hold` reads event `new_state` (F2) | live `states.get` | **UNTESTED, MEDIUM.** The harness makes the live state equal the event's, so a callback-time race is never exercised. `AE5` has a unit test, but nothing ties the controller to it. |
| G10 | away-dwell: `p in persons` filter | removed | **UNTESTED, LOW-MEDIUM.** |
| G11 | away-dwell: `max(dues)` vs `min` | min | **UNTESTED, LOW** (multi-person holds). |
| G12 | away-dwell: `+ LOCK_ARRIVAL_DWELL_DEFER_PAD_S` and CO3 pad 0.1->0 | removed | **UNTESTED, MEDIUM.** The F3 ordering (a confirm replay cancels the dwell before it re-fires) is exactly what the pad guards. |
| G13 | away-dwell: `_away_pending_at = due` | removed | **UNTESTED, LOW.** Surfaces in the `pending_engage_at` snapshot. |
| G14 | listener `old is None` -> `_drop_hold` | removed | **UNTESTED, LOW.** |
| G15 | `_stale` exception swallow | narrowed to `KeyError` | **UNTESTED, LOW.** No test injects a read error. |
| G16 | `_on_hold_confirm` state recheck | removed | **Provably equivalent in-flow.** Any person change fires the listener, which drops or cancels the hold first. Defensive only. LOW. |
| G17 | `_on_hold_confirm` `_torn_down` guard | removed | **Equivalent while teardown unsubs.** Backstop only. |
| G18 | confirm proximity resident gate | removed | **Equivalent.** D4 already returns early for non-residents. |
| G19 | `_should_hold` `not_home` exclusion | removed | **Equivalent.** `_stale` returns False for `not_home`. |
| G20 | AE8 `last_updated` on the person side only | | **Test-fixture equivalent.** `FakeState.last_updated` defaults to `last_changed`. The source-side mutation (AE9) is RED, so the real-HA test covers the intent. LOW. |

Tally: 79 mutations, 57 RED. 22 GREEN rows: 15 genuinely untested (G1-G15; G10-G15 low severity), 4 equivalent or defensive (G16-G19), 1 fixture-equivalent (G20), plus the CO3/G12 and AE8/G20 pairs counted once.

## Harness masking check (the `_lockout_harness.py` fresh-source injection)

The harness injects a fresh `device_tracker.<p>_ura_test_src` on every person write that lacks `source` or has one ending in the auto suffix. Mutating
the missing-source branch (AE2: `if not src: return True` -> False) is caught ONLY by the pure unit test
`test_stale_source_missing_source_or_no_state`. No controller-level test (`test_lock_arrival_hold`, `_real_ha`, `_replay`) goes red, because the harness
always supplies a source. **F1 (LOW-MEDIUM):** the missing-source-attribute branch has no integration anchor; a controller that mishandled it
(e.g. stopped treating it as suspicious) would pass every behavioural test. The sibling branches (AE3 source-has-no-state, AE4 no `last_changed`) ARE
caught at the controller level by `test_replay_real_instant_blips_never_unlock` (AE3) or only by the unit test (AE4). The harness change does not hide the
unit-level branch, but it does mean the missing-source case is never driven through a held-edge path. Recommended fix: one controller test that
writes a person with an explicit `attributes={}` and `source` removed.

## Findings (all MEDIUM unless noted)

1. G1/G2/G3: H=0 and boot exemptions on D3/D4 are untested. H=0 on D3 is the kill-switch contract (INV-H4).
2. G5/G6: edge_ts stamping through `_arrival_counts` and `_away_on_person` on confirm replay is untested (INV-H5).
3. G7/G8/G9: synthetic-hold pre-edge value and F2 event-`new_state` read are untested.
4. G4, G12: the held-edge D3 branch and the dwell pad (F3) are untested; one mid-hold-source-fresh test and one confirm-vs-dwell ordering test would close both.
5. F1 above: missing-source branch has no controller-level test.
6. LOW: G10, G11, G13, G14, G15.

## Verdict: FIX-REQUIRED

Must add anchoring tests (each verified by re-running the matching mutation): G1, G2, G3, G4, G5, G6, G7/G8, G9, G12, F1 (missing-source, controller level).
G10 to G15 are LOW; fix in-cycle if cheap. G16 to G19 need no test (equivalent). The mutation-authority core (compare, hold start, same-state keep, revert
cancel, confirm replay, D3 signal gate, D4 gate, dwell deferral, teardown, number/const/suppress wiring) is genuinely anchored; the gaps are the edges around it.

# Review C - SC-LOCK-SWEEP-EXCLUDE-1 / SC-LOCK-REGIME-DOOR-LOCKS-1 (test authority via per-site source mutation)

Branch `feature/sc-lock-exclude-away-lock`, diff `3032edf6...2b3ae2f6` (three-dot, base verified).
Method: ONE load-bearing site mutated per run in production source, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared before every run, mutate+restore in one Python try/finally, `git status` clean after.
Target set per run (no full suite): `test_sc_away_lock`, `test_sc_lock_exclude`, `test_sc_lock_exclude_options`, `test_part2_ec_hc_writeback`, `test_sc_garage_lockout`, `test_sc_garage_lockout_review_c`, `test_v4_6_9_security_aggregator` (384 tests, baseline green).
Enumeration was independent of the builder's list: 166 single-site mutants + 8 multi-site combos (all in scratchpad `drill_c*.py`).

## Result: 150 of 166 single mutants RED on a SPECIFIC named test; 16 GREEN (below), of which 3 were bad mutants re-run and now RED.

### RED (tested) - by area
| Area | Sites mutated | Killing test (examples) |
|---|---|---|
| S1 lockdown filter | filter removed | test_sc_lock_exclude::test_lockdown_skips_excluded |
| S2 sweep skip / excluded_seen / unavailable-still-notified | 3 | test_sweep_skips_excluded_unlocked, test_excluded_unavailable_still_notified |
| S3 garage engage guard (`excluded`) | 1 | test_lockout_engage_skips_excluded_runtime_guard |
| hazard egress unlock still covers excluded | 1 | test_hazard_unlock_still_includes_excluded |
| `_sweep_excluded` no-regime CM fallback (options merge) | 1 | test_sweep_skips_excluded_unlocked |
| Aggregator posture filter, locks_excluded count/key/sensor attr/fallback shape | 6 | test_aggregator_excludes_excluded, test_aggregator_fallback_shape_has_locks_excluded |
| Compliance total + numerator (by key) | 2 | test_compliance_rate_never_above_100 |
| LastLockSweep sensor `excluded` attr | 1 | test_last_lock_sweep_sensor_exposes_excluded |
| house_status doors branch / note / bad-set | 3 | test_doors_excluded_unlocked_not_problem |
| Switch built/default/release_on_off/conf_key pass-through; regime key routing; garage OFF `force` | 6 | test_switch_default_off, test_switch_off_releases_only_its_policy, test_kill_switch_off_releases_owned, test_garage_switch_off_path_byte_identical |
| Predicate clauses: kill_switch, sc_alive, not_excluded, is_lockout, dwell, unlocked-only (+ not_all_away via non-crashing neuter, see note) | 7 | test_kill_switch_off_after_arming_blocks_engage ... test_stale_stamp_with_named_zone_state_never_engages |
| due_ts: exact not_home, max-not-min, empty persons | 3 | test_dwell_counts_from_last_person_out, test_empty_persons_inert |
| Engage loop: set_attempted, epoch (B1), per-lock cfg re-read (combo C3), observation mode, in-flight stamp + persist (A5), readback scheduling | 8 | test_b1_hazard_after_first_lock_second_never_locked, test_a4_switch_off_mid_loop_second_never_locked, test_a5_restart_inside_readback_window_owns_locked_lock |
| Readback: locked->owned, persist owned, advisory once/sent | 4 | test_engage_taken_records_ownership, test_two_entities_not_taken_one_advisory |
| Ownership: manual-unlock drop, listener registered, `unlocked`-only filter, targets union in-flight | 4 | test_manual_unlock_drops_ownership, test_release_inside_readback_window |
| Release: epoch bump, pop in-flight, unavailable keeps ownership (B4), discard owned, policy passed, NM away wording | 6 | test_b4_inflight_unavailable_at_release_becomes_owned, test_release_readback_retry_then_high_nm |
| A1 home release, boot discharge (call/home/rearm), M6 clear-attempted, stamp edges, boot-window no-arm, person list gate, restore path, non-resident `_last_real` | 14 | test_release_on_either_arrival_p1, test_a1_restart_person_home_at_boot_recheck_releases_owned, test_away_person_also_lockout_excluded_still_tracked |
| Setup reconcile (owned-unlocked dropped, in-flight restored, stamp setdefault/pop, B2 marker compare, formation-key none-if-missing) | 6 | test_b2_new_outing_after_restart_still_engages, test_stale_persisted_stamp_dropped_when_person_reads_home |
| Store: every payload key (5), every loader key (5), pid filter, independent load, set_attempted marker | 13 | test_store_save_merges_keys, test_owned_survives_restart |
| Teardown: store flush, dwell unsub, away readbacks, await unlocks; SC-disable away release (call, unlock verb, kill-switch independence) | 8 | test_b5_teardown_flushes_store, test_sc_disable_releases_away_lock_with_garage_off |
| Validators + flow: `lock_exclude_not_subset`, `lockout_overlap`, three error keys, errors-gate, options merge, distance filter, strings/en.json keys | 11 | test_sc_lock_exclude_options.* |
| Reload-suppress / NO_LIVE sets (both copies; `away_lock_entities` must stay out) | 2 | test_live_keys_in_reload_suppress_and_no_live_attr_sets |
| Constants: dwell=300, away default False | 2 | test_no_engage_before_dwell, test_kill_switch_absent_is_off |

Note on `not_all_away`: neutering with `if False:` stayed GREEN only because `None < due` raises TypeError inside a swallowed task (crash-safe, not a lock). Re-run as a non-crashing neuter (`due=0.0`, combos C1/C2) it is RED (test_stale_stamp_with_named_zone_state_never_engages). Tested. Likewise the first `per-lock cfg re-read` mutant was bad (NameError); the proper frozen-cfg combo C3 is RED.

## GREEN (untested) sites - each is a finding

MEDIUM
- G1 `security_lock_runtime` A1 named-zone rule: `if new_val == "home" and self._away_targets()` (security_lock_regime.py ~1523). Widening to "any non-not_home reading releases" (named zone releases) leaves the suite green. The operator ruling (named zones are "not away", but only `home` releases; passage mode B) has no test that a person entering a named zone does NOT release owned locks. Add: owned lock, listed person -> `zone.work`, assert no unlock.
- G2 Release is not gated by observation mode (INV-X3 fail-safe): inserting `if observation_mode: return` at the top of `_away_release` stays green. Add test: observation_mode True, owned lock, person home -> unlock issued.
- G3 SC-disable away release independent of the away switch (M4): gating `_away_release_on_disable` on `away_lock_on()` stays green. Add test: away switch OFF + SC disabled + owned lock -> unlocked.
- G4 `_set_attempted()` inside `_away_release` (formation latch, "no re-engage in this outing after any release"). Removing it stays green (only the epoch half is tested, C5 RED). Reachable: switch OFF during dwell, back ON, next listed-person edge re-arms and locks the same outing. Add test: kill-switch OFF release then ON then person edge -> no engage.
- G5 `home pops stamp` (`_away_on_person` else-branch, `_away_not_home_since.pop`): removing it is green. Reachable: person home (stamp should drop) -> unavailable -> not_home keeps the OLD stamp (`elif pid not in since` is False) so the dwell is skipped and the lock engages immediately on a GPS flap. Add test for home -> unavailable -> not_home needing a fresh 300 s.
- G6 Options form defaults for the three new fields (`default=self._get_current(...)` -> `[]` for `security_lock_sweep_exclude`, `security_away_lock_entities`, `security_away_lock_persons`) all stay green. Submitting an untouched form would then erase existing config (data loss on the options round-trip). Add a flow test that asserts the rendered schema defaults reflect stored options.
- G7 `_sweep_excluded` string coercion (`security.py` ~690) and the `except Exception` fallback are untested: a single-string `security_lock_sweep_exclude` is treated as "nothing excluded" by SC while `regime.sweep_exclude` (`_as_set`) accepts it - divergent readers; the sweep would lock an interior door. Also the `& set(self._lock_entities)` intersect. Add parametrized test (str, tuple, junk, exception).

LOW
- G8 formation-key `max` vs `min` (multi-person B2 marker identity) green - tests use one person. Add two-person restart test.
- G9 `_set_attempted` / `_clear_attempted` `_save_store()` calls green (the marker persists only via a later save; test passes because teardown/other saves follow). Add assertion on `async_delay_save` after the call.
- G10 SC-disable away path: `_notify_failure(..., policy=POLICY_AWAY_LOCK)` (no HIGH NM on failed disable-release), A3 unreal-state keep-ownership, `_save_store` at end, epoch bump - all green. Add a failing-unlock-on-disable test.
- G11 Engage exception path pops in-flight (`_away_engage_inflight.pop` on lock.lock raising) green; `blocking=False` on the away lock.lock call green (a blocking call would stall the engage loop; the garage suite pins this only for the garage path).
- G12 Double-defence pairs: `rearm cancels prior timer` and `engage attempted-guard` each green alone AND together (C4 green) - two stacked dwell timers would double-issue lock.lock; unproven redundant defences. `rearm kill-switch/entities gate` (C7), `release unlocked/in-flight skips` (C8, extra unlock on an already-unlocked lock), `release cancel dwell` / `no-target early return` / `release save` all green.
- G13 Redundant-by-design (equivalent mutants, documented not required): `P not_away_lock_entity` (loop iterates the same list), `ownership in-flight guard`, `readback released-meanwhile` / `readback torn_down`, `released-while-call` continue, `P release_inflight`, `undecided cancels dwell`, `due missing since`, `setup marker clear`, `store load marker bool`, `setup warn both`, `away_lock_persons person. filter`, `away_lock_entities empty filter`, `garage engage touches away entities` (blocked upstream by the S3 `excluded` guard), garage OFF `_cancel_reengage` byte-identity (not asserted by test_garage_switch_off_path_byte_identical). Not blockers; `P release_inflight` and the garage `_cancel_reengage` assertion are cheap to pin.

## Cleanliness
Every drill restored in try/finally; `git status --short` in the worktree is empty after all runs. Main checkout untouched except this file. No full-suite run (validator's job).

## Verdict: FIX-REQUIRED (test additions only, no production defect found)
Must-fix tests before ship: G1, G2, G3, G4, G5 (also confirm G5 is a real bug - it looks like one: stale stamp survives home -> unavailable -> not_home), G6, G7. G8-G12 fix in-cycle as LOWs (small). No production-code leak was proven by Review C itself; G4/G5/G7 are production behaviours the suite cannot distinguish from a broken variant and should be handed to Review A/B/D to confirm reachability.

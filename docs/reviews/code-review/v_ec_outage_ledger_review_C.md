# EC outage ledger (Stage L) - Review C: test authority via real per-site mutation

Branch feature/ec-outage-ledger @ 9fe8e3f34, base b003a64cd. Reviewer C (independent of the builder's 53-drill claim).
Method: for each site, one source mutation applied to production code, `quality/tests/test_ec_outage_ledger.py` run
(47 tests, ~0.8 s) with PYTHONDONTWRITEBYTECODE=1 and `__pycache__` cleared, file restored in `finally`, `git status` clean after.
95 mutants run (83 + 12 extra). 78 RED, 17 SURVIVED (of which 5 are equivalent/near-equivalent, 12 are real test gaps).

## Fixture authority
- `real_db` builds `UniversalRoomDatabase(...).initialize()` + the real write worker: schema comes from production source, not hand-copied DDL. PASS.
- Prune tests seed via sqlite INSERT then call production `prune_activity_log`; filter/error tests call production `query_activities`. PASS.
- `test_real_timers_run_the_sweep_on_the_loop` uses `async_test_home_assistant` + real `async_call_later` / `async_track_time_interval` + `async_fire_time_changed`, asserts the sweep runs on the loop thread. Removing `@callback` from `_spawn_sweep` and from `_on_initial` each goes RED (that test and `test_sweep_timer_callbacks_are_ha_callbacks`). It really exercises HA's timer dispatch. PASS.
- Hook placement test drives the real `_decision_cycle_body` (CycleShell subclass); removing the `_outage_ledger_tick()` call goes RED in 3 tests. PASS.
- Caveat: `_FakeDB.query_activities` ignores filters (action/coordinator) and `_CycleShell` assigns `_outage_ledger` itself, so those two seams are only covered where `real_db` is used (action) or not at all (see S12, S16).

## Per-site table
| Site | Mutation | Result |
|---|---|---|
| database prune info tier | drop `+ _keep` | RED test_prune_keeps_ledger_rows, test_prune_still_deletes_other_rows |
| database prune notable tier | drop `+ _keep` | RED test_prune_keeps_ledger_rows |
| `_render_ledger_exemption` empty branch | always "" | RED (3 tests incl. bad_identifier) |
| exemption NOT IN | IN | RED test_prune_keeps_ledger_rows |
| exemption identifier validation | disabled | RED test_ledger_exemption_rejects_bad_identifier |
| query_activities action clause | removed | RED test_query_activities_action_filter |
| query_activities action param | wrong value | RED test_query_activities_action_filter, round_trips |
| query_activities error key | removed | RED test_query_activities_reports_error |
| const retained: nws_alert / grid_outage / code_drift / memory_cleared | each dropped | RED test_prune_keeps_ledger_rows (all four) |
| alert dedup `in _seen_alerts` | removed | RED one_row_per_id, seen_set_pruned, seed_dedups_across_boots |
| seen set only on emit success | unconditional/none | RED (3 tests) |
| alert prune (remove / ignore end / not-list=empty) | each | RED seen_set_pruned / unavailable_feed |
| alert prune `if key in present: continue` | removed | **SURVIVED** (S1) |
| alert hard ceiling MAX_SEEN | disabled | **SURVIVED** (S2) |
| alert pass waits for seed; ensure-seed from tick | each | RED test_alert_pass_waits_for_seed (+) |
| seed flag set before read / on fail / no max-attempts / attempt not counted | each | RED seed_failure_is_retried..., no_database_counts_attempt |
| seed loads nothing / lookback zero | each | RED seed_dedups_across_boots (+) |
| `_query_ledger_rows` error ignored / no pagination / no-db returns [] / action dropped | each | RED |
| cloud seed flag set before read | | RED test_cloud_seed_failure_retried_next_sweep |
| cloud seed attempt not counted | | **SURVIVED** (S3) |
| cloud seed attempts cap (`< MAX_ATTEMPTS`) | forced True | **SURVIVED** (S3) |
| cloud seed `witness == "cloud"` filter | removed | SURVIVED, equivalent (local_only rows carry no `event_start_utc`) |
| cloud seed loads nothing; cloud dedup skip; `_cloud_seen.add` | each | RED test_outage_sweep_dedups_* |
| cloud seen ceiling | disabled | **SURVIVED** (S4) |
| local min-gap removed / global-not-per-sensor / row_at not set / suppressed not counted | each | RED test_local_only_min_gap_* |
| `_local_suppressed.pop` -> `get` | | **SURVIVED** (S5) |
| `_local_obs.append` placed after gap check | moved/removed | RED test_outage_sweep_marks_local_corroboration |
| None resets baseline (`pop` on None) | | **SURVIVED** (S6) |
| boot opens row / any-edge / baseline not stored / witness label | each | RED |
| decision hist append / nearest `<=` | each | RED test_outage_sweep_embeds_nearest_decision |
| corroborated false / no tolerance | each | RED test_outage_sweep_marks_local_corroboration |
| `ongrid_at` selection (`p[0] > t` dropped) | | **SURVIVED** (S7) |
| generator window (`t <= p[0] <= win_end` dropped) | | **SURVIVED** (S7) |
| events sort removed | | **SURVIVED** (S7) |
| calendar resolve ambiguity / platform / suffix filters | each | RED test_outage_sweep_calendar_unresolved[...] |
| calendar unavailable skip | | RED test_outage_sweep_calendar_unavailable_skips |
| sweep exception isolation | | RED test_outage_sweep_failure_isolated |
| `_fetch_events` timeout | `timeout=None` | **SURVIVED** (S8) |
| `_emit` no-db returns True | | **SURVIVED** (S9) |
| `_emit` importance | | RED round_trips |
| `_emit` coordinator="energy" | | **SURVIVED** (S10) |
| action names, cloud timestamp/entity_id, alert entity_id/payload fields, lookback | each | RED |
| classifier ordering; `cls is None` skip; empty-OFFGRID guard | each | SURVIVED, equivalent/constant-bound (substrings disjoint; later offgrid filter; guard needs constant monkeypatch) |
| `_alert_end` Expires fallback | removed | **SURVIVED** (S11) |
| `@callback` on `_spawn_sweep` / `_on_initial` | removed | RED (real-timer test) |
| `_spawn_sweep` one-at-a-time | removed | **SURVIVED** (S13) |
| arm idempotency (initial / interval), interval=0 disable, arm starts seed, initial delay | each | RED |
| cancel initial / interval / sweep task / task.cancel() | each | RED |
| cancel `_alert_seed_task` | removed from loop | **SURVIVED** (S14) |
| `_ensure_alert_seed` one-at-a-time | removed | RED test_alert_pass_waits_for_seed |
| energy.py tick call / arm call / cancel call | each | RED (3 hook tests / async_setup_arms / task_cancelled_on_unload) |
| energy.py alerts->None, local_readings={}, grid_enabled leg, grid_status invert/unknown/name, age | each | RED |
| energy.py `soc=soc` wiring | -> None | **SURVIVED** (S15) |
| energy.py `decision=dec` wiring | -> None | **SURVIVED** (S15) |
| energy.py `OutageLedger(hass)` in `__init__` | -> None | **SURVIVED** (S16) |

## Survivors (load-bearing unless noted)
- S1 MEDIUM: alert prune without the `key in present` guard deletes a still-present alert whose end is None/past, so next tick re-logs it (duplicate never-pruned rows). Tests only use future-end alerts.
- S2 LOW: seen-set hard ceiling untested.
- S3 MEDIUM: cloud-seed retry accounting and the unseeded fall-through cap are untested; a persistently failing read would retry silently forever (no row ever written) and nothing fails. Only the first-retry path is tested.
- S4 LOW: `_cloud_seen` ceiling untested.
- S5 LOW: suppressed counter never reset -> `suppressed_since_last` overstates after the second row.
- S6 MEDIUM: a None reading wiping the baseline would drop a real False->None->True edge. Existing None test starts at True so it cannot discriminate. Needed sequence: False, None, True -> 1 row.
- S7 MEDIUM: payload fields `ongrid_at` and `generator_events` (the outage duration and generator evidence the ledger exists to record) are never asserted; the sort/selection logic is unanchored.
- S8 LOW: sweep timeout not tested.
- S9 MEDIUM: `_emit` returning True when there is no database would mark alerts/cloud events seen with no row written; the no-database test passes only because `_seen_alerts == {}` is satisfied by a different path (seed counts attempts). Needs a test where the DB vanishes after seed.
- S10 MEDIUM: `coordinator="energy"` in `_emit` unasserted. Seed queries filter `coordinator="energy"`, so a wrong value would silently break cross-boot dedup in production while `_FakeDB` (ignores filters) stays green. `real_db` round-trip should assert the stored coordinator.
- S11 LOW: Expires fallback in `_alert_end` untested.
- S13 LOW: one-sweep-at-a-time guard untested.
- S14 MEDIUM: teardown cancel of the in-flight alert-seed task untested (Bug Class: untracked background task). Cancel-sweep-task is covered, seed-task is not.
- S15 MEDIUM: `soc` and `decision` threading from `_outage_ledger_tick` is unasserted; rows would silently lose `soc`/`tier`/`hold_depth`. (battery_soc stub is None in the cycle shell.)
- S16 MEDIUM: nothing proves `EnergyCoordinator.__init__` constructs the ledger (the cycle shell sets it by hand; `test_async_setup_arms_outage_ledger` likely does the same). A removed constructor line leaves the whole feature inert and the suite green.

## Verdict: FIX-REQUIRED
Per policy any surviving load-bearing mutant is a FIX. Must-fix (add discriminating tests, no production change expected): S1, S3, S6, S7, S9, S10, S14, S15, S16. Fold in the LOWs (S2, S4, S5, S8, S11, S13) as cheap additions. After adding tests, re-drill exactly these mutants. 78 of 95 mutants were killed by named tests; the builder's RED claims for the rest of the surface reproduce.

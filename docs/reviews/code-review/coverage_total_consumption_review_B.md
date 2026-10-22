# Review B: COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 (fix/coverage-total-consumption @ 6945e1228)

Framing: consumers + lifecycle + test authority via per-site source mutation. Reviewed 2026-10-22.
Diff base: merge-base `23699c0b0` (develop is 71 commits ahead). Code diff: `aggregation.py` (+71), `energy.py` (comments only), new test file, README.

## Verdict: SHIP (code). One must-fix at merge: rename the README (version collision).

## Findings

| # | Sev | Where | Class | Finding |
|---|---|---|---|---|
| B1 | MEDIUM (merge-blocking, not code) | `docs/readmes/README_v5.103.83.md` | Release hygiene | `git merge-tree` vs develop: add/add conflict. develop already has README_v5.103.83 (BAYES-OCCUPANCY-ANOMALY) and v5.103.84. Renumber to the next free version (>= 5.103.85) at merge. The code files auto-merge cleanly (`energy.py` auto-merged). |
| B2 | LOW | `aggregation.py:3440` + `:3453` | Display/attribute split | `native_value` and `extra_state_attributes` each call `_get_whole_house_energy()` in the same state write, and the switch guard is stateful. On the switch cycle the state is None but the attributes are computed on the second call, which reads normally against the new source. For a never-seen source that call yields about 0, which takes the "No data" attribute path. For a previously seen source (CM reload round-trip) the attributes show real values while the state is None. This is cosmetic for one cycle, and nothing consumes either value (see consumers). |
| B3 | LOW | `aggregation.py:3564-3576` | #7 boot variant | At boot, if the aggregation entity polls before the CM/EC entry registers `coordinators["energy"]`, the first pick is the NET field ("unknown" means it reads normally). The sensor publishes NET-based unattributed values until EC appears, then drops one cycle and switches to TOTAL. This only affects display, only during the boot window, and the post-restart baseline is the first read anyway. Accepted. |

No CRITICAL/HIGH.

## Consumers
- No code consumer of `energy_coverage_delta` or its `whole_house_*` attributes outside `aggregation.py`. I grepped custom_components, the pwa dir and scripts. The only `unattributed` hit in optimization.py:5213 is unrelated. So the change is display-only.
- Cost/billing still reads NET. `CONF_WHOLE_HOUSE_ENERGY_SENSORS` and the cost sensor are untouched by the diff, and `test_cost_sensor_still_reads_net` pins this. EC's own `_entity_lifetime_consumption` read (`energy.py:3024`) is unchanged; the energy.py hunks are comment-only.
- Unit/semantics: TOTAL is a lifetime kWh counter. It goes through the existing `_classify_and_accumulate` path (today_derived plus a per-sensor baseline), the same path the NET lifetime counter used. Its tracker key `__whole_house____<eid>` is per-entity, so NET and TOTAL never share a baseline.

## Lifecycle
- EC not loaded / CM reload: `_get_energy_coordinator` is a lazy lookup (`aggregation.py:3690`) and returns None, so the sensor falls back to NET with a one-cycle no-data guard. When EC returns, there is another one-cycle guard, and TOTAL's existing baseline entry is reused (it is still keyed and anchored the same day), so the delta is correct.
- Envoy dropout: when the entity exists but is unavailable, the sensor stays on ec_total and returns None (no NET swap). Pinned by `test_ec_total_unavailable_stays_on_total_no_data`. If the entity is removed from the state machine, the sensor falls back to NET with the guard.
- No new listeners, timers or tasks; nothing to unsub. `_whole_house_source` is not restored. It starts "unknown" after a restart, so the first read is not suppressed. That matches the pre-existing non-restored `_tier_baselines`.
- Midnight: no new seam. The read-and-discard path calls `_classify_and_accumulate`, which still runs `_maybe_reclassify_at_midnight`, and the per-key day rollover is the pre-existing machinery.

## Test authority (real per-site mutation; PYTHONDONTWRITEBYTECODE=1, __pycache__ cleared per run; 6 coverage test files, baseline 122 passed)

| Site | Mutation | Result | Named RED test(s) |
|---|---|---|---|
| EC-total preferred (`return [total_eid], EC_TOTAL`) | -> pass | RED 4 | test_ec_total_configured_coverage_uses_total_not_net, +3 |
| State-machine existence check | -> `and True` | RED 1 | test_ec_total_entity_missing_from_state_machine_falls_back |
| Switch guard `return None` | removed | RED 2 | test_net_to_total_switch_publishes_no_data_then_total_baseline, test_total_to_net_switch_publishes_no_data |
| Read-and-discard re-anchor | -> pass | RED 1 | test_net_to_total_switch_publishes_no_data_then_total_baseline |
| First-ever exemption (`previous != "unknown"`) | dropped | RED 6 | test_ec_absent_falls_back_to_whole_house_energy_sensors, +5 |
| Source tracking assignment | -> pass | RED 6 | test_ec_total_unavailable_stays_on_total_no_data, +5 |
| `whole_house_source` attribute | key renamed | RED 5 | test_ec_total_configured_coverage_uses_total_not_net, +4 |

No GREEN rows. Tree was restored and `git status` was clean after the drills.

## Bug-class tally
Release hygiene 1 (MEDIUM), display/attribute split 1 (LOW), #7 stale-source boot variant 1 (LOW). No QUALITY_CONTEXT update proposed.

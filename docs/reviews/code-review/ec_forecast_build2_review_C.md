# EC Forecast Build 2 -- Review C (test authority, real per-site source mutation)

Branch fix/ec-forecast-build2 @ 29fd7d33, base develop 12e979b7 (merge-base verified = 12e979b7).
Method: one production-source edit per drill (mutate + restore in one Python step, `__pycache__` cleared, PYTHONDONTWRITEBYTECODE=1), run against the 7 cycle/module test files only (no full suite). 100 drills.

## Result
First pass: 83 RED, 17 GREEN (surviving = untested sites). All 17 closed by the new
`quality/tests/test_ec_forecast_build2_mutation_gaps.py` (23 tests); re-drilled: 17/17 now RED. Tree clean after every drill.

## Site table (site | mutation | killing test)
| Site | Mutation | RED test |
|---|---|---|
| S1 signed write gate energy.py ~4632 | `!= 0` -> `> 0` | test_arbitrage_loss_books_negative_row |
| S2 discharge_savings_usd | restore `max(0,..)` | test_discharge_savings_signed_not_clamped (+loss row) |
| S3 lifetime sensor live-when-rows / max(baseline) / baseline fallback | 3 mutants | test_lifetime_arbitrage_net_loss_not_masked_by_baseline |
| S4 predicted-bill pace `!= 0` | `> 0` | test_predicted_bill_counterfactual_carries_arbitrage_loss |
| S5 predicted_energy_today sign flip / EC source (energy+cost) | 3 mutants | test_predicted_today_reads_ec_forecast, test_predicted_cost_does_not_double_count_delivery[Today] |
| D8 local-date match, midpoint, no index-0 fallback | 3 | test_forecast_temps_for_date_dst_day, test_temp_feature_is_high_low_midpoint, ..._no_fallback |
| D8 6h age-out (async + sync reader), B4 no-restamp | 3 | test_failed_fetch_does_not_restamp_and_list_ages_out |
| D8 provider-mismatch (async + sync) | 2 | **GREEN -> new** test_provider_switch_inside_ttl_refetches_not_serves_old_provider |
| D8 shadow feed (sync + async) / tick call | 3 | test_decision_cycle_body_never_awaits_weather_and_reads_cache, test_set_predictor_shadow_temp_feeds_today_forecast |
| D3 local tomorrow, Solcast, bias, sign x2, window, kill switch, missing_input, rate limit, inputs sched, sensor snapshot | 11 | test_net_tomorrow_*, test_net_bias_trailing_window_and_kill_switch, test_tomorrow_forecast_rate_limited, test_tomorrow_refresh_schedules_recorder_inputs_task, test_tomorrow_sensor_reads_ec_option_a_snapshot |
| D4 bucket _period_at / local tz / share weighting / min_days / export rate / rep instants / fallback import hw / mix whole days / mix since / tomorrow target day / priced via EC | 11 | test_predicted_cost_*, test_period_kwh_mix_*, test_refresh_period_mix_reads_whole_local_days |
| D4 export uses export shares | key import-only | **GREEN -> new** test_export_credit_uses_export_shares_and_period_rates |
| D4 fallback export hour-weighted | instant | **GREEN -> new** test_fallback_export_is_hour_weighted_not_instant |
| D4 absent period priced hw | 0 rate | **GREEN -> new** test_period_absent_from_day_priced_at_hour_weighted_not_zero |
| D4 Cost-Today prices today | day+3 | **GREEN -> new** test_predicted_cost_today_prices_today_not_other_day |
| D4 no-EC export None | removed | **GREEN -> new** test_price_predicted_no_ec_export_has_no_rate |
| D4 EC.price_net_kwh passes real mix_days | 999 | **GREEN -> new** test_ec_price_net_kwh_passes_real_mix_days_to_min_days_gate |
| D5 INSERT OR IGNORE, skip-on-None, logged_for guard, hour gate, consumed flag/arm, single batch, accuracy exclude-today/JOIN, DDL, PK | 12 | test_forecast_log_*, test_restart_2210_*, test_incomplete_prediction_not_logged_and_retried, test_forecast_accuracy_excludes_today_and_unscored |
| D5 mark logged only on write success | unconditional | **GREEN -> new** test_failed_log_write_is_retried_not_marked_logged |
| D5 accuracy refresh wired | removed | **GREEN -> new** test_refresh_populates_accuracy_attrs_from_joined_log |
| D5 backtest_mae >=7 rows gate | removed | **GREEN -> new** test_backtest_mae_attr_needs_seven_log_rows |
| Sched: refresh call, stopping guards x2, tick single-flight, inflight reset, teardown cancel, inputs reset, inputs rate limit, tick isolation | 9 | test_decision_cycle_schedules_forecast_refresh_off_tick, test_forecast_refresh_not_scheduled_when_stopping, test_forecast_tick_isolates_failures, test_tomorrow_refresh_schedules_recorder_inputs_task |
| Sched: inputs in-flight guard | removed | **GREEN -> new** test_forecast_inputs_single_flight_when_interval_elapsed |
| Sched: create-task failure closes coro + resets flag | removed | **GREEN -> new** test_schedule_failure_closes_coroutine_and_resets_inflight |
| Bucketing min hours / local days | 2 | test_bucket_forecast_inputs_local_days_and_partial_drop |
| Bucketing negative change dropped | removed | **GREEN -> new** test_bucket_drops_negative_change_rows |
| database local week/month/midnight helper/tomorrow weekday/local bounds | 5 | test_week_and_month_windows_use_local_midnight, test_predict_energy_tomorrow_*, test_refresh_period_mix_reads_whole_local_days |
| database get_energy_history_kwh_rows | `AND 1=0` | **GREEN -> new** test_history_kwh_rows_returns_interval_rows_since (real schema) |
| D9 hvac_zone formula/base-None/AC subtraction, weekly persistence, v2 const | 5 | test_hvac_zone_*, test_consumption_arms_* |
| D9 trailing_mean excludes target | range(0,..) | **GREEN -> new** test_trailing_mean_excludes_target_day |
| D9 dow_legacy adjustment factor | dropped | **GREEN -> new** test_dow_legacy_arm_applies_adjustment_factor |
| database get_energy_daily_balance_recent order | (equivalent -- DB6 RED via bias window test) | n/a |

## Specific judgements requested
- **test_forecast_service_migration.py narrowed source-grep** (`"await self._refresh_forecast_cache()" in body`, bug class #62): converted to behavioural -- removed; replaced by `test_predicted_async_update_refreshes_forecast_cache_behaviourally` (6 classes, real async_update, counts the refresh). Today/Tomorrow sensors are covered behaviourally by Build 2 tests (S5/D3k/D4m RED).
- **test_energy_savings_unification.py::test_lifetime_survives_row_prune**: confirmed hollow (re-implemented retired `max(baseline, live)` on literals; no production code touched; S3/S3b/S3c never reached it). Removed; replaced by `test_signed_savings_flow_through_real_table_to_lifetime_sensor` (real arbitrage_cycles table +3.00/-5.00 -> query_arbitrage_savings_total -> real sensor `_arb_lifetime` = -2.00 despite baseline +1.00; empty table -> baseline fallback).

## Residual (LOW, not blocking)
- Week/Month cost sensors' `now.date()` price day is not day-discriminated (Today/Tomorrow are). Week/month use the flat-mix pricer; a wrong day only shifts the hour-weighted rate slightly.
- S3 relies on the documented FENCE (no prune of arbitrage_cycles); no test enforces absence of a prune (comment-only fence).

## Verdict
**SHIP** from the test-authority framing: every enumerated load-bearing site now goes RED under a specific named test; 17 initially-surviving sites closed with committed tests; tree clean (only intended test changes + this doc).

# EC storm Stage B+C — Tier-3 Review C (test authority via real per-site mutation)

Branch `feature/ec-stage-b`, HEAD `c07d4388b`. Date 2026-10-17. Framing C only; no code fixed.

**Diff base used:** `git merge-base HEAD develop` = `88dd37aa0`. The brief's `f9f33fc52` (Stage A merge commit) is NOT an ancestor of HEAD (it differs from 88dd37aa0 by one README only, no code), so the code diff `88dd37aa0..HEAD` (12 files, +1895/-160) was used; `f9f33fc52..HEAD` shows the identical code stat.

## Method
- Reused the crashed attempt's spec (`mut_spec_reviewC.json`, 144 sites) after verifying every `old` string still matches current source exactly once (0 stale). Added 14 Review-B fix-up sites (spec kept outside the repo): `weather_manager._maybe_hourly_catch_up` call + guards + tracking + teardown, and `energy_battery` full-hold degraded `envoy_available=False` (+ the pre-onset twin).
- One mutation at a time, written and restored in one Python step (try/finally); `__pycache__` removed with Python and `PYTHONDONTWRITEBYTECODE=1` before every run. Scoped suite: 9 test files (cycle tests + mutated-module tests, 1855 tests, baseline green in ~12 s), `-x`.
- Every scoped-survivor was re-run against the WIDE set (69 files mentioning inclement/weather_manager/polygon/storm_guard/forecast_confirm/BatteryStrategy; 11 pre-existing failures, name-diffed against that baseline). Mutants BC7/BC8 needed `nth` disambiguation and were re-run.
- Result: 158 mutations: **131 RED, 27 SURVIVED** (26 survived wide as well; BC3b is RED only in the legacy `test_v47x_weather_manager.py`). Source verified `git diff --quiet` clean after every batch.

## Review B fix-up sites (new in 186364ed3 / 95ecb7430)
| Site | Mutation | Result |
|---|---|---|
| weather_manager.py:819 call to `_maybe_hourly_catch_up` | dropped | RED test_provider_recovery_after_boot_refreshes_hourly_immediately |
| :832 has-rows guard | dropped | RED test_hourly_catch_up_not_retriggered_once_rows_exist |
| :834 unavailable/unknown guard | dropped | RED test_provider_recovery_after_boot_refreshes_hourly_immediately |
| :838 coroutine | swapped to `_refresh_all_providers` | RED (same) |
| debounce `pending is not None and not pending.done()` | removed | RED test_hourly_catch_up_not_retriggered_once_rows_exist |
| `_hourly_catch_up_task = task` | dropped | RED (same, via debounce) |
| `not pending.done()` | `pending is not None` (stuck after first task finishes) | **SURVIVED** |
| `_pending_refresh_tasks.add(task)` in catch-up | dropped (task untracked, teardown cannot cancel) | **SURVIVED** |
| async_teardown `task.cancel()` | dropped | **SURVIVED** |
| `not isinstance(task, asyncio.Future)` test-double guard | dropped | SURVIVED (low value) |
| `not entity_id` guard / `new_state is None` guard | dropped / inverted | SURVIVED scoped; new_state inversion RED only in legacy test_v47x_weather_manager |
| energy_battery.py:6321 full-hold degraded `_res["envoy_available"]=False` | dropped | RED test_full_hold_degraded_precharge_reports_envoy_unavailable |
| energy_battery.py:6322 `_stamp_grid_buy(_res, decision)` at that site | replaced by `return _res` | **SURVIVED** |
| energy_battery.py:6396 pre-onset twin | dropped | RED test_preonset_degraded_fresh_decision_control |

## SURVIVED mutants (each = untested site)
| Site | Mutation | Why it matters | Sev |
|---|---|---|---|
| inclement.py:1337 `forecast_confirms` freeze | `tmin is None or ...` (no temperature confirms) | Fail-open of INV-6(vii) forecast-confirmed buy when an outlook has hours but no temps (e.g. precip-only rows) | MEDIUM |
| inclement.py:1348 convective | precip branch dropped (`False or conditions`) | Half of the convective confirm untested; precipitation-only confirmation can silently stop | MEDIUM |
| inclement.py:148 polygon top-up `stop` | `stop = cap_end` ignoring `r.end` | Top-up keeps buying after the alert ended (up to cap) | MEDIUM |
| inclement.py:149 | `start<=now` dropped | Top-up fires before polygon onset | MEDIUM |
| inclement.py:140 | `cap<=0` kill switch dropped | The documented knob=0 kill switch has no test | MEDIUM |
| inclement.py:162 | `eligible` counts polygon rows | Polygon-local rows feed the non-polygon eligibility leg | MEDIUM |
| inclement.py:167 | prepare eligibility ignores `cls == pclass` | Watch-class eligibility can enable a warn-class prepare | MEDIUM |
| inclement.py:956 | `prows` not class-filtered | Key row/latch id may come from the wrong class | LOW |
| inclement.py:981 | full_hold shadow `return base` removed | Prepare fields/engaged state computed under an active full_hold | MEDIUM |
| inclement.py:479 | lead window ignores the `preonset_lead_h` argument | Concept split masked by coincidental equality (default == knob, Bug Class #63) | MEDIUM |
| inclement.py:298/308 | code-row precedence swapped / code match disabled | Code-over-name resolution and code-only resolution untested | LOW |
| energy_battery.py:2879 `_cfg_buy_commanded` | `charge_from_grid` kept-check skipped | Stamp/latch can fire for a buy that the result chokepoint withheld | MEDIUM |
| energy_battery.py:6322 | stamp at full-hold degraded site removed | New Review-B site; buy-confirmed attribute not asserted there | MEDIUM |
| energy_battery.py (pre-onset call) | `cloud_withhold_exempt=True` dropped | Documented unreachable on cloud tier (Review C L1): equivalent mutant | LOW |
| energy.py Storm Guard registry resolve | platform filter dropped | Single-match + suffix filters still catch it in tests | LOW |
| weather_manager.py:993 / :972 / :995 / :997 | pop/mm `elif`->`if`; slot not floored; gust and conditions not aggregated | Outlook aggregation not asserted for these fields (conditions feeds the convective confirm, `F7` is RED only because tests inject the Outlook directly) | LOW / MEDIUM (conditions, slot floor) |
| weather_manager.py refresh lock | `async with self._refresh_lock` removed | Concurrent refresh race untested | LOW |
| weather_manager.py catch-up | `not pending.done()` -> `pending is not None`; task not added to `_pending_refresh_tasks`; teardown `task.cancel()` dropped | Bug Class #19 (untracked task): the B-MED-1 fix claims tracking + teardown cancel and nothing asserts either; a stuck debounce silently disables later recoveries | MEDIUM |
| weather_manager.py | `not entity_id` guard; `isinstance(Future)` guard | Defensive, near-equivalent | LOW |

## RED mutants (123 + the 8 above, test that failed)
| # | Site | Mutation | RED test |
|---|---|---|---|
| I1 | inclement.py:930 | zbc drop eligible | test_ec_stage_b_preonset_precharge.py::test_severe_thunderstorm_watch_never_precharges |
| I2 | inclement.py:931 | zbc drop confirmed | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_verified_local_any_tou[now2] |
| I3 | inclement.py:1071 | warn zone_ok drop buy_ok | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_verified_local_any_tou[now2] |
| I3b | inclement.py:1071 | warn zone_ok drop bottom | test_ec_stage_b_preonset_precharge.py::test_fullhold_precharge_ineligible_peak_nonpolygon |
| I3c | inclement.py:1068 | warn buy_ok forced True | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_verified_local_any_tou[now2] |
| I4 | inclement.py:1073 | poly import guard dropped | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_respects_enabled_import_guard |
| I4b | inclement.py:1073 | poly leg ignores topup flag | test_ec_stage_b_preonset_precharge.py::test_fullhold_precharge_ineligible_peak_nonpolygon |
| I5 | inclement.py:1143 | watch-bottom buy gate bypass | test_ec_stage_b_preonset_precharge.py::test_severe_thunderstorm_watch_never_precharges |
| I5b | inclement.py:1140 | watch-bottom buy_ok forced | test_ec_stage_b_preonset_precharge.py::test_severe_thunderstorm_watch_never_precharges |
| I6 | inclement.py:989 | preonset zbc dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[ineligible] |
| I7 | inclement.py:989 | preonset bottom dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[not_bottom] |
| I8 | inclement.py:993 | preonset reached-state dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_latch_no_flap |
| I9 | inclement.py:992 | preonset soc<floor dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[soc_at_floor] |
| I10 | inclement.py:985 | preonset option gate dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[option_off] |
| I11 | inclement.py:968 | high=True | test_ec_stage_b_preonset_precharge.py::test_preonset_watch_floor_uncorroborated |
| I12 | inclement.py:965 | watch_confirmed False | test_ec_stage_b_preonset_precharge.py::test_preonset_watch_floor_uncorroborated |
| I13 | inclement.py:970 | floor drops lower max | test_ec_stage_b_preonset_precharge.py::test_preonset_config_extremes[80-50-60-80] |
| I13b | inclement.py:970 | floor ignores knob | test_ec_stage_b_preonset_precharge.py::test_preonset_floor_registered_before_onset |
| I14 | inclement.py:979 | latch never reaches | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_latch_no_flap |
| I15 | inclement.py:1006 | solar test dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[solar_closes] |
| I16 | inclement.py:995 | engaged short-circuit dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_latch_no_flap |
| I18 | inclement.py:951 | latch cleanup dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates_positive_control |
| I19 | inclement.py:1019 | buy attr union dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_buy_reports_forecast_confirmed_fusion_direct |
| I20 | inclement.py:1104 | forecast corroboration dropped | test_ec_stage_b_preonset_precharge.py::test_forecast_confirms_freeze_watch |
| P1 | inclement.py:148 | cap window dropped | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_cap_expires |
| P2b | inclement.py:140 | unverified-feed kill dropped | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_unverified_locality_refused |
| P3 | inclement.py:143 | polygon eligible dropped | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_requires_eligible_row |
| C1 | inclement.py:261 | onset ignored | test_ec_stage_b_classification.py::test_wiy_is_notice_never_hold |
| C2 | inclement.py:511 | prepare polygon exclusion dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_polygon_excluded |
| C3 | inclement.py:512 | lead window dropped | test_ec_stage_b_goldens.py::test_preonset_noop_byte_identical[01-15|00|wsw_far|soc50] |
| C4 | inclement.py:510 | prepare class gate dropped | test_ec_stage_b_classification.py::test_wiy_is_notice_never_hold |
| C5 | inclement.py:264 | end fallback unbounded | test_ec_stage_b_classification.py::test_unbounded_alert_capped |
| C6 | inclement.py:517 | expired not skipped | test_ec_stage_b_classification.py::test_wiy_is_notice_never_hold |
| C7 | inclement.py:507 | preonset split dropped | test_ec_stage_b_classification.py::test_wiy_is_notice_never_hold |
| C9 | inclement.py:296 | substring name match | test_ec_stage_b_classification.py::test_freeze_products_hold |
| C11 | inclement.py:296 | name match disabled | test_ec_stage_b_classification.py::test_update_message_kept_cancel_dropped |
| F1 | inclement.py:1311 | outlook None confirms | test_ec_stage_b_classification.py::test_battery_passes_engine_bottom_rate_into_fusion |
| F3 | inclement.py:1337 | freeze threshold dropped | test_ec_stage_b_preonset_precharge.py::test_forecast_confirms_freeze_watch |
| F4 | inclement.py:1333 | apparent never used | test_ec_stage_b_preonset_precharge.py::test_apparent_temperature_confirm[Wind Chill Warning-30.0--5.0-True] |
| F4b | inclement.py:1334 | apparent for ALL freeze products | test_ec_stage_b_preonset_precharge.py::test_apparent_temperature_confirm[Hard Freeze Warning-30.0--5.0-False] |
| F5 | inclement.py:1340 | winter precip dropped | test_ec_stage_b_preonset_precharge.py::test_forecast_confirms_predicates[Winter Storm Warning-outlook3-False] |
| F6 | inclement.py:1340 | winter temp dropped | test_ec_stage_b_preonset_precharge.py::test_zone_buy_requires_forecast_confirmation |
| F7 | inclement.py:1348 | convective cond dropped | test_ec_stage_b_preonset_precharge.py::test_forecast_confirms_predicates[Severe Thunderstorm Watch-outlook7-True] |
| F9 | inclement.py:1327 | mm threshold dropped | test_ec_stage_b_preonset_precharge.py::test_forecast_confirms_predicates[Winter Storm Warning-outlook5-True] |
| F10 | inclement.py:1325 | pop threshold dropped | test_ec_stage_b_preonset_precharge.py::test_fullhold_precharge_eligible_warn |
| F11 | inclement.py:1313 | unknown family confirms | test_ec_stage_b_preonset_precharge.py::test_forecast_confirms_predicates[Wind Advisory-outlook9-False] |
| B1 | energy_battery.py:2934 | confirm latch read dropped | test_ec_stage_b_preonset_precharge.py::test_zone_buy_forecast_latch_no_flap |
| B2 | energy_battery.py:2921 | latch purge dropped | test_ec_stage_b_preonset_precharge.py::test_zone_buy_forecast_latch_no_flap |
| B2b | energy_battery.py:2921 | latch purge always | test_ec_stage_b_preonset_precharge.py::test_zone_buy_forecast_latch_no_flap |
| B3 | energy_battery.py:2955 | latch never stored | test_ec_stage_b_preonset_precharge.py::test_zone_buy_forecast_latch_no_flap |
| B4 | energy_battery.py:2932 | polygon not skipped | test_ec_stage_b_preonset_precharge.py::test_fullhold_precharge_mixed_contributors_any |
| B5 | energy_battery.py:2925 | prepare records excluded | test_ec_stage_b_preonset_precharge.py::test_forecast_window_capped |
| B6 | energy_battery.py:2940 | window start clamp dropped | test_ec_stage_b_preonset_precharge.py::test_forecast_window_capped |
| B7 | energy_battery.py:2943 | window cap dropped | test_ec_stage_b_preonset_precharge.py::test_forecast_window_capped |
| B8 | energy_battery.py:2951 | no-outlook confirms | test_ec_stage_b_classification.py::test_battery_passes_engine_bottom_rate_into_fusion |
| B9 | energy_battery.py:2893 | stamp ungated | test_ec_stage_b_preonset_precharge.py::test_fullhold_stripped_turn_on_no_stamp |
| B10b | energy_battery.py:2881 | commanded: ignore turn_on | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates_positive_control |
| B10c | energy_battery.py:2883 | commanded: state fallback always | test_ec_stage_b_preonset_precharge.py::test_preonset_stripped_turn_on_no_latch_no_stamp |
| B11 | energy_battery.py:6400 | latch set ungated | test_ec_stage_b_preonset_precharge.py::test_preonset_stripped_turn_on_no_latch_no_stamp |
| B12 | energy_battery.py:6354 | arbitrage yield dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[arbitrage_charge] |
| B12b | energy_battery.py:6354 | attain yield dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[attain_charging] |
| B13 | energy_battery.py:6358 | blind refusal dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates[degraded_stale] |
| B14 | energy_battery.py:6845 | reg floor ignores preonset (partial) | test_ec_stage_b_preonset_precharge.py::test_preonset_partial_hold_takes_max |
| B14b | energy_battery.py:6848 | reg floor allow_discharge none | test_ec_stage_b_preonset_precharge.py::test_preonset_floor_registered_before_onset |
| B14c | energy_battery.py:6845 | reg floor min not max | test_ec_stage_b_preonset_precharge.py::test_preonset_partial_hold_takes_max |
| B15 | energy_battery.py:5916 | stamp entry-reset dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates_positive_control |
| B15b | energy_battery.py:5916 | engaged-id entry-reset dropped | test_ec_stage_b_preonset_precharge.py::test_observation_rollback_keeps_prior_engaged_latch |
| B16 | energy_battery.py:2854 | stamp zone cands no confirm | test_ec_stage_b_preonset_precharge.py::test_zone_stamp_names_confirmed_record[True] |
| B17 | energy_battery.py:2858 | stamp pick order-dependent | test_ec_stage_b_preonset_precharge.py::test_zone_stamp_key_order_independent[True] |
| B18 | energy_battery.py:6378 | preonset reason/degraded clear dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_degraded_fresh_decision_control |
| B20 | energy_battery.py:6385 | preonset reserve_level dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_routes_through_result |
| B21 | energy_battery.py:2694 | knob read ignored | test_ec_stage_b_preonset_precharge.py::test_preonset_config_extremes[20-50-100-100] |
| B22 | energy_battery.py:2798 | knob not passed to decider | test_ec_stage_b_preonset_precharge.py::test_preonset_config_extremes[20-50-100-100] |
| B23 | energy_battery.py:2815 | confirmed not passed | test_ec_stage_b_preonset_precharge.py::test_fullhold_precharge_eligible_warn |
| B24 | energy_battery.py:2816 | latch not passed | test_ec_stage_b_preonset_precharge.py::test_preonset_precharge_gates_positive_control |
| B25 | energy_battery.py:2814 | bottom rate not passed | test_ec_stage_b_classification.py::test_battery_passes_engine_bottom_rate_into_fusion |
| B27 | energy_battery.py:2799 | polygon guard not passed | test_ec_stage_b_preonset_precharge.py::test_polygon_topup_respects_enabled_import_guard |
| B28 | energy_battery.py:3026 | feed health staleness dropped | test_ec_stage_b_classification.py::test_steady_alert_not_stale |
| B29 | energy_battery.py:2805 | confirmed set stored | test_ec_stage_b_preonset_precharge.py::test_zone_stamp_names_confirmed_record[True] |
| B30 | energy_battery.py:2848 | polygon stamp leg uses cap window | test_ec_stage_b_preonset_precharge.py::test_polygon_stamp_names_in_window_record |
| E1 | energy.py:9401 | obs-mode notify guard dropped | test_ec_stage_b_preonset_precharge.py::test_grid_buy_no_nm_and_latch_rolled_back_in_observation_mode |
| E2 | energy.py:9410 | obs-mode latch rollback dropped | test_ec_stage_b_preonset_precharge.py::test_grid_buy_no_nm_and_latch_rolled_back_in_observation_mode |
| E3 | energy.py:9415 | NM boot seed dropped | test_ec_stage_b_preonset_precharge.py::test_grid_buy_episode_notifies_once |
| E4 | energy.py:9424 | NM episode dedup dropped | test_ec_stage_b_preonset_precharge.py::test_grid_buy_episode_notifies_once |
| E5 | energy.py:9428 | NM notified.add dropped | test_ec_stage_b_preonset_precharge.py::test_grid_buy_episode_notifies_once |
| E7 | energy.py:6467 | grid_buy_notify not wired | ERROR:custom_components.universal_room_automation.domain_coordinators.energy:Error in energy decision cycle |
| E8 | energy.py:6466 | storm_guard_tick not wired | ERROR:custom_components.universal_room_automation.domain_coordinators.energy:Error in energy decision cycle |
| E9 | energy.py:6462 | rows_tick not wired | ERROR:custom_components.universal_room_automation.domain_coordinators.energy:Error in energy decision cycle |
| E10 | energy.py:9344 | empty-platform kill dropped | test_ec_stage_b_preonset_precharge.py::test_storm_guard_tripwire_disabled_empty_platform |
| E11 | energy.py:9356 | single-match rule dropped | test_ec_stage_b_preonset_precharge.py::test_storm_guard_entity_resolved_from_registry |
| E13 | energy.py:9352 | suffix filter dropped | test_ec_stage_b_preonset_precharge.py::test_storm_guard_entity_resolved_from_registry |
| E14 | energy.py:9308 | sg: prev==on refire | test_ec_stage_b_preonset_precharge.py::test_storm_guard_tripwire_fires_once_on_transition |
| E15 | energy.py:9300 | sg: boot seed dropped | test_ec_stage_b_preonset_precharge.py::test_storm_guard_tripwire_on_at_boot_is_log_only |
| E16 | energy.py:9293 | sg: unavailable not skipped | test_ec_stage_b_preonset_precharge.py::test_storm_guard_tripwire_ignores_unavailable |
| E17 | energy.py:9320 | sg: NM not created | test_ec_stage_b_preonset_precharge.py::test_storm_guard_tripwire_fires_once_on_transition |
| E18 | energy.py:9310 | sg: anomaly not created |  |
| E19 | energy.py:9299 | sg: seed sets prev dropped | test_ec_stage_b_preonset_precharge.py::test_storm_guard_tripwire_fires_once_on_transition |
| E20 | energy.py:9335 | sg: cached eid re-resolve dropped | test_ec_stage_b_preonset_precharge.py::test_storm_guard_reresolves_when_cached_entity_vanishes |
| W1 | weather_manager.py:935 | precip unit conv dropped | test_ec_stage_c_hourly_outlook.py::test_precipitation_unit_converted_to_mm[cm-0.15-1.5] |
| W2 | weather_manager.py:71 | in factor | test_ec_stage_c_hourly_outlook.py::test_precipitation_unit_converted_to_mm[in-0.1-2.54] |
| W2b | weather_manager.py:71 | cm factor | test_ec_stage_c_hourly_outlook.py::test_precipitation_unit_converted_to_mm[cm-0.15-1.5] |
| W3 | weather_manager.py:928 | temp C->F dropped | test_ec_stage_c_hourly_outlook.py::test_celsius_provider_converted |
| W4 | weather_manager.py:931 | apparent C->F dropped | test_ec_stage_c_hourly_outlook.py::test_apparent_temperature_celsius_converted |
| W5 | weather_manager.py:1017 | min_apparent dropped | test_ec_stage_c_hourly_outlook.py::test_apparent_temperature_aggregated |
| W6 | weather_manager.py:990 | apparent not collected | test_ec_stage_c_hourly_outlook.py::test_apparent_temperature_aggregated |
| W7 | weather_manager.py:964 | staleness gate dropped | test_ec_stage_c_hourly_outlook.py::test_forecast_stale_beyond_limit_is_none |
| W7b | weather_manager.py:964 | staleness gate inverted | test_ec_stage_c_hourly_outlook.py::test_backup_policy_owm_then_open_meteo_beyond_horizon |
| W8 | weather_manager.py:966 | outlook reachable filter dropped | test_ec_stage_c_hourly_outlook.py::test_unhealthy_primary_skipped |
| W9 | weather_manager.py:895 | reachable always true | test_ec_stage_c_hourly_outlook.py::test_unhealthy_primary_skipped |
| W9b | weather_manager.py:895 | reachable requires HEALTHY | test_ec_stage_c_hourly_outlook.py::test_condition_stale_providers_still_hourly_fetched_and_used |
| W9c | weather_manager.py:875 | refresh reachable filter dropped | test_ec_stage_c_hourly_outlook.py::test_provider_recovery_after_boot_refreshes_hourly_immediately |
| W10 | weather_manager.py:1005 | backup->all providers | test_ec_stage_c_hourly_outlook.py::test_backup_policy_owm_then_open_meteo_beyond_horizon |
| W12 | weather_manager.py:982 | window end inclusive | test_ec_stage_c_hourly_outlook.py::test_backup_policy_owm_then_open_meteo_beyond_horizon |
| W16 | weather_manager.py:1011 | temp min->max | test_ec_stage_c_hourly_outlook.py::test_backup_policy_owm_then_open_meteo_beyond_horizon |
| W17 | weather_manager.py:241 | hourly timer not registered | test_ec_stage_c_hourly_outlook.py::test_forecast_timer_torn_down |
| W19 | weather_manager.py:960 | provider order shuffled | test_ec_stage_c_hourly_outlook.py::test_backup_policy_owm_then_open_meteo_beyond_horizon |
| W20 | weather_manager.py:882 | fetched_at stamp stale | test_ec_stage_c_hourly_outlook.py::test_backup_policy_owm_then_open_meteo_beyond_horizon |
| N1 | number.py:86 | number not registered | test_runtime_smoke.py::test_number_platform_registers_inclement_preonset_floor |
| N2 | number.py:1651 | number seed ignores options | test_ec_stage_b_preonset_precharge.py::test_preonset_floor_number_seeds_from_options[opts0-65] |
| N3 | number.py:1708 | number key wrong | test_ec_stage_b_preonset_precharge.py::test_preonset_floor_number_seeds_from_options[opts0-65] |
| N4 | __init__.py:7457 | suppress set 1 entry dropped | test_part2_ec_hc_writeback.py::test_apply_in_place_dispatch_coverage |
| N5 | __init__.py:7457 | suppress set 2 entry dropped | test_part2_ec_hc_writeback.py::test_options_reload_suppress_keys_membership_exact |
| N6 | energy_const.py:749 | default changed | test_runtime_smoke.py::test_number_platform_registers_inclement_preonset_floor |
| BC1 | weather_manager.py:819 | catch-up call dropped | test_ec_stage_c_hourly_outlook.py::test_provider_recovery_after_boot_refreshes_hourly_immediately |
| BC2 | weather_manager.py:830 | has-rows guard dropped | test_ec_stage_c_hourly_outlook.py::test_hourly_catch_up_not_retriggered_once_rows_exist |
| BC3 | weather_manager.py:833 | unavailable-skip dropped | test_ec_stage_c_hourly_outlook.py::test_provider_recovery_after_boot_refreshes_hourly_immediately |
| BC4 | weather_manager.py:836 | debounce dropped | test_ec_stage_c_hourly_outlook.py::test_hourly_catch_up_not_retriggered_once_rows_exist |
| BC5 | weather_manager.py:845 | task handle not stored | test_ec_stage_c_hourly_outlook.py::test_hourly_catch_up_not_retriggered_once_rows_exist |
| BE1 | energy_battery.py:6321 | full-hold envoy_available dropped | test_ec_stage_b_preonset_precharge.py::test_full_hold_degraded_precharge_reports_envoy_unavailable |
| BE2 | energy_battery.py:6321 | preonset envoy_available dropped | test_ec_stage_b_preonset_precharge.py::test_preonset_degraded_fresh_decision_control |
| BC8 | weather_manager.py:838 | catch-up runs wrong coroutine | test_ec_stage_c_hourly_outlook.py::test_provider_recovery_after_boot_refreshes_hourly_immediately |

## Verdict: **FIX-REQUIRED** (no HIGH, 14 MEDIUM survivors = untested load-bearing sites)
Must-fix (add discriminating tests; do not change source):
1. `forecast_confirms`: no-temperature freeze must NOT confirm; convective precip-only confirm; (fail-open sites).
2. `polygon_topup_records`: window end (`r.end < cap_end`), pre-start tick, `cap<=0` kill; `_precharge_flags` polygon-excluded eligibility and class-matched prepare eligibility.
3. `_prepare_decision`: active full_hold with a prepare row must leave prepare fields default; lead window must honor the `preonset_lead_h` argument (use a non-default value, #63).
4. `_cfg_buy_commanded` withheld-write case and the stamp at the full-hold degraded site (energy_battery.py:6322).
5. `_maybe_hourly_catch_up`: assert the task is in `_pending_refresh_tasks`, is cancelled by `async_teardown`, and that a second recovery after the first catch-up completed schedules again.
6. Weather aggregation: assert `conditions` and slot-floor in `outlook_for_window`.
LOW survivors can ride with the same pass (1-30 LoC each). Re-verify with the same mutation list after the test add.

Cleanliness: after the last drill `git status --short` shows only the three pre-existing untracked files (`mut_drill_reviewC.py`, `mut_spec_reviewC.py`, `mut_spec_reviewC.json`); `git diff --quiet` clean.

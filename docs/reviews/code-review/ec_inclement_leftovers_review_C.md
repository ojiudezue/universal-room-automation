# EC inclement leftovers — Review C (test authority, real per-site source mutation)

Branch `feature/ec-inclement-leftovers` @ 0fe1948b vs `pre-review-ec-inclement-leftovers`.
Method: one production-source edit per row, `__pycache__` purged, `PYTHONDONTWRITEBYTECODE=1`,
named test files only (`-x`, `-m ""`), restored in `finally`, worktree `git status` clean after.
PR = `test_ec_inclement_leftovers_period_rank.py`, ENV = `..._envoy.py`.

| Site | Mutation | Test that went RED | Result |
|---|---|---|---|
| energy.py billing displaced (~4634) | `above_bottom_rate` -> literal | PR::test_apply_arbitrage_tick_routes_through_above_bottom_rate[table0-peak-False] | RED |
| energy.py `_update_energy_situation` | -> literal | PR::test_update_energy_situation_routes_through_above_bottom_rate | RED |
| energy.py `_update_load_shedding` | -> literal | PR::test_update_load_shedding_routes_through_above_bottom_rate | RED |
| energy_pool EVSE pause | -> literal | PR::test_evse_tou_pause_routes_through_above_bottom_rate | RED |
| energy_pool plug pause | -> literal | PR::test_plug_tou_pause_routes_through_above_bottom_rate | RED |
| hvac_predict next period | -> literal | PR::test_intent_anchor_next_period_routes_through_above_bottom_rate | RED |
| hvac_predict current period | -> literal | PR::test_intent_anchor_current_period_routes_through_above_bottom_rate | RED |
| sensor.py next boundary | -> literal | PR::test_situation_next_boundary_routes_through_above_bottom_rate | RED |
| plug `tou_engine=self._tou` wire-in (energy.py ~7676) | arg removed | test_ec_degraded_data_p1::test_decision_cycle_threads_tou_engine_into_plug_tou_path | RED |
| H1 shape: load-shed ranks clock period | passed period -> `get_current_period()` | PR::test_update_load_shedding_routes... | RED |
| H1 shape: situation ranks clock period | same | PR::test_update_energy_situation_routes... | RED |
| H1 shape: helper ignores passed period | `period_rank(season, tou.get_current_period())` | PR::test_above_bottom_rate_full_year_sweep_matches_literal | RED |
| helper: drop isinstance guard | `rank is not None` | PR::test_above_bottom_rate_fallbacks[peak] | RED |
| helper: allow bool rank | drop bool exclusion | PR::test_above_bottom_rate_fallbacks[off_peak] | RED |
| helper: no literal fallback | `return False` | PR::test_above_bottom_rate_fallbacks[peak] | RED |
| helper: `rank > 0` -> `>= 0` | | PR::..._full_year_sweep_matches_literal | RED |
| helper: exception swallow narrowed | `except KeyError` | PR::test_above_bottom_rate_fallbacks[peak] | RED |
| `season_at` always None | | PR::test_above_bottom_rate_season_boundary_uses_transition_season | RED |
| `season_at` exception swallow narrowed | | PR::test_season_at_failures_are_none | RED |
| hvac future season (M2/H1) | `season_at(tou,_next_when)` -> `_tou_now` | PR::test_intent_anchor_season_boundary_uses_transition_season | RED |
| sensor future season | `_next_when` -> `dt_util.now()` | PR::test_situation_next_boundary_season_boundary | RED |
| **hvac CURRENT-period season** | `season_at(tou,_tou_now)` -> `_next_when` | none (23 passed) | **GREEN** |
| D5 `envoy_available` -> True, site 1 | | ENV::test_attain_hold_current_degraded_reports_envoy_unavailable[defer/warmup] + counter test | RED |
| D5 -> True, site 2 | | ENV::test_decision_dicts_carry_non_literal_envoy_available (AST pin only) | RED |
| D5 key dropped, site 1 / site 2 / both | | behavioral tests (site 1), AST pin (site 2) | RED |
| item 2: re-add `_check_legacy_threat_list` | stub method | test_ec_outage_ledger::test_async_setup_arms_outage_ledger | RED |
| item 2: re-add `CONF_INCLEMENT_POWER_THREAT_EVENTS` / `DEFAULT_...` / strings.json issue | | test_ec_stage_e_selection::test_legacy_plumbing_removed (all three) | RED |
| period-literal pin: inject `'peak'` in new function | | PR::test_period_literal_sites_pinned | RED |
| period-literal pin: remove a pinned literal | | PR::test_period_literal_sites_pinned | RED |

## Findings

- **HIGH (rule: GREEN = untested site) — hvac_predict current-period season is unpinned.**
  `hvac_predict.py` `above_bottom_rate(tou, season_at(tou, _tou_now), current)`: swapping `_tou_now` for
  `_next_when` leaves PR + the touched suite green. The season-boundary tests only exercise the NEXT-period site.
  Real-world blast radius is tiny (only differs when the transition crosses a season boundary, and only
  affects the "current period" intent anchor), but plan M2 explicitly specified `now` for this site.
  Fix: add a boundary test (current period ranked in today's season while the transition falls in the next season).
- **LOW — D5 second `envoy_available` dict is pinned only by the AST predicate**, no behavioral test for that
  site (mutation is still RED via the pin). Acceptable; optional behavioral test.

## Verdict: FIX-REQUIRED (one GREEN site: hvac current-period season). All other 30 mutations RED.
Worktree clean after all drills.

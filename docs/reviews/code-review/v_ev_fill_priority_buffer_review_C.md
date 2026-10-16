# EV fill-priority re-pause band: Tier-3 Review C (test authority via per-site source mutation)

Branch `feature/ev-fill-priority-buffer` at HEAD `c22579c70`. Base `67e5c66e2`, which is the merge-base (verified). Worktree: `.claude/worktrees/review-ev-buffer-C`.

## Verdict: SHIP (2 LOW gaps, both on the plug side; fix optionally in-cycle)

## Method
Each mutation was applied to one site in production source (`energy_pool.py` / `energy.py`). The drill wrote the file, ran pytest, then restored the saved original in a `try/finally`. Every run used `PYTHONDONTWRITEBYTECODE=1` and cleared every `__pycache__` first. Test set per run (739 tests): `test_ev_fill_priority_repause_band`, `test_energy_pool_fill_priority`, `test_ev_arbitrage_release_fill_priority`, `test_energy_pause_release_hygiene`, `test_ec_degraded_data_p1`, `test_energy_evse`, `test_energy_pool_drain`, `test_energy_pool_drain_release`, `test_evse_charge_onset`, `test_arbitrage_*`, `test_evse_drain_precedence*`. `git status` was clean after each run (only the untracked drill dir).

**Baseline:** the unmutated run gives 1 failed / 738 passed. `test_dp_enable_switch_registered_in_setup_entry` fails on clean HEAD in this combined file set, so it is pre-existing and unrelated (it is a setup_entry registration test). It is excluded from every row below.

**Drill-targeting correction:** my first pass on the EV D2 peers `us/arbitrage/load_shed/blind_window/dp` and the proactive re-add matched an EARLIER identical line elsewhere in `energy_pool.py`. For example, `or evse_id in self._paused_by_us` appears 7 times. Those rows came back GREEN for that reason. I re-ran them anchored inside the D2 block, and all turned RED (rows marked *anchored*). Lesson: a string-replace mutation has to be anchored to its block.

## Drill table
| # | Site neutered | RED (specific test) |
|---|---|---|
| 1 | EV producer: latch on every resume (drop `resume_soc_met` discriminator) | `test_a10_forecast_decay_resume_no_latch_then_legacy_repause` |
| 2 | Plug producer: same | `test_a10_plug_forecast_decay_no_latch` |
| 3 | EV producer: never latch | 33 fail, incl. `test_a1_latched_walk_80_79_no_membership_transitions` |
| 4 | Plug producer: never latch | 15 fail, incl. `test_a6_plug_band_suppresses_chatter` |
| 5 | Plug stored value 0 (threshold detached) | `test_a3_plug_boundary_77_0_holds_76_9_pauses` and 4 more |
| 6 | EV pause gate ignores latch | 11 fail, incl. `test_a3_soc_77_0_inside_band_no_pause` |
| 7 | Plug pause gate ignores latch | `test_a6_plug_band_suppresses_chatter` and 4 more |
| 8 | D1 EV inert clear | `test_a9_inert_night_clears_latch_morning_first_pause_at_79`, `test_a9_other_inert_periods_clear_latch[peak/mid_peak]` |
| 9 | D1 plug inert clear | `test_a9_plug_inert_clears_latch` |
| 10 | D3 EV force clear removed | `test_a7_force_charge_clears_latch_then_first_pause_at_79` |
| 11 | D3 EV clear moved INSIDE the FP-membership guard | `test_a7_force_charge_clears_latch_then_first_pause_at_79` |
| 12 | D3 plug force clear | `test_a7_plug_force_charge_clears_latch` |
| 13 | D4 EV release_all clear | `test_d4_ev_release_all_clears_latch` |
| 14 | D4 plug release_all clear | `test_d4_plug_release_all_clears_latch`, `..._before_grid_charge_return` |
| 15 | D5 EV below-floor pop | 13 fail, incl. `test_a3_soc_76_9_below_floor_pauses_next_tick` |
| 16 | D5 plug below-floor pop | `test_a3_plug_boundary_77_0_holds_76_9_pauses`, `test_a11_plug_sweep_off` |
| 17 | D5 EV `<` to `<=` (77.0 boundary) | `test_a3_soc_77_0_inside_band_no_pause`, `test_extreme_slider_min_50_band_default[47.0-False]` |
| 18 | D5 plug `<` to `<=` | `test_a3_plug_boundary_77_0_holds_76_9_pauses` |
| 19 | D5 EV SOC-None guard to `soc is None or` | `test_a12_soc_none_leaves_latch_untouched` |
| 20 | D5 plug SOC-None guard | `test_a12_plug_soc_none` |
| 21 | D5 EV threshold-change pop | `test_d_l1_threshold_lowered_first_pause_fires` |
| 22 | D5 plug threshold-change pop | `test_d_l1_plug_threshold_lowered_first_pause_fires` |
| 23 | EV band module attr replaced by literal 3 | `test_a4_module_attribute_band_zero_restores_legacy_chatter`, `test_callsite_band_read_at_call_time` |
| 24 | Plug band module attr replaced by literal 3 | `test_a4_plug_module_attribute_band_zero` |
| 25 | EV `repause_band_pct` kwarg ignored | `test_band_zero_sequence_matches_legacy_oracle` and 5 more |
| 26 | **Plug `repause_band_pct` kwarg ignored** | **GREEN**: finding C-L1 |
| 27 | EV clamp `max(0,…)` dropped | GREEN: **equivalent mutant**. A negative floor can never satisfy `soc < floor` for SOC ≥ 0, so behaviour is identical. |
| 28 | Plug clamp `max(0,…)` dropped | GREEN: equivalent (same argument) |
| 29 | EV clamp `max(0)` to `max(50)` | `test_extreme_band_100_latched_floor_zero_no_repause`, `test_extreme_slider_min_50_band_default[47.0-False]` |
| 30 | **Plug clamp `max(0)` to `max(50)`** | **GREEN**: finding C-L2 |
| 31 | D6 EV observation clear | `test_a15_observation_mode_clears_both_latches` |
| 32 | D6 plug observation clear | `test_a15_observation_mode_clears_both_latches` |
| 33 | Prune EV | `test_a16_prune_pops_latch_for_removed_evse` |
| 34 | Prune plug | `test_a16_prune_pops_latch_for_removed_plug` |
| 35 | Arbitrage hand-off per-id latch term | `test_a13_arbitrage_handoff_latched_vs_unlatched_sibling` |
| 36 | D2 EV: re-add `_proactive_offpeak_holds` (*anchored*) | `test_a_high_1_ev_offpeak_ensure_on_does_not_discharge_latch` |
| 37 | D2 plug: re-add `_proactive_offpeak_holds` | `test_a_high_1_plug_offpeak_ensure_on_does_not_discharge_latch` |
| 38-44 | D2 EV peer removed: grid_cap, battery_drain, us*, arbitrage*, load_shed*, blind_window*, dp* (*anchored) | `test_a8_ev_peer_steal_clears_latch[_paused_by_<peer>]`, each its own param |
| 45-47 | D2 plug peer removed: us, battery_drain, load_shed | `test_a8_plug_peer_steal_clears_latch[_paused_by_<peer>]`, each its own param |

## Findings
- **C-L1 LOW (untested site), `energy_pool.py` plug `determine_fill_priority_actions` `_band = ... if repause_band_pct is None else repause_band_pct`.** No plug test passes `repause_band_pct`. Production does not reach it either: `energy.py` passes no `repause_band_pct` at either call site, so the kwarg is a test-only seam. Fix: add one plug test with `repause_band_pct=0` (legacy chatter), or drop the kwarg from the plug signature. Bug class #62-adjacent (untested surface).
- **C-L2 LOW (untested boundary), plug `effective_floor = max(0, soc_threshold - _band)`.** No plug test exercises a floor below 50 (threshold 50 to 52 with band 3, or a band override). The EV side covers this with `test_extreme_slider_min_50_*` and `test_extreme_band_100_*`, but the plug mirror has no extreme tests. With the slider at its legal minimum of 50, the floor is 47, so the plug's 47.0/46.9 boundary is reachable and untested. Fix: parametrize `test_a3_plug_boundary` at threshold 50 (47.0 holds, 46.9 pauses).

## Test quality
- Latches are set by real production paths (`_latch_ev` / `_latch_plug` drive a real pause followed by a SOC-reached resume), not by hand-seeding. The exceptions are the call-site / A15 tests, which seed `{_A: 80}`. That is acceptable because the value equals the configured threshold, and the producer is drilled separately (rows 3-5).
- The tests call the real entry points: `determine_fill_priority_actions`, `determine_actions("off_peak")` (A-HIGH-1), `determine_arbitrage_actions` with two chargers (A13), and `EnergyCoordinator._decision_cycle_body` (call site, band read at call time, D6). No test re-implements a production expression.
- Oracles are literal SOC values (77.0 / 76.9 / 47.0 / 46.9 / 79 / 78), not derived from imported constants. The one constant pin (`== 3`) is a deliberate tripwire on the knob value.
- Gap: there is no plug-side `_decision_cycle_body` latch test. The plug wire-in is covered only by A15 (D6). This is acceptable because the plug call site is unchanged in this diff.

## Verdict
**SHIP.** Every load-bearing site except the two plug-side LOWs turns a specific named test RED when neutered. Three GREEN rows are argued equivalent or test-only: the two `max(0)` drops and the plug kwarg. C-L1 and C-L2 are about 10 LoC of tests each and fit the in-cycle LOW fix-up policy. Neither blocks the ship.

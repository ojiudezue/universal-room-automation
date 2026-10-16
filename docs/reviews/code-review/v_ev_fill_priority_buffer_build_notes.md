# Build notes: EV-FILL-PRIORITY-SOC-CHATTER-1 (fill-priority re-pause band)

- Plan: `docs/planning/PLANNING_ev_fill_priority_soc_buffer.md` Rev 3 (Tier 3)
- Branch: `feature/ev-fill-priority-buffer`, base develop `67e5c66e2`
- Builder: ura-super-builder. HVAC/presence docs don't apply (energy only).

## Falsifiable invariant (plan §3)
- **INV-1:** a latched id (prior SOC-reached resume, no D1-D6 since) with SOC in `[thr-band, thr)` never changes FP membership. SOC 77.0 does not pause; 76.9 pauses.
- **INV-2:** the first pause with no latch is unchanged (`soc < thr`).
- **INV-3:** SOC below the floor pauses on the next tick.
- **INV-4:** an unlatched charger is byte-identical to develop on every path. Every new read is `id in latch`, and the latch is always empty for an unlatched id.

## Sites (file:line on the branch)
`energy_pool.py`:
| Site | EV | Plug |
|---|---|---|
| Latch init | :595 | :3712 |
| D1 inert pop | :2788-2789 | :4535-4536 |
| D5 below-floor sweep (call-time band read) | :2798-2806 | :4540-4548 |
| D2 peer steal (loop top) | :2823-2833 | :4557-4563 |
| D3 force-charge (unconditional) | :2841 | :4570 |
| Consumer (pause gate only) | :2903 | :4608 |
| Producer (`if resume_soc_met`) | :2981-2982 | :4676-4677 |
| Arbitrage hand-off per-id term | :3226 | — |
| D4 `release_all` | :3568 | :4107 (before the `grid_charge_on` return) |
| Prune | :1257-1261 | :4183-4187 |

`energy.py` D6: :6978-6979 (new `else:` on `if not self._observation_mode:` at :6582).

Writers of the latch (re-grepped `_recently_released_by_fill_priority\[.*\] =`): the two producers only. Every other touch is a pop, a clear, or a read.

## Drill table (one site neutered at a time; PYTHONDONTWRITEBYTECODE=1, `__pycache__` cleared, original written back in `finally`, `git status` clean after)
Run: `test_ev_fill_priority_repause_band.py` + `test_energy_pause_release_hygiene.py` (91 tests).

| Site mutated | Result | Specific test that goes RED |
|---|---|---|
| Producer EV (set disabled) | 30 fail | `test_a1_latched_walk_80_79_no_membership_transitions` (+ all EV latch tests) |
| Producer plug | 13 fail | `test_a3_plug_boundary_77_0_holds_76_9_pauses`, `test_a6_plug_band_suppresses_chatter` |
| Producer discriminator EV (`resume_soc_met` → True) | 1 fail | `test_a10_forecast_decay_resume_no_latch_then_legacy_repause` |
| Producer discriminator plug | 1 fail | `test_a10_plug_forecast_decay_no_latch` |
| D1 EV inert | 3 fail | `test_a9_inert_night_clears_latch_morning_first_pause_at_79`, `test_a9_other_inert_periods_clear_latch[peak/mid_peak]` |
| D1 plug inert | 1 fail | `test_a9_plug_inert_clears_latch` |
| D2 EV, each peer conjunct removed separately (8 at b1d5b878d; `proactive_offpeak_holds` removed in the fix-up, so 7 now) | 1 fail each | `test_a8_ev_peer_steal_clears_latch[<that peer>]`, for grid_cap, battery_drain, us, arbitrage, load_shed, blind_window, dp, proactive_offpeak_holds |
| D2 plug, each peer conjunct (4) | 1 fail each | `test_a8_plug_peer_steal_clears_latch[<that peer>]`, for us, battery_drain, load_shed, proactive_offpeak_holds |
| D3 EV force | 1 fail | `test_a7_force_charge_clears_latch_then_first_pause_at_79` |
| D3 plug force | 1 fail | `test_a7_plug_force_charge_clears_latch` |
| D4 EV release_all | 1 fail | `test_d4_ev_release_all_clears_latch` |
| D4 plug release_all removed | 2 fail | `test_d4_plug_release_all_clears_latch`, `..._before_grid_charge_return` |
| D4 plug clear moved AFTER the grid-charge return | 1 fail | `test_d4_plug_release_all_clears_latch_before_grid_charge_return` |
| D5 EV sweep | 11 fail | `test_a3_soc_76_9_below_floor_pauses_next_tick`, `test_a11_sweep_runs_for_off_charger`, ... |
| D5 plug sweep | 3 fail | `test_a3_plug_boundary_77_0_holds_76_9_pauses`, `test_a11_plug_sweep_off` |
| D5 EV `<` → `<=` | 3 fail | `test_a3_soc_77_0_inside_band_no_pause`, `test_a1_...` |
| D5 plug `<` → `<=` | 2 fail | `test_a3_plug_boundary_77_0_holds_76_9_pauses` |
| D5 EV / plug soc-None guard dropped | 1 fail each | `test_a12_soc_none_leaves_latch_untouched` / `test_a12_plug_soc_none` |
| D5 EV band hard-bound to 3 (module attr ignored) | 2 fail | `test_a4_module_attribute_band_zero_restores_legacy_chatter`, `test_callsite_band_read_at_call_time` |
| D5 plug band hard-bound to 3 | 1 fail | `test_a4_plug_module_attribute_band_zero` |
| D5 EV kwarg ignored | 5 fail | `test_band_zero_sequence_matches_legacy_oracle`, `test_extreme_*` |
| D5 EV outer `max(0, …)` dropped | **0 fail: equivalent mutant** | — (a floor below 0 can't be crossed because SOC ≥ 0; kept per plan LOW-10) |
| Consumer EV | 8 fail | `test_a1_...`, `test_callsite_latched_no_pause_at_78_default_band`, `test_a13_...` |
| Consumer plug | 3 fail | `test_a6_plug_band_suppresses_chatter`, `test_a12_plug_soc_none` |
| Arbitrage hand-off per-id term | 1 fail | `test_a13_arbitrage_handoff_latched_vs_unlatched_sibling` |
| D6 EV observation clear | 1 fail | `test_a15_observation_mode_clears_both_latches` |
| D6 plug observation clear | 1 fail | `test_a15_observation_mode_clears_both_latches` |
| Prune EV / plug | 1 fail each | `test_a16_prune_pops_latch_for_removed_evse` / `..._plug` |

Wire-in anchors: the `energy.py` FP call site (~:6817 on develop) and D6 are driven through the real `EnergyCoordinator._decision_cycle_body` (`test_callsite_*`, `test_a15_*`). A13 drives the real `determine_arbitrage_actions` with two chargers.

## F-set on develop `67e5c66e2`
The new file run against the develop sources gives 55 failed and 7 passed. The 7 that pass are regression guards that are green by design: A2 ×2, A13 unlatched-single, A14 cold-latch toggle, callsite-unlatched, and slider-min-50 fresh ×2.

## Config extremes (plan §7), all tested
- **band 0 (kill switch):** reproduces the legacy off/on/off/on sequence.
- **band 100:** a fresh charger at SOC 50 pauses; a latched charger never re-pauses (floor 0).
- **band −5:** legacy behaviour. A latched charger at 79 pauses.
- **thr 50 / band 3:** 47 holds, 46.9 pauses, fresh 49 pauses, 50.0 doesn't.
- **thr 50 / band 0:** 47 and 46.9 both pause.

## Plan discrepancies found (code wins; reported, not improvised)
1. **D6 "existing else-branch" doesn't exist.** `energy.py:6582` `if not self._observation_mode:` had no `else`. I added a minimal `else:` with exactly the two clears the plan specifies.
2. **Attribute name:** the plan says `self._plug`; the real attribute is `self._smart_plugs`.
3. **Class names:** the plan says `EVPool`/`PlugPool`; the classes are `EVChargerController`/`SmartPlugController`. The plug prune is the public `prune_removed_plugs`.
4. **§7 table vs notes on negative band.** The table row "band=−5 → effective_floor 0" contradicts the §7 notes ("floor = threshold → legacy") and §5.3.2 (`max(0, thr − band)` gives 85). I implemented §5.3.2 verbatim. The observable behaviour is legacy (every latched id below threshold is popped by D5), which matches the notes and the row's expected values.
5. **A14 "restore symmetry" drill:** the restore path needed no code change (the latch is RAM-only), so there is no site to neuter. A14 asserts that the restored FP set is present and the latch is empty.

## Review fix-up (after Tier-3 reviews A/B/D on b1d5b878d)
- **A-HIGH-1 (= B-HIGH-1), fixed.** Removed `_proactive_offpeak_holds` from the EV and plug D2 peer lists. It is off-peak ensure-on's own idempotent claim, re-made on every off_peak tick, not a steal. Counting it wiped the latch every tick in the off_peak-daylight FP window. The plan's B1 F4 ruling is reversed for this one peer; dp stays a peer. The A8 parametrization drops it.
  - New tests drive the REAL `determine_actions("off_peak")` between FP ticks: `test_a_high_1_ev_offpeak_ensure_on_does_not_discharge_latch` and `test_a_high_1_plug_offpeak_ensure_on_does_not_discharge_latch`.
- **D-L1, fixed.** The latch value is now the `fill_priority_soc` it was set under, replacing the monotonic time. D5 pops a latch whose stored threshold differs from the current one, so lowering 80 to 70 lets the first pause fire at 69. Tests: `test_d_l1_threshold_lowered_first_pause_fires`, `test_d_l1_plug_threshold_lowered_first_pause_fires`, `test_d_l1_unchanged_threshold_keeps_latch`.
- **B-LOW-1, documented, no code.** A different car replugged inside the band charges from the battery until SOC < floor. The cost is bounded by the band (3 SOC points), and the daily inert window discharges the latch.
- **B-LOW-2, documented, no code.** A restart, reload or observation-mode exit inside the band causes one extra first-pause off/on cycle, because the latch is RAM-only. This matches the plan's A14/D6 intent.
- **D-L2, documented, no code.** The arbitrage hand-off latch term is effectively unreachable, because D2 pops the latch once arbitrage owns the id. It is kept as defence-in-depth and adds nothing to the unlatched path (INV-4).
- **Plan §7 negative-band row, corrected.** The floor is 85 and the behaviour is legacy.

Fix-up drills (each site alone; PYTHONDONTWRITEBYTECODE=1; `__pycache__` cleared; the original restored; `git status` clean):
| Mutation | Result | RED test |
|---|---|---|
| Re-add `_proactive_offpeak_holds` to the EV D2 list | 1 fail | `test_a_high_1_ev_offpeak_ensure_on_does_not_discharge_latch` |
| Re-add `_proactive_offpeak_holds` to the plug D2 list | 1 fail | `test_a_high_1_plug_offpeak_ensure_on_does_not_discharge_latch` |
| EV threshold-change pop neutered | 1 fail | `test_d_l1_threshold_lowered_first_pause_fires` |
| Plug threshold-change pop neutered | 1 fail | `test_d_l1_plug_threshold_lowered_first_pause_fires` |
| EV producer stores 0 instead of the threshold (value detached) | 9 fail | `test_d_l1_unchanged_threshold_keeps_latch`, `test_a1_...`, `test_a3_soc_77_0_...` |

Run against the `b1d5b878d` `energy_pool.py`, the 5 new tests fail (both A-HIGH-1 tests and all three D-L1 tests).

## Review C fix-up
- **C-L1, fixed by removing the plug's `repause_band_pct` kwarg.** `energy.py` never passes a band to either tier, and no plug test relied on the kwarg. The plug still reads `_energy_const.DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` when it is called. The EV kwarg stays, because the EV config-extreme tests use it and those tests don't need the plug to match. The plug extremes are now driven by patching the same module attribute that production reads.
- **C-L2, fixed.** `test_a3_plug_boundary` is parametrized at threshold 50 (floor 47: 47.0 holds, 46.9 pauses). New plug tests cover the §7 extremes: band 0 at thresholds 80 and 50, band 100, band −5, and slider-min-50 fresh.

| Mutation | Result | RED tests |
|---|---|---|
| Plug floor clamp `max(0, …)` changed to `max(50, …)` | 2 fail | `test_a3_plug_boundary_77_0_holds_76_9_pauses[50-47.0-46.9]`, `test_plug_extreme_band_100_fresh_pauses_latched_never` |
| Plug band hard-coded to 3 (module attribute not read) | 5 fail | `test_plug_extreme_band_zero_legacy[80/50]`, `test_plug_extreme_negative_band_legacy`, `test_plug_extreme_band_100_...`, `test_a4_plug_module_attribute_band_zero` |

## Deferrals
- L1-L3 are live criteria and belong to the post-deploy validator.
- No README/version bump: the orchestrator owns the release.

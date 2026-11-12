# EV rung-1 redirect cap — Review C (test authority, per-site source mutation)

Branch feature/ev-rung1-redirect-cap @ 9d5cfbdb (code 03eb3b70). Each row: ONE site neutered in
`energy_battery.py`, suite = `test_ev_rung1_redirect_cap.py` + `test_ec_daylight_horizon_poor_night_floor.py`,
`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared per run, restored in try/finally, `git status` clean after.

| # | Site (mutation) | Result | First named failing tests |
|---|---|---|---|
| 1 | cap `min(ev, ...)` removed | RED (4) | cap_export_full_credit, case_07_ev_estimate_bounded, kill_switch_zero |
| 2 | cap `max(0.0, ...)` removed | RED (8) | cap_1108_replay_grid_fed_ev_no_entry, cap_ev_below_import, replay_1001 |
| 3 | import subtraction dropped (credit = full EV) | RED (15) | cap_1108_replay..., cap_two_evs_summed |
| 4 | freshness gate dropped | RED (1) | cap_net_power_stale_no_entry_with_fresh_control |
| 5 | freshness max_age -> 0 (gate dead) | RED (1) | same |
| 6 | freshness gate inverted | RED (45) | many |
| 7 | max_age<=0 carve-out removed (`_read_fresh_power_w`) | RED (1) | cap_kill_switch_zero_trusts_value |
| 8 | snapshot `_arb_last_ev_load_pct_per_h` uncapped | RED (2) | cap_snapshot_equals_entry_credit, cap_two_evs_summed |
| 9 | zero-credit short-circuit to rung_2 removed | RED (2) | test_rung1_post_sunrise_grid_fed_ev_no_entry, counterfactual_site_daylight_gate |
| 10 | `_arb_rung1_latched_at = now` not written | RED (10) | hold_flat_rate_escalates_exactly_at_flush_direct |
| 11 | hold `>=` -> `>` | RED (3) | hold_flat_rate_escalates_exactly_at_flush_direct/_prod |
| 12 | hold `>=` -> `<` | RED (6) | hold_held_tick_below_exit_band |
| 13 | window_flushed forced True (no hold) | RED (5) | hold_flat_rate_escalates..., hold_held_tick |
| 14 | hold never flushes (escalation never) | RED (9) | hold_latched_at_none_legacy |
| 15 | latched_at None blocks escalation | RED (5) | hold_latched_at_none_legacy |
| 16 | escalation drops exit_band compare | RED (2) | hold_genuine_redirect_no_flap_prod, daylight_carried_rung1_latch_still_held |
| 17 | hold placed on night release (gates it) | RED (1) | hold_does_not_gate_night_release |
| 18 | D3 stamp removed | RED (19) | redirectable_kw_value_on_entry_tick et al |
| 19 | D3 stamp = raw EV kW | RED (16) | cap_1108_replay... |
| 20 | D3 entry-reset removed | RED (2) | redirectable_kw_reset_on_peak_tick, _none_while_latched |
| 21 | D3 attribute not surfaced | RED (1) | redirectable_kw_value_on_entry_tick |
| 22 | hold: empty history -> flushed (`(not _hist) or ...`) | GREEN | equivalent mutant, see below |

## Row 22 — equivalent mutant (not a finding)
The `bool(_hist)` guard is unreachable-false at the hold line: `_record_attain_sample` runs at the top of the
classifier, and `test_rung1_hold_window_cleared_midlatch` shows an emptied window returns the cold-boot
rung_2 (<2 samples) BEFORE the latched branch reaches the hold (latch kept). So history is never empty there;
the guard is defensive only.

## Observations
- Hold-placement-only-on-escalation is covered both directions (rows 13/14 vs 17; counterfactual-exit and
  solar-collapse via the `does_not_gate_*` tests).
- No GREEN rows other than the proven-equivalent one. Production-path tests (`_Coord` async) exist for the hold
  and the 11-08 replay, not only direct classifier calls.
- Tree left clean (`git status --short` empty).

**Verdict: SHIP** (no must-fix).

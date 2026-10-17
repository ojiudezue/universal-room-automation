# EC Stage A (storm/blind) — Tier-3 Review C: test authority via per-site source mutation

Branch `feature/ec-stage-a` (base f2ec3cb38). Reviewer C, Sonnet 5.5. Method: one production-source edit per drill
(read original, write mutant, run, restore in `finally`; `__pycache__` cleared + `PYTHONDONTWRITEBYTECODE=1` before every
run), run set = the 4 Stage A files + `test_reserve_governor_ab`, `test_reserve_write_chokepoint_lint`,
`test_reserve_write_rows`, `test_battery_inclement_arbitrage_floor`, `test_part2_ec_hc_writeback`, `test_energy_battery`
(plus `test_runtime_smoke` for the number-platform row; its 3 failures/2 errors are pre-existing, name-diffed). `git status`
clean after every batch. The untracked `test_zz_reviewD_holdcurrent_repro.py` is Reviewer D's, untouched.
Builder's table was not consulted; 90 drills run independently.

## Drill table (site -> mutation -> first failing tests -> result)

| Site | Mutation | Named test(s) that fail | Result |
|---|---|---|---|
| `_reserve_action` fold | fold removed | fold_raises_only, fold_before_deadband, overlay_append_cannot_undercut_floor, deescalation_reserve_folded (9) | RED |
| fold-before-deadband | deadband uses pre-fold value | fold_before_deadband, stamps_folded_when_deadband_suppresses (4) | RED |
| stamp value | stamp pre-fold | deescalation_reserve_folded, fold_raises_only (5) | RED |
| stamp placement | stamp only when action emitted | stamps_folded_when_deadband_suppresses + golden (31) | RED |
| stamp removed | no stamp | 210 | RED |
| sole writer | second stamp in `_result` | is_sole_desired_stamper | RED |
| sole writer | `=77` stamp at determine_mode entry | 17 incl. blind ones | RED |
| sole writer | stamp after `_reserve_action` in blind | hold_writes_floor_once, ab_golden[blind] (7) | RED |
| writer lint | second `number.set_value` literal in determine_mode | test_no_unlisted_writers | RED |
| writer table | count 1->2 | lint_catches_second_writer..., no_unlisted_writers | RED |
| tick-floor reset | entry-reset removed | test_tick_floor_entry_reset | RED |
| registration (sighted) | dropped | 33 | RED |
| registration (blind) | dropped | 28 | RED |
| `_registered_floor` | full_hold excluded | 16 | RED |
| blind -> `_reserve_action` | direct dict, no fold/stamp | 14 | RED |
| blind hold rule | disabled | 16 | RED |
| hold never lowers | `_target=_floor` | test_blind_hold_never_lowers_held_value | RED |
| hold unreadable deadband | compare_to None | test_blind_hold_unreadable_reserve_writes_once | RED |
| hold base uses stamp | `_base=_wl` | test_blind_manual_raise_not_treated_as_lower | RED |
| **hold base falls back to write leg** | `_base=_desired` (drop `else _wl`) | none | **GREEN (finding C-1)** |
| release rule | disabled | release_at_hazard_end (3) | RED |
| release flag clear | not cleared | test_blind_release_at_hazard_end | RED |
| release pre_raise clear | not cleared | none | GREEN, equivalent (arming always overwrites; LOW, benign) |
| release arming | disabled | 5 | RED |
| arming capture | pre_raise None | 3 | RED |
| release fallback | 100 not reserve_soc | release_unknown_base_targets_reserve_soc | RED |
| de-esc full_hold exemption | dropped | blind_full_hold_exempts_deescalation (3) | RED |
| de-esc CFG gate | dropped | fully_blind_peak_cfg_already_off_is_idempotent | RED |
| de-esc CFG last-cmd | ignored | cfg_entity_unavailable_plus_ledger_true... | RED |
| de-esc turn_off | dropped | 13 | RED |
| de-esc target | 100 | 12 | RED |
| de-esc clear `<=` | `<` | at_or_below_pre_raise_clears_release | RED |
| Q6 constant | True | blind_respect_manual_lower_default_false | RED |
| Q6 override set / gate | removed | hold_manual_lower[True] | RED |
| Q6 URA-dispatched conjunct | dropped | ura_dispatched_lower_not_treated_as_manual | RED |
| Q6 comparison | inverted | hold_manual_lower[True], manual_raise_not_treated_as_lower | RED |
| episode flag reset (sighted) | dropped | episode_flags_reset_on_sighted_tick | RED |
| blind `_desired_stamped_at` | stamped | test_blind_never_stamps_desired_at | RED |
| reason prefixes (hold/release/de-esc) | renamed | 5 / 2 / 10 | RED |
| blind return actions | hold actions dropped | 13 | RED |
| write-leg None | treated as 0 | hold_unreadable..., release_unknown_base... | RED |
| top-rate edge (name) | `is_top_rate`->peak literal | deescalation_shoulder_midpeak (5) | RED |
| transition into top (name / ignored) | peak literal / False | deescalation_on_transition_into_top_rate | RED |
| `is_top_period` by name | `period=="peak"` | 11 | RED |
| single-rate guard | `<1` | rate_rank_ties_and_single_rate | RED |
| ties | list not set | rate_rank_ties_and_single_rate | RED |
| `is_bottom_rate` | `==1` | hour_sweep_pec_dst, ties_and_single_rate | RED |
| `tou_top_rate` attr | None / by name | get_status_carries_tou_top_rate, tou_top_rate_strategy_attr | RED |
| slider read | module default not `entry.options` | first_tick_after_restart, extremes_0_100 (5) | RED |
| slider pass-through / fusion init | default / ignore arg | same (5, 5) | RED |
| blind floor terms | drop slider / drop partial | extremes, inversion (7 / 3) | RED |
| **blind floor term reserve_soc** | drop `self._reserve_soc` from max | none | **GREEN (finding C-2)** |
| sighted full-hold floor | floor at reserve_soc | sighted_full_hold_floor_below_reserve_soc_unchanged | RED |
| suppress-key sets | drop from `_NO_LIVE_ATTR_KEYS` / `OPTIONS_RELOAD_SUPPRESS_KEYS` | 2 / 3 incl. key_in_* | RED |
| Number registration | removed from platform list | test_runtime_smoke::test_number_platform_registers_inclement_blind_floor | RED (only in runtime_smoke; none of the 4 Stage A files) |
| Number setter / seed / default | wrong value / ignore options / 60->100 | writes_options_only / seeds_from_options / seeds, junk-60 | RED |
| D-A4 row | tick_floor / tick_hold_depth not recorded / source None | reserve_row_carries_tick_floor (2-4) | RED |
| D29 off-peak drain clamp | deleted | offpeak_clamp_rekey_identical, registered_floor_reaches_offpeak_dp_stamp_and_hold, golden (26) | RED |
| D29 revert to `hold_depth=="partial_hold"` keying | revert | registered_floor_reaches_offpeak_dp_stamp_and_hold | RED |
| D30 off-peak hold clamp | deleted / reverted | none | GREEN (adjudicated redundant, below) |
| `_reserve_action` clamp 0-100 | removed | fold_raises_only | RED |
| unconfigured reserve role | emits | blind_de_escalation_emits_no_targetless_writes | RED |
| compare_to | ignored | compare_to_overrides_hardware | RED |
| **stand-down skip** | `_standdown_skip=False` | none (also none in `test_energy_behavioral_write_verify`) | **GREEN (finding C-3)** |
| **deadband threshold** | `>=2` -> `>2` | none | **GREEN (finding C-4)** |

## Findings

C-1 MEDIUM (untested load-bearing site, Bug Class #62-adjacent): `_base = _desired if _desired is not None else _wl`
(`energy_battery.py` blind hold). Dropping the write-leg fallback is GREEN. Legal repro the code handles and no test pins:
restart into blind (desired None), hardware reserve 90 (arbitrage-set), floor 60 -> correct code targets max(60,90)=90
(no write); mutant writes 60, lowering a held 90. Spec "never lowers a held value" is only tested with a stamped desire.
Need: test with `_last_reserve_level_desired=None`, write leg 90, floor 60 -> no action.

C-2 MEDIUM: `_full_hold_floor(None)` `max(reserve_soc, partial_floor, slider)` — the `reserve_soc` term is unpinned.
Test only has partial>slider (`inversion`) and slider extremes at default reserve_soc. Repro: reserve_soc=80, partial=50,
slider=60 -> must be 80; mutant gives 60 (below the operator's configured reserve) and the restart-into-blind first write
would be 60. Need: `test_blind_full_hold_floor_reserve_soc_dominates`.

C-3 MEDIUM: the HARD STAND-DOWN skip inside `_reserve_action` (moved from `_result` by this diff) is untested. Drill GREEN
across the cycle files and `test_energy_behavioral_write_verify`; no suite file drives `is_standdown_active_for_value`
through `_result`/`_reserve_action`. Blind hold/release now route through it, so the "don't keep re-dispatching a stuck
value" guard is the thing preventing a blind write every tick against a stuck non-compliant surface. Need: a stand-down
fixture on the reserve surface at target value -> no action, but the stamp still lands.

C-4 LOW: deadband boundary (`abs(diff) >= 2`) untested (diff == 2). Pre-existing behavior moved verbatim; golden has no
diff-exactly-2 case. Add one boundary case.

C-5 LOW (informational): `_blind_pre_raise = None` after release is redundant with arming (always overwritten); no action.

## D30 adjudication (off-peak hold clamp re-key)

Redundant, not mis-keyed. `hold_reserve`'s sole consumer is `_result(reserve_level=hold_reserve)`; `reserve_level` is
consumed ONLY by `_reserve_action` (verified: no other `reserve_level` use in `_result`, grep at 6488-6900), which
folds the same `_tick_reserve_floor` registered earlier the same tick, before clamp, stamp and deadband. No tick reorder
between the clamp and the fold, no other reader of `hold_reserve`, and the reason string does not print it. So no state
exists where the clamp changes an emitted value, a stamp, or a reason. D29 (drain target) IS load-bearing because the
value feeds the `soc > drain_target` branch decision, the reason text and the DP value stamp. Verdict: D30 is dead
defense-in-depth; keep or delete, but the plan's mutation item "revert the off-peak inline clamps" is only
satisfiable for the drain clamp. Control: deleting D30 AND the fold turns 30 tests RED (the fold carries it).

## Not drilled / limits
- `force_redispatch` and `_apply_evse_battery_hold` inherit the floored stamp without a code change; their coverage is
  via the fold/stamp drills (overlay test goes RED); no dedicated redispatch-composes-floor test (INFO).
- Hold-current-boot path (Reviewer D's repro file) is outside this lane.

## Verdict: FIX-REQUIRED
Load-bearing GREEN drills: C-1, C-2, C-3 (tests only; production code is correct in each case). Add the three tests
(+ C-4 boundary), re-run these four mutations RED, then SHIP. Everything else (≈85 drills) is RED on a specific test.

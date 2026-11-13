# Review C: lock-release-on-arriving (test authority, real per-site mutation)

Branch feature/lock-release-arriving @ 14fbfc21. Tier 3 framing C. Interpreter .venv-ha, PYTHONDONTWRITEBYTECODE=1, -p no:cacheprovider, __pycache__ cleared per mutation, `-m ""`.

Target set per mutation: test_lock_release_arriving, test_sc_garage_lockout{,_real_ha,_review_c}, test_lock_arrival_hold{,_real_ha}, test_lock_face_arrival_corroboration, test_sc_away_lock (541 tests, baseline green). Mutate+restore in one Python step (try/finally); `git status` clean after.

## Site x test x RED-on-neuter (62 sites)

| Site | Result | First failing test |
|---|---|---|
| M01 edge_decision tainted HOME->arriving_hold | RED | test_arriving_then_home_star_chain_holds_until_backstop |
| M02 edge_decision override bypass | RED | test_override_set_bypasses_taint |
| M03 edge arriving non-override hold | RED | test_body_only_arriving_does_not_release_sleep |
| M04 edge arriving override release | RED | test_override_set_arriving_releases_without_taint |
| M05 edge waking release sleep-like | RED | test_every_reason_none_site_clears_flags[after_release |
| M06 taint set on arriving edge: old==arriving | RED | test_boot_settle_suppressed_arriving_old_state_taints |
| M07 taint set reason!=NONE guard dropped(taint w/ NONE) | RED | test_reason_none_arriving_no_unlock |
| M08 taint set skip override exempt | GREEN | - |
| M09 taint set no save | RED | test_boot_rebuild_sleep_vacation_clears_restored_taint[sleep |
| M10 clear site never clears | RED | test_arriving_then_home_star_chain_holds_until_backstop |
| M11 clear leaves saw flag | RED | test_boot_recheck_sleep_vacation_rebuild_clears_taint[sleep |
| M12 engage no episode-boundary clear | RED | test_guest_clock_clears_taint |
| M13 store save taint key | RED | test_boot_recheck_arriving_taints_later_home_star_held |
| M14 store save saw key | RED | test_boot_guest_night_rebuild_keeps_taint |
| M15 store save garage_reason | RED | test_taint_persisted_across_restart_two_rigs |
| M16 store load taint | RED | test_boot_recheck_arriving_taints_later_home_star_held |
| M17 store load saw | RED | test_boot_guest_night_rebuild_keeps_taint |
| M18 store load restored reason | RED | test_taint_persisted_across_restart_two_rigs |
| M19 PERSISTED_REASONS drop vacation | RED | test_vacation_lock_survives_daytime_restart_after_away |
| M20 reason setter no persist | RED | test_vacation_lock_survives_daytime_restart_after_away |
| M21 boot rebuild restored reason wins | RED | test_taint_persisted_across_restart_two_rigs |
| M22 boot rebuild away/arriving taint | RED | test_boot_rebuild_away_locked_taints |
| M23 boot rebuild sleep no clear | RED | test_boot_rebuild_sleep_vacation_clears_restored_taint[sleep |
| M24 boot rebuild vacation no clear | RED | test_boot_rebuild_sleep_vacation_clears_restored_taint[vacation |
| M25 boot rebuild nothing-locked no clear | RED | test_boot_nothing_locked_clears_stale_taint |
| M26 boot rebuild killswitch-off no clear | RED | test_boot_kill_switch_off_clears_restored_taint |
| M27 recheck house==arriving taint | RED | test_boot_recheck_arriving_taints_later_home_star_held |
| M28 recheck ended arriving_hold excl | RED | test_manual_unlock_memory_survives_tainted_boot_recheck |
| M29 D3 saw_before captured | RED | test_tripwire_fires_on_house_state_unlock_when_gate_bypassed |
| M30 D3 waking trigger exempt | RED | test_tripwire_waking_and_override_exempt |
| M31 D3 boot_recheck waking exempt | RED | test_boot_recheck_waking_release_kept_no_tripwire |
| M32 D3 override exempt | RED | test_tripwire_waking_and_override_exempt |
| M33 D3 written required | RED | test_tripwire_silent_when_nothing_written |
| M34 D3 boot_recheck trigger incl | RED | test_tripwire_covers_boot_recheck_channel_two_rigs[arriving |
| M35 D3 counter | RED | test_tripwire_fires_on_house_state_unlock_when_gate_bypassed |
| M36 D4 engage_seq bump | RED | test_still_locked_engage_seq_guard_without_last_changed |
| M37 D4 fire seq check | RED | test_still_locked_engage_seq_guard_without_last_changed |
| M38 D4 observed relock check | RED | test_still_locked_skips_human_relock_in_window |
| M39 D4 relock record | RED | test_still_locked_skips_human_relock_in_window |
| M40 D4 failure-NM dedupe | RED | test_still_locked_dedups_release_failed_nm |
| M41 D4 one-page-per-seq | RED | test_still_locked_one_page_per_lock_two_residents |
| M42 D4 unavailable recheck rearm | RED | test_still_locked_unavailable_at_timer_rechecked_then_pages_locked |
| M43 D4 unreadable skip first pass | RED | test_still_locked_unavailable_at_timer_rechecked_then_pages_locked |
| M44 D4 earliest-check keep | RED | test_still_locked_flaps_after_counted_arrival_do_not_postpone |
| M45 D4 only-locked pages (unlocked skip) | RED | test_still_locked_silent_after_unlock |
| M46 D4 window<=0 off | RED | test_still_locked_window_zero_disables |
| M47 D4b taint-or-away condition | RED | test_uncounted_return_pages_late_reconnect_tainted_home |
| M48 D4b old_val unreal | GREEN | - |
| M49 D4b reason != NONE | RED | test_uncounted_return_silent_when_reason_none |
| M50 D4b house away/arriving only | RED | test_still_locked_one_page_per_lock_two_residents |
| M51 D-L2 boot_house gate | RED | test_boot_gap_silent_when_restored_house_not_away |
| M52 D-L2 failure_nm gate | RED | test_boot_gap_silent_when_release_failed_already_paged |
| M53 D-L2 release_inflight gate | RED | test_boot_gap_silent_while_unlock_in_flight |
| M54 D-L2 home resident required | GREEN | - |
| M55 D-L2 reason NONE gate | RED | test_boot_gap_silent_when_reason_none_at_recheck |
| M56 D-L2 dedupe per seq | RED | test_boot_gap_dedups_with_still_locked_page |
| M57 D-L2 flag const | RED | test_boot_gap_return_pages_never_releases |
| M58 D3 flag const | RED | test_tripwire_fires_on_house_state_unlock_when_gate_bypassed |
| M59 D4 window const 90->0 | RED | test_still_locked_after_arrival_pages |
| M60 D4b flag const | RED | test_still_locked_one_page_per_lock_two_residents |
| M61 relock-from set | RED | test_still_locked_skips_relock_via_locking |
| M62 boot_provisional reason_from_store | RED | test_tripwire_covers_boot_recheck_channel_two_rigs[arriving |

59 RED / 3 GREEN.

## GREEN rows (findings)

**C-1 MEDIUM (M54, hollow assertion), `security_lock_regime.py:1176-1177` (`if not home: return []` in `_boot_gap_return_page`).** Neutered: the loop reaches `home[0]` -> IndexError, caught by the caller's try/except (`:1146-1148`), `boot_gap_paged` stays `[]`, no NM. `test_boot_gap_silent_when_no_resident_home` / `_only_excluded_person_home` assert only `nm.of(BOOT_GAP) == []`, so they stay green. Verified with a throwaway probe (deleted): under the mutant `still_locked_pages == 1` and `_still_locked_paged[ent] == engage_seq` are poisoned BEFORE the exception (`:1191-1192`), which would silently suppress a later genuine D4 page for that engage episode (dedupe `:1554`). Fix: assert `still_locked_pages == 0`, `_still_locked_paged == {}` and a WARNING-free log in those two tests (or reorder the stamp after the spawn).

**C-2 LOW (M08, `:1000-1003`: `and not override` on the taint-set condition).** Dropping it is invisible to the suite. By reading: an override ARRIVING / HOME_* edge releases anyway and the release ends the episode, so the extra taint is cleared; the residual observable is override GUEST->HOME_NIGHT (`guest_yield_hold`, no release) with `old == arriving`, which would leave a spurious persisted taint that holds a later HOME_* edge. Narrow reachability, but untested. Add one test: override edge with old==arriving, reason guest_night, in sleep window; assert taint stays False. Not executed here (reasoned, not drilled).

**C-3 INFO (M48, equivalent mutant), `:1490` `old_val in _UNREAL_STATES` inside `_uncounted_return_pages`.** Only caller (`:1455`) is reached solely when `_arrival_counts` is False, which `:1757-1759` returns only for old_val in _UNREAL_STATES. Redundant defence-in-depth today, not a test hole. Becomes live if the caller ever changes; a unit test calling `_uncounted_return_pages("p","not_home")` directly would pin it.

## Other runs
- Isolated per-file: test_lock_release_arriving 110 pass; test_sc_garage_lockout 204; _real_ha 3; _review_c 39. All green.
- `URA_D7_HYGIENE=1` test_d7_donor_hygiene.py + test_collect_order_matrix_run_mode.py: 58 passed, 1 skipped, 28 deselected (215 s). Green.
- Drill tests (`source_mutation` marker) were not part of these files' target set; no `-m source_mutation` run needed.
- Tree clean (`git status --short`: only untracked `.claude/tmp/`, my drill script/output). No production source left mutated.

## Coverage notes
Sites covered RED: taint set (old==arriving, reason!=NONE, save), all clear sites (never-clear, saw-flag, engage boundary, boot SLEEP/VACATION/nothing-locked/kill-switch-off), store save+load of taint/saw/garage_reason (3 keys each way), _PERSISTED_REASONS, reason setter persist, restored-reason precedence, boot away/arriving taint, recheck arriving taint, `ended` arriving_hold exclusion, waking exemption (edge and boot_recheck), D3 (captured saw flag, written, override, boot_recheck channel, counter, flag), D4 (seq bump/check, observed re-lock record+check incl. `_RELOCK_FROM`, failure-NM dedupe, one page per seq, unavailable recheck + first-pass skip, earliest-check keep, unlocked skip, window 0, constant), D4b (taint-or-away both halves, reason!=NONE, flag), D-L2 (boot_house, failure_nm, inflight, reason NONE, dedupe, flag), D-H1 (restore, vacation persist).

## Verdict: FIX-REQUIRED (minor)
Must-fix: C-1 (add the two assertions; the unguarded stamp-before-spawn order is a latent suppression if the `home` guard is ever refactored). C-2 should be fixed in-cycle (LOW, ~10 LoC test). C-3 optional. No production-code defect found; fix-ups are test-only, after which SHIP.

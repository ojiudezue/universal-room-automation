# Review A (local correctness) — LOCK-RELEASE-ON-ARRIVING

Branch `feature/lock-release-arriving` HEAD 30b80831; merge-base with develop `e4069fca` (three-dot diff).
Plan `PLANNING_lock_release_on_arriving.md` rev 3. Framing A only: taint set/clear, `_edge_decision`, store,
D3/D4 conditions, timers, None handling, config extremes.

Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`docs/architecture/SENSOR_FLEET_CLASSES.md`. No §10 ledger claim is re-asserted. No doc/code contradiction found
in the areas reviewed (row 83 / §7 / #35 match the code).

`test_lock_release_arriving.py`: 80 passed (single file).

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A-1 | MEDIUM | `security_lock_regime.py` `_on_still_locked`, the `last_changed > anchor_wall` skip (~:1439-1441) | INV-PAGE leak. The R2-7 "re-locked by someone else" skip also fires when a lockout was `unavailable` at the S1 call and comes back `locked`. `_release` skips unavailable entities (~:1865-1871), so nothing is unlocked; the `unavailable -> locked` return moves `last_changed` past the anchor, and the page is suppressed. Result: resident arrives, the lock stays locked, no page. Repro (scratch test on the plan's rig, deleted after): sleep engage; LOCK_A set `unavailable`; `away`; Ezinne `not_home -> home` (S1 unlocks LOCK_B only, WARN "release skipped"); +20 s LOCK_A set `locked`; +100 s: 0 `lockout_locked_after_arrival` pages, LOCK_A never unlocked. Legal: Wi-Fi/Konnected/ratgdo openers drop off the network. Fix: capture each lockout's value at the anchor and skip on `last_changed` only when that value was `unlocked` (a real re-lock), or require the transition's prior state to be `unlocked`. Add a test for the unavailable case. | #53-shaped (a guard written for one shape catches a second) |
| A-2 | LOW | `_boot_recheck_regime` waking path (~:1029-1047) + `_check_uncorroborated` (~:1888) | D3 false page. A restart in the morning where boot settle swallows the SLEEP and WAKING edges leaves `reason = boot_unknown` with a restored taint; the recheck sees house `waking`, `_edge_decision` releases (correct), trigger `boot_recheck`, `saw_before` True, so D3 pages. The exemption covers only `house_state:waking`. Suggest exempting `boot_recheck` when the house reads `waking`. Narrow (restart inside the wake window after a tainted episode). | trip-wire precision |
| A-3 | LOW | `_boot_rebuild` early return when the kill switch is off (~:650) | A restored taint is not cleared when setup runs with the switch off. Inert while reason is NONE (every consumer gates on `reason != NONE`), and the next engage clears it. It matters only if a later boot runs with the switch on, a lockout hand-locked and the house HOME_*: BOOT_UNKNOWN keeps the stale taint and the recheck holds (`arriving_hold`) instead of releasing; the `allow_immediate` backstop releases at once by day, at the morning deadline at night. Suggest calling `_end_episode_arrival_flags()` before that return too. | stale persisted state |
| A-4 | LOW (note) | `_async_engage` (~:2246) | `engage_seq` is bumped before the `lock.lock` call, so a failed call still silences an older still-locked check. Harmless (the lock did not change), noted only. | — |

## Verified (holds because)

- `_edge_decision` truth table (reason × taint × override × new):
  arriving: override → release; reason≠NONE → arriving_hold; NONE → none. HOME_*: guest-yield branch first (unchanged);
  reason≠NONE ∧ taint ∧ ¬override → arriving_hold; reason≠NONE otherwise → release; NONE → none. waking/sleep/
  vacation/guest unchanged. Matches plan D1 item 4.
- Taint set in `on_house_state_changed` precedes `if not new: return` and the decision; gated on reason≠NONE and
  ¬override; covers `old == "arriving"` (H2). Saves only on change.
- Clear helper at every `self.reason = REASON_NONE` write (:815, :1198, :1226, :2031, :2039), `_set_engage_reason`
  (top, before the write), boot SLEEP/VACATION rebuilds (:663/:666, :691/:694), nothing-locked boot return. The two
  allowlisted no-clear writes (:671 BOOT_UNKNOWN, :1022 GUEST_NIGHT) keep the taint. Guest clock routed through
  `_set_engage_reason`; byte-identical otherwise (reason write + `_schedule_backstop` for a sleep-like reason).
- Boot recheck: `ended` excludes `arriving_hold`; house `arriving` with reason≠NONE taints before deciding and never
  releases.
- Store: two keys in `_store_payload`; load uses `is True` (missing / non-bool → False); `_load_away_store` runs before
  `_boot_rebuild` (:565 vs :626); non-dict data returns early (flags stay False).
- D3: `saw_before` captured at the top of `_release`, before `_after_release` clears; `written` empty never pages;
  `_release`'s kill-switch / SC-dead early returns skip D3 (no write happened).
- D4a scheduled only after a counted S1; D4b only on `unknown/unavailable -> home` rejected by `_arrival_counts`,
  reason≠NONE, (taint ∨ house away/arriving), constants on. Window 0 disables both (`_schedule_still_locked` and
  `_uncounted_return_pages`). Timer is a `@callback` partial; previous per-person handle unsubscribed; teardown clears.
  `anchor_wall` is `dt_util.now()` (aware) vs aware `State.last_changed`: comparable.
- `_failure_nm_at` written for garage policy only; `engage_seq` bumped only in the garage `_async_engage`, not the
  away-lock engage.
- Observation mode gates only engage; release still unlocks, so D4 does not page every arrival in observation mode.

## Statistics

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 1 | 0 | — |
| LOW | 3 | 0 | — |

## Verdict

**FIX-REQUIRED** — must fix A-1 (MEDIUM, INV-PAGE leak, with a test). A-2 and A-3 are cheap in-cycle LOWs. D1's
release gate itself (INV-ARR) holds locally on every site reviewed.

## Fix-up round (reviews A, B, D), 2026-11-13, commit e6a86c06

| Finding | Sev | Bug class | Disposition | Fix | Test (RED on neuter) |
|---|---|---|---|---|---|
| A-1 / B-H1 / D-M1 | HIGH (B) / MED | #63 coincidental equality (availability return read as re-lock) | FIXED | `_on_lockout_event` stamps `_lockout_relocked_at` on `unlocked/locking/open/opening -> locked`; `_on_still_locked` skips only on a stamp after the anchor; an unavailable/unknown lockout is re-checked once (same window) and paged "unreadable" unless it reads unlocked | `test_still_locked_pages_lock_unavailable_at_arrival_back_locked` (A repro), `test_still_locked_tainted_home_night_lock_back_after_30s` (B repro), `test_still_locked_unavailable_at_timer_rechecked_then_pages_locked`, `test_still_locked_unavailable_through_recheck_pages_unreadable`, `test_still_locked_readback_unavailable_then_locked_pages` (D read-back shape), `test_still_locked_skips_human_relock_in_window` + `test_still_locked_skips_relock_via_locking` (real re-lock still skipped) |
| B-L1 | LOW | suppression without discharge | FIXED | one pending check per person; a check from the same `engage_seq` is kept (earliest anchor and its kind); an older-seq check is replaced | `test_still_locked_flaps_after_counted_arrival_do_not_postpone` (4 flaps), `test_uncounted_flaps_keep_earliest_check`, `test_still_locked_check_from_older_engage_is_replaced` |
| A-2 / D-L1 | LOW | trip-wire precision | FIXED | D3 exempts `boot_recheck` with the house reading `waking`; release kept; INV-ARR exception amended (plan §2) | `test_boot_recheck_waking_release_kept_no_tripwire` |
| A-3 | LOW | stale persisted state | FIXED | `_boot_rebuild` calls `_end_episode_arrival_flags()` before the kill-switch-off return | `test_boot_kill_switch_off_clears_restored_taint` |
| D-L2 | LOW | restart state loss | FIXED (page, not release) | `_boot_gap_return_page` at the boot recheck: restored house away/arriving, decision `arriving_hold`/`no_change`, reason not none, a resident (live exclusions) reads home, lockout locked, no unlock in flight, no failure/still-locked page already sent -> NM HIGH `lockout_locked_boot_gap_return`; knob `LOCK_RELEASE_BOOT_GAP_RETURN_PAGE_ENABLED` (rung 1, True) | `test_boot_gap_return_pages_never_releases` + 11 conjunct tests (`test_boot_gap_*`) |
| D-H1 | HIGH (pre-existing) | restart state loss | FIXED | `reason` is a property persisting every change (Store `garage_reason`); `_boot_rebuild` rebuilds the stored reason when the house is not sleep/vacation; the rebuilt reason is provisional at the boot recheck like `boot_unknown` (`_boot_provisional`) until an engage | `test_vacation_lock_survives_daytime_restart_after_away`, `test_reason_none_persisted_after_release`, `test_restored_sleep_untainted_home_releases_at_recheck`, `test_restored_vacation_converts_to_sleep_at_recheck`, `test_restored_sleep_home_night_guest_window_held_as_guest_night`, `test_restored_reason_manual_unlock_remembered_rebuilds_episode`, `test_restored_reason_confirmed_by_boot_window_engage_not_provisional` |
| D-L3 | LOW | episode-boundary laundering | CARDED `LOCK-VACATION-PHANTOM-SLEEP-DAILY-UNLOCK-1`; plan §9.3; README notes must state it | - | - |
| D-L4 | LOW (pre-existing) | restart state loss | CARDED `LOCK-BOOT-LOCKOUT-UNAVAILABLE-AT-SETUP-1`; plan §9.3 | - | - |
| A-4 | note | - | no change (harmless) | - | - |
| B-L2 | LOW | test coverage | NOT DONE (not in the fix-up brief): real-HA rig still does not fire `_on_still_locked` on a real loop | - | - |
| B-I3 | INFO | - | NOT DONE here: README note that "override" includes `ura.set_house_state` (README not yet written) | - | - |

Test changes to existing tests: `test_taint_persisted_across_restart_two_rigs` now expects the persisted `sleep` (was `boot_unknown`, D-H1). `test_reason_assignments_structurally_guarded` (AST source read, Bug Class #62) removed: the new store-rebuild write broke it, and every `self.reason` write is pinned by a behavioural test (parametrised clear-site test, boot rebuild/recheck tests, guest-night keep test, D-H1 tests).

Mutation drills (one site neutered at a time, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared, restored, `git status` clean): 31 sites, 31 RED. Suites: `test_lock_release_arriving.py` 110 passed; lock-regime siblings (12 files) 655 passed, both orders checked.

| Severity | Found (A+B+D) | Fixed | Carded / deferred |
|---|---|---|---|
| HIGH | 2 (B-H1, D-H1) | 2 | 0 |
| MEDIUM | 2 (A-1, D-M1; same bug as B-H1) | 2 | 0 |
| LOW | 8 (A-2, A-3, B-L1, B-L2, D-L1, D-L2, D-L3, D-L4) | 5 (A-2, A-3, B-L1, D-L1, D-L2) | 3 (D-L3, D-L4 carded; B-L2 deferred) |

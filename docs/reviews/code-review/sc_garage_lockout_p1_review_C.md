# GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 Phase 1 — Review C (test authority via real per-site source mutation)

Branch `feature/sc-garage-lockout-phase1` @ `a69e924c`. Diff base `3153a918` (verified: `git merge-base HEAD develop` = 3153a918; three-dot).
Worktree `.claude/worktrees/agent-a12c8c90be2abe137`. Reviewer: C (Sonnet 5.5). The builder's `.lockout_drills.py` was not used or trusted.

## Method
- One production-source edit per drill (exact-once string replace, count asserted), written and restored in a `try/finally`, `__pycache__` cleared and `PYTHONDONTWRITEBYTECODE=1` before every run.
- Suite per drill, in this order (order matters, see Finding 17): `test_house_state_rung1`, `test_low_cleanup`, `test_part2_ec_hc_writeback`, `test_sc_garage_lockout`, `test_sc_garage_lockout_optimizer`, `test_sc_garage_lockout_real_ha`. Baseline 260 passed (`-m ""`).
- 316 single-site mutations plus 12 multi-site mutations. Of the 316: about 195 RED, about 119 GREEN, 1 bad match, 1 drill that was an identity edit (discarded). Every GREEN was triaged by hand into equivalent/redundant or a gap.
- For each suspected gap I wrote a probe test against UNMUTATED code (it passes), then re-ran it against the mutant (it goes RED). That proves the behaviour is observable, so the suite really lacks the test and the mutant is not equivalent. 22 of 24 probe sites went RED. The 2 non-RED are explained under Finding 9. Probe file and drill scripts are kept outside the repo at `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/reviewC/` (`test_zz_reviewC_probes.py`, `reviewC_d1..d5.py`, `reviewC_multi.py`). These probes are the ready-made tests to add.

## Site table (all `security_lock_regime.py` unless noted)

| Site | Mutation | Result |
|---|---|---|
| @callback x10 (`_on_boot_recheck`, `_on_guest_clock`, `_on_person_added`, `_on_person_removed`, `_on_person_event`, `_on_distance_event`, `_on_lockout_event`, `_on_readback`, `_on_reengage_timer`, `_on_backstop`) | strip decorator, each one | all 10 RED (`assert_loop_callback` in the harness, e.g. `test_sleep_engages_both`, `test_reengage_after_settled_arrival`) |
| custom `callback` decorator marker | drop `_ha_callback` / drop `setattr` / both | each alone GREEN (provably redundant: either one sets the same HA marker); both together RED |
| pre-lock: kill switch | `engage_predicate` kill conjunct off | RED `test_engage_intent_dropped_if_kill_switch_off_after_queue` |
| pre-lock: release_gen | gen conjunct off | RED `test_engage_intent_dropped_if_release_after_queue` |
| pre-lock: release in flight | inflight conjunct off | RED `test_engage_dropped_when_release_inflight` |
| pre-lock: house=sleep | off | RED `test_engage_intent_dropped_if_house_left_sleep_before_batch` |
| pre-lock: house=vacation | off | GREEN, probe P9a RED (F5) |
| pre-lock: guest house leg | off | RED `test_guest_engage_dropped_if_house_left_guest_before_write` |
| pre-lock: guest toggle leg / guest sleep-window leg | off, each | GREEN, probes P9b/P9c RED (F5) |
| pre-lock: SC alive (enabled/_shutting_down/_torn_down) | conjunct off / each sub-leg off | GREEN (F5); `enabled` sub-leg is only caught through `_release` (`test_arriving_signal_releases_when_sc_handler_disabled_flag`) |
| pre-lock: re-engage row at write time | off | GREEN, probe P9f RED (F5) |
| pre-lock: lockout state must be `unlocked` | off | GREEN, probe P9e RED (F5) |
| pre-lock: observation | `observation_mode`->False | RED `test_observation_mode_records_would_engage` |
| predicate is called at all | `why=None` | RED (4 tests) |
| in-flight latch ordering (B-M2) | restore pre-fix shape (add before `create_task`, no discard in except) | RED `test_failed_spawn_never_poisons_release_latch` |
| latch never added / `_release` skip-inflight removed | | RED `test_multi_trigger_arrival_single_unlock`, `test_release_inflight_latch_clears_after_readback` |
| `_release` ignores `_spawn_unlock` False | | GREEN (F13, LOW) |
| latch not cleared on read-back exhaustion | drop `_release_inflight.discard` in `_on_readback` | GREEN, probe P7 RED (F4) |
| teardown awaits pending unlocks (B-M1) | remove `asyncio.wait` / `pending=[]` / untrack `_unlock_tasks` | RED `test_reload_mid_unlock_still_releases` (x3) |
| teardown wait is bounded | `timeout=None` | GREEN (F7) |
| teardown cancels leftover tasks | cancel loop off | GREEN (F7) |
| teardown unsubs (persons, distance, backstop, reengage, guest clock, read-backs) | each off | RED `test_teardown_cancels_regime_timers` (5 of 6); `_boot_recheck_unsub` GREEN (F13) |
| teardown `_torn_down=True` | off | RED `test_sc_teardown_release_timeout_does_not_block_unload` |
| after-unlock-during-teardown early return | off | GREEN (LOW, `_on_readback` re-checks `_torn_down`) |
| switch-off release via live CM entry (security.py call) | remove `await async_release_if_disabled()` | RED `test_sc_switch_off_releases_before_reload` + `test_sc_teardown_reads_live_cm_entry_not_setup_snapshot` |
| `coordinator_should_run` gate / inverted | | RED (`test_sc_teardown_restart_does_not_release` etc.) |
| release_if_disabled kill-switch check | off | RED `test_sc_teardown_no_release_when_kill_switch_off` |
| release_if_disabled `release_gen += 1` | off | GREEN (F6, pair with SC-alive conjunct) |
| release_if_disabled timeout / NM on failure | | RED `test_sc_teardown_release_timeout_does_not_block_unload` |
| release_if_disabled entry None / skip-unlocked / reason reset / cfg precedence | | GREEN (F14) |
| security.py teardown call of `async_teardown` | removed | RED |
| boot window (`_in_boot_window`) false / arrival window false | | RED (`test_restart_*`) |
| `_setup_ts is None` fail-safe branches | flip | GREEN (unreachable after setup sets ts first; provably dead, LOW) |
| `_setup_ts` assignment removed | | RED |
| boot rebuild: never engages (`boot_edge_rebuild` branch off) | | RED |
| boot rebuild: `locked` filter / reason mapping sleep+vacation / backstop schedule / allow_immediate / called at setup / recheck scheduled | | RED |
| boot rebuild kill-switch gate | off | GREEN (F14, LOW) |
| boot recheck: sleep upgrade, vacation backstop cancel, torn guard | | GREEN (F10) |
| boot recheck: missing-resident list | | RED |
| restored-state arrival rule: `old is None` stamp / restored flag / return | | RED (`test_restored_state_counts_after_boot_window`, `test_restart_restore_then_unknown_then_home_releases`) |
| M2 `_really_away` gate on SIGNAL_PERSON_ARRIVING | gate removed / ts=0 | RED `test_interior_camera_face_for_resident_home_does_not_release`, `test_arriving_signal_short_abse...` |
| M2 resident filter | removed | RED |
| M2 `>=` 15 min boundary | `>` | GREEN (LOW boundary) |
| M2 flipped / minutes-as-seconds / always-true / home-blip branch | | RED |
| M2 release passes `person=` (re-engage scheduling) | `person` dropped | GREEN, probe P10 RED (F9) |
| M2 feed above `enabled` return (security.py) | gated by `_enabled` | GREEN, provably equivalent (`_release` already needs `_sc_alive`, which is `enabled`); feed above observation return | RED |
| proximity: person mapping across live person.* | drop live leg / drop `_person_unsubs` leg | each GREEN (redundant pair: every live person is subscribed at setup/add); drop BOTH (residents only) RED `test_excluded...` |
| proximity: exclusion applied after mapping | removed | RED |
| proximity: unmapped sensor still releases | `person is None` also blocks | GREEN, probe P11 RED (F9) |
| proximity: `endswith(_obj_distance)` pattern | `obj in sensor_id` / no delimiter / unsorted | GREEN, probe P14 RED (F9) |
| proximity: edge-trigger `prev>radius and cur<=radius` | `cur<radius`; `prev>=radius`; any-inside; radius<=0 guard; torn guard | all GREEN; any-inside probe P2 RED (F2) |
| proximity: crossing direction flipped / tracker unregistered / person arg / unit ignored | | RED |
| DistanceConverter conversion (`convert` skipped, wrong target) | | RED `test_proximity_unit_km_converted`, `test_proximity_survives_unit_conversion_module_swap` |
| DistanceConverter error path (`HomeAssistantError` / ValueError / non-numeric) | | RED (3 tests) |
| backstop DST-safe arithmetic | `today_deadline + 86400` | RED (DST-day test) |
| backstop `_local_wall` tz resolution | system-tz construction, run under TZ=UTC and TZ=Pacific/Honolulu | RED (both) |
| backstop `end` hour, minute unit, today-vs-tomorrow, allow_immediate branches, min-ignored | | RED |
| backstop `<=` boundary / negative clamp | | GREEN (LOW) |
| backstop fire: release / torn guard / reason gate / vacation cancel | fire off | RED; reason gate alone, vacation-cancel alone, torn alone: GREEN, pair (gate + vacation cancel) GREEN, probe P16 RED (F8) |
| backstop release resets reason (after_release `backstop` branch) | | GREEN (F14) |
| guest-in-sleep: house-state engage requires toggle / window / branch exists | toggle off; window off; branch off; always | toggle GREEN, window GREEN, branch RED, always RED (`test_guest_night_does_not_engage_when_toggle_off` covers one of two paths only) |
| guest clock handler: kill, toggle, boot, reason set, backstop schedule, daily re-arm, torn guard, `max(60,...)` | each off | all GREEN; probes P3 (reason+backstop) and P4 (re-arm) RED (F3). Only the `house == guest` leg is RED. |
| Away never engages | `away` -> vacation | RED `test_away_never_engages`; `away` -> sleep reason GREEN, probe P13 RED (F11) |
| sleep window wrap/equal/non-wrapping end | | wrap RED; start==end GREEN; non-wrapping `<=end` GREEN, probe P15 RED (LOW-MED) |
| optimizer layer 1 (`_check_safety_denylist` cover branch) | branch off | RED |
| optimizer layer 1 fail-closed (`except -> owned=True`) | -> False | RED |
| optimizer layer 1 configured list arg | `[]` | RED |
| optimizer layer 1 `applied_outcome` stamp / activity log reason | | applied_outcome GREEN (LOW); log reason RED |
| optimizer layer 2 (SC `_veto` cover branch) | off | RED |
| optimizer layer 2 fail-closed | -> False | GREEN (F12) |
| optimizer layer 2 configured list arg / reason string / return | | RED |
| `cover_ownership` configured-first leg / fall-through | | RED; str-input branch GREEN (LOW) |
| options-flow overlap validator | call removed / args blanked / errors not shown / wrong key / still saves | RED (5 of 5) |
| `lockout_overlap` `&` -> `|` ; str handling ; sorted | | RED; RED(`str`); `sorted` GREEN (LOW) |
| hazard release placement above observation return | moved below observation / below `enabled` | RED (both) |
| hazard feed call removed | | RED |
| hazard type filter (smoke/fire/CO) | removed | GREEN, probe P5 RED (F9) |
| hazard severity filter / config gate / dict branch | | RED |
| hazard: `on_hazard` cancel-reengage / reason reset / torn | | GREEN (F14, LOW; re-engage also cancelled by the gen bump) |
| kill-switch OFF edge: security switch call | removed | RED `test_kill_switch_entity_off_edge_calls_release` |
| kill-switch OFF edge: option actually persisted | `options` not written | RED |
| kill-switch OFF edge: `old and not value` | `old` dropped | GREEN (LOW) |
| kill-switch OFF edge: `on_kill_switch_changed(True)` is inert | `enabled` guard dropped | GREEN, probe P12 RED (F9) |
| kill-switch OFF edge: `force=True` | dropped | RED |
| `_release` kill-switch gate (`not force and not kill`) | removed | GREEN, probe P1 RED (F1) |
| `_release` `_sc_alive` gate with force | | GREEN (LOW) |
| `_release` gen bump / `releasing_set` stamp | | gen bump RED; stamp RED |
| `_release` `val in _UNREAL_STATES` skip | | GREEN (equivalent apart from a log line) |
| home-state release needs `reason != NONE` | gate dropped | GREEN, probe P6 RED (F5b) |
| per-lock NM dedup location (`garage:{ent}`) | `garage` | RED `test_...notes location` (2 distinct keys) |
| NM hazard_type / severity / timeout path | | hazard_type GREEN, timeout GREEN (LOW); severity RED |
| Store shape check (`isinstance(raw,list) and all(str)`) | each leg | GREEN (F15, hollow test); shape check plus the `startswith` filter together RED |
| Store: dict check / person filter / save / union / exclusion | | person filter GREEN; save RED; union RED; exclusion RED |
| reload-suppress keys (`OPTIONS_RELOAD_SUPPRESS_KEYS`, `_NO_LIVE_ATTR_KEYS`) | drop 6 keys | RED (3 tests each) |
| approach zone: `_is_approach_zone` release branch | branch off; `new != old`; friendly-name leg; lower-case leg | all GREEN (F2b); `zone.` prefix check RED (as a side effect) |
| re-engage: row checks (doors, max_wait, sleep window) / retry paths / abandon record / `_after_release` vacation / `releasing_set` removed flag | | RED |
| re-engage: row house checks, stale timer gen guard, `after_release` sleep-window / GUEST_NIGHT reason, `releasing_set.clear()` after engage, proximity as arrival | | GREEN (F10, LOW-MED) |
| re-engage delay 0 means "never" | `delay<=0` guard dropped | GREEN (F16, masked by the read-back latch) |
| SC wire-ins: house-state feed removed / setup call removed | | RED |
| SC wire-ins: Store handed to regime, exception isolation of 4 feeds, setup-failure isolation | | all GREEN (F12) |
| sensor `snapshot()` merged into attributes | merge removed | GREEN (F12) |

## Findings (numbered; severity; mechanism; probe)

### HIGH
**F1 — Kill switch OFF does not make `_release` inert; no test (HIGH, Bug Class #62/#53).** `security_lock_regime.py:875` `if not force and not self.kill_switch_on(): return` removed -> suite GREEN. With the switch OFF, an arrival/proximity/house-state release still unlocks a lockout that is locked. Probe P1: options `security_garage_lockout_enabled=False`, lockouts `locked`, `EZ -> home` => expects no unlock; passes on source, RED on mutant. INV-5 (kill-switch inertness) has no release-side test, only the OFF-edge and the engage-side predicate.

**F2 — Proximity edge-trigger and the approach-zone release have no tests (HIGH).** (a) `:859` `if prev > radius and cur <= radius` -> `if cur <= radius` GREEN. Every in-radius distance update would re-unlock. Probe P2 (second in-radius reading must not release again) RED on mutant. `cur < radius`, `prev >= radius`, `radius <= 0` guard, and the torn guard are also GREEN; the "0 = proximity off" knob is untested. (b) `:774-776` the whole approach-zone release (`_is_approach_zone` branch, `new_val != old_val`, friendly-name leg, case-insensitive leg) can be removed with the suite GREEN: the P4 input has zero behavioural coverage.

**F3 — Guest-clock handler (Q-G1, the newest behaviour) is almost untested (HIGH).** Only the `house == "guest"` conjunct is RED. Kill-switch, toggle, boot-window, `self.reason = REASON_GUEST_NIGHT`, `_schedule_backstop`, and the daily `_call_later` re-arm are each GREEN. Probe P3 (engage by clock at 22:00, then reason must be `guest_night` and the backstop must unlock) goes RED on both "reason not set" and "backstop not scheduled": a clock-engaged guest-night lock would never release by backstop (reason stays NONE, `_on_backstop` and the `waking`/home paths gate on reason) and would sit locked until an arrival. Probe P4 (re-arm next day) RED when the re-arm is removed: the clock would work for one night only.

**F4 — Release latch is not cleared when read-back retries are exhausted; no test (HIGH, wedge).** `:994` `self._release_inflight.discard(ent)` before the retry branch can be dropped with the suite GREEN. Probe P7 (unlock that never lands; after the retries and NM, `_release_inflight` must be empty) RED: after one failed release cycle, `_release` skips that lock forever (`:894`) and engage drops with `release_inflight`.

### MEDIUM
**F5 — Write-time predicate conjuncts are individually untested (MEDIUM, #53).** GREEN, each probe-proved: house=vacation (P9a), guest toggle (P9b), guest sleep-window (P9c), SC alive (P9d; `enabled`/`_shutting_down` sub-legs), lockout must read `unlocked` (P9e), re-engage row at write time (P9f; needs open door, the earlier "house" probe was non-discriminating). Rev 5 H-1 makes this predicate the sole pre-lock authority, and only 4 of 9 conjuncts are anchored (kill, gen, inflight, house=sleep, guest house leg, observation).
**F5b — Release on home states without owning the lock (MEDIUM).** `:633-635` `if self.reason != REASON_NONE` removed -> GREEN; probe P6 (user locks the garage manually, house goes `home_day`; regime idle) RED. The regime would unlock a lock it never engaged.

**F6 — Engage after the SC-disable release is covered by two redundant guards, neither tested (MEDIUM, #63).** `release_if_disabled`'s `release_gen += 1` (`:592`) off: GREEN. `engage_predicate`'s SC-alive: GREEN. Both off together: GREEN (multi-drill A). Each guard hides the other, so the sequence "engage queued, SC switched off, release unlocks, queued engage re-locks the garage during the teardown await" has no test. I did not build a probe for the combined sequence (needs a held engage task across the teardown await); treat as unproven rather than proven-leaky.

**F7 — Teardown bound and cleanup unanchored (MEDIUM).** `asyncio.wait(..., timeout=...)` -> `timeout=None` GREEN (a stuck unlock would block unload forever; the existing timeout test covers only the SC-disable release path). `task.cancel()` loop off GREEN (untracked background tasks, QUALITY_CONTEXT class).

**F8 — Vacation never released by backstop: no live-path test (MEDIUM).** Three guards (`_on_backstop` reason gate, `_cancel_backstop` on VACATION engage, recheck cancel). Removing the first two together is GREEN; probe P16 (sleep -> vacation live, 10 h) RED. Only the restart path (`test_restart_late_house_state_restore_upgrades_reason`) is tested, and only via the third guard.

**F9 — Other observable-but-untested conditions (MEDIUM/LOW, probes RED on mutant):** hazard type filter (P5: a critical `water_leak` hazard would release the lockouts); M2 release without `person=` (P10: no re-engage scheduled after an arrival signal); unmapped distance sensor blocked (P11); `obj in sensor_id` substring mapping (P14); `on_kill_switch_changed(True)` releases (P12); `away` sets reason SLEEP/backstop even though the predicate masks the lock (P13); non-wrapping sleep window includes the end hour (P15). Two probe-RED-on-first-run corrections: P9f needed an open door (a house=`home_night` probe was masked by the sleep house check) and P15 needed a non-wrapping config (default 22-06 uses the wrap branch).

**F10 — Boot recheck and re-engage-row seams (MEDIUM-LOW).** Recheck BOOT_UNKNOWN -> SLEEP upgrade, vacation backstop cancel, and torn guard GREEN (the upgrade matters because only SLEEP/GUEST_NIGHT schedule a re-engage after an arrival). Re-engage row house legs, stale `_reengage_gen` guard, `after_release` sleep-window leg, GUEST_NIGHT reason leg, `releasing_set.clear()` after a re-engage, proximity-as-arrival all GREEN.

**F11 — `away` state leak behind a masking predicate (LOW-MED, #63).** `new == "sleep" or new == "away"` -> GREEN because `engage_predicate` drops it ("house_left_sleep"); the test asserts only "no lock call". Reason and backstop state are unasserted (P13).

**F12 — SC-side isolation and diagnostics unanchored (MEDIUM-LOW).** The four `except Exception` wrappers (house-state feed, hazard feed, disable-release, teardown), the `_async_setup_lock_regime` failure isolation, the Store handed to the regime, the `sensor.py` snapshot merge, optimizer layer-2 fail-closed (`except -> owned=True`) all GREEN. The statement "a regime error cannot touch the arming path / never blocks SC setup" has no failing-regime test.

**F16 — `reengage_delay_s = 0` ("never re-engage") is covered only by coincidence (MEDIUM-LOW, #63).** `:1159` `if delay <= 0: return` dropped -> `test_number_knob_read_live_by_regime` GREEN: the 0-delay timer fires but the re-engage is dropped by the read-back in-flight latch. Intentional knob semantics rest on a timing accident.

### LOW
**F13** `_release` ignoring `_spawn_unlock` False (record lists an entity not unlocked); `_boot_recheck_unsub` not cancelled at teardown (callback self-guards on `_torn_down`); after-unlock-in-teardown early return; `lockout_overlap` unsorted; `cover_ownership` string-input branch; NM `hazard_type`/timeout; optimizer `applied_outcome` stamp.
**F14** `release_if_disabled` entry-None/skip-unlocked/reason reset; `_cfg` precedence (options vs data); boot-rebuild kill gate; backstop release reason reset; `<=` / `>` boundaries (`_really_away` 15 min, backstop today-deadline, `_seconds_until_hour`); hazard `on_hazard` cancel/reason/torn; `old and not value` on the switch.
**F15 — Store shape test is hollow (LOW, #62).** `test_corrupt_resident_store_shape_ignored` passes with the shape check removed, because the `startswith("person.")` filter already discards the characters of a string. Only removing both turns it RED. The B-L3 warning log and the shape guard are unanchored.
**F17 — Test-order coupling (LOW, process).** Running `test_low_cleanup.py` AFTER the lockout test files fails 2 tests (`ModuleNotFoundError` at `test_low_cleanup.py:782`, `test_hvac_decision_cycle_enabled_guard` and `test_hvac_observation_switch_has_deferred_restore`) because the lockout files leave `sys.modules` state. Default alphabetical order is fine (260 pass); an explicit file list or `-p randomly` could trip it. Worth one line in the validator brief.

## Provably redundant / equivalent (not findings)
- Custom decorator: `_ha_callback` and the `setattr` each set the same marker; both removed is RED.
- `_setup_ts is None` branches (unreachable after `async_setup` stamps the time).
- M2 feed above the `enabled` return: `_release` already requires `_sc_alive` (`enabled`), so gating the feed is behaviour-identical.
- Proximity person mapping: live-persons leg and `_person_unsubs` leg are mutual backups (every live/added person is subscribed); both removed is RED.
- `_release` unavailable-lockout skip: apart from a warning line, the next condition also skips.
- `store_allstr`: a string `raw` iterates into characters that fail `startswith("person.")` (see F15).

## Summary
| | Count |
|---|---|
| single mutations | 316 (+12 multi, +24 probe sites) |
| RED | ~195 |
| GREEN | ~119 (of which ~12 equivalent/redundant) |
| HIGH findings | 4 (F1, F2, F3, F4) |
| MEDIUM | F5, F5b, F6, F7, F8, F9, F10, F12 |
| MEDIUM-LOW / LOW | F11, F13, F14, F15, F16, F17 |

## Verdict: **FIX-REQUIRED**
Must-fix (add tests; each probe above is a ready oracle and passes against unmutated source):
1. F1 kill-OFF release inertness (P1).
2. F2 proximity edge-trigger (P2) plus an approach-zone release test (named zone, friendly name, case, same-state no-op).
3. F3 guest-clock handler: reason set, backstop releases (P3), daily re-arm (P4), kill/toggle/boot conjuncts.
4. F4 latch cleared after exhausted read-backs (P7).
5. F5/F5b predicate conjuncts (P9a-f) and home-state release gated on reason (P6).
6. F6/F7/F8: the SC-disable queued-engage sequence, bounded teardown wait, task cancel, live vacation backstop (P16).
7. F9 probes P5, P10, P11, P12 (cheap, real behaviour).
F12 and the LOWs can ride the same pass (1-30 LoC each). No production-code defect was found by this review; every finding is a missing or hollow test. Findings F1-F4 are only HIGH because the suite would stay green if a regression landed there.

## Worktree state
`git status --short` shows only the pre-existing untracked `.lockout_drills.py`. HEAD `a69e924c` on `feature/sc-garage-lockout-phase1`, no tracked diff, no `__pycache__`. (One accidental `git checkout 3153a918` while probing the baseline was reverted immediately to the branch; no file edits resulted.)

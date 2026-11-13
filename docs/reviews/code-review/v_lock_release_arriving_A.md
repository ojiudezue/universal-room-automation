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

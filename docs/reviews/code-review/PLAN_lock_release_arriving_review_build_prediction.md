# Plan review (Tier 3, framing 2: adversarial build-prediction)

Plan: `docs/planning/PLANNING_lock_release_on_arriving.md` rev 1 (branch `plan/lock-release-arriving`, commit 1e3a54ee).
Question: what will the builder get wrong reading this plan?
Reviewer read COMPLETELY: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 1,026 lines),
`docs/architecture/SENSOR_FLEET_CLASSES.md`. Read in part: the audit (§4.2, §5, §7), `security_lock_regime.py`
160-2630, `security.py` 178-200, 1175-1470, 2382-2470, `house_state.py` 56-135, `presence.py` 5290-5350, the five
lockout test files' ARRIVING sites. HVAC not touched (ARRIVING producer unchanged). The identity manual was not opened:
the plan changes no identity path.

**Verdict: FIX-PLAN.** 5 HIGH, 10 MEDIUM, 7 LOW. The HIGHs are a self-contradiction in the taint lifecycle (F1), a D4
mechanism that does not exist in code (F2), a D4 constant that breaks the plan's own inequality (F3), a trust read of
raw `person.state` (F4), and a D3 trip-wire that is blind on the boot channel it claims to cover (F5).

---

## HIGH

**F1. Clearing the taint on every `_release` makes the episode's meaning depend on edge order, falsifies INV-ARR as written,
and makes D3 page on real arrivals.** Plan §4 D1 item 1 ("every `_release` call (any trigger)"); `_after_release`
`security_lock_regime.py:1693-1716`.
- 16/17 shape (edge before ARRIVING): S1 releases with no taint yet, ARRIVING sets the taint, HOME_* is held, and the
  episode continues.
- 8632 shape (ARRIVING leads by 45 s): ARRIVING sets the taint, S1 at +45 s clears it, and HOME_* (ARRIVING hysteresis
  60 s, `house_state.py` DEFAULT_HYSTERESIS) releases with `house_state:home_*`. That ends the episode: re-engage
  cancelled, reason NONE.
- Same arrival, two semantics. Worse, any HOME_* edge more than 120 s after the S1 release (a time edge hours later,
  HOME_DAY -> HOME_EVENING) releases on a `house_state:*` trigger in an episode that passed through ARRIVING, with no
  stamp in the window. That is a literal INV-ARR break by the plan's own design. `_episode_saw_arriving` is still True,
  so D3 sends NM HIGH "released without a resident arrival" on a real arrival.
- Repro: reason `sleep`. 02:30 AWAY -> ARRIVING (body), held. 02:31 HOME_* held. 03:00 Oji `not_home -> home`, S1
  releases and clears the taint. House stays HOME_* (no SLEEP edge). The next HOME_* -> HOME_* edge releases (nothing
  locked) and D3 fires.
- M7's description ("asserts the next real-arrival-free HOME_* after a person release still releases nothing extra /
  taint false") contradicts itself: taint false means that HOME_* releases.
- **Fix:** clear the taint only at episode boundaries: engage edges, `waking`, house_state, backstop and boot releases,
  hazard, kill switch OFF, SC disable. Never clear it on `person:` / `approach_zone:` / `proximity:` / `arriving_signal`
  releases. Then drop (a) from INV-ARR. The person path is the release, and a later HOME_* has nothing left to release.
  Rewrite M7 against the new rule.

**F2. D4's "no newer engage (release_gen unchanged)" relies on a mechanism the code does not have.** `release_gen` is
bumped only by releases: `_release` :1587, the SC-disable release :761. Engage only captures it (`_request_engage`
:1860; the stale-intent guard :1879). The D4 AC "A re-engage before 90 s (`release_gen` bumped by an engage)" cannot be
built without breaking that guard (INV-2). The S1 `_release` also bumps the generation itself, so a builder who captures
the generation before the call gets "changed" every time and the trip-wire never fires (a hollow test).
- Repro of the false page: 22:59:00 resident edge with reason NONE and the lockout unlocked. S1 runs and D4 is
  scheduled. 22:59:30 HOME_NIGHT -> SLEEP is an engage edge and locks at about +31 s. At +90 s the lockout reads
  `locked` and `release_gen` is unchanged, so NM HIGH "lockout locked after arrival" goes out.
- **Fix:** add an engage sequence counter, bumped in `_async_engage` on every issued `lock.lock` (or a last-engage ts).
  Fire only if no engage was issued after the S1 call. Capture `release_gen` after the S1 `_release` returns.

**F3. D4's 90 s violates the plan's own inequality, and its clock is unspecified.** Hold Number max is 60
(`number.py:4488`). Read-back is 20 s (`const.py:3901`) with 1 retry (:3902), and the retry starts another 20 s
read-back (`_on_readback` :1785-1787). That is 60 + 20 + 20 = 100 s, plus the blocking unlock call time, which is more
than 90. The §6 test "fail a test if the inequality breaks" will fail on day one. The plan also never says whether the
timer runs from `edge_ts` or from the S1 call:
- the S1 call happens after the hold (`_on_hold_confirm` :1340), so if the timer starts there, the hold is irrelevant;
- if it starts from `edge_ts`, 90 s is too short.

**Fix:** state "timer starts at the S1 call (post-hold)". The bound is then read-back x (retries + 1) + margin, so 90
holds. Assert that inequality, not the hold one.

**F4. The "live `home`" evidence leg reads raw `person.state`, which the presence architecture says not to trust for a
level decision.** Plan D1 item 6, D2 item 4, INV-ARR (b), D3's boot exemption. The State of Play §1 row 97 and §3 say
trust readers use `person_state_for_trust` (GPS-assistive, live since v5.103.90): a GPS-led raw `home` is overruled
when BLE says the resident is gone, and path α reads that overruled `location`. So house AWAY with a resident's raw
state `home` is a reachable, legal state.
- Repro: Oji abroad, phone GPS frozen `home`, BLE Leads overrules him to away, house AWAY. A zone phantom (68.5% of
  ARRIVING edges) produces AWAY -> ARRIVING. `resident_home_evidence()` is True on raw `home`, so auto-follow disarms
  (INV-AF broken). After a restart in the same state, boot recheck (b) unlocks the garage.
- **Fix:** the level leg calls `person_state_for_trust(hass, pid)` (fail closed: no person coordinator means raw state,
  as today's helper does) and excludes `_held_edges`. Edge readers stay raw, as the doc requires.

**F5. The D3 boot-recheck channel is blind after a restart, so its test can only pass hollow.**
`_episode_saw_arriving` is not persisted, and the plan does not say how a fresh instance sets it. After a restart a new
`LockRegimeController` starts with it False, so `_release("boot_recheck")` can never satisfy the D3 predicate. A boot
replay of ARRIVING could set it only if the builder routes replays through the new set. Unspecified.
`test_tripwire_covers_boot_recheck_channel` will then be written by assigning `regime._episode_saw_arriving = True`
(Bug Class #62, the very #56 gap the plan cites).
- **Fix:** persist it next to `garage_arrival_taint` in `_store_payload` / `_load_away_store`, AND set it at boot recheck
  when `house == "arriving"` and reason != NONE. Require the boot test to use two rigs sharing a `DictStore`, the same
  shape as `test_sc_garage_lockout.py:512-528`.

## MEDIUM

**F6. The boot recheck's `ended` expression still clears the manual-unlock memory on a tainted HOME_*** (Bug Class #53).
`:914-917`: `ended = kind == "release" or (kind != "guest_yield_hold" and (house in _HOME_STATES or house in ("waking",
"arriving")))`. D1 item 4 removes only `"arriving"`. A HOME_* house at boot with `kind == "arriving_hold"` still reads
`ended=True`, and `:922` clears `garage_manual_unlock`, which contradicts §3.3 row 4. Fix: add `kind != "arriving_hold"`
to the guard, and give it its own mutation row.

**F7. D3 fires even when nothing was unlocked.** The predicate is computed "before the kill-switch return" and ignores
whether any lockout was `locked` or pending. A house_state release with the lockouts already unlocked (an earlier manual
unlock, or F1) pages. Fix: evaluate after the entity loop, and only when `written` is non-empty.

**F8. D2's 120 s window is really about 60 s.** D2 item 3 clears the pending stamp "at `_handle_house_state_intent`
entry". ARRIVING -> HOME_* lands about 60 s after ARRIVING (hysteresis), and its intent clears the stamp. HOME_* is
unmapped (`security.py:189-195`, early return :1270), so a resident whose geofence trails ARRIVING by more than about
60 s stays ARMED_AWAY. The plan's "+45/+55 s with margin" has about 5 s of margin. Fix: clear the stamp only on intents
for mapped targets (away / vacation / guest / waking) and on teardown, and keep the 120 s window across HOME_*.

**F9. D2's discharge accepts suspicious-arrival blips.** It keys on a raw `SIGNAL_PERSON_ARRIVING(geofence)`, which
presence sends for any `-> home` including stale-source blips (`presence.py:5321-5349`; ledger #33 counts 78 blips in 7
days). The lock regime holds those blips (`_apply_arrival` :1044-1049); D2 would disarm on them. The plan also leaves
the order between SC's arriving handler and the regime's `_on_person_event` (both fed by the same state change)
undefined, and the S1 stamp depends on it. Fix: discharge only when `regime.resident_home_evidence()` (stamp leg, after
F4) is True at the signal. If the stamp has not landed yet, re-check once on the regime's S1 stamp write rather than
trusting the signal.

**F10. D2 mechanics are under-specified.**
- `_handle_person_arriving_signal` is sync and `handle_disarm` is async, so the disarm needs a tracked task cancelled
  at teardown (untracked-task class).
- The gate must sit after the `new_armed == old_state` noop check (`security.py:1430`). Otherwise an already-disarmed
  house stamps a pending disarm, and a later signal calls `handle_disarm` again and sends a duplicate NM.
- D3 item 2 is placed "before `handle_disarm` when `target_state == 'arriving'`". The discharge path has no
  `target_state`, so the auto-disarm trip-wire silently skips the second channel (#56). Name both call sites.

**F11. The taint and saw-flag clear sites have no choke point.** `reason` is written to NONE at `:767` (SC disable, not
in the plan's list), `:1072`, `:1099` and `:1708`. The engage-edge clear must sit before the kill-switch return (:825)
and the boot-window return (:828-832); otherwise a SLEEP boot replay leaves the flags set. Fix: one helper,
`_end_lock_episode_flags()`, called at the top of the engage branch and at every reason->NONE write, enumerated by
grep in the plan.

**F12. Behaviour claims told to the operator are wrong in mechanism.**
- (a) "Night arrival re-engages after 900 s once settled": `_reengage_row_fails` needs `house == "sleep"` (:1959-1960).
  On a SLEEP->AWAY->ARRIVING->HOME_NIGHT night the timer is abandoned with `house_not_sleep` (:2017-2019). What re-locks
  in practice is the live HOME_NIGHT -> SLEEP engage edge, which happens today too.
- (b) "VACATION: no release, ever, until a resident edge / switch" (§8, operator Q2): VACATION -> ARRIVING -> HOME_* ->
  SLEEP is a live engage edge that overwrites the reason to `sleep`, and the next WAKING releases.
- (c) "VACATION has no backstop": a restart rebuilds the reason as `boot_unknown` (`_boot_rebuild` :634), which is
  sleep-like, and the backstop runs with `allow_immediate`.
- Fix the D1 trade-off text and operator questions 1 and 2.

**F13. The §8 row "kill switch OFF during ARRIVING, ON afterwards: taint was still set; HOME_* after switch-on holds"
contradicts D1 item 1** (the switch going ON -> OFF clears the taint). It is also vacuous: the switch going OFF sets
reason NONE (:1099), and turning it back ON never catches up (INV-5). Delete or rewrite the row.

**F14. Some test inversions must swap the trigger instead of flipping the assertion.** In each of these, ARRIVING is
only an incidental second release used to prove a different property:
- `test_sc_garage_lockout.py:2512`: a failed spawn does not leave the latch stuck;
- `test_sc_garage_lockout_review_c.py:209`: the latch clears after read-back exhaustion (this site is not listed in the
  plan);
- `test_house_state_rung2a.py:383`: the de-escalation NM is MEDIUM.

Flipping these deletes the property. Swap the trigger instead: a `waking` edge after `sleep`, a fresh resident edge, or
`_pending_house_state = "waking"`. The genuine flips are `:172-178`, `:512` (drop the param), `:892-897` and the rung-2a
`arriving -> DISARMED` cases. `:2329` and review_c `:52` need no change.

**F15. One knob does two jobs** (Bug Class #63). `LOCK_RELEASE_TRIPWIRE_WINDOW_S` is the trip-wire window AND the
evidence window behind D2 gating and the D1 boot recheck. Setting it to 0 to quiet a noisy trip-wire silently changes
when ARRIVING disarms. Split it into `..._EVIDENCE_WINDOW_S` and `..._TRIPWIRE_WINDOW_S`, or state the coupling on the
constant.

## LOW

- **F16.** `resident_home_evidence(boot=True)` "additionally accepts a restored home". The live leg already reads the
  restored state, so the flag does nothing as written. Define it or drop it.
- **F17. Hollow-anchor guards to write into §7:**
  - M4 needs two rig instances sharing a `DictStore`.
  - Under F1's fix, M8 bites only on a boot-recheck or 8632-shape path. Name the fixture.
  - D3 and D4 tests use a named seam (patch `_edge_decision`'s return, or neuter only the S1 `_release` call) and never
    assign `_episode_saw_arriving`, `_arrival_taint` or `_resident_home_edges` directly.
  - Add drills for: the saw-flag clear on engage, the boot `ended` guard (F6), D4 engage suppression (F2), and the D2
    pending clear (F8).
- **F18.** Inside a tainted episode a manual HOME_* override and a GUEST -> HOME_* guest exit outside the window are
  both held. The audit §7.2 says "Keep ... manual-override HOME_* releases", and plan §5 says guest exit is "unchanged".
  Say so in the README, or exempt `old_state == "guest"`.
- **F19.** An ARRIVING edge with reason NONE no longer unlocks a lockout a person locked by hand (it used to release
  through `_release`). This behaviour change is not named.
- **F20.** Expose the taint (and the saw flag) in `snapshot()` (:2611) for "why is my garage locked". D3's message about
  "the last house edges" needs a small ring the plan does not create.
- **F21.** The audit's discriminating replay acceptance criteria were dropped. Audit §7 (a) runs the 10-14..10-18
  cluster plus edge 8623 (zero `lock_regime_release` rows); (b) runs 8545-8632 (each released by `person:*`).
  `quality/tests/_lock_arrival_replay.py` already exists. Add both.
- **F22.** The D4 timer must be a `@callback` bound with `functools.partial`, never a lambda (Review B-C1 hazard, comment
  at :1734). Unsubscribe it at teardown alongside `_held_edges`.

## Must-fix before build
F1, F2, F3, F4, F5 (HIGH); F6, F7, F11, F12, F13, F14 (they change code paths or operator-facing claims). F8-F10 and
F15 are needed only if D2 ships in this cycle; otherwise move them into the D2 sibling plan.

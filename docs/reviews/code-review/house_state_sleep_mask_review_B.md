# Review B: state machine, lifecycle, cross-coordinator (house-state SLEEP-mask cycle)

- **Branch:** `feature/house-state-sleep-mask-ble-memory`, head `2e10e3a09`. Diff base: `a0cd40412...HEAD` (three-dot).
- **Tier:** 3. **Framing:** B. A, C and D lanes are not covered here.
- **Read in full before review:**
  - `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`
  - `docs/architecture/SENSOR_FLEET_CLASSES.md`
  - `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, incl. the §10 ledger
  - the plan, Rev 2 + Rev 2.1 delta
  - `AUDIT_census_arc_and_away_holistic.md` §P5, at `1c74b467b`
- No ledger claim is re-asserted. No code contradicted either state-of-play doc on the surfaces reviewed.
- **Method:** code reading only. No pytest was run, because the C lane owns the suite. Every finding is cited to code. B-M1 was traced through the code but not reproduced at runtime.

## Verdict: SHIP

There is no CRITICAL or HIGH finding. Fold B-M1 (MEDIUM) and B-L1 into the fix-up pass. Both fixes are small and display or observability only.

## Findings

| ID | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| B-M1 | MEDIUM | `presence.py:6770` (mirror), `:7874` (`await log_decision`), `:8159` (`_note_away_entry` reads `self._veto_path`), `:8250` (D7 payload, pre-existing) | The AWAY branch label is read from the instance attribute after an `await`. See the scenario below. | Capture-before-first-await (value entry/exit); unserialized `_run_inference` |
| B-L1 | LOW | `_check_sleep_raw_hold` (`presence.py` ~4049-4115); `house_state.py:213-228` | The trip-wire false-fires under a manual house SLEEP override whose inferred state is not SLEEP. See the scenario below. | Suppression or trip-wire scoping |
| B-L2 | LOW | `_stuck_signal_nm.py:220-227` | The trip-wire NM goes out at `Severity.MEDIUM`. HVAC state-of-play §1 (S10 latch note, 2026-10-16) says MEDIUM reaches no channel under the live NM config: the companion channel is HIGH+ and the rest are CRITICAL. If so, `sleep_raw_hold` is an audit row plus an anomaly row (`_write_stuck_anomaly`), not a page. Not verified live. This affects every `stuck_signal` kind, not only this cycle's. Confirm the live NM thresholds before relying on it as the D1b-failure trip-wire. | Trip-wire delivery |
| B-L3 | LOW | `presence.py` `_check_sleep_raw_hold`: `_sleep_raw_hold_nm_fired = True` set before `hass.async_create_task(fire_stuck_signal(...))` | (a) If the emit returns False (NM missing at boot, kill switch, same-day latch from an earlier episode), the episode is marked fired and never retried. (b) The sleep-hour branch clears `_sleep_raw_hold_since` but not `_fired`, so a hold lasting more than one day pages only on day 1. Both match "one per episode" by design. Note them in the README; no fix is needed. | Latch semantics |
| B-L4 | LOW (latent) | `security.py:179-185` (`"waking": DISARMED`) | Cross-coordinator. D1b adds a new path: census-0 SLEEP→WAKING. Before the cycle, WAKING needed census > 0 because pinned zones read SLEEP. If `security_auto_follow` is enabled (off in the live CM entry per P5), an empty house held in SLEEP by a phantom is DISARMED at the end of the window. Before the cycle it would have gone AWAY→ARMED_AWAY. Inert today. Card it as a precondition for enabling auto-follow. | Cross-coordinator ripple |
| B-L5 | LOW (doc) | plan §3.2 row c vs `presence.py:5851-5855` | The plan says the arriving re-arm bypass is "less likely" while a resident is STALE-home. The code makes it more likely: `tracked_count > 0 and not all_tracked_persons_away` → True. The direction is the safe one, since a real arrival is never delayed, and `_arriving_last_was_outdoor_only` is also less likely to arm. Fix the plan wording. | Doc vs code |
| B-L6 | LOW | `_zone_night_rooms` `<error>` limb vs the WAKING gate's `any_zone_raw_occupied` (`presence.py` ~6207, ~6935) | If a room read raises, the zone counts as night-occupied. `raw_occupied` would raise or read False, so the 90 s WAKING gate never passes and the backstop needs census > 0. D1b then cannot discharge, and only the trip-wire covers it. This is exotic, since a dict read would have to raise. Accept and note. | Discharge coverage |

**B-M1 failure scenario.** `_run_inference` is not serialized; this was accepted at `presence.py` ~6232 as B-HIGH-2.
1. Tick 1 fires nobody-home and sets `_veto_path = "nobody_home"`. `transition(AWAY)` is accepted synchronously.
2. Tick 1 then yields in `_log_state_transition`, at the aiosqlite connect inside `log_decision`.
3. A concurrent tick (`census_update` / `occupancy_change` / `camera_detection`) runs end to end. It now sees `current_state == AWAY`, so `infer()` resets the label to `"none"` and returns None ("already away"). It mirrors `"none"` into `self._veto_path`.
4. Tick 1 resumes. `_dispatch_house_state_change` → `_note_away_entry` stores `last_away_branch = "none"`, and the D7 `house_state_transition` payload carries `veto_path = "none"`.

Effects:
- It falsifies the D3 claim that the label identifies the branch.
- It undercounts the scorecard rows filtered on `veto_path='nobody_home'` (plan §10 rows 1–2, D1 Live). That hides exactly the D1-broken rows the scorecard is meant to show.
- The frequency is not measured; the path is reachable on any AWAY edge with a concurrent trigger.

**B-M1 fix.** Capture `_veto_path` into a local at `:6770`. Pass it to `_dispatch_house_state_change(..., veto_path=<local>)`. Use that value in both `_note_away_entry` and the D7 snapshot. Override sources keep their mapping. The fix is about 6 lines. Anchor it with a test that runs a second `_run_inference` from inside a patched `decision_logger.log_decision`.

**B-L1 failure scenario.** A manual house SLEEP override is set from inferred HOME_DAY, for example a daytime nap, with census 0 and any room raw-occupied.
- D1b proposes WAKING. `transition()` validates against the underlying `_state` (HOME_DAY), and HOME_DAY→WAKING is not in `VALID_TRANSITIONS`, so it is rejected.
- `held` is True, and `now − window_end > 5400` is already true at, say, 14:00. The trip-wire therefore fires on the first tick.
- Its message, "the wake-time discharge (D1b) did not release it", is wrong: the hold is the operator's override.
- It is also reachable with sleep hours 0-0. There, `_is_sleep_hour` is never true and SLEEP is entered only by override or restore.

**B-L1 fix.** Skip the trip-wire (clear its episode) while `manager.house_state_machine.is_overridden`.

## Cleared (holds because …)

### Transitions and dwell: does D1 or D1b suppress a legitimate AWAY or WAKING?

- **SLEEP→AWAY.**
  - D1 changes only the nobody-home condition (`presence.py:1137-1146`). α and β come after it, unchanged. β is still sleep-exempt.
  - A false-positive raw hold is bounded by D1b at the end of the window, and the trip-wire backs it up.
  - The SLEEP 600 s dwell is unchanged (`house_state.py:129-139`).
  - The PICK 1 carve-out holds: an AWAY-pinned zone reads `mode == AWAY` (`presence.py:654-658`), so it counts as empty.
- **SLEEP→WAKING.**
  - D1b (`presence.py:1320-1327`) runs only when `has_people` is False, `current_state == SLEEP`, it is not a sleep hour, and `any_zone_occupied_for_empty is True`.
  - Nobody-home already reads the same input, so D1b can never shadow an AWAY that would otherwise fire. α and β precede it.
  - With census 0 the path goes GUEST-exit (n/a) → sleep-hour (false) → SLEEP→WAKING (`:1376-1379`). The 90 s raw gate still applies (`:6925-6935`).
  - `_zone_night_rooms` mirrors `_derived_mode` (`:768-790`), so the night input and `raw_occupied` agree except for the B-L6 `<error>` limb. The gate passes after 90 s of sustained raw occupancy.
  - After WAKING is accepted, `set_sleep(False)` unpins the zones (`:7290-7295`). The next tick then goes WAKING→HOME_DAY, or AWAY if the room cleared. Both are valid (`house_state.py:113-116`).
- **ARRIVING.** D1b requires SLEEP and D1 changes only nobody-home, so AWAY→ARRIVING is unchanged.
- **GUEST.** There are no pinned trackers in GUEST, so behaviour is byte-identical. GUEST→SLEEP was never valid.
- **House overrides.**
  - **HOME override after SLEEP:** zones stay pinned and D1 holds HOME (intended, R2 M2). D1b is inert because `current_state` is not SLEEP.
  - **SLEEP override over inferred SLEEP:** D1b's WAKING clears it, as census > 0 WAKING always did, and as the old false AWAY did. This is the pre-existing "inference clears override" rule (`house_state.py:250-256`).
  - The only new defect here is B-L1.
- **Zone overrides.**
  - A manual zone SLEEP override in a HOME house reads raw for nobody-home (intended).
  - `set_sleep` never pins an already-overridden zone (`:930-937`).
- **boot_settle.**
  - Restored SLEEP pins at the reconcile tick (`:2460-2468`). Proposals before that tick are deferred (`_should_defer_transition_for_boot_restore`).
  - Gated dispatches write no row and count nothing (`:8203-8217`, counter at `:8282`).
  - Side benefit: a boot-transient census-0 tick on a restored SLEEP no longer proposes a false AWAY.

### Byte-identity on the no-op path (no SLEEP-mode tracker, nobody STALE)

- With no SLEEP-mode tracker, `any_zone_occupied_for_empty ≡ any_zone_occupied` (`:6221-6229`). Nobody-home is therefore identical.
- D1b needs `has_people False` ⇒ `any_zone_occupied False` ⇒ the input is False ⇒ inert. This also covers `current_state == SLEEP` with all trackers overridden or no trackers.
- `_tracking_active` is unchanged for non-STALE statuses (`:6067-6073`).
- New side effects per tick: `_check_sleep_raw_hold` clears two RAM fields; `_guest_room_gate_fired_room` has no other reader; the new attributes are display only.
- The only permitted delta is `_veto_path = "nobody_home"` on the firing return. `_veto_path` has no decision reader; it is read by `sensor.py:5668`, the D7 snapshot `:8250`, and `_note_away_entry`.
- D6 `TrackerTrustExcludedWriter` sees fewer set-diffs while someone is STALE, which means fewer rows: the safe direction.

### Restart

- **Counter.** `_hydrate_away_entries_today` (`:8165-8183`) runs at setup next to the existing `_transitions_today` hydration (`:2655-2663`). It uses the naive-UTC `start_of_local_day` bound and the DAO kwargs. The default call's SQL is byte-identical (`database.py:3059-3070`). The getter returns 0 on a new local day (`:8139-8143`), and the periodic rolls at midnight (`:5256-5260`). An unflushed write-queue row at reload is within the stated INV scope ("within one flush").
- **STALE is not restored.** The PersonCoordinator `old_data` is empty at boot (the STALE branch needs `old_last_bermuda_update`, `person_coordinator.py:603-616`). The test `test_stale_not_restored_across_restart` anchors it.
- **Trip-wire episode state.** It is RAM-only (`_sleep_raw_hold_since`, `_sleep_raw_hold_nm_fired`) and resets at restart. `_LATCHES` is module-level: it survives a config-entry reload, so there is no double page that day, but a full HA restart resets it, allowing at most one more NM that day. Acceptable.
- **The moved 60 s periodic** (`:2995-3016`).
  - It is registered after the discovery `try:` closes, in its own try. There is exactly one `async_track_time_interval` per `async_setup` call.
  - There is no early `return` in `async_setup` before it; its top-level try blocks are listed at `:2544-3098`.
  - It is appended to `_unsub_listeners` and cancelled by `_cancel_listeners` (`base.py:287-299`), called from `async_teardown` (`:8000`), which clears the list. A re-setup therefore registers one fresh handle.
  - Tests `test_periodic_registered_when_discovery_raises` and `test_periodic_cancelled_on_unload_and_not_double_registered` drive the real `async_setup` and `async_teardown`. The second covers a single setup and teardown, not setup→teardown→setup on one instance. That is an acceptable gap, because reload builds a new coordinator.

### D2 readers (each read in code)

| Reader | Code | Effect for a STALE resident | Verdict |
|---|---|---|---|
| Perimeter `persons_home` | `perimeter_alert.py:1684-1704` reads `_tracked_persons_count_trusted` | +1 | Holds, intended |
| HVAC Wait-for-Presence | `hvac.py:2711-2745`: defer when consensus < 0.5 within 30 s of a transition, hold until ≥ 0.7. `presence.py:7534` drops the −0.4 term only when `all_tracked_persons_away` turns False. A STALE location is a room (`person_coordinator.py:612-614`), so it is not `away`. | HVAC defers less | Holds; matches the house-state direction |
| Compliance consensus defer | `coordinator_diagnostics.py:659-683`: suppress the emit when consensus < 0.6 for ≥ 60 s | Fewer suppressions while a resident is STALE-home | Holds, intended |
| Arriving re-arm bypass | `presence.py:5851-5855`, callers `:7179`, `:7246` | Bypass more likely (safe direction) | Holds; see B-L5 for the doc fix |
| Zone `room_level_weighted` veto context | `presence.py:6472-6486` passes `all_tracked_persons_away`/`tracked_count` | Context sees the resident as home | Holds |
| −0.2 term (`any_stale_or_lost_tracker`) | Keyed on `location == "unknown"` (`:7518-7538`) | Unaffected by D2 | Holds |

### Cross-coordinator: HVAC and security

- **HVAC.**
  - HVAC reads house state only for preset choice, the night-tail selection (`HVAC_NIGHT_HOLD_STATES`) and the D6 failsafe skip in SLEEP (`hvac.py:3060-3064`).
  - Zone vacancy is independent of house state (HVAC doc ledger #11; P5 §4), so D1 cannot keep an empty zone conditioned.
  - Fewer false SLEEP→AWAY→ARRIVING flaps means fewer Carrier writes.
  - D1b's WAKING→HOME_DAY at the end of the window on a census-0 house gives the same preset sequence a census > 0 house already gets.
  - No HVAC code was touched, so the HVAC doc needs no update.
- **Security.** Only B-L4, which is latent.

### `fire_stuck_signal` latch

- Per-(kind, key) per local day (`_stuck_signal_nm.py:182-192`). It is fail-open and writes one anomaly row per emit.
- The cycle adds an episode latch on top, which resets when `held` goes False (`presence.py` `_check_sleep_raw_hold`).
- The task is a one-shot `hass.async_create_task`, the same pattern as `actuator_reconciler.py:1146` and `coordinator.py:2664`. `presence.py` is not in the scope of `test_setup_unload_symmetry` for untracked tasks.
- The residuals are B-L2 and B-L3.

## Invariant checklist (framing B view)

| Invariant | Status |
|---|---|
| INV-SLEEP-NOT-EMPTY (with carve-out) | PASS |
| INV-SLEEP-HOLD-BOUNDED (b): out of SLEEP by window end + dwell | PASS, with no house override. Under an override, see B-L1. The `<error>` limb is B-L6. |
| INV-BYTE-ID | PASS |
| INV-NO-BLE-HOLD / STALE not restored | PASS |
| INV-COUNTER-MATCHES-LOG | PASS. The count can match while the label is wrong (B-M1). |
| Periodic registered exactly once, cancelled on unload | PASS |

## Statistics

| Severity | Found | Must-fix before ship |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 1 (B-M1) | fold in the fix-up (recommended) |
| LOW | 6 | B-L1 recommended; B-L5 doc; rest note/card |

| Bug class | Count |
|---|---|
| Capture-before-first-await / unserialized inference | 1 |
| Trip-wire scoping / delivery / latch | 3 |
| Cross-coordinator latent ripple | 1 |
| Doc vs code | 1 |

**QUALITY_CONTEXT candidate.** "Label read after await". A per-tick diagnostic copied onto `self` and consumed after an `await` in an unserialized handler. This is the same shape as the value-entry/exit rule, applied to display labels that feed acceptance scorecards.

# Review B — lock suspicious-arrival hold (async / lifecycle / race / cross-coordinator)

Branch `feature/lock-suspicious-arrival-hold` (70c6d4ac, 1eec0050), base b7e4289e (`git diff b7e4289e...HEAD`).
Plan `docs/planning/PLANNING_lock_suspicious_arrival_hold.md` rev 2.
Pre-read: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md`, both read completely. The doc's §1 hold row and §10 #33 match the code. No contradiction found.

Tests run (branch lock-regime files + new files, one serial process): 483 passed.

## Findings

| # | SEV | Site | Finding | Bug class |
|---|---|---|---|---|
| B-M1 | MEDIUM | `security_lock_regime.py:1164-1173` (revert-cancel branch) | Repro: Oji `not_home` since setup, Ezinne `home`, H = 5. Oji's iPad blip is held (`stale(OJI,"home")`). 0.3 s later Ezinne leaves (`fresh(EZ,"not_home")`), so `_away_on_person(EZ)` calls `_away_rearm` (:2152). `_away_due_ts` (:2167) reads Oji live `home` and returns None, so the dwell is cancelled and not re-armed. 0.5 s later Oji reverts to `not_home`: the pair cancels and returns at :1173 without re-arming. Result: both listed persons are `not_home` with no dwell timer, and the away lock never engages until the next listed-person edge (could be the whole outing). With H = 0 the same sequence engages at +300 s, because the revert is processed as a real leave and re-arms. Verified with a harness probe on the branch: H = 5 gives `locks_called("lock") == []` after 400 s, while H = 0 and no blip both give `[BED]`. The window is narrow (another listed person's edge inside a ~1 s blip), but the effect is a door left unlocked in an empty house. That is the opposite failure to the one the hold exists to prevent. **Fix:** in the revert branch, after `_record`, call `self._away_rearm(cfg)` unless `self._in_boot_window()`, as `_away_on_person` does at :2148-2152. `_away_rearm` changes no stamp, so INV-H3 holds. It also subsumes a pending F3 deferral: due is already past, so the timer fires at once and engages. Add a mutation-anchored test for this sequence. | Suppression needs a discharge (a cancelled edge drops a re-arm duty that a concurrent edge delegated to it) |
| B-L1 | LOW | `security_lock_regime.py:1114-1126` `_on_person_removed` | A person removed during a hold keeps its `_held_edges` entry, and its confirm timer stays live until H expires. The confirm is safe: `hass.states.get` returns None, so it is dropped at :1316. During those ≤ H seconds, though, `_apply_arrival`'s `person in self._held_edges` and the F3 dwell deferral still see it. The effect is bounded by H. Optional: `_drop_hold(pid)` in `_on_person_removed`. | Untracked state on lifecycle edge (bounded) |
| B-L2 | LOW | `_start_synthetic_hold` :1541-1552 | When a resident has read home on a stale source for a long time, a synthetic hold has `edge_ts` = an old `last_changed`. `due` is then in the past and the confirm runs on the next loop pass, so a proximity crossing releases with about 0 s delay. That matches develop and is harmless. If `_last_real[pid]` was a restored stamp (`prev[2] True`), the replay restamps it as real at `edge_ts` (:1214), which is the boot time after a restart. `_really_away` (:1346) then returns False for later P2 signals, where develop returned True (M-2 ii). This moves toward fewer unlocks (fail-safe) and is reachable only after a crossing while home. Noted, no fix required. | Concept drift on replay stamp (benign) |
| B-L3 | LOW (test gap, C's lane) | `test_lock_arrival_hold_real_ha.py` | No real-HA test fires the confirm timer. I checked by probe (temporarily appended to the file, then restored; tree clean). With real `async_call_later` + `async_fire_time_changed(+6 s)`, the `functools.partial` of the `@callback` `_on_hold_confirm` runs on the loop, `arrival_hold_confirms == 1` and both lockouts unlock. After `async_teardown`, the same time jump fires nothing. Suggest committing both as tests. | — |

## Cleared (holds because …)

- **Timer handles:** each hold owns one `_call_later` unsub (:1285). `_drop_hold` unsubs on revert, other-value and `old_state None` (restore/add, :1146). `async_teardown` unsubs every hold and clears the dict (:692-694). `_on_hold_confirm` pops before replay and returns if `_torn_down` (:1313-1315). Reload = teardown plus a new instance (holds are not persisted, by design R5). Confirm after teardown was verified not to fire in real HA (probe above).
- **Kill switch off / SC disabled / observation:** the hold does not check these. That is the same as develop's person listener: every effect still routes through `_release` (:1564-1567, `kill_switch_on` / `_sc_alive`) and `_away_release`. Confirm after kill-off is a no-op write.
- **Callback vs coroutine:** `_on_hold_confirm` and `_on_away_dwell` are `@callback` and synchronous. HA unwraps the partial (same pattern as readback, review B-C1). Nothing awaits between the stale read and the hold decision.
- **Same person, two edges in a hold:** a same-state event (attribute-only or a source switch) is ignored and keeps the hold (:1147-1157). On a revert the pair cancels (INV-H3). Any other value drops the hold and is re-judged from the pre-edge value, so a second stale edge starts a fresh hold with a new ts. The re-entrancy slot is cleared before replay.
- **Two people concurrently:** `_held_edges` is per pid with independent timers. The F3 deferral takes `max(due)` over held listed persons (:2241-2245). The confirm replay cancels the dwell through the home branch (:2137). A cancel fires at due+0.1 and engages (`test_away_dwell_deferred_during_hold`).
- **`_last_real` / `_arrival_edges` ordering:** while an edge is held, S1-S5 do not run, so P2's `_really_away` sees the pre-edge `_last_real`, and P2 is dropped anyway while held (:1036-1041). The replay stamps with `edge_ts` (`_process_person_edge` :1181-1214). The face stamp `_arrival_edges` is deferred to confirm, so a face during a hold is not corroborated by the blip (`test_face_not_corroborated_by_blip`).
- **`_process_person_edge` refactor / H = 0 byte-identical:** the golden is real, not self-referential. I extracted the base tree (`git archive b7e4289e`), copied only the replay driver and the edge fixture, and ran `run_replay(None)` (no knob) against develop's `security_lock_regime.py`. Both `trace` and `final` equal the committed golden (339 inputs, 118/118 edges release). The `_Val`-wrapped `live_arrival_slug` reads only `.state` and `entity_id` (`arrival_edges.py:33-42`).
- **SIGNAL_PERSON_ARRIVING consumers outside the lock regime:** the diff does not touch `presence.py` or any other consumer. Only `LockRegimeController._apply_arrival` gates.
- **Boot window:** person edges (:1257), P2 stale (:1038) and proximity (:1531) all bypass inside `_in_boot_arrival_window()` (600 s), and boot replays never arm the dwell (unchanged :2148).

## Summary

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | – | – |
| HIGH | 0 | – | – |
| MEDIUM | 1 | 0 | – |
| LOW | 3 | 0 | – |

Bug classes: suppression-needs-discharge (1), lifecycle-edge state (1), replay-stamp concept drift (1), test gap (1).

## Verdict

**FIX-REQUIRED**. Must fix B-M1: re-arm the away-lock dwell on the revert-cancel branch (`security_lock_regime.py:1173`), with a mutation-anchored test for the "other listed person leaves inside a hold" sequence. B-L1 and B-L3 are cheap and recommended in the same fix-up.

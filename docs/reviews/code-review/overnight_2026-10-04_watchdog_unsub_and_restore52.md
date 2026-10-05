# Overnight 2026-10-04 — review record: watchdog stop-unsub + Bug Class #52 restore sweep

Two Tier-1 builds taken to `review` by the overnight pass (autonomous → two framing-disjoint reviews +
orchestrator mutation verify each). Neither is deployed; both ride the next operator-timed release.

## 1. LOOP-STALL-WATCHDOG-STOP-UNSUB-ERROR-1 — `fix/loop-stall-watchdog-stop-unsub` (117016e1d + 59caf1743)

The HA-stop once-listener handler called `uninstall()`, which called the listener's own (already
consumed) unsub, so HA logged `Unable to remove unknown job listener` from a worker thread at every
shutdown. Fix: `_on_stop` clears `wd._ha_stop_unsub` before `uninstall()`.

| # | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| A1 | LOW | Comment at `_loop_stall_watchdog.py:286-287` claimed HA's once-listener unsub is "safe to call twice" — false (`core.py` `_async_remove_listener` logs ERROR on the second call) | Stale/false documentation | FIXED (59caf1743) |
| B1 | LOW | Unload-vs-HA-stop race: `_on_stop` (executor) and unload (loop) can both reach `uninstall`; registry `pop` is atomic so only one proceeds; the loser can log the same line once | Concurrent teardown race (pre-existing) | DEFERRED — harmless, pre-existing |
| B2 | MEDIUM-advisory | New test uses a fake bus (`_UnsubTrackingBus`); proves the regression, not HA's real log line | Test authority (fake collaborator) | ACCEPTED — live acceptance = 0 such lines at the next shutdown |
| A2/B3 | LOW | `uninstall` pops `hass.data` off-loop (pre-existing, single atomic op at shutdown) | Off-loop state mutation | DEFERRED — pre-existing |

Verification: targeted file 9/9; orchestrator single-site mutation of the new line → `test_ha_stop_fire_does_not_call_consumed_unsub` red. Note: both reviewers ran the file concurrently and one observed an in-place drill mutation mid-run — `test_loop_stall_watchdog.py` carries in-place source-mutation drills (an instance of TEST-SOURCE-MUTATION-INPLACE-RESIDUAL-1).

## 2. RESTORE-UNAVAILABLE-OFF-SWEEP-1 — `fix/restore-guard-52-sweep` (63523e0ed)

Live incident (HA recorder): after the 61-minute v5.103.37 CM outage on 10-03, restore state was saved
as `unavailable`; at the 21:59Z restart `switch.ura_hvac_coordinator_zone_sweep` (default ON, on for 10
days) restored OFF. Fix: Bug Class #52 guard (`last_state.state in ("on","off")`) on 9 switch restores —
6 behavioural (HVACZoneSweep, SecurityDelegateLights, AutomationSwitch, CoverAutomationSwitch,
AiAutomation, InfrastructureRoom), 3 behaviour-neutral default-OFF (OverrideOccupied, OverrideVacant,
ManualMode).

| # | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| A1 | — | Independent enumeration of all 51 `async_get_last_state` sites: no remaining unguarded site where unavailable/unknown overrides a non-matching default | #52 completeness | PASS |
| A2 | LOW | Guarded skip logs nothing; some prior sites log INFO "skipping restore" | Diagnostics consistency | DEFERRED — cosmetic |
| B1 | LOW | `test_restore_guard_present_in_source` is a source search (hollow anchor); each default-ON class also has a behavioural test | #62 hollow test anchor | ACCEPTED as tripwire only, not counted as coverage |
| B2 | LOW | `asyncio.get_event_loop()` in the test harness will warn in future Pythons | Test hygiene | DEFERRED |

Trade-off (accepted, matches every earlier #52 site): an operator-OFF switch saved as `unavailable` now
restores to its default ON. None of the changed switches is safety-relevant in the wrong direction.

Verification: 18/18 targeted; builder per-site mutation drills red at all 6 behavioural sites; orchestrator
re-drilled HVACZoneSweep → its behavioural test red; restored clean. HA `restore_state.py:166-182` confirmed
to persist `unavailable` (skips only `ATTR_RESTORED` placeholders).

## Summary

| Severity | Found | Fixed | Deferred/accepted |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 1 (advisory) | 0 | 1 |
| LOW | 7 | 1 | 6 |

| Bug class | Count |
|---|---|
| #52 RestoreEntity unavailable-coercion | 1 (the cycle's subject) |
| #62 hollow test anchor | 1 |
| Concurrent teardown race / off-loop mutation | 2 |
| Stale documentation | 1 |

QUALITY_CONTEXT: no new class. Suggest appending to #52 the 10-03 zone-sweep exemplar and the note that
HA persists `unavailable` whenever URA is down at a periodic save, not only at shutdown.

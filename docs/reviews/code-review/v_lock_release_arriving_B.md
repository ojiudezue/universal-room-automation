# Review B: LOCK-RELEASE-ON-ARRIVING (integration / state machine / restart / async lifecycle)

Branch `feature/lock-release-arriving`, HEAD 30b80831, base e4069fca (merge-base with develop). Plan
`PLANNING_lock_release_on_arriving.md` rev 3. Tier 3, framing B.

Read first: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete), `SENSOR_FLEET_CLASSES.md` (complete),
`IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5 (lock regime and the new "house state is not identity" paragraph), the
`QUALITY_CONTEXT.md` bug-class index (#19, #42, #53, #62, #63 bodies). No ledger claim re-asserted.

Tests run (single files, `PYTHONDONTWRITEBYTECODE=1`): `test_lock_release_arriving.py` 80 passed,
`test_sc_garage_lockout.py` 204 passed, `test_sc_garage_lockout_real_ha.py` 3 passed,
`test_sc_garage_lockout_review_c.py` 39 passed. Two repro probes run from the session scratchpad (not committed);
tree clean afterwards.

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| B-H1 | HIGH | `security_lock_regime.py:1433-1441` (`_on_still_locked`) with `:1865-1871` (`_release` skips unavailable) | A lockout that is `unavailable` at the resident's S1 edge and comes back `locked` is never released and never paged. `_release` skips it (one WARNING). The D4 timer then sees `locked`, but `State.last_changed` (the unavailable -> locked change) is after `anchor_wall`, so the R2-7 "re-locked by someone else" skip fires. Before this cycle the ARRIVING / HOME_* edges ~35-95 s later released it; now they are `arriving_hold` in the tainted episode. The lock stays locked until the morning backstop (none under VACATION). Repro (run): tainted SLEEP episode; `LOCK_A` unavailable; Ezinne `not_home -> home` (S1 unlocks only LOCK_B); +30 s `LOCK_A` reads `locked`; HOME_NIGHT edge (held); +100 s: 0 unlocks of LOCK_A, 0 `lockout_locked_after_arrival` pages. Same silence if the lock is still `unavailable` at +90 s and returns `locked` later. This breaks the operator constraint "no real arrival may lose its release" on a path that used to be covered. | Suppression without discharge; #53-adjacent (R2-7 skip keyed on a value that conflates availability recovery with a human re-lock) |
| B-L1 | LOW | `security_lock_regime.py:1410` (`_schedule_still_locked` pops the pid's pending timer) | One timer per pid: a D4b `unavailable -> home` flap after a counted arrival replaces the pending `arrival` check with a new anchor and kind `uncounted`. A phone flapping faster than 90 s postpones the page indefinitely, and the page that finally lands says "phone was offline when they left" for a resident whose arrival did count. Repro (run): tainted episode, S1 cannot unlock (SC not alive), Ezinne home, then 4 flaps at 60 s spacing -> 0 pages at +240 s; pages arrive only 91 s after the last flap, as `uncounted`. D0 measured 0 resident unavailable edges/week, so rare. Fix: do not replace a pending check (keep the earliest anchor) or key by (pid, kind). | Suppression without discharge |
| B-L2 | LOW | `quality/tests/test_sc_garage_lockout_real_ha.py:286` | The real-HA rig schedules a D4a timer and tears it down, but never lets `_on_still_locked` fire on a real loop (partial + `@callback` job typing, `now` positional). Same pattern as `_on_readback`, which is real-HA exercised, so low risk. | Test coverage |
| B-I1 | INFO | `security_lock_regime.py:875` / `:943-948` | Kill switch OFF is byte-identical in effect: reason stays NONE, so no taint, no hold, no timer, no page. Only difference: an ARRIVING edge no longer bumps `release_gen` (old path entered `_release`, bumped, returned on kill-off), so `last_action.release_gen` diverges. No consumer acts on it while off. | - |
| B-I2 | INFO | `security_lock_regime.py:1058`, `:1073` | Boot recheck `already_locked` / `manual_unlock_remembered` call `_set_engage_reason`, which clears a restored taint. Only reachable with house `guest` in the sleep window from BOOT_UNKNOWN; a tainted episode cannot reach GUEST in the sleep window (night yield), and the live guest clock clears at the same boundary. Consistent with the plan's boundary list. | - |
| B-I3 | INFO | `presence.py:2689-2699`, `house_state.py:283` | `override_set` is also emitted by the boot-settle reconciliation for a restored operator override and by the `ura.set_house_state` service (HA automations can call it). Both bypass the taint by design (operator intent, possibly an earlier one). README should say "override" includes the service. | - |

## Cleared (holds because)

- **Store / boot ordering.** `async_setup` loads the Store (`:562-565`, flags restored, missing/non-bool -> False at
  `:2869-2870`), then `_boot_rebuild` (`:626`). The `_save_store` at `:593` is a delayed save whose payload lambda reads
  state at write time, so rebuild changes are what lands. Nothing-locked return clears a stale taint (`:659`); SLEEP /
  VACATION rebuilds clear (`:664`, `:667`); BOOT_UNKNOWN keeps it and adds it for house away/arriving (`:671-677`).
  The regime is attached to SC only after `async_setup` completes (`security.py:726-727`), so no edge can interleave
  with the load; an edge missed in that window is covered by the house away/arriving rebuild or is the named §9.3
  residual. Teardown flushes the full payload (`:774-779`); HA Store's final-write flush covers a stop.
- **Boot recheck.** Taint set before `_edge_decision` (`:1023-1028`); `arriving_hold` never acts (`:1050-1053`); `ended`
  excludes `arriving_hold` (`:1032-1035`). GUEST_NIGHT conversion keeps the taint (`:1022`, allowlisted).
- **Timers / teardown.** D4 handle per pid, popped on fire (`:1428`), cancelled on reschedule (`:1410`) and in teardown
  (`:741-743`); callback guards `_torn_down` and kill switch (`:1429`); `@callback` shim applied (`:74-87`), partial not
  lambda (#42/#45). NM sends go through `_spawn` (tracked, cancelled at teardown; #19). `engage_seq` bump sits after the
  predicate with no await before `lock.lock` (`:2248-2252`), INV-2 intact.
- **Person path.** S1 / approach / proximity / `arriving_signal` never clear the flags (`_after_release:2023-2048` only
  clears on house_state / backstop / boot_recheck and the VACATION arrival arm). Held edges replay through
  `_process_person_edge`, so D4a anchors after the hold. Boot-arrival window: `_really_away` True, so D4b unreachable.
- **Hazard / kill switch / SC disable.** Release first, then `reason = NONE` + clear helper (`:1197-1199`, `:1225-1227`,
  `:815-816`); triggers are not `house_state:*`, so D3 is silent.
- **D3.** `saw_before` captured before `_after_release` clears it (`:1851`); `written` empty -> silent; waking / override
  exempt (`:1905-1911`).
- **Guest clock.** Routed through `_set_engage_reason`: same reason write and `_schedule_backstop(cfg)`, plus the clear.
- **H3b dedup.** `_failure_nm_at` stamped at `_notify_failure` entry for the garage policy only (`:2136-2138`).

## Summary

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 1 | 1 |
| MEDIUM | 0 | 0 |
| LOW | 2 | fix in cycle (B-L1 is ~5 lines) |
| INFO | 3 | README note for B-I3 |

Bug classes: suppression without discharge (2), test coverage (1).

## Verdict: FIX-REQUIRED

Must fix B-H1. Suggested shape: stamp `_lockout_unlocked_at[ent]` in `_on_lockout_event` when a lockout reads
`unlocked`, and skip the R2-7 re-lock only when that stamp is >= the anchor (the lock actually left `locked` after the
arrival). Also re-check (or page) a lockout that reads `unavailable` at the timer instead of skipping it silently.
Add the repro above as a test (lock unavailable at S1, back `locked` at +30 s -> one `lockout_locked_after_arrival`).
QUALITY_CONTEXT candidate: "availability recovery read as a state change" (a `last_changed` comparison that does not
check the prior value).

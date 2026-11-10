# URA v5.108.3: garage lockout boot recheck re-asks "locked now?"

Card: LOCK-BOOT-RECHECK-ENGAGE-1. Status: **Validated-pending** (fill in the table after the first restart that follows deploy).

## Behaviour change

`security_lock_regime.py` `_on_boot_recheck` runs once, 120 s after setup (`GARAGE_LOCKOUT_BOOT_RECHECK_S`). Before this change it only rebuilt `reason`. Boot-window house-state edges still only rebuild `reason` (plan M1). The recheck now applies the decision a real edge to the current house state would take. It uses the same decision helper (`_edge_decision`, now shared with `on_house_state_changed`) and the same write paths (`_request_engage` / `_release`).

- **Engage:** if the house is `sleep`, or `guest` inside the sleep window with the guest toggle on, and a lockout is unlocked, the lockouts are engaged with trigger `boot_recheck`. The backstop is scheduled exactly as the sleep edge schedules it. The engage predicate, observation mode and sweep-exclude still apply.
- **Release:** if `reason == boot_unknown`, a lockout is locked, and the edge path would release (`home_*`, `arriving`, `waking`), the lockouts are released with trigger `boot_recheck`, and `reason` resets to `none`.
- **No change needed:** no service call.
- **Guest-yield hold (INV-LOCK-1):** a `boot_unknown` lock found in `home_night` inside the sleep window with the guest toggle on is treated as the guest-night lock after the yield. It is held (`reason` becomes `guest_night`), and the next `home_day`/`waking`/arrival or the backstop releases it.
- **Arrival inside the boot window:** if a resident arrival released (or tried to release) since setup, the recheck does not engage. The re-engage machinery owns re-locking.
- **VACATION: no catch-up engage.** Plan INV-5's falsifier says an operator unlock during vacation must survive a restart. At boot, an unlocked lockout in vacation can't be told apart from that case, so the next real edge engages.
- **Unknown or unavailable house state:** the recheck does nothing and logs at debug level.

Every decision writes a `boot_recheck` diagnostic record (`decision` = `engage` / `release` / `already_locked` / `no_change` / `guest_yield_hold` / `arrival_suppressed` / `vacation_no_catchup`, plus the `locked` / `unlocked` lists) before any command.

**No effect while the master lockout (`security_garage_lockout_enabled`) is off.** That is the default.

## Live validation (prospective)

| Criterion | Evidence to collect | Result |
|---|---|---|
| A `boot_recheck` decision is recorded ~120 s after the next restart (master lockout ON) | SC decision log `lock_regime_boot_recheck`, or `last_action` on the lock regime diagnostic | pending |
| With the master lockout OFF, no `boot_recheck` record and no lock service call | same surfaces | pending |

# URA v5.108.3: garage lockout boot recheck re-asks "locked now?"

Card: LOCK-BOOT-RECHECK-ENGAGE-1. Status: **Validated-pending** (fill in the table after the first restart that follows deploy).

## Behaviour change

`security_lock_regime.py` `_on_boot_recheck` runs once, 120 s after setup (`GARAGE_LOCKOUT_BOOT_RECHECK_S`). Before this change it only rebuilt `reason`. Boot-window house-state edges still only rebuild `reason` (plan M1). The recheck now applies the decision a real edge to the current house state would take. It uses the same decision helper (`_edge_decision`, now shared with `on_house_state_changed`) and the same write paths (`_request_engage` / `_release`).

- **Engage:** if the house is `sleep`, or `guest` inside the sleep window with the guest toggle on, and a lockout is unlocked, the lockouts are engaged with trigger `boot_recheck`. The backstop is scheduled exactly as the sleep edge schedules it. The engage predicate, observation mode and sweep-exclude still apply.
- **Release:** if `reason == boot_unknown`, a lockout is locked, and the edge path would release (`home_*`, `arriving`, `waking`), the lockouts are released with trigger `boot_recheck`, and `reason` resets to `none`.
- **No change needed:** no service call.
- **Guest-yield hold (INV-LOCK-1):** a `boot_unknown` lock found in `home_night` inside the sleep window with the guest toggle on is treated as the guest-night lock after the yield. It is held (`reason` becomes `guest_night`), and the next `home_day`/`waking`/arrival or the backstop releases it.
- **Arrival inside the boot window:** if a resident arrival released (or tried to release) since setup, the recheck does not engage. The re-engage machinery owns re-locking.
- **VACATION catches up like sleep (operator 2026-11-10).** If the house is in `vacation` at the recheck and a lockout is unlocked, it is engaged (trigger `boot_recheck`), unless a manual unlock is remembered for this episode (below). There is no sleep-window or backstop gate for vacation, so this also happens in the daytime.
- **Remembered manual unlock (operator 2026-11-10, option B; INV-5; resolves review A MEDIUM).** When a person unlocks a lockout during an engaged episode (`sleep` / `vacation` / `guest_night`), the regime stores the episode in its existing Store (`security_lock_regime.py` `_store_payload`, new key `garage_manual_unlock`, same Store as residents and away-lock state). A lockout counts as manually unlocked when it goes from `locked` to `unlocked`, the regime has no release of its own in flight for it, and the SC-disable release is not running. After a restart in the same episode, the recheck records `manual_unlock_remembered`, rebuilds `reason`, and sends no lock command. The mark clears at the edge that ends the episode: the wake / `home_*` / `arriving` release, the morning backstop, a boot-recheck release, the SC-disable release, a new live engage edge (new episode), or a recheck that finds an awake house or a different episode. The next episode then locks normally.
- **Missing or corrupt Store value: no mark (fail secure).** A missing file, a missing key, a wrong type, an unknown reason or a load exception all read as "no manual unlock", so the catch-up locks. The cost is that a manual unlock is re-locked once if the Store write was lost (it is a 1 s delayed save, flushed by HA's final write at shutdown).
- **No engage outside the sleep hours or past the backstop (review A HIGH):** a SLEEP / GUEST-night catch-up engage needs both conditions: the current time is inside the configured sleep hours, and the morning backstop deadline has not passed. Otherwise the recheck records `past_backstop_no_catchup` and sends no command. Without this gate, a house still reading `sleep` at 09:00 (no wake edge) would lock again and move the backstop to tomorrow, leaving the lockouts locked all day.
- **Known LOW (accepted):** a lockout locked by hand in the daytime while the regime reads `boot_unknown` is released by the recheck when the house is awake. The regime cannot tell a hand lock from a stale night lock.
- **Unknown or unavailable house state:** the recheck does nothing and logs at debug level.

Every decision writes a `boot_recheck` diagnostic record (`decision` = `engage` / `release` / `already_locked` / `no_change` / `guest_yield_hold` / `arrival_suppressed` / `past_backstop_no_catchup` / `manual_unlock_remembered`, plus the `locked` / `unlocked` lists) before any command.

**No effect while the master lockout (`security_garage_lockout_enabled`) is off.** That is the default.

## Deviations from the original build

- The first build had a VACATION carve-out (`vacation_no_catchup`): no catch-up engage in vacation, to keep INV-5. Operator 2026-11-10 replaced it: vacation catches up like sleep, and INV-5 now holds because the manual unlock is persisted. The carve-out and its decision value are gone.
- Review A MEDIUM (a manual unlock during sleep was re-locked by the recheck after a restart) is resolved by the same remembered mark.
- A `manual_unlock` diagnostic record is written when a manual unlock is noted.

## Live validation (prospective)

| Criterion | Evidence to collect | Result |
|---|---|---|
| A `boot_recheck` decision is recorded ~120 s after the next restart (master lockout ON) | SC decision log `lock_regime_boot_recheck`, or `last_action` on the lock regime diagnostic | pending |
| With the master lockout OFF, no `boot_recheck` record and no lock service call | same surfaces | pending |
| A restart during vacation with a lockout unlocked and no manual unlock remembered locks it ~120 s after setup | `boot_recheck` record with `decision=engage`; lock entity `locked` | pending |
| A manual unlock during an engaged episode writes `garage_manual_unlock` to the regime Store | `.storage` file of the lock regime Store: key `garage_manual_unlock` = episode; `manual_unlock` diagnostic record | pending |
| A restart in the same episode after a manual unlock leaves the lockout unlocked | `boot_recheck` record with `decision=manual_unlock_remembered`; no `lock.lock` call | pending (occurs only if the operator unlocks by hand) |
| The mark clears at the next wake / home / arriving edge | Store key `garage_manual_unlock` = null after the edge | pending |

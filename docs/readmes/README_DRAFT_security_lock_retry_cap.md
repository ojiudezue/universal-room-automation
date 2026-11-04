# DRAFT — SECURITY-LOCK-SWEEP-RETRY-CAP-1

## What changed
The security coordinator's periodic lock check (`_evaluate_lock_check`) used to re-send
`lock.lock` / `cover.close_cover` on every interval for as long as a lock stayed unlocked or a
garage door stayed open, even when the command never took (audit
`docs/planning/AUDIT_security_sweep_and_mopup.md`: 46 lock commands on 2026-03-11 at a 30-min
interval, nearly every one followed by `unlocked` again).

Now each device gets a retry episode. The sweep sends at most N commands per episode. If the
device is still unlocked/open at the next check after the Nth command, the sweep stops commanding
it and sends ONE security notification: "<device> did not lock/close after N tries. URA has
stopped retrying until it changes state."

The episode resets when the device is seen locked/closed at a check, or when its state changes
between checks (tracked by the state's `last_changed`, so a manual lock-then-unlock re-arms it).
Unavailable/unknown devices keep their existing offline handling and are not counted.
Episodes live in memory only: an HA restart starts a fresh episode.

Not capped (one-shot actions, not retry loops): `_generate_lockdown_actions` called from the
unknown-person alert and the entry alert. They fire once per alert event.

## Constant
`SECURITY_LOCK_RETRY_CAP` in `const.py` (module constant, rung 1, review-gated), default `3`.
`0` disables the cap (unlimited retries, the old behaviour).

## Live acceptance criteria
- Next time a lock/garage command fails to take: the HA logbook shows at most 3 `lock.lock`
  (or `cover.close_cover`) calls from URA for that device in the episode, then none until the
  device changes state.
- Exactly one NM row with "did not lock/close after 3 tries" for that episode.
- Log line `Periodic lock check: retry cap (3) reached, stopped commanding: <entity>` once.
- After the device is locked/closed (or manually toggled), a later failure gets a fresh 3 tries.

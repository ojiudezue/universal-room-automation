# DRAFT — SECURITY-LOCK-SWEEP-RETRY-CAP-1

## What changed
The security coordinator's periodic lock check (`_evaluate_lock_check`) used to re-send
`lock.lock` / `cover.close_cover` on every interval for as long as a lock stayed unlocked or a
garage door stayed open, even when the command never took (audit
`docs/planning/AUDIT_security_sweep_and_mopup.md`: 46 lock commands on 2026-03-11 at a 30-min
interval, nearly every one followed by `unlocked` again).

Now each device gets a retry episode:
- The episode starts when the sweep first sees the device `unlocked` / `open`.
- The sweep sends at most N commands per episode. On the next sweep that still sees it
  unlocked/open, it stops commanding the device and sends ONE security notification:
  "<device> did not lock/close after N tries. URA has stopped retrying until it changes state."
- The episode ends ONLY when the device is seen `locked` (lock) or `closed` (garage). Transient
  states (`locking`, `unlocking`, `jammed`, `opening`, `closing`) continue the episode and are not
  success, so a lock that bounces unlocked -> locking -> unlocked still caps. A manual
  lock-then-unlock passes through `locked` and re-arms naturally.
- A `jammed` lock is still never sent `lock.lock` (unchanged).
- 24 h after capping, a fresh episode starts (fresh N tries and one fresh notice) if the device
  is still unlocked/open.
- Observation mode: while it is on, evaluate() drops all actions, so no attempt is counted and no
  notice is marked sent. Turning it off resumes with the tries unspent (and a pending cap notice
  still goes out).
- Unavailable/unknown devices keep their existing offline handling and are not counted.
- Episodes live in memory only: an HA restart starts a fresh episode.

`sensor.ura_security_last_lock_sweep` attributes: `found_unlocked` = every device seen
unlocked/open (capped ones included), `lock_actions_sent` = the subset commanded this sweep, new
`retry_capped` = devices currently capped.

Not capped (one-shot actions, not retry loops): `_generate_lockdown_actions` called from the
unknown-person alert and the entry alert. They fire once per alert event.

## Constants (`const.py`, module constants, rung 1, review-gated)
- `SECURITY_LOCK_RETRY_CAP` = `3`. `0` disables the cap (unlimited retries, the old behaviour).
- `SECURITY_LOCK_RETRY_REARM_S` = `86400`. `0` = never re-arm on time (stay capped until the
  device is seen locked/closed).

## Live acceptance criteria
- Next time a lock/garage command fails to take: the HA logbook shows at most 3 `lock.lock`
  (or `cover.close_cover`) calls from URA for that device in the episode, then none until the
  device is seen locked/closed or 24 h pass.
- Exactly one NM row with "did not lock/close after 3 tries" for that episode.
- Log line `Periodic lock check: retry cap (3) reached, stopped commanding: <entity>` once.
- `sensor.ura_security_last_lock_sweep` shows the capped device in `found_unlocked` and
  `retry_capped`, and not in `lock_actions_sent`.
- After the device is seen locked/closed, a later failure gets a fresh 3 tries.

## Rebased onto v5.106.0 (overnight 2026-11-08)
Ships from `integ/overnight-2026-11-08` (develop c7e049ae + this fix + OPTIMIZER-META-NEVER-PAGES-1 +
ANOMALY-METRIC-DISPOSITION-1). It supersedes `integ/overnight-2026-11-04`, which no longer merges because v5.106.0
changed the same function. Behaviour with the never-auto-lock list: excluded locks skip the retry cap entirely (never
commanded, never counted, no cap notice). `sensor.ura_*_last_lock_sweep` gains a `retry_capped` attribute. Merge review:
docs/reviews/code-review/security_lock_retry_cap_merge_onto_v5106_review.md (SHIP, 2 LOWs fixed).
Extra live check after restart: the sweep sensor shows `retry_capped: []` and `excluded` lists the master bedroom lock
once you add it to the never-auto-lock list.

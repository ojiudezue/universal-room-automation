# Review: SECURITY-LOCK-SWEEP-RETRY-CAP-1 (Tier 1, framing A + safety posture)

Branch `origin/fix/security-lock-sweep-retry-cap` @ 25bc49bb. Base: develop eec11764 (merge-base verified). Diff is three-dot.
Not HVAC or presence work, so the state-of-play docs were not required.

## Verdict: FIX-REQUIRED (1 HIGH, 2 MEDIUM)

## Findings

### HIGH-1: observation mode burns the retry budget, then the door is silently never locked. Bug class #23 (observation-mode gating)
`security.py:1728/1750` calls `_lock_retry_allows()`, which increments `attempts` while the actions list is being *built*. `async_evaluate` (`security.py:831-837`) then drops **every** action when `observation_mode` is on, including the ServiceCallAction and the cap NotificationAction. The episode is still marked `attempts=3, notified=True`.
**Repro (legal config):** `switch.ura_security_observation_mode` = on (`switch.py:3471`), lock interval 30 min, front door left unlocked. After 3 sweeps (~90 min) the episode is capped and the cap notification has been suppressed. The operator turns observation mode off with the door still unlocked and `last_changed` unchanged. From then on the sweep never sends `lock.lock` and never notifies. The door stays unlocked with zero alerts until someone touches it or HA restarts.
The same accounting gap applies when CoordinatorManager conflict resolution drops the lock action (the code already notes this, ~1849): the attempt is counted but the command never went out.
**Fix:** skip counting when `self.observation_mode` is on (or count only actions that were actually emitted), and add a test that flips observation mode.

### MEDIUM-1: the cap likely never engages for the locks it targets (transient states re-arm the episode). Bug class #53-adjacent (gate computed but ineffective)
An episode is keyed on `last_changed` (`security.py:1697-1701`), and any non-`unlocked`/non-`open` observation pops it (`1726-1727`, `1748-1749`). A Z-Wave/Zigbee lock that tries and fails moves `unlocked→locking→unlocked` or `→jammed`. Garage covers move `open→closing→open`. Each of those transitions changes `last_changed`, so the next sweep sees a "fresh" episode with attempts=0. The cap therefore engages only for a lock that ignores the command outright, with no state movement. It does not engage for a lock that jams or bounces. Whether the Mar 8-12 audit lock (74 commands) bounced through `locking` is not established in the audit. Check recorder history for that entity before claiming the card is closed. This is not a safety problem, because it fails toward the old retry-forever behaviour. Treating `jammed` as "not unlocked" also means no lock command is sent for a jammed lock. That matches pre-change behaviour.
**Suggest:** key the episode on "last time the device was locked/closed" (reset only on `locked`/`closed`, not on any change), and treat `locking`/`jammed`/`closing`/`opening` as continuing the episode.

### MEDIUM-2: the sweep sensor and the "locked N doors" message now hide a capped unlocked door. Bug class #63 (one name, two concepts: "found unlocked" vs "commanded")
`found_unlocked` (`security.py:1852-1858`, which feeds `sensor.ura_security_last_lock_sweep` attrs, `sensor.py:7589`) is the same list as `lock_actions_sent`. A capped device is unlocked but appears in neither, so the sensor reports `found_unlocked: []` while the door is unlocked. Fix: track `found_unlocked` separately (every device seen unlocked/open) and keep `lock_actions_sent` as the commanded subset. The "locked N door(s)" message and the compliance `schedule_check` now covering only commanded devices is correct, because claiming to lock a door the code didn't command would be false.
`_lock_compliance` / `get_compliance_summary` (`2533-2541`) are **unaffected**: they still record the raw `state.state` for every device, so a capped unlocked door counts as non-compliant. That holds.

### LOW-1: no periodic re-arm. Safety posture
Once capped, a stuck-unlocked door with an unchanged `last_changed` gets one MEDIUM notification and then silence until a state change or restart. Attribute-only updates don't change `last_changed`, so they correctly don't re-arm. A restart re-arms by design, because the episodes dict is in memory. Re-arming once per 24 h is cheap: store `started_at` in the episode and reset when `now - started_at > 86400`, about 4 lines plus one test. I recommend it for a security device. A lock that was fixed physically without a state change is the case it covers.

## Cleared
- **Lockdown path uncapped:** `_generate_lockdown_actions` (`1648-1678`) does not touch `_lock_retry_episodes`. Arming/away/intrusion lockdown is unaffected.
- **Unavailable handling unchanged:** `continue` happens before the cap logic (`1722-1724`, `1744-1746`). Test `test_unavailable_not_counted_as_failure` covers it.
- **Cap=0 kill switch:** `SECURITY_LOCK_RETRY_CAP > 0` guard at `1702`. Covered.
- **Tests drive the real `_evaluate_lock_check`.** The sys.modules save/purge/restore at import (test file lines 24-30) leaves the global module table as it was, so it does not pollute other files. It does create a private second copy of the package, which is why the action classes are taken from `security_mod`. Acceptable.

## Test run + mutation
- `pytest quality/tests/test_security_lock_retry_cap.py`: 6 passed.
- Mutation `if SECURITY_LOCK_RETRY_CAP > 0 and ep["attempts"] >= CAP` changed to `if False and ...` (pycache cleared, PYTHONDONTWRITEBYTECODE=1): **5 failed, 1 passed** (cap-0 test, expected). Source restored; `git status` clean.
- No test covers observation mode (HIGH-1) or transient `locking`/`closing` states (MEDIUM-1).

## Must-fix
1. HIGH-1: don't count attempts when actions are suppressed by observation mode, and add a test.
2. MEDIUM-2: keep `found_unlocked` as "seen unlocked" separate from `lock_actions_sent`.
3. MEDIUM-1 (recommended): episode keyed on last locked/closed, with transient states continuing the episode. Without it the card's goal is likely unmet for jamming locks.
4. LOW-1 (recommended, cheap): 24 h re-arm.

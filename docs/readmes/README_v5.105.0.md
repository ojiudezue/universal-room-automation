# v5.105.0 — Garage remote lockout: SC lock regime (Phase 1)

**Card:** GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 (Phase 1). **Tier:** 2, elevated to three framing-disjoint code
reviews. **Plan:** `docs/planning/PLANNING_sc_garage_remote_lockout.md` rev 5 + Q-G1, after two plan reviews
and a delta review. **Code reviews:** `docs/reviews/code-review/sc_garage_lockout_p1_review_{A,B,C}.md`.

## Why
Each garage opener has a remote lockout (`lock.konnected_f0f5bd523b00_lock`, Garage A;
`lock.ratgdov25i_dbfe2a_lock_remotes`, Garage B). It stops car remotes and the outside keypad from opening the
door while the wall button and HA still work. The operator wants it on at night and on vacation, so the keypad
cannot be guessed or bypassed. Family must never be locked out when they come home, including on 3 AM
red-eyes. SC had no locking concept separate from alarm arming.

## What's new
- **Arming and locks are split.** Arming means the alarm only. A new lock regime inside SC
  (`domain_coordinators/security_lock_regime.py`) owns the garage lockouts. It runs whether or not the alarm is
  armed, and the arming path is unchanged byte for byte.
- **Engage:** the house goes to SLEEP or VACATION, or to GUEST during sleep hours (behind its own toggle,
  default ON). AWAY never engages.
- **Release:**
  - When the house wakes or goes HOME_* (this undoes only an engage the regime itself made).
  - At the morning backstop (the sleep end hour + 60 min). A vacation engage is held until a resident arrives.
  - On any resident arrival. Arrival means the person goes to `home` after really being away for 15 min or more,
    a geofence/BLE/face arrival signal after a real absence, a proximity crossing inside the radius, or the
    approach zone. A release also undoes a manual lock (the dashboard tile, "Lock all").
  - On a fire/smoke/CO hazard, on the kill switch going ON→OFF, and on SC being turned off.
- **Re-engage:** a single timer re-engages after a release, and only while it is still night, both doors are
  closed, and every released resident is home or back beyond the radius. It gives up after an hour.
- **Fail-safes are release-biased:**
  - Releases bypass observation mode and the manager batch.
  - A restart never engages.
  - An arrival during a restart counts.
  - An unlock that doesn't take is read back at 20 s, retried once, and then sent as a HIGH notification.
  - A reload waits up to 5 s for an in-flight unlock to finish.
- **Optimizer cannot open a garage.** It is blocked inside the optimizer's own safety denylist and also by
  SC's veto.
- **The resident list is live.** It is every `person.*` minus an exclusion list. Adds and removals take effect
  at once, and the list persists across restarts.
- **Lockouts are never swept.** They are a separate list, and the options validator rejects any overlap with
  the SC lock list.

## Knobs
| Knob | Default | Rung |
|---|---|---|
| `switch.ura_security_coordinator_garage_lockout` (feature + kill switch) | **OFF at ship** | 3 |
| Guest-night engage toggle | ON | 3 |
| Morning backstop offset, re-engage delay, proximity radius | 60 min / 15 min / 1500 m | 3 |
| Excluded persons, lockout entities, distance sensors, approach zone | options flow | 2 |

## Operator actions before enabling
1. **Physical test, per door:** with the lockout ON, try the outside keypad and an HA-app open. The keypad must
   NOT open the door; HA should.
2. Add `person.wall_kiosk` to the excluded persons.
3. Optional: add both garage covers to the optimizer safety deny list (config-only belt to the code block).
4. Turn on `switch.ura_security_coordinator_garage_lockout`.

## Known behaviour and limits
- Jaya and Ziri have no GPS tracker, so they get no proximity release and are released on arrival instead.
- A manual lockout is released by an arriving resident or the kill switch, never by a house-state edge alone.
- If HA is down at night, there is no release. Open from the wall button.
- An SC disable with both openers offline can add about 20 s to that reload.
- A HOME_* replay in the first 120 s after a night restart releases the lockouts until the next SLEEP edge.

## Tests
`test_sc_garage_lockout.py`, `test_sc_garage_lockout_review_c.py`, `test_sc_garage_lockout_real_ha.py`
(real HA timers/trackers), and the optimizer/options tests. 116/116 source-mutation drills go red. The full
suite has no new failing names against develop.

## Live validation (after restart)
- Integration loads, and the lockout switch and its knobs exist with the feature OFF.
- Both lockouts are untouched while the feature is OFF (no `lock.*` calls in the logbook).
- After the operator enables it, tonight's SLEEP gives both lockouts `locked` with trigger
  `house_state:sleep`, and the morning gives `unlocked` with trigger waking or backstop.
- The armed-state sensor attributes show the regime state.
- Core log has no `security_lock_regime` errors after boot.

## Validated 2026-11-07 (post-restart, feature OFF)
| Criterion | Result | Evidence |
|---|---|---|
| Integration loads, lockout switch exists, OFF | PASS | `switch.ura_security_coordinator_garage_lockout` = off |
| Lockouts untouched while OFF | PASS | both `lock.*_lock` / `_lock_remotes` = unlocked; last_changed = boot re-registration only |
| No `security_lock_regime` errors after boot | PASS | system_log: URA entries are pre-existing boot warnings only |
| SLEEP engage / morning release | PENDING | needs operator to enable the switch after the keypad test |

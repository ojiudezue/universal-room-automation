# v5.106.0 — SC "Never auto-lock" list + Away Lock

**Cards:** SC-LOCK-SWEEP-EXCLUDE-1, SC-LOCK-REGIME-DOOR-LOCKS-1. **Tier:** 2, elevated to three framing-disjoint
code reviews (it changes the v5.105.0 lock regime's person handling and switch-off routing).
**Plan:** `docs/planning/PLANNING_sc_lock_exclude_and_door_regime.md` rev 3, after plan review 1.
**Reviews:** `docs/reviews/code-review/sc_lock_exclude_review_{A,B,C}.md`.

## Why
Every lock should be registered in SC, but an interior lock (the master bedroom lock, in passage mode) must not
be swept: sweeping it only drains its battery. Lockdown should focus on egress doors. The operator locks the
bedroom by hand when Oji and Ezinne are both out; this automates that, behind a knob.

## What's new
- **"Never auto-lock these"** (options flow, subset of the SC lock list). Excluded locks are still shown in
  `diag doors`, the dashboard and the offline-lock notice, but the periodic sweep, security lockdown and the
  garage-lockout engage never lock them. A fire/smoke/CO hazard still unlocks them. Compliance, the dashboard
  aggregator and the optimizer's security-posture check ignore an excluded lock being unlocked.
- **Away Lock** (inside the SC lock regime). Locks the chosen excluded locks after every chosen person has read
  `not_home` for 5 minutes (named zones like work do not count). It unlocks only locks it locked itself, when any
  chosen person reads `home` (including at boot and after a short trip), on a hazard, when its switch goes off,
  or when SC is disabled. One attempt per outing; if the lock doesn't take (passage mode still on), one LOW
  notice and no ownership. Ownership, away times and the outing marker persist across restarts.
- **Form layout:** SC lock list, never-auto-lock, Away Lock locks/persons, then the four garage lockout fields
  sit together. The distance-sensor picker is limited to proximity distance sensors.

## Knobs
| Knob | Default | Rung |
|---|---|---|
| `switch.ura_security_coordinator_away_lock` (feature + kill switch) | **OFF at ship** | 3 |
| Never auto-lock list, Away Lock locks, Away Lock persons | options flow | 2 |
| `SECURITY_AWAY_LOCK_ENGAGE_DWELL_S` | 300 s | 1 (GPS-flap guard on an actuation; change by review) |

## Operator actions after deploy
1. Add `lock.master_bedroom_lock` back to the SC lock list and tick it in "Never auto-lock these".
2. Set Away Lock locks = master bedroom lock, persons = Oji, Ezinne.
3. Turn passage mode off by hand when you want it armed, then turn on `switch.ura_security_coordinator_away_lock`.

## Known limits
- HA has no passage-mode control on this lock; with passage mode on, the lock command doesn't take.
- Turning the switch on while everyone is already out engages on the next person state update, not instantly.
- Editing the persons list live is re-evaluated on the next person state change.
- The sweep change is written against develop; SECURITY-LOCK-SWEEP-RETRY-CAP-1 must rebase onto it.

## Tests
`test_sc_lock_exclude.py`, `test_sc_lock_exclude_options.py`, `test_sc_away_lock.py`; garage switch-off path
proven byte-identical. Review C drilled 166 single-site mutations; every GREEN site now has a RED test. Full
suite name-diff vs develop: 0 new, 0 gone. Three files that fail in isolation fail identically on develop.

## Live validation (after restart)
- Integration loads; `switch.ura_security_coordinator_away_lock` exists and is OFF; garage lockout switch unchanged.
- Options form shows the new fields together; distance picker lists only the `madronehaos_*_distance` sensors.
- No lock calls on `lock.master_bedroom_lock` while the switch is OFF; no `security_lock_regime` errors after boot.

## Validated 2026-11-08 (post-restart 08:24 CST, Away Lock OFF)
| Criterion | Result | Evidence |
|---|---|---|
| Integration loads; Away Lock switch exists, OFF; garage lockout unchanged | PASS | `switch.ura_security_coordinator_away_lock` = off, `switch.ura_security_coordinator_garage_lockout` = off (both last_changed = boot 14:24:39Z) |
| Form fields grouped | PASS | `coordinator_security` step order: lock list, never-auto-lock, Away Lock locks, Away Lock persons, then lockout entities, excluded persons, distance sensors, approach zone (flow opened and aborted, not saved) |
| Distance picker filtered | PASS | selector filter `integration: proximity, domain: sensor, device_class: distance`; defaults are the `sensor.madronehaos_*_distance` sensors |
| No lock calls while OFF | PASS | logbook since 14:20Z empty for `lock.master_bedroom_lock` and both garage lockouts; last_changed = restore at boot |
| No `security_lock_regime` errors after boot | PASS | system_log (current boot): no entries for `security_lock_regime` or the security coordinator; URA entries are the known boot warnings. Raw journald was not readable this run. |
| Away Lock engage/release | PENDING | needs the operator setup (bedroom lock in the list + excluded, persons set, passage mode off, switch on) |

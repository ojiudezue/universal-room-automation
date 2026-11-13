# Audit: garage hallway lock revert + perimeter D3/D5 gates off (2026-11-12, read-only)
Run 2026-11-12 ~22:00 CST (date output "CST"). All times local (UTC-6).

## Q1. Why does lock.garage_hallway_doorlock_kwikset916_zwave_garagehallway revert to unlocked?
ANSWER: URA's security periodic lock check is the only commander (hourly `lock.lock`); the lock itself then reports
`unlocked` ~6-7 s later with no HA context. No HA automation, no person, no other URA code path unlocks it.
Most likely cause is the lock's own battery/actuator failing (Z-Wave alarm_type 169 fires at each relock; replace_battery_now = on).
Mechanism of the 7 s revert is NOT directly proven (no Z-Wave JS log access; docker/journal denied to ssh user).

Evidence
- Recorder (ssh ha sqlite3 -readonly /config/home-assistant_v2.db), 58 state rows in 7 d, 0 with context_user_id, 0 with
  context_parent_id. Pairs: 11-12 17:52:23 locked -> 17:52:30 unlocked; 16:52:24 -> 16:52:30; 18:52:24 -> 18:52:30; 15:49:36 -> 15:49:43; 14:49:36 -> 14:49:43;
  11-11 20:24:48 -> 20:24:55; 21:24:48 -> 21:24:55; 22:24:48 -> 22:24:55; and so on. 29 `unlocked` rows since 11-06.
  Latest: unlocked 11-12 21:11:29 and 21:56:15 (no preceding locked row, no context user = lock-originated report, e.g. keypad/manual/firmware; not attributable).
- Commander: decision_log (URA DB) service_call rows "Periodic lock check: locking lock.garage_hallway_..." at exactly the :23/:24/:36 timestamps above
  (e.g. 2026-11-12 17:52:23). Code: domain_coordinators/security.py:1830-1865 `_evaluate_lock_check` emits ServiceCallAction lock.lock when state == "unlocked",
  bounded by `_lock_retry_allows` (security.py:~1790-1815, SECURITY_LOCK_RETRY_CAP). The lock is in `security_lock_entities` (PLANNING_sc_lock_exclude_and_door_regime.md:67; PLANNING_sc_garage_remote_lockout.md:488).
- Other URA unlock paths checked: security.py:2335 (`lock.unlock` only on critical smoke/fire/CO hazard, gated by CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS) and
  security_lock_regime.py:778 (garage-remote-lockout release / hazard). Neither fired at these times (no hazard rows; regime scopes garage covers/lockouts). Not the cause.
- HA automations: grep -n lock /config/automations.yaml shows only "Front Door - Auto-Relock (test)" (lock.doorlock_kwikset_zwave_frontentry, line ~662-711). Nothing references the garage hallway lock.
- Lock hardware signals: sensor ..._alarm_type = 169, alarm_level = 1 at 17:52:24 and 11-11 20:11:50, 20:24:48 (i.e. 1 s after each relock, before the revert).
  Community mapping (openHAB forum, Kwikset 914 table; not Kwikset-official, unverified for 916): 169 = "Battery too low to operate lock"
  (https://community.openhab.org/t/kwikset-916-door-lock-find-out-alarm-type/99021/2). binary_sensor ..._replace_battery_now = on (every refresh 11-10 23:06 -> 11-12 21:56),
  replace_battery_soon = off, while battery_level reads 90.0 (inconsistent; stale/clamped). lock_jammed = off throughout. Door contact (openclose_aquara_zigbee_garagehallway_contact) had no change at the 17:52 relock (closed), so not a "door open" refusal.
- Contradiction to note: lock_jammed off + battery 90% argue against failure-to-latch; alarm 169 + replace_battery_now argue for a weak-battery actuator that retracts after the motor stalls. Falsifier: swap batteries; if hourly relocks then hold, battery is it.
  If not, suspect Kwikset auto-relock/RF settings or a physical bolt misalignment.

Fix (proposed, not applied)
1. Operator: replace the lock's batteries now (alarm 169 + replace_battery_now on). Cheapest discriminator; zero code (Config-First).
2. After swap, if revert persists: check bolt alignment/strike; ping node (button.doorlock_kwikset916_zwave_garagehallway_ping) and read Z-Wave JS log for the 17:52:23-30 window.
3. Code follow-ups (carded as LOCK-REVERT-LOOP-1 in the broken-promises audit #4): make retry-cap reach the operator, not an audit row only; surface replace_battery_now on the lock regime.
Unknown: the cause of the 21:11:29 and 21:56:15 unlocks (no HA-side initiator found; physical/keypad not excluded).

## Q2. Why are perimeter D3/D5 FP gates off?
Source: docs/planning/AUDIT_broken_promises_2026_11_12.md item 6 (row #5 in file) -> README_v5.107.0.md:23-26,56.
Recorded reason: shadow-first by design, to collect evidence and then turn on by knob; not an operator prohibition, not a risk ruling.
- README_v5.107.0.md: "Every new gate can only LOWER an alert to LOW. None stops a dispatch. Each records its decision (also when off, as a shadow)...";
  D3 "off (shadow)"; D5 "off (shadow + learning)"; "Gates D3/D5/D6 stay off; turning them on is a later knob turn read off the shadow data."
- PLANNING_perimeter_fp_build_2026_11.md D3 (line ~299-300): "It is cheap ... and ships off in shadow, so it stays. The shadow `would_demote` count decides whether it is ever enforced."
  Also states D3 marginal benefit is small once D1 zone sensors are on. D5 (line ~353): "default off ... The operator turns it on for this house after D5a." Operator approved all phases 2026-11-08 (plan line 11).
- Invariant INV-FP-DEMOTE-ONLY / INV-FP-FAIL-OPEN (plan 119-137): gates only lower to LOW, never block dispatch, never demote on absent evidence.
- D5a probe (README "Probe results", 2026-11-08 19:12): 8 s settle is below most cameras' p90 lag (4-46 s); "retune before enforcing D5". H6: LOW alerts are pushed nowhere today (all channel floors HIGH+), so demote == silence.
Knobs (const.py:2627-2640): CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE default False, PERIMETER_ZONE_AGREEMENT_MAX_AGE_S=20; CONF_PERIMETER_SINGLE_SOURCE_DEMOTE default False; thresholds PERIMETER_SS_MIN_SAMPLES / PERIMETER_SS_MIN_AGREEMENT (0.6 over >=20 samples per README).
Live (HA API, 2026-11-12 22:01): switch.ura_perimeter_zone_agreement_demote off, switch.ura_perimeter_single_source_demote off, select.ura_perimeter_vlm_gate off (all last_changed 11-12 21:56:44 = restart).

Producer / consumer finding (the real issue): the shadow data the gates were meant to be judged on is EMPTY.
- sensor.ura_security_coordinator_outside_open_tracks_diagnostic attributes (live): gate_decisions_by_camera = {}, zone_map = {}, dual_role_cameras = [].
  zone_map {} means D1 (perimeter_zone_sensors) was never configured (config-entries grep found no such key), so D3 has no mapped zone and can never evaluate or shadow.
  The plan's "Config at the deploy restart" step 1 (7 property-zone sensors) appears not applied. (Counter may also reset at restart; last restart 21:56, so {} is weak alone, but zone_map {} is structural.)
- D5 learning IS running: agreement_by_camera g5_bullet 0.683 (41 samples), rear_ptz 0.419 (31), front_side_ptz 1.0 (4), utilities_ptz (10). Only g5_bullet clears 0.6/20; rear_ptz does not.
  So D5 would reach at most g5_bullet today.
- Consumers: perimeter_alert.py:4548-4559 (diagnostic), :5245 (read decision). Gates only alter severity; LOW is silent on every channel.
Counts (notification_log, hazard_type='exterior_person', 90 d window but rows exist only from 2026-10-14, i.e. ~30 d; row = per recipient audit incl. [ACK]):
CRITICAL 2,295; HIGH 1,754; MEDIUM 34; LOW 10. Title "Perimeter Alert - Person Detected" 2,270 CRITICAL.
Share the gates would have suppressed: UNKNOWN/unmeasured. gate_decisions_by_camera is empty and not persisted, so no would_demote count exists anywhere.
Only proxy: D4a burst replay 30 d: 584 of 1,707 would demote (34%), 30-snapshot sample 0 person-on-property (README, convenience sample); that is D4, not D3/D5.
Falsifier for "gates are safe to turn on": gate_decisions_by_camera would_demote rows with a real person confirmed. Cannot be run today.

Recommendation: do not flip the switches blind. Step 1 apply D1 zone sensors (config), step 2 persist/export gate shadow counts, step 3 dispose with a date.
Card: PERIMETER-FP-GATES-DISPOSE-1 (already on audit). Add D1-never-configured as its precondition.

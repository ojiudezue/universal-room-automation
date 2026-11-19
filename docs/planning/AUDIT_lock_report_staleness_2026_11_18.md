# AUDIT: lock report staleness (card SECURITY-LOCK-STALE-STATE-1)

Probed 2026-11-18 23:51-00:20 CST, read-only. Scripts in `.claude/tmp/lock*_probe.py`. Recorder `/config/home-assistant_v2.db`, URA DB `universal_room_automation.db`.
Caveat: the recorder only holds states from 2026-11-11 04:12 (oldest row), so "30 days" is really ~8 days. HA restarted 2026-11-18 23:04 CST (lock states `last_changed` 05:04 UTC).

## Locks in scope (registry-resolved, core.config_entries / core.entity_registry)
- security_lock_entities: `lock.doorlock_kwikset_zwave_frontentry` (zwave_js node 3), `lock.garage_hallway_doorlock_kwikset916_zwave_garagehallway` (zwave_js node 10, device a09b8d29...), `lock.master_bedroom_lock` (philips_home_access).
- security_away_lock_entities: `lock.master_bedroom_lock`. security_lock_sweep_exclude: `lock.master_bedroom_lock` (so it is on the offline notice only, never relocked).
- Door contacts from the registry: each lock's own device carries a zwave/Philips "door" binary_sensor (same radio, NOT independent). The ELK zones (`binary_sensor.elkm1_front_door`, `elkm1_garage_p_hallway`) are independent, but which ELK zone is the garage hallway door is unknown from the registry (the name "Garage\P Hallway" is not proof); `elkm1_garage_p_hallway` has 0 recorder rows. Independent activity evidence used instead: `person_entry_exit_events` rows on garage cameras.

## Q1. State-row gaps (recorder, 11-11 to 11-18)
| lock | rows | p50 | p90 | max | >6h | >24h |
|---|---|---|---|---|---|---|
| front | 44 | 2.0h | 16.3h | 25.9h (11-17 15:06 to 11-18 17:01) | 8 | 1 |
| garage hallway | 121 | 0.7h | 2.5h | 23.8h (11-17 15:06 to 11-18 14:51) | 8 | 0 |
| master bedroom | 34 | 3.1h | 17.3h | 31.9h (11-17 15:07 to 11-18 23:04) | 9 | 1 |

Many rows are restart "restore" rows, not lock reports (shared timestamps across all three locks: 11-11 19:24, 11-13 18:51, 11-17 15:06). Rows therefore overstate liveness.
Activity during the dead window: garage camera egress events (`person_entry_exit_events`, camera `sensor/binary_sensor.garage_a_*`) 11-16: 14, 11-17: 2 (plus doorbell/entry events), 11-18: 10. The garage lock had no real report between its last sweep-lock ack (11-16 07:37 CST, state locked, compliance row 11-16 13:39 UTC verified) and 11-18 14:51, so >24h (about 55h) with people coming and going. Its own door sensor stalled in step (restore rows only). Healthy front/master gaps >24h occurred overnight / low traffic.
Correction to the card: the lock did report until 11-16 07:37 CST (the sweep's relock took), not 11-15 20:42. The 11-15 20:41:55 row is an hourly last_reported refresh. After 11-16 07:37 only restart-restore rows exist (11-16 09:05/09:10, 11-17 15:01/15:06). On the ping at 11-18 14:51:59 the lock reported `unlocked` (so the physical state was unlocked), then `unavailable` 14:53; node_status went `dead` 14:52.

## Q2. Did anything notice 11-16 to 11-18?
- No anomaly_log rows for locks (only 2 unrelated `stuck_signal` rows, 2026-09-17, mmwave).
- notification_log: no sweep notice about the garage lock between 11-16 13:37 UTC (relock) and 11-18 21:41 UTC ("1 device(s) offline: ...garagehallway"), which is the first notice after it went unavailable. Nothing about silence. Channel `digest`, bucket `digest_queued`, delivered NULL: it is queued to a digest, not an immediate page.
- Sweep sensor `sensor.ura_security_coordinator_security_last_lock_sweep` is currently `unknown`, `no_sweep_yet` (restart 23:04 CST). Earlier history attributes not recoverable from recorder in this probe.
- Earlier same lock: retry-cap notices 11-13 21:44 and 11-14 04:51 UTC (a different failure, command not taking).

## Q3. How the sweep treats states (security.py)
- `_evaluate_lock_check` 1816. Per lock (1836-1866): state None / `unavailable` / `unknown` -> appended to `unavailable`, compliance "unavailable", `continue` (1838-1842). `locked` -> clears retry episode, no action (1850-1851). `unlocked` -> `lock.lock` ServiceCallAction (1852-1866). No age check anywhere: a stale restored `locked` is trusted (the card's defect). Same for garage covers 1868-1891.
- Unavailable: log warning (1894) and a NotificationAction, channel "security", MEDIUM, deduped per entity by `CONF_LOCK_UNAVAILABLE_DEDUP_S` default 86400s (1903-1933; const.py:5993); the dedup map is in memory (security.py:623), so a restart resets it. Excluded locks still get the offline notice (1839).
- Today: the garage lock is `unavailable` (live 11-19 05:05 UTC, restored: true). The next hourly sweep will notice and queue one offline notice to the digest (not an immediate page) because the dedup map was reset at the 23:04 restart. It does not command anything. `security_lock_regime.py` ignores unavailable lockout entities (release skipped with a one-time warning, ~2046-2052) and lists `_UNREAL_STATES` (107); no staleness handling there either (grep for stale/last_reported shows only person-source staleness).

## Q4. Recommendation
- Do not use state-row age alone: healthy locks reach 25.9h to 31.9h (overnight and restart-polluted), so a 24h knob false-pages the front and master locks. last_reported (live `last_reported` attr; recorder `last_reported_ts`) does update without a state change but only sporadically (garage rows show e.g. 11-15 15:47 locked, lr 18:14; front lock: 26 of 44 rows have null lr and 11-17 15:06 to 11-18 17:01 shows none), so it is a weak freshness signal.
- Better signal: zwave_js node `last_seen` sensor. Node 3 (healthy) updates about hourly (325 rows/8d, p50 0.1h, p90 1.1h, max 17.5h). The garage node's last_seen entity does not exist in the live state machine (`Entity not found`; registry lists it, so probably disabled): enabling it, or reading node status/`last_seen` from the zwave_js node, is needed. Unknown whether Kwikset 916 `last_seen` updates when it silently stops (not testable now: it is dead).
- Proposed knob `security_lock_silent_hours` (module-constant rung or Number): N = 12h of no report AND no node last_seen, tightened to 3h if any door-crossing evidence (garage/front camera egress event, ELK contact) occurred after the lock's last report. Rationale: 12h sits under the garage's measured 17.3h overnight restart gaps only because overnight rows are restore rows, so gate on (last_reported, last_changed, node last_seen) max, not rows. Activity-gating is what makes a short N safe; unconditional N should be >= 24h (or 36h, above the 31.9h max). On breach: page immediately (not digest), and issue a `zwave_js.refresh_value`/ping before trusting `locked`.
- Falsifier not run: whether node 3 last_seen keeps updating across a multi-day window with the recorder only holding 8 days; and whether Kwikset last_seen updates on non-state traffic is unmeasured for node 10.

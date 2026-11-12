# AUDIT: BLE-arrival D0 probe (EGRESS-BLE-ARRIVAL-LATENCY-1)

Run Thu 2026-11-12 14:05-14:30 CST by ura-prober. Read-only. Executes D0 of `PLANNING_ble_seen_at_home_arrival.md` (read in full). I did NOT re-read the presence/identity STATE_OF_PLAY docs for this probe; claims below rest on the recorder/DB and the cited code lines only.

## Data windows (say-so)
- Recorder `/config/home-assistant_v2.db` states: 2026-11-05 04:12 to 2026-11-12 14:05 CST (about 7.4 days, NOT 14). Times below are CST (UTC-6).
- `ura_activity_log`: 2026-10-13 to 2026-11-12 (20,728 rows). Only the HVAC handler writes `pre_arrival` rows (333 total), AFTER its source filter and `_pre_arrival_spent` dedup (hvac.py:7238-7246 per the plan). So "no row" does not prove the signal was not dispatched; the signal itself is not logged anywhere I could query.
- Person edge = `person.*` not_home -> home in recorder `states` (`last_updated_ts`). Row-to-edge match window: -5 s to +120 s, first row by time.

## 1. Arrival edge vs first URA pre_arrival row

| Person | person not_home->home edges | first row `geofence` within 1 s | geofence but late | first row `ble` | no row |
|---|---|---|---|---|---|
| ezinne | 16 | 16 | 0 | 0 | 0 |
| jaya | 9 | 9 | 0 | 0 | 0 |
| ziri | 7 | 7 | 0 | 0 | 0 |
| oji_udezue | 86 | 79 | 3 | 1 | 3 |
| total | 118 | 111 (94%) | 3 | 1 | 3 |

(Also: oji 11-05 04:22 and jaya 11-05 06:21 have `None -> home` first-state edges; excluded.)

- For ezinne/jaya/ziri, 32 of 32 resident arrivals: first row is `source=geofence` at lag 0.00 s (max 0.9 s for a trailing `ble` row on ziri). The `ble` row follows 0.9-60 s later (ezinne 7-60 s, jaya 2.5-35 s, ziri 0.9-32 s). This is consistent with the plan's claim (D0 gate: confirm).
- Oji exceptions (7), all in his stream of sub-second blips (section 2):
  - 11-06 09:01:15.7 first row is `ble` +29.9 s (previous geofence row 26 s earlier; his person bounced).
  - geofence late: 11-07 08:26:36 (+41.8 s), 11-07 08:27:47 (+38.5 s), 11-09 01:42:25 (+119.4 s). These match an earlier row, not the edge, so the edge itself had no row.
  - no row: 11-06 21:44:49, 11-07 08:30:40, 11-07 16:20:18.
  - Likely explanation is the HVAC repeat-arrival dedup (`_pre_arrival_spent`) swallowing repeats within a short window, but I did not verify that. Unknown.
- Caveat on the plan's premise ("person edge is BLE-driven"): the person's `source` attribute at the home edge, counted over all edges:
  - ezinne: `zinny_s_iphone_15` (source_type **gps**, the app tracker) 13, `ezinne_iphone` (bluetooth_le) 3. So 13/16 of Ezinne's arrivals were GPS/app-driven, not BLE.
  - jaya: `private_ble_device_249050` 7, `iphone_jaya_bermuda_tracker` 2 (all BLE).
  - ziri: `ziri_iphone` (bluetooth_le) 7.
  - oji: `okosisipadmini6_2` 78 (GPS iPad, see section 2), `phalanxiphone15promaxcflare` 6 (GPS phone), `private_ble_device_8ce182` 2 (BLE).
  The conclusion that a geofence row appears at t0 holds regardless of driver; but "geofence row at t0 == BLE-seen arrival" is only true for Jaya, Ziri and 3 of Ezinne's 16.

## 2. Home flips that revert within 10 min

Person level (person.* home -> not_home within 600 s of its edge):

| Person | edges | reverted <=10 min | of which <1 s |
|---|---|---|---|
| oji_udezue | 86 | 78 (observed in his 87 home spells: 77 under 1 s, 1 of 1.2 s; the rest 7.5 s to 460 s) | 77 |
| ezinne | 16 | 0 | 0 |
| jaya | 9 | 0 | 0 |
| ziri | 7 | 0 | 0 |

Oji's 78 reverts are NOT real BLE hearings. Mechanism (observed, example 11-05 18:08:39.580 -> .619, 39 ms):
- `person.oji_udezue` goes `home` with `source=device_tracker.okosisipadmini6_2` (his iPad mini, source_type gps, last `home` state stale), then `not_home` with `source=device_tracker.phalanxiphone15promaxcflare` 39 ms later.
- Each time the phone tracker `phalanxiphone15promaxcflare` emits `unavailable` then `not_home` (e.g. 11-05 18:08:39). While it is `unavailable`, HA person falls back to the other tracker, which still reads `home`.
- Count of such blips: 77 under 1 s (plus 1 of 1.2 s). Phone tracker state counts since 11-05: home 239, not_home 513, unavailable 281. iPad tracker: home 19, not_home 26, unavailable 14.
- Scanner/area: not applicable. In 78 of 78 no Bermuda/private-BLE tracker went home within the window as the driver; Bermuda area sensor `sensor.iphone_oji_area` has no rows in these windows. Street-facing scanner question: no data, nothing BLE drove these flips.
- Side effect: each blip dispatches `SIGNAL_PERSON_ARRIVING(source=geofence)` (observed as the lag-0 `geofence` row in section 1; HVAC pre-arrival rows, 79 of 86 Oji edges). These are false arrivals; his phone was at not_home (and he was away from about 11-09).
- Oji's other 8 edges: 6 driven by his phone tracker (GPS), 2 by `private_ble_device_8ce182` (BLE). Of the 87 home spells, 10 lasted 1.2-460 s; the BLE-driven cause for them was not separately attributed.

Tracker level (since 11-05), home spells under 1 s / 1 s-10 min:
- `zinny_s_iphone_15` (Ezinne app, gps): 32 `unavailable->home`, 15 `not_home->home`; 7 sub-second home blips, 8 home spells of 1 s-10 min. These are the app-tracker reconnect blips. They did NOT surface at person level because Ezinne's BLE trackers (`ezinne_iphone`, `ezinne_iphone_bermuda_tracker`) hold `home` / non-GPS precedence or the person was already home (inference; person.ezinne has zero reverts).
- `ezinne_iphone` / `ezinne_iphone_bermuda_tracker`: 2 sub-second blips each (both BLE), 0 spells 1 s-10 min.
- `private_ble_device_8ce182` (Oji BLE): 2 blips, 1 spell 1 s-10 min. `iphone_oji_bermuda_tracker`: 1 blip. `iphone_ziri_bermuda_tracker`: 1 blip. Jaya and Ziri's other BLE trackers: 0.
- None of these BLE-tracker blips reverted person.* within 10 min (person reverts = Oji's iPad-fallback only).

## 3. Lock regime on the short flips
- Code: `security_lock_regime.py:1097-1143` `_on_person_event`: a resident's not_home->home edge calls `_arrival_counts` (old value `not_home` is not in `_UNREAL_STATES`, so it returns True at :1138-1141 without applying the `_really_away` 15-min blip gate) and then `_release(...)`. So Oji's iPad-fallback blips WOULD call `_release` if lockouts were engaged and locked. The `_really_away` blip gate only applies to `unavailable/unknown` old states. (I read the code only; `kill_switch_on`/`_sc_alive` gates at :1344-1347 not evaluated.)
- Activity log: `ura_activity_log` has ZERO rows with `coordinator='security'` and none matching lock/lockout/release/unlock in the whole 30 days. The regime logs only when `written` (an entity was actually unlocked) is non-empty (:2328-2342), so no lockout/away lock release was written, ever, in this log.
- Lock history, 78 Oji blips, window edge-5 s to edge+duration+120 s, over `lock.konnected_f0f5bd523b00_lock`, `lock.ratgdov25i_dbfe2a_lock_remotes`, `lock.doorlock_kwikset_zwave_frontentry`, `lock.garage_hallway_doorlock_kwikset916_zwave_garagehallway`, `lock.master_bedroom_lock`: only two state changes, both `lock.master_bedroom_lock` after the 11-05 18:08:39 and 18:11:45 blips (unlocked 18:09:04; locking/unlocked 18:11:53-18:13:04). Not linked to the regime on evidence; `master_bedroom_lock` is not a garage or exterior lock by name, but I did not verify its membership in the regime's lockout/away config. The four garage/exterior locks did not change in any blip window.
- Net: no observed release of a garage lockout or away lock attributable to a short flip. Whether the regime was armed (lockout engaged) at those times is unknown, so "no release" does not prove the gate would have held.

## Findings for the card
1. INV-ARR-1 holds (94% overall; 100% for the three non-Oji residents, 32/32 at lag 0.00 s). D0 gate confirms: first trigger is `geofence`, not `ble`.
2. The plan's premise that geofence == BLE-seen is only partly true: Ezinne's arrivals are 13/16 app-GPS-driven.
3. New: Oji's 77-78 false arrivals since 11-05 (sub-second `home` blips from phone-tracker `unavailable` fallback to a stale GPS iPad tracker). Each dispatches `source=geofence` arrival; a possible card for a person-level arrival blip guard (min-hold) is outside this card.
4. No lock release was observed on any blip; the guard evidence is weak (regime `_arrival_counts` does not gate `not_home->home`).

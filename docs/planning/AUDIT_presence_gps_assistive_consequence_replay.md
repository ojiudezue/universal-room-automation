# AUDIT — Presence GPS-assistive: consequence replay (read-only)

**Run:** 2026-10-24 19:27 CDT. **Plan under test:** `docs/planning/PLANNING_presence_gps_assistive.md` Rev 3 (f96aaa0ed).
**Window:** recorder 2026-10-17 04:12 CDT to 2026-10-24 ~19:25 CDT (7.6 d). **Read first, completely:** the plan, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`.
**Method:** `ssh ha` read-only SQLite (HA recorder `home-assistant_v2.db`, URA `universal_room_automation.db`), 30 s replay grid, scripts in the session scratchpad (`rp2.py`..`rp15.py`). No HA or repo writes except this file.

---

## 0. Verdict (answer first)

1. **The replay changes the plan's premise.** The plan treats the 13 frozen-GPS segments as a departed Oji whom GPS wrongly held home. Interior-camera face recognition says otherwise: **about 728 of the 1,124 overrule-eligible minutes (65%) were Oji physically at home with both BLE trackers dark**, so GPS "home" was right and BLE was wrong. Only about 396 min (35%) were true departures (IV2 body, IV3, IV4, IV5, IV8, IV9 and the back half of IV7; IV numbers are defined in section 2). The plan's oracle question Q1 is answerable from the data and the answer is "mostly home". This includes **today**: Oji left through the garage at 08:39, was back in the Family Room at 08:42, and has been recognised on interior cameras 75 times since. His phone's BLE has been dark since 08:44 (Bermuda `area_last_seen = Garage A`). Under the new rule he would read AWAY from 08:45 to now while at home.
2. **Why it looked fine historically (section 5):** none of the person-state trust sites that the plan swaps was exercised in those minutes. Four of the seven are night-gated (zero overrule minutes in `home_night`/`sleep`/`waking`), one has no production caller, one feeds a display-only entity, and the daytime HVAC retreat does not consult person state at all (19 of 39 zone_1 `->away` retreats in the window were logged with Oji in `home_persons`). The house-AWAY path was held by a co-resident or by camera bodies. In the 4 intervals where every other resident was away and Oji really was away, the visible cost was a late or missed house AWAY.
3. **No unintended house-AWAY occurred in the replay**, but two near misses (IV10 and IV11 below) were saved only by other residents' face latches and by camera body counts, not by anything the rule guarantees.
4. **Unintended consequences the plan does not list (all replayed, section 4):**
   - **False GUEST arming** when Oji is home and BLE-silent, **made worse by the plan's own ADOPT at `camera_census.py:5884`**. Proxy replay: unidentified body at medium/high census confidence for 1,080 s (IV10), 2,641 s (IV11), 2,595 s (IV12) with the swap, against 1,080 / 1,411 / 0 s with the guard left raw. The gate arms at 300 s (`const.py:3953`).
   - **False pre-arrival signal on every BLE return**, with no 15-minute guard: the S3 away arm sets `_person_was_away` immediately (`person_coordinator.py:792`, `:873`); the 15-min test exists only on the LOST path (`:658`). Plan table row 15 is inaccurate for the overrule path. 2 of the 6 BLE-return arrivals in the window were false (Oji was home).
   - **`hvac_zones.zone_has_home_person` has no production caller** (repo-wide grep: only `quality/tests/test_zzz_hvac_conditioning_demand.py` and the definition). The plan's ADOPT row for it is a no-op.
5. **Opposite risk (section 6):** Oji: 12 overrule intervals, 1,124 min, 7 of them at-home false-away (above). Ezinne: **0** qualifying moments.

---

## 1. How the replay decides "overruled" (and the caveats)

Overrule(p, t) = URA location sensor reads `Home` (the forced-home stamp) AND `person.p == home` AND every one of p's BLE trackers is exactly `not_home` AND Bermuda Active Proxy Count has been numeric >= 30 continuously for >= 360 s (run start taken from the recorded sensor series) AND WiFi axis missing (sensor attribute `tracker_sources.wifi = MISSING` throughout). Evaluated for Oji and Ezinne (Jaya and Ziri have no non-BLE tracker, so the rule cannot act on them: it needs `person.state == home` with every BLE tracker `not_home`).

Without the arm gate the same replay finds 4 more episodes/segments that the latch correctly suppresses: 10-20 17:50 (2.5 min), 10-20 22:21 (5 min), 10-24 10:11-10:18 and 14:03-14:10 (restart latch; Oji was at home). The latch works as designed.

Caveats: (a) 30 s tick granularity; (b) "Oji at home" is inferred from Frigate face labels `Oji`/`Ojini` on interior cameras (family_room, master_hallway, playroom, staircase, stairs_top, upstairs_hall, foyer_fisheye), not from the operator; a mislabel to Jaya/Ziri would weaken single events but not 21 + 50 events across 6 cameras; (c) the census counterfactual uses `frigate_count` as the camera-body proxy (`unidentified' = max(0, frigate_count - |identified minus Oji|)`, mirroring `camera_census.py:2463/2500`); the true `camera_total` is richer, so treat the GUEST/alpha numbers as estimates; (d) house-AWAY alpha is replayed on its stated inputs (all trusted away, unidentified 0, face 0), ignoring alpha's debounce.

---

## 2. The 13 segments, mapped to overrule intervals, with ground truth

IV = overrule interval after the arm gate. Times CDT. "Others away" = Ezinne, Jaya, Ziri URA location all `Away` (minutes). "Ezinne home" = `person.ezinne == home` (minutes; she shares `zone_persons` with Oji in Entertainment and Master Suite, `core.config_entries` Zone Manager).

| Seg | Plan segment | IV | Overrule min | Ground truth (evidence) | House state during | Ezinne home / others away (min) |
|---|---|---|---|---|---|---|
| 1 | 10-19 09:37 8.5 m | IV1 | 8.5 | **HOME.** `family_room` face 09:40:27; no egress; last fix Study A, return fix Study A Closet 09:46 | home_day | 9 / 0 |
| 2 | 10-19 17:50 104 m | IV2 | 103 | **AWAY**, except ~15 min tail. Egress exit (face) 17:44:46; last fix Garage A; `front_door_aerial` face 19:19:18 then BLE fix 19:34 | home_day -> home_evening | 103 / 0 |
| 3 | 10-20 07:26 55.5 m | IV3 | 55 | **AWAY.** Egress exit (face) 07:19:33; 0 interior faces | home_day | 0 / 54 |
| 4 | 10-20 17:47 5.3 m | none | 0 | one BLE tracker `home` 57% and restart 17:52 (latched) | home_day | n/a |
| 5 | 10-20 22:21 5.0 m | none | 0 | restart 22:23 latch | home_day | n/a |
| 6 | 10-21 07:30 42 m | IV4 | 41 | **AWAY.** Egress exit (face) 07:23:57; 0 interior faces | home_day, AWAY at 08:12:09 | 0 / 40 |
| 7 | 10-22 09:17 8.5 m | IV5 | 4.5 | **AWAY.** Exit 09:11:58, entry 09:27:36 | home_day | 0 / 5 |
| 8 | 10-22 16:45 77 m | IV6 | 77 | **HOME.** 6 `family_room` faces 17:20-17:34 | home_day -> home_evening | 77 / 0 |
| 9 | 10-22 19:28 23.5 m | IV7 | 21.5 | **MIXED.** `family_room` faces 19:30:26 and 19:36:34 (home), GPS flips to Away at 19:52 | home_evening | 22 / 0 |
| 10 | 10-23 11:32 152 m | IV8 | 149.5 | **AWAY.** Exits 11:24:48 and 11:28:17; 0 interior faces | home_day | 0 / 149 |
| 11 | 10-23 17:33 45.5 m | IV9 | 43.5 | **AWAY.** 0 interior faces; GPS Away 18:18:34, house AWAY 18:18:50 | home_day -> home_evening | 0 / 42 |
| 12 | 10-24 08:45 85.6 m | IV10 | 85.5 | **HOME.** `master_hallway` 08:52, 10:04, `family_room` 10:07-10:10 (4 faces). Exit at 08:39 was to the garage and he was in the Family Room at 08:42 | home_day | 66 / 19 |
| 13 | 10-24 10:10 ongoing | IV11 + IV12 | 225.5 + 309.5 (ongoing) | **HOME.** 21 + 50 interior faces, doorbell entry 17:06 | home_day, home_evening | 180 / 45 and 310 / 0 |

Totals: 1,124 overrule min; home-truth about 728 (IV1 8.5, IV2 tail 15, IV6 77, IV7 first 7, IV10 85.5, IV11 225.5, IV12 309.5); away-truth about 396.

---

## 3. Per-site tables

Legend: **Actual** = what the site decided with Oji reading `home` (recorder/URA DB). **Counterfactual** = Oji `not_home`/away, reasoned from the cited code. "Changes?" = an observable outcome.

### 3.1 `aggregation.py:4455-4463` (sleep layer) feeding `ZoneAnyoneBinarySensor.is_on` via `presence.py:2121`

Evaluated only when `manager.house_state == "sleep"` (`aggregation.py:4430`), for zones Entertainment and Master Suite (persons Ezinne + Oji; Upstairs = Ziri + Jaya; Back Hallway and Outside none).

| Segments | Evaluated? | Actual | Counterfactual | Changes? |
|---|---|---|---|---|
| IV1-IV12 (all) | **No.** House state in every overrule minute was `home_day` or `home_evening` (house_state_log); 0 overrule minutes in `sleep` | n/a | n/a | No |
| Nights 10-17..10-24 | Yes, nightly 22:00-06:00 | Oji BLE present overnight (plan 5.2: 0 episodes >= 5 min, 23:00-06:00; confirmed 0 overrule minutes in sleep) | same | No |

### 3.2 `aggregation.py:4589-4596` (non-sleep layer 3) feeding the same entity

Evaluated when house state is home-like, zone rooms read unoccupied, and sensors quiet >= 300 s (`presence.py:196`). Only the sole-home-person case changes: Ezinne must be away too.

| Segments | Evaluated? | Actual | Counterfactual | Changes? |
|---|---|---|---|---|
| IV1, IV2, IV6, IV7, IV12 (Ezinne home throughout) | Yes if rooms quiet | Anyone ON (Ezinne home) | unchanged (Ezinne still home) | No |
| IV3, IV4, IV5, IV8, IV9 (Ezinne away 55/41/5/149/43 min, Oji truly away) | Yes if rooms quiet | Anyone held ON by the frozen Oji | Anyone drops to rooms-only | Yes, **more accurate** (display) |
| IV10 (20 min), IV11 (45 min) (Ezinne away, Oji **home**) | Yes if rooms quiet >= 300 s | Anyone ON | Anyone can read OFF during quiet spells with Oji present | Yes, **wrong** but display-only |

Consumers of `binary_sensor.zone_*_anyone`: only `.storage/lovelace.ura_v8` tiles (`grep` of `/config/.storage`); zero code references (`grep _anyone` over the integration returns only the entity itself and a comment) and zero hits in `automations.yaml`. **Outcome: display only.**

### 3.3 `hvac_zones.py:2655-2675` `zone_has_home_person`

| Segments | Evaluated? | Actual | Counterfactual | Changes? |
|---|---|---|---|---|
| All | **Never in production.** `grep -rn zone_has_home_person --include=*.py` finds the definition and `quality/tests/test_zzz_hvac_conditioning_demand.py` only. Test line 927-934 states the shared retreat helper must NOT consult it | n/a | n/a | No. Plan row is stale: nothing to adopt |

### 3.4 `hvac.py:3401-3410` night preset hold (and `hvac.py:3978-3986` log field)

Condition (`hvac.py:3398-3401`): `effective_preset == "away"` AND house in `FAN_TRUST_STATES` (`hvac_const.py:1067` = home_night, sleep, waking) AND zone not retreat-ok.

| Segments | Evaluated? | Actual | Counterfactual | Changes? |
|---|---|---|---|---|
| IV1-IV12 | **No.** 0 overrule minutes in FAN_TRUST states | The 2 zone_1 `->away` rows in FAN_TRUST states in the window (10-17 23:28, 10-18 23:18) had `home_persons = []` | n/a | No |
| Day retreats in the intervals | Condition false (house_state `home_day`/`home_evening`) | zone_1 `home->away reason=vacant_past_grace` at 07:27 (IV3), 07:31 (IV4), 11:35 (IV8), 09:29 (IV10, Oji home), 10:18, 11:01, 11:14, 12:15, 13:40 (IV11), 14:40, 17:23, 17:43, 18:27 (IV12) | identical: day retreat is room-driven (`conditioning_retreat_ok`, HVAC SoP 3.2), person-trust "dropped from the established path" (`hvac.py:3390-3395`) | No |
| `hvac.py:3978` `home_persons` | Evaluated on every S1 preset row | 19 of 39 zone_1 `->away` rows list `person.oji_udezue` in `home_persons` (raw) | would list only Ezinne or nobody | Activity-log text only (display) |

### 3.5 `hvac_fans.py:1525-1535` night vacancy hold

Condition: house in FAN_TRUST_STATES and (sleep or bedroom room_type).

| Segments | Evaluated? | Actual | Counterfactual | Changes? |
|---|---|---|---|---|
| IV1-IV12 | **No.** 0 overrule minutes in FAN_TRUST states | n/a | n/a | No |

### 3.6 `camera_census.py:5884-5895` stale-face latch guard

Runs for a face-recognised person inside `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (1800 s). Today it drops a face only when raw `person.state == not_home`. With the swap it also drops an overruled person.

| Segments | Oji face events in interval | Actual | Counterfactual (swap adopted) | Changes? |
|---|---|---|---|---|
| IV3, IV4, IV9 (true away) | 0 interior; Oji's last face age at the first alpha-eligible minute was 1,791 / 1,725 / 1,721 s | face expires within ~80 s anyway | guard drops it ~1-2 min sooner | Negligible (<= ~1.5 min earlier AWAY) |
| IV1, IV6, IV7 (home) | 1 / 6 / 2 faces | Oji stays identified by face | Oji dropped from `recognized`; his body becomes unidentified if cameras see him | Short runs (0 / 78 / 0 s): below the 300 s gate |
| IV10, IV11, IV12 (home, 4 / 24 / 54 faces) | faces continuous | identified stays 3 (BLE-forced) | **swap**: unidentified > 0 at medium/high for 1,080 / 2,641 / 2,595 s. **Left raw**: 1,080 / 1,411 / 0 s | **Yes: GUEST gate (300 s, `const.py:3953`) arms in IV10, IV11, IV12 with the swap; only IV10 and IV11 (shorter) without it.** Proxy estimate (caveat c) |

**Net:** across the window the swap bought at most ~1.5 min of earlier AWAY on 3 true departures and exposes at least one extra GUEST arming run (IV12, 43 min) on a verified at-home day.

### 3.7 `person_coordinator` location consumers (not a raw-state site; replayed because INV-1 changes them)

| Consumer | Evaluated? | Actual | Counterfactual | Changes? |
|---|---|---|---|---|
| Path alpha / nobody-home (`presence.py:1229`, `:1126`) | Every tick. Needs all trusted away + unidentified 0 + face 0 + cameras OK | House never went AWAY in an interval except IV4 08:12:09 and IV9 18:18:50 (both when GPS finally flipped Oji to Away) | Alpha-eligible minutes (others away, other-resident face latch clear, Oji removed from identified): **IV3 33 min (first 07:48), IV4 19 (first 07:53), IV9 24 (first 17:54), all true departures**. IV8: 0 (a persistent 1-body camera count, `frigate_count = 1`, keeps unidentified = 1). IV10, IV11 (Oji **home**, others away 19 / 45 min): **0** | **Benefit:** house AWAY 19 min earlier (IV4: 07:53 vs 08:12), 25 min earlier (IV9: 17:54 vs 18:18), and an AWAY that never happened (IV3: 33 min). **No false AWAY in the window.** IV10 saved by other residents' face latch (19 of 19 min); IV11 by face latch (23 of 45) and unidentified > 0 (22 of 45). Camera luck, not a guarantee |
| Guest gate (`presence.py:5965`) | Every census tick | n/a in actual (Oji counted identified) | See 3.6 | Yes (false GUEST risk) |
| Pre-arrival (`person_coordinator.py:601-638` -> `hvac.py:7052`, security expected-arrival) | At each BLE return | The S3 away arm never ran, so no arrival signal for Oji at any of these returns | Fires at the BLE return. IV2, IV3, IV5, IV8: true arrivals (benefit). **IV1 (8.5 min), IV6: false, Oji was home.** IV4/IV7/IV9 end by GPS, IV10-12 not by BLE | Yes. Historically `pre_arrival` rows are followed by `S12_pre_cool` writes on the person's zone (e.g. 10-18 23:56:47 zone_1, 10-20 18:42:04 zone_1), so the write is reachable. Today's eventual BLE return would be a 10+ h false arrival |
| `persons_home`, NM targeting, music following, transitions, location sensor | Continuous | Oji shown home | Oji shown away | Display / routing. Not traced beyond the plan's table |

---

## 4. Why it looked fine this long

1. **GPS usually reports the departure.** Plan card probe: 7 clean events, median ~30 s. Frozen-GPS episodes are the minority; of the 13 raw segments, 2 are restart artefacts (latched, segments 4 and 5) and the other 11 become 12 overrule intervals: 5 camera-confirmed at-home (IV1, IV6, IV10, IV11, IV12), 1 mixed (IV7) and 6 true departures (IV2, IV3, IV4, IV5, IV8, IV9).
2. **When GPS "won" and BLE was dark, GPS was usually right.** 65% of overrule minutes were Oji at home. The defect the plan fixes (a departed person held home) is real but is only ~35% of the minutes (IV2 body, IV3, IV4, IV5, IV8, IV9).
3. **Daytime HVAC never reads person state.** zone_1 retreated `home -> away` with Oji listed in `home_persons` 19 of 39 times. Person-trust survives only on the night gate (`hvac.py:3398-3401`, `hvac_fans.py:1520-1523`), which was never active in an overrule minute.
4. **Co-resident masking.** Ezinne shares zone_persons with Oji and was home for IV1, IV2, IV6, IV7, IV12 (and 66 and 180 min of IV10, IV11).
5. **Nobody-home and alpha need all residents gone and no unexplained bodies.** The forced-home Oji also "explains" camera bodies (IV8: `frigate_count = 1` for 2.5 h, identified = [Oji]); removing him makes that body unidentified.
6. **Where it did hurt, it was subtle:** IV3 (55 min, everyone gone), IV4 (+19 min) and IV9 (+25 min) delayed or missed a correct house AWAY. HVAC zone_1 still retreated by room vacancy at 07:27, 07:31 and 11:35, so nothing visible broke.

---

## 5. Opposite risk: new rule marks an app user away while home

**Ezinne:** 0 qualifying moments. Her only GPS-home/URA-home segment (10-19 07:22, 2 min) had one BLE tracker `home` the whole time, so own-BLE-away was false.

**Oji (home-truth intervals):**

| Interval | Minutes at home marked away | Evidence he was home | What each site would have done |
|---|---|---|---|
| IV1 10-19 09:37-09:46 | 8.5 | face `family_room` 09:40:27; BLE re-fix Study A Closet | Zone Anyone: Ezinne home, no change. Alpha: Ezinne home, blocked. **False pre-arrival at 09:46** (no 15-min guard) |
| IV2 tail 19:19-19:34 | ~15 | `front_door_aerial` face 19:19:18, BLE re-fix 19:34 | Ezinne home, nothing changes beyond display; arrival signal comes 15 min late |
| IV6 10-22 16:46-18:03 | 77 | 6 `family_room` faces 17:20-17:34 | Ezinne home: zone sites unchanged, alpha blocked. Unidentified run 78 s (< 300 s gate). **False pre-arrival at 18:03** |
| IV7 10-22 19:30-19:37 | ~7 | `family_room` faces 19:30:26, 19:36:34 | Ezinne and Jaya home: no house or zone effect |
| IV10 10-24 08:45-10:11 | 85.5 | 4 interior faces; Garage A last fix 08:39 | Ezinne away 20 min: Anyone display can drop; alpha blocked (face latch 19/19). Unidentified > 0 run 1,080 s: **GUEST gate arms** |
| IV11 10-24 10:18-14:03 | 225.5 | 21 interior faces, 3 garage, 5 perimeter | Ezinne away 45 min (Anyone display can drop); alpha blocked (face latch 23, unidentified 22 of 45). Unidentified run 2,641 s (1,411 s if guard raw): **GUEST gate arms** |
| IV12 10-24 14:10-ongoing | 309.5+ | 50 interior faces, doorbell entry 17:06 | Ezinne and Jaya home: zone sites unchanged. Unidentified run 2,595 s with the swap, 0 s raw: **GUEST gate arms only with the swap** |

Operator's stated acceptance ("I don't have to care about Bluetooth being missed while at home") covers the display/routing effects. It does not cover a false GUEST state, a false arrival/pre-cool, or a house AWAY while he is home; the replay shows the first two reachable and the third prevented only by cameras.

---

## 6. Falsification attempts

- **"Oji was away on 10-24":** disproved by 75 interior-camera face events (`sensor.*_last_recognized_face_2`) and the 08:42 `family_room` `Ojini` event after the 08:39 garage exit. Would be revived only if those labels are systematically wrong; `frigate_ojini_last_camera` also tracks Family Room 14:41, 17:13, 19:02 today.
- **"The swap at 5884 is neutral":** disproved by the 3.6 run lengths (IV12 2,595 s swapped vs 0 s raw).
- **"The 15-min pre-arrival guard covers overrule":** disproved by `person_coordinator.py:792` / `:873` (immediate `_person_was_away = True`); guard only at `:658` (LOST path).
- **"`zone_has_home_person` is a live site":** disproved by repo-wide grep.
- **"Frozen GPS is a GPS problem":** in IV10-IV12 the GPS tracker's last real fix is 06:11 and the phone's BLE last seen is Garage A 08:39; GPS "home" is plausible truth while BLE is the dead source. Cause of the BLE silence is **unknown** (UNVERIFIED hypothesis: phone left in a garage vehicle or powered down; `sensor.iphone_oji_area_last_seen = Garage A` at 08:46).

---

## 7. Items for the plan (not applied; read-only audit)

1. Reframe the headline: the new rule is correct in ~35% of the minutes and produces a false-away in ~65%; INV-1's falsifier tuple (10-24, proxy 55) is a verified at-home day. Ask the operator to confirm 10-24 (and 10-22 16:46-18:03, 10-19 09:37).
2. Do not adopt `camera_census.py:5884` (leave raw). Measured benefit <= ~1.5 min; measured cost = GUEST arming.
3. Drop `zone_has_home_person` from the §6b ADOPT list (no production caller).
4. Fix plan table row 15: the overrule path fires pre-arrival with no 15-min guard (`:792`, `:873`); decide whether Q3 "dropout-triggered pre-arrival accepted" covers a pre-cool write on a home zone.
5. The D1 live re-run (2) "false aways overnight 0" cannot detect this class. Add the daytime camera-face check used here.
6. The four night-gated and display-only sites need no change either way; note that in §6b.

## 8. Files

- Plan: `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_presence_gps_assistive.md`
- Code cited: `custom_components/universal_room_automation/` `aggregation.py:4430-4640`, `person_coordinator.py:601-660,776-800,861-880`, `camera_census.py:2670-2700,5870-5905`, `domain_coordinators/hvac.py:3380-3410,3974-3990,7052`, `hvac_fans.py:1500-1540`, `hvac_zones.py:2653-2680`, `presence.py:196,2085-2150,5965`, `hvac_const.py:1067,1284`, `const.py:3953`.

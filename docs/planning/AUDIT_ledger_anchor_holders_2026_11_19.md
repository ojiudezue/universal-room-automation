# AUDIT: what blocks the crossing-ledger empty-house anchor (probe (b), PLANNING_vision_interior_sightings.md §1b.0) (2026-11-19 00:25 CST)

Read-only. Presence STATE_OF_PLAY not read in full (no presence behaviour changed; anchor rules taken from `crossing_ledger.py:471-540`, `crossing_vision.py:1888-1972`, `const.py:3883-3925`; §1b read fully). All times CST.
Scripts: `.claude/tmp/holdpull_drv.py` (remote read-only pull), `holdan_run.py`, `holdan_eval.py`, `holdan_cf.py`, `holdan_cf2.py`. Data `.claude/tmp/holdpull.json`.

## Window and method
Recorder `states` starts 11-11 04:12 (`tmin`), so the window is 11-11 04:12 to 11-19 00:20 (7.8 d). Empty-house window = all four residents (`person.oji_udezue/ezinne/ziri/jaya`; `person.wall_kiosk` excluded, a kiosk) `not_home` for >= 900 s, sampled on the house `census_snapshots` (frigate+unifi bodies, ~90 s). 22 windows, 1,216 min.
Per sample the anchor predicate is replayed: bodies 0, fleet not dark (`persons_in_house.camera_input_dark_fired`), no held Tier-1 input (71 entities, config-derived list `ledgersweep/tier1.json`; dead = `unavailable/unknown` with last-good `on` or none, last-good reset at each recorder run start), no rising edge (any transition to `on`). Stuck release is modeled only as P22: live `on` >= 4 h and house state not in sleep/waking/home_night (`const.py:3903`, `coordinator.py:2938-2968`). Chatter / duty-cycle exclusion, stream-dead views and `R is not None` (`crossing_ledger.py:503`) are RAM-only and NOT reconstructable.

## 1. Answer
Cause mix over 1,216 empty minutes (a minute counts for each failing condition): edge 581, bodies 346, held 336, dark 0, passing 260.
- **Edges, not holds, was the dominant blocker, and one sensor caused it:** `binary_sensor.ratgdov25i_dbfe2a_motion` (Garage B, esphome / ratgdo `v25iboard_secplus2`, device `GarageOpener_RATGDO2.5i_Wifi_GarageB`) = 1,933 rising edges inside empty windows; 14,117 `on` pulses of median 3.0 s in the recorder; 300+/h from 11-11 until 11-16 ~09:00 then abruptly ~0 (2-8/h from 11-17 15:00). Excluding it as held only gains nothing (11 vs 3 windows anchored only if its edges are also ignored; edges still block). Cause of the 11-16 stop unknown (not investigated). It is no longer a blocker.
- **Since 11-16 09:30 (post-chatter) the blockers are:** bodies > 0 while residents are away (guest or non-resident persons, ~half of the home_day windows) and the two Living Room radars below.
- **Live stuck holders P3-D8 releases (inferred):** the one live anchor (11-17 08:42:32) is reproduced to 48 s (model 08:43:20) only if `screek_human_sensor_l13_2412s_presence` AND `mmwave_lux_temp_hum_zigbee_livingroom_presence` are both excluded; `screek` crossed exactly 4 h `on` at 08:42:32 (on since 04:42:32). So P3-D8 already covers them, at the 4 h latency (P22), not earlier.
- **Unexplained live false negative:** 11-17 17:04-17:30 and 17:40-18:02 (all away, bodies 0, nothing held in my replay, 4 h+ after the 10:40 restart, no restart in the interval): the model predicts anchors at ~17:18 and ~17:55; the DB has none. Live blocker is unmodeled: `R` None, a stream-dead Tier-1 input (`camera_stream_health.entity_stream_view`), Tier-1 map drift vs `tier1.json`, or a chatter/duty-cycle state lost at restart. UNKNOWN. This must be resolved before trusting the "gain" numbers below; enabling the registry-disabled diagnostic `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` (holders + R) is the one-shot oracle (operator config).

## 2. Per-entity table (empty windows, 11-11 to 11-19)
Registry-resolved (`core.entity_registry` + `core.device_registry`). "On min" = held `on` minutes excluding the P22-modeled release; "dead min" was 0 for every entity (no recorder `unavailable` overlapped an empty window; stream-dead views not observable).

| entity (binary_sensor.) | room / class | platform, device model | on min | edges | max on-run | live-stuck vs dead | already excluded? | alone gain (held+edges) |
|---|---|---|---|---|---|---|---|---|
| occupancy_lux_temp_humidity_hobeian_downguestroom_presence_2 | Guest Bedroom 1 / motion | mqtt, HOBEIAN mmWave motion | 137 (+61 P22-released) | 0 | 11.7 h | live-stuck (11-13 on 13:10 to 18:51, no bodies) | P22 after 4 h only; the first ~3 h held | +3 anchors, +116 known min, all 11-13 (pre-ship) |
| ratgdov25i_dbfe2a_motion | Garage B / motion | esphome, ratgdo | 93 | 1,933 | 3 s pulses | live chatter | unknown (chatter client is RAM-only); silent since 11-16 09:00 | 0 held-only; held+edges: 11 windows vs 3 (pre-fix only) |
| occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2 | Guest Bedroom 2 / motion | mqtt, HOBEIAN | 76 | 31 | 4.4 h | live, uncorroborated | no | 0 alone |
| mmwave_lux_temp_hum_zigbee_livingroom_presence | Living Room / mmwave | mqtt, HOBEIAN 24GHz | 63 | 0 | 4.4 h | live-stuck | YES, inferred (live anchor 11-17 08:42 requires it) | with screek: +1 window, +1 anchor (11-17) |
| screek_human_sensor_l13_2412s_presence | Living Room / mmwave | esphome, Screek L13S | 30 (+93 P22) | 0 | 20.0 h | live-stuck | YES, P22 at 4 h (anchor lands at 4 h boundary) | as above |
| mmwave_motion_lux_meross_wifi_mediaroom_sensor_presence_motion | Media / motion | meross_lan ms600-un | 10 | 9 | 0.2 h | live, short | no | 0 |
| mmwave_temp_hum_lux_zigbee_masterbedroom_presence | Master Bedroom / mmwave | mqtt, HOBEIAN 24GHz | 6 | 9 | 2.1 h | live, short | no | 0 |
| screek_human_sensor_l13_b38b24_presence | Master Bedroom / mmwave | esphome, Screek L13S | 4 | 6 | 1.8 h | live, short | no | 0 |
| up_hallway_panel_person_occupancy | Upstairs Hallway / "mmwave" | **frigate** (Up Hallway Panel camera person) | 0 (+82 P22) | 0 | 14.0 h | live-stuck camera-person ghost in Tier-1 | YES, P22 | 0 |
| mmwave_motion_lux_matter_wifi_mediaroom_occupancy | Media / mmwave | matter, Meross presence | 0 (+10 P22) | 0 | 18.2 h | live-stuck | YES, P22 | 0 |

Garage A `occupancy_lux_temp_humidity_garagea_presence` (mqtt HOBEIAN): 6 edges, no holds.

## 3. Expected anchor gain
Baseline replay (P22 only): 3 windows anchored / 7 anchors (11-14 and earlier mostly pre-ship; ledger live 11-14 16:03). Since 11-16 09:30: 1 window / 2 anchors (the 17:xx false positive above, not observed live).
- Exclude every live `on` holder (held only, edges still count): all 15 windows / 45 anchors, but that includes ratgdo chatter; since 11-16 09:30: 3 windows / 5 anchors / 66 known min (vs 1/2/45).
- Ceiling with no holders and no edges at all (bodies and dark only): 4 windows / 11 anchors; since 11-16 09:30 2 windows / 3 anchors. So after the ratgdo stopped, what remains is bodies and real occupancy, not stuck sensors.
- No single remaining live-stuck input is worth a card on its own: since 11-16 the only gain is the Living Room pair, already released live (inferred). The Guest Bedroom 1 HOBEIAN (11-13) is the only entity with a sole-blocker record.

## 4. Recommendations (stuck-sensor cards, no ledger change)
1. (Gap, low) P22 latency: a motion-class HOBEIAN `on` for >= 4 h in an empty house blocks ~3 h before release; Guest Bedroom 1 on 11-13 cost ~116 known min. A motion-class shorter-than-4 h stuck rule (duty-cycle) is the existing mechanism's job; card only if the probe recurs. No dead input is touched.
2. ratgdo Garage B chatter 11-11 to 11-16 was the single largest anchor blocker (1,933 edges); it stopped by itself. Cause unknown; card to find out (firmware/ESPHome change?) before it returns. Existing chatter client exclusion may handle it; verify with the diagnostic.
3. Tier-1 contains a Frigate camera-person entity (`up_hallway_panel_person_occupancy`, platform frigate) classed "mmwave". A camera entity in the held set is by registry a camera, not a radar: confirm intent (registry-not-names rule). Not changed here.
4. Resolve the 17:xx unexplained non-anchor (enable the diagnostic) before F-D0 trusts any anchor-yield number.

## 5. Known-time since 11-17 10:40 restart (F-K, §1b.0 method 1)
- Ledger rows 11-11 onward: 1 anchor (11-17 14:42:32Z = 08:42:32 CST) and 111 terms, all `applied=false reason="unknown"` (SQL on `memory_episodes`, `episode_type='crossing_vision_ledger'`).
- Restarts (`recorder_runs`): 11-17 08:50:54 down / 08:51:35 up; **11-17 10:40:14 down / 10:40:48 up**; **11-18 23:02:46 down / 23:03:36 up** (a later restart than the one named in the brief).
- Known from that anchor to the next restart: 08:42:32 to 08:50:54 = **8.4 min**, over-count error 0 (restart terminates it; first later term 09:16 is `unknown`).
- **Since the 10:40:48 restart: 0 anchors, 34 terms all unknown, known-time = 0 over 37.7 h (to 00:23).** The 4 empty windows in that span (11-17 16:36-18:02; 11-18 07:21-08:11, 15:38-16:02, 16:11-16:47) had 0 anchors; the first ran 52 passing minutes in the replay (unexplained, section 1).
- 7-day known fraction: 8.4 / 10,080 min = **0.08 %**, F-K (0.25) FAILS. Prior audit's "~34 min known" figure over-counted: the restart cut it at 8.4 min.
- Anchor-zero trip-wire (`CROSSING_VISION_LEDGER_ANCHOR_ZERO_S` 172800 s) would first fire ~11-19 08:42.

## Falsification
- "Held inputs block anchors": falsified for ratgdo (held-only exclusion gains nothing; edges block); confirmed for the Guest Bedroom 1 sensor on 11-13.
- "Living room pair already released": would be falsified by the live anchor not occurring at the 4 h boundary; it occurred at 08:42:32 (the boundary exactly), so this is consistent, but only inferred (no direct exclusion-set read).
- Calibration: replay misses the 17:xx non-anchor. Model is a lower-confidence guide, n = 1 anchor.

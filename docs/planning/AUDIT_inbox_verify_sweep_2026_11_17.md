# Inbox verify-before-work sweep, 2026-11-17 (read-only)

Run 2026-11-17 02:08-02:30 CDT on `develop` (checkout `/Users/okosisi/Code/universal-room-automation`; HEAD 088c9c819). Live data: HA recorder `/config/home-assistant_v2.db` and URA DB via `ssh ha sqlite3 -readonly`. Card text was not trusted. For card 5 I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` headers, §0, §1, §2 and the 2026-11-12 pre-arrival header entry (line 13). I did not read §3-§12 fully, so the "no arrival-heat cap" claim rests on the code citation, not on a full read of that doc.

## Summary

| # | Card | Verdict | Evidence |
|---|---|---|---|
| 1 | STALE-SOURCE-ARRIVAL-CONSUMERS-1 | STILL-REAL (blocker shipped) | `stale_source_arrival` exists (`arrival_edges.py:73`). The security geofence handler `security.py:2268-2288` does not call it. |
| 2 | LOCK-UNCOUNTED-RETURN-ARM-REDUNDANT-1 | PARTIALLY-DONE | The ARRIVING evidence compute is now gated to ARRIVING (`perimeter_alert.py:2157`). The `away`/`arriving` arm is still in `security_lock_regime.py:1513-1514`. |
| 3 | PHONE-LEFT-BEHIND-TRANSIENT-FLICKER-1 | STILL-REAL (rarer, and no gate in code) | The camera-leg swap shipped (v5.108.21), but it is display-only. 19 on-spells in 7 days, every one 30 s, none real. No spell since 11-14 16:06. |
| 4 | CENSUS-FACE-READS-STREAM-HEALTH-1 | STILL-REAL, but unmeasurable from persisted data | Face legs are age-gated at 1800 s. No table persists per-leg camera provenance joined to stream-dead intervals. |
| 5 | HVAC-PRECOOL-FLOOR-BELOW-ARRIVAL-HEAT-1 | STILL-REAL in code, cannot fire today | The stand-down shipped (v5.108.14). Cool Floor is live at 74.0, which is at least 72. |
| 6 | DEPARTURE-ACTIONS-1 | CARD-WAS-WRONG on "nothing consumes a departure" (D8 itself not shipped) | D8 is not shipped (card `planned`, direction-blind veto at `transit_validator.py:2303-2307`). A departure consumer exists in `music_following.py:1821-1915`, shipped 11-15 in v5.108.33. |

## 1. STALE-SOURCE-ARRIVAL-CONSUMERS-1: STILL-REAL

- Lock hold shipped. Its blocker `GARAGE-REMOTE-LOCKOUT-SCHEDULE-1` is `shipped_organic` v5.108.13 (`kanban.data.yaml:701-705`). The check is `arrival_edges.stale_source_arrival` (`arrival_edges.py:73-107`), used by the lock regime (`security_lock_regime.py:1678`) and the residency tracker (`presence.py:5380-5395`).
- A music consumer already routes through the residency record flag. `music_following.py:1152` skips with `skipped_not_counted_return:stale_source`.
- Security expected-arrival window: `SecurityCoordinator._handle_person_state_change` (`security.py:2252-2288`) does `not_home -> home` and calls `add_expected_arrival(entity_id, window_minutes=10)`. Its only gate is `_armed_state == DISARMED` (`security.py:2258`).
  - `grep stale_source` in `security.py` returns nothing. The only `arrival_edges` import there is `arrival_source_needs_corroboration` (`security.py:49`).
  - So a stale-tracker fallback `home` blip still opens a 10-minute window.
  - While `_expected_arrivals` is non-empty, `SANCTIONED` is returned (`security.py:304-305`).
- Correction to the card's severity framing: after the expected-arrivals check, `if persons_home: return SANCTIONED` (`security.py:312-313`). So the window changes the verdict only when the census sees nobody home. With residents home the entry is sanctioned either way. The "house otherwise occupied" harm in `finding_2026_11_12` is overstated. The `unknown_present` ALERT_HIGH check (`security.py:299-301`) still runs first.
- I did not recount the 78 iPad blips.
- Falsifier I checked: that the geofence handler delegates to the lock regime. It does not. The `SIGNAL_PERSON_ARRIVING` path at `security.py:2410-2446` is separately gated through `face_input_corroborated`, but that is the other path.
- Residual if built: add the `stale_source_arrival` check at `security.py:2275`, or use the residency record's `source_stale`. Also check whether HVAC pre-arrival needs it. `source_stale` has no HVAC reader today (grep of `source_stale` finds only `music_following.py:1152` and `presence.py:5366-5394`). I did not trace HVAC's trigger.

## 2. LOCK-UNCOUNTED-RETURN-ARM-REDUNDANT-1: PARTIALLY-DONE

- (b) ARRIVING evidence computed and logged for every alert: FIXED. `perimeter_alert.py:2157` `if (state or "").lower() == "arriving":` wraps the whole evidence compute. `evidence` stays `None` otherwise, and the INFO line at `perimeter_alert.py:2190-2195` is guarded by `if evidence is not None`. Introduced in `a0d590ef2` (11-13, house-state 1a D2/D5). The original finding was U8 in `docs/reviews/code-review/v_house_state_step1a_C.md:55`.
- (a) Redundant arm: STILL PRESENT. `_uncounted_return_pages` (`security_lock_regime.py:1495-1520`) ends with `self._episode_saw_empty or self._house_state() in ("away", "arriving")` (lines 1513-1514). I did not prove whether the `away`/`arriving` branch is redundant; I rely on the review's L6 label. The code itself is unchanged since its introduction on 11-13.
- Residual: delete or pin that arm (about 1 LoC). Write a test either way.

## 3. PHONE-LEFT-BEHIND-TRANSIENT-FLICKER-1: STILL-REAL

- Camera-leg swap shipped. `PHONE-LEFT-BEHIND-CAMERA-LEG-1` is `shipped_organic` v5.108.21 (commit 4dbaffe33, 11-13 23:56). Operator ruling A: the camera leg is display-only (`kanban.data.yaml` ~35700 block). So it cannot affect the flicker.
- No dwell or census-ready gate exists in the PLB sensor. The sensor class is at `binary_sensor.py:~2156`. A grep of `binary_sensor.py` lines 2100-2500 for census_ready, dwell, settle, boot_window and ready returns only a comment at line 2197.
- Recorder measurement, 2026-11-17 ~02:10 CDT. Entities: `binary_sensor.universal_room_automation_{ezinne,jaya,oji_udezue,ziri}_phone_left_behind`, metadata_ids 15980-15983.
  - Method: state-change rows only (`last_changed_ts` null or equal to `last_updated_ts`), last 7 days, `lead()` for duration. Table (query `/tmp/q3.sql`):

| entity | on-spells | durations |
|---|---|---|
| ezinne | 11 | all 30.0-30.6 s |
| jaya | 7 | all 30.0-30.6 s |
| ziri | 1 | 30.6 s |
| oji_udezue | 0 | none |

  - Total: 19 spells, all under 60 s, all about one 30 s poll. Zero longer than 60 s, so zero real ones. This agrees with the card's "17 in 8 days, none real".
  - Dates (CDT): 11-10, 11-11, 11-12 (two sensors at 21:12:01), 11-13, 11-14.
  - Latest spell is 11-14 16:06:57 (three sensors at once, so it looks restart-shaped).
  - Nothing 11-15 to 11-17.
- Residual: the rate dropped (none in the last ~3 days) but the code gate is absent. The card's value claim is "house-state trust input". Whether a 30 s transient `true` ever mattered is not measured here. Re-check if a restart happens and the flags blip again.

## 4. CENSUS-FACE-READS-STREAM-HEALTH-1: STILL-REAL, answer unmeasurable from persisted data

- By construction a face leg cannot be held "past its window". The age gate is `age <= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (1800, `const.py:5058`) at `camera_census.py:4087`, `:6370` and `:6702`. The residual hazard is a flap that re-stamps `last_changed`: `camera_census.py:6704-6706` says the Frigate `last_camera` sensor "flaps unavailable<->camera, re-stamping last_changed, so the age gate alone never elapses". That hazard is handled by the person-tracker `not_home` veto (`camera_census.py:6707-6712`, fail-open if the person entity is missing).
- Interior stream-dead is already honoured by census for configured interior inputs (`camera_census.py:2068, 2254, 6306-6310`), but not for the face leg.
- Why the data cannot answer:
  - Stream-dead state is in RAM only (`camera_stream_health.py`, no DB writes).
  - NM is the only persisted trace, and it is thin. `anomaly_log` holds 33 `camera_stuck` rows (2026-08-24 to 2026-10-30), all about occupancy sensors. There are 6 `camera_stream_nvr_down_twin_covering` rows, all at one moment on 2026-11-17 04:15 UTC. There are zero `camera_stream_dead` or `hold_released` rows.
  - `census_snapshots` (195,405 rows since 2026-08-18) has only counts, `identified_persons` and `source_agreement`. It has no per-leg camera id.
  - `person_presence_snapshots` is `(person, room, confidence, method)`, also no camera.
  - The recorder shows long camera `unavailable` spells. Camera outages over 30 minutes in the last 7 days include `camera.g3_instant_high_resolution_channel(_2)` (max about 1050-1077 min) and `camera.up_hallway_panel` (843 min). Most of the rest show 250 min, which looks like one shared event. I did not join these to face-leg state, because that state is not persisted.
- Verdict: the card's own gate ("build only if it has") cannot be evaluated. By the Soak Exit rule, either park it with a revival trigger (a counted census face from a camera stream-dead for more than 1800 s) or add a trip-wire. Recommend PARK. The window gate bounds the damage, and the card's own value is 1/1/2.

## 5. HVAC-PRECOOL-FLOOR-BELOW-ARRIVAL-HEAT-1: STILL-REAL in code, dormant live

- Stand-down shipped: `HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1` is `shipped_organic` v5.108.14 (`kanban.data.yaml:34600-34601`; state-of-play line 13, "validated 21:10 CST"). Code: `hvac_predict.py:1403-1409` (mode gate) and `:1448-1458` (`T <= effective_high + margin -> "standdown"`).
- The defect is unchanged. `_precool_effective_high` (`hvac_predict.py:1667-1673`) is `max(banked_high, max(solar_bank_floor, live_low + MIN_DEADBAND))`, with no cap at the arrival preset's heat setpoint.
  - The heat leg has the band-inversion guard `band_inverted` (state-of-play line 13), but the cool leg has no heat-floor cap.
  - A zone at T above `effective_high` but inside Home's band gets cooled down to `effective_high`. If the floor is under Home heat (state-of-play line 13: shoulder/winter Home baseline 70/77, summer 70/76), that is down to or below the heat setpoint.
- Live knob: `number.ura_hvac_coordinator_solar_banking_cool_floor` = 74.0, last updated 2026-11-16 15:33 CDT (recorder `states` latest row). Entity min/max is 65-80 (`number.py:2781-2786`), default 72.0 (`hvac_const.py:66`).
  - Result: at floor 74, `effective_high >= 74`, which is above Home heat 70. The defect cannot fire today.
  - It would need the floor lowered under about 70-72.
- Verdict: dormant, legal-knob-extreme only. Reasonable to PARK with the revival trigger "floor knob set < 72" or fold into the next HVAC cycle, as the card says.

## 6. DEPARTURE-ACTIONS-1: CARD-WAS-WRONG on "nothing acts"; D8 not shipped

- D8 (`EGRESS-DIRECTION-AWARE-IDENTITY-1`) is not shipped. The card status is `planned`, tier 3 (`kanban.data.yaml:34859-34880`). The code still holds the direction-blind veto: `transit_validator.py:2303-2307` returns `vetoed` when `person.<slug> == not_home`, with no direction branch. `git log` shows only plans, contracts and the layer 3a scaffolding (`a3d20ea90`, `99be55c27`), not the D8 rule. The "direction-aware" rule itself is not built.
- Departure consumer exists and is not D8-fed. `music_following.py:1821-1915` sets `stamp.departure` from a record `edge_ts` and pauses the arrival music (`departure_paused`, gated by `ARRIVAL_MUSIC_DEPARTURE_PAUSE = True`, `const.py:5349`). Shipped in `f7277a07f` (2026-11-15 21:59, "arc step 8 D2-D4 arrival music, welcome scene decision, departure pause"), contained in tags v5.108.33 and v5.108.34. Its departure signal is the residency tracker's person edges (`get_person_edges_since`, `music_following.py:1859-1866`), not egress.
- Fire check: `memory_episodes` has 21 `person_departure` and 23 `person_arrival` episodes (latest 2026-11-16 22:26 and 21:01 UTC). There are zero `arrival_music` episodes, so the music consumer's outcome ledger has never written a row. I could not tell whether that is a toggle or profile gap or the consumer not yet being live (it shipped under 1 day ago). Unknown.
- Residual: nothing consumes a departure for HVAC setback or last-resident-out arming. `LAST-RESIDENT-EGRESS-ARM-1` is parked (`kanban.data.yaml:27428-27441`, revive at greater than 30% egress attach and a measured arm-lag gap). The card's "after D8" gate stands for those. The title is stale.

## Not verified
- The number of stale-tracker blips for card 1 (card claims 78 in 11-05..11-11).
- Whether the lock regime's `away`/`arriving` arm is truly redundant (card 2).
- Whether `arrival_music` having zero episodes is a defect (card 6).

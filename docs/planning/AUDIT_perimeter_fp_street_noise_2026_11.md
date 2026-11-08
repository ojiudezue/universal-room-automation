# AUDIT: Perimeter alert false positives and street noise (PERIMETER-FP-STREET-NOISE-1)

Date: 2026-11-08 (CST; DST ended 2026-11-01, so local = UTC-6 now, UTC-5 before). Read-only probe. Nothing was changed.
Read first: AUDIT_perimeter_fp_correlation.md, PLANNING_perimeter_consolidation.md, PLANNING_snap1_at_detection_snapshots.md,
the PERIMETER-PHANTOM-XCORR-1 and FRIGATE-LEG-NAMING-1 cards (kanban.data.yaml), IDENTITY_FUSION_CAMERAS_MANUAL.md section 4.5,
memories reference_frigate_ghost_evidence_chain / reference_frigate1_retired_2suffix_permanent / reference_pooloverhead_four_integrations.
I did NOT read PRESENCE/HVAC state-of-play docs (not relevant here).

## 0. Answer first

1. **About 95% of person alerts are outside 23:00-05:00** (1616 of 1696 in 30 days, ~56/day). The person alert-hours gate was removed in CONSOL-1 (perimeter_alert.py:1068). The one gate aimed at repeats (XCORR-1 burst demote) is night-only (const.py:2481, 2491), so it covers about 5% of traffic. Only 25 of 1696 alerts were ever demoted to LOW.
2. **Two distinct noise populations**, in a 52-snapshot sample of 7-day alerts (viewed):
   - **Empty-scene Frigate-2 detections** on back_yard, hot_tub, front_side_ptz, pool_equipment. 21 of 52 samples had nothing visible. They are short (back_yard median 6.5 s, 22% under 2 s) and fire with Protect silent.
   - **Real people on the street/sidewalk/road behind the lot** on rear_ptz, utilities_ptz, g5_bullet (top-right strip). 16 of 52. These are true persons, not model errors, and are mostly **Protect-only** (6 of 8 rear_ptz, 2 of 2 g5_bullet street persons had no Frigate-2 leg within 60 s).
3. **No existing gate uses score, dwell, box position or zone.** The Frigate event handler reads only label/camera/id (perimeter_alert.py:779-815) and the linker is fed `score=0.0` (perimeter_alert.py:3896-3903). The bridge automation already puts the full Frigate `after` payload (box, score, current_zones, stationary) on the bus for both Frigate hosts (automations.yaml:6578-6595), so the data to extend the existing handler is already flowing.
4. **Storage is not a concern for URA snapshots** (250 MB, 1781 files, ~36 MB/day, retention working, 318 GB free). **It IS a concern for `/config/www/doorbell_alerts`**: 2.3 GB, 5396 files, no cleanup, web-served, written by an HA automation (not URA). See section 5.

## 1. Tuning already in place (what exists, live value, what it was meant to stop)

URA-side gates, in the order the person path runs them (`_async_handle_perimeter_trigger`, perimeter_alert.py:1064+). All values are module constants or code, not live knobs (the only live perimeter options on the config entry are the camera lists; read from `.storage/core.config_entries` 2026-11-08: `perimeter_cameras` = 11 cameras incl. madroneptultra and sonoffwindow, `egress_cameras` = 5; no `perimeter_enrichment_*` keys, so enrichment is OFF by default).

| # | Gate | Live value / file:line | Added by | Meant to stop | Applies to |
|---|---|---|---|---|---|
| 1 | Rising-edge only + boot settle | `PERIMETER_BOOT_SETTLE_S=30` const.py:2845; `_on_perimeter_event` :3849 | v3.5.0 base (bc97cf23); B-HIGH-2 fix-up 312fb329 (2026-08-01) | RestoreEntity replay and on->on attribute churn firing CRITICALs at boot | all legs |
| 2 | Egress suppression | `EGRESS_SUPPRESSION_WINDOW_SECONDS=120` perimeter_alert.py:247, used :1076 | v3.5.0 (2026-02-24) | Alerting on your own recent entry/exit crossing | all cameras |
| 3 | Per-camera cooldown, keyed by camera not sensor | `PERIMETER_ALERT_COOLDOWN_SECONDS=300` const.py:2405; `_camera_key_for_sensor` :1840 strips `_2`/Protect/vehicle suffixes | cooldown v3.5.0; camera-key collapse = Cycle 2 fused-sourcing (2026-08), alias fix 2026-08-06/07 | Duplicate sends for one event seen on Frigate + Protect + `_2` legs (the "double send" in PHANTOM-XCORR-1) | all cameras; this is the `_2` / dedup handling |
| 4 | In-flight guard | `_dispatch_in_flight` :1129 | A-M1 (2026-08) | Second trigger while a delayed-snapshot dispatch is pending | all |
| 5 | Classification-transition exemption | `_classification_transition_exemption_permitted` :2055 | CIRCLING-LABEL-1 D2 fba479f7 (2026-08-14) | Not an FP gate. It lets approach/circling bypass the cooldown once per track. It can only add alerts | linker-tracked cameras |
| 6 | Contextual severity | `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` const.py:2589 (home_day/evening first_sighting = LOW if trusted persons_home >= 1 else HIGH; away/sleep/home_night/waking = CRITICAL) | CONSOL-1 90dfe1bf (2026-08-11) | Loudness proportional to house state (replaces the removed 23-05 existence window) | all |
| 7 | Track-linker severity coercion | `TRACK_LINK_WINDOW_S=180` const.py:2677; perimeter_alert.py ~1190-1260. Demotes to LOW only for a CONTINUATION of a confident pass_by track with camera_count >= 2; first alert of a track is never touched | linker cf34a650 (2026-08-06), Tier-3 fix-up | Same walker pinging camera after camera | multi-camera tracks only; ring adjacency const.py ~2700 |
| 8 | XCORR-1 burst demote | `PERIMETER_BURST_DEMOTE_ENABLED=True`, `_WINDOW_S=1800`, `_MIN_ALERTS=2`, `_NIGHT_ONLY=True`, `_NIGHT_WINDOW=(23,5)` const.py:2469-2491; `_evaluate_burst_demotion` :2208; sibling window `_SOLE_FIRE_WINDOW_S=60` :1891 | XCORR-1 cf7a9be7 (2026-08-08); night window pinned CONSOL-1 fix-up A4 | 2nd+ isolated single-camera alert within 30 min with no sibling-engine corroboration and no adjacent-camera activity (the 08-08 repeat-ghost incident) | **23:00-05:00 only**; first alert always full severity |
| 9 | Snapshot at detection + retention | SNAP-1 7e28a2ea (2026-08-08): dir `/media/ura/snapshots`, `RETENTION_AGE_H=168`, `RETENTION_COUNT=5000`, sweep 6 h (const.py:2918-2967) | SNAP-1 | Empty/late snapshots; disk growth | all |
| 10 | llmvision enrichment | `DEFAULT_PERIMETER_ENRICHMENT_ENABLED=False` const.py:2437; text-only, INV-ENRICH-NEVER-SILENCES | CONSOL-1 | Not a gate. Adds a description, cannot suppress | OFF live |
| 11 | Safeword silence window | SAFEWORD-WINDOW-1 (2026-08-14) | operator-initiated | Operator-opened perimeter mute | manual |

Cross-NVR corroboration, specifically (PERIMETER-PHANTOM-XCORR-1, status done 2026-10-12):
- The URA-side "demote single-source to LOW" was **deliberately not built**. Card measure 2026-09-12: ~87% of alerts are single-source because most cameras have no overlapping second NVR, so a blanket demote would floor genuine detections (front_side_ptz caught the real garage walk-in). The only corroboration that exists is the sibling-engine check inside the night-only burst demote (gate 8) and the track linker (gate 7).
- The card was closed because **homelab applied pool_equipment masks 10-09** (bundle, back-wall pipe fitting, condenser motion mask).

Frigate-2 side (from homelab-automation `configs/snapshots/frigate2/config.yaml-2026-10-09-pre-pool-equipment-mask`; this is a 10-09 snapshot, the live file is the homelab agent's to confirm):
- `objects.filters.person min_score 0.5 / threshold 0.6` on back_yard, front_side_ptz, hot_tub only. utilities_ptz, g5_bullet, pool_equipment, rear_ptz have no person filter block.
- Motion + object **road masks** on front_side_ptz (`0,0 1,0 1,0.46 0,0.46`, 2026-08-27 / 09-14) and rear_ptz (`... 0.62 ...`). Comment says it degrades if the PTZ roams.
- **No zones anywhere. No masks on back_yard, hot_tub, utilities_ptz, g5_bullet.** Global `detect` threshold 0.6 / face min_area 250 are face settings.
- Frigate 1 is retired (entities removed), so the `_2` suffix is the live perimeter leg; URA resolves legs via the resolver (FRIGATE-LEG-NAMING-1 latent LOW, no live bug).

## 2. Method

- Alerts: `notification_log` rows with `hazard_type in (exterior_person, exterior_vehicle)` and `message='[audit]'` (one per logical alert), 2026-10-09 to 2026-11-08, read via `ssh ha sqlite3 mode=ro`. 1696 person + 41 vehicle alerts. Camera collapsed from the leg entity in `location`. The table has no score/zone/snapshot column; snapshot is matched by camera + epoch in the filename (capture within -3..+15 s of the audit timestamp; 7-day matches covered almost every alert).
- On-duration: HA recorder `states` for all `binary_sensor.*person*` ON periods, last 7 days (immutable read; 8904 periods).
- Snapshots: `/media/ura/snapshots` on the HA host. 52 alert-matched files (stratified random, seed 7) pulled to the scratchpad, tiled into contact sheets, viewed by eye, labelled.
- Caveat: n=52 and one labeller. Per-camera rates below are indicative, not tight. Uncertain frames are labelled uncertain, not forced.

Artifacts (scratchpad, `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/perim/`):
`sheets/sheet01.jpg` .. `sheet09.jpg` (6 tiles each, tile label = #index camera local-time severity leg), `sel2.json` (index to file/leg), `labels.json`, `dur.txt`, `audit.txt`, `files.txt`. Sample originals are in `img/`.

## 3. Alert inventory (30 days, person)

| camera | alerts/30d | alerts in 23-05 | dominant legs | severity mix (30d) |
|---|---:|---:|---|---|
| back_yard | 437 | 4 | Frigate-2 426 / Protect 11 | HIGH 313, CRIT 109 |
| hot_tub | 305 | 23 | Frigate-2 283 / Protect 22 | HIGH 153, CRIT 127 |
| g5_bullet | 205 | 20 | Protect 107 / F2 98 | HIGH 134, CRIT 61 |
| rear_ptz | 205 | 16 | Protect 146 / F2 59 | HIGH 163, CRIT 66 |
| reolinkstudybporchptz | 178 | 0 | F2 104 / Reolink 74 | HIGH 98, CRIT 70 |
| utilities_ptz | 178 | 0 | F2 149 / Protect 29 | HIGH 155, CRIT 24 |
| front_side_ptz | 97 | 2 | F2 80 / Protect 17 | HIGH 84, CRIT 23 |
| pool_equipment | 52 | 15 | F2 40 / Protect 12 | CRIT 25, HIGH 24 |
| armcrest | 39 | 0 | F2 21 / Dahua 18 | HIGH 39 |
| vehicle (deep-night) | 41 | n/a | rear_ptz 28, front_side 10, utilities 3 | |

Hour of day (local): back_yard peaks 07-19 h with a 12-17 h hump (35-58 per hour-bucket over 30 d); hot_tub peaks 07-11 h; rear/utilities/g5 spread through the day with a 08 h spike; pool_equipment is the only camera whose alerts are mostly night (00-06 h). Full per-hour table is reproducible from `audit.txt`.
Daily volume 13-163, median ~40/day. CRITICAL 505 and HIGH 1122: both page every channel (companion, iMessage, Pushover, WhatsApp) per the audit rows. Whether daytime CRITICAL is from away state or ph=0 is **unknown** (house state history not pulled); daytime HIGH implies persons_home=0 or a non-first_sighting track (const.py:2632-2641).

On-duration of the ON period (7 d, recorder): back_yard F2 n=114 median 6.5 s, 22% under 2 s, 31% under 5 s; hot_tub F2 n=65 median 7.9 s, 26% under 2 s, 46% under 5 s; front_side F2 n=34 median 10.6 s, 15% under 2 s. Healthy comparison: g5_bullet 20-21 s with ~0% under 5 s, armcrest 41 s, utilities Protect 52 s, pool_equipment F2 54 s (0% short: its remaining false ONs are long static ones, so a dwell gate would not help there).

## 4. Snapshot review and per-camera FP table

Sample classification (52 viewed): true person on property 10; vehicle on property (service truck) 1; person on street/sidewalk/road 16; empty/nothing visible 21; animal 1; weather/IR insects 1; uncertain tiny far figure 2.

| camera | n | true on property | street person | empty | other | dominant class | median ON (sample empties vs trues) |
|---|---:|---:|---:|---:|---|---|---|
| back_yard | 9 | 0 | 0 | **9** | | empty lawn, midday and dawn; 3 frames show a hard sun-shadow edge (#3, #7, #9), hypothesis only | empties 0.6-35 s, 7 of 9 under 6 s |
| hot_tub | 6 | 1 (#25) | 0 | **5** | | empty, mostly IR night (#26-28 on 11-08 04:26-06:02) | empties 1.7-11 s; true 28 s |
| front_side_ptz | 6 | 0 | 0 | 2 | weather/IR streaks #31, animal #34, uncertain far-left #35/#36 | non-actionable; IR + animal + tiny far | 0.7-13 s |
| pool_equipment | 4 | 1 (#44) | 0 | **3** | | empty generator enclosure with cloth/bundle still at left even after 10-09 masks (#43 11-08 05:07, #45 11-03 03:47, #46 11-08 06:16) | empties 36 s, 106 s, 805 s (long static) |
| rear_ptz | 8 | 0 | **8** | 0 | | pedestrians/dog-walkers/stroller on the road across the street; 6 of 8 Protect-only | 2-62 s |
| utilities_ptz | 6 | 0 | **6** | 0 | | joggers/dog walkers on the back road/trail, plus a flashlight walker at night (#38) | 11-71 s |
| g5_bullet | 7 | 3 (#18, #20, #24 at garage) | 2 (#22, #23 far top-right sidewalk) | 1 (#21) | service truck in driveway #19 | mixed; real hits dominate; street persons Protect-only | 14-28 s |
| armcrest | 3 | 3 | 0 | 0 | | pool service on property | 18-23 s |
| reolinkstudybporchptz | 3 | 2 (#50 far, #52) | 0 | 1 (#51) | | real people in yard | 5-28 s |

Estimated non-actionable share (empty + animal + weather + uncertain + street person), by camera from the sample: back_yard 100%, hot_tub 83%, front_side_ptz 100% (4 of 6 definite), pool_equipment 75%, rear_ptz 100% (street), utilities_ptz 100% (street), g5_bullet 43%, reolinkstudybporchptz 33%, armcrest 0%. These cover 1,350 of the 1,696 monthly person alerts (back_yard, hot_tub, rear, utilities, front_side, pool = 1274; plus g5 partial). Small n (3-9 per camera), so treat any rate under ~80% as imprecise.

Where in the frame:
- Street persons: rear_ptz top-middle road band (y 0.45-0.58 of frame; inside the existing F2 mask polygon), utilities_ptz horizon road band (y 0.22-0.38), g5_bullet top-right sidewalk (x 0.85-0.95, y 0.02-0.15).
- Empty detections have no visible object, so no frame region to name; they need the detection box which is only available on the Frigate event (see lever U1).

Producer/consumer for one value: the alert is produced from the rising edge of `binary_sensor.<cam>_person_occupancy_2` (Frigate-2) or `_person_detected` (Protect) via `async_track_state_change_event` (perimeter_alert.py:737-750); consumers are `_on_perimeter_event` -> dispatch -> NM channels, plus the linker. Both producers' health is currently fine (Frigate-2 is up; legs resolve).

## 5. Which gate should have caught each remaining FP, and why it did not

| Remaining FP | Gate that should catch it | Verdict: gap / too loose / does not run there |
|---|---|---|
| Daytime empty-lawn Frigate-2 hits on back_yard, hot_tub, front_side (about 840 alerts/30 d) | #8 XCORR-1 burst demote (isolated single-engine repeat); #3 cooldown | **Does not run**: burst demote is night-only (`PERIMETER_BURST_NIGHT_ONLY=True`, window 23-05). 95% of alerts are outside it. Cooldown only rate-limits (5 min), it never judges. Nothing checks score/dwell. back_yard F2 has Protect silent (4 Protect ONs vs 114 F2 in 7 d), so a corroboration rule would drop nearly all of them. |
| Empty IR night hits (hot_tub 11-08 04:26/05:57/06:02, front_side 11-03 03:53) | #8 burst demote | **Partly runs but too narrow**: the FIRST alert per camera per 30 min is always full severity ("first alert is sacred"), and the 11-08 hot_tub events were 5-35 min apart so each could be a first alert in a fresh window only if the previous was > 30 min earlier. Unverified per event, I did not replay the ring buffer. |
| pool_equipment night phantom survives masks (19 alerts in 7 d, 12 night CRIT/HIGH; recorder shows 30 ONs, median 54 s) | Frigate masks (homelab, applied 10-09); card said 0 ON in 3 nights after | **Gap**: either the masks do not cover the item still visible in the sample (cloth bundle, left wall) or the phantom returned after 10-12. A homelab check of live mask polygons vs frames #43/#45/#46 is needed. Dwell does not help (long static). |
| Street persons on rear_ptz (Protect leg) | Frigate-2 road mask (09-14, y<0.62) | **Does not run on that leg**: masks are Frigate-only; Protect smart-detect has no mask in URA or Frigate. 6 of 8 rear_ptz sample alerts had no F2 leg within 60 s (the mask worked, Protect did not respect it). |
| Street persons on utilities_ptz, g5_bullet (F2 and Protect) | Frigate road mask | **Does not exist** on these cameras in the 10-09 config. |
| First-sighting street walker at any camera | #7 track-linker coercion | **Design gap**: demotion needs a continuation AND camera_count >= 2 AND pass_by. A lone walker on one camera is a first alert, which is never demoted, and single-camera tracks cannot reach camera_count 2. |
| Any FP of any class | #6 contextual severity | **Too loose by design**: home_day first_sighting is LOW only when `_tracked_persons_count_trusted >= 1`; anything else is HIGH and pages every channel. Whether the house is "occupied" at those moments is not measured here. |
| Animal (front_side dog/coyote #34), weather IR streaks (#31) | none | **Gap**: no label filter at URA (person sensor only), Frigate `person` filter 0.5/0.6 let it through. No per-camera night IR rule. |
| Dup sends | #3 camera-key collapse | Working: audit rows show one logical alert per event, no repeat sends found in the sample. |

## 6. Levers, ranked, building on what exists

Operator ruling to respect: FP mitigation by cross-corroboration, not latency/duration gates (memory reference_frigate_ghost_evidence_chain). Duration is therefore only offered below as a demote-never-silence option, flagged as needing an operator decision.

**Extend an existing gate (preferred)**

1. **U1. Extend the Frigate event handler to carry score, box and zones (REUSE `_on_frigate_event`, perimeter_alert.py:779-815).** It already caches the latest event per camera and the bridge already delivers `after.score/top_score/box/current_zones/stationary` for both hosts (automations.yaml:6578-6595; Frigate fields confirmed at docs.frigate.video/integrations/mqtt). Cache them next to `_frigate_last_event_id` and feed the real score to `linker.observe` (currently 0.0, :3896-3903). Value: gives every other URA lever a score and a position. Effort small. Prerequisite for U3/U4.
2. **U2. Make XCORR-1 burst demote cover 24h (REUSE gate 8).** Flip scope via `PERIMETER_BURST_NIGHT_ONLY=False` or widen `PERIMETER_BURST_NIGHT_WINDOW` (const.py:2481/2491). It already demotes only the 2nd+ isolated alert in 30 min, never the first, never silences. Rung 1 constant (review-gated). Expected effect: back_yard, hot_tub, front_side repeats drop to LOW (companion only). Does not touch the first alert, so a single phantom still pages. Needs a measure-before-build replay of 30 days of audit rows to count how many alerts would have been demoted and confirm none of the genuine ones (pool service 11-04 13:46-14:41 on armcrest/reolink) were repeats of a real person, because repeats on a real visitor would also demote; the linker's approach/circling exemption (gate 5) already shields escalating tracks.
3. **U3. Add a single-engine demote on cameras that have two healthy engines (EXTEND `_evaluate_burst_demotion` sibling check, :2290-2306, with `_recent_fires`).** Observed asymmetry: back_yard/hot_tub FPs are F2-only with Protect silent; rear_ptz/g5 street persons are Protect-only with F2 (masked) silent; g5 true persons had both (3 of 3). Rule: first alert on a camera with live F2 AND Protect legs, fired by only one engine and not corroborated within `_SOLE_FIRE_WINDOW_S=60` after a short settle (needs the existing in-flight wait), demote to MEDIUM/LOW, never silence. This directly contradicts the 2026-09-12 fence only in the first-alert case, so it is an operator decision: the card concluded B-alone is unsafe because ~87% of alerts are single-source; that figure is dominated by cameras with one NVR, which this rule excludes (applies only where both legs resolve). Measure first: of the 30-day alerts, how many on dual-leg cameras were single-engine, and how many of those are real (needs more labelled frames than my 52).
4. **U4. Region gate from the Frigate box (builds on U1; EXTEND, not new).** Per-camera "street band" table as a module constant (reuse the polygons already in the Frigate masks: rear_ptz y<0.62, front_side y<0.46; add utilities_ptz y<~0.38, g5_bullet top-right strip), demoting to LOW when the box bottom-centre lands in it. Helps the Protect leg that Frigate masks cannot reach, but only where a Frigate event exists for the same instant. For Protect-only detections there is no box, so this lever and U3 overlap; prefer U3 for Protect.
5. **U5. Tighten the severity table for first sightings (REUSE const.py:2589).** `home_day` perimeter first_sighting = HIGH when `persons_home == 0`. Verify via the live `_tracked_persons_count_trusted` whether it is 0 at the midday alerts; if so the "HIGH" is a presence-count issue not an FP issue. Read-only check owed.

**Homelab (Frigate-2), no URA code**

6. **H1. Object mask / zone for the road bands** on utilities_ptz (road y < ~0.38) and g5_bullet (top-right sidewalk), same pattern as rear_ptz/front_side (post-inference object mask, comment at config 2026-09-14 says motion mask alone did not stop road detections). Removes street persons from the F2 leg. Cost: none on URA. Does not affect Protect.
7. **H2. Per-camera `objects.filters.person` for back_yard/hot_tub/front_side**: raise `min_score` / `threshold` and set `min_area` (current 0.5/0.6; no `min_area`); add `person` filters on utilities/g5/pool/rear (currently none). The empty frames are low-score model noise, but no score data was available in the DB, so the right numbers need the Frigate event DB (`events.score/top_score`), which I could not read. Needs homelab data.
8. **H3. Re-verify pool_equipment masks against frames #43/#45/#46** (cloth bundle at left wall still visible; 12 night CRIT/HIGH in 7 d after the 10-09 fix). Static, so dwell would not help.
9. **H4. Protect smart-detect**: set camera-level motion zones / ignore the street band on rear_ptz and g5_bullet in the UniFi Protect console (not repo-managed, not verified by me). This is the only lever that removes Protect street persons at the source.
10. **H5. Shadow-edge hypothesis** (back_yard #3/#7/#9 show a hard shadow of the house moving across the lawn): if the box is on the shadow edge, a motion mask will not help, only score filtering will. Needs Frigate event boxes; unverified.

**Interim / last resort (operator decision, new ingredient)**

11. **N1. Escalate-on-persistence**: send the first alert LOW and raise to full severity only if the sensor is still ON after N seconds (true on-property hits sustained 18-28 s in my sample; empties were mostly under 6 s on back_yard/hot_tub). This is a duration gate, which the operator previously rejected (reference_frigate_ghost_evidence_chain). It is a NEW state-machine x time ingredient. Per the marginal-benefit rule, do U1+U2+U3+H1+H2 first and revisit only if the residual remains high.

Ranked order by (impact on count, risk): H1/H2 (zero URA risk, remove street + low-score noise at source) , U2 (existing gate, constant change), U3 (existing gate extension, operator decision), U1 (enabler), U4, U5, H3-H5, N1.

Do not do: a blanket single-source demote on all cameras (card ruling, 87% coverage artifact); URA-side "street zone" without the box (U1 first).

## 7. Storage and archival

| Item | Measure (2026-11-08 ~14:10 local) |
|---|---|
| `/media/ura/snapshots` (URA SNAP-1) | 1781 JPEGs, 250.1 MB (du), oldest 2026-11-01 14:00:14, newest 2026-11-08 13:58 (names carry epoch). ~290-330 files and 35-53 MB/day on full days (11-02..11-05). Mean 140 KB; front_side_ptz files are large (263 KB avg, 128 MB of the 250). Per camera: rear_ptz 629, front_side 486, utilities 206, g5_bullet 131, back_yard 115, pool 85, hot_tub 67, armcrest 38, reolink 24. |
| Retention code | `_async_prune_snapshot_dir` / `_prune_snapshot_dir` perimeter_alert.py:3679/3701; age 168 h, count cap 5000, sweep every 6 h (const.py:2921-2942). **Running**: oldest file is exactly 7 d old, count 1781 << 5000. |
| Volume | `/dev/nvme0n1p8` 457.7 GB, 120.8 GB used (28%), 318.3 GB free; `/config` and `/media` are the same filesystem. |
| `/media/timemachine`, `/media/llmvision` | 476.6 MB, 8 KB. Not URA. |
| **`/config/www/doorbell_alerts`** | **2.3 GB (2,340,228 KB), 5396 files, 3325 older than 30 days, 315 files / 229 MB in the last 7 days.** Written by HA automations (automations.yaml:6064, 6171, 6365), no cleanup found in configuration.yaml. SNAP-1 planning (section 4) says the previous 682 MB pile was purged 2026-08-07; it has regrown. Files are 0.9-1.0 MB each recently. **Web-served under `/local/`** (the exact privacy risk SNAP-1 D4 was written to avoid), and includes "Garage_Doorbell_Vehicle" shots, i.e. street traffic noise from a separate HA-side alert stack. |
| DB growth side note | URA DB 1.49 GB live plus three older backups (929 MB, 944 MB, 1.48 GB) in the same folder: ~4.7 GB. Out of scope, noted. |

Verdict: URA snapshot storage is healthy and bounded (about 250 MB steady state, 0.05% of the free space). No action needed for URA. Archival recommendation (recommendation only, nothing applied):
- Keep 168 h on-box. If you want a longer FP-review corpus, add a **one-line sweep that copies a downscaled (640 px) copy of each snapshot to the NAS/unraid share before prune**, ~40 KB each, ~12 MB/day. Not required for space.
- For `/config/www/doorbell_alerts`: add a retention rule (delete older than 14-30 d via a `shell_command` or a scheduled `find -mtime`) and move the target out of `/www` into `/media` (auth-gated), mirroring SNAP-1 D4. This one is HA-automation scope, not URA code; the freed 2 GB is minor for disk but it removes the public-path exposure. Decision for the operator.
- A dedicated label corpus (a per-alert snapshot path in the audit row) would make the next FP audit mechanical: `notification_log` has no snapshot path column, so I had to join by camera + epoch. A new column or a `snapshot_path` field in the audit message is a cheap, low-risk addition (Producer/consumer: producer is `_note_capture` :3661, consumer would be audits only).

## 8. What I could not verify

- The live Frigate-2 config (I used the 10-09 repo snapshot); live scores/boxes from the Frigate event DB; Protect smart-detect zone settings; the exact severity the house state gave at each midday alert; whether frames #35/#36 contain a person.
- Empty frames could still hide a very small distant person; the tiles are downscaled to 640 px and the detect stream is 1280x720.
- The 7-day recorder read was `immutable=1`, so the most recent minutes may be missing.
- Per-camera rates carry n=3-9 uncertainty. The recorder duration and alert counts are exact.

Falsification I checked: the claim "back_yard/hot_tub FPs are Frigate-2-only" would be disproved by high Protect agreement. Measured: back_yard F2 114 ONs, Protect agrees on 6; hot_tub F2 65, Protect agrees on 6. The claim "street persons come through Protect": rear_ptz 6 of 8, g5 2 of 2 sampled had no F2 leg within 60 s; but overall rear_ptz Protect/F2 agreement is 33 of 44 (F2 ONs corroborated), so the Protect-only rule will not be clean, it needs the labelled replay in U3.

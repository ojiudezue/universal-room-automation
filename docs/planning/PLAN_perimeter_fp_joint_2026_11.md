# Joint plan: perimeter false positives and street noise (URA + HomeLab), 2026-11-08

**Card:** PERIMETER-FP-STREET-NOISE-1. **Status:** PROPOSED. Nothing changes until the operator approves.
**Inputs:**
- URA audit `docs/planning/AUDIT_perimeter_fp_street_noise_2026_11.md`: 30 days of alerts, 52 snapshots viewed.
- HomeLab inventory `homelab-automation/logs/frigate2-perimeter-2026-11-08/INVENTORY.md`: live Frigate 0.18.2
  config plus a current frame per camera.

## What we know
- **Volume:** about 56 person alerts a day; 95% fall in the daytime, outside 23:00–05:00. Only 25 of 1,696 were ever demoted.
- **Three kinds of false positive:**
  1. **Empty frames, Frigate 2 only:** back_yard (437 alerts in 30 days, 100% noise in the sample),
     hot_tub (305, 83%), front_side_ptz (97).
  2. **Static phantom despite the Oct 9 masks:** pool_equipment (52, 75%).
  3. **Real people on the street or sidewalk:** utilities_ptz (178), g5_bullet (205), rear_ptz (205). These are
     mostly Protect-only, plus the cameras that have no masks at all.
- **Prior tuning to build on:**
  - Frigate road masks on front_side_ptz and rear_ptz. They only hold at the parked view.
  - Static-object masks on back_yard, hot_tub, pool_equipment and ReolinkPatio (Oct 9–15).
  - URA's XCORR-1 burst demote, which only runs at night, and the track linker.
- **Gaps:**
  - **Frigate:** no zones on any camera, so `required_zones` is empty for alerts and snapshots. `min_area` is 0
    everywhere. Seven street-facing cameras have no masks at all.
  - **URA:** reads only label, camera and id from Frigate events, never score, box or zones, although HA's
    bridge automation already forwards them. The single-source demote planned in XCORR-1 was never built.

## Plan: four phases, cheapest and most reversible first

### Phase 1: Frigate zones and filters (owner: HomeLab, config only, revert = restore backup)
Back up the live Frigate config first. Draw the zones on the current frames in the inventory folder.
1. **Add a `property` zone and require it for alerts and snapshots.** Set `review.alerts.required_zones: [property]`
   and `snapshots.required_zones: [property]` on every street-facing camera. A person on the road can still be
   detected and recorded, but no alert or snapshot fires unless they enter the property polygon. Polygons from
   the frames:
   - **utilities_ptz:** the zone is below the rock edging (about y > 0.42). The gravel road at y ≈ 0.33–0.40 and
     the far bank are excluded. Parked view only.
   - **g5_bullet:** the driveway and front lawn. The street and sidewalk in the top-right corner
     (x > 0.6, y < 0.2) are excluded.
   - **front_door_aerial, madrone_g6_entry, doorbell_lite, rear_ptz, front_side_ptz:** each zone ends at the
     property line. On rear_ptz and front_side_ptz this sits alongside the existing road object masks.
   - **Garages, Study B porch, back_yard, hot_tub:** no street in view, so no required zone. Use step 2 instead.
   - **Also on utilities_ptz and g5_bullet:** object masks on the road band and the sidewalk strip. This is the
     method that took the PTZ road events to 0. Draw these polygons from where the bottoms of recent detection
     boxes actually fall, not by eye (HomeLab).
2. **Size and score filters for the empty-frame cameras.** On back_yard, hot_tub and front_side_ptz:
   - Raise the person `min_score` to 0.6.
   - Set `threshold` to 0.72–0.75. back_yard and hot_tub currently sit at 0.6, below the 0.7 default.
   - Set `min_area` to about 1,500–2,500 px at 1280×720, per camera, from the box sizes of real detections.
   - **front_side_ptz:** if its empty frames come from roaming off the parked view, the masks no longer line up. A
     return-to-home position matters more there than filters.
3. **pool_equipment:** the Oct 9 masks are live (2 object masks and 1 motion mask). The phantom that remains means
   either a different static spot, or masks that don't cover the bottom-center of the detection box. HomeLab checks
   the object coordinates on audit frames #43, #45 and #46 and extends the mask.

**Why first:** the noise is stopped at its source, and no URA code changes.
**Measure:** seven days later, alerts per camera against the 30-day baseline in the audit. Spot-check 10 snapshots per
camera so that real visitors still alert.
**Risk:** a polygon drawn too tight could miss a real person at the edge of the property. That is why zones end at
the property line, not the driveway, and why the spot-check is in the measure step.

### Phase 1b: point URA at the zone sensors (owner: URA; config first, code only if needed)
**HomeLab review finding, verified in URA code:** `required_zones` gates Frigate's own review alerts and
snapshots. It does not gate the camera-level `binary_sensor.<cam>_person_occupancy`, which still counts a
person standing on the street. URA's perimeter alert triggers on those camera-level sensors
(`perimeter_alert.py:431-519`, engine detection by the `_person_occupancy` suffix). `frigate_events` is only
used to attach the snapshot. **So Phase 1 on its own does not quiet URA's pushes.**

Fix:
1. **Name zones per camera** (`utilities_property`, `g5_property`, `rear_property`, and so on). Frigate merges
   same-named zones across cameras into one entity, so a shared "property" zone would break this.
2. **Point URA's perimeter camera inputs** at the per-zone sensors
   (`binary_sensor.<cam>_property_person_occupancy`) for the street-facing cameras.
   - Before switching, verify that URA's engine detection, `_2` sibling pairing and cross-NVR logic resolve a
     zone sensor to its camera.
   - If they don't, the code change is small: map the zone sensor to its camera.
   - Revert: restore the previous camera list.
3. Phase 3.2 (Frigate zone agreement from the `frigate_events` payload) stays the fallback for cameras
   where zone sensors can't be used.

**Geometry corrections from HomeLab** (frames from 2026-11-08):
- **utilities_ptz:** the rock edging slopes, so the zone is the polygon `0,0.47 0.5,0.43 1,0.41 1,1 0,1`. It also
  excludes the berm and treeline phantoms.
- **g5_bullet:** the zone is everything below the diagonal `0.55,0 → 1,0.22`, so the driveway mouth stays in.
  Exclude the top strip (y < 0.07), which holds the timestamp overlay and the eave.
- **min_area:** about 70% of the smallest real person box at the farthest point of the property worth caring
  about, taken from the Frigate events API at 1280×720. Expected about 1,500–3,000 px on back_yard and hot_tub.
  Then set threshold to 0.75.
- **PTZ cameras** (front_side_ptz, rear_ptz, and utilities_ptz if it roams): zones and masks only line up at the
  parked view. Add a return-to-home preset, or confirm they stay parked.
- **Applying Phase 1:** one Frigate restart (about 1 minute). HomeLab backs up the config first and verifies every
  camera afterwards.

### Phase 2: Protect street band (owner: HomeLab, or the operator in the UniFi UI; revert = remove the zone)
On rear_ptz and g5_bullet, set a Protect smart-detect zone or exclusion zone that leaves out the street and
sidewalk band. This is the only fix that reaches the Protect-only street walkers. The Protect integration API does
not expose zones, so the current setup has to be read, and the change made, in the Protect UI. Either the operator
does it, or HomeLab does it with the operator's OK.

### Phase 3: URA interim gates before an alert (owner: URA; Tier 2 with reviews; knobs default to today's behaviour)
1. **Use the data URA already receives.** Extend the Frigate event handler (`perimeter_alert.py:779-815`) to
   cache score, box and zones from the bridge payload, and give the track linker the real score instead of 0.0.
   This changes no behaviour on its own; it is the input for the steps below.
2. **Frigate zone agreement.** When a camera has a Frigate `property` zone and the event is outside it, demote the
   alert to LOW. That catches Protect-only street walkers through the camera's Frigate leg. Knob: on/off,
   default off at ship.
3. **Run the burst demote all day instead of 23:00–05:00.** This is a constant change (`const.py:2481/:2491`) and
   never demotes the first alert. Before shipping, replay the 30 days of alerts to show the alerts it would have
   demoted and confirm none were real visitors.
4. **Demote single-source first alerts: APPROVED by the operator 2026-11-08 (relaxes the 2026-09-12 fence).** On
   cameras with live Frigate 2 and Protect legs, demote a first alert that only one engine raised.
   - **One system-wide setting, not per camera** (operator). A Switch entity, default off, turned on for this house.
   - **Eligibility is automatic, per camera.** The demote applies only while BOTH legs for that camera are live and
     reporting. If either leg goes down it switches off for that camera, so alerts revert to today's behaviour.
   - **Capability parity gate.** It applies only on cameras where the two engines mostly agree on real events,
     measured per camera. back_yard had 116 Frigate person detections vs 4 Protect in the week to 11-08, so it
     does not qualify until Protect detection there is fixed (Phase 2).
   - **Single-NVR homes:** never applies. Their noise is handled by Phases 1, 3.1–3.3 and image checks.

LOW means quiet: it is logged and shown on the dashboard, with no push. Nothing is dropped.

### Phase 4: storage (owner: URA for the folder, and whoever owns the doorbell automation)
- **URA snapshots:** no action. 250 MB with 7-day retention working, and 318 GB free.
- **Frigate 2:** no action. 9.2 TB free on Unraid. Alerts and detections are kept 14 days, continuous recording
  5 days, at about 1.2 TB a day across all cameras. There is no archive, and that is fine for review clips.
- **`/config/www/doorbell_alerts`:** fix this one. It holds 2.3 GB in 5,396 files, 3,325 of them older than 30 days,
  with no cleanup. It is publicly reachable under `/local/` without auth, and it sits inside every HA backup,
  adding 2.3 GB to each. HA's own automations write it: `doorbell_detection_whatsapp_alert` and/or
  `g6_doorbell_analysis`. HomeLab does not own them. Proposal:
  1. Point the doorbell automation at `/media/doorbell_alerts`.
  2. Add a 30-day retention: a daily cleanup in the automation or a shell command, with the age as a knob.
  3. Move or delete the existing files, with operator OK on what is kept.
  4. Optionally copy anything worth keeping to the Unraid share.

## Order and checkpoints
1. Phase 1 plus Phase 1b (together, otherwise URA's pushes don't change) plus Phase 2, then seven days of measurement. Report alerts per camera before and after, plus the
   snapshot spot-check.
2. Phase 3.1–3.3, built and reviewed in parallel with the Phase 1 measurement. They ship after it, so their effect
   is measured on top of Phase 1.
3. Phase 3.4 only if street noise is still high after that.
4. Phase 4 can go at any time; it is independent.

**Each phase needs the operator's OK before anything changes.**

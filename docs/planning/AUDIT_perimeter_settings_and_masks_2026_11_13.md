# AUDIT: perimeter settings, config-flow parity, single-source shadow, Frigate masks (2026-11-13)

Read-only probe, run 2026-11-13 11:44-11:55 CST (HA was mid-restart at 11:44; /api/states answered with 570 entities by ~11:48). Nothing changed in HA, Frigate or Protect. Frigate was not logged into. HVAC/presence state-of-play docs not read (not relevant). Not committed.

## Answers first
1. "Perimeter AI Person Check" is `select.ura_perimeter_vlm_gate` (a select, not a switch), on the "Universal Room Automation" integration device, state `off`. It is a URA feature (PERIMETER-FP D6), not an HA automation.
2. Of the 7 settings, 5 have no options/config-flow field and no flow translation: the 4 perimeter switches and the AI check. Only Presence Face Matching and Name People at Doors have flow fields.
3. The shadow data you asked me to count does not exist anywhere: gate decisions are in memory only, one last decision per gate per camera, and the attribute is excluded from the recorder. Proxy reconstruction from the recorder: only g5_bullet is currently eligible; of 18 g5_bullet would-demote candidates in 7 days, 16 are street and **2 are own property (key risk)**, one a real person at the garage at night.
4. Homelab reports (vibememo 117, CONFIGS.md:491, commit 7ecaa64, 2026-11-08 19:24 CST) that object masks on utilities_ptz road and g5_bullet street plus `<cam>_property` zones were applied on 11-08, and rear_ptz zone added. The coordinates were not recorded in any repo doc, and the data suggests the g5 mask is not holding. Proposed polygons below.

## 1. "Perimeter AI Person Check"

- Entity: `select.ura_perimeter_vlm_gate`, friendly name "Perimeter AI Person Check", options `['off','shadow','enforce']`, state `off`, last_changed 2026-11-13T17:44:41Z (boot restore). Live read via /api/states.
- Registry: platform `universal_room_automation`, device_id `61e84be21633...`, the device named "Universal Room Automation" (identifiers `('universal_room_automation','integration')`), same device as the switches. (`.storage/core.entity_registry`, `core.device_registry` via ssh ha.)
- Defined: `select.py:1178-1203` (`PerimeterVlmGateSelect`, `_attr_name = "Perimeter AI Person Check"`, entity_id pinned `select.ura_perimeter_vlm_gate`). Key `perimeter_vlm_gate`, default `off`: `const.py:2641-2648`. Trusted tiers `("frigate_event",)`: `const.py:2651`. Stored option: no `perimeter_vlm_gate` key in the integration entry's options (`core.config_entries`), so it is on the default.
- Behaviour, from code:
  - Consumer: `perimeter_alert.py:1783-1796`, person path, runs between snapshot resolution and the notification dispatch. `off`: calls `enrich_dispatched_alert` with the normal descriptive prompt (today's behaviour). `shadow`/`enforce`: calls `enrich_with_verdict` (`perimeter_enrichment.py:263-292`), whose prompt asks the vision model for a first line `PERSON: YES|NO|UNSURE` then a one-to-two-sentence description (llmvision `image_analyzer`, model gpt-4o-mini, live options).
  - Gate: `_apply_vlm_gate`, `perimeter_alert.py:4920-4957`. `would_demote` only if verdict is exactly NO, the snapshot tier is `frigate_event`, and the classification-transition exemption does not shield it. Parse failures, timeouts, empty text, any exception give UNSURE, so no demote (`perimeter_fp_gates.py:47-70`, `perimeter_enrichment.py:289-292`).
  - ON vs OFF for an alert: `off` = nothing changes, alert keeps its severity. `shadow` = decision recorded, severity unchanged (the AI still runs and the description is still attached). `enforce` = a `PERSON: NO` on a Frigate-event frame lowers the alert to LOW (`_demote`, line 4745; LOW means logged and shown on the dashboard, no push per PLAN_perimeter_fp_joint line 128). Protect-sourced snapshots are never demoted by this gate.
- Related but different: AI descriptions (`perimeter_enrichment_enabled`) is live ON (options) and has a flow field ("AI descriptions", `config_flow.py:5259`, en.json:925). 103 alerts in the last 7 days carry route_reason `enriched_llmvision`, 2 `enrichment_failed_fall_through` (`notification_log`). The VLM gate is a separate select layered on it.
- Fire check: no decision data is persisted (section 3), the select has been `off`, so it has never run a verdict prompt in this install. Unknown whether any `PERSON: NO` would be produced.

## 2. Config-flow parity (switches on the "Universal Room Automation" device)

Switches created by `_IntegrationOptionsSwitch` (`switch.py:210-271`, class `switch.py:615`), live states from /api/states 2026-11-13 ~11:48:

| Entity (friendly name) | conf key | Live | Options/config-flow field? |
|---|---|---|---|
| switch.ura_presence_face_matching (Presence Face Matching) | `face_recognition_enabled` | on | YES: `config_flow.py:5012` (camera_census step; en.json:869/878) |
| switch.ura_name_people_at_doors (Name People at Doors) | `egress_identity_enabled` | on | YES: `config_flow.py:5026` (en.json:871/880) |
| switch.ura_perimeter_zone_agreement_demote (Quiet Off-Property Alerts) | `perimeter_zone_agreement_demote` | off | NO. Only `switch.py`, `perimeter_alert.py:4733`, `__init__.py:7817` (reload-suppress set), strings/en.json switch description |
| switch.ura_perimeter_single_source_demote (Quiet Single-Camera-System Alerts) | `perimeter_single_source_demote` | on | NO (same places; `perimeter_alert.py:4793`) |
| switch.ura_perimeter_egress_known_xcorr_gate (Door Alerts Only for Strangers) | `perimeter_egress_known_xcorr_gate` | on | NO (`perimeter_alert.py:5184`) |
| switch.ura_perimeter_identity_followup (Door Alert Name Follow-Up) | `perimeter_identity_followup` | on | NO (`perimeter_alert.py:5285`) |
| select.ura_perimeter_vlm_gate (Perimeter AI Person Check) | `perimeter_vlm_gate` | off | NO, and no `perimeter_vlm_gate` text in strings.json or translations/en.json at all (name is hardcoded `select.py:1202`) |

Gaps: 5 of 7 (all PERIMETER-FP). Method: grep of `config_flow.py` (the only flow file; no `options_flow*.py` exists, the options flow is `UniversalRoomAutomationOptionsFlow` at `config_flow.py:3906`), `strings.json`, `translations/en.json` for each conf key and constant. Also noted: `DomainCoordinatorsSwitch` (same device) is a different class and was not assessed. Flow saves merge existing options (`config_flow.py` camera_census step `data={**self._config_entry.options, **cleaned}`), so adding fields later will not clobber switch-written values.

## 3. Single-source shadow check

### 3a. Where decisions persist: nowhere
- `_record_gate` (`perimeter_alert.py:4594-4600`) writes `self._last_gate_decisions[cam][gate]` only: an in-memory dict, last decision per gate per camera, lost on restart (HA restarted 11:44 today).
- It surfaces via `gate_decision_stats()` (`perimeter_alert.py:4602`) into the diagnostic sensor `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` (`sensor.py:4587-4588`), and `gate_decisions_by_camera` is explicitly in `_unrecorded_attributes` (`sensor.py:4449-4453`). Checked: the sensor's last recorder row has no gate fields.
- Not in `anomaly_log` (0 rows with `single_source` in context_json or `gate` metric), not in `memory_episodes` (0 gate/perim episode types; `exterior_track` episodes exist, no gate field), not in `notification_log` (route_reason values in 7 days: `force_immediate_security_image`, `enriched_llmvision`, etc.; none gate-related). No journal, HA log keeps nothing of it (`home-assistant.log.old` is from Nov 2025).
- So "count would_demote per camera for 7 days" cannot be answered from recorded decisions. This is itself a finding: shadow mode produced no durable evidence. (Suggested card: persist each gate decision as a row, or at least count per camera, with a zero-fire trip-wire. Not built.)

### 3b. Proxy reconstruction (recorder + snapshots)
Method: recorder `states` (ON edges, 7 days) for `binary_sensor.<cam>_person_detected` (Protect) and `_person_occupancy_2` (Frigate-2) on g5_bullet, utilities_ptz, rear_ptz. A would_demote candidate = first ON of a cluster after 30 min quiet (`PERIMETER_BURST_WINDOW_S=1800`, `const.py:2566`) with no other-family ON within -60 s..+8 s (`_SOLE_FIRE_WINDOW_S=60`, `perimeter_alert.py:2276`; `PERIMETER_SS_SETTLE_S=8`). This ignores the gate's other inputs, so it is an upper-bound proxy. Eligibility today from `.storage/universal_room_automation.perimeter_agreement` (rate must be >= 0.6 with >= 20 samples, `const.py:2637-2638`): g5_bullet 28/41 = 0.683 ELIGIBLE; rear_ptz 13/32 = 0.406 not; utilities_ptz 8/10 = 0.8 but 10 samples < 20, not; hot_tub 9/9 but 9 samples; pool_equipment 5/9; back_yard 0/4; front_side_ptz 4/4. So only g5_bullet could demote right now (and the switch is ON since ~10:00 CT).

| Camera | clusters (7 d) | solo candidates | eligible now? |
|---|---|---|---|
| g5_bullet | 47 | 18 (7 Frigate-only, 11 Protect-only) | yes |
| rear_ptz | 39 | 29 (6 F2-only, 23 Protect-only) | no (0.406) |
| utilities_ptz | 18 | 10 (3 F2-only, 7 Protect-only) | no (10 samples) |

Classification from snapshots in `/media/ura/snapshots` (viewed all 18 g5 and all 10 utilities candidate frames; epochs from filenames):
- **g5_bullet: 16 street, 2 own property.**
  - OWN PROPERTY 1: epoch 1794119481 (2026-11-08 00:31 CST, night): a person standing in the driveway near the garage/car, Protect only (no F2 ON within 5 min). This is the key risk: it would have been demoted to LOW had the switch been on.
  - OWN PROPERTY 2: epoch 1794230682 (2026-11-09 07:24 CST): two people walking on the driveway (one boxed by Frigate). Protect ON 1794230682, F2 ON 1794230691 = +9 s, one second outside the 8 s settle window, so this was a near-miss, not a corroboration. A slower F2 would be demoted.
  - STREET (16): 1793987983, 1793997911, 1794060819, 1794163878, 1794320136, 1794322043, 1794331489, 1794333680, 1794340443, 1794350809, 1794360276, 1794405716, 1794507297, 1794523473, 1794527515, 1794538260. People, dogs and a cyclist on the road/sidewalk at the top-right of frame (feet x 0.72-0.98, y 0.03-0.14).
- utilities_ptz: 10 of 10 road pedestrians or a car on the far road (feet y 0.28-0.36); 0 own property.
- rear_ptz: 29 candidates, not eligible so not demotable now. Not viewed; the 11-13 audit already classified rear_ptz Protect-only alerts as mostly street.
- Falsification: the own-property claim is falsified if either frame is not own property (I saw both; #1 a person in the driveway at night, #2 two people on pavers). The "would demote" claim is a proxy: `memory_episodes`/notification rows cannot confirm the gate state at that time. Eligibility at the time of those events is unknown (the agreement rate then may have been below 0.6).
- Caveat on severity: since the switch went ON, 0 perimeter_alert rows with LOW/non-CRITICAL/HIGH severity exist after 2026-11-13 15:00Z (`notification_log`). That is expected only if no would-demote has occurred since ~10:00 CT; it does not prove the gate is wired.
- Action for the operator: with `switch.ura_perimeter_single_source_demote` ON, an own-property Protect-only first alert on g5_bullet (Protect fires, F2 later than 8 s or absent) would be silenced to LOW. 2 of 18 candidates in 7 days were such events. Options (not applied): turn it off until decisions are persisted, or raise `PERIMETER_SS_MIN_AGREEMENT` for g5 (rate 0.683 sits only 0.083 over 0.6).

## 4. Frigate masks: planned vs reported applied

Read: `docs/planning/PLAN_perimeter_fp_joint_2026_11.md` (whole), `AUDIT_perimeter_fp_street_noise_2026_11.md`, `AUDIT_perimeter_path_alert_2026_11_13.md`, `AUDIT_protect_zone_additions_2026_11_13.md`, `PLANNING_perimeter_fp_build_2026_11.md` (grep), homelab repo `/Users/okosisi/Code/homelab-automation`: `.vibememo/.../117_frigate2_perimeter_fp_phase1.json`, `docs/CONFIGS.md:491`, commit `7ecaa64` (2026-11-08 19:24 CST), `logs/frigate2-perimeter-2026-11-08/INVENTORY.md` and frames.

Planned (joint plan, 2026-11-08):
- Phase 1 (homelab, Frigate): per-camera `<cam>_property` zone required for review alerts and snapshots (plan lines 31-41); object masks on road band and sidewalk strip on utilities_ptz and g5_bullet (lines 42-44); geometry corrections lines 80-84: utilities zone `0,0.47 0.5,0.43 1,0.41 1,1 0,1`; g5 zone is everything below diagonal `0.55,0 -> 1,0.22`, exclude top strip y < 0.07. rear_ptz: existing road mask (y < 0.62, added 2026-09-14, motion plus object) stays, zone added (line 39). No Frigate zones/masks existed on g5/utilities before (INVENTORY.md:23-24 "motion 0, object 0").
- Phase 1b (URA): point URA at `binary_sensor.<cam>_property_person_occupancy` (config field `perimeter_zone_sensors`, `const.py:2596`).
- Phase 2 (operator, Protect UI): street exclusion zones on rear_ptz and g5_bullet. The 11-13 audit says rear_ptz was done by the operator; g5_bullet and utilities_ptz still open.

Reported applied (homelab vibememo 117, 11-08): "`<cam>_property` zones ... on utilities_ptz, g5_bullet, rear_ptz, front_side_ptz, front_door_aerial, madrone_g6_entry, doorbell_lite ... Object masks: utilities road, g5 street, pool hose/pump and brick pile, hot_tub patio chairs ... All geometry is from 30 days of box bottom-centres." Backup `config.yaml.bak-pre-perimeter-fp-2026-11-08` on F2. The repo holds only the PRE-change resolved config (`configs/snapshots/frigate2/config-resolved-pre-perimeter-fp-2026-11-08.json`), so the exact applied polygons are NOT recorded in any repo doc. rear_ptz: the 09-14 road mask (y < 0.62, `CONFIGS.md:417`) is the only confirmed rear_ptz Frigate mask; the 11-08 entry adds a rear_ptz zone but no new rear_ptz object mask.

Live evidence the Frigate side is not fully working (recorder + snapshots, after the 11-08 19:24 CST apply; cutoff epoch 1794187440):
- Zone sensors exist live: `binary_sensor.{g5_bullet,utilities_ptz,rear_ptz,front_side_ptz,front_door_aerial,madrone_g6_entry,doorbell_lite}_property_person_occupancy` all `off` (/api/states). URA is NOT pointed at them: the integration entry options have no `perimeter_zone_sensors` and `perimeter_enrichment_person_sensors`/cameras are still camera-level (`core.config_entries`). So Frigate `required_zones` does not reach URA's alerts (plan Phase 1b not done).
- g5_bullet F2 camera-level ONs still fire: 55 after cutoff (28 before, but the windows differ in length; do not read as a rate change). Five F2-first clusters after the cutoff are street walkers with a Frigate box in the top-right (11-10 13:54, 16:46, 19:24; 11-12 12:14, 20:50). The g5 street mask therefore either is not in the live config, does not cover feet y ~0.03-0.14 at x 0.72-0.98, or tracks boxes whose bottom-centre fall outside it. Unknown which (live F2 config not readable without credentials; homelab to dump it).
- utilities_ptz F2 ONs after cutoff: 17 (11 clusters). All 11 snapshots show road pedestrians, a pickup, or a mower on the far road, none on the near lawn. Two Frigate frames (11-12 09:50 and 13:57 CST, with person box bottoms at y ~0.46-0.50) show a DIFFERENT view: tree line higher, road lower (road at y 0.42-0.55) than the 11-08 parked frame (road y 0.33-0.40). Interpretation: the PTZ is not at its parked/home position on 11-12, so a pixel-anchored mask drawn for the 11-08 view would not cover the road in that view. Unverified: Protect preset history. This is the "if it roams" risk the plan flagged (plan line 88).

### 4a. Proposed Frigate masks (PROPOSALS for the homelab session; nothing applied)
Frame reference: homelab frames `logs/frigate2-perimeter-2026-11-08/g5_bullet.jpg` and `utilities_ptz.jpg` (1280x720 detect frame) and 28 URA snapshots. Coordinates normalized 0-1, x right, y down. Frigate masks work on the box bottom-centre. Use `objects.mask` (post-inference, blocks the object) as in homelab vibememo 081; a motion mask alone does not block detection (081). A person-only variant is `objects.filters.person.mask` (keeps cars, e.g. delivery vehicles; homelab decides). Format: Frigate 0.17 used comma-separated flat `x,y,x,y,...` strings; 0.18 migrates to named mappings with `enabled`/`friendly_name` (CONFIGS.md:357). Homelab should match whatever the live 0.18.2 config already uses.

**g5_bullet** (road, sidewalk and neighbour verge, top-right). Evidence: street feet at (0.72,0.03), (0.84,0.12), (0.87,0.10), (0.90,0.05), (0.98,0.08); own-property people at (0.45,0.10) night and (0.75,0.55-0.68), so the mask must stop right of x~0.52. Primary (follows the plan diagonal with a small margin, traces the road-side of the rock/drain line in the frame):
```
cameras.g5_bullet.objects.mask:
  - 0.52,0,1,0,1,0.24,0.90,0.17,0.80,0.12,0.68,0.075,0.58,0.04
```
Plan-exact alternative (simpler, slightly looser at x 0.8-0.9): `0.55,0,1,0,1,0.22`. Optional top strip for the overlay/eave (object bottoms there are never a person): `0,0,1,0,1,0.04,0,0.04`. Do NOT extend below the line or left of x 0.52: the driveway mouth and the 11-08 00:31 night person at (0.45,0.10) must stay live. Check: boxes at feet y > line value at that x (e.g. x 0.84: 0.133) stay unmasked; my feet readings are +/-0.02, so the margin at x 0.8-0.9 is thin; homelab should place the final points from box bottom-centres (as in 081/117), not from this proposal.

**utilities_ptz** (far gravel road, bank, treeline, neighbouring strip at right edge). Evidence: road walkers' feet at y 0.28-0.36 (far bank y~0.27 at night), verge y 0.38-0.40, rock edging y ~0.40 (right) to 0.45 (left) in the 11-08 frame; near lawn empty in every frame.
```
cameras.utilities_ptz.objects.mask:
  - 0,0,1,0,1,0.42,0.5,0.44,0,0.48
```
This is the plan polygon (`0,0.47 0.5,0.43 1,0.41`) with 1 point of margin. Constraint: valid only at the 11-08 parked view; on 11-12 the view differed (above). Homelab should first confirm/return the PTZ to its home preset, or the mask will miss the road (road y 0.42-0.55 in the 11-12 view).

Not proposed here: rear_ptz (existing y < 0.62 mask retained; needs the Protect-side zone, which is the operator's).

## Not verified
- Live F2 config (masks, zones, formats) and live Protect zones: not readable.
- Whether the g5 object mask exists live: the evidence is indirect (street boxes tracked after 11-08).
- Gate state, agreement rate, and Protect/F2 liveness at each historical timestamp, so 3b is an upper-bound proxy.
- Whether the 11-12 utilities view change is a preset change, a roam, or a stream change.

## Files
- This report: `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_perimeter_settings_and_masks_2026_11_13.md`
- Code: `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/select.py:1178`, `.../switch.py:210-271,615`, `.../perimeter_alert.py:1783,4594,4780-4850,4920`, `.../perimeter_enrichment.py:263`, `.../sensor.py:4449`
- Joint plan: `/Users/okosisi/Code/universal-room-automation/docs/planning/PLAN_perimeter_fp_joint_2026_11.md`; homelab: `/Users/okosisi/Code/homelab-automation/.vibememo/users/ojiudezue/entries/117_frigate2_perimeter_fp_phase1.json`, `/Users/okosisi/Code/homelab-automation/docs/CONFIGS.md:491`
- Scratch (contact sheets): `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/out/`

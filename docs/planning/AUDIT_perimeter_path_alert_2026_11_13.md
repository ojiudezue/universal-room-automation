# AUDIT: perimeter alert "person walking along a path" (rear_ptz, 2026-11-13)

Read-only probe, run 2026-11-13 ~11:05 CST. Nothing changed. Read first: AUDIT_perimeter_fp_street_noise_2026_11.md, PLAN_perimeter_fp_joint_2026_11.md. I did not read the HVAC/presence state-of-play docs (not relevant).

## Answer first
The alert was a real pedestrian on the street/sidewalk across from the lot, seen by the **Protect** leg of rear_ptz. Every mechanism that was supposed to tune street noise out is either Frigate-only (road mask, which cannot affect a Protect detection) or shipped but switched off in the live options. Nothing is a code bug. The operator's belief ("road is masked") is true only for the Frigate-2 leg; the Protect leg has no mask/zone, and the Phase 2 (Protect street band) and Phase 1b/3 knobs from the 11-08 joint plan have not been applied.

## The alert (notification_log, URA DB via ssh ha sqlite3)
| Field | Value |
|---|---|
| Time | 2026-11-13 08:56:16 CST (14:56:16 UTC); dispatched 14:56:20-21 UTC |
| Camera / sensor | rear_ptz, `binary_sensor.rear_ptz_person_detected` (on 14:56:16, off 14:56:50, recorder) |
| Source | **Protect** (no `_2` suffix = Protect leg). No `binary_sensor.rear_ptz_person_occupancy_2` (Frigate-2) edge in 14:54-14:59 UTC, so Protect-only. Description text is from **llmvision enrichment** (gpt-4o-mini) |
| Severity | CRITICAL on pushover, companion, whatsapp, imessage (ids 26859-26862, audit row 26863) |
| Route | `route_reason=enriched_llmvision`, `bucket_outcome=accepted`, `matrix_branch=legacy_fallback`, recipient person.oji_udezue |
| House state | `away` since 14:36:45 UTC (house_state_log id 8639, census_update); CRITICAL follows from away in the contextual severity table (const.py ~2589 per prior audit) |
| Snapshot | `/media/ura/snapshots/rear_ptz_1794581776_0feb7c.jpg` on HA (epoch 1794581776 = 14:56:16 UTC exactly). Pulled to scratchpad `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/p/rear.jpg` and viewed |
| Event id | none (Protect leg; no Frigate event). Ack at 17:00:33 UTC (safeword ack) |

Snapshot: a woman walking on the **road/sidewalk across the street** (mid-frame, y ~0.45-0.55), in front of the neighbouring house. The foreground path/lawn is the operator's own property and is empty. The VLM text "walking along a path in front of a house" described the neighbour-side scene. The VLM never said road/street; no verdict line is surfaced (gate off, see below).

## Why it was not filtered
Producer: Protect smart-detect `person_detected` ON edge -> `_on_perimeter_event` -> severity table -> gates -> dispatch (perimeter_alert.py). Consumers: NM channels.

| Control | Applies to this alert? | Evidence |
|---|---|---|
| Frigate-2 road object/motion mask on rear_ptz (y < ~0.62; added 2026-09-14) | **No.** Frigate-only; the Protect leg never passes through it | AUDIT_perimeter_fp_street_noise sections 1, 5 ("masks are Frigate-only; Protect smart-detect has no mask in URA or Frigate"; 6 of 8 rear_ptz sampled street alerts were Protect-only, same as this one) |
| Protect smart-detect zone / exclusion zone on rear_ptz | **Does not exist** (Phase 2 of PLAN_perimeter_fp_joint is operator/UniFi-UI action, status PROPOSED). The Protect API does not expose zones, so URA cannot read or enforce them | PLAN_perimeter_fp_joint_2026_11.md:93-98; no zone data in URA |
| URA zone sensors (D1) | **Off.** `perimeter_zone_sensors` absent from live options (core.config_entries, URA entry, read 2026-11-13); grep of options for zone/single/demote/verdict keys returned only enrichment keys | const.py:2596 |
| D3 zone-agreement demote | **Off** (default False, key unset) and needs a cached Frigate event, none existed | const.py:2627-2630; perimeter_alert.py:1589 |
| D5 single-source demote | **Off** (default False, key unset). This alert is exactly its target case (Protect-only first alert on a dual-NVR camera). Runs in shadow only | const.py:2632-2633; perimeter_alert.py:1595-1600, 4793 |
| D6 VLM person verdict gate | **Off** (default). Also only demotes on `PERSON: NO`, never on "person is on the street" | const.py:2641-2651; perimeter_alert.py:4938 |
| XCORR-1 burst demote | Does not run: night-only (23-05) and the first alert is never demoted | const.py:2577 |
| Contextual severity | Escalated, not demoted: house `away` -> CRITICAL, all channels | house_state_log 8639 |
| URA consumption of zone/box | The alert path reads no zone info from Protect (none is delivered). Frigate zone/box is cached (perimeter_alert.py:4376) but irrelevant to a Protect-only edge | perimeter_alert.py:4376, 1589 |

Frigate side (stale-copy caveat): `/Users/okosisi/ha-config/www_moved_2026-11-13/frigate.yml` is the old Frigate-1 config (rear_ptz at :461, `rtspx` Protect-sourced streams); Frigate 1 is retired (memory reference_frigate1_retired_2suffix_permanent), so it says nothing about the live F2 config. Live F2 config was not readable without credentials; I used the 11-08 HomeLab INVENTORY via PLAN_perimeter_fp_joint. Whether Phase 1 (F2 `required_zones`) was applied since 11-08 is **unknown**, but it would not change this Protect-only alert anyway (plan line 66: "Phase 1 on its own does not quiet URA's pushes").

Falsification: claim "Protect-only" would be disproved by an F2 `_2` ON near 14:56; recorder query for `binary_sensor.rear_ptz_person%` 14:54-14:59 UTC returned only the Protect sensor on/off. Claim "street, not property" is from one frame (viewed); one sample, but consistent with the 11-08 audit's 8/8 rear_ptz street frames.

Repeat context: 11-12 to 11-13 there were 7 more rear_ptz alerts (HIGH, companion), mostly Protect, same population.

## Recommended fix (config-first, ordered)
1. **Protect smart-detect exclusion zone on rear_ptz** (UniFi Protect UI, operator or HomeLab with OK): exclude the road/sidewalk band (y ~0.40-0.60 of frame at the parked view). This is the only control that stops a Protect street detection at source. Caveat: PTZ view must be at its parked position; zones do not follow a roaming PTZ.
2. **Turn on `perimeter_single_source_demote`** (options knob, default False, shadow data already being logged in `_last_*` decisions): demotes a lone-engine first alert on a camera with both families live to MEDIUM/LOW, never silences. Before flipping, read its shadow `would_demote` rows for rear_ptz to confirm it would have caught this one (D5a measurement gate in the build plan).
3. Consider `perimeter_vlm_gate=shadow` then enforce only if the prompt is extended to answer "on the property vs street" (today it only rejects "no person"; it would NOT have caught this).
4. Operator note: severity was CRITICAL on all four channels because the house was `away`; a street pedestrian alerting CRITICAL when away is the severity table working as designed, which is why the per-source demote (2) matters more than severity tuning.

No code change is needed for 1-2.

## Not verified
Live Protect zone config (not exposed by API); live Frigate-2 config; D5 shadow rows for this alert (not read); whether a house-state-away CRITICAL was intended for daytime street traffic (policy question for the operator).

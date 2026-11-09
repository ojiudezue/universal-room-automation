# v5.107.0 — Perimeter false-positive gates, egress cameras as perimeter alerts, truthful WhatsApp delivery

**Card:** PERIMETER-FP-STREET-NOISE-1 (related PERIMETER-PHANTOM-XCORR-1, WA-BRIDGE-DOMAIN-1).
**Tier:** 2-DB review protocol (three framing-disjoint reviews), no DB schema change.
**Plan:** `docs/planning/PLANNING_perimeter_fp_build_2026_11.md` rev 2 (plan review 1 applied). D11 (camera-list live
rewire) is a separate Tier-3 track and is NOT in this release.
**Version:** MINOR: new user-facing gates and a new alert source (egress cameras).

## Why
Perimeter alerts were firing on people walking on the street and on empty frames. Frigate's whole-camera person sensor
sees the road; one NVR often fires alone; and the door cameras raised no perimeter alert at all. Separately, a failed
WhatsApp send was logged as delivered and blocked the iMessage fallback in the digest.

## What changed
Every new gate can only LOWER an alert to LOW. None stops a dispatch. Each records its decision (also when off, as a
shadow) on the exterior open-tracks diagnostic sensor under `gate_decisions_by_camera`.

| Item | What | Ships |
|---|---|---|
| D1 | `perimeter_zone_sensors` (Camera Census step, Advanced): Frigate zone person sensors (`<camera>_property`) replace that camera's whole-frame Frigate leg, at setup and after HA start. Zone legs share the camera's cooldown/key and inherit its Frigate-2 host tag. | empty = today |
| D1.8 | Burst sibling check compares NVR families (frigate*/protect*), not engine strings. | identical for today's legs |
| D2 | Per-camera cache of the `frigate_events` payload + 24 h counters; WARN once if Frigate legs rise ≥ 20 times with zero bus events (bridge-automation trip-wire). | display only |
| D3 | `switch.ura_perimeter_zone_agreement_demote`: LOW when Frigate's fresh event never entered the property zone. | off (shadow) |
| D4 | The all-day burst-demote path ships, but `PERIMETER_BURST_NIGHT_ONLY` stays `True` (option C, review A-M3): flip only after a daytime-only re-sample of ≥ 30 would-demotes. | night-only (today) |
| D5 | `switch.ura_perimeter_single_source_demote`: LOW for a camera's first alert when only one NVR fired, on cameras whose learned agreement is ≥ 0.6 over ≥ 20 samples (persisted in `.storage/universal_room_automation.perimeter_agreement`). 8 s settle with the in-flight key held. | off (shadow + learning) |
| D6 | `select.ura_perimeter_vlm_gate` off/shadow/enforce: verdict prompt; `PERSON: NO` on a `frigate_event`-tier frame → LOW. | off |
| D10 | A camera in BOTH the outdoor and door lists raises perimeter alerts. It ignores door stamps from other dual-role cameras; door-only cameras still suppress it. No vehicle legs for dual-role cameras. | needs config |
| D10.5 | `switch.ura_perimeter_egress_known_xcorr_gate`: on dual-role cameras, LOW for a known person (≥ 0.9: egress event or scored face leg matched to the edge, or a Frigate face match + a real ARRIVAL of the same person within 120 s — a live `person.*` not_home → home edge, or a Bermuda move into the door camera's own area / configured door neighbours; nothing within 600 s of setup counts), LOW for an unknown person seen by only one NVR while both are live (after its own 20 s settle, `PERIMETER_EGRESS_XCORR_SETTLE_S`); otherwise contextual severity. No identity wait (0 s). | on |
| D7 | WhatsApp: `_send_whatsapp` returns success; a known-down wa_bridge skips the call and counts a failure; failed sends are logged `delivered=-1` (NOT 0, which is the digest-queue marker; `get_pending_digest` reads `= 0`, history readers `> 0`), are not listed in `channels_fired`, and let the digest fall through to iMessage. Per-recipient audit rows now list what actually fired. | always |

**Audit-row semantics change (D7.4):** from the first `exterior_person`/any `[audit]` row written after this deploy,
`channel`/`delivered`/`bucket_outcome` list channels that actually fired for that recipient (before: channels the
gate allowed). Probes and analytics that span the deploy must split at that row. First changed row timestamp: _fill
in at live validation_.

## Probe results (read-only, 2026-11-08 19:12 CST)
- **D4a burst replay (30 d):** 1,707 alerts, 584 would demote (adjacency approximated by adjacent-camera audit rows).
  Sample of 30 still-existing snapshots (only 32 of 584 retained, 5 cameras, ~7 d): 21 empty, 7 person on street,
  2 unclear (far road edge), 0 person on property. Review A-M3: a convenience sample (30 of the only 32 retained
  files, no hour split; night entries were already demoted), adjacency check wider than runtime, hour table in UTC.
  **Decision: option C** — code ships, flag stays `True`; re-sample ≥ 30 DAYTIME would-demotes, then flip.
- **D5a agreement (30 d):** high on doorbell_lite 0.86, front_door_aerial 0.87, g5_bullet 0.82, garage_a 0.87;
  rear_ptz 0.63, utilities_ptz 0.61; low on back_yard 0.08, hot_tub 0.17, pool_equipment 0.12 (Protect nearly silent).
  Lag p90 4–46 s (rear_ptz 12.9, g5_bullet 14.6). The 8 s settle is below most p90s: retune before enforcing D5.
- **D8 snapshot tier (7 d):** 272 alerts: 244 `live_grab`, 28 no file, **0 `frigate_event`**. The Frigate event
  capture tier is not producing files at all, so D6 enforce would never fire with `PERIMETER_VLM_TRUSTED_TIERS =
  ("frigate_event",)`. Card owed: why `_try_capture_frigate_event` never succeeds.
- **LOW channel check (H6):** single NM person (Oji); every enabled channel floor is HIGH or CRITICAL, so a LOW
  `exterior_person` alert is pushed nowhere today. No person has WhatsApp as the only immediate channel.

## Config at the deploy restart (awake hours, one parent reload)
1. Camera Census → Advanced → Property zone sensors: the 7 live ids
   (`binary_sensor.{utilities_ptz,g5_bullet,rear_ptz,front_side_ptz,front_door_aerial,madrone_g6_entry,doorbell_lite}_property_person_occupancy`).
2. Outdoor cameras: add `camera.madrone_g6_entry`, `camera.doorbell_lite`, `camera.front_door_aerial`.
3. Cameras to describe: add the zone sensors and the three door cameras' person sensors.
Gates D3/D5/D6 stay off; turning them on is a later knob turn read off the shadow data.

## Live validation (prospective)
| # | Criterion | How |
|---|---|---|
| L1 | Boot log "person-leg coverage" for utilities_ptz shows the zone sensor + Protect; "Frigate leg is zone sensor(s)" line; no `utilities_ptz_person_occupancy_2` subscribed | journald |
| L2 | No `exterior_person` audit row with `location` = a camera-level `_person_occupancy_2` leg on a zoned camera within 24 h | URA DB |
| L3 | `frigate_bus_by_camera.back_yard.frigate_events_24h` > 0 within an hour; `last_event.score` numeric, `current_zones` a list | diag sensor attrs |
| L4 | `gate_decisions_by_camera.*.zone_agreement` and `.single_source` reasons appear on alerts; `agreement_by_camera` samples grow | diag sensor attrs |
| L5 | D4 unchanged at ship: daytime repeats show burst reason `outside_night_window` (flag stays True) | diag sensor `burst_demotions_by_camera` |
| L6 | Person at the front door → `exterior_person` row with `location` = doorbell person sensor; `suppressions_by_camera` shows no `egress_suppression` for its own edge; `egress_identity` reason recorded | DB + diag |
| L7 | NM test send with bridge connected → whatsapp health `ok`; (operator OK) bridge add-on stopped for one send → failure counted, WARN names the status | NM sensor + log |

## Review fix-up (reviews A + B, both SHIP)
| Finding | Fix |
|---|---|
| A-M1 / B-MED-1 | failed WhatsApp row `delivered=-1` (`NM_DELIVERED_FAILED`); real-DB test: never in `get_pending_digest` |
| A-M2 | D3 skips the zone sensor's own edge (`zone_leg_edge`) |
| A-M3 | D4 option C (flag back to True) |
| A-M4 | D10.5 own settle `PERIMETER_EGRESS_XCORR_SETTLE_S = 20` (door-camera p90 18.0 / 20.2 / 22.4 s, capped at 20 for a time-sensitive page) |
| B-MED-2 | D10.5 non-face = real arrival (live not_home → home edge; Bermuda move into an area at/near the door; 600 s post-boot exclusion) |
| A-L1 / B-LOW-1 | late `_rescan_siblings` legs feed liveness |
| A-L2 | `KNOWN_MIN_CONF > 1` and window 0 really disable |
| B-LOW-3 | agreement store flushed on teardown; load merges in-memory samples |
| B-LOW-5 | gate / bus diag attributes unrecorded |
| B-LOW-6 | presence state-of-play consumer table updated |
| Not changed | A-L3 (superseded by B-MED-2), A-L4 (display drift, accepted), B-LOW-2 / B-LOW-4 (bounded, harmless; noted) |

## Review C (mutation) fix-up
Review C: 216 mutants, 66 GREEN, verdict FIX-REQUIRED. The two "code" items were test gaps; the code was already correct:
- **D1d:** the legacy fallback already applies `_excluded(eid, engine)`; the predicate also matches by `_person_occupancy[_2]` suffix, which catches `legacy`-tagged legs.
- **D5p:** `except BaseException: if _held: discard; raise` already releases the key. A plain `finally` would release it too early on the delayed-dispatch path, reopening the H1 parallel-dispatch race.

Both are now pinned, along with every HIGH and MEDIUM gap (K3/K4/K5/K7, W5-W12, W15-W17, D1c/q/r/v, D6f/g/h, D5af/E9, E6/E14/D5i, N17). Handler-driving tests are bounded (`asyncio.wait_for`), so a stuck hold FAILS instead of hanging. Re-drill with the reviewer's own `muts.py`: all 35 previously-GREEN or hanging mutants touched are now RED, with no hangs. The LOWs were not addressed in this pass.

## Not done / deferred
- D9 direct MQTT: parked (plan). D10.2 resident demote: parked; replaced by D10.5.
- D10.5 operator ask (2): a "that was <name>" follow-up when Protect back-fills the name within 90 s. **Parked**: NM has no
  "update the same notification" path; a second `async_notify` at the same severity pages again and at LOW reaches no
  channel (all floors ≥ HIGH). Revival trigger: NM gains an edit/thread-reply primitive per channel (Pushover receipt
  replace, companion `tag`), or the operator accepts a second page.
- D10.5 operator ask (1): no fast non-face identity signal names the person *in frame* at dispatch. The reused signals
  (Bermuda room transition, person tracker → home) are used only as corroboration of a face match, per the
  2026-11-08 ruling.
- D11: separate Tier-3 branch.
- D4 daytime-only re-sample (then flip `PERIMETER_BURST_NIGHT_ONLY`).

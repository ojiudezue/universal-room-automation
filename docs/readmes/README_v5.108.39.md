# v5.108.39 — batched release (room rules, arrival wording, perimeter circling, lock page, anomaly flood, digest race, house average)

Released 2026-11-22. One restart (operator cleared it 2026-11-22 ~21:30). PATCH bump.

Cards: AI-ROOM-RULES-TRUST-REPAIR-1, EGRESS-DIRECTION-AWARE-IDENTITY-1, PERIMETER-CIRCLING-HOP-SEVERITY-COLLIDE-1,
SECURITY-LOCK-PAGE-LAST-SEEN-1, BLE-EXTEND-DRILL-RETARGET-1, ANOMALY-FLOOD-ROWS-1, NM-DIGEST-MARK-RACE-1, HOUSE-AVG-SENSORS-1.

## 1. Unified room rules (AI-ROOM-RULES-TRUST-REPAIR-1, D1-D9)

AI-described rules and chained rules now share one record, one compiler and one executor (`_run_room_rules`).
One parser (`rule_compiler`), three conditions, a preview built by code from validated actions, and an honest
status: a rule that has not been parsed into actions shows as needing parsing, never as active. Person rules fire on
`ura_person_location_change`. Every decision is logged; a Room Rules Status sensor reports accuracy from implicit
reversals; the NM digest carries a rules line; a `room_rule_silent` trip-wire flags rules that never fire; room
memory episodes record rule runs. Ships ON (no shadow mode). Design: `docs/planning/PLANNING_unified_room_rules.md`,
user doc `ROOM_RULES.md`.

Review fix-up (fd3c9739d): a reversal is judged by the direction of the state change, not by HA call context
(context expires after 5 s, so a slow cover or media device finishing its own move used to count as a manual undo);
no source_ref dedup; closed-watch guard; light watch keyed per rule; climate entities out of the prompt set.
Tests for all 14 mutation-review survivors (G1-G14), each drilled RED. Reviews A, G SHIP; B and C fixed.
Harness fix 26576c05a: the new suppress key `room_rules_ai_task_entity` added to the AST-slice stubs and the
suppress-key allowlist (140 -> 141).

**Not in this release (deferred, tracked on the card):** the three room-rules screen picks (keep the When dropdown;
rule-writing model in its own step; plain Save / Change-the-wording menu). Deferred because the restart window opened
before they were built and reviewed. They ship in the next release.

## 2. Arrival wording and anchor reasons (EGRESS-DIRECTION-AWARE-IDENTITY-1, step 7 S1)

- An egress notice says "arrived" only when that person's own phone arrival edge is in the window; otherwise
  "came in" (operator A and B, 2026-11-20). Both live cases from 11-19/11-20 are tests.
- Every entry crossing that S1 does not anchor records why: `edge_anchor_reason` on the D8a rows (closed set
  `EDGE_ANCHOR_REASONS`), and `edge_anchor_none` counters on the persons-in-house census sensor attributes.
- Review: SHIP, 0 CRIT/HIGH/MED (`v_s1_anchor_reasons_review.md`).

## 3. Perimeter circling escalation gets its own title (PERIMETER-CIRCLING-HOP-SEVERITY-COLLIDE-1)

NM dedups on `coordinator:title:location`; severity only sets the window. The circling escalation used the same
title as an ordinary sighting, so 8 of 8 escalations since 11-14 were dropped as repeats (one CRITICAL). Escalation
dispatches are now titled "Perimeter Alert — Person Escalated" (053f48563). Reviews A, B SHIP.

## 4. Lock page shows last-seen age (SECURITY-LOCK-PAGE-LAST-SEEN-1)


### What changed
When a swept lock has not reported since HA restarted, the HIGH "Lock not verified" page now says
"last seen N h ago (before restart)", using the lock's Z-Wave last_seen sensor. It used to say
"last report unknown". Display only: the pre-restart stamp still does not count as a report, so
staleness, the dead-node debounce and the repage timing are unchanged
(`domain_coordinators/security_lock_freshness.py` `sweep()` / `_page()`).

- A missing, disabled, unparseable, timezone-naive or future-dated last_seen keeps the old text.
- A stamp after boot but inside the boot grace window prints the age without "(before restart)".

### Tests
`quality/tests/test_security_lock_freshness.py`: page wording for stale, dead-node and offline
pages; the fallback cases; the grace-window label; and a check that freshness values (real
report time, age, stale set) do not change. Mutation drills went RED on each guard.
Review record: `docs/reviews/code-review/overnight_2026_11_20_lock_page_and_ble_drill_review.md`
(SHIP, 2 LOWs fixed in 5a9f2687b).

### Live validation (after the restart)
- When a lock that died before the restart is paged, the message contains "last seen" plus an
  age, not "last report unknown". The garage lock (node 10) is the live case if it is still silent.
- `sensor.ura_security_coordinator_*` lock sweep attributes `freshness_age_h` / `stale` behave as
  in v5.108.38 (no change expected).

## 5. Transit "impossible move" only where a camera covers the move (ANOMALY-FLOOD-ROWS-1)


### What changed

The transit validator called a room move "implausible" whenever no hallway-type (shared-space) camera saw it AND
any shared-space camera anywhere in the house had fired in the last 10 minutes. It never asked whether a camera
could have seen that move. So walking from a bedroom into its own bathroom was "implausible" whenever someone was
in the hallway. Each one cut the move's confidence by 0.15 (enough to drop a normal move below music following's
0.6 bar) and wrote a `transit.path_implausible` anomaly row: 226-275 rows/day on 11-14..11-16, the top anomaly
metric.

Now the penalty applies only when the move's from-room or to-room itself holds a shared-space camera. Otherwise
the result is `no_camera_data`: no penalty, no anomaly row. Rooms map to HA areas through each room's configured
area (`CONF_AREA_ID`, the same helper the census uses); cameras map through the entity registry area, else the
camera device's area. No names are compared.

A confirmed sighting (+0.10), the concurrent-movers correlation and the penalty value are unchanged.

New diagnostics on the presence diagnostic sensor (via `TransitValidator.build_diagnostic_attrs`):
`path_coverage_not_covered_count` (moves spared the penalty) and `path_coverage_room_unresolved_count` (room
strings with no configured area, e.g. `away`).

Side fix: three unsub fields (`_rebuild_timer_unsub`, `_config_signal_unsub`, `_face_recog_signal_unsub`) were
initialised after a `return` and never ran; they are now set in `__init__` (all readers were already guarded).

### Files

- `custom_components/universal_room_automation/transit_validator.py`
- `custom_components/universal_room_automation/sensor.py` (presence diagnostic sensor carries the two counters)
- `custom_components/universal_room_automation/camera_census.py` (module-level `build_room_to_area_id_map`;
  the census method delegates, behaviour identical)
- `quality/tests/test_transit_path_coverage.py` (new), `quality/tests/test_phone_left_behind_camera_leg.py`
  (golden case 3 pins coverage True)
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`

### Live acceptance criteria (prospective)

- **DB:** `anomaly_log` rows with `type = 'transit.path_implausible'` drop from ~230/day to near zero for room pairs
  where neither room holds a shared-space camera (e.g. Master Bedroom <-> Master Bathroom, Jaya Bedroom <-> Jaya
  Bathroom, Kitchen <-> Breakfast Nook). Query the first full day after restart, grouped by from/to room.
- **DB:** `path_implausible` rows are still possible, and only for pairs where one side is a camera room (hallway,
  foyer, stairs, landing). Every surviving row's from or to room maps to an area holding a shared-space camera.
- **Sensor:** the presence diagnostic sensor shows `path_coverage_not_covered_count` rising through the day
  (roughly the old flood rate) and `path_coverage_room_unresolved_count` small (only sentinel locations).
- **Discriminator:** if surviving rows still include bedroom <-> own-bathroom pairs, the room or camera area
  mapping is wrong (check that room's `area_id` and the camera's registry area), not the rule.

## 6. Digest no longer drops rows queued during a send (NM-DIGEST-MARK-RACE-1)

`mark_digest_delivered` marked every undelivered row delivered, including rows queued while the digest was being
built and sent, so those rows never appeared in any digest. It now marks only rows up to the id high-water mark the
digest read (aac62d620). Tests in `quality/tests/test_notification_manager.py`.

## 7. House-average indoor temperature and humidity sensors (HOUSE-AVG-SENSORS-1)


### What changed

Two new whole-house sensors on the "Universal Room Automation" (Whole House) device:

| Entity (expected id) | unique_id | Unit | Device class |
|---|---|---|---|
| `sensor.universal_room_automation_house_avg_temperature` | `universal_room_automation_house_avg_temperature` | °F | temperature, measurement |
| `sensor.universal_room_automation_house_avg_humidity` | `universal_room_automation_house_avg_humidity` | % | humidity, measurement |

Confirm the actual entity ids in the registry after the restart. The slug comes from the device name plus the entity name.

Each sensor averages room readings and leaves out:
- **infrastructure rooms** (room type "Infrastructure (Always-On Equipment)", or the room's infrastructure switch is on), and
- **outdoor rooms**, meaning rooms whose zone has "Outdoor zone" turned on, and
- **garages** (room type "garage"): they are unconditioned (operator 2026-11-22).

Classification comes from `room_classification.get_room_classification`, the same accessor the room classification attribute uses. Rooms are never picked by name.

Attributes (display only): `rooms_included` (rooms that supplied a reading) and `rooms_excluded` (names of the rooms left out).

The existing unfiltered getters `_get_house_avg_temp` / `_get_house_avg_humidity` are unchanged, so Temp Delta Outside, Humidity Delta Outside, HVAC Direction and the DB snapshot behave as before.

### Operator decisions (2026-11-22, applied)

- Study A Closet set to room type Infrastructure via its options (switch `switch.study_a_closet_infrastructure_room` on). Its power sensor `sensor.span_panel_office_closet_power` (SPAN "Study A Closet Main Plug") was already configured.
- Garage A and Garage B left out (unconditioned), by the room-type rule above.

### Operator config needed (no code) — superseded by the decisions above

The live config was read on 2026-11-17. **AV Closet** is already `infrastructure`, so it is excluded. **Study A Closet** is `closet`, the same type as the clothing closets, so it is still included. To exclude it, set Study A Closet's room type to "Infrastructure (Always-On Equipment)" in its options, or turn on its infrastructure switch. Infrastructure also changes that room's other behaviour (always-on equipment semantics and its menu), so check that this is what you want. **Patio** is in the zone "Outside" (outdoor), so it is excluded. Garage A and Garage B (`garage`) are still included. If they should be left out, that is a follow-up decision.

### Post-deploy steps (attended session / operator, not the build)

1. Check that both entities exist and have numeric states.
2. Point the v8 dashboard weather card at the new entity ids instead of `sensor.house_indoor_temperature` / `sensor.house_indoor_humidity`.
3. After the card has been moved, delete the two template helpers:
   - `01M6SKV8XWBQ255247672EM8QZ`
   - `01M6SKV9GS5E8M0XF89K79RWHH`

   Before deleting, grep the dashboards and automations for other consumers of those helpers.

### Live acceptance criteria

- **Live:** `sensor.universal_room_automation_house_avg_temperature` is numeric, and `rooms_excluded` is exactly `AV Closet`, `Garage A`, `Garage B`, `Patio`, `Study A Closet`.
- **Live:** the humidity sensor has the same `rooms_excluded` list.
- **Live (discriminating):** the new temperature differs from the `house_avg_temp` attribute on Temp Delta Outside whenever AV Closet or Patio reads differently from the indoor mean. Under the unfiltered failure the two values would be identical.
- **Live:** `rooms_included` equals the number of non-excluded rooms that have a temperature reading.
- **Live:** no errors from `aggregation` in the log after the restart.

### Tests

`quality/tests/test_house_avg_sensors.py` (10 tests). Each exclusion conjunct, the whole filter and both registrations were mutation-drilled RED.

## 8. Test-only: BLE drill retarget (BLE-EXTEND-DRILL-RETARGET-1)

`test_MUTATION_m2_seeding_hoisted` drill anchor updated to the post-b13a151e coordinator.py text. No production change.

## Tests

Full suite before deploy (develop 74a667b77 + README): 23847 passed, 0 failed, 117 skipped (`.claude/suite-out-v5.108.39.txt`) (baseline v5.108.38 = 1 known failure,
`test_v4710_trap_restores_clean_url_on_sigint`; known flake `test_interior_vision_fixup.py::test_path_task_tracked_until_done`,
card TEST-INTERIOR-TASK-TRACK-FLAKE-1).

## Validated 2026-11-22 (restart 21:46 CST, URA loaded ~21:48)

| Criterion | Result | Evidence |
|---|---|---|
| Installed version | PASS | HACS installed v5.108.39; `/config/custom_components/universal_room_automation/manifest.json` version v5.108.39 |
| Boot, no URA errors | PASS | system_log has no ERROR from `universal_room_automation` after boot. Warnings are known boot transients: boot-settle timeouts, sensors unavailable for 60 s, census cameras unavailable at first read, and the Zone-kWh seed wording (parked card HVAC-ZONE-KWH-SEED-WARN-WORDING-1) |
| House average sensors | PASS | `sensor.universal_room_automation_house_avg_temperature` 73.2 °F, `_humidity` 52.4 %, rooms_included 7, rooms_excluded = AV Closet, Garage A, Garage B, Media Room Closet, Patio, Study A Closet. Media Room Closet is room type closet with its infrastructure switch on (already set), so it is excluded by design |
| Infrastructure switches survive restart | PASS | `switch.study_a_closet_infrastructure_room`, `switch.garage_a_infrastructure_room`, `switch.garage_b_infrastructure_room` all on after boot |
| Room rules executor live | PASS | 47 `sensor.*_ai_automation_status` (Room Rules Status) sensors present; sampled rooms show `knobs.unified_executor: true`, state `none` (no rules configured), no rule shown active with zero actions. `sensor.ura_coordinator_manager_room_rules_accuracy` present (unknown: 0 fires in window) |
| Transit coverage counters | PASS (wiring) | `sensor.ura_presence_coordinator_presence_diagnostics` carries `path_coverage_not_covered_count` and `path_coverage_room_unresolved_count` (both 0 two minutes after boot) |
| Anomaly flood drop | PENDING | needs the first full day: `transit.path_implausible` rows on 11-23 vs ~230/day |
| S1 `edge_anchor_reason` | PENDING | needs a new entry crossing that S1 does not anchor |
| Perimeter escalation title | PENDING | needs a circling escalation (rare event; proven in-suite) |
| Lock page last-seen | PENDING | needs a lock_unverified page after a restart (garage lock node 10 is the live candidate) |
| Digest race | PENDING | needs a LOW row queued during a digest send (race window; proven in-suite) |
| Room rule end-to-end | PENDING | needs one test rule ("Run an automation", Claude AI Task) |

Not shipped in this release: the room-rules screen picks (see section 1).

# PLANNING: camera area map falls back to the device area (ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1)

**Status: PARKED 2026-11-15** (operator: "Yes park the camera area"; and "Turn off camera hold. Too inaccurate in every
room."). Nothing below is scheduled for build. Revival triggers and the verbatim decisions are on card
ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 (`operator_2026_11_15_park`, `operator_2026_11_15_no_camera_hold`). The option-A
decision recorded under it is superseded by the park.

Date 2026-11-15. Author ura-planner. Status: plan rev 2 (applies plan review
`docs/reviews/code-review/plan_review_camera_area_map_2026_11_15.md`, PLAN-FIX-REQUIRED; finding map in §10).
Card ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1.
Operator decision 2026-11-15 (verbatim on the card): "Yes (option A: fix the lookup to fall back to the device area;
zone camera tier on; room camera-hold off by default except rooms the operator lists)."
Tier: **2-DB minimum with the house-state rule** (operator + `feedback_tier2db_minimum_arc`), plus framing G (arc).
Code base read: `develop` @ 94f276e5.

Read completely before writing: the card (incl. `consumer_map_2026_11_13`, `INSTANCE_2026_11_15_v5_108_25_watched_set`,
`CORRECTION_2026-11-12`, `gate_2026_11_13`); `AUDIT_v5_108_25_watched_set_2026_11_15.md`;
`HARMONIZATION_identity_vision_census_2026_11_15.md` (§1, §2 C12/C13, §3 S2-S4, §4, §7 D2);
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger); `SENSOR_FLEET_CLASSES.md`;
`IDENTITY_FUSION_CAMERAS_MANUAL.md`; `CONTRACT_person_awareness_layer.md`; `PLANNING_zone_camera_person_only_guard.md`;
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (read because the room camera hold stamps HVAC evidence, §3.1). No claim in either
corrections ledger is re-asserted here. Where code disagrees with a doc, this plan says so (§1.3).

---

## 0. The cycle in one paragraph

`CameraIntegrationManager.resolve_camera_entity` (`camera_census.py:680`) sets `CameraInfo.area_id = bs_entity.area_id
or camera_entry.area_id`: two ENTITY areas, never the device's. In this house every camera person entity has entity area
null (watched-set audit §1), so the area map `_cameras_by_area` (`:1120-1123`) files all of them under `""` and the
census's own per-camera `area_id` reads None. Five consumers have therefore never seen a camera by area. Fixing the
lookup switches all five on at once, three of them for the first time ever (room camera hold, zone camera tier, census
per-area dedup / BLE cancel). The operator chose to fix the lookup, turn the zone tier on, and keep the room hold off
except in rooms he lists. This plan measures first (D0), fixes the lookup through the existing resolver helper (D1),
gates the room hold per room (D2), turns the zone tier on with a person-only guard (D3), and decides the census by
the D0 numbers (D4).

---

## 1. Institutional context verified

### 1.1 Greps run (re-run 2026-11-15 on develop 94f276e5)

```
$ grep -n "def resolve_area_id_for_entity" camera_resolver.py
474:def resolve_area_id_for_entity(entity_registry, device_registry, entity_id) -> str | None:
    (entity.area_id, else device.area_id via entity.device_id, else None; never raises)
$ grep -n "resolve_area_id_for_entity\|area_id=" camera_census.py
680:  area_id=bs_entity.area_id or camera_entry.area_id,          <- resolve_camera_entity (configured mode)
918:  _area = resolve_area_id_for_entity(ent_reg, dev_reg, eid)  <- resolve_cross_platform_sensors (already correct)
994:  area_id=entry.area_id or info.area_id,                     <- legacy cross-platform fire-axe path
1011: area_id=entry.area_id or info.area_id,                     <- same
1163: area_id=entity.area_id,                                    <- _discover_full_scan (Frigate)
1191: area_id=entity.area_id,                                    <- _discover_full_scan (Protect)
$ grep -rn "get_person_sensor_for_area\|get_cameras_for_area\|_cameras_by_area" --include='*.py' .
sensor.py:2839                         has_camera (room)
domain_coordinators/camera_stream_health.py:921  camera_override_person_sensors -> room hold + Wr + room stream tick
domain_coordinators/presence.py:5240, :5248      _discover_zone_cameras (zone camera tier)
camera_census.py:1226-1271             the map and its two getters
$ grep -n "camera_info.area_id\|\.area_id$" camera_census.py   (CameraInfo readers in the census)
2078  _calculate_house_census (frigate / binary contributions -> _dedup_by_area)
3072  stuck-camera watchdog (discount needs an area)
6302  _get_unrecognized_camera_count (per-area max, BLE cancel)
$ grep -rn "CONF_DISABLE_CAMERA_PRESENCE" --include='*.py' .
const.py:726 (per-room, default False); config_flow.py:2626, :13480 (room sensors step, both flows);
presence.py:3964-3987, :5221-5243 (zone tier opt-out); sensor.py:2821 (has_camera); fan_veto.py:361; binary_sensor.py:1805
coordinator.py: NO read (the room camera override ignores it today)
$ grep -n "CAMERA_HOLD\|CAMERA_OVERRIDE\|CAMERA_EXTEND" const.py      -> no match
$ grep -n "CAMERA_AREA" const.py                                       -> no match
```

### 1.2 REUSE-or-BUILD per piece

| Piece | Verdict | Where |
|---|---|---|
| Entity-else-device area rule | **REUSED** `resolve_area_id_for_entity` | `camera_resolver.py:474`; already the census cross-platform rule at `camera_census.py:918` |
| Area map + getters | **REUSED** unchanged shape | `camera_census.py:1083-1123`, `:1226-1271` |
| Room camera hold block (v3.5.1) | **REUSED**, one new gate | `coordinator.py:4482-4521`; lookup `:2847-2864` → `camera_stream_health.camera_override_person_sensors` `:912-923` |
| Per-room camera mute | **REUSED** `CONF_DISABLE_CAMERA_PRESENCE` (made authoritative over the hold) | `const.py:726` |
| Per-room hold opt-in | **NEW** `CONF_ROOM_CAMERA_HOLD` (room options, default False). No equivalent: `CONF_DISABLE_CAMERA_PRESENCE` has the opposite polarity and default (reusing it would switch the hold ON in every camera room, which the operator rejected) | §D2 |
| Master kill for the lookup fix | **NEW** `CAMERA_AREA_DEVICE_FALLBACK_ENABLED` (rung 1). No area kill exists (`grep CAMERA_AREA const.py` empty) | §D1 |
| Census area semantics knob | **NEW** `CENSUS_CAMERA_AREA_FROM_DEVICE` (rung 1), value set by D0 | §D4 |
| Census stuck-camera discount by area | **NEW** `CENSUS_STUCK_CAMERA_DISCOUNT_ENABLED` (rung 1, False = today's notify-only) | §D4 |
| Zone camera tier | **REUSED** `_discover_zone_cameras` / `ZonePresenceTracker` | `presence.py:5192-5300`, `:819-860`, `:977-1051` |
| Person-only guard | **REUSED** the parked plan `PLANNING_zone_camera_person_only_guard.md` D1 (Source 3 filter) + a matching registration filter | §D3 |
| Offline probe pattern | **REUSED** `.claude/tmp/wr_repro_v108_25.py` (reads Samba `.storage`, no token) and `.claude/tmp/rev35_probe.py` `area_of` | §D0 |
| Stream health / twin owner | **REUSED** unchanged; Wr/U recompute automatically | `camera_twin_health.py:569-584`, `camera_stream_health.room_stream_input_entities` `:934-969` |

### 1.3 Code-vs-doc contradictions found (code wins; docs fixed in the build commit)

1. **Harmonization C12 / the brief: "the census currently computes a house-wide max under `""`".** WRONG. The census does
   not read `_cameras_by_area`; it reads `CameraInfo.area_id` from `_camera_by_entity` (`camera_census.py:2077-2078`,
   `:6295-6302`), which is **None**, not `""`. Null-area contributions are **summed individually** and **never BLE-cancelled**
   (`_dedup_by_area` `:2873-2883`; `_get_unrecognized_camera_count` Step 2 `:6356-6366`, Step 3 comment I3 `:6386-6390`).
   So today's census is a house-wide **SUM** with no same-area dedup and no BLE cancel. Fixing the map can only **lower**
   `unidentified_count` and the camera body total (arithmetic in D4), never raise it, on the census paths themselves.
   The one raising path is indirect, through the zone tier (D4 (iv)).
2. **Card consumer map: "zone trackers (zone camera tier + face arrival)".** Face arrival no longer reads zone trackers:
   the v3.19 path is deleted (`presence.py` has no `_handle_face_arrival`; `_derive_face_arrival` `:5924` reads person
   sightings over `zone_cameras` picks, and is off: `FACE_ARRIVAL_INTERIOR_ENABLED = False`, `const.py:3457`). Card
   CORRECTION_2026-11-12 already says so. Face arrival is NOT a consumer of this fix.
3. **"Camera EXTENDS room occupancy" (card, coordinator comment `:4483`).** The block runs whenever the room reads vacant
   (`if not data.get(STATE_OCCUPIED) and not self._failsafe_fired`, `:4491`), with no chain test, so a camera person
   sensor `on` also **creates** occupancy in a vacant room (lights on at entry, HVAC evidence stamp). D0 measures both.
4. **Ship 3b "U = the foyer group"** (contract §3 INV-MISSING-NOT-ZERO (b), presence doc ship 3b entry). Live U = 14,
   Wr = 3 (watched-set audit). After D1, U shrinks toward the plan's original number; both docs get the D0 numbers.
5. **Census stuck-camera discount** (`camera_census.py:3085-3133`) has never discounted in this house: every camera's
   `area_id` is None, so every stuck camera is `notify_only_reason: no_area_id` with one WARN each (`:3117-3123`).
   D1 would activate the discount; D4 keeps it off by default (still-guest risk).

### 1.4 Prior plans, audits, memory consulted

- `PLANNING_zone_camera_person_only_guard.md` (backlog, LOW): Source 3 filter. Folded in as D3b.
- `AUDIT_v5_108_25_watched_set_2026_11_15.md`: the root cause, Wr = 3, U = 14, repro script.
- `AUDIT_face_arrival_and_prearrival_fan_rooms.md` (card origin): face arrival never fired.
- `AUDIT_entry_room_foyer_camera_2026_11_15.md` via card HA-FOYER-CAMERA-AREA-ALIGN-1: the foyer device move.
- Card CENSUS-PATIO-THROUGH-GLASS-1: config-only verdict (Frigate mask + Protect zone on `camera.family_room` /
  `camera.family_room_high_resolution_channel`), still `waiting_operator`.
- `PLANNING_census_ble_cancel_unrecognized.md` (via code docstrings): per-area BLE cancel invariants I1-I3.
- `PLANNING_person_awareness_layer_ship3.md` §6 (3b): Wr / U definitions.
- `PLANNING_nvr_witness_layer.md`: W5b moves `_cross_validate_platforms` behind a byte-identical house-count fixture.
- `PLANNING_vision_interior_sightings.md` §214: interior resolves area entity-then-device itself.
- `PLANNING_crossing_vision.md` P3-D8: anchor reads substrate Tier-1 inputs, not the area map.
- Memory: `feedback_registry_not_name_guessing`, `feedback_portability_imperative`, `feedback_dead_sensor_is_faulty_equipment`,
  `feedback_tier2db_minimum_arc`, `reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`,
  `feedback_parsimonious_room_config`, `feedback_no_shadow_mode_day1_correct`.

### 1.5 Config-first check

- **A config-only route exists and is rejected:** set an entity-level area on each of the 28 configured camera person
  entities. That is option B (every camera room starts holding on day one), it is per-install manual work that breaks
  portability, and HA's own rule is entity-else-device (`feedback_portability_imperative`). Rejected by the operator's
  option A.
- No knob gates the room hold today (`coordinator.py` never reads `CONF_DISABLE_CAMERA_PRESENCE`), so the per-room
  default-off needs code.
- The patio-through-glass leak IS a config fix (Frigate mask + Protect zone, card CENSUS-PATIO-THROUGH-GLASS-1); this
  plan does not code around it. It recommends the operator apply it before opting the family room into the hold.

### 1.6 Layer conformance (contract §6)

| Row | Answer |
|---|---|
| Facts | Evidence service (camera → area) feeding F2 (census body terms, unchanged ingest), comfort (room occupancy), house_state via zone occupancy. No F1/F3/F4/F5 change. |
| Ingest | F2 stays at `_apply_enhanced_house_census` / `_cross_validate_platforms`; no new store. |
| Read | Room hold reads its own room's camera sensors (comfort class, existing allowlisted path). Zone tier: existing tracker. |
| Separation | No F4 reaches F2. No access consumer reads anything new. |
| Delivery | YES, named for the operator (§7): census guest count goes down (D4-CORRECT); 3b pages move partly from the owner to rooms; WAKING may come earlier (D0 (e) sizes it). AWAY and ARRIVING-while-AWAY timing do NOT change (INV-AWAY-UNCHANGED, D3c). |
| Guard delta | 0 allowlist rows. |
| Seam | 3b `CameraTwinHealth`, interior vision D4, NVR W5b fixture, crossing P3-D8 (§D5). |

---

## 2. Falsifiable invariants

- **INV-MAP.** For every configured camera person entity E: `CameraInfo(E).area_id == resolve_area_id_for_entity(E)`
  (entity area when set, else device area, else None) at all SIX `CameraInfo(` construction sites in `camera_census.py`:
  `:677` (area at `:680`), `:919` (ALREADY compliant via `:918`; not touched, not behind the kill switch), `:991`
  (`:994`), `:1008` (`:1011`), `:1160` (`:1163`), `:1188` (`:1191`). With `CAMERA_AREA_DEVICE_FALLBACK_ENABLED = False`
  the five changed sites are byte-identical to develop and `:919` is unchanged in both states. *Broken by:* any site
  writing entity-only area with the knob on, or `:919` changing with the knob off.
- **INV-AWAY-UNCHANGED (charter hard constraint, "I need away to be fast acting").** For the same evidence sequence, the
  time and branch (`veto_path`) of every AWAY edge (nobody-home, α, β) and of every ARRIVING edge raised while the house is
  AWAY are byte-identical with D3 on and with D3 off (= develop, where no zone has a camera). *Broken by:* any evidence
  sequence where a zone camera `on`, in its 300 s timeout, or in its stream-dead hold (up to 900 s more) moves one of
  those edges.
- **INV-NO-SELF-CORROBORATION.** A camera's own detection never corroborates that camera's divergent count: census
  divergence corroboration (`camera_census._any_zone_occupied_snapshot` `:2522`, read at `:2206-2221`) reads the
  camera-free zone view, so with D3 on its answer equals develop's. *Broken by:* the review repro (§D3c) keeping 1.
- **INV-HOLD-OPT-IN (the load-bearing one).** In a room with `CONF_ROOM_CAMERA_HOLD` False (the default) OR
  `CONF_DISABLE_CAMERA_PRESENCE` True, no camera person sensor ever sets that room's `STATE_OCCUPIED`,
  `occupancy_source = "camera"`, `_last_motion_time`, `_became_occupied_time` or the HVAC evidence stamp, in any
  reachable path, whatever the area map holds. The room's occupancy trace is identical to develop's (where the extras
  list is empty). *Broken by:* any room with the default config whose occupancy differs from develop when a camera in
  its area reads `on`.
- **INV-ZONE-PERSON.** A zone tracker registers only person-detection entities: never an entity whose registry
  `original_device_class` is `motion`; and HVAC D6 Source 3 never counts one. *Broken by:* a `device_class: motion`
  entity in `_camera_entity_ids` or incrementing `confirmed`.
- **INV-CENSUS-DOWN (only if D4 ships the corrected logic; holds WITH D3 on because of INV-NO-SELF-CORROBORATION).** For any evidence state S, `unidentified_count_after(S) <=
  unidentified_count_before(S)` and `camera_total_after(S) <= camera_total_before(S)` on the census paths
  (`_calculate_house_census`, `_get_unrecognized_camera_count`); and with `CENSUS_STUCK_CAMERA_DISCOUNT_ENABLED` False
  no camera is discounted. *Broken by:* any S where a per-area value exceeds the null-area sum.

---

## 3. Producer and consumer checks

### 3.1 Producer: the area of a camera

- Arithmetic today: `bs_entity.area_id or camera_entry.area_id` (two entity reads). Dependency health: the registry has
  entity area null on all 28 configured person entities and on their `camera.*` entities; device areas are set (watched-
  set audit §1; the foyer devices moved to `foyer` on 2026-11-15).
- After: `resolve_area_id_for_entity(ent_reg, dev_reg, bs_id)`, and if None, the same for `camera_entry` (keeps the
  current second fallback: a camera entity can carry an area its sibling lacks).
- Ground truth to compare against: the operator's own room ↔ camera knowledge (D0 table is shown to him), never another
  URA number.
- Hazard (manual §1.2): a device mounted in one area but watching another (pool-overhead in Balcony; family room sees the
  patio). Device area is the mount, not the view. D0 lists every camera whose device area has a URA room, so the operator
  sees each mapping before any hold or zone uses it.

### 3.2 Consumers (every reader of the map or of `CameraInfo.area_id`)

| # | Consumer | File:line | Class | Fires today? | After D1 |
|---|---|---|---|---|---|
| C1 | Room camera hold (create + extend occupancy; HVAC evidence stamp; failsafe timer) | `coordinator.py:4482-4521` via `:2847-2864`, `camera_stream_health.py:912-923` | comfort (lights, fans, HVAC room demand, NM panel targeting, dwell model) | never (extras empty) | gated per room by D2 |
| C2 | Room camera stream tick extras (exclusion + S1/S2 pages) | `coordinator.py:2619-2623`, `room_stream_input_entities` `camera_stream_health.py:934-969` | evidence service | only the 3 configured panels | rooms watch their area's cameras (Wr grows, U shrinks) |
| C3 | 3b twin owner Wr/U | `camera_twin_health.py:569-584` | evidence service, pages | Wr 3 / U 14 | recomputed (D0 gives numbers) |
| C4 | Room `has_camera` | `sensor.py:2811-2842` | display | always False | true for camera rooms |
| C5 | Zone camera tier (`_discover_zone_cameras` → `register_camera` → `_any_camera_occupied` → `_derived_mode`) | `presence.py:5192-5300`, `:819-860` | house_state readers: nobody-home (`any_zone_occupied_for_empty`, `:7731-7741`), path β (`any_indoor_zone_occupied`, `:7704-7708`), ARRIVING while AWAY (`has_people`, `:1411-1432`), census divergence corroboration (`camera_census.py:2522`), WAKING (`any_zone_raw_occupied`, `:7719`), SLEEP night signal (`_zone_night_raw`); display | never (`signal_tiers.camera_sensors=false`, all 5 zones, card verify 11-13) | on for display, WAKING and the night signal outside the AWAY input; camera-free for AWAY, ARRIVING-while-AWAY and corroboration (D3c) |
| C6 | `_run_inference("camera_detection")` trigger | `presence.py:5303-5320` | house_state push | never (no camera registered) | fires on every camera person edge |
| C7 | Census `_calculate_house_census` `_dedup_by_area` | `camera_census.py:2060-2144` | F2 trust (census_count) | sum (null areas) | per-area max (D4) |
| C8 | Census `_get_unrecognized_camera_count` (per-area max, BLE cancel) | `camera_census.py:6235-6420` | F2 trust (`unidentified_count`, AWAY α, guest_reason, visitors_present path A) | sum, BLE cancel never applies | per-area max − BLE (D4) |
| C9 | Census stuck-camera discount | `camera_census.py:3072-3133` | F2 trust | notify-only always | gated off (D4) |
| — | Not consumers (verified): transit checkpoints (`transit_validator.py:259`, resolver enumeration), census face reads (`:3975`, `:4018`), sightings (picks), fan_veto / room fused camera (`CONF_ROOM_CAMERAS`), D6 Source 3 (`zone.zone_cameras` picks), interior vision (own resolution), crossing ledger anchor (substrate Tier-1) | | | | unchanged |

### 3.3 Fire checks and forward traces

- C1/C5/C6: zero fires ever (card evidence: zone attributes `cameras={}`, `face_arrivals_today=0`; audit: extras `{}`).
  Forward trace C1 → `STATE_OCCUPIED` → lights (paused rooms skip actuation: 20 of 47 room Automation switches read off,
  harmonization §7 D5), fans, HVAC `hvac_occupied` + fast entry run (HVAC doc §2, §3.1 "camera override verdict" is
  evidence), NM panel targeting, dwell model. C5 → nobody-home / path β / ARRIVING / night_raw / D4d page / census
  divergence corroboration (`_any_zone_occupied_snapshot`).
- C9: zero discounts ever (every stuck row `no_area_id`).
- New producers get zero-fire trip-wires (D2, D3).

---

## 4. Deliverables

### D0. Measurement probe (read-only, FIRST; gates D2-D4)

One offline script `scripts/probes/camera_area_map_replay.py` (run on the Mac against the Samba `.storage` and
`ssh ha "python3 -" < script` for the recorder; the URA DB via the live mount). Writes
`docs/planning/AUDIT_camera_area_map_replay_2026_11.md`. No HA call that writes; no Bermuda diagnostics.

Sections (each a table):
- **(a) Rebuilt map.** For every entity on the integration lists (`camera_person_entities`, egress, perimeter): resolved
  person sensors (same suffix rule as `resolve_camera_entity`, so the probe reproduces the real set), entity area,
  device area, new area, the URA room on that area (room entry `CONF_AREA_ID`), that room's zone, its Automation switch
  live state, `CONF_DISABLE_CAMERA_PRESENCE`. Plus the full-scan and legacy paths' outputs for completeness. Cross-check:
  reproduce today's Wr = 3 / U = 14 with the entity-only rule before computing the new values (the repro proves the
  probe matches code).
- **(b) Zones gaining cameras.** Per zone: cameras registered after D1, with each camera's device area, mount note and ROLE (interior / egress / perimeter, from the configured lists matched by registry device), and which ones D3a' admits.
- **(c) Room hold replay, 7 days** (recorder retention). Per room with cameras: from the room's
  `binary_sensor.<room>_occupied` history and its camera person sensors' history, minutes where a camera person sensor
  read `on` while the room read vacant (would-create minutes, count of would-create episodes) and the extra hold
  minutes after the room went vacant (camera `on` past vacancy + the room occupancy timeout), split by house state and
  by night (22-06). Also the HVAC view: would-be extra `hvac_occupied` minutes using the room-type evidence hold (HVAC
  doc §3.1). Rooms ranked by extra minutes.
- **(d) Census replay.** For every `census_snapshots` row / recorder sample of the census sensor in 7 days, recompute
  `unidentified_count` and the camera body total with (i) null areas (today, must match the recorded value: the
  equality rate is the probe's self-check), (ii) device areas, per-area max, (iii) (ii) + BLE cancel from
  `sensor.<person>_room` history mapped through room `CONF_AREA_ID`, (iv) (iii) + stuck discount. Report per day: minutes
  with a different `unidentified_count`, distribution of the delta, minutes where it crosses 0 (that is the AWAY α and
  `guest_reason`/`visitors_present` reach), and **11-14 (the party) hour by hour**.
  - **Contradicted-zero table (the D4 gate input).** Every minute where (ii) or (iii) reads 0 while (i) read > 0, with the
    oracle verdict "a person not accounted for was home": (1) any `person.*` whose trust state (`person_state_for_trust`
    rule, replayed from person + Bermuda history) is `home` with no BLE room in the camera's area and no fresh face, OR
    (2) a door-crossing entry (`person_entry_exit_events`, direction `entry`) in the prior 2 h with no matching exit, OR
    (3) a Tier-1 sensor `on` in the camera's area with no BLE person there, OR (4) for 11-14 only, the operator's party
    head counts by hour (§8 Q6). A minute is CONTRADICTED if any of (1)-(4) says someone uncounted was there.
  - **Hidden-second-person table.** Per area with ≥ 2 interior physical cameras (by registry device, after the W1 twin
    collapse, so two NVRs on one camera count once): minutes where two DIFFERENT physical cameras each read ≥ 1 and the
    area max is below their sum, cameras named. That is where per-area max can hide a second person.
- **(e) Zone tier house-state replay.** Using the house-state history and the zone cameras from (b), camera-INCLUSIVE
  counterfactual (what develop + D1 without D3c would do), to prove D3c is needed and size what stays camera-inclusive:
  - minutes a zone reads occupied ONLY because of a camera (live, within its 300 s timeout
    `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS` `presence.py:150`, or in a stream-dead hold up to 900 s more,
    `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S`);
  - every AWAY edge split by `veto_path` (`nobody_home` / `active` α / `lost_admitted*` β) with the delay each would have
    had (α must show 0);
  - would-be ARRIVING edges while AWAY;
  - **WAKING edges moved earlier** (sustained gate reads `any_zone_raw_occupied`, `presence.py:7719`, which keeps the
    camera tier), by how much, per zone and camera, and whether a person was up (BLE move / Tier-1 in that minute);
  - **SLEEP held by `_zone_night_raw`** through a camera limb: minutes and nights;
  - `camera_detection` inference trigger count per day.
- **(f) Family room through glass** (CENSUS-PATIO-THROUGH-GLASS-1). For the family-room camera person sensors and count
  sensors: minutes `on` / count > 0 while the family room's own motion/presence sensors were quiet AND no BLE person was
  in that room, split by house state; same minutes with the house AWAY; and the subset during sun-up vs dark. That is
  the patio-leak upper bound for both the room hold and the census.
- **(g) 3b deltas.** New Wr, new U, which page groups move from the owner to rooms.
- **(h) Stuck discount.** Every `camera_stuck` NM in the window and whether the new area would have discounted it, with
  the room's sensors and BLE at that time (still-guest check).

#### Acceptance criteria
- **Verify:** the (a) repro with the entity-only rule yields Wr 3 / U 14 exactly; the (d)(i) recompute equals the
  recorded `unidentified_count` on ≥ 99 % of samples (a lower rate means the replay misses an input; fix the probe before
  reading (ii)-(iv)).
- **Verify (discriminating):** if (d)(ii)-(iii) show ANY sample with after > before, INV-CENSUS-DOWN is false and the
  §1.3 #1 reading is wrong; stop and re-plan D4.
- **Live:** none (read-only).
- **Gate:** D2's default room list, D3's go, D4's branch and the operator questions (§8) are decided on this report.

### D1. The lookup fix

Replace the entity-only area at every CameraInfo construction that feeds the area map or the census with
`resolve_area_id_for_entity` (camera_resolver.py:474):
- `camera_census.py:680` `resolve_camera_entity`: `area = resolve_area_id_for_entity(ent_reg, dev_reg, bs_id) or
  resolve_area_id_for_entity(ent_reg, dev_reg, camera_entity_id)`.
- `:994`, `:1011` (legacy cross-platform fire-axe path): `resolve_area_id_for_entity(ent_reg, dev_reg, candidate_id) or
  info.area_id`.
- `:1163`, `:1191` (`_discover_full_scan`): `resolve_area_id_for_entity(ent_reg, dev_reg, entity_id)`.
- Registry rule, not names (`feedback_registry_not_name_guessing`). The suffix-based person classification inside
  `resolve_camera_entity` (`:650-670`) is NOT changed here (REGISTRY-NOT-NAMES-1 owns it).
- Kill switch `CAMERA_AREA_DEVICE_FALLBACK_ENABLED` (rung 1, True). False = develop byte-identical (all five sites).
- Rebuild trigger: the map is rebuilt at `async_discover`; a later device-area move takes effect on the next rediscovery
  (reload / restart). Check during build whether `async_discover` already re-runs on `device_registry_updated`; if not,
  say so in the README (no new listener in this cycle, non-goal).
- Ships in the SAME release as D2 and D4 (D1 alone would switch the hold on in every camera room and change the census).

#### Acceptance criteria
- **Verify:** a fixture registry with entity area None and device area `family_room` gives `area_id == "family_room"`
  at each of the five sites; entity area set wins; no device → None; knob False → entity-only.
- **Test:** `test_camera_area_map_device_fallback.py::test_resolve_camera_entity_uses_device_area`,
  `::test_entity_area_wins`, `::test_full_scan_device_area`, `::test_legacy_cross_platform_device_area`,
  `::test_kill_switch_byte_identical` (map + `_camera_by_entity` equal to a develop golden captured before the edit).
  Each site mutation-anchored (revert one site → its named test RED).
- **Live:** `sensor.<room>_*` has_camera reads true for the D0 (a) camera rooms; `sensor.zone_<z>_presence_status`
  `signal_tiers.camera_sensors` true and `cameras` non-empty for the D0 (b) zones; boot INFO
  "Subscribed to N zone camera entities" with N = D0 (b) total.

### D2. Room camera hold: per-room opt-in, default off

> **Operator decision 2026-11-15, supersedes the opt-in below:** "Turn off camera hold. Too inaccurate in every room. We
> have enough with the other sensor fusion." D0 (c) measured 53-91% unsupported created minutes in every candidate room.
> The room camera hold is a non-goal: no per-room opt-in field ships; if D1 ever ships, the hold block
> (`coordinator.py:4491`) is disabled outright, with a test that no camera person sensor ever sets room occupancy. The
> text below is kept only as the record of the design that was rejected.

- **Knob home: room options field (rung 2), NEW `CONF_ROOM_CAMERA_HOLD = "room_camera_hold"`, boolean, default False**,
  in the room `sensors` step next to `CONF_DISABLE_CAMERA_PRESENCE` and `CONF_ROOM_CAMERAS` (`config_flow.py:2568` /
  `:12724` steps; fields at `:2626` / `:13480`). Label (style guide): "Cameras hold occupancy". Helper: "When on, a camera
  in this room's area that sees a person keeps the room occupied (lights, fans, heating and cooling) after the motion
  sensors stop. Off by default." Lazy default (absent key = False, Bug Class #46 doctrine, no migration).
  Reload-suppression: add the key to the room options reload-suppression allowlist if the room has one for
  `CONF_DISABLE_CAMERA_PRESENCE` (check at build; read fresh per tick either way).
- **Why rung 2, not a per-room Switch (rung 3):** the operator sets it once per room after D0, it is per-deployment
  structure, and a Switch would add ~47 entities with persistence for a setting changed about once
  (`feedback_parsimonious_room_config`).
- **Gate site: the consumer, not the lookup.** In `coordinator._async_update_data` the v3.5.1 block (`:4491`) runs only
  when `_room_camera_hold_enabled()` = `CONF_ROOM_CAMERA_HOLD` True AND `CONF_DISABLE_CAMERA_PRESENCE` False (options
  over data, fresh per tick). The lookup `_camera_override_person_sensors` stays unconditional, so the producer is right
  for every other reader: the room stream tick extras, has_camera, 3b Wr. Policy lives in the consumer (CLAUDE.md fire
  check rule 3).
- **Room knob inventory after this cycle (room `sensors` step):** motion sensors, presence sensors, occupancy sensors,
  scanner areas, Disable camera presence (zone tier + has_camera + now the hold), Room cameras (fusion), **Cameras hold
  occupancy (new)**. One new field. Nothing else is exposed (the 300 s zone camera timeout and the room occupancy timeout
  stay where they are).
- **Default rooms:** the operator lists them after D0 (§8 Q1). Recommendation: none on ship day except rooms where D0 (c)
  shows the hold covers a known miss with no patio / glass exposure in (f).
- **Trip-wire:** a per-room counter `camera_hold_ticks_today` (unrecorded attribute on the room's
  `sensor.<room>_unavailable_entities` diagnostics or the occupancy sensor attrs, whichever already carries
  `occupancy_source` diagnostics; pick at build and name it in the README) and one INFO per room per day on the first
  hold. No NM: zero holds in an opted-in room is a finding only when the room's camera produced person edges that day;
  the README Live row checks it by query.

#### Acceptance criteria
- **Verify:** default room + camera `on` + motion off → room stays vacant, `occupancy_source` never `camera`, no HVAC
  evidence stamp (INV-HOLD-OPT-IN); opted-in room → the v3.5.1 behaviour exactly (golden from develop with extras
  injected); opted-in + Disable camera presence → no hold.
- **Verify (discriminating):** the extras list for a default room is NON-empty after D1 (so the test proves the gate,
  not an empty lookup). A test with an empty lookup would pass under both the fix and the old bug; it does not count.
- **Test:** `test_room_camera_hold_opt_in.py::test_default_room_never_holds_on_camera`,
  `::test_opted_in_room_holds_like_v351`, `::test_disable_camera_presence_wins`,
  `::test_hold_gate_does_not_shrink_stream_extras`, `::test_options_flow_round_trip_camera_hold`,
  `::test_default_room_dead_extra_camera_stays_vacant` (a default room whose extra camera is stream-dead, view HELD,
  last reading `on`: room stays vacant; the dead-input-holds rule never reaches a default room). Mutation: delete the
  gate → `test_default_room_never_holds_on_camera` RED.
- **Live:** for each default room with a D0 camera, `binary_sensor.<room>_occupied` shows no `occupancy_source: camera`
  over the first day (recorder query); for each opted-in room, at least one `camera` source row on a day its camera saw a
  person (or the README states the room had no camera person edge that day).

### D3. Zone camera tier on, with the person-only guard

- **D3a.** No new switch: D1 makes `_discover_zone_cameras` find cameras. Per-room brake stays
  `CONF_DISABLE_CAMERA_PRESENCE` (already honoured at `presence.py:5221-5246`).
- **D3b (person-only guard, from `PLANNING_zone_camera_person_only_guard.md` D1 + a registration twin).** One pure helper
  `camera_resolver.is_person_detection_entity(ent_reg, eid)` = registry entry exists and `original_device_class` (or
  `device_class` override) is not `motion`. Used (1) at `_discover_zone_cameras` before `register_camera` (skip + one
  WARN per entity), (2) in `check_zone_occupancy_confidence` Source 3 (`presence.py:~2466`, skip). The guard plan's D2
  (ingestion warning in `hvac_zones`) and D3 (config-flow selector) stay parked there.
  Note the configured-mode area map already holds only person-suffix entities; the guard bites in full-scan mode
  (`_discover_full_scan` files any `platform == frigate` binary sensor) and on operator `zone_cameras` picks.
- **D3a' (camera roles admitted to the zone tier).** Rule: the zone tier registers a camera only when its configured
  `camera.*` entity is on the integration's INTERIOR list (`CONF_CAMERA_PERSON_ENTITIES`) and on neither
  `CONF_EGRESS_CAMERAS` nor `CONF_PERIMETER_CAMERAS`. The role comes from those configured lists, matched by registry
  DEVICE (`entity.device_id` of each configured `camera.*` entity), never from a name; a person sensor inherits the role of
  its device. A device on both an interior and an egress/perimeter list is excluded (door cameras see every departure).
  Implementation: `CameraIntegrationManager` records the role set per device while building the map
  (`_discover_from_configured_cameras` already holds the three lists, `camera_census.py:1107`); a new getter
  `get_interior_cameras_for_area(area_id)` returns only interior-role infos; `_discover_zone_cameras` calls it. The room
  hold (D2), has_camera and the stream extras keep the full map. Full-scan mode (no configured lists) admits nothing to
  the zone tier (no role is known; fails closed). Test `::test_zone_tier_excludes_egress_and_perimeter_roles`,
  `::test_zone_tier_full_scan_admits_nothing`.
- **D3c (camera-free AWAY decision view, review HIGH 1 + HIGH 2).** One new `ZonePresenceTracker` property
  `occupied_excluding_camera` = the tracker's mode computed with the Tier-2 camera term removed: True iff the mode
  machinery (overrides, SLEEP pin) yields OCCUPIED from BLE or Tier-1 alone (implementation: `_derived_mode` gains a
  keyword `include_camera=True`; `mode_excluding_camera` mirrors `mode` with `include_camera=False`). Also
  `_zone_night_raw(t, include_camera=False)` for the night limb inside the AWAY input. Readers moved to it:
  - `any_zone_occupied_for_empty` (`presence.py:7731-7741`): OCCUPIED limb and the SLEEP night-raw limb both camera-free;
  - `any_indoor_zone_occupied` (path β, `:7704-7708`) and its SLEEP night-signal fallback (`:7759-7765`);
  - the `any_zone_occupied` term of `has_people` (`:1411-1432`) whenever `current_state` is AWAY (ARRIVING trigger);
    outside AWAY it keeps the camera-inclusive view (it decides HOME_* vs AWAY nowhere else; verify at build, and if any
    other non-AWAY state reads it as an AWAY input, move that read too);
  - `camera_census._any_zone_occupied_snapshot` (`:2522`, read at `:2206-2221`): `mode_excluding_camera == "occupied"`.
  Kept camera-inclusive: zone display / `sensor.zone_<z>_presence_status`, `raw_occupied` for the WAKING sustained gate
  (`:7719`, sized by D0 (e), §8 Q5), the night signal for SLEEP hold outside the AWAY input, D6. Note on develop parity:
  develop registers no zone camera, so the camera-free view equals today's mode on every input; that is what makes
  INV-AWAY-UNCHANGED testable as a golden.
  Tests: `test_zone_camera_away_unchanged.py::test_nobody_home_edge_identical_d3_on_off`,
  `::test_beta_edge_identical_d3_on_off` (LOST tracker, camera `on` then off, then 300 s tail and a stream-dead hold:
  same β edge time), `::test_alpha_untouched`, `::test_arriving_while_away_identical_d3_on_off` (perimeter-free interior
  camera `on` while AWAY with α off: no new ARRIVING), `::test_away_golden_replay` (recorded evidence fixture incl. 11-14,
  edge list equal with D3 on/off), and
  `test_census_no_self_corroboration.py::test_frigate_ghost_not_corroborated_by_own_zone` (review repro: Frigate count 1,
  Protect 0, no face, no BLE, Tier-1 quiet, the Frigate person sensor `on` registered in its zone tier → census 0, as
  develop; `DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE` True). Mutation: point any one of the five reads back at `mode` → its
  named test RED.
- **Trip-wire:** zone camera tier silence. Per zone with registered cameras, `camera_detections_today` (unrecorded
  attribute on `sensor.zone_<z>_presence_status`); one LOW stuck-signal NM `kind=zone_camera_tier_silent` when a zone with
  ≥ 1 registered camera has 0 detections in `ZONE_CAMERA_TIER_SILENT_NM_HOURS` (rung 1, 72; 0 = off) while its cameras'
  person sensors had ≥ 1 `on` edge in the same window (so a quiet zone does not page; a broken subscription does).

#### Acceptance criteria
- **Verify:** zones from D0 (b) register exactly those person sensors; a `device_class: motion` Frigate entity (e.g. the
  2026-06-08 `binary_sensor.family_room_motion_3` shape) is neither registered nor counted in Source 3.
- **Test:** `test_zone_camera_tier_device_area.py::test_zone_registers_device_area_cameras`,
  `::test_opted_out_room_area_skipped`, `::test_motion_class_entity_not_registered`,
  `::test_source3_skips_motion_class`, `::test_silent_tier_tripwire_needs_camera_edges`.
- **Live:** `sensor.zone_<z>_presence_status` `cameras` matches D0 (b); within a day, `camera_detections_today` > 0 for
  each zone whose cameras saw a person (recorder); no `zone_camera_tier_silent` page.

### D4. Census: decided by D0

The arithmetic (from code, §1.3 #1): today every interior camera contributes individually (sum). With areas:
(i) same-area cameras collapse to the max, which is ≤ their sum; (ii) BLE cancel subtracts `min(area_max, ble_here)` ≥ 0;
(iii) the stuck discount removes a term. All three are monotone non-increasing, so the census paths can only report the
same or fewer people. The house-state reach is therefore DOWNWARD: fewer `unidentified_count` minutes > 0 means path α
AWAY can fire where it was blocked, `guest_reason` `unidentified_persistent` and `visitors_present` path A fire less. GUEST
itself follows the night-stay latch over the DB (presence doc §2 step 3) and does not read `unidentified_count`.
(iv) The one UPWARD path, census divergence corroboration through `_any_zone_occupied_snapshot`, would let a camera
corroborate itself once D3 registers it (review HIGH 2). It is closed by construction: the snapshot reads the camera-free
view (D3c, INV-NO-SELF-CORROBORATION), so INV-CENSUS-DOWN holds with D3 on.

Branches (D0 picks one by a HARD gate; both ship behind `CENSUS_CAMERA_AREA_FROM_DEVICE`, rung 1):
- **Gate:** D4-CORRECT only if the D0 (d) contradicted-zero table has **zero** contradicted minutes over the 7 days
  (oracle (1)-(4) named in D0 (d); threshold 0, no tolerance) AND the operator accepts the hidden-second-person table.
  One contradicted minute = D4-KEEP.
- **D4-KEEP (gate fails, or the operator prefers it):** `CENSUS_CAMERA_AREA_FROM_DEVICE = False`. The census reads area None for every CameraInfo
  through ONE helper `_census_camera_area(info)` at the three sites (`:2078`, `:3072`, `:6302`), so the census is
  bit-for-bit today's while rooms and zones get D1. Test: a develop golden of `_calculate_house_census` +
  `_get_unrecognized_camera_count` + the watchdog over a recorded fixture (incl. 11-14 samples), equal after D1.
- **D4-CORRECT (gate passes):** `CENSUS_CAMERA_AREA_FROM_DEVICE = True`, so per-area max and BLE cancel apply as their own plans
  designed (v5.9.0 D-A; census BLE cancel I1-I3).
- **Both branches:** `CENSUS_STUCK_CAMERA_DISCOUNT_ENABLED` (rung 1, **False**) keeps the stuck watchdog notify-only
  (today's behaviour, `notify_only_reason` becomes `discount_disabled`). Why off: a still guest (sleeping, reading) in a
  room whose only sensors are motion-class (ZV, PIR: cannot hold a still person, SENSOR_FLEET_CLASSES Rule 1) is
  "uncorroborated" after `CONF_STUCK_CAMERA_HOURS`, so the discount would drop a real body and could open AWAY α. Revival
  trigger: D0 (h) or a later probe shows every would-be discount was a real stuck camera.
- House-state rule: Tier 2-DB, three reviews (framings below), operator checkpoint before deploy with D0 (d) in hand.

#### Acceptance criteria
- **Verify (both):** `_census_camera_area` is the only area read in the census (AST/grep test); stuck discount never
  applies with the knob False.
- **Verify (D4-CORRECT, discriminating):** over the recorded fixture, after ≤ before on every sample (INV-CENSUS-DOWN);
  and on the 11-14 party samples the per-hour delta equals the D0 (d) table. A test showing only "count changed" would
  pass under a raising bug too; it must assert the direction and the value.
- **Test:** `test_census_camera_area.py::test_keep_branch_golden_identical`, `::test_correct_branch_never_raises`,
  `::test_same_area_max`, `::test_ble_cancel_applies_with_area`, `::test_stuck_discount_off_by_default`,
  `::test_census_area_single_helper`.
- **Live:** `sensor.universal_room_automation_persons_in_house` attributes: `area_raw_max_pre_cancel` keyed by real areas
  (D4-CORRECT) or still empty (D4-KEEP); `unidentified_count` over the first day within the D0 (d) predicted band; zero
  `camera_stuck` rows with `discounted: true`.

### D5. Seams (each a named contract, single owner)

| Seam | What changes | Resolution |
|---|---|---|
| 3b `CameraTwinHealth` | Wr grows to the camera rooms' area cameras; U shrinks; room S1/S2 pages for those devices go through the room page policy (owner suppresses rooms only for groups it pages, `pages_device`) | No 3b code change. D0 (g) lists the moved groups; build adds `test_twin_scope_after_device_area` (every census/zone camera still in Wr ∪ U, INV-DEAD-INPUT, no group paged twice). Presence doc + contract §3 (b) numbers corrected in the build commit. Owner: 3b code as is. |
| Interior vision (`PLANNING_vision_interior_sightings.md`) | Its groups resolve area entity-then-device already (§214) and never read this map; its D4 agreement compares with `guest_cam`, which goes down under D4-CORRECT | Interior plan notes the baseline shift; its D4 flip bar is measured after this ships. Owner: interior plan. |
| NVR witness W2 / W5b | W5b moves `_cross_validate_platforms` behind a byte-identical house-count test over a recorded fixture | The W5b fixture is recorded AFTER this ships (else it pins the old sum). NVR plan rewrite (harmonization C13) gets that line. Owner: NVR plan. |
| Foyer device move (HA-FOYER-CAMERA-AREA-ALIGN-1) | Takes effect here: foyer fisheye (Frigate + Protect devices, area `foyer`) maps to the Foyer room and its zone | D0 (a) shows it; the Foyer room is off by default (D2); the Foyer Automation switch reads off (harmonization D5). Card disposition: met when D1 Live shows the Foyer room `has_camera` true. |
| Crossing vision P3 (P3-D8 anchor, ledger census tick) | Anchor reads substrate Tier-1 + stream view, not the map: unchanged. Ledger `R` and the census camera body total feed `guest_vis` / agreement; the body total can drop under D4-CORRECT (zero-ness unchanged except BLE cancel) | No P3 change. P3-D6 / P2-D10 scorer baselines read after this ships, and the crossing plan cites this plan for the shift. Owner: crossing plan. |
| Perimeter / egress / transit | Not consumers (§3.2) | None. |

---

## 5. Numbers and knobs

| Knob | Rung | Default | Why this rung | Kill semantics |
|---|---|---|---|---|
| `CAMERA_AREA_DEVICE_FALLBACK_ENABLED` | 1 | True | correctness rule, change needs review | False = develop map byte-identical |
| `CONF_ROOM_CAMERA_HOLD` | 2 (room options) | False | per-room structure, set once after D0 | False = no camera hold in that room |
| `CONF_DISABLE_CAMERA_PRESENCE` (REUSED) | 2 | False | existing per-room mute | True = no zone camera, no has_camera, no hold |
| `CENSUS_CAMERA_AREA_FROM_DEVICE` | 1 | set by D0 | house-state input, review only | False = census bit-for-bit today |
| `CENSUS_STUCK_CAMERA_DISCOUNT_ENABLED` | 1 | False | safety (still guest) | False = notify-only (today) |
| `ZONE_CAMERA_TIER_SILENT_NM_HOURS` | 1 | 72 | trip-wire window | 0 = no page |
| `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS` (REUSED, `presence.py:150`, 300) | 1 (module literal today) | unchanged | not tuned in this cycle; D0 (e) reports its AWAY cost | n/a. Flag: it is a module-private literal, not in `const.py`; leave as is unless D0 shows a cost (non-goal) |

---

## 6. Non-goals

- Room camera hold in any room (operator 2026-11-15: "Too inaccurate in every room. We have enough with the other sensor
  fusion.").

- No change to the hold's semantics (create + extend stays as v3.5.1) other than the opt-in gate.
- No switch of the hold source to `CONF_ROOM_CAMERAS` (operator-declared fusion); the approved design is the area map.
- No new rediscovery listener on device-registry changes.
- No change to the person-suffix classification in `resolve_camera_entity` (REGISTRY-NOT-NAMES-1).
- No code for the patio leak (config fix, card CENSUS-PATIO-THROUGH-GLASS-1).
- No face-arrival work (FACE-ARRIVAL-REBUILD-1 owns it; not a consumer).
- No change to the 300 s zone camera timeout, stream-health caps, the D6 failsafe or any HVAC write path.
- The guard plan's D2 (hvac_zones ingestion warning) and D3 (selector) stay parked.

---

## 7. Delivery changes to name for the operator (charter rule 3)

1. AWAY is NOT slowed and no new ARRIVING is raised while AWAY (INV-AWAY-UNCHANGED). Without D3c the zone tier would
   have delayed nobody-home AND path β by the 300 s camera timeout plus up to 900 s of stream-dead hold (α reads no zone);
   D3c removes the camera tier from every AWAY input, so there is nothing to accept.
2. WAKING can come earlier when an interior zone camera sees someone at the end of the sleep window, and a camera in its
   timeout can hold the SLEEP night signal (outside the AWAY input). D0 (e) sizes both; §8 Q5.
3. Census (D4-CORRECT only): fewer unidentified-person minutes; AWAY α can fire in moments it was blocked by a summed
   count; `visitors_present` cam leg fires less.
4. 3b: some dead-camera pages come from rooms instead of the house owner (same keys, same dedup).
5. Opted-in rooms: lights, fans and HVAC follow cameras, including creating occupancy.

---

## 8. Operator questions (with recommended defaults)

| # | Question | Recommended default |
|---|---|---|
| Q1 | Which rooms get "Cameras hold occupancy" on ship day? | None until D0 (c)/(f) is shown; then only rooms whose cameras watch only that room (no glass, no doorway into another area) and where D0 shows held minutes that match real presence |
| Q2 | Census: keep today's summed count behind the knob (D4-KEEP) or ship per-area max + BLE cancel (D4-CORRECT)? | The hard gate decides (D4): CORRECT only with zero contradicted minutes; you confirm the hidden-second-person table |
| Q3 | Keep the stuck-camera census discount off? | Yes (still-guest risk) |
| Q4 | Apply the family-room Frigate mask + Protect zone (CENSUS-PATIO-THROUGH-GLASS-1) before the zone tier ships? | Yes; it is config only and D0 (f) sizes it |
| Q5 | Should the zone camera tier feed WAKING (earlier wake on an interior camera) and the SLEEP night signal? (AWAY is not a question: it stays camera-free.) | Yes if D0 (e) shows WAKING moves only on real wakes; if any moved WAKING edge was a camera with nobody up, make WAKING camera-free too (same property, one more read) |
| Q6 | Party head count on 11-14 by hour (oracle (4) for the D4 gate) | Please supply rough counts; without them oracle (4) is skipped and (1)-(3) decide |

---

## 9. Tier, reviews, sequence

- **Tier 2-DB + house-state rule** (operator). Plan review: one adversarial plan review + framing G before build
  (Tier 2 plan rule; G mandatory inside the arc). If D0 sends D4 to D4-CORRECT, the plan review re-runs on D4 only.
- **Code reviews (three, framing-disjoint) + G:** A = local correctness of the five area sites, the hold gate, the census
  helper; B = cross-coordinator ripple (presence house state, HVAC evidence/fast path, 3b pages, census → AWAY α), restart
  and rediscovery; D = adversarial completeness: re-enumerate every reader of `CameraInfo.area_id`, `_cameras_by_area`,
  `get_person_sensor_for_area`, `has_camera` and try to break INV-HOLD-OPT-IN and INV-CENSUS-DOWN with a legal config.
  C-style per-site source mutation by `ura-reviewer-mutation` on the five D1 sites, the D2 gate and the D4 helper.
- **Sequence:** D0 → operator answers Q1-Q5 → plan edits → one build (D1+D2+D3+D4 together, `ura-builder`, worktree) →
  reviews → operator checkpoint (house state) → deploy attended, not while the house sleeps → README live table.
  Harmonization §4 puts the build "next week, before interior ship 3 and any F-LEAD"; D0 can run now (no builder slot).
- **Docs in the build commit:** presence state of play (header entry, §1 consumer rows for the hold and zone tier, §10
  ledger entry for "census computes a house-wide max under ''" and the face-arrival consumer claim), identity manual §4.2
  (census area semantics), contract §3 INV-MISSING-NOT-ZERO (b) U numbers, HVAC doc §3.1 one line (camera hold is opt-in
  per room), card consumer map corrected.

---

## 10. Plan review rev 2 finding map

| Finding (review 2026-11-15) | Fixed in |
|---|---|
| HIGH 1: zone tier slows nobody-home and β; bound 300 s + 900 s; Q5 accept-by-default; D0 (e) not split | §2 INV-AWAY-UNCHANGED; §3.2 C5; D3c (camera-free view, five reads, tests); D0 (e) veto_path split; §1.6; §7 item 1; §8 Q5 replaced |
| HIGH 2: self-corroboration via `_any_zone_occupied_snapshot` | §2 INV-NO-SELF-CORROBORATION, INV-CENSUS-DOWN restated; D3c (snapshot read + repro test); D4 (iv) |
| MEDIUM 3: egress / perimeter cameras join the zone tier | D3a' (interior roles only, by registry device against configured lists; full scan admits nothing) |
| MEDIUM 4: WAKING / SLEEP not measured | D0 (e) WAKING-moved and SLEEP night-raw rows; §7 item 2; §8 Q5 |
| MEDIUM 5: unsized gates | D0 (d) contradicted-zero oracle (1)-(4) + hidden-second-person table; D4 hard gate (threshold 0); §8 Q2, Q6 |
| LOW 6: six `CameraInfo(` sites | §2 INV-MAP lists all six, `:919` already compliant |
| LOW 7: dead extra camera in a default room | D2 test `test_default_room_dead_extra_camera_stays_vacant` |

# PLANNING — Census Occupancy Estimator (bounded floor / ceiling / estimate) + `guests_present` flag

**Status:** DRAFT plan, not reviewed. No code is changed by this document.
**Author:** ura-planner, 2026-10-04.
**Trigger:** `docs/planning/AUDIT_census_subsystem_2026_10_04.md` (census read 2–3 against a truth of 10–12 on 10-03). The plan covers recommendations R2, R4 and R7, depends on R1 and R3, and supersedes the parked card `CENSUS-GUEST-FLOOR-1`. That card's revisit trigger ("after the fix ships + one real gathering, if guest counts still under-read materially") **fired on 10-03**.
**Canonical domain reference:** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. This plan was written against it. §11 lists the corrections this plan makes to it.

---

## 0. Operator rulings this plan implements (2026-10-04)

1. Cameras count people well. Names are secondary and depend on faces. **Counting must never need a name or a face.**
2. "Guests present" becomes a **flag that is independent of house state**. The house can be SLEEP with guests present. Today guest is a house state, and the sleep branch blocks it (`presence.py:1305-1310`, since v3.6.0).
3. Two feeds drive that flag:
   - occupied designated guest rooms (Guest Bedroom 1 and 2 are `room_is_guest_room=true`, `core.config_entries` lines 306 and 337);
   - guest phones on SSID **Revel**. The `_get_wifi_guest_count` recency filter is broken and must be fixed (`camera_census.py:5520-5536` uses `last_changed`).
4. Fix the dead face lookup (`camera_census.py:3216`, `er.async_entries_for_platform`). This is audit R1, carded separately. It is a prerequisite only for the identity attributes, not for counting.
5. Dedup door crossings across the Protect, Frigate-binary and Frigate-count legs. This is audit R3, a hard prerequisite.
6. Design ask: a **bounded estimate**.
   - **FLOOR** = evidence now, aging out over about 15–30 min.
   - **CEILING** = door entries minus exits, with group size; reset when the house is verified empty; decays without reconfirmation over a 4–6 h window.
   - **Estimate** sits between the two.
   - It must stay sane in the stress case of **40 people circulating for 6 h**.

---

## 1. Tier classification

**This is a split program. The tier is chosen per phase, because the risk is not uniform.**

| Phase | Deliverables | Tier | Why |
|---|---|---|---|
| **Measure** | D0 (replay probe), D2-probe (indoor overlap probe) | none (read-only probe) | Measure-Before-Build. D0 is the go/no-go for everything after it. |
| **Shadow** | D2 (overlap table), D3 (estimator in shadow), D4 (Revel connected-now) | **Tier 2-DB** | D3 adds new persisted state that must survive restart, plus new sensors. It reads the shared census primitive but **writes no consumer-visible value**: the payload keys are additive and `interior_count` stays byte-identical. The DB/restart surface earns the three framings, but nothing actuates. |
| **Promote** | D5 (`guests_present` flag + migration of GUEST consumers), D6 (estimate replaces snapshot `total_persons`; AWAY-veto binding) | **Tier 3** | This changes the **house state machine's vocabulary**: GUEST stops being an inferred state. It also changes the count that feeds the **AWAY veto**, HVAC preset composition, security arming (`security.py:173`), NM perimeter severity (`const.py:2307`) and Bayesian learning suppression (`__init__.py:2893`). This is a cross-coordinator trust-hierarchy ripple at a state-machine × time seam (decay windows, restart restore), which is the exact ingredient class behind the worst recent bug families. Audit F5 (AWAY latched with 11 people home across a restart) shows the restart seam is already live-broken. One missed consumer means GUEST behaviour silently disappears, or the house goes AWAY with people inside. |
| **Later** | D7 (AI-vision door group count) | Tier 2 (parked) | Optional. Advisory only, under manual §5.5 doctrine. Parked with an evidence trigger. |

**Tier 3 additions that apply to D5/D6:** two plan reviews before the D5 build (completeness and adversarial build-prediction), four framing-disjoint build reviews (A local / B state-machine / C per-site source-mutation / D adversarial completeness), orchestrator re-grep of every GUEST reader before ship, and an operator checkpoint before deploy.

---

## 2. Institutional context verified

### 2.1 Greps run and results (REUSED vs NEW)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Interior camera person counts | **REUSED** | `CONF_CAMERA_PERSON_ENTITIES` (`const.py:1973`). Live value: 12 entities (`core.config_entries:268`): playroom, master_hallway, staircase, foyer_fisheye, family_room, upstairs_hall, stairs_top, each with HR-channel and Frigate variants. Count producer `_calculate_house_census` `camera_census.py:1690`. |
| Per-area max / cross-area sum dedup | **REUSED, then EXTENDED** | Catalog C2 (`CATALOG_cross_correlation_primitives.md` §Tier 2). The "area" is today's overlap proxy. `CONF_CAMERA_OVERLAP_GROUPS` was **designed and cut** in `PLANNING_census_overcount_dedup_decay.md` (07-07; see the RESEARCH doc §5 table). |
| Interior overlap table | **NEW** | Grep of `OVERLAP\|overlap_group\|INTERIOR_ADJACENCY` across the component returned 0 hits, apart from an unrelated energy comment at `energy_battery.py:3874`. The method is reused from `AUDIT_exterior_camera_adjacency_probe.md` → `EXTERIOR_ADJACENCY_GRAPH` (`const.py:2373`). |
| Hold/decay machinery | **REUSED (concept); not reused for the floor** | `_apply_hold_decay` `camera_census.py:5026`. `CENSUS_PEAK_SUSTAIN_SECONDS=15` (`const.py:3544`). `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES=3` (`const.py:3528`). The floor needs a *window-max-minus-exits* operator, not peak-hold, because peak-hold cannot subtract observed exits. |
| Door flow producer | **REUSED** | `TransitValidator._resolve_direction` `transit_validator.py:1724`. Persisted to `person_entry_exit_events` (`database.py:793-808`). Physical-leg dedup `:816-828` (`TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS=5.0`, `const.py:2712`). Stem dedup `:1733-1742` uses an **inline literal `5.0`**, which violates Numbers-Get-Knobs; R3 must fix it. |
| Door group size | **REUSED (entities exist)** | Frigate `sensor.<cam>_person_count` exists for all 5 egress cameras: madrone_g6_entry, doorbell_lite, front_door_aerial, garage_a, garage_b (`core.entity_registry` 26332-26373). No URA code reads them for group size today. NEW logic, existing input. |
| Guest-room occupancy | **REUSED** | `_guest_room_gate_armed` `presence.py:5303`. `_is_known_person_in_room` (live re-check). `CONF_ROOM_IS_GUEST_ROOM` (`const.py:402`). |
| Revel guest phones | **REUSED, FIXED** | `_get_wifi_guest_count` `camera_census.py:5383-5548`. `CONF_GUEST_VLAN_SSID` (`const.py:3553`), live value `Revel`. `WIFI_GUEST_RECENCY_HOURS=4` (`const.py:3638`; the docstring at `:5404` still says 24h and is stale). |
| Egress-face guest identities | **REUSED** | `_get_egress_guest_ids_fresh` `camera_census.py:5695`. `EGRESS_FACE_UNION_TTL_S=300` (`const.py:2734`). |
| Body-reinforcement TTL bucket | **ADJACENT, SUPERSEDED-BY-THIS** | `PLANNING_egress_interior_count_reinforce.md` D2 (`_egress_body_reinforcements`, stem-keyed TTL) is a short-TTL special case of this plan's ceiling. Card `EGRESS-INTERIOR-COUNT-REINFORCE-1` should be folded in, not built separately. |
| `guests_present` flag | **NEW (an entity), REUSING existing gates** | No `guests_present`/`guest_present` symbol exists (grep of `*.py` returned 0). `binary_sensor.ura_presence_coordinator_guest_mode` (`binary_sensor.py:2412-2445`) exists but is defined as `house_state == GUEST`. **Recommendation:** re-point *that* entity to the flag rather than add a second entity (it keeps the `entity_id`; see D5). |
| Manual guest override | **REUSED** | `select.ura_presence_coordinator_house_state_override`, `services.yaml:21` ("guest" option), `HouseStateMachine.set_override`. |
| Census sensors | **REUSED + 3 NEW** | `persons_in_house` / identified / unidentified (`sensor.py:~3581-3760`). NEW: `occupancy_floor`, `occupancy_ceiling`, `occupancy_estimate` (shadow). They could be attributes instead; see operator question Q6. |

### 2.2 Prior planning docs consulted
- `AUDIT_census_subsystem_2026_10_04.md`: full read. Ground truth, F1–F7, R1–R8, mermaid diagram. This is the root of this plan.
- `RESEARCH_guest_actuation_and_census.md`: §4–§8 read. The inventory of what GUEST does is reused in §6 of this plan. G1/G4/G6 history, and the warning against re-admitting the WiFi floor *on an over-reading path*. That premise is now inverted (10-03 was an under-read), so the warning is answered, not ignored.
- `CATALOG_cross_correlation_primitives.md` Tier 2 (C1–C16): the verdict "EXTEND, do not roll a new primitive" is honoured. The estimator is a new **combiner** over existing producers.
- `AUDIT_exterior_camera_adjacency_probe.md`: the method template for the indoor overlap map (§5), including the operator-ratification step.
- `PLANNING_egress_interior_count_reinforce.md`: adjacent; folded in (see above).
- `PLANNING_guest_census_correctness.md` (GUEST-CENSUS D1/D2, 2026-08-16): the reason Path A is computed but not consumed (`presence.py:5886-5892`).
- Kanban: `CENSUS-GUEST-FLOOR-1` (`kanban.data.yaml:16899`) is parked and its trigger has fired → SUPERSEDED by D3+D4. `EGRESS-INTERIOR-COUNT-REINFORCE-1` (`:16687`) → fold into D3. `CENSUS-GHOST-DEDUP-1` (`:16776`) → ADJACENT (the per-area BLE-cancel the floor reuses). `CENSUS-FACE-RESOLVER-MIGRATE-1` (`:19861`) → candidate home for R1; the orchestrator's adjacency sweep decides.

### 2.3 Memory bodies relevant (index lines read; bodies to be pulled by the plan reviewer)
`reference_frigate1_retired_2suffix_permanent` (do not string-build `_2`), `reference_protect_face_latency_async`, `reference_egress_face_coverage_7pct_not_a_ceiling`, `project_guest_mode_false_positive_backlog`, `project_presence_guest_latch_and_veto_gap` ("do NOT re-plan" D1/D1b; this plan *removes* the latch it fixed, so the reviewer must confirm I-D1 is superseded and not regressed), `reference_pooloverhead_four_integrations`, `feedback_no_restart_during_sleep`, `project_single_user_no_backcompat` (now CHANGING: a 2nd install goes live 10-03/04, so optional inputs such as Revel and guest rooms must degrade gracefully).

### 2.4 Design docs read
`IDENTITY_FUSION_CAMERAS_MANUAL.md` §1–§4 (platform roles, `_2` rules, cross-corroboration doctrine, resolver ladder, TransitValidator). `house_state.py:60-139` (states, transitions, hysteresis).

### 2.5 Code surveyed (read, with line ranges)
- `presence.py`: 1230-1349 (infer AWAY/ARRIVING/GUEST/SLEEP ordering), 5290-5410 (both gates), 5840-5910 (gate composition).
- `camera_census.py`: 3192-3231 (dead face map), 5383-5548 (WiFi), 5640-5770 (enhanced total chokepoint).
- `transit_validator.py`: 795-834, 1724-1748.
- `house_state.py`: 60-139.
- `hvac.py`: 3928-3974. `hvac_const.py`: 220-275, 1229-1239.
- `preset_overrides.py`: 40-155. `dynamic_preset.py`: 840-874. `energy.py`: 7371-7389.
- `security.py`: 160-176. `__init__.py`: 2875-2899. `const.py`: 2290-2311.
- Live config: `/Users/okosisi/ha-config/.storage/core.config_entries` and `core.entity_registry`, read-only over the Samba mount.

### 2.6 Config-first check (gate step 1b)
- **Interim, zero code:** for a known party, the operator can set `select.ura_presence_coordinator_house_state_override` → guest. That is the only lever today, and it still blocks SLEEP. No knob makes the census count stock instead of snapshot, and no knob makes GUEST coexist with SLEEP. **Code is required.**
- **Config that improves inputs (operator action, not code):**
  - Frigate *zones* on interior cameras would give per-zone counts. No Frigate zone-count entities exist today (registry grep found none).
  - More interior camera coverage (R8).
  - Enrolling Jaya and Ezinne in Protect faces (manual §2.3).

None of these substitute for the estimator.

---

## 3. Literature and prior art (cited; years marked "unverified" where I did not confirm them)

| # | Source | What it establishes | Use in this plan |
|---|---|---|---|
| L1 | Meyn, Surana, Lin, Oggianu, Narayanan, Frewen, *A sensor-utility-network method for estimation of occupancy in buildings*, IEEE CDC **2009**. https://www.ece.ufl.edu/wp-content/uploads/sites/77/archive/spm_files/Papers_pdf/CDC09_2928_FI.pdf (index: https://www.semanticscholar.org/paper/03569a1bd6b1adc6dde1e66450e25ae30f179006) | Flow-only (door-count) occupancy had **~70% average error** at building level. Fusing flow with other sensors and history in a receding-horizon convex estimator cut it to **~11%**. | Pure entries−exits is not enough; it must be fused and bounded. Grounds the floor/ceiling/estimate split, and why the ceiling must be re-anchored by evidence. |
| L2 | Sangogboye & Kjærgaard, *PreCount: a predictive model for correcting real-time occupancy count data*, Energy Informatics 1:12, **2018**. https://link.springer.com/article/10.1186/s42162-018-0016-4 | Camera-based door counters accumulate error. Learning error estimates from history corrected counts in real time, with up to 68% NRMSE reduction against ground truth. | A future refinement: learn per-door bias from verified-empty anchors (D3 records the residual at every reset for exactly this). Not built now. |
| L3 | Kjærgaard group, *Real-time Occupancy Correction Method for 3D Stereovision Counting Cameras*, ACM (SenSys/BuildSys proceedings; year unverified). https://dl.acm.org/doi/10.1145/3274783.3275204 | Same problem class: real-time drift correction of stereo door counters. | Supports anti-windup re-anchoring of the flow integrator to the bounds. |
| L4 | Axis Communications, *AXIS Occupancy Estimator* user help (current product docs). https://help.axis.com/en-us/axis-occupancy-estimator | Commercial practice: "naive" entries−exits mode should be paired with a **scheduled reset**. "Smart" mode filters counting errors and refines after close with full-day analysis. | Industry precedent for reset-on-empty plus filtering. Our "verified empty" is a stronger anchor than a clock reset. |
| L5 | Surveillant.ai, *People counting accuracy* (vendor guide, undated). https://surveillant.ai/guides/people-counting-accuracy | States the drift arithmetic: at 98% per-crossing accuracy, 10,200 in / 9,800 out leaves a phantom 400 at close. Errors **accumulate rather than average out**, and only a genuine empty reset clears them. | Motivates the ceiling **decay** in place of an unbounded integrator (§7.4 stress case). |
| L6 | *Building occupancy estimation with robust Kalman filter*, IEEE (year unverified). https://ieeexplore.ieee.org/document/8287378/ | Kalman-family state estimation over occupancy, robust to outlier counts. | Considered and **not chosen for v1** (§4.3). The bounded design is the deterministic analogue with explicit, inspectable bounds. |
| L7 | *A fusion framework for occupancy estimation in office buildings based on environmental sensor data* (particle filter; year unverified). https://www.researchgate.net/publication/309329930 | A particle filter fusing data-driven and occupancy models gave a 5–14% estimation gain. | Same as L6: deferred. A recorded trigger for revisiting is in §4.3. |
| L8 | *Occupancy Counting with Burst and Intermittent Signals in Smart Buildings*, arXiv:1702.06423 (**2017**). https://arxiv.org/pdf/1702.06423 | Counting from bursty, intermittent sensor signals. This is exactly our camera-visibility regime: people pop in and out of view. | Justifies the window-max floor over an instantaneous floor. |
| L9 | *Indoor occupancy measurement by the fusion of motion detection and static estimation*, Energy & Buildings (ScienceDirect; year unverified). https://www.sciencedirect.com/science/article/abs/pii/S037877882100877X | Fuses a dynamic (flow/motion) estimator with a static (snapshot) estimator through a Kalman filter. | Conceptually the same split as ceiling (flow) vs floor (snapshot). |
| L10 | *People Counting across Multiple Cameras for Intelligent Video Surveillance*, IEEE (year unverified). https://ieeexplore.ieee.org/document/6328005/. Also *Online adaptive learning for multi-camera people counting*, IEEE. https://ieeexplore.ieee.org/document/6460898/ | Partially overlapping FOVs double count unless you find correspondences (homography + similarity). | We have no calibrated homographies. The overlap **group max** (§5) is the coarse, calibration-free substitute, and it biases low (correct for a floor). |
| L11 | *People Counting in Crowded and Outdoor Scenes using a Hybrid Multi-Camera Approach*, arXiv:1704.00326 (**2017**). https://arxiv.org/abs/1704.00326 | Fusing multiple partially overlapping views for crowd counts. | Same as L10. |
| L12 | *Integrating multi-camera surveillance with transductive learning for duplicate removal*, Neural Computing & Applications (**2025**). https://link.springer.com/article/10.1007/s00521-025-11716-2 | Indoor overlapping cameras: duplicates when the same person appears in both views. | Confirms overlap dedup is still an open, learning-heavy problem. We deliberately take the conservative max instead. |
| L13 | Ye, Shen, Lin, Xiang, Shao, Hoi, *Deep Learning for Person Re-Identification: A Survey and Outlook*, IEEE TPAMI 44(6), **2022**, doi:10.1109/TPAMI.2021.3054775. https://github.com/mangye16/ReID-Survey | State of the art in cross-camera Re-ID. | Re-ID would let us count *distinct* people across non-overlapping cameras over time. Frigate/Protect expose no appearance embeddings to HA, so it is **out of reach without new infra**, and it is not needed for bounds. Recorded as the long-run path to tightening the floor. |
| L14 | Gao et al., *CNN-based Density Estimation and Crowd Counting: A Survey*, arXiv:2003.12783 (**2020**). https://arxiv.org/abs/2003.12783. Also Sindagi & Patel, arXiv:1707.01202 (**2017**). https://arxiv.org/pdf/1707.01202 | Detection-based counting under-counts under occlusion. Density-map methods are needed for dense scenes. | Our cameras are detection-based (YOLO), so occluded groups under-count. That is the reason the door group-size term takes the **max** across legs and frames, and the reason D7 (vision group count) exists. |
| L15 | Frigate docs, MQTT (current). https://docs.frigate.video/integrations/mqtt | `frigate/<camera>/<object>` and `frigate/<zone>/<object>` publish an **object count**; `.../active` publishes active (moving) count. The `frigate/events` payload carries `id` (tracked-object id), `sub_label`, `current_zones`, `entered_zones`. | Inventory §4. The count includes stationary people, which is good for the floor. Tracked-object ids exist on MQTT but are **not** surfaced as HA entities. |
| L16 | Frigate docs, Zones (current). https://docs.frigate.video/configuration/zones | Zones key off the bottom-center of the bbox. `inertia` (frames) and `loitering_time` (s) filters. | Interior zones are a config-only upgrade path (§2.6). |
| L17 | Home Assistant, UniFi Protect integration docs (current). https://www.home-assistant.io/integrations/unifiprotect/. Line-crossing feature request: https://community.home-assistant.io/t/unifi-protect-crossing-lines-support/453196. HA core PR #183372 (vehicle line-crossing events): https://github.com/home-assistant/core/pull/183372 | Protect exposes per-type detected-object binary sensors and smart-detection **event** entities. **No count sensors.** Person line-crossing is not exposed as a dedicated entity; the community uses Alarm Manager webhooks. | Inventory §4. Protect is a binary corroborator only, never a count source. |
| L18 | HA core `unifi/device_tracker.py` (dev branch, fetched 2026-10-04). https://github.com/home-assistant/core/blob/dev/homeassistant/components/unifi/device_tracker.py | A wireless client is `home` iff `now − client.last_seen ≤ option_detection_time`. Attributes when connected include `essid`, `is_guest`, `ip`, `ap_mac`, `mac`, `host_name`/`name`, `oui`. **No `last_seen` attribute is exposed.** | Root cause of R7: `last_changed` is the *connect* time, so "connected > 4 h" was misread as "resident". The correct "connected now" is simply `state == home`; UniFi already applies `last_seen` freshness. Fix in D4. |

**Not found:** I found no occupancy-specific *set-membership / interval-estimation* reference (one search was inconclusive). The floor/ceiling construction here is an engineering design, not a cited method.

---

## 4. Inventory: person-detection capabilities actually available

**Verification basis:** read-only `core.entity_registry` and `core.config_entries` over the Samba mount, plus vendor docs (L15–L18). **Not verified live:** recorder state histories. There was no shell in this session, so every per-entity *rate* belongs to D0.

### 4.1 Frigate (Frigate-2; Frigate-1 retired)
| Capability | Entities present | Notes |
|---|---|---|
| Per-camera person **count** | `sensor.<cam>_person_count`. Interior: family_room, foyer_fisheye, master_hallway, staircase, stairs_top, playroom, upstairs_hall, garage_b. Egress: madrone_g6_entry, doorbell_lite, front_door_aerial, garage_a, garage_b. Perimeter: rear_ptz, utilities_ptz, front_side_ptz, back_yard, hot_tub, pool_equipment, g5_bullet, armcrest, reolinkstudybporchptz, madroneptultra, armcrestash41b. Also `madrone_g6_entry_package_person_count` (F3 exclusion) | Bare-suffix names in the registry today; resolve via registry, never string-build (manual §1.1). `foyer_fisheye_person_count` was near-dead in 08-16 (RESEARCH §5); D0 re-checks. |
| Per-camera person occupancy | `binary_sensor.<cam>_person_occupancy` (interior, bare) / `_person_occupancy_2` (perimeter/egress) | Mixed suffix, as the manual describes. |
| Per-zone counts | **none in registry** | Requires Frigate zone config. Optional operator upgrade. |
| Active (moving) count | **none in registry** | MQTT-only per L15. |
| Tracked-object id / sub_label | MQTT `frigate/events` only | Not surfaced as HA entities. Out of scope for v1. |
| Face name | `sensor.<cam>_last_recognized_face[_2]`, `sensor.frigate_<name>_last_camera[_2]` | Identity only. The census face-map read is dead (R1). |

### 4.2 UniFi Protect
| Capability | Entities | Notes |
|---|---|---|
| Person detected (binary) | `binary_sensor.<cam>_person_detected`. Interior: family_room, foyer_fisheye, master_hallway, playroom, stairs_top, upstairs_hall, `camera_protect_garagehallway`. Egress: garage_a, garage_b, doorbell_lite, front_door_aerial, madrone_g6_entry, g4_doorbell_pro | A binary corroborator only. Catalog C1: "binary is floor-only — binary>frigate never raises count". |
| Count, line-crossing, zone count | **not exposed** (L17) | Line-crossing is reachable only through Alarm Manager webhooks, which deliver empty bodies here (manual §2.3). |
| Face name | via Protect API/MCP only, on 2 cameras (manual §2.3) | Identity only. |

### 4.3 Non-camera counters found in the registry (unexpected; flag for the operator)
- `sensor.apollo_mtr_1_fa21b0_zone_{1,2,3}_{all,still,moving}_target_count`: an Apollo MTR-1 mmWave with per-zone target counts. Its room is unknown to this planner. It is a candidate **per-room floor source for a camera-less room** (multi-target mmWave). Operator question Q8.
- `sensor.upzone2_people_count`: a non-URA template or integration. Provenance unknown. Must be verified before any use (Q8).

### 4.4 Phones and identity
- BLE/WiFi/GPS residents: `PersonCoordinator` (manual §2.1). 4 tracked persons.
- Revel SSID UniFi trackers: §3 L18 semantics; D4.
- URA room-level `binary_sensor.<room>_camera_person_detected` (platform `universal_room_automation`, e.g. `core.entity_registry:16821`) are **URA's own derived entities, not camera sources**. They must never feed the estimator, because that would be circular.

### 4.5 Area-mapping facts that matter for overlap
- `camera.family_room` is declared on room **Living Room** (`room_cameras`, `core.config_entries:317`).
- The `playroom` camera feeds room **Game Room** (`camera_person_entities`, `:372`).
- `camera.upstairs_hall_2` is on **Upstairs Hallway** (`:461`).
- Kitchen, Dining, Media, Master Bedroom, Guest Bedrooms and Garage rooms have `room_cameras: []`.

So **guest rooms have no camera**. That makes the guest-room term spatially disjoint from the camera term at any single instant, which §7.2 relies on.

---

## 5. Indoor camera overlap map (D2): method, candidate structure, ratification

The exterior map was built as: transition matrix → simultaneity filter → threshold → operator ratification (`AUDIT_exterior_camera_adjacency_probe.md`). The indoor map needs a **different statistic**, because the question is different:
- **Exterior adjacency** asks: *does one person walk from A to B?* That is a lagged transition.
- **Indoor overlap** asks: *can one person be in A's and B's view at the same instant?* That is a **simultaneous co-occupancy**. Only overlapping cameras need the max-collapse. Adjacent but non-overlapping cameras are correctly **summed**.

### 5.1 Probe (read-only, recorder over ≥7 days of retention; script under `scripts/probes/`, report `docs/planning/AUDIT_interior_camera_overlap_probe.md`)

For each ordered pair (A, B) of interior physical cameras, after resolver-stem collapse of the Frigate and Protect legs:

1. **Simultaneous Jaccard:** J = |on_A ∩ on_B| / |on_A ∪ on_B| over `person_occupancy` on-intervals.
2. **Onset lag:** for each A rising edge, the time to the nearest B rising edge. Overlap shows a median under 2 s. Adjacency shows a lag of 3–60 s.
3. **Count co-movement:** over ticks where both counts are >0, the fraction where `count_A == count_B`. Overlapping views of the same people tend to agree.
4. **Single-resident oracle (discriminating):** windows where exactly 1 BLE resident is home, Ziri-style away days, and no guests. Any co-on interval then **is** one person in two views. This is the cleanest overlap evidence and does not depend on thresholds.

**Classification (rung-1 thresholds, set in the probe and reviewed):** OVERLAP if (J ≥ 0.25 and median lag < 2 s) or the single-resident oracle shows ≥ 3 co-on episodes. Otherwise DISJOINT.

### 5.2 Candidate structure (hypotheses only, NOT asserted; the probe and the operator decide)
From names and room mapping alone, I would *test* these candidate overlap groups first:
- `{foyer_fisheye, staircase}` (foyer stair)
- `{staircase, stairs_top}` (stairwell)
- `{stairs_top, upstairs_hall}` (landing)
- `{family_room}` alone, unless the Living Room camera sees into the foyer
- `{master_hallway}`
- `{playroom}`

I have not seen the floor plan. Every pair above is a guess for the probe to confirm or reject.

### 5.3 Output and governance
`INTERIOR_CAMERA_OVERLAP_GROUPS: Final[tuple[frozenset[str], ...]]` in `const.py`, **rung 1** (reviewed table, operator-ratified, like `EXTERIOR_ADJACENCY_GRAPH`). Keys are resolver base stems. A camera not listed is its own group (fail-safe: sum).
- Non-transitive chains (A∩B, B∩C, A∦C) are handled by computing the group max over **connected components**. That collapses A+C conservatively, and the bias is low, which is the sound direction for a floor.
- **Dedup rule (per tick):** `S(t) = Σ_components max_{cam∈component} count_cam(t)`. This replaces "per-area max" for interior floor purposes. The existing area grouping stays for the legacy snapshot until D6.

---

## 6. `guests_present` flag and consumer migration (D5)

### 6.1 Semantics
`guests_present: bool` is owned by `PresenceCoordinator` and published on a new signal, `SIGNAL_GUESTS_PRESENT_CHANGED` (NEW; the house-state signal must not be reused, because its payload is a state). **It is independent of `HouseState`.**

**ON** when any of these holds:
- (a) estimator `guest_estimate ≥ GUESTS_PRESENT_MIN_COUNT` sustained `GUESTS_PRESENT_ON_S`;
- (b) the guest-room gate fires: the existing `_guest_room_gate_armed`, with its existing 30 min `threshold_min`, **now evaluated in all states including SLEEP**;
- (c) `revel_guest_phones ≥ 1` sustained `GUESTS_PRESENT_ON_S` **and** the floor shows at least one anonymous body in that window;
- (d) manual override.

Revel alone never arms it. Phones are a corroborator, because of the IoT false-positive history (RESEARCH §1.4).

**OFF** when, for `GUESTS_PRESENT_OFF_S`, all of these hold: the guest ceiling is 0 or (guest estimate is 0 and floor guests are 0); no guest room is unknown-occupied; and no manual override is active.
- Exit is deliberately slower than entry.
- A verified-empty reset forces OFF immediately.

**House state:** `infer()` **stops proposing `HouseState.GUEST`.**
- The enum value stays: `services.yaml:21`, restore, history rows, `routine_forecaster`, and the operator automation at `automations.yaml:8308` all reference "guest".
- A manual override to "guest" is **translated** into `guests_present=ON (manual)` plus a time-based HOME_* state. Option (B) in Q2 keeps GUEST as an override-only state instead.
- On restore, a persisted GUEST maps to the time-based HOME_* plus flag ON pending re-evaluation.
- The GUEST row stays in `VALID_TRANSITIONS` for back-compat. Inference just never targets it.
- Consequence: **SLEEP becomes reachable during a party.** Today it is not: GUEST has no SLEEP successor, `house_state.py:116-121`.

### 6.2 Every reader of GUEST: migration table (file:line, trust vs display, proposed behaviour)

| # | Reader | Kind | Today | After D5 |
|---|---|---|---|---|
| 1 | `presence.py:1301-1303` GUEST exit before sleep | trust (state machine) | exits GUEST when gate disarms | Deleted (GUEST never inferred). Override-GUEST handling moves into the flag. **Invariant I-D1 is superseded; reviewer confirms there is no residual latch.** |
| 2 | `presence.py:1305-1310` sleep branch blocks guest entry | trust | the blocker the operator called out | Unchanged for state. The flag is evaluated outside `infer()`, so the sleep branch no longer blocks guests. |
| 3 | `presence.py:1327-1334` GUEST entry | trust | `guest_gate_armed` → GUEST | Removed. |
| 4 | `presence.py:5850-5904` gate composition; Path A unconsumed | trust | `guest_armed = guest_room_gate_armed` | Replaced by the flag evaluator. Path A (`_guest_gate_armed`, side-effecting persistence) is **retired** in favour of estimator criterion (a). KEEP+DOCUMENT per the supersession rule until D6 validates. |
| 5 | `presence.py:6465-6467` confidence override on GUEST via room path | display/diagnostic | 0.9 | Moves to the flag's `confidence`/`source` attributes. |
| 6 | `presence.py:6558-6611` GUEST exit sustained gate (Pattern E, "guest_exit" veto scope `:1883`, `:2029`) | trust | debounces GUEST→HOME | Repurposed as the flag OFF debounce (`GUESTS_PRESENT_OFF_S`). The veto-scope plumbing is reused or deleted; the reviewer decides. |
| 7 | `presence.py:6829-6833` transition logging/NM | display | logs entry/exit | Logs flag edges. |
| 8 | `presence.py:1993`, `aggregation.py:4501`, `__init__.py:5806` state lists including "guest" | trust (home-like sets) | treats GUEST like HOME | No change needed (GUEST is unreachable by inference). Left for back-compat with manual GUEST if Q2(B). |
| 9 | `binary_sensor.py:2412-2445` `guest_mode` entity | display + operator automations | `house_state == GUEST` | **Re-point to `guests_present`**, keeping the entity_id. Attributes: `source` (estimate/guest_room/revel/manual), `guest_estimate`, `floor`, `ceiling`. |
| 10 | `binary_sensor.py:3250-3257` OccupancyAnomaly suppression | trust (finding suppression) | suppressed when house_state guest | Suppress when `guests_present`. |
| 11 | `__init__.py:2888-2894` Bayesian `suppress_learning` | trust (learning) | on house-state signal == guest | Subscribe to `SIGNAL_GUESTS_PRESENT_CHANGED`. Must also seed from the current flag at setup, not only on edges (restart). |
| 12 | `optimization.py:2763-2792` accuracy-drift suppression | trust | follows Bayesian suppressed flag | Unchanged (it reads the suppression flag). Verified indirect. |
| 13 | `dynamic_preset.py:860-861` zero DPM offset under guest | trust (HVAC setpoint) | `house_state == "guest"` | `guests_present` (passed via `energy.py:7371` sibling getter `_get_guests_present`). **Behaviour change:** now applies during SLEEP/HOME_NIGHT with guests. Operator question Q3. |
| 14 | `preset_overrides.py:147-148` predicate `house_state == 'guest'` | trust, **dead** (no producer; RESEARCH §4.2) | n/a | Add predicate `"guests_present"`; leave the old string for compatibility. No producer is added in this program. |
| 15 | `hvac_const.py:1238` `HOUSE_STATE_PRESET_MAP["guest"]="home"` + `hvac.py:3971` | trust | guest→home preset | Inert (no inferred GUEST). Kept for override GUEST. |
| 16 | `hvac_const.py:228-275` `ARRESTER_HOLD_PRESERVING_STATES` (`hvac_override.py:933-954,1547`) | trust (HVAC hold sunset) | entering GUEST preserves holds | Flag edges cause no state transition, so holds are untouched by guest arrival. That is the same net effect as today's preserve. **New:** HOME_*→SLEEP during a party now sunsets holds where today it could not happen. Q3. |
| 17 | `security.py:170-176` `"guest": ARMED_HOME` | trust (security arming, HIGH NM) | GUEST arms HOME | **No arming on the flag** (recommended): arming should follow house state, and guests should not arm security. Q4. |
| 18 | `const.py:2307-2308` exterior-person NM severity in guest → MEDIUM | trust (alert severity) | MEDIUM while GUEST | Severity function gains a `guests_present` input. Recommended: while guests are present, cap perimeter severity at MEDIUM in HOME_* states, but keep CRITICAL in SLEEP unless the person is *exiting the house* (an egress event in the last N s). Q5. Note the circling→HIGH carve-out (RESEARCH §4.1). |
| 19 | `routine_forecaster.py:101,105` guest passthrough / exclusion of guest rows from training | trust (learning) | excludes `prev_state=guest` rows | Must exclude rows where `guests_present` was ON. This needs the flag in the history the forecaster reads; scope it in the D5 plan review. Otherwise training quietly absorbs party days (regression risk). |
| 20 | `memory_facade.py:279` guest→home binning | display/memory | n/a | Unchanged. |
| 21 | `sensor.py:6334` enum `GUEST="guest"` | display | n/a | Unchanged. |
| 22 | `services.yaml:21` override option "guest" | operator surface | sets GUEST | Translated per §6.1 (Q2). |
| 23 | `/config/automations.yaml:8308` operator template brightness map has `'guest':80` | **operator-owned automation** | uses house_state | It will never see "guest". Tell the operator; do not edit their config. |
| 24 | `switch.py:3787` kill-switch docstring | doc | n/a | Update the text. `switch.ura_presence_guest_detection_enabled` now gates the flag. |
| 25 | `aggregation.py:6296-6375` zone guest counts; `binary_sensor.py:1919-2225` | display | house-census derived | Read `guest_estimate` after D6. |

**Orchestrator must re-run before D5 ship:** `git grep -nE "GUEST\b|'guest'|\"guest\"|guest_mode"` over the component plus `/config/automations.yaml`, `scripts.yaml` and dashboards. This table is a hypothesis.

---

## 7. Algorithm specification (D3)

**Scope decision:** the estimator counts **people on the premises inside the egress boundary**, meaning interior plus anything reached without passing an egress camera.
- Backyard and patio doors are **not** egress-monitored (`egress_cameras` = madrone_g6_entry, doorbell_lite, front_door_aerial, garage_a_2, garage_b_2).
- A guest stepping out to the patio has not "exited". Counting them out would be wrong, and counting them would need perimeter cameras.
- Interior-vs-yard split stays a floor-level attribute only.

### 7.1 Inputs per tick (the existing census tick; no new timer)
- `R_home`: set of residents the person tracker shows home. Uses the existing BLE fleet-liveness gate.
- `R_cam(t)`: residents BLE-placed in a camera-covered room. This is the existing `_ble_home_by_area`.
- `count_cam(t)`: Frigate `person_count` per interior physical camera, watchdog-discounted (existing stuck-camera discount; it must run upstream).
- `S(t)`: overlap-deduped interior bodies (§5.3).
- `U_gr(t)`: number of designated guest rooms currently occupied with **no** known person (existing `_is_known_person_in_room`). Each counts as ≥1.
- `W(t)`: Revel guest phones connected-now (D4).
- `G_id(t)`: fresh egress-face guest ids (existing). Optional; nothing depends on faces.
- Door events (after R3 dedup): `(t_e, direction, physical_cam, person_id|None, group_lo, group_hi)`.
  - `group_hi` = max of the Frigate `person_count` on that physical door camera over `[t_e − 2 s, t_e + DOOR_GROUP_WINDOW_S]`, floored at 1 and capped at `DOOR_GROUP_MAX`.
  - `group_lo` = 1.
  - `group_med` = `group_hi` if every sample in the window agrees, else `round((1 + group_hi)/2)`.
  - Resident attribution: a crossing whose `person_id` resolves to a resident, **or** that falls within `RESIDENT_CROSSING_MATCH_S` of a resident's tracker home↔not_home edge (existing BLE-provenance pattern; see card `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`), consumes one unit of group size as resident. The remainder is anonymous.

### 7.2 FLOOR (sound lower bound on people present now)
- Anonymous instantaneous: `A(t) = max( max(0, S(t) − |R_cam(t)|) + U_gr(t),  W(t),  |G_id(t)| )`.
  - Camera areas and guest rooms are spatially disjoint at an instant (§4.5), so summing them is sound.
  - Phones and faces overlap bodies, so they enter by `max`, never by sum.
- Aged anonymous floor: `F_anon(t) = max_{τ ∈ [t − FLOOR_WINDOW_S, t]} [ A(τ) − X_hi(τ, t) ]⁺`, where `X_hi(τ,t)` = Σ `group_hi` of anonymous **exits** after τ.
  - Exits are counted *generously*, so the floor drops at least as fast as people leave. That keeps it sound.
- `FLOOR(t) = |R_home(t)| + F_anon(t)`.

**Why a window max minus exits, and not hold/decay:** a person seen 12 min ago who walked into the kitchen (no camera) is still inside unless a door saw them leave. Peak-hold cannot express "unless they left". Aging out at `FLOOR_WINDOW_S` bounds the cost of a missed exit (an unmonitored gate) to that window.

### 7.3 CEILING (upper bound that is plausible but decaying)
- Anonymous stock `C_anon`:
  - on an anonymous **entry**: `C_anon += group_hi`
  - on an anonymous **exit**: `C_anon −= group_lo` (that is, 1)
  - The bias is deliberately upward.
- **Clamp up:** `C_anon = max(C_anon, F_anon)`. If evidence exceeds the ceiling, an entry was missed. Raise it and count `ceiling_raised_by_floor` as a diagnostic (a missed-door trip-wire).
- **Reconfirmation:** the ceiling is *reconfirmed* whenever `F_anon(t) ≥ C_anon − CEILING_RECONFIRM_MARGIN`, or on any anonymous entry. Set `t_reconf = t`.
- **Decay:** if `t − t_reconf > CEILING_RECONFIRM_WINDOW_S`, decay `C_anon` linearly toward `F_anon` over `CEILING_DECAY_S`. People nobody has re-evidenced for hours and who were never seen leaving are most likely gone via an unmonitored path, or were double-counted.
- **Reset to 0 (verified empty):** all of the following must hold for `EMPTY_RESET_DWELL_S`:
  - `R_home = ∅`;
  - `F_anon = 0`;
  - no interior zone or room occupied (the existing `any_zone_occupied` substrate);
  - no guest room unknown-occupied;
  - `W = 0`.

  Record the pre-reset `C_anon` and `N_anon` (below) as the **drift residual** of that episode. That is PreCount-style training data (L2) and a trip-wire.
- `CEILING(t) = |R_home(t)| + C_anon(t)`.

### 7.4 ESTIMATE
- Unbiased integrator `N_anon`: `+group_med` per anonymous entry, `−group_med` per anonymous exit.
- Anti-windup: `N_anon = clamp(N_anon, F_anon, C_anon)` every tick. The integrator is re-anchored to the bound it hits, so a past error cannot keep pushing.
- `guest_estimate = N_anon`. `ESTIMATE(t) = |R_home(t)| + N_anon`.
- Published band: `band = CEILING − FLOOR`. That is the honesty metric. Consumers that need safety use FLOOR (anyone here?). Comfort and guest consumers use ESTIMATE.

### 7.5 Restart / boot (Bug Class: restore poisoning, F5)
- Persist `C_anon`, `N_anon`, `t_reconf` and `last_reset_ts` through RestoreEntity extra data on the ceiling and estimate sensors. Use the existing RestoreEntity pattern; the plan reviewer verifies the pattern.
- On restore:
  - apply decay for the elapsed downtime;
  - **never** treat the boot-time floor (0 until cameras and BLE settle) as reconfirmation, and never let it lower anything;
  - suppress the verified-empty reset for `BOOT_SETTLE_S` after start. This is the F5 fence.
- Door events during downtime are lost. That is accepted; the clamp-up and decay re-converge.

### 7.6 Stress case: 40 people circulating for 6 h
| Error source | Effect | Bound |
|---|---|---|
| Camera coverage φ (7 areas; kitchen, living-adjacent, dining and media uncovered) | FLOOR ≈ the peak number simultaneously visible over 20 min: perhaps 15–25 of 40 | FLOOR stays sound (≤ truth) but loose. |
| Door group undercount (occlusion, L14) | `group_hi` < true group on dense arrivals | CEILING could fall below truth. Mitigation: clamp-up by FLOOR, plus D7 vision count if D0 shows it binding. |
| Door double-fire (R3 residual) | +1 phantom per leaked crossing on entries | ~2× today. **R3 must get below 5% duplicates or the ceiling is meaningless.** |
| Circulating to the patio/yard | no door events | Correct by scope (still on premises). |
| Leaving via an unmonitored gate | the stock never decrements | Bounded by `CEILING_RECONFIRM_WINDOW_S` + `CEILING_DECAY_S`. The floor also ages out. |
| 40 arrivals × ~1 round trip each to the car | ~80–120 crossings. At 2% per-crossing bias (L5 arithmetic) that is a ±2–3 drift on `N_anon` | Held inside `[F, C]` by anti-windup. |

**Expected behaviour:** the band is wide (perhaps 20–45) during the party. ESTIMATE tracks the flow net (the audit showed raw net +9 vs truth +8, before dedup), and `guests_present` is unambiguously ON from criterion (a) within minutes of the first groups.
- Accuracy target for the stress case is **within ±15%** of truth while the flow is healthy. It is **not** within ±1. The data cannot support that, and saying otherwise would be fabrication.
- The decisions that matter (guests present, house not empty) are robust to a ±6 error at 40.

### 7.7 Knob ladder (every number: name, rung, default, why)

| Knob | Rung | Default | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `FLOOR_WINDOW_S` → Number entity **"Count memory"** | 3 | 1200 s (20 min; operator range 15–30) | The operator tunes it by observing parties vs quiet days. | 0 = instantaneous floor (no memory). |
| `CEILING_RECONFIRM_WINDOW_S` → Number **"Guest count hold"** | 3 | 5 h (range 4–6 h) | Operator policy. | 0 = ceiling decays immediately to floor (flow ignored). |
| `CEILING_DECAY_S` | 1 | 1800 s | Shape parameter; changes need review. | n/a |
| `CEILING_RECONFIRM_MARGIN` | 1 | 1 person | Internal. | n/a |
| `EMPTY_RESET_DWELL_S` | 1 | 900 s | Safety-adjacent: a premature reset loses a stock. | n/a |
| `BOOT_SETTLE_S` | 1 | 600 s | Restart fence. | n/a |
| `DOOR_GROUP_WINDOW_S` | 1 | 8 s (D0 P2 fits it) | Fitted to measured crossing duration. | 0 = group size 1 always. |
| `DOOR_GROUP_MAX` | 1 | 6 | Sanity cap against a stuck count. | n/a |
| `RESIDENT_CROSSING_MATCH_S` | 1 | 120 s (D0 fits it) | Fitted. | n/a |
| Door dedup window (R3; replaces inline `5.0` at `transit_validator.py:1736`) | 1 | from D0 P1 (expect 10–30 s) | Protocol window. | n/a |
| `GUESTS_PRESENT_MIN_COUNT` | 2 (options flow) | 1 | Set once per household. | n/a |
| `GUESTS_PRESENT_ON_S` / `GUESTS_PRESENT_OFF_S` → **"Guest flag on/off delay"** as named buckets (quick / normal / cautious) | 2 | normal = 600 s / 1800 s | Set once; named buckets per the configurability-clarity rule. | n/a |
| `WIFI_GUEST_RECENCY_HOURS` | **retired** (KEEP+DOCUMENT) | n/a | D4 replaces the semantic. | n/a |
| Estimator master switch `switch.ura_census_estimator_enabled` | 3 | ON in shadow (no consumers) | Byte-identical fallback for D6. | OFF = legacy snapshot total, legacy GUEST gate. |

Label check: entity names are ≤3 words with no jargon ("Count memory", "Guest count hold", "Guest flag delay").

### 7.8 Falsifiable invariants
- **INV-FLOOR-SOUND:** for any tick, `FLOOR(t) ≤ true_people(t)` unless an exit is *under*-counted. Falsifier: a replay bin where the floor exceeds operator truth with no door-exit miss. D0 measures the violation rate.
- **INV-ORDER:** `FLOOR ≤ ESTIMATE ≤ CEILING` on every tick, every path (boot, restore, reset, decay, clamp). Falsifier: any published triple violating the order. Reachable candidates to test at the extremes: `FLOOR_WINDOW_S=0` with `CEILING_RECONFIRM_WINDOW_S=0`; restore after a 7 h downtime; a reset racing an entry in the same tick.
- **INV-NO-NAME:** setting all face inputs to empty and the kill switch `switch.ura_name_people_at_doors` OFF changes no FLOOR/CEILING/ESTIMATE value, except the `G_id` term, which only ever enters via `max`. Falsifier: any count delta under face-off on the D0 replay.
- **INV-GUEST-ORTHOGONAL (D5):** for any reachable state including SLEEP, `guests_present` can be ON, and `infer()` never returns `HouseState.GUEST`. Falsifier: a SLEEP tick with guest-room unknown occupancy ≥ 30 min and the flag OFF.
- **INV-AWAY-SAFE (D6):** the house never enters AWAY while `FLOOR > 0`. Falsifier: the F5 replay (15:57 AWAY with 11 present).
- **INV-SHADOW-BYTE-IDENTICAL (D3):** with the estimator ON in shadow, `interior_count` and every existing payload key are identical to pre-cycle. Falsifier: golden-master diff on recorded ticks.

---

## 8. D0: replay of 2026-10-03 (go/no-go gate). Spec

**Nature:** a one-shot read-only script, run over `ssh ha` against the recorder (`/config/home-assistant_v2.db`, immutable) and the URA DB (`person_entry_exit_events`, `census_snapshots`). Report: `docs/planning/AUDIT_census_estimator_replay_2026_10_03.md`. Script: `scripts/probes/census_estimator_replay.py`. No runtime instrumentation. It **must be run before any build dispatch.** I could not execute it in this session (no shell), so §8.4 contains no fabricated numbers.

### 8.1 Truth timeline (from the audit §0/§1.2; arrival times inferred, operator must confirm, Q1)
| Window (CDT) | Residents home | Guests | Truth |
|---|---|---|---|
| 00:00–08:17 | Ezinne, Oji, Jaya (3) | long-stay 1 | 4 |
| 08:17–09:20 | Jaya (1) | 1 | 2 |
| 09:20–12:19 | 3 | 1 | 4 |
| 12:19–12:57 | Oji, Jaya (2) | 1 → arrivals begin ~12:00–13:30 | 3 → ~11 |
| 13:30–14:03 | 3 | 9 (8 stayers + 1 transient, departure time unknown) | ~12 |
| 14:03–15:42 | Ezinne (1) | 9 (or 8 if the transient left) | 9–10 |
| 15:42–23:28 | Ezinne, Oji (2; Oji short gaps after 21:39) | 9 | ~11 |
| 23:28–24:00 | 3 | 9 | ~12 |

### 8.2 Sub-probes
- **P1 Door dedup collapse.** Collapse `person_entry_exit_events` by resolver base stem and direction at windows {5, 10, 20, 30, 60} s. Report logical events, the inter-leg gap histogram, and residual same-stem pairs. **Gate:** a window that leaves <5% residual duplicates without merging true distinct crossings (spot-check 10 events against recorder states of the door person_count sensors).
- **P2 Group size.** For each deduped door event, compute `group_hi` from the door camera `person_count` history over the candidate windows {4, 8, 12} s. Report the distribution in the 12:00–13:30 burst. Truth is about 8 people arriving, likely in 2–4 groups.
- **P3 Resident attribution.** Match crossings to resident tracker edges at {60, 120, 300} s. Report resident vs anonymous split. Truth: anonymous entries ≈ 9, anonymous exits ≈ 1.
- **P4 Floor series.** Compute `S(t)` from interior `person_count` histories with candidate overlap groups (§5.2, with and without), `R_cam`, `U_gr` from Guest Bedroom 1/2 occupancy history, and `W(t)` (P5). Compute `F_anon` at `FLOOR_WINDOW_S` ∈ {900, 1200, 1800}.
- **P5 Revel connected-now.** Count `device_tracker.*` with `state==home`, `source_type==router`, `essid==Revel`, after the existing hostname, infra and family filters, minute by minute over 10-03 **and over a guest-free baseline day** (operator to name one, Q1). The baseline count is the IoT noise floor. **Gate for including W in the floor:** baseline ≤ 0.5 mean and 0 at p90. Also explain why 10-03 `wifi_guest_floor` fell 5→0 at 15:00. That is ~2 h after arrival, not the 4 h recency, so the recency filter alone may not be the cause. Candidates: hostname/MAC randomization or a tracker `detection_time` effect.
- **P6 Ceiling/estimate series.** Integrate per §7.3–7.4 with P1–P3 outputs. Report `CEILING`, `ESTIMATE`, `FLOOR` per 15-min bin against truth.
- **P7 Multi-day drift (all retained days).** For each verified-empty anchor (per §7.3 reset predicate), report the pre-reset `C_anon` and `N_anon` residuals. This answers audit R2's open question: drift per day.
- **P8 F5 replay.** Run the estimator through the 15:53 stop and the 16:01/17:02 starts with §7.5 restore. Show that FLOOR > 0 at 15:57 under the boot fence.

### 8.3 Go/no-go criteria (all must hold to build D3)
1. **Ordering:** `FLOOR ≤ ESTIMATE ≤ CEILING` in 100% of bins (construction check).
2. **Floor soundness:** `FLOOR ≤ truth` in ≥ 95% of 15-min bins.
3. **Ceiling coverage:** `CEILING ≥ truth` in ≥ 90% of bins from 13:30–24:00.
4. **Estimate accuracy:** |ESTIMATE − truth| ≤ 2 in ≥ 80% of bins from 13:30–24:00, **and** ≤ 1 in ≥ 80% of bins from 00:00–12:00 (the morning long-stay guest must appear: FLOOR's guest-room term or Revel).
5. **Discrimination (the acceptance criteria must discriminate):** on the guest-free baseline day, `guest_estimate` = 0 in ≥ 95% of bins and `guests_present` never ON. Under the legacy snapshot both days look alike; under the estimator they must not.
6. **Drift:** median |pre-reset residual| ≤ 2 across P7 anchors. If there are **no verified-empty anchors** in retention, that is itself a finding: the ceiling relies on decay alone, and the operator decides (Q7).

**NO-GO outcomes and what they mean:**
- (2) fails → the overlap groups or the BLE-cancel are wrong; fix D2 first.
- (3) fails → group undercount; D7 moves up.
- (4) fails with (2) and (3) passing → integrator bias; tune or adopt the PreCount correction.
- (5) fails → Revel or the guest rooms false-fire; drop W from the floor.

### 8.4 What is already known (from the audit, not computed here)
- Raw ledger net is entries − exits = +9 rows against ≈ +8 truth (audit §1.3). Logical events after stem collapse are ~86 at 5 s and ~73 at 60 s. **Net after collapse was not reported.** P1 must report it.
- The snapshot census reads 2–3 against truth 10–12 (§1.1). That is the baseline the estimator must beat.

---

## 9. Deliverables and acceptance criteria

### D0 — Replay probe (read-only; gate)
As specified in §8.
- **Verify:** the report exists with P1–P8 tables and an explicit GO/NO-GO line per criterion.
- **Live:** n/a (offline).

### D1 — Prerequisites (separate Tier-1/2 cards; not built here)
- **R1** face map fix (`camera_census.py:3216`) plus replacing the fake-API monkeypatch tests (`test_census_accuracy_d1_d2.py:347`, `test_egress_camera_dead_config.py:59`).
- **R3** door dedup across legs, keyed on the resolver physical camera, with the window from D0 P1 and the inline `5.0` at `transit_validator.py:1736` replaced by a named knob.
- **R5** F5 AWAY fence. Can be folded into D6.
- **Verify (R3):** a replay of 10-03 with production dedup gives <5% same-stem duplicate rows. The `persons_entered_today` display drops by roughly 2× on a re-run day.
- **Live (R3):** the next day's `person_entry_exit_events` shows no `garage_a` pairs <30 s apart with the same direction.

### D2 — Interior overlap probe + `INTERIOR_CAMERA_OVERLAP_GROUPS` (rung 1, operator-ratified)
- **Verify:** the probe report lists every interior pair with J, lag, count-agreement and the single-resident oracle. The operator ratification section is filled in.
- **Test:** `test_overlap_groups_components_max`: a non-transitive chain collapses by component, and an unlisted camera sums.
- **Live:** with a single resident walking the foyer→stairs, `S(t)` never exceeds 1 (attribute `floor_components`).

### D3 — Estimator in SHADOW (Tier 2-DB)
A new module, `census_estimator.py` (pure, HA-free core plus a thin adapter on `PersonCensus`), fed by the existing census tick and the TransitValidator event (the existing `ura_person_egress_event` bus event). It publishes `occupancy_floor`, `occupancy_ceiling`, `occupancy_estimate` (or attributes, Q6) and new additive payload keys `estimate_floor`, `estimate_ceiling`, `estimate`, `guest_estimate` on `SIGNAL_CENSUS_UPDATED`. **No consumer reads them in this phase.**
- **Verify:** INV-ORDER and INV-NO-NAME property tests (hypothesis-style, including knob extremes 0 and max and the restore-after-7h case).
- **Verify:** INV-SHADOW-BYTE-IDENTICAL: golden-master over recorded ticks, `interior_count` unchanged.
- **Test:** `test_estimator_replay_2026_10_03` drives the **production** estimator over a fixture extracted from D0. The fixture is generated from DB rows; the expected values are hand-authored from the truth table (independent oracle, not produced by the code under test).
- **Test:** per-site mutation anchors:
  - neuter the floor exit subtraction → `test_floor_drops_on_exit` fails;
  - neuter the clamp-up → `test_ceiling_raised_by_floor` fails;
  - neuter the anti-windup → `test_estimate_clamped` fails;
  - neuter the boot fence → `test_no_reset_during_boot_settle` fails;
  - neuter the decay → `test_ceiling_decays_without_reconfirm` fails.
- **Sensor:** `sensor.universal_room_automation_occupancy_estimate` attributes: `floor`, `ceiling`, `band`, `guest_estimate`, `drift_residual_last_reset`, `ceiling_raised_by_floor_count`, `floor_components`.
- **Live:** at the next gathering (or a two-person drill: one guest phone on Revel plus one person in Guest Bedroom 1 for 30 min), `guest_estimate ≥ 1` and the ESTIMATE band contains the truth. On a guest-free evening `guest_estimate = 0`. Validate with a one-shot query, not a soak.

### D4 — Revel connected-now (Tier 1, ships inside D3)
Replace the `last_changed` recency (`camera_census.py:5520-5536`) with `state == home` (UniFi already applies `last_seen` within `detection_time`, L18), keeping the hostname, infra, tablet and family/MAC filters. Fix the stale docstring (`:5404`).
- **Verify:** `test_wifi_guest_long_connected_still_counted`: a tracker with `last_changed` 6 h old and state home counts. `test_wifi_guest_not_home_excluded`.
- **Live:** with a guest phone connected > 4 h, the `wifi_guest_floor` attribute stays ≥ 1.

### D5 — `guests_present` flag + GUEST consumer migration (Tier 3)
Per §6. Requires two plan reviews before build.
- **Verify:** INV-GUEST-ORTHOGONAL: SLEEP + guest-room unknown-occupied 30 min → flag ON, state stays SLEEP.
- **Verify:** override "guest" → flag ON (manual) plus time-based HOME_*.
- **Test:** one behavioural test per row of §6.2 that changes behaviour (rows 9–13, 16–19, 22), each with a source-mutation anchor.
- **Sensor:** `binary_sensor.ura_presence_coordinator_guest_mode` follows the flag, with attribute `source`.
- **Live:** on the next gathering, the flag turns ON before sleep hours, stays ON through SLEEP, house state reaches SLEEP, Bayesian learning is suppressed (`bayesian_predictor` suppressed attribute), and the flag goes OFF within `GUESTS_PRESENT_OFF_S` after the last guest leaves.

### D6 — Promote estimate to `total_persons` + AWAY binding (Tier 3)
`_apply_enhanced_house_census` (`camera_census.py:5740-5754`) publishes `total = ESTIMATE` when the estimator switch is ON. `infer()` AWAY requires `FLOOR == 0`. R5 boot fence included.
- **Verify:** INV-AWAY-SAFE on the F5 replay.
- **Test:** existing AWAY-veto tests pass unchanged with the switch OFF (byte-identical). With it ON, the new AWAY-safe tests pass.
- **Live:** `sensor.universal_room_automation_persons_in_house` during a gathering reads within the D0-accepted error. No AWAY transition occurs while the floor is >0 across a restart.

### D7 — AI-vision door group count (PARKED)
Audit §4.1 option B. **Revival trigger:** D0 criterion 3 fails because of group undercount, or the live D3 `ceiling_raised_by_floor_count` exceeds 2 per gathering. It stays advisory only (manual §5.5), and only the ceiling `group_hi` consumes it.

### Non-goals
- No Re-ID.
- No Kalman or particle filter in v1. Revisit if the D3 live band width is >50% of the estimate on ordinary days.
- No guest HVAC setpoint producer (still dead per RESEARCH §4.2).
- No change to exterior/property census.
- No new interior hardware.

---

## 10. Plan completion tracking (what this plan deliberately does NOT do)
- **AI vision:** parked as D7 with a trigger.
- **Kalman/particle filters:** recorded with a trigger in Non-goals.
- **Frigate interior zones:** an operator config option. No code depends on it.
- **R6 `ojini` slug hygiene:** separate Tier-1 card, unrelated to counting.
- **D0 execution:** **not run in this session (no shell).** It is the first action.

## 11. Manual corrections this plan implies (apply when D3/D5 ship, same commit)
- **Manual §4.2:** the census "holds+decays after peaks". After D3, add the floor/ceiling/estimate layer, and the rule that counting must not need names.
- **Manual §4.3:** the "5s window" stem dedup leaks across legs (audit F4). Correct it when R3 ships.
- Add §4.7 "Occupancy estimator": scope = inside egress boundary, and the bound semantics.

---

## 12. Operator questions
- **Q1 Truth and baseline.** Confirm the 10-03 arrival window (~12:00–13:30?) and when the 9th guest left. Name one recent guest-free day (with only the long-stay guest) for the D0 discrimination baseline.
- **Q2 Manual "guest" override.** (A) translate it into the flag (recommended), or (B) keep GUEST as an override-only house state?
- **Q3 HVAC under SLEEP + guests.** Should the DPM-offset reset (`dynamic_preset.py:861`) apply during SLEEP when guests are present? Should HOME→SLEEP during a party sunset arrester holds as usual?
- **Q4 Security.** Recommendation: the flag never arms security (today GUEST → ARMED_HOME). Agree?
- **Q5 Perimeter severity with guests at night.** Cap at MEDIUM only in HOME_*, or also in SLEEP when an egress *exit* happened in the last few minutes?
- **Q6 Surfaces.** Three new sensors, or one `occupancy_estimate` sensor with floor/ceiling as attributes (the parsimonious option)?
- **Q7 Empty anchors.** Is the house ever truly empty with all phones away (vacations, school/work days)? If not, the ceiling relies on decay, and a manual "reset guest count" button may be needed.
- **Q8 Unknown counters.** Which room has the Apollo MTR-1 (`apollo_mtr_1_fa21b0`, per-zone target counts), and what is `sensor.upzone2_people_count`? Either could feed the floor for a camera-less room.
- **Q9 Scope.** Do you agree the count means "inside the egress boundary", so patio and backyard count as present and only the five egress doors count as in/out?

## Operator ruling 2026-10-04 — prior-art first
"Census must use prior tested machinery and functions, not invent new ones. New only where there are proper prior-art gaps. Does not mean using bad functions — fix them, or justify why they should be discarded."
Binding for the next revision (after §8a D0): a REUSE / FIX / DISCARD (with written justification) / NEW (named gap) table covering every census-related function and data path (camera_census.py census/hold/enhanced/property/face/wifi, transit_validator.py direction/dedup/egress identity, person_entry_exit_events, presence.py guest gates and house-state infer, egress/perimeter identity, EGRESS-INTERIOR-COUNT-REINFORCE-1, CENSUS-GUEST-FLOOR-1), each with file:line. Default verdict for a broken-but-right-place function is FIX. NEW pieces (e.g. a persisted entries-minus-exits ledger) must extend existing structures (person_entry_exit_events, existing count sensors/group-size legs) rather than add parallel trackers. Plan reviewers re-grep the table.

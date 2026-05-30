# INVESTIGATION — Camera signal context-sensitivity + UniFi Protect vs Frigate durability

**Date opened:** 2026-05-30
**Status:** Investigation (not yet a planning doc — gathers evidence + frames cycle proposal)
**Catalyst:** v4.7.14 empty-house-oscillation diagnostic exposed that URA's interior camera-person signals can drive ghost-occupancy; user clarified principle going forward
**Author:** captured from working session

---

## 1. User-stated principle

Captured verbatim 2026-05-30:

> "Cam person is good. Cam motion needs to be context-sensitive to configure for a room. We might also examine durability between Protect and Frigate for those kinds of sensor."

The principle splits cleanly:

- **Camera PERSON-classified signals** (binary_sensor.*_person_detected, binary_sensor.*_person_occupancy) — generally trustworthy, OK as a Tier 2 input
- **Camera MOTION signals** (binary_sensor.*_motion, *_motion_2, *_motion_3) — too noisy in most contexts; only acceptable when context (room type, time of day, who's home) makes it useful

This investigation scopes a v4.7.x cycle to enforce that principle in URA.

---

## 2. What URA reads today (verified from source)

### 2.1 The camera signals URA's presence coordinator consumes

`presence.py:1367` enumerates the suffix list URA's discovery uses:

```python
for suffix in ("_person_occupancy", "_person_detected", "_occupancy"):
    ...
```

`camera_census.py:451` confirms the same suffix list for `person_binary_sensor` discovery:

```python
for suffix in ("_person_occupancy", "_person_detected", "_person_count", "_person"):
```

**URA's presence Tier 2 reads PERSON-classified entities only.** It does NOT consume `binary_sensor.*_motion` for presence. So the user's principle is partially honored already: motion is not a Tier-2 presence input today.

### 2.2 Where motion IS consumed (separate from presence)

Greppable surface that touches `*_motion`:
- `domain_coordinators/safety.py` — likely motion-as-signal for safety/security context (verify in cycle)
- `domain_coordinators/security.py` — likely for after-hours / intrusion detection
- `binary_sensor.py:769` — `camera_person_detected` aggregator (separate from motion)

**Action item for the cycle:** enumerate every motion-consuming code path and classify: is it presence-like (bad), or hazard/security-like (OK, context-appropriate)?

### 2.3 Where the conflation can leak in

Per the user's clarification, the v4.7.14 trigger incident framing was imprecise — I said "Frigate motion firing every 60-90 s drives the ghost-flips." The ACTUAL trigger was Frigate **person-classified** detections (`*_person_detected` going on/off as the model classifies shapes outside windows / sun shadows / etc. as person). That's a model imperfection in the person classifier, not raw motion bleeding through.

This makes the cycle proposal more surgical: we need to investigate whether **Frigate's person classifier is producing more false positives than UniFi Protect's** under our current camera configuration / lighting / model versions.

---

## 3. UniFi Protect vs Frigate — known characteristics

(Marked as `[verify]` where I'm uncertain — the cycle should prove these claims with on-device evidence.)

### 3.1 UniFi Protect (`*_person_occupancy`, `*_person_detected`)

- **Person detection runs on the camera or NVR (Protect server) using UniFi's own model** [verify version]
- Threshold/sensitivity is per-camera in Protect web UI, not in HA
- "Smart Detection" events expose `_person_detected` (event boundary) and `_person_occupancy` (sustained-detection while present) [verify which suffix maps to which semantics]
- False-positive rate generally low on indoor cameras with stable lighting; higher with sun glare or moving plants outside windows [user observation needed]
- Recovery from a missed detection (person re-acquired) tends to be fast (~1-2 s) [verify]
- Pros: low CPU on HAOS (runs on camera/NVR), tightly integrated UI for tuning
- Cons: less granular event types, vendor-locked algorithm

### 3.2 Frigate (`*_person_detected` via `_person_occupancy` patterns in URA)

- **Person detection runs on HAOS via Coral / GPU / CPU** — model is configurable (default `mobiledet`, can use yolov5/yolov8) [verify what's deployed]
- Per-zone configuration in `frigate.yml`; per-zone person threshold, min/max box size, etc.
- Detected zones list (filtered by `objects.filters.person.min_score`) drives the binary_sensor state
- False-positive rate depends heavily on model + zone shapes + lighting; can fire on TVs, shadows, reflections, mannequins, posters
- Recovery from missed detection slower than Protect because it depends on inference cadence (default 5 fps but tunable)
- Pros: highly tunable, per-zone configuration, runs locally with no vendor dependency, exposes events to MQTT for fine-grained automation
- Cons: HAOS CPU/GPU load, more config burden, model upgrades require attention

### 3.3 Hypotheses to test in the cycle

1. **H1:** A meaningful subset of the ghost-`*_person_detected` events seen 2026-05-30 came from Frigate cameras specifically (not Protect). If true → Frigate config/model tuning is the upstream lever.
2. **H2:** UniFi Protect's `_person_occupancy` sensors are sticky (hold ON longer than Frigate's after person leaves frame), making them less prone to short flap-bursts but more prone to long false-positive holds.
3. **H3:** Camera person false-positive rate is correlated with sun angle (correlate event timestamps with sun position).
4. **H4:** A few specific cameras drive most of the noise — the 80/20 should hold here.

These are testable with a 7-day audit of `*_person_detected` event counts per camera, joined with platform metadata.

---

## 4. Proposed cycle — context-sensitive camera signal policy

### 4.1 Two-part design

**Part A — per-room camera-person opt-out (small, deterministic).** A new room config flag `CONF_DISABLE_CAMERA_PRESENCE: bool` (default False) that, when True, causes URA's discovery code at `presence.py:1118` to skip `tracker.register_camera()` for that room. Lets the user surgically turn off camera-presence for specific high-false-positive rooms (e.g., living room with TV, hallways) while keeping it for rooms where it's useful.

**Part B — durability audit + sensible defaults (data-driven).** A 7-day or 14-day audit script that captures, per camera:
- Total `_person_detected` flips
- Flips while all phones away (true-false-positives)
- Mean detection-hold duration
- Platform (Protect vs Frigate)
- Time-of-day distribution

Output: a small dashboard sensor and a recommendation report ("these 5 rooms drive 80% of ghost-detections — recommend opt-out"). Defaults for new rooms can be informed by which platform tends to fire cleaner in this house.

### 4.2 Estimated effort

- **Part A:** Tier 1, ~50-70 LoC + ~5 tests. New const + config_flow field + discovery-time check + UI strings.
- **Part B:** Tier 1, ~150-200 LoC + ~10 tests + 1 dashboard sensor. New `nm_audit`-style telemetry coordinator subset.

Versions:
- Part A as standalone could ship as v4.7.15 (small, decoupled from any other work)
- Part B as v4.7.16 once Part A enables surgical fixes the audit will recommend

### 4.3 What's NOT in this cycle

- **Not adding camera-motion as a presence input.** Motion stays out per user principle.
- **Not changing Frigate config.** That's upstream tuning, separate work.
- **Not changing UniFi Protect smart-detection config.** Same.
- **Not deprecating camera-person signals globally.** Only opt-out per-room.

---

## 5. Manual investigation parking lot (user-led)

User is doing manual audit of older rooms (garage hallway already done). Items they should look at:

- For each older room (`master_hallway`, `upstairs_hall`, `family_room`, `living_room`, `kitchen`, `playroom`, `dining_room`, `breakfast_nook`, `foyer`, `staircase`, bedrooms): what camera entities are auto-discovered today? Are they Frigate or Protect? Are the person-classifier zones tight or sloppy?
- Per-room sensor inventory: does the room have working mmWave/PIR? Camera should be redundant Tier 2, not the only Tier.
- Identify rooms where the room sensor + person tracker is sufficient and camera-person can be opted out without coverage loss.

Persist the per-room verdict in this doc (extend the table below as the audit progresses).

### Per-room camera-presence audit log

| Room | Camera entity in use | Platform (P/F) | mmWave/PIR present | Opt-out decision | Notes / date |
|---|---|---|---|---|---|
| Garage Hallway | `staircase_person_occupancy` ("Camera_Frigate_GarageHallway") and/or `camera_protect_garagehallway_person_detected` | F + P | yes (mmwave) | done (user-side, 2026-05-XX) | Done before this cycle |
| Master Hallway | `master_hallway_person_detected`, `master_hallway_person_occupancy` (+ `_2`) | ? | ? | pending | High ghost-flip suspect |
| Upstairs Hall | `upstairs_hall_person_detected`, `upstairs_hall_person_occupancy` (+ `_2`) | ? | ? | pending | High ghost-flip suspect |
| Family Room | `family_room_person_detected`, `family_room_person_occupancy` (+ `_2`) | ? | ? | pending | TV reflections expected |
| Living Room | `living_room_camera_person_detected` | ? | ? | pending | TV reflections expected |
| Kitchen | `kitchen_camera_person_detected` | ? | ? | pending | High-traffic, multiple people |
| Playroom | `playroom_person_detected`, `playroom_person_occupancy` (+ `_2`) | ? | ? | pending | Kids motion expected |
| Dining Room | `dining_room_camera_person_detected` | ? | ? | pending | — |
| Breakfast Nook | `breakfast_nook_camera_person_detected` | ? | ? | pending | — |
| Foyer | `foyer_fisheye_person_detected`, `foyer_fisheye_person_occupancy` (+ `_2`) | ? | ? | pending | Sun + door traffic |
| Staircase / Stairs Top | `stairs_top_person_detected`, `stairs_top_person_occupancy` (+ `_2`) | ? | ? | pending | — |
| Master Bedroom | `master_bedroom_camera_person_detected` | ? | ? | pending | Privacy + presence |
| Master Bathroom | `master_bathroom_camera_person_detected` | ? | ? | pending | Privacy |
| Oji Vanity | `oji_vanity_camera_person_detected` | ? | ? | pending | Privacy |
| Jaya Bedroom | `jaya_bedroom_bedroom_4_camera_person_detected` | ? | ? | pending | Privacy |
| Jaya Bathroom | `jaya_bathroom_camera_person_detected` | ? | ? | pending | Privacy |
| Ziri Bedroom | `ziri_bedroom_bedroom_5_camera_person_detected` | ? | ? | pending | Privacy |
| Ziri Bathroom | `ziri_bathroom_camera_person_detected` | ? | ? | pending | Privacy |
| Guest Bedroom 1 | `guest_bedroom_1_camera_person_detected` | ? | ? | pending | Privacy |
| Guest Bedroom 2 | `guest_bedroom_2_camera_person_detected` | ? | ? | pending | Privacy |
| Down Guest Bathroom | `down_guest_bathroom_camera_person_detected` | ? | ? | pending | Privacy |
| Study A | `studya_room_device_camera_person_detected` | ? | ? | pending | Office |
| Study B | `study_b_camera_person_detected` | ? | ? | pending | Office |
| Game Room | `game_room_camera_person_detected` | ? | ? | pending | — |
| Media Room | `media_room_camera_person_detected` | ? | ? | pending | TV reflections expected |
| Exercise Room | `exercise_room_camera_person_detected` | ? | ? | pending | — |
| Laundry | `laundry_camera_person_detected` | ? | ? | pending | — |
| Receiving Room | `receiving_room_camera_person_detected` | ? | ? | pending | — |
| Butler Pantry | `butler_pantry_camera_person_detected` | ? | ? | pending | — |

(Closets generally should opt out — not load-bearing for occupancy decisions.)

### Perimeter cameras — keep as security, NOT presence

- `back_yard_*`, `patio_*`, `pool_equipment_*`, `hot_tub_*`, `front_door_aerial_*`, `front_side_ptz_*`, `rear_ptz_*`, `utilities_ptz_*`, `g5_bullet_*`, `madrone_g6_entry_*`, `doorbell_lite_*`, `garage_a_*` (exterior), `garage_b_*` (exterior), `armcrest_*`, `armcrestash41b_*`, `reolinkstudybporchptz_*`

These are tracked by `CONF_PERIMETER_CAMERAS` / `CONF_EGRESS_CAMERAS` at `const.py:783-784` and should remain in the security path, not presence.

---

## 6. Bug class candidates this investigation surfaces

- **"Camera person classifier as oracle"** — treating ML-classified `*_person_detected` events as ground truth without considering false-positive distribution per camera/lighting. Not yet a QUALITY_CONTEXT class; v4.7.15 could be its first exemplar.
- **"Platform-conflated camera signal trust"** — URA treats Frigate and Protect signals identically in Tier 2 even though their false-positive characteristics differ. Worth promoting if Part B's audit shows the difference is meaningful.

---

## 7. Acceptance criteria for the eventual cycle (v4.7.15)

When Part A ships, expect:
- New room config field `CONF_DISABLE_CAMERA_PRESENCE` in config_flow
- Verifier: room with `disable_camera_presence=True` results in `tracker.register_camera()` being skipped at `presence.py:~1118`
- Verifier: opted-out room's `_camera_entity_ids` set stays empty across reload
- Verifier: opt-out is idempotent (toggle on/off mid-flight doesn't corrupt state)
- Live: at least 3 high-suspect rooms (master_hallway + upstairs_hall + one TV-room) opted out and verified zero ghost-flips overnight while all phones away
- Test: `test_disable_camera_presence_skips_register_camera`
- Test: `test_disable_camera_presence_default_false_preserves_behavior`
- Test: `test_disable_camera_presence_toggle_at_reload`

When Part B ships:
- New sensor `sensor.ura_camera_presence_audit` exposing per-camera flip counts + false-positive ratios over last 7 days
- Verifier: audit excludes camera events while at least one person home (only counts true-false-positives)
- Verifier: distinguishes Protect vs Frigate in attribute breakdown
- Test: `test_audit_counts_only_while_all_away`
- Test: `test_audit_separates_platform`

---

## 8. References

- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` — the inference-engine veto fix (in flight at investigation open)
- `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md` — the sleep-state sibling (live)
- `custom_components/universal_room_automation/domain_coordinators/presence.py:1100-1138` — camera discovery + registration
- `custom_components/universal_room_automation/domain_coordinators/presence.py:1367` — person sensor suffix list
- `custom_components/universal_room_automation/camera_census.py:127-451` — CameraIntegrationManager + suffix discovery
- `custom_components/universal_room_automation/const.py:782-908` — camera-related config constants (`CONF_CAMERA_PERSON_ENTITIES`, `CONF_PERIMETER_CAMERAS`, `CONF_EGRESS_CAMERAS`, `CONF_SECURITY_CAMERA_*`)

## 9. Open questions for the cycle

1. Should `CONF_DISABLE_CAMERA_PRESENCE` be per-camera (more granular) or per-room (simpler)? Per-room recommended; per-camera defers to URA's discovery and is what most operators would want.
2. Does URA already have a discovery-time hook where this flag would naturally fit, or does the check go inline at `register_camera` call site?
3. Should the audit (Part B) write to its own DAO table or piggyback on `anomaly_log`?
4. Should there be a "camera-presence shadow mode" — register them but log-only — so the audit baseline can compare opted-in vs opted-out without losing safety net?

These get resolved during the planning cycle.

## 10. Recall

- "Resume camera presence investigation"
- "Plan v4.7.15 per-room camera opt-out"
- "Audit Protect vs Frigate durability"

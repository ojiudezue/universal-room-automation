# AUDIT: Frigate 1 Sunset — Full Implications (read-only)

**Date:** 2026-08-06 · **Read-only** — no config changed anywhere.
**Scope:** retire Frigate 1 (192.168.13.16, Coral EdgeTPU / SSD-MobileNet NUC — operator wants
the hardware repurposed), consolidate on **Frigate 2** (192.168.13.18, 3× OpenVINO / yolov9t)
+ **UniFi Protect** + **native camera AI** (Reolink, Dahua/Amcrest) as the go-forward platforms.

**Sources read:** live `/config/.storage/core.config_entries` + `core.entity_registry` (ssh ha,
2026-08-06); live `/api/stats` from BOTH Frigate hosts (authenticated on-host, creds never
materialized locally); F1/F2 config backups `docs/planning/backups/f{1,2}_{raw,runtime}_config_2026-08-07.*`
(untracked, credential-bearing — NEVER commit); `AUDIT_exterior_camera_detection_settings.md`
(incl. CORRECTED architecture section); `GOLDEN_MASTER_census_cutover_diff.md`;
`camera_resolver.py`, `camera_census.py`, `perimeter_alert.py`, `const.py`;
live `automations.yaml`, `packages/zone_monitoring.yaml`, `lovelace.ura_v8`, group helpers.

**Architecture baseline (post 2026-08-01 prefix split + cycle-2 fused sourcing):** F1 (`frigate`)
and F2 (`frigate2`) are PARALLEL MQTT devices. Every Frigate camera has a base entity set
(F1, e.g. `binary_sensor.back_yard_person_occupancy`) and a `_2` set (F2,
`..._person_occupancy_2`). F1 HA config entry `01JV6G4E…`; F2 `01KM239Z…`; Protect `01K1SBX7…`.
Both hosts run identical camera fleets (23 cameras each; verified from runtime configs — zero
F1-only or F2-only cameras). The ONLY divergences: `ArmCrestASH41B` enabled F1 / disabled F2,
and back_yard + hot_tub detect at 1280×720 on F2 vs 640×360 on F1 (deliberate — headroom host).

---

## 1. Entity blast radius

### 1a. URA config-entry references (live `core.config_entries`)

Platform of every configured `camera.*` entity verified against the live entity registry.
Classes: **(a)** survives via `_2` fused sourcing · **(b)** survives via resolver ·
**(c)** BREAKS — the referenced entity is deleted when the F1 entry is removed; needs re-pointing.

**`perimeter_cameras` (integration entry, 9 rows):**

| Row | Platform (registry) | Class |
|---|---|---|
| `camera.front_side_ptz` | frigate/F1 | **(c) BREAKS** |
| `camera.armcrest` | frigate/F1 | **(c) BREAKS** |
| `camera.hot_tub` | frigate/F1 | **(c) BREAKS** |
| `camera.pool_equipment` | frigate/F1 | **(c) BREAKS** |
| `camera.g5_bullet` | frigate/F1 | **(c) BREAKS** |
| `camera.back_yard` | frigate/F1 | **(c) BREAKS** |
| `camera.reolinkstudybporchptz` | frigate/F1 | **(c) BREAKS** |
| `camera.rear_ptz_high_resolution_channel` | unifiprotect | (b) survives |
| `camera.utilities_ptz_high_resolution_channel` | unifiprotect | (b) survives |

Important nuance on the cycle-2 "F1-retirement insurance": `PerimeterAlertManager` subscribes
to base + `_2` person sensors (perimeter_alert.py `_fused_sibling`, dedup by camera key), so a
DEAD F1 *sensor* is covered — but the insurance is derived FROM
`info.person_binary_sensor`, which comes from resolving the configured `camera.*` entity
(`camera_census._get_integration_camera_list` → `resolve_configured_cameras`). If the
configured F1 **camera entity itself is deleted** (F1 entry removal), resolution of that row
yields nothing and the whole camera drops out of perimeter monitoring — the `_2` insurance
never attaches. Hence class (c), not (a): re-point BEFORE removing the F1 entry.

**`egress_cameras` (3 rows):** `camera.madrone_g6_entry`, `camera.doorbell_lite`,
`camera.front_door_aerial` — all frigate/F1 → **all 3 (c) BREAK**. (Post census-cutover fix,
the resolver reaches the Protect leg from a Frigate input via the bidirectional stem index —
but only while the Frigate input entity exists.)

**`camera_person_entities` (interior census, 9 rows):** 5 Protect rows survive
(`playroom/staircase/family_room/foyer_fisheye/master_hallway_high_resolution_channel`);
4 frigate/F1 rows (`camera.playroom`, `camera.master_hallway`, `camera.foyer_fisheye`,
`camera.family_room`) go dead — **class (b) net-survives**: each F1 row has a Protect sibling
row in the same list, and from the Protect input rung-5 reaches the F2 `_2` Frigate person
sensors (stem index normalizes `_2` per B-HIGH-2). No interior camera loses coverage; the 4
dead rows are config lint to prune.

**Room entries:** Study A `room_cameras` = `camera.armcrestash41b_2` (already F2-pointed —
**class (a)**, and only goes truly live once ASH41B is enabled on F2) +
`sensor.g3_instant_last_motion_detected_2` (Protect). Game Room `camera_person_entities` =
Protect only. CM `security_camera_entities` = empty. No other room references cameras.

**Blast-radius counts (URA config): 21 camera rows total → 10 (c) BREAK (7 perimeter + 3
egress), 4 dead-but-redundant (interior, class b), 7 survive as-is (a/b).**

### 1b. HA-side references

- **Dashboard `lovelace.ura_v8`:** exactly **1** F1 entity — `camera.armcrestash41b`
  (Study A card). Every other camera ref is a Protect `*_high_resolution_channel` /
  `*_package_camera`. → 1 re-point.
- **`automations.yaml`:** **14 base F1 person sensors** (`binary_sensor.<cam>_person_occupancy`
  for armcrest, back_yard, doorbell_lite, front_door_aerial, front_side_ptz, g5_bullet,
  garage_a, garage_b, hot_tub, madrone_g6_entry, pool_equipment, rear_ptz,
  reolinkstudybporchptz, utilities_ptz), **4 F1 camera entities** (front_side_ptz, rear_ptz,
  utilities_ptz, reolinkstudybporchptz), and **3 F1 face sensors**
  (`sensor.{front_side,rear,utilities}_ptz_last_recognized_face` — frigate platform; `_2`
  siblings exist). All BREAK. (Some automation refs are ALREADY dead pre-sunset:
  `sensor.*_last_identified_person`, `event.front_door_aerial_person` — MISSING from registry.)
- **Groups + packages:** `BinaryGroup_Camera_PersonDetected_Zone1` (+Upstairs group) and
  `packages/zone_monitoring.yaml` consume Protect `*_person_detected` sensors only → survive.
- **Scripts:** zero camera refs.

## 2. Redundancy accounting — per-camera post-F1 witness table

Today's second engine per camera is F1↔F2 cross-host corroboration
(`FRIGATE_CROSS_HOST_CORROBORATION_ENABLED=True` since 2026-08-04, camera_resolver.py:79;
consumers: census `_cross_validate_platforms` + resolver collapse-winner, D3 fused per-room
sensor, D5 fan_veto, perimeter fused sourcing). Post-F1 that rung is inert; independent
witnesses become Frigate-F2 ↔ Protect ↔ native AI.

| Camera | Engines after sunset | Witnesses | Verdict |
|---|---|---|---|
| front_side_ptz, rear_ptz, utilities_ptz, g5_bullet, back_yard, hot_tub, pool_equipment | F2 + Protect | 2 | OK — second engine fully replaced |
| front_door_aerial, doorbell_lite, madrone_g6_entry (egress) | F2 + Protect | 2 | OK |
| garage_a, garage_b, playroom, family_room, foyer_fisheye, master_hallway, upstairs_hall, stairs_top | F2 + Protect | 2 | OK |
| staircase | F2 + Protect (NVR-homed sensor excluded by F1 stem filter — correct) | 2 | OK |
| madrone_g6_entry_package | F2 only (`_package_*` excluded from person capability by design, F3 fix) | 1 | OK by design |
| `armcrest` (pool overhead) | F2 + Dahua native (`binary_sensor.armcrestpooloverhead_smart_motion_human`, enabled) | 2 | OK — native leg is the second witness |
| `reolinkstudybporchptz` | F2 + Reolink native (`binary_sensor.ptzcamreolinktmixpstudybporch_person`, enabled) | 2 | OK |
| `ArmCrestASH41B` (interior, Study A) | **F2 only** post-move (no Protect; no native AI entity in registry) | **1** | **Single-witness** — acceptable for an interior room-presence cam (room has other substrate sensors), flag for the corroboration doctrine |

Also single-witness today under F1: ASH41B (F1 only, F2 disabled). Net redundancy REGRESSION
from the sunset: none, provided the native Reolink/Dahua legs are wired where a Frigate↔Frigate
pair was previously counted. Whether the resolver actually reaches the reolink/dahua sensors
(different naming stems: `ptzcamreolinktmixpstudybporch` vs `reolinkstudybporchptz`;
`armcrestpooloverhead` vs `armcrest` — only `perimeter_alert` has the
`EXTERIOR_CAMERA_KEY_ALIASES` bridge, const.py ~1397) is a **cycle-3 resolver work item**.

## 3. F2 capacity (measured 2026-08-06, live `/api/stats`)

- **F2 detectors:** ov 12.62 ms · ov_1 12.79 ms · ov_2 12.94 ms inference. Aggregate
  theoretical ≈ 3 × (1000/12.8) ≈ **235 inferences/s**; current summed `detection_fps` ≈ **39**
  (~17% of capacity). (F1 Coral for reference: 17.74 ms.)
- **F2 cameras:** all 22 enabled cameras at `process_fps` 4.3–5.1, `skipped_fps` 0.0 —
  **including back_yard (det 4.9) and hot_tub (det 7.5) at 1280×720 detect**. Only
  ReolinkStudyBPorchPTZ shows skip 0.9, and F1 shows the same on that camera (0.6) → stream-side,
  not host load. Total process_fps 110.5.
- **What F1 carries that F2 doesn't:** exactly one thing — **ArmCrestASH41B** (enabled F1,
  disabled F2; config-diff of the two runtime configs shows no other enabled/camera delta).
  ASH41B on F1 today: proc 5.1, det 0.7.
- **Headroom estimate for absorbing ASH41B:** +1 camera decode (~5 proc fps on a 704×480
  sub-stream) + ~1 det fps against ~196 spare inferences/s and a CPU pool already decoding 23
  streams incl. two 720p detects with zero skips. **Verdict: trivially absorbable; the
  already-720p cameras stay healthy** (skip 0.0 measured with today's full fleet).

## 4. ASH41B move plan

**Config change (verified against the F2 backup):** F2 config already contains the full
`ArmCrestASH41B` block — go2rtc restream + camera block with
`enabled: false  # 2026-08-01: camera cannot serve both NVRs concurrently — OWNED BY F1 until
F1 is retired. Creds/channel here are CORRECT (admin + ASH41B pw, channel=1); just re-enable
when F1 goes away…` (f2_raw_config_2026-08-07.yaml:170-180; creds via config vars, channel=1
subtype 0/1 at 192.168.12.143 — matches F1's working block byte-for-byte on the stream URLs).
The move is: **set `enabled: false` on F1's ASH41B (or stop F1 first), THEN flip F2's to
`enabled: true`** — never both (the comment's watchdog-loop + /tmp/cache-refill outage).
Two saves via `/api/config/save?save_option=restart`.

**HA entity consequences:** F2's `camera.armcrestash41b_2` +
`binary_sensor.armcrestash41b_person_occupancy_2` ALREADY exist (registered, enabled, currently
unavailable-shaped since the F2 camera is disabled). Enabling on F2 makes them live. Study A's
config already points at the `_2` camera — zero URA config change needed for the move itself.
Deleting the F1 entry later removes `camera.armcrestash41b` + base sensor.

**The `_2` question — does HA rename survivors when the F1 entry is deleted? NO.**
Entity-registry behavior (verified semantics, not guessed mechanics): the `_2` suffix was
minted ONCE at registration time because the base entity_id was taken; the registry keys
entities by `(platform, unique_id)` and the entity_id is a stable, never-auto-recomputed
property. Removing the F1 config entry deletes F1's registry entries and **frees** the base
ids, but nothing in HA revisits existing entities' ids — **the `_2` suffix on the entire F2
entity set persists forever unless manually renamed**. Options:

- **Option A — live with `_2`:** re-point all configs/automations to `_2` ids, delete F1 entry.
  Zero rename risk; URA's suffix-stripping (`perimeter_alert._camera_key_for_sensor`, resolver
  stem normalization) already treats `_2` as first-class. Cost: permanently ugly ids, every
  future config/dashboard/automation must remember the suffix, and the D-H2 class of bugs
  (`_2` snapshot-cache key misses) stays a live hazard.
- **Option B — delete F1 entry, then bulk-rename `_2` → base (RECOMMENDED):** once the base
  ids are free, rename each `_2` entity to the base id via the entity registry (UI or
  websocket `config/entity_registry/update`). `unique_id` is untouched, so the F2 integration
  keeps driving them. Every existing base-id reference — the 14 automation sensors, 3 face
  sensors, URA camera lists, dashboards — comes back to life WITHOUT editing those consumers.
  Caveats: renames do NOT propagate anywhere automatically, so anything pointed at `_2`
  meanwhile (Study A `room_cameras`, the one dashboard card if re-pointed in step 2) must be
  flipped back to base ids in the same pass; URA builds subscriptions at setup, so reload
  URA / restart HA after the rename batch; ~90 entities × 4-ish domains to rename (scriptable).
- **Option C — hybrid:** point URA lists at Protect camera entities wherever a Protect sibling
  exists (interior already is), rename only the Frigate-only cameras (reolinkstudybporchptz,
  armcrest, ASH41B, package cam). Smallest rename batch but leaves the automation-referenced
  perimeter person sensors on `_2` or dead → still needs A- or B-style handling for those.

Recommendation: **B**. Single-user deployment, no back-compat obligation, and it converges the
namespace so cycle-3 resolver work doesn't have to carry `_2` normalization as a permanent
invariant. One open verification before relying on Frigate snapshots post-rename/removal:
`perimeter_alert` builds snapshot URLs as `/api/frigate/notifications/<event_id>/snapshot.jpg`
(un-prefixed = default frigate entry). With F1's entry deleted, confirm F2's events still
arrive on the `frigate_event` bus and whether the un-prefixed proxy URL serves F2's entry or
requires the client_id-prefixed form — test one live event before closing (honest gap: not
verifiable read-only today).

## 5. Sequenced sunset plan

Preconditions (already met): protect-legs / fused-sourcing cycle deployed; census resolver
cutover GO (`CENSUS_USE_NEW_RESOLVER=True`); cross-host gate passed.

| # | Step | Verification signal | Revert point | Operator hands? |
|---|---|---|---|---|
| 1 | **Re-point URA config lists** — perimeter 7 F1 rows + egress 3 rows → Protect camera entities where they exist (all 10 have one? egress yes; perimeter: reolinkstudybporchptz + armcrest have NO Protect entity → point at `_2` Frigate cameras) ; prune 4 dead interior rows | PerimeterAlertManager log: monitoring count unchanged (9 cameras), no "no `_2` sibling" warnings; census `active_platforms` unchanged | old lists recorded in §1a — paste back | No (options flow) |
| 2 | **Move ASH41B**: disable on F1 (save+restart), verify F1 clean, enable on F2 (save+restart) | F2 `/api/stats`: ASH41B proc ≈5, skip 0; `camera.armcrestash41b_2` live; Study A camera presence functional | re-flip the two `enabled` flags | No (API) |
| 3 | **Disable all F1 cameras** (fleet `enabled: false`, F1 service stays up) — F2-only detection era begins | perimeter alerts + interior census + D3 sensors keep firing on `_2` legs over several organic events; zone-monitoring package unaffected (Protect) | re-enable F1 cameras | No |
| 4 | **Observe** until each perimeter camera has ≥1 organic F2-sourced alert with snapshot (trip-wire: `no _2 sibling` / snapshot-miss warnings in log), incl. the §4 snapshot-URL check | log scan + NM delivery record | F1 still intact — re-enable | No |
| 5 | **Delete the Frigate 1 HA config entry** (frees base entity ids). Do NOT uninstall the frigate integration (F2 uses it) | no unavailable-entity storm; `frigate` domain shows 1 entry loaded | re-add F1 entry (URL + creds), entities re-register with base ids | No |
| 6 | **Rename `_2` → base** (Option B batch), flip Study A + any step-1 `_2` pointers back to base, reload URA / restart HA | automations referencing base sensors trigger on live events; golden-master probe re-run shows one person-BS per stem; dashboard card renders | renames are reversible individually | No (scripted) |
| 7 | **Retire the NUC**: power down 192.168.13.16, remove MQTT client `frigate-f1` creds if dedicated, clean DHCP reservation / UniFi client entry, repurpose hardware | F2 stats healthy 24h-equivalent organic traffic; zero URA camera ERROR logs | physical re-rack (last resort) | **YES — physical** |

Steps 1–6 are remote/console work; only step 7 needs hands on hardware. Ordering rationale:
re-point (1) BEFORE any F1 removal so no monitoring gap ever opens; entry deletion (5) strictly
after the F2-only observation window (3–4); renames (6) strictly after (5) frees the ids.

## 6. Cycle-3 resolver implications

- **Two-platform world** (+ native legs): the resolver's cross-host Frigate collapse
  (rung-5 F2-fix, collapse-winner `state_getter` pick, `FRIGATE_CROSS_HOST_CORROBORATION_ENABLED`)
  becomes inert — one Frigate host means nothing to collapse. Don't rip it out in the same
  cycle as the sunset (it's harmless dormant code and the fire-axe path), but cycle-3 design
  should NOT build new behavior on cross-host corroboration.
- **Corroboration doctrine:** the two independent engines per camera are Frigate-F2 ↔ Protect
  (interior + most perimeter) and Frigate-F2 ↔ native AI (reolink porch PTZ, dahua pool
  overhead). Cycle-3 legs should elevate the native-AI sensors to first-class resolver
  capabilities — today only `perimeter_alert` bridges the stem mismatch via
  `EXTERIOR_CAMERA_KEY_ALIASES`; the resolver's stem index has no
  `ptzcamreolinktmixpstudybporch→reolinkstudybporchptz` / `armcrestpooloverhead→armcrest` rung.
- **Entity landscape:** design for BOTH interim states — `_2`-suffixed survivors (between
  steps 5 and 6, or forever under Option A) and renamed base ids (after step 6). Concretely:
  keep the B-HIGH-2 bidirectional `_2` normalization until the rename batch is confirmed done,
  then it can be retired with the cross-host machinery. Registry-update listeners (B-HIGH-1
  resolver cache invalidation) make the rename batch safe for cached indices, but
  setup-time-built subscription lists (perimeter manager) need the step-6 reload.
- **ASH41B stays single-witness** — the corroboration doctrine should classify it (and any
  future Frigate-only interior cam) as single-engine rather than pretending a second leg exists.

---

## Summary

- **Blast radius:** URA config — 10 rows BREAK (7 perimeter + 3 egress, all F1 `camera.*`
  entities), 4 interior rows dead-but-redundant, 7 survive; HA — 1 dashboard entity,
  14 automation person sensors + 4 camera refs + 3 face sensors BREAK; groups/packages survive
  (Protect-sourced).
- **Witness table:** every exterior + interior camera keeps ≥2 engines post-sunset (F2+Protect,
  or F2+native for the Reolink porch PTZ and Amcrest pool overhead); sole exception ASH41B
  (F2-only, interior, acceptable).
- **F2 headroom:** measured 12.6–12.9 ms × 3 detectors, ~39 of ~235 inf/s used, all 22 cams
  5 fps / 0 skipped incl. both 720p detects — ASH41B absorption is trivial; verdict GO.
- **`_2` naming:** HA never auto-renames — `_2` persists after F1 entry deletion unless
  manually renamed. Recommended: delete F1 entry, then bulk-rename `_2`→base (Option B), which
  resurrects every existing base-id consumer without editing them.
- **Plan:** re-point → move ASH41B → disable F1 cameras → observe organically → delete F1
  entry → rename → retire NUC. Only the final physical step needs operator hands.

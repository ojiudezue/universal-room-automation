# Review A (local correctness) + G (goal fidelity): camera input stream health S2

Branch `feature/camera-input-stream-health-s2` @ 8fee2e47, base develop 3ec3f4d2 (`git merge-base develop HEAD` =
3ec3f4d2, verified). Plan `docs/planning/PLANNING_camera_input_stream_health.md` S2; card
CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1. Tier 2-DB.

Read completely first: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`,
and (because the review assesses the "HVAC needed no change" claim and finds an HVAC-consumed reader)
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No ledger claim re-asserted. Live config read from the Samba
mount `.storage/core.config_entries` (read-only).

Test note: my one targeted run (S1 + S2 test files) showed `test_camera_keyed_getter` red, but `git status` showed
`coordinator.py` and `camera_stream_health.py` modified plus `rvc_drill_s2_tool.py` / `rvc_m1.json`: reviewer C's
mutation drill was live in the shared worktree. That result is void; I ran nothing further. C owns pytest.

## Findings

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| A-M1 | MEDIUM | `domain_coordinators/presence.py:2437-2442` (`check_zone_occupancy_confidence` Source 3) | Missed zone-tier camera reader. It reads each `zone.zone_cameras` entity's raw `on`, not the getter. Consumer: HVAC D6 stale-occupancy failsafe (`hvac.py:3099`): `confirmed >= threshold` resets `continuous_occupied_since`, so a zone camera person sensor frozen `on` while its camera is `unavailable` (the exact Frigate behaviour measured in the plan: person sensor stuck `on` 14 h with the camera unavailable) keeps confirming and the 4 h failsafe never forces the zone away. Legal repro: zone `Entertainment`, `zone_cameras` includes `binary_sensor.family_room_person_occupancy` (live config); `camera.family_room` goes `unavailable`, the person sensor stays `on`; any room whose area holds that camera watches it through the camera-override extras, so `entity_stream_dead` would answer True, but Source 3 never asks. Direction: holds comfort (not AWAY). Fix is one line, the same guard as `_any_camera_occupied`: `and not _camera_entity_stream_dead(self.hass, camera_entity)`. Fix in cycle (plus one mutation-anchored test). | #53 one missed site |
| A-M2 | MEDIUM | `docs/readmes/README_camera_input_stream_health_s2_DRAFT.md` "Acceptance", plan S2 "Live" | The live census criterion cannot be observed on the measured outage. The panel inputs (`binary_sensor.{study_a,kitchen,up_hallway}_panel_person_occupancy`) are room `presence_sensors` only; the census interior list `camera_person_entities` holds 12 Frigate/Protect cameras and no panel (live config). So "`persons_in_house` stops counting that camera's frozen body" and the plan's "`aware_agreement` shows single_source" will read the same under fix and no-fix on a panel outage (non-discriminating criterion). Rewrite: panel outage → the panel room's substrate kind / zone stops following the frozen `on` (zone tracker room view, `zone_<z>_presence_status`); census → only on an outage of an interior census camera, observed as that camera absent from `area_contributions` while `camera_input_dark` is unchanged. | acceptance must discriminate |
| A-L1 | LOW | `camera_census.py:2190-2199` (cross-validation OFF branch) | The dead skip runs BEFORE `seen_device_ids.add`, while an unavailable entity is skipped AFTER it. So a second entity on the same device is counted when the first is dead-stream, but not when the first is unavailable: "missing term as if unavailable" diverges. Only reachable when the second entity's own camera is unresolved (multi-camera device) while the first resolves via the input route; cross-validation is ON live. Move the skip after the device dedup, or accept by name. | #63 concept split |
| A-L2 | LOW | `domain_coordinators/presence.py:4510-4521` (D4d `zone_hold_all_away` diagnosis labels) | Lists live `on` entities without the getter, so the page can name a dead-stream input as a holder. Display only (NM text). Optional one-line guard. | display drift |
| A-L3 | LOW | `fan_veto.py:418-447` vs the S2 legacy-leg edit `:460-463` | The S2 guard sits in the legacy `CONF_CAMERA_PERSON_ENTITIES` leg, which runs only when the fused `binary_sensor.<room>_camera_person_detected` has no state. Every room creates that entity, so in production the fused branch returns first and the S2 edit is nearly unreachable. The comfort-fan camera leg is therefore NOT stream-health aware in practice. See G-2 for the disposition. The README table row "Comfort-fan AWAY veto (motion leg + legacy camera leg)" is accurate but should say the fused leg is the live one and is uncovered. | #53 (reader covered on a dead path) |

Cleared (holds because):

- **Combining rule** `camera_stream_health._fold` (`:340-349`): returns True on the first True, else False if any False,
  else None; non-bool answers ignored. `input_stream_dead` / `camera_stream_dead` swallow per-room exceptions as no
  opinion. Truth table below.
- **No second liveness rule:** the three house functions read only `coord.camera_input_stream_dead` /
  `coord.camera_stream_dead`; `entity_stream_dead` reuses the S1 resolver `own_camera_entity_for_input` (indexed
  per-device lookup, `camera_resolver.py:818-863`) and then the camera-keyed getter. No camera state is read outside
  `CameraInputStreamHealth.evaluate`.
- **`camera_is_dead`** (`:293-302`): None when unresolved or the camera is not the own camera of any watched input
  (configured or override extra); True iff a `_dead_now` entry names it. `_dead_now` is populated only when
  `enabled` (`:244-253`), so kill switch False gives False for a watched camera and every caller tests `is True`.
- **Kill switch byte-identity:** `dead == {}` every tick, `_camera_stream_prev_dead` stays empty, so
  `_notify_substrate_stream_flips` is never called (`coordinator.py:2629-2636`); every reader guard is `is True`.
  The switch is a module constant, so no runtime flip leaves a stale prev set.
- **Substrate `_kind_on_now`** (`occupancy_substrate.py:297-319`): event leg and sibling leg both guarded; a dead event
  entity falls through to siblings (which skip the event entity), so a live sibling still holds the kind. Seed and live
  share it. Switch-off live path (`:812-817`) guarded.
- **Discharge `recheck_entities`** (`:334-368`): re-reads the mapped (room, kind) through the one rule, updates
  `_raw_state`, dispatches only on change and only after boot settle (same gate as the live path). Unknown entities and
  override extras (not in the substrate map) are ignored. Dead → live flip re-reads `on` and dispatches True, so
  recovery is symmetric.
- **Ordering:** the tick sets `_dead_now` inside `evaluate` before the flip compare, so the substrate's re-read through
  the getter sees this tick's answer.
- **Restart / reload:** tracker and prev set are RAM. After a restart or room reload, a substrate seed in the first
  grace window counts the frozen `on`; once the new tick passes the grace the flip fires and the recheck dispatches
  False. Bounded by grace + one poll, as documented. Accepted.
- **Census cross-validation ON branch** (`camera_census.py:2023-2029`): the skip is before any `frigate_available` /
  `binary_platforms_available` marking, so a dead camera neither counts nor marks a platform available (missing, not
  zero). `_get_unrecognized_camera_count` (`:6022-6026`): skipped before the platform test, so it can only lower the
  guest count.
- **α gate untouched:** `camera_input_degraded` reads `camera_input_dark` from `compute_camera_input_dark_frame`
  (`camera_census.py:186-275`), which counts Frigate person_count sensors directly and is not affected by the S2 skip.
  The census `degraded_mode` the skip can set (all interior skipped) does not feed α.
- **Presence radar-sole gate** (`presence.py:4302-4308`) and **`_zone_night_rooms`** switch-off limb (`:4346-4352`): dead
  input dropped from the live on-set; both only remove evidence.
- **Zone camera tier** (`presence.py:829-835`): skips a dead camera before both the live and timeout legs.
- **Fan recheck:** reads room-tier fusion-filtered values (`data.occupied`, radar-sole ring), already S1-covered.
- **HVAC room occupancy:** `hvac_occupied` rides room `occupied` (HVAC doc §3.1, C24), S1-filtered. The "HVAC needed no
  change" claim holds for that path; it misses the D6 confidence path (A-M1).
- **Cost:** `_room_coordinators` is O(rooms) per call; called per `on` sibling, per census interior entity per tick.
  Cheap at 40 rooms.

### Truth table, house fold (per input / camera, over rooms R1..Rn)

| Room answers | `_fold` | Reader effect |
|---|---|---|
| all None / no rooms | None | counts as before (byte-identical) |
| ≥1 False, no True | False | counts as before |
| ≥1 True | True | input off / camera skipped / census missing term |
| kill switch False (watched) | False | counts as before |
| a stub's non-bool | ignored | as above |

`entity_stream_dead(e)`: `camera.*` → camera-keyed fold; else input fold if not None; else own camera (exactly one
enabled camera on the device) → camera-keyed fold; unresolved → None.

## G: goal fidelity

- **Agnostic (operator: "Not agnostic enough. Too specific").** PASS. Keyed on camera-entity availability through the
  S1 resolver; no camera name, kiosk app or NVR brand in any S2 site. The camera-keyed getter is the generic hook a
  later NVR witness reads.
- **"If the app is down Ura can't do what it needs to do."** PASS for the measured harm: a frozen panel `on` no longer
  holds its zone (substrate guard + flip discharge), the night-raw limb, the radar-sole fan gate. The objective is
  stream death removing evidence everywhere outside the room; the D6 confidence reader (A-M1) and the fused fan leg
  (A-L3) are the two places it still does not.
- **Hard constraint: AWAY stays fast.** PASS. Every S2 edit only removes evidence (zone, census, guest count, fan
  presence). The α degraded gate is computed elsewhere and is unaffected. No new hold path.
- **Census arithmetic.** Matches the plan: missing term, current trust arithmetic kept, no `deconflict_house`
  pre-emption.
- **Builder "not done" list:**
  1. *Fused `camera_person_detected` not honouring the getter (fan_veto's preferred leg)* — CARD, not this cycle.
     Live config: no room lists a panel in `CONF_ROOM_CAMERAS`, so the measured harm does not reach it; the effect is
     comfort-only and fails toward the fan running. The fix changes a room entity's state and attributes (agreement /
     confidence), which deserves its own small plan. The README / state-of-play must say the fan camera leg is
     uncovered in practice (A-L3), not imply coverage.
  2. *Census face reads / stuck-camera watchdog* — CARD. Face legs are freshness-windowed (`CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`
     1800 s), so a dead camera's last face ages out; the watchdog already discounts downward only. Low marginal value.
  3. *Perimeter ring cameras unwatched → `camera_stream_dead` None* — CARD against W6b. None is the correct "unknown";
     no current consumer. W6b must add its own watch through the same tracker, not a second rule.
  - Add A-M1 (D6 confidence Source 3) as a fix in this cycle: one line, same guard, a Tier-1-size change.

## Verdict

**FIX-REQUIRED** (small).

Must-fix before ship:
1. A-M1: guard `check_zone_occupancy_confidence` Source 3 with `_camera_entity_stream_dead` + a mutation-anchored test.
2. A-M2: rewrite the README (and plan S2 "Live") acceptance so the panel criterion is the zone/substrate one and the
   census criterion names an interior census camera outage.

Fix in cycle if cheap (LOW): A-L1 (move the skip after device dedup), A-L2 (diagnosis label guard), A-L3 (README /
state-of-play wording). Card: fused fan leg, census face/watchdog, perimeter watch for W6b.

| Severity | Found | Must-fix | Card / optional |
|---|---|---|---|
| MEDIUM | 2 | 2 | 0 |
| LOW | 3 | 0 | 3 |

Bug classes: #53 one missed site (A-M1, A-L3), #63 concept split (A-L1), non-discriminating acceptance (A-M2).

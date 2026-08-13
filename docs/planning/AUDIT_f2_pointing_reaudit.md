# AUDIT: FRIGATE-RETIRE-1 Gate-2 re-audit — F2-pointing verification

**Date:** 2026-08-13 (post F1 disable). **Mode:** read-only.
**Context:** Frigate-1 HA integration entry `01JV6G4E57HT3WH86WSQ4RJT11` ("Frigate 1", `disabled_by: user`)
is disabled+unloaded; its container is about to stop. Frigate-2 entry `01KM239Z8ZQWQTN1D9CV5JRA7V`
("Frigate 2") is loaded. Registry state: **965 F1 entities remain in the registry, all
`disabled_by: config_entry`** (not deleted); their state objects currently linger as `unavailable`
until the next HA restart, after which they vanish from the state machine entirely. F2 owns 964
entities (817 still carry a `_2` suffix; the 25 `*_f1retired` renames from 08-12 moved F2 copies
into base names for the URA-referenced set only).

## Verdict summary

| # | Surface | Verdict |
|---|---------|---------|
| 1 | URA config entries | **CLEAN** (0 F1 refs; 29 F2 refs verified) |
| 2 | Live states spot-check | **CLEAN** (12 checked, all fresh, `client_id=frigate-f2`) |
| 3 | URA snapshot engine (perimeter_alert.py) | **CLEAN** (one LOW self-healing note) |
| 4 | automations.yaml + lovelace | **1 MEDIUM FINDING + 2 LOW + 1 INFO** |
| 5 | MQTT dual-prefix bridge | **CLEAN** |
| 6 | HA error log since disable | **CLEAN** |
| 7 | camera_census + CameraResolver | **CLEAN** (one LOW latent note) |

---

## 1. URA config entries — CLEAN

Parsed all `universal_room_automation` entries in `.storage/core.config_entries`, extracted every
`image./camera./binary_sensor./sensor./switch./number.` reference (443 distinct), cross-checked each
against `core.entity_registry` `config_entry_id`:

- **F1-owned refs: 0.** (The 08-12 migration's 26 mapped refs held; independent re-sweep found no missed ones.)
- **F2-owned refs: 29** — e.g. `camera.back_yard`, `camera.foyer_fisheye`, `camera.doorbell_lite`,
  `camera.armcrestash41b_2` (Study A), `binary_sensor.garage_b_person_occupancy` (Garage B),
  `binary_sensor.staircase_person_occupancy` (Garage Hallway), `binary_sensor.family_room_person_occupancy`,
  `binary_sensor.upstairs_hall_all_occupancy`, `binary_sensor.playroom_all_occupancy_2` (Zone Manager).
- **Refs resolving to nothing: 7 — all non-Frigate, pre-existing, out of scope** (informational):
  `binary_sensor.openclose_aquara_zigbee_jayabedroom_contact`,
  `binary_sensor.waterleak_sonoff_zigbee_ziribathroom_water_leak_2`,
  `sensor.openclose_aquara_zigbee_jayabedroom_device_temperature`,
  `sensor.towerfandreowifilivingroom_temperature_2`, `switch.master_bedroom_television`,
  2× `switch.smartplug_moes_wifi_garagealeftfront_socket_*` (Zigbee/WiFi devices, not camera entities).

## 2. Live states — CLEAN

Spot-checked 12 URA-referenced entities via live template render (2026-08-13 17:16 UTC):

- Cameras `back_yard`, `foyer_fisheye`, `family_room`, `master_hallway`, `garage_a_2`,
  `doorbell_lite`, `hot_tub`: all `recording`, **`client_id=frigate-f2`**, `last_reported` seconds old.
- Occupancy sensors `back_yard_person_occupancy_2`, `staircase_person_occupancy`,
  `garage_b_person_occupancy`, `family_room_person_occupancy`, `upstairs_hall_all_occupancy`:
  all `off` with `last_reported` < 30 s old (live MQTT flow from F2).

Control check: F1-owned ids (`binary_sensor.back_yard_person_occupancy`, `camera.garage_a`, etc.)
all read `unavailable` — confirmed dead as expected.

## 3. URA snapshot engine — CLEAN (LOW note)

- `_discover_frigate_instance_ids` (perimeter_alert.py:3030-3055) reads
  `hass.data['frigate'][entry_id]['config']['mqtt']['client_id']` from **loaded** entries only.
  With F1 unloaded, next discovery yields `['frigate-f2']` only.
- **LOW (self-healing, no action):** discovery runs once at snapshot-dir setup (SNAP-1, ~:2718),
  so until the next URA reload/HA restart the in-memory `_frigate_instance_ids` may still contain
  F1's client_id. Consequence is bounded by design: the candidate loop (:3036-3067) tries the
  learned/other instance URLs in sequence and **invalidates a learned instance on miss**
  (`_camera_frigate_instance.pop`, :3061), so a dead F1 candidate costs one failed HTTP GET before
  falling through to `frigate-f2`. Learned map is in-memory only — a restart clears it cleanly.
- `base_engine` endswith check (:464): URA-configured Frigate person sensors all use base
  `*_person_occupancy` names (no `_2` on the person legs URA is configured with) → still classify
  as `frigate`. No breakage.
- Hardcoded `'frigate'` strings audit: all remaining occurrences are **engine/platform labels**
  (`camera_resolver.py:123`, `const.py:1312`, `camera_census.py:854`, `transit_validator.py:1157`,
  `perimeter_alert.py:440/464`) — none is an F1 *instance-id* assumption. The non-instance-scoped
  default URL `/api/frigate/notifications/...` is only used when zero instances are discovered
  (:3043-3048), which cannot occur while F2 is loaded.
- Live: `sensor.universal_room_automation_last_perimeter_alert` fired 2026-08-13 10:02 CT — engine
  active. Verify a snapshot attaches on the next organic alert (no error-log evidence of failures).

## 4. automations.yaml + lovelace — 1 MEDIUM, 2 LOW, 1 INFO

No `*_f1retired` references anywhere (automations.yaml + all 22 `.storage/lovelace*` files).

- **FINDING (MEDIUM)** — `automation.g6_doorbell_analysis` (id `1756527184585`, "G4 Doorbell
  Analysis", **enabled**, last fired 2026-08-12): blueprint input
  `motion_entity: binary_sensor.madrone_g6_entry_motion_2` is **F1-owned and now dead**.
  Consequence: AI doorbell analysis for the G6 entry camera silently never fires again.
  Smallest fix: repoint `motion_entity` to `binary_sensor.madrone_g6_entry_motion_3` (the F2 copy)
  — or the native UniFi motion sensor. (`camera_target: camera.madrone_g6_entry` is fine — F2-owned.)
- **FINDING (LOW)** — `.storage/lovelace.ura_v8` references `camera.armcrestash41b` (F1) →
  blank/unavailable card after restart. Fix: `camera.armcrestash41b_2`.
- **FINDING (LOW)** — `.storage/lovelace.ura_v6` references `camera.garage_a` (F1). Fix: `camera.garage_a_2`.
- **INFO (no runtime impact)** — "Phase 1: All Detections - Dual System (AI)" (id `1770938962920`)
  and "Phase 1: Known Person - Dual System" (id `1770938962921`) reference ~38 now-dead F1 base-name
  ids (13 `*_person_occupancy` triggers, `camera.garage_a/garage_b/rear_ptz/utilities_ptz`,
  all `*_last_recognized_face` sensors) plus 3 `sensor.*_last_identified_person` ids that don't exist
  at all. **Both automations have been disabled since 2026-02-17/18** — dead weight, not a live
  dependency. If ever re-enabled they must be migrated to `_2` names (or deleted; URA perimeter
  alerting has superseded them).

## 5. MQTT dual-prefix bridge — CLEAN

`automation.frigate_mqtt_to_frigate_events_bridge_ura_snapshot_support` (id `1785624383111`):
subscribes `frigate/events` + `frigate2/events`, mode queued. Last triggered 2026-08-13 12:11 CT
(via `frigate2/`). A silent `frigate/` topic produces no errors — MQTT subscriptions to quiet topics
are free. No MQTT-related warnings/errors in the log. The FRIGATE-RETIRE-1 recording tripwire
automation (`frigate2_recording_tripwire`) watches `sensor.phalanxu8_423_share_frigate2_usage` — F2-only, correct.

## 6. HA error log since disable — CLEAN

`error_log` + `system_log` sweeps for `frigate` / disabled-entry symptoms: only two pre-existing,
retirement-unrelated warning families — `frigate_config_builder.discovery.*` "Could not get stream
URL" (recurring every 30 min since before the disable) and generic slow-entity-update warnings
(one on an F2 sensor, cosmetic). Zero errors referencing the disabled entry, orphaned devices,
or failed lookups of F1 entities.

## 7. camera_census + CameraResolver — CLEAN (LOW latent note)

- **CameraResolver** explicitly skips disabled entities: `camera_resolver.py:491` and `:942`
  (`disabled_by is not None` gates, A-MED-1 / Bug Class #21 "disabled-entity leakage"). F1's 965
  disabled entities cannot be pulled into a fusion or leg set.
- **camera_census** live path is **configured mode** (`_discover_from_configured_cameras`,
  camera_census.py:737 — URA has camera lists configured), which routes through the resolver →
  disabled-safe. Runtime reads are `hass.states.get(...)` → F1 entities return
  unavailable/None and are handled as absent.
- **LOW (latent, not live):** the legacy `_discover_full_scan` path (camera_census.py:776) iterates
  the entity registry with **no `disabled_by` filter** and would admit all disabled F1
  `*_person_occupancy` sensors if URA were ever run without configured camera lists. Consequence
  bounded (states reads return None), but worth a one-line `disabled_by` gate whenever that file is
  next touched. No log evidence of census errors since the disable.

---

## Actions (smallest fixes, none blocking container stop)

1. **MED:** repoint G6 Doorbell Analysis `motion_entity` → `binary_sensor.madrone_g6_entry_motion_3`.
2. **LOW:** ura_v8 dashboard `camera.armcrestash41b` → `camera.armcrestash41b_2`; ura_v6
   `camera.garage_a` → `camera.garage_a_2`.
3. **Cleanup (optional):** delete or migrate the two long-disabled Phase-1 dual-system automations.
4. **Latent LOW:** add `disabled_by` filter to `_discover_full_scan` next time camera_census.py is touched.

Nothing found that depends on the F1 container being up. **Gate-2: PASS with the above follow-ups.**

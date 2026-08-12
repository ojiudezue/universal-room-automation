# AUDIT: FRIGATE-RETIRE-1 Step 1 — Capability Inventory + Parity Audit

**Date:** 2026-08-12 · **Read-only** — no config changed anywhere. Do not commit (contains host/entry details).
**Scope:** retire Frigate-1 (192.168.13.16, HA entry "Frigate 1", MQTT prefix `frigate`, Coral edgetpu);
promote Frigate-2 (192.168.13.18, "Frigate 2", prefix `frigate2`, 3× OpenVINO + custom `yolov9t.onnx`) to primary.
**Builds on:** `docs/planning/AUDIT_frigate1_sunset.md` (2026-08-06 — full blast-radius audit; still valid, cross-checked below)
and `docs/planning/AUDIT_perimeter_fp_correlation.md` (2026-08-12 — 7-day FP evidence).
**Sources (fresh today):** live `/api/config` from BOTH Frigate hosts (POST `/api/login` + cookie, curl -sk; creds from
`core.config_entries`); `.storage/core.config_entries` + `core.entity_registry` (Samba mount `/Users/okosisi/ha-config`);
live `automations.yaml`; `.storage/lovelace.ura_v8` / `lovelace.ura_v6`; `perimeter_alert.py`, `camera_resolver.py`;
`~/Code/homelab-automation/docs/CONFIGS.md` §4.

Config-entry ids: **F1** `01JV6G4E57HT3WH86WSQ4RJT11` (`https://192.168.13.16:8971`) ·
**F2** `01KM239Z8ZQWQTN1D9CV5JRA7V` (`https://192.168.13.18:8971/`). Both have
`notification_proxy_enable: true` (snapshot proxy works for either instance).

---

## 1. Camera coverage parity (live `/api/config`, 2026-08-12)

**24 cameras defined on EACH host — identical sets, identical tracked-object lists, identical
detect/record/snapshots enablement**, verified camera-by-camera from both runtime configs.
(Prior audit said 23; today's configs show 24 including `madrone_g6_entry_package`.)

- **The ONLY divergence: `ArmCrestASH41B` — `enabled: true` on F1, `enabled: false` on F2.**
  Deliberate: the consumer-grade cam serves only ONE NVR at a time (CONFIGS.md §4). F2's block is
  complete and correct (creds/channel=1) — flip to `enabled: true` when F1 stops pulling it.
- **Zero cameras exist on F1 only.** No class (person/car/dog/cat) tracked on F1 but not F2 — the
  `objects.track` lists match per camera on both hosts.
- Enrichment parity (both hosts): face_recognition (large) ✅ · lpr (small) ✅ · semantic_search (large) ✅ ·
  audio ✅ · birdseye ✅ · genai→Ollama ✅ (F1 got parity 2026-08-01).
- Detector: F1 `coral` (edgetpu, default model); F2 `ov`/`ov_1`/`ov_2` (openvino,
  `/config/model_cache/yolov9t.onnx`). Measured headroom (prior audit, `/api/stats` 2026-08-06):
  F2 at ~17% of ~235 inf/s — ASH41B absorption trivial.
- Retention: F1 alerts/detections 30 d/7 d (per CONFIGS.md; API shows record.alerts/detections retain
  3 d on F1 vs **14 d on F2**) — F2's retention is deliberately NOT synced to F1 (disk-refill risk, CONFIGS.md §4).
  Retirement makes F2 the recording of record → the "retention not pruning" work item in CONFIGS.md becomes load-bearing.

**Coverage-gap verdict: NONE, contingent on the ASH41B enable-flip being part of the swap.**

## 2. HA entity census + consumers

Entity registry: **F1 entry = 965 entities** (base ids, e.g. `binary_sensor.back_yard_person_occupancy`,
`camera.back_yard`, `sensor.<cam>_last_recognized_face`, `_plate`, per-class occupancy/count, review
alert/detection switches, sound sensors). **F2 entry = 964 entities**, all `_2`/`_3`-suffixed
(`binary_sensor.back_yard_person_occupancy_2`, `camera.back_yard_2`, …) because F1 claimed the base
names first. Per the prior audit's verified registry semantics: **deleting the F1 entry frees the base
ids but never auto-renames F2's `_2` entities** — the rename batch (sunset plan step 6, Option B) is a
separate, later step and NOT part of the parity window.

### 2a. URA config-entry consumers of F1 entities (live `core.config_entries`, exact key paths)

| Entry | Key | F1 entities |
|---|---|---|
| Universal Room Automation (integration) | `options.perimeter_cameras` | `camera.reolinkstudybporchptz`, `camera.front_side_ptz`, `camera.armcrest`, `camera.hot_tub`, `camera.pool_equipment`, `camera.g5_bullet`, `camera.back_yard` (7 of 9; other 2 are Protect) |
| 〃 | `options.egress_cameras` | `camera.madrone_g6_entry`, `camera.doorbell_lite`, `camera.front_door_aerial` (all 3) |
| 〃 | `options.camera_person_entities` | `camera.master_hallway`, `camera.playroom`, `camera.foyer_fisheye`, `camera.family_room` (4 F1 rows; each has a Protect sibling row — dead-but-redundant post-retirement) + `camera.stairs_top_2` (already F2) |
| URA: Zone Manager | `options.zones.<zone>.zone_cameras` | Back Hallway: `binary_sensor.staircase_all_occupancy` · Entertainment: `family_room_person_occupancy`, `foyer_fisheye_person_occupancy`, `master_hallway_person_occupancy` · Master Suite: `master_hallway_person_occupancy` · Upstairs: `upstairs_hall_all_occupancy`, `stairs_top_person_occupancy` (+ `playroom_all_occupancy_2` already F2) |
| Garage Hallway (room) | `data.motion_sensors` / `data+options.occupancy_sensors` | `binary_sensor.staircase_motion_2` (an F1 entity despite the `_2` — it is F1's second *class* sensor, registry-confirmed), `binary_sensor.staircase_person_occupancy` |
| Garage B (room) | `data.motion_sensors` / `data+options.occupancy_sensors` | `binary_sensor.garage_b_motion_2`, `binary_sensor.garage_b_all_occupancy`, `binary_sensor.garage_b_person_occupancy` |
| Study A (room) | `options.room_cameras` | `camera.armcrestash41b_2` — **already F2-pointed**; goes live only after the ASH41B enable-flip |

### 2b. HA automations (`automations.yaml`)

- **`Phase 1: Known Person - Dual System`** (the doorbell/perimeter face-alert pipeline, ids
  `<cam>_person_frigate`): triggers on **16 F1 person sensors** (armcrest, back_yard, doorbell_lite,
  front_door_aerial, front_side_ptz, g5_bullet, garage_a, garage_b, hot_tub, madrone_g6_entry
  (+`_motion_2`), pool_equipment, rear_ptz, reolinkstudybporchptz, utilities_ptz), snapshots **14 F1
  `camera.*` entities**, and reads **13 F1 `sensor.*_last_recognized_face`** sensors. All F1-sourced;
  zero F2 references. This is the single biggest non-URA consumer.
- **`Frigate MQTT to frigate_events bridge (URA snapshot support)`** (id `1785624383111`, v5.44.0
  2026-08-01): already subscribes to **BOTH** `frigate/events` and `frigate2/events` → fires
  `frigate_events` on the HA bus. **No change needed for the swap**; after retirement the
  `frigate/events` trigger goes silent (harmless; prune at final cleanup).
- Wallpanel fleet wake: uses `binary_sensor.foyer_fisheye_person_occupancy` (F1) — needs a `_2` re-point.

### 2c. Dashboards (best effort, `.storage/lovelace*`)

- `lovelace.ura_v8`: **1** F1 entity — `camera.armcrestash41b` (Study A card).
- `lovelace.ura_v6` (legacy): `camera.back_yard`, `camera.front_door_aerial`, `camera.garage_a`,
  `camera.madrone_g6_entry`.
- Zero F2 refs on any dashboard today.

## 3. URA snapshot-engine wiring (perimeter_alert.py) — what must change: **nothing in code**

All file:line refs `custom_components/universal_room_automation/perimeter_alert.py` @ develop a7ff3574.

- **Event-id cache:** `_on_frigate_event` (`:743`) listens to the `frigate_events` bus event
  (`FRIGATE_EVENTS_BUS_EVENT`, `:237`) and caches `camera_name → (event_id, ts)` in
  `_frigate_last_event_id` (`:275`). The bridge automation feeds it from both MQTT prefixes, keyed by
  camera name (identical on both hosts) — after F1 retires, only `frigate2/events` populates it. No change.
- **Instance discovery is automatic:** `_discover_frigate_instance_ids` (`:2718-2739`) enumerates MQTT
  `client_id`s from `hass.data["frigate"]` — currently `["frigate-f1", "frigate-f2"]` (live configs:
  `mqtt.client_id` = `frigate-f1` / `frigate-f2`). After F1's HA entry is removed it returns
  `["frigate-f2"]`. No change.
- **Snapshot URL selection:** `_try_capture_frigate_event` (`:2998-3082`) builds instance-scoped URLs
  `/api/frigate/<client_id>/notifications/<event_id>/snapshot.jpg`, tries the learned instance first
  (`_camera_frigate_instance`, `:342`), **invalidates the learned instance on a miss** (F4 fix, `:3055-3061`)
  and re-learns from the successful URL — so cameras "migrating" from F1 to F2 self-heal per event.
  It deliberately does NOT try the un-prefixed default URL while ≥2 instances exist (F4, `:3030-3050`),
  which sidesteps the prior audit's open question about which entry the default proxy serves.
- **Legacy (non-SNAP-1) snapshot URL:** `_resolve_snapshot_url` (`:1595-1603`) still emits the
  un-prefixed `/api/frigate/notifications/<eid>/snapshot.jpg`. During the parity window (both entries
  loaded) this path is ambiguous IF the kill switch has re-engaged the legacy URL — **P6 below tests
  the actual delivered snapshot**; post-retirement (single entry) the default shape is unambiguous.
- **Leg subscription:** `_wire_camera` (`:442-534`) resolves person legs from the CONFIGURED
  `camera.*` entity via the resolver, tagging engines `frigate`/`frigate2` by `_2` suffix
  (`_leg_tag` `:435-440`; resolver `_engine_tag` camera_resolver.py:1153). **Both legs are already
  subscribed today** (fused sourcing) — the parity window needs no URA change to *receive* F2
  detections. The prior audit's key caveat stands: resolution starts from the configured camera
  entity, so the F1 `camera.*` rows must be re-pointed **before** the F1 entry is ever deleted
  (class (c) breaks), but for the parity window itself (F1 entry still loaded, cameras merely
  disabled on the F1 host) the entities persist and legs stay wired.
- **⚠ One code-level watch item for the eventual re-point:** `base_engine` derivation at `:464` uses
  `base_bs.endswith("_person_occupancy")` — a re-pointed base of `..._person_occupancy_2` fails that
  check (and the `_2` sibling probe at `:481` would look for `..._2_2`). Preferred mitigation: re-point
  the URA camera lists to **Protect camera entities** where they exist (egress ×3 + 5 perimeter), and
  `_2` Frigate cameras only where no Protect sibling exists (`reolinkstudybporchptz`, `armcrest`) —
  the resolver reaches the F2 person legs from either input (stem index normalizes `_2`,
  camera_resolver.py:502-505). Flag for the Step-2 plan review; not a Step-1 blocker.

## 4. Recording / review duties (CONFIGS.md §4 + live configs)

- **F1**: records to local USB, **468 G, 90% full**, retention 30 d/7 d/30 d configured (API reports
  3 d alerts/detections — config drift to verify at swap time, not load-bearing for retirement).
- **F2**: records to CIFS→Unraid `//192.168.13.11/Frigate2`, **7.3 T, 75% full**, 14 d/3 d/14 d —
  deliberately NOT raised (disk-refill → the 2026-08-01 `/tmp/cache` outage class). **Known F2 fragility:**
  the 8-day silent-recording outage (watchdog loop filling tmpfs). Recurrence tripwire:
  `docker exec frigate df -h /tmp/cache`. Retirement makes F2 the sole Frigate recorder → the
  disk-usage + `/tmp/cache` Pushover alert proposed in CONFIGS.md should ship BEFORE or WITH the swap
  (F1's copy of recordings disappears as a safety net).
- Review/alert switches (`switch.<cam>_alerts` / `_detections`, F1 base ids ×23 + F2 `_2` set): no
  automation or URA consumer found; UI-only. HA-side alert consumers are URA's PerimeterAlertManager
  (NM channels) + the Phase-1 automation (§2b).
- **Double-take** container runs alongside F1 only (CONFIGS.md) — anything consuming it needs its own
  check at NUC-retirement time (outside URA scope; no HA entity consumers found in this sweep).

## 5. Parity checklist P1–P7 (testable on organic events, ledger/recorder)

Baseline evidence (AUDIT_perimeter_fp_correlation.md, 7 d to 2026-08-12): F1 daytime is healthy
(75–95% engine agreement with Protect on healthy cams) but is ALSO the sole source of the nighttime
FP blips (100% of alert-hour edges = frigate-1, sub-2 s, IR-mode). F2 fires far less than F1 today
(e.g. front_side 91 vs 697 edges/7 d) — partly FP inflation on F1, partly a real sensitivity delta
to prove out. Oracles: HA recorder `states` (rising edges per sensor), URA `notification_log`
(alert delivery + snapshot URL), Frigate `/api/events` per host.

| # | Capability | Test (organic, per camera) | PASS bar |
|---|---|---|---|
| **P1** | **Daytime person-detection parity** (headline — F1 daytime was healthy) | For each of the 9 perimeter + 3 egress cameras, over the window: recorder edges of `<cam>_person_occupancy_2` vs Protect `<cam>_person_detected` (±120 s agreement), same method as FP-audit Q3 | F2↔Protect agreement ≥ F1↔Protect baseline on the same camera (Q3 table); no camera where Protect fires ≥3 daytime person events with zero F2 corroboration |
| **P2** | Alert-hours behavior (23:00–05:00 CDT) | Count F2 person edges + their corroboration during alert hours | F2 does NOT reproduce F1's single-witness sub-2 s blip morphology (median on-duration > 2 s; SW rate materially below F1's 49–94%); genuine nighttime events (if any) corroborated by Protect |
| **P3** | Per-class parity (car/dog/cat where tracked) | Recorder edges on `_2` car/dog/cat occupancy sensors for the 8 cameras tracking them vs F1 base over the same window | Each (camera, class) with ≥1 F1 event in window has ≥1 F2 event OR an explained delta (e.g. F1 FP) |
| **P4** | URA perimeter/egress alert delivery via F2 leg | `notification_log`: alerts whose firing sensor is a `_2` engine leg (`sensor_engine=frigate2` in dispatch telemetry / coverage logs) | ≥1 organic F2-sourced alert per perimeter camera; zero "no `_2` sibling" WARNs on Frigate-based rows |
| **P5** | Interior census / zone presence via F2 | Zone Manager zone_cameras rows (§2a) — during F1-camera-disable window, zones still see camera occupancy (recorder on `_2` sensors + URA zone state) | No zone loses camera-leg presence; playroom `_2` row (already F2) keeps working |
| **P6** | **Snapshot quality + routing** (event best-frame via F2 proxy) | For each F2-sourced alert: `notification_log` snapshot URL is instance-scoped `/api/frigate/frigate-f2/notifications/…` (or learned-instance log line), image non-empty and shows the right camera view | 100% of F2-sourced alerts carry a fetchable, correct-view snapshot; zero wrong-camera images (the F4 cross-host hazard) |
| **P7** | Enrichment parity (face / plate / genai) | `sensor.<cam>_last_recognized_face_2` + `_plate_2` update on organic events; Phase-1 automation equivalent works when re-pointed | Face sensor updates for ≥1 known-person event on an egress cam; LPR updates on ≥1 vehicle event; genai descriptions present on F2 events |

Window sizing: FP-audit rates suggest most cameras see multiple organic person events per day; 7 days
matches the baseline window and covers weekly patterns. Low-traffic cameras (armcrest,
reolinkstudybporchptz: ~18/17 edges per 7 d) set the floor.

## 6. Swap plan — minimal, reversible config changes to OPEN the parity window

Deliberately smaller than the full sunset (AUDIT_frigate1_sunset.md §5): the parity window runs with
**both HA entries loaded and F1's host still up**; only detection duty shifts. Every step reverts by
pasting back the recorded value.

| # | Change | Where | Revert |
|---|---|---|---|
| S1 | **Nothing for URA leg subscription** — fused sourcing already subscribes base+`_2`; F2 detections already alert today | — | — |
| S2 | **ASH41B hand-off**: F1 config `ArmCrestASH41B.enabled: false` (save+restart via `/api/config/save?save_option=restart`), verify F1 clean, then F2 `enabled: true` (same API) | Frigate configs (both hosts) | Re-flip the two flags. NEVER both enabled (watchdog-loop/tmpfs outage class) |
| S3 | **Disable F1's camera fleet** (`enabled: false` per camera; F1 service + HA entry stay UP so base entities remain `unavailable`, not deleted — legs stay wired, no URA reload needed) | F1 config | Re-enable F1 cameras |
| S4 | Ship the F2 `/tmp/cache` + disk-usage tripwire alert (CONFIGS.md §4 item 5) — F2 becomes sole recorder | homelab (Pushover/NM) | Remove alert |
| S5 | *(Optional during window, required before entry deletion)* Re-point Phase-1 automation triggers/cameras/face-sensors and wallpanel foyer sensor to `_2`/Protect ids — OR defer to the post-window rename batch (Option B resurrects base ids without editing consumers) | automations.yaml | Paste back |
| S6 | Run P1–P7 over ≥7 days of organic events | recorder + notification_log | — |

**Explicit non-goals for this window:** deleting the F1 HA entry, renaming `_2`→base, re-pointing the
10 URA camera-list rows, retiring the NUC — all sequenced AFTER parity passes (sunset plan steps 5–7).
The recommendation to defer S5 via Option B (delete entry → bulk-rename `_2`→base → base-id consumers
resurrect untouched) stands from the prior audit and avoids editing 30+ automation references twice.

## 7. Verdict: **GO** to start the parity window, with 3 adjustments

Coverage is not at risk: camera sets, tracked classes, and enrichment features are identical (§1);
F2 headroom is measured-ample; URA already subscribes both engine legs and the snapshot engine
discovers/learns instances automatically (§3). The FP evidence actively favors the swap — F1 is the
sole source of this week's nighttime false positives.

Adjustments before/at window open:
1. **ASH41B enable-flip (S2) is mandatory at window open** — it is the only coverage gap, and Study A's
   config already points at the F2 entity that is currently dead.
2. **Ship the F2 recorder tripwire (S4) with the swap**, not after — F2 has an 8-day silent-outage
   history and becomes the sole Frigate recorder.
3. **P1 needs the F2-sensitivity question answered honestly**: F2's raw edge counts are far below F1's;
   the parity bar is agreement-with-Protect (true-positive parity), not raw edge-count parity — a
   window where F2 misses Protect-corroborated daytime persons on any camera is ADJUST (tune yolov9t
   thresholds per camera) before proceeding to entry deletion.

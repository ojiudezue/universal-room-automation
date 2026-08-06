# AUDIT: Exterior Camera Person-Detection Settings (read-only)

**Date:** 2026-08-06 · **Read-only** — no config changed anywhere.
**Motivation:** `AUDIT_exterior_camera_adjacency_probe.md` ratification removed two co-firing-but-not-adjacent pairs (rear_ptz↔utilities_ptz 17x, pool_equipment↔rear_ptz 6x) as missed-intermediate artifacts: a MIDDLE camera failed to detect the person during a real traversal, splitting one track into two threads. Priority cameras: `front_side_ptz` (front route middle) and the pool chain (`armcrest`, `back_yard`, `hot_tub`, `g5_bullet`).

## Sources actually read

- **Frigate 1** (`https://192.168.13.16:8971`, config via `/api/config` on port 5000) — Coral EdgeTPU detector, **default model** (path unset → SSD MobileNet), 320×320.
- **Frigate 2** (`https://192.168.13.18:8971`, config via authenticated `/api/config`) — 3× OpenVINO detectors, **yolov9t.onnx**, 320×320.
- **UniFi Protect** via `unifi-protect` MCP (read-only: list_cameras, get_camera, get_camera_analytics).
- **7-day event counts** reused from the adjacency probe doc (2026-07-30 → 2026-08-06, 659 ON-events).

**Could NOT read (honest gaps):**
- **Protect smart-detect sensitivity and zone GEOMETRY** — the MCP surface exposes only zone *counts* (`motion_zone_count`, `smart_detect_zone_count`) and last-detected timestamps per type, not sensitivity sliders or polygon coordinates. Verifying whether a Protect detection zone excludes a walkway requires the Protect web UI.
- **Protect MCP data is stale:** every camera reports `recording_end` ≈ **2026-07-25** and last smart detects ≤ 07-25 (12 days ago). Config-shaped facts (types enabled, zone counts) are likely still valid; live-state facts from Protect in this audit should be re-checked after the MCP session reconnects.
- **PTZ pointing/patrol state** — Frigate config carries no PTZ preset info; whether the three G5 PTZs are parked on the traversal corridors is unreadable here (Protect UI question).

**Note on architecture:** all `*_person_occupancy` entities are **Frigate** sensors. Protect is the *stream source* (rtsps `192.168.15.173:7441`) for every fleet camera except `armcrest` (direct Amcrest RTSP `192.168.15.96`) and `reolinkstudybporchptz` (Reolink). Protect's own smart detections do NOT feed these entities; they only matter as a corroboration/backup channel. Both Frigate hosts still share MQTT prefix `frigate` (known upstream issue), so each entity merges F1 (Coral/SSD-MobileNet) and F2 (yolov9t) detections from the SAME sub-streams.

## Headline finding

**Frigate per-camera config is completely uniform and permissive — masks and zones are NOT the cause of missed middles.** Every fleet camera on both instances has: `person` tracked, `min_score 0.5`, `threshold 0.7`, `min_area 0`, **no object mask, no motion mask, no zones**, detect `enabled`, 5 fps, snapshots+record on. Nothing excludes any walkway. The plausible miss mechanisms are instead:

1. **Detect-stream resolution × model input.** Detect runs on the 640×360 low sub-stream (704×480 Amcrest, 640×480 Reolink, 352×480 G6 Entry), fed to a **320×320** model. A walker at the far edge of a wide yard view (back_yard, hot_tub, armcrest overhead, g5_bullet) can be tens of pixels tall — below reliable detection for SSD-MobileNet especially (F1/Coral).
2. **Confirmation gate:** `threshold 0.7` + `min_initialized 2` @ 5 fps — a fast, partially-occluded, or distant crosser must score ≥0.7 on ~2 frames to latch a track. Middles seeing the person obliquely/briefly are exactly the ones that fail this.
3. **PTZ aiming:** `front_side_ptz`, `rear_ptz`, `utilities_ptz` are G5 PTZs. If `front_side_ptz` is panned off the side-yard corridor, the front-route middle is blind regardless of any Frigate setting — invisible to this audit (see gaps).

## Per-camera findings

Platform legend: F = Frigate (both F1+F2 unless noted) / P = Protect stream source + Protect native smart detect. Frigate settings identical on F1 and F2 for every camera below (verified field-by-field), except the noted `ArmCrestASH41B` asymmetry. Protect person smart-detect: ON (1 smart-detect zone) for every Protect camera queried; sensitivity unreadable (gap above).

| Camera | Platform | Person det ON? | Score gates (Frigate) | Mask/zone concern | Detect stream → model | 7-day events | FINDING |
|---|---|---|---|---|---|---:|---|
| `front_side_ptz` | F + P (G5 PTZ) | Yes (F+P) | min_score .5 / thr .7 / min_init 2 | none — no masks/zones | 640×360 @5fps → 320² | 96 | **suspect: PTZ aiming + 0.7 confirm gate** — front-route middle; verify parked position covers side-yard corridor |
| `armcrest` | F only (direct Amcrest RTSP) | Yes | same | none | 704×480 @5fps → 320² | 39 | **suspect: overhead pool view, small/foreshortened persons vs 320² model**; also F1 runs sibling `ArmCrestASH41B` enabled while F2 has it disabled (config drift, different camera but same family) |
| `back_yard` | F + P (G5 Turret Ultra) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 28 | **suspect: wide yard, distant walkers sub-resolvable at 640×360→320²**; lowest middle count on the chain |
| `hot_tub` | F + P (G5 Turret Ultra) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 28 | **suspect: same as back_yard** — 28 events vs pool_equipment's 93 despite being the chain link before it |
| `g5_bullet` | F + P (G5 Bullet) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 45 | suspect (mild): chain entry cam; same resolution/gate mechanism |
| `rear_ptz` | F + P (G5 PTZ) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 75 | OK (seam endpoint — it fires; the middles miss) |
| `utilities_ptz` | F + P (G5 PTZ) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 58 | OK (seam endpoint) |
| `pool_equipment` | F + P (G5 Turret Ultra) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 93 | OK for detection; 93/wk with weak chain corroboration — probe already flagged possible over-fire (service activity), not a miss problem |
| `reolinkstudybporchptz` | F only (Reolink) | Yes | same | none | 640×480 @5fps → 320² | 30 | OK |
| `madrone_g6_entry` | F + P (G6 Entry) | Yes (F+P) | same | none | **352×480** @5fps → 320² | 48 | OK (egress, close-range doorbell framing suits low res) |
| `doorbell_lite` | F + P (Doorbell Lite) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 33 | OK (egress) |
| `front_door_aerial` | F + P (G5 Turret Ultra) | Yes (F+P) | same | none | 640×360 @5fps → 320² | 34 | OK (egress) |

**No camera has person detection OFF, and no mask/zone covers any traversal path (there are zero masks and zero zones fleet-wide).** Nothing is outright *misconfigured*; the fleet is uniformly tuned for precision (0.7 threshold) over recall, which is exactly the trade that drops brief middle-camera sightings.

## Recommendations (prioritized, operator action)

1. **Recall-tune the four seam middles on BOTH Frigate instances** (`front_side_ptz`, `back_yard`, `hot_tub`, `armcrest`; optionally `g5_bullet`): lower person `threshold` 0.7 → 0.6 (keep `min_score` 0.5) and set `detect.min_initialized: 1`. This directly attacks the confirm-gate miss mechanism. Watch the ghost-FP history (Bug Class #48 / v4.7.14): URA's downstream trust vetoes already absorb upstream FP noise, and the track linker over-alerts (safe direction) on splits — recall is the cheap side of this trade *for these four cameras only*; do not fleet-wide it.
2. **Raise the detect stream to the Medium channel (1280×720) for `back_yard`, `hot_tub`, and `armcrest`** (Protect Medium channel is enabled and RTSP-published; Amcrest has a higher sub-stream too). 640×360 into a 320×320 model under-resolves distant walkers on wide/overhead views. CPU/TPU cost check first on F1 (Coral is the weaker host); if F1 can't afford it, do it on F2 only — the merged MQTT stream means either host's detection lights the entity.
3. **Verify PTZ parking/patrol in the Protect UI** for `front_side_ptz` (and secondarily `rear_ptz`/`utilities_ptz`): confirm the idle preset actually frames the side-yard traversal corridor. This is unreadable from Frigate/MCP and could single-handedly explain the front-route rear↔utilities co-fires. Also check, in the same UI session, the Protect smart-detect zone geometry for the middles (only zone COUNTS were readable here).

Secondary (not seam-critical): resolve the F1/F2 `ArmCrestASH41B` enabled/disabled asymmetry when the MQTT prefix split lands; note F1 runs the default SSD-MobileNet model while F2 runs yolov9t — after any tuning, re-run the adjacency probe's transition mining to measure whether the middle-camera fire rate on ratified chain hops improved (measure, don't soak-watch).

## Tuning applied (2026-08-06)

Executed per operator adjudication: ArmCrestASH41B is an INTERIOR cam (untouched; the F1/F2 drift finding is void); PTZ parked positions confirmed fine; BOTH engines tuned (Frigate F1+F2 + Protect pass). Before-copies of both hosts' raw + runtime configs saved locally BEFORE any change (NOT committed — they carry live stream credentials and this repo is public) at the main checkout's untracked `docs/planning/backups/f{1,2}_raw_config_2026-08-06.yaml` + `f{1,2}_runtime_config_2026-08-06.json`.

### Frigate changes (per-camera, per-host)

Applied via `POST /api/config/save?save_option=restart` (Frigate 0.17.2 on both hosts), one host at a time, F2 first. The other host was verified detecting (live `/api/stats`) before each restart.

| Camera | Setting | Before | After (F1) | After (F2) |
|---|---|---|---|---|
| front_side_ptz | person threshold / min_score | 0.7 / 0.5 | **0.6** / 0.5 | **0.6** / 0.5 |
| front_side_ptz | detect.min_initialized | 2 (default) | **1** | **1** |
| back_yard | person threshold / min_initialized | 0.7 / 2 | **0.6 / 1** | **0.6 / 1** |
| back_yard | detect stream / resolution | Low `kTV6T19pfApN4U7D` 640×360 | 640×360 (reverted — see below) | **Medium `538nPCLjZfzNe2YZ` 1280×720** |
| hot_tub | person threshold / min_initialized | 0.7 / 2 | **0.6 / 1** | **0.6 / 1** |
| hot_tub | detect stream / resolution | Low `BCE1pp4Ix8POhWpG` 640×360 | 640×360 (reverted — see below) | **Medium `kEHncqTAuEgxnE5M` 1280×720** |
| armcrest (`ArmCrest`) | all | thr 0.7 / min_init 2 / 704×480 | unchanged | unchanged |

Per-camera overrides only; fleet defaults untouched. `min_score` stays 0.5 everywhere. No detection disabled anywhere; no interior camera touched.

**Skipped: armcrest detect-stream upgrade.** Probed the Amcrest encode config directly (`configManager.cgi?action=getConfig&name=Encode`): ALL sub-streams (ExtraFormat 0–2) are capped at **704×480** — no ~720p sub-stream exists on this hardware. The only higher stream is the 2560×1440 main (already the record stream); moving detect there was judged too heavy, especially for F1. Detect stays on 704×480 subtype=1 on both hosts.

**Enabling note: Back Yard's Medium channel was not RTSP-published** (only High + Low). Enabled via Protect MCP `protect_toggle_rtsp` (medium, additive; no detection settings touched) → alias `538nPCLjZfzNe2YZ`. Hot tub Medium (`kEHncqTAuEgxnE5M`) was already published.

**F1 could not afford the 720p detect bump — resolution applied on F2 only.** Timeline (local): F2 saved+restarted 07:13:32, detectors back in ~20 s, verified 07:13:56. F1 saved+restarted 07:14:13 with the full change set (thresholds + 720p); after settle F1 showed decode saturation: back_yard/hot_tub `process_fps` 0.2–0.4 with `skipped_fps` ~4.8 and collateral skipping on ArmCrest/rear_ptz. Reverted the resolution portion on F1 only (second save 07:17:38), keeping threshold/min_initialized. Post-revert F1 settled clean (all cameras proc ≈5 fps, skip ≈0). The merged MQTT prefix means F2's 720p detections still light the shared `*_person_occupancy` entities.

### Verification reads (live `/api/config` after restart)

- **F1** (~07:22): front_side_ptz thr 0.6 / min_init 1 / 640×360; back_yard 0.6 / 1 / 640×360; hot_tub 0.6 / 1 / 640×360; ArmCrest unchanged (0.7 / 2 / 704×480).
- **F2** (~07:14): front_side_ptz 0.6 / 1 / 640×360; back_yard 0.6 / 1 / **1280×720**; hot_tub 0.6 / 1 / **1280×720**; ArmCrest unchanged.

### Post-change `/api/stats` health

| Host | Detector inference (baseline → after) | Camera health after settle |
|---|---|---|
| F1 (Coral) | 28.17 ms → 26.0 ms | all cams proc ≈5 fps, skipped ≈0 (transient rear_ptz 1.5 skip during a vehicle event) |
| F2 (3× OpenVINO) | 10.3–11.3 ms → 11.2–12.2 ms | front_side_ptz / back_yard / hot_tub proc 5.0–5.1, skipped 0.0 at 720p |

No degradation beyond noise on either detector; both far under the 2× revert bar.

### UniFi Protect engine pass

Writability finding: the `unifi-protect` MCP's only camera-settings write tool (`protect_update_camera_settings`) exposes ir/hdr/mic/speaker/status-light/name/motion_detection — **smart-detect sensitivity, per-type toggles, and zone geometry are NOT writable through the MCP**. Per directive, no other write paths were improvised. Read-only verification (MCP analytics + read-only bootstrap pull):

| Camera | Person smart detect | Detect zone | Sensitivity (numeric slider; read-only here) |
|---|---|---|---|
| Front Side PTZ (G5 PTZ) | ON | "Default", full frame [[0,0],[1,0],[1,1],[0,1]] | 50 |
| Rear PTZ (G5 PTZ) | ON | full frame | 50 |
| Utilities PTZ (G5 PTZ) | ON | full frame | 50 |
| G5 Bullet | ON (person+animal) | full frame | 50 |
| Back Yard / Hot tub | ON | full frame | 50 |

**Needs Protect UI (per-camera, optional):** raising sensitivity one step (50 → 60) on the seam cameras — the slider exists (`smartDetectZones[].sensitivity` in bootstrap) but no available tool writes it. Everything else (person ON, full-frame zones) is already in the recall-leaning state.

**Stale-data note resolved:** the audit's "Protect data ends 2026-07-25" was MCP session-cache lag (stale in-memory bootstrap), not a controller problem. The Protect REST events API returned events from 2026-08-06 12:11Z, and a fresh bootstrap read shows `recordingEnd` ≈ 2026-08-06 12:21Z on all seam cameras. Config-shaped facts from the audit remain valid.

### Follow-up

Re-run the adjacency probe's transition mining after ~1 week under the new settings to measure middle-camera fire rate on the ratified chain hops (measure, don't soak-watch).

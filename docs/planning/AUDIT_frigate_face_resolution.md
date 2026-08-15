# AUDIT — Frigate-2 face-recognition vs official docs

**Date:** 2026-08-15
**Author:** Oji Udezue
**Scope:** Explain why the F2 face bank is well-populated (many Oji/Ziri/etc. trained this morning) yet recognition barely fires — Frigate recognized Oji once, Ziri never; ~6 of 9 people cameras emit only boot churn; family-room face is dead while UniFi Protect recognizes faces on the *same* physical camera.
**Access note / provenance:** The F2 API at `https://192.168.13.18:8971/api/config` returned **401** (no credentials available to this session; credential stores are off-limits). The audit is therefore built from the **config-of-record artifact on HA**: `/config/www/frigate.yml`, produced by the "Frigate Config Builder" integration (573 lines, 23 cameras). This is READ-ONLY analysis; nothing was modified. Config values below are quoted from that file. Official-docs comparison is against <https://docs.frigate.video/configuration/face_recognition>.

### ⚠️ Live-vs-generated caveat (read before acting)
Two independent signals say the **generated file may not byte-match the live F2**, so treat resolutions as *strongly corroborated but verify on live before large edits*:
1. The generated file declares `detectors: default: edgetpu (usb coral)`, but live HA telemetry shows **OpenVINO detectors running** (`sensor.frigate_ov_inference_speed` ≈ 14–18 ms, `sensor.frigate_detection_fps_2` = 156 fps). Live F2 is running an **iGPU/OpenVINO** detector, not (only) the Coral in the file.
2. `sensor.frigate_config_builder_frigate_status` = **disconnected** (points at `192.168.13.16:8971`, not the real F2 at `.18`) and `binary_sensor.frigate_config_builder_config_stale` = **on**. So the builder is **not currently pushing** to live F2.

**Corroboration that the resolutions ARE live-accurate:** the operator independently reported family-room detect at **640×480**; the generated file shows `family_room` detect = **640×480** exactly. That match is strong evidence the per-camera detect geometry in this file reflects live F2. The detector-type mismatch (Coral vs OpenVINO) matters only for the "can we run the large model" recommendation — and the answer there is **yes, live F2 has a GPU**.

---

## 1. Per-camera detect stream — resolution vs docs guidance

Global default: `detect: width 640, height 360, fps 5`. Every camera's `detect` role is bound to the camera's **low sub-stream** (Ubiquiti `rtsps://…` secondary channel), NOT the high/primary stream (which carries `record`).

Docs guidance: *"Face recognition does NOT run on the recording stream"* — it runs on the **detect** stream. *"ensure detect stream resolution … is sufficiently high enough to capture face details on `person` objects"* and check the camera's **DORI recognition range**. No hard pixel minimum is published, but `min_area` defaults to **500 px²** (≈ 22×22) and the community-practical floor for reliable recognition is a face **~60–80 px wide**. On a 640×360 wide room view a standing person's face is typically **15–35 px wide** → ~200–1200 px² — at or below `min_area` and far below what the small model needs at `recognition_threshold 0.9`.

| Camera | detect W×H | fps | face-viable per docs? |
|---|---|---|---|
| armcrestpooloverhead_armcrestint | 640×360 | 5 | ✗ (overhead + low res; also currently unavailable) |
| back_yard | 640×360 | 5 | ✗ outdoor/distance |
| staircase | 640×360 | 5 | △ only at close pass |
| **family_room** | **640×480** | 5 | △ best of the wide rooms, still the camera's LOW leg — face still small across the room |
| foyer_fisheye | 640×640 | 5 | △ fisheye distortion hurts recognition even at 640² |
| front_door_aerial | 640×360 | 5 | ✗ aerial angle |
| front_side_ptz | 640×360 | 5 | ✗ wide PTZ |
| g5_bullet | 640×360 | 5 | ✗ |
| garage_a | 640×360 | 5 | ✗ |
| garage_b | 640×360 | 5 | ✗ |
| **doorbell_lite** | **640×853** | 5 | ✓ close-range portrait framing — the one geometry that reliably yields a large frontal face |
| hot_tub | 640×360 | 5 | ✗ |
| madrone_g6_entry | 352×480 | 5 | △ portrait but low width |
| madrone_g6_entry_package | 400×300 | 5 | ✗ package-zoom, very low res |
| master_hallway | 640×360 | 5 | △ close pass only |
| playroom | 640×360 | 5 | △ |
| pool_equipment | 640×360 | 5 | ✗ |
| ptz reolink …_ptz | 640×360 | 5 | ✗ (`_sub` stream) |
| ptz reolink …_wide | 640×360 | 5 | ✗ (`_sub` stream) |
| rear_ptz | 640×360 | 5 | ✗ |
| stairs_top | 640×360 | 5 | △ |
| upstairs_hall | 640×360 | 5 | △ |
| utilities_ptz | 640×360 | 5 | ✗ |

**Pattern that explains the symptom:** the only cameras with a chance of clearing the small-model / 0.9 bar are the ones with a **taller, closer-framed detect stream** — `doorbell_lite` (640×853), `foyer_fisheye` (640×640), `family_room` (640×480). Everything else is a 640×360 wide view where faces never reach recognizable size. That is exactly "3–4 cameras fire, the rest emit only person/boot churn." The face bank being well-populated is irrelevant — a rich embedding library can't match a **20-px crop**.

**Family-room "dead while Protect works" (collateral #4):** Frigate detects family_room on the **640×480 Low leg** of the AI Theta (which also publishes 1280×960 Medium and 3264×2448 High). UniFi Protect runs its own recognition on the **full-res** stream, so it recognizes the same faces Frigate cannot. This is not a Frigate bug — it is Frigate being fed the camera's lowest-resolution leg.

---

## 2. `face_recognition` config block vs docs defaults

Live file:
```yaml
face_recognition:
  enabled: true
  model_size: small
```
Nothing else set → these docs defaults apply: `detection_threshold: 0.7`, `recognition_threshold: 0.9`, `min_area: 500`, `unknown_score: 0.8`. No per-camera `face_recognition:` overrides; no `objects:` block anywhere (so tracked objects = default `person`, which is correct — face needs a `person` first).

Deviations / concerns vs docs:
- **`model_size: small`** — docs: small is "optimized for efficiency and **not as accurate**"; large is "optimized for accuracy" and needs a GPU/NPU. **Live F2 HAS a GPU** (OpenVINO detectors active). Running `small` on GPU hardware is leaving the accuracy on the table — the single highest-leverage one-line change *after* resolution.
- **`recognition_threshold: 0.9` (default, unset)** — very strict; combined with the less-accurate small model **and** tiny face crops, almost nothing clears it. This is why Oji matched *once* (a lucky large frontal crop) and Ziri *never*.
- **`min_area: 500` (default, unset)** — fine in principle, but on 640×360 many real faces fall *under* it and are dropped before recognition even runs.
- **No per-camera enablement** — face runs on all 23 cameras including outdoor/overhead/PTZ where it can never succeed. Not harmful to recognition, but it's the source of the "boot churn only" noise on the 6+ cameras that will never produce a face.

---

## 3. Pipeline dependencies / why 6-of-9 never attempt face

- **Semantic search:** enabled (`semantic_search: {enabled: true, model_size: small}`). Per docs, face recognition is **independent** of semantic search — so that's not gating anything (fine to leave on).
- **Detector / GPU:** face detection (finding the face box before recognition) runs via a CPU DNN unless a Frigate+ native-face model is used; there is **no `face` in any `objects` list** and no Frigate+ model, so Frigate uses the built-in CPU face detector automatically. That path works; it is **not** the blocker.
- **Real reason 6-of-9 "never attempt face":** it's not that face is disabled per-camera — it's that **face detection needs a person crop big enough to contain a detectable face**, and on 640×360 wide views the person's face box never reaches the detector's minimum. Person is detected (motion/boot churn), face is never found → no recognition attempt is logged. The 3–4 that "attempt" are the taller/closer geometries in §1.
- No camera has `detect: enabled: false`; all 23 have detect on. So the split is **resolution/geometry-driven**, not an enable flag.

---

## 4. The low-res-leg collateral (confirmed)

`family_room` (AI Theta) detect input is the camera's low sub-stream at **640×480**, while the same camera publishes 1280×960 (Medium) and 3264×2448 (High). Frigate recognizing on the 640×480 leg — while Protect uses the High leg — is sufficient on its own to explain family-room's dead face pipeline vs Protect's working one. The same low-leg binding applies to **every** UniFi camera in the file (detect always bound to the secondary `rtsps` GUID, record to the primary).

---

## Ranked deltas (by likely impact on recognition)

1. **[CRITICAL] Detect streams are the low sub-stream (≈640×360/480).** Root cause. Faces are physically too small to recognize on almost every camera. Nothing else matters until this is fixed on the people-cameras.
2. **[HIGH] `model_size: small` on GPU hardware.** Live F2 runs OpenVINO/iGPU; the large model would materially raise match rate and costs one line. (Verify GPU headroom, but 156 fps detection + 14–18 ms inference says there's room.)
3. **[HIGH] `recognition_threshold` left at the strict 0.9 default** with a small model + tiny crops → near-zero matches. Lower once resolution is fixed (and/or when moving to large model).
4. **[MEDIUM] Face runs on all 23 cameras** including outdoor/overhead/PTZ that can never succeed → log churn and wasted CPU face-detect. Scope face to the people-transit cameras.
5. **[MEDIUM] `min_area: 500` default** drops sub-500px² faces before recognition — will still bite on any camera left at 640×360.
6. **[LOW/INFO] Config drift:** builder disconnected + stale, points at `.16` not `.18`, declares Coral while live runs OpenVINO. Reconcile the builder→live path or the next "Push to Frigate" will overwrite live with a Coral config.

---

## Recommended Frigate config changes (for operator / homelab agent to apply — NOT applied here)

Apply on live F2 (`192.168.13.18`), or fix the builder's target first (§6) and regenerate. Prioritize the indoor people-transit cameras.

**A. Repoint detect to a higher-res sub-stream (biggest win).** For each people-camera, bind the `detect` role to the camera's **Medium** leg instead of Low. Targets: `family_room`, `foyer_fisheye`, `master_hallway`, `staircase`, `stairs_top`, `upstairs_hall`, `playroom`, `madrone_g6_entry`, `doorbell_lite`. Aim for **≥1280×720** detect (family-room AI Theta: use the **1280×960 Medium** RTSP leg). Keep fps at 5 — resolution, not frame rate, is the lever. Example shape:
```yaml
family_room:
  detect:
    width: 1280
    height: 960   # AI Theta Medium leg (was 640x480 Low)
    fps: 5
  # ffmpeg.inputs: point the `detect` role at the 1280x960 RTSP GUID, not the 640-wide one
```
(Watch total detector load as detect pixels rise; the iGPU has headroom but stagger the rollout camera-by-camera and watch `sensor.frigate_detection_fps_2`.)

**B. Use the large face model (GPU is present).**
```yaml
face_recognition:
  enabled: true
  model_size: large        # was small; live F2 has an OpenVINO GPU
  recognition_threshold: 0.8   # relax from the 0.9 default once crops are larger
  detection_threshold: 0.7     # keep default
```

**C. (REVISED per operator ruling 2026-08-15: "No — we're looking at recognizing known persons in the exterior.")** Exterior recognition is the PRODUCT (the known-person annotation cycle targets perimeter/egress alerts), so face stays ENABLED on exterior people-cameras — the fix for them is the SAME as A: repoint their `detect` to the highest leg the hardware affords (medium/high sub-stream), because exterior approach shots at entry distance are exactly where "likely Oji" pays. Rec A's stream-repoint therefore applies to perimeter/egress cameras FIRST-CLASS, not just indoor. Disable face ONLY on structurally-hopeless geometries where no available stream can yield a recognizable face at any plausible subject distance — overhead/roofline views (`front_door_aerial`, `armcrestpooloverhead_*`) and non-people utility views (`pool_equipment`, `utilities_ptz`). Keep enabled: `back_yard`, `hot_tub`, `garage_*`, entry PTZs (parked positions frame approaches). Churn on a viable camera is acceptable cost; a disabled viable camera is a lost recognition.

**D. After A/B/C, tune `min_area` / `recognition_threshold` empirically** from the F2 UI's face "train/attempts" view — raise `min_area` only if you see false small-face matches; lower `recognition_threshold` further toward ~0.75 if genuine faces still miss. Do this last, once crops are large.

**E. Reconcile the builder (§6):** either point `sensor.frigate_config_builder` at the live F2 (`192.168.13.18:8971`) and set the detector to `openvino` to match live, or stop using "Push to Frigate" so it can't clobber the live GPU/large-model config with the stale Coral/small one.

**Expected effect:** A alone should revive family-room and the hallway/stair cameras (bigger crops clear detection + recognition). A+B together (applied to interior AND exterior people-cameras) should move recognition from "Oji once, Ziri never" to routine per-pass matches indoors and at exterior approach distance; C (revised) trims only the structurally-hopeless overhead/utility views.

**Verification after apply:** watch the F2 face events / `sensor.frigate_<person>_last_camera_2` entities populate on indoor passes; confirm `sensor.frigate_detection_fps_2` stays healthy (didn't collapse under higher detect res). Re-fetch `/api/config` once credentials are available to confirm live matches intent.

# v5.46.0 — Fan-Transition Coincidence Gate + Study A Camera-Bench Fixes

## 1. Fan-transition coincidence gate (Tier 2-DB, probe-gated)
The recorder probe (`AUDIT_fan_signature_separability_probe.md`) found both
labeled mmWave phantom events began at the **exact second** of a fan power/speed
transition, while steady-state fans produced multi-hour negatives. This cycle
ships the prevention leg of the three-mechanism stack:

- **Creation-only suppression**: a would-be occupancy CREATION whose only
  evidence is mmWave (`presence_detected` and no PIR/occupancy) is suppressed
  when the edge lands within `FAN_TRANSITION_SUSPECT_WINDOW_S = 5.0` s of a fan
  transition in that room (rung-1 module constant; `0.0` = kill switch).
- Stamps ride the existing `_handle_fan_change` listener (state edge OR
  percentage change; no stamp on malformed states, no new listeners); cleared
  on fan re-discovery; newest-stamp-wins across trackers.
- Never releases existing occupancy; never touches PIR/BLE/camera-backed
  creation; preserves an in-progress entry-debounce clock when it fires (B1).
- Complementarity: fan_veto = actuation guard, D2 demotion = sustain
  correction, this gate = creation prevention. Same-tick event-ordering race
  (stamp after read) deliberately deferred to D2 — documented in-code.
- Observability: `fan_transition_suppressed_count` attr on
  `binary_sensor.<room>_occupied`; DEBUG line per suppression with Δt;
  WARNING one-shot if the gate itself errors.

Review: `docs/reviews/code-review/fan_transition_gate_tier2db.md` — 3
framing-disjoint reviews; 1 HIGH (debounce-clock reset side effect) + 3 MED
fixed; orchestrator drills red-verified on the suppression line AND the B1
preservation guard. 19 gate tests incl. subprocess mutation drill and a
reachability source-scan guard.

## 2. Study A camera-bench fixes (first-contact findings)
Configuring the first `room_cameras` room surfaced two real correlation bugs:
- **fan_veto fused-sensor lookup**: the fused entity id is device-name-derived
  (`binary_sensor.studya_room_device_camera_person_detected`), so the old
  slugify guess (`study_a_...`) missed. Now resolved via entity-registry
  unique_id (`<entry_id>_camera_person_detected`), slugify fallback retained.
- **`_N` disambiguation suffix**: `camera.armcrestash41b_2` failed the Frigate
  name-stem match against object `armcrestash41b`. Rung-5 now also tries a
  disambiguation-suffix-stripped stem.

## 3. Probe doc correction
The still_energy corroborator is NOT blocked: the live fleet is ESPHome/Screek
(`jaya_3`, `ziri_3`, kitchen, studyb + 2× LD2412S) streaming in 6 rooms; only
the four redundant Bluetooth LD2410 dongles are disabled (operator BLE-budget
call — leave off).

## Suite
Full suite 7919 passed / 34 failed = pre-existing develop baseline, zero drift.
(Baseline moved 32→34: two order-dependent `test_energy_restart_resilience`
BillingRestoreDaily failures that pass in isolation — pollution class, tracked.)

## Live Validation — prospective
- **Live:** clean boot, zero URA ERRORs; no WARNING from the fan-transition
  gate error latch.
- **Live:** `fan_transition_suppressed_count` attr present (0) on occupied
  sensors of fan-equipped rooms.
- **Live:** first organic suppression: DEBUG line with Δt ≤ 5 s during a fan
  speed change in a vacant room, counter increments, room stays vacant, NO
  subsequent D2 demotion needed for that event.
- **Live:** no missed real entries: a person entering a fan-room is detected
  normally (PIR/BLE co-fire admits; worst case mmWave-sole coincident entry
  delayed ≤5 s with debounce clock preserved — accepted A1 trade).
- **Live:** Study A fused camera sensor leaves `no_sources` once resolver
  re-runs with the `_N`-strip fix (attribution attrs populate for
  armcrestash41b / G3 Instant).

### Validated 2026-08-01 (~20:40 CDT, first post-deploy boot)
| Criterion | Result | Evidence |
|---|---|---|
| Clean boot, zero URA ERRORs | **PASS** | journald scan: only unrelated lepro_led/wiim errors; zero URA ERROR lines; no fan-gate WARNING (error latch silent). |
| `fan_transition_suppressed_count` attr present | **PASS** | `binary_sensor.study_a_occupied` carries `fan_transition_suppressed_count: 0` post-boot. |
| First organic suppression | pending-organic | Needs a fan transition in a vacant mmWave room; watch DEBUG line + counter. |
| No missed real entries | pending-organic | Standing watch; PIR/BLE co-fire admits normally by design + tests. |
| Study A fused sensor leaves `no_sources` | **PASS-after-reload / BUG FOUND** | Post-boot it stayed `no_sources` (boot-order cache poisoning — see below). After a targeted Study A entry reload: `agreement: single_source`, `confidence: medium`, armcrestash41b resolved via `name_stem` (the `_N`-strip fix working live). G3 Instant correctly contributes no person source (motion-only hardware). |

**Defect found during validation (fixed in v5.46.1):** `CameraPersonDetectedSensor._get_fusion` caches an EMPTY resolution (`_fusions = []` is `not None`) computed while camera integrations are still loading at boot, and `_subscribe_sources` returns without any subscriptions — so the fused sensor and the fan-veto camera leg are inert after every restart until a manual entry reload. Failure direction is conservative (no camera evidence → veto holds), but the surface is dead each boot.

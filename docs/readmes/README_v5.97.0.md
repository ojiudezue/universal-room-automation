# v5.97.0 — Frigate real-time face-NAME bridge (names reach the resolver)

**Card:** FRIGATE-SUBLABEL-FACE-BRIDGE-1 (task #11). Step 4 of the identity sequence; completes the face side of the 6.0.0 producer. **Tier:** 2 → escalated in practice: prior-art-scanned plan + 1 plan-review (4 blocking, fixed) + 3 framing-disjoint build reviews (1 CRITICAL + 3 HIGH) + consolidated fix-up + adversarial re-review (must-fix) + final fix-up + orchestrator independent mutation-verify.

## Problem
Frigate recognizes resident faces in real time, but the name never reached a URA-joinable entity: the HA Frigate integration writes the name to `sensor.<cam>_last_recognized_face_2` then `async_call_later(60s)` resets it, so URA's point-poll resolver landed on `None` almost always. (Corrected premise: the name is top-level `name` on MQTT `frigate/tracked_object_update` where `type=="face"` — NOT `sub_label` on `frigate/events`, as the card and an earlier probe had it; caught by a source-read.)

## Solution — URA subscribes to the bus, owns the retention
URA subscribes to `frigate/tracked_object_update`, filters `type=="face"`, maps the Frigate camname→URA face-sensor base_stem (registry-anchored via `CameraResolver._frigate_stem_to_device_ids` — never string-built), and stores `(name, ts)` in a URA-owned latch (`FACE_NAME_LATCH_TTL_S`, URA-controlled, not Frigate's 60s reset). `_resolve_face_legs` emits a **synthetic FaceLeg** from the latch — additive to the existing entity point-read — so a name present on the bus within the crossing window is no longer lost.

Safety/correctness (all review-hardened):
- **Fail-safe inherited:** the synthetic leg rides the same `all_legs` the caller drops under drill/producer-outage (`transit_validator.py:1264-1276`) — the v5.95.x drill still suppresses it (verified end-to-end, RED-on-neuter).
- **No boot-stranding:** `mqtt` is NOT an `after_dependencies` (that would reintroduce the 2026-06-12 Envoy P0); late-loading MQTT is recovered via `async_when_setup`, guarded against a torn-down census.
- **Key-namespace normalized:** write key == read `base_name` for every camera shape (`garage_a_2`→`garage_a`, `foyer_fisheye`→`foyer_fisheye`) — the bridge is NOT inert for garage_a.
- **Sentinel filter:** Frigate's first-class `"unknown"` face label never becomes a `person_id`.
- **Dedup, not corroborate:** a latch leg + the same-camera entity leg collapse to one (no false CONFIDENCE_HIGH); a stale latch never pushes a resolvable crossing to DISAGREE (live entity wins).
- **Single-stem, topic-collision guarded, memoized lookup** (no per-message registry scan).

## Reviews
Plan-review caught 4 unbuildable seam citations (synthetic-leg vs tuple, caller-side suppression, the real camname map, MQTT coroutine/dep). Build reviews A/B/D caught a boot-stranding CRITICAL, a silently-inert-for-garage_a key HIGH, and a `"unknown"`-as-person_id HIGH. Fix-up + re-review + final fix-up closed all + the orphan-subscription must-fix. Orchestrator independently mutation-verified the key-normalization, the sentinel drop, and the end-to-end drill (each RED-on-neuter). 13 bridge tests + 33 fusion tests; zero net-new suite regressions.

### Acceptance criteria
- **Verify:** a `type==face` msg for garage_a/front_door latches under the correct base_stem and `_resolve_face_legs` emits a synthetic leg within the crossing window; a `"unknown"` name never latches; a drill suppresses the synthetic leg.
- **Test:** the anchors above, each RED-on-neuter.
- **Live:** a recognized face at a door/garage cam corroborates or attaches identity to an egress crossing; `frigate_face_msg_face_count` + `frigate_face_latch_size` move; the drill still suppresses.

## Non-goals / deferred
Face SCORE confidence gate (deferred — no score field confirmed on the wire; card if a daytime capture shows one). Exit-specific face (BLE backfill handles exit). F1/F2 host-disambiguation (F1 retired).

## Live Validation — post-restart (to record as `Validated <date>`)
- `frigate_face_msg_face_count` climbs when a resident is recognized on a door/garage cam; `frigate_face_latch_size` non-zero.
- A recognized face within a crossing window corroborates/attaches identity.
- The fail-safe drill suppresses the synthetic leg.

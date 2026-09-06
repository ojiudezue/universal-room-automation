# PLANNING — Frigate real-time face-NAME bridge (D1)

**Card:** FRIGATE-SUBLABEL-FACE-BRIDGE-1 (task #11). **Tier:** 2 (feeds the identity producer — regression-prone; but additive + behind the existing face path). Step 4 of the identity sequence.

## Institutional context verified (prior-art scan — mandatory Tier-2+ rule)
- **`AUDIT_egress_face_identity_prior_art.md` (2026-08-18)** — the seam map: `EgressDirectionTracker` leaves `person_id=None` (transit_validator.py:1106/1121); the resolver `_resolve_face_legs` + `_resolve_face_entity_id` (camera_census.py:2842) read `sensor.<base>_last_recognized_face[_2]`; consumers of `ura_person_egress_event`. REUSE this map — do NOT re-survey the seams or add a parallel writer (§D collision warning).
- **FRIGATE-SUBLABEL card `live_correction_2026_09_06`** — CORRECTED field/topic (this supersedes the card's original sub_label premise AND the earlier session probe): the real-time face NAME is **top-level `name` on MQTT `frigate/tracked_object_update` where `type=="face"` and `camera==<cam>`**. NOT `sub_label` on `frigate/events` (that's Frigate's classification path). Source: the HA Frigate integration `FrigateRecognizedFaceSensor` (`/config/custom_components/frigate/sensor.py:1082-1113`) — it latches `name` real-time then `async_call_later(60s)` resets to "None" (the latch-reset bug URA's point-poll resolver loses to).
- **No existing `mqtt.async_subscribe` in the component** → the subscription is NEW (justified); reuse `homeassistant.components.mqtt.async_subscribe` (standard HA API).
- **REUSE:** `_resolve_face_entity_id` / camera_manager `get_all_frigate_cameras` for camname↔slug (the `_2` suffix is permanent — resolve via registry, never string-build; memory `frigate1 retired 2 suffix`). Guard the **Frigate 1/2 shared-topic-prefix collision** (memory `frigate mqtt collision`) — filter on the known frigate camera set, not every message on the shared topic.
- **Live evidence (2026-09-05):** garage_a (Jaya ×4), front_door_aerial (Jaya), rear_ptz, interior cams all emitted real names; real-time; door/garage INCLUDED.

## D0 — confirm the wire payload (measure-before-build gate)
The field names are from the consumer SOURCE (authoritative), but no live `frigate/tracked_object_update` face payload was captured (late-night lull). Before/at build, run a daytime `ssh ha "mosquitto_sub -h core-mosquitto -u homeassistant -P <pw> -t 'frigate/tracked_object_update' -v -W 300"` during foot traffic to confirm: (a) the `type`/`camera`/`name` triplet on the wire (and whether it's top-level vs nested under `after.`), (b) whether a face **score** field is present (for an optional confidence gate). This is a 5-min run; it gates the exact payload-parsing in D1.

## Falsifiable invariant
> A face-name latch entry for URA camera C is created iff a `frigate/tracked_object_update` message arrives with `type=="face"` and a `camera` that resolves (via registry) to C, carrying a non-empty `name`; the latch retains `(name, ts)` for `FACE_NAME_LATCH_TTL_S` (URA-controlled, ≥ the egress face-match window), independent of Frigate's 60s entity reset; and `_resolve_face_legs` reads the URA latch so a name present on the bus within the match window is never lost to the entity's reset. No message on the shared topic from a non-URA / non-face / unknown-camera source creates a latch entry.

## D1 — MQTT subscriber + URA-owned name latch (camera_census)
- On setup, `mqtt.async_subscribe("frigate/tracked_object_update", cb)`; register the unsub for teardown (reuse the existing unsub-tracking discipline; unload-only cancel).
- `cb`: parse the payload (per D0 wire shape); require `type=="face"`, non-empty `name`, and `camera` in the known frigate-camera set (collision guard). Map Frigate camname (`garageA`) → URA base/slug via camera_manager/registry (NOT string-built). Store `self._frigate_face_latch[urakey] = (name, dt_util.utcnow())`. Prune entries older than `FACE_NAME_LATCH_TTL_S`.
- `FACE_NAME_LATCH_TTL_S` (const, module rung) = the egress face-match window (reuse the existing FACE_MATCH_* value; comment the relation).
- Fail-safe: malformed/foreign messages ignored + counted (`_frigate_face_msg_dropped_count`); a dead MQTT/unavailable broker leaves the latch empty (resolver falls back to today's point-read — no regression).

## D2 — `_resolve_face_legs` reads the URA latch
Extend the face-leg read (camera_census.py ~`_resolve_face_legs` / `_get_face_recognized_persons`): for each camera, prefer the URA latch `(name, ts)` if within the match window, else fall back to the existing `_resolve_face_entity_id` point-read (so behaviour is strictly additive — the latch can only ADD names the point-read missed, never remove a working read). Respect the existing D2b kill-switch / `_face_suppressed_now()` fail-safe (the latch is a face-provenance source → it MUST route through `_face_suppressed_now`, same as the entity read, so the producer-outage/drill fail-safe still suppresses it).

## D3 — observability
Surface `frigate_face_latch_size`, `frigate_face_msg_seen_count`, `frigate_face_msg_dropped_count`, and last-latched `(cam, name, age)` on the persons-in-house sensor. This is the discriminator that the bridge is actually receiving names.

## Non-goals
Face SCORE confidence gate (only if D0 shows a score field — else defer). Changing the entity/Frigate side. Exit-specific face (the exit backfill is BLE; face corroboration flows through the same resolver once the latch feeds it).

## Tier-2 review framings
- A correctness: payload parse + camname→slug mapping + latch TTL + additive read (never removes a working point-read).
- B integration/lifecycle: MQTT subscribe/unsub teardown, no leak, collision-guard on the shared topic, `_face_suppressed_now` routing (fail-safe still governs the latch), no regression to the point-read path.
- (C test-authority mutation on: type!=face rejected, unknown-camera rejected, latch TTL prune, additive-read fallback, fail-safe suppression of the latch.)

## Acceptance criteria
- **D0:** live wire capture confirms the `type/camera/name` triplet (+ score presence).
- **Test:** the invariant anchors, each RED-on-neuter.
- **Live:** a real recognized face at garage_a/front_door lands in the URA latch and (within the window of an egress crossing) corroborates/attaches via `_resolve_face_legs` — observable as `frigate_face_msg_seen_count` rising and a face-provenance attach appearing; the fail-safe drill still suppresses the latch.

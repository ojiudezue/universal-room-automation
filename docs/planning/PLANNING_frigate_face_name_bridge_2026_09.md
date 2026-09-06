# PLANNING — Frigate real-time face-NAME bridge (D1) — rev 2

**Card:** FRIGATE-SUBLABEL-FACE-BRIDGE-1 (task #11). **Tier:** 2 (feeds the identity producer; additive behind the existing face path). Step 4 of the identity sequence.
**Rev 2:** applies plan-review (4 blocking + should-fix) — corrected the face-read seam (synthetic FaceLeg, not a tuple; not `_resolve_face_entity_id`), the suppression mechanism (caller-side), the camname→slug prior art, the MQTT dependency/coroutine, and the TTL derivation.

## Institutional context verified (prior-art scan)
- **`AUDIT_egress_face_identity_prior_art.md`** — seam map (EgressDirectionTracker person_id=None gap; the resolver; consumers). REUSE; no parallel writer.
- **FRIGATE-SUBLABEL card `live_correction_2026_09_06`** — face name = top-level `name` on `frigate/tracked_object_update` where `type=="face"`, `camera==<cam>` (NOT `sub_label`/`frigate/events`). Frigate integration `FrigateRecognizedFaceSensor` latches then `async_call_later(60s)` resets — the latch-reset bug. Real-time, no backfill.
- **Face-read seam (CORRECTED):** `_resolve_face_legs` (camera_census.py:2885-3002) enumerates 4 candidate entity_ids INLINE (`:2915-2918`) and builds frozen `FaceLeg` dataclasses (`FaceLeg` at camera_census.py:205-221: `entity_id, engine, device_id, base_stem, canonical_slug, last_changed, confidence`). It does NOT call `_resolve_face_entity_id`. Suppression is applied by the CALLER `transit_validator.py:1356-1370` (recomputes strict/face_live, drops ALL legs) — a synthetic leg inherits the fail-safe automatically.
- **camname→slug (CORRECTED prior art):** `CameraResolver._frigate_stem_to_device_ids` (camera_resolver.py:460, built :508-519 from device identifiers `("frigate","<host>:<name>")`) + `_compute_device_stems` (:1299) / `_frigate_object_name_for_device` (:1287); reached via `self._camera_manager._get_resolver()` (the pattern `_resolve_face_legs` already uses at camera_census.py:2921-2925). NOTE: `:518`/`:1295` `rsplit(":",1)[-1]` DISCARD the host — so F1/F2 host-disambiguation is NOT available from this index; guard = "camname ∈ known frigate camera set" only (acceptable: F1 retired, memory `frigate1 retired 2 suffix`).
- **MQTT:** manifest.json `dependencies:["http","frontend","logbook"]` — NO mqtt; zero `mqtt.async_subscribe` in the component (net-new). `mqtt.async_subscribe` is a COROUTINE returning the unsub (the BLE precedent `async_track_state_change_event` is sync — do NOT copy its shape).
- **TTL prior art:** the BLE-transition cache TTL derivation at const.py:2296-2306 (max-of-windows + margin) — reuse the pattern.
- **DO-NOT-TOUCH fences:** `_resolve_face_entity_id` (frozen per the EGRESS-IDENTITY-JOIN-GAP-1 B-HIGH-1 revert comment, camera_census.py:2856-2864 — widening it feeds 4 ungated surfaces incl presence pre-arrival presence.py:4633); `_get_face_recognized_persons` (:3153) and especially `_get_face_recognized_persons_fresh` (:3178, UNGATED — no `_face_suppressed_now`). The latch feeds `_resolve_face_legs` ONLY.

## Falsifiable invariant
> A synthetic face `FaceLeg` for URA camera C is produced by `_resolve_face_legs` iff a `frigate/tracked_object_update` (`type=="face"`, `camera`→C via the resolver, non-empty `name`) was received within `FACE_NAME_LATCH_TTL_S`; the latch entry is pruned after the TTL; the synthetic leg carries the SAME `engine` tag as C's Frigate entity leg so the two DEDUP (never corroborate as two engines); and the synthetic leg is dropped under the drill / producer-outage fail-safe exactly like an entity leg (because the caller drops all legs). No message from a non-face / unknown-camera / non-URA source produces a leg.

## D0 — NON-BLOCKING confirm (NOT a gate — the source-read is authoritative)
The gate is phantom: `FrigateRecognizedFaceSensor`'s callback parses the SAME topic payload URA will receive as top-level `data.get("type")` / `data["name"]`, so field names AND top-level nesting are settled by the code that parses the wire. A daytime `mosquitto_sub` only CONFIRMS it; it does not block. The one genuinely-open item — a `score` field — is an optional confidence-gate enhancement, NOT a correctness requirement (the synthetic leg with `confidence=None` already flows through the classifier + fail-safe). → **BUILD NOW on the source-read; card the score-gate as a follow-up if a later capture shows a usable score.** If the running capture returns a payload, fold the nesting/score into the parser opportunistically.

## D1 — MQTT subscriber + URA-owned latch (camera_census + manifest + __init__)
- **manifest.json:** add `"after_dependencies": ["mqtt"]` (SOFT — URA must still load on an MQTT-less install).
- **Subscribe (coroutine):** an async `async_register_frigate_face_listener()` on PersonCensus that does `unsub = await mqtt.async_subscribe(hass, "frigate/tracked_object_update", cb)`, wrapped in try/except (log + leave bridge inert if MQTT unloaded/raises). Store `unsub`. Wire-in at `__init__.py:2247` (adjacent to `census._register_ble_transition_listeners()` inside async_setup_entry — but this is async, so it can be awaited there); teardown at `__init__.py:4920-4932` (unload-only), mirroring `async_teardown_ble_transition_listeners`.
- **`cb(msg)`:** parse JSON (per D0 nesting); require `type=="face"`, non-empty `name`, `camera` ∈ known frigate set (collision guard). Map Frigate camname→URA base_stem via `self._camera_manager._get_resolver()._frigate_stem_to_device_ids` + `_compute_device_stems` (NOT string-built). Store `self._frigate_face_latch[base_stem] = (name, dt_util.utcnow())`. Prune entries older than `FACE_NAME_LATCH_TTL_S`. Malformed/foreign → `_frigate_face_msg_dropped_count += 1`.
- **`FACE_NAME_LATCH_TTL_S`** (const, module rung) = `max(FACE_MATCH_EXIT_BEFORE, FACE_MATCH_EXIT_AFTER, FACE_MATCH_ENTRY_BEFORE, FACE_MATCH_ENTRY_AFTER) + margin` (≥300), reusing the const.py:2296-2306 derivation pattern. Invariant: TTL ⊇ the classifier's signed-lag window so a prune never truncates a name the classifier still wants.

## D2 — `_resolve_face_legs` emits a synthetic FaceLeg from the latch (additive, at :3001)
After the candidate loop closes, before `return results` (camera_census.py:3001), inside the same try: for each camera C in scope, if `self._frigate_face_latch` has a fresh `(name, ts)` (age ≤ TTL) for C's base_stem:
- resolve C's Frigate entity leg engine tag (the SAME `engine` value the entity-read legs use for that camera) so the synthetic leg dedups with, not corroborates, the entity leg.
- build `FaceLeg(entity_id=<the resolved _2 face entity or a sentinel>, engine=<same frigate engine>, device_id=<C's>, base_stem=C, canonical_slug=self._canonical_person_slug(name), last_changed=ts, confidence=None)` (confidence None passes the FACE_MATCH_MIN_CONFIDENCE floor, camera_census.py:2949; `last_changed=ts` is REQUIRED — the classifier keys off `leg.last_changed`, transit_validator.py:1345-1360, and a None there is silently skipped).
- **Dedup rule:** if `results` already has a leg with the same `(canonical_slug, engine, base_stem)`, keep the fresher `last_changed` (do NOT append a duplicate — a duplicate would double-count as agreement → spurious corroboration boost at transit_validator.py:1657). Else `results.append(synthetic)`.
- Suppression: NONE added here — the caller (transit_validator.py:1356-1370) drops all legs under drill/outage, so the synthetic leg is covered. (Do NOT add a redundant gate; do NOT touch `_resolve_face_entity_id` / `_get_face_recognized_persons*`.)

## D3 — observability
`frigate_face_latch_size`, `frigate_face_msg_seen_count`, `frigate_face_msg_dropped_count`, last-latched `(cam, name, age)` on the persons-in-house sensor.

## Non-goals / fences
- Do NOT modify `_resolve_face_entity_id`, `_get_face_recognized_persons`, `_get_face_recognized_persons_fresh` (frozen / ungated — fence per B-HIGH-1).
- No face SCORE gate unless D0 shows a score field.
- F1/F2 host-disambiguation out of scope (F1 retired; guard = known-camname-set).

## Tier-2 review framings
- A correctness: payload parse; camname→base_stem via the resolver chain (not string-built); synthetic FaceLeg fields (esp. last_changed=ts, engine=same-as-entity, confidence=None); dedup rule (no double-count).
- B integration/lifecycle: async subscribe/unsub teardown (unload-only), MQTT-unloaded try/except (bridge inert, point-read intact), collision guard, and the fences held (no widening of the frozen helpers; latch feeds `_resolve_face_legs` only).
- C test-authority mutation: type!=face rejected; unknown-camera rejected; TTL prune; synthetic leg dropped under drill (fail-safe); dedup collapses same-name latch+entity (no boost).

## Acceptance criteria
- **D0:** wire triplet confirmed (+ score presence).
- **Test:** invariant anchors RED-on-neuter, incl. the drill-suppression of a latch leg and the dedup-no-boost.
- **Live:** a recognized face at garage_a/front_door lands in the latch and corroborates/attaches via `_resolve_face_legs` within an egress crossing window; `frigate_face_msg_seen_count` rises; the drill still suppresses it; a working entity point-read is never regressed (latch only ADDS).

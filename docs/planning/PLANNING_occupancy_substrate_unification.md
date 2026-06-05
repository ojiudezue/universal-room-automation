# PLANNING — Occupancy substrate unification (shared raw per-room per-kind primitive across the room + zone tiers)

**Status:** Draft (planning). No version pre-stamped — assigned at deploy time per
operator convention.

**Companion plan:** `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md` (Plan A —
the Mode-2 BLE-gated fan pause + recheck that the operator wants to ship FIRST). This
substrate plan is the natural cleanup that lands NEXT and absorbs the cross-check shape
Plan A relies on.

**Tier vocabulary discipline (locked).** URA is a layered lattice: **ROOM tier**
(`coordinator.py` / `RoomCoordinator` / per-room config entry), **ZONE tier**
(`presence.py` / `ZonePresenceTracker`), **HOUSE tier** (`StateInferenceEngine`).
`coordinator.py` is the deliberate ROOM tier — it is **NOT "legacy"** and this plan
never calls it that. The substrate is a sensor-layer abstraction that sits BENEATH the
room + zone tiers; it is not a new tier and it does not replace one. Reviewers should
flag any drift toward "old/legacy/replaced-by" language about the room tier.

**One-line summary.** Stop having two tiers discover, classify, and trust different
sensor sets for the same room. Build a shared per-room, per-kind, instantaneous raw-signal
substrate sourced from the operator's curated `CONF_MOTION_SENSORS / CONF_MMWAVE_SENSORS /
CONF_OCCUPANCY_SENSORS` lists. Room tier and zone tier each apply their OWN temporal
smoothing on top of the same raw truth — preserving both tiers' legitimate, distinct
smoothing semantics while eliminating the discovery + classification divergence.

---

## Motivation (live-verified fragility)

Live divergence observed 2026-06-05 between room-tier `RoomCoordinator` and zone-tier
`ZonePresenceTracker` for the same room:

1. **Discovery divergence.** Room tier uses the operator's CURATED CONF lists
   (`CONF_MOTION_SENSORS`, `CONF_MMWAVE_SENSORS`, `CONF_OCCUPANCY_SENSORS` —
   `coordinator.py:1248-1250`). Zone tier does an entity-registry **area-sweep** every
   `binary_sensor` whose `entity_id` contains one of `("occupancy", "motion", "presence",
   "mmwave")` AND whose effective area_id (entity area_id, fallback to device area_id)
   matches the room (`presence.py:2168-2308`). Concrete cases:
   - **Jaya room.** Zone area-sweep registers 4 presence binary_sensors
     (`jaya_3_presence` ESP, `jaya_bedroom_bedroom_4_sensor_presence` ESP,
     `mmwave_zigbee_jayabedroom_presence` zigbee — fan-sensitive,
     `seeedstudio_mmwave_kit_047d34_presence_information` — currently unavailable).
     Operator's curated config lists 2. Zone trusts a SUPERSET of what the operator chose.
   - **Exercise room.** Zone sweeps 3 presence sensors vs the curated 2.
2. **area_id == null fragility.** All the listed presence binary_sensors have entity-level
   `area_id: null`, so the zone tier falls entirely back to the device-area lookup. An
   unset device area silently drops a sensor from the zone discovery, while the room tier
   (driven by the CONF list, area_id-agnostic) keeps it. Quiet divergence.
3. **Kind-classification divergence.** The Exercise hobeian device-class `occupancy`
   sensor is treated as MOTION by the room tier (observed `occupancy_source: motion` on
   the live entity) because it's listed in `CONF_MOTION_SENSORS`. The zone tier's
   `_classify_entity_kind` (`presence.py:226-281`) name-classifies the same entity using
   substring rules and may assign a different kind. Per-kind provenance between the two
   tiers therefore CANNOT agree by construction — they read the same world through
   different name-classification lenses.

The Plan A (Mode-2) cycle works AROUND this fragility by depending on the room-tier
`STATE_OCCUPANCY_SOURCE == "mmwave"` precondition (which is correct because it's driven
by the CONF list slot directly). Plan B is the durable fix: the two tiers should be
working from the SAME raw-signal truth at the per-room, per-kind, instantaneous layer,
and should each apply their own legitimate smoothing on top.

The zone tier's smoothing (raw_occupied, derived OR over per-kind provenance) is
intentionally DIFFERENT from the room tier's smoothing (timeout~900s, failsafe, camera +
BLE override). Both are legitimate. The substrate cycle preserves both — it ONLY unifies
the discovery + classification layer they BOTH sit on top of.

---

## Tier classification

**Tier 2-DB (three framing-disjoint reviews).**

Triggers:

1. **Touches the discovery path every Tier-1-presence consumer in the codebase depends
   on.** Switching the zone tier's source-of-truth from area-sweep to the CONF lists is a
   payload-shape change at the bottom of the trust hierarchy. Room tier already uses CONF
   lists; zone tier swap means the per-kind `_room_provenance` entries can change shape
   for some rooms (the Jaya/Exercise area-sweep superset drops). Any consumer of
   `provenance_for(room)` (`presence.py:535-561`) and the derived `_room_occupied`
   property (`presence.py:474-533`) sees the change.
2. **Cross-coordinator ripple — presence ↔ HVAC ↔ house_state ↔ compliance ↔ safety ↔
   guest-room detector.** Although HVAC reads the ROOM tier directly (so HVAC is largely
   isolated from the substrate change), the house tier's `StateInferenceEngine.infer()`
   (`presence.py:852-977` — `any_zone_occupied: bool` parameter) consumes a zone-derived
   bool composed from `tracker.raw_occupied` at the PresenceCoordinator caller (the
   actual composition site is `any_zone_raw_occupied = any(t.raw_occupied for t in
   self._zone_trackers.values())` at `presence.py:3996-3998`, used by the v4.7.18.1
   wake-timer fix). The substrate cycle MUST preserve `raw_occupied` freshness; both
   citations matter — the engine signature is the consumer surface, the
   `:3996-3998` composition is the freshness-critical compute path.
3. **Removal of a discovery code path (the area-sweep) with downstream consumers.**
   `_discover_room_sensors` + `_discover_room_sensors_by_name` (`presence.py:2168-2351`)
   go away (or change to a CONF-driven shape). Anything reading
   `tracker._entity_to_room` (set at `:2224, :2346`) is affected.
4. **Operator-elevated.** Same justification as Plan A — this is the substrate underneath
   the same cross-coordinator trust hierarchy.

### Framings (locked here; repeated at review dispatch)

- **Reviewer A — Discovery correctness + sensor-set divergence audit + tier-vocabulary
  hygiene.** For each configured room, does the substrate's per-kind set match the
  operator's curated CONF lists exactly? Are there rooms today where the zone-tier
  area-sweep included sensors the operator did NOT list (e.g., Jaya's 4-vs-2 case) — and
  is the operator OK with those sensors no longer contributing to the zone-tier reading?
  For rooms with no CONF lists (if any), does the fallback path behave correctly?
  Backward compatibility audit per-room. **Hygiene cross-check:** confirm no code or
  comment lands that calls the room tier "legacy" or implies the substrate replaces it
  (substrate is BENEATH both tiers, not a successor). Confirm the kill-paths for the
  area-sweep cleanly remove the discovery path without leaving orphan state on
  `tracker._entity_to_room` / `tracker._entity_kind_cache`.
- **Reviewer B — Smoothing-policy preservation + async/lifecycle.** Does the room tier's
  timeout/failsafe/camera/BLE-override smoothing stay byte-equivalent (the substrate only
  feeds the room tier's raw flat-OR input; downstream smoothing is unchanged)? Does the
  zone tier's `raw_occupied` semantics (the v4.7.18.1 wake-timer dependency) survive?
  Listener teardown on coordinator unload (Bug Class #38). Single subscription per
  configured sensor across both tiers (today the ROOM tier subscribes via the inline
  `_tier1_state_changed` callback registered in `RoomCoordinator.async_setup` —
  `coordinator.py:901-944` — and the ZONE tier subscribes via
  `_discover_room_sensors` `:2250-2256`; combined number of listeners may DROP after
  dedup, which is a behavior change worth documenting). Reviewer B specifically traces
  through the `coordinator.py async_setup` listener-registration code (the doc does NOT
  promise the room-tier listener is in a method called `_setup_state_listeners` — it is
  not; the registration is inline). No `async_dispatcher_send` function-local import
  (Bug Class #34, v4.7.20.1 recurrence).
- **Reviewer C — Boundary cleanliness + test fixture authority + consumer migration
  audit.** Where does the substrate physically live (shared helper module vs method on
  the room coordinator that the zone subscribes to)? Are there consumers in
  `_compute_fan_interference_rooms`, `_audit_provenance_invariants`, guest-room detector,
  D5 sensor attrs, `provenance_for` reading the prior shape that need adjustment? Does
  the new module ship with behavioral test fixtures extracted from production source (not
  hand-copied)?

The three framings are deliberately disjoint: A owns the **discovery surface** (what
sensors are subscribed and how they're named-to-kind), B owns the **temporal smoothing +
lifecycle** (does downstream behavior stay byte-equivalent; are listeners cleaned up),
C owns the **boundaries + module-level migration** (where the new code lives; do
consumers of the existing per-kind dict need touching; are tests authoritative). Risk
surface coverage cross-check: discovery (A) + lifecycle (B) + boundary/consumer-rip (C)
covers the three failure-mode classes for this cycle — wrong sensors subscribed (A),
right sensors but wrong timing/teardown (B), right data but wrong downstream wiring (C).

---

## Institutional context verified

### A. Primitives + signals + consumers (REUSED / NEW / MODIFY verdict per item)

| Primitive | Verdict | Evidence (file:line) | Notes |
|---|---|---|---|
| Curated config lists `CONF_MOTION_SENSORS / CONF_MMWAVE_SENSORS / CONF_OCCUPANCY_SENSORS` | **REUSED — promoted to single source of truth.** `const.py:311-313`. (Note: `CONF_MMWAVE_SENSORS = "presence_sensors"` — the storage key value doesn't match the const name; the substrate cycle keeps the key value unchanged so existing config entries remain readable.) | The substrate's identity layer. The zone tier stops trusting the entity-registry area-sweep and consumes these lists directly. |
| Room-tier `RoomCoordinator._async_update_data` | **REUSED — input changes, semantics unchanged.** `coordinator.py:1241-1610`. | Still reads `motion_sensors / mmwave_sensors / occupancy_sensors` via `self._get_config(CONF_*, [])`. The substrate publishes per-kind raw bools that the room tier can ALSO subscribe to OR continue to compute itself. Recommendation: leave the room tier's flat-OR computation in place (the substrate is the input source-of-truth, but the room tier's smoothing pipeline is independent). |
| Room-tier state-listener registration (inline `_tier1_state_changed` callback in `async_setup`) | **REUSED / MODIFIED.** Verified at `coordinator.py:901-944` — registration is INLINE inside `async_setup`, NOT in a method called `_setup_state_listeners` (which does not exist on `UniversalRoomCoordinator`). | Today the room tier and zone tier subscribe to potentially-different sets of binary_sensors. After the substrate change, the substrate publishes one canonical subscription set per room; both tiers consume from the substrate (no duplicate listeners). Reviewer B audits this carefully — the listener-count drop is a behavior change. |
| Room-tier `STATE_OCCUPANCY_SOURCE` resolution | **REUSED — strict subset of substrate.** `coordinator.py:1408-1444, 1510, 1539, 1586, 1876, 1882`. | Today's flat-OR collapses to ONE winner (motion / mmwave / occupancy_sensor / timeout / camera / ble / failsafe / grace_hold / override / none). Post-substrate, the underlying raw per-kind bools are exposed (so a consumer that wants "all kinds firing right now" can read them) BUT the room tier's `STATE_OCCUPANCY_SOURCE` field stays unchanged for backward compat. The substrate exposes the wider view through a NEW attribute (D2). |
| Zone-tier `_discover_room_sensors` (area-sweep) | **DELETED (full replacement — NO fallback).** `presence.py:2168-2308`. | The area-sweep is the source of the Jaya/Exercise divergence. Replaced with CONF-driven discovery that reads the same lists the room tier reads. The area-sweep is NOT retained as a fallback — that would reintroduce the divergence it causes. Rooms with no CONF lists register zero Tier-1 sensors (made visible via the D5 INFO log + planning-time CONF-coverage audit), exactly as if the sweep found nothing. |
| Zone-tier `_discover_room_sensors_by_name` (name fallback) | **DELETED (full replacement — NO fallback).** `presence.py:2310-2351`. | A workaround for rooms with no area_id. Post-substrate, a room with no CONF lists is simply a no-Tier-1 room (D5) — it falls through to camera/BLE composition. No silent name-classifier fallback survives. See D5. |
| Zone-tier `_classify_entity_kind` substring heuristic | **REPLACED for CONF-listed sensors.** `presence.py:226-281` (CONF-list lookup branch at `:241-273`; substring fallback at `:275-281`). | The CONF-list lookup branch already returns the canonical kind from the CONF list slot — this is the substrate's classification. The substring fallback is retained ONLY for non-CONF sensors (defensive — should never fire for properly-configured rooms post-substrate). Logged at WARN if substring fallback ever fires post-substrate to surface configuration gaps. |
| Zone-tier `_classify_entity_kind_cached` wrapper | **REUSED — cache scope adjusted.** `presence.py:1232-1255`. | Cache key (entity_id, room_name). Substrate change does not alter cache shape; cache invalidation on `_discover_room_sensors` re-entry (`presence.py:2177`) still fires. |
| Zone-tier `_handle_occupancy_change` listener callback | **REUSED — feeds substrate.** | The callback writes to the substrate instead of writing directly to `_room_provenance`. Substrate fan-out to the per-tier views. |
| Zone-tier `_room_provenance` dict | **REUSED — source of writes changes.** `presence.py:419` (declaration; per-room dicts populated lazily). | Stays as the zone tier's view of per-kind state. Now POPULATED from the substrate rather than from a divergent listener set. Shape unchanged → `provenance_for` (`presence.py:535-561`) and derived `_room_occupied` (`presence.py:474-533`) consumers are unaffected. |
| Zone-tier derived `_room_occupied` property | **REUSED — semantics unchanged.** `presence.py:474-533`. | Still derives from `_room_provenance`. The v4.7.20 hold extension lives here today; substrate cycle is orthogonal to whether that hold is kept (Plan A § P2). |
| Zone-tier `raw_occupied` property | **REUSED — semantics unchanged.** `presence.py:563-570`. | v4.7.18.1 wake-timer dependency. Reviewer B verifies post-substrate raw_occupied freshness is at least as fast as today (substrate is INSTANTANEOUS per-kind, so raw_occupied freshness is unchanged or improved). The freshness-critical caller is the `any_zone_raw_occupied` compute at `presence.py:3996-3998`. |
| `_audit_provenance_invariants` | **REUSED — semantics unchanged.** `presence.py:284-386`. | Operates on `_room_provenance` shape, which doesn't change. Verified the four invariants still hold post-substrate. |
| `_compute_fan_interference_rooms` zone-tier diagnostic | **REUSED — reads per-kind provenance.** `presence.py:2539-2698`. | Unchanged. Post-substrate, the diagnostic is MORE reliable because per-kind data agrees with the CONF list operator chose. |
| D5 sensor attrs on `OccupiedBinarySensor` | **REUSED — `provenance_for` consumers.** `binary_sensor.py:405-501`. | Unchanged shape; data quality improves. (Prior draft said `:410-510`; the attr block actually starts at `:405` and the exception fallback ends at `:501`.) |
| D5 guest-room detector subscribing to `binary_sensor.<room>_occupied` | **REUSED — reads room-tier sensor.** `presence.py:3500-3561` (`_discover_guest_rooms` and the subscribe site at `:3551-3556`). | Unaffected (room tier sensor identity unchanged). |
| Room-tier `binary_sensor.<room>_occupied` sensor entity | **REUSED — unchanged.** | Entity ID, state, attrs all unchanged. |
| `CONF_ADJACENT_ROOMS` per-room adjacency | **REUSED — unchanged.** `const.py:373`, `config_flow.py:1104, 6620`, `presence.py:1995-2017`. | Substrate is orthogonal to adjacency. |
| `D3_DIAGNOSTIC_ENABLED` kill switch | **REUSED — unchanged.** `const.py:351`. | Same kill switch for the zone-tier diagnostic. The substrate has no separate kill switch — it's a foundational layer. |
| **`OccupancySubstrate` module** (per-room, per-kind, instantaneous raw view + listener registration) | **NEW.** Verified absent — `Grep "OccupancySubstrate\|occupancy_substrate\|RawOccupancy"` across `custom_components/` returned 0 matches at planning time. | Headline NEW surface. ~200 LoC in a new file `domain_coordinators/occupancy_substrate.py`. |
| `RawOccupancyState[room][kind] -> bool` per-room per-kind view | **NEW — published by substrate.** Verified absent (covered by the same grep). | Read by both tiers (zone tier via the substrate API; room tier still computes its own flat-OR but the substrate is the source of truth for per-kind raw signal). |
| Substrate API surface | **NEW.** Verified absent — `Grep "is_kind_active\|get_room_kinds"` across `custom_components/` returned 0 matches at planning time. `is_kind_active(room, kind) -> bool`, `get_room_kinds(room) -> Dict[str, bool]`, `get_kinds_for_room_at_tick(room) -> Dict[str, bool]`, `subscribe(callback)`. | Idiomatic, fail-OPEN. |
| `SIGNAL_SUBSTRATE_KIND_CHANGED(room, kind, new_state)` | **NEW.** Verified absent — `Grep "SIGNAL_SUBSTRATE_KIND_CHANGED"` across `custom_components/` returned 0 matches. Lives in `domain_coordinators/signals.py` (verified path — there is no top-level `signals.py`; the canonical signals module is `domain_coordinators/signals.py`). | Dispatched on every per-kind edge. Subscribed by `_handle_occupancy_change` in zone tier (replaces direct state-change subscription). |

### B. Prior planning docs consulted

| Doc | Relevance | Read depth |
|---|---|---|
| `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md` | **Companion plan.** Defines the cross-check shape Plan A relies on; the substrate makes the cross-check tractable. See § Seam-with-Plan-A. | Full body (just rewritten same session). |
| `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` | v4.7.19 cycle. Defines `_room_provenance`, `provenance_for`, derived `_room_occupied` property. Substrate sits BENEATH this and feeds it. | Full body. |
| `docs/planning/PLANNING_fan_noise_mitigation_layers1_2.md` | v4.7.20 cycle that built the hold extension on top of `_room_occupied`. Substrate is orthogonal to the hold; Plan A § P2 decides whether to strip. | Header + D1. |
| `docs/planning/PLANNING_v4.7.18.1_sleep_wake_deadlock.md` (if filed; otherwise the LIVE memo) | v4.7.18.1 introduced `raw_occupied` for the wake-timer fix. Substrate must preserve `raw_occupied` freshness. | Memory body. |
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | "Presence provides STATE not ACTIONS." Substrate is pure STATE (no actuation). Invariant honored. | Re-read. |
| `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` | Cross-coordinator boundaries and the URA layered lattice (room / zone / house) framing. Substrate sits BENEATH the room and zone tiers — it's a sensor-layer abstraction, not a new tier. | Re-read. |

### C. Memory bodies pulled

| File | Relevance |
|---|---|
| `project_v4_7_19_live.md` | Provenance split + the cold-boot away-actuation storm context. Substrate must NOT add to boot storm — subscribe + first-tick semantics covered in D6. |
| `project_v4_7_18_1_sleep_wake_deadlock.md` | `raw_occupied` introduction. Substrate preserves the freshness this fix depends on. |
| `project_v4_7_20_fan_noise_layer1_live.md` | The two-failure-modes reframe. Substrate is the durable fix for the discovery/classification divergence Plan A works around. |
| `project_fan_noise_mmwave_mitigation_backlog.md` | Operator's note-b ("PIR/mmWave OR split prereq: do it, but CONTEXT-WIDE, no regression"). Substrate IS the context-wide split. |

### D. Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — substrate is pure-state, honors the invariant.
- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — substrate is a sensor-layer abstraction
  that sits beneath both tiers; not a new tier.
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — HVAC reads ROOM tier directly. Substrate
  is largely invisible to HVAC (the room tier's smoothing pipeline is unchanged).

### E. Code locations surveyed (read end-to-end during scoping)

| File | Lines surveyed | What was confirmed |
|---|---|---|
| `coordinator.py` | `:1241-1610` (full `_async_update_data` path), `:1248-1250` (CONF list reads), `:1289-1309` (stuck-sensor detector — reads CONF list), `:1311-1330` (motion/mmwave/occupancy flat-OR), `:844-944` (`async_setup` listener registration — inline `_tier1_state_changed` at `:901-944`, NOT in a `_setup_state_listeners` method) | The room tier's logic IS already CONF-list-driven. Substrate makes the underlying listener set canonical without changing the room tier's smoothing. |
| `presence.py` | `:226-281` (`_classify_entity_kind` — CONF-list branch at `:241-273`, substring fallback at `:275-281`), `:412-561` (provenance + derived view, `_room_provenance` declared at `:419`, `_room_occupied` property at `:474-533`, `provenance_for` at `:535-561`), `:563-570` (`raw_occupied` property), `:1232-1255` (cache wrapper), `:2168-2308` (`_discover_room_sensors` area-sweep — seed loop at `:2262-2308`), `:2310-2351` (name fallback), `:1995-2017` (adjacency cache), `:2539-2698` (fan-interference diagnostic), `:3500-3561` (guest-room subscribes to room-tier sensor), `:3996-3998` (`any_zone_raw_occupied` composition — v4.7.18.1 wake-timer freshness path), `:852-977` (`StateInferenceEngine.infer` signature — `any_zone_occupied: bool` parameter, the consumer surface) | Zone tier is the source of divergence. CONF-list classification is already implemented in `_classify_entity_kind` (`:241-273`) — substrate cycle just makes that the EXCLUSIVE source path and removes the area-sweep + substring discovery. |
| `const.py` | `:208-637` (STATE_* + CONF_*) | Surface and the CONF list key names. |
| `binary_sensor.py` | `:405-501` (OccupiedBinarySensor attr block, including `provenance_for` consumer at `:434-435`; exception fallback at `:492-500`) | D5 surface unchanged. |
| `hvac_zones.py` | `:537-552` | HVAC reads room tier — substrate invisible to HVAC. |
| `domain_coordinators/signals.py` | (path verified) | The canonical signals module is here; there is no top-level `signals.py`. New `SIGNAL_SUBSTRATE_KIND_CHANGED` lands in this file. |

---

## Non-goals (explicit, locked)

- **No new tier.** Substrate is a sensor-layer abstraction; the room + zone + house tier
  structure is preserved.
- **No "legacy" label for the room tier.** The room tier is a deliberate, current,
  CONF-driven path. The substrate sits BENEATH it (input layer), it does not supersede
  it. Code comments and docs that drift toward "old/legacy/replaced-by" language about
  `coordinator.py` are wrong and should be caught in review.
- **No collapse of zone tier onto room tier.** They have legitimately distinct smoothing
  policies. Substrate unifies the INPUT layer; smoothing stays per-tier.
- **No removal of room tier's timeout / failsafe / camera / BLE override.** These are
  HVAC stability levers; substrate is upstream of them.
- **No removal of zone tier's `raw_occupied` semantics.** v4.7.18.1 wake-timer depends on
  it. Substrate preserves freshness.
- **No removal of `_room_provenance` shape.** Substrate FEEDS it; `provenance_for` and
  derived `_room_occupied` consumers are unaffected.
- **No removal of the v4.7.20 hold.** Orthogonal to substrate. Plan A § P2 decides.
- **No deprecation of `STATE_OCCUPANCY_SOURCE`.** Backward compat: same single-winner
  attr stays in place. Substrate exposes a NEW per-kind attr alongside.
- **No automatic re-discovery on every entity-registry change.** Substrate re-discovery is
  triggered on the same events as today's `_discover_room_sensors` (config-flow reload,
  options-flow save, room-coord init).
- **No new DB schema.** Substrate is pure in-memory state. Restart behavior: substrate
  re-derives from current `hass.states` on `async_setup` (no persistence needed because
  the substrate is INSTANTANEOUS — it's a view, not a memory).
- **No subscription to entities outside the operator's CONF lists.** This is the WHOLE
  POINT — the substrate trusts the operator's curation.

---

## Discipline: what the substrate is NOT a substitute for

This is the explicit tradeoff the operator and I reasoned through. Do not collapse it.

| Concern | Where it lives | Why NOT in substrate |
|---|---|---|
| Room-tier 900s timeout decay | RoomCoordinator | HVAC stability lever; substrate is instantaneous |
| Room-tier failsafe force-vacant | RoomCoordinator | Bounded smoothing; substrate is instantaneous |
| Room-tier camera override | RoomCoordinator | Independent signal tier (camera) blends in at smoothing layer |
| Room-tier BLE override | RoomCoordinator | Independent signal tier (BLE) blends in at smoothing layer |
| Zone-tier `raw_occupied` freshness | ZonePresenceTracker | v4.7.18.1 wake-timer dependency; preserved by substrate's instantaneous publish |
| Zone-tier camera `_camera_occupied` timeout | ZonePresenceTracker | `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS` is a zone-tier smoothing knob |
| Zone-tier `_derived_mode` (BLE → room → camera precedence) | ZonePresenceTracker | Zone-tier composition rule; orthogonal to substrate |
| Zone-tier `_room_occupied` derived-OR view | ZonePresenceTracker | Composition on top of `_room_provenance`; substrate feeds the latter |
| v4.7.20 hold extension (if kept) | ZonePresenceTracker | Smoothing decision, not raw signal |
| Plan A BLE-ladder (L1 / L2 / L3 / Tier-1/2/0 drop-authorization) | `_ble_corroboration.py` + `presence_fan_recheck.py` | Different signal class (BLE phone presence vs Tier-1 sensor presence); substrate does NOT carry BLE data and cannot help Plan A's BLE-tier logic. See § Seam-with-Plan-A bullet 3. |

The substrate is **per-room, per-kind, instantaneous raw truth.** That's all. Every
existing temporal policy stays where it lives today.

---

## D1 — `OccupancySubstrate` module (the headline new surface)

NEW file: `domain_coordinators/occupancy_substrate.py` (~200 LoC).

Responsibilities:

1. **Discovery.** For each configured ROOM entry (`ENTRY_TYPE_ROOM`), read the three CONF
   lists and produce the canonical (entity_id, room_name, kind) triples. NO area-sweep,
   NO name heuristic. Kind is determined by which CONF list slot the entity is in. An
   entity listed in multiple CONF lists for the same room is reported at WARN and the
   first match (in declared order motion → mmwave → occupancy) wins (defensive — should
   not happen in normal operator configs).
2. **Listener registration.** One state-change subscription per (entity_id) covering all
   the discovered Tier-1 entities. Single canonical subscription set; both tiers consume
   from the substrate.
3. **Per-kind raw state.** `_raw_state[room_name][kind] -> bool` keyed on the curated kind
   ∈ TIER1_KINDS. Updated synchronously on every state-change callback. Unavailable /
   unknown states map to False (matches today's `_handle_occupancy_change` semantics).
4. **Publish.** On every per-kind edge, dispatch `SIGNAL_SUBSTRATE_KIND_CHANGED(room,
   kind, new_state)`. Zone tier subscribes; calls `tracker.update_room_occupancy(room,
   new_state, kind=kind)` exactly as today's `_handle_occupancy_change` does.
5. **Seed on startup.** Mirror the v4.7.18.1 B-HIGH-1 seed: on `async_setup`, read current
   `hass.states.get(entity_id)` for each discovered entity and seed `_raw_state` + emit
   the same signal so the first tick agrees with reality.
6. **Re-discovery.** On config-flow / options-flow change for a room entry, re-read the
   CONF lists, unsubscribe stale entities, subscribe newly added entities, prune
   `_raw_state` entries for removed entities. Bug Class #38: clean teardown of stale
   subscriptions.
7. **Owned by the PresenceCoordinator instance** (not a global). Initialized at
   PresenceCoordinator `async_setup`. Reviewer B confirms lifecycle.

### D1 API

```
class OccupancySubstrate:
    def is_kind_active(self, room_name: str, kind: str) -> bool: ...
    def get_room_kinds(self, room_name: str) -> Dict[str, bool]:
        """Returns a stable dict with every TIER1_KINDS slot present
        (missing kinds default False). Same shape as provenance_for."""
    def get_all_room_kinds(self) -> Dict[str, Dict[str, bool]]: ...
    def subscribe(self, callback: Callable[[str, str, bool], None]) -> Callable[[], None]:
        """Subscribe to per-kind edges. Returns unsub callable."""
```

### D1 Acceptance Criteria

- **Verify (Jaya divergence kills):** for Jaya room, `OccupancySubstrate.get_room_kinds("Jaya Bedroom")`
  returns kinds derived ONLY from the operator's curated 2 sensors. The two area-sweep-
  superset sensors (`mmwave_zigbee_jayabedroom_presence`,
  `seeedstudio_mmwave_kit_047d34_presence_information`) are NOT subscribed and NOT in the
  per-kind view.
- **Verify (Exercise divergence kills):** for Exercise room, the curated 2 sensors are the
  only contributors. The hobeian occupancy-class sensor is treated as MOTION (per the
  operator's CONF_MOTION_SENSORS placement), matching the room tier's classification
  exactly.
- **Verify (kind agreement):** for every configured room, the substrate's per-kind view
  MATCHES the room tier's `STATE_OCCUPANCY_SOURCE` directional sense — when room-tier
  reads `motion`, the substrate has motion=True for that room at the same tick.
- **Verify (seed correctness):** post-restart, the first tick's substrate state matches
  the current `hass.states` for every subscribed entity (per the v4.7.18.1 B-HIGH-1
  pattern).
- **Verify (listener-count drop is testable):** build-time computation produces an
  EXPECTED listener-count delta N per (room, tier) — counted by enumerating today's
  pre-substrate subscription sites: room-tier inline `_tier1_state_changed`
  (`coordinator.py:901-944`) over `tier1_sensors`, and zone-tier `_discover_room_sensors`
  subscription at `presence.py:2250-2256` over the area-sweep set. Test asserts
  post-substrate combined listener count = expected dedup'd set (sized at build using a
  one-off audit script committed alongside the cycle). Acceptance is a numeric equality,
  not a "≥ some N" inequality.
- **Sensor:** new diagnostic attribute `substrate_kinds` on `binary_sensor.<room>_occupied`
  showing the current per-kind raw view at the last tick. Lazy attr (read on access).
- **Test:** `quality/tests/test_substrate_discovery.py` — for synthetic CONF lists,
  substrate produces the expected (entity_id, room, kind) triples; no area-sweep
  contamination.
- **Test:** `quality/tests/test_substrate_classification.py` — kind always equals the CONF
  list slot, never the substring heuristic, for CONF-listed sensors.
- **Test:** `quality/tests/test_substrate_seed.py` — seed-vs-live invariant (same predicate
  used at seed and on state-change).
- **Test:** `quality/tests/test_substrate_lifecycle.py` — re-discovery cleanly unsubs
  stale listeners and subscribes new ones (Bug Class #38).
- **Live:** post-deploy, `binary_sensor.jaya_bedroom_bedroom_4_occupied.attributes.substrate_kinds`
  shows ONLY the operator-curated kinds. Operator manually verifies parity with intent.

---

## D2 — Zone-tier migration onto substrate

MODIFY `presence.py`:

1. **Remove the area-sweep + name-fallback discovery** (`_discover_room_sensors` body at
   `:2168-2308` and `_discover_room_sensors_by_name` at `:2310-2351`). REPLACE with a
   thin subscription to the substrate's `SIGNAL_SUBSTRATE_KIND_CHANGED`.
2. **`_handle_occupancy_change` rewires.** Today it reads state-change events directly.
   Replace with a substrate subscription handler that calls
   `tracker.update_room_occupancy(room, new_state, kind=kind)` with the same call shape.
   Result: `_room_provenance` writes are unchanged; the dispatch source changes.
3. **`_classify_entity_kind_cached` becomes vestigial for CONF-listed sensors.** Kept for
   compatibility (callers in `:3215, :3230` continue to work) but the cache is populated
   exclusively from the substrate's pre-classified triples. The substring fallback at
   `_classify_entity_kind:275-281` is RETAINED and gated on a WARN log if it ever fires
   (it should not, for properly-configured rooms).
4. **Adjacency cache (`presence.py:1995-2017`) UNCHANGED.**
5. **`raw_occupied` UNCHANGED.** v4.7.18.1 invariant preserved (substrate publishes
   instantaneously; `raw_occupied` is at least as fresh as today).
6. **`_audit_provenance_invariants` UNCHANGED.** Reviewer B confirms invariants still hold
   post-migration.

### D2 Acceptance Criteria

- **Verify (no area-sweep):** grep `for entity in ent_reg.entities.values()` inside
  `_discover_room_sensors` returns zero matches post-cycle. Discovery path is exclusively
  CONF-list-driven.
- **Verify (provenance shape unchanged):** for each room, the shape of
  `_room_provenance[room]` (kinds present) post-substrate is a SUBSET of pre-substrate
  (the substrate may report fewer kinds when the area-sweep was pulling in extra
  sensors). Reviewer A confirms this subset is the operator's intent.
- **Verify (raw_occupied freshness):** behavioral test that drives a per-kind edge through
  the substrate completes within the same tick budget as the pre-substrate state-change
  path (no regression on v4.7.18.1 wake-timer semantics).
- **Verify (audit invariants):** `_audit_provenance_invariants` returns the same empty
  violation list pre- and post-substrate for a synthetic stable state.
- **Test:** `quality/tests/test_zone_substrate_migration.py` — drives a state-change
  through the substrate and asserts the zone tier's `_room_provenance` updates correctly.
- **Live:** post-deploy, `_compute_fan_interference_rooms` output is at least as
  meaningful as today (the room-tier and zone-tier kinds now agree by construction).

---

## D3 — Room-tier integration (optional cleanup, low priority — DEFER recommended)

The room tier ALREADY consumes the CONF lists directly via `coordinator.py:1248-1250`.
Substrate cycle does NOT need to change room-tier logic for correctness.

**Decision: DEFER D3 to a follow-up cycle.** Justification:

- Substrate's value is overwhelmingly in unifying the **zone-tier** discovery (D2). The
  zone-tier was the source of the live Jaya / Exercise divergence; the room tier was
  never divergent.
- D3 is a latency win only (event-driven vs polling-interval), not a correctness win.
  The room-tier `_tier1_state_changed` callback already runs on every per-sensor state
  change (`coordinator.py:906`), so the latency delta is bounded by the existing 2s
  rate-limiter, not by the substrate.
- Tier 2-DB ceremony is heavy. Adding D3 doubles the test surface (room-tier consumers
  of the substrate require their own backward-compat audit) for marginal benefit.
- Operator-confirm during planning. D3 stays documented for future cycles.

If D3 is later pursued, the integration is small (RoomCoordinator subscribes to
`SIGNAL_SUBSTRATE_KIND_CHANGED` for its configured room and triggers
`async_set_updated_data`). No fan-out work needed.

### D3 Acceptance Criteria (if pursued in a future cycle)

- **Verify:** room tier picks up Tier-1 changes within one event-loop tick instead of one
  polling interval. (Test against the existing 2s rate-limiter behavior in
  `_tier1_state_changed` at `coordinator.py:929-937`.)
- **Test:** `quality/tests/test_room_substrate_integration.py`.

---

## D4 — Backward-compat audit

Per the Tier 2-DB framing, every consumer of the affected surfaces is audited.

| Consumer | Read surface | Behavior pre-substrate | Behavior post-substrate |
|---|---|---|---|
| HVAC zone aggregator | `coordinator.data["occupied"]` (room tier) | unchanged | unchanged (room tier smoothing preserved) |
| HVAC defer gate | `check_zone_occupancy_confidence` (enumerates room coords) | unchanged | unchanged |
| House-state inference | `StateInferenceEngine.infer(any_zone_occupied=...)` (`presence.py:852-977` signature) ← composition at `presence.py:3996-3998` (`any_zone_raw_occupied = any(t.raw_occupied for t in self._zone_trackers.values())`) ← `tracker.raw_occupied` (`:563-570`) ← `_derived_mode` ← `_room_occupied` (`:474-533`) ← `_room_provenance` | unchanged | unchanged (substrate feeds `_room_provenance`; downstream composition identical) |
| Guest-room detector | subscribes to `binary_sensor.<room>_occupied` | unchanged | unchanged |
| D5 OccupiedBinarySensor attrs | `tracker.provenance_for(room)` | unchanged shape | data quality improves (kinds reflect operator config) |
| `_compute_fan_interference_rooms` zone diagnostic | `_room_provenance`, `_fan_on_rooms` | unchanged shape | data quality improves |
| `_audit_provenance_invariants` | `_room_provenance` | unchanged invariants | invariants preserved |
| Plan A trigger condition | room-tier `STATE_OCCUPANCY_SOURCE == "mmwave"` | works today | works identically post-substrate; precondition can OPTIONALLY tighten to per-kind raw view (post-substrate path) |
| Plan A acceptance D2.7 cross-check | "does zone-tier per-kind picture corroborate room-tier verdict?" | unreliable today (divergence) | reliable post-substrate (kinds agree by construction) |
| Plan A BLE-ladder + Tier-1/2/0 drop-authorization gate (D1.5) | `person_coord.get_ble_tier`, `get_persons_in_room`, adjacency cache | unchanged | unchanged — substrate carries NO BLE data; this consumer column lives entirely outside the substrate's signal class |
| Quality test `test_presence_provenance_split.py` | invariants | unchanged | unchanged |

For ANY consumer not on this list, Reviewer C grep-audits during review.

### D4 Acceptance Criteria

- **Verify:** every consumer in the table above is traced. Behavior recorded as
  unchanged or improved.
- **Test:** `quality/tests/test_substrate_backcompat.py` — for each consumer, drive a
  synthetic substrate state-change and assert the consumer's output matches
  pre-substrate.

---

## D5 — Rooms with no CONF lists (fallback)

Some rooms may genuinely have no configured Tier-1 sensors (camera-only rooms, BLE-only
rooms). Today the zone tier's area-sweep silently provides no sensors for such rooms (no
entity_ids match the area). Post-substrate, the same behavior is preserved by EXPLICIT
fallback: if all three CONF lists are empty for a room, the substrate registers zero
sensors for that room AND logs at INFO once "Room <name>: no Tier-1 occupancy sensors
configured; relying on zone tier camera/BLE composition." This makes the configuration
gap visible (today it's silent) without changing behavior.

The substring-based name fallback (`_discover_room_sensors_by_name`) is DELETED — it was
a workaround for rooms with no area_id that ALSO had no CONF lists. Such rooms are simply
no-Tier-1 rooms post-substrate (handled above).

### D5 Acceptance Criteria

- **Verify:** a synthetic room with empty CONF lists registers zero substrate listeners
  and logs the explicit INFO once.
- **Verify (audit script — PLANNING-TIME TOOL, not a pre-deploy gate):** the audit
  enumerates all configured ROOM entries and reports which (if any) have empty CONF lists
  / are relying on the area-sweep superset today. **DECIDED (operator, 2026-06-05): this
  is a planning-time informational tool the planner/operator runs to size the migration
  and decide which rooms to curate — it does NOT block the deploy.** Run it during
  scoping; act on its output by curating CONF lists where wanted; the cycle ships
  regardless (uncovered rooms degenerate to no-Tier-1, surfaced by the D5 INFO at
  runtime). The script ships in `quality/scripts/audit_substrate_conf_coverage.py`.
- **Test:** `quality/tests/test_substrate_no_conf_lists_fallback.py`.

---

## D6 — Cold-boot storm coordination

Substrate `async_setup` runs early in PresenceCoordinator init (before
`_discover_room_sensors` is called today). Listener subscriptions and initial seeding
fire WITHIN the cold-boot window. This is acceptable because the substrate is pure
observation — it does not ACTUATE — but the SIGNAL_SUBSTRATE_KIND_CHANGED dispatches
during the boot storm may be noisy. Mitigation:

- Substrate suppresses signal dispatch during the boot window
  (`_boot_settle_done == False` — read from the PresenceCoordinator that owns the
  substrate; declared at `presence.py:1191`, gated at `:1669, :1722, :3814, :4587`),
  but still updates `_raw_state` so the FIRST post-boot tick reads correctly.
- At settle (transition `_boot_settle_done False → True`), the substrate emits ONE
  synthetic `SIGNAL_SUBSTRATE_KIND_CHANGED` per (room, kind) slot whose seeded state is
  True at that moment. False-seeded slots emit NO signal at settle (consumers default
  False; emitting "kind=False" on every kind would itself become a per-room storm).
- Zone tier's `_handle_occupancy_change` already runs through the inference loop which
  has its own settle handling; this is defense-in-depth.

**Does this avoid adding to the known cold-boot away-actuation storm?** Yes, provided
the two invariants hold:
1. **During boot:** NO signal dispatch. Consumers see only the seeded post-settle
   snapshot, not a per-state-change stream. Verified by the test below.
2. **At settle:** ONLY True slots emit. False slots default-False in consumers, so a
   settle that finds the house already empty produces ZERO dispatches — strictly less
   noise than today's `_discover_room_sensors` seed loop at `presence.py:2262-2308`,
   which writes False to every room/kind unconditionally.

The substrate does NOT actuate, so even if a signal escapes during boot, the worst
case is a redundant zone-tier `_room_provenance` write (no downstream actuation). This
is strictly safer than the v4.7.19 cold-boot away-actuation storm pattern (which
involved HVAC writes triggered by zone-tier composition).

### D6 Acceptance Criteria

- **Verify (dispatch suppression):** behavioral test drives N state-change events
  during a simulated cold-boot window (`_boot_settle_done == False`) and asserts the
  dispatcher receives ZERO `SIGNAL_SUBSTRATE_KIND_CHANGED` emissions. `_raw_state` is
  asserted to have been updated nonetheless.
- **Verify (settle emit count):** at the boot-settle transition, the substrate emits
  exactly one signal per (room, kind) slot whose seeded state is True. False slots emit
  none. Test asserts the count equals `sum(1 for room in rooms for kind in TIER1_KINDS
  if seeded[room][kind])`, NOT the larger `len(rooms) * len(TIER1_KINDS)`.
- **Verify (no storm contribution):** integration test seeds a synthetic empty-house
  cold-boot scenario and asserts ZERO substrate dispatches at settle (matches
  v4.7.19 storm-context invariant).
- **Test:** `quality/tests/test_substrate_boot_settle.py`.

---

## D7 — Files changed

| File | Change |
|---|---|
| `const.py` | No change. CONF list names unchanged. |
| `domain_coordinators/signals.py` | ADD `SIGNAL_SUBSTRATE_KIND_CHANGED`. (Path is `domain_coordinators/signals.py`; there is no top-level `signals.py` in this repo.) |
| `domain_coordinators/occupancy_substrate.py` | NEW (~200 LoC). Substrate class, discovery, listeners, seed, re-discovery, publish. |
| `domain_coordinators/presence.py` | REMOVE area-sweep body in `_discover_room_sensors` (`:2168-2308`); REPLACE with substrate subscription. REMOVE `_discover_room_sensors_by_name` (`:2310-2351`). REWIRE `_handle_occupancy_change` to consume substrate signals. `_classify_entity_kind` substring fallback retained, WARN-logged if it fires for CONF-listed sensors. |
| `domain_coordinators/__init__.py` | EXPORT `OccupancySubstrate`. |
| `__init__.py` | Wire substrate instantiation on PresenceCoordinator setup; teardown on unload. |
| `binary_sensor.py` | ADD `substrate_kinds` lazy attr on `OccupiedBinarySensor` (extends the existing attr block at `:405-501`). |
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | UPDATE: document the substrate as the unified Tier-1 raw-signal layer; clarify that smoothing stays per-tier; clarify the room tier is NOT being deprecated. |
| `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` | UPDATE: add substrate to the layered lattice diagram (beneath room + zone). |
| `quality/scripts/audit_substrate_conf_coverage.py` | NEW. Audits which configured ROOM entries have empty CONF lists; used during planning + as a deploy-time check. |
| `quality/tests/test_substrate_*.py` | NEW (6 files per D-acceptance). |
| `quality/tests/test_zone_substrate_migration.py` | NEW. |
| `docs/planning/AUDIT_occupancy_substrate_consumer_ripple.md` | NEW. Per-consumer ripple table per D4. |

NOTE: no DB schema change. No new CONFs. No new entities besides the diagnostic attr.

---

## D8 — Plan completion tracking (post-build)

| Item | Status | Notes |
|---|---|---|
| (TBD at deploy time) | | |

---

## D9 — Open questions / scope risks for operator weigh-in

1. **Ownership location.** Recommendation: a helper module (`occupancy_substrate.py`)
   owned by the PresenceCoordinator. Alternative: a method on RoomCoordinator that the
   zone subscribes to. Picked module ownership because the substrate is shared by N rooms
   and the PresenceCoordinator is the natural cross-room owner. Operator-confirm.
2. **What to do about rooms whose area-sweep included sensors the operator did NOT list.**
   **DECIDED (operator, 2026-06-05): drop them + log-WARN-once per dropped sensor at
   startup.** The substrate trusts the CONF lists; each area-sweep-superset sensor that is
   silently dropped (e.g., Jaya 4→2, Exercise 3→2) emits one WARN at startup naming the
   sensor and the room so the divergence is surfaced, not silent. This is observability
   only — it does NOT re-include the sensor.
3. **D3 (room-tier integration) deferred (see D3). DECIDED (operator, 2026-06-05):
   confirmed deferred — ~zero latency cost.** The room tier is ALREADY event-driven for
   its Tier-1 sensors via the inline `_tier1_state_changed` callback
   (`coordinator.py:907`, registered through `async_track_state_change_event` at
   `:960-964`, 2s rate-limiter + trailing-edge refresh; Tier-2 sensors poll at 30s).
   Routing the room tier through the substrate is a listener-CONSOLIDATION / single-
   source-of-truth win, NOT a latency win — deferring it leaves the room tier reacting to
   motion/mmwave/occupancy changes just as fast as today. D3 lands as a follow-up once
   the zone-tier substrate has soaked.
4. **Substrate boot-storm signal suppression vs naïve dispatch.** Recommendation: suppress
   during boot, emit synthetic seed signals at settle for True-slots only (D6).
   Alternative: dispatch all during boot. Suppression is safer — boot storms hurt.
5. **Substring-fallback retention for non-CONF sensors.** Recommendation: keep + WARN.
   Alternative: hard error / refuse to register. Keep-and-WARN is gentler for live
   migration.
6. **`STATE_OCCUPANCY_SOURCE` strict-subset attribute.** The room tier's single-winner
   collapse stays. Should the substrate's per-kind view ALSO be promoted to a top-level
   sensor attribute on `binary_sensor.<room>_occupied`? Recommended yes — visible in HA
   dev tools, valuable for operator inspection.

---

## Seam-with-Plan-A (CRITICAL — read with companion doc open)

Plan A ships FIRST per operator preference. The substrate is the durable cleanup that
lands next. Plan A's recent amendments — (a) the BLE tier-gated drop-authorization rule
(only Tier-1 rooms let BLE-absence authorize a drop; Tier-2/0 are "trust sensors only"
with BLE veto-only) and (b) the adjacency tier-flip (a phone in an adjacent room weakly
authorizes in Tier-1 but is an unconditional veto in Tier-2) — are **about the BLE
signal class, not the Tier-1 sensor signal class.** The substrate carries the latter
only. So both amendments are orthogonal to the substrate by construction, and the seam
list below holds unchanged.

Specific seams:

1. **Plan A's `STATE_OCCUPANCY_SOURCE == "mmwave"` trigger precondition** is correct
   today (room-tier flat-OR precedence is well-defined; mmwave-only fires when motion =
   occupancy = False). After the substrate, this can OPTIONALLY tighten to "substrate
   reports mmwave True AND motion False AND occupancy False for N consecutive ticks" —
   strictly more precise. Plan A's `CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS` ring already
   provides the history shape; post-substrate, the trigger reads substrate's per-kind
   view per tick instead of `STATE_OCCUPANCY_SOURCE`. This is a 1-line change in
   `presence_fan_recheck.py` once the substrate ships. No churn to the rest of the state
   machine.

2. **Plan A's `_recent_occupancy_sources` ring on RoomCoordinator** stays. The ring is the
   short-history shape; the substrate is the per-tick raw kind view. They compose
   naturally — Plan A can either keep computing the ring from `STATE_OCCUPANCY_SOURCE` (no
   change) or switch to deriving from the substrate (one-line refactor). No deletion.

3. **Plan A's BLE ladder shared helpers (`_ble_corroboration.py`), BLE-tier
   drop-authorization gate (D1.5), and adjacency tier-flip** are orthogonal to the
   substrate by signal class. The substrate carries Tier-1 SENSOR data (motion / mmwave
   / occupancy binary_sensors). The BLE ladder carries Tier-1 PERSON-TRACKING data
   (`person_coord.get_persons_in_room`, `get_ble_tier`, `get_persons_in_zone`). Different
   data sources, different cadences, different failure modes. The substrate does not and
   should not help Plan A's BLE-tier logic; conversely, Plan A's BLE-tier logic does not
   constrain the substrate. **Affirmed orthogonal.**

4. **Plan A's `presence_fan_recheck.py` state machine** is orthogonal. No interaction.

5. **Plan A's HVAC handshake (`hvac_fans.py` additions)** is orthogonal. No interaction.

6. **Plan A's acceptance D2.7 cross-check** ("does the zone-tier per-kind picture
   corroborate the room-tier verdict?") becomes trivially True post-substrate (the per-kind
   pictures AGREE by construction). The acceptance criterion is REWRITTEN post-substrate
   to "the substrate per-kind view records mmwave-only for at least N ticks at trigger
   time" — strictly stronger than today's diagnostic-correlation acceptance.

**Plan-A code the substrate cycle later absorbs/refactors (verbatim — both docs quote
this list):**

1. `RoomCoordinator._recent_occupancy_sources` deque — RETAINED but optionally rebuilt
   from substrate per-kind data.
2. The `STATE_OCCUPANCY_SOURCE == "mmwave"` precondition check — REPLACED with a
   substrate per-kind read inside `presence_fan_recheck.py`'s trigger evaluator. One-line
   refactor; gates can be expressed as "substrate motion AND occupancy False for N ticks
   AND substrate mmwave True for N ticks."
3. Plan A acceptance criterion D2.7 cross-check — REWRITTEN as stated above.
4. NO state-machine code is absorbed. The HVAC handshake, BLE ladder, snapshot/restore,
   pause precedence matrix, BLE-tier drop-authorization gate, and adjacency tier-flip
   all stay verbatim.

**Did the planner consider substrate-first?** Yes. Justification for Plan-A-first:

- Live energy waste is observable today (Exercise Room AC + fan running in an empty room).
  Substrate-first delays Plan A by one full cycle for no Mode-2 win.
- Plan A does not DEPEND on substrate. The room-tier flat-OR precedence at
  `coordinator.py:1416-1420` correctly resolves `STATE_OCCUPANCY_SOURCE = "mmwave"` for
  the Mode-2 trigger. Plan A's precondition is correct today.
- Substrate is the durable cleanup; Plan A is the live fix. Operator preference (Plan A
  first, substrate "right after if the sequence works") matches the engineering reality.

**Recommended sequence:** Plan A → live-validate Mode-2 fix → Plan B (substrate) →
optionally Plan A § P2 (strip v4.7.20 hold) any time after Plan A (the hold strip is
orthogonal to substrate). If Plan A live-validation surfaces noise that the substrate
would fix (e.g., the area-sweep is picking up a fan-sensitive sensor that's confusing
Plan A's mmwave-history precondition in a specific room), flip the order and ship
substrate first. This is unlikely — the failure mode would be a clearly identifiable
extra-sensor-in-zone-tier divergence visible in the substrate_kinds attr — but the
flip is cheap if needed.

---

## Cross-references

- `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md` — companion plan (ships first)
- `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` — v4.7.19 ship; substrate sits beneath
- `docs/planning/AUDIT_occupancy_substrate_consumer_ripple.md` — NEW per-consumer ripple audit
- `docs/Coordinator/PRESENCE_COORDINATOR.md` — invariant honored (substrate is pure state)
- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — updated to document the substrate layer
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — HVAC unchanged (reads room tier)
- Memory: `project_v4_7_19_live.md`, `project_v4_7_18_1_sleep_wake_deadlock.md`, `project_v4_7_20_fan_noise_layer1_live.md`, `project_fan_noise_mmwave_mitigation_backlog.md`
- `docs/BACKLOG.md` Fan-noise entry (substrate is the operator-note-b "context-wide split")
- `docs/TECH_DEBT.md` "Presence — Tier 1 ORs mmWave + PIR" entry (CLOSED by this cycle's discovery/classification unification)

# AUDIT — Occupancy substrate consumer ripple

**Companion to:** `PLANNING_occupancy_substrate_unification.md` (D4).

This per-consumer table traces every read surface affected by the
substrate cycle and records whether behavior is **unchanged**,
**improved**, or **changed**. The verification status notes whether the
ripple is also covered by `quality/tests/test_substrate_backcompat.py`.

The substrate sits BENEATH both the room and zone tiers — it is NOT a
new tier and does NOT supersede either. Per-tier smoothing remains
exactly where it lives today; only the discovery + classification +
state-change subscription set are unified.

## Consumer ripple table

| Consumer | Read surface | Behavior pre-substrate | Behavior post-substrate | Verified |
|---|---|---|---|---|
| HVAC zone aggregator | `coordinator.data["occupied"]` (room tier) | unchanged | unchanged — substrate feeds the room tier's flat-OR input but smoothing pipeline is identical | yes (backcompat test) |
| HVAC defer gate | `check_zone_occupancy_confidence` (enumerates room coords) | unchanged | unchanged | yes |
| House-state inference | `StateInferenceEngine.infer(any_zone_occupied=...)` ← `any_zone_raw_occupied = any(t.raw_occupied for t in self._zone_trackers.values())` (`presence.py:4027-4032`) ← `tracker.raw_occupied` ← `_derived_mode` ← `_room_occupied` ← `_room_provenance` | unchanged | unchanged — substrate feeds `_room_provenance` via `_on_substrate_kind_changed`; downstream composition is identical and freshness is at least as fast (substrate is instantaneous) | yes |
| Guest-room detector | subscribes to `binary_sensor.<room>_occupied` (room-tier output) | unchanged | unchanged — room-tier sensor identity / state / attrs unchanged | yes |
| `OccupiedBinarySensor` D5 attrs | `tracker.provenance_for(room)` + new `substrate_kinds` attr | `tier1_provenance` shape preserved | data quality improves (kinds reflect operator config exactly); new `substrate_kinds` lazy attr surfaces the raw substrate view | yes |
| `_compute_fan_interference_rooms` zone-tier diagnostic | `_room_provenance`, `_fan_on_rooms` | unchanged shape | data quality improves — Jaya-style masking case fixed | indirect (covered by zone-tier integration test) |
| `_audit_provenance_invariants` | `_room_provenance` | invariants hold | invariants hold | yes (existing provenance-split tests still green) |
| FanRecheckManager (v4.7.22, LIVE) | `room_coord.recent_occupancy_sources()` (`coordinator.py:2266`), `room_coord.data["occupancy_source"]` (`presence_fan_recheck.py:494`), `data["occupied"]` / `data["presence_detected"]` | works today | unchanged — substrate feeds `STATE_OCCUPANCY_SOURCE` via the same room-tier flat-OR; the ring + dict reads are untouched. The optional `recent_occupancy_sources()` rebuild-from-substrate is a FUTURE refactor (seam absorb-point 1), explicitly NOT in this cycle. | yes — backcompat test drives a substrate-mediated transition and asserts identical reads |
| Plan A BLE-ladder + Tier-1/2/0 drop-authorization gate (D1.5) | `person_coord.get_ble_tier`, `get_persons_in_room`, adjacency cache | unchanged | unchanged — substrate carries no BLE data; this consumer column is orthogonal by signal class | n/a |
| `test_presence_provenance_split.py` invariants | tracker shape | unchanged | unchanged | yes (pre-cycle tests remain green) |
| Plan A trigger precondition | room-tier `STATE_OCCUPANCY_SOURCE == "mmwave"` | works today | works identically post-substrate; precondition can OPTIONALLY tighten to per-kind raw view (post-substrate path) — out of scope for this cycle | n/a |
| Plan A acceptance D2.7 cross-check | "does zone-tier per-kind picture corroborate room-tier verdict?" | unreliable today (divergence) | reliable post-substrate (kinds agree by construction) — observation only | n/a |

## Notes

The substrate's `_handle_state_change` callback is the SINGLE replacement
for two prior state-change subscriptions:

* `RoomCoordinator._tier1_state_changed` — registered inline in
  `UniversalRoomCoordinator.async_config_entry_first_refresh` (was at
  `coordinator.py:915-967`, registered at `:969-973`).
* `PresenceCoordinator._discover_room_sensors` — registered at
  `presence.py:2250-2256` over the area-sweep set.

Post-substrate, BOTH tiers consume `SIGNAL_SUBSTRATE_KIND_CHANGED`
(room tier in `coordinator.py`, zone tier in
`presence.py:_on_substrate_kind_changed`). The substrate's listener
count equals the deduplicated union of operator-curated CONF-list
entities across all configured rooms; per-tier listener counts drop
correspondingly.

## Listener-count delta

Per the plan's D1 acceptance:

| Source | Pre-substrate | Post-substrate |
|---|---|---|
| Room tier (per `UniversalRoomCoordinator` instance) | 1 `async_track_state_change_event` over `tier1_sensors` (motion + mmwave + occupancy + lux) | 1 `async_dispatcher_connect` on `SIGNAL_SUBSTRATE_KIND_CHANGED` + 1 `async_track_state_change_event` over `[lux]` (lux remains direct — it's not in the substrate's CONF surface) |
| Zone tier (PresenceCoordinator) | 1 `async_track_state_change_event` over the area-sweep set | 1 `async_dispatcher_connect` on `SIGNAL_SUBSTRATE_KIND_CHANGED` |
| Substrate (PresenceCoordinator-owned) | n/a | 1 `async_track_state_change_event` over the CONF-driven canonical set |

For N rooms with `tier1_sensors` count k_i each:

* Pre-substrate state-change listener count = N (room-tier) + 1 (zone-tier, batched).
* Post-substrate state-change listener count = N (room-tier, lux only) + 1 (substrate, batched).
* Net state-change listener delta on the canonical Tier-1 sensor set = 1 batched listener replaces N + 1 batched listeners overall (zone area-sweep removed; room-tier non-lux removed; substrate adds 1 batched).

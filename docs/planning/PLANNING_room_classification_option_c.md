# PLANNING — Room classification unification, Option C: derived read-model (ROOM-CLASSIFICATION-CONSISTENCY-1)

**Card:** ROOM-CLASSIFICATION-CONSISTENCY-1 · **Date:** 2026-09-14 · **Tier:** 1–2 (additive, read-only)
**Status:** operator-approved to plan ("Want me to plan that accessor (Option C)? — Yes")
**Builds on:** D1 documentation shipped (`docs/architecture/ROOM_CLASSIFICATION.md`).

## Goal (operator): achieve unification CHEAPLY, keep the outdoor coercion, don't overthink
Unify the **reads**, not the writes. The scattered flags stay as-is (they are the operator's write
surfaces). Add ONE derived read-model that presents "what is this room?" coherently, without migrating any
consumer.

## Architecture — deliberately NOT a coordinator (the axis the operator flagged)
Contrast with the appliance capability, which IS a first-class coordinator (own observations, own
anomalies, own persisted state → appears under 'Add Coordinator'). **Option C is the opposite kind of
thing and must not be built as a coordinator:**
- It has **no observations of its own** — it is a pure *projection* over existing config surfaces.
- It has **no state to persist** and **no anomalies to raise** — nothing to wire into the anomaly subsystem.
- It drives **no actions** (`evaluate` would be `[]` — but it isn't even a coordinator).

So it will **not** appear under 'Add Coordinator', and that is correct: adding coordinator scaffolding
(enable key, switch, CM menu, AnomalyDetector, metric_baselines) to a stateless derivation would be
over-engineering the exact kind the sweep warned against. Option C = **a helper + a read-only sensor
attribute**, nothing more.

## Institutional context verified (REUSE-or-BUILD per piece — plan-review corrected)
- **No unified accessor exists today** — grep for `get_room_classification` / `RoomClassification` /
  `room_classes` / `get_room_info` returns nothing (not a duplicate). **Host = `RoomSignalInventorySensor`
  (`sensor.py:2615`)** — already a pure lazy config-introspection diagnostic (no dispatch/DB/actuation) with
  a `_config()` merged-dict helper at `sensor.py:2657`. NOT `RoomReconcileSensor` — its
  `extra_state_attributes` returns `{}` on any exception (`sensor.py:2605`), silently swallowing the attribute.
- **Outdoor: REUSE `outdoor_zone_names_snapshot(hass)` (`safety.py:510`)** — module-level, `hass`-only,
  handles both zone shapes (legacy `ENTRY_TYPE_ZONE` + ZM `options["zones"]`), fails open to `set()`, and is
  **NOT the coercion** (it does not touch `safety.py:428` or `:1319`). Do NOT hand-roll a fourth copy of the
  zone-map walk (three already exist: `presence.py:1727`, `safety.py:510`, cached `aggregation.py:4621`).
- **Room→zone resolution: pin `{**entry.data, **entry.options}.get(CONF_ZONE)` (options-WINS)** — matches the
  safety authority at `safety.py:1319-1322` and the user-facing source of truth (`config_flow.py:435`).
  ⚠️ `aggregation.py:745` reads data-first (inverted, Bug Class #14) — that is NOT the model; do not copy it.
- **Infrastructure: read `coordinator._infrastructure_room`, NOT the switch state.** Every real consumer
  reads `getattr(coord, "_infrastructure_room", False)` (`aggregation.py:3522/3539/3589/...`); the switch
  merely writes through to it (`switch.py:5137/5142`). Reach it via `hass.data[DOMAIN][room_entry.entry_id]`
  → coordinator; fall back to `room_type == "infrastructure"` when the coordinator isn't in `hass.data` yet
  (boot). This *dissolves* the reload-window caveat — `_infrastructure_room` IS the collapsed representation,
  so the accessor inherits exactly the authority the consumers see.
- **Other producers** (from `docs/architecture/ROOM_CLASSIFICATION.md`): `room_type` (`CONF_ROOM_TYPE`),
  `CONF_ROOM_IS_GUEST_ROOM` (flag at presence.py:4879), `CONF_WET_ROOM`, `CONF_SHARED_SPACE`.
- **Performance: REUSE the `_outdoor_zones_cache` hass.data cache** (`aggregation.py:4621`, "FIX 5 (B-M1)")
  rather than walking all 46 entries per state write — an uncached entry-walk on a hot read is a defect this
  repo paid down twice (aggregation B-M1 + presence M1). Note its single invalidator:
  `ZoneSafetyAlertSensor._invalidate_zone_configured_cache` on `SIGNAL_ZM_ZONES_UPDATED`
  (`aggregation.py:4641`) — a second consumer inherits that one staleness point (acceptable, documented).

## Deliverable D-C1 — the read-model accessor + one sensor attribute
- **Accessor:** `get_room_classification(hass, room_entry) -> RoomClassification` where
  `RoomClassification = {function: str, flags: list[str], outdoor: bool, infrastructure: bool}` derived by:
  `function`/flags from `{**data, **options}` keys (same keys the real consumers read); `outdoor` =
  `zone_of(room) in outdoor_zone_names_snapshot(hass)` with `zone_of = {**data, **options}.get(CONF_ZONE)`
  (options-wins), reusing the `_outdoor_zones_cache`; `infrastructure` = `getattr(coord, "_infrastructure_room",
  room_type == "infrastructure")` via `hass.data[DOMAIN][room_entry.entry_id]`.
- **One read-only sensor attribute** — expose the `RoomClassification` as a `classification` attribute on
  **`RoomSignalInventorySensor`** (`sensor.py:2615`). Single place to see a room's unified classification;
  zero new entity.
- **No consumer migration.** Existing readers (presence GUEST gate, safety bands, energy exclusion,
  automation auto-off) keep their current reads untouched. Consumers may opt into the accessor later, one
  at a time — never required.

### Acceptance criteria
- **Verify (discriminating):** with **no SafetyCoordinator in `hass.data`** (and `_sensor_room_types`
  unpopulated), `get_room_classification` for the Patio still returns `outdoor: true` — proving it reads
  `outdoor_zone_names_snapshot`, not the coercion. (Fails under a coercion-dependent implementation.)
- **Verify:** for a guest+wet room, returns `{function, flags: [guest, wet], ...}` matching each flag's
  real-consumer read (discriminating: flip one flag → exactly that flag changes). ⚠️ use a **non-bathroom**
  function for the wet flip (bathroom auto-seeds wet at create, `const.py:1234`) so the axes stay separable.
- **Verify:** ZERO edit to any existing classification consumer (a grep/diff over the diff proves additive).
- **Sensor:** `RoomSignalInventorySensor` exposes a `classification` attribute with the four fields.
- **Test:** unit test the accessor against a fixture room set (guest, wet, shared, outdoor-zone, infra,
  plain) — each field correct; **wire-in anchor** — the test reads
  `sensor.extra_state_attributes["classification"]` and asserts field VALUES (not calling the accessor), so
  neutering the accessor call site turns it RED.
- **Live:** post-deploy, the Patio sensor's `classification.outdoor == true` and a guest room shows
  `guest` in flags.

## Non-goals
- NOT a coordinator; no enable switch, no anomaly wiring, no persistence.
- NOT migrating any consumer (that would be Option B churn — rejected/parked).
- NOT touching the outdoor coercion, the GUEST gate, or the infra enum/switch duality.

## Tier / review
Tier 1–2 (additive, read-only projection + one attribute). One adversarial review focused on: the
accessor reads the real producers (not the coercion), zero consumer edits, and the wire-in anchor is
behavioural not a source-grep.

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

## Institutional context verified
- **No unified accessor exists today** — grep for `get_room_classification` / `room_classes` /
  `get_room_info` returns nothing (not a duplicate). Per-room sensors that could host the attribute:
  `RoomReconcileSensor` / `RoomSignalInventorySensor` (`sensor.py:2562/2615`), both `UniversalRoomEntity`.
- **Producers to read** (from `docs/architecture/ROOM_CLASSIFICATION.md`, review-verified): `room_type`
  (`CONF_ROOM_TYPE`), `CONF_ROOM_IS_GUEST_ROOM` (flag at presence.py:4879), `CONF_WET_ROOM`,
  `CONF_SHARED_SPACE`, `zone_is_outdoor` (**zone-scoped**, lives in the zone_manager `zones` map — the
  `Outside` zone is `True`), infra (`switch.infrastructure` runtime + `coordinator.py:336` string).
- **Do NOT read through the safety coercion** (`safety.py:428`/`:1319`) — read `zone_is_outdoor` directly
  from the zone map, so the accessor is above the coercion and the coercion stays untouched (operator: do
  not retire it). This is *how* unification is achieved without touching the live patio-humidity
  suppression.

## Deliverable D-C1 — the read-model accessor + one sensor attribute
- **Accessor:** `get_room_classification(hass, room_entry) -> RoomClassification` where
  `RoomClassification = {function: str, flags: list[str], outdoor: bool, infrastructure: bool}` derived by
  reading the existing surfaces (flags via the same keys their real consumers read; `outdoor` via the
  zone_manager zone lookup, NOT the coercion; `infrastructure` via the switch state with the reload-window
  caveat documented in D1).
- **One read-only sensor attribute** — expose the `RoomClassification` as an attribute (e.g.
  `classification`) on an existing per-room sensor (`RoomReconcileSensor` or `RoomSignalInventorySensor`).
  Single place to see a room's unified classification; zero new entity if hosted on an existing sensor.
- **No consumer migration.** Existing readers (presence GUEST gate, safety bands, energy exclusion,
  automation auto-off) keep their current reads untouched. Consumers may opt into the accessor later, one
  at a time — never required.

### Acceptance criteria
- **Verify:** `get_room_classification` for the Patio returns `outdoor: true` **without** invoking any
  `safety.py` coercion path (the accessor reads the zone map directly).
- **Verify:** for a guest+wet bedroom, returns `{function: bedroom, flags: [guest, wet], ...}` matching
  each flag's real-consumer read (discriminating: flip one flag in config → exactly that flag changes).
- **Verify:** ZERO behaviour change for every existing consumer (the accessor is additive; no existing
  read path is modified). A grep/diff shows no edit to any current classification consumer.
- **Sensor:** the chosen per-room sensor exposes a `classification` attribute with the four fields.
- **Test:** unit test the accessor against a fixture room set (guest, wet, shared, outdoor-zone, infra,
  plain) — each field correct; **wire-in anchor** — the sensor attribute reads the accessor output, and
  neutering the accessor call turns the attribute test RED.
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

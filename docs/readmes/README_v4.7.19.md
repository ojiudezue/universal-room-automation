# v4.7.19 — Presence Tier-1 provenance split + fan-interference Layer-1 diagnostic (observation-only)

**Feature cycle (Tier-2-DB-style, framing-disjoint reviews).** Splits per-room
Tier-1 presence into per-kind provenance and adds an OBSERVATION-ONLY
fan-interference diagnostic. Five reviews total: three Tier-2-DB passes
(A = data integrity, B = migration/signal-chain, C = new surfaces + test
fixtures) plus two final adversarial passes (R1). All CRITICAL + HIGH fixed.
Rebased onto v4.7.18.3 (setup/unload symmetry preserved). Review docs:
`docs/reviews/code-review/` + `presence_provenance_split_DEFERRED.md`.

## The problem — Tier-1 occupancy was a lossy single bool

`ZonePresenceTracker._room_occupied` collapsed motion / mmwave / occupancy into
one per-room boolean. Provenance was lost: once a room read "occupied," nothing
downstream could tell whether mmwave alone said so (the classic fan-stirred-air
false positive) or whether PIR + occupancy corroborated it. That blind spot is
the root of the "disconcerting periodic fan-pause" class of complaints — mmwave
trips on moving air, no other sensor agrees, but the single bool hides it.

## The fix — per-kind provenance + a derived OR view (D2)

- `_room_provenance: Dict[str, Dict[str, bool]]` — per-room, per-kind truth.
  `TIER1_KINDS = ("motion", "mmwave", "occupancy")`.
- `_room_occupied` is now a DERIVED `@property` = OR across the provenance kinds.
  **Back-compat is exact:** every existing consumer reading `_room_occupied`
  sees the same boolean it always did (shim: `tier1_occupied_count ==
  mmwave_occupied_count` while mmwave is the only firing kind).
- Helpers: `_classify_entity_kind` (entity → kind, cached), and
  `_audit_provenance_invariants` (asserts the derived view never disagrees with
  the recorded kinds).
- **Semantics note (R1-H1 honesty fix):** an `occupied=False` write clears the
  WHOLE room bucket — today's discovery path cannot distinguish per-kind
  off-edges (the state-change callback knows only the entity that fired, not its
  type). The derived OR is therefore NOT "strictly stronger" than the old bool;
  it is exactly equivalent for occupancy and additionally exposes provenance.
  Docstrings + planning doc corrected to say so.

## The fan-interference Layer-1 diagnostic (D3) — OBSERVATION ONLY

Flags a room as fan-interference-suspect when ALL hold:
1. A fan is on in the room (`_fan_on_rooms`).
2. Tier-1 provenance shows **mmwave as the sole positive kind** (motion=False,
   occupancy=False, mmwave=True).
3. **BLE absence at room grain** — `person_coordinator.get_persons_in_room(room)`
   is empty, **and**
4. **Camera absence at zone grain** — `any(tracker._camera_occupied.values())`
   is False. The camera signal is PERSON-classified (Frigate
   `*_person_occupancy` / UniFi `*_person_detected`), not motion, and is
   deliberately zone-wide because URA cameras have no per-room routing map
   (documented in-code, R1-H3).

**It writes nothing.** No service calls, no dispatch, no fan/climate actuation —
it only populates diagnostic attributes + `_signal_consensus_inputs
["fan_interference_rooms"]`. Layers 2 (adjacent-room drift hold) and 3
(zone-absent → fan-pause-and-recheck, the actuation rung) are deferred to
`PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md`.

## UI / sensor surface (D5) — attributes only, no new entities

| Attribute | Entity |
|---|---|
| `tier1_provenance`, `last_kind_to_fire`, `fan_on`, `fan_interference_suspect` | `binary_sensor.<room>_occupied` |
| `zones[<zone>].tier1_provenance_breakdown` | `sensor.ura_presence_coordinator_presence_house_state` |
| `fan_interference_active` (house-wide rollup) | same sensor, top-level |
| `signal_consensus_inputs.tier1_occupied_count` (+ `mmwave_occupied_count` shim) | `sensor` (free ride on existing block) |

## Final-pass fix-up (rebased onto v4.7.18.3)

| ID | Sev | Resolution |
|---|---|---|
| C1 | — | Rebased branch onto develop (`cdf152d`, v4.7.18.3). Teardowns preserved; full suite re-run identical to baseline. |
| C2/C3/M1 | MED | `_room_to_zone` O(1) cache replaces per-attr / per-firing walks in `binary_sensor.py` D5 block and `_classify_entity_kind`. |
| R1-H1 | HIGH | Docstring + planning-doc honesty: full-room-clear semantics; dropped the false "strictly stronger" claim. |
| R1-H2 | HIGH | `provenance_for` folds the legacy `"tier1"` sentinel so a `kind=None` True is never dropped from the derived view. |
| R1-H3 | HIGH | Camera-veto documented (person-classified, zone-grain deliberate) — not re-architected. |
| H1 | HIGH | `_fan_entity_to_room` declared in `__init__` + cleared on re-discovery. |
| H2 | HIGH | Fan/camera listener torn down before re-subscribe (no leak). |

## Files changed

| File | What |
|---|---|
| `domain_coordinators/presence.py` | D2 provenance store + derived property + classifier; D3 fan listener + diagnostic; D4 docstring; `_room_to_zone` cache; H1/H2 lifecycle. |
| `binary_sensor.py` | D5 per-room attrs (cached lookup). |
| `sensor.py` | D5 zone-rollup + house-wide attrs. |
| `const.py` | `TIER1_KINDS`. |
| `quality/tests/test_presence_provenance_*.py` + `test_presence_fan_interference_layer1.py` + `test_zone_confidence_doc.py` | 37 tests (AST + behavioral). |

## Migration

**No DB migration. No CONF migration. No new config knobs or entities.** Pure
internal refactor + additive diagnostic attributes.

## Pre-deploy baseline (anchor for post-deploy drift check)

Captured 2026-06-04 ~03:25 UTC on the live instance, BEFORE deploy:

- House state `sleep`, confidence 0.7, `signal_consensus` 0.9 (high).
- `mmwave_occupied_count: 2`, `camera_occupied_count: 0`.
- 5 zones (Back Hallway, Entertainment, Master Suite, Outside, Upstairs) — **all
  `mode: sleep`**.
- Error-log symbol counts: `provenance` = 0, `fan_interference` = 0.

## Live validation (post-restart)

1. **Shim integrity:** `sensor.ura_presence_coordinator_presence_house_state`
   attr `signal_consensus_inputs.tier1_occupied_count == mmwave_occupied_count`
   (baseline mmwave count = 2). This is the back-compat proof.
2. **D5 surface live:** `binary_sensor.<room>_occupied` carries `tier1_provenance`
   (dict of the three kinds); house-state sensor carries
   `zones[<zone>].tier1_provenance_breakdown` and top-level
   `fan_interference_active` (bool).
3. **No drift:** per-zone `mode` distribution within ±5% of the baseline above
   (all 5 zones were `sleep`).
4. **Clean logs:** `ha_get_logs source=error_log` shows zero new lines matching
   `provenance | tier1 | fan_interference | _fan_on_rooms | _room_provenance`.
5. **D3 is observation-only** — expect NO fan/climate state changes attributable
   to URA from the diagnostic. A room appearing in `fan_interference_rooms` is a
   note, not an action.

## Acceptance

```yaml
version: v4.7.19
hypotheses:
  - id: H1
    name: no_provenance_errors
    description: |
      No ERROR-level logs reference the new provenance machinery. Covers the
      derived-property path, the classifier, and the audit invariant helper.
    query:
      kind: ha_log_count
      source: error_log
      search: "provenance"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
  - id: H2
    name: no_fan_diagnostic_errors
    description: |
      The observation-only fan-interference diagnostic raises no errors. The D3
      compute path is wrapped defensive; any ERROR here means a regression in
      the listener lifecycle (H1/H2 fix-up) or the veto logic.
    query:
      kind: ha_log_count
      source: error_log
      search: "fan_interference"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

## Rollback

HACS install v4.7.18.3 — restores the single-bool Tier-1 occupancy and removes
the diagnostic attributes. No persisted state shape changed; clean either
direction.

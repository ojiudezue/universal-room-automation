# v5.108.24: person-awareness layer ship 3a (producer side + leak guard)

Card: PERSON-AWARENESS-READ-API-1 (ship 3a; ships 1 and 2 were v5.108.21 / v5.108.22).

Branch `feature/layer-ship3a`, merged into develop after v5.108.23. Tier 2-DB: reviews A (local correctness, SHIP,
2 LOW), B (lifecycle, SHIP, 3 LOW), C (per-site source mutation: 245 mutations, 39 green sites, all anchored in
14eb9d20; the guard's two wholesale file exemptions narrowed to per-rule, proven by 8 injected leaks going RED). Review
docs: `docs/reviews/code-review/v_layer_ship3a_*.md`. Full-suite name-diff against develop: 0 new failing names,
201 new tests all passing (22368 passed); source-mutation full name-diff and isolated per-file name-diff both CLEAN (0 new failing names).
Orchestrator check before deploy (2026-11-14): the missing-source guard in `dispatch_person_arriving` neutered -> `test_dispatch_rejects_missing_source[None]` and `[]` RED; restored -> 200 passed (ship3a + guard).

Plan: `docs/planning/PLANNING_person_awareness_layer_ship3.md` rev 3.8 §5 (D0-D5, D7) and §17 (guard rulings).
Contract: `docs/planning/CONTRACT_person_awareness_layer.md`. Charter:
`docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`.

## What ships

Producers and readers for the F1-F5 identity model go through one public layer. No behaviour changes: every existing
payload, dispatch order and reader answer is byte-identical (the INV-3A-NOOP invariant, checked by dict-equality tests).

- **D1, F5 is arriving.** `signals.dispatch_person_arriving` (rejects a payload with no source) and
  `PersonArrivingPayload.to_signal()`; the geofence, BLE and camera-face producers call it and keep their
  observation-mode suppression. `subscribe_person_arriving` for readers (first user: step 8). Typed face-latch
  register / read over the same callback list.
- **D2, F1 edges.** `residency.subscribe_person_edges` (sync callbacks, filtered by person and kind) and
  `get_person_edges_since` / `person_edges_truncated_since` (epoch seconds; truncation also true when the window is
  older than the tracker's creation). Crossing vision is the first subscriber, same delivery order as before.
- **D3, F3 crossings.** A per-camera crossing ring with `get_crossings_since`, `get_crossing`, the door roster
  (`door_entry_entities`, `door_neighbours_for_stem`, `door_camera_device_ids` from the registry), and the G3 amend
  primitive `attach_crossing_attribute` / `amend_crossing` on `SIGNAL_EGRESS_RECORD_AMENDED`. The exit backfill moves
  onto it; `SIGNAL_EGRESS_EXIT_BACKFILLED` is deleted.
- **D4, owner setters and reads.** `set_pre_arrival_enabled` (HVAC calls it), `note_face`, the BLE move log
  (`location_moves_since` / `location_moves_truncated_since`), `min_confidence(cls)`, and the class-taking census view
  (`house_census_view(..., cls=...)`; Phone Left Behind reads `cls="house_state"`, always trust).
- **D5, diagnostics download.** A config-entry diagnostics download on the coordinator-manager entry, key
  `person_awareness_layer`, with the layer counters only (F5 sends by source, G3 calls by role, ring and move-log
  sizes, G1 subscribers, truncation counts). No config-entry data, options, entity states or person data.
- **D7, the leak guard.** R1-R14 static rules over the integration with a reasoned allowlist; the allowlist total is
  ratcheted, so a new private read across members fails the suite. Open leaks after 3a are carded (plan §9,
  LAYER-LEAK-CLEANUP-1 / LAYER-LEAK-CLEANUP-PLAN-1).

## Not delivered (plan completion tracking)

- Ship 3b (device-level dead-camera rule) ships separately, Tier 3, after this.
- G6 rest -> G6-ONE-BLE-ROOM-READ-1; leak groups -> LAYER-LEAK-CLEANUP-1 (plan §9).

## Live validation (prospective)

- **D1:** the next real geofence or BLE arrival writes the HVAC `pre_arrival` activity row with that source; the
  diagnostics download shows `f5_sent` for that source >= 1.
- **D2:** the next resident departure still writes the crossing-vision departure-reconcile row; the download shows
  `g1_subscribers` = 1.
- **D3:** Persons Exited Today still renames a backfilled exit on the next BLE departure with a null-person exit row;
  the download shows `g3_calls.exit_backfilled` >= 1.
- **D4:** after the HVAC pre-arrival switch goes off then on, the next BLE arrival writes an HVAC `pre_arrival` row
  with source `ble`.
- **D5:** the coordinator-manager diagnostics download contains `person_awareness_layer` and no config-entry data.
- **Boot:** no URA ERROR or traceback in the log after restart.

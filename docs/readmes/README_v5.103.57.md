# URA v5.103.57 — batch: never-fires sensor detector, EC field clearing, shutdown DB hygiene, EV tripwire test order

Batch of four reviewed branches, merged to develop 2026-10-14. Deploy risk (operator travel rule): **MEDIUM** overall. No presence, guest, HVAC comfort, safety or battery-reserve behaviour changes.

Batch validation: no merge conflicts, no file overlap between the four branches. Full-suite name-diff of the batch (validate/batch-1014 @ 7d18a6ec5 vs develop c55b42b8d): no real regressions. The NEW names were order-dependent tests in the new shutdown test file, since fixed in b3808ad38. 3 GONE names are the EV tripwire tests. Final name-diff of merged develop vs c55b42b8d: see "Pre-deploy gate" below.

## 1. OC-STUCK-SENSOR-GENERALIZE-1 — never-fires detector (MEDIUM: advisory only)
New Optimization Coordinator evaluator `_evaluate_sensor_never_fires_dimension`. It raises a HIGH `SENSOR_HEALTH` finding when a raw motion or occupancy sensor URA consumes has had zero ON transitions over the horizon: 7 days by default, gated on at least 80% availability. Per-entity state (`first_seen`, `last_on_seen`, `unavailable_s`, `unavail_since`) is kept in an HA Store, loaded before the first cycle. Persistence is capped at ≤1 row/entity/24h by the existing `_filter_repeat_sensor_health`. Spec: `docs/planning/PLANNING_oc_stuck_sensor_generalize.md` (Rev 3). Reviews A and B, each with a fix-up, plus a B re-verify (`docs/reviews/code-review/v_oc_never_fires_review_B_reverify.md`).
- B2-R (an outage that spans a restart is charged in full): orchestrator mutation verify 2026-10-14. Dropping the stamp restore on load, or not persisting `unavail_since`, each turns `test_never_fires_outage_spans_restart_fully_charged` red.
- Knobs: `SENSOR_NEVER_FIRES_HORIZON_S`, `SENSOR_NEVER_FIRES_MIN_AVAILABILITY_FRACTION`, `SENSOR_NEVER_FIRES_PERSIST_DEBOUNCE_S`, `SENSOR_NEVER_FIRES_OVERRIDES_S` (module constants; 0 in overrides opts a sensor out).

## 2. EC-OPTIONS-CLEAR-FIELD-NOOP-1 — clearing an Energy entity field now removes it (MEDIUM: config UI)
The EC options save merged over old options, so a blanked entity field kept its old value. Every `EC_ROLE_KEY_SET` field is now clearable through an explicit clear choice, reusing the `clear_grid_fields` pattern. The `ec_role_entity_broken` Repairs text now says that an offline device clears by itself. Review A plus 3 fix-ups, verified.
- Operator action after deploy: clear (or re-point) `energy_solar_follow_grid_fallback_entity`, which still points at the retired `sensor.envoy_stream_grid_power`.

## 3. UNLOAD-SYMMETRY-TASK-HYGIENE-1 — shutdown/teardown DB hygiene (MEDIUM: Tier 2-DB)
- DB writes during HA stop raise `DBShuttingDown`, a `RuntimeError` subclass. They log at DEBUG instead of ERROR, and so do the drain, the flush leftover and a mid-write cancel at stop. Outside shutdown (unload, reload, VACUUM) the old RuntimeError and ERROR path is kept.
- Diagnostics SELECTs use `_db_read()`, so reads no longer queue behind the write worker.
- The coordinator manager's stop-save runs as a zero-arg shutdown job with a 15 s timeout inside stage 1.
- A failed orphan prune no longer disables baseline saves.
- Reviews: A SHIP, B SHIP, C FIX-REQUIRED on test gaps only, fixed in b3808ad38 with 9 tests and 7 mutation drills, all red as expected.
- Carded separately: B-LOW-2 (a setup failure leaves the shutdown job registered; pre-existing).

## 4. EV-TRIPWIRE-TESTS-ORDER-DEPENDENT-1 — test-only (LOW)
`test_ec_ev_toggle_tripwire.py` no longer depends on wall-clock order. 3 previously failing names now pass. No production change.

## Pre-deploy gate
- Conflict-marker grep clean; py_compile clean on all changed files.
- Full-suite name-diff of merged develop (3dbcb7930) vs c55b42b8d: 124 failed / 14770 passed / 3 errors vs a baseline of 129 failing. 1 NEW name: `test_cleared_key_is_a_change_under_normalised_diff`. It passed on its own and failed only in suite order, because a sibling suite left a stub package in `sys.modules`. Fixed in bbc75f2b1: the test compiles `_norm_cm_opt` from the production source and no longer imports the package. Mutation check: making `_norm_cm_opt` always return None turns it red. 3 GONE (the EV tripwire tests).

## Live acceptance
- **Live:** 0 `universal_room_automation` ERRORs in system_log after boot. In particular, none of "Error logging decision", "Error counting anomalies" or "Error saving baselines" at the restart's shutdown.
- **Live:** OC store `.storage/universal_room_automation.optimization.sensor_never_fires_last_on_seen` (or the Store key used) exists within ~2 min of boot, with records for configured motion/occupancy sensors.
- **Live:** no `sensor_never_fires` finding on the first day for a sensor that fired in the last 7 days. The first possible legitimate finding is ≥7 days after a sensor's `first_seen`.
- **Live:** EC options flow opens and saves; the clear choice is present.
- **Live:** anomaly baselines still save and load (diagnostics counts populated after boot).

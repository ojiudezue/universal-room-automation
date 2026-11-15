# Review B: person-awareness layer ship 3a (async, lifecycle, ordering, AWAY latency, setup order)

Branch `feature/layer-ship3a` @ 0b7d5061 (includes merge 6d763d88). Diff base `develop` @ bc4f462b, confirmed
with `git merge-base HEAD bc4f462b` = bc4f462b; three-dot diff, 32 files. Tier 2-DB, operator-elevated.
Plan: `PLANNING_person_awareness_layer_ship3.md` @ 4d6a3daf, §4 (INV-AWAY-LATENCY, INV-ONE-INGEST-AND-LISTENER) and
§5 D1-D5. Contract `CONTRACT_person_awareness_layer.md` rev 2.

Read completely before reviewing: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger),
`SENSOR_FLEET_CLASSES.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger), the contract. This review
re-asserts no ledger claim.

## Verdict: SHIP

No CRITICAL, HIGH or MEDIUM. Three LOW and two notes.

## INV-AWAY-LATENCY: holds

- Geofence path on HEAD: `presence._handle_geofence_change` (`presence.py:5644`) calls `_feed_residency`
  (`:5654`, unchanged position), returns on `old_state is None`, then `handle_geofence_event` (`:5678` / `:5697`),
  which creates the `_run_inference("geofence_arrive" / "geofence_leave")` task (`presence.py:10011`, `:10015`,
  unchanged). The F5 send follows (`:5690`). No await and no new hop sits before inference. The only new code on the
  path is the G1 `_deliver` closure (`residency.py`, `subscribe_person_edges`): two frozenset membership tests and an
  inline `cb(record)`.
- G1 subscribers run synchronously inside `_feed_residency`. `_deliver` is decorated with HA `callback`. HA treats a
  target as a Callback job when `is_callback(target)` (`homeassistant/core.py:347-360`, venv HA 2026.2), and
  `async_dispatcher_send_internal` calls a Callback job inline (`helpers/dispatcher.py`, loop `for target, job in
  list(target_list.items())`). Pinned by `test_person_awareness_layer_ship3a.py::test_person_edges_delivered_synchronously`
  (edge recorded before the trigger), real HA core.
- A raising subscriber cannot block inference or the F5 send, through two independent layers. (1) HA catches
  exceptions per Callback target and logs them (`dispatcher.py`: `try: job.target(*args) except Exception:
  log_exception(...)`), so later targets still run. (2) `_feed_residency` wraps the dispatch in its own `try`
  (`presence.py:5338-5373`), and `handle_geofence_event` and the F5 send run after `_feed_residency` returns.
  The residency row persist (`_persist_residency_event`, `:5367`) runs before the dispatch, so a subscriber cannot
  stop the row either. Pinned by `::test_g1_subscriber_raise_does_not_block_inference` (real HA dispatcher: triggers
  and the one F5 payload unchanged, 2 records kept) and `::test_geofence_triggers_unchanged`.
- HA 2026.11 dispatcher: NOT verified. Only the venv's HA 2026.2 source is on this machine (`find` for another
  `helpers/dispatcher.py` found none). The per-Callback catch and inline call have been in HA since 2024 (the
  comment in the source cites April 2024). If 2026.11 changed it, layer (2) above still protects inference and the
  F5 send, but a raising subscriber could then skip later subscribers. Only crossing vision subscribes today.

## Ordering vs develop

| Path | Develop | HEAD | Evidence |
|---|---|---|---|
| Residency delivery to crossing vision | raw `async_dispatcher_connect(SIGNAL_RESIDENCY_EVENT, _on_residency_event)` | `subscribe_person_edges(..., kinds=EDGE_KINDS)` (`crossing_vision.py:426`). Same single target slot, same records (both kinds; residency produces only `arrival` / `departure`, `residency.py:32-33`), same objects, same time. `_on_residency_event` is already `@callback` (`crossing_vision.py:1204`), so the inline call does not move it off the executor | `::test_crossing_vision_residency_delivery_equal` (identity `is` per record) |
| F5 send vs HVAC / music / security listeners | three raw `async_dispatcher_send(SIGNAL_PERSON_ARRIVING, dict)` | `signals.dispatch_person_arriving` -> the same `async_dispatcher_send` with `to_signal()` (same dict). Listener order is the dispatcher's connect order, untouched | `::test_dispatch_person_arriving_payload_equal[*]` |
| Exit backfill signal vs DB write | send after `await database.backfill_entry_exit_person_id` returns `ok` | `amend_crossing(...)` at the same spot (`camera_census.py:5305-5313`), still after the awaited UPDATE and inside the same `try` | `::test_exit_backfill_display_equal[*]` |
| Ring append vs bus fire vs DB INSERT | bus fire (`transit_validator.py:2474`) -> `_record_crossing` (`:2506`) -> notify, census attach, DB row later | unchanged; the ring append lives inside `_record_crossing` (`:1153-1163`), after the bus fire, inside the existing `try`; a store failure is counted (`:2523`) | `::test_crossing_store_failure_counted` |
| Move log vs location-change fire vs DB | fire `ura_person_location_change` -> DB task | fire (`person_coordinator.py:1129`) -> `_log_location_move` (`:1138`, never raises) -> DB task (`:1143`) | `::test_location_moves_mirror_bus_event` |

## Lifecycle: holds

- G1 subscription: unsub returned and appended to `CrossingVisionShadow._unsubs` (`crossing_vision.py:425-427`),
  called in `async_teardown` (`:445-450`). Idempotent unsub (`done` flag), counter decremented once
  (`::test_subscribe_rejects_coroutine_and_unknown_kind` calls unsub twice, counter 0). No leak on CM reload: the
  connect is on HA's dispatcher, not on the tracker, so a presence reload does not orphan it.
- Face latch: `register_face_latch_callback` returns an unsub that removes exactly that callback from the CURRENT
  list (`signals.py:199-216`); `PersonSightingProducer.async_teardown` calls it (`person_sighting.py:201-206`). Same
  bound-method equality as the old `lst.remove(self._bridge_cb)`. Nothing registered with `FACE_SIGHTING_ENABLED`
  False.
- Exit-backfill readers: both re-pointed connects stay under `async_on_remove` (`sensor.py:5063`, `:5220`).
- `subscribe_person_arriving`: returns HA's unsub; no caller in 3a.
- No new timer, task or `async_call_later` in the diff. `diagnostics.py` registers nothing.
- RAM bounds: crossing ring per egress camera key, count `EGRESS_CROSSING_RING_PER_CAMERA` then age
  `EGRESS_CROSSING_RING_MAX_AGE_S`, pruned on append and on every read (`transit_validator.py:1166-1177`); a camera
  that stops firing keeps at most the count bound. Move log: count `PERSON_LOCATION_MOVES_MAX` then age, pruned on
  append and read (`person_coordinator.py:2293-2304`). Residency `recent` is a `maxlen` deque (`residency.py:91`).
  `LayerCounters` dicts are keyed by source / role (small fixed sets).
- Setup order: every new reader resolves its dependency at call time, never at setup. `amend_crossing` with no
  tracker sends the notice only (`transit_validator.py:1046-1057`); `arrival_edges.door_entry_areas` and perimeter
  `_near_areas` read `hass.data[DOMAIN]["egress_tracker"]` per call; presence F3 delegates return `()` / None with no
  tracker; `get_layer_diagnostics` reads the person coordinator and tracker per call; `subscribe_person_edges` needs
  no presence object (module function, dispatcher signal). HVAC's setter calls `pc.set_pre_arrival_enabled` only
  when the person coordinator exists (`hvac.py:1240-1242`), the same guard as before.
- Diagnostics on a non-CM entry: returns `{}` (`diagnostics.py:34-37`); on the CM entry with no presence, the key
  with `{}`; never raises. Covered by `::test_diagnostics_download_*`.

## Thread safety: holds

Every new mutation (counters, ring, move log, latch list) runs from loop callbacks or coroutines already on the loop:
the geofence state listener (`@callback`), the BLE tick (`_async_update_data`), the egress resolver, the census
backfill coroutine, setup / teardown. `dispatch_person_arriving` and `_send_record_amended` use
`async_dispatcher_send`, which asserts the loop thread (`dispatcher.py`, `verify_event_loop_thread`), the same call
the replaced sends made. No executor path reaches the new code.

## Restart: holds

All stores are RAM and start empty. `person_edges_truncated_since(t)` is True for `t < tracker.created_ts`
(`residency.py`, `edges_truncated_since`; `created_ts` = `setup_ts`, set in `_setup_residency`, `presence.py:5296`)
and True with no tracker. `location_moves_truncated_since(t)` is True for `t < _moves_created_at` (set in the
coordinator constructor, `person_coordinator.py:276`). Pinned: `::test_person_edges_truncated_since`
(`T_SETUP - 1` -> True on an empty ledger), `::test_location_moves_truncated_since`.

## Guard test: deterministic, file-only, but slow

`test_person_awareness_layer_guard.py` imports only `pytest`, `_layer_guard_engine` (`ast`, `re`, `dataclasses`,
`pathlib`, `typing`) and the allowlist module (no imports). It reads source text through
`sorted(root.rglob("*.py"))` (`_layer_guard_engine.py:1220`), writes nothing to disk, and its caches key on
in-process `hash(src)`, so the result does not depend on hash seed or order. Runtime measured here: 107 tests in
29.0 s, `test_guard_matches_provisional_allowlist` alone 10.2 s, each `test_guard_red_on_reverted_site[*]` about
1.2-1.8 s.

## Findings

| # | SEV | Site | Finding | Bug class |
|---|---|---|---|---|
| B-L1 | LOW | `transit_validator.py:967-969` (`nameable` default `MappingProxyType({})`) | `CrossingRecord` can no longer go through `dataclasses.asdict`, `copy.deepcopy` or `pickle`: each raises `TypeError: cannot pickle 'mappingproxy' object` (reproduced in a scratch interpreter). No production caller does any of these today (grep: `asdict` only in `crossing_ledger.py:98` and `residency.py:54`, other types). The first step 7 or diagnostics consumer that serialises a record with `asdict` breaks at run time. Fix: a frozen tuple of pairs, or document "never asdict" on the class and pin it with a test | latent API hazard |
| B-L2 | LOW | `_layer_guard_engine.py`, `test_person_awareness_layer_guard.py` | About 29 s per run of the guard file in one process (10 s for the main test), repeated per xdist worker. That is a large share of a targeted or full run for an AST check. Not a correctness issue. Option: cache the parsed real tree per session (it is already cached per process) or mark the reverted-site matrix as one parametrised scan | suite cost |
| B-L3 | LOW | `transit_validator.py:2474` vs `:2506` | A SYNC listener of `ura_person_egress_event` that calls `get_crossings_since` / `get_crossing` / `get_last_crossing` inside the bus fire does not see the crossing being fired, because the ring append follows the fire. This is develop's order (the plan keeps "bus-then-store"), and no listener reads the ring today (the sighting producer and crossing vision use the event payload). Step 7 consumers must read the payload, or defer, not the ring. Record it in the step 7 plan | ordering seam |
| N1 | note | `get_crossings_since` | No truncation read after a restart or tracker reload: the ring is empty and the caller cannot tell "no crossings" from "lost on restart". The contract §4.1 chooses this explicitly ("no truncation read"); flagged so step 7 does not treat an empty ring after boot as "nobody crossed" | design residual |
| N2 | note | HA 2026.11 dispatcher | Per-target exception catch verified on venv HA 2026.2 only (see INV-AWAY-LATENCY) | unverified dependency |

## Invariant checklist

| Invariant (framing B part) | Result |
|---|---|
| No await / hop before `_run_inference` on the geofence path | PASS |
| G1 subscribers run inline in `_feed_residency`, before the inference task is created | PASS |
| A raising G1 subscriber does not block inference or the F5 send | PASS |
| Residency delivery to crossing vision equal (records, order, time) | PASS |
| F5 send order vs HVAC / music / security unchanged | PASS |
| Exit-backfill notice after the DB UPDATE | PASS |
| Ring append after bus fire, before DB; store failure counted | PASS |
| Every new subscription unsubscribed at teardown; no CM-reload leak | PASS |
| Ring and move-log RAM bounded | PASS |
| Setup order: absent / late presence, tracker, person coordinator | PASS |
| Diagnostics on a non-CM entry returns `{}` and never raises | PASS |
| No non-loop-thread call | PASS |
| Truncation True for `t` before creation (edges, moves) | PASS |
| Guard deterministic, file-only | PASS (slow: B-L2) |

## Tests run (targeted, not the full suite)

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality .venv-ha/bin/python -m pytest -p no:randomly`:
- `test_person_awareness_layer_guard.py`: 107 passed, 29.0 s.
- `test_person_awareness_layer_ship3a.py`, `test_crossing_ledger_wiring.py`, `test_egress_display_reread_and_tz.py`,
  `test_residency_wiring.py`, `test_person_sighting.py`, `test_face_sighting_tripwire.py`,
  `test_lock_face_arrival_corroboration.py`, `test_presence_geofence_late_person.py`: 265 passed, 10.1 s.

## Statistics

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 0 | 0 |
| LOW | 3 | 0 (fix B-L1 in cycle if cheap) |

| Bug class | Count |
|---|---|
| latent API hazard | 1 |
| suite cost | 1 |
| ordering seam | 1 |

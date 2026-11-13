# Person sightings Phase 1 — Review A (local correctness)

Branch `feature/person-sightings-p1`, diff `3348d379..f4455a9d` (merge-base verified = 3348d379).
Plan: `PLANNING_person_sighting_layer.md` rev 11. Framing A only: arithmetic, gates, None handling, edge cases, config
extremes. Cycle test files (person_sighting, tripwire, arrival_rule, access_invariant): 69 passed.

## Findings

| # | Sev | Class | Site | Finding |
|---|---|---|---|---|
| A1 | HIGH | Trip-wire window mismatch (numerator/denominator scope split, #63) | `person_sighting.py:687-720`, `:731-748` | `face_sighting_zero` false HIGH page. Denominator counts census ring entries from any time in the window, including before producer setup and inside the boot exclusion. Numerator counts only emitted interior sightings, and `_emit` boot-drops `ts < setup_ts + 600` (`:567-570`). Repro 1 (run as a scratch test, then deleted): HA restart, healthy hook, 10 named Oji MQTT messages on `family_room` inside the first 600 s, one periodic tick -> `[('face_sighting_zero','HIGH')]`. Repro 2: producer past boot emits normally, presence re-runs `_setup_person_sightings()` (entry reload; the census ring survives), next tick -> HIGH page. A resident on camera after any restart or reload pages HIGH. Fix: limit the denominator to `t >= max(now - window, setup_ts + PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S)`, and add tests for both repros. |
| A2 | MEDIUM | #53 computed-but-not-consumed / kill-switch bypass | `presence.py:1824, 2959-3001`; `person_sighting.py:141-166, 547` | D5 removed the only reader of presence `_face_recognition_enabled` (the v3.19 path was gated by `... and self._face_recognition_enabled`). The new producer never reads it. With the operator's face-recognition switch OFF, source (b) face-sensor changes still emit sightings and write zone `_last_face_recognized` / `_last_face_time` (`:639-647`). Develop gated those displays on the switch. When `FACE_ARRIVAL_INTERIOR_ENABLED` flips, `camera_face` arrivals would also fire with the switch OFF. The plan's INV-PRODUCER falsifier (§2 line 800) assumes the gate exists ("while `face_recognition_enabled`"). Fix: gate `_emit` (or `async_setup`/sources) on the switch, counted as an evidence-source-off skip, and re-read it through the existing `SIGNAL_URA_FACE_RECOGNITION_CHANGED` handler. |
| A3 | LOW | Stale-ts re-emit | `person_sighting.py:420-442` | `async_track_state_change_event` also fires on attribute-only updates (old.state == new.state). Those re-emit with `ts = last_changed` (the original recognition time). This usually self-debounces (`store[dkey]` equals that ts). But if the original change was dropped by suppression or the sentinel/unmapped gates without stamping `store`, a later attribute update emits a sighting with an old ts. Fix: `if old_state.state == new_state.state: return`. |
| A4 | LOW | Day-boundary | `presence.py:8696` (pre-existing clear) + `:5561-5566` | The first transition after the date changes clears `_face_arrival_cooldown`, which now holds both the sighting debounce and the 600 s arrival debounce. A face at 23:58 and another at 00:01 can produce two `camera_face` arrivals. Gated off in Phase 1 (`FACE_ARRIVAL_INTERIOR_ENABLED=False`). Fix: only clear keys older than their window. |
| A5 | LOW | #63 coincidental equality | `transit_validator.py:2025-2039` | Branching uses `identity_confidence == float(CONFIDENCE_HIGH)` / `== FACE_MATCH_CORRELATED_BOOST`. Values today are 0.9 / 0.75 / 0.6, so behaviour is byte-identical to develop. A retune making BOOST == HIGH would silently skip the BOOST ledger append. Fix: have `egress_identity_tier` return a tier label (or compare by branch). |
| A6 | LOW | Input hygiene | `arrival_edges.py:51-57` | `arrival_source_needs_corroboration` raises `TypeError` on an unhashable `source` (list/dict). Not reachable from the three production dispatchers ("geofence", "ble", "camera_face"). If it were reached, the lock regime handler raises and drops the arrival, so it fails closed in effect. Wrap the check or `isinstance(source, str)`. |
| A7 | LOW | Fallback masks 0 | `person_sighting.py:478` | `float(identity_confidence or CONFIDENCE_MEDIUM)` turns 0.0 into 0.6. Unreachable on today's attach paths (0.6-0.9); use an `is None` check. |
| A8 | NIT | Validator | `interior_paths.py:131` | `lag_p90_s: true` passes rule 8 as 1.0 (bool is int). Phase 1 has no runtime reader. |

## Cleared (holds because)

- **INV-ACCESS classifier.** `arrival_source_needs_corroboration` truth table: None→F, geofence/ble→F, camera_face/camera_egress→T, ""/unknown→T. Matches §2. Production sources enumerated: `presence.py:5317` geofence, `person_coordinator.py:1132` ble, `presence.py:5576` camera_face. No existing source is newly held.
- **Security gate** `security.py:2423-2445`. The None regime is rejected. `at_ts` is the sighting epoch ts, the same clock as the lock regime `_ts()` (`security_lock_regime.py:417-418`, epoch). The person entity is reduced to a slug inside `_face_arrival_corroborated`. `face_input_corroborated` returns False after teardown.
- **INV-PROVENANCE.** BLE-only and ble-wins attaches carry `provenance=ble` → the producer skips them (`:455-457`). The face-only attach writes explicit `face`. The bus key is None when `person_id` is None (`transit_validator.py:2188-2190`). The only emitter of `ura_person_egress_event` is `transit_validator.py:2170`, so no backfill path emits.
- **Tier refactor** (`egress_identity_tier`). Same pairwise base_stem predicate, same synthetic re-check over live legs, same BOOST ledger append on the attach path only. The veto path calls the pure helper (no stash, no ledger), matching INV-NOOP Phase 1.
- **INV-LOG.** Every return in `_resolve_egress_face_identity_ex` goes through `_ret`, including `census_unavailable` and `resolver_error`. `_log_egress_outcome` checks `_torn_down` and the kill switch.
- **D2 rule** `presence.py:5520-5585`. Order of gates: interior only, the switch, observation mode, boot, raw state (home / unknown fail-closed), phone-edge gap, debounce. The slug keys match (`person.<slug>` split vs census canonical slug).
- **HVAC counter** by membership (`presence.py:5600-5604`). Room names vs `ZoneState.rooms` (room names, `hvac_zones.py:987`) or a compound split on " + ". It counts once per zone object.
- **Debounce.** It is a fixed window from the first emit; duplicates never extend it. An out-of-order (earlier) ts is still debounced.
- **Path-map loader.** The four outcomes are correct: a read_error on first load falls back to the const, and a later reject keeps the previous file map. `json_file_loader` never raises.

## Verdict: FIX-REQUIRED

Must-fix: **A1** (false HIGH NM page after every restart or presence reload while a resident is on a picked camera).
Should-fix in cycle: **A2** (operator kill-switch no longer gates face-derived display/arrivals), A3.
LOWs A4-A8 at builder discretion.

| Sev | Found |
|---|---|
| HIGH | 1 |
| MEDIUM | 1 |
| LOW | 5 |
| NIT | 1 |

# Plan review — OC-STUCK-SENSOR-GENERALIZE-1 (Tier 2, one adversarial plan review)

Plan: docs/planning/PLANNING_oc_stuck_sensor_generalize.md. Reviewed 2026-10-10 against develop (fe0532918).
HVAC: not touched; HVAC state-of-play doc not required.

**Verdict: FIX-PLAN-REQUIRED.** D2 (stuck-ON) is largely a duplicate of shipped machinery the plan mis-describes. D3 (never-fires) is new and worth building, but its recorder-read design is under-specified for the event loop.

## CRITICAL
**C1: D2 duplicates the room-level P22 continuous-stuck detector. Operators would get the same stuck sensor reported two or three times.**
- coordinator.py:3065-3072 tracks `_sensor_on_since` for every room `motion_sensors`, `mmwave_sensors` and `occupancy_sensors` entry. coordinator.py:2208-2234 (`_p22_stuck_sensor_set`) flags a sensor at `_stuck_sensor_hours`=4.0h (coordinator.py:364). coordinator.py:3120-3135 labels it `"continuous"` and fires `_fire_stuck_sensor_nm` through `_stuck_signal_nm.fire_stuck_signal` with a per-day latch. It is persisted across restarts (coordinator.py:2235-2363), and `_is_sensor_on` treats unavailable/unknown as off (coordinator.py:2861-2866), so it already breaks on unavailable.
- The plan says P22 "addresses a different problem (per-room duty-cycle)". That is wrong: P22 has both a continuous kind and a duty-cycle kind.
- D1 enumerates exactly the same keys (CONF_OCCUPANCY/MOTION/MMWAVE_SENSORS) plus the exterior cameras. Exterior cameras are already covered twice: OC `camera_stuck` (optimization.py:1921, kept per PICK 3-A) and census `get_stuck_cameras` / CONF_STUCK_CAMERA_HOURS (camera_census.py:2945). Both feed `sensor.ura_stuck_signal_watchdog` (sensor.py:5323-5351).
- Concrete repro: a mmwave sensor pinned ON for 13h fires P22 NM at 4h, then a new OC `sensor_stuck` HIGH at 12h. A perimeter camera ON for 13h hits `camera_stuck` at 30 min, `sensor_stuck` at 12h, and the census stuck list.
- **D2 as written adds zero new coverage.** Fix the plan in one of two ways:
  - (a) Drop D2. Make OC `sensor_stuck` a house-level, entity-keyed *mirror* that reads `coord.get_stuck_sensor_kinds()` (the producer the watchdog sensor already uses), so P22 stays the only detector.
  - (b) Restrict D2 to entities NOT covered by P22/camera_stuck/census. The resolver would then have to source something those don't see; today nothing qualifies.
- Either way, rewrite the extend-vs-new verdict and the institutional-context row for coordinator.py. Add an explicit "no-double-surface" acceptance criterion: for one stuck entity, the count of NM-pathway emissions across P22 + camera_stuck + OC is at most 1 per day.

## HIGH
**H1: D3 recorder read on the event loop and boot burst are under-specified.** OC uses no recorder anywhere (grep `recorder|get_instance|async_add_executor_job` in optimization.py returns 0 code hits). `history.state_changes_during_period` is a blocking sync DB call. The plan must state:
- (i) Call it via `get_instance(hass).async_add_executor_job(...)`.
- (ii) Use one batched multi-entity call per tick (`entity_ids` list, `include_start_time_state=False`, no attributes), not one call per entity. ~500 entities × 7d on the first post-restart tick is a recorder-executor burst. The "1h TTL" in D5 bounds the steady state, not the cold start.
- (iii) A recorder-not-ready / boot-settle skip.
- (iv) A test that fails if the call runs on the loop.

A cheaper producer avoids the recorder entirely: in-memory `last_on_seen` from live `last_changed` plus boot time, firing only after the horizon has elapsed since OC start. Price this alternative in the plan.

**H2: the never-fires gate does not exclude unavailable room sensors.** The camera gate requires availability, but the room gate only requires "another sensor in the room fired". Repro: a room mmwave unavailable for 8 days while room motion fires produces both a `sensor_health` unavailable finding (optimization.py:2228-2257) and `sensor_never_fires` for the same eid. Fix: the gate requires the current state not in {unavailable, unknown}, and requires the entity to have been available for at least most of the horizon. Add a test for this.

## MEDIUM
- **M1: the aggregate filter is wrong-keyed.** URA entities are not named `universal_room_automation_*` by entity_id. Use the entity registry: `er.async_get(hass).async_get(eid).platform == DOMAIN`, and treat no registry entry as "include, log". Same fix for unique_id. The `anyone_home` AC test is unrealistic because room CONF lists are the only input. Test instead a room whose CONF_OCCUPANCY_SENSORS contains a URA zone/room occupancy binary_sensor.
- **M2: the suppression table is wrong about discharge.** Recovery clears `_sensor_health_last_persisted` only for `("sensor_health", room, eid)` keys (optimization.py:2265-2270). New `sensor_stuck` / `sensor_never_fires` keys would not be cleared, so a re-stick within 24h of recovery fires a finding (and NM) but persists no DB row. Either clear the key on the evaluator's OFF/recovery branch, or correct the table.
- **M3: the dedup_key format breaks the invariant's "one per entity" claim if camera_stuck stays.** `("camera_stuck", cam_key)` and `("sensor_stuck", eid)` are distinct keys for the same physical sensor, so `_notify_dedup_state` (optimization.py:4650) and the persist filter do not merge them. This is moot if C1 is fixed via mirror or exclusion.
- **M4: the falsifiable invariant says "exactly ONE ... per episode per day".** With the midnight latch clear, a 30h episode fires twice. State it as "at most one per (entity, local day)" and name the DST test explicitly. The plan mentions DST for Reviewer D but lists no test.

## LOW
- L1: Line refs have drifted: camera eval is at 1921, `_exterior_person_sensors` at 2182, sensor_health at ~2210, `_filter_repeat` at 4149, the evaluator tuple at 966. These are not substantive.
- L2: No tie to the in-review `fix/stuck-sensor-warn-once` (33b730db4, coordinator.py-only, boot INFO naming latched sensors). There is no code collision, but it is the same P22 surface C1 builds on, so sequence this cycle after that branch merges.
- L3: The D4 "debug log shows per-evaluator timing" check is not discriminating. Prefer counts per evaluator.
- L4: Knob ladder is complete (4 numbers, rung + why, 0 = kill-switch). Fine. Note that P22's 4h threshold and the new 12h threshold are two thresholds for one concept. That is a Bug Class #63 smell and goes away with C1.

## PICK adjudication
| PICK | A safe autonomously? | Note |
|---|---|---|
| 1 threshold (12h universal vs per-class) | Moot for room sensors under C1. If D2 survives, A is safe. | P22's 4h already governs. |
| 2 no Store persistence | Yes for D3. | P22 already persists; restart cost is bounded. |
| 3 keep camera_stuck | Yes, but it creates a triple surface unless C1 is fixed. | Needs C1 resolution first. |
| 4 classes {motion, occupancy} | Yes. | B needs a baseline the plan doesn't have. |
| 5 never-fires 7d | Yes. | 72h raises false positives; this is policy-light. |

None of the PICKs needs the operator once C1 is resolved. **C1's direction (mirror vs drop D2) is a scope change, so page the operator** if (a) and (b) are both rejected.

## Tier
Tier 2 is correct. There is no schema/DAO change and the shared NM/persist paths are reused unchanged. Reviewer B's framing must explicitly own the recorder-executor / boot-burst items (H1). Elevate to 2-DB only if the fix to M2 touches `_filter_repeat_sensor_health` itself; that is a shared primitive with a load-bearing docstring.

## Must-fix in plan before build
C1, H1, H2, M1, M2, M4.

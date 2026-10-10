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

---

# Re-verify (Rev 2) — 2026-10-10, against develop fb60aef91, PICK A treated as chosen

**Verdict: FIX-PLAN.** Rev 2 closes C1, H1, M1, M2 and M4. **H2 is closed in a way that never fires under PICK A.** The availability accrual is in-memory and resets on restart. At the measured 16 restarts in 7 days (mean uptime about 10.5h), the gate needs 0.8 × 7d = 5.6d of accrued availability since the last boot, so it can never pass. The table at Rev 2 "Suppression / discharge", row `_sensor_available_since`, admits the reset and calls it "a conscious cost". That reasoning only held for pure in-memory; under PICK A it makes D3 permanently dormant. The plan's own "D3 ships dormant" warning applies again.

## 1. Prior findings
| ID | Closed? | Rev 2 evidence |
|---|---|---|
| C1 | YES | "Drop D2 entirely" + parked list with a reproduced-miss revival trigger. The no-double-surface clause is in the invariant. |
| H1 | YES | "No recorder reads in v1. No `hass.data[recorder]` dependency; no executor jobs." Non-goals repeat it, and the Reviewer B grep is assigned. |
| H2 | **LEAK** | The gate text is correct (state not unavailable/unknown AND accrual ≥ 0.8·horizon), but the accrual store resets on restart. See F1. |
| M1 | YES | The D1 / "Rev 2 M1" section adds the registry `platform == DOMAIN` check and two named tests. Minor inconsistency: D1 says "log at debug" and the M1 section says "WARN". Pick one (F6). |
| M2 | YES | Evaluator-local pop of `("sensor_never_fires", eid)` keys, with test `..._resilence_within_24h_persists_a_row`. The shared helper is untouched. |
| M4 | YES | "at most one ... per sensor per local day" + named DST fall-back test. |

## 2. PICK A Store design
Precedent `coordinator.py:2239-2283` (`_async_load_stuck_state`) and the 2310-2343 save use `Store.async_delay_save(..., 60.0)`. HA flushes pending delay-saves at final write, so the precedent needs no stop listener. **The precedent does not face the same issues.** It persists stuck-ON `_sensor_on_since`, and its MED-1 guard requires a live-ON re-observation before acting, so it has no first-boot-floor problem and no availability accrual. It also never prunes vanished eids (harmless there).
- **F1 (HIGH): accrual must persist, or the gate must be redefined.** Fix: persist per-eid `{first_seen, last_on_seen, unavailable_s_in_window}` in the same blob, with downtime not counted against availability. The better option drops the accrual counter and instead requires (a) the current state is available and (b) the recorded *unavailable* seconds since `max(first_seen, last_on_seen)` are ≤ (1-0.8)·horizon. Unavailable spells are captured by the listener and persisted, and HA-down time counts as neither. Test: `test_never_fires_fires_across_frequent_restarts` (simulate 16 restarts over 7d with a Store round-trip each time, and assert one finding).
- **F2 (HIGH): first-ever boot / new entity floor is ambiguous.** "horizon clock = max(restored_last_on, oc_tracking_start_for_entity)" re-floors to *this boot* when `oc_tracking_start` is per-boot, which brings back the dormancy. Fix: persist `first_seen[eid]` (written once, the first time the eid appears in D1) and use the clock `max(first_seen, last_on_seen)`. With no Store, first_seen = now, so there is no immediate fire on first boot. Test: `test_never_fires_no_store_first_boot_does_not_fire`.
- **F3 (MEDIUM): vanished entities are not specified.** Fix: prune any eid not in the current D1 resolution at load/evaluate time, so the blob cannot grow without bound. If the eid reappears, first_seen re-floors.
- **F4 (MEDIUM): the debounce/flush mechanics are wrong-shaped.** "≤1 write per entity per hour" plus "flushed on `homeassistant.async_stop`" is not how Store works, and the precedent does neither. Fix: use `store.async_delay_save(provider, SENSOR_NEVER_FIRES_PERSIST_DEBOUNCE_S)` (whole-blob debounce), which HA flushes at final write. Keep the knob, reworded as a blob-level delay. Note that the delay must be short enough that the restart cadence cannot drop writes: a pending delay-save IS flushed on clean stop but lost on crash. Use 60-300s like the precedent, not 3600.
- **F5 (MEDIUM): wrong lifecycle hook.** The plan says "one restore in `async_added_to_hass`", but OC is a coordinator, not an entity. Fix: load in OC setup, BEFORE the first `_cycle_unsub` tick is armed (optimization.py:876). The evaluator also returns `[]` until loaded.

## 3. Recorder / lifecycle
No recorder or executor use remains (H1). **Unsub is not stated.** `async_track_state_change_event` on the D1 list must append to `self._unsub_listeners` (Bug Class #50; the pattern is at optimization.py:736/881). D1 resolution changes after an options edit also need a re-subscribe policy (rebuild on reload is acceptable; say so). The plan only lists this as a Reviewer B question. F7: add it to D4 as a requirement plus a test (`test_never_fires_listener_unsub_on_unload`).

## 4. AC / invariant
The invariant is falsifiable and the ACs discriminate (count per evaluator, URA-platform drop, unavailable-8d → 0 findings). The "fires across restarts" AC is MISSING, and it is the one that discriminates PICK A working from PICK A dormant. F1's test supplies it. Also fix the stale "Only present if operator picks" wording in the knob table and the "(if Pick A)" hedges now that A is chosen.

## Must-fix before build
F1, F2, F4, F5, F7 (with F3 and F6 in the same edit).

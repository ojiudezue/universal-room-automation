# Plan review: crossing vision Phase 3, final spot-check (2026-11-15)

Diff: `git diff 25b30764 5f602cd3 -- PLANNING_crossing_vision.md PLANNING_census_deconfliction.md PLANNING_vision_interior_sightings.md`.
Answers: closure review `plan_review_crossing_vision_p3_closure_2026_11_15.md` and harmonization C1/C3/C5/C7/C8/C2.
Presence-touching (P3-D8 reads room stuck exclusion); verified against code on develop.

**Verdict: PLAN-FIX-REQUIRED** (one HIGH, small text fix).

## HIGH

**H1. P3-D8 reads the wrong getter: `get_stuck_sensor_kinds()` is a label map, not the exclusion set.** (Bug class #63 coincidental equality / sensor-fleet class.)
Plan `PLANNING_crossing_vision.md:878-881` treats "in `get_stuck_sensor_kinds()`" as "stuck-excluded". Code says otherwise:
- `coordinator.py:3801-3808`: a duty-cycle hit is labelled `"dutycycle"` in `_stuck_sensor_kinds` but deliberately NOT excluded ("a sleeping person is ~100% mmWave duty cycle with zero PIR, and excluding would vacate sleeping bedrooms"). Exclusion only follows `_promote_dutycycle_to_exclusion` (`:3813`).
- `coordinator.py:3073-3084`: chatter is labelled `"chatter"` in shadow mode too, with the comment "SHADOW: DO NOT promote; DO NOT add to stuck_sensors".
Repro (legal config, default chatter mode or the duty-cycle notify-only path): house AWAY-by-phone or not, a resident asleep in a bedroom whose mmWave reads `on` with ~100 % duty cycle → label `dutycycle` → P3-D8 drops it from `held` → if no other holder, the empty-house anchor fires on an occupied house. That is the exact failure the room code refuses to cause.
Fix in plan: use the room's real exclusion set through the existing public getter `camera_input_room_quarantined(input_eid)` (`coordinator.py:2790-2796`, wraps `_exclusion_set.is_excluded`), optionally narrowed to stuck clients (`p22_continuous`, act-mode `chatter`, promoted duty-cycle) via `SensorExclusionSet.clients_for` (`domain_coordinators/sensor_exclusion.py:145`) if a public wrapper is added. Add test `test_dutycycle_label_without_exclusion_still_holds` and `test_shadow_chatter_still_holds`; mutation: switch back to the kinds map → those go RED.
Reachability: the room-coordinator sweep pattern exists (`aggregation._get_room_coordinators`, used at `sensor.py:5724-5733`); the plan should name it (or the substrate's room mapping) as the route from `crossing_vision` and state the guard delta (zero rows expected: the guard has no `crossing_vision`→coordinator rule today; confirm in build).
Dead vs stuck: distinguishable with existing data. `_held_inputs` already has `state` and the stream view per entity (`crossing_vision.py:1170-1176`); P3-D8 applies only to `state == "on"` with view None. Holds.

## MEDIUM

**M1. Anchor-block deadline arithmetic is wrong as written.** `:757-758`: "`EVENT_END_WAIT_S` 120 + `TIMEOUT_S` 90 = 320 s". 120 + 90 = 210. The worst outcome bound stated at `:680` is E + 45 + 120 + 90 = E + 255. Either reading (E + 110 + 210 = E + 320, or E + 110 + 320 = E + 430) exceeds E + 255, so it is safe, but a builder will code one of two numbers. Write it as `E_primary + TERM_HOLD_S (110) + EVENT_END_WAIT_S (120) + TIMEOUT_S (90) = E + 320 s`, and assert at setup that it is ≥ `EGRESS_ENTRY_WINDOW_SECONDS + EVENT_END_WAIT_S + TIMEOUT_S`.

**M2. `PASS_ROUND_TRIP_MIN_N` = 5 cannot demonstrate `MERGE_MAX` = 0.10.** `:618-622`, knobs `:988-989`. At N = 5 one merge is 0.20 (fail) and zero merges has a Wilson 95 % upper bound ≈ 0.43. The gate passes on a point estimate of 0/5, which proves little. HOLD at < 5 is correct; either raise MIN_N (≈ 20-30 for an upper bound near 0.10) or state that the merge gate is a point-estimate bar and name the residual risk. Operator call; record it.

**M3. Claimed `pass_key` consumers not reflected in their plans.** `:568`, `:899-900` say interior D5 and NVR W2 consume `pass_key`; `PLANNING_vision_interior_sightings.md` has zero `pass_key` hits. Either add the consume line to the interior plan (D5) or drop it from the consumer list. NVR W2 is covered by the pending rewrite (harmonization `:322`).

## LOW

- **L1. P3-D9a lifecycle unspecified.** The tracker gains its first Frigate consumer (`register_frigate_consumer`, `frigate_ingress.py:582`; no hit in `transit_validator.py` today). Name the unsub in tracker teardown, the ring bound/retention, and a test (`test_tracker_frigate_consumer_unsubscribed_on_teardown`).
- **L2. P3-D9b ordering.** The pass check must run before the dedup `return` at `transit_validator.py:2428-2434`, so `pass_identity` is computed before the dedup block, not at record creation (`:2515`). P3-D9a stamping at `:2515` is fine; say so for D9b.
- **L3. Merge sentence.** "The interior branch's 259 means no change; whichever merges second takes 260 if P3-D3 landed first" (both plans). Clearer: "Only P3-D3 changes the total (259 → 260). If interior merges after P3-D3, it keeps 260; it never resets to 259."
- **L4. P3-D9a guard delta** not stated (new consumer registration in `transit_validator.py`). Expected zero; state it.

## Checked and holding

| Item | Result | Evidence |
|---|---|---|
| CrossingRecord created after direction | PASS | direction resolved `transit_validator.py:2401-2423`, dedup `:2425-2438`, record `:2515` |
| Tracker can know the event window | PASS | resolution runs at E + `ENTRY_WINDOW_SECONDS` (45, `const.py:3381`; scheduled `:1664`, `:1715`); Frigate `new` arrives at event start, so `start` is known; `end is None` handled by the plan's open-window rule (`:572-574`) and measured in P3-D0 (d). No data the tracker lacks, given the new ring |
| New bus key impact | PASS | all `ura_person_egress_event` readers use `event.data.get(...)` (`sensor.py:4928`, `:5075`, `:5163`, `:5279`); no strict-shape reader in person_sighting / perimeter_alert / presence / crossing_vision |
| Frozen CrossingRecord + new field | PASS | `@dataclass(frozen=True)` `:945`; defaulted field set at construction is valid; not added to `_CROSSING_AMENDABLE_KEYS` (`:684-685`) |
| Contract update | PASS | orchestrator amends §2.3/§4.2 once (C7) |
| Guard counts | PASS | live: `LAYER_ALLOWLIST_TOTAL` 259, `_PROVISIONAL` 259 (`person_awareness_layer_allowlist_PROVISIONAL.py:19,26`), `len(A.ROWS)` 231 asserted at `test_person_awareness_layer_guard.py:62`; plan 231→232, 259→260 both totals. Note the same assertion is duplicated in `test_allowlist_is_final_post_census_p2` (`:62` is it) |
| P3-D6 tracker verdict | PASS | TRACKER-READY/BELOW-BAR defined with Wilson LB and N; F-LEAD needs the ledger source's verdict |
| P3-D5 DAO | PASS | `ended_at`, `attrs_json` exist (`database.py:2005-2010`); read connection, `(count, ok)` error shape, conditional index; isoformat bounds match writer |
| Label uniqueness | PASS | P3-D8 = stuck exclusion only; tracker = P3-D9 / D9a / D9b throughout |
| One clean document | PASS except M1 and L3 text |

Must-fix before approval: H1, M1, M3. M2 needs an operator decision recorded in the plan.

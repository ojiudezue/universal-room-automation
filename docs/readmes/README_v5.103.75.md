# v5.103.75: paused rooms stop occupancy lights and fans

Card: ROOM-OVERRIDE-SWITCH-FORGOTTEN-1.

Plan: `docs/planning/PLANNING_paused_room_occupancy_lights_fans.md`. The plan was reviewed, with findings R1–R6 folded in.

**Tier 2** with 3 framing-disjoint reviews: `docs/reviews/code-review/paused_rooms_review_{A,B,C}.md`.

**Deploy risk: LOW.** It is a gate-only change. When no room is paused, behaviour is byte-identical to before.

## Operator intent

> "Paused rooms should stop with lights and fans automation based on occupancy. Blinds down, house state, venting are fine. I just didn't want it turning off lights when paused."

2026-10-19, the operator answered YES to two questions:
- Stop all HVAC-side fan automation, including sleep-onset.
- Accept that a paused room can still be marked vacant, so its zone can retreat.

## What "paused" means

A room is paused when its Automation switch is OFF or Manual Mode is ON. The shared predicate is `const.room_automation_paused`.

| Situation | Reads as |
|---|---|
| Switch reads unavailable or unknown | Paused (the room tier already treats it this way) |
| Missing room coordinator | Enabled |
| Missing switch | Enabled |
| Error while checking | Enabled |

## Gated sites

These now skip paused rooms:
- the zone vacancy sweep (lights, night lights and fans): `hvac.py`;
- HVAC comfort fans (F1). The room's tracking is released on every paused tick, and nothing is written: `hvac_fans.py`;
- the sleep-onset fan (F3): `hvac_fans.py`;
- the pre-arrival fans, on (`hvac_predict.py`) and off (`hvac.py`);
- the fan recheck: a new `room_paused` veto at arm time and in the arm-delay re-check;
- the 3 s exit-verify retry: `coordinator.py`.

**Exceptions (still run in paused rooms):**
- the smoke/CO safety stop;
- `turn_off_all_managed`;
- the fan recheck's restore of a fan it paused.

**Unchanged:** blinds, house state, venting, humidity fans and AI rules.

## Accepted consequences

1. **The fan-noise backstop (D2) can still mark a paused fan room vacant,** so its zone HVAC may retreat. The operator accepted this.
2. **A paused room loses the recheck's VACATED release.** In paused rooms with no fan-immune sensor (Media, GB1 and GB2 today), a running fan can hold the room and its zone occupied. The hold lasts until the 4 h stuck-sensor rule or the P24 failsafe fires. This follows from the operator's ruling.
3. **Fans URA turned on before a pause stay on until unpause.** On unpause, URA adopts them under the manual-ON hold.

## Tests

- `test_paused_room_gates.py` (17 tests), plus the D2 backstop test in `test_mmwave_fan_demotion.py`.
- **Full name-diff** at 67a9f7442 vs fa3db9a59: **CLEAN, 0 NEW / 0 GONE**.
- **Mutation testing:**
  - Builder drills: 13 sites.
  - Review C: 17 gate mutations, all RED. Its 3 surviving mutations were closed by the 25188ad02 tests.
  - Orchestrator: neutered the sleep-onset gate, and `test_sleep_onset_skips_paused_room` went RED. Restored.

## Live validation (replace with a Validated table)

- **Load:** manifest v5.103.75, all entries loaded, no URA ERRORs.
- **Sweep skip:** an INFO "skipped paused room" log line appears when a zone sweep passes a paused room. If no sweep occurs, record this as not yet exercised.
- **Recheck veto:** the fan recheck state sensor shows a `room_paused` veto count for a paused room with a fan on.
- **No light-off in paused rooms:** a one-shot recorder query finds no URA-originated light turn_off in a paused room after the restart.

Restart: installed, **restart held**. It goes with v5.103.73 and v5.103.74.

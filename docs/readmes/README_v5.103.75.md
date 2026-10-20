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

## Validated 2026-10-20

Restarts carrying this build: 02:05 CDT (07:05:40Z, recorder run 1199) and 09:59 CDT (14:59:25Z, run 1200). Evidence comes from the 09:59 boot unless marked. Read-only checks (ha-mcp, the recorder DB, the URA DB via `ssh ha`).

| Criterion | Result | Evidence |
|---|---|---|
| Install and load | PASS | `/config/custom_components/universal_room_automation/manifest.json` version `v5.103.75` (it carries .73 and .74). `ha_get_integration`: 50/50 URA entries `loaded`. `system_log` ERROR filter for URA: 0 entries. error_log after boot has WARNING-level boot transients only (sensors unavailable for 60s, census cameras unavailable, HA deprecation notices). |
| Sweep skip INFO line | Cannot observe | The "skipped paused room" line is INFO and the URA logger is at WARNING, so it never reaches the log. Proven in-suite only. Use the next criterion instead. |
| Recheck veto `room_paused` | PASS | `sensor.jaya_bedroom_jaya_bedroom_bedroom_4_fan_recheck_state` `fan_recheck_veto_counts = {room_paused: 2}` (09:59 boot); `{room_paused: 5}` at the 02:05 boot. Jaya Bedroom is paused (`switch.jaya_bedroom_automation` = off). |
| No URA light-off in paused rooms | PASS | Recorder, since 07:05:40Z: `switch.switch_sonoffm4rm_matter_jayabedroom` (the room's only configured light) went on 11:48:43Z and off 12:14:12Z. The off state carries no user context and no parent context, and no `call_service` or `ura_action` event shares its context. A recorder search for any `call_service`/`ura_action` with `turn_off` targeting `jayabedroom` since restart returns 0 rows. So the off came from the device itself (physical or Matter report), not from URA. Scope: Jaya Bedroom, the paused room seen in this pass. |

Restart: installed, **restart held**. It goes with v5.103.73 and v5.103.74.

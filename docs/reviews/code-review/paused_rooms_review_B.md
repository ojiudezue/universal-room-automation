# Review B: paused rooms (ROOM-OVERRIDE-SWITCH-FORGOTTEN-1)

Framing B: cross-coordinator integration, lifecycle, precedence, no-flap. Owns plan finding R3.
Branch `fix/paused-room-lights-fans` @ `67a9f7442`, base `fa3db9a59` (three-dot diff).
Read completely first: HVAC_ARCHITECTURE_STATE_OF_PLAY.md, PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md, SENSOR_FLEET_CLASSES.md, the plan.
Tests run (targeted only): `test_paused_room_gates.py` + `test_mmwave_fan_demotion.py`, 39 passed.

## Findings

| # | Sev | Site | Finding |
|---|---|---|---|
| B-M1 | MEDIUM (doc, operator-visible) | `presence_fan_recheck.py:552-556` (veto) with `coordinator.py` ~5720 ("fan-recheck released occupancy") | **R3 is NOT the only zone-side consequence.** The veto also removes the recheck's VACATED release of a fan-held phantom. In a paused room where D2 fails closed (no fan-immune witness, e.g. Media / GB1 / GB2 with MS600-only motion bits, per SENSOR_FLEET_CLASSES), nothing breaks a fan-on radar hold any more. The room stays `occupied`, so `hvac_occupied` stays set and the zone does not retreat until the 4 h stuck-sensor rule or the P24 failsafe fires. Repro: Media (paused, zone_2) by day, a person runs the fan and leaves, and the MS600 Matter radar holds on fan noise. Before the change, the recheck armed, paused the fan, VACATED, released occupancy and left the fan off (C1a). After it, veto `room_paused` → no probe; D2 fail-closed → zone_2 holds Home. This drift goes the opposite way from R3 (it holds rather than retreats). It follows directly from the operator ruling (a probe turns the person's fan off), so no code change is needed. But INV-Z as written ("byte-identical EXCEPT via the D2 backstop") is false. **Fix:** restate INV-Z in the plan and in PRESENCE §4.5 / §6 item 3 and HVAC §4.2b, and add a README one-liner: "a paused fan room loses the recheck's phantom release; in a room with no fan-immune witness its zone may hold conditioning until the stuck-sensor rule". |
| B-L1 | LOW (pre-existing class, newly reachable) | `hvac_fans.py:2079-2091` snapshot, `presence_fan_recheck` arm | Tracking is cleared on every paused tick. After an unpause, the recheck (60 s driver) can arm and snapshot before the next `FanController.update` adopts the running fan. The snapshot then reads `is_on=False`, so the pause OFF is skipped, the probe runs with the fan on (an inconclusive recheck), and the restore writes nothing. There is no wrong write and no flap. The same window already exists for any externally lit fan before adoption. Accept. |
| B-L2 | LOW (accepted by plan §5) | `hvac_fans.py:741-825` adoption | On unpause, a fan URA itself lit before the pause, or that the restore re-lit, is adopted as `trigger=external` with a manual-ON hold. It then stays on for the hold length instead of being temp-managed. Same as a Fan-Mode hand-back. The README already plans "fans URA lit before the pause stay on"; add "and up to one manual-ON hold after unpause". |

## Cleared (holds because…)

- **R3 D2 backstop is real and pinned.** `is_recheck_eligible` has exactly one consumer (`coordinator.py:4378-4381`). `test_paused_room_d2_backstop_not_deferred` drives a REAL `FanRecheckManager` through the D2 block, with an enabled control that defers. The lights cannot flap: the room tier is paused and the sweep skips the room.
- **No other zone-side reader of FanController tracking.** `_room_fans` outside `hvac_fans` is read only for the recheck's manual-hold / cooldown fallbacks (`presence_fan_recheck.py:1554,1614`; the release never touches those fields) and for `get_fan_status`. `active_fans` is display-only (`hvac.py:8202`). `_fan_assist_active` is a house-level computation, not a per-room tracking read. `swept_count` only feeds a log line (`hvac.py:6919`). `vacancy_sweep_done` / `_vacancy_sweeps_today` are set by the callers and are unchanged.
- **Fake cooldown.** The level release runs before the external-change sync (`hvac_fans.py:651-666`) on every paused tick. It does not touch suppress-until, hold or cooldown (`_release_room_tracking`, `hvac_fans.py:1266-1294`). After unpause `is_on=False`, so the "turned off externally" branch cannot book a cooldown. Pinned by `test_fan_controller_paused_release_level_no_write`.
- **Mid-flight restore.** The release clears `is_on` during PAUSED, but the restore works from the recheck's own snapshot (`hvac_fans.py:2353-2392`), not the live tracking. Restore ON → `is_on=True` → the next paused tick releases again. VACATED leave_off clears. A paused room cannot snapshot a new recheck: `_evaluate_eligibility` vetoes it and `_on_arm_expired` → `_still_armed_eligible` (`presence_fan_recheck.py:792`, `:1230`) → cooldown, with no fan write.
- **Stale tracking / restart.** FanController tracking is RAM-only (no persist/rehydrate in `hvac_fans.py`), so a restart starts clean. Recheck rehydrate: PAUSED → `_restore` (the discharge runs whatever the pause state, which is correct). ARMED → idle. COOLDOWN → resumes. None of these read the pause gate, so all stay restart-safe. An unavailable switch reads paused (`coordinator.py:3179`, `state == "on"`), which fails closed for actuation. A missing switch reads enabled (fail-open = today).
- **Lookups.** `hass.data[DOMAIN][entry_id]` is the room coordinator itself (`__init__.py:5583`), so the new `FanController._room_coord` returns an object exposing `_is_automation_enabled`. The gate is not silently inert.
- **Sleep-onset.** Skip at `hvac_fans.py:1055-1058` sits after the G3 owner check. `_sleep_onset_fired` is per-house, so there is no per-room catch-up after unpause (consistent with §5).
- **Pre-arrival.** F4a skip records `room_paused` in `_last_fan_skipped_rooms` (reset per call `hvac_predict.py:453`, display only). F4b skip leaves a person's fan alone. A fan F4a lit before the pause stays on (plan §5).
- **Exit verify.** `skipped_paused` is display-only (`sensor.py:2598`). Task lifecycle unchanged (entry background task).
- **Untouched by ruling:** house state, covers, humidity venting, AI rules, safety stop, `turn_off_all_managed`. No diff in those files. `_set_fan_state` chokepoint callers are exactly update / sleep-onset / pause / restore / turn_off_all_managed (`hvac_fans.py:542,937,1142,2192,2389`).
- **INV-N.** The predicate returns False for an enabled room, and every gate is a `continue` / veto behind it. The only extra cost is the per-room config-entry scan in `_room_coord` per tick (negligible).

## Verdict

**FIX-REQUIRED (doc-only, no code):** B-M1. Restate INV-Z and the STATE_OF_PLAY / README lines so the second zone-side consequence (lost recheck phantom release in paused rooms where D2 fails closed) is recorded and operator-visible. Optionally fold B-L2 into the README. No code change is required for ship.

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 1 (B-M1, doc) | 1 |
| LOW | 2 | 0 |

## Fix-up (2026-10-19)
- **B-M1 FIXED (doc only).** INV-Z is restated in the plan, PRESENCE §4.5 / §6 item 3 and HVAC §4.2b. Besides the D2 backstop, a paused room also loses the recheck's VACATED release. In paused rooms without a fan-immune witness (Media, GB1 and GB2 today), a running fan can therefore hold the room and its zone occupied until the 4 h stuck rule or the P24 failsafe fires. The operator ruling accepts this consequence. The README one-liner is due at deploy.
- **B-L2 FIXED (doc only).** The plan §5 unpause note, HVAC §4.2b and PRESENCE §4.5 now state that a fan URA lit before the pause (or one the recheck restore re-lit) is adopted under the manual-ON hold on unpause, for up to one hold.
- B-L1: accepted, no action.

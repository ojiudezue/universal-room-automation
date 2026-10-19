# Review A — paused rooms stop occupancy lights/fans (local correctness + edge cases)

Branch `fix/paused-room-lights-fans` @ `67a9f7442`, base `fa3db9a59` (three-dot). Reviewer framing A.
Read COMPLETELY first: `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`SENSOR_FLEET_CLASSES.md`, plan `PLANNING_paused_room_occupancy_lights_fans.md`. No ledger claim re-asserted.

## Predicate truth table — `const.room_automation_paused` (const.py:1310)

| room_coord | manual_mode | automation switch | `_is_automation_enabled()` | paused? |
|---|---|---|---|---|
| None | – | – | – | False |
| no method / non-callable | – | – | – | False |
| method raises | – | – | raises | False |
| coord | on | any | False | **True** |
| coord | off/missing | on | True | False |
| coord | off/missing | off | False | **True** |
| coord | off/missing | missing (not in registry, no state) | True | False |
| coord | off/missing | `unavailable` / `unknown` | False (`state.state == "on"` is False, coordinator.py:3179) | **True** |

Manual Mode counts as paused: correct per plan §0 and coordinator.py:3183-3186. Fail-open on None/exception: correct —
the failure mode equals today's behaviour (the room gets swept/actuated), and the alternative (fail-closed) would silently
stop automation in an unpaused room with no trip-wire. `check() is False` is right for a `bool` return.

## Findings

| # | SEV | Site | Finding |
|---|---|---|---|
| A-L1 | LOW | const.py:1310 docstring; HVAC SoP §4.2b; PRESENCE SoP §4.5 ("fail-open") | "Fail-open" is true only for None / no method / exception. A room Automation switch that reads `unavailable`/`unknown` (room entry reload, entity re-create) yields `_get_room_switch_state` → False → **paused** (coordinator.py:3179, pre-existing semantics shared with the room tier). Repro: room reload while its zone's vacancy sweep fires → that room is skipped with no catch-up (plan §5). Narrow window; behaviour matches the room tier's own gate, so no code change required — but the docs should say "fail-open on missing switch / None / exception; an unavailable switch reads as paused (same as the room tier)". Bug class: doc/code semantic drift. |
| A-L2 | LOW | hvac_fans.py:1295 `_room_coord` vs presence_fan_recheck.py:1354 `_room_coord_for` | Docstring says "same shape" but the recheck also accepts `entry.data["room_name"]` fallback. `CONF_ROOM_NAME == "room_name"` (const.py:395), so the fallback is identical — no behaviour difference. Holds. Info only. |

No CRITICAL / HIGH / MEDIUM.

## Per-gate correctness

| Gate | Site | Verdict |
|---|---|---|
| L1 zone vacancy sweep | hvac.py:6733-6741 | Holds: after coordinator-None `continue`, before config merge, so both emit sites (lights/night lights hvac.py:~6783, fans ~6879) are skipped; covers row-1 and D6 callers (gate inside the function). `vacancy_sweep_done` / counter untouched (set by callers). INFO per skipped room, bounded by one sweep per zone vacancy. |
| F1 FanController.update | hvac_fans.py:651-666 | Holds: placed after G2 `_is_room_hvac_managed`, BEFORE the recheck suppress-until handshake and external-change sync, so no adoption / cooldown is opened while paused. Level release every paused tick. |
| `_release_room_tracking` | hvac_fans.py:1266-1294 | Holds: clears exactly `is_on`, `trigger`, `speed_pct`, `last_on_time`, `vacancy_detected_time`; does NOT touch `fan_recheck_suppress_until`, manual-ON hold fields or the oracle cooldown ledger; writes nothing. The Fan-Mode release branch (hvac_fans.py:1345) now calls the same helper — field set byte-identical to the deleted inline block. |
| F3 sleep onset | hvac_fans.py:1055-1058 | Holds: after G3, before any ON decision; no release here (F1 owns it). |
| F4a pre-arrival ON | hvac_predict.py:1455-1468 | Holds: after coordinator-None, before all three `turn_on` emits (:1573/:1597/:1611); `_last_fan_skipped_rooms` initialised (:153, reset :453); `temp: None` in the skip record is consistent with other skip rows. |
| F4b pre-arrival OFF | hvac.py:7405-7414 | Holds: after coordinator-None, before the emit (:7483). |
| F2 recheck arm | presence_fan_recheck.py:552-556, :1230-1233 | Holds: veto `room_paused` right after `fan_control_off`; still-armed twin returns False. PAUSED recheck not cut short; restore (`restore_after_recheck`) ungated. |
| D2 backstop | `is_recheck_eligible` → `_evaluate_eligibility` (inert sink) | Holds as operator-accepted: paused → ineligible → D2 defer no longer applies. Pinned by `test_mmwave_fan_demotion.py::test_paused_room_d2_backstop_not_deferred`. |
| Exit-verify gate | coordinator.py:5735-5741 | Holds: re-reads `_is_automation_enabled()` after the 3 s sleep, after the re-occupied check, before any device count / retry. `_is_automation_enabled` does not raise on a missing switch (returns True). |

None handling: every site checks coordinator-None first (sweep, F4a, F4b) or the predicate absorbs None (F1/F3 via
`_room_coord` → None → not paused; F2 `room_coord` None → not paused). `_room_coord` never raises.

## Independent re-enumeration of light/fan occupancy writers (operator invariant INV-P')

Greps run on the branch: `_set_fan_state(`, `"turn_on"/"turn_off"`, `async_call(` across `domain_coordinators/*.py`;
`turn_(on|off)` file list across the package; `ServiceCallAction(` producers.

| Writer | Gated / whitelisted |
|---|---|
| hvac.py:6644/6672/6687 `_stop_all_fans_safety` | whitelisted (i) |
| hvac.py:6783/6879 vacancy sweep | gated L1 |
| hvac.py:7483 `_deactivate_zone_fans` | gated F4b |
| hvac_predict.py:1573/1597/1611 | gated F4a |
| hvac_fans.py:542 `turn_off_all_managed` | whitelisted (ii) (writes only tracked `is_on`; paused release clears it, so in practice no write — allowed, not required) |
| hvac_fans.py:937 `update` | gated F1 |
| hvac_fans.py:1142 sleep onset | gated F3 |
| hvac_fans.py:2192 `pause_for_recheck` | gated at arm F2 |
| hvac_fans.py:2389 restore + attribute restores :2410-2438 (preset/oscillate/direction, not on/off) | whitelisted (iii) |
| hvac_fans.py:1766-1786 `_emit_fan_state` | inner emit only |
| hvac_override / hvac.py:8792 / hvac_covers / energy / notification_manager / music_following / radar_tuning / optimization / weather_manager | not room light/fan occupancy writers (notifications, carrier reload, covers, energy loads, alert lights) |
| safety.py / security.py `ServiceCallAction` light.turn_on via manager.py:1054 | safety/security lights — not occupancy-driven |
| aggregation.py:1511-1532 `_flash_light` | alert flash, not occupancy |
| room tier (coordinator.py gated block, automation.py, actuator_reconciler.py:544) | pre-existing gates |

No missed site. INV-P' holds on the enumerated surface.

## Tests (targeted only)
`test_paused_room_gates.py` + `test_mmwave_fan_demotion.py`: 39 passed (PYTHONDONTWRITEBYTECODE=1, .venv-ha). Mutation
authority is framing C's lane; not drilled here.

## Verdict
**SHIP.** No must-fix. Optional in-cycle LOW: correct the "fail-open" wording (A-L1) in the predicate docstring and both
STATE_OF_PLAY lines to note that an `unavailable` Automation switch reads as paused (pre-existing room-tier semantics).

## Fix-up (2026-10-19)
- **A-L1 FIXED (doc only).** The "fail-open" wording is corrected in the `const.room_automation_paused` docstring, plan §4, HVAC STATE_OF_PLAY §4.2b and PRESENCE STATE_OF_PLAY §4.5. A missing coordinator, method or switch, or an exception, reads enabled. A switch that reads `unavailable` / `unknown` reads PAUSED (`coordinator.py:3179`, `state == "on"`), which is the room tier's pre-existing semantics. No code change.
- A-L2: info only, no action.

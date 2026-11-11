# DRAFT — LIGHT-TRANSITION-COVERAGE-1 (Tier 1)

Every ambient `light.*` turn_on/turn_off URA issues now carries the room's configured fade
(`CONF_LIGHT_TRANSITION_ON` / `_OFF`, const.py:1236-1237; defaults 1 s / 3 s, const.py:1719-1720).
No new knobs, no default change. Alert, security, safety and warning-flash lights stay instant.
`switch.*` relays never get a `transition` key.

New helper: `lighting/resolver.py::light_transition(cfg, *, on)` (reads the existing knobs).
Help text on the two room fade fields (strings.json + translations/en.json) now says relay
(`switch.*`) lights cannot fade.

## Emission-site table (light domain, `custom_components/universal_room_automation`)

| Site | Call | Status |
|---|---|---|
| automation.py ~1614 `_control_lights_entry` | light.turn_on | already had ON transition |
| automation.py ~1702 exit path | light.turn_off | already had OFF transition |
| automation.py ~1855 / ~1885 entry/exit (other branch) | on / off | already had transition |
| automation.py ~1979 `_turn_on_night_lights` | light.turn_on | already had (via `_nl_params(include_transition=True)`) |
| automation.py ~2014 night-light off | light.turn_off | already had OFF transition |
| automation.py ~922 `handle_away_leave_on_sweep` | light.turn_off | **ADDED** OFF |
| automation.py ~4694 `_shared_space_turn_off_all` | light.turn_off | **ADDED** OFF |
| switch.py ~5654 `RoomLightsSwitch.async_turn_on` regular | light.turn_on | **ADDED** ON |
| switch.py ~5663 `RoomLightsSwitch.async_turn_on` night | light.turn_on | **ADDED** ON |
| switch.py ~5697 `RoomLightsSwitch.async_turn_off` | light.turn_off | **ADDED** OFF |
| actuator_reconciler.py ~704 `_reconcile_one` dispatch (all reconciler light writes: entry, night-light, sleep, exit) | on / off | **ADDED** at dispatch for `light` domain, non-fan; added to the payload, not to `DesiredState.params`, so the `has_params_to_apply` no-op gate is unchanged |
| automation.py ~4617 / ~4632 `_warning_flash` | light.turn_on | instant: auto-off warning signal, a fade would blunt the flash |
| automation.py ~4784 / ~4818 / ~4831 / ~4869 / ~4885 alert lights (trigger / flash / restore) | on / off | instant: alert signal and its restore |
| aggregation.py ~1670 / ~1680 / ~1691 alert flash + restore | on / off | instant: alert |
| domain_coordinators/notification_manager.py ~2748 `_ura_light_call` | on / off | instant: NM alert pattern + restore |
| domain_coordinators/security.py:1726 | light.turn_on | instant: security (per card) |
| domain_coordinators/safety.py:2701 | light.turn_on | instant: safety (per card) |

`night_light_turn_on_params(include_transition=False)` callers: automation.py passes `True` (already
faded); actuator_reconciler.py :840 / :912 keep `False` deliberately. The reconciler now adds the
fade at dispatch instead, because putting it in params would make `has_params_to_apply` true for a
BASIC night light and re-send it on every reconcile.

## Acceptance
- **Test:** `quality/tests/test_light_transition_coverage.py` (11 tests; each added site
  mutation-anchored).
- **Live:** toggle a room's "Room lights" switch → the HA logbook/trace for the `light.turn_on`
  call shows `transition` equal to the room's fade-in value; a `switch.*` member switches with no
  `transition` in its service data.

# LIGHT-TRANSITION-COVERAGE-1 — Review A (local correctness + edge cases)

Commit dfc4268c, base origin/develop. Verdict: **SHIP**.

## Site re-enumeration (independent grep of every `light` turn_on/turn_off emission)
| Site | Kind | Transition | Switch-safe |
|---|---|---|---|
| automation.py:1604 entry regular lights | ambient | pre-existing CONF_ON | split by prefix |
| automation.py:1705 exit | ambient | pre-existing CONF_OFF | split |
| automation.py:1841 regular on | ambient | pre-existing CONF_ON | split |
| automation.py:1884 sleep-gate NL off | ambient | pre-existing CONF_OFF | split |
| automation.py:1984 night-light on | ambient | `_nl_params(include_transition=True)` | split |
| automation.py:2019 non-night off | ambient | pre-existing CONF_OFF | split |
| automation.py:923 away leave-on sweep | ambient | NEW helper off | split (`light.` prefix) |
| automation.py:4696 night failsafe off | ambient | NEW helper off | split |
| actuator_reconciler.py:704 dispatch | ambient (alert lights excluded at :106) | NEW helper on/off | `domain` derived from prefix :818, switch never gets it |
| switch.py:5654/5662 RoomLightsSwitch on | ambient | NEW helper on | switches separate |
| switch.py:5696 RoomLightsSwitch off | ambient | NEW helper off | switches separate |
| automation.py:4622-4640 warning flash | alert | none (instant) | — |
| automation.py:4793/4827/4840/4878/4894 alert lights + restore | alert | none | — |
| aggregation.py:1670-1691 alert flash | alert | none | — |
| notification_manager.py:2748 NM light channel | alert | none | — |

No ambient site missed; no alert site gained transition.

## Edge cases
- transition=0: knob min=0 (config_flow.py:3004); HA accepts 0 → instant. Holds.
- unset knob: helper falls back to DEFAULT 1/3 (const.py:1719-1720), matching the pre-existing literal 1/3 sites. Holds.
- None: not reachable via selector (vol.Optional with default). Helper does not coerce None (LOW, same as all pre-existing `.get(CONF, 1)` sites; no action).
- basic-capability / switch-backed light groups: HA light core strips `transition` for entities without TRANSITION feature; pre-existing canonical sites already send it to basic lights. Holds.
- brightness+transition: additive keys, no conflict. Reconciler override is after the `has_params_to_apply` no-op gate (:646), so no-op path byte-identical.
- Reconciler night-light ON now carries transition_on, matching canonical include_transition=True (parity improved).

## Findings
- LOW (no fix required): resolver.py:158 helper returns raw cfg value; a stored None would fail HA schema. Unreachable via flow; parity with pre-existing sites.

## Tests
test_light_transition_coverage.py 11 passed; 442 passed across reconciler / RoomLightsSwitch / leave-on / auto-off / night-light test files.

**SHIP.**

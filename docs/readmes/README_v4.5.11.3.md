# v4.5.11.3 — Fix AC Ramp button stuck-unavailable after restart

**Date:** 2026-05-10
**Type:** Tier 1 hotfix (~20 LoC + 5 regression tests)
**Predecessor:** v4.5.11.2

## Summary

The 9 per-zone AC Ramp buttons (Force AC Nudge / Cancel AC Nudge / Clear AC Ramp Lockout × 3 zones) cached `available: False` permanently after a restart, appearing greyed-out in the UI until a manual `homeassistant.update_entity` service call was issued.

## Root cause

`_ACRampButton.available` returns `self._get_arrester() is not None`. At platform `async_setup_entry` time, the HVAC coordinator's `_override_arrester` attribute may not be reachable yet (timing between integration setup and platform setup). When HA caches `available: False` for a button entity, it does NOT re-evaluate unless something explicitly triggers a state update.

- **Number entities** survive this because HA reads their `native_value` property on every state poll — which forces `available` re-evaluation indirectly.
- **Switch entities** survive because `is_on` is queried on every state read.
- **Button entities** have no equivalent natural refresh — they only fire on press. Once HA caches `available: False`, the button stays greyed-out until manual intervention or HA restart.

## Fix

Add `async_added_to_hass` to `_ACRampButton` that subscribes to `SIGNAL_HVAC_ENTITIES_UPDATE` (which the HVAC coordinator fires at the end of every 5-minute decision cycle). On signal: call `async_schedule_update_ha_state()`, which makes HA re-query `available`. Once the arrester is reachable, `available` flips to True and the button becomes pressable.

Subscription is unwrapped via `self.async_on_remove()` so HA cleans it up on entity removal.

```python
async def async_added_to_hass(self) -> None:
    await super().async_added_to_hass()
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
    self.async_on_remove(
        async_dispatcher_connect(
            self.hass,
            SIGNAL_HVAC_ENTITIES_UPDATE,
            self._handle_hvac_update,
        )
    )

@callback
def _handle_hvac_update(self, *_args, **_kwargs) -> None:
    self.async_schedule_update_ha_state()
```

This matches the pattern used by HVAC sensors in `sensor.py` (HVACModeSensor, HVACZoneStatusSensor, etc.) — they all subscribe to the same signal.

## Effect on user experience

| | Before v4.5.11.3 | After v4.5.11.3 |
|---|---|---|
| Restart with arrester reachable at button-setup time | Buttons work | Buttons work |
| Restart with arrester delayed past button-setup time | **Buttons stuck unavailable** until manual `update_entity` or next restart | Buttons auto-recover within one decision cycle (≤5 min) |
| Arrester briefly unreachable mid-runtime (e.g., during reload) | Buttons stay unavailable thereafter | Buttons re-evaluate at next signal fire |

## Regression test

New class `TestButtonAutoRefresh` (5 tests) in `test_v4511_ac_energy_aware_ramp_down.py`:

- `test_button_has_async_added_to_hass` — method exists
- `test_button_subscribes_to_hvac_signal` — connects to SIGNAL_HVAC_ENTITIES_UPDATE
- `test_button_uses_async_on_remove` — unsub cleanup path present
- `test_button_signal_handler_schedules_state_update` — handler calls `async_schedule_update_ha_state`
- `test_button_handler_is_callback_decorated` — handler is `@callback` (sync, HA dispatcher contract)

## Tier 1 review

Bug classes checked:
- **#5 Startup race** — subscription happens in `async_added_to_hass` (post-setup), dispatcher is ready ✓
- **#19 Untracked background tasks** — unsub wrapped with `async_on_remove`, cleaned up on entity removal ✓
- **#22 Enum mismatch** — signal name imported from canonical `hvac_const` ✓
- **#28 Sync/async pattern** — handler is `@callback`-decorated (correct for dispatcher) ✓
- **#34 Function-local import shadow** — local imports inside method don't shadow module-level names ✓

Verdict: APPROVED for deploy.

## Test count progression

- v4.5.11.2: 155 tests
- **v4.5.11.3: 160** (+5), 0 isolated failures

## Lesson — Bug Class #35 candidate

> **Button entities must subscribe to a refresh signal if their `available` property depends on a runtime-mutable resource.** Unlike Number/Switch/Sensor entities, HA does not naturally re-evaluate `available` for Button entities. Once `available: False` is cached at setup time, the button stays greyed-out indefinitely without an explicit trigger.
>
> **Test pattern:** for any Button entity whose `available` depends on a coord/manager/registry lookup, source-grep its class body for `async_dispatcher_connect` or `async_track_state_change` or similar refresh mechanism. If absent, the button risks the stuck-unavailable pattern.

Adding this to `QUALITY_CONTEXT.md` is a slice-2 task alongside Bug Class #34.

## Deploy notes

- No DB schema changes
- No migration
- HACS download required after deploy.sh
- HA restart required (1 file touched: button.py)
- After restart: buttons should be operable within one decision cycle (≤5 min) without any manual intervention

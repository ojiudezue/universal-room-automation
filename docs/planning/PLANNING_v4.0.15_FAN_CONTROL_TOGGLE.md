# v4.0.15: HVAC FanController Toggle + Occupancy Gate

## Context

HVAC FanController (Path 1) runs ceiling fans based on temperature delta from thermostat setpoint. Two bugs:
1. **No toggle** — unlike every other HVAC sub-feature (arrester, AC reset, zone intelligence, pre-arrival, zone sweep), FanController has no enable/disable switch. Can't turn it off without disabling the entire HVAC coordinator.
2. **No occupancy gate on activation** — temperature check (line 227) fires BEFORE occupancy is evaluated (line 241). Fans turn on in empty rooms, wasting electricity and conflicting with external leave automations.

**Triggered by:** Study A fan flapping — FanController turns it on (warm room), external Office Leave Automation turns it off (room empty), repeat every 5 min.

---

## Deliverables

### D1: Toggle switch — `switch.py`

Add `HVACFanControlSwitch` following the `HVACZoneIntelligenceSwitch` pattern (line 922):
- Class: `HVACFanControlSwitch(SwitchEntity, RestoreEntity)`
- Entity: `switch.ura_hvac_coordinator_fan_control`
- Icon: `mdi:fan`
- Device: `hvac_coordinator`
- Reads/writes: `hvac.fan_control_enabled` (new property on HVACCoordinator)
- Default: `True` (on — backward compatible)
- RestoreEntity for persistence across restarts

Register in `async_setup_entry` switch list (line ~146, alongside other HVAC toggles).

### D2: Fan control enabled property — `hvac.py`

Add to `HVACCoordinator.__init__`:
```python
self._fan_control_enabled: bool = fan_control_enabled
```

Add property + setter. Gate `FanController.update()` call:
```python
if self._fan_control_enabled:
    await self._fan_controller.update(self._energy_constraint, self._house_state)
```

### D3: Occupancy gate in FanController — `hvac_fans.py`

Move occupancy check BEFORE temperature triggers in `_evaluate_temp_fan()`. New logic:
- **Unoccupied + fan off** → return False immediately (don't activate)
- **Unoccupied + fan on** → apply vacancy hold (600s), then off
- **Occupied** → proceed to temperature/fan_assist triggers as before

### D4: Config flow — `config_flow.py`

Add `CONF_HVAC_FAN_CONTROL_ENABLED` boolean toggle in `async_step_coordinator_hvac` after fan tuning params.

### D5: Constants — `hvac_const.py`

```python
CONF_HVAC_FAN_CONTROL_ENABLED: Final = "hvac_fan_control_enabled"
DEFAULT_FAN_CONTROL_ENABLED: Final = True
```

### D6: Init wiring — `__init__.py`

Pass `fan_control_enabled` from cm_config to HVACCoordinator.

### D7: Observability — `hvac.py` mode sensor attributes

Add `fan_control_enabled` attribute alongside existing `arrester_enabled`, `ac_reset_enabled`.

### D8: strings.json

Label + description for the config flow toggle.

### D9: Tests

- Occupancy gate prevents activation in empty rooms
- Vacancy hold works correctly
- Occupied + warm room activates fan (existing behavior preserved)
- Default is True (backward compatible)

---

## Files Modified

| # | File | Changes |
|---|------|---------|
| 1 | `hvac_const.py` | +CONF_HVAC_FAN_CONTROL_ENABLED, +DEFAULT_FAN_CONTROL_ENABLED |
| 2 | `hvac.py` | +fan_control_enabled param/property/setter, gate FanController.update(), +attribute |
| 3 | `hvac_fans.py` | Rewrite _evaluate_temp_fan() occupancy gate before temperature triggers |
| 4 | `switch.py` | +HVACFanControlSwitch class, register in async_setup_entry |
| 5 | `config_flow.py` | +fan_control_enabled boolean in coordinator_hvac step |
| 6 | `__init__.py` | +import + pass fan_control_enabled to HVACCoordinator |
| 7 | `strings.json` | +label for hvac_fan_control_enabled |
| 8 | `quality/tests/test_hvac_fan_control.py` | 6 tests |

---

## Verification

### Pre-deploy
1. Tests: `PYTHONPATH=quality python3 -m pytest quality/tests/test_hvac_fan_control.py -v`
2. Full suite: `PYTHONPATH=quality python3 -m pytest quality/tests/ -v`
3. Tier 1 review (hotfix scope)

### Post-deploy — User action
4. Toggle `switch.ura_hvac_coordinator_fan_control` OFF in HA UI
5. Verify Study A fan stops cycling

### Post-deploy — Claude verifies via MCP
6. Check `sensor.ura_hvac_coordinator_mode` attributes include `fan_control_enabled: false`
7. Check `switch.ura_hvac_coordinator_fan_control` exists and is toggleable
8. Verify `active_fans: 0` after toggle off
9. Toggle back on → verify fan activates in occupied warm room only

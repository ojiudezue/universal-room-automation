# Smart Plug Controller Hardening

**Risk: LOW** — Small scope, follows existing EVChargerController patterns, no new sensors or DB changes.

## Context

`SmartPlugController` manages 4 Moes WiFi smart plug sockets in Garage A (L1 charger outlets for trickle charging). Currently only pauses during `peak` TOU. Missing:
- No `mid_peak` pause (L2 EVSE pauses on both peak AND mid_peak)
- No battery drain awareness (L1 chargers drain battery same as any load)

The plugs have **no power sensors** — only on/off switches. So grid cap and power-based detection are not applicable.

## Current SmartPlugController Behavior

```
peak → turn off (if on and not already paused)
anything else → turn on (if we paused it)
```

Single tracking set: `_paused_by_us`

## Deliverables

### D1: Add mid_peak to TOU pause

Change `tou_period == "peak"` to `tou_period in ("peak", "mid_peak")`. Aligns with EVChargerController's TOU behavior.

### Acceptance Criteria
- **Verify:** Smart plugs turn off during mid_peak period
- **Verify:** Smart plugs resume on off_peak (not on mid_peak→peak transition)
- **Verify:** Manual turn-on during mid_peak is not re-paused (existing `_paused_by_us` dedup)

### D2: Battery drain protection for smart plugs

New method: `determine_battery_drain_actions(battery_power_w, battery_soc, soc_threshold)`

**Pause when:** Plug is ON AND battery is discharging (>100W) AND SOC < threshold.
**Resume when:** Battery stops discharging OR SOC recovers above threshold + 5%.
**No charging detection needed** — can't detect power draw on dumb plugs, so we check `is_on` instead of `charging`. If the plug is on and battery is draining, assume it's contributing to the drain.

New tracking set: `_paused_by_battery_drain: set[str]`

Cross-pause guards (same pattern as EVChargerController):
- TOU resume checks `_paused_by_battery_drain` before turning on
- Battery drain resume checks `_paused_by_us` before turning on

### Acceptance Criteria
- **Verify:** Plugs turn off when battery discharging + SOC < 80%
- **Verify:** Plugs resume when battery stops discharging (reserve holds)
- **Verify:** TOU resume doesn't override battery drain
- **Verify:** Battery drain resume doesn't override TOU pause

### D3: Integration into decision cycle

Call `self._smart_plugs.determine_battery_drain_actions()` after existing `self._smart_plugs.determine_actions()` in energy.py. Pass same battery state as EVSE battery drain.

### Acceptance Criteria
- **Verify:** Both TOU and battery drain actions execute each cycle
- **Verify:** Smart plug status sensor shows `paused_by_battery_drain` attribute

## Files Modified

| File | Changes |
|------|---------|
| `energy_pool.py` | SmartPlugController: mid_peak pause, `_paused_by_battery_drain` set, `determine_battery_drain_actions()`, cross-pause guards, updated `get_status()` |
| `energy.py` | Call `_smart_plugs.determine_battery_drain_actions()` in decision cycle |

## Risk Assessment

**LOW risk because:**
- Follows exact EVChargerController battery drain pattern (proven code shape)
- No power sensors to fail — simpler than EVSE (just on/off)
- No DB changes, no new config (uses same SOC threshold as EVSE)
- No new entities — status visible in existing smart plug status
- Easily testable: unplug everything, watch plug toggle on battery state changes

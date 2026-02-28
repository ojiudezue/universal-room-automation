# Universal Room Automation v3.6.0-c2.8 — Fix Unsafe Safety Light Response

**Release Date:** 2026-02-28
**Internal Reference:** C2.8 (critical hotfix)
**Previous Release:** v3.6.0-c2.7
**Minimum HA Version:** 2024.1+

---

## Summary

**CRITICAL FIX.** The Safety Coordinator's `_critical_response` method was calling `light.turn_on` with `entity_id: "all"` — meaning any CRITICAL hazard (smoke, flooding, CO) would set **every light in the entire house** to full brightness with a colored RGB pattern. It also called `fan.turn_on` with `entity_id: "all"` for CO events.

These service calls were **live** — the coordinator manager's `_execute_action` method calls `hass.services.async_call(..., blocking=True)` for `ServiceCallAction` objects. This was not theoretical; it would have fired on the next CRITICAL hazard detection.

### Why This Was Missed

The Safety Coordinator was built in C2 with placeholder "all lights" logic intended to be replaced with the configured emergency lights. The config flow (`async_step_coordinator_safety`) correctly collects `emergency_light_entities` and passes them to the constructor as `self._emergency_lights`, but the `_critical_response` method was written to use `entity_id: "all"` and never wired up to use the configured list.

The CO response (`fan.turn_on` with `entity_id: "all"`) was similarly a placeholder that should have been gated or removed.

---

## What Changed

### Before (dangerous)

```python
def _critical_response(self, hazard):
    # Targets EVERY light in the house
    actions.append(ServiceCallAction(
        service="light.turn_on",
        service_data={
            "entity_id": "all",
            "brightness": 255,
            "rgb_color": [255, 100, 0],  # Colored flash
        },
    ))
    # CO: turns on EVERY fan
    if hazard.type == HazardType.CARBON_MONOXIDE:
        actions.append(ServiceCallAction(
            service="fan.turn_on",
            service_data={"entity_id": "all"},
        ))
```

### After (safe)

```python
def _critical_response(self, hazard):
    # Only configured emergency lights, white, full brightness
    if self._emergency_lights:
        actions.append(ServiceCallAction(
            service="light.turn_on",
            service_data={
                "entity_id": self._emergency_lights,
                "brightness": 255,
            },
        ))
    else:
        _LOGGER.warning(
            "CRITICAL hazard (%s) but no emergency lights configured",
            hazard.type.value,
        )
    # CO fan blast removed — no blanket fan.turn_on
```

### Additional fix

`_water_shutoff_actions` was reading from `hass.data[DOMAIN]["water_shutoff_valve"]` (never set) instead of `self._water_shutoff_valve` (set from config). Fixed to use the instance variable.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | Rewrote `_critical_response`: use `self._emergency_lights` instead of `entity_id: "all"`. Removed CO fan blast. Fixed `_water_shutoff_actions` to use `self._water_shutoff_valve`. |

---

## How to Configure Emergency Lights

1. Go to **Settings → Devices & Services → URA**
2. Click **Configure** on the **Coordinator Manager** entry
3. Select **Safety Monitoring**
4. Use the **Emergency Light Entities** multi-select to pick specific lights
5. Optionally configure **Water Shutoff Valve** entity

If no emergency lights are configured, the Safety Coordinator will:
- Still detect and log hazards
- Still send notifications
- Still trigger water shutoff (if configured)
- **Skip all light manipulation** and log a warning

---

## How to Verify

1. Check logs after restart for: `"Safety Coordinator setup complete"` — no errors
2. If no emergency lights configured, check for warning: `"CRITICAL hazard ... but no emergency lights configured"`
3. Verify no lights change unexpectedly during normal operation
4. In CM → Configure → Safety Monitoring, verify the light picker shows your selected entities

---

## Version Mapping

| Version | Cycle | Description |
|---------|-------|-------------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| 3.6.0-c0.1–c0.4 | C0.x | Integration page, census fix, entity availability, diagnostics |
| 3.6.0-c1 | C1 | Presence Coordinator |
| 3.6.0-c2 | C2 | Safety Coordinator |
| 3.6.0-c2.1–c2.4 | C2.x | Deployment bug fixes (options wipe, census signal, zone config) |
| 3.6.0-c2.5 | C2.5 | Per-coordinator toggle switches (code added) |
| 3.6.0-c2.6 | C2.6 | Fix zone presence "unknown", safety false positives |
| 3.6.0-c2.7 | C2.7 | Fix toggle switches not appearing (Platform.SWITCH missing) |
| **3.6.0-c2.8** | **C2.8** | **Fix unsafe entity_id "all" in safety critical response** |

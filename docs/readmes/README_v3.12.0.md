# v3.12.0 — AI Custom Automation (M2 + M3 + M4)

**Date**: 2026-03-12
**Scope**: Complete AI automation system — coordinator signal triggers, AI natural-language rules, conflict detection, diagnostics
**Tests**: 1008 total (49 automation chaining M1+M2 + ~46 AI automation M3+M4)

---

## Summary

Completes the AI Custom Automation feature set (milestones M2-M4) on top of the M1 chaining infrastructure shipped in v3.10.0. Users can now:

1. **M2**: Bind HA automations to house state transitions, energy constraints, safety hazards, and security events — per-room
2. **M3**: Create natural-language automation rules parsed by AI at config time, executed deterministically at runtime
3. **M4**: Monitor all automation activity via a per-room diagnostics sensor

## M2: Coordinator Signal Triggers

### New Trigger Types (12)

#### House State Triggers (9)
| Trigger | Fires When |
|---------|-----------|
| `house_state_away` | House transitions to Away |
| `house_state_arriving` | Someone is arriving |
| `house_state_home_day` | House enters Home Day |
| `house_state_home_evening` | House enters Home Evening |
| `house_state_home_night` | House enters Home Night |
| `house_state_sleep` | House enters Sleep mode |
| `house_state_waking` | House enters Waking mode |
| `house_state_guest` | House enters Guest mode |
| `house_state_vacation` | House enters Vacation mode |

#### Coordinator Signal Triggers (3)
| Trigger | Fires When |
|---------|-----------|
| `energy_constraint` | Energy coordinator changes constraint (peak, shed, coast) |
| `safety_hazard` | Safety coordinator detects a hazard (smoke, CO, water leak) |
| `security_event` | Security coordinator fires an event (entry alert, unknown person) |

### Config Flow Sub-Menu

The single "Automation Chaining" form is now a **sub-menu** with 4 groups:

```
Automation Chaining
  ├── Occupancy Triggers (enter, exit)
  ├── Light Level Triggers (lux_dark, lux_bright)
  ├── House State Triggers (9 states)
  └── Coordinator Triggers (energy, safety, security)
```

Each sub-step preserves bindings from other groups when saving.

### Signal Architecture

Room coordinators subscribe conditionally to dispatcher signals — only when chains or AI rules are configured for the relevant trigger type. This avoids N*4 handler overhead for unconfigured rooms.

Signals are dispatched at the source:
- `SIGNAL_HOUSE_STATE_CHANGED` — dispatched by presence coordinator on house state transitions
- `SIGNAL_ENERGY_CONSTRAINT` — dispatched by energy coordinator on constraint changes
- `SIGNAL_SAFETY_HAZARD` — dispatched by safety coordinator in `_respond_to_hazard()`
- `SIGNAL_SECURITY_EVENT` — dispatched by security coordinator on entry alerts and unknown person detection

Handlers are `@callback`-decorated (sync), use `async_create_task` to schedule async work.

---

## M3: AI Natural-Language Rules

### How It Works

1. **Config time**: User writes a rule in plain English (e.g., "When I arrive home in the evening, turn on the living room lights to 50%")
2. **AI parsing**: `ai_task.generate_data` parses the rule into structured JSON — trigger type, person filter, target entities, actions
3. **Validation**: Parsed actions are validated against available room entities
4. **Runtime**: Rules execute deterministically from the parsed structure — no AI calls at runtime

### Config Flow

```
AI Rules
  ├── Add Rule (description → AI parse → validate → save)
  ├── List Rules (view configured rules with details)
  └── Delete Rule (select and remove)
```

### Rule Structure (parsed)

```json
{
  "description": "When I arrive home in the evening, dim living room lights to 50%",
  "trigger_type": "house_state_home_evening",
  "person_filter": "Oji",
  "actions": [
    {"service": "light.turn_on", "entity_id": "light.living_room", "data": {"brightness_pct": 50}}
  ]
}
```

### Person Filtering

Rules can target specific people. The coordinator checks `_get_identified_persons_in_room()` against the rule's `person_filter` before executing.

### Conflict Detection

When an AI rule targets the same entity as URA's built-in automation for the same trigger, `binary_sensor.{room}_automation_conflict` turns on. Detection uses set intersection of explicit entity targets.

---

## M4: Diagnostics Sensor

### `sensor.ura_{room}_ai_automation_status`

Per-room diagnostic sensor that tracks all AI automation activity.

| Attribute | Description |
|-----------|-----------|
| `native_value` | "active" if any rules/chains configured, else "inactive" |
| `chained_automations` | Dict of all chain bindings |
| `ai_rules_count` | Number of configured AI rules |
| `last_trigger` | Last trigger event that fired |
| `last_trigger_time` | Timestamp of last trigger |
| `conflict_detected` | Boolean — any active conflicts |
| `last_conflicts` | Last 5 conflict details |

---

## Critical Fixes in This Release

### Listener Leak Fix (CRITICAL)
`async_will_remove_from_hass` is an Entity lifecycle method — never called on DataUpdateCoordinator. State and signal listener unsub handles were leaking on every entry reload. Fixed by adding explicit cleanup in `async_unload_entry` for room coordinators.

### Signal Dispatch Wiring (CRITICAL)
`SIGNAL_SAFETY_HAZARD` and `SIGNAL_SECURITY_EVENT` were defined in `signals.py` but never dispatched. Safety/security coordinators only dispatched their entity-update signals. Added dispatch calls in:
- `SafetyCoordinator._respond_to_hazard()` — dispatches `SafetyHazard` payload
- `SecurityCoordinator._handle_census_intent()` — dispatches `SecurityEvent` for unknown persons
- `SecurityCoordinator._handle_entry_intent()` — dispatches `SecurityEvent` for entry alerts

### Conditional Signal Subscriptions (HIGH)
Rooms now only subscribe to signals they have bindings or AI rules for. Unconfigured rooms skip subscription entirely.

### AutomationConflictBinarySensor Device Class (MEDIUM)
Added missing `BinarySensorDeviceClass.PROBLEM` to the conflict sensor.

---

## Files Changed

| File | Changes |
|------|---------|
| `const.py` | M2 trigger constants, trigger groups, M3 AI rule constants |
| `coordinator.py` | Signal handlers (4), conditional subscriptions, AI rule execution, conflict detection, trigger tracking |
| `config_flow.py` | M2 chain sub-menu (4 groups), M3 AI rules menu (add/list/delete), AI parsing integration |
| `strings.json` | M2 menu + sub-steps, M3 AI rules menu + steps + errors |
| `translations/en.json` | Mirror of strings.json |
| `binary_sensor.py` | AutomationConflictBinarySensor — device_class fix, M3 conflict detection reads |
| `sensor.py` | AIAutomationStatusSensor (M4 diagnostics) |
| `domain_coordinators/safety.py` | SIGNAL_SAFETY_HAZARD dispatch in _respond_to_hazard |
| `domain_coordinators/security.py` | SIGNAL_SECURITY_EVENT dispatch (2 sites: unknown person + entry alert) |
| `__init__.py` | Coordinator listener cleanup in async_unload_entry |
| `test_automation_chaining.py` | 24 M2 tests (49 total with M1) |
| `test_ai_automation.py` | ~46 M3+M4 tests (AI rules, conflict detection, diagnostics sensor) |

## Verification

1. Room options -> Automation Chaining -> sub-menu appears with 4 groups
2. House State -> bind `automation.evening_scene` to `home_evening`
3. House transitions to home_evening -> automation fires
4. Configure Occupancy group -> exit -> configure House State -> occupancy bindings preserved
5. AI Rules -> Add Rule -> enter description -> AI parses -> validates -> saves
6. AI Rules -> List Rules -> shows configured rules
7. Trigger fires -> AI rule executes -> diagnostics sensor updates
8. AI rule targets same entity as URA built-in -> conflict sensor turns on
9. `sensor.ura_{room}_ai_automation_status` shows "active" with correct attributes
10. Reload integration -> no listener leak warnings in logs

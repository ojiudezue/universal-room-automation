# PLANNING v3.10.0 — AI Custom Automation & Automation Chaining

**Version:** v3.10.0 – v3.10.3
**Date:** 2026-03-10
**Status:** Planning (locked)
**Parent plans:** PLANNING_v3_4_0_REVISED.md, PLANNING_v3.4.0_CYCLE_5.md
**Estimated effort:** 4 milestones, ~20 hours total

---

## OVERVIEW

Two complementary features for extending room automation beyond URA's built-in behaviors:

1. **Automation Chaining** — Bind existing HA automations to URA trigger events (enter, exit, lux, house state, coordinator signals). Simple dropdown config, no AI. 1 automation per trigger per room.

2. **AI NL Rules** — Natural language descriptions parsed into structured service calls via `ai_task.generate_data`. Person-specific enter/exit rules. Parse-once at config time, deterministic at runtime.

Both share a common **trigger infrastructure** that detects events beyond the existing enter/exit occupancy transitions.

---

## MILESTONE BREAKDOWN

| Milestone | Version | Scope | Effort |
|-----------|---------|-------|--------|
| M1 | v3.10.0 | Trigger infrastructure + automation chaining (enter/exit/lux) | ~5 hrs |
| M2 | v3.10.1 | Coordinator signal triggers + conflict sensor | ~4 hrs |
| M3 | v3.10.2 | AI NL rules (parse-once, person-specific) | ~7 hrs |
| M4 | v3.10.3 | Polish: rule list UI, diagnostics, tests | ~4 hrs |

---

## DESIGN DECISIONS

### Parse once, execute many (AI rules)
The AI is called exactly once per rule: when the user saves it. Output is a list of structured service calls stored in the config entry. Runtime is deterministic — no AI latency in the automation path.

### Automation chaining runs AFTER built-in automation
URA's `automation.py` runs first (lights, climate, covers). Chained automations fire after via `automation.trigger`. AI rules fire after chained automations. Order: built-in → chained → AI rules.

### Conflict detection is AI-rule-only, pre-execution
Conflict detection is scoped to AI rules only (not chained automations). AI rules have explicit entity targets in their parsed `actions` list, so conflicts are detected via simple set intersection with URA's built-in targets — no timing window, no HA automation introspection, fully deterministic.

### Triggers are room-scoped
Each trigger fires in the context of a specific room. The trigger system is a shared module consumed by both automation chaining and AI rules.

### Rule editing is delete + recreate (v3.10.0)
The original NL description is stored for display. To edit, user deletes the rule and creates a new one. A future version can pre-fill the description for re-parsing.

---

## TRIGGER TYPES

| Trigger | Event | Source | Available from |
|---------|-------|--------|----------------|
| `enter` | Room occupied (False → True) | Occupancy sensors + BLE | M1 |
| `exit` | Room vacant (True → False) | Occupancy sensors + BLE | M1 |
| `lux_dark` | Lux drops below dark threshold | Room light sensor | M1 |
| `lux_bright` | Lux rises above bright threshold | Room light sensor | M1 |
| `house_state` | House state transitions to target | Presence coordinator | M2 |
| `energy_constraint` | Energy constraint changes (peak, shed, coast) | Energy coordinator | M2 |
| `safety_hazard` | Safety hazard detected | Safety coordinator | M2 |
| `security_event` | Security event fires | Security coordinator | M2 |

---

# M1: Trigger Infrastructure + Automation Chaining (v3.10.0)

## Scope

- Trigger detection module for enter, exit, lux_dark, lux_bright
- Config flow: dropdown to bind 1 existing HA automation per trigger per room
- Execution: `automation.trigger` after URA built-in automation completes
- Lux thresholds auto-set by the system with sensible defaults

## Trigger Detection

### Enter/Exit (existing)
Already detected in `coordinator.py` via `_last_occupied_state` comparison. Extend with a hook point for chained automations.

### Lux (new)
The room already has `CONF_LIGHT_SENSOR` configured. URA tracks the lux value each coordinator update cycle (~30s). Add threshold crossing detection:

```python
# In coordinator.py — new trigger detection

# Lux thresholds (sensible defaults, no config needed in M1)
LUX_DARK_THRESHOLD = 50      # Below this = dark
LUX_BRIGHT_THRESHOLD = 200   # Above this = bright

# State tracking
self._last_lux_zone: str | None = None  # "dark", "mid", "bright"

def _detect_lux_trigger(self, current_lux: float | None) -> str | None:
    """Detect lux threshold crossing. Returns trigger name or None."""
    if current_lux is None:
        return None

    if current_lux < LUX_DARK_THRESHOLD:
        new_zone = "dark"
    elif current_lux > LUX_BRIGHT_THRESHOLD:
        new_zone = "bright"
    else:
        new_zone = "mid"

    if new_zone == self._last_lux_zone:
        return None

    old_zone = self._last_lux_zone
    self._last_lux_zone = new_zone

    if old_zone is None:
        return None  # First reading, no transition

    if new_zone == "dark":
        return "lux_dark"
    elif new_zone == "bright":
        return "lux_bright"
    return None
```

Hysteresis is implicit: "mid" zone prevents flapping between dark and bright.

## Config Flow

Add to `OptionsFlowHandler` a new step `async_step_automation_chaining`. Accessible from the room options menu (same pattern as "Manage Zones").

### UI: Dropdown of existing HA automations

```python
# In config_flow.py OptionsFlowHandler

async def async_step_automation_chaining(self, user_input=None):
    """Bind HA automations to URA triggers."""
    if user_input is not None:
        # Store bindings in options
        bindings = {}
        for trigger in AUTOMATION_CHAIN_TRIGGERS:
            key = f"chain_{trigger}"
            val = user_input.get(key, "")
            if val:
                bindings[trigger] = val
        return self.async_create_entry(
            title="",
            data={**self.options, CONF_AUTOMATION_CHAINS: bindings},
        )

    # Build automation dropdown options
    automation_entities = sorted([
        eid for eid in self.hass.states.async_entity_ids("automation")
    ])
    options = [{"value": "", "label": "(none)"}] + [
        {
            "value": eid,
            "label": self.hass.states.get(eid).attributes.get(
                "friendly_name", eid
            ),
        }
        for eid in automation_entities
        if self.hass.states.get(eid) is not None
    ]

    current = self.options.get(CONF_AUTOMATION_CHAINS, {})

    schema = vol.Schema({
        vol.Optional(
            f"chain_{trigger}",
            default=current.get(trigger, ""),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        for trigger in ["enter", "exit", "lux_dark", "lux_bright"]
    })

    return self.async_show_form(
        step_id="automation_chaining",
        data_schema=schema,
    )
```

### Storage

```python
# Config entry options
{
    "automation_chains": {
        "enter": "automation.entertainment_welcome",
        "exit": "automation.entertainment_goodbye",
        "lux_dark": "automation.entertainment_dim_lights",
        # "lux_bright" not set — no automation for this trigger
    }
}
```

## Execution

```python
# In coordinator.py — after built-in automation runs

async def _fire_chained_automations(self, triggers: list[str]) -> None:
    """Fire chained HA automations for the given trigger types.

    Called after URA built-in automation completes. Runs chained
    automations in parallel via asyncio.gather.
    """
    chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
    if not chains:
        return

    room_name = self.entry.data.get(CONF_ROOM_NAME, "unknown")
    tasks = []

    for trigger in triggers:
        automation_id = chains.get(trigger)
        if not automation_id:
            continue

        state = self.hass.states.get(automation_id)
        if state is None or state.state == "unavailable":
            _LOGGER.warning(
                "[%s] Chained automation '%s' for trigger '%s' is unavailable",
                room_name, automation_id, trigger,
            )
            continue

        _LOGGER.info(
            "[%s] Firing chained automation '%s' (trigger=%s)",
            room_name, automation_id, trigger,
        )
        tasks.append(
            self.hass.services.async_call(
                "automation", "trigger",
                {"entity_id": automation_id},
                blocking=False,
            )
        )

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
```

### Integration point in `_async_update_data`

```python
# In coordinator.py — _async_update_data(), after automation.py runs

# Detect triggers
triggers_fired: list[str] = []

# Enter/exit
previous_occupied = self._last_occupied_state
current_occupied = data[STATE_OCCUPIED]
if current_occupied and not previous_occupied:
    triggers_fired.append("enter")
elif not current_occupied and previous_occupied:
    triggers_fired.append("exit")

# Lux
lux_trigger = self._detect_lux_trigger(data.get(STATE_ILLUMINANCE))
if lux_trigger:
    triggers_fired.append(lux_trigger)

# Fire chained automations
if triggers_fired:
    await self._fire_chained_automations(triggers_fired)
```

## Constants

```python
# In const.py

# v3.10.0 Automation Chaining
CONF_AUTOMATION_CHAINS: Final = "automation_chains"

# Trigger types (M1 subset — M2 adds coordinator triggers)
AUTOMATION_CHAIN_TRIGGERS_M1: Final = ["enter", "exit", "lux_dark", "lux_bright"]
```

## Strings

```json
"step": {
    "automation_chaining": {
        "title": "Automation Chaining",
        "description": "Bind existing HA automations to room triggers. These run after URA's built-in automation.",
        "data": {
            "chain_enter": "On room enter",
            "chain_exit": "On room exit",
            "chain_lux_dark": "When room gets dark",
            "chain_lux_bright": "When room gets bright"
        }
    }
}
```

## Files Changed

| File | Changes |
|------|---------|
| `const.py` | `CONF_AUTOMATION_CHAINS`, lux threshold constants, trigger type list |
| `coordinator.py` | `_detect_lux_trigger()`, `_fire_chained_automations()`, trigger detection in `_async_update_data` |
| `config_flow.py` | `async_step_automation_chaining()`, add to options menu |
| `strings.json` | Automation chaining step strings |
| `translations/en.json` | Mirror strings.json |

## Verification

1. Room options → Automation Chaining → dropdown shows all `automation.*` entities
2. Bind `automation.test_enter` to "enter" trigger
3. Room becomes occupied → URA lights fire → then `automation.test_enter` triggers
4. Check logs: `"[Office] Firing chained automation 'automation.test_enter' (trigger=enter)"`
5. Bind lux_dark → walk into dark room → lux drops below 50 → chained automation fires
6. Unbind (set to none) → trigger fires → no chained automation runs
7. Bind nonexistent automation → log warning, no crash

---

# M2: Coordinator Signal Triggers + Conflict Sensor (v3.10.1)

## Scope

- Add 4 coordinator signal triggers: house_state, energy_constraint, safety_hazard, security_event
- Extend config flow dropdown with new trigger types
- Conflict detection binary sensor

## Coordinator Signal Triggers

URA already has a signal dispatch system (`domain_coordinators/signals.py`). The room coordinator subscribes to signals and maps them to trigger events.

### Signal → Trigger Mapping

```python
# In coordinator.py — async_setup or __init__

# Subscribe to coordinator signals for trigger detection
from .domain_coordinators.signals import (
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_ENERGY_CONSTRAINT,
    SIGNAL_SAFETY_HAZARD,
    SIGNAL_SECURITY_EVENT,
)

async def _on_house_state_changed(self, signal_data) -> None:
    """Handle house state change signal."""
    new_state = signal_data.new_state  # e.g., "home_evening"
    # Check if any chained automation is bound to this specific state
    chains = self._get_config(CONF_AUTOMATION_CHAINS, {})
    trigger_key = f"house_state_{new_state}"
    if trigger_key in chains:
        await self._fire_chained_automations([trigger_key])
    # Also fire AI rules with house_state trigger type
    await self._execute_ai_rules_for_trigger("house_state", context={"state": new_state})
```

### Config Flow Extension

The house_state trigger needs a sub-selector for WHICH state transition to bind to. The config flow dropdown becomes:

```python
# Trigger options for M2
AUTOMATION_CHAIN_TRIGGERS_M2 = [
    "enter", "exit", "lux_dark", "lux_bright",
    # House state transitions
    "house_state_away", "house_state_arriving", "house_state_home_day",
    "house_state_home_evening", "house_state_home_night",
    "house_state_sleep", "house_state_waking",
    # Coordinator signals
    "energy_constraint",   # Any energy constraint change
    "safety_hazard",       # Any safety hazard detected
    "security_event",      # Any security event
]
```

Each gets a dropdown slot in the config flow. Most rooms will only use 2-3 of these.

### Grouping in Config Flow

To avoid a wall of 13+ dropdowns, group them into collapsible sections:

```
Occupancy Triggers:
  On room enter:     [dropdown]
  On room exit:      [dropdown]

Light Level Triggers:
  When room gets dark:    [dropdown]
  When room gets bright:  [dropdown]

House State Triggers:
  On home_evening:   [dropdown]
  On sleep:          [dropdown]
  On away:           [dropdown]
  ... (show all 7 states)

Coordinator Triggers:
  On energy constraint:  [dropdown]
  On safety hazard:      [dropdown]
  On security event:     [dropdown]
```

HA config flow doesn't support collapsible sections natively. Use separate sub-steps:
- `async_step_automation_chaining` → menu: Occupancy / Light / House State / Coordinator / Back
- Each sub-step shows only its relevant dropdowns

## Files Changed

| File | Changes |
|------|---------|
| `coordinator.py` | Signal subscriptions, `_on_house_state_changed()`, coordinator trigger dispatch |
| `config_flow.py` | Sub-step menus for trigger groups, coordinator trigger dropdowns |
| `const.py` | Extended trigger type list |
| `strings.json` | Trigger group labels, coordinator trigger names |

## Verification

1. Bind `automation.evening_scene` to `house_state_home_evening`
2. URA transitions to home_evening → chained automation fires
3. Bind `automation.energy_save` to `energy_constraint` → energy goes to peak → fires
4. Unbind → signal fires → no chained automation runs

---

# M3: AI NL Rules (v3.10.2)

## Scope

- `ai_task.generate_data` integration for NL rule parsing
- Person-specific enter/exit rules
- Rule management in options flow (add / list / delete)
- Rule validation (entity existence)
- Rule execution after trigger fire (after chained automations)
- Conflict detection binary sensor (AI rules vs URA built-in)

## Design

Follows Cycle 5 plan closely. Key differences from original:
- Uses the trigger infrastructure from M1/M2 (not a separate system)
- AI rules fire AFTER chained automations (third layer)
- Reuses `_get_room_entities_for_prompt()` pattern from Cycle 5

## Rule Data Model

Stored in `entry.options[CONF_AI_RULES]` as a list of dicts:

```python
{
    "rule_id": "a1b2c3d4",           # uuid4 hex[:8]
    "trigger_type": "enter",          # Any trigger from the trigger type list
    "person": "John",                 # Empty string = any person
    "description": "When John enters, set lights to 4000K and turn on desk lamp",
    "actions": [
        {
            "domain": "light",
            "service": "turn_on",
            "target": {"entity_id": "light.office_overhead"},
            "data": {"color_temp_kelvin": 4000, "brightness_pct": 100}
        },
        {
            "domain": "switch",
            "service": "turn_on",
            "target": {"entity_id": "switch.office_desk_lamp"},
            "data": {}
        }
    ],
    "enabled": true,
    "created_at": "2026-03-10T10:00:00",
    "ai_provider_used": "ai_task.claude_ai_task"
}
```

## AI Parsing

Direct `ai_task.generate_data` call — no wrapper class.

```python
# In config_flow.py

async def _parse_rule_with_ai(
    self,
    description: str,
    trigger_type: str,
    person: str,
) -> list[dict] | None:
    """Parse NL description into service call list via ai_task."""
    room_name = self._data.get(CONF_ROOM_NAME, "this room")
    room_entities = await self._get_room_entities_for_prompt()

    trigger_label = {
        "enter": f"{person or 'someone'} enters the room",
        "exit": f"{person or 'someone'} leaves the room",
        "lux_dark": "the room gets dark",
        "lux_bright": "the room gets bright",
    }.get(trigger_type, trigger_type)

    prompt = AI_RULE_PARSING_PROMPT.format(
        room_name=room_name,
        trigger_label=trigger_label,
        description=description,
        entities_json=json.dumps(room_entities, indent=2),
    )

    structure = {
        "actions": {
            "selector": {"object": {"multiple": True}},
            "description": (
                "List of HA service calls. Each must have: "
                "domain (string), service (string), "
                "target (object with entity_id string or list), "
                "data (object, may be empty {}). "
                "Use color_temp_kelvin not color_temp. "
                "Use brightness_pct (0-100) not brightness."
            ),
        }
    }

    try:
        result = await self.hass.services.async_call(
            "ai_task", "generate_data",
            {
                "task_name": "ura_parse_room_rule",
                "instructions": prompt,
                "structure": structure,
            },
            blocking=True,
            return_response=True,
        )
    except Exception as err:
        _LOGGER.error("ai_task failed during rule parsing: %s", err)
        return None

    if not result or not isinstance(result, dict):
        return None

    actions = result.get("data", {}).get("actions") or result.get("actions")
    if not isinstance(actions, list) or not actions:
        return None

    return actions
```

### Prompt Template

```python
AI_RULE_PARSING_PROMPT = """You are a Home Assistant automation rule parser.

TASK: Convert a natural language rule into a list of Home Assistant service calls.

ROOM: {room_name}
TRIGGER: When {trigger_label}
RULE: {description}

AVAILABLE ENTITIES IN THIS ROOM:
{entities_json}

REQUIREMENTS:
- Only use entity_ids from the available entities list above.
- Each service call must have: domain, service, target (with entity_id), data.
- Use exact entity_ids as shown — do not invent entity IDs.
- If a device is mentioned but not in the list, omit it.
- data may be an empty object {{}} if no parameters needed.
- For lights: use color_temp_kelvin (integer), brightness_pct (0-100).
- For media_player: use volume_level (0.0-1.0).
- For climate: use temperature (number).

Output only valid JSON. No explanation text."""
```

### Room Entity Discovery

```python
async def _get_room_entities_for_prompt(self) -> list[dict]:
    """Build entity list for AI context from room config + HA area."""
    entities = []
    seen = set()

    def add(entity_id: str) -> None:
        if entity_id in seen:
            return
        state = self.hass.states.get(entity_id)
        if not state:
            return
        seen.add(entity_id)
        entities.append({
            "entity_id": entity_id,
            "name": state.attributes.get("friendly_name", entity_id),
            "domain": entity_id.split(".")[0],
        })

    # Explicitly configured devices
    for key in (CONF_LIGHTS, CONF_FANS, CONF_AUTO_DEVICES, CONF_MANUAL_DEVICES,
                CONF_COVERS, CONF_AUTO_SWITCHES, CONF_MANUAL_SWITCHES):
        for eid in self._data.get(key, []):
            add(eid)

    if climate := self._data.get(CONF_CLIMATE_ENTITY):
        add(climate)

    # All entities in the room's HA area
    area_id = self._data.get(CONF_AREA_ID)
    if area_id:
        ent_reg = er.async_get(self.hass)
        for entity in ent_reg.entities.values():
            if entity.area_id == area_id and not entity.disabled:
                add(entity.entity_id)

    return entities
```

### Validation

```python
def _validate_parsed_actions(self, actions: list[dict]) -> tuple[bool, list[str]]:
    """Validate AI-parsed actions. Entity existence + structure checks."""
    errors = []
    for i, action in enumerate(actions):
        label = f"Action {i + 1}"
        for key in ("domain", "service", "target"):
            if key not in action:
                errors.append(f"{label}: missing '{key}'")
        target = action.get("target", {})
        entity_id = target.get("entity_id")
        if entity_id:
            eids = entity_id if isinstance(entity_id, list) else [entity_id]
            for eid in eids:
                if not self.hass.states.get(eid):
                    errors.append(f"{label}: entity '{eid}' not found")
        if "data" in action and not isinstance(action["data"], dict):
            errors.append(f"{label}: 'data' must be an object")
    return len(errors) == 0, errors
```

## Config Flow Steps

### Options menu addition

```
Room Options → Manage AI Rules → [Add Rule / View Rules / Back]
```

### Add Rule step

Form fields:
- **Trigger**: Select (enter, exit, lux_dark, lux_bright + M2 triggers if available)
- **Person** (optional): Text input — leave blank for any person
- **Description**: Multiline text — the NL rule description

On submit: call `_parse_rule_with_ai()` → validate → store in `CONF_AI_RULES` list.

### List Rules step

Shows existing rules with description + trigger + person. Select one to delete.

### Delete Rule step

Confirmation, then remove from `CONF_AI_RULES` list.

## Rule Execution

```python
# In coordinator.py — called after chained automations

async def _execute_ai_rules(self, triggers: list[str]) -> None:
    """Execute AI rules matching fired triggers."""
    rules = self._get_config(CONF_AI_RULES, [])
    if not rules:
        return

    room_name = self.entry.data.get(CONF_ROOM_NAME, "unknown")
    identified_persons = self._get_identified_persons_in_room()

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if rule.get("trigger_type") not in triggers:
            continue

        # Person filter
        person_filter = rule.get("person", "").strip()
        if person_filter:
            match = any(
                person_filter.lower() == p.lower()
                for p in identified_persons
            )
            if not match:
                continue

        _LOGGER.info(
            "[%s] Executing AI rule '%s' (trigger=%s, person='%s'): %s",
            room_name, rule.get("rule_id"), rule.get("trigger_type"),
            person_filter or "any", rule.get("description", ""),
        )

        for action in rule.get("actions", []):
            await self._execute_rule_action(action, room_name)


async def _execute_rule_action(self, action: dict, room_name: str) -> None:
    """Execute a single parsed service call."""
    domain = action.get("domain")
    service = action.get("service")
    target = action.get("target", {})
    data = {**action.get("data", {})}

    if not domain or not service:
        return

    entity_id = target.get("entity_id")
    if entity_id:
        data["entity_id"] = entity_id

    try:
        await asyncio.wait_for(
            self.hass.services.async_call(domain, service, data, blocking=False),
            timeout=5.0,
        )
    except Exception as err:
        _LOGGER.error("[%s] AI rule action failed: %s.%s — %s", room_name, domain, service, err)
```

### Person identification source

```python
def _get_identified_persons_in_room(self) -> list[str]:
    """Get identified persons from census or BLE fallback."""
    room_name = self.entry.data.get(CONF_ROOM_NAME, "")

    # Census (cameras + BLE fusion)
    census = self.hass.data.get(DOMAIN, {}).get("census")
    if census is not None:
        result = census.get_room_identified_persons(room_name)
        if result is not None:
            return result

    # BLE-only fallback
    person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
    if person_coord is not None:
        return person_coord.get_persons_in_room(room_name)

    return []
```

## Files Changed

| File | Changes |
|------|---------|
| `const.py` | `CONF_AI_RULES`, `CONF_AI_RULE_*` constants, `AI_RULE_PARSING_PROMPT` |
| `coordinator.py` | `_execute_ai_rules()`, `_execute_rule_action()`, `_get_identified_persons_in_room()`, `_detect_ai_rule_conflicts()`, integration in trigger flow |
| `config_flow.py` | `async_step_ai_rules_menu()`, `async_step_ai_rule_add()`, `async_step_ai_rule_list()`, `async_step_ai_rule_delete()`, `_parse_rule_with_ai()`, `_get_room_entities_for_prompt()`, `_validate_parsed_actions()` |
| `binary_sensor.py` | `RoomAutomationConflictSensor` |
| `strings.json` | AI rules step strings, error messages |
| `translations/en.json` | Mirror |

## Conflict Sensor (AI Rules Only)

Conflict detection is scoped to AI rules because their parsed `actions` contain explicit entity targets. Simple set intersection with URA built-in targets — no timing window, fully deterministic.

### Detection

```python
# In coordinator.py — called during AI rule execution

def _detect_ai_rule_conflicts(self, rule: dict, trigger: str) -> None:
    """Detect entity conflicts between AI rule actions and URA built-in automation.

    Compares entity_ids targeted by the AI rule's parsed actions against
    entities URA's built-in automation acted on for the same trigger.
    """
    # Entities URA built-in automation targeted for this trigger
    ura_entities = set(self._get_builtin_target_entities(trigger))
    if not ura_entities:
        return

    # Entities this AI rule will target
    rule_entities = set()
    for action in rule.get("actions", []):
        target = action.get("target", {})
        entity_id = target.get("entity_id")
        if entity_id:
            if isinstance(entity_id, list):
                rule_entities.update(entity_id)
            else:
                rule_entities.add(entity_id)

    # Intersection = conflict
    contested = ura_entities & rule_entities
    if contested:
        conflict = {
            "rule_id": rule.get("rule_id"),
            "rule_description": rule.get("description", ""),
            "trigger": trigger,
            "contested_entities": sorted(contested),
            "timestamp": dt_util.utcnow().isoformat(),
        }
        self._last_conflicts.append(conflict)
        self._conflict_detected = True
        _LOGGER.warning(
            "[%s] AI rule '%s' conflicts with built-in automation on: %s",
            self._room_name, rule.get("rule_id"), ", ".join(contested),
        )


def _get_builtin_target_entities(self, trigger: str) -> list[str]:
    """Return entities that URA built-in automation targets for a trigger.

    Enter: configured lights, fans, climate
    Exit: configured lights, fans, auto_devices, auto_switches
    """
    entities = []
    if trigger in ("enter", "lux_dark"):
        entities.extend(self._get_config(CONF_LIGHTS, []))
        entities.extend(self._get_config(CONF_FANS, []))
        if climate := self._get_config(CONF_CLIMATE_ENTITY):
            entities.append(climate)
    elif trigger in ("exit", "lux_bright"):
        entities.extend(self._get_config(CONF_LIGHTS, []))
        entities.extend(self._get_config(CONF_FANS, []))
        entities.extend(self._get_config(CONF_AUTO_DEVICES, []))
        entities.extend(self._get_config(CONF_AUTO_SWITCHES, []))
    return entities
```

### Binary Sensor

```python
# binary_sensor.{room}_automation_conflict

class RoomAutomationConflictSensor(BinarySensorEntity):
    """Detects when AI rules and URA built-in automation target the same entity."""

    @property
    def is_on(self) -> bool:
        return self.coordinator._conflict_detected

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "last_conflicts": self.coordinator._last_conflicts,
            "conflict_count": len(self.coordinator._last_conflicts),
        }
```

Auto-clears on next trigger event with no conflict.

## Verification

1. No AI configured → add rule → error: "AI parsing failed"
2. Add rule: enter, person=blank, "Turn on overhead light" → parses → validates → stored
3. Room enter → URA lights → chained automation → AI rule fires → overhead light on
4. Person-specific: enter, person="John", "Set lights to 4000K" → John enters → fires. Jane enters → skips.
5. Hallucinated entity → validation catches → error shown
6. Delete rule → confirm → removed from config
7. Rule with disabled=false → trigger fires → rule skips
8. AI rule targets `light.office_overhead` (also in URA lights config) → conflict sensor fires, attributes show contested entity + rule_id
9. AI rule targets `switch.desk_lamp` (NOT in URA config) → no conflict

---

# M4: Polish — Rule List UI, Diagnostics, Tests (v3.10.3)

## Scope

- Improved rule list display in config flow
- Diagnostic sensor for rule execution history
- Conflict sensor tuning
- Unit tests for trigger detection, rule parsing, conflict detection
- README cycle doc

## Diagnostic Sensor

```python
# sensor: sensor.{room}_ai_automation_status

class AIAutomationStatusSensor(SensorEntity):
    """Tracks AI rule and automation chain execution."""

    @property
    def native_value(self) -> str:
        return "active" if self.coordinator._ai_rules_enabled else "inactive"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "chained_automations": self.coordinator._get_config(CONF_AUTOMATION_CHAINS, {}),
            "ai_rules_count": len(self.coordinator._get_config(CONF_AI_RULES, [])),
            "last_trigger": self.coordinator._last_trigger_event,
            "last_trigger_time": self.coordinator._last_trigger_time,
            "last_conflict": self.coordinator._last_conflicts,
            "rules_fired_today": self.coordinator._rules_fired_count,
        }
```

## Tests

```python
# quality/tests/test_ai_automation.py

class TestLuxTriggerDetection:
    """Test lux threshold crossing detection."""
    - test_dark_transition (lux 100 → 40 = lux_dark)
    - test_bright_transition (lux 100 → 250 = lux_bright)
    - test_hysteresis_no_flap (lux 55 → 45 → 55 = one dark, no bright)
    - test_first_reading_no_trigger (lux None → 30 = no trigger)

class TestAutomationChaining:
    """Test chained automation execution."""
    - test_enter_fires_chained
    - test_exit_fires_chained
    - test_no_binding_no_fire
    - test_unavailable_automation_warns
    - test_multiple_triggers_parallel

class TestAIRuleParsing:
    """Test rule validation (AI call is mocked)."""
    - test_valid_actions_pass
    - test_missing_domain_fails
    - test_nonexistent_entity_fails
    - test_empty_data_allowed

class TestAIRuleExecution:
    """Test rule execution with person filtering."""
    - test_any_person_rule_fires
    - test_person_specific_fires_on_match
    - test_person_specific_skips_on_mismatch
    - test_disabled_rule_skips
    - test_wrong_trigger_skips

class TestConflictDetection:
    """Test conflict sensor."""
    - test_no_conflict_when_different_entities
    - test_conflict_detected_same_entity
    - test_conflict_auto_clears
```

## Files Changed

| File | Changes |
|------|---------|
| `sensor.py` | `AIAutomationStatusSensor` |
| `binary_sensor.py` | Conflict sensor auto-clear logic |
| `coordinator.py` | Execution counters, last trigger tracking |
| `quality/tests/test_ai_automation.py` | New test file (~25 tests) |

---

## EXECUTION ORDER SUMMARY

```
Trigger fires (enter/exit/lux/house_state/coordinator)
    │
    ▼
1. URA built-in automation (automation.py)
   - Lights, climate, covers, fans
    │
    ▼
2. Chained HA automation (automation.trigger)
   - 1 per trigger, parallel execution
    │
    ▼
3. AI NL rules (parsed service calls)
   - Person-filtered, sequential per rule
    │
    ▼
4. Conflict detection (2s observation window)
   - Updates binary_sensor.{room}_automation_conflict
```

---

## CONSTANTS SUMMARY (all milestones)

```python
# v3.10.0 Automation Chaining
CONF_AUTOMATION_CHAINS: Final = "automation_chains"

# v3.10.0 Lux triggers
LUX_DARK_THRESHOLD: Final = 50
LUX_BRIGHT_THRESHOLD: Final = 200

# v3.10.2 AI Rules
CONF_AI_RULES: Final = "ai_rules"
CONF_AI_RULE_TRIGGER: Final = "ai_rule_trigger"
CONF_AI_RULE_PERSON: Final = "ai_rule_person"
CONF_AI_RULE_DESCRIPTION: Final = "ai_rule_description"

# Trigger types (full list after M2)
TRIGGER_ENTER: Final = "enter"
TRIGGER_EXIT: Final = "exit"
TRIGGER_LUX_DARK: Final = "lux_dark"
TRIGGER_LUX_BRIGHT: Final = "lux_bright"
TRIGGER_HOUSE_STATE_PREFIX: Final = "house_state_"
TRIGGER_ENERGY_CONSTRAINT: Final = "energy_constraint"
TRIGGER_SAFETY_HAZARD: Final = "safety_hazard"
TRIGGER_SECURITY_EVENT: Final = "security_event"
```

---

## RISK MITIGATION

| Risk | Mitigation |
|------|------------|
| AI provider unavailable | `ServiceNotFound` caught, clear error in config flow |
| AI hallucinates entity IDs | Validation checks entity existence before storing |
| Chained automation is deleted | Check entity state before triggering, log warning |
| Lux sensor flapping | Hysteresis via 3-zone model (dark/mid/bright) |
| Conflict detection false positives | 2s window + context ID comparison filters URA's own writes |
| Person identification unavailable | Person-specific rules silently skip, any-person rules still work |
| Config entry size (many rules) | Practical limit: ~50 rules before JSON gets unwieldy. Not a concern for home use. |

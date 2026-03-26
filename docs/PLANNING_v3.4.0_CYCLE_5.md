# PLANNING: v3.4.0 Cycle 5 — AI Custom Automation (Person-Specific Rules)

**Version:** 1.0
**Date:** 2026-02-23
**Parent:** PLANNING_v3_4_0_REVISED.md (original vision)
**Status:** Planning
**Depends on:** v3.5.1 (room-level person identification from camera+BLE fusion)

---

## OVERVIEW

Cycle 5 adds natural language automation rules that can be scoped to specific people. When John enters the office, set the lights to 4000K and turn on the desk lamp. When the last person leaves the kitchen, turn off the coffee maker.

This is the key differentiator from basic HA automations: rules know WHO entered or left, because the census from v3.5.1 provides `identified_persons` per room. Person-specific rules consume that data. Rules without a person filter work for any occupancy change, which makes the feature useful even without cameras or on BLE-only setups.   

**Scope boundary:** Two trigger types only — room-enter and room-exit. The AI parses natural language into structured service calls at rule creation time. At execution time, URA checks the census and calls the pre-parsed service calls directly. No AI inference at runtime.

**What this is NOT:**
- Schedule-based rules (use HA automations for that)
- Compound conditions with and/or/not logic
- AI that learns from behavior patterns over time
- A custom AI service abstraction layer (the revised plan proposed one; the simplified scope does not need it)
- Rule conflict resolution (rules execute independently — last writer wins on the device)

---

## DESIGN DECISIONS

### Parse once, execute many

The AI is called exactly once per rule: when the user saves it. The output is a list of structured service calls stored in the config entry. At execution time, URA reads those stored service calls and fires them directly. This means:

- Runtime is deterministic and fast — no AI latency in the automation path
- Rules survive AI provider downtime
- The stored representation is inspectable and auditable

### Direct `ai_task` usage

No wrapper class. The config flow calls `hass.services.async_call("ai_task", "generate_data", ...)` directly with a `structure` parameter that constrains the output to the service call format. This is three lines of code, not a module.

The revised plan proposed a reusable `URAIService` class with provider fallback chains. That is appropriate if multiple coordinators need AI at runtime. For parse-once-at-config-time, it is over-engineering. A single direct call with error handling is sufficient.

### Rule storage in config entry data

Rules are stored as a list under `CONF_AI_RULES` in the room's config entry data. Each rule is a dict. No separate database table — the SQLite database already used for occupancy patterns does not need to store rules, which are configuration, not telemetry.

### Person identification source

Person-specific rules rely on `identified_persons` from the census. In v3.5.1, the room coordinator exposes which named persons are currently in the room. This is the only data source for person matching — no additional person tracking is added in this cycle.

On setups without cameras, BLE-tracked persons from Bermuda provide the `identified_persons` list at lower confidence. Rules still work; they just have lower confidence in identification. Rules without a person filter (`person: ""`) always execute on any occupancy change and have no camera/BLE dependency at all.

---

## IMPLEMENTATION

### Rule data model

Each rule is a plain dict stored in config entry data. No dataclass is needed because HA config entries serialize to JSON natively.

```python
# Rule structure (stored in entry.data[CONF_AI_RULES])
{
    "rule_id": "abc123",           # uuid4 hex, generated at creation time
    "trigger_type": "enter",       # "enter" or "exit"
    "person": "John",              # Person name from census. Empty string = any person.
    "description": "When John enters the office, set lights to 4000K and turn on the desk lamp",
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
    "created_at": "2026-02-23T10:00:00",
    "ai_provider_used": "claude"   # For diagnostics. Which provider parsed the rule.
}
```

Fields:
- `rule_id` — `uuid.uuid4().hex[:8]`. Short enough to be readable in logs, unique enough for a home's scale.
- `trigger_type` — `"enter"` or `"exit"`. Enter fires when `occupied` transitions False → True. Exit fires when `occupied` transitions True → False.
- `person` — If non-empty, rule only fires when this person's name appears in `identified_persons` for the room. Case-insensitive match. If empty, fires on any occupancy change.
- `description` — The original natural language text the user wrote. Stored for display in the UI and for re-parsing if the user edits.
- `actions` — List of service call dicts. Each has `domain`, `service`, `target`, and `data`. Passed directly to `hass.services.async_call`.
- `enabled` — Boolean. Allows disabling a rule without deleting it.
- `created_at` — ISO timestamp. For display ordering.
- `ai_provider_used` — Which AI entity_id was used. For diagnostics.

### AI parsing at rule creation time

The config flow collects the user's natural language description and calls `ai_task.generate_data`. The prompt includes the room name, the list of entities in the room (so the AI can resolve "desk lamp" to `switch.office_desk_lamp`), and the rule text. The `structure` parameter constrains the AI output to the actions list format.

```python
# In config_flow.py — async_step_ai_rule_add()

async def _parse_rule_with_ai(
    self,
    description: str,
    trigger_type: str,
    person: str,
) -> list[dict] | None:
    """Call ai_task to parse natural language into service call list.

    Returns list of action dicts on success, None on failure.
    """
    room_name = self._data.get(CONF_ROOM_NAME, "this room")
    room_entities = await self._get_room_entities_for_prompt()

    prompt = AI_RULE_PARSING_PROMPT.format(
        room_name=room_name,
        trigger_type=trigger_type,
        person=person or "any person",
        description=description,
        entities_json=json.dumps(room_entities, indent=2),
    )

    structure = {
        "actions": {
            "selector": {"object": {"multiple": True}},
            "description": (
                "List of HA service calls to execute. Each item must have: "
                "domain (string), service (string), "
                "target (object with entity_id string or list), "
                "data (object, may be empty)."
            ),
        }
    }

    try:
        result = await self.hass.services.async_call(
            domain="ai_task",
            service="generate_data",
            service_data={
                "task_name": "ura_parse_room_rule",
                "instructions": prompt,
                "structure": structure,
            },
            blocking=True,
            return_response=True,
        )
    except Exception as err:
        _LOGGER.error("ai_task call failed during rule parsing: %s", err)
        return None

    if not result or not isinstance(result, dict):
        _LOGGER.error("ai_task returned empty or non-dict result")
        return None

    actions = result.get("data", {}).get("actions") or result.get("actions")
    if not isinstance(actions, list) or len(actions) == 0:
        _LOGGER.error("ai_task returned no actions: %s", result)
        return None

    return actions
```

**Why not check for an ai_task entity first?**

If `ai_task.generate_data` is not available, the service call raises `ServiceNotFound`. The `except Exception` block catches it, logs it, and returns `None`. The config flow then shows an error telling the user that no AI provider is configured. This is simpler than probing entity states before calling.

### AI prompt template

```python
# In const.py or a new ai_rules.py

AI_RULE_PARSING_PROMPT = """You are a Home Assistant automation rule parser for the Universal Room Automation (URA) integration.

TASK: Convert a natural language rule description into a list of Home Assistant service calls.

ROOM: {room_name}
TRIGGER: When {trigger_type} event fires ({person} {enters_or_exits} the room)
RULE: {description}

AVAILABLE ENTITIES IN THIS ROOM:
{entities_json}

REQUIREMENTS:
- Only use entity_ids from the available entities list above.
- Output a JSON object with a single key "actions" containing a list of service call objects.
- Each service call object must have: domain, service, target (with entity_id), data.
- Use exact entity_ids as shown — do not guess or invent entity IDs.
- If the rule mentions a device not in the list, omit it and proceed with what is available.
- data may be an empty object {{}} if the service needs no parameters.
- For lights: use color_temp_kelvin (integer) not color_temp, brightness_pct (0-100) not brightness.
- For media_player volume: use volume_level (0.0 to 1.0).

EXAMPLE OUTPUT:
{{
  "actions": [
    {{
      "domain": "light",
      "service": "turn_on",
      "target": {{"entity_id": "light.office_overhead"}},
      "data": {{"color_temp_kelvin": 4000, "brightness_pct": 100}}
    }},
    {{
      "domain": "switch",
      "service": "turn_on",
      "target": {{"entity_id": "switch.office_desk_lamp"}},
      "data": {{}}
    }}
  ]
}}

Output only valid JSON. No explanation text."""
```

The prompt gets `enters_or_exits` substituted from the trigger_type: `"enters"` for `"enter"`, `"leaves"` for `"exit"`.

### Gathering room entities for the prompt

The config flow needs to build a list of entities relevant to the room before calling the AI, so the AI can resolve "desk lamp" to an entity ID. This reuses existing coordinator patterns.

```python
# In config_flow.py

async def _get_room_entities_for_prompt(self) -> list[dict]:
    """Return a simplified list of room entities for AI context.

    Uses the room's HA area_id to find entities, supplemented
    by explicitly configured device lists.
    """
    entities = []
    seen = set()

    def add_entity(entity_id: str) -> None:
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
            "state": state.state,
        })

    # Devices explicitly configured for this room
    for key in (CONF_LIGHTS, CONF_FANS, CONF_AUTO_DEVICES, CONF_MANUAL_DEVICES,
                CONF_COVERS, CONF_AUTO_SWITCHES, CONF_MANUAL_SWITCHES):
        for eid in self._data.get(key, []):
            add_entity(eid)

    # Climate entity
    if climate := self._data.get(CONF_CLIMATE_ENTITY):
        add_entity(climate)

    # Entities in the room's HA area (catches media players, etc.)
    area_id = self._data.get(CONF_AREA_ID)
    if area_id:
        ent_reg = er.async_get(self.hass)
        for entity in ent_reg.entities.values():
            if entity.area_id == area_id and not entity.disabled:
                add_entity(entity.entity_id)

    return entities
```

### Validating parsed actions before storage

After AI parsing returns an `actions` list, URA validates each action before storing the rule. Validation is intentionally minimal — just enough to catch hallucinated entity IDs.

```python
# In config_flow.py

def _validate_parsed_actions(self, actions: list[dict]) -> tuple[bool, list[str]]:
    """Validate AI-parsed actions.

    Returns (is_valid, list_of_error_messages).
    Intentionally lenient: structure checks + entity existence only.
    """
    errors = []

    for i, action in enumerate(actions):
        label = f"Action {i + 1}"

        # Required keys
        for key in ("domain", "service", "target"):
            if key not in action:
                errors.append(f"{label}: missing required key '{key}'")

        # Entity existence
        target = action.get("target", {})
        entity_id = target.get("entity_id")
        if entity_id:
            if isinstance(entity_id, list):
                for eid in entity_id:
                    if not self.hass.states.get(eid):
                        errors.append(f"{label}: entity '{eid}' not found in HA")
            elif isinstance(entity_id, str):
                if not self.hass.states.get(entity_id):
                    errors.append(f"{label}: entity '{entity_id}' not found in HA")

        # data must be a dict (may be empty)
        if "data" in action and not isinstance(action["data"], dict):
            errors.append(f"{label}: 'data' must be an object")

    return len(errors) == 0, errors
```

### Config flow step: adding a rule

The config flow gets a new step `async_step_ai_rule_add`. This step is NOT in the initial setup flow (users don't have to create rules to set up a room). It is accessible from the options flow, under a "Manage AI Rules" menu option — the same pattern used by "Manage Zones" added in v3.3.3.

```python
# In config_flow.py OptionsFlowHandler

async def async_step_ai_rules_menu(self, user_input=None):
    """Show AI rules management menu."""
    return self.async_show_menu(
        step_id="ai_rules_menu",
        menu_options=["ai_rule_add", "ai_rule_list", "init"],
    )

async def async_step_ai_rule_add(self, user_input=None):
    """Add a new AI rule via natural language input."""
    errors = {}
    description_placeholders = {}

    if user_input is not None:
        description = user_input.get(CONF_AI_RULE_DESCRIPTION, "").strip()
        trigger_type = user_input.get(CONF_AI_RULE_TRIGGER, "enter")
        person = user_input.get(CONF_AI_RULE_PERSON, "").strip()

        if not description:
            errors[CONF_AI_RULE_DESCRIPTION] = "required"
        else:
            # Call AI to parse rule
            actions = await self._parse_rule_with_ai(description, trigger_type, person)

            if actions is None:
                errors["base"] = "ai_parsing_failed"
                description_placeholders["error"] = (
                    "AI parsing failed. Ensure an AI provider (Claude, OpenAI, or Google) "
                    "is configured in Home Assistant Settings > AI Assistants."
                )
            else:
                is_valid, validation_errors = self._validate_parsed_actions(actions)

                if not is_valid:
                    errors["base"] = "validation_failed"
                    description_placeholders["validation_errors"] = "\n".join(validation_errors)
                else:
                    # Store the rule
                    import uuid
                    from datetime import datetime

                    new_rule = {
                        "rule_id": uuid.uuid4().hex[:8],
                        "trigger_type": trigger_type,
                        "person": person,
                        "description": description,
                        "actions": actions,
                        "enabled": True,
                        "created_at": datetime.now().isoformat(),
                        "ai_provider_used": "ai_task",
                    }

                    existing_rules = list(self.options.get(CONF_AI_RULES, []))
                    existing_rules.append(new_rule)

                    return self.async_create_entry(
                        title="",
                        data={**self.options, CONF_AI_RULES: existing_rules},
                    )

    return self.async_show_form(
        step_id="ai_rule_add",
        data_schema=vol.Schema({
            vol.Required(CONF_AI_RULE_TRIGGER, default="enter"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["enter", "exit"],
                    translation_key="ai_rule_trigger",
                )
            ),
            vol.Optional(CONF_AI_RULE_PERSON, default=""): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                )
            ),
            vol.Required(CONF_AI_RULE_DESCRIPTION): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    multiline=True,
                )
            ),
        }),
        errors=errors,
        description_placeholders=description_placeholders,
    )
```

### Rule execution in the coordinator

The coordinator already tracks occupancy transitions in `_async_update_data`. The occupancy transition is the moment `occupied` flips from its previous value. Rules are evaluated at that moment.

The coordinator needs to know the previous occupancy state to detect a transition. It already tracks `_last_occupied_state` for the 4-hour failsafe and energy calculations. Reuse that.

```python
# In coordinator.py — _async_update_data(), after the occupied boolean is determined

# --- AI Rules execution ---
# Compare current occupancy to previous to detect enter/exit transition
previous_occupied = self._last_occupied_state
current_occupied = data[STATE_OCCUPIED]

if current_occupied != previous_occupied:
    trigger_type = "enter" if current_occupied else "exit"
    await self._execute_ai_rules(trigger_type)

# (existing line that updates _last_occupied_state)
self._last_occupied_state = current_occupied
```

```python
# In coordinator.py — new method

async def _execute_ai_rules(self, trigger_type: str) -> None:
    """Execute AI rules matching the given trigger type.

    Called when room occupancy transitions. Checks each enabled rule
    with matching trigger_type, then evaluates person filter against
    census identified_persons if a person is specified.
    """
    rules = self._get_config(CONF_AI_RULES, [])
    if not rules:
        return

    room_name = self.entry.data.get(CONF_ROOM_NAME, "unknown")

    # Get current identified persons in this room from census.
    # Census is stored on hass.data[DOMAIN]["census"] by v3.5.1.
    # On setups without census, identified_persons is empty — person-specific
    # rules will not fire, but rules with person="" still fire.
    identified_persons = self._get_identified_persons_in_room()

    for rule in rules:
        if not rule.get("enabled", True):
            continue

        if rule.get("trigger_type") != trigger_type:
            continue

        person_filter = rule.get("person", "").strip()

        if person_filter:
            # Person-specific rule: only fire if person is in the room
            match = any(
                person_filter.lower() == p.lower()
                for p in identified_persons
            )
            if not match:
                _LOGGER.debug(
                    "[%s] AI rule '%s' skipped — '%s' not in identified_persons %s",
                    room_name,
                    rule.get("rule_id"),
                    person_filter,
                    identified_persons,
                )
                continue

        _LOGGER.info(
            "[%s] Executing AI rule '%s' (trigger=%s, person='%s'): %s",
            room_name,
            rule.get("rule_id"),
            trigger_type,
            person_filter or "any",
            rule.get("description", ""),
        )

        for action in rule.get("actions", []):
            await self._execute_rule_action(action, room_name)


async def _execute_rule_action(self, action: dict, room_name: str) -> None:
    """Execute a single parsed service call action."""
    domain = action.get("domain")
    service = action.get("service")
    target = action.get("target", {})
    data = action.get("data", {})

    if not domain or not service:
        _LOGGER.warning(
            "[%s] AI rule action missing domain or service: %s",
            room_name, action,
        )
        return

    service_data = {**data}
    if target:
        entity_id = target.get("entity_id")
        if entity_id:
            service_data["entity_id"] = entity_id

    try:
        await asyncio.wait_for(
            self.hass.services.async_call(
                domain,
                service,
                service_data,
                blocking=False,
            ),
            timeout=5.0,
        )
        _LOGGER.debug(
            "[%s] AI rule action executed: %s.%s on %s",
            room_name, domain, service, target,
        )
    except asyncio.TimeoutError:
        _LOGGER.error(
            "[%s] AI rule action timed out: %s.%s on %s",
            room_name, domain, service, target,
        )
    except Exception as err:
        _LOGGER.error(
            "[%s] AI rule action failed: %s.%s — %s",
            room_name, domain, service, err,
        )


def _get_identified_persons_in_room(self) -> list[str]:
    """Get the list of identified persons currently in this room.

    Source: v3.5.1 census, accessed via hass.data[DOMAIN]["census"].
    Each room coordinator knows its own room_name, which is the key
    used by the census to store per-room person lists.

    Falls back to BLE-only person tracking (person_coordinator) if
    census is not available (no cameras configured).

    Returns empty list if no identification data is available.
    """
    room_name = self.entry.data.get(CONF_ROOM_NAME, "")

    # Try full census (v3.5.1 — cameras + BLE fusion)
    census = self.hass.data.get(DOMAIN, {}).get("census")
    if census is not None:
        room_result = census.get_room_identified_persons(room_name)
        if room_result is not None:
            return room_result

    # Fallback: BLE-only via person_coordinator
    person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
    if person_coordinator is not None:
        return person_coordinator.get_persons_in_room(room_name)

    return []
```

### Exit trigger and "last person leaves" semantics

For rules like "When the last person leaves the kitchen, turn off the coffee maker", the trigger is `exit`. URA fires exit rules when occupancy transitions from True to False (occupied → vacant). At that moment, the room is already vacant, so the census should show zero persons. The rule fires without a person filter (`person: ""`), which matches any exit event — including the event where the last person left.

If the user writes "When John leaves the kitchen, turn off the coffee maker", the rule sets `person: "John"`. The exit trigger fires and checks whether John was in the identified_persons list at the moment of the transition. Since the census updates incrementally and the person list reflects the state at the time of the event, John's name should still be in the list when the exit fires (the coordinator fires rules immediately on occupancy change detection, before the census catches up to "zero persons"). If census timing causes John's name to already be removed, the rule silently skips. This is an acceptable false-negative — better than a false-positive.

**Implementation note:** Person-specific exit rules have inherently weaker reliability than enter rules, because by definition the person is leaving. Document this limitation clearly for users.

---

## ENTITIES

Cycle 5 does not add new HA entities. Rules are configuration stored in the config entry, not runtime state entities. The only new observable state is the diagnostic logging when rules fire.

If in a future cycle users want visibility into rule execution, a `sensor.{room}_last_ai_rule_fired` entity could be added. That is explicitly out of scope here.

---

## FILES TO CREATE/MODIFY

### `const.py` — Add new constants

```python
# ============================================================================
# v3.4.0 AI Custom Automation Rules
# ============================================================================

# Config keys
CONF_AI_RULES: Final = "ai_rules"                    # list of rule dicts stored in entry
CONF_AI_RULE_TRIGGER: Final = "ai_rule_trigger"      # "enter" or "exit"
CONF_AI_RULE_PERSON: Final = "ai_rule_person"        # person name filter (empty = any)
CONF_AI_RULE_DESCRIPTION: Final = "ai_rule_description"  # natural language text

# AI parsing prompt — stored here so it is versioned with the integration
AI_RULE_PARSING_PROMPT: Final = """..."""  # (full prompt text as shown above)

# Rule trigger types
AI_RULE_TRIGGER_ENTER: Final = "enter"
AI_RULE_TRIGGER_EXIT: Final = "exit"
```

### `coordinator.py` — Add rule execution

Modify `_async_update_data()` to detect occupancy transitions and call `_execute_ai_rules()`.

Add three new methods:
- `_execute_ai_rules(trigger_type: str) -> None`
- `_execute_rule_action(action: dict, room_name: str) -> None`
- `_get_identified_persons_in_room() -> list[str]`

No changes to the coordinator's initialization — rules are read from `_get_config(CONF_AI_RULES, [])` at execution time, which already picks up config entry changes via the existing options/data fallback pattern.

### `config_flow.py` — Add rule management to options flow

Add to `OptionsFlowHandler`:
- `async_step_ai_rules_menu()` — menu step with Add Rule / View Rules / Back options
- `async_step_ai_rule_add()` — form for adding a new rule
- `async_step_ai_rule_list()` — read-only list of existing rules (select one to delete)
- `async_step_ai_rule_delete()` — confirmation step for deleting a selected rule
- `_parse_rule_with_ai()` — helper that calls `ai_task.generate_data`
- `_get_room_entities_for_prompt()` — helper that builds entity list for the AI prompt
- `_validate_parsed_actions()` — helper that validates entity IDs in parsed actions

Add "Manage AI Rules" option to the existing options flow main menu (the same menu that contains "Manage Zones").

### `strings.json` — Add UI strings

```json
"step": {
    "ai_rules_menu": {
        "title": "AI Automation Rules",
        "description": "Manage natural language automation rules for this room."
    },
    "ai_rule_add": {
        "title": "Add Automation Rule",
        "description": "Describe what should happen in plain English. The AI will parse your description into automation actions.",
        "data": {
            "ai_rule_trigger": "Trigger",
            "ai_rule_person": "Person (optional — leave blank for any person)",
            "ai_rule_description": "Rule description"
        }
    },
    "ai_rule_list": {
        "title": "Existing Rules",
        "description": "Select a rule to delete it, or go back to add a new one."
    }
},
"error": {
    "ai_parsing_failed": "AI parsing failed. {error}",
    "validation_failed": "Parsed actions contain invalid entities:\n{validation_errors}"
},
"selector": {
    "ai_rule_trigger": {
        "options": {
            "enter": "Person enters the room",
            "exit": "Person leaves the room"
        }
    }
}
```

### No new files required

The original plan proposed a full `ai/` module hierarchy and a `custom_automation/` package. That is not needed for the simplified scope. All new code fits in the three existing files above (const.py, coordinator.py, config_flow.py).

---

## VERIFICATION

The following scenarios must be manually verified. No automated test harness is assumed — match the pattern used by prior cycles.

**1. No AI provider configured**
- Add a rule via options flow.
- ai_task call raises ServiceNotFound.
- Config flow shows error: "AI parsing failed. Ensure an AI provider is configured."
- No partial rule is stored.

**2. Rule added successfully (any-person enter rule)**
- Configure Claude, OpenAI, or Google AI in HA.
- Add rule: trigger=enter, person=(blank), description="When someone enters the office, turn on the overhead light."
- Flow calls `ai_task.generate_data` and receives actions containing `light.turn_on` for the office overhead.
- Validation passes — entity exists.
- Rule appears in `entry.options[CONF_AI_RULES]`.
- Room becomes occupied → rule fires → `light.office_overhead` turns on.
- Check HA logs: `"[Office] Executing AI rule 'abc123' (trigger=enter, person='any'): When someone enters..."`

**3. Person-specific enter rule — person present**
- Add rule: trigger=enter, person="John", description="When John enters the office, set lights to 4000K."
- Census (v3.5.1) identifies John in the office.
- Room becomes occupied with John identified → rule fires → lights set to 4000K.

**4. Person-specific enter rule — different person enters**
- Same rule as above (person="John").
- Room becomes occupied but census identifies "Jane", not "John".
- Rule does NOT fire.
- Log shows: `"[Office] AI rule 'abc123' skipped — 'John' not in identified_persons ['Jane']"`

**5. Exit rule — last person leaves**
- Add rule: trigger=exit, person=(blank), description="When the last person leaves the kitchen, turn off the coffee maker."
- Kitchen becomes vacant → rule fires → `switch.kitchen_coffee_maker` turns off.

**6. Exit rule — person-specific**
- Add rule: trigger=exit, person="John", description="When John leaves the office, turn off the desk lamp."
- John is in the room. Room transitions to vacant with John as last identified person → rule fires → desk lamp turns off.

**7. Hallucinated entity in AI output**
- AI returns an entity_id that does not exist in HA.
- `_validate_parsed_actions()` catches it.
- Config flow shows error: "Action 1: entity 'switch.nonexistent' not found in HA."
- Rule is not saved.

**8. Rule disabled flag**
- Set `enabled: false` on a rule (manually via developer tools to modify config entry, or via future delete UI).
- Occupancy changes → rule does not fire.

**9. No census available (BLE-only setup)**
- `hass.data[DOMAIN]["census"]` is None.
- `_get_identified_persons_in_room()` falls back to person_coordinator.
- Person-specific rules use BLE-only identification.
- Any-person rules (person="") fire normally.

**10. Multiple rules on same trigger**
- Two enter rules: one turns on lights (any person), one sets temperature (John only).
- John enters: both rules fire independently.
- Jane enters: only the lights rule fires.
- Rules do not interfere — they execute sequentially in list order.

---

## DEPLOY

```bash
./scripts/deploy.sh "3.4.0" "AI custom automation — person-specific natural language rules" "- Room-enter and room-exit rule triggers
- Natural language rule descriptions parsed by ai_task at save time (parse-once)
- Person-specific rules consume census identified_persons from v3.5.1
- BLE-only fallback for setups without cameras (lower identification confidence)
- Rules with no person filter work on any occupancy change, no camera dependency
- Rule storage in config entry (no database changes)
- Rule management via options flow (same pattern as Manage Zones)
- Validation: entity existence check before storing any parsed rule
- Graceful failure: ai_task unavailable shows clear error, no partial state stored"
```

---

## DEPENDENCY NOTES

**Hard dependency on v3.5.1:** Person-specific rules require `census.get_room_identified_persons(room_name)` or the equivalent person_coordinator fallback. If Cycle 5 is deployed before v3.5.1 ships:

- Rules with `person=""` work immediately on any setup.
- Rules with a person filter fall through to `_get_identified_persons_in_room()`, which tries person_coordinator (BLE) as fallback.
- If neither census nor person_coordinator is available, `identified_persons` is empty, person-specific rules never fire, and the error is silent (debug log only).

This is acceptable degraded behavior. The feature is usable end-to-end for any-person rules from day one. Person-specific rules light up automatically when v3.5.1 is deployed alongside.

**No dependency on cameras:** Camera integration from Cycle 3 (v3.5.0) makes person identification more reliable and enables guest detection, but it is not required. BLE-only identification via Bermuda (v3.2.0+) is the minimum working baseline for person-specific rules.

# PLANNING v3.4.0 - AI Custom Automation

**Version:** 3.4.0  
**Codename:** "Natural Language Rooms"  
**Status:** Planning Phase  
**Estimated Effort:** 12-15 hours  
**Priority:** HIGH (Game-changer feature)  
**Prerequisites:** v3.3.0 deployed  
**Target:** Q2 2026  

---

## 🎯 VISION

Enable users to customize room automation using **natural language instructions** instead of YAML configurations or complex UI forms.

**Example use cases:**
```
Master Bedroom:
"Use sensor.bed_pressure for occupancy detection instead of motion.
When bed pressure > 50 lbs for 5 minutes, mark room as occupied.
Don't turn off lights when TV is on.
Keep AC running even when unoccupied during summer."

Office:
"If CO2 > 1000 ppm, turn on air purifier.
Set temperature to 68°F during work hours (9 AM - 5 PM).
Turn off all devices when door closes and motion stops."

Nursery:
"Night light stays on 24/7.
White noise machine runs during sleep hours (7 PM - 7 AM).
Never use overhead lights between 7 PM - 7 AM, only use lamp."
```

**Why this is game-changing:**
- Handles edge cases without code changes
- User-friendly for power users
- Solves "my room is different" problem
- Reduces support burden (no feature requests for quirks)

---

## 🏗️ ARCHITECTURE

### High-Level Flow

```
User Input (Config UI)
    ↓
"Use bed pressure sensor for occupancy"
    ↓
Claude API (Parsing)
    ↓
Structured Rules (JSON)
    ↓
Rule Validator
    ↓
Custom Automation Engine
    ↓
Runtime Execution (Override Standard Logic)
```

### Component Overview

**1. Config Flow Extension**
- Add "Custom Automation" optional step
- Multi-line text input for instructions
- Live validation feedback
- Preview of parsed rules

**2. Claude API Integration**
- Anthropic API client (async)
- Parsing prompt templates
- Structured output schema
- Error handling and retries

**3. Rule Schema**
- JSON-based rule format
- Entity mappings
- Conditional overrides
- Time-based settings
- Action sequences

**4. Validation Engine**
- Syntax validation
- Entity existence checks
- Conflict detection
- Safety limits

**5. Runtime Engine**
- Rule execution layer
- Override mechanism for standard automation
- Fallback to defaults
- Logging and diagnostics

---

## 📋 DETAILED DESIGN

### 1. Config Flow Extension

**New Step: `async_step_custom_automation`**

```python
# config_flow.py

async def async_step_custom_automation(self, user_input=None):
    """Configure AI custom automation (v3.4.0)."""
    
    if user_input is not None:
        if user_input.get("enable_custom_automation"):
            # Parse instructions via Claude API
            try:
                parsed_rules = await self._parse_custom_instructions(
                    user_input.get("custom_instructions", "")
                )
                
                # Validate parsed rules
                validation_result = await self._validate_rules(parsed_rules)
                
                if not validation_result["valid"]:
                    # Show errors to user
                    return self.async_show_form(
                        step_id="custom_automation",
                        data_schema=self._get_custom_automation_schema(user_input),
                        errors=validation_result["errors"],
                        description_placeholders={
                            "validation_errors": "\n".join(validation_result["messages"])
                        }
                    )
                
                # Store validated rules
                self._data["custom_automation_enabled"] = True
                self._data["custom_automation_rules"] = parsed_rules
                self._data["custom_instructions_raw"] = user_input["custom_instructions"]
                
            except Exception as e:
                _LOGGER.error(f"Failed to parse custom automation: {e}")
                return self.async_show_form(
                    step_id="custom_automation",
                    data_schema=self._get_custom_automation_schema(user_input),
                    errors={"base": "parsing_failed"},
                    description_placeholders={
                        "error": str(e)
                    }
                )
        else:
            # Custom automation disabled
            self._data["custom_automation_enabled"] = False
        
        return await self.async_step_notifications()
    
    # Show form
    return self.async_show_form(
        step_id="custom_automation",
        data_schema=self._get_custom_automation_schema(),
        description_placeholders={
            "info": (
                "Describe custom automation in plain English:\n\n"
                "Examples:\n"
                "- Use sensor.bed_pressure for occupancy\n"
                "- Don't turn off lights when TV is on\n"
                "- If CO2 > 1000, turn on air purifier\n"
                "- Keep temperature at 68°F during work hours"
            )
        }
    )

def _get_custom_automation_schema(self, defaults=None):
    """Get schema for custom automation step."""
    return vol.Schema({
        vol.Optional(
            "enable_custom_automation",
            default=defaults.get("enable_custom_automation", False) if defaults else False
        ): bool,
        
        vol.Optional(
            "custom_instructions",
            default=defaults.get("custom_instructions", "") if defaults else ""
        ): str,  # Multi-line text
    })
```

**UI Layout:**
```
┌─────────────────────────────────────────────┐
│ Custom Automation (Optional)                │
├─────────────────────────────────────────────┤
│                                             │
│ [✓] Enable custom automation                │
│                                             │
│ Instructions (plain English):               │
│ ┌─────────────────────────────────────────┐ │
│ │ Use sensor.bed_pressure for occupancy   │ │
│ │ When bed pressure > 50 lbs for 5 min,   │ │
│ │ mark room as occupied.                  │ │
│ │                                         │ │
│ │ Don't turn off lights when TV is on.    │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ [Preview Rules]  [Clear]                    │
│                                             │
│ ✓ Parsed successfully                       │
│ - 2 entity mappings found                   │
│ - 1 conditional override found              │
│                                             │
│         [Back]  [Skip]  [Continue]          │
└─────────────────────────────────────────────┘
```

### 2. Claude API Integration

**New Module: `ai_parser.py`**

```python
"""AI-powered custom automation parser using Claude API.

This module handles:
1. Anthropic API authentication
2. Prompt template management
3. Structured output parsing
4. Error handling and retries
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from anthropic import AsyncAnthropic
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_CUSTOM_INSTRUCTIONS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# API Configuration
CLAUDE_MODEL = "claude-sonnet-4-20250514"  # Latest Sonnet
CLAUDE_MAX_TOKENS = 4096
CLAUDE_TEMPERATURE = 0.0  # Deterministic for parsing

# Parsing prompt template
PARSING_PROMPT = """You are a Home Assistant automation rule parser. Convert natural language instructions into structured JSON rules.

**Available entity types:**
- Sensors: motion, temperature, humidity, CO2, pressure, light_level, etc.
- Binary sensors: occupancy, door, window, motion, etc.
- Switches: lights, fans, air_purifiers, etc.
- Climate: thermostats, HVAC systems
- Media players: TVs, speakers
- Covers: blinds, shades

**Output schema:**
{
  "entity_mappings": [
    {
      "purpose": "occupancy_detection",
      "entity_id": "sensor.bed_pressure",
      "conditions": {
        "threshold": 50,
        "duration": 300
      }
    }
  ],
  "conditional_overrides": [
    {
      "condition": {
        "entity_id": "media_player.tv",
        "state": "on"
      },
      "override": {
        "disable_light_off": true
      }
    }
  ],
  "time_based_settings": [
    {
      "time_range": {
        "start": "09:00",
        "end": "17:00"
      },
      "settings": {
        "temperature_setpoint": 68
      }
    }
  ],
  "action_sequences": [
    {
      "trigger": {
        "entity_id": "sensor.co2",
        "above": 1000
      },
      "actions": [
        {
          "service": "switch.turn_on",
          "target": "switch.air_purifier"
        }
      ]
    }
  ]
}

**Instructions to parse:**
{instructions}

**Output only valid JSON. No explanations.**"""


class AIParser:
    """Parse natural language automation instructions using Claude API."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize AI parser."""
        self.hass = hass
        self._client: Optional[AsyncAnthropic] = None
    
    async def _get_client(self) -> AsyncAnthropic:
        """Get or create Anthropic API client."""
        if self._client is None:
            # Try to get API key from integration config
            integration_entry = self.hass.data.get(DOMAIN, {}).get("integration_entry")
            
            # For now, use direct API (no key needed in claude.ai context)
            # In production, user would provide their own API key
            self._client = AsyncAnthropic(
                # API key from environment or config
                # api_key=os.getenv("ANTHROPIC_API_KEY")
            )
        
        return self._client
    
    async def parse_instructions(
        self,
        instructions: str,
        room_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Parse natural language instructions into structured rules.
        
        Args:
            instructions: User's natural language instructions
            room_context: Optional room context (sensors, devices, etc.)
        
        Returns:
            Structured rules dictionary
        
        Raises:
            HomeAssistantError: If parsing fails
        """
        if not instructions or not instructions.strip():
            return self._empty_rules()
        
        try:
            client = await self._get_client()
            
            # Build prompt with room context
            prompt = PARSING_PROMPT.format(
                instructions=instructions,
            )
            
            # Add room context if available
            if room_context:
                prompt += f"\n\n**Room context:**\n{json.dumps(room_context, indent=2)}"
            
            # Call Claude API
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                temperature=CLAUDE_TEMPERATURE,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            # Extract JSON from response
            response_text = response.content[0].text
            
            # Parse JSON (handle potential markdown code blocks)
            rules = self._extract_json(response_text)
            
            # Validate structure
            self._validate_structure(rules)
            
            _LOGGER.info(
                "Successfully parsed custom automation rules: "
                f"{len(rules.get('entity_mappings', []))} entity mappings, "
                f"{len(rules.get('conditional_overrides', []))} conditional overrides"
            )
            
            return rules
            
        except Exception as e:
            _LOGGER.error(f"Failed to parse instructions: {e}")
            raise HomeAssistantError(f"AI parsing failed: {e}")
    
    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from Claude response (handle markdown)."""
        # Remove markdown code blocks if present
        text = text.strip()
        
        if text.startswith("```json"):
            text = text[7:]  # Remove ```json
        elif text.startswith("```"):
            text = text[3:]  # Remove ```
        
        if text.endswith("```"):
            text = text[:-3]  # Remove trailing ```
        
        text = text.strip()
        
        # Parse JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            _LOGGER.error(f"Invalid JSON from Claude: {text}")
            raise HomeAssistantError(f"Invalid JSON response: {e}")
    
    def _validate_structure(self, rules: Dict[str, Any]) -> None:
        """Validate rules structure."""
        required_keys = [
            "entity_mappings",
            "conditional_overrides",
            "time_based_settings",
            "action_sequences"
        ]
        
        for key in required_keys:
            if key not in rules:
                rules[key] = []
    
    def _empty_rules(self) -> Dict[str, Any]:
        """Return empty rules structure."""
        return {
            "entity_mappings": [],
            "conditional_overrides": [],
            "time_based_settings": [],
            "action_sequences": []
        }
```

### 3. Rule Schema

**Detailed schema with examples:**

```python
# const.py

# Custom Automation Schema
CUSTOM_AUTOMATION_SCHEMA = {
    "entity_mappings": [
        {
            "purpose": str,  # "occupancy_detection", "temperature_control", etc.
            "entity_id": str,  # Entity to use
            "conditions": {  # Optional conditions
                "threshold": float,
                "above": float,
                "below": float,
                "duration": int,  # seconds
                "state": str,
            }
        }
    ],
    "conditional_overrides": [
        {
            "condition": {
                "entity_id": str,
                "state": str,  # "on", "off", etc.
                "above": float,
                "below": float,
            },
            "override": {
                "disable_light_off": bool,
                "disable_climate_off": bool,
                "force_fan_on": bool,
                # ... other overrides
            }
        }
    ],
    "time_based_settings": [
        {
            "time_range": {
                "start": str,  # "HH:MM"
                "end": str,    # "HH:MM"
            },
            "days": [str],  # Optional: ["monday", "tuesday", ...]
            "settings": {
                "temperature_setpoint": float,
                "light_mode": str,  # "night", "dim", "bright"
                "disable_automation": bool,
            }
        }
    ],
    "action_sequences": [
        {
            "trigger": {
                "entity_id": str,
                "above": float,
                "below": float,
                "state": str,
            },
            "actions": [
                {
                    "service": str,  # "switch.turn_on", etc.
                    "target": str,   # Entity ID
                    "data": dict,    # Optional service data
                }
            ]
        }
    ]
}
```

**Example parsed rules:**

```json
{
  "entity_mappings": [
    {
      "purpose": "occupancy_detection",
      "entity_id": "sensor.bed_pressure",
      "conditions": {
        "threshold": 50,
        "duration": 300
      }
    }
  ],
  "conditional_overrides": [
    {
      "condition": {
        "entity_id": "media_player.bedroom_tv",
        "state": "playing"
      },
      "override": {
        "disable_light_off": true
      }
    }
  ],
  "time_based_settings": [
    {
      "time_range": {
        "start": "22:00",
        "end": "07:00"
      },
      "settings": {
        "light_mode": "night_only",
        "disable_overhead_lights": true
      }
    }
  ],
  "action_sequences": [
    {
      "trigger": {
        "entity_id": "sensor.co2",
        "above": 1000
      },
      "actions": [
        {
          "service": "switch.turn_on",
          "target": "switch.air_purifier"
        }
      ]
    }
  ]
}
```

### 4. Validation Engine

**New Module: `rule_validator.py`**

```python
"""Validation engine for custom automation rules."""

import logging
from typing import Any, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class RuleValidator:
    """Validate custom automation rules."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize validator."""
        self.hass = hass
        self.entity_registry = er.async_get(hass)
    
    async def validate_rules(self, rules: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate custom automation rules.
        
        Returns:
            {
                "valid": bool,
                "errors": {...},
                "messages": [...]
            }
        """
        errors = {}
        messages = []
        
        # Validate entity mappings
        if "entity_mappings" in rules:
            mapping_errors = await self._validate_entity_mappings(
                rules["entity_mappings"]
            )
            if mapping_errors:
                errors["entity_mappings"] = mapping_errors
                messages.extend(mapping_errors)
        
        # Validate conditional overrides
        if "conditional_overrides" in rules:
            override_errors = await self._validate_conditional_overrides(
                rules["conditional_overrides"]
            )
            if override_errors:
                errors["conditional_overrides"] = override_errors
                messages.extend(override_errors)
        
        # Validate time-based settings
        if "time_based_settings" in rules:
            time_errors = self._validate_time_based_settings(
                rules["time_based_settings"]
            )
            if time_errors:
                errors["time_based_settings"] = time_errors
                messages.extend(time_errors)
        
        # Validate action sequences
        if "action_sequences" in rules:
            action_errors = await self._validate_action_sequences(
                rules["action_sequences"]
            )
            if action_errors:
                errors["action_sequences"] = action_errors
                messages.extend(action_errors)
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "messages": messages
        }
    
    async def _validate_entity_mappings(
        self,
        mappings: List[Dict[str, Any]]
    ) -> List[str]:
        """Validate entity mappings."""
        errors = []
        
        for i, mapping in enumerate(mappings):
            entity_id = mapping.get("entity_id")
            
            if not entity_id:
                errors.append(f"Mapping {i+1}: Missing entity_id")
                continue
            
            # Check entity exists
            if not self.hass.states.get(entity_id):
                errors.append(
                    f"Mapping {i+1}: Entity '{entity_id}' not found"
                )
            
            # Validate purpose
            purpose = mapping.get("purpose")
            valid_purposes = [
                "occupancy_detection",
                "temperature_control",
                "humidity_control",
                "air_quality",
                "light_level",
            ]
            
            if purpose and purpose not in valid_purposes:
                errors.append(
                    f"Mapping {i+1}: Invalid purpose '{purpose}'. "
                    f"Valid: {', '.join(valid_purposes)}"
                )
        
        return errors
    
    async def _validate_conditional_overrides(
        self,
        overrides: List[Dict[str, Any]]
    ) -> List[str]:
        """Validate conditional overrides."""
        errors = []
        
        for i, override in enumerate(overrides):
            condition = override.get("condition", {})
            entity_id = condition.get("entity_id")
            
            if not entity_id:
                errors.append(f"Override {i+1}: Missing condition entity_id")
                continue
            
            # Check entity exists
            if not self.hass.states.get(entity_id):
                errors.append(
                    f"Override {i+1}: Entity '{entity_id}' not found"
                )
        
        return errors
    
    def _validate_time_based_settings(
        self,
        settings: List[Dict[str, Any]]
    ) -> List[str]:
        """Validate time-based settings."""
        errors = []
        
        for i, setting in enumerate(settings):
            time_range = setting.get("time_range", {})
            start = time_range.get("start")
            end = time_range.get("end")
            
            if not start or not end:
                errors.append(
                    f"Setting {i+1}: Missing time_range start or end"
                )
                continue
            
            # Validate time format (HH:MM)
            import re
            time_pattern = r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$"
            
            if not re.match(time_pattern, start):
                errors.append(
                    f"Setting {i+1}: Invalid start time '{start}' (use HH:MM)"
                )
            
            if not re.match(time_pattern, end):
                errors.append(
                    f"Setting {i+1}: Invalid end time '{end}' (use HH:MM)"
                )
        
        return errors
    
    async def _validate_action_sequences(
        self,
        sequences: List[Dict[str, Any]]
    ) -> List[str]:
        """Validate action sequences."""
        errors = []
        
        for i, sequence in enumerate(sequences):
            # Validate trigger
            trigger = sequence.get("trigger", {})
            entity_id = trigger.get("entity_id")
            
            if not entity_id:
                errors.append(f"Sequence {i+1}: Missing trigger entity_id")
                continue
            
            if not self.hass.states.get(entity_id):
                errors.append(
                    f"Sequence {i+1}: Trigger entity '{entity_id}' not found"
                )
            
            # Validate actions
            actions = sequence.get("actions", [])
            
            if not actions:
                errors.append(f"Sequence {i+1}: No actions defined")
            
            for j, action in enumerate(actions):
                service = action.get("service")
                target = action.get("target")
                
                if not service:
                    errors.append(
                        f"Sequence {i+1}, Action {j+1}: Missing service"
                    )
                
                if not target:
                    errors.append(
                        f"Sequence {i+1}, Action {j+1}: Missing target"
                    )
                elif not self.hass.states.get(target):
                    errors.append(
                        f"Sequence {i+1}, Action {j+1}: "
                        f"Target entity '{target}' not found"
                    )
        
        return errors
```

### 5. Runtime Engine

**New Module: `custom_automation.py`**

```python
"""Runtime engine for custom automation rules."""

import logging
from datetime import datetime, time
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class CustomAutomationEngine:
    """Execute custom automation rules."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        room_name: str,
        rules: Dict[str, Any]
    ) -> None:
        """Initialize custom automation engine."""
        self.hass = hass
        self.room_name = room_name
        self.rules = rules
        
        # Parse rules into efficient lookup structures
        self._entity_map = self._build_entity_map()
        self._override_conditions = rules.get("conditional_overrides", [])
        self._time_settings = rules.get("time_based_settings", [])
        self._action_sequences = rules.get("action_sequences", [])
    
    def _build_entity_map(self) -> Dict[str, Dict[str, Any]]:
        """Build entity mapping lookup."""
        entity_map = {}
        
        for mapping in self.rules.get("entity_mappings", []):
            purpose = mapping.get("purpose")
            if purpose:
                entity_map[purpose] = mapping
        
        return entity_map
    
    def get_occupancy_entity(self) -> Optional[str]:
        """Get custom occupancy detection entity."""
        mapping = self._entity_map.get("occupancy_detection")
        if mapping:
            return mapping.get("entity_id")
        return None
    
    def check_occupancy_custom(self, entity_id: str) -> bool:
        """
        Check occupancy using custom logic.
        
        Args:
            entity_id: Custom occupancy entity
        
        Returns:
            True if occupied according to custom rules
        """
        mapping = self._entity_map.get("occupancy_detection")
        if not mapping:
            return False
        
        state = self.hass.states.get(entity_id)
        if not state:
            return False
        
        conditions = mapping.get("conditions", {})
        
        # Check threshold
        threshold = conditions.get("threshold")
        if threshold is not None:
            try:
                value = float(state.state)
                if value < threshold:
                    return False
            except (ValueError, TypeError):
                return False
        
        # Check above/below
        if "above" in conditions:
            try:
                value = float(state.state)
                if value <= conditions["above"]:
                    return False
            except (ValueError, TypeError):
                return False
        
        if "below" in conditions:
            try:
                value = float(state.state)
                if value >= conditions["below"]:
                    return False
            except (ValueError, TypeError):
                return False
        
        # Check duration (would need state history - simplified here)
        # duration = conditions.get("duration")
        # if duration:
        #     # Check how long entity has been in this state
        #     pass
        
        return True
    
    def should_override(self, action: str) -> bool:
        """
        Check if action should be overridden.
        
        Args:
            action: Action to check (e.g., "light_off")
        
        Returns:
            True if action should be blocked
        """
        for override in self._override_conditions:
            # Check condition
            condition = override.get("condition", {})
            entity_id = condition.get("entity_id")
            
            if not entity_id:
                continue
            
            state = self.hass.states.get(entity_id)
            if not state:
                continue
            
            # Check state match
            required_state = condition.get("state")
            if required_state and state.state != required_state:
                continue
            
            # Check numeric conditions
            if "above" in condition:
                try:
                    value = float(state.state)
                    if value <= condition["above"]:
                        continue
                except (ValueError, TypeError):
                    continue
            
            if "below" in condition:
                try:
                    value = float(state.state)
                    if value >= condition["below"]:
                        continue
                except (ValueError, TypeError):
                    continue
            
            # Condition met - check override
            override_rules = override.get("override", {})
            
            if action == "light_off" and override_rules.get("disable_light_off"):
                _LOGGER.debug(
                    f"[{self.room_name}] Blocking light_off due to override: "
                    f"{entity_id} is {state.state}"
                )
                return True
            
            if action == "climate_off" and override_rules.get("disable_climate_off"):
                _LOGGER.debug(
                    f"[{self.room_name}] Blocking climate_off due to override"
                )
                return True
        
        return False
    
    def get_time_based_settings(self) -> Optional[Dict[str, Any]]:
        """
        Get settings for current time.
        
        Returns:
            Settings dict if time matches, None otherwise
        """
        now = dt_util.now()
        current_time = now.time()
        current_day = now.strftime("%A").lower()
        
        for setting in self._time_settings:
            time_range = setting.get("time_range", {})
            start_str = time_range.get("start")
            end_str = time_range.get("end")
            
            if not start_str or not end_str:
                continue
            
            # Parse times
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
            
            # Check if current time is in range
            in_range = False
            if start_time <= end_time:
                # Same day range
                in_range = start_time <= current_time <= end_time
            else:
                # Overnight range
                in_range = current_time >= start_time or current_time <= end_time
            
            if not in_range:
                continue
            
            # Check day match (if specified)
            days = setting.get("days", [])
            if days and current_day not in days:
                continue
            
            # Match found
            return setting.get("settings", {})
        
        return None
    
    async def execute_action_sequences(self) -> None:
        """Execute action sequences based on triggers."""
        for sequence in self._action_sequences:
            trigger = sequence.get("trigger", {})
            entity_id = trigger.get("entity_id")
            
            if not entity_id:
                continue
            
            state = self.hass.states.get(entity_id)
            if not state:
                continue
            
            # Check trigger conditions
            triggered = False
            
            if "above" in trigger:
                try:
                    value = float(state.state)
                    if value > trigger["above"]:
                        triggered = True
                except (ValueError, TypeError):
                    pass
            
            if "below" in trigger:
                try:
                    value = float(state.state)
                    if value < trigger["below"]:
                        triggered = True
                except (ValueError, TypeError):
                    pass
            
            if "state" in trigger:
                if state.state == trigger["state"]:
                    triggered = True
            
            if not triggered:
                continue
            
            # Execute actions
            actions = sequence.get("actions", [])
            for action in actions:
                service = action.get("service")
                target = action.get("target")
                data = action.get("data", {})
                
                if not service or not target:
                    continue
                
                domain, service_name = service.split(".", 1)
                
                try:
                    await self.hass.services.async_call(
                        domain,
                        service_name,
                        {
                            "entity_id": target,
                            **data
                        }
                    )
                    
                    _LOGGER.info(
                        f"[{self.room_name}] Executed custom action: "
                        f"{service} on {target}"
                    )
                    
                except Exception as e:
                    _LOGGER.error(
                        f"[{self.room_name}] Failed to execute custom action: {e}"
                    )
```

---

## 🔌 INTEGRATION POINTS

### Coordinator Integration

**Modified: `coordinator.py`**

```python
# In RoomCoordinator.__init__

# Load custom automation engine
self.custom_automation: Optional[CustomAutomationEngine] = None

if entry.data.get("custom_automation_enabled"):
    rules = entry.data.get("custom_automation_rules", {})
    self.custom_automation = CustomAutomationEngine(
        hass,
        self.room_name,
        rules
    )
    
    _LOGGER.info(
        f"[{self.room_name}] Custom automation enabled with "
        f"{len(rules.get('entity_mappings', []))} entity mappings"
    )
```

### Automation Engine Integration

**Modified: `automation.py`**

```python
# In AutomationEngine._determine_occupancy

async def _determine_occupancy(self) -> bool:
    """Determine occupancy with custom automation support."""
    
    # Check for custom occupancy detection
    if self.coordinator.custom_automation:
        custom_entity = self.coordinator.custom_automation.get_occupancy_entity()
        
        if custom_entity:
            # Use custom entity and logic
            is_occupied = self.coordinator.custom_automation.check_occupancy_custom(
                custom_entity
            )
            
            _LOGGER.debug(
                f"[{self.room_name}] Custom occupancy: {is_occupied} "
                f"(entity: {custom_entity})"
            )
            
            return is_occupied
    
    # Fall back to standard occupancy detection
    return await self._standard_occupancy_detection()


# In AutomationEngine._control_lights

async def _control_lights(self, target_state: str) -> None:
    """Control lights with custom automation support."""
    
    # Check for override
    if self.coordinator.custom_automation:
        if target_state == "off":
            if self.coordinator.custom_automation.should_override("light_off"):
                _LOGGER.debug(
                    f"[{self.room_name}] Light off blocked by custom automation"
                )
                return
        
        # Check time-based settings
        time_settings = self.coordinator.custom_automation.get_time_based_settings()
        if time_settings:
            light_mode = time_settings.get("light_mode")
            
            if light_mode == "night_only" and target_state == "on":
                # Use night lights only
                await self._activate_night_lights_only()
                return
            
            if time_settings.get("disable_overhead_lights") and target_state == "on":
                # Don't use overhead lights
                await self._activate_non_overhead_lights()
                return
    
    # Standard light control
    await self._standard_light_control(target_state)
```

---

## 🧪 TESTING STRATEGY

### Unit Tests

**test_ai_parser.py**
```python
async def test_parse_bed_pressure():
    """Test parsing bed pressure occupancy."""
    parser = AIParser(hass)
    
    instructions = """
    Use sensor.bed_pressure for occupancy detection.
    When bed pressure > 50 lbs for 5 minutes, mark room as occupied.
    """
    
    rules = await parser.parse_instructions(instructions)
    
    assert len(rules["entity_mappings"]) == 1
    assert rules["entity_mappings"][0]["entity_id"] == "sensor.bed_pressure"
    assert rules["entity_mappings"][0]["conditions"]["threshold"] == 50
    assert rules["entity_mappings"][0]["conditions"]["duration"] == 300

async def test_parse_tv_override():
    """Test parsing TV conditional override."""
    parser = AIParser(hass)
    
    instructions = "Don't turn off lights when TV is on."
    
    rules = await parser.parse_instructions(instructions)
    
    assert len(rules["conditional_overrides"]) == 1
    override = rules["conditional_overrides"][0]
    assert "tv" in override["condition"]["entity_id"].lower()
    assert override["override"]["disable_light_off"] is True
```

**test_rule_validator.py**
```python
async def test_validate_valid_rules():
    """Test validation of valid rules."""
    validator = RuleValidator(hass)
    
    rules = {
        "entity_mappings": [{
            "purpose": "occupancy_detection",
            "entity_id": "sensor.bed_pressure",
            "conditions": {"threshold": 50}
        }]
    }
    
    result = await validator.validate_rules(rules)
    
    assert result["valid"] is True
    assert len(result["errors"]) == 0

async def test_validate_missing_entity():
    """Test validation catches missing entities."""
    validator = RuleValidator(hass)
    
    rules = {
        "entity_mappings": [{
            "purpose": "occupancy_detection",
            "entity_id": "sensor.does_not_exist"
        }]
    }
    
    result = await validator.validate_rules(rules)
    
    assert result["valid"] is False
    assert "not found" in result["messages"][0]
```

**test_custom_automation.py**
```python
async def test_custom_occupancy_detection():
    """Test custom occupancy detection."""
    rules = {
        "entity_mappings": [{
            "purpose": "occupancy_detection",
            "entity_id": "sensor.bed_pressure",
            "conditions": {"threshold": 50}
        }]
    }
    
    engine = CustomAutomationEngine(hass, "bedroom", rules)
    
    # Test threshold check
    hass.states.async_set("sensor.bed_pressure", "60")
    assert engine.check_occupancy_custom("sensor.bed_pressure") is True
    
    hass.states.async_set("sensor.bed_pressure", "40")
    assert engine.check_occupancy_custom("sensor.bed_pressure") is False

async def test_conditional_override():
    """Test conditional override."""
    rules = {
        "conditional_overrides": [{
            "condition": {
                "entity_id": "media_player.tv",
                "state": "playing"
            },
            "override": {
                "disable_light_off": True
            }
        }]
    }
    
    engine = CustomAutomationEngine(hass, "bedroom", rules)
    
    # TV playing - should override
    hass.states.async_set("media_player.tv", "playing")
    assert engine.should_override("light_off") is True
    
    # TV off - no override
    hass.states.async_set("media_player.tv", "off")
    assert engine.should_override("light_off") is False
```

### Integration Tests

**test_custom_automation_integration.py**
```python
async def test_end_to_end_custom_automation(hass):
    """Test complete custom automation flow."""
    
    # 1. Setup room with custom automation
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "room_name": "Master Bedroom",
            "custom_automation_enabled": True,
            "custom_automation_rules": {
                "entity_mappings": [{
                    "purpose": "occupancy_detection",
                    "entity_id": "sensor.bed_pressure",
                    "conditions": {"threshold": 50, "duration": 300}
                }],
                "conditional_overrides": [{
                    "condition": {
                        "entity_id": "media_player.bedroom_tv",
                        "state": "playing"
                    },
                    "override": {"disable_light_off": True}
                }]
            }
        }
    )
    
    # 2. Load integration
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    
    # 3. Test custom occupancy
    hass.states.async_set("sensor.bed_pressure", "60")
    await hass.async_block_till_done()
    
    # Room should be occupied
    occupancy_sensor = hass.states.get("binary_sensor.master_bedroom_occupancy")
    assert occupancy_sensor.state == "on"
    
    # 4. Test TV override
    hass.states.async_set("media_player.bedroom_tv", "playing")
    hass.states.async_set("sensor.bed_pressure", "0")  # Leave bed
    await hass.async_block_till_done()
    
    # Lights should stay on (TV playing)
    light = hass.states.get("light.master_bedroom")
    assert light.state == "on"
```

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: Foundation (3-4 hours)
- [ ] Create `ai_parser.py` module
- [ ] Implement Claude API integration
- [ ] Create parsing prompt templates
- [ ] Add structured output schema
- [ ] Test basic parsing with examples

### Phase 2: Validation (2-3 hours)
- [ ] Create `rule_validator.py` module
- [ ] Implement entity existence checks
- [ ] Add time format validation
- [ ] Add service/action validation
- [ ] Test validation with edge cases

### Phase 3: Runtime Engine (3-4 hours)
- [ ] Create `custom_automation.py` module
- [ ] Implement occupancy override logic
- [ ] Add conditional override system
- [ ] Add time-based settings
- [ ] Add action sequence execution

### Phase 4: Config Flow (2-3 hours)
- [ ] Add custom automation step to config flow
- [ ] Implement live validation feedback
- [ ] Add preview functionality
- [ ] Test UI flow end-to-end

### Phase 5: Integration (2-3 hours)
- [ ] Integrate with coordinator
- [ ] Modify automation engine for overrides
- [ ] Add diagnostics and logging
- [ ] Test with real hardware

### Phase 6: Documentation (1-2 hours)
- [ ] Write user guide with examples
- [ ] Document all rule types
- [ ] Create troubleshooting guide
- [ ] Add to README

**Total: 12-15 hours**

---

## 🎯 SUCCESS CRITERIA

**Functional:**
- ✅ User can input natural language instructions
- ✅ Instructions parsed into valid rules
- ✅ Rules validated against HA entities
- ✅ Custom occupancy detection works
- ✅ Conditional overrides work
- ✅ Time-based settings work
- ✅ Action sequences execute

**Quality:**
- ✅ Parsing accuracy >90%
- ✅ Clear error messages for invalid input
- ✅ Graceful fallback to defaults
- ✅ No performance impact on standard automation
- ✅ All rules documented with examples

**User Experience:**
- ✅ Simple UI (one text box)
- ✅ Live validation feedback
- ✅ Clear examples in placeholder text
- ✅ Works without Claude API key (uses existing claude.ai context)

---

## 🚧 KNOWN LIMITATIONS

**v3.4.0 Limitations:**
1. **No duration tracking** - Condition duration checks simplified (v3.5.0)
2. **No learning** - Rules are static, don't adapt (v4.0.0)
3. **Limited safety** - Basic validation only (v3.5.0 for sandboxing)
4. **English only** - Parsing only works in English
5. **No visual editor** - Text-only input (future enhancement)

---

## 🔮 FUTURE ENHANCEMENTS (Post-v3.4.0)

**v3.5.0 - Enhanced Safety:**
- Sandboxed rule execution
- Rate limiting on custom actions
- Anomaly detection
- Undo/rollback mechanism

**v4.0.0 - Learning Integration:**
- Custom rules inform Bayesian predictions
- Auto-suggest rules based on usage
- Conflictdetection with learned patterns

**v5.0.0 - Visual Editor:**
- Drag-and-drop rule builder
- Visual condition editor
- Template library
- Multi-language support

---

**PLANNING v3.4.0 - AI Custom Automation**  
**Status:** Complete specification  
**Ready for:** Session 2 (Sonnet 4.5)  
**Estimated Effort:** 12-15 hours  
**Dependencies:** v3.3.0 deployed  
**Target:** Q2 2026

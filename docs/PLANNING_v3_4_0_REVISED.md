# PLANNING v3.4.0 - AI Custom Automation (REVISED)

**Version:** 3.4.0  
**Codename:** "Natural Language Rooms"  
**Status:** Planning Phase (Revised)  
**Estimated Effort:** 10-12 hours  
**Priority:** HIGH  
**Prerequisites:** v3.3.0 deployed  
**Target:** Q2 2026  
**Revision Date:** 2026-01-25

---

## 🔄 KEY CHANGES FROM ORIGINAL PLAN

| Aspect | Original (v1) | Revised (v2) |
|--------|---------------|--------------|
| **API Approach** | Direct `anthropic` library | HA's built-in `ai_task` service |
| **Auth** | User provides Claude API key | Uses existing HA AI configuration |
| **Providers** | Claude only | Claude/GPT/Gemini (user choice) |
| **Structured Output** | Custom JSON parsing | HA's `structure` parameter |
| **Scope** | Config flow only | Reusable AI service for coordinators |
| **Setup Friction** | Additional API key | Zero (if AI already configured) |

**Why the change:**
1. User already has all 3 AI providers configured in HA
2. `ai_task.generate_data` supports structured output natively
3. Establishes AI infrastructure for future coordinator features
4. Reduces integration complexity and maintenance burden

---

## 🎯 VISION (Unchanged)

Enable users to customize room automation using **natural language instructions** instead of YAML configurations or complex UI forms.

**Example use cases:**
```
Master Bedroom:
"Use sensor.bed_pressure for occupancy detection instead of motion.
When bed pressure > 50 lbs for 5 minutes, mark room as occupied.
Don't turn off lights when TV is on."

Office:
"If CO2 > 1000 ppm, turn on air purifier.
Set temperature to 68°F during work hours (9 AM - 5 PM)."
```

---

## 🏗️ REVISED ARCHITECTURE

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         URA INTEGRATION                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Config Flow                        Runtime                                  │
│  ┌──────────────┐                  ┌──────────────────────────────────┐    │
│  │ User Input   │                  │ Coordinators (Future)            │    │
│  │ "Use bed     │                  │ • Presence inference              │    │
│  │  pressure"   │                  │ • Anomaly explanation            │    │
│  └──────┬───────┘                  │ • Comfort learning               │    │
│         │                          └──────────────┬───────────────────┘    │
│         ▼                                         │                         │
│  ┌────────────────────────────────────────────────▼─────────────────────┐  │
│  │                     URA AI SERVICE LAYER                              │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────────┐ │  │
│  │  │   Prompt    │  │  Provider   │  │    Response Parser           │ │  │
│  │  │  Templates  │  │  Selector   │  │  (Structured → Python)       │ │  │
│  │  └─────────────┘  └─────────────┘  └──────────────────────────────┘ │  │
│  └──────────────────────────────────┬───────────────────────────────────┘  │
│                                     │                                       │
│                                     ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │                   HOME ASSISTANT CORE                                   ││
│  │  ┌─────────────────────────────────────────────────────────────────┐  ││
│  │  │  ai_task.generate_data service                                   │  ││
│  │  │  • entity_id: ai_task.claude_ai_task (or openai/google)         │  ││
│  │  │  • instructions: <prompt>                                        │  ││
│  │  │  • structure: <JSON schema>                                      │  ││
│  │  └─────────────────────────────────────────────────────────────────┘  ││
│  │                              │                                          ││
│  │              ┌───────────────┼───────────────┐                         ││
│  │              ▼               ▼               ▼                         ││
│  │  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐                ││
│  │  │    Claude     │ │    OpenAI     │ │    Gemini     │                ││
│  │  │  (Anthropic)  │ │   (ChatGPT)   │ │   (Google)    │                ││
│  │  └───────────────┘ └───────────────┘ └───────────────┘                ││
│  └────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Overview

```
custom_components/universal_room_automation/
├── ai/                              # NEW: AI Service Layer
│   ├── __init__.py
│   ├── service.py                   # AIService class
│   ├── prompts.py                   # Prompt templates
│   ├── schemas.py                   # Structured output schemas
│   └── parsers.py                   # Response parsing
├── custom_automation/               # NEW: Custom Automation
│   ├── __init__.py
│   ├── rule_parser.py               # Uses AIService
│   ├── rule_validator.py            # Entity validation
│   ├── rule_engine.py               # Runtime execution
│   └── models.py                    # Rule data structures
├── coordinator.py                   # (existing)
├── config_flow.py                   # Extended with AI step
└── ...
```

---

## 📋 DETAILED DESIGN

### 1. URA AI Service Layer

**Purpose:** Abstraction over HA's AI integrations for use by config flow AND coordinators.

```python
"""ai/service.py - URA AI Service Layer.

Provides a unified interface to HA's AI integrations for:
1. Config-time rule parsing (v3.4.0)
2. Runtime coordinator intelligence (v3.5.0+)
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


class AIProvider(Enum):
    """Supported AI providers."""
    CLAUDE = "claude"
    OPENAI = "openai"
    GOOGLE = "google"


# Entity mapping for ai_task
AI_TASK_ENTITIES = {
    AIProvider.CLAUDE: "ai_task.claude_ai_task",
    AIProvider.OPENAI: "ai_task.openai_ai_task",
    AIProvider.GOOGLE: "ai_task.google_ai_task",
}

# Fallback to conversation services
CONVERSATION_SERVICES = {
    AIProvider.CLAUDE: ("conversation", "process", "conversation.claude_conversation"),
    AIProvider.OPENAI: ("openai_conversation", "generate_content", None),
    AIProvider.GOOGLE: ("google_generative_ai_conversation", "generate_content", None),
}


@dataclass
class AIRequest:
    """Request to AI service."""
    task_name: str
    instructions: str
    structure: dict | None = None  # JSON schema for structured output
    attachments: list[str] | None = None


@dataclass
class AIResponse:
    """Response from AI service."""
    success: bool
    data: dict | str | None = None
    error: str | None = None
    provider: AIProvider | None = None
    raw_response: Any = None


class URAIService:
    """URA AI Service - abstraction over HA AI integrations."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        preferred_provider: AIProvider = AIProvider.CLAUDE,
        fallback_providers: list[AIProvider] | None = None,
    ):
        self.hass = hass
        self.preferred_provider = preferred_provider
        self.fallback_providers = fallback_providers or [
            AIProvider.OPENAI,
            AIProvider.GOOGLE,
        ]
        
        # Track available providers
        self._available_providers: list[AIProvider] = []
        self._initialized = False
    
    async def async_initialize(self) -> None:
        """Initialize and detect available AI providers."""
        
        for provider in AIProvider:
            entity_id = AI_TASK_ENTITIES.get(provider)
            if entity_id:
                state = self.hass.states.get(entity_id)
                if state is not None:
                    self._available_providers.append(provider)
                    _LOGGER.debug(f"AI provider available: {provider.value}")
        
        if not self._available_providers:
            _LOGGER.warning("No AI providers available - AI features disabled")
        else:
            _LOGGER.info(
                f"AI service initialized with providers: "
                f"{[p.value for p in self._available_providers]}"
            )
        
        self._initialized = True
    
    @property
    def is_available(self) -> bool:
        """Check if any AI provider is available."""
        return len(self._available_providers) > 0
    
    @property
    def available_providers(self) -> list[AIProvider]:
        """Get list of available providers."""
        return self._available_providers.copy()
    
    async def generate(self, request: AIRequest) -> AIResponse:
        """
        Generate AI response with automatic fallback.
        
        Tries preferred provider first, then fallbacks.
        """
        if not self._initialized:
            await self.async_initialize()
        
        if not self.is_available:
            return AIResponse(
                success=False,
                error="No AI providers available",
            )
        
        # Build provider order
        providers_to_try = []
        if self.preferred_provider in self._available_providers:
            providers_to_try.append(self.preferred_provider)
        
        for fallback in self.fallback_providers:
            if fallback in self._available_providers and fallback not in providers_to_try:
                providers_to_try.append(fallback)
        
        # Try each provider
        last_error = None
        for provider in providers_to_try:
            try:
                response = await self._call_provider(provider, request)
                if response.success:
                    return response
                last_error = response.error
            except Exception as e:
                _LOGGER.warning(f"AI provider {provider.value} failed: {e}")
                last_error = str(e)
        
        return AIResponse(
            success=False,
            error=f"All AI providers failed. Last error: {last_error}",
        )
    
    async def _call_provider(
        self,
        provider: AIProvider,
        request: AIRequest,
    ) -> AIResponse:
        """Call a specific AI provider."""
        
        entity_id = AI_TASK_ENTITIES.get(provider)
        
        if not entity_id:
            return AIResponse(success=False, error=f"Unknown provider: {provider}")
        
        # Build service data
        service_data = {
            "task_name": request.task_name,
            "instructions": request.instructions,
            "entity_id": entity_id,
        }
        
        if request.structure:
            service_data["structure"] = request.structure
        
        if request.attachments:
            service_data["attachments"] = request.attachments
        
        try:
            # Call ai_task.generate_data
            result = await self.hass.services.async_call(
                domain="ai_task",
                service="generate_data",
                service_data=service_data,
                blocking=True,
                return_response=True,
            )
            
            _LOGGER.debug(f"AI response from {provider.value}: {result}")
            
            # Parse result
            if result and isinstance(result, dict):
                return AIResponse(
                    success=True,
                    data=result.get("data", result),
                    provider=provider,
                    raw_response=result,
                )
            
            return AIResponse(
                success=False,
                error="Empty response from AI",
                provider=provider,
            )
            
        except HomeAssistantError as e:
            return AIResponse(
                success=False,
                error=str(e),
                provider=provider,
            )
    
    # =========================================================================
    # HIGH-LEVEL METHODS FOR SPECIFIC USE CASES
    # =========================================================================
    
    async def parse_custom_rules(
        self,
        instructions: str,
        room_context: dict,
    ) -> AIResponse:
        """
        Parse natural language instructions into structured rules.
        
        Used by: Config flow (v3.4.0)
        """
        from .prompts import RULE_PARSING_PROMPT
        from .schemas import RULE_SCHEMA
        
        prompt = RULE_PARSING_PROMPT.format(
            instructions=instructions,
            room_name=room_context.get("room_name", "Unknown"),
            available_entities=json.dumps(room_context.get("entities", []), indent=2),
        )
        
        return await self.generate(AIRequest(
            task_name="parse_room_automation_rules",
            instructions=prompt,
            structure=RULE_SCHEMA,
        ))
    
    async def explain_anomaly(
        self,
        anomaly_data: dict,
    ) -> AIResponse:
        """
        Explain an anomaly detected by coordinators.
        
        Used by: Coordinators (v3.5.0+)
        """
        from .prompts import ANOMALY_EXPLANATION_PROMPT
        
        prompt = ANOMALY_EXPLANATION_PROMPT.format(
            anomaly_type=anomaly_data.get("type"),
            anomaly_details=json.dumps(anomaly_data, indent=2),
        )
        
        return await self.generate(AIRequest(
            task_name="explain_home_anomaly",
            instructions=prompt,
        ))
    
    async def infer_house_state(
        self,
        context: dict,
    ) -> AIResponse:
        """
        Infer house state from ambiguous signals.
        
        Used by: Presence Coordinator (v3.5.0+)
        """
        from .prompts import HOUSE_STATE_INFERENCE_PROMPT
        from .schemas import HOUSE_STATE_SCHEMA
        
        prompt = HOUSE_STATE_INFERENCE_PROMPT.format(
            census_data=json.dumps(context.get("census", {}), indent=2),
            time_of_day=context.get("time_of_day"),
            recent_events=json.dumps(context.get("events", []), indent=2),
        )
        
        return await self.generate(AIRequest(
            task_name="infer_house_state",
            instructions=prompt,
            structure=HOUSE_STATE_SCHEMA,
        ))
```

### 2. Prompt Templates

```python
"""ai/prompts.py - Prompt templates for AI service."""

RULE_PARSING_PROMPT = """You are a Home Assistant automation rule parser for the Universal Room Automation (URA) integration.

TASK: Convert natural language instructions into structured automation rules.

ROOM CONTEXT:
- Room Name: {room_name}
- Available Entities:
{available_entities}

USER INSTRUCTIONS:
{instructions}

RULES:
1. Only reference entities from the available entities list
2. Use exact entity_id values
3. For thresholds, use numeric values with units
4. For durations, use seconds
5. For time ranges, use 24-hour format (HH:MM)

OUTPUT: Respond with valid JSON matching the structure schema.
"""

ANOMALY_EXPLANATION_PROMPT = """You are a smart home diagnostic assistant.

TASK: Explain the following anomaly in plain language for the homeowner.

ANOMALY:
{anomaly_type}

DETAILS:
{anomaly_details}

Provide:
1. A brief explanation of what happened
2. Possible causes
3. Suggested actions (if any)

Keep the response concise and actionable.
"""

HOUSE_STATE_INFERENCE_PROMPT = """You are a presence detection assistant for a smart home.

TASK: Infer the current house state based on available signals.

CENSUS DATA (who's detected where):
{census_data}

TIME OF DAY: {time_of_day}

RECENT EVENTS:
{recent_events}

Based on these signals, determine:
1. The most likely house state (AWAY, HOME_DAY, HOME_EVENING, SLEEP, etc.)
2. Confidence level (0.0 - 1.0)
3. Reasoning

OUTPUT: Respond with valid JSON matching the structure schema.
"""
```

### 3. Structured Output Schemas

```python
"""ai/schemas.py - Structured output schemas for AI service."""

# Schema for rule parsing (v3.4.0)
RULE_SCHEMA = {
    "entity_mappings": {
        "selector": {"object": {}},
        "description": "List of entity mapping overrides",
    },
    "conditional_overrides": {
        "selector": {"object": {}},
        "description": "List of conditional automation overrides",
    },
    "time_settings": {
        "selector": {"object": {}},
        "description": "Time-based automation settings",
    },
    "action_sequences": {
        "selector": {"object": {}},
        "description": "Custom action sequences",
    },
}

# More detailed schema (if ai_task supports nested structure)
RULE_SCHEMA_DETAILED = {
    "entity_mappings": {
        "selector": {"object": {"multiple": True}},
        "description": (
            "Array of objects with: "
            "purpose (string: occupancy_detection|temperature_source|humidity_source), "
            "entity_id (string), "
            "conditions (object with threshold, duration, comparison)"
        ),
    },
    "conditional_overrides": {
        "selector": {"object": {"multiple": True}},
        "description": (
            "Array of objects with: "
            "condition (object with entity_id, state or threshold), "
            "override (object with disable_light_off, disable_fan_off, etc.)"
        ),
    },
    "time_settings": {
        "selector": {"object": {"multiple": True}},
        "description": (
            "Array of objects with: "
            "setting (string: temperature|brightness|fan_speed), "
            "time_range (object with start, end in HH:MM), "
            "value (number or string)"
        ),
    },
    "action_sequences": {
        "selector": {"object": {"multiple": True}},
        "description": (
            "Array of objects with: "
            "trigger (object with type, entity_id, conditions), "
            "actions (array of service calls)"
        ),
    },
}

# Schema for house state inference (v3.5.0+)
HOUSE_STATE_SCHEMA = {
    "house_state": {
        "selector": {
            "select": {
                "options": [
                    "AWAY", "ARRIVING", "HOME_DAY", "HOME_EVENING",
                    "HOME_NIGHT", "SLEEP", "WAKING", "GUEST", "VACATION"
                ]
            }
        },
        "description": "Inferred house state",
    },
    "confidence": {
        "selector": {"number": {"min": 0.0, "max": 1.0, "step": 0.01}},
        "description": "Confidence level (0.0 to 1.0)",
    },
    "reasoning": {
        "selector": {"text": {"multiline": True}},
        "description": "Brief explanation of the inference",
    },
}
```

### 4. Config Flow Extension

```python
"""config_flow.py additions for v3.4.0"""

async def async_step_custom_automation(self, user_input=None):
    """Configure AI custom automation (v3.4.0)."""
    
    errors = {}
    description_placeholders = {}
    
    # Check if AI is available
    ai_service = self.hass.data.get(DOMAIN, {}).get("ai_service")
    ai_available = ai_service and ai_service.is_available
    
    if not ai_available:
        description_placeholders["ai_status"] = (
            "⚠️ No AI providers detected. "
            "Configure Claude, OpenAI, or Google AI in Home Assistant settings."
        )
    else:
        providers = [p.value for p in ai_service.available_providers]
        description_placeholders["ai_status"] = (
            f"✅ AI available: {', '.join(providers)}"
        )
    
    if user_input is not None:
        if user_input.get("enable_custom_automation") and ai_available:
            instructions = user_input.get("custom_instructions", "").strip()
            
            if instructions:
                # Get room context
                room_context = {
                    "room_name": self._data.get("room_name"),
                    "entities": await self._get_room_entities(),
                }
                
                # Parse via AI
                response = await ai_service.parse_custom_rules(
                    instructions=instructions,
                    room_context=room_context,
                )
                
                if response.success:
                    # Validate parsed rules
                    validator = RuleValidator(self.hass)
                    validation = await validator.validate(response.data)
                    
                    if validation["valid"]:
                        self._data["custom_automation_enabled"] = True
                        self._data["custom_automation_rules"] = response.data
                        self._data["custom_instructions_raw"] = instructions
                        self._data["ai_provider_used"] = response.provider.value
                        
                        return await self.async_step_notifications()
                    else:
                        errors["base"] = "validation_failed"
                        description_placeholders["validation_errors"] = (
                            "\n".join(validation["messages"])
                        )
                else:
                    errors["base"] = "parsing_failed"
                    description_placeholders["error"] = response.error
            else:
                # No instructions but enabled - error
                errors["custom_instructions"] = "required"
        else:
            # Custom automation disabled or AI not available
            self._data["custom_automation_enabled"] = False
            return await self.async_step_notifications()
    
    return self.async_show_form(
        step_id="custom_automation",
        data_schema=self._get_custom_automation_schema(user_input),
        errors=errors,
        description_placeholders=description_placeholders,
    )


async def _get_room_entities(self) -> list[dict]:
    """Get available entities for this room."""
    
    room_name = self._data.get("room_name", "").lower().replace(" ", "_")
    entities = []
    
    # Get entities matching room name or in room's area
    for entity_id in self.hass.states.async_entity_ids():
        state = self.hass.states.get(entity_id)
        if not state:
            continue
        
        # Check if entity matches room
        if room_name in entity_id.lower():
            entities.append({
                "entity_id": entity_id,
                "friendly_name": state.attributes.get("friendly_name", entity_id),
                "domain": entity_id.split(".")[0],
                "state": state.state,
            })
    
    return entities
```

### 5. Integration Initialization

```python
"""__init__.py additions for v3.4.0"""

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up URA integration."""
    
    hass.data.setdefault(DOMAIN, {})
    
    # Initialize AI service (v3.4.0)
    from .ai.service import URAIService, AIProvider
    
    ai_service = URAIService(
        hass,
        preferred_provider=AIProvider.CLAUDE,
        fallback_providers=[AIProvider.OPENAI, AIProvider.GOOGLE],
    )
    await ai_service.async_initialize()
    
    hass.data[DOMAIN]["ai_service"] = ai_service
    
    _LOGGER.info(
        f"URA AI Service initialized. "
        f"Available providers: {[p.value for p in ai_service.available_providers]}"
    )
    
    return True
```

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: AI Service Layer (3-4 hours)
- [ ] Create `ai/` module structure
- [ ] Implement `URAIService` class
- [ ] Add prompt templates
- [ ] Add structured output schemas
- [ ] Test with all 3 providers
- [ ] Handle provider failures gracefully

### Phase 2: Rule Parsing (2-3 hours)
- [ ] Create `custom_automation/rule_parser.py`
- [ ] Implement `parse_custom_rules()` method
- [ ] Test with example instructions
- [ ] Handle edge cases and errors

### Phase 3: Rule Validation (1-2 hours)
- [ ] Create `custom_automation/rule_validator.py`
- [ ] Entity existence checks
- [ ] Schema validation
- [ ] Conflict detection

### Phase 4: Config Flow (2-3 hours)
- [ ] Add `async_step_custom_automation`
- [ ] UI with AI status indicator
- [ ] Live validation feedback
- [ ] Store parsed rules

### Phase 5: Runtime Engine (2-3 hours)
- [ ] Create `custom_automation/rule_engine.py`
- [ ] Integrate with coordinator
- [ ] Override mechanism
- [ ] Logging and diagnostics

### Phase 6: Testing & Docs (1-2 hours)
- [ ] Unit tests for AI service
- [ ] Integration tests
- [ ] User documentation
- [ ] Example instructions library

**Total: 10-12 hours** (reduced from 12-15)

---

## 🔧 CONFIGURATION

### User Configuration (Options Flow)

```yaml
# URA options for custom automation
custom_automation:
  enabled: true
  preferred_ai_provider: "claude"  # claude, openai, google
  fallback_enabled: true
  
  # Advanced (optional)
  parsing_timeout: 30  # seconds
  retry_on_failure: true
  max_retries: 2
```

### No Additional API Keys Required

The AI service uses HA's existing integrations:
- `ai_task.claude_ai_task` → Uses Anthropic integration
- `ai_task.openai_ai_task` → Uses OpenAI integration
- `ai_task.google_ai_task` → Uses Google AI integration

If user has any of these configured, AI features work automatically.

---

## 🔮 FUTURE COORDINATOR INTEGRATION (v3.5.0+)

The AI service layer enables these future capabilities:

### Presence Coordinator
```python
# When signals are ambiguous
if confidence < 0.7:
    response = await ai_service.infer_house_state({
        "census": census_data,
        "time_of_day": datetime.now().strftime("%H:%M"),
        "events": recent_events,
    })
    
    if response.success and response.data["confidence"] > confidence:
        return response.data["house_state"]
```

### Safety Coordinator
```python
# Explain unusual sensor readings
async def explain_anomaly(self, reading: SensorReading):
    response = await ai_service.explain_anomaly({
        "type": "unusual_sensor_reading",
        "entity_id": reading.entity_id,
        "current_value": reading.value,
        "normal_range": reading.expected_range,
        "history": reading.recent_values,
    })
    
    return response.data if response.success else None
```

### Comfort Coordinator
```python
# Learn preference patterns
async def suggest_preference_update(self, feedback: UserFeedback):
    response = await ai_service.generate(AIRequest(
        task_name="analyze_comfort_feedback",
        instructions=f"User adjusted {feedback.setting} from {feedback.old} to {feedback.new}...",
        structure=PREFERENCE_UPDATE_SCHEMA,
    ))
    
    if response.success:
        return response.data["suggested_preference"]
```

---

## 🎯 SUCCESS CRITERIA

**Functional:**
- ✅ AI service initializes with available providers
- ✅ Natural language instructions parsed correctly
- ✅ Rules validated against HA entities
- ✅ Custom occupancy detection works
- ✅ Conditional overrides work
- ✅ Graceful degradation if AI unavailable

**Quality:**
- ✅ Provider-agnostic (works with Claude/GPT/Gemini)
- ✅ Automatic fallback on provider failure
- ✅ Clear error messages
- ✅ No additional API key configuration required

**Architecture:**
- ✅ AI service reusable by coordinators
- ✅ Clean separation of concerns
- ✅ Well-defined interfaces for future expansion

---

## ⚠️ RISK MITIGATION

| Risk | Mitigation |
|------|------------|
| AI provider unavailable | Fallback chain + graceful degradation |
| Parsing errors | Validation layer + clear error messages |
| Rate limiting | Caching + retry with backoff |
| Response format changes | Schema validation + version checks |
| HA AI integration changes | Abstract service layer isolates changes |

---

**PLANNING v3.4.0 (REVISED) - AI Custom Automation**  
**Status:** Complete specification  
**Ready for:** Implementation  
**Estimated Effort:** 10-12 hours  
**Dependencies:** v3.3.0 deployed, HA AI integrations configured  
**Target:** Q2 2026

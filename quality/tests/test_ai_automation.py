"""Tests for v3.12.0 AI rule constants.

AI-ROOM-RULES-TRUST-REPAIR-1 D9: the inline replicas of the executor,
person filter, conflict detector, config persistence and status sensor
that lived here are DELETED (they re-implemented production logic and
proved nothing about it). Real-path coverage: test_room_rules_executor.py,
test_rule_compiler.py, test_room_rules_flow.py, test_room_rules_observability.py.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'custom_components', 'universal_room_automation'))

from const import (
    CONF_AI_RULES,
    CONF_AUTOMATION_CHAINS,
    CONF_AI_RULE_TRIGGER,
    CONF_AI_RULE_PERSON,
    CONF_AI_RULE_DESCRIPTION,
    TRIGGER_ENTER,
    TRIGGER_EXIT,
    TRIGGER_LUX_DARK,
    TRIGGER_LUX_BRIGHT,
    TRIGGER_ENERGY_CONSTRAINT,
    TRIGGER_HOUSE_STATE_PREFIX,
    TRIGGER_SAFETY_HAZARD,
    TRIGGER_SECURITY_EVENT,
    AI_RULE_PARSING_PROMPT,
    AI_RULE_TRIGGER_OPTIONS,
    AUTOMATION_CHAIN_TRIGGERS_M2,
    CONF_LIGHTS,
    CONF_FANS,
    CONF_AUTO_DEVICES,
    CONF_AUTO_SWITCHES,
    CONF_CLIMATE_ENTITY,
)


# =============================================================================
# AI RULE CONSTANTS
# =============================================================================

class TestAIRuleConstants:
    """Validate M3 AI rule constants."""

    def test_ai_rule_constants_exist(self):
        """All M3 constants should be importable."""
        assert CONF_AI_RULES == "ai_rules"
        assert CONF_AI_RULE_TRIGGER == "ai_rule_trigger"
        assert CONF_AI_RULE_PERSON == "ai_rule_person"
        assert CONF_AI_RULE_DESCRIPTION == "ai_rule_description"

    def test_parsing_prompt_has_placeholders(self):
        """AI_RULE_PARSING_PROMPT must contain all 4 placeholder keys."""
        assert "{room_name}" in AI_RULE_PARSING_PROMPT
        assert "{trigger_label}" in AI_RULE_PARSING_PROMPT
        assert "{description}" in AI_RULE_PARSING_PROMPT
        assert "{entities_json}" in AI_RULE_PARSING_PROMPT

    def test_ai_rule_trigger_options_match_m2(self):
        """AI_RULE_TRIGGER_OPTIONS should equal the M2 trigger list."""
        assert AI_RULE_TRIGGER_OPTIONS == AUTOMATION_CHAIN_TRIGGERS_M2

    def test_ai_rule_trigger_options_include_all_types(self):
        """Trigger options include occupancy, lux, house state, and coordinator triggers."""
        assert TRIGGER_ENTER in AI_RULE_TRIGGER_OPTIONS
        assert TRIGGER_EXIT in AI_RULE_TRIGGER_OPTIONS
        assert TRIGGER_LUX_DARK in AI_RULE_TRIGGER_OPTIONS
        assert TRIGGER_LUX_BRIGHT in AI_RULE_TRIGGER_OPTIONS
        assert TRIGGER_ENERGY_CONSTRAINT in AI_RULE_TRIGGER_OPTIONS
        assert TRIGGER_SAFETY_HAZARD in AI_RULE_TRIGGER_OPTIONS
        assert TRIGGER_SECURITY_EVENT in AI_RULE_TRIGGER_OPTIONS
        # At least one house state trigger
        assert f"{TRIGGER_HOUSE_STATE_PREFIX}away" in AI_RULE_TRIGGER_OPTIONS



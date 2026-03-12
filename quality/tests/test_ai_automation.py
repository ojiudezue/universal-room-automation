"""Tests for v3.12.0 AI Automation (M3+M4).

Tests AI rule execution, person filtering, conflict detection,
builtin target entity resolution, config persistence, and the
AIAutomationStatusSensor diagnostic sensor.
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
# HELPERS
# =============================================================================

def _make_rule(
    rule_id="rule_1",
    trigger_type=TRIGGER_ENTER,
    person="",
    description="Test rule",
    actions=None,
    enabled=True,
):
    """Create a well-formed AI rule dict."""
    return {
        "rule_id": rule_id,
        "trigger_type": trigger_type,
        "person": person,
        "description": description,
        "actions": actions or [],
        "enabled": enabled,
        "created_at": "2026-03-12T00:00:00+00:00",
    }


def _make_action(domain="light", service="turn_on", entity_id="light.bedroom", data=None):
    """Create a parsed action dict."""
    return {
        "domain": domain,
        "service": service,
        "target": {"entity_id": entity_id},
        "data": data or {},
    }


def _make_config_entry(data=None, options=None):
    """Create a mock config entry."""
    from conftest import MockConfigEntry
    return MockConfigEntry(
        data=data or {"room_name": "Office"},
        options=options or {},
    )


def _get_config(entry, key, default=None):
    """Replicate coordinator._get_config logic."""
    return entry.options.get(key, entry.data.get(key, default))


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


# =============================================================================
# AI RULE EXECUTION (inline logic)
# =============================================================================

class TestAIRuleExecution:
    """Test AI rule filtering logic (trigger match, person filter, enabled).

    Replicates _execute_ai_rules logic inline since coordinator.py
    cannot be imported due to homeassistant dependency.
    """

    def _filter_rules(self, rules, triggers, identified_persons):
        """Inline version of the rule filtering logic from _execute_ai_rules."""
        matched = []
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("trigger_type") not in triggers:
                continue

            person_filter = rule.get("person", "").strip()
            if person_filter:
                match = any(
                    person_filter.lower() == p.lower()
                    for p in identified_persons
                )
                if not match:
                    continue
            matched.append(rule)
        return matched

    def test_matching_trigger_fires_rule(self):
        """Rule with matching trigger should pass the filter."""
        rule = _make_rule(trigger_type=TRIGGER_ENTER)
        matched = self._filter_rules([rule], [TRIGGER_ENTER], [])
        assert len(matched) == 1

    def test_wrong_trigger_skips_rule(self):
        """Rule with non-matching trigger should be skipped."""
        rule = _make_rule(trigger_type=TRIGGER_EXIT)
        matched = self._filter_rules([rule], [TRIGGER_ENTER], [])
        assert len(matched) == 0

    def test_disabled_rule_skips(self):
        """Disabled rule should be skipped regardless of trigger."""
        rule = _make_rule(trigger_type=TRIGGER_ENTER, enabled=False)
        matched = self._filter_rules([rule], [TRIGGER_ENTER], [])
        assert len(matched) == 0

    def test_person_specific_match_fires(self):
        """Rule with person filter should fire when person is present."""
        rule = _make_rule(trigger_type=TRIGGER_ENTER, person="Alice")
        matched = self._filter_rules([rule], [TRIGGER_ENTER], ["Alice", "Bob"])
        assert len(matched) == 1

    def test_person_specific_mismatch_skips(self):
        """Rule with person filter should skip when person is NOT present."""
        rule = _make_rule(trigger_type=TRIGGER_ENTER, person="Charlie")
        matched = self._filter_rules([rule], [TRIGGER_ENTER], ["Alice", "Bob"])
        assert len(matched) == 0

    def test_any_person_rule_fires_for_all(self):
        """Rule with empty person filter fires for any occupant."""
        rule = _make_rule(trigger_type=TRIGGER_ENTER, person="")
        matched = self._filter_rules([rule], [TRIGGER_ENTER], ["Alice"])
        assert len(matched) == 1

    def test_any_person_rule_fires_with_no_persons(self):
        """Rule with empty person filter fires even with no identified persons."""
        rule = _make_rule(trigger_type=TRIGGER_ENTER, person="")
        matched = self._filter_rules([rule], [TRIGGER_ENTER], [])
        assert len(matched) == 1

    def test_person_filter_case_insensitive(self):
        """Person filter should match case-insensitively."""
        rule = _make_rule(trigger_type=TRIGGER_ENTER, person="alice")
        matched = self._filter_rules([rule], [TRIGGER_ENTER], ["Alice"])
        assert len(matched) == 1

        rule2 = _make_rule(trigger_type=TRIGGER_ENTER, person="ALICE")
        matched2 = self._filter_rules([rule2], [TRIGGER_ENTER], ["alice"])
        assert len(matched2) == 1

    def test_empty_rules_list_no_op(self):
        """Empty rules list returns nothing."""
        matched = self._filter_rules([], [TRIGGER_ENTER], ["Alice"])
        assert len(matched) == 0

    def test_multiple_rules_partial_match(self):
        """Only matching rules from a mixed set should pass."""
        rules = [
            _make_rule(rule_id="r1", trigger_type=TRIGGER_ENTER),
            _make_rule(rule_id="r2", trigger_type=TRIGGER_EXIT),
            _make_rule(rule_id="r3", trigger_type=TRIGGER_ENTER, enabled=False),
        ]
        matched = self._filter_rules(rules, [TRIGGER_ENTER], [])
        assert len(matched) == 1
        assert matched[0]["rule_id"] == "r1"


# =============================================================================
# AI RULE ACTION EXECUTION (async, inline logic)
# =============================================================================

class TestAIRuleActionExecution:
    """Test AI rule action execution logic."""

    async def _execute_rule_action(self, hass, action, room_name="Test"):
        """Inline version of coordinator._execute_rule_action."""
        domain = action.get("domain")
        service = action.get("service")
        target = action.get("target", {})
        data = {**action.get("data", {})}

        if not domain or not service:
            return False

        entity_id = target.get("entity_id")
        if entity_id:
            data["entity_id"] = entity_id

        try:
            await asyncio.wait_for(
                hass.services.async_call(domain, service, data, blocking=False),
                timeout=5.0,
            )
            return True
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False

    @pytest.mark.asyncio
    async def test_valid_action_calls_service(self):
        """Valid action with domain+service should call the service."""
        from conftest import MockHass
        hass = MockHass()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        action = _make_action(domain="light", service="turn_on", entity_id="light.bedroom")
        result = await self._execute_rule_action(hass, action)

        assert result is True
        hass.services.async_call.assert_called_once_with(
            "light", "turn_on",
            {"entity_id": "light.bedroom"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_action_with_entity_id_in_target(self):
        """Entity ID from target should be merged into data."""
        from conftest import MockHass
        hass = MockHass()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        action = _make_action(
            domain="light", service="turn_on",
            entity_id="light.kitchen",
            data={"brightness_pct": 80},
        )
        await self._execute_rule_action(hass, action)

        call_args = hass.services.async_call.call_args
        assert call_args[0][0] == "light"
        assert call_args[0][1] == "turn_on"
        assert call_args[0][2]["entity_id"] == "light.kitchen"
        assert call_args[0][2]["brightness_pct"] == 80

    @pytest.mark.asyncio
    async def test_action_missing_domain_skips(self):
        """Action without domain should not call any service."""
        from conftest import MockHass
        hass = MockHass()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        action = {"service": "turn_on", "target": {}, "data": {}}
        result = await self._execute_rule_action(hass, action)

        assert result is False
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_action_missing_service_skips(self):
        """Action without service should not call any service."""
        from conftest import MockHass
        hass = MockHass()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        action = {"domain": "light", "target": {}, "data": {}}
        result = await self._execute_rule_action(hass, action)

        assert result is False
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_action_timeout_handled(self):
        """Timeout during service call should be handled gracefully."""
        from conftest import MockHass
        hass = MockHass()
        hass.services = MagicMock()

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)

        hass.services.async_call = slow_call

        action = _make_action()
        # Use a very short timeout override
        result = await self._execute_rule_action_with_timeout(hass, action, timeout=0.01)
        assert result is False

    async def _execute_rule_action_with_timeout(self, hass, action, timeout=5.0):
        """Version with configurable timeout for testing."""
        domain = action.get("domain")
        service = action.get("service")
        target = action.get("target", {})
        data = {**action.get("data", {})}

        if not domain or not service:
            return False

        entity_id = target.get("entity_id")
        if entity_id:
            data["entity_id"] = entity_id

        try:
            await asyncio.wait_for(
                hass.services.async_call(domain, service, data, blocking=False),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False

    @pytest.mark.asyncio
    async def test_action_exception_handled(self):
        """Exception during service call should be handled gracefully."""
        from conftest import MockHass
        hass = MockHass()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(side_effect=RuntimeError("service failed"))

        action = _make_action()
        result = await self._execute_rule_action(hass, action)
        assert result is False


# =============================================================================
# CONFLICT DETECTION (inline logic)
# =============================================================================

class TestConflictDetection:
    """Test entity conflict detection between AI rules and URA built-in automation.

    Replicates _detect_ai_rule_conflicts + _get_builtin_target_entities logic inline.
    """

    def _get_builtin_target_entities(self, config, trigger):
        """Inline version of coordinator._get_builtin_target_entities."""
        entities = []
        if trigger in (TRIGGER_ENTER, TRIGGER_LUX_DARK):
            entities.extend(config.get(CONF_LIGHTS, []))
            entities.extend(config.get(CONF_FANS, []))
            climate = config.get(CONF_CLIMATE_ENTITY)
            if climate:
                entities.append(climate)
        elif trigger in (TRIGGER_EXIT, TRIGGER_LUX_BRIGHT):
            entities.extend(config.get(CONF_LIGHTS, []))
            entities.extend(config.get(CONF_FANS, []))
            entities.extend(config.get(CONF_AUTO_DEVICES, []))
            entities.extend(config.get(CONF_AUTO_SWITCHES, []))
        return entities

    def _detect_conflicts(self, config, rule, trigger):
        """Inline version of coordinator._detect_ai_rule_conflicts."""
        ura_entities = set(self._get_builtin_target_entities(config, trigger))
        if not ura_entities:
            return None

        rule_entities = set()
        for action in rule.get("actions", []):
            target = action.get("target", {})
            entity_id = target.get("entity_id")
            if entity_id:
                if isinstance(entity_id, list):
                    rule_entities.update(entity_id)
                else:
                    rule_entities.add(entity_id)

        contested = ura_entities & rule_entities
        if contested:
            return {
                "rule_id": rule.get("rule_id"),
                "trigger": trigger,
                "contested_entities": sorted(contested),
            }
        return None

    def test_no_conflict_different_entities(self):
        """No conflict when AI rule targets different entities than URA."""
        config = {CONF_LIGHTS: ["light.bedroom"]}
        rule = _make_rule(
            trigger_type=TRIGGER_ENTER,
            actions=[_make_action(entity_id="light.hallway")],
        )
        conflict = self._detect_conflicts(config, rule, TRIGGER_ENTER)
        assert conflict is None

    def test_conflict_detected_same_entity(self):
        """Conflict detected when AI rule targets same entity as URA."""
        config = {CONF_LIGHTS: ["light.bedroom"]}
        rule = _make_rule(
            trigger_type=TRIGGER_ENTER,
            actions=[_make_action(entity_id="light.bedroom")],
        )
        conflict = self._detect_conflicts(config, rule, TRIGGER_ENTER)
        assert conflict is not None
        assert "light.bedroom" in conflict["contested_entities"]

    def test_conflict_with_multiple_entities(self):
        """Conflict detected with multiple overlapping entities."""
        config = {
            CONF_LIGHTS: ["light.bedroom", "light.desk"],
            CONF_FANS: ["fan.bedroom"],
        }
        rule = _make_rule(
            trigger_type=TRIGGER_ENTER,
            actions=[
                _make_action(entity_id="light.bedroom"),
                _make_action(domain="fan", service="turn_on", entity_id="fan.bedroom"),
            ],
        )
        conflict = self._detect_conflicts(config, rule, TRIGGER_ENTER)
        assert conflict is not None
        assert len(conflict["contested_entities"]) == 2
        assert "light.bedroom" in conflict["contested_entities"]
        assert "fan.bedroom" in conflict["contested_entities"]

    def test_no_ura_entities_no_conflict(self):
        """No conflict when URA has no entities configured for the trigger."""
        config = {}  # No lights, fans, etc.
        rule = _make_rule(
            trigger_type=TRIGGER_ENTER,
            actions=[_make_action(entity_id="light.bedroom")],
        )
        conflict = self._detect_conflicts(config, rule, TRIGGER_ENTER)
        assert conflict is None

    def test_conflict_sets_flag_and_appends(self):
        """Simulate coordinator conflict state tracking."""
        conflict_detected = False
        last_conflicts = []

        config = {CONF_LIGHTS: ["light.bedroom"]}
        rule = _make_rule(
            trigger_type=TRIGGER_ENTER,
            actions=[_make_action(entity_id="light.bedroom")],
        )
        conflict = self._detect_conflicts(config, rule, TRIGGER_ENTER)
        if conflict:
            conflict_detected = True
            last_conflicts.append(conflict)

        assert conflict_detected is True
        assert len(last_conflicts) == 1

    def test_exit_conflict_includes_auto_devices(self):
        """Exit trigger conflict check includes auto_devices and auto_switches."""
        config = {
            CONF_LIGHTS: ["light.bedroom"],
            CONF_AUTO_DEVICES: ["switch.heater"],
        }
        rule = _make_rule(
            trigger_type=TRIGGER_EXIT,
            actions=[_make_action(domain="switch", service="turn_off", entity_id="switch.heater")],
        )
        conflict = self._detect_conflicts(config, rule, TRIGGER_EXIT)
        assert conflict is not None
        assert "switch.heater" in conflict["contested_entities"]

    def test_rule_with_list_entity_id(self):
        """Conflict detection handles list-type entity_ids in actions."""
        config = {CONF_LIGHTS: ["light.bedroom", "light.desk"]}
        rule = _make_rule(
            trigger_type=TRIGGER_ENTER,
            actions=[{
                "domain": "light",
                "service": "turn_on",
                "target": {"entity_id": ["light.bedroom", "light.hallway"]},
                "data": {},
            }],
        )
        conflict = self._detect_conflicts(config, rule, TRIGGER_ENTER)
        assert conflict is not None
        assert "light.bedroom" in conflict["contested_entities"]
        assert "light.hallway" not in conflict["contested_entities"]


# =============================================================================
# BUILTIN TARGET ENTITIES
# =============================================================================

class TestBuiltinTargetEntities:
    """Test _get_builtin_target_entities logic."""

    def _get_builtin_target_entities(self, config, trigger):
        """Inline version of coordinator._get_builtin_target_entities."""
        entities = []
        if trigger in (TRIGGER_ENTER, TRIGGER_LUX_DARK):
            entities.extend(config.get(CONF_LIGHTS, []))
            entities.extend(config.get(CONF_FANS, []))
            climate = config.get(CONF_CLIMATE_ENTITY)
            if climate:
                entities.append(climate)
        elif trigger in (TRIGGER_EXIT, TRIGGER_LUX_BRIGHT):
            entities.extend(config.get(CONF_LIGHTS, []))
            entities.extend(config.get(CONF_FANS, []))
            entities.extend(config.get(CONF_AUTO_DEVICES, []))
            entities.extend(config.get(CONF_AUTO_SWITCHES, []))
        return entities

    def test_enter_returns_lights_fans_climate(self):
        """Enter trigger returns lights, fans, and climate entity."""
        config = {
            CONF_LIGHTS: ["light.bedroom"],
            CONF_FANS: ["fan.bedroom"],
            CONF_CLIMATE_ENTITY: "climate.bedroom",
        }
        entities = self._get_builtin_target_entities(config, TRIGGER_ENTER)
        assert "light.bedroom" in entities
        assert "fan.bedroom" in entities
        assert "climate.bedroom" in entities

    def test_lux_dark_same_as_enter(self):
        """lux_dark trigger returns same entities as enter."""
        config = {
            CONF_LIGHTS: ["light.bedroom"],
            CONF_FANS: ["fan.bedroom"],
            CONF_CLIMATE_ENTITY: "climate.bedroom",
        }
        enter = self._get_builtin_target_entities(config, TRIGGER_ENTER)
        lux_dark = self._get_builtin_target_entities(config, TRIGGER_LUX_DARK)
        assert set(enter) == set(lux_dark)

    def test_exit_returns_lights_fans_devices_switches(self):
        """Exit trigger returns lights, fans, auto_devices, auto_switches."""
        config = {
            CONF_LIGHTS: ["light.bedroom"],
            CONF_FANS: ["fan.bedroom"],
            CONF_AUTO_DEVICES: ["switch.heater"],
            CONF_AUTO_SWITCHES: ["switch.lamp"],
        }
        entities = self._get_builtin_target_entities(config, TRIGGER_EXIT)
        assert "light.bedroom" in entities
        assert "fan.bedroom" in entities
        assert "switch.heater" in entities
        assert "switch.lamp" in entities

    def test_lux_bright_same_as_exit(self):
        """lux_bright trigger returns same entities as exit."""
        config = {
            CONF_LIGHTS: ["light.bedroom"],
            CONF_AUTO_DEVICES: ["switch.heater"],
        }
        exit_ents = self._get_builtin_target_entities(config, TRIGGER_EXIT)
        bright_ents = self._get_builtin_target_entities(config, TRIGGER_LUX_BRIGHT)
        assert set(exit_ents) == set(bright_ents)

    def test_unknown_trigger_returns_empty(self):
        """Unknown trigger type returns empty list."""
        config = {
            CONF_LIGHTS: ["light.bedroom"],
            CONF_FANS: ["fan.bedroom"],
        }
        entities = self._get_builtin_target_entities(config, "unknown_trigger")
        assert entities == []

    def test_enter_without_climate(self):
        """Enter trigger without climate entity omits it."""
        config = {
            CONF_LIGHTS: ["light.bedroom"],
            CONF_FANS: [],
        }
        entities = self._get_builtin_target_entities(config, TRIGGER_ENTER)
        assert "light.bedroom" in entities
        assert len(entities) == 1


# =============================================================================
# CONFIG PERSISTENCE
# =============================================================================

class TestConfigPersistence:
    """Test AI rule storage and backward compatibility."""

    def test_ai_rule_stored_in_options(self):
        """AI rules should be retrievable from entry.options."""
        rule = _make_rule()
        entry = _make_config_entry(options={CONF_AI_RULES: [rule]})
        rules = _get_config(entry, CONF_AI_RULES, [])
        assert len(rules) == 1
        assert rules[0]["rule_id"] == "rule_1"

    def test_ai_rule_stored_in_data_fallback(self):
        """AI rules in data should be found when options is empty."""
        rule = _make_rule()
        entry = _make_config_entry(
            data={"room_name": "Office", CONF_AI_RULES: [rule]},
            options={},
        )
        rules = _get_config(entry, CONF_AI_RULES, [])
        assert len(rules) == 1

    def test_empty_rules_backward_compat(self):
        """Room config without ai_rules key returns empty list."""
        entry = _make_config_entry(data={"room_name": "Test"}, options={})
        rules = _get_config(entry, CONF_AI_RULES, [])
        assert rules == []

    def test_rule_structure_complete(self):
        """A well-formed rule has all required fields."""
        rule = _make_rule(
            rule_id="abc123",
            trigger_type=TRIGGER_ENTER,
            person="Alice",
            description="Turn on lights when Alice enters",
            actions=[_make_action()],
            enabled=True,
        )
        assert "rule_id" in rule
        assert "trigger_type" in rule
        assert "person" in rule
        assert "description" in rule
        assert "actions" in rule
        assert "enabled" in rule
        assert "created_at" in rule

    def test_options_override_data(self):
        """Options should override data for _get_config."""
        data_rule = _make_rule(rule_id="data_rule")
        opt_rule = _make_rule(rule_id="opt_rule")
        entry = _make_config_entry(
            data={"room_name": "Office", CONF_AI_RULES: [data_rule]},
            options={CONF_AI_RULES: [opt_rule]},
        )
        rules = _get_config(entry, CONF_AI_RULES, [])
        assert len(rules) == 1
        assert rules[0]["rule_id"] == "opt_rule"

    def test_chains_and_rules_coexist(self):
        """Both automation_chains and ai_rules can exist in same config."""
        entry = _make_config_entry(
            options={
                CONF_AUTOMATION_CHAINS: {"enter": "automation.welcome"},
                CONF_AI_RULES: [_make_rule()],
            }
        )
        chains = _get_config(entry, CONF_AUTOMATION_CHAINS, {})
        rules = _get_config(entry, CONF_AI_RULES, [])
        assert len(chains) == 1
        assert len(rules) == 1


# =============================================================================
# AI AUTOMATION STATUS SENSOR (inline logic)
# =============================================================================

class TestAIAutomationStatusSensor:
    """Test AIAutomationStatusSensor native_value and attributes."""

    def _sensor_value(self, rules, chains):
        """Simulate sensor.native_value logic."""
        if rules or chains:
            return "active"
        return "inactive"

    def _sensor_attrs(self, rules, chains, last_trigger=None,
                      last_trigger_time=None, conflict_detected=False,
                      last_conflicts=None):
        """Simulate sensor.extra_state_attributes logic."""
        return {
            "chained_automations": chains,
            "ai_rules_count": len(rules),
            "last_trigger": last_trigger,
            "last_trigger_time": last_trigger_time,
            "conflict_detected": conflict_detected,
            "last_conflicts": (last_conflicts or [])[-5:],
        }

    def test_inactive_when_no_config(self):
        """Sensor shows 'inactive' when no rules or chains configured."""
        assert self._sensor_value([], {}) == "inactive"

    def test_active_with_rules_only(self):
        """Sensor shows 'active' when AI rules are configured."""
        assert self._sensor_value([_make_rule()], {}) == "active"

    def test_active_with_chains_only(self):
        """Sensor shows 'active' when chains are configured."""
        assert self._sensor_value([], {"enter": "automation.welcome"}) == "active"

    def test_active_with_both(self):
        """Sensor shows 'active' with both rules and chains."""
        assert self._sensor_value(
            [_make_rule()], {"enter": "automation.welcome"}
        ) == "active"

    def test_attributes_include_all_fields(self):
        """Sensor attributes include all expected fields."""
        attrs = self._sensor_attrs(
            rules=[_make_rule()],
            chains={"enter": "automation.welcome"},
            last_trigger="enter",
            last_trigger_time="2026-03-12T00:00:00+00:00",
            conflict_detected=True,
            last_conflicts=[{"rule_id": "r1", "trigger": "enter", "contested_entities": ["light.bedroom"]}],
        )
        assert "chained_automations" in attrs
        assert "ai_rules_count" in attrs
        assert "last_trigger" in attrs
        assert "last_trigger_time" in attrs
        assert "conflict_detected" in attrs
        assert "last_conflicts" in attrs
        assert attrs["ai_rules_count"] == 1
        assert attrs["conflict_detected"] is True

    def test_last_conflicts_capped_at_5(self):
        """last_conflicts attribute caps at 5 most recent entries."""
        conflicts = [{"rule_id": f"r{i}"} for i in range(10)]
        attrs = self._sensor_attrs([], {}, last_conflicts=conflicts)
        assert len(attrs["last_conflicts"]) == 5
        # Should be the LAST 5
        assert attrs["last_conflicts"][0]["rule_id"] == "r5"

    def test_attributes_none_defaults(self):
        """Attributes have sensible None defaults when nothing has fired."""
        attrs = self._sensor_attrs([], {})
        assert attrs["last_trigger"] is None
        assert attrs["last_trigger_time"] is None
        assert attrs["conflict_detected"] is False
        assert attrs["last_conflicts"] == []

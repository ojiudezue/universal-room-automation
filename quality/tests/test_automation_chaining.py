"""Tests for v3.10.0/v3.12.0 trigger constants (M1 + M2).

AI-ROOM-RULES-TRUST-REPAIR-1 D9: the inline replicas (mock lux detector,
chain firing, config persistence, signal handlers) are DELETED. Legacy
chains are now read by the rule adapter and run through the one executor:
test_room_rules_executor.py (test_legacy_chain_dict_becomes_automation_rules,
test_rules_automation_goes_through_gate).
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'custom_components', 'universal_room_automation'))

from const import (
    CONF_AUTOMATION_CHAINS,
    LUX_DARK_THRESHOLD,
    LUX_BRIGHT_THRESHOLD,
    TRIGGER_ENTER,
    TRIGGER_EXIT,
    TRIGGER_LUX_DARK,
    TRIGGER_LUX_BRIGHT,
    AUTOMATION_CHAIN_TRIGGERS_M1,
    # v3.12.0 M2
    TRIGGER_HOUSE_STATE_PREFIX,
    TRIGGER_ENERGY_CONSTRAINT,
    TRIGGER_SAFETY_HAZARD,
    TRIGGER_SECURITY_EVENT,
    HOUSE_STATE_TRIGGER_VALUES,
    AUTOMATION_CHAIN_TRIGGERS_M2,
    CHAIN_GROUP_OCCUPANCY,
    CHAIN_GROUP_LIGHT,
    CHAIN_GROUP_HOUSE_STATE,
    CHAIN_GROUP_COORDINATOR,
)


class TestConstants:
    """Validate M1 constants."""

    def test_trigger_list_has_four_entries(self):
        assert len(AUTOMATION_CHAIN_TRIGGERS_M1) == 4

    def test_triggers_are_strings(self):
        for t in AUTOMATION_CHAIN_TRIGGERS_M1:
            assert isinstance(t, str)

    def test_thresholds_ordered(self):
        """Dark threshold must be less than bright threshold."""
        assert LUX_DARK_THRESHOLD < LUX_BRIGHT_THRESHOLD


# =============================================================================
# v3.12.0 M2: COORDINATOR SIGNAL TRIGGERS
# =============================================================================

class TestM2Constants:
    """Validate M2 constants."""

    def test_m2_trigger_list_has_16_entries(self):
        """M2 list: 4 M1 + 9 house states + 3 coordinator = 16."""
        assert len(AUTOMATION_CHAIN_TRIGGERS_M2) == 16

    def test_m2_includes_all_m1_triggers(self):
        """M2 trigger list is a superset of M1."""
        for t in AUTOMATION_CHAIN_TRIGGERS_M1:
            assert t in AUTOMATION_CHAIN_TRIGGERS_M2

    def test_house_state_triggers_use_prefix(self):
        """All house state triggers start with the prefix."""
        for s in HOUSE_STATE_TRIGGER_VALUES:
            trigger = f"{TRIGGER_HOUSE_STATE_PREFIX}{s}"
            assert trigger in AUTOMATION_CHAIN_TRIGGERS_M2

    def test_house_state_values_complete(self):
        """All 9 house states are listed."""
        expected = {"away", "arriving", "home_day", "home_evening",
                    "home_night", "sleep", "waking", "guest", "vacation"}
        assert set(HOUSE_STATE_TRIGGER_VALUES) == expected

    def test_coordinator_triggers_in_m2(self):
        """Energy, safety, security triggers are in M2 list."""
        assert TRIGGER_ENERGY_CONSTRAINT in AUTOMATION_CHAIN_TRIGGERS_M2
        assert TRIGGER_SAFETY_HAZARD in AUTOMATION_CHAIN_TRIGGERS_M2
        assert TRIGGER_SECURITY_EVENT in AUTOMATION_CHAIN_TRIGGERS_M2

    def test_trigger_groups_cover_all_m2(self):
        """The 4 trigger groups together cover all M2 triggers."""
        all_grouped = (
            CHAIN_GROUP_OCCUPANCY
            + CHAIN_GROUP_LIGHT
            + CHAIN_GROUP_HOUSE_STATE
            + CHAIN_GROUP_COORDINATOR
        )
        assert set(all_grouped) == set(AUTOMATION_CHAIN_TRIGGERS_M2)

    def test_trigger_groups_no_overlap(self):
        """Trigger groups do not overlap."""
        groups = [
            CHAIN_GROUP_OCCUPANCY,
            CHAIN_GROUP_LIGHT,
            CHAIN_GROUP_HOUSE_STATE,
            CHAIN_GROUP_COORDINATOR,
        ]
        all_triggers = []
        for g in groups:
            all_triggers.extend(g)
        assert len(all_triggers) == len(set(all_triggers))



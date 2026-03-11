"""Tests for v3.10.0 Automation Chaining (M1).

Tests lux trigger detection, chained automation firing, and config flow persistence.
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
)


# =============================================================================
# LUX TRIGGER DETECTION
# =============================================================================

class MockLuxDetector:
    """Minimal mock with _detect_lux_trigger logic from coordinator.py."""

    def __init__(self):
        self._last_lux_zone = None

    def _detect_lux_trigger(self, current_lux):
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
            return None

        if new_zone == "dark":
            return TRIGGER_LUX_DARK
        elif new_zone == "bright":
            return TRIGGER_LUX_BRIGHT
        return None


class TestLuxTriggerDetection:
    """Test lux threshold crossing detection with 3-zone hysteresis."""

    def test_first_reading_no_trigger(self):
        """First lux reading initializes zone but does not fire a trigger."""
        d = MockLuxDetector()
        assert d._detect_lux_trigger(30) is None
        assert d._last_lux_zone == "dark"

    def test_first_reading_bright(self):
        """First bright reading initializes zone but does not fire."""
        d = MockLuxDetector()
        assert d._detect_lux_trigger(300) is None
        assert d._last_lux_zone == "bright"

    def test_none_lux_returns_none(self):
        """None lux value returns None without changing zone."""
        d = MockLuxDetector()
        d._last_lux_zone = "mid"
        assert d._detect_lux_trigger(None) is None
        assert d._last_lux_zone == "mid"

    def test_dark_transition(self):
        """Mid to dark fires lux_dark."""
        d = MockLuxDetector()
        d._last_lux_zone = "mid"
        result = d._detect_lux_trigger(40)
        assert result == TRIGGER_LUX_DARK

    def test_bright_transition(self):
        """Mid to bright fires lux_bright."""
        d = MockLuxDetector()
        d._last_lux_zone = "mid"
        result = d._detect_lux_trigger(250)
        assert result == TRIGGER_LUX_BRIGHT

    def test_dark_to_bright_fires_bright(self):
        """Direct dark to bright transition fires lux_bright."""
        d = MockLuxDetector()
        d._last_lux_zone = "dark"
        result = d._detect_lux_trigger(250)
        assert result == TRIGGER_LUX_BRIGHT

    def test_bright_to_dark_fires_dark(self):
        """Direct bright to dark transition fires lux_dark."""
        d = MockLuxDetector()
        d._last_lux_zone = "bright"
        result = d._detect_lux_trigger(30)
        assert result == TRIGGER_LUX_DARK

    def test_hysteresis_no_flap(self):
        """Oscillation within mid zone does not fire triggers."""
        d = MockLuxDetector()
        d._last_lux_zone = "mid"
        # Stay in mid
        assert d._detect_lux_trigger(55) is None
        assert d._detect_lux_trigger(100) is None
        assert d._detect_lux_trigger(195) is None
        assert d._last_lux_zone == "mid"

    def test_mid_to_dark_to_mid_no_bright(self):
        """Dark to mid transition returns None (no bright trigger)."""
        d = MockLuxDetector()
        d._last_lux_zone = "mid"
        assert d._detect_lux_trigger(30) == TRIGGER_LUX_DARK
        # Back to mid — no trigger
        assert d._detect_lux_trigger(100) is None
        assert d._last_lux_zone == "mid"

    def test_same_zone_no_retrigger(self):
        """Staying in same zone does not re-fire trigger."""
        d = MockLuxDetector()
        d._last_lux_zone = "dark"
        assert d._detect_lux_trigger(10) is None
        assert d._detect_lux_trigger(20) is None
        assert d._detect_lux_trigger(49) is None

    def test_boundary_values(self):
        """Test exact threshold boundary values."""
        d = MockLuxDetector()
        # Exactly at LUX_DARK_THRESHOLD (50) = mid zone (not < 50)
        d._last_lux_zone = "dark"
        result = d._detect_lux_trigger(50)
        assert result is None  # 50 is mid, dark->mid = None
        assert d._last_lux_zone == "mid"

        # Exactly at LUX_BRIGHT_THRESHOLD (200) = mid zone (not > 200)
        result = d._detect_lux_trigger(200)
        assert result is None  # 200 is mid, mid->mid = None

        # Just above bright threshold
        result = d._detect_lux_trigger(201)
        assert result == TRIGGER_LUX_BRIGHT


# =============================================================================
# CHAINED AUTOMATION FIRING
# =============================================================================

class TestAutomationChaining:
    """Test chained automation execution logic.

    Tests the _fire_chained_automations logic inline (coordinator.py cannot
    be imported due to homeassistant dependency).
    """

    async def _fire_chained_automations(self, hass, entry, triggers):
        """Inline version of coordinator._fire_chained_automations for testing."""
        chains = entry.options.get(
            CONF_AUTOMATION_CHAINS, entry.data.get(CONF_AUTOMATION_CHAINS, {})
        )
        if not chains:
            return

        room_name = entry.data.get("room_name", "unknown")
        tasks = []

        for trigger in triggers:
            automation_id = chains.get(trigger)
            if not automation_id:
                continue

            state = hass.states.get(automation_id)
            if state is None or state.state in ("unavailable", "off"):
                continue

            tasks.append(
                hass.services.async_call(
                    "automation", "trigger",
                    {"entity_id": automation_id},
                    blocking=False,
                )
            )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    pass  # Would log in production

    def _make_mock(self, chains=None):
        """Create mock hass + entry with chaining support."""
        from conftest import MockHass, MockConfigEntry

        hass = MockHass()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        entry = MockConfigEntry(
            data={"room_name": "Office"},
            options={CONF_AUTOMATION_CHAINS: chains or {}},
        )
        return hass, entry

    @pytest.mark.asyncio
    async def test_enter_fires_chained(self):
        """Enter trigger fires bound automation."""
        hass, entry = self._make_mock(
            chains={"enter": "automation.office_welcome"}
        )
        hass.set_state("automation.office_welcome", "on",
                       {"friendly_name": "Office Welcome"})

        await self._fire_chained_automations(hass, entry, [TRIGGER_ENTER])

        hass.services.async_call.assert_called_once_with(
            "automation", "trigger",
            {"entity_id": "automation.office_welcome"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_exit_fires_chained(self):
        """Exit trigger fires bound automation."""
        hass, entry = self._make_mock(
            chains={"exit": "automation.office_goodbye"}
        )
        hass.set_state("automation.office_goodbye", "on")

        await self._fire_chained_automations(hass, entry, [TRIGGER_EXIT])

        hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_binding_no_fire(self):
        """No bindings configured — no service calls."""
        hass, entry = self._make_mock(chains={})

        await self._fire_chained_automations(hass, entry, [TRIGGER_ENTER])

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_unavailable_automation_skips(self):
        """Nonexistent automation is skipped."""
        hass, entry = self._make_mock(
            chains={"enter": "automation.missing"}
        )
        # State is None (entity doesn't exist)

        await self._fire_chained_automations(hass, entry, [TRIGGER_ENTER])

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_automation_skips(self):
        """Disabled automation (state=off) is skipped."""
        hass, entry = self._make_mock(
            chains={"enter": "automation.disabled_one"}
        )
        hass.set_state("automation.disabled_one", "off")

        await self._fire_chained_automations(hass, entry, [TRIGGER_ENTER])

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_triggers_fire_parallel(self):
        """Multiple triggers in same cycle fire their automations."""
        hass, entry = self._make_mock(
            chains={
                "enter": "automation.welcome",
                "lux_dark": "automation.dim_lights",
            }
        )
        hass.set_state("automation.welcome", "on")
        hass.set_state("automation.dim_lights", "on")

        await self._fire_chained_automations(
            hass, entry, [TRIGGER_ENTER, TRIGGER_LUX_DARK]
        )

        assert hass.services.async_call.call_count == 2

    @pytest.mark.asyncio
    async def test_trigger_without_binding_skips(self):
        """Trigger with no binding does not fire."""
        hass, entry = self._make_mock(
            chains={"enter": "automation.welcome"}
        )
        hass.set_state("automation.welcome", "on")

        await self._fire_chained_automations(
            hass, entry, [TRIGGER_EXIT]  # No exit binding
        )

        hass.services.async_call.assert_not_called()


# =============================================================================
# CONFIG FLOW PERSISTENCE
# =============================================================================

class TestAutomationChainingConfig:
    """Test config flow data persistence for automation chains."""

    def test_empty_selection_produces_empty_bindings(self):
        """Selecting '(none)' for all triggers produces empty dict."""
        user_input = {
            "chain_enter": "",
            "chain_exit": "",
            "chain_lux_dark": "",
            "chain_lux_bright": "",
        }
        bindings = {}
        for trigger in AUTOMATION_CHAIN_TRIGGERS_M1:
            key = f"chain_{trigger}"
            val = user_input.get(key, "")
            if val:
                bindings[trigger] = val
        assert bindings == {}

    def test_partial_selection_persists_correctly(self):
        """Selecting automation for some triggers persists only those."""
        user_input = {
            "chain_enter": "automation.welcome",
            "chain_exit": "",
            "chain_lux_dark": "automation.dim",
            "chain_lux_bright": "",
        }
        bindings = {}
        for trigger in AUTOMATION_CHAIN_TRIGGERS_M1:
            key = f"chain_{trigger}"
            val = user_input.get(key, "")
            if val:
                bindings[trigger] = val
        assert bindings == {
            "enter": "automation.welcome",
            "lux_dark": "automation.dim",
        }

    def test_all_triggers_persist(self):
        """All 4 triggers can be bound simultaneously."""
        user_input = {
            "chain_enter": "automation.a",
            "chain_exit": "automation.b",
            "chain_lux_dark": "automation.c",
            "chain_lux_bright": "automation.d",
        }
        bindings = {}
        for trigger in AUTOMATION_CHAIN_TRIGGERS_M1:
            key = f"chain_{trigger}"
            val = user_input.get(key, "")
            if val:
                bindings[trigger] = val
        assert len(bindings) == 4

    def test_backward_compat_no_chains_key(self):
        """Room config without automation_chains key returns empty dict."""
        from conftest import MockConfigEntry
        entry = MockConfigEntry(data={"room_name": "Test"}, options={})
        chains = entry.options.get(
            CONF_AUTOMATION_CHAINS,
            entry.data.get(CONF_AUTOMATION_CHAINS, {}),
        )
        assert chains == {}


# =============================================================================
# CONSTANTS VALIDATION
# =============================================================================

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

"""Tests for Cycle B: Config Flow UX (v3.20.1).

Covers:
  D1: Automation chaining in initial room setup
  D2: AI rules in initial room setup (with inline parsing)
  D3: Split oversized options step (options_lighting + options_covers)
  D4: Conditional fields (shared space, notification override) — OptionsFlow only
  D5: AI rule person selector (EntitySelector)

Strategy:
  1. Import const.py directly (no HA dependency).
  2. Build a self-contained mock of the HA module tree in a PRIVATE dict,
     inject it into sys.modules only long enough to compile config_flow,
     then RESTORE the original sys.modules so other tests are not polluted.
"""

import sys
import os
import types
import importlib
import importlib.util
import copy
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# ---------------------------------------------------------------------------
# Import const directly (no HA dependency)
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_COMPONENT_DIR = os.path.join(_REPO_ROOT, 'custom_components', 'universal_room_automation')

sys.path.insert(0, _COMPONENT_DIR)
from const import (  # noqa: E402
    DOMAIN,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE_MANAGER,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    CONF_SHARED_SPACE,
    CONF_SHARED_SPACE_AUTO_OFF_HOUR,
    CONF_SHARED_SPACE_WARNING,
    CONF_OVERRIDE_NOTIFICATIONS,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_LEVEL,
    CONF_AUTOMATION_CHAINS,
    CONF_AI_RULES,
    CONF_AI_RULE_TRIGGER,
    CONF_AI_RULE_PERSON,
    CONF_AI_RULE_DESCRIPTION,
    CONF_ENTRY_LIGHT_ACTION,
    CONF_EXIT_LIGHT_ACTION,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_BRIGHTNESS_PCT,
    CONF_LIGHT_TRANSITION_ON,
    CONF_LIGHT_TRANSITION_OFF,
    CONF_COVER_OPEN_MODE,
    CONF_COVER_TYPE,
    CHAIN_GROUP_OCCUPANCY,
    CHAIN_GROUP_LIGHT,
    CHAIN_GROUP_HOUSE_STATE,
    CHAIN_GROUP_COORDINATOR,
    AI_RULE_TRIGGER_OPTIONS,
    ROOM_TYPE_GENERIC,
    LIGHT_ACTION_NONE,
    LIGHT_ACTION_TURN_OFF,
    COVER_OPEN_NONE,
    COVER_TYPE_SHADE,
    NOTIFY_LEVEL_ERRORS,
    DEFAULT_OCCUPANCY_TIMEOUT,
)

# ---------------------------------------------------------------------------
# Build HA mock module tree and load config_flow in isolation
# ---------------------------------------------------------------------------

class _CallableSelector:
    """Base selector that is callable (voluptuous requires it)."""
    def __init__(self, config=None):
        self.config = config
    def __call__(self, value):
        return value

class _SelectorConfig:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

class EntitySelectorConfig(_SelectorConfig): pass
class EntitySelector(_CallableSelector): pass
class SelectSelectorConfig(_SelectorConfig): pass
class SelectSelector(_CallableSelector): pass
class NumberSelectorConfig(_SelectorConfig): pass
class NumberSelector(_CallableSelector): pass
class TextSelectorConfig(_SelectorConfig): pass
class TextSelector(_CallableSelector): pass
class BooleanSelector(_CallableSelector): pass
class AreaSelectorConfig(_SelectorConfig): pass
class AreaSelector(_CallableSelector): pass

class SelectSelectorMode:
    DROPDOWN = "dropdown"
    LIST = "list"

class NumberSelectorMode:
    BOX = "box"
    SLIDER = "slider"

class TextSelectorType:
    TEXT = "text"
    URL = "url"
    EMAIL = "email"
    PASSWORD = "password"
    NUMBER = "number"


def _build_ha_modules():
    """Build a complete homeassistant mock module tree for config_flow."""
    modules = {}

    def _mod(name):
        m = types.ModuleType(name)
        modules[name] = m
        return m

    ha = _mod("homeassistant")
    ha_ce = _mod("homeassistant.config_entries")
    ha_core = _mod("homeassistant.core")
    ha_const = _mod("homeassistant.const")
    ha_helpers = _mod("homeassistant.helpers")
    ha_sel = _mod("homeassistant.helpers.selector")
    ha_er = _mod("homeassistant.helpers.entity_registry")
    ha_dr = _mod("homeassistant.helpers.device_registry")
    ha_ep = _mod("homeassistant.helpers.entity_platform")
    ha_ev = _mod("homeassistant.helpers.event")
    ha_util = _mod("homeassistant.util")
    ha_dt = _mod("homeassistant.util.dt")

    ha.config_entries = ha_ce
    ha.core = ha_core
    ha.const = ha_const
    ha.helpers = ha_helpers
    ha.util = ha_util
    ha_helpers.selector = ha_sel
    ha_helpers.entity_registry = ha_er
    ha_helpers.device_registry = ha_dr
    ha_helpers.entity_platform = ha_ep
    ha_helpers.event = ha_ev
    ha_util.dt = ha_dt

    # ConfigFlow / OptionsFlow base classes
    class FakeConfigFlow:
        VERSION = 1
        def __init_subclass__(cls, **kwargs): pass
        def async_show_form(self, **kw): return {"type": "form", **kw}
        def async_show_menu(self, **kw): return {"type": "menu", **kw}
        def async_create_entry(self, **kw): return {"type": "create_entry", **kw}
        def async_abort(self, **kw): return {"type": "abort", **kw}
        def _async_current_entries(self): return []

    class FakeOptionsFlow:
        def __init_subclass__(cls, **kwargs): pass
        def async_show_form(self, **kw): return {"type": "form", **kw}
        def async_show_menu(self, **kw): return {"type": "menu", **kw}
        def async_create_entry(self, **kw): return {"type": "create_entry", **kw}

    ha_ce.ConfigFlow = FakeConfigFlow
    ha_ce.OptionsFlow = FakeOptionsFlow
    ha_ce.ConfigEntry = MagicMock

    ha_core.callback = lambda f: f
    ha_core.HomeAssistant = MagicMock

    ha_const.CONF_NAME = "name"
    ha_const.Platform = MagicMock()

    ha_ep.AddEntitiesCallback = MagicMock
    ha_ev.async_track_time_interval = MagicMock
    ha_ev.async_track_state_change_event = MagicMock

    ha_er.async_get = MagicMock(return_value=MagicMock())
    ha_dr.async_get = MagicMock(return_value=MagicMock())

    ha_dt.utcnow = MagicMock()

    ha_sel.EntitySelectorConfig = EntitySelectorConfig
    ha_sel.EntitySelector = EntitySelector
    ha_sel.SelectSelectorConfig = SelectSelectorConfig
    ha_sel.SelectSelectorMode = SelectSelectorMode
    ha_sel.SelectSelector = SelectSelector
    ha_sel.NumberSelectorConfig = NumberSelectorConfig
    ha_sel.NumberSelectorMode = NumberSelectorMode
    ha_sel.NumberSelector = NumberSelector
    ha_sel.TextSelectorConfig = TextSelectorConfig
    ha_sel.TextSelectorType = TextSelectorType
    ha_sel.TextSelector = TextSelector
    ha_sel.BooleanSelector = BooleanSelector
    ha_sel.AreaSelectorConfig = AreaSelectorConfig
    ha_sel.AreaSelector = AreaSelector

    return modules


def _load_config_flow():
    """Load config_flow.py with mocked HA modules, then restore sys.modules."""
    ha_modules = _build_ha_modules()

    # Save originals
    saved = {}
    for name in ha_modules:
        if name in sys.modules:
            saved[name] = sys.modules[name]

    # Also save component package modules
    _pkg = "custom_components.universal_room_automation"
    pkg_names = [_pkg, f"{_pkg}.const", f"{_pkg}.config_flow", "custom_components"]
    for name in pkg_names:
        if name in sys.modules:
            saved[name] = sys.modules[name]

    try:
        # Inject HA mocks
        sys.modules.update(ha_modules)

        # Create package scaffold
        if "custom_components" not in sys.modules:
            cc = types.ModuleType("custom_components")
            cc.__path__ = [os.path.join(_REPO_ROOT, "custom_components")]
            sys.modules["custom_components"] = cc

        ura = types.ModuleType(_pkg)
        ura.__path__ = [_COMPONENT_DIR]
        ura.__package__ = _pkg
        sys.modules[_pkg] = ura

        # Load const via importlib (no HA deps)
        const_spec = importlib.util.spec_from_file_location(
            f"{_pkg}.const", os.path.join(_COMPONENT_DIR, "const.py"),
        )
        const_mod = importlib.util.module_from_spec(const_spec)
        const_mod.__package__ = _pkg
        sys.modules[f"{_pkg}.const"] = const_mod
        ura.const = const_mod
        const_spec.loader.exec_module(const_mod)

        # Load config_flow
        cf_spec = importlib.util.spec_from_file_location(
            f"{_pkg}.config_flow", os.path.join(_COMPONENT_DIR, "config_flow.py"),
        )
        cf_mod = importlib.util.module_from_spec(cf_spec)
        cf_mod.__package__ = _pkg
        sys.modules[f"{_pkg}.config_flow"] = cf_mod
        ura.config_flow = cf_mod
        cf_spec.loader.exec_module(cf_mod)

        return cf_mod
    finally:
        # Restore sys.modules — remove what we injected, restore originals
        for name in ha_modules:
            if name in saved:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)
        for name in pkg_names:
            if name in saved:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)


_cf = _load_config_flow()
UniversalRoomAutomationConfigFlow = _cf.UniversalRoomAutomationConfigFlow
UniversalRoomAutomationOptionsFlow = _cf.UniversalRoomAutomationOptionsFlow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeConfigEntry:
    """Minimal ConfigEntry mock for options flow."""
    def __init__(self, data=None, options=None, entry_id="test_room_entry"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id
        self.title = data.get(CONF_ROOM_NAME, "Test Room") if data else "Test Room"


class _FakeHass:
    """Minimal hass mock for config flow tests."""
    def __init__(self):
        self._states = {}
        self.states = MagicMock()
        self.states.get = lambda eid: self._states.get(eid)
        self.states.async_entity_ids = MagicMock(return_value=[])
        self.config_entries = MagicMock()
        self.config_entries.async_entries = MagicMock(return_value=[])
        self.services = MagicMock()
        self.services.async_services = MagicMock(return_value={})
        self.services.async_call = AsyncMock(return_value=None)


def _make_config_flow(hass=None):
    """Create a ConfigFlow instance wired to a fake hass."""
    flow = UniversalRoomAutomationConfigFlow.__new__(UniversalRoomAutomationConfigFlow)
    flow._data = {}
    flow._integration_data = None
    flow._energy_data = None
    flow._integration_entry_id = None
    flow.hass = hass or _FakeHass()
    return flow


def _make_options_flow(data=None, options=None, hass=None):
    """Create an OptionsFlow instance wired to a fake config entry + hass."""
    entry = _FakeConfigEntry(data=data or {}, options=options or {})
    flow = UniversalRoomAutomationOptionsFlow.__new__(UniversalRoomAutomationOptionsFlow)
    flow._config_entry = entry
    flow._selected_zone_entry_id = None
    flow._pending_delete_rule_id = None
    flow.hass = hass or _FakeHass()
    return flow


def _schema_keys(result):
    """Extract schema key names from a show_form result."""
    schema = result.get("data_schema")
    if schema is None:
        return []
    return [str(k) for k in schema.schema]


def _schema_field(result, key_name):
    """Find a selector by key name in a schema."""
    schema = result.get("data_schema")
    if schema is None:
        return None
    for k, v in schema.schema.items():
        if str(k) == key_name:
            return v
    return None


# ============================================================================
# D1: Automation Chaining in Initial Room Setup
# ============================================================================


class TestD1AutomationChainingInitialSetup:
    """D1: Automation chaining step exists in initial room setup flow."""

    @pytest.mark.asyncio
    async def test_automation_behavior_routes_to_chaining(self):
        """After automation_behavior, flow goes to init_automation_chaining (not climate)."""
        flow = _make_config_flow()
        result = await flow.async_step_automation_behavior(user_input={
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_NONE,
        })
        assert result["type"] == "menu"
        assert result["step_id"] == "init_automation_chaining"

    @pytest.mark.asyncio
    async def test_init_automation_chaining_menu_options(self):
        """Chaining menu offers 4 trigger groups + skip."""
        flow = _make_config_flow()
        result = await flow.async_step_init_automation_chaining()
        assert result["type"] == "menu"
        opts = result["menu_options"]
        assert "init_chain_occupancy" in opts
        assert "init_chain_light" in opts
        assert "init_chain_house_state" in opts
        assert "init_chain_coordinator" in opts
        assert "init_chain_skip" in opts

    @pytest.mark.asyncio
    async def test_init_chain_skip_goes_to_ai_rules(self):
        """Skipping chaining goes to AI rules menu."""
        flow = _make_config_flow()
        result = await flow.async_step_init_chain_skip()
        assert result["type"] == "menu"
        assert result["step_id"] == "init_ai_rules"

    @pytest.mark.asyncio
    async def test_init_chain_occupancy_shows_form(self):
        """Occupancy chain step shows form with enter/exit fields."""
        flow = _make_config_flow()
        result = await flow.async_step_init_chain_occupancy(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "init_chain_occupancy"
        keys = _schema_keys(result)
        assert "chain_enter" in keys
        assert "chain_exit" in keys

    @pytest.mark.asyncio
    async def test_init_chain_light_shows_form(self):
        """Light chain step shows form with lux_dark/lux_bright fields."""
        flow = _make_config_flow()
        result = await flow.async_step_init_chain_light(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "init_chain_light"
        keys = _schema_keys(result)
        assert "chain_lux_dark" in keys
        assert "chain_lux_bright" in keys

    @pytest.mark.asyncio
    async def test_init_chain_saves_to_data(self):
        """Submitting a chain trigger stores it in self._data."""
        flow = _make_config_flow()
        result = await flow.async_step_init_chain_occupancy(user_input={
            "chain_enter": "automation.test_enter",
            "chain_exit": "",
        })
        assert result["type"] == "menu"
        assert result["step_id"] == "init_automation_chaining"
        chains = flow._data.get(CONF_AUTOMATION_CHAINS, {})
        assert chains.get("enter") == "automation.test_enter"
        assert "exit" not in chains

    @pytest.mark.asyncio
    async def test_init_chain_preserves_across_groups(self):
        """Chain bindings from different groups are preserved."""
        flow = _make_config_flow()
        await flow.async_step_init_chain_occupancy(user_input={
            "chain_enter": "automation.my_enter",
            "chain_exit": "",
        })
        await flow.async_step_init_chain_light(user_input={
            "chain_lux_dark": "automation.my_dark",
            "chain_lux_bright": "",
        })
        chains = flow._data.get(CONF_AUTOMATION_CHAINS, {})
        assert chains.get("enter") == "automation.my_enter"
        assert chains.get("lux_dark") == "automation.my_dark"


# ============================================================================
# D2: AI Rules in Initial Room Setup
# ============================================================================


class TestD2AIRulesInitialSetup:
    """D2: AI rules step exists in initial room setup flow."""

    @pytest.mark.asyncio
    async def test_ai_rules_menu_after_chaining_skip(self):
        """After skipping chaining, AI rules menu appears."""
        flow = _make_config_flow()
        result = await flow.async_step_init_chain_skip()
        assert result["type"] == "menu"
        assert result["step_id"] == "init_ai_rules"
        opts = result["menu_options"]
        assert "init_ai_rule_add" in opts
        assert "init_ai_rules_skip" in opts

    @pytest.mark.asyncio
    async def test_ai_rules_skip_goes_to_climate(self):
        """Skipping AI rules goes to climate step."""
        flow = _make_config_flow()
        result = await flow.async_step_init_ai_rules_skip()
        assert result["type"] == "form"
        assert result["step_id"] == "climate"

    @pytest.mark.asyncio
    async def test_init_ai_rule_add_shows_form(self):
        """AI rule add step shows form with trigger, person, description fields."""
        flow = _make_config_flow()
        result = await flow.async_step_init_ai_rule_add(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "init_ai_rule_add"
        keys = _schema_keys(result)
        assert CONF_AI_RULE_TRIGGER in keys
        assert CONF_AI_RULE_PERSON in keys
        assert CONF_AI_RULE_DESCRIPTION in keys

    @pytest.mark.asyncio
    async def test_init_ai_rule_add_stores_rule_with_deferred_parsing(self):
        """Adding an AI rule when ai_task is unavailable stores with needs_parsing fallback."""
        hass = _FakeHass()
        # ai_task not available — async_call raises
        hass.services.async_call = AsyncMock(side_effect=Exception("ai_task not found"))
        flow = _make_config_flow(hass=hass)
        result = await flow.async_step_init_ai_rule_add(user_input={
            CONF_AI_RULE_TRIGGER: "enter",
            CONF_AI_RULE_PERSON: "person.john",
            CONF_AI_RULE_DESCRIPTION: "Turn on the lights when I arrive",
        })
        assert result["type"] == "menu"
        assert result["step_id"] == "init_ai_rules"
        rules = flow._data.get(CONF_AI_RULES, [])
        assert len(rules) == 1
        assert rules[0]["trigger_type"] == "enter"
        assert rules[0]["person"] == "person.john"
        assert rules[0]["description"] == "Turn on the lights when I arrive"
        assert rules[0]["needs_parsing"] is True
        assert rules[0]["actions"] == []

    @pytest.mark.asyncio
    async def test_init_ai_rule_add_inline_parsing_success(self):
        """Adding an AI rule when ai_task IS available parses inline."""
        hass = _FakeHass()
        # ai_task returns valid parsed actions
        hass.services.async_call = AsyncMock(return_value={
            "data": {
                "actions": [
                    {
                        "domain": "light",
                        "service": "turn_on",
                        "target": {"entity_id": "light.test"},
                        "data": {"brightness_pct": 80},
                    }
                ]
            }
        })
        # Entity must exist for validation
        hass._states["light.test"] = MagicMock()
        hass.states.get = lambda eid: hass._states.get(eid)
        flow = _make_config_flow(hass=hass)

        # Inject the HA mock modules needed for the inline import of dt_util
        ha_modules = _build_ha_modules()
        saved = {}
        for name in ha_modules:
            if name in sys.modules:
                saved[name] = sys.modules[name]
        sys.modules.update(ha_modules)
        try:
            result = await flow.async_step_init_ai_rule_add(user_input={
                CONF_AI_RULE_TRIGGER: "enter",
                CONF_AI_RULE_PERSON: "",
                CONF_AI_RULE_DESCRIPTION: "Turn on the lights",
            })
        finally:
            for name in ha_modules:
                if name in saved:
                    sys.modules[name] = saved[name]
                else:
                    sys.modules.pop(name, None)

        assert result["type"] == "menu"
        assert result["step_id"] == "init_ai_rules"
        rules = flow._data.get(CONF_AI_RULES, [])
        assert len(rules) == 1
        assert rules[0]["actions"] != []
        assert "needs_parsing" not in rules[0]

    @pytest.mark.asyncio
    async def test_init_ai_rule_add_empty_description_error(self):
        """Empty description should show error."""
        flow = _make_config_flow()
        result = await flow.async_step_init_ai_rule_add(user_input={
            CONF_AI_RULE_TRIGGER: "enter",
            CONF_AI_RULE_PERSON: "",
            CONF_AI_RULE_DESCRIPTION: "",
        })
        assert result["type"] == "form"
        assert result.get("errors", {}).get("base") == "ai_rule_empty_description"

    @pytest.mark.asyncio
    async def test_init_ai_rule_add_multiple_rules(self):
        """Multiple AI rules can be added during initial setup."""
        hass = _FakeHass()
        hass.services.async_call = AsyncMock(side_effect=Exception("ai_task not found"))
        flow = _make_config_flow(hass=hass)
        await flow.async_step_init_ai_rule_add(user_input={
            CONF_AI_RULE_TRIGGER: "enter",
            CONF_AI_RULE_PERSON: "",
            CONF_AI_RULE_DESCRIPTION: "Turn on lights",
        })
        await flow.async_step_init_ai_rule_add(user_input={
            CONF_AI_RULE_TRIGGER: "exit",
            CONF_AI_RULE_PERSON: "",
            CONF_AI_RULE_DESCRIPTION: "Turn off lights",
        })
        rules = flow._data.get(CONF_AI_RULES, [])
        assert len(rules) == 2
        assert rules[0]["trigger_type"] == "enter"
        assert rules[1]["trigger_type"] == "exit"


# ============================================================================
# D3: Split Oversized Options Step
# ============================================================================


class TestD3SplitOptionsStep:
    """D3: automation_behavior options step split into lighting + covers."""

    @pytest.mark.asyncio
    async def test_room_options_menu_has_split_steps(self):
        """Room options menu offers options_lighting and options_covers (not automation_behavior)."""
        flow = _make_options_flow(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM})
        result = await flow.async_step_init()
        opts = result["menu_options"]
        assert "options_lighting" in opts
        assert "options_covers" in opts
        assert "automation_behavior" not in opts

    @pytest.mark.asyncio
    async def test_options_lighting_has_6_fields(self):
        """Lighting step has exactly 6 fields (all lighting-related)."""
        flow = _make_options_flow(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM})
        result = await flow.async_step_options_lighting(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "options_lighting"
        keys = _schema_keys(result)
        assert len(keys) == 6
        assert CONF_ENTRY_LIGHT_ACTION in keys
        assert CONF_EXIT_LIGHT_ACTION in keys
        assert CONF_ILLUMINANCE_THRESHOLD in keys
        assert CONF_LIGHT_BRIGHTNESS_PCT in keys
        assert CONF_LIGHT_TRANSITION_ON in keys
        assert CONF_LIGHT_TRANSITION_OFF in keys

    @pytest.mark.asyncio
    async def test_options_covers_has_10_fields(self):
        """Covers step has exactly 10 fields (all cover-related)."""
        flow = _make_options_flow(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM})
        result = await flow.async_step_options_covers(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "options_covers"
        keys = _schema_keys(result)
        assert len(keys) == 10
        assert CONF_COVER_TYPE in keys
        assert CONF_COVER_OPEN_MODE in keys

    @pytest.mark.asyncio
    async def test_options_lighting_saves_data(self):
        """Submitting lighting options creates entry with merged data."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={"existing_key": "existing_value"},
        )
        result = await flow.async_step_options_lighting(user_input={
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_NONE,
        })
        assert result["type"] == "create_entry"
        assert result["data"]["existing_key"] == "existing_value"
        assert result["data"][CONF_ENTRY_LIGHT_ACTION] == LIGHT_ACTION_NONE

    @pytest.mark.asyncio
    async def test_options_covers_saves_data(self):
        """Submitting cover options creates entry with merged data."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={"existing_key": "existing_value"},
        )
        result = await flow.async_step_options_covers(user_input={
            CONF_COVER_OPEN_MODE: COVER_OPEN_NONE,
        })
        assert result["type"] == "create_entry"
        assert result["data"]["existing_key"] == "existing_value"
        assert result["data"][CONF_COVER_OPEN_MODE] == COVER_OPEN_NONE

    @pytest.mark.asyncio
    async def test_neither_step_exceeds_10_fields(self):
        """Both steps stay within the 10-field limit."""
        flow = _make_options_flow(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM})
        lighting = await flow.async_step_options_lighting(user_input=None)
        covers = await flow.async_step_options_covers(user_input=None)
        assert len(_schema_keys(lighting)) <= 10
        assert len(_schema_keys(covers)) <= 10


# ============================================================================
# D4: Conditional Fields
# ============================================================================


class TestD4ConditionalFields:
    """D4: Shared space and notification override fields hidden when toggle is off.

    REVIEW FIX: Initial ConfigFlow (linear, no back) keeps all fields visible.
    Only OptionsFlow applies conditional hiding.
    """

    @pytest.mark.asyncio
    async def test_initial_room_setup_shared_space_always_visible(self):
        """REVIEW FIX: Initial room_setup always shows shared space detail fields."""
        flow = _make_config_flow()
        result = await flow.async_step_room_setup(user_input=None)
        keys = _schema_keys(result)
        assert CONF_SHARED_SPACE in keys
        # In initial flow, detail fields are always visible
        assert CONF_SHARED_SPACE_AUTO_OFF_HOUR in keys
        assert CONF_SHARED_SPACE_WARNING in keys

    @pytest.mark.asyncio
    async def test_options_basic_setup_no_shared_space_when_off(self):
        """Options basic_setup hides shared space detail when toggle is off."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Test"},
            options={CONF_SHARED_SPACE: False},
        )
        result = await flow.async_step_basic_setup(user_input=None)
        keys = _schema_keys(result)
        assert CONF_SHARED_SPACE in keys
        assert CONF_SHARED_SPACE_AUTO_OFF_HOUR not in keys

    @pytest.mark.asyncio
    async def test_options_basic_setup_shows_shared_space_when_on(self):
        """Options basic_setup shows shared space detail when toggle is on."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Test"},
            options={CONF_SHARED_SPACE: True},
        )
        result = await flow.async_step_basic_setup(user_input=None)
        keys = _schema_keys(result)
        assert CONF_SHARED_SPACE_AUTO_OFF_HOUR in keys
        assert CONF_SHARED_SPACE_WARNING in keys

    @pytest.mark.asyncio
    async def test_options_notifications_no_override_fields_when_off(self):
        """Options notifications hides override fields when toggle is off."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={CONF_OVERRIDE_NOTIFICATIONS: False},
        )
        result = await flow.async_step_notifications(user_input=None)
        keys = _schema_keys(result)
        assert CONF_OVERRIDE_NOTIFICATIONS in keys
        assert CONF_NOTIFY_SERVICE not in keys

    @pytest.mark.asyncio
    async def test_options_notifications_shows_override_fields_when_on(self):
        """Options notifications shows override fields when toggle is on."""
        hass = _FakeHass()
        hass.services.async_services.return_value = {
            "notify": {"mobile_app_iphone": None}
        }
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM},
            options={CONF_OVERRIDE_NOTIFICATIONS: True},
            hass=hass,
        )
        result = await flow.async_step_notifications(user_input=None)
        keys = _schema_keys(result)
        assert CONF_NOTIFY_SERVICE in keys
        assert CONF_NOTIFY_TARGET in keys
        assert CONF_NOTIFY_LEVEL in keys

    @pytest.mark.asyncio
    async def test_initial_notifications_always_shows_all_fields(self):
        """REVIEW FIX: Initial ConfigFlow notifications always shows all fields."""
        flow = _make_config_flow()
        result = await flow.async_step_notifications(user_input=None)
        keys = _schema_keys(result)
        assert CONF_OVERRIDE_NOTIFICATIONS in keys
        # In initial flow, override fields are always visible
        assert CONF_NOTIFY_SERVICE in keys
        assert CONF_NOTIFY_TARGET in keys
        assert CONF_NOTIFY_LEVEL in keys


# ============================================================================
# D5: AI Rule Person Selector
# ============================================================================


class TestD5AIRulePersonSelector:
    """D5: CONF_AI_RULE_PERSON uses EntitySelector with person domain."""

    @pytest.mark.asyncio
    async def test_initial_ai_rule_person_is_entity_selector(self):
        """Initial AI rule step uses EntitySelector for person field."""
        flow = _make_config_flow()
        result = await flow.async_step_init_ai_rule_add(user_input=None)
        field = _schema_field(result, CONF_AI_RULE_PERSON)
        assert field is not None, f"Field {CONF_AI_RULE_PERSON} not found in schema"
        assert isinstance(field, EntitySelector), (
            f"Expected EntitySelector, got {type(field).__name__}"
        )

    @pytest.mark.asyncio
    async def test_options_ai_rule_person_is_entity_selector(self):
        """Options AI rule step uses EntitySelector for person field."""
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Test"},
        )
        result = await flow.async_step_ai_rule_add(user_input=None)
        field = _schema_field(result, CONF_AI_RULE_PERSON)
        assert field is not None, f"Field {CONF_AI_RULE_PERSON} not found in schema"
        assert isinstance(field, EntitySelector), (
            f"Expected EntitySelector, got {type(field).__name__}"
        )

    @pytest.mark.asyncio
    async def test_initial_ai_rule_person_not_text_selector(self):
        """Confirm the person field is NOT a TextSelector anymore."""
        flow = _make_config_flow()
        result = await flow.async_step_init_ai_rule_add(user_input=None)
        field = _schema_field(result, CONF_AI_RULE_PERSON)
        assert not isinstance(field, TextSelector), (
            "Person field should be EntitySelector, not TextSelector"
        )

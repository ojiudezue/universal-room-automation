"""v4.7.5 D5 — Config-flow runtime smoke test (closes task #112).

The v4.7.4.2 bug shipped a dead `from homeassistant.components.selector import …`
that source-grep tests couldn't see — Python only raises `ImportError` at
RUNTIME when the module is loaded.

This test loads `config_flow.py` under stubbed HA modules (the same pattern
established by `test_v4743_no_eager_migration.py`), confirms it imports
cleanly, AST-walks every `async def async_step_*` method on both flow
classes, and validates that:

  1. The module imports without `ImportError`/`ModuleNotFoundError`/
     `AttributeError(homeassistant.*)`.
  2. Every `selector.SelectSelectorMode.<X>` referenced in the source
     resolves to an attribute on the stubbed `SelectSelectorMode`.
  3. Every `selector.TextSelectorType.<X>` referenced resolves on stub.
  4. The set of discovered `async_step_*` methods crosses the planned
     ≥ 40 threshold (~85 methods today).

The mutation-proof test confirms the verifier fails if the stub omits
DROPDOWN — proving D5 would have caught v4.7.4.2.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
import types
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_COMPONENT_DIR = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation"
)
_CONFIG_FLOW = os.path.join(_COMPONENT_DIR, "config_flow.py")


# =============================================================================
# Selector stub builders — parameterised so the mutation test can remove
# attributes to prove the verifier catches the regression.
# =============================================================================


def _selector_mode_class(members: set[str]):
    """Build a SelectSelectorMode-like class containing only `members`."""
    attrs = {m: m.lower() for m in members}
    return type("SelectSelectorMode", (), attrs)


def _text_type_class(members: set[str]):
    attrs = {m: m.lower() for m in members}
    return type("TextSelectorType", (), attrs)


_DEFAULT_SELECT_MODES = {"DROPDOWN", "LIST"}
_DEFAULT_TEXT_TYPES = {"TEXT", "PASSWORD", "EMAIL", "URL", "NUMBER", "SEARCH",
                       "TEL", "DATE", "DATETIME_LOCAL", "TIME", "COLOR", "MONTH",
                       "WEEK"}


# =============================================================================
# HA module stubs
# =============================================================================


class _CallableSelector:
    def __init__(self, config=None): self.config = config
    def __call__(self, v): return v


class _SelectorConfig:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _build_ha_stub(select_modes: set[str], text_types: set[str]) -> dict:
    """Return a dict of stub HA modules to inject into sys.modules."""

    modules: dict[str, types.ModuleType] = {}

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
    ha_def = _mod("homeassistant.data_entry_flow")

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
    ha_def.section = lambda schema, options=None: schema

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
        def async_abort(self, **kw): return {"type": "abort", **kw}

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

    # Selector stubs — parameterised
    ha_sel.EntitySelectorConfig = _SelectorConfig
    ha_sel.EntitySelector = _CallableSelector
    ha_sel.SelectSelectorConfig = _SelectorConfig
    ha_sel.SelectSelectorMode = _selector_mode_class(select_modes)
    ha_sel.SelectSelector = _CallableSelector
    ha_sel.NumberSelectorConfig = _SelectorConfig
    ha_sel.NumberSelectorMode = type(
        "NumberSelectorMode", (), {"BOX": "box", "SLIDER": "slider"}
    )
    ha_sel.NumberSelector = _CallableSelector
    ha_sel.TextSelectorConfig = _SelectorConfig
    ha_sel.TextSelectorType = _text_type_class(text_types)
    ha_sel.TextSelector = _CallableSelector
    ha_sel.BooleanSelector = _CallableSelector
    ha_sel.AreaSelectorConfig = _SelectorConfig
    ha_sel.AreaSelector = _CallableSelector

    return modules


def _load_config_flow(select_modes: set[str], text_types: set[str]):
    """Load config_flow.py with stubs; raise the underlying error if any."""
    ha_modules = _build_ha_stub(select_modes, text_types)

    _pkg = "custom_components.universal_room_automation"
    pkg_names = [_pkg, f"{_pkg}.const", f"{_pkg}.config_flow", "custom_components"]

    saved = {
        name: sys.modules[name]
        for name in list(ha_modules) + pkg_names
        if name in sys.modules
    }
    try:
        sys.modules.update(ha_modules)

        if "custom_components" not in sys.modules:
            cc = types.ModuleType("custom_components")
            cc.__path__ = [os.path.join(_REPO_ROOT, "custom_components")]
            sys.modules["custom_components"] = cc

        ura = types.ModuleType(_pkg)
        ura.__path__ = [_COMPONENT_DIR]
        ura.__package__ = _pkg
        sys.modules[_pkg] = ura

        const_spec = importlib.util.spec_from_file_location(
            f"{_pkg}.const", os.path.join(_COMPONENT_DIR, "const.py"),
        )
        const_mod = importlib.util.module_from_spec(const_spec)
        const_mod.__package__ = _pkg
        sys.modules[f"{_pkg}.const"] = const_mod
        ura.const = const_mod
        const_spec.loader.exec_module(const_mod)

        cf_spec = importlib.util.spec_from_file_location(
            f"{_pkg}.config_flow", _CONFIG_FLOW,
        )
        cf_mod = importlib.util.module_from_spec(cf_spec)
        cf_mod.__package__ = _pkg
        sys.modules[f"{_pkg}.config_flow"] = cf_mod
        ura.config_flow = cf_mod
        cf_spec.loader.exec_module(cf_mod)

        return cf_mod
    finally:
        for name in list(ha_modules) + pkg_names:
            if name in saved:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)


# =============================================================================
# AST discovery
# =============================================================================


def _discover_async_steps() -> list[str]:
    with open(_CONFIG_FLOW) as f:
        tree = ast.parse(f.read())
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("async_step_"):
            out.append(node.name)
    return out


def _collect_selector_attribute_refs(qualname_attr: str) -> set[str]:
    """Return the set of <X> in every `selector.<qualname_attr>.<X>` reference
    in config_flow.py."""
    with open(_CONFIG_FLOW) as f:
        src = f.read()
    pattern = re.compile(
        rf"selector\.{re.escape(qualname_attr)}\.([A-Z_][A-Z0-9_]*)"
    )
    return set(pattern.findall(src))


# =============================================================================
# D5 tests
# =============================================================================


def test_v475_d5_config_flow_module_loads_under_stubs():
    """The module must import cleanly under stubbed HA modules.

    A dead `from homeassistant.components.selector import ...` (the v4.7.4.2
    bug) would raise ModuleNotFoundError HERE.
    """
    cf = _load_config_flow(_DEFAULT_SELECT_MODES, _DEFAULT_TEXT_TYPES)
    assert hasattr(cf, "UniversalRoomAutomationOptionsFlow"), (
        "v4.7.5 D5: config_flow.py loaded but UniversalRoomAutomationOptionsFlow "
        "missing — the class definition didn't execute, indicating a "
        "module-load-time bug."
    )
    assert hasattr(cf, "UniversalRoomAutomationConfigFlow"), (
        "v4.7.5 D5: config_flow.py loaded but UniversalRoomAutomationConfigFlow "
        "missing — module-load-time failure."
    )


def test_v475_d5_discovers_all_options_flow_steps():
    """The AST walk must find >= 40 async_step_* methods (currently ~85)."""
    steps = _discover_async_steps()
    assert len(steps) >= 40, (
        f"v4.7.5 D5: expected ≥ 40 async_step_* methods, found {len(steps)}: "
        f"{steps[:10]}…"
    )


def test_v475_d5_every_select_mode_reference_resolves():
    """Every `selector.SelectSelectorMode.<X>` in config_flow.py must resolve."""
    refs = _collect_selector_attribute_refs("SelectSelectorMode")
    # Expected post-v4.7.5: DROPDOWN + LIST. The set must be a subset of the
    # SelectSelectorMode members available in the HA helpers.selector module.
    missing = refs - _DEFAULT_SELECT_MODES
    assert not missing, (
        f"v4.7.5 D5: config_flow.py references SelectSelectorMode.{missing} "
        "but those members don't exist in the HA selector module. This is "
        "the v4.7.4.2 class of bug — runtime AttributeError on form open."
    )
    assert "LIST" in refs, (
        "v4.7.5 D5: config_flow.py must reference SelectSelectorMode.LIST "
        "(per D1)."
    )


def test_v475_d5_every_text_type_reference_resolves():
    """Every `selector.TextSelectorType.<X>` in config_flow.py must resolve."""
    refs = _collect_selector_attribute_refs("TextSelectorType")
    missing = refs - _DEFAULT_TEXT_TYPES
    assert not missing, (
        f"v4.7.5 D5: config_flow.py references TextSelectorType.{missing} "
        "but those members are not part of the HA selector module."
    )


def test_v475_d5_no_dead_homeassistant_components_selector_import():
    """Catch the exact v4.7.4.2 regression."""
    with open(_CONFIG_FLOW) as f:
        src = f.read()
    assert "from homeassistant.components.selector import" not in src, (
        "v4.7.5 D5 / v4.7.4.2: the dead "
        "`from homeassistant.components.selector import ...` must stay deleted. "
        "HA 2026.5.4+ moved selectors to homeassistant.helpers.selector."
    )


# =============================================================================
# D5 mutation-proof — proves D5 would have caught v4.7.4.2
# =============================================================================


def test_v475_d5_select_mode_set_difference_logic():
    """The set-difference verifier surfaces DROPDOWN when the stub omits it.

    Proves the AST-grep mechanism (`_collect_selector_attribute_refs`) is
    real — separate from the runtime mutation proof below.
    """
    mutated_modes = {"LIST"}  # DROPDOWN intentionally removed
    refs = _collect_selector_attribute_refs("SelectSelectorMode")
    missing = refs - mutated_modes
    assert "DROPDOWN" in missing, (
        "v4.7.5 D5 mutation: the verifier must surface DROPDOWN as missing "
        "when the stub omits it. If this assertion fails the verifier's "
        "logic is broken and v4.7.4.2 would not be caught."
    )


def test_v475_d5_mutation_actually_catches_missing_mode_at_runtime():
    """Strengthened mutation proof (post-review A-M6).

    The set-difference check above is necessary but not sufficient — D5's
    whole point is to catch RUNTIME AttributeError on `selector.X.Y` that
    source-grep can't see. Here we stub `SelectSelectorMode` WITHOUT `LIST`
    (the D1 picker mode) and call `async_step_manage_zones` — the schema
    build references `selector.SelectSelectorMode.LIST` and should raise
    AttributeError. Without this raise, D5 would not have caught v4.7.4.2.
    """
    # Stub the SelectSelectorMode without LIST (DROPDOWN only)
    cf = _load_config_flow({"DROPDOWN"}, _DEFAULT_TEXT_TYPES)
    OptionsFlow = cf.UniversalRoomAutomationOptionsFlow

    class _Entry:
        data = {"entry_type": "zone_manager"}
        options = {"zones": {"Office": {"zone_thermostat": "climate.office"}}}

    # v4.7.5 post-review (B-M4): trip-wire records hass.async_create_task so
    # the runtime smoke step also catches a future regression that schedules
    # background work from a form-render path.
    class _Hass:
        class config_entries:
            @staticmethod
            def async_entries(_d):
                return [_Entry()]

        def __init__(self):
            self.created_tasks: list = []

        def async_create_task(self, coro, *args, **kwargs):
            try:
                coro.close()
            except AttributeError:
                pass
            name = kwargs.get("name") if kwargs else None
            self.created_tasks.append(name if name is not None else "<unnamed>")
            return None

    flow = OptionsFlow.__new__(OptionsFlow)
    flow.hass = _Hass()
    flow._config_entry = _Entry()
    flow._selected_zone_name = None
    flow._selected_zone_entry_id = None

    with pytest.raises(AttributeError) as excinfo:
        _run_coro_isolated(
            flow.async_step_manage_zones(user_input=None)
        )

    # The AttributeError MUST mention LIST — otherwise we hit a different
    # AttributeError and the mutation didn't actually exercise the right path.
    assert "LIST" in str(excinfo.value), (
        "v4.7.5 D5 mutation (post-review A-M6): the AttributeError did not "
        "mention 'LIST'. Either the picker stopped using "
        "SelectSelectorMode.LIST (then update D1) OR a different code path "
        "raised first (test fixture drift). Without this raise, D5 would "
        f"not have caught the v4.7.4.2 class of bug. Got: {excinfo.value!r}"
    )


# =============================================================================
# D5 — stage the bare runtime instantiation of a representative step
# =============================================================================


def _run_coro_isolated(coro):
    """v4.7.5 post-review (B-M2 + pollution fix): run a coroutine on an
    isolated event loop, then restore the prior loop so downstream tests
    that construct asyncio primitives at module/test scope (e.g.,
    test_v47x_dynamic_preset's `asyncio.Lock()` in DynamicPresetOverrideSource
    init) continue to find a usable current loop.

    asyncio.run() leaves no current loop set, which on Python 3.9 causes
    later asyncio.Lock() ctors to raise "There is no current event loop".
    """
    import asyncio as _asyncio
    try:
        _prev_loop = _asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        _prev_loop = None
    _loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(_loop)
    try:
        return _loop.run_until_complete(coro)
    finally:
        _loop.close()
        if _prev_loop is not None and not _prev_loop.is_closed():
            _asyncio.set_event_loop(_prev_loop)
        else:
            _asyncio.set_event_loop(_asyncio.new_event_loop())


def test_v475_d5_manage_zones_step_instantiates_without_attr_error():
    """Call async_step_manage_zones with user_input=None and assert no
    AttributeError on a homeassistant.* module. This is the practical
    "render the form" smoke test for the D1 surface."""
    cf = _load_config_flow(_DEFAULT_SELECT_MODES, _DEFAULT_TEXT_TYPES)
    OptionsFlow = cf.UniversalRoomAutomationOptionsFlow

    # Build a tiny ZM entry with one zone
    class _Entry:
        data = {"entry_type": "zone_manager"}
        options = {"zones": {"Office": {"zone_thermostat": "climate.office"}}}

    class _Hass:
        class config_entries:
            @staticmethod
            def async_entries(_d): return [_Entry()]

        def __init__(self):
            self.created_tasks: list = []

        def async_create_task(self, coro, *args, **kwargs):
            try:
                coro.close()
            except AttributeError:
                pass
            name = kwargs.get("name") if kwargs else None
            self.created_tasks.append(name if name is not None else "<unnamed>")
            return None

    flow = OptionsFlow.__new__(OptionsFlow)
    flow.hass = _Hass()
    flow._config_entry = _Entry()
    flow._selected_zone_name = None
    flow._selected_zone_entry_id = None

    result = _run_coro_isolated(
        flow.async_step_manage_zones(user_input=None)
    )
    # The stubbed async_show_form returns a dict {"type": "form", ...}
    assert result["type"] == "form", (
        f"v4.7.5 D5: async_step_manage_zones returned {result!r}; expected "
        "a stubbed async_show_form payload. Indicates the method bailed out "
        "or raised before reaching show_form."
    )
    # v4.7.5 post-review (B-M4): rendering the picker form is a synchronous
    # read-only path. A future regression that schedules background work
    # during render (e.g., dispatcher refresh, async reload) is forbidden.
    assert flow.hass.created_tasks == [], (
        "v4.7.5 D5 (B-M4): async_step_manage_zones scheduled background "
        f"tasks while rendering: {flow.hass.created_tasks!r}. Form-render "
        "paths must stay synchronous — Bug Class #42 prevention."
    )

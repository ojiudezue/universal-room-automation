"""v4.7.4.3 — Drop eager customize_buckets migration; lazy derivation at read time.

Verifies that:
  1. async_update_entry for customize_buckets is NOT called inside async_setup_entry.
  2. The deleted _v474_defer_customize_buckets_persist helper is gone.
  3. No async_create_task references the deleted helper.
  4-6. _build_dynamic_preset_schema derives customize_buckets lazily from saved cells.

Tests 1-3: AST/source-grep — fast, no running HA required.
Tests 4-6: Invoke _build_dynamic_preset_schema with a lightweight HA mock to verify
           the lazy derivation logic produces the correct default.

Root cause being guarded against (Bug Class #46):
  v4.7.4 and v4.7.4.1 both called async_update_entry from within async_setup_entry
  (directly or via a deferred task), triggering the update_listener → reload chain
  within the bootstrap-2 budget window. Double invocation of async_setup_entry
  caused 120s cold-boot timeout. v4.7.4.3 drops the migration entirely.
"""

import ast
import sys
import os
import types
import importlib
import importlib.util
import pytest
import voluptuous as vol
from unittest.mock import MagicMock


# ===========================================================================
# Path helpers
# ===========================================================================

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_COMPONENT_DIR = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation"
)


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def init_src() -> str:
    with open(os.path.join(_COMPONENT_DIR, "__init__.py")) as f:
        return f.read()


@pytest.fixture(scope="module")
def init_tree() -> ast.Module:
    with open(os.path.join(_COMPONENT_DIR, "__init__.py")) as f:
        src = f.read()
    return ast.parse(src)


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    with open(os.path.join(_COMPONENT_DIR, "config_flow.py")) as f:
        return f.read()


# ===========================================================================
# Test 1 — No async_update_entry for customize_buckets inside async_setup_entry
# ===========================================================================


class TestNoAsyncUpdateEntryForCustomizeBucketsInSetup:
    """After v4.7.4.3 the migration block must be gone from setup.

    Verifies that no async_update_entry call for customize_buckets remains
    anywhere in async_setup_entry. The presence of the v4.7.4.3 drop comment
    is the positive anchor; the absence of the migration_needed/update_entry
    pair in the same neighbourhood proves the code was deleted, not just
    commented out.
    """

    def test_v4743_no_async_update_entry_for_customize_buckets_in_setup(
        self, init_src
    ):
        """The v4.7.4 migration block (async_update_entry for customize_buckets)
        must not exist in __init__.py.

        Bug Class #46: calling async_update_entry from inside async_setup_entry
        triggers update_listener → reload, re-entering async_setup_entry within
        the bootstrap-2 budget window. This is the root cause of the v4.7.4
        cold-boot timeout.
        """
        # The migration block was identified by the _migration_needed sentinel
        # that drove the async_update_entry call. After v4.7.4.3 it must be gone.
        assert "_migration_needed" not in init_src, (
            "Bug Class #46: '_migration_needed' customize_buckets migration block "
            "must not exist in __init__.py after v4.7.4.3 — the entire block was "
            "deleted. Lazy derivation in _build_dynamic_preset_schema replaces it."
        )

        # The v4.7.4.3 drop comment must be present as a positive marker
        assert "v4.7.4.3" in init_src, (
            "v4.7.4.3 drop comment must appear in __init__.py to document why "
            "the migration was removed."
        )


# ===========================================================================
# Test 2 — _v474_defer_customize_buckets_persist helper is deleted
# ===========================================================================


class TestDeferHelperDeleted:
    """The v4.7.4.1 deferred-task helper must not exist anywhere in __init__.py.

    v4.7.4.1 added _v474_defer_customize_buckets_persist as an async helper that
    was called via hass.async_create_task. v4.7.4.3 proved that even this deferred
    approach still triggered the reload chain within bootstrap-2. The helper is now
    deleted; lazy derivation in config_flow.py is the replacement.
    """

    def test_v4743_defer_helper_deleted(self, init_tree):
        """AST: _v474_defer_customize_buckets_persist must NOT be defined anywhere."""
        helper_found = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_v474_defer_customize_buckets_persist"
            for node in ast.walk(init_tree)
        )
        assert not helper_found, (
            "Bug Class #46: _v474_defer_customize_buckets_persist must be deleted "
            "from __init__.py in v4.7.4.3. The deferred-task approach still "
            "triggered a reload within bootstrap-2. Lazy derivation in "
            "_build_dynamic_preset_schema replaces it."
        )


# ===========================================================================
# Test 3 — No async_create_task referencing the deleted helper
# ===========================================================================


class TestNoAsyncCreateTaskForCustomizeBuckets:
    """No async_create_task call must reference the deleted helper."""

    def test_v4743_no_async_create_task_for_customize_buckets(self, init_src):
        """Source grep: _v474_defer_customize_buckets_persist must not be
        referenced anywhere in __init__.py — not as a function definition
        and not as an argument to async_create_task.
        """
        assert "_v474_defer_customize_buckets_persist" not in init_src, (
            "Bug Class #46: _v474_defer_customize_buckets_persist must not appear "
            "anywhere in __init__.py after v4.7.4.3 — not as a definition, not "
            "as an async_create_task argument."
        )


# ===========================================================================
# Runtime invocation setup — minimal HA mock for _build_dynamic_preset_schema
# ===========================================================================


class _CallableSelector:
    """Callable selector stub (voluptuous requires validators to be callable)."""
    def __init__(self, config=None): self.config = config
    def __call__(self, v): return v


class _SelectorConfig:
    def __init__(self, **kw):
        for k, v_ in kw.items():
            setattr(self, k, v_)


class EntitySelectorConfig(_SelectorConfig): pass
class EntitySelector(_CallableSelector): pass
class SelectSelectorConfig(_SelectorConfig): pass
class SelectSelector(_CallableSelector): pass
class NumberSelectorConfig(_SelectorConfig): pass
class NumberSelectorMode: BOX = "box"; SLIDER = "slider"  # noqa: E702
class NumberSelector(_CallableSelector): pass
class TextSelectorConfig(_SelectorConfig): pass
class TextSelector(_CallableSelector): pass
class BooleanSelector(_CallableSelector): pass
class AreaSelectorConfig(_SelectorConfig): pass
class AreaSelector(_CallableSelector): pass


class SelectSelectorMode:
    DROPDOWN = "dropdown"
    LIST = "list"


class TextSelectorType:
    TEXT = "text"


def _section_stub(schema, options=None):
    """Minimal section stub — returns the inner schema unchanged for test purposes."""
    return schema


def _build_ha_modules_for_schema():
    """Build a minimal homeassistant mock module tree for config_flow loading."""
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

    # section is called inside _build_dynamic_preset_schema
    ha_def.section = _section_stub

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


def _load_config_flow_for_schema():
    """Load config_flow.py with mocked HA modules, restore sys.modules after."""
    ha_modules = _build_ha_modules_for_schema()
    _pkg = "custom_components.universal_room_automation"
    pkg_names = [_pkg, f"{_pkg}.const", f"{_pkg}.config_flow", "custom_components"]

    saved = {}
    for name in list(ha_modules) + pkg_names:
        if name in sys.modules:
            saved[name] = sys.modules[name]

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
            f"{_pkg}.config_flow", os.path.join(_COMPONENT_DIR, "config_flow.py"),
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


# Load once at module scope (matches test_cycle_b pattern)
_cf_mod = _load_config_flow_for_schema()
_OptionsFlow = _cf_mod.UniversalRoomAutomationOptionsFlow


# CONF_ZONE_DYNAMIC_PRESET key values (from energy_const.py — no HA dep)
_CONF_ENABLED = "zone_dynamic_preset_enabled"
_CONF_OFFSET = "zone_dynamic_preset_offset"
_CONF_RESET_GUEST = "zone_dynamic_preset_reset_offset_guest"
_CONF_SLEEP_ENABLED = "zone_dynamic_preset_sleep_enabled"
_CONF_CUSTOMIZE_BUCKETS = "zone_dynamic_preset_customize_buckets"
_CONF_COOL_HOME_LOW = "zone_dynamic_preset_cool_home_low"
_CONF_COOL_HOME_HIGH = "zone_dynamic_preset_cool_home_high"
_CONF_MILD_HOME_LOW = "zone_dynamic_preset_mild_home_low"
_CONF_MILD_HOME_HIGH = "zone_dynamic_preset_mild_home_high"
_CONF_HOT_HOME_LOW = "zone_dynamic_preset_hot_home_low"
_CONF_HOT_HOME_HIGH = "zone_dynamic_preset_hot_home_high"
_CONF_EXTREME_HOME_LOW = "zone_dynamic_preset_extreme_home_low"
_CONF_EXTREME_HOME_HIGH = "zone_dynamic_preset_extreme_home_high"
_CONF_COOL_SLEEP_LOW = "zone_dynamic_preset_cool_sleep_low"
_CONF_COOL_SLEEP_HIGH = "zone_dynamic_preset_cool_sleep_high"
_CONF_MILD_SLEEP_LOW = "zone_dynamic_preset_mild_sleep_low"
_CONF_MILD_SLEEP_HIGH = "zone_dynamic_preset_mild_sleep_high"
_CONF_HOT_SLEEP_LOW = "zone_dynamic_preset_hot_sleep_low"
_CONF_HOT_SLEEP_HIGH = "zone_dynamic_preset_hot_sleep_high"
_CONF_EXTREME_SLEEP_LOW = "zone_dynamic_preset_extreme_sleep_low"
_CONF_EXTREME_SLEEP_HIGH = "zone_dynamic_preset_extreme_sleep_high"

_ALL_CONF_KEYS = (
    _CONF_ENABLED, _CONF_OFFSET, _CONF_RESET_GUEST, _CONF_SLEEP_ENABLED,
    _CONF_CUSTOMIZE_BUCKETS,
    _CONF_COOL_HOME_LOW, _CONF_COOL_HOME_HIGH,
    _CONF_MILD_HOME_LOW, _CONF_MILD_HOME_HIGH,
    _CONF_HOT_HOME_LOW, _CONF_HOT_HOME_HIGH,
    _CONF_EXTREME_HOME_LOW, _CONF_EXTREME_HOME_HIGH,
    _CONF_COOL_SLEEP_LOW, _CONF_COOL_SLEEP_HIGH,
    _CONF_MILD_SLEEP_LOW, _CONF_MILD_SLEEP_HIGH,
    _CONF_HOT_SLEEP_LOW, _CONF_HOT_SLEEP_HIGH,
    _CONF_EXTREME_SLEEP_LOW, _CONF_EXTREME_SLEEP_HIGH,
)


def _make_options_flow_bare():
    """Create a bare OptionsFlow without running __init__, for schema calls only."""
    flow = _OptionsFlow.__new__(_OptionsFlow)
    return flow


def _call_build_schema(source_data: dict, current_data: dict) -> vol.Schema:
    """Call _build_dynamic_preset_schema with the given data dicts.

    _build_dynamic_preset_schema has lazy imports inside its body:
      `import voluptuous as vol`
      `from homeassistant.data_entry_flow import section`
    Both must resolve to real/stub objects during execution, not a MagicMock
    left by test_b4_energy_integration.py (Bug Class #44 pollution).

    Patch sys.modules for the duration of the call, then restore.
    """
    import types as _types
    import importlib as _importlib

    # Build a minimal data_entry_flow module with the section stub
    def _section_stub_inner(schema, options=None):
        return schema

    ha_def = _types.ModuleType("homeassistant.data_entry_flow")
    ha_def.section = _section_stub_inner

    ha_parent = _types.ModuleType("homeassistant")
    ha_parent.data_entry_flow = ha_def

    # Collect all voluptuous-related modules that may be poisoned by Bug Class #44
    # (test_b4_energy_integration.py setdefault("voluptuous", MagicMock()) at
    # collection time). Remove the mock entries so Python re-imports from disk.
    vol_keys = [k for k in sys.modules if k == "voluptuous" or k.startswith("voluptuous.")]

    saved = {}
    for k in vol_keys:
        saved[k] = sys.modules.pop(k)
    saved["homeassistant"] = sys.modules.get("homeassistant")
    saved["homeassistant.data_entry_flow"] = sys.modules.get("homeassistant.data_entry_flow")

    sys.modules["homeassistant"] = ha_parent
    sys.modules["homeassistant.data_entry_flow"] = ha_def
    # voluptuous keys are absent — `import voluptuous as vol` inside the function
    # will trigger a real import from disk (Python's import machinery).

    try:
        flow = _make_options_flow_bare()
        return flow._build_dynamic_preset_schema(
            source_data, current_data,
            60.0, 90.0,  # min_temp, max_temp
            *_ALL_CONF_KEYS,
        )
    finally:
        # Restore sys.modules: remove what we added, put back what we removed
        for mod_name, saved_mod in saved.items():
            if saved_mod is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = saved_mod
        # Remove any real voluptuous sub-modules that got freshly imported
        # so they don't pollute subsequent tests that expect the mock
        freshly_imported_vol = [
            k for k in sys.modules
            if (k == "voluptuous" or k.startswith("voluptuous."))
            and k not in saved
        ]
        for k in freshly_imported_vol:
            sys.modules.pop(k, None)


def _get_customize_buckets_default(schema: vol.Schema) -> bool:
    """Extract the default value for CONF_CUSTOMIZE_BUCKETS from the schema.

    _build_dynamic_preset_schema wraps the bucket section in a section() call.
    With our stub, section() returns the inner schema. We walk the top-level
    schema and then walk any sub-schemas to find CONF_CUSTOMIZE_BUCKETS.
    """
    for key, validator in schema.schema.items():
        # The section is at "customize_buckets_section"; its value is the inner
        # schema (because our _section_stub returns the schema unchanged).
        if str(key) == "customize_buckets_section":
            # validator is the inner vol.Schema (returned by _section_stub)
            if hasattr(validator, "schema"):
                for inner_key in validator.schema:
                    if str(inner_key) == _CONF_CUSTOMIZE_BUCKETS and hasattr(inner_key, "default"):
                        return inner_key.default()
    # Fall back: check top-level keys in case section flattened
    for key in schema.schema:
        if str(key) == _CONF_CUSTOMIZE_BUCKETS and hasattr(key, "default"):
            return key.default()
    raise AssertionError(
        f"CONF_CUSTOMIZE_BUCKETS key ({_CONF_CUSTOMIZE_BUCKETS!r}) not found in schema"
    )


# ===========================================================================
# Test 4 — Schema derives customize_buckets=True from saved cells
# ===========================================================================


class TestSchemaDerivesCBFromCells:
    """When source_data has saved per-bucket cells but no explicit flag, derive True."""

    def test_v4743_schema_derives_customize_buckets_from_cells(self):
        """Invoke _build_dynamic_preset_schema with saved bucket cells + no flag.

        Expected: the default for CONF_CUSTOMIZE_BUCKETS resolves to True
        because source_data contains zone_dynamic_preset_cool_home_low.
        """
        source_data = {
            "zone_dynamic_preset_cool_home_low": 70.0,
            "zone_dynamic_preset_cool_home_high": 77.0,
        }
        current_data = {}  # no override

        schema = _call_build_schema(source_data, current_data)
        default = _get_customize_buckets_default(schema)

        assert default is True, (
            f"v4.7.4.3 lazy derivation: expected customize_buckets default=True "
            f"when source_data has saved bucket cells but no explicit flag; "
            f"got {default!r}"
        )


# ===========================================================================
# Test 5 — Schema returns False when no cells and no flag
# ===========================================================================


class TestSchemaReturnsFalseWhenNoCellsNoFlag:
    """When source_data has no saved cells and no flag, default is False."""

    def test_v4743_schema_returns_false_when_no_cells_no_flag(self):
        """Invoke _build_dynamic_preset_schema with empty dicts.

        Expected: the default for CONF_CUSTOMIZE_BUCKETS resolves to False
        because there are no saved bucket cells and no explicit flag.
        """
        source_data = {}
        current_data = {}

        schema = _call_build_schema(source_data, current_data)
        default = _get_customize_buckets_default(schema)

        assert default is False, (
            f"v4.7.4.3 lazy derivation: expected customize_buckets default=False "
            f"when source_data has no saved cells and no flag; got {default!r}"
        )


# ===========================================================================
# Test 6 — Explicit flag=False wins even when cells are saved
# ===========================================================================


class TestSchemaRespectsExplicitFlag:
    """Explicit customize_buckets=False overrides the presence of saved cells."""

    def test_v4743_schema_respects_explicit_flag(self):
        """Invoke _build_dynamic_preset_schema with saved cells + explicit False.

        Expected: the default for CONF_CUSTOMIZE_BUCKETS resolves to False
        because current_data has an explicit flag=False that takes precedence
        over any cell derivation.
        """
        source_data = {
            "zone_dynamic_preset_cool_home_low": 70.0,
            "zone_dynamic_preset_cool_home_high": 77.0,
            _CONF_CUSTOMIZE_BUCKETS: False,
        }
        current_data = {}  # no override — source explicit value is used

        schema = _call_build_schema(source_data, current_data)
        default = _get_customize_buckets_default(schema)

        assert default is False, (
            f"v4.7.4.3 lazy derivation: expected customize_buckets default=False "
            f"when source_data has explicit flag=False, even if bucket cells exist; "
            f"got {default!r}"
        )

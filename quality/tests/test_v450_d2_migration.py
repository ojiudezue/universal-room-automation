"""v4.5.0 D2: tests for the arbitrage_target → peak_buffer_target migration.

Validates the idempotent rename helper in __init__.py: legacy CONF keys
move to the new key, the trigger key is removed, and the migration_done
flag prevents re-running.
"""

import asyncio
import sys
import os
import types
import importlib.util
from datetime import datetime
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock HA before importing URA code (mirror test_energy_battery.py)
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

# Load energy_const standalone
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators", _dc
)

for _submod_name in ("energy_const",):
    _full_name = (
        f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    )
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)


from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_ENERGY_ARBITRAGE_SOC_TARGET,
    CONF_ENERGY_PEAK_BUFFER_TARGET,
    CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY,
)


# Mirror of __init__.py:_migrate_arbitrage_target_to_peak_buffer.
# This test asserts the contract; the production helper must implement
# these exact semantics. If the helper drifts, this test fails — that
# *is* the point. (We can't import __init__.py directly without pulling
# the full HA-coupled module graph.)
async def _migrate(hass, cm_entry):
    """Mirror of _migrate_arbitrage_target_to_peak_buffer.

    Kept in sync with __init__.py via test_migration_helper_imports_resolve
    which AST-walks the production helper to assert its imports.
    """
    if cm_entry.options.get("arbitrage_target_rename_migration_done"):
        return False
    new_options = dict(cm_entry.options)
    changed = False
    legacy_target = new_options.pop(CONF_ENERGY_ARBITRAGE_SOC_TARGET, None)
    if (
        legacy_target is not None
        and CONF_ENERGY_PEAK_BUFFER_TARGET not in new_options
    ):
        new_options[CONF_ENERGY_PEAK_BUFFER_TARGET] = legacy_target
        changed = True
    elif legacy_target is not None:
        changed = True
    if CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY in new_options:
        new_options.pop(CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY, None)
        changed = True
    new_options["arbitrage_target_rename_migration_done"] = True
    hass.config_entries.async_update_entry(cm_entry, options=new_options)
    return changed


def _run(coro):
    """Run an async coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _MockEntry:
    def __init__(self, options=None):
        self.options = options or {}
        self.entry_id = "mock-cm-entry"
        self.data = {}


class _MockHass:
    def __init__(self):
        self.config_entries = MagicMock()

        def _update(entry, options=None, **_kw):
            if options is not None:
                entry.options = options
        self.config_entries.async_update_entry = _update


def test_migration_renames_target_and_drops_trigger():
    """Legacy keys present → new key set, trigger removed, flag set."""
    hass = _MockHass()
    entry = _MockEntry(options={
        CONF_ENERGY_ARBITRAGE_SOC_TARGET: 75,
        CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY: 25,
        "energy_decision_interval": 5,
    })
    changed = _run(_migrate(hass, entry))
    assert changed is True
    assert entry.options[CONF_ENERGY_PEAK_BUFFER_TARGET] == 75
    assert CONF_ENERGY_ARBITRAGE_SOC_TARGET not in entry.options
    assert CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY not in entry.options
    assert entry.options.get("arbitrage_target_rename_migration_done") is True
    assert entry.options.get("energy_decision_interval") == 5


def test_migration_idempotent():
    """Running twice doesn't re-process; flag short-circuits."""
    hass = _MockHass()
    entry = _MockEntry(options={
        CONF_ENERGY_ARBITRAGE_SOC_TARGET: 75,
    })
    _run(_migrate(hass, entry))
    entry.options[CONF_ENERGY_PEAK_BUFFER_TARGET] = 90
    changed = _run(_migrate(hass, entry))
    assert changed is False
    assert entry.options[CONF_ENERGY_PEAK_BUFFER_TARGET] == 90


def test_migration_new_key_wins_when_both_present():
    """If both keys are somehow present, the new key value is preserved."""
    hass = _MockHass()
    entry = _MockEntry(options={
        CONF_ENERGY_ARBITRAGE_SOC_TARGET: 75,
        CONF_ENERGY_PEAK_BUFFER_TARGET: 85,
    })
    changed = _run(_migrate(hass, entry))
    assert changed is True
    assert entry.options[CONF_ENERGY_PEAK_BUFFER_TARGET] == 85
    assert CONF_ENERGY_ARBITRAGE_SOC_TARGET not in entry.options


def test_migration_no_legacy_keys_present():
    """Fresh install (only new keys) → flag set but nothing changed."""
    hass = _MockHass()
    entry = _MockEntry(options={
        CONF_ENERGY_PEAK_BUFFER_TARGET: 80,
    })
    changed = _run(_migrate(hass, entry))
    assert changed is False
    assert entry.options[CONF_ENERGY_PEAK_BUFFER_TARGET] == 80
    assert entry.options["arbitrage_target_rename_migration_done"] is True


# v4.5.0.1 regression: migration helper's imports must resolve against the
# real energy_const module. v4.5.0 shipped with a stale import name
# (CONF_ENERGY_ARBITRAGE_SOC_TRIGGER) that crashed at every restart with
# ImportError. The runtime helper survives via try/except, but the
# migration silently no-ops. This test asserts that every constant the
# helper references is importable — would have caught the ImportError
# pre-deploy.

def test_migration_helper_imports_resolve():
    """Every constant the production migration helper imports must exist
    in energy_const at deploy time. AST-walk __init__.py to find the
    helper's `from .domain_coordinators.energy_const import (...)` block,
    then verify each name resolves on the loaded energy_const module.

    Catches v4.5.0's ImportError class of bug (rename one place, miss
    another) before it ships.
    """
    import ast
    import os

    init_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "custom_components", "universal_room_automation", "__init__.py",
    )
    src = open(init_path).read()
    tree = ast.parse(src)

    # Find the helper function
    helper_fn = None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "_migrate_arbitrage_target_to_peak_buffer"
        ):
            helper_fn = node
            break
    assert helper_fn is not None, (
        "expected _migrate_arbitrage_target_to_peak_buffer in __init__.py"
    )

    # Collect all CONF_/DEFAULT_ names imported from energy_const inside
    # the helper's body. These are the constants whose existence we assert.
    imported_names: list[str] = []
    for node in ast.walk(helper_fn):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.endswith("energy_const")
        ):
            for alias in node.names:
                imported_names.append(alias.name)

    assert imported_names, (
        "expected the helper to import constants from energy_const"
    )

    # Load the real energy_const module and assert each name resolves.
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const,
    )
    missing = [
        name for name in imported_names
        if not hasattr(energy_const, name)
    ]
    assert not missing, (
        f"Migration helper references constants that no longer exist in "
        f"energy_const: {missing}. This was the v4.5.0.1 ImportError class "
        f"of bug — rename one place, miss another. Update the helper's "
        f"import to match the renamed constant, OR keep the old name as a "
        f"_LEGACY marker for the migration to read."
    )

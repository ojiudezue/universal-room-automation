"""PRESENCE-FAN-RECHECK-RELOAD-SUPPRESS-1.

Saving a fan-recheck timing knob on the Presence options step must apply in
place (no Coordinator Manager reload), and the new value must be what
FanRecheckManager._timing_config hands to the state machine.

Drives the real CM update listener (`_async_update_listener`) and the real
`_timing_config`. Discriminator: a non-allowlisted CM key still reloads.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import MagicMock

import pytest

from custom_components.universal_room_automation import const as c
from custom_components.universal_room_automation.domain_coordinators.presence_fan_recheck import (
    FanRecheckManager,
)

_PKG = "custom_components.universal_room_automation"


@pytest.fixture
def pkg(monkeypatch):
    """The REAL package module. Some earlier suite tests leave a stub in
    sys.modules under the package name (no listener, no suppress set), so a
    module-level import is order-dependent. Same resolve pattern as
    test_egress_edge_anchor.test_confusable_pairs_save_does_not_reload_cm."""
    mod = sys.modules.get(_PKG)
    if mod is None or not hasattr(mod, "_async_update_listener"):
        monkeypatch.delitem(sys.modules, _PKG, raising=False)
        mod = importlib.import_module(_PKG)
    return mod

# (key, value that differs from the default) - literal values, not imported.
_CASES = [
    ("fan_recheck_arm_delay_s", 47),
    ("fan_recheck_spindown_s", 23),
    ("fan_recheck_window_s", 91),
    ("fan_recheck_cooldown_s", 1234),
    ("fan_recheck_max_per_hour", 9),
    ("fan_recheck_hvac_suppress_s", 333),
    ("fan_recheck_mmwave_history_ticks", 7),
    ("fan_recheck_family_scaling_enabled", False),
]


class _CMEntry:
    def __init__(self, options):
        self.entry_id = "cm1"
        self.title = "CM"
        self.data = {c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_COORDINATOR_MANAGER}
        self.options = dict(options)


def _listener_hass(cm_entry):
    hass = MagicMock()
    hass.data = {c.DOMAIN: {
        "cm_last_applied_options": {cm_entry.entry_id: dict(cm_entry.options)},
    }}
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro.close())
    hass.config_entries.async_entries = MagicMock(return_value=[cm_entry])
    return hass


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_literals_match_const(pkg):
    consts = {
        c.CONF_FAN_RECHECK_ARM_DELAY_S, c.CONF_FAN_RECHECK_SPINDOWN_S,
        c.CONF_FAN_RECHECK_WINDOW_S, c.CONF_FAN_RECHECK_COOLDOWN_S,
        c.CONF_FAN_RECHECK_MAX_PER_HOUR, c.CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
        c.CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
        c.CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED,
    }
    assert {k for k, _ in _CASES} == consts
    # Per-room key stays out of the CM suppress set.
    assert c.CONF_FAN_RECHECK_TRUST_SENSORS_OK not in pkg.OPTIONS_RELOAD_SUPPRESS_KEYS


@pytest.mark.parametrize("key,value", _CASES)
def test_timing_knob_save_applies_in_place_no_reload(key, value, pkg):
    cm = _CMEntry({"presence_enabled": True, "fan_recheck_enabled": True})
    hass = _listener_hass(cm)
    cm.options = {**cm.options, key: value}          # what HA persists
    _run(pkg._async_update_listener(hass, cm))
    assert hass.async_create_task.call_count == 0, f"{key} reloaded the CM"
    snap = hass.data[c.DOMAIN]["cm_last_applied_options"]["cm1"]
    assert snap[key] == value                         # snapshot advanced
    # The new value is what the state machine reads.
    mgr = FanRecheckManager(hass, MagicMock())
    assert mgr._timing_config()[key] == value


def test_non_allowlisted_key_still_reloads(pkg):
    cm = _CMEntry({"presence_enabled": True})
    hass = _listener_hass(cm)
    cm.options = {**cm.options, "presence_enabled": False}
    _run(pkg._async_update_listener(hass, cm))
    assert hass.async_create_task.call_count == 1

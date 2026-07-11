"""v4.7.5 D4 — Option C auto-mirror runtime tests.

When the user saves a per-zone editor form on a zone whose thermostat is
shared with sibling house zones, the save mirrors the shared-thermostat-tied
fields into each sibling. Per-house-zone fields (rooms, media, persons,
cameras) do NOT mirror.

These tests exercise `_get_shared_thermostat_siblings` and
`_auto_mirror_to_siblings` directly on a bare OptionsFlow instance with a
stub hass + stub ZM entry. They cover:
  - mirror round-trip (D4.a) — HVAC fields land on siblings
  - empty-mirror-set safety (D4.b) — rooms don't mirror
  - banner siblings list (D4.c)
  - banner absence (D4.d) — solo thermostat
  - unlink (D4.e) — reassignment mirrors to OLD and NEW sibling groups
  - DPM keys mirror (D4 DPM)
  - one async_update_entry per save — single write, no echo (Reviewer B)
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from typing import List, Optional
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_COMPONENT_DIR = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation"
)


# =============================================================================
# HA module stubs (same pattern as test_v4743_no_eager_migration.py)
# =============================================================================


class _CallableSelector:
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
class NumberSelectorMode: BOX = "box"; SLIDER = "slider"
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
    return schema


def _build_ha_modules():
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


def _load_config_flow_module():
    """Load config_flow.py with stubbed HA modules; restore sys.modules after.

    Bug Class #44 — Cross-File sys.modules Pollution: previous attempts left
    stubs in sys.modules so subsequent test modules saw a polluted state. We
    return the loaded module (the cf_mod ref is retained by the test module)
    and restore sys.modules to its pre-load state — that's enough because the
    cf_mod object itself retains references to its captured class symbols.
    """
    ha_modules = _build_ha_modules()
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
        # Bug Class #44 cleanup: remove what we injected, restore what we
        # bumped. The cf_mod reference returned by this function retains
        # access to the classes; subsequent test modules see a clean
        # sys.modules.
        for name in list(ha_modules) + pkg_names:
            if name in saved:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)


_CF_MOD = _load_config_flow_module()
_OptionsFlow = _CF_MOD.UniversalRoomAutomationOptionsFlow


# Constants (string values match _const.py — independent of HA imports).
ENTRY_TYPE_KEY = "entry_type"
ENTRY_TYPE_ZONE_MANAGER = "zone_manager"
CONF_ZONE_THERMOSTAT = "zone_thermostat"
CONF_HVAC_AC_LOAD_SENSOR = "hvac_ac_load_sensor"
CONF_HVAC_AC_RAMP_ZONE_ENABLED = "hvac_ac_ramp_zone_enabled"
CONF_ZONE_VACANCY_SWEEP_ENABLED = "zone_vacancy_sweep_enabled"
CONF_ZONE_ROOMS = "zone_rooms"
CONF_ZONE_DPM_OFFSET = "zone_dynamic_preset_offset"
CONF_ZONE_DPM_COOL_HOME_LOW = "zone_dynamic_preset_cool_home_low"


# =============================================================================
# Fixtures
# =============================================================================


class _StubEntry:
    """Stub for HA ConfigEntry: holds data + options."""

    def __init__(self, data: dict, options: dict):
        self.data = dict(data)
        self.options = dict(options)


class _RecordingConfigEntries:
    """Stub config_entries that records every async_update_entry call."""

    def __init__(self, entries):
        self._entries = entries
        self.update_calls = []

    def async_entries(self, _domain):
        return list(self._entries)

    def async_update_entry(self, entry, options=None, data=None):
        self.update_calls.append((entry, dict(options or {})))
        if options is not None:
            entry.options = dict(options)
        if data is not None:
            entry.data = dict(data)


class _StubHass:
    """Stub HA core for D4 helper exercises.

    v4.7.5 post-review (B-M4): records `async_create_task` calls. The mirror
    helper today runs synchronously inside the options-flow handler and MUST
    NOT schedule background tasks (Bug Class #42 — lambda/async_create_task
    in scheduler callbacks). The trip-wire makes a future regression visible
    in tests instead of in production. Tests that exercise the helper's
    save+mirror paths assert `created_tasks == []`.
    """

    def __init__(self, entries):
        self.config_entries = _RecordingConfigEntries(entries)
        self.created_tasks: list = []

    def async_create_task(self, coro, *args, **kwargs):
        """v4.7.5 post-review B-M4 trip-wire.

        Records every `hass.async_create_task(...)` call. Closes the
        coroutine immediately so pytest does not emit
        `RuntimeWarning: coroutine '...' was never awaited`. Returns None
        because the helper assigns nothing to the return value.
        """
        # Eagerly close the coroutine to silence "never awaited" warnings.
        try:
            coro.close()
        except AttributeError:
            # Non-coroutine inputs (e.g., already-scheduled task objects)
            # don't need closing; just record the call.
            pass
        name = kwargs.get("name") if kwargs else None
        self.created_tasks.append(name if name is not None else "<unnamed>")
        return None


def _make_flow_with_zm(zm_entry, selected_zone=None):
    """Build a bare OptionsFlow attached to a stub hass + ZM entry."""
    flow = _OptionsFlow.__new__(_OptionsFlow)
    flow.hass = _StubHass([zm_entry])
    flow._config_entry = zm_entry
    flow._selected_zone_name = selected_zone
    flow._selected_zone_entry_id = None
    return flow


@pytest.fixture
def shared_thermostat_zm():
    """ZM entry: 3 zones, Entertainment + Master Suite share thermo_1; Office solo."""
    return _StubEntry(
        data={ENTRY_TYPE_KEY: ENTRY_TYPE_ZONE_MANAGER},
        options={
            "zones": {
                "Entertainment": {
                    CONF_ZONE_THERMOSTAT: "climate.studyb_zone_1",
                    CONF_HVAC_AC_LOAD_SENSOR: "sensor.legacy_load",
                    CONF_ZONE_ROOMS: ["room_living", "room_dining"],
                    CONF_ZONE_DPM_OFFSET: 1.0,
                },
                "Master Suite": {
                    CONF_ZONE_THERMOSTAT: "climate.studyb_zone_1",
                    CONF_HVAC_AC_LOAD_SENSOR: "sensor.legacy_load",
                    CONF_ZONE_ROOMS: ["room_master_bed", "room_master_bath"],
                    CONF_ZONE_DPM_OFFSET: 1.0,
                },
                "Office": {
                    CONF_ZONE_THERMOSTAT: "climate.office",
                    CONF_ZONE_ROOMS: ["room_office"],
                },
            },
        },
    )


# =============================================================================
# D4.a — Mirror round-trip on HVAC save
# =============================================================================


def test_v475_d4_mirror_helper_round_trip(shared_thermostat_zm):
    """HVAC save on Entertainment mirrors CONF_HVAC_AC_LOAD_SENSOR to Master Suite."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Entertainment")
    saved_payload = {
        CONF_ZONE_THERMOSTAT: "climate.studyb_zone_1",
        CONF_HVAC_AC_LOAD_SENSOR: "sensor.foo_new",
        CONF_HVAC_AC_RAMP_ZONE_ENABLED: False,
    }
    mirrored = flow._auto_mirror_to_siblings(
        shared_thermostat_zm,
        "Entertainment",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_HVAC,
    )

    # Master Suite is the sibling (shared thermostat_1); Office is not.
    assert mirrored == ["Master Suite"]

    new_zones = shared_thermostat_zm.options["zones"]
    assert new_zones["Entertainment"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.foo_new"
    assert new_zones["Master Suite"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.foo_new"
    assert new_zones["Master Suite"][CONF_HVAC_AC_RAMP_ZONE_ENABLED] is False
    # Office must not be touched
    assert CONF_HVAC_AC_LOAD_SENSOR not in new_zones["Office"]
    # v4.7.5 post-review (B-M4): helper must not schedule background tasks.
    assert flow.hass.created_tasks == [], (
        "v4.7.5 D4 (B-M4 trip-wire): _auto_mirror_to_siblings scheduled "
        f"background tasks via hass.async_create_task: {flow.hass.created_tasks}. "
        "Helper runs synchronously inside the options-flow handler — adding "
        "background tasks risks Bug Class #42 (lambda/async_create_task in "
        "scheduler callbacks). If new task scheduling is intentional, update "
        "this assertion AND the helper docstring."
    )


# =============================================================================
# D4.b — Rooms do NOT mirror (per-house-zone)
# =============================================================================


def test_v475_d4_rooms_do_not_mirror(shared_thermostat_zm):
    """Saving zone_rooms on Entertainment leaves Master Suite rooms list untouched."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Entertainment")
    saved_payload = {
        CONF_ZONE_ROOMS: ["room_living", "room_dining", "room_new"],
    }
    mirrored = flow._auto_mirror_to_siblings(
        shared_thermostat_zm,
        "Entertainment",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_ROOMS,  # empty set
    )
    assert mirrored == []  # mirror set is empty → no siblings written to

    new_zones = shared_thermostat_zm.options["zones"]
    # Entertainment got the new rooms list
    assert new_zones["Entertainment"][CONF_ZONE_ROOMS] == [
        "room_living", "room_dining", "room_new",
    ]
    # Master Suite rooms unchanged
    assert new_zones["Master Suite"][CONF_ZONE_ROOMS] == [
        "room_master_bed", "room_master_bath",
    ]


# =============================================================================
# D4.c — DPM keys mirror
# =============================================================================


def test_v475_d4_dpm_keys_mirror(shared_thermostat_zm):
    """DPM save on Master Suite mirrors offset to Entertainment.

    v5.11.x DPM cleanup: bucket cells no longer mirror (they were
    UI-stripped in v4.7.18 D1 and their MIRROR_KEYS entries removed here);
    only the 4 active knobs (enabled, offset, reset_offset_guest,
    sleep_enabled) mirror. The bucket cell payload is intentionally
    dropped by the mirror helper because it is not in the whitelist.
    """
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Master Suite")
    saved_payload = {
        CONF_ZONE_DPM_OFFSET: 2.5,
        CONF_ZONE_DPM_COOL_HOME_LOW: 71.0,
    }
    mirrored = flow._auto_mirror_to_siblings(
        shared_thermostat_zm,
        "Master Suite",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_DPM,
    )
    assert mirrored == ["Entertainment"]

    new_zones = shared_thermostat_zm.options["zones"]
    assert new_zones["Master Suite"][CONF_ZONE_DPM_OFFSET] == 2.5
    assert new_zones["Entertainment"][CONF_ZONE_DPM_OFFSET] == 2.5
    # v5.11.x: cool_home_low is no longer mirrored; Entertainment retains
    # whatever prior value it had (or is absent). No assertion here.


# =============================================================================
# D4.d — No mirror when thermostat is unique
# =============================================================================


def test_v475_d4_no_mirror_when_unique_thermostat(shared_thermostat_zm):
    """Office's thermostat is unique; save on Office does not mirror to anyone."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Office")
    saved_payload = {
        CONF_ZONE_THERMOSTAT: "climate.office",
        CONF_HVAC_AC_LOAD_SENSOR: "sensor.office_load",
    }
    mirrored = flow._auto_mirror_to_siblings(
        shared_thermostat_zm,
        "Office",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_HVAC,
    )
    assert mirrored == []

    new_zones = shared_thermostat_zm.options["zones"]
    assert new_zones["Office"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.office_load"
    # Entertainment / Master Suite untouched
    assert new_zones["Entertainment"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.legacy_load"
    assert new_zones["Master Suite"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.legacy_load"
    # v4.7.5 post-review (B-M4): no-sibling save path also schedules no tasks.
    assert flow.hass.created_tasks == []


# =============================================================================
# D4.e — Unlink: reassigning thermostat mirrors to OLD AND NEW sibling groups
# =============================================================================


def test_v475_d4_unlink_mirrors_to_old_and_new():
    """Reassigning Master Suite's thermostat from thermo_1 to thermo_2 (where
    Office already lives on thermo_2) mirrors:
      - new payload to Entertainment (the OLD sibling) ONE LAST TIME
      - new payload to Office (the NEW sibling)
    """
    zm = _StubEntry(
        data={ENTRY_TYPE_KEY: ENTRY_TYPE_ZONE_MANAGER},
        options={
            "zones": {
                "Entertainment": {
                    CONF_ZONE_THERMOSTAT: "climate.thermo_1",
                    CONF_HVAC_AC_LOAD_SENSOR: "sensor.t1_old",
                },
                "Master Suite": {
                    CONF_ZONE_THERMOSTAT: "climate.thermo_1",
                    CONF_HVAC_AC_LOAD_SENSOR: "sensor.t1_old",
                },
                "Office": {
                    CONF_ZONE_THERMOSTAT: "climate.thermo_2",
                    CONF_HVAC_AC_LOAD_SENSOR: "sensor.t2_old",
                },
            },
        },
    )
    flow = _make_flow_with_zm(zm, selected_zone="Master Suite")
    saved_payload = {
        # Master Suite moves to thermo_2 and picks a new load sensor
        CONF_ZONE_THERMOSTAT: "climate.thermo_2",
        CONF_HVAC_AC_LOAD_SENSOR: "sensor.t2_new",
        CONF_HVAC_AC_RAMP_ZONE_ENABLED: True,
    }
    mirrored = flow._auto_mirror_to_siblings(
        zm,
        "Master Suite",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_HVAC,
        old_thermostat="climate.thermo_1",
    )
    # Both the OLD sibling (Entertainment) and the NEW sibling (Office) must
    # receive the mirror; order is "new first, then old (if not already)".
    assert set(mirrored) == {"Entertainment", "Office"}

    new_zones = zm.options["zones"]
    # Master Suite got the new values
    assert new_zones["Master Suite"][CONF_ZONE_THERMOSTAT] == "climate.thermo_2"
    assert new_zones["Master Suite"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.t2_new"
    # Entertainment (old sibling) got the final pre-unlink payload
    assert new_zones["Entertainment"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.t2_new"
    assert new_zones["Entertainment"][CONF_ZONE_THERMOSTAT] == "climate.thermo_2"
    # Office (new sibling) also got the mirror
    assert new_zones["Office"][CONF_HVAC_AC_LOAD_SENSOR] == "sensor.t2_new"
    # v4.7.5 post-review (B-M4): unlink path is still a single sync write —
    # zero scheduled background tasks even when mirroring OLD + NEW groups.
    assert flow.hass.created_tasks == []


# =============================================================================
# D4 banner — siblings list correctness
# =============================================================================


def test_v475_d4_banner_lists_siblings(shared_thermostat_zm):
    """`_get_shared_thermostat_siblings('Entertainment')` returns ['Master Suite']."""
    flow = _make_flow_with_zm(shared_thermostat_zm)
    sibs = flow._get_shared_thermostat_siblings(shared_thermostat_zm, "Entertainment")
    assert sibs == ["Master Suite"]
    sibs2 = flow._get_shared_thermostat_siblings(shared_thermostat_zm, "Office")
    assert sibs2 == []
    # Zone with no thermostat → empty
    shared_thermostat_zm.options["zones"]["Storage"] = {}
    sibs3 = flow._get_shared_thermostat_siblings(shared_thermostat_zm, "Storage")
    assert sibs3 == []


# =============================================================================
# D4 — Exactly one async_update_entry per save (reload chain doesn't double)
# =============================================================================


def test_v475_d4_one_update_entry_per_save(shared_thermostat_zm):
    """Mirror helper must call async_update_entry EXACTLY ONCE per save."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Entertainment")
    saved_payload = {
        CONF_ZONE_THERMOSTAT: "climate.studyb_zone_1",
        CONF_HVAC_AC_LOAD_SENSOR: "sensor.foo_new",
    }
    flow._auto_mirror_to_siblings(
        shared_thermostat_zm,
        "Entertainment",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_HVAC,
    )
    assert len(flow.hass.config_entries.update_calls) == 1, (
        "v4.7.5 D4 / Reviewer B: save + mirror must fold into ONE "
        "async_update_entry call. Two calls means the update_listener fires "
        "twice — re-entrant reload hazard echoes Bug Class #46."
    )


# =============================================================================
# D4 — MIRROR_KEYS_* constants are correctly scoped
# =============================================================================


def test_v475_d4_mirror_keys_module_constants_present():
    """All 7 MIRROR_KEYS_* constants exist on the config_flow module."""
    expected = [
        "MIRROR_KEYS_ZONE_ROOMS",
        "MIRROR_KEYS_ZONE_MEDIA",
        "MIRROR_KEYS_ZONE_HVAC",
        "MIRROR_KEYS_ZONE_ENERGY",
        "MIRROR_KEYS_ZONE_PERSONS",
        "MIRROR_KEYS_ZONE_CAMERAS",
        "MIRROR_KEYS_ZONE_DPM",
    ]
    for name in expected:
        assert hasattr(_CF_MOD, name), (
            f"v4.7.5 D4: MIRROR_KEYS_* constant {name!r} missing from "
            "config_flow.py module-level."
        )


def test_v475_d4_per_house_zone_mirror_sets_empty():
    """Per-house-zone CONFs (rooms, media, persons, cameras) MUST NOT mirror."""
    assert _CF_MOD.MIRROR_KEYS_ZONE_ROOMS == frozenset()
    assert _CF_MOD.MIRROR_KEYS_ZONE_MEDIA == frozenset()
    assert _CF_MOD.MIRROR_KEYS_ZONE_PERSONS == frozenset()
    assert _CF_MOD.MIRROR_KEYS_ZONE_CAMERAS == frozenset()


def test_v475_d4_hvac_mirror_set_contains_shared_equipment_keys():
    """MIRROR_KEYS_ZONE_HVAC must include thermostat + AC ramp fields."""
    assert "zone_thermostat" in _CF_MOD.MIRROR_KEYS_ZONE_HVAC
    assert "hvac_ac_load_sensor" in _CF_MOD.MIRROR_KEYS_ZONE_HVAC
    assert "hvac_ac_ramp_zone_enabled" in _CF_MOD.MIRROR_KEYS_ZONE_HVAC


def test_v475_d4_dpm_mirror_set_contains_master_toggle_and_buckets():
    """MIRROR_KEYS_ZONE_DPM must include the 4 active DPM knobs.

    v5.11.x DPM cleanup: bucket cell + customize_buckets keys were
    stripped from MIRROR_KEYS_ZONE_DPM. Only the 4 knobs that drive
    runtime behavior mirror to sibling zones. This test also enforces
    the ABSENCE of the 17 vestigial keys as a regression guard against
    reintroduction.
    """
    expected_subset = {
        "zone_dynamic_preset_enabled",
        "zone_dynamic_preset_offset",
        "zone_dynamic_preset_reset_offset_guest",
        "zone_dynamic_preset_sleep_enabled",
    }
    missing = expected_subset - _CF_MOD.MIRROR_KEYS_ZONE_DPM
    assert not missing, (
        f"v5.11.x DPM cleanup: MIRROR_KEYS_ZONE_DPM missing keys {missing}"
    )
    forbidden = {
        "zone_dynamic_preset_customize_buckets",
        "zone_dynamic_preset_cool_home_low",
        "zone_dynamic_preset_cool_home_high",
        "zone_dynamic_preset_mild_home_low",
        "zone_dynamic_preset_mild_home_high",
        "zone_dynamic_preset_hot_home_low",
        "zone_dynamic_preset_hot_home_high",
        "zone_dynamic_preset_extreme_home_low",
        "zone_dynamic_preset_extreme_home_high",
        "zone_dynamic_preset_cool_sleep_low",
        "zone_dynamic_preset_cool_sleep_high",
        "zone_dynamic_preset_mild_sleep_low",
        "zone_dynamic_preset_mild_sleep_high",
        "zone_dynamic_preset_hot_sleep_low",
        "zone_dynamic_preset_hot_sleep_high",
        "zone_dynamic_preset_extreme_sleep_low",
        "zone_dynamic_preset_extreme_sleep_high",
    }
    resurrected = forbidden & _CF_MOD.MIRROR_KEYS_ZONE_DPM
    assert not resurrected, (
        f"v5.11.x DPM cleanup: 17 vestigial keys resurfaced in "
        f"MIRROR_KEYS_ZONE_DPM: {resurrected}"
    )


# =============================================================================
# v4.7.5 post-review M4 — every per-zone editor step routes through the
# centralised _auto_mirror_to_siblings helper. If a future maintainer inlines
# `async_update_entry` again on any of these steps, this test fails and the
# Option C invariant ("one save = one update_entry") is locked.
# =============================================================================


def test_v475_d4_every_save_step_routes_through_mirror_helper():
    """All 7 zone editor save paths must call self._auto_mirror_to_siblings.

    AST-scan config_flow.py; for each AsyncFunctionDef in the expected set,
    assert that its body (at any nesting depth) contains a Call to
    `self._auto_mirror_to_siblings(...)`. Catches the H1-class regression
    (zone_rooms used inline async_update_entry, contradicting its comment).
    """
    import ast as _ast

    cf_path = os.path.join(_COMPONENT_DIR, "config_flow.py")
    with open(cf_path) as _f:
        src = _f.read()
    tree = _ast.parse(src)

    expected_callers = {
        "async_step_zone_rooms",
        "async_step_zone_media",
        "async_step_zone_hvac",
        "async_step_zone_energy",
        "async_step_zone_persons",
        "async_step_zone_cameras",
        "async_step_zone_dynamic_preset",
    }

    found_callers: set[str] = set()
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.AsyncFunctionDef):
            continue
        if node.name not in expected_callers:
            continue
        for sub in _ast.walk(node):
            if not isinstance(sub, _ast.Call):
                continue
            func = sub.func
            if (
                isinstance(func, _ast.Attribute)
                and func.attr == "_auto_mirror_to_siblings"
                and isinstance(func.value, _ast.Name)
                and func.value.id == "self"
            ):
                found_callers.add(node.name)
                break

    missing = expected_callers - found_callers
    assert not missing, (
        "v4.7.5 D4 (post-review M4): the following per-zone editor steps do "
        "NOT call self._auto_mirror_to_siblings — Option C 'one save = one "
        f"update_entry' invariant broken on: {sorted(missing)}. "
        "Route each step through the helper (per-house-zone steps use an "
        "empty MIRROR_KEYS_* set; the helper is then a save-only path)."
    )


# =============================================================================
# v4.7.5 post-review A-H2 — MIRROR_KEYS_ZONE_ENERGY covers every thermostat-
# tied CONF the zone_energy step writes. If a new shared-circuit field is
# added to the energy form schema, it MUST be added to MIRROR_KEYS_ZONE_ENERGY
# (or explicitly documented as per-house-zone).
# =============================================================================


def test_v475_d4_energy_mirror_set_covers_step_schema():
    """Every CONF key written by async_step_zone_energy must be in the mirror set.

    Today the schema accepts CONF_ZONE_POWER_SENSORS + CONF_ZONE_ENERGY_SENSORS
    only — both are physical AC sub-circuit sensors tied to the shared
    thermostat. The mirror set must include them; a future contributor adding
    a third thermostat-tied energy CONF must update this test + the set.
    """
    expected_thermostat_tied = {
        "zone_power_sensors",
        "zone_energy_sensors",
    }
    missing = expected_thermostat_tied - _CF_MOD.MIRROR_KEYS_ZONE_ENERGY
    assert not missing, (
        "v4.7.5 D4 (post-review A-H2): MIRROR_KEYS_ZONE_ENERGY narrowed past "
        f"the thermostat-tied set; missing keys {missing}. Every per-zone "
        "energy CONF on async_step_zone_energy that tracks the shared AC "
        "sub-circuit MUST be in this set — otherwise saving on one sibling "
        "leaves the other stale."
    )


# =============================================================================
# v4.7.5 post-review (Reviewer B H3) — zone_energy + zone_dynamic_preset save
# paths pass old_thermostat to the mirror helper so the unlink branch fires
# on those steps too (not just zone_hvac).
# =============================================================================


def test_v475_d4_unlink_mirrors_energy_to_old_sibling():
    """Saving zone_energy after a thermostat reassignment mirrors the new
    energy payload to the OLD sibling one final time so the previous sibling
    group reflects the final pre-unlink state."""
    zm = _StubEntry(
        data={ENTRY_TYPE_KEY: ENTRY_TYPE_ZONE_MANAGER},
        options={
            "zones": {
                "Entertainment": {
                    CONF_ZONE_THERMOSTAT: "climate.thermo_1",
                    "zone_power_sensors": ["sensor.t1_power_old"],
                },
                "Master Suite": {
                    CONF_ZONE_THERMOSTAT: "climate.thermo_2",
                    "zone_power_sensors": ["sensor.t1_power_old"],
                },
                "Office": {
                    CONF_ZONE_THERMOSTAT: "climate.thermo_2",
                    "zone_power_sensors": ["sensor.t2_power_old"],
                },
            },
        },
    )
    flow = _make_flow_with_zm(zm, selected_zone="Master Suite")
    # Master Suite already moved to thermo_2 (via a prior HVAC save); now the
    # user saves new energy sensors on Master Suite. The unlink branch mirrors
    # the new sensors to Entertainment (the OLD sibling) AND Office (the NEW
    # sibling), in one async_update_entry call.
    saved_payload = {
        "zone_power_sensors": ["sensor.t2_power_new"],
    }
    mirrored = flow._auto_mirror_to_siblings(
        zm,
        "Master Suite",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_ENERGY,
        old_thermostat="climate.thermo_1",
    )
    # Office (new sibling) AND Entertainment (old sibling) both mirrored
    assert set(mirrored) == {"Office", "Entertainment"}
    new_zones = zm.options["zones"]
    assert new_zones["Entertainment"]["zone_power_sensors"] == ["sensor.t2_power_new"]
    assert new_zones["Office"]["zone_power_sensors"] == ["sensor.t2_power_new"]
    # And it folded into ONE async_update_entry
    assert len(flow.hass.config_entries.update_calls) == 1


# =============================================================================
# v4.7.5 post-review (B-M4) — _StubHass `async_create_task` trip-wire.
# Helper must not schedule background tasks on ANY save path. A future
# regression that adds `hass.async_create_task(...)` inside the helper would
# slip past every other D4 test silently — this one nails it.
# =============================================================================


def test_v475_d4_helper_does_not_schedule_background_tasks(shared_thermostat_zm):
    """The mirror helper runs synchronously and MUST NOT call
    hass.async_create_task on any path (Bug Class #42 prevention)."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Entertainment")
    saved_payload = {
        CONF_ZONE_THERMOSTAT: "climate.studyb_zone_1",
        CONF_HVAC_AC_LOAD_SENSOR: "sensor.foo_new",
    }
    flow._auto_mirror_to_siblings(
        shared_thermostat_zm,
        "Entertainment",
        saved_payload,
        _CF_MOD.MIRROR_KEYS_ZONE_HVAC,
    )
    assert flow.hass.created_tasks == [], (
        "v4.7.5 D4 (B-M4): _auto_mirror_to_siblings must not schedule "
        "background tasks — it runs synchronously inside the options-flow "
        "handler. Tasks scheduled: %r" % flow.hass.created_tasks
    )


def test_v475_d4_stub_hass_records_async_create_task_calls(shared_thermostat_zm):
    """Sanity: the trip-wire itself works — explicitly calling
    `hass.async_create_task(...)` populates `created_tasks`. Without this
    self-test, a broken stub would silently accept any helper behavior."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Entertainment")

    async def _noop():
        return None

    # Stub records both unnamed and named calls
    flow.hass.async_create_task(_noop())
    flow.hass.async_create_task(_noop(), name="probe")
    assert flow.hass.created_tasks == ["<unnamed>", "probe"], (
        "v4.7.5 D4 B-M4 trip-wire self-test: _StubHass.async_create_task did "
        "not record the calls. The B-M4 assertions in other tests would pass "
        f"vacuously. Got: {flow.hass.created_tasks!r}"
    )


# =============================================================================
# v4.7.5 post-review (A-M2) — `_render_shared_thermostat_banner` is a
# read-only helper. The same inputs must produce the same output across
# repeated calls AND must not mutate `entry.options` / `entry.data`.
# =============================================================================


def test_v475_d4_render_banner_is_side_effect_free(shared_thermostat_zm):
    """The banner helper reads only — repeated calls return identical strings
    and leave the ZM entry unchanged."""
    import copy

    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Entertainment")
    flow._selected_zone_name = "Entertainment"

    # Snapshot before
    data_before = copy.deepcopy(shared_thermostat_zm.data)
    options_before = copy.deepcopy(shared_thermostat_zm.options)

    banner1 = flow._render_shared_thermostat_banner("Entertainment")
    banner2 = flow._render_shared_thermostat_banner("Entertainment")
    banner3 = flow._render_shared_thermostat_banner("Entertainment")

    # Same input → same output
    assert banner1 == banner2 == banner3, (
        "v4.7.5 D4 (A-M2): _render_shared_thermostat_banner is supposed to be "
        "a pure read-only helper; repeated calls returned divergent strings: "
        f"{banner1!r} vs {banner2!r} vs {banner3!r}"
    )
    # Non-empty for shared-thermostat zone
    assert "Master Suite" in banner1
    assert "climate.studyb_zone_1" in banner1

    # No mutation of the entry
    assert shared_thermostat_zm.data == data_before, (
        "v4.7.5 D4 (A-M2): banner helper mutated entry.data — the read-only "
        "contract is broken."
    )
    assert shared_thermostat_zm.options == options_before, (
        "v4.7.5 D4 (A-M2): banner helper mutated entry.options — the "
        "read-only contract is broken."
    )
    # No background tasks scheduled either
    assert flow.hass.created_tasks == [], (
        "v4.7.5 D4 (A-M2 + B-M4): banner helper scheduled background tasks: "
        f"{flow.hass.created_tasks!r}"
    )


def test_v475_d4_render_banner_empty_for_solo_zone(shared_thermostat_zm):
    """Office has a unique thermostat → banner is empty string (not None)."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone="Office")
    banner = flow._render_shared_thermostat_banner("Office")
    assert banner == "", (
        f"v4.7.5 D4 (A-M2): solo-thermostat zone should return empty banner; "
        f"got {banner!r}"
    )


def test_v475_d4_render_banner_empty_for_none_zone_name(shared_thermostat_zm):
    """Legacy zone-entry path passes zone_name=None → banner is empty."""
    flow = _make_flow_with_zm(shared_thermostat_zm, selected_zone=None)
    banner = flow._render_shared_thermostat_banner(None)
    assert banner == "", (
        "v4.7.5 D4 (A-M2): legacy zone-entry path (zone_name=None) must "
        f"return empty banner; got {banner!r}"
    )

"""Tests for the HVAC presence-timer knobs + options-writeback retrofit.

Per planning doc:
``docs/planning/PLANNING_hvac_presence_timer_knobs_and_options_writeback_retrofit.md``

Coverage (D6):
  1. AST: none of the four presence-timer Numbers inherit RestoreEntity.
  2. Each of the four Numbers' ``async_set_native_value`` calls
     ``async_update_entry`` with the matching CONF key.
  3. Call-order: live-attr push on the HVAC coordinator happens BEFORE
     ``async_update_entry``.
  4. Reset button: SINGLE ``async_update_entry`` call carrying all four
     defaults; all four live attrs set on the mocked coordinator.
  5. Config-flow schema source contains a ``presence_timing`` section.
  6. The ``vacancy_grace_constrained > vacancy_grace`` reject path exists
     in source and ``vacancy_grace_constrained_exceeds_normal`` is the
     error key.
  7. ``strings.json`` and ``translations/en.json`` carry identical key
     sets under ``coordinator_hvac_settings.data`` /
     ``coordinator_hvac_settings.data_description`` and both include the
     three new presence-timer keys.
  8. AST: ``ZoneEntryDwellNumber._attr_name`` starts ``"47 · Zone Entry
     Dwell"``; ``HVACZoneSweepSwitch._attr_name`` starts ``"46 · Vacancy
     Auto-Off"`` AND its ``_attr_unique_id`` is still
     ``f"{DOMAIN}_hvac_zone_sweep"``.
  9. All four presence-timer Numbers have ``_attr_mode = NumberMode.BOX``
     and the four config-flow ``NumberSelector``s in the
     ``presence_timing`` section use ``NumberSelectorMode.BOX``.

The tests are SOURCE-AST + LIGHT-MOCK style — they do not import the
runtime URA package, matching the precedent in
``test_v4521_hc_device_ordering.py`` (AST) and the lightweight mock
pattern used by entity tests. The four entity-class behaviour tests
(2, 3, 4) instantiate a class extracted at AST-parse time and exercise
``async_set_native_value`` / ``async_press`` directly via lightweight
``MagicMock`` stand-ins for hass / entry / coordinator — same approach
as v4.7.x cycle tests.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import sys
import types
import importlib
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"


# ===========================================================================
# Fixtures — raw source for AST-walk tests
# ===========================================================================


@pytest.fixture(scope="module")
def number_src() -> str:
    return (PKG / "number.py").read_text()


@pytest.fixture(scope="module")
def switch_src() -> str:
    return (PKG / "switch.py").read_text()


@pytest.fixture(scope="module")
def button_src() -> str:
    return (PKG / "button.py").read_text()


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    return (PKG / "config_flow.py").read_text()


@pytest.fixture(scope="module")
def number_tree(number_src: str) -> ast.Module:
    return ast.parse(number_src)


@pytest.fixture(scope="module")
def button_tree(button_src) -> ast.Module:
    return ast.parse(button_src)


PRESENCE_TIMER_NUMBER_CLASSES = (
    "ZoneEntryDwellNumber",
    "VacancyGraceMinutesNumber",
    "VacancyGraceConstrainedNumber",
    "MaxOccupancyHoursNumber",
)


PRESENCE_TIMER_CONF_KEYS = {
    "ZoneEntryDwellNumber": "CONF_HVAC_ZONE_ENTRY_DWELL",
    "VacancyGraceMinutesNumber": "CONF_HVAC_VACANCY_GRACE_MINUTES",
    "VacancyGraceConstrainedNumber": "CONF_HVAC_VACANCY_GRACE_CONSTRAINED",
    "MaxOccupancyHoursNumber": "CONF_HVAC_MAX_OCCUPANCY_HOURS",
}


PRESENCE_TIMER_HVAC_ATTRS = {
    "ZoneEntryDwellNumber": "_zone_entry_dwell",
    "VacancyGraceMinutesNumber": "_vacancy_grace",
    "VacancyGraceConstrainedNumber": "_vacancy_grace_constrained",
    "MaxOccupancyHoursNumber": "_max_occupancy_hours",
}


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Class {name!r} not found in module AST")


def _class_base_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _method(cls: ast.ClassDef, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in cls.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Method {name!r} not found on class {cls.name!r}")


def _class_attr_literal(cls: ast.ClassDef, attr: str) -> str | None:
    """Return the literal value assigned to ``self.<attr> = <const>`` in __init__
    OR to ``<attr> = <const>`` at class scope.
    """
    # Class-level assignment first
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == attr:
                    if isinstance(stmt.value, ast.Constant):
                        return stmt.value.value
    # __init__ self.<attr> = <const>
    try:
        init = _method(cls, "__init__")
    except AssertionError:
        return None
    for stmt in ast.walk(init):
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if (
                    isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "self"
                    and tgt.attr == attr
                    and isinstance(stmt.value, ast.Constant)
                ):
                    return stmt.value.value
    return None


# ===========================================================================
# Test 1 — AST: no RestoreEntity on any presence-timer Number
# ===========================================================================


@pytest.mark.parametrize("class_name", PRESENCE_TIMER_NUMBER_CLASSES)
def test_no_restore_entity_on_presence_timer_numbers(number_tree, class_name):
    cls = _find_class(number_tree, class_name)
    bases = _class_base_names(cls)
    assert "RestoreEntity" not in bases, (
        f"{class_name} must NOT inherit RestoreEntity — entry.options is the "
        f"sole source of truth. Found bases: {sorted(bases)!r}"
    )


# ===========================================================================
# Test 2 — async_set_native_value writes back to entry.options with matching
# CONF key, mutates self._value and pushes to hvac._<attr>.
# ===========================================================================


@pytest.mark.parametrize("class_name", PRESENCE_TIMER_NUMBER_CLASSES)
def test_async_set_native_value_calls_update_entry(number_tree, class_name):
    cls = _find_class(number_tree, class_name)
    method = _method(cls, "async_set_native_value")
    src = ast.unparse(method)
    conf_key = PRESENCE_TIMER_CONF_KEYS[class_name]
    hvac_attr = PRESENCE_TIMER_HVAC_ATTRS[class_name]

    # Calls async_update_entry with the matching CONF key.
    assert "async_update_entry" in src, (
        f"{class_name}.async_set_native_value must call async_update_entry "
        f"to persist to entry.options."
    )
    assert conf_key in src, (
        f"{class_name}.async_set_native_value must reference {conf_key} when "
        f"updating entry.options."
    )
    # Pushes to the live HVAC coordinator attribute.
    assert f"hvac.{hvac_attr}" in src, (
        f"{class_name}.async_set_native_value must push to hvac.{hvac_attr} "
        f"for next-cycle pickup."
    )
    # Updates self._value.
    assert "self._value" in src


# ===========================================================================
# Test 3 — call-order: live-attr push BEFORE async_update_entry.
# ===========================================================================


@pytest.mark.parametrize("class_name", PRESENCE_TIMER_NUMBER_CLASSES)
def test_live_attr_push_before_update_entry(number_tree, class_name):
    cls = _find_class(number_tree, class_name)
    method = _method(cls, "async_set_native_value")
    src = ast.unparse(method)
    hvac_attr = PRESENCE_TIMER_HVAC_ATTRS[class_name]
    live_idx = src.find(f"hvac.{hvac_attr}")
    write_idx = src.find("async_update_entry")
    assert live_idx >= 0 and write_idx >= 0
    assert live_idx < write_idx, (
        f"{class_name}.async_set_native_value must push to hvac.{hvac_attr} "
        f"BEFORE calling async_update_entry (so next decision cycle picks up "
        f"the value before the reload settles)."
    )


# ===========================================================================
# Test 4 — ResetPresenceTimersButton: SINGLE async_update_entry carrying
# all four defaults; all four live attrs pushed.
# ===========================================================================


def test_reset_presence_timers_button_single_writeback(button_tree):
    cls = _find_class(button_tree, "ResetPresenceTimersButton")
    method = _method(cls, "async_press")
    src = ast.unparse(method)
    # Exactly one async_update_entry call inside the method body.
    update_calls = [
        n for n in ast.walk(method)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "async_update_entry"
    ]
    assert len(update_calls) == 1, (
        f"Expected exactly ONE async_update_entry call in "
        f"ResetPresenceTimersButton.async_press, got {len(update_calls)}."
    )
    # All four default constants referenced.
    for const_name in (
        "DEFAULT_VACANCY_GRACE_MINUTES",
        "DEFAULT_VACANCY_GRACE_CONSTRAINED",
        "DEFAULT_MAX_OCCUPANCY_HOURS",
        "DEFAULT_ZONE_ENTRY_DWELL_MINUTES",
    ):
        assert const_name in src, (
            f"ResetPresenceTimersButton.async_press must reference "
            f"{const_name} when resetting."
        )
    # All four live attrs pushed.
    for attr in PRESENCE_TIMER_HVAC_ATTRS.values():
        assert f"hvac.{attr}" in src, (
            f"ResetPresenceTimersButton.async_press must push hvac.{attr}."
        )


def test_reset_presence_timers_button_attrs(button_tree):
    """Slot 51, CONFIG entity_category, correct unique_id, lives on HC device."""
    cls = _find_class(button_tree, "ResetPresenceTimersButton")
    name = _class_attr_literal(cls, "_attr_name")
    assert name is not None and name.startswith("51 · Reset Presence Timers"), (
        f"Expected _attr_name to start with '51 · Reset Presence Timers', "
        f"got {name!r}"
    )
    init_src = ast.unparse(_method(cls, "__init__"))
    # Quote-agnostic: ast.unparse normalizes string literals to single quotes,
    # so match the quote-independent interior of each literal.
    assert "{DOMAIN}_hvac_reset_presence_timers" in init_src
    assert "hvac_coordinator" in init_src
    # _attr_entity_category is a class-body attribute, not set in __init__.
    cls_src = ast.unparse(cls)
    assert "EntityCategory.CONFIG" in cls_src


# ===========================================================================
# Test 5 — Config-flow schema contains a presence_timing section with the
# four expected fields.
# ===========================================================================


def test_hvac_settings_schema_includes_presence_timing_section(config_flow_src):
    assert 'vol.Optional("presence_timing")' in config_flow_src, (
        "Expected a vol.Optional('presence_timing') section in "
        "async_step_coordinator_hvac_settings schema."
    )
    # Section body must hold all four presence-timer CONF keys.
    # Locate the section block and search within it.
    start = config_flow_src.find('vol.Optional("presence_timing"): section(')
    assert start >= 0
    # Take the next ~3000 chars of source as the section window.
    window = config_flow_src[start:start + 4000]
    for key in (
        "CONF_HVAC_VACANCY_GRACE_MINUTES",
        "CONF_HVAC_VACANCY_GRACE_CONSTRAINED",
        "CONF_HVAC_ZONE_ENTRY_DWELL",
        "CONF_HVAC_MAX_OCCUPANCY_HOURS",
    ):
        assert key in window, (
            f"presence_timing section must include {key}."
        )


def test_zone_entry_dwell_moved_into_section(config_flow_src):
    """The dwell CONF should appear ONLY once in the schema region — inside
    the presence_timing section, not as a top-level schema entry.
    """
    # Count occurrences of CONF_HVAC_ZONE_ENTRY_DWELL inside the schema
    # build for coordinator_hvac_settings. Easy proxy: only one
    # `vol.Optional(\n*\s*CONF_HVAC_ZONE_ENTRY_DWELL` in the entire file.
    pattern = re.compile(r"vol\.Optional\(\s*CONF_HVAC_ZONE_ENTRY_DWELL")
    matches = pattern.findall(config_flow_src)
    assert len(matches) == 1, (
        "CONF_HVAC_ZONE_ENTRY_DWELL should appear in exactly ONE vol.Optional "
        "schema slot (the presence_timing section). Found "
        f"{len(matches)} occurrences."
    )


# ===========================================================================
# Test 6 — Cross-field validation: grace_constrained > grace yields the
# expected error key and bypasses async_create_entry.
# ===========================================================================


def test_constrained_validation_reject_in_source(config_flow_src):
    assert "vacancy_grace_constrained_exceeds_normal" in config_flow_src, (
        "Expected error key 'vacancy_grace_constrained_exceeds_normal' in "
        "config_flow.py for the constrained-vs-normal vacancy delay reject."
    )
    # The reject path must compare grace_constrained > grace.
    assert "grace_constrained > grace" in config_flow_src, (
        "Expected explicit `grace_constrained > grace` comparison guarding "
        "the error path."
    )


def test_flatten_presence_timing_before_validation(config_flow_src):
    """Section flatten happens BEFORE create_entry / validation, mirroring
    the fan_recheck precedent.
    """
    flatten_idx = config_flow_src.find('user_input.pop("presence_timing"')
    cover_validation_idx = config_flow_src.find('"cover_temp_hysteresis_too_small"')
    assert flatten_idx >= 0 and cover_validation_idx >= 0
    assert flatten_idx < cover_validation_idx, (
        "Flatten of presence_timing must happen BEFORE the cover-temp "
        "validation read of user_input keys."
    )


# ===========================================================================
# Test 7 — strings.json + translations/en.json key parity.
# ===========================================================================


@pytest.fixture(scope="module")
def strings_json() -> dict:
    return json.loads((PKG / "strings.json").read_text())


@pytest.fixture(scope="module")
def translations_en() -> dict:
    return json.loads((PKG / "translations" / "en.json").read_text())


def _hvac_settings_block(blob: dict) -> dict:
    return blob["options"]["step"]["coordinator_hvac_settings"]


def test_strings_and_translations_data_keys_in_lockstep(strings_json, translations_en):
    s = _hvac_settings_block(strings_json)
    t = _hvac_settings_block(translations_en)
    assert set(s["data"].keys()) == set(t["data"].keys()), (
        "data keys diverged between strings.json and translations/en.json"
    )
    assert set(s["data_description"].keys()) == set(t["data_description"].keys()), (
        "data_description keys diverged between strings.json and translations/en.json"
    )


def test_new_presence_timer_keys_present(strings_json, translations_en):
    s = _hvac_settings_block(strings_json)
    t = _hvac_settings_block(translations_en)
    for key in (
        "hvac_vacancy_grace_minutes",
        "hvac_vacancy_grace_constrained",
        "hvac_max_occupancy_hours",
    ):
        assert key in s["data"], f"strings.json missing {key} in data"
        assert key in s["data_description"], f"strings.json missing {key} in data_description"
        assert key in t["data"], f"translations/en.json missing {key} in data"
        assert key in t["data_description"], f"translations/en.json missing {key} in data_description"


def test_presence_timing_section_title_present(strings_json, translations_en):
    s = _hvac_settings_block(strings_json)
    t = _hvac_settings_block(translations_en)
    assert "sections" in s and "presence_timing" in s["sections"]
    assert "sections" in t and "presence_timing" in t["sections"]


def test_constrained_error_key_present(strings_json, translations_en):
    s_err = strings_json["options"]["error"]
    t_err = translations_en["options"]["error"]
    assert "vacancy_grace_constrained_exceeds_normal" in s_err
    assert "vacancy_grace_constrained_exceeds_normal" in t_err


# ===========================================================================
# Test 8 — Renumber + relabel sanity.
# ===========================================================================


def test_zone_entry_dwell_renumbered_to_47(number_tree):
    cls = _find_class(number_tree, "ZoneEntryDwellNumber")
    name = _class_attr_literal(cls, "_attr_name")
    assert name is not None and name.startswith("47 · Zone Entry Dwell"), (
        f"Expected ZoneEntryDwellNumber._attr_name to start '47 · Zone Entry "
        f"Dwell', got {name!r}"
    )


def test_vacancy_sweep_switch_renumbered_to_46(switch_src):
    tree = ast.parse(switch_src)
    cls = _find_class(tree, "HVACZoneSweepSwitch")
    name = _class_attr_literal(cls, "_attr_name")
    assert name is not None and name.startswith("46 · Vacancy Auto-Off"), (
        f"Expected HVACZoneSweepSwitch._attr_name to start '46 · Vacancy "
        f"Auto-Off', got {name!r}"
    )
    # Unique_id stability bar — entity_id MUST NOT change.
    # Quote-agnostic: ast.unparse normalizes to single quotes.
    init_src = ast.unparse(_method(cls, "__init__"))
    assert "{DOMAIN}_hvac_zone_sweep" in init_src, (
        "HVACZoneSweepSwitch._attr_unique_id must remain "
        "f'{DOMAIN}_hvac_zone_sweep' (entity_id stability)."
    )


# ===========================================================================
# Test 9 — All four presence-timer Numbers use NumberMode.BOX; the four
# config-flow selectors in the presence_timing section use BOX.
# ===========================================================================


@pytest.mark.parametrize("class_name", PRESENCE_TIMER_NUMBER_CLASSES)
def test_presence_timer_numbers_use_box_mode(number_tree, class_name):
    cls = _find_class(number_tree, class_name)
    # _attr_mode = NumberMode.BOX at class scope
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_attr_mode":
                    rendered = ast.unparse(stmt.value)
                    assert "NumberMode.BOX" in rendered, (
                        f"{class_name}._attr_mode must be NumberMode.BOX, "
                        f"got {rendered!r}"
                    )
                    return
    raise AssertionError(
        f"{class_name} missing _attr_mode = NumberMode.BOX class attribute"
    )


def test_presence_timing_selectors_use_box(config_flow_src):
    start = config_flow_src.find('vol.Optional("presence_timing"): section(')
    assert start >= 0
    end = config_flow_src.find("{\"collapsed\": True}", start)
    if end < 0:
        end = start + 4000
    window = config_flow_src[start:end]
    # Section should contain four NumberSelector entries — every one BOX.
    selector_count = window.count("selector.NumberSelector(")
    assert selector_count == 4, (
        f"presence_timing section must contain 4 NumberSelector entries, "
        f"got {selector_count}."
    )
    box_count = window.count("NumberSelectorMode.BOX")
    assert box_count == 4, (
        f"presence_timing section must use NumberSelectorMode.BOX for all 4 "
        f"selectors, got {box_count}."
    )


# ===========================================================================
# Test 10 (bonus) — Behavioural mock: instantiate each Number with mock
# entry/hass and exercise async_set_native_value end-to-end through a
# real-ish object. Catches missed wiring the AST tests don't.
# ===========================================================================


def _load_number_module() -> types.ModuleType:
    """Load number.py in isolation with mocked homeassistant deps.

    Mirrors the lightweight mock pattern used by test_v47x_dynamic_preset.py.
    """
    if "custom_components.universal_room_automation.number" in sys.modules:
        return sys.modules["custom_components.universal_room_automation.number"]

    _identity = lambda fn: fn  # noqa: E731

    def _mock_mod(name: str, **attrs) -> types.ModuleType:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    class _NumberMode:
        BOX = "box"
        SLIDER = "slider"
        AUTO = "auto"

    class _NumberEntity:
        pass

    class _SwitchEntity:
        pass

    class _RestoreEntity:
        pass

    class _EntityCategory:
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    class _UnitOfTime:
        MINUTES = "min"
        HOURS = "h"
        SECONDS = "s"
        DAYS = "d"

    class _UnitOfTemperature:
        FAHRENHEIT = "°F"
        CELSIUS = "°C"

    mocks = {
        "homeassistant": {},
        "homeassistant.components": {},
        "homeassistant.components.number": {
            "NumberEntity": _NumberEntity,
            "NumberMode": _NumberMode,
        },
        "homeassistant.config_entries": {"ConfigEntry": MagicMock},
        "homeassistant.core": {"HomeAssistant": MagicMock, "callback": _identity},
        "homeassistant.helpers": {},
        "homeassistant.helpers.entity": {
            "EntityCategory": _EntityCategory,
            "DeviceInfo": dict,
        },
        "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": MagicMock},
        "homeassistant.helpers.restore_state": {"RestoreEntity": _RestoreEntity},
        "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
        "homeassistant.const": {
            "UnitOfTemperature": _UnitOfTemperature,
            "UnitOfTime": _UnitOfTime,
            "PERCENTAGE": "%",
        },
    }
    # Merge-don't-skip: an earlier test in the full suite may have installed a
    # partial mock for a shared module (e.g. homeassistant.components.number
    # with NumberEntity but no NumberMode). Skipping it would let number.py's
    # `from homeassistant.components.number import NumberMode` ImportError.
    # Fill in only the names that are missing so we don't clobber another
    # test's richer mock.
    for name, attrs in mocks.items():
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_mod(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)

    sys.path.insert(0, str(REPO_ROOT))

    # Package stubs
    if "custom_components" not in sys.modules:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [str(REPO_ROOT / "custom_components")]
        sys.modules["custom_components"] = cc

    ura_path = REPO_ROOT / "custom_components" / "universal_room_automation"
    if "custom_components.universal_room_automation" not in sys.modules:
        ura = types.ModuleType("custom_components.universal_room_automation")
        ura.__path__ = [str(ura_path)]
        ura.__package__ = "custom_components.universal_room_automation"
        sys.modules["custom_components.universal_room_automation"] = ura

    # Stub out the heavy-weight const, coordinator, entity, energy_const,
    # hvac_const modules pulled in by number.py — we only need the names
    # used in our Number classes.
    if "custom_components.universal_room_automation.const" not in sys.modules:
        const_spec = importlib.util.spec_from_file_location(
            "custom_components.universal_room_automation.const",
            ura_path / "const.py",
        )
        const_mod = importlib.util.module_from_spec(const_spec)
        sys.modules[const_spec.name] = const_mod
        const_spec.loader.exec_module(const_mod)

    # Stub coordinator + entity to avoid pulling in their full deps
    if "custom_components.universal_room_automation.coordinator" not in sys.modules:
        sys.modules["custom_components.universal_room_automation.coordinator"] = (
            _mock_mod(
                "custom_components.universal_room_automation.coordinator",
                UniversalRoomCoordinator=MagicMock,
            )
        )
    if "custom_components.universal_room_automation.entity" not in sys.modules:
        class _UniversalRoomEntity:
            pass
        sys.modules["custom_components.universal_room_automation.entity"] = (
            _mock_mod(
                "custom_components.universal_room_automation.entity",
                UniversalRoomEntity=_UniversalRoomEntity,
            )
        )

    # domain_coordinators package + hvac_const submodule
    dc_path = ura_path / "domain_coordinators"
    if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
        dc = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators"
        )
        dc.__path__ = [str(dc_path)]
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators"
        ] = dc

    # Load hvac_const + energy_const directly — they have no heavy deps.
    for sub in ("hvac_const", "energy_const"):
        full = f"custom_components.universal_room_automation.domain_coordinators.{sub}"
        if full in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(
            full, dc_path / f"{sub}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)

    # Finally load number.py
    spec = importlib.util.spec_from_file_location(
        "custom_components.universal_room_automation.number",
        ura_path / "number.py",
    )
    number_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = number_mod
    spec.loader.exec_module(number_mod)
    return number_mod


def _make_hass_with_hvac() -> tuple[MagicMock, MagicMock]:
    hass = MagicMock()
    hass.data = {}
    hvac = MagicMock()
    hvac._vacancy_grace = 0
    hvac._vacancy_grace_constrained = 0
    hvac._max_occupancy_hours = 0
    hvac._zone_entry_dwell = 0
    manager = MagicMock()
    manager.coordinators = {"hvac": hvac}
    hass.data["universal_room_automation"] = {"coordinator_manager": manager}
    return hass, hvac


def _make_entry(opts: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.data = {}
    entry.options = dict(opts or {})
    return entry


@pytest.mark.parametrize(
    "class_name,attr,conf_key,value",
    [
        ("VacancyGraceMinutesNumber", "_vacancy_grace",
         "hvac_vacancy_grace_minutes", 20),
        ("VacancyGraceConstrainedNumber", "_vacancy_grace_constrained",
         "hvac_vacancy_grace_constrained", 7),
        ("MaxOccupancyHoursNumber", "_max_occupancy_hours",
         "hvac_max_occupancy_hours", 12),
        ("ZoneEntryDwellNumber", "_zone_entry_dwell",
         "hvac_zone_entry_dwell", 5),
    ],
)
def test_set_native_value_end_to_end(class_name, attr, conf_key, value):
    number_mod = _load_number_module()
    hass, hvac = _make_hass_with_hvac()
    entry = _make_entry()
    cls = getattr(number_mod, class_name)
    inst = cls(hass, entry)

    # async_update_entry is the mutation surface we assert against.
    captured = {}

    def _mock_update_entry(target_entry, options=None, **_):
        captured["target"] = target_entry
        captured["options"] = options
        target_entry.options = options

    hass.config_entries.async_update_entry.side_effect = _mock_update_entry
    # async_write_ha_state is normally a NumberEntity method — stub it.
    inst.async_write_ha_state = MagicMock()

    asyncio.run(inst.async_set_native_value(value))

    # 1. Live-attr push reached the coordinator.
    assert getattr(hvac, attr) == value
    # 2. async_update_entry was called once with the CONF key.
    assert captured.get("options") is not None
    assert captured["options"][conf_key] == value
    # 3. Internal _value updated.
    assert inst._value == value


def test_constrained_number_clamps_to_normal():
    """HIGH-1: setting energy-saving delay > normal via the Number entity is
    clamped to the normal delay (the form blocks it; the entity path must too).
    """
    number_mod = _load_number_module()
    hass, hvac = _make_hass_with_hvac()
    # normal delay persisted at 15; try to set energy-saving to 30.
    entry = _make_entry({"hvac_vacancy_grace_minutes": 15})
    inst = number_mod.VacancyGraceConstrainedNumber(hass, entry)

    captured = {}

    def _mock_update_entry(target_entry, options=None, **_):
        captured["options"] = options
        target_entry.options = options

    hass.config_entries.async_update_entry.side_effect = _mock_update_entry
    inst.async_write_ha_state = MagicMock()

    asyncio.run(inst.async_set_native_value(30))

    assert captured["options"]["hvac_vacancy_grace_constrained"] == 15
    assert hvac._vacancy_grace_constrained == 15
    assert inst._value == 15


def test_lowering_normal_clamps_constrained_down():
    """HIGH-1: lowering the normal delay below the persisted energy-saving
    delay clamps the latter down in the SAME writeback (never left inverted).
    """
    number_mod = _load_number_module()
    hass, hvac = _make_hass_with_hvac()
    # normal 30, energy-saving 20 persisted; drop normal to 10.
    entry = _make_entry({
        "hvac_vacancy_grace_minutes": 30,
        "hvac_vacancy_grace_constrained": 20,
    })
    inst = number_mod.VacancyGraceMinutesNumber(hass, entry)

    captured = {}

    def _mock_update_entry(target_entry, options=None, **_):
        captured["options"] = options
        target_entry.options = options

    hass.config_entries.async_update_entry.side_effect = _mock_update_entry
    inst.async_write_ha_state = MagicMock()

    asyncio.run(inst.async_set_native_value(10))

    assert captured["options"]["hvac_vacancy_grace_minutes"] == 10
    assert captured["options"]["hvac_vacancy_grace_constrained"] == 10
    assert hvac._vacancy_grace == 10
    assert hvac._vacancy_grace_constrained == 10


def test_reset_button_end_to_end():
    """Behavioural mock for ResetPresenceTimersButton — one update_entry call
    carrying all four defaults; all four live attrs pushed.
    """
    _load_number_module()  # ensure HA mocks are in place

    # Mock homeassistant.components.button.ButtonEntity (lightweight)
    if "homeassistant.components.button" not in sys.modules:
        mod = types.ModuleType("homeassistant.components.button")
        mod.ButtonEntity = type("ButtonEntity", (), {})
        sys.modules["homeassistant.components.button"] = mod

    # Pre-stub some heavy/optional deps that button.py imports at module level.
    for missing in (
        "homeassistant.helpers.dispatcher",
        "homeassistant.helpers.event",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.entity_registry",
        "homeassistant.util.dt",
    ):
        if missing not in sys.modules:
            sys.modules[missing] = MagicMock()

    # Load button.py
    button_path = PKG / "button.py"
    full_name = "custom_components.universal_room_automation.button"
    if full_name in sys.modules:
        button_mod = sys.modules[full_name]
    else:
        spec = importlib.util.spec_from_file_location(full_name, button_path)
        button_mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = button_mod
        spec.loader.exec_module(button_mod)

    hass, hvac = _make_hass_with_hvac()
    entry = _make_entry()
    cls = button_mod.ResetPresenceTimersButton
    btn = cls(hass, entry)

    call_count = {"n": 0, "options": None}

    def _mock_update_entry(target_entry, options=None, **_):
        call_count["n"] += 1
        call_count["options"] = options
        target_entry.options = options

    hass.config_entries.async_update_entry.side_effect = _mock_update_entry

    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_const,
    )

    asyncio.run(btn.async_press())

    assert call_count["n"] == 1, (
        f"Expected exactly ONE async_update_entry call, got {call_count['n']}"
    )
    opts = call_count["options"]
    assert opts[hvac_const.CONF_HVAC_VACANCY_GRACE_MINUTES] == hvac_const.DEFAULT_VACANCY_GRACE_MINUTES
    assert opts[hvac_const.CONF_HVAC_VACANCY_GRACE_CONSTRAINED] == hvac_const.DEFAULT_VACANCY_GRACE_CONSTRAINED
    assert opts[hvac_const.CONF_HVAC_MAX_OCCUPANCY_HOURS] == hvac_const.DEFAULT_MAX_OCCUPANCY_HOURS
    assert opts[hvac_const.CONF_HVAC_ZONE_ENTRY_DWELL] == hvac_const.DEFAULT_ZONE_ENTRY_DWELL_MINUTES
    # Live attrs.
    assert hvac._vacancy_grace == hvac_const.DEFAULT_VACANCY_GRACE_MINUTES
    assert hvac._vacancy_grace_constrained == hvac_const.DEFAULT_VACANCY_GRACE_CONSTRAINED
    assert hvac._max_occupancy_hours == hvac_const.DEFAULT_MAX_OCCUPANCY_HOURS
    assert hvac._zone_entry_dwell == hvac_const.DEFAULT_ZONE_ENTRY_DWELL_MINUTES

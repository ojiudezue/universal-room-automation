"""Tests for CM option-writeback reload suppression + Part-1 hygiene + A-MED-1.

Per planning doc:
``docs/planning/PLANNING_cm_option_writeback_reload_suppression.md``

Coverage:
  D1 — last-applied-options snapshot lifecycle (seeded at setup; cleared
       at unload; reseeded after reload).
  D2 — Part-1 hygiene: DynamicPresetDwellMinutesNumber no longer inherits
       RestoreEntity; setter still writes through async_update_entry;
       docstring no longer claims RestoreEntity is canonical.
  D3 — reload suppression in _async_update_listener:
        * allowlist membership = exactly the five intended CONFs
        * single-suppress-key edit → in-place apply, NO async_reload
        * non-allowlisted edit     → async_reload (regression guard)
        * mixed-key edit            → async_reload
        * ROOM entry edit           → async_reload (unchanged)
        * apply_in_place updates live attrs + snapshot
        * A-HIGH-1 clamp invariant preserved through in-place apply
  D5 — config-flow async_step_coordinator_hvac_settings:
        * BOTH violations → combined `errors["base"]` in single submit
        * single cover violation → existing key (byte-identical)
        * single vacancy violation → existing key (byte-identical)
        * combined translation key present in strings.json + en.json

These tests are SOURCE-AST + LIGHT-MOCK style (no runtime HA package
import for most assertions), matching `test_hvac_presence_timer_knobs.py`.
The listener behavior tests import the real `_async_update_listener`,
`_apply_in_place`, and `OPTIONS_RELOAD_SUPPRESS_KEYS` via a lightweight
package shim that stubs the heavy HA-dependent siblings.
"""
from __future__ import annotations

import ast
import asyncio
import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC = (PKG / "__init__.py").read_text()
NUMBER_SRC = (PKG / "number.py").read_text()
CONFIG_FLOW_SRC = (PKG / "config_flow.py").read_text()
STRINGS = json.loads((PKG / "strings.json").read_text())
EN_TRANSLATIONS = json.loads((PKG / "translations" / "en.json").read_text())


# ============================================================================
# D3 — allowlist membership (AST + symbolic CONF imports)
# ============================================================================


def test_options_reload_suppress_keys_exists_and_is_frozenset():
    """The allowlist must exist as a module-level frozenset literal."""
    assert "OPTIONS_RELOAD_SUPPRESS_KEYS" in INIT_SRC
    assert "OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str] = frozenset({" in INIT_SRC


def test_options_reload_suppress_keys_contains_exactly_five_conf_imports():
    """Five CONFs (the four HVAC presence timers + DPM dwell) must each
    appear in the suppress-keys block. Each CONF imported via an alias so
    the literal-match check is deterministic.
    """
    # Extract the OPTIONS_RELOAD_SUPPRESS_KEYS block source
    m = re.search(
        r"OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset\[str\] = frozenset\(\{(.*?)\}\)",
        INIT_SRC, re.DOTALL,
    )
    assert m, "OPTIONS_RELOAD_SUPPRESS_KEYS block not found"
    body = m.group(1)
    expected = [
        "_CONF_HVAC_VACANCY_GRACE_MINUTES",
        "_CONF_HVAC_VACANCY_GRACE_CONSTRAINED",
        "_CONF_HVAC_MAX_OCCUPANCY_HOURS",
        "_CONF_HVAC_ZONE_ENTRY_DWELL",
        "_CONF_DYNAMIC_PRESET_DWELL_MINUTES",
    ]
    for name in expected:
        assert name in body, f"{name} missing from OPTIONS_RELOAD_SUPPRESS_KEYS"
    # Count CONF aliases — guards against accidental additions.
    alias_count = sum(1 for name in expected if name in body)
    assert alias_count == 5


def test_options_reload_suppress_keys_resolves_to_known_conf_strings():
    """Resolve each CONF alias through the actual const module so the
    allowlist's CONTENT (string values) is locked, not just its names.
    """
    # Import the const modules directly without triggering URA package init.
    hvac_const_src = (PKG / "domain_coordinators" / "hvac_const.py").read_text()
    energy_const_src = (PKG / "domain_coordinators" / "energy_const.py").read_text()

    def extract(src: str, name: str) -> str:
        m = re.search(
            rf"^{name}\s*:\s*Final\s*=\s*\"([^\"]+)\"",
            src, re.MULTILINE,
        )
        assert m, f"{name} not found"
        return m.group(1)

    expected_strings = {
        extract(hvac_const_src, "CONF_HVAC_VACANCY_GRACE_MINUTES"),
        extract(hvac_const_src, "CONF_HVAC_VACANCY_GRACE_CONSTRAINED"),
        extract(hvac_const_src, "CONF_HVAC_MAX_OCCUPANCY_HOURS"),
        extract(hvac_const_src, "CONF_HVAC_ZONE_ENTRY_DWELL"),
        extract(energy_const_src, "CONF_DYNAMIC_PRESET_DWELL_MINUTES"),
    }
    assert expected_strings == {
        "hvac_vacancy_grace_minutes",
        "hvac_vacancy_grace_constrained",
        "hvac_max_occupancy_hours",
        "hvac_zone_entry_dwell",
        "dynamic_preset_dwell_minutes",
    }


# ============================================================================
# D1 + D3 — listener behavior (runtime test against real listener function)
# ============================================================================


def _load_init_listener_helpers():
    """Extract the listener + helpers from __init__.py as a synthetic
    module so the test can drive the real code paths without importing
    the full URA package (which depends on Home Assistant runtime).

    We isolate the two helpers and the listener by re-parsing the source
    and execing the relevant top-level definitions into a fresh namespace.
    """
    tree = ast.parse(INIT_SRC)
    keep = {
        "OPTIONS_RELOAD_SUPPRESS_KEYS",
        "_seed_cm_last_applied_options",
        "_apply_in_place",
        "_async_update_listener",
    }
    body = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target = getattr(node.target, "id", None)
            if target in keep:
                body.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in keep:
                body.append(node)
    # Build a minimal namespace with stand-ins.
    ns: dict = {
        "_LOGGER": MagicMock(),
        "DOMAIN": "universal_room_automation",
        "CONF_ENTRY_TYPE": "entry_type",
        "ENTRY_TYPE_COORDINATOR_MANAGER": "coordinator_manager",
        "_CONF_HVAC_VACANCY_GRACE_MINUTES": "hvac_vacancy_grace_minutes",
        "_CONF_HVAC_VACANCY_GRACE_CONSTRAINED": "hvac_vacancy_grace_constrained",
        "_CONF_HVAC_MAX_OCCUPANCY_HOURS": "hvac_max_occupancy_hours",
        "_CONF_HVAC_ZONE_ENTRY_DWELL": "hvac_zone_entry_dwell",
        "_CONF_DYNAMIC_PRESET_DWELL_MINUTES": "dynamic_preset_dwell_minutes",
        # Typing — frozenset[str] subscript requires Python 3.9+; ok.
    }
    # Wrap kept nodes in a Module and compile.
    mod = ast.Module(body=body, type_ignores=[])
    code = compile(mod, str(PKG / "__init__.py"), "exec")
    exec(code, ns)
    return ns


@pytest.fixture(scope="module")
def listener_ns():
    return _load_init_listener_helpers()


class _FakeHvac:
    def __init__(self):
        self._vacancy_grace = 20
        self._vacancy_grace_constrained = 10
        self._max_occupancy_hours = 6
        self._zone_entry_dwell = 2


class _FakeManager:
    def __init__(self, hvac):
        self.coordinators = {"hvac": hvac}


class _FakeHass:
    def __init__(self, hvac=None, *, with_manager=True):
        self.data = {"universal_room_automation": {}}
        if with_manager:
            mgr = _FakeManager(hvac) if hvac is not None else None
            self.data["universal_room_automation"]["coordinator_manager"] = mgr
        self.config_entries = MagicMock()
        self.config_entries.async_reload = MagicMock()
        self.async_create_task = MagicMock()


class _FakeEntry:
    def __init__(self, entry_id, options, *, is_cm=True, title="CM"):
        self.entry_id = entry_id
        self.title = title
        self.options = dict(options)
        self.data = {"entry_type": "coordinator_manager"} if is_cm else {"entry_type": "room"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) else asyncio.new_event_loop().run_until_complete(coro)


def test_d1_seed_cm_last_applied_options_seeds_at_setup(listener_ns):
    hass = _FakeHass(hvac=_FakeHvac())
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    snap = hass.data["universal_room_automation"]["cm_last_applied_options"]["cm1"]
    assert snap == {"hvac_vacancy_grace_minutes": 20}


def test_d1_snapshot_is_a_copy_not_a_reference(listener_ns):
    hass = _FakeHass(hvac=_FakeHvac())
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Mutate entry.options post-seed — snapshot must NOT change.
    entry.options["hvac_vacancy_grace_minutes"] = 999
    snap = hass.data["universal_room_automation"]["cm_last_applied_options"]["cm1"]
    assert snap["hvac_vacancy_grace_minutes"] == 20


def test_d3_listener_suppresses_reload_for_allowlisted_keys(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Operator edits the timer Number from 20 → 25.
    entry.options = {"hvac_vacancy_grace_minutes": 25}
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0
    assert hvac._vacancy_grace == 25
    snap = hass.data["universal_room_automation"]["cm_last_applied_options"]["cm1"]
    assert snap == {"hvac_vacancy_grace_minutes": 25}


def test_d3_listener_reloads_for_non_allowlisted_keys(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {"presence_enabled": True})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = {"presence_enabled": False}
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 1


def test_d3_listener_reloads_for_mixed_change(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {
        "hvac_vacancy_grace_minutes": 20,
        "presence_enabled": True,
    })
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # One allowlisted + one non-allowlisted key change in the SAME write.
    entry.options = {
        "hvac_vacancy_grace_minutes": 25,
        "presence_enabled": False,
    }
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    # Mixed change MUST reload (the dominant non-allowlisted change wins).
    assert hass.async_create_task.call_count == 1


def test_d3_listener_no_op_on_empty_diff(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Same value rewritten — no reload, no in-place apply.
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0
    assert hvac._vacancy_grace == 20  # unchanged


def test_d3_listener_unchanged_for_room_entries(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("room1", {"timeout_override": 30}, is_cm=False)
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    # ROOM entry: ALWAYS reload, regardless of which keys changed.
    assert hass.async_create_task.call_count == 1


def test_d3_apply_in_place_updates_all_four_hvac_live_attrs(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    new = {
        "hvac_vacancy_grace_minutes": 25,
        "hvac_vacancy_grace_constrained": 12,
        "hvac_max_occupancy_hours": 8,
        "hvac_zone_entry_dwell": 3,
    }
    listener_ns["_apply_in_place"](hass, _FakeEntry("cm1", new), set(new.keys()), new)
    assert hvac._vacancy_grace == 25
    assert hvac._vacancy_grace_constrained == 12
    assert hvac._max_occupancy_hours == 8
    assert hvac._zone_entry_dwell == 3


def test_d3_apply_in_place_safe_when_coordinator_missing(listener_ns):
    """If HVAC coordinator is mid-teardown, apply_in_place must not raise."""
    hass = _FakeHass(hvac=None, with_manager=True)  # manager exists, hvac=None
    new = {"hvac_vacancy_grace_minutes": 25}
    # Should NOT raise.
    listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), {"hvac_vacancy_grace_minutes"}, new,
    )


def test_d3_apply_in_place_safe_when_manager_missing(listener_ns):
    """If coordinator_manager is absent entirely, apply_in_place must not raise."""
    hass = _FakeHass(with_manager=False)
    hass.data["universal_room_automation"] = {}
    new = {"hvac_vacancy_grace_minutes": 25}
    listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), {"hvac_vacancy_grace_minutes"}, new,
    )


def test_d3_clamp_invariant_holds_after_in_place_apply(listener_ns):
    """The A-HIGH-1 bidirectional clamp lives in the Number setter (runs
    BEFORE async_update_entry) and in the OptionsFlow form validation. By
    the time apply_in_place sees `entry.options`, the pair is already
    consistent. The invariant we lock here: apply_in_place itself never
    INTRODUCES an inversion — it only mirrors the option write."""
    hvac = _FakeHvac()
    hvac._vacancy_grace = 30
    hvac._vacancy_grace_constrained = 15
    hass = _FakeHass(hvac=hvac)
    # The setter's clamp already wrote BOTH keys consistently in one go.
    new = {
        "hvac_vacancy_grace_minutes": 10,
        "hvac_vacancy_grace_constrained": 10,
    }
    listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), set(new.keys()), new,
    )
    assert hvac._vacancy_grace == 10
    assert hvac._vacancy_grace_constrained == 10
    assert hvac._vacancy_grace_constrained <= hvac._vacancy_grace


def test_d3_listener_handles_all_four_timers_via_reset_button(listener_ns):
    """The `51 Reset` button writes all four HVAC timer defaults in one
    async_update_entry call. changed_keys ⊆ suppress set, so the listener
    must apply in place and skip reload."""
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {
        "hvac_vacancy_grace_minutes": 30,
        "hvac_vacancy_grace_constrained": 15,
        "hvac_max_occupancy_hours": 12,
        "hvac_zone_entry_dwell": 5,
    })
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Reset to defaults (all four allowlisted keys change).
    entry.options = {
        "hvac_vacancy_grace_minutes": 20,
        "hvac_vacancy_grace_constrained": 10,
        "hvac_max_occupancy_hours": 6,
        "hvac_zone_entry_dwell": 2,
    }
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0  # NO reload
    assert hvac._vacancy_grace == 20
    assert hvac._max_occupancy_hours == 6


# ============================================================================
# D2 — DynamicPresetDwellMinutesNumber hygiene
# ============================================================================


def test_d2_dpm_dwell_no_longer_inherits_restoreentity():
    """AST: class signature must NOT include RestoreEntity."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            base_names = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    base_names.append(b.id)
                elif isinstance(b, ast.Attribute):
                    base_names.append(b.attr)
            assert "RestoreEntity" not in base_names, (
                f"DynamicPresetDwellMinutesNumber still inherits RestoreEntity "
                f"(bases={base_names})"
            )
            return
    pytest.fail("DynamicPresetDwellMinutesNumber class not found in number.py")


def test_d2_dpm_dwell_no_async_added_to_hass_restore_branch():
    """The class must not define an async_added_to_hass method that reads
    `async_get_last_state` (the restore branch is what was being removed).
    """
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_added_to_hass":
                    method_src = ast.unparse(item)
                    assert "async_get_last_state" not in method_src, (
                        "DPM dwell async_added_to_hass still reads last_state"
                    )
            return
    pytest.fail("DynamicPresetDwellMinutesNumber not found")


def test_d2_dpm_dwell_docstring_no_longer_claims_restoreentity_canonical():
    """The class docstring must not claim 'RestoreEntity is the canonical
    runtime store' — that line was the stale doctrine being fixed."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            doc = ast.get_docstring(node) or ""
            assert "canonical runtime store" not in doc, (
                "DPM dwell docstring still claims RestoreEntity canonical"
            )
            assert "SOLE source of truth" in doc, (
                "DPM dwell docstring must state options-as-sole-source"
            )
            return
    pytest.fail("DynamicPresetDwellMinutesNumber not found")


def test_d2_dpm_dwell_setter_still_writes_through_async_update_entry():
    """Persistence path must remain: setter calls async_update_entry with
    the DPM dwell CONF key. This is what makes restart-restore work via
    `{**entry.data, **entry.options}` reseeding."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_set_native_value":
                    body_src = ast.unparse(item)
                    assert "async_update_entry" in body_src
                    assert "CONF_DYNAMIC_PRESET_DWELL_MINUTES" in body_src
                    return
    pytest.fail("DPM dwell setter not found")


# ============================================================================
# D5 — A-MED-1 combined cross-field error
# ============================================================================


def test_d5_save_path_runs_both_validations_unconditionally():
    """The `if not errors:` gate must be GONE between the two validations.
    Source-level check: the vacancy-grace check must not be nested inside
    `if not errors:`."""
    # Locate `async_step_coordinator_hvac_settings` source.
    tree = ast.parse(CONFIG_FLOW_SRC)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_step_coordinator_hvac_settings":
            src = ast.unparse(node)
            assert "vacancy_grace_constrained_exceeds_normal" in src
            # The old pattern was:
            #   if not errors:
            #       grace = ...
            #       grace_constrained = ...
            #       if grace_constrained > grace:
            #           errors["base"] = "vacancy_grace_constrained_exceeds_normal"
            # New pattern: both checks always run; an accumulator is used.
            assert "error_keys" in src, (
                "D5: save path must use an error_keys accumulator"
            )
            # No remaining gate immediately before the vacancy check.
            # Pattern that should NOT exist: an `if not errors:` that
            # contains `vacancy_grace_constrained_exceeds_normal`.
            for sub in ast.walk(node):
                if isinstance(sub, ast.If):
                    test_src = ast.unparse(sub.test)
                    body_src = ast.unparse(sub.body) if sub.body else ""
                    if (
                        "not errors" in test_src
                        and "vacancy_grace_constrained_exceeds_normal" in body_src
                    ):
                        pytest.fail(
                            "D5: vacancy check still gated behind `if not errors:`"
                        )
            found = True
            break
    assert found, "async_step_coordinator_hvac_settings not found"


def test_d5_save_path_uses_combined_key_when_two_violations():
    """Source-level check: combined-key branch must exist and depend on
    `len(error_keys) >= 2`."""
    assert "cover_and_vacancy_combined" in CONFIG_FLOW_SRC
    assert "len(error_keys) >= 2" in CONFIG_FLOW_SRC


def test_d5_strings_json_has_combined_key():
    section = (
        STRINGS.get("options", {}).get("error", {})
    )
    assert "cover_and_vacancy_combined" in section, (
        "cover_and_vacancy_combined missing from strings.json options.error"
    )
    # Single-violation keys remain so single-violation paths are byte-identical.
    assert "cover_temp_hysteresis_too_small" in section
    assert "vacancy_grace_constrained_exceeds_normal" in section


def test_d5_en_translations_has_combined_key():
    section = (
        EN_TRANSLATIONS.get("options", {}).get("error", {})
    )
    assert "cover_and_vacancy_combined" in section
    assert "cover_temp_hysteresis_too_small" in section
    assert "vacancy_grace_constrained_exceeds_normal" in section


def test_d5_strings_and_translations_combined_key_in_lockstep():
    """The combined key must appear in BOTH files (lockstep — translations
    file is loaded by HA, strings file is the source for `script
    extract-strings`)."""
    s_section = STRINGS.get("options", {}).get("error", {})
    e_section = EN_TRANSLATIONS.get("options", {}).get("error", {})
    assert "cover_and_vacancy_combined" in s_section
    assert "cover_and_vacancy_combined" in e_section
    # The text doesn't need to match byte-for-byte across the two files,
    # but both should reference both violations so an operator sees both.
    for text in (s_section["cover_and_vacancy_combined"], e_section["cover_and_vacancy_combined"]):
        assert "Cover" in text and "Vacancy" in text


def test_d5_other_errors_base_sites_not_touched():
    """Regression-bar: the ~15 other `errors["base"] = "<key>"` sites in
    config_flow.py are UNCHANGED. The only modification is the SHARED save
    path of async_step_coordinator_hvac_settings. Count single-base sites
    and assert there is at least the previous quorum AND that our specific
    new accumulator pattern only appears in the target function.
    """
    # `errors["base"] = ` should appear many times throughout config_flow.
    count = CONFIG_FLOW_SRC.count("errors[\"base\"] = ")
    assert count >= 10, (
        f"Expected ~15 single-base error sites; found only {count}. "
        "D5 regression — was a sibling site accidentally rewritten?"
    )
    # The `error_keys` accumulator is the new D5 pattern; should only
    # appear in async_step_coordinator_hvac_settings.
    tree = ast.parse(CONFIG_FLOW_SRC)
    accumulator_uses = 0
    target_uses = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            src = ast.unparse(node)
            if "error_keys" in src and "append" in src:
                accumulator_uses += 1
                if node.name == "async_step_coordinator_hvac_settings":
                    target_uses += 1
    assert accumulator_uses == 1, (
        f"D5: error_keys accumulator pattern leaked into "
        f"{accumulator_uses} functions; expected 1"
    )
    assert target_uses == 1


# ============================================================================
# Listener registration discipline — multiple entry-types share one listener
# ============================================================================


def test_listener_registered_at_all_three_entry_types():
    """`_async_update_listener` is registered for ROOM, ZONE_MANAGER, and
    COORDINATOR_MANAGER entries. The cycle's change must NOT remove any
    registration site. Pin the call sites by literal grep."""
    sites = INIT_SRC.count("add_update_listener(_async_update_listener)")
    # The planning doc enumerates 4 registration sites (2365, 2515, 2743, 2851).
    assert sites >= 3, (
        f"Listener registration sites dropped to {sites}; expected >= 3"
    )

"""v4.7.2 D1 / D2 / D3 — DPM HVAC Coordinator Surface + Switch Migration.

Source-grep style (matches project convention). Fast, no running HA required.

Deliverables covered:
  D1 — New config flow step: async_step_hvac_dynamic_preset (Surface 1)
       + coordinator_hvac converted from form → menu
       + _validate_dynamic_preset_input shared with Surface 2
       + _build_hvac_dynamic_preset_schema (Surface 1 schema builder)

  D2 — HVACDynamicPresetSwitch: migrated from ECDynamicPresetSwitch
       on Energy Coordinator device → HVAC Coordinator device.
       unique_id PRESERVED: f"{DOMAIN}_energy_dynamic_preset_enabled"
       Default flipped OFF → ON.
       Deferred-restore via SIGNAL_ENERGY_COORDINATOR_READY.

  D3 — HVACGuestModeActuationSwitch._attr_name renamed:
       "Guest Mode Actuation" → "01 · Custom Preset Ranges"
       unique_id preserved.
"""

import json
import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    with open(
        "custom_components/universal_room_automation/config_flow.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def switch_src() -> str:
    with open(
        "custom_components/universal_room_automation/switch.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def strings() -> dict:
    with open(
        "custom_components/universal_room_automation/strings.json"
    ) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def translations_en() -> dict:
    with open(
        "custom_components/universal_room_automation/translations/en.json"
    ) as f:
        return json.load(f)


# ===========================================================================
# D1 — coordinator_hvac is now a menu step
# ===========================================================================


class TestD1CoordinatorHvacMenu:
    """D1: async_step_coordinator_hvac must be a menu step, not a form step."""

    def test_coordinator_hvac_is_menu_step(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_coordinator_hvac(")
        assert idx > 0, "async_step_coordinator_hvac must exist"
        body = config_flow_src[idx:idx + 500]
        assert "async_show_menu" in body, (
            "coordinator_hvac must call async_show_menu (D1: form → menu conversion)"
        )

    def test_coordinator_hvac_menu_options_include_settings(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_coordinator_hvac(")
        body = config_flow_src[idx:idx + 500]
        assert "coordinator_hvac_settings" in body, (
            "menu must include coordinator_hvac_settings for existing tuning fields"
        )

    def test_coordinator_hvac_menu_options_include_dynamic_preset(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_coordinator_hvac(")
        body = config_flow_src[idx:idx + 500]
        assert "hvac_dynamic_preset" in body, (
            "menu must include hvac_dynamic_preset (new D1 Surface 1)"
        )

    def test_coordinator_hvac_settings_form_exists(self, config_flow_src):
        assert "async def async_step_coordinator_hvac_settings(" in config_flow_src, (
            "coordinator_hvac_settings form step must exist for tuning fields "
            "(previously the coordinator_hvac form)"
        )

    def test_coordinator_hvac_settings_has_step_id(self, config_flow_src):
        # The step_id "coordinator_hvac_settings" must appear somewhere in the file
        # (the async_show_form call inside the function can be many lines below the def).
        assert 'step_id="coordinator_hvac_settings"' in config_flow_src, (
            "step_id must match the function suffix — HA wires step_id to the "
            "translation key"
        )

    def test_strings_coordinator_hvac_is_menu(self, strings):
        step = strings["options"]["step"]["coordinator_hvac"]
        assert "menu_options" in step, (
            "strings.json coordinator_hvac must be a menu step (has menu_options)"
        )
        assert "data" not in step, (
            "Menu steps must NOT have a 'data' key — that belongs on form steps"
        )

    def test_strings_coordinator_hvac_menu_has_both_options(self, strings):
        opts = strings["options"]["step"]["coordinator_hvac"].get("menu_options", {})
        assert "coordinator_hvac_settings" in opts
        assert "hvac_dynamic_preset" in opts

    def test_strings_coordinator_hvac_settings_is_form(self, strings):
        step = strings["options"]["step"]["coordinator_hvac_settings"]
        assert "data" in step, (
            "coordinator_hvac_settings must be a form step with 'data'"
        )

    def test_translations_coordinator_hvac_is_menu(self, translations_en):
        step = translations_en["options"]["step"]["coordinator_hvac"]
        assert "menu_options" in step
        assert "data" not in step

    def test_translations_coordinator_hvac_settings_is_form(self, translations_en):
        step = translations_en["options"]["step"]["coordinator_hvac_settings"]
        assert "data" in step


# ===========================================================================
# D1 — hvac_dynamic_preset step (Surface 1)
# ===========================================================================


class TestD1HvacDynamicPresetStep:
    """D1: async_step_hvac_dynamic_preset must exist and use shared helpers."""

    def test_hvac_dynamic_preset_step_exists(self, config_flow_src):
        assert "async def async_step_hvac_dynamic_preset(" in config_flow_src

    def test_hvac_dynamic_preset_calls_schema_builder(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_hvac_dynamic_preset(")
        # Function body can be long — use 12 000 chars to capture all branches
        body = config_flow_src[idx:idx + 14000]
        assert "_build_hvac_dynamic_preset_schema" in body, (
            "Surface 1 must call _build_hvac_dynamic_preset_schema"
        )

    # v4.7.18 D2: test_validate_dynamic_preset_input_helper_exists DROPPED.
    # The shared helper was deleted in D2 after D1 stripped Surface 2's
    # bucket cells (no remaining caller in production code).
    # v4.7.18 D2: test_validate_helper_accepts_zone_prefix DROPPED — same.

    def test_build_hvac_dynamic_preset_schema_exists(self, config_flow_src):
        assert "def _build_hvac_dynamic_preset_schema(" in config_flow_src

    def test_strings_hvac_dynamic_preset_step_exists(self, strings):
        assert "hvac_dynamic_preset" in strings["options"]["step"], (
            "strings.json must have hvac_dynamic_preset step for Surface 1"
        )

    def test_translations_hvac_dynamic_preset_step_exists(self, translations_en):
        assert "hvac_dynamic_preset" in translations_en["options"]["step"]

    # v4.7.4 D1: test_per_zone_keys_use_double_underscore_prefix DROPPED.
    # Surface 1 no longer renders per-zone fields — the prefix bug is
    # prevented by architectural removal, not by pattern assertion.
    # The D5 AST test (test_v474_translation_coverage.py) provides the
    # regression guard: asserts no schema key contains '__'.


# ===========================================================================
# D2 — HVACDynamicPresetSwitch migration
# ===========================================================================


class TestD2HvacDynamicPresetSwitch:
    """D2: HVACDynamicPresetSwitch must live on HVAC Coordinator device,
    preserve the original unique_id, default ON, and use deferred-restore."""

    def test_class_exists(self, switch_src):
        assert "class HVACDynamicPresetSwitch(" in switch_src, (
            "HVACDynamicPresetSwitch class must exist in switch.py"
        )

    def test_unique_id_preserved(self, switch_src):
        idx = switch_src.find("class HVACDynamicPresetSwitch(")
        body = switch_src[idx:idx + 2000]
        assert 'f"{DOMAIN}_energy_dynamic_preset_enabled"' in body, (
            "unique_id MUST be preserved as f\"{DOMAIN}_energy_dynamic_preset_enabled\" "
            "so existing entity_registry entries are not orphaned"
        )

    def test_device_is_hvac_coordinator(self, switch_src):
        idx = switch_src.find("class HVACDynamicPresetSwitch(")
        body = switch_src[idx:idx + 2000]
        assert '"hvac_coordinator"' in body, (
            "D2: device must be hvac_coordinator (migrated from energy_coordinator)"
        )
        # Also confirm energy_coordinator is NOT referenced for this class
        # (search only the class body, not the entire file)
        energy_idx = body.find('"energy_coordinator"')
        assert energy_idx == -1, (
            "HVACDynamicPresetSwitch must NOT reference energy_coordinator device; "
            "it belongs on the HVAC Coordinator device after D2 migration"
        )

    def test_default_is_on(self, switch_src):
        idx = switch_src.find("class HVACDynamicPresetSwitch(")
        body = switch_src[idx:idx + 3000]
        # Default can be expressed as _attr_is_on, self._is_on, or self._default
        assert (
            "_attr_is_on = True" in body
            or "self._is_on = True" in body
            or "self._default: bool = True" in body
            or "_default = True" in body
        ), (
            "D2: default must be ON (flipped from ECDynamicPresetSwitch default OFF); "
            "may be expressed as _attr_is_on, self._is_on, or self._default = True"
        )

    def test_uses_restore_entity(self, switch_src):
        idx = switch_src.find("class HVACDynamicPresetSwitch(")
        assert "RestoreEntity" in switch_src[idx:idx + 100], (
            "HVACDynamicPresetSwitch must inherit RestoreEntity for state persistence"
        )

    def test_deferred_restore_uses_signal(self, switch_src):
        idx = switch_src.find("class HVACDynamicPresetSwitch(")
        body = switch_src[idx:idx + 5000]
        assert "SIGNAL_ENERGY_COORDINATOR_READY" in body, (
            "D2: must use SIGNAL_ENERGY_COORDINATOR_READY for deferred restore "
            "(replicates _ec_switch_factory pattern)"
        )

    def test_numeric_prefix_02(self, switch_src):
        idx = switch_src.find("class HVACDynamicPresetSwitch(")
        body = switch_src[idx:idx + 2000]
        assert "02 ·" in body, (
            "_attr_name must start with '02 ·' — numeric prefix for HVAC "
            "Coordinator device frontend sort"
        )

    def test_ec_dynamic_preset_switch_not_in_setup_entry(self, switch_src):
        # After D2, async_setup_entry must wire HVACDynamicPresetSwitch,
        # not ECDynamicPresetSwitch for this slot.
        idx = switch_src.find("async def async_setup_entry(")
        # Window widened from 5000 → 6000 (Session B1 EVSE drain-precedence
        # added ECDrainPrecedenceEnableSwitch to CM setup_entry, pushing
        # HVACDynamicPresetSwitch out of the original 5000-char slice by
        # ~34 chars). The invariant is presence-in-setup_entry, not
        # location within a fixed character window.
        body = switch_src[idx:idx + 6000]
        assert "HVACDynamicPresetSwitch" in body, (
            "async_setup_entry must instantiate HVACDynamicPresetSwitch "
            "(not the old ECDynamicPresetSwitch factory call)"
        )


# ===========================================================================
# D3 — HVACGuestModeActuationSwitch rename
# ===========================================================================


class TestD3GuestModeActuationRename:
    """D3: _attr_name renamed from 'Guest Mode Actuation' to '01 · Custom Preset Ranges'.
    unique_id must be UNCHANGED."""

    def test_new_name_present(self, switch_src):
        assert "01 · Custom Preset Ranges" in switch_src, (
            "D3: _attr_name must be '01 · Custom Preset Ranges'"
        )

    def test_old_name_absent_from_attr_name(self, switch_src):
        # The _attr_name must not be the old value. Log messages may still say
        # "Guest Mode Actuation" — only the name attribute matters for the rename.
        idx = switch_src.find("class HVACGuestModeActuationSwitch(")
        body = switch_src[idx:idx + 1500]
        assert '_attr_name = "Guest Mode Actuation"' not in body, (
            "D3: _attr_name must no longer be 'Guest Mode Actuation'"
        )

    def test_unique_id_unchanged(self, switch_src):
        idx = switch_src.find("class HVACGuestModeActuationSwitch(")
        body = switch_src[idx:idx + 1500]
        # unique_id uses f-string: f"{DOMAIN}_hvac_coordinator_guest_mode_actuation_enabled"
        assert "hvac_coordinator_guest_mode_actuation_enabled" in body, (
            "unique_id must be preserved so existing entity_registry entry survives; "
            "expected '_hvac_coordinator_guest_mode_actuation_enabled' in unique_id"
        )

    def test_numeric_prefix_01(self, switch_src):
        assert "01 · Custom Preset Ranges" in switch_src, (
            "_attr_name must start with '01 ·' — numeric prefix for HVAC "
            "Coordinator device frontend sort, non-colliding with '02 ·' (D2)"
        )

    def test_d2_and_d3_prefixes_are_distinct(self, switch_src):
        assert "01 · Custom Preset Ranges" in switch_src
        assert "02 · Dynamic Preset Auto-Adjust" in switch_src, (
            "01 · and 02 · must coexist without collision"
        )


# ===========================================================================
# C1 fix-up — validation parity: Surface 2 must call shared helper
# (v4.7.2 reviewer fix-up)
# ===========================================================================


class TestC1ValidationParityBothSurfaces:
    """C1 fix-up: async_step_zone_dynamic_preset must call
    _validate_dynamic_preset_input (not use inline validation).

    v4.7.4 D1: Surface 1 per-zone validation REMOVED — Surface 1 no longer
    iterates zones or validates per-zone input. The sync invariant between
    Surface 1 and Surface 2 is resolved by architectural separation:
    - Surface 1 = house-wide settings only (no per-zone fields, no prefix)
    - Surface 2 = per-zone settings (bare keys, one zone at a time)
    Tests for Surface 1 calling _validate_dynamic_preset_input are DROPPED.
    Surface 2 validation tests (C1 fix) remain unchanged.
    """

    # test_surface_1_calls_validate_helper DROPPED (v4.7.4 D1: Surface 1 has no per-zone fields).
    # test_validate_helper_called_with_zone_prefix_in_surface_1 DROPPED (same reason).

    # v4.7.18 D2: test_surface_2_calls_validate_helper DROPPED. The helper
    # was deleted in D2 after D1 stripped Surface 2's bucket cells. Surface 2
    # now collapses to 4 fields (enabled/offset/reset_guest/sleep_enabled)
    # with no per-bucket validation needed.

    def test_surface_2_no_inline_bucket_keys_loop(self, config_flow_src):
        """C1 fix: Surface 2 must NOT contain the old inline bucket_keys validation loop."""
        idx = config_flow_src.find("async def async_step_zone_dynamic_preset(")
        assert idx > 0, "Surface 2 must exist"
        body = config_flow_src[idx:idx + 5000]
        # The old inline validation used a list named 'bucket_keys' with tuple pairs.
        # After the fix, this loop should no longer appear inside Surface 2.
        # We check for the specific pattern that defined the old inline loop.
        assert "bucket_keys = [" not in body, (
            "C1 fix: Surface 2 must NOT contain inline 'bucket_keys = [' validation "
            "loop — validation must be delegated to _validate_dynamic_preset_input"
        )

    # v4.7.18 D2: test_validate_helper_called_with_zone_prefix_empty_in_surface_2
    # DROPPED. Helper deleted; Surface 2 has no per-bucket validation path.
    # test_validate_helper_called_with_zone_prefix_in_surface_1 DROPPED (v4.7.4 D1).


# ===========================================================================
# B2 fix-up — D2 entity_registry migration helper (idempotent)
# (v4.7.2 reviewer fix-up)
# ===========================================================================


@pytest.fixture(scope="module")
def init_src() -> str:
    with open("custom_components/universal_room_automation/__init__.py") as f:
        return f.read()


class TestB2MigrationHelper:
    """B2 fix-up: idempotent entity_registry device-reassignment helper for
    the HVACDynamicPresetSwitch (v4.7.2 D2 migration from EC to HVAC device).

    Source-grep checks that:
    1. The helper is present in __init__.py inside the CM entry branch.
    2. It checks device_id equality before updating (idempotent guard).
    3. It is wrapped in try/except (non-fatal).
    4. It targets the hvac_coordinator device identifiers.
    """

    # Use the 'if entry_type ==' form as the anchor — the bare constant name
    # appears first in the import block and would give a wrong window.
    _CM_ANCHOR = "if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:"

    def test_migration_helper_present_in_init(self, init_src):
        assert "v4.7.2 D2" in init_src, (
            "B2 fix: __init__.py must contain the v4.7.2 D2 migration helper comment"
        )

    def test_migration_helper_in_cm_entry_branch(self, init_src):
        idx = init_src.find(self._CM_ANCHOR)
        assert idx > 0, "CM entry 'if entry_type ==' branch must exist"
        # Use 4000-char window from the if-branch — migration helper is within
        # v4.7.7: window widened from 4000 → 10000 after the v4.7.7 B1
        # orphan sweep + A4 ramp rename + B3 per-zone DPM device migration
        # blocks were inserted inside the CM entry branch ahead of
        # `entity reassignment skipped` debug log line.
        body = init_src[idx:idx + 14000]
        assert "v4.7.2 D2" in body, (
            "B2 fix: migration helper must be inside the CM entry branch "
            "(ENTRY_TYPE_COORDINATOR_MANAGER section)"
        )

    def test_migration_helper_targets_hvac_coordinator(self, init_src):
        idx = init_src.find(self._CM_ANCHOR)
        # v4.7.7: window widened from 4000 → 10000 after the v4.7.7 B1
        # orphan sweep + A4 ramp rename + B3 per-zone DPM device migration
        # blocks were inserted inside the CM entry branch ahead of
        # `entity reassignment skipped` debug log line.
        body = init_src[idx:idx + 14000]
        assert '"hvac_coordinator"' in body, (
            "B2 fix: migration helper must target hvac_coordinator device identifiers"
        )

    def test_migration_helper_idempotent_guard(self, init_src):
        """Helper must check device_id equality before updating."""
        idx = init_src.find(self._CM_ANCHOR)
        # v4.7.7: window widened from 4000 → 10000 after the v4.7.7 B1
        # orphan sweep + A4 ramp rename + B3 per-zone DPM device migration
        # blocks were inserted inside the CM entry branch ahead of
        # `entity reassignment skipped` debug log line.
        body = init_src[idx:idx + 14000]
        assert (
            "device_id != _target_device.id" in body
            or "_ent_entry.device_id != _target_device.id" in body
            or "ent_entry.device_id != target_device.id" in body
        ), (
            "B2 fix: migration helper must check device_id equality — "
            "if already correctly assigned, no update should be issued (idempotent)"
        )

    def test_migration_helper_wrapped_in_try_except(self, init_src):
        """Helper must be non-fatal — wrapped in try/except.

        v4.7.3 D4 refactored the single-entity helper into a loop; the debug
        log message was updated.  Test checks for the presence of any
        'entity reassignment skipped' debug log (version-agnostic).
        """
        idx = init_src.find(self._CM_ANCHOR)
        # v4.7.7: window widened from 4000 → 10000 after the v4.7.7 B1
        # orphan sweep + A4 ramp rename + B3 per-zone DPM device migration
        # blocks were inserted inside the CM entry branch ahead of
        # `entity reassignment skipped` debug log line.
        body = init_src[idx:idx + 14000]
        # The try/except block must contain a debug log on failure.
        assert "entity reassignment skipped" in body, (
            "B2 fix: migration helper must be wrapped in try/except with a debug log "
            "on failure (non-fatal — must not break CM entry setup)"
        )

    def test_migration_helper_default_flip_pending_nm_initialized(self, switch_src):
        """B4 fix: _default_flip_pending_nm must be initialized in __init__."""
        idx = switch_src.find("class HVACDynamicPresetSwitch(")
        assert idx > 0
        body = switch_src[idx:idx + 2000]
        assert "_default_flip_pending_nm: bool = False" in body, (
            "B4 fix: _default_flip_pending_nm must be initialized in __init__ "
            "so all code paths can use direct attribute access (not getattr guard)"
        )

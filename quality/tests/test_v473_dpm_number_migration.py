"""v4.7.3 D4 — DPM Number Entity Migration from EC → HVAC Coordinator device.

Source-grep + import style. Fast, no running HA required.

Deliverables covered:
  D4 — DynamicPresetDwellMinutesNumber.DeviceInfo.identifiers → hvac_coordinator
       DynamicPresetHysteresisFNumber.DeviceInfo.identifiers  → hvac_coordinator
       Both _attr_name prefixed 03· / 04· for device-page sort
       Both unique_ids PRESERVED (entity_id stability)
       __init__.py migration helper extended to loop over 3 unique_ids
"""

import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def number_src() -> str:
    with open(
        "custom_components/universal_room_automation/number.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def init_src() -> str:
    with open(
        "custom_components/universal_room_automation/__init__.py"
    ) as f:
        return f.read()


# ===========================================================================
# D4 — DynamicPresetDwellMinutesNumber
# ===========================================================================


class TestD4DwellEntityOnHvacDevice:
    """D4: DynamicPresetDwellMinutesNumber must live on hvac_coordinator device."""

    def test_dwell_device_identifiers_hvac_coordinator(self, number_src):
        """DeviceInfo.identifiers must use hvac_coordinator, not energy_coordinator."""
        idx = number_src.find("class DynamicPresetDwellMinutesNumber(")
        assert idx > 0, "DynamicPresetDwellMinutesNumber must exist in number.py"
        body = number_src[idx:idx + 1500]
        assert '"hvac_coordinator"' in body or "'hvac_coordinator'" in body, (
            "D4: DynamicPresetDwellMinutesNumber.DeviceInfo.identifiers must use 'hvac_coordinator'"
        )
        assert '"energy_coordinator"' not in body and "'energy_coordinator'" not in body, (
            "D4: DynamicPresetDwellMinutesNumber must NOT reference 'energy_coordinator' in identifiers"
        )

    def test_dwell_unique_id_preserved(self, number_src):
        """unique_id must be the v4.7.1 value — DOMAIN + '_energy_dynamic_preset_dwell_minutes'."""
        idx = number_src.find("class DynamicPresetDwellMinutesNumber(")
        body = number_src[idx:idx + 1500]
        assert "_energy_dynamic_preset_dwell_minutes" in body, (
            "D4: DynamicPresetDwellMinutesNumber unique_id must be preserved "
            "(f'{DOMAIN}_energy_dynamic_preset_dwell_minutes')"
        )

    def test_dwell_attr_name_has_03_prefix(self, number_src):
        """_attr_name must start with '03 · ' for numeric sort on HVAC Coordinator device page."""
        idx = number_src.find("class DynamicPresetDwellMinutesNumber(")
        body = number_src[idx:idx + 1500]
        assert "03 ·" in body or "03 ·" in body, (
            "D4: DynamicPresetDwellMinutesNumber._attr_name must include '03 ·' prefix"
        )

    def test_dwell_device_name_is_hvac_coordinator(self, number_src):
        """Device name must be 'URA: HVAC Coordinator'."""
        idx = number_src.find("class DynamicPresetDwellMinutesNumber(")
        body = number_src[idx:idx + 1500]
        assert "URA: HVAC Coordinator" in body, (
            "D4: DynamicPresetDwellMinutesNumber device name must be 'URA: HVAC Coordinator'"
        )


# ===========================================================================
# D4 — DynamicPresetHysteresisFNumber
# ===========================================================================


class TestD4HysteresisEntityOnHvacDevice:
    """D4: DynamicPresetHysteresisFNumber must live on hvac_coordinator device."""

    def test_hysteresis_device_identifiers_hvac_coordinator(self, number_src):
        idx = number_src.find("class DynamicPresetHysteresisFNumber(")
        assert idx > 0, "DynamicPresetHysteresisFNumber must exist in number.py"
        body = number_src[idx:idx + 1500]
        assert '"hvac_coordinator"' in body or "'hvac_coordinator'" in body, (
            "D4: DynamicPresetHysteresisFNumber.DeviceInfo.identifiers must use 'hvac_coordinator'"
        )
        assert '"energy_coordinator"' not in body and "'energy_coordinator'" not in body, (
            "D4: DynamicPresetHysteresisFNumber must NOT reference 'energy_coordinator' in identifiers"
        )

    def test_hysteresis_unique_id_preserved(self, number_src):
        """unique_id must be the v4.7.1 value — DOMAIN + '_energy_dynamic_preset_hysteresis_f'."""
        idx = number_src.find("class DynamicPresetHysteresisFNumber(")
        body = number_src[idx:idx + 1500]
        assert "_energy_dynamic_preset_hysteresis_f" in body, (
            "D4: DynamicPresetHysteresisFNumber unique_id must be preserved "
            "(f'{DOMAIN}_energy_dynamic_preset_hysteresis_f')"
        )

    def test_hysteresis_attr_name_has_04_prefix(self, number_src):
        """_attr_name must start with '04 · ' for numeric sort on HVAC Coordinator device page."""
        idx = number_src.find("class DynamicPresetHysteresisFNumber(")
        body = number_src[idx:idx + 1500]
        assert "04 ·" in body or "04 ·" in body, (
            "D4: DynamicPresetHysteresisFNumber._attr_name must include '04 ·' prefix"
        )

    def test_hysteresis_device_name_is_hvac_coordinator(self, number_src):
        idx = number_src.find("class DynamicPresetHysteresisFNumber(")
        body = number_src[idx:idx + 1500]
        assert "URA: HVAC Coordinator" in body, (
            "D4: DynamicPresetHysteresisFNumber device name must be 'URA: HVAC Coordinator'"
        )


# ===========================================================================
# D4 — unique_id values byte-for-byte
# ===========================================================================


class TestD4UniqueIdsPreserved:
    """D4: Both unique_id strings must match the v4.7.1 values exactly."""

    def test_dwell_unique_id_string(self):
        """DynamicPresetDwellMinutesNumber unique_id string bytes unchanged from v4.7.1."""
        # Source-grep only — no HA import needed
        with open("custom_components/universal_room_automation/number.py") as f:
            src = f.read()
        assert '_energy_dynamic_preset_dwell_minutes"' in src, (
            "unique_id string '_energy_dynamic_preset_dwell_minutes' not found in number.py"
        )

    def test_hysteresis_unique_id_string(self):
        """DynamicPresetHysteresisFNumber unique_id string bytes unchanged from v4.7.1."""
        with open("custom_components/universal_room_automation/number.py") as f:
            src = f.read()
        assert '_energy_dynamic_preset_hysteresis_f"' in src, (
            "unique_id string '_energy_dynamic_preset_hysteresis_f' not found in number.py"
        )


# ===========================================================================
# D4 — __init__.py migration helper covers all 3 entities
# ===========================================================================


class TestD4MigrationHelperHandlesAllThreeEntities:
    """D4: The __init__.py migration helper must iterate over 3 unique_ids via a loop."""

    def test_migration_helper_is_loop_not_single_entity(self, init_src):
        """The helper must use a list/loop, not single-entity inline code."""
        assert "_HVAC_DEVICE_MIGRATIONS" in init_src, (
            "D4: __init__.py must define _HVAC_DEVICE_MIGRATIONS list of (platform, unique_id) tuples"
        )

    def test_migration_helper_includes_switch_unique_id(self, init_src):
        """Migration list must include the v4.7.2 switch unique_id."""
        assert "_energy_dynamic_preset_enabled" in init_src, (
            "D4: migration list must include '_energy_dynamic_preset_enabled' (v4.7.2 D2 switch)"
        )

    def test_migration_helper_includes_dwell_unique_id(self, init_src):
        """Migration list must include the dwell number unique_id."""
        assert "_energy_dynamic_preset_dwell_minutes" in init_src, (
            "D4: migration list must include '_energy_dynamic_preset_dwell_minutes'"
        )

    def test_migration_helper_includes_hysteresis_unique_id(self, init_src):
        """Migration list must include the hysteresis number unique_id."""
        assert "_energy_dynamic_preset_hysteresis_f" in init_src, (
            "D4: migration list must include '_energy_dynamic_preset_hysteresis_f'"
        )

    def test_migration_helper_uses_async_get_entity_id_pattern(self, init_src):
        """D4: entity lookup must use async_get_entity_id (critical per v4.7.2 B2 lesson)."""
        idx = init_src.find("_HVAC_DEVICE_MIGRATIONS")
        assert idx > 0
        body = init_src[idx:idx + 2000]
        assert "async_get_entity_id" in body, (
            "D4: migration helper must use async_get_entity_id to look up entity_id from unique_id. "
            "entity_id is NOT predictable from unique_id — lesson from v4.7.2 B2 reviewer fix-up."
        )

    def test_migration_helper_iterates_over_list(self, init_src):
        """Loop pattern: must iterate over the migration list."""
        idx = init_src.find("_HVAC_DEVICE_MIGRATIONS")
        body = init_src[idx:idx + 2000]
        assert "for _platform, _unique_id in _HVAC_DEVICE_MIGRATIONS" in body, (
            "D4: migration helper must iterate over _HVAC_DEVICE_MIGRATIONS with "
            "'for _platform, _unique_id in _HVAC_DEVICE_MIGRATIONS'"
        )

    def test_migration_helper_list_has_three_entries(self, init_src):
        """Migration list must contain exactly 3 tuples."""
        import re
        idx = init_src.find("_HVAC_DEVICE_MIGRATIONS = [")
        assert idx > 0, "_HVAC_DEVICE_MIGRATIONS must be assigned as a list"
        bracket_start = init_src.find("[", idx)
        bracket_end = init_src.find("]", bracket_start)
        list_src = init_src[bracket_start:bracket_end + 1]
        # Count entries by counting tuple open-parens
        entry_count = list_src.count("(\"")
        assert entry_count == 3, (
            f"D4: _HVAC_DEVICE_MIGRATIONS must have exactly 3 entries, found {entry_count}"
        )

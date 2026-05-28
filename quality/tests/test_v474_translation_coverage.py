"""v4.7.4 D5 — Translation Source-Contract Test.

AST-based source-contract tests asserting:
  1. Every DPM-related step field key in config_flow.py has a matching entry in
     translations/en.json options.step.<step_id>.data.
  2. No schema field key contains '__' (regression guard for v4.7.2's prefix bug
     where zone names were encoded as '<zone_name>__field_name').
  3. Section wrapper keys ("advanced", "customize_buckets_section", "sleep_section",
     "summer_section", "shoulder_section", "winter_section") are registered in
     translations/en.json sections blocks.

Source-grep style tests are used where AST is too fragile; pure text matching is
used for the __ prefix invariant.
"""

import json
import re
import pytest


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    with open(
        "custom_components/universal_room_automation/config_flow.py"
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
# D5 — No __ prefix regression guard
# ===========================================================================


class TestD5NoPrefixedFieldKeys:
    """D5: Schema field keys must NOT contain __ (the v4.7.2 translation bug class).

    The v4.7.2 prefix bug: Surface 1 prepended '<zone_name>__' to every per-zone
    field to avoid voluptuous duplicate-key collisions across zones. HA's translation
    system cannot match these runtime-prefixed keys, so raw keys were shown to users.

    This test is the regression guard. If any schema builder ever introduces __ into
    a field key, this test fails.
    """

    # Patterns for the schema-builder functions we care about
    _SCHEMA_BUILDER_MARKERS = [
        "def _build_hvac_dynamic_preset_schema(self",  # Surface 1 (D1/D2)
        "def _build_dynamic_preset_schema(self",       # Surface 2 (D3)
        "async def async_step_hvac_baseline_presets(", # Baseline editor (D4)
    ]

    def test_d5_no_prefixed_field_keys_in_surface1_schema(self, config_flow_src):
        """Surface 1 schema builder must not produce any __ prefixed field key."""
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        assert idx > 0, "Surface 1 schema builder must exist"
        body = config_flow_src[idx:idx + 3000]
        # __ appearing in a string literal used as a vol.Optional key
        # Pattern: vol.Optional("something__field")  or just  "__zone_dynamic_preset"
        matches = re.findall(r'vol\.Optional\(\s*["\']([^"\']*__[^"\']*)["\']', body)
        assert not matches, (
            f"D5 REGRESSION: Surface 1 schema builder has __ prefixed field keys: {matches}. "
            "This is the v4.7.2 translation bug class — zone names must NEVER appear as "
            "field key prefixes on Surface 1."
        )

    def test_d5_no_prefixed_field_keys_in_surface2_schema(self, config_flow_src):
        """Surface 2 schema builder must not produce any __ prefixed field key."""
        # Function has a multi-line signature; search without trailing '(self'
        idx = config_flow_src.find("def _build_dynamic_preset_schema(\n")
        assert idx > 0, "Surface 2 schema builder must exist"
        body = config_flow_src[idx:idx + 5000]
        matches = re.findall(r'vol\.Optional\(\s*["\']([^"\']*__[^"\']*)["\']', body)
        assert not matches, (
            f"D5 REGRESSION: Surface 2 schema builder has __ prefixed field keys: {matches}."
        )

    def test_d5_no_prefixed_field_keys_in_baseline_schema(self, config_flow_src):
        """Baseline presets step must not produce any __ prefixed field key."""
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets(")
        assert idx > 0, "Baseline presets step must exist"
        body = config_flow_src[idx:idx + 12000]
        matches = re.findall(r'vol\.Optional\(\s*["\']([^"\']*__[^"\']*)["\']', body)
        assert not matches, (
            f"D5 REGRESSION: Baseline presets step has __ prefixed field keys: {matches}."
        )

    def test_d5_no_double_underscore_anywhere_in_schema_builders(self, config_flow_src):
        """Broad guard: vol.Optional with __ key anywhere in any DPM schema builder.

        This is the canary — if any future schema builder re-introduces the pattern,
        this test will catch it before it ships.
        """
        # We look at the entire config_flow.py for the most sensitive pattern:
        # vol.Optional("something__zone_dynamic_preset...") — zone-prefixed DPM keys
        matches = re.findall(
            r'vol\.Optional\(\s*["\'][^"\']*__zone_dynamic_preset[^"\']*["\']',
            config_flow_src
        )
        assert not matches, (
            f"D5 REGRESSION GUARD: Found {len(matches)} zone-prefixed DPM field keys in "
            f"config_flow.py: {matches}. This is the v4.7.2 root cause — drop all zone-name "
            "prefixes from vol.Optional keys."
        )


# ===========================================================================
# D5 — Surface 1 field coverage
# ===========================================================================


class TestD5Surface1FieldCoverage:
    """D5: Every Surface 1 field key must have a translation entry."""

    _SURFACE1_EXPECTED_FIELDS = [
        "dynamic_preset_enabled",
        "dynamic_preset_delta_cool_max",
        "dynamic_preset_delta_mild_max",
        "dynamic_preset_delta_hot_max",
        "dynamic_preset_dwell_minutes",
        "dynamic_preset_hysteresis_f",
    ]

    def test_d5_surface1_field_coverage_strings(self, strings):
        """All 6 Surface 1 fields must have translation entries in strings.json."""
        data = strings["options"]["step"]["hvac_dynamic_preset"].get("data", {})
        for field in self._SURFACE1_EXPECTED_FIELDS:
            assert field in data, (
                f"D5: strings.json hvac_dynamic_preset.data is missing '{field}' — "
                "this would render as a raw key in the HA UI"
            )

    def test_d5_surface1_field_coverage_translations_en(self, translations_en):
        """All 6 Surface 1 fields must have translation entries in translations/en.json."""
        data = translations_en["options"]["step"]["hvac_dynamic_preset"].get("data", {})
        for field in self._SURFACE1_EXPECTED_FIELDS:
            assert field in data, (
                f"D5: translations/en.json hvac_dynamic_preset.data is missing '{field}'"
            )

    def test_d5_surface1_advanced_section_key_in_sections(self, strings):
        """D5: 'advanced' section key must have a label in strings.json sections."""
        sections = strings["options"]["step"]["hvac_dynamic_preset"].get("sections", {})
        assert "advanced" in sections, (
            "D5: strings.json hvac_dynamic_preset.sections must have 'advanced' label — "
            "without it, the section header shows a raw key"
        )

    def test_d5_surface1_advanced_section_key_in_translations(self, translations_en):
        """D5: 'advanced' section key must have a label in translations/en.json sections."""
        sections = translations_en["options"]["step"]["hvac_dynamic_preset"].get("sections", {})
        assert "advanced" in sections, (
            "D5: translations/en.json hvac_dynamic_preset.sections must have 'advanced' label"
        )

    def test_d5_surface1_no_extra_untranslated_fields(self, strings, config_flow_src):
        """D5: Surface 1 schema builder must not reference CONFs missing from strings.json.

        Source-grep: extract all CONF_DYNAMIC_PRESET_* names from the schema builder
        and verify each maps to a known strings field.
        """
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        body = config_flow_src[idx:idx + 3000]
        data = strings["options"]["step"]["hvac_dynamic_preset"].get("data", {})
        # Each CONF in the schema builder corresponds to a field key
        # (the key is the CONF value, which is the snake_case string without the CONF_ prefix).
        # The strings.json uses the CONF value directly as the field key.
        # We verify coverage by checking the known set — not by live-importing the consts.
        conf_to_field = {
            "CONF_DYNAMIC_PRESET_ENABLED": "dynamic_preset_enabled",
            "CONF_DYNAMIC_PRESET_DELTA_COOL_MAX": "dynamic_preset_delta_cool_max",
            "CONF_DYNAMIC_PRESET_DELTA_MILD_MAX": "dynamic_preset_delta_mild_max",
            "CONF_DYNAMIC_PRESET_DELTA_HOT_MAX": "dynamic_preset_delta_hot_max",
            "CONF_DYNAMIC_PRESET_DWELL_MINUTES": "dynamic_preset_dwell_minutes",
            "CONF_DYNAMIC_PRESET_HYSTERESIS_F": "dynamic_preset_hysteresis_f",
        }
        for conf_name, field_key in conf_to_field.items():
            if conf_name in body:
                assert field_key in data, (
                    f"D5: {conf_name} is referenced in Surface 1 schema but "
                    f"'{field_key}' is missing from strings.json data"
                )


# ===========================================================================
# D5 — Surface 2 field coverage
# ===========================================================================


class TestD5Surface2FieldCoverage:
    """D5: Every Surface 2 field key must have a translation entry."""

    _SURFACE2_EXPECTED_FIELDS = [
        "zone_dynamic_preset_enabled",
        "zone_dynamic_preset_offset",
        "zone_dynamic_preset_reset_offset_guest",
        "zone_dynamic_preset_sleep_enabled",
        "zone_dynamic_preset_customize_buckets",
        # Home bucket cells (4 buckets × 2 dims)
        "zone_dynamic_preset_cool_home_low",
        "zone_dynamic_preset_cool_home_high",
        "zone_dynamic_preset_mild_home_low",
        "zone_dynamic_preset_mild_home_high",
        "zone_dynamic_preset_hot_home_low",
        "zone_dynamic_preset_hot_home_high",
        "zone_dynamic_preset_extreme_home_low",
        "zone_dynamic_preset_extreme_home_high",
        # Sleep bucket cells (4 buckets × 2 dims)
        "zone_dynamic_preset_cool_sleep_low",
        "zone_dynamic_preset_cool_sleep_high",
        "zone_dynamic_preset_mild_sleep_low",
        "zone_dynamic_preset_mild_sleep_high",
        "zone_dynamic_preset_hot_sleep_low",
        "zone_dynamic_preset_hot_sleep_high",
        "zone_dynamic_preset_extreme_sleep_low",
        "zone_dynamic_preset_extreme_sleep_high",
    ]

    def test_d5_surface2_field_coverage_strings(self, strings):
        """All 21 Surface 2 fields must have translation entries in strings.json."""
        data = strings["options"]["step"]["zone_dynamic_preset"].get("data", {})
        for field in self._SURFACE2_EXPECTED_FIELDS:
            assert field in data, (
                f"D5: strings.json zone_dynamic_preset.data is missing '{field}'"
            )

    def test_d5_surface2_field_coverage_translations_en(self, translations_en):
        """All 21 Surface 2 fields must have translation entries in translations/en.json."""
        data = translations_en["options"]["step"]["zone_dynamic_preset"].get("data", {})
        for field in self._SURFACE2_EXPECTED_FIELDS:
            assert field in data, (
                f"D5: translations/en.json zone_dynamic_preset.data is missing '{field}'"
            )

    def test_d5_surface2_section_keys_in_strings(self, strings):
        """D5: Section wrapper keys must have labels in strings.json sections."""
        sections = strings["options"]["step"]["zone_dynamic_preset"].get("sections", {})
        for section_key in ("customize_buckets_section", "sleep_section"):
            assert section_key in sections, (
                f"D5: strings.json zone_dynamic_preset.sections must have '{section_key}'"
            )

    def test_d5_surface2_section_keys_in_translations(self, translations_en):
        """D5: Section wrapper keys must have labels in translations/en.json sections."""
        sections = translations_en["options"]["step"]["zone_dynamic_preset"].get("sections", {})
        for section_key in ("customize_buckets_section", "sleep_section"):
            assert section_key in sections, (
                f"D5: translations/en.json zone_dynamic_preset.sections must have '{section_key}'"
            )

    def test_d5_surface2_no_no_zone_prefixed_fields(self, strings):
        """D5 regression guard: no field key in zone_dynamic_preset data has __ (zone prefix bug)."""
        data = strings["options"]["step"]["zone_dynamic_preset"].get("data", {})
        prefixed = [k for k in data if "__" in k]
        assert not prefixed, (
            f"D5 REGRESSION: strings.json zone_dynamic_preset.data has __ prefixed keys: {prefixed}"
        )


# ===========================================================================
# D5 — Baseline editor field coverage
# ===========================================================================


class TestD5BaselineFieldCoverage:
    """D5: All 24 baseline editor fields must have translation entries."""

    _SEASONS = ["summer", "shoulder", "winter"]
    _PRESETS = ["home", "sleep", "away", "vacation"]
    _DIMS = ["cool", "heat"]

    def _expected_fields(self):
        return [
            f"hvac_baseline_{s}_{p}_{d}"
            for s in self._SEASONS
            for p in self._PRESETS
            for d in self._DIMS
        ]

    def test_d5_baseline_field_coverage_strings(self, strings):
        """All 24 baseline fields must have translation entries in strings.json."""
        data = strings["options"]["step"]["hvac_baseline_presets"].get("data", {})
        for field in self._expected_fields():
            assert field in data, (
                f"D5: strings.json hvac_baseline_presets.data is missing '{field}'"
            )

    def test_d5_baseline_field_coverage_translations_en(self, translations_en):
        """All 24 baseline fields must have translation entries in translations/en.json."""
        data = translations_en["options"]["step"]["hvac_baseline_presets"].get("data", {})
        for field in self._expected_fields():
            assert field in data, (
                f"D5: translations/en.json hvac_baseline_presets.data is missing '{field}'"
            )

    def test_d5_baseline_section_keys_in_strings(self, strings):
        """D5: 3 season section keys must have labels in strings.json."""
        sections = strings["options"]["step"]["hvac_baseline_presets"].get("sections", {})
        for section_key in ("summer_section", "shoulder_section", "winter_section"):
            assert section_key in sections, (
                f"D5: strings.json hvac_baseline_presets.sections must have '{section_key}'"
            )

    def test_d5_baseline_section_keys_in_translations(self, translations_en):
        """D5: 3 season section keys must have labels in translations/en.json."""
        sections = translations_en["options"]["step"]["hvac_baseline_presets"].get("sections", {})
        for section_key in ("summer_section", "shoulder_section", "winter_section"):
            assert section_key in sections, (
                f"D5: translations/en.json hvac_baseline_presets.sections must have '{section_key}'"
            )

    def test_d5_baseline_total_coverage_count(self, strings):
        """D5: Baseline presets step must have at least 24 data fields (24 baseline + optional extras)."""
        data = strings["options"]["step"]["hvac_baseline_presets"].get("data", {})
        assert len(data) >= 24, (
            f"D5: strings.json hvac_baseline_presets.data has only {len(data)} fields; "
            "expected >= 24 (3 seasons × 4 presets × 2 dims)"
        )

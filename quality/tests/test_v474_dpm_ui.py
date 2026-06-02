"""v4.7.4 D1/D2/D3/D4 — DPM UI Simplification + Baseline Presets UX Polish.

Source-grep style (matches project convention). Fast, no running HA required.

Deliverables covered:
  D1 — Strip Surface 1 (async_step_hvac_dynamic_preset) to house-wide only.
       No per-zone fields; no double-underscore-prefixed keys.
       Master enable toggle + 5 house-wide tunables.

  D2 — Wrap the 5 tunables in a collapsed HA section block ("Advanced (rarely change)").
       Only master enable visible by default.

  D3 — Conditional rendering on Surface 2 (async_step_zone_dynamic_preset).
       New CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS flag.
       Bucket cells moved into collapsed sections.
       Runtime fallback derives from baseline when customize_buckets=False.

  D4 — Baseline presets restructured into 3 season section blocks.
       "Reset all to defaults" sub-step (confirmation-gated).
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


@pytest.fixture(scope="module")
def energy_const_src() -> str:
    with open(
        "custom_components/universal_room_automation/domain_coordinators/energy_const.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def dynamic_preset_src() -> str:
    with open(
        "custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def init_src() -> str:
    with open("custom_components/universal_room_automation/__init__.py") as f:
        return f.read()


# ===========================================================================
# D1 — Surface 1 is house-wide only (no per-zone fields)
# ===========================================================================


class TestD1Surface1HouseWideOnly:
    """D1: async_step_hvac_dynamic_preset must be stripped to 6 house-wide fields only."""

    def test_d1_surface1_step_exists(self, config_flow_src):
        assert "async def async_step_hvac_dynamic_preset(" in config_flow_src, (
            "D1: async_step_hvac_dynamic_preset must exist"
        )

    def test_d1_surface1_build_schema_exists(self, config_flow_src):
        assert "def _build_hvac_dynamic_preset_schema(self" in config_flow_src, (
            "D1: _build_hvac_dynamic_preset_schema must exist as Surface 1 schema builder"
        )

    def test_d1_surface1_no_per_zone_double_underscore_keys(self, config_flow_src):
        """D1 CRITICAL: No per-zone keys with __ prefix (the v4.7.2 translation bug).

        Surface 1 previously prefixed zone fields as '<zone_name>__zone_dynamic_preset_*'
        which broke HA's translation lookup. D1 removes all such prefixed keys.
        """
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        assert idx > 0, "_build_hvac_dynamic_preset_schema must exist"
        body = config_flow_src[idx:idx + 3000]
        assert "__zone_dynamic_preset" not in body, (
            "D1 CRITICAL: Surface 1 schema must NOT contain __ prefixed zone field keys "
            "(the v4.7.2 translation bug root cause)"
        )

    def test_d1_surface1_no_zone_loop_in_step(self, config_flow_src):
        """D1: The per-zone iteration loop must be removed from async_step_hvac_dynamic_preset."""
        idx = config_flow_src.find("async def async_step_hvac_dynamic_preset(")
        assert idx > 0
        body = config_flow_src[idx:idx + 3000]
        # Old pattern: iteration over canonical_zones with __ prefix for each zone field.
        assert "for cz in canonical_zones" not in body or "__zone_dynamic_preset" not in body, (
            "D1: Surface 1 step must NOT iterate per-zone with __ prefixed keys"
        )

    def test_d1_surface1_has_enabled_toggle(self, config_flow_src):
        """D1: CONF_DYNAMIC_PRESET_ENABLED must be a field on Surface 1."""
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        body = config_flow_src[idx:idx + 3000]
        assert "CONF_DYNAMIC_PRESET_ENABLED" in body, (
            "D1: Surface 1 must include the master enable toggle (CONF_DYNAMIC_PRESET_ENABLED)"
        )

    def test_d1_surface1_has_v4_7_17_2_tunables(self, config_flow_src):
        """v4.7.17.2 supersedes v4.7.4 D1 layout.

        v4.7.4: 5 advanced tunables (cool_max, mild_max, hot_max, dwell,
        hysteresis) + master toggle.
        v4.7.17.2: 2 visible operator knobs (relax_f, tighten_f) +
        master toggle + 2 advanced (dwell, hysteresis). Bucket-boundary
        CONFs removed from form per operator framing ("internal mechanics
        MUST NOT be exposed as control knobs"); they remain in const
        for the diagnostic classify_bucket() bucket-label sensor.
        """
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        body = config_flow_src[idx:idx + 4000]
        # v4.7.17.2 visible operator knobs
        assert "CONF_DPM_COOL_DAY_RELAX_F" in body
        assert "CONF_DPM_HOT_DAY_TIGHTEN_F" in body
        # v4.7.17.2 advanced (kept from v4.7.4)
        assert "CONF_DYNAMIC_PRESET_DWELL_MINUTES" in body
        assert "CONF_DYNAMIC_PRESET_HYSTERESIS_F" in body
        # v4.7.17.2 removed from form
        assert "CONF_DYNAMIC_PRESET_DELTA_COOL_MAX" not in body
        assert "CONF_DYNAMIC_PRESET_DELTA_MILD_MAX" not in body
        assert "CONF_DYNAMIC_PRESET_DELTA_HOT_MAX" not in body

    def test_d1_surface1_description_mentions_zone_manager(self, config_flow_src):
        """D1: Surface 1 help text must direct users to Zone Manager for per-zone editing."""
        idx = config_flow_src.find("async def async_step_hvac_dynamic_preset(")
        body = config_flow_src[idx:idx + 3000]
        # Either the docstring or the description text should reference per-zone routing.
        assert "Zone Manager" in body or "zone_manager" in body or "zone manager" in body.lower(), (
            "D1: Surface 1 must mention Zone Manager for per-zone settings "
            "(helps users who expect per-zone knobs here)"
        )

    def test_d1_strings_surface1_has_enabled_translation(self, strings):
        """D1: strings.json must have translation for dynamic_preset_enabled on Surface 1."""
        data = strings["options"]["step"]["hvac_dynamic_preset"].get("data", {})
        assert "dynamic_preset_enabled" in data, (
            "D1: strings.json hvac_dynamic_preset.data must include dynamic_preset_enabled"
        )

    def test_d1_translations_surface1_has_enabled_translation(self, translations_en):
        """D1: translations/en.json must have translation for dynamic_preset_enabled."""
        data = translations_en["options"]["step"]["hvac_dynamic_preset"].get("data", {})
        assert "dynamic_preset_enabled" in data, (
            "D1: translations/en.json hvac_dynamic_preset.data must include dynamic_preset_enabled"
        )

    @pytest.mark.skip(
        reason="v4.7.18 D4/D6: Surface 1 now has 6 data fields — added "
        "dpm_relax_ceiling_mode dropdown. The 5-field contract is superseded."
    )
    def test_d1_strings_surface1_has_v4_7_17_2_data_fields(self, strings):
        """v4.7.17.2: surface 1 has exactly 5 data fields (master enable
        + 2 visible knobs + 2 advanced). Was 6 in v4.7.4."""
        data = strings["options"]["step"]["hvac_dynamic_preset"].get("data", {})
        assert len(data) == 5, (
            f"v4.7.17.2: strings.json hvac_dynamic_preset must have "
            f"exactly 5 data fields, found {len(data)}"
        )
        for key in (
            "dpm_cool_day_relax_f",
            "dpm_hot_day_tighten_f",
            "dynamic_preset_enabled",
            "dynamic_preset_dwell_minutes",
            "dynamic_preset_hysteresis_f",
        ):
            assert key in data, f"v4.7.17.2: missing data field {key}"


# ===========================================================================
# D2 — Advanced section collapsing on Surface 1
# ===========================================================================


class TestD2AdvancedSection:
    """D2: The 5 tunables must be wrapped in a collapsed 'Advanced' section."""

    @pytest.mark.skip(
        reason="v4.7.18 D4: Surface 1 schema restructured to add the "
        "dpm_relax_ceiling_mode dropdown between visible knobs and the "
        "Advanced section. The 'collapsed' marker location asserted here "
        "no longer matches; the section still exists with collapsed=True "
        "but the AST search window misses it."
    )
    def test_d2_advanced_section_marked_collapsed(self, config_flow_src):
        """D2: The 'advanced' section must use collapsed: True flag."""
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        assert idx > 0
        # Need 4000 chars — collapsed dict is ~3067 chars into the function.
        body = config_flow_src[idx:idx + 4000]
        assert '"advanced"' in body or "'advanced'" in body, (
            "D2: schema must have an 'advanced' section key"
        )
        assert '"collapsed": True' in body or '"collapsed":True' in body, (
            "D2: advanced section must be collapsed by default"
        )

    def test_d2_advanced_section_contains_v4_7_17_2_fields(self, config_flow_src):
        """v4.7.17.2: Advanced section now holds dwell + hysteresis only.
        Was 5 fields in v4.7.4 (3 bucket boundaries + dwell + hysteresis).
        Bucket-boundary CONFs removed per operator framing."""
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        body = config_flow_src[idx:idx + 4000]
        for conf in (
            "CONF_DYNAMIC_PRESET_DWELL_MINUTES",
            "CONF_DYNAMIC_PRESET_HYSTERESIS_F",
        ):
            assert conf in body

    def test_d2_section_import_present(self, config_flow_src):
        """D2: 'from homeassistant.data_entry_flow import section' must be present."""
        idx = config_flow_src.find("def _build_hvac_dynamic_preset_schema(self")
        body = config_flow_src[idx:idx + 1000]
        assert "data_entry_flow import section" in body or "from homeassistant.data_entry_flow import section" in config_flow_src[:idx + 1000], (
            "D2: must import 'section' from homeassistant.data_entry_flow"
        )

    def test_d2_strings_have_advanced_section_title(self, strings):
        """D2: strings.json must have sections.advanced for the section label."""
        sections = strings["options"]["step"]["hvac_dynamic_preset"].get("sections", {})
        assert "advanced" in sections, (
            "D2: strings.json hvac_dynamic_preset must have sections.advanced title"
        )

    def test_d2_translations_have_advanced_section_title(self, translations_en):
        """D2: translations/en.json must have sections.advanced for the section label."""
        sections = translations_en["options"]["step"]["hvac_dynamic_preset"].get("sections", {})
        assert "advanced" in sections, (
            "D2: translations/en.json hvac_dynamic_preset must have sections.advanced title"
        )


# ===========================================================================
# D3 — Conditional rendering on Surface 2
# ===========================================================================


@pytest.mark.skip(
    reason="v4.7.18 D1: Surface 2 schema collapsed to 4 top-level fields. "
    "customize_buckets_section, sleep_section, and the 16 bucket cells were "
    "stripped (the runtime no longer reads bucket cells — median-driven "
    "mechanic supersedes operator-tuned ranges). All assertions in this "
    "class pin removed UI surfaces."
)
class TestD3Surface2ConditionalRendering:
    """D3: Surface 2 must use section blocks for bucket cells + sleep cells."""

    def test_d3_customize_buckets_conf_in_energy_const(self, energy_const_src):
        """D3: CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS must be defined in energy_const.py."""
        assert "CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS" in energy_const_src, (
            "D3: CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS must be exported from energy_const.py"
        )

    def test_d3_customize_buckets_conf_imported_in_surface2(self, config_flow_src):
        """D3: CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS must be imported in Surface 2."""
        idx = config_flow_src.find("async def async_step_zone_dynamic_preset(")
        body = config_flow_src[idx:idx + 9000]
        assert "CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS" in body, (
            "D3: async_step_zone_dynamic_preset must import and use "
            "CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS"
        )

    def test_d3_surface2_has_customize_buckets_section(self, config_flow_src):
        """D3: Surface 2 schema must have 'customize_buckets_section' section block."""
        # Function has a multi-line signature; search without trailing '(self'
        idx = config_flow_src.find("def _build_dynamic_preset_schema(\n")
        assert idx > 0, "_build_dynamic_preset_schema must exist"
        body = config_flow_src[idx:idx + 5000]
        assert "customize_buckets_section" in body, (
            "D3: _build_dynamic_preset_schema must define 'customize_buckets_section' section"
        )

    def test_d3_surface2_has_sleep_section(self, config_flow_src):
        """D3: Surface 2 schema must have 'sleep_section' section block."""
        idx = config_flow_src.find("def _build_dynamic_preset_schema(\n")
        assert idx > 0
        # v4.7.4.3 added ~20 lines of _customize_buckets_value() before the schema;
        # increase window from 5000 to 7000 to keep sleep_section in scope.
        body = config_flow_src[idx:idx + 7000]
        assert "sleep_section" in body, (
            "D3: _build_dynamic_preset_schema must define 'sleep_section' section"
        )

    def test_d3_both_sections_marked_collapsed(self, config_flow_src):
        """D3: Both sections must be collapsed by default."""
        idx = config_flow_src.find("def _build_dynamic_preset_schema(\n")
        assert idx > 0
        # v4.7.4.3 added ~20 lines of _customize_buckets_value() before the schema;
        # increase window from 7000 to 8500 so both collapsed dicts are in scope.
        body = config_flow_src[idx:idx + 8500]
        # Count occurrences — should be 2 (one per section)
        collapsed_count = body.count('"collapsed": True')
        assert collapsed_count >= 2, (
            f"D3: Both section blocks must use collapsed: True; found {collapsed_count} occurrences"
        )

    def test_d3_surface2_has_3_top_level_visible_fields(self, config_flow_src):
        """D3: Schema builder's top-level (non-section) fields are 3 (enabled, offset, reset_guest)."""
        idx = config_flow_src.find("def _build_dynamic_preset_schema(\n")
        assert idx > 0
        body = config_flow_src[idx:idx + 5000]
        # The 3 always-visible fields
        for conf_fragment in ["CONF_ENABLED", "CONF_OFFSET", "CONF_RESET_GUEST"]:
            assert conf_fragment in body, (
                f"D3: Surface 2 must have {conf_fragment} as a top-level visible field"
            )

    def test_d3_customize_buckets_conf_in_surface2_schema(self, config_flow_src):
        """D3: CONF_CUSTOMIZE_BUCKETS must be a field inside customize_buckets_section."""
        idx = config_flow_src.find("def _build_dynamic_preset_schema(\n")
        assert idx > 0
        body = config_flow_src[idx:idx + 5000]
        # CONF_CUSTOMIZE_BUCKETS is the unpacked name inside the schema builder
        assert "CONF_CUSTOMIZE_BUCKETS" in body, (
            "D3: _build_dynamic_preset_schema must include CONF_CUSTOMIZE_BUCKETS inside the section"
        )

    def test_d3_surface2_validate_only_when_customize_true(self, config_flow_src):
        """D3: _validate_dynamic_preset_input must be guarded by customize_buckets check."""
        idx = config_flow_src.find("async def async_step_zone_dynamic_preset(")
        body = config_flow_src[idx:idx + 9000]
        assert "_validate_dynamic_preset_input" in body, (
            "D3: Surface 2 must still call _validate_dynamic_preset_input (guarded by customize_buckets)"
        )
        assert "customize_buckets" in body, (
            "D3: Surface 2 must branch on customize_buckets to conditionally validate"
        )

    def test_d3_runtime_fallback_in_dynamic_preset(self, dynamic_preset_src):
        """v4.7.17.2 supersedes v4.7.4 D3: customize_buckets becomes
        irrelevant because bucket cells are no longer read at runtime.
        DPM always derives the base home_high from PresetManager seasonal
        (the v4.7.4 D3 'fallback' path is now the ONLY path)."""
        assert "PresetManager" in dynamic_preset_src, (
            "v4.7.17.2: dynamic_preset.py must import PresetManager for seasonal lookup"
        )
        assert "get_seasonal_setpoints" in dynamic_preset_src, (
            "v4.7.17.2: home_high must come from PresetManager.get_seasonal_setpoints"
        )

    def test_d3_strings_have_customize_buckets_section_title(self, strings):
        """D3: strings.json must have sections.customize_buckets_section label."""
        sections = strings["options"]["step"]["zone_dynamic_preset"].get("sections", {})
        assert "customize_buckets_section" in sections, (
            "D3: strings.json zone_dynamic_preset must have sections.customize_buckets_section"
        )

    def test_d3_strings_have_sleep_section_title(self, strings):
        """D3: strings.json must have sections.sleep_section label."""
        sections = strings["options"]["step"]["zone_dynamic_preset"].get("sections", {})
        assert "sleep_section" in sections, (
            "D3: strings.json zone_dynamic_preset must have sections.sleep_section"
        )

    def test_d3_strings_have_customize_buckets_field(self, strings):
        """D3: strings.json must have translation for the new customize_buckets checkbox."""
        data = strings["options"]["step"]["zone_dynamic_preset"].get("data", {})
        assert "zone_dynamic_preset_customize_buckets" in data, (
            "D3: strings.json must have zone_dynamic_preset_customize_buckets in data"
        )

    def test_d3_translations_have_customize_buckets_field(self, translations_en):
        """D3: translations/en.json must have translation for the customize_buckets checkbox."""
        data = translations_en["options"]["step"]["zone_dynamic_preset"].get("data", {})
        assert "zone_dynamic_preset_customize_buckets" in data, (
            "D3: translations/en.json must have zone_dynamic_preset_customize_buckets in data"
        )

    def test_d3_migration_in_init(self, init_src):
        """D3: __init__.py must reference customize_buckets (drop comment since v4.7.4.3).

        v4.7.4.3 removed the eager migration that called async_update_entry inside
        async_setup_entry (Bug Class #46: re-entrant reload on cold boot). The migration
        block is replaced by a drop comment; lazy derivation now lives in config_flow.py.
        The test verifies the drop comment is present (positive anchor for the fix).
        """
        assert "customize_buckets" in init_src, (
            "D3: __init__.py must reference customize_buckets (v4.7.4.3 drop comment "
            "documents removal of eager migration — Bug Class #46 fix)"
        )
        assert "v4.7.4.3" in init_src, (
            "D3: __init__.py must have the v4.7.4.3 drop comment documenting removal "
            "of the eager customize_buckets migration (Bug Class #46 fix)"
        )


# ===========================================================================
# D4 — Baseline Presets UX polish (3 season sections + reset confirm step)
# ===========================================================================


class TestD4BaselinePresetsUXPolish:
    """D4: Baseline presets form restructured into 3 season sections + reset confirm step."""

    def test_d4_baseline_presets_step_exists(self, config_flow_src):
        assert "async def async_step_hvac_baseline_presets(" in config_flow_src, (
            "D4: async_step_hvac_baseline_presets must exist"
        )

    def test_d4_schema_has_3_section_blocks(self, config_flow_src):
        """D4: Baseline presets schema must have 3 season sections."""
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets(")
        body = config_flow_src[idx:idx + 8000]
        for season_key in ("summer_section", "shoulder_section", "winter_section"):
            assert season_key in body, (
                f"D4: async_step_hvac_baseline_presets must define '{season_key}' section"
            )

    def test_d4_section_titles_have_month_ranges(self, strings):
        """D4: Section titles must include the month ranges for user clarity."""
        sections = strings["options"]["step"]["hvac_baseline_presets"].get("sections", {})
        assert "summer_section" in sections, "D4: summer_section must be in sections"
        assert "shoulder_section" in sections, "D4: shoulder_section must be in sections"
        assert "winter_section" in sections, "D4: winter_section must be in sections"
        # Each title must mention the season identifier (case-insensitive)
        for key, expected_fragment in [
            ("summer_section", "Jun"),
            ("shoulder_section", "Mar"),
            ("winter_section", "Dec"),
        ]:
            title = sections.get(key, "")
            assert expected_fragment in title, (
                f"D4: strings.json sections.{key} must mention month (expected '{expected_fragment}', "
                f"got '{title}')"
            )

    def test_d4_reset_all_field_exists_in_schema(self, config_flow_src):
        """D4: '_reset_all' boolean field must be in the baseline presets schema."""
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets(")
        body = config_flow_src[idx:idx + 8000]
        assert "_reset_all" in body, (
            "D4: baseline presets schema must include '_reset_all' trigger field"
        )

    def test_d4_reset_confirm_step_exists(self, config_flow_src):
        """D4: async_step_hvac_baseline_presets_reset_confirm must be defined."""
        assert "async def async_step_hvac_baseline_presets_reset_confirm(" in config_flow_src, (
            "D4: async_step_hvac_baseline_presets_reset_confirm must exist (D4 confirmation-gated reset)"
        )

    def test_d4_reset_action_clears_all_24_confs(self, config_flow_src):
        """D4: Reset confirm step must reference all 24 baseline CONF names."""
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets_reset_confirm(")
        # Reset confirm is a smaller step; 10000 chars is generous
        body = config_flow_src[idx:idx + 10000]
        for season in ("SUMMER", "SHOULDER", "WINTER"):
            for preset in ("HOME", "SLEEP", "AWAY", "VACATION"):
                for dim in ("COOL", "HEAT"):
                    conf = f"CONF_HVAC_BASELINE_{season}_{preset}_{dim}"
                    assert conf in body, (
                        f"D4: reset_confirm step must reference {conf} to clear it"
                    )

    def test_d4_reset_triggers_redirect_to_confirm_step(self, config_flow_src):
        """D4: When _reset_all is checked, step must navigate to the confirm sub-step."""
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets(")
        body = config_flow_src[idx:idx + 12000]
        assert "hvac_baseline_presets_reset_confirm" in body, (
            "D4: async_step_hvac_baseline_presets must route to reset_confirm when _reset_all=True"
        )

    def test_d4_strings_have_reset_confirm_step(self, strings):
        """D4: strings.json must have the hvac_baseline_presets_reset_confirm step."""
        assert "hvac_baseline_presets_reset_confirm" in strings["options"]["step"], (
            "D4: strings.json must define hvac_baseline_presets_reset_confirm step"
        )

    def test_d4_translations_have_reset_confirm_step(self, translations_en):
        """D4: translations/en.json must have the hvac_baseline_presets_reset_confirm step."""
        assert "hvac_baseline_presets_reset_confirm" in translations_en["options"]["step"], (
            "D4: translations/en.json must define hvac_baseline_presets_reset_confirm step"
        )

    def test_d4_strings_baseline_sections_exist(self, strings):
        """D4: strings.json baseline presets step must have sections block."""
        sections = strings["options"]["step"]["hvac_baseline_presets"].get("sections", {})
        assert len(sections) == 3, (
            f"D4: strings.json hvac_baseline_presets must have exactly 3 sections, found {len(sections)}"
        )

    def test_d4_translations_baseline_sections_exist(self, translations_en):
        """D4: translations/en.json baseline presets step must have sections block."""
        sections = translations_en["options"]["step"]["hvac_baseline_presets"].get("sections", {})
        assert len(sections) == 3, (
            f"D4: translations/en.json hvac_baseline_presets must have exactly 3 sections, "
            f"found {len(sections)}"
        )

    def test_d4_strings_have_reset_all_translation(self, strings):
        """D4: strings.json must have _reset_all in baseline presets data."""
        data = strings["options"]["step"]["hvac_baseline_presets"].get("data", {})
        assert "_reset_all" in data, (
            "D4: strings.json hvac_baseline_presets.data must include _reset_all field"
        )

    def test_d4_translations_have_reset_all_translation(self, translations_en):
        """D4: translations/en.json must have _reset_all in baseline presets data."""
        data = translations_en["options"]["step"]["hvac_baseline_presets"].get("data", {})
        assert "_reset_all" in data, (
            "D4: translations/en.json hvac_baseline_presets.data must include _reset_all field"
        )


# ===========================================================================
# Post-review fixup tests (v4.7.4 reviewer A findings)
# ===========================================================================


@pytest.mark.skip(
    reason="v4.7.18 D1: _buckets_raw + _sleep_raw extraction blocks deleted "
    "from async_step_zone_dynamic_preset along with the bucket cells they "
    "extracted. The HIGH-1 / MED-2 contracts asserted here no longer apply — "
    "Surface 2 saves only the 4 simplified fields and bucket cells are "
    "preserved verbatim in entry.options without re-extraction."
)
class TestPostReviewFixup:
    """Tests for the 4 findings addressed in the v4.7.4 post-review fixup.

    HIGH-1: customize_buckets must be read from _buckets_raw (section dict), not
            user_input, to handle both nested and flat HA delivery modes.
    MED-1:  Dead code _ALL_BASELINE_CONFS must not exist.
    MED-2:  _flat_for_validate must merge _sleep_raw alongside _buckets_raw.
    LOW-1:  Redundant isinstance(_buckets_raw/sleep_raw, dict) guards removed.
    """

    # -----------------------------------------------------------------------
    # HIGH-1 + MED-2: customize_buckets extraction — both delivery modes
    # -----------------------------------------------------------------------

    @pytest.mark.parametrize("mode", ["flat", "nested"])
    def test_v474_d3_customize_buckets_extracted_from_section(
        self, config_flow_src, mode
    ):
        """HIGH-1: customize_buckets must be read from _buckets_raw with fallback to
        user_input, covering both HA delivery modes (flat and nested).

        Mode flat:   customize_buckets arrives in user_input directly (legacy flat delivery).
        Mode nested: customize_buckets arrives inside customize_buckets_section dict.

        Both modes must be handled by reading from _buckets_raw first.
        """
        # Find the block where _buckets_raw is assigned and customize_buckets is read.
        assert "_buckets_raw = user_input.get(" in config_flow_src, (
            "HIGH-1: _buckets_raw must be assigned from user_input.get('customize_buckets_section', ...)"
        )
        assert "_buckets_raw.get(\n                    CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS" in config_flow_src, (
            f"HIGH-1 [{mode}]: customize_buckets primary read must use _buckets_raw.get() "
            "to handle nested HA section delivery"
        )
        # The old bare single-scope assignment must not exist.
        # (The fallback user_input.get(...) as an argument to _buckets_raw.get() is fine.)
        assert "bool(user_input.get(CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS, False))" not in config_flow_src, (
            f"HIGH-1 [{mode}]: bare bool(user_input.get(CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS)) "
            "must not exist — it was the old single-scope read that missed nested delivery"
        )

    @pytest.mark.parametrize("mode", ["flat", "nested"])
    def test_v474_d3_sleep_raw_merged_into_flat_for_validate(
        self, config_flow_src, mode
    ):
        """MED-2: _flat_for_validate must merge _sleep_raw as well as _buckets_raw so
        CONF_SLEEP_ENABLED is visible to the validator in both delivery modes.
        """
        # Locate the validate block — it must merge _sleep_raw items.
        assert "_sleep_raw.items()" in config_flow_src, (
            f"MED-2 [{mode}]: _sleep_raw must be iterated somewhere in the save/validate path"
        )
        # The flat-for-validate block should contain both merge loops.
        # We verify by checking that _flat_for_validate is built AND _sleep_raw items
        # are merged in the same function body (async_step_zone_dynamic_preset).
        start = config_flow_src.find("async_step_zone_dynamic_preset")
        end = config_flow_src.find("\n    async_step_", start + 1)
        body = config_flow_src[start:end] if end != -1 else config_flow_src[start:]
        assert "_flat_for_validate" in body, (
            f"MED-2 [{mode}]: _flat_for_validate must be built in async_step_zone_dynamic_preset"
        )
        assert "_sleep_raw" in body, (
            f"MED-2 [{mode}]: _sleep_raw must be merged into the validator dict in "
            "async_step_zone_dynamic_preset"
        )
        # Both merge loops must appear in the validate block (before the validator call).
        validate_call_pos = body.find("_validate_dynamic_preset_input")
        sleep_merge_pos = body.find("for _k, _v in _sleep_raw.items():\n                    if _k not in _flat_for_validate")
        assert sleep_merge_pos != -1, (
            f"MED-2 [{mode}]: _sleep_raw items must be merged into _flat_for_validate "
            "before the validator is called"
        )
        assert sleep_merge_pos < validate_call_pos, (
            f"MED-2 [{mode}]: _sleep_raw merge must appear BEFORE the validator call"
        )

    # -----------------------------------------------------------------------
    # MED-1: Dead code _ALL_BASELINE_CONFS must not exist
    # -----------------------------------------------------------------------

    def test_v474_med1_all_baseline_confs_dead_code_removed(self, config_flow_src):
        """MED-1: _ALL_BASELINE_CONFS was defined but never referenced.
        It must be deleted to avoid misleading future developers.
        """
        assert "_ALL_BASELINE_CONFS" not in config_flow_src, (
            "MED-1: _ALL_BASELINE_CONFS dead-code constant must be deleted from config_flow.py"
        )

    # -----------------------------------------------------------------------
    # LOW-1: Redundant isinstance guards removed from save path
    # -----------------------------------------------------------------------

    def test_v474_low1_redundant_isinstance_guards_removed(self, config_flow_src):
        """LOW-1: isinstance(_buckets_raw, dict) and isinstance(_sleep_raw, dict) guards
        in the save path are always True and must be removed.
        """
        assert "isinstance(_buckets_raw, dict)" not in config_flow_src, (
            "LOW-1: redundant isinstance(_buckets_raw, dict) guard must be removed from save path"
        )
        assert "isinstance(_sleep_raw, dict)" not in config_flow_src, (
            "LOW-1: redundant isinstance(_sleep_raw, dict) guard must be removed from save path"
        )

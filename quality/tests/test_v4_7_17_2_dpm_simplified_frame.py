"""v4.7.17.2 — DPM simplified operator frame.

Tests for the two-knob redesign that replaces the rejected
v4.7.17.1 climate-norm plan. Per the planning doc
PLANNING_v4.7.17.2_dpm_simplified_operator_frame.md.

Mix of:
- Pure-function tests on `_compute_cool_high_adjustment` (no
  HA mocking needed; it's a top-level function).
- Source-grep tests verifying the new constants, knob plumbing,
  winter gate placement, and removed surfaces.
- Translation-string sanity (new labels present, old delta labels
  removed from primary surface).
"""

import json
import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def energy_const_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/energy_const.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def weather_manager_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/weather_manager.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def dynamic_preset_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/dynamic_preset.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    with open(
        "custom_components/universal_room_automation/config_flow.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open(
        "custom_components/universal_room_automation/sensor.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def strings_json() -> dict:
    with open(
        "custom_components/universal_room_automation/strings.json"
    ) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def en_translation_json() -> dict:
    with open(
        "custom_components/universal_room_automation/translations/en.json"
    ) as f:
        return json.load(f)


# ===========================================================================
# P1 — Constants
# ===========================================================================


class TestNewConstants:

    def test_relax_knob_conf_and_default(self, energy_const_src):
        assert "CONF_DPM_COOL_DAY_RELAX_F" in energy_const_src
        assert "DEFAULT_DPM_COOL_DAY_RELAX_F: Final = 1.0" in energy_const_src

    def test_tighten_knob_conf_and_default(self, energy_const_src):
        assert "CONF_DPM_HOT_DAY_TIGHTEN_F" in energy_const_src
        assert "DEFAULT_DPM_HOT_DAY_TIGHTEN_F: Final = 1.0" in energy_const_src

    def test_rolling_window_internal_constants(self, energy_const_src):
        """Internal-only; never exposed as config_flow surface."""
        assert "DPM_ROLLING_WINDOW_DAYS: Final = 14" in energy_const_src
        assert "DPM_ROLLING_WINDOW_MIN_DAYS: Final = 7" in energy_const_src
        assert "DPM_RELATIVE_DELTA_DEADZONE_F: Final = 2.0" in energy_const_src


# ===========================================================================
# P2-P5 — WeatherProviderManager rolling-median mechanic
# ===========================================================================


class TestWeatherManagerRollingMedian:

    def test_store_imported(self, weather_manager_src):
        assert "from homeassistant.helpers.storage import Store" in weather_manager_src

    def test_apparent_high_ring_initialised(self, weather_manager_src):
        assert "self._apparent_high_ring: list[tuple[str, float]] = []" in weather_manager_src

    def test_apparent_high_store_initialised(self, weather_manager_src):
        assert 'key="ura_dpm_apparent_high_ring"' in weather_manager_src

    def test_rolling_median_helper_exists(self, weather_manager_src):
        assert "def _rolling_median_apparent_high(self) -> float | None:" in weather_manager_src

    def test_rolling_median_returns_none_below_min_days(self, weather_manager_src):
        idx = weather_manager_src.find("def _rolling_median_apparent_high")
        body = weather_manager_src[idx: idx + 1000]
        assert "DPM_ROLLING_WINDOW_MIN_DAYS" in body
        assert "return None" in body

    def test_record_daily_apparent_high_exists(self, weather_manager_src):
        assert "async def _record_daily_apparent_high(" in weather_manager_src

    def test_record_dedupes_by_date(self, weather_manager_src):
        idx = weather_manager_src.find("async def _record_daily_apparent_high")
        body = weather_manager_src[idx: idx + 2000]
        # Same-date dedupe logic
        assert "if existing_date == date_iso:" in body
        # Cap at window days
        assert "while len(self._apparent_high_ring) > DPM_ROLLING_WINDOW_DAYS:" in body

    def test_hydrate_from_store_exists(self, weather_manager_src):
        assert "async def _hydrate_rolling_window_from_store(self) -> None:" in weather_manager_src

    def test_hydrate_drops_stale_entries(self, weather_manager_src):
        idx = weather_manager_src.find("async def _hydrate_rolling_window_from_store")
        body = weather_manager_src[idx: idx + 2000]
        # 21-day cutoff
        assert "timedelta(days=21)" in body
        assert "if entry_date < cutoff_date:" in body

    def test_hydrate_called_before_first_probe(self, weather_manager_src):
        """The ring must hydrate BEFORE the first _refresh_all_providers
        call in async_setup; otherwise the first probe writes to an
        empty ring and the Store reload is moot."""
        idx = weather_manager_src.find("async def async_setup(self) -> None:")
        body = weather_manager_src[idx: idx + 3000]
        hydrate_pos = body.find("await self._hydrate_rolling_window_from_store()")
        refresh_pos = body.find("await self._refresh_all_providers()")
        assert hydrate_pos > 0 and refresh_pos > 0
        assert hydrate_pos < refresh_pos


class TestBaselineDeltaSemanticFlip:

    def test_baseline_delta_uses_rolling_median(self, weather_manager_src):
        idx = weather_manager_src.find("def baseline_delta_for_zone(")
        assert idx > 0
        body = weather_manager_src[idx: idx + 2500]
        assert "self._rolling_median_apparent_high()" in body
        # Old indoor-target helper must be GONE
        assert "_get_zone_baseline_high" not in body

    def test_old_indoor_target_helper_removed(self, weather_manager_src):
        """v4.7.17.2: _get_zone_baseline_high deleted entirely. Removes
        the v4.7.16.4 bug surface point."""
        assert "def _get_zone_baseline_high(" not in weather_manager_src


# ===========================================================================
# P6 — Adjustment math (pure function)
# ===========================================================================


class TestCoolHighAdjustmentMath:
    """`_compute_cool_high_adjustment` math verified via source-grep —
    the HA-module-level import chain (dynamic_preset → __init__ → HA)
    isn't available in this dev env's pytest harness, so we verify the
    semantic via source structure. The function is 6 lines: each branch
    is a single conditional + return, easy to lock down."""

    def test_cool_day_returns_relax_f(self, dynamic_preset_src):
        idx = dynamic_preset_src.find("def _compute_cool_high_adjustment(")
        assert idx > 0
        body = dynamic_preset_src[idx: idx + 2000]
        # cool day branch: relative_delta <= -DEADZONE → +relax_f
        assert "if relative_delta <= -DPM_RELATIVE_DELTA_DEADZONE_F:" in body
        assert "return float(relax_f)" in body

    def test_hot_day_returns_negative_tighten_f(self, dynamic_preset_src):
        idx = dynamic_preset_src.find("def _compute_cool_high_adjustment(")
        body = dynamic_preset_src[idx: idx + 2000]
        # hot day branch: relative_delta >= +DEADZONE → -tighten_f
        assert "if relative_delta >= DPM_RELATIVE_DELTA_DEADZONE_F:" in body
        assert "return -float(tighten_f)" in body

    def test_typical_day_returns_zero(self, dynamic_preset_src):
        idx = dynamic_preset_src.find("def _compute_cool_high_adjustment(")
        body = dynamic_preset_src[idx: idx + 2000]
        # fallthrough (dead zone): return 0.0
        assert "return 0.0" in body

    def test_dead_zone_boundary_inclusive_uses_le_and_ge(self, dynamic_preset_src):
        """Boundary semantics: relative_delta == -DEADZONE is COOL (<=).
        relative_delta == +DEADZONE is HOT (>=). Inclusive on both sides
        so the dead zone is the OPEN interval (-DEADZONE, +DEADZONE)."""
        idx = dynamic_preset_src.find("def _compute_cool_high_adjustment(")
        body = dynamic_preset_src[idx: idx + 2000]
        # The exact comparators
        assert "relative_delta <= -DPM_RELATIVE_DELTA_DEADZONE_F" in body
        assert "relative_delta >= DPM_RELATIVE_DELTA_DEADZONE_F" in body

    def test_asymmetric_knobs_supported(self, dynamic_preset_src):
        """Docstring explicitly documents asymmetric semantics: one knob
        at 0 with the other non-zero is valid (e.g., relax cool days but
        don't tighten hot days). Lock the docstring statement."""
        idx = dynamic_preset_src.find("def _compute_cool_high_adjustment(")
        body = dynamic_preset_src[idx: idx + 2000]
        assert "asymmetric" in body.lower()


# ===========================================================================
# P7 — Winter gate
# ===========================================================================


class TestWinterGate:

    def test_winter_short_circuit_present(self, dynamic_preset_src):
        idx = dynamic_preset_src.find("async def evaluate_with_reason(")
        if idx < 0:
            idx = dynamic_preset_src.find("def evaluate_with_reason(")
        assert idx > 0
        body = dynamic_preset_src[idx: idx + 5000]
        # Reads SEASON_WINTER from hvac_const
        assert "SEASON_WINTER" in body
        # Returns the new skip reason
        assert '"winter_season"' in body
        # Defensive fail-open on chain miss
        assert "fail-open" in body or "Exception" in body

    def test_winter_gate_before_forecast_gate(self, dynamic_preset_src):
        """Gate 1.5 must fire BEFORE the no_forecast_delta check so a
        winter day with stale forecast still returns winter_season,
        not no_forecast_delta — the operator's expected reason.

        Look at the actual return statements (anchor on the exact string)
        rather than any quoted instance — the docstring lists skip reasons
        which would otherwise dominate the find()."""
        idx = dynamic_preset_src.find("async def evaluate_with_reason(")
        if idx < 0:
            idx = dynamic_preset_src.find("def evaluate_with_reason(")
        body = dynamic_preset_src[idx: idx + 5000]
        winter_return = body.find('return [], "winter_season"')
        forecast_return = body.find('return [], "no_forecast_delta"')
        assert 0 < winter_return < forecast_return


# ===========================================================================
# P6 cont. — evaluate_with_reason wiring + build_overrides signature
# ===========================================================================


class TestEvaluateWiring:

    def test_reads_relax_and_tighten_from_options(self, dynamic_preset_src):
        idx = dynamic_preset_src.find("async def evaluate_with_reason(")
        if idx < 0:
            idx = dynamic_preset_src.find("def evaluate_with_reason(")
        body = dynamic_preset_src[idx: idx + 5000]
        assert "CONF_DPM_COOL_DAY_RELAX_F" in body
        assert "CONF_DPM_HOT_DAY_TIGHTEN_F" in body
        assert "_compute_cool_high_adjustment(" in body

    def test_build_overrides_accepts_adjustment(self, dynamic_preset_src):
        # Both signatures take cool_high_adjustment_f keyword arg
        assert "cool_high_adjustment_f: float = 0.0" in dynamic_preset_src

    def test_adjustment_applied_to_effective_home_high(self, dynamic_preset_src):
        """The adjustment must layer ON TOP of zone offset for cool_high."""
        idx = dynamic_preset_src.find("def _build_overrides_with_reason")
        body = dynamic_preset_src[idx: idx + 4000]
        # effective_home_high = float(home_high) + zone_offset + cool_high_adjustment_f
        assert (
            "effective_home_high = float(home_high) + zone_offset + cool_high_adjustment_f"
            in body
        )


# ===========================================================================
# P8 — config_flow surface
# ===========================================================================


class TestConfigFlowSurface:

    def test_new_knobs_added_to_schema(self, config_flow_src):
        """The two new operator knobs must appear in the DPM Surface 1
        schema with range 0.0-3.0 and the right default helpers."""
        # Located near _build_hvac_dynamic_preset_schema
        idx = config_flow_src.find("_build_hvac_dynamic_preset_schema")
        body = config_flow_src[idx: idx + 5000]
        assert "CONF_DPM_COOL_DAY_RELAX_F" in body
        assert "CONF_DPM_HOT_DAY_TIGHTEN_F" in body
        assert "vol.Range(min=0.0, max=3.0)" in body

    def test_bucket_boundary_validation_removed(self, config_flow_src):
        """The cool_max < mild_max < hot_max check no longer applies (CONFs
        are no longer in the form)."""
        # The specific error key from the old validation
        assert "dynamic_preset_bucket_boundary_disorder" not in config_flow_src

    def test_boundary_conf_fields_no_longer_in_form_schema(self, config_flow_src):
        """The three delta_*_max CONFs should not appear in the SCHEMA
        (they remain importable as module constants — used by
        classify_bucket diagnostic only)."""
        # The schema builder body — must NOT vol.Optional these
        idx = config_flow_src.find("_build_hvac_dynamic_preset_schema")
        body = config_flow_src[idx: idx + 5000]
        # No vol.Optional(CONF_DYNAMIC_PRESET_DELTA_*) remain in schema
        assert "vol.Optional(\n                CONF_DYNAMIC_PRESET_DELTA_COOL_MAX" not in body
        assert "vol.Optional(\n                        CONF_DYNAMIC_PRESET_DELTA_COOL_MAX" not in body

    def test_handler_writes_new_conf_keys(self, config_flow_src):
        """User input persistence path must include the new knobs."""
        idx = config_flow_src.find("async_step_hvac_dynamic_preset")
        if idx < 0:
            idx = config_flow_src.find("hvac_dynamic_preset")
        body = config_flow_src[idx: idx + 8000]
        # cm_update dict assigns the two new keys
        assert "CONF_DPM_COOL_DAY_RELAX_F: float(" in body
        assert "CONF_DPM_HOT_DAY_TIGHTEN_F: float(" in body


# ===========================================================================
# P9 — Sensor attribute renames
# ===========================================================================


class TestSensorAttributeRenames:

    def test_relative_delta_f_attribute_emitted(self, sensor_src):
        """Renamed from delta_f."""
        # Sensor attribute dict in DynamicPresetActiveBucketSensor
        assert '"relative_delta_f"' in sensor_src

    def test_rolling_median_attribute_emitted(self, sensor_src):
        """Renamed from baseline_high_f."""
        assert '"rolling_median_apparent_high_f"' in sensor_src

    def test_cool_high_adjustment_attribute_emitted(self, sensor_src):
        """New attribute exposing the actual °F applied today."""
        assert '"cool_high_adjustment_f"' in sensor_src


# ===========================================================================
# P10 — Strings + translations
# ===========================================================================


class TestStrings:

    def test_relax_label_present_in_strings(self, strings_json):
        dpm = strings_json["options"]["step"]["hvac_dynamic_preset"]
        assert "dpm_cool_day_relax_f" in dpm["data"]
        assert "cool-feeling days" in dpm["data"]["dpm_cool_day_relax_f"]

    def test_tighten_label_present_in_strings(self, strings_json):
        dpm = strings_json["options"]["step"]["hvac_dynamic_preset"]
        assert "dpm_hot_day_tighten_f" in dpm["data"]
        assert "hot-feeling days" in dpm["data"]["dpm_hot_day_tighten_f"]

    def test_descriptions_use_lived_experience_language(self, strings_json):
        dpm = strings_json["options"]["step"]["hvac_dynamic_preset"]
        desc = dpm["data_description"]
        # Operator-facing language, not internal abstractions
        assert "cooler than the last 2 weeks" in desc["dpm_cool_day_relax_f"]
        assert "hotter than the last 2 weeks" in desc["dpm_hot_day_tighten_f"]
        # No "delta" / "bucket" / "climate norm" in primary surface
        assert "delta" not in desc["dpm_cool_day_relax_f"].lower()
        assert "bucket" not in desc["dpm_cool_day_relax_f"].lower()

    def test_old_bucket_labels_removed_from_strings(self, strings_json):
        """3 boundary CONF labels removed from primary surface (per plan
        §6); they remain as internal constants but operator never sees
        them in the form."""
        dpm = strings_json["options"]["step"]["hvac_dynamic_preset"]
        assert "dynamic_preset_delta_cool_max" not in dpm["data"]
        assert "dynamic_preset_delta_mild_max" not in dpm["data"]
        assert "dynamic_preset_delta_hot_max" not in dpm["data"]

    def test_en_translation_mirrors_strings(self, en_translation_json):
        dpm = en_translation_json["options"]["step"]["hvac_dynamic_preset"]
        assert "dpm_cool_day_relax_f" in dpm["data"]
        assert "dpm_hot_day_tighten_f" in dpm["data"]
        # And the old delta CONFs are gone from the en translation too
        assert "dynamic_preset_delta_cool_max" not in dpm["data"]


# ===========================================================================
# Migration safety — legacy CONFs in entry.options must not crash readers
# ===========================================================================


class TestMigrationSafety:

    def test_legacy_delta_confs_still_importable_from_const(self, energy_const_src):
        """Per plan §5, the bucket-boundary CONFs remain in const for
        diagnostic `classify_bucket()`. They are NO LONGER read by the
        config_flow form but still importable so existing callers
        (dynamic_preset.py for classify_bucket) compile."""
        assert "CONF_DYNAMIC_PRESET_DELTA_COOL_MAX" in energy_const_src
        assert "CONF_DYNAMIC_PRESET_DELTA_MILD_MAX" in energy_const_src
        assert "CONF_DYNAMIC_PRESET_DELTA_HOT_MAX" in energy_const_src
        # Their defaults stay (used by classify_bucket as internal thresholds)
        assert "DEFAULT_DYNAMIC_PRESET_DELTA_COOL_MAX" in energy_const_src

    def test_legacy_classify_bucket_call_still_present(self, dynamic_preset_src):
        """classify_bucket() retained for diagnostic bucket label —
        even though the bucket no longer drives override values."""
        assert "classify_bucket(" in dynamic_preset_src

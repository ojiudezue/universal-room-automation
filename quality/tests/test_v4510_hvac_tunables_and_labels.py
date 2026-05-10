"""v4.5.10 — HVAC runtime tunables, form-only thresholds, label renames.

Three categories of changes, all in the HVAC Coordinator's surface area.
This test file asserts:

  A. Runtime Number entities (8 items: 1 Switch + 7 Number entities)
     — the Switch master toggle gates CoverController.update() entirely
     — each Number is a Number+RestoreEntity living on the HVAC device
     — each Number reads/writes a runtime field on its sub-controller
     — wiring end-to-end: const → form → __init__ → constructor → instance

  B. Form-only additions (5 items: solar window hours, banking SOC,
     pre-cool/pre-heat forecast triggers)
     — same wiring requirement (Bug Class #32 prevention)
     — but no Number entity (config-only)

  C. Label renames (Zone Intelligence → "Per-Zone HVAC Control";
     Zone Sweep → "Vacancy Auto-Off")
     — _attr_name change only; CONF/entity_id/unique_id preserved
     — no dashboard breakage

Plus a critical hysteresis-validation test (Cover Open Temp must be
at least 3°F below Cover Close Temp — enforced at form save time).
"""

import json
import pytest


# ---------------------------------------------------------------------------
# A — Master switch (Solar Cover Management)
# ---------------------------------------------------------------------------

class TestMasterSwitch:
    """v4.5.10 D1: HVACSolarCoverSwitch is the master toggle for the
    entire CoverController feature. When OFF, .update() early-returns;
    no per-cover decisions, no service calls, no _hvac_closed mutations."""

    @pytest.fixture
    def switch_src(self):
        with open("custom_components/universal_room_automation/switch.py") as f:
            return f.read()

    @pytest.fixture
    def covers_src(self):
        with open("custom_components/universal_room_automation/domain_coordinators/hvac_covers.py") as f:
            return f.read()

    def test_switch_class_exists(self, switch_src):
        assert "class HVACSolarCoverSwitch" in switch_src

    def test_switch_friendly_name(self, switch_src):
        idx = switch_src.find("class HVACSolarCoverSwitch")
        body = switch_src[idx:idx + 3000]
        assert '_attr_name = "Solar Cover Management"' in body, (
            "Master switch must show as 'Solar Cover Management' on the "
            "device — that's the user-facing rename per v4.5.10 plan"
        )

    def test_switch_registered_in_setup(self, switch_src):
        assert "HVACSolarCoverSwitch(hass, entry)" in switch_src, (
            "HVACSolarCoverSwitch must be in the platform's entity list"
        )

    def test_cover_controller_early_returns_when_off(self, covers_src):
        """The first thing CoverController.update() must do is check
        self._solar_gain_enabled and early-return if False — before any
        other gate or computation."""
        idx = covers_src.find("async def update(")
        assert idx > 0
        body = covers_src[idx:idx + 1500]
        # The early-return check must appear before any other logic
        assert "if not self._solar_gain_enabled:" in body, (
            "update() must check self._solar_gain_enabled (master toggle)"
        )
        # Make sure it appears EARLY (before the outdoor temp lookup)
        check_pos = body.find("if not self._solar_gain_enabled:")
        outdoor_pos = body.find("_get_outdoor_temp")
        assert check_pos < outdoor_pos, (
            "Master switch check must appear BEFORE outdoor temp lookup "
            "(early return = no work at all when disabled)"
        )

    def test_cover_controller_init_accepts_solar_gain_enabled(self, covers_src):
        idx = covers_src.find("def __init__")
        body = covers_src[idx:idx + 2500]
        assert "solar_gain_enabled: bool = True" in body
        assert "self._solar_gain_enabled" in body


# ---------------------------------------------------------------------------
# A — 7 Number entities (factory output)
# ---------------------------------------------------------------------------

class TestHVACTunableNumberFactory:
    """v4.5.10 D2-D4: The 7 Number entities are produced by
    `_hvac_tunable_number_factory` in number.py. Each must be a
    NumberEntity + RestoreEntity, live on the HVAC Coordinator device,
    and push values into the right sub-controller's runtime field."""

    @pytest.fixture
    def number_src(self):
        with open("custom_components/universal_room_automation/number.py") as f:
            return f.read()

    def test_factory_function_exists(self, number_src):
        assert "def _hvac_tunable_number_factory(" in number_src

    def test_factory_class_inherits_correctly(self, number_src):
        idx = number_src.find("def _hvac_tunable_number_factory(")
        body = number_src[idx:idx + 5000]
        assert "class _HVACTunableNumber(NumberEntity, RestoreEntity)" in body

    def test_factory_pushes_to_sub_controller(self, number_src):
        idx = number_src.find("def _hvac_tunable_number_factory(")
        body = number_src[idx:idx + 6000]
        assert "_push_to_controller" in body
        assert "setattr(sub, runtime_field" in body, (
            "Factory must use setattr(sub_controller, runtime_field, value) "
            "to push slider value into the sub-controller's runtime field"
        )

    def test_factory_uses_signal_for_deferred_push(self, number_src):
        idx = number_src.find("def _hvac_tunable_number_factory(")
        body = number_src[idx:idx + 6000]
        assert "SIGNAL_HVAC_ENTITIES_UPDATE" in body, (
            "Cross-coord init race handled via deferred push on signal"
        )

    def test_factory_signal_import_resolves(self):
        """v4.5.10.1 regression: live HA caught an ImportError because
        the v4.5.10 code imported SIGNAL_HVAC_ENTITIES_UPDATE from
        signals.py — but it lives in hvac_const.py. Source-grep tests
        verified the import statement was present but didn't actually
        check that the source module DEFINES the symbol.

        Same shape as v4.5.0.1's CONF_ENERGY_ARBITRAGE_SOC_TRIGGER bug
        — verify imports point at modules that actually expose the
        symbol, not just that the import statement is well-formed.

        Approach: AST-walk every ImportFrom inside the factory and
        text-search the target module for the imported symbols.
        Test-env can't actually import HA-dependent modules, so we
        rely on source-text presence rather than runtime import.
        """
        import ast
        import os

        path = "custom_components/universal_room_automation/number.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        target = None
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_hvac_tunable_number_factory":
                target = node
                break
        assert target is not None, "_hvac_tunable_number_factory must exist"

        # Map relative module name to file path within the package.
        package_root = "custom_components/universal_room_automation"
        for n in ast.walk(target):
            if not isinstance(n, ast.ImportFrom):
                continue
            if n.level == 0:
                continue   # absolute import — skip
            if not n.module:
                continue
            # Resolve relative module to a file path. n.level is the dots.
            # n.level=1 means sibling of number.py (i.e. inside package_root)
            # n.level=2 would mean parent's sibling — not used here.
            if n.level == 1:
                module_file = os.path.join(package_root, n.module.replace(".", "/") + ".py")
            else:
                continue   # nested package — out of scope for this test
            assert os.path.exists(module_file), (
                f"_hvac_tunable_number_factory imports from "
                f"{n.module} but the target file {module_file} does not exist"
            )
            with open(module_file) as mf:
                module_src = mf.read()
            for alias in n.names:
                if alias.name == "*":
                    continue
                # Symbol must be defined as a module-level name.
                # Heuristic: appear at start of line followed by `=` or `:`.
                pattern_assign = f"\n{alias.name} ="
                pattern_typed = f"\n{alias.name}:"
                pattern_def = f"\ndef {alias.name}"
                pattern_class = f"\nclass {alias.name}"
                # Also accept top-of-file occurrence (no leading newline)
                if module_src.startswith(f"{alias.name} =") or module_src.startswith(f"{alias.name}:"):
                    continue
                assert (
                    pattern_assign in module_src
                    or pattern_typed in module_src
                    or pattern_def in module_src
                    or pattern_class in module_src
                ), (
                    f"v4.5.10.1 bug class — _hvac_tunable_number_factory "
                    f"imports `{alias.name}` from `{n.module}` but the "
                    f"symbol is NOT defined in {module_file}. Live HA "
                    f"raises ImportError on entity registration. Either "
                    f"the imported name is wrong, or it lives in a "
                    f"different module."
                )

    def test_seven_v4510_numbers_built(self, number_src):
        """The build function must produce exactly 7 Number classes."""
        idx = number_src.find("def _build_hvac_v4510_numbers")
        assert idx > 0
        body = number_src[idx:idx + 6000]
        # Count factory calls inside the build function
        n = body.count("_hvac_tunable_number_factory(")
        assert n == 7, f"Expected 7 v4.5.10 Number entities; build function makes {n}"

    @pytest.mark.parametrize("expected_name", [
        "Cover Close Threshold",
        "Cover Close Temp",
        "Cover Open Temp",
        "Cover Override Duration",
        "Solar Banking Cool Floor",
        "Fan On Threshold",
        "Fan Off Hysteresis",
    ])
    def test_each_number_has_friendly_name(self, number_src, expected_name):
        assert f'name="{expected_name}"' in number_src, (
            f"v4.5.10 must surface a Number entity with friendly name "
            f"'{expected_name}'"
        )

    def test_setup_entry_includes_v4510_numbers(self, number_src):
        idx = number_src.find("async def async_setup_entry")
        body = number_src[idx:idx + 3000]
        assert "_build_hvac_v4510_numbers()" in body, (
            "async_setup_entry must add the 7 v4.5.10 Number entities"
        )


# ---------------------------------------------------------------------------
# Sub-controller wiring — runtime fields exist + use instance attrs
# ---------------------------------------------------------------------------

class TestSubControllerWiring:
    @pytest.fixture
    def covers_src(self):
        with open("custom_components/universal_room_automation/domain_coordinators/hvac_covers.py") as f:
            return f.read()

    @pytest.fixture
    def predict_src(self):
        with open("custom_components/universal_room_automation/domain_coordinators/hvac_predict.py") as f:
            return f.read()

    def test_cover_controller_has_5_v4510_runtime_fields(self, covers_src):
        idx = covers_src.find("def __init__")
        body = covers_src[idx:idx + 2500]
        for field in (
            "self._cover_close_temp",
            "self._cover_open_temp",
            "self._cover_override_hours",
            "self._solar_start_hour",
            "self._solar_end_hour",
        ):
            assert field in body, f"CoverController must store {field}"

    def test_cover_controller_uses_runtime_fields(self, covers_src):
        # update() must read instance attrs, not module constants
        idx = covers_src.find("async def update(")
        body = covers_src[idx:idx + 3000]
        assert "self._cover_close_temp" in body, (
            "update() must use self._cover_close_temp (not module constant)"
        )
        assert "self._cover_open_temp" in body
        assert "self._solar_start_hour" in body
        assert "self._solar_end_hour" in body

    def test_predictor_has_4_v4510_runtime_fields(self, predict_src):
        idx = predict_src.find("def __init__")
        body = predict_src[idx:idx + 3000]
        for field in (
            "self._solar_bank_floor",
            "self._solar_bank_soc_min",
            "self._precool_forecast_high",
            "self._preheat_forecast_low",
        ):
            assert field in body, f"HVACPredictor must store {field}"

    def test_predictor_uses_runtime_fields_at_decision_sites(self, predict_src):
        # Find _execute_zone_pre_cool — must use self._solar_bank_floor
        idx = predict_src.find("def _execute_zone_pre_cool")
        body = predict_src[idx:idx + 1500]
        assert "self._solar_bank_floor" in body, (
            "_execute_zone_pre_cool must use self._solar_bank_floor (not module constant)"
        )
        # Find _should_solar_bank — must use self._solar_bank_soc_min
        idx = predict_src.find("def _should_solar_bank")
        body = predict_src[idx:idx + 1500]
        assert "self._solar_bank_soc_min" in body
        # _should_weather_pre_cool — must use self._precool_forecast_high
        idx = predict_src.find("def _should_weather_pre_cool")
        body = predict_src[idx:idx + 1500]
        assert "self._precool_forecast_high" in body
        # Pre-heat path — must use self._preheat_forecast_low
        idx = predict_src.find("self._preheat_forecast_low")
        assert idx > 0, (
            "Pre-heat path must use self._preheat_forecast_low somewhere"
        )


# ---------------------------------------------------------------------------
# B — Form-only additions + 11 new CONFs end-to-end
# ---------------------------------------------------------------------------

class TestNewCONFsWiredEndToEnd:
    """All 11 new CONFs (1 master switch + 5 runtime sliders + 5 form-only)
    must be wired: defined → in form → read in __init__ → passed to
    HVACCoordinator → forwarded to sub-controller. Bug Class #32 prevention.
    """

    @pytest.fixture
    def hvac_const_src(self):
        with open("custom_components/universal_room_automation/domain_coordinators/hvac_const.py") as f:
            return f.read()

    @pytest.fixture
    def init_src(self):
        with open("custom_components/universal_room_automation/__init__.py") as f:
            return f.read()

    @pytest.fixture
    def config_flow_src(self):
        with open("custom_components/universal_room_automation/config_flow.py") as f:
            return f.read()

    @pytest.fixture
    def hvac_src(self):
        with open("custom_components/universal_room_automation/domain_coordinators/hvac.py") as f:
            return f.read()

    @pytest.mark.parametrize("conf,default", [
        ("CONF_HVAC_SOLAR_GAIN_COVER_ENABLED", "DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED"),
        ("CONF_HVAC_COVER_CLOSE_TEMP", "DEFAULT_HVAC_COVER_CLOSE_TEMP"),
        ("CONF_HVAC_COVER_OPEN_TEMP", "DEFAULT_HVAC_COVER_OPEN_TEMP"),
        ("CONF_HVAC_COVER_OVERRIDE_HOURS", "DEFAULT_HVAC_COVER_OVERRIDE_HOURS"),
        ("CONF_HVAC_SOLAR_BANK_FLOOR", "DEFAULT_HVAC_SOLAR_BANK_FLOOR"),
        ("CONF_HVAC_COVER_SOLAR_START_HOUR", "DEFAULT_HVAC_COVER_SOLAR_START_HOUR"),
        ("CONF_HVAC_COVER_SOLAR_END_HOUR", "DEFAULT_HVAC_COVER_SOLAR_END_HOUR"),
        ("CONF_HVAC_SOLAR_BANK_SOC_MIN", "DEFAULT_HVAC_SOLAR_BANK_SOC_MIN"),
        ("CONF_HVAC_PRECOOL_FORECAST_HIGH", "DEFAULT_HVAC_PRECOOL_FORECAST_HIGH"),
        ("CONF_HVAC_PREHEAT_FORECAST_LOW", "DEFAULT_HVAC_PREHEAT_FORECAST_LOW"),
    ])
    def test_const_defined(self, hvac_const_src, conf, default):
        assert conf in hvac_const_src, f"{conf} must be defined in hvac_const.py"
        assert default in hvac_const_src, f"{default} must be defined in hvac_const.py"

    @pytest.mark.parametrize("conf", [
        "CONF_HVAC_SOLAR_GAIN_COVER_ENABLED",
        "CONF_HVAC_COVER_CLOSE_TEMP",
        "CONF_HVAC_COVER_OPEN_TEMP",
        "CONF_HVAC_COVER_OVERRIDE_HOURS",
        "CONF_HVAC_SOLAR_BANK_FLOOR",
        "CONF_HVAC_COVER_SOLAR_START_HOUR",
        "CONF_HVAC_COVER_SOLAR_END_HOUR",
        "CONF_HVAC_SOLAR_BANK_SOC_MIN",
        "CONF_HVAC_PRECOOL_FORECAST_HIGH",
        "CONF_HVAC_PREHEAT_FORECAST_LOW",
    ])
    def test_conf_in_form_step(self, config_flow_src, conf):
        idx = config_flow_src.find("async def async_step_coordinator_hvac")
        assert idx > 0
        end = config_flow_src.find("\n    async def ", idx + 1)
        body = config_flow_src[idx:end] if end > 0 else config_flow_src[idx:]
        assert conf in body, (
            f"{conf} must have a form field in coordinator_hvac step "
            f"(Bug Class #32 prevention)"
        )

    @pytest.mark.parametrize("conf", [
        "CONF_HVAC_SOLAR_GAIN_COVER_ENABLED",
        "CONF_HVAC_COVER_CLOSE_TEMP",
        "CONF_HVAC_COVER_OPEN_TEMP",
        "CONF_HVAC_COVER_OVERRIDE_HOURS",
        "CONF_HVAC_SOLAR_BANK_FLOOR",
        "CONF_HVAC_COVER_SOLAR_START_HOUR",
        "CONF_HVAC_COVER_SOLAR_END_HOUR",
        "CONF_HVAC_SOLAR_BANK_SOC_MIN",
        "CONF_HVAC_PRECOOL_FORECAST_HIGH",
        "CONF_HVAC_PREHEAT_FORECAST_LOW",
    ])
    def test_conf_read_in_init(self, init_src, conf):
        assert conf in init_src, (
            f"{conf} must be read in __init__.py and passed to HVACCoordinator"
        )

    def test_hvac_coordinator_accepts_all_v4510_kwargs(self, hvac_src):
        idx = hvac_src.find("def __init__")
        # __init__ signature can span many lines
        body = hvac_src[idx:idx + 3000]
        for kwarg in (
            "solar_gain_cover_enabled",
            "cover_close_temp",
            "cover_open_temp",
            "cover_override_hours",
            "solar_bank_floor",
            "cover_solar_start_hour",
            "cover_solar_end_hour",
            "solar_bank_soc_min",
            "precool_forecast_high",
            "preheat_forecast_low",
        ):
            assert kwarg in body, (
                f"HVACCoordinator.__init__ must accept {kwarg} kwarg"
            )

    def test_hvac_coordinator_forwards_to_sub_controllers(self, hvac_src):
        # CoverController gets the master + 5 cover-related kwargs
        cc_init = hvac_src.find("self._cover_controller = CoverController(")
        assert cc_init > 0
        cc_body = hvac_src[cc_init:cc_init + 800]
        for kwarg in (
            "solar_gain_enabled=solar_gain_cover_enabled",
            "cover_close_temp=cover_close_temp",
            "cover_open_temp=cover_open_temp",
            "cover_override_hours=cover_override_hours",
            "solar_start_hour=cover_solar_start_hour",
            "solar_end_hour=cover_solar_end_hour",
        ):
            assert kwarg in cc_body, (
                f"CoverController constructor must receive {kwarg}"
            )

        # HVACPredictor gets 4 predictor-related kwargs
        pred_init = hvac_src.find("self._predictor = HVACPredictor(")
        assert pred_init > 0
        pred_body = hvac_src[pred_init:pred_init + 600]
        for kwarg in (
            "solar_bank_floor=solar_bank_floor",
            "solar_bank_soc_min=solar_bank_soc_min",
            "precool_forecast_high=precool_forecast_high",
            "preheat_forecast_low=preheat_forecast_low",
        ):
            assert kwarg in pred_body, (
                f"HVACPredictor constructor must receive {kwarg}"
            )


# ---------------------------------------------------------------------------
# Validation — Cover Open Temp must be ≥3°F below Cover Close Temp
# ---------------------------------------------------------------------------

class TestCoverHysteresisValidation:
    """v4.5.10 form-save validation: Cover Open Temp must be at least
    COVER_HYSTERESIS_MIN_GAP (3°F) below Cover Close Temp. Otherwise
    solar-gain logic will flap when outdoor temp wobbles around the
    threshold."""

    @pytest.fixture
    def config_flow_src(self):
        with open("custom_components/universal_room_automation/config_flow.py") as f:
            return f.read()

    @pytest.fixture
    def strings(self):
        with open("custom_components/universal_room_automation/strings.json") as f:
            return json.load(f)

    def test_validation_block_present(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_coordinator_hvac")
        end = config_flow_src.find("\n    async def ", idx + 1)
        body = config_flow_src[idx:end] if end > 0 else config_flow_src[idx:]
        assert "cover_temp_hysteresis_too_small" in body, (
            "v4.5.10: form-save must reject Open/Close pair when gap < 3°F"
        )
        assert "COVER_HYSTERESIS_MIN_GAP" in body

    def test_error_string_localized(self, strings):
        errors = strings["options"]["error"]
        assert "cover_temp_hysteresis_too_small" in errors, (
            "Validation error key must have a friendly localization"
        )
        msg = errors["cover_temp_hysteresis_too_small"]
        assert "3" in msg and "Cover" in msg

    def test_form_show_passes_errors(self, config_flow_src):
        # Find the show_form for coordinator_hvac
        idx = config_flow_src.find('step_id="coordinator_hvac"')
        assert idx > 0
        body = config_flow_src[idx:idx + 200]
        assert "errors=errors" in body, (
            "async_show_form for coordinator_hvac must pass errors dict"
        )


# ---------------------------------------------------------------------------
# C — Label renames
# ---------------------------------------------------------------------------

class TestLabelRenames:
    """v4.5.10 D6: friendly-name only. CONF/entity_id/unique_id preserved."""

    @pytest.fixture
    def switch_src(self):
        with open("custom_components/universal_room_automation/switch.py") as f:
            return f.read()

    @pytest.fixture
    def strings(self):
        with open("custom_components/universal_room_automation/strings.json") as f:
            return json.load(f)

    def test_zone_intelligence_renamed(self, switch_src):
        """HVACZoneIntelligenceSwitch._attr_name → "Per-Zone HVAC Control"."""
        idx = switch_src.find("class HVACZoneIntelligenceSwitch")
        assert idx > 0
        body = switch_src[idx:idx + 2000]
        assert '_attr_name = "Per-Zone HVAC Control"' in body
        # The OLD name must be gone (check the same body slice)
        assert '_attr_name = "Zone Intelligence"' not in body

    def test_zone_intelligence_unique_id_unchanged(self, switch_src):
        """unique_id must NOT change — that would orphan dashboards."""
        idx = switch_src.find("class HVACZoneIntelligenceSwitch")
        body = switch_src[idx:idx + 2000]
        assert 'f"{DOMAIN}_hvac_zone_intelligence"' in body, (
            "unique_id must stay the same — entity_id is derived from this; "
            "renaming would break user dashboards"
        )

    def test_zone_sweep_renamed(self, switch_src):
        idx = switch_src.find("class HVACZoneSweepSwitch")
        assert idx > 0
        body = switch_src[idx:idx + 2000]
        assert '_attr_name = "Vacancy Auto-Off"' in body
        assert '_attr_name = "Zone Sweep"' not in body

    def test_zone_sweep_unique_id_unchanged(self, switch_src):
        idx = switch_src.find("class HVACZoneSweepSwitch")
        body = switch_src[idx:idx + 2000]
        assert 'f"{DOMAIN}_hvac_zone_sweep"' in body

    def test_form_label_for_vacancy_sweep_synced(self, strings):
        """The config-flow form label should also reflect the rename."""
        step = strings["options"]["step"]["coordinator_hvac"]
        assert step["data"]["zone_vacancy_sweep_enabled"] == "Vacancy Auto-Off"


# ---------------------------------------------------------------------------
# Strings + translations
# ---------------------------------------------------------------------------

class TestStringsAndTranslations:
    """All 11 new CONFs must have friendly labels + helper text in BOTH
    strings.json and translations/en.json (per CLAUDE.md sync requirement)."""

    @pytest.fixture
    def strings(self):
        with open("custom_components/universal_room_automation/strings.json") as f:
            return json.load(f)

    @pytest.fixture
    def en_translations(self):
        with open("custom_components/universal_room_automation/translations/en.json") as f:
            return json.load(f)

    @pytest.mark.parametrize("conf_key", [
        "hvac_solar_gain_cover_enabled",
        "hvac_cover_close_temp",
        "hvac_cover_open_temp",
        "hvac_cover_override_hours",
        "hvac_solar_bank_floor",
        "hvac_cover_solar_start_hour",
        "hvac_cover_solar_end_hour",
        "hvac_solar_bank_soc_min",
        "hvac_precool_forecast_high",
        "hvac_preheat_forecast_low",
    ])
    def test_strings_label_present(self, strings, conf_key):
        step = strings["options"]["step"]["coordinator_hvac"]
        assert conf_key in step["data"], (
            f"strings.json coordinator_hvac.data missing label for {conf_key}"
        )
        assert conf_key in step["data_description"], (
            f"strings.json coordinator_hvac.data_description missing helper for {conf_key}"
        )

    @pytest.mark.parametrize("conf_key", [
        "hvac_solar_gain_cover_enabled",
        "hvac_cover_close_temp",
        "hvac_cover_open_temp",
        "hvac_cover_override_hours",
        "hvac_solar_bank_floor",
        "hvac_cover_solar_start_hour",
        "hvac_cover_solar_end_hour",
        "hvac_solar_bank_soc_min",
        "hvac_precool_forecast_high",
        "hvac_preheat_forecast_low",
    ])
    def test_translations_en_synced(self, en_translations, conf_key):
        step = en_translations["options"]["step"]["coordinator_hvac"]
        assert conf_key in step["data"]
        assert conf_key in step["data_description"]


# ---------------------------------------------------------------------------
# Backward compatibility — defaults preserve v4.5.9.x behavior
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    """Defaults must match the prior hardcoded values exactly so users
    who don't reconfigure see identical behavior to v4.5.9.x."""

    @pytest.fixture
    def hvac_const_src(self):
        with open("custom_components/universal_room_automation/domain_coordinators/hvac_const.py") as f:
            return f.read()

    @pytest.mark.parametrize("default,expected_value", [
        ("DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED", "True"),
        ("DEFAULT_HVAC_COVER_CLOSE_TEMP", "85.0"),
        ("DEFAULT_HVAC_COVER_OPEN_TEMP", "80.0"),
        ("DEFAULT_HVAC_COVER_OVERRIDE_HOURS", "2.0"),
        ("DEFAULT_HVAC_SOLAR_BANK_FLOOR", "72.0"),
        ("DEFAULT_HVAC_COVER_SOLAR_START_HOUR", "13"),
        ("DEFAULT_HVAC_COVER_SOLAR_END_HOUR", "18"),
        ("DEFAULT_HVAC_SOLAR_BANK_SOC_MIN", "95"),
        ("DEFAULT_HVAC_PRECOOL_FORECAST_HIGH", "90.0"),
        ("DEFAULT_HVAC_PREHEAT_FORECAST_LOW", "35.0"),
    ])
    def test_default_value(self, hvac_const_src, default, expected_value):
        # Find the assignment line
        idx = hvac_const_src.find(f"{default}: Final")
        assert idx > 0, f"{default} must be declared as Final"
        end = hvac_const_src.find("\n", idx)
        line = hvac_const_src[idx:end]
        assert f"= {expected_value}" in line, (
            f"{default} must equal {expected_value} (preserves v4.5.9.x "
            f"behavior). Got: {line}"
        )

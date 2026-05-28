"""v4.7.3 D1 / D2 / D3 — Baseline Preset Editor + PresetManager override.

Source-grep style (matches project convention). Fast, no running HA required.

Deliverables covered:
  D1 — New config flow step: async_step_hvac_baseline_presets
       + coordinator_hvac menu updated with hvac_baseline_presets option

  D2 — PresetManager.get_seasonal_setpoints() prefers CM entry.options overrides
       over SEASONAL_DEFAULTS with per-CONF granularity and fallback semantics

  D3 — 24 CONF_HVAC_BASELINE_* + 24 DEFAULT_HVAC_BASELINE_* constants in
       hvac_const.py matching SEASONAL_DEFAULTS values
"""

import ast
import importlib
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# HA mock infrastructure (Bug Class #44 pattern — required to import URA modules)
# Must be set up BEFORE any URA imports.
# ---------------------------------------------------------------------------

_UTC = timezone.utc
_identity = lambda fn: fn  # noqa: E731


def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_dt_util_mock = _mock_module(
    "homeassistant.util.dt",
    utcnow=lambda: datetime.now(_UTC),
    now=lambda: datetime.now(),
    UTC=_UTC,
    as_local=lambda dt: dt,
)

_ha_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "callback": _identity,
        "State": MagicMock,
    },
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_platform": {
        "AddEntitiesCallback": MagicMock,
    },
    "homeassistant.helpers.event": {
        "async_track_state_change_event": MagicMock(),
        "async_track_time_interval": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
        "async_dispatcher_connect": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": MagicMock(),
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.restore_state": {"RestoreEntity": MagicMock},
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.storage": {"Store": MagicMock},
    "homeassistant.util": {},
    "homeassistant.util.dt": _dt_util_mock,
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": MagicMock(),
        "SensorStateClass": MagicMock(),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": MagicMock(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": MagicMock(),
        "NumberDeviceClass": MagicMock(),
    },
}

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules["homeassistant.util.dt"] = _dt_util_mock
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc


def _load_submod(name: str) -> types.ModuleType:
    full_name = f"custom_components.universal_room_automation.domain_coordinators.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(
        full_name, os.path.join(_dc_path, f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    setattr(_dc, name, mod)
    return mod


# Load const module (needed for ENTRY_TYPE_COORDINATOR_MANAGER)
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Load hvac_const and hvac_preset
_hvac_const = _load_submod("hvac_const")
_hvac_preset = _load_submod("hvac_preset")


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
def hvac_const_src() -> str:
    with open(
        "custom_components/universal_room_automation/domain_coordinators/hvac_const.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_preset_src() -> str:
    with open(
        "custom_components/universal_room_automation/domain_coordinators/hvac_preset.py"
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
# D3 — 24 CONF + 24 DEFAULT constants
# ===========================================================================


class TestD3ConfConstants:
    """D3: hvac_const.py must export exactly 24 CONF_HVAC_BASELINE_* and matching DEFAULT_* constants."""

    _SEASONS = ["SUMMER", "SHOULDER", "WINTER"]
    _PRESETS = ["HOME", "SLEEP", "AWAY", "VACATION"]
    _DIMS = ["COOL", "HEAT"]

    def _expected_confs(self):
        return [
            f"CONF_HVAC_BASELINE_{s}_{p}_{d}"
            for s in self._SEASONS
            for p in self._PRESETS
            for d in self._DIMS
        ]

    def _expected_defaults(self):
        return [
            f"DEFAULT_HVAC_BASELINE_{s}_{p}_{d}"
            for s in self._SEASONS
            for p in self._PRESETS
            for d in self._DIMS
        ]

    def test_conf_count_matches_seasonal_defaults_shape(self, hvac_const_src):
        """Exactly 3 × 4 × 2 = 24 CONF_HVAC_BASELINE_* constants."""
        confs = [
            name for name in hvac_const_src.split()
            if name.startswith("CONF_HVAC_BASELINE_") and "=" not in name
        ]
        # Count via assignment lines for accuracy
        lines = hvac_const_src.splitlines()
        conf_defs = [l.strip() for l in lines if l.strip().startswith("CONF_HVAC_BASELINE_")]
        assert len(conf_defs) == 24, (
            f"Expected 24 CONF_HVAC_BASELINE_* constants, found {len(conf_defs)}"
        )

    def test_default_count_matches_conf_count(self, hvac_const_src):
        """Exactly 24 DEFAULT_HVAC_BASELINE_* constants — one per CONF."""
        lines = hvac_const_src.splitlines()
        default_defs = [l.strip() for l in lines if l.strip().startswith("DEFAULT_HVAC_BASELINE_")]
        assert len(default_defs) == 24, (
            f"Expected 24 DEFAULT_HVAC_BASELINE_* constants, found {len(default_defs)}"
        )

    def test_every_conf_has_default(self, hvac_const_src):
        """D3 source-contract: every CONF_HVAC_BASELINE_* must have a matching DEFAULT_HVAC_BASELINE_*."""
        for conf_name in self._expected_confs():
            default_name = conf_name.replace("CONF_", "DEFAULT_")
            assert default_name in hvac_const_src, (
                f"Missing DEFAULT constant for {conf_name} — "
                "Bug Class #32: form field must have a runtime-readable default"
            )

    def test_all_expected_confs_present(self, hvac_const_src):
        """All 24 expected CONF names are present in source."""
        for conf_name in self._expected_confs():
            assert conf_name in hvac_const_src, (
                f"Missing CONF constant: {conf_name}"
            )

    def test_defaults_match_seasonal_defaults_values(self):
        """DEFAULT_HVAC_BASELINE_* values must match current SEASONAL_DEFAULTS."""
        hc = _hvac_const  # loaded at module level with HA mocks in place
        sd = hc.SEASONAL_DEFAULTS
        # Verify summer values
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_HOME_COOL == sd["summer"]["home"][0]
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_HOME_HEAT == sd["summer"]["home"][1]
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_COOL == sd["summer"]["sleep"][0]
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_HEAT == sd["summer"]["sleep"][1]
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_AWAY_COOL == sd["summer"]["away"][0]
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_AWAY_HEAT == sd["summer"]["away"][1]
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_VACATION_COOL == sd["summer"]["vacation"][0]
        assert hc.DEFAULT_HVAC_BASELINE_SUMMER_VACATION_HEAT == sd["summer"]["vacation"][1]
        # Spot-check shoulder + winter
        assert hc.DEFAULT_HVAC_BASELINE_SHOULDER_HOME_COOL == sd["shoulder"]["home"][0]
        assert hc.DEFAULT_HVAC_BASELINE_WINTER_SLEEP_COOL == sd["winter"]["sleep"][0]
        assert hc.DEFAULT_HVAC_BASELINE_WINTER_SLEEP_HEAT == sd["winter"]["sleep"][1]

    def test_baseline_min_deadband_exported(self, hvac_const_src):
        """BASELINE_MIN_DEADBAND must be exported from hvac_const.py."""
        assert "BASELINE_MIN_DEADBAND" in hvac_const_src


# ===========================================================================
# D1 — coordinator_hvac menu + baseline_presets step
# ===========================================================================


class TestD1BaselinePresetsMenuAndStep:
    """D1: coordinator_hvac menu must include hvac_baseline_presets; form step must exist."""

    def test_coordinator_hvac_menu_includes_baseline_presets(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_coordinator_hvac(")
        assert idx > 0, "async_step_coordinator_hvac must exist"
        body = config_flow_src[idx:idx + 600]
        assert "hvac_baseline_presets" in body, (
            "coordinator_hvac menu must include hvac_baseline_presets (D1)"
        )

    def test_baseline_presets_step_exists(self, config_flow_src):
        assert "async def async_step_hvac_baseline_presets(" in config_flow_src, (
            "async_step_hvac_baseline_presets must be defined in config_flow.py"
        )

    def test_baseline_presets_step_id(self, config_flow_src):
        assert 'step_id="hvac_baseline_presets"' in config_flow_src, (
            "step_id must be 'hvac_baseline_presets' to match the HA translation key"
        )

    def test_baseline_presets_step_has_24_conf_refs(self, config_flow_src):
        """The form step must reference all 24 CONF keys."""
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets(")
        body = config_flow_src[idx:idx + 8000]
        for season in ["SUMMER", "SHOULDER", "WINTER"]:
            for preset in ["HOME", "SLEEP", "AWAY", "VACATION"]:
                for dim in ["COOL", "HEAT"]:
                    conf_name = f"CONF_HVAC_BASELINE_{season}_{preset}_{dim}"
                    assert conf_name in body, (
                        f"Step body must reference {conf_name}"
                    )

    def test_baseline_presets_validates_deadband(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets(")
        body = config_flow_src[idx:idx + 8000]
        assert "baseline_preset_invalid_deadband" in body, (
            "Step must set errors['base'] = 'baseline_preset_invalid_deadband' "
            "when deadband check fails"
        )
        assert "BASELINE_MIN_DEADBAND" in body, (
            "Step must use BASELINE_MIN_DEADBAND constant for deadband check"
        )

    def test_baseline_presets_saves_to_entry_options(self, config_flow_src):
        idx = config_flow_src.find("async def async_step_hvac_baseline_presets(")
        body = config_flow_src[idx:idx + 8000]
        assert "async_create_entry" in body, (
            "Step must call async_create_entry to persist to entry.options"
        )
        assert "self._config_entry.options" in body, (
            "Step must merge with existing options (not replace them)"
        )

    def test_strings_coordinator_hvac_menu_has_baseline_presets(self, strings):
        opts = strings["options"]["step"]["coordinator_hvac"].get("menu_options", {})
        assert "hvac_baseline_presets" in opts, (
            "strings.json coordinator_hvac menu_options must include hvac_baseline_presets"
        )

    def test_strings_baseline_presets_step_exists(self, strings):
        assert "hvac_baseline_presets" in strings["options"]["step"], (
            "strings.json must have hvac_baseline_presets form step"
        )

    def test_strings_baseline_presets_step_has_24_data_fields(self, strings):
        data = strings["options"]["step"]["hvac_baseline_presets"].get("data", {})
        assert len(data) == 24, (
            f"strings.json hvac_baseline_presets must have 24 data fields, found {len(data)}"
        )

    def test_strings_baseline_presets_has_data_descriptions(self, strings):
        desc = strings["options"]["step"]["hvac_baseline_presets"].get("data_description", {})
        assert len(desc) == 24, (
            f"strings.json hvac_baseline_presets must have 24 data_description entries, found {len(desc)}"
        )

    def test_strings_error_key_exists(self, strings):
        errors = strings["options"].get("error", {})
        assert "baseline_preset_invalid_deadband" in errors, (
            "strings.json must define error key 'baseline_preset_invalid_deadband'"
        )

    def test_translations_coordinator_hvac_menu_has_baseline_presets(self, translations_en):
        opts = translations_en["options"]["step"]["coordinator_hvac"].get("menu_options", {})
        assert "hvac_baseline_presets" in opts

    def test_translations_baseline_presets_step_exists(self, translations_en):
        assert "hvac_baseline_presets" in translations_en["options"]["step"]

    def test_translations_baseline_presets_step_has_24_data_fields(self, translations_en):
        data = translations_en["options"]["step"]["hvac_baseline_presets"].get("data", {})
        assert len(data) == 24

    def test_translations_error_key_exists(self, translations_en):
        errors = translations_en["options"].get("error", {})
        assert "baseline_preset_invalid_deadband" in errors


# ===========================================================================
# D2 — PresetManager.get_seasonal_setpoints() override logic
# ===========================================================================


class TestD2GetSeasonalSetpointsOverride:
    """D2: get_seasonal_setpoints must prefer CM entry.options overrides."""

    def test_get_seasonal_setpoints_reads_cm_options(self, hvac_preset_src):
        """D2: get_seasonal_setpoints must access CM entry options."""
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        assert idx > 0, "get_seasonal_setpoints must exist in hvac_preset.py"
        body = hvac_preset_src[idx:idx + 3000]
        assert "ENTRY_TYPE_COORDINATOR_MANAGER" in body, (
            "D2: must look up CM entry by ENTRY_TYPE_COORDINATOR_MANAGER"
        )
        assert "async_entries" in body, (
            "D2: must iterate config entries to find CM entry"
        )
        assert "ce.options" in body, (
            "D2: must read from CM entry.options"
        )

    def test_get_seasonal_setpoints_falls_back_to_defaults(self, hvac_preset_src):
        """D2: must fall back to SEASONAL_DEFAULTS when CONF is absent from options."""
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        body = hvac_preset_src[idx:idx + 3000]
        # The fallback uses default_pair[0] / default_pair[1]
        assert "default_pair" in body, (
            "D2: must use default_pair as fallback when key absent from cm_options"
        )
        assert "cm_options.get" in body, (
            "D2: must use dict.get() for per-CONF granularity (missing = fallback)"
        )

    def test_get_seasonal_setpoints_uses_baseline_conf_map(self, hvac_preset_src):
        """D2: _BASELINE_CONF_MAP must be used for (season, preset) → CONF key lookup."""
        assert "_BASELINE_CONF_MAP" in hvac_preset_src, (
            "D2: _BASELINE_CONF_MAP must be defined at module level for O(1) lookup"
        )
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        body = hvac_preset_src[idx:idx + 3000]
        assert "_BASELINE_CONF_MAP" in body, (
            "D2: get_seasonal_setpoints must use _BASELINE_CONF_MAP"
        )

    def test_get_seasonal_setpoints_guards_with_try_except(self, hvac_preset_src):
        """D2: CM entry lookup must be wrapped in try/except (Bug Class #4)."""
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        body = hvac_preset_src[idx:idx + 3000]
        assert "except Exception" in body or "except" in body, (
            "D2: CM options lookup must be guarded by try/except"
        )

    def test_d2_uses_override_when_set(self, hvac_preset_src):
        """D2: get_seasonal_setpoints reads cool/heat from cm_options using conf keys.

        Source-grep version — ordering-safe (Bug Class #44).
        Verifies the lookup pattern: cm_options.get(conf_key, default_pair[N]).
        """
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        body = hvac_preset_src[idx:idx + 3000]
        # The override path: cm_options.get(conf_cool_key, ...) and cm_options.get(conf_heat_key, ...)
        assert "conf_cool_key" in body and "conf_heat_key" in body, (
            "D2: get_seasonal_setpoints must use conf_cool_key and conf_heat_key "
            "to look up overrides in cm_options"
        )
        # float() conversion applied to both values
        assert "float(cm_options.get(" in body or "float(" in body, (
            "D2: result values must be float() converted from cm_options"
        )
        # The override values are returned as a tuple
        assert "return (cool, heat)" in body, (
            "D2: must return (cool, heat) tuple, not the raw default_pair"
        )

    def test_d2_falls_back_to_defaults_when_no_overrides(self, hvac_preset_src):
        """D2: fallback to default_pair when key absent from cm_options.

        Source-grep version — ordering-safe (Bug Class #44).
        Verifies that .get() with default_pair[N] is used (not None or error).
        """
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        body = hvac_preset_src[idx:idx + 3000]
        # default_pair[0] and default_pair[1] used as fallback
        assert "default_pair[0]" in body, (
            "D2: fallback must use default_pair[0] for cool when CONF absent from cm_options"
        )
        assert "default_pair[1]" in body, (
            "D2: fallback must use default_pair[1] for heat when CONF absent from cm_options"
        )

    def test_d2_per_conf_granularity(self, hvac_preset_src):
        """D2: per-CONF granularity — each key fetched independently via .get().

        Source-grep version — ordering-safe (Bug Class #44).
        Verifies that cool and heat each do their own .get() with their own default.
        """
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        body = hvac_preset_src[idx:idx + 3000]
        # Two separate cm_options.get calls — one per dimension
        cool_get_count = body.count("cm_options.get(conf_cool_key")
        heat_get_count = body.count("cm_options.get(conf_heat_key")
        assert cool_get_count >= 1, (
            "D2: cool must be fetched via cm_options.get(conf_cool_key, ...)"
        )
        assert heat_get_count >= 1, (
            "D2: heat must be fetched via cm_options.get(conf_heat_key, ...)"
        )

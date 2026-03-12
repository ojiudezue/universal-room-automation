"""Tests for TOURateEngine — JSON loading, period aliases, rate_source, fallbacks."""

import pytest
import json
import tempfile
import os
from datetime import datetime
from unittest.mock import MagicMock
import sys
import types
import importlib

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_tou"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    PEC_TOU_RATES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(tmpdir, filename, data):
    """Write a JSON file to tmpdir and return the path."""
    path = os.path.join(tmpdir, filename)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


_VALID_JSON = {
    "utility": "TestCo",
    "effective_date": "2026-06-01",
    "seasons": {
        "summer": {
            "months": [6, 7, 8, 9],
            "periods": {
                "off_peak": {"hours": [[0, 14], [21, 24]], "import_rate": 0.04, "export_rate": 0.04},
                "mid_peak": {"hours": [[14, 16], [20, 21]], "import_rate": 0.09, "export_rate": 0.09},
                "peak":     {"hours": [[16, 20]], "import_rate": 0.16, "export_rate": 0.16},
            },
        },
        "shoulder": {
            "months": [3, 4, 5, 10, 11],
            "periods": {
                "off_peak": {"hours": [[0, 17], [21, 24]], "import_rate": 0.04, "export_rate": 0.04},
                "mid_peak": {"hours": [[17, 21]], "import_rate": 0.08, "export_rate": 0.08},
            },
        },
        "winter": {
            "months": [12, 1, 2],
            "periods": {
                "off_peak": {"hours": [[0, 5], [9, 17], [21, 24]], "import_rate": 0.04, "export_rate": 0.04},
                "mid_peak": {"hours": [[5, 9], [17, 21]], "import_rate": 0.08, "export_rate": 0.08},
            },
        },
    },
    "fixed_charges": {
        "service_availability_monthly": 30.0,
        "delivery_per_kwh": 0.02,
        "transmission_per_kwh": 0.01,
    },
}


# ── Default (built-in) ──────────────────────────────────────────────────────

class TestDefaultEngine:
    """TOURateEngine with no file uses PEC defaults."""

    def test_default_rate_source(self):
        engine = TOURateEngine()
        assert engine.rate_source == "built-in PEC 2026"

    def test_default_season_march_is_shoulder(self):
        engine = TOURateEngine()
        now = datetime(2026, 3, 15, 18, 0)
        assert engine.get_season(now) == "shoulder"

    def test_default_rate_source_in_period_info(self):
        engine = TOURateEngine()
        info = engine.get_period_info()
        assert info["rate_source"] == "built-in PEC 2026"


# ── from_json_file — happy path ─────────────────────────────────────────────

class TestFromJsonFile:
    """Loading rates from a valid JSON file."""

    def test_loads_valid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", _VALID_JSON)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert engine._rate_file_loaded is True
            assert "TestCo" in engine.rate_source

    def test_rates_match_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", _VALID_JSON)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            now = datetime(2026, 7, 15, 17, 0)  # summer, hour 17 = peak
            assert engine.get_current_period(now) == "peak"
            assert engine.get_current_rate(now) == 0.16

    def test_fixed_charges_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", _VALID_JSON)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert engine._fixed["delivery_per_kwh"] == 0.02
            assert engine._fixed["service_availability"] == 30.0

    def test_rate_source_includes_utility_and_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", _VALID_JSON)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert "TestCo" in engine.rate_source
            assert "2026-06-01" in engine.rate_source


# ── from_json_file — fallbacks ───────────────────────────────────────────────

class TestFromJsonFileFallbacks:
    """Fallback to PEC defaults on missing/invalid file."""

    def test_missing_file_returns_defaults(self):
        engine = TOURateEngine.from_json_file("/nonexistent/path", "tou.json")
        assert engine._rate_file_loaded is False
        assert engine.rate_source == "built-in PEC 2026"

    def test_invalid_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "tou.json")
            with open(path, "w") as f:
                f.write("NOT VALID JSON {{{")
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert engine._rate_file_loaded is False
            assert engine.rate_source == "built-in PEC 2026"

    def test_missing_fixed_charges_uses_defaults(self):
        """JSON without fixed_charges should use PEC defaults for those."""
        data = {**_VALID_JSON}
        del data["fixed_charges"]
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert engine._fixed["service_availability"] == 32.50
            assert engine._fixed["delivery_per_kwh"] == 0.022546


# ── Period alias normalization ───────────────────────────────────────────────

class TestPeriodAliases:
    """JSON with variant period names should be normalized."""

    def test_on_peak_normalized_to_peak(self):
        data = json.loads(json.dumps(_VALID_JSON))
        summer_periods = data["seasons"]["summer"]["periods"]
        summer_periods["on_peak"] = summer_periods.pop("peak")

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            now = datetime(2026, 7, 15, 17, 0)  # summer, hour 17
            assert engine.get_current_period(now) == "peak"

    def test_on_peak_rate_accessible(self):
        data = json.loads(json.dumps(_VALID_JSON))
        summer_periods = data["seasons"]["summer"]["periods"]
        summer_periods["on_peak"] = summer_periods.pop("peak")

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            now = datetime(2026, 7, 15, 17, 0)
            assert engine.get_current_rate(now) == 0.16

    def test_hyphenated_aliases(self):
        """'off-peak', 'mid-peak', 'on-peak' should all normalize."""
        data = json.loads(json.dumps(_VALID_JSON))
        summer = data["seasons"]["summer"]["periods"]
        summer["off-peak"] = summer.pop("off_peak")
        summer["mid-peak"] = summer.pop("mid_peak")
        summer["on-peak"] = summer.pop("peak")

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert engine.get_current_period(datetime(2026, 7, 15, 10, 0)) == "off_peak"
            assert engine.get_current_period(datetime(2026, 7, 15, 15, 0)) == "mid_peak"
            assert engine.get_current_period(datetime(2026, 7, 15, 17, 0)) == "peak"

    def test_no_separator_aliases(self):
        """'offpeak', 'midpeak', 'onpeak' should all normalize."""
        data = json.loads(json.dumps(_VALID_JSON))
        summer = data["seasons"]["summer"]["periods"]
        summer["offpeak"] = summer.pop("off_peak")
        summer["midpeak"] = summer.pop("mid_peak")
        summer["onpeak"] = summer.pop("peak")

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert engine.get_current_period(datetime(2026, 7, 15, 10, 0)) == "off_peak"
            assert engine.get_current_period(datetime(2026, 7, 15, 15, 0)) == "mid_peak"
            assert engine.get_current_period(datetime(2026, 7, 15, 17, 0)) == "peak"


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    """Invalid period names are skipped; missing off_peak falls back to defaults."""

    def test_unknown_period_ignored(self):
        data = json.loads(json.dumps(_VALID_JSON))
        # Add a bogus period to shoulder
        data["seasons"]["shoulder"]["periods"]["super_off_peak"] = {
            "hours": [[0, 5]], "rate": 0.01,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            # Should still load successfully, ignoring the unknown period
            assert engine._rate_file_loaded is True
            # shoulder mid_peak should still work
            now = datetime(2026, 3, 15, 18, 0)
            assert engine.get_current_period(now) == "mid_peak"

    def test_missing_off_peak_falls_back(self):
        """If a season is missing off_peak, fall back to PEC defaults entirely."""
        data = json.loads(json.dumps(_VALID_JSON))
        del data["seasons"]["shoulder"]["periods"]["off_peak"]
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            assert engine._rate_file_loaded is False
            assert engine.rate_source == "built-in PEC 2026"


# ── Separate import/export rates ─────────────────────────────────────────────

class TestSeparateImportExport:
    """JSON can specify different import and export rates per period."""

    def test_asymmetric_rates(self):
        data = json.loads(json.dumps(_VALID_JSON))
        # Make shoulder mid_peak asymmetric
        data["seasons"]["shoulder"]["periods"]["mid_peak"]["import_rate"] = 0.10
        data["seasons"]["shoulder"]["periods"]["mid_peak"]["export_rate"] = 0.07

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            now = datetime(2026, 3, 15, 18, 0)  # shoulder, hour 18 = mid_peak
            assert engine.get_current_rate(now) == 0.10
            assert engine.get_export_rate(now) == 0.07

    def test_symmetric_rate_fallback(self):
        """JSON with only 'rate' (no import_rate/export_rate) sets both to the same value."""
        data = json.loads(json.dumps(_VALID_JSON))
        # Replace import_rate/export_rate with single "rate" for shoulder mid_peak
        shoulder_mid = data["seasons"]["shoulder"]["periods"]["mid_peak"]
        del shoulder_mid["import_rate"]
        del shoulder_mid["export_rate"]
        shoulder_mid["rate"] = 0.085

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            now = datetime(2026, 3, 15, 18, 0)
            assert engine.get_current_rate(now) == 0.085
            assert engine.get_export_rate(now) == 0.085

    def test_import_rate_overrides_rate(self):
        """If both 'rate' and 'import_rate' exist, import_rate wins."""
        data = json.loads(json.dumps(_VALID_JSON))
        shoulder_mid = data["seasons"]["shoulder"]["periods"]["mid_peak"]
        shoulder_mid["rate"] = 0.05  # should be ignored
        shoulder_mid["import_rate"] = 0.10
        shoulder_mid["export_rate"] = 0.07

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_json(tmpdir, "tou.json", data)
            engine = TOURateEngine.from_json_file(tmpdir, "tou.json")
            now = datetime(2026, 3, 15, 18, 0)
            assert engine.get_current_rate(now) == 0.10
            assert engine.get_export_rate(now) == 0.07

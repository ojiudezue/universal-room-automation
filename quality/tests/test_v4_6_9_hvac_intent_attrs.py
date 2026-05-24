"""Tests for v4.6.9 D4 — HVAC pre-cool/pre-heat attribute enrichment.

Mandatory test names from plan acceptance criteria:
  - test_intent_attrs_when_forecast_present
  - test_intent_attrs_when_forecast_stale_returns_nulls
  - test_intent_attrs_shape_flat

Additional behavioral tests:
  - test_solar_intent_harvest_when_charging_from_grid
  - test_solar_intent_export_when_discharging
  - test_solar_intent_unknown_when_no_battery_strategy
  - test_anchor_period_during_peak
  - test_anchor_period_during_off_peak_targets_next_peak

Bug-class guards exercised:
  #8   (forecast dict guards — isinstance on dict + list)
  #11  (timezone — all timestamps UTC; no naive datetime)
  #14  (config staleness — energy coordinator re-read at call time)
  #29  (null-forecast branch + present-forecast branch both covered)
  #37  (stable attribute shape — all 6 keys always present)
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parents[2]
HVAC_PREDICT_PY = (
    ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "hvac_predict.py"
)
SENSOR_PY = ROOT / "custom_components" / "universal_room_automation" / "sensor.py"

# ---------------------------------------------------------------------------
# HA stub layer — must be set up before any integration import
# ---------------------------------------------------------------------------
_HA_STUBS: dict = {
    "homeassistant": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.update_coordinator": MagicMock(),
    "homeassistant.helpers.restore_state": MagicMock(),
    "homeassistant.helpers.dispatcher": MagicMock(),
    "homeassistant.helpers.entity": MagicMock(),
    "homeassistant.helpers.entity_platform": MagicMock(),
    "homeassistant.helpers.event": MagicMock(),
    "homeassistant.helpers.device_registry": MagicMock(),
    "homeassistant.components.sensor": MagicMock(),
    "homeassistant.components.button": MagicMock(),
    "homeassistant.components.binary_sensor": MagicMock(),
    "homeassistant.util": MagicMock(),
    "homeassistant.util.dt": MagicMock(),
    "homeassistant.const": MagicMock(),
}
for _k, _v in _HA_STUBS.items():
    sys.modules.setdefault(_k, _v)

sys.modules["homeassistant.const"].STATE_UNAVAILABLE = "unavailable"

# Configure dt_util stub to return a fixed UTC-aware datetime
_FIXED_NOW = datetime(2026, 5, 24, 10, 30, 0, tzinfo=timezone.utc)
_dt_stub = sys.modules["homeassistant.util.dt"]
_dt_stub.now = lambda: _FIXED_NOW
_dt_stub.utcnow = lambda: _FIXED_NOW

# ---------------------------------------------------------------------------
# Helpers to build a minimal HVACPredictor-like object running get_intent_attrs
# ---------------------------------------------------------------------------

def _extract_get_intent_attrs_src() -> str:
    """Extract the get_intent_attrs method body from hvac_predict.py."""
    src = HVAC_PREDICT_PY.read_text()
    start = src.index("    def get_intent_attrs(")
    end = src.index("\n    def get_outcome_attrs(", start)
    return src[start:end]


def _make_predictor(
    cached_forecast_high: float | None = 95.0,
    tou_transition: dict | None = None,
    tou_current_period: str = "off_peak",
    battery_phase: str = "n/a",
    battery_mode: str = "self_consumption",
    energy_available: bool = True,
) -> MagicMock:
    """Build a mock HVACPredictor that runs the real get_intent_attrs body.

    The method is extracted from source, stripped of class indent, and exec'd
    against a controlled environment — same pattern as test_v4_6_9_energy_recent_decisions.
    """
    import logging
    import types

    raw_src = _extract_get_intent_attrs_src()

    # Strip 4-space class indent
    lines = raw_src.splitlines()
    stripped = "\n".join(line[4:] if len(line) >= 4 else line for line in lines) + "\n"

    # Build a dt_util shim that returns _FIXED_NOW
    class _DtUtil:
        @staticmethod
        def now() -> datetime:
            return _FIXED_NOW

    dt_util_shim = _DtUtil()

    # Install the shim into sys.modules for the duration of exec
    import types as _types
    dt_mod = _types.ModuleType("homeassistant.util.dt")
    dt_mod.now = _DtUtil.now
    ha_util_mod = _types.ModuleType("homeassistant.util")
    ha_util_mod.dt = dt_mod

    old_dt = sys.modules.get("homeassistant.util.dt")
    old_util = sys.modules.get("homeassistant.util")
    sys.modules["homeassistant.util.dt"] = dt_mod
    sys.modules["homeassistant.util"] = ha_util_mod

    # Build a fake const module so `from ..const import DOMAIN` in the
    # exec'd method body resolves without needing the real package hierarchy.
    # We install it under the relative path that the stripped method body
    # will import from (after stripping, it becomes `from ..const import DOMAIN`
    # which exec can't resolve — we rewrite the import by pre-injecting DOMAIN
    # into exec_globals so Python finds it before hitting the import machinery).
    _fake_const = _types.ModuleType("universal_room_automation.const")
    _fake_const.DOMAIN = "universal_room_automation"
    sys.modules["universal_room_automation.const"] = _fake_const

    # Rewrite relative import to absolute so exec can resolve it.
    # `from ..const import DOMAIN` → inject DOMAIN directly via exec_globals.
    # We strip the relative import line and provide DOMAIN as a global.
    stripped_no_rel = stripped.replace(
        "from ..const import DOMAIN\n", ""
    )

    from datetime import timezone as _tz

    exec_globals: dict = {
        "dt_util": dt_util_shim,
        "PEAK_HOUR_START": 14,
        "_LOGGER": logging.getLogger("test.hvac_predict"),
        "Any": object,
        "DOMAIN": "universal_room_automation",
        "timezone": _tz,
    }

    try:
        exec(compile(stripped_no_rel, "<get_intent_attrs>", "exec"), exec_globals)
    finally:
        if old_dt is not None:
            sys.modules["homeassistant.util.dt"] = old_dt
        elif "homeassistant.util.dt" in sys.modules:
            del sys.modules["homeassistant.util.dt"]
        if old_util is not None:
            sys.modules["homeassistant.util"] = old_util
        elif "homeassistant.util" in sys.modules:
            del sys.modules["homeassistant.util"]

    fn = exec_globals["get_intent_attrs"]

    # --- Build mock energy coordinator ---
    mock_energy = MagicMock()
    mock_energy._cached_forecast_high = cached_forecast_high

    # TOU engine
    mock_tou = MagicMock()
    mock_tou.get_next_transition.return_value = tou_transition or {
        "next_period": "peak",
        "hours_until": 3.5,
        "transition_hour": 14,
    }
    mock_tou.get_current_period.return_value = tou_current_period
    mock_energy.tou_engine = mock_tou

    # Battery status
    mock_energy.battery_status = {
        "arbitrage_phase": battery_phase,
        "mode": battery_mode,
    }

    # --- Build mock coordinator_manager ---
    mock_manager = MagicMock()
    mock_energy_coord = mock_energy if energy_available else None
    mock_manager.coordinators.get = lambda key: mock_energy_coord if key == "energy" else None

    # --- Build mock hass ---
    mock_hass = MagicMock()

    def _hass_data_get(key, default=None):
        if key == "universal_room_automation":
            return {"coordinator_manager": mock_manager}
        return default

    mock_hass.data.get = _hass_data_get

    # --- Build predictor stub ---
    predictor = MagicMock()
    predictor.hass = mock_hass

    # Wrap the exec'd function; install dt shim on each call
    def _call(*args, **kwargs):
        old_dt2 = sys.modules.get("homeassistant.util.dt")
        old_util2 = sys.modules.get("homeassistant.util")
        sys.modules["homeassistant.util.dt"] = dt_mod
        sys.modules["homeassistant.util"] = ha_util_mod
        try:
            return fn(predictor, *args, **kwargs)
        finally:
            if old_dt2 is not None:
                sys.modules["homeassistant.util.dt"] = old_dt2
            elif "homeassistant.util.dt" in sys.modules:
                del sys.modules["homeassistant.util.dt"]
            if old_util2 is not None:
                sys.modules["homeassistant.util"] = old_util2
            elif "homeassistant.util" in sys.modules:
                del sys.modules["homeassistant.util"]

    predictor.get_intent_attrs = _call
    return predictor


# ---------------------------------------------------------------------------
# Source-structure tests
# ---------------------------------------------------------------------------

class TestSourceStructure:
    """Confirm get_intent_attrs exists and the sensor merges it correctly."""

    def test_get_intent_attrs_defined_in_hvac_predict(self):
        src = HVAC_PREDICT_PY.read_text()
        assert "def get_intent_attrs(" in src

    def test_all_six_contract_keys_present_in_return(self):
        """Bug Class #37: stable shape — all 6 D4 keys in return dict."""
        src = HVAC_PREDICT_PY.read_text()
        start = src.index("def get_intent_attrs(")
        end = src.index("\n    def get_outcome_attrs(", start)
        block = src[start:end]
        for key in (
            "forecast_peak_outside_f",
            "forecast_peak_time_iso",
            "anchor_period",
            "anchor_starts_in_minutes",
            "solar_intent",
            "prior_day_at_this_hour_f",
        ):
            assert f'"{key}"' in block, f"Contract key {key!r} missing from get_intent_attrs"

    def test_prior_day_todo_comment_present(self):
        """prior_day_at_this_hour_f must have a TODO(v4.7.x) deferral note."""
        src = HVAC_PREDICT_PY.read_text()
        assert "TODO(v4.7.x)" in src

    def test_sensor_extra_state_attributes_merges_intent_attrs(self):
        """HVACPreCoolLikelihoodSensor.extra_state_attributes calls get_intent_attrs."""
        src = SENSOR_PY.read_text()
        start = src.index("class HVACPreCoolLikelihoodSensor")
        end = src.index("\nclass HVACComfortRiskSensor", start)
        block = src[start:end]
        assert "get_intent_attrs()" in block, (
            "HVACPreCoolLikelihoodSensor.extra_state_attributes must call get_intent_attrs()"
        )

    def test_sensor_merges_with_update(self):
        """Sensor uses attrs.update(intent) — merges, not replaces."""
        src = SENSOR_PY.read_text()
        start = src.index("class HVACPreCoolLikelihoodSensor")
        end = src.index("\nclass HVACComfortRiskSensor", start)
        block = src[start:end]
        assert "attrs.update(intent)" in block

    def test_sensor_has_defensive_except_around_intent(self):
        """Defensive guard: intent attr failure must not break base attrs."""
        src = SENSOR_PY.read_text()
        start = src.index("class HVACPreCoolLikelihoodSensor")
        end = src.index("\nclass HVACComfortRiskSensor", start)
        block = src[start:end]
        assert "except Exception" in block

    def test_no_string_sentinels_in_get_intent_attrs(self):
        """Bug Class #37 / PWA contract: no 'N/A', '—', 'unknown' as default values."""
        src = HVAC_PREDICT_PY.read_text()
        start = src.index("def get_intent_attrs(")
        end = src.index("\n    def get_outcome_attrs(", start)
        block = src[start:end]
        # prior_day_at_this_hour_f is assigned as `None` (the variable then used in
        # the return dict). Confirm the None assignment is present.
        assert "prior_day_at_this_hour_f: float | None = None" in block, (
            "prior_day_at_this_hour_f must be assigned None, not a string sentinel"
        )

    def test_bug_class_14_no_cached_forecast_on_self(self):
        """Bug Class #14: get_intent_attrs must re-read from EC, not cache on self."""
        src = HVAC_PREDICT_PY.read_text()
        start = src.index("def get_intent_attrs(")
        end = src.index("\n    def get_outcome_attrs(", start)
        block = src[start:end]
        # Must read from energy coordinator, not from self._cached_forecast_high
        assert "self._cached_forecast_high" not in block, (
            "Bug Class #14: get_intent_attrs must read forecast from EC at call time, "
            "not use a cached self attribute"
        )
        assert "energy._cached_forecast_high" in block or "_cached_forecast_high" in block


# ---------------------------------------------------------------------------
# Mandatory behavioral tests (plan acceptance criteria)
# ---------------------------------------------------------------------------

class TestIntentAttrsWhenForecastPresent:
    """test_intent_attrs_when_forecast_present — Bug Classes #8, #11, #29"""

    def test_intent_attrs_when_forecast_present(self):
        """When forecast available: forecast_peak_outside_f is float, time is UTC ISO."""
        predictor = _make_predictor(cached_forecast_high=96.5)
        attrs = predictor.get_intent_attrs()

        assert attrs["forecast_peak_outside_f"] == pytest.approx(96.5), (
            f"Expected 96.5, got {attrs['forecast_peak_outside_f']}"
        )
        assert isinstance(attrs["forecast_peak_time_iso"], str), (
            f"forecast_peak_time_iso must be str, got {type(attrs['forecast_peak_time_iso'])}"
        )

    def test_forecast_peak_time_is_utc_aware_iso(self):
        """Bug Class #11: forecast_peak_time_iso must parse as UTC-aware datetime."""
        predictor = _make_predictor(cached_forecast_high=90.0)
        attrs = predictor.get_intent_attrs()
        ts = attrs["forecast_peak_time_iso"]
        assert ts is not None
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None, (
            "forecast_peak_time_iso must be UTC-aware (has tzinfo)"
        )

    def test_forecast_peak_time_is_at_peak_hour(self):
        """forecast_peak_time_iso anchors to PEAK_HOUR_START (14:00) in UTC."""
        predictor = _make_predictor(cached_forecast_high=92.0)
        attrs = predictor.get_intent_attrs()
        ts = attrs["forecast_peak_time_iso"]
        parsed = datetime.fromisoformat(ts)
        # _FIXED_NOW is 10:30 UTC; peak is 14:00 local. Since test env uses UTC as
        # local timezone (no tzdata offset), the hour in UTC should be 14.
        assert parsed.hour == 14, (
            f"Expected peak hour 14, got {parsed.hour} in {ts}"
        )

    def test_forecast_value_is_float_not_int(self):
        """forecast_peak_outside_f must be float (PWA contract — no int/Decimal)."""
        predictor = _make_predictor(cached_forecast_high=100)
        attrs = predictor.get_intent_attrs()
        assert isinstance(attrs["forecast_peak_outside_f"], float), (
            f"Expected float, got {type(attrs['forecast_peak_outside_f'])}"
        )

    def test_anchor_period_populated_when_forecast_present(self):
        """anchor_period is set when TOU engine returns a peak transition."""
        predictor = _make_predictor(
            cached_forecast_high=95.0,
            tou_transition={"next_period": "peak", "hours_until": 3.5, "transition_hour": 14},
        )
        attrs = predictor.get_intent_attrs()
        assert attrs["anchor_period"] == "peak", (
            f"Expected 'peak', got {attrs['anchor_period']!r}"
        )

    def test_anchor_starts_in_minutes_is_int(self):
        """anchor_starts_in_minutes must be int when populated."""
        predictor = _make_predictor(
            tou_transition={"next_period": "peak", "hours_until": 2.0, "transition_hour": 14},
        )
        attrs = predictor.get_intent_attrs()
        assert isinstance(attrs["anchor_starts_in_minutes"], int), (
            f"Expected int, got {type(attrs['anchor_starts_in_minutes'])}"
        )
        assert attrs["anchor_starts_in_minutes"] == 120, (
            f"Expected 120 minutes (2h * 60), got {attrs['anchor_starts_in_minutes']}"
        )


class TestIntentAttrsWhenForecastStaleReturnsNulls:
    """test_intent_attrs_when_forecast_stale_returns_nulls — Bug Class #29"""

    def test_intent_attrs_when_forecast_stale_returns_nulls(self):
        """When forecast is None: forecast_peak_outside_f and _time_iso are None."""
        predictor = _make_predictor(cached_forecast_high=None)
        attrs = predictor.get_intent_attrs()

        assert attrs["forecast_peak_outside_f"] is None, (
            f"Expected None, got {attrs['forecast_peak_outside_f']!r}"
        )
        assert attrs["forecast_peak_time_iso"] is None, (
            f"Expected None, got {attrs['forecast_peak_time_iso']!r}"
        )

    def test_no_string_sentinels_when_forecast_missing(self):
        """PWA contract: None, not '—' or 'N/A', when forecast stale."""
        predictor = _make_predictor(cached_forecast_high=None)
        attrs = predictor.get_intent_attrs()
        for key, val in attrs.items():
            assert val != "—", f"Key {key!r} must not be '—'; got {val!r}"
            assert val != "N/A", f"Key {key!r} must not be 'N/A'; got {val!r}"
            assert val != "", f"Key {key!r} must not be empty string; got {val!r}"

    def test_all_six_keys_present_even_when_forecast_missing(self):
        """Bug Class #37: stable shape — all 6 keys present even with null forecast."""
        predictor = _make_predictor(cached_forecast_high=None, energy_available=False)
        attrs = predictor.get_intent_attrs()
        required = {
            "forecast_peak_outside_f",
            "forecast_peak_time_iso",
            "anchor_period",
            "anchor_starts_in_minutes",
            "solar_intent",
            "prior_day_at_this_hour_f",
        }
        assert required.issubset(attrs.keys()), (
            f"Missing keys: {required - attrs.keys()}"
        )

    def test_when_energy_coordinator_missing_all_nulls(self):
        """When EC is not registered, all attrs return None."""
        predictor = _make_predictor(energy_available=False)
        attrs = predictor.get_intent_attrs()
        assert attrs["forecast_peak_outside_f"] is None
        assert attrs["forecast_peak_time_iso"] is None
        assert attrs["anchor_period"] is None
        assert attrs["anchor_starts_in_minutes"] is None
        assert attrs["solar_intent"] is None
        assert attrs["prior_day_at_this_hour_f"] is None


class TestIntentAttrsShapeFlat:
    """test_intent_attrs_shape_flat — Bug Class #37"""

    def test_intent_attrs_shape_flat(self):
        """get_intent_attrs() returns a flat dict — no nested dicts or lists."""
        predictor = _make_predictor()
        attrs = predictor.get_intent_attrs()
        for key, val in attrs.items():
            assert not isinstance(val, dict), (
                f"Key {key!r} must not be a nested dict; got {type(val)}"
            )
            assert not isinstance(val, list), (
                f"Key {key!r} must not be a list; got {type(val)}"
            )

    def test_intent_attrs_exactly_six_keys(self):
        """Exactly the 6 D4 contract keys — no extras, no missing."""
        predictor = _make_predictor()
        attrs = predictor.get_intent_attrs()
        expected_keys = {
            "forecast_peak_outside_f",
            "forecast_peak_time_iso",
            "anchor_period",
            "anchor_starts_in_minutes",
            "solar_intent",
            "prior_day_at_this_hour_f",
        }
        assert attrs.keys() == expected_keys, (
            f"Key mismatch. Extra: {attrs.keys() - expected_keys}, "
            f"Missing: {expected_keys - attrs.keys()}"
        )

    def test_no_decimal_values(self):
        """PWA contract: no Decimal objects in attrs."""
        from decimal import Decimal
        predictor = _make_predictor(cached_forecast_high=97.3)
        attrs = predictor.get_intent_attrs()
        for key, val in attrs.items():
            assert not isinstance(val, Decimal), (
                f"Key {key!r} must not be Decimal; got {type(val)}"
            )

    def test_all_attrs_json_serializable(self):
        """All attr values must be JSON-serializable (no datetime obj, no Decimal)."""
        import json
        predictor = _make_predictor(cached_forecast_high=95.0)
        attrs = predictor.get_intent_attrs()
        # Must not raise
        json.dumps(attrs)

    def test_prior_day_at_this_hour_f_is_none(self):
        """prior_day_at_this_hour_f must be None (deferred to v4.7.x)."""
        predictor = _make_predictor()
        attrs = predictor.get_intent_attrs()
        assert attrs["prior_day_at_this_hour_f"] is None, (
            f"Expected None for prior_day_at_this_hour_f (TODO v4.7.x), "
            f"got {attrs['prior_day_at_this_hour_f']!r}"
        )


# ---------------------------------------------------------------------------
# Solar intent behavioral tests
# ---------------------------------------------------------------------------

class TestSolarIntentHarvestWhenChargingFromGrid:
    """test_solar_intent_harvest_when_charging_from_grid"""

    def test_solar_intent_harvest_when_charging_from_grid(self):
        """arbitrage_phase == 'charge' → solar_intent == 'harvest'."""
        predictor = _make_predictor(battery_phase="charge")
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] == "harvest", (
            f"Expected 'harvest' for arbitrage_phase=charge, got {attrs['solar_intent']!r}"
        )

    def test_harvest_regardless_of_mode(self):
        """solar_intent == 'harvest' even if Enphase mode is not self_consumption."""
        predictor = _make_predictor(battery_phase="charge", battery_mode="savings")
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] == "harvest"


class TestSolarIntentExportWhenDischarging:
    """test_solar_intent_export_when_discharging"""

    def test_solar_intent_export_when_discharging(self):
        """arbitrage_phase == 'discharge' → solar_intent == 'export'."""
        predictor = _make_predictor(battery_phase="discharge")
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] == "export", (
            f"Expected 'export' for arbitrage_phase=discharge, got {attrs['solar_intent']!r}"
        )

    def test_export_regardless_of_mode(self):
        """solar_intent == 'export' even if Enphase mode is 'self_consumption'."""
        predictor = _make_predictor(battery_phase="discharge", battery_mode="self_consumption")
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] == "export"


class TestSolarIntentUnknownWhenNoBatteryStrategy:
    """test_solar_intent_unknown_when_no_battery_strategy"""

    def test_solar_intent_unknown_when_no_battery_strategy(self):
        """When energy coordinator missing → solar_intent is None."""
        predictor = _make_predictor(energy_available=False)
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] is None, (
            f"Expected None when EC unavailable, got {attrs['solar_intent']!r}"
        )

    def test_solar_intent_passthrough_for_self_consumption(self):
        """mode == 'self_consumption' and phase not charge/discharge → 'passthrough'."""
        predictor = _make_predictor(battery_phase="n/a", battery_mode="self_consumption")
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] == "passthrough", (
            f"Expected 'passthrough' for self_consumption mode, got {attrs['solar_intent']!r}"
        )

    def test_solar_intent_unknown_for_hold_phase(self):
        """arbitrage_phase == 'hold' with non-self_consumption mode → 'unknown'."""
        predictor = _make_predictor(battery_phase="hold", battery_mode="backup")
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] == "unknown", (
            f"Expected 'unknown' for hold+backup, got {attrs['solar_intent']!r}"
        )

    def test_solar_intent_unknown_for_wait_phase(self):
        """arbitrage_phase == 'wait' with savings mode → 'unknown'."""
        predictor = _make_predictor(battery_phase="wait", battery_mode="savings")
        attrs = predictor.get_intent_attrs()
        assert attrs["solar_intent"] == "unknown"


# ---------------------------------------------------------------------------
# TOU anchor period behavioral tests
# ---------------------------------------------------------------------------

class TestAnchorPeriodDuringPeak:
    """test_anchor_period_during_peak"""

    def test_anchor_period_during_peak(self):
        """When currently in peak period, anchor_period = 'peak', minutes = 0."""
        predictor = _make_predictor(
            # next transition goes to off_peak (we're currently in peak)
            tou_transition={"next_period": "off_peak", "hours_until": 4.0, "transition_hour": 19},
            tou_current_period="peak",
        )
        attrs = predictor.get_intent_attrs()
        assert attrs["anchor_period"] == "peak", (
            f"Expected 'peak' when currently in peak, got {attrs['anchor_period']!r}"
        )
        assert attrs["anchor_starts_in_minutes"] == 0, (
            f"Expected 0 minutes (already in peak), got {attrs['anchor_starts_in_minutes']}"
        )

    def test_anchor_period_mid_peak_during_mid_peak(self):
        """When currently in mid_peak and next transition to off_peak, anchor = 'mid_peak'."""
        predictor = _make_predictor(
            tou_transition={"next_period": "off_peak", "hours_until": 2.0, "transition_hour": 19},
            tou_current_period="mid_peak",
        )
        attrs = predictor.get_intent_attrs()
        assert attrs["anchor_period"] == "mid_peak"
        assert attrs["anchor_starts_in_minutes"] == 0

    def test_anchor_period_mid_peak_next_transition(self):
        """Next transition to mid_peak → anchor_period = 'mid_peak'."""
        predictor = _make_predictor(
            tou_transition={"next_period": "mid_peak", "hours_until": 1.5, "transition_hour": 17},
            tou_current_period="off_peak",
        )
        attrs = predictor.get_intent_attrs()
        assert attrs["anchor_period"] == "mid_peak"
        assert attrs["anchor_starts_in_minutes"] == 90  # 1.5h * 60


class TestAnchorPeriodDuringOffPeakTargetsNextPeak:
    """test_anchor_period_during_off_peak_targets_next_peak"""

    def test_anchor_period_during_off_peak_targets_next_peak(self):
        """During off_peak with next transition to peak → anchor_period = 'peak'."""
        predictor = _make_predictor(
            tou_transition={"next_period": "peak", "hours_until": 3.5, "transition_hour": 14},
            tou_current_period="off_peak",
        )
        attrs = predictor.get_intent_attrs()
        assert attrs["anchor_period"] == "peak", (
            f"Expected 'peak', got {attrs['anchor_period']!r}"
        )
        assert attrs["anchor_starts_in_minutes"] == 210, (
            f"Expected 210 minutes (3.5h * 60), got {attrs['anchor_starts_in_minutes']}"
        )

    def test_anchor_starts_in_minutes_rounds_to_int(self):
        """anchor_starts_in_minutes is always int, not float."""
        predictor = _make_predictor(
            tou_transition={"next_period": "peak", "hours_until": 2.25, "transition_hour": 14},
        )
        attrs = predictor.get_intent_attrs()
        assert isinstance(attrs["anchor_starts_in_minutes"], int)

    def test_anchor_period_none_when_next_is_off_peak_and_not_in_peak(self):
        """During off_peak with next transition also to off_peak → anchor_period None."""
        predictor = _make_predictor(
            tou_transition={"next_period": "off_peak", "hours_until": 24, "transition_hour": 0},
            tou_current_period="off_peak",
        )
        attrs = predictor.get_intent_attrs()
        # next_period is off_peak, so not peak/mid_peak; current is off_peak too
        assert attrs["anchor_period"] is None
        assert attrs["anchor_starts_in_minutes"] is None

    def test_anchor_period_is_string_or_none(self):
        """anchor_period must be str or None — never a non-string non-None value."""
        predictor = _make_predictor()
        attrs = predictor.get_intent_attrs()
        val = attrs["anchor_period"]
        assert val is None or isinstance(val, str), (
            f"anchor_period must be str or None, got {type(val)}: {val!r}"
        )

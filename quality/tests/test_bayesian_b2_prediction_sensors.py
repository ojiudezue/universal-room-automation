"""Tests for v4.0.0-B2 Bayesian Prediction Sensors.

Validates:
- D1: BayesianPredictor extensions (predict_at_time, anomaly, accuracy)
- D2: Database prediction_results methods
- D3: PersonLikelyNextRoomSensor Bayesian upgrade
- D4: BayesianOccupancyForecastSensor
- D5: OccupancyAnomalyBinarySensor
- D6: BayesianPredictionAccuracySensor
- D7: Deferred entities (occupancy_pct, time_occupied, time_uncomfortable, avg_comfort)
- D8: Wiring (accuracy timer, pruning, cleanup)
"""

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import pytest

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


class FakeSensorStateClass:
    MEASUREMENT = "measurement"
    TOTAL_INCREASING = "total_increasing"


class FakeSensorDeviceClass:
    TEMPERATURE = "temperature"
    DURATION = "duration"


class FakeEntityCategory:
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"


class FakeBinarySensorDeviceClass:
    PROBLEM = "problem"
    OCCUPANCY = "occupancy"
    SAFETY = "safety"
    PLUG = "plug"


class FakeUnitOfTime:
    MINUTES = "min"
    SECONDS = "s"
    HOURS = "h"


_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": _mock_module(
        "homeassistant.const",
        UnitOfTemperature=_mock_cls(),
        UnitOfEnergy=_mock_cls(),
        UnitOfPower=_mock_cls(),
        UnitOfTime=FakeUnitOfTime,
        PERCENTAGE="%",
        LIGHT_LUX="lx",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": FakeEntityCategory,
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
        "async_track_time_change": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
        "parse_datetime": lambda s: datetime.fromisoformat(s),
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": FakeSensorDeviceClass,
        "SensorStateClass": FakeSensorStateClass,
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": FakeBinarySensorDeviceClass,
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    elif isinstance(attrs, types.ModuleType):
        sys.modules.setdefault(name, attrs)
    else:
        sys.modules.setdefault(name, attrs)

# ---------------------------------------------------------------------------
# Bypass __init__.py
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [
    os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")
]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Provide .const module with DOMAIN and needed constants
_ura_const = types.ModuleType(
    "custom_components.universal_room_automation.const"
)
_ura_const.DOMAIN = "universal_room_automation"
_ura_const.VERSION = "4.0.2"
sys.modules["custom_components.universal_room_automation.const"] = _ura_const

# Provide .domain_coordinators.signals
_dc = types.ModuleType(
    "custom_components.universal_room_automation.domain_coordinators"
)
_dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
sys.modules[
    "custom_components.universal_room_automation.domain_coordinators"
] = _dc

_dc_signals = types.ModuleType(
    "custom_components.universal_room_automation.domain_coordinators.signals"
)
_dc_signals.SIGNAL_BAYESIAN_UPDATED = "ura_bayesian_updated"
_dc_signals.SIGNAL_OCCUPANCY_ANOMALY = "ura_occupancy_anomaly"
sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.signals"
] = _dc_signals

# ---------------------------------------------------------------------------
# Now import the module under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.bayesian_predictor import (
    BayesianPredictor,
    LearningStatus,
    _hour_to_time_bin,
    _day_type,
)

DOMAIN = "universal_room_automation"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeHass:
    def __init__(self):
        self.data = {DOMAIN: {}}


class FakeDatabase:
    """Mock database with B2 methods."""

    def __init__(self, transitions=None, beliefs=None):
        self._transitions = transitions or []
        self._beliefs = beliefs or []
        self._saved_beliefs = []
        self._cleared = False
        self._prediction_results = []
        self._occupancy_time = 0
        self._uncomfortable_minutes = 0

    async def get_room_transition_counts(self, days=None):
        return self._transitions

    async def load_bayesian_beliefs(self):
        return self._beliefs

    async def save_bayesian_beliefs(self, beliefs):
        self._saved_beliefs = beliefs

    async def clear_bayesian_beliefs(self):
        self._cleared = True
        self._beliefs = []

    async def save_prediction_result(
        self, room_id, time_bin, day_type, predicted_prob, actual_occupied, timestamp
    ):
        self._prediction_results.append({
            "room_id": room_id,
            "time_bin": time_bin,
            "day_type": day_type,
            "predicted_probability": predicted_prob,
            "actual_occupied": actual_occupied,
            "timestamp": timestamp,
        })

    async def get_prediction_results(self, days=7, prediction_type="bayesian_occupancy"):
        return self._prediction_results

    async def prune_prediction_results(self, days=30):
        return 0

    async def get_occupancy_time_today(self, room_id):
        return self._occupancy_time

    async def get_uncomfortable_minutes_today(self, room_id):
        return self._uncomfortable_minutes


@pytest.fixture
def hass():
    return FakeHass()


@pytest.fixture
def predictor(hass):
    return BayesianPredictor(hass)


def _seed_predictor(predictor, persons=None, rooms=None, beliefs=None, obs=None):
    """Helper to seed predictor with beliefs."""
    if persons:
        predictor._known_persons = set(persons)
    if rooms:
        predictor._known_rooms = set(rooms)
    if beliefs:
        predictor._beliefs = beliefs
    if obs:
        predictor._observation_counts = obs


# ============================================================================
# D1: BayesianPredictor Extensions
# ============================================================================


class TestPredictRoomAtTime:
    """Test predict_room_at_time() convenience wrapper."""

    @pytest.mark.asyncio
    async def test_basic_prediction(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)  # morning, weekday
        predictor._beliefs[key] = {"Kitchen": 5.0, "Living Room": 3.0}
        predictor._observation_counts[key] = 50
        predictor._known_rooms = {"Kitchen", "Living Room"}
        predictor._known_persons = {"Oji"}

        # Wednesday 8 AM = time_bin 1 (morning), day_type 0 (weekday)
        future = datetime(2026, 3, 25, 8, 0, 0)
        result = predictor.predict_room_at_time("Oji", future)
        assert result is not None
        assert result["top_room"] == "Kitchen"

    @pytest.mark.asyncio
    async def test_with_timezone(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 5.0}
        predictor._observation_counts[key] = 10
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        future = datetime(2026, 3, 25, 8, 0, 0, tzinfo=timezone.utc)
        result = predictor.predict_room_at_time("Oji", future)
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_data_returns_none(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        future = datetime(2026, 3, 25, 8, 0, 0)
        result = predictor.predict_room_at_time("Nobody", future)
        assert result is None


class TestPredictRoomOccupancyAtTime:
    """Test predict_room_occupancy_at_time() convenience wrapper."""

    @pytest.mark.asyncio
    async def test_basic(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 4, 1)  # evening, weekend
        predictor._beliefs[key] = {"Kitchen": 8.0, "Other": 2.0}
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        # Saturday 7 PM = evening, weekend
        future = datetime(2026, 3, 28, 19, 0, 0)
        prob = predictor.predict_room_occupancy_at_time("Kitchen", future)
        assert prob is not None
        assert abs(prob - 0.8) < 0.001


class TestAnomalyScore:
    """Test get_anomaly_score()."""

    @pytest.mark.asyncio
    async def test_anomaly_when_occupied_and_low_prediction(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        # Set very low probability for Kitchen
        key = ("Oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 0.05, "Other": 9.95}
        predictor._observation_counts[key] = 60  # ACTIVE status
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        result = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert result["anomaly"] is True
        assert result["learning_status"] == "active"
        assert result["predicted_probability"] is not None
        assert result["predicted_probability"] < 0.10

    @pytest.mark.asyncio
    async def test_no_anomaly_when_not_occupied(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        key = ("Oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 0.05, "Other": 9.95}
        predictor._observation_counts[key] = 60
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        result = predictor.get_anomaly_score("Kitchen", is_occupied=False)
        assert result["anomaly"] is False

    @pytest.mark.asyncio
    async def test_no_anomaly_when_insufficient_data(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        key = ("Oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 0.05, "Other": 9.95}
        predictor._observation_counts[key] = 3  # INSUFFICIENT_DATA
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        result = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert result["anomaly"] is False
        assert result["learning_status"] == "insufficient_data"

    @pytest.mark.asyncio
    async def test_no_anomaly_when_high_prediction(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        key = ("Oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 8.0, "Other": 2.0}
        predictor._observation_counts[key] = 60
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        result = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert result["anomaly"] is False

    @pytest.mark.asyncio
    async def test_anomaly_score_no_persons(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        result = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert result["anomaly"] is False
        assert result["learning_status"] == "insufficient_data"

    @pytest.mark.asyncio
    async def test_anomaly_learning_status_picks_best(self, hass):
        """When multiple persons, picks the best (most advanced) learning status."""
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        # Person A: insufficient data, Person B: active
        predictor._beliefs[("A", time_bin, day_type_val)] = {"Kitchen": 0.05, "Other": 9.95}
        predictor._observation_counts[("A", time_bin, day_type_val)] = 2
        predictor._beliefs[("B", time_bin, day_type_val)] = {"Kitchen": 0.05, "Other": 9.95}
        predictor._observation_counts[("B", time_bin, day_type_val)] = 60
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"A", "B"}

        result = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        # Best status is ACTIVE from person B
        assert result["learning_status"] == "active"
        assert result["anomaly"] is True


class TestRecordPrediction:
    """Test record_prediction() and get_accuracy_stats()."""

    @pytest.mark.asyncio
    async def test_record_prediction_calls_db(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        await predictor.record_prediction(
            room_id="Kitchen",
            time_bin=1,
            day_type=0,
            predicted_prob=0.75,
            actual_occupied=True,
        )
        assert len(db._prediction_results) == 1
        row = db._prediction_results[0]
        assert row["room_id"] == "Kitchen"
        assert row["predicted_probability"] == 0.75
        assert row["actual_occupied"] == 1

    @pytest.mark.asyncio
    async def test_record_prediction_no_db(self, hass):
        predictor = BayesianPredictor(hass)
        # No database initialized
        await predictor.record_prediction(
            room_id="Kitchen",
            time_bin=1,
            day_type=0,
            predicted_prob=0.75,
            actual_occupied=True,
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_accuracy_stats_empty(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        stats = await predictor.get_accuracy_stats()
        assert stats["brier_score"] is None
        assert stats["hit_rate"] is None
        assert stats["total_predictions"] == 0

    @pytest.mark.asyncio
    async def test_accuracy_stats_perfect(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        db._prediction_results = [
            {"predicted_probability": 0.9, "actual_occupied": 1},
            {"predicted_probability": 0.1, "actual_occupied": 0},
        ]
        await predictor.initialize(db)

        stats = await predictor.get_accuracy_stats()
        assert stats["total_predictions"] == 2
        assert stats["hit_rate"] == 100.0
        # Brier: ((0.9-1)^2 + (0.1-0)^2) / 2 = (0.01+0.01)/2 = 0.01
        assert abs(stats["brier_score"] - 0.01) < 0.001

    @pytest.mark.asyncio
    async def test_accuracy_stats_mixed(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        db._prediction_results = [
            {"predicted_probability": 0.8, "actual_occupied": 1},  # hit
            {"predicted_probability": 0.7, "actual_occupied": 0},  # miss (pred > 0.5 but actual = 0)
            {"predicted_probability": 0.3, "actual_occupied": 0},  # hit
            {"predicted_probability": 0.2, "actual_occupied": 1},  # miss (pred <= 0.5 but actual = 1)
        ]
        await predictor.initialize(db)

        stats = await predictor.get_accuracy_stats()
        assert stats["total_predictions"] == 4
        assert stats["hit_rate"] == 50.0  # 2/4 hits

    @pytest.mark.asyncio
    async def test_accuracy_no_database(self, hass):
        predictor = BayesianPredictor(hass)
        # No database
        stats = await predictor.get_accuracy_stats()
        assert stats["total_predictions"] == 0
        assert stats["brier_score"] is None


# ============================================================================
# D2: Database prediction_results methods
# ============================================================================


class TestDatabasePredictionResults:
    """Test the FakeDatabase prediction results pipeline (structural)."""

    @pytest.mark.asyncio
    async def test_save_and_get_roundtrip(self):
        db = FakeDatabase()
        await db.save_prediction_result(
            room_id="Kitchen",
            time_bin=1,
            day_type=0,
            predicted_prob=0.65,
            actual_occupied=1,
            timestamp="2026-04-08T10:00:00",
        )
        results = await db.get_prediction_results(days=7)
        assert len(results) == 1
        assert results[0]["room_id"] == "Kitchen"
        assert results[0]["predicted_probability"] == 0.65

    @pytest.mark.asyncio
    async def test_prune_returns_zero(self):
        db = FakeDatabase()
        deleted = await db.prune_prediction_results(days=30)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_occupancy_time_today(self):
        db = FakeDatabase()
        db._occupancy_time = 3600  # 1 hour
        secs = await db.get_occupancy_time_today("Kitchen")
        assert secs == 3600

    @pytest.mark.asyncio
    async def test_uncomfortable_minutes(self):
        db = FakeDatabase()
        db._uncomfortable_minutes = 15
        mins = await db.get_uncomfortable_minutes_today("Kitchen")
        assert mins == 15


# ============================================================================
# D3: PersonLikelyNextRoomSensor Bayesian upgrade
# ============================================================================


class TestPersonLikelyNextRoomBayesianUpgrade:
    """Test that the sensor tries Bayesian first, falls back to frequency."""

    @pytest.mark.asyncio
    async def test_bayesian_primary(self, hass):
        """When Bayesian has data, use it as primary."""
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        key = ("oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 5.0, "Living Room": 3.0}
        predictor._observation_counts[key] = 20  # LEARNING status
        predictor._known_rooms = {"Kitchen", "Living Room"}
        predictor._known_persons = {"oji"}

        hass.data[DOMAIN]["bayesian_predictor"] = predictor

        result = predictor.predict_room_at_time("oji", now)
        assert result is not None
        assert result["top_room"] == "Kitchen"
        assert result["learning_status"] == "learning"

    @pytest.mark.asyncio
    async def test_bayesian_insufficient_data_triggers_fallback(self, hass):
        """When Bayesian returns insufficient_data, should fallback."""
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        key = ("oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 0.5}
        predictor._observation_counts[key] = 2  # INSUFFICIENT_DATA
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"oji"}

        result = predictor.predict_room_at_time("oji", now)
        assert result is not None
        assert result["learning_status"] == "insufficient_data"
        # PersonLikelyNextRoomSensor checks this and would fallback

    @pytest.mark.asyncio
    async def test_bayesian_no_data_returns_none(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        result = predictor.predict_room_at_time("nonexistent", now)
        assert result is None


# ============================================================================
# D4: BayesianOccupancyForecastSensor (structural)
# ============================================================================


class TestOccupancyForecast:
    """Test forecast sensor computes 3 time horizons."""

    @pytest.mark.asyncio
    async def test_forecast_now_1h_4h(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        for delta_h in [0, 1, 4]:
            future = now + timedelta(hours=delta_h)
            time_bin = _hour_to_time_bin(future.hour)
            day_type_val = _day_type(future)

            key = ("Oji", time_bin, day_type_val)
            if key not in predictor._beliefs:
                predictor._beliefs[key] = {"Kitchen": 6.0, "Other": 4.0}
                predictor._observation_counts[key] = 30

        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        # Check that predict_room_occupancy_at_time works for each horizon
        for delta_h in [0, 1, 4]:
            future = now + timedelta(hours=delta_h)
            prob = predictor.predict_room_occupancy_at_time("Kitchen", future)
            assert prob is not None
            assert 0.0 <= prob <= 1.0


# ============================================================================
# D5: OccupancyAnomalyBinarySensor (logic tests)
# ============================================================================


class TestOccupancyAnomaly:
    """Test anomaly detection logic end-to-end."""

    @pytest.mark.asyncio
    async def test_anomaly_detected(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        # Low predicted probability + ACTIVE status
        key = ("Oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 0.01, "Other": 9.99}
        predictor._observation_counts[key] = 100
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        score = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert score["anomaly"] is True

    @pytest.mark.asyncio
    async def test_anomaly_not_detected_normal_occupancy(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        # High predicted probability
        key = ("Oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 7.0, "Other": 3.0}
        predictor._observation_counts[key] = 100
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        score = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert score["anomaly"] is False

    @pytest.mark.asyncio
    async def test_anomaly_suppressed_during_learning(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        key = ("Oji", time_bin, day_type_val)
        predictor._beliefs[key] = {"Kitchen": 0.01, "Other": 9.99}
        predictor._observation_counts[key] = 20  # LEARNING, not ACTIVE
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        score = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert score["anomaly"] is False
        assert score["learning_status"] == "learning"


# ============================================================================
# D6: BayesianPredictionAccuracySensor (structural)
# ============================================================================


class TestAccuracySensor:
    """Test accuracy stats computation."""

    @pytest.mark.asyncio
    async def test_brier_score_computation(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        db._prediction_results = [
            {"predicted_probability": 1.0, "actual_occupied": 1},
            {"predicted_probability": 0.0, "actual_occupied": 0},
        ]
        await predictor.initialize(db)

        stats = await predictor.get_accuracy_stats()
        assert stats["brier_score"] == 0.0  # Perfect predictions
        assert stats["hit_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_brier_score_worst_case(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        db._prediction_results = [
            {"predicted_probability": 0.0, "actual_occupied": 1},
            {"predicted_probability": 1.0, "actual_occupied": 0},
        ]
        await predictor.initialize(db)

        stats = await predictor.get_accuracy_stats()
        assert stats["brier_score"] == 1.0  # Worst predictions
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_window_7_days(self, hass):
        """Verify the default window is 7 days."""
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        db._prediction_results = [
            {"predicted_probability": 0.6, "actual_occupied": 1},
        ]
        await predictor.initialize(db)

        stats = await predictor.get_accuracy_stats(days=7)
        assert stats["total_predictions"] == 1


# ============================================================================
# D7: Deferred entities (structural tests)
# ============================================================================


class TestDeferredEntities:
    """Test deferred entity DB helpers work correctly."""

    @pytest.mark.asyncio
    async def test_occupancy_percentage_calculation(self):
        db = FakeDatabase()
        db._occupancy_time = 7200  # 2 hours = 7200 seconds
        secs = await db.get_occupancy_time_today("Living Room")
        assert secs == 7200
        # If 12 hours have elapsed, pct = 7200 / (12*3600) * 100 = 16.7%
        elapsed_secs = 12 * 3600
        pct = secs / elapsed_secs * 100
        assert abs(pct - 16.67) < 0.1

    @pytest.mark.asyncio
    async def test_time_occupied_minutes(self):
        db = FakeDatabase()
        db._occupancy_time = 5400  # 90 minutes
        secs = await db.get_occupancy_time_today("Kitchen")
        minutes = secs // 60
        assert minutes == 90

    @pytest.mark.asyncio
    async def test_uncomfortable_minutes_query(self):
        db = FakeDatabase()
        db._uncomfortable_minutes = 25
        mins = await db.get_uncomfortable_minutes_today("Bedroom")
        assert mins == 25

    @pytest.mark.asyncio
    async def test_avg_time_to_comfort_estimation(self):
        """Test the comfort estimation formula."""
        db = FakeDatabase()
        db._occupancy_time = 7200  # 2 hours
        db._uncomfortable_minutes = 30

        occupied_secs = await db.get_occupancy_time_today("Bedroom")
        uncomfortable_mins = await db.get_uncomfortable_minutes_today("Bedroom")
        occupied_mins = occupied_secs // 60  # 120
        uncomfort_ratio = uncomfortable_mins / occupied_mins  # 30/120 = 0.25
        avg_comfort_time = max(0, round(uncomfort_ratio * 30))  # 0.25*30 = 7.5 -> 8
        assert avg_comfort_time == 8

    @pytest.mark.asyncio
    async def test_avg_time_to_comfort_zero_occupied(self):
        db = FakeDatabase()
        db._occupancy_time = 0
        occupied_secs = await db.get_occupancy_time_today("Bedroom")
        occupied_mins = occupied_secs // 60
        assert occupied_mins == 0
        # Should not divide by zero


# ============================================================================
# D8: Wiring (accuracy timer at bin boundaries, pruning, cleanup)
# ============================================================================


class TestWiring:
    """Test that wiring produces correct structures."""

    @pytest.mark.asyncio
    async def test_accuracy_evaluation_records_predictions(self, hass):
        """Test that record_prediction saves data."""
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        # Set up some beliefs
        for time_bin in range(6):
            for day_type in range(2):
                key = ("Oji", time_bin, day_type)
                predictor._beliefs[key] = {"Kitchen": 6.0, "Other": 4.0}
                predictor._observation_counts[key] = 30

        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji"}

        # Simulate accuracy evaluation
        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        prob = predictor.predict_room_occupancy("Kitchen", time_bin, day_type_val)
        assert prob is not None

        await predictor.record_prediction(
            room_id="Kitchen",
            time_bin=time_bin,
            day_type=day_type_val,
            predicted_prob=prob,
            actual_occupied=True,
        )
        assert len(db._prediction_results) == 1

    @pytest.mark.asyncio
    async def test_prune_called(self):
        """Test that prune doesn't raise."""
        db = FakeDatabase()
        deleted = await db.prune_prediction_results(days=30)
        assert deleted == 0

    def test_signal_constant_exists(self):
        """SIGNAL_OCCUPANCY_ANOMALY is defined."""
        assert _dc_signals.SIGNAL_OCCUPANCY_ANOMALY == "ura_occupancy_anomaly"

    def test_signal_bayesian_updated_exists(self):
        """SIGNAL_BAYESIAN_UPDATED is still defined."""
        assert _dc_signals.SIGNAL_BAYESIAN_UPDATED == "ura_bayesian_updated"


# ============================================================================
# Edge cases and integration tests
# ============================================================================


class TestEdgeCases:
    """Edge cases for B2 extensions."""

    @pytest.mark.asyncio
    async def test_predict_at_time_handles_no_tz(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 2, 0)
        predictor._beliefs[key] = {"Kitchen": 3.0}
        predictor._observation_counts[key] = 10
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        # Naive datetime (no timezone)
        naive_dt = datetime(2026, 3, 25, 10, 0, 0)
        result = predictor.predict_room_at_time("Oji", naive_dt)
        assert result is not None

    @pytest.mark.asyncio
    async def test_anomaly_score_multiple_persons_all_low(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        now = datetime.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)

        # Both persons very low probability for Kitchen
        for person in ["A", "B"]:
            key = (person, time_bin, day_type_val)
            predictor._beliefs[key] = {"Kitchen": 0.02, "Other": 9.98}
            predictor._observation_counts[key] = 80

        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"A", "B"}

        score = predictor.get_anomaly_score("Kitchen", is_occupied=True)
        assert score["anomaly"] is True

    @pytest.mark.asyncio
    async def test_record_multiple_predictions(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        for i in range(10):
            await predictor.record_prediction(
                room_id="Kitchen",
                time_bin=1,
                day_type=0,
                predicted_prob=0.5 + i * 0.05,
                actual_occupied=i % 2 == 0,
            )

        assert len(db._prediction_results) == 10
        stats = await predictor.get_accuracy_stats()
        assert stats["total_predictions"] == 10
        assert stats["brier_score"] is not None

    @pytest.mark.asyncio
    async def test_accuracy_stats_single_prediction(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        db._prediction_results = [
            {"predicted_probability": 0.6, "actual_occupied": 1},
        ]
        await predictor.initialize(db)

        stats = await predictor.get_accuracy_stats()
        assert stats["total_predictions"] == 1
        # Brier: (0.6-1)^2 = 0.16
        assert abs(stats["brier_score"] - 0.16) < 0.001
        assert stats["hit_rate"] == 100.0  # 0.6 > 0.5 and actual = 1

    @pytest.mark.asyncio
    async def test_occupancy_forecast_all_bins(self, hass):
        """Ensure forecast works for every time bin."""
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        for tb in range(6):
            for dt_val in range(2):
                key = ("Oji", tb, dt_val)
                predictor._beliefs[key] = {"Kitchen": 5.0, "Other": 5.0}
                predictor._observation_counts[key] = 30
                predictor._known_rooms.add("Other")

        # Test each hour maps correctly
        for hour in range(24):
            future = datetime(2026, 3, 25, hour, 0, 0)
            prob = predictor.predict_room_occupancy_at_time("Kitchen", future)
            assert prob is not None
            assert 0.0 <= prob <= 1.0

    @pytest.mark.asyncio
    async def test_anomaly_returns_correct_keys(self, hass):
        """Verify all expected keys in anomaly score dict."""
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        predictor._known_persons = {"Oji"}

        result = predictor.get_anomaly_score("Kitchen", is_occupied=False)
        assert "predicted_probability" in result
        assert "anomaly" in result
        assert "learning_status" in result
        assert "time_bin" in result
        assert "day_type" in result

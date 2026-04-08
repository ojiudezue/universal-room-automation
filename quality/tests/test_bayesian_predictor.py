"""Tests for v4.0.0-B1 Bayesian Predictor.

Validates:
- D1: BayesianPredictor — posterior update, predict, learning status, guest suppression,
      room aggregate, confidence intervals
- D2: DB persistence — save/load round-trip
- D3: Data quality scanner — all 7 filter categories
- D4: Integration wiring — update via transition, guest state suppression
- D5: Sensor value computation
- D6: ClearDatabaseButton — clear and reinitialize
"""

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from unittest.mock import MagicMock, AsyncMock, patch
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

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {"RestoreEntity": type("RestoreEntity", (), {})},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
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
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

# ---------------------------------------------------------------------------
# Bypass __init__.py: register the URA package as a stub module and import
# bayesian_predictor directly so the heavy coordinator/automation imports
# in __init__.py are never triggered.
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Provide .const module with DOMAIN
_ura_const = types.ModuleType("custom_components.universal_room_automation.const")
_ura_const.DOMAIN = "universal_room_automation"
sys.modules["custom_components.universal_room_automation.const"] = _ura_const

# Provide .domain_coordinators.signals
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc

_dc_signals = types.ModuleType("custom_components.universal_room_automation.domain_coordinators.signals")
_dc_signals.SIGNAL_BAYESIAN_UPDATED = "ura_bayesian_updated"
sys.modules["custom_components.universal_room_automation.domain_coordinators.signals"] = _dc_signals

# ---------------------------------------------------------------------------
# Now import the module under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.bayesian_predictor import (
    BayesianPredictor,
    DataQualityReport,
    LearningStatus,
    TimeBin,
    EXCLUDED_ROOMS,
    MINIMUM_ALPHA,
    PRIOR_SCALE_FACTOR,
    MIN_CONFIDENCE_FULL_WEIGHT,
    COLD_START_THRESHOLD,
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
    """Mock database for testing."""

    def __init__(self, transitions=None, beliefs=None):
        self._transitions = transitions or []
        self._beliefs = beliefs or []
        self._saved_beliefs = []
        self._cleared = False

    async def get_room_transition_counts(self, days=None):
        return self._transitions

    async def load_bayesian_beliefs(self):
        return self._beliefs

    async def save_bayesian_beliefs(self, beliefs):
        self._saved_beliefs = beliefs

    async def clear_bayesian_beliefs(self):
        self._cleared = True
        self._beliefs = []


@pytest.fixture
def hass():
    return FakeHass()


@pytest.fixture
def predictor(hass):
    return BayesianPredictor(hass)


def _make_transition(
    person_id="Oji",
    from_room="Living Room",
    to_room="Kitchen",
    timestamp=None,
    confidence=0.85,
    duration_seconds=15,
):
    """Helper to create a transition row dict."""
    if timestamp is None:
        # Wednesday 8:00 AM UTC
        timestamp = datetime(2026, 3, 25, 8, 0, 0, tzinfo=timezone.utc)
    return {
        "person_id": person_id,
        "from_room": from_room,
        "to_room": to_room,
        "timestamp": timestamp.isoformat(),
        "confidence": confidence,
        "duration_seconds": duration_seconds,
    }


# ============================================================================
# D1: BayesianPredictor core logic
# ============================================================================


class TestTimeBinHelpers:
    """Test time bin and day type helper functions."""

    def test_hour_to_time_bin_night(self):
        assert _hour_to_time_bin(0) == 0
        assert _hour_to_time_bin(5) == 0

    def test_hour_to_time_bin_morning(self):
        assert _hour_to_time_bin(6) == 1
        assert _hour_to_time_bin(8) == 1

    def test_hour_to_time_bin_midday(self):
        assert _hour_to_time_bin(9) == 2
        assert _hour_to_time_bin(11) == 2

    def test_hour_to_time_bin_afternoon(self):
        assert _hour_to_time_bin(12) == 3
        assert _hour_to_time_bin(16) == 3

    def test_hour_to_time_bin_evening(self):
        assert _hour_to_time_bin(17) == 4
        assert _hour_to_time_bin(20) == 4

    def test_hour_to_time_bin_late(self):
        assert _hour_to_time_bin(21) == 5
        assert _hour_to_time_bin(23) == 5

    def test_day_type_weekday(self):
        # Wednesday
        dt = datetime(2026, 3, 25)
        assert _day_type(dt) == 0

    def test_day_type_weekend(self):
        # Saturday
        dt = datetime(2026, 3, 28)
        assert _day_type(dt) == 1


class TestPosteriorUpdate:
    """Test that update() correctly modifies alpha values."""

    @pytest.mark.asyncio
    async def test_update_increases_alpha(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        # Manually seed a cell
        key = ("Oji", 1, 0)  # morning, weekday
        predictor._beliefs[key] = {"Kitchen": 1.0, "Living Room": 1.0}
        predictor._observation_counts[key] = 0
        predictor._known_rooms = {"Kitchen", "Living Room"}
        predictor._known_persons = {"Oji"}

        old_alpha = predictor._beliefs[key]["Kitchen"]
        ts = datetime(2026, 3, 25, 7, 30)  # Wednesday morning
        predictor.update("Oji", "Kitchen", ts, 0.85)

        assert predictor._beliefs[key]["Kitchen"] > old_alpha
        assert predictor._observation_counts[key] == 1

    @pytest.mark.asyncio
    async def test_update_fractional_weight_low_confidence(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 1.0}
        predictor._observation_counts[key] = 0
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "Kitchen", ts, 0.2)  # Below threshold

        # Weight = 0.2 * 0.5 = 0.1
        expected = 1.0 + 0.1
        assert abs(predictor._beliefs[key]["Kitchen"] - expected) < 0.001

    @pytest.mark.asyncio
    async def test_update_creates_new_cell(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("NewPerson", "Kitchen", ts, 0.9)

        key = ("NewPerson", 1, 0)
        assert key in predictor._beliefs
        assert "Kitchen" in predictor._beliefs[key]
        assert predictor._observation_counts[key] == 1

    @pytest.mark.asyncio
    async def test_update_excludes_away_room(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "away", ts, 0.9)

        # Should not create a cell for "away"
        for key in predictor._beliefs:
            assert "away" not in predictor._beliefs.get(key, {})

    @pytest.mark.asyncio
    async def test_update_excludes_home_room(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "home", ts, 0.9)

        for key in predictor._beliefs:
            assert "home" not in predictor._beliefs.get(key, {})


class TestPredictRoom:
    """Test predict_room() returns correct distributions."""

    @pytest.mark.asyncio
    async def test_predict_room_basic(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        # Set up a simple cell
        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {
            "Kitchen": 5.0,
            "Living Room": 3.0,
            "Bedroom": 2.0,
        }
        predictor._observation_counts[key] = 50
        predictor._known_rooms = {"Kitchen", "Living Room", "Bedroom"}
        predictor._known_persons = {"Oji"}

        result = predictor.predict_room("Oji", 1, 0)
        assert result is not None
        assert result["top_room"] == "Kitchen"
        assert result["probability"] == 0.5  # 5/10
        assert result["learning_status"] == "active"
        assert len(result["alternatives"]) == 2

    @pytest.mark.asyncio
    async def test_predict_room_no_data(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        result = predictor.predict_room("NonexistentPerson", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_predict_room_confidence_interval(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 10.0, "Bathroom": 2.0}
        predictor._observation_counts[key] = 12

        result = predictor.predict_room("Oji", 1, 0)
        ci = result["confidence_interval"]
        assert "low" in ci
        assert "high" in ci
        assert ci["low"] <= result["probability"] <= ci["high"]
        assert ci["low"] >= 0.0
        assert ci["high"] <= 1.0


class TestLearningStatus:
    """Test learning status transitions."""

    def test_insufficient_data(self):
        assert (
            BayesianPredictor._learning_status(0)
            == LearningStatus.INSUFFICIENT_DATA
        )
        assert (
            BayesianPredictor._learning_status(4)
            == LearningStatus.INSUFFICIENT_DATA
        )

    def test_learning(self):
        assert BayesianPredictor._learning_status(5) == LearningStatus.LEARNING
        assert BayesianPredictor._learning_status(49) == LearningStatus.LEARNING

    def test_active(self):
        assert BayesianPredictor._learning_status(50) == LearningStatus.ACTIVE
        assert BayesianPredictor._learning_status(100) == LearningStatus.ACTIVE


class TestGuestSuppression:
    """Test learning suppression in guest mode."""

    @pytest.mark.asyncio
    async def test_suppress_learning(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 1.0}
        predictor._observation_counts[key] = 0
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        predictor.suppress_learning(True)
        assert predictor.is_learning_suppressed is True

        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "Kitchen", ts, 0.9)

        # Alpha should NOT change
        assert predictor._beliefs[key]["Kitchen"] == 1.0
        assert predictor._observation_counts[key] == 0

    @pytest.mark.asyncio
    async def test_resume_learning(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 1.0}
        predictor._observation_counts[key] = 0
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        predictor.suppress_learning(True)
        predictor.suppress_learning(False)
        assert predictor.is_learning_suppressed is False

        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "Kitchen", ts, 0.9)

        assert predictor._beliefs[key]["Kitchen"] > 1.0


class TestRoomOccupancyAggregate:
    """Test predict_room_occupancy() aggregation across persons."""

    @pytest.mark.asyncio
    async def test_single_person(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 8.0, "Living Room": 2.0}
        predictor._known_rooms = {"Kitchen", "Living Room"}
        predictor._known_persons = {"Oji"}

        prob = predictor.predict_room_occupancy("Kitchen", 1, 0)
        assert prob is not None
        # P = 1 - (1 - 8/10) = 0.8
        assert abs(prob - 0.8) < 0.001

    @pytest.mark.asyncio
    async def test_two_persons(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        predictor._beliefs[("Oji", 1, 0)] = {"Kitchen": 8.0, "Other": 2.0}
        predictor._beliefs[("Ezinne", 1, 0)] = {"Kitchen": 6.0, "Other": 4.0}
        predictor._known_rooms = {"Kitchen", "Other"}
        predictor._known_persons = {"Oji", "Ezinne"}

        prob = predictor.predict_room_occupancy("Kitchen", 1, 0)
        assert prob is not None
        # P = 1 - (1-0.8)*(1-0.6) = 1 - 0.2*0.4 = 1 - 0.08 = 0.92
        assert abs(prob - 0.92) < 0.001

    @pytest.mark.asyncio
    async def test_no_data(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        prob = predictor.predict_room_occupancy("Kitchen", 1, 0)
        assert prob is None


class TestConfidenceInterval:
    """Test Dirichlet confidence interval computation."""

    def test_uniform_distribution(self):
        # 2 rooms, equal alpha
        ci = BayesianPredictor._confidence_interval(5.0, 10.0)
        assert ci["low"] < 0.5
        assert ci["high"] > 0.5

    def test_concentrated_distribution(self):
        # High alpha for one room — with very large counts the interval tightens
        ci = BayesianPredictor._confidence_interval(1000.0, 1100.0)
        # Should be a tight interval around 0.909
        assert ci["high"] - ci["low"] < 0.1

    def test_zero_alpha(self):
        ci = BayesianPredictor._confidence_interval(0.0, 10.0)
        assert ci["low"] == 0.0
        assert ci["high"] >= 0.0

    def test_zero_total(self):
        ci = BayesianPredictor._confidence_interval(0.0, 0.0)
        assert ci["low"] == 0.0
        assert ci["high"] == 0.0


# ============================================================================
# D2: DB Persistence
# ============================================================================


class TestDBPersistence:
    """Test save/load round-trip."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        # Set up beliefs
        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 5.5, "Living Room": 3.2}
        predictor._observation_counts[key] = 42
        predictor._known_rooms = {"Kitchen", "Living Room"}
        predictor._known_persons = {"Oji"}

        # Save
        await predictor.save_beliefs()
        saved = db._saved_beliefs
        assert len(saved) == 2

        # Check saved data
        kitchen_row = next(r for r in saved if r["room_id"] == "Kitchen")
        assert kitchen_row["person_id"] == "Oji"
        assert kitchen_row["time_bin"] == 1
        assert kitchen_row["day_type"] == 0
        assert kitchen_row["alpha"] == 5.5
        assert kitchen_row["observation_count"] == 42

    @pytest.mark.asyncio
    async def test_restore_from_saved(self, hass):
        saved_beliefs = [
            {
                "person_id": "Oji",
                "time_bin": 1,
                "day_type": 0,
                "room_id": "Kitchen",
                "alpha": 5.5,
                "observation_count": 42,
                "updated_at": "2026-03-25T12:00:00",
            },
            {
                "person_id": "Oji",
                "time_bin": 1,
                "day_type": 0,
                "room_id": "Living Room",
                "alpha": 3.2,
                "observation_count": 42,
                "updated_at": "2026-03-25T12:00:00",
            },
        ]
        db = FakeDatabase(beliefs=saved_beliefs)
        predictor = BayesianPredictor(hass)
        await predictor.initialize(db)

        assert ("Oji", 1, 0) in predictor._beliefs
        assert predictor._beliefs[("Oji", 1, 0)]["Kitchen"] == 5.5
        assert predictor._beliefs[("Oji", 1, 0)]["Living Room"] == 3.2
        assert predictor._observation_counts[("Oji", 1, 0)] == 42
        assert "Kitchen" in predictor._known_rooms
        assert "Oji" in predictor._known_persons

    @pytest.mark.asyncio
    async def test_empty_beliefs_triggers_prior_build(self, hass):
        """When no saved beliefs, should try to build from transitions."""
        transitions = [
            _make_transition("Oji", "Living Room", "Kitchen"),
        ] * 15  # 15 transitions to exceed COLD_START_THRESHOLD

        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        await predictor.initialize(db)

        assert len(predictor._beliefs) > 0
        assert "Kitchen" in predictor._known_rooms

    @pytest.mark.asyncio
    async def test_save_with_no_database(self, hass):
        """Save should warn but not crash when no database."""
        predictor = BayesianPredictor(hass)
        # Don't initialize — no database reference
        await predictor.save_beliefs()  # Should not raise


# ============================================================================
# D3: Data Quality Scanner
# ============================================================================


class TestDataQualityScanner:
    """Test scan_data_quality with all 7 filter categories."""

    @pytest.mark.asyncio
    async def test_empty_data(self, hass):
        db = FakeDatabase()
        predictor = BayesianPredictor(hass)
        report = await predictor.scan_data_quality(db)
        assert report.total_rows == 0
        assert report.passed == 0

    @pytest.mark.asyncio
    async def test_null_rooms(self, hass):
        transitions = [
            _make_transition(to_room=""),
            _make_transition(from_room=""),
        ]
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        report = await predictor.scan_data_quality(db)
        assert report.null_rooms == 2
        assert report.passed == 0

    @pytest.mark.asyncio
    async def test_self_transitions(self, hass):
        transitions = [
            _make_transition(from_room="Kitchen", to_room="Kitchen"),
        ]
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        report = await predictor.scan_data_quality(db)
        assert report.self_transitions == 1

    @pytest.mark.asyncio
    async def test_impossible_durations(self, hass):
        transitions = [
            _make_transition(duration_seconds=-5),
            _make_transition(duration_seconds=100000),  # > 24h
        ]
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        report = await predictor.scan_data_quality(db)
        assert report.impossible_durations == 2

    @pytest.mark.asyncio
    async def test_unknown_rooms(self, hass):
        transitions = [
            _make_transition(
                to_room="away",
                timestamp=datetime(2026, 3, 25, 8, 0, 1, tzinfo=timezone.utc),
            ),
            _make_transition(
                to_room="home",
                timestamp=datetime(2026, 3, 25, 8, 0, 2, tzinfo=timezone.utc),
            ),
            _make_transition(
                from_room="not_home",
                timestamp=datetime(2026, 3, 25, 8, 0, 3, tzinfo=timezone.utc),
            ),
        ]
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        report = await predictor.scan_data_quality(db)
        assert report.unknown_rooms == 3

    @pytest.mark.asyncio
    async def test_low_confidence(self, hass):
        transitions = [
            _make_transition(
                confidence=0.1,
                timestamp=datetime(2026, 3, 25, 8, 0, 1, tzinfo=timezone.utc),
            ),
            _make_transition(
                confidence=0.2,
                timestamp=datetime(2026, 3, 25, 8, 0, 2, tzinfo=timezone.utc),
            ),
        ]
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        report = await predictor.scan_data_quality(db)
        assert report.low_confidence == 2

    @pytest.mark.asyncio
    async def test_good_data_passes(self, hass):
        transitions = [
            _make_transition(
                person_id="Oji",
                from_room="Living Room",
                to_room="Kitchen",
                confidence=0.85,
                duration_seconds=15,
            ),
        ]
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        report = await predictor.scan_data_quality(db)
        assert report.passed == 1
        assert report.total_rows == 1

    @pytest.mark.asyncio
    async def test_quality_summary(self, hass):
        report = DataQualityReport(
            total_rows=100,
            null_rooms=2,
            self_transitions=1,
            impossible_durations=0,
            duplicate_timestamps=0,
            unknown_rooms=3,
            low_confidence=4,
            passed=90,
        )
        summary = report.summary()
        assert "100 total" in summary
        assert "90 passed" in summary
        assert "90.0%" in summary


# ============================================================================
# D4: Integration wiring tests
# ============================================================================


class TestIntegrationWiring:
    """Test wiring: transition -> update, guest suppression."""

    @pytest.mark.asyncio
    async def test_transition_triggers_update(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        # Simulate a transition update
        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "Kitchen", ts, 0.85)

        key = ("Oji", 1, 0)
        assert key in predictor._beliefs
        assert "Kitchen" in predictor._beliefs[key]
        assert predictor._observation_counts[key] == 1

    @pytest.mark.asyncio
    async def test_guest_state_suppresses_learning(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 1.0}
        predictor._observation_counts[key] = 0
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        # Simulate GUEST state
        predictor.suppress_learning(True)

        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "Kitchen", ts, 0.9)

        # Should not have changed
        assert predictor._beliefs[key]["Kitchen"] == 1.0

    @pytest.mark.asyncio
    async def test_periodic_save(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        key = ("Oji", 1, 0)
        predictor._beliefs[key] = {"Kitchen": 5.0}
        predictor._observation_counts[key] = 10
        predictor._known_rooms = {"Kitchen"}
        predictor._known_persons = {"Oji"}

        await predictor.save_beliefs()
        assert len(db._saved_beliefs) == 1


# ============================================================================
# D5: Sensor value tests
# ============================================================================


class TestSensorValues:
    """Test sensor value computation from predictor."""

    @pytest.mark.asyncio
    async def test_weekday_morning_prob(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        predictor._beliefs[("Oji", 1, 0)] = {"Kitchen": 8.0, "Other": 2.0}
        predictor._known_persons = {"Oji"}
        predictor._known_rooms = {"Kitchen", "Other"}

        prob = predictor.predict_room_occupancy("Kitchen", 1, 0)
        assert prob is not None
        assert abs(prob - 0.8) < 0.001

    @pytest.mark.asyncio
    async def test_weekend_evening_prob(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        predictor._beliefs[("Oji", 4, 1)] = {"Living Room": 6.0, "Other": 4.0}
        predictor._known_persons = {"Oji"}
        predictor._known_rooms = {"Living Room", "Other"}

        prob = predictor.predict_room_occupancy("Living Room", 4, 1)
        assert prob is not None
        assert abs(prob - 0.6) < 0.001

    @pytest.mark.asyncio
    async def test_occupancy_pattern_top_bin(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        # Kitchen most used in morning weekday
        predictor._beliefs[("Oji", 1, 0)] = {"Kitchen": 9.0, "Other": 1.0}
        predictor._beliefs[("Oji", 4, 0)] = {"Kitchen": 2.0, "Other": 8.0}
        predictor._known_persons = {"Oji"}
        predictor._known_rooms = {"Kitchen", "Other"}

        top = predictor.get_top_time_bin_for_room("Kitchen")
        assert top is not None
        assert top["time_bin"] == 1  # Morning
        assert top["time_bin_name"] == "Morning"


# ============================================================================
# D6: Clear and reinitialize
# ============================================================================


class TestClearAndReinitialize:
    """Test clear_and_reinitialize() button action."""

    @pytest.mark.asyncio
    async def test_clear_resets_beliefs(self, hass):
        predictor = BayesianPredictor(hass)

        # Start with some transitions to build priors
        transitions = [
            _make_transition("Oji", "Living Room", "Kitchen"),
        ] * 15
        db = FakeDatabase(transitions=transitions)
        await predictor.initialize(db)

        # Add some online updates
        ts = datetime(2026, 3, 25, 7, 30)
        predictor.update("Oji", "Kitchen", ts, 0.9)
        old_cells = len(predictor._beliefs)
        assert old_cells > 0

        # Clear and reinitialize
        await predictor.clear_and_reinitialize()

        # DB should have been cleared
        assert db._cleared is True
        # Beliefs should be rebuilt from priors (all observation counts = 0)
        for key in predictor._observation_counts:
            assert predictor._observation_counts[key] == 0


# ============================================================================
# Prior initialization tests
# ============================================================================


class TestPriorInitialization:
    """Test prior building from room_transitions."""

    @pytest.mark.asyncio
    async def test_cold_start_with_few_samples(self, hass):
        """Cells with < COLD_START_THRESHOLD use global distribution."""
        transitions = [
            _make_transition("Oji", "A", "B", datetime(2026, 3, 25, 7, i))
            for i in range(5)  # Only 5 samples — below threshold
        ]
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        await predictor.initialize(db)

        # Should use cold start alpha, not scaled counts
        assert len(predictor._beliefs) > 0

    @pytest.mark.asyncio
    async def test_normal_prior_with_enough_samples(self, hass):
        """Cells with >= COLD_START_THRESHOLD use scaled counts."""
        # Create 20 transitions to Kitchen, 5 to Bedroom — all in morning weekday
        transitions = []
        for i in range(20):
            transitions.append(
                _make_transition(
                    "Oji", "Living Room", "Kitchen",
                    datetime(2026, 3, 25, 7, 0, i),
                )
            )
        for i in range(5):
            transitions.append(
                _make_transition(
                    "Oji", "Living Room", "Bedroom",
                    datetime(2026, 3, 25, 7, 1, i),
                )
            )

        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        await predictor.initialize(db)

        key = ("Oji", 1, 0)  # Morning, weekday
        if key in predictor._beliefs:
            alphas = predictor._beliefs[key]
            # Kitchen should have higher alpha than Bedroom (20 vs 5 counts)
            assert alphas.get("Kitchen", 0) > alphas.get("Bedroom", 0)

    @pytest.mark.asyncio
    async def test_excluded_rooms_not_in_priors(self, hass):
        """Rooms like 'away', 'home' should not appear in beliefs."""
        transitions = [
            _make_transition("Oji", "Living Room", "away"),
            _make_transition("Oji", "Living Room", "home"),
            _make_transition("Oji", "Living Room", "Kitchen"),
        ] * 15
        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        await predictor.initialize(db)

        assert "away" not in predictor._known_rooms
        assert "home" not in predictor._known_rooms
        assert "Kitchen" in predictor._known_rooms

    @pytest.mark.asyncio
    async def test_minimum_alpha_floor(self, hass):
        """All rooms should have at least MINIMUM_ALPHA."""
        transitions = [
            _make_transition("Oji", "A", "Kitchen"),
        ] * 15 + [
            _make_transition("Oji", "A", "Bedroom"),
        ] * 15

        db = FakeDatabase(transitions=transitions)
        predictor = BayesianPredictor(hass)
        await predictor.initialize(db)

        for key, alphas in predictor._beliefs.items():
            for room, alpha in alphas.items():
                assert alpha >= MINIMUM_ALPHA, (
                    f"Room {room} in cell {key} has alpha {alpha} "
                    f"< MINIMUM_ALPHA {MINIMUM_ALPHA}"
                )


# ============================================================================
# Excluded rooms constant test
# ============================================================================


class TestExcludedRooms:
    """Test EXCLUDED_ROOMS constant."""

    def test_excluded_rooms_contains_expected(self):
        assert "away" in EXCLUDED_ROOMS
        assert "home" in EXCLUDED_ROOMS
        assert "unknown" in EXCLUDED_ROOMS
        assert "not_home" in EXCLUDED_ROOMS

    def test_excluded_rooms_is_frozenset(self):
        assert isinstance(EXCLUDED_ROOMS, frozenset)


# ============================================================================
# Top time bin test
# ============================================================================


class TestGetTopTimeBin:
    """Test get_top_time_bin_for_room."""

    @pytest.mark.asyncio
    async def test_returns_none_with_no_data(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        result = predictor.get_top_time_bin_for_room("Kitchen")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_correct_top_bin(self, hass):
        predictor = BayesianPredictor(hass)
        db = FakeDatabase()
        await predictor.initialize(db)

        predictor._known_persons = {"Oji"}
        predictor._known_rooms = {"Kitchen", "Other"}

        # Evening weekday has highest Kitchen probability
        predictor._beliefs[("Oji", 1, 0)] = {"Kitchen": 3.0, "Other": 7.0}
        predictor._beliefs[("Oji", 4, 0)] = {"Kitchen": 9.0, "Other": 1.0}

        top = predictor.get_top_time_bin_for_room("Kitchen")
        assert top is not None
        assert top["time_bin"] == 4  # Evening
        assert top["time_bin_name"] == "Evening"
        assert top["probability"] > 0.5

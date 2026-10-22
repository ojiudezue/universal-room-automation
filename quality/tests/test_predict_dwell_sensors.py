"""Room forecast / pattern sensors read the dwell model (PREDICT-MODEL-DWELL-
MIGRATION-1, plan D2). Oracles are hand-stated cell shares; the Bayesian
predictor stub returns a deliberately different number so a sensor still
reading it fails the dwell assertions."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from occ_dwell_helpers import default_tz, real_package

from custom_components.universal_room_automation.const import DOMAIN

UTC = timezone.utc
ENTRY_ID = "entry_study_a"
NOW = datetime(2026, 10, 21, 10, 30, tzinfo=UTC)   # Wednesday 10:30


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    import importlib

    global dt_util, sensor, rdm, const
    with real_package():
        dt_util = importlib.import_module("homeassistant.util.dt")
        sensor = importlib.import_module(
            "custom_components.universal_room_automation.sensor")
        rdm = importlib.import_module(
            "custom_components.universal_room_automation.room_dwell_model")
        const = importlib.import_module(
            "custom_components.universal_room_automation.const")
        yield


@pytest.fixture(autouse=True)
def _utc_now():
    with default_tz("UTC"), patch.object(dt_util, "now", return_value=NOW):
        yield


# Wednesday cells: 10:00 -> 36/60 = 0.6, 11:00 -> 0.75, 14:00 -> 0.5;
# Saturday 09:00 -> 1.0 (the peak).
_ROWS = [(ENTRY_ID, "2026-10-14T10", 36, 60), (ENTRY_ID, "2026-10-14T11", 9, 12),
         (ENTRY_ID, "2026-10-14T14", 6, 12), (ENTRY_ID, "2026-10-17T09", 12, 12)]


def _runner(last=None, refreshed=True):
    r = rdm.RoomDwellModelRunner(SimpleNamespace(data={}))
    if refreshed:
        assert r.model.refresh(_ROWS, UTC, now_utc=NOW, window_days=56)
    if last is not None:
        r._last_hour_fraction = {ENTRY_ID: last}
    return r


def _predictor(prob=0.01):
    p = MagicMock()
    p.predict_room_occupancy_at_time = MagicMock(return_value=prob)
    p.known_persons = []
    p.get_top_time_bin_for_room = MagicMock(return_value={
        "time_bin": 1, "time_bin_name": "Morning", "day_type": 0,
        "probability": 0.3, "learning_status": "active"})
    return p


def _make(cls, runner=None, predictor=None):
    coord = SimpleNamespace(
        entry=SimpleNamespace(entry_id=ENTRY_ID, data={"room_name": "Study A"}),
        data={}, last_update_success=True,
    )
    ent = cls(coord)
    domain = {}
    if runner is not None:
        domain[rdm.HASS_DATA_KEY] = runner
    if predictor is not None:
        domain["bayesian_predictor"] = predictor
    ent.hass = SimpleNamespace(data={DOMAIN: domain})
    return ent


def _forecast(**kw):
    return _make(sensor.BayesianOccupancyForecastSensor, **kw)


def _pattern(**kw):
    return _make(sensor.BayesianOccupancyPatternSensor, **kw)


# ---------------------------------------------------------------------------
# Forecast sensor
# ---------------------------------------------------------------------------


def test_forecast_state_is_dwell_share():
    ent = _forecast(runner=_runner(), predictor=_predictor(0.01))
    assert ent.native_value == 60.0          # Bayesian would read 1.0
    attrs = ent.extra_state_attributes
    assert attrs["forecast_now"] == 60.0
    assert attrs["model"] == "dwell"
    assert attrs["cell"] == "weekday 10:00"
    assert attrs["cell_days"] == 1
    assert attrs["model_status"] == "ok"


def test_forecast_blend_uses_last_hour():
    ent = _forecast(runner=_runner(last=0.1), predictor=_predictor())
    attrs = ent.extra_state_attributes
    assert attrs["last_hour_fraction"] == 0.1
    # +1 h: 0.5 x 0.1 + 0.5 x 0.75 = 0.425
    assert attrs["forecast_+1h"] == 42.5
    # +4 h (14:30, cell 0.5): 0.25 x 0.1 + 0.75 x 0.5 = 0.4
    assert attrs["forecast_+4h"] == 40.0
    assert attrs["forecast_now"] == 60.0     # weight 0 at "now"


def test_forecast_weight_knobs_read():
    with patch.object(const, "FORECAST_PERSISTENCE_WEIGHT_1H", 0.0), \
            patch.object(const, "FORECAST_PERSISTENCE_WEIGHT_4H", 1.0):
        attrs = _forecast(runner=_runner(last=0.1)).extra_state_attributes
    assert attrs["forecast_+1h"] == 75.0     # cell share only
    assert attrs["forecast_+4h"] == 10.0     # persistence only


def test_forecast_after_restart_no_persistence():
    attrs = _forecast(runner=_runner(last=None)).extra_state_attributes
    assert attrs["last_hour_fraction"] is None
    assert attrs["forecast_+1h"] == 75.0
    assert attrs["forecast_+4h"] == 50.0


def test_forecast_unknown_before_model():
    ent = _forecast(runner=_runner(refreshed=False), predictor=_predictor(0.5))
    assert ent.native_value is None
    attrs = ent.extra_state_attributes
    assert attrs["model_status"] == "never_refreshed"
    assert attrs["forecast_now"] is None and attrs["forecast_+1h"] is None
    no_runner = _forecast(predictor=_predictor(0.5))
    assert no_runner.native_value is None
    assert no_runner.extra_state_attributes["model_status"] == "never_refreshed"


def test_forecast_kill_switch_byte_identical():
    with patch.object(const, "FORECAST_DWELL_SOURCE_ENABLED", False):
        ent = _forecast(runner=_runner(last=0.1), predictor=_predictor(0.42))
        value, attrs = ent.native_value, ent.extra_state_attributes
    assert value == 42.0
    assert attrs == {
        "room": "Study A",
        "forecast_now": 42.0, "forecast_+1h": 42.0, "forecast_+4h": 42.0,
        "learning_status": "insufficient_data",
    }


# ---------------------------------------------------------------------------
# Pattern sensor
# ---------------------------------------------------------------------------


def test_pattern_state_is_peak_cell():
    ent = _pattern(runner=_runner(), predictor=_predictor())
    assert ent.native_value == "weekend 09:00"
    attrs = ent.extra_state_attributes
    assert attrs["peak_share"] == 1.0
    assert attrs["model"] == "dwell"
    assert attrs["top_cells"][:2] == [
        {"cell": "weekend 09:00", "share": 1.0},
        {"cell": "weekday 11:00", "share": 0.75},
    ]
    assert len(attrs["top_cells"]) == 4


def test_pattern_top_cells_knob():
    with patch.object(const, "FORECAST_TOP_CELLS_COUNT", 1):
        attrs = _pattern(runner=_runner()).extra_state_attributes
    assert attrs["top_cells"] == [{"cell": "weekend 09:00", "share": 1.0}]
    with patch.object(const, "FORECAST_TOP_CELLS_COUNT", 0):
        attrs = _pattern(runner=_runner()).extra_state_attributes
    assert "top_cells" not in attrs


def test_pattern_unknown_before_model():
    ent = _pattern(runner=_runner(refreshed=False), predictor=_predictor())
    assert ent.native_value is None
    assert ent.extra_state_attributes["model_status"] == "never_refreshed"


def test_pattern_kill_switch_byte_identical():
    with patch.object(const, "FORECAST_DWELL_SOURCE_ENABLED", False):
        ent = _pattern(runner=_runner(), predictor=_predictor())
        value, attrs = ent.native_value, ent.extra_state_attributes
    assert value == "Morning (Weekday)"
    assert attrs == {
        "room": "Study A", "time_bin": 1, "time_bin_name": "Morning",
        "day_type": 0, "probability": 0.3, "learning_status": "active",
    }

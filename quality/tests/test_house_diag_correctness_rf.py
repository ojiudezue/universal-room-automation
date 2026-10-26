"""HOUSE-DIAG-CORRECTNESS (audit 2026-10-25 P13): next-state ETA is the
REMAINING time, and the cell is keyed on the current state's ENTRY time.

Reuses the stub harness of test_routine_forecaster (imported for its
side effects; it installs stubs only when absent).
"""
from __future__ import annotations

from datetime import timedelta

import test_routine_forecaster as _h  # noqa: F401

rf_mod = _h.rf_mod


def _seed_cell(fc, at, prev, nxt, dwells_min):
    local = rf_mod.dt_util.as_local(at)
    cell = (prev, rf_mod._day_type(local), rf_mod._hour_to_time_bin(local.hour))
    fc._counts[cell][nxt] = fc._counts[cell].get(nxt, 0) + len(dwells_min)
    fc._etas[cell][nxt].extend(m * 60.0 for m in dwells_min)
    return cell


def _fc(entered_minutes_ago, last_state="home_day"):
    fc = rf_mod.RoutineForecaster(_h._hass(), _h._FakeDB([]))
    entered = rf_mod.dt_util.utcnow() - timedelta(minutes=entered_minutes_ago)
    fc._last_row_ts = entered
    fc._last_row_state = last_state
    return fc, entered


def test_eta_is_remaining_not_total():
    # Dwells 60/90/120/150/180 min, 100 min elapsed -> survivors
    # 120,150,180 -> remaining 20,50,80 -> median 50 (old code: 120).
    # (5 samples = ROUTINE_FORECAST_MIN_SUPPORT.)
    fc, entered = _fc(100)
    _seed_cell(fc, entered, "home_day", "away", [60, 90, 120, 150, 180])
    out = fc.predict("home_day")
    assert out["state"] == "away"
    assert out["transition_eta_minutes"] == 50


def test_eta_none_once_every_sample_exceeded():
    # Live repro shape: 164 min elapsed, every dwell shorter -> no ETA.
    fc, entered = _fc(164)
    _seed_cell(fc, entered, "home_day", "away", [60, 65, 71, 80, 90])
    out = fc.predict("home_day")
    assert out["state"] == "away"
    assert out["transition_eta_minutes"] is None


def test_unknown_entry_time_keeps_total_median():
    # Last observed transition landed in another state -> elapsed unknown
    # -> prior shape (median of total dwell, now-keyed cell).
    fc, _ = _fc(100, last_state="away")
    _seed_cell(fc, rf_mod.dt_util.utcnow(), "home_day", "away", [60, 90, 120, 150, 180])
    out = fc.predict("home_day")
    assert out["transition_eta_minutes"] == 120


def test_cell_keyed_on_entry_time_not_now():
    # 7 h ago is always a different time bin than now (bins are <= 6 h).
    fc, entered = _fc(7 * 60)
    entry_cell = _seed_cell(fc, entered, "home_day", "away", [600] * 5)
    now_cell = _seed_cell(fc, rf_mod.dt_util.utcnow(), "home_day", "sleep", [900] * 7)
    assert entry_cell != now_cell
    out = fc.predict("home_day")
    assert out["state"] == "away"
    assert out["transition_eta_minutes"] == 180  # 600 - 420

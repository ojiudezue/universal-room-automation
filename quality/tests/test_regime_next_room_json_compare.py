"""REGIME-NEXT-ROOM-ACCURACY-JSON-COMPARE-1.

next_room rows store predicted_value as JSON ({"top": ..., ...}); the
regime detector's accuracy-drop check compared the raw JSON to actual_value,
so hits were always 0 and the check could never fire. These tests build the
schema with the real ``UniversalRoomDatabase.initialize()`` (database.py's own
DDL + person_id migration), seed real-shape rows, and drive the production
``RegimeDetector._compute_cell_accuracy_drop``.

Oracles are hand-counted from the seeded rows (stated per window below).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from occ_dwell_helpers import make_real_db, real_package, seed

UTC = timezone.utc
PID = "person.jaya"
# Friday 2026-10-23 20:00 UTC. Recent window = since 2026-10-16T20:00,
# baseline window = 2026-09-16T20:00 .. 2026-10-16T20:00.
NOW = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
RECENT_TS = "2026-10-21T13:00:00+00:00"    # Wednesday, time_bin 3 (12-16h)
BASELINE_TS = "2026-10-07T13:00:00+00:00"  # Wednesday, time_bin 3

_INSERT = (
    "INSERT INTO prediction_results (room_id, prediction_timestamp, "
    "prediction_type, predicted_value, confidence, actual_value, "
    "error_value, person_id) VALUES (?, ?, 'next_room', ?, 0.5, ?, NULL, ?)"
)


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    import importlib

    global rd, dt_util
    with real_package():
        dt_util = importlib.import_module("homeassistant.util.dt")
        rd = importlib.import_module(
            "custom_components.universal_room_automation."
            "domain_coordinators.regime_detector")
        yield


def _pred(top: str) -> str:
    return json.dumps({"top": top, "alternatives": ["Game Room", "Garage A"],
                       "source": "frequency"})


def _rows(ts: str, hits: int, misses: int) -> list[tuple]:
    out = [("r", ts, _pred("Jaya Bathroom"), "Jaya Bathroom", PID)
           for _ in range(hits)]
    out += [("r", ts, _pred("Game Room"), "Jaya Bathroom", PID)
            for _ in range(misses)]
    return out


async def _drop(tmp_path, rows):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, _INSERT, rows)
    det = rd.RegimeDetector(MagicMock(), db, MagicMock())
    with patch.object(dt_util, "utcnow", return_value=NOW):
        return await det._compute_cell_accuracy_drop(PID, 3, 0)


@pytest.mark.asyncio
async def test_accuracy_drop_counts_json_top_hits_and_legacy_row(tmp_path):
    # Recent: 2 JSON hits + 8 JSON misses -> 2/10 = 0.2
    # Baseline: 8 JSON hits + 1 JSON miss + 1 legacy plain-string hit
    #   ("Kitchen" == "Kitchen") -> 9/10 = 0.9 ; drop 0.7 -> CRITICAL
    rows = _rows(RECENT_TS, 2, 8) + _rows(BASELINE_TS, 8, 1)
    rows.append(("r", BASELINE_TS, "Kitchen", "Kitchen", PID))
    res = await _drop(tmp_path, rows)
    assert res is not None
    assert res["recent_total"] == 10
    assert res["base_total"] == 10
    assert res["recent_hit_rate"] == 0.2
    assert res["baseline_hit_rate"] == 0.9
    assert res["drop"] == 0.7
    assert res["magnitude_bucket"] == "CRITICAL"


@pytest.mark.asyncio
async def test_recent_window_json_hits_suppress_drop(tmp_path):
    # Recent 9/10, baseline 9/10 -> no drop -> None. Under the old raw
    # compare both rates were 0 (also None) — so this pairs with the next
    # test: recent hits must be COUNTED to keep the drop below threshold.
    rows = _rows(RECENT_TS, 9, 1) + _rows(BASELINE_TS, 9, 1)
    assert await _drop(tmp_path, rows) is None


@pytest.mark.asyncio
async def test_recent_window_counts_json_hits(tmp_path):
    # Recent 6/10 = 0.6, baseline 10/10 = 1.0 -> drop 0.4 -> INFO.
    rows = _rows(RECENT_TS, 6, 4) + _rows(BASELINE_TS, 10, 0)
    res = await _drop(tmp_path, rows)
    assert res is not None
    assert res["recent_hit_rate"] == 0.6
    assert res["baseline_hit_rate"] == 1.0
    assert res["magnitude_bucket"] == "INFO"

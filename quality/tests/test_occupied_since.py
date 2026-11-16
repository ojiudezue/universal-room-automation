"""Arc step 8 §5.5: UniversalRoomCoordinator.occupied_since() (read-only onset).

The accessor delegates to get_became_occupied_time (one source). Oracles are
hand-set datetimes, not values re-derived from the code under test.
"""
from __future__ import annotations

from datetime import datetime, timezone

from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)


def _coord(onset):
    c = object.__new__(UniversalRoomCoordinator)
    c._became_occupied_time = onset
    return c


def test_occupied_since_returns_session_onset():
    onset = datetime(2026, 11, 15, 18, 4, 30, tzinfo=timezone.utc)
    c = _coord(onset)
    assert c.occupied_since() == datetime(2026, 11, 15, 18, 4, 30, tzinfo=timezone.utc)


def test_occupied_since_none_when_vacant():
    assert _coord(None).occupied_since() is None


def test_occupied_since_tracks_onset_change_same_object():
    c = _coord(datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc))
    c._became_occupied_time = datetime(2026, 11, 15, 9, 15, tzinfo=timezone.utc)
    assert c.occupied_since() == datetime(2026, 11, 15, 9, 15, tzinfo=timezone.utc)
    # read-only: reading does not clear or move the onset
    assert c._became_occupied_time == datetime(2026, 11, 15, 9, 15, tzinfo=timezone.utc)

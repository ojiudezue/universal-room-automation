"""FACE-ARRIVAL-REBUILD-1 D8a (plan rev 11 M2): `_resolve_egress_face_identity`
is kept as a thin 3-tuple wrapper over `_resolve_egress_face_identity_ex`."""

from __future__ import annotations

from datetime import timedelta

from test_egress_outcome_log import _state

def test_three_tuple_wrapper_equals_ex_prefix():
    """The kept 3-tuple method returns exactly the first three values of
    `_ex`, for an attach and for a veto (one body, two signatures)."""
    from test_egress_identity_producer_d2b import (
        _install_legs,
        _leg as _d2b_leg,
        _make_census,
        _make_tracker,
    )
    from datetime import datetime, timezone

    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    for state in ("home", "not_home"):
        census, hass, st = _make_census({})
        st["person.oji_udezue"] = _state(state)
        tracker = _make_tracker(census, hass, interior_stems=["foyer"])
        _install_legs(census, {
            "front_door": [_d2b_leg("sensor.front_door_last_recognized_face", "frigate",
                                    "d1", "oji_udezue", now - timedelta(seconds=20))],
        })
        three = tracker._resolve_egress_face_identity(
            "binary_sensor.front_door_person_occupancy", now, "exit",
        )
        four = tracker._resolve_egress_face_identity_ex(
            "binary_sensor.front_door_person_occupancy", now, "exit",
        )
        assert three == four[:3]
        assert four[3].outcome == ("attached" if state == "home" else "vetoed")
        assert four[3].slug == "oji_udezue"

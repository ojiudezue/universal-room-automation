"""RECORDER-CHURN-DIAG-SENSORS (2026-10-20) — diagnostic sensors must publish
identical state + attributes on consecutive refreshes when nothing
transitioned.

HA writes a recorder `states` row whenever the state OR the attribute dict
changes (and a new `state_attributes` row for each new attribute blob). The
classes below published per-refresh elapsed/remaining numbers, so every
refresh wrote rows (~20k/hr URA total, measured 2026-10-20).

Each test drives the real property code on an entity built with
`object.__new__` and a mock coordinator, reads (state, attrs) at T0, advances
the clock (and only the clock) inside one quantum, reads again, and asserts
equality. Boundary tests pin the quantum with hardcoded literals (never the
imported constant).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

from custom_components.universal_room_automation import sensor as sen  # noqa: E402

_UTC = timezone.utc
T0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=_UTC)


def _read(ent):
    return ent.native_value, dict(ent.extra_state_attributes or {})


def _room_entity(cls, data=None):
    ent = object.__new__(cls)
    coord = MagicMock()
    coord.data = data if data is not None else {}
    ent.coordinator = coord
    ent.hass = MagicMock()
    return ent, coord


# ---------------------------------------------------------------------------
# 1. AutomationHealthSensor
# ---------------------------------------------------------------------------
def _health(*, failsafe_s=3600):
    ent, c = _room_entity(sen.AutomationHealthSensor, {"occupied": True})
    c._failsafe_fired = False
    c._became_occupied_time = T0 - timedelta(minutes=20)
    c._get_failsafe_duration_seconds = MagicMock(return_value=failsafe_s)
    c._stuck_sensor_hours = 4.0
    c._sensor_on_since = {"binary_sensor.stuck": T0 - timedelta(hours=5)}
    c._dutycycle_excluded_now = {}
    c._occupancy_first_detected = T0 - timedelta(seconds=10)
    c._occupancy_debounce_seconds = 10_000
    c._all_sensors_unavailable_since = T0 - timedelta(seconds=10)
    c._unavail_grace_seconds = 10_000
    c._last_exit_verify_result = None
    c._last_exit_verify_time = None
    c.automation = None
    return ent, c


def test_automation_health_identical_across_refresh_no_transition():
    """Session, failsafe, stuck, debounce and grace are all in-flight; the
    clock moves 30 s (one refresh). Re-adding any elapsed/remaining number
    (session_duration_minutes, failsafe_remaining_minutes, on_hours,
    debounce_elapsed_seconds, grace_remaining_seconds) turns this RED."""
    ent, _c = _health()
    with patch.object(sen.dt_util, "now", return_value=T0):
        s1, a1 = _read(ent)
    with patch.object(sen.dt_util, "now", return_value=T0 + timedelta(seconds=30)):
        s2, a2 = _read(ent)
    assert s1 == s2 == "stuck_sensor"
    diffs = {k: (a1.get(k), a2.get(k)) for k in set(a1) | set(a2) if a1.get(k) != a2.get(k)}
    assert diffs == {}, diffs


def test_automation_health_stable_values_and_flags():
    """Oracle values derived by hand from the fixture stamps."""
    ent, c = _health(failsafe_s=3600)
    with patch.object(sen.dt_util, "now", return_value=T0):
        _s, a = _read(ent)
    assert a["session_started_at"] == "2026-10-20T09:40:00+00:00"
    # 09:40 + 3600 s (room-type failsafe from the coordinator, not 4 h)
    assert a["failsafe_at"] == "2026-10-20T10:40:00+00:00"
    assert a["stuck_sensors"] == [
        {"entity_id": "binary_sensor.stuck", "on_since": "2026-10-20T05:00:00+00:00"}
    ]
    assert a["debounce_active"] is True
    assert a["debounce_started_at"] == "2026-10-20T09:59:50+00:00"
    assert a["grace_active"] is True
    # 09:59:50 + 10000 s = 12:46:30
    assert a["grace_until"] == "2026-10-20T12:46:30+00:00"
    for gone in (
        "session_duration_minutes", "failsafe_remaining_minutes",
        "debounce_elapsed_seconds", "grace_remaining_seconds",
    ):
        assert gone not in a


def test_automation_health_vacant_publishes_none():
    ent, c = _health()
    c.data = {"occupied": False}
    c._occupancy_first_detected = None
    c._all_sensors_unavailable_since = None
    with patch.object(sen.dt_util, "now", return_value=T0):
        _s, a = _read(ent)
    assert a["session_started_at"] is None
    assert a["failsafe_at"] is None
    assert a["debounce_started_at"] is None
    assert a["grace_until"] is None


# ---------------------------------------------------------------------------
# 2. Last automation trigger / action / time — no `time_ago`
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cls", [
    "LastAutomationTriggerSensor",
    "LastAutomationActionSensor",
    "LastAutomationTimeSensor",
])
def test_last_automation_sensors_identical_across_refresh(cls):
    ent, c = _room_entity(getattr(sen, cls))
    c._last_trigger_source = "motion"
    c._last_trigger_entity = "binary_sensor.m"
    c._last_trigger_time = T0 - timedelta(seconds=5)
    c._last_action_description = "lights on"
    c._last_action_entity = "light.x"
    c._last_action_type = "turn_on"
    c._last_action_time = T0 - timedelta(seconds=5)
    with patch.object(sen.dt_util, "now", return_value=T0):
        s1, a1 = _read(ent)
    with patch.object(sen.dt_util, "now", return_value=T0 + timedelta(minutes=7)):
        s2, a2 = _read(ent)
    assert (s1, a1) == (s2, a2)
    assert "time_ago" not in a1


def test_last_automation_trigger_keeps_timestamp():
    ent, c = _room_entity(sen.LastAutomationTriggerSensor)
    c._last_trigger_source = "motion"
    c._last_trigger_entity = "binary_sensor.m"
    c._last_trigger_time = T0
    _s, a = _read(ent)
    assert a["timestamp"] == "2026-10-20T10:00:00+00:00"


def test_last_automation_time_never_publishes_no_time_ago():
    ent, c = _room_entity(sen.LastAutomationTimeSensor)
    c._last_action_time = None
    _s, a = _read(ent)
    assert a == {}


# ---------------------------------------------------------------------------
# 3. TimeSinceMotionSensor — floor to 60 s
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    (0, 0), (59, 0), (60, 60), (119, 60), (125, 120), (3601, 3600), (None, None),
])
def test_time_since_motion_floor_60(raw, expected):
    ent, _c = _room_entity(sen.TimeSinceMotionSensor, {"time_since_motion": raw})
    assert ent.native_value == expected


def test_time_since_motion_identical_within_minute():
    ent, c = _room_entity(sen.TimeSinceMotionSensor, {"time_since_motion": 125})
    v1 = ent.native_value
    c.data = {"time_since_motion": 170}  # three refreshes later
    assert ent.native_value == v1 == 120


# ---------------------------------------------------------------------------
# 4. URACensusValidationAgeSensor — floor to 60 s
# ---------------------------------------------------------------------------
def _census_age(ts):
    ent = object.__new__(sen.URACensusValidationAgeSensor)
    ent._get_census = lambda: SimpleNamespace(timestamp=ts)
    return ent


@pytest.mark.parametrize("age_s,expected", [(0, 0), (59, 0), (60, 60), (61, 60), (299, 240), (301, 300)])
def test_census_validation_age_floor_60(age_s, expected):
    ent = _census_age(T0)
    with patch.object(sen.dt_util, "utcnow", return_value=T0 + timedelta(seconds=age_s)):
        assert ent.native_value == expected


def test_census_validation_age_identical_across_refresh():
    ent = _census_age(T0)
    with patch.object(sen.dt_util, "utcnow", return_value=T0 + timedelta(seconds=65)):
        v1 = ent.native_value
    with patch.object(sen.dt_util, "utcnow", return_value=T0 + timedelta(seconds=95)):
        v2 = ent.native_value
    assert v1 == v2 == 60


# ---------------------------------------------------------------------------
# 5. OccupancyTimeoutSensor — ceil to 30 s
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    (0, 0), (1, 30), (29, 30), (30, 30), (31, 60), (299, 300), (300, 300),
])
def test_occupancy_timeout_remaining_ceil_30(raw, expected):
    ent, _c = _room_entity(sen.OccupancyTimeoutSensor, {"timeout_remaining": raw})
    assert ent.native_value == expected


def test_occupancy_timeout_remaining_identical_within_step():
    ent, c = _room_entity(sen.OccupancyTimeoutSensor, {"timeout_remaining": 290})
    v1 = ent.native_value
    c.data = {"timeout_remaining": 271}
    assert ent.native_value == v1 == 300


def test_occupancy_timeout_remaining_no_data_is_zero():
    ent, _c = _room_entity(sen.OccupancyTimeoutSensor, {})
    ent.coordinator.data = None
    assert ent.native_value == 0


# ---------------------------------------------------------------------------
# 6. HVACACRampKwhRateSensor — no `age_seconds`; last_updated unrecorded
# ---------------------------------------------------------------------------
class _FakeDT(datetime):
    _now = T0

    @classmethod
    def now(cls, tz=None):
        return cls._now


def _kwh():
    ent = object.__new__(sen.HVACACRampKwhRateSensor)
    ent._zone_name = "Zone 1"
    ent._climate_entity = "climate.z1"
    zone = SimpleNamespace(ac_load_sensor="sensor.ac_load", kwh_rate_threshold=1.5)
    ent._get_zone = lambda: zone
    src = SimpleNamespace(
        state="2.5", attributes={"unit_of_measurement": "kW"},
        last_updated=T0 - timedelta(seconds=20),
    )
    ent.hass = MagicMock()
    ent.hass.states.get = lambda eid: src if eid == "sensor.ac_load" else None
    return ent


def test_ac_kwh_rate_identical_across_refresh_same_source_reading():
    ent = _kwh()
    with patch.object(sen, "datetime", _FakeDT):
        _FakeDT._now = T0
        s1, a1 = _read(ent)
        _FakeDT._now = T0 + timedelta(seconds=30)
        s2, a2 = _read(ent)
    assert (s1, a1) == (s2, a2)
    assert s1 == 2.5
    assert "age_seconds" not in a1
    assert a1["last_updated"] == "2026-10-20T09:59:40+00:00"
    assert a1["stale"] is False


def test_ac_kwh_rate_stale_flag_still_computed():
    ent = _kwh()
    with patch.object(sen, "datetime", _FakeDT):
        _FakeDT._now = T0 + timedelta(hours=2)
        _s, a = _read(ent)
    assert a["stale"] is True


def test_ac_kwh_rate_last_updated_unrecorded():
    assert "last_updated" in sen.HVACACRampKwhRateSensor._unrecorded_attributes


# ---------------------------------------------------------------------------
# Fix-up 1
# ---------------------------------------------------------------------------
def test_automation_health_excluded_sensors_stable_across_restamp():
    """The coordinator re-stamps `_dutycycle_excluded_now[eid] = now` every
    tick (coordinator.py ~3383 / ~3526). Publishing that stamp churned."""
    ent, c = _health()
    c._dutycycle_excluded_now = {"binary_sensor.b": T0, "binary_sensor.a": T0}
    with patch.object(sen.dt_util, "now", return_value=T0):
        _s1, a1 = _read(ent)
    c._dutycycle_excluded_now = {
        "binary_sensor.a": T0 + timedelta(seconds=30),
        "binary_sensor.b": T0 + timedelta(seconds=30),
    }
    with patch.object(sen.dt_util, "now", return_value=T0 + timedelta(seconds=30)):
        _s2, a2 = _read(ent)
    assert a1["excluded_sensors"] == a2["excluded_sensors"] == [
        ("binary_sensor.a", "dutycycle"), ("binary_sensor.b", "dutycycle"),
    ]


def test_census_validation_age_future_stamp_clamped_to_zero():
    ent = _census_age(T0 + timedelta(seconds=90))  # census stamp 90 s ahead
    with patch.object(sen.dt_util, "utcnow", return_value=T0):
        assert ent.native_value == 0


def test_last_occupant_no_time_ago_identical_across_refresh():
    ent = object.__new__(sen.LastOccupantSensor)
    ent._last_occupant_time = "2026-10-20T09:00:00+00:00"
    with patch.object(sen.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    with patch.object(sen.dt_util, "utcnow", return_value=T0 + timedelta(minutes=5)):
        a2 = dict(ent.extra_state_attributes)
    assert a1 == a2 == {"last_seen": "2026-10-20T09:00:00+00:00"}

"""OccupancyAnomalyBinarySensor on the dwell model (BAYES-OCCUPANCY-ANOMALY-
NEVER-EVALUATES-1, plan D2 + D3).

I1: on only when (a) occupied, (b) cell share strictly < threshold, (c) cell
samples >= min, (d) occupied >= debounce, (e) not GUEST, (f) model refreshed.
Each clause is negated alone. Boundaries use literals (not the constants).
I2: no notification on any path. I3: one row per rising edge, cooldown,
none in observation mode.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from occ_dwell_helpers import default_tz, fetch, make_real_db

from custom_components.universal_room_automation import binary_sensor as bs
from custom_components.universal_room_automation import room_dwell_model as rdm
from custom_components.universal_room_automation.const import (
    DOMAIN,
    STATE_BLE_PERSONS,
    STATE_OCCUPANCY_SOURCE,
    STATE_OCCUPIED,
    STATE_RADAR_SOLE_TICK,
)

UTC = timezone.utc
ENTRY_ID = "entry_kitchen"
# Wednesday 03:30 UTC; the tests run with HA's default tz, and the model is
# fed buckets in that same zone via _bucket(), so the "now" cell is fixed.
NOW = datetime(2026, 10, 21, 3, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _utc_default_tz():
    """Pin HA's default zone so the "now" cell is weekday 03:00 in every
    test regardless of what an earlier test file left behind."""
    with default_tz("UTC"):
        yield


def _bucket(local: datetime) -> str:
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H")


def _model(occ: int, n: int, at: datetime = NOW) -> rdm.RoomDwellModel:
    """A refreshed model whose cell at ``at`` holds occ/n."""
    m = rdm.RoomDwellModel()
    prior_week = (at - timedelta(days=7)).astimezone(dt_util.DEFAULT_TIME_ZONE)
    assert m.refresh([(ENTRY_ID, _bucket(prior_week), occ, n)],
                     dt_util.DEFAULT_TIME_ZONE,
                     now_utc=at, window_days=56)
    return m


class _Coord:
    def __init__(self):
        self.entry = SimpleNamespace(entry_id=ENTRY_ID,
                                     data={"room_name": "Kitchen"})
        self.data = {}
        self.became = None
        self.last_update_success = True

    def get_became_occupied_time(self):
        return self.became

    def _get_room_area(self):
        return None


class _NM:
    def __init__(self):
        self.async_notify = AsyncMock()
        self.calls = []

    def __getattr__(self, name):  # any other NM entry point is a failure
        raise AssertionError(f"NotificationManager.{name} used")


def _make(model=None, *, house="home_day", observation=False, db=None,
          nm=None, startup_ago_s=10_000):
    coord = _Coord()
    ent = bs.OccupancyAnomalyBinarySensor(coord)
    tasks = []

    def _create_task(coro, *a, **k):
        t = asyncio.ensure_future(coro)
        tasks.append(t)
        return t

    presence = SimpleNamespace(observation_mode=observation)
    manager = SimpleNamespace(house_state=house,
                              coordinators={"presence": presence})
    domain = {"coordinator_manager": manager}
    if model is not None:
        domain[rdm.HASS_DATA_KEY] = SimpleNamespace(model=model)
    if db is not None:
        domain["database"] = db
    if nm is not None:
        domain["notification_manager"] = nm
    ent.hass = SimpleNamespace(data={DOMAIN: domain},
                               async_create_task=_create_task)
    ent._startup_time = NOW - timedelta(seconds=startup_ago_s)
    ent._tasks = tasks
    ent._signals = []
    return ent, coord


def _tick(ent, coord, *, occupied: bool, now: datetime = NOW,
          occupied_for_s: float | None = 1200.0):
    coord.data = {
        STATE_OCCUPIED: occupied,
        STATE_OCCUPANCY_SOURCE: "presence_sensors",
        STATE_RADAR_SOLE_TICK: True,
        STATE_BLE_PERSONS: ["ziri"],
    }
    coord.became = (
        now - timedelta(seconds=occupied_for_s)
        if occupied and occupied_for_s is not None else None
    )

    def _send(hass, signal, payload):
        ent._signals.append((signal, payload))

    with patch.object(bs.dt_util, "now", return_value=now), \
            patch.object(bs.dt_util, "utcnow", return_value=now), \
            patch("homeassistant.helpers.dispatcher.async_dispatcher_send", _send):
        ent._evaluate()
    return ent.is_on


# 2/480 = 0.0042 < 0.02; 480 >= 200 samples.
LOW = (2, 480)


# ---------------------------------------------------------------------------
# I1: each clause alone
# ---------------------------------------------------------------------------


def test_fires_when_all_clauses_hold():
    ent, coord = _make(_model(*LOW))
    assert _tick(ent, coord, occupied=True) is True
    a = ent.extra_state_attributes
    assert a["expected_share"] == 0.0042
    assert a["cell_samples"] == 480
    assert a["learning_status"] == "ok"
    assert a["suppressed_reason"] is None
    assert a["occupied_for_min"] == 20
    assert a["radar_sole"] is True and a["ble_persons"] == ["ziri"]
    assert a["room"] == "Kitchen"


def test_clause_a_vacant_off():
    ent, coord = _make(_model(*LOW))
    assert _tick(ent, coord, occupied=False) is False


def test_clause_a_vacant_off_with_zero_debounce():
    """Config extreme: debounce 0 must not let a VACANT room fire (the
    debounce is not what holds clause (a))."""
    from custom_components.universal_room_automation import const

    ent, coord = _make(_model(*LOW))
    with patch.object(const, "OCC_ANOMALY_DEBOUNCE_S", 0):
        assert _tick(ent, coord, occupied=False) is False
        assert _tick(ent, coord, occupied=True) is True


def test_clause_b_share_at_threshold_off_strict():
    ent, coord = _make(_model(10, 500))  # exactly 0.02
    assert _tick(ent, coord, occupied=True) is False
    ent2, coord2 = _make(_model(9, 500))  # 0.018
    assert _tick(ent2, coord2, occupied=True) is True


def test_usual_room_never_fires():
    """Discriminating: share 0.6 occupied 2 h stays off. The old arrival
    model scored Study A 0.004 and would have fired here."""
    ent, coord = _make(_model(288, 480))
    assert _tick(ent, coord, occupied=True, occupied_for_s=7200) is False
    assert ent.extra_state_attributes["expected_share"] == 0.6
    assert ent.extra_state_attributes["usual_hours"].startswith("weekdays 03")


def test_clause_c_min_samples_boundary():
    ent, coord = _make(_model(0, 199))
    assert _tick(ent, coord, occupied=True) is False
    assert ent.extra_state_attributes["learning_status"] == "learning"
    assert ent.extra_state_attributes["suppressed_reason"] == "learning"
    ent2, coord2 = _make(_model(0, 200))
    assert _tick(ent2, coord2, occupied=True) is True


def test_clause_c_empty_cell_is_learning():
    ent, coord = _make(_model(0, 480, at=NOW + timedelta(hours=5)))
    assert _tick(ent, coord, occupied=True) is False
    assert ent.extra_state_attributes["learning_status"] == "learning"


def test_clause_d_debounce_boundary():
    ent, coord = _make(_model(*LOW))
    assert _tick(ent, coord, occupied=True, occupied_for_s=899) is False
    assert ent.extra_state_attributes["suppressed_reason"] == "debouncing"
    assert ent.extra_state_attributes["debounce_remaining_s"] == 1
    assert _tick(ent, coord, occupied=True, occupied_for_s=900) is True
    ent2, coord2 = _make(_model(*LOW))
    assert _tick(ent2, coord2, occupied=True, occupied_for_s=901) is True


def test_clause_d_no_coordinator_stamp_uses_first_seen():
    """became_occupied_time None while occupied: the debounce runs from this
    entity's first occupied tick."""
    ent, coord = _make(_model(*LOW))
    assert _tick(ent, coord, occupied=True, occupied_for_s=None) is False
    assert ent.extra_state_attributes["suppressed_reason"] == "debouncing"
    later = NOW + timedelta(seconds=899)
    assert _tick(ent, coord, occupied=True, now=later,
                 occupied_for_s=None) is False
    later = NOW + timedelta(seconds=900)
    assert _tick(ent, coord, occupied=True, now=later,
                 occupied_for_s=None) is True


def test_clause_d_first_seen_resets_on_vacant():
    ent, coord = _make(_model(*LOW))
    _tick(ent, coord, occupied=True, occupied_for_s=None)
    _tick(ent, coord, occupied=False, now=NOW + timedelta(seconds=600))
    t = NOW + timedelta(seconds=1000)
    assert _tick(ent, coord, occupied=True, now=t, occupied_for_s=None) is False


def test_clause_e_guest_off():
    ent, coord = _make(_model(*LOW), house="guest")
    assert _tick(ent, coord, occupied=True) is False
    assert ent.extra_state_attributes["suppressed_reason"] == "guest_mode"


def test_clause_f_no_model_off():
    ent, coord = _make(None)
    assert _tick(ent, coord, occupied=True) is False
    assert ent.extra_state_attributes["learning_status"] == "no_model"
    ent2, coord2 = _make(rdm.RoomDwellModel())  # never refreshed
    assert _tick(ent2, coord2, occupied=True) is False
    assert ent2.extra_state_attributes["learning_status"] == "no_model"
    assert ent2.extra_state_attributes["model_status"] == "never_refreshed"


def test_kill_switch_disabled_off():
    from custom_components.universal_room_automation import const

    ent, coord = _make(_model(*LOW))
    with patch.object(const, "OCC_ANOMALY_DWELL_ENABLED", False):
        assert _tick(ent, coord, occupied=True) is False
    assert ent.extra_state_attributes["learning_status"] == "disabled"


def test_discharges_on_vacant_tick():
    ent, coord = _make(_model(*LOW))
    assert _tick(ent, coord, occupied=True) is True
    assert _tick(ent, coord, occupied=False,
                 now=NOW + timedelta(seconds=30)) is False


# ---------------------------------------------------------------------------
# The defect: nothing called the evaluation. Drive the REAL CoordinatorEntity
# listener path (coordinator.async_set_updated_data -> entity callback).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluates_on_coordinator_update():
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
    import logging

    hass = MagicMock()
    hass.data = {}
    hass.loop = asyncio.get_running_loop()

    class _RealCoord(DataUpdateCoordinator):
        def __init__(self, h):
            super().__init__(h, logging.getLogger("t"), name="t",
                             config_entry=None)
            self.entry = SimpleNamespace(entry_id=ENTRY_ID,
                                         data={"room_name": "Kitchen"})
            self.became = NOW - timedelta(seconds=1200)

        def get_became_occupied_time(self):
            return self.became

        def _get_room_area(self):
            return None

    coord = _RealCoord(hass)
    ent = bs.OccupancyAnomalyBinarySensor(coord)
    ent.hass = hass
    ent.entity_id = "binary_sensor.kitchen_occupancy_anomaly"
    ent.async_write_ha_state = MagicMock()
    hass.data.setdefault(DOMAIN, {})[rdm.HASS_DATA_KEY] = SimpleNamespace(
        model=_model(*LOW))
    hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
        house_state="home_day", coordinators={})
    ent._startup_time = NOW  # inside the grace: no record side effects
    await ent.async_added_to_hass()
    try:
        with patch.object(bs.dt_util, "now", return_value=NOW), \
                patch.object(bs.dt_util, "utcnow", return_value=NOW):
            coord.async_set_updated_data({STATE_OCCUPIED: True})
            assert ent.is_on is True
            coord.async_set_updated_data({STATE_OCCUPIED: False})
            assert ent.is_on is False
        assert ent.async_write_ha_state.call_count == 2
    finally:
        await ent.async_will_remove_from_hass()
        hass.data[DOMAIN].pop(rdm.HASS_DATA_KEY, None)
        hass.data[DOMAIN].pop("coordinator_manager", None)


# ---------------------------------------------------------------------------
# D3: no notification, one record, cooldown, observation mode, grace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_notification_on_rising_edge():
    nm = _NM()
    db = SimpleNamespace(save_anomaly_event=AsyncMock())
    ent, coord = _make(_model(*LOW), db=db, nm=nm)
    _tick(ent, coord, occupied=True)
    await asyncio.gather(*ent._tasks)
    nm.async_notify.assert_not_called()
    assert db.save_anomaly_event.await_count == 1
    assert len(ent._signals) == 1
    sig, payload = ent._signals[0]
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        SIGNAL_OCCUPANCY_ANOMALY,
    )
    assert sig == SIGNAL_OCCUPANCY_ANOMALY
    assert payload == {
        "room": "Kitchen", "entry_id": ENTRY_ID, "expected_share": 0.0042,
        "threshold": 0.02, "cell": "weekday 03:00",
        "occupied_since": (NOW - timedelta(seconds=1200)).isoformat(),
        "occupancy_source": "presence_sensors", "radar_sole": True,
    }


@pytest.mark.asyncio
async def test_anomaly_log_row_shape(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        ent, coord = _make(_model(*LOW), db=db)
        _tick(ent, coord, occupied=True)
        await asyncio.gather(*ent._tasks)
        rows = fetch(db, "SELECT coordinator_id, severity, anomaly_type, "
                         "context_json, room_id, expected_mean, sample_size, "
                         "observed_value, metric_name FROM anomaly_log")
    finally:
        await db.stop_write_worker()
    assert len(rows) == 1
    coord_id, sev, atype, ctx, room, mean, n, obs, typ = rows[0]
    assert (coord_id, int(sev), atype, room) == (
        "occupancy", 0, "point_in_time", "Kitchen")
    assert typ == "occupancy.dwell_anomaly"
    assert (mean, n, obs) == (0.0042, 480, 1.0)
    payload = json.loads(ctx)
    flat = {**payload, **payload.get("extra", {})}
    assert flat["expected_share"] == 0.0042
    assert flat["cell_samples"] == 480
    assert flat["ble_persons"] == ["ziri"]
    assert flat["entry_id"] == ENTRY_ID


@pytest.mark.asyncio
async def test_log_cooldown():
    db = SimpleNamespace(save_anomaly_event=AsyncMock())
    ent, coord = _make(_model(*LOW), db=db)
    _tick(ent, coord, occupied=True)                      # edge 1: record
    _tick(ent, coord, occupied=False, now=NOW + timedelta(seconds=60))
    _tick(ent, coord, occupied=True, now=NOW + timedelta(seconds=1799))
    assert ent.is_on is True                              # edge 2: in cooldown
    _tick(ent, coord, occupied=False, now=NOW + timedelta(seconds=1799))
    _tick(ent, coord, occupied=True, now=NOW + timedelta(seconds=1800))
    await asyncio.gather(*ent._tasks)                     # edge 3: record
    assert db.save_anomaly_event.await_count == 2
    assert len(ent._signals) == 2


@pytest.mark.asyncio
async def test_observation_mode_no_row():
    db = SimpleNamespace(save_anomaly_event=AsyncMock())
    ent, coord = _make(_model(*LOW), db=db, observation=True)
    assert _tick(ent, coord, occupied=True) is True       # state still shows
    await asyncio.gather(*ent._tasks)
    assert db.save_anomaly_event.await_count == 0
    assert ent._signals == []


@pytest.mark.asyncio
async def test_startup_grace_boundary():
    db = SimpleNamespace(save_anomaly_event=AsyncMock())
    ent, coord = _make(_model(*LOW), db=db, startup_ago_s=299)
    _tick(ent, coord, occupied=True)
    assert db.save_anomaly_event.await_count == 0 and ent._signals == []
    ent2, coord2 = _make(_model(*LOW), db=db, startup_ago_s=300)
    _tick(ent2, coord2, occupied=True)
    await asyncio.gather(*ent2._tasks)
    assert db.save_anomaly_event.await_count == 1


@pytest.mark.asyncio
async def test_no_record_while_staying_on():
    """Only the rising edge records, even with the cooldown at 0."""
    from custom_components.universal_room_automation import const

    db = SimpleNamespace(save_anomaly_event=AsyncMock())
    ent, coord = _make(_model(*LOW), db=db, startup_ago_s=10_000)
    with patch.object(const, "OCC_ANOMALY_LOG_COOLDOWN_S", 0):
        for s in (0, 30, 60, 1700):
            _tick(ent, coord, occupied=True, now=NOW + timedelta(seconds=s))
    await asyncio.gather(*ent._tasks)
    assert db.save_anomaly_event.await_count == 1
    assert len(ent._signals) == 1


@pytest.mark.asyncio
async def test_remove_cancels_pending_write():
    gate = asyncio.Event()

    async def _slow(_event):
        await gate.wait()

    db = SimpleNamespace(save_anomaly_event=_slow)
    ent, coord = _make(_model(*LOW), db=db)
    _tick(ent, coord, occupied=True)
    assert len(ent._pending_tasks) == 1
    task = next(iter(ent._pending_tasks))
    with patch("homeassistant.helpers.update_coordinator.CoordinatorEntity."
               "async_will_remove_from_hass", AsyncMock()):
        await ent.async_will_remove_from_hass()
    await asyncio.sleep(0)
    assert task.cancelled()
    assert ent._pending_tasks == set()

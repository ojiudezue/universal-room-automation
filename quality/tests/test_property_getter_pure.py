"""PROPERTY-GETTER-SIDE-EFFECT-TASKS-1 — property getters must be pure.

Three getters used to spawn tasks on every read (any reader thread):
  1. aggregation.SafetyAlertBinarySensor.is_on      -> _process_alerts
  2. sensor.UnavailableEntitiesSensor.native_value  -> log_memory_episode
  3. sensor.SafetyEventsSummarySensor.native_value  -> _refresh_cache

The work now runs from on-loop update paths (the discharge):
  1 + 3 -> async_update (HA poll), 2 -> _handle_coordinator_update.

Drives the REAL entity classes (object.__new__ to skip the fragile
constructor chain, same pattern as test_prediction_sensor_kill_list).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mods():
    try:
        from custom_components.universal_room_automation import (  # noqa: PLC0415
            aggregation as _agg,
            sensor as _sen,
        )
    except Exception:  # noqa: BLE001
        pytest.skip("integration not importable in this environment")
    return _agg, _sen


def _hass():
    """hass double whose async_create_task records + closes coroutines."""
    hass = MagicMock()
    created = []

    def _create(coro, *a, **kw):
        if asyncio.iscoroutine(coro):
            coro.close()
        task = MagicMock()
        task.done.return_value = False
        created.append(task)
        return task

    hass.async_create_task.side_effect = _create
    hass.created = created
    return hass


# ---------------------------------------------------------------- site 1


def _safety_alert(agg, monkeypatch, *, temp):
    hass = _hass()
    hass.data = {}
    coord = MagicMock()
    coord.entry.data = {"room_name": "Garage A"}
    coord.entry.options = {}
    coord.data = {agg.STATE_TEMPERATURE: temp}
    monkeypatch.setattr(agg, "_get_room_coordinators", lambda h: [coord])
    s = object.__new__(agg.SafetyAlertBinarySensor)
    s.hass = hass
    s._last_alert_time = None
    s._alert_task = None
    return s, hass


def test_safety_alert_is_on_spawns_no_task(mods, monkeypatch):
    agg, _ = mods
    s, hass = _safety_alert(agg, monkeypatch, temp=92.8)
    for _ in range(5):
        assert s.is_on is True
    attrs = s.extra_state_attributes
    assert attrs["alert_count"] == 1
    assert attrs["alerts"][0]["issue"] == "too_hot"
    hass.async_create_task.assert_not_called()


def test_safety_alert_update_dispatches_once_and_guards(mods, monkeypatch):
    agg, _ = mods
    s, hass = _safety_alert(agg, monkeypatch, temp=92.8)
    asyncio.run(s.async_update())
    assert hass.async_create_task.call_count == 1
    # Re-entry guard: in-flight task -> no pile-up.
    asyncio.run(s.async_update())
    assert hass.async_create_task.call_count == 1
    # Finished task -> next poll dispatches again.
    hass.created[0].done.return_value = True
    asyncio.run(s.async_update())
    assert hass.async_create_task.call_count == 2


def test_safety_alert_update_no_alerts_no_task(mods, monkeypatch):
    agg, _ = mods
    s, hass = _safety_alert(agg, monkeypatch, temp=70.0)
    asyncio.run(s.async_update())
    assert s.is_on is False
    hass.async_create_task.assert_not_called()


# ---------------------------------------------------------------- site 2


def _unavail(sen, eids):
    hass = _hass()
    db = MagicMock()
    hass.data = {sen.DOMAIN: {"database": db}}
    coord = MagicMock()
    coord.hass = hass
    coord.room_name = "Garage A"
    s = object.__new__(sen.UnavailableEntitiesSensor)
    s.coordinator = coord
    s._get_unavailable_entities = lambda: list(eids)
    s.async_write_ha_state = MagicMock()
    return s, hass, db


def test_unavailable_native_value_spawns_no_task(mods):
    _, sen = mods
    s, hass, db = _unavail(sen, ["light.a", "sensor.b"])
    for _ in range(5):
        assert s.native_value == 2
    hass.async_create_task.assert_not_called()
    db.log_memory_episode.assert_not_called()


def test_unavailable_coordinator_update_logs_dropout_once(mods):
    _, sen = mods
    s, hass, db = _unavail(sen, ["light.a"])
    s._handle_coordinator_update()
    assert hass.async_create_task.call_count == 1
    kw = db.log_memory_episode.call_args.kwargs
    assert kw["node_id"] == "room:garage_a"
    assert kw["episode_type"] == "sensor_dropout"
    assert kw["attrs"]["entities"] == ["light.a"]
    assert s.async_write_ha_state.call_count == 1
    # Still non-empty -> no second episode.
    s._handle_coordinator_update()
    assert hass.async_create_task.call_count == 1
    assert s.async_write_ha_state.call_count == 2


def test_unavailable_coordinator_update_empty_no_episode(mods):
    _, sen = mods
    s, hass, db = _unavail(sen, [])
    s._handle_coordinator_update()
    hass.async_create_task.assert_not_called()
    assert s.async_write_ha_state.call_count == 1


# ---------------------------------------------------------------- site 3


def _summary(sen):
    hass = _hass()
    s = object.__new__(sen.SafetyEventsSummarySensor)
    s.hass = hass
    s._cache_time = None
    s._cached_count = 7
    s._cached_auto_dismissed = 0
    s._cached_last_event_at = None
    s._refresh_task = None
    return s, hass


def test_summary_native_value_spawns_no_task(mods):
    _, sen = mods
    s, hass = _summary(sen)
    for _ in range(5):
        assert s.native_value == 7
    hass.async_create_task.assert_not_called()


def test_summary_update_refreshes_when_stale_and_guards(mods):
    _, sen = mods
    s, hass = _summary(sen)
    asyncio.run(s.async_update())
    assert hass.async_create_task.call_count == 1
    asyncio.run(s.async_update())  # in-flight -> guarded
    assert hass.async_create_task.call_count == 1


def test_summary_update_skips_when_fresh(mods):
    _, sen = mods
    s, hass = _summary(sen)
    from homeassistant.util import dt as dt_util  # noqa: PLC0415

    s._cache_time = dt_util.utcnow()
    asyncio.run(s.async_update())
    hass.async_create_task.assert_not_called()

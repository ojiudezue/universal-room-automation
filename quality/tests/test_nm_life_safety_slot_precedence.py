"""NM-MULTI-ALERT-TRACKING-1 (SIMPLIFY): life-safety keeps NM's single slot.

Drives the REAL Safety -> CoordinatorManager -> NotificationManager path for
the smoke alert and the REAL ``async_notify`` -> ``_enter_alerting`` path for
the perimeter CRITICAL. Oracles are literals: urgent smoke cadence 30 s, the
perimeter hazard token "exterior_person", ack target (safety, smoke).
"""
from __future__ import annotations

import asyncio

import pytest

from test_safety_nm_refire import (  # noqa: F401  (clock is a fixture)
    AlertState,
    Rig,
    clock,
    nm_mod,
)

_SCHED_KEY = "nm_life_safety_repeat_schedule"


def _repeat_delays(rig):
    return [d for d, cb in rig.later if getattr(cb, "__name__", "") == "_repeat_alert"]


async def _urgent_smoke_rig(monkeypatch, clock):
    rig = Rig(monkeypatch, clock)
    monkeypatch.setattr(rig.nm, "_refresh_config", lambda: None)
    rig.nm._config[_SCHED_KEY] = "urgent"
    await rig.raise_smoke()
    assert rig.nm._active_alert_data["hazard_type"] == "smoke"
    assert _repeat_delays(rig)[-1] == 30
    return rig


async def _perimeter_critical(rig, hazard="exterior_person", title="Person at gate"):
    await rig.nm.async_notify(
        coordinator_id="perimeter",
        severity=nm_mod.Severity.CRITICAL,
        title=title,
        message="person detected at side gate",
        hazard_type=hazard,
        location="Side Gate",
    )


@pytest.mark.asyncio
async def test_smoke_keeps_slot_when_perimeter_critical_arrives(monkeypatch, clock):
    rig = await _urgent_smoke_rig(monkeypatch, clock)
    episode = rig.nm._active_episode_id
    rows_before = len(rig.channel_rows())
    rig.later.clear()
    clock.advance(5)

    await _perimeter_critical(rig)

    # Perimeter still delivered on its channels once.
    new_rows = rig.channel_rows()[rows_before:]
    assert new_rows and all(r["hazard_type"] == "exterior_person" for r in new_rows)
    # Slot unchanged: same episode, still smoke, cadence still 30 s, no reschedule.
    assert rig.nm.alert_state == AlertState.REPEATING
    assert rig.nm._active_episode_id == episode
    assert rig.nm._active_alert_data["hazard_type"] == "smoke"
    assert rig.nm._active_alert_data["coordinator_id"] == "safety"
    assert _repeat_delays(rig) == []
    assert rig.nm._repeat_interval_for_active_alert() == 30

    # Ack clears the smoke episode and targets the smoke DB row.
    await rig.nm.async_acknowledge()
    assert episode in rig.nm._ack_registry
    assert rig.nm.alert_state == AlertState.COOLDOWN
    rig.db.acknowledge_notification.assert_awaited_once_with(
        coordinator_id="safety", hazard_type="smoke"
    )


@pytest.mark.asyncio
async def test_life_safety_newcomer_preempts_non_life_safety_slot(monkeypatch, clock):
    rig = Rig(monkeypatch, clock)
    await _perimeter_critical(rig)
    assert rig.nm._active_alert_data["hazard_type"] == "exterior_person"
    clock.advance(5)
    await rig.raise_smoke()
    assert rig.nm._active_alert_data["hazard_type"] == "smoke"
    assert rig.nm._active_alert_data["coordinator_id"] == "safety"


@pytest.mark.asyncio
async def test_life_safety_newcomer_preempts_life_safety_slot(monkeypatch, clock):
    rig = await _urgent_smoke_rig(monkeypatch, clock)
    clock.advance(5)
    await _perimeter_critical(rig, hazard="intruder", title="Intruder")
    assert rig.nm._active_alert_data["hazard_type"] == "intruder"


@pytest.mark.asyncio
async def test_non_life_safety_over_non_life_safety_unchanged(monkeypatch, clock):
    rig = Rig(monkeypatch, clock)
    await rig.nm.async_notify(
        coordinator_id="energy", severity=nm_mod.Severity.CRITICAL,
        title="Reserve", message="reserve low", hazard_type="reserve_soc",
    )
    assert rig.nm._active_alert_data["hazard_type"] == "reserve_soc"
    clock.advance(5)
    await _perimeter_critical(rig)
    assert rig.nm._active_alert_data["hazard_type"] == "exterior_person"
    await rig.nm.async_acknowledge()
    rig.db.acknowledge_notification.assert_awaited_once_with(
        coordinator_id="perimeter", hazard_type="exterior_person"
    )


@pytest.mark.asyncio
async def test_acked_smoke_does_not_hold_slot(monkeypatch, clock):
    """Guard requires an ACTIVE (unacked) slot: after ack, perimeter takes it."""
    rig = await _urgent_smoke_rig(monkeypatch, clock)
    await rig.nm.async_acknowledge()
    assert rig.nm.alert_state == AlertState.COOLDOWN
    clock.advance(5)
    await _perimeter_critical(rig)
    assert rig.nm._active_alert_data["hazard_type"] == "exterior_person"


@pytest.mark.asyncio
async def test_db_targeted_ack_hits_slot_row_not_latest(tmp_path):
    from test_imsg_audit_fix_1 import _drain, _make_db
    import sqlite3

    db = _make_db(str(tmp_path))
    await db.initialize()
    await db.start_write_worker()
    smoke_id = await db.log_notification(
        coordinator_id="safety", severity="CRITICAL", title="Smoke",
        message="smoke in garage", hazard_type="smoke", delivered=1,
    )
    await asyncio.sleep(0.004)
    perim_id = await db.log_notification(
        coordinator_id="perimeter", severity="CRITICAL", title="Person",
        message="person at gate", hazard_type="exterior_person", delivered=1,
    )
    await db.acknowledge_notification(coordinator_id="safety", hazard_type="smoke")
    await _drain(db)
    conn = sqlite3.connect(db.db_file)
    acked = dict(conn.execute("SELECT id, acknowledged FROM notification_log"))
    conn.close()
    assert acked[smoke_id] == 1
    assert acked[perim_id] == 0

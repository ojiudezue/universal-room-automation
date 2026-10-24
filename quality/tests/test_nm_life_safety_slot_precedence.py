"""NM-MULTI-ALERT-TRACKING-1 (SIMPLIFY): life-safety keeps NM's single slot.

Drives the REAL Safety -> CoordinatorManager -> NotificationManager path for
the smoke alert and the REAL ``async_notify`` -> ``_enter_alerting`` path for
the perimeter CRITICAL. Oracles are literals: urgent smoke cadence 30 s, the
perimeter hazard token "exterior_person", ack target (safety, smoke).
"""
from __future__ import annotations

import asyncio

import sqlite3
from unittest.mock import AsyncMock

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


# ---------------------------------------------------------------------------
# Fix-up (Reviews A/B/C): restart recovery, guarded-newcomer ack, cooldown row,
# untargeted ack fallback, NULL hazard, hazard discrimination, helper units.
# ---------------------------------------------------------------------------

async def _real_db(tmp_path):
    from test_imsg_audit_fix_1 import _make_db
    db = _make_db(str(tmp_path))
    await db.initialize()
    await db.start_write_worker()
    return db


def _rows(db):
    conn = sqlite3.connect(db.db_file)
    conn.row_factory = sqlite3.Row
    out = [dict(r) for r in conn.execute(
        "SELECT id, coordinator_id, hazard_type, acknowledged, cooldown_expires "
        "FROM notification_log WHERE message != '[audit]'"
    )]
    conn.close()
    return out


@pytest.mark.asyncio
async def test_real_db_guard_acks_newcomer_and_cooldown_lands_on_smoke(
    monkeypatch, clock, tmp_path
):
    from test_imsg_audit_fix_1 import _drain
    rig = Rig(monkeypatch, clock)
    db = await _real_db(tmp_path)
    rig.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    monkeypatch.setattr(rig.nm, "_refresh_config", lambda: None)
    rig.nm._config[_SCHED_KEY] = "urgent"
    await rig.raise_smoke()
    await asyncio.sleep(0.004)
    await _perimeter_critical(rig)
    await db._write_queue.join()
    perim = [r for r in _rows(db) if r["coordinator_id"] == "perimeter"]
    assert perim, "perimeter must still be delivered (rows written)"
    assert all(r["acknowledged"] == 1 for r in perim)
    smoke = [r for r in _rows(db) if r["hazard_type"] == "smoke"]
    assert smoke and all(r["acknowledged"] == 0 for r in smoke)

    # A newer unrelated unacked CRITICAL row (written outside the slot) is
    # what the legacy "newest unacked" cooldown lookup would wrongly stamp.
    clock.advance(1)
    await db.log_notification(
        coordinator_id="energy", severity="CRITICAL", title="Reserve",
        message="reserve low", hazard_type="reserve_soc", delivered=1,
    )
    await db._write_queue.join()

    await rig.nm.async_acknowledge()
    await _drain(db)
    stamped = [r for r in _rows(db) if r["cooldown_expires"]]
    assert len(stamped) == 1
    assert stamped[0]["hazard_type"] == "smoke"
    assert stamped[0]["acknowledged"] == 1


async def _two_rows(db, clock, first, second):
    for coord, hz in (first, second):
        await db.log_notification(
            coordinator_id=coord, severity="CRITICAL", title=hz,
            message=f"{hz} msg", hazard_type=hz, location="L", delivered=1,
        )
        await asyncio.sleep(0.004)
        clock.advance(1)
    await db._write_queue.join()


@pytest.mark.asyncio
async def test_restart_recovery_prefers_older_life_safety_row(
    monkeypatch, clock, tmp_path
):
    from test_imsg_audit_fix_1 import _drain
    db = await _real_db(tmp_path)
    await _two_rows(db, clock, ("safety", "smoke"), ("perimeter", "exterior_person"))
    rig = Rig(monkeypatch, clock)
    rig.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    await rig.nm._recover_state_from_db()
    await _drain(db)
    assert rig.nm.alert_state == AlertState.REPEATING
    assert rig.nm._active_alert_data["hazard_type"] == "smoke"
    assert rig.nm._active_alert_data["coordinator_id"] == "safety"


@pytest.mark.asyncio
async def test_restart_recovery_stale_life_safety_does_not_displace_fresh_row(
    monkeypatch, clock, tmp_path
):
    """Re-review D: a 30 h-old unacked smoke row (beyond the 24 h recovery
    bound) must not be swapped in — the fresh perimeter alert is recovered."""
    from test_imsg_audit_fix_1 import _drain
    db = await _real_db(tmp_path)
    await db.log_notification(
        coordinator_id="safety", severity="CRITICAL", title="Smoke",
        message="old smoke", hazard_type="smoke", location="Garage",
        delivered=1,
    )
    await db._write_queue.join()
    clock.advance(30 * 3600)
    await db.log_notification(
        coordinator_id="perimeter", severity="CRITICAL", title="Person",
        message="person at gate", hazard_type="exterior_person",
        location="Side Gate", delivered=1,
    )
    await db._write_queue.join()
    clock.advance(60)
    rig = Rig(monkeypatch, clock)
    rig.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    await rig.nm._recover_state_from_db()
    await _drain(db)
    assert rig.nm.alert_state == AlertState.REPEATING
    assert rig.nm._active_alert_data["hazard_type"] == "exterior_person"


@pytest.mark.asyncio
async def test_restart_recovery_newest_row_when_no_life_safety(
    monkeypatch, clock, tmp_path
):
    from test_imsg_audit_fix_1 import _drain
    db = await _real_db(tmp_path)
    await _two_rows(db, clock, ("energy", "reserve_soc"), ("perimeter", "exterior_person"))
    rig = Rig(monkeypatch, clock)
    rig.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    await rig.nm._recover_state_from_db()
    await _drain(db)
    assert rig.nm._active_alert_data["hazard_type"] == "exterior_person"


@pytest.mark.asyncio
async def test_inbound_log_links_slot_row_not_newest(monkeypatch, clock):
    rig = Rig(monkeypatch, clock)
    rig.nm._active_alert_data = {"coordinator_id": "safety", "hazard_type": "smoke"}
    rig.db.get_active_criticals = AsyncMock(return_value=[
        {"id": 9, "coordinator_id": "perimeter", "hazard_type": "exterior_person"},
        {"id": 4, "coordinator_id": "safety", "hazard_type": "smoke"},
    ])
    rig.db.get_active_critical = AsyncMock(return_value={"id": 9})
    await rig.nm._log_and_reply(rig.db, None, "pushover", "ok", "ack", "r", True)
    assert rig.db.log_inbound.await_args.args[5] == 4


@pytest.mark.asyncio
async def test_ack_without_slot_data_uses_untargeted_ack(monkeypatch, clock):
    rig = await _urgent_smoke_rig(monkeypatch, clock)
    rig.nm._active_alert_data = {}
    await rig.nm.async_acknowledge()
    rig.db.acknowledge_notification.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_db_targeted_ack_null_hazard_row(tmp_path):
    from test_imsg_audit_fix_1 import _drain
    db = await _real_db(tmp_path)
    rid = await db.log_notification(
        coordinator_id="energy", severity="CRITICAL", title="X",
        message="x", hazard_type=None, delivered=1,
    )
    got = await db.acknowledge_notification(coordinator_id="energy", hazard_type=None)
    await _drain(db)
    assert got == rid
    assert {r["id"]: r["acknowledged"] for r in _rows(db)}[rid] == 1


@pytest.mark.asyncio
async def test_db_targeted_ack_discriminates_hazard_same_coordinator(tmp_path):
    from test_imsg_audit_fix_1 import _drain
    db = await _real_db(tmp_path)
    smoke_id = await db.log_notification(
        coordinator_id="safety", severity="CRITICAL", title="Smoke",
        message="s", hazard_type="smoke", delivered=1,
    )
    await asyncio.sleep(0.004)
    leak_id = await db.log_notification(
        coordinator_id="safety", severity="CRITICAL", title="Leak",
        message="l", hazard_type="water_leak", delivered=1,
    )
    await db.acknowledge_notification(coordinator_id="safety", hazard_type="smoke")
    await _drain(db)
    acked = {r["id"]: r["acknowledged"] for r in _rows(db)}
    assert acked[smoke_id] == 1
    assert acked[leak_id] == 0


@pytest.mark.asyncio
async def test_ack_clears_all_channel_rows_and_recovery_restores_nothing(
    monkeypatch, clock, tmp_path
):
    from test_imsg_audit_fix_1 import _drain
    db = await _real_db(tmp_path)
    for ch in ("tts", "pushover", "whatsapp"):
        await db.log_notification(
            "safety", "CRITICAL", "Smoke", "smoke in garage",
            "smoke", "Garage", None, ch, 1,
        )
    await db._write_queue.join()
    rig = Rig(monkeypatch, clock)
    rig.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    await rig.nm._enter_alerting(
        "safety", "CRITICAL", "Smoke", "smoke in garage", "smoke", "Garage"
    )
    await rig.nm.async_acknowledge()
    await db._write_queue.join()
    rows = _rows(db)
    assert len(rows) == 3
    assert all(r["acknowledged"] == 1 for r in rows)
    assert sum(1 for r in rows if r["cooldown_expires"]) == 1

    # Restart: a fresh NM must not resurrect the smoke alert as REPEATING.
    rig2 = Rig(monkeypatch, clock)
    rig2.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    await rig2.nm._recover_state_from_db()
    await _drain(db)
    assert rig2.nm.alert_state != AlertState.REPEATING


@pytest.mark.asyncio
async def test_one_ack_clears_every_unacked_critical_across_coordinators(
    monkeypatch, clock, tmp_path
):
    """NM-ACK-CLEARS-ALL: smoke (life-safety, in slot) + energy envoy
    CRITICAL + perimeter CRITICAL, all unacked -> ONE ack -> zero unacked
    CRITICAL rows, and restart recovery finds nothing to re-raise."""
    from test_imsg_audit_fix_1 import _drain
    db = await _real_db(tmp_path)
    for coord, hz, loc in (
        ("energy", "envoy_write_verification", None),
        ("perimeter", "exterior_person", "Side Gate"),
        ("perimeter", "exterior_person", "Driveway"),
    ):
        await db.log_notification(
            coord, "CRITICAL", hz, f"{hz} msg", hz, loc, None, "pushover", 1,
        )
    await db._write_queue.join()
    rig = Rig(monkeypatch, clock)
    rig.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    released = []
    monkeypatch.setattr(rig.nm, "_panel_release_id", released.append)
    await rig.nm._enter_alerting(
        "safety", "CRITICAL", "Smoke", "smoke in garage", "smoke", "Garage"
    )
    await db.log_notification(
        "safety", "CRITICAL", "Smoke", "smoke in garage", "smoke", "Garage",
        None, "tts", 1,
    )
    await db._write_queue.join()
    assert sum(1 for r in _rows(db) if r["acknowledged"] == 0) == 4

    await rig.nm.async_acknowledge()
    await db._write_queue.join()
    assert [r for r in _rows(db) if r["acknowledged"] == 0] == []
    assert await db.get_active_criticals() == []
    # Every acked episode's panel lease released (slot + 3 backlog episodes).
    assert set(released) >= {
        "ura:energy:envoy_write_verification:house",
        "ura:perimeter:exterior_person:side_gate",
        "ura:perimeter:exterior_person:driveway",
    }

    rig2 = Rig(monkeypatch, clock)
    rig2.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    await rig2.nm._recover_state_from_db()
    await _drain(db)
    assert rig2.nm.alert_state != AlertState.REPEATING
    assert rig2.nm.alert_state != AlertState.ALERTING


@pytest.mark.asyncio
async def test_idle_ack_clears_leftover_criticals_without_touching_slot(
    monkeypatch, clock, tmp_path
):
    """NM idle + 2 leftover unacked CRITICALs -> ack -> zero unacked, leases
    released, state stays IDLE (no slot re-entry)."""
    db = await _real_db(tmp_path)
    for coord, hz, loc in (
        ("energy", "envoy_write_verification", None),
        ("perimeter", "exterior_person", "Side Gate"),
    ):
        await db.log_notification(
            coord, "CRITICAL", hz, f"{hz} msg", hz, loc, None, "pushover", 1,
        )
    await db._write_queue.join()
    rig = Rig(monkeypatch, clock)
    rig.nm.hass.data[nm_mod.DOMAIN]["database"] = db
    released = []
    monkeypatch.setattr(rig.nm, "_panel_release_id", released.append)
    assert rig.nm.alert_state == AlertState.IDLE

    await rig.nm.async_acknowledge(acked_by_channel="button")
    await db._write_queue.join()
    assert [r for r in _rows(db) if r["acknowledged"] == 0] == []
    assert sorted(released) == [
        "ura:energy:envoy_write_verification:house",
        "ura:perimeter:exterior_person:side_gate",
    ]
    assert rig.nm.alert_state == AlertState.IDLE
    assert not rig.nm._active_alert_data
    assert not any(r["cooldown_expires"] for r in _rows(db))
    from test_imsg_audit_fix_1 import _drain
    await _drain(db)


def test_helper_holds_in_alerting_state(monkeypatch, clock):
    nm = Rig(monkeypatch, clock).nm
    nm._alert_state = AlertState.ALERTING
    nm._active_alert_data = {"hazard_type": "smoke"}
    assert nm._life_safety_slot_holds_against("exterior_person") is True


def test_helper_false_with_empty_active_data(monkeypatch, clock):
    nm = Rig(monkeypatch, clock).nm
    nm._alert_state = AlertState.REPEATING
    nm._active_alert_data = {}
    assert nm._life_safety_slot_holds_against("exterior_person") is False
    nm._active_alert_data = None
    assert nm._life_safety_slot_holds_against("exterior_person") is False

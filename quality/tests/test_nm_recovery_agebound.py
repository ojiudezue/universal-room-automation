"""NM-RECOVERY-AGEBOUND-1 (2026-08-14) — boot recovery freshness bound.

Boot recovery in `_recover_state_from_db` walks `get_active_critical`
newest-first with no freshness bound. After the twin-eaten incident 326
historical unacked CRITICAL rows sat in the notification_log; on the
next restart NM would resurrect the newest of them as a live REPEATING
alert regardless of how many hours or days had passed since the event.

Invariant (falsifiable): an unacked CRITICAL row whose insert timestamp
is older than NM_RECOVERY_MAX_AGE_H must NOT arm REPEATING on recovery.
Kill switch: NM_RECOVERY_MAX_AGE_H = 0 restores unbounded pre-fix
behavior.

Wire-in anchor: the bound lives at the recovery caller (not the DAO)
because `get_active_critical` has other legitimate unbounded callers.
Neutering the age comparison must make named tests red — see the drill
report attached to the cycle.
"""

import asyncio
from datetime import timedelta, timezone
from unittest.mock import MagicMock, AsyncMock

# Bootstrap HA stubs by importing the sibling NM test module first.
from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.domain_coordinators import (
    notification_manager as nm_mod,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
    AlertState,
)
from homeassistant.util import dt as dt_util


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mock_db(active_row):
    db = MagicMock()
    db.get_active_critical = AsyncMock(return_value=active_row)
    db.get_active_cooldown = AsyncMock(return_value=None)
    db.get_last_notification = AsyncMock(return_value=None)
    db.get_notifications_today = AsyncMock(return_value=[])
    return db


def _row(age_hours):
    ts = (dt_util.utcnow() - timedelta(hours=age_hours)).isoformat()
    return {
        "coordinator_id": "safety",
        "title": "Smoke",
        "message": "Alarm",
        "hazard_type": "smoke",
        "location": "kitchen",
        "timestamp": ts,
    }


class TestRecoveryAgeBound:
    """Freshness bound on _recover_state_from_db."""

    def test_stale_unacked_critical_is_skipped(self, caplog):
        """25h-old unacked CRITICAL must NOT arm REPEATING."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        hass.data["universal_room_automation"] = {"database": _mock_db(_row(25.0))}
        import logging
        with caplog.at_level(logging.INFO):
            _run(nm._recover_state_from_db())
        assert nm.alert_state == AlertState.IDLE, (
            "stale unacked CRITICAL must be skipped by NM_RECOVERY_MAX_AGE_H"
        )
        # Skip log emitted (INFO).
        assert any(
            "skipping stale unacked CRITICAL" in rec.getMessage()
            for rec in caplog.records
        ), "expected INFO skip log line"

    def test_fresh_unacked_critical_is_recovered(self):
        """1h-old unacked CRITICAL must arm REPEATING (within bound)."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        hass.data["universal_room_automation"] = {"database": _mock_db(_row(1.0))}
        _run(nm._recover_state_from_db())
        assert nm.alert_state == AlertState.REPEATING

    def test_kill_switch_zero_recovers_ancient_row(self, monkeypatch):
        """NM_RECOVERY_MAX_AGE_H = 0 disables the bound (kill switch)."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        hass.data["universal_room_automation"] = {"database": _mock_db(_row(500.0))}
        monkeypatch.setattr(nm_mod, "NM_RECOVERY_MAX_AGE_H", 0.0)
        _run(nm._recover_state_from_db())
        assert nm.alert_state == AlertState.REPEATING, (
            "kill switch (0) must restore unbounded recovery"
        )

    def test_zombie_repeating_reset_to_idle_after_recovery_skip(self):
        """MED-1 fix-up: pre-fix boot persisted alert_state=repeating,
        this boot skipped the stale row -> _active_alert_data is None.
        restore_persistence_state must reset REPEATING -> IDLE so
        dashboards don't show a zombie repeating with empty alert.
        """
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        # Step 1: recovery skips the stale row.
        hass.data["universal_room_automation"] = {"database": _mock_db(_row(50.0))}
        _run(nm._recover_state_from_db())
        assert nm.alert_state == AlertState.IDLE
        assert nm._active_alert_data is None
        # Step 2: sensor restores the pre-fix persisted attrs (REPEATING).
        nm.restore_persistence_state({"alert_state": "repeating"})
        assert nm.alert_state == AlertState.IDLE, (
            "zombie REPEATING must be reset to IDLE when no active alert data"
        )

    def test_missing_timestamp_recovers_as_fresh(self):
        """Row without timestamp cannot be aged — recover (backward compat)."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        row = _row(1.0)
        row.pop("timestamp")
        hass.data["universal_room_automation"] = {"database": _mock_db(row)}
        _run(nm._recover_state_from_db())
        assert nm.alert_state == AlertState.REPEATING

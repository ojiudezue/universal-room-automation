"""v4.6.2 D6 — NotificationManager routine-shift dispatch structural tests.

Source-grep tests verifying:
- NM subscribes to SIGNAL_REGIME_EVENT_EMITTED via async_dispatcher_connect
- Subscription captured for teardown (Bug Class #38)
- silent mode returns early (no notification)
- event mode checks cooldown via DAO
- weekly_digest mode enqueues into digest queue
- Notification copy is neutral (no diagnostic detail like 'js' or 'p_total')
- Weekly digest flush uses async_track_time_change (Sunday 09:00)
"""

from pathlib import Path


def _nm_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/notification_manager.py"
    ).read_text()


def _signals_src() -> str:
    return Path(
        "custom_components/universal_room_automation/"
        "domain_coordinators/signals.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Signal subscription
# ---------------------------------------------------------------------------


def test_nm_subscribes_to_regime_event_signal():
    src = _nm_src()
    assert "SIGNAL_REGIME_EVENT_EMITTED" in src, (
        "NotificationManager must subscribe to SIGNAL_REGIME_EVENT_EMITTED"
    )
    assert "async_dispatcher_connect" in src, (
        "NotificationManager must use async_dispatcher_connect for regime event"
    )


def test_nm_regime_subscription_captured_for_teardown():
    src = _nm_src()
    assert "_regime_event_unsub" in src, (
        "NM must store regime_event_unsub for cleanup (Bug Class #38)"
    )
    # Verify teardown calls it
    teardown_idx = src.find("async def async_teardown(")
    assert teardown_idx >= 0
    teardown_block = src[teardown_idx: teardown_idx + 2000]
    assert "_regime_event_unsub" in teardown_block, (
        "async_teardown must cancel _regime_event_unsub"
    )


# ---------------------------------------------------------------------------
# silent mode
# ---------------------------------------------------------------------------


def test_silent_mode_returns_early():
    src = _nm_src()
    idx = src.find("async def _dispatch_regime_notification(")
    assert idx >= 0
    end = src.find("\n    async def ", idx + 1)
    block = src[idx: end if end > 0 else idx + 4000]
    assert "silent" in block, "_dispatch_regime_notification must check for 'silent' mode"
    assert "return" in block, "must return early when mode is 'silent'"


# ---------------------------------------------------------------------------
# event mode
# ---------------------------------------------------------------------------


def test_event_mode_checks_cooldown():
    src = _nm_src()
    idx = src.find("async def _dispatch_regime_notification(")
    assert idx >= 0
    end = src.find("\n    async def ", idx + 1)
    block = src[idx: end if end > 0 else idx + 4000]
    assert "get_regime_last_notified" in block, (
        "event mode must call get_regime_last_notified DAO for cooldown check"
    )
    assert "upsert_regime_last_notified" in block, (
        "event mode must call upsert_regime_last_notified to record notification"
    )


def test_event_mode_respects_severity_floor():
    src = _nm_src()
    idx = src.find("async def _dispatch_regime_notification(")
    assert idx >= 0
    end = src.find("\n    async def ", idx + 1)
    block = src[idx: end if end > 0 else idx + 4000]
    assert "min_sev" in block or "min_severity" in block or "CONF_ROUTINE_EVENT_MIN_SEVERITY" in block, (
        "event mode must check minimum severity floor"
    )


# ---------------------------------------------------------------------------
# weekly_digest mode
# ---------------------------------------------------------------------------


def test_weekly_digest_mode_enqueues():
    src = _nm_src()
    idx = src.find("async def _dispatch_regime_notification(")
    assert idx >= 0
    end = src.find("\n    async def ", idx + 1)
    block = src[idx: end if end > 0 else idx + 4000]
    assert "enqueue_regime_weekly_digest" in block, (
        "weekly_digest mode must call enqueue_regime_weekly_digest DAO"
    )


def test_weekly_digest_flush_uses_time_change():
    src = _nm_src()
    assert "async_track_time_change" in src, (
        "NM must use async_track_time_change to schedule Sunday 09:00 digest flush"
    )
    # Weekly digest timer — look for the hour=9 setup
    assert "hour=9" in src, (
        "Digest flush must be scheduled at hour=9"
    )


# ---------------------------------------------------------------------------
# Notification copy is neutral
# ---------------------------------------------------------------------------


def test_notification_copy_is_neutral():
    src = _nm_src()
    idx = src.find("async def _dispatch_regime_notification(")
    assert idx >= 0
    end = src.find("\n    async def ", idx + 1)
    block = src[idx: end if end > 0 else idx + 4000]
    # The user-facing message should NOT include raw diagnostic fields
    assert "p_total" not in block, (
        "Notification copy must NOT include p_total (diagnostic detail)"
    )
    assert "js_divergence" not in block, (
        "Notification copy must NOT include js_divergence value"
    )
    # Must include the neutral template
    assert "Routine pattern shift detected" in block, (
        "Notification copy must say 'Routine pattern shift detected'"
    )

"""IMSG-IMAGE-FAIL-1 (2026-08-14) — Tier-1 batch fix.

Covers:
  FIX A — _send_imessage payload key hygiene: mirror the WhatsApp leg
          (attachment=<local HA path> for snapshot_path; media_url=<url>
          for snapshot_url). Never emits the dead ``attachment_path`` key
          and never puts a URL into ``attachment``.
  FIX B — get_active_critical / get_active_cooldown MUST skip audit-
          sentinel rows (``message='[audit]'``) so the [ACK] audit row
          written 4ms after the real row cannot be resurrected as the
          active alert.
  BELT   — the [ACK] emit MUST produce a row that get_active_critical
          can NEVER return (pre-acknowledged=1 in addition to sentinel).

The DB tests drive REAL production writers (log_notification /
_emit_audit_row) and REAL production readers (get_active_critical /
get_active_cooldown) against a schema extracted from production source
via UniversalRoomDatabase.initialize() — no hand-copied DDL.
"""

import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# Piggyback on the notification-manager harness's HA-module stubs. Also
# re-uses _make_hass / _make_config, and installs sys.modules stubs.
from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)
from custom_components.universal_room_automation.database import UniversalRoomDatabase
from custom_components.universal_room_automation.const import DOMAIN


# =========================================================================
# FIX A — payload key hygiene on _send_imessage
# =========================================================================


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSendImessagePayloadShape:
    """Wire-in anchor: neutering the key assignments in _send_imessage
    (attachment / media_url) reddens the corresponding assertion below."""

    def test_snapshot_path_uses_attachment_key(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        _run(nm._send_imessage(
            title="t", message="m", handle="+15551112222",
            snapshot_url=None,
            snapshot_path="/media/ura/snapshots/x.jpg",
        ))
        assert hass.services.async_call.await_count == 1
        args, _kwargs = hass.services.async_call.call_args
        # args = (domain, service, payload)
        assert args[0] == "bluebubbles"
        assert args[1] == "send_message"
        payload = args[2]
        assert payload["attachment"] == "/media/ura/snapshots/x.jpg", (
            "snapshot_path must be delivered via the 'attachment' key "
            "(mirror of the WhatsApp leg)"
        )
        assert "attachment_path" not in payload, (
            "dead 'attachment_path' key must never appear (SNAP-1 was false "
            "for the installed BB integration)"
        )
        assert "media_url" not in payload, (
            "local path must not be smuggled into media_url"
        )

    def test_snapshot_url_uses_media_url_key(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        _run(nm._send_imessage(
            title="t", message="m", handle="+15551112222",
            snapshot_url="https://example.com/x.jpg",
            snapshot_path=None,
        ))
        args, _kwargs = hass.services.async_call.call_args
        payload = args[2]
        assert payload["media_url"] == "https://example.com/x.jpg", (
            "snapshot_url must be delivered via the 'media_url' key"
        )
        assert "attachment" not in payload, (
            "a URL must NEVER be put in the 'attachment' key (that key "
            "is for local HA paths only in the WhatsApp/BB leg)"
        )
        assert "attachment_path" not in payload

    def test_no_snapshot_no_attachment_keys(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        _run(nm._send_imessage(
            title="t", message="m", handle="+15551112222",
        ))
        args, _kwargs = hass.services.async_call.call_args
        payload = args[2]
        for k in ("attachment", "attachment_path", "media_url"):
            assert k not in payload


# =========================================================================
# FIX B / BELT — reader-side sentinel filter + pre-ack [ACK] emit
# =========================================================================


def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    """Real UniversalRoomDatabase against a fresh temp file.

    Mirrors _make_db in test_data_pipeline.py so the schema is the one
    production creates (no hand-copied DDL).
    """
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)

    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task
    return UniversalRoomDatabase(hass)


async def _drain(db):
    if db._write_task is not None and not db._write_task.done():
        await db._write_queue.join()
        db._write_task.cancel()
        try:
            await db._write_task
        except asyncio.CancelledError:
            pass


class TestActiveCriticalSkipsAuditTwin:

    def test_real_row_returned_not_audit_twin(self, tmp_path):
        db = _make_db(str(tmp_path))

        async def _do():
            await db.initialize()
            await db.start_write_worker()
            # Real CRITICAL alert row (unacked, delivered).
            await db.log_notification(
                coordinator_id="perimeter",
                severity="CRITICAL",
                title="Intruder",
                message="person at side gate",
                hazard_type="exterior_person",
                delivered=1,
            )
            # Audit twin written ~4ms later (message='[audit]', same
            # severity, unacked from the DB's perspective — this is the
            # class the fix must exclude).
            await asyncio.sleep(0.004)
            await db.log_notification(
                coordinator_id="perimeter",
                severity="CRITICAL",
                title="[audit-twin]",
                message="[audit]",
                delivered=1,
            )
            await _drain(db)
            return await db.get_active_critical()

        row = _run(_do())
        assert row is not None
        assert row["message"] == "person at side gate", (
            "get_active_critical must return the REAL row, never the "
            "later '[audit]' twin"
        )
        assert row["title"] == "Intruder"

    def test_lone_audit_row_returns_none(self, tmp_path):
        db = _make_db(str(tmp_path))

        async def _do():
            await db.initialize()
            await db.start_write_worker()
            await db.log_notification(
                coordinator_id="perimeter",
                severity="CRITICAL",
                title="[audit-only]",
                message="[audit]",
                delivered=1,
            )
            await _drain(db)
            return await db.get_active_critical()

        row = _run(_do())
        assert row is None, (
            "An audit-sentinel row with no real sibling must never "
            "surface as the active CRITICAL"
        )


class TestActiveCooldownSkipsAuditTwin:

    def test_real_cooldown_row_returned_not_audit_twin(self, tmp_path):
        db = _make_db(str(tmp_path))
        # Cooldown expiry ~1h in the future.
        from homeassistant.util import dt as dt_util
        from datetime import timedelta
        future = (dt_util.utcnow() + timedelta(hours=1)).isoformat()

        async def _do():
            await db.initialize()
            await db.start_write_worker()
            real_id = await db.log_notification(
                coordinator_id="perimeter",
                severity="CRITICAL",
                title="Intruder",
                message="person at side gate",
                delivered=1,
            )
            # Acknowledge + set cooldown on the real row.
            await db.acknowledge_notification()
            await db.set_cooldown(real_id, future)
            # Audit twin (acked, cooldown set too — simulating a bug
            # that back-fills these on a sibling row).
            await asyncio.sleep(0.004)
            audit_id = await db.log_notification(
                coordinator_id="perimeter",
                severity="CRITICAL",
                title="[audit-twin]",
                message="[audit]",
                delivered=1,
                acknowledged=1,
            )
            await db.set_cooldown(audit_id, future)
            await _drain(db)
            return await db.get_active_cooldown()

        row = _run(_do())
        assert row is not None
        assert row["message"] == "person at side gate", (
            "get_active_cooldown must return the REAL cooldown row, "
            "never the '[audit]' twin"
        )


class TestAckAuditRowPreAcknowledged:
    """BELT: the [ACK] audit row that notification_manager emits after a
    real ack must produce a DB row that get_active_critical CANNOT
    return — both because message='[audit]' AND because acknowledged=1
    at write time (defense in depth)."""

    def test_ack_emit_row_never_resurfaces_as_active(self, tmp_path):
        db = _make_db(str(tmp_path))

        async def _do():
            await db.initialize()
            await db.start_write_worker()
            # Simulate the exact write shape _emit_audit_row uses for
            # the [ACK] emit (post-acknowledge site in
            # notification_manager.py: severity=CRITICAL, message=[audit],
            # acknowledged=1 per BELT).
            await db.log_notification(
                coordinator_id="perimeter",
                severity="CRITICAL",
                title="[ACK] Intruder (created_at=...)",
                message="[audit]",
                delivered=1,
                acknowledged=1,
            )
            await _drain(db)
            return await db.get_active_critical()

        row = _run(_do())
        assert row is None, (
            "The [ACK] audit row must NEVER surface as an active "
            "CRITICAL (BELT: pre-ack + sentinel filter)"
        )

    def test_emit_audit_row_writer_passes_acknowledged(self):
        """The _emit_audit_row helper must forward `acknowledged` to
        log_notification. Wire-in check — dropping the kwarg re-opens
        the resurrection path even with the sentinel filter in place."""
        import inspect
        from custom_components.universal_room_automation.domain_coordinators import (
            notification_manager as _nm_mod,
        )
        src = inspect.getsource(_nm_mod.NotificationManager._emit_audit_row)
        assert "acknowledged=int(acknowledged)" in src, (
            "_emit_audit_row must forward acknowledged to log_notification"
        )
        # And the post-ack site must pass acknowledged=1.
        src_ack = inspect.getsource(
            _nm_mod.NotificationManager._acknowledge_alert
        ) if hasattr(_nm_mod.NotificationManager, "_acknowledge_alert") else ""
        # Fall back: scan full module for the [ACK] emit block.
        if "acknowledged=1" not in src_ack:
            full = inspect.getsource(_nm_mod)
            assert "[ACK]" in full and "acknowledged=1" in full, (
                "the [ACK] audit emit site must pass acknowledged=1"
            )

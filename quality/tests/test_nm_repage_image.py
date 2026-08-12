"""NM-REPAGE-IMG-1 — 5-minute CRITICAL re-page must re-attach the stored
snapshot image on WhatsApp + iMessage (BlueBubbles), with graceful
text-only fallback when the file is gone at re-page time.

Falsifiable invariant:
  For any CRITICAL alert that ORIGINALLY dispatched with a snapshot
  (path or url) and remains unacknowledged, EVERY subsequent re-page
  emit on a media-capable channel MUST carry the same snapshot payload
  when the file still exists at re-page time.

Mutation anchor (WIRE-IN):
  ``notification_manager.py :: _repeat_alert`` — the four transport
  dispatches thread ``snapshot_url=_snap_url, snapshot_path=_snap_path``.
  Neutering the whatsapp/imessage attach expressions makes
  ``test_repage_reattaches_snapshot_on_whatsapp_and_imessage`` fail.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Piggyback on the NM harness (installs HA-module stubs + imports NM/Severity/DOMAIN).
from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.const import (
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_IMESSAGE_ENABLED,
    CONF_NM_IMESSAGE_SEVERITY,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_WHATSAPP_SEVERITY,
    DOMAIN,
    NM_DELIVERY_IMMEDIATE,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity


SNAP_URL = "https://ha.local/api/media_proxy/cam_front.jpg"


def _person():
    return {
        CONF_NM_PERSON_ENTITY: "person.oji",
        CONF_NM_PERSON_PUSHOVER_KEY: "pk_oji",
        CONF_NM_PERSON_COMPANION_SERVICE: "notify.oji_phone",
        CONF_NM_PERSON_WHATSAPP_PHONE: "+15551234",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "user@icloud",
        CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
    }


def _cfg():
    return _make_config(**{
        CONF_NM_PUSHOVER_ENABLED: True,
        CONF_NM_PUSHOVER_SEVERITY: "LOW",
        CONF_NM_COMPANION_ENABLED: True,
        CONF_NM_WHATSAPP_ENABLED: True,
        CONF_NM_WHATSAPP_SEVERITY: "LOW",
        CONF_NM_IMESSAGE_ENABLED: True,
        CONF_NM_IMESSAGE_SEVERITY: "LOW",
        CONF_NM_QUIET_USE_HOUSE_STATE: True,
        CONF_NM_PERSONS: [_person()],
    })


def _put_house_awake(hass):
    cm = MagicMock()
    cm.house_state = "home_day"
    hass.data[DOMAIN]["coordinator_manager"] = cm


def _install_nm(hass, cfg):
    nm = NotificationManager(hass, cfg)
    nm._send_pushover = AsyncMock()
    nm._send_companion = AsyncMock()
    nm._send_whatsapp = AsyncMock()
    nm._send_imessage = AsyncMock()
    nm._send_tts = AsyncMock()
    # LOW-1 fix-up: production off-loads os.path.exists to the executor
    # via hass.async_add_executor_job. Stub returns the real call result
    # so tests exercise the actual fallback branch.
    async def _executor(fn, *args):
        return fn(*args)
    hass.async_add_executor_job = AsyncMock(side_effect=_executor)
    return nm


async def _arm_critical(nm, snap_path, snap_url=None):
    """Drive the original CRITICAL dispatch so _enter_alerting stashes
    snapshot on _active_alert_data."""
    await nm.async_notify(
        "perimeter_alert",
        Severity.CRITICAL,
        "Perimeter Alert — Person",
        "Person on porch",
        hazard_type="exterior_person",
        location="front_yard",
        snapshot_url=snap_url,
        snapshot_path=snap_path,
    )


class TestRepageReattachesImage:

    @pytest.mark.asyncio
    async def test_repage_reattaches_snapshot_on_whatsapp_and_imessage(self, tmp_path):
        """WIRE-IN ANCHOR: the re-page emit on WhatsApp and iMessage MUST
        thread the stored snapshot path. If the four snapshot kwargs on
        the four dispatches in `_repeat_alert` are neutered (e.g.
        `snapshot_path=None`), this test goes red.
        """
        snap = tmp_path / "cam_front.jpg"
        snap.write_bytes(b"\xff\xd8\xff")  # minimal JPEG magic — file exists
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg())

        await _arm_critical(nm, str(snap), snap_url=SNAP_URL)

        # Original dispatch attached — sanity.
        assert nm._send_whatsapp.await_args.kwargs.get("snapshot_path") == str(snap)
        assert nm._send_imessage.await_args.kwargs.get("snapshot_path") == str(snap)

        # Reset call history and fire the re-page.
        nm._send_whatsapp.reset_mock()
        nm._send_imessage.reset_mock()
        nm._send_pushover.reset_mock()
        nm._send_companion.reset_mock()

        await nm._repeat_alert()

        # Re-page must have fired on WA + iMessage with the SAME snapshot.
        nm._send_whatsapp.assert_awaited()
        nm._send_imessage.assert_awaited()
        wa_kwargs = nm._send_whatsapp.await_args.kwargs
        im_kwargs = nm._send_imessage.await_args.kwargs
        assert wa_kwargs.get("snapshot_path") == str(snap), (
            "WA re-page dropped snapshot_path — WIRE-IN broken"
        )
        assert wa_kwargs.get("snapshot_url") == SNAP_URL
        assert im_kwargs.get("snapshot_path") == str(snap), (
            "iMessage re-page dropped snapshot_path — WIRE-IN broken"
        )
        assert im_kwargs.get("snapshot_url") == SNAP_URL

    @pytest.mark.asyncio
    async def test_repage_falls_back_to_text_only_when_file_gone(self, tmp_path):
        """If the stored snapshot file no longer exists at re-page time,
        `snapshot_path` MUST be dropped (fallback to text-only or
        URL-only). Must not crash, must not block the re-page."""
        snap = tmp_path / "cam_front.jpg"
        snap.write_bytes(b"\xff\xd8\xff")
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg())

        await _arm_critical(nm, str(snap), snap_url=None)

        # Delete the file BEFORE re-page — simulates snapshot cleanup.
        os.unlink(str(snap))

        nm._send_whatsapp.reset_mock()
        nm._send_imessage.reset_mock()

        # Must not raise.
        await nm._repeat_alert()

        nm._send_whatsapp.assert_awaited()
        nm._send_imessage.assert_awaited()
        assert nm._send_whatsapp.await_args.kwargs.get("snapshot_path") is None, (
            "WA re-page kept stale snapshot_path pointing at deleted file"
        )
        assert nm._send_imessage.await_args.kwargs.get("snapshot_path") is None, (
            "iMessage re-page kept stale snapshot_path pointing at deleted file"
        )
        # No URL either → both are None (text-only fallback).
        assert nm._send_whatsapp.await_args.kwargs.get("snapshot_url") is None
        assert nm._send_imessage.await_args.kwargs.get("snapshot_url") is None

    @pytest.mark.asyncio
    async def test_repage_wire_in_anchor_on_enter_alerting(self, tmp_path):
        """WIRE-IN ANCHOR (enclosing method): `_enter_alerting` must stash
        snapshot_url + snapshot_path on `_active_alert_data`. Neutering
        the two `snapshot_*: ...` keys in the dict literal makes the
        re-page path effectively text-only. This test asserts the state
        directly so mutation of the helper is caught even if the
        transport-side stubs above are also mutated.
        """
        snap = tmp_path / "cam_front.jpg"
        snap.write_bytes(b"\xff\xd8\xff")
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg())

        await _arm_critical(nm, str(snap), snap_url=SNAP_URL)

        assert nm._active_alert_data is not None
        assert nm._active_alert_data.get("snapshot_path") == str(snap)
        assert nm._active_alert_data.get("snapshot_url") == SNAP_URL

        # And the persisted state carries the snapshot so post-restart
        # re-pages still have it.
        persisted = nm.get_persistence_state()
        assert persisted.get("active_alert_snapshot_path") == str(snap)
        assert persisted.get("active_alert_snapshot_url") == SNAP_URL
        # LOW-2 fix-up: identity key is persisted alongside snapshot.
        assert persisted.get("active_alert_snapshot_created_at") == (
            nm._active_alert_data.get("created_at")
        )

    def test_restore_merges_snapshot_when_identity_matches(self):
        """LOW-2 fix-up: post-restart, when the persisted snapshot's
        alert-identity (created_at) matches the DB-recovered alert's
        created_at, the snapshot is merged onto _active_alert_data."""
        hass = _make_hass()
        nm = _install_nm(hass, _cfg())
        # Simulate _recover_state_from_db populating the DB-recovered alert.
        created = "2026-08-12T10:00:00+00:00"
        nm._active_alert_data = {
            "coordinator_id": "perimeter_alert",
            "severity": "CRITICAL",
            "title": "Perimeter Alert",
            "message": "Person",
            "hazard_type": "exterior_person",
            "location": "front_yard",
            "created_at": created,
        }
        nm._alert_state = nm._alert_state  # keep whatever the ctor set
        nm.restore_persistence_state({
            "active_alert_snapshot_url": SNAP_URL,
            "active_alert_snapshot_path": "/media/ura/snapshots/cam_front.jpg",
            "active_alert_snapshot_created_at": created,
        })
        assert nm._active_alert_data.get("snapshot_url") == SNAP_URL
        assert nm._active_alert_data.get("snapshot_path") == (
            "/media/ura/snapshots/cam_front.jpg"
        )

    def test_restore_does_not_merge_snapshot_on_identity_mismatch(self):
        """LOW-2 fix-up: cross-episode bleed guard — a stale snapshot
        whose identity does not match the DB-recovered alert MUST NOT
        graft onto _active_alert_data. Legacy blob without identity
        also does NOT merge (safe default)."""
        hass = _make_hass()
        nm = _install_nm(hass, _cfg())
        nm._active_alert_data = {
            "coordinator_id": "perimeter_alert",
            "severity": "CRITICAL",
            "title": "Perimeter Alert B",
            "message": "Person",
            "hazard_type": "exterior_person",
            "location": "front_yard",
            "created_at": "2026-08-12T11:00:00+00:00",  # alert B
        }
        # Mismatch: persisted snapshot belongs to acked alert A.
        nm.restore_persistence_state({
            "active_alert_snapshot_url": SNAP_URL,
            "active_alert_snapshot_path": "/media/ura/snapshots/A.jpg",
            "active_alert_snapshot_created_at": "2026-08-12T10:00:00+00:00",
        })
        assert nm._active_alert_data.get("snapshot_url") is None
        assert nm._active_alert_data.get("snapshot_path") is None

        # Legacy blob (no identity field) — also refuse to merge.
        nm._active_alert_data = {
            "coordinator_id": "perimeter_alert",
            "severity": "CRITICAL",
            "title": "Perimeter Alert C",
            "message": "Person",
            "hazard_type": "exterior_person",
            "location": "front_yard",
            "created_at": "2026-08-12T12:00:00+00:00",
        }
        nm.restore_persistence_state({
            "active_alert_snapshot_url": SNAP_URL,
            "active_alert_snapshot_path": "/media/ura/snapshots/legacy.jpg",
            # no active_alert_snapshot_created_at
        })
        assert nm._active_alert_data.get("snapshot_url") is None
        assert nm._active_alert_data.get("snapshot_path") is None

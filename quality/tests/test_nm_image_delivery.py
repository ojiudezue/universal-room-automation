"""NM-IMAGE-1 (2026-08-11) — security-image force-immediate + audit-sentinel
reader-side filter.

Plan: docs/planning/PLANNING_nm_image_delivery.md (rev-2)

Falsifiable invariants:

  INV-1 (primary): For every exterior security-class alert
    (`hazard_type in NM_SECURITY_HAZARDS`) with a truthy snapshot that
    survives NM's pre-existing suppressions (kill switch, disabled,
    silence-until, dedup, boot-settle, memory-conditioning) — the alert
    is delivered on the IMMEDIATE branch on every router-selected
    media-capable channel and is NEVER dropped by the global
    quiet-hours early-return.

  INV-2 (audit hygiene): No `notification_log` row with
    `message='[audit]'` is ever rendered into a delivered digest body.

Mutation anchors (each test names the load-bearing production line):
  - Site A (early-return OR): notification_manager.py :1276 (the
    `and not _force_immediate_for_security_image` clause).
  - Site B (per-person override): notification_manager.py :1512 (the
    `or _force_immediate_for_security_image` clause).
  - D3 sentinel filter (SELECT): database.py :3888
    (`AND message != '[audit]'`).
  - D3 sentinel filter (formatter): notification_manager.py :4319
    (`if item.get("message") == "[audit]": continue`).
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Piggyback on the NM harness's HA-module stubs (installs sys.modules stubs
# + imports NotificationManager, Severity, DOMAIN, etc.).
from test_notification_manager import _make_hass, _make_config  # noqa: F401

# Order-hardening: force real dt_util bindings after harness import (same
# guard as test_nm_cycle_c_routing_matrix.py — a MagicMock'd
# `homeassistant.util.dt` would break `datetime.utcnow() < ...`).
import sys as _sys
from datetime import datetime as _datetime
_dt_util_mod = _sys.modules.get("homeassistant.util.dt")
if _dt_util_mod is not None:
    _dt_util_mod.utcnow = _datetime.utcnow
    _dt_util_mod.now = _datetime.now
    _dt_util_mod.as_local = lambda dt: dt

from custom_components.universal_room_automation.const import (
    CONF_NM_ENABLED,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_COMPANION_SEVERITY,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_WHATSAPP_SEVERITY,
    CONF_NM_IMESSAGE_ENABLED,
    CONF_NM_IMESSAGE_SEVERITY,
    CONF_NM_TTS_ENABLED,
    CONF_NM_LIGHTS_ENABLED,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    CONF_NM_QUIET_MANUAL_START,
    CONF_NM_QUIET_MANUAL_END,
    DOMAIN,
    NM_DELIVERY_IMMEDIATE,
    NM_DELIVERY_DIGEST,
    NM_HAZARD_EXTERIOR_PERSON,
    NM_HAZARD_EXTERIOR_VEHICLE,
    NM_SECURITY_HAZARDS,
    NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE,
    NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE,
)
import custom_components.universal_room_automation.domain_coordinators.notification_manager as _nm_mod
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity


SNAP = "/media/ura/snapshots/cam_front.jpg"


# =========================================================================
# D1 — constants: shape + monkeypatch surface
# =========================================================================


class TestD1Constants:
    """Constants exist, have expected shape, and are patchable at the
    notification_manager MODULE binding (rev-2 MED-3).
    """

    def test_nm_security_hazards_constant_shape(self):
        # Shape: frozenset of the two exterior hazard strings.
        assert isinstance(NM_SECURITY_HAZARDS, frozenset)
        assert NM_SECURITY_HAZARDS == frozenset({
            "exterior_person", "exterior_vehicle",
        })
        # And the string constants match the security set.
        assert NM_HAZARD_EXTERIOR_PERSON in NM_SECURITY_HAZARDS
        assert NM_HAZARD_EXTERIOR_VEHICLE in NM_SECURITY_HAZARDS
        # Immutable (frozenset has no `add`).
        assert not hasattr(NM_SECURITY_HAZARDS, "add")

    def test_module_binding_is_patchable(self):
        # rev-2 MED-3: monkeypatch target for the disable-override test is
        # the MODULE binding, not `const`. Patching const would leave the
        # imported reference in notification_manager stale.
        assert hasattr(_nm_mod, "NM_SECURITY_HAZARDS")
        with patch.object(_nm_mod, "NM_SECURITY_HAZARDS", frozenset()):
            assert _nm_mod.NM_SECURITY_HAZARDS == frozenset()
        # Restored after context.
        assert _nm_mod.NM_SECURITY_HAZARDS == NM_SECURITY_HAZARDS

    def test_nm_route_reason_constants_are_strings(self):
        assert isinstance(NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE, str)
        assert isinstance(NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE, str)
        assert (
            NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE
            == "force_immediate_security_image"
        )
        assert (
            NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE
            == "dnd_suppressed_security_image"
        )


# =========================================================================
# D2 — force-immediate override at BOTH sites (predicate + edge cases)
# =========================================================================


def _digest_person(pid="person.oji"):
    return {
        CONF_NM_PERSON_ENTITY: pid,
        CONF_NM_PERSON_PUSHOVER_KEY: "pk_oji",
        CONF_NM_PERSON_COMPANION_SERVICE: "notify.oji_phone",
        CONF_NM_PERSON_WHATSAPP_PHONE: "+15551234",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "user@icloud",
        CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_DIGEST,
    }


def _immediate_person(pid="person.oji"):
    p = _digest_person(pid)
    p[CONF_NM_PERSON_DELIVERY_PREF] = NM_DELIVERY_IMMEDIATE
    return p


def _cfg_all_channels(persons=None, **overrides):
    cfg = _make_config(**{
        CONF_NM_PUSHOVER_ENABLED: True,
        CONF_NM_PUSHOVER_SEVERITY: "LOW",
        CONF_NM_COMPANION_ENABLED: True,
        CONF_NM_COMPANION_SEVERITY: "LOW",
        CONF_NM_WHATSAPP_ENABLED: True,
        CONF_NM_WHATSAPP_SEVERITY: "LOW",
        CONF_NM_IMESSAGE_ENABLED: True,
        CONF_NM_IMESSAGE_SEVERITY: "LOW",
        CONF_NM_TTS_ENABLED: False,
        CONF_NM_LIGHTS_ENABLED: False,
        CONF_NM_QUIET_USE_HOUSE_STATE: True,
        CONF_NM_PERSONS: persons or [_digest_person()],
    })
    cfg.update(overrides)
    return cfg


def _install_db(hass):
    db = MagicMock()
    db.log_notification = AsyncMock()
    hass.data[DOMAIN]["database"] = db
    return db


def _install_nm(hass, cfg):
    """Instantiate NM + stub every transport so tests can assert on calls."""
    nm = NotificationManager(hass, cfg)
    nm._send_pushover = AsyncMock()
    nm._send_companion = AsyncMock()
    nm._send_whatsapp = AsyncMock()
    nm._send_imessage = AsyncMock()
    return nm


def _put_house_awake(hass):
    """home_day = not in quiet hours (see TestQuietHours in the base file)."""
    cm = MagicMock()
    cm.house_state = "home_day"
    hass.data[DOMAIN]["coordinator_manager"] = cm


def _put_house_asleep(hass):
    """sleep = quiet hours."""
    cm = MagicMock()
    cm.house_state = "sleep"
    hass.data[DOMAIN]["coordinator_manager"] = cm


class TestD2ForceImmediateOverride:

    @pytest.mark.asyncio
    async def test_security_image_forces_immediate_over_digest(self):
        """MEDIUM exterior_person + snapshot + digest-pref recipient →
        IMMEDIATE transports fire with attachment threaded.

        Mutation anchor: remove `or _force_immediate_for_security_image`
        from the effective_pref override (Site B, notification_manager.py
        :~1512) → this test fails (digest queue row instead of send).
        """
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        _install_db(hass)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )

        nm._send_pushover.assert_awaited()
        nm._send_companion.assert_awaited()
        nm._send_whatsapp.assert_awaited()
        # Attachment threaded to each media-capable send.
        for call in nm._send_pushover.await_args_list:
            assert call.kwargs.get("snapshot_path") == SNAP
        assert nm._send_whatsapp.await_args.kwargs.get("snapshot_path") == SNAP
        assert nm._send_companion.await_args.kwargs.get("snapshot_path") == SNAP

    @pytest.mark.asyncio
    async def test_no_snapshot_no_forced_immediate(self):
        """MEDIUM exterior_person with NO snapshot → falls through to
        recipient's digest pref (predicate False)."""
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        _install_db(hass)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=None,
            snapshot_url=None,
        )
        nm._send_pushover.assert_not_awaited()
        nm._send_companion.assert_not_awaited()
        nm._send_whatsapp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_security_snapshot_no_force(self):
        """hazard NOT in NM_SECURITY_HAZARDS + snapshot → NOT forced
        (predicate False on hazard axis)."""
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        _install_db(hass)

        await nm.async_notify(
            "safety", Severity.MEDIUM,
            "Humidity high", "Bathroom humid",
            hazard_type="indoor_humidity",
            location="bathroom",
            snapshot_path=SNAP,   # would fire if hazard axis mis-evaluated
        )
        nm._send_pushover.assert_not_awaited()
        nm._send_companion.assert_not_awaited()
        nm._send_whatsapp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_string_snapshot_no_force(self):
        """rev-2 MED-4: predicate is truthy (`bool(a or b)`), not
        `is not None`. Empty-string upstream bug must NOT force page."""
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        _install_db(hass)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path="",
            snapshot_url="",
        )
        nm._send_pushover.assert_not_awaited()
        nm._send_whatsapp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_security_image_survives_global_dnd_early_return_with_all_immediate_pref_recipients(self):
        """rev-2 HIGH-1 / L4′ acceptance test — EXACT name required.

        Setup: quiet hours ON, all recipients IMMEDIATE-pref, no
        per-recipient DND-bypass matching MEDIUM, no global bypass.
        Today (without the fix): early-return at :1261-1265 fires →
        per-person loop never runs → attachment lost.
        Post-fix: early-return condition ANDed with
        `not _force_immediate_for_security_image` → control reaches the
        per-person loop → Site B forces immediate → transport fires.

        Mutation anchor: remove `and not _force_immediate_for_security_image`
        from the early-return condition (Site A) → this test fails
        (transports never awaited).
        """
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
        )
        hass = _make_hass()
        _put_house_asleep(hass)  # quiet hours
        # ALL recipients IMMEDIATE-pref, NO bypass matching MEDIUM
        # (empty bypass set). Without Site A fix, the global early-return
        # would fire because none of the three original escape clauses
        # (global_bypass, any_recipient_bypass, any_digest_recipient)
        # hold — control never reaches the per-person loop and even the
        # per-recipient DND-suppression audit row (L9) never gets
        # written. With Site A fix, the OR'd predicate keeps control
        # flowing, and per-person Site B's DND branch either delivers
        # (if bypass) or writes the L9 audit row.
        p = _immediate_person()
        p[CONF_NM_PERSON_DND_BYPASS_SEVERITIES] = ()
        cfg = _cfg_all_channels(persons=[p])
        nm = _install_nm(hass, cfg)
        db = _install_db(hass)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )

        # WITHOUT Site A: early-return fires → no audit row, no send.
        # WITH Site A: control reaches per-person loop; recipient has
        # no bypass so no transport send, BUT the L9 audit row IS
        # written with the named DND-suppressed-security-image reason.
        audit_reasons = [
            c.kwargs.get("route_reason")
            for c in db.log_notification.await_args_list
            if c.kwargs.get("message") == "[audit]"
        ]
        assert NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE in audit_reasons, (
            "Site A fix must let control reach the per-person loop so the "
            "L9 DND-suppressed audit row is emitted. Without the fix, "
            "the global early-return short-circuits before any audit "
            f"row is written. Got audit reasons: {audit_reasons!r}"
        )

    @pytest.mark.asyncio
    async def test_force_immediate_respects_recipient_dnd_bypass(self):
        """L9: quiet hours + security-image + recipient WITHOUT matching
        DND bypass (IMMEDIATE-pref) → NOT delivered; audit row records
        the named DND-suppression reason (INV-1 does not override DND).
        """
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
        )
        hass = _make_hass()
        _put_house_asleep(hass)
        # digest-pref recipient with bypass-set = () → no MEDIUM bypass.
        # Digest pref is required so that any_digest_recipient=True does
        # NOT keep control from the per-person loop in the without-fix
        # world; but with the fix, this ensures Site B's per-recipient
        # DND branch decides. The audit row should carry the named
        # DND-suppression reason.
        p = _immediate_person()
        p[CONF_NM_PERSON_DND_BYPASS_SEVERITIES] = ()  # no bypass at all
        cfg = _cfg_all_channels(persons=[p])
        nm = _install_nm(hass, cfg)
        db = _install_db(hass)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )

        # DND without bypass → no transport send.
        nm._send_pushover.assert_not_awaited()
        nm._send_whatsapp.assert_not_awaited()
        # An audit row was emitted with the named DND-suppressed reason.
        audit_reasons = [
            c.kwargs.get("route_reason")
            for c in db.log_notification.await_args_list
            if c.kwargs.get("message") == "[audit]"
        ]
        assert (
            NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE in audit_reasons
        ), (
            f"expected DND-suppressed-security-image audit row, "
            f"got audit reasons: {audit_reasons!r}"
        )

    @pytest.mark.asyncio
    async def test_force_immediate_respects_global_kill_switch(self):
        """INV-1 non-override list: _messaging_suppressed kill switch
        drops the emit even for security+image."""
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        nm._messaging_suppressed = True

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )
        nm._send_pushover.assert_not_awaited()
        nm._send_whatsapp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_force_immediate_respects_silence_until(self):
        """INV-1 non-override list: an active silence-until window drops
        non-CRITICAL emits including security+image at MEDIUM."""
        from datetime import datetime, timedelta
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        nm._silence_until = datetime.utcnow() + timedelta(minutes=30)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )
        nm._send_pushover.assert_not_awaited()
        nm._send_whatsapp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_force_immediate_respects_dedup_window(self):
        """INV-1 non-override list: dedup on (coord,title,location)
        drops a duplicate security+image emit within the window."""
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        _install_db(hass)

        kwargs = dict(
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )
        # First emit fires.
        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted", **kwargs,
        )
        first_count = nm._send_whatsapp.await_count
        assert first_count >= 1
        # Second emit (same coord/title/location within window) is deduped.
        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted", **kwargs,
        )
        assert nm._send_whatsapp.await_count == first_count, (
            "security+image emit must still be dedup-suppressed on "
            "same (coord,title,location) within window"
        )

    @pytest.mark.asyncio
    async def test_force_immediate_respects_boot_settle_guard(self):
        """INV-1 non-override list: boot-settle guard drops a repeat
        (coord, hazard) emit within the boot window — critical against
        camera-boot avalanches (rev-2 HIGH-3)."""
        from datetime import datetime
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        _install_db(hass)
        # Arm the boot-settle window and mark this (coord, hazard) as
        # already seen so the SECOND emit is collapsed.
        with patch.object(_nm_mod, "dt_util") as mock_dt:
            mock_dt.utcnow.return_value = datetime.utcnow()
            mock_dt.now.return_value = datetime.now()
            mock_dt.as_local = lambda dt: dt
            # Far-future boot-settle window.
            nm._boot_settle_until = (
                datetime.utcnow().timestamp() + 3600
            )
            nm._boot_settle_seen.add(
                ("perimeter_alert", NM_HAZARD_EXTERIOR_PERSON),
            )
            await nm.async_notify(
                "perimeter_alert", Severity.MEDIUM,
                "Perimeter Alert — Person", "Person spotted",
                hazard_type=NM_HAZARD_EXTERIOR_PERSON,
                location="front_yard",
                snapshot_path=SNAP,
            )
        nm._send_pushover.assert_not_awaited()
        nm._send_whatsapp.assert_not_awaited()


# =========================================================================
# D2 audit-row assertions
# =========================================================================


class TestD2AuditRows:

    @pytest.mark.asyncio
    async def test_audit_row_route_reason_force_immediate_security_image(self):
        """When the predicate forces immediate, the per-recipient audit
        row's route_reason is the named constant (not a string literal
        anywhere in the test — sourced from const import).
        """
        hass = _make_hass()
        _put_house_awake(hass)
        nm = _install_nm(hass, _cfg_all_channels())
        db = _install_db(hass)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )

        audit_reasons = [
            c.kwargs.get("route_reason")
            for c in db.log_notification.await_args_list
            if c.kwargs.get("message") == "[audit]"
        ]
        assert (
            NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE in audit_reasons
        ), audit_reasons

        # In-memory routing ring MUST also carry the reason (feeds
        # sensor.ura_notification_manager_notification_diagnostics
        # attribute `nm_routing_audit_recent`).
        ring_reasons = [e.get("route_reason") for e in nm._routing_audit_log]
        assert (
            NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE in ring_reasons
        ), ring_reasons

    @pytest.mark.asyncio
    async def test_audit_row_route_reason_dnd_suppressed_security_image(self):
        """L9: quiet hours + no bypass matching MEDIUM → the audit row
        carries the DND-suppressed-security-image constant (not the
        legacy `"dnd_suppressed"` string)."""
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
        )
        hass = _make_hass()
        _put_house_asleep(hass)
        p = _immediate_person()
        p[CONF_NM_PERSON_DND_BYPASS_SEVERITIES] = ()
        cfg = _cfg_all_channels(persons=[p])
        nm = _install_nm(hass, cfg)
        db = _install_db(hass)

        await nm.async_notify(
            "perimeter_alert", Severity.MEDIUM,
            "Perimeter Alert — Person", "Person spotted",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front_yard",
            snapshot_path=SNAP,
        )
        audit_reasons = [
            c.kwargs.get("route_reason")
            for c in db.log_notification.await_args_list
            if c.kwargs.get("message") == "[audit]"
        ]
        assert (
            NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE in audit_reasons
        ), audit_reasons


# =========================================================================
# D3 — [audit] sentinel reader-side filter
# =========================================================================


class TestD3AuditSentinelFilter:
    """INV-2: no audit sentinel row ever renders into a digest body."""

    def test_format_digest_skips_audit_sentinel_items(self):
        """`_format_digest` given a mixed list of real + audit rows emits
        lines only for the real rows (belt-and-suspenders).

        Mutation anchor: remove the
        `if item.get("message") == "[audit]": continue` guard from
        `_format_digest` → this test still passes IF `get_pending_digest`
        excludes the sentinel; passes on the direct formatter test only
        as a second-layer guard.
        """
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        items = [
            {
                "coordinator_id": "perimeter_alert",
                "severity": "MEDIUM",
                "title": "Perimeter Alert",
                "location": "front_yard",
                "message": "[audit]",   # sentinel — MUST be skipped
            },
            {
                "coordinator_id": "safety",
                "severity": "HIGH",
                "title": "Water leak",
                "location": "Kitchen",
                "message": "Real leak detected",
            },
        ]
        result = nm._format_digest(items)
        assert "[audit]" not in result
        assert "Water leak" in result
        # Perimeter_alert coordinator has ONLY audit rows → it must not
        # produce a coordinator header either.
        assert "Perimeter_Alert" not in result

    def test_digest_body_excludes_audit_sentinel_rows(self):
        """End-to-end via `_fire_digest`: DB returns a mix of audit +
        real rows; delivered digest body carries only the real one."""
        hass = _make_hass()
        p = _digest_person()
        cfg = _cfg_all_channels(persons=[p])
        nm = NotificationManager(hass, cfg)
        nm._send_pushover = AsyncMock()

        db = MagicMock()
        db.get_pending_digest = AsyncMock(return_value=[
            {
                "coordinator_id": "perimeter_alert",
                "severity": "MEDIUM",
                "title": "Perimeter Alert",
                "location": "front_yard",
                "message": "[audit]",
            },
            {
                "coordinator_id": "safety",
                "severity": "MEDIUM",
                "title": "Humidity high",
                "location": "Bath",
                "message": "Real event",
            },
        ])
        db.mark_digest_delivered = AsyncMock()
        hass.data[DOMAIN]["database"] = db

        asyncio.get_event_loop().run_until_complete(
            nm._fire_digest("person.oji", p),
        )

        # Delivered body: 2nd positional arg to _send_pushover is the message.
        assert nm._send_pushover.await_count == 1
        body = nm._send_pushover.await_args.args[1]
        assert "[audit]" not in body
        assert "Humidity high" in body

    def test_pending_digest_query_shape(self):
        """Verify the reader-side filter is expressed in the SQL: a static
        source assertion that the WHERE clause carries the sentinel
        exclusion (paired with the runtime filter test above).

        Mutation anchor: remove `AND message != '[audit]'` from
        database.py get_pending_digest → this test fails.
        """
        import inspect
        from custom_components.universal_room_automation import database as _db_mod
        src = inspect.getsource(_db_mod.UniversalRoomDatabase.get_pending_digest)
        assert "message != '[audit]'" in src, (
            "get_pending_digest must exclude the [audit] sentinel at the "
            "SELECT layer (D3 primary reader-side fix)"
        )

    def test_mark_digest_delivered_also_marks_audit_rows_bounded(self):
        """`mark_digest_delivered` marks BOTH real and audit rows
        delivered=2 for the person — bounded queue growth per
        rev-2 §10.4. Static source assertion: the UPDATE has no
        `message != '[audit]'` guard."""
        import inspect
        from custom_components.universal_room_automation import database as _db_mod
        src = inspect.getsource(_db_mod.UniversalRoomDatabase.mark_digest_delivered)
        assert "message != '[audit]'" not in src, (
            "mark_digest_delivered must include audit rows in the UPDATE "
            "so the audit queue does not grow unboundedly at LOW/MEDIUM "
            "volume (rev-2 §10.4)"
        )
        # And the marker value is 2 (queue-management, not "delivered").
        assert "delivered = 2" in src

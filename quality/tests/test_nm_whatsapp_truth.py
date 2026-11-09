"""PERIMETER-FP D7 (v5.107.0): WhatsApp silent-failure fix (INV-WA-TRUTH).

A WhatsApp send counts as delivered only when the pre-send check did not say
the bridge was down AND the service call did not raise. Unknown status =
today's behaviour (send). Drives the REAL `_send_whatsapp`, `async_notify`
and `_deliver_digest`; only the non-WhatsApp transports are stubbed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_nm_image_delivery import (  # noqa: F401  (autouse clock fixture)
    _d7_naive_nm_clock,
    _cfg_all_channels,
    _immediate_person,
    _install_db,
    _put_house_awake,
)
from test_notification_manager import _make_hass
from custom_components.universal_room_automation.const import (
    CONF_NM_PERSON_DIGEST_CHANNELS,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_IMESSAGE_ENABLED,
    NM_HAZARD_EXTERIOR_PERSON,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity


def _nm(hass, cfg=None, status="connected", bridges=True):
    if bridges:
        hass.data["wa_bridge"] = {"e1": SimpleNamespace(connection_status=status)}
    nm = NotificationManager(hass, cfg or _cfg_all_channels())
    nm._send_pushover = AsyncMock()
    nm._send_companion = AsyncMock()
    nm._send_imessage = AsyncMock()
    nm._channel_health.setdefault("whatsapp", {"status": "ok", "failures": 0})
    return nm


def _wa_calls(hass):
    return [c for c in hass.services.async_call.await_args_list
            if c.args[:2] == ("wa_bridge", "send_message")]


@pytest.mark.parametrize("status,ready", [
    ("connected", True),
    ("auth_failed", False), ("error", False), ("reconnecting", False),
    ("disconnected", False),
    ("weird_new_state", True),   # unknown -> today's behaviour
    (None, True),                # attribute present but None -> unknown
])
def test_wa_ready_each_status(status, ready):
    hass = _make_hass()
    nm = _nm(hass, status=status)
    ok = asyncio.run(nm._send_whatsapp("T", "m", "+1555"))
    assert ok is ready
    assert len(_wa_calls(hass)) == (1 if ready else 0)


def test_wa_ready_missing_attr_and_missing_data():
    hass = _make_hass()
    nm = _nm(hass, bridges=False)
    hass.data["wa_bridge"] = {"e1": object()}  # no connection_status attr
    assert asyncio.run(nm._send_whatsapp("T", "m", "+1")) is True
    hass2 = _make_hass()
    nm2 = _nm(hass2, bridges=False)  # hass.data["wa_bridge"] absent
    assert asyncio.run(nm2._send_whatsapp("T", "m", "+1")) is True
    assert len(_wa_calls(hass2)) == 1
    assert nm2._whatsapp_probe_unknown == 1


def test_wa_ready_mixed_bad_and_unknown_sends():
    """Only an all-known-bad answer blocks; one unknown bridge = today."""
    hass = _make_hass()
    nm = _nm(hass, bridges=False)
    hass.data["wa_bridge"] = {
        "e1": SimpleNamespace(connection_status="auth_failed"),
        "e2": SimpleNamespace(connection_status="booting"),
    }
    assert asyncio.run(nm._send_whatsapp("T", "m", "+1")) is True


def test_wa_ready_entry_not_loaded():
    from homeassistant.config_entries import ConfigEntryState
    hass = _make_hass()
    nm = _nm(hass, status="connected")
    hass.config_entries.async_entries = MagicMock(
        return_value=[SimpleNamespace(state=ConfigEntryState.SETUP_RETRY)])
    assert asyncio.run(nm._send_whatsapp("T", "m", "+1")) is False
    assert _wa_calls(hass) == []


def test_wa_failure_counts_health_and_returns_false():
    hass = _make_hass()
    nm = _nm(hass, status="auth_failed")
    before = nm._channel_health["whatsapp"]["failures"]
    assert asyncio.run(nm._send_whatsapp("T", "m", "+1")) is False
    assert nm._channel_health["whatsapp"]["failures"] == before + 1


def test_wa_service_raise_returns_false():
    hass = _make_hass()
    nm = _nm(hass)
    hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
    assert asyncio.run(nm._send_whatsapp("T", "m", "+1")) is False


def test_wa_2x_domain_not_probed():
    hass = _make_hass()
    hass.services.has_service = lambda d, s: d == "whatsapp"
    nm = _nm(hass, status="auth_failed")
    assert asyncio.run(nm._send_whatsapp("T", "m", "+1")) is True
    assert [c.args[0] for c in hass.services.async_call.await_args_list] == ["whatsapp"]


def test_wa_dry_run_returns_true():
    hass = _make_hass()
    nm = _nm(hass, status="auth_failed")
    nm._dry_run_active = True
    nm._log_dry_run = AsyncMock()
    assert asyncio.run(nm._send_whatsapp("T", "m", "+1")) is True


def _notify(nm):
    asyncio.run(nm.async_notify(
        "perimeter_alert", Severity.CRITICAL, "Perimeter", "Person",
        hazard_type=NM_HAZARD_EXTERIOR_PERSON, location="front_yard",
    ))


def test_wa_immediate_alert_uses_result():
    """Site :2044 — failed WhatsApp: not in channels_fired, logged 0."""
    hass = _make_hass()
    _put_house_awake(hass)
    db = _install_db(hass)
    nm = _nm(hass, _cfg_all_channels(persons=[_immediate_person()]), status="auth_failed")
    nm._emit_audit_row = AsyncMock()
    _notify(nm)
    wa_rows = [c.args for c in db.log_notification.await_args_list if c.args[7] == "whatsapp"]
    assert wa_rows and all(r[8] == 0 for r in wa_rows)
    audit = nm._emit_audit_row.await_args.kwargs
    assert "whatsapp" not in (audit["channel"] or "")
    assert audit["channel"] == "companion,imessage,pushover"
    # and when connected it IS counted
    hass2 = _make_hass()
    _put_house_awake(hass2)
    db2 = _install_db(hass2)
    nm2 = _nm(hass2, _cfg_all_channels(persons=[_immediate_person()]), status="connected")
    nm2._emit_audit_row = AsyncMock()
    _notify(nm2)
    wa2 = [c.args for c in db2.log_notification.await_args_list if c.args[7] == "whatsapp"]
    assert wa2 and wa2[0][8] == 1
    assert "whatsapp" in nm2._emit_audit_row.await_args.kwargs["channel"]


def test_audit_row_per_recipient_fired():
    """Two recipients; WhatsApp fails for one only. Each row lists what
    fired for THAT recipient (channels_fired is per notify)."""
    hass = _make_hass()
    _put_house_awake(hass)
    _install_db(hass)
    a = _immediate_person("person.a")
    b = _immediate_person("person.b")
    b[CONF_NM_PERSON_WHATSAPP_PHONE] = "+2"
    nm = _nm(hass, _cfg_all_channels(persons=[a, b]))
    real = nm._send_whatsapp

    async def _wa(title, message, phone, **kw):
        if phone == "+2":
            return False
        return await real(title, message, phone, **kw)
    nm._send_whatsapp = _wa
    nm._emit_audit_row = AsyncMock()
    _notify(nm)
    rows = {c.kwargs["recipient_id"]: c.kwargs["channel"]
            for c in nm._emit_audit_row.await_args_list}
    assert "whatsapp" in rows["person.a"]
    assert "whatsapp" not in rows["person.b"]
    assert rows["person.b"] == "companion,imessage,pushover"


def test_audit_row_omits_channel_with_no_handle():
    """Pre-cycle rows listed gate-allowed channels even with no handle."""
    hass = _make_hass()
    _put_house_awake(hass)
    _install_db(hass)
    p = _immediate_person()
    p[CONF_NM_PERSON_WHATSAPP_PHONE] = ""
    nm = _nm(hass, _cfg_all_channels(persons=[p]))
    nm._emit_audit_row = AsyncMock()
    _notify(nm)
    assert nm._emit_audit_row.await_args.kwargs["channel"] == "companion,imessage,pushover"


def _digest_cfg(selected=None):
    p = {
        CONF_NM_PERSON_ENTITY: "person.a",
        CONF_NM_PERSON_WHATSAPP_PHONE: "+1",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "a@icloud",
    }
    if selected is not None:
        p[CONF_NM_PERSON_DIGEST_CHANNELS] = selected
    return p


def test_digest_falls_through_on_wa_fail():
    """Site :5470 — first-wins chain: pushover/companion off, WhatsApp
    auth_failed -> iMessage sent."""
    hass = _make_hass()
    nm = _nm(hass, _cfg_all_channels(**{
        CONF_NM_PUSHOVER_ENABLED: False, CONF_NM_COMPANION_ENABLED: False,
    }), status="auth_failed")
    sent = asyncio.run(nm._deliver_digest("person.a", _digest_cfg(), "digest"))
    assert sent is True
    nm._send_imessage.assert_awaited_once()


def test_digest_chain_stops_at_wa_when_connected():
    hass = _make_hass()
    nm = _nm(hass, _cfg_all_channels(**{
        CONF_NM_PUSHOVER_ENABLED: False, CONF_NM_COMPANION_ENABLED: False,
    }), status="connected")
    assert asyncio.run(nm._deliver_digest("person.a", _digest_cfg(), "digest")) is True
    nm._send_imessage.assert_not_awaited()


def test_digest_selected_set_wa_only_fail_reports_unsent():
    """Site :5443 — selected {whatsapp} only, bridge down -> sent_any False."""
    hass = _make_hass()
    nm = _nm(hass, _cfg_all_channels(), status="error")
    assert asyncio.run(nm._deliver_digest("person.a", _digest_cfg(["whatsapp"]), "d")) is False
    hass2 = _make_hass()
    nm2 = _nm(hass2, _cfg_all_channels(), status="connected")
    assert asyncio.run(nm2._deliver_digest("person.a", _digest_cfg(["whatsapp"]), "d")) is True

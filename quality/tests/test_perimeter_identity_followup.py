"""PERIMETER-IDENTITY-FOLLOWUP-1 (v5.107.5) — "that was <name>" follow-up.

Drives the REAL `_async_handle_perimeter_trigger` (alert + arm), the real
scheduled `_tick` callbacks, `async_teardown`, and the real NotificationManager
`async_notify` / `_send_pushover`. Oracles are hand-written: the window is
90 s at a 5 s poll = 18 ticks; the message text is spelled out literally.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_perimeter_alert_nm_routing import _scheduled, Severity, _const  # noqa: E402
from test_perimeter_fp_gates import (  # noqa: E402,F401  (autouse clock)
    _frozen_clock,
    _d105,
    _leg,
    _now,
    _run,
    _sev,
    DB_PR,
    DB_KEY,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _drain_scheduled():
    """`_scheduled` is module state shared with test_exterior_cycle2 — a
    pending follow-up tick must never outlive its test."""
    _scheduled.clear()
    yield
    _scheduled.clear()


def _ticks():
    return [(d, cb) for (d, cb) in _scheduled if getattr(cb, "__name__", "") == "_tick"]


def _fire_tick(hass):
    """Fire every pending follow-up tick once; run any task it creates."""
    ticks = _ticks()
    for item in ticks:
        _scheduled.remove(item)
    created: list = []
    hass.async_create_task = lambda coro: created.append(coro)
    for _d, cb in ticks:
        cb(None)
    for c in created:
        _run(c)
    return ticks


def _followups(nm):
    return [c for c in nm.async_notify.await_args_list
            if c.kwargs.get("title") == "Perimeter Alert — Identified"]


def _alert(monkeypatch, legs=None, **kw):
    """One unknown, corroborated doorbell alert (CRITICAL, house away)."""
    _scheduled.clear()
    hass, nm, mgr = _d105(monkeypatch, legs=legs or [], **kw)
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    return hass, nm, mgr


def _jaya_named(hass, conf=0.95, after_s=60):
    # Protect back-fills the name onto the face leg AFTER the edge.
    hass.data[_const.DOMAIN]["census"].legs = [_leg("jaya_udezue", conf, age_s=-after_s)]


# --------------------------------------------------------------------------
# sent once / quiet
# --------------------------------------------------------------------------

def test_followup_sent_once_when_name_arrives(monkeypatch):
    hass, nm, mgr = _alert(monkeypatch)
    assert nm.async_notify.await_count == 1
    assert _sev(nm) == Severity.CRITICAL
    assert DB_KEY in mgr._pending_followups
    # First tick: nobody named yet -> nothing sent, re-armed.
    assert [d for d, _ in _fire_tick(hass)] == [5.0]
    assert _followups(nm) == []
    assert len(_ticks()) == 1
    # Name lands -> exactly one follow-up.
    _jaya_named(hass)
    _fire_tick(hass)
    fu = _followups(nm)
    assert len(fu) == 1
    kw = fu[0].kwargs
    assert kw["message"] == "Doorbell Lite: that was Jaya Udezue"
    assert kw["severity"] == Severity.CRITICAL      # same channels as original
    assert kw["quiet"] is True                      # non-siren form
    assert kw["location"] == DB_PR
    assert kw["hazard_type"] == _const.NM_HAZARD_EXTERIOR_PERSON
    assert DB_KEY not in mgr._pending_followups
    assert _ticks() == []


def test_followup_frigate_face_needs_corroboration(monkeypatch):
    """Unscored (Frigate) face alone never names anyone (D10.5 rule)."""
    hass, nm, mgr = _alert(monkeypatch)
    hass.data[_const.DOMAIN]["census"].legs = [_leg("jaya_udezue", None, age_s=-30)]
    _fire_tick(hass)
    assert _followups(nm) == []
    assert DB_KEY in mgr._pending_followups


def test_followup_uses_person_friendly_name(monkeypatch):
    from test_perimeter_fp_gates import _St
    hass, nm, _mgr = _alert(monkeypatch)
    hass._states["person.jaya_udezue"] = _St("home", {"friendly_name": "Jaya"})
    hass._states["camera.doorbell_lite"] = _St("idle", {"friendly_name": "Front door"})
    _jaya_named(hass)
    _fire_tick(hass)
    assert _followups(nm)[0].kwargs["message"] == "Front door: that was Jaya"


# --------------------------------------------------------------------------
# window
# --------------------------------------------------------------------------

def test_followup_not_sent_after_window(monkeypatch):
    hass, nm, mgr = _alert(monkeypatch)
    for _ in range(17):                    # 85 s: still pending
        _fire_tick(hass)
    assert DB_KEY in mgr._pending_followups
    _fire_tick(hass)                       # 90 s: window closes
    assert DB_KEY not in mgr._pending_followups
    assert _ticks() == []
    _jaya_named(hass)                      # name arrives late
    _fire_tick(hass)
    assert _followups(nm) == []


def test_followup_sent_on_last_tick_inside_window(monkeypatch):
    hass, nm, _mgr = _alert(monkeypatch)
    for _ in range(17):
        _fire_tick(hass)
    _jaya_named(hass, after_s=88)
    _fire_tick(hass)                       # tick 18 = 90 s, still inside
    assert len(_followups(nm)) == 1


def test_followup_window_zero_disables(monkeypatch):
    from test_perimeter_alert_nm_routing import _perimeter
    monkeypatch.setattr(_perimeter, "PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S", 0)
    _hass, _nm, mgr = _alert(monkeypatch)
    assert mgr._pending_followups == {}
    assert _ticks() == []


# --------------------------------------------------------------------------
# never for demoted / LOW / named / switch off
# --------------------------------------------------------------------------

def test_followup_not_armed_for_known_demoted_alert(monkeypatch):
    hass, nm, mgr = _alert(monkeypatch, legs=[_leg("oji_udezue", 0.9)])
    assert _sev(nm) == Severity.LOW
    assert mgr._pending_followups == {}
    assert _ticks() == []


def test_followup_not_armed_for_low_alert(monkeypatch):
    """Unknown + corroborated, but house-state severity is LOW: nothing
    reached the operator, so there is nothing to follow up."""
    _scheduled.clear()
    hass, nm, mgr = _d105(monkeypatch, legs=[])
    hass.data[_const.DOMAIN]["coordinator_manager"].house_state = "home_day"
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW
    assert mgr._last_gate_decisions[DB_KEY]["egress_identity"]["reason"] == "egress_unknown_corroborated"
    assert mgr._pending_followups == {}


def test_followup_not_armed_when_alert_already_named(monkeypatch):
    """0.8 Protect name: below the 0.9 demote floor (pages) but the alert
    already said 'Identified: Oji Udezue'."""
    _hass, nm, mgr = _alert(monkeypatch, legs=[_leg("oji_udezue", 0.8)])
    assert _sev(nm) == Severity.CRITICAL
    assert "Identified: Oji Udezue." in nm.async_notify.await_args.kwargs["message"]
    assert mgr._pending_followups == {}


def test_followup_switch_off(monkeypatch):
    _scheduled.clear()
    hass, nm, mgr = _d105(monkeypatch, legs=[])
    entry = hass.config_entries.async_entries.return_value[0]
    entry.options[_const.CONF_PERIMETER_IDENTITY_FOLLOWUP] = False
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert mgr._pending_followups == {}


def test_followup_default_on():
    assert _const.DEFAULT_PERIMETER_IDENTITY_FOLLOWUP is True


def test_followup_switch_registered_with_key():
    from test_perimeter_fp_gates import _platform_entities
    sw = _platform_entities("switch")["switch.ura_perimeter_identity_followup"]
    assert sw.is_on is True
    sw._entry.options = {"perimeter_identity_followup": False}
    assert sw.is_on is False


@pytest.mark.parametrize("field,value", [
    ("demoted", True),
    ("reason", "egress_known_person"),
    ("reason", "gate_off"),
    ("severity_after", "LOW"),        # a later gate (VLM) demoted it
    ("at", "1999-01-01T00:00:00"),    # decision belongs to another alert
])
def test_followup_arm_requires_this_alerts_unknown_decision(monkeypatch, field, value):
    _hass, _nm, mgr = _alert(monkeypatch)
    edge = _now()
    mgr._cancel_identity_followup(DB_KEY, "test")
    d = dict(mgr._last_gate_decisions[DB_KEY]["egress_identity"])
    assert mgr._arm_identity_followup(DB_KEY, DB_PR, edge, Severity.CRITICAL, None) is True
    d[field] = value
    mgr._last_gate_decisions[DB_KEY]["egress_identity"] = d
    assert mgr._arm_identity_followup(DB_KEY, DB_PR, edge, Severity.CRITICAL, None) is False
    assert mgr._pending_followups == {}


# --------------------------------------------------------------------------
# at most once / supersede / teardown
# --------------------------------------------------------------------------

def test_followup_not_sent_twice(monkeypatch):
    hass, nm, _mgr = _alert(monkeypatch)
    _jaya_named(hass)
    fired = _ticks()
    _fire_tick(hass)
    assert len(_followups(nm)) == 1
    # A stale tick firing again (timer race) must not send a second one.
    created: list = []
    hass.async_create_task = lambda coro: created.append(coro)
    for _d, cb in fired:
        cb(None)
    for c in created:
        _run(c)
    assert len(_followups(nm)) == 1


def test_followup_superseded_by_new_alert(monkeypatch):
    hass, nm, mgr = _alert(monkeypatch)
    first = mgr._pending_followups[DB_KEY]
    first_unsub = first["unsub"]
    stale = _ticks()
    later = _now() + timedelta(seconds=400)
    mgr._last_gate_decisions[DB_KEY]["egress_identity"]["at"] = later.isoformat()
    assert mgr._arm_identity_followup(DB_KEY, DB_PR, later, Severity.CRITICAL, None)
    assert mgr._pending_followups[DB_KEY] is not first
    first_unsub.assert_called_once()
    # The superseded alert's stale tick sends nothing.
    _jaya_named(hass)
    created: list = []
    hass.async_create_task = lambda coro: created.append(coro)
    for _d, cb in stale:
        cb(None)
    assert created == []


def test_followup_superseded_by_demoted_alert(monkeypatch):
    """Any later dispatched alert on the camera discharges the pending one,
    even one that does not arm its own."""
    hass, nm, mgr = _alert(monkeypatch)
    unsub = mgr._pending_followups[DB_KEY]["unsub"]
    assert mgr._arm_identity_followup(DB_KEY, DB_PR, _now(), Severity.LOW, None) is False
    assert mgr._pending_followups == {}
    unsub.assert_called_once()


def test_followup_cancelled_on_teardown(monkeypatch):
    hass, nm, mgr = _alert(monkeypatch)
    unsub = mgr._pending_followups[DB_KEY]["unsub"]
    stale = _ticks()
    _run(mgr.async_teardown())
    assert mgr._pending_followups == {}
    unsub.assert_called_once()
    _jaya_named(hass)
    created: list = []
    hass.async_create_task = lambda coro: created.append(coro)
    for _d, cb in stale:
        cb(None)
    assert created == []
    assert _followups(nm) == []


# --------------------------------------------------------------------------
# NotificationManager quiet form
# --------------------------------------------------------------------------

from test_nm_image_delivery import (  # noqa: E402,F401
    _d7_naive_nm_clock,
    _cfg_all_channels,
    _immediate_person,
    _install_db,
    _put_house_awake,
)
from test_notification_manager import _make_hass as _nm_hass  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (  # noqa: E402
    NotificationManager,
)


def _pushover_data(hass):
    calls = [c for c in hass.services.async_call.await_args_list
             if c.args[:2] == ("notify", "pushover")]
    assert len(calls) == 1
    return calls[0].args[2]


@pytest.mark.parametrize("sev", [Severity.CRITICAL, Severity.HIGH])
def test_pushover_quiet_is_not_siren(sev):
    hass = _nm_hass()
    nm = NotificationManager(hass, _cfg_all_channels())
    asyncio.run(nm._send_pushover("T", "m", sev, "ukey", quiet=True))
    data = _pushover_data(hass)
    assert data["data"] == {"priority": 0}


def test_pushover_not_quiet_unchanged():
    hass = _nm_hass()
    nm = NotificationManager(hass, _cfg_all_channels())
    asyncio.run(nm._send_pushover("T", "m", Severity.CRITICAL, "ukey"))
    assert _pushover_data(hass)["data"] == {"priority": 1, "sound": "siren"}


def _quiet_nm(tts=True):
    hass = _nm_hass()
    _put_house_awake(hass)
    _install_db(hass)
    cfg = _cfg_all_channels(persons=[_immediate_person()])
    cfg[_const.CONF_NM_TTS_ENABLED] = tts
    nm = NotificationManager(hass, cfg)
    nm._send_companion = AsyncMock()
    nm._send_whatsapp = AsyncMock(return_value=True)
    nm._send_imessage = AsyncMock()
    nm._send_tts = AsyncMock()
    nm._enter_alerting = AsyncMock()
    nm._schedule_panel_delivery = MagicMock()
    return hass, nm


def test_async_notify_quiet_critical_followup():
    hass, nm = _quiet_nm()
    asyncio.run(nm.async_notify(
        "perimeter_alert", Severity.CRITICAL, "Perimeter Alert — Identified",
        "Front door: that was Jaya",
        hazard_type=_const.NM_HAZARD_EXTERIOR_PERSON, location=DB_PR, quiet=True,
    ))
    # Pushover reached at priority 0, no siren, no response menu.
    data = _pushover_data(hass)
    assert data["data"] == {"priority": 0}
    assert data["message"] == "Front door: that was Jaya"
    # Companion reached without the critical sound.
    assert nm._send_companion.await_args.kwargs["is_critical"] is False
    # Text channels reached with the plain message.
    assert nm._send_whatsapp.await_args.args[1] == "Front door: that was Jaya"
    assert nm._send_imessage.await_count == 1
    # No house-wide side effects, no re-page engine.
    nm._send_tts.assert_not_awaited()
    nm._enter_alerting.assert_not_awaited()
    nm._schedule_panel_delivery.assert_not_called()


def test_async_notify_not_quiet_critical_unchanged():
    hass, nm = _quiet_nm()
    asyncio.run(nm.async_notify(
        "perimeter_alert", Severity.CRITICAL, "Perimeter", "Person",
        hazard_type=_const.NM_HAZARD_EXTERIOR_PERSON, location=DB_PR,
    ))
    assert _pushover_data(hass)["data"] == {"priority": 1, "sound": "siren"}
    assert nm._send_companion.await_args.kwargs["is_critical"] is True
    nm._send_tts.assert_awaited_once()
    nm._enter_alerting.assert_awaited_once()
    nm._schedule_panel_delivery.assert_called_once()

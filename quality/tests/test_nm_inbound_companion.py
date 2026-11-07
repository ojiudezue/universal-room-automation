"""Companion action replies reach the person (NM-COMPANION-STATUS-NO-REPLY-1).

Person resolved from event.context.user_id -> person.* state attribute
user_id (same lookup as hvac_override._resolve_context_user_to_person).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import nm_diag_harness as h
from nm_diag_harness import Clock, PERSON, fixed_clock, make_nm, run


@pytest.fixture
def clock():
    c = Clock()
    with fixed_clock(c):
        yield c


def _persons(*pairs):
    return [SimpleNamespace(entity_id=e, attributes={"user_id": u}) for e, u in pairs]


def _drive(nm, data, user_id, persons):
    nm.hass.states.async_all = lambda domain: persons if domain == "person" else []
    coros = []
    nm.hass.async_create_task = lambda coro, *a, **k: coros.append(coro)
    nm._handle_companion_action(SimpleNamespace(data=data, context=SimpleNamespace(user_id=user_id)))
    return [run(c) for c in coros]


def _sent(nm):
    return [c.args for c in nm.hass.services.async_call.call_args_list]


def test_status_reply_reaches_resolved_person(clock):
    """Protects the STATUS_URA call site passing _person_for_companion_event."""
    nm = make_nm()
    out = _drive(nm, {"action": "STATUS_URA"}, "u-op", _persons(("person.other", "u-x"), (PERSON, "u-op")))
    assert out == ["URA Alert Status: No active alerts. All clear."]
    # A2: a reply carries no action buttons at all.
    assert _sent(nm) == [("notify", "mobile_app_op", {"title": "URA", "message": out[0]})]
    assert nm._test_db.log_inbound.call_args.args[0] == PERSON


def test_silence_reply_reaches_resolved_person(clock):
    nm = make_nm()
    out = _drive(nm, {"action": "SILENCE_URA"}, "u-op", _persons((PERSON, "u-op")))
    assert out[0].startswith("Non-CRITICAL alerts silenced")
    assert len(_sent(nm)) == 1


def test_text_input_diag_word_answers(clock):
    """Protects the ACKNOWLEDGE_URA_CRITICAL call site."""
    nm = make_nm()
    out = _drive(nm, {"action": "ACKNOWLEDGE_URA_CRITICAL", "reply_text": "doors"}, "u-op", _persons((PERSON, "u-op")))
    assert out[0].startswith("Doors")
    assert _sent(nm)[0][0] == "notify"


def test_unresolved_user_keeps_old_behaviour(clock):
    nm = make_nm()
    out = _drive(nm, {"action": "STATUS_URA"}, "u-nobody", _persons((PERSON, "u-op")))
    assert out == ["URA Alert Status: No active alerts. All clear."]
    assert _sent(nm) == []


def test_unconfigured_person_not_resolved(clock):
    nm = make_nm()
    assert nm._person_for_companion_event(SimpleNamespace(context=SimpleNamespace(user_id="u-g"))) is None
    nm.hass.states.async_all = lambda d: _persons(("person.guest", "u-g"))
    assert nm._person_for_companion_event(SimpleNamespace(context=SimpleNamespace(user_id="u-g"))) is None


def test_no_context_user_none(clock):
    nm = make_nm()
    nm.hass.states.async_all = lambda d: _persons((PERSON, "u-op"))
    assert nm._person_for_companion_event(SimpleNamespace(context=SimpleNamespace(user_id=None))) is None
    assert nm._person_for_companion_event(SimpleNamespace()) is None


def test_status_during_critical_reply_has_no_actions_and_stays_unacked(clock):
    """A2: protects `reply=True` from _send_reply -> _send_companion and the
    `if reply:` branch: no Acknowledge button under a CRITICAL's status reply."""
    nm = make_nm()
    nm._alert_state = h.AlertState.ALERTING
    nm._active_alert_data = {"severity": "CRITICAL", "hazard_type": "smoke",
                             "location": "kitchen", "coordinator_id": "safety"}
    out = _drive(nm, {"action": "STATUS_URA"}, "u-op", _persons((PERSON, "u-op")))
    assert out[0].startswith("URA Alert Status:")
    (domain, service, payload), = _sent(nm)
    assert "data" not in payload and "actions" not in str(payload)
    assert nm.async_acknowledge.call_count == 0
    assert nm._alert_state is h.AlertState.ALERTING


def test_alert_push_keeps_buttons(clock):
    """Legacy alert pushes (not replies) still carry their action buttons."""
    nm = make_nm()
    run(nm._send_companion("Alert", "body", h.nm_mod.Severity.HIGH, "notify.mobile_app_op"))
    run(nm._send_companion("Alert", "body", h.nm_mod.Severity.CRITICAL, "notify.mobile_app_op", is_critical=True))
    acts = [[a["action"] for a in c.args[2]["data"]["actions"]] for c in nm.hass.services.async_call.call_args_list]
    assert acts == [["ACKNOWLEDGE_URA", "STATUS_URA", "SILENCE_URA"],
                    ["ACKNOWLEDGE_URA_CRITICAL", "STATUS_URA", "SILENCE_URA"]]


def test_resolved_companion_digit_while_alerting_is_legacy(clock):
    """A3: a resolved Companion person's '1' during ALERTING is the legacy ack
    path (state rail), not a menu item."""
    nm = make_nm()
    _drive(nm, {"action": "ACKNOWLEDGE_URA_CRITICAL", "reply_text": "diag"}, "u-op", _persons((PERSON, "u-op")))
    nm._alert_state = h.AlertState.ALERTING
    nm._active_alert_data = {"severity": "CRITICAL", "hazard_type": "smoke"}
    out = _drive(nm, {"action": "ACKNOWLEDGE_URA_CRITICAL", "reply_text": "1"}, "u-op", _persons((PERSON, "u-op")))
    assert out == ["CRITICAL alert requires safe word. Reply with your safe word to acknowledge."]

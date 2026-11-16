"""VISION-INTERIOR-SIGHTINGS-1 ship 2 (plan §9.D3, Q2): the NM `describe`
command. REAL NotificationManager (``nm_diag_harness.make_nm``), driven
through ``_process_inbound_reply`` (the inbound entry), with a recording
presence coordinator standing in for the read surface (the producer side is
covered on the real rig in ``test_interior_vision_describe.py``) and a
recording ``_send_reply``. No swallowed exceptions; fixed clock."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import nm_diag_harness as H
from custom_components.universal_room_automation import const as C
from custom_components.universal_room_automation.interior_vision import describe_access

OP = H.PERSON              # first NM person = the operator (no security-ack list)
KID = "person.kid"
STRANGER = "person.stranger"


class _Presence:
    def __init__(self, immediate: str = "") -> None:
        self.calls: list[dict] = []
        self.immediate = immediate

    def request_room_description(self, target, *, requester, reason, include_affect=False,
                                 reply=None):
        self.calls.append({"target": target, "requester": requester, "reason": reason,
                           "include_affect": include_affect, "reply": reply})
        return self.immediate


def _nm(mode=None, immediate=""):
    nm = H.make_nm()
    nm._config[C.CONF_NM_PERSONS] = list(nm._config[C.CONF_NM_PERSONS]) + [
        {C.CONF_NM_PERSON_ENTITY: KID, C.CONF_NM_PERSON_IMESSAGE_HANDLE: "kid@example.com"}]
    pres = _Presence(immediate)
    nm.hass.data[C.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"presence": pres})
    if mode is not None:
        nm.hass.data[C.DOMAIN][C.INTERIOR_DESCRIBE_ACCESS_HASS_KEY] = mode
    nm._send_reply = AsyncMock(return_value=None)
    return nm, pres


def _in(nm, person, text, channel="imessage"):
    return H.run(nm._process_inbound_reply(person, channel, text))


def test_describe_access_default_operator_only():
    """Default `operator`: the operator gets a call (no affect); a resident
    gets "Not available." and no call."""
    nm, pres = _nm()
    with H.fixed_clock(H.Clock()):
        assert _in(nm, KID, "describe family room") == ""
        assert pres.calls == []
        nm._send_reply.assert_awaited_once_with(KID, "imessage", "Not available.")
        assert _in(nm, OP, "Describe Family Room") == ""
    assert [(c["target"], c["requester"], c["include_affect"]) for c in pres.calls] == [
        ("Family Room", OP, False)]
    by = nm.inbound_by_command
    assert (by.get("describe_denied"), by.get("describe_scheduled")) == (1, 1)


@pytest.mark.parametrize("mode, who, allowed, affect", [
    ("operator", OP, True, False),
    ("operator", KID, False, False),
    ("operator_affect", OP, True, True),
    ("operator_affect", KID, False, False),
    ("residents", KID, True, False),
    ("residents", STRANGER, False, False),
    ("any_resolved", STRANGER, True, False),
])
def test_describe_access_modes(mode, who, allowed, affect):
    """Q2 Select modes end to end; affect only for operator_affect + operator."""
    nm, pres = _nm(mode)
    with H.fixed_clock(H.Clock()):
        _in(nm, who, "describe foyer")
    assert bool(pres.calls) is allowed
    if allowed:
        assert pres.calls[0]["include_affect"] is affect


def test_describe_access_pure_rule():
    ops, res = [OP], [OP, KID]
    assert describe_access("operator", None, ops, res, True) == (False, False)
    assert describe_access("operator_affect", OP, ops, res, False) == (True, False)
    assert describe_access("bogus", KID, ops, res, True) == (False, False)
    assert describe_access("any_resolved", OP, ops, res, True) == (True, False)


def test_describe_reply_to_requester_only():
    """The answer goes through `_send_reply` to the requester on the
    requester's channel, once."""
    nm, pres = _nm()
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe family room", channel="whatsapp")
    reply = pres.calls[0]["reply"]
    H.run(reply("Family Room: 1 person."))
    nm._send_reply.assert_awaited_once_with(OP, "whatsapp", "Family Room: 1 person.")


def test_describe_refusal_relayed_and_no_cooldown():
    """An immediate refusal from the read surface is sent back at once and
    does not start the cooldown."""
    nm, pres = _nm(immediate="No camera in Garage A.")
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe garage a")
        _in(nm, OP, "describe garage a")
    assert len(pres.calls) == 2
    assert [c.args for c in nm._send_reply.await_args_list] == [
        (OP, "imessage", "No camera in Garage A.")] * 2


def test_describe_nm_cooldown():
    """INTERIOR_DESCRIBE_NM_COOLDOWN_S (60 s) per requester: a second
    accepted request inside it is refused with no call; 61 s later it goes."""
    nm, pres = _nm()
    clock = H.Clock()
    with H.fixed_clock(clock):
        _in(nm, OP, "describe family room")
        clock.now = H.T0 + timedelta(seconds=59)
        _in(nm, OP, "describe family room")
        assert len(pres.calls) == 1
        nm._send_reply.assert_awaited_once_with(
            OP, "imessage", "Please wait 60 s before asking again.")
        clock.now = H.T0 + timedelta(seconds=61)
        _in(nm, OP, "describe family room")
    assert len(pres.calls) == 2


def test_describe_unresolved_requester_no_call():
    nm, pres = _nm()
    with H.fixed_clock(H.Clock()):
        _in(nm, None, "describe family room")
    assert pres.calls == [] and nm._send_reply.await_count == 0


def test_describe_blocked_by_messaging_kill():
    nm, pres = _nm()
    nm._messaging_suppressed = True
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe family room")
    assert pres.calls == []


@pytest.mark.parametrize("channel", ["pushover", "companion"])
def test_describe_text_channels_only(channel):
    """Only iMessage / WhatsApp take the command (plan: text channels)."""
    nm, pres = _nm()
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe family room", channel=channel)
    assert pres.calls == []


def test_operator_helper_shared_with_security_ack():
    """The factored helper keeps the security-ack rule: the security-ack
    list when set, else the first NM person."""
    nm, _ = _nm()
    assert nm._operator_person_entities() == [OP]
    nm._config[C.CONF_NM_SECURITY_ACK_PERSONS] = [KID]
    assert nm._operator_person_entities() == [KID]
    assert nm._is_authorized_to_ack(KID, "intruder") == (True, "authorized_security")
    assert nm._is_authorized_to_ack(OP, "intruder") == (False, "unauthorized_security")


def test_describe_reply_dropped_when_messaging_killed_meanwhile():
    """Review A-L4: the kill flipped while the call runs stops the reply."""
    nm, pres = _nm()
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe family room")
    nm._messaging_suppressed = True
    H.run(pres.calls[0]["reply"]("Family Room: 1 person."))
    assert nm._send_reply.await_count == 0
    assert nm.inbound_by_command.get("describe_reply_suppressed") == 1


def test_describe_cooldown_is_per_requester():
    nm, pres = _nm("residents")
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe family room")
        _in(nm, KID, "describe family room")
    assert [c["requester"] for c in pres.calls] == [OP, KID]


def test_describe_without_presence_coordinator_replies_not_running():
    nm, pres = _nm()
    nm.hass.data[C.DOMAIN].pop("coordinator_manager")
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe family room")
    nm._send_reply.assert_awaited_once_with(OP, "imessage", "Interior vision is not running.")


@pytest.mark.parametrize("text", ["describe", "describes family room", "please describe x"])
def test_describe_needs_the_exact_prefix(text):
    nm, pres = _nm()
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, text)
    assert pres.calls == []


def test_scheduled_describe_logs_inbound_and_sends_nothing_yet():
    """Accepted: one inbound row `describe` / `(describing)`, no reply until
    the answer, and the command table never runs (no second reply)."""
    nm, pres = _nm()
    with H.fixed_clock(H.Clock()):
        _in(nm, OP, "describe family room")
    assert nm._send_reply.await_count == 0
    args = nm._test_db.log_inbound.await_args_list[-1].args
    assert (args[0], args[3], args[4]) == (OP, "describe", "(describing)")
    assert nm.inbound_by_command.get("help", 0) == 0

"""WhatsApp inbound payload parsing (NM-WA-INBOUND-KEYS-1).

The installed bridge fires ``whatsapp_message_received`` with
from/to/body/isGroup/fromMe (custom_components/whatsapp/trigger.py:37-56).
Payload shapes below mirror recorder events of 2026-11-07 (digits changed).
The bridge account number is the operator's own NM WhatsApp phone.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import nm_diag_harness as h
from nm_diag_harness import Clock, PERSON, fixed_clock, run
from nm_diag_harness import make_nm as _make_nm

OP = "15125550001"       # bridge account == operator NM phone (real-length 11 digits)
OP_CFG = "+15125550001"
OTHER = "15125559999"


def _evt(**kw):
    base = {"from": f"{OTHER}@c.us", "to": f"{OP}@c.us", "body": "", "timestamp": 1793959620,
            "hasMedia": False, "author": None, "deviceType": None, "isForwarded": False,
            "fromMe": False, "chatName": "", "isGroup": False, "groupId": None}
    base.update(kw)
    return SimpleNamespace(data=base)


def make_nm():
    nm = _make_nm()
    nm._config[h.CONF_NM_PERSONS][0][h.CONF_NM_PERSON_WHATSAPP_PHONE] = OP_CFG
    return nm


@pytest.fixture
def clock():
    c = Clock()
    with fixed_clock(c):
        yield c


def _drive(nm, event):
    """Run the handler; return the coroutines it scheduled (awaited here)."""
    coros = []
    nm.hass.async_create_task = lambda coro, *a, **k: coros.append(coro)
    nm._handle_whatsapp_reply(event)
    return [run(c) for c in coros]


def test_one_to_one_from_person_is_processed(clock):
    """Protects _parse_whatsapp_event's from-digits + body mapping."""
    nm = make_nm()
    out = _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": "15550002@c.us", "body": "status"}))
    assert out == ["URA Alert Status: No active alerts. All clear."]
    assert nm._test_db.log_inbound.call_args.args[:4] == (PERSON, "whatsapp", "status", "status")


def test_device_suffix_jid_is_normalised(clock):
    nm = make_nm()
    out = _drive(nm, _evt(**{"from": f"{OP}:12@c.us", "to": "15550002@c.us", "body": "status"}))
    assert len(out) == 1


def test_unknown_sender_ignored(clock):
    nm = make_nm()
    assert _drive(nm, _evt(body="status")) == []


@pytest.mark.parametrize("payload", [
    {"from": "120363000000@g.us", "to": "120363000000@g.us", "isGroup": True, "author": f"{OP}@c.us"},
    {"from": f"{OP}@c.us", "to": "120363000000@g.us"},  # own group msg, isGroup absent
    {"from": "120363000000@newsletter", "to": "120363000000@newsletter"},
    {"from": f"{OP}@c.us", "to": "status@broadcast"},
])
def test_group_newsletter_broadcast_ignored(clock, payload):
    """Protects the non-direct guard: family group chats never parse."""
    nm = make_nm()
    payload = {**payload, "body": "3"}
    assert _drive(nm, _evt(**payload)) == []
    assert nm._silence_until is None


def test_from_me_to_someone_else_ignored(clock):
    """Operator texting '3' to a family member must not silence alerts."""
    nm = make_nm()
    assert _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": f"{OTHER}@c.us", "fromMe": True, "body": "3"})) == []
    assert nm._silence_until is None


def test_from_me_self_chat_is_processed(clock):
    nm = make_nm()
    out = _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": f"{OP}@c.us", "fromMe": True, "body": "status"}))
    assert out == ["URA Alert Status: No active alerts. All clear."]


def test_from_me_self_chat_echo_of_our_send_dropped(clock):
    """NM's own sends land in the self-chat; echo rail 1 drops them."""
    nm = make_nm()
    nm._notifications_today_count = 1
    run(nm._send_whatsapp("URA", "Unknown command. Reply: 1=Ack", OP_CFG))
    nm.hass.services.async_call.reset_mock()
    out = _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": f"{OP}@c.us", "fromMe": True,
                             "body": "*URA*\nUnknown command. Reply: 1=Ack"}))
    assert out == [""]
    assert nm.hass.services.async_call.call_count == 0


def test_legacy_phone_message_keys_still_work(clock):
    nm = make_nm()
    out = _drive(nm, SimpleNamespace(data={"phone": OP_CFG, "message": "status"}))
    assert len(out) == 1


def test_diag_over_whatsapp_end_to_end(clock):
    nm = make_nm()
    menu = _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": "15550002@c.us", "body": "diag"}))
    assert menu == [h.nm_mod.DIAG_MENU_TEXT]
    out = _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": "15550002@c.us", "body": "1"}))
    assert out[0].startswith("Doors")
    sent = [c.args for c in nm.hass.services.async_call.call_args_list]
    assert [a[0] for a in sent] == ["whatsapp", "whatsapp"]
    assert sent[1][2]["number"] == OP_CFG
    assert [c.args[3] for c in nm._test_db.log_inbound.call_args_list] == ["diag_menu", "diag_doors"]

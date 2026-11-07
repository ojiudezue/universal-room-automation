"""WhatsApp inbound payload parsing (NM-WA-INBOUND-KEYS-1).

The installed bridge fires ``whatsapp_message_received`` with
from/to/body/isGroup/fromMe (custom_components/whatsapp/trigger.py:37-56).
Payload shapes below mirror recorder events of 2026-11-07 (digits changed).
The bridge account number is the operator's own NM WhatsApp phone, so only
the SELF-CHAT (from == to == that phone) is ever parsed (Review A A1).
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
FAMILY = "15125557777"   # a configured NM person's WhatsApp phone
FAMILY_PERSON = "person.jaya"
SELF = {"from": f"{OP}@c.us", "to": f"{OP}@c.us", "fromMe": True}


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


def make_nm_with_family():
    nm = make_nm()
    nm._config[h.CONF_NM_PERSONS].append({
        h.CONF_NM_PERSON_ENTITY: FAMILY_PERSON,
        h.CONF_NM_PERSON_PUSHOVER_KEY: "",
        h.CONF_NM_PERSON_COMPANION_SERVICE: "",
        h.CONF_NM_PERSON_WHATSAPP_PHONE: "+" + FAMILY,
        h.CONF_NM_PERSON_IMESSAGE_HANDLE: "",
        h.CONF_NM_PERSON_DELIVERY_PREF: h.NM_DELIVERY_IMMEDIATE,
    })
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


@pytest.mark.parametrize("text", ["stop", "who", "1", "diag", "status"])
def test_family_direct_chat_never_parsed(clock, text):
    """Protects the self-chat guard (from digits == to digits): a configured
    family member's 1:1 chat to the operator's number is personal."""
    nm = make_nm_with_family()
    nm._notifications_today_count = 3
    out = _drive(nm, _evt(**{"from": f"{FAMILY}@c.us", "to": f"{OP}@c.us", "body": text}))
    assert out == []
    assert nm.hass.services.async_call.call_count == 0
    assert nm._silence_until is None
    assert nm._test_db.log_inbound.call_count == 0


def test_self_chat_diag_works(clock):
    nm = make_nm()
    out = _drive(nm, _evt(**SELF, body="diag"))
    assert out == [h.nm_mod.DIAG_MENU_TEXT]
    assert nm._test_db.log_inbound.call_args.args[:4] == (PERSON, "whatsapp", "diag", "diag_menu")


def test_self_chat_without_from_me_flag_also_works(clock):
    nm = make_nm()
    out = _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": f"{OP}@c.us", "body": "status"}))
    assert out == ["URA Alert Status: No active alerts. All clear."]


def test_device_suffix_jid_is_normalised(clock):
    nm = make_nm()
    out = _drive(nm, _evt(**{"from": f"{OP}:12@c.us", "to": f"{OP}@c.us", "fromMe": True, "body": "status"}))
    assert len(out) == 1


def test_unconfigured_self_chat_ignored(clock):
    """from == to but not a configured NM phone -> no person, ignored."""
    nm = make_nm()
    assert _drive(nm, _evt(**{"from": f"{OTHER}@c.us", "to": f"{OTHER}@c.us", "body": "status"})) == []


@pytest.mark.parametrize("payload", [
    {"from": "120363000000@g.us", "to": "120363000000@g.us", "isGroup": True, "author": f"{OP}@c.us"},
    {"from": f"{OP}@c.us", "to": "120363000000@g.us"},  # own group msg, isGroup absent
    {"from": "120363000000@newsletter", "to": "120363000000@newsletter"},
    {"from": f"{OP}@c.us", "to": "status@broadcast"},
    {"from": f"{OP}@c.us", "to": f"{OP}@c.us", "isGroup": True},
])
def test_group_newsletter_broadcast_ignored(clock, payload):
    """Protects the non-direct guard: family group chats never parse."""
    nm = make_nm()
    payload = {**payload, "body": "3"}
    assert _drive(nm, _evt(**payload)) == []
    assert nm._silence_until is None


def test_group_filter_runs_before_legacy_keys(clock):
    """A7: a legacy-keyed payload that is a group is still ignored."""
    nm = make_nm()
    ev = SimpleNamespace(data={"phone": OP_CFG, "message": "3", "isGroup": True, "to": "1203@g.us"})
    assert _drive(nm, ev) == []
    assert nm._silence_until is None


def test_from_me_to_someone_else_ignored(clock):
    """Operator texting '3' to a family member must not silence alerts."""
    nm = make_nm()
    assert _drive(nm, _evt(**{"from": f"{OP}@c.us", "to": f"{OTHER}@c.us", "fromMe": True, "body": "3"})) == []
    assert nm._silence_until is None


def test_from_me_self_chat_echo_of_our_send_dropped(clock):
    """NM's own sends land in the self-chat; echo rail 1 drops them."""
    nm = make_nm()
    nm._notifications_today_count = 1
    run(nm._send_whatsapp("URA", "Unknown command. Reply: 1=Ack", OP_CFG))
    nm.hass.services.async_call.reset_mock()
    out = _drive(nm, _evt(**SELF, body="*URA*\nUnknown command. Reply: 1=Ack"))
    assert out == [""]
    assert nm.hass.services.async_call.call_count == 0


def test_legacy_phone_message_keys_still_work(clock):
    nm = make_nm()
    out = _drive(nm, SimpleNamespace(data={"phone": OP_CFG, "message": "status"}))
    assert len(out) == 1


def test_kill_switch_ignores_all_whatsapp(clock, monkeypatch):
    """Protects `if not NM_WHATSAPP_INBOUND_ENABLED`."""
    monkeypatch.setattr(h.nm_mod, "NM_WHATSAPP_INBOUND_ENABLED", False)
    nm = make_nm()
    assert _drive(nm, _evt(**SELF, body="status")) == []
    assert _drive(nm, SimpleNamespace(data={"phone": OP_CFG, "message": "status"})) == []


def test_diag_over_whatsapp_end_to_end(clock):
    nm = make_nm()
    menu = _drive(nm, _evt(**SELF, body="diag"))
    assert menu == [h.nm_mod.DIAG_MENU_TEXT]
    out = _drive(nm, _evt(**SELF, body="1"))
    assert out[0].startswith("Doors")
    sent = [c.args for c in nm.hass.services.async_call.call_args_list]
    assert [a[0] for a in sent] == ["whatsapp", "whatsapp"]
    assert sent[1][2]["number"] == OP_CFG
    assert [c.args[3] for c in nm._test_db.log_inbound.call_args_list] == ["diag_menu", "diag_doors"]


def test_replay_of_same_event_is_dropped(clock):
    """Review B LOW-4: protects _is_whatsapp_replay in _handle_whatsapp_reply —
    a bridge replay of the same (from, timestamp, body) never re-applies silence."""
    nm = make_nm()
    first = _drive(nm, _evt(**SELF, body="silence"))
    assert first and first[0].startswith("Non-CRITICAL alerts silenced")
    nm._silence_until = None
    assert _drive(nm, _evt(**SELF, body="silence")) == []
    assert nm._silence_until is None
    # a NEW message (new bridge timestamp) is processed
    assert _drive(nm, _evt(**SELF, body="silence", timestamp=1793959700))


def test_replay_after_ttl_is_processed(clock):
    nm = make_nm()
    _drive(nm, _evt(**SELF, body="status"))
    clock.now = clock.now + __import__("datetime").timedelta(seconds=600)
    assert len(_drive(nm, _evt(**SELF, body="status"))) == 1


def test_dedup_kill_switch_zero(clock, monkeypatch):
    monkeypatch.setattr(h.nm_mod, "NM_WHATSAPP_DEDUP_TTL_S", 0)
    nm = make_nm()
    _drive(nm, _evt(**SELF, body="status"))
    assert len(_drive(nm, _evt(**SELF, body="status"))) == 1

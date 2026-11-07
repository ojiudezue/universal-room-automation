"""NM diag dispatch in _process_inbound_reply (NM-INBOUND-HOUSE-QUERIES-1 D3).

I1b (diag never swallows an alert reply), I2 (read-only), I3 (no echo
loop), I4 (no regression for non-diag text; oracle = NM_DIAG_ENABLED False
arm + the merge-base fixture), I5 (bounded reply), budget, silence, help.
"""
from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest

import nm_diag_harness as h
from nm_diag_harness import (
    AlertState, Clock, PERSON, SAFE_WORD, fixed_clock, make_nm, run,
)

nm_mod = h.nm_mod
DIAG_TOKENS = ["diag", "menu", "house", *nm_mod.DIAG_ITEMS]


@pytest.fixture
def clock():
    c = Clock()
    with fixed_clock(c):
        yield c


def _say(nm, text, channel="imessage", person=PERSON):
    return run(nm._process_inbound_reply(person, channel, text))


def _sent(nm):
    return [c.args for c in nm.hass.services.async_call.call_args_list]


def _critical(nm):
    nm._alert_state = AlertState.ALERTING
    nm._active_alert_data = {"severity": "CRITICAL", "hazard_type": "smoke",
                             "location": "kitchen", "coordinator_id": "safety"}


# --- I4 ------------------------------------------------------------------------

def _record_with(enabled: bool, monkeypatch, text, scenario, channel):
    monkeypatch.setattr(nm_mod, "NM_DIAG_ENABLED", enabled)
    return h.golden_record(text, scenario, channel)


def test_golden_oracle_enabled_false_vs_true(monkeypatch):
    """Every non-diag input: identical return/calls/DB/acks with diag on vs off."""
    diffs = []
    for sc in h.SCENARIOS:
        for ch in h.CHANNELS:
            for t in h.golden_inputs():
                if t in nm_mod.RESPONSE_COMMANDS and nm_mod.RESPONSE_COMMANDS[t] == "help":
                    continue  # help gains the diag line only when enabled (asserted below)
                off = _record_with(False, monkeypatch, t, sc, ch)
                on = _record_with(True, monkeypatch, t, sc, ch)
                if off != on:
                    diffs.append((sc, ch, t))
    assert diffs == []


def test_golden_false_arm_matches_merge_base_fixture(monkeypatch):
    """The False arm really is the pre-cycle code: diff vs the committed capture."""
    with open(h.FIXTURE, encoding="utf-8") as fh:
        fixture = json.load(fh)
    assert len(fixture["_merge_base_sha"]) == 40
    diffs = []
    for key, expected in fixture["records"].items():
        sc, ch, t = key.split("|", 2)
        got = json.loads(json.dumps(_record_with(False, monkeypatch, t, sc, ch), sort_keys=True, default=str))
        if got != expected:
            diffs.append(key)
    assert diffs == []


def test_non_diag_inputs_byte_identical_golden(monkeypatch):
    """Diag ON vs the merge-base fixture for every non-help golden input."""
    with open(h.FIXTURE, encoding="utf-8") as fh:
        records = json.load(fh)["records"]
    diffs = []
    for key, expected in records.items():
        sc, ch, t = key.split("|", 2)
        if nm_mod.RESPONSE_COMMANDS.get(t) == "help":
            continue
        got = json.loads(json.dumps(_record_with(True, monkeypatch, t, sc, ch), sort_keys=True, default=str))
        if got != expected:
            diffs.append(key)
    assert diffs == []


def test_help_mentions_diag_and_alert_body_unchanged(clock):
    nm = make_nm()
    assert _say(nm, "help") == "Reply: 1=Ack  2=Status  3=Silence\ndiag = house status menu"
    assert nm_mod.RESPONSE_DICT_TEXT == "Reply: 1=Ack  2=Status  3=Silence"


# --- I1b -----------------------------------------------------------------------

def test_doors_then_safe_word_20s_confirmation_sent(clock):
    """Protects `rail2=False` in _handle_diag -> _log_and_reply and the
    `if person_id and not rail2` branch (no _last_reply_at stamp)."""
    nm = make_nm()
    _say(nm, "doors")
    _critical(nm)
    clock.now += timedelta(seconds=20)
    n = len(_sent(nm))
    ret = _say(nm, SAFE_WORD)
    assert ret.startswith("CRITICAL alert acknowledged")
    msgs = [a[2]["message"] for a in _sent(nm)[n:]]
    assert msgs == ["URA\n" + ret]


def test_doors_then_silence_20s_confirmation_sent(clock):
    nm = make_nm()
    _say(nm, "doors", channel="whatsapp")
    clock.now += timedelta(seconds=20)
    n = len(_sent(nm))
    ret = _say(nm, "silence", channel="whatsapp")
    assert [a[2]["message"] for a in _sent(nm)[n:]] == ["*URA*\n" + ret]


def test_doors_then_ack_20s_confirmation_sent(clock):
    nm = make_nm()
    _say(nm, "doors")
    _critical(nm)
    clock.now += timedelta(seconds=20)
    n = len(_sent(nm))
    ret = _say(nm, "ack")
    assert [a[2]["message"] for a in _sent(nm)[n:]] == ["URA\n" + ret]


def test_diag_reply_does_not_stamp_last_reply_at(clock):
    nm = make_nm()
    for t in ["diag", "1", "garage", "who"]:
        _say(nm, t)
    assert nm._last_reply_at == {}


def test_legacy_reply_still_rate_limited(clock):
    """rail 2 unchanged for non-diag: two 'status' within 30 s -> one send."""
    nm = make_nm()
    _say(nm, "status")
    clock.now += timedelta(seconds=10)
    _say(nm, "status")
    assert len(_sent(nm)) == 1


# --- silence / safe word / auth ------------------------------------------------

def test_diag_answers_while_silenced(clock):
    """Protects `and diag is None` in the silence gate."""
    nm = make_nm()
    nm._silence_until = clock.now + timedelta(minutes=10)
    assert _say(nm, "doors").startswith("Doors")


def test_safe_word_beats_diag_name(clock):
    """Protects `is_safe_word or` in the step-4 guard: a safe word equal to a
    diag token never resolves diag (no answer, and no window side effect)."""
    nm = h.make_nm()
    nm._config[h.CONF_NM_SAFE_WORD] = "doors"
    _critical(nm)
    assert _say(nm, "doors").startswith("CRITICAL alert acknowledged")
    nm2 = h.make_nm()
    nm2._config[h.CONF_NM_SAFE_WORD] = "diag"
    assert _say(nm2, "diag") == "No active alert to acknowledge."
    assert nm2._diag_windows == {}
    assert nm2._inbound_by_command["diag"] == 0


def test_kill_switch_disables_diag(clock, monkeypatch):
    """Protects `or not NM_DIAG_ENABLED`: off -> diag tokens take the legacy path."""
    monkeypatch.setattr(nm_mod, "NM_DIAG_ENABLED", False)
    nm = make_nm()
    nm._notifications_today_count = 1
    assert _say(nm, "doors").startswith("Unknown command")
    assert _say(nm, "diag").startswith("Unknown command")
    assert nm._diag_windows == {}


def test_unknown_sender_gets_nothing(clock):
    """BB webhook drops unknown handles before parsing (allowlist reused)."""
    nm = make_nm()
    nm._match_person_by_imessage_handle = lambda handle: None
    req = h.MagicMock()

    async def _json():
        return {"type": "new-message", "data": {"isFromMe": False, "text": "doors",
                                                "handle": {"address": "stranger@x"}}}

    req.json = _json
    run(nm._handle_bb_webhook(nm.hass, "wid", req))
    assert _sent(nm) == []
    assert nm._test_db.log_inbound.call_count == 0


# --- budget --------------------------------------------------------------------

def test_rate_exempt_and_budget(clock):
    nm = make_nm()
    for i in range(10):  # 10 replies inside 600 s, 1 s apart: all answered
        assert _say(nm, "diag") != ""
        clock.now += timedelta(seconds=1)
    assert len(_sent(nm)) == 10
    ret = _say(nm, "doors")  # 11th -> one over-budget reply
    assert ret.startswith("Too many requests")
    assert len(_sent(nm)) == 11
    assert _say(nm, "doors") == ""  # then silence, row still logged
    assert len(_sent(nm)) == 11
    assert nm._test_db.log_inbound.call_args_list[-1].args[3] == "diag_rate_limited"
    clock.now += timedelta(seconds=600)
    assert _say(nm, "doors").startswith("Doors")


# --- I2 ------------------------------------------------------------------------

@pytest.mark.parametrize("channel", ["imessage", "whatsapp", "pushover"])
def test_diag_tokens_call_no_service_but_reply(clock, channel):
    expected_domain = {"imessage": "bluebubbles", "whatsapp": "whatsapp", "pushover": "notify"}[channel]
    for tok in DIAG_TOKENS + ["1", "7", "9"]:
        nm = make_nm()
        nm._notifications_today_count = 1
        if tok.isdigit():
            _say(nm, "diag", channel=channel)
        nm.hass.services.async_call.reset_mock()
        nm._test_db.log_inbound.reset_mock()
        before = (nm._silence_until, nm._alert_state, dict(nm._last_reply_at),
                  nm._perimeter_silence_until)
        ret = _say(nm, tok, channel=channel)
        calls = _sent(nm)
        assert len(calls) == 1 and calls[0][0] == expected_domain, (tok, calls)
        assert nm._test_db.log_inbound.call_count == 1
        assert nm._test_db.log_inbound.call_args.args[3].startswith("diag_"), tok
        assert nm.async_acknowledge.call_count == 0
        assert nm._test_created_tasks == []
        assert (nm._silence_until, nm._alert_state, dict(nm._last_reply_at),
                nm._perimeter_silence_until) == before
        assert ret


def test_closed_notice_is_read_only(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    run(nm._send_imessage("Alert", "x", "op@example.com"))
    nm.hass.services.async_call.reset_mock()
    before = nm._silence_until
    assert _say(nm, "3") == nm_mod.DIAG_CLOSED_NOTICE_TEXT
    assert len(_sent(nm)) == 1 and nm._silence_until == before


# --- I3 + I5 -------------------------------------------------------------------

def test_echoed_reply_never_parses(clock):
    replies = []
    for tok in DIAG_TOKENS + ["8"]:
        nm = make_nm()  # fresh per token (stay inside the diag budget)
        if tok == "8":
            _say(nm, "diag")
        replies.append(_say(nm, tok))
        clock.now += timedelta(seconds=1)
    for body in replies:
        for prefixed in ("URA\n" + body, "*URA*\n" + body, body):
            nm2 = make_nm()
            nm2._notifications_today_count = 0
            _say(nm2, "diag")  # an open window must not make an echo parse either
            nm2.hass.services.async_call.reset_mock()
            nm2._recent_outbound_texts.clear()
            assert "\n" in prefixed
            assert _say(nm2, prefixed) == ""
            assert _sent(nm2) == []


def test_reply_bounded(clock, monkeypatch):
    nm = make_nm()
    from custom_components.universal_room_automation import house_status as hs
    many = [hs.Field(f"room {i}", "unavailable", problem=True) for i in range(300)]
    monkeypatch.setattr(hs, "health", lambda hass: hs.StatusResult("health", clock.now, many, 300))
    ret = _say(nm, "health", channel="whatsapp")
    sent = _sent(nm)[0][2]["message"]
    assert len(sent) <= 900
    assert ret.endswith("…(more: health)")


def test_rate_limited_notice_does_not_stamp_rail2(clock):
    """Review C F1: protects rail2=False on the diag_rate_limited notice in
    _handle_diag: the over-budget reply must not swallow a later safe-word
    confirmation inside NM_REPLY_MIN_INTERVAL_S."""
    nm = make_nm()
    for _ in range(10):
        _say(nm, "diag")
        clock.now += timedelta(seconds=1)
    assert _say(nm, "doors").startswith("Too many requests")
    assert nm._last_reply_at == {}
    _critical(nm)
    clock.now += timedelta(seconds=5)
    n = len(_sent(nm))
    ret = _say(nm, SAFE_WORD)
    assert ret.startswith("CRITICAL alert acknowledged")
    assert [a[2]["message"] for a in _sent(nm)[n:]] == ["URA\n" + ret]

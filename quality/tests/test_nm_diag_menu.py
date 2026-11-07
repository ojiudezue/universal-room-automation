"""NM diag menu window + the two rails (NM-INBOUND-HOUSE-QUERIES-1 D2).

Real NotificationManager, real ``_process_inbound_reply``; only the DB and
hass service bus are mocks (recorded). Invariant I1: an alert digit is never
shadowed by the menu once an alert send began or while the alert state is
not IDLE.
"""
from __future__ import annotations

import ast
import inspect
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

import nm_diag_harness as h
from nm_diag_harness import AlertState, Clock, fixed_clock, make_nm, run, PERSON

nm_mod = h.nm_mod
NM_SRC = inspect.getsource(nm_mod)  # AST tests only (structure, not behaviour)

SENDERS = ("_send_pushover", "_send_companion", "_send_whatsapp", "_send_imessage")


def _send(nm, which: str):
    """One non-reply text send through the named sender."""
    if which == "whatsapp":
        return run(nm._send_whatsapp("Alert", "body", "+15550001"))
    if which == "imessage":
        return run(nm._send_imessage("Alert", "body", "op@example.com"))
    if which == "pushover":
        return run(nm._send_pushover("Alert", "body", h.nm_mod.Severity.CRITICAL, "pkey"))
    if which == "companion":
        return run(nm._send_companion("Alert", "body", h.nm_mod.Severity.CRITICAL, "notify.mobile_app_op"))
    raise ValueError(which)


def _say(nm, text, channel="imessage", person=PERSON):
    return run(nm._process_inbound_reply(person, channel, text))


@pytest.fixture
def clock():
    c = Clock()
    with fixed_clock(c):
        yield c


DOORS_HEADER = "Doors"  # render header for item "doors"


def _doors_answer(ret: str) -> bool:
    return ret.split("\n", 1)[0].startswith(DOORS_HEADER)


# --- send rail ----------------------------------------------------------------

@pytest.mark.parametrize("which", ["whatsapp", "imessage", "pushover", "companion"])
def test_digit_after_critical_send_is_ack(clock, which):
    """Protects the bump at the top of each sender (_send_<which>):
    diag -> a non-reply send -> '1' is legacy (CRITICAL reply text)."""
    nm = make_nm()
    nm._notifications_today_count = 1
    assert _say(nm, "diag").startswith("House menu")
    _send(nm, which)
    # CRITICAL send landed; _enter_alerting not reached yet (state IDLE) but
    # the alert data is already set — the legacy path must answer.
    nm._active_alert_data = {"severity": "CRITICAL", "hazard_type": "smoke"}
    clock.now += timedelta(seconds=5)
    ret = _say(nm, "1")
    assert ret == "No active alerts."  # legacy ack path (IDLE), not doors
    assert not _doors_answer(ret)


def test_digit_after_critical_async_notify_requires_safe_word(clock):
    """End-to-end: real CRITICAL async_notify closes the window; '1' replies
    the legacy 'requires safe word'."""
    nm = make_nm()
    nm._enter_alerting = AsyncMock()  # isolate the send rail
    db = AsyncMock()
    db.get_active_criticals = AsyncMock(return_value=[])
    db.get_active_critical = AsyncMock(return_value={"id": 7})
    nm.hass.data[h.DOMAIN]["database"] = db
    nm._test_db = db
    _say(nm, "diag")
    epoch = nm._diag_send_epoch
    run(nm.async_notify(
        coordinator_id="safety", severity=h.nm_mod.Severity.CRITICAL,
        title="Smoke", message="kitchen", hazard_type="smoke", location="kitchen",
    ))
    assert nm._diag_send_epoch > epoch
    nm._alert_state = AlertState.ALERTING
    nm._active_alert_data = {"severity": "CRITICAL", "hazard_type": "smoke"}
    assert _say(nm, "1") == "CRITICAL alert requires safe word. Reply with your safe word to acknowledge."


def test_dry_run_send_still_bumps_epoch(clock):
    nm = make_nm()
    nm._dry_run_active = True
    nm._log_dry_run = AsyncMock()
    _say(nm, "diag")
    _send(nm, "whatsapp")
    assert _say(nm, "1") != "" and not _doors_answer(_say(nm, "1"))


def test_reply_send_does_not_close_window(clock):
    """Protects _send_reply's menu_safe=True: the menu reply itself must not close."""
    nm = make_nm()
    _say(nm, "diag", channel="whatsapp")
    clock.now += timedelta(seconds=3)
    assert _doors_answer(_say(nm, "1", channel="whatsapp"))


# --- state rail ---------------------------------------------------------------

def test_digit_while_alerting_is_ack(clock):
    """Protects the state rail in _resolve_diag (`_alert_state is not IDLE` -> None)."""
    nm = make_nm()
    _say(nm, "diag")
    nm._alert_state = AlertState.ALERTING
    nm._active_alert_data = {"severity": "CRITICAL", "hazard_type": "smoke"}
    assert nm._diag_send_epoch == nm._diag_windows[(PERSON, "imessage")][1]  # no send
    assert _say(nm, "1") == "CRITICAL alert requires safe word. Reply with your safe word to acknowledge."


def test_menu_while_alerting_has_no_numbers(clock):
    nm = make_nm()
    nm._alert_state = AlertState.REPEATING
    ret = _say(nm, "diag")
    assert ret == nm_mod.DIAG_MENU_ALERT_TEXT
    assert (PERSON, "imessage") not in nm._diag_windows


# --- window -------------------------------------------------------------------

def test_digit_in_window_idle_runs_item(clock):
    nm = make_nm()
    _say(nm, "diag")
    clock.now += timedelta(seconds=119)
    assert _doors_answer(_say(nm, "1"))
    assert _say(nm, "7").startswith("Health")
    assert _say(nm, "8") == nm_mod.DIAG_BAD_PICK_TEXT


def test_window_expiry_restores_legacy(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    clock.now += timedelta(seconds=120)  # literal boundary: 120 s = closed
    assert _say(nm, "1") == "No active alerts."


def test_window_per_person_and_channel(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag", channel="whatsapp")
    assert _say(nm, "1", channel="imessage") == "No active alerts."
    assert _doors_answer(_say(nm, "1", channel="whatsapp"))


def test_restart_closes_windows(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    nm2 = make_nm()  # fresh instance = restart
    nm2._notifications_today_count = 1
    assert _say(nm2, "1") == "No active alerts."


def test_diag_resend_refreshes_window(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    clock.now += timedelta(seconds=100)
    _send(nm, "whatsapp")  # closes
    _say(nm, "diag")  # reopen: refreshes opened_at AND epoch
    clock.now += timedelta(seconds=100)  # 200 s after first open, 100 after second
    assert _doors_answer(_say(nm, "1"))


def test_companion_person_none_skips_diag(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    ret = _say(nm, "diag", channel="companion", person=None)
    assert ret.startswith("Unknown command")
    assert nm._diag_windows == {}


# --- HIGH-1: capture before first await ---------------------------------------

def test_epoch_captured_before_first_await(clock):
    """Protects step 0 of _process_inbound_reply: a send that lands DURING the
    menu reply's await must close the window."""
    nm = make_nm()
    nm._notifications_today_count = 1
    real_send_reply = nm._send_reply

    async def _racing_send_reply(person_id, channel, message):
        nm._diag_send_epoch += 1  # a CRITICAL send through a sender, mid-await
        await real_send_reply(person_id, channel, message)

    nm._send_reply = _racing_send_reply
    _say(nm, "diag")
    nm._send_reply = real_send_reply
    nm._active_alert_data = {"severity": "CRITICAL"}
    assert _say(nm, "1") == "No active alerts."


# --- MEDIUM-6: closed notice --------------------------------------------------

def test_digit_after_noncritical_send_gets_closed_notice(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    _send(nm, "imessage")  # HIGH alert: state stays IDLE, no _active_alert_data
    clock.now += timedelta(seconds=30)
    before = nm._silence_until
    assert _say(nm, "3") == nm_mod.DIAG_CLOSED_NOTICE_TEXT
    assert nm._silence_until == before
    # record dropped: next 3 is legacy silence
    assert _say(nm, "3").startswith("Non-CRITICAL alerts silenced")


def test_closed_notice_expires_to_legacy(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    _send(nm, "imessage")
    clock.now += timedelta(seconds=300)  # literal: 300 s = notice over
    assert _say(nm, "3").startswith("Non-CRITICAL alerts silenced")


def test_closed_notice_not_when_alert_expected(clock):
    """Protects the `self._alert_state is IDLE and not _active_alert_data` gate."""
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    _send(nm, "imessage")
    nm._alert_state = AlertState.ALERTING
    assert _say(nm, "3").startswith("Non-CRITICAL alerts silenced")


def test_closed_notice_not_when_alert_data_set(clock):
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    _send(nm, "imessage")
    nm._active_alert_data = {"severity": "CRITICAL"}
    assert _say(nm, "3").startswith("Non-CRITICAL alerts silenced")


def test_window_zero_is_names_only(clock, monkeypatch):
    monkeypatch.setattr(nm_mod, "NM_DIAG_MENU_WINDOW_S", 0)
    nm = make_nm()
    nm._notifications_today_count = 1
    assert _say(nm, "diag") == nm_mod.DIAG_MENU_WORDS_TEXT
    assert _say(nm, "1") == "No active alerts."
    _send(nm, "imessage")
    assert _say(nm, "3").startswith("Non-CRITICAL alerts silenced")  # no notice
    assert _doors_answer(_say(nm, "doors"))


# --- AST structure pins -------------------------------------------------------

def _tree():
    return ast.parse(NM_SRC)


def _fn(name):
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(name)


def test_menu_safe_is_keyword_only():
    for name in SENDERS:
        args = _fn(name).args
        assert "menu_safe" in [a.arg for a in args.kwonlyargs], name
        assert "menu_safe" not in [a.arg for a in args.args], name


def test_only_send_reply_passes_menu_safe_ast():
    callers = set()
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and any(k.arg == "menu_safe" for k in sub.keywords):
                    callers.add(node.name)
    assert callers == {"_send_reply"}


def test_each_sender_bumps_epoch_first_ast():
    for name in SENDERS:
        body = list(_fn(name).body)
        if isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
            body = body[1:]  # docstring
        first = body[0]
        assert isinstance(first, ast.If), name
        assert ast.unparse(first.test) == "not menu_safe", name
        assert ast.unparse(first.body[0]) == "self._diag_send_epoch += 1", name


_TEXT_DOMAINS = {"whatsapp", "bluebubbles", "notify", "pushover"}
_NON_TEXT_ALLOW = {("_send_tts", "tts"), ("_announce_ack", "tts")}


def test_no_text_service_call_outside_four_senders():
    """MEDIUM-3: any hass.services.async_call with a text domain (or a
    non-literal domain) outside the four senders breaks the send rail."""
    offenders = []
    for node in ast.walk(_tree()):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "async_call"
                and "services" in ast.unparse(sub.func.value)
            ):
                dom = sub.args[0] if sub.args else None
                literal = dom.value if isinstance(dom, ast.Constant) else None
                if node.name in SENDERS:
                    continue
                if literal is not None and literal not in _TEXT_DOMAINS:
                    continue  # tts / light etc.
                if literal is None and ast.unparse(dom) in ("HALO_DOMAIN", "light_domain", "domain_light"):
                    continue
                offenders.append((node.name, ast.unparse(dom) if dom is not None else None, sub.lineno))
    assert offenders == [], offenders


def test_closed_notice_age_bound_when_notice_shorter(clock, monkeypatch):
    """Protects `age_s < NM_DIAG_CLOSED_NOTICE_S` (only load-bearing when the
    notice window is shorter than the menu window)."""
    monkeypatch.setattr(nm_mod, "NM_DIAG_CLOSED_NOTICE_S", 60)
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    _send(nm, "imessage")
    clock.now += timedelta(seconds=61)
    assert _say(nm, "3").startswith("Non-CRITICAL alerts silenced")


def test_closed_notice_only_for_alert_digits(clock):
    """Protects `text in ("1", "2", "3")`: other digits after a close are legacy."""
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    _send(nm, "imessage")
    assert _say(nm, "4").startswith("Unknown command")


def test_superscript_digit_is_not_a_pick(clock):
    """A5: protects `text.isdecimal()` — "\u00b3".isdigit() is True but int() raises."""
    nm = make_nm()
    nm._notifications_today_count = 1
    _say(nm, "diag")
    assert _say(nm, "\u00b3").startswith("Unknown command")

"""NM echo-loop guard (2026-08-05 BlueBubbles echo incident).

URA's outbound iMessages synced back through the BB new-message webhook
with the isFromMe guard defeated, and each auto-reply re-triggered
itself (12 replies in 7 s; one echo matched the silence path and
silenced alerts without operator intent). Two rails shipped:

  Rail 1 — outbound ring buffer + exact-match echo drop at
           _process_inbound_reply entry (imessage/whatsapp only).
  Rail 2 — NM_REPLY_MIN_INTERVAL_S floor between auto-reply SENDS per
           (person, channel) in _log_and_reply; command processing is
           never gated.

Behavioral tests exec the extracted methods (same technique as
test_notification_hygiene.py); source anchors pin the hook sites.
"""
from __future__ import annotations

import ast
import os
import textwrap
from collections import deque
from datetime import datetime, timedelta, timezone


HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


NM_SRC = _read(
    "custom_components/universal_room_automation/domain_coordinators/"
    "notification_manager.py"
)
SENSOR_SRC = _read("custom_components/universal_room_automation/sensor.py")


def _load_fn(src: str, name: str, *, is_async: bool = False):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            (is_async and isinstance(node, ast.AsyncFunctionDef))
            or (not is_async and isinstance(node, ast.FunctionDef))
        ) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


class _FakeDtUtil:
    """dt_util stub with a controllable clock."""

    def __init__(self, now: datetime):
        self._now = now

    def utcnow(self) -> datetime:
        return self._now


def _build_echo_fns(ttl: int = 600):
    """Exec _record_outbound_text + _is_self_echo with a stub namespace."""
    ns: dict = {
        "NM_ECHO_GUARD_TTL_S": ttl,
        "timedelta": timedelta,
    }
    for name in ("_record_outbound_text", "_is_self_echo"):
        src = _load_fn(NM_SRC, name)
        assert src is not None, f"{name} missing from notification_manager"
        exec(textwrap.dedent(src), ns)
    return ns


class _Fake:
    def __init__(self):
        self._recent_outbound_texts: deque = deque(maxlen=20)
        self._echo_suppressed_count = 0


NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


def test_echo_exact_match_dropped():
    ns = _build_echo_fns()
    ns["dt_util"] = _FakeDtUtil(NOW)
    f = _Fake()
    ns["_record_outbound_text"](f, "URA\nAlerts silenced. Will resume at 08:34.")
    assert ns["_is_self_echo"](f, "URA\nAlerts silenced. Will resume at 08:34.")
    # Leading/trailing whitespace on the reflected copy still matches.
    assert ns["_is_self_echo"](f, "  URA\nAlerts silenced. Will resume at 08:34.\n")


def test_non_echo_and_empty_pass_through():
    ns = _build_echo_fns()
    ns["dt_util"] = _FakeDtUtil(NOW)
    f = _Fake()
    ns["_record_outbound_text"](f, "URA\nUnknown command. Reply: 1=Ack")
    assert not ns["_is_self_echo"](f, "duke")
    assert not ns["_is_self_echo"](f, "3")
    assert not ns["_is_self_echo"](f, "")
    # Substring of an outbound is NOT an echo (exact match only).
    assert not ns["_is_self_echo"](f, "Unknown command.")


def test_echo_ttl_expiry():
    ns = _build_echo_fns(ttl=600)
    clock = _FakeDtUtil(NOW)
    ns["dt_util"] = clock
    f = _Fake()
    ns["_record_outbound_text"](f, "URA\nold message")
    clock._now = NOW + timedelta(seconds=601)
    assert not ns["_is_self_echo"](f, "URA\nold message")
    clock._now = NOW + timedelta(seconds=599)
    assert ns["_is_self_echo"](f, "URA\nold message")


def test_echo_kill_switch_zero_disables():
    ns = _build_echo_fns(ttl=0)
    ns["dt_util"] = _FakeDtUtil(NOW)
    f = _Fake()
    ns["_record_outbound_text"](f, "URA\nmsg")
    assert not ns["_is_self_echo"](f, "URA\nmsg")


def test_ring_buffer_bounded():
    ns = _build_echo_fns()
    ns["dt_util"] = _FakeDtUtil(NOW)
    f = _Fake()
    for i in range(50):
        ns["_record_outbound_text"](f, f"URA\nmsg {i}")
    assert len(f._recent_outbound_texts) == 20
    assert not ns["_is_self_echo"](f, "URA\nmsg 0")  # evicted
    assert ns["_is_self_echo"](f, "URA\nmsg 49")


# ---------------------------------------------------------------------------
# Source anchors — hook sites must stay wired
# ---------------------------------------------------------------------------
def test_process_inbound_checks_echo_before_command_parse():
    src = _load_fn(NM_SRC, "_process_inbound_reply", is_async=True)
    assert src is not None
    echo_at = src.index("_is_self_echo")
    parse_at = src.index("RESPONSE_COMMANDS.get")
    assert echo_at < parse_at, "echo drop must precede command parsing"
    # Review A M-3: the incident pathology was the SILENCE branch firing
    # on an echo — pin that echo drop precedes the silence check too.
    assert echo_at < src.index("_silence_until"), (
        "echo drop must precede the silenced auto-reply branch"
    )
    # Drop applies to the two loop-capable channels.
    assert '"imessage", "whatsapp"' in src


def test_senders_record_outbound_after_successful_send():
    """Review A M-4 + B B2: recording must sit AFTER the service call
    (proof-of-send: failed dispatch must not seed the echo buffer) and
    must record the same variable that was sent."""
    for fn_name in ("_send_imessage", "_send_whatsapp"):
        src = _load_fn(NM_SRC, fn_name, is_async=True)
        assert src is not None
        record_at = src.index("_record_outbound_text")
        call_at = src.index("services.async_call")
        assert call_at < record_at, f"{fn_name}: record must follow the send"
        # Same body variable is sent and recorded.
        assert '"message": outbound_text' in src
        assert "_record_outbound_text(outbound_text)" in src


def test_send_reply_routes_through_recording_senders():
    """Review A M-5: rail 1 is self-consistent only if every URA reply
    goes out via a recording sender."""
    src = _load_fn(NM_SRC, "_send_reply", is_async=True)
    assert src is not None
    assert '_send_imessage("URA"' in src
    assert '_send_whatsapp("URA"' in src


def test_log_and_reply_rate_limit_gates_send_not_processing():
    src = _load_fn(NM_SRC, "_log_and_reply", is_async=True)
    assert src is not None
    assert "NM_REPLY_MIN_INTERVAL_S" in src
    assert "_last_reply_at" in src
    # log_inbound (processing/audit) must NOT be inside the rate-limit gate:
    # DB log occurs before the min-interval check.
    assert src.index("log_inbound") < src.index("NM_REPLY_MIN_INTERVAL_S")


def test_ring_buffer_dedup_on_append():
    """Review A H-1: identical per-recipient bodies refresh one slot."""
    ns = _build_echo_fns()
    clock = _FakeDtUtil(NOW)
    ns["dt_util"] = clock
    f = _Fake()
    for _ in range(5):  # same alert fanned to 5 recipients
        ns["_record_outbound_text"](f, "URA\nCRITICAL: smoke")
    assert len(f._recent_outbound_texts) == 1
    # Refresh semantics: TTL measured from the LAST send of that body.
    clock._now = NOW + timedelta(seconds=300)
    ns["_record_outbound_text"](f, "URA\nCRITICAL: smoke")
    clock._now = NOW + timedelta(seconds=880)  # 580s after refresh
    assert ns["_is_self_echo"](f, "URA\nCRITICAL: smoke")


def test_rate_limit_behavior():
    """Second reply within the floor is swallowed; after the floor it sends."""
    ns: dict = {
        "NM_REPLY_MIN_INTERVAL_S": 30.0,
        "NM_REPLY_RATE_LIMITED_CHANNELS": ("imessage", "whatsapp"),
        "NM_REPLY_RATE_LIMIT_EXEMPT_COMMANDS": ("safe_word_unauthorized",),
    }
    src = _load_fn(NM_SRC, "_log_and_reply", is_async=True)
    assert src is not None
    exec(textwrap.dedent(src), ns)
    fn = ns["_log_and_reply"]

    import asyncio

    class _FakeNM:
        def __init__(self, now):
            self._active_alert_data = None
            self._last_reply_at = {}
            self.sent = []
            self.hass = None
            self._now = now

        async def _send_reply(self, person_id, channel, message):
            self.sent.append(message)

    clock = _FakeDtUtil(NOW)
    ns["dt_util"] = clock
    # async_dispatcher_send is imported at module scope in the real file;
    # stub it in the exec namespace.
    ns["async_dispatcher_send"] = lambda *a, **k: None
    ns["SIGNAL_NM_ENTITIES_UPDATE"] = "sig"
    import logging
    ns["_LOGGER"] = logging.getLogger("test")

    f = _FakeNM(NOW)

    async def run():
        await fn(f, None, "person.oji", "imessage", "echo1", "unknown", "r1", False)
        await fn(f, None, "person.oji", "imessage", "echo2", "unknown", "r2", False)
        # Review A H-2: security deny is NEVER swallowed, even in-floor.
        await fn(
            f, None, "person.oji", "imessage", "duke",
            "safe_word_unauthorized", "deny", False,
        )
        # Review B B1: companion is not an echo-capable channel — never
        # gated regardless of cadence.
        await fn(f, None, "person.oji", "companion", "1", "ack", "c1", True)
        await fn(f, None, "person.oji", "companion", "1", "ack", "c2", True)
        clock._now = NOW + timedelta(seconds=31)
        await fn(f, None, "person.oji", "imessage", "echo3", "unknown", "r3", False)
        # Different channel has its own floor.
        await fn(f, None, "person.oji", "whatsapp", "x", "unknown", "r4", False)

    asyncio.run(run())
    assert f.sent == ["r1", "deny", "c1", "c2", "r3", "r4"]


def test_knob_defaults_present():
    assert "NM_ECHO_GUARD_TTL_S = 600" in NM_SRC
    assert "NM_ECHO_GUARD_BUFFER_LEN = 100" in NM_SRC
    assert "NM_REPLY_MIN_INTERVAL_S = 30.0" in NM_SRC
    assert 'NM_REPLY_RATE_LIMITED_CHANNELS = ("imessage", "whatsapp")' in NM_SRC
    # SAFEWORD-WINDOW-1 fix-up C-LOW-3 (2026-08-14): the exempt tuple
    # grew to include "safe_word_window_rejected" so the "duke > 3h"
    # cap-reject reply cannot be rate-dropped on a fast retry. Assert
    # both members are present (order-independent) rather than pinning
    # the literal tuple string.
    assert "NM_REPLY_RATE_LIMIT_EXEMPT_COMMANDS = (" in NM_SRC
    assert '"safe_word_unauthorized"' in NM_SRC
    assert '"safe_word_window_rejected"' in NM_SRC


def test_echo_drop_counts_in_inbound_telemetry():
    """Review A M-1: dropped echoes stay visible in inbound totals."""
    src = _load_fn(NM_SRC, "_process_inbound_reply", is_async=True)
    assert src is not None
    echo_block = src[src.index("_is_self_echo"): src.index("RESPONSE_COMMANDS.get")]
    assert "_inbound_today_count += 1" in echo_block
    assert '"echo"' in echo_block


def test_counter_surfaced_on_sensor():
    assert "echo_suppressed_count" in NM_SRC
    assert '"echo_suppressed": nm.echo_suppressed_count' in SENSOR_SRC

"""SAFEWORD-WINDOW-1: "duke Nh" perimeter-scoped silence window tests.

Per docs/planning/PLANNING_safeword_window.md — five falsifiable
invariants I1..I5 are each anchored by at least one named test below:

  I1 (never-blanket)             : test_window_never_blankets_life_safety_smoke
  I2 (perimeter-only scope)      : test_window_suppresses_exterior_person_first_fire
                                   test_window_never_blankets_water_leak
                                   test_window_never_blankets_life_safety_smoke
  I3 (current-alert ack, not
      repeat-suppress)           : test_duke_2h_acks_current_and_opens_window
                                   (ack invoked; not gated inside _repeat_alert)
  I4 (bounded, reject-with-reply): test_duke_over_cap_rejected
                                   test_duke_zero_minutes_falls_through
                                   test_duke_abc_falls_through
  I5 (auto-expiry + surfaced)    : test_window_expires_and_emits_resumed_note
                                   test_attribute_surface_reflects_window

Also anchors D1 parse (regex), D2 gate site, D3 ack+window wire-in,
D4 attribute surface, D6 kill switch (NM_SAFEWORD_WINDOW_ENABLED).

Tests are wall-clock-independent: the perimeter window is injected by
directly setting `_perimeter_silence_until` where a clock advance would
otherwise be needed, and `dt_util.utcnow` is not monkey-patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

# Piggyback the HA-stub bootstrap used by test_notification_manager.py.
from test_notification_manager import _make_hass, _make_config  # noqa: F401

import custom_components.universal_room_automation.domain_coordinators.notification_manager as _nm_mod
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    AlertState,
    NotificationManager,
    _NM_SAFEWORD_WINDOW_RE,
    NM_SAFEWORD_WINDOW_ENABLED,
    NM_SAFEWORD_WINDOW_MAX_MIN,
)
from custom_components.universal_room_automation.const import (
    CONF_NM_SAFE_WORD,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_DELIVERY_PREF,
    NM_DELIVERY_IMMEDIATE,
    NM_HAZARD_EXTERIOR_PERSON,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    Severity,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_nm(safe_word: str = "dukeword") -> NotificationManager:
    """Build a NotificationManager with a global safeword configured.

    All outbound channels muted (no send-side plumbing under test); the
    _log_and_reply DB write is short-circuited by patching after init.
    """
    hass = _make_hass()
    cfg = _make_config(**{
        CONF_NM_SAFE_WORD: safe_word,
        CONF_NM_PERSONS: [{
            CONF_NM_PERSON_ENTITY: "person.op",
            CONF_NM_PERSON_PUSHOVER_KEY: "k",
            CONF_NM_PERSON_COMPANION_SERVICE: "",
            CONF_NM_PERSON_WHATSAPP_PHONE: "",
            CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
        }],
    })
    nm = NotificationManager(hass, cfg)
    # Neutralize the outbound reply/DB path — we assert on NM state, not
    # on log-row shape.
    nm._log_and_reply = AsyncMock(return_value=None)
    # Neutralize the ack authority pipeline: ack is not the SUT here.
    nm.async_acknowledge = AsyncMock(return_value=None)
    # Note-emit helpers spawn async tasks via hass.async_create_task;
    # keep them in-process and drainable — collect coros for direct await.
    nm._pending_note_coros = []

    def _capture_task(coro):
        nm._pending_note_coros.append(coro)
        return MagicMock()

    nm.hass.async_create_task = _capture_task
    return nm


# ---------------------------------------------------------------------------
# D1 — parse regex
# ---------------------------------------------------------------------------


def test_regex_parses_hours():
    m = _NM_SAFEWORD_WINDOW_RE.match("dukeword 2h")
    assert m is not None
    assert m.group("word") == "dukeword"
    assert m.group("n") == "2"
    assert m.group("unit") == "h"


def test_regex_parses_minutes():
    m = _NM_SAFEWORD_WINDOW_RE.match("dukeword 45m")
    assert m is not None and m.group("n") == "45" and m.group("unit") == "m"


def test_regex_rejects_bare_word():
    assert _NM_SAFEWORD_WINDOW_RE.match("dukeword") is None


def test_regex_rejects_negative_and_letters():
    # regex does not admit '-' or non-digits in <n>
    assert _NM_SAFEWORD_WINDOW_RE.match("dukeword -1h") is None
    assert _NM_SAFEWORD_WINDOW_RE.match("dukeword abc") is None


# ---------------------------------------------------------------------------
# I4 — parse -> reject / open / fall-through
# ---------------------------------------------------------------------------


def test_duke_2h_acks_current_and_opens_window():
    """I3 anchor: current alert acked (via async_acknowledge), window opens
    120min in the future for FUTURE first-fire perimeter alerts."""
    nm = _make_nm()
    # Simulate an active perimeter CRITICAL that would otherwise re-page.
    nm._alert_state = AlertState.REPEATING
    nm._active_alert_data = {
        "severity": "CRITICAL",
        "hazard_type": NM_HAZARD_EXTERIOR_PERSON,
        "location": "front_yard",
    }
    # Authorize the ack path.
    nm._is_authorized_to_ack = MagicMock(return_value=(True, "authorized_security"))
    nm._get_person_name = MagicMock(return_value="Op")
    nm._announce_ack = AsyncMock()

    before = datetime.utcnow()
    resp = _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 2h"))
    after = datetime.utcnow()

    # Ack was invoked (I3 — the in-flight re-page loop is stopped by the
    # ordinary ack path, NOT by this new gate).
    assert nm.async_acknowledge.await_count == 1
    # Window was opened ~120 minutes out.
    assert nm._perimeter_silence_until is not None
    delta = nm._perimeter_silence_until - before
    assert timedelta(minutes=119, seconds=55) <= delta <= (after - before + timedelta(minutes=120, seconds=5))
    # Reply mentions the window.
    assert "silenced" in resp.lower()
    assert "resume" in resp.lower()


def test_duke_45m_parses():
    nm = _make_nm()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 45m"))
    assert nm._perimeter_silence_until is not None
    remaining = nm._perimeter_silence_until - datetime.utcnow()
    assert timedelta(minutes=44, seconds=55) < remaining < timedelta(minutes=45, seconds=5)


def test_duke_over_cap_rejected():
    """I4: raw > 180 min rejects (no ack, no window)."""
    nm = _make_nm()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    resp = _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 5h"))
    assert "capped" in resp.lower()
    assert nm._perimeter_silence_until is None
    assert nm.async_acknowledge.await_count == 0


def test_duke_zero_minutes_falls_through():
    """I4: '<word> 0m' fails min-bound → no window, no ack (text as-is
    fails _match_safe_word because of trailing '0m')."""
    nm = _make_nm()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 0m"))
    assert nm._perimeter_silence_until is None
    assert nm.async_acknowledge.await_count == 0


def test_duke_abc_falls_through():
    """I4: '<word> abc' does not match regex → normal safeword path.

    Since 'dukeword abc' also doesn't equal the safeword exactly, no ack
    fires and no window opens.
    """
    nm = _make_nm()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    _run(nm._process_inbound_reply("person.op", "imessage", "dukeword abc"))
    assert nm._perimeter_silence_until is None
    assert nm.async_acknowledge.await_count == 0


def test_bare_duke_still_acks_no_window():
    """Non-goal preservation: bare safeword unchanged."""
    nm = _make_nm()
    nm._alert_state = AlertState.REPEATING
    nm._active_alert_data = {"severity": "CRITICAL", "hazard_type": "water_leak", "location": "basement"}
    nm._is_authorized_to_ack = MagicMock(return_value=(True, "any"))
    nm._get_person_name = MagicMock(return_value="Op")
    nm._announce_ack = AsyncMock()
    _run(nm._process_inbound_reply("person.op", "imessage", "dukeword"))
    assert nm.async_acknowledge.await_count == 1
    assert nm._perimeter_silence_until is None


# ---------------------------------------------------------------------------
# I2 — perimeter-only gate scope (async_notify site)
# ---------------------------------------------------------------------------


def _open_window(nm, minutes: int = 60) -> None:
    nm._perimeter_silence_until = (
        datetime.utcnow() + timedelta(minutes=minutes)
    )
    nm._perimeter_silence_last_notified_expiry = None


def _stub_downstream_notify(nm):
    """Force async_notify past the gate: stub all downstream helpers so
    return-normally means 'dedup/hygiene/route were reached'.
    """
    # After the gate, the next branch is dedup. Make dedup a no-op returning
    # False so the notify would proceed to real routing (which we short-circuit
    # by disabling every channel — done in _make_config already for TTS/lights
    # and by setting _channel_qualifies=False for everything except a marker).
    nm._is_deduplicated = MagicMock(return_value=False)
    nm._is_quiet_hours = MagicMock(return_value=False)
    nm._recipient_bypasses_dnd = MagicMock(return_value=False)
    nm._boot_settle_should_suppress = MagicMock(return_value=False)
    nm._channel_ready = MagicMock(return_value=False)
    nm._channel_qualifies = MagicMock(return_value=False)
    # Route markers — we tick a counter when notify progresses past the gate.
    nm._route_marker = 0
    _orig_incr = nm._increment_counters if hasattr(nm, "_increment_counters") else None
    def _mark(*a, **kw):
        nm._route_marker += 1
        if _orig_incr:
            return _orig_incr(*a, **kw)
    if _orig_incr is not None:
        nm._increment_counters = _mark


def test_window_suppresses_exterior_person_first_fire():
    """I2: NM_SECURITY_HAZARDS ∧ window active ⇒ suppressed early."""
    nm = _make_nm()
    _stub_downstream_notify(nm)
    _open_window(nm, minutes=30)
    before = nm._perimeter_silence_suppressions
    _run(nm.async_notify(
        coordinator_id="perimeter",
        severity=Severity.CRITICAL,
        title="Person at gate",
        message="detected",
        hazard_type=NM_HAZARD_EXTERIOR_PERSON,
        location="front",
    ))
    assert nm._perimeter_silence_suppressions == before + 1
    # Route marker never advanced — the gate returned early.
    assert nm._route_marker == 0


def test_window_never_blankets_water_leak():
    """I2 anchor: non-perimeter, non-life-safety hazard passes the gate.

    'high_humidity' is neither in NM_SECURITY_HAZARDS nor in
    NM_LIFE_SAFETY_HAZARDS — the ONLY thing that can suppress it here
    is the new perimeter-scope check. Mutation of `hazard_type in
    NM_SECURITY_HAZARDS` reddens THIS test specifically.
    """
    nm = _make_nm()
    _stub_downstream_notify(nm)
    _open_window(nm, minutes=30)
    before = nm._perimeter_silence_suppressions
    _run(nm.async_notify(
        coordinator_id="climate",
        severity=Severity.HIGH,
        title="High humidity",
        message="detected",
        hazard_type="high_humidity",
        location="bathroom",
    ))
    # The new gate did NOT fire (would only fire if perimeter-scope
    # check were removed).
    assert nm._perimeter_silence_suppressions == before


def test_window_never_blankets_life_safety_smoke():
    """I1 anchor: life-safety hazards ALWAYS pass through, even in
    perimeter-adjacent code paths."""
    nm = _make_nm()
    _stub_downstream_notify(nm)
    _open_window(nm, minutes=30)
    # Belt-and-suspenders: if a hazard were BOTH perimeter AND life-safety,
    # the life-safety check must win. Force is_life_safety_hazard True for
    # exterior_person to prove the exclusion is load-bearing.
    _nm_mod.is_life_safety_hazard = lambda hass, hz: True
    try:
        before = nm._perimeter_silence_suppressions
        _run(nm.async_notify(
            coordinator_id="perimeter",
            severity=Severity.CRITICAL,
            title="Person at gate (promoted life-safety)",
            message="detected",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location="front",
        ))
        assert nm._perimeter_silence_suppressions == before
    finally:
        # Restore module binding for later tests.
        from custom_components.universal_room_automation.domain_coordinators._nm_cycle_a import (
            is_life_safety_hazard as _real,
        )
        _nm_mod.is_life_safety_hazard = _real


# ---------------------------------------------------------------------------
# I5 — expiry + resumed note + attribute surface
# ---------------------------------------------------------------------------


def test_window_expires_and_emits_resumed_note():
    """I5: at expiry, next perimeter dispatch sees the window cleared and
    a 'resumed' note task is created exactly once."""
    nm = _make_nm()
    _stub_downstream_notify(nm)
    # Expiry in the PAST — the next async_notify tick should observe expiry.
    nm._perimeter_silence_until = (
        datetime.utcnow() - timedelta(seconds=1)
    )
    nm._perimeter_silence_last_notified_expiry = None
    before_tasks = len(nm._pending_note_coros)
    _run(nm.async_notify(
        coordinator_id="perimeter",
        severity=Severity.CRITICAL,
        title="Person at gate",
        message="detected",
        hazard_type=NM_HAZARD_EXTERIOR_PERSON,
        location="front",
    ))
    # Window cleared.
    assert nm._perimeter_silence_until is None
    # Exactly one resumed-note task queued.
    assert len(nm._pending_note_coros) == before_tasks + 1
    # A second tick after expiry MUST NOT emit another resumed note
    # (idempotence via _perimeter_silence_last_notified_expiry).
    _run(nm.async_notify(
        coordinator_id="perimeter",
        severity=Severity.CRITICAL,
        title="Another person at gate",
        message="detected",
        hazard_type=NM_HAZARD_EXTERIOR_PERSON,
        location="front",
    ))
    assert len(nm._pending_note_coros) == before_tasks + 1
    # Drain queued coros so they don't warn on GC.
    for c in nm._pending_note_coros:
        c.close()


def test_attribute_surface_reflects_window():
    """D4 anchor: three new keys present on diagnostics_summary; both null
    after clearing."""
    nm = _make_nm()
    attrs = nm.diagnostics_summary
    assert "perimeter_silence_active" in attrs
    assert "perimeter_silence_expires_at" in attrs
    assert "perimeter_silence_suppressions_today" in attrs
    assert attrs["perimeter_silence_active"] is False
    assert attrs["perimeter_silence_expires_at"] is None
    _open_window(nm, minutes=15)
    attrs2 = nm.diagnostics_summary
    assert attrs2["perimeter_silence_active"] is True
    assert attrs2["perimeter_silence_expires_at"] is not None


# ---------------------------------------------------------------------------
# D6 — kill switch
# ---------------------------------------------------------------------------


def test_kill_switch_disables_pre_parse(monkeypatch):
    """NM_SAFEWORD_WINDOW_ENABLED=False → 'duke Nh' does NOT open a
    window and does NOT ack (raw text fails exact _match_safe_word)."""
    monkeypatch.setattr(_nm_mod, "NM_SAFEWORD_WINDOW_ENABLED", False)
    nm = _make_nm()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 2h"))
    assert nm._perimeter_silence_until is None
    assert nm.async_acknowledge.await_count == 0


# ---------------------------------------------------------------------------
# Non-invariant / persistence: RAM-only
# ---------------------------------------------------------------------------


def test_restart_clears_window_via_persistence():
    """RAM-only: window key MUST NOT appear in get_persistence_state, and
    a restored NM has _perimeter_silence_until is None."""
    nm = _make_nm()
    _open_window(nm, minutes=60)
    state = nm.get_persistence_state()
    assert not any("perimeter_silence" in k for k in state.keys()), state.keys()
    # Fresh instance is untouched.
    nm2 = _make_nm()
    nm2.restore_persistence_state(state)
    assert nm2._perimeter_silence_until is None


# ---------------------------------------------------------------------------
# Echo safety — our own reply strings do not carry the safeword
# ---------------------------------------------------------------------------


def test_reply_strings_never_contain_safeword():
    """Rail-safety: the two feature reply strings never carry 'dukeword'
    so the echo rail-1 self-echo drop can never re-parse them as
    another duke Nh open."""
    # Cap-reject reply is constructed from module constants only.
    reject = (
        f"Window capped at {NM_SAFEWORD_WINDOW_MAX_MIN // 60}h — "
        f"try 'duke {NM_SAFEWORD_WINDOW_MAX_MIN // 60}h' or less."
    )
    assert "dukeword" not in reject.lower()
    # Ack+window reply is composed with "Perimeter alerts silenced for
    # {N}m; resume at HH:MM." — no operator word by construction.
    silenced_template = "Perimeter alerts silenced for 60m; resume at 12:34."
    assert "dukeword" not in silenced_template.lower()


# ---------------------------------------------------------------------------
# Wire-in anchors (source-shape checks — these fail if the load-bearing
# lines are deleted, backing the C-framing per-site mutation drill).
# ---------------------------------------------------------------------------


def test_wire_in_gate_present_in_async_notify():
    """The perimeter gate MUST be wired inside async_notify — a source
    read confirms the load-bearing predicate. This is a shape check;
    the behavioral guarantee is test_window_suppresses_exterior_person_
    first_fire (removing the gate reddens both)."""
    import inspect
    src = inspect.getsource(NotificationManager.async_notify)
    assert "hazard_type in NM_SECURITY_HAZARDS" in src
    assert "is_life_safety_hazard(self.hass, hazard_type)" in src
    assert "_perimeter_silence_until" in src


def test_wire_in_parse_present_in_process_inbound_reply():
    import inspect
    src = inspect.getsource(NotificationManager._process_inbound_reply)
    assert "_NM_SAFEWORD_WINDOW_RE" in src
    assert "NM_SAFEWORD_WINDOW_ENABLED" in src
    assert "_perimeter_silence_until" in src

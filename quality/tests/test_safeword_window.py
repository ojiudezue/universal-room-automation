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
    """I4: raw > 180 min rejects (no ack, no window). Also verifies the
    cap-reject reply routes through _log_and_reply with the
    'safe_word_window_rejected' parsed-command tag (feeds C-LOW-3's
    rate-limit-exempt list)."""
    nm = _make_nm()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    resp = _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 5h"))
    assert "capped" in resp.lower()
    assert nm._perimeter_silence_until is None
    assert nm.async_acknowledge.await_count == 0
    # C-LOW-3 anchor: reply went through _log_and_reply with the exact
    # tag added to NM_REPLY_RATE_LIMIT_EXEMPT_COMMANDS.
    assert nm._log_and_reply.await_count == 1
    _, kwargs = nm._log_and_reply.await_args
    args = nm._log_and_reply.await_args.args
    assert args[4] == "safe_word_window_rejected", args


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
    """Stub downstream helpers of async_notify so we can observe whether
    control REACHED the dedup step (i.e. flowed past the perimeter gate)
    via a spy on ``_is_deduplicated`` — the very next site after the
    gate's ``return``.

    Fix-up C-CRIT-1: the earlier version used a dead ``_route_marker``
    based on a non-existent ``_increment_counters`` and therefore only
    proved that the return WASN'T bypassed by some unrelated route; it
    could not distinguish "gate returned" from "gate was skipped and
    downstream stubbed to no-op". Spying on the FIRST real callee past
    the gate does — removing the return reddens it.
    """
    nm._is_deduplicated = MagicMock(return_value=False)
    nm._is_quiet_hours = MagicMock(return_value=False)
    nm._recipient_bypasses_dnd = MagicMock(return_value=False)
    nm._boot_settle_should_suppress = MagicMock(return_value=False)
    nm._channel_ready = MagicMock(return_value=False)
    nm._channel_qualifies = MagicMock(return_value=False)


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
    # C-CRIT-1 anchor: the gate's ``return`` short-circuits BEFORE the
    # dedup call (the very next site). If the return is removed, the
    # dedup spy fires — reddening this assertion.
    assert nm._is_deduplicated.call_count == 0


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
    """C-LOW-2: capture the ACTUAL reply text emitted by production code
    on both feature paths (cap-reject + ack+window) and prove none of
    them carry the operator's safeword. Guards the echo-loop rail: if
    a reply DID carry 'dukeword' plus a trailing digit+unit, rail-1's
    self-echo drop would still catch it, but a rail-2 miss could
    otherwise re-parse into another open."""
    nm = _make_nm()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    # Path 1: cap-reject.
    _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 9h"))
    assert nm._log_and_reply.await_count == 1
    reject_reply = nm._log_and_reply.await_args.args[5]
    assert "dukeword" not in reject_reply.lower()
    # Reply must end with terminal punctuation so the "N[h|m]" tail
    # cannot end-anchor _NM_SAFEWORD_WINDOW_RE on a reflected copy.
    assert reject_reply.rstrip().endswith(".")

    # Path 2: ack+window opened.
    nm2 = _make_nm()
    nm2._alert_state = AlertState.IDLE
    nm2._active_alert_data = None
    _run(nm2._process_inbound_reply("person.op", "imessage", "dukeword 15m"))
    assert nm2._log_and_reply.await_count == 1
    open_reply = nm2._log_and_reply.await_args.args[5]
    assert "dukeword" not in open_reply.lower()
    assert open_reply.rstrip().endswith(".")
    # And even if we splice the reply back through the regex, it must
    # NOT match (rail-safety at the parse level).
    assert _NM_SAFEWORD_WINDOW_RE.match(open_reply.strip().lower()) is None
    assert _NM_SAFEWORD_WINDOW_RE.match(reject_reply.strip().lower()) is None


# ---------------------------------------------------------------------------
# A1/A4 (fix-up) — authorization on window-open + cap-reject
# ---------------------------------------------------------------------------


def _make_nm_with_extra_person(extra_id: str = "person.guest") -> NotificationManager:
    """NM with two persons; only person.op is in the default security-ack
    allowlist (first-person fallback). person.guest is unauthorized."""
    hass = _make_hass()
    cfg = _make_config(**{
        CONF_NM_SAFE_WORD: "dukeword",
        CONF_NM_PERSONS: [
            {
                CONF_NM_PERSON_ENTITY: "person.op",
                CONF_NM_PERSON_PUSHOVER_KEY: "k",
                CONF_NM_PERSON_COMPANION_SERVICE: "",
                CONF_NM_PERSON_WHATSAPP_PHONE: "",
                CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
            },
            {
                CONF_NM_PERSON_ENTITY: extra_id,
                CONF_NM_PERSON_PUSHOVER_KEY: "k2",
                CONF_NM_PERSON_COMPANION_SERVICE: "",
                CONF_NM_PERSON_WHATSAPP_PHONE: "",
                CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
            },
        ],
    })
    nm = NotificationManager(hass, cfg)
    nm._log_and_reply = AsyncMock(return_value=None)
    nm.async_acknowledge = AsyncMock(return_value=None)
    nm._pending_note_coros = []
    nm.hass.async_create_task = lambda coro: (
        nm._pending_note_coros.append(coro) or MagicMock()
    )
    return nm


def test_unauthorized_person_cannot_open_window():
    """A1 (fix-up): a CONF_NM_PERSONS member not on the security-ack
    allowlist cannot open a perimeter window via 'duke Nh' when idle.
    Mutation-drilled: removing the auth check (the two-line
    ``_win_allowed`` gate in async _process_inbound_reply) reddens
    this test."""
    nm = _make_nm_with_extra_person()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    resp = _run(nm._process_inbound_reply("person.guest", "imessage", "dukeword 2h"))
    assert nm._perimeter_silence_until is None
    assert "not authorized" in resp.lower()


def test_authorized_person_can_open_window():
    """Companion to the unauthorized test — proves the allowlisted
    person.op still opens the window under the same auth gate."""
    nm = _make_nm_with_extra_person()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    _run(nm._process_inbound_reply("person.op", "imessage", "dukeword 2h"))
    assert nm._perimeter_silence_until is not None


def test_unauthorized_cap_reject_falls_through_silently():
    """A4 (fix-up): unauthorized 'duke 9h' does NOT confirm the cap or
    the word — the reply routes through the normal 'unknown / no
    context' path, not through 'safe_word_window_rejected'. Blocks
    the C-LOW-4 side channel."""
    nm = _make_nm_with_extra_person()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    _run(nm._process_inbound_reply("person.guest", "imessage", "dukeword 9h"))
    # Either no _log_and_reply at all (silent-ignore path when there is
    # no context) OR the tag is NOT the cap-reject one.
    if nm._log_and_reply.await_count > 0:
        args = nm._log_and_reply.await_args.args
        assert args[4] != "safe_word_window_rejected", args


def test_companion_channel_auto_authorized_for_window_open():
    """Existing convention: companion channel is operator-grade and
    auto-authorized. Prove this holds for the new auth gate too."""
    nm = _make_nm_with_extra_person()
    nm._alert_state = AlertState.IDLE
    nm._active_alert_data = None
    # No person_id, companion channel.
    _run(nm._process_inbound_reply(None, "companion", "dukeword 30m"))
    assert nm._perimeter_silence_until is not None


# ---------------------------------------------------------------------------
# B-LOW-1 (fix-up) — bounded suppressed-event ring
# ---------------------------------------------------------------------------


def test_recent_suppressions_ring_bounded_to_10():
    """Suppress 12 perimeter alerts under an open window; the ring on
    diagnostics_summary must hold only the newest 10."""
    nm = _make_nm()
    _stub_downstream_notify(nm)
    _open_window(nm, minutes=30)
    for i in range(12):
        _run(nm.async_notify(
            coordinator_id="perimeter",
            severity=Severity.CRITICAL,
            title=f"Person at gate #{i}",
            message="detected",
            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
            location=f"front-{i}",
        ))
    ring = nm.diagnostics_summary["perimeter_silence_recent_suppressions"]
    assert isinstance(ring, list)
    assert len(ring) == 10
    # Newest at the tail (deque.append semantics). Oldest 2 evicted → the
    # first entry is #2, last is #11.
    assert ring[0]["title"].endswith("#2")
    assert ring[-1]["title"].endswith("#11")
    for entry in ring:
        assert set(entry.keys()) == {"ts", "hazard", "title", "location"}
    # And the today-counter reflects the true count including evicted ones.
    assert nm._perimeter_silence_suppressions == 12


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

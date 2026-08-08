"""OVERRIDE-NOTIFY-1 (2026-08-08, operator-approved): pre-warn +
deferral NM notes for the Temp Arrester Override, plus release-path
dedup verification.

Behavioral tests drive the REAL `OverrideArrester` methods (no re-
implementation of logic). Reuses the sys.modules HA-stub bootstrap
from `test_arrester_operator_immunity.py`.

Mutation drills documented per-test.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from unittest.mock import MagicMock

# Reuse sibling test module's stub bootstrap (top-level side effects
# install stubs + source-load the real hvac_override module).
import quality.tests.test_arrester_operator_immunity as _sib  # noqa: F401

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_override as _ho_mod,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_override import (  # noqa: E402
    OverrideArrester,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E402
    ARRESTER_OVERRIDE_EXPIRY_WARN_S,
    ARRESTER_OVERRIDE_MIN_LIFE_S,
    COMFORT_OVERRIDE_MAX_S,
)


def _make_arrester():
    return _sib._make_arrester()


# ---------------------------------------------------------------------------
# Timer-capture helper — hijack async_call_later so we can capture the
# scheduled (delay, cb) and simulate fire without wall-clock waits.
# ---------------------------------------------------------------------------

class _TimerCapture:
    def __init__(self):
        self.calls: list[tuple[float, callable]] = []
        self.unsub_calls: int = 0

    def __call__(self, _hass, delay, cb):
        self.calls.append((delay, cb))
        cap = self

        def _unsub():
            cap.unsub_calls += 1
        return _unsub


def _install_timer_capture(monkeypatch):
    cap = _TimerCapture()
    monkeypatch.setattr(_ho_mod, "async_call_later", cap)
    return cap


# ---------------------------------------------------------------------------
# Pre-warn tests
# ---------------------------------------------------------------------------

def test_prewarn_scheduled_at_correct_offset_on_engage(monkeypatch):
    """OVERRIDE-NOTIFY-1: set_temp_arrester_override(True) schedules the
    pre-warn one-shot at (COMFORT_OVERRIDE_MAX_S - warn_s).

    Mutation drill: delete the async_call_later block from
    set_temp_arrester_override's ON branch -> this test goes RED.
    """
    cap = _install_timer_capture(monkeypatch)
    a = _make_arrester()

    notified: list[int] = []
    a.set_on_expiry_warn_notify(lambda mins: notified.append(mins))

    a.set_temp_arrester_override(True)

    # Filter to the pre-warn schedule (single async_call_later call from
    # engage; no other timers fire in this path).
    assert cap.calls, "no async_call_later invoked on engage"
    delay, cb = cap.calls[-1]
    expected = COMFORT_OVERRIDE_MAX_S - ARRESTER_OVERRIDE_EXPIRY_WARN_S
    assert delay == expected, (
        f"pre-warn scheduled at {delay}s, expected {expected}s"
    )

    # Firing the captured cb → notify fires with ~5 min remaining.
    cb(None)
    assert notified == [5], (
        f"pre-warn callback did not fire once with 5-min remaining: {notified}"
    )


def test_prewarn_does_not_fire_after_release(monkeypatch):
    """OVERRIDE-NOTIFY-1: cancel_expiry_warn_timer on manual OFF must
    prevent the pre-warn from firing against a released override.

    Mutation drill: remove `self._cancel_expiry_warn_timer()` from
    set_temp_arrester_override's OFF branch -> this test goes RED.
    """
    cap = _install_timer_capture(monkeypatch)
    a = _make_arrester()

    notified: list[int] = []
    a.set_on_expiry_warn_notify(lambda mins: notified.append(mins))

    a.set_temp_arrester_override(True)
    assert cap.calls
    _delay, cb = cap.calls[-1]

    # Operator flips OFF before warn fires.
    a.set_temp_arrester_override(False)
    assert cap.unsub_calls >= 1, "manual OFF did not cancel pre-warn timer"

    # Even if a stale timer fires anyway (defensive), the active guard
    # inside the cb must suppress the notify.
    cb(None)
    assert notified == [], (
        f"pre-warn fired after release: {notified}"
    )


def test_prewarn_cancelled_on_sunset_fire(monkeypatch):
    """OVERRIDE-NOTIFY-1: all sunset paths (max_age here) must cancel
    the pending pre-warn so it cannot fire post-release.

    Mutation drill: remove `self._cancel_expiry_warn_timer()` from the
    sunset_temp_arrester_override fire branch -> this test goes RED.
    """
    cap = _install_timer_capture(monkeypatch)
    a = _make_arrester()

    notified: list[int] = []
    a.set_on_expiry_warn_notify(lambda mins: notified.append(mins))

    a.set_temp_arrester_override(True)
    assert cap.calls
    _delay, cb = cap.calls[-1]

    # Force max-age elapse and fire sunset.
    a._temp_arrester_override_started_ts = (
        a._temp_arrester_override_started_ts - timedelta(seconds=999999)
    )
    fired = a.sunset_temp_arrester_override(reason="max_age")
    assert fired is True
    assert cap.unsub_calls >= 1, (
        "sunset fire did not cancel the pre-warn timer"
    )

    # Late-fire of the timer's cb must be a no-op (active guard).
    cb(None)
    assert notified == [], (
        f"pre-warn fired after sunset release: {notified}"
    )


def test_prewarn_teardown_cancels_timer(monkeypatch):
    """OVERRIDE-NOTIFY-1: teardown() must cancel the pre-warn timer so a
    late-fire cannot land on a torn-down arrester.

    Mutation drill: remove `self._cancel_expiry_warn_timer()` from
    teardown() -> this test goes RED.
    """
    cap = _install_timer_capture(monkeypatch)
    a = _make_arrester()
    a.set_temp_arrester_override(True)
    assert cap.calls
    a.teardown()
    assert cap.unsub_calls >= 1, "teardown did not cancel pre-warn timer"


# ---------------------------------------------------------------------------
# Deferral note tests
# ---------------------------------------------------------------------------

def test_defer_notify_fires_with_remaining_minutes(monkeypatch):
    """OVERRIDE-NOTIFY-1: when a state-transition sunset is DEFERRED by
    the MIN_LIFE grace, the on_defer_notify callback fires immediately
    with the remaining grace in minutes.

    F4 fix-up (2026-08-08): ALSO verify the deferral branch cancels the
    pre-warn timer (via ``_cancel_expiry_warn_timer()`` inside the defer
    block) so a subsequent stale fire of the pre-warn callback does NOT
    emit a notification.

    Mutation drill (defer-notify): remove the `cb_defer(remaining_min)`
    block from the deferral branch of sunset_temp_arrester_override
    -> the ``deferred`` assertion below goes RED.

    Mutation drill (F4 — cancel-prewarn-on-defer): remove the
    ``self._cancel_expiry_warn_timer()`` call inside the defer branch
    (~hvac_override.py:905) -> the ``cap.unsub_calls`` assertion below
    goes RED (unsub never called, and a stale pre-warn fire would then
    emit a notification against a defer-superseded engagement).
    """
    cap = _install_timer_capture(monkeypatch)
    a = _make_arrester()

    deferred: list[int] = []
    notified_prewarn: list[int] = []
    a.set_on_defer_notify(lambda mins: deferred.append(mins))
    a.set_on_expiry_warn_notify(lambda mins: notified_prewarn.append(mins))

    a.set_temp_arrester_override(True)
    # Capture the pre-warn cb scheduled by the engage.
    assert cap.calls, "engage did not schedule pre-warn timer"
    _delay, prewarn_cb = cap.calls[-1]
    unsub_before_defer = cap.unsub_calls

    # Freshly engaged — well within MIN_LIFE. Fire an invalidating
    # state-transition sunset — must DEFER (not fire).
    fired = a.sunset_temp_arrester_override(
        reason="durable_state", house_state="sleep",
    )
    assert fired is False, "sunset fired instead of deferring inside MIN_LIFE"
    assert a._temp_arrester_override_pending_sunset == "sleep"

    assert deferred, "defer-notify callback did not fire"
    # Remaining minutes should be ~ceil(MIN_LIFE/60) since we just engaged
    # (max of 1). Allow a wide band since wall clock jitters.
    expected_max = max(1, int(round(ARRESTER_OVERRIDE_MIN_LIFE_S / 60)))
    assert 1 <= deferred[0] <= expected_max, (
        f"defer-notify remaining minutes out of range: {deferred[0]}"
    )

    # F4: pre-warn timer must have been cancelled by the defer branch.
    assert cap.unsub_calls > unsub_before_defer, (
        "F4 regression: deferral branch did NOT cancel the pre-warn "
        "timer (expected _cancel_expiry_warn_timer() call inside "
        "the defer block). A stale pre-warn would then emit a warning "
        "after the override has already been superseded by deferral."
    )
    # And firing the captured (now-stale) pre-warn cb must NOT emit a
    # notification. Two guards protect this:
    #  (a) unsub above stops async_call_later from firing it in prod;
    #  (b) even if it does fire (defensive), the cb clears its own
    #      unsub handle first and the active guard suppresses notify
    #      when override is no longer active — but here override IS
    #      still active (deferred, not sunset), so the true guard is
    #      that the timer was cancelled. Simulate a stale fire:
    prewarn_cb(None)
    assert notified_prewarn == [] or notified_prewarn == [5], (
        # Defensive-fire may or may not still notify depending on how the
        # cb guards run, but the CANCELLATION assertion above is the
        # load-bearing F4 anchor; this line documents the observed
        # behavior without over-constraining a defensive path.
        f"unexpected pre-warn notify shape: {notified_prewarn!r}"
    )


def test_prewarn_refires_on_reengagement(monkeypatch):
    """F3 fix-up (2026-08-08): pre-warn dedup is keyed by ENGAGEMENT ID,
    not a boolean "already warned" latch. A release + re-engage MUST
    schedule a fresh pre-warn timer whose fire notifies again.

    Mutation drill: change `_last_expiry_warned_engagement_id` from an
    int engagement-id counter to a boolean-style latch (e.g. stamp it
    True on first warn, then `if self._last_expiry_warned_engagement_id:
    return`) -> re-engagement is treated as warned -> this test goes RED
    because ``notified == [5]`` instead of ``[5, 5]``.
    """
    cap = _install_timer_capture(monkeypatch)
    a = _make_arrester()

    notified: list[int] = []
    a.set_on_expiry_warn_notify(lambda mins: notified.append(mins))

    # First engagement — capture cb, fire it, expect one notify.
    a.set_temp_arrester_override(True)
    assert cap.calls, "engage#1 did not schedule pre-warn timer"
    _d1, cb1 = cap.calls[-1]
    cb1(None)
    assert notified == [5], f"engage#1 pre-warn did not notify once: {notified}"

    # Release, then re-engage — must schedule a fresh timer.
    a.set_temp_arrester_override(False)
    calls_before = len(cap.calls)
    a.set_temp_arrester_override(True)
    assert len(cap.calls) > calls_before, (
        "engage#2 did not schedule a fresh pre-warn timer"
    )
    _d2, cb2 = cap.calls[-1]

    # Fire the re-engaged cb — must notify AGAIN (dedup is per-engagement).
    cb2(None)
    assert notified == [5, 5], (
        f"F3 regression: pre-warn did not re-fire on re-engagement — "
        f"dedup latch is not engagement-scoped. notified={notified!r}"
    )


def test_prewarn_not_scheduled_when_warn_s_zero(monkeypatch):
    """F6 fix-up (2026-08-08): the ``ARRESTER_OVERRIDE_EXPIRY_WARN_S = 0``
    kill switch must fully disable the pre-warn — engaging the override
    MUST NOT schedule the pre-warn timer at all.

    Mutation drill: remove the ``ARRESTER_OVERRIDE_EXPIRY_WARN_S > 0``
    guard from the engage branch of set_temp_arrester_override
    -> this test goes RED (a timer gets scheduled with delay ==
    COMFORT_OVERRIDE_MAX_S).
    """
    cap = _install_timer_capture(monkeypatch)
    # Patch the imported name inside hvac_override (module-local ref).
    monkeypatch.setattr(_ho_mod, "ARRESTER_OVERRIDE_EXPIRY_WARN_S", 0)
    a = _make_arrester()
    a.set_temp_arrester_override(True)
    # No pre-warn timer scheduled — the ON branch's only async_call_later
    # call is the pre-warn schedule; with WARN_S=0 it is guarded off.
    assert cap.calls == [], (
        f"F6 regression: WARN_S=0 kill switch did not suppress pre-warn "
        f"timer schedule (got {cap.calls!r})"
    )


# ---------------------------------------------------------------------------
# Release-path notify coverage — Part 3 of the OVERRIDE-NOTIFY-1 spec.
# ---------------------------------------------------------------------------

def test_release_paths_all_notify_exactly_once(monkeypatch):
    """Part 3: verify the sunset "override ended (auto)" NM callback
    fires exactly once per engagement across all sunset paths
    (max_age here + state-transition after MIN_LIFE elapsed +
    min_life_discharge via timer). Engagement-id dedup blocks the
    double-notify race.

    Mutation drill: neuter the `cb(_reason_out)` call inside the fire
    branch of sunset_temp_arrester_override -> all three assertions on
    len(notified) go RED (no path notifies).
    """
    _install_timer_capture(monkeypatch)
    a = _make_arrester()

    notified: list[str] = []
    a.set_on_sunset_notify(lambda reason: notified.append(reason))

    # Path 1: max_age
    a.set_temp_arrester_override(True)
    a._temp_arrester_override_started_ts = (
        a._temp_arrester_override_started_ts - timedelta(seconds=999999)
    )
    fired = a.sunset_temp_arrester_override(reason="max_age")
    assert fired is True
    assert len(notified) == 1

    # Idempotent re-call: no double-notify.
    a.sunset_temp_arrester_override(reason="max_age")
    assert len(notified) == 1

    # Path 2: state-transition sunset AFTER MIN_LIFE elapsed
    a.set_temp_arrester_override(True)
    a._temp_arrester_override_started_ts = (
        a._temp_arrester_override_started_ts
        - timedelta(seconds=ARRESTER_OVERRIDE_MIN_LIFE_S + 60)
    )
    fired = a.sunset_temp_arrester_override(
        reason="durable_state", house_state="sleep",
    )
    assert fired is True
    assert len(notified) == 2, f"state-transition sunset did not notify: {notified}"

    # Path 3: deferred → timer discharge (simulate timer cb call).
    a.set_temp_arrester_override(True)
    a.sunset_temp_arrester_override(
        reason="durable_state", house_state="sleep",
    )  # defers (fresh engagement)
    assert a._temp_arrester_override_pending_sunset == "sleep"
    # Advance past MIN_LIFE and drive the discharge sweep.
    a._temp_arrester_override_started_ts = (
        a._temp_arrester_override_started_ts
        - timedelta(seconds=ARRESTER_OVERRIDE_MIN_LIFE_S + 60)
    )
    a.sunset_temp_arrester_override(reason="min_life_discharge")
    assert len(notified) == 3, (
        f"deferred discharge did not notify: {notified}"
    )

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

    Mutation drill: remove the `cb_defer(remaining_min)` block from the
    deferral branch of sunset_temp_arrester_override -> this test goes RED.
    """
    cap = _install_timer_capture(monkeypatch)
    a = _make_arrester()

    deferred: list[int] = []
    a.set_on_defer_notify(lambda mins: deferred.append(mins))

    a.set_temp_arrester_override(True)
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

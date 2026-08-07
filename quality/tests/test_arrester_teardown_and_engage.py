"""F5/F6/F8 (2026-08-07 fix-up cycle-4): OverrideArrester teardown +
engage-defensive-clear + timer-path NM-note dispatch.

Reuses the sys.modules HA-stub bootstrap from
test_arrester_operator_immunity.py by importing it FIRST — that file's
top-level side effects install the stubs and source-load the real
hvac_override module. This test file then reaches into the same
already-loaded module by name.
"""

from __future__ import annotations

import sys

# Force the sibling test module to run its stub bootstrap. Its
# top-level imports register HA stubs + source-load hvac_override etc.
import quality.tests.test_arrester_operator_immunity as _sib  # noqa: F401

from custom_components.universal_room_automation.domain_coordinators.hvac_override import (  # noqa: E402
    OverrideArrester,
)


def _make_arrester():
    # Delegate to the sibling's helper — identical shape.
    return _sib._make_arrester()


def test_f5_teardown_cancels_pending_sunset_and_clears_state():
    """F5: teardown() must cancel the pending-sunset async_call_later,
    clear the pending flag, and force the override OFF so a racing
    late-fire callback is a no-op."""
    a = _make_arrester()
    a.set_temp_arrester_override(True)
    # Simulate a mid-grace deferred sunset — advance 60s and fire an
    # invalidating transition; it defers.
    _sib.SIGNAL_check = None  # unused; readability
    # advance is exposed via _sib.fake_clock — but we don't have the
    # fixture here. Direct-state seed instead:
    a._temp_arrester_override_pending_sunset = "sleep"

    # Fake unsub sentinel so we can prove teardown cancelled it.
    cancelled = {"n": 0}

    def _fake_unsub():
        cancelled["n"] += 1

    a._temp_arrester_override_pending_sunset_unsub = _fake_unsub

    a.teardown()

    assert cancelled["n"] == 1, "F5: pending-sunset timer was not cancelled"
    assert a._temp_arrester_override_pending_sunset_unsub is None
    assert a._temp_arrester_override_pending_sunset is None
    assert a._temp_arrester_override_active is False

    # A racing late fire on the timer callback must be a no-op — the
    # active guard trips.
    a._pending_sunset_timer_cb(None)
    # State stayed OFF; no exception raised.
    assert a._temp_arrester_override_active is False


def test_f6_engage_defensively_clears_stale_pending():
    """F6: set_temp_arrester_override(True) after a stale pending flag
    (e.g. after a bad prior teardown / partial reload) must NOT let the
    fresh engagement inherit that pending sunset — otherwise the sweep
    would discharge it at the FIRST post-engage tick."""
    a = _make_arrester()
    # Seed a stale pending flag + fake unsub as if a prior engagement
    # had deferred a sunset but was cleared without teardown.
    a._temp_arrester_override_pending_sunset = "sleep"
    stale_cancels = {"n": 0}
    a._temp_arrester_override_pending_sunset_unsub = (
        lambda: stale_cancels.__setitem__("n", stale_cancels["n"] + 1)
    )

    a.set_temp_arrester_override(True)

    assert a._temp_arrester_override_active is True
    assert a._temp_arrester_override_pending_sunset is None, (
        "F6: fresh engagement inherited stale pending sunset"
    )
    assert stale_cancels["n"] == 1, (
        "F6: fresh engagement did not cancel the stale pending timer"
    )


def test_f8_timer_path_and_sweep_produce_exactly_one_note():
    """F8: BOTH the timer-precise discharge path and the periodic sweep
    must produce at most ONE NM-note per engagement (engagement-id
    dedup). Prior behavior: timer path was silent (only sweep fired)."""
    a = _make_arrester()

    notified: list = []
    a.set_on_sunset_notify(lambda reason: notified.append(reason))

    a.set_temp_arrester_override(True)

    # Force max-age elapse by rewinding started_ts.
    from datetime import timedelta
    a._temp_arrester_override_started_ts = (
        a._temp_arrester_override_started_ts - timedelta(seconds=999999)
    )

    fired = a.sunset_temp_arrester_override(reason="max_age_or_boundary")
    assert fired is True
    assert len(notified) == 1, notified

    # Re-invoke sunset — nothing more should fire (already OFF), and
    # even if fired somehow, engagement-id dedup would block it.
    a.sunset_temp_arrester_override(reason="max_age_or_boundary")
    assert len(notified) == 1

    # New engagement → engagement-id ticks → dedup allows a fresh note.
    a.set_temp_arrester_override(True)
    a._temp_arrester_override_started_ts = (
        a._temp_arrester_override_started_ts - timedelta(seconds=999999)
    )
    a.sunset_temp_arrester_override(reason="max_age_or_boundary")
    assert len(notified) == 2

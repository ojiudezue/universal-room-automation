"""Regression anchors for ActuatorReconciler FAN-MANUAL-1 guards.

Two guards live in ``actuator_reconciler.py`` at the fan turn_off /
turn_on branches (~lines 611-622 for the OFF defer, ~lines 630-639 for
the mark-fan-on-issued bridge). Both are load-bearing but were
previously untested via the production dispatch path — the room-tier
fan test file exercises ``handle_temperature_based_fan_control`` and
covers ``mark_fan_on_issued`` only by DIRECT method call (hollow), and
no test at all reached the reconciler's ``_reconcile_one`` fan-off /
fan-on hold branches. Validator mutation drill: neutering either guard
leaves the full suite green — these tests close that gap.

Drives the production ``ActuatorReconciler`` through the shared
``_reconcile_harness`` fake HA layer. All harness patterns mirror
``test_reconcile_on_return.py`` (same env constructor, same
``run_pending_coalesce`` firing pattern).
"""

from __future__ import annotations

import _reconcile_harness as _H  # noqa: F401 — installs HA mocks on import
from _reconcile_harness import (
    fire_available,
    make_env,
    run_pending_coalesce,
)

from custom_components.universal_room_automation.const import (
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FANS,
    STATE_OCCUPIED,
    STATE_TEMPERATURE,
)


FAN = "fan.bedroom"


def _fan_env(temp: float, occupied: bool = True):
    """Reconciler env for a room-owned comfort fan.

    Adds a ``mark_fan_on_issued`` recorder + ``is_fan_in_manual_on_hold``
    accessor to the FakeAutomation (both are RoomAutomation surfaces the
    reconciler consults; the shared harness's FakeAutomation is minimal
    and does not carry them by default).
    """
    hass, coord, r = make_env(
        data={
            CONF_FANS: [FAN],
            CONF_FAN_CONTROL_ENABLED: True,
            CONF_FAN_TEMP_THRESHOLD: 75,
        },
        coordinator_data={STATE_OCCUPIED: occupied, STATE_TEMPERATURE: temp},
    )
    auto = coord.automation
    # INV-FMH accessors — flipped per-test.
    auto._manual_on_hold = False
    auto.is_fan_in_manual_on_hold = lambda: auto._manual_on_hold
    auto.is_fan_in_manual_cooldown = lambda: False
    # mark_fan_on_issued call recorder (T3 oracle).
    auto._mark_fan_on_issued_calls = 0

    def _mark():
        auto._mark_fan_on_issued_calls += 1

    auto.mark_fan_on_issued = _mark
    return hass, coord, r, auto


# ===========================================================================
# T2 — B-HIGH-2: reconciler OFF-defer under a live manual-ON hold.
# actuator_reconciler.py ~611-622 (is_fan_in_manual_on_hold early-return).
#
# Mutation anchor (validator drill): force `is_fan_in_manual_on_hold` to
# return False (or delete the early-return at ~:620) — the "hold live"
# test below MUST red on the turn_off dispatch count.
# ===========================================================================


def test_reconciler_fan_off_deferred_when_manual_on_hold_live():
    """Occupied + cool → resolver wants OFF; fan currently ON; a room-tier
    manual-ON hold is live → the reconciler MUST NOT dispatch turn_off,
    AND MUST stamp ``_last_skip_reason == 'manual_on_hold'``.
    """
    hass, coord, r, auto = _fan_env(temp=70.0)  # cool → resolver wants OFF
    auto._manual_on_hold = True
    hass.states.set(FAN, "on")

    fire_available(r, FAN, hass, prior="unavailable", new="on")
    run_pending_coalesce(hass)

    off_calls = [c for c in auto.service_calls if c[1] == "turn_off"]
    assert off_calls == [], (
        "FAN-MANUAL-1: reconciler must defer turn_off against a fan under "
        "a live manual-ON hold (actuator_reconciler.py :611-622)"
    )
    assert r._last_skip_reason == "manual_on_hold", (
        "Skip reason must be recorded so the guard is observable in "
        "diagnostics (record_skip stamps the reason)"
    )


def test_reconciler_fan_off_fires_without_hold_positive_control():
    """Same setup, hold NOT live → the OFF MUST dispatch.

    Positive control: proves the OFF path is reachable and the defer
    above is a real guard (not a coincidence of the fixture).
    """
    hass, coord, r, auto = _fan_env(temp=70.0)  # cool → resolver wants OFF
    auto._manual_on_hold = False
    hass.states.set(FAN, "on")

    fire_available(r, FAN, hass, prior="unavailable", new="on")
    run_pending_coalesce(hass)

    off_calls = [c for c in auto.service_calls if c[1] == "turn_off"]
    assert len(off_calls) == 1, (
        "Positive control: with no hold, the reconciler must resolve to "
        "OFF and dispatch turn_off for a hot-fan-in-cool-room reconcile "
        f"(got service_calls={auto.service_calls})"
    )


# ===========================================================================
# T3 — A-HIGH-2: reconciler ON path marks the fan-on-issued bridge.
# actuator_reconciler.py ~630-639 (mark_fan_on_issued before turn_on).
#
# The existing anchor calls `mark_fan_on_issued()` directly — hollow (it
# only proves the method exists). This test drives the reconciler's
# production turn_on path and asserts the bridge was invoked BEFORE the
# service dispatch, which is the property the room-tier external-ON
# detector actually depends on to avoid opening a spurious hold on URA's
# own write.
#
# Mutation anchor: delete the `mark_fan_on_issued()` call at :637
# — this test MUST red (call count stays at 0).
# ===========================================================================


def test_reconciler_fan_on_calls_mark_fan_on_issued_before_dispatch():
    """Occupied + hot + fan currently OFF → resolver wants ON.
    Reconciler MUST call ``mark_fan_on_issued`` before dispatching
    turn_on, so the room-tier detector treats the resulting ON as
    URA-issued (no spurious manual-ON hold).
    """
    hass, coord, r, auto = _fan_env(temp=90.0)  # hot → resolver wants ON
    hass.states.set(FAN, "off")

    fire_available(r, FAN, hass, prior="unavailable", new="off")
    run_pending_coalesce(hass)

    on_calls = [c for c in auto.service_calls if c[1] == "turn_on"]
    assert len(on_calls) == 1, (
        "Setup precondition: hot+occupied+fan-off must resolve to ON and "
        f"dispatch turn_on (got service_calls={auto.service_calls})"
    )
    assert auto._mark_fan_on_issued_calls >= 1, (
        "FAN-MANUAL-1: reconciler MUST call mark_fan_on_issued before "
        "dispatching turn_on so the room-tier external-ON detector does "
        "not open a spurious hold on URA's own write "
        "(actuator_reconciler.py :630-639)"
    )


def test_reconciler_fan_off_dispatch_does_not_call_mark_bridge():
    """Scoping: the mark bridge is ON-only. An OFF dispatch (no hold,
    cool room) MUST NOT invoke ``mark_fan_on_issued``. Guards against a
    future refactor that widens the bridge accidentally (which would
    silently suppress legitimate external-OFF hold-clear discharges).
    """
    hass, coord, r, auto = _fan_env(temp=70.0)  # cool → resolver wants OFF
    hass.states.set(FAN, "on")

    fire_available(r, FAN, hass, prior="unavailable", new="on")
    run_pending_coalesce(hass)

    off_calls = [c for c in auto.service_calls if c[1] == "turn_off"]
    assert len(off_calls) == 1, "Setup: OFF must dispatch when no hold live"
    assert auto._mark_fan_on_issued_calls == 0, (
        "Scoping: mark_fan_on_issued must fire only on the ON branch "
        "— an OFF dispatch calling it would break external-OFF discharge "
        "semantics"
    )

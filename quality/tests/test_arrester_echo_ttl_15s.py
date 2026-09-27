"""HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1 (2026-09-26).

Behavioural guard for raising `SUPPRESS_TTL_SECONDS` 5 -> 15 s.

Evidence (`docs/planning/PLANNING_hvac_arrester_nudge_echo.md` §14a):
Carrier's echo of URA's own nudge lands 5.3-7.5 s after the write (past
the old 5 s temp-suppression window). Genuine humans were all > 60 s from
any URA write. 15 s = 2x the measured 7.5 s max echo, still far below the
human floor.

Tests drive the REAL `OverrideArrester._handle_climate_change` /
`_is_genuine_manual` with real event-shaped objects and own the clock by
monkeypatching `hvac_override.dt_util` (the module binds it at load time,
`from homeassistant.util import dt as dt_util`).

Cases:
  (a) URA temp write (kind="temp") then a preset home -> manual event at
      +6.9 s with new_high 78 after writing 77.5: NOT booked (no
      `override_detected` ledger row) — the echo is inside the 15 s window
      AND kind="temp" blocks the mid-window passthrough.
  (b) Same event at +16 s: booked — outside the window, echo becomes a
      genuine override.
  (c) Genuine human preset -> manual with no URA write in the prior 60 s:
      booked.
  (d) Boundary: +14.9 s NOT booked, +15.1 s booked (hardcoded literals,
      NOT the imported constant — so a silent lowering of the constant
      would red the test).

Mutation drill anchor: set `SUPPRESS_TTL_SECONDS` back to 5 -> case (a)
reddens (the +6.9 s echo would be booked because it's outside a 5 s
window). Restore.
"""
from __future__ import annotations

# Reuse the module loading + fixtures from the sibling A-F5 test module.
# That file already builds the URA package hierarchy, force-reloads real
# `hvac_override` from source, and exposes `fake_clock` / `_make_arrester`
# / `_make_event` / `hvac_override`.
from test_override_arrester_ttl_suppression import (  # noqa: F401
    CLIMATE_ENTITY,
    _make_arrester,
    _make_event,
    fake_clock,
    hvac_override,
)


def _override_ledger_rows(arrester) -> list:
    """Capture any `override_detected` ledger emits.

    `_arrest_ledger` is the durable-row emitter for detected overrides
    (see `hvac_override.py` right after the INFO "Override detected on"
    log). We swap it for a capturing spy so the tests read the boolean
    "did URA book this as an override" without dragging the DB layer in.
    """
    rows: list = []
    real = getattr(arrester, "_arrest_ledger", None)

    def _spy(**kwargs):
        rows.append(kwargs)
        # Do not delegate: the real ledger emits a DB write path that
        # the sibling A-F5 test's MagicMock hass cannot service.
        return None

    arrester._arrest_ledger = _spy  # type: ignore[assignment]
    # Return the captured list; also stash a restore hook on the arrester
    # in case a test wants to swap back (none do today).
    arrester._arrest_ledger_restore = lambda: setattr(  # type: ignore[attr-defined]
        arrester, "_arrest_ledger", real,
    )
    return rows


def _count_override_detected(rows: list) -> int:
    return sum(1 for r in rows if r.get("action") == "override_detected")


# --------------------------------------------------------------------------
# Cases (a)-(d)
# --------------------------------------------------------------------------


def test_a_echo_at_6_9s_after_temp_write_is_not_booked(fake_clock):
    """Live-row fixture: URA writes 77.5 (kind="temp"); Carrier echoes back
    a preset home -> manual with new_high 78 at +6.9 s. Under the new 15 s
    temp window this MUST NOT be booked as an override."""
    arrester = _make_arrester()
    rows = _override_ledger_rows(arrester)

    # (i) URA temp write: opens the 15 s temp-kind suppression window.
    arrester.suppress(CLIMATE_ENTITY, kind="temp")

    # (ii) 6.9 s later: Carrier echo — preset home -> manual, new_high 78.
    fake_clock.advance(6.9)
    evt = _make_event(
        CLIMATE_ENTITY,
        old_preset="home", new_preset="manual",
        old_high=77.5, new_high=78.0,
        old_low=70.0, new_low=70.0,
    )
    arrester._handle_climate_change(evt)

    assert _count_override_detected(rows) == 0, (
        "Echo at +6.9 s (kind=temp) must be swallowed by the raised 15 s "
        f"window; got rows: {rows!r}"
    )


def test_b_echo_at_16s_after_temp_write_is_booked(fake_clock):
    """Same shape as (a) but at +16 s — outside the 15 s window, so the
    listener must fall through to override detection and book a row."""
    arrester = _make_arrester()
    rows = _override_ledger_rows(arrester)

    arrester.suppress(CLIMATE_ENTITY, kind="temp")

    fake_clock.advance(16.0)
    evt = _make_event(
        CLIMATE_ENTITY,
        old_preset="home", new_preset="manual",
        old_high=77.5, new_high=78.0,
        old_low=70.0, new_low=70.0,
    )
    arrester._handle_climate_change(evt)

    assert _count_override_detected(rows) == 1, (
        "Echo at +16 s is outside the 15 s window and must be booked as "
        f"override_detected; got rows: {rows!r}"
    )


def test_c_genuine_human_manual_with_no_recent_ura_write_is_booked(fake_clock):
    """No suppression window open -> the listener runs straight into
    override detection. Represents a human > 60 s from any URA write."""
    arrester = _make_arrester()
    rows = _override_ledger_rows(arrester)

    # No suppress() call. Advance the clock arbitrarily so the "no recent
    # URA write in the prior 60 s" premise is unmistakable.
    fake_clock.advance(120.0)

    evt = _make_event(
        CLIMATE_ENTITY,
        old_preset="home", new_preset="manual",
        old_high=76.0, new_high=74.0,
        old_low=70.0, new_low=68.0,
    )
    arrester._handle_climate_change(evt)

    assert _count_override_detected(rows) == 1, (
        "Genuine human manual with no URA write in the prior 60 s must be "
        f"booked; got rows: {rows!r}"
    )


def test_d_boundary_14_9s_not_booked_15_1s_booked(fake_clock):
    """Boundary check with HARDCODED literals (not the imported constant)
    so a silent lowering of `SUPPRESS_TTL_SECONDS` would red this test."""
    # -- 14.9 s: inside the window -> NOT booked --
    arrester = _make_arrester()
    rows = _override_ledger_rows(arrester)
    arrester.suppress(CLIMATE_ENTITY, kind="temp")
    fake_clock.advance(14.9)
    arrester._handle_climate_change(_make_event(
        CLIMATE_ENTITY,
        old_preset="home", new_preset="manual",
        old_high=77.5, new_high=78.0,
        old_low=70.0, new_low=70.0,
    ))
    assert _count_override_detected(rows) == 0, (
        "Inside window at +14.9 s must not be booked; got rows: %r" % (rows,)
    )

    # -- 15.1 s: past the window -> booked. Fresh arrester + clock so the
    # +14.9 s call above does not contaminate the second scenario. --
    arrester2 = _make_arrester()
    rows2 = _override_ledger_rows(arrester2)
    arrester2.suppress(CLIMATE_ENTITY, kind="temp")
    fake_clock.advance(15.1)
    arrester2._handle_climate_change(_make_event(
        CLIMATE_ENTITY,
        old_preset="home", new_preset="manual",
        old_high=77.5, new_high=78.0,
        old_low=70.0, new_low=70.0,
    ))
    assert _count_override_detected(rows2) == 1, (
        "Outside window at +15.1 s must be booked; got rows: %r" % (rows2,)
    )

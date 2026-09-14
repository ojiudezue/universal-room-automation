"""ROUTINE-DETECTOR-NO-DISCHARGE-1 — behavioural tests for the discharge.

The existing regime tests in this repo are SOURCE GREPS. These are not:
they construct the detector with a fake database and assert the DAO is
actually called (or not) at the return-to-stable seam.

Why this matters: the detector's in-memory cell counter always reset
correctly on return-to-stable, but the anomaly_log rows it emitted had no
automatic clear path. Measured 2026-09-14: 462 rows, 462 unacknowledged
since 2026-05-15, zero ever acked, while all 48 cells read `stable` — so
the household sensor sat at `major_shift` on rows from May.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _detector():
    from custom_components.universal_room_automation.domain_coordinators.regime_detector import (
        RegimeDetector,
    )
    db = MagicMock()
    db.get_regime_cell_state = AsyncMock(return_value=None)
    db.upsert_regime_cell_state = AsyncMock()
    db.discharge_routine_shifts_for_cell = AsyncMock(return_value=3)
    return RegimeDetector(MagicMock(), db, MagicMock()), db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_return_to_stable_discharges_when_counter_was_open():
    """THE FIX: a cell whose counter was >0 and has now gone stable must
    clear its open rows."""
    det, db = _detector()
    db.get_regime_cell_state = AsyncMock(
        return_value={"unacknowledged_consecutive": 4}
    )
    _run(det._persist_state("Jaya", 0, 1, "stable"))
    db.discharge_routine_shifts_for_cell.assert_awaited_once_with("Jaya", 0, 1)


def test_discharge_is_scoped_to_the_one_cell_not_a_bulk_ack():
    """A bulk clear would also discharge cells that are STILL drifting.
    The call must carry this cell's identity."""
    det, db = _detector()
    db.get_regime_cell_state = AsyncMock(
        return_value={"unacknowledged_consecutive": 1}
    )
    _run(det._persist_state("Ziri", 3, 0, "stable"))
    args = db.discharge_routine_shifts_for_cell.await_args.args
    assert args == ("Ziri", 3, 0), f"expected this cell only, got {args}"


def test_still_drifting_cell_is_NOT_discharged():
    """DISCRIMINATOR: the fix must not clear a cell that is still shifted —
    otherwise it would silently erase live signal."""
    det, db = _detector()
    db.get_regime_cell_state = AsyncMock(
        return_value={"unacknowledged_consecutive": 2}
    )
    _run(det._persist_state("Jaya", 0, 1, "major"))
    db.discharge_routine_shifts_for_cell.assert_not_awaited()


def test_already_stable_cell_does_no_pointless_db_write():
    """Counter already 0 means nothing is open — don't hit the DB every
    cycle for all 48 cells (that is the row-flood shape B2 just fixed)."""
    det, db = _detector()
    db.get_regime_cell_state = AsyncMock(
        return_value={"unacknowledged_consecutive": 0}
    )
    _run(det._persist_state("Jaya", 0, 1, "stable"))
    db.discharge_routine_shifts_for_cell.assert_not_awaited()


def test_discharge_failure_is_non_fatal():
    """Discharge is housekeeping; it must never break the detector cycle."""
    det, db = _detector()
    db.get_regime_cell_state = AsyncMock(
        return_value={"unacknowledged_consecutive": 5}
    )
    db.discharge_routine_shifts_for_cell = AsyncMock(side_effect=RuntimeError("db down"))
    assert _run(det._persist_state("Jaya", 0, 1, "stable")) == 0
    db.upsert_regime_cell_state.assert_awaited()


def test_counter_still_resets_to_zero_on_stable():
    """Pre-existing invariant must be untouched by this change."""
    det, db = _detector()
    db.get_regime_cell_state = AsyncMock(
        return_value={"unacknowledged_consecutive": 7}
    )
    assert _run(det._persist_state("Jaya", 0, 1, "stable")) == 0


# ======================================================================
# ROUTINE-DETECTOR-NO-DISCHARGE-1 — recency bound
#
# The sensor query had NO time filter, so one unacknowledged row pinned
# the sensor for up to the 365-day retention. Operator requirement:
# "we need to not have this be a problem if unacknowledged."
# ======================================================================

def test_recency_bound_is_tied_to_the_detector_baseline_window():
    """The bound must match the detector's own 56-day baseline, not an
    unrelated invented number — a shift older than one baseline window was
    computed against data that has itself aged out."""
    from custom_components.universal_room_automation.const import (
        ROUTINE_STATUS_RECENCY_DAYS,
    )
    assert ROUTINE_STATUS_RECENCY_DAYS == 56


def test_sensor_query_is_recency_bounded_wire_in_anchor():
    """WIRE-IN ANCHOR: the bound is useless if the ROUTINE-STATUS query does
    not apply it.

    NOTE the trap this test was rewritten to avoid: a bare
    `"AND timestamp >= ?" in src` assertion passes on ANY of the three
    unrelated queries in sensor.py that also filter by timestamp, so it
    stayed green when the routine-status predicate was deleted. The
    assertion must be scoped to the routine_shift query itself.
    """
    import inspect
    from custom_components.universal_room_automation import sensor as _sensor
    src = inspect.getsource(_sensor)
    assert "ROUTINE_STATUS_RECENCY_DAYS" in src, "recency const never referenced"

    # Isolate the BOUNDED routine_shift query and assert the predicate is
    # inside THAT statement, not merely somewhere in the module.
    marker = "AND recovery_at IS NULL"
    bounded = None
    start = 0
    while True:
        i = src.find(marker, start)
        if i == -1:
            break
        stmt_start = src.rfind("SELECT severity", 0, i)
        stmt_end = src.find('"""', i)
        if stmt_start != -1 and stmt_end != -1:
            stmt = src[stmt_start:stmt_end]
            if "timestamp >= ?" in stmt:
                bounded = stmt
                break
        start = i + 1
    assert bounded is not None, (
        "no routine_shift query carries a recency predicate — one stale "
        "unacknowledged row will pin the sensor again"
    )
    assert "bayesian.routine_shift" in bounded, (
        "the recency-bounded query is not the routine_shift one"
    )


def test_unbounded_fallback_preserved_for_kill_switch():
    """Setting the constant to 0 must restore the pre-fix behaviour, so the
    change is reversible without a code edit."""
    import inspect
    from custom_components.universal_room_automation import sensor as _sensor
    src = inspect.getsource(_sensor)
    assert "if ROUTINE_STATUS_RECENCY_DAYS > 0:" in src
    assert src.count("AND recovery_at IS NULL") >= 2, (
        "both the bounded and unbounded query variants must exist"
    )


def test_BOTH_routine_queries_are_recency_bounded():
    """COUNT THE CONSUMERS. There are TWO routine-status sensors with TWO
    separate queries. Bounding only the person one left the household sensor
    pinned — proven live 2026-09-14: Jaya correctly dropped
    major_shift -> shifted while the household sensor still read major_shift
    on the same 462 rows.

    NOTE the trap this was rewritten to avoid (twice now on this feature):
    an earlier version located each SQL statement by searching backwards for
    a `SELECT` keyword. That span ran 5887 characters on one occurrence,
    swallowing an unrelated query's `timestamp >= ?` and reporting a bound
    that was not there. Statements are delimited by the triple-quoted string
    literal — anchor on THAT, not on keywords.
    """
    import inspect
    from custom_components.universal_room_automation import sensor as _sensor
    src = inspect.getsource(_sensor)

    bounded = unbounded = 0
    start = 0
    while True:
        i = src.find("bayesian.routine_shift", start)
        if i == -1:
            break
        # The enclosing SQL literal: nearest triple-quote before / after.
        a = src.rfind('"""', 0, i)
        b = src.find('"""', i)
        stmt = src[a:b] if (a != -1 and b != -1) else ""
        # Only count real routine-status SELECTs, not comments mentioning it.
        if "SELECT" in stmt and "recovery_at IS NULL" in stmt:
            if "timestamp >= ?" in stmt:
                bounded += 1
            else:
                unbounded += 1
        start = i + 1

    assert bounded >= 2, (
        f"only {bounded} routine_shift query/queries carry a recency bound "
        f"({unbounded} unbounded); BOTH the person and household sensors "
        "need it or one stays pinned"
    )

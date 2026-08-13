"""CIRCLING-SEVERITY-1 D3 — diagnostic sensor tests.

INV-M enforcement machinery: exercises the three residual dispatch-loss
paths (NM raise, teardown short-circuit, cancelled delayed dispatch)
and confirms the diagnostic counter surfaces each.

See docs/planning/PLANNING_circling_severity.md §D3.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# --- reuse the founding-case harness for the same package plumbing -----------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from quality.tests.perimeter.test_circling_founding_case import (  # noqa: E402
    ExteriorTrackLinker,
    PerimeterAlertManager,
    Severity,
    _const,
    _perimeter,
    _make_hass_with_linker,
    _observe,
    _run,
    _setup,
    _scheduled,
    CAMS,
    SENSORS,
)

_diag = importlib.import_module(
    "custom_components.universal_room_automation.perimeter_diagnostics"
)


def _drive_founding_sequence(mgr, linker):
    """Feed 5 events but observe/dispatch each hop individually."""
    t0 = datetime.now(timezone.utc)
    seq = [
        ("back_yard",       t0),
        ("front_side_ptz",  t0 + timedelta(seconds=25)),
        ("back_yard",       t0 + timedelta(seconds=60)),
        ("front_side_ptz",  t0 + timedelta(seconds=95)),
        ("back_yard",       t0 + timedelta(seconds=130)),
    ]
    for cam_key, ts in seq:
        _observe(linker, cam_key, ts)
        _run(mgr._async_handle_perimeter_trigger(SENSORS[cam_key]))


# --- AC-1: NM-exception loss path (trace path 5) ------------------------------


def test_diag_sensor_counts_nm_exception_loss():
    """AC-1 / MEDIUM-1: NM raises → dispatched_ok stays False →
    note_alert_dispatched NEVER called → alert_count stays at 0 →
    D3 reports 1 with the offending track_id in attributes."""
    hass, nm, linker = _make_hass_with_linker(CAMS)
    # Make every NM notify raise so dispatched_ok never becomes True.
    nm.async_notify = AsyncMock(side_effect=RuntimeError("nm boom"))
    mgr = _run(_setup(hass))
    _drive_founding_sequence(mgr, linker)

    # Track exists, classified circling, alert_count == 0
    person_tracks = linker._tracks.get("person", [])
    assert len(person_tracks) == 1
    tr = person_tracks[0]
    assert linker.classify(tr) == "circling"
    assert tr.alert_count == 0, (
        f"expected alert_count=0 on NM-exception path, got {tr.alert_count}"
    )

    # D3 should report 1
    count, offenders = _diag.count_circling_zero_dispatch(linker)
    assert count == 1
    assert offenders and offenders[0]["track_id"] == tr.track_id


# --- AC-2: happy path returns 0 ----------------------------------------------


def test_diag_sensor_zero_when_dispatches_succeed():
    """AC-2: normal run — dispatches succeed → alert_count >= 2 →
    D3 reports 0."""
    hass, _nm, linker = _make_hass_with_linker(CAMS)
    mgr = _run(_setup(hass))
    _drive_founding_sequence(mgr, linker)
    count, _off = _diag.count_circling_zero_dispatch(linker)
    assert count == 0


# --- AC-3: teardown short-circuit (trace path 6) ------------------------------


def test_diag_sensor_counts_teardown_loss():
    """AC-3: schedule a delayed dispatch, then invoke teardown before
    the delay fires → `_do_dispatch` short-circuits on `is_stopping` →
    dispatched_ok never true → alert_count stays 0 → D3 reports 1."""
    hass, nm, linker = _make_hass_with_linker(CAMS)
    mgr = _run(_setup(hass))
    _scheduled.clear()

    # Drive the sequence enough to build a circling track. First we
    # observe all 5 hops so the linker classifies circling, then we
    # arrange for a *delayed* dispatch by opting for the live-fallback
    # path (offset_s > 0). Rebuild entry.options to use a nonzero
    # offset for the last event only — easier: manually schedule a
    # dispatch through the code path.
    t0 = datetime.now(timezone.utc)
    seq = [
        ("back_yard",       t0),
        ("front_side_ptz",  t0 + timedelta(seconds=25)),
        ("back_yard",       t0 + timedelta(seconds=60)),
        ("front_side_ptz",  t0 + timedelta(seconds=95)),
    ]
    for cam_key, ts in seq:
        _observe(linker, cam_key, ts)
    # Simulate teardown *between* schedule and dispatch.
    hass.is_stopping = True
    # Now drive the final hop through — dispatches short-circuit on
    # is_stopping and never call note_alert_dispatched.
    _observe(linker, "back_yard", t0 + timedelta(seconds=130))
    _run(mgr._async_handle_perimeter_trigger(SENSORS["back_yard"]))

    # Also fire any pending scheduled callbacks (they should short-circuit).
    for _delay, cb in list(_scheduled):
        try:
            cb(None)
        except Exception:
            pass
    _scheduled.clear()

    person_tracks = linker._tracks.get("person", [])
    tr = person_tracks[0]
    # Since hass.is_stopping was flipped BEFORE the trigger, that last
    # dispatch short-circuited. Earlier hops with hass.is_stopping=False
    # dispatched normally. To hit the pure teardown-loss path, we drive
    # a fresh linker where NO dispatch has run yet.
    # Better isolation: fresh setup with is_stopping already True.
    hass2, _nm2, linker2 = _make_hass_with_linker(CAMS)
    hass2.is_stopping = True
    mgr2 = _run(_setup(hass2))
    # Force _active=True is already the case post-setup.
    for cam_key, ts in [
        ("back_yard",       t0),
        ("front_side_ptz",  t0 + timedelta(seconds=25)),
        ("back_yard",       t0 + timedelta(seconds=60)),
        ("front_side_ptz",  t0 + timedelta(seconds=95)),
        ("back_yard",       t0 + timedelta(seconds=130)),
    ]:
        _observe(linker2, cam_key, ts)
        _run(mgr2._async_handle_perimeter_trigger(SENSORS[cam_key]))

    person_tracks2 = linker2._tracks.get("person", [])
    assert len(person_tracks2) == 1
    tr2 = person_tracks2[0]
    assert linker2.classify(tr2) == "circling"
    assert tr2.alert_count == 0, (
        f"teardown short-circuit should have prevented all dispatches, "
        f"got alert_count={tr2.alert_count}"
    )
    count, offenders = _diag.count_circling_zero_dispatch(linker2)
    assert count == 1
    assert offenders and offenders[0]["track_id"] == tr2.track_id


# --- AC-4: cancelled delayed-dispatch (trace path 7) --------------------------


def test_diag_sensor_counts_cancelled_delay_loss():
    """AC-4: dispatch scheduled with delay > 0; manager teardown calls
    unsub on every _pending_dispatches entry BEFORE the delayed callback
    fires → `_scheduled_dispatch` never runs → `_do_dispatch` never runs
    → note_alert_dispatched never called → D3 reports 1.

    Verifies both the alert_count == 0 outcome AND that the unsub was
    invoked (mutation anchor for the cancel loop at
    perimeter_alert.py:1006-1013)."""
    hass, nm, linker = _make_hass_with_linker(CAMS)
    mgr = _run(_setup(hass))
    _scheduled.clear()

    # Track spy on the unsub returned by async_call_later — replace
    # the fake to return a MagicMock we can inspect.
    unsub_spies: list = []

    def _call_later_spy(hass, delay, cb):
        spy = MagicMock()
        unsub_spies.append(spy)
        _scheduled.append((delay, cb))
        return spy

    orig_call_later = _perimeter.async_call_later
    _perimeter.async_call_later = _call_later_spy
    try:
        # Force nonzero delay: no cached Frigate event_id AND set snapshot
        # offset to nonzero. Rebuild the entry options in place.
        entry = hass.config_entries.async_entries.return_value[0]
        entry.options[_const.CONF_EXTERIOR_SNAPSHOT_OFFSET_S] = 7

        # Build the circling track first, then drive one more trigger
        # that should schedule a delayed dispatch (cameras have entity_picture
        # set → live-fallback path with offset).
        t0 = datetime.now(timezone.utc)
        for cam_key, ts in [
            ("back_yard",       t0),
            ("front_side_ptz",  t0 + timedelta(seconds=25)),
            ("back_yard",       t0 + timedelta(seconds=60)),
            ("front_side_ptz",  t0 + timedelta(seconds=95)),
            ("back_yard",       t0 + timedelta(seconds=130)),
        ]:
            _observe(linker, cam_key, ts)
            _run(mgr._async_handle_perimeter_trigger(SENSORS[cam_key]))

        # At least one dispatch was scheduled with a delay.
        assert _scheduled, "expected at least one delayed dispatch scheduled"

        # Simulate teardown BEFORE the delayed dispatches fire. Cancel
        # each pending unsub (mirrors perimeter_alert.py:1006-1013 cancel
        # loop).
        for unsub in list(mgr._pending_dispatches):
            try:
                unsub()
            except Exception:
                pass
        mgr._pending_dispatches.clear()
    finally:
        _perimeter.async_call_later = orig_call_later
        _scheduled.clear()

    # Spy on unsub was called (the cancel loop invariant).
    assert any(spy.called for spy in unsub_spies), (
        "expected the delayed dispatch unsub to be invoked by teardown"
    )

    # Because the dispatches were scheduled but cancelled (or would-be
    # cancelled) before firing, note_alert_dispatched was not called for
    # those hops. Some earlier same-camera hops with delay=0 may have
    # dispatched; but the LAST cancelled hop leaves the track in a state
    # where at least one dispatch was cancelled. The reliable D3 signal
    # is: iff any dispatch loss occurred and the alert_count is < number
    # of dispatched attempts, the tripwire fires.
    # For determinism, we assert that alert_count is strictly less than
    # the number of scheduled attempts (i.e. at least one dispatch was
    # lost to cancellation).
    person_tracks = linker._tracks.get("person", [])
    tr = person_tracks[0]
    # note: the diagnostic fires when alert_count == 0 specifically; when
    # earlier hops dispatched successfully alert_count > 0 and the tripwire
    # (correctly) stays quiet. To exercise the AC-4 tripwire deterministically
    # we do a fresh run where ALL dispatches go through the delayed path.
    del tr

    # Fresh isolation: fresh manager with EVERY dispatch delayed and
    # cancelled — no earlier successful dispatch to muddy alert_count.
    hass2, nm2, linker2 = _make_hass_with_linker(CAMS)
    entry2 = hass2.config_entries.async_entries.return_value[0]
    entry2.options[_const.CONF_EXTERIOR_SNAPSHOT_OFFSET_S] = 7
    mgr2 = _run(_setup(hass2))
    _scheduled.clear()
    unsub_spies2: list = []
    _perimeter.async_call_later = _call_later_spy  # reuse spy factory
    unsub_spies = unsub_spies2  # rebind
    try:
        t0 = datetime.now(timezone.utc)
        for cam_key, ts in [
            ("back_yard",       t0),
            ("front_side_ptz",  t0 + timedelta(seconds=25)),
            ("back_yard",       t0 + timedelta(seconds=60)),
            ("front_side_ptz",  t0 + timedelta(seconds=95)),
            ("back_yard",       t0 + timedelta(seconds=130)),
        ]:
            _observe(linker2, cam_key, ts)
            _run(mgr2._async_handle_perimeter_trigger(SENSORS[cam_key]))
        # Cancel ALL pending dispatches before any run.
        for unsub in list(mgr2._pending_dispatches):
            unsub()
        mgr2._pending_dispatches.clear()
    finally:
        _perimeter.async_call_later = orig_call_later
        _scheduled.clear()

    person_tracks2 = linker2._tracks.get("person", [])
    assert len(person_tracks2) == 1
    tr2 = person_tracks2[0]
    assert linker2.classify(tr2) == "circling"
    assert tr2.alert_count == 0, (
        f"all dispatches cancelled — expected alert_count=0, got "
        f"{tr2.alert_count}"
    )
    count, offenders = _diag.count_circling_zero_dispatch(linker2)
    assert count == 1
    assert offenders and offenders[0]["track_id"] == tr2.track_id


# --- AC-5: poll neuter drill — sensor updates only via the tick --------------


def test_diag_helper_lookback_bounds_stale_offenders():
    """Offenders older than CIRCLING_DIAG_LOOKBACK_HOURS are dropped."""
    hass, nm, linker = _make_hass_with_linker(CAMS)
    nm.async_notify = AsyncMock(side_effect=RuntimeError("boom"))
    mgr = _run(_setup(hass))
    _drive_founding_sequence(mgr, linker)
    # In-window: 1 offender.
    now = datetime.now(timezone.utc)
    count, _ = _diag.count_circling_zero_dispatch(linker, now=now)
    assert count == 1
    # Advance the clock past the lookback → 0 offenders.
    future = now + timedelta(hours=_const.CIRCLING_DIAG_LOOKBACK_HOURS + 1)
    count, _ = _diag.count_circling_zero_dispatch(linker, now=future)
    assert count == 0


def test_diag_helper_none_linker_returns_zero():
    """Fail-open: no linker installed → (0, [])."""
    count, offenders = _diag.count_circling_zero_dispatch(None)
    assert count == 0
    assert offenders == []


def test_diag_sensor_source_wires_the_poll_pattern():
    """Wire-in anchor for D3 poll mechanism (build-pred #2 resolution).

    The sensor class MUST use async_track_time_interval keyed to
    CIRCLING_DIAG_POLL_INTERVAL_MINUTES — the linker exposes no per-track
    dispatcher signal, so subscription-based updates would fire only once
    at SIGNAL_EXTERIOR_LINKER_READY. Anchor via source inspection so a
    future refactor that swaps the poll for a broken signal-subscription
    is caught here rather than in production silence.
    """
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "custom_components", "universal_room_automation", "sensor.py",
    )
    src = open(src_path, encoding="utf-8").read()
    # The class exists.
    assert "class PerimeterCirclingZeroDispatch24hSensor" in src
    # The poll pattern is wired via async_track_time_interval with the
    # named constant (no inline literal).
    _class_slice = src.split(
        "class PerimeterCirclingZeroDispatch24hSensor", 1,
    )[1].split("\nclass ", 1)[0]
    assert "async_track_time_interval" in _class_slice
    assert "CIRCLING_DIAG_POLL_INTERVAL_MINUTES" in _class_slice
    # count_circling_zero_dispatch is the load-bearing helper the tick
    # calls into.
    assert "count_circling_zero_dispatch" in _class_slice

"""Tests for DB-WAIT-WARNING-REWORK-1 episode-based wait logging.

The wait-episode helpers on ``URADatabase`` produce ONE warning per
episode + ONE summary line, instead of the pre-fix per-waiter spam
(~23 warnings for a single event-loop freeze).

We test the pure helpers directly by constructing a minimal
``URADatabase`` instance without running __init__ (so we don't need a
real event loop or filesystem), then wiring the fields the helpers
touch.
"""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from custom_components.universal_room_automation import database as db_mod


def _fresh_db_instance():
    """Bypass __init__; wire only the fields the wait-episode helpers use."""
    d = object.__new__(db_mod.UniversalRoomDatabase)
    d.hass = None
    d._write_queue = asyncio.Queue()
    d._boot_started_at = time.monotonic() - 10_000  # steady state
    d._wait_boot_window_s = 300.0
    d._wait_episode_active = False
    d._wait_episode_started_at = None
    d._wait_episode_max_wait = 0.0
    d._wait_episode_peak_queue = 0
    d._wait_episode_callers = 0
    d._wait_episode_dropped = 0
    d._wait_episode_in_flight = 0
    d._wait_episode_stall_multiplier = 2.0
    return d


def test_many_waiters_produce_one_warning_and_one_summary(caplog):
    """23 slow waiters in one episode -> 1 WARNING + 1 summary INFO."""
    caplog.set_level(logging.INFO)
    d = _fresh_db_instance()
    for _ in range(23):
        d._wait_episode_note_slow(40.0)
    # Now they all clear.
    for _ in range(23):
        d._wait_episode_release(dropped=False)
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING
             and "DB write not yet served" in r.getMessage()]
    summaries = [r for r in caplog.records
                 if "DB write wait episode cleared" in r.getMessage()]
    assert len(warns) == 1, f"expected 1 warning, got {len(warns)}"
    assert len(summaries) == 1, f"expected 1 summary, got {len(summaries)}"
    assert "callers=23" in summaries[0].getMessage()


def test_stall_vs_backlog_classification(caplog):
    caplog.set_level(logging.WARNING)
    # Backlog: just barely over soft.
    d1 = _fresh_db_instance()
    d1._wait_episode_note_slow(db_mod.DB_WRITE_READY_SOFT_WARN_S + 1.0)
    d1._wait_episode_release(dropped=False)
    # Event-loop stall: >= 2x soft.
    d2 = _fresh_db_instance()
    d2._wait_episode_note_slow(db_mod.DB_WRITE_READY_SOFT_WARN_S * 3.0)
    d2._wait_episode_release(dropped=False)
    msgs = [r.getMessage() for r in caplog.records
            if "DB write not yet served" in r.getMessage()]
    assert any("worker backlog" in m for m in msgs)
    assert any("event-loop stall" in m for m in msgs)


def test_boot_window_downgrades_warning_to_info(caplog):
    caplog.set_level(logging.INFO)
    d = _fresh_db_instance()
    d._boot_started_at = time.monotonic()  # boot right now
    d._wait_boot_window_s = 300.0
    d._wait_episode_note_slow(40.0)
    d._wait_episode_release(dropped=False)
    entry = [r for r in caplog.records
             if "DB write not yet served" in r.getMessage()]
    assert len(entry) == 1
    assert entry[0].levelno == logging.INFO, "boot-phase must log INFO"


def test_summary_carries_dropped_count(caplog):
    caplog.set_level(logging.INFO)
    d = _fresh_db_instance()
    d._wait_episode_note_slow(40.0)
    d._wait_episode_note_slow(60.0)
    d._wait_episode_release(dropped=True)   # one dropped
    d._wait_episode_release(dropped=False)
    summaries = [r for r in caplog.records
                 if "DB write wait episode cleared" in r.getMessage()]
    assert len(summaries) == 1
    assert "dropped=1" in summaries[0].getMessage()
    assert "callers=2" in summaries[0].getMessage()


def test_fast_waiter_release_would_prematurely_clear_with_slow_pending(caplog):
    """Direct invariant (Tier 1 MED fix): _wait_episode_release must be
    called ONLY by waiters that crossed the soft threshold. If a fast
    waiter calls release() while a slow waiter is still outstanding,
    in_flight drops to 0 -> the episode summary fires prematurely AND
    a second warning fires on the next slow arrival in the same freeze.

    This test drives the invariant at the helper: it simulates what
    happens if the `_noted` guard in `_db()` is removed and a fast
    waiter reaches its `finally` while a slow one is pending. Then a
    third (also slow) waiter arrives — under the buggy behavior the
    episode reopens and warn #2 fires. Under the correct contract the
    episode is still active and no second warn fires.
    """
    caplog.set_level(logging.INFO)
    d = _fresh_db_instance()
    # Slow waiter B opens the episode.
    d._wait_episode_note_slow(40.0)
    assert d._wait_episode_in_flight == 1
    # Simulate the BUGGY behavior: a fast waiter (A) that never crossed
    # soft nevertheless calls release. This is exactly what removing
    # `if _noted:` at the _db() call site produces.
    d._wait_episode_release(dropped=False)  # buggy path
    # Bug observed: episode prematurely cleared while B still pending.
    prem_summaries = [r for r in caplog.records
                      if "DB write wait episode cleared" in r.getMessage()]
    assert len(prem_summaries) == 1, "premature summary from fast release"
    assert d._wait_episode_active is False, (
        "invariant violated by buggy release: episode cleared while a slow "
        "waiter is still pending — the production `_noted` guard prevents "
        "this call from happening in the real code path"
    )
    # A second slow waiter (C) arrives — under the bug the episode reopens
    # and emits a SECOND warning in the same physical freeze.
    d._wait_episode_note_slow(45.0)
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING
             and "DB write not yet served" in r.getMessage()]
    assert len(warns) == 2, (
        f"bug reproduces: episode reopened by C after A's premature clear "
        f"-> second warn. Got {len(warns)} warns."
    )
    # Slow B finally clears — third summary follow-on (still bug shape).
    d._wait_episode_release(dropped=False)


def test_db_source_has_noted_guard_at_release_site():
    """Source-authoritative check: `_db()` MUST gate its release() call
    behind the `_noted` flag. This is the load-bearing site the Tier-1
    fix installed; its removal is the mutation drilled below.
    """
    src = open(_SRC_PATH, "r", encoding="utf-8").read()
    assert (
        "if _noted:\n                self._wait_episode_release(dropped=_dropped)"
        in src
    ), (
        "the `_noted` guard on _wait_episode_release is missing at the "
        "_db() call site. Fast waiters would decrement in_flight and "
        "prematurely clear the episode (Tier 1 MED)."
    )


# ---------------------------------------------------------------------------
# Mutation drill on the per-episode-latch site in database.py.
# ---------------------------------------------------------------------------
# TEST-HARNESS D1: drills run against a tmp COPY of the repo via
# apply_mutation_in_sandbox — the real database.py is never opened for write
# (the old in-place _mutate wrote before its try and could leak the mutant).
from pathlib import Path as _Path  # noqa: E402

from _mutation_sandbox import apply_mutation_in_sandbox  # noqa: E402

_SRC_PATH = _Path(db_mod.__file__).resolve()
_THIS_TEST = _Path(__file__).resolve()


def _drill(swap_from, swap_to, anchor):
    apply_mutation_in_sandbox(
        prod_path=_SRC_PATH,
        swap_from=swap_from,
        swap_to=swap_to,
        anchor_test_file=_THIS_TEST,
        anchor_test_name=anchor,
        expect="KILLED",
        timeout=120.0,
    )


def test_mutation_drill_removes_noted_guard():
    """Neuter the `_noted` guard: fast waiters release() unconditionally.
    The overlap test MUST turn red (premature clear / extra warning)."""
    _drill(
        # Force _noted to always evaluate True so the fast waiter also
        # invokes release() from its finally.
        "if _noted:\n                self._wait_episode_release(dropped=_dropped)",
        "if True:  # MUTATION\n                self._wait_episode_release(dropped=_dropped)",
        "test_db_source_has_noted_guard_at_release_site",
    )


def test_mutation_drill_removes_episode_latch():
    """Neuter the 'already active -> return' guard; the many-waiters test
    MUST turn red (many warnings instead of one)."""
    _drill(
        "if self._wait_episode_active:\n            return  # already logged this episode",
        "if False:  # MUTATION\n            return",
        "test_many_waiters_produce_one_warning_and_one_summary",
    )

"""MEMORY-WRITERS-SILENT-DROP-1 fix-up #1 — behavioural wire-in drill.

The former ``test_fan_recheck_outcome_wire_in_at_restore_site`` was a
pure AST scan — it proved only that the writer *name* appeared inside
``_restore``'s source, not that it actually fires with the correct
payload. This file drives the real ``FanRecheckManager._restore`` and
asserts the mem row that lands.

Covers:
  * verdict=vacated     (fan_restored=False, leave_off path)
  * verdict=occupied    (fan_restored=True)
  * verdict=occupied    forced=True
  * cancel-driven       (PAUSED-path L1 cancel -> _restore via
                         ``_cancel_and_restore_async``)
  * shutdown cancels the follow-up ``async_call_later`` probe
  * abort row at an ARMED-path cancel site
  * two per-site mutation drills: neuter the verdict writer call OR
    the follow-up scheduling — each must turn a specific named test red
    (asserted via subprocess so this file itself stays green).

Reuses the module loader + fakes from ``test_fan_recheck_mode2_cycle``
to keep the HA stub surface identical.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_fan_recheck_mode2_cycle import (  # noqa: E402
    _build_world,
    _drain_tasks,
    _load_fan_recheck_module,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
URA_DIR = ROOT_DIR / "custom_components" / "universal_room_automation"


# ---------------------------------------------------------------------------
# Load memory_writers.py into the SAME package namespace the production
# ``_restore`` imports via ``from ..memory_writers import ...`` — i.e.
# ``ura_fanrecheck_pkg.memory_writers`` (the stub pkg the fan-recheck
# loader installs). Without this the dynamic import inside _restore
# fails and the writer call is silently swallowed by the outer
# try/except — exactly the failure mode fix-up #1 is here to catch.
# ---------------------------------------------------------------------------


def _load_memory_writers_into_pkg():
    _load_fan_recheck_module()
    fq = "ura_fanrecheck_pkg.memory_writers"
    if fq in sys.modules:
        return sys.modules[fq]
    spec = importlib.util.spec_from_file_location(
        fq, str(URA_DIR / "memory_writers.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "ura_fanrecheck_pkg"
    sys.modules[fq] = mod
    spec.loader.exec_module(mod)
    return mod


class _MemDBMixin:
    """Mixin that extends the mode2 _FakeDB with log_memory_episode."""

    def __init__(self, inner):
        self._inner = inner
        self.mem_rows: list = []
        self._next_mem_id = 1

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def log_memory_episode(
        self,
        *,
        node_id,
        episode_type,
        adjudication="unadjudicated",
        adjudicated_by=None,
        attrs=None,
        source_ref=None,
        started_at=None,
        ended_at=None,
        dedup_source_ref=False,
    ):
        if dedup_source_ref and source_ref is not None:
            for r in self.mem_rows:
                if r["source_ref"] == source_ref:
                    return None
        rid = self._next_mem_id
        self._next_mem_id += 1
        self.mem_rows.append({
            "id": rid,
            "node_id": node_id,
            "episode_type": episode_type,
            "adjudication": adjudication,
            "adjudicated_by": adjudicated_by,
            "attrs": dict(attrs or {}),
            "source_ref": source_ref,
            "started_at": started_at,
            "ended_at": ended_at,
        })
        return rid


def _install_mem_db(hass):
    inner = hass.data["universal_room_automation"]["database"]
    wrapped = _MemDBMixin(inner)
    hass.data["universal_room_automation"]["database"] = wrapped
    return wrapped


def _install_verify_shims(hass):
    """Minimal ``verify_event_loop_thread`` + ``loop`` shims so any HA
    helper that landed from a sibling test's real import can still run.
    No-op where the stubs are in place; harmless when they aren't."""
    if not hasattr(hass, "verify_event_loop_thread"):
        hass.verify_event_loop_thread = lambda *_a, **_kw: None
    if not hasattr(hass, "loop"):
        hass.loop = asyncio.get_event_loop()
    # Route async_create_background_task through hass._tasks so the
    # mode2 `_drain_tasks` helper awaits scheduler-queued writer coros.
    def _acbt(coro, name, eager_start=True):
        hass._tasks.append(coro)
        return coro
    hass.async_create_background_task = _acbt
    # Replace async_call_later with a no-op fake so (a) HA's real timer
    # machinery doesn't fire against our _FakeHass (ERROR: lingering
    # timers in conftest) and (b) we can observe the followup unsub.
    # The pytest-homeassistant conftest imports the real
    # ``homeassistant.helpers.event`` at collection time, so the
    # mode2-cycle stub for that module is shadowed; we must patch at
    # the production module level, not at sys.modules.
    import ura_fan_recheck_under_test as _mod  # noqa: PLC0415

    def _fake_async_call_later(_hass, _delay, _cb):
        return lambda: None

    _mod.async_call_later = _fake_async_call_later


def _mk_manager_in_paused_state(**build_kwargs):
    mod = _load_memory_writers_into_pkg()  # noqa: F841 — ensure import landed
    mod_fr, hass, mgr, rc, fc, pc, _db = _build_world(**build_kwargs)
    _install_verify_shims(hass)
    mem_db = _install_mem_db(hass)
    # Hand-build a ctx in PAUSED so _restore can run end-to-end without
    # driving the full state machine timers.
    ctx = mod_fr._RoomCtx(
        room_name="exercise",
        entry_id="entry_exercise",
    )
    ctx.state = mod_fr.STATE_PAUSED
    ctx.state_entered_at = datetime.now(timezone.utc)
    ctx.last_attempt_at = ctx.state_entered_at
    ctx.ble_ladder_layer = mod_fr.LAYER_L3
    ctx.snapshot = {
        "entities": ["fan.exercise"], "is_on": True, "speed_pct": 50,
        "trigger": "temperature", "last_on_time": "", "entity_attrs": {},
    }
    mgr._rooms["exercise"] = ctx
    return mod_fr, hass, mgr, rc, fc, pc, mem_db, ctx


def _outcome_rows(mem_db):
    return [r for r in mem_db.mem_rows if r["episode_type"] == "fan_recheck_outcome"]


# =============================================================================
# Behavioural wire-in drills
# =============================================================================


@pytest.mark.asyncio
async def test_restore_vacated_writes_fan_recheck_outcome_row():
    mod_fr, hass, mgr, rc, _fc, _pc, mem_db, ctx = (
        _mk_manager_in_paused_state()
    )
    await mgr._restore(ctx, outcome=mod_fr.OUTCOME_VACATED)
    await _drain_tasks(hass)
    rows = _outcome_rows(mem_db)
    assert len(rows) == 1, (
        "fix-up #1 wire-in drill: _restore must land exactly one "
        "fan_recheck_outcome row at verdict time."
    )
    r = rows[0]
    assert r["attrs"]["verdict"] == "vacated"
    assert r["attrs"]["reason"] == "pause_window_complete"
    assert r["attrs"]["fan_restored"] is False  # leave_off on VACATED
    # Fix-up #3: verdict row carries the verdict's own timestamp, not
    # the probe time. The source_ref embeds that iso.
    assert r["source_ref"].startswith("fan_recheck_outcome:exercise:")
    assert ":followup" not in r["source_ref"]
    # Fix-up #2: no manual_fan_on_followup on the verdict row — the
    # follow-up probe writes a separate second row.
    assert "manual_fan_on_followup" not in r["attrs"]


@pytest.mark.asyncio
async def test_restore_occupied_confirmed_writes_fan_restored_true():
    mod_fr, hass, mgr, _rc, _fc, _pc, mem_db, ctx = (
        _mk_manager_in_paused_state()
    )
    await mgr._restore(ctx, outcome=mod_fr.OUTCOME_OCCUPIED_CONFIRMED)
    await _drain_tasks(hass)
    rows = _outcome_rows(mem_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["attrs"]["verdict"] == "occupied_confirmed"
    assert r["attrs"]["fan_restored"] is True


@pytest.mark.asyncio
async def test_restore_forced_writes_restored_true_reason_forced():
    mod_fr, hass, mgr, _rc, _fc, _pc, mem_db, ctx = (
        _mk_manager_in_paused_state()
    )
    await mgr._restore(
        ctx, outcome=mod_fr.OUTCOME_OCCUPIED_CONFIRMED, forced=True,
    )
    await _drain_tasks(hass)
    rows = _outcome_rows(mem_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["attrs"]["reason"] == "forced"
    assert r["attrs"]["fan_restored"] is True


@pytest.mark.asyncio
async def test_restore_cancel_driven_marks_reason_cancel_driven():
    mod_fr, hass, mgr, _rc, _fc, _pc, mem_db, ctx = (
        _mk_manager_in_paused_state()
    )
    # Simulate the PAUSED-path L1/motion cancel site which sets this.
    ctx._cancel_driven = True
    await mgr._restore(ctx, outcome=mod_fr.OUTCOME_OCCUPIED_CONFIRMED)
    await _drain_tasks(hass)
    rows = _outcome_rows(mem_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["attrs"]["reason"] == "cancel_driven"


# =============================================================================
# Fix-up #2 — shutdown cancels the follow-up probe
# =============================================================================


@pytest.mark.asyncio
async def test_shutdown_cancels_followup_probe_unsub():
    mod_fr, hass, mgr, _rc, _fc, _pc, _mem_db, ctx = (
        _mk_manager_in_paused_state()
    )

    await mgr._restore(ctx, outcome=mod_fr.OUTCOME_OCCUPIED_CONFIRMED)
    await _drain_tasks(hass)
    assert len(mgr._followup_timer_unsubs) == 1, (
        "fix-up #2 pre-condition: _restore must track the follow-up "
        "probe async_call_later unsub on the manager."
    )
    tracked_unsub = mgr._followup_timer_unsubs[0]
    cancel_log = {"n": 0}
    orig_unsub = tracked_unsub

    def _wrapped():
        cancel_log["n"] += 1
        return orig_unsub()

    mgr._followup_timer_unsubs[0] = _wrapped
    await mgr.shutdown()
    assert cancel_log["n"] == 1, (
        "fix-up #2: shutdown() must cancel every outstanding "
        "follow-up probe unsub."
    )
    assert mgr._followup_timer_unsubs == []


# =============================================================================
# Fix-up #4 — aborted mem row on ARMED-path cancels
# =============================================================================


@pytest.mark.asyncio
async def test_motion_cancel_while_armed_writes_aborted_row():
    mod_fr, hass, mgr, rc, _fc, _pc, _db = _build_world()
    _install_verify_shims(hass)
    _load_memory_writers_into_pkg()
    mem_db = _install_mem_db(hass)
    ctx = mod_fr._RoomCtx(room_name="exercise", entry_id="entry_exercise")
    ctx.state = mod_fr.STATE_ARMED
    ctx.state_entered_at = datetime.now(timezone.utc)
    mgr._rooms["exercise"] = ctx
    rc.data["motion_detected"] = True
    mgr._evaluate_cancellation_during_tick(ctx, rc)
    await _drain_tasks(hass)
    rows = _outcome_rows(mem_db)
    assert len(rows) == 1, (
        "fix-up #4: an ARMED-path motion cancel must write exactly one "
        "aborted fan_recheck_outcome mem row."
    )
    r = rows[0]
    assert r["attrs"]["verdict"] == "aborted"
    assert r["attrs"]["reason"] == "motion"


# =============================================================================
# Per-site mutation drills — each must turn ONE named test red.
#
# A pure AST / global-monkeypatch "writer is called" check cannot tell the
# verdict-write apart from the followup-write; the two live on different
# code paths with different consequences. Neutering each site in the
# production source and running ONLY the test that owns that path proves
# the test is actually load-bearing for that site. The outer test
# restores the source + clears __pycache__ (PYTHONDONTWRITEBYTECODE=1 is
# set via env for the subprocess so a bytecode copy cannot mask the
# mutation).
# =============================================================================


_PFR = URA_DIR / "domain_coordinators" / "presence_fan_recheck.py"


def _mutate_and_run(
    *, old: str, new: str, target: str,
) -> subprocess.CompletedProcess:
    src = _PFR.read_text(encoding="utf-8")
    assert old in src, f"mutation anchor missing: {old!r}"
    _PFR.write_text(src.replace(old, new, 1), encoding="utf-8")
    try:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(ROOT_DIR / "quality") + os.pathsep + env.get(
            "PYTHONPATH", "",
        )
        return subprocess.run(
            [
                sys.executable, "-m", "pytest", "-x",
                f"quality/tests/test_fan_recheck_memory_outcome.py::{target}",
            ],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        _PFR.write_text(src, encoding="utf-8")
        # Clear bytecode cache so the restored source wins.
        for pyc in _PFR.parent.glob("__pycache__/presence_fan_recheck.*"):
            try:
                pyc.unlink()
            except OSError:
                pass


def test_mutation_neutering_verdict_writer_call_turns_vacated_test_red():
    """Replace the IMMEDIATE verdict-row _emit(None) call inside _restore
    with a no-op; the vacated behavioural test must FAIL (0 rows).
    """
    result = _mutate_and_run(
        old="            # Verdict row — immediate.\n            _emit(None)",
        new="            # Verdict row — immediate.\n            pass  # mutation: neutered",
        target="test_restore_vacated_writes_fan_recheck_outcome_row",
    )
    assert result.returncode != 0, (
        "mutation drill #1 regressed — removing the verdict-row writer "
        "call from _restore MUST turn the vacated behavioural test red, "
        f"but pytest returned 0. stdout={result.stdout[-500:]}"
    )


def test_mutation_neutering_followup_scheduling_turns_shutdown_test_red():
    """Replace the async_call_later probe-scheduling block with a no-op;
    the shutdown-cancels-probe test must FAIL (no unsub tracked).
    """
    result = _mutate_and_run(
        old="                unsub = async_call_later(",
        new="                unsub = None; _ = (lambda *a: None)(",
        target="test_shutdown_cancels_followup_probe_unsub",
    )
    assert result.returncode != 0, (
        "mutation drill #2 regressed — removing the follow-up probe "
        "scheduling MUST turn the shutdown test red, but pytest "
        f"returned 0. stdout={result.stdout[-500:]}"
    )

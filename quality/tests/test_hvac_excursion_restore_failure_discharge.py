"""HVAC-GOVERNED-EXCURSION-1 fix-up r6 - per-episode NM discharge.

Operator ruling: the borrow_restore_failed NM latch discharges on the
next successful ``return_excursion`` for the same zone. Resulting
semantics: ONE ALERT PER FAILURE EPISODE, not per calendar day.

  * consistent failure -> latch holds -> ONE alert (correct)
  * fail -> succeed -> fail -> TWO alerts (correct: alternating
    failure is MORE alarming than steady failure, not less)

Load-bearing three-way distinction on ``restore_ok``:
  * True  -> discharges
  * False -> emits
  * None  -> discharges NEITHER (policy chose not to attempt, so not
    evidence the mechanism works). Testing that None does NOT
    discharge is item 2 of the operator's required drills.

Guard-tests:
  1. test_r6_discharge_makes_fail_succeed_fail_emit_TWICE
     Neuter anchor: delete the ``elif restore_ok is True: await
     _discharge_restore_failure_latch(...)`` branch in return_excursion
     -> this test asserts 2 emits; without discharge only 1 emits.
  2. test_r6_None_does_NOT_discharge_the_latch
     restore_ok=None between two failures must NOT clear the latch.
  3. test_r6_per_day_latch_still_suppresses_repeat_fail_no_success
     Two consecutive failures with NO intervening success emit exactly
     one - the per-day backstop still works, the discharge did not
     accidentally defeat it entirely.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock

_this_dir = os.path.dirname(__file__)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import _excursion_harness  # noqa: E402
_mods = _excursion_harness.bootstrap()
_ex_mod = _mods["hvac_excursion"]

# Re-install homeassistant.util.dt (harness pop restored, needed by
# _stuck_signal_nm) - see the sibling restore_failure_surface test for
# the same guard.
import types as _types  # noqa: E402
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
if "homeassistant.util.dt" not in sys.modules:
    _dt_mock = _types.ModuleType("homeassistant.util.dt")
    _dt_mock.now = lambda: _dt.now(_tz.utc)
    _dt_mock.utcnow = lambda: _dt.now(_tz.utc)
    _dt_mock.as_local = lambda d: d
    def _pd(s):
        try:
            return _dt.fromisoformat(s) if isinstance(s, str) else None
        except (ValueError, TypeError):
            return None
    _dt_mock.parse_datetime = _pd
    sys.modules["homeassistant.util.dt"] = _dt_mock


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _drain(pending):
    if not pending:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    for coro in pending:
        try:
            loop.run_until_complete(coro)
        except Exception:
            pass
    pending.clear()


def _reset_stats():
    _ex_mod._stats_date = None
    _ex_mod._started_today.clear()
    _ex_mod._returned_today.clear()
    _ex_mod._restore_failed_today.clear()
    _ex_mod._last_return = None


def _ensure_util_dt():
    import types as _types
    from datetime import datetime as _dt, timezone as _tz
    if "homeassistant.util.dt" not in sys.modules:
        m = _types.ModuleType("homeassistant.util.dt")
        m.now = lambda: _dt.now(_tz.utc)
        m.utcnow = lambda: _dt.now(_tz.utc)
        m.as_local = lambda d: d
        def _pd(s):
            try:
                return _dt.fromisoformat(s) if isinstance(s, str) else None
            except (ValueError, TypeError):
                return None
        m.parse_datetime = _pd
        sys.modules["homeassistant.util.dt"] = m


def setup_function(_):
    _ensure_util_dt()
    _reset_stats()
    _ex_mod._test_clear_rows()
    _ex_mod._test_set_kill_switch(True)


def _install_capture(monkeypatch):
    """Return (fake_hass, emit_calls, recovered_calls, pending)."""
    emit_calls = []
    recovered_calls = []
    pending = []
    # Model the per-day latch inside the fake so this test exercises
    # the real semantic (latch + discharge), not the monkeypatched
    # emit's raw dispatch. Real fire_stuck_signal uses
    # _LATCHES[(kind, key)]; we mirror that here so a repeat emit for
    # the same (kind, key) is suppressed until a recovered call
    # discharges it.
    _fake_latches: set = set()

    async def _emit(hass, kind, key, diagnosis, remedy="", **kw):
        latch_key = (kind, tuple(key))
        if latch_key in _fake_latches:
            return False   # latch-suppressed, same as real helper
        _fake_latches.add(latch_key)
        emit_calls.append({
            "kind": kind, "key": key, "diagnosis": diagnosis, **kw,
        })
        return True

    async def _recovered(hass, kind, key, message, **kw):
        latch_key = (kind, tuple(key))
        _fake_latches.discard(latch_key)   # discharge - matches real helper
        recovered_calls.append({
            "kind": kind, "key": key, "message": message,
        })
        return True

    fake_hass = MagicMock()
    fake_hass.data = {"universal_room_automation": {}}

    def _sched(coro):
        pending.append(coro)
        return MagicMock()
    fake_hass.async_create_task = _sched

    _ex_mod._test_bind(hass=fake_hass, db=None)

    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    _stuck_signal_nm.reset_latches_for_tests()
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _emit)
    monkeypatch.setattr(
        _stuck_signal_nm, "fire_stuck_signal_recovered", _recovered,
    )
    return fake_hass, emit_calls, recovered_calls, pending


def _fail_borrow(zone_id: str = "zone_a"):
    """Open + fail-close a borrow. Returns nothing."""
    _ex_mod._test_clear_rows()
    tok = _ex_mod._test_seed_row(zone_id, pre_preset="home")
    _run(_ex_mod.return_excursion(
        tok, trigger="timer", restore_ok=False,
        trigger_detail="test_wire_diverged",
    ))


def _succeed_borrow(zone_id: str = "zone_a"):
    _ex_mod._test_clear_rows()
    tok = _ex_mod._test_seed_row(zone_id, pre_preset="home")
    _run(_ex_mod.return_excursion(tok, trigger="timer", restore_ok=True))


def _policy_skip_borrow(zone_id: str = "zone_a"):
    """restore_ok=None (policy chose not to attempt) - must NOT discharge."""
    _ex_mod._test_clear_rows()
    tok = _ex_mod._test_seed_row(zone_id, pre_preset="home")
    _run(_ex_mod.return_excursion(
        tok, trigger="immunity_skip", restore_ok=None,
        trigger_detail="revert_skipped_immunity",
    ))


# ---------------------------------------------------------------------------
# 1. Discharge makes fail -> succeed -> fail emit TWICE (per-episode)
# ---------------------------------------------------------------------------


def test_r6_discharge_makes_fail_succeed_fail_emit_TWICE(monkeypatch):
    """Per-episode semantics: two distinct failure episodes, two emits."""
    _, emit_calls, recovered_calls, pending = _install_capture(monkeypatch)
    _fail_borrow()
    _drain(pending)
    _succeed_borrow()  # MUST fire fire_stuck_signal_recovered
    _drain(pending)
    _fail_borrow()
    _drain(pending)
    assert len(emit_calls) == 2, (
        f"Expected 2 alerts for fail -> succeed -> fail (per-episode "
        f"semantics). Got {len(emit_calls)}: {emit_calls}. Without the "
        "discharge, the per-day latch collapses this to 1 alert."
    )
    assert len(recovered_calls) >= 1, (
        f"Expected fire_stuck_signal_recovered on the intervening "
        f"success; got {recovered_calls}. Neuter anchor for this test: "
        "delete the `elif restore_ok is True: await "
        "_discharge_restore_failure_latch(...)` branch in "
        "return_excursion."
    )
    assert all(c["kind"] == "borrow_restore_failed" for c in emit_calls)
    assert all(c["key"] == ("zone_a",) for c in emit_calls)
    assert recovered_calls[0]["kind"] == "borrow_restore_failed"
    assert recovered_calls[0]["key"] == ("zone_a",)


# ---------------------------------------------------------------------------
# 2. restore_ok=None MUST NOT discharge
# ---------------------------------------------------------------------------


def test_r6_None_does_NOT_discharge_the_latch(monkeypatch):
    """Policy-skip (restore_ok=None) is not evidence the mechanism works.
    Treating it as recovery would silently re-arm the alert on a zone
    that has not actually succeeded at anything.

    Sequence: fail (emit 1) -> None-return -> fail (per-day latch still
    armed -> suppressed) -> total 1 emit + 0 recovered.
    """
    _, emit_calls, recovered_calls, pending = _install_capture(monkeypatch)
    _fail_borrow()
    _drain(pending)
    _policy_skip_borrow()   # restore_ok=None
    _drain(pending)
    _fail_borrow()          # would emit if None had discharged the latch
    _drain(pending)
    assert len(emit_calls) == 1, (
        f"restore_ok=None discharged the latch (BUG). Should have "
        f"suppressed the second failure. Got emit_calls={emit_calls}. "
        "Neuter anchor: replace `elif restore_ok is True:` guard "
        "with `elif restore_ok is not False:` -> this test fails."
    )
    assert not recovered_calls, (
        f"restore_ok=None fired fire_stuck_signal_recovered (BUG). "
        f"None is not proof the mechanism works. Got {recovered_calls}."
    )


# ---------------------------------------------------------------------------
# 3. Per-day latch still suppresses fail -> fail with no intervening success
# ---------------------------------------------------------------------------


def test_r6_per_day_latch_still_suppresses_repeat_fail_no_success(monkeypatch):
    """Backstop invariant: without an intervening success, two failures
    still collapse to one alert. Guards against a discharge that
    accidentally defeats the per-day latch entirely.
    """
    _, emit_calls, recovered_calls, pending = _install_capture(monkeypatch)
    _fail_borrow()
    _drain(pending)
    _fail_borrow()
    _drain(pending)
    assert len(emit_calls) == 1, (
        f"Per-day latch failed to suppress a repeat failure with NO "
        f"intervening success. Discharge is defeating the latch. "
        f"Got emit_calls={emit_calls}."
    )
    assert not recovered_calls

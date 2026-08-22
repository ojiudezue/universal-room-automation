"""HVAC-GOVERNED-EXCURSION-1 fix-up r5 addendum - restore-failure surface.

Anchors for section B (log line) and section C (NM emit) of the r5
addendum. Both surfaces fire ONLY on ``restore_ok is False`` (attempted-
and-diverged); neither fires on ``None`` (policy skip) or ``True``.

Neuter drills documented in the drill table at the top of the file.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from unittest.mock import MagicMock, AsyncMock

_this_dir = os.path.dirname(__file__)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import _excursion_harness  # noqa: E402
_mods = _excursion_harness.bootstrap()
_ex_mod = _mods["hvac_excursion"]

# Re-install homeassistant.util.dt after harness pop - _stuck_signal_nm
# needs it at import time when we monkeypatch its fire_stuck_signal in
# the C/D tests below. Harness pops it to avoid tripping
# test_hvac_excursion_d1_observability's _HA_REAL gate; we don't need
# that pop for this file.
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
    """Await coros collected via fake_hass.async_create_task."""
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
    """Clear the module-global diagnostic counters + _last_return so
    each test observes a clean slate. Counters are process-wide globals
    (per-day design); tests need explicit reset."""
    _ex_mod._stats_date = None
    _ex_mod._started_today.clear()
    _ex_mod._returned_today.clear()
    _ex_mod._restore_failed_today.clear()
    _ex_mod._last_return = None


def setup_function(_):
    _reset_stats()


def _fresh_token():
    """Populate a synthetic token in _rows and return it."""
    _ex_mod._test_clear_rows()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)
    tok = _ex_mod._test_seed_row("zone_a", pre_preset="home")
    return tok


# ---------------------------------------------------------------------------
# Section B - log line fires on restore_ok=False
# ---------------------------------------------------------------------------


def test_B_log_error_fires_on_restore_ok_False(caplog):
    """MANDATORY per operator: 'We need a log line on failure not just
    nm.' The log is the record of last resort - fires INDEPENDENT of NM.

    Neuter anchor: strip the _LOGGER.error call in
    _surface_restore_failure - this test fails."""
    tok = _fresh_token()
    caplog.set_level(logging.ERROR)
    _run(_ex_mod.return_excursion(
        tok, trigger="timer",
        restore_ok=False,
        trigger_detail="test_wire_diverged",
        preset_after="manual",
        target_low_after=68.0,
        target_high_after=76.0,
    ))
    text = caplog.text
    assert "[GOVERNED BORROW RESTORE FAILED]" in text, (
        f"Section B: greppable log tag missing. caplog={text!r}"
    )
    assert "zone=zone_a" in text
    assert "test_wire_diverged" in text


def test_B_log_line_records_snapshot_and_observed():
    """The log line MUST carry both the snapshot URA tried to restore
    AND what the wire actually showed - not just one side."""
    import io
    tok = _fresh_token()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.ERROR)
    logging.getLogger(_ex_mod.__name__).addHandler(handler)
    try:
        _run(_ex_mod.return_excursion(
            tok, trigger="timer", restore_ok=False,
            preset_after="manual",
            target_low_after=99.0, target_high_after=101.0,
        ))
        text = buf.getvalue()
        # Snapshot side (from the token)
        assert "pre_preset='home'" in text
        # Observed side (what the wire actually read after restore)
        assert "preset='manual'" in text
        assert "target_low=99.0" in text
        assert "target_high=101.0" in text
    finally:
        logging.getLogger(_ex_mod.__name__).removeHandler(handler)


# ---------------------------------------------------------------------------
# Section C - NM emit fires via the standard fire_stuck_signal helper
# ---------------------------------------------------------------------------


def test_C_nm_fire_stuck_signal_called_on_restore_ok_False(monkeypatch):
    """NM emit MUST route through fire_stuck_signal (the standard
    governed emit path) so every governance layer applies. Neuter
    anchor: strip the fire_stuck_signal dispatch in
    _surface_restore_failure - this test fails."""
    tok = _fresh_token()
    calls = []
    async def _capture(hass, kind, key, diagnosis, remedy="", **kw):
        calls.append({
            "kind": kind, "key": key, "diagnosis": diagnosis,
            "remedy": remedy, **kw,
        })
        return True
    # Install a synthetic hass ref so the NM branch runs.
    fake_hass = MagicMock()
    fake_hass.data = {"universal_room_automation": {}}
    _pending_tasks = []
    def _sched(coro):
        _pending_tasks.append(coro)
        # Return a MagicMock so callers that store the handle succeed.
        return MagicMock()
    fake_hass.async_create_task = _sched
    _ex_mod._test_bind(hass=fake_hass, db=None)
    # Patch fire_stuck_signal at the import point.
    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _capture)
    _run(_ex_mod.return_excursion(
        tok, trigger="timer", restore_ok=False,
        trigger_detail="test",
        preset_after="manual",
    ))
    _drain(_pending_tasks)
    assert calls, (
        "Section C: fire_stuck_signal was not called on restore_ok=False. "
        "The governed NM path is the ONLY path the operator can "
        "configure recipients / quiet hours / thresholds on; a bypass "
        "silently loses the governance layers."
    )
    assert calls[0]["kind"] == "borrow_restore_failed", (
        f"kind identifier changed: {calls[0]['kind']!r}. If this is "
        "intentional, coordinate with NM subscription config."
    )
    assert calls[0]["key"] == ("zone_a",), (
        f"key shape changed: {calls[0]['key']!r}. Dedup latch keys must "
        "include zone_id at minimum."
    )
    # title_override lets user see "Governed borrow restore failed" not
    # "Stuck signal: borrow_restore_failed".
    assert "title_override" in calls[0]
    assert "Governed borrow restore failed" in calls[0]["title_override"]


def test_C_nm_observation_mode_suppresses_emit(monkeypatch):
    """Bug Class #23 - observation mode gates dispatch. Log still fires
    (proven by section B tests); NM does not."""
    tok = _fresh_token()
    calls = []
    async def _capture(*a, **kw):
        calls.append(1)
        return True
    fake_hass = MagicMock()
    # Set up hass.data with an HVAC coord whose _observation_mode = True.
    fake_hvac = MagicMock()
    fake_hvac._observation_mode = True
    fake_cm = MagicMock()
    fake_cm.coordinators = {"hvac": fake_hvac}
    fake_hass.data = {"universal_room_automation": {"coordinator_manager": fake_cm}}
    _pending_tasks = []
    def _sched(coro):
        _pending_tasks.append(coro)
        # Return a MagicMock so callers that store the handle succeed.
        return MagicMock()
    fake_hass.async_create_task = _sched
    _ex_mod._test_bind(hass=fake_hass, db=None)
    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _capture)
    _run(_ex_mod.return_excursion(
        tok, trigger="timer", restore_ok=False,
    ))
    _drain(_pending_tasks)
    assert not calls, (
        "Observation mode did NOT suppress the NM emit. Bug Class #23."
    )


# ---------------------------------------------------------------------------
# Section D - restore_ok=None (policy skip) MUST fire NEITHER
# ---------------------------------------------------------------------------


def test_D_restore_ok_None_fires_neither_log_nor_nm(caplog, monkeypatch):
    """Operator ruling: 'Do NOT log on restore_ok is None - after round
    2 that means policy deliberately did not restore (immunity /
    comfort_delay). Logging those as failures would train the reader
    to ignore the line.'"""
    tok = _fresh_token()
    caplog.set_level(logging.DEBUG)
    calls = []
    async def _capture(*a, **kw):
        calls.append(1)
        return True
    fake_hass = MagicMock()
    fake_hass.data = {"universal_room_automation": {}}
    _pending_tasks = []
    def _sched(coro):
        _pending_tasks.append(coro)
        # Return a MagicMock so callers that store the handle succeed.
        return MagicMock()
    fake_hass.async_create_task = _sched
    _ex_mod._test_bind(hass=fake_hass, db=None)
    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _capture)
    _run(_ex_mod.return_excursion(
        tok, trigger="immunity_skip",
        restore_ok=None,
        trigger_detail="revert_skipped_immunity",
    ))
    _drain(_pending_tasks)
    assert "[GOVERNED BORROW RESTORE FAILED]" not in caplog.text, (
        "restore_ok=None (policy skip) MUST NOT emit the failure log."
    )
    assert not calls, (
        "restore_ok=None (policy skip) MUST NOT emit the failure NM."
    )


def test_D_restore_ok_True_fires_neither_log_nor_nm(caplog, monkeypatch):
    """Success also does not emit."""
    tok = _fresh_token()
    caplog.set_level(logging.DEBUG)
    calls = []
    async def _capture(*a, **kw):
        calls.append(1)
        return True
    fake_hass = MagicMock()
    fake_hass.data = {"universal_room_automation": {}}
    _pending_tasks = []
    def _sched(coro):
        _pending_tasks.append(coro)
        # Return a MagicMock so callers that store the handle succeed.
        return MagicMock()
    fake_hass.async_create_task = _sched
    _ex_mod._test_bind(hass=fake_hass, db=None)
    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _capture)
    _run(_ex_mod.return_excursion(
        tok, trigger="timer", restore_ok=True,
    ))
    _drain(_pending_tasks)
    assert "[GOVERNED BORROW RESTORE FAILED]" not in caplog.text
    assert not calls


# ---------------------------------------------------------------------------
# Section A - the diagnostic counters increment on begin/return
# ---------------------------------------------------------------------------


def test_A_counters_track_started_returned_restore_failed():
    _ex_mod._test_clear_rows()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    # Start a NUDGE.
    tok1 = _run(_ex_mod.begin_excursion(
        hass, zone_id="z1", entity_id="climate.z1",
        kind=_ex_mod.EXCURSION_KIND.NUDGE, duration_s=60,
        site="test",
    ))
    stats = _ex_mod.get_borrow_stats()
    assert stats["started_today"].get("nudge") == 1
    assert stats["returned_today"].get("nudge", 0) == 0
    # Return cleanly.
    _run(_ex_mod.return_excursion(tok1, trigger="timer", restore_ok=True))
    stats = _ex_mod.get_borrow_stats()
    assert stats["returned_today"].get("nudge") == 1
    assert stats["restore_failed_today"].get("nudge", 0) == 0
    # A second NUDGE that fails restore.
    tok2 = _run(_ex_mod.begin_excursion(
        hass, zone_id="z1", entity_id="climate.z1",
        kind=_ex_mod.EXCURSION_KIND.NUDGE, duration_s=60,
        site="test",
    ))
    _run(_ex_mod.return_excursion(tok2, trigger="timer", restore_ok=False))
    stats = _ex_mod.get_borrow_stats()
    assert stats["started_today"].get("nudge") == 2
    assert stats["returned_today"].get("nudge") == 2
    assert stats["restore_failed_today"].get("nudge") == 1


def test_A_last_return_snapshot_populated():
    _ex_mod._test_clear_rows()
    _ex_mod._test_bind(hass=None, db=None)
    hass = MagicMock()
    hass.states = MagicMock(); hass.states.get = MagicMock(return_value=None)
    tok = _run(_ex_mod.begin_excursion(
        hass, zone_id="z1", entity_id="climate.z1",
        kind=_ex_mod.EXCURSION_KIND.COMPROMISE, duration_s=60, site="test",
    ))
    _run(_ex_mod.return_excursion(
        tok, trigger="timer", restore_ok=True,
        trigger_detail=None,
    ))
    stats = _ex_mod.get_borrow_stats()
    lr = stats["last_return"]
    assert lr is not None
    assert lr["zone_id"] == "z1"
    assert lr["kind"] == "compromise"
    assert lr["restore_ok"] is True
    assert lr["trigger"] == "timer"
    assert "ended_iso" in lr

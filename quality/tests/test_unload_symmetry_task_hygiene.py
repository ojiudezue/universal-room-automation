"""UNLOAD-SYMMETRY-TASK-HYGIENE-1 wire-in behavioral tests.

The 5 sites this cycle covers each retain an ``async_call_later`` unsub
on a per-owner list drained at teardown. THREE of the five are per-event
hot paths (per-detection / per-governed-command), so the fix-up round
(2026-09-16) added the SELF-REMOVING idiom (mirrors
``hvac.py:1351 _unsub_kick``) so those lists stay bounded across process
lifetime. Behavioral tests below cover:

  * append-on-schedule           (per-owner retention plumbing works)
  * cancel-on-teardown           (unsub is invoked)
  * self-removal-on-fire         (list shrinks when the timer actually fires)
  * double-teardown idempotency  (second teardown is a clean no-op)
  * ConfigEntryState-LOADED gate (init retry: register vs inline-cancel)

Neuter drill (per site, per test): remove the corresponding production
line → the named test goes red. Verified below in the commit message.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _Ev:
    def __init__(self, new_state, old_state=None):
        self.data = {"new_state": new_state, "old_state": old_state}


class _State:
    def __init__(self, entity_id, state):
        self.entity_id = entity_id
        self.state = state


def _capture_delayed_callable(spy_mock):
    """Return the callable passed as the 3rd positional arg to
    ``async_call_later(hass, delay, cb)`` on the most recent call."""
    assert spy_mock.called, "async_call_later was not scheduled"
    args, kwargs = spy_mock.call_args
    # signature: async_call_later(hass, delay, action)
    return args[2] if len(args) >= 3 else kwargs.get("action")


# ---------------------------------------------------------------------------
# Site 1: transit_validator._on_egress_state_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_egress_state_change_retains_and_cancels_on_teardown():
    from custom_components.universal_room_automation import transit_validator as tv

    tracker = tv.EgressDirectionTracker(hass=MagicMock())
    fake_unsub = MagicMock(name="unsub_state")
    with patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ):
        tracker._on_egress_state_change(_Ev(_State("binary_sensor.foo", "on")))

    assert fake_unsub in tracker._unsub, (
        "UNLOAD-SYMMETRY: unsub not appended to self._unsub — pending "
        "callback cannot be cancelled on teardown."
    )
    await tracker.async_teardown()
    fake_unsub.assert_called_once()


@pytest.mark.asyncio
async def test_egress_state_change_self_removes_on_fire():
    """Per-detection hot path: after the timer fires, its unsub MUST
    drop out of ``self._unsub`` so the list stays bounded.

    Neuter drill: delete ``self._unsub.remove(_captured_unsub)`` in
    ``_delayed_resolve`` → this test fails (list retains fake_unsub).
    """
    from custom_components.universal_room_automation import transit_validator as tv

    tracker = tv.EgressDirectionTracker(hass=MagicMock())
    tracker._resolve_direction = MagicMock(  # avoid real DB work
        return_value=asyncio.sleep(0),
    )
    fake_unsub = MagicMock(name="unsub_state")
    with patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ) as spy:
        tracker._on_egress_state_change(_Ev(_State("binary_sensor.foo", "on")))

    delayed = _capture_delayed_callable(spy)
    assert fake_unsub in tracker._unsub  # armed

    await delayed(None)  # simulate the timer firing

    assert fake_unsub not in tracker._unsub, (
        "UNLOAD-SYMMETRY fix-up: _delayed_resolve did NOT remove its own "
        "unsub from self._unsub on fire — per-detection retention list "
        "grows unbounded for process lifetime."
    )


# ---------------------------------------------------------------------------
# Site 2: transit_validator._on_egress_count_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_egress_count_change_retains_and_cancels_on_teardown():
    from custom_components.universal_room_automation import transit_validator as tv

    tracker = tv.EgressDirectionTracker(hass=MagicMock())
    fake_unsub = MagicMock(name="unsub_count")
    with patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ):
        tracker._on_egress_count_change(
            _Ev(
                _State("sensor.cam_person_count", "1"),
                _State("sensor.cam_person_count", "0"),
            )
        )
    assert fake_unsub in tracker._unsub
    await tracker.async_teardown()
    fake_unsub.assert_called_once()


@pytest.mark.asyncio
async def test_egress_count_change_self_removes_on_fire():
    from custom_components.universal_room_automation import transit_validator as tv

    tracker = tv.EgressDirectionTracker(hass=MagicMock())
    tracker._resolve_direction = MagicMock(return_value=asyncio.sleep(0))
    fake_unsub = MagicMock(name="unsub_count")
    with patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ) as spy:
        tracker._on_egress_count_change(
            _Ev(
                _State("sensor.cam_person_count", "1"),
                _State("sensor.cam_person_count", "0"),
            )
        )

    delayed = _capture_delayed_callable(spy)
    assert fake_unsub in tracker._unsub
    await delayed(None)
    assert fake_unsub not in tracker._unsub


@pytest.mark.asyncio
async def test_transit_validator_double_teardown_is_noop():
    """Idempotency: two back-to-back teardowns must not raise and must
    leave the retention list clean.
    """
    from custom_components.universal_room_automation import transit_validator as tv

    tracker = tv.EgressDirectionTracker(hass=MagicMock())
    fake_unsub = MagicMock(name="unsub_dup")
    with patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ):
        tracker._on_egress_state_change(_Ev(_State("binary_sensor.foo", "on")))

    await tracker.async_teardown()
    fake_unsub.assert_called_once()
    # Second teardown: no additional invocation, no raise, list stays empty.
    await tracker.async_teardown()
    assert fake_unsub.call_count == 1
    assert tracker._unsub == []


# ---------------------------------------------------------------------------
# Site 3: coordinator_diagnostics.ComplianceTracker.schedule_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compliance_schedule_check_retains_and_cancels_on_teardown():
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cd,
    )

    tracker = cd.ComplianceTracker(hass=MagicMock())
    fake_unsub = MagicMock(name="unsub_compliance")
    with patch.object(cd, "async_call_later", return_value=fake_unsub):
        await tracker.schedule_check(
            decision_id=1, scope="test", device_type="light",
            device_id="light.foo", commanded_state={"state": "on"},
        )

    assert fake_unsub in tracker._pending_check_unsubs
    tracker.async_teardown()
    fake_unsub.assert_called_once()
    assert tracker._pending_check_unsubs == []


@pytest.mark.asyncio
async def test_compliance_schedule_check_self_removes_on_fire():
    """Per-governed-command hot path: the shared ComplianceTracker lives
    for process lifetime; the retention list must drop entries on fire.

    Neuter drill: delete ``self._pending_check_unsubs.remove(...)`` in
    ``_delayed_check`` → this test fails.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cd,
    )

    tracker = cd.ComplianceTracker(hass=MagicMock())
    # Bypass the real _check_compliance body (which hits hass.states + DB).
    async def _fake_check(*a, **kw):
        return None
    tracker._check_compliance = _fake_check  # type: ignore[assignment]

    fake_unsub = MagicMock(name="unsub_c1")
    with patch.object(cd, "async_call_later", return_value=fake_unsub) as spy:
        await tracker.schedule_check(
            decision_id=1, scope="test", device_type="light",
            device_id="light.foo", commanded_state={"state": "on"},
        )
    delayed = _capture_delayed_callable(spy)
    assert fake_unsub in tracker._pending_check_unsubs
    await delayed(None)
    assert fake_unsub not in tracker._pending_check_unsubs, (
        "UNLOAD-SYMMETRY fix-up: _delayed_check did NOT remove its own "
        "unsub from _pending_check_unsubs on fire — the shared CM "
        "ComplianceTracker's list would grow monotonically per "
        "governed command."
    )


@pytest.mark.asyncio
async def test_compliance_double_teardown_is_noop():
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cd,
    )

    tracker = cd.ComplianceTracker(hass=MagicMock())
    fake_unsub = MagicMock(name="unsub_c2")
    with patch.object(cd, "async_call_later", return_value=fake_unsub):
        await tracker.schedule_check(
            decision_id=1, scope="test", device_type="light",
            device_id="light.foo", commanded_state={"state": "on"},
        )
    tracker.async_teardown()
    tracker.async_teardown()  # second call must not raise
    assert fake_unsub.call_count == 1
    assert tracker._pending_check_unsubs == []


# ---------------------------------------------------------------------------
# Site 4: hvac.py egress-gate 60s release (LABELED SHAPE GUARD)
# ---------------------------------------------------------------------------


def test_hvac_egress_gate_release_source_shape_guard():
    """SHAPE GUARD — not a behavioral wire-in.

    Instantiating the full ``HVACCoordinator`` (deep coord DAG + DB +
    config-entry graph) is out of scope for this hygiene cycle, so this
    test asserts the AST shape of the ``async_setup`` schedule site:
    the 60s ``async_call_later(self.hass, 60, _release_egress_gate)``
    call MUST be an argument of ``self._unsub_listeners.append(...)``.
    A neuter drill that strips the wrapper leaves the source in the
    "discarded" shape and this guard goes red — but it does NOT prove
    the unsub is invoked at runtime; the ``async_teardown`` path is
    proven by the coordinator's existing ``_cancel_listeners`` test.
    """
    import ast
    import pathlib

    src = pathlib.Path(
        "custom_components/universal_room_automation/domain_coordinators/hvac.py"
    ).read_text()
    tree = ast.parse(src)

    found_wrapped = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (
            isinstance(f, ast.Attribute) and f.attr == "append"
            and isinstance(f.value, ast.Attribute)
            and f.value.attr == "_unsub_listeners"
        ):
            continue
        if not node.args:
            continue
        inner = node.args[0]
        if not isinstance(inner, ast.Call):
            continue
        inner_name = ""
        if isinstance(inner.func, ast.Name):
            inner_name = inner.func.id
        elif isinstance(inner.func, ast.Attribute):
            inner_name = inner.func.attr
        if inner_name != "async_call_later":
            continue
        if (
            len(inner.args) >= 3 and isinstance(inner.args[2], ast.Name)
            and inner.args[2].id == "_release_egress_gate"
        ):
            found_wrapped = True
            break

    assert found_wrapped, (
        "UNLOAD-SYMMETRY (shape guard): hvac.py egress-gate 60s "
        "async_call_later is not wrapped in self._unsub_listeners.append(...)."
    )


# ---------------------------------------------------------------------------
# Site 5: __init__.py _check_and_notify_room_name_desync retry — BEHAVIORAL
# ---------------------------------------------------------------------------


class _FakeConfigEntry:
    """Mock ConfigEntry sufficient to drive
    ``_check_and_notify_room_name_desync`` end-to-end.

    ``async_create_background_task`` awaits the coroutine INLINE so the
    test can observe the on_unload / inline-cancel branch synchronously.
    """

    def __init__(self, *, data=None, options=None, state):
        self.entry_id = "e1"
        self.title = "Room A"
        self.data = data or {}
        self.options = options or {}
        self.state = state
        self.on_unload_calls: list = []
        self._task_coros: list = []

    def async_create_background_task(self, hass, coro, name=None):
        # Run inline for deterministic test observation.
        self._task_coros.append(coro)
        return asyncio.get_event_loop().create_task(coro)

    def async_on_unload(self, cb):
        self.on_unload_calls.append(cb)
        return cb


def _make_entry(state):
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM,
    )
    return _FakeConfigEntry(
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            # Desynced field so a NM emit is pending.
            "room_name": "Room A",
        },
        options={"room_name": "Room A Renamed"},
        state=state,
    )


@pytest.mark.asyncio
async def test_room_name_desync_retry_registers_on_unload_when_loaded():
    """Behavioral wire-in for __init__.py:_emit_with_retry.

    Setup: first NM emit raises → retry is scheduled → entry.state is
    LOADED → the retry unsub MUST be registered via
    ``entry.async_on_unload`` (NOT cancelled inline).

    Neuter drill: remove the LOADED branch's
    ``entry.async_on_unload(_retry_unsub)`` line → this test fails.
    """
    import importlib
    from homeassistant.config_entries import ConfigEntryState
    ura_init = importlib.import_module(
        "custom_components.universal_room_automation"
    )

    hass = MagicMock()
    entry = _make_entry(state=ConfigEntryState.LOADED)
    fake_unsub = MagicMock(name="retry_unsub")

    async def _boom(*a, **kw):
        raise RuntimeError("NM not ready")

    with patch(
        "custom_components.universal_room_automation."
        "domain_coordinators._stuck_signal_nm.fire_stuck_signal",
        side_effect=_boom,
    ), patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ) as spy_later:
        await ura_init._check_and_notify_room_name_desync(hass, entry)
        # Await the background task so _emit_with_retry runs to completion.
        for coro_task in list(asyncio.all_tasks()):
            if coro_task is asyncio.current_task():
                continue
            try:
                await asyncio.wait_for(coro_task, timeout=1.0)
            except Exception:
                pass

    assert spy_later.called, "expected async_call_later retry to be scheduled"
    assert fake_unsub in entry.on_unload_calls, (
        "UNLOAD-SYMMETRY: LOADED-state entry did NOT register the retry "
        "unsub via entry.async_on_unload."
    )
    fake_unsub.assert_not_called()  # not cancelled inline while LOADED


@pytest.mark.asyncio
async def test_room_name_desync_retry_cancels_inline_when_not_loaded():
    """Setup: entry is NOT_LOADED (unload already ran) → the retry unsub
    MUST be cancelled INLINE (never handed to ``async_on_unload``, which
    would leak into a drained list).

    Neuter drill: delete the ``else`` branch (inline cancel) → the fake
    unsub is never invoked and this test fails.
    """
    import importlib
    from homeassistant.config_entries import ConfigEntryState
    ura_init = importlib.import_module(
        "custom_components.universal_room_automation"
    )

    hass = MagicMock()
    entry = _make_entry(state=ConfigEntryState.NOT_LOADED)
    fake_unsub = MagicMock(name="retry_unsub_nl")

    async def _boom(*a, **kw):
        raise RuntimeError("NM not ready")

    with patch(
        "custom_components.universal_room_automation."
        "domain_coordinators._stuck_signal_nm.fire_stuck_signal",
        side_effect=_boom,
    ), patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ):
        await ura_init._check_and_notify_room_name_desync(hass, entry)
        for coro_task in list(asyncio.all_tasks()):
            if coro_task is asyncio.current_task():
                continue
            try:
                await asyncio.wait_for(coro_task, timeout=1.0)
            except Exception:
                pass

    assert fake_unsub not in entry.on_unload_calls, (
        "UNLOAD-SYMMETRY: NOT_LOADED entry registered the retry unsub via "
        "entry.async_on_unload — the drained list won't be drained again "
        "this unload → leaked timer."
    )
    fake_unsub.assert_called_once_with()  # inline cancel path


# ---------------------------------------------------------------------------
# Audit-tool contract: the discarded-unsub set must stay empty.
# ---------------------------------------------------------------------------


def test_audit_listener_cleanup_reports_zero_discarded():
    import pathlib
    import subprocess
    import sys

    repo = pathlib.Path(__file__).resolve().parents[2]
    tool = repo / "quality" / "tools" / "audit_listener_cleanup.py"
    out = subprocess.run(
        [sys.executable, str(tool)],
        capture_output=True, text=True, cwd=str(repo),
    )
    combined = out.stdout + out.stderr
    assert "DISCARDED (return value dropped): 0" in combined, (
        "UNLOAD-SYMMETRY: audit_listener_cleanup.py reports discarded "
        "subscriptions again. Output:\n" + combined
    )

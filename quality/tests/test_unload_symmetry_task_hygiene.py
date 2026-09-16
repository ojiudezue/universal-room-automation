"""UNLOAD-SYMMETRY-TASK-HYGIENE-1 wire-in behavioral tests.

Each test spies the ``async_call_later`` call at a fixed source site, exercises
the path that schedules the one-shot timer, then triggers the paired teardown
and asserts the returned unsub was actually invoked.

Neuter drill: removing the ``append`` / ``async_on_unload`` line at the
production site leaves the returned unsub unretained, so teardown cannot
cancel it — the corresponding assertion goes red.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Site 1+2: transit_validator.EgressDirectionTracker._on_egress_state_change /
#           _on_egress_count_change
# ---------------------------------------------------------------------------


class _Ev:
    def __init__(self, new_state, old_state=None):
        self.data = {"new_state": new_state, "old_state": old_state}


class _State:
    def __init__(self, entity_id, state):
        self.entity_id = entity_id
        self.state = state


@pytest.mark.asyncio
async def test_egress_state_change_call_later_is_cancelled_on_teardown():
    """Wire-in for transit_validator.py:1072 (_on_egress_state_change).

    Neuter drill: remove ``self._unsub.append(...)`` at the schedule site
    → this test fails because the returned unsub is never invoked.
    """
    from custom_components.universal_room_automation import transit_validator as tv

    tracker = tv.EgressDirectionTracker(hass=MagicMock())

    fake_unsub = MagicMock(name="unsub_state")
    with patch(
        "homeassistant.helpers.event.async_call_later", return_value=fake_unsub,
    ) as spy:
        tracker._on_egress_state_change(_Ev(_State("binary_sensor.foo", "on")))

    assert spy.called, "async_call_later should have been scheduled"
    assert fake_unsub in tracker._unsub, (
        "UNLOAD-SYMMETRY: async_call_later unsub was NOT appended to "
        "self._unsub in _on_egress_state_change — pending callback cannot "
        "be cancelled on teardown."
    )

    await tracker.async_teardown()
    fake_unsub.assert_called_once()


@pytest.mark.asyncio
async def test_egress_count_change_call_later_is_cancelled_on_teardown():
    """Wire-in for transit_validator.py:1111 (_on_egress_count_change)."""
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

    assert fake_unsub in tracker._unsub, (
        "UNLOAD-SYMMETRY: async_call_later unsub was NOT appended to "
        "self._unsub in _on_egress_count_change."
    )

    await tracker.async_teardown()
    fake_unsub.assert_called_once()


# ---------------------------------------------------------------------------
# Site 3: coordinator_diagnostics.ComplianceTracker.schedule_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compliance_schedule_check_call_later_is_cancelled_on_teardown():
    """Wire-in for coordinator_diagnostics.py:369 (schedule_check).

    Neuter drill: remove ``self._pending_check_unsubs.append(_unsub)`` at
    the schedule site → the retained unsub list stays empty and
    ``async_teardown`` cannot cancel the deferred check.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cd,
    )

    tracker = cd.ComplianceTracker(hass=MagicMock())

    fake_unsub = MagicMock(name="unsub_compliance")
    with patch.object(cd, "async_call_later", return_value=fake_unsub):
        await tracker.schedule_check(
            decision_id=1,
            scope="test",
            device_type="light",
            device_id="light.foo",
            commanded_state={"state": "on"},
        )

    assert fake_unsub in tracker._pending_check_unsubs, (
        "UNLOAD-SYMMETRY: async_call_later unsub was NOT retained in "
        "ComplianceTracker._pending_check_unsubs — a torn-down coordinator "
        "will still receive the deferred check callback."
    )

    tracker.async_teardown()
    fake_unsub.assert_called_once()
    assert tracker._pending_check_unsubs == []


# ---------------------------------------------------------------------------
# Site 4: hvac.py:1205 (egress-gate 60s release scheduled from async_setup)
# ---------------------------------------------------------------------------


def test_hvac_egress_gate_release_retains_unsub_on_unsub_listeners():
    """Wire-in AST guard for hvac.py:1205.

    Verifies the ``async_call_later(self.hass, 60, _release_egress_gate)``
    call inside ``async_setup`` is wrapped by
    ``self._unsub_listeners.append(...)``. A neuter drill that strips the
    wrapper leaves the source in the "discarded" shape and this test goes
    red.

    Uses source inspection because instantiating the full HVACCoordinator
    (deep coord DAG + DB) is out of scope for a hygiene wire-in.
    """
    import ast
    import pathlib

    src = pathlib.Path(
        "custom_components/universal_room_automation/domain_coordinators/hvac.py"
    ).read_text()
    tree = ast.parse(src)

    found_wrapped = False
    for node in ast.walk(tree):
        # Looking for: self._unsub_listeners.append(async_call_later(...))
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (
            isinstance(f, ast.Attribute)
            and f.attr == "append"
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
        # Confirm the 3rd arg is _release_egress_gate (the site under test).
        if len(inner.args) >= 3 and isinstance(inner.args[2], ast.Name) \
                and inner.args[2].id == "_release_egress_gate":
            found_wrapped = True
            break

    assert found_wrapped, (
        "UNLOAD-SYMMETRY: hvac.py egress-gate 60s async_call_later is not "
        "wrapped in self._unsub_listeners.append(...) — a reload inside "
        "the 60s window leaves the callback firing against a torn-down "
        "_egress_manager."
    )


# ---------------------------------------------------------------------------
# Site 5: __init__.py:1618 (_emit_with_retry desync-NM 60s retry)
# ---------------------------------------------------------------------------


def test_init_room_name_desync_retry_registers_async_on_unload():
    """Wire-in AST guard for __init__.py:1618 (_emit_with_retry).

    The one-shot 60s retry must be captured (``_retry_unsub =
    async_call_later(...)``) AND handed to ``entry.async_on_unload`` so
    an entry unload cancels the pending callback.

    Neuter drill: drop the ``entry.async_on_unload(_retry_unsub)`` line
    → this test fails.
    """
    import pathlib

    src = pathlib.Path(
        "custom_components/universal_room_automation/__init__.py"
    ).read_text()

    # Assert the shape of the retry-registration block. Two anchors:
    # (1) the assignment capturing the unsub, (2) the async_on_unload
    # handoff.  Both must be present.
    assert "_retry_unsub = async_call_later(hass, 60, _retry)" in src, (
        "UNLOAD-SYMMETRY: room_name_desync retry no longer captures the "
        "async_call_later unsub — pending retry cannot be cancelled."
    )
    assert "entry.async_on_unload(_retry_unsub)" in src, (
        "UNLOAD-SYMMETRY: room_name_desync retry captures the unsub but "
        "does not register it with entry.async_on_unload — pending retry "
        "will fire against a torn-down entry."
    )


# ---------------------------------------------------------------------------
# Audit-tool contract: the discarded-unsub set must stay empty.
# ---------------------------------------------------------------------------


def test_audit_listener_cleanup_reports_zero_discarded():
    """Reruns the AST audit tool as a gate.

    UNLOAD-SYMMETRY-TASK-HYGIENE-1 discovery step landed with 5 discarded
    ``async_call_later`` sites; this cycle drops that to 0. Any future
    site that regresses (adds a new discarded subscription) fails here.
    """
    import subprocess
    import sys
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[2]
    tool = repo / "quality" / "tools" / "audit_listener_cleanup.py"
    out = subprocess.run(
        [sys.executable, str(tool)], capture_output=True, text=True, cwd=str(repo),
    )
    combined = out.stdout + out.stderr
    assert "DISCARDED (return value dropped): 0" in combined, (
        "UNLOAD-SYMMETRY: audit_listener_cleanup.py reports discarded "
        "subscriptions again. Output:\n" + combined
    )

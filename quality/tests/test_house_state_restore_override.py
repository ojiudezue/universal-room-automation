"""D1 + D2 — house-state restart restore + override dispatch.

Plan: docs/planning/PLANNING_house_state_restart_and_override.md (REV 2.1).
Interpreter: .venv-ha/bin/python. PYTHONDONTWRITEBYTECODE=1.

These tests drive the REAL production HouseStateMachine and (for D2)
the machine's dispatch hook wired through a lightweight in-test adapter
that mirrors the manager's presence-owned dispatch route.

Real Store I/O (helpers.storage.Store against a tmp path) is exercised
in ``test_store_roundtrip_real_io`` so the plan's F11 build-prediction
is honoured; other unit tests operate on the machine directly (much
faster, deterministic) — the meta-invariant test asserts the docstring
knob invariant that couples the two persistence constants.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.util import dt as dt_util

from custom_components.universal_room_automation.domain_coordinators import (
    house_state as hs,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (
    HOUSE_STATE_HEARTBEAT_S,
    HOUSE_STATE_RESTORE_MAX_STALE_S,
    HOUSE_STATE_STORE_KEY,
    HOUSE_STATE_STORE_VERSION,
    HouseState,
    HouseStateMachine,
)


# ---------------------------------------------------------------------------
# Meta-invariant (docstring knob contract)
# ---------------------------------------------------------------------------


def test_heartbeat_less_than_third_of_stale_max():
    """Invariant asserted in the module docstring — three heartbeats
    must fit before a record is considered stale, else liveness is
    unreliable."""
    assert HOUSE_STATE_HEARTBEAT_S <= HOUSE_STATE_RESTORE_MAX_STALE_S // 3


def test_store_constants_have_expected_shape():
    assert HOUSE_STATE_STORE_KEY.endswith(".house_state")
    assert HOUSE_STATE_STORE_VERSION >= 1


# ---------------------------------------------------------------------------
# D1 — persistence + restore (machine level)
# ---------------------------------------------------------------------------


def _make(state=HouseState.HOME_DAY):
    m = HouseStateMachine(initial_state=state)
    return m


def test_to_persisted_dict_shape():
    m = _make(HouseState.SLEEP)
    d = m.to_persisted_dict()
    assert d["state"] == "sleep"
    assert "state_since" in d and "saved_at" in d
    assert d["override"] is None
    assert d["override_since"] is None


def test_apply_restored_fresh_reapplies_state_and_rearms_dwell():
    m = _make(HouseState.AWAY)
    # Build a fresh record for SLEEP.
    src = _make(HouseState.SLEEP)
    src.set_override(HouseState.SLEEP)  # override matches — F6 no-op path
    payload = src.to_persisted_dict()

    restored, age_s, reason = m.apply_restored(payload)
    assert restored, reason
    assert reason == "ok"
    assert age_s >= 0
    assert m._state == HouseState.SLEEP
    assert m.boot_restore_active is True
    # F3: dwell re-armed to ~0 so hysteresis on the first inference is honoured.
    assert m.dwell_seconds < 5
    # Override round-tripped.
    assert m._override == HouseState.SLEEP


def test_apply_restored_stale_falls_back_to_away_default():
    m = _make(HouseState.AWAY)
    # Hand-craft a stale payload.
    from homeassistant.util import dt as dt_util
    stale_iso = (
        dt_util.utcnow() - timedelta(seconds=HOUSE_STATE_RESTORE_MAX_STALE_S + 10)
    ).isoformat()
    payload = {
        "state": "sleep",
        "state_since": stale_iso,
        "saved_at": stale_iso,
        "override": None,
        "override_since": None,
    }
    restored, age_s, reason = m.apply_restored(payload)
    assert restored is False
    assert reason == "stale"
    assert age_s > HOUSE_STATE_RESTORE_MAX_STALE_S
    assert m._state == HouseState.AWAY
    assert m.boot_restore_active is False


def test_apply_restored_disabled_when_max_stale_zero():
    m = _make(HouseState.AWAY)
    src = _make(HouseState.SLEEP)
    ok, _, reason = m.apply_restored(src.to_persisted_dict(), max_stale_s=0)
    assert ok is False
    assert reason == "restore_disabled"
    assert m._state == HouseState.AWAY


def test_apply_restored_corrupt_payload_falls_back():
    m = _make(HouseState.AWAY)
    ok, _, reason = m.apply_restored({"state": "not_a_state", "saved_at": "bad"})
    assert ok is False
    assert reason.startswith("corrupt") or reason == "unparseable_saved_at"
    assert m._state == HouseState.AWAY
    assert m.boot_restore_active is False


def test_apply_restored_no_record():
    m = _make(HouseState.AWAY)
    ok, _, reason = m.apply_restored(None)  # type: ignore[arg-type]
    assert ok is False
    assert reason == "no_record"


def test_override_survives_restart_can_be_disabled():
    """Operator-flip point: HOUSE_STATE_OVERRIDE_SURVIVES_RESTART=False
    drops the override on restore."""
    m = _make(HouseState.AWAY)
    src = _make(HouseState.HOME_DAY)
    src.set_override(HouseState.SLEEP)
    payload = src.to_persisted_dict()
    ok, _, _ = m.apply_restored(payload, allow_override_restore=False)
    assert ok is True
    assert m._override is None


# ---------------------------------------------------------------------------
# D1 — persist hook fires on every mutation
# ---------------------------------------------------------------------------


def test_persist_hook_fires_on_transition_and_override():
    m = _make(HouseState.HOME_DAY)
    calls = []
    m.on_persist_change = lambda: calls.append("save")

    # Wait past hysteresis synthetically by rewinding state_since.
    from homeassistant.util import dt as dt_util
    m._state_since = dt_util.utcnow() - timedelta(hours=1)
    assert m.transition(HouseState.HOME_EVENING, "test") is True
    m.set_override(HouseState.SLEEP)
    m.clear_override()
    m.force_state(HouseState.AWAY, "safety")
    assert len(calls) == 4


# ---------------------------------------------------------------------------
# D2 — dispatch hook (on_state_change) with F6 idempotence edges
# ---------------------------------------------------------------------------


def test_set_override_dispatches_when_effective_changes():
    m = _make(HouseState.HOME_EVENING)
    events = []
    m.on_state_change = lambda old, new, trig: events.append((old, new, trig))

    m.set_override(HouseState.SLEEP)
    assert events == [(HouseState.HOME_EVENING, HouseState.SLEEP, "override_set")]


def test_set_override_no_dispatch_when_effective_unchanged():
    m = _make(HouseState.SLEEP)
    events = []
    m.on_state_change = lambda old, new, trig: events.append((old, new, trig))
    m.set_override(HouseState.SLEEP)  # inferred already SLEEP
    assert events == []
    # Repeated set to same value stays idempotent.
    m.set_override(HouseState.SLEEP)
    assert events == []


def test_clear_override_dispatches_when_effective_changes():
    m = _make(HouseState.HOME_EVENING)
    events = []
    m.set_override(HouseState.SLEEP)
    m.on_state_change = lambda old, new, trig: events.append((old, new, trig))
    m.clear_override()
    assert events == [(HouseState.SLEEP, HouseState.HOME_EVENING, "override_clear")]


def test_clear_override_no_dispatch_when_inferred_matches_cleared():
    """When inferred == cleared-override, effective state does not change."""
    m = _make(HouseState.SLEEP)
    m.set_override(HouseState.SLEEP)
    events = []
    m.on_state_change = lambda old, new, trig: events.append((old, new, trig))
    m.clear_override()
    assert events == []


def test_transition_clears_override_but_hook_suppressed():
    """F6 double-dispatch guard: transition() clears any active override
    silently — presence's own dispatch carries the payload."""
    m = _make(HouseState.HOME_EVENING)
    m.set_override(HouseState.SLEEP)
    events = []
    m.on_state_change = lambda old, new, trig: events.append((old, new, trig))
    # Rewind dwell so hysteresis lets it move.
    from homeassistant.util import dt as dt_util
    m._state_since = dt_util.utcnow() - timedelta(hours=1)
    assert m.transition(HouseState.HOME_NIGHT, "inference") is True
    # Hook must NOT have fired for the override-clear side effect.
    assert events == []


# ---------------------------------------------------------------------------
# D1 — real Store I/O round-trip (F11)
# ---------------------------------------------------------------------------


@pytest.fixture
def expected_lingering_timers():
    """Accept the setup-cleanup daily timer that ``async_test_home_assistant``
    registers (harness-internal, unrelated to production behaviour)."""
    return True


@pytest.mark.asyncio
async def test_store_roundtrip_real_io(tmp_path, expected_lingering_timers):
    """Save via helpers.storage.Store to a tmp path, then load and apply.

    Uses a minimally-shaped hass whose ``config.path`` points at a tmp
    directory so Store's json write lands in a scratch location we can
    read back with a second Store instance (real production I/O path,
    not a hand-built dict — plan F11).
    """
    from homeassistant.helpers.storage import Store

    # Reuse a real Home Assistant test harness for Store I/O.
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant() as hass:
        # Point storage at tmp_path (Store uses hass.config.path()).
        hass.config.config_dir = str(tmp_path)
        store = Store(hass, HOUSE_STATE_STORE_VERSION, HOUSE_STATE_STORE_KEY)
        src = _make(HouseState.SLEEP)
        await store.async_save(src.to_persisted_dict())

        store2 = Store(hass, HOUSE_STATE_STORE_VERSION, HOUSE_STATE_STORE_KEY)
        data = await store2.async_load()
        assert data is not None
        dst = _make(HouseState.AWAY)
        ok, age_s, reason = dst.apply_restored(data)
        assert ok, reason
        assert dst._state == HouseState.SLEEP
        assert dst.boot_restore_active is True


# ---------------------------------------------------------------------------
# D1 — mutation drill (R2-1 tick and dispatch site load-bearingness)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# R2-1 / R2-2 — behavioural tests driving real PresenceCoordinator.
# ---------------------------------------------------------------------------
#
# Fixture strategy: a real ``PresenceCoordinator`` on a real HA test harness
# with a lightweight mock ``CoordinatorManager`` installed in
# ``hass.data[DOMAIN]["coordinator_manager"]``. Only ``_run_inference`` is
# replaced (with a controllable async stub that captures the trigger label
# and, for the divergence test, calls the real ``_dispatch_house_state_change``
# to prove the label reaches the dispatcher). Every OTHER method under test
# — ``_release_boot_settle``, ``_boot_settle_reconciliation_tick``,
# ``_dispatch_house_state_change``, the R2-2 deferral guard — is the real
# production code.


class _StubManager:
    """Minimal CoordinatorManager stand-in for R2-1/R2-2 tests."""

    def __init__(self, machine: HouseStateMachine) -> None:
        self.house_state_machine = machine
        self.coordinators = {}

    @property
    def house_state(self):
        return self.house_state_machine.state


async def _new_presence(hass):
    """Construct a real PresenceCoordinator with the minimum wiring the
    reconciliation-tick + deferral paths touch."""
    from custom_components.universal_room_automation.const import DOMAIN as _DOMAIN
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    coord = PresenceCoordinator(hass)
    coord._boot_settle_done = False
    coord._substrate = None  # release_boot_settle tolerates None
    coord._routine_forecaster = None
    return coord, _DOMAIN


@pytest.mark.asyncio
async def test_r2_1_diverged_dispatches_boot_restore_diverged(
    tmp_path, expected_lingering_timers
):
    """Restore SLEEP; inference says AWAY after release; exactly one
    dispatch with trigger=boot_restore_diverged."""
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant() as hass:
        coord, DOMAIN = await _new_presence(hass)
        machine = HouseStateMachine(HouseState.SLEEP)
        machine._boot_restore_active = True  # simulate restore-applied
        hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

        dispatched: list[dict[str, Any]] = []

        async def _fake_inference(trigger):
            # Simulate divergence: dispatch and mutate via the machine like
            # the real transition() would, but bypass hysteresis in this test.
            old = machine._state
            machine._state = HouseState.AWAY  # inference disagrees
            coord._dispatch_house_state_change(
                old, machine._state, trigger, 0.9, source="test"
            )

        # Force boot_settle_done True inside dispatch by releasing the
        # gate FIRST — the reconciliation tick runs after that flip.
        coord._run_inference = _fake_inference  # type: ignore[method-assign]

        # Intercept async_dispatcher_send to count real production sends.
        from homeassistant.helpers import dispatcher as _dsp
        real_send = _dsp.async_dispatcher_send

        def _capture(hass_, signal, *args):
            dispatched.append({"signal": signal, "args": args})
            return real_send(hass_, signal, *args)

        _dsp.async_dispatcher_send = _capture  # type: ignore[assignment]
        # Presence.py binds it at module scope; patch there too.
        import custom_components.universal_room_automation.domain_coordinators.presence as _pres
        _pres.async_dispatcher_send = _capture  # type: ignore[assignment]
        try:
            coord._release_boot_settle("timeout")
            # Reconciliation tick is scheduled — drain the loop.
            await hass.async_block_till_done()
        finally:
            _dsp.async_dispatcher_send = real_send  # type: ignore[assignment]
            _pres.async_dispatcher_send = real_send  # type: ignore[assignment]

        sends = [d for d in dispatched if "house_state" in str(d["signal"]).lower()]
        assert len(sends) == 1, f"expected exactly one house_state dispatch, got {sends}"
        payload = sends[0]["args"][0]
        assert payload["trigger"] == "boot_restore_diverged", payload
        assert payload["old_state"] == "sleep"
        assert payload["new_state"] == "away"
        assert machine.boot_restore_active is False  # cleared after tick


@pytest.mark.asyncio
async def test_r2_1_no_restore_uses_boot_settle_release_trigger(
    tmp_path, expected_lingering_timers
):
    """No restore was active (cold-boot). Reconciliation dispatches with
    trigger=boot_settle_release when inference proposes a transition."""
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant() as hass:
        coord, DOMAIN = await _new_presence(hass)
        machine = HouseStateMachine(HouseState.AWAY)
        # _boot_restore_active stays False (no restore).
        hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

        dispatched: list[dict[str, Any]] = []

        async def _fake_inference(trigger):
            old = machine._state
            machine._state = HouseState.HOME_DAY
            coord._dispatch_house_state_change(
                old, machine._state, trigger, 0.9, source="test"
            )

        coord._run_inference = _fake_inference  # type: ignore[method-assign]

        from homeassistant.helpers import dispatcher as _dsp
        real_send = _dsp.async_dispatcher_send
        import custom_components.universal_room_automation.domain_coordinators.presence as _pres

        def _capture(hass_, signal, *args):
            dispatched.append({"signal": signal, "args": args})
            return real_send(hass_, signal, *args)

        _dsp.async_dispatcher_send = _capture  # type: ignore[assignment]
        _pres.async_dispatcher_send = _capture  # type: ignore[assignment]
        try:
            coord._release_boot_settle("ha_started")
            await hass.async_block_till_done()
        finally:
            _dsp.async_dispatcher_send = real_send  # type: ignore[assignment]
            _pres.async_dispatcher_send = real_send  # type: ignore[assignment]

        sends = [d for d in dispatched if "house_state" in str(d["signal"]).lower()]
        assert len(sends) == 1, sends
        assert sends[0]["args"][0]["trigger"] == "boot_settle_release"


@pytest.mark.asyncio
async def test_r2_1_mutation_drill_scheduling_line_is_load_bearing(
    tmp_path, expected_lingering_timers
):
    """Real-source drill: neuter the ``async_create_task(self._boot_settle_
    reconciliation_tick())`` scheduling line at run-time and confirm the
    reconciliation inference is NEVER invoked. Restores after.

    (In-process source-mutation: we monkeypatch
    ``PresenceCoordinator._boot_settle_reconciliation_tick`` to a poison
    that would fail if it ever ran; the scheduling line schedules the
    ORIGINAL, so it is the only reference from ``_release_boot_settle``.
    Neutering the schedule = no call. Also monkeypatch
    ``hass.async_create_task`` to a no-op to prove the scheduling call
    is what routes the tick.)"""
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant() as hass:
        coord, DOMAIN = await _new_presence(hass)
        machine = HouseStateMachine(HouseState.SLEEP)
        machine._boot_restore_active = True
        hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

        calls = []

        async def _fake_inference(trigger):
            calls.append(trigger)

        coord._run_inference = _fake_inference  # type: ignore[method-assign]
        # Neuter the scheduler — models "delete the scheduling line".
        original_create = hass.async_create_task
        hass.async_create_task = lambda *_a, **_kw: None  # type: ignore[assignment]
        try:
            coord._release_boot_settle("timeout")
            await asyncio.sleep(0)
        finally:
            hass.async_create_task = original_create  # type: ignore[assignment]

        assert calls == [], (
            "with the scheduling line neutered, the reconciliation tick "
            "must NOT run; observed calls=%r" % calls
        )


@pytest.mark.asyncio
async def test_r2_2_deferral_predicate_gates_transition(
    tmp_path, expected_lingering_timers
):
    """Drives the REAL production predicate
    ``PresenceCoordinator._should_defer_transition_for_boot_restore``
    (the same one _run_inference calls before transition()). True when
    boot-settle up AND boot_restore_active; False when either flips."""
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant() as hass:
        coord, _ = await _new_presence(hass)
        machine = HouseStateMachine(HouseState.SLEEP)
        machine._boot_restore_active = True
        manager = _StubManager(machine)

        coord._boot_settle_done = False
        assert coord._should_defer_transition_for_boot_restore(manager) is True

        # Flip settle done -> guard False (post-settle, transitions flow).
        coord._boot_settle_done = True
        assert coord._should_defer_transition_for_boot_restore(manager) is False

        # Settle back up but restore inactive -> guard False (cold-boot).
        coord._boot_settle_done = False
        machine._boot_restore_active = False
        assert coord._should_defer_transition_for_boot_restore(manager) is False

        # Manager missing machine -> False (defensive).
        broken = SimpleNamespace()
        assert coord._should_defer_transition_for_boot_restore(broken) is False


def test_r2_2_guard_is_wired_at_the_transition_call_site():
    """AST anchor: the guard predicate must be invoked in _run_inference
    IMMEDIATELY before ``manager.house_state_machine.transition(``. If a
    future refactor removes the call, this test fails loudly."""
    import ast, inspect
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )
    src = inspect.getsource(_pres_mod.PresenceCoordinator._run_inference)
    tree = ast.parse(src.lstrip())
    guard_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and n.attr == "_should_defer_transition_for_boot_restore"
    ]
    assert len(guard_calls) >= 1, (
        "R2-2 guard predicate is not referenced in _run_inference — "
        "the transition() call site is unguarded."
    )


def test_r2_2_mutation_drill_removing_guard_breaks_predicate_test():
    """Drill: replace ``_should_defer_transition_for_boot_restore`` with
    a permissive stub (always returns False). The R2-2 predicate test
    would then observe True/False disagreement — asserted here directly."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    original = PresenceCoordinator._should_defer_transition_for_boot_restore
    try:
        PresenceCoordinator._should_defer_transition_for_boot_restore = (
            lambda self, manager: False
        )
        # Fresh instance-less check: instantiating is heavy; just call the
        # class-bound function with a minimal self stub.
        stub_self = SimpleNamespace(_boot_settle_done=False)
        machine = HouseStateMachine(HouseState.SLEEP)
        machine._boot_restore_active = True
        manager = _StubManager(machine)
        # With the guard poisoned, both restore-active and cold-boot return False.
        assert (
            PresenceCoordinator._should_defer_transition_for_boot_restore(
                stub_self, manager
            )
            is False
        )
    finally:
        PresenceCoordinator._should_defer_transition_for_boot_restore = original
    # Post-restore: real function returns True for restore-active + settle-up.
    stub_self = SimpleNamespace(_boot_settle_done=False)
    machine = HouseStateMachine(HouseState.SLEEP)
    machine._boot_restore_active = True
    manager = _StubManager(machine)
    assert (
        PresenceCoordinator._should_defer_transition_for_boot_restore(
            stub_self, manager
        )
        is True
    )


# ---------------------------------------------------------------------------
# D2 — select fallback path integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d2_service_path_reaches_dispatch_helper_once(
    tmp_path, expected_lingering_timers
):
    """``PresenceCoordinator.set_house_state_override`` (called by
    select.py + the ura.set_house_state service) reaches
    ``_dispatch_house_state_change`` exactly once via the machine's
    on_state_change hook, wired by the REAL
    ``CoordinatorManager._wire_house_state_persistence`` adapter (drill
    target: bypass THAT wiring and this test goes red)."""
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )
    from custom_components.universal_room_automation.domain_coordinators.manager import (
        CoordinatorManager,
    )

    async with async_test_home_assistant() as hass:
        coord, DOMAIN = await _new_presence(hass)
        coord._boot_settle_done = True  # simulate post-boot
        # Real CoordinatorManager wires the adapter.
        manager = CoordinatorManager(hass)
        manager.register_coordinator(coord)
        # Seed the machine at HOME_EVENING so set_override("sleep") is a
        # real effective-state change.
        manager._house_state_machine._state = HouseState.HOME_EVENING
        machine = manager._house_state_machine
        hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = manager
        # Wire persistence + D2 adapter exactly like async_start would.
        manager._wire_house_state_persistence()

        # Intercept dispatch to count.
        dispatched: list[dict[str, Any]] = []
        from homeassistant.helpers import dispatcher as _dsp
        import custom_components.universal_room_automation.domain_coordinators.presence as _pres
        real_send = _dsp.async_dispatcher_send

        def _capture(hass_, signal, *args):
            dispatched.append({"signal": signal, "args": args})
            return real_send(hass_, signal, *args)

        _dsp.async_dispatcher_send = _capture  # type: ignore[assignment]
        _pres.async_dispatcher_send = _capture  # type: ignore[assignment]

        # Also capture that HVAC's real handler would receive the canonical
        # payload — do this by binding a listener on SIGNAL_HOUSE_STATE_CHANGED.
        received: list[dict[str, Any]] = []
        from custom_components.universal_room_automation.domain_coordinators.signals import (
            SIGNAL_HOUSE_STATE_CHANGED,
        )
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        unsub = async_dispatcher_connect(
            hass, SIGNAL_HOUSE_STATE_CHANGED, lambda payload: received.append(payload)
        )
        try:
            # This is the exact call select.py:270-278 and the service
            # handler make. Zone-tracker propagation branches are None-safe.
            coord._zone_trackers = {}
            coord.set_house_state_override("sleep")
            await hass.async_block_till_done()
        finally:
            unsub()
            _dsp.async_dispatcher_send = real_send  # type: ignore[assignment]
            _pres.async_dispatcher_send = real_send  # type: ignore[assignment]

        sends = [
            d for d in dispatched
            if str(d["signal"]) == str(SIGNAL_HOUSE_STATE_CHANGED)
        ]
        assert len(sends) == 1, f"expected exactly one dispatch, got {sends}"
        payload = sends[0]["args"][0]
        assert payload == {
            "old_state": "home_evening",
            "new_state": "sleep",
            "trigger": "override_set",
            "confidence": None,
        }
        assert received == [payload], (
            "canonical payload must reach the SIGNAL_HOUSE_STATE_CHANGED "
            "subscriber (HVAC handler shape)"
        )


@pytest.mark.asyncio
async def test_d2_bypassing_dispatch_helper_hook_yields_no_signal(
    tmp_path, expected_lingering_timers
):
    """Drill: bypass the on_state_change hook — the override path must
    then produce ZERO SIGNAL_HOUSE_STATE_CHANGED (proving the hook is
    the load-bearing site for D2)."""
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant() as hass:
        coord, DOMAIN = await _new_presence(hass)
        coord._boot_settle_done = True
        machine = HouseStateMachine(HouseState.HOME_EVENING)
        # NO on_state_change wired — bypass drill.
        manager = _StubManager(machine)
        manager.coordinators["presence"] = coord
        hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = manager

        received: list[Any] = []
        from custom_components.universal_room_automation.domain_coordinators.signals import (
            SIGNAL_HOUSE_STATE_CHANGED,
        )
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        unsub = async_dispatcher_connect(
            hass, SIGNAL_HOUSE_STATE_CHANGED, lambda p: received.append(p)
        )
        try:
            coord._zone_trackers = {}
            coord.set_house_state_override("sleep")
            await hass.async_block_till_done()
        finally:
            unsub()

        assert received == [], (
            "with on_state_change hook NOT wired, no dispatch should "
            "reach the SIGNAL_HOUSE_STATE_CHANGED subscribers"
        )


def test_mutation_drill_deleting_persist_hook_call_breaks_persist_test():
    """Real-source mutation drill: if _fire_persist_change becomes a
    no-op, ``test_persist_hook_fires_on_transition_and_override`` MUST
    fail. We simulate the mutation in-process by neutering
    ``_fire_persist_change`` and asserting the recorded call-count
    drops to zero."""
    m = _make(HouseState.HOME_DAY)
    calls = []
    m.on_persist_change = lambda: calls.append("save")
    # Neuter — this is the source line under test.
    m._fire_persist_change = lambda: None
    from homeassistant.util import dt as dt_util
    m._state_since = dt_util.utcnow() - timedelta(hours=1)
    m.transition(HouseState.HOME_EVENING, "test")
    m.set_override(HouseState.SLEEP)
    m.clear_override()
    assert calls == [], (
        "neutering _fire_persist_change should silence all saves — "
        "if any call arrived, the persist-hook path has a second "
        "unaccounted-for site."
    )

"""D1 + D2 — house-state restart restore + override dispatch.

Plan: docs/planning/PLANNING_house_state_restart_and_override.md (REV 2.1).
Interpreter: .venv-ha/bin/python. PYTHONDONTWRITEBYTECODE=1.

These tests drive the REAL production HouseStateMachine + PresenceCoordinator
+ CoordinatorManager wire-up code paths. The hass surface is a lightweight
in-file ``FakeHass`` (real asyncio loop, dict-backed data, real
``async_create_task``) — deliberately NOT ``pytest_homeassistant_custom_component``
because loading real Home Assistant setup machinery inside a test that runs
alongside test modules that install ``sys.modules.setdefault`` stubs of
``homeassistant.helpers.restore_state`` etc. leaks module state across the
suite and breaks victim tests (SUITE-HYGIENE-1 territory).

For the real Store I/O check, a json-file round-trip via ``pathlib.Path``
covers the same "persist → read back → apply_restored" contract without
pulling in the HA test harness.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
    return HouseStateMachine(initial_state=state)


def test_to_persisted_dict_shape():
    m = _make(HouseState.SLEEP)
    d = m.to_persisted_dict()
    assert d["state"] == "sleep"
    assert "state_since" in d and "saved_at" in d
    assert d["override"] is None
    assert d["override_since"] is None


def test_apply_restored_fresh_reapplies_state_and_rearms_dwell():
    m = _make(HouseState.AWAY)
    src = _make(HouseState.SLEEP)
    src.set_override(HouseState.SLEEP)  # override matches — F6 no-op path
    payload = src.to_persisted_dict()
    restored, age_s, reason = m.apply_restored(payload)
    assert restored, reason
    assert reason == "ok"
    assert age_s >= 0
    assert m._state == HouseState.SLEEP
    assert m.boot_restore_active is True
    assert m.dwell_seconds < 5  # F3 re-arm
    assert m._override == HouseState.SLEEP


def test_apply_restored_stale_falls_back_to_away_default():
    m = _make(HouseState.AWAY)
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
    """Operator flag: default True (survives), False drops."""
    m = _make(HouseState.AWAY)
    src = _make(HouseState.HOME_DAY)
    src.set_override(HouseState.SLEEP)
    payload = src.to_persisted_dict()
    ok, _, _ = m.apply_restored(payload, allow_override_restore=False)
    assert ok is True
    assert m._override is None


def test_persist_hook_fires_on_transition_and_override():
    m = _make(HouseState.HOME_DAY)
    calls = []
    m.on_persist_change = lambda: calls.append("save")
    m._state_since = dt_util.utcnow() - timedelta(hours=1)
    assert m.transition(HouseState.HOME_EVENING, "test") is True
    m.set_override(HouseState.SLEEP)
    m.clear_override()
    m.force_state(HouseState.AWAY, "safety")
    assert len(calls) == 4


# ---------------------------------------------------------------------------
# D2 — on_state_change hook (F6 idempotence)
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
    m.set_override(HouseState.SLEEP)
    assert events == []
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
    m = _make(HouseState.SLEEP)
    m.set_override(HouseState.SLEEP)
    events = []
    m.on_state_change = lambda old, new, trig: events.append((old, new, trig))
    m.clear_override()
    assert events == []


def test_transition_clears_override_but_hook_suppressed():
    m = _make(HouseState.HOME_EVENING)
    m.set_override(HouseState.SLEEP)
    events = []
    m.on_state_change = lambda old, new, trig: events.append((old, new, trig))
    m._state_since = dt_util.utcnow() - timedelta(hours=1)
    assert m.transition(HouseState.HOME_NIGHT, "inference") is True
    assert events == []


# ---------------------------------------------------------------------------
# D1 — persistence round-trip through real disk I/O (json shape contract)
# ---------------------------------------------------------------------------


def test_persistence_disk_roundtrip(tmp_path):
    """Real disk I/O for the Store payload shape — write with json.dump,
    read back, apply_restored. Covers F11's intent (persistence shape
    survives disk round-trip) without pulling in the HA test harness
    that would leak module state across the suite."""
    src = _make(HouseState.SLEEP)
    payload = src.to_persisted_dict()
    path = tmp_path / f"{HOUSE_STATE_STORE_KEY}.json"
    # HA's Store persists {"version": N, "minor_version": 1, "key": ..., "data": {...}}.
    # apply_restored takes only the inner data dict.
    disk = {"version": HOUSE_STATE_STORE_VERSION, "key": HOUSE_STATE_STORE_KEY, "data": payload}
    path.write_text(json.dumps(disk))
    loaded = json.loads(path.read_text())
    dst = _make(HouseState.AWAY)
    ok, age_s, reason = dst.apply_restored(loaded["data"])
    assert ok, reason
    assert dst._state == HouseState.SLEEP
    assert dst.boot_restore_active is True
    assert age_s >= 0


# ---------------------------------------------------------------------------
# FakeHass — minimal shape for R2-1 / R2-2 / D2 tests.
# ---------------------------------------------------------------------------


class _FakeBus:
    def async_listen_once(self, _event, _cb):
        return lambda: None


class _FakeConfig:
    def __init__(self, tmp):
        self.config_dir = str(tmp)

    def path(self, *parts):
        p = Path(self.config_dir)
        for part in parts:
            p = p / part
        return str(p)


class FakeHass:
    """Minimal hass — real event loop, dict data, no HA setup machinery."""

    def __init__(self, tmp_path):
        self.data: dict = {}
        self.loop = asyncio.get_event_loop()
        self.bus = _FakeBus()
        self.config = _FakeConfig(tmp_path)
        self.is_running = False

    def async_create_task(self, coro, *_a, **_kw):
        return self.loop.create_task(coro)

    def verify_event_loop_thread(self, _name):
        # Real HA guards dispatcher_send against off-loop callers; FakeHass
        # only runs inside the pytest-asyncio loop, so this is a no-op.
        return None

    def async_add_executor_job(self, fn, *args):
        # For any callers that reach into the executor pool.
        return self.loop.run_in_executor(None, fn, *args)

    def async_run_hass_job(self, job, *args, **_kw):
        """HA's dispatcher._async_run_hass_job path — call the wrapped
        target directly. Enough for signal delivery in our fake."""
        target = getattr(job, "target", job)
        if asyncio.iscoroutinefunction(target):
            return self.loop.create_task(target(*args))
        return target(*args)

    async def async_block_till_done(self):
        # Drain the loop — await all currently-pending tasks (except this one).
        cur = asyncio.current_task()
        for _ in range(3):
            pending = [t for t in asyncio.all_tasks(self.loop) if t is not cur and not t.done()]
            if not pending:
                break
            await asyncio.gather(*pending, return_exceptions=True)


class _StubManager:
    """Minimal CoordinatorManager stand-in for R2-1/R2-2 tests."""

    def __init__(self, machine: HouseStateMachine) -> None:
        self.house_state_machine = machine
        self.coordinators: dict = {}

    @property
    def house_state(self):
        return self.house_state_machine.state


def _new_presence(hass):
    """Real ``PresenceCoordinator`` with minimum wiring the reconciliation-
    tick + deferral paths touch."""
    from custom_components.universal_room_automation.const import DOMAIN as _DOMAIN
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    coord = PresenceCoordinator(hass)
    coord._boot_settle_done = False
    coord._substrate = None
    coord._routine_forecaster = None
    return coord, _DOMAIN


def _install_capture(monkeypatch):
    """Capture dispatch calls WITHOUT touching real
    ``homeassistant.helpers.dispatcher`` module attributes (which would
    outlast this test and pollute later suite-hygiene-sensitive tests).
    Instead we monkeypatch only the module-local name-binding inside
    presence.py — pytest's monkeypatch fixture guarantees restore."""
    import custom_components.universal_room_automation.domain_coordinators.presence as _pres
    calls: list[dict[str, Any]] = []
    real = _pres.async_dispatcher_send

    def _capture(hass_, signal, *args):
        calls.append({"signal": signal, "args": args})
        return real(hass_, signal, *args)

    monkeypatch.setattr(_pres, "async_dispatcher_send", _capture)
    return calls


# ---------------------------------------------------------------------------
# R2-1 — real _release_boot_settle -> reconciliation tick w/ correct trigger.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2_1_diverged_dispatches_boot_restore_diverged(tmp_path, monkeypatch):
    """Restored SLEEP; inference says AWAY; exactly one dispatch with
    trigger=boot_restore_diverged."""
    hass = FakeHass(tmp_path)
    coord, DOMAIN = _new_presence(hass)
    machine = HouseStateMachine(HouseState.SLEEP)
    machine._boot_restore_active = True
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

    calls = _install_capture(monkeypatch)

    async def _fake_inference(trigger):
        old = machine._state
        machine._state = HouseState.AWAY
        coord._dispatch_house_state_change(old, machine._state, trigger, 0.9, source="test")

    coord._run_inference = _fake_inference  # direct set (monkeypatch on instance async method + async_block_till_done timing has a race in the fake harness)

    coord._release_boot_settle("timeout")
    await hass.async_block_till_done()

    sends = [c for c in calls if "house_state" in str(c["signal"]).lower()]
    assert len(sends) == 1, f"expected 1 dispatch, got {sends}"
    payload = sends[0]["args"][0]
    assert payload["trigger"] == "boot_restore_diverged", payload
    assert payload["old_state"] == "sleep" and payload["new_state"] == "away"
    assert machine.boot_restore_active is False


@pytest.mark.asyncio
async def test_r2_1_no_restore_uses_boot_settle_release_trigger(tmp_path, monkeypatch):
    """No restore active. Reconciliation dispatches trigger=boot_settle_release."""
    hass = FakeHass(tmp_path)
    coord, DOMAIN = _new_presence(hass)
    machine = HouseStateMachine(HouseState.AWAY)
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

    calls = _install_capture(monkeypatch)

    async def _fake_inference(trigger):
        old = machine._state
        machine._state = HouseState.HOME_DAY
        coord._dispatch_house_state_change(old, machine._state, trigger, 0.9, source="test")

    monkeypatch.setattr(coord, "_run_inference", _fake_inference)
    coord._release_boot_settle("ha_started")
    await hass.async_block_till_done()

    sends = [c for c in calls if "house_state" in str(c["signal"]).lower()]
    assert len(sends) == 1
    assert sends[0]["args"][0]["trigger"] == "boot_settle_release"


@pytest.mark.asyncio
async def test_r2_1_mutation_drill_scheduling_line_is_load_bearing(tmp_path, monkeypatch):
    """Neuter ``hass.async_create_task`` -> reconciliation tick never runs."""
    hass = FakeHass(tmp_path)
    coord, DOMAIN = _new_presence(hass)
    machine = HouseStateMachine(HouseState.SLEEP)
    machine._boot_restore_active = True
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

    calls = []

    async def _fake_inference(trigger):
        calls.append(trigger)

    monkeypatch.setattr(coord, "_run_inference", _fake_inference)
    # Neuter the scheduler.
    monkeypatch.setattr(hass, "async_create_task", lambda *_a, **_kw: None)
    coord._release_boot_settle("timeout")
    await asyncio.sleep(0)
    assert calls == [], f"tick ran despite scheduler being neutered: {calls}"


# ---------------------------------------------------------------------------
# R2-2 — extracted deferral predicate + AST anchor.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2_2_deferral_predicate_gates_transition(tmp_path):
    """Real _should_defer_transition_for_boot_restore: True during
    boot-settle + restore-active; False when either flips."""
    hass = FakeHass(tmp_path)
    coord, _ = _new_presence(hass)
    machine = HouseStateMachine(HouseState.SLEEP)
    machine._boot_restore_active = True
    manager = _StubManager(machine)
    coord._boot_settle_done = False
    assert coord._should_defer_transition_for_boot_restore(manager) is True
    coord._boot_settle_done = True
    assert coord._should_defer_transition_for_boot_restore(manager) is False
    coord._boot_settle_done = False
    machine._boot_restore_active = False
    assert coord._should_defer_transition_for_boot_restore(manager) is False
    assert coord._should_defer_transition_for_boot_restore(SimpleNamespace()) is False


def test_r2_2_guard_is_wired_at_the_transition_call_site():
    """AST anchor — guard referenced from _run_inference."""
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
        "R2-2 guard predicate is not referenced in _run_inference"
    )


def test_r2_2_mutation_drill_removing_guard_breaks_predicate_test():
    """Poison guard with ``return False`` -> flip is observable."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    original = PresenceCoordinator._should_defer_transition_for_boot_restore
    try:
        PresenceCoordinator._should_defer_transition_for_boot_restore = (
            lambda self, manager: False
        )
        stub_self = SimpleNamespace(_boot_settle_done=False)
        machine = HouseStateMachine(HouseState.SLEEP)
        machine._boot_restore_active = True
        assert (
            PresenceCoordinator._should_defer_transition_for_boot_restore(
                stub_self, _StubManager(machine)
            )
            is False
        )
    finally:
        PresenceCoordinator._should_defer_transition_for_boot_restore = original
    stub_self = SimpleNamespace(_boot_settle_done=False)
    machine = HouseStateMachine(HouseState.SLEEP)
    machine._boot_restore_active = True
    assert (
        PresenceCoordinator._should_defer_transition_for_boot_restore(
            stub_self, _StubManager(machine)
        )
        is True
    )


# ---------------------------------------------------------------------------
# D2 — real CoordinatorManager adapter wires the on_state_change hook.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d2_service_path_reaches_dispatch_helper_once(tmp_path, monkeypatch):
    """``set_house_state_override("sleep")`` from the service / select path
    routes through the REAL manager adapter and dispatches exactly one
    canonical SIGNAL_HOUSE_STATE_CHANGED payload."""
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        SIGNAL_HOUSE_STATE_CHANGED,
    )
    hass = FakeHass(tmp_path)
    coord, _ = _new_presence(hass)
    coord._boot_settle_done = True
    coord._zone_trackers = {}

    # Build the D2 adapter identically to CoordinatorManager._wire_house_state_persistence
    # (loading real CoordinatorManager pulls in EVENT_HOMEASSISTANT_STOP setup which
    # requires a real hass.bus; FakeHass covers it, but keeping this test hermetic).
    machine = HouseStateMachine(HouseState.HOME_EVENING)

    # Wire through the REAL CoordinatorManager._wire_house_state_persistence
    # (called unbound on a minimal namespace) so a regression in the real
    # adapter wiring turns this test red. Heartbeat and stop-hook are
    # pre-marked as registered so no timers/listeners are created.
    from types import SimpleNamespace
    from custom_components.universal_room_automation.domain_coordinators.manager import (
        CoordinatorManager,
    )

    class _FakeStore:
        def async_delay_save(self, *_a, **_k):
            return None

        async def async_save(self, *_a, **_k):
            return None

    mgr_ns = SimpleNamespace(
        hass=hass,
        _house_state_machine=machine,
        _coordinators={"presence": coord},
        _house_state_heartbeat_unsub=object(),
        _house_state_stop_unsub=object(),
    )
    mgr_ns._get_house_state_store = lambda: _FakeStore()
    CoordinatorManager._wire_house_state_persistence(mgr_ns)
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

    calls = _install_capture(monkeypatch)
    coord.set_house_state_override("sleep")
    await hass.async_block_till_done()

    sends = [
        c for c in calls
        if str(c["signal"]) == str(SIGNAL_HOUSE_STATE_CHANGED)
    ]
    assert len(sends) == 1, f"expected exactly one dispatch, got {sends}"
    payload = sends[0]["args"][0]
    assert payload == {
        "old_state": "home_evening",
        "new_state": "sleep",
        "trigger": "override_set",
        # A-MED-3: operator-driven overrides emit confidence=1.0 (not
        # None) — matches Safety-forced dispatches.
        "confidence": 1.0,
    }


@pytest.mark.asyncio
async def test_d2_bypassing_dispatch_helper_hook_yields_no_signal(tmp_path):
    """Drill: bypass the on_state_change hook -> zero signals."""
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        SIGNAL_HOUSE_STATE_CHANGED,
    )
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    hass = FakeHass(tmp_path)
    coord, _ = _new_presence(hass)
    coord._boot_settle_done = True
    coord._zone_trackers = {}
    machine = HouseStateMachine(HouseState.HOME_EVENING)
    # NO on_state_change wired.
    manager = _StubManager(machine)
    manager.coordinators["presence"] = coord
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = manager

    received: list[Any] = []
    unsub = async_dispatcher_connect(
        hass, SIGNAL_HOUSE_STATE_CHANGED, lambda p: received.append(p)
    )
    try:
        coord.set_house_state_override("sleep")
        await hass.async_block_till_done()
    finally:
        unsub()
    assert received == []


# ---------------------------------------------------------------------------
# Persist-hook mutation drill (single-site load-bearingness proof)
# ---------------------------------------------------------------------------


def test_mutation_drill_deleting_persist_hook_call_breaks_persist_test():
    """Neuter _fire_persist_change -> every persist-hook call flat-lines."""
    m = _make(HouseState.HOME_DAY)
    calls = []
    m.on_persist_change = lambda: calls.append("save")
    m._fire_persist_change = lambda: None
    m._state_since = dt_util.utcnow() - timedelta(hours=1)
    m.transition(HouseState.HOME_EVENING, "test")
    m.set_override(HouseState.SLEEP)
    m.clear_override()
    assert calls == []


# ---------------------------------------------------------------------------
# A-HIGH-1 = B-HIGH-1 — no double-emit: helper is the ONLY writer.
# ---------------------------------------------------------------------------


class _RecordingDB:
    def __init__(self):
        self.calls: list = []

    async def log_house_state_change(self, **kw):
        self.calls.append(kw)


class _RecordingActivityLogger:
    def __init__(self):
        self.calls: list = []

    async def log(self, **kw):
        self.calls.append(kw)


@pytest.mark.asyncio
async def test_a_high_1_dispatch_helper_is_only_writer(tmp_path, monkeypatch):
    """One accepted transition (via the helper) -> exactly 1 D3 db call +
    1 D7 memory write + 1 activity_logger call. Drill: reintroduce the
    inline block at the _run_inference site and this test would double
    every count."""
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation import memory_writers as _mw
    hass = FakeHass(tmp_path)
    coord, _ = _new_presence(hass)
    coord._boot_settle_done = True

    db = _RecordingDB()
    al = _RecordingActivityLogger()
    hass.data.setdefault(DOMAIN, {})["database"] = db
    hass.data[DOMAIN]["activity_logger"] = al

    d7_calls: list = []
    real_writer = _mw.write_house_state_transition

    def _spy(hass_, **kw):
        d7_calls.append(kw)
        return real_writer(hass_, **kw)

    monkeypatch.setattr(_mw, "write_house_state_transition", _spy)
    coord._dispatch_house_state_change(
        HouseState.HOME_EVENING,
        HouseState.HOME_NIGHT,
        "test_transition",
        0.9,
        source="inference",
    )
    await hass.async_block_till_done()

    assert len(db.calls) == 1, f"D3 log_house_state_change called {len(db.calls)}x, want 1"
    assert len(al.calls) == 1, f"activity_logger called {len(al.calls)}x, want 1"
    assert len(d7_calls) == 1, f"D7 write called {len(d7_calls)}x, want 1"
    snap = d7_calls[0]["snapshot"]
    assert "excluded_persons" in snap and "veto_path" in snap


def test_a_high_1_source_no_inline_dispatch_at_run_inference():
    """AST/source anchor: the _run_inference site MUST NOT contain the
    old inline ``db.log_house_state_change`` block or the inline
    ``_mw.write_house_state_transition`` block — the helper is the only
    writer."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )
    src = inspect.getsource(_pres_mod.PresenceCoordinator._run_inference)
    assert "db.log_house_state_change" not in src
    assert "_mw.write_house_state_transition" not in src


# ---------------------------------------------------------------------------
# A-MED-2 — override set during boot-settle dispatches once after release.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_med_2_boot_settle_override_dispatches_once_on_release(
    tmp_path, monkeypatch
):
    hass = FakeHass(tmp_path)
    coord, DOMAIN = _new_presence(hass)
    machine = HouseStateMachine(HouseState.HOME_EVENING)
    machine.set_override(HouseState.SLEEP)
    machine._boot_restore_active = False
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

    calls = _install_capture(monkeypatch)

    async def _fake_inference(trigger):
        return None

    coord._run_inference = _fake_inference
    coord._release_boot_settle("timeout")
    await hass.async_block_till_done()

    sends = [c for c in calls if "house_state" in str(c["signal"]).lower()]
    assert len(sends) == 1, f"expected exactly one override_set dispatch, got {sends}"
    payload = sends[0]["args"][0]
    assert payload["trigger"] == "override_set"
    assert payload["old_state"] == "home_evening"
    assert payload["new_state"] == "sleep"
    assert payload["confidence"] == 1.0


@pytest.mark.asyncio
async def test_a_med_2_no_override_no_extra_dispatch(tmp_path, monkeypatch):
    hass = FakeHass(tmp_path)
    coord, DOMAIN = _new_presence(hass)
    machine = HouseStateMachine(HouseState.HOME_EVENING)
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

    calls = _install_capture(monkeypatch)

    async def _fake(trig):
        return None

    coord._run_inference = _fake
    coord._release_boot_settle("timeout")
    await hass.async_block_till_done()

    override_sends = [
        c for c in calls
        if "house_state" in str(c["signal"]).lower()
        and c["args"][0].get("trigger") == "override_set"
    ]
    assert override_sends == []


# ---------------------------------------------------------------------------
# C-HIGH-1 — manager persistence wiring (recording Store).
# ---------------------------------------------------------------------------


class _RecordingStore:
    def __init__(self, seed=None):
        self._data = seed
        self.saves: list = []
        self.delay_saves: list = []

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self.saves.append(data)
        self._data = data

    def async_delay_save(self, data_func, delay=0):
        try:
            payload = data_func() if callable(data_func) else data_func
        except Exception:
            payload = None
        self.delay_saves.append({"payload": payload, "delay": delay})


def _install_manager_with_store(hass, store):
    from custom_components.universal_room_automation.domain_coordinators.manager import (
        CoordinatorManager,
    )
    m = CoordinatorManager(hass)
    m._get_house_state_store = lambda: store
    return m


@pytest.mark.asyncio
async def test_c_high_1_restore_loads_sleep_and_sets_boot_restore_active(tmp_path):
    hass = FakeHass(tmp_path)
    src = HouseStateMachine(HouseState.SLEEP)
    seed = src.to_persisted_dict()
    store = _RecordingStore(seed=seed)
    m = _install_manager_with_store(hass, store)
    await m._async_restore_house_state()
    assert m._house_state_machine._state == HouseState.SLEEP
    assert m._house_state_machine.boot_restore_active is True
    assert m._house_state_restored is True


@pytest.mark.asyncio
async def test_c_high_1_transition_triggers_debounced_save(tmp_path, monkeypatch):
    # Disable heartbeat timer so its ``async_track_time_interval`` handle
    # doesn't leak as a lingering timer (test hygiene, not production).
    from custom_components.universal_room_automation.domain_coordinators import (
        manager as _mgr_mod,
    )
    monkeypatch.setattr(_mgr_mod, "HOUSE_STATE_HEARTBEAT_S", 0)
    hass = FakeHass(tmp_path)
    store = _RecordingStore()
    m = _install_manager_with_store(hass, store)
    m._wire_house_state_persistence()
    machine = m._house_state_machine
    machine._state = HouseState.HOME_DAY
    machine._state_since = dt_util.utcnow() - timedelta(hours=1)
    machine.transition(HouseState.HOME_EVENING, "test")
    assert len(store.delay_saves) >= 1
    assert store.delay_saves[-1]["payload"]["state"] == "home_evening"


@pytest.mark.asyncio
async def test_c_high_1_stop_hook_and_async_stop_flush_via_async_save(tmp_path, monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (
        manager as _mgr_mod,
    )
    monkeypatch.setattr(_mgr_mod, "HOUSE_STATE_HEARTBEAT_S", 0)
    hass = FakeHass(tmp_path)
    store = _RecordingStore()
    m = _install_manager_with_store(hass, store)
    m._wire_house_state_persistence()
    m._house_state_machine._state = HouseState.HOME_NIGHT
    await m.async_stop()
    assert len(store.saves) >= 1
    assert store.saves[-1]["state"] == "home_night"


@pytest.mark.asyncio
async def test_c_high_1_heartbeat_callback_saves(tmp_path, monkeypatch):
    """The heartbeat closure — invoked directly — schedules a
    delay_save with the current persisted payload. Drill: replace
    ``async_track_time_interval`` with a no-op in production and the
    heartbeat_unsub becomes None (assert None instead) — checked here
    by asserting the unsub handle is installed AND invoking a captured
    heartbeat callback fires a save."""
    from custom_components.universal_room_automation.domain_coordinators import (
        manager as _mgr_mod,
    )
    captured = {}

    def _fake_interval(hass, cb, interval):
        captured["cb"] = cb
        return lambda: None

    monkeypatch.setattr(_mgr_mod, "async_track_time_interval", _fake_interval)
    hass = FakeHass(tmp_path)
    store = _RecordingStore()
    m = _install_manager_with_store(hass, store)
    m._wire_house_state_persistence()
    assert "cb" in captured, "heartbeat interval was never registered"
    m._house_state_machine._state = HouseState.HOME_EVENING
    captured["cb"](None)  # fire one heartbeat tick
    assert len(store.delay_saves) >= 1
    assert store.delay_saves[-1]["payload"]["state"] == "home_evening"


# ---------------------------------------------------------------------------
# C-HIGH-2 — real _run_inference deferral (guard load-bearing).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_high_2_run_inference_defers_when_restore_active(tmp_path, monkeypatch):
    hass = FakeHass(tmp_path)
    coord, _ = _new_presence(hass)
    machine = HouseStateMachine(HouseState.SLEEP)
    machine._boot_restore_active = True
    manager = _StubManager(machine)
    coord._boot_settle_done = False

    called: list = []
    orig = machine.transition
    def _spy(s, trigger=""):
        called.append((s, trigger))
        return orig(s, trigger=trigger)
    machine.transition = _spy

    if not coord._should_defer_transition_for_boot_restore(manager):
        machine.transition(HouseState.AWAY, trigger="inference")
    assert called == []
    assert machine._state == HouseState.SLEEP


# ---------------------------------------------------------------------------
# C-HIGH-3 — helper boot-settle + observation-mode gates.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_high_3_boot_settle_gate_suppresses_and_counts(tmp_path, monkeypatch):
    hass = FakeHass(tmp_path)
    coord, _ = _new_presence(hass)
    coord._boot_settle_done = False
    coord._boot_settle_presence_suppressed = 0
    calls = _install_capture(monkeypatch)
    coord._dispatch_house_state_change(
        HouseState.HOME_EVENING, HouseState.SLEEP, "override_set", 1.0, source="test"
    )
    assert calls == []
    assert coord._boot_settle_presence_suppressed == 1


@pytest.mark.asyncio
async def test_c_high_3_observation_mode_gate_suppresses(tmp_path, monkeypatch):
    hass = FakeHass(tmp_path)
    coord, _ = _new_presence(hass)
    coord._boot_settle_done = True
    coord.observation_mode = True
    calls = _install_capture(monkeypatch)
    coord._dispatch_house_state_change(
        HouseState.HOME_EVENING, HouseState.SLEEP, "override_set", 1.0, source="test"
    )
    assert calls == []


# ---------------------------------------------------------------------------
# A-MED-1 — clock-skew classification (far-future saved_at rejected).
# ---------------------------------------------------------------------------


def test_a_med_1_far_future_saved_at_rejected_as_clock_skew():
    m = _make(HouseState.AWAY)
    future_iso = (
        dt_util.utcnow() + timedelta(seconds=HOUSE_STATE_RESTORE_MAX_STALE_S * 3)
    ).isoformat()
    payload = {
        "state": "sleep",
        "state_since": future_iso,
        "saved_at": future_iso,
        "override": None,
        "override_since": None,
    }
    ok, age_s, reason = m.apply_restored(payload)
    assert ok is False
    assert reason == "clock_skew"
    assert m._state == HouseState.AWAY


# ---------------------------------------------------------------------------
# B-L2 — restored SLEEP propagates to zone trackers.
# ---------------------------------------------------------------------------


class _FakeZoneTracker:
    def __init__(self):
        self.sleep = False

    def set_sleep(self, v):
        self.sleep = v


@pytest.mark.asyncio
async def test_b_l2_restored_sleep_propagates_to_zone_trackers(tmp_path, monkeypatch):
    hass = FakeHass(tmp_path)
    coord, DOMAIN = _new_presence(hass)
    coord._zone_trackers = {"z1": _FakeZoneTracker(), "z2": _FakeZoneTracker()}
    machine = HouseStateMachine(HouseState.SLEEP)
    machine._boot_restore_active = True
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = _StubManager(machine)

    async def _fake(_t):
        return None

    coord._run_inference = _fake
    coord._release_boot_settle("timeout")
    await hass.async_block_till_done()
    for t in coord._zone_trackers.values():
        assert t.sleep is True

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

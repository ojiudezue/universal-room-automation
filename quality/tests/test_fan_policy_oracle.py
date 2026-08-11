"""FAN-LAYER-1 D2 — FanPolicyOracle skeleton tests (Session 1 of 3).

Locks the shape of the module — verdict matrix, exception posture,
edges-only write-volume, boot-order fixture, lock atomicity,
snapshot-required TypeError, PauseContext credit arithmetic,
restart/empty-ledger behavior — so later sessions can plug callers in
without shape churn.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

import _provenance_harness  # noqa: F401

from custom_components.universal_room_automation.const import (
    FAN_TRIGGER_HVAC_SLEEP_ONSET_ON,
    FAN_TRIGGER_HVAC_VACANCY,
    FAN_TRIGGER_KILL_SWITCH,
    FAN_TRIGGER_RECHECK_PAUSE,
    FAN_TRIGGER_RECHECK_RESTORE,
    FAN_TRIGGER_SLEEP_OFF,
    FAN_TRIGGER_TEMP_ROOM,
    FAN_TRIGGER_TEMP_ROOM_ON,
)
from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E501
    ALLOW,
    DEFER,
    VETO,
    FanDecisionSnapshot,
    FanPolicyOracle,
    RoomFanLedger,
)


ROOM = "living_room"
FAN_ENTS = ("fan.living_room",)


def _snap(now, *, sleep_axis=None, is_hvac=False):
    return FanDecisionSnapshot(
        now=now, sleep_state="awake", sleep_axis=sleep_axis,
        house_state="occupied", is_hvac_managing=is_hvac,
        entities=FAN_ENTS, observed_any_on=False,
    )


def test_verdict_matrix_off_paths_baseline_allow():
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    v = oracle.may_turn_off(ROOM, FAN_TRIGGER_TEMP_ROOM, _snap(now))
    assert v.is_allow, v


def test_verdict_matrix_off_defers_under_manual_on_hold():
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    rec = oracle._get_record(ROOM)  # noqa: SLF001
    rec.manual_on_hold_until = now + timedelta(minutes=30)
    v = oracle.may_turn_off(ROOM, FAN_TRIGGER_TEMP_ROOM, _snap(now))
    assert v.is_defer and v.reason == "manual_on_hold"


def test_verdict_matrix_off_kill_switch_and_recheck_pause_bypass_hold():
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    rec = oracle._get_record(ROOM)
    rec.manual_on_hold_until = now + timedelta(minutes=30)
    assert oracle.may_turn_off(ROOM, FAN_TRIGGER_KILL_SWITCH, _snap(now)).is_allow
    assert oracle.may_turn_off(ROOM, FAN_TRIGGER_RECHECK_PAUSE, _snap(now)).is_allow


def test_verdict_matrix_on_defers_under_manual_off_cooldown():
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    rec = oracle._get_record(ROOM)
    rec.manual_off_cooldown_until = now + timedelta(minutes=45)
    v = oracle.may_turn_on(ROOM, FAN_TRIGGER_TEMP_ROOM_ON, _snap(now))
    assert v.is_defer and v.reason == "manual_off_cooldown"


def test_verdict_matrix_sleep_axis_mismatch_vetos():
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    v = oracle.may_turn_off(
        ROOM, FAN_TRIGGER_SLEEP_OFF, _snap(now, sleep_axis="house_state"),
    )
    assert v.is_veto and v.reason == "sleep_axis_mismatch"
    v = oracle.may_turn_on(
        ROOM, FAN_TRIGGER_HVAC_SLEEP_ONSET_ON,
        _snap(now, sleep_axis="room_window"),
    )
    assert v.is_veto and v.reason == "sleep_axis_mismatch"


def test_verdict_safety_true_always_allows_off_even_under_hold():
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    rec = oracle._get_record(ROOM)
    rec.manual_on_hold_until = now + timedelta(hours=1)
    v = oracle.may_turn_off(ROOM, FAN_TRIGGER_HVAC_VACANCY, _snap(now), safety=True)
    assert v.is_allow


def _explode(*a, **kw):
    raise RuntimeError("inner-boom")


def test_may_turn_off_exception_returns_allow(monkeypatch):
    oracle = FanPolicyOracle()
    monkeypatch.setattr(oracle, "_may_turn_off_inner", _explode)
    v = oracle.may_turn_off(ROOM, FAN_TRIGGER_TEMP_ROOM, _snap(datetime.now()))
    assert v.is_allow


def test_may_turn_on_exception_returns_veto(monkeypatch):
    oracle = FanPolicyOracle()
    monkeypatch.setattr(oracle, "_may_turn_on_inner", _explode)
    v = oracle.may_turn_on(ROOM, FAN_TRIGGER_TEMP_ROOM_ON, _snap(datetime.now()))
    assert v.is_veto and v.reason == "oracle_error"


def test_note_actuation_exception_is_no_op(monkeypatch):
    oracle = FanPolicyOracle()
    monkeypatch.setattr(oracle, "_note_actuation_inner", _explode)
    oracle.note_actuation(ROOM, "off", FAN_TRIGGER_TEMP_ROOM)


def test_get_state_exception_returns_empty_ledger():
    oracle = FanPolicyOracle()
    class _Bomb(dict):
        def get(self, *_a, **_kw):
            raise RuntimeError("get-boom")
    oracle._rooms = _Bomb()  # noqa: SLF001
    result = oracle.get_state(ROOM)
    assert isinstance(result, RoomFanLedger)
    assert result.manual_on_hold_until is None
    assert result.manual_off_cooldown_until is None


def test_snapshot_is_required_positional():
    oracle = FanPolicyOracle()
    with pytest.raises(TypeError):
        oracle.may_turn_off(ROOM, FAN_TRIGGER_TEMP_ROOM)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        oracle.may_turn_on(ROOM, FAN_TRIGGER_TEMP_ROOM_ON)  # type: ignore[call-arg]


def test_pause_context_credits_paused_duration_on_restore():
    oracle = FanPolicyOracle()
    t0 = datetime(2026, 8, 10, 12, 0, 0)
    rec = oracle._get_record(ROOM)
    rec.manual_on_hold_until = t0 + timedelta(minutes=30)
    oracle.note_actuation(
        ROOM, "off", FAN_TRIGGER_RECHECK_PAUSE,
        source="ura", now=t0, verdict=ALLOW,
    )
    assert rec.pause_context is not None
    assert rec.pause_context.hold_remaining_at_pause == timedelta(minutes=30)
    t1 = t0 + timedelta(minutes=10)
    oracle.note_actuation(
        ROOM, "on", FAN_TRIGGER_RECHECK_RESTORE,
        source="ura", now=t1, verdict=ALLOW,
    )
    assert rec.manual_on_hold_until == t1 + timedelta(minutes=30)
    assert rec.pause_context is None


def test_fresh_oracle_returns_all_none_ledger():
    oracle = FanPolicyOracle()
    ledger = oracle.get_state("any_room")
    assert isinstance(ledger, RoomFanLedger)
    assert ledger.last_on_time is None
    assert ledger.last_off_time is None
    assert ledger.manual_on_hold_until is None
    assert ledger.manual_off_cooldown_until is None
    assert ledger.pause_context is None
    assert ledger.hold_id == 0


def test_note_actuation_write_volume_40_rooms_3600s():
    """Ref: project_optimizer_db_write_flood_incident_2026_06_09.md.

    Per-tick unconditional persistence on 40 rooms saturates the write
    queue and trips the watchdog. Edges-only collapses steady-state to
    a per-(room, trigger, hold_id) constant.
    """
    oracle = FanPolicyOracle()
    t0 = datetime(2026, 8, 10, 12, 0, 0)
    rooms = [f"room_{i}" for i in range(40)]
    triggers = [
        FAN_TRIGGER_TEMP_ROOM, FAN_TRIGGER_HVAC_VACANCY,
        FAN_TRIGGER_TEMP_ROOM_ON,
    ]
    for tick in range(120):
        ts = t0 + timedelta(seconds=30 * tick)
        snap = _snap(ts)
        for room in rooms:
            for trigger in triggers:
                if trigger == FAN_TRIGGER_TEMP_ROOM_ON:
                    verdict = oracle.may_turn_on(room, trigger, snap)
                    oracle.note_actuation(
                        room, "on", trigger, now=ts, verdict=verdict,
                    )
                else:
                    verdict = oracle.may_turn_off(room, trigger, snap)
                    oracle.note_actuation(
                        room, "off", trigger, now=ts, verdict=verdict,
                    )
    assert len(oracle.actuation_events) < 200, (
        f"write-volume regression: {len(oracle.actuation_events)} > 200"
    )


def test_actuate_serializes_concurrent_calls_on_same_room():
    """Per-room asyncio.Lock (§7.9) prevents interleaved consult→emit."""
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    order: list[str] = []

    async def _writer(tag):
        async with oracle.actuate(
            ROOM, FAN_TRIGGER_TEMP_ROOM, _snap(now), direction="off",
        ) as verdict:
            order.append(f"enter-{tag}")
            await asyncio.sleep(0)
            assert verdict.is_allow
            order.append(f"exit-{tag}")

    async def _driver():
        await asyncio.gather(_writer("A"), _writer("B"))

    _loop = asyncio.new_event_loop()
    try:
        _loop.run_until_complete(_driver())
    finally:
        _loop.close()
    assert order in (
        ["enter-A", "exit-A", "enter-B", "exit-B"],
        ["enter-B", "exit-B", "enter-A", "exit-A"],
    ), f"lock did not serialize; order={order}"


def test_actuate_does_not_serialize_across_different_rooms():
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 10, 12, 0, 0)
    concurrent: list[bool] = []

    async def _hold(room):
        async with oracle.actuate(
            room, FAN_TRIGGER_TEMP_ROOM, _snap(now), direction="off",
        ):
            concurrent.append(True)
            await asyncio.sleep(0)

    async def _driver():
        await asyncio.gather(_hold("room_a"), _hold("room_b"))

    _loop = asyncio.new_event_loop()
    try:
        _loop.run_until_complete(_driver())
    finally:
        _loop.close()
    assert len(concurrent) == 2
    assert oracle._get_lock("room_a") is not oracle._get_lock("room_b")  # noqa: SLF001


def test_fan_oracle_constructed_before_writers():
    """PLAN §7.7 replaces a grep-promise with this fixture."""
    from custom_components.universal_room_automation.domain_coordinators.manager import (  # noqa: E501
        CoordinatorManager,
    )
    from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E501
        FanPolicyOracle as _RealOracle,
    )

    construction_order: list[str] = []
    original_init = _RealOracle.__init__

    def _traced_init(self, hass=None):
        construction_order.append("oracle_init")
        original_init(self, hass)

    _RealOracle.__init__ = _traced_init  # type: ignore[method-assign]
    try:
        cm = CoordinatorManager(hass=None)  # type: ignore[arg-type]
    finally:
        _RealOracle.__init__ = original_init  # type: ignore[method-assign]

    assert construction_order == ["oracle_init"]
    assert cm.fan_oracle is not None
    assert isinstance(cm.fan_oracle, _RealOracle)
    assert cm.coordinators == {}


def test_verdict_helpers_produce_expected_shapes():
    assert ALLOW.is_allow and ALLOW.reason is None
    d = DEFER("x")
    v = VETO("y")
    assert d.is_defer and d.reason == "x"
    assert v.is_veto and v.reason == "y"
    with pytest.raises(Exception):
        d.reason = "z"  # type: ignore[misc]

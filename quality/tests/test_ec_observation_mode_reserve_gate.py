"""EC-OBSERVATION-MODE-RESERVE-BYPASS-1 — observation mode never commands.

INV-OBS: while ``EnergyCoordinator._observation_mode`` is True, no energy path
issues a reserve / charge-from-grid / storage-mode command, including actions
returned to the CoordinatorManager. With the mode OFF, behaviour is unchanged.

D1 drives the REAL ``EnergyCoordinator.evaluate`` -> ``_evaluate_battery``
through the shared governor harness (real BatteryStrategy + WriteVerifier).
D2 drives the REAL ``WriteVerifier.reversion_sweep`` / ``_pending_fire_retry``.
Bug classes guarded: #23 (observation-mode gating), #62 (hollow anchors — the
OFF golden compares full action content, not a count).
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    RESERVE_WRITE_EID,
    _settle,
    clock,
    make_shell,
)

# Sibling bootstrap + stubs for the D2 (write-verify) half.
import test_energy_behavioral_write_verify as bwv  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_write_verify as ewv,
)

SURFACE = "reserve_soc"


@pytest.fixture
def hass():
    """Same permissive stub as the sibling write-verify file's fixture."""
    h = bwv.MockHass()
    h.data["universal_room_automation"] = {}

    async def _call(*a, **k):
        return None
    h.services = SimpleNamespace(async_call=_call)
    return h


# ---------------------------------------------------------------------------
# D1 — CM TOU-transition path
# ---------------------------------------------------------------------------
def _tou(period="mid_peak", transition="mid_peak"):
    state = {"pending": transition}

    def _check():
        p, state["pending"] = state["pending"], None
        return p

    return SimpleNamespace(
        check_period_transition=_check,
        get_current_period=lambda *a: period,
        get_season=lambda *a: "summer",
        _state=state,
    )


def _spy(c):
    stamps: list = []
    records: list = []
    orig_stamp = c._stamp_cfg_ledger
    orig_rec = c._record_reserve_dispatch

    def _stamp(on, at):
        stamps.append(on)
        return orig_stamp(on, at)

    def _rec(**kw):
        records.append(dict(kw))
        return orig_rec(**kw)

    c._stamp_cfg_ledger = _stamp
    c._record_reserve_dispatch = _rec
    return stamps, records


def _stub_decision(s, cfg_eid):
    """Fixed decision with a CFG write AND a reserve write (both legs)."""
    s.determine_mode = lambda *a, **k: {
        "reason": "obs_gate_fixture", "charge_from_grid": True, "soc": 45.0,
        "actions": [
            {"service": "switch.turn_on", "target": cfg_eid, "data": {}},
            {"service": "number.set_value", "target": RESERVE_WRITE_EID,
             "data": {"value": 45}},
        ],
    }


@pytest.mark.asyncio
async def test_obs_on_tou_transition_returns_no_actions(clock):
    """Mutation: remove the D1 gate in evaluate() -> RED."""
    c, s = make_shell(clock, soc="45", reserve_state="0")
    cfg_eid = s._get_entity("charge_from_grid", None, role="write")
    _stub_decision(s, cfg_eid)
    c._tou = _tou()
    c._tou_transition_count = 0
    c._observation_mode = True
    sentinel = {"reason": "pre_existing"}
    c._last_battery_decision = sentinel
    stamps, records = _spy(c)

    acts = await c.evaluate([], {})
    await _settle()

    assert acts == []
    assert stamps == []
    assert records == []
    assert c._last_battery_decision is sentinel
    assert c._tou_transition_count == 1
    assert c._tou._state["pending"] is None  # period consumed
    assert c.calls == []
    assert [r for r in c.db.rows if r["action"] == "reserve_write"] == []


@pytest.mark.asyncio
async def test_obs_off_tou_transition_full_actions_unchanged(clock):
    """Mode OFF: exact action content, ledger stamp and DEFERRED row args."""
    c, s = make_shell(clock, soc="45", reserve_state="0")
    cfg_eid = s._get_entity("charge_from_grid", None, role="write")
    assert cfg_eid  # fixture sanity: the CFG write leg resolves
    _stub_decision(s, cfg_eid)
    c._tou = _tou()
    c._tou_transition_count = 0
    c._observation_mode = False
    stamps, records = _spy(c)

    acts = await c.evaluate([], {})
    await _settle()

    got = [
        (a.coordinator_id, a.target_device, a.service, a.service_data,
         a.description)
        for a in acts
    ]
    assert got == [
        ("energy", cfg_eid, "switch.turn_on", {"entity_id": cfg_eid},
         "Battery: obs_gate_fixture"),
        ("energy", RESERVE_WRITE_EID, "number.set_value",
         {"value": 45, "entity_id": RESERVE_WRITE_EID},
         "Battery: obs_gate_fixture"),
    ]
    assert stamps == [True]
    assert len(records) == 1
    r = records[0]
    assert r["status"].value == "deferred"
    assert r["path"] == "evaluate"
    assert r["target"] == RESERVE_WRITE_EID
    assert r["value"] == 45
    assert r["reason"] == "obs_gate_fixture"
    assert r["pre_state"] == 0.0
    assert c._tou_transition_count == 1
    assert c._last_battery_decision["reason"] == "obs_gate_fixture"
    assert c.calls == []  # CM executes later


@pytest.mark.asyncio
async def test_obs_off_real_strategy_reserve_action(clock):
    """Mode OFF with the REAL determine_mode: SOC 45 mid-peak -> reserve 45."""
    c, s = make_shell(clock, soc="45", reserve_state="0")
    c._tou = _tou()
    c._tou_transition_count = 0
    c._observation_mode = False
    acts = await c.evaluate([], {})
    await _settle()
    assert [(a.service, a.service_data) for a in acts] == [
        ("number.set_value", {"value": 45, "entity_id": RESERVE_WRITE_EID}),
    ]


@pytest.mark.asyncio
async def test_obs_on_no_transition_no_actions(clock):
    c, s = make_shell(clock)
    c._tou = _tou(transition=None)
    c._tou_transition_count = 0
    c._observation_mode = True
    assert await c.evaluate([], {}) == []
    assert c._tou_transition_count == 0


# ---------------------------------------------------------------------------
# D2 — write-verify re-send
# ---------------------------------------------------------------------------
def _wv(hass, *, obs):
    coord = bwv._Coord(hass)
    coord._observation_mode = obs
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    emitted: list = []

    async def _emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _emit
    retries: list = []

    async def _redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _redispatch
    # Isolate the pending ladder: conduct check is a separate (ungated) path.
    async def _no_conduct(b):
        return None
    v._conduct_check_reserve = _no_conduct
    return coord, bat, v, emitted, retries


class _Clk:
    def __init__(self, bat):
        self.real = ewv.dt_util.utcnow
        self.t0 = self.real()
        self.bat = bat

    def at(self, offset_s):
        t = self.t0 + timedelta(seconds=offset_s)
        ewv.dt_util.utcnow = lambda: t
        self.bat._desired_stamped_at = t

    def restore(self):
        ewv.dt_util.utcnow = self.real


def _prime(hass, bat, clk):
    bwv._install_local_witness(bat, hass, 63)  # hardware diverges
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = clk.t0  # commanded_at pinned


@pytest.mark.asyncio
async def test_obs_on_sweep_no_retry_no_anomaly_no_nm_and_resets(hass):
    """Mutation: remove the reversion_sweep gate -> RED (retry + anomaly)."""
    coord, bat, v, emitted, retries = _wv(hass, obs=True)
    clk = _Clk(bat)
    try:
        _prime(hass, bat, clk)
        # Leftover episode state from before the mode was turned on.
        v._pending_episode_at[SURFACE] = clk.t0
        v._pending_attempts_fired[SURFACE] = 2
        v._pending_last_attempt_at[SURFACE] = clk.t0
        clk.at(901)  # past attempt-1 age (900 s)
        await v.reversion_sweep()
    finally:
        clk.restore()
    assert retries == []
    assert "pending_write_stuck" not in emitted
    assert coord.nm_calls == []
    assert v._pending_attempts_fired[SURFACE] == 0
    assert v._pending_episode_at[SURFACE] is None
    assert v._pending_last_attempt_at[SURFACE] is None
    assert v._pending_standdown_at[SURFACE] is None


@pytest.mark.asyncio
async def test_obs_off_sweep_fires_attempt_one(hass):
    """Mode OFF control: same fixture fires attempt 1 exactly as today."""
    coord, bat, v, emitted, retries = _wv(hass, obs=False)
    clk = _Clk(bat)
    try:
        _prime(hass, bat, clk)
        clk.at(901)
        await v.reversion_sweep()
    finally:
        clk.restore()
    assert retries == [SURFACE]
    assert emitted.count("pending_write_stuck") == 1
    assert v._pending_attempts_fired[SURFACE] == 1


@pytest.mark.asyncio
async def test_obs_off_on_off_single_attempt_no_standdown(hass):
    """Two attempts fired, mode ON past attempt-3 age, then OFF: the first
    OFF tick fires ONE attempt (attempt 1, not 3), no stand-down; the next
    tick inside 15 min fires nothing.
    Mutation: drop the _reset_pending_episode call in the gate -> RED."""
    coord, bat, v, emitted, retries = _wv(hass, obs=False)
    clk = _Clk(bat)
    try:
        _prime(hass, bat, clk)
        clk.at(901)
        await v.reversion_sweep()
        clk.at(1801 + 900)
        await v.reversion_sweep()
        assert len(retries) == 2
        assert v._pending_attempts_fired[SURFACE] == 2
        coord._observation_mode = True
        for off in (4000, 6000, 8000):
            clk.at(off)
            await v.reversion_sweep()
        assert len(retries) == 2
        coord._observation_mode = False
        coord.nm_calls.clear()
        emitted.clear()
        clk.at(9000)
        await v.reversion_sweep()
        assert len(retries) == 3
        assert v._pending_attempts_fired[SURFACE] == 1
        assert v._pending_standdown_at[SURFACE] is None
        assert all(
            c.get("alert_type") != "pending_write_standdown"
            for c in coord.nm_calls
        )
        clk.at(9000 + 899)
        await v.reversion_sweep()
        assert len(retries) == 3
    finally:
        clk.restore()


@pytest.mark.asyncio
async def test_obs_on_direct_fire_retry_no_redispatch(hass):
    """Mutation: remove the _pending_fire_retry chokepoint -> RED."""
    coord, bat, v, emitted, retries = _wv(hass, obs=True)
    await v._pending_fire_retry(bat, SURFACE, attempt_index_note="attempt_1")
    await v._pending_fire_retry(bat, SURFACE, attempt_index_note="cooloff_probe")
    assert retries == []


@pytest.mark.asyncio
async def test_obs_off_direct_fire_retry_redispatches(hass):
    coord, bat, v, emitted, retries = _wv(hass, obs=False)
    await v._pending_fire_retry(bat, SURFACE, attempt_index_note="attempt_1")
    assert retries == [SURFACE]


@pytest.mark.asyncio
async def test_coord_without_observation_attr_keeps_today(hass):
    """Test doubles lacking `_observation_mode` keep today's behaviour."""
    coord, bat, v, emitted, retries = _wv(hass, obs=False)
    del coord._observation_mode
    await v._pending_fire_retry(bat, SURFACE, attempt_index_note="attempt_1")
    assert retries == [SURFACE]

"""EC-RESERVE-WRITE-GOVERNOR-1 — INV-G2 truthful `reserve_write` rows.

Every reserve-entity `number.set_value` URA dispatches produces exactly one
`ura_activity_log` row (`action="reserve_write"`) whose `value` is the
DISPATCHED value, subject only to the change gate. No row for a value that
was not dispatched. Drives the REAL dispatch paths through the shared
harness (`_reserve_governor_harness.make_shell`): timer (C1), evaluate (C2),
force_redispatch (C3).

Each test is the RED-on-neuter anchor for one row of the plan's mutation
table (see the docstrings).
"""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    RESERVE_WRITE_EID,
    _CDT,
    _settle,
    _st,
    clock,
    make_shell,
    seed_inclement,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy as energy_mod,
    hvac_strategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
)


def rows(c) -> list[dict]:
    out = []
    for r in c.db.rows:
        if r["action"] != "reserve_write":
            continue
        d = json.loads(r["details_json"])
        d["_entity_id"] = r["entity_id"]
        d["_coordinator"] = r["coordinator"]
        d["_importance"] = r["importance"]
        d["_timestamp"] = r["timestamp"]
        out.append(d)
    return out


async def timer_tick(c, s, period, now, *, decision=None):
    d = decision if decision is not None else s.determine_mode(period, "summer", now=now)
    await c._execute_breaker_safe_dispatch(d, period)
    await _settle()
    return d


# ---------------------------------------------------------------------------
# C1 — timer path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reserve_row_on_timer_dispatch(clock):
    """Mutation: delete the C1 call → RED."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    d = await timer_tick(c, s, "mid_peak", now)
    assert [x[:2] for x in c.calls] == [["number", "set_value"]]
    rs = rows(c)
    assert len(rs) == 1, rs
    r = rs[0]
    assert r["status"] == "applied"
    assert r["path"] == "timer"
    assert r["value"] == 45
    assert r["desire"] == 45
    assert r["pre_state"] == 0.0
    # `_resolve_hold_owner` vocabulary verbatim: mid_peak summer phase.
    assert r["hold_owner"] == "arbitrage_discharge"
    assert r["evse_hold_soc"] is None
    assert r["inclement_floor"] is None and r["floor_ok"] is None
    assert r["reason"] == d["reason"]
    assert r["_entity_id"] == RESERVE_WRITE_EID
    assert r["_coordinator"] == "energy"
    assert r["_importance"] == "notable"
    assert r["_timestamp"] == clock.t.isoformat()
    # The dispatch itself is untouched (A/B is the full proof).
    assert s._last_reserve_level == 45


@pytest.mark.asyncio
async def test_reserve_row_deadband_no_row(clock):
    """INV-G2 falsifier 2 / Repro-1: current 20, desire 21 → no action, no row."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="21", reserve_state="20")
    d = await timer_tick(c, s, "mid_peak", now)
    assert s._last_reserve_level_desired == 21
    assert not [a for a in d["actions"] if a["service"] == "number.set_value"]
    assert c.calls == []
    assert rows(c) == []


@pytest.mark.asyncio
async def test_reserve_row_records_overlay_value_not_desire(clock):
    """Repro-2 (edge 2): EVSE overlay sends 60 while the desire is 20.
    Mutation: C1 passes the pre-overlay desire instead of data["value"] → RED."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="20", reserve_state="0")
    d = s.determine_mode("mid_peak", "summer", now=now)
    c._evse_hold_soc = 60
    c._evse_battery_hold_active = True
    d = c._apply_evse_battery_hold(d)
    await timer_tick(c, s, "mid_peak", now, decision=d)
    assert c.calls[0][2]["value"] == 60
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["value"] == 60
    assert rs[0]["desire"] == 20
    assert rs[0]["hold_owner"] == "evse_battery_hold"
    assert rs[0]["evse_hold_soc"] == 60


@pytest.mark.asyncio
async def test_reserve_row_dp_fold_owner_and_value(clock):
    """Edge 3: DP fold raises the overlay → hold_owner dp_transition, folded max."""
    from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (
        DPState,
    )
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="20", reserve_state="0")
    d = s.determine_mode("mid_peak", "summer", now=now)
    c._evse_hold_soc = 60
    c._evse_battery_hold_active = True
    c._dp_decision_soc = 70
    c._dp_carrier = SimpleNamespace(state=DPState.TRANSITIONED)
    d = c._apply_evse_battery_hold(d)
    await timer_tick(c, s, "mid_peak", now, decision=d)
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["value"] == 70
    assert rs[0]["desire"] == 20
    assert rs[0]["hold_owner"] == "dp_transition"


@pytest.mark.asyncio
async def test_reserve_row_blind_deescalation(clock):
    """Edge 4: blind row via C1, reason prefix "Blind de-escalation",
    value=reserve_soc, desire = previous tick's (None here: blind bypasses
    `_result`), floor fields per the cached decision (none)."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="unavailable", cfg_state="on", reserve_state="0")
    s._soc_lkg = None
    s._soc_lkg_at = None
    d = await timer_tick(c, s, "peak", now)
    assert d["reason"].startswith("Blind de-escalation")
    # Two dispatches (CFG off + reserve), ONE reserve row.
    assert [x[:2] for x in c.calls] == [["switch", "turn_off"], ["number", "set_value"]]
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["value"] == 10 == s.reserve_soc
    assert rs[0]["desire"] is None
    assert rs[0]["reason"].startswith("Blind de-escalation")
    assert rs[0]["inclement_floor"] is None


@pytest.mark.asyncio
async def test_reserve_row_blind_under_partial_hold_floor_ok_false(clock):
    """Edge 4 (continued): blind is the KNOWN unfloored site — under a
    cached partial_hold with floor 50 the row shows floor_ok=False. That is
    correct and expected (EC-INCLEMENT-HARDENING-1 D-blind fixes the write;
    the row makes it visible). floor_ok is observed, never enforced."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="unavailable", cfg_state="on", reserve_state="0")
    s._soc_lkg = None
    s._soc_lkg_at = None
    # Cached (fresh) partial_hold — the blind branch runs before the ladder
    # and does not read it, but the row does.
    seed_inclement(s, now, "partial_hold", 50)
    d = await timer_tick(c, s, "peak", now)
    assert d["reason"].startswith("Blind de-escalation")
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["value"] == 10
    assert rs[0]["inclement_floor"] == 50
    assert rs[0]["floor_ok"] is False


@pytest.mark.asyncio
async def test_reserve_row_failed_dispatch(clock):
    """A raised service call → status failed (and the row is ungated)."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")

    async def _boom(domain, svc, data, blocking=False, **kw):
        raise RuntimeError("cloud down")
    c.hass.services.async_call = _boom
    await timer_tick(c, s, "mid_peak", now)
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["status"] == "failed"
    assert rs[0]["path"] == "timer"
    assert rs[0]["value"] == 45


@pytest.mark.asyncio
async def test_reserve_row_requires_configured_reserve_entity(clock):
    """G-6: with NO reserve role configured, a `number.set_value` to some
    other number passes the tap's filter (pre-existing hole, untouched) but
    writes NO row. Mutation: C1 drops the truthy-`reserve_eid` guard → RED."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    # Unconfigure the reserve role on BOTH legs (second-install shape).
    s._entities.pop("reserve_soc_number", None)
    s._entities.pop("cloud_reserve_oracle", None)
    assert s._get_entity("reserve_soc_number", None, role="write") is None
    decision = {
        "reason": "unrelated number", "charge_from_grid": False,
        "arbitrage_phase": "n/a",
        "actions": [{
            "service": "number.set_value", "target": "number.some_other_number",
            "data": {"value": 33},
        }],
    }
    await timer_tick(c, s, "mid_peak", now, decision=decision)
    assert [x[:2] for x in c.calls] == [["number", "set_value"]]  # it WAS dispatched
    assert rows(c) == []


@pytest.mark.asyncio
async def test_reserve_row_other_number_target_with_reserve_configured_no_row(clock):
    """Build-risk 2: a non-reserve `number.set_value` in the battery decision
    (pool etc.) never gets a reserve_write row."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    decision = {
        "reason": "pool speed", "charge_from_grid": False, "arbitrage_phase": "n/a",
        "actions": [{
            "service": "number.set_value", "target": "number.pool_pump_speed",
            "data": {"value": 2},
        }],
    }
    await timer_tick(c, s, "mid_peak", now, decision=decision)
    assert len(c.calls) == 1
    assert rows(c) == []


# ---------------------------------------------------------------------------
# Change gate (R3-01 / G-5)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reserve_row_gate_suppresses_identical_dispatch(clock):
    """Edge 9: the overlay re-sends 60 every charging tick. Tick 1 (hardware
    "0") → row. Hardware then reads "60.0" (HA string state) and tick 2
    re-sends 60 with the same key → NO second row.
    Mutations: remove the gate → RED; compare the raw "60.0" string to int
    (drop `_get_state_float`/round) → RED."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="20", reserve_state="0")
    c._evse_hold_soc = 60
    c._evse_battery_hold_active = True

    d1 = c._apply_evse_battery_hold(s.determine_mode("mid_peak", "summer", now=now))
    await timer_tick(c, s, "mid_peak", now, decision=d1)
    assert len(rows(c)) == 1 and rows(c)[0]["pre_state"] == 0.0

    # Hardware now holds 60 (cloud reflected the write); strategy desire is
    # still 20 → `_result` deadband appends nothing; the overlay appends 60.
    _st(c.hass, RESERVE_WRITE_EID, "60.0", unit="%", lu=clock.t)
    clock.t = clock.t + timedelta(minutes=5)
    now2 = clock.t.astimezone(_CDT)
    d2 = c._apply_evse_battery_hold(s.determine_mode("mid_peak", "summer", now=now2))
    assert [a["data"]["value"] for a in d2["actions"] if a["service"] == "number.set_value"] == [60]
    await timer_tick(c, s, "mid_peak", now2, decision=d2)
    assert len(c.calls) == 2  # the re-send DID happen
    assert len(rows(c)) == 1  # ...and was gated (SKIPPED_ALREADY_CORRECT)
    assert hvac_strategy.WriteStatus.SKIPPED_ALREADY_CORRECT.value not in {
        r["status"] for r in rows(c)
    }


@pytest.mark.asyncio
async def test_reserve_row_records_drift_correction(clock):
    """R3-01 / edge 9b: row at 30; cloud reverts to 20; URA re-sends 30 with
    the same owner → pre_state 20 != 30 → a row IS written.
    Mutation: drop pre_state from the gate rule (gate on key only) → RED."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="30", reserve_state="0")
    await timer_tick(c, s, "mid_peak", now)
    assert [r["value"] for r in rows(c)] == [30]

    _st(c.hass, RESERVE_WRITE_EID, "20.0", unit="%", lu=clock.t)  # cloud reverted
    clock.t = clock.t + timedelta(minutes=5)
    now2 = clock.t.astimezone(_CDT)
    await timer_tick(c, s, "mid_peak", now2)
    assert [x[2]["value"] for x in c.calls] == [30, 30]
    rs = rows(c)
    assert [r["value"] for r in rs] == [30, 30]
    assert rs[1]["pre_state"] == 20.0
    assert rs[0]["hold_owner"] == rs[1]["hold_owner"]


@pytest.mark.asyncio
async def test_reserve_row_cloud_lag_resend_is_two_rows(clock):
    """Edge 9d: same value re-sent while the cloud still reads the OLD value
    → two rows (truthful; the live AC tolerates it)."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="30", reserve_state="0")
    await timer_tick(c, s, "mid_peak", now)
    clock.t = clock.t + timedelta(minutes=1)
    await timer_tick(c, s, "mid_peak", clock.t.astimezone(_CDT))  # hw still "0"
    assert [r["pre_state"] for r in rows(c)] == [0.0, 0.0]


@pytest.mark.asyncio
async def test_reserve_row_pre_state_none_writes_row(clock):
    """Hardware `unavailable` → pre_state None → never gated."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="30", reserve_state="unavailable")
    await timer_tick(c, s, "mid_peak", now)
    clock.t = clock.t + timedelta(minutes=5)
    await timer_tick(c, s, "mid_peak", clock.t.astimezone(_CDT))
    rs = rows(c)
    assert len(rs) == 2
    assert all(r["pre_state"] is None for r in rs)


@pytest.mark.asyncio
async def test_reserve_row_failed_row_updates_memo(clock):
    """R3-06: every WRITTEN row updates the memo, failures included — a
    later success at the same key with hardware already correct is gated."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    good = c.hass.services.async_call

    async def _boom(domain, svc, data, blocking=False, **kw):
        raise RuntimeError("cloud down")
    c.hass.services.async_call = _boom
    await timer_tick(c, s, "mid_peak", now)
    assert [r["status"] for r in rows(c)] == ["failed"]
    assert c._last_reserve_row_key == ("timer", 45, "arbitrage_discharge")

    c.hass.services.async_call = good
    _st(c.hass, RESERVE_WRITE_EID, "45", unit="%", lu=clock.t)
    # Force a re-send despite the deadband (same key, hardware correct).
    decision = {
        "reason": "x", "charge_from_grid": False, "arbitrage_phase": "n/a",
        "actions": [{"service": "number.set_value", "target": RESERVE_WRITE_EID,
                     "data": {"value": 45}}],
    }
    await timer_tick(c, s, "mid_peak", now, decision=decision)
    # The good stub records; the raising stub did not → exactly one record,
    # proving the SECOND dispatch happened.
    assert [x[2]["value"] for x in c.calls] == [45]
    assert [r["status"] for r in rows(c)] == ["failed"]  # success gated


@pytest.mark.asyncio
async def test_reserve_row_first_write_after_boot_always_logged(clock):
    """Memo is RAM-only: a fresh coordinator with hardware ALREADY at the
    value still writes the first row."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="45")
    decision = {
        "reason": "x", "charge_from_grid": False, "arbitrage_phase": "n/a",
        "actions": [{"service": "number.set_value", "target": RESERVE_WRITE_EID,
                     "data": {"value": 45}}],
    }
    await timer_tick(c, s, "mid_peak", now, decision=decision)
    assert [r["pre_state"] for r in rows(c)] == [45.0]


# ---------------------------------------------------------------------------
# inclement_floor / floor_ok + ordering
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reserve_row_inclement_floor_expression(clock):
    """Edge 6 / R1-02: reserve_soc=20, partial_hold reserve_floor=10 →
    inclement_floor = max(20, 10) = 20.
    Mutation: use `dec.reserve_floor` without the max(reserve_soc, …) → RED."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    s.reserve_soc = 20
    seed_inclement(s, now, "partial_hold", 10)
    await timer_tick(c, s, "mid_peak", now)
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["value"] == 45
    assert rs[0]["inclement_floor"] == 20
    assert rs[0]["floor_ok"] is True
    assert rs[0]["hold_owner"] == "inclement"


@pytest.mark.asyncio
async def test_reserve_row_partial_hold_floor_binds(clock):
    """Edge 5 (config extreme, floor > target): reserve_floor=80,
    peak_buffer_target=40, soc 45 → the wraps raise the write to 80; row
    value=80, inclement_floor=80, floor_ok=True."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0", peak_buffer_target=40)
    seed_inclement(s, now, "partial_hold", 80)
    await timer_tick(c, s, "mid_peak", now)
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["value"] == 80
    assert rs[0]["inclement_floor"] == 80
    assert rs[0]["floor_ok"] is True


@pytest.mark.asyncio
async def test_reserve_row_full_hold_has_no_inclement_floor_field(clock):
    """full_hold is not a partial_hold floor: inclement_floor None, owner inclement."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    seed_inclement(s, now, "full_hold", 70)
    await timer_tick(c, s, "mid_peak", now)
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["value"] == 70
    assert rs[0]["inclement_floor"] is None and rs[0]["floor_ok"] is None
    assert rs[0]["hold_owner"] == "inclement"


@pytest.mark.asyncio
async def test_reserve_row_reads_current_tick_decision(clock):
    """§Ordering (R2-10): tick 1 partial_hold floor 30 dispatches 30 and the
    row has inclement_floor=30; tick 2 at allow_discharge (desire 20,
    current 30) dispatches 20 and the row has inclement_floor=None.
    Mutation: `_record_reserve_dispatch` reads a decision frozen on first
    call → tick 2 shows 30 → RED."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="20", reserve_state="0")
    seed_inclement(s, now, "partial_hold", 30)
    await timer_tick(c, s, "mid_peak", now)
    rs = rows(c)
    assert [r["value"] for r in rs] == [30]
    assert rs[0]["inclement_floor"] == 30 and rs[0]["floor_ok"] is True

    # Tick 2: alert cleared → allow_discharge is re-derived for the new `now`.
    _st(c.hass, RESERVE_WRITE_EID, "30", unit="%", lu=clock.t)
    clock.t = clock.t + timedelta(minutes=5)
    now2 = clock.t.astimezone(_CDT)
    s._last_inclement_decision = None
    s._last_inclement_decision_at = None
    d2 = await timer_tick(c, s, "mid_peak", now2)
    assert s._last_inclement_decision.hold_depth == "allow_discharge"
    rs = rows(c)
    assert [r["value"] for r in rs] == [30, 20], d2["reason"]
    assert rs[1]["inclement_floor"] is None and rs[1]["floor_ok"] is None


# ---------------------------------------------------------------------------
# C2 — evaluate (CoordinatorManager) path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reserve_row_on_evaluate_path(clock):
    """Mutation: delete the C2 call → RED. The CM path bypasses the tap, so
    the row is DEFERRED (outcome unseen) with path=evaluate."""
    c, s = make_shell(clock, soc="45", reserve_state="0")
    c._tou = SimpleNamespace(
        get_current_period=lambda *a: "mid_peak", get_season=lambda *a: "summer",
    )
    acts = await c._evaluate_battery()
    await _settle()
    assert [a.service for a in acts] == ["number.set_value"]
    assert c.calls == []  # the CM executes later, not here
    rs = rows(c)
    assert len(rs) == 1
    r = rs[0]
    assert r["status"] == "deferred"
    assert r["path"] == "evaluate"
    assert r["value"] == 45
    assert r["desire"] == 45
    assert r["pre_state"] == 0.0
    assert r["reason"] == c._last_battery_decision["reason"]
    assert r["_entity_id"] == RESERVE_WRITE_EID


@pytest.mark.asyncio
async def test_reserve_row_evaluate_path_gated_like_timer(clock):
    """The evaluate row obeys the same gate (own key: path=evaluate)."""
    c, s = make_shell(clock, soc="45", reserve_state="0")
    c._tou = SimpleNamespace(
        get_current_period=lambda *a: "mid_peak", get_season=lambda *a: "summer",
    )
    await c._evaluate_battery()
    await _settle()
    _st(c.hass, RESERVE_WRITE_EID, "45.0", unit="%", lu=clock.t)
    # Force a re-emit despite the deadband by stubbing determine_mode.
    s.determine_mode = lambda *a, **k: {
        "reason": "x", "charge_from_grid": False, "soc": 45.0,
        "actions": [{"service": "number.set_value", "target": RESERVE_WRITE_EID,
                     "data": {"value": 45}}],
    }
    await c._evaluate_battery()
    await _settle()
    assert len(rows(c)) == 1


@pytest.mark.asyncio
async def test_reserve_row_evaluate_requires_configured_reserve_entity(clock):
    c, s = make_shell(clock, soc="45", reserve_state="0")
    s._entities.pop("reserve_soc_number", None)
    s._entities.pop("cloud_reserve_oracle", None)
    c._tou = SimpleNamespace(
        get_current_period=lambda *a: "mid_peak", get_season=lambda *a: "summer",
    )
    s.determine_mode = lambda *a, **k: {
        "reason": "x", "charge_from_grid": False, "soc": 45.0,
        "actions": [{"service": "number.set_value", "target": "number.other",
                     "data": {"value": 45}}],
    }
    acts = await c._evaluate_battery()
    await _settle()
    assert len(acts) == 1
    assert rows(c) == []


# ---------------------------------------------------------------------------
# C3 — force_redispatch
# ---------------------------------------------------------------------------
def _redispatch_ready(c, s, clock, desire=42):
    s._desired_stamped_at = clock.t
    s._last_reserve_level_desired = desire
    s._last_reserve_level = 80
    s._last_reserve_level_at = clock.t - timedelta(hours=1)


@pytest.mark.asyncio
async def test_reserve_row_on_force_redispatch(clock):
    """Mutation: delete the C3 success call → RED."""
    c, s = make_shell(clock, soc="45", reserve_state="0")
    _redispatch_ready(c, s, clock)
    await s.force_redispatch("reserve_soc")
    await _settle()
    assert [x[2]["value"] for x in c.calls] == [42]
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["status"] == "applied"
    assert rs[0]["path"] == "redispatch"
    assert rs[0]["value"] == 42
    assert rs[0]["desire"] == 42
    assert rs[0]["_entity_id"] == RESERVE_WRITE_EID
    assert s._last_reserve_level == 42  # ledger stamped (step 5) before the row


@pytest.mark.asyncio
async def test_reserve_row_on_force_redispatch_failure(clock):
    """A raised redispatch → `record_dispatch_failed` runs AND a failed row
    is written after it (never inside the service-call except)."""
    c, s = make_shell(clock, soc="45", reserve_state="0")
    _redispatch_ready(c, s, clock)
    recorded: list = []

    async def _rec(*a, **k):
        recorded.append(a)
    c._write_verifier.record_dispatch_failed = _rec

    async def _boom(domain, svc, data, blocking=False, **kw):
        raise RuntimeError("cloud down")
    c.hass.services.async_call = _boom
    await s.force_redispatch("reserve_soc")
    await _settle()
    assert len(recorded) == 1
    rs = rows(c)
    assert len(rs) == 1
    assert rs[0]["status"] == "failed" and rs[0]["path"] == "redispatch"
    assert rs[0]["value"] == 42
    assert s._last_reserve_level == 80  # not stamped on failure (unchanged)


@pytest.mark.asyncio
async def test_reserve_row_redispatch_bypasses_gate(clock):
    """Edge 10: redispatch of an unchanged desire, hardware already at the
    value → ALWAYS a row. Mutation: apply the gate to redispatch → RED."""
    c, s = make_shell(clock, soc="45", reserve_state="42")
    _redispatch_ready(c, s, clock)
    await s.force_redispatch("reserve_soc")
    await _settle()
    await s.force_redispatch("reserve_soc")
    await _settle()
    assert len(c.calls) == 2
    rs = rows(c)
    assert [r["path"] for r in rs] == ["redispatch", "redispatch"]
    assert [r["value"] for r in rs] == [42, 42]


@pytest.mark.asyncio
async def test_force_redispatch_row_call_cannot_fake_failure(clock):
    """G-1: the row call lives OUTSIDE the service-call try. (a) No `_coord`
    at all (standard test wiring) and (b) a coord whose
    `_record_reserve_dispatch` RAISES — in both cases the ledger is stamped
    and `record_dispatch_failed` is NOT called.
    Mutation: move C3 back inside the try with a direct attribute call → RED."""
    from homeassistant.util import dt as _dt

    for variant in ("no_coord", "raising_coord"):
        c, s = make_shell(clock, soc="45", reserve_state="0")
        _redispatch_ready(c, s, clock)
        failed: list = []

        async def _rec(*a, **k):
            failed.append(a)
        c._write_verifier.record_dispatch_failed = _rec
        if variant == "no_coord":
            del s._coord
            assert not hasattr(s, "_coord")
        else:
            def _raise(**kw):
                raise RuntimeError("row writer exploded")
            s._coord = SimpleNamespace(_record_reserve_dispatch=_raise)
        await s.force_redispatch("reserve_soc")
        await _settle()
        assert [x[2]["value"] for x in c.calls] == [42], variant
        assert failed == [], variant
        assert s._last_reserve_level == 42, variant
        assert s._last_reserve_level_at == _dt.utcnow(), variant


# ---------------------------------------------------------------------------
# Typed outcome + constants
# ---------------------------------------------------------------------------
def test_reserve_row_status_uses_hvac_writestatus():
    """Mutation: status re-typed as a local string/enum instead of the
    imported `hvac_strategy.WriteStatus` → RED (identity)."""
    assert energy_mod.WriteStatus is hvac_strategy.WriteStatus
    assert {m.value for m in energy_mod.WriteStatus} == {
        "applied", "skipped_already_correct", "deferred", "failed",
    }


@pytest.mark.asyncio
async def test_reserve_row_status_values_come_from_the_enum(clock):
    """Row `status` strings are exactly the enum members' `.value`s."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    await timer_tick(c, s, "mid_peak", now)
    assert rows(c)[0]["status"] == hvac_strategy.WriteStatus.APPLIED.value == "applied"


def test_reserve_write_importance_parity_with_climate_row():
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const, hvac_const,
    )
    assert energy_const.RESERVE_WRITE_LOG_IMPORTANCE == hvac_const.CLIMATE_WRITE_LOG_IMPORTANCE


@pytest.mark.asyncio
async def test_reserve_row_db_missing_dispatch_proceeds(clock):
    """Edge 8: no database → row skipped with a debug log, dispatch proceeds,
    ledger stamped, nothing raised."""
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    c.hass.data["universal_room_automation"] = {}
    await timer_tick(c, s, "mid_peak", now)
    assert [x[:2] for x in c.calls] == [["number", "set_value"]]
    assert s._last_reserve_level == 45
    assert c.db.rows == []
    # Memo NOT updated (no row written). The shell bypasses __init__, so
    # read the way production does (getattr default None).
    assert getattr(c, "_last_reserve_row_key", None) is None


@pytest.mark.asyncio
async def test_reserve_row_never_awaited_on_dispatch_path(clock):
    """Fire-and-forget: the row is scheduled through `hass.async_create_task`
    (never awaited inline), so a stalled DB cannot back-pressure dispatch."""
    import asyncio
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(clock, soc="45", reserve_state="0")
    scheduled: list = []
    c.hass.async_create_task = lambda coro: scheduled.append(coro)
    d = s.determine_mode("mid_peak", "summer", now=now)
    await c._execute_breaker_safe_dispatch(d, "mid_peak")
    assert len(scheduled) == 1 and asyncio.iscoroutine(scheduled[0])
    assert c.db.rows == []  # not run yet: nothing awaited it
    await scheduled[0]
    assert len(rows(c)) == 1

"""EC reserve oracle phase 2 — local witness primary, cloud corroborator.

Plan: docs/planning/PLANNING_ec_reserve_oracle_phase2.md (rev 2.2; D0 §13).
Tier 3. Drives the REAL `BatteryStrategy._reserve_action` /
`force_redispatch`, the REAL `EnergyCoordinator` dispatch chokepoint + tap +
`_record_reserve_dispatch`, and the REAL `WriteVerifier` through the shared
governor harness. Only the HA service bus, the entity registry, NM and the
DB are faked. Oracles are independently stated plan facts (acceptance
criteria / D0 numbers), never re-derived from the code under test; boundary
times are hardcoded literals, never the imported constants.

Falsifiable invariants (plan §2) — each has a test that would go RED:
  INV-R1 convergence while trusted   → test_inv_r1_* , episode tests
  INV-R2 no false "not applied"      → test_check_* / test_sweep_* / episode E
  INV-R3 witnesses only tighten      → test_inv_r3_* , kill-switch golden
  INV-R4 bounded writes              → test_pending_episode_bounded_writes
"""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    RESERVE_WRITE_EID,
    _CDT,
    _SOC,
    _settle,
    _st,
    clock,
    make_shell,
)
from ec_phalanx_entities import PHALANX_RESERVE_SOC_ENTITY

from custom_components.universal_room_automation.domain_coordinators import (
    energy_const as ec,
    energy_write_verify as ewv,
    hvac_strategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    _nudge_value,
)

SURFACE = "reserve_soc"
SERIAL = "482543015950"
LOCAL_EID = "sensor.envoy_482543015950_reserve_battery_level"
WS = hvac_strategy.WriteStatus


# ---------------------------------------------------------------------------
# Registry fake (mirrors HA's two lookups; same shape as
# test_ec_reserve_witness_resolution.py). Installed per test.
# ---------------------------------------------------------------------------
class _Entry:
    def __init__(self, entity_id, platform, unique_id, disabled_by=None):
        self.entity_id = entity_id
        self.domain = entity_id.split(".", 1)[0]
        self.platform = platform
        self.unique_id = unique_id
        self.disabled_by = disabled_by


class _Registry:
    def __init__(self):
        self._by_eid: dict = {}
        self._by_key: dict = {}

    def add(self, entity_id, platform, unique_id, disabled_by=None):
        e = _Entry(entity_id, platform, unique_id, disabled_by)
        self._by_eid[entity_id] = e
        self._by_key[(e.domain, platform, unique_id)] = entity_id

    def async_get(self, entity_id):
        return self._by_eid.get(entity_id)

    def async_get_entity_id(self, domain, platform, unique_id):
        return self._by_key.get((domain, platform, unique_id))


def _registry(with_sensor=True):
    r = _Registry()
    r.add(_SOC, "enphase_envoy", f"{SERIAL}_battery_level")
    if with_sensor:
        r.add(LOCAL_EID, "enphase_envoy", f"{SERIAL}_reserve_soc")
    return r


@pytest.fixture
def reg(monkeypatch):
    from homeassistant.helpers import entity_registry as er

    holder = {"r": _registry()}
    monkeypatch.setattr(er, "async_get", lambda hass: holder["r"], raising=False)
    return holder


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------
class _SvcErr(Exception):
    def __init__(self, key):
        super().__init__(key)
        self.translation_key = key


def shell(clock, *, soc=98, cloud=10, local=98, enpower=None):
    c, s = make_shell(clock, soc=str(soc), reserve_state=str(cloud))
    c.soc_value = soc
    c.local_value = local
    if enpower is not None:
        _st(c.hass, PHALANX_RESERVE_SOC_ENTITY, str(enpower), unit="%", lu=clock.t)
    refresh(c, clock)
    c.anomalies = []

    async def _save(ev):
        c.anomalies.append((ev.type, ev.payload))
    c.db.save_anomaly_event = _save
    return c, s


def refresh(c, clock):
    """Keep SOC + local fresh at the frozen clock (staleness tiers)."""
    _st(c.hass, _SOC, str(c.soc_value) if c.soc_value is not None
        else "unavailable", unit="%", lu=clock.t)
    _st(c.hass, LOCAL_EID, "unavailable" if c.local_value is None
        else str(c.local_value), unit="%", lu=clock.t)


def set_cloud(c, clock, v):
    _st(c.hass, RESERVE_WRITE_EID, str(v), unit="%", lu=clock.t)


def set_local(c, clock, v):
    c.local_value = v
    refresh(c, clock)


def decide(s, target):
    _, a = s._reserve_action(target)
    return a["data"]["value"] if a is not None else None


def set_values(c):
    return [x[2]["value"] for x in c.calls if x[:2] == ["number", "set_value"]]


async def tick(c, s, clock, target, *, at=None):
    """One real timer-path decision + dispatch of `target` at `at` (s from
    the shell's start). Returns the emitted value (or None)."""
    if at is not None:
        clock.t = c.t0 + timedelta(seconds=at)
    refresh(c, clock)
    _, a = s._reserve_action(target)
    d = {"actions": [a] if a else [], "reason": "t", "charge_from_grid": False}
    await c._execute_breaker_safe_dispatch(d, "mid_peak")
    await _settle()
    return a["data"]["value"] if a is not None else None


def rows(c):
    return [json.loads(r["details_json"]) for r in c.db.rows
            if r["action"] == "reserve_write"]


def anomalies(c, typ):
    return [p for t, p in c.anomalies if t == typ]


def raising_bus(c, key):
    async def _svc(domain, svc, data, blocking=False, **kw):
        c.calls.append([domain, svc, dict(data)])
        raise _SvcErr(key)
    c.hass.services = SimpleNamespace(async_call=_svc)


@pytest.fixture
def sh(clock, reg):
    def _make(**kw):
        c, s = shell(clock, **kw)
        c.t0 = clock.t
        return c, s
    return _make


# ===========================================================================
# D1.1 trust rule
# ===========================================================================
def test_trust_rule_reasons_pinned(sh, reg, clock):
    """Every untrusted reason is pinned to its exact string (C14, C6)."""
    c, s = sh(soc=50, local=40)
    wv = c._write_verifier
    assert wv.trusted_local_reserve(s, 40, 50) == (40.0, "local")
    assert wv.trusted_local_reserve(s, 10, None) == (None, "soc_unknown_high")
    assert wv.trusted_local_reserve(s, 40, None) == (40.0, "local")
    set_local(c, clock, None)
    assert wv.trusted_local_reserve(s, 40, 50) == (None, "unavailable")
    set_local(c, clock, "abc")
    assert wv.trusted_local_reserve(s, 40, 50) == (None, "unavailable")
    reg["r"] = _registry(with_sensor=False)
    assert wv.trusted_local_reserve(s, 40, 50) == (None, "fallback_only")


def test_trust_rule_kill_switch(sh, monkeypatch):
    c, s = sh(soc=50, local=40)
    monkeypatch.setattr(ec, "RESERVE_LOCAL_WITNESS_ENABLED", False)
    assert c._write_verifier.trusted_local_reserve(s, 40, 50) == (None, "disabled")


def test_low_soc_guard_boundaries_literal(sh):
    """Guard = soc <= target+5 AND target < local <= soc+20. Each conjunct
    tested on its own with literal edges (margin 5, span 20)."""
    c, s = sh()
    wv = c._write_verifier
    # soc - target: 5 → guard (untrusted); 6 → trusted.
    c.local_value = 16
    refresh(c, SimpleNamespace(t=c.t0))
    assert wv.trusted_local_reserve(s, 10, 15)[1] == "low_soc_guard"
    assert wv.trusted_local_reserve(s, 10, 16) == (16.0, "local")
    # local <= target → trusted (conjunct target < local).
    c.local_value = 10
    refresh(c, SimpleNamespace(t=c.t0))
    assert wv.trusted_local_reserve(s, 10, 8) == (10.0, "local")
    # local - soc: 20 → guard; 21 → trusted (stuck high, R2-M1).
    c.local_value = 31
    refresh(c, SimpleNamespace(t=c.t0))
    assert wv.trusted_local_reserve(s, 10, 11)[1] == "low_soc_guard"
    c.local_value = 32
    refresh(c, SimpleNamespace(t=c.t0))
    assert wv.trusted_local_reserve(s, 10, 11) == (32.0, "local")


# ===========================================================================
# D1.3 decision rules (acceptance criteria, plan §5 D1)
# ===========================================================================
def test_reserve_reference_local_primary_releases_stuck_hold(sh, monkeypatch):
    """Incident shape: cloud 10 (stale), local 98, target 10, SOC 98 → an
    action (D2 nudge 11, cloud == target). Pre-cycle: none."""
    c, s = sh(soc=98, cloud=10, local=98)
    assert decide(s, 10) == 11
    assert s._reserve_reference_source == "local"
    monkeypatch.setattr(ec, "RESERVE_LOCAL_WITNESS_ENABLED", False)
    assert decide(s, 10) is None


def test_reserve_reference_suppresses_stale_cloud_churn(sh, monkeypatch):
    """Episode B: cloud 98 (stale), local 10, target 10, last_ok 10 → none.
    Pre-cycle sends 10."""
    c, s = sh(soc=60, cloud=98, local=10)
    s._reserve_last_ok_value = 10
    assert decide(s, 10) is None
    assert s._reserve_reference_source == "local"
    monkeypatch.setattr(ec, "RESERVE_LOCAL_WITNESS_ENABLED", False)
    assert decide(s, 10) == 10


def test_reserve_reference_ledger_term_when_local_unavailable(sh, monkeypatch):
    """Local unavailable, cloud 10, last_ok 98, target 10, no attempt in
    gap → action, source ledger."""
    c, s = sh(soc=60, cloud=10, local=None)
    s._reserve_last_ok_value = 98
    assert decide(s, 10) is not None
    assert s._reserve_reference_source == "ledger"
    monkeypatch.setattr(ec, "RESERVE_LEDGER_SEND_ENABLED", False)
    assert decide(s, 10) is None


def test_reserve_reference_low_soc_ratchet_guard(sh):
    """C5: SOC 6, target 10, local 16, cloud 10 → no action, guarded."""
    c, s = sh(soc=6, cloud=10, local=16)
    assert decide(s, 10) is None
    assert s._reserve_reference_source == "cloud_low_soc_guard"


def test_reserve_reference_low_soc_guard_upper_bound_stuck_high(sh):
    """C5b (R2-M1): SOC 11, target 10, local 98, cloud 10, last_ok 10 →
    action (98 > 11 + 20 → trusted)."""
    c, s = sh(soc=11, cloud=10, local=98)
    s._reserve_last_ok_value = 10
    assert decide(s, 10) == 11
    assert s._reserve_reference_source == "local"


def test_reserve_reference_soc_unknown_high_local_untrusted(sh):
    """C6: SOC unknown, local 98 > target 10 → untrusted; cloud 10 → none."""
    c, s = sh(soc=50, cloud=10, local=98)
    c._write_verifier._read_soc_via_resolver = lambda b: None
    assert decide(s, 10) is None
    assert s._reserve_reference_source == "cloud"


def test_reserve_reference_untrusted_fallback_witness(sh, reg):
    """C14: only the Enpower-number fallback resolves (reads 98) → never
    trusted; cloud 10 = target → none (pre-cycle)."""
    reg["r"] = _registry(with_sensor=False)
    c, s = sh(soc=98, cloud=10, local=None, enpower=98)
    assert decide(s, 10) is None
    assert s._reserve_reference_source == "cloud"


def test_reserve_reference_no_verifier_untrusted(sh):
    c, s = sh(soc=98, cloud=10, local=98)
    s._write_verifier = None
    assert decide(s, 10) is None
    assert s._reserve_reference_source == "cloud"
    set_cloud(c, SimpleNamespace(t=c.t0), 50)
    assert decide(s, 10) == 10


def test_reserve_reference_ledger_overrides_trusted_within_deadband(sh):
    """R1-M1: trusted local 10 = target, last_ok 98 → action (rule L)."""
    c, s = sh(soc=60, cloud=50, local=10)
    s._reserve_last_ok_value = 98
    assert decide(s, 10) == 10
    assert s._reserve_reference_source == "ledger"


def test_rule_l_skips_when_landed_is_the_nudge(sh):
    """Rule L conjunct `last_ok != nudge(target)`: a landed nudge 11 for
    target 10 never re-triggers rule L (local 10 within deadband)."""
    c, s = sh(soc=60, cloud=50, local=10)
    s._reserve_last_ok_value = 11
    assert decide(s, 10) is None
    s._reserve_last_ok_value = 12   # |12 - 10| = 2 and != 11 → rule L
    assert decide(s, 10) == 10


@pytest.mark.asyncio
async def test_reserve_reference_no_resend_inside_spacing(sh, clock):
    """R1-H2 / C17: target 10 sent at T (local stays 98) → T+300 in_flight;
    T+899 in_flight; T+900 → nudge 11 (trigger b: landed 10)."""
    c, s = sh(soc=98, cloud=50, local=98)
    assert await tick(c, s, clock, 10, at=0) == 10
    assert await tick(c, s, clock, 10, at=300) is None
    assert s._reserve_reference_source == "in_flight"
    assert await tick(c, s, clock, 10, at=899) is None
    assert await tick(c, s, clock, 10, at=900) == 11
    assert set_values(c) == [10, 11]


@pytest.mark.asyncio
async def test_normal_apply_converges_without_second_send(sh, clock):
    """C17: one send; local converges before T+900 → no second send."""
    c, s = sh(soc=98, cloud=50, local=98)
    assert await tick(c, s, clock, 10, at=0) == 10
    set_local(c, clock, 10)
    for at in (300, 600, 900, 1200):
        assert await tick(c, s, clock, 10, at=at) is None
    assert set_values(c) == [10]


@pytest.mark.asyncio
async def test_resend_gap_never_gates_cloud_term(sh, clock):
    """INV-R3: no trusted witness, cloud 50, target 10 → rule C re-sends every
    tick exactly as pre-cycle (never `in_flight`)."""
    c, s = sh(soc=98, cloud=50, local=None)
    assert await tick(c, s, clock, 10, at=0) == 10
    assert await tick(c, s, clock, 10, at=300) == 10
    assert s._reserve_reference_source == "cloud"
    assert set_values(c) == [10, 10]


@pytest.mark.asyncio
async def test_resend_gap_never_gates_raise(sh, clock):
    """C21 / RG-H1: inclement raises 10 → 50; local trusted 10, cloud 10,
    SOC 60. (a) the send of 50 raises at T → re-sent at T+300; (b) silently
    dropped (landed) → nudge 51 at T+300."""
    c, s = sh(soc=60, cloud=10, local=10)
    raising_bus(c, "timeout")
    assert await tick(c, s, clock, 50, at=0) == 50
    assert await tick(c, s, clock, 50, at=300) == 50
    assert s._reserve_reference_source == "local"
    c2, s2 = sh(soc=60, cloud=10, local=10)
    assert await tick(c2, s2, clock, 50, at=0) == 50
    assert await tick(c2, s2, clock, 50, at=300) == 51


@pytest.mark.asyncio
async def test_rule_l_raise_exemption_without_witness(sh, clock):
    """Rule-L raise with no witness (target > last_ok) is never gated;
    a rule-L lowering inside the gap is."""
    c, s = sh(soc=60, cloud=49, local=None)   # cloud within deadband, != 50
    s._reserve_last_ok_value = 40
    s._reserve_last_attempt_value = 50
    s._reserve_last_attempt_at = clock.t
    assert decide(s, 50) == 50              # raise (50 > 40): ungated
    s._reserve_last_ok_value = 60
    assert decide(s, 50) is None            # lowering, same value in gap
    assert s._reserve_reference_source == "in_flight"


@pytest.mark.asyncio
async def test_rule_g_disabled_at_zero(sh, clock, monkeypatch):
    monkeypatch.setattr(ec, "RESERVE_RESEND_MIN_GAP_S", 0)
    c, s = sh(soc=98, cloud=50, local=98)
    assert await tick(c, s, clock, 10, at=0) == 10
    assert await tick(c, s, clock, 10, at=300) == 11


@pytest.mark.asyncio
async def test_rule_g_does_not_gate_a_different_value(sh, clock):
    """A genuine desire change is never gated (C19)."""
    c, s = sh(soc=98, cloud=50, local=98)
    assert await tick(c, s, clock, 10, at=0) == 10
    assert await tick(c, s, clock, 20, at=300) == 20


@pytest.mark.asyncio
async def test_pending_episode_bounded_writes(sh, clock):
    """INV-R4 synthetic pending episode (D0-P2 cannot exercise it): local
    stuck 98 for 70 min, every send raises `control_change_pending` → <= 5
    dispatches, none of the same value closer than 900 s. Variant: every
    send silently dropped (lands, local never moves)."""
    for raising in (True, False):
        c, s = sh(soc=98, cloud=50, local=98)
        if raising:
            raising_bus(c, "control_change_pending")
        sent = []
        for at in range(0, 4201, 300):
            v = await tick(c, s, clock, 10, at=at)
            if v is not None:
                sent.append((at, v))
        assert len(sent) <= 5, sent
        for i, (t1, v1) in enumerate(sent):
            for t2, v2 in sent[i + 1:]:
                assert not (v1 == v2 and t2 - t1 < 900), sent
        assert [t for t, _ in sent] == [0, 900, 1800, 2700, 3600], sent


# ===========================================================================
# D1.4 attain base = intent
# ===========================================================================
def _attain(clock, reg_holder, *, hw, local, desire, last_ok, floor=50,
            ledger=40, soc="45"):
    from test_ec_stage_a_floor_and_blind import (  # noqa: PLC0415
        OCT_03, _hold_current_shell, tick as stage_a_tick, writes,
    )
    c, s = _hold_current_shell(clock, hw=hw)
    s._last_reserve_level = ledger
    s._last_reserve_level_desired = desire
    s._reserve_last_ok_value = last_ok
    clock.t = OCT_03
    _st(c.hass, LOCAL_EID, str(local), unit="%", lu=OCT_03)
    d = stage_a_tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", floor))
    assert "post-reboot HOLD CURRENT" in d["reason"]
    return writes(d)


def test_attain_floor_bypass_does_not_lower_inflight_with_stale_cloud(
    clock, reg, monkeypatch,
):
    """Desire 80 landed, cloud stale 10, local 80, floor 50 → no lowering
    write. Pre-cycle (kill switch) sends 50."""
    assert _attain(clock, reg, hw="10", local=80, desire=80, last_ok=80) == []
    monkeypatch.setattr(ec, "RESERVE_ATTAIN_BASE_INTENT_ENABLED", False)
    assert _attain(clock, reg, hw="10", local=80, desire=80, last_ok=80) == [50]


def test_attain_bypass_after_hold_release_lowers_to_floor(clock, reg):
    """R2-H3: hold just released: desire 10, ledger 98, local 98, cloud 10,
    floor 50 → lowers to 50 (the rev-1 `_hw` swap would send nothing)."""
    assert _attain(clock, reg, hw="10", local=98, desire=10, last_ok=None,
                   ledger=98) == [50]


def test_attain_base_does_not_reassert_unlanded_prior_desire(clock, reg):
    """RG-M2: desire 80 never landed, local 10, floor 50 → level 50."""
    assert _attain(clock, reg, hw="10", local=10, desire=80, last_ok=10) == [50]


def test_attain_base_keeps_landed_prior_desire(clock, reg):
    assert _attain(clock, reg, hw="10", local=80, desire=80, last_ok=80) == []


def test_attain_floor_drop_keeps_level(clock, reg):
    """Floor 80 → 20 with level 80 landed keeps 80 (no write)."""
    assert _attain(clock, reg, hw="80", local=80, desire=80, last_ok=80,
                   floor=20) == []


def test_attain_no_desire_keeps_hardware_first(clock, reg):
    """Post-reboot (desire None): hardware 80 outranks the KV ledger 40 →
    never lowered (pre-existing raise-only invariant kept)."""
    assert _attain(clock, reg, hw="80", local=80, desire=None, last_ok=None,
                   ledger=40) == []


# ===========================================================================
# EVSE hold, CM path, stamps
# ===========================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("cloud", [98, 10])
async def test_hold_active_local_primary_dispatches_same_value(
    sh, clock, monkeypatch, cloud,
):
    """C16 / R1-H3: EVSE hold 98, strategy target 10, local 98: the
    dispatched (service, value) list equals pre-cycle (kill switches off)."""
    out = []
    for on in (False, True):
        for name in ("RESERVE_LOCAL_WITNESS_ENABLED",
                     "RESERVE_SAME_VALUE_NUDGE_ENABLED",
                     "RESERVE_LEDGER_SEND_ENABLED"):
            monkeypatch.setattr(ec, name, on)
        c, s = sh(soc=98, cloud=cloud, local=98)
        _, a = s._reserve_action(10)
        d = {"actions": [a] if a else [], "reason": "t",
             "charge_from_grid": False, "soc": 98}
        c._evse_hold_soc = 98
        c._evse_battery_hold_active = True
        d = c._apply_evse_battery_hold(d)
        await c._execute_breaker_safe_dispatch(d, "mid_peak")
        await _settle()
        out.append([x[:2] + [x[2]["value"]] for x in c.calls
                    if x[:2] == ["number", "set_value"]])
    assert out[0] == out[1] == [["number", "set_value", 98]]


def test_hold_release_with_inclement_floor_local_primary(sh):
    """C8: on release target = max(strategy 10, floor 50) = 50; D1 sends 50
    against local 98 (cloud 98: no nudge)."""
    c, s = sh(soc=98, cloud=98, local=98)
    s._tick_reserve_floor = 50
    assert decide(s, 10) == 50


@pytest.mark.asyncio
async def test_cm_path_emits_nudge_and_stamps_attempt_only(sh, clock):
    """R1-M4: `_evaluate_battery` → `_reserve_action` → nudge; the DEFERRED
    row stamps the attempt stamp but not the landed stamp. RG-M3: a
    change-gated CM row (SKIPPED_ALREADY_CORRECT) still stamps attempt."""
    c, s = sh(soc=45, cloud=45, local=0)
    c._tou = SimpleNamespace(
        get_current_period=lambda *a: "mid_peak", get_season=lambda *a: "summer",
    )
    acts = await c._evaluate_battery()
    await _settle()
    assert [a.service for a in acts] == ["number.set_value"]
    assert s._last_reserve_level_desired == 45
    assert rows(c)[-1]["value"] == 46 and rows(c)[-1]["status"] == "deferred"
    assert s._reserve_last_attempt_value == 46
    assert s._reserve_last_attempt_at == clock.t
    assert s._reserve_last_ok_value is None
    # Change-gated CM row: memo == key and pre_state == value.
    n_rows = len(rows(c))
    clock.t = clock.t + timedelta(seconds=60)
    owner = c._write_verifier._resolve_hold_owner(s)
    c._last_reserve_row_key = ("evaluate", 45, owner)
    s.determine_mode = lambda *a, **k: {
        "reason": "x", "charge_from_grid": False, "soc": 45.0,
        "actions": [{"service": "number.set_value", "target": RESERVE_WRITE_EID,
                     "data": {"value": 45}}],
    }
    await c._evaluate_battery()
    await _settle()
    assert len(rows(c)) == n_rows            # gated: no row
    assert s._reserve_last_attempt_value == 45
    assert s._reserve_last_attempt_at == clock.t
    assert s._reserve_last_ok_value is None


@pytest.mark.asyncio
async def test_attempt_stamp_written_without_database_and_when_row_gated(sh, clock):
    """RG-M1: stamps sit before the change gate and the no-DB return."""
    c, s = sh()
    c.hass.data["universal_room_automation"] = {}
    c._record_reserve_dispatch(status=WS.APPLIED, path="timer",
                               target=RESERVE_WRITE_EID, value=30, reason="x")
    assert (s._reserve_last_attempt_value, s._reserve_last_ok_value) == (30, 30)
    assert s._reserve_last_attempt_at == clock.t
    c2, s2 = sh()
    owner = c2._write_verifier._resolve_hold_owner(s2)
    c2._last_reserve_row_key = ("timer", 40, owner)
    c2._record_reserve_dispatch(status=WS.APPLIED, path="timer",
                                target=RESERVE_WRITE_EID, value=40, reason="x",
                                pre_state=40.0)
    await _settle()
    assert rows(c2) == []
    assert (s2._reserve_last_attempt_value, s2._reserve_last_ok_value) == (40, 40)
    # FAILED / DEFERRED: attempt only.
    for st in (WS.FAILED, WS.DEFERRED):
        c3, s3 = sh()
        c3._record_reserve_dispatch(status=st, path="timer",
                                    target=RESERVE_WRITE_EID, value=50, reason="x")
        assert s3._reserve_last_attempt_value == 50
        assert s3._reserve_last_ok_value is None


@pytest.mark.asyncio
async def test_restart_new_stamps_none_bounded(sh, clock):
    """C13: fresh strategy → stamps None → first tick ungated (one send),
    the next tick inside the gap is gated."""
    c, s = sh(soc=98, cloud=50, local=98)
    assert s._reserve_last_attempt_at is None and s._reserve_last_ok_value is None
    assert await tick(c, s, clock, 10, at=0) == 10
    assert await tick(c, s, clock, 10, at=300) is None


def test_resend_gap_matches_watchdog_ladder():
    """Plan §7: the gap equals the watchdog attempt-1 spacing (both 900)."""
    assert ec.RESERVE_RESEND_MIN_GAP_S == 900
    assert ec.CONF_PENDING_ATTEMPT_1_AGE_S == 900
    assert ec.RESERVE_CONVERGENCE_BOUND_S == 2400


def test_reserve_reference_source_exposed(sh):
    c, s = sh(soc=98, cloud=10, local=98)
    decide(s, 10)
    st = s.get_status()
    assert st["reserve_reference_source"] == "local"
    assert st["reserve_enforced_divergence_s"] == 0


# ===========================================================================
# D2 nudge
# ===========================================================================
def test_nudge_value_pure():
    assert [_nudge_value(t) for t in (0, 10, 99, 100)] == [1, 11, 100, 99]


def test_nudge_when_cloud_equals_target(sh):
    c, s = sh(soc=98, cloud=10, local=98)
    assert decide(s, 10) == 11


@pytest.mark.asyncio
async def test_nudge_stable_next_tick(sh, clock):
    """Next tick (local 11, cloud stuck 10) → no action (C7)."""
    c, s = sh(soc=98, cloud=10, local=98)
    assert await tick(c, s, clock, 10, at=0) == 11
    set_local(c, clock, 11)
    assert await tick(c, s, clock, 10, at=300) is None
    assert await tick(c, s, clock, 10, at=1200) is None
    assert set_values(c) == [11]


def test_nudge_when_landed_equals_target_and_cloud_differs(sh, clock):
    """R2-H1 / C18: cloud 50 (begin snapshot), last_ok 10, local 50 trusted,
    target 10, gap elapsed → 11, not 10."""
    c, s = sh(soc=60, cloud=50, local=50)
    s._reserve_last_ok_value = 10
    s._reserve_last_attempt_value = 10
    s._reserve_last_attempt_at = clock.t - timedelta(seconds=1000)
    assert decide(s, 10) == 11


def test_nudge_target_100_downward(sh):
    """C9 (Q2): target 100, cloud 100, local 60 → 99."""
    c, s = sh(soc=100, cloud=100, local=60)
    assert decide(s, 100) == 99


def test_no_nudge_when_cloud_differs(sh):
    c, s = sh(soc=98, cloud=15, local=98)
    assert decide(s, 10) == 10


def test_nudge_kill_switch(sh, monkeypatch):
    monkeypatch.setattr(ec, "RESERVE_SAME_VALUE_NUDGE_ENABLED", False)
    c, s = sh(soc=98, cloud=10, local=98)
    assert decide(s, 10) == 10


def _redispatch_ready(s, clock, desire=42):
    s._desired_stamped_at = clock.t
    s._last_reserve_level_desired = desire
    s._last_reserve_level = 80
    s._last_reserve_level_at = clock.t - timedelta(hours=1)


@pytest.mark.asyncio
async def test_force_redispatch_nudges_same_value_all_sinks(sh, clock):
    """R2-M2: cloud = live desire 42 → service value, step-5 ledger, the
    APPLIED row and (raise variant) the failure record + FAILED row all
    carry 43."""
    c, s = sh(soc=60, cloud=42, local=80)
    _redispatch_ready(s, clock)
    await s.force_redispatch(SURFACE)
    await _settle()
    assert set_values(c) == [43]
    assert s._last_reserve_level == 43
    assert [(r["status"], r["value"]) for r in rows(c)] == [("applied", 43)]
    c2, s2 = sh(soc=60, cloud=42, local=80)
    _redispatch_ready(s2, clock)
    raising_bus(c2, "timeout")
    seen = []
    orig = c2._write_verifier.record_dispatch_failed

    async def _spy(surface, value, *a):
        seen.append(value)
        return await orig(surface, value, *a)
    c2._write_verifier.record_dispatch_failed = _spy
    await s2.force_redispatch(SURFACE)
    await _settle()
    assert set_values(c2) == [43]
    assert seen == [43]
    assert [(r["status"], r["value"]) for r in rows(c2)] == [("failed", 43)]
    assert s2._last_reserve_level == 80     # no ledger stamp on raise


@pytest.mark.asyncio
async def test_force_redispatch_no_nudge_when_cloud_differs(sh, clock):
    c, s = sh(soc=60, cloud=10, local=80)
    _redispatch_ready(s, clock)
    await s.force_redispatch(SURFACE)
    assert set_values(c) == [42]


# ===========================================================================
# D3 verifier: local confirms, cloud stale
# ===========================================================================
def _ready_check(c, s, clock, commanded):
    s._last_reserve_level = commanded
    s._last_reserve_level_at = clock.t - timedelta(minutes=20)
    s._last_reserve_level_desired = commanded
    s._desired_stamped_at = clock.t


def _criticals(c):
    return [n for n in c.nm if n.get("severity") == "critical"]


@pytest.mark.asyncio
async def test_check_cloud_stale_local_confirms_no_critical(sh, clock):
    """commanded 15, cloud 10, local 15 → CLOUD_STALE, one anomaly, no NM."""
    c, s = sh(soc=60, cloud=10, local=15)
    _ready_check(c, s, clock, 15)
    wv = c._write_verifier
    await wv._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert wv._records[SURFACE].status == ewv.STATUS_CLOUD_STALE
    assert len(anomalies(c, "reserve_cloud_oracle_stale")) == 1
    assert anomalies(c, "write_verification_failed") == []
    assert c.nm == []
    assert wv.is_reserve_verifiable() is False


@pytest.mark.asyncio
async def test_check_mismatch_local_disagrees_still_critical(sh, clock):
    c, s = sh(soc=60, cloud=10, local=10)
    _ready_check(c, s, clock, 15)
    wv = c._write_verifier
    await wv._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert wv._records[SURFACE].status == ewv.STATUS_MISMATCH
    assert len(_criticals(c)) == 1
    assert "not applied" in _criticals(c)[0]["title"]


@pytest.mark.asyncio
async def test_check_local_confirms_boundary_at_deadband(sh, clock):
    """C20 / R2-M4: local 17 vs commanded 15 (exactly 2) → CRITICAL; local
    16 (1) → CLOUD_STALE."""
    c, s = sh(soc=60, cloud=10, local=17)
    _ready_check(c, s, clock, 15)
    await c._write_verifier._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert len(_criticals(c)) == 1
    c2, s2 = sh(soc=60, cloud=10, local=16)
    _ready_check(c2, s2, clock, 15)
    await c2._write_verifier._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert c2.nm == []
    assert c2._write_verifier._records[SURFACE].status == ewv.STATUS_CLOUD_STALE


@pytest.mark.asyncio
async def test_check_local_unavailable_falls_back_critical(sh, clock):
    """INV-R3: no witness → existing CRITICAL."""
    c, s = sh(soc=60, cloud=10, local=None)
    _ready_check(c, s, clock, 15)
    await c._write_verifier._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert len(_criticals(c)) == 1


@pytest.mark.asyncio
async def test_check_kill_switch_restores_critical(sh, clock, monkeypatch):
    monkeypatch.setattr(ec, "RESERVE_LOCAL_WITNESS_ENABLED", False)
    c, s = sh(soc=60, cloud=10, local=15)
    _ready_check(c, s, clock, 15)
    await c._write_verifier._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert len(_criticals(c)) == 1


@pytest.mark.asyncio
async def test_sweep_cloud_stale_no_reverted_nm(sh, clock):
    c, s = sh(soc=60, cloud=10, local=15)
    _ready_check(c, s, clock, 15)
    wv = c._write_verifier
    await wv._sweep_surface(s, SURFACE)
    assert wv._records[SURFACE].status == ewv.STATUS_CLOUD_STALE
    assert anomalies(c, "write_reverted") == []
    assert len(anomalies(c, "reserve_cloud_oracle_stale")) == 1
    assert c.nm == []
    # Discriminator: local disagrees → existing REVERTED + NM.
    c2, s2 = sh(soc=60, cloud=10, local=10)
    _ready_check(c2, s2, clock, 15)
    await c2._write_verifier._sweep_surface(s2, SURFACE)
    assert len(anomalies(c2, "write_reverted")) == 1
    assert len(_criticals(c2)) == 1


@pytest.mark.asyncio
async def test_sweep_pending_suppression_precedes_cloud_stale(sh, clock):
    """R1-M7: a pending episode armed → existing suppression; no CLOUD_STALE
    row; episode state untouched."""
    c, s = sh(soc=60, cloud=10, local=15)
    _ready_check(c, s, clock, 15)
    wv = c._write_verifier
    wv._pending_attempts_fired[SURFACE] = 1
    ep = clock.t - timedelta(minutes=17)
    wv._pending_episode_at[SURFACE] = ep
    await wv._sweep_surface(s, SURFACE)
    assert wv._records[SURFACE].status == ewv.STATUS_REVERTED
    assert anomalies(c, "reserve_cloud_oracle_stale") == []
    assert anomalies(c, "write_reverted") == []
    assert c.nm == []
    assert wv._pending_attempts_fired[SURFACE] == 1
    assert wv._pending_episode_at[SURFACE] == ep


@pytest.mark.asyncio
async def test_cloud_stale_latch_keyed_on_desire(sh, clock):
    """R2-L2: alternating schedules 11, 10, 11 under one desire 10 → one
    anomaly; a new effective desire re-arms; cloud matching clears."""
    c, s = sh(soc=60, cloud=50, local=10)
    _ready_check(c, s, clock, 10)
    wv = c._write_verifier
    for v in (11, 10, 11):
        await wv._check(SURFACE, v, clock.t - timedelta(minutes=20))
    assert len(anomalies(c, "reserve_cloud_oracle_stale")) == 1
    s._last_reserve_level_desired = 11
    await wv._check(SURFACE, 11, clock.t - timedelta(minutes=20))
    assert len(anomalies(c, "reserve_cloud_oracle_stale")) == 2
    set_cloud(c, clock, 11)
    await wv._check(SURFACE, 11, clock.t - timedelta(minutes=20))
    assert wv._cloud_stale_check_latch is None
    set_cloud(c, clock, 50)
    await wv._check(SURFACE, 11, clock.t - timedelta(minutes=20))
    assert len(anomalies(c, "reserve_cloud_oracle_stale")) == 3


@pytest.mark.asyncio
async def test_sweep_latch_clears_on_match(sh, clock):
    c, s = sh(soc=60, cloud=10, local=15)
    _ready_check(c, s, clock, 15)
    wv = c._write_verifier
    await wv._sweep_surface(s, SURFACE)
    await wv._sweep_surface(s, SURFACE)
    assert len(anomalies(c, "reserve_cloud_oracle_stale")) == 1
    set_cloud(c, clock, 15)
    await wv._sweep_surface(s, SURFACE)
    assert wv._cloud_stale_sweep_latch is None


@pytest.mark.asyncio
@pytest.mark.parametrize("local,expect_nm", [(15, False), (10, True)])
async def test_self_heal_starvation_suppressed_when_local_confirms(
    sh, clock, monkeypatch, local, expect_nm,
):
    """Three same-value self-heals: local matching → no starvation NM;
    local not matching → existing NM."""
    monkeypatch.setattr(ewv, "async_call_later", lambda *a, **k: (lambda: None))
    c, s = sh(soc=60, cloud=10, local=local)
    _ready_check(c, s, clock, 15)
    wv = c._write_verifier
    for _ in range(4):
        await ewv.WriteVerifier.schedule(wv, SURFACE, 15, clock.t)
    starv = [p for p in anomalies(c, "write_verification_failed")
             if "self_heal_starvation" in str(p)]
    assert bool(_criticals(c)) is expect_nm
    assert bool(starv) is expect_nm


@pytest.mark.asyncio
async def test_reserve_verifiable_false_on_cloud_stale(sh, clock):
    c, s = sh(soc=60, cloud=10, local=15)
    _ready_check(c, s, clock, 15)
    wv = c._write_verifier
    rec = wv._records[SURFACE]
    rec.status = ewv.STATUS_OK
    rec.verified_at = clock.t.isoformat()
    assert wv.is_reserve_verifiable() is True       # discriminator
    await wv._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert wv.is_reserve_verifiable() is False


# ===========================================================================
# D4 enforced-vs-desired dwell trip-wire
# ===========================================================================
async def _dwell(c, s, clock, at):
    clock.t = c.t0 + timedelta(seconds=at)
    refresh(c, clock)
    await c._write_verifier._enforced_divergence_tick(s)


def _div(c):
    return anomalies(c, "reserve_enforced_divergence")


def _highs(c):
    return [n for n in c.nm if n.get("severity") == "high"
            and "not following" in n.get("title", "")]


@pytest.mark.asyncio
async def test_enforced_divergence_fires_after_dwell(sh, clock):
    """Local 98, effective desire 10: none at 2700 s, fires past it."""
    c, s = sh(soc=98, cloud=10, local=98)
    s._last_reserve_level_desired = 10
    for at in range(0, 2701, 300):
        await _dwell(c, s, clock, at)
    assert _div(c) == [] and _highs(c) == []
    assert s.get_status()["reserve_enforced_divergence_s"] == 2700
    await _dwell(c, s, clock, 2701)
    assert len(_div(c)) == 1 and len(_highs(c)) == 1
    await _dwell(c, s, clock, 3000)
    assert len(_div(c)) == 1 and len(_highs(c)) == 1


@pytest.mark.asyncio
async def test_enforced_divergence_daily_latch(sh, clock):
    """A second episode the same day → anomaly, no NM."""
    c, s = sh(soc=98, cloud=10, local=98)
    s._last_reserve_level_desired = 10
    for at in (0, 2701):
        await _dwell(c, s, clock, at)
    set_local(c, clock, 10)
    await _dwell(c, s, clock, 3000)
    assert c._write_verifier._enforced_divergence_s == 0
    set_local(c, clock, 98)
    for at in (3300, 6001):
        await _dwell(c, s, clock, at)
    assert len(_div(c)) == 2
    assert len(_highs(c)) == 1


@pytest.mark.asyncio
async def test_enforced_divergence_ignores_low_soc_and_standdown(sh, clock):
    c, s = sh(soc=6, cloud=10, local=16)
    s._last_reserve_level_desired = 10
    for at in range(0, 7201, 300):
        await _dwell(c, s, clock, at)
    assert _div(c) == [] and c._write_verifier._enforced_divergence_s == 0
    c2, s2 = sh(soc=98, cloud=10, local=98)
    s2._last_reserve_level_desired = 10
    c2._write_verifier._pending_standdown_at[SURFACE] = clock.t
    c2._write_verifier._pending_standdown_value[SURFACE] = 10
    for at in range(0, 7201, 300):
        await _dwell(c2, s2, clock, at)
    assert _div(c2) == [] and c2._write_verifier._enforced_divergence_s == 0


@pytest.mark.asyncio
async def test_enforced_divergence_uses_effective_desire_under_evse_hold(sh, clock):
    """C16: EVSE hold 98, strategy desire 10, local 98 for 2 h → no dwell."""
    c, s = sh(soc=98, cloud=10, local=98)
    s._last_reserve_level_desired = 10
    c._evse_battery_hold_active = True
    c._evse_hold_soc = 98
    for at in range(0, 7201, 300):
        await _dwell(c, s, clock, at)
    assert _div(c) == [] and c._write_verifier._enforced_divergence_s == 0


@pytest.mark.asyncio
async def test_enforced_divergence_kill_switch(sh, clock, monkeypatch):
    monkeypatch.setattr(ec, "RESERVE_ENFORCED_DIVERGENCE_TRIPWIRE_S", 0)
    c, s = sh(soc=98, cloud=10, local=98)
    s._last_reserve_level_desired = 10
    for at in range(0, 7201, 300):
        await _dwell(c, s, clock, at)
    assert _div(c) == []


@pytest.mark.asyncio
async def test_observation_mode_excludes_dwell(sh, clock):
    """C12: observation mode → dwell excluded."""
    c, s = sh(soc=98, cloud=10, local=98)
    s._last_reserve_level_desired = 10
    c._observation_mode = True
    for at in range(0, 7201, 300):
        await _dwell(c, s, clock, at)
    assert _div(c) == [] and c._write_verifier._enforced_divergence_s == 0


@pytest.mark.asyncio
async def test_enforced_divergence_wired_into_reversion_sweep(sh, clock):
    """Wire-in anchor: the enclosing `reversion_sweep` drives D4."""
    c, s = sh(soc=98, cloud=10, local=98)
    s._last_reserve_level_desired = 10
    wv = c._write_verifier

    async def _noop(*a, **k):
        return None
    wv._pending_watchdog_reserve = _noop
    wv._conduct_check_reserve = _noop
    wv._sweep_surface = _noop
    for at in (0, 2701):
        clock.t = c.t0 + timedelta(seconds=at)
        refresh(c, clock)
        await wv.reversion_sweep()
    assert len(_div(c)) == 1


# ===========================================================================
# D5 control_change_pending = DEFERRED
# ===========================================================================
@pytest.mark.asyncio
async def test_control_change_pending_is_deferred_not_paged(sh, clock):
    c, s = sh(soc=98, cloud=50, local=98)
    raising_bus(c, "control_change_pending")
    await tick(c, s, clock, 10, at=0)
    await tick(c, s, clock, 20, at=300)
    assert c.nm == []
    assert [r["status"] for r in rows(c)] == ["deferred", "deferred"]
    assert len(anomalies(c, "battery_write_deferred")) == 1
    assert anomalies(c, "battery_write_failed") == []
    assert c._write_verifier._records[SURFACE].status == ewv.STATUS_DISPATCH_DEFERRED


@pytest.mark.asyncio
async def test_deferred_episode_closes_on_success(sh, clock):
    c, s = sh(soc=98, cloud=50, local=98)
    raising_bus(c, "control_change_pending")
    await tick(c, s, clock, 10, at=0)
    ok = []

    async def _svc(domain, svc, data, blocking=False, **kw):
        ok.append(data)
    c.hass.services = SimpleNamespace(async_call=_svc)
    await tick(c, s, clock, 20, at=300)
    raising_bus(c, "control_change_pending")
    await tick(c, s, clock, 30, at=600)
    assert len(anomalies(c, "battery_write_deferred")) == 2


@pytest.mark.asyncio
async def test_out_of_range_still_pages(sh, clock):
    c, s = sh(soc=98, cloud=50, local=98)
    raising_bus(c, "out_of_range")
    await tick(c, s, clock, 3, at=0)
    assert [r["status"] for r in rows(c)] == ["failed"]
    assert len([n for n in c.nm if n.get("severity") == "high"]) == 1
    assert len(anomalies(c, "battery_write_failed")) == 1


@pytest.mark.asyncio
async def test_raised_dispatch_does_not_advance_landed_stamp(sh, clock):
    c, s = sh(soc=98, cloud=50, local=98)
    s._reserve_last_ok_value = 98
    raising_bus(c, "control_change_pending")
    await tick(c, s, clock, 10, at=0)
    assert s._reserve_last_ok_value == 98
    assert s._reserve_last_attempt_value == 10
    assert s._reserve_last_attempt_at == clock.t


@pytest.mark.asyncio
async def test_tap_still_stamps_commanded_ledger_on_raise(sh, clock):
    """Pins existing behaviour (N9): the tap stamps the ledger on a raise."""
    c, s = sh(soc=98, cloud=50, local=98)
    raising_bus(c, "control_change_pending")
    await tick(c, s, clock, 10, at=0)
    assert s._last_reserve_level == 10
    assert s._last_reserve_level_at == clock.t


@pytest.mark.asyncio
async def test_raised_dispatch_retried_after_gap(sh, clock):
    """C11: raise at T; T+300 in_flight; T+900 re-sent (trusted local 98)."""
    c, s = sh(soc=98, cloud=50, local=98)
    raising_bus(c, "control_change_pending")
    assert await tick(c, s, clock, 10, at=0) == 10
    assert await tick(c, s, clock, 10, at=300) is None
    assert await tick(c, s, clock, 10, at=900) == 10


@pytest.mark.asyncio
async def test_force_redispatch_control_change_pending_row_deferred(sh, clock):
    c, s = sh(soc=60, cloud=10, local=80)
    _redispatch_ready(s, clock)
    raising_bus(c, "control_change_pending")
    await s.force_redispatch(SURFACE)
    await _settle()
    assert [r["status"] for r in rows(c)] == ["deferred"]
    assert c.nm == []
    assert s._reserve_last_ok_value is None


# ===========================================================================
# Episode replays (D0 §13.2 shapes; recorder fixtures not committed, so the
# shapes are scripted from the D0 report rows — inputs are the recorded
# values quoted there).
# ===========================================================================
@pytest.mark.asyncio
async def test_episode_d_stuck_98_released_within_bound(sh, clock):
    """Episode D (10-23): hold 98 ended, cloud 10, local 98, desire 10. The
    gateway applies a landed non-dropped value; enphase_ev drops a value
    equal to its stored selected value (10). INV-R1: local reaches desire
    (within the deadband) inside 2400 s."""
    c, s = sh(soc=98, cloud=10, local=98)
    selected = 10

    async def _svc(domain, svc, data, blocking=False, **kw):
        nonlocal selected
        c.calls.append([domain, svc, dict(data)])
        if data["value"] != selected:
            selected = data["value"]
            c.local_value = data["value"]
    c.hass.services = SimpleNamespace(async_call=_svc)
    converged_at = None
    for at in range(0, 2401, 300):
        await tick(c, s, clock, 10, at=at)
        if converged_at is None and abs(c.local_value - 10) < 2:
            converged_at = at
    assert converged_at is not None and converged_at <= 2400
    assert set_values(c) == [11]


@pytest.mark.asyncio
async def test_episode_d_pre_cycle_never_releases(sh, clock, monkeypatch):
    """Discriminator for the test above: kill switches off → no send at all
    (cloud 10 = target), local stays 98."""
    for name in ("RESERVE_LOCAL_WITNESS_ENABLED", "RESERVE_LEDGER_SEND_ENABLED",
                 "RESERVE_SAME_VALUE_NUDGE_ENABLED"):
        monkeypatch.setattr(ec, name, False)
    c, s = sh(soc=98, cloud=10, local=98)
    for at in range(0, 2401, 300):
        await tick(c, s, clock, 10, at=at)
    assert set_values(c) == []


@pytest.mark.asyncio
async def test_episode_e_cloud_stuck_no_churn_no_false_critical(sh, clock):
    """Episode E (10-24 00:25-06:06Z): cloud stuck at 12; local 10 (= desire)
    then desire 15 applied (local 15). Pre-cycle: 66 re-sends + false
    CRITICAL. New: the two legitimate sends only; the verifier classifies
    CLOUD_STALE; the 04:06 local-unavailable window behaves as pre-cycle."""
    c, s = sh(soc=80, cloud=12, local=12)

    async def _svc(domain, svc, data, blocking=False, **kw):
        c.calls.append([domain, svc, dict(data)])
        c.local_value = data["value"]          # gateway applies; cloud stays 12
    c.hass.services = SimpleNamespace(async_call=_svc)
    assert await tick(c, s, clock, 10, at=0) == 10
    for at in range(300, 7200, 300):
        assert await tick(c, s, clock, 10, at=at) is None
    assert await tick(c, s, clock, 15, at=7200) == 15
    for at in range(7500, 13800, 300):
        assert await tick(c, s, clock, 15, at=at) is None
    assert set_values(c) == [10, 15]
    s._last_reserve_level_desired = 15
    s._desired_stamped_at = clock.t
    await c._write_verifier._check(SURFACE, 15, clock.t - timedelta(minutes=20))
    assert _criticals(c) == []
    assert c._write_verifier._records[SURFACE].status == ewv.STATUS_CLOUD_STALE
    # Local unavailable window: rule C = pre-cycle (cloud 12 vs 15 → send).
    c.local_value = None
    assert await tick(c, s, clock, 15, at=13800) == 15


@pytest.mark.asyncio
async def test_episode_e_pre_cycle_churns(sh, clock, monkeypatch):
    """Discriminator: kill switches off → re-send every tick (the 66)."""
    for name in ("RESERVE_LOCAL_WITNESS_ENABLED", "RESERVE_LEDGER_SEND_ENABLED",
                 "RESERVE_SAME_VALUE_NUDGE_ENABLED"):
        monkeypatch.setattr(ec, name, False)
    c, s = sh(soc=80, cloud=12, local=12)
    for at in range(7200, 13800, 300):
        await tick(c, s, clock, 15, at=at)
    assert len(set_values(c)) == 22


# ===========================================================================
# INV-R3 kill-switch golden (all four switches off → pre-Stage-A golden)
# ===========================================================================
_SWITCHES = ("RESERVE_LOCAL_WITNESS_ENABLED", "RESERVE_LEDGER_SEND_ENABLED",
             "RESERVE_SAME_VALUE_NUDGE_ENABLED",
             "RESERVE_ATTAIN_BASE_INTENT_ENABLED")


def _golden_with_live_witness(monkeypatch, reg, local):
    import test_ec_stage_a_noop_golden as g  # noqa: PLC0415
    orig = g.make_shell

    def _wrapped(clock, **kw):
        c, s = orig(clock, **kw)
        _st(c.hass, LOCAL_EID, str(local), unit="%", lu=clock.t)
        s._reserve_last_ok_value = 98
        return c, s
    monkeypatch.setattr(g, "make_shell", _wrapped)
    return g


def test_reserve_reference_kill_switch_byte_identical(clock, reg, monkeypatch):
    """All four switches off + a live witness (local 98) + a landed stamp
    98 → every golden case reproduces exactly."""
    for name in _SWITCHES:
        monkeypatch.setattr(ec, name, False)
    g = _golden_with_live_witness(monkeypatch, reg, 98)
    golden = json.loads(g.GOLDEN.read_text())
    for case in g.CASES:
        assert json.loads(json.dumps(g._run_case(case, clock))) == golden[case], case


def test_golden_harness_witness_is_live_when_switches_on(clock, reg, monkeypatch):
    """Discriminator for the golden test: with the switches ON the same
    wrapper changes at least one case (the witness really is live)."""
    g = _golden_with_live_witness(monkeypatch, reg, 98)
    golden = json.loads(g.GOLDEN.read_text())
    diffs = [case for case in g.CASES
             if json.loads(json.dumps(g._run_case(case, clock))) != golden[case]]
    assert diffs


# ===========================================================================
# Additional anchors
# ===========================================================================
@pytest.mark.asyncio
async def test_timer_deferred_row_does_not_arm_gate(sh, clock):
    """D5 + D-4: a timer DEFERRED (raised) row must not arm the change gate:
    the recovered re-send of the same value at the same pre-state logs."""
    c, s = sh()
    owner = c._write_verifier._resolve_hold_owner(s)
    c._record_reserve_dispatch(status=WS.DEFERRED, path="timer",
                               target=RESERVE_WRITE_EID, value=40, reason="x",
                               pre_state=40.0)
    assert getattr(c, "_last_reserve_row_key", None) != ("timer", 40, owner)
    c._record_reserve_dispatch(status=WS.APPLIED, path="timer",
                               target=RESERVE_WRITE_EID, value=40, reason="x",
                               pre_state=40.0)
    await _settle()
    assert [r["status"] for r in rows(c)] == ["deferred", "applied"]


@pytest.mark.asyncio
async def test_row_carries_reserve_reference_source(sh, clock):
    c, s = sh(soc=98, cloud=50, local=98)
    await tick(c, s, clock, 10, at=0)
    assert rows(c)[-1]["reserve_reference_source"] == "local"


@pytest.mark.parametrize("margin", [0, 5])
@pytest.mark.parametrize("span", [20, 100])
def test_config_extremes_trust_guard(sh, monkeypatch, margin, span):
    """§6 config extremes: margin {0, 5} x span {20, 100}.
    (a) Incident shape (SOC 98, local 98, target 10) always trusted → sends.
    (b) Ratchet shape (SOC 6, local 16, target 10) always guarded (SOC <=
        target even at margin 0; local - SOC = 10 <= span).
    (c) Stuck-high at SOC 11 (local 98): trusted iff span < 87."""
    monkeypatch.setattr(ec, "RESERVE_LOCAL_LOW_SOC_MARGIN_PCT", margin)
    monkeypatch.setattr(ec, "RESERVE_LOCAL_RATCHET_SPAN_PCT", span)
    c, s = sh(soc=98, cloud=10, local=98)
    assert decide(s, 10) == 11
    c2, s2 = sh(soc=6, cloud=10, local=16)
    assert decide(s2, 10) is None
    assert s2._reserve_reference_source == "cloud_low_soc_guard"
    c3, s3 = sh(soc=11, cloud=10, local=98)
    src = c3._write_verifier.trusted_local_reserve(s3, 10, 11)[1]
    assert src == ("local" if (span == 20 or margin == 0) else "low_soc_guard")

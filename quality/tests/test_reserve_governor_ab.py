"""EC-RESERVE-WRITE-GOVERNOR-1 — INV-G3 A/B golden (no behaviour change).

The golden fixture `fixtures/reserve_governor_golden.json` is captured in a
commit that PREDATES any governor code (the plan's Commit 1). Every later
commit must reproduce it byte-for-byte, both with the row writer live and
with `EnergyCoordinator._record_reserve_dispatch` patched to a no-op.

What is captured per branch (frozen `dt_util.utcnow`/`dt_util.now`, so the
timestamp fields are kept, not dropped — plan R3-05):
  * the HA service calls actually dispatched (domain, service, data)
  * the decision's dispatched `actions` list + `reason`
  * `_last_reserve_level`, `_last_reserve_level_at`, `_last_reserve_level_desired`
  * every `WriteVerifier.schedule(surface, value, now)` call

Branches: allow_discharge, partial_hold, full_hold, EVSE overlay, DP fold,
blind de-escalation (timer path through the REAL
`_execute_breaker_safe_dispatch` → `_execute_service_action` →
`_tap_write_verifier`), the TOU-transition evaluate path
(`_evaluate_battery`, which bypasses the tap), and `force_redispatch`.

Regenerate ONLY in a commit with no governor code:
    RESERVE_GOVERNOR_WRITE_GOLDEN=1 PYTHONPATH=quality .venv-ha/bin/python \
        -m pytest quality/tests/test_reserve_governor_ab.py -q
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from conftest import MockHass, MockState  # noqa: E402
from ec_phalanx_entities import (  # noqa: E402
    PHALANX_CHARGE_FROM_GRID_ENTITY,
    PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
    PHALANX_CLOUD_RESERVE_ORACLE_ENTITY,
    PHALANX_GRID_ENABLED_ENTITY,
    PHALANX_RESERVE_SOC_ENTITY,
    PHALANX_SOLCAST_TODAY_ENTITY,
    PHALANX_SOLCAST_TOMORROW_ENTITY,
    PHALANX_STORAGE_MODE_ENTITY,
    PHALANX_WEATHER_ENTITY,
    phalanx_battery_entities,
    phalanx_cloud_oracles,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (  # noqa: E402
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (  # noqa: E402
    WriteVerifier,
)

GOLDEN = Path(__file__).parent / "fixtures" / "reserve_governor_golden.json"
WRITE_GOLDEN = os.environ.get("RESERVE_GOVERNOR_WRITE_GOLDEN") == "1"

_SOC = "sensor.ab_envoy_battery"
_CDT = timezone(timedelta(hours=-5))
_UTC = timezone.utc
# Summer afternoon so "peak" exists for the blind branch (summer TOU).
_T0 = datetime(2026, 6, 15, 21, 0, tzinfo=_UTC)  # 16:00 CDT

BRANCHES = (
    "allow_discharge", "partial_hold", "full_hold", "evse_overlay",
    "dp_fold", "blind", "evaluate", "redispatch",
)


# ---------------------------------------------------------------------------
# Frozen clock (same pattern as test_ec_degraded_data_p1.py `clock`).
# ---------------------------------------------------------------------------
class _Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t


def _dt_modules():
    mods = []
    m = sys.modules.get("homeassistant.util.dt")
    if m is not None:
        mods.append(m)
    pkg = sys.modules.get("homeassistant.util")
    alt = getattr(pkg, "dt", None) if pkg is not None else None
    if alt is not None and alt not in mods:
        mods.append(alt)
    return mods


@pytest.fixture
def clock(monkeypatch):
    c = _Clock(_T0)
    for m in _dt_modules():
        monkeypatch.setattr(m, "utcnow", lambda: c.t, raising=False)
        monkeypatch.setattr(m, "now", lambda: c.t.astimezone(_CDT), raising=False)
        monkeypatch.setattr(m, "as_local", lambda d: d.astimezone(_CDT), raising=False)
    return c


# ---------------------------------------------------------------------------
# Harness: REAL EnergyCoordinator dispatch chokepoint + REAL BatteryStrategy
# + REAL WriteVerifier. Only the HA service bus, NM and the DB are faked.
# ---------------------------------------------------------------------------
class _Shell(EnergyCoordinator):
    def __init__(self):  # noqa: D401 — bypass the heavy init
        pass


class _DB:
    """Records `log_activity` rows (async, like production)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def log_activity(self, **kw):
        self.rows.append(kw)


def _st(hass, eid, state, *, unit=None, lu=None):
    attrs = {"unit_of_measurement": unit} if unit else {}
    s = MockState(eid, state, attrs)
    if lu is not None:
        s.last_updated = lu
        s.last_changed = lu
        s.last_reported = lu
    hass._states[eid] = s


def make_shell(clock, *, soc="45", reserve_state="0", cfg_state="off",
               peak_buffer_target=30):
    """Build (coord, strategy). Cloud-first write routing (the live config):
    the reserve write leg is `PHALANX_CLOUD_RESERVE_ORACLE_ENTITY`."""
    hass = MockHass()
    t = clock.t
    _st(hass, _SOC, soc, unit="%", lu=t)
    _st(hass, PHALANX_STORAGE_MODE_ENTITY, "self_consumption", lu=t)
    _st(hass, PHALANX_GRID_ENABLED_ENTITY, "on", lu=t)
    _st(hass, PHALANX_CHARGE_FROM_GRID_ENTITY, cfg_state, lu=t)
    _st(hass, PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY, cfg_state, lu=t)
    _st(hass, PHALANX_RESERVE_SOC_ENTITY, reserve_state, unit="%", lu=t)
    _st(hass, PHALANX_CLOUD_RESERVE_ORACLE_ENTITY, reserve_state, unit="%", lu=t)
    _st(hass, PHALANX_SOLCAST_TODAY_ENTITY, "90", lu=t)
    _st(hass, PHALANX_SOLCAST_TOMORROW_ENTITY, "90", lu=t)
    _st(hass, PHALANX_WEATHER_ENTITY, "sunny", lu=t)
    # Real task scheduling so fire-and-forget DB rows actually run.
    hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
    db = _DB()
    hass.data["universal_room_automation"] = {"database": db}

    calls: list = []

    async def _svc(domain, svc, data, blocking=False, **kw):
        calls.append([domain, svc, dict(data)])
    hass.services = SimpleNamespace(async_call=_svc)

    s = BatteryStrategy(
        hass,
        reserve_soc=10,
        peak_buffer_target=peak_buffer_target,
        entity_config=phalanx_battery_entities() | phalanx_cloud_oracles()
        | {"battery_soc": _SOC},
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        arbitrage_enabled=False,
    )
    s._inclement_config_override = {}  # no NWS entity → allow_discharge

    c = _Shell()
    c.hass = hass
    c._battery = s
    c._ev = EVChargerController(hass, evse_config={"garage_a": {
        "switch": "switch.ab_garage_a", "power": "sensor.ab_garage_a_power",
    }})
    _st(hass, "switch.ab_garage_a", "off", lu=t)
    _st(hass, "sensor.ab_garage_a_power", "0", unit="W", lu=t)
    c._last_known_grid_charge_on = False
    c._last_cfg_off_read_at = None
    c._cfg_unknown_forced_since = None
    c._evse_battery_hold_active = False
    c._evse_hold_soc = None
    c._dp_decision_soc = None
    c._dp_carrier = None
    c._observation_mode = False
    c.calls = calls
    c.db = db
    c.nm: list = []

    async def _nm(**kw):
        c.nm.append(kw)
    c._send_nm_alert = _nm
    c._write_verifier = WriteVerifier(hass, c)
    s._write_verifier = c._write_verifier
    s._coord = c
    # Record every verifier.schedule(surface, value, now) call, then call
    # through (the verifier is "never raises").
    c.schedules: list = []
    _orig_schedule = c._write_verifier.schedule

    async def _rec_schedule(surface, value, now=None):
        c.schedules.append([surface, value, now.isoformat() if now else None])
        return await _orig_schedule(surface, value, now)
    c._write_verifier.schedule = _rec_schedule
    return c, s


def _inclement(hold_depth, floor):
    from custom_components.universal_room_automation.domain_coordinators.inclement import (
        InclementDecision,
        _na_horizon,
    )
    return InclementDecision(
        hold_depth=hold_depth, grid_precharge=False, tier="watch",
        source="alert", contributing_event="Severe Thunderstorm Watch",
        expires_at=None, reserve_floor=floor,
        reason="watch_corroborated_recoverable_partial_hold",
        solar_horizon=_na_horizon(),
    )


def seed_inclement(s, now, hold_depth, floor):
    """Pre-seed determine_mode's per-tick cache (same seam as
    test_battery_inclement_arbitrage_floor._seed_partial_hold)."""
    s._last_inclement_decision = _inclement(hold_depth, floor)
    s._last_inclement_decision_at = now


def _snapshot(c, s, decision=None, extra=None):
    out = {
        "calls": c.calls,
        "schedules": c.schedules,
        "last_reserve_level": s._last_reserve_level,
        "last_reserve_level_at": (
            s._last_reserve_level_at.isoformat()
            if s._last_reserve_level_at else None
        ),
        "last_reserve_level_desired": s._last_reserve_level_desired,
    }
    if decision is not None:
        out["reason"] = decision.get("reason")
        out["actions"] = decision.get("actions")
    if extra:
        out.update(extra)
    return out


async def _settle():
    # Let fire-and-forget tasks (DB rows) run so they cannot leak.
    for _ in range(3):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Branch drivers
# ---------------------------------------------------------------------------
async def run_branch(branch: str, clock) -> dict:
    now = clock.t.astimezone(_CDT)
    if branch == "allow_discharge":
        c, s = make_shell(clock, soc="45")
        d = s.determine_mode("mid_peak", "summer", now=now)
        await c._execute_breaker_safe_dispatch(d, "mid_peak")
        await _settle()
        return _snapshot(c, s, d)
    if branch == "partial_hold":
        c, s = make_shell(clock, soc="45")
        seed_inclement(s, now, "partial_hold", 60)
        d = s.determine_mode("mid_peak", "summer", now=now)
        await c._execute_breaker_safe_dispatch(d, "mid_peak")
        await _settle()
        return _snapshot(c, s, d)
    if branch == "full_hold":
        c, s = make_shell(clock, soc="45")
        seed_inclement(s, now, "full_hold", 70)
        d = s.determine_mode("mid_peak", "summer", now=now)
        await c._execute_breaker_safe_dispatch(d, "mid_peak")
        await _settle()
        return _snapshot(c, s, d)
    if branch == "evse_overlay":
        c, s = make_shell(clock, soc="20")
        d = s.determine_mode("mid_peak", "summer", now=now)
        c._evse_hold_soc = 60
        c._evse_battery_hold_active = True
        d = c._apply_evse_battery_hold(d)
        await c._execute_breaker_safe_dispatch(d, "mid_peak")
        await _settle()
        return _snapshot(c, s, d)
    if branch == "dp_fold":
        from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (
            DPState,
        )
        c, s = make_shell(clock, soc="20")
        d = s.determine_mode("mid_peak", "summer", now=now)
        c._evse_hold_soc = 60
        c._evse_battery_hold_active = True
        c._dp_decision_soc = 70
        c._dp_carrier = SimpleNamespace(state=DPState.TRANSITIONED)
        d = c._apply_evse_battery_hold(d)
        await c._execute_breaker_safe_dispatch(d, "mid_peak")
        await _settle()
        return _snapshot(c, s, d)
    if branch == "blind":
        c, s = make_shell(clock, soc="unavailable", cfg_state="on")
        s._soc_lkg = None
        s._soc_lkg_at = None
        d = s.determine_mode("peak", "summer", now=now)
        assert "Blind de-escalation" in d["reason"], d["reason"]
        await c._execute_breaker_safe_dispatch(d, "peak")
        await _settle()
        return _snapshot(c, s, d)
    if branch == "evaluate":
        c, s = make_shell(clock, soc="45")
        c._tou = SimpleNamespace(
            get_current_period=lambda *a: "mid_peak",
            get_season=lambda *a: "summer",
        )
        acts = await c._evaluate_battery()
        await _settle()
        return _snapshot(c, s, c._last_battery_decision, extra={
            "cm_actions": [
                [a.service, a.target_device, a.service_data] for a in acts
            ],
        })
    if branch == "redispatch":
        c, s = make_shell(clock, soc="45")
        s._desired_stamped_at = clock.t
        s._last_reserve_level_desired = 42
        s._last_reserve_level = 80
        s._last_reserve_level_at = clock.t - timedelta(hours=1)
        await s.force_redispatch("reserve_soc")
        await _settle()
        return _snapshot(c, s)
    raise AssertionError(branch)


def _load_golden() -> dict:
    return json.loads(GOLDEN.read_text())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("branch", BRANCHES)
async def test_ab_golden_matches(branch, clock):
    """Live row writer (if any) vs the pre-governor golden capture."""
    observed = run_branch_result = await run_branch(branch, clock)
    if WRITE_GOLDEN:
        data = _load_golden() if GOLDEN.exists() else {}
        data[branch] = observed
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        return
    golden = _load_golden()
    assert branch in golden, f"golden has no branch {branch!r}"
    assert json.loads(json.dumps(observed)) == golden[branch]
    del run_branch_result


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", BRANCHES)
async def test_ab_golden_matches_with_row_writer_noop(branch, clock, monkeypatch):
    """Same capture with `_record_reserve_dispatch` patched to a no-op (the
    governor's only new side effect). `raising=False` so this test is valid
    in Commit 1, where the helper does not exist yet."""
    if WRITE_GOLDEN:
        pytest.skip("golden write mode")
    monkeypatch.setattr(
        EnergyCoordinator, "_record_reserve_dispatch",
        lambda *a, **k: None, raising=False,
    )
    observed = await run_branch(branch, clock)
    golden = _load_golden()
    assert json.loads(json.dumps(observed)) == golden[branch]


def test_golden_covers_every_branch():
    golden = _load_golden()
    assert set(golden) == set(BRANCHES)


def test_golden_branches_dispatch_reserve_writes():
    """Sanity on the fixture itself: every branch actually produced a
    reserve `number.set_value` (else the A/B would be vacuous)."""
    golden = _load_golden()
    for branch in BRANCHES:
        if branch == "evaluate":
            svcs = [a[0] for a in golden[branch]["cm_actions"]]
        else:
            svcs = [f"{d}.{s}" for d, s, _ in golden[branch]["calls"]]
        assert "number.set_value" in svcs, (branch, svcs)

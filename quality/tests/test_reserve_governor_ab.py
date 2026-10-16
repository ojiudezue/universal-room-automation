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

import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    BRANCHES,
    EnergyCoordinator,
    _CDT,
    _settle,
    _snapshot,
    clock,
    make_shell,
    seed_inclement,
)

GOLDEN = Path(__file__).parent / "fixtures" / "reserve_governor_golden.json"
WRITE_GOLDEN = os.environ.get("RESERVE_GOVERNOR_WRITE_GOLDEN") == "1"


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

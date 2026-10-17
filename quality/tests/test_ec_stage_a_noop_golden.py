"""EC storm/blind Stage A — sighted no-op golden (PLANNING_ec_storm_and_blind_decisions.md).

Captured on the PRE-Stage-A commit (no `_reserve_action`, no
`_tick_reserve_floor`). Every later commit must reproduce it exactly: the
Stage A extraction of `_result`'s reserve block into `_reserve_action`, the
registered per-tick floor, the fold, and the re-keyed off-peak clamps are
all byte-identical on every SIGHTED tick (INV-1 is satisfied by construction
there already; a diff here is a pre-existing floor leak of the D-HIGH-1
class and stops the build).

What is captured per case: the decision's `mode`, `reason`, `actions`,
`charge_from_grid`, `arbitrage_phase`, plus the strategy's
`_last_reserve_level_desired` and `_offpeak_drain_branch_target` stamps.
Inputs: TOU period x season x clock hour x inclement hold (none / partial /
full, seeded through the per-tick cache seam) x SOC x hardware reserve x
arbitrage on/off. Inclement floors are >= reserve_soc, as fusion always
produces (`inclement.py _partial_floor_value`).

Regenerate ONLY on a commit with no Stage A code:
    EC_STAGE_A_WRITE_GOLDEN=1 PYTHONPATH=quality .venv-ha/bin/python \
        -m pytest quality/tests/test_ec_stage_a_noop_golden.py -q
"""
from __future__ import annotations

import itertools
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _CDT,
    clock,
    make_shell,
    seed_inclement,
)

GOLDEN = Path(__file__).parent / "fixtures" / "ec_stage_a_noop_golden.json"
WRITE_GOLDEN = os.environ.get("EC_STAGE_A_WRITE_GOLDEN") == "1"

# (label, utc datetime, tou_period, season) — tou_period passed explicitly
# exactly as EnergyCoordinator does; the hour drives the phase machine.
_TIMES = (
    ("jun_03", datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc), "off_peak", "summer"),
    ("jun_15", datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc), "mid_peak", "summer"),
    ("jun_17", datetime(2026, 6, 15, 22, 0, tzinfo=timezone.utc), "peak", "summer"),
    ("oct_03", datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc), "off_peak", "shoulder"),
    ("oct_18", datetime(2026, 10, 15, 23, 0, tzinfo=timezone.utc), "mid_peak", "shoulder"),
)
_HOLDS = (("none", None), ("partial", 60), ("full", 70))
_SOCS = ("15", "45", "85")
_HW = ("0", "60")
_ARB = (False, True)

CASES = [
    f"{t[0]}|{h[0]}|soc{soc}|hw{hw}|arb{int(arb)}"
    for t, h, soc, hw, arb in itertools.product(_TIMES, _HOLDS, _SOCS, _HW, _ARB)
]
# Review D HIGH-1 fix-up: attain post-reboot HOLD-CURRENT (CFG leg
# unavailable at boot, latch unconsumed, arbitrage on) with NO floor —
# the fix routes a registered floor through `_reserve_action`, and must be
# byte-identical (zero actions, stamp untouched) when none is registered.
# Captured on pre-Stage-A f2ec3cb38.
CASES += [
    f"{t[0]}|none|soc{soc}|hw{hw}|arb1|hc"
    for t, soc, hw in itertools.product(_TIMES, _SOCS, _HW)
]


def _run_case(case: str, clock) -> dict:
    tlabel, hlabel, soc_s, hw_s, arb_s, *hc = case.split("|")
    t = next(x for x in _TIMES if x[0] == tlabel)
    hold = dict(_HOLDS)[hlabel]
    clock.t = t[1]
    now = clock.t.astimezone(_CDT)
    c, s = make_shell(
        clock, soc=soc_s[3:], reserve_state=hw_s[2:],
        **({"cfg_state": "unavailable"} if hc else {}),
    )
    s._arbitrage_enabled = arb_s == "arb1"
    if hc:
        s._attain_reboot_recovered = False
    if hold is not None:
        seed_inclement(
            s, now, "partial_hold" if hlabel == "partial" else "full_hold", hold,
        )
    d = s.determine_mode(t[2], t[3], now=now)
    return {
        "mode": d.get("mode"),
        "reason": d.get("reason"),
        "actions": d.get("actions"),
        "charge_from_grid": d.get("charge_from_grid"),
        "arbitrage_phase": d.get("arbitrage_phase"),
        "desired": s._last_reserve_level_desired,
        "dp_stamp": s._offpeak_drain_branch_target,
    }


@pytest.mark.parametrize("case", CASES)
def test_stage_a_sighted_noop_golden(case, clock):
    observed = json.loads(json.dumps(_run_case(case, clock)))
    if WRITE_GOLDEN:
        data = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        data[case] = observed
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        return
    golden = json.loads(GOLDEN.read_text())
    assert observed == golden[case]

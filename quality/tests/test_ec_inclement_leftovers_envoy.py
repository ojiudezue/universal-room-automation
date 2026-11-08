"""EC inclement leftovers D5 — the attain HOLD-CURRENT decision carries the
real `envoy_available` (PLANNING_ec_inclement_leftovers_2026_11.md Rev 2 §D5).

INV-E1: on any `determine_mode` call where the Envoy is telemetry-blind, the
returned dict has `envoy_available is False` — including the attain
HOLD-CURRENT literal dict (`_get_attainability_hold_current_decision`), which
bypasses `_result`. Before the fix it hard-coded True, so
`EnergyCoordinator._track_envoy_availability` reset its outage count on every
such tick and the "Envoy Offline" page never fired.

Harness: REAL BatteryStrategy + REAL EnergyCoordinator `_track_envoy_availability`
(`_reserve_governor_harness`), frozen clock.
"""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _CDT,
    _SOC,
    _st,
    clock,
    make_shell,
)
from ec_phalanx_entities import (
    PHALANX_CHARGE_FROM_GRID_ENTITY,
    PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
)

from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

_UTC = timezone.utc
OCT_03 = datetime(2026, 10, 15, 8, 0, tzinfo=_UTC)   # 03:00 CDT, shoulder off_peak

_ENERGY_BATTERY = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
    / "domain_coordinators" / "energy_battery.py"
)


def _shell(clock, *, degraded: bool, site: str):
    """Attain HOLD-CURRENT shell. `site`:
    - "defer": reboot-recovery defer (latch unconsumed, CFG unavailable);
    - "warmup": rate-window warm-up (latch consumed, attain latched
      `charging`, CFG on, no rate samples)."""
    clock.t = OCT_03
    cfg = "unavailable" if site == "defer" else "on"
    c, s = make_shell(
        clock, soc=("unavailable" if degraded else "45"),
        reserve_state="40", cfg_state=cfg,
        peak_buffer_target=(30 if site == "defer" else 80),
    )
    s.reserve_soc = 20
    s._tou = TOURateEngine()
    s._arbitrage_enabled = True
    s._last_reserve_level_desired = None
    s._last_reserve_level = 40
    if site == "defer":
        s._attain_reboot_recovered = False
    else:
        _st(c.hass, PHALANX_CHARGE_FROM_GRID_ENTITY, "on", lu=clock.t)
        _st(c.hass, PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY, "on",
            lu=clock.t)
        s._attain_reboot_recovered = True
        s._attain_state = "charging"
        # A readable panel net-power (e.g. a non-Envoy meter) — otherwise
        # the degraded continuation fails closed to HOLD before warm-up.
        _np = "sensor.leftovers_panel_net_power"
        s._entities["net_power"] = _np
        _st(c.hass, _np, "500", unit="W", lu=clock.t)
    if degraded:
        # Envoy SOC entity unavailable; SOC resolves from the last good
        # reading (fallback tier) → degraded, not fully blind.
        s._soc_lkg = 45.0
        s._soc_lkg_at = clock.t - timedelta(seconds=30)
    # Coordinator outage-tracker state (production __init__ defaults).
    c._envoy_unavailable_count = 0
    c._envoy_last_available = None
    c._envoy_degraded = False
    c._envoy_degraded_since = None
    c._decision_interval = 5
    return c, s


def _decide(s):
    return s.determine_mode("off_peak", "shoulder", now=OCT_03.astimezone(_CDT))


@pytest.mark.parametrize("site", ["defer", "warmup"])
def test_attain_hold_current_degraded_reports_envoy_unavailable(clock, site):
    c, s = _shell(clock, degraded=True, site=site)
    d = _decide(s)
    assert "post-reboot HOLD CURRENT" in d["reason"], d["reason"]
    assert s._degraded_telemetry_source is not None
    assert d["envoy_available"] is False
    # HOLD-CURRENT itself is unchanged: no hardware command.
    assert d["actions"] == []


@pytest.mark.parametrize("site", ["defer", "warmup"])
def test_attain_hold_current_healthy_reports_envoy_available(clock, site):
    c, s = _shell(clock, degraded=False, site=site)
    d = _decide(s)
    assert "post-reboot HOLD CURRENT" in d["reason"], d["reason"]
    assert s._degraded_telemetry_source is None
    assert d["envoy_available"] is True
    assert d["actions"] == []


def test_degraded_hold_current_counts_toward_envoy_offline_page(clock):
    """Three degraded HOLD-CURRENT ticks through the REAL tracker: the count
    reaches 3, D7 degraded is set, and exactly one "Envoy Offline" page is
    sent. Pre-fix the count stayed 0 and no page fired."""
    c, s = _shell(clock, degraded=True, site="defer")
    for i in range(3):
        clock.t = OCT_03 + timedelta(minutes=5 * i)
        s._soc_lkg_at = clock.t - timedelta(seconds=30)
        d = s.determine_mode(
            "off_peak", "shoulder", now=clock.t.astimezone(_CDT),
        )
        assert "post-reboot HOLD CURRENT" in d["reason"]
        c._track_envoy_availability(d)
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert c._envoy_unavailable_count == 3
    assert c._envoy_degraded is True
    pages = [n for n in c.nm if n.get("hazard_type") == "envoy_offline"]
    assert len(pages) == 1
    assert pages[0]["title"] == "Envoy Offline"


# ---------------------------------------------------------------------------
# Whole-surface pin (review M4): every decision-shaped dict literal in
# energy_battery.py carries `envoy_available`, never as literal True.
# ---------------------------------------------------------------------------
def _decision_dict_violations(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, problem) for every `ast.Dict` whose constant keys
    include both "mode" and "actions" and whose "envoy_available" value is
    missing or `Constant(True)`."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {
            k.value: v for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        if "mode" not in keys or "actions" not in keys:
            continue
        val = keys.get("envoy_available")
        if val is None:
            out.append((node.lineno, "missing"))
        elif isinstance(val, ast.Constant) and val.value is True:
            out.append((node.lineno, "literal_true"))
    return out


def _decision_dict_count(tree: ast.AST) -> int:
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            ks = {k.value for k in node.keys
                  if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if {"mode", "actions"} <= ks:
                n += 1
    return n


def test_decision_dicts_carry_non_literal_envoy_available():
    tree = ast.parse(_ENERGY_BATTERY.read_text())
    # Today: HOLD-CURRENT, the fully-blind dict, `_result`. A new one must
    # be reviewed against this pin.
    assert _decision_dict_count(tree) == 3
    assert _decision_dict_violations(tree) == []


def test_decision_dict_predicate_self_test():
    src = (
        "a = {'mode': 'x', 'actions': []}\n"                              # missing
        "b = {'mode': 'x', 'actions': [], 'envoy_available': True}\n"     # literal
        "c = {'mode': 'x', 'actions': [], 'envoy_available': ok()}\n"     # fine
        "d = {'mode': 'x', 'actions': [], 'envoy_available': False}\n"    # fine
        "e = {'mode': 'x', 'reason': 'no actions', 'envoy_available': True}\n"  # not a decision
    )
    got = _decision_dict_violations(ast.parse(src))
    assert got == [(1, "missing"), (2, "literal_true")]

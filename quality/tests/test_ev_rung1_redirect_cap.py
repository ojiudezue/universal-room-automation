"""EV rung-1 redirect cap (D1) + post-pause latch hold (D2) + observability (D3).

Plan: docs/planning/PLANNING_ev_rung1_redirect_cap.md (rev 2, Tier 3).
Card: EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1.

Invariants under test (falsifiable form in plan §1):
  INV-1  rung-1 latch is taken only with fresh net_power and ev > effective
         import; the snapshotted credit equals the entry credit, which never
         exceeds clamp(ev - imp, 0, ev) / capacity * 100.
  INV-2  while latched, the `projected_rung0 < exit_band` escalation does not
         fire until the rate window's oldest sample is at/after the entry
         tick; night release, solar collapse and counterfactual stay ungated.
  INV-3  hold is bounded: prod (determine_mode, double-sampled) flushes at
         N+2; classifier-direct (single-sampled) flushes at N+3.
  INV-4  grid-charge intent / CHARGE always → pause_reason "breaker",
         dispatched before the charge_from_grid turn_on.
  INV-5  night rung / intent / gate / actions identical to develop.

Expected values are HAND-DERIVED (arithmetic in docstrings), never computed
from production helpers. net_power is stamped at WALL CLOCK (MockState
default) because `_state_age_s` compares to `dt_util.utcnow()`; only the
stale test uses an old stamp, and it carries a fresh positive control.

Fixture arithmetic (shoulder day, `_make` defaults): sunrise 07:00, sunset
19:00, boundary 17:00, capacity 40 kWh, target 80 → entry 83 / exit 77,
remaining solcast 24 kWh, solar capture 0.5. At 09:00: mins 480 (8 h);
surplus = 24 * (8/10) * 0.5 / 40 * 100 = 24.0 %.  A 2 kW credit = 5 %/h.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_battery as eb_mod,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (  # noqa: E402
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    ARBITRAGE_PHASE_CHARGE,
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)
from ec_phalanx_entities import (  # noqa: E402
    phalanx_battery_entities,
    PHALANX_CHARGE_FROM_GRID_ENTITY,
    PHALANX_GRID_ENABLED_ENTITY,
    PHALANX_RESERVE_SOC_ENTITY,
    PHALANX_SOLCAST_REMAINING_ENTITY,
    PHALANX_SOLCAST_TODAY_ENTITY,
    PHALANX_SOLCAST_TOMORROW_ENTITY,
    PHALANX_STORAGE_MODE_ENTITY,
    PHALANX_WEATHER_ENTITY,
)

_SOC = "sensor.test_r1cap_battery_soc"
_CAP = "sensor.test_r1cap_battery_capacity"
_NET = "sensor.test_r1cap_net_power"
_BPW = "sensor.test_r1cap_battery_power"
_GA, _GB = "switch.garage_a", "switch.garage_b"
_GA_P, _GB_P = "sensor.garage_a_power", "sensor.garage_b_power"
_DRAINS = {
    "excellent": 10, "good": 15, "moderate": 20, "poor": 30,
    "very_poor": 30, "unknown": 40,
}
_D = datetime(2026, 10, 1)
_BND = datetime(2026, 10, 1, 17, 0)
_T9 = datetime(2026, 10, 1, 9, 0)


class _FakeTOU:
    """Fixed next high-rate boundary; off-peak everywhere."""

    def __init__(self, boundary, period="mid_peak"):
        self.boundary = boundary
        self.period = period
        self._rates = {"shoulder": {"periods": {
            "off_peak": {"import_rate": 0.05},
            "mid_peak": {"import_rate": 0.15},
            "peak": {"import_rate": 0.25},
        }}}

    def get_next_high_rate_transition(self, now):
        return None if self.boundary is None else (self.boundary, self.period)

    def get_season(self, now=None):
        return "shoulder"

    def get_current_period(self, now=None):
        return "off_peak"

    def peak_ahead_before_offpeak(self, now=None):
        return False


@pytest.fixture(autouse=True)
def _as_local_identity(monkeypatch):
    """sun.sun ISO strings are written AS local wall clock (scoped)."""
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "as_local", lambda d: d, raising=False)
    yield


def _sun(hass, rise, sset):
    hass.set_state("sun.sun", "above_horizon",
                   attributes={"next_rising": rise, "next_setting": sset})


def _make(*, soc=30.0, target=80, boundary=_BND, today_kwh="40",
          tomorrow_kwh="40", remaining_kwh="24", lead_min=180,
          rise="2026-10-01T07:00:00+00:00", sset="2026-10-01T19:00:00+00:00"):
    hass = MockHass()
    hass.set_state(_SOC, str(soc))
    hass.set_state(_CAP, "40", attributes={"unit_of_measurement": "kWh"})
    hass.set_state(PHALANX_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(PHALANX_GRID_ENABLED_ENTITY, "on")
    hass.set_state(PHALANX_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(PHALANX_RESERVE_SOC_ENTITY, "99")
    hass.set_state(PHALANX_SOLCAST_TODAY_ENTITY, today_kwh)
    hass.set_state(PHALANX_SOLCAST_TOMORROW_ENTITY, tomorrow_kwh)
    hass.set_state(PHALANX_SOLCAST_REMAINING_ENTITY, remaining_kwh)
    hass.set_state(PHALANX_WEATHER_ENTITY, "sunny")
    _sun(hass, rise, sset)
    strat = BatteryStrategy(
        hass,
        reserve_soc=10,
        entity_config=phalanx_battery_entities() | {
            "battery_soc": _SOC, "battery_capacity": _CAP,
            "net_power": _NET, "battery_power": _BPW},
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        offpeak_drain_targets=dict(_DRAINS),
        arbitrage_enabled=True,
        peak_buffer_target=target,
        arbitrage_charge_lead_time_min=lead_min,
        arbitrage_grid_import_guard_enabled=False,
        tou_engine=_FakeTOU(boundary),
    )
    strat._inclement_config_override = {}  # no NWS → allow_discharge
    return strat, hass


def _net(hass, kw):
    """Fresh (wall-clock-stamped) net_power in W; None → unavailable."""
    if kw is None:
        hass.set_state(_NET, "unavailable")
    else:
        hass.set_state(_NET, str(kw * 1000.0),
                       attributes={"unit_of_measurement": "W"})


def _bpw(hass, kw):
    """Battery power, `kw` positive = CHARGING (strategy convention). The raw
    Envoy entity is positive = discharging; `battery_power_w` negates it
    (energy_battery.py `battery_power_w`), so the raw state is -kw."""
    if kw is None:
        hass.set_state(_BPW, "unavailable")
    else:
        hass.set_state(_BPW, str(-kw * 1000.0),
                       attributes={"unit_of_measurement": "W"})


def _seed_pre(strat, now, soc, rate=0.0):
    """Single-sampled pre-entry window: N-15, N-10, N-5 at `rate` %/h.

    The classifier's own append at N completes [N-15, N-10, N-5, N].
    """
    strat._attain_soc_history.clear()
    for back in (3, 2, 1):
        strat._record_attain_sample(
            now - timedelta(minutes=5 * back), soc - back * rate * 5.0 / 60.0,
        )


def _classify(strat, now, soc, ev_kw):
    return strat._classify_attain_rung(now, soc, ev_kw * 1000.0)


# ---------------------------------------------------------------------------
# Legacy (develop) emulation — used ONLY as a discriminator oracle.
# ---------------------------------------------------------------------------


def _install_legacy(strat):
    """Emulate develop: full EV credit (no cap) and no D2 hold.

    Inside `_classify_attain_rung` only: net_power reads fresh and the
    effective import reads 0 → redirectable == ev. Callers also reset
    `_arb_rung1_latched_at = None` before each tick (window always flushed).
    """
    import sys as _sys

    real_imp = strat._effective_import_kw
    real_fresh = strat._read_fresh_power_w

    def _imp():
        if _sys._getframe(1).f_code.co_name == "_classify_attain_rung":
            return (0.0, 0.0, 0.0)
        return real_imp()

    def _fresh(key, max_age, **kw):
        if (key == "net_power"
                and _sys._getframe(1).f_code.co_name == "_classify_attain_rung"):
            return 0.0
        return real_fresh(key, max_age, **kw)

    strat._effective_import_kw = _imp
    strat._read_fresh_power_w = _fresh


# ===========================================================================
# D1 — cap the rung-1 entry credit
# ===========================================================================


def _seed_1108(strat):
    """11-08 shape: SOC flat 30 (rate 0) on single-sampled ticks."""
    _seed_pre(strat, datetime(2026, 11, 8, 14, 3), 30.0, 0.0)


def _make_1108(**kw):
    """11-08 14:03 CST: target 90 (entry 93 / exit 87), boundary 17:00
    mid_peak, sunrise 06:48, sunset 17:36, lead 150 → window opens 14:30.

    surplus = 3 kWh * (177 / 213) * 0.5 / 40 * 100 = 3.12 %
    p0 = 30 + 0 * 2.95 h + 3.12 = 33.1 < 93 → rung 0 fails.
    develop (full credit 10.1 kW = 25.25 %/h): p1 = 30 + 25.25 * 2.95 + 3.12
    = 107.6 → clamp 100 ≥ 93 → rung_1.
    """
    return _make(soc=30.0, target=90, boundary=datetime(2026, 11, 8, 17, 0),
                 today_kwh="40", tomorrow_kwh="40", remaining_kwh="3",
                 lead_min=150, rise="2026-11-08T06:48:00+00:00",
                 sset="2026-11-08T17:36:00+00:00", **kw)


def test_rung1_cap_1108_replay_grid_fed_ev_no_entry():
    """ev 10.1, net 12.9 fresh, batt 0 → redirectable = clamp(10.1-12.9) = 0
    → rung_2, latch False, intent breaker. Discriminator: same inputs with a
    solar-fed net (0 kW) → rung_1 (proves the cap, not the fixture, moved it).
    """
    now = datetime(2026, 11, 8, 14, 3)
    strat, hass = _make_1108()
    _net(hass, 12.9)
    _bpw(hass, 0.0)
    _seed_1108(strat)
    r = strat.determine_mode("off_peak", "shoulder", now=now, ev_load_w=10100.0)
    assert strat._arb_last_projection_rung0 < 93  # rung 0 must fail
    assert strat._arb_last_rung == "rung_2"
    assert strat._arb_rung1_latch is False
    assert strat._arbitrage_intent == "breaker"
    assert strat._arb_last_redirectable_kw == 0.0
    assert r["arbitrage_phase"] != ARBITRAGE_PHASE_CHARGE  # window not open

    ctl, chass = _make_1108()
    _net(chass, 0.0)
    _bpw(chass, 0.0)
    _seed_1108(ctl)
    ctl.determine_mode("off_peak", "shoulder", now=now, ev_load_w=10100.0)
    assert ctl._arb_last_rung == "rung_1"
    assert ctl._arb_last_redirectable_kw == 10.1


def test_rung1_cap_ev_below_import():
    """Case 2: ev 3, net 5 → credit 0 → rung_2 (09:00 shape, p0 54)."""
    strat, hass = _make()
    _net(hass, 5.0)
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 3.0) == "rung_2"
    assert strat._arb_last_redirectable_kw == 0.0
    assert strat._arb_rung1_latch is False


def test_rung1_cap_net_power_none_no_entry():
    """Case 4: net_power unavailable → no credit → rung_2.
    Control: a fresh net of 0 kW → full 2 kW credit → p1 = 30+5*8+24 = 94."""
    strat, hass = _make()
    _net(hass, None)
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 2.0) == "rung_2"
    assert strat._arb_last_redirectable_kw == 0.0
    ctl, chass = _make()
    _net(chass, 0.0)
    _seed_pre(ctl, _T9, 30.0)
    assert _classify(ctl, _T9, 30.0, 2.0) == "rung_1"
    assert ctl._arb_last_projection_rung1 == 94.0


def _set_stale_net(hass, kw, age_s):
    from datetime import timezone as _tz
    hass.set_state_with_time(
        _NET, str(kw * 1000.0), {"unit_of_measurement": "W"},
        datetime.now(_tz.utc) - timedelta(seconds=age_s),
    )


@pytest.fixture
def _aware_utcnow(monkeypatch):
    """Some sibling stubs install a NAIVE `utcnow`; `_state_age_s` then
    swallows the aware/naive TypeError and treats the stamp as fresh. Pin
    an aware wall-clock utcnow for the staleness tests (scoped)."""
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "utcnow",
                        lambda: datetime.now(timezone.utc), raising=False)
    yield


def test_rung1_cap_net_power_stale_no_entry_with_fresh_control(_aware_utcnow):
    """Case 5: net frozen at -2 kW, 600 s old (> 180 s) → no credit → rung_2.
    Positive control: identical inputs with a fresh stamp → rung_1 (the
    -2 kW export gives the full 2 kW credit)."""
    strat, hass = _make()
    _set_stale_net(hass, -2.0, 600)
    assert strat._read_fresh_power_w("net_power", 180) is None  # precondition
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 2.0) == "rung_2"
    assert strat._arb_last_redirectable_kw == 0.0
    ctl, chass = _make()
    _set_stale_net(chass, -2.0, 1)
    _seed_pre(ctl, _T9, 30.0)
    assert _classify(ctl, _T9, 30.0, 2.0) == "rung_1"
    assert ctl._arb_last_redirectable_kw == 2.0


def test_rung1_cap_kill_switch_zero_trusts_value(_aware_utcnow, monkeypatch):
    """Case 5b: DEFAULT_NET_POWER_MAX_AGE_S = 0 disables the gate (INV-1
    carve-out): the same 600 s-old -2 kW value is trusted → rung_1."""
    monkeypatch.setattr(eb_mod, "DEFAULT_NET_POWER_MAX_AGE_S", 0)
    strat, hass = _make()
    _set_stale_net(hass, -2.0, 600)
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 2.0) == "rung_1"
    assert strat._arb_last_redirectable_kw == 2.0


def test_rung1_cap_export_full_credit():
    """Case 6: exporting (net -3, ev 7) → credit min(7, 7+3) = 7 kW."""
    strat, hass = _make()
    _net(hass, -3.0)
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 7.0) == "rung_1"
    assert strat._arb_last_redirectable_kw == 7.0
    # 7 kW / 40 kWh * 100 = 17.5 %/h snapshotted.
    assert strat._arb_last_ev_load_pct_per_h == pytest.approx(17.5)


def test_rung1_cap_two_evs_summed():
    """Case 8: two EVs 6 + 5 kW via the real pool sum, net 8 → credit 3 kW
    (7.5 %/h); p1 = 30 + 7.5*8 + 24 = 114 → 100 → rung_1; the redirect pause
    turns BOTH chargers off."""
    strat, hass = _make()
    _net(hass, 8.0)
    pool = _pool(hass, a_kw=6.0, b_kw=5.0)
    ev_w = pool.current_charging_load_w()
    assert ev_w == 11000.0
    _seed_pre(strat, _T9, 30.0)
    assert strat._classify_attain_rung(_T9, 30.0, ev_w) == "rung_1"
    assert strat._arb_last_redirectable_kw == 3.0
    assert strat._arb_last_ev_load_pct_per_h == pytest.approx(7.5)
    offs = pool.determine_arbitrage_actions(
        arbitrage_charging=True, tou_period="off_peak", pause_reason="redirect")
    assert sorted(a["target"] for a in offs) == [_GA, _GB]


def test_rung1_cap_battery_power_none_conservative():
    """Case 10: battery charging 4 kW, net 6, ev 7. Fresh battery_power:
    imp = 6 - 4 = 2 → credit 5. battery_power unavailable → imp = net 6 →
    credit 1 (smaller, conservative)."""
    strat, hass = _make()
    _net(hass, 6.0)
    _bpw(hass, 4.0)
    _seed_pre(strat, _T9, 30.0)
    _classify(strat, _T9, 30.0, 7.0)
    assert strat._arb_last_redirectable_kw == 5.0
    s2, h2 = _make()
    _net(h2, 6.0)
    _bpw(h2, None)
    _seed_pre(s2, _T9, 30.0)
    _classify(s2, _T9, 30.0, 7.0)
    assert s2._arb_last_redirectable_kw == 1.0


def test_rung1_cap_battery_discharge_credit():
    """Case 9: battery discharging 5 kW, ev 10, house 2, solar 1 → net =
    2 + 10 - 1 - 5 = 6. Discharge is not subtracted (max(0, -5) = 0) →
    imp 6 → credit 4 kW (the avoided discharge is the SOC effect)."""
    strat, hass = _make()
    _net(hass, 6.0)
    _bpw(hass, -5.0)
    _seed_pre(strat, _T9, 30.0)
    _classify(strat, _T9, 30.0, 10.0)
    assert strat._arb_last_redirectable_kw == 4.0


def test_rung1_cap_snapshot_equals_entry_credit():
    """INV-1: the snapshot used by the counterfactual equals the capped
    entry credit: ev 7, net 5 → credit 2 kW → 5.0 %/h (not 17.5)."""
    strat, hass = _make()
    _net(hass, 5.0)
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 7.0) == "rung_1"
    assert strat._arb_last_ev_load_pct_per_h == pytest.approx(5.0)
    assert strat._arb_last_redirectable_kw == 2.0


def test_case_03_daylight_solar_zero_no_entry():
    """Case 3: daylight, solcast remaining 0 → surplus 0 < 0.5 → rung_2 via
    the no-solar guard even with a full (solar-fed) credit."""
    strat, hass = _make(remaining_kwh="0", today_kwh="0", tomorrow_kwh="0")
    _net(hass, 0.0)
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 7.0) == "rung_2"
    assert strat._arb_rung1_latch is False


def test_case_07_ev_estimate_bounded():
    """Case 7: power sensor unavailable, switch status 'charging' → the
    pool's fallback estimate E is the EV draw; credit is clamped to <= E."""
    strat, hass = _make()
    hass.set_state(_GA, "on", attributes={"status": "charging"})
    hass.set_state(_GA_P, "unavailable")
    pool = EVChargerController(hass, evse_config={"garage_a": {
        "switch": _GA, "power": _GA_P}})
    est_w = pool.current_charging_load_w()
    assert est_w > 0
    _net(hass, -50.0)  # huge export: credit still bounded by the estimate
    _seed_pre(strat, _T9, 30.0)
    strat._classify_attain_rung(_T9, 30.0, est_w)
    assert strat._arb_last_redirectable_kw == round(est_w / 1000.0, 2)


# ===========================================================================
# D2 — hold the latch until the rate window is all post-pause
# ===========================================================================


def _enter_direct(strat, hass, soc=30.0):
    """Entry at N = 09:00 with a solar-fed 2 kW EV (net 0): p0 54, p1 94."""
    _net(hass, 0.0)
    _seed_pre(strat, _T9, soc)
    assert _classify(strat, _T9, soc, 2.0) == "rung_1"
    assert strat._arb_rung1_latched_at == _T9


def _tick(n):
    return _T9 + timedelta(minutes=5 * n)


def test_rung1_hold_flat_rate_escalates_exactly_at_flush_direct():
    """Case 20, classifier-direct (single-sampled): window at N+1 =
    [N-10,N-5,N,N+1], N+2 = [N-5,N,N+1,N+2] → held; N+3 = [N..N+3] →
    flushed. Flat SOC: p0 = 30 + 0 + ~24 = ~54 < exit 77; cf < 83 → rung_2
    EXACTLY at N+3."""
    strat, hass = _make()
    _enter_direct(strat, hass)
    assert _classify(strat, _tick(1), 30.0, 0.0) == "rung_1"
    assert _classify(strat, _tick(2), 30.0, 0.0) == "rung_1"
    assert _classify(strat, _tick(3), 30.0, 0.0) == "rung_2"
    assert strat._arb_rung1_latch is False


def test_rung1_hold_held_tick_below_exit_band():
    """M4 anchor (R2-F3): at N+1 the held tick provably projects below exit
    (precondition), yet returns rung_1. Control: same sequence with
    latched_at forced None (develop behaviour) → rung_2 at N+1."""
    strat, hass = _make()
    _enter_direct(strat, hass)
    r = _classify(strat, _tick(1), 30.0, 0.0)
    assert strat._arb_last_projection_rung0 < 80 - 3  # below exit band
    assert r == "rung_1"

    ctl, chass = _make()
    _enter_direct(ctl, chass)
    ctl._arb_rung1_latched_at = None
    assert _classify(ctl, _tick(1), 30.0, 0.0) == "rung_2"


def test_rung1_hold_latched_at_none_legacy():
    """Case 18: latched with latched_at None (e.g. a latch set by a path
    that never stamped it) → treated as flushed → develop escalation."""
    strat, hass = _make()
    _net(hass, 0.0)
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    strat._arb_rung1_latched_at = None
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 0.0) == "rung_2"


def test_rung1_hold_does_not_gate_night_release():
    """Night release stays ungated: latched (unflushed) at 06:30 → the
    pre-sunrise release clears the latch on the very next tick."""
    strat, hass = _make()
    _net(hass, 0.0)
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    night = datetime(2026, 10, 1, 6, 30)
    strat._arb_rung1_latched_at = night  # unflushed: window predates it
    _seed_pre(strat, night, 30.0)
    assert _classify(strat, night, 30.0, 0.0) == "rung_2"
    assert strat._arb_rung1_latch is False


def test_rung1_hold_does_not_gate_solar_collapse():
    """Solar collapse exit stays ungated: entry at N, then remaining solcast
    drops to 0 at N+1 (unflushed) → surplus 0 < 0.5 → rung_2 at N+1."""
    strat, hass = _make()
    _enter_direct(strat, hass)
    hass.set_state(PHALANX_SOLCAST_REMAINING_ENTITY, "0")
    hass.set_state(PHALANX_SOLCAST_TODAY_ENTITY, "0")
    assert _classify(strat, _tick(1), 30.0, 0.0) == "rung_2"
    assert strat._arb_rung1_latch is False
    assert strat._arb_last_ev_load_pct_per_h == 0.0


def test_rung1_hold_does_not_gate_counterfactual_rung0():
    """Counterfactual exit stays ungated: at N+1 (unflushed window
    [N-10, N-5, N, N+1]) SOC reads 60 → rate = 30 % / 15 min = 120 %/h →
    cf = 60 + (120 - 5) * 7.92 + ~23.8 → clamp 100 ≥ 83 → rung_0 at N+1."""
    strat, hass = _make()
    _enter_direct(strat, hass)
    assert _classify(strat, _tick(1), 60.0, 0.0) == "rung_0"
    assert strat._arb_rung1_latch is False
    assert strat._arb_rung0_latch is True


def test_rung1_hold_window_cleared_midlatch():
    """Case 13: window cleared mid-latch → <2 samples → cold-boot rung_2
    (develop). After a reseed of post-entry samples the window is flushed."""
    strat, hass = _make()
    _enter_direct(strat, hass)
    strat._attain_soc_history.clear()
    assert _classify(strat, _tick(1), 30.0, 0.0) == "rung_2"
    assert strat._arb_rung1_latch is True  # cold-boot return precedes latch
    # Reseed with post-entry samples only → flushed → flat → escalate.
    strat._record_attain_sample(_tick(1), 30.0)
    assert _classify(strat, _tick(2), 30.0, 0.0) == "rung_2"
    assert strat._arb_rung1_latch is False


def test_case_12_soc_none_while_latched():
    """Case 12: SOC None while latched → early rung_2 (develop); latch kept."""
    strat, hass = _make()
    _enter_direct(strat, hass)
    assert strat._classify_attain_rung(_tick(1), None, 0.0) == "rung_2"
    assert strat._arb_rung1_latch is True


def test_case_14_target_le_soc_while_latched():
    """Case 14: SOC >= target while latched → early rung_2 (HOLD path)."""
    strat, hass = _make()
    _enter_direct(strat, hass)
    assert _classify(strat, _tick(1), 80.0, 0.0) == "rung_2"


# ---------------------------------------------------------------------------
# Production path (determine_mode → _gate_is_open → energy.py dispatch →
# determine_arbitrage_actions on the REAL pool).
# ---------------------------------------------------------------------------


class _Coord:
    """Stand-in for the two EnergyCoordinator dispatch helpers' surface.

    The pause-reason derivation, breaker ordering and arbitrage release are
    the REAL unbound methods; dispatched switch actions are applied to hass
    so the next tick sees the new EV state (power + net)."""

    def __init__(self, strat, pool, hass, ev_kw_each, house_kw):
        self._battery = strat
        self._ev = pool
        self.hass = hass
        self._pool = MagicMock()
        self._pool.determine_actions = MagicMock(return_value=[])
        self._ev_tou_enabled = False
        self.dispatched = []
        self._ev_kw_each = ev_kw_each
        self._house_kw = house_kw

    def _cfg_ledger_says_on(self):
        return False

    def _cfg_off_read_fresh(self, eid):
        return False

    def _note_cfg_unknown_forced(self, *a, **k):
        return None

    def _cfg_write_leg_provably_off(self):
        return True

    async def _tap_write_verifier(self, *a, **k):
        return None

    async def _execute_service_action(self, spec):
        self.dispatched.append(dict(spec))
        tgt = str(spec.get("target", ""))
        svc = spec.get("service")
        for sw, p in ((_GA, _GA_P), (_GB, _GB_P)):
            if tgt == sw and svc in ("switch.turn_off", "switch.turn_on"):
                on = svc == "switch.turn_on"
                self.hass.set_state(sw, "on" if on else "off")
                self.hass.set_state(
                    p, str(self._ev_kw_each * 1000.0 if on else 0.0),
                    attributes={"unit_of_measurement": "W"})
        if "charge_from_grid" in tgt and svc in ("switch.turn_on", "switch.turn_off"):
            self.hass.set_state(PHALANX_CHARGE_FROM_GRID_ENTITY,
                                "on" if svc == "switch.turn_on" else "off")
        self._refresh_net()

    def _refresh_net(self):
        ev = self._ev.current_charging_load_w() / 1000.0
        _net(self.hass, self._house_kw + ev)


def _pool(hass, a_kw=None, b_kw=None):
    cfg = {}
    for eid, sw, p, kw in (("garage_a", _GA, _GA_P, a_kw),
                           ("garage_b", _GB, _GB_P, b_kw)):
        if kw is None:
            continue
        cfg[eid] = {"switch": sw, "power": p}
        hass.set_state(sw, "on" if kw > 0 else "off")
        hass.set_state(p, str(kw * 1000.0), attributes={"unit_of_measurement": "W"})
    return EVChargerController(hass, evse_config=cfg)


async def _run_tick(coord, now):
    strat = coord._battery
    ev_w = coord._ev.current_charging_load_w()
    decision = strat.determine_mode("off_peak", "shoulder", now=now, ev_load_w=ev_w)
    start = len(coord.dispatched)
    pr, preq, gci = await EnergyCoordinator._execute_breaker_safe_dispatch(
        coord, decision, "off_peak")
    await EnergyCoordinator._dispatch_post_decision_tou_and_arbitrage(
        coord, period="off_peak", pause_reason=pr, pause_requested=preq,
        grid_charge_intent=gci)
    return {
        "rung": strat._arb_last_rung, "intent": strat._arbitrage_intent,
        "gate": strat._arb_last_gate_outcome,
        "phase": decision["arbitrage_phase"], "pause_reason": pr,
        "cfg": decision.get("charge_from_grid", False),
        "actions": coord.dispatched[start:], "decision": decision,
    }


def _ev_svc(tick, svc):
    return [a for a in tick["actions"]
            if a.get("service") == svc and a.get("target") in (_GA, _GB)]


def _prod_setup(*, ev_kw_each=1.0, house_kw=0.0, soc=30.0, **mk):
    """Two chargers, `ev_kw_each` each; net = house + EV (house <= 0 means
    solar covers the EV). Pre-entry window single-sampled at N-15..N-5."""
    strat, hass = _make(soc=soc, **mk)
    pool = _pool(hass, a_kw=ev_kw_each, b_kw=ev_kw_each)
    coord = _Coord(strat, pool, hass, ev_kw_each, house_kw)
    coord._refresh_net()
    return strat, hass, coord


@pytest.mark.asyncio
async def test_rung1_hold_flat_rate_escalates_exactly_at_flush_prod():
    """Case 20 prod (R2-F2 / M5 anchor). EV 2 x 1 kW solar-fed (house -2 →
    net 0) → entry at N (p1 94). Double-sampled: N → [N-10,N-5,N,N];
    N+1 classify → [N-5,N,N,N+1] held; attain → [N,N,N+1,N+1];
    N+2 classify → [N,N+1,N+1,N+2] flushed. Flat SOC → p0 ~54 < 77 →
    rung_1 at N+1, rung_2 EXACTLY at N+2 with the EV release (turn_on)."""
    strat, hass, coord = _prod_setup(house_kw=-2.0)
    _seed_pre(strat, _T9, 30.0)
    t0 = await _run_tick(coord, _tick(0))
    assert (t0["rung"], t0["pause_reason"]) == ("rung_1", "redirect")
    assert len(_ev_svc(t0, "switch.turn_off")) == 2
    t1 = await _run_tick(coord, _tick(1))
    assert t1["rung"] == "rung_1"
    assert _ev_svc(t1, "switch.turn_on") == []
    t2 = await _run_tick(coord, _tick(2))
    assert t2["rung"] == "rung_2"
    assert len(_ev_svc(t2, "switch.turn_on")) == 2


@pytest.mark.asyncio
async def test_rung1_hold_genuine_redirect_no_flap_prod():
    """Case 19 prod: EV 2 x 2.5 kW solar-fed (house -5 → net 0; credit 5 kW
    = 12.5 %/h; p1 = 30 + 12.5*8 + 24 → 100 ≥ 83). Pre-pause SOC flat;
    post-pause SOC rises 0.5 % per tick (6 %/h).
    N+1 (held): window [N-5,N,N,N+1] → rate 0.5/10min = 3 %/h →
      p0 = 30.5 + 3*7.92 + ~23.8 = ~78 ... held regardless → rung_1.
    N+2 (flushed): [N,N+1,N+1,N+2] → 1.0/10min = 6 %/h → p0 ≈ 31+47.0+23.7
      ≫ 77; cf = 31 + (6-12.5)*7.83 + 23.7 = 3.8 < 83 → rung_1.
    No EV turn_on at any tick (no flap); exactly one pause."""
    strat, hass, coord = _prod_setup(ev_kw_each=2.5, house_kw=-5.0)
    _seed_pre(strat, _T9, 30.0)
    socs = [30.0, 30.5, 31.0, 31.5, 32.0]
    ticks = []
    for n, s in enumerate(socs):
        hass.set_state(_SOC, str(s))
        ticks.append(await _run_tick(coord, _tick(n)))
    assert [t["rung"] for t in ticks] == ["rung_1"] * 5
    assert sum(len(_ev_svc(t, "switch.turn_off")) for t in ticks) == 2
    assert sum(len(_ev_svc(t, "switch.turn_on")) for t in ticks) == 0


@pytest.mark.asyncio
async def test_rung1_hold_charge_window_opens_during_hold():
    """Case 21: lead 475 min → window opens at 09:05 (17:00 - 7h55m). Entry
    at N=09:00 (rung_1, gate closed). N+1 is held → rung_1 → gate closed →
    NO arbitrage CHARGE, no CFG turn_on. N+2 flushes → rung_2 → gate open →
    CHARGE, breaker pause dispatched BEFORE the CFG turn_on. CHARGE is
    delayed exactly one tick (develop: CHARGE at N+1)."""
    strat, hass, coord = _prod_setup(house_kw=-2.0, lead_min=475)
    _seed_pre(strat, _T9, 30.0)
    t0 = await _run_tick(coord, _tick(0))
    assert t0["rung"] == "rung_1"
    t1 = await _run_tick(coord, _tick(1))
    assert t1["rung"] == "rung_1"
    assert t1["gate"] == "closed_rung_1"
    assert t1["phase"] != ARBITRAGE_PHASE_CHARGE  # no arbitrage CHARGE
    # On this fixture the attain branch (gate closed) commands grid on the
    # held tick: INV-2/INV-4 — that grid pull is paused as "breaker".
    assert t1["cfg"] is True
    assert t1["pause_reason"] == "breaker"
    assert _ev_svc(t1, "switch.turn_on") == []
    t2 = await _run_tick(coord, _tick(2))
    assert t2["rung"] == "rung_2"
    assert t2["phase"] == ARBITRAGE_PHASE_CHARGE
    assert t2["pause_reason"] == "breaker"
    assert _ev_svc(t2, "switch.turn_on") == []

    # Discriminator: develop (no hold) → CHARGE at N+1.
    dev, dhass, dcoord = _prod_setup(house_kw=-2.0, lead_min=475)
    _install_legacy(dev)
    _seed_pre(dev, _T9, 30.0)
    await _run_tick(dcoord, _tick(0))
    dev._arb_rung1_latched_at = None
    d1 = await _run_tick(dcoord, _tick(1))
    assert d1["phase"] == ARBITRAGE_PHASE_CHARGE


# ===========================================================================
# D3 — observability
# ===========================================================================


def test_rung1_redirectable_kw_none_on_boot_gate_closed():
    """Fresh boot, forecast gate closed (good day) → attr None, no error."""
    strat, hass = _make(today_kwh="90", tomorrow_kwh="90", remaining_kwh="90")
    _net(hass, 0.0)
    strat.determine_mode("off_peak", "shoulder", now=_T9, ev_load_w=2000.0)
    assert strat._arb_last_gate_outcome == "closed_forecast"
    st = strat.get_status()
    assert "arb_rung1_redirectable_kw" in st
    assert st["arb_rung1_redirectable_kw"] is None


def test_rung1_redirectable_kw_value_on_entry_tick():
    """Entry tick (ev 7, net 5) → 2.0 on the status surface."""
    strat, hass = _make()
    _net(hass, 5.0)
    _seed_pre(strat, _T9, 30.0)
    strat.determine_mode("off_peak", "shoulder", now=_T9, ev_load_w=7000.0)
    assert strat._arb_last_rung == "rung_1"
    assert strat.get_status()["arb_rung1_redirectable_kw"] == 2.0


def test_rung1_redirectable_kw_reset_on_peak_tick():
    """Set on an entry tick, then a peak tick (early return, classifier not
    called) → None (per-tick entry reset)."""
    strat, hass = _make()
    _net(hass, 5.0)
    _seed_pre(strat, _T9, 30.0)
    strat.determine_mode("off_peak", "shoulder", now=_T9, ev_load_w=7000.0)
    assert strat._arb_last_redirectable_kw == 2.0
    strat.determine_mode("peak", "shoulder", now=_tick(1), ev_load_w=7000.0)
    assert strat._arb_last_redirectable_kw is None
    assert strat.get_status()["arb_rung1_redirectable_kw"] is None


def test_rung1_redirectable_kw_none_while_latched():
    """Latched tick (held) never reaches the entry evaluation → None."""
    strat, hass = _make()
    _net(hass, 5.0)
    _seed_pre(strat, _T9, 30.0)
    strat.determine_mode("off_peak", "shoulder", now=_T9, ev_load_w=7000.0)
    assert strat._arb_rung1_latch is True
    strat.determine_mode("off_peak", "shoulder", now=_tick(1), ev_load_w=0.0)
    assert strat._arb_last_rung == "rung_1"
    assert strat._arb_last_redirectable_kw is None


# ===========================================================================
# D4 — replays + breaker matrix + extremes
# ===========================================================================


@pytest.mark.asyncio
async def test_replay_1108_no_arbitrage_toggle_before_charge():
    """11-08 14:03-14:33 CST, 7 ticks, garage_a + garage_b 5.05 kW each
    (10.1 kW), house 2.8 kW → net 12.9 with EVs on. Window opens 14:30.
    Fixed: zero EV switch actions before 14:30; at 14:30 the CHARGE tick
    dispatches the breaker pause (2 turn_off) BEFORE the CFG turn_on.
    Develop (legacy emulation): >= 3 arbitrage turn_off and >= 2 turn_on
    before 14:30 (the observed off->on->off loop)."""
    ticks = [datetime(2026, 11, 8, 14, 3) + timedelta(minutes=5 * i)
             for i in range(7)]

    async def _run(legacy):
        strat, hass = _make_1108()
        _bpw(hass, 0.0)
        pool = _pool(hass, a_kw=5.05, b_kw=5.05)
        coord = _Coord(strat, pool, hass, 5.05, 2.8)
        coord._refresh_net()
        if legacy:
            _install_legacy(strat)
        _seed_1108(strat)
        out = []
        for t in ticks:
            if legacy:
                strat._arb_rung1_latched_at = None
            out.append((t, await _run_tick(coord, t)))
        return out

    fixed = await _run(False)
    pre = [r for t, r in fixed if t < datetime(2026, 11, 8, 14, 30)]
    assert len(pre) == 6
    assert all(_ev_svc(r, "switch.turn_off") == [] for r in pre)
    assert all(_ev_svc(r, "switch.turn_on") == [] for r in pre)
    assert all(r["rung"] == "rung_2" for r in pre)
    _t, at = fixed[-1]
    assert at["phase"] == ARBITRAGE_PHASE_CHARGE
    assert at["pause_reason"] == "breaker"
    acts = at["actions"]
    off_idx = [i for i, a in enumerate(acts) if a.get("service") == "switch.turn_off"
               and a.get("target") in (_GA, _GB)]
    cfg_idx = [i for i, a in enumerate(acts) if a.get("service") == "switch.turn_on"
               and "charge_from_grid" in str(a.get("target"))]
    assert len(off_idx) == 2 and cfg_idx
    assert max(off_idx) < min(cfg_idx)

    legacy = await _run(True)
    lpre = [r for t, r in legacy if t < datetime(2026, 11, 8, 14, 30)]
    offs = sum(len(_ev_svc(r, "switch.turn_off")) for r in lpre)
    ons = sum(len(_ev_svc(r, "switch.turn_on")) for r in lpre)
    assert offs >= 3 * 2 and ons >= 2 * 2, (offs, ons)


def test_replay_1001_daylight_grid_fed_no_entry():
    """10-01 shape shifted into daylight: EV 11.6 kW, import 17.7 kW at
    09:00 → credit 0 → rung_2. Develop (legacy) → rung_1 (p1 = 30 + 29*8 +
    24 → 100)."""
    strat, hass = _make()
    _net(hass, 17.7)
    _seed_pre(strat, _T9, 30.0)
    assert _classify(strat, _T9, 30.0, 11.6) == "rung_2"
    assert strat._arb_last_redirectable_kw == 0.0
    dev, dhass = _make()
    _net(dhass, 17.7)
    _install_legacy(dev)
    _seed_pre(dev, _T9, 30.0)
    assert _classify(dev, _T9, 30.0, 11.6) == "rung_1"


def test_replay_1001_night_rung_intent_actions_identical(monkeypatch):
    """INV-5 on the real 10-01 recorder replay: every pre-sunrise /
    post-sunset tick has the same rung, intent, gate outcome, phase,
    charge_from_grid and battery actions as the develop emulation (full
    EV credit, no hold). Display attrs are NOT compared (INV-5 scope)."""
    from test_ec_daylight_horizon_poor_night_floor import _replay

    new = _replay(monkeypatch)
    old = _replay(monkeypatch, legacy_cap=True)
    assert [o["t"] for o in new] == [o["t"] for o in old]
    night = [(n, o) for n, o in zip(new, old)
             if not (n["sunrise"] <= n["t"] < n["sunset"])]
    assert len(night) > 100
    keys = ("rung", "intent", "gate", "phase", "cfg", "reserve", "actions")
    diffs = [(n["t"], k, n[k], o[k]) for n, o in night for k in keys
             if n[k] != o[k]]
    assert diffs == []


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["latched_unflushed", "latched_flushed",
                                   "cap_zero", "no_latch"])
@pytest.mark.parametrize("trigger", ["grid_charge_intent", "phase_charge"])
async def test_breaker_always_pauses_matrix(state, trigger):
    """INV-4: whatever the rung/latch/cap state, a grid-charge decision or a
    CHARGE phase → pause_reason 'breaker', EV turn_off dispatched before the
    CFG turn_on (when one is dispatched)."""
    strat, hass = _make()
    pool = _pool(hass, a_kw=3.0, b_kw=3.0)
    coord = _Coord(strat, pool, hass, 3.0, 0.0)
    if state == "cap_zero":
        _net(hass, 20.0)
        _seed_pre(strat, _T9, 30.0)
        _classify(strat, _T9, 30.0, 6.0)
        assert strat._arb_last_redirectable_kw == 0.0
    elif state != "no_latch":
        _net(hass, 0.0)
        _seed_pre(strat, _T9, 30.0)
        assert _classify(strat, _T9, 30.0, 6.0) == "rung_1"
        if state == "latched_flushed":
            strat._arb_rung1_latched_at = _T9 - timedelta(hours=1)
        strat._arbitrage_intent = "redirect"  # rung_1 intent on this tick
    cfg = PHALANX_CHARGE_FROM_GRID_ENTITY
    decision = {
        "charge_from_grid": trigger == "grid_charge_intent",
        "arbitrage_phase": (ARBITRAGE_PHASE_CHARGE if trigger == "phase_charge"
                            else "attain"),
        "actions": [{"service": "switch.turn_on", "target": cfg, "data": {}}],
    }
    pr, preq, gci = await EnergyCoordinator._execute_breaker_safe_dispatch(
        coord, decision, "off_peak")
    assert pr == "breaker"
    acts = coord.dispatched
    off_idx = [i for i, a in enumerate(acts) if a.get("service") == "switch.turn_off"
               and a.get("target") in (_GA, _GB)]
    cfg_idx = [i for i, a in enumerate(acts) if a.get("service") == "switch.turn_on"
               and a.get("target") == cfg]
    assert len(off_idx) == 2 and cfg_idx
    assert max(off_idx) < min(cfg_idx)


@pytest.mark.parametrize("target", [30, 100])
def test_target_extremes_cap_holds(target):
    """Case 15: target extremes. Grid-fed EV (ev 7, net 9) never earns a
    credit. target 100 (entry 103), SOC 30: p0 = 30 + 24 = 54 → rung-1
    evaluated → credit 0 → rung_2. target 30 (entry 33), SOC 5: p0 = 5 + 24
    = 29 < 33 → rung-1 evaluated → credit 0 → rung_2. Control: the same
    inputs solar-fed (net 0) DO enter rung_1 (full 7 kW = 17.5 %/h)."""
    soc = 5.0 if target == 30 else 30.0
    strat, hass = _make(soc=soc, target=target)
    _net(hass, 9.0)
    _seed_pre(strat, _T9, soc)
    assert _classify(strat, _T9, soc, 7.0) == "rung_2"
    assert strat._arb_last_projection_rung0 < target + 3
    assert strat._arb_last_redirectable_kw == 0.0
    assert strat._arb_rung1_latch is False
    ctl, chass = _make(soc=soc, target=target)
    _net(chass, 0.0)
    _seed_pre(ctl, _T9, soc)
    expected = "rung_1" if target == 30 else "rung_2"  # 100: p1 clamps at 100 < 103
    assert _classify(ctl, _T9, soc, 7.0) == expected
    assert ctl._arb_last_redirectable_kw == 7.0

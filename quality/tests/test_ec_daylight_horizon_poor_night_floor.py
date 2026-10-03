"""EC daylight-gated rung horizon (D1) + poor-night WAIT drain floor (D2).

Plan: docs/planning/PLANNING_ec_daylight_horizon_and_poor_night_floor.md
(Tier 3; plan reviews #1 + #2 binding). Cards: EC-RUNG1-WAIT-EV-PINGPONG-1
and the poor-night WAIT-floor card.

Invariants under test (falsifiable form in the plan §2):
  INV-H1  pre-sunrise / post-sunset: projection_rung1_entry == projection_rung0
          (the EV term contributes exactly 0) → rung_1 is never ENTERED.
  INV-H2  daylight (sunrise <= now < sunset): projections byte-identical to
          the pre-change expression.
  INV-H3  now >= sunset: byte-identical (old code already gave 0).
  INV-W0  new WAIT reserve >= legacy WAIT reserve (reserve_soc) on every
          input; equal when every drain slider == reserve_soc (kill switch).
  INV-W1  WAIT reserve >= max(min(floor, int(soc)), reserve_soc).
  INV-W2  CHARGE / HOLD / completed-chunk HOLD unchanged; WAIT never grid
          charges (operator ruling 2026-10-03: park-only, refill = attain).
  INV-W3  partial_hold: WAIT reserve >= effective_reserve.
  INV-W4  `_offpeak_drain_branch_target` stays None on arbitrage ticks.

Expected values are HAND-DERIVED literals (arithmetic in comments), never
recomputed with the production helpers (Bug Class #62 / plan review #2 F2).
Drives the REAL `BatteryStrategy` (`_classify_attain_rung`, `determine_mode`)
and the REAL `EnergyCoordinator._tap_write_verifier` + `compose_release_floor`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_battery as eb_mod,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
    compose_release_floor,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_WEATHER_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_projector import (  # noqa: E402
    EnergyProjector,
)
from custom_components.universal_room_automation.domain_coordinators.inclement import (  # noqa: E402
    InclementDecision,
    _na_horizon,
)

_SOC = "sensor.test_ecdh_battery_soc"
_CAP = "sensor.test_ecdh_battery_capacity"
_NET = "sensor.test_ecdh_net_power"
_BPW = "sensor.test_ecdh_battery_power"
_LIVE_DRAINS = {
    "excellent": 10, "good": 15, "moderate": 20, "poor": 30,
    "very_poor": 30, "unknown": 40,
}
_CDT = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _FakeTOU:
    """Deterministic TOU stand-in: a fixed next high-rate boundary.

    Off-peak everywhere (the strategy only asks for the next transition on
    the off_peak path). Rates make mid_peak/peak >= off_peak so the attain
    lead helpers read real numbers.
    """

    def __init__(self, boundary: datetime | None, period: str = "mid_peak"):
        self.boundary = boundary
        self.period = period
        self._rates = {
            "shoulder": {"periods": {
                "off_peak": {"import_rate": 0.05},
                "mid_peak": {"import_rate": 0.15},
                "peak": {"import_rate": 0.25},
            }},
        }

    def get_next_high_rate_transition(self, now):
        if self.boundary is None:
            return None
        return (self.boundary, self.period)

    def get_season(self, now=None):
        return "shoulder"

    def get_current_period(self, now=None):
        return "off_peak"

    def peak_ahead_before_offpeak(self, now=None):
        return False


@pytest.fixture(autouse=True)
def _as_local_identity(monkeypatch):
    """`_daylight_bounds` projects sun.sun HH:MM via dt_util.as_local.

    Unit tests write sun.sun ISO strings AS local wall-clock (identity);
    the replay converts recorder UTC strings to CDT. Scoped + restored.
    """
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "as_local", lambda d: d, raising=False)
    yield


def _sun(hass, rise: str, sset: str):
    hass.set_state(
        "sun.sun", "below_horizon",
        attributes={"next_rising": rise, "next_setting": sset},
    )


def _make(
    *,
    soc: float | None = 40.0,
    reserve: int = 10,
    drains: dict | None = None,
    boundary: datetime | None = None,
    tomorrow_kwh: str = "40",      # 30 <= 40 < 50 → poor (custom thresholds)
    today_kwh: str = "40",
    remaining_kwh: str = "24",
    lead_min: int = 180,
    multi_day: bool = False,
    cap_kwh: str = "40",
    reserve_entity: str = "99",
    cls=BatteryStrategy,
):
    hass = MockHass()
    if soc is not None:
        hass.set_state(_SOC, str(soc))
    hass.set_state(_CAP, cap_kwh, attributes={"unit_of_measurement": "kWh"})
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    # Far from every emitted value so the deadband never hides the write.
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, reserve_entity)
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, today_kwh)
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, tomorrow_kwh)
    hass.set_state(DEFAULT_SOLCAST_REMAINING_ENTITY, remaining_kwh)
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    # Local wall-clock (as_local is identity in these unit tests).
    _sun(hass, "2026-10-01T07:00:00+00:00", "2026-10-01T19:00:00+00:00")
    strat = cls(
        hass,
        reserve_soc=reserve,
        entity_config={"battery_soc": _SOC, "battery_capacity": _CAP,
                       "net_power": _NET, "battery_power": _BPW},
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        offpeak_drain_targets=dict(drains if drains is not None else _LIVE_DRAINS),
        arbitrage_enabled=True,
        peak_buffer_target=80,
        arbitrage_charge_lead_time_min=lead_min,
        arbitrage_grid_import_guard_enabled=False,
        tou_engine=_FakeTOU(boundary),
        multi_day_horizon_enabled=multi_day,
    )
    strat._inclement_config_override = {}  # no NWS → allow_discharge
    return strat, hass


def _seed_rate(strat, now: datetime, soc: float, rate: float) -> None:
    """3 samples at 5-min steps ending AT now with the given %/h rate.

    The classifier appends (now, soc) itself (duplicate of the last seed —
    benign), so the observed rate is exactly `rate`.
    """
    strat._attain_soc_history.clear()
    for steps_back in (2, 1, 0):
        t = now - timedelta(minutes=5 * steps_back)
        strat._record_attain_sample(t, soc - steps_back * rate * 5.0 / 60.0)


def _legacy_rung_sunrise(strat):
    """Simulate the PRE-FIX rung site exactly: the rung classifier sees no
    sunrise (v5.17.4 discarded it), every other `_daylight_bounds` caller
    (the surplus slicer) still gets the real pair. Returns the patched fn."""
    import sys as _sys

    real = strat._daylight_bounds

    def _patched(anchor):
        sr, ss = real(anchor)
        if _sys._getframe(1).f_code.co_name == "_classify_attain_rung":
            return (None, ss)
        return (sr, ss)

    return _patched


def _classify(strat, now, soc, rate, ev_kw):
    _seed_rate(strat, now, soc, rate)
    strat._arb_last_projection_rung0 = None
    strat._arb_last_projection_rung1 = None
    rung = strat._classify_attain_rung(now, soc, ev_kw * 1000.0)
    return rung, strat._arb_last_projection_rung0, strat._arb_last_projection_rung1


def _reserve_actions(r):
    return [a["data"]["value"] for a in r["actions"]
            if a.get("service") == "number.set_value"]


def _cfg_on_actions(r):
    return [a for a in r["actions"]
            if a.get("service") == "switch.turn_on"
            and "charge_from_grid" in str(a.get("target", ""))]


# Shoulder day 2026-10-01: sunrise 07:00, sunset 19:00 (unit-test sun),
# boundary 17:00 mid_peak.
_D = datetime(2026, 10, 1)
_SHOULDER_BND = datetime(2026, 10, 1, 17, 0)
_SUMMER_BND = datetime(2026, 10, 1, 14, 0)


# ===========================================================================
# D1 — daylight-gated rate horizon
# ===========================================================================


def test_flap_shape_0114_rung1_suppressed_and_p1_equals_p0():
    """10-01 01:14 shape: SOC 9, rate 0, EV 11.6 kW, shoulder boundary 17:00.

    surplus (today branch): window [07:00, 17:00] = 10 h of 12 h daylight →
    24 kWh * 10/12 = 20 kWh * 0.5 capture = 10 kWh / 40 kWh = 25.0 %.
    rate term 0 pre-sunrise → p0 = p1 = 9 + 25 = 34.0 < 83 → rung_2.
    """
    strat, _ = _make(soc=9, boundary=_SHOULDER_BND)
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 1, 14), 9.0, 0.0, 11.6)
    assert rung == "rung_2"
    assert p0 == 34.0
    assert p1 == 34.0
    assert strat._arb_rung1_latch is False


def test_flap_shape_legacy_sunset_only_bound_latches_rung1(monkeypatch):
    """Discriminator: the SAME inputs with sunrise discarded (pre-fix
    behaviour) enter rung_1 — proves the test above is not vacuous.

    rate_hours = min(946 min, sunset-now 17h46m) = 946/60 h;
    p1 = 9 + 29 %/h * 15.77 h + 25 → clamp 100 ≥ 83 → rung_1.
    """
    strat, _ = _make(soc=9, boundary=_SHOULDER_BND)
    monkeypatch.setattr(strat, "_daylight_bounds", _legacy_rung_sunrise(strat))
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 1, 14), 9.0, 0.0, 11.6)
    assert rung == "rung_1"
    assert p1 == 100.0
    assert p0 == 34.0


@pytest.mark.parametrize("bnd", [_SUMMER_BND, _SHOULDER_BND], ids=["summer14", "shoulder17"])
@pytest.mark.parametrize("hhmm", [(0, 5), (1, 14), (6, 59), (22, 0)],
                         ids=["0005", "0114", "sunrise-1m", "2200"])
@pytest.mark.parametrize("rate", [-20.0, 0.0, 20.0])
@pytest.mark.parametrize("soc", [5.0, 30.0, 79.0])
@pytest.mark.parametrize("ev_kw", [1.0, 5.0, 11.6, 20.0])
def test_rung1_never_latches_pre_sunrise_any_ev_load(ev_kw, soc, rate, hhmm, bnd):
    """INV-H1 over the config/time matrix (pre-sunrise + post-sunset).

    22:00 is post-sunset: the boundary is the NEXT day's (summer 14:00 /
    shoulder 17:00) and the surplus comes from tomorrow's forecast (24 kWh).
    """
    now = _D.replace(hour=hhmm[0], minute=hhmm[1])
    boundary = bnd if now < bnd else bnd + timedelta(days=1)
    strat, _ = _make(soc=soc, boundary=boundary, tomorrow_kwh="24")
    rung, p0, p1 = _classify(strat, now, soc, rate, ev_kw)
    assert rung != "rung_1"
    assert strat._arb_rung1_latch is False
    assert p1 is None or p1 == p0


def test_rung_projection_daylight_byte_identical():
    """INV-H2 at 09:00 (daylight), summer boundary 14:00.

    Pre-change expression, by hand: mins 300, sunset-now 600 → 5 h.
    surplus: overlap [09:00,14:00] 5 h / remaining [09:00,19:00] 10 h →
    16 kWh * 0.5 * 0.5 = 4 kWh / 40 = 10.0 %.
    p0 = 40 + 2*5 + 10 = 60.0 ; EV 2 kW = 5 %/h → p1 = 40 + 7*5 + 10 = 85.0.
    """
    strat, _ = _make(soc=40, boundary=_SUMMER_BND, remaining_kwh="16")
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 9, 0), 40.0, 2.0, 2.0)
    assert (p0, p1) == (60.0, 85.0)
    assert rung == "rung_1"  # daylight rung_1 is legitimate (85 >= 83)


def test_rung_projection_exactly_at_sunrise_rate_counts():
    """F5: now == sunrise (07:00) is daylight → rate counts.

    mins 420 (7 h); surplus overlap [07:00,14:00] 7 h / 12 h → 24*7/12 = 14
    kWh * 0.5 = 7 kWh / 40 = 17.5 %. p0 = 20 + 1*7 + 17.5 = 44.5;
    EV 2 kW (+5 %/h) → p1 = 20 + 6*7 + 17.5 = 79.5.
    """
    strat, _ = _make(soc=20, boundary=_SUMMER_BND)
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 7, 0), 20.0, 1.0, 2.0)
    assert (p0, p1) == (44.5, 79.5)
    assert rung == "rung_2"


def test_rung_projection_one_second_before_sunrise_rate_zero():
    """F5: sunrise − 1 s → rate term 0 (pre-change would give 44.5 / 79.5).

    surplus unchanged (window starts at sunrise) = 17.5 → p0 = p1 = 37.5.
    """
    strat, _ = _make(soc=20, boundary=_SUMMER_BND)
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 6, 59, 59), 20.0, 1.0, 2.0)
    assert (p0, p1) == (37.5, 37.5)
    assert rung == "rung_2"


def test_rung_projection_one_minute_before_sunset_unchanged():
    """INV-H2 at sunset − 1 min, boundary next day 17:00.

    rate_mins = min(1321, 1) = 1 → rate 6 → +0.1; surplus: overlap
    [18:59,19:00] / remaining 1 min → whole 4 kWh * 0.5 = 2 kWh / 40 = 5.0.
    p0 = 30 + 0.1 + 5 = 35.1 ; EV 2 kW → p1 = 30 + 11/60 + 5 = 35.18 → 35.2.
    """
    strat, _ = _make(soc=30, boundary=_SHOULDER_BND + timedelta(days=1),
                     remaining_kwh="4")
    _, p0, p1 = _classify(strat, datetime(2026, 10, 1, 18, 59), 30.0, 6.0, 2.0)
    assert (p0, p1) == (35.1, 35.2)


def test_rung_projection_post_sunset_unchanged():
    """INV-H3 at exactly sunset (19:00): rate term 0 (pre- and post-change).

    tomorrow branch: [07:00, 17:00] of 12 h daylight → 24*10/12 = 20 kWh *
    0.5 = 10 kWh / 40 = 25.0 → p0 = p1 = 30 + 25 = 55.0.
    """
    strat, _ = _make(soc=30, boundary=_SHOULDER_BND + timedelta(days=1),
                     tomorrow_kwh="24")
    _, p0, p1 = _classify(strat, datetime(2026, 10, 1, 19, 0), 30.0, 6.0, 2.0)
    assert (p0, p1) == (55.0, 55.0)


def test_local_predicate_anchor_with_r7_projector_off(monkeypatch):
    """F5: R7_USE_UNIFIED_PROJECTOR=False exercises the battery-local
    `rate_hours` predicate (kill-switch branch). Same literals as the
    projector path: pre-sunrise 37.5/37.5, at sunrise 44.5/79.5, daylight
    60.0/85.0.
    """
    monkeypatch.setattr(eb_mod, "R7_USE_UNIFIED_PROJECTOR", False)
    strat, _ = _make(soc=20, boundary=_SUMMER_BND)
    _, p0, p1 = _classify(strat, datetime(2026, 10, 1, 6, 59, 59), 20.0, 1.0, 2.0)
    assert (p0, p1) == (37.5, 37.5)
    strat_at, _ = _make(soc=20, boundary=_SUMMER_BND)
    _, p0, p1 = _classify(strat_at, datetime(2026, 10, 1, 7, 0), 20.0, 1.0, 2.0)
    assert (p0, p1) == (44.5, 79.5)  # exactly at sunrise: rate counts
    strat2, _ = _make(soc=40, boundary=_SUMMER_BND, remaining_kwh="16")
    _, p0, p1 = _classify(strat2, datetime(2026, 10, 1, 9, 0), 40.0, 2.0, 2.0)
    assert (p0, p1) == (60.0, 85.0)


def test_rung1_counterfactual_site_daylight_gated():
    """Latched pre-sunrise: the night release (fix-up B/D-HIGH-1) clears the
    latch before the counterfactual site, so p1 is None (not computed).

    06:30, rate 2, soc 30, surplus 25 (shoulder, today [07:00,17:00]).
    p0 = 30 + 0 + 25 = 55.0 < entry 83 → rung_2; both latches cleared.
    """
    strat, _ = _make(soc=30, boundary=_SHOULDER_BND)
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 6, 30), 30.0, 2.0, 0.0)
    assert (p0, p1) == (55.0, None)  # ev_kw 0 → entry site not reached
    assert rung == "rung_2"
    assert strat._arb_rung1_latch is False
    assert strat._arb_last_ev_load_pct_per_h == 0.0


# ---------------------------------------------------------------------------
# Fix-up B/D-HIGH-1: a rung latch taken in daylight must not survive night.
# Repro (reviews): shoulder, poor, target 80, rung_1 latch carried, EV 2 kW
# (= 5 %/h on 40 kWh), SOC 55, surplus 25 → p0 = 55 + 0 + 25 = 80 < entry 83.
# Pre-fix: cf = 80 < 83 and p0 80 >= exit 77 → rung_1 HELD all night.
# ---------------------------------------------------------------------------

_NIGHT_CASES = [
    # 02:00 → today's boundary 17:00; surplus today [07,17] 10/12*24*.5/40=25
    (datetime(2026, 10, 1, 2, 0), _SHOULDER_BND),
    # 21:05 → next-day 17:00; surplus tomorrow (24 kWh) same slice = 25
    (datetime(2026, 10, 1, 21, 5), _SHOULDER_BND + timedelta(days=1)),
]


@pytest.mark.parametrize("now,bnd", _NIGHT_CASES, ids=["0200", "2105"])
def test_night_releases_carried_rung1_latch(now, bnd):
    strat, _ = _make(soc=55, boundary=bnd, tomorrow_kwh="24")
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    rung, p0, p1 = _classify(strat, now, 55.0, 0.0, 2.0)
    assert p0 == 80.0
    assert rung == "rung_2"
    assert p1 == 80.0  # rung-1 ENTRY (not counterfactual): EV term 0 at night
    assert strat._arb_rung1_latch is False
    assert strat._arb_rung0_latch is False
    assert strat._arb_last_ev_load_pct_per_h == 0.0


@pytest.mark.parametrize("now,bnd", _NIGHT_CASES, ids=["0200", "2105"])
def test_night_carried_rung1_latch_full_determine_mode(now, bnd):
    """Full determine_mode: gate not closed_rung_1, intent never "redirect",
    no grid charge requested → EnergyCoordinator pause_reason (energy.py
    `arb_intent == "redirect"` branch) cannot be "redirect"."""
    strat, _ = _make(soc=55, boundary=bnd, tomorrow_kwh="24")
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    _seed_rate(strat, now, 55.0, 0.0)
    r = strat.determine_mode("off_peak", "shoulder", now=now, ev_load_w=2000.0)
    assert strat._arb_last_gate_outcome != "closed_rung_1"
    assert strat._arbitrage_intent != "redirect"
    assert strat._arb_last_rung == "rung_2"
    assert strat._arb_rung1_latch is False
    assert r["arbitrage_phase"] == "wait"
    assert _cfg_on_actions(r) == []


@pytest.mark.parametrize("now,bnd", _NIGHT_CASES, ids=["0200", "2105"])
def test_night_carried_rung0_latch_kept_in_hysteresis_band(now, bnd):
    """Operator ruling: rung_0 latch/hysteresis KEPT at night. p0 = 55 + 25
    = 80, in [exit 77, entry 83) → carried rung_0 latch HOLDS rung_0 (no
    flip to the rung_2 grid-charge plan)."""
    strat, _ = _make(soc=55, boundary=bnd, tomorrow_kwh="24")
    strat._arb_rung0_latch = True
    rung, p0, _p1 = _classify(strat, now, 55.0, 0.0, 2.0)
    assert (rung, p0) == ("rung_0", 80.0)
    assert strat._arb_rung0_latch is True


@pytest.mark.parametrize("now,bnd", _NIGHT_CASES, ids=["0200", "2105"])
def test_night_carried_rung0_latch_exits_below_exit_band(now, bnd):
    """p0 = 50 + 25 = 75 < exit 77 → carried rung_0 latch exits → rung_2."""
    strat, _ = _make(soc=50, boundary=bnd, tomorrow_kwh="24")
    strat._arb_rung0_latch = True
    rung, p0, _p1 = _classify(strat, now, 50.0, 0.0, 2.0)
    assert (rung, p0) == ("rung_2", 75.0)
    assert strat._arb_rung0_latch is False


@pytest.mark.parametrize("now,bnd", _NIGHT_CASES, ids=["0200", "2105"])
def test_night_both_latches_rung1_released_rung0_kept(now, bnd):
    """Both latched at night, p0 80: rung_1 + EV load cleared, rung_0 held."""
    strat, _ = _make(soc=55, boundary=bnd, tomorrow_kwh="24")
    strat._arb_rung0_latch = True
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    rung, p0, _p1 = _classify(strat, now, 55.0, 0.0, 2.0)
    assert (rung, p0) == ("rung_0", 80.0)
    assert strat._arb_rung1_latch is False
    assert strat._arb_rung0_latch is True
    assert strat._arb_last_ev_load_pct_per_h == 0.0


def test_night_p0_above_entry_gives_rung0_unlatched():
    """02:00 SOC 60: p0 = 60 + 25 = 85 >= 83 → rung_0 via unlatched entry
    (the carried rung_1 latch is released first)."""
    strat, _ = _make(soc=60, boundary=_SHOULDER_BND)
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    rung, p0, _p1 = _classify(strat, datetime(2026, 10, 1, 2, 0), 60.0, 0.0, 2.0)
    assert (rung, p0) == ("rung_0", 85.0)
    assert strat._arb_rung1_latch is False


def test_daylight_carried_rung1_latch_still_held():
    """Discriminator: same latch in daylight is NOT released.

    09:00 shoulder 17:00: 8 h, surplus 24.0 (see daylight_value test).
    soc 55 rate 2: p0 = 55 + 16 + 24 = 95; cf = 55 + (2-5)*8 + 24 = 55 < 83;
    p0 95 >= exit 77 → rung_1 held."""
    strat, _ = _make(soc=55, boundary=_SHOULDER_BND)
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 9, 0), 55.0, 2.0, 0.0)
    assert (rung, p0, p1) == ("rung_1", 95.0, 55.0)
    assert strat._arb_rung1_latch is True


def test_intent_reset_on_early_return_tick():
    """D-MED-1: a daylight rung_1 tick sets intent "redirect"; the next tick
    takes a peak early return (never reaches _gate_is_open) → intent None.

    10:00 shoulder 17:00: 7 h; surplus [10,17] 7/9 * 24 * .5 / 40 = 23.33.
    p0 = 55 + 0 + 23.3 = 78.3 < 83; entry = 55 + 5*7 + 23.3 → 100 >= 83."""
    strat, _ = _make(soc=55, boundary=_SHOULDER_BND)
    now = datetime(2026, 10, 1, 10, 0)
    _seed_rate(strat, now, 55.0, 0.0)
    strat.determine_mode("off_peak", "shoulder", now=now, ev_load_w=2000.0)
    assert strat._arbitrage_intent == "redirect"
    r = strat.determine_mode("peak", "shoulder", now=now + timedelta(minutes=5),
                             ev_load_w=2000.0)
    assert strat._arbitrage_intent is None
    assert _cfg_on_actions(r) == []


def test_rung1_counterfactual_site_daylight_value():
    """Counterfactual in daylight keeps the pre-change value.

    09:00, shoulder 17:00: mins 480 → 8 h; surplus overlap [09:00,17:00] 8 h
    of remaining 10 h → 24*0.8 = 19.2 kWh *0.5 = 9.6 / 40 = 24.0.
    cf = 30 + (2 - 5)*8 + 24 = 30.0; p0 = 30 + 2*8 + 24 = 70.0 (< exit 77).
    """
    strat, _ = _make(soc=30, boundary=_SHOULDER_BND)
    strat._arb_rung1_latch = True
    strat._arb_last_ev_load_pct_per_h = 5.0
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 9, 0), 30.0, 2.0, 0.0)
    assert (p0, p1) == (70.0, 30.0)
    assert rung == "rung_2"


def test_sun_unavailable_fallback_envelope_gates_both_ends():
    """F8: sun.sun missing → fallback envelope 07:00-19:00 (both ends).

    06:30 → rate 0: surplus [07:00,14:00] 7h/12h → 17.5; p0 = 20 + 17.5 = 37.5.
    08:00 → rate counts: mins 360 → 6 h; surplus [08:00,14:00] 6 h / 11 h →
    24*6/11*0.5 = 6.545 kWh / 40 = 16.36 %; p0 = 20 + 6 + 16.36 = 42.4.
    """
    strat, hass = _make(soc=20, boundary=_SUMMER_BND)
    hass._states.pop("sun.sun", None)
    assert hass.states.get("sun.sun") is None
    _, p0, p1 = _classify(strat, datetime(2026, 10, 1, 6, 30), 20.0, 1.0, 2.0)
    assert (p0, p1) == (37.5, 37.5)
    _, p0, _ = _classify(strat, datetime(2026, 10, 1, 8, 0), 20.0, 1.0, 0.0)
    assert p0 == 42.4


def test_inverted_bounds_rate_term_zero():
    """F8: projected sunset HH:MM <= sunrise HH:MM → predicate never true.

    sunrise 19:00, sunset 07:00 at noon: rate term 0. Surplus: now >= sunset
    → tomorrow branch; boundary 14:00 <= tomorrow-sunrise 19:00 → 0.
    p0 = p1 = 40 → but surplus 0 < 0.5 short-circuits rung-1 → p1 None.
    """
    strat, hass = _make(soc=40, boundary=_SUMMER_BND)
    _sun(hass, "2026-10-01T19:00:00+00:00", "2026-10-01T07:00:00+00:00")
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 12, 0), 40.0, 20.0, 11.6)
    assert p0 == 40.0
    assert p1 is None
    assert rung == "rung_2"


def test_rung1_post_sunrise_ev_draw_documented():
    """F6(b) — DOCUMENTS the residual, not correctness.

    At sunrise + 1 min with the EV still drawing and a ~0 trailing rate,
    the entry extrapolates +29 %/h over min(599, 719) min → p1 = 100 →
    rung_1 (the same pause/release mechanism the plan scopes out: D1 removes
    the PRE-DAWN window only). Detector: the SPEC INV-1 trip-wire card.
    """
    strat, _ = _make(soc=9, boundary=_SHOULDER_BND)
    rung, p0, p1 = _classify(strat, datetime(2026, 10, 1, 7, 1), 9.0, 0.0, 11.6)
    assert rung == "rung_1"
    assert p1 == 100.0


# ---------------------------------------------------------------------------
# Projector primitive (parity extension)
# ---------------------------------------------------------------------------

_P_NOW = datetime(2026, 10, 1, 9, 0)


@pytest.mark.parametrize("now,sunset", [
    (_P_NOW, datetime(2026, 10, 1, 19, 0)),
    (datetime(2026, 10, 1, 1, 14), datetime(2026, 10, 1, 19, 0)),
    (datetime(2026, 10, 1, 22, 0), datetime(2026, 10, 1, 19, 0)),
    (_P_NOW, None),
])
@pytest.mark.parametrize("bound", [True, False])
def test_projector_sunrise_none_byte_identical(now, sunset, bound):
    """`sunrise_dt=None` (default) is byte-identical to not passing it."""
    kw = dict(soc=40.0, rate_pct_per_h=3.0, mins=600, solar_surplus_pct=7.0,
              source="t", bound_to_solar_horizon=bound, now=now,
              sunset_dt=sunset, extra_rate_pct_per_h=5.0)
    a = EnergyProjector.project_soc_at_boundary(**kw)
    b = EnergyProjector.project_soc_at_boundary(**kw, sunrise_dt=None)
    assert a == b


def test_projector_sunrise_gate_values():
    """now < sunrise → horizon 0; now == sunrise → legacy sunset bound.

    Before: raw = 40 + 8*0 + 7 = 47.0. At sunrise 07:00: min(600, 720) = 600
    → 10 h → 40 + 80 + 7 = 127 raw, 100 clamped.
    """
    sr = datetime(2026, 10, 1, 7, 0)
    ss = datetime(2026, 10, 1, 19, 0)
    kw = dict(soc=40.0, rate_pct_per_h=3.0, mins=600, solar_surplus_pct=7.0,
              source="t", bound_to_solar_horizon=True, sunset_dt=ss,
              extra_rate_pct_per_h=5.0, sunrise_dt=sr)
    pre = EnergyProjector.project_soc_at_boundary(now=sr - timedelta(seconds=1), **kw)
    assert (pre.horizon_min, pre.raw_soc_pct, pre.soc_pct) == (0.0, 47.0, 47.0)
    at = EnergyProjector.project_soc_at_boundary(now=sr, **kw)
    assert (at.horizon_min, at.raw_soc_pct, at.soc_pct) == (600.0, 127.0, 100.0)
    # bound_to_solar_horizon=False ignores sunrise entirely (attain sites).
    kw["bound_to_solar_horizon"] = False
    off = EnergyProjector.project_soc_at_boundary(now=sr - timedelta(hours=6), **kw)
    assert off.horizon_min == 600.0


# ===========================================================================
# D2 — poor-night WAIT holds the forecast drain floor (park-only)
# ===========================================================================

# 22:30 on 10-01, boundary next day 17:00 (18.5 h > lead 180) → WAIT.
_W_NOW = datetime(2026, 10, 1, 22, 30)
_W_BND = datetime(2026, 10, 2, 17, 0)


def _wait(strat):
    r = strat.determine_mode("off_peak", "shoulder", now=_W_NOW, ev_load_w=0.0)
    assert r["arbitrage_phase"] == "wait", r["reason"]
    return r


def test_wait_emits_drain_floor_when_soc_above():
    """poor slider 30, reserve 10, SOC 45 > 30 → reserve 30, no grid charge."""
    strat, _ = _make(soc=45, boundary=_W_BND)
    r = _wait(strat)
    assert _reserve_actions(r) == [30]
    assert strat._last_reserve_level_desired == 30
    assert "holding drain floor 30%" in r["reason"]
    assert _cfg_on_actions(r) == []
    assert strat._last_charge_from_grid_desired is False


def test_wait_parks_at_soc_when_below_floor():
    """SOC 22.7 ≤ floor 30 → park at max(10, int(22.7)) = 22."""
    strat, _ = _make(soc=22.7, boundary=_W_BND)
    r = _wait(strat)
    assert _reserve_actions(r) == [22]


@pytest.mark.parametrize("soc,expected", [(12.0, 12), (8.0, 10)])
def test_wait_below_floor_never_grid_charges(soc, expected):
    """Operator ruling 2026-10-03: WAIT is PARK-ONLY.

    SOC below the 30 floor → reserve = max(reserve 10, int(soc)); NO
    charge_from_grid turn_on, desired CFG False. Refill-to-floor is attain's
    decision, not WAIT's.
    """
    strat, _ = _make(soc=soc, boundary=_W_BND)
    r = _wait(strat)
    assert _reserve_actions(r) == [expected]
    assert _cfg_on_actions(r) == []
    assert strat._last_charge_from_grid_desired is False


@pytest.mark.parametrize("reserve,drains,soc,new,legacy", [
    # default ladder 10/15/20/30/30/40 (poor floor 30)
    (10, _LIVE_DRAINS, 5.0, 10, 10),     # SOC < reserve: max(10, 5)
    (10, _LIVE_DRAINS, 9.0, 10, 10),     # 09-30 night shape
    (10, _LIVE_DRAINS, 9.9, 10, 10),     # int(9.9) = 9 → 10
    (10, _LIVE_DRAINS, 30.0, 30, 10),    # at floor: max(10, 30)
    (10, _LIVE_DRAINS, 31.0, 30, 10),    # above: floor
    (10, _LIVE_DRAINS, 79.0, 30, 10),
    # all sliders == reserve → byte-identical to legacy (kill switch)
    (10, dict.fromkeys(_LIVE_DRAINS, 10), 5.0, 10, 10),
    (10, dict.fromkeys(_LIVE_DRAINS, 10), 9.0, 10, 10),
    (10, dict.fromkeys(_LIVE_DRAINS, 10), 30.0, 10, 10),
    (10, dict.fromkeys(_LIVE_DRAINS, 10), 79.0, 10, 10),
    # reserve 40 > poor 30 → effective poor 40 == legacy
    (40, _LIVE_DRAINS, 79.0, 40, 40),
    (40, _LIVE_DRAINS, 35.0, 40, 40),   # ≤ floor: max(40, 35)
    # reserve 60 > poor raw → 60
    (60, _LIVE_DRAINS, 79.0, 60, 60),
    # reserve 5: effective poor 30
    (5, _LIVE_DRAINS, 3.0, 5, 5),
    (5, _LIVE_DRAINS, 50.0, 30, 5),
    # poor 100: SOC never above → park at int(soc)
    (10, {**_LIVE_DRAINS, "poor": 100, "very_poor": 100}, 79.0, 79, 10),
])
def test_wait_floor_never_below_legacy(reserve, drains, soc, new, legacy):
    """INV-W0 (review #2 F1) + INV-W1 over the §4 config-extreme matrix."""
    strat, _ = _make(soc=soc, reserve=reserve, drains=drains, boundary=_W_BND)
    _wait(strat)
    got = strat._last_reserve_level_desired
    assert got == new
    assert got >= legacy


def test_wait_soc_none_holds_drain_floor():
    """Blind SOC reaching WAIT (phase 1 skipped) → protective floor 30."""
    strat, _ = _make(soc=45, boundary=_W_BND)
    r = strat._get_arbitrage_decision(
        soc=None, now=_W_NOW, target_day_class="poor", tomorrow_class="poor",
        current_mode="self_consumption", season="shoulder",
    )
    assert r["arbitrage_phase"] == "wait"
    assert strat._last_reserve_level_desired == 30


@pytest.mark.parametrize("drains,expected", [
    # raw poor 5 < reserve 10 → effective 10 (cumulative max anchored at 10)
    ({"excellent": 5, "good": 5, "moderate": 5, "poor": 5, "very_poor": 5,
      "unknown": 40}, 10),
    # poor 15 < moderate 20 (inverted) → effective poor 20
    ({"excellent": 10, "good": 15, "moderate": 20, "poor": 15,
      "very_poor": 15, "unknown": 40}, 20),
])
def test_wait_floor_uses_effective_ladder_clamp(drains, expected):
    strat, _ = _make(soc=50, drains=drains, boundary=_W_BND)
    _wait(strat)
    assert strat._last_reserve_level_desired == expected


def test_wait_floor_multi_day_max():
    """Target poor (30) + D+1-of-target very_poor slider 45 → floor 45
    (multi-day max). Without the multi-day max the floor would be 30."""
    strat, _ = _make(soc=60, boundary=_W_BND, multi_day=True,
                     drains={**_LIVE_DRAINS, "very_poor": 45})
    strat.classify_solar_day_n = lambda n, now=None: "very_poor"
    _wait(strat)
    assert strat._last_reserve_level_desired == 45


def _partial(floor):
    return InclementDecision(
        hold_depth="partial_hold", grid_precharge=False, tier="watch",
        source="alert", contributing_event="Flood Watch", expires_at=None,
        reserve_floor=floor, reason="test", solar_horizon=_na_horizon(),
    )


@pytest.mark.parametrize("floor,expected,suffix", [(50, 50, True), (25, 30, False)])
def test_wait_partial_hold_floor_dominates(floor, expected, suffix):
    """INV-W3: partial_hold 50 > drain floor 30 → 50 (suffix); 25 < 30 → 30."""
    strat, _ = _make(soc=45, boundary=_W_BND)
    strat._inclement_decision = lambda tp, now: _partial(floor)
    r = _wait(strat)
    assert strat._last_reserve_level_desired == expected
    assert ("partial_hold floor" in r["reason"]) is suffix


def test_wait_recheck_abort_path_emits_floor():
    """F9: abort-path WAIT (charge-window recheck fails → chunk locked)."""
    strat, _ = _make(soc=45, boundary=_W_BND)
    strat._recheck_forecast_on_charge_entry = lambda now: False
    now = datetime(2026, 10, 2, 15, 0)  # 2 h before 17:00, inside lead 180
    r = strat.determine_mode("off_peak", "shoulder", now=now, ev_load_w=0.0)
    assert r["arbitrage_phase"] == "wait"
    assert strat._arbitrage_chunk_completed is True
    assert strat._last_reserve_level_desired == 30
    assert _cfg_on_actions(r) == []


def test_charge_hold_byte_identical():
    """INV-W2: CHARGE → reserve 80 + CFG on; HOLD (SOC ≥ 80) → 80, CFG off."""
    strat, _ = _make(soc=20, boundary=_W_BND)
    r = strat.determine_mode("off_peak", "shoulder",
                             now=datetime(2026, 10, 2, 15, 0), ev_load_w=0.0)
    assert r["arbitrage_phase"] == "charge"
    assert _reserve_actions(r) == [80]
    assert len(_cfg_on_actions(r)) == 1
    strat2, _ = _make(soc=85, boundary=_W_BND)
    r2 = strat2.determine_mode("off_peak", "shoulder", now=_W_NOW, ev_load_w=0.0)
    assert r2["arbitrage_phase"] == "hold"
    assert _reserve_actions(r2) == [80]
    assert _cfg_on_actions(r2) == []


def test_completed_chunk_hold_unchanged():
    """INV-W2: completed chunk + boundary ahead → HOLD 80 (not WAIT floor)."""
    strat, _ = _make(soc=45, boundary=_W_BND)
    strat._arbitrage_chunk_completed = True
    r = strat.determine_mode("off_peak", "shoulder", now=_W_NOW, ev_load_w=0.0)
    assert r["arbitrage_phase"] == "hold"
    assert _reserve_actions(r) == [80]


def test_wait_does_not_stamp_dp_target():
    """INV-W4 / F10: fallback tick stamps 15 (good), then a WAIT tick on the
    same object clears it (entry-reset) and never re-stamps."""
    # SOC 35: tick-2 rung_0 projection 35 + 0 + surplus (tomorrow 40 kWh
    # sliced [07:00,17:00] 10/12 * 0.5 / 40 kWh = 41.7) = 76.7 < 83 → rung_2.
    strat, hass = _make(soc=35, boundary=_W_BND, tomorrow_kwh="90")  # good
    r1 = strat.determine_mode("off_peak", "shoulder", now=_W_NOW, ev_load_w=0.0)
    assert r1["arbitrage_phase"] != "wait"
    assert strat._offpeak_drain_branch_target == 15
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, "40")  # → poor
    _wait_now = _W_NOW + timedelta(minutes=5)
    r2 = strat.determine_mode("off_peak", "shoulder", now=_wait_now, ev_load_w=0.0)
    assert r2["arbitrage_phase"] == "wait"
    assert strat._offpeak_drain_branch_target is None


def test_next_action_estimate_names_wait_floor():
    """F9: both WAIT display strings name the floor WAIT parks at."""
    strat, _ = _make(soc=45, boundary=_W_BND)
    _wait(strat)
    assert strat._next_action_estimate(45.0, _W_NOW) == (
        "waiting for charge window, holding 30% floor (lead_time=180m)"
    )
    strat._arbitrage_chunk_completed = True
    assert strat._next_action_estimate(22.7, _W_NOW) == (
        "arbitrage chunk completed — holding 22% floor"
    )


def test_next_action_estimate_wait_shows_partial_hold_floor():
    """A-LOW-1: display = emitted value. partial_hold 50 > floor 30 → 50."""
    strat, _ = _make(soc=45, boundary=_W_BND)
    strat._inclement_decision = lambda tp, now: _partial(50)
    _wait(strat)
    strat._last_inclement_decision = _partial(50)
    assert strat._last_reserve_level_desired == 50
    assert strat._next_action_estimate(45.0, _W_NOW) == (
        "waiting for charge window, holding 50% floor (partial_hold floor) "
        "(lead_time=180m)"
    )
    strat._last_inclement_decision = _partial(25)
    assert strat._next_action_estimate(45.0, _W_NOW) == (
        "waiting for charge window, holding 30% floor (lead_time=180m)"
    )


class _VerifierStub:
    def __init__(self):
        self.scheduled = []

    async def schedule(self, surface, value, now):
        self.scheduled.append((surface, value))


def _fake_ec(strat):
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    ec = EnergyCoordinator.__new__(EnergyCoordinator)
    ec._battery = strat
    ec._write_verifier = _VerifierStub()
    return ec


@pytest.mark.asyncio
@pytest.mark.parametrize("soc,expected", [(45.0, 30), (9.0, 10)])
async def test_wait_floor_composes_into_release_floor(soc, expected):
    """R1-1: the WAIT emission, dispatched through the REAL dispatch tap,
    becomes the EV drain-release floor.

    SOC 45 → WAIT 30 → ledger 30 → compose_release_floor = (30, True).
    SOC 9, reserve 10 → WAIT 10 → (10, True) (not the 30 planned fallback).
    """
    strat, _ = _make(soc=soc, boundary=_W_BND)
    r = _wait(strat)
    ec = _fake_ec(strat)
    for action in r["actions"]:
        await ec._tap_write_verifier(action, r)
    assert strat._last_reserve_level == expected
    assert compose_release_floor(strat, "off_peak") == (expected, True)


# ===========================================================================
# D0 replay — recorder fixture 2026-09-28 21:00 → 2026-10-03 14:30 CDT
# ===========================================================================

_FIXTURE = Path(__file__).parent / "fixtures" / "ec_nights_2026_09_28_10_02.json"
_OFFPEAK_PREFIXES = (
    "Off-peak", "Arbitrage", "Peak-buffer attainability", "Charging the battery",
)


def _load_rows():
    d = json.loads(_FIXTURE.read_text())
    return [dict(zip(d["fields"], r)) for r in d["rows"]], d


def _parse(s):
    return datetime.fromisoformat(s)


def _night_key(local: datetime) -> str:
    """Night of D = local D 20:00 → D+1 19:59 (one fresh strategy per night)."""
    base = local if local.hour >= 20 else local - timedelta(days=1)
    return base.date().isoformat()


class _ReplayBattery(BatteryStrategy):
    """Replay-only: the SOC resolver OUTPUT (value + tier) is a recorded
    input. The 3-tier resolver is not under change; injecting its recorded
    tier lets the real degraded-telemetry entry refusal (energy_battery
    `_degraded_entry_refused`) see what production saw."""

    _rp_soc = None
    _rp_src = "envoy"

    @property
    def battery_soc(self):
        self._soc_source_last = self._rp_src
        return self._rp_soc

    @property
    def envoy_available(self):
        return self._rp_src == "envoy"


class _ReplayTOU(_FakeTOU):
    def __init__(self):
        super().__init__(None)


def _replay(monkeypatch, *, legacy_sunrise: bool = False):
    """Drive the REAL off-peak decision per recorded decision tick.

    Emitted decisions are asserted PER RECORDED INPUT — the recorder SOC
    trajectory is NOT re-simulated (under the fix the battery would have
    parked at 30, so a simulated trajectory would diverge by design; do not
    "fix" this into a simulation). Injected per row: now, SOC (the K-tick
    rate is RECOMPUTED by the real `_observed_net_charge_rate_per_hour` from
    the injected SOC series — not stubbed), EV load (garage A+B minute
    averages), sun.sun (derived next_rising/next_setting), Solcast
    remaining/today/tomorrow, battery capacity (LKG 40 kWh when the recorded
    state was unavailable), next high-rate boundary, target-day class and
    D+1 class (recorded), inclement hold depth (recorded; partial_hold floor
    50 = live knob).
    """
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "as_local", lambda d: d.astimezone(_CDT),
                        raising=False)
    rows, meta = _load_rows()
    out = []
    strat = hass = None
    cur_night = None
    for r in rows:
        t = _parse(r["t"]).astimezone(_CDT)
        reason = r["reason"] or ""
        if r["soc"] is None or not reason.startswith(_OFFPEAK_PREFIXES):
            continue
        if r["target_day_class"] is None:
            continue
        nk = _night_key(t)
        if nk != cur_night:
            cur_night = nk
            drains = {k: int(v) for k, v in
                      meta["drain_targets_by_local_day"][t.date().isoformat()].items()}
            strat, hass = _make(soc=r["soc"], drains=drains, boundary=None,
                                multi_day=True, cap_kwh="40000",
                                cls=_ReplayBattery)
            hass.set_state(_CAP, "40000", attributes={"unit_of_measurement": "Wh"})
            tou = _ReplayTOU()
            strat._tou = tou
            if legacy_sunrise:
                strat._daylight_bounds = _legacy_rung_sunrise(strat)
        bnd = _parse(r["next_high_rate_transition"])
        strat._tou.boundary = bnd
        offset = max(0, (bnd.date() - t.date()).days)
        tgt, d2 = r["target_day_class"], r["d2_class"] or r["target_day_class"]
        strat._resolve_target_day = (lambda now, _c=tgt, _o=offset: (_c, _o))
        strat.classify_solar_day_n = (lambda n, now=None, _c=d2: _c)
        depth = r["inclement_hold_depth"] or "allow_discharge"
        dec = _partial(50) if depth == "partial_hold" else InclementDecision(
            hold_depth="allow_discharge", grid_precharge=False, tier="none",
            source="none", contributing_event=None, expires_at=None,
            reserve_floor=10, reason="replay", solar_horizon=_na_horizon(),
        )
        strat._inclement_decision = (lambda tp, now, _d=dec: _d)
        hass.set_state(_SOC, str(r["soc"]))
        strat._rp_soc = float(r["soc"])
        strat._rp_src = r["soc_source"] or "envoy"
        for eid, key in ((_NET, "net_power"), (_BPW, "battery_power")):
            if r[key] is None:
                hass.set_state(eid, "unavailable")
            else:
                hass.set_state(eid, str(r[key]),
                               attributes={"unit_of_measurement": "kW"})
        if r["capacity_wh"] is not None:
            hass.set_state(_CAP, str(r["capacity_wh"]),
                           attributes={"unit_of_measurement": "Wh"})
        for eid, key in ((DEFAULT_SOLCAST_REMAINING_ENTITY, "solcast_remaining"),
                         (DEFAULT_SOLCAST_TODAY_ENTITY, "solcast_today"),
                         (DEFAULT_SOLCAST_TOMORROW_ENTITY, "solcast_tomorrow")):
            if r[key] is not None:
                hass.set_state(eid, str(r[key]))
        _sun(hass, r["sun_next_rising"], r["sun_next_setting"])
        ev_w = sum(float(r[k] or 0.0) for k in ("garage_a_w", "garage_b_w"))
        strat._arb_last_projection_rung0 = None
        strat._arb_last_projection_rung1 = None
        strat._arb_last_rung = None
        strat._arb_last_gate_outcome = None
        strat._last_reserve_level_desired = None
        rates = []
        _real_rate = BatteryStrategy._observed_net_charge_rate_per_hour.__get__(strat)

        def _spy_rate(_real=_real_rate, _acc=rates):
            v = _real()
            _acc.append(v)
            return v

        strat._observed_net_charge_rate_per_hour = _spy_rate
        dec_out = strat.determine_mode("off_peak", "shoulder", now=t, ev_load_w=ev_w)
        sr, ss = strat._daylight_bounds(t)
        out.append({
            "t": t, "row": r, "ev_w": ev_w, "phase": dec_out["arbitrage_phase"],
            "reason": dec_out["reason"], "rung": strat._arb_last_rung,
            "gate": strat._arb_last_gate_outcome,
            "p0": strat._arb_last_projection_rung0,
            "p1": strat._arb_last_projection_rung1,
            "reserve": strat._last_reserve_level_desired,
            "cfg": strat._last_charge_from_grid_desired,
            "drain_for": strat._drain_target_for(t),
            "sunrise": sr, "sunset": ss,
            "rate": rates[0] if rates else None,
            "mins": int((bnd - t).total_seconds() // 60),
            "surplus": strat._expected_solar_surplus_pct(
                t, int((bnd - t).total_seconds() // 60)),
        })
    return out


def _in(t, d, h0, m0, h1, m1):
    lo = datetime(d.year, d.month, d.day, h0, m0, tzinfo=_CDT)
    hi = datetime(d.year, d.month, d.day, h1, m1, tzinfo=_CDT)
    return lo <= t < hi


def test_replay_fixture_fidelity_drain_target_matches_recorder(monkeypatch):
    """Sanity: the replay's `_drain_target_for` equals the recorded
    `current_offpeak_drain_target` on every driven tick (fixture wiring)."""
    out = _replay(monkeypatch)
    assert len(out) > 300
    mism = [(o["t"], o["drain_for"], o["row"]["current_offpeak_drain_target"])
            for o in out
            if o["row"]["current_offpeak_drain_target"] is not None
            and o["drain_for"] != int(o["row"]["current_offpeak_drain_target"])]
    assert mism == []


def test_replay_2026_10_01_no_rung1_flap(monkeypatch):
    """10-01 00:00 → projected sunrise (07:23): zero rung_1, zero
    closed_rung_1, zero rung_1 fallback-hold decisions; p1 == p0 on every
    pre-sunrise EV-drawing tick. Anchor: the SAME replay with sunrise
    discarded (pre-fix) yields >= 10 rung_1 ticks in 01:14-03:20."""
    d = datetime(2026, 10, 1)
    out = _replay(monkeypatch)
    pre = [o for o in out if o["t"].date() == d.date()
           and o["t"] < o["sunrise"]]
    assert len(pre) > 50
    assert [o["t"] for o in pre if o["rung"] == "rung_1"] == []
    assert [o["t"] for o in pre if o["gate"] == "closed_rung_1"] == []
    assert [o["t"] for o in pre if o["reason"].startswith("Off-peak hold — SOC")] == []
    ev_ticks = [o for o in pre if o["ev_w"] > 0 and o["p1"] is not None]
    assert len(ev_ticks) >= 10
    assert all(o["p1"] == o["p0"] for o in ev_ticks)

    legacy = _replay(monkeypatch, legacy_sunrise=True)
    flap = [o for o in legacy if _in(o["t"], d, 1, 14, 3, 21)
            and o["rung"] == "rung_1"]
    assert len(flap) >= 10, len(flap)


def test_replay_daylight_ticks_unchanged(monkeypatch):
    """INV-H2 on real data: every daylight tick (sunrise <= now < sunset)
    has projections IDENTICAL between the fixed code and the pre-change
    code (sunrise discarded), and the same rung."""
    new = _replay(monkeypatch)
    old = _replay(monkeypatch, legacy_sunrise=True)
    assert [o["t"] for o in new] == [o["t"] for o in old]
    day = [(n, o) for n, o in zip(new, old)
           if n["sunrise"] <= n["t"] < n["sunset"] and n["p0"] is not None]
    assert len(day) > 50
    diffs = [(n["t"], n["p0"], o["p0"], n["p1"], o["p1"], n["rung"], o["rung"])
             for n, o in day
             if (n["p0"], n["p1"], n["rung"]) != (o["p0"], o["p1"], o["rung"])]
    assert diffs == []
    # Independent pre-change oracle (v5.17.4 expression written here, not
    # imported): p0 = clamp(soc + rate * min(mins, sunset-now)/60 + surplus),
    # rate = the K-tick rate the classifier read that tick. `surplus` is the
    # UNCHANGED `_expected_solar_surplus_pct` value for that tick. Recorded
    # p0 is rounded to 0.1 → tolerance 0.05.
    checked = 0
    for n, _o in day:
        rate = n["rate"]  # value the classifier read (spy, not recomputed)
        if rate is None:
            continue
        hours = min(n["mins"], (n["sunset"] - n["t"]).total_seconds() / 60.0) / 60.0
        raw = float(n["row"]["soc"]) + rate * hours + n["surplus"]
        oracle = max(0.0, min(100.0, raw))
        assert abs(oracle - n["p0"]) <= 0.05 + 1e-9, (n["t"], oracle, n["p0"])
        checked += 1
    assert checked > 50


def test_replay_poor_nights_hold_floor(monkeypatch):
    """10-01 and 10-02 nights (poor, gate open): from the first WAIT tick
    after 21:00 to the first CHARGE tick, the WAIT emission is 30 while SOC
    > 30 and max(10, int(soc)) at/below (partial_hold rows: max(that, 50)),
    never 10 while SOC > 10, never < 10, never grid charge; the first CHARGE
    tick is identical to the recorder (reserve 80). 09-30 night (SOC ~9 at
    21:00): every WAIT tick emits 10 (F1 — not 9/8/7)."""
    out = _replay(monkeypatch)

    def night(start: datetime):
        seg = []
        started = False
        for o in out:
            if o["t"] < start:
                continue
            if not started and o["phase"] == "wait":
                started = True
            if started:
                seg.append(o)
                if o["phase"] == "charge":
                    break
        return seg

    for start in (datetime(2026, 10, 1, 21, 0, tzinfo=_CDT),
                  datetime(2026, 10, 2, 21, 0, tzinfo=_CDT)):
        seg = night(start)
        waits = [o for o in seg if o["phase"] == "wait"]
        assert len(waits) > 20, start
        for o in waits:
            soc = float(o["row"]["soc"])
            exp = 30 if soc > 30 else max(10, int(soc))
            if o["row"]["inclement_hold_depth"] == "partial_hold":
                exp = max(exp, 50)
            assert o["reserve"] == exp, (o["t"], soc, o["reserve"])
            assert o["reserve"] >= 10
            # Plan (3) "never 10 while SOC > 10" read with (2)'s int(soc)
            # park: SOC 10.6 parks at int → 10 by design; >= 11 never 10.
            if int(soc) > 10:
                assert o["reserve"] != 10, (o["t"], soc)
            assert o["cfg"] is False
        if start.day == 1:
            # 10-01 night ends at the 10-02 15:53 CHARGE (Envoy blind
            # 14:08-15:53 — the recorder's first CHARGE tick).
            assert seg[-1]["phase"] == "charge"
            assert seg[-1]["t"].strftime("%m-%d %H:%M") == "10-02 15:53"
            assert seg[-1]["reserve"] == 80
            assert seg[-1]["row"]["live_desire"] == 80
            assert seg[-1]["cfg"] is True
        # Non-vacuous: the night has WAIT ticks with SOC above reserve (the
        # recorder emitted 10 on every one of them; the fix holds them).
        above = [o for o in waits if int(float(o["row"]["soc"])) > 10]
        assert len(above) >= 5, start
        assert all(o["row"]["live_desire"] in (10, 50) for o in above)

    # 09-30 night: SOC 6.4-10 the whole way → every WAIT tick 10.
    seg = night(datetime(2026, 9, 30, 21, 0, tzinfo=_CDT))
    waits = [o for o in seg if o["phase"] == "wait"
             and o["row"]["inclement_hold_depth"] != "partial_hold"
             and float(o["row"]["soc"]) < 11]
    assert len(waits) > 50
    assert {o["reserve"] for o in waits} == {10}
    assert seg[-1]["phase"] == "charge"
    assert seg[-1]["t"].strftime("%m-%d %H:%M") == "10-01 14:01"
    assert seg[-1]["reserve"] == 80


def test_replay_nonpoor_nights_byte_identical(monkeypatch):
    """09-28 (good → 15) and 09-29 (moderate → 20) nights, 21:00 → 08:30:
    every drain-fallback decision equals the recorder (desired reserve,
    self_consumption, no grid charge, gate closed_forecast)."""
    out = _replay(monkeypatch)
    sel = [o for o in out
           if _night_key(o["t"]) in ("2026-09-28", "2026-09-29")
           and (o["t"].hour >= 21 or o["t"].hour < 8
                or (o["t"].hour == 8 and o["t"].minute < 30))
           and (o["row"]["reason"] or "").startswith(("Off-peak drain", "Off-peak hold"))]
    assert len(sel) > 100
    bad = [(o["t"], o["reserve"], o["row"]["live_desire"], o["reason"][:40])
           for o in sel
           if o["reserve"] != o["row"]["live_desire"]
           or o["cfg"] is not False
           or o["gate"] != "closed_forecast"]
    assert bad == []
    assert {o["reserve"] for o in sel} >= {15, 20}

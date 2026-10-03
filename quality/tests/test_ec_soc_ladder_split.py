"""EC-SOC-LADDER-FULL-WIRING-1 — RECOMMENDED SPLIT (D1 + D3 + D4).

Invariants (plan §3, narrowed by plan review 2026-10-02):

* I-1 (drain leg + DP stamp): for any legal ladder, the off_peak
  drain-fallback DRAIN leg of ``BatteryStrategy.determine_mode`` never
  emits ``reserve_level < reserve_soc`` and the DP value stamp
  ``_offpeak_drain_branch_target`` is never < ``reserve_soc``. (HOLD leg
  ``hold_reserve = int(soc)`` is out of scope.) Inclement recoverability
  never uses a floor < reserve_soc.
* I-2 (detect-AND-clamp): validator / anomaly readers stay RAW — an
  inverted ladder still produces a ``threshold_ladder_violation`` code
  AFTER determine_mode has run.
* I-3 (identity): a valid ladder (incl. ``excellent == reserve``,
  ``poor == very_poor``) is unchanged bit-for-bit.

Expected values are hand-derived literals (independent oracle), never
recomputed with the production formula. #2 peak-buffer stays detect-only.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_WEATHER_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
    compose_release_floor,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (  # noqa: E402
    TOURateEngine,
)
from custom_components.universal_room_automation.domain_coordinators.inclement import (  # noqa: E402
    AlertClassification,
    InclementFusion,
)

_SOC = "sensor.test_envoy_battery_ladder"

# off_peak 22:30 in each season of the built-in PEC table; next high-rate
# transition is the following day in all three (summer 14:00 mid_peak,
# shoulder 17:00 mid_peak — no peak, winter 05:00 mid_peak).
_SEASON_NOW = {
    "summer": datetime(2026, 7, 15, 22, 30, 0),
    "shoulder": datetime(2026, 10, 2, 22, 30, 0),
    "winter": datetime(2026, 1, 14, 22, 30, 0),
}

# Solcast-tomorrow kWh → class under the custom thresholds below.
_CLASS_KWH = {
    "excellent": 110, "good": 90, "moderate": 60, "poor": 40,
    "very_poor": 10, "unknown": None,
}


def _make(reserve, drains, *, soc=95.0, cls="excellent", season="summer",
          inclement_floor=50):
    hass = MockHass()
    hass.set_state(_SOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    # Enphase reserve Number currently far from any target so the
    # reserve write always dispatches and its value is observable.
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "99")
    kwh = _CLASS_KWH[cls]
    if kwh is not None:
        hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, str(kwh))
        hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, str(kwh))
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    strat = BatteryStrategy(
        hass,
        reserve_soc=reserve,
        entity_config={"battery_soc": _SOC},
        offpeak_drain_targets=dict(drains),
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
    )
    strat._tou = TOURateEngine()
    strat._inclement_config_override = {
        CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: inclement_floor,
    }
    return strat


def _drive(strat, season):
    return strat.determine_mode("off_peak", season, now=_SEASON_NOW[season])


def _emitted_reserve(r):
    """The reserve value actually dispatched to the Enphase reserve Number."""
    vals = [a["data"]["value"] for a in r["actions"]
            if a.get("service") == "number.set_value"]
    assert len(vals) == 1, r["actions"]
    return vals[0]


def _make_ec(strat, *, fill_priority=30, excess_solar=80, ev_drain=None):
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )

    class _Hass:
        def __init__(self):
            self.data = {"universal_room_automation": {"database": SimpleNamespace(
                save_anomaly_event=lambda evt: None,
            )}}
            self.states = SimpleNamespace(get=lambda _k: None)

        def async_create_task(self, coro):
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            return SimpleNamespace(add_done_callback=lambda _cb: None)

    ec = EnergyCoordinator.__new__(EnergyCoordinator)
    ec.hass = _Hass()
    ec._battery = strat
    ec._fill_priority_soc = fill_priority
    ec._excess_solar_soc = excess_solar
    ec._ev_battery_drain_soc = (
        ev_drain if ev_drain is not None else strat.reserve_soc
    )
    ec._ladder_anomaly_last = {}
    return ec


def _drains(e, g, m, p, vp, unk):
    return {"excellent": e, "good": g, "moderate": m, "poor": p,
            "very_poor": vp, "unknown": unk}


# ---------------------------------------------------------------------------
# D1 enclosing-method anchors (determine_mode drain-fallback)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("season", ["summer", "shoulder", "winter"])
def test_drain_excellent_below_reserve_emits_reserve(season):
    """Plan D1 primary anchor: reserve 10, excellent 5, SOC 50 → emitted
    reserve_level 10 (raw path would write 5 to Enphase)."""
    strat = _make(10, _drains(5, 15, 20, 30, 30, 40), soc=50, cls="excellent")
    r = _drive(strat, season)
    assert "Off-peak drain" in r["reason"], r["reason"]
    assert _emitted_reserve(r) == 10
    assert strat._offpeak_drain_branch_target == 10


def test_very_poor_below_poor_lifted_to_poor_emission_and_stamp():
    strat = _make(10, _drains(10, 15, 20, 50, 30, 40), soc=60, cls="very_poor")
    r = _drive(strat, "summer")
    assert "Off-peak drain" in r["reason"], r["reason"]
    assert _emitted_reserve(r) == 50
    assert strat._offpeak_drain_branch_target == 50


def test_multi_day_max_uses_effective_targets():
    strat = _make(10, _drains(10, 60, 20, 30, 30, 40), cls="good")
    strat._multi_day_horizon_enabled = True
    strat._resolve_target_day = lambda now: ("good", 1)
    strat.classify_solar_day_n = lambda n: "moderate"
    # raw moderate 20 < raw good 60 → effective moderate is 60.
    assert strat._get_offpeak_drain_target("moderate") == 60
    assert strat._drain_target_for(_SEASON_NOW["summer"]) == 60


def test_unknown_floored_not_monotonised():
    s1 = _make(10, _drains(10, 15, 20, 30, 30, 5))
    assert s1._get_offpeak_drain_target("unknown") == 10
    s2 = _make(10, _drains(10, 15, 20, 80, 80, 40))
    assert s2._get_offpeak_drain_target("unknown") == 40
    # unseen class → floored default, not dropped
    s3 = _make(50, _drains(50, 50, 50, 50, 50, 40))
    assert s3._get_offpeak_drain_target("bogus") == 50


def test_unknown_class_emission_floored_at_reserve():
    strat = _make(20, _drains(20, 25, 30, 40, 40, 5), soc=90, cls="unknown")
    r = _drive(strat, "summer")
    assert "Off-peak drain" in r["reason"], r["reason"]
    assert _emitted_reserve(r) == 20
    assert strat._offpeak_drain_branch_target == 20


def test_cap_at_100():
    strat = _make(10, _drains(100, 120, 100, 100, 100, 130))
    eff = strat._effective_drain_targets()
    assert eff == {"excellent": 100, "good": 100, "moderate": 100,
                   "poor": 100, "very_poor": 100, "unknown": 100}


def test_release_floor_pool_path_uses_effective():
    """compose_release_floor is the real helper energy.py threads into the
    pool drain-release gates (energy_pool reserve_soc kwarg)."""
    strat = _make(10, _drains(5, 15, 20, 30, 30, 40), cls="excellent")
    floor, is_off = compose_release_floor(strat, "off_peak")
    assert is_off is True
    assert floor == 10
    strat2 = _make(10, _drains(10, 15, 20, 50, 30, 40), cls="very_poor")
    floor2, _ = compose_release_floor(strat2, "off_peak")
    assert floor2 == 50


def test_status_exposes_raw_and_effective():
    strat = _make(20, _drains(5, 5, 5, 5, 5, 40))
    st = strat.get_status()
    assert st["drain_targets"] == _drains(5, 5, 5, 5, 5, 40)
    assert st["drain_targets_effective"] == _drains(20, 20, 20, 20, 20, 40)


def test_identity_on_live_ladder():
    """I-3: live config 10/15/20/30/30 unknown 40, reserve 10."""
    raw = _drains(10, 15, 20, 30, 30, 40)
    strat = _make(10, raw)
    assert strat._effective_drain_targets() == raw
    assert strat.get_status()["drain_targets_effective"] == raw


# ---------------------------------------------------------------------------
# I-2 anti-swallow — validator / anomaly read RAW after determine_mode
# ---------------------------------------------------------------------------

def test_anomaly_still_fires_after_determine_mode_drain_below_reserve():
    strat = _make(10, _drains(5, 15, 20, 30, 30, 40), soc=50, cls="excellent")
    r = _drive(strat, "summer")
    assert _emitted_reserve(r) == 10
    # raw dict untouched by the decision
    assert strat._drain_targets["excellent"] == 5
    ec = _make_ec(strat)
    ec._check_threshold_ladder()
    assert "drain_excellent_below_reserve" in ec._ladder_anomaly_last
    assert strat.get_status()["threshold_warning"] is not None


def test_anomaly_still_fires_after_determine_mode_very_poor_below_poor():
    strat = _make(10, _drains(10, 15, 20, 50, 30, 40), soc=60, cls="very_poor")
    _drive(strat, "summer")
    ec = _make_ec(strat)
    ec._check_threshold_ladder()
    assert "drain_ladder_not_monotonic" in ec._ladder_anomaly_last


# ---------------------------------------------------------------------------
# §7 config-extreme matrix (split scope: X1 X2 X3 X6 X9 X10 X11)
# ---------------------------------------------------------------------------

# (case, reserve, raw drains, expected effective drains [hand-derived],
#  inclement floor, expected anomaly code or None)
_MATRIX = [
    ("X1", 10, _drains(10, 15, 20, 30, 30, 40),
     _drains(10, 15, 20, 30, 30, 40), 50, None),
    ("X2", 20, _drains(5, 5, 5, 5, 5, 40),
     _drains(20, 20, 20, 20, 20, 40), 50, "drain_excellent_below_reserve"),
    ("X3", 10, _drains(80, 60, 40, 20, 5, 40),
     _drains(80, 80, 80, 80, 80, 40), 50, "drain_very_poor_below_reserve"),
    ("X6", 10, _drains(10, 15, 20, 50, 30, 40),
     _drains(10, 15, 20, 50, 50, 40), 50, "drain_ladder_not_monotonic"),
    ("X9", 30, _drains(30, 30, 40, 50, 50, 40),
     _drains(30, 30, 40, 50, 50, 40), 10, "inclement_partial_hold_below_reserve"),
    ("X10", 20, _drains(20, 25, 30, 40, 40, 5),
     _drains(20, 25, 30, 40, 40, 20), 50, None),
    ("X11", 20, _drains(25, 20, 30, 30, 25, 5),
     _drains(25, 25, 30, 30, 30, 20), 15, "drain_ladder_not_monotonic"),
]

_CLASSES = ["excellent", "good", "moderate", "poor", "very_poor", "unknown"]


@pytest.mark.parametrize("season", ["summer", "shoulder", "winter"])
@pytest.mark.parametrize(
    "case,reserve,raw,expected,inc_floor,code", _MATRIX,
    ids=[m[0] for m in _MATRIX],
)
@pytest.mark.parametrize("cls", _CLASSES)
def test_config_extreme_matrix(season, case, reserve, raw, expected,
                               inc_floor, code, cls):
    strat = _make(reserve, raw, soc=95, cls=cls, season=season,
                  inclement_floor=inc_floor)
    r = _drive(strat, season)
    assert "Off-peak drain" in r["reason"], (case, cls, r["reason"])
    # I-1: drain leg + DP stamp never below reserve, and equal the
    # hand-derived effective value.
    assert _emitted_reserve(r) == expected[cls], (case, cls)
    assert _emitted_reserve(r) >= reserve
    assert strat._offpeak_drain_branch_target == expected[cls]
    # raw preserved (I-2 precondition) + status shape
    assert strat._drain_targets == raw
    assert strat.get_status()["drain_targets_effective"] == expected
    # I-2: anomaly still fires on the raw inversion (or not, on valid ladders)
    ec = _make_ec(strat)
    ec._check_threshold_ladder()
    if code is None:
        assert ec._ladder_anomaly_last == {}
    else:
        assert code in ec._ladder_anomaly_last


# ---------------------------------------------------------------------------
# D3 — inclement recoverability uses max(reserve, floor)
# ---------------------------------------------------------------------------

_INC_NOW = datetime(2026, 10, 2, 18, 0, 0)  # shoulder mid_peak


class _Bat:
    def __init__(self, surplus):
        self._expected_solar_surplus_pct = MagicMock(return_value=surplus)

    def classify_tomorrow_solar(self):
        return "poor"

    def _daylight_bounds(self, anchor):
        return (anchor.replace(hour=6, minute=0), anchor.replace(hour=20, minute=0))


def _watch():
    return AlertClassification(
        tier="watch", contributing_events=("Severe Thunderstorm Watch",),
        max_severity="Severe", max_certainty="Possible",
        expires_at=_INC_NOW.replace(hour=19, minute=30), raw_alert_count=1,
    )


def _decide(reserve, floor, surplus, soc=60):
    fusion = InclementFusion(reserve_soc=reserve,
                             partial_hold_reserve_floor=floor,
                             surplus_margin_pct=5)
    return fusion.decide(_Bat(surplus), _watch(), True, 1, "mid_peak",
                         _INC_NOW, soc)


def test_inclement_inverted_floor_uses_reserve_for_recoverability():
    """reserve 20, floor 10, SOC 60: permitted = 40 (not 50). surplus 47:
    clamped 47 >= 40+5 → recoverable partial_hold; raw 47 < 50+5 → full."""
    d = _decide(20, 10, 47.0)
    assert d.solar_horizon.permitted_discharge_pct == 40.0
    assert d.hold_depth == "partial_hold"
    assert d.reserve_floor == 20


def test_inclement_inverted_floor_not_recoverable_when_surplus_short():
    d = _decide(20, 10, 44.0)
    assert d.solar_horizon.permitted_discharge_pct == 40.0
    assert d.hold_depth == "full_hold"


def test_inclement_identity_on_healthy_floor():
    d = _decide(10, 50, 15.0)
    assert d.solar_horizon.permitted_discharge_pct == 10.0
    assert d.hold_depth == "partial_hold"
    assert d.reserve_floor == 50

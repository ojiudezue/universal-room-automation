"""Pure-helper tests for scripts/probes/house2_ecobee_d0b_probe.py (D0b probe kit)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "probes" / "house2_ecobee_d0b_probe.py"
_spec = importlib.util.spec_from_file_location("house2_d0b_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def _st(state="heat_cool", low=70.0, high=75.0, temp=None, indoor=72.0):
    return {"state": state, "attributes": {"target_temp_low": low, "target_temp_high": high,
                                           "temperature": temp, "current_temperature": indoor}}


# --- clamping ---------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [(60, 66.0), (66, 66.0), (72.5, 72.5), (80, 80.0), (95, 80.0)])
def test_clamp_leg(value, expected):
    assert probe.clamp_leg(value) == expected


def test_clamp_leg_rejects_none():
    with pytest.raises(ValueError):
        probe.clamp_leg(None)


# --- both legs ---------------------------------------------------------------
def test_payload_always_carries_both_legs_clamped():
    p = probe.build_range_payload("climate.x", 60, 90)
    assert p == {"entity_id": "climate.x", "target_temp_low": 66.0, "target_temp_high": 80.0}


@pytest.mark.parametrize("low,high", [(None, 75), (70, None)])
def test_payload_rejects_single_leg(low, high):
    with pytest.raises(ValueError):
        probe.build_range_payload("climate.x", low, high)


def test_payload_rejects_range_emptied_by_clamp():
    with pytest.raises(ValueError):
        probe.build_range_payload("climate.x", 85, 90)  # both clamp to 80


def test_all_planned_writes_are_in_band_and_two_legged():
    for lo, hi in probe.P2_WRITES + probe.P3_WRITES + [probe.P4_BASE]:
        p = probe.build_range_payload("climate.x", lo, hi)
        assert 66 <= p["target_temp_low"] < p["target_temp_high"] <= 80
    # plan: P2 includes a .5 value and 70 F; P3 includes the 2 F winter-home gap
    assert any(lo % 1 == 0.5 for lo, _ in probe.P2_WRITES)
    assert any(70.0 in pair for pair in probe.P2_WRITES)
    assert (70.0, 72.0) in probe.P3_WRITES


def test_assert_heat_cool_refuses_other_modes():
    probe.assert_heat_cool(_st())
    for mode in ("cool", "heat", "off", "unavailable"):
        with pytest.raises(probe.ProbeAbort):
            probe.assert_heat_cool(_st(state=mode))


def test_indoor_band():
    assert probe.indoor_in_band(_st(indoor=72))
    assert not probe.indoor_in_band(_st(indoor=65.9))
    assert not probe.indoor_in_band(_st(indoor=80.1))
    assert not probe.indoor_in_band(_st(indoor=None))  # unknown fails safe


def test_no_setpoint_hazard():
    assert probe.is_no_setpoint_state(_st(low=None, high=None, temp=None))
    assert not probe.is_no_setpoint_state(_st())
    assert not probe.is_no_setpoint_state(_st(state="cool", low=None, high=None, temp=74))


def test_single_leg_changed():
    tgt = (71.0, 76.0)
    assert probe.single_leg_changed((70, 75), (71, 75), tgt, 0.5)
    assert not probe.single_leg_changed((70, 75), (71, 76), tgt, 0.5)  # both moved
    assert not probe.single_leg_changed((70, 75), (70, 75), tgt, 0.5)  # nothing moved
    assert not probe.single_leg_changed((71, 70), (71, 76), (71, 76), 0.5)  # one moved but now at target


def test_percentile():
    assert probe.percentile([], 95) is None
    assert probe.percentile([5.0], 95) == 5.0
    assert probe.percentile([float(i) for i in range(1, 21)], 95) == 19.0
    assert probe.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0


# --- G-criteria ---------------------------------------------------------------
def _good():
    return {
        "preflight": {"hvac_modes": ["off", "heat", "cool", "heat_cool"]},
        "p0_notes": {"auto_heat_cool_enabled": True, "device_min_delta_f": 3.0},
        "p1": {"legs_present_in_heat_cool": True},
        "p2": {"tolerance_t_f": 0.2, "all_landed": True, "echo_p95_s": 8.0,
               "hold_persists_operator": True, "drift_events": 0, "single_leg_intermediates": []},
        "p3": {"device_min_delta_f": 3.0, "single_leg_intermediates": []},
        "p4": {"separable": True, "separability_evidence": "ok"},
        "restore": {"verified": True},
        "hazard_no_setpoint_states": [],
    }


def test_all_go():
    g = probe.evaluate_g(_good())
    assert all(g[k]["status"] == "GO" for k in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"))
    assert g["OVERALL"]["status"] == "GO"


def test_g2_tolerance_boundaries():
    r = _good()
    r["p2"]["tolerance_t_f"] = 0.6
    g = probe.evaluate_g(r)
    assert g["G2"]["status"] == "GO" and "PR2-4" in g["G2"]["evidence"]
    r["p2"]["tolerance_t_f"] = 1.1
    g = probe.evaluate_g(r)
    assert g["G2"]["status"] == "NO-GO" and g["OVERALL"]["status"] == "NO-GO"


def test_g3_echo_p95():
    r = _good()
    r["p2"]["echo_p95_s"] = 121.0
    assert probe.evaluate_g(r)["G3"]["status"] == "NO-GO"


def test_g5_q4_acceptance():
    r = _good()
    r["p4"] = {"separable": False, "separability_evidence": "close"}
    assert probe.evaluate_g(r)["G5"]["status"] == "NO-GO"
    r["p0_notes"]["q4_accepted"] = True
    assert probe.evaluate_g(r)["G5"]["status"] == "GO"


def test_g6_drift_is_no_go():
    r = _good()
    r["p2"]["drift_events"] = 1
    assert probe.evaluate_g(r)["G6"]["status"] == "NO-GO"


def test_g1_needs_auto():
    r = _good()
    r["p0_notes"]["auto_heat_cool_enabled"] = False
    g = probe.evaluate_g(r)
    assert g["G1"]["status"] == "NO-GO" and g["OVERALL"]["status"] == "NO-GO"


def test_restore_failure_is_overall_no_go():
    r = _good()
    r["restore"] = {"verified": False, "detail": "x"}
    g = probe.evaluate_g(r)
    assert g["G7"]["status"] == "NO-GO" and g["OVERALL"]["status"] == "NO-GO"


@pytest.mark.parametrize("mutate", [
    lambda r: r["hazard_no_setpoint_states"].append({"state": "heat_cool"}),
    lambda r: r["p2"]["single_leg_intermediates"].append({"low": 71, "high": 75}),
    lambda r: r["p3"]["single_leg_intermediates"].append({"low": 71, "high": 75}),
])
def test_hard_no_go_overrides(mutate):
    r = _good()
    mutate(r)
    assert probe.evaluate_g(r)["OVERALL"]["status"] == "NO-GO"


def test_missing_steps_are_unknown_not_go():
    g = probe.evaluate_g({"restore": {"verified": True}})
    assert g["G2"]["status"] == "UNKNOWN" and g["G3"]["status"] == "UNKNOWN"
    assert g["OVERALL"]["status"] == "NO-GO"

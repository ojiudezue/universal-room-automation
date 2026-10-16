"""Review D (adversarial completeness) probes for EV-FILL-PRIORITY-SOC-CHATTER-1.

Characterization + leak probes. Each test drives the REAL controller.
"""
from __future__ import annotations

from test_ev_fill_priority_repause_band import (  # noqa: F401
    _A, _B, _SW_A, _SW_B, _PLUG, _ev, _plug, _apply, _offs, _ons, _fp, _pfp,
    _latch_ev, _latch_plug,
)


def test_d_envoy_jump_79_81_76_pauses_on_drop():
    ev, hass = _ev()
    _latch_ev(ev, hass)  # 79 pause -> 80 resume
    _apply(hass, _fp(ev, 81))
    acts = _fp(ev, 76)
    assert len(_offs(acts)) == 1 and _A in ev._paused_by_fill_priority


def test_d_envoy_jump_81_to_77_5_holds_then_76_9_pauses():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    _apply(hass, _fp(ev, 81))
    assert _offs(_fp(ev, 77.5)) == []
    assert len(_offs(_fp(ev, 76.9))) == 1


def test_d_two_chargers_latch_is_per_id():
    ev, hass = _ev(ids=(_A, _B))
    # A pauses+resumes (latched); B also pauses then resumes in the same ticks.
    acts = _fp(ev, 79); _apply(hass, acts)
    acts = _fp(ev, 80); _apply(hass, acts)
    assert {_A, _B} <= set(ev._recently_released_by_fill_priority)
    # B removed from latch by a peer steal (arbitrage) -> next FP tick drops it
    ev._paused_by_arbitrage.add(_B)
    _fp(ev, 78)
    assert _B not in ev._recently_released_by_fill_priority
    assert _A in ev._recently_released_by_fill_priority


def test_d_latch_and_fp_set_disjoint_through_sequence():
    ev, hass = _ev(ids=(_A, _B))
    for soc in (79, 80, 79, 78, 77, 76.9, 78, 80, 79, 81, 76, 80):
        _apply(hass, _fp(ev, soc))
        assert not (set(ev._recently_released_by_fill_priority)
                    & ev._paused_by_fill_priority), soc


def test_d_soc_none_preserves_latch():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    _fp(ev, None)
    assert _A in ev._recently_released_by_fill_priority
    assert _offs(_fp(ev, 78)) == []


def _superseded_threshold_lowered():
    """LOW characterization: latch from threshold=80 suppresses the first
    pause under a newly-lowered threshold=70 until SOC < 67."""
    ev, hass = _ev()
    _latch_ev(ev, hass)
    assert _offs(_fp(ev, 68, threshold=70)) == []
    assert len(_offs(_fp(ev, 66.9, threshold=70))) == 1


def test_d_threshold_raised_while_latched_pauses():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    assert len(_offs(_fp(ev, 85, threshold=90))) == 1


def test_d_plug_jump_and_inert_discharge():
    p, hass = _plug()
    _latch_plug(p, hass)
    assert _offs(_pfp(p, 78), _PLUG) == []
    _pfp(p, 78, tou="peak")
    assert _PLUG not in p._recently_released_by_fill_priority
    assert len(_offs(_pfp(p, 79), _PLUG)) == 1


# ---- Re-verify after fix-ups (HEAD ccb1c9559) ----

def test_d2_offpeak_hold_does_not_wipe_latch_but_floor_still_pops():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    ev._proactive_offpeak_holds.add(_A)
    hass.set_state(_SW_A, "off")
    _fp(ev, 78)
    assert _A in ev._recently_released_by_fill_priority
    acts = _fp(ev, 76.9)  # held OFF by offpeak only: latch pops, no FP claim
    assert _A not in ev._recently_released_by_fill_priority
    assert _offs(acts) == [] and _A not in ev._paused_by_fill_priority


def test_d2_offpeak_daylight_to_peak_boundary_discharges():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    ev._proactive_offpeak_holds.add(_A)
    _fp(ev, 78, tou="peak")
    assert _A not in ev._recently_released_by_fill_priority


def test_d2_offpeak_claim_then_real_steal_drops_latch():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    ev._proactive_offpeak_holds.add(_A)
    ev._paused_by_battery_drain.add(_A)
    _fp(ev, 78)
    assert _A not in ev._recently_released_by_fill_priority


def test_d2_threshold_lowered_now_first_pause_fires():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    assert len(_offs(_fp(ev, 68, threshold=70))) == 1


def test_d2_threshold_change_with_soc_none_clears_conservatively():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    _fp(ev, None, threshold=81)
    assert _A not in ev._recently_released_by_fill_priority


def test_d2_same_threshold_float_int_keeps_latch():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    assert _offs(_fp(ev, 78, threshold=80.0)) == []


def test_d2_plug_offpeak_hold_keeps_latch_and_threshold_clears():
    p, hass = _plug()
    _latch_plug(p, hass)
    p._proactive_offpeak_holds.add(_PLUG)
    _pfp(p, 78)
    assert _PLUG in p._recently_released_by_fill_priority
    assert len(_offs(_pfp(p, 68, threshold=70), _PLUG)) == 1

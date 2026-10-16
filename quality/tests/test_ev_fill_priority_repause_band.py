"""EV-FILL-PRIORITY-SOC-CHATTER-1 — fill-priority SOC re-pause band.

Plan: docs/planning/PLANNING_ev_fill_priority_soc_buffer.md (Rev 3, Tier 3).

INV-1  latched id (prior SOC-reached resume, no discharge since) with SOC in
       [threshold - band, threshold) never changes FP membership; SOC == floor
       (77.0) is INSIDE the band, 76.9 pauses.
INV-2  first pause (no latch) unchanged: soc < threshold.
INV-3  SOC strictly below the floor pauses on the next tick.
INV-4  an unlatched charger behaves exactly as develop on every path.

Every test drives the REAL controller methods (and the REAL
`EnergyCoordinator._decision_cycle_body` for the call-site / observation-mode
anchors). Expected values are hand-derived literals from plan §6/§7, never
computed from the code under test. FP ticks call
`determine_fill_priority_actions` WITHOUT `repause_band_pct=` unless the test
is a config-extreme case, so the shipped default is what is exercised.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_pool as _epool,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
    SmartPlugController,
)

_A = "garage_a"
_B = "garage_b"
_SW_A = "switch.garage_a"
_SW_B = "switch.garage_b"
_PLUG = "switch.socket_1"


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

def _ev(ids=(_A,), on=True):
    hass = MockHass()
    cfg = {}
    for eid in ids:
        sw = f"switch.{eid}"
        pw = f"sensor.{eid}_power"
        hass.set_state(sw, "on" if on else "off")
        hass.set_state(pw, "7000" if on else "0",
                       attributes={"unit_of_measurement": "W"})
        cfg[eid] = {"switch": sw, "power": pw}
    return EVChargerController(hass, evse_config=cfg), hass


def _plug(on=True):
    hass = MockHass()
    hass.set_state(_PLUG, "on" if on else "off")
    return SmartPlugController(hass=hass, plug_entities=[_PLUG]), hass


def _apply(hass, actions):
    """Model the dispatch landing: switch state follows the action."""
    for a in actions:
        if a["service"] == "switch.turn_off":
            hass.set_state(a["target"], "off")
        elif a["service"] == "switch.turn_on":
            hass.set_state(a["target"], "on")


def _offs(actions, target=_SW_A):
    return [a for a in actions
            if a["service"] == "switch.turn_off" and a["target"] == target]


def _ons(actions, target=_SW_A):
    return [a for a in actions
            if a["service"] == "switch.turn_on" and a["target"] == target]


def _fp(ev, soc, *, forecast=18.0, tou="off_peak", daylight=True,
        threshold=80, **kw):
    return ev.determine_fill_priority_actions(
        soc=soc, remaining_forecast_kwh=forecast, tou_period=tou,
        soc_threshold=threshold, excess_solar_kwh_threshold=5.0,
        is_daylight=daylight, **kw,
    )


def _pfp(p, soc, *, forecast=18.0, tou="off_peak", daylight=True,
         threshold=80, **kw):
    return p.determine_fill_priority_actions(
        soc=soc, remaining_forecast_kwh=forecast, tou_period=tou,
        soc_threshold=threshold, excess_solar_kwh_threshold=5.0,
        is_daylight=daylight, **kw,
    )


def _latch_ev(ev, hass, threshold=80, eid=_A, **kw):
    """Drive a REAL first pause + SOC-reached resume so the latch is set by
    production code (never seeded by hand)."""
    below = threshold - 1
    acts = _fp(ev, below, threshold=threshold, **kw)
    assert len(_offs(acts, f"switch.{eid}")) == 1
    _apply(hass, acts)
    acts = _fp(ev, threshold, threshold=threshold, **kw)
    assert len(_ons(acts, f"switch.{eid}")) == 1
    _apply(hass, acts)
    assert eid not in ev._paused_by_fill_priority
    assert eid in ev._recently_released_by_fill_priority


def _latch_plug(p, hass, threshold=80, **kw):
    acts = _pfp(p, threshold - 1, threshold=threshold, **kw)
    assert len(_offs(acts, _PLUG)) == 1
    _apply(hass, acts)
    acts = _pfp(p, threshold, threshold=threshold, **kw)
    assert len(_ons(acts, _PLUG)) == 1
    _apply(hass, acts)
    assert _PLUG in p._recently_released_by_fill_priority


# --------------------------------------------------------------------------
# Constant / knob
# --------------------------------------------------------------------------

def test_band_constant_pinned_and_below_fill_soc():
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const,
    )
    assert energy_const.DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT == 3
    assert (0 <= energy_const.DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT
            < energy_const.DEFAULT_FILL_PRIORITY_SOC)


# --------------------------------------------------------------------------
# A1 — INV-1 (no chatter) / A2 — INV-2 / A3 — INV-3 + 77 boundary
# --------------------------------------------------------------------------

def test_a1_latched_walk_80_79_no_membership_transitions():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    for soc in (79.0, 80.0, 79.0, 78.0, 77.0):
        acts = _fp(ev, soc)
        assert acts == [], f"SOC {soc}: latched charger toggled: {acts}"
        assert _A not in ev._paused_by_fill_priority
        _apply(hass, acts)


def test_a2_fresh_charger_first_pause_unchanged():
    ev, _ = _ev()
    acts = _fp(ev, 78.0)
    assert len(_offs(acts)) == 1
    assert _A in ev._paused_by_fill_priority


def test_a2_fresh_charger_at_79_9_pauses():
    ev, _ = _ev()
    assert len(_offs(_fp(ev, 79.9))) == 1


def test_a3_soc_77_0_inside_band_no_pause():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    acts = _fp(ev, 77.0)
    assert _offs(acts) == []
    assert _A in ev._recently_released_by_fill_priority


def test_a3_soc_76_9_below_floor_pauses_next_tick():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    acts = _fp(ev, 76.9)
    assert len(_offs(acts)) == 1
    assert _A in ev._paused_by_fill_priority
    assert _A not in ev._recently_released_by_fill_priority


def test_a3_plug_boundary_77_0_holds_76_9_pauses():
    p, hass = _plug()
    _latch_plug(p, hass)
    assert _offs(_pfp(p, 77.0), _PLUG) == []
    assert len(_offs(_pfp(p, 76.9), _PLUG)) == 1


# --------------------------------------------------------------------------
# A4 — kill switch via the CALL-TIME module attribute (same surface prod reads)
# --------------------------------------------------------------------------

def test_a4_module_attribute_band_zero_restores_legacy_chatter(monkeypatch):
    monkeypatch.setattr(
        _epool._energy_const, "DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT", 0,
    )
    ev, hass = _ev()
    _latch_ev(ev, hass)
    acts = _fp(ev, 79.0)
    assert len(_offs(acts)) == 1, "band 0 must reproduce the legacy re-pause"
    _apply(hass, acts)
    acts = _fp(ev, 80.0)
    assert len(_ons(acts)) == 1


def test_a4_plug_module_attribute_band_zero(monkeypatch):
    monkeypatch.setattr(
        _epool._energy_const, "DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT", 0,
    )
    p, hass = _plug()
    _latch_plug(p, hass)
    assert len(_offs(_pfp(p, 79.0), _PLUG)) == 1


def test_band_zero_sequence_matches_legacy_oracle():
    """INV-4 / A4: band 0 action sequence for an 79→80→79→80 walk is the
    hand-written legacy chatter: off, on, off, on."""
    ev, hass = _ev()
    seq = []
    for soc in (79.0, 80.0, 79.0, 80.0):
        acts = _fp(ev, soc, repause_band_pct=0)
        seq.append([a["service"] for a in acts])
        _apply(hass, acts)
    assert seq == [["switch.turn_off"], ["switch.turn_on"],
                   ["switch.turn_off"], ["switch.turn_on"]]


def test_default_band_sequence_oracle():
    ev, hass = _ev()
    seq = []
    for soc in (79.0, 80.0, 79.0, 80.0, 79.0, 76.9):
        acts = _fp(ev, soc)
        seq.append([a["service"] for a in acts])
        _apply(hass, acts)
    assert seq == [["switch.turn_off"], ["switch.turn_on"], [], [], [],
                   ["switch.turn_off"]]


# --------------------------------------------------------------------------
# Config extremes (plan §7)
# --------------------------------------------------------------------------

def test_extreme_band_100_fresh_soc_50_pauses():
    ev, _ = _ev()
    assert len(_offs(_fp(ev, 50.0, repause_band_pct=100))) == 1


def test_extreme_band_100_latched_floor_zero_no_repause():
    ev, hass = _ev()
    _latch_ev(ev, hass, repause_band_pct=100)
    assert _fp(ev, 50.0, repause_band_pct=100) == []
    assert _fp(ev, 1.0, repause_band_pct=100) == []


def test_extreme_negative_band_clamps_to_legacy():
    ev, hass = _ev()
    _latch_ev(ev, hass, repause_band_pct=-5)
    assert len(_offs(_fp(ev, 79.0, repause_band_pct=-5))) == 1
    assert _A not in ev._recently_released_by_fill_priority


def test_extreme_negative_band_fresh_soc_50_pauses():
    ev, _ = _ev()
    assert len(_offs(_fp(ev, 50.0, repause_band_pct=-5))) == 1


@pytest.mark.parametrize("soc,expect_pause", [(47.0, False), (46.9, True)])
def test_extreme_slider_min_50_band_default(soc, expect_pause):
    ev, hass = _ev()
    _latch_ev(ev, hass, threshold=50)
    acts = _fp(ev, soc, threshold=50)
    assert bool(_offs(acts)) is expect_pause


@pytest.mark.parametrize("soc", [50.0, 49.0])
def test_extreme_slider_min_50_fresh(soc):
    ev, _ = _ev()
    acts = _fp(ev, soc, threshold=50)
    # 50.0 is not < 50 → no pause; 49 → first-pause edge.
    assert bool(_offs(acts)) is (soc == 49.0)


@pytest.mark.parametrize("soc", [47.0, 46.9])
def test_extreme_slider_min_50_band_zero_legacy(soc):
    ev, hass = _ev()
    _latch_ev(ev, hass, threshold=50, repause_band_pct=0)
    assert len(_offs(_fp(ev, soc, threshold=50, repause_band_pct=0))) == 1


def test_extreme_threshold_80_band_zero_77_pauses():
    ev, hass = _ev()
    _latch_ev(ev, hass, repause_band_pct=0)
    assert len(_offs(_fp(ev, 77.0, repause_band_pct=0))) == 1


# --------------------------------------------------------------------------
# A6 — plug parity + grid-charge M1 held resume sets no latch
# --------------------------------------------------------------------------

def test_a6_plug_band_suppresses_chatter():
    p, hass = _plug()
    _latch_plug(p, hass)
    for soc in (79.0, 80.0, 79.0, 77.0):
        acts = _pfp(p, soc)
        assert acts == []
        assert _PLUG not in p._paused_by_fill_priority


def test_a6_plug_grid_charge_held_resume_sets_no_latch():
    p, hass = _plug()
    acts = _pfp(p, 79.0)
    _apply(hass, acts)
    assert _PLUG in p._paused_by_fill_priority
    acts = _pfp(p, 80.0, grid_charge_on=True)
    assert _ons(acts, _PLUG) == []
    assert _PLUG in p._paused_by_fill_priority
    assert p._recently_released_by_fill_priority == {}


# --------------------------------------------------------------------------
# A7 — D3 force-charge clears the latch unconditionally
# --------------------------------------------------------------------------

def test_a7_force_charge_clears_latch_then_first_pause_at_79():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    ev._is_force_charge_active = lambda: True
    assert _fp(ev, 79.0) == []
    assert _A not in ev._recently_released_by_fill_priority
    ev._is_force_charge_active = lambda: False
    assert len(_offs(_fp(ev, 79.0))) == 1


def test_a7_plug_force_charge_clears_latch():
    p, hass = _plug()
    _latch_plug(p, hass)
    _pfp(p, 79.0, force_charge_active=True)
    assert p._recently_released_by_fill_priority == {}
    assert len(_offs(_pfp(p, 79.0), _PLUG)) == 1


# --------------------------------------------------------------------------
# A8 — D2 cross-owner steal (one case per peer)
# --------------------------------------------------------------------------

_EV_PEERS = [
    "_paused_by_grid_cap", "_paused_by_battery_drain", "_paused_by_us",
    "_paused_by_arbitrage", "_paused_by_load_shed", "_paused_by_blind_window",
    "_paused_by_dp",
]
# Review A-HIGH-1: `_proactive_offpeak_holds` is ensure-on's own recurring
# claim, NOT a steal — deliberately absent (see the ensure-on tests below).
_PLUG_PEERS = [
    "_paused_by_us", "_paused_by_battery_drain", "_paused_by_load_shed",
]


# --------------------------------------------------------------------------
# Review A-HIGH-1 — off-peak daylight: ensure-on's own claim must NOT wipe
# the latch (REAL determine_actions + REAL FP tick, EV and plug)
# --------------------------------------------------------------------------

def test_a_high_1_ev_offpeak_ensure_on_does_not_discharge_latch():
    ev, hass = _ev()
    acts = _fp(ev, 79.0)                      # off_peak daylight, healthy
    assert len(_offs(acts)) == 1
    _apply(hass, acts)
    acts = _fp(ev, 80.0)                      # SOC-reached resume → latch
    assert len(_ons(acts)) == 1
    _apply(hass, acts)
    assert _A in ev._recently_released_by_fill_priority
    _apply(hass, ev.determine_actions("off_peak", grid_charge_on=False))
    assert _A in ev._proactive_offpeak_holds  # ensure-on claimed it
    acts = _fp(ev, 79.0)
    assert _offs(acts) == [], "ensure-on claim wiped the latch → re-pause"
    assert _A in ev._recently_released_by_fill_priority
    _apply(hass, ev.determine_actions("off_peak", grid_charge_on=False))
    assert len(_offs(_fp(ev, 76.9))) == 1


def test_a_high_1_plug_offpeak_ensure_on_does_not_discharge_latch():
    p, hass = _plug()
    acts = _pfp(p, 79.0)
    assert len(_offs(acts, _PLUG)) == 1
    _apply(hass, acts)
    acts = _pfp(p, 80.0)
    assert len(_ons(acts, _PLUG)) == 1
    _apply(hass, acts)
    _apply(hass, p.determine_actions("off_peak", grid_charge_on=False))
    assert _PLUG in p._proactive_offpeak_holds
    acts = _pfp(p, 79.0)
    assert _offs(acts, _PLUG) == []
    _apply(hass, p.determine_actions("off_peak", grid_charge_on=False))
    assert len(_offs(_pfp(p, 76.9), _PLUG)) == 1


# --------------------------------------------------------------------------
# Review D-L1 — threshold change discharges the latch
# --------------------------------------------------------------------------

def test_d_l1_threshold_lowered_first_pause_fires():
    ev, hass = _ev()
    _latch_ev(ev, hass)                        # latched under 80
    acts = _fp(ev, 69.0, threshold=70)
    assert len(_offs(acts)) == 1, "latch from threshold 80 suppressed 70's first pause"
    assert ev._recently_released_by_fill_priority == {}


def test_d_l1_plug_threshold_lowered_first_pause_fires():
    p, hass = _plug()
    _latch_plug(p, hass)
    assert len(_offs(_pfp(p, 69.0, threshold=70), _PLUG)) == 1


def test_d_l1_unchanged_threshold_keeps_latch():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    assert _fp(ev, 79.0, threshold=80) == []
    assert ev._recently_released_by_fill_priority == {_A: 80}


@pytest.mark.parametrize("peer", _EV_PEERS)
def test_a8_ev_peer_steal_clears_latch(peer):
    ev, hass = _ev()
    _latch_ev(ev, hass)
    getattr(ev, peer).add(_A)
    hass.set_state(_SW_A, "off")
    _fp(ev, 79.0)
    assert _A not in ev._recently_released_by_fill_priority, peer
    # Peer releases at 78; charger back ON → first-pause edge fires.
    getattr(ev, peer).discard(_A)
    hass.set_state(_SW_A, "on")
    assert len(_offs(_fp(ev, 78.0))) == 1, peer


@pytest.mark.parametrize("peer", _PLUG_PEERS)
def test_a8_plug_peer_steal_clears_latch(peer):
    p, hass = _plug()
    _latch_plug(p, hass)
    getattr(p, peer).add(_PLUG)
    hass.set_state(_PLUG, "off")
    _pfp(p, 79.0)
    assert p._recently_released_by_fill_priority == {}, peer
    getattr(p, peer).discard(_PLUG)
    hass.set_state(_PLUG, "on")
    assert len(_offs(_pfp(p, 78.0), _PLUG)) == 1, peer


# --------------------------------------------------------------------------
# A9 — D1 inert window discharges the latch (overnight repro)
# --------------------------------------------------------------------------

def test_a9_inert_night_clears_latch_morning_first_pause_at_79():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    assert _fp(ev, 90.0, daylight=False) == []   # off_peak night → inert
    assert ev._recently_released_by_fill_priority == {}
    assert len(_offs(_fp(ev, 79.0, daylight=True))) == 1


@pytest.mark.parametrize("tou,kw", [("peak", {}),
                                    ("mid_peak", {"peak_ahead": False})])
def test_a9_other_inert_periods_clear_latch(tou, kw):
    ev, hass = _ev()
    _latch_ev(ev, hass)
    _fp(ev, 79.0, tou=tou, **kw)
    assert ev._recently_released_by_fill_priority == {}


def test_a9_plug_inert_clears_latch():
    p, hass = _plug()
    _latch_plug(p, hass)
    _pfp(p, 90.0, daylight=False)
    assert p._recently_released_by_fill_priority == {}
    assert len(_offs(_pfp(p, 79.0), _PLUG)) == 1


# --------------------------------------------------------------------------
# A10 — forecast-decay resume does NOT latch
# --------------------------------------------------------------------------

def test_a10_forecast_decay_resume_no_latch_then_legacy_repause():
    ev, hass = _ev()
    acts = _fp(ev, 78.0)
    _apply(hass, acts)
    acts = _fp(ev, 78.0, forecast=3.0)      # 3.0 <= 5.0 - 1.0 → decayed
    assert len(_ons(acts)) == 1
    _apply(hass, acts)
    assert ev._recently_released_by_fill_priority == {}
    assert len(_offs(_fp(ev, 78.0))) == 1


def test_a10_plug_forecast_decay_no_latch():
    p, hass = _plug()
    _apply(hass, _pfp(p, 78.0))
    acts = _pfp(p, 78.0, forecast=3.0)
    assert len(_ons(acts, _PLUG)) == 1
    assert p._recently_released_by_fill_priority == {}


# --------------------------------------------------------------------------
# A11 / A12 — D5 sweep (OFF chargers; SOC None no-op)
# --------------------------------------------------------------------------

def test_a11_sweep_runs_for_off_charger():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    hass.set_state(_SW_A, "off")
    _fp(ev, 76.0)
    assert ev._recently_released_by_fill_priority == {}


def test_a11_plug_sweep_off():
    p, hass = _plug()
    _latch_plug(p, hass)
    hass.set_state(_PLUG, "off")
    _pfp(p, 76.0)
    assert p._recently_released_by_fill_priority == {}


def test_a12_soc_none_leaves_latch_untouched():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    assert _fp(ev, None) == []
    assert _A in ev._recently_released_by_fill_priority
    assert _fp(ev, 78.0) == []


def test_a12_plug_soc_none():
    p, hass = _plug()
    _latch_plug(p, hass)
    _pfp(p, None)
    assert _PLUG in p._recently_released_by_fill_priority
    assert _pfp(p, 78.0) == []


# --------------------------------------------------------------------------
# A13 — REAL arbitrage hand-off, two chargers (per-id peer term, INV-4)
# --------------------------------------------------------------------------

def test_a13_arbitrage_handoff_latched_vs_unlatched_sibling():
    ev, hass = _ev(ids=(_A, _B), on=True)
    # garage_b is OFF from the start so FP never claims it; garage_a goes
    # through a REAL pause + SOC-reached resume → latched.
    hass.set_state(_SW_B, "off")
    _latch_ev(ev, hass)
    # FP tick at 78 (B still OFF → unclaimed; A latched → not re-paused)
    # publishes the GLOBAL would-hold verdict (unchanged producer).
    assert _fp(ev, 78.0) == []
    assert ev._fill_priority_would_hold is True
    # Grid charging: arbitrage pauses both chargers (B switched on first).
    hass.set_state(_SW_B, "on")
    acts = ev.determine_arbitrage_actions(
        arbitrage_charging=True, tou_period="off_peak", pause_reason="breaker",
    )
    _apply(hass, acts)
    assert {_A, _B} <= ev._paused_by_arbitrage
    # Grid charging ends on the next tick, before FP runs again.
    acts = ev.determine_arbitrage_actions(
        arbitrage_charging=False, tou_period="off_peak", grid_charge_on=False,
    )
    # Unlatched sibling: develop behaviour — handed to FP, no turn_on.
    assert _B in ev._paused_by_fill_priority
    assert _ons(acts, _SW_B) == []
    # Latched charger: NOT handed off (falls through to arbitrage turn_on).
    assert _A not in ev._paused_by_fill_priority
    assert len(_ons(acts, _SW_A)) == 1


def test_a13_unlatched_single_charger_handoff_unchanged():
    """INV-4: no latch → hand-off exactly as develop."""
    ev, hass = _ev(on=True)
    acts = ev.determine_arbitrage_actions(
        arbitrage_charging=True, tou_period="off_peak", pause_reason="breaker",
    )
    _apply(hass, acts)
    _fp(ev, 78.0)
    assert ev._fill_priority_would_hold is True
    acts = ev.determine_arbitrage_actions(
        arbitrage_charging=False, tou_period="off_peak", grid_charge_on=False,
    )
    assert _ons(acts) == []
    assert _A in ev._paused_by_fill_priority


# --------------------------------------------------------------------------
# D4 — release_all_fill_priority (EV + plug, plug clear before grid return)
# --------------------------------------------------------------------------

def test_d4_ev_release_all_clears_latch():
    ev, hass = _ev()
    _latch_ev(ev, hass)
    ev.release_all_fill_priority()
    assert ev._recently_released_by_fill_priority == {}
    assert len(_offs(_fp(ev, 79.0))) == 1


def test_d4_plug_release_all_clears_latch():
    p, hass = _plug()
    _latch_plug(p, hass)
    p.release_all_fill_priority()
    assert p._recently_released_by_fill_priority == {}


def test_d4_plug_release_all_clears_latch_before_grid_charge_return():
    p, hass = _plug()
    _latch_plug(p, hass)
    p.release_all_fill_priority(grid_charge_on=True)
    assert p._recently_released_by_fill_priority == {}
    assert len(_offs(_pfp(p, 79.0), _PLUG)) == 1


# --------------------------------------------------------------------------
# A14 — restart: FP set restored from KV, latch is cold
# --------------------------------------------------------------------------

class _KVDB:
    def __init__(self, rows):
        self.rows = rows

    async def restore_energy_state_with_age(self, key, max_age_hours=None):
        return self.rows.get(key)


@pytest.mark.asyncio
async def test_a14_restore_restores_fp_set_latch_stays_cold():
    import json
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    ev, hass = _ev(on=False)
    shell = SimpleNamespace(_ev=ev)
    db = _KVDB({"evse_fill_priority_paused": json.dumps([_A])})
    await EnergyCoordinator._restore_registry_owner_lists(shell, db, 10.0, {_A})
    assert _A in ev._paused_by_fill_priority
    assert ev._recently_released_by_fill_priority == {}
    # Restored member at 78 stays held (no toggle); at 80 it resumes once
    # and latches via the normal producer.
    assert _fp(ev, 78.0) == []
    acts = _fp(ev, 80.0)
    assert len(_ons(acts)) == 1
    assert _A in ev._recently_released_by_fill_priority


def test_a14_cold_latch_in_band_at_most_one_toggle():
    """Resumed EV in band after restart (latch lost): exactly one
    first-pause edge, then the normal cycle."""
    ev, _ = _ev(on=True)
    assert len(_offs(_fp(ev, 78.0))) == 1


# --------------------------------------------------------------------------
# A16 — prune on removal
# --------------------------------------------------------------------------

def test_a16_prune_pops_latch_for_removed_evse():
    ev, _ = _ev()
    ev._recently_released_by_fill_priority["garage_gone"] = 1.0
    ev._recently_released_by_fill_priority[_A] = 80
    ev._prune_removed_evses()
    assert ev._recently_released_by_fill_priority == {_A: 80}


def test_a16_prune_pops_latch_for_removed_plug():
    p, _ = _plug()
    p._recently_released_by_fill_priority["switch.gone"] = 1.0
    p._recently_released_by_fill_priority[_PLUG] = 80
    p.prune_removed_plugs()
    assert p._recently_released_by_fill_priority == {_PLUG: 80}


# --------------------------------------------------------------------------
# Producer discrimination: an already-ON resume also latches only on SOC
# --------------------------------------------------------------------------

def test_producer_sets_latch_only_on_soc_reached():
    ev, hass = _ev()
    _apply(hass, _fp(ev, 79.0))
    assert ev._recently_released_by_fill_priority == {}
    _fp(ev, 80.0)
    assert _A in ev._recently_released_by_fill_priority


# --------------------------------------------------------------------------
# Wire-in: REAL `_decision_cycle_body` (energy.py FP call site + D6)
# --------------------------------------------------------------------------

from test_ec_degraded_data_p1 import (  # noqa: E402
    _NATIVE, _cycle_shell, _st, _strategy,
    clock, mono,  # noqa: F401 — fixtures
)


def _cycle(clock, soc="78"):
    s, hass, _ = _strategy(clock, stream=False)
    _st(hass, _NATIVE, soc, unit="%", lu=clock.t)
    hass.set_state(_SW_A, "on")
    hass.set_state("sensor.garage_a_power", "7000",
                   attributes={"unit_of_measurement": "W"})
    hass.set_state(_PLUG, "off")
    ev = EVChargerController(hass, evse_config={_A: {
        "switch": _SW_A, "power": "sensor.garage_a_power",
    }})
    c = _cycle_shell(clock, s, hass, ev)
    plugs = SmartPlugController(hass=hass, plug_entities=[_PLUG])
    c._smart_plugs = plugs
    c._ev_tou_enabled = False
    c._excess_solar_enabled = True
    c._excess_solar_kwh = 3.0
    c._fill_priority_soc = 80
    c._grid_import_cap_enabled = False
    c._grid_import_cap_kw = 12.0
    c._dp_carrier = None
    c._dp_must_start_by_min = None
    c._last_soc_recovered = False

    async def _anoop(*a, **k):
        return None
    c._check_fill_priority_nm_trip = _anoop
    c._post_excess_solar_bookkeeping = lambda *a, **k: None
    c._send_nm_alert = _anoop
    return c, ev, plugs, hass


def _cycle_offs(c):
    return [d for d in c.dispatched
            if d.get("service") == "switch.turn_off" and d.get("target") == _SW_A]


@pytest.mark.asyncio
async def test_callsite_unlatched_pauses_at_78(clock, mono):
    c, ev, _, _ = _cycle(clock)
    await c._decision_cycle_body()
    assert len(_cycle_offs(c)) == 1
    assert _A in ev._paused_by_fill_priority


@pytest.mark.asyncio
async def test_callsite_latched_no_pause_at_78_default_band(clock, mono):
    c, ev, _, _ = _cycle(clock)
    ev._recently_released_by_fill_priority[_A] = 80
    await c._decision_cycle_body()
    assert _cycle_offs(c) == []
    assert _A in ev._recently_released_by_fill_priority


@pytest.mark.asyncio
async def test_callsite_band_read_at_call_time(clock, mono, monkeypatch):
    """A4 through the production call site: patching the module attribute
    AFTER import changes the decision (band 0 → 78 is below floor 80)."""
    monkeypatch.setattr(
        _epool._energy_const, "DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT", 0,
    )
    c, ev, _, _ = _cycle(clock)
    ev._recently_released_by_fill_priority[_A] = 80
    await c._decision_cycle_body()
    assert len(_cycle_offs(c)) == 1
    assert ev._recently_released_by_fill_priority == {}


@pytest.mark.asyncio
async def test_a15_observation_mode_clears_both_latches(clock, mono):
    c, ev, plugs, _ = _cycle(clock)
    ev._recently_released_by_fill_priority[_A] = 80
    plugs._recently_released_by_fill_priority[_PLUG] = 80
    c._observation_mode = True
    for _ in range(3):
        await c._decision_cycle_body()
    assert _cycle_offs(c) == []
    assert ev._recently_released_by_fill_priority == {}
    assert plugs._recently_released_by_fill_priority == {}
    # Exit observation mode: first normal tick at 78 pauses (legacy edge).
    c._observation_mode = False
    await c._decision_cycle_body()
    assert len(_cycle_offs(c)) == 1

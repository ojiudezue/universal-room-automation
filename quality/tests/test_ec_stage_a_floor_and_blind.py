"""EC storm/blind Stage A — one floor, one writer, blind decisions.

PLANNING_ec_storm_and_blind_decisions.md Rev 3.3, Stage A (D-A2, D-A3, D-A4)
and §12 config extremes.

INV-1 (floor by construction): in any determine_mode call whose decision
holds (partial/full), every `_reserve_action` output and the post-tick
`_last_reserve_level_desired` are >= decision.reserve_floor; therefore the
EVSE overlay (which composes from the stamp) emits >= it.
INV-2 (blind command surface): while fully blind, at most ONE reserve
set_value per tick from the decision, the pre-existing top-rate turn_off,
never a CFG turn_on / select / `_desired_stamped_at` refresh; release
restores the captured pre-raise value.

Harness: REAL BatteryStrategy + REAL EnergyCoordinator dispatch/overlay
(`_reserve_governor_harness`), frozen `dt_util.now/utcnow` (`clock`). The
per-tick inclement cache seam (`seed_inclement`) or a real NWS alert entity
drives the decision. No real time is read.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    RESERVE_WRITE_EID,
    _CDT,
    _SOC,
    _settle,
    _st,
    clock,
    make_shell,
    seed_inclement,
)
from ec_phalanx_entities import PHALANX_RESERVE_SOC_ENTITY

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    BATTERY_MODE_SELF_CONSUMPTION,
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
    CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

_UTC = timezone.utc
OCT_18 = datetime(2026, 10, 15, 23, 0, tzinfo=_UTC)  # 18:00 CDT, shoulder mid_peak (top)
OCT_19 = datetime(2026, 10, 16, 0, 0, tzinfo=_UTC)   # 19:00 CDT, still top
OCT_03 = datetime(2026, 10, 15, 8, 0, tzinfo=_UTC)   # 03:00 CDT, off_peak (bottom)
OCT_04 = datetime(2026, 10, 15, 9, 0, tzinfo=_UTC)   # 04:00 CDT
OCT_05 = datetime(2026, 10, 15, 10, 0, tzinfo=_UTC)  # 05:00 CDT
OCT_16 = datetime(2026, 10, 15, 21, 0, tzinfo=_UTC)  # 16:00 CDT, off_peak
JUN_15 = datetime(2026, 6, 15, 20, 0, tzinfo=_UTC)   # 15:00 CDT, summer mid_peak
_NWS = "sensor.stage_a_nws_alerts"
_CFG_SURFACES = ("switch.turn_on", "select.select_option")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def shell(clock, *, blind, cfg="off", hw="0", reserve_soc=10, soc="45",
          tou=True, opts=None, peak_buffer_target=30):
    c, s = make_shell(
        clock, soc=("unavailable" if blind else soc), reserve_state=hw,
        cfg_state=cfg, peak_buffer_target=peak_buffer_target,
    )
    if blind:
        s._soc_lkg = None
        s._soc_lkg_at = None
    s.reserve_soc = reserve_soc
    if tou:
        s._tou = TOURateEngine()
    if opts is not None:
        s._inclement_config_override = opts
    s._test_soc = None if blind else soc
    s._test_hass = c.hass
    return c, s


def tick(clock, s, t, period, season="shoulder", seed=None, into=None):
    clock.t = t
    now = t.astimezone(_CDT)
    if s._test_soc is not None:
        # Sighted: keep the primary SOC fresh at the tick's frozen clock.
        _st(s._test_hass, _SOC, s._test_soc, unit="%", lu=t)
    if seed is not None:
        seed_inclement(s, now, *seed)
    d = s.determine_mode(period, season, now=now, tou_transition_into=into)
    # Guard the harness itself: a sighted tick must not silently go blind
    # (stale SOC stamp) and vice versa.
    assert d["envoy_available"] is (s._test_soc is not None), d["reason"]
    return d


def set_hw(c, value):
    for eid in (RESERVE_WRITE_EID, PHALANX_RESERVE_SOC_ENTITY):
        _st(c.hass, eid, value, unit="%")


def writes(d):
    return [a["data"]["value"] for a in d["actions"]
            if a["service"] == "number.set_value"]


def services(d):
    return [a["service"] for a in d["actions"]]


def alert_opts(c, event, certainty="Likely", partial=None):
    c.hass.set_state(_NWS, "1", attributes={"Alerts": [{
        "Event": event, "Severity": "Severe", "Certainty": certainty,
        "Status": "Actual", "Onset": "2026-10-14T00:00:00-05:00",
        "Ends": "2026-10-20T00:00:00-05:00",
    }]})
    opts = {CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS}
    if partial is not None:
        opts[CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR] = partial
    return opts


# ===========================================================================
# D-A2 — `_reserve_action`: fold → clamp → stamp → stand-down → deadband
# ===========================================================================
def test_reserve_action_fold_raises_only(clock):
    c, s = shell(clock, blind=False, hw="0")
    s._tick_reserve_floor = 50
    assert s._reserve_action(30)[0] == 50
    assert s._last_reserve_level_desired == 50
    assert s._reserve_action(80)[0] == 80          # fold never lowers
    assert s._last_reserve_level_desired == 80
    s._tick_reserve_floor = None
    assert s._reserve_action(30)[0] == 30          # no floor → identity
    assert s._reserve_action(150) == (100, {
        "service": "number.set_value", "target": RESERVE_WRITE_EID,
        "data": {"value": 100},
    })                                             # clamp after fold
    s._last_reserve_level_desired = 42
    assert s._reserve_action(None) == (None, None)  # no intent, no stamp
    assert s._last_reserve_level_desired == 42


def test_reserve_action_fold_before_deadband(clock):
    """Hardware 20 == the raw level: deadband on the RAW value would
    suppress; the fold to 50 happens first, so the write fires."""
    c, s = shell(clock, blind=False, hw="20")
    s._tick_reserve_floor = 50
    folded, act = s._reserve_action(20)
    assert folded == 50
    assert act is not None and act["data"]["value"] == 50


def test_reserve_action_stamps_folded_when_deadband_suppresses(clock):
    c, s = shell(clock, blind=False, hw="50")
    s._tick_reserve_floor = 50
    folded, act = s._reserve_action(20)
    assert act is None                       # within deadband of hardware 50
    assert folded == 50
    assert s._last_reserve_level_desired == 50   # stamped regardless


def test_reserve_action_compare_to_overrides_hardware(clock):
    c, s = shell(clock, blind=False, hw="unavailable")
    s._tick_reserve_floor = None
    assert s._reserve_action(60, compare_to=60)[1] is None
    assert s._reserve_action(60, compare_to=None)[1] is not None


def test_reserve_action_is_sole_desired_stamper(clock):
    """`_result` with a floor registered stamps the FOLDED value (60), not
    its raw argument (20); with reserve_level None it leaves the stamp."""
    c, s = shell(clock, blind=False, hw="0")
    s._tick_reserve_floor = 60
    d = s._result(BATTERY_MODE_SELF_CONSUMPTION, "t", "self_consumption",
                  reserve_level=20)
    assert writes(d) == [60]
    assert s._last_reserve_level_desired == 60
    s._last_reserve_level_desired = 33
    s._result(BATTERY_MODE_SELF_CONSUMPTION, "t", "self_consumption")
    assert s._last_reserve_level_desired == 33


def test_tick_floor_entry_reset(clock):
    """A prior tick's floor never survives into a tick whose early return
    skips registration (grid disconnect) or whose decision does not hold."""
    c, s = shell(clock, blind=False, hw="0")
    s._tick_reserve_floor = 77
    _st(c.hass, "switch.enpower_482348004678_grid_enabled", "off")
    from ec_phalanx_entities import PHALANX_GRID_ENABLED_ENTITY
    _st(c.hass, PHALANX_GRID_ENABLED_ENTITY, "off")
    d = tick(clock, s, OCT_16, "off_peak")
    assert "Grid disconnected" in d["reason"]
    assert s._tick_reserve_floor is None
    _st(c.hass, PHALANX_GRID_ENABLED_ENTITY, "on")
    s._tick_reserve_floor = 77
    tick(clock, s, OCT_03, "off_peak")       # allow_discharge
    assert s._tick_reserve_floor is None


def test_tick_floor_registered_for_partial_and_full(clock):
    c, s = shell(clock, blind=False, hw="0")
    tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 60))
    assert s._tick_reserve_floor == 60
    tick(clock, s, OCT_04, "off_peak", seed=("full_hold", 45))
    assert s._tick_reserve_floor == 45


@pytest.mark.asyncio
async def test_overlay_append_cannot_undercut_floor(clock):
    """§3 overlay repro: floor 50, hardware already 50 (deadband suppresses),
    EVSE hold 45, branch emitting 20 → overlay appends 50 (a pre-fold stamp
    would have given max(45, 20) = 45)."""
    c, s = shell(clock, blind=False, hw="50")
    s._tick_reserve_floor = 50
    d = s._result(BATTERY_MODE_SELF_CONSUMPTION, "Peak — x", "self_consumption",
                  reserve_level=20, season="summer")
    assert writes(d) == []
    c._evse_hold_soc = 45
    c._evse_battery_hold_active = True
    d = c._apply_evse_battery_hold(d)
    assert writes(d) == [50]


def test_offpeak_clamp_rekey_identical_for_partial_hold(clock):
    """Under a real (fusion-made) partial hold, the registered floor equals
    effective_reserve = max(reserve_soc, partial_floor), so the re-keyed
    clamps are byte-identical: the DP stamp and the hold write are both 50."""
    c, s = shell(clock, blind=False, hw="0", reserve_soc=10, soc="30")
    s._inclement_config_override = alert_opts(
        c, "Winter Storm Watch", certainty="Possible", partial=50)
    d = tick(clock, s, OCT_03, "off_peak")
    dec = s._last_inclement_decision
    assert dec.hold_depth == "partial_hold"
    assert s._tick_reserve_floor == max(s.reserve_soc, dec.reserve_floor) == 50
    assert s._offpeak_drain_branch_target == 50
    assert writes(d) == [50]


def test_registered_floor_reaches_offpeak_dp_stamp_and_hold(clock, monkeypatch):
    """The off-peak clamps key on the REGISTERED floor, not on
    `hold_depth == "partial_hold"` (Rev 3.1 H4; D-B6 relies on it). A floor
    registered under allow_discharge (via the registration seam) reaches the
    DP drain stamp and the hold write."""
    c, s = shell(clock, blind=False, hw="0", soc="30")
    monkeypatch.setattr(type(s), "_registered_floor",
                        staticmethod(lambda decision: 70))
    d = tick(clock, s, OCT_03, "off_peak")
    assert s._last_inclement_decision.hold_depth == "allow_discharge"
    assert s._offpeak_drain_branch_target == 70
    assert writes(d) == [70]


# ===========================================================================
# §12 config extremes (sighted)
# ===========================================================================
def test_extreme_reserve_soc_above_partial_floor(clock):
    """§12-1: reserve_soc 80 > partial 50 → floor 80; the fold never lowers."""
    c, s = shell(clock, blind=False, hw="0", reserve_soc=80, soc="30")
    s._inclement_config_override = alert_opts(
        c, "Winter Storm Watch", certainty="Possible", partial=50)
    d = tick(clock, s, OCT_03, "off_peak")
    assert s._tick_reserve_floor == 80
    assert writes(d) == [80]


def test_extreme_partial_floor_100_pins(clock):
    """§12-2: partial_floor 100 → partial hold pins 100."""
    c, s = shell(clock, blind=False, hw="0", soc="30")
    s._inclement_config_override = alert_opts(
        c, "Winter Storm Watch", certainty="Possible", partial=100)
    d = tick(clock, s, OCT_03, "off_peak")
    assert s._tick_reserve_floor == 100
    assert writes(d) == [100]
    assert s._last_reserve_level_desired == 100


def test_sighted_full_hold_floor_below_reserve_soc_unchanged(clock):
    """§12-4: sighted full hold with SOC 15 < reserve_soc 20 writes 15 (the
    fold must not raise a sighted full hold to reserve_soc)."""
    c, s = shell(clock, blind=False, hw="0", reserve_soc=20, soc="15")
    s._inclement_config_override = alert_opts(c, "Winter Storm Warning")
    d = tick(clock, s, OCT_16, "off_peak")
    assert s._last_inclement_decision.hold_depth == "full_hold"
    assert s._tick_reserve_floor == 15
    assert writes(d) == [15]


def test_extreme_floor_above_peak_buffer_target(clock):
    """§12-5: peak_buffer_target 40 < floor 80 → every reserve write 80."""
    c, s = shell(clock, blind=False, hw="0", soc="30", peak_buffer_target=40)
    s._arbitrage_enabled = True
    s._inclement_config_override = alert_opts(
        c, "Winter Storm Watch", certainty="Possible", partial=80)
    d = tick(clock, s, OCT_03, "off_peak")
    assert s._tick_reserve_floor == 80
    assert writes(d) and min(writes(d)) == 80
    assert s._last_reserve_level_desired == 80


# ===========================================================================
# D-A3 — blind decisions
# ===========================================================================
def test_blind_runs_inclement_decision(clock):
    """Fully blind + a real Winter Storm Warning: the decision runs on the
    blind tick, its floor is registered (blind full hold = max(reserve_soc,
    partial 50, slider default 60) = 60) and one Blind hold write follows."""
    c, s = shell(clock, blind=True, hw="0")
    s._inclement_config_override = alert_opts(c, "Winter Storm Warning")
    d = tick(clock, s, OCT_03, "off_peak")
    dec = s._last_inclement_decision
    assert dec.hold_depth == "full_hold"
    assert dec.reserve_floor == 60
    assert s._tick_reserve_floor == 60
    assert writes(d) == [60]
    assert d["reason"].startswith("Blind hold — ")
    assert d["envoy_available"] is False and d["charge_from_grid"] is False


def test_blind_full_hold_floor_inversion(clock):
    """§12-3: reserve_soc 20, partial 80, slider 60 → 80."""
    c, s = shell(clock, blind=True, hw="0", reserve_soc=20)
    s._inclement_config_override = alert_opts(c, "Winter Storm Warning", partial=80)
    d = tick(clock, s, OCT_03, "off_peak")
    assert s._tick_reserve_floor == 80
    assert writes(d) == [80]


def test_blind_hold_writes_floor_once(clock):
    """03:00 off-peak partial hold floor 50, blind: one write of 50, then
    none once hardware holds 50. No select, no CFG turn_on."""
    c, s = shell(clock, blind=True, hw="20", reserve_soc=20)
    d1 = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert writes(d1) == [50]
    assert d1["reason"].startswith("Blind hold — ")
    set_hw(c, "50")
    d2 = tick(clock, s, OCT_04, "off_peak", seed=("partial_hold", 50))
    assert writes(d2) == []
    for d in (d1, d2):
        assert not any(sv in services(d) for sv in _CFG_SURFACES)


def test_blind_hold_unreadable_reserve_writes_once(clock):
    """Restart into blind: desired and write-leg both None → one write of F,
    then none (deadband against the stamp, not the unreadable hardware)."""
    c, s = shell(clock, blind=True, hw="unavailable")
    assert s._last_reserve_level_desired is None
    d1 = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert writes(d1) == [50]
    d2 = tick(clock, s, OCT_04, "off_peak", seed=("partial_hold", 50))
    assert writes(d2) == []
    d3 = tick(clock, s, OCT_05, "off_peak", seed=("partial_hold", 50))
    assert writes(d3) == []


def test_blind_hold_never_lowers_held_value(clock):
    """§12-7: blind entered with an arbitrage desire of 80, floor 60 → no
    write and the stamp stays 80; hazard end → no release (never raised)."""
    c, s = shell(clock, blind=True, hw="80")
    s._last_reserve_level_desired = 80
    d1 = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 60))
    assert writes(d1) == []
    assert s._last_reserve_level_desired == 80
    d2 = tick(clock, s, OCT_04, "off_peak")   # allow_discharge
    assert writes(d2) == []
    assert s._last_reserve_level_desired == 80


def test_blind_no_release_without_raise(clock):
    """Blind + allow_discharge, no prior raise, pre-blind desire 80 → no
    reserve action at all."""
    c, s = shell(clock, blind=True, hw="80")
    s._last_reserve_level_desired = 80
    d = tick(clock, s, OCT_03, "off_peak")
    assert d["actions"] == []
    assert "holding (no commands issued)" in d["reason"]


def test_blind_release_at_hazard_end(clock):
    """Hold raises 20 → 50 (arms release, pre-raise 20); hazard ends → one
    release write back to 20; next tick → nothing."""
    c, s = shell(clock, blind=True, hw="20", reserve_soc=10)
    s._last_reserve_level_desired = 20
    d1 = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert writes(d1) == [50]
    assert s._blind_raised is True and s._blind_pre_raise == 20
    set_hw(c, "50")
    d2 = tick(clock, s, OCT_04, "off_peak")       # floor gone
    assert writes(d2) == [20]
    assert d2["reason"].startswith("Blind release — ")
    assert s._blind_raised is False
    set_hw(c, "20")
    d3 = tick(clock, s, OCT_05, "off_peak")
    assert d3["actions"] == []


def test_blind_release_unknown_base_targets_reserve_soc(clock):
    c, s = shell(clock, blind=True, hw="unavailable", reserve_soc=15)
    d1 = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert writes(d1) == [50]
    assert s._blind_raised is True and s._blind_pre_raise is None
    d2 = tick(clock, s, OCT_04, "off_peak")
    assert writes(d2) == [15]


def test_blind_deescalation_raise_arms_release(clock):
    """A de-escalation write folded above its base arms the release: top
    rate + CFG on + partial floor 50 + desire 20 → writes 50, arms; at the
    next non-top tick with no floor and CFG off → release to 20."""
    c, s = shell(clock, blind=True, cfg="on", hw="20", reserve_soc=20)
    s._last_reserve_level_desired = 20
    d1 = tick(clock, s, OCT_18, "mid_peak", seed=("partial_hold", 50))
    assert d1["reason"].startswith("Blind de-escalation — ")
    assert writes(d1) == [50]
    assert s._blind_raised is True and s._blind_pre_raise == 20
    for eid in ("switch.iq_battery_hacs_charge_battery_from_grid",):
        _st(c.hass, eid, "off")
    from ec_phalanx_entities import (
        PHALANX_CHARGE_FROM_GRID_ENTITY,
        PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
    )
    _st(c.hass, PHALANX_CHARGE_FROM_GRID_ENTITY, "off")
    _st(c.hass, PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY, "off")
    s._last_charge_from_grid_command = False
    set_hw(c, "50")
    d2 = tick(clock, s, OCT_03, "off_peak")
    assert writes(d2) == [20]
    assert d2["reason"].startswith("Blind release — ")


def test_blind_deescalation_at_or_below_pre_raise_clears_release(clock):
    c, s = shell(clock, blind=True, cfg="on", hw="20", reserve_soc=20)
    s._last_reserve_level_desired = 20
    tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))   # hold raise
    assert s._blind_raised is True and s._blind_pre_raise == 20
    set_hw(c, "50")
    d = tick(clock, s, OCT_18, "mid_peak")     # top, CFG on, no floor
    assert d["reason"].startswith("Blind de-escalation — ")
    assert writes(d) == [20]
    assert s._blind_raised is False


def test_blind_deescalation_shoulder_midpeak(clock):
    """INV-4: October 18:00 (shoulder mid_peak = top rate), fully blind, CFG
    on → exactly one turn_off and one reserve action (pre-Stage-A: none)."""
    c, s = shell(clock, blind=True, cfg="on", hw="0", reserve_soc=10)
    d = tick(clock, s, OCT_18, "mid_peak")
    assert services(d).count("switch.turn_off") == 1
    assert writes(d) == [10]
    assert d["reason"].startswith("Blind de-escalation — ")


def test_blind_deescalation_on_transition_into_top_rate(clock):
    """`tou_transition_into` with top rank triggers de-escalation even when
    `now`'s own period is not top (engine path)."""
    c, s = shell(clock, blind=True, cfg="on", hw="0")
    d = tick(clock, s, OCT_16, "off_peak", into="mid_peak")
    assert services(d).count("switch.turn_off") == 1
    c2, s2 = shell(clock, blind=True, cfg="on", hw="0")
    d2 = tick(clock, s2, OCT_16, "off_peak")
    assert "switch.turn_off" not in services(d2)


def test_blind_deescalation_not_at_summer_midpeak(clock):
    """Summer mid_peak is NOT the top rate (peak is): no de-escalation."""
    c, s = shell(clock, blind=True, cfg="on", hw="0")
    d = tick(clock, s, JUN_15, "mid_peak", season="summer")
    assert "switch.turn_off" not in services(d)


def test_blind_deescalation_engine_missing_uses_peak_literal(clock):
    """§12-11: no TOU engine → the legacy `peak` literal (byte-safe)."""
    c, s = shell(clock, blind=True, cfg="on", hw="0", tou=False)
    assert "switch.turn_off" not in services(tick(clock, s, OCT_18, "mid_peak"))
    c2, s2 = shell(clock, blind=True, cfg="on", hw="0", tou=False)
    assert "switch.turn_off" in services(tick(clock, s2, OCT_18, "peak"))


def test_blind_deescalation_reserve_folded(clock):
    """INV-1 repro: reserve_soc 20, partial floor 50, blind, October 18:00,
    CFG on, corroborated watch → partial_hold at top rate → de-escalation
    writes 50 (pre-Stage-A: 20)."""
    c, s = shell(clock, blind=True, cfg="on", hw="0", reserve_soc=20)
    d = tick(clock, s, OCT_18, "mid_peak", seed=("partial_hold", 50))
    assert writes(d) == [50]
    assert s._last_reserve_level_desired == 50


def test_blind_deescalation_uncorroborated_watch_is_not_a_leak(clock):
    """Uncorroborated watch at top rate → allow_discharge, no floor →
    de-escalation writes reserve_soc 20 (correct)."""
    c, s = shell(clock, blind=True, cfg="on", hw="0", reserve_soc=20)
    s._inclement_config_override = alert_opts(
        c, "Winter Storm Watch", certainty="Possible", partial=50)
    d = tick(clock, s, OCT_18, "mid_peak")
    assert s._last_inclement_decision.hold_depth == "allow_discharge"
    assert writes(d) == [20]
    # Same alert at 03:00 (off-peak): partial hold floor 50 → hold write 50.
    c2, s2 = shell(clock, blind=True, cfg="on", hw="0", reserve_soc=20)
    s2._inclement_config_override = alert_opts(
        c2, "Winter Storm Watch", certainty="Possible", partial=50)
    d2 = tick(clock, s2, OCT_03, "off_peak")
    assert writes(d2) == [50]
    assert d2["reason"].startswith("Blind hold — ")


def test_blind_full_hold_exempts_deescalation(clock):
    """A current-tick full_hold exempts de-escalation (no turn_off); the hold
    rule writes the blind floor instead."""
    c, s = shell(clock, blind=True, cfg="on", hw="0")
    d = tick(clock, s, OCT_18, "mid_peak", seed=("full_hold", 60))
    assert "switch.turn_off" not in services(d)
    assert writes(d) == [60]


def test_blind_never_stamps_desired_at(clock):
    c, s = shell(clock, blind=True, cfg="on", hw="0")
    sentinel = datetime(2020, 1, 1, tzinfo=_UTC)
    s._desired_stamped_at = sentinel
    tick(clock, s, OCT_18, "mid_peak", seed=("partial_hold", 50))  # de-esc
    tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))  # hold
    tick(clock, s, OCT_04, "off_peak")                              # release
    assert s._desired_stamped_at == sentinel


def test_blind_one_reserve_action_per_tick(clock):
    """De-escalation AND a registered floor on the same tick → exactly one
    reserve set_value (de-escalation wins, folded), plus the turn_off."""
    c, s = shell(clock, blind=True, cfg="on", hw="0", reserve_soc=20)
    d = tick(clock, s, OCT_18, "mid_peak", seed=("partial_hold", 50))
    assert writes(d) == [50]
    assert services(d) == ["switch.turn_off", "number.set_value"]


@pytest.mark.asyncio
async def test_blind_hold_with_standing_evse_hold(clock):
    """§12-6 / INV-2(b): blind floor 60, EVSE hold 45 → the overlay appends
    60 every tick (pre-existing deadband-free re-send, value >= floor,
    reason ends '+ EVSE hold'); never 45."""
    c, s = shell(clock, blind=True, hw="60")
    s._last_reserve_level_desired = 60
    c._evse_hold_soc = 45
    c._evse_battery_hold_active = True
    for t in (OCT_03, OCT_04):
        d = tick(clock, s, t, "off_peak", seed=("full_hold", 60))
        assert writes(d) == []                     # decision side: deadband
        d = c._apply_evse_battery_hold(d)
        assert writes(d) == [60]
        assert d["reason"].endswith("+ EVSE hold")


@pytest.mark.parametrize("respect", [False, True])
def test_blind_hold_manual_lower(clock, monkeypatch, respect):
    """Q6: manual lower to 30 under floor 50. False (ruled) → re-asserted to
    50 next tick; True → no reserve action and the episode flag is set."""
    c, s = shell(clock, blind=True, hw="20", reserve_soc=20)
    # Patch the switch in the globals the REAL determine_mode reads (robust
    # to other test files re-importing the module object).
    monkeypatch.setitem(
        type(s).determine_mode.__globals__, "BLIND_RESPECT_MANUAL_LOWER", respect,
    )
    d1 = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert writes(d1) == [50]
    s._last_reserve_level = 50          # what the dispatch tap records
    set_hw(c, "30")                     # operator lowers it by hand
    d2 = tick(clock, s, OCT_04, "off_peak", seed=("partial_hold", 50))
    if respect:
        assert writes(d2) == []
        assert s._blind_operator_override is True
    else:
        assert writes(d2) == [50]
        assert s._blind_operator_override is False


def test_blind_respect_manual_lower_default_false():
    """Q6 ruled A (2026-10-16): the shipped default re-asserts the floor."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const,
    )
    assert energy_const.BLIND_RESPECT_MANUAL_LOWER is False


def _respect_on(monkeypatch, s):
    monkeypatch.setitem(
        type(s).determine_mode.__globals__, "BLIND_RESPECT_MANUAL_LOWER", True,
    )


def test_blind_manual_raise_not_treated_as_lower(clock, monkeypatch):
    """BLIND_RESPECT_MANUAL_LOWER=True: hardware ABOVE the stamp is not a
    manual lower → no override; the hold still writes its target."""
    c, s = shell(clock, blind=True, hw="70")
    _respect_on(monkeypatch, s)
    s._last_reserve_level_desired = 50
    s._last_reserve_level = 50
    d = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert s._blind_operator_override is False
    assert writes(d) == [50]


def test_blind_ura_dispatched_lower_not_treated_as_manual(clock, monkeypatch):
    """BLIND_RESPECT_MANUAL_LOWER=True: hardware below the stamp but EQUAL to
    what URA last dispatched (C1) is URA's own value → no override."""
    c, s = shell(clock, blind=True, hw="30")
    _respect_on(monkeypatch, s)
    s._last_reserve_level_desired = 50
    s._last_reserve_level = 30
    d = tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert s._blind_operator_override is False
    assert writes(d) == [50]


def test_blind_episode_flags_reset_on_sighted_tick(clock):
    c, s = shell(clock, blind=True, hw="20")
    s._last_reserve_level_desired = 20
    tick(clock, s, OCT_03, "off_peak", seed=("partial_hold", 50))
    assert s._blind_raised is True
    s._test_soc = "45"                  # Envoy back: sighted tick
    d = tick(clock, s, OCT_04, "off_peak")
    assert "Envoy unavailable" not in d["reason"]
    assert s._blind_raised is False and s._blind_pre_raise is None


# ===========================================================================
# D-A4 — `reserve_write` row carries `tick_floor`
# ===========================================================================
@pytest.mark.asyncio
async def test_reserve_row_carries_tick_floor(clock):
    import json
    c, s = shell(clock, blind=False, hw="0", soc="45")
    d = tick(clock, s, JUN_15, "mid_peak", season="summer",
             seed=("partial_hold", 60))
    await c._execute_breaker_safe_dispatch(d, "mid_peak")
    await _settle()
    rows = [json.loads(r["details_json"]) for r in c.db.rows
            if r["action"] == "reserve_write"]
    assert len(rows) == 1
    assert rows[0]["tick_floor"] == 60
    assert rows[0]["tick_hold_depth"] == "partial_hold"
    assert rows[0]["value"] == 60 >= rows[0]["tick_floor"]


@pytest.mark.asyncio
async def test_reserve_row_tick_floor_null_without_hold(clock):
    import json
    c, s = shell(clock, blind=False, hw="0", soc="45")
    d = tick(clock, s, JUN_15, "mid_peak", season="summer")
    await c._execute_breaker_safe_dispatch(d, "mid_peak")
    await _settle()
    rows = [json.loads(r["details_json"]) for r in c.db.rows
            if r["action"] == "reserve_write"]
    assert len(rows) == 1
    assert rows[0]["tick_floor"] is None
    assert rows[0]["tick_hold_depth"] == "allow_discharge"


@pytest.mark.parametrize("t,expected", [(OCT_18, True), (OCT_16, False)])
def test_get_status_carries_tou_top_rate(clock, t, expected):
    """D-A1 wire-in: the strategy sensor's attr pack (get_status) carries
    `tou_top_rate` from the engine's rate rank (October 18:00 top, 16:00
    not; a name-keyed check would read False all shoulder day)."""
    clock.t = t
    c, s = shell(clock, blind=False, hw="0")
    assert s.get_status()["tou_top_rate"] is expected
    s._tou = None
    assert s.get_status()["tou_top_rate"] is None

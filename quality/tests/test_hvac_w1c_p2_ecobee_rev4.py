"""HVAC W1-C P2 option C — ecobee comfort SELECT by default (Branch S), range
hold only for composed numbers (Branch R). Behavioural suite.

Plan: docs/planning/PLANNING_hvac_w1c_p2_ecobee.md REV 4 + REV 4.1 + "Operator
rulings 2026-10-05" (select via a governed funnel; fifth funnel
`emit_select_comfort`; Branch D parked; vacation selects Away only when its
numbers equal Away's; ECOBEE_SELECT_ECHO_TTL_S = 180 s).

Every test drives REAL production code on the shared W1-B harness (real
HVACCoordinator / OverrideArrester / PresetManager / strategy on the smoke
StubHass) with a REAL registry lookup: zone 1 is `homekit_controller` +
"ecobee Inc." WITH a Current Mode select (translation_key `ecobee_mode`);
zones 2/3 are Carrier. Oracles are hand-derived literals: summer Seasonal
Baseline Home 77/70, Sleep 76/70, Away 82/60, Vacation 85/58; the device's
own Home comfort is played as 71/75 (deliberately NOT the baseline, so a
reference taken from the baseline, the live legs or `settled` are three
different numbers). TTL boundaries are literal seconds (179 / 180 / 181),
never the imported constant.

Falsifiable invariants (REV 4.1-D):
  INV-E2' an ecobee is sent only climate.set_hvac_mode, climate.set_temperature
          (both legs, heat_cool) and select.select_option on its Current Mode
          select through emit_select_comfort.
  INV-R'  clauses 1-7 (named tests below).
  INV-C   Carrier is byte-identical (test_hvac_w1c_p1_byte_identity.py).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402

ZONE = "zone_1"
ENT = "climate.test_zone_1"          # ecobee over HomeKit
SEL = "select.test_zone_1_current_mode"
DEV = "dev_ecobee_1"
CAR = "climate.test_zone_2"          # Carrier
CAR_ZONE = "zone_2"
T0 = 1_800_000_000.0                 # wall epoch the tests start at


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    return H.load_real()


@pytest.fixture
def expected_lingering_timers():
    return True


class _Reg:
    def __init__(self, entries):
        self.entries = entries

    def async_get(self, entity_id):
        return self.entries.get(entity_id)


class _DevReg:
    def __init__(self, devices):
        self.devices = devices

    def async_get(self, dev_id):
        return self.devices.get(dev_id)


def _entry(eid, platform, device_id=None, translation_key=None):
    return types.SimpleNamespace(
        entity_id=eid, platform=platform, device_id=device_id,
        domain=eid.split(".")[0], translation_key=translation_key,
    )


def _install_registry(monkeypatch, mods, *, with_select=True):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    entries = {
        ENT: _entry(ENT, "homekit_controller", DEV),
        CAR: _entry(CAR, "ha_carrier"),
        "climate.test_zone_3": _entry("climate.test_zone_3", "ha_carrier"),
    }
    if with_select:
        entries[SEL] = _entry(SEL, "homekit_controller", DEV, "ecobee_mode")
    reg = _Reg(entries)
    dreg = _DevReg({DEV: types.SimpleNamespace(manufacturer="ecobee Inc.")})
    monkeypatch.setattr(er, "async_get", lambda _h: reg)
    monkeypatch.setattr(
        er, "async_entries_for_device",
        lambda r, dev, include_disabled_entities=False: [
            e for e in r.entries.values() if e.device_id == dev
        ],
    )
    monkeypatch.setattr(dr, "async_get", lambda _h: dreg)
    mods["hvac_strategy"]._test_reset_cache()


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _clock(monkeypatch, mods, t=T0):
    c = _Clock(t)
    monkeypatch.setattr(mods["hvac_strategy"], "_wall_now", c)
    return c


def _set_eco(hass, *, mode="heat_cool", low=None, high=None, temperature=None, sel=None):
    attrs = {
        "hvac_modes": ["off", "heat", "cool", "heat_cool"],
        "target_temp_low": low if mode == "heat_cool" else None,
        "target_temp_high": high if mode == "heat_cool" else None,
        "current_temperature": 74.0,
    }
    if mode != "heat_cool":
        attrs["temperature"] = temperature
    hass.states.async_set(ENT, mode, attrs)
    if sel is not None:
        hass.states.async_set(SEL, sel, {"options": ["home", "sleep", "away"]})
    return hass.states.get(ENT)


def _rig(mods, monkeypatch, *, season="summer", house="home_day", low=68.0, high=72.0,
         with_select=True):
    coord, hass = H.make_coord(mods)
    _install_registry(monkeypatch, mods, with_select=with_select)
    mods["hvac_setpoint"]._test_clear_ura_setpoints()
    coord._house_state = house
    coord._zone_intelligence_enabled = False
    coord._preset_manager._current_season = season
    for other in ("zone_2", "zone_3"):
        coord.zone_manager.zones[other].preset_mode = "home"
    _set_eco(hass, low=low, high=high, sel="unknown")
    coord.zone_manager.zones[ZONE].hvac_mode = "heat_cool"
    coord._override_arrester.enabled = True
    return coord, hass


def _S(mods):
    return mods["hvac_strategy"]


def _eco(mods, hass):
    return _S(mods).strategy_for(hass, ENT)


async def _tick(coord, hass):
    coord.zone_manager.update_zone_climate_state(ZONE)
    await coord._apply_house_state_presets()
    await H.drain(hass)


def _selects(hass):
    return [c[2] for c in hass.services.calls if c[0] == "select" and c[1] == "select_option"]


def _temps(hass, ent=ENT):
    return [c[2] for c in hass.services.calls
            if c[0] == "climate" and c[1] == "set_temperature" and c[2].get("entity_id") == ent]


def _db_rows(hass, mods):
    return [r for r in hass.data[mods["const"].DOMAIN]["database"].rows
            if r.get("action") == "climate_write"]


def _assert_inv_e2_prime(hass):
    """INV-E2' over every call this test made to the ecobee (climate or its
    select): no preset write, no single `temperature`, no button / number,
    a select only on the Current Mode select with a comfort option."""
    for d, svc, data in hass.services.calls:
        eid = data.get("entity_id")
        if eid not in (ENT, SEL):
            continue
        assert d in ("climate", "select"), (d, svc)
        if d == "select":
            assert (svc, eid) == ("select_option", SEL)
            assert data["option"] in ("home", "sleep", "away")
            continue
        assert svc in ("set_hvac_mode", "set_temperature"), svc
        if svc == "set_temperature":
            assert set(data) == {"entity_id", "target_temp_low", "target_temp_high"}


def _hsel(mods, label, t, settled=None):
    S = _S(mods)
    return S.Held(label, S.HELD_SELECT, None, None, t, settled)


def _hrng(mods, label, lo, hi, t=T0):
    S = _S(mods)
    return S.Held(label, S.HELD_RANGE, float(lo), float(hi), t, None)


# ==========================================================================
# M1 / M2 / M18 — Branch S default through the real S1 site
# ==========================================================================


@pytest.mark.asyncio
async def test_m1_s1_home_selects_the_comfort_once_through_the_funnel(mods, monkeypatch):
    """M1: S1 `home` on an ecobee with no composition -> ONE
    select.select_option {SEL, home}; zero range / preset writes; held =
    Held(home, select, None, None, T0, None) stamped BEFORE the wire; this
    zone's select record = ("select_option", "home")."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)
    sp = mods["hvac_setpoint"]
    real = sp.emit_select_comfort
    seen = []

    async def _spy(h, e, opt, **kw):
        seen.append(eco._held.get(e))
        return await real(h, e, opt, **kw)
    monkeypatch.setattr(sp, "emit_select_comfort", _spy)
    await _tick(coord, hass)
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]
    assert _temps(hass) == []
    assert [c for c in hass.services.calls if c[1] == "set_preset_mode" and c[2].get("entity_id") == ENT] == []
    assert seen == [_hsel(mods, "home", T0)]
    assert eco._held[ENT] == _hsel(mods, "home", T0)
    assert eco._last_sent_select == {(ZONE, ENT): ("select_option", "home")}
    _assert_inv_e2_prime(hass)


@pytest.mark.asyncio
async def test_m2_next_tick_with_the_select_unknown_writes_nothing(mods, monkeypatch):
    """M2 / INV-R' 2: after the select the device holds its own comfort and
    the select reads `unknown`; the next S1 ticks (inside AND after the
    window) write nothing."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _tick(coord, hass)
    _set_eco(hass, low=71.0, high=75.0, sel="unknown")
    clk.t = T0 + 60
    await _tick(coord, hass)
    clk.t = T0 + 400
    await _tick(coord, hass)
    assert len(_selects(hass)) == 1
    assert _temps(hass) == []
    assert coord.zone_manager.zones[ZONE].preset_mode == "home"


@pytest.mark.asyncio
async def test_m18_select_ledger_row_shape(mods, monkeypatch):
    """M18 + C.14: ONE climate_write row, verb select.select_option, entity_id
    = the CLIMATE entity, select_entity_id = the select, values_before /
    values_after as specified, issue <= return stamps."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _tick(coord, hass)
    rows = _db_rows(hass, mods)
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_id"] == ENT
    d = json.loads(r["details_json"])
    assert d["verb"] == "select.select_option"
    assert d["site"] == "S1_reason_ladder"
    assert d["select_entity_id"] == SEL
    assert d["values_before"] == {
        "select": "unknown",
        "climate": {"hvac_mode": "heat_cool", "setpoints": {
            "target_low": 68.0, "target_high": 72.0, "temperature": None}},
    }
    assert d["values_after"] == {"service_data": {"entity_id": SEL, "option": "home"}}
    assert d["wire_ok"] is True and d["exc"] is None
    assert d["ts_issued"] <= d["ts_returned"]


@pytest.mark.asyncio
async def test_m13_select_entity_id_only_on_select_rows(mods, monkeypatch):
    """M13: the select row carries select_entity_id; a Carrier preset row and
    an ecobee range row do not have the key (NULL to json_extract)."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    await _tick(coord, hass)
    H.set_climate(hass, CAR, preset_mode="manual", hold_activity="manual")
    await S.strategy_for(hass, CAR).hold_preset(hass, CAR, "sleep", site="S1", zone_id=CAR_ZONE, reason="t")
    eco = _eco(mods, hass)
    eco._ranges[(ENT, "home", "summer")] = (69.0, 78.0)
    await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE, site="S10_preset_range", reason="r")
    await H.drain(hass)
    by_verb = {}
    for r in _db_rows(hass, mods):
        d = json.loads(r["details_json"])
        by_verb.setdefault(d["verb"], []).append(d)
    assert [d["select_entity_id"] for d in by_verb["select.select_option"]] == [SEL]
    assert by_verb["set_preset_mode"] and all("select_entity_id" not in d for d in by_verb["set_preset_mode"])
    assert by_verb["set_temperature"] and all("select_entity_id" not in d for d in by_verb["set_temperature"])


# ==========================================================================
# emit_select_comfort — the funnel (gate, raise path, no freeze param)
# ==========================================================================


@pytest.mark.asyncio
async def test_funnel_comfort_delay_gate_defers_with_zero_calls_and_one_deferred_row(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    sp = mods["hvac_setpoint"]
    n = len(hass.services.calls)
    wrote = await sp.emit_select_comfort(
        hass, ENT, "home", select_entity_id=SEL, site="S1_reason_ladder",
        zone_id=ZONE, reason="r", blocking=False, gate=lambda: True)
    await H.drain(hass)
    assert wrote is False
    assert len(hass.services.calls) == n
    assert _db_rows(hass, mods) == []
    rows = hass.data[mods["const"].DOMAIN]["activity_logger"].actions("comfort_delay_deferred_write")
    assert len(rows) == 1 and rows[0]["details"]["would_have_emitted"] == {
        "option": "home", "select_entity_id": SEL}


@pytest.mark.asyncio
async def test_funnel_wire_exception_reraises_after_one_failed_row(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    sp = mods["hvac_setpoint"]

    async def _boom(*a, **k):
        raise RuntimeError("wire")
    monkeypatch.setattr(hass.services, "async_call", _boom)
    with pytest.raises(RuntimeError):
        await sp.emit_select_comfort(
            hass, ENT, "sleep", select_entity_id=SEL, site="S4", zone_id=ZONE,
            reason="r", blocking=True)
    await H.drain(hass)
    rows = _db_rows(hass, mods)
    assert len(rows) == 1
    d = json.loads(rows[0]["details_json"])
    assert (d["wire_ok"], d["exc"], d["select_entity_id"]) == (False, "RuntimeError", SEL)


@pytest.mark.asyncio
async def test_hold_preset_gate_deferred_restores_held_and_records_nothing(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)
    prev = _hrng(mods, "sleep", 70, 76)
    eco._held[ENT] = prev
    res = await eco.hold_preset(hass, ENT, "home", gate=lambda: True, site="S1",
                                zone_id=ZONE, reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.DEFERRED, "gate_deferred")
    assert _selects(hass) == []
    assert eco._held[ENT] is prev
    assert eco._last_sent_select == {}


@pytest.mark.asyncio
async def test_hold_preset_wire_exception_is_failed_and_restores_held(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)

    async def _boom(*a, **k):
        raise RuntimeError("wire")
    monkeypatch.setattr(hass.services, "async_call", _boom)
    res = await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    assert (res.status, res.reason, res.exc) == (S.WriteStatus.FAILED, "emit_raised", "RuntimeError")
    assert ENT not in eco._held
    assert eco._last_sent_select == {}


# ==========================================================================
# M6 / M15 / M9 — the branch ladder (mapping, vacation, freeze)
# ==========================================================================


@pytest.mark.parametrize("preset,option", [("home", "home"), ("wake", "home"),
                                           ("sleep", "sleep"), ("away", "away")])
@pytest.mark.asyncio
async def test_m6_mapping_selects_the_comfort_option(mods, monkeypatch, preset, option):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    res = await eco.hold_preset(hass, ENT, preset, site="S1", zone_id=ZONE, reason="r")
    assert res.status is _S(mods).WriteStatus.APPLIED
    assert _selects(hass) == [{"entity_id": SEL, "option": option}]
    assert _temps(hass) == []
    assert eco._held[ENT].label == preset


@pytest.mark.asyncio
async def test_m15_vacation_with_default_numbers_holds_the_vacation_range(mods, monkeypatch):
    """Ruling 5 / M15: summer Vacation 85/58 differs from Away 82/60 -> Branch
    R: one range write 58/85, zero select writes (never `vacation`, never a
    bare `away` select)."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    eco = _eco(mods, hass)
    res = await eco.hold_preset(hass, ENT, "vacation", site="S1", zone_id=ZONE, reason="r")
    assert res.status is _S(mods).WriteStatus.APPLIED
    assert _selects(hass) == []
    assert _temps(hass) == [{"entity_id": ENT, "target_temp_low": 58.0, "target_temp_high": 85.0}]
    h = eco._held[ENT]
    assert (h.label, h.mode, h.lo, h.hi) == ("vacation", "range", 58.0, 85.0)


@pytest.mark.asyncio
async def test_m15_vacation_equal_to_away_selects_away(mods, monkeypatch):
    """Ruling 5: Vacation numbers equal to Away's -> Branch S `away`; the
    zone still reads `vacation` (held label)."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    hc = sys.modules[type(coord._preset_manager).__module__]
    monkeypatch.setitem(hc.SEASONAL_DEFAULTS["summer"], "vacation", (82, 60))
    eco = _eco(mods, hass)
    await eco.hold_preset(hass, ENT, "vacation", site="S1", zone_id=ZONE, reason="r")
    assert _selects(hass) == [{"entity_id": SEL, "option": "away"}]
    assert _temps(hass) == []
    assert eco.preset_of(hass.states.get(ENT), None, hass=hass, entity_id=ENT) == "vacation"


@pytest.mark.asyncio
async def test_m15_vacation_equal_to_a_composed_away_still_holds_a_range(mods, monkeypatch):
    """Selecting `away` hands the device's OWN away comfort, not URA's
    composed away numbers: a composed away forces vacation to Branch R."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    hc = sys.modules[type(coord._preset_manager).__module__]
    monkeypatch.setitem(hc.SEASONAL_DEFAULTS["summer"], "vacation", (80, 62))
    eco = _eco(mods, hass)
    eco._ranges[(ENT, "away", "summer")] = (62.0, 80.0)
    await eco.hold_preset(hass, ENT, "vacation", site="S1", zone_id=ZONE, reason="r")
    assert _selects(hass) == []
    assert _temps(hass) == [{"entity_id": ENT, "target_temp_low": 62.0, "target_temp_high": 80.0}]


@pytest.mark.asyncio
async def test_unmapped_preset_holds_a_range(mods, monkeypatch):
    """C.8: a preset the select cannot name is held as a range (never
    coerced to away). `boost` has no baseline -> FAILED, zero calls."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    res = await _eco(mods, hass).hold_preset(hass, ENT, "boost", site="S1", zone_id=ZONE, reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.FAILED, "no_range_for_preset")
    assert [c for c in hass.services.calls if c[2].get("entity_id") in (ENT, SEL)] == []


@pytest.mark.asyncio
async def test_m9_freeze_forces_a_range_hold(mods, monkeypatch):
    """M9 / INV-R' 6: freeze active at hold_preset -> one range write, zero
    selects (a select hands the device numbers URA cannot floor)."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    monkeypatch.setattr(S._CTX, "freeze_active", lambda: True)
    res = await _eco(mods, hass).hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    assert res.status is S.WriteStatus.APPLIED
    assert _selects(hass) == []
    assert _temps(hass) == [{"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 77.0}]
    assert _eco(mods, hass)._held[ENT].mode == "range"


@pytest.mark.asyncio
async def test_no_current_mode_select_keeps_the_option_b_range_hold(mods, monkeypatch):
    """Builder fallback (reported): a unit with no Current Mode select is
    held by its effective range exactly as option B."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, with_select=False)
    await _tick(coord, hass)
    assert _selects(hass) == []
    assert _temps(hass) == [{"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 77.0}]


# ==========================================================================
# M7 / M16 — lazy settle and window absorption
# ==========================================================================


@pytest.mark.parametrize("dt,settled", [(179, None), (180, (71.0, 75.0)), (181, (71.0, 75.0))])
def test_m7_lazy_settle_fills_at_and_after_180_s_only(mods, monkeypatch, dt, settled):
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    st = _set_eco(hass, low=71.0, high=75.0)
    clk.t = T0 + dt
    assert eco.preset_of(st, None, hass=hass, entity_id=ENT) == "home"
    assert eco._held[ENT].settled == settled


def test_m7_settled_is_reused_by_later_reads(mods, monkeypatch):
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 181
    eco.preset_of(_set_eco(hass, low=71.0, high=75.0), None, hass=hass, entity_id=ENT)
    clk.t = T0 + 500
    assert eco.preset_of(_set_eco(hass, low=71.0, high=75.0), None, hass=hass, entity_id=ENT) == "home"
    assert eco._held[ENT].settled == (71.0, 75.0)


def test_a_m1_unsettled_select_off_heat_cool_never_settles_on_the_single_target(mods, monkeypatch):
    """A-M1 repro 1 (replaces the C.6 "single target twice" settle): the
    first read after the window is in `cool` 75 -> the label, NOTHING
    settled; the unit back in heat_cool at its comfort 71/75 then settles
    there and reads home. (Settling (75, 75) would read the comfort as a
    phantom `manual`.)"""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 181
    st = _set_eco(hass, mode="cool", temperature=75.0)
    assert eco.preset_of(st, None, hass=hass, entity_id=ENT) == "home"
    assert eco._held[ENT].settled is None
    clk.t = T0 + 200
    assert eco.preset_of(_set_eco(hass, low=71.0, high=75.0), None, hass=hass, entity_id=ENT) == "home"
    assert eco._held[ENT].settled == (71.0, 75.0)


def test_a_m1_settled_select_off_heat_cool_reads_the_label(mods, monkeypatch):
    """A-M1 repro 2: a SETTLED select (71/75) while B1 has not yet put the
    unit back in heat_cool (`cool` 73) reads the held label — mode drift is
    B1's, exactly like the range branch — never `manual`."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    clk.t = T0 + 600
    for mode in ("cool", "heat", "off"):
        st = _set_eco(hass, mode=mode, temperature=73.0)
        assert eco.preset_of(st, None, hass=hass, entity_id=ENT) == "home", mode
    assert eco._held[ENT].settled == (71.0, 75.0)


def test_c_low_unreadable_legs_under_a_settled_select_read_the_label(mods, monkeypatch):
    """C-LOW: heat_cool with a missing leg under a settled select -> the
    held label (no comparison possible), and `settled` is untouched."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    clk.t = T0 + 600
    for low, high in ((None, 75.0), (71.0, None), (None, None)):
        st = _set_eco(hass, low=low, high=high)
        assert eco.preset_of(st, None, hass=hass, entity_id=ENT) == "home", (low, high)
    assert eco._held[ENT].settled == (71.0, 75.0)


def test_inside_the_window_unknown_select_and_any_legs_read_the_label(mods, monkeypatch):
    """C.3 'unknown stays home': inside the window the label is returned
    whatever the legs or the select read."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 179
    st = _set_eco(hass, low=60.0, high=90.0, sel="unknown")
    assert eco.preset_of(st, None, hass=hass, entity_id=ENT) == "home"


def test_m16_first_read_after_the_window_settles_late(mods, monkeypatch):
    """C.6b row 1: select at T0, first read at T0+65 s past the window
    (T0+245) settles there; later equal legs read home."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 245
    eco.preset_of(_set_eco(hass, low=71.0, high=75.0), None, hass=hass, entity_id=ENT)
    assert eco._held[ENT].settled == (71.0, 75.0)


@pytest.mark.asyncio
async def test_m16_a_newer_select_drops_the_earlier_settle_candidate(mods, monkeypatch):
    """C.6b row 2: home at T0, sleep at T0+10 -> held is sleep with a fresh
    window from T0+10. A read at T0+185 (past HOME's window, inside SLEEP's)
    must not settle; the read at T0+191 settles it for SLEEP."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    clk.t = T0 + 10
    await eco.hold_preset(hass, ENT, "sleep", site="S1", zone_id=ZONE, reason="r")
    clk.t = T0 + 185                      # 175 s after the sleep select: inside
    eco.preset_of(_set_eco(hass, low=70.0, high=76.0), None, hass=hass, entity_id=ENT)
    assert eco._held[ENT].settled is None
    clk.t = T0 + 191                      # 181 s after the sleep select
    assert eco.preset_of(_set_eco(hass, low=70.0, high=76.0), None, hass=hass, entity_id=ENT) == "sleep"
    assert (eco._held[ENT].label, eco._held[ENT].settled) == ("sleep", (70.0, 76.0))


# ==========================================================================
# M3 / M14 / C.5 — the arrester reference under Branch S
# ==========================================================================


def _eco_ev(old, new):
    o = types.SimpleNamespace(entity_id=ENT, state=old[0], attributes={
        "target_temp_low": old[1], "target_temp_high": old[2],
        "hvac_modes": ["off", "heat", "cool", "heat_cool"]})
    o.last_updated = datetime.now(timezone.utc) - timedelta(seconds=1)
    n = types.SimpleNamespace(entity_id=ENT, state=new[0], attributes={
        "target_temp_low": new[1], "target_temp_high": new[2],
        "hvac_modes": ["off", "heat", "cool", "heat_cool"]})
    n.last_updated = datetime.now(timezone.utc)
    return types.SimpleNamespace(
        data={"entity_id": ENT, "new_state": n, "old_state": o},
        context=types.SimpleNamespace(user_id=None, parent_id=None, id="ctx"))


@pytest.mark.asyncio
async def test_m3_settled_drift_reads_manual_and_is_booked_against_settled(mods, monkeypatch):
    """M3: Branch-S home settled at the device's 71/75; a wall change of the
    cool leg to 73 after the window reads `manual` (a held-label read would
    book nothing) and the arrester books ONE override. A plain transition
    measures against the old legs (Carrier semantics) = settled: -2."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _tick(coord, hass)                                # select home at T0
    clk.t = T0 + 181
    _set_eco(hass, low=71.0, high=75.0)
    coord.zone_manager.update_zone_climate_state(ZONE)      # R1 read settles
    eco = _eco(mods, hass)
    assert eco._held[ENT].settled == (71.0, 75.0)
    assert eco.preset_of(_set_eco(hass, low=71.0, high=73.0), None, hass=hass, entity_id=ENT) == "manual"
    coord._override_arrester._handle_climate_change(
        _eco_ev(("heat_cool", 71.0, 75.0), ("heat_cool", 71.0, 73.0)))
    await H.drain(hass, rounds=6)
    rows = [r for r in hass.data[mods["const"].DOMAIN]["activity_logger"].actions("override_detected")
            if r.get("entity_id") == ENT]
    assert len(rows) == 1
    assert rows[0]["details"]["delta_f"] == -2.0


@pytest.mark.parametrize("held_kind,expect", [
    ("range", (78.0, 69.0)),          # (held.hi, held.lo)
    ("settled", (75.0, 71.0)),        # settled (heat, cool) -> (cool, heat)
    ("unsettled", (77.0, 70.0)),      # Seasonal Baseline of the label (summer home)
    ("none", (99.0, 11.0)),           # the caller's baseline, untouched
])
def test_m14_reference_setpoints_rows(mods, monkeypatch, held_kind, expect):
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    if held_kind == "range":
        eco._held[ENT] = _hrng(mods, "home", 69, 78)
    elif held_kind == "settled":
        eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    elif held_kind == "unsettled":
        eco._held[ENT] = _hsel(mods, "home", T0)
        _set_eco(hass, low=72.0, high=73.0)          # mid-settle live legs
        clk.t = T0 + 30
    assert eco.reference_setpoints(hass, ENT, "home", (99.0, 11.0)) == expect


def test_m14_unsettled_reference_drives_the_arrester_resolver(mods, monkeypatch):
    """Wire-in anchor (`_arrester_reference`): an unsettled select measures
    a change against the baseline of the selected preset, never the live
    mid-settle legs."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    _set_eco(hass, low=72.0, high=73.0)
    clk.t = T0 + 30
    res = coord._override_arrester._baseline_resolver
    assert res(ZONE, "home") == ("home", 77.0, 70.0)
    eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    assert res(ZONE, "home") == ("home", 75.0, 71.0)


@pytest.mark.asyncio
async def test_arrester_revert_pin_selects_the_comfort_not_a_raw_range(mods, monkeypatch):
    """C.5: an S4-style revert (`pin_preset`) on a Branch-S zone is ONE
    select of the comfort setting, zero range writes."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    res = await _eco(mods, hass).pin_preset(
        hass, ENT, "home", emit=object(), blocking=True, site="S4", zone_id=ZONE, reason="revert")
    assert res.status is S.WriteStatus.APPLIED
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]
    assert _temps(hass) == []
    # B-L1 / D-L1: a landed pin is this zone's select record.
    assert _eco(mods, hass)._last_sent_select == {(ZONE, ENT): ("select_option", "home")}


@pytest.mark.asyncio
async def test_b_l1_s1_tick_after_a_pin_does_not_select_again(mods, monkeypatch):
    """B-L1 wire-in: after an S4-style `pin_preset(home)` the next S1 tick
    (zone reads home) writes nothing — without the pin's record R2 would
    select the same comfort a second time."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _eco(mods, hass).pin_preset(
        hass, ENT, "home", emit=object(), blocking=True, site="S4", zone_id=ZONE, reason="revert")
    clk.t = T0 + 30
    await _tick(coord, hass)
    assert coord.zone_manager.zones[ZONE].preset_mode == "home"
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]


@pytest.mark.asyncio
async def test_pin_preset_select_wire_exception_propagates_and_restores_held(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    prev = _hrng(mods, "sleep", 70, 76)
    eco._held[ENT] = prev

    async def _boom(*a, **k):
        raise RuntimeError("wire")
    monkeypatch.setattr(hass.services, "async_call", _boom)
    with pytest.raises(RuntimeError):
        await eco.pin_preset(hass, ENT, "home", site="S7", zone_id=ZONE, reason="r")
    assert eco._held[ENT] is prev


# ==========================================================================
# M4 / M5 — set_preset_range upgrade / downgrade in ONE call (INV-R' 3/4)
# ==========================================================================


@pytest.mark.asyncio
async def test_m4_composition_on_the_held_select_upgrades_in_the_same_call(mods, monkeypatch):
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)
    await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    _set_eco(hass, low=71.0, high=75.0)
    clk.t = T0 + 300
    res = await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE,
                                     site="S10_preset_range", reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.APPLIED, "emitted")
    assert _temps(hass) == [{"entity_id": ENT, "target_temp_low": 69.0, "target_temp_high": 78.0}]
    assert eco._held[ENT] == _hrng(mods, "home", 69, 78, T0 + 300)
    assert len(_selects(hass)) == 1
    assert eco._last_sent_select == {}


@pytest.mark.asyncio
async def test_m5_baseline_on_a_held_range_downgrades_with_one_select_in_the_same_call(mods, monkeypatch):
    """M5 / INV-R' 4: CPR OFF hands back the baseline for the held preset ->
    the entry is deleted AND one select home is emitted in THIS call; the
    next S1 tick writes nothing."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)
    eco._ranges[(ENT, "home", "summer")] = (69.0, 78.0)
    await _tick(coord, hass)                                  # Branch R: 69/78
    assert _temps(hass) == [{"entity_id": ENT, "target_temp_low": 69.0, "target_temp_high": 78.0}]
    _set_eco(hass, low=69.0, high=78.0)
    clk.t = T0 + 300
    res = await eco.set_preset_range(hass, ENT, "home", 70.0, 77.0, zone_id=ZONE,
                                     site="S10_preset_range_restore", reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.APPLIED, "emitted")
    assert eco._ranges == {}
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]
    assert eco._held[ENT] == _hsel(mods, "home", T0 + 300)
    _set_eco(hass, low=71.0, high=75.0)
    n = len(hass.services.calls)
    await _tick(coord, hass)
    assert len(hass.services.calls) == n


@pytest.mark.asyncio
async def test_baseline_on_a_held_select_writes_nothing(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)
    await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    n = len(hass.services.calls)
    res = await eco.set_preset_range(hass, ENT, "home", 70.0, 77.0, zone_id=ZONE, site="s", reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.SKIPPED_ALREADY_CORRECT, "comfort_already_selected")
    assert len(hass.services.calls) == n


@pytest.mark.asyncio
async def test_s10_restore_pass_on_ecobee_downgrades_to_the_comfort_select(mods, monkeypatch):
    """Enclosing-method anchor (S10 `_async_apply_preset_overrides`): CPR ON
    stores 69/78 for the held home (one range write); switch OFF -> the
    restore pass deletes it and re-selects home in the same pass."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    coord._zone_state_store = H.FakeStore()
    cm = next(e for e in hass.config_entries.async_entries() if "zones" not in (e.options or {}))
    cm.options = {**(cm.options or {}), "hvac_s10_rollout_zone_ids": [ZONE]}
    await _tick(coord, hass)                                  # select home
    _set_eco(hass, low=71.0, high=75.0)
    coord.zone_manager.update_zone_climate_state(ZONE)
    eco = _eco(mods, hass)
    coord._zones_written_this_cycle.clear()
    coord.set_custom_ranges_enabled(True, source="user")
    monkeypatch.setattr(coord, "_s10_desired", lambda z, p, e, o: ((69.0, 78.0), "preset_range_dpm"))
    await coord._async_apply_preset_overrides()
    await H.drain(hass)
    assert _temps(hass)[-1] == {"entity_id": ENT, "target_temp_low": 69.0, "target_temp_high": 78.0}
    _set_eco(hass, low=69.0, high=78.0)
    coord.set_custom_ranges_enabled(False, source="user")
    await coord._async_apply_preset_overrides()
    await H.drain(hass)
    assert eco._ranges == {}
    assert _selects(hass)[-1] == {"entity_id": SEL, "option": "home"}
    assert len(_selects(hass)) == 2
    _assert_inv_e2_prime(hass)


def test_c15_ecobee_s10_original_is_the_baseline_so_capture_is_a_noop(mods, monkeypatch):
    """C.15: the ecobee "device original" S10 compares against is the
    Seasonal Baseline as the adapter would write it — equal to what the
    adapter would write for the baseline, so nothing new is captured."""
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    assert eco.preset_range_original(hass, ENT, "home") == (70, 77)
    assert eco.preset_range_would_write(70.0, 77.0, ENT) == (70, 77)
    assert eco._ranges == {}


# ==========================================================================
# M8 — hold_needs_reassert truth table (direct) + wire-in at S1
# ==========================================================================


@pytest.mark.asyncio
async def test_m8_r1_upgrade_and_downgrade(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is False
    eco._ranges[(ENT, "home", "summer")] = (69.0, 78.0)       # composition appears
    _set_eco(hass, low=69.0, high=78.0)                       # even with legs == composition
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True
    eco._ranges.clear()
    eco._held[ENT] = _hrng(mods, "home", 69, 78)              # composition gone
    _set_eco(hass, low=69.0, high=78.0)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True


def test_m8_r2_label_or_this_zone_record_mismatch(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "sleep", T0)
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "sleep")
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True
    eco._held[ENT] = _hsel(mods, "home", T0)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True   # record says sleep
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id="zone_9") is True  # other zone
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is False
    eco._held.pop(ENT)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True


def test_m8_r3_range_legs_drift(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, with_select=False)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hrng(mods, "home", 70, 77)
    _set_eco(hass, low=70.0, high=77.0)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is False
    coord._preset_manager._current_season = "shoulder"        # eff 70/75
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True


def test_m8_r4_settled_deviation_matching_a_recent_ura_value(mods, monkeypatch):
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
    clk.t = T0 + 600
    _set_eco(hass, low=68.0, high=74.0)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is False   # not URA-shaped
    mods["hvac_setpoint"].record_ura_setpoint(ENT, 68.0, 74.0)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True


@pytest.mark.parametrize("dt", [0, 15, 16])
def test_a_l1_r4_has_no_select_time_arm(mods, monkeypatch, dt):
    """A-L1: the old "within 15 s of URA's select" R4 arm is gone (a
    `settled` hold is always past the 180 s window, so it was dead). A
    deviation that matches no recent URA setpoint never re-asserts."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
    _set_eco(hass, low=68.0, high=74.0)
    clk.t = T0 + dt
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is False


def test_m8_carrier_and_generic_never_reassert(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    car = S.strategy_for(hass, CAR)
    assert car.hold_needs_reassert(hass, CAR, "home", zone_id=CAR_ZONE) is False
    assert S.GenericStrategy().hold_needs_reassert(hass, CAR, "home", zone_id=CAR_ZONE) is False


@pytest.mark.asyncio
async def test_m8_inv_r5_season_rollover_reselects_through_s1(mods, monkeypatch):
    """INV-R' 5 at the S1 short-circuit: a stored SUMMER composition held
    as a range; the season rolls -> the composition is pruned, Branch S
    applies, and the next tick selects home (one write) although the zone
    still reads home."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._ranges[(ENT, "home", "summer")] = (69.0, 78.0)
    await _tick(coord, hass)
    _set_eco(hass, low=69.0, high=78.0)
    await _tick(coord, hass)
    assert _selects(hass) == [] and len(_temps(hass)) == 1
    coord._preset_manager._current_season = "shoulder"
    await _tick(coord, hass)
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]
    assert len(_temps(hass)) == 1


@pytest.mark.asyncio
async def test_m8_vacancy_away_site_reselects_on_reassert(mods, monkeypatch):
    """Wire-in anchor at the vacancy-bypass `Already away` skip: a zone
    reading away from a RANGE hold (no composition any more) is re-selected
    `away` instead of skipped."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=60.0, high=82.0)
    coord._zone_intelligence_enabled = True
    monkeypatch.setattr(coord, "_zone_conditioning_retreat_ok", lambda z: True)
    z = coord.zone_manager.zones[ZONE]
    z.last_occupied_time = H.utc_now() - timedelta(hours=3)
    _eco(mods, hass)._held[ENT] = _hrng(mods, "away", 60, 82)
    coord.zone_manager.update_zone_climate_state(ZONE)
    assert z.preset_mode == "away"
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert _selects(hass) == [{"entity_id": SEL, "option": "away"}]


# ==========================================================================
# M10 / M12 — restart, RAM-only select record, persistence + migration
# ==========================================================================


@pytest.mark.asyncio
async def test_m10_restart_reselects_once_then_skips(mods, monkeypatch):
    """C.10: `_last_sent_select` is RAM-only. After a restart the rehydrated
    settled hold reads home; the first S1 tick selects home ONCE (R2), the
    next writes nothing."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    await _tick(coord, hass)
    _set_eco(hass, low=71.0, high=75.0)
    clk.t = T0 + 400
    coord.zone_manager.update_zone_climate_state(ZONE)        # settles 71/75
    blob = json.loads(json.dumps(coord._build_zone_state_snapshot()["__w1c_adapter"]))
    assert blob[ENT]["held"]["settled"] == [71.0, 75.0]
    S._test_reset_cache()                                     # "restart"
    coord._rehydrate_w1c_adapter({"__w1c_adapter": blob})
    eco2 = _eco(mods, hass)
    assert eco2._last_sent_select == {}
    assert eco2._held[ENT].settled == (71.0, 75.0)
    n = len(_selects(hass))
    await _tick(coord, hass)
    assert len(_selects(hass)) == n + 1
    await _tick(coord, hass)
    assert len(_selects(hass)) == n + 1


def test_m12_legacy_option_b_held_migrates_once(mods, monkeypatch, caplog):
    """C.1 / C.13: the v5.103.40 3-list `held` migrates to Held(range) on
    rehydrate with ONE INFO line; the next save writes `_schema_version` 2;
    a v2 slice rehydrates with no migration line."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    S._test_reset_cache()
    with caplog.at_level(logging.INFO):
        coord._rehydrate_w1c_adapter({"__w1c_adapter": {ENT: {
            "held": ["home", 70.0, 77.0], "ranges": []}}})
    eco = _eco(mods, hass)
    assert eco._held[ENT] == _hrng(mods, "home", 70, 77, T0)
    mig = [r for r in caplog.records if "migrated" in r.getMessage()]
    assert len(mig) == 1
    blob = S.export_adapter_state()
    assert blob[ENT]["_schema_version"] == 2
    assert blob[ENT]["held"] == {"label": "home", "mode": "range", "lo": 70.0,
                                 "hi": 77.0, "t_issued_wall": T0, "settled": None}
    caplog.clear()
    S._test_reset_cache()
    with caplog.at_level(logging.INFO):
        coord._rehydrate_w1c_adapter({"__w1c_adapter": json.loads(json.dumps(blob))})
    assert not [r for r in caplog.records if "migrated" in r.getMessage()]
    assert _eco(mods, hass)._held[ENT] == _hrng(mods, "home", 70, 77, T0)


def test_m12_v2_select_hold_round_trips(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "sleep", T0 - 5, (70.0, 76.0))
    blob = json.loads(json.dumps(S.export_adapter_state()))
    S._test_reset_cache()
    S.rehydrate_adapter_state(hass, blob)
    assert _eco(mods, hass)._held[ENT] == _hsel(mods, "sleep", T0 - 5, (70.0, 76.0))


@pytest.mark.parametrize("bad", [
    {"label": "home", "mode": "bogus", "lo": None, "hi": None, "t_issued_wall": 1.0, "settled": None},
    {"label": "home", "mode": "range", "lo": None, "hi": 77.0, "t_issued_wall": 1.0, "settled": None},
    ["home", 70.0],
    "junk",
])
def test_m12_malformed_held_is_dropped_with_a_warning(mods, monkeypatch, caplog, bad):
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    S._test_reset_cache()
    with caplog.at_level(logging.WARNING):
        S.rehydrate_adapter_state(hass, {ENT: {"_schema_version": 2, "held": bad, "ranges": []}})
    assert ENT not in _eco(mods, hass)._held
    assert any("malformed held" in r.getMessage() for r in caplog.records)


# ==========================================================================
# M17 — schedule re-capture (C.7)
# ==========================================================================


@pytest.mark.asyncio
async def test_m17_r4_reselect_logs_and_the_second_raises_the_repair(mods, monkeypatch, caplog):
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    from homeassistant.helpers import issue_registry as ir
    created = []
    monkeypatch.setattr(ir, "async_create_issue",
                        lambda *a, **k: created.append((a[2], k["translation_key"])))
    eco = _eco(mods, hass)
    mods["hvac_setpoint"].record_ura_setpoint(ENT, 68.0, 74.0)

    async def _drift_and_reselect():
        eco._held[ENT] = _hsel(mods, "home", clk.t, (71.0, 75.0))
        eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
        clk.t += 600
        _set_eco(hass, low=68.0, high=74.0)
        assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True
        await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")

    with caplog.at_level(logging.INFO):
        await _drift_and_reselect()
        assert created == []
        await _drift_and_reselect()
    assert len([r for r in caplog.records if "branch_s_schedule_recapture" in r.getMessage()]) == 2
    assert created == [(f"thermostat_hold_action_not_set_{ENT}", "thermostat_hold_action_not_set")]
    assert len(_selects(hass)) == 2
    # Noise bound: once raised, R4 stands down on this thermostat.
    eco._held[ENT] = _hsel(mods, "home", clk.t, (71.0, 75.0))
    clk.t += 600
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is False


@pytest.mark.asyncio
async def test_m17_recaptures_outside_24_h_do_not_raise(mods, monkeypatch):
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    from homeassistant.helpers import issue_registry as ir
    created = []
    monkeypatch.setattr(ir, "async_create_issue", lambda *a, **k: created.append(a[2]))
    eco = _eco(mods, hass)
    for gap in (0, 86400):
        clk.t += gap
        eco._recapture_pending.add((ZONE, ENT))
        await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    assert created == []


@pytest.mark.asyncio
async def test_m17_a_plain_s1_reclaim_is_not_counted_as_a_recapture(mods, monkeypatch, caplog):
    """Only an R4-driven select counts: a person's change that S1 reclaims
    (zone read manual) never raises the hold-action Repair."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    from homeassistant.helpers import issue_registry as ir
    created = []
    monkeypatch.setattr(ir, "async_create_issue", lambda *a, **k: created.append(a[2]))
    eco = _eco(mods, hass)
    eco._recapture_pending.add((ZONE, ENT))                   # one R4-driven select
    with caplog.at_level(logging.INFO):
        for _ in range(3):
            await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
            clk.t += 600
    assert len([r for r in caplog.records if "branch_s_schedule_recapture" in r.getMessage()]) == 1
    assert created == []


# ==========================================================================
# Profile switch / prune — the RAM records go with the entity
# ==========================================================================


def test_flush_entity_forgets_select_records_and_recapture_state(mods, monkeypatch):
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
    eco._last_sent_select[(ZONE, "climate.other")] = ("select_option", "sleep")
    eco._recapture_pending.add((ZONE, ENT))
    eco._recapture_times[ENT] = [T0]
    eco.flush_entity(ENT)
    assert ENT not in eco._held
    assert eco._last_sent_select == {(ZONE, "climate.other"): ("select_option", "sleep")}
    assert eco._recapture_pending == set() and eco._recapture_times == {}


@pytest.mark.asyncio
async def test_branch_s_noop_inside_hold_preset(mods, monkeypatch):
    """REV 4-C.1 Branch-S no-op: held select + this zone's record + the zone
    reads the preset -> SKIPPED with zero calls (a direct S1-shaped call)."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    eco = _eco(mods, hass)
    await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    n = len(hass.services.calls)
    res = await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.SKIPPED_ALREADY_CORRECT, "no_op_last_sent_matches")
    assert len(hass.services.calls) == n
    res = await eco.hold_preset(hass, ENT, "home", site="S1", zone_id="zone_9", reason="r")
    assert res.status is S.WriteStatus.APPLIED                 # another zone's record


@pytest.mark.asyncio
async def test_vacancy_site_skips_this_zones_held_away_select(mods, monkeypatch):
    """Wire-in (zone keying at the vacancy `Already away` skip): an away
    select THIS zone made reads away -> no write."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=60.0, high=82.0)
    coord._zone_intelligence_enabled = True
    monkeypatch.setattr(coord, "_zone_conditioning_retreat_ok", lambda z: True)
    z = coord.zone_manager.zones[ZONE]
    z.last_occupied_time = H.utc_now() - timedelta(hours=3)
    await _eco(mods, hass).hold_preset(hass, ENT, "away", site="S1", zone_id=ZONE, reason="r")
    coord.zone_manager.update_zone_climate_state(ZONE)
    assert z.preset_mode == "away"
    n = len(hass.services.calls)
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert len(hass.services.calls) == n


@pytest.mark.asyncio
async def test_m4_upgrade_writes_even_when_live_legs_coincide(mods, monkeypatch):
    """A select hold whose device comfort happens to equal the new
    composition is still upgraded to a range hold in THIS call (else the
    next tick's R1 makes it two writes)."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    _set_eco(hass, low=69.0, high=78.0)
    res = await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE, site="s", reason="r")
    assert res.status is _S(mods).WriteStatus.APPLIED
    assert eco._held[ENT].mode == "range"


@pytest.mark.asyncio
async def test_c5_within_manual_change_is_measured_against_settled(mods, monkeypatch):
    """C.5 falsifier (case C, `_resolve_reference` -> `reference_setpoints`):
    the zone already reads manual at 71/73 (a person's first change); the
    person moves cool again to 72. The delta is measured on the changed
    leg against the comfort URA holds: settled cool 75 -> -3. The Seasonal
    Baseline (77) would give -5; the live legs would give 0 (declined)."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
    clk.t = T0 + 600
    _set_eco(hass, low=71.0, high=72.0)
    coord._override_arrester._handle_climate_change(
        _eco_ev(("heat_cool", 71.0, 73.0), ("heat_cool", 71.0, 72.0)))
    await H.drain(hass, rounds=6)
    rows = [r for r in hass.data[mods["const"].DOMAIN]["activity_logger"].actions("override_detected")
            if r.get("entity_id") == ENT]
    assert len(rows) == 1
    assert rows[0]["details"]["delta_f"] == -3.0


@pytest.mark.asyncio
async def test_s1_skip_keeps_the_selects_suppression_window(mods, monkeypatch):
    """Wire-in (S1 short-circuit keyed by zone): the tick after a select
    skips BEFORE the strategy call, so the select's 120 s preset
    suppression survives. Mis-keyed, S1 would reach `hold_preset`, whose
    SKIPPED path unsuppresses the entity."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _tick(coord, hass)
    arr = coord._override_arrester
    assert ENT in arr._suppressed_until
    _set_eco(hass, low=71.0, high=75.0)
    clk.t = T0 + 30
    await _tick(coord, hass)
    assert ENT in arr._suppressed_until
    assert len(_selects(hass)) == 1


@pytest.mark.asyncio
async def test_vacancy_skip_keeps_the_selects_suppression_window(mods, monkeypatch):
    """Wire-in (vacancy `Already away` skip keyed by zone): same contract."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=60.0, high=82.0)
    coord._zone_intelligence_enabled = True
    monkeypatch.setattr(coord, "_zone_conditioning_retreat_ok", lambda z: True)
    z = coord.zone_manager.zones[ZONE]
    z.last_occupied_time = H.utc_now() - timedelta(hours=3)
    await _tick(coord, hass)                       # vacancy away select
    assert _selects(hass) == [{"entity_id": SEL, "option": "away"}]
    arr = coord._override_arrester
    assert ENT in arr._suppressed_until
    clk.t = T0 + 30
    await _tick(coord, hass)
    assert ENT in arr._suppressed_until
    assert len(_selects(hass)) == 1


# ==========================================================================
# Review fix pass 2026-10-06 (B-M1/D-M1, A-M2, D-M2, C-HIGH, B-L2, B-L3, A-L2)
# ==========================================================================


def _ts(wall):
    """A state `last_updated` at the given wall epoch second (tz-aware)."""
    return datetime.fromtimestamp(wall, tz=timezone.utc)


def _st(mode, low, high, lu):
    """A climate state object; `lu` None = no timestamp attribute at all."""
    s = types.SimpleNamespace(entity_id=ENT, state=mode, attributes={
        "target_temp_low": low, "target_temp_high": high,
        "hvac_modes": ["off", "heat", "cool", "heat_cool"]})
    if lu is not None:
        s.last_updated = _ts(lu)
    return s


def _ev(old, new):
    return types.SimpleNamespace(
        data={"entity_id": ENT, "new_state": new, "old_state": old},
        context=types.SimpleNamespace(user_id=None, parent_id=None, id="ctx"))


def _overrides(hass, mods):
    return [r for r in hass.data[mods["const"].DOMAIN]["activity_logger"].actions("override_detected")
            if r.get("entity_id") == ENT]


@pytest.mark.asyncio
async def test_b_m1_person_change_as_first_event_after_the_window_is_booked(mods, monkeypatch):
    """B-M1 = D-M1 (handler read order): select home at T0, the device
    holds its comfort 71/75, NOTHING reads it until a person moves cool to
    73 at T0+181. That event is the first read after the window. The
    arrester reads the OLD state first, settles 71/75 and books ONE
    override (delta -2). States here carry no timestamp, so only the read
    order protects them (reading NEW first settles 71/73 = absorbed)."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _tick(coord, hass)                                    # select home at T0
    clk.t = T0 + 181
    coord._override_arrester._handle_climate_change(_ev(
        _st("heat_cool", 71.0, 75.0, None), _st("heat_cool", 71.0, 73.0, None)))
    await H.drain(hass, rounds=6)
    rows = _overrides(hass, mods)
    assert len(rows) == 1
    assert rows[0]["details"]["delta_f"] == -2.0
    assert _eco(mods, hass)._held[ENT].settled == (71.0, 75.0)


@pytest.mark.asyncio
async def test_d_m1_a_reader_of_the_new_state_first_never_absorbs_the_change(mods, monkeypatch):
    """D-M1 (refusal): another reader sees the person's NEW state (stamped
    after the window end) BEFORE the arrester. It must not settle from it:
    it reads the label, settles nothing, and the arrester then books the
    change against the comfort as of the window end (71/75)."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _tick(coord, hass)
    eco = _eco(mods, hass)
    clk.t = T0 + 300
    old = _st("heat_cool", 71.0, 75.0, T0 + 5)
    new = _st("heat_cool", 71.0, 73.0, T0 + 290)
    assert eco.preset_of(new, None, hass=hass, entity_id=ENT) == "home"
    assert eco._held[ENT].settled is None
    coord._override_arrester._handle_climate_change(_ev(old, new))
    await H.drain(hass, rounds=6)
    assert len(_overrides(hass, mods)) == 1
    assert eco._held[ENT].settled == (71.0, 75.0)


def test_d_m1_a_later_state_settles_from_the_state_seen_before_the_window_end(mods, monkeypatch):
    """D-M1 (state as of the window end): the comfort 71/75 was seen inside
    the window; the first read after it is a LATER state 71/73 -> settled
    from the 71/75 seen before the end, so 71/73 reads `manual`."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 30
    assert eco.preset_of(_st("heat_cool", 71.0, 75.0, T0 + 5), None, hass=hass, entity_id=ENT) == "home"
    clk.t = T0 + 300
    assert eco.preset_of(_st("heat_cool", 71.0, 73.0, T0 + 290), None, hass=hass, entity_id=ENT) == "manual"
    assert eco._held[ENT].settled == (71.0, 75.0)


def test_d_m1_a_later_state_equal_to_an_earlier_later_state_settles(mods, monkeypatch):
    """D-M1 "unless it equals the prior state": with nothing seen before the
    window end (e.g. after a restart), a later state is refused; a second,
    DIFFERENT state with the same legs settles (the legs did not change
    between them). The same state read twice never does."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 400
    s1 = _st("heat_cool", 71.0, 75.0, T0 + 300)
    assert eco.preset_of(s1, None, hass=hass, entity_id=ENT) == "home"
    assert eco.preset_of(s1, None, hass=hass, entity_id=ENT) == "home"
    assert eco._held[ENT].settled is None
    assert eco.preset_of(_st("heat_cool", 71.0, 75.0, T0 + 350), None, hass=hass, entity_id=ENT) == "home"
    assert eco._held[ENT].settled == (71.0, 75.0)


@pytest.mark.parametrize("boundary,settles", [(179, True), (180, True), (181, False)])
def test_d_m1_settle_boundary_is_the_window_end(mods, monkeypatch, boundary, settles):
    """A state stamped at/before T0+180 existed at the window end and
    settles at once; one stamped T0+181 is refused (nothing seen before)."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 400
    eco.preset_of(_st("heat_cool", 71.0, 75.0, T0 + boundary), None, hass=hass, entity_id=ENT)
    assert (eco._held[ENT].settled is not None) is settles


def test_a_l2_settle_requests_one_save(mods, monkeypatch):
    """A-L2: the lazy settle asks for a zone-state save once (reason
    `w1c_adapter_settled`); later equal reads ask for nothing."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    saves = []
    monkeypatch.setattr(S._CTX, "on_change", saves.append)
    eco = _eco(mods, hass)
    eco._held[ENT] = _hsel(mods, "home", T0)
    clk.t = T0 + 181
    for _ in range(3):
        eco.preset_of(_set_eco(hass, low=71.0, high=75.0), None, hass=hass, entity_id=ENT)
    assert saves == ["w1c_adapter_settled"]


def test_b_l3_migration_requests_a_save_and_v2_does_not(mods, monkeypatch):
    """B-L3: a legacy option-B `held` migrates and asks for ONE save; a v2
    slice rehydrates with no save request."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    saves = []
    monkeypatch.setattr(S._CTX, "on_change", saves.append)
    S._test_reset_cache()
    coord._rehydrate_w1c_adapter({"__w1c_adapter": {ENT: {"held": ["home", 70.0, 77.0], "ranges": []}}})
    assert saves == ["w1c_adapter_migrated"]
    blob = json.loads(json.dumps(S.export_adapter_state()))
    saves.clear()
    S._test_reset_cache()
    coord._rehydrate_w1c_adapter({"__w1c_adapter": blob})
    assert saves == []


# ---- A-M2: the reference for a preset URA does not hold -----------------


@pytest.mark.asyncio
async def test_a_m2_q7_pre_arrival_reference_is_the_arrival_preset_not_the_held_away(mods, monkeypatch):
    """A-M2 / Q7: the zone holds away (settled 60/82); the arrival reference
    (home_day -> home) measures against HOME's effective range 70/77, not
    the held away numbers."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    clk.t = T0 + 600
    res = coord._override_arrester._baseline_resolver
    eco._held[ENT] = _hsel(mods, "away", T0, (60.0, 82.0))
    assert res(ZONE, None, True) == ("home", 77.0, 70.0)
    eco._held[ENT] = _hrng(mods, "away", 60, 82)
    assert res(ZONE, None, True) == ("home", 77.0, 70.0)
    assert res(ZONE, "away") == ("away", 82.0, 60.0)           # label match: held numbers


@pytest.mark.asyncio
async def test_a_m2_q7_reference_uses_a_stored_composition_of_the_requested_preset(mods, monkeypatch):
    """A-M2: the reference for a preset URA does not hold is its EFFECTIVE
    range — a stored composition wins over the baseline (option B)."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    clk.t = T0 + 600
    eco._ranges[(ENT, "home", "summer")] = (69.0, 78.0)
    eco._held[ENT] = _hsel(mods, "away", T0, (60.0, 82.0))
    assert coord._override_arrester._baseline_resolver(ZONE, None, True) == ("home", 78.0, 69.0)


@pytest.mark.parametrize("house,reverts,expect", [
    ("sleep", False, None),           # target sleep: eff 70/76 == live -> no revert
    ("home_day", True, (72.0, 68.0)),  # target home == held label: settled 68/72
])
@pytest.mark.asyncio
async def test_a_m2_startup_audit_measures_the_target_preset(mods, monkeypatch, house, reverts, expect):
    """A-M2 (startup audit): held = home select settled 68/72; the device
    reads 70/76 (manual). In Sleep the audit targets `sleep`, whose
    effective range IS 70/76 -> nothing to revert (the held home numbers
    would read a 4 °F departure). In Home the held numbers apply."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=76.0)
    arr = coord._override_arrester
    _eco(mods, hass)._held[ENT] = _hsel(mods, "home", T0, (68.0, 72.0))
    clk.t = T0 + 600
    await arr.async_startup_audit(coord._preset_manager, house)
    await H.drain(hass)
    assert bool(arr._override_active.get(ZONE)) is reverts
    if expect is not None:
        ep = arr._arrest_episode[ZONE]
        assert (ep["expected_cool"], ep["expected_heat"]) == expect


# ---- D-M2: person-protection gates hold the S1 re-assert -----------------


def _absorbed_after_restart(mods, monkeypatch):
    """A person's 69/74 absorbed as `settled` of a home select; restart =
    no RAM select record, so the zone (reading home) needs a re-assert."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=69.0, high=74.0)
    _eco(mods, hass)._held[ENT] = _hsel(mods, "home", T0, (69.0, 74.0))
    clk.t = T0 + 600
    return coord, hass


@pytest.mark.parametrize("gate", ["tao", "immune", "grace", "borrow_row", "nudge_in_flight"])
@pytest.mark.asyncio
async def test_d_m2_reassert_is_held_by_the_person_protection_gates(mods, monkeypatch, gate):
    """D-M2 (ruling b): TAO / an immune hold (a/b), an arrester grace (c) or
    a live borrow (e) hold the S1 re-assert — the person's absorbed change
    is not overwritten. Positive control: the gate gone -> ONE select."""
    coord, hass = _absorbed_after_restart(mods, monkeypatch)
    arr = coord._override_arrester
    if gate == "tao":
        arr._temp_arrester_override_active = True
    elif gate == "immune":
        monkeypatch.setattr(arr, "_is_hold_immune", lambda z: z == ZONE)
    elif gate == "grace":
        arr._grace_timers[ZONE] = lambda: None
    elif gate == "borrow_row":
        ex = sys.modules[type(arr).__module__.replace("hvac_override", "hvac_excursion")]
        monkeypatch.setattr(ex, "is_borrow_active", lambda z: z == ZONE)
    else:
        arr._nudge_in_flight.add(ZONE)
    await _tick(coord, hass)
    assert coord.zone_manager.zones[ZONE].preset_mode == "home"
    assert _selects(hass) == []
    arr._temp_arrester_override_active = False
    monkeypatch.setattr(arr, "_is_hold_immune", lambda z: False)
    arr._grace_timers.pop(ZONE, None)
    arr._nudge_in_flight.discard(ZONE)
    ex = sys.modules[type(arr).__module__.replace("hvac_override", "hvac_excursion")]
    monkeypatch.setattr(ex, "is_borrow_active", lambda z: False)
    await _tick(coord, hass)
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]


@pytest.mark.asyncio
async def test_d_m2_passive_arrester_does_not_hold_the_reassert(mods, monkeypatch):
    """Ruling b names (a/b), (c), (e) — gate (d) (arrester disabled) does
    NOT hold a re-assert."""
    coord, hass = _absorbed_after_restart(mods, monkeypatch)
    coord._override_arrester.enabled = False
    await _tick(coord, hass)
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]


@pytest.mark.asyncio
async def test_d_m2_unwired_arrester_holds_the_reassert(mods, monkeypatch):
    """Fail-closed like the manual rule: no arrester wired -> no re-assert."""
    coord, hass = _absorbed_after_restart(mods, monkeypatch)
    coord._preset_manager._arrester = None
    await _tick(coord, hass)
    assert _selects(hass) == []


@pytest.mark.parametrize("gate", ["tao", "nudge_in_flight"])
@pytest.mark.asyncio
async def test_d_m2_vacancy_away_reassert_is_held_by_a_b_and_e(mods, monkeypatch, gate):
    """D-M2 at the vacancy `Already away` re-assert: (a/b) and (e) — the
    gates this bypass respects over manual — hold it; positive control
    without the gate re-selects away."""
    _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch, low=60.0, high=82.0)
    coord._zone_intelligence_enabled = True
    monkeypatch.setattr(coord, "_zone_conditioning_retreat_ok", lambda z: True)
    z = coord.zone_manager.zones[ZONE]
    z.last_occupied_time = H.utc_now() - timedelta(hours=3)
    _eco(mods, hass)._held[ENT] = _hrng(mods, "away", 60, 82)
    arr = coord._override_arrester
    if gate == "tao":
        arr._temp_arrester_override_active = True
    else:
        arr._nudge_in_flight.add(ZONE)
    coord.zone_manager.update_zone_climate_state(ZONE)
    assert z.preset_mode == "away"
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert _selects(hass) == []
    arr._temp_arrester_override_active = False
    arr._nudge_in_flight.discard(ZONE)
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert _selects(hass) == [{"entity_id": SEL, "option": "away"}]


@pytest.mark.asyncio
async def test_d_m2_carrier_reassert_path_never_reads_the_gates(mods, monkeypatch):
    """Carrier byte-identity: a Carrier zone at its target never reaches the
    re-assert gate read (the adapter says no re-assert first)."""
    coord, hass = _rig(mods, monkeypatch)
    calls = []
    real = coord._reassert_refused
    monkeypatch.setattr(coord, "_reassert_refused", lambda z, g: calls.append(z) or real(z, g))
    H.set_climate(hass, CAR, preset_mode="home", hold_activity="home")
    coord.zone_manager.update_zone_climate_state(CAR_ZONE)
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert CAR_ZONE not in calls


# ---- C-HIGH: the Branch-S no-op's `preset_of(...) == preset` clause -------


@pytest.mark.asyncio
async def test_c_high_s1_reclaims_a_settled_person_change_with_exactly_one_select(mods, monkeypatch):
    """C-HIGH (S1-tick version): select home, settle 68/72, a person moves
    the legs to 64/78 -> the zone reads manual; three S1 ticks make EXACTLY
    one new select (the Branch-S no-op must not swallow the reclaim, and
    the re-select's window keeps the next ticks quiet)."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    await _tick(coord, hass)
    clk.t = T0 + 181
    coord.zone_manager.update_zone_climate_state(ZONE)
    eco = _eco(mods, hass)
    assert eco._held[ENT].settled == (68.0, 72.0)
    _set_eco(hass, low=64.0, high=78.0)
    for _ in range(3):
        await _tick(coord, hass)
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}] * 2


# ---- B-L2: a stale recapture request never outlives one skip check -------


@pytest.mark.asyncio
async def test_b_l2_stale_recapture_request_is_cleared_by_the_next_skip_check(mods, monkeypatch, caplog):
    """R4 asks for a recapture, but S1 does not act on it (e.g. a gate). The
    next skip check without R4 clears it, so a later select is NOT counted
    as a schedule recapture."""
    clk = _clock(monkeypatch, mods)
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    mods["hvac_setpoint"].record_ura_setpoint(ENT, 68.0, 74.0)
    eco._held[ENT] = _hsel(mods, "home", T0, (71.0, 75.0))
    eco._last_sent_select[(ZONE, ENT)] = ("select_option", "home")
    clk.t = T0 + 600
    _set_eco(hass, low=68.0, high=74.0)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is True     # R4
    _set_eco(hass, low=71.0, high=75.0)
    assert eco.hold_needs_reassert(hass, ENT, "home", zone_id=ZONE) is False
    eco._last_sent_select.clear()
    with caplog.at_level(logging.INFO):
        await eco.hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="r")
    assert _selects(hass) == [{"entity_id": SEL, "option": "home"}]
    assert not [r for r in caplog.records if "branch_s_schedule_recapture" in r.getMessage()]

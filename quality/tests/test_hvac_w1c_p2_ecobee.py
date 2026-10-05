"""HVAC W1-C P2 — ecobee (HomeKit) thin command adapter: behavioural suite.

Plan: docs/planning/PLANNING_hvac_w1c_p2_ecobee.md REV 3 + D0b sections +
"Operator on-site check 2026-10-05" (min delta = configured value, default
5 °F per thermostat; the adapter widens before sending; no learning).

Every test drives REAL production code on the shared W1-B harness (real
HVACCoordinator / OverrideArrester / PresetManager / strategy on the smoke
StubHass). The thermostat profile is resolved through a REAL registry
lookup (`strategy_for`): a fixture entity + device registry reports
`homekit_controller` + manufacturer "ecobee Inc." for zone 1 and
`ha_carrier` for zones 2/3. Oracles are hand-derived literals from
SEASONAL_DEFAULTS (summer Home 77/70 -> range 70/77; summer Sleep 76/70 ->
70/76; shoulder Home 74/70 -> 70/74 widened to the 5 °F min delta -> 70/75).

Falsifiable invariants under test (plan §6):
  INV-E2  URA never sends `set_preset_mode`, a `temperature` key, or a range
          while the live mode is not heat_cool, to a HomeKit ecobee.
  INV-R   whenever S1 skips preset P on an ecobee, the live legs equal
          effective_range(P).
  INV-P   an ecobee zone and a Carrier zone fed equivalent states make the
          same HC decision (only the wire verb differs).
  INV-F   no HC code path chooses a feature by brand / capability field.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
URA = ROOT / "custom_components" / "universal_room_automation"
DC = URA / "domain_coordinators"

ZONE = "zone_1"
ENT = "climate.test_zone_1"          # ecobee over HomeKit
SEL = "select.test_zone_1_current_mode"
DEV = "dev_ecobee_1"
CAR = "climate.test_zone_2"          # Carrier
CAR_ZONE = "zone_2"
HK_OTHER = "climate.hk_other"        # HomeKit, not ecobee
NATIVE_ECOBEE = "climate.native_ecobee"
MADE_UP = "climate.madeup"
MISSING = "climate.not_in_registry"


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


# --------------------------------------------------------------------------
# Registry fixtures (real lookup path; scoped monkeypatch)
# --------------------------------------------------------------------------


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


def _install_registry(monkeypatch, mods, entries=None, devices=None):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    if entries is None:
        entries = {
            ENT: _entry(ENT, "homekit_controller", DEV),
            SEL: _entry(SEL, "homekit_controller", DEV, "ecobee_mode"),
            CAR: _entry(CAR, "ha_carrier"),
            "climate.test_zone_3": _entry("climate.test_zone_3", "ha_carrier"),
            HK_OTHER: _entry(HK_OTHER, "homekit_controller", "dev_other"),
            NATIVE_ECOBEE: _entry(NATIVE_ECOBEE, "ecobee", "dev_native"),
            MADE_UP: _entry(MADE_UP, "acme_thermo"),
        }
    if devices is None:
        devices = {
            DEV: types.SimpleNamespace(manufacturer="ecobee Inc."),
            "dev_other": types.SimpleNamespace(manufacturer="Honeywell"),
            "dev_native": types.SimpleNamespace(manufacturer="ecobee Inc."),
        }
    reg, dreg = _Reg(entries), _DevReg(devices)
    monkeypatch.setattr(er, "async_get", lambda _h: reg)
    monkeypatch.setattr(
        er, "async_entries_for_device",
        lambda r, dev, include_disabled_entities=False: [
            e for e in r.entries.values() if e.device_id == dev
        ],
    )
    monkeypatch.setattr(dr, "async_get", lambda _h: dreg)
    mods["hvac_strategy"]._test_reset_cache()
    return reg, dreg


def _set_eco(hass, *, mode="heat_cool", low=None, high=None, temperature=None,
             modes=("off", "heat", "cool", "heat_cool"), ent=ENT):
    """An ecobee over HomeKit: NO preset_mode / preset_modes attributes.
    Outside heat_cool the legs are None and `temperature` is set (D0b)."""
    attrs = {
        "hvac_modes": list(modes),
        "target_temp_low": low if mode == "heat_cool" else None,
        "target_temp_high": high if mode == "heat_cool" else None,
        "current_temperature": 74.0,
        "min_temp": 45, "max_temp": 92,
    }
    if mode != "heat_cool":
        attrs["temperature"] = temperature
    hass.states.async_set(ent, mode, attrs)
    return hass.states.get(ent)


def _rig(mods, monkeypatch, *, season="summer", house="home_day", low=72.0, high=68.0,
         mode="heat_cool"):
    coord, hass = H.make_coord(mods)
    _install_registry(monkeypatch, mods)
    mods["hvac_setpoint"]._test_clear_ura_setpoints()
    coord._house_state = house
    coord._zone_intelligence_enabled = False
    coord._preset_manager._current_season = season
    for other in ("zone_2", "zone_3"):
        coord.zone_manager.zones[other].preset_mode = "home"
    _set_eco(hass, mode=mode, low=low, high=high)
    coord.zone_manager.zones[ZONE].hvac_mode = mode
    coord._override_arrester.enabled = True
    return coord, hass


def _S(mods):
    return mods["hvac_strategy"]


def _eco(mods, hass):
    return _S(mods).strategy_for(hass, ENT)


async def _tick(coord, hass):
    """One S1 pass, R1 (the hub read) refreshed first, as the cycle does."""
    coord.zone_manager.update_zone_climate_state(ZONE)
    await coord._apply_house_state_presets()
    await H.drain(hass)


def _temp(hass, ent=ENT):
    return [c[2] for c in hass.services.calls
            if c[0] == "climate" and c[1] == "set_temperature" and c[2].get("entity_id") == ent]


def _presets(hass, ent=ENT):
    return [c for c in hass.services.calls
            if c[0] == "climate" and c[1] == "set_preset_mode" and c[2].get("entity_id") == ent]


def _ledger(hass, mods, action):
    return hass.data[mods["const"].DOMAIN]["activity_logger"].actions(action)


def _assert_inv_e2(hass):
    """INV-E2 over every call this test made to the ecobee."""
    for d, svc, data in hass.services.calls:
        if data.get("entity_id") != ENT:
            continue
        assert d == "climate", (d, svc)
        assert svc != "set_preset_mode"
        if svc == "set_temperature":
            assert "temperature" not in data
            assert set(data) == {"entity_id", "target_temp_low", "target_temp_high"}


# ==========================================================================
# D1 — detection, per-entity cache, profile switch, display attrs
# ==========================================================================


@pytest.mark.parametrize("eid,profile,source,cls", [
    (CAR, "carrier", "detected", "CarrierStrategy"),
    (ENT, "ecobee_homekit", "detected", "EcobeeHomeKitStrategy"),
    (HK_OTHER, "generic", "detected", "GenericStrategy"),
    (NATIVE_ECOBEE, "generic", "detected", "GenericStrategy"),
    (MADE_UP, "generic", "detected", "GenericStrategy"),
    (MISSING, "generic", "default", "GenericStrategy"),
])
def test_resolution_matrix(mods, monkeypatch, eid, profile, source, cls):
    _install_registry(monkeypatch, mods)
    S = _S(mods)
    inst = S.strategy_for(None, eid)
    assert type(inst).__name__ == cls
    assert S.profile_info(None, eid) == (profile, source)


def test_carrier_goes_through_the_unchanged_platform_cache(mods, monkeypatch):
    _install_registry(monkeypatch, mods)
    S = _S(mods)
    a = S.strategy_for(None, CAR)
    assert S._STRATEGY_BY_PLATFORM["ha_carrier"] is a
    assert S.strategy_for(None, "climate.test_zone_3") is a
    assert "homekit_controller" not in S._STRATEGY_BY_PLATFORM


@pytest.mark.parametrize("order", [(ENT, HK_OTHER), (HK_OTHER, ENT)])
def test_ecobee_and_other_homekit_resolve_independently(mods, monkeypatch, order):
    """PR2-7: the first HomeKit resolution must not win for both."""
    _install_registry(monkeypatch, mods)
    S = _S(mods)
    got = {e: S.strategy_for(None, e) for e in order}
    assert type(got[ENT]) is S.EcobeeHomeKitStrategy
    assert type(got[HK_OTHER]) is S.GenericStrategy


def test_strategy_for_platform_refuses_homekit(mods):
    S = _S(mods)
    assert type(S.strategy_for_platform("homekit_controller")) is S.GenericStrategy


@pytest.mark.asyncio
async def test_w1c_p2_registry_miss_generic_noop_persists(mods, monkeypatch):
    """P1 F1: a registry-miss entity's Generic is cached per ENTITY, so its
    D2.5 no-op fires on the second S1 call (pre-P2: a fresh Generic per call
    forgot `last_sent` and re-wrote every tick)."""
    coord, hass = H.make_coord(mods)
    _install_registry(monkeypatch, mods, entries={}, devices={})
    S = _S(mods)
    H.set_climate(hass, MISSING, preset_mode="manual", hold_activity="manual")
    r1 = await S.strategy_for(hass, MISSING).hold_preset(
        hass, MISSING, "home", site="S1", zone_id=ZONE, reason="t")
    assert r1.status is S.WriteStatus.APPLIED
    H.set_climate(hass, MISSING, preset_mode="home", hold_activity="home")
    r2 = await S.strategy_for(hass, MISSING).hold_preset(
        hass, MISSING, "home", site="S1", zone_id=ZONE, reason="t")
    assert r2.status is S.WriteStatus.SKIPPED_ALREADY_CORRECT
    assert len(H.preset_writes(hass, MISSING, "home")) == 1


@pytest.mark.asyncio
async def test_profile_switch_flushes_state_and_closes_live_borrows(mods, monkeypatch):
    """§4.1 F3: a resolved brand change flushes last_sent / held / ranges on
    both instances, queues the switch, and the HC drain unsuppresses the
    entity and closes the zone's live borrow with NO write."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("home", 70.0, 77.0)
    eco._ranges[(ENT, "home", "summer")] = (69.0, 78.0)
    eco._record_sent(ENT, "set_preset_mode", "home")
    from homeassistant.helpers import entity_registry as er
    er.async_get(None).entries[ENT] = _entry(ENT, "ha_carrier")
    car = S.strategy_for(hass, ENT)
    assert type(car) is S.CarrierStrategy
    assert ENT not in eco._held and not eco._ranges and eco.last_sent(ENT, "set_preset_mode") is None
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.BANKING, duration_s=600,
                      pre_preset="home")
    coord._override_arrester.suppress(ENT)
    calls_before = len(hass.services.calls)
    await coord._w1c_drain_profile_switches()
    await H.drain(hass)
    assert ex.live_token_for(ZONE) is None
    assert ENT not in coord._override_arrester._suppressed_until
    assert len(hass.services.calls) == calls_before
    assert S.drain_profile_switches() == []


@pytest.mark.asyncio
async def test_profile_switch_drain_runs_in_the_decision_cycle(mods, monkeypatch):
    """Wire-in anchor: the enclosing `_run_decision_cycle` drains a queued
    profile switch (the borrow on the switched thermostat's zone closes)."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.BANKING, duration_s=600,
                      pre_preset="home")
    S._PROFILE_SWITCHES.append((ENT, "homekit_controller", "ha_carrier"))
    coord._startup_audit_done = True       # async_setup's flag (not run here)
    await coord._run_decision_cycle()
    await H.drain(hass)
    assert ex.live_token_for(ZONE) is None
    assert S._PROFILE_SWITCHES == []


def test_zone_status_attrs_name_the_profile(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    a1 = coord.zone_manager.get_zone_status_attrs(ZONE)
    a2 = coord.zone_manager.get_zone_status_attrs(CAR_ZONE)
    assert (a1["thermostat_profile"], a1["profile_source"]) == ("ecobee_homekit", "detected")
    assert (a2["thermostat_profile"], a2["profile_source"]) == ("carrier", "detected")


# ==========================================================================
# D2 — command verbs + effective range
# ==========================================================================


@pytest.mark.asyncio
async def test_s1_home_writes_one_effective_range_and_stamps_held_before_the_wire(mods, monkeypatch):
    """S1 `home` on an ecobee reading a person's 68/72 (summer): ONE
    set_temperature {70, 77} through the funnel, one climate_write row, the
    pair ring holds (70, 77), `held` stamped BEFORE the wire with the
    post-guard values, zero set_preset_mode."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    S = _S(mods)
    eco = _eco(mods, hass)
    seen_held = []
    sp = mods["hvac_setpoint"]
    real = sp.emit_set_temperature

    async def _spy(h, e, **kw):
        seen_held.append(eco._held.get(e))
        return await real(h, e, **kw)
    monkeypatch.setattr(sp, "emit_set_temperature", _spy)
    await _tick(coord, hass)
    assert _temp(hass) == [{"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 77.0}]
    assert _presets(hass) == []
    assert seen_held == [("home", 70.0, 77.0)]
    assert eco._held[ENT] == ("home", 70.0, 77.0)
    assert (70.0, 77.0) in [tuple(v) for v in sp.recent_ura_setpoints(ENT)]
    rows = H.climate_write_rows(hass, mods)
    assert [r["site"] for r in rows] == ["S1_reason_ladder"]
    assert eco.last_sent(ENT, "set_preset_mode") == "home"
    _assert_inv_e2(hass)


@pytest.mark.asyncio
async def test_s1_after_echo_reads_home_and_writes_nothing(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    await _tick(coord, hass)
    _set_eco(hass, low=70.0, high=77.0)            # the device echo
    await _tick(coord, hass)
    assert coord.zone_manager.zones[ZONE].preset_mode == "home"
    assert len(_temp(hass)) == 1
    S = _S(mods)
    res = await _eco(mods, hass).hold_preset(hass, ENT, "home", site="S1", zone_id=ZONE, reason="t")
    assert res.status is S.WriteStatus.SKIPPED_ALREADY_CORRECT


@pytest.mark.asyncio
async def test_inv_r_season_rollover_rewrites_the_held_preset(mods, monkeypatch):
    """INV-R: summer home 70/77 held; the season rolls to shoulder (home
    74/70 -> 70/74, widened to the 5 °F min delta -> 70/75): the next S1
    tick writes 70/75 although the zone still reads `home`; then nothing."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    await _tick(coord, hass)
    _set_eco(hass, low=70.0, high=77.0)
    coord._preset_manager._current_season = "shoulder"
    await _tick(coord, hass)
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 75.0}
    _set_eco(hass, low=70.0, high=75.0)
    n = len(_temp(hass))
    await _tick(coord, hass)
    assert len(_temp(hass)) == n
    assert coord.zone_manager.zones[ZONE].preset_mode == "home"


@pytest.mark.asyncio
async def test_inv_r_baseline_edit_rewrites_the_held_preset(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    await _tick(coord, hass)
    _set_eco(hass, low=70.0, high=77.0)
    # The dict the coordinator's own PresetManager reads (robust to reloads).
    hc = sys.modules[type(coord._preset_manager).__module__]
    monkeypatch.setitem(hc.SEASONAL_DEFAULTS["summer"], "home", (78, 71))
    await _tick(coord, hass)
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 71.0, "target_temp_high": 78.0}


@pytest.mark.asyncio
async def test_inv_r_vacancy_away_site_rewrites_a_stale_away_range(mods, monkeypatch):
    """INV-R at the vacancy-bypass site (`Already away` skip): an empty
    zone held at summer Away 60/82; the season rolls to shoulder (Away
    80/62 -> 62/80): S1 writes 62/80 instead of skipping."""
    from datetime import timedelta
    coord, hass = _rig(mods, monkeypatch, low=60.0, high=82.0)
    coord._zone_intelligence_enabled = True
    monkeypatch.setattr(coord, "_zone_conditioning_retreat_ok", lambda z: True)
    z = coord.zone_manager.zones[ZONE]
    z.last_occupied_time = H.utc_now() - timedelta(hours=3)
    _eco(mods, hass)._held[ENT] = ("away", 60.0, 82.0)
    coord.zone_manager.update_zone_climate_state(ZONE)
    assert z.preset_mode == "away"
    coord._preset_manager._current_season = "shoulder"
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert _temp(hass) and _temp(hass)[-1] == {
        "entity_id": ENT, "target_temp_low": 62.0, "target_temp_high": 80.0}


@pytest.mark.asyncio
async def test_set_preset_range_while_holding_p_writes_now_then_s1_noops(mods, monkeypatch):
    """Review #1 HIGH: S10 `set_preset_range(home, 69, 78)` while the zone
    holds home -> APPLIED, one write, held = (home, 69, 78); next S1 no-op."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    await _tick(coord, hass)
    _set_eco(hass, low=70.0, high=77.0)
    S = _S(mods)
    eco = _eco(mods, hass)
    res = await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE,
                                     site="S10_preset_range", reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.APPLIED, "emitted")
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 69.0, "target_temp_high": 78.0}
    assert eco._held[ENT] == ("home", 69.0, 78.0)
    _set_eco(hass, low=69.0, high=78.0)
    n = len(_temp(hass))
    await _tick(coord, hass)
    assert len(_temp(hass)) == n
    res2 = await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE,
                                      site="S10_preset_range", reason="r")
    assert (res2.status, res2.reason) == (S.WriteStatus.SKIPPED_ALREADY_CORRECT, "range_already_live")


@pytest.mark.asyncio
async def test_set_preset_range_for_another_preset_is_stored_for_the_next_hold(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, house="sleep", low=68.0, high=72.0)
    await _tick(coord, hass)                       # holds sleep 70/76
    _set_eco(hass, low=70.0, high=76.0)
    S = _S(mods)
    eco = _eco(mods, hass)
    n = len(hass.services.calls)
    res = await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE,
                                     site="S10_preset_range", reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.SKIPPED_ALREADY_CORRECT, "stored_for_next_hold")
    assert len(hass.services.calls) == n
    coord._house_state = "home_day"
    await _tick(coord, hass)
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 69.0, "target_temp_high": 78.0}


@pytest.mark.asyncio
async def test_set_preset_range_mode_off_defers_but_keeps_the_range(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    await _tick(coord, hass)
    _set_eco(hass, mode="off")
    S = _S(mods)
    eco = _eco(mods, hass)
    n = len(hass.services.calls)
    res = await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE,
                                     site="S10_preset_range", reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.DEFERRED, "mode_not_heat_cool")
    assert len(hass.services.calls) == n
    assert eco._ranges[(ENT, "home", "summer")] == (69.0, 78.0)


@pytest.mark.asyncio
async def test_set_preset_range_with_the_baseline_deletes_the_entry(mods, monkeypatch):
    """§4.9 CPR OFF: the ecobee original is the Seasonal Baseline; handing
    it back deletes the stored range, and the next hold writes the baseline."""
    coord, hass = _rig(mods, monkeypatch, house="sleep", low=68.0, high=72.0)
    await _tick(coord, hass)
    _set_eco(hass, low=70.0, high=76.0)
    eco = _eco(mods, hass)
    await eco.set_preset_range(hass, ENT, "home", 69.0, 78.0, zone_id=ZONE, site="s", reason="r")
    assert eco._ranges
    assert eco.preset_range_original(hass, ENT, "home") == (70, 77)
    await eco.set_preset_range(hass, ENT, "home", 70.0, 77.0, zone_id=ZONE, site="s", reason="r")
    assert eco._ranges == {}
    coord._house_state = "home_day"
    await _tick(coord, hass)
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 77.0}


@pytest.mark.asyncio
async def test_s10_restore_pass_on_ecobee_returns_the_baseline(mods, monkeypatch):
    """Batch C x P2 (§4.9): CPR ON stores 69/78 for home (zone holds home ->
    written now); switch OFF -> the restore pass hands the baseline back,
    the stored entry is deleted and the live range returns to 70/77."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    coord._zone_state_store = H.FakeStore()
    cm = next(e for e in hass.config_entries.async_entries() if "zones" not in (e.options or {}))
    cm.options = {**(cm.options or {}), "hvac_s10_rollout_zone_ids": [ZONE]}
    await _tick(coord, hass)
    _set_eco(hass, low=70.0, high=77.0)
    coord.zone_manager.update_zone_climate_state(ZONE)
    eco = _eco(mods, hass)
    coord._zones_written_this_cycle.clear()     # next tick (S1 wrote this one)
    coord.set_custom_ranges_enabled(True, source="user")
    monkeypatch.setattr(coord, "_s10_desired",
                        lambda z, p, e, o: ((69.0, 78.0), "preset_range_dpm"))
    await coord._async_apply_preset_overrides()
    await H.drain(hass)
    assert _temp(hass)[-1]["target_temp_high"] == 78.0
    assert coord._s10_snapshots[ZONE]["home"] == {
        "low": 70.0, "high": 77.0, "captured_iso": coord._s10_snapshots[ZONE]["home"]["captured_iso"]}
    _set_eco(hass, low=69.0, high=78.0)
    coord.set_custom_ranges_enabled(False, source="user")
    await coord._async_apply_preset_overrides()
    await H.drain(hass)
    assert eco._ranges == {}
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 77.0}
    _assert_inv_e2(hass)


@pytest.mark.asyncio
async def test_persistence_round_trip_and_carrier_snapshot_has_no_key(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    S = _S(mods)
    snap0 = coord._build_zone_state_snapshot()
    assert "__w1c_adapter" not in snap0           # nothing held yet
    await _tick(coord, hass)
    eco = _eco(mods, hass)
    eco._ranges[(ENT, "sleep", "summer")] = (69.0, 75.0)
    blob = coord._build_zone_state_snapshot()["__w1c_adapter"]
    assert blob == {ENT: {"held": ["home", 70.0, 77.0], "ranges": [["sleep", "summer", 69.0, 75.0]]}}
    S._test_reset_cache()
    coord._rehydrate_w1c_adapter({"__w1c_adapter": json.loads(json.dumps(blob))})
    eco2 = _eco(mods, hass)
    assert eco2 is not eco
    assert eco2._held[ENT] == ("home", 70.0, 77.0)
    assert eco2._ranges == {(ENT, "sleep", "summer"): (69.0, 75.0)}


@pytest.mark.asyncio
async def test_carrier_only_install_snapshot_has_no_adapter_key(mods, monkeypatch):
    coord, hass = H.make_coord(mods)
    _install_registry(monkeypatch, mods, entries={
        f"climate.test_zone_{i}": _entry(f"climate.test_zone_{i}", "ha_carrier") for i in (1, 2, 3)
    }, devices={})
    coord._house_state = "home_day"
    coord._zone_intelligence_enabled = False
    for z in coord.zone_manager.zones.values():
        z.preset_mode = "manual"
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert H.preset_writes(hass, ENT)
    assert "__w1c_adapter" not in coord._build_zone_state_snapshot()


def test_rehydrate_keeps_a_slice_pending_until_the_entity_resolves_to_ecobee(mods, monkeypatch):
    """RR3-2: at boot the registry misses the entity -> the slice stays
    pending (re-exported verbatim, never erased by a save) and is handed
    over on the first ecobee resolution."""
    _install_registry(monkeypatch, mods, entries={}, devices={})
    S = _S(mods)
    sl = {"held": ["sleep", 70.0, 76.0], "ranges": []}
    S.rehydrate_adapter_state(None, {ENT: sl})
    assert S.export_adapter_state() == {ENT: sl}
    _install_registry(monkeypatch, mods)
    S._PENDING_ADAPTER_STATE[ENT] = sl          # reset_cache cleared it; re-seed
    eco = S.strategy_for(None, ENT)
    assert eco._held[ENT] == ("sleep", 70.0, 76.0)
    assert ENT not in S._PENDING_ADAPTER_STATE


def test_rehydrate_drops_another_seasons_ranges(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    S._test_reset_cache()
    coord._rehydrate_w1c_adapter({"__w1c_adapter": {ENT: {"held": None, "ranges": [
        ["home", "summer", 69.0, 78.0], ["home", "winter", 66.0, 74.0]]}}})
    assert _eco(mods, hass)._ranges == {(ENT, "home", "summer"): (69.0, 78.0)}


def test_prune_at_the_latch_seam_drops_unmapped_entities(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("home", 70.0, 77.0)
    eco._held["climate.swapped_out"] = ("home", 70.0, 77.0)
    coord._zone_state_store = H.FakeStore()
    coord._prune_interrupt_latch()
    assert "climate.swapped_out" not in eco._held and ENT in eco._held


@pytest.mark.asyncio
async def test_async_setup_rehydrates_the_adapter_before_the_first_cycle(mods, monkeypatch):
    """Wire-in anchor for `_rehydrate_w1c_adapter` in `async_setup`: the
    held range is back before the first decision cycle runs."""
    from runtime_harness import (
        StubBus, StubHass, make_coordinator_manager_entry, make_zone_manager_entry,
    )
    orig_listen = StubBus.async_listen
    monkeypatch.setattr(StubBus, "async_listen",
                        lambda self, et, li, *a, **k: orig_listen(self, et, li))
    zm = make_zone_manager_entry(zones={
        "Test Zone": {"zone_thermostat": ENT, "zone_rooms": []},
    })
    hass = StubHass(config_entries=[make_coordinator_manager_entry(), zm])
    _install_registry(monkeypatch, mods)
    coord = mods["hvac"].HVACCoordinator(hass)
    coord._zone_state_store = H.FakeStore({"__w1c_adapter": {
        ENT: {"held": ["home", 70.0, 77.0], "ranges": []}}})
    hass.data.setdefault(mods["const"].DOMAIN, {})
    seen = []

    async def _first_cycle(*_a, **_k):
        seen.append(_S(mods).strategy_for(hass, ENT)._held.get(ENT))
    monkeypatch.setattr(coord, "_async_decision_cycle", _first_cycle)
    await coord.async_setup()
    await coord.async_teardown()
    assert seen and seen[0] == ("home", 70.0, 77.0)


@pytest.mark.asyncio
async def test_set_setpoints_rounds_widens_and_leaves_held(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("home", 70.0, 77.0)
    res = await eco.set_setpoints(hass, ENT, target_temp_low=70.0, target_temp_high=78.5,
                                  site="S5", zone_id=ZONE, reason="nudge")
    assert res.status is S.WriteStatus.APPLIED
    assert _temp(hass) == [{"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 79.0}]
    assert eco._held[ENT] == ("home", 70.0, 77.0)
    res = await eco.set_setpoints(hass, ENT, target_temp_low=72.0, target_temp_high=74.0,
                                  site="S3", zone_id=ZONE, reason="compromise")
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 72.0, "target_temp_high": 77.0}


@pytest.mark.parametrize("low,high", [(None, 77.0), (70.0, None), (None, None)])
@pytest.mark.asyncio
async def test_set_setpoints_one_leg_defers_with_zero_calls(mods, monkeypatch, low, high):
    """PR2-3: a one-leg call is the `temperature=None` hazard."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    res = await _eco(mods, hass).set_setpoints(
        hass, ENT, target_temp_low=low, target_temp_high=high,
        site="S5", zone_id=ZONE, reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.DEFERRED, "setpoint_leg_missing")
    assert hass.services.calls == []


@pytest.mark.parametrize("mode", ["off", "cool", "heat"])
@pytest.mark.parametrize("verb", ["hold_preset", "pin_preset", "set_setpoints"])
@pytest.mark.asyncio
async def test_range_verbs_defer_outside_heat_cool_with_zero_calls(mods, monkeypatch, mode, verb):
    """INV-E2 / §4.2 mechanism (i): never a range unless the LIVE mode is
    heat_cool. Under (i) an arrester revert whose B4 mode write has not
    landed yet DEFERs its pin; the next S1 tick repairs it (next test)."""
    coord, hass = _rig(mods, monkeypatch, mode=mode)
    S = _S(mods)
    eco = _eco(mods, hass)
    kw = dict(site="S", zone_id=ZONE, reason="r")
    if verb == "set_setpoints":
        res = await eco.set_setpoints(hass, ENT, target_temp_low=70.0, target_temp_high=77.0, **kw)
    else:
        res = await getattr(eco, verb)(hass, ENT, "home", **kw)
    assert (res.status, res.reason) == (S.WriteStatus.DEFERRED, "mode_not_heat_cool")
    assert hass.services.calls == []
    assert ENT not in eco._held


@pytest.mark.asyncio
async def test_s4_pin_deferred_in_cool_is_repaired_by_the_next_s1_tick(mods, monkeypatch):
    """PR2-5 (mechanism i, stated): the pin deferred while the mode write had
    not landed; once the device reads heat_cool (HomeKit fills both legs
    with the old single setpoint, 76/76) the zone reads its held preset name
    but the range is wrong -> S1 holds it again."""
    coord, hass = _rig(mods, monkeypatch, mode="cool")
    eco = _eco(mods, hass)
    res = await eco.pin_preset(hass, ENT, "home", site="S4", zone_id=ZONE, reason="revert")
    assert res.status is _S(mods).WriteStatus.DEFERRED
    eco._held[ENT] = ("home", 70.0, 77.0)          # what URA last held
    _set_eco(hass, low=76.0, high=76.0)
    coord.zone_manager.zones[ZONE].hvac_mode = "heat_cool"
    await _tick(coord, hass)
    assert _temp(hass) == [{"entity_id": ENT, "target_temp_low": 70.0, "target_temp_high": 77.0}]


@pytest.mark.asyncio
async def test_pin_preset_writes_the_effective_range_never_a_preset(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=72.0, high=68.0)
    S = _S(mods)
    eco = _eco(mods, hass)
    for preset, rng in (("sleep", (70.0, 76.0)), ("away", (60.0, 82.0)), ("home", (70.0, 77.0))):
        res = await eco.pin_preset(hass, ENT, preset, emit=object(), blocking=True,
                                   site="S7", zone_id=ZONE, reason="restore")
        assert res.status is S.WriteStatus.APPLIED
        assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": rng[0], "target_temp_high": rng[1]}
        assert eco._held[ENT] == (preset,) + rng
    assert eco.last_sent(ENT, "set_preset_mode") is None
    _assert_inv_e2(hass)


@pytest.mark.asyncio
async def test_pin_preset_wire_exception_propagates_and_restores_held(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("sleep", 70.0, 76.0)

    async def _boom(*a, **k):
        raise RuntimeError("wire")
    monkeypatch.setattr(hass.services, "async_call", _boom)
    with pytest.raises(RuntimeError, match="wire"):
        await eco.pin_preset(hass, ENT, "home", site="S7", zone_id=ZONE, reason="r")
    assert eco._held[ENT] == ("sleep", 70.0, 76.0)


@pytest.mark.asyncio
async def test_gate_deferred_hold_restores_held(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("sleep", 70.0, 76.0)
    res = await eco.hold_preset(hass, ENT, "home", gate=lambda: True,
                                site="S1", zone_id=ZONE, reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.DEFERRED, "gate_deferred")
    assert eco._held[ENT] == ("sleep", 70.0, 76.0)
    assert _temp(hass) == []


@pytest.mark.asyncio
async def test_no_range_for_preset_fails_with_zero_calls(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    res = await _eco(mods, hass).hold_preset(hass, ENT, "wake", site="S1", zone_id=ZONE, reason="r")
    assert (res.status, res.reason) == (S.WriteStatus.FAILED, "no_range_for_preset")
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_zone_last_write_is_away_after_an_applied_away_hold(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    res = await _eco(mods, hass).hold_preset(hass, ENT, "away", site="S1", zone_id=ZONE, reason="r")
    assert res.status is _S(mods).WriteStatus.APPLIED
    coord._zone_last_s1_write.pop(ZONE, None)
    assert coord._zone_last_write_is_away(coord.zone_manager.zones[ZONE]) is True


# ---- min delta (operator on-site ruling) ----------------------------------


@pytest.mark.parametrize("delta,low,high,expect", [
    (5.0, 70, 72, (70, 75)),      # winter home default widened
    (5.0, 70, 75, (70, 75)),      # exactly the gap: unchanged
    (5.0, 70, 76, (70, 76)),
    (2.0, 70, 72, (70, 72)),      # an operator-set 2 °F unit
    (3.0, 69.5, 71.4, (70, 73)),  # round half up, then widen
    (5.0, 70.4, 70.6, (70, 75)),  # rounds to 70/71 -> widened
])
def test_wire_range_rounds_half_up_then_widens_to_the_configured_min_delta(
    mods, monkeypatch, delta, low, high, expect,
):
    coord, hass = _rig(mods, monkeypatch)
    coord.zone_manager.zones[ZONE].thermostat_min_delta_f = delta
    assert _S(mods).EcobeeHomeKitStrategy.wire_range(low, high, entity_id=ENT) == expect


def test_min_delta_comes_from_the_zone_config_field(mods, monkeypatch):
    hz = mods["hvac_zones"]
    assert hz._min_delta_from({}) == 5.0
    assert hz._min_delta_from({"hvac_thermostat_min_delta_f": 3}) == 3.0
    assert hz._min_delta_from({"hvac_thermostat_min_delta_f": "junk"}) == 5.0
    assert hz._min_delta_from({"hvac_thermostat_min_delta_f": 0}) == 5.0


@pytest.mark.asyncio
async def test_zone_discovery_reads_the_min_delta_and_shared_thermostats_take_the_wider(mods):
    """The rung-2 Zone -> Thermostat field reaches the ZoneState through the
    REAL discovery: a solo zone keeps its own value, two house zones sharing
    one thermostat take the wider gap, an unset zone gets the 5 °F default."""
    from runtime_harness import StubHass, make_coordinator_manager_entry, make_zone_manager_entry
    zm = make_zone_manager_entry(zones={
        "Upstairs": {"zone_thermostat": "climate.eco_up", "zone_rooms": [],
                     "hvac_thermostat_min_delta_f": 3.0},
        "Master A": {"zone_thermostat": "climate.eco_ms", "zone_rooms": [],
                     "hvac_thermostat_min_delta_f": 4.0},
        "Master B": {"zone_thermostat": "climate.eco_ms", "zone_rooms": [],
                     "hvac_thermostat_min_delta_f": 6.0},
        "Down": {"zone_thermostat": "climate.eco_dn", "zone_rooms": []},
    })
    hass = StubHass(config_entries=[make_coordinator_manager_entry(), zm])
    zmgr = mods["hvac_zones"].ZoneManager(hass)
    await zmgr.async_discover_zones()
    by_ent = {z.climate_entity: z.thermostat_min_delta_f for z in zmgr.zones.values()}
    assert by_ent == {"climate.eco_up": 3.0, "climate.eco_ms": 6.0, "climate.eco_dn": 5.0}


# ---- §4.11 deferral reporting ---------------------------------------------


@pytest.mark.asyncio
async def test_mode_off_deferral_is_reported_once_per_episode(mods, monkeypatch, caplog):
    coord, hass = _rig(mods, monkeypatch, mode="off")
    monkeypatch.setattr(coord._override_arrester, "_supports_heat_cool", lambda e: False)
    caplog.set_level(logging.INFO)
    for _ in range(3):
        await _tick(coord, hass)
    rows = [r for r in _ledger(hass, mods, "preset_change_deferred") if r["zone"] == ZONE]
    assert len(rows) == 1
    assert rows[0]["details"]["reason"] == "strategy_deferred:mode_not_heat_cool"
    assert sum("cannot take preset" in m for m in caplog.messages) == 1
    assert _temp(hass) == []
    # An APPLIED tick closes the episode; a later deferral opens a new one.
    _set_eco(hass, low=68.0, high=72.0)
    coord.zone_manager.zones[ZONE].hvac_mode = "heat_cool"
    await _tick(coord, hass)
    assert len(_temp(hass)) == 1
    assert ZONE not in coord._s1_strategy_episode
    _set_eco(hass, mode="off")
    await _tick(coord, hass)
    rows = [r for r in _ledger(hass, mods, "preset_change_deferred") if r["zone"] == ZONE]
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_no_heat_cool_mode_fails_with_one_repair_cleared_when_it_appears(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    from homeassistant.helpers import issue_registry as ir
    created, deleted = [], []
    monkeypatch.setattr(ir, "async_create_issue", lambda *a, **k: created.append((a, k)))
    monkeypatch.setattr(ir, "async_delete_issue", lambda *a, **k: deleted.append(a))
    _set_eco(hass, low=68.0, high=72.0, modes=("off", "heat", "cool"))
    for _ in range(2):
        await _tick(coord, hass)
    assert _temp(hass) == []
    assert len(created) == 1 and created[0][1]["translation_key"] == "thermostat_no_heat_cool"
    rows = [r for r in _ledger(hass, mods, "preset_change_deferred") if r["zone"] == ZONE]
    assert [r["details"]["reason"] for r in rows] == ["strategy_failed:no_heat_cool_mode"]
    _set_eco(hass, low=68.0, high=72.0)
    await _tick(coord, hass)
    assert len(deleted) == 1 and len(_temp(hass)) == 1


@pytest.mark.parametrize("mode,repair", [("cool", True), ("off", False)])
@pytest.mark.asyncio
async def test_heat_cool_never_reached_escalates_after_three_ticks(mods, monkeypatch, mode, repair):
    coord, hass = _rig(mods, monkeypatch, mode=mode, low=None, high=None)
    from homeassistant.helpers import issue_registry as ir
    created = []
    monkeypatch.setattr(ir, "async_create_issue", lambda *a, **k: created.append(k))
    monkeypatch.setattr(ir, "async_delete_issue", lambda *a, **k: None)
    for _ in range(3):
        await _tick(coord, hass)
    reasons = [r["details"]["reason"] for r in _ledger(hass, mods, "preset_change_deferred")
               if r["zone"] == ZONE]
    if repair:
        assert reasons == ["strategy_deferred:mode_not_heat_cool",
                           "strategy_failed:heat_cool_not_reached"]
        assert [k["translation_key"] for k in created] == ["thermostat_heat_cool_not_reached"]
    else:
        assert reasons == ["strategy_deferred:mode_not_heat_cool"]
        assert created == []
    assert _temp(hass) == []


# ==========================================================================
# D3 — projection + classifier + tolerance (R1–R16, T1–T2)
# ==========================================================================


def _st(mode, low, high, ent=ENT):
    return types.SimpleNamespace(entity_id=ent, state=mode, attributes={
        "target_temp_low": low, "target_temp_high": high,
        "hvac_modes": ["off", "heat", "cool", "heat_cool"]})


@pytest.mark.parametrize("held,mode,low,high,expect", [
    (("home", 70.0, 77.0), "heat_cool", 70.0, 77.0, "home"),
    (("home", 70.0, 77.0), "heat_cool", 70.5, 77.5, "home"),     # tolerance edge (inclusive)
    (("home", 70.0, 77.0), "heat_cool", 70.0, 77.6, "manual"),   # past the edge
    (("home", 70.0, 77.0), "heat_cool", 70.0, 76.0, "manual"),   # PR2-4: not `sleep`
    (("home", 70.0, 77.0), "cool", None, None, "home"),          # mode drift keeps the name
    (None, "heat_cool", 70.0, 76.0, "sleep"),                     # restart fallback, unique
    (None, "heat_cool", 60.0, 82.0, "away"),
    (None, "heat_cool", 68.0, 72.0, "manual"),
    (None, "cool", None, None, ""),
    (("home", 70.0, 77.0), "unavailable", None, None, "<default>"),
    (None, "unknown", None, None, "<default>"),
])
def test_preset_of_table(mods, monkeypatch, held, mode, low, high, expect):
    coord, hass = _rig(mods, monkeypatch)
    eco = _eco(mods, hass)
    if held:
        eco._held[ENT] = held
    got = eco.preset_of(_st(mode, low, high), "<default>", hass=hass)
    assert got == expect


def test_preset_of_restart_fallback_rejects_two_near_candidates(mods, monkeypatch):
    """Two candidate ranges both within tolerance -> no match (manual)."""
    coord, hass = _rig(mods, monkeypatch)
    # The dict the coordinator's own PresetManager reads (robust to reloads).
    hc = sys.modules[type(coord._preset_manager).__module__]
    monkeypatch.setitem(hc.SEASONAL_DEFAULTS["summer"], "sleep", (77, 70))   # == home
    assert _eco(mods, hass).preset_of(_st("heat_cool", 70.0, 77.0), "", hass=hass) == "manual"


@pytest.mark.parametrize("sel_state,expect", [
    ("home", "home"), ("sleep", "sleep"), ("away", "away"),
    ("unknown", ""), ("unavailable", ""),
])
def test_current_mode_select_is_a_read_fallback_and_unknown_is_never_away(
    mods, monkeypatch, sel_state, expect,
):
    coord, hass = _rig(mods, monkeypatch)
    hass.states.async_set(SEL, sel_state, {"options": ["home", "sleep", "away"]})
    # Nothing held, mode drifted -> the comfort select (if readable).
    assert _eco(mods, hass).preset_of(_st("cool", None, None), "", hass=hass) == expect
    # In heat_cool an unexplained range is `manual` whatever the select says
    # (a stale select must never hide a person's range from the arrester).
    assert _eco(mods, hass).preset_of(_st("heat_cool", 68.0, 72.0), "", hass=hass) == "manual"


def test_r1_hub_reads_the_projection(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=76.0)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("sleep", 70.0, 76.0)
    coord.zone_manager.update_zone_climate_state(ZONE)
    assert coord.zone_manager.zones[ZONE].preset_mode == "sleep"
    _set_eco(hass, low=69.0, high=76.0)
    coord.zone_manager.update_zone_climate_state(ZONE)
    assert coord.zone_manager.zones[ZONE].preset_mode == "manual"


def _eco_ev(old, new):
    """old/new = (mode, low, high) — HomeKit states carry no preset_mode."""
    from datetime import datetime, timedelta, timezone
    o = _st(*old)
    o.last_updated = datetime.now(timezone.utc) - timedelta(seconds=1)
    n = _st(*new)
    n.last_updated = datetime.now(timezone.utc)
    return types.SimpleNamespace(
        data={"entity_id": ENT, "new_state": n, "old_state": o},
        context=types.SimpleNamespace(user_id=None, parent_id=None, id="ctx"))


@pytest.mark.asyncio
async def test_r7_wall_change_under_home_is_booked_like_carrier(mods, monkeypatch):
    """INV-P: a wall change 70/77 -> 68/72 under home books ONE
    override_detected row on the ecobee, with the same delta / legs a
    Carrier zone books for the same change."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    arr = coord._override_arrester
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    arr._handle_climate_change(_eco_ev(("heat_cool", 70.0, 77.0), ("heat_cool", 68.0, 72.0)))
    await H.drain(hass, rounds=6)
    eco_rows = [r for r in _ledger(hass, mods, "override_detected") if r.get("entity_id") == ENT]
    assert len(eco_rows) == 1
    # Carrier, same change.
    H.set_climate(hass, CAR, preset_mode="home", low=70.0, high=77.0)
    arr._handle_climate_change(H.make_event(
        CAR, old_preset="home", new_preset="manual", old_low=70.0, old_high=77.0,
        new_low=68.0, new_high=72.0))
    await H.drain(hass, rounds=6)
    car_rows = [r for r in _ledger(hass, mods, "override_detected") if r.get("entity_id") == CAR]
    assert len(car_rows) == 1
    keys = ("delta_f", "changed_legs", "gated_reason", "within_manual")
    assert {k: eco_rows[0]["details"].get(k) for k in keys} == {
        k: car_rows[0]["details"].get(k) for k in keys}


@pytest.mark.asyncio
async def test_r7_echo_of_an_s1_hold_landing_during_the_call_is_not_booked(mods, monkeypatch):
    """`held` is stamped BEFORE the wire: an echo delivered while the write
    is still in flight (HomeKit's blocking call returns AFTER the state
    update, D0b G3) reads the new preset, not `manual`."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=76.0)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("sleep", 70.0, 76.0)          # URA held sleep before
    arr = coord._override_arrester
    real_call = hass.services.async_call

    async def _call(domain, service, data=None, blocking=False, **kw):
        await real_call(domain, service, data, blocking, **kw)
        if domain == "climate" and service == "set_temperature" and data["entity_id"] == ENT:
            arr._handle_climate_change(_eco_ev(
                ("heat_cool", 70.0, 76.0),
                ("heat_cool", data["target_temp_low"], data["target_temp_high"])))
    monkeypatch.setattr(hass.services, "async_call", _call)
    await _tick(coord, hass)                          # home_day -> hold home
    assert _temp(hass)[-1]["target_temp_high"] == 77.0
    await H.drain(hass, rounds=6)
    assert _ledger(hass, mods, "override_detected") == []


@pytest.mark.asyncio
async def test_t1_rounded_echo_within_ecobee_tolerance_is_ura_echo(mods, monkeypatch):
    """PR2-8 / T1: the within-manual classifier uses the profile's echo
    tolerance and the PROJECTED presets (R2)."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    S = _S(mods)
    # 74 vs URA's 73.4: 0.6 °F off — URA's echo at the ecobee tolerance
    # (0.6 here), a person at Carrier's 0.5.
    mods["hvac_setpoint"].record_ura_setpoint(ENT, 68.0, 73.4)
    arr = coord._override_arrester
    monkeypatch.setattr(S, "ECOBEE_RANGE_TOLERANCE_F", 0.6)
    arr._handle_climate_change(_eco_ev(("heat_cool", 68.0, 72.0), ("heat_cool", 68.0, 74.0)))
    await H.drain(hass, rounds=6)
    assert _ledger(hass, mods, "override_detected") == []


@pytest.mark.asyncio
async def test_t1_within_manual_person_change_on_ecobee_is_booked(mods, monkeypatch):
    """R2: both states project to `manual` -> a person's fine-tune is
    booked (a raw read would see None/None and never classify it)."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    arr = coord._override_arrester
    arr._handle_climate_change(_eco_ev(("heat_cool", 68.0, 72.0), ("heat_cool", 68.0, 71.0)))
    await H.drain(hass, rounds=6)
    rows = _ledger(hass, mods, "override_detected")
    assert len(rows) == 1 and rows[0]["details"]["within_manual"] is True


@pytest.mark.parametrize("tol,expected", [(0.5, True), (0.6, False)])
def test_t2_transition_tolerance_comes_from_the_profile(mods, monkeypatch, tol, expected):
    """T2: `_transition_is_human` gets the profile's tolerance; an echo
    0.6 °F off a recent write is a person at 0.5 and URA's echo at 0.6."""
    coord, hass = _rig(mods, monkeypatch)
    S = _S(mods)
    monkeypatch.setattr(S, "ECOBEE_RANGE_TOLERANCE_F", tol)
    tol_used = _eco(mods, hass).echo_tolerance_f()
    arr = coord._override_arrester
    got = arr._transition_is_human(
        _st("heat_cool", 70.0, 77.0), _st("heat_cool", 70.0, 78.6), ["high"],
        [(70.0, 78.0)], tol_used)
    assert got is expected


@pytest.mark.asyncio
async def test_t2_wired_into_the_arrester(mods, monkeypatch):
    """Call-site anchor for T2: the `_tol` the arrester hands
    `_transition_is_human` is the profile's, not the module constant."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    monkeypatch.setattr(S, "ECOBEE_RANGE_TOLERANCE_F", 0.9)
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    arr = coord._override_arrester
    seen = []
    real = arr._transition_is_human
    monkeypatch.setattr(arr, "_transition_is_human",
                        lambda o, n, legs, rec, tol: seen.append(tol) or real(o, n, legs, rec, tol))
    arr._handle_climate_change(_eco_ev(("heat_cool", 70.0, 77.0), ("heat_cool", 68.0, 72.0)))
    await H.drain(hass, rounds=6)
    assert seen == [0.9]


def test_r3_latch_discharges_on_a_held_named_range(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    arr = coord._override_arrester
    assert arr._latch_state_discharges(hass.states.get(ENT)) is True
    _set_eco(hass, low=68.0, high=72.0)
    assert arr._latch_state_discharges(hass.states.get(ENT)) is False


@pytest.mark.parametrize("low,high,reverts", [
    (68.0, 72.0, True),     # a person's range under a held home -> stale manual
    (70.0, 77.0, False),    # URA's own held home range -> nothing to audit
])
@pytest.mark.asyncio
async def test_r4_startup_audit_reads_the_projection(mods, monkeypatch, low, high, reverts):
    """R4 through the REAL `async_startup_audit` (after the §4.2a rehydrate):
    a person's range reads `manual` and is scheduled for revert; URA's own
    held range reads `home` and is left alone. A raw read sees None and
    never audits an ecobee at all."""
    coord, hass = _rig(mods, monkeypatch, low=low, high=high)
    arr = coord._override_arrester
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    await arr.async_startup_audit(coord._preset_manager, "home_day")
    await H.drain(hass)
    assert bool(arr._override_active.get(ZONE)) is reverts
    assert (ZONE in arr._grace_timers) is reverts


def test_r5_mid_window_person_transition_passes_through(mods, monkeypatch):
    """R5: inside a PRESET-kind suppression window only a fresh transition
    INTO manual is genuine. On an ecobee that transition exists only in the
    projection (raw reads are None -> None)."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    arr = coord._override_arrester
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    arr.suppress(ENT, kind="preset")
    ev = _eco_ev(("heat_cool", 70.0, 77.0), ("heat_cool", 68.0, 72.0))
    assert arr._is_genuine_manual(ev, ENT) is True
    arr.suppress(ENT, kind="preset")
    echo = _eco_ev(("heat_cool", 68.0, 72.0), ("heat_cool", 70.0, 77.0))
    assert arr._is_genuine_manual(echo, ENT) is False


@pytest.mark.asyncio
async def test_r6_episode_boundary_clears_the_last_detection(mods, monkeypatch):
    """R6: leaving `manual` (a person range -> URA's held range) ends the
    manual episode — the last-detection record is dropped."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    arr = coord._override_arrester
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    arr._last_detection[ENT] = {"booked": True}
    arr.suppress(ENT)     # URA's own write: the rest of the handler stands down
    arr._handle_climate_change(_eco_ev(("heat_cool", 68.0, 72.0), ("heat_cool", 70.0, 77.0)))
    await H.drain(hass)
    assert ENT not in arr._last_detection


@pytest.mark.asyncio
async def test_r8_ac_reset_restore_target_is_the_projected_preset(mods, monkeypatch):
    """R8 through the REAL `_perform_ac_reset`: the preset the reset's
    restore pins back is the projection (`sleep`), not the raw ''."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=76.0)
    arr = coord._override_arrester
    _eco(mods, hass)._held[ENT] = ("sleep", 70.0, 76.0)
    fired = []
    monkeypatch.setattr(mods["hvac_override"], "async_call_later",
                        lambda h, d, cb: fired.append(cb) or (lambda: None))
    got = []

    async def _restore(zone, mode, preset):
        got.append(preset)
    monkeypatch.setattr(arr, "_restore_after_reset", _restore)
    z = coord.zone_manager.zones[ZONE]
    await arr._perform_ac_reset(z)
    await H.drain(hass)
    for cb in fired:
        cb(None)
    await H.drain(hass)
    assert got == ["sleep"]


@pytest.mark.asyncio
async def test_r10_nudge_start_snapshot_is_the_projected_preset(mods, monkeypatch):
    """R10 through the REAL `_perform_soft_nudge`: the snapshot the nudge
    restore pins back is `sleep` (raw read: '' -> no preset restore)."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=76.0)
    arr = coord._override_arrester
    _eco(mods, hass)._held[ENT] = ("sleep", 70.0, 76.0)
    monkeypatch.setattr(mods["hvac_override"], "async_call_later",
                        lambda h, d, cb: (lambda: None))
    z = coord.zone_manager.zones[ZONE]
    z.target_temp_low, z.target_temp_high = 70.0, 76.0
    await arr._perform_soft_nudge(z, 2.5)
    await H.drain(hass)
    assert arr._nudge_pre_preset.get(ZONE) == "sleep"
    assert _temp(hass)[-1]["target_temp_high"] > 76.0
    _assert_inv_e2(hass)


@pytest.mark.asyncio
async def test_r15_begin_excursion_snapshots_the_projected_preset(mods, monkeypatch):
    """R15 drives C26 / `is_human_manual_snapshot`: a held home range
    snapshots `home` (a named return), not None (a raw restore)."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    ex = mods["hvac_excursion"]
    tok = await ex.begin_excursion(hass, zone_id=ZONE, entity_id=ENT,
                                   kind=ex.EXCURSION_KIND.NUDGE, excursion_high=78.5,
                                   duration_s=120, site="S5")
    assert tok is not None and tok.pre_preset == "home"
    assert _eco(mods, hass).is_human_manual_snapshot(tok.pre_preset) is False


def test_pr2_6_ecobee_snapshot_rule_is_carriers(mods):
    eco = _S(mods).EcobeeHomeKitStrategy()
    assert eco.is_human_manual_snapshot("home", preset_modes=()) is False
    for v in ("manual", "", None):
        assert eco.is_human_manual_snapshot(v, preset_modes=()) is True


def test_r16_compliance_actual_is_the_projection(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (
        ComplianceTracker,
    )
    ct = ComplianceTracker(hass)
    actual = ct._extract_state(hass.states.get(ENT), "climate")
    assert actual["preset_mode"] == "home"
    ok, _ = ct._compare_states({"preset_mode": "home"}, actual, "climate")
    assert ok is True


@pytest.mark.asyncio
async def test_r14_egress_pause_saves_the_projected_preset(mods, monkeypatch):
    """R14 through the REAL `EgressManager._engage_pause`: the saved preset
    (what the resume pins back) is the projection, not the raw None."""
    from datetime import datetime, timezone
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    _eco(mods, hass)._held[ENT] = ("home", 70.0, 77.0)
    eg = coord._egress_manager
    # The egress module memoises the excursion module on first use; scope it
    # to THIS harness's module and restore the memo afterwards (a memo left
    # pointing at this test's module object would leak into later files).
    monkeypatch.setattr(mods["hvac_egress"], "_EX_MOD_CACHE", mods["hvac_excursion"])

    async def _noop(*a, **k):
        return None
    for name in ("_db_save", "_db_clear"):
        if hasattr(eg, name):
            monkeypatch.setattr(eg, name, _noop)
    await eg._engage_pause(zone_id=ZONE, zone_state=coord.zone_manager.zones[ZONE],
                           triggered_room="Hall", now=datetime.now(timezone.utc))
    await H.drain(hass)
    assert eg._paused_by_egress[ZONE]["preset"] == "home"


# ==========================================================================
# D4 / INV-F — scaffold removal + lints
# ==========================================================================

_SCOPE = sorted(DC.glob("hvac*.py")) + [DC / "coordinator_diagnostics.py",
                                        URA / "sensor.py", URA / "binary_sensor.py"]

# Raw thermostat `preset_mode` reads allowed outside hvac_strategy.py:
# (file, enclosing function) -> reason.
RAW_PRESET_READ_ALLOWLIST = {
    ("hvac_setpoint.py", "_snapshot_climate_state"):
        "W1-A ledger `values_before` stays RAW on purpose (plan §5 excluded)",
    ("hvac_fans.py", "snapshot_room_fan"): "fan entity, not a thermostat",
    ("hvac_fans.py", "_restore_after_recheck_body"): "fan entity, not a thermostat",
    ("hvac_override.py", "classify_manual_setpoint_change"):
        "Carrier default branch; the live caller threads `preset_of` (R2)",
    ("coordinator_diagnostics.py", "_compare_states"):
        "compares the commanded dict vs the already-projected `actual` (R16)",
}


def _raw_preset_reads(files):
    out = []
    for f in files:
        if f.name == "hvac_strategy.py":
            continue
        src = f.read_text()
        tree = ast.parse(src)
        parents = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parents[c] = n
        for n in ast.walk(tree):
            hit = (
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and n.args
                and isinstance(n.args[0], ast.Constant) and n.args[0].value == "preset_mode"
            ) or (
                isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and n.slice.value == "preset_mode" and isinstance(n.ctx, ast.Load)
            )
            if not hit:
                continue
            p = n
            while p in parents and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                p = parents[p]
            out.append((f.name, getattr(p, "name", "<module>"), n.lineno))
    return out


def test_no_raw_thermostat_preset_read_outside_strategy():
    bad = [f"{f}:{ln} in {fn}" for f, fn, ln in _raw_preset_reads(_SCOPE)
           if (f, fn) not in RAW_PRESET_READ_ALLOWLIST]
    assert not bad, "raw preset_mode read — route through preset_of_for:\n" + "\n".join(bad)


def test_raw_preset_allowlist_has_no_stale_entries():
    seen = {(f, fn) for f, fn, _ in _raw_preset_reads(_SCOPE)}
    assert not [k for k in RAW_PRESET_READ_ALLOWLIST if k not in seen]


def test_raw_preset_lint_catches_a_planted_read(tmp_path):
    p = tmp_path / "hvac_planted.py"
    p.write_text('def f(st):\n    return st.attributes.get("preset_mode", "")\n')
    assert _raw_preset_reads([p]) == [("hvac_planted.py", "f", 2)]


def test_feature_available_scaffold_is_gone(mods):
    S = _S(mods)
    for cls in (S.GenericStrategy, S.CarrierStrategy, S.EcobeeHomeKitStrategy):
        for name in ("feature_available", "feature_unavailable_reason"):
            assert not hasattr(cls, name), (cls.__name__, name)


def _inv_f_violations(files):
    bad = []
    for f in files:
        if f.name == "hvac_strategy.py":
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Attribute) and n.attr in (
                "capabilities", "feature_available", "feature_unavailable_reason",
            ):
                bad.append(f"{f.name}:{n.lineno} .{n.attr}")
            if isinstance(n, ast.Attribute) and n.attr == "platform":
                bad.append(f"{f.name}:{n.lineno} .platform")
            if isinstance(n, ast.Name) and n.id in (
                "CARRIER_PLATFORM", "HOMEKIT_PLATFORM", "CarrierStrategy",
                "EcobeeHomeKitStrategy", "GenericStrategy",
            ):
                bad.append(f"{f.name}:{n.lineno} {n.id}")
            if isinstance(n, ast.alias) and n.name in (
                "CARRIER_PLATFORM", "HOMEKIT_PLATFORM", "CarrierStrategy",
                "EcobeeHomeKitStrategy",
            ):
                bad.append(f"{f.name}:{n.lineno} import {n.name}")
    return bad


def test_inv_f_no_brand_or_capability_branch_outside_strategy():
    hvac_scope = sorted(DC.glob("hvac*.py")) + [DC / "coordinator_diagnostics.py"]
    assert _inv_f_violations(hvac_scope) == []


@pytest.mark.parametrize("planted", [
    "def f(s):\n    return s.capabilities.hold_via\n",
    "def f(s):\n    return s.platform == 'ha_carrier'\n",
    "from .hvac_strategy import CARRIER_PLATFORM\n",
    "def f(s):\n    return isinstance(s, CarrierStrategy)\n",
])
def test_inv_f_lint_catches_planted_brand_branches(tmp_path, planted):
    p = tmp_path / "hvac_planted.py"
    p.write_text(planted)
    assert _inv_f_violations([p]) != []


# ---- F4 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_w1c_p2_s1_failed_no_error_spam(mods, monkeypatch, caplog):
    """F4: three S1 ticks on a no-presets Generic -> 0 ERROR, 1 INFO, 1 row,
    and the suppress stamp rolled back every tick."""
    coord, hass = H.make_coord(mods)
    _install_registry(monkeypatch, mods, entries={}, devices={})
    coord._house_state = "home_day"
    coord._zone_intelligence_enabled = False
    for other in ("zone_2", "zone_3"):
        coord.zone_manager.zones[other].preset_mode = "home"
    coord.zone_manager.zones[ZONE].preset_mode = "manual"
    H.set_climate(hass, ENT, preset_mode="manual", preset_modes=())
    caplog.set_level(logging.INFO)
    for _ in range(3):
        await coord._apply_house_state_presets()
        await H.drain(hass)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert sum("cannot take preset" in m for m in caplog.messages) == 1
    rows = [r for r in _ledger(hass, mods, "preset_change_deferred") if r["zone"] == ZONE]
    assert [r["details"]["reason"] for r in rows] == ["strategy_failed:no_presets_supported"]
    assert ENT not in coord._override_arrester._suppressed_until
    assert H.preset_writes(hass, ENT) == []


@pytest.mark.asyncio
async def test_carrier_emit_raised_still_takes_the_runtime_error_path(mods, monkeypatch, caplog):
    coord, hass = H.make_coord(mods)
    _install_registry(monkeypatch, mods, entries={
        ENT: _entry(ENT, "ha_carrier")}, devices={})
    coord._house_state = "home_day"
    coord._zone_intelligence_enabled = False
    for other in ("zone_2", "zone_3"):
        coord.zone_manager.zones[other].preset_mode = "home"
    coord.zone_manager.zones[ZONE].preset_mode = "manual"
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")

    async def _boom(*a, **k):
        raise RuntimeError("cloud down")
    monkeypatch.setattr(hass.services, "async_call", _boom)
    caplog.set_level(logging.INFO)
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert any("S1 strategy write failed: emit_raised" in r.getMessage()
               for r in caplog.records if r.levelno >= logging.ERROR)
    assert _ledger(hass, mods, "preset_change_deferred") == []


# ==========================================================================
# D6 — freshness / reload are adapter verbs
# ==========================================================================


def _stale_state(eid, mode="heat_cool", age_s=3600):
    from datetime import datetime, timedelta, timezone
    return types.SimpleNamespace(
        entity_id=eid, state=mode,
        attributes={"hvac_action": "idle", "target_temp_low": 70.0, "target_temp_high": 77.0},
        last_reported=datetime.now(timezone.utc) - timedelta(seconds=age_s),
        last_updated=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    )


def _freshness_rig(mods, monkeypatch):
    coord, hass = _rig(mods, monkeypatch)
    reloads, notes = [], []

    async def _reload(zones):
        reloads.append(list(zones))

    async def _note(**kw):
        notes.append(kw)
    monkeypatch.setattr(coord, "_reload_ha_carrier_entry", _reload)
    monkeypatch.setattr(coord, "_nm_carrier_reload_note", _note)
    monkeypatch.setattr(coord, "_carrier_require_blind_corroboration", lambda: False)
    monkeypatch.setattr(coord, "_carrier_in_flight_ops_pending", lambda: None)
    for zid in ("zone_2", "zone_3"):
        coord.zone_manager.zones[zid].climate_entity = ""   # only z1 (+ z2 below)
    return coord, hass, reloads, notes


@pytest.mark.asyncio
async def test_ecobee_stale_entity_is_not_applicable(mods, monkeypatch):
    coord, hass, reloads, notes = _freshness_rig(mods, monkeypatch)
    real_get = hass.states.get
    monkeypatch.setattr(hass.states, "get",
                        lambda e: _stale_state(e) if e == ENT else real_get(e))
    await coord._check_carrier_freshness()
    row = coord._carrier_freshness_snapshot[ZONE]
    assert row["freshness"] == "not_applicable" and row["stale"] is False
    assert coord._carrier_stale_zone_count == 0
    assert reloads == [] and notes == []


@pytest.mark.asyncio
async def test_mixed_install_only_the_carrier_zone_qualifies(mods, monkeypatch):
    coord, hass, reloads, notes = _freshness_rig(mods, monkeypatch)
    coord.zone_manager.zones["zone_2"].climate_entity = CAR
    real_get = hass.states.get
    monkeypatch.setattr(hass.states, "get",
                        lambda e: _stale_state(e) if e in (ENT, CAR) else real_get(e))
    await coord._check_carrier_freshness()
    assert reloads == [["zone_2"]]
    assert coord._carrier_stale_zone_count == 1
    assert "freshness" not in coord._carrier_freshness_snapshot["zone_2"]
    assert coord._carrier_freshness_snapshot[ZONE]["freshness"] == "not_applicable"
    assert all("ambiguous" not in json.dumps(n).lower() for n in notes)


# ==========================================================================
# Review fix pass (A-M1 / A-M2 / A-L1 / B-L1..L4 / D MED-1, LOW-1 / C MED)
# ==========================================================================


def _rollout(coord, hass):
    cm = next(e for e in hass.config_entries.async_entries() if "zones" not in (e.options or {}))
    cm.options = {**(cm.options or {}), "hvac_s10_rollout_zone_ids": [ZONE]}


@pytest.mark.asyncio
async def test_fix_a_m1_s10_original_is_compared_with_the_thermostats_own_gap(mods, monkeypatch):
    """A-M1: a 2 °F thermostat, summer Home baseline 72/77. S10 asks for
    72/74: the adapter writes 72/74 (its own gap), so the 72/77 original MUST
    be saved before the write — the default 5 °F gap would have widened the
    request to 72/77 (== the original) and skipped the save. Switch OFF then
    puts 72/77 back."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    S = _S(mods)
    coord.zone_manager.zones[ZONE].thermostat_min_delta_f = 2.0
    real = S._CTX.baseline
    monkeypatch.setattr(
        S._CTX, "baseline",
        lambda p, season=None: (77.0, 72.0) if p == "home" else real(p, season),
    )
    coord._zone_state_store = H.FakeStore()
    _rollout(coord, hass)
    await _tick(coord, hass)
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 72.0, "target_temp_high": 77.0}
    _set_eco(hass, low=72.0, high=77.0)
    coord.zone_manager.update_zone_climate_state(ZONE)
    eco = _eco(mods, hass)
    coord._zones_written_this_cycle.clear()
    coord.set_custom_ranges_enabled(True, source="user")
    monkeypatch.setattr(coord, "_s10_desired",
                        lambda z, p, e, o: ((72.0, 74.0), "preset_range_dpm"))
    await coord._async_apply_preset_overrides()
    await H.drain(hass)
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 72.0, "target_temp_high": 74.0}
    snap = coord._s10_snapshots[ZONE]["home"]
    assert (snap["low"], snap["high"]) == (72.0, 77.0)
    _set_eco(hass, low=72.0, high=74.0)
    coord.set_custom_ranges_enabled(False, source="user")
    await coord._async_apply_preset_overrides()
    await H.drain(hass)
    assert eco._ranges == {}
    assert _temp(hass)[-1] == {"entity_id": ENT, "target_temp_low": 72.0, "target_temp_high": 77.0}
    _assert_inv_e2(hass)


def test_fix_a_m2_corrupt_ranges_are_dropped_and_the_slice_is_consumed(mods, monkeypatch):
    """A-M2: {"held": [...], "ranges": 5} — the held range lands, the
    corrupt ranges are dropped, the pending slice is consumed, and later
    resolutions never raise."""
    _install_registry(monkeypatch, mods)
    S = _S(mods)
    S.rehydrate_adapter_state(None, {ENT: {"held": ["home", 70.0, 77.0], "ranges": 5}})
    eco = S.strategy_for(None, ENT)
    assert eco._held[ENT] == ("home", 70.0, 77.0)
    assert eco._ranges == {}
    assert ENT not in S._PENDING_ADAPTER_STATE
    assert S.strategy_for(None, ENT) is eco
    # The adapter itself accepts the corrupt slice without raising.
    assert eco.rehydrate_state({"climate.other": {"held": None, "ranges": 5}}) is True


def test_fix_a_m2_a_raising_rehydrate_drops_the_pending_slice(mods, monkeypatch):
    """A-M2 (`_note_resolution`): a slice the profile raises on is dropped
    once — never retried (and re-raised) on every `strategy_for`."""
    _install_registry(monkeypatch, mods)
    S = _S(mods)

    def _boom(self, blob):
        raise RuntimeError("corrupt")
    monkeypatch.setattr(S.EcobeeHomeKitStrategy, "rehydrate_state", _boom)
    S._PENDING_ADAPTER_STATE[ENT] = {"held": "junk"}
    eco = S.strategy_for(None, ENT)
    assert ENT not in S._PENDING_ADAPTER_STATE
    assert S.strategy_for(None, ENT) is eco


@pytest.mark.asyncio
async def test_fix_a_l1_fast_runs_do_not_advance_the_heat_cool_stuck_count(mods, monkeypatch):
    """A-L1: zone-scoped fast runs never count toward the 3-tick escalation;
    full ticks do."""
    coord, hass = _rig(mods, monkeypatch, mode="cool", low=None, high=None)
    from homeassistant.helpers import issue_registry as ir
    created = []
    monkeypatch.setattr(ir, "async_create_issue", lambda *a, **k: created.append(k))
    monkeypatch.setattr(ir, "async_delete_issue", lambda *a, **k: None)
    eco = _eco(mods, hass)
    for _ in range(4):
        coord.zone_manager.update_zone_climate_state(ZONE)
        await coord._apply_house_state_presets(zone_filter={ZONE}, trigger="fast_entry")
        await H.drain(hass)
    assert eco._mode_stuck.get(ENT, 0) == 0
    assert created == []
    for _ in range(3):
        await _tick(coord, hass)
    assert eco._mode_stuck[ENT] == 3
    assert [k["translation_key"] for k in created] == ["thermostat_heat_cool_not_reached"]


@pytest.mark.asyncio
async def test_fix_b_l2_s1_skip_in_heat_cool_ends_the_stuck_episode_and_repair(mods, monkeypatch):
    """B-L2: the zone holds home, drifts to cool for three full ticks (Repair
    raised), then reads heat_cool with URA's range again: S1 SKIPS (no
    write) — that skip resets the stuck count and deletes the Repair."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    from homeassistant.helpers import issue_registry as ir
    created, deleted = [], []
    monkeypatch.setattr(ir, "async_create_issue", lambda *a, **k: created.append(a[2]))
    monkeypatch.setattr(ir, "async_delete_issue", lambda *a, **k: deleted.append(a[2]))
    await _tick(coord, hass)                                   # holds home 70/77
    eco = _eco(mods, hass)
    _set_eco(hass, mode="cool", temperature=77.0)
    for _ in range(3):
        await _tick(coord, hass)
    assert created == [f"thermostat_heat_cool_not_reached_{ENT}"]
    n_writes = len(_temp(hass))
    _set_eco(hass, low=70.0, high=77.0)
    await _tick(coord, hass)
    assert len(_temp(hass)) == n_writes                       # the skip path
    assert ENT not in eco._mode_stuck
    assert deleted == [f"thermostat_heat_cool_not_reached_{ENT}"]


@pytest.mark.asyncio
async def test_fix_b_l3_each_repair_key_has_its_own_issue(mods, monkeypatch):
    """B-L3: "no heat_cool" and "heat_cool not reached" are two issues; the
    first is deleted as soon as heat_cool is offered again, while the second
    can still be raised."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    from homeassistant.helpers import issue_registry as ir
    created, deleted = [], []
    monkeypatch.setattr(ir, "async_create_issue",
                        lambda *a, **k: created.append((a[2], k["translation_key"])))
    monkeypatch.setattr(ir, "async_delete_issue", lambda *a, **k: deleted.append(a[2]))
    _set_eco(hass, mode="cool", temperature=74.0, modes=("off", "heat", "cool"))
    await _tick(coord, hass)
    _set_eco(hass, mode="cool", temperature=74.0)              # heat_cool offered, not reached
    for _ in range(3):
        await _tick(coord, hass)
    assert created == [
        (f"thermostat_no_heat_cool_{ENT}", "thermostat_no_heat_cool"),
        (f"thermostat_heat_cool_not_reached_{ENT}", "thermostat_heat_cool_not_reached"),
    ]
    assert deleted == [f"thermostat_no_heat_cool_{ENT}"]
    # Auto heat/cool disabled again while "not reached" is still raised: the
    # "no heat_cool" issue is raised alongside it (never deduped away).
    _set_eco(hass, mode="cool", temperature=74.0, modes=("off", "heat", "cool"))
    await _tick(coord, hass)
    assert created[-1] == (f"thermostat_no_heat_cool_{ENT}", "thermostat_no_heat_cool")
    assert len(created) == 3


@pytest.mark.parametrize("outcome", ["raise", "defer"])
@pytest.mark.asyncio
async def test_fix_b_l4_failed_write_never_undoes_a_newer_stamp(mods, monkeypatch, outcome):
    """B-L4: another write stamped `held` while this one was on the wire —
    the failed / deferred write must not roll that newer stamp back."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    eco = _eco(mods, hass)
    eco._held[ENT] = ("sleep", 70.0, 76.0)
    newer = ("away", 60.0, 82.0)

    async def _emit(*a, **k):
        eco._held[ENT] = newer
        if outcome == "raise":
            raise RuntimeError("wire")
        return False
    monkeypatch.setattr(mods["hvac_setpoint"], "emit_set_temperature", _emit)
    if outcome == "raise":
        with pytest.raises(RuntimeError):
            await eco.pin_preset(hass, ENT, "home", site="S7", zone_id=ZONE, reason="r")
    else:
        await eco.pin_preset(hass, ENT, "home", site="S7", zone_id=ZONE, reason="r")
    assert eco._held[ENT] is newer


@pytest.mark.asyncio
async def test_fix_b_l1_profile_switch_stands_down_the_zones_arrester_timers(mods, monkeypatch):
    """B-L1: the drain cancels the switched zone's nudge-restore / eval /
    grace / compromise timers and ends the arrester episode; the AC-reset
    restore timer (another owner) survives."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    S = _S(mods)
    arr = coord._override_arrester
    cancelled = []
    for name in ("_nudge_restore_timers", "_nudge_eval_timers", "_grace_timers",
                 "_compromise_timers", "_reset_timers"):
        getattr(arr, name)[ZONE] = (lambda n=name: cancelled.append(n))
    arr._nudge_in_flight.add(ZONE)
    arr._override_active[ZONE] = True
    arr._compromise_active[ZONE] = True
    arr._arrest_episode[ZONE] = {"original_preset": "home"}
    S._PROFILE_SWITCHES.append((ENT, "homekit_controller", "ha_carrier"))
    calls_before = len(hass.services.calls)
    await coord._w1c_drain_profile_switches()
    await H.drain(hass)
    assert sorted(cancelled) == sorted(["_nudge_restore_timers", "_nudge_eval_timers",
                                        "_grace_timers", "_compromise_timers"])
    assert ZONE in arr._reset_timers
    assert ZONE not in arr._nudge_in_flight
    assert not arr._override_active[ZONE] and not arr._compromise_active[ZONE]
    assert ZONE not in arr._arrest_episode
    assert not arr._borrow_gate_armed(ZONE)
    assert len(hass.services.calls) == calls_before


def test_fix_d_med1_arrester_reference_is_the_held_effective_range(mods, monkeypatch):
    """D MED-1 (`_arrester_reference`): the ecobee zone is measured against
    the range URA holds (shoulder Home 74/70 widened to the 5 °F gap ->
    70/75; a stored S10 range wins); the Carrier zone keeps the Seasonal
    Baseline exactly."""
    coord, hass = _rig(mods, monkeypatch, season="shoulder")
    res = coord._override_arrester._baseline_resolver
    assert res(ZONE, "home") == ("home", 75.0, 70.0)
    assert res(CAR_ZONE, "home") == ("home", 74.0, 70.0)
    _eco(mods, hass)._ranges[(ENT, "home", "shoulder")] = (68.0, 76.0)
    assert res(ZONE, "home") == ("home", 76.0, 68.0)
    assert res(CAR_ZONE, "home") == ("home", 74.0, 70.0)


@pytest.mark.asyncio
async def test_fix_d_med1_startup_audit_measures_against_the_held_range(mods, monkeypatch):
    """D MED-1 (startup audit): URA holds a stored 66/80 for home; the device
    shows 70/77 (= the baseline). That is a 3-4 °F departure from URA's
    range -> revert scheduled (the baseline would have read delta 0)."""
    coord, hass = _rig(mods, monkeypatch, low=70.0, high=77.0)
    arr = coord._override_arrester
    eco = _eco(mods, hass)
    eco._ranges[(ENT, "home", "summer")] = (66.0, 80.0)
    eco._held[ENT] = ("home", 66.0, 80.0)
    await arr.async_startup_audit(coord._preset_manager, "home_day")
    await H.drain(hass)
    assert arr._override_active.get(ZONE) is True
    assert ZONE in arr._grace_timers
    assert (arr._arrest_episode[ZONE]["expected_cool"],
            arr._arrest_episode[ZONE]["expected_heat"]) == (80.0, 66.0)


def test_fix_d_low1_unreadable_manufacturer_keeps_a_resolved_ecobee(mods, monkeypatch):
    """D LOW-1: a None manufacturer (device registry miss) never downgrades
    an entity already resolved to ecobee; a real different maker does."""
    _reg, dreg = _install_registry(monkeypatch, mods)
    S = _S(mods)
    eco = S.strategy_for(None, ENT)
    eco._held[ENT] = ("home", 70.0, 77.0)
    dreg.devices.pop(DEV)
    assert S.strategy_for(None, ENT) is eco
    assert eco._held[ENT] == ("home", 70.0, 77.0)
    assert S.drain_profile_switches() == []
    dreg.devices[DEV] = types.SimpleNamespace(manufacturer="Honeywell")
    assert type(S.strategy_for(None, ENT)) is S.GenericStrategy
    assert S.drain_profile_switches() == [(ENT, "homekit_controller", "homekit_controller")]


@pytest.mark.asyncio
async def test_fix_c_stale_ecobee_after_settle_never_trips_the_reload_wire(mods, monkeypatch):
    """C MED: a stale ecobee with a Carrier reload older than the settle
    window — no trip-wire, the post-reload stale counter clears, and the
    ecobee zone is never a qualifying zone."""
    from datetime import timedelta
    coord, hass, reloads, notes = _freshness_rig(mods, monkeypatch)
    trips = []

    async def _trip(**kw):
        trips.append(kw)
    monkeypatch.setattr(coord, "_trip_wire_carrier_reload_ineffective", _trip)
    real_get = hass.states.get
    monkeypatch.setattr(hass.states, "get",
                        lambda e: _stale_state(e) if e == ENT else real_get(e))
    settle = float(mods["hvac_const"].DEFAULT_HVAC_CARRIER_POST_RELOAD_SETTLE_S)
    coord._last_carrier_reload_at = mods["hvac"].dt_util.utcnow() - timedelta(seconds=settle + 30)
    coord._carrier_reload_suppressed_today = False
    coord._carrier_stale_ticks_since_reload = 3
    await coord._check_carrier_freshness()
    assert trips == []
    assert coord._carrier_stale_ticks_since_reload == 0
    assert reloads == []
    # Mixed: a stale Carrier zone qualifies ALONE (the trip-wire names it only).
    coord.zone_manager.zones["zone_2"].climate_entity = CAR
    monkeypatch.setattr(hass.states, "get",
                        lambda e: _stale_state(e) if e in (ENT, CAR) else real_get(e))
    await coord._check_carrier_freshness()
    assert len(trips) == 1 and "qualifying_zones=['zone_2']" in trips[0]["reason"]


@pytest.mark.asyncio
async def test_fix_a_m1_post_await_recheck_uses_the_thermostats_own_gap(mods, monkeypatch):
    """A-M1, the post-await re-check site: at step 9 the 72/77 original
    equals the would-write (5 °F gap) so nothing is captured; during the
    write-ahead save the thermostat's gap becomes 2 °F, so the adapter would
    now write 72/74 with no original saved — S10 must stand down (no
    write, no record)."""
    coord, hass = _rig(mods, monkeypatch, low=68.0, high=72.0)
    S = _S(mods)
    real = S._CTX.baseline
    monkeypatch.setattr(
        S._CTX, "baseline",
        lambda p, season=None: (77.0, 72.0) if p == "home" else real(p, season),
    )
    coord._zone_state_store = H.FakeStore()
    _rollout(coord, hass)
    await _tick(coord, hass)
    _set_eco(hass, low=72.0, high=77.0)
    coord.zone_manager.update_zone_climate_state(ZONE)
    coord._zones_written_this_cycle.clear()
    coord.set_custom_ranges_enabled(True, source="user")
    monkeypatch.setattr(coord, "_s10_desired",
                        lambda z, p, e, o: ((72.0, 74.0), "preset_range_dpm"))
    real_save = coord._s10_save_strict

    async def _save_then_narrow():
        coord.zone_manager.zones[ZONE].thermostat_min_delta_f = 2.0
        await real_save()
    monkeypatch.setattr(coord, "_s10_save_strict", _save_then_narrow)
    n = len(_temp(hass))
    await coord._async_apply_preset_overrides()
    await H.drain(hass)
    assert len(_temp(hass)) == n
    assert ZONE not in coord._s10_snapshots
    assert coord._s10_record(ZONE, "home", "apply") is None
    assert _eco(mods, hass)._ranges == {}

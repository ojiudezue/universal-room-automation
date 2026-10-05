"""HVAC Batch C — Custom Preset Ranges (CPR) behavioural suite.

Plan: docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md
(REV 5 > REV 4 > REV 3.3 > REV 3.2 > REV 3.1 > REV 3).

Every test drives REAL production code on the shared W1-B harness
(`_w1b_harness`: real HVACCoordinator / OverrideArrester / PresetManager /
strategy on the smoke StubHass). The strategy is resolved through a REAL
entity-registry lookup (`strategy_for`), never monkeypatched: a fixture
registry reports platform `ha_carrier` (Carrier) or misses (Generic).
Oracles are hand-derived literals (SEASONAL_DEFAULTS shoulder Home 74/70 ->
desired (70, 74); the live entity reads 68/76).

Falsifiable invariant (INV-CPR-REV5, plan REV 5 F5):
  With switch 01 resolved True and the Carrier adapter present: at most ONE
  wire call per tick per (zone, preset); ZERO wire calls once the HA view
  equals the composed range; a strategy returning FAILED for any reason
  other than `emit_raised` costs zero wire calls / zero latch / zero NM;
  every APPLIED (zone, preset) has a persisted original captured before it,
  and a restore write happens ONLY while the switch resolved False.
  F-APPLY: an `S10_preset_range` row while the flag is not True.
  F-RESTORE: an `S10_preset_range_restore` row while the flag is not False.
"""
from __future__ import annotations

import asyncio
import json
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

Z1, Z2, Z3 = "zone_1", "zone_2", "zone_3"
E1, E2, E3 = "climate.test_zone_1", "climate.test_zone_2", "climate.test_zone_3"
T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
ROLLOUT_KEY = "hvac_s10_rollout_zone_ids"


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
# Rig
# --------------------------------------------------------------------------


class Clock:
    def __init__(self, start=T0):
        self.now = start

    def advance(self, seconds: float):
        self.now = self.now + timedelta(seconds=seconds)


class OrderedStore(H.FakeStore):
    """FakeStore that records save order against service calls and can be
    told to raise."""

    def __init__(self, events, data=None):
        super().__init__(data)
        self.events = events
        self.raise_next = 0

    async def async_save(self, data):
        if self.raise_next:
            self.raise_next -= 1
            raise OSError("store write failed")
        self.events.append(("save", json.loads(json.dumps(data, default=str))))
        await super().async_save(data)


class Rig:
    def __init__(self, mods, monkeypatch, *, zones=(Z1,), rollout=(Z1,), flag=True,
                 season="shoulder", registry="carrier", house="home_day"):
        self.mods = mods
        self.mp = monkeypatch
        coord, hass = H.make_coord(mods)
        self.coord, self.hass = coord, hass
        self.DOMAIN = mods["const"].DOMAIN
        self.events: list = []
        self.store = OrderedStore(self.events)
        coord._zone_state_store = self.store
        coord._house_state = house
        coord._zone_intelligence_enabled = False
        coord._preset_manager._current_season = season
        self.registry = registry
        from homeassistant.helpers import entity_registry as er

        rig = self

        class _Reg:
            def async_get(self, entity_id):
                if rig.registry == "carrier" and str(entity_id).startswith("climate."):
                    return types.SimpleNamespace(platform="ha_carrier", entity_id=entity_id)
                return None

        _reg = _Reg()
        monkeypatch.setattr(er, "async_get", lambda _h: _reg)
        mods["hvac_strategy"]._test_reset_cache()
        mods["hvac_setpoint"]._test_clear_ura_setpoints()
        self.cm = next(e for e in hass.config_entries.async_entries()
                       if "zones" not in (e.options or {}))
        self.cm.options = {**(self.cm.options or {}), ROLLOUT_KEY: list(rollout)}
        self.overrides: dict = {}
        hass.data[self.DOMAIN]["coordinator_manager"] = types.SimpleNamespace(
            coordinators={"energy": types.SimpleNamespace(
                _dynamic_preset_overrides=self.overrides)},
        )
        for zid, ent in ((Z1, E1), (Z2, E2), (Z3, E3)):
            coord.zone_manager.zones[zid].preset_mode = "home"
            H.set_climate(hass, ent, preset_mode="home", hold_activity="home",
                          low=68.0, high=76.0)
        coord._guest_mode_actuation_enabled = flag
        self.clock = Clock()
        real_dt = mods["hvac"].dt_util
        clock = self.clock

        class _Dt:
            def __getattr__(self, name):
                if name == "utcnow":
                    return lambda: clock.now
                return getattr(real_dt, name)

        monkeypatch.setattr(mods["hvac"], "dt_util", _Dt())
        # Record service calls in the shared event stream (order checks).
        orig_call = hass.services.async_call
        self.raise_domains: set = set()

        async def _svc(domain, service, service_data=None, blocking=False, **kw):
            self.events.append(("call", domain, service, dict(service_data or {})))
            if domain in self.raise_domains:
                raise RuntimeError("cpr_wire_failure")
            return await orig_call(domain, service, service_data, blocking=blocking, **kw)

        hass.services.async_call = _svc

    # ---- helpers -----------------------------------------------------
    @property
    def arr(self):
        return self.coord._override_arrester

    def view(self, ent=E1, *, preset="home", hold=None, low=68.0, high=76.0, state="heat_cool"):
        H.set_climate(self.hass, ent, preset_mode=preset,
                      hold_activity=preset if hold is None else hold,
                      low=low, high=high, state=state)

    def pr_calls(self, ent=None):
        return [
            c[2] for c in self.hass.services.calls
            if c[0] == "ha_carrier" and c[1] == "set_activity_setpoint"
            and (ent is None or c[2].get("entity_id") == ent)
        ]

    async def tick(self, n=1, step_s=0):
        for _ in range(n):
            await self.coord._async_apply_preset_overrides()
            await H.drain(self.hass)
            if step_s:
                self.clock.advance(step_s)

    def rows(self, site):
        return H.climate_write_rows(self.hass, self.mods, site)

    def ledger(self, action):
        return [r for r in self.hass.data[self.DOMAIN]["database"].rows
                if r.get("action") == action]

    def nms(self, hazard=None):
        notes = self.hass.data[self.DOMAIN]["notification_manager"].notes
        return [n for n in notes if hazard is None or n.get("hazard_type") == hazard]

    def restart(self):
        """Simulate a restart for S10: RAM state dropped, rehydrated from
        the persisted store."""
        self.coord._s10_snapshots = {}
        self.coord._s10_records = {}
        self.coord._s10_meta = {}
        self.coord._s10_last_outcome = {}
        self.coord._rehydrate_s10_state(self.store.data)


def _rig(mods, monkeypatch, **kw) -> Rig:
    return Rig(mods, monkeypatch, **kw)


def _dpm(zone_id, preset, cool_high, priority=30):
    from custom_components.universal_room_automation.domain_coordinators.preset_overrides import (
        PresetOverride,
    )
    return PresetOverride(source="dynamic_preset", preset=preset, priority=priority,
                          cool_high=cool_high, zone_id=zone_id, active_when="dynamic_preset")


# ==========================================================================
# D1 — emit_set_activity_setpoint funnel
# ==========================================================================


def _funnel_kwargs(**over):
    kw = dict(service_domain="ha_carrier", service_name="set_activity_setpoint",
              target_temp_low=70.0, target_temp_high=74.0, freeze_active=False,
              blocking=True, gate=None, site="S10_preset_range", zone_id=Z1,
              reason="preset_range_baseline")
    kw.update(over)
    return kw


@pytest.mark.asyncio
async def test_emit_set_activity_setpoint_one_row_per_call(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    sp = mods["hvac_setpoint"]
    assert await sp.emit_set_activity_setpoint(r.hass, E1, **_funnel_kwargs()) is True
    await H.drain(r.hass)
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 74.0}]
    rows = r.rows("S10_preset_range")
    assert len(rows) == 1
    assert rows[0]["verb"] == "set_activity_setpoint" and rows[0]["wire_ok"] is True
    assert rows[0]["values_before"]["preset_mode"] == "home"


@pytest.mark.asyncio
async def test_emit_set_activity_setpoint_raise_one_row(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.raise_domains.add("ha_carrier")
    with pytest.raises(RuntimeError, match="cpr_wire_failure"):
        await mods["hvac_setpoint"].emit_set_activity_setpoint(r.hass, E1, **_funnel_kwargs())
    await H.drain(r.hass)
    rows = r.rows("S10_preset_range")
    assert len(rows) == 1 and rows[0]["wire_ok"] is False and rows[0]["exc"] == "RuntimeError"


@pytest.mark.asyncio
async def test_emit_set_activity_setpoint_gate_defers_no_call(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    out = await mods["hvac_setpoint"].emit_set_activity_setpoint(
        r.hass, E1, **_funnel_kwargs(gate=lambda: True))
    await H.drain(r.hass)
    assert out is False and r.pr_calls() == [] and r.rows("S10_preset_range") == []


@pytest.mark.asyncio
async def test_emit_set_activity_setpoint_freeze_floor(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await mods["hvac_setpoint"].emit_set_activity_setpoint(
        r.hass, E1, **_funnel_kwargs(target_temp_low=45.0, target_temp_high=72.0,
                                     freeze_active=True))
    # FREEZE_FLOOR 50 (hardcoded oracle); 72 >= 50 + 3 deadband -> unchanged.
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 50.0, "target_temp_high": 72.0}]


@pytest.mark.asyncio
async def test_emit_set_activity_setpoint_uses_caller_supplied_domain(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await mods["hvac_setpoint"].emit_set_activity_setpoint(
        r.hass, E1, **_funnel_kwargs(service_domain="brand_x", service_name="edit_profile"))
    calls = [c for c in r.hass.services.calls if c[0] == "brand_x"]
    assert calls == [("brand_x", "edit_profile",
                      {"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 74.0})]


@pytest.mark.asyncio
async def test_emit_set_activity_setpoint_not_in_ura_setpoint_ring(mods, monkeypatch):
    """T11 / §3.1: a profile edit is not a raw setpoint write — the
    within-manual detector's URA ring is untouched."""
    r = _rig(mods, monkeypatch)
    sp = mods["hvac_setpoint"]
    await sp.emit_set_activity_setpoint(r.hass, E1, **_funnel_kwargs())
    assert sp.recent_ura_setpoints(E1) == ()


# ==========================================================================
# D2 — the adapter verbs
# ==========================================================================


class _Spy:
    def __init__(self, ret=True, exc=None, hook=None):
        self.calls = []
        self.ret, self.exc, self.hook = ret, exc, hook

    async def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        if self.hook is not None:
            self.hook()
        if self.exc is not None:
            raise self.exc
        return self.ret


def _carrier(mods):
    return mods["hvac_strategy"].CarrierStrategy()


async def _spr(mods, r, st, *, low=70.0, high=74.0, emit=None, preset="home"):
    return await st.set_preset_range(
        r.hass, E1, preset, low, high, gate=None, zone_id=Z1,
        site="S10_preset_range", reason="preset_range_baseline", emit=emit,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_p,hold_p", [("home", "away"), ("away", "home"), ("home", None)])
async def test_carrier_set_preset_range_requires_both_feeds(mods, monkeypatch, status_p, hold_p):
    r = _rig(mods, monkeypatch)
    H.set_climate(r.hass, E1, preset_mode=status_p, hold_activity=hold_p, low=68.0, high=76.0)
    spy = _Spy()
    res = await _spr(mods, r, _carrier(mods), emit=spy)
    assert res.status.value == "deferred" and res.reason == "activity_not_confirmed"
    assert spy.calls == []


@pytest.mark.asyncio
async def test_carrier_set_preset_range_manual_defers(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.view(preset="manual")
    spy = _Spy()
    res = await _spr(mods, r, _carrier(mods), emit=spy)
    assert (res.status.value, res.reason) == ("deferred", "activity_not_confirmed")
    assert spy.calls == []


@pytest.mark.asyncio
async def test_carrier_set_preset_range_heat_cool_only(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.view(state="cool")
    spy = _Spy()
    res = await _spr(mods, r, _carrier(mods), emit=spy)
    assert (res.status.value, res.reason) == ("deferred", "not_heat_cool")
    assert spy.calls == []


@pytest.mark.asyncio
async def test_carrier_set_preset_range_rounds_and_skips(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=75.0)
    spy = _Spy()
    res = await _spr(mods, r, _carrier(mods), low=70.2, high=75.4, emit=spy)
    assert (res.status.value, res.reason) == ("skipped_already_correct", "ha_view_matches")
    assert spy.calls == []


@pytest.mark.asyncio
async def test_carrier_set_preset_range_applies_diff(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=76.0)
    spy = _Spy()
    res = await _spr(mods, r, _carrier(mods), low=70.0, high=74.0, emit=spy)
    assert (res.status.value, res.reason) == ("applied", "emitted")
    assert len(spy.calls) == 1
    a, kw = spy.calls[0]
    assert a == (r.hass, E1)
    assert kw["service_domain"] == "ha_carrier" and kw["service_name"] == "set_activity_setpoint"
    assert (kw["target_temp_low"], kw["target_temp_high"], kw["blocking"]) == (70.0, 74.0, True)


@pytest.mark.asyncio
async def test_carrier_set_preset_range_rounding_half_up(mods, monkeypatch):
    """P3: 70.5 -> 71, 74.5 -> 75 (half up, hardcoded oracle)."""
    r = _rig(mods, monkeypatch)
    spy = _Spy()
    await _spr(mods, r, _carrier(mods), low=70.5, high=74.5, emit=spy)
    kw = spy.calls[0][1]
    assert (kw["target_temp_low"], kw["target_temp_high"]) == (71.0, 75.0)


@pytest.mark.asyncio
async def test_carrier_set_preset_range_flags_possible_wrong_profile(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    spy = _Spy(hook=lambda: r.view(preset="sleep"))
    res = await _spr(mods, r, _carrier(mods), emit=spy)
    assert (res.status.value, res.reason) == ("applied", "possible_wrong_profile")


@pytest.mark.asyncio
async def test_carrier_set_preset_range_range_unreadable_defers(mods, monkeypatch):
    """No readable view = no original to capture -> never edit."""
    r = _rig(mods, monkeypatch)
    r.hass.states.async_set(E1, "heat_cool", {"preset_mode": "home", "hold_activity": "home"})
    spy = _Spy()
    res = await _spr(mods, r, _carrier(mods), emit=spy)
    assert (res.status.value, res.reason) == ("deferred", "range_unreadable") and spy.calls == []


@pytest.mark.asyncio
async def test_generic_set_preset_range_zero_calls_unsupported(mods, monkeypatch):
    """REV 5 F1 rename: (a) FAILED preset_range_unsupported, (b) zero
    climate/service calls, (c) no call_failed latch and no NM through S10."""
    r = _rig(mods, monkeypatch, registry="miss")
    st = mods["hvac_strategy"].GenericStrategy()
    spy = _Spy()
    res = await _spr(mods, r, st, emit=spy)
    assert (res.status.value, res.reason) == ("failed", "preset_range_unsupported")
    assert spy.calls == [] and r.hass.services.calls == []
    await r.tick()
    assert r.hass.services.calls == []
    assert r.coord._s10_records == {}
    assert r.nms("s10_preset_range_call_failed") == []


@pytest.mark.asyncio
async def test_set_preset_range_no_await_between_observe_and_wire(mods, monkeypatch):
    """P5/T5: the view the adapter decides on is the one the wire call is
    issued against — a state change scheduled on the loop cannot slip in."""
    r = _rig(mods, monkeypatch)
    seen = []

    async def _emit(hass, ent, **kw):
        seen.append(hass.states.get(ent).attributes.get("preset_mode"))
        return True

    def _flip():
        r.view(preset="sleep")
    r.hass.loop.call_soon(_flip)
    res = await _spr(mods, r, _carrier(mods), emit=_emit)
    assert seen == ["home"]
    assert res.status.value == "applied"


@pytest.mark.asyncio
async def test_carrier_set_preset_range_records_nothing_in_last_sent(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    st = _carrier(mods)
    st._record_sent(E1, "set_preset_mode", "home")
    await _spr(mods, r, st, emit=_Spy())
    assert st.last_sent(E1, "set_preset_mode") == "home"
    assert set(st._last_sent[E1]) == {"set_preset_mode"}


@pytest.mark.asyncio
async def test_set_preset_range_wire_raise_maps_failed_emit_raised(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    res = await _spr(mods, r, _carrier(mods), emit=_Spy(exc=RuntimeError("x")))
    assert (res.status.value, res.reason, res.exc) == ("failed", "emit_raised", "RuntimeError")


@pytest.mark.asyncio
async def test_preset_range_original_carrier_and_generic(mods, monkeypatch):
    """REV 5 F2 verb: Carrier = the HA view of P while confirmed on P
    (whole °F); Generic = None."""
    r = _rig(mods, monkeypatch)
    S = mods["hvac_strategy"]
    r.view(low=68.4, high=75.6)
    assert _carrier(mods).preset_range_original(r.hass, E1, "home") == (68, 76)
    assert _carrier(mods).preset_range_original(r.hass, E1, "sleep") is None
    r.view(hold="away")
    assert _carrier(mods).preset_range_original(r.hass, E1, "home") is None
    r.view()
    assert S.GenericStrategy().preset_range_original(r.hass, E1, "home") is None


# ==========================================================================
# D3 — the S10 apply pass
# ==========================================================================


@pytest.mark.asyncio
async def test_s10_applies_named_profile_on_rollout_zone(mods, monkeypatch):
    """Control: zone_1 on home (68/76) vs shoulder Home 70/74 -> ONE
    set_activity_setpoint, original 68/76 snapshotted, record writes 1."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 74.0}]
    assert r.coord._s10_snapshots[Z1]["home"]["low"] == 68.0
    assert r.coord._s10_snapshots[Z1]["home"]["high"] == 76.0
    rec = r.coord._s10_records[Z1]["home|apply"]
    assert rec["writes"] == 1 and rec["value"] == [70.0, 74.0]
    rows = r.rows("S10_preset_range")
    assert len(rows) == 1 and rows[0]["reason"] == "preset_range_baseline"


@pytest.mark.asyncio
async def test_s10_edits_profile_not_hold_no_s1_reclaim(mods, monkeypatch):
    """§3.1 / T2: through `_apply_house_state_presets` — DPM cool_high 75 vs
    the zone's 76: one profile edit, NO preset write, the zone never goes
    manual; the next tick has zero S1 writes and zero S10 calls."""
    r = _rig(mods, monkeypatch)
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    await r.coord._apply_house_state_presets()
    await H.drain(r.hass)
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 75.0}]
    assert H.preset_writes(r.hass, E1) == [] and H.temp_writes(r.hass, E1) == []
    r.view(low=70.0, high=75.0)          # the device took it; still named home
    r.clock.advance(300)
    await r.coord._apply_house_state_presets()
    await H.drain(r.hass)
    assert len(r.pr_calls()) == 1
    assert H.preset_writes(r.hass, E1) == []
    assert r.hass.states.get(E1).attributes["preset_mode"] == "home"


@pytest.mark.asyncio
async def test_s10_empty_zone_no_storm_12_ticks(mods, monkeypatch):
    """U6 / compose-away card: an established fused-empty zone on `away`
    whose profile matches gets ZERO calls over 12 ticks (old code: 12)."""
    r = _rig(mods, monkeypatch)
    z = r.coord.zone_manager.zones[Z1]
    z.preset_mode = "away"
    r.view(preset="away", low=62.0, high=80.0)   # shoulder Away 80/62 already
    monkeypatch.setattr(r.coord, "_zone_conditioning_retreat_ok", lambda _z: True)
    await r.tick(12, step_s=300)
    assert r.pr_calls() == [] and r.rows("S10_preset_range") == []


@pytest.mark.asyncio
async def test_s10_no_s1_alternation_on_empty_zone(mods, monkeypatch):
    """U6 discriminator: 6 full ticks through `_apply_house_state_presets`
    on an empty zone that S1 holds `away` — there is no (S10 call -> S1
    preset_change) pair on the same zone (the compose-away storm shape)."""
    r = _rig(mods, monkeypatch, house="away")
    for zid in (Z1, Z2, Z3):
        r.coord.zone_manager.zones[zid].preset_mode = "away"
    r.view(preset="away", low=62.0, high=81.0)   # differs from 80/62 once
    r.view(E2, preset="away", low=62.0, high=80.0)
    r.view(E3, preset="away", low=62.0, high=80.0)
    seq = []
    for _ in range(6):
        n_pr, n_pm = len(r.pr_calls(E1)), len(H.preset_writes(r.hass, E1))
        await r.coord._apply_house_state_presets()
        await H.drain(r.hass)
        seq.append((len(r.pr_calls(E1)) - n_pr, len(H.preset_writes(r.hass, E1)) - n_pm))
        r.clock.advance(300)
    assert sum(p for p, _ in seq) == 1, seq
    assert all(pm == 0 for _, pm in seq), seq


SKIPS = ["egress", "unavailable", "person_protected", "same_tick", "borrow_row",
         "nudge_in_flight", "compromise_timer", "ac_reset", "manual", "wake"]


def _apply_skip(r, mods, case, monkeypatch):
    c, arr, z = r.coord, r.arr, r.coord.zone_manager.zones[Z1]
    if case == "egress":
        monkeypatch.setattr(c._egress_manager, "is_paused", lambda zid: zid == Z1)
    elif case == "unavailable":
        r.hass.states.async_set(E1, "unavailable", {})
    elif case == "person_protected":
        monkeypatch.setattr(arr, "_corrective_writes_suppressed", lambda zid: zid == Z1)
    elif case == "same_tick":
        c._zones_written_this_cycle.add(Z1)
    elif case == "borrow_row":
        ex = mods["hvac_excursion"]
        ex._test_seed_row(Z1, kind=ex.EXCURSION_KIND.COMPROMISE, duration_s=900)
    elif case == "nudge_in_flight":
        arr._nudge_in_flight.add(Z1)
    elif case == "compromise_timer":
        arr._compromise_timers[Z1] = lambda: None
    elif case == "ac_reset":
        arr._reset_timers[Z1] = lambda: None
    elif case == "manual":
        z.preset_mode = "manual"
        r.view(preset="manual")
    elif case == "wake":
        z.preset_mode = "wake"
        r.view(preset="wake")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["none"] + SKIPS)
async def test_s10_skip_matrix(mods, monkeypatch, case):
    r = _rig(mods, monkeypatch)
    if case != "none":
        _apply_skip(r, mods, case, monkeypatch)
    await r.tick()
    mods["hvac_excursion"]._test_clear_leases()
    if case == "none":
        assert len(r.pr_calls()) == 1   # non-vacuity control
    else:
        assert r.pr_calls() == [], case
        assert Z1 not in r.coord._s10_snapshots, case


@pytest.mark.asyncio
@pytest.mark.parametrize("preset", ["wake", "manual"])
async def test_s10_never_edits_wake_or_manual_even_with_a_baseline(mods, monkeypatch, preset):
    """Step 6 (§12 "no wake preset"): only home/sleep/away/vacation are
    edited, even if a baseline table ever names another preset."""
    r = _rig(mods, monkeypatch)
    monkeypatch.setattr(r.coord._preset_manager, "get_seasonal_setpoints",
                        lambda p, season=None: (74.0, 70.0))
    r.coord.zone_manager.zones[Z1].preset_mode = preset
    r.view(preset=preset)
    await r.tick()
    assert r.pr_calls() == []


@pytest.mark.asyncio
async def test_s10_defers_when_climate_unreadable(mods, monkeypatch):
    """Step 0.5: zero calls, zero snapshot, and S10 opens NO second outage
    episode (the Batch D helper's one row only)."""
    r = _rig(mods, monkeypatch)
    r.hass.states.async_set(E1, "unavailable", {})
    await r.tick(3, step_s=300)
    assert r.pr_calls() == [] and r.coord._s10_records == {}
    held = r.hass.data[r.DOMAIN]["activity_logger"].actions("climate_write_held_unreadable")
    assert len(held) == 1


@pytest.mark.asyncio
async def test_s10_low_side_uses_configured_heat_winter_away(mods, monkeypatch):
    """Bug Class #63: winter away 80/65 -> writes 65/80 (cool-7 would be 73)."""
    r = _rig(mods, monkeypatch, season="winter")
    r.cm.options = {**r.cm.options, "hvac_baseline_winter_away_cool": 80,
                    "hvac_baseline_winter_away_heat": 65}
    r.coord.zone_manager.zones[Z1].preset_mode = "away"
    r.view(preset="away", low=60.0, high=78.0)
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 65.0, "target_temp_high": 80.0}]


@pytest.mark.asyncio
async def test_s10_acts_on_zone_preset_not_house_state(mods, monkeypatch):
    """House home_day (target home) but the zone sits on away: the AWAY
    profile (shoulder 80/62) is edited, never home's 74/70."""
    r = _rig(mods, monkeypatch)
    r.coord.zone_manager.zones[Z1].preset_mode = "away"
    r.view(preset="away", low=60.0, high=82.0)
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 62.0, "target_temp_high": 80.0}]
    assert "away" in r.coord._s10_snapshots[Z1] and "home" not in r.coord._s10_snapshots[Z1]


@pytest.mark.asyncio
async def test_s10_dpm_sleep_override_applies_only_in_sleep(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.overrides[Z1] = [_dpm(Z1, "sleep", 75.0)]
    await r.tick()     # zone on home -> baseline 70/74, reason baseline
    assert r.pr_calls()[-1]["target_temp_high"] == 74.0
    assert r.rows("S10_preset_range")[-1]["reason"] == "preset_range_baseline"
    r.coord.zone_manager.zones[Z1].preset_mode = "sleep"
    r.view(preset="sleep", low=68.0, high=73.0)
    await r.tick()     # zone on sleep -> shoulder sleep heat 68, override 75
    assert r.pr_calls()[-1] == {"entity_id": E1, "target_temp_low": 68.0, "target_temp_high": 75.0}
    assert r.rows("S10_preset_range")[-1]["reason"] == "preset_range_dpm"


@pytest.mark.asyncio
async def test_s10_edit_books_no_override_detected(mods, monkeypatch):
    """M4 / T6: S10 stamps NO suppression, and the profile edit replayed as
    a state_changed (named home -> home, new range) books no override."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    assert E1 not in r.arr._suppressed_until
    ev = H.make_event(E1, old_preset="home", new_preset="home",
                      old_high=76.0, new_high=74.0, old_low=68.0, new_low=70.0)
    r.arr._handle_climate_change(ev)
    await H.drain(r.hass)
    booked = r.hass.data[r.DOMAIN]["activity_logger"].actions("override_detected")
    assert booked == []
    assert Z1 not in r.arr._grace_timers and Z1 not in getattr(r.arr, "_comfort_delay_timers", {})


@pytest.mark.asyncio
async def test_s10_edit_not_recorded_in_within_manual_detector(mods, monkeypatch):
    """T11: an S10 edit is NOT in the URA set_temperature ring, so a person
    typing the same numbers into the manual profile is still booked HUMAN."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    sp, ov = mods["hvac_setpoint"], mods["hvac_override"]
    assert sp.recent_ura_setpoints(E1) == ()
    old = types.SimpleNamespace(state="heat_cool", attributes={
        "preset_mode": "manual", "target_temp_low": 68.0, "target_temp_high": 76.0})
    new = types.SimpleNamespace(state="heat_cool", attributes={
        "preset_mode": "manual", "target_temp_low": 70.0, "target_temp_high": 74.0})
    assert ov.classify_manual_setpoint_change(old, new, sp.recent_ura_setpoints(E1), 0.5) \
        == ov.MANUAL_CHANGE_HUMAN


@pytest.mark.asyncio
async def test_s10_comfort_gate_defers_then_fires(mods, monkeypatch):
    """ARREST-COMFORT-1 at S10: comfort window active -> funnel gate defers
    (no wire call); window gone + spacing elapsed -> fires."""
    r = _rig(mods, monkeypatch)
    monkeypatch.setattr(r.arr, "comfort_delay_active", lambda zid: zid == Z1)
    await r.tick()
    assert r.pr_calls() == []
    assert r.coord._s10_last_outcome[Z1]["home"]["reason"] == "gate_deferred"
    monkeypatch.setattr(r.arr, "comfort_delay_active", lambda zid: False)
    r.clock.advance(600)
    await r.tick()
    assert len(r.pr_calls()) == 1


@pytest.mark.asyncio
async def test_s10_deferred_consumes_rate_clock(mods, monkeypatch):
    """REV 5 F1: DEFERRED consumes the rate clock (the attempt stamp is
    kept): once the deferral clears, a retry inside the 600 s spacing makes
    no call (599 s literal) and the next one at 600 s does."""
    r = _rig(mods, monkeypatch)
    monkeypatch.setattr(r.arr, "comfort_delay_active", lambda zid: zid == Z1)
    await r.tick()
    monkeypatch.setattr(r.arr, "comfort_delay_active", lambda zid: False)
    r.clock.advance(599)
    await r.tick()
    assert r.pr_calls() == []
    assert r.coord._s10_records[Z1]["home|apply"]["failures"] == 0
    r.clock.advance(1)
    await r.tick()
    assert len(r.pr_calls()) == 1


@pytest.mark.asyncio
async def test_s10_possible_wrong_profile_logs_row(mods, monkeypatch):
    """P6 at S10: the status activity moves under the wire call -> APPLIED
    flagged, one `s10_possible_wrong_profile` row, the write still counts."""
    r = _rig(mods, monkeypatch)
    orig = r.hass.services.async_call

    async def _svc(domain, service, data=None, blocking=False, **kw):
        out = await orig(domain, service, data, blocking=blocking, **kw)
        if domain == "ha_carrier":
            r.view(preset="sleep")
        return out
    r.hass.services.async_call = _svc
    await r.tick()
    assert len(r.ledger("s10_possible_wrong_profile")) == 1
    assert r.coord._s10_records[Z1]["home|apply"]["writes"] == 1


@pytest.mark.asyncio
async def test_s10_freeze_floor_raises_configured_low(mods, monkeypatch):
    r = _rig(mods, monkeypatch, season="winter")
    r.cm.options = {**r.cm.options, "hvac_baseline_winter_home_cool": 72,
                    "hvac_baseline_winter_home_heat": 45}
    r.coord._freeze_active = True
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 50.0, "target_temp_high": 72.0}]


@pytest.mark.asyncio
async def test_s10_freeze_floor_inactive_writes_configured_low(mods, monkeypatch):
    r = _rig(mods, monkeypatch, season="winter")
    r.cm.options = {**r.cm.options, "hvac_baseline_winter_home_cool": 72,
                    "hvac_baseline_winter_home_heat": 45}
    r.coord._freeze_active = False
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 45.0, "target_temp_high": 72.0}]


@pytest.mark.asyncio
async def test_s10_registry_miss_generic_skips_quietly(mods, monkeypatch):
    """U2/U1 + REV 5 F1 + F7 drill target: a registry-miss (Generic) zone
    makes zero calls, keeps no record, no snapshot, no failure count, no
    latch and no NM — over 12 ticks."""
    r = _rig(mods, monkeypatch, registry="miss")
    await r.tick(12, step_s=900)
    assert r.hass.services.calls == []
    assert r.coord._s10_records == {}, "a quiet skip must not leave a record / failure / latch"
    assert r.coord._s10_snapshots == {}
    assert r.nms() == []


@pytest.mark.asyncio
async def test_s10_generic_strategy_quiet_skip_zero_rows_zero_latch(mods, monkeypatch):
    """REV 4 D3 add-on: zero climate_write rows and zero latch over 12 ticks."""
    r = _rig(mods, monkeypatch, registry="miss")
    await r.tick(12, step_s=900)
    assert r.rows("S10_preset_range") == [] and r.rows("S10_preset_range_restore") == []
    assert not any(rec.get("latched") for d in r.coord._s10_records.values() for rec in d.values())


@pytest.mark.asyncio
async def test_s10_generic_zone_never_snapshots(mods, monkeypatch):
    """REV 5 F2: a Generic zone captures no original and so never produces
    a restore row across apply -> OFF."""
    r = _rig(mods, monkeypatch, registry="miss")
    await r.tick(2, step_s=900)
    r.coord.set_custom_ranges_enabled(False, source="user")
    await r.tick(2, step_s=8000)
    assert r.coord._s10_snapshots == {}
    assert r.rows("S10_preset_range_restore") == []


@pytest.mark.asyncio
async def test_s10_strategy_call_supplies_site_zone_reason(mods, monkeypatch):
    """U1: the funnel passed as `emit=` receives site / zone_id / reason."""
    r = _rig(mods, monkeypatch)
    spy = _Spy()
    monkeypatch.setattr(mods["hvac"], "emit_set_activity_setpoint", spy)
    await r.tick()
    assert len(spy.calls) == 1
    kw = spy.calls[0][1]
    assert (kw["site"], kw["zone_id"], kw["reason"]) == ("S10_preset_range", Z1, "preset_range_baseline")


@pytest.mark.asyncio
async def test_s10_rollout_default_empty_set_no_apply_rows_on_fresh_install(mods, monkeypatch):
    """REV 5 F6: no rollout option at all (fresh install) -> nothing edited."""
    r = _rig(mods, monkeypatch, zones=(Z1, Z2, Z3))
    r.cm.options = {k: v for k, v in r.cm.options.items() if k != ROLLOUT_KEY}
    await r.tick(3, step_s=900)
    assert r.pr_calls() == [] and r.rows("S10_preset_range") == []


@pytest.mark.asyncio
async def test_s10_rollout_scope_apply_zone_3_only_restore_all(mods, monkeypatch):
    """U5/F6: apply only to the opted-in zone; restore is NOT gated."""
    r = _rig(mods, monkeypatch, rollout=(Z3,))
    await r.tick()
    assert [c["entity_id"] for c in r.pr_calls()] == [E3]
    # A zone outside the rollout with a persisted original still restores.
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    r.coord.set_custom_ranges_enabled(False, source="user")
    r.clock.advance(600)
    await r.tick()
    restored = [c for c in r.pr_calls() if c["entity_id"] == E1]
    assert restored == [{"entity_id": E1, "target_temp_low": 66.0, "target_temp_high": 77.0}]


@pytest.mark.asyncio
async def test_s10_nm_templates_use_strategy_app_name(mods, monkeypatch):
    """REV 5 F9: NM text names the adapter's app; Generic -> neutral noun."""
    r = _rig(mods, monkeypatch)
    S = mods["hvac_strategy"]
    z = r.coord.zone_manager.zones[Z1]
    eco = types.SimpleNamespace(app_name="ecobee")
    for strat in (S.CarrierStrategy(), eco, S.GenericStrategy()):
        r.coord._s10_latch(Z1, z, "home", "restore", {"value": [70.0, 74.0]},
                           "not_sticking", [70.0, 74.0], strat)
    await H.drain(r.hass)
    msgs = [n["message"] for n in r.nms("s10_restore_not_taking")]
    assert msgs[0].endswith("Please set it in the Bryant app.")
    assert msgs[1].endswith("Please set it in the ecobee app.")
    assert msgs[2].endswith("Please set it in the thermostat app.")
    assert "Bryant" not in msgs[2]


@pytest.mark.asyncio
async def test_borrow_live_extraction_verdict_identical(mods, monkeypatch):
    """`borrow_live` is exactly gate (e) of `manual_guard_verdict`."""
    r = _rig(mods, monkeypatch)
    pm, arr, ex = r.coord._preset_manager, r.arr, mods["hvac_excursion"]
    expect = {
        "none": None, "row": "row", "nudge_restore_timer": "nudge_restore_timer",
        "nudge_in_flight": "nudge_in_flight", "compromise_timer": "compromise_timer",
    }
    for case, want in expect.items():
        ex._test_clear_leases()
        arr._nudge_restore_timers.pop(Z1, None)
        arr._nudge_in_flight.discard(Z1)
        arr._compromise_timers.pop(Z1, None)
        if case == "row":
            ex._test_seed_row(Z1, kind=ex.EXCURSION_KIND.BANKING, duration_s=None)
        elif case == "nudge_restore_timer":
            arr._nudge_restore_timers[Z1] = lambda: None
        elif case == "nudge_in_flight":
            arr._nudge_in_flight.add(Z1)
        elif case == "compromise_timer":
            arr._compromise_timers[Z1] = lambda: None
        assert pm.borrow_live(Z1) == want, case
        assert pm.manual_guard_verdict(Z1)["gate_snapshot"]["e_source"] == want, case
    ex._test_clear_leases()


# ==========================================================================
# INV-CPR-REV5 falsifiers + config extremes
# ==========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [None, False, True])
async def test_s10_F_APPLY_and_F_RESTORE_by_flag(mods, monkeypatch, flag):
    """With a persisted original AND a differing view on the zone's preset:
    apply rows only when the flag is True; restore rows only when False;
    nothing at all while unresolved."""
    r = _rig(mods, monkeypatch, flag=flag)
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    await r.tick(3, step_s=8000)
    apply_rows, restore_rows = r.rows("S10_preset_range"), r.rows("S10_preset_range_restore")
    assert bool(apply_rows) is (flag is True)
    assert bool(restore_rows) is (flag is False)


@pytest.mark.asyncio
async def test_s10_at_most_one_wire_call_per_tick_per_zone_preset(mods, monkeypatch):
    r = _rig(mods, monkeypatch, rollout=(Z1, Z2, Z3))
    for _ in range(6):
        before = {e: len(r.pr_calls(e)) for e in (E1, E2, E3)}
        await r.tick(step_s=8000)
        for e in (E1, E2, E3):
            assert len(r.pr_calls(e)) - before[e] <= 1


@pytest.mark.asyncio
async def test_s10_extreme_rollout_empty_switch_off_still_restores(mods, monkeypatch):
    """Config extreme: rollout empty AND switch OFF with a pending original
    -> the restore still runs (U5 restore ungated)."""
    r = _rig(mods, monkeypatch, rollout=(), flag=False)
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 66.0, "target_temp_high": 77.0}]


@pytest.mark.asyncio
async def test_s10_extreme_dpm_high_below_heat_deadband_clamped(mods, monkeypatch):
    """Config extreme: DPM cool_high 71 vs configured heat 70 (inside the
    2 F MIN_DEADBAND) -> the guard raises high to 72 BEFORE stamp + write
    (clamp before stamp: the recorded value is the written one)."""
    r = _rig(mods, monkeypatch)
    r.overrides[Z1] = [_dpm(Z1, "home", 71.0)]
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 72.0}]
    assert r.coord._s10_records[Z1]["home|apply"]["value"] == [70.0, 72.0]


@pytest.mark.asyncio
async def test_s10_extreme_freeze_floor_and_dpm_high_below_floor(mods, monkeypatch):
    """Config extreme (two guards at once): winter Home heat 45 with freeze
    active AND a DPM cool_high 49 -> low raised to the 50 F floor, high
    raised to 52 (floor + 2 F MIN_DEADBAND); the record holds what is
    written."""
    r = _rig(mods, monkeypatch, season="winter")
    r.cm.options = {**r.cm.options, "hvac_baseline_winter_home_cool": 72,
                    "hvac_baseline_winter_home_heat": 45}
    r.overrides[Z1] = [_dpm(Z1, "home", 49.0)]
    r.coord._freeze_active = True
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 50.0, "target_temp_high": 52.0}]
    assert r.coord._s10_records[Z1]["home|apply"]["value"] == [50.0, 52.0]


@pytest.mark.asyncio
async def test_s10_value_change_discharges_latch(mods, monkeypatch):
    """A latched (zone, preset) re-opens on a value change (subject to the
    600 s spacing) — the documented discharge besides a user toggle."""
    r = _rig(mods, monkeypatch)
    for _ in range(4):
        await r.tick()
        r.clock.advance(7800)
    assert r.coord._s10_records[Z1]["home|apply"]["latched"] is True
    n = len(r.pr_calls())
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    await r.tick()
    assert len(r.pr_calls()) == n + 1
    assert r.coord._s10_records[Z1]["home|apply"]["latched"] is False


@pytest.mark.asyncio
async def test_s10_zero_calls_once_view_matches_steady_state(mods, monkeypatch):
    """INV-CPR-REV5 clause 2: after the device holds the range, 12 more
    ticks (incl. past the 130-min retry) make ZERO wire calls."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    r.view(low=70.0, high=74.0)
    for _ in range(12):
        r.clock.advance(1800)
        await r.tick()
    assert len(r.pr_calls()) == 1


# ==========================================================================
# D3b — originals: capture, restore, persistence
# ==========================================================================


@pytest.mark.asyncio
async def test_s10_snapshot_saved_before_first_edit(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await r.tick()
    kinds = [e[0] for e in r.events]
    first_call = kinds.index("call")
    saves_before = [e[1] for e in r.events[:first_call] if e[0] == "save"]
    assert any(
        s.get("__s10_preset_ranges", {}).get("snapshots", {}).get(Z1, {}).get("home")
        == {"low": 68.0, "high": 76.0, "captured_iso": T0.isoformat()}
        for s in saves_before
    ), saves_before


@pytest.mark.asyncio
async def test_s10_snapshot_never_overwritten(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await r.tick()
    r.view(low=70.0, high=74.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 76.0)]
    r.clock.advance(600)
    await r.tick()
    assert len(r.pr_calls()) == 2
    assert r.coord._s10_snapshots[Z1]["home"]["low"] == 68.0
    assert r.coord._s10_snapshots[Z1]["home"]["high"] == 76.0


@pytest.mark.asyncio
async def test_s10_no_snapshot_when_already_matching(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=74.0)
    await r.tick()
    assert r.pr_calls() == [] and r.coord._s10_snapshots == {}


@pytest.mark.asyncio
async def test_s10_snapshot_save_failure_blocks_write(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.store.raise_next = 1
    await r.tick()
    assert r.pr_calls() == []
    assert r.coord._s10_snapshots == {}
    # The zone's pass STOPS at the failed save: no write-ahead attempt
    # (no further save, no record) this tick.
    assert not any(e[0] == "save" for e in r.events)
    assert r.coord._s10_records == {}


@pytest.mark.asyncio
async def test_s10_write_ahead_save_failure_blocks_write(mods, monkeypatch):
    """The attempt stamp must be persisted before the call (second save)."""
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=74.0)                 # matching -> no snapshot save
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]   # but a DPM value to write
    r.coord._s10_snapshots[Z1] = {"home": {"low": 68.0, "high": 76.0, "captured_iso": "x"}}
    r.store.raise_next = 1
    await r.tick()
    assert r.pr_calls() == []
    assert r.coord._s10_records == {}


@pytest.mark.asyncio
async def test_s10_snapshot_await_gap_never_edits_without_original(mods, monkeypatch):
    """INV snapshot clause (builder hardening): at step 9 the zone is not
    yet confirmed on home (no original); during the write-ahead save it
    becomes confirmed with a differing view -> S10 must NOT edit this tick
    (no original persisted) and captures it first next tick."""
    r = _rig(mods, monkeypatch)
    r.view(hold="away")       # step 9: not confirmed -> original None

    real_save = r.store.async_save

    async def _save_and_settle(data):
        r.view()              # confirmed home, 68/76 during the await
        await real_save(data)
    r.store.async_save = _save_and_settle
    await r.tick()
    assert r.pr_calls() == []
    r.store.async_save = real_save
    r.clock.advance(600)
    await r.tick()
    assert len(r.pr_calls()) == 1
    assert r.coord._s10_snapshots[Z1]["home"]["high"] == 76.0


async def _apply_then_off(r):
    await r.tick()                       # edit home 68/76 -> 70/74
    r.view(low=70.0, high=74.0)          # the device took it
    r.coord.set_custom_ranges_enabled(False, source="user")
    r.clock.advance(600)


@pytest.mark.asyncio
async def test_s10_restore_on_off_current_preset_only(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await _apply_then_off(r)
    r.coord.zone_manager.zones[Z1].preset_mode = "away"
    r.view(preset="away", low=62.0, high=80.0)
    await r.tick()
    assert len(r.pr_calls()) == 1, "a zone on away with only a home original: no call"
    r.coord.zone_manager.zones[Z1].preset_mode = "home"
    r.view(low=70.0, high=74.0)
    r.clock.advance(600)
    await r.tick()
    assert r.pr_calls()[-1] == {"entity_id": E1, "target_temp_low": 68.0, "target_temp_high": 76.0}
    assert r.rows("S10_preset_range_restore")[-1]["reason"] == "restore_carrier_original"


@pytest.mark.asyncio
async def test_s10_restore_confirm_clears_snapshot(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await _apply_then_off(r)
    await r.tick()                       # restore write
    r.view()                             # device back on 68/76
    r.clock.advance(7799)                # one second short of a full read
    await r.tick()
    assert Z1 in r.coord._s10_snapshots
    r.clock.advance(1)
    await r.tick()
    assert Z1 not in r.coord._s10_snapshots
    assert len(r.ledger("s10_original_restored")) == 1
    assert len(r.rows("S10_preset_range_restore")) == 1


@pytest.mark.asyncio
async def test_s10_restore_never_edited_untouched(mods, monkeypatch):
    r = _rig(mods, monkeypatch, flag=False)
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    r.coord.zone_manager.zones[Z1].preset_mode = "sleep"
    r.view(preset="sleep", low=68.0, high=73.0)
    await r.tick(3, step_s=8000)
    assert r.pr_calls() == []


@pytest.mark.asyncio
async def test_s10_restart_on_keeps_snapshots(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await r.tick()
    r.restart()
    r.coord.set_custom_ranges_enabled(True, source="restore_entity")
    assert r.coord._s10_snapshots[Z1]["home"]["high"] == 76.0
    r.view(low=71.0, high=75.0)            # view moved; original must not
    r.overrides[Z1] = [_dpm(Z1, "home", 73.0)]
    r.clock.advance(8000)
    await r.tick()
    assert r.coord._s10_snapshots[Z1]["home"] == {"low": 68.0, "high": 76.0,
                                                 "captured_iso": T0.isoformat()}


@pytest.mark.asyncio
async def test_s10_restart_off_continues_restore(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await _apply_then_off(r)
    r.restart()
    r.coord.set_custom_ranges_enabled(False, source="restore_entity")
    await r.tick()
    assert r.pr_calls()[-1] == {"entity_id": E1, "target_temp_low": 68.0, "target_temp_high": 76.0}


@pytest.mark.asyncio
async def test_s10_restart_keeps_latch(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    for _ in range(4):
        await r.tick()
        r.clock.advance(7800)
    assert r.coord._s10_records[Z1]["home|apply"]["latched"] is True
    n = len(r.pr_calls())
    r.restart()
    r.coord.set_custom_ranges_enabled(True, source="restore_entity")
    await r.tick(3, step_s=8000)
    assert len(r.pr_calls()) == n
    assert r.coord._s10_records[Z1]["home|apply"]["latched"] is True


@pytest.mark.asyncio
async def test_s10_user_toggle_clears_records_keeps_snapshots(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await r.tick()
    assert r.coord._s10_records
    r.coord.set_custom_ranges_enabled(False, source="user")
    assert r.coord._s10_records == {}
    assert r.coord._s10_snapshots[Z1]["home"]["high"] == 76.0
    r.coord.set_custom_ranges_enabled(True, source="user")
    assert r.coord._s10_snapshots[Z1]["home"]["high"] == 76.0


@pytest.mark.asyncio
async def test_s10_restore_entity_path_clears_nothing(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await r.tick()
    before = json.dumps(r.coord._s10_records, sort_keys=True)
    r.coord.set_custom_ranges_enabled(False, source="restore_entity")
    r.coord.set_custom_ranges_enabled(True, source="restore_entity")
    assert json.dumps(r.coord._s10_records, sort_keys=True) == before


@pytest.mark.asyncio
async def test_s10_restore_latch_nm(mods, monkeypatch):
    """The device never takes the original back: exactly 3 restore calls
    (>= 130 min apart), then ONE `s10_restore_not_taking` NM, no 4th call."""
    r = _rig(mods, monkeypatch)
    await _apply_then_off(r)
    for _ in range(6):
        await r.tick()
        r.clock.advance(7800)
    assert len(r.rows("S10_preset_range_restore")) == 3
    assert len(r.nms("s10_restore_not_taking")) == 1
    assert r.coord._s10_records[Z1]["home|restore"]["latched"] is True


@pytest.mark.asyncio
async def test_s10_zone_delete_prunes_memory_and_store(mods, monkeypatch):
    """U7: the zone-delete handler prunes the in-memory S10 state AND the
    persisted side-key; one ledger row lists the dropped originals."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    await r.coord.async_save_zone_state()
    assert Z1 in r.store.data["__s10_preset_ranges"]["snapshots"]
    import custom_components.universal_room_automation.domain_coordinators.hvac as hv
    monkeypatch.setattr(hv, "_compute_surviving_thermostats", lambda *_a, **_k: (set(), True))
    r.coord._handle_zm_zones_updated({"deleted_zone_name": "Zone 1", "deleted_zone_id": Z1})
    await H.drain(r.hass, rounds=6)
    assert Z1 not in r.coord._s10_snapshots and Z1 not in r.coord._s10_records
    blob = r.store.data["__s10_preset_ranges"]
    assert Z1 not in blob["snapshots"] and Z1 not in blob["records"]
    rows = r.ledger("s10_original_dropped_zone_removed")
    assert len(rows) == 1
    assert json.loads(rows[0]["details_json"])["originals"]["home"]["high"] == 76.0


@pytest.mark.asyncio
async def test_s10_side_keys_coexist(mods, monkeypatch):
    """U8: the snapshot carries all six side-keys; the S10 key round-trips
    through rehydrate without touching the other five."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    snap = r.coord._build_zone_state_snapshot()
    for k in ("__person_zone_map", "__short_cycles_today", "__immune_holds",
              "__tao_state", "__interrupt_latch", "__s10_preset_ranges"):
        assert k in snap, k
    r.restart()
    r.coord._rehydrate_s10_state(snap)
    assert r.coord._s10_snapshots[Z1]["home"]["low"] == 68.0
    assert r.coord._s10_records[Z1]["home|apply"]["writes"] == 1


# ==========================================================================
# D4 — rate bound + latch
# ==========================================================================


@pytest.mark.asyncio
async def test_s10_retry_interval_130min(mods, monkeypatch):
    """Same value, device never takes it: the retry waits 7800 s (literal)."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    r.clock.advance(7799)
    await r.tick()
    assert len(r.pr_calls()) == 1
    r.clock.advance(1)
    await r.tick()
    assert len(r.pr_calls()) == 2


@pytest.mark.asyncio
async def test_s10_latch_without_call_at_limit(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    for _ in range(6):
        await r.tick()
        r.clock.advance(7800)
    assert len(r.pr_calls()) == 3
    assert len(r.nms("s10_preset_range_not_sticking")) == 1
    rec = r.coord._s10_records[Z1]["home|apply"]
    assert rec["latched"] is True and rec["latch_reason"] == "not_sticking"


@pytest.mark.asyncio
async def test_s10_failed_counted_separately_own_nm(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.raise_domains.add("ha_carrier")
    for _ in range(6):
        await r.tick()
        r.clock.advance(7800)
    rec = r.coord._s10_records[Z1]["home|apply"]
    assert (rec["failures"], rec["writes"]) == (3, 0)
    assert rec["latch_reason"] == "call_failed"
    assert len(r.nms("s10_preset_range_call_failed")) == 1
    assert r.nms("s10_preset_range_not_sticking") == []
    assert len([e for e in r.events if e[0] == "call"]) == 3


@pytest.mark.asyncio
async def test_s10_value_change_resets_record_but_respects_spacing(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    await r.tick()                                  # writes 74
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    r.clock.advance(599)
    await r.tick()
    assert len(r.pr_calls()) == 1                   # spacing holds at 599 s
    r.clock.advance(1)
    await r.tick()
    assert r.pr_calls()[-1]["target_temp_high"] == 75.0
    rec = r.coord._s10_records[Z1]["home|apply"]
    assert rec["value"] == [70.0, 75.0] and rec["writes"] == 1


@pytest.mark.asyncio
async def test_s10_dwell_zero_flap_bounded_by_spacing(mods, monkeypatch):
    """R5: cool_high flaps 74<->75 every 5-min tick for 30 min (A->B->A):
    calls allowed at t=0, 10, 20, 30 min -> <= 4 wire calls."""
    r = _rig(mods, monkeypatch)
    for i in range(7):            # t = 0, 5, ..., 30 min
        r.overrides[Z1] = [] if i % 2 == 0 else [_dpm(Z1, "home", 75.0)]
        await r.tick()
        r.clock.advance(300)
    assert len(r.pr_calls()) <= 4
    assert len(r.pr_calls()) >= 1


@pytest.mark.asyncio
async def test_s10_restart_storm_no_refire(mods, monkeypatch):
    """8 restarts within an hour, device never takes the value: the
    persisted attempt stamp holds the retry -> ONE call (<= 3 required)."""
    r = _rig(mods, monkeypatch)
    for _ in range(8):
        await r.tick()
        r.restart()
        r.coord.set_custom_ranges_enabled(True, source="restore_entity")
        r.clock.advance(450)
    assert len(r.pr_calls()) == 1


@pytest.mark.asyncio
async def test_s10_write_ahead_save(mods, monkeypatch):
    """§6.2: the record carrying the attempt stamp is persisted BEFORE the
    wire call."""
    r = _rig(mods, monkeypatch)
    await r.tick()
    first_call = [e[0] for e in r.events].index("call")
    stamped = [
        e for e in r.events[:first_call] if e[0] == "save"
        and (e[1].get("__s10_preset_ranges", {}).get("records", {}).get(Z1, {})
             .get("home|apply", {}).get("last_attempt_iso")) == T0.isoformat()
    ]
    assert stamped


# ==========================================================================
# D3c — map retirement (S11 / S13 / pre-arrival / S12 snapshot)
# ==========================================================================


@pytest.mark.asyncio
async def test_s11_baseline_uses_preset_resolved_after_map_retirement(mods, monkeypatch):
    """S11 HUMAN_MANUAL release writes the house-state preset's configured
    (heat, cool) — shoulder Home 70/74 — exactly `_resolve_baseline_range`."""
    r = _rig(mods, monkeypatch)
    ex = mods["hvac_excursion"]
    r.view(preset="manual")
    tok = await ex.begin_excursion(r.hass, zone_id=Z1, entity_id=E1,
                                   kind=ex.EXCURSION_KIND.BANKING, duration_s=None,
                                   site="S12_pre_cool")
    pr = r.coord._predictor
    pr._banking_excursion_tokens = {Z1: tok}
    assert pr._resolve_baseline_range(Z1) == (70.0, 74.0)
    await pr._release_banked_zones({Z1})
    await H.drain(r.hass)
    assert [c[2] for c in r.hass.services.calls if c[1] == "set_temperature"] == [
        {"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 74.0}]
    ex._test_clear_leases()


@pytest.mark.asyncio
async def test_s11_write_reflects_baseline_not_map_pair(mods, monkeypatch):
    """R3 discriminator: a pre-heat return used to plant its snapshot pair
    (61/89) into the map that S11 then wrote. After retirement S11 writes
    the resolved baseline (70/74), NOT (61, 89)."""
    r = _rig(mods, monkeypatch)
    ex, pr = mods["hvac_excursion"], r.coord._predictor
    r.view(preset="manual", low=61.0, high=89.0)
    ph = await ex.begin_excursion(r.hass, zone_id=Z1, entity_id=E1,
                                  kind=ex.EXCURSION_KIND.PREHEAT, excursion_low=63.0,
                                  excursion_high=89.0, duration_s=600, site="S13_pre_heat")
    pr._preheat_excursion_tokens = {Z1: ph}
    pr._preheat_return_timers = {Z1: lambda: None}
    pr._pre_conditioning_zones.add(Z1)
    await pr._return_preheat(Z1)
    await H.drain(r.hass)
    r.hass.services.calls.clear()
    r.view(preset="manual")
    bk = await ex.begin_excursion(r.hass, zone_id=Z1, entity_id=E1,
                                  kind=ex.EXCURSION_KIND.BANKING, duration_s=None,
                                  site="S12_pre_cool")
    pr._banking_excursion_tokens = {Z1: bk}
    # A stale emitted-range pair planted on the coordinator must be ignored.
    r.coord._last_emitted_range = {Z1: (61.0, 89.0)}
    await pr._release_banked_zones({Z1})
    await H.drain(r.hass)
    temps = [c[2] for c in r.hass.services.calls if c[1] == "set_temperature"]
    assert temps == [{"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 74.0}]
    ex._test_clear_leases()


@pytest.mark.asyncio
async def test_s13_return_writes_no_setpoints_after_map_retirement(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    ex, pr = mods["hvac_excursion"], r.coord._predictor
    r.view(preset="home")
    ph = await ex.begin_excursion(r.hass, zone_id=Z1, entity_id=E1,
                                  kind=ex.EXCURSION_KIND.PREHEAT, excursion_low=70.0,
                                  excursion_high=76.0, duration_s=600, site="S13_pre_heat")
    pr._preheat_excursion_tokens = {Z1: ph}
    pr._preheat_return_timers = {Z1: lambda: None}
    pr._pre_conditioning_zones.add(Z1)
    await pr._return_preheat(Z1)
    await H.drain(r.hass)
    assert H.temp_writes(r.hass, E1) == []
    assert H.preset_writes(r.hass, E1, "home")
    assert not hasattr(r.coord, "_last_emitted_range")
    ex._test_clear_leases()


@pytest.mark.asyncio
async def test_pre_arrival_precool_from_baseline_uses_preset_fallback(mods, monkeypatch):
    """U3: the pre-arrival `from_baseline` pre-cool offsets the configured
    cool (74 - 2 = 72), ignoring a planted stale pair (60/90)."""
    r = _rig(mods, monkeypatch)
    r.coord._last_emitted_range = {Z1: (60.0, 90.0)}
    pr = r.coord._predictor
    pr._solar_bank_floor = 60.0
    z = r.coord.zone_manager.zones[Z1]
    z.target_temp_low, z.target_temp_high = 66.0, 80.0
    await pr._execute_zone_pre_cool(z, -2.0, "pre_arrival", from_baseline=True)
    await H.drain(r.hass)
    highs = [c[2]["target_temp_high"] for c in r.hass.services.calls if c[1] == "set_temperature"]
    assert highs == [72.0]
    mods["hvac_excursion"]._test_clear_leases()


@pytest.mark.asyncio
async def test_s12_token_snapshot_uses_preset_fallback_not_map(mods, monkeypatch):
    """U3: the S12 token's pre_target pair is the configured (heat, cool)
    (70, 74), not a planted stale pair."""
    r = _rig(mods, monkeypatch)
    r.coord._last_emitted_range = {Z1: (60.0, 90.0)}
    pr = r.coord._predictor
    pr._solar_bank_floor = 60.0
    z = r.coord.zone_manager.zones[Z1]
    z.target_temp_low, z.target_temp_high = 66.0, 80.0
    await pr._execute_zone_pre_cool(z, -3.0, "energy_precool")
    await H.drain(r.hass)
    tok = pr._banking_excursion_tokens[Z1]
    assert (tok.pre_target_low, tok.pre_target_high) == (70.0, 74.0)
    mods["hvac_excursion"]._test_clear_leases()


# ==========================================================================
# D8 / F1 / R2 / F3 / F8 — tri-state switch resolution
# ==========================================================================


@pytest.mark.asyncio
async def test_custom_preset_ranges_default_is_none_until_resolved(mods, monkeypatch):
    coord, hass = H.make_coord(mods)
    assert coord._guest_mode_actuation_enabled is None


@pytest.mark.asyncio
async def test_s10_no_write_before_switch_resolved(mods, monkeypatch):
    """F1 / T12: cycles 1..3 unresolved -> zero calls; cycle 4 resolves ->
    normal apply."""
    r = _rig(mods, monkeypatch, flag=None)
    await r.tick(3, step_s=900)
    assert r.pr_calls() == [] and r.coord._s10_snapshots == {}
    r.coord.set_custom_ranges_enabled(True, source="restore_entity")
    await r.tick()
    assert len(r.pr_calls()) == 1


@pytest.mark.asyncio
async def test_s10_no_restore_before_switch_resolved(mods, monkeypatch):
    r = _rig(mods, monkeypatch, flag=None)
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    await r.tick(3, step_s=900)
    assert r.pr_calls() == []


@pytest.mark.asyncio
async def test_s10_reload_race_no_restore_when_actually_on(mods, monkeypatch):
    r = _rig(mods, monkeypatch, flag=None)
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    await r.tick()
    assert r.pr_calls() == []
    r.coord.set_custom_ranges_enabled(True, source="deferred_landing_restore_entity")
    await r.tick()
    assert r.rows("S10_preset_range_restore") == []
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 70.0, "target_temp_high": 74.0}]


@pytest.mark.asyncio
async def test_s10_default_off_no_last_state_emits_one_nm(mods, monkeypatch):
    """F1: no-last-state default OFF with pending originals -> ONE info NM
    + one ledger row; a repeat within 24 h (S10_DEFAULT_OFF_NM_GUARD_S) does
    not re-emit; with no originals there is no NM."""
    r = _rig(mods, monkeypatch, flag=None)
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    r.coord.set_custom_ranges_enabled(False, source="no_last_state_default")
    await H.drain(r.hass)
    assert len(r.nms("s10_restart_default_off_restore_pending")) == 1
    assert len(r.ledger("s10_default_off_after_restart")) == 1
    r.coord._guest_mode_actuation_enabled = None
    r.clock.advance(3600)
    r.coord.set_custom_ranges_enabled(False, source="no_last_state_default")
    await H.drain(r.hass)
    assert len(r.nms("s10_restart_default_off_restore_pending")) == 1
    r2 = _rig(mods, monkeypatch, flag=None)
    r2.coord.set_custom_ranges_enabled(False, source="no_last_state_default")
    await H.drain(r2.hass)
    assert r2.nms("s10_restart_default_off_restore_pending") == []


@pytest.mark.asyncio
async def test_custom_preset_ranges_no_last_state_resolves_off_and_nm(mods, monkeypatch):
    r = _rig(mods, monkeypatch, flag=None)
    r.coord._s10_snapshots[Z2] = {"sleep": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    r.coord.set_custom_ranges_enabled(False, source="no_last_state_default")
    await H.drain(r.hass)
    assert r.coord._guest_mode_actuation_enabled is False
    assert r.nms("s10_restart_default_off_restore_pending")[0]["message"] == (
        "URA is putting back the original ranges on 1 presets as each zone next uses them.")


def _fake_call_later(mods, monkeypatch):
    scheduled = []

    def _cl(_hass, delay, cb):
        rec = {"delay": delay, "cb": cb, "cancelled": False, "seq": len(scheduled)}

        def _cancel():
            rec["cancelled"] = True
            rec["cancel_seq"] = len(scheduled)
        rec["cancel"] = _cancel
        scheduled.append(rec)
        return _cancel
    monkeypatch.setattr(mods["hvac"], "async_call_later", _cl)
    return scheduled


@pytest.mark.asyncio
async def test_s10_backstop_resolves_false_after_timeout(mods, monkeypatch):
    """R2: the switch never resolves -> after 300 s (literal) the flag is
    False, one `s10_switch_unresolved_backstop` NM, and the restore pass
    runs next tick."""
    r = _rig(mods, monkeypatch, flag=None)
    sched = _fake_call_later(mods, monkeypatch)
    r.coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    r.coord._arm_cpr_resolution_backstop()
    assert len(sched) == 1 and sched[0]["delay"] == 300
    sched[0]["cb"](None)
    await H.drain(r.hass)
    assert r.coord._guest_mode_actuation_enabled is False
    assert len(r.nms("s10_switch_unresolved_backstop")) == 1
    rows = r.ledger("s10_switch_resolved")
    assert json.loads(rows[0]["details_json"])["source"] == "unresolved_backstop"
    await r.tick()
    assert r.rows("S10_preset_range_restore")


@pytest.mark.asyncio
async def test_s10_backstop_cancelled_when_switch_resolves_earlier(mods, monkeypatch):
    r = _rig(mods, monkeypatch, flag=None)
    sched = _fake_call_later(mods, monkeypatch)
    r.coord._arm_cpr_resolution_backstop()
    r.coord.set_custom_ranges_enabled(True, source="restore_entity")
    assert sched[0]["cancelled"] is True
    assert r.coord._cpr_resolution_backstop_handle is None
    sched[0]["cb"](None)         # a late fire is a no-op
    assert r.coord._guest_mode_actuation_enabled is True
    assert r.nms("s10_switch_unresolved_backstop") == []


@pytest.mark.asyncio
async def test_s10_backstop_not_armed_when_already_resolved(mods, monkeypatch):
    r = _rig(mods, monkeypatch, flag=True)
    sched = _fake_call_later(mods, monkeypatch)
    r.coord._arm_cpr_resolution_backstop()
    assert sched == [] and r.coord._cpr_resolution_backstop_handle is None


async def _drive_setup(mods, monkeypatch):
    """Drive the REAL `HVACCoordinator.async_setup` on a StubHass (pattern
    of test_hvac_live_room_hold_wire_in::test_drain_call_site_in_async_setup_fires_nm)."""
    from runtime_harness import (
        StubBus, StubHass, make_coordinator_manager_entry, make_zone_manager_entry,
    )
    orig_listen = StubBus.async_listen

    def _tolerant_listen(self, event_type, listener, *a, **k):
        return orig_listen(self, event_type, listener)
    monkeypatch.setattr(StubBus, "async_listen", _tolerant_listen)
    zm = make_zone_manager_entry(zones={
        "Test Zone": {"zone_thermostat": "climate.test_zone_1", "zone_rooms": []},
    })
    hass = StubHass(config_entries=[make_coordinator_manager_entry(), zm])
    coord = mods["hvac"].HVACCoordinator(hass)
    coord._zone_state_store = H.FakeStore()
    hass.data.setdefault(mods["const"].DOMAIN, {})
    return coord, hass


@pytest.mark.asyncio
async def test_cpr_r2_backstop_handle_cancelled_on_reload_and_teardown(mods, monkeypatch):
    """REV 5 F8, through the REAL `async_setup` (wire-in anchor): setup arms
    the backstop; a second setup (manager re-enable) cancels the first
    handle BEFORE scheduling the second; teardown cancels the final one."""
    sched = _fake_call_later(mods, monkeypatch)
    coord, hass = await _drive_setup(mods, monkeypatch)
    await coord.async_setup()
    backstops = [s for s in sched if s["delay"] == 300]
    assert len(backstops) == 1 and coord._cpr_resolution_backstop_handle is backstops[0]["cancel"]
    await coord.async_setup()
    backstops = [s for s in sched if s["delay"] == 300]
    assert len(backstops) == 2
    assert backstops[0]["cancelled"] is True
    assert backstops[0]["cancel_seq"] <= backstops[1]["seq"]
    assert coord._cpr_backstop_cancelled_by == "reload"
    await coord.async_teardown()
    assert backstops[1]["cancelled"] is True
    assert coord._cpr_resolution_backstop_handle is None
    assert coord._cpr_backstop_cancelled_by == "teardown"


@pytest.mark.asyncio
async def test_setup_rehydrates_s10_state_before_first_cycle(mods, monkeypatch):
    """Wire-in anchor for `_rehydrate_s10_state` in `async_setup`."""
    _fake_call_later(mods, monkeypatch)
    coord, hass = await _drive_setup(mods, monkeypatch)
    coord._zone_state_store = H.FakeStore({"__s10_preset_ranges": {
        "snapshots": {Z1: {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}},
        "records": {}, "meta": {}}})
    await coord.async_setup()
    assert coord._s10_snapshots[Z1]["home"]["high"] == 77.0
    await coord.async_teardown()


# ---- the switch entity (real class) --------------------------------------


def _switch(mods, monkeypatch, hass, coord, last_state):
    from custom_components.universal_room_automation import switch as switch_mod
    from homeassistant.helpers import dispatcher as _disp
    from homeassistant.helpers.restore_state import RestoreEntity
    connected = []
    monkeypatch.setattr(_disp, "async_dispatcher_connect",
                        lambda _h, sig, cb: connected.append((sig, cb)) or (lambda: None))

    async def _noop(self):
        return None
    monkeypatch.setattr(RestoreEntity, "async_added_to_hass", _noop)
    entry = hass.config_entries.async_entries()[0]
    sw = switch_mod.HVACGuestModeActuationSwitch(hass, entry)
    sw.async_write_ha_state = lambda: None

    async def _last():
        return last_state
    sw.async_get_last_state = _last
    sw._test_connected = connected
    return sw


def _install_manager(hass, mods, coord):
    hass.data[mods["const"].DOMAIN]["coordinator_manager"] = types.SimpleNamespace(
        coordinators={"hvac": coord} if coord is not None else {},
    )


@pytest.mark.asyncio
async def test_switch_is_on_renders_none_as_none(mods, monkeypatch):
    coord, hass = H.make_coord(mods)
    sw = _switch(mods, monkeypatch, hass, coord, None)
    _install_manager(hass, mods, None)
    assert sw.is_on is None
    _install_manager(hass, mods, coord)
    assert sw.is_on is None           # coordinator present but unresolved
    coord._guest_mode_actuation_enabled = False
    assert sw.is_on is False


@pytest.mark.asyncio
@pytest.mark.parametrize("last", ["on", "off"])
async def test_switch_restore_fast_path(mods, monkeypatch, last):
    coord, hass = H.make_coord(mods)
    _install_manager(hass, mods, coord)
    sw = _switch(mods, monkeypatch, hass, coord, types.SimpleNamespace(state=last))
    await sw.async_added_to_hass()
    await H.drain(hass)
    assert coord._guest_mode_actuation_enabled is (last == "on")
    rows = [r for r in hass.data[mods["const"].DOMAIN]["database"].rows
            if r.get("action") == "s10_switch_resolved"]
    assert json.loads(rows[0]["details_json"])["source"] == "restore_entity"
    assert sw._test_connected and sw._test_connected[0][1] == sw._handle_hvac_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [None, "unavailable", "unknown"])
async def test_switch_restore_unavailable_last_state_resolves_false(mods, monkeypatch, saved):
    """REV 5 F3 (Bug Class #52): no saved state / `unavailable` / `unknown`
    resolves OFF with source `no_last_state_default` — never ON."""
    coord, hass = H.make_coord(mods)
    _install_manager(hass, mods, coord)
    last = None if saved is None else types.SimpleNamespace(state=saved)
    sw = _switch(mods, monkeypatch, hass, coord, last)
    await sw.async_added_to_hass()
    await H.drain(hass)
    assert coord._guest_mode_actuation_enabled is False
    rows = [r for r in hass.data[mods["const"].DOMAIN]["database"].rows
            if r.get("action") == "s10_switch_resolved"]
    assert json.loads(rows[0]["details_json"])["source"] == "no_last_state_default"


@pytest.mark.asyncio
async def test_switch_no_last_state_deferred_lands_false_via_ready_signal(mods, monkeypatch):
    """REV 5 F3: the coordinator is not registered at load -> deferred; the
    READY signal lands OFF with `deferred_landing_no_last_state_default`,
    and the NM + ledger row are emitted at the LANDING instant."""
    coord, hass = H.make_coord(mods)
    coord._s10_snapshots[Z1] = {"home": {"low": 66.0, "high": 77.0, "captured_iso": "x"}}
    _install_manager(hass, mods, None)
    sw = _switch(mods, monkeypatch, hass, coord, None)
    await sw.async_added_to_hass()
    await H.drain(hass)
    notes = hass.data[mods["const"].DOMAIN]["notification_manager"].notes
    assert coord._guest_mode_actuation_enabled is None and notes == []
    _install_manager(hass, mods, coord)
    sw._handle_hvac_ready()
    await H.drain(hass)
    assert coord._guest_mode_actuation_enabled is False
    rows = [r for r in hass.data[mods["const"].DOMAIN]["database"].rows
            if r.get("action") == "s10_switch_resolved"]
    assert json.loads(rows[0]["details_json"])["source"] == "deferred_landing_no_last_state_default"
    assert [n["hazard_type"] for n in notes] == ["s10_restart_default_off_restore_pending"]
    assert sw._deferred_value is None


@pytest.mark.asyncio
async def test_switch_deferred_restore_entity_on_lands_true(mods, monkeypatch):
    coord, hass = H.make_coord(mods)
    _install_manager(hass, mods, None)
    sw = _switch(mods, monkeypatch, hass, coord, types.SimpleNamespace(state="on"))
    await sw.async_added_to_hass()
    _install_manager(hass, mods, coord)
    sw._handle_hvac_ready()
    assert coord._guest_mode_actuation_enabled is True


@pytest.mark.asyncio
async def test_switch_user_toggle_routes_through_coordinator(mods, monkeypatch):
    coord, hass = H.make_coord(mods)
    _install_manager(hass, mods, coord)
    sw = _switch(mods, monkeypatch, hass, coord, None)
    coord._guest_mode_actuation_enabled = True
    coord._s10_records = {Z1: {"home|apply": {"value": [70.0, 74.0], "latched": True}}}
    coord._s10_snapshots = {Z1: {"home": {"low": 68.0, "high": 76.0, "captured_iso": "x"}}}
    await sw.async_turn_off()
    await H.drain(hass)
    assert coord._guest_mode_actuation_enabled is False
    assert coord._s10_records == {} and coord._s10_snapshots[Z1]
    notes = hass.data[mods["const"].DOMAIN]["notification_manager"].notes
    assert notes[-1]["hazard_type"] == "s10_restore_pending"
    await sw.async_turn_on()
    assert coord._guest_mode_actuation_enabled is True


@pytest.mark.asyncio
async def test_switch_unique_id_and_name_unchanged(mods, monkeypatch):
    """DoD 7 conversion of test_v472 `test_unique_id_unchanged`."""
    coord, hass = H.make_coord(mods)
    sw = _switch(mods, monkeypatch, hass, coord, None)
    assert sw.unique_id == f"{mods['const'].DOMAIN}_hvac_coordinator_guest_mode_actuation_enabled"
    assert sw.name == "01 · Custom Preset Ranges"


# ---- the diagnostics sensor ------------------------------------------------


def _sensor(mods, hass):
    from custom_components.universal_room_automation import sensor as sensor_mod
    entry = hass.config_entries.async_entries()[0]
    return sensor_mod.HVACActivePresetOverridesSensor(hass, entry)


@pytest.mark.asyncio
async def test_sensor_renders_none_as_unknown_not_true(mods, monkeypatch):
    r = _rig(mods, monkeypatch, flag=None)
    r.hass.data[r.DOMAIN]["coordinator_manager"].coordinators["hvac"] = r.coord
    s = _sensor(mods, r.hass)
    assert s.extra_state_attributes["master_enabled"] == "unknown"
    assert s.native_value == 0
    r.coord._guest_mode_actuation_enabled = True
    assert s.extra_state_attributes["master_enabled"] is True


@pytest.mark.asyncio
async def test_active_preset_overrides_sensor_exposes_s10_record_and_originals(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.hass.data[r.DOMAIN]["coordinator_manager"].coordinators["hvac"] = r.coord
    await r.tick()
    attrs = _sensor(mods, r.hass).extra_state_attributes
    home = attrs["preset_range_by_zone"][Z1]["home"]
    assert (home["desired_low"], home["desired_high"], home["writes"], home["status"]) == (
        70.0, 74.0, 1, "applied")
    assert attrs["originals_pending_restore"][Z1]["home"]["high"] == 76.0


# ==========================================================================
# D5 — text
# ==========================================================================


_JARGON = ("DPM", "override", "hold", "throttle", "S10", "latch")


@pytest.mark.asyncio
async def test_label_no_jargon_s10_strings(mods, monkeypatch):
    """Every S10 NM produced by the real paths + the new UI strings are
    jargon-free (label style guide)."""
    r = _rig(mods, monkeypatch)
    z = r.coord.zone_manager.zones[Z1]
    S = mods["hvac_strategy"]
    for mode, reason in (("apply", "not_sticking"), ("apply", "call_failed"),
                         ("restore", "not_sticking")):
        r.coord._s10_latch(Z1, z, "home", mode, {"value": [70.0, 74.0]}, reason,
                           [70.0, 74.0], S.CarrierStrategy())
    r.coord._s10_snapshots[Z1] = {"home": {"low": 68.0, "high": 76.0, "captured_iso": "x"}}
    r.coord.set_custom_ranges_enabled(False, source="user")
    r.coord._guest_mode_actuation_enabled = None
    r.coord.set_custom_ranges_enabled(False, source="no_last_state_default")
    r.coord._guest_mode_actuation_enabled = None
    r.coord.set_custom_ranges_enabled(False, source="unresolved_backstop")
    await H.drain(r.hass)
    texts = [n["title"] for n in r.nms()] + [n["message"] for n in r.nms()]
    assert len(r.nms()) == 6
    root = os.path.abspath(os.path.join(_HERE, "..", ".."))
    for f in ("custom_components/universal_room_automation/strings.json",
              "custom_components/universal_room_automation/translations/en.json"):
        data = json.load(open(os.path.join(root, f)))
        step = data["options"]["step"]
        texts.append(step["hvac_baseline_presets"]["description"])
        texts.append(step["hvac_baseline_presets"]["data"][ROLLOUT_KEY])
        texts.append(step["hvac_baseline_presets"]["data_description"][ROLLOUT_KEY])
        texts.append(step["hvac_dynamic_preset"]["data_description"]["dynamic_preset_enabled"])
    for t in texts:
        for word in _JARGON:
            assert word.lower() not in t.lower(), (word, t)


def test_s10_strings_translation_parity():
    root = os.path.abspath(os.path.join(_HERE, "..", ".."))
    a = json.load(open(os.path.join(root, "custom_components/universal_room_automation/strings.json")))
    b = json.load(open(os.path.join(
        root, "custom_components/universal_room_automation/translations/en.json")))
    for key in ("hvac_baseline_presets", "hvac_dynamic_preset"):
        assert a["options"]["step"][key] == b["options"]["step"][key]


# ==========================================================================
# Row-1 / D7 routing (DoD 7 conversion of a broken source-count grep)
# ==========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("retreat_ok,expect_away", [
    ((True, True), True),      # row-1 retreats, D7 lets `away` stand
    ((False, False), False),   # row-1 does not retreat
    ((True, False), False),    # row-1 retreats, D7 (person home) keeps the preset
])
async def test_row1_and_d7_route_through_retreat_helper(mods, monkeypatch, retreat_ok, expect_away):
    """Row-1's vacancy retreat (and D7's night trust, evaluated with it in
    `sleep`) decide through `_zone_conditioning_retreat_ok`: the helper's
    answer alone flips whether an empty `sleep` zone with a person home is
    sent away."""
    r = _rig(mods, monkeypatch, house="sleep")
    c = r.coord
    c._zone_intelligence_enabled = True
    c._boot_settle_done = True
    for zid in (Z1, Z2, Z3):
        c.zone_manager.zones[zid].preset_mode = "sleep"
    for e in (E1, E2, E3):
        r.view(e, preset="sleep")
    z = c.zone_manager.zones[Z1]
    z.last_occupied_time = T0 - timedelta(hours=3)   # the rig clock's frame
    z.zone_persons = ["person.a"]
    r.hass.states.async_set("person.a", "home", {})
    calls = []

    def _spy(zone):
        # Per zone: 1st consult = row-1, 2nd = D7 (same pass order).
        n = sum(1 for zid in calls if zid == zone.zone_id)
        calls.append(zone.zone_id)
        return retreat_ok[min(n, 1)] if zone.zone_id == Z1 else False
    monkeypatch.setattr(c, "_zone_conditioning_retreat_ok", _spy)
    await c._apply_house_state_presets()
    await H.drain(r.hass)
    assert calls.count(Z1) == (2 if retreat_ok[0] else 1)
    assert bool(H.preset_writes(r.hass, E1, "away")) is expect_away


# ==========================================================================
# REV 5 F6 — the rung-2 rollout field in the REAL options flow
# ==========================================================================


def _cm_options_flow(options, zones):
    from custom_components.universal_room_automation import config_flow as _cf
    from custom_components.universal_room_automation.const import DOMAIN

    class _Entry:
        entry_id = "cm"
        data = {"entry_type": "coordinator_manager"}

        def __init__(self, opts):
            self.options = dict(opts)

    flow = _cf.UniversalRoomAutomationOptionsFlow(_Entry(options))
    hvac = types.SimpleNamespace(zone_manager=types.SimpleNamespace(zones={
        zid: types.SimpleNamespace(zone_name=name) for zid, name in zones.items()
    }))
    hass = types.SimpleNamespace(data={DOMAIN: {"coordinator_manager": types.SimpleNamespace(
        coordinators={"hvac": hvac})}})
    flow.hass = hass
    return flow


def _rollout_field(result):
    for marker, value in result["data_schema"].schema.items():
        if getattr(marker, "schema", None) == ROLLOUT_KEY:
            default = marker.default() if callable(marker.default) else marker.default
            return default, [o["value"] for o in value.config["options"]], value.config
    raise AssertionError("rollout field not on the Baseline Presets form")


def test_rollout_field_renders_discovered_zones_and_default_empty():
    flow = _cm_options_flow({}, {Z1: "Entertainment", Z3: "Back Hallway"})
    default, opts, cfg = _rollout_field(asyncio.run(flow.async_step_hvac_baseline_presets(None)))
    assert default == [] and opts == [Z1, Z3]
    assert cfg["multiple"] is True and cfg["custom_value"] is True


def test_rollout_field_keeps_a_stored_undiscovered_zone_and_saves_sorted():
    flow = _cm_options_flow({ROLLOUT_KEY: ["zone_9"]}, {Z1: "Entertainment"})
    default, opts, _ = _rollout_field(asyncio.run(flow.async_step_hvac_baseline_presets(None)))
    assert default == ["zone_9"] and "zone_9" in opts
    saved = {}

    def _create(*, title, data):
        saved.update(data)
        return {"type": "create_entry", "data": data}
    flow.async_create_entry = _create
    asyncio.run(flow.async_step_hvac_baseline_presets({ROLLOUT_KEY: [" zone_3 ", Z1, "zone_3", ""]}))
    assert saved[ROLLOUT_KEY] == [Z1, Z3]


# ==========================================================================
# Fix-up pass (review round 1): D-HIGH-1 / M45 / M39 / B1 + recommended
# ==========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("orig_high,dpm_high,wire_high", [(76.0, 76.5, 77.0), (73.0, 73.5, 74.0)])
async def test_s10_half_degree_desired_snapshots_before_write(
    mods, monkeypatch, orig_high, dpm_high, wire_high,
):
    """D-HIGH-1 (step-9 gate): the device holds 70/<orig_high>; the DPM
    asks for <orig_high>+0.5. Carrier rounds half up, so the wire gets
    <wire_high> — a real edit. The original MUST be persisted before that
    call (old gate compared the UNROUNDED 0.5 diff with `> 0.5` -> no
    snapshot, an edit with no original)."""
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=orig_high)
    r.overrides[Z1] = [_dpm(Z1, "home", dpm_high)]
    await r.tick()
    assert r.pr_calls() == [{"entity_id": E1, "target_temp_low": 70.0,
                             "target_temp_high": wire_high}]
    first_call = [e[0] for e in r.events].index("call")
    saves_before = [e[1] for e in r.events[:first_call] if e[0] == "save"]
    assert any(
        s.get("__s10_preset_ranges", {}).get("snapshots", {}).get(Z1, {}).get("home")
        == {"low": 70.0, "high": orig_high, "captured_iso": T0.isoformat()}
        for s in saves_before
    ), saves_before


@pytest.mark.asyncio
async def test_s10_half_degree_recheck_after_await_never_edits_without_original(
    mods, monkeypatch,
):
    """D-HIGH-1 (B2 re-check site): at step 9 the zone is not confirmed (no
    original); during the write-ahead save it becomes confirmed at 70/76
    while URA wants 76.5 (wire 77). The re-check must stand down."""
    r = _rig(mods, monkeypatch)
    r.view(hold="away", low=70.0, high=76.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 76.5)]
    real_save = r.store.async_save

    async def _save_and_settle(data):
        r.view(low=70.0, high=76.0)
        await real_save(data)
    r.store.async_save = _save_and_settle
    await r.tick()
    assert r.pr_calls() == []
    assert Z1 not in r.coord._s10_snapshots


@pytest.mark.asyncio
async def test_s10_half_degree_exact_match_no_snapshot_no_call(mods, monkeypatch):
    """Control for the would-write compare: device 70/77, desired 76.5 ->
    the wire value (77) equals the original -> no snapshot, no call."""
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=77.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 76.5)]
    await r.tick()
    assert r.pr_calls() == [] and r.coord._s10_snapshots == {}


@pytest.mark.asyncio
async def test_preset_range_would_write_carrier_and_generic(mods, monkeypatch):
    st = mods["hvac_strategy"]
    assert st.CarrierStrategy().preset_range_would_write(70.0, 76.5) == (70, 77)
    assert st.CarrierStrategy().preset_range_would_write(69.4, 73.5) == (69, 74)
    assert st.GenericStrategy().preset_range_would_write(70.0, 76.5) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("obs_mode", [True, False])
async def test_s10_observation_mode_gate_at_call_site(mods, monkeypatch, obs_mode):
    """M45: through `_apply_house_state_presets` with switch 01 ON, zone_1
    in the rollout and a differing range — observation mode ON makes ZERO
    set_activity_setpoint calls and ZERO climate_write rows; OFF (control)
    makes exactly one."""
    r = _rig(mods, monkeypatch)
    r.coord._observation_mode = obs_mode
    await r.coord._apply_house_state_presets()
    await H.drain(r.hass)
    if obs_mode:
        assert r.pr_calls() == []
        assert r.rows("S10_preset_range") == []
        assert r.coord._s10_snapshots == {}
    else:
        assert len(r.pr_calls()) == 1
        assert len(r.rows("S10_preset_range")) == 1


@pytest.mark.asyncio
async def test_s10_restore_confirm_clears_apply_record(mods, monkeypatch):
    """M39: a restore-entity OFF keeps the apply record; the restore
    confirmation clears BOTH the restore and the apply record."""
    r = _rig(mods, monkeypatch)
    await r.tick()                                   # edit home 68/76 -> 70/74
    r.view(low=70.0, high=74.0)
    assert "home|apply" in r.coord._s10_records[Z1]
    r.coord.set_custom_ranges_enabled(False, source="restore_entity")
    assert "home|apply" in r.coord._s10_records[Z1]  # restore_entity clears nothing
    r.clock.advance(600)
    await r.tick()                                   # restore write
    r.view()                                         # device back on 68/76
    r.clock.advance(7800)
    await r.tick()                                   # confirm
    assert Z1 not in r.coord._s10_snapshots
    assert r.coord._s10_records == {}


# ---- pre-call re-checks after the write-ahead await (D-LOW-1 / B3 / B4) ----


def _during_save(r, fn, *, nth=1):
    real_save = r.store.async_save
    seen = {"n": 0}

    async def _save(data):
        seen["n"] += 1
        if seen["n"] == nth:
            fn()
        await real_save(data)
    r.store.async_save = _save


@pytest.mark.asyncio
async def test_s10_switch_off_during_save_no_apply_call(mods, monkeypatch):
    """D-LOW-1: the switch resolves OFF (restore_entity) while the apply
    attempt is being saved -> no apply call; the stamp is undone."""
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=76.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    r.coord._s10_snapshots[Z1] = {"home": {"low": 70.0, "high": 76.0, "captured_iso": "x"}}
    _during_save(r, lambda: r.coord.set_custom_ranges_enabled(False, source="restore_entity"))
    await r.tick()
    assert r.pr_calls() == []
    assert r.rows("S10_preset_range") == []
    assert r.coord._s10_records == {}


@pytest.mark.asyncio
async def test_s10_zone_removed_during_save_no_call(mods, monkeypatch):
    """B3: the zone leaves URA while the attempt is saved -> no call."""
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=76.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    r.coord._s10_snapshots[Z1] = {"home": {"low": 70.0, "high": 76.0, "captured_iso": "x"}}
    _during_save(r, lambda: r.coord.zone_manager._zones.pop(Z1))
    await r.tick()
    assert r.pr_calls() == []


@pytest.mark.asyncio
async def test_s10_person_protected_during_save_no_call(mods, monkeypatch):
    """B4: the zone becomes person-protected while the attempt is saved ->
    the skip matrix re-run right before the call stands down."""
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=76.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    r.coord._s10_snapshots[Z1] = {"home": {"low": 70.0, "high": 76.0, "captured_iso": "x"}}
    _during_save(r, lambda: monkeypatch.setattr(
        r.arr, "_corrective_writes_suppressed", lambda zid: zid == Z1))
    await r.tick()
    assert r.pr_calls() == []


# ---- D-LOW-2: a user toggle during an await never gets a record written back


def _toggle_off_on(r):
    r.coord.set_custom_ranges_enabled(False, source="user")
    r.coord.set_custom_ranges_enabled(True, source="user")


@pytest.mark.asyncio
async def test_s10_user_toggle_during_snapshot_save_writes_no_record(mods, monkeypatch):
    r = _rig(mods, monkeypatch)                      # 68/76 -> snapshot save first
    _during_save(r, lambda: _toggle_off_on(r), nth=1)
    await r.tick()
    assert r.coord._s10_records == {}
    assert r.pr_calls() == []
    assert r.coord._s10_snapshots[Z1]["home"]["high"] == 76.0


@pytest.mark.asyncio
async def test_s10_user_toggle_during_attempt_save_writes_no_record(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=76.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    r.coord._s10_snapshots[Z1] = {"home": {"low": 70.0, "high": 76.0, "captured_iso": "x"}}
    _during_save(r, lambda: _toggle_off_on(r), nth=1)
    await r.tick()
    assert r.coord._s10_records == {}
    assert r.pr_calls() == []


@pytest.mark.asyncio
async def test_s10_user_toggle_during_wire_call_writes_no_record(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.view(low=70.0, high=76.0)
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    r.coord._s10_snapshots[Z1] = {"home": {"low": 70.0, "high": 76.0, "captured_iso": "x"}}
    inner = r.hass.services.async_call

    async def _svc(domain, service, service_data=None, blocking=False, **kw):
        if domain == "ha_carrier":
            _toggle_off_on(r)
        return await inner(domain, service, service_data, blocking=blocking, **kw)
    r.hass.services.async_call = _svc
    await r.tick()
    assert len(r.pr_calls()) == 1
    assert r.coord._s10_records == {}


# ---- A2 / B2 / B5 ---------------------------------------------------------


@pytest.mark.asyncio
async def test_s10_rehydrate_one_malformed_original_keeps_the_others(mods, monkeypatch):
    r = _rig(mods, monkeypatch)
    r.coord._rehydrate_s10_state({"__s10_preset_ranges": {"snapshots": {
        Z1: {"home": {"low": 68.0, "high": 76.0, "captured_iso": "x"},
             "sleep": {"low": "not-a-number", "high": 75.0}},
        Z2: {"away": {"low": 62.0, "high": 80.0, "captured_iso": "y"}},
    }, "records": {}, "meta": {}}})
    assert r.coord._s10_snapshots == {
        Z1: {"home": {"low": 68.0, "high": 76.0, "captured_iso": "x"}},
        Z2: {"away": {"low": 62.0, "high": 80.0, "captured_iso": "y"}},
    }


@pytest.mark.asyncio
async def test_s10_default_off_nm_reevaluated_after_rehydrate(mods, monkeypatch):
    """B2: the switch resolves default-OFF BEFORE the originals are
    rehydrated (zero snapshots -> no NM); rehydrating one original then
    sends the ONE default-off NM + ledger row."""
    r = _rig(mods, monkeypatch, flag=None)
    r.coord.set_custom_ranges_enabled(False, source="no_last_state_default")
    await H.drain(r.hass)
    assert r.nms("s10_restart_default_off_restore_pending") == []
    r.coord._rehydrate_s10_state({"__s10_preset_ranges": {"snapshots": {
        Z1: {"home": {"low": 68.0, "high": 76.0, "captured_iso": "x"}}},
        "records": {}, "meta": {}}})
    await H.drain(r.hass)
    assert len(r.nms("s10_restart_default_off_restore_pending")) == 1
    assert len(r.ledger("s10_default_off_after_restart")) == 1


@pytest.mark.asyncio
async def test_s10_rehydrate_after_restore_entity_off_sends_no_default_nm(mods, monkeypatch):
    """B2 control: an explicit saved OFF is not the default -> no NM."""
    r = _rig(mods, monkeypatch, flag=None)
    r.coord.set_custom_ranges_enabled(False, source="restore_entity")
    r.coord._rehydrate_s10_state({"__s10_preset_ranges": {"snapshots": {
        Z1: {"home": {"low": 68.0, "high": 76.0, "captured_iso": "x"}}},
        "records": {}, "meta": {}}})
    await H.drain(r.hass)
    assert r.nms("s10_restart_default_off_restore_pending") == []


@pytest.mark.asyncio
async def test_s10_switch_resolved_row_has_no_stale_cancelled_by(mods, monkeypatch):
    """B5: a cancel left over from an earlier reload is not reported as
    this resolution's `handle_cancelled_by`."""
    r = _rig(mods, monkeypatch, flag=None)
    r.coord._cpr_backstop_cancelled_by = "reload"     # stale, no live handle
    r.coord.set_custom_ranges_enabled(True, source="restore_entity")
    await H.drain(r.hass)
    rows = r.ledger("s10_switch_resolved")
    assert json.loads(rows[-1]["details_json"])["handle_cancelled_by"] is None


# ---- B1: a rebuilt coordinator re-lands from the switch's own state ---------


@pytest.mark.asyncio
@pytest.mark.parametrize("path,expect", [
    ("fast_on", True), ("fast_off", False), ("user_off", False), ("user_on", True),
    ("deferred_on", True),
])
async def test_switch_relands_on_rebuilt_coordinator(mods, monkeypatch, path, expect):
    """B1: an integration-entry reload rebuilds the HVAC coordinator without
    re-adding the switch. On READY the new coordinator (unresolved) gets the
    switch's last value with source `deferred_landing_restore_entity` — no
    backstop OFF, no restore pass."""
    coord, hass = H.make_coord(mods)
    saved = {"fast_on": "on", "fast_off": "off", "user_off": "on",
             "user_on": "off", "deferred_on": "on"}[path]
    if path == "deferred_on":
        _install_manager(hass, mods, None)
    else:
        _install_manager(hass, mods, coord)
    sw = _switch(mods, monkeypatch, hass, coord, types.SimpleNamespace(state=saved))
    await sw.async_added_to_hass()
    if path == "deferred_on":
        _install_manager(hass, mods, coord)
        sw._handle_hvac_ready()
    elif path == "user_off":
        await sw.async_turn_off()
    elif path == "user_on":
        await sw.async_turn_on()
    await H.drain(hass)
    assert coord._guest_mode_actuation_enabled is expect
    coord2 = mods["hvac"].HVACCoordinator(hass)
    assert coord2._guest_mode_actuation_enabled is None
    _install_manager(hass, mods, coord2)
    sw._handle_hvac_ready()
    await H.drain(hass)
    assert coord2._guest_mode_actuation_enabled is expect
    rows = [x for x in hass.data[mods["const"].DOMAIN]["database"].rows
            if x.get("action") == "s10_switch_resolved"]
    assert json.loads(rows[-1]["details_json"])["source"] == "deferred_landing_restore_entity"
    # A READY on an already-resolved coordinator never overrides it.
    coord2._guest_mode_actuation_enabled = not expect
    sw._handle_hvac_ready()
    assert coord2._guest_mode_actuation_enabled is (not expect)


@pytest.mark.asyncio
async def test_switch_ready_with_nothing_resolved_does_nothing(mods, monkeypatch):
    coord, hass = H.make_coord(mods)
    _install_manager(hass, mods, coord)
    sw = _switch(mods, monkeypatch, hass, coord, None)
    sw._handle_hvac_ready()
    assert coord._guest_mode_actuation_enabled is None


@pytest.mark.asyncio
async def test_active_preset_overrides_sensor_low_side_is_configured_heat(mods, monkeypatch):
    """D-LOW-3: the display's resolved low side is the configured heat for
    the preset (shoulder Home heat 70, what S10 writes), never `cool - 7`
    (74 - 7 = 67)."""
    r = _rig(mods, monkeypatch)
    r.hass.data[r.DOMAIN]["coordinator_manager"].coordinators["hvac"] = r.coord
    r.overrides[Z1] = [_dpm(Z1, "home", 75.0)]
    attrs = _sensor(mods, r.hass).extra_state_attributes
    assert attrs["resolved_ranges"][Z1]["cool_low"] == 70.0
    assert attrs["resolved_ranges"][Z1]["cool_high"] == 75.0

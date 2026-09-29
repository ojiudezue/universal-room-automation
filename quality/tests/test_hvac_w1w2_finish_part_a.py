"""HVAC W1/W2 finish — PART A: a person's change ends a non-nudge borrow.

Plan: docs/planning/PLANNING_hvac_w1_w2_finish.md REV 2 + §8 rulings Q1-Q6 +
the Q7 ruling (a pre-arrival interrupt reverts to the house's CURRENT S1
target, not the pre-borrow snapshot).

Falsifiable invariants under test (plan §A.1):

INV-A  If D1 classifies a change on zone Z at time t as HUMAN (both states
       `heat_cool`, manual -> manual, legs numeric, outside suppression, no
       match among URA's last 4 setpoint writes) — or a transition INTO
       manual whose changed legs match no recent URA write — and a BANKING,
       PREHEAT or COMPROMISE borrow B is live on Z (owned or ownerless),
       then until Z next leaves `manual`:
         1. no `set_temperature` / `set_preset_mode` carries B's id after t;
         2. no S12 / S13 write lands on Z;
         3. B ends with trigger `human_interrupt` and restore_ok = None.
       Allowed writes: S1 under the §9e gates; the arrester's S3/S4 for the
       NEW episode; S5 nudges / hard resets; egress mode writes; the
       heat_cool enforcer.
INV-A4 (D13) With a nudge live, the change is booked `nudge_win`, the nudge
       is not ended, no arrester timer is created.
INV-A5 A URA `set_temperature` echo matching one of URA's last 4 writes is
       never booked HUMAN; a mode change (either side not `heat_cool`) is
       never booked HUMAN by D1.
D6     The boot audit never pins `manual` for a NUDGE row.

Drives the REAL `OverrideArrester` / `HVACPredictor` / excursion primitive on
the smoke StubHass (W1-B harness). Timers go through a fake
`async_call_later` fired by hand; writes are read off `hass.services.calls`.
Oracles are hand-typed literals (the fixture classes come from probe P1).
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

FIXTURE = os.path.join(_HERE, "fixtures", "hvac_09_28_zone2_prearrival.json")

Z1, E1 = "zone_1", "climate.test_zone_1"
Z2, E2 = "zone_2", "climate.test_zone_2"

# Hand-typed seasonal profiles (independent oracle for the resolver).
# `sleep` deliberately differs from `home` so a case-B / case-C mix-up can
# never pass by coincidence (Bug Class #63).
SEASONAL = {"home": (76.0, 70.0), "away": (80.0, 68.0), "sleep": (78.0, 66.0)}


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    m = H.load_real()
    yield m
    # Leave no residue in module-global registries for later files.
    m["hvac_excursion"]._test_clear_leases()
    m["hvac_setpoint"]._test_clear_ura_setpoints()


@pytest.fixture
def expected_lingering_timers():
    return True


class FakeScheduler:
    """Stand-in for `async_call_later`: records (delay, cb), fired by hand."""

    def __init__(self):
        self.pending: list[list] = []

    def __call__(self, hass, delay, cb):
        rec = [float(delay), cb, False]
        self.pending.append(rec)

        def _cancel():
            rec[2] = True
        return _cancel

    def live(self):
        return [r for r in self.pending if not r[2]]


class PersistDB(H.FakeDB):
    """Excursion persistence that actually persists (boot-audit replays)
    and records event rows. ``save_hook`` (async) runs INSIDE
    `begin_excursion`'s save await — the M1 race window."""

    def __init__(self):
        super().__init__()
        self.state: dict[str, dict] = {}
        self.events: list[dict] = []
        self.save_hook = None

    async def save_excursion_row(self, row):
        self.state[row["zone_id"]] = dict(row)
        if self.save_hook is not None:
            hook, self.save_hook = self.save_hook, None
            await hook(row)

    async def clear_excursion_row(self, zone_id):
        self.state.pop(zone_id, None)

    async def get_all_excursion_rows(self):
        return [dict(r) for r in self.state.values()]

    async def log_excursion_event(self, **kw):
        self.events.append(dict(kw))


def _setup(mods, monkeypatch, *, house_state="home_night", db=None,
           zone=Z2, preset="manual", low=68.0, high=74.0):
    coord, hass = H.make_coord(mods)
    coord._house_state = house_state
    coord._zone_intelligence_enabled = True
    mods["hvac_setpoint"]._test_clear_ura_setpoints()
    pm = coord._preset_manager
    monkeypatch.setattr(pm, "get_seasonal_setpoints",
                        lambda p, season=None: SEASONAL.get(p))
    pm._current_season = "summer"
    arr = coord._override_arrester
    arr.enabled = True
    sched = FakeScheduler()
    monkeypatch.setattr(mods["hvac_override"], "async_call_later", sched)
    monkeypatch.setattr(mods["hvac_predict"], "async_call_later", sched)
    ex = mods["hvac_excursion"]
    db = db if db is not None else PersistDB()
    ex._test_bind(hass=hass, db=db)
    z = coord.zone_manager.zones[zone]
    z.target_temp_low, z.target_temp_high = low, high
    z.preset_mode = preset
    H.set_climate(hass, z.climate_entity, preset_mode=preset,
                  hold_activity=preset, low=low, high=high)
    return coord, hass, arr, sched, db


def _occ(mods, coord, zid, *, lighting=False, hvac=False):
    """Zone occupancy flags are derived from `room_conditions`."""
    RC = mods["hvac_zones"].RoomCondition
    coord.zone_manager.zones[zid].room_conditions = [
        RC(room_name=f"r_{zid}", occupied=lighting, hvac_occupied=hvac)]


def _ev(ent, old, new, *, old_state="heat_cool", new_state="heat_cool"):
    """old/new = (preset, low, high)."""
    return H.make_event(ent, old_preset=old[0], new_preset=new[0],
                        old_low=old[1], old_high=old[2],
                        new_low=new[1], new_high=new[2],
                        old_state=old_state, new_state=new_state)


def _od_rows(hass, mods):
    return hass.data[mods["const"].DOMAIN]["activity_logger"].actions("override_detected")


def _temp_writes(hass, ent, site=None):
    return [c for c in H.temp_writes(hass, ent)]


def _cw_rows(hass, mods, site=None):
    return H.climate_write_rows(hass, mods, site)


async def _fire(hass, arr, ev):
    arr._handle_climate_change(ev)
    await H.drain(hass, rounds=6)


def _seed(mods, zone, kind, *, pre_preset="away", site="S12_pre_cool", duration_s=None):
    ex = mods["hvac_excursion"]
    return ex._test_seed_row(zone_id=zone, kind=getattr(ex.EXCURSION_KIND, kind),
                             duration_s=duration_s, pre_preset=pre_preset, site=site)


# ==========================================================================
# D1 — the within-manual classifier (pure) + the funnel record
# ==========================================================================


def _state(row):
    return types.SimpleNamespace(
        state=row["state"],
        attributes={"preset_mode": row["preset_mode"],
                    "target_temp_low": row["low"], "target_temp_high": row["high"]},
    )


def _ring_at(fx, ts):
    t = datetime.fromisoformat(ts)
    ws = [w for w in fx["ura_writes"] if datetime.fromisoformat(w["ts"]) <= t]
    return [(w["low"], w["high"]) for w in ws][-4:]


def test_classify_within_manual_fixture_09_28(mods):
    """Every consecutive recorder pair of the 09-28 22:03-22:16 zone_2 trace
    is classified exactly as probe P1 classified it (L1). 22:15:40 -> human."""
    fx = json.load(open(FIXTURE))
    cls = mods["hvac_override"].classify_manual_setpoint_change
    got = []
    for rows in (fx["rows"], fx["rows_23_03"]):
        for prev, cur in zip(rows, rows[1:]):
            got.append((cur["ts"], cls(_state(prev), _state(cur),
                                       _ring_at(fx, cur["ts"]), 0.5)))
            assert got[-1][1] == cur["expected"], (cur["ts"], got[-1][1])
    assert ("2026-09-28T22:15:40-05:00", "human") in got


@pytest.mark.parametrize("old_state,new_state,old,new", [
    ("off", "heat_cool", (68.0, 74.0), (68.0, 71.0)),
    ("heat_cool", "off", (68.0, 74.0), (68.0, 71.0)),
    ("cool", "heat_cool", (68.0, 74.0), (68.0, 71.0)),
    ("heat_cool", "heat_cool", (68.0, 74.0), (None, None)),   # legs -> None
    ("heat_cool", "heat_cool", (None, 74.0), (68.0, 71.0)),
])
def test_classify_mode_change_is_none(mods, old_state, new_state, old, new):
    cls = mods["hvac_override"].classify_manual_setpoint_change
    o = types.SimpleNamespace(state=old_state, attributes={
        "preset_mode": "manual", "target_temp_low": old[0], "target_temp_high": old[1]})
    n = types.SimpleNamespace(state=new_state, attributes={
        "preset_mode": "manual", "target_temp_low": new[0], "target_temp_high": new[1]})
    assert cls(o, n, [], 0.5) == "none"


@pytest.mark.parametrize("ring_high,expected", [
    (77.5, "ura_echo"),   # Carrier shows 78 for URA's 77.5: |0.5| <= 0.5
    (77.4, "human"),      # 0.6 away
    (78.0, "ura_echo"),
])
def test_classify_tolerance_boundary_inclusive(mods, ring_high, expected):
    cls = mods["hvac_override"].classify_manual_setpoint_change
    o = types.SimpleNamespace(state="heat_cool", attributes={
        "preset_mode": "manual", "target_temp_low": 70.0, "target_temp_high": 76.0})
    n = types.SimpleNamespace(state="heat_cool", attributes={
        "preset_mode": "manual", "target_temp_low": 70.0, "target_temp_high": 78.0})
    assert cls(o, n, [(70.0, ring_high)], 0.5) == expected


def test_classify_only_changed_legs_must_match(mods):
    """A ring entry whose UNCHANGED leg differs still matches: S12 writes a
    synthetic low that must not decide the classification (P3)."""
    cls = mods["hvac_override"].classify_manual_setpoint_change
    o = types.SimpleNamespace(state="heat_cool", attributes={
        "preset_mode": "manual", "target_temp_low": 68.0, "target_temp_high": 76.0})
    n = types.SimpleNamespace(state="heat_cool", attributes={
        "preset_mode": "manual", "target_temp_low": 68.0, "target_temp_high": 74.0})
    assert cls(o, n, [(60.0, 74.0)], 0.5) == "ura_echo"
    assert cls(o, n, [(68.0, 73.0)], 0.5) == "human"


@pytest.mark.asyncio
async def test_emit_set_temperature_records_before_await(mods, monkeypatch):
    """The record is appended BEFORE the wire await: a call that raises is
    still recognised when its echo arrives."""
    coord, hass, *_ = _setup(mods, monkeypatch)
    sp = mods["hvac_setpoint"]

    async def _boom(*a, **k):
        raise RuntimeError("wire down")
    monkeypatch.setattr(hass.services, "async_call", _boom)
    with pytest.raises(RuntimeError):
        await sp.emit_set_temperature(hass, E2, target_temp_low=68.0,
                                      target_temp_high=74.0, site="t", zone_id=Z2,
                                      reason="t")
    assert sp.recent_ura_setpoints(E2) == ((68.0, 74.0),)


@pytest.mark.asyncio
async def test_recent_writes_depth_bound(mods, monkeypatch):
    coord, hass, *_ = _setup(mods, monkeypatch)
    sp = mods["hvac_setpoint"]
    for h in (80.0, 79.0, 78.0, 77.0, 76.0):
        await sp.emit_set_temperature(hass, E2, target_temp_low=68.0,
                                      target_temp_high=h, site="t", zone_id=Z2, reason="t")
    assert sp.recent_ura_setpoints(E2) == (
        (68.0, 79.0), (68.0, 78.0), (68.0, 77.0), (68.0, 76.0))


@pytest.mark.asyncio
async def test_boot_seed_from_rehydrated_rows(mods, monkeypatch):
    """Wire-in anchor: the REAL `async_setup` runs the excursion boot audit
    and then seeds the URA-write record from every rehydrated row."""
    from runtime_harness import StubBus
    _orig = StubBus.async_listen
    monkeypatch.setattr(StubBus, "async_listen",
                        lambda self, et, li, *a, **k: _orig(self, et, li))
    coord, hass, *_ = _setup(mods, monkeypatch)
    now_iso = datetime.now(timezone.utc).isoformat()

    class _RowDB(H.FakeDB):
        async def get_all_excursion_rows(self):
            return [{"zone_id": Z2, "excursion_id": "compromise:zone_2:1",
                     "kind": "compromise", "started_ts": now_iso, "duration_s": 900,
                     "pre_preset": "manual", "pre_target_low": 68.0,
                     "pre_target_high": 74.0, "excursion_target_low": 69.0,
                     "excursion_target_high": 73.0, "intended_mode": "heat_cool",
                     "caller_site": "S3_compromise"}]
    hass.data[mods["const"].DOMAIN]["database"] = _RowDB()
    coord._zone_state_store = H.FakeStore()

    async def _no_cycle(*a, **k):
        return None
    coord._async_decision_cycle = _no_cycle
    await coord.async_setup()
    ent = coord.zone_manager.zones[Z2].climate_entity   # zones are rebuilt at setup
    assert (69.0, 73.0) in mods["hvac_setpoint"].recent_ura_setpoints(ent), (
        ent, dict(mods["hvac_setpoint"]._URA_SETPOINT_WRITES))
    mods["hvac_excursion"]._test_clear_leases()


# ==========================================================================
# D1 — wired into the arrester's detection path
# ==========================================================================


@pytest.mark.asyncio
async def test_within_manual_change_books_override_detected_row(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    rows = _od_rows(hass, mods)
    assert len(rows) == 1
    d = rows[0]["details"]
    assert d["within_manual"] is True and d["changed_legs"] == ["high"]
    assert d["baseline_case"] == "C" and d["reference_preset"] == "home"
    assert d["delta_f"] == -5.0   # 71 vs home 76, high leg only


@pytest.mark.asyncio
async def test_within_manual_ura_echo_not_booked(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    mods["hvac_setpoint"].record_ura_setpoint(E2, 68.0, 77.5)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 76.0), ("manual", 68.0, 78.0)))
    assert _od_rows(hass, mods) == []
    assert arr.last_detection_for(E2) is None


@pytest.mark.asyncio
async def test_egress_mode_off_during_banking_not_booked_human(mods, monkeypatch):
    """H1 repro: a BANKING row is live, the zone is manual 69/74 heat_cool;
    egress writes mode `off` (no suppression) and ha_carrier reports both
    legs None. Not a person: the borrow lives on, no latch, no row."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "BANKING")
    await _fire(hass, arr, _ev(E2, ("manual", 69.0, 74.0), ("manual", None, None),
                               new_state="off"))
    assert _od_rows(hass, mods) == []
    assert tok.returned is False and not arr.interrupt_latched(E2)


@pytest.mark.asyncio
async def test_reconnect_within_manual_ignored(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "BANKING")
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0),
                               old_state="unavailable"))
    assert _od_rows(hass, mods) == [] and tok.returned is False


@pytest.mark.asyncio
async def test_transition_late_ura_echo_does_not_end_borrow(mods, monkeypatch):
    """INV-A5 on the transition branch: a transition INTO manual whose
    changed leg matches URA's own recent write (a late > 15 s echo of the
    S12 write) is booked as today (borrow_active) and ends nothing."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="away",
                                         low=68.0, high=80.0)
    tok = _seed(mods, Z2, "BANKING")
    mods["hvac_setpoint"].record_ura_setpoint(E2, 68.0, 78.0)
    await _fire(hass, arr, _ev(E2, ("away", 68.0, 80.0), ("manual", 68.0, 78.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["gated_reason"] == "borrow_active" and d["human_interrupt"] is False
    assert tok.returned is False and not arr.interrupt_latched(E2)


# ==========================================================================
# D2a — end the borrow, no write
# ==========================================================================


@pytest.mark.asyncio
async def test_human_interrupt_ends_banking_borrow_bookkeeping_only(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "BANKING", pre_preset="away")
    calls_before = len(hass.services.calls)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    assert tok.returned is True
    assert tok._return_outcome.trigger == "human_interrupt"
    assert tok._return_outcome.restore_ok is None
    assert db.events[-1]["trigger"] == "human_interrupt"
    assert db.events[-1]["restore_ok"] is None
    # No write under the borrow; the only new calls are none at all (the
    # arrester's new episode only arms a timer).
    assert hass.services.calls[calls_before:] == []
    assert arr.interrupt_latched(E2)
    d = _od_rows(hass, mods)[0]["details"]
    assert d["human_interrupt"] is True and d["interrupted_kind"] == "banking"
    assert d["interrupted_excursion_id"] == tok.excursion_id
    assert d["gated_reason"] is None and d["gate_snapshot"]["borrow_row"] is False
    assert d["gate_snapshot_pre_interrupt"]["borrow_row"] is True


@pytest.mark.asyncio
async def test_human_interrupt_ends_preheat_borrow(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "PREHEAT", pre_preset="home", site="S13_pre_heat", duration_s=3600)
    await _fire(hass, arr, _ev(E2, ("manual", 72.0, 76.0), ("manual", 70.0, 76.0)))
    assert tok.returned and tok._return_outcome.trigger == "human_interrupt"


@pytest.mark.asyncio
async def test_egress_row_not_ended_by_human(mods, monkeypatch):
    """Q2: the open-door pause is excluded from "person interrupts"."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "EGRESS_PAUSE", pre_preset="home", site="S15_egress", duration_s=3600)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    assert tok.returned is False
    assert _od_rows(hass, mods)[0]["details"]["gated_reason"] == "borrow_active"


@pytest.mark.asyncio
async def test_nudge_live_human_change_nudge_win_not_ended(mods, monkeypatch):
    """INV-A4 (D13). A BANKING row AND a live nudge: the nudge wins, nothing
    is ended, no latch, no arrester timer."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "BANKING")
    arr._nudge_in_flight.add(Z2)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["gated_reason"] == "nudge_win" and d["human_interrupt"] is False
    assert tok.returned is False and not arr.interrupt_latched(E2)
    assert sched.live() == [] and Z2 not in arr._grace_timers


@pytest.mark.asyncio
async def test_ownerless_compromise_row_ended_by_human(mods, monkeypatch):
    """M3: a rehydrated COMPROMISE row with no arrester timer / token is
    ended (case C baseline)."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="manual", site="S3_compromise", duration_s=900)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    assert tok.returned and tok._return_outcome.trigger == "human_interrupt"
    d = _od_rows(hass, mods)[0]["details"]
    assert d["baseline_case"] == "C" and d["interrupted_kind"] == "compromise"


@pytest.mark.asyncio
async def test_compromise_row_with_timer_only_is_not_ownerless(mods, monkeypatch):
    """Ownerless conjunct `no _compromise_timers entry`, on its own."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="manual", site="S3_compromise", duration_s=900)
    arr._compromise_timers[Z2] = lambda: None
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["interrupted_kind"] is None and d["episode_superseded"] is True


@pytest.mark.asyncio
async def test_compromise_row_being_applied_is_not_ownerless(mods, monkeypatch):
    """Ownerless conjunct `not _compromise_active` (an `_apply_compromise`
    in flight between begin and the timer), on its own."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="manual", site="S3_compromise", duration_s=900)
    arr._compromise_active[Z2] = True
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["interrupted_kind"] is None and d["episode_superseded"] is True
    assert d["gated_reason"] is None     # own in-flight row does not block


@pytest.mark.asyncio
async def test_owned_compromise_is_not_ownerless(mods, monkeypatch):
    """Discriminator for the ownerless rule: the SAME row with an owning
    token is superseded (D2c), not ended as an orphan (D2a)."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="manual", site="S3_compromise", duration_s=900)
    arr._compromise_excursion_tokens[Z2] = tok
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["interrupted_kind"] is None and d["episode_superseded"] is True
    assert tok.returned and tok._return_outcome.detail == "compromise_superseded_by_human"


@pytest.mark.asyncio
async def test_immune_person_interrupt_ends_borrow_and_stamps(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    hass.states.async_set("person.oji", "home", {"user_id": "u-oji", "friendly_name": "Oji"})
    arr.set_immune_persons(["person.oji"])
    tok = _seed(mods, Z2, "BANKING")
    ev = _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0))
    ev.context.user_id = "u-oji"
    await _fire(hass, arr, ev)
    assert tok.returned and Z2 in arr._immune_holds
    assert _od_rows(hass, mods)[0]["details"]["gated_reason"] == "immune_stamp"
    assert Z2 not in arr._grace_timers


@pytest.mark.asyncio
async def test_passive_mode_interrupt_ends_borrow_no_revert(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    arr.enabled = False
    tok = _seed(mods, Z2, "BANKING")
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    assert tok.returned and arr.interrupt_latched(E2)
    assert _od_rows(hass, mods)[0]["details"]["gated_reason"] == "passive_mode"
    assert sched.live() == []


@pytest.mark.asyncio
async def test_interrupt_does_not_cancel_reset_timers(mods, monkeypatch):
    """The interrupt itself cancels only the arrester's grace / compromise
    timers — a pending AC-reset restore timer (another owner) survives."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    arr.enabled = False   # passive: no dispatch after the interrupt
    cancelled = []
    arr._reset_timers[Z2] = lambda: cancelled.append(True)
    arr._grace_timers[Z2] = lambda: None
    _seed(mods, Z2, "BANKING")
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    assert Z2 in arr._reset_timers and cancelled == []
    assert Z2 not in arr._grace_timers


# ==========================================================================
# Baseline — one reference preset per case (H3 / P3 / Q7)
# ==========================================================================


@pytest.mark.asyncio
async def test_case_c_plain_within_manual_dispatch_against_resolver(mods, monkeypatch):
    """M9: no borrow, no episode: a person fine-tuning a manual hold is
    measured against the house S1 target (home 76) on the changed leg."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    ep = arr._arrest_episode[Z2]
    assert ep["original_preset"] == "home" and ep["expected_cool"] == 76.0
    assert [r[0] for r in sched.live()] == [120.0]   # severe grace


@pytest.mark.asyncio
async def test_case_c_resolver_none_books_no_dispatch(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    arr.set_baseline_resolver(lambda z, p=None: None)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    assert len(_od_rows(hass, mods)) == 1
    assert sched.live() == [] and Z2 not in arr._arrest_episode


@pytest.mark.asyncio
async def test_coordinator_wires_real_resolver(mods, monkeypatch):
    """Wire-in anchor: the coordinator constructor registers the resolver;
    None -> house S1 target, a named preset -> that preset's setpoints."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, house_state="sleep")
    assert arr._resolve_reference(Z2) == ("sleep", 78.0, 66.0)
    assert arr._resolve_reference(Z2, "away") == ("away", 80.0, 68.0)


@pytest.mark.asyncio
async def test_case_a_single_reference_preset(mods, monkeypatch):
    """H3: an energy BANKING borrow snapshotted `away` (80). A person sets 78
    -> delta -2 vs AWAY (normal) -> compromise at 79 -> S4 pins away. The
    house target (home 76) is never mixed in."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, low=68.0, high=74.0)
    _seed(mods, Z2, "BANKING", pre_preset="away", site="S12_pre_cool")
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 78.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["baseline_case"] == "A" and d["reference_preset"] == "away"
    assert d["delta_f"] == -2.0
    (delay, cb, _c), = sched.live()
    assert delay == 300.0                      # normal grace, 5 min
    cb(None)
    await H.drain(hass, rounds=8)
    s3 = _cw_rows(hass, mods, "S3_compromise")
    assert s3 and s3[-1]["values_after"]["target_temp_high"] == 79.0
    assert s3[-1]["values_after"]["target_temp_low"] == 68.0
    comp = [r for r in sched.live()]
    comp[-1][1](None)
    await H.drain(hass, rounds=8)
    assert H.preset_writes(hass, E2, "away") and not H.preset_writes(hass, E2, "home")


@pytest.mark.asyncio
async def test_case_a_pre_arrival_uses_house_target(mods, monkeypatch):
    """Q7: a PRE-ARRIVAL borrow (snapshot away) interrupted in home_night is
    judged against Home 76 and reverted to Home."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    _seed(mods, Z2, "BANKING", pre_preset="away", site="S12_pre_arrival")
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["reference_preset"] == "home" and d["delta_f"] == -5.0
    assert arr._arrest_episode[Z2]["original_preset"] == "home"


@pytest.mark.asyncio
async def test_case_a_human_manual_snapshot_uses_house_target(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    _seed(mods, Z2, "BANKING", pre_preset="manual", site="S12_pre_cool")
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    assert _od_rows(hass, mods)[0]["details"]["reference_preset"] == "home"


# ==========================================================================
# D2c — compromise / grace re-dispatch (H2, L6)
# ==========================================================================


async def _normal_then_compromise(mods, hass, arr, sched):
    """home 70/76 -> manual 70/78 (normal, +2) -> grace fires -> S3 at 77."""
    await _fire(hass, arr, _ev(E2, ("home", 70.0, 76.0), ("manual", 70.0, 78.0)))
    (_d, grace_cb, _c), = sched.live()
    grace_cb(None)
    await H.drain(hass, rounds=8)
    assert Z2 in arr._compromise_timers and Z2 in arr._compromise_excursion_tokens
    return arr._compromise_excursion_tokens[Z2]


@pytest.mark.asyncio
async def test_human_change_during_compromise_redispatches(mods, monkeypatch):
    """H2. House state `sleep` (resolver -> sleep 78) makes case B (episode
    original = home 76) and case C distinguishable: delta must be +4 vs the
    EPISODE, not +2 vs the house target."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=70.0, high=76.0, house_state="sleep")
    tok = await _normal_then_compromise(mods, hass, arr, sched)
    old_comp = [r for r in sched.live() if r[0] == 900.0][0]
    arr.unsuppress(E2)   # the compromise write's 15 s temp window has passed
    await _fire(hass, arr, _ev(E2, ("manual", 70.0, 77.0), ("manual", 70.0, 80.0)))
    d = _od_rows(hass, mods)[-1]["details"]
    assert d["gated_reason"] != "borrow_active" and d["gated_reason"] is None
    assert d["episode_superseded"] is True and d["baseline_case"] == "B"
    assert d["delta_f"] == 4.0                # 80 vs the episode's expected 76
    assert old_comp[2] is True                # old compromise timer cancelled
    assert tok.returned and tok._return_outcome.trigger == "human_interrupt"
    new = [r for r in sched.live() if r[0] == 120.0]
    assert len(new) == 1                      # NEW severe grace
    new[0][1](None)
    await H.drain(hass, rounds=8)
    assert H.preset_writes(hass, E2, "home")  # original preset, never manual
    assert not H.preset_writes(hass, E2, "manual")


@pytest.mark.asyncio
async def test_d2c_gen_bump_without_redispatch(mods, monkeypatch):
    """The supersede alone (no new episode: the person goes back within
    tolerance) must make the pending grace task stand down."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=70.0, high=76.0)
    await _fire(hass, arr, _ev(E2, ("home", 70.0, 76.0), ("manual", 70.0, 78.0)))
    (_d, grace_cb, _c), = sched.live()
    arr.unsuppress(E2)
    await _fire(hass, arr, _ev(E2, ("manual", 70.0, 78.0), ("manual", 70.0, 76.5)))
    assert _od_rows(hass, mods)[-1]["details"]["episode_superseded"] is True
    assert sched.live() == []                 # nothing re-dispatched
    grace_cb(None)                            # the old task was already due
    await H.drain(hass, rounds=8)
    assert _cw_rows(hass, mods, "S3_compromise") == []


@pytest.mark.asyncio
async def test_fired_compromise_revert_stands_down_on_supersede(mods, monkeypatch):
    """The compromise timer fired (its revert task is queued) and a person
    supersedes before it runs: no S4 for the old episode."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=70.0, high=76.0)
    await _normal_then_compromise(mods, hass, arr, sched)
    comp_cb = [r for r in sched.live() if r[0] == 900.0][0][1]
    comp_cb(None)                             # revert task created, not run
    arr.unsuppress(E2)
    # 76.2 is outside the 0.5 tolerance of URA's 77 compromise write, and
    # within 1 F of the episode's home 76 -> no new episode is dispatched.
    arr._handle_climate_change(_ev(E2, ("manual", 70.0, 77.0), ("manual", 70.0, 76.2)))
    await H.drain(hass, rounds=8)
    assert _od_rows(hass, mods)[-1]["details"]["episode_superseded"] is True
    assert H.preset_writes(hass, E2) == []


@pytest.mark.asyncio
async def test_delta_and_compromise_count_only_changed_legs(mods, monkeypatch):
    """P3: an unchanged low (S12's synthetic low, 60 here) never enters the
    delta or the compromise. 75 vs home 76 on the changed leg = -1 (normal);
    counting the low would give -10 (severe). Compromise low stays 70."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, low=60.0, high=74.0)
    await _fire(hass, arr, _ev(E2, ("manual", 60.0, 74.0), ("manual", 60.0, 75.0)))
    d = _od_rows(hass, mods)[0]["details"]
    assert d["delta_f"] == -1.0 and d["changed_legs"] == ["high"]
    (delay, cb, _c), = sched.live()
    assert delay == 300.0
    cb(None)
    await H.drain(hass, rounds=8)
    s3 = _cw_rows(hass, mods, "S3_compromise")[-1]["values_after"]
    assert s3["target_temp_high"] == 75.5 and s3["target_temp_low"] == 70.0


@pytest.mark.asyncio
async def test_pending_apply_compromise_stands_down_on_gen_bump(mods, monkeypatch):
    """L6: a grace task already pending when a person supersedes the episode
    writes nothing."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=70.0, high=76.0)
    await _fire(hass, arr, _ev(E2, ("home", 70.0, 76.0), ("manual", 70.0, 78.0)))
    (_d, grace_cb, _c), = sched.live()
    gen = arr._arrest_gen[Z2]
    arr._bump_arrest_gen(Z2)   # a person superseded the episode
    await arr._apply_compromise(coord.zone_manager.zones[Z2], "home",
                                77.0, 70.0, 76.0, 70.0, gen=gen)
    await H.drain(hass)
    assert _cw_rows(hass, mods, "S3_compromise") == []
    assert mods["hvac_excursion"].live_token_for(Z2) is None
    # Stood down BEFORE touching episode state or opening a row.
    assert arr._compromise_active.get(Z2) is not True
    assert not [e for e in db.events if e["kind"] == "compromise"]


@pytest.mark.asyncio
async def test_apply_compromise_stands_down_when_superseded_during_begin(mods, monkeypatch):
    """INV-A.1 race: the person's change lands while `begin_excursion`
    awaits its DB save. The just-opened COMPROMISE row is closed as a
    human interrupt and no S3 write carries its id."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=70.0, high=76.0)
    await _fire(hass, arr, _ev(E2, ("home", 70.0, 76.0), ("manual", 70.0, 78.0)))
    (_d, grace_cb, _c), = sched.live()

    async def _hook(row):
        arr._handle_climate_change(
            _ev(E2, ("manual", 70.0, 78.0), ("manual", 70.0, 80.0)))
    db.save_hook = _hook
    grace_cb(None)
    await H.drain(hass, rounds=8)
    assert _cw_rows(hass, mods, "S3_compromise") == []
    assert any(e["trigger"] == "human_interrupt" and e["kind"] == "compromise"
               for e in db.events)


@pytest.mark.asyncio
async def test_stale_revert_stands_down(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=70.0, high=76.0)
    await _fire(hass, arr, _ev(E2, ("home", 70.0, 76.0), ("manual", 70.0, 64.0)))
    (_d, old_cb, _c), = sched.live()
    arr.unsuppress(E2)
    await _fire(hass, arr, _ev(E2, ("manual", 70.0, 64.0), ("manual", 70.0, 63.0)))
    old_cb(None)          # the superseded episode's timer (already pending)
    await H.drain(hass, rounds=8)
    assert H.preset_writes(hass, E2) == []
    # The stale task never touched the NEW episode's state.
    assert Z2 in arr._grace_timers and Z2 in arr._arrest_episode
    assert arr._override_active.get(Z2) is True


@pytest.mark.asyncio
async def test_revert_stands_down_when_superseded_during_mode_write(mods, monkeypatch):
    """The S4 re-check: a person supersedes the episode while the B4
    heat_cool write awaits — no S4 under the old episode."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=70.0, high=76.0)
    await _fire(hass, arr, _ev(E2, ("home", 70.0, 76.0), ("manual", 70.0, 64.0)))
    (_d, cb, _c), = sched.live()
    coord.zone_manager.zones[Z2].hvac_mode = "cool"   # forces the B4 write
    real_call = hass.services.async_call

    async def _hooked(domain, service, data=None, blocking=False, **kw):
        await real_call(domain, service, data, blocking=blocking, **kw)
        if service == "set_hvac_mode":
            arr._bump_arrest_gen(Z2)
    monkeypatch.setattr(hass.services, "async_call", _hooked)
    cb(None)
    await H.drain(hass, rounds=8)
    assert [c for c in hass.services.calls if c[1] == "set_hvac_mode"]
    assert H.preset_writes(hass, E2) == []


@pytest.mark.asyncio
async def test_arrester_disable_releases_compromise_rows(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="manual", site="S3_compromise", duration_s=900)
    arr._compromise_excursion_tokens[Z2] = tok
    arr._compromise_timers[Z2] = lambda: None
    arr.enabled = False
    await H.drain(hass)
    assert tok.returned
    assert tok._return_outcome.trigger == "arrester_disabled"
    assert tok._return_outcome.restore_ok is None


# ==========================================================================
# D2d — the S4 revert never pins `manual`
# ==========================================================================


@pytest.mark.asyncio
async def test_s4_revert_never_pins_manual(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="manual", site="S3_compromise", duration_s=900)
    arr._compromise_excursion_tokens[Z2] = tok
    await arr._revert_override(coord.zone_manager.zones[Z2], "home")
    await H.drain(hass)
    assert H.preset_writes(hass, E2, "home")
    assert not H.preset_writes(hass, E2, "manual")


@pytest.mark.asyncio
async def test_s4_revert_named_snapshot_still_wins(mods, monkeypatch):
    """Byte-identical twin (F2): a NAMED token snapshot is still the value."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="sleep", site="S3_compromise", duration_s=900)
    arr._compromise_excursion_tokens[Z2] = tok
    await arr._revert_override(coord.zone_manager.zones[Z2], "home")
    await H.drain(hass)
    assert H.preset_writes(hass, E2, "sleep") and not H.preset_writes(hass, E2, "home")


@pytest.mark.asyncio
async def test_s4_revert_no_named_preset_skips(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    tok = _seed(mods, Z2, "COMPROMISE", pre_preset="manual", site="S3_compromise", duration_s=900)
    arr._compromise_excursion_tokens[Z2] = tok
    await arr._revert_override(coord.zone_manager.zones[Z2], "manual")
    await H.drain(hass)
    assert H.preset_writes(hass, E2) == []
    assert tok._return_outcome.detail == "revert_no_named_preset"
    assert tok._return_outcome.restore_ok is None


# ==========================================================================
# D2e — the interrupt latch (H4)
# ==========================================================================


@pytest.mark.asyncio
async def test_interrupt_latch_survives_second_human_change(mods, monkeypatch):
    """H4 repro: 71 (interrupt), then 70 in the same episode: the latch holds
    and the next energy pre-cool begins nothing."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    _seed(mods, Z2, "BANKING", pre_preset="away")
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    arr.unsuppress(E2)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 71.0), ("manual", 68.0, 70.0)))
    assert arr.interrupt_latched(E2)
    z = coord.zone_manager.zones[Z2]
    z.target_temp_high, z.target_temp_low = 76.0, 68.0
    await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    assert _cw_rows(hass, mods, "S12_pre_cool") == []
    assert mods["hvac_excursion"].live_token_for(Z2) is None


@pytest.mark.asyncio
async def test_interrupt_latch_blocks_preheat(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    arr._interrupt_latch.add(E2)
    _zones_only(mods, coord, Z2)
    await coord._predictor._execute_pre_heat()
    await H.drain(hass)
    assert _cw_rows(hass, mods, "S13_pre_heat") == []
    assert mods["hvac_excursion"].live_token_for(Z2) is None   # nothing begun


@pytest.mark.asyncio
async def test_interrupt_latch_discharges_on_manual_exit(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    arr._interrupt_latch.add(E2)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 71.0), ("home", 70.0, 76.0)))
    assert not arr.interrupt_latched(E2)


def test_interrupt_latch_cleared_by_teardown(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    arr._interrupt_latch.add(E2)
    arr.teardown()
    assert not arr.interrupt_latched(E2)


# ==========================================================================
# D2b / M1 — owner sites never write for an ended token
# ==========================================================================


def _zones_only(mods, coord, zid):
    for z_id in coord.zone_manager.zones:
        _occ(mods, coord, z_id, hvac=(z_id == zid))


@pytest.mark.asyncio
async def test_interrupt_inside_begin_await_blocks_s12_write(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=68.0, high=76.0)

    async def _hook(row):
        arr._handle_climate_change(
            _ev(E2, ("manual", 68.0, 76.0), ("manual", 68.0, 71.0)))
        await asyncio.sleep(0)
    db.save_hook = _hook
    z = coord.zone_manager.zones[Z2]
    await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    await H.drain(hass, rounds=6)
    assert _cw_rows(hass, mods, "S12_pre_cool") == []
    assert db.events and db.events[-1]["trigger"] == "human_interrupt"
    assert Z2 not in getattr(coord._predictor, "_banking_excursion_tokens", {})


@pytest.mark.asyncio
async def test_m1_returned_token_blocks_s12_write(mods, monkeypatch):
    """Conjunct 1 of the M1 check on its own: the token was returned during
    begin, no latch."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=68.0, high=76.0)
    ex = mods["hvac_excursion"]

    async def _hook(row):
        await ex.return_excursion(ex._rows[Z2], trigger="test_end", restore_ok=None)
    db.save_hook = _hook
    await coord._predictor._execute_zone_pre_cool(
        coord.zone_manager.zones[Z2], offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    assert _cw_rows(hass, mods, "S12_pre_cool") == []
    assert not arr.interrupt_latched(E2)


@pytest.mark.asyncio
async def test_m1_latch_blocks_s12_write(mods, monkeypatch):
    """Conjunct 2 on its own: the latch is set during begin, the token is
    not (yet) returned."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=68.0, high=76.0)

    async def _hook(row):
        arr._interrupt_latch.add(E2)
    db.save_hook = _hook
    await coord._predictor._execute_zone_pre_cool(
        coord.zone_manager.zones[Z2], offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    assert _cw_rows(hass, mods, "S12_pre_cool") == []
    tok = mods["hvac_excursion"].live_token_for(Z2)
    assert tok is not None and not tok.returned   # CM did NOT close it as a wire failure


@pytest.mark.asyncio
async def test_interrupt_inside_begin_await_blocks_s13_write(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=68.0, high=76.0)
    _zones_only(mods, coord, Z2)

    async def _hook(row):
        arr._handle_climate_change(
            _ev(E2, ("manual", 68.0, 76.0), ("manual", 66.0, 76.0)))
        await asyncio.sleep(0)
    db.save_hook = _hook
    await coord._predictor._execute_pre_heat()
    await H.drain(hass, rounds=6)
    assert _cw_rows(hass, mods, "S13_pre_heat") == []
    assert Z2 not in getattr(coord._predictor, "_preheat_return_timers", {})


@pytest.mark.asyncio
async def test_m1_returned_token_blocks_s13_write(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=68.0, high=76.0)
    _zones_only(mods, coord, Z2)
    ex = mods["hvac_excursion"]

    async def _hook(row):
        await ex.return_excursion(ex._rows[Z2], trigger="test_end", restore_ok=None)
    db.save_hook = _hook
    await coord._predictor._execute_pre_heat()
    await H.drain(hass)
    assert _cw_rows(hass, mods, "S13_pre_heat") == []


@pytest.mark.asyncio
async def test_m1_latch_blocks_s13_write(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=68.0, high=76.0)
    _zones_only(mods, coord, Z2)

    async def _hook(row):
        arr._interrupt_latch.add(E2)
    db.save_hook = _hook
    await coord._predictor._execute_pre_heat()
    await H.drain(hass)
    assert _cw_rows(hass, mods, "S13_pre_heat") == []


@pytest.mark.asyncio
async def test_release_banked_zones_skips_returned_token(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="home",
                                         low=68.0, high=76.0)
    pred = coord._predictor
    await pred._execute_zone_pre_cool(coord.zone_manager.zones[Z2], offset=-3.0,
                                      reason="energy_precool")
    tok = pred._banking_excursion_tokens[Z2]
    await mods["hvac_excursion"].return_excursion(tok, trigger="human_interrupt", restore_ok=None)
    n = len(hass.services.calls)
    await pred._release_banked_zones({Z2})
    await H.drain(hass)
    assert hass.services.calls[n:] == []
    assert Z2 not in pred._banking_excursion_tokens


@pytest.mark.asyncio
async def test_return_preheat_skips_returned_token(mods, monkeypatch):
    coord, hass, arr, sched, db = _setup(mods, monkeypatch)
    pred = coord._predictor
    tok = _seed(mods, Z2, "PREHEAT", pre_preset="home", site="S13_pre_heat", duration_s=3600)
    pred._preheat_excursion_tokens = {Z2: tok}
    await mods["hvac_excursion"].return_excursion(tok, trigger="human_interrupt", restore_ok=None)
    n = len(hass.services.calls)
    await pred._return_preheat(Z2)
    await H.drain(hass)
    assert hass.services.calls[n:] == []


# ==========================================================================
# D6 — the boot audit never pins `manual` after a nudge
# ==========================================================================


def _nudge_row(pre_preset):
    return {"zone_id": Z1, "excursion_id": "nudge:zone_1:1", "kind": "nudge",
            "started_ts": datetime.now(timezone.utc).isoformat(), "duration_s": 120,
            "pre_preset": pre_preset, "pre_target_low": 70.0, "pre_target_high": 76.0,
            "intended_mode": "heat_cool", "caller_site": "S5_nudge_start"}


@pytest.mark.asyncio
async def test_boot_audit_nudge_manual_snapshot_no_pin(mods, monkeypatch):
    db = PersistDB()
    coord, hass, arr, sched, _ = _setup(mods, monkeypatch, db=db, zone=Z1)
    db.state[Z1] = _nudge_row("manual")
    await mods["hvac_excursion"].async_startup_excursion_audit(hass, coord)
    await H.drain(hass)
    assert H.preset_writes(hass, E1) == []
    assert Z1 not in db.state


@pytest.mark.asyncio
async def test_boot_audit_nudge_named_snapshot_still_pins(mods, monkeypatch):
    db = PersistDB()
    coord, hass, arr, sched, _ = _setup(mods, monkeypatch, db=db, zone=Z1)
    db.state[Z1] = _nudge_row("sleep")
    await mods["hvac_excursion"].async_startup_excursion_audit(hass, coord)
    await H.drain(hass)
    assert H.preset_writes(hass, E1, "sleep")


# ==========================================================================
# Acceptance replays — 09-28 zone_2
# ==========================================================================


def _to_zone2(fx_row):
    return ("manual" if fx_row["preset_mode"] == "manual" else fx_row["preset_mode"],
            fx_row["low"], fx_row["high"])


async def _replay_until_person(mods, monkeypatch, *, occupied=False, soc=None):
    """22:03:51 pre-arrival -> ONE S12 write (baseline home 76 - 2 = 74, no
    ratchet across three triggers) -> Carrier echoes -> 22:15:40 a person
    sets 71."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="away",
                                         low=68.0, high=80.0)
    pred = coord._predictor
    z = coord.zone_manager.zones[Z2]
    _occ(mods, coord, Z2, lighting=occupied)
    if soc is not None:
        arr._battery_soc = soc
    coord._pre_arrival_zones.add(Z2)
    now = datetime(2026, 9, 28, 22, 3, 51)
    for _ in range(3):   # 22:03:51, 22:04:26, 22:06:02 triggers
        await pred._check_pre_conditioning(None, "home_night", now,
                                           pre_arrival_zones={Z2},
                                           zone_intelligence_enabled=True)
        await H.drain(hass)
    s12 = _cw_rows(hass, mods, "S12_pre_cool")
    assert len(s12) == 1, s12
    assert s12[0]["values_after"]["target_temp_high"] == 74.0
    assert s12[0]["values_after"]["target_temp_low"] == 68.0
    tok = pred._banking_excursion_tokens[Z2]
    assert tok.caller_site == "S12_pre_arrival" and s12[0]["excursion_id"] == tok.excursion_id
    # Carrier echo of URA's own write (inside the 15 s temp window -> dropped).
    z.target_temp_high, z.preset_mode = 74.0, "manual"
    H.set_climate(hass, E2, preset_mode="manual", hold_activity="manual", low=68.0, high=74.0)
    await _fire(hass, arr, _ev(E2, ("away", 68.0, 80.0), ("manual", 68.0, 74.0)))
    assert _od_rows(hass, mods) == []
    # 22:15:40 — the window has long passed; a person sets 71.
    arr.unsuppress(E2)
    await _fire(hass, arr, _ev(E2, ("manual", 68.0, 74.0), ("manual", 68.0, 71.0)))
    return coord, hass, arr, sched, db, tok


@pytest.mark.asyncio
async def test_replay_09_28_zone2_expected_writes(mods, monkeypatch):
    coord, hass, arr, sched, db, tok = await _replay_until_person(mods, monkeypatch)
    d = _od_rows(hass, mods)[0]["details"]
    assert d["within_manual"] is True and d["human_interrupt"] is True
    assert d["interrupted_kind"] == "banking" and d["reference_preset"] == "home"
    assert d["delta_f"] == -5.0
    assert tok.returned and tok._return_outcome.trigger == "human_interrupt"
    assert tok._return_outcome.restore_ok is None
    ev = [e for e in db.events if e["excursion_id"] == tok.excursion_id]
    assert ev and ev[0]["trigger"] == "human_interrupt" and ev[0]["restore_ok"] is None
    n_s12 = len(_cw_rows(hass, mods, "S12_pre_cool"))
    # Next passes: the zone leaves pre-arrival (interrupted); nothing begins.
    reasons = coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert reasons == {Z2: "interrupted"}
    await coord._async_end_pre_arrival_borrows(reasons)
    for _ in range(2):
        await coord._predictor._check_pre_conditioning(
            None, "home_night", datetime(2026, 9, 28, 22, 20), pre_arrival_zones={Z2},
            zone_intelligence_enabled=True)
        await H.drain(hass)
    assert len(_cw_rows(hass, mods, "S12_pre_cool")) == n_s12
    assert _cw_rows(hass, mods, "S13_pre_heat") == []
    assert not [r for r in _cw_rows(hass, mods) if r["excursion_id"] == tok.excursion_id
                and r["site"] != "S12_pre_cool"]
    # After the 2-min severe grace the revert pins HOME (Q7), never away.
    (delay, cb, _c), = sched.live()
    assert delay == 120.0
    cb(None)
    await H.drain(hass, rounds=8)
    s4 = [c for c in H.preset_writes(hass, E2) if c[2]["preset_mode"] != "resume"]
    assert [c[2]["preset_mode"] for c in s4] == ["home"]


@pytest.mark.asyncio
async def test_replay_09_28_occupied_high_soc_comfort_grant(mods, monkeypatch):
    coord, hass, arr, sched, db, tok = await _replay_until_person(
        mods, monkeypatch, occupied=True, soc=90)
    d = _od_rows(hass, mods)[0]["details"]
    assert d["gated_reason"] == "comfort_grant" and tok.returned
    assert Z2 not in arr._grace_timers and Z2 not in arr._arrest_episode
    assert H.preset_writes(hass, E2) == []


@pytest.mark.asyncio
async def test_replay_23_03_interrupt_leaves_boot_audit_nothing(mods, monkeypatch):
    """README_v5.103.22 boot evidence: at 23:40 the stale-boot release
    restored `away` over a person's 71 set at 23:03. With the interrupt
    ending the row at 23:03, the restart finds nothing to restore."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="away",
                                         low=68.0, high=80.0)
    coord._pre_arrival_zones.add(Z2)
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 3, 51), pre_arrival_zones={Z2},
        zone_intelligence_enabled=True)
    await H.drain(hass)
    assert Z2 in db.state          # the pre-arrival row is persisted
    # 23:03:51 sleep 70/76 -> manual 68/71 (a person), well outside any window.
    arr.unsuppress(E2)
    await _fire(hass, arr, _ev(E2, ("sleep", 70.0, 76.0), ("manual", 68.0, 71.0)))
    assert Z2 not in db.state
    # Restart: RAM registry gone, boot audit reads the DB.
    ex = mods["hvac_excursion"]
    ex._test_clear_leases()
    n = len(hass.services.calls)
    await ex.async_startup_excursion_audit(hass, coord)
    await H.drain(hass)
    assert H.preset_writes(hass, E2) == [] and hass.services.calls[n:] == []


@pytest.mark.asyncio
async def test_replay_23_03_control_without_interrupt_restores_away(mods, monkeypatch):
    """Discriminating twin: with no person change, the same restart restores
    the snapshot `away` (today's stale_boot_release)."""
    coord, hass, arr, sched, db = _setup(mods, monkeypatch, preset="away",
                                         low=68.0, high=80.0)
    coord._pre_arrival_zones.add(Z2)
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 3, 51), pre_arrival_zones={Z2},
        zone_intelligence_enabled=True)
    await H.drain(hass)
    ex = mods["hvac_excursion"]
    ex._test_clear_leases()
    await ex.async_startup_excursion_audit(hass, coord)
    await H.drain(hass)
    assert H.preset_writes(hass, E2, "away")

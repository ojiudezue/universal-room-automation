"""HVAC W1-B fix-up round 2 — behavioural anchors.

MEDIUM-1 nudge in-flight discharge; D-1 arrester timers stand down to a
live borrow / egress pause at fire time; D-2 force_ac_reset returns the
nudge row + nudge_win needs a LIVE nudge; D-3 egress rehydrate re-links
the EGRESS row; D-4 in-window resume is presets-only; LOW-3 marker
cleared on automatic sunset.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402


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


ZONE = "zone_1"
ENT = "climate.test_zone_1"


class _RampDB(H.FakeDB):
    def __init__(self, *, raise_on=None, in_flight=None, excursion_rows=None, egress_rows=None):
        super().__init__()
        self.raise_on = raise_on
        self._in_flight = in_flight or {}
        self._ex_rows = excursion_rows or []
        self._egress_rows = egress_rows or []
        self.ramp_events: list[dict] = []

    def _maybe(self, name):
        if self.raise_on == name:
            self.raise_on = None  # one-shot: only the START bookkeeping fails
            raise RuntimeError(f"injected {name}")

    async def set_ac_in_flight_nudge(self, **kw):
        return None

    async def get_ac_reset_state(self, zone_id):
        self._maybe("get_ac_reset_state")
        return {"in_flight_nudge_original_target": self._in_flight.get(zone_id), "soft_nudge_count": 0}

    async def save_ac_reset_state(self, state):
        self._maybe("save_ac_reset_state")

    async def log_ac_ramp_event(self, **kw):
        self._maybe("log_ac_ramp_event")
        self.ramp_events.append(kw)

    async def clear_ac_in_flight_nudge(self, zone_id):
        self._in_flight.pop(zone_id, None)

    async def update_ac_ramp_restore_settled(self, **kw):
        return None

    async def get_zones_with_in_flight_nudge(self):
        return [{"zone_id": z, "original_target": t, "nudged_target": t + 1.5,
                 "started_ts": (H.local_now() - timedelta(seconds=60)).isoformat(),
                 "duration_s": 1200} for z, t in self._in_flight.items()]

    async def get_all_excursion_rows(self):
        return list(self._ex_rows)

    async def get_all_egress_state(self):
        return list(self._egress_rows)

    def __getattr__(self, name):  # any other DAO -> async no-op
        async def _noop(*a, **k):
            return None
        return _noop


def _setup(mods, db=None):
    coord, hass = H.make_coord(mods)
    arr = coord._override_arrester
    z = coord.zone_manager.zones[ZONE]
    arr._db = db
    arr._ramp_master_enabled = True
    arr._nudge_duration_min = 20
    arr.set_egress_manager(coord._egress_manager)  # as HVACCoordinator.async_setup does
    return coord, hass, arr, z


def _ledger(hass, mods, action):
    return hass.data[mods["const"].DOMAIN]["activity_logger"].actions(action)


# ---- MEDIUM-1 --------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("dao", ["get_ac_reset_state", "save_ac_reset_state", "log_ac_ramp_event"])
async def test_nudge_start_db_failure_does_not_strand_in_flight(mods, dao):
    coord, hass, arr, z = _setup(mods, db=_RampDB(raise_on=dao))
    await arr._perform_soft_nudge(z, 2.5, triggered_by="test")
    await H.drain(hass)
    assert H.temp_writes(hass, ENT), "nudge wire write still happens"
    assert ZONE in arr._nudge_restore_timers, "restore timer (the discharge) must be scheduled"
    # Fire the restore: in-flight clears, gate (e) disarms.
    await arr._restore_after_nudge(z, 76.0)
    await H.drain(hass)
    assert ZONE not in arr._nudge_in_flight and ZONE not in arr._nudge_restore_timers
    z.preset_mode = "manual"
    mods["hvac_excursion"]._test_clear_leases()
    assert coord.preset_manager.manual_guard_verdict(ZONE)["gate_snapshot"]["e"] is False


# ---- D-1 -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grace_then_egress_pause_compromise_refuses_and_no_b4_write(mods):
    """Reviewer repro: human +2 F -> grace (t=0); egress pauses (t=4); grace
    fires (t=5) -> compromise REFUSES; revert at t=20 -> NO heat_cool write."""
    coord, hass, arr, z = _setup(mods)
    ev = H.make_event(ENT, old_preset="home", new_preset="manual", old_high=76.0, new_high=78.0)
    arr._handle_climate_change(ev)
    await H.drain(hass)
    assert ZONE in arr._grace_timers and arr._override_active.get(ZONE) is True
    coord._egress_manager._paused_by_egress[ZONE] = {"mode": "heat_cool", "preset": "home", "thermostat": ENT}
    z.hvac_mode = "off"
    await arr._apply_compromise(z, "home", 77.0, 68.0, 76.0, 68.0)
    await H.drain(hass)
    assert H.temp_writes(hass, ENT) == [], "compromise must not write over an egress pause"
    assert arr._override_active.get(ZONE) is False and ZONE not in arr._grace_timers
    rows = _ledger(hass, mods, "arrester_deferred_to_borrow")
    assert rows and rows[0]["details"]["source"] == "egress_paused"
    await arr._revert_override(z, "home")
    await H.drain(hass)
    assert not [c for c in hass.services.calls if c[1] == "set_hvac_mode"], "no B4 heat_cool write"
    assert H.preset_writes(hass, ENT) == []


@pytest.mark.asyncio
async def test_compromise_and_revert_refuse_under_live_banking_row(mods):
    coord, hass, arr, z = _setup(mods)
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.BANKING, duration_s=None)
    arr._override_active[ZONE] = True
    await arr._apply_compromise(z, "home", 77.0, 68.0, 76.0, 68.0)
    await H.drain(hass)
    assert H.temp_writes(hass, ENT) == [] and ZONE not in arr._compromise_timers
    assert arr._override_active.get(ZONE) is False
    z.hvac_mode = "off"
    await arr._revert_override(z, "home")
    await H.drain(hass)
    assert not [c for c in hass.services.calls if c[1] == "set_hvac_mode"]
    assert H.preset_writes(hass, ENT) == []
    src = [r["details"]["source"] for r in _ledger(hass, mods, "arrester_deferred_to_borrow")]
    assert len(src) == 2 and all(s.startswith("borrow_row:") for s in src)
    ex._test_clear_leases()


@pytest.mark.asyncio
async def test_revert_proceeds_when_only_its_own_compromise_row_is_live(mods):
    """Own token exempt: the compromise's own row must not block its revert."""
    coord, hass, arr, z = _setup(mods)
    ex = mods["hvac_excursion"]
    tok = ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.COMPROMISE, duration_s=900, pre_preset="home")
    arr._compromise_excursion_tokens[ZONE] = tok
    await arr._revert_override(z, "home")
    await H.drain(hass)
    assert H.preset_writes(hass, ENT, "home")
    ex._test_clear_leases()


# ---- D-2 -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_ac_reset_returns_nudge_row_and_later_override_is_governed(mods):
    coord, hass, arr, z = _setup(mods, db=_RampDB())
    ex = mods["hvac_excursion"]
    await arr._perform_soft_nudge(z, 2.5, triggered_by="test")
    await H.drain(hass)
    assert ZONE in arr._nudge_excursion_tokens and ex.is_borrow_active(ZONE)

    async def _no_escalation(*a, **k):
        return None
    arr._perform_hard_reset_escalation = _no_escalation
    await arr.force_ac_reset(ZONE)
    await H.drain(hass)
    assert ZONE not in arr._nudge_excursion_tokens
    assert ex.is_borrow_active(ZONE) is False, "row must be returned"
    assert ZONE not in arr._nudge_in_flight and ZONE not in arr._nudge_restore_timers
    arr.unsuppress(ENT)  # the nudge's own 15 s temp window has passed
    ev = H.make_event(ENT, old_preset="home", new_preset="manual", old_high=76.0, new_high=64.0, old_low=68.0, new_low=64.0)
    arr._handle_climate_change(ev)
    await H.drain(hass)
    d = _ledger(hass, mods, "override_detected")[-1]["details"]
    assert d["gated_reason"] is None, "governed, not nudge_win"


@pytest.mark.asyncio
async def test_nudge_win_requires_live_nudge_not_a_stale_token(mods):
    coord, hass, arr, z = _setup(mods)
    arr._nudge_excursion_tokens[ZONE] = type("T", (), {"excursion_id": "stale", "pre_preset": "home"})()
    ev = H.make_event(ENT, old_preset="home", new_preset="manual", old_high=76.0, new_high=64.0, old_low=68.0, new_low=64.0)
    arr._handle_climate_change(ev)
    await H.drain(hass)
    d = _ledger(hass, mods, "override_detected")[-1]["details"]
    assert d["gated_reason"] is None and d["gate_snapshot"]["nudge_token"] is True


# ---- D-3 -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_egress_rehydrate_relinks_row_and_resume_returns_it(mods):
    coord, hass, arr, z = _setup(mods)
    ex = mods["hvac_excursion"]
    eg = coord._egress_manager
    tok = ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.EGRESS_PAUSE, duration_s=None, pre_preset="home")
    eg._db = _RampDB(egress_rows=[{
        "zone_id": ZONE, "state": "paused", "saved_hvac_mode": "heat_cool",
        "saved_preset_mode": "home", "paused_at": H.local_now().isoformat(),
        "triggered_by_room": "r", "thermostat_entity": ENT,
    }])
    await eg.async_rehydrate_from_db()
    assert eg.is_paused(ZONE)
    assert eg._egress_excursion_tokens.get(ZONE) is tok, "rehydrated EGRESS row must be re-linked"
    z.preset_mode = "manual"
    assert coord.preset_manager.manual_guard_verdict(ZONE)["gate_snapshot"]["e"] is True
    await eg._engage_resume(zone_id=ZONE, zone_state=z, now=H.local_now())
    await H.drain(hass)
    assert ZONE not in ex._rows, "resume must return the re-linked row"
    assert coord.preset_manager.manual_guard_verdict(ZONE)["gate_snapshot"]["e"] is False


@pytest.mark.asyncio
async def test_egress_rehydrate_returns_orphan_row_when_not_paused(mods):
    coord, hass, arr, z = _setup(mods)
    ex = mods["hvac_excursion"]
    eg = coord._egress_manager
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.EGRESS_PAUSE, duration_s=None)
    eg._db = _RampDB(egress_rows=[])
    await eg.async_rehydrate_from_db()
    assert not eg.is_paused(ZONE)
    assert ZONE not in ex._rows, "orphaned EGRESS row returned at rehydrate"


# ---- D-4 -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_mid_nudge_resume_is_presets_only(mods):
    coord, hass, arr, z = _setup(mods, db=_RampDB(
        in_flight={ZONE: 76.0},
        excursion_rows=[{"zone_id": ZONE, "kind": "nudge", "pre_preset": "home"}],
    ))
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual", high=77.5)
    await arr.async_startup_ramp_audit()
    assert ZONE in arr._nudge_in_flight and arr._nudge_pre_preset.get(ZONE) == "home"
    await arr._restore_after_nudge(z, 76.0)
    await H.drain(hass)
    assert H.temp_writes(hass, ENT) == [], "named snapshot -> no raw setpoint restore"
    assert H.preset_writes(hass, ENT, "home")


# ---- LOW-3 ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_automatic_sunset_clears_restart_marker(mods):
    coord, hass, arr, z = _setup(mods)
    coord._zone_state_store = H.FakeStore()
    DOMAIN = mods["const"].DOMAIN
    for e in hass.config_entries.async_entries(DOMAIN):
        e.options = {**(e.options or {}), "hvac_temp_arrester_override_was_active": True}
    arr.set_temp_arrester_override(True)
    arr._temp_arrester_override_started_ts = H.local_now() - timedelta(seconds=21601)
    assert arr.sunset_temp_arrester_override("max_age_or_boundary") is True
    await H.drain(hass)
    for e in hass.config_entries.async_entries(DOMAIN):
        assert "hvac_temp_arrester_override_was_active" not in (e.options or {})

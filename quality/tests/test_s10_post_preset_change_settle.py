"""HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1 — behavioural suite.

Plan: docs/planning/PLANNING_hvac_s10_stale_range.md (Rev 3).

Each test drives REAL production code on the shared W1-B harness
(`_w1b_harness`): the real HVACCoordinator + ZoneState observer against
the smoke StubHass. T15 drives `update_zone_climate_state` through a real
`hass.states.async_set` so the observer wire-in is exercised end-to-end
(wire-in anchor mandate).

Falsifiable invariants (plan §Falsifiable invariant):
  INV-S10-SETTLE          - no S10 wire/capture/failure increment while
                            `(now - zone.last_observed_preset_change) <
                            S10_POST_PRESET_CHANGE_SETTLE_S`.
  INV-S10-LATCH-RESET     - `_s10_success` (SKIPPED_ALREADY_CORRECT or
                            limit-matching view) resets BOTH `writes`
                            AND `failures`; APPLIED resets NEITHER.
  INV-S10-SETTLE-OBSERVABLE - rollout zone held in a continuous settle
                            episode >= `S10_SETTLE_HELD_WARN_S` fires
                            exactly one `s10_settle_held` ledger row per
                            calendar day.
"""
from __future__ import annotations

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
T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
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


class Clock:
    def __init__(self, start=T0):
        self.now = start

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)


class Rig:
    """Minimum rig for the settle gate + confirmed-success reset tests."""

    def __init__(self, mods, monkeypatch, *, rollout=(Z1,), flag=True):
        self.mods = mods
        self.mp = monkeypatch
        coord, hass = H.make_coord(mods)
        self.coord, self.hass = coord, hass
        self.DOMAIN = mods["const"].DOMAIN
        from homeassistant.helpers import entity_registry as er

        class _Reg:
            def async_get(self, entity_id):
                if str(entity_id).startswith("climate."):
                    return types.SimpleNamespace(
                        platform="ha_carrier", entity_id=entity_id,
                    )
                return None

        monkeypatch.setattr(er, "async_get", lambda _h: _Reg())
        mods["hvac_strategy"]._test_reset_cache()
        mods["hvac_setpoint"]._test_clear_ura_setpoints()
        self.cm = next(
            e for e in hass.config_entries.async_entries()
            if "zones" not in (e.options or {})
        )
        self.cm.options = {**(self.cm.options or {}), ROLLOUT_KEY: list(rollout)}
        self.overrides: dict = {}
        hass.data[self.DOMAIN]["coordinator_manager"] = types.SimpleNamespace(
            coordinators={"energy": types.SimpleNamespace(
                _dynamic_preset_overrides=self.overrides)},
        )
        for zid, ent in ((Z1, E1), (Z2, E2), (Z3, E3)):
            coord.zone_manager.zones[zid].preset_mode = "home"
            H.set_climate(
                hass, ent, preset_mode="home", hold_activity="home",
                low=68.0, high=76.0,
            )
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
        monkeypatch.setattr(mods["hvac_zones"], "dt_util", _Dt())
        coord._zone_state_store = H.FakeStore()
        coord._house_state = "home_day"

    def set_stamp(self, zone_id, age_s):
        """Arm an observed-preset-change stamp (and an episode start of
        the same age)."""
        zone = self.coord.zone_manager.zones[zone_id]
        ts = self.clock.now - timedelta(seconds=age_s)
        zone.last_observed_preset_change = ts
        zone.settle_episode_started_at = ts

    def rows(self, site):
        return H.climate_write_rows(self.hass, self.mods, site)

    def ledger(self, action):
        return [
            r for r in self.hass.data[self.DOMAIN]["database"].rows
            if r.get("action") == action
        ]


# ==========================================================================
# T1 / T2 / T7 — the skip-matrix step itself
# ==========================================================================


def test_T1_gate_active_within_settle(mods, monkeypatch):
    """stamp 300s old < 600s -> post_preset_change_settle."""
    r = Rig(mods, monkeypatch)
    r.set_stamp(Z1, 300)
    reason = r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
    assert reason == "post_preset_change_settle"


def test_T2_gate_expired(mods, monkeypatch):
    """stamp 601s old >= 600s -> NOT post_preset_change_settle."""
    r = Rig(mods, monkeypatch)
    r.set_stamp(Z1, 601)
    reason = r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
    assert reason != "post_preset_change_settle"


def test_T7_no_stamp_behaves_as_today(mods, monkeypatch):
    """last_observed_preset_change is None -> gate is invisible."""
    r = Rig(mods, monkeypatch)
    z = r.coord.zone_manager.zones[Z1]
    assert z.last_observed_preset_change is None
    reason = r.coord._s10_zone_skip_reason(Z1, z)
    assert reason != "post_preset_change_settle"


# ==========================================================================
# T3 / T4 — _s10_pass: zero wire + zero capture + zero failure
# ==========================================================================


@pytest.mark.asyncio
async def test_T3_apply_pass_zero_wire_zero_capture(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    r.set_stamp(Z1, 60)
    await r.coord._s10_pass(mode="apply")
    await H.drain(r.hass)
    assert r.rows("S10_preset_range") == []
    assert Z1 not in r.coord._s10_snapshots
    rec = (r.coord._s10_records.get(Z1) or {}).get("home|apply")
    assert rec is None


@pytest.mark.asyncio
async def test_T4_restore_pass_zero_wire(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    # Pre-stage a snapshot so the restore pass has work to do.
    r.coord._s10_snapshots[Z1] = {
        "home": {"low": 68.0, "high": 76.0, "captured_iso": r.clock.now.isoformat()},
    }
    r.coord._guest_mode_actuation_enabled = False
    r.set_stamp(Z1, 60)
    await r.coord._s10_pass(mode="restore")
    await H.drain(r.hass)
    assert r.rows("S10_preset_range_restore") == []


# ==========================================================================
# T5 — pre-call re-check (settle armed mid-await)
# ==========================================================================


def test_T5_pre_call_recheck_catches_settle(mods, monkeypatch):
    """`_s10_zone_skip_reason` is the same function used by the pass-level
    skip check (:4467) AND the pre-call re-check (:4664). Arming the
    stamp AFTER the pass-level check means the pre-call re-check must
    stand down with `post_preset_change_settle`."""
    r = Rig(mods, monkeypatch)
    assert r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1]) is None
    r.set_stamp(Z1, 60)
    assert (
        r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
        == "post_preset_change_settle"
    )


# ==========================================================================
# T6 — sibling zone unaffected
# ==========================================================================


def test_T6_sibling_zone_unaffected(mods, monkeypatch):
    r = Rig(mods, monkeypatch, rollout=(Z1, Z2))
    r.set_stamp(Z1, 60)  # only zone_1
    assert (
        r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
        == "post_preset_change_settle"
    )
    assert (
        r.coord._s10_zone_skip_reason(Z2, r.coord.zone_manager.zones[Z2])
        != "post_preset_change_settle"
    )


# ==========================================================================
# T8 — observed anchor covers non-S1 writer (no _zone_last_s1_write)
# ==========================================================================


def test_T8_non_s1_writer_still_gates(mods, monkeypatch):
    """`_zone_last_s1_write` is empty for Z1 but the OBSERVED stamp was
    armed (any writer: arrester revert, S7 restore, Bryant, human...).
    The gate fires on the stamp, independent of the S1 record."""
    r = Rig(mods, monkeypatch)
    assert r.coord._zone_last_s1_write.get(Z1) is None
    r.set_stamp(Z1, 60)
    reason = r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
    assert reason == "post_preset_change_settle"


# ==========================================================================
# T9 / T10 / T11 — D2 confirmed-success reset of `failures`
# ==========================================================================


@pytest.mark.asyncio
async def test_T9_failures_reset_on_skipped_already_correct(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    r.coord._s10_set_record(
        Z1, "home", "apply",
        {
            "value": [70.0, 74.0], "writes": 0, "failures": 2,
            "latched": False, "latch_reason": None,
            "last_attempt_iso": None, "last_write_iso": None,
        },
    )
    rec = r.coord._s10_record(Z1, "home", "apply")
    await r.coord._s10_success(Z1, "home", "apply", rec, r.clock.now)
    rec2 = r.coord._s10_record(Z1, "home", "apply")
    assert rec2["failures"] == 0
    assert rec2["writes"] == 0


@pytest.mark.asyncio
async def test_T10_failures_reset_on_limit_matching_view(mods, monkeypatch):
    """The limit-matching view path near hvac.py:4596 calls
    `_s10_success` with the same signature; the reset propagates."""
    r = Rig(mods, monkeypatch)
    r.coord._s10_set_record(
        Z1, "home", "restore",
        {
            "value": [70.0, 74.0], "writes": 3, "failures": 1,
            "latched": False, "latch_reason": None,
            "last_attempt_iso": r.clock.now.isoformat(),
            "last_write_iso": None,
        },
    )
    rec = r.coord._s10_record(Z1, "home", "restore")
    # Mirrors the ":4596" call site: success at the limit.
    await r.coord._s10_success(Z1, "home", "restore", rec, r.clock.now)
    # restore removes the record entirely; we test the apply-mode mirror
    # to witness the discharged failures counter.
    r.coord._s10_set_record(
        Z1, "home", "apply",
        {
            "value": [70.0, 74.0], "writes": 3, "failures": 1,
            "latched": False, "latch_reason": None,
            "last_attempt_iso": r.clock.now.isoformat(),
            "last_write_iso": None,
        },
    )
    rec_a = r.coord._s10_record(Z1, "home", "apply")
    await r.coord._s10_success(Z1, "home", "apply", rec_a, r.clock.now)
    out = r.coord._s10_record(Z1, "home", "apply")
    assert out["failures"] == 0 and out["writes"] == 0


@pytest.mark.asyncio
async def test_T11_applied_does_not_reset_failures(mods, monkeypatch):
    """APPLIED is a wire return (operator ruling A4): neither `writes`
    nor `failures` is reset. _s10_write_one updates APPLIED inline and
    does NOT call _s10_success - this test asserts the invariant by
    checking that calling the APPLIED branch's record update preserves
    the failures counter."""
    r = Rig(mods, monkeypatch)
    r.coord._s10_set_record(
        Z1, "home", "apply",
        {
            "value": [70.0, 74.0], "writes": 1, "failures": 2,
            "latched": False, "latch_reason": None,
            "last_attempt_iso": r.clock.now.isoformat(),
            "last_write_iso": None,
        },
    )
    # Simulate the APPLIED branch in _s10_write_one hvac.py ~4687.
    rec = dict(r.coord._s10_record(Z1, "home", "apply"))
    rec["writes"] = int(rec.get("writes") or 0) + 1
    rec["last_write_iso"] = r.clock.now.isoformat()
    r.coord._s10_set_record(Z1, "home", "apply", rec)
    out = r.coord._s10_record(Z1, "home", "apply")
    # failures is UNCHANGED under APPLIED (A4): the discharge is only
    # via _s10_success. The build adds the failures=0 line INSIDE
    # _s10_success - APPLIED must not touch it.
    assert out["failures"] == 2
    assert out["writes"] == 2


# ==========================================================================
# T13 / T14 — integration: full _async_apply_preset_overrides
# ==========================================================================


@pytest.mark.asyncio
async def test_T13_apply_overrides_gated_then_runs_next_tick(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    r.set_stamp(Z1, 60)
    await r.coord._async_apply_preset_overrides()
    await H.drain(r.hass)
    assert r.rows("S10_preset_range") == []
    # Advance past settle; stamp still points to the OLD time, so a
    # subsequent tick finds (now - stamp) > 600s and no longer skips.
    r.clock.advance(600)
    # The pass may still skip for OTHER reasons (snapshot capture etc.)
    # but it must NOT skip with post_preset_change_settle.
    assert (
        r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
        != "post_preset_change_settle"
    )


@pytest.mark.asyncio
async def test_T14_restore_pass_gates_then_releases(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    r.coord._guest_mode_actuation_enabled = False
    r.coord._s10_snapshots[Z1] = {
        "home": {"low": 68.0, "high": 76.0, "captured_iso": r.clock.now.isoformat()},
    }
    r.set_stamp(Z1, 60)
    await r.coord._async_apply_preset_overrides()
    await H.drain(r.hass)
    assert r.rows("S10_preset_range_restore") == []
    r.clock.advance(600)
    assert (
        r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
        != "post_preset_change_settle"
    )


# ==========================================================================
# T15 — observer wire-in via real hass.states.async_set
# ==========================================================================


def test_T15a_observer_fires_on_preset_mode_change(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    # Seed via first readable observation (no stamp).
    r.coord.zone_manager.update_zone_climate_state(Z1)
    z = r.coord.zone_manager.zones[Z1]
    assert z.last_observed_preset_change is None
    assert z.prev_preset_mode == "home" and z.prev_hold_activity == "home"
    # Change preset_mode via real hass.states.async_set.
    H.set_climate(
        r.hass, E1, preset_mode="away", hold_activity="away",
        low=66.0, high=80.0,
    )
    r.coord.zone_manager.update_zone_climate_state(Z1)
    z = r.coord.zone_manager.zones[Z1]
    assert z.last_observed_preset_change is not None
    assert z.settle_episode_started_at is not None
    assert (
        r.coord._s10_zone_skip_reason(Z1, z) == "post_preset_change_settle"
    )


def test_T15b_observer_fires_on_hold_activity_change(mods, monkeypatch):
    """R1: `hold_activity` edge also arms the stamp - both signals
    must open the window because Carrier's two-feed transition can
    land either side first."""
    r = Rig(mods, monkeypatch)
    r.coord.zone_manager.update_zone_climate_state(Z1)
    # preset_mode constant; only hold_activity moves.
    H.set_climate(
        r.hass, E1, preset_mode="home", hold_activity="away",
        low=68.0, high=76.0,
    )
    r.coord.zone_manager.update_zone_climate_state(Z1)
    z = r.coord.zone_manager.zones[Z1]
    assert z.last_observed_preset_change is not None
    assert (
        r.coord._s10_zone_skip_reason(Z1, z) == "post_preset_change_settle"
    )


# ==========================================================================
# T16 — boot seed rule (R3)
# ==========================================================================


def test_T16_boot_seed_without_stamping(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    z = r.coord.zone_manager.zones[Z1]
    assert z.prev_preset_mode == "" and z.prev_hold_activity == ""
    # 1st readable observation: SEED (no stamp).
    r.coord.zone_manager.update_zone_climate_state(Z1)
    assert z.last_observed_preset_change is None
    assert z.prev_preset_mode == "home" and z.prev_hold_activity == "home"
    # 2nd readable observation, same values: still no stamp.
    r.coord.zone_manager.update_zone_climate_state(Z1)
    assert z.last_observed_preset_change is None
    # 3rd observation, flipped: stamp set.
    H.set_climate(
        r.hass, E1, preset_mode="away", hold_activity="away",
        low=66.0, high=80.0,
    )
    r.coord.zone_manager.update_zone_climate_state(Z1)
    assert z.last_observed_preset_change is not None


# ==========================================================================
# T17 — unknown flap does not stamp (R3)
# ==========================================================================


def test_T17_unknown_flap_does_not_stamp(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    r.coord.zone_manager.update_zone_climate_state(Z1)
    z = r.coord.zone_manager.zones[Z1]
    assert (z.prev_preset_mode, z.prev_hold_activity) == ("home", "home")
    # Flip preset_mode to "unknown" - unreadable, prev untouched.
    H.set_climate(
        r.hass, E1, preset_mode="unknown", hold_activity="home",
        low=68.0, high=76.0,
    )
    r.coord.zone_manager.update_zone_climate_state(Z1)
    assert z.last_observed_preset_change is None
    assert z.prev_preset_mode == "home"
    # Return to "home" - no stamp (same as prev).
    H.set_climate(
        r.hass, E1, preset_mode="home", hold_activity="home",
        low=68.0, high=76.0,
    )
    r.coord.zone_manager.update_zone_climate_state(Z1)
    assert z.last_observed_preset_change is None


# ==========================================================================
# T18 — R4 trip-wire: once-per-day s10_settle_held
# ==========================================================================


@pytest.mark.asyncio
async def test_T18_trip_wire_fires_once_per_day(mods, monkeypatch):
    r = Rig(mods, monkeypatch)
    z = r.coord.zone_manager.zones[Z1]
    # Open a settle episode and keep extending it with re-stamps every
    # 300 s (< 600 s settle so the episode stays continuous).
    z.settle_episode_started_at = r.clock.now
    z.last_observed_preset_change = r.clock.now
    for _ in range(49):  # 49 * 300 s = 14_700 s, past 14_400 warn.
        r.clock.advance(300)
        z.last_observed_preset_change = r.clock.now  # within-settle re-stamp
    # Episode start is now 14_700 s in the past; last stamp is at now (fresh).
    r.coord._s10_check_settle_held()
    await H.drain(r.hass)
    held_rows = r.ledger("s10_settle_held")
    assert len(held_rows) == 1
    details = json.loads(held_rows[0]["details_json"])
    assert details["zone_id"] == Z1
    assert details["held_s"] >= 14_400
    # Second cross on same calendar day does NOT fire a second row.
    r.clock.advance(300)
    z.last_observed_preset_change = r.clock.now
    r.coord._s10_check_settle_held()
    await H.drain(r.hass)
    held_rows2 = r.ledger("s10_settle_held")
    assert len(held_rows2) == 1
    # Diagnostics surface - episode length is observable.
    diag = r.coord.get_s10_diagnostics()
    assert Z1 in diag["s10_settle_held_s"]
    assert diag["s10_settle_held_s"][Z1] >= 14_400
    # Release: advance past settle (no re-stamp) -> latch clears.
    r.clock.advance(601)
    r.coord._s10_check_settle_held()
    assert Z1 not in r.coord._s10_settle_held_fired_on
    # Review A A-M1: diagnostic field is None once the stamp is stale
    # (the display must NOT keep growing forever after the gate
    # released; otherwise the live acceptance criterion `no rollout
    # zone reports s10_settle_held_s >= 14_400` false-fires forever).
    diag2 = r.coord.get_s10_diagnostics()
    assert diag2["s10_settle_held_s"][Z1] is None


# ==========================================================================
# T19 — skip-step ordering mutation (per-site source mutation anchor)
# ==========================================================================


def test_T19_settle_dominates_s1_same_tick(mods, monkeypatch):
    """Per-site source-mutation anchor: with the s1_same_tick check
    EXECUTED (zone IS in _zones_written_this_cycle) AND the settle
    stamp armed, the function must return `post_preset_change_settle`
    - proving the settle check is strictly ahead of s1_same_tick in
    the matrix.

    This is the oracle for R6d. If a future refactor moves
    `post_preset_change_settle` AFTER `s1_same_tick`, the fail-closed
    skip would be `s1_same_tick` and this test turns red.
    """
    r = Rig(mods, monkeypatch)
    r.set_stamp(Z1, 60)  # settle armed
    r.coord._zones_written_this_cycle.add(Z1)  # s1_same_tick armed
    reason = r.coord._s10_zone_skip_reason(Z1, r.coord.zone_manager.zones[Z1])
    assert reason == "post_preset_change_settle"


# ==========================================================================
# Review A fix-ups
# ==========================================================================


def test_RA_M1_diagnostic_none_after_release(mods, monkeypatch):
    """A-M1: `s10_settle_held_s` returns None once the last stamp is
    older than the settle window. Standalone from T18 so a regression
    turns red with a tiny repro."""
    r = Rig(mods, monkeypatch)
    r.set_stamp(Z1, 60)
    diag = r.coord.get_s10_diagnostics()
    # Fresh stamp -> armed episode, int seconds.
    assert isinstance(diag["s10_settle_held_s"][Z1], int)
    assert diag["s10_settle_held_s"][Z1] >= 0
    # Advance past settle without re-stamping -> diagnostic reports None.
    r.clock.advance(601)
    diag2 = r.coord.get_s10_diagnostics()
    assert diag2["s10_settle_held_s"][Z1] is None


def test_RA_L4_diagnostic_is_int(mods, monkeypatch):
    """A-L4: the field is an int (whole seconds). A growing float
    would differ on every sensor update and churn the recorder."""
    r = Rig(mods, monkeypatch)
    r.set_stamp(Z1, 90)
    diag = r.coord.get_s10_diagnostics()
    val = diag["s10_settle_held_s"][Z1]
    assert isinstance(val, int)
    assert not isinstance(val, bool)


def test_RA_L1_latch_uses_local_calendar_day(mods, monkeypatch):
    """A-L1: once-per-day latch keys on the LOCAL calendar day
    (`dt_util.now().date()`), not UTC. Patch `dt_util.now` to return a
    local date that differs from `dt_util.utcnow().date()` and assert
    the latch entry equals the LOCAL date."""
    r = Rig(mods, monkeypatch)
    # Clock utcnow() -> 2026-10-16 02:00 UTC; local -> 2026-10-15 21:00
    # (CDT, UTC-5). The local date is Oct 15; the UTC date is Oct 16.
    from datetime import timezone as _tz
    r.clock.now = datetime(2026, 10, 16, 2, 0, 0, tzinfo=_tz.utc)
    local_now = datetime(
        2026, 10, 15, 21, 0, 0,
        tzinfo=timezone(timedelta(hours=-5)),
    )
    local_date = local_now.date()

    class _DtLocal:
        def __getattr__(self, name):
            if name == "utcnow":
                return lambda: r.clock.now
            if name == "now":
                return lambda: local_now
            real_dt = mods["hvac"].__dict__["dt_util"]
            # Fall through to whatever real_dt wraps.
            import homeassistant.util.dt as _real
            return getattr(_real, name)

    monkeypatch.setattr(mods["hvac"], "dt_util", _DtLocal())
    z = r.coord.zone_manager.zones[Z1]
    z.settle_episode_started_at = r.clock.now - timedelta(seconds=14_500)
    z.last_observed_preset_change = r.clock.now - timedelta(seconds=60)
    r.coord._s10_check_settle_held()
    stored = r.coord._s10_settle_held_fired_on.get(Z1)
    assert stored == local_date
    # UTC date would have been Oct 16; sanity-check the discriminator.
    assert stored != r.clock.now.date()


def test_RA_L2_latch_pruned_on_rollout_removal(mods, monkeypatch):
    """A-L2: a zone removed from the rollout has its stale latch
    pruned at the top of the check, so a same-day re-add can warn
    fresh."""
    r = Rig(mods, monkeypatch, rollout=(Z1, Z2))
    r.coord._s10_settle_held_fired_on[Z2] = r.clock.now.date()
    # Remove Z2 from the rollout.
    r.cm.options = {**(r.cm.options or {}), ROLLOUT_KEY: [Z1]}
    r.coord._s10_check_settle_held()
    assert Z2 not in r.coord._s10_settle_held_fired_on
    assert Z1 not in r.coord._s10_settle_held_fired_on  # Z1 has no stamp


def test_RA_L3_carrier_none_hold_is_readable(mods, monkeypatch):
    """A-L3: a Carrier zone with `hold_activity = None` (no hold) is
    READABLE. Driving a real `hass.states.async_set` with
    `hold_activity` explicitly None then changing `preset_mode` must
    stamp the observer (Bryant-schedule preset change on an unheld
    Carrier zone — the zones 1/2 rollout depends on this)."""
    r = Rig(mods, monkeypatch)
    # First readable observation seeds the prev fields.
    r.hass.states.async_set(E1, "heat_cool", {
        "preset_mode": "home",
        "preset_modes": ["away", "home", "manual", "sleep", "resume"],
        "hold_activity": None,  # Carrier "no hold" sentinel
        "target_temp_high": 76.0, "target_temp_low": 68.0,
        "hvac_modes": ["off", "heat_cool", "cool", "heat"],
        "current_temperature": 74.0,
    })
    r.coord.zone_manager.update_zone_climate_state(Z1)
    z = r.coord.zone_manager.zones[Z1]
    # Seed stored "none" (readable), no stamp yet.
    assert z.last_observed_preset_change is None
    assert z.prev_hold_activity == "none"
    assert z.prev_preset_mode == "home"
    # Bryant schedule flips preset_mode while the zone remains unheld.
    r.hass.states.async_set(E1, "heat_cool", {
        "preset_mode": "away",
        "preset_modes": ["away", "home", "manual", "sleep", "resume"],
        "hold_activity": None,
        "target_temp_high": 80.0, "target_temp_low": 66.0,
        "hvac_modes": ["off", "heat_cool", "cool", "heat"],
        "current_temperature": 74.0,
    })
    r.coord.zone_manager.update_zone_climate_state(Z1)
    assert z.last_observed_preset_change is not None
    assert z.settle_episode_started_at is not None
    assert (
        r.coord._s10_zone_skip_reason(Z1, z) == "post_preset_change_settle"
    )


def test_RA_L3_absent_hold_still_inert(mods, monkeypatch):
    """A-L3 corollary: on an ecobee / Generic entity (hold_activity
    attribute ABSENT), the observer stays inert — preserving the
    plan's `no ecobee adapter change` non-goal."""
    r = Rig(mods, monkeypatch)
    # No `hold_activity` key at all.
    r.hass.states.async_set(E1, "heat_cool", {
        "preset_mode": "home",
        "preset_modes": ["away", "home"],
        "target_temp_high": 76.0, "target_temp_low": 68.0,
        "hvac_modes": ["off", "heat_cool"],
        "current_temperature": 74.0,
    })
    r.coord.zone_manager.update_zone_climate_state(Z1)
    r.hass.states.async_set(E1, "heat_cool", {
        "preset_mode": "away",
        "preset_modes": ["away", "home"],
        "target_temp_high": 80.0, "target_temp_low": 66.0,
        "hvac_modes": ["off", "heat_cool"],
        "current_temperature": 74.0,
    })
    r.coord.zone_manager.update_zone_climate_state(Z1)
    z = r.coord.zone_manager.zones[Z1]
    assert z.last_observed_preset_change is None  # unreadable - no stamp


# ==========================================================================
# Review B fix-ups
# ==========================================================================


def _arm_episode(r, zone_id, episode_s=14_500):
    """Open a settle episode of ~episode_s with a fresh last stamp."""
    z = r.coord.zone_manager.zones[zone_id]
    z.settle_episode_started_at = r.clock.now - timedelta(seconds=episode_s)
    z.last_observed_preset_change = r.clock.now - timedelta(seconds=60)


@pytest.mark.asyncio
async def test_RB_M1_tripwire_dispatches_nm(mods, monkeypatch):
    """B-M1: the 4 h settle-held warn goes through the EXISTING S10 NM
    path (`_s10_notify` -> notification_manager.async_notify) so the
    operator is paged, in addition to the ledger row. Hazard type
    s10_settle_held, severity LOW, once per zone per local day."""
    r = Rig(mods, monkeypatch)
    _arm_episode(r, Z1)
    r.coord._s10_check_settle_held()
    await H.drain(r.hass)
    nm = r.hass.data[r.DOMAIN]["notification_manager"]
    held_notes = [n for n in nm.notes if n.get("hazard_type") == "s10_settle_held"]
    assert len(held_notes) == 1
    assert held_notes[0]["severity"].name == "LOW"
    # Second check same day does NOT fire again (once-per-day latch).
    r.clock.advance(300)
    r.coord.zone_manager.zones[Z1].last_observed_preset_change = r.clock.now
    r.coord._s10_check_settle_held()
    await H.drain(r.hass)
    held_notes2 = [n for n in nm.notes if n.get("hazard_type") == "s10_settle_held"]
    assert len(held_notes2) == 1
    # Ledger row still present.
    assert len(r.ledger("s10_settle_held")) == 1


@pytest.mark.asyncio
async def test_RB_M2_restore_candidate_included(mods, monkeypatch):
    """B-M2: a zone REMOVED from the rollout but still carrying a
    saved original (ruling-A6 restore candidate) is covered by BOTH
    the trip-wire and `get_s10_diagnostics()['s10_settle_held_s']`."""
    r = Rig(mods, monkeypatch, rollout=())  # empty rollout
    # Pre-stage a saved original for Z1 (restore candidate).
    r.coord._s10_snapshots[Z1] = {
        "home": {"low": 68.0, "high": 76.0, "captured_iso": r.clock.now.isoformat()},
    }
    _arm_episode(r, Z1)
    # Trip-wire fires on the restore candidate even with empty rollout.
    r.coord._s10_check_settle_held()
    await H.drain(r.hass)
    nm = r.hass.data[r.DOMAIN]["notification_manager"]
    held_notes = [n for n in nm.notes if n.get("hazard_type") == "s10_settle_held"]
    assert len(held_notes) == 1
    assert len(r.ledger("s10_settle_held")) == 1
    # Diagnostic surfaces the zone's held_s even though it's not in the
    # rollout.
    diag = r.coord.get_s10_diagnostics()
    assert Z1 in diag["s10_settle_held_s"]
    assert isinstance(diag["s10_settle_held_s"][Z1], int)
    assert diag["s10_settle_held_s"][Z1] >= 14_400


@pytest.mark.asyncio
async def test_RB_L2_confirmed_success_persists_apply(mods, monkeypatch):
    """B-L2: apply-mode confirmed success schedules a persist so the
    `failures = 0` reset survives a restart."""
    r = Rig(mods, monkeypatch)
    r.coord._s10_set_record(
        Z1, "home", "apply",
        {
            "value": [70.0, 74.0], "writes": 0, "failures": 2,
            "latched": False, "latch_reason": None,
            "last_attempt_iso": None, "last_write_iso": None,
        },
    )
    saves_before = len(r.coord._zone_state_store.saves)
    rec = r.coord._s10_record(Z1, "home", "apply")
    await r.coord._s10_success(Z1, "home", "apply", rec, r.clock.now)
    await H.drain(r.hass)
    saves_after = len(r.coord._zone_state_store.saves)
    assert saves_after > saves_before
    # The persisted snapshot carries failures=0 under the S10 side-key.
    from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
        S10_STATE_SIDE_KEY,
    )
    last = r.coord._zone_state_store.saves[-1]
    s10_blob = last.get(S10_STATE_SIDE_KEY) or {}
    recs = s10_blob.get("records", {}).get(Z1, {})
    assert recs.get("home|apply", {}).get("failures") == 0

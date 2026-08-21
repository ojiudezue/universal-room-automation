"""HVAC-GOVERNED-EXCURSION-1 D3 — nudge cluster migration.

Row 6 (S5 nudge START, `_perform_soft_nudge`): must open an excursion
lease via ``begin_excursion(kind=NUDGE)`` and store the token on
``arrester._nudge_excursion_tokens[zone_id]``.

Row 7 (nudge RETURN normal, `_restore_after_nudge`): must call
``return_excursion`` on the stored token — clears the in-memory
lease and deletes the persisted state row.

Row 8 (S8 cancel, `cancel_nudge`): same return call.

Snapshot-restore semantics (§13.5 CLOSED): the pre_preset snapshot is
UNFILTERED — a "manual" value is stored (not filtered out); the
restore preset write is UNCONDITIONAL — fires whenever the snapshot
has a value, no `_cur_preset == "manual"` gate.

Neuter drill anchors:
- Comment out `begin_excursion(...)` call in `_perform_soft_nudge` →
  `test_perform_soft_nudge_creates_lease` fails (no lease).
- Comment out `return_excursion(...)` in `_restore_after_nudge` →
  `test_restore_after_nudge_releases_lease` fails (lease survives).
- Comment out `return_excursion(...)` in `cancel_nudge` →
  `test_cancel_nudge_releases_lease` fails (lease survives).

Fixture: reuses the harness loader from
``test_override_arrester_ttl_suppression.py`` for module load, then
constructs a minimal OverrideArrester via the shared _make_arrester.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock


# Use the shared, idempotent harness (C-H2 fix — no more coupling
# by importing another test file for its module-scope side effects).
_this_dir = os.path.dirname(__file__)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import _excursion_harness  # noqa: E402
_mods = _excursion_harness.bootstrap()
hvac_override = _mods["hvac_override"]
_ex_mod = _mods["hvac_excursion"]
OverrideArrester = hvac_override.OverrideArrester
ZoneState = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
].ZoneState

ZONE_ID = "zone_a"
CLIMATE_ENTITY = "climate.zone_a"


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _make_zone_with_temps():
    z = ZoneState(
        zone_id=ZONE_ID, zone_name="Zone A",
        climate_entity=CLIMATE_ENTITY,
    )
    z.hvac_mode = "heat_cool"
    z.preset_mode = "home"
    z.target_temp_low = 70.0
    z.target_temp_high = 76.0
    z.nudge_kwh_rate_before = 1.0
    return z


_ORIG_EMIT_TEMP = hvac_override.emit_set_temperature
_ORIG_EMIT_PRESET = hvac_override.emit_set_preset_mode
_ORIG_CALL_LATER = hvac_override.async_call_later


def teardown_function(_):
    """Restore module-level chokepoints to their pre-test values so
    sibling test files (e.g. test_override_arrester_ttl_suppression)
    don't inherit our AsyncMock patches."""
    hvac_override.emit_set_temperature = _ORIG_EMIT_TEMP
    hvac_override.emit_set_preset_mode = _ORIG_EMIT_PRESET
    hvac_override.async_call_later = _ORIG_CALL_LATER


def _setup_arrester_for_nudge(preset_now: str = "home"):
    """Return an arrester ready to have _perform_soft_nudge called.

    Stubs emit_set_temperature + async_call_later on the module so the
    real coroutine runs through without producing HA service calls.
    Wires hass.states.get to return preset_now.
    """
    _ex_mod._test_clear_leases()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)

    zone = _make_zone_with_temps()
    zm = MagicMock()
    zm.zones = {ZONE_ID: zone}
    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None
    st = MagicMock()
    st.attributes = {"preset_mode": preset_now}
    st.state = "cool"
    hass.states.get = MagicMock(return_value=st)

    a = OverrideArrester(
        hass=hass, zone_manager=zm,
        compromise_minutes=30, ac_reset_timeout=60, enabled=True,
    )
    a._db = None
    hvac_override.emit_set_temperature = AsyncMock(return_value=True)
    hvac_override.emit_set_preset_mode = AsyncMock(return_value=True)
    hvac_override.async_call_later = MagicMock(return_value=lambda: None)
    return a, zone


# ---------------------------------------------------------------------------
# Row 6 — _perform_soft_nudge OPENS an excursion lease
# ---------------------------------------------------------------------------

def test_perform_soft_nudge_creates_lease_row_6():
    """After _perform_soft_nudge, an excursion lease exists for the zone
    AND the arrester carries the token on _nudge_excursion_tokens.

    Neuter anchor: comment out the begin_excursion call in
    _perform_soft_nudge → this test fails."""
    a, zone = _setup_arrester_for_nudge()
    _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
    assert _ex_mod._test_has_row(ZONE_ID) is True, (
        "Row 6: _perform_soft_nudge must open an excursion lease "
        "so decision ticks defer at the S1 gate. No lease means the "
        "begin_excursion call was skipped/deleted."
    )
    assert ZONE_ID in a._nudge_excursion_tokens, (
        "Row 6: the arrester must carry the ExcursionToken so the "
        "restore/cancel paths can find it."
    )
    token = a._nudge_excursion_tokens[ZONE_ID]
    assert token.kind == _ex_mod.EXCURSION_KIND.NUDGE


def test_perform_soft_nudge_snapshot_is_UNFILTERED_manual_stored():
    """§13.5 CLOSED — snapshot is UNFILTERED. When the thermostat
    reports preset_mode='manual' at nudge start, the snapshot
    STORES 'manual' (unlike pre-cycle behavior which filtered it out).

    Under the new semantics, the token's pre_preset field is 'manual'.
    The arrester's _nudge_pre_preset dict still captures 'manual' too."""
    a, zone = _setup_arrester_for_nudge(preset_now="manual")
    _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
    # Legacy dict: the manual filter is removed, so 'manual' is stored.
    assert a._nudge_pre_preset.get(ZONE_ID) == "manual", (
        "Snapshot-restore: _nudge_pre_preset must UNFILTERED — "
        "'manual' is stored, not skipped."
    )
    # Primitive token: pre_preset is also 'manual'.
    token = a._nudge_excursion_tokens[ZONE_ID]
    assert token.pre_preset == "manual"


# ---------------------------------------------------------------------------
# Row 7 — _restore_after_nudge CLOSES the excursion lease
# ---------------------------------------------------------------------------

def test_restore_after_nudge_releases_lease_row_7():
    """After _restore_after_nudge, the lease is cleared and the token
    is popped from _nudge_excursion_tokens.

    Neuter anchor: comment out the return_excursion call at the end of
    _restore_after_nudge → this test fails (lease survives)."""
    a, zone = _setup_arrester_for_nudge()
    _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
    assert _ex_mod._test_has_row(ZONE_ID) is True  # pre-condition
    _run(a._restore_after_nudge(zone, original_target=76.0))
    assert _ex_mod._test_has_row(ZONE_ID) is False, (
        "Row 7: _restore_after_nudge must call return_excursion to "
        "release the lease. A lingering lease permanently blocks "
        "future decision-tick preset writes for the zone."
    )
    assert ZONE_ID not in a._nudge_excursion_tokens


def test_restore_after_nudge_writes_preset_unconditionally():
    """§13.5 CLOSED — restore emits set_preset_mode UNCONDITIONALLY when
    the snapshot has a value; the old `_cur_preset == "manual"` gate is
    deleted.

    Positive control: even when the thermostat's current preset already
    equals the snapshot, the restore fires (idempotent write). Neuter
    anchor: if a builder re-adds the manual gate, this test fails."""
    a, zone = _setup_arrester_for_nudge(preset_now="home")
    _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
    hvac_override.emit_set_preset_mode.reset_mock()
    _run(a._restore_after_nudge(zone, original_target=76.0))
    assert hvac_override.emit_set_preset_mode.await_count >= 1, (
        "Snapshot-restore: preset write must fire whenever the snapshot "
        "has a value, regardless of current thermostat preset."
    )


# ---------------------------------------------------------------------------
# Row 8 — cancel_nudge CLOSES the excursion lease
# ---------------------------------------------------------------------------

def test_cancel_nudge_releases_lease_row_8():
    """After cancel_nudge, the lease is cleared and the token is popped.

    Neuter anchor: comment out the return_excursion call at the end of
    cancel_nudge → this test fails (lease survives after cancel)."""
    a, zone = _setup_arrester_for_nudge()
    _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
    assert _ex_mod._test_has_row(ZONE_ID) is True

    # cancel_nudge takes a zone_id or entity_id and resolves via
    # self._resolve_zone. Stub that to return our zone.
    a._resolve_zone = MagicMock(return_value=zone)
    _run(a.cancel_nudge(ZONE_ID))
    assert _ex_mod._test_has_row(ZONE_ID) is False, (
        "Row 8: cancel_nudge must call return_excursion. Cancelled "
        "nudges that leave a lease behind permanently block ticks."
    )
    assert ZONE_ID not in a._nudge_excursion_tokens


# ---------------------------------------------------------------------------
# Kill-switch (§4.7): OFF → begin_excursion returns None → no lease.
# The nudge still fires on the wire; only the lease-based tick
# deferral is bypassed.
# ---------------------------------------------------------------------------

def test_kill_switch_off_produces_no_lease_but_still_nudges():
    a, zone = _setup_arrester_for_nudge()
    _ex_mod._test_set_kill_switch(False)
    try:
        _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
        assert _ex_mod._test_has_row(ZONE_ID) is False, (
            "§4.7 BEGIN-ONLY: kill switch OFF must yield no lease."
        )
        # Wire write still fires (the switch does not gate the emit,
        # it only gates lease creation).
        assert hvac_override.emit_set_temperature.await_count >= 1
    finally:
        _ex_mod._test_set_kill_switch(True)



# ---------------------------------------------------------------------------
# F3 fix - cancel_nudge writes preset from snapshot
# ---------------------------------------------------------------------------

def test_F3_cancel_nudge_writes_preset_from_snapshot():
    """Plan section 3 row 8: cancel_nudge must restore the preset from
    the snapshot, not just the setpoint. Pre-cycle behaviour popped and
    discarded _nudge_pre_preset and emitted set_temperature only, which
    left preset_mode=manual on preset-based thermostats (Bryant/Carrier).

    Neuter anchor: delete the F3 preset-restore block at the tail of
    cancel_nudge -> this test fails."""
    a, zone = _setup_arrester_for_nudge(preset_now="home")
    # A real DB stub returns the in-flight target so cancel proceeds.
    class _FakeDB:
        async def get_ac_reset_state(self, zid):
            return {"in_flight_nudge_original_target": 76.0,
                    "soft_nudge_count": 0}
        async def save_ac_reset_state(self, st): return None
        async def clear_ac_in_flight_nudge(self, zid): return None
        async def log_ac_ramp_event(self, **kw): return None
        async def set_ac_in_flight_nudge(self, **kw): return None
    a._db = _FakeDB()
    # Take a nudge (populates _nudge_excursion_tokens with snapshot=home).
    _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
    tok = a._nudge_excursion_tokens[ZONE_ID]
    assert tok.pre_preset == "home"
    # Reset preset-mock count.
    hvac_override.emit_set_preset_mode.reset_mock()
    # Resolve-zone stub for cancel path.
    a._resolve_zone = MagicMock(return_value=zone)
    _run(a.cancel_nudge(ZONE_ID))
    # The preset chokepoint MUST have been called for the cancel restore.
    calls = hvac_override.emit_set_preset_mode.await_args_list
    preset_values = [c.args[2] if len(c.args) > 2 else c.kwargs.get("preset")
                     for c in calls]
    assert "home" in preset_values, (
        "F3: cancel_nudge must restore the preset from the snapshot; "
        f"preset writes captured: {preset_values}"
    )



# ---------------------------------------------------------------------------
# #53 sweep - ac_ramp_events.excursion_id is populated (not dead)
# ---------------------------------------------------------------------------

def test_53_ac_ramp_events_excursion_id_populated_by_nudge_calls():
    """The excursion_id column added by D2 was DEAD pre-fix — the DAO
    accepted it, no caller passed it. Post-fix: _perform_soft_nudge
    passes the token's excursion_id so ac_ramp_events can UNION-analyse
    against hvac_excursion_events.

    Neuter anchor: delete the excursion_id kwarg from either
    log_ac_ramp_event call in _perform_soft_nudge -> this test fails."""
    a, zone = _setup_arrester_for_nudge()
    captured = []
    class _CaptureDB:
        async def get_ac_reset_state(self, zid):
            return {"soft_nudge_count": 0}
        async def save_ac_reset_state(self, st): return None
        async def set_ac_in_flight_nudge(self, **kw): return None
        async def clear_ac_in_flight_nudge(self, zid): return None
        async def log_ac_ramp_event(self, **kw):
            captured.append(kw)
        async def update_ac_ramp_restore_settled(self, **kw): return None
    a._db = _CaptureDB()
    _run(a._perform_soft_nudge(zone, kwh_rate_before=2.0))
    started = [c for c in captured if c.get("event_type") == "nudge_started"]
    assert started, f"no nudge_started row captured: {captured}"
    assert started[0].get("excursion_id"), (
        "#53: nudge_started must populate excursion_id from the token. "
        f"kwargs={started[0]}"
    )
    tok = a._nudge_excursion_tokens[ZONE_ID]
    assert started[0]["excursion_id"] == tok.excursion_id

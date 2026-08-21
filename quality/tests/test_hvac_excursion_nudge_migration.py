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


# Reuse the ttl_suppression harness (which loads hvac_override + the HA
# mocks + hvac_excursion into sys.modules already). This test file must
# import AFTER that harness runs; pytest collection order alphabetizes, so
# lease_ac14_behavioural loads first (also HA-mocked), then we run.
_this_dir = os.path.dirname(__file__)
sys.path.insert(0, _this_dir)

# Trigger the ttl_suppression module-level bootstrap.
import test_override_arrester_ttl_suppression as _tsp  # noqa: E402

OverrideArrester = _tsp.OverrideArrester
ZoneState = _tsp.ZoneState
_make_arrester = _tsp._make_arrester
ZONE_ID = _tsp.ZONE_ID
CLIMATE_ENTITY = _tsp.CLIMATE_ENTITY
hvac_override = _tsp.hvac_override

# The excursion primitive module (imported into sys.modules by the
# earlier harness — sibling load list includes it).
_ex_mod = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_excursion"
]


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
    assert _ex_mod.lease_active(ZONE_ID) is True, (
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
    assert _ex_mod.lease_active(ZONE_ID) is True  # pre-condition
    _run(a._restore_after_nudge(zone, original_target=76.0))
    assert _ex_mod.lease_active(ZONE_ID) is False, (
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
    assert _ex_mod.lease_active(ZONE_ID) is True

    # cancel_nudge takes a zone_id or entity_id and resolves via
    # self._resolve_zone. Stub that to return our zone.
    a._resolve_zone = MagicMock(return_value=zone)
    _run(a.cancel_nudge(ZONE_ID))
    assert _ex_mod.lease_active(ZONE_ID) is False, (
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
        assert _ex_mod.lease_active(ZONE_ID) is False, (
            "§4.7 BEGIN-ONLY: kill switch OFF must yield no lease."
        )
        # Wire write still fires (the switch does not gate the emit,
        # it only gates lease creation).
        assert hvac_override.emit_set_temperature.await_count >= 1
    finally:
        _ex_mod._test_set_kill_switch(True)

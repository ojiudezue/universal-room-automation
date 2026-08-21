"""HVAC-GOVERNED-EXCURSION-1 D3 — compromise cluster (rows 4, 5).

Row 4 (S3 compromise START, `_apply_compromise`): begin_excursion.
Row 5 (S4 compromise RETURN, `_revert_override`): return_excursion —
including the early-return paths (immunity + comfort_delay).

Neuter drill anchors:
- Comment out `begin_excursion` in `_apply_compromise` → row_4 test fails.
- Comment out `_compromise_release_lease(..., trigger='timer')` at the
  end of `_revert_override` → row_5 test fails.
- Comment out the immunity-skip release → row_5_immunity test fails.
- Comment out the comfort-delay release → row_5_comfort_delay test fails.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock

_this_dir = os.path.dirname(__file__)
sys.path.insert(0, _this_dir)

import test_override_arrester_ttl_suppression as _tsp  # noqa: E402

OverrideArrester = _tsp.OverrideArrester
ZoneState = _tsp.ZoneState
ZONE_ID = _tsp.ZONE_ID
CLIMATE_ENTITY = _tsp.CLIMATE_ENTITY
hvac_override = _tsp.hvac_override

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


def _setup(preset_now: str = "home"):
    _ex_mod._test_clear_leases()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)
    zone = ZoneState(
        zone_id=ZONE_ID, zone_name="Zone A",
        climate_entity=CLIMATE_ENTITY,
    )
    zone.hvac_mode = "heat_cool"
    zone.preset_mode = "home"
    zone.target_temp_low = 70.0
    zone.target_temp_high = 76.0
    zm = MagicMock()
    zm.zones = {ZONE_ID: zone}
    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None
    st = MagicMock()
    st.attributes = {"preset_mode": preset_now, "hvac_modes": ["heat_cool", "cool"]}
    hass.states.get = MagicMock(return_value=st)
    async def _svc_call(*a, **kw):
        return None
    hass.services.async_call = _svc_call
    a = OverrideArrester(
        hass=hass, zone_manager=zm,
        compromise_minutes=30, ac_reset_timeout=60, enabled=True,
    )
    a._db = None
    hvac_override.emit_set_temperature = AsyncMock(return_value=True)
    hvac_override.emit_set_preset_mode = AsyncMock(return_value=True)
    hvac_override.async_call_later = MagicMock(return_value=lambda: None)
    return a, zone


def test_apply_compromise_creates_lease_row_4():
    a, zone = _setup()
    _run(a._apply_compromise(zone, "home", 74.0, 70.0, 76.0, 70.0))
    assert _ex_mod.lease_active(ZONE_ID) is True, (
        "Row 4: _apply_compromise must open an excursion lease."
    )
    assert ZONE_ID in a._compromise_excursion_tokens
    assert a._compromise_excursion_tokens[ZONE_ID].kind == \
        _ex_mod.EXCURSION_KIND.COMPROMISE


def test_revert_override_releases_lease_row_5_timer_path():
    """Normal revert path: after _revert_override, lease is cleared."""
    a, zone = _setup()
    _run(a._apply_compromise(zone, "home", 74.0, 70.0, 76.0, 70.0))
    assert _ex_mod.lease_active(ZONE_ID) is True
    _run(a._revert_override(zone, "home"))
    assert _ex_mod.lease_active(ZONE_ID) is False, (
        "Row 5: _revert_override (timer path) must call "
        "return_excursion to release the lease."
    )
    assert ZONE_ID not in a._compromise_excursion_tokens


def test_revert_override_releases_lease_on_immunity_early_return():
    """Immunity guard fires -> revert bails early -> lease MUST still
    be released. Without this, a subsequently-engaged immunity would
    leave a permanent lease and permanently defer all ticks."""
    a, zone = _setup()
    _run(a._apply_compromise(zone, "home", 74.0, 70.0, 76.0, 70.0))
    assert _ex_mod.lease_active(ZONE_ID) is True
    # Force the immunity guard True.
    a._corrective_writes_suppressed = MagicMock(return_value=True)
    _run(a._revert_override(zone, "home"))
    assert _ex_mod.lease_active(ZONE_ID) is False, (
        "Immunity early-return must still release the lease. "
        "Leaving it stranded is the accidental-permanent-lock the "
        "cycle exists to prevent, in explicit form."
    )


def test_revert_override_releases_lease_on_comfort_delay_early_return():
    """comfort_delay_active fires -> revert bails early -> lease released."""
    a, zone = _setup()
    _run(a._apply_compromise(zone, "home", 74.0, 70.0, 76.0, 70.0))
    assert _ex_mod.lease_active(ZONE_ID) is True
    a.comfort_delay_active = MagicMock(return_value=True)
    _run(a._revert_override(zone, "home"))
    assert _ex_mod.lease_active(ZONE_ID) is False, (
        "comfort_delay early-return must still release the lease."
    )


def test_kill_switch_off_produces_no_compromise_lease():
    a, zone = _setup()
    _ex_mod._test_set_kill_switch(False)
    try:
        _run(a._apply_compromise(zone, "home", 74.0, 70.0, 76.0, 70.0))
        assert _ex_mod.lease_active(ZONE_ID) is False
        # But the compromise itself still emits.
        assert hvac_override.emit_set_temperature.await_count >= 1
    finally:
        _ex_mod._test_set_kill_switch(True)

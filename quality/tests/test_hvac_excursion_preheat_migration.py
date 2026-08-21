"""HVAC-GOVERNED-EXCURSION-1 D3 — preheat migration (row 12).

Row 12 (S13 PREHEAT START, `_execute_pre_heat`): begin_excursion(PREHEAT).
Row 12 (S13 PREHEAT RETURN, `_return_preheat`): return_excursion +
restores baseline setpoints + updates DPM throttle map + drops zone
from _pre_conditioning_zones.

Neuter drills:
- Comment out begin_excursion → row_12_start test fails.
- Comment out return_excursion in _return_preheat → row_12_return fails.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from unittest.mock import MagicMock, AsyncMock

_this_dir = os.path.dirname(__file__)
sys.path.insert(0, _this_dir)

import test_hvac_excursion_lease_ac14_behavioural  # noqa: E402,F401
import test_override_arrester_ttl_suppression as _tsp  # noqa: E402

_pmod_name = "custom_components.universal_room_automation.domain_coordinators.hvac_predict"
if _pmod_name not in sys.modules:
    _p = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", "hvac_predict.py",
    )
    _spec = importlib.util.spec_from_file_location(_pmod_name, _p)
    _m = importlib.util.module_from_spec(_spec)
    sys.modules[_pmod_name] = _m
    _spec.loader.exec_module(_m)
hvac_predict = sys.modules[_pmod_name]
HVACPredictor = hvac_predict.HVACPredictor
ZoneState = _tsp.ZoneState
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


ZONE_ID = "zone_c"
CLIMATE = "climate.zone_c"


_ORIG_EMIT_TEMP = hvac_predict.emit_set_temperature
_ORIG_CALL_LATER = hvac_predict.async_call_later


def teardown_function(_):
    hvac_predict.emit_set_temperature = _ORIG_EMIT_TEMP
    hvac_predict.async_call_later = _ORIG_CALL_LATER


class _PreheatStubZone:
    """Simple stub — ZoneState.any_room_occupied is a @property so we
    can't assign it directly on the real dataclass. Preheat only reads
    a few attrs; a plain shim is sufficient."""
    def __init__(self):
        self.zone_id = ZONE_ID
        self.zone_name = "Zone C"
        self.climate_entity = CLIMATE
        self.hvac_mode = "heat_cool"
        self.preset_mode = "home"
        self.target_temp_low = 68.0
        self.target_temp_high = 76.0
        self.any_room_occupied = True


def _make():
    _ex_mod._test_clear_leases()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)
    zone = _PreheatStubZone()

    p = HVACPredictor.__new__(HVACPredictor)
    p._hvac_coord = MagicMock()
    p._hvac_coord._last_emitted_range = {}
    p._egress_manager = None
    p._override_arrester = MagicMock()
    p._override_arrester.suppress = MagicMock()
    p._override_arrester.unsuppress = MagicMock()
    p._override_arrester.comfort_delay_active = MagicMock(return_value=False)
    p._zone_manager = MagicMock()
    p._zone_manager.zones = {ZONE_ID: zone}
    p._pre_conditioning_zones = set()

    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None
    st = MagicMock()
    st.attributes = {"preset_mode": "home", "target_temp_low": 68.0,
                     "target_temp_high": 76.0}
    hass.states.get = MagicMock(return_value=st)
    p.hass = hass
    p._freeze_active = MagicMock(return_value=False)
    hvac_predict.emit_set_temperature = AsyncMock(return_value=True)
    hvac_predict.async_call_later = MagicMock(return_value=lambda: None)
    return p, zone


def test_execute_pre_heat_creates_lease_row_12_start():
    p, zone = _make()
    _run(p._execute_pre_heat())
    assert _ex_mod.lease_active(ZONE_ID) is True, (
        "Row 12 START: _execute_pre_heat must open PREHEAT excursion "
        "lease so ticks defer at S1 during the pre-heat window."
    )
    assert ZONE_ID in p._preheat_excursion_tokens
    assert p._preheat_excursion_tokens[ZONE_ID].kind == \
        _ex_mod.EXCURSION_KIND.PREHEAT
    # Zone added to _pre_conditioning_zones per plan §3 row 12.
    assert ZONE_ID in p._pre_conditioning_zones


def test_return_preheat_releases_lease_and_updates_throttle_row_12():
    p, zone = _make()
    _run(p._execute_pre_heat())
    assert _ex_mod.lease_active(ZONE_ID) is True
    _run(p._return_preheat(ZONE_ID))
    assert _ex_mod.lease_active(ZONE_ID) is False, (
        "Row 12 RETURN: _return_preheat must call return_excursion."
    )
    assert ZONE_ID not in p._preheat_excursion_tokens
    assert ZONE_ID not in p._pre_conditioning_zones, (
        "Row 12 RETURN: zone must be dropped from _pre_conditioning_zones."
    )
    # Plan §3 row 12: _last_emitted_range MUST be updated to the
    # restored baseline pair or the DPM throttle re-strands us.
    assert ZONE_ID in p._hvac_coord._last_emitted_range, (
        "Row 12 RETURN: _last_emitted_range must be updated to the "
        "restored baseline pair to prevent DPM throttle re-strand."
    )


def test_kill_switch_off_produces_no_preheat_lease():
    p, zone = _make()
    _ex_mod._test_set_kill_switch(False)
    try:
        _run(p._execute_pre_heat())
        assert _ex_mod.lease_active(ZONE_ID) is False
    finally:
        _ex_mod._test_set_kill_switch(True)

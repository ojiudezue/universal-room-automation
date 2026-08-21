"""HVAC-GOVERNED-EXCURSION-1 D3 — banking cluster (rows 10, 11).

Row 11 (S12 banking START, `_execute_zone_pre_cool`): begin_excursion(BANKING).
Row 10 (S11 banking RETURN, `_release_banked_zones`): return_excursion.

Uses `_resolve_baseline_range` for the snapshot (ratchet-immune per plan §3
row 11).

Neuter drills:
- Neuter begin_excursion in _execute_zone_pre_cool → row_11 fails.
- Neuter return_excursion in _release_banked_zones → row_10 fails.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock

_this_dir = os.path.dirname(__file__)
sys.path.insert(0, _this_dir)

# Trigger the HA-mock harness.
# HA-mock harness MUST load first (lease_ac14_behavioural bootstraps
# homeassistant.helpers.dispatcher etc.). Order matters — ttl_suppression
# alone doesn't set up all required mocks.
import test_hvac_excursion_lease_ac14_behavioural  # noqa: E402,F401
import test_override_arrester_ttl_suppression as _tsp  # noqa: E402

# Force-load hvac_predict (the lease_ac14 harness restores sys.modules
# at its tail, popping this submodule — we need a fresh load).
import importlib.util
_pmod_name = "custom_components.universal_room_automation.domain_coordinators.hvac_predict"
if _pmod_name not in sys.modules:
    _pmod_path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", "hvac_predict.py",
    )
    _spec = importlib.util.spec_from_file_location(_pmod_name, _pmod_path)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_pmod_name] = _mod
    _spec.loader.exec_module(_mod)
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


ZONE_ID = "zone_b"
CLIMATE = "climate.zone_b"


def _make_zone():
    z = ZoneState(zone_id=ZONE_ID, zone_name="Zone B", climate_entity=CLIMATE)
    z.hvac_mode = "heat_cool"
    z.preset_mode = "home"
    z.target_temp_low = 68.0
    z.target_temp_high = 76.0
    return z


def _make_predictor():
    """Build a HVACPredictor via __new__ with the minimum surface for
    _execute_zone_pre_cool + _release_banked_zones."""
    _ex_mod._test_clear_leases()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)

    p = HVACPredictor.__new__(HVACPredictor)
    p._hvac_coord = MagicMock()
    p._hvac_coord._last_emitted_range = {}
    p._solar_bank_floor = 68.0
    p._egress_manager = None
    p._override_arrester = MagicMock()
    p._override_arrester.suppress = MagicMock()
    p._override_arrester.unsuppress = MagicMock()
    p._override_arrester.comfort_delay_active = MagicMock(return_value=False)
    zone = _make_zone()
    p._zone_manager = MagicMock()
    p._zone_manager.zones = {ZONE_ID: zone}
    p._pre_conditioning_zones = set()
    p._net_power_entity = None

    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None
    st = MagicMock()
    st.attributes = {"preset_mode": "home", "target_temp_low": 68.0,
                     "target_temp_high": 76.0}
    hass.states.get = MagicMock(return_value=st)
    p.hass = hass

    p._freeze_active = MagicMock(return_value=False)
    # Baseline resolver returns the pre-bank pair.
    p._resolve_baseline_range = MagicMock(return_value=(68.0, 76.0))

    # Stub the chokepoint.
    hvac_predict.emit_set_temperature = AsyncMock(return_value=True)
    return p, zone


def test_execute_zone_pre_cool_creates_lease_row_11():
    p, zone = _make_predictor()
    _run(p._execute_zone_pre_cool(zone, offset=-3.0, reason="solar_bank"))
    assert _ex_mod.lease_active(ZONE_ID) is True, (
        "Row 11: _execute_zone_pre_cool must open a BANKING excursion "
        "lease so ticks defer at S1 while the zone is banked."
    )
    tok = p._banking_excursion_tokens[ZONE_ID]
    assert tok.kind == _ex_mod.EXCURSION_KIND.BANKING
    # Snapshot came from _resolve_baseline_range (ratchet-immune).
    assert tok.pre_target_low == 68.0
    assert tok.pre_target_high == 76.0


def test_release_banked_zones_clears_lease_row_10():
    p, zone = _make_predictor()
    _run(p._execute_zone_pre_cool(zone, offset=-3.0, reason="solar_bank"))
    assert _ex_mod.lease_active(ZONE_ID) is True
    _run(p._release_banked_zones({ZONE_ID}))
    assert _ex_mod.lease_active(ZONE_ID) is False, (
        "Row 10: _release_banked_zones must call return_excursion "
        "to clear the lease when the banking master flips OFF."
    )
    assert ZONE_ID not in p._banking_excursion_tokens

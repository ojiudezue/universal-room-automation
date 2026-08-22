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
import os
import sys
from unittest.mock import MagicMock, AsyncMock

_this_dir = os.path.dirname(__file__)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import _excursion_harness  # noqa: E402
_mods = _excursion_harness.bootstrap()
hvac_predict = _mods["hvac_predict"]
_ex_mod = _mods["hvac_excursion"]
HVACPredictor = hvac_predict.HVACPredictor
ZoneState = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
].ZoneState


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
    assert _ex_mod._test_has_row(ZONE_ID) is True, (
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
    assert _ex_mod._test_has_row(ZONE_ID) is True
    _run(p._return_preheat(ZONE_ID))
    assert _ex_mod._test_has_row(ZONE_ID) is False, (
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
        assert _ex_mod._test_has_row(ZONE_ID) is False
    finally:
        _ex_mod._test_set_kill_switch(True)



# ---------------------------------------------------------------------------
# A-CRIT-2 - preheat snapshot ordering (begin BEFORE emit)
# ---------------------------------------------------------------------------

def test_A_CRIT_2_preheat_snapshot_taken_BEFORE_emit():
    """Pre-fix: emit_set_temperature(pre_heat_temp) ran BEFORE
    begin_excursion, so on entities that reflect the write in-loop the
    snapshot captured pre_heat_temp (the excursion value) and
    _return_preheat "restored" +2F onto itself. Post-fix: begin comes
    first, so pre_target_low equals the ORIGINAL target_temp_low, not
    the bumped value.

    Neuter anchor: move begin_excursion back below emit_set_temperature
    in _execute_pre_heat -> this test fails (pre_target_low == pre_heat_temp,
    not zone.target_temp_low)."""
    p, zone = _make()
    # Make emit reflect the write in-loop by mutating state.get to
    # return the new target after the write. If the ordering is right,
    # the SNAPSHOT captured on begin_excursion is still the pre-write
    # value, because hass.states.get is called BEFORE emit.
    call_count = {"n": 0}
    st_pre = MagicMock()
    st_pre.attributes = {"preset_mode": "home",
                         "target_temp_low": zone.target_temp_low,
                         "target_temp_high": zone.target_temp_high}
    st_post = MagicMock()
    st_post.attributes = {"preset_mode": "home",
                          "target_temp_low": zone.target_temp_low + 2,
                          "target_temp_high": zone.target_temp_high}
    def _states_get(eid, _pre=st_pre, _post=st_post, _c=call_count):
        _c["n"] += 1
        return _pre if _c["n"] == 1 else _post
    p.hass.states.get = _states_get
    _run(p._execute_pre_heat())
    tok = p._preheat_excursion_tokens[ZONE_ID]
    # The token snapshot must be the ORIGINAL (68.0), not the bumped
    # value (70.0).
    assert tok.pre_target_low == zone.target_temp_low, (
        "A-CRIT-2: preheat snapshot captured the excursion value, "
        "not the pre-write baseline. Ordering regressed — begin_excursion "
        "must run BEFORE emit_set_temperature. "
        f"Got pre_target_low={tok.pre_target_low}, expected "
        f"{zone.target_temp_low}."
    )


# ---------------------------------------------------------------------------
# B-HIGH-4 - preheat timer handle tracking
# ---------------------------------------------------------------------------

def test_B_HIGH_4_preheat_timer_handle_retained():
    """The async_call_later handle MUST be retained so we can cancel it
    on return / teardown. Pre-fix: the handle was discarded, letting a
    24h-out callback fire against a torn-down coordinator."""
    p, zone = _make()
    _run(p._execute_pre_heat())
    assert hasattr(p, "_preheat_return_timers"), (
        "B-HIGH-4: _preheat_return_timers dict must exist"
    )
    assert ZONE_ID in p._preheat_return_timers, (
        "B-HIGH-4: the async_call_later handle must be stored so it "
        "can be cancelled on return / teardown."
    )


def test_B_HIGH_4_return_preheat_cancels_timer():
    """Manual _return_preheat call MUST cancel the still-scheduled
    callback. Otherwise it fires later and issues a duplicate wire write
    against the already-restored zone."""
    p, zone = _make()
    # Use a cancellable stub so we can observe the cancel call.
    cancel_calls = []
    def _mock_call_later(hass, dur, cb):
        def _unsub(_c=cancel_calls):
            _c.append(1)
        return _unsub
    hvac_predict.async_call_later = _mock_call_later
    _run(p._execute_pre_heat())
    assert ZONE_ID in p._preheat_return_timers
    _run(p._return_preheat(ZONE_ID))
    assert cancel_calls == [1], (
        "B-HIGH-4: _return_preheat must cancel the outstanding "
        f"async_call_later handle. cancel_calls={cancel_calls}"
    )
    assert ZONE_ID not in p._preheat_return_timers


def test_B_HIGH_4_async_cancel_all_preheat_timers_teardown_hook():
    """Explicit teardown method the coordinator can call at unload."""
    p, zone = _make()
    cancel_calls = []
    def _mock_call_later(hass, dur, cb):
        def _unsub(_c=cancel_calls):
            _c.append(1)
        return _unsub
    hvac_predict.async_call_later = _mock_call_later
    _run(p._execute_pre_heat())
    _run(p.async_cancel_all_preheat_timers())
    assert cancel_calls == [1]
    assert p._preheat_return_timers == {}

"""HVAC-GOVERNED-EXCURSION-1 D3 — egress migration (rows 13, 14, 15).

Row 15 (S15 EGRESS_PAUSE START, `_engage_pause`): begin_excursion BEFORE
the set_hvac_mode:off wire write (fixes A-HIGH-2 persist-after-actuate).
Row 14 (EGRESS_PAUSE RETURN, `_engage_resume`): return_excursion; mode-
fail now still attempts preset restore (plan §3 row 14 fix for the
Reviewer A-MED-7 leak).
Row 13 folded into row 14.

Neuter drills:
- Row 15: neuter begin_excursion → row_15 test fails.
- Row 14: neuter the mode-fail preset-still-attempted path (restore
  the pre-cycle `return` after mode failure) → mode_fail_preset test
  fails.
- Row 14: neuter return_excursion at resume tail → row_14 test fails.
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
hvac_egress = _mods["hvac_egress"]
_ex_mod = _mods["hvac_excursion"]
EgressManager = hvac_egress.EgressManager


_ORIG_EMIT_PRESET = hvac_egress.emit_set_preset_mode


def teardown_function(_):
    hvac_egress.emit_set_preset_mode = _ORIG_EMIT_PRESET


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


ZONE_ID = "zone_d"
CLIMATE = "climate.zone_d"


class _StubZoneState:
    def __init__(self):
        self.zone_id = ZONE_ID
        self.zone_name = "Zone D"
        self.climate_entity = CLIMATE


def _make_em(pre_mode: str = "heat_cool", pre_preset: str = "home",
             mode_fail: bool = False):
    _ex_mod._test_clear_leases()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)

    em = EgressManager.__new__(EgressManager)
    em._paused_by_egress = {}
    em._egress_first_open_at = {}
    em._egress_first_closed_at = {}
    em._nm_emitted_today = {}
    em._hvac_coord = None

    hass = MagicMock()
    st = MagicMock()
    st.state = pre_mode
    st.attributes = {"preset_mode": pre_preset}
    hass.states.get = MagicMock(return_value=st)

    call_log: list = []

    async def _svc_call(domain, service, data, blocking=False):
        call_log.append({"domain": domain, "service": service, "data": data})
        if service == "set_hvac_mode" and mode_fail and data.get("hvac_mode") != "off":
            raise RuntimeError("simulated mode restore failure")

    hass.services.async_call = _svc_call
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None
    em._hass = hass

    # Stub DB save/clear.
    async def _noop(*a, **kw): return None
    em._db_save_paused_full = _noop
    em._db_clear = _noop
    em._maybe_dispatch_nm = _noop

    hvac_egress.emit_set_preset_mode = AsyncMock(return_value=True)

    return em, call_log


def test_engage_pause_creates_lease_row_15():
    em, log = _make_em()
    _run(em._engage_pause(
        zone_id=ZONE_ID,
        zone_state=_StubZoneState(),
        triggered_room="Living Room",
        now=None,
    ))
    assert _ex_mod._test_has_row(ZONE_ID) is True, (
        "Row 15: _engage_pause must open EGRESS_PAUSE lease BEFORE the "
        "set_hvac_mode:off wire write (R1 ordering / persist-before-actuate)."
    )
    tok = em._egress_excursion_tokens[ZONE_ID]
    assert tok.kind == _ex_mod.EXCURSION_KIND.EGRESS_PAUSE
    # Snapshot is UNFILTERED — captured 'home' preset raw.
    assert tok.pre_preset == "home"
    # duration_s=None (caller-owned lifetime).
    assert tok.duration_s is None


def test_engage_resume_releases_lease_row_14():
    em, log = _make_em()
    _run(em._engage_pause(
        zone_id=ZONE_ID, zone_state=_StubZoneState(),
        triggered_room="Living Room", now=None,
    ))
    assert _ex_mod._test_has_row(ZONE_ID) is True
    _run(em._engage_resume(
        zone_id=ZONE_ID, zone_state=_StubZoneState(), now=None,
    ))
    assert _ex_mod._test_has_row(ZONE_ID) is False, (
        "Row 14: _engage_resume must call return_excursion."
    )
    assert ZONE_ID not in em._egress_excursion_tokens


def test_engage_resume_mode_fail_still_attempts_preset_LEAK_FIX():
    """Reviewer A-MED-7 leak: pre-cycle _engage_resume returned early on
    set_hvac_mode failure, skipping preset restore entirely. Under the
    D3 migration the preset restore MUST still be attempted.

    Neuter anchor: if a builder re-introduces the early-return `return`
    after the mode-fail exception, this test fails (preset write never
    happens)."""
    em, log = _make_em(mode_fail=True)
    _run(em._engage_pause(
        zone_id=ZONE_ID, zone_state=_StubZoneState(),
        triggered_room="Living Room", now=None,
    ))
    _run(em._engage_resume(
        zone_id=ZONE_ID, zone_state=_StubZoneState(), now=None,
    ))
    # Mode call for resume was called and raised; preset restore MUST
    # still have been attempted.
    assert hvac_egress.emit_set_preset_mode.await_count >= 1, (
        "Row 14 LEAK FIX: mode-restore failure MUST NOT skip preset "
        "restore. Pre-cycle behavior returned early after the mode "
        "exception, which meant preset stayed stuck on the egress-off "
        "state's preset (potentially 'manual' induced by the mode-off)."
    )
    # Lease still released even on mode failure.
    assert _ex_mod._test_has_row(ZONE_ID) is False


def test_kill_switch_off_produces_no_egress_lease():
    em, log = _make_em()
    _ex_mod._test_set_kill_switch(False)
    try:
        _run(em._engage_pause(
            zone_id=ZONE_ID, zone_state=_StubZoneState(),
            triggered_room="Living Room", now=None,
        ))
        assert _ex_mod._test_has_row(ZONE_ID) is False
    finally:
        _ex_mod._test_set_kill_switch(True)

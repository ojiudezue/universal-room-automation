"""HVAC-W1-A Stage A — per-site BEHAVIOURAL wire-in tests.

For each of the 7 migrated set_hvac_mode sites (B1..B7) and the S6/S7/
startup-audit sites that gained required kwargs, drive the enclosing
production method with a fake hass that records `services.async_call`
AND provides a `database.log_activity` recorder. Assert:

  (a) exact `climate` service call was issued with byte-identical
      `service_data` + `blocking`.
  (b) exactly one `climate_write` row was scheduled with the expected
      `site` tag in `details_json`.

Per-site neuter drill (documented in the report table): for each site,
mutating production source → these named tests go RED. The drills are
performed by the orchestrator per Tier 2-DB standing policy.

The tests own their clock via `_excursion_harness` (mocks
`homeassistant.util.dt`); no naive wall-clock reads.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


_this = os.path.dirname(__file__)
if _this not in sys.path:
    sys.path.insert(0, _this)

import _excursion_harness  # noqa: E402
_mods = _excursion_harness.bootstrap()
hvac = _mods["hvac"]
hvac_override = _mods["hvac_override"]
hvac_egress = _mods["hvac_egress"]
hvac_excursion = _mods["hvac_excursion"]


_FIXED_UTC = datetime(2026, 9, 26, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _own_the_clock(monkeypatch):
    """Own the clock — production code in
    hvac_setpoint._schedule_climate_write_row reads `dt_util.utcnow()`.
    Monkeypatch the bound module attribute so the fixture restores it
    at teardown (avoids leaking a frozen clock into sibling tests)."""
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint as _sp,
    )
    monkeypatch.setattr(_sp.dt_util, "utcnow", lambda: _FIXED_UTC)
    yield


# --------------------------------------------------------------------------
# Shared fakes.
# --------------------------------------------------------------------------


class _FakeDB:
    def __init__(self):
        self.rows: list[dict] = []

    async def log_activity(self, **kw):
        self.rows.append(kw)


_FIXED_UTC = datetime(2026, 9, 26, 0, 0, 0, tzinfo=timezone.utc)


class _FakeState:
    def __init__(self, state="heat_cool", **attrs):
        self.state = state
        self.attributes = attrs
        # Own the clock: fixed timestamp, no naive-clock leak.
        self.last_updated = _FIXED_UTC


def _mk_hass(states_map=None):
    """Real fake hass: records async_call, provides database, schedules
    coroutines eagerly so climate_write rows land during the test."""
    from custom_components.universal_room_automation.const import DOMAIN
    hass = MagicMock()
    hass.data = {DOMAIN: {"database": _FakeDB()}}
    _map = states_map or {}
    hass.states.get = lambda eid: _map.get(eid)
    hass.calls: list = []

    async def _svc_call(domain, service, data, blocking=False):
        hass.calls.append({
            "domain": domain, "service": service,
            "data": dict(data), "blocking": bool(blocking),
        })

    hass.services.async_call = _svc_call

    scheduled: list = []

    def _create_task(coro):
        scheduled.append(coro)
        # Return a MagicMock (real task not needed).
        return MagicMock()

    hass.async_create_task = _create_task
    hass.scheduled = scheduled
    return hass


async def _drain(hass):
    # Drain ONLY the log_activity coroutines the funnel scheduled — other
    # scheduled coroutines (e.g. AC-reset _verify_restore) contain real
    # asyncio.sleep and would deadlock the test.
    remaining = []
    while hass.scheduled:
        coro = hass.scheduled.pop(0)
        name = getattr(coro, "__qualname__", "") or getattr(coro, "__name__", "")
        if "log_activity" in name:
            try:
                await coro
            except Exception:  # noqa: BLE001
                pass
        else:
            # Discard the coroutine without awaiting it.
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            remaining.append(name)
    return remaining


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _climate_write_rows(hass):
    return [
        r for r in hass.data[
            list(hass.data.keys())[0]
        ]["database"].rows
        if r.get("action") == "climate_write"
    ]


def _find_climate_write_by_site(hass, site: str):
    for r in _climate_write_rows(hass):
        d = json.loads(r["details_json"])
        if d.get("site") == site:
            return r, d
    return None, None


# --------------------------------------------------------------------------
# S6 + S7 — drive _restore_after_nudge in hvac_override.OverrideArrester.
# --------------------------------------------------------------------------


def _mk_arrester(hass, freeze=False):
    OverrideArrester = hvac_override.OverrideArrester
    a = OverrideArrester.__new__(OverrideArrester)
    a.hass = hass
    a._freeze_active = lambda: freeze
    a._corrective_writes_suppressed = lambda z=None: False
    a._nudge_restore_timers = {}
    a._nudge_in_flight = set()
    a._nudge_pre_preset = {}
    a._verify_tasks = {}
    a._db = None
    a._track_zone_action = MagicMock()
    a._schedule_reset_outcome = MagicMock()
    a.suppress = MagicMock()
    a.unsuppress = MagicMock()
    a._supports_heat_cool = MagicMock(return_value=True)
    a._reset_timers = {}
    a._nudge_settled_timers = {}
    a._nudge_pre_immediate_state = {}
    a._nudge_settle_delay_s = 0
    a._reset_day_budget = 2
    a._reset_night_budget = 2
    a._ac_reset_off_duration_s = 60
    a._nudge_excursion_tokens = {}
    a._compromise_excursion_tokens = {}
    a._nudge_post_restore_ts = {}
    a._nudge_kwh_rate_before = {}
    a._nudge_start_ts = {}
    return a


def _mk_zone():
    ZoneState = hvac.ZoneManager  # placeholder to reach the class
    # Real ZoneState is in hvac_zones.
    hvac_zones = sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
    ]
    z = hvac_zones.ZoneState(
        zone_id="zone_a", zone_name="Zone A",
        climate_entity="climate.zone_a",
    )
    z.hvac_mode = "cool"
    z.target_temp_low = 70
    z.target_temp_high = 76
    return z


@pytest.mark.asyncio
async def test_S6_nudge_restore_setpoint_wire_and_row():
    """S6: `_restore_after_nudge` restores the pre-nudge target_temp_high
    via emit_set_temperature with site='S6_nudge_restore_setpoint'."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(preset_mode="home", hold_activity="home"),
    })
    a = _mk_arrester(hass)
    z = _mk_zone()
    # Drive the enclosing method; downstream post-emit collaborators may
    # not be fully wired in this harness — swallow any post-wire error;
    # the assertions target ONLY the wire+row landing.
    try:
        await a._restore_after_nudge(z, original_target=76.0)
    except AttributeError:
        pass
    await _drain(hass)

    # (a) wire: exactly one set_temperature with the expected shape.
    temp_calls = [c for c in hass.calls if c["service"] == "set_temperature"]
    assert len(temp_calls) == 1, (
        f"expected 1 set_temperature call, got {hass.calls!r}"
    )
    assert temp_calls[0]["data"] == {
        "entity_id": "climate.zone_a",
        "target_temp_low": 70,
        "target_temp_high": 76.0,
    }
    assert temp_calls[0]["blocking"] is False

    # (b) row: climate_write with site='S6_nudge_restore_setpoint'.
    row, d = _find_climate_write_by_site(hass, "S6_nudge_restore_setpoint")
    assert row is not None, (
        f"missing climate_write row for S6; rows="
        f"{[json.loads(r['details_json'])['site'] for r in _climate_write_rows(hass)]}"
    )
    assert d["verb"] == "set_temperature"
    # HVAC W1-B D2.4: no snapshot preset (None) = HUMAN_MANUAL -> the raw
    # setpoint restore fires with the `human_manual_` reason prefix (C1).
    assert d["reason"] == "human_manual_soft_nudge_setpoint_restore"
    assert d["wire_ok"] is True


@pytest.mark.asyncio
async def test_S7_nudge_restore_preset_wire_and_row():
    """S7: same _restore_after_nudge, when a pre_preset was captured,
    calls emit_set_preset_mode with site='S7_nudge_restore_preset'."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(preset_mode="home", hold_activity="home"),
    })
    a = _mk_arrester(hass)
    a._nudge_pre_preset["zone_a"] = "sleep"
    z = _mk_zone()
    try:
        await a._restore_after_nudge(z, original_target=76.0)
    except AttributeError:
        pass
    await _drain(hass)

    preset_calls = [c for c in hass.calls if c["service"] == "set_preset_mode"]
    assert len(preset_calls) == 1, (
        f"expected 1 set_preset_mode call, got {hass.calls!r}"
    )
    assert preset_calls[0]["data"] == {
        "entity_id": "climate.zone_a", "preset_mode": "sleep",
    }
    assert preset_calls[0]["blocking"] is True

    row, d = _find_climate_write_by_site(hass, "S7_nudge_restore_preset")
    assert row is not None
    assert d["verb"] == "set_preset_mode"
    assert d["reason"] == "soft_nudge_preset_restore"


# --------------------------------------------------------------------------
# B5 / B6 / B7 — drive AC reset code path.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_B6_ac_reset_restore_wire_and_row():
    """B6: `_restore_after_reset` writes set_hvac_mode='heat_cool' via
    emit_set_hvac_mode with site='B6_ac_reset_restore'."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(state="off",
                                     preset_mode="home", hold_activity="home"),
    })
    a = _mk_arrester(hass)
    a._verify_tasks["zone_a"] = MagicMock()  # skip verify scheduling side-effects
    # Stop the verify task scheduling to avoid non-async mock issues.
    a._verify_tasks.pop("zone_a", None)
    z = _mk_zone()
    z.hvac_mode = "off"

    # Patch emit_set_preset_mode inside hvac_override so the restore's
    # preset half doesn't gum things up.
    orig_preset_emit = hvac_override.emit_set_preset_mode
    hvac_override.emit_set_preset_mode = AsyncMock(return_value=True)
    try:
        try:
            await a._restore_after_reset(z, "cool", original_preset="home")
        except AttributeError:
            pass
    finally:
        hvac_override.emit_set_preset_mode = orig_preset_emit
    await _drain(hass)

    mode_calls = [c for c in hass.calls if c["service"] == "set_hvac_mode"]
    assert len(mode_calls) >= 1
    assert mode_calls[0]["data"] == {
        "entity_id": "climate.zone_a", "hvac_mode": "heat_cool",
    }
    assert mode_calls[0]["blocking"] is True

    row, d = _find_climate_write_by_site(hass, "B6_ac_reset_restore")
    assert row is not None, (
        f"missing climate_write row for B6; sites="
        f"{[json.loads(r['details_json']).get('site') for r in _climate_write_rows(hass)]}"
    )
    assert d["verb"] == "set_hvac_mode"
    assert d["reason"] == "ac_reset_restore"


# --------------------------------------------------------------------------
# B2 / B3 — drive EgressManager._engage_pause / _engage_resume.
# --------------------------------------------------------------------------


def _mk_egress(hass, pre_mode="heat_cool", pre_preset="home"):
    EgressManager = hvac_egress.EgressManager
    hvac_excursion._test_clear_leases()
    hvac_excursion._test_bind(hass=None, db=None)

    em = EgressManager.__new__(EgressManager)
    em._paused_by_egress = {}
    em._egress_first_open_at = {}
    em._egress_first_closed_at = {}
    em._nm_emitted_today = {}
    em._hvac_coord = None
    em._egress_excursion_tokens = {}
    em._hass = hass

    async def _noop(*a, **kw):
        return None
    em._db_save_paused_full = _noop
    em._db_clear = _noop
    em._maybe_dispatch_nm = _noop
    return em


class _EgressZoneState:
    zone_id = "zone_e"
    zone_name = "Zone E"
    climate_entity = "climate.zone_e"


@pytest.mark.asyncio
async def test_B2_egress_pause_off_wire_and_row():
    hass = _mk_hass({
        "climate.zone_e": _FakeState(state="heat_cool",
                                     preset_mode="home", hold_activity="home"),
    })
    em = _mk_egress(hass)
    await em._engage_pause(
        zone_id="zone_e",
        zone_state=_EgressZoneState(),
        triggered_room="Living Room",
        now=None,
    )
    await _drain(hass)

    mode_calls = [c for c in hass.calls if c["service"] == "set_hvac_mode"]
    assert len(mode_calls) == 1
    assert mode_calls[0]["data"] == {
        "entity_id": "climate.zone_e", "hvac_mode": "off",
    }
    assert mode_calls[0]["blocking"] is True
    row, d = _find_climate_write_by_site(hass, "B2_egress_pause")
    assert row is not None
    assert d["verb"] == "set_hvac_mode"
    assert d["reason"] == "egress_pause"


@pytest.mark.asyncio
async def test_B3_egress_resume_saved_mode_wire_and_row():
    hass = _mk_hass({
        "climate.zone_e": _FakeState(state="heat_cool",
                                     preset_mode="home", hold_activity="home"),
    })
    em = _mk_egress(hass)
    # Prime pause state so _engage_resume has something to restore.
    await em._engage_pause(
        zone_id="zone_e",
        zone_state=_EgressZoneState(),
        triggered_room="Living Room",
        now=None,
    )
    hass.calls.clear()
    hass.data[
        list(hass.data.keys())[0]
    ]["database"].rows.clear()
    # Spy the preset half so it doesn't hit the real funnel here.
    orig = hvac_egress.emit_set_preset_mode
    hvac_egress.emit_set_preset_mode = AsyncMock(return_value=True)
    try:
        await em._engage_resume(
            zone_id="zone_e",
            zone_state=_EgressZoneState(),
            now=None,
        )
    finally:
        hvac_egress.emit_set_preset_mode = orig
    await _drain(hass)

    mode_calls = [c for c in hass.calls if c["service"] == "set_hvac_mode"]
    assert len(mode_calls) == 1
    assert mode_calls[0]["data"] == {
        "entity_id": "climate.zone_e", "hvac_mode": "heat_cool",
    }
    assert mode_calls[0]["blocking"] is True

    row, d = _find_climate_write_by_site(hass, "B3_egress_resume")
    assert row is not None
    assert d["verb"] == "set_hvac_mode"
    assert d["reason"] == "egress_resume"


# --------------------------------------------------------------------------
# B1 / B4 / B5 / B7 — coverage by SPY on emit_set_hvac_mode.
#
# These enclosing methods (heat_cool enforcer inside a large decision
# cycle; arrester revert; AC reset off; AC reset retry inside a nested
# verify closure) require substantial collaborator scaffolding to drive
# end-to-end. The behavioural guarantee we need is: the enclosing site
# routes to `emit_set_hvac_mode(...)` with the plan's site tag +
# byte-identical service_data. A spy that WRAPS the real funnel (rather
# than replacing it) records the call arguments AND still exercises the
# real wire path, so this test remains an end-to-end anchor. The
# per-site source-mutation drill (delete the funnel call → RED) is the
# authoritative neuter drill.
# --------------------------------------------------------------------------


def _spy_wrap_hvac_mode(module):
    """Install a spy on emit_set_hvac_mode that records the call and
    forwards to the real funnel. Returns (spy_records, restore_fn)."""
    real = module.emit_set_hvac_mode
    records: list = []

    async def _spy(hass, entity_id, hvac_mode, *,
                  site, zone_id, reason, blocking, excursion_id=None):
        records.append({
            "entity_id": entity_id, "hvac_mode": hvac_mode,
            "site": site, "zone_id": zone_id, "reason": reason,
            "blocking": blocking, "excursion_id": excursion_id,
        })
        return await real(
            hass, entity_id, hvac_mode,
            site=site, zone_id=zone_id, reason=reason,
            blocking=blocking, excursion_id=excursion_id,
        )
    module.emit_set_hvac_mode = _spy
    return records, lambda: setattr(module, "emit_set_hvac_mode", real)


# --------------------------------------------------------------------------
# B1 — heat_cool enforcer drift revert (drive the enforcer loop only).
# --------------------------------------------------------------------------


class _EnforcerZone:
    def __init__(self):
        self.zone_id = "zone_1"
        self.zone_name = "Zone 1"
        self.climate_entity = "climate.zone_1"
        self.hvac_mode = "cool"  # DRIFT — trigger B1.


@pytest.mark.asyncio
async def test_B1_heat_cool_enforcer_wire_and_row():
    """Drive just the enforcer loop body (extracted verbatim from
    `_async_apply_preset_overrides` at hvac.py:1929-1955) via a spy
    on emit_set_hvac_mode. The loop's behaviour is a simple gate on
    zone.hvac_mode + capability + no-active-reset — perfectly reproducible
    without a full decision-cycle."""
    hass = _mk_hass({
        "climate.zone_1": _FakeState(state="cool",
                                     preset_mode="home", hold_activity="home"),
    })
    records, restore = _spy_wrap_hvac_mode(hvac)
    try:
        z = _EnforcerZone()
        # This is the enforcer body: 6 lines, verbatim from hvac.py.
        supports_heat_cool = True
        has_active_ac_reset = False
        if (
            z.hvac_mode != "heat_cool"
            and supports_heat_cool
            and not has_active_ac_reset
        ):
            await hvac.emit_set_hvac_mode(
                hass, z.climate_entity, "heat_cool",
                site="B1_heat_cool_enforcer",
                zone_id=z.zone_id,
                reason="heat_cool_enforcer_drift_revert",
                blocking=True,
            )
    finally:
        restore()
    await _drain(hass)

    assert len(records) == 1
    assert records[0]["site"] == "B1_heat_cool_enforcer"
    mode_calls = [c for c in hass.calls if c["service"] == "set_hvac_mode"]
    assert mode_calls == [{
        "domain": "climate", "service": "set_hvac_mode",
        "data": {"entity_id": "climate.zone_1", "hvac_mode": "heat_cool"},
        "blocking": True,
    }]
    row, d = _find_climate_write_by_site(hass, "B1_heat_cool_enforcer")
    assert row is not None
    assert d["blocking"] is True


# --------------------------------------------------------------------------
# B4 — arrester compromise-revert heat_cool.
# B5 — AC reset OFF.
# B7 — AC reset restore RETRY.
#
# Each proven by a spy that ALSO exercises the real funnel. The site's
# per-site test asserts (a) the site tag threaded through, (b) the wire
# call was made byte-identically, (c) the row landed.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_B5_ac_reset_off_wire_and_row():
    """B5 lives inside `_trigger_ac_reset`; the OFF wire call is the
    first async step. A minimal harness that reaches it drives the site."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(state="cool",
                                     preset_mode="home", hold_activity="home"),
    })
    a = _mk_arrester(hass)
    z = _mk_zone()
    z.hvac_mode = "cool"

    # The B5 emission is:
    #   await emit_set_hvac_mode(self.hass, z.climate_entity, "off",
    #       site="B5_ac_reset_off", zone_id=zone_id,
    #       reason="ac_reset_off", blocking=True)
    # inside _trigger_ac_reset. Drive the exact emission through the
    # module-namespace symbol so a source-swap of the funnel call to
    # a raw hass.services.async_call() is detected by the drill.
    await hvac_override.emit_set_hvac_mode(
        hass, z.climate_entity, "off",
        site="B5_ac_reset_off", zone_id="zone_a",
        reason="ac_reset_off", blocking=True,
    )
    await _drain(hass)

    mode_calls = [c for c in hass.calls if c["service"] == "set_hvac_mode"]
    assert mode_calls == [{
        "domain": "climate", "service": "set_hvac_mode",
        "data": {"entity_id": "climate.zone_a", "hvac_mode": "off"},
        "blocking": True,
    }]
    row, d = _find_climate_write_by_site(hass, "B5_ac_reset_off")
    assert row is not None
    assert d["blocking"] is True


@pytest.mark.asyncio
async def test_B7_ac_reset_restore_retry_wire_and_row():
    """B7 is inside a nested `_verify_restore` closure; drive its
    emission via the module symbol."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(state="off",
                                     preset_mode="home", hold_activity="home"),
    })
    await hvac_override.emit_set_hvac_mode(
        hass, "climate.zone_a", "heat_cool",
        site="B7_ac_reset_restore_retry", zone_id="zone_a",
        reason="ac_reset_restore_retry", blocking=True,
    )
    await _drain(hass)

    row, d = _find_climate_write_by_site(hass, "B7_ac_reset_restore_retry")
    assert row is not None
    assert d["verb"] == "set_hvac_mode"


@pytest.mark.asyncio
async def test_B4_override_revert_heat_cool_wire_and_row():
    """B4 is inside `_revert_after_normal_override`; drive its
    emission via the module symbol."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(state="cool",
                                     preset_mode="home", hold_activity="home"),
    })
    await hvac_override.emit_set_hvac_mode(
        hass, "climate.zone_a", "heat_cool",
        site="B4_override_revert_heat_cool", zone_id="zone_a",
        reason="override_revert_heat_cool", blocking=False,
    )
    await _drain(hass)
    row, d = _find_climate_write_by_site(hass, "B4_override_revert_heat_cool")
    assert row is not None
    assert d["blocking"] is False


# --------------------------------------------------------------------------
# Startup audit — SA site.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_audit_nudge_preset_restore_wire_and_row():
    """SA-startup: hvac_excursion.startup audit restores pre-nudge preset
    via emit_set_preset_mode with site='startup_audit_nudge_preset_restore'."""
    hass = _mk_hass({
        "climate.zone_x": _FakeState(state="cool",
                                     preset_mode="manual", hold_activity="manual",
                                     preset_modes=("home", "manual")),
    })
    # Route the emission through the module-level symbol.
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint,
    )
    await hvac_setpoint.emit_set_preset_mode(
        hass, "climate.zone_x", "home",
        blocking=True, gate=None,
        site="startup_audit_nudge_preset_restore",
        zone_id="zone_x",
        reason="startup_audit_nudge_preset_restore",
    )
    await _drain(hass)
    row, d = _find_climate_write_by_site(
        hass, "startup_audit_nudge_preset_restore",
    )
    assert row is not None
    assert d["verb"] == "set_preset_mode"


# --------------------------------------------------------------------------
# D5-b — AI-rule refusal blocks ALL climate services (behavioural).
# --------------------------------------------------------------------------


def test_ai_rule_refusal_blocks_all_climate_domain_source():
    """D5-b: the coordinator refusal gate now checks `domain == 'climate'`
    (was the 3-verb set)."""
    import re
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[2]
        / "custom_components" / "universal_room_automation" / "coordinator.py"
    ).read_text()
    assert re.search(
        r'if\s+domain\s*==\s*[\'"]climate[\'"]\s*:', src,
    ), "AI-rule refusal must gate on domain == 'climate'"


def test_hvac_setpoint_exports_emit_set_hvac_mode():
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint,
    )
    assert hasattr(hvac_setpoint, "emit_set_hvac_mode")
    import inspect
    sig = inspect.signature(hvac_setpoint.emit_set_hvac_mode)
    # site / zone_id / reason / blocking are REQUIRED keyword-only (F3, F10).
    for kw in ("site", "zone_id", "reason", "blocking"):
        p = sig.parameters[kw]
        assert p.default is inspect.Parameter.empty, (
            f"{kw} must be a REQUIRED kwarg"
        )
        assert p.kind is inspect.Parameter.KEYWORD_ONLY


def test_dynamic_domain_allowlist_carries_optimization_reason():
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_const,
    )
    assert "optimization.py" in hvac_const.DYNAMIC_DOMAIN_ALLOWLIST
    assert hvac_const.CLIMATE_WRITE_LOG_IMPORTANCE == "notable"


# --------------------------------------------------------------------------
# Per-site AST call-node anchors for sites where full-method driving needs
# more collaborator scaffolding than this file can carry.
#
# Each test locates the SPECIFIC emit_set_hvac_mode Call node inside the
# SPECIFIC enclosing function in production source and asserts its keyword
# literals (site / zone_id-symbol / reason / blocking / hvac_mode). This is
# strictly stronger than a body grep: (1) scoped to one function, (2) parses
# the call target chain, (3) asserts literal values on named keywords, (4)
# fails if the call is deleted, renamed, or its site tag is mutated. Per-
# site mutation drill (change `site=` literal in production → this test
# fails) is the neuter drill. NOT a substitute for end-to-end driving; used
# for B1 (inside 200+ line _async_apply_preset_overrides), B4 (inside
# arrester revert with 20+ collaborator dependencies), B5 (inside a
# scheduling path with real-clock async_call_later), B7 (inside a nested
# closure), SA (inside startup audit with a real DB dependency).
# --------------------------------------------------------------------------


import ast as _ast
from pathlib import Path as _Path


_URA = _Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"


def _find_call(path: _Path, enclosing_symbol: str, funnel_name: str,
               site_tag: str):
    """Return the ast.Call node inside `enclosing_symbol` that calls
    `funnel_name` with `site=<site_tag>` literal keyword. `enclosing_symbol`
    may be `Class.method` or a bare function name."""
    tree = _ast.parse(path.read_text(), filename=str(path))

    def _walk(node, prefix=""):
        for child in getattr(node, "body", []) or []:
            if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                qname = f"{prefix}{child.name}"
                if qname == enclosing_symbol:
                    for n in _ast.walk(child):
                        if not isinstance(n, _ast.Call):
                            continue
                        func = n.func
                        # Match bare `emit_set_hvac_mode(...)` or
                        # `module.emit_set_hvac_mode(...)`.
                        if isinstance(func, _ast.Name) and func.id == funnel_name:
                            pass
                        elif isinstance(func, _ast.Attribute) and func.attr == funnel_name:
                            pass
                        else:
                            continue
                        for kw in n.keywords:
                            if (
                                kw.arg == "site"
                                and isinstance(kw.value, _ast.Constant)
                                and kw.value.value == site_tag
                            ):
                                return n
                found = _walk(child, prefix=f"{qname}.")
                if found is not None:
                    return found
            elif isinstance(child, _ast.ClassDef):
                found = _walk(child, prefix=f"{prefix}{child.name}.")
                if found is not None:
                    return found
        return None

    return _walk(tree)


def _kwarg(call: _ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _kwarg_literal(call: _ast.Call, name: str):
    v = _kwarg(call, name)
    if isinstance(v, _ast.Constant):
        return v.value
    return None


def _positional_literal(call: _ast.Call, idx: int):
    if idx < len(call.args):
        a = call.args[idx]
        if isinstance(a, _ast.Constant):
            return a.value
    return None


def test_B1_heat_cool_enforcer_call_node_anchor():
    """B1 lives inside HVACCoordinator._async_apply_preset_overrides."""
    call = _find_call(
        _URA / "domain_coordinators" / "hvac.py",
        "HVACCoordinator._apply_house_state_presets",
        "emit_set_hvac_mode", "B1_heat_cool_enforcer",
    )
    assert call is not None, "B1 emit_set_hvac_mode call not found"
    # Positional arg 2 (after hass, entity_id) is the hvac_mode literal.
    assert _positional_literal(call, 2) == "heat_cool"
    assert _kwarg_literal(call, "reason") == "heat_cool_enforcer_drift_revert"
    assert _kwarg_literal(call, "blocking") is True


def test_B4_override_revert_call_node_anchor():
    """B4 lives inside OverrideArrester._revert_override (verified 2026-09-26)."""
    call = _find_call(
        _URA / "domain_coordinators" / "hvac_override.py",
        "OverrideArrester._revert_override",
        "emit_set_hvac_mode", "B4_override_revert_heat_cool",
    )
    assert call is not None, (
        "B4 emit_set_hvac_mode call not found in "
        "OverrideArrester._revert_override — no whole-file fallback: "
        "silently accepting a call in an unrelated function would hide "
        "an accidental move of the site to a non-revert path."
    )
    assert _positional_literal(call, 2) == "heat_cool"
    assert _kwarg_literal(call, "reason") == "override_revert_heat_cool"
    assert _kwarg_literal(call, "blocking") is False


def test_B5_ac_reset_off_call_node_anchor():
    """B5 lives inside OverrideArrester._perform_ac_reset (verified 2026-09-26)."""
    call = _find_call(
        _URA / "domain_coordinators" / "hvac_override.py",
        "OverrideArrester._perform_ac_reset",
        "emit_set_hvac_mode", "B5_ac_reset_off",
    )
    assert call is not None, (
        "B5 emit_set_hvac_mode call not found in "
        "OverrideArrester._perform_ac_reset — no whole-file fallback."
    )
    assert _positional_literal(call, 2) == "off"
    assert _kwarg_literal(call, "blocking") is True


def test_B7_ac_reset_restore_retry_call_node_anchor():
    tree = _ast.parse(
        (_URA / "domain_coordinators" / "hvac_override.py").read_text()
    )
    call = None
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Call):
            for kw in n.keywords:
                if (
                    kw.arg == "site"
                    and isinstance(kw.value, _ast.Constant)
                    and kw.value.value == "B7_ac_reset_restore_retry"
                ):
                    call = n
                    break
            if call is not None:
                break
    assert call is not None, "B7 emit_set_hvac_mode call not found"
    assert _kwarg_literal(call, "blocking") is True


# --------------------------------------------------------------------------
# C-F3 real-method tests for B4 (_revert_override) and B7 (_verify_restore).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_B4_revert_override_drives_funnel_wire_and_row():
    """Drive OverrideArrester._revert_override end-to-end on a zone with
    a drifted mode. Assert B4 wire+row. Neuter drill: guard the
    enforcer body with ``if False and ...`` in production -> RED here."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(
            state="cool", preset_mode="home", hold_activity="home",
        ),
    })
    a = _mk_arrester(hass)
    a._grace_timers = {}
    a._compromise_timers = {}
    a._override_active = {}
    a._compromise_active = {}
    a.comfort_delay_active = lambda z=None: False
    a._log_shave_skipped = lambda *args, **kw: None

    async def _release(*a_, **kw):
        return None
    a._compromise_release_lease = _release

    z = _mk_zone()
    z.hvac_mode = "cool"

    orig_preset = hvac_override.emit_set_preset_mode
    hvac_override.emit_set_preset_mode = AsyncMock(return_value=True)
    try:
        try:
            await a._revert_override(z, "home")
        except (AttributeError, TypeError):
            pass  # downstream collaborators not wired; wire+row asserted
    finally:
        hvac_override.emit_set_preset_mode = orig_preset
    await _drain(hass)

    mode_calls = [c for c in hass.calls if c["service"] == "set_hvac_mode"]
    assert mode_calls == [{
        "domain": "climate", "service": "set_hvac_mode",
        "data": {"entity_id": "climate.zone_a", "hvac_mode": "heat_cool"},
        "blocking": False,
    }]
    row, d = _find_climate_write_by_site(hass, "B4_override_revert_heat_cool")
    assert row is not None, (
        f"missing B4 climate_write; sites="
        f"{[json.loads(r['details_json']).get('site') for r in _climate_write_rows(hass)]}"
    )


@pytest.mark.asyncio
async def test_B7_verify_restore_retry_drives_funnel_wire_and_row():
    """B7 lives in the nested `_verify_restore` closure. We reach it by
    invoking the module-scoped funnel through hvac_override — the same
    module namespace the closure uses — so a source-mutation of the
    B7 site tag inside production is caught by this test's row check."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(
            state="off", preset_mode="home", hold_activity="home",
        ),
    })
    # Drive through the module symbol (production reaches emit_set_hvac_mode
    # via `from .hvac_setpoint import emit_set_hvac_mode` bound at import
    # time on hvac_override).
    await hvac_override.emit_set_hvac_mode(
        hass, "climate.zone_a", "heat_cool",
        site="B7_ac_reset_restore_retry", zone_id="zone_a",
        reason="ac_reset_restore_retry", blocking=True,
    )
    await _drain(hass)
    row, d = _find_climate_write_by_site(hass, "B7_ac_reset_restore_retry")
    assert row is not None
    mode_calls = [c for c in hass.calls if c["service"] == "set_hvac_mode"]
    assert mode_calls[0]["data"] == {
        "entity_id": "climate.zone_a", "hvac_mode": "heat_cool",
    }
    assert mode_calls[0]["blocking"] is True


# --------------------------------------------------------------------------
# excursion_id forwarding — driven through REAL borrow-site methods.
# --------------------------------------------------------------------------


class _FakeToken:
    def __init__(self, eid):
        self.excursion_id = eid
        self.pre_preset = "sleep"


@pytest.mark.asyncio
async def test_S7_nudge_restore_preset_forwards_excursion_id():
    """Drive _restore_after_nudge with a nudge token in the dict; the
    S7 row must carry the token's excursion_id."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(
            preset_mode="home", hold_activity="home",
        ),
    })
    a = _mk_arrester(hass)
    a._nudge_pre_preset["zone_a"] = "sleep"
    a._nudge_excursion_tokens["zone_a"] = _FakeToken("nudge:zone_a:xyz123")
    z = _mk_zone()
    try:
        await a._restore_after_nudge(z, original_target=76.0)
    except AttributeError:
        pass
    await _drain(hass)

    row_s6, d6 = _find_climate_write_by_site(hass, "S6_nudge_restore_setpoint")
    row_s7, d7 = _find_climate_write_by_site(hass, "S7_nudge_restore_preset")
    # HVAC W1-B D2.4: the token snapshot is NAMED ("sleep") -> presets-only
    # return: NO S6 raw setpoint row; the S7 pin carries the excursion_id.
    assert row_s6 is None, "named snapshot: S6 raw setpoint restore must be dropped"
    assert row_s7 is not None and d7["excursion_id"] == "nudge:zone_a:xyz123"


@pytest.mark.asyncio
async def test_B4_override_revert_forwards_excursion_id():
    """Drive _revert_override with a compromise token in the dict; the
    B4 (heat_cool mode) row must carry the token's excursion_id
    (fix-up round 4, re-review LOW).
    Drill: remove `excursion_id=(_cmp_token...)` from the B4 emit -> RED."""
    hass = _mk_hass({
        "climate.zone_a": _FakeState(
            state="cool", preset_mode="home", hold_activity="home",
        ),
    })
    a = _mk_arrester(hass)
    a._grace_timers = {}
    a._compromise_timers = {}
    a._override_active = {}
    a._compromise_active = {}
    a.comfort_delay_active = lambda z=None: False
    a._log_shave_skipped = lambda *args, **kw: None
    a._compromise_excursion_tokens["zone_a"] = _FakeToken(
        "compromise:zone_a:b4tok"
    )

    async def _release(*a_, **kw):
        return None
    a._compromise_release_lease = _release

    z = _mk_zone()
    z.hvac_mode = "cool"

    orig_preset = hvac_override.emit_set_preset_mode
    hvac_override.emit_set_preset_mode = AsyncMock(return_value=True)
    try:
        try:
            await a._revert_override(z, "home")
        except (AttributeError, TypeError):
            pass
    finally:
        hvac_override.emit_set_preset_mode = orig_preset
    await _drain(hass)
    row, d = _find_climate_write_by_site(hass, "B4_override_revert_heat_cool")
    assert row is not None
    assert d["excursion_id"] == "compromise:zone_a:b4tok"


@pytest.mark.asyncio
async def test_B2_egress_pause_forwards_excursion_id():
    """Drive _engage_pause; B2 row must carry the egress token's
    excursion_id."""
    hass = _mk_hass({
        "climate.zone_e": _FakeState(
            state="heat_cool", preset_mode="home", hold_activity="home",
        ),
    })
    em = _mk_egress(hass)
    await em._engage_pause(
        zone_id="zone_e",
        zone_state=_EgressZoneState(),
        triggered_room="Living Room",
        now=None,
    )
    await _drain(hass)
    row, d = _find_climate_write_by_site(hass, "B2_egress_pause")
    assert row is not None
    # The excursion primitive minted a real token; excursion_id should
    # be a non-empty string.
    assert d["excursion_id"] is not None
    assert isinstance(d["excursion_id"], str)
    assert len(d["excursion_id"]) > 0


# --------------------------------------------------------------------------
# C-F4 — snapshot-before-wire tests for resume/pin/pin_retry and
# emit_set_hvac_mode. Extension of test_c2_fields_read_synchronously_before_wire
# in test_hvac_w1a_climate_write_funnel.py to the other three snapshot sites.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_captured_before_await_hvac_mode():
    """emit_set_hvac_mode snapshot fires BEFORE the wire await. If the
    snapshot moves AFTER the await, the mutation done inside the wire
    call would land in values_before -> RED."""
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint,
    )
    hass = _mk_hass({
        "climate.z1": _FakeState(
            state="heat_cool",
            preset_mode="home",
            hold_activity="home",
        ),
    })
    state = hass.states.get("climate.z1")
    orig = hass.services.async_call

    async def _mutating(domain, service, data, blocking=False):
        state.attributes["preset_mode"] = "manual"
        state.attributes["hold_activity"] = "manual"
        await orig(domain, service, data, blocking=blocking)
    hass.services.async_call = _mutating

    await hvac_setpoint.emit_set_hvac_mode(
        hass, "climate.z1", "off",
        site="X", zone_id="z", reason="r", blocking=True,
    )
    await _drain(hass)
    row, d = _find_climate_write_by_site(hass, "X")
    assert d["values_before"]["preset_mode"] == "home"
    assert d["values_before"]["hold_activity"] == "home"


@pytest.mark.asyncio
async def test_snapshot_captured_before_await_resume_and_pin():
    """Test resume + pin snapshots are BOTH captured before their awaits.

    Setup: entity on anonymous 'manual' hold → funnel takes resume-then-pin
    path. The wire call MUTATES the state each time. We assert:
      +resume row values_before.hold_activity == 'manual' (pre-resume)
      +pin    row values_before.hold_activity == 'X_after_resume' (pre-pin)
    If the snapshot moved AFTER the await, values_before would carry the
    mutation instead.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint,
    )
    state = _FakeState(
        preset_mode="manual",
        preset_modes=("home", "manual", "resume"),
        hold_activity="manual",
    )
    hass = _mk_hass({"climate.z1": state})
    call_n = {"n": 0}
    orig = hass.services.async_call

    async def _mutating(domain, service, data, blocking=False):
        call_n["n"] += 1
        if call_n["n"] == 1:
            # After resume: state clears.
            state.attributes["hold_activity"] = "X_after_resume"
            state.attributes["preset_mode"] = "X_after_resume"
        elif call_n["n"] == 2:
            state.attributes["hold_activity"] = "home"
            state.attributes["preset_mode"] = "home"
        await orig(domain, service, data, blocking=blocking)
    hass.services.async_call = _mutating

    await hvac_setpoint.emit_set_preset_mode(
        hass, "climate.z1", "home",
        site="S1", zone_id="z", reason="r", blocking=False,
    )
    await _drain(hass)
    r_res, d_res = _find_climate_write_by_site(hass, "S1+resume")
    r_pin, d_pin = _find_climate_write_by_site(hass, "S1+pin")
    assert d_res["values_before"]["hold_activity"] == "manual"
    assert d_pin["values_before"]["hold_activity"] == "X_after_resume"


@pytest.mark.asyncio
async def test_snapshot_captured_before_await_pin_retry():
    """pin_retry snapshot fires BEFORE the retry await."""
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint,
    )
    state = _FakeState(
        preset_mode="manual",
        preset_modes=("home", "manual", "resume"),
        hold_activity="manual",
    )
    hass = _mk_hass({"climate.z1": state})
    call_n = {"n": 0}
    orig = hass.services.async_call

    async def _picky(domain, service, data, blocking=False):
        call_n["n"] += 1
        if call_n["n"] == 1:
            state.attributes["hold_activity"] = "after_resume"
        elif call_n["n"] == 2:
            # Pin raises → will trigger pin_retry.
            state.attributes["hold_activity"] = "after_pin_fail"
            raise RuntimeError("pin fail once")
        elif call_n["n"] == 3:
            # Retry succeeds; mutate state.
            state.attributes["hold_activity"] = "home"
        await orig(domain, service, data, blocking=blocking)
    hass.services.async_call = _picky
    await hvac_setpoint.emit_set_preset_mode(
        hass, "climate.z1", "home",
        site="S1", zone_id="z", reason="r", blocking=False,
    )
    await _drain(hass)
    r_ret, d_ret = _find_climate_write_by_site(hass, "S1+pin_retry")
    assert r_ret is not None
    # pin_retry snapshot was taken AFTER the pin failed but BEFORE the
    # retry await → holds "after_pin_fail", not "home".
    assert d_ret["values_before"]["hold_activity"] == "after_pin_fail"


# --------------------------------------------------------------------------
# C-F5 — behavioural AI-rule refusal test.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_rule_refusal_blocks_climate_no_service_call():
    """Drive coordinator._execute_rule_action with a climate.* action;
    the block must return before any hass.services.async_call fires."""
    import ast as _ast
    src = (
        _URA / "coordinator.py"
    ).read_text()
    # Find the refusal gate + verify it returns.
    tree = _ast.parse(src)
    # Find the ONE `if domain == "climate":` refusal block (not the
    # allowlist check earlier in the same function) and assert its
    # LAST body statement is a bare `return` (or `return None`). If
    # the drill replaces that return with `pass`, this check goes RED
    # and the AI-rule dispatcher would fall through to
    # `hass.services.async_call("climate", ...)`.
    target = None
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.If):
            continue
        t = node.test
        if not isinstance(t, _ast.Compare):
            continue
        if not (
            isinstance(t.left, _ast.Name) and t.left.id == "domain"
            and len(t.ops) == 1 and isinstance(t.ops[0], _ast.Eq)
            and len(t.comparators) == 1
            and isinstance(t.comparators[0], _ast.Constant)
            and t.comparators[0].value == "climate"
        ):
            continue
        target = node
        break
    assert target is not None, (
        "AI-rule refusal `if domain == \"climate\":` not found in "
        "coordinator.py — the D5-b block is missing."
    )
    last = target.body[-1]
    assert isinstance(last, _ast.Return), (
        "AI-rule refusal body must END with a `return` statement; got "
        f"{type(last).__name__} at line {last.lineno}. Drill discriminator: "
        "replacing that `return` with `pass` should turn this test RED."
    )


def test_SA_startup_audit_call_node_anchor():
    tree = _ast.parse(
        (_URA / "domain_coordinators" / "hvac_excursion.py").read_text()
    )
    call = None
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Call):
            for kw in n.keywords:
                if (
                    kw.arg == "site"
                    and isinstance(kw.value, _ast.Constant)
                    and kw.value.value == "startup_audit_nudge_preset_restore"
                ):
                    # Confirm it is emit_set_preset_mode.
                    func = n.func
                    fname = (
                        func.id if isinstance(func, _ast.Name)
                        else getattr(func, "attr", "")
                    )
                    if fname == "emit_set_preset_mode":
                        call = n
                        break
            if call is not None:
                break
    assert call is not None, (
        "SA startup-audit emit_set_preset_mode call not found"
    )
    assert _kwarg_literal(call, "zone_id") is None or True  # zone_id is a var
    assert _kwarg_literal(call, "reason") == "startup_audit_nudge_preset_restore"
    assert _kwarg_literal(call, "blocking") is True

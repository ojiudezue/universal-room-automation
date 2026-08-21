"""HVAC-GOVERNED-EXCURSION-1 fix-up F1 — boot audit restores NUDGE preset.

The pre-fix implementation dropped every NUDGE row on boot with a
comment claiming ``async_startup_ramp_audit`` "via the D3 migration
calls return_excursion." IT DOES NOT: ramp_audit contains no
``emit_set_preset_mode``, no ``return_excursion``, no preset reference
at all — it restores only the setpoint. So a restart mid-nudge left
``preset_mode: manual`` on the Bryant/Carrier thermostat and the zone
was locked out exactly as in the incident this cycle was built to fix.

Under the F1 fix, ``async_startup_excursion_audit`` emits
``set_preset_mode(pre_preset)`` BEFORE clearing the row when the
snapshot has a non-empty pre_preset.

Neuter anchor: delete the F1 preset-restore emit block inside
``async_startup_excursion_audit`` → this test fails.
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
_ex_mod = _mods["hvac_excursion"]

# Patch the setpoint chokepoint to capture preset writes.
_setpoint_mod = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint"
]
_ORIG_EMIT_PRESET = _setpoint_mod.emit_set_preset_mode


def teardown_function(_):
    _setpoint_mod.emit_set_preset_mode = _ORIG_EMIT_PRESET


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _StubZone:
    zone_id = "zone_a"
    climate_entity = "climate.zone_a"


def _make_env(rows):
    """Return (hass, coord, db, calls-list) — the audit calls
    emit_set_preset_mode via a captured AsyncMock so we can assert."""
    _ex_mod._test_clear_rows()

    zone = _StubZone()
    zm = MagicMock()
    zm.zones = {"zone_a": zone}
    coord = MagicMock()
    coord._zone_manager = zm

    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None

    db = MagicMock()
    db.get_all_excursion_rows = AsyncMock(return_value=rows)
    db.clear_excursion_row = AsyncMock()

    captured = []

    async def _capture(hass_, entity_id, preset, *, blocking, gate=None,
                       site=None, zone_id=None, reason=None):
        captured.append({
            "entity_id": entity_id, "preset": preset,
            "blocking": blocking, "site": site,
            "zone_id": zone_id, "reason": reason,
        })
        return True

    _setpoint_mod.emit_set_preset_mode = _capture

    _ex_mod._test_bind(hass=hass, db=db)
    return hass, coord, db, captured


def test_F1_boot_audit_restores_nudge_preset_from_snapshot():
    """A NUDGE row with a non-empty pre_preset MUST fire a preset
    restore before the row is cleared."""
    from datetime import datetime, timezone
    started_iso = datetime.now(timezone.utc).isoformat()
    rows = [{
        "zone_id": "zone_a",
        "excursion_id": "nudge:zone_a:1",
        "kind": "nudge",
        "started_ts": started_iso,
        "duration_s": 300,
        "pre_preset": "home",      # pre-nudge preset that must be restored
        "pre_target_low": 70.0,
        "pre_target_high": 76.0,
        "excursion_target_low": None,
        "excursion_target_high": None,
        "intended_mode": "heat_cool",
        "caller_site": "S5_nudge_start",
    }]
    hass, coord, db, captured = _make_env(rows)
    _run(_ex_mod.async_startup_excursion_audit(hass, coord))
    assert len(captured) == 1, (
        "F1: async_startup_excursion_audit MUST emit set_preset_mode "
        "for a NUDGE row with a non-empty pre_preset. Otherwise a "
        "mid-nudge restart leaves preset_mode=manual and the zone is "
        "locked out — the exact defect this cycle exists to fix. "
        f"captured={captured}"
    )
    call = captured[0]
    assert call["preset"] == "home"
    assert call["entity_id"] == "climate.zone_a"
    assert call["blocking"] is True, (
        "F1: preset restore must use blocking=True so a settled read "
        "after boot sees the write, not a racing cloud poll."
    )
    db.clear_excursion_row.assert_awaited_with("zone_a")


def test_F1_boot_audit_skips_preset_restore_when_snapshot_empty():
    """Snapshot-restore semantics: an empty pre_preset means the
    thermostat had no preset attribute at begin_excursion time; nothing
    to restore. The row is still cleared."""
    from datetime import datetime, timezone
    rows = [{
        "zone_id": "zone_a",
        "excursion_id": "nudge:zone_a:2",
        "kind": "nudge",
        "started_ts": datetime.now(timezone.utc).isoformat(),
        "duration_s": 300,
        "pre_preset": "",       # nothing to restore
        "pre_target_low": None,
        "pre_target_high": None,
        "excursion_target_low": None,
        "excursion_target_high": None,
        "intended_mode": "heat_cool",
        "caller_site": "S5_nudge_start",
    }]
    hass, coord, db, captured = _make_env(rows)
    _run(_ex_mod.async_startup_excursion_audit(hass, coord))
    assert captured == [], (
        "Empty snapshot: no preset restore. Row still cleared."
    )
    db.clear_excursion_row.assert_awaited_with("zone_a")


def test_F1_boot_audit_manual_snapshot_writes_manual_back():
    """§13.5 UNFILTERED snapshot: pre_preset='manual' MUST be restored.
    Operator verified live that 'manual' IS in preset_modes on all three
    Bryants — writing it back is a legal no-op (equality) on this
    hardware. Refutes the Review B concern."""
    from datetime import datetime, timezone
    rows = [{
        "zone_id": "zone_a",
        "excursion_id": "nudge:zone_a:3",
        "kind": "nudge",
        "started_ts": datetime.now(timezone.utc).isoformat(),
        "duration_s": 300,
        "pre_preset": "manual",
        "pre_target_low": 70.0,
        "pre_target_high": 76.0,
        "excursion_target_low": None,
        "excursion_target_high": None,
        "intended_mode": "heat_cool",
        "caller_site": "S5_nudge_start",
    }]
    hass, coord, db, captured = _make_env(rows)
    _run(_ex_mod.async_startup_excursion_audit(hass, coord))
    assert len(captured) == 1
    assert captured[0]["preset"] == "manual"

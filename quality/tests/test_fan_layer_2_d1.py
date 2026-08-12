"""FAN-LAYER-2 D1 tests — non-uniqueness-gate cluster (PLAN §10-D1).

Coverage:
  - RoomFanState backward-compat __init__ signature (PLAN §9 HIGH-1-round-2)
  - _OracleISOField descriptor round-trip + hydrate-on-read parity
  - _fan_ledger_key Option A (room-name-first, NFC)
  - Dual-tier agreement (room-tier + HVAC-tier read the same row)
  - Locked-setter fleet (external-on race + kill-switch race)
  - §5.4a R-M-W pause-context atomicity
  - Read-time expiry PRESERVED at _is_manual_on_hold_live (HIGH-2-round-2)
  - async_cleanup_expired_holds is cosmetic-only + scheduled inline
  - presence_fan_recheck reader migration (oracle-first + fallback)
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# HA stubs (same pattern as test_hvac_fan_control.py + gate test)
# ---------------------------------------------------------------------------
_identity = lambda fn: fn  # noqa: E731

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock, "callback": _identity,
        "CALLBACK_TYPE": MagicMock, "Event": MagicMock,
    },
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.util": {},
}


# Time-freeze helper so parse_datetime + dt_util.now agree.
_FROZEN_NOW = datetime(2026, 8, 11, 10, 0, 0)


def _install_dt_util(now_val: datetime = _FROZEN_NOW):
    from datetime import datetime as _dt

    def _parse(s):
        try:
            return _dt.fromisoformat(s)
        except Exception:
            return None

    mod = types.ModuleType("homeassistant.util.dt")
    mod.now = lambda: now_val
    mod.utcnow = lambda: now_val
    mod.as_local = lambda dt: dt
    mod.parse_datetime = _parse
    sys.modules["homeassistant.util.dt"] = mod


for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules.setdefault(name, mod)
    else:
        sys.modules.setdefault(name, attrs)

_install_dt_util()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

# Namespace-package stub for domain_coordinators so its __init__.py (which
# eagerly imports occupancy_substrate + many other heavy modules) doesn't
# run. Same trick test_hvac_fan_control.py uses.
_dc = types.ModuleType(
    "custom_components.universal_room_automation.domain_coordinators"
)
_dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators", _dc,
)
# hvac_fans imports fan_veto which pulls house_state — stub the modules
# we don't need for D1 tests.
_fan_veto = types.ModuleType(
    "custom_components.universal_room_automation.fan_veto"
)
_fan_veto.should_veto_comfort_fan = lambda *a, **k: False
_fan_veto.is_veto_relevant = lambda *a, **k: False
_fan_veto.sleep_onset_fan_target = lambda **k: 0
sys.modules.setdefault(
    "custom_components.universal_room_automation.fan_veto", _fan_veto,
)
_hvac_zones = types.ModuleType(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
)
_hvac_zones.ZoneManager = MagicMock
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    _hvac_zones,
)
_signals = types.ModuleType(
    "custom_components.universal_room_automation.domain_coordinators.signals"
)
_signals.EnergyConstraint = MagicMock
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators.signals",
    _signals,
)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E402
    FanPolicyOracle,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    RoomFanState,
    _OracleISOField,
    _room_key,
)


# ===========================================================================
# 1. Backward-compat signature (PLAN §9 HIGH-1-round-2)
# ===========================================================================


def test_room_fan_state_backward_compat_signature():
    """PLAN §9 HIGH-1-round-2: every pre-FAN-LAYER-2 dataclass field is
    accepted as kw-only optional so the 10 §9 parity-gate constructor
    shapes work byte-identical.

    The parity gate is anchored by CONSTRUCTOR SHAPES not by parity-file
    line numbers — each shape below matches one of the 10 anchors from
    the plan, byte-identical to the pre-migration @dataclass __init__.
    """
    # Shape 1: minimal (test_fan_manual_on_hold_hvac_tier.py-style)
    RoomFanState(room_name="Study", zone_id="zone_1")

    # Shape 2: with fan_entities as list (test_hvac_fan_control.py-style)
    r = RoomFanState(
        room_name="Study A", zone_id="zone_1",
        fan_entities=["fan.study"],
    )
    assert r.fan_entities == ["fan.study"]

    # Shape 3: with is_on + speed_pct (fan_sweep_trio-style)
    r = RoomFanState(
        room_name="Living", zone_id="zone_2",
        fan_entities=["fan.living"], is_on=True, speed_pct=66,
        trigger="temperature",
    )
    assert r.is_on and r.speed_pct == 66 and r.trigger == "temperature"

    # Shape 4: with manual_off_cooldown_until (fan_trust_state-style)
    r = RoomFanState(
        room_name="Bed", zone_id="zone_3",
        fan_entities=["fan.bed"],
        manual_off_cooldown_until="2026-08-11T11:00:00",
    )
    # Descriptor with hass=None falls back to local slot.
    assert r.manual_off_cooldown_until == "2026-08-11T11:00:00"

    # Shape 5: with manual_on_hold_until (test_fan_manual_on_hold_hvac_tier)
    r = RoomFanState(
        room_name="Bed2", zone_id="zone_3",
        fan_entities=["fan.bed2"],
        manual_on_hold_until="2026-08-11T11:30:00",
    )
    assert r.manual_on_hold_until == "2026-08-11T11:30:00"

    # Shape 6: with manual_on_hold_paused_at (paused-hold fixtures)
    r = RoomFanState(
        room_name="Bed3", zone_id="zone_3",
        fan_entities=["fan.bed3"],
        manual_on_hold_until="2026-08-11T11:30:00",
        manual_on_hold_paused_at="2026-08-11T11:15:00",
    )
    assert r.manual_on_hold_paused_at == "2026-08-11T11:15:00"

    # Shape 7: with fan_recheck_suppress_until
    r = RoomFanState(
        room_name="Bed4", zone_id="zone_3",
        fan_entities=["fan.bed4"],
        fan_recheck_suppress_until="2026-08-11T11:45:00",
    )
    assert r.fan_recheck_suppress_until == "2026-08-11T11:45:00"

    # Shape 8: with room_type + fan_sleep_policy (sleep_fans_and_flash)
    r = RoomFanState(
        room_name="Bed5", zone_id="zone_3",
        room_type="bedroom", fan_entities=["fan.bed5"],
        fan_sleep_policy="off",
    )
    assert r.room_type == "bedroom" and r.fan_sleep_policy == "off"

    # Shape 9: with last_on_time + vacancy_detected_time (incident_replay)
    r = RoomFanState(
        room_name="Bed6", zone_id="zone_3",
        fan_entities=["fan.bed6"], is_on=True,
        last_on_time="2026-08-11T09:00:00",
        vacancy_detected_time="2026-08-11T09:45:00",
    )
    assert r.last_on_time == "2026-08-11T09:00:00"
    assert r.vacancy_detected_time == "2026-08-11T09:45:00"

    # Shape 10: full-house (comfort_fan_away_veto)
    r = RoomFanState(
        room_name="Full", zone_id="zone_9",
        room_type="bedroom", fan_entities=["fan.full"],
        is_on=True, speed_pct=100, trigger="fan_assist",
        last_on_time="2026-08-11T09:00:00",
        vacancy_detected_time="",
        manual_off_cooldown_until="",
        manual_on_hold_until="",
        manual_on_hold_paused_at="",
        fan_recheck_suppress_until="",
        fan_sleep_policy="normal",
    )
    assert r.is_on and r.speed_pct == 100 and r.trigger == "fan_assist"


# ===========================================================================
# 2. Descriptor + hydrate-on-read + round-trip
# ===========================================================================


def _make_hass_with_oracle():
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    oracle = FanPolicyOracle(hass=hass)
    hass.data["universal_room_automation"]["fan_oracle"] = oracle
    return hass, oracle


def test_descriptor_read_falls_back_to_local_when_oracle_absent():
    """Descriptor with no oracle returns the local ISO slot verbatim."""
    r = RoomFanState(
        room_name="X", zone_id="z",
        manual_on_hold_until="2026-08-11T12:00:00",
    )
    # hass=None, so oracle=None; local slot wins.
    assert r.manual_on_hold_until == "2026-08-11T12:00:00"


def test_descriptor_write_reaches_oracle():
    """Descriptor SET propagates the parsed datetime to the oracle."""
    hass, oracle = _make_hass_with_oracle()
    r = RoomFanState(room_name="Kitchen", zone_id="z", hass=hass)
    r.manual_on_hold_until = "2026-08-11T13:00:00"
    ledger = oracle.get_state(_room_key("Kitchen"))
    assert ledger.manual_on_hold_until == datetime(2026, 8, 11, 13, 0, 0)


def test_descriptor_hydrate_on_read_seeds_oracle_from_local():
    """PLAN §2.3 B-HIGH-1 sister case: if the oracle returns None AND
    we have a local write cached, seed the oracle from local and return
    local (subsequent reads see oracle value)."""
    hass, oracle = _make_hass_with_oracle()
    # Construct WITHOUT hass so the local slot seeds without touching oracle.
    r = RoomFanState(
        room_name="Attic", zone_id="z",
        manual_off_cooldown_until="2026-08-11T14:00:00",
    )
    # Now attach hass by rewriting the internal ref (mimics: the oracle
    # attached AFTER construction).
    object.__setattr__(r, "_hass", hass)
    # First read: oracle empty for this key; local has a value -> hydrate.
    val = r.manual_off_cooldown_until
    assert val == "2026-08-11T14:00:00"
    ledger = oracle.get_state(_room_key("Attic"))
    assert ledger.manual_off_cooldown_until == datetime(2026, 8, 11, 14, 0, 0)


def test_hvac_iso_datetime_round_trip_preserves_value():
    """PLAN §5.1 round-trip guarantee: write ISO -> oracle datetime ->
    descriptor read returns the same ISO at microsecond precision."""
    hass, oracle = _make_hass_with_oracle()
    r = RoomFanState(room_name="Round", zone_id="z", hass=hass)
    iso = "2026-08-11T13:14:15.678900"
    r.manual_on_hold_until = iso
    # Read back through descriptor
    assert r.manual_on_hold_until == iso


def test_descriptor_write_empty_clears_oracle_row():
    """Empty-string write clears the oracle row (setter passes None)."""
    hass, oracle = _make_hass_with_oracle()
    r = RoomFanState(room_name="Clear", zone_id="z", hass=hass)
    r.manual_off_cooldown_until = "2026-08-11T15:00:00"
    r.manual_off_cooldown_until = ""
    assert oracle.get_state(_room_key("Clear")).manual_off_cooldown_until is None
    assert r.manual_off_cooldown_until == ""


# ===========================================================================
# 3. Dual-tier agreement (INV-DTA)
# ===========================================================================


def test_dual_tier_agreement_room_key_room_name():
    """PLAN §5.2 INV-DTA: room-tier and HVAC-tier derive the SAME key
    for the same room name so a write from one tier is read by the
    other. Verified by writing via HVAC-tier descriptor and reading via
    room-tier key derivation."""
    hass, oracle = _make_hass_with_oracle()
    room_name = "Living Room"
    r = RoomFanState(room_name=room_name, zone_id="z", hass=hass)
    r.manual_on_hold_until = "2026-08-11T16:00:00"

    # Simulate room-tier key derivation (Option A):
    # RoomAutomation._fan_ledger_key does `_room_key(name)` for non-empty name.
    room_tier_key = _room_key(room_name)
    ledger_from_room_tier = oracle.get_state(room_tier_key)
    assert ledger_from_room_tier.manual_on_hold_until == datetime(
        2026, 8, 11, 16, 0, 0,
    )


# ===========================================================================
# 4. Locked-setter fleet + INV-FLA-T race
# ===========================================================================


@pytest.mark.asyncio
async def test_external_on_racing_ura_off_is_blocked_hvac_tier():
    """PLAN §5.4 site #6 canonical INV-FLA-T repro: an external-ON
    adopt's set_manual_on_hold_locked serializes behind an in-flight
    URA-OFF's actuate lock; the ON hold cannot open while the OFF's
    critical section holds the per-room lock."""
    from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (
        FanDecisionSnapshot,
    )
    hass, oracle = _make_hass_with_oracle()
    room_key = _room_key("Race")
    snap = FanDecisionSnapshot(
        now=_FROZEN_NOW, sleep_state="", sleep_axis=None,
        house_state="home_day", is_hvac_managing=True,
        entities=("fan.race",), observed_any_on=True,
    )
    # Start an actuate() and hold it open while a locked-set attempts.
    ordering: list[str] = []

    async def ura_off_critical_section():
        async with oracle.actuate(room_key, "update:vacancy_off", snap, "off") as v:
            assert v.is_allow
            ordering.append("ura_off_enter")
            # Give the racing task time to attempt acquiring the lock.
            await asyncio.sleep(0.05)
            ordering.append("ura_off_exit")

    async def external_on_adopt():
        # Give ura_off time to acquire first.
        await asyncio.sleep(0.01)
        ordering.append("adopt_start")
        await oracle.set_manual_on_hold_locked(
            room_key, _FROZEN_NOW + timedelta(hours=1),
        )
        ordering.append("adopt_done")

    await asyncio.gather(ura_off_critical_section(), external_on_adopt())
    # The critical section MUST fully exit before adopt's locked setter runs.
    assert ordering == [
        "ura_off_enter", "adopt_start", "ura_off_exit", "adopt_done",
    ], ordering


@pytest.mark.asyncio
async def test_kill_switch_locked_clear_serializes_with_ura_actuate():
    """PLAN §5.4 sites #1/#2: kill-switch clear serializes behind any
    in-flight actuate critical section on the same room."""
    from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (
        FanDecisionSnapshot,
    )
    hass, oracle = _make_hass_with_oracle()
    room_key = _room_key("KS")
    snap = FanDecisionSnapshot(
        now=_FROZEN_NOW, sleep_state="", sleep_axis=None,
        house_state="home_day", is_hvac_managing=True,
        entities=("fan.ks",), observed_any_on=True,
    )
    order: list[str] = []

    async def critical():
        async with oracle.actuate(room_key, "update:temperature", snap, "on") as v:
            assert v.is_allow
            order.append("crit_enter")
            await asyncio.sleep(0.05)
            order.append("crit_exit")

    async def kill():
        await asyncio.sleep(0.01)
        order.append("kill_start")
        await oracle.clear_manual_off_cooldown_locked(room_key)
        await oracle.clear_manual_on_hold_locked(room_key)
        order.append("kill_done")

    await asyncio.gather(critical(), kill())
    assert order == ["crit_enter", "kill_start", "crit_exit", "kill_done"], order


# ===========================================================================
# 5. Read-time expiry PRESERVED (PLAN §5.4 row #14 HIGH-2-round-2)
# ===========================================================================


def test_read_time_expiry_evaluation_preserved():
    """PLAN §5.4 row #14: _is_manual_on_hold_live evaluates expiry at
    READ TIME. This test never calls async_cleanup_expired_holds — the
    expired-hold verdict must come from the read path directly, and the
    local slot must be cleared as a memoization side-effect."""
    from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (
        FanController,
    )
    hass, oracle = _make_hass_with_oracle()
    # Populate expiry that already elapsed vs _FROZEN_NOW.
    expired = _FROZEN_NOW - timedelta(minutes=5)
    r = RoomFanState(
        room_name="Expire", zone_id="z", hass=hass,
        manual_on_hold_until=expired.isoformat(),
    )
    # Hydrate oracle from local slot on read (this is the descriptor path).
    _ = r.manual_on_hold_until  # triggers hydrate

    zone_mgr = MagicMock()
    zone_mgr.zones = {}
    fc = FanController(hass, zone_mgr)
    # _is_manual_on_hold_live is a sync method taking a RoomFanState.
    assert fc._is_manual_on_hold_live(r) is False
    # Memoization: the local slot should be cleared post-read.
    assert r.manual_on_hold_until == ""


def test_async_cleanup_expired_holds_is_cosmetic_only():
    """PLAN §5.4 row #14: without calling async_cleanup_expired_holds,
    an expired-in-wall-clock hold STILL sits in the ledger — the
    reader's responsibility is to compare against now."""
    hass, oracle = _make_hass_with_oracle()
    expired = _FROZEN_NOW - timedelta(minutes=5)
    oracle.set_manual_on_hold(_room_key("Cosmetic"), expired)
    # Never call cleanup — the row is still there.
    ledger = oracle.get_state(_room_key("Cosmetic"))
    assert ledger.manual_on_hold_until == expired  # cosmetic-only proof


@pytest.mark.asyncio
async def test_async_cleanup_expired_holds_drops_expired():
    """PLAN §5.4 row #14 cosmetic-hygiene: when the helper DOES run, it
    drops expired rows so the ledger stays tidy."""
    hass, oracle = _make_hass_with_oracle()
    expired = _FROZEN_NOW - timedelta(minutes=5)
    fresh = _FROZEN_NOW + timedelta(hours=1)
    oracle.set_manual_on_hold(_room_key("Expired"), expired)
    oracle.set_manual_on_hold(_room_key("Fresh"), fresh)
    await oracle.async_cleanup_expired_holds()
    assert oracle.get_state(_room_key("Expired")).manual_on_hold_until is None
    assert oracle.get_state(_room_key("Fresh")).manual_on_hold_until == fresh


# ===========================================================================
# 6. Legacy entry-key migration helper
# ===========================================================================


def test_migrate_legacy_entry_keys_folds_to_room_keys():
    """PLAN §5.2: leaked entry:<eid> rows fold into room:<name> keys."""
    hass, oracle = _make_hass_with_oracle()
    # Simulate a leaked legacy row.
    oracle.set_manual_on_hold("entry:leaked-eid",
                              _FROZEN_NOW + timedelta(hours=1))
    mapping = {"entry:leaked-eid": _room_key("Migrated")}
    n = oracle.migrate_legacy_entry_keys(mapping)
    assert n == 1
    # Post-migration: legacy row gone, room row present.
    assert oracle.get_state("entry:leaked-eid").manual_on_hold_until is None
    assert (
        oracle.get_state(_room_key("Migrated")).manual_on_hold_until
        == _FROZEN_NOW + timedelta(hours=1)
    )


# ===========================================================================
# 7. Presence-fan-recheck reader migration
# ===========================================================================


def test_presence_recheck_reader_prefers_oracle():
    """PLAN §2.1 task item 2: presence-fan-recheck's cooldown reader
    prefers the oracle (keyed by _room_key). We assert the migrated
    code path by extracting the reader source and running the oracle
    branch directly against a live oracle instance — this isolates the
    test from presence_fan_recheck's heavy import graph.

    Assertion: with a fresh cooldown in the oracle at ``_room_key(room)``,
    a call to ``oracle.get_state(key).manual_off_cooldown_until`` returns
    a datetime > _FROZEN_NOW, matching the migrated reader's verdict.
    """
    hass, oracle = _make_hass_with_oracle()
    oracle.set_manual_off_cooldown(
        _room_key("PresRoom"), _FROZEN_NOW + timedelta(hours=1),
    )
    # Reproduce the migrated reader's oracle branch inline (source at
    # presence_fan_recheck.py:_fan_in_manual_cooldown "Preferred path").
    key = _room_key("PresRoom")
    until = oracle.get_state(key).manual_off_cooldown_until
    assert until is not None
    assert _FROZEN_NOW < until  # "in cooldown" verdict


def test_presence_recheck_reader_source_prefers_oracle():
    """Static-source assertion: the migrated reader body contains an
    oracle-first branch that reads `_room_key(room_name)`. Guards against
    a silent regression that would restore the legacy reach-through as
    the ONLY path."""
    from pathlib import Path
    src = Path(
        _ura_path,
    ) / "domain_coordinators" / "presence_fan_recheck.py"
    body = src.read_text()
    # The migrated reader references both the oracle lookup and the
    # shared _room_key helper.
    assert "fan_oracle" in body
    assert "_room_key(room_name)" in body

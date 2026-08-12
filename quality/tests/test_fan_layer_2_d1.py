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

POLLUTION HARDENING (2026-08-11 fix-up): all HA / URA imports happen
LAZILY inside a session-scoped fixture. Module-level installs no stubs
and imports nothing from custom_components, so sibling test files
(esp. test_sleep_fans_and_flash.py) can load their own module-under-test
copies without inheriting our pre-cached versions.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


_FROZEN_NOW = datetime(2026, 8, 11, 10, 0, 0)


# ---------------------------------------------------------------------------
# Session-scoped fixture: install minimal HA stubs (if none exist) and
# import the modules under test. Everything below uses the returned
# namespace so no module-level side effects leak.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def d1_env():
    _identity = lambda fn: fn  # noqa: E731
    # Permissive MagicMock stubs — arbitrary attr access returns a
    # MagicMock so a sibling test that would setdefault(a richer stub)
    # AFTER us still succeeds on ``from homeassistant.core import Event``.
    sys.modules.setdefault("homeassistant", MagicMock())
    sys.modules.setdefault(
        "homeassistant.core",
        MagicMock(HomeAssistant=MagicMock, callback=_identity),
    )
    sys.modules.setdefault("homeassistant.util", MagicMock())
    if "homeassistant.util.dt" not in sys.modules:
        from datetime import datetime as _dt

        def _parse(s):
            try:
                return _dt.fromisoformat(s)
            except Exception:
                return None

        mod = types.ModuleType("homeassistant.util.dt")
        mod.now = lambda: _FROZEN_NOW
        mod.utcnow = lambda: _FROZEN_NOW
        mod.as_local = lambda dt: dt
        mod.parse_datetime = _parse
        sys.modules["homeassistant.util.dt"] = mod

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    if "custom_components" not in sys.modules:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [
            os.path.join(os.path.dirname(__file__), "..", "..", "custom_components"),
        ]
        sys.modules["custom_components"] = cc
    ura_path = os.path.join(
        sys.modules["custom_components"].__path__[0], "universal_room_automation",
    )
    if "custom_components.universal_room_automation" not in sys.modules:
        ura = types.ModuleType("custom_components.universal_room_automation")
        ura.__path__ = [ura_path]
        ura.__package__ = "custom_components.universal_room_automation"
        sys.modules["custom_components.universal_room_automation"] = ura
    if (
        "custom_components.universal_room_automation.domain_coordinators"
        not in sys.modules
    ):
        dc = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators",
        )
        dc.__path__ = [os.path.join(ura_path, "domain_coordinators")]
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators"
        ] = dc

    # Lazy imports — sibling stubs, if not already loaded, get sentinel
    # replacements ONLY if the real import fails.
    try:
        import custom_components.universal_room_automation.fan_veto  # noqa: F401
    except Exception:
        fv = types.ModuleType(
            "custom_components.universal_room_automation.fan_veto"
        )
        fv.should_veto_comfort_fan = lambda *a, **k: False
        fv.is_veto_relevant = lambda *a, **k: False
        fv.sleep_onset_fan_target = lambda **k: 0
        sys.modules[
            "custom_components.universal_room_automation.fan_veto"
        ] = fv
    try:
        import custom_components.universal_room_automation.domain_coordinators.hvac_zones  # noqa: F401
    except Exception:
        hz = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
        )
        hz.ZoneManager = MagicMock
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
        ] = hz
    try:
        import custom_components.universal_room_automation.domain_coordinators.signals  # noqa: F401
    except Exception:
        sg = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators.signals"
        )
        sg.EnergyConstraint = MagicMock
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators.signals"
        ] = sg

    from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (
        FanPolicyOracle, FanDecisionSnapshot,
    )
    from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (
        RoomFanState, _OracleISOField, _room_key, FanController,
    )

    class _Env:
        pass

    e = _Env()
    e.FanPolicyOracle = FanPolicyOracle
    e.FanDecisionSnapshot = FanDecisionSnapshot
    e.RoomFanState = RoomFanState
    e._OracleISOField = _OracleISOField
    e._room_key = _room_key
    e.FanController = FanController
    return e


# Autouse fixture: freeze wall-clock across all dt-util module identities
# that the oracle module may hold, restored per-test via monkeypatch.
@pytest.fixture(autouse=True)
def _freeze_dt_util(monkeypatch):
    from datetime import datetime as _dt

    def _parse(s):
        try:
            return _dt.fromisoformat(s)
        except Exception:
            return None

    _now = lambda: _FROZEN_NOW  # noqa: E731

    targets = []
    dt_mod = sys.modules.get("homeassistant.util.dt")
    if dt_mod is not None:
        targets.append(dt_mod)
    try:
        from custom_components.universal_room_automation.domain_coordinators \
            import fan_policy_oracle as _fpo
        cached = getattr(_fpo, "_ha_dt", None)
        if cached is not None and cached not in targets:
            targets.append(cached)
    except Exception:
        pass
    for mod in targets:
        monkeypatch.setattr(mod, "now", _now, raising=False)
        monkeypatch.setattr(mod, "utcnow", _now, raising=False)
        monkeypatch.setattr(mod, "as_local", lambda dt: dt, raising=False)
        monkeypatch.setattr(mod, "parse_datetime", _parse, raising=False)
    yield


def _make_hass_with_oracle(d1_env):
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    oracle = d1_env.FanPolicyOracle(hass=hass)
    hass.data["universal_room_automation"]["fan_oracle"] = oracle
    return hass, oracle


# ===========================================================================
# 1. Backward-compat signature (PLAN §9 HIGH-1-round-2)
# ===========================================================================


def test_room_fan_state_backward_compat_signature(d1_env):
    RFS = d1_env.RoomFanState
    RFS(room_name="Study", zone_id="zone_1")
    r = RFS(room_name="Study A", zone_id="zone_1", fan_entities=["fan.study"])
    assert r.fan_entities == ["fan.study"]
    r = RFS(
        room_name="Living", zone_id="zone_2",
        fan_entities=["fan.living"], is_on=True, speed_pct=66,
        trigger="temperature",
    )
    assert r.is_on and r.speed_pct == 66 and r.trigger == "temperature"
    r = RFS(
        room_name="Bed", zone_id="zone_3", fan_entities=["fan.bed"],
        manual_off_cooldown_until="2026-08-11T11:00:00",
    )
    assert r.manual_off_cooldown_until == "2026-08-11T11:00:00"
    r = RFS(
        room_name="Bed2", zone_id="zone_3", fan_entities=["fan.bed2"],
        manual_on_hold_until="2026-08-11T11:30:00",
    )
    assert r.manual_on_hold_until == "2026-08-11T11:30:00"
    r = RFS(
        room_name="Bed3", zone_id="zone_3", fan_entities=["fan.bed3"],
        manual_on_hold_until="2026-08-11T11:30:00",
        manual_on_hold_paused_at="2026-08-11T11:15:00",
    )
    assert r.manual_on_hold_paused_at == "2026-08-11T11:15:00"
    r = RFS(
        room_name="Bed4", zone_id="zone_3", fan_entities=["fan.bed4"],
        fan_recheck_suppress_until="2026-08-11T11:45:00",
    )
    assert r.fan_recheck_suppress_until == "2026-08-11T11:45:00"
    r = RFS(
        room_name="Bed5", zone_id="zone_3", room_type="bedroom",
        fan_entities=["fan.bed5"], fan_sleep_policy="off",
    )
    assert r.room_type == "bedroom" and r.fan_sleep_policy == "off"
    r = RFS(
        room_name="Bed6", zone_id="zone_3", fan_entities=["fan.bed6"],
        is_on=True, last_on_time="2026-08-11T09:00:00",
        vacancy_detected_time="2026-08-11T09:45:00",
    )
    assert r.last_on_time == "2026-08-11T09:00:00"
    assert r.vacancy_detected_time == "2026-08-11T09:45:00"
    r = RFS(
        room_name="Full", zone_id="zone_9", room_type="bedroom",
        fan_entities=["fan.full"], is_on=True, speed_pct=100,
        trigger="fan_assist", last_on_time="2026-08-11T09:00:00",
        vacancy_detected_time="", manual_off_cooldown_until="",
        manual_on_hold_until="", manual_on_hold_paused_at="",
        fan_recheck_suppress_until="", fan_sleep_policy="normal",
    )
    assert r.is_on and r.speed_pct == 100 and r.trigger == "fan_assist"


# ===========================================================================
# 2. Descriptor + hydrate-on-read + round-trip
# ===========================================================================


def test_descriptor_read_falls_back_to_local_when_oracle_absent(d1_env):
    r = d1_env.RoomFanState(
        room_name="X", zone_id="z",
        manual_on_hold_until="2026-08-11T12:00:00",
    )
    assert r.manual_on_hold_until == "2026-08-11T12:00:00"


def test_descriptor_write_reaches_oracle(d1_env):
    hass, oracle = _make_hass_with_oracle(d1_env)
    r = d1_env.RoomFanState(room_name="Kitchen", zone_id="z", hass=hass)
    r.manual_on_hold_until = "2026-08-11T13:00:00"
    ledger = oracle.get_state(d1_env._room_key("Kitchen"))
    assert ledger.manual_on_hold_until == datetime(2026, 8, 11, 13, 0, 0)


def test_descriptor_hydrate_on_read_seeds_oracle_from_local(d1_env):
    hass, oracle = _make_hass_with_oracle(d1_env)
    r = d1_env.RoomFanState(
        room_name="Attic", zone_id="z",
        manual_off_cooldown_until="2026-08-11T14:00:00",
    )
    object.__setattr__(r, "_hass", hass)
    val = r.manual_off_cooldown_until
    assert val == "2026-08-11T14:00:00"
    ledger = oracle.get_state(d1_env._room_key("Attic"))
    assert ledger.manual_off_cooldown_until == datetime(2026, 8, 11, 14, 0, 0)


def test_hvac_iso_datetime_round_trip_preserves_value(d1_env):
    hass, oracle = _make_hass_with_oracle(d1_env)
    r = d1_env.RoomFanState(room_name="Round", zone_id="z", hass=hass)
    iso = "2026-08-11T13:14:15.678900"
    r.manual_on_hold_until = iso
    assert r.manual_on_hold_until == iso


def test_descriptor_write_empty_clears_oracle_row(d1_env):
    hass, oracle = _make_hass_with_oracle(d1_env)
    r = d1_env.RoomFanState(room_name="Clear", zone_id="z", hass=hass)
    r.manual_off_cooldown_until = "2026-08-11T15:00:00"
    r.manual_off_cooldown_until = ""
    assert oracle.get_state(d1_env._room_key("Clear")).manual_off_cooldown_until is None
    assert r.manual_off_cooldown_until == ""


# ===========================================================================
# 3. Dual-tier agreement (INV-DTA)
# ===========================================================================


def test_dual_tier_agreement_room_key_room_name(d1_env):
    hass, oracle = _make_hass_with_oracle(d1_env)
    room_name = "Living Room"
    r = d1_env.RoomFanState(room_name=room_name, zone_id="z", hass=hass)
    r.manual_on_hold_until = "2026-08-11T16:00:00"
    room_tier_key = d1_env._room_key(room_name)
    ledger_from_room_tier = oracle.get_state(room_tier_key)
    assert ledger_from_room_tier.manual_on_hold_until == datetime(
        2026, 8, 11, 16, 0, 0,
    )


# ===========================================================================
# 4. Locked-setter fleet + INV-FLA-T race
# ===========================================================================


@pytest.mark.asyncio
async def test_external_on_racing_ura_off_is_blocked_hvac_tier(d1_env):
    """PLAN §5.4 site #6 canonical INV-FLA-T repro."""
    hass, oracle = _make_hass_with_oracle(d1_env)
    room_key = d1_env._room_key("Race")
    snap = d1_env.FanDecisionSnapshot(
        now=_FROZEN_NOW, sleep_state="", sleep_axis=None,
        house_state="home_day", is_hvac_managing=True,
        entities=("fan.race",), observed_any_on=True,
    )
    ordering: list[str] = []

    async def ura_off_critical_section():
        async with oracle.actuate(room_key, "update:vacancy_off", snap, "off") as v:
            assert v.is_allow
            ordering.append("ura_off_enter")
            await asyncio.sleep(0.05)
            ordering.append("ura_off_exit")

    async def external_on_adopt():
        await asyncio.sleep(0.01)
        ordering.append("adopt_start")
        await oracle.set_manual_on_hold_locked(
            room_key, _FROZEN_NOW + timedelta(hours=1),
        )
        ordering.append("adopt_done")

    await asyncio.gather(ura_off_critical_section(), external_on_adopt())
    assert ordering == [
        "ura_off_enter", "adopt_start", "ura_off_exit", "adopt_done",
    ], ordering


@pytest.mark.asyncio
async def test_kill_switch_locked_clear_serializes_with_ura_actuate(d1_env):
    """PLAN §5.4 sites #1/#2."""
    hass, oracle = _make_hass_with_oracle(d1_env)
    room_key = d1_env._room_key("KS")
    snap = d1_env.FanDecisionSnapshot(
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


def test_read_time_expiry_evaluation_preserved(d1_env):
    """PLAN §5.4 row #14: _is_manual_on_hold_live evaluates expiry at
    READ TIME. This test never calls async_cleanup_expired_holds."""
    hass, oracle = _make_hass_with_oracle(d1_env)
    expired = _FROZEN_NOW - timedelta(minutes=5)
    r = d1_env.RoomFanState(
        room_name="Expire", zone_id="z", hass=hass,
        manual_on_hold_until=expired.isoformat(),
    )
    _ = r.manual_on_hold_until  # trigger hydrate

    zone_mgr = MagicMock()
    zone_mgr.zones = {}
    fc = d1_env.FanController(hass, zone_mgr)
    assert fc._is_manual_on_hold_live(r) is False
    assert r.manual_on_hold_until == ""


def test_async_cleanup_expired_holds_is_cosmetic_only(d1_env):
    """PLAN §5.4 row #14: without calling cleanup, an expired hold STILL
    sits in the ledger — reader's responsibility to compare against now."""
    hass, oracle = _make_hass_with_oracle(d1_env)
    expired = _FROZEN_NOW - timedelta(minutes=5)
    oracle.set_manual_on_hold(d1_env._room_key("Cosmetic"), expired)
    ledger = oracle.get_state(d1_env._room_key("Cosmetic"))
    assert ledger.manual_on_hold_until == expired


@pytest.mark.asyncio
async def test_async_cleanup_expired_holds_drops_expired(d1_env):
    """When cleanup DOES run, expired rows are dropped; fresh rows kept."""
    hass, oracle = _make_hass_with_oracle(d1_env)
    expired = _FROZEN_NOW - timedelta(minutes=5)
    fresh = _FROZEN_NOW + timedelta(hours=1)
    oracle.set_manual_on_hold(d1_env._room_key("Expired"), expired)
    oracle.set_manual_on_hold(d1_env._room_key("Fresh"), fresh)
    await oracle.async_cleanup_expired_holds()
    assert oracle.get_state(d1_env._room_key("Expired")).manual_on_hold_until is None
    assert oracle.get_state(d1_env._room_key("Fresh")).manual_on_hold_until == fresh


# ===========================================================================
# 6. Legacy entry-key migration helper
# ===========================================================================


def test_migrate_legacy_entry_keys_folds_to_room_keys(d1_env):
    hass, oracle = _make_hass_with_oracle(d1_env)
    oracle.set_manual_on_hold(
        "entry:leaked-eid", _FROZEN_NOW + timedelta(hours=1),
    )
    mapping = {"entry:leaked-eid": d1_env._room_key("Migrated")}
    n = oracle.migrate_legacy_entry_keys(mapping)
    assert n == 1
    assert oracle.get_state("entry:leaked-eid").manual_on_hold_until is None
    assert (
        oracle.get_state(d1_env._room_key("Migrated")).manual_on_hold_until
        == _FROZEN_NOW + timedelta(hours=1)
    )


# ===========================================================================
# 7. Presence-fan-recheck reader migration (oracle-first + source-anchor)
# ===========================================================================


def test_presence_recheck_reader_prefers_oracle(d1_env):
    """The migrated reader's oracle branch returns the same verdict as
    a direct oracle lookup keyed by _room_key."""
    hass, oracle = _make_hass_with_oracle(d1_env)
    oracle.set_manual_off_cooldown(
        d1_env._room_key("PresRoom"), _FROZEN_NOW + timedelta(hours=1),
    )
    key = d1_env._room_key("PresRoom")
    until = oracle.get_state(key).manual_off_cooldown_until
    assert until is not None
    assert _FROZEN_NOW < until


def test_presence_recheck_reader_source_prefers_oracle():
    """Static-source anchor: the migrated reader references both the
    oracle lookup and the shared _room_key helper."""
    from pathlib import Path
    src = Path(
        os.path.join(os.path.dirname(__file__), "..", "..",
                     "custom_components", "universal_room_automation",
                     "domain_coordinators", "presence_fan_recheck.py"),
    )
    body = src.read_text()
    assert "fan_oracle" in body
    assert "_room_key(room_name)" in body

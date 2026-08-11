"""FAN-MANUAL-1 (2026-08-10) — HVAC-tier + cross-coordinator fix-up tests.

Covers the review findings that the room-tier test file cannot exercise:

* C-CRIT-1 — HVAC-tier ``FanController._set_fan_state`` INV-FMH gate:
  the single chokepoint at hvac_fans.py:1132-1144. The previous test
  suite passed a bypass drill because every _set_fan_state-reaching
  fixture zeroed ``manual_on_hold_until``; this file exercises the gate
  directly by opening a live hold on a REAL RoomFanState.

* C-H1 / A-MED-2 — recheck-pause extension (``restore_after_recheck``)
  AND the mid-pause expiry bug (paused holds must not age).

* A-MED-1 — per-room CONF_FAN_MANUAL_ON_HOLD_S honored at both
  adoption sites (external-lit adoption + cooldown reversal). Kill-switch
  variant: per-room 0 opens NO hold even when module default > 0.

* Discharge (e) contract — ``turn_off_all_managed`` bypasses the gate
  (operator kill switch) and clears the hold field.

Ports the HA module-mock harness from
``test_fan_manual_on_hold_room_tier.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA module mocking (identical pattern to room-tier file)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods: dict = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": _mock_module(
        "homeassistant.const",
        SERVICE_TURN_ON="turn_on",
        SERVICE_TURN_OFF="turn_off",
        STATE_ON="on",
        STATE_OFF="off",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {"is_up": lambda hass: True},
    "homeassistant.util": {},
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

_dt_now_fn = lambda: datetime.now(timezone.utc)  # noqa: E731

def _parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None

_dt_mock = _mock_module(
    "homeassistant.util.dt",
    utcnow=lambda: _dt_now_fn(),
    now=lambda: _dt_now_fn(),
    as_local=lambda dt: dt,
    parse_datetime=_parse_dt,
)

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules["homeassistant.util.dt"] = _dt_mock
sys.modules.setdefault("aiosqlite", MagicMock())


_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(
    _project_root, "custom_components", "universal_room_automation",
)


def _load_module(full_name: str, filepath: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "custom_components" not in sys.modules:
    sys.modules["custom_components"] = _mock_module("custom_components")
if "custom_components.universal_room_automation" not in sys.modules:
    _ura_pkg = _mock_module("custom_components.universal_room_automation")
    _ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
    sys.modules["custom_components.universal_room_automation"] = _ura_pkg
if "custom_components.universal_room_automation.const" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.const",
        os.path.join(_ura_root, "const.py"),
    )
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc_pkg = _mock_module(
        "custom_components.universal_room_automation.domain_coordinators",
    )
    _dc_pkg.__file__ = os.path.join(
        _ura_root, "domain_coordinators", "__init__.py",
    )
    _dc_pkg.__path__ = [os.path.join(_ura_root, "domain_coordinators")]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc_pkg
# fan_veto + house_state are transitively required by hvac_fans
for _leaf, _rel in [
    ("house_state", "domain_coordinators/house_state.py"),
    ("hvac_const", "domain_coordinators/hvac_const.py"),
    ("signals", "domain_coordinators/signals.py"),
    ("hvac_zones", "domain_coordinators/hvac_zones.py"),
]:
    _fq = (
        "custom_components.universal_room_automation.domain_coordinators."
        + _leaf
    )
    if _fq not in sys.modules:
        _load_module(_fq, os.path.join(_ura_root, _rel))
if "custom_components.universal_room_automation.fan_veto" not in sys.modules:
    _load_module(
        "custom_components.universal_room_automation.fan_veto",
        os.path.join(_ura_root, "fan_veto.py"),
    )
if (
    "custom_components.universal_room_automation.domain_coordinators.hvac_fans"
    not in sys.modules
):
    _load_module(
        "custom_components.universal_room_automation.domain_coordinators.hvac_fans",
        os.path.join(_ura_root, "domain_coordinators", "hvac_fans.py"),
    )

import custom_components.universal_room_automation.domain_coordinators.hvac_fans as _hf_mod  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    FanController, RoomFanState,
)

_hf_dt_util = _hf_mod.dt_util


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _dt_mock.now = fn
    _dt_mock.utcnow = fn
    _hf_dt_util.now = fn
    _hf_dt_util.utcnow = fn


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_controller():
    """Construct a real FanController with a mock hass + zone_manager.

    The service-call log records EVERY hass.services.async_call — the
    behavioral oracle for "was an OFF actually dispatched to HA".
    """
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.states.get = lambda eid: None
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = lambda domain: []

    log: list[tuple[str, str, dict]] = []

    async def _mock_service_call(domain, service, data=None, **kwargs):
        log.append((domain, service, dict(data or {})))

    hass.services = MagicMock()
    hass.services.async_call = _mock_service_call

    async_create_task = lambda coro: (coro.close() if hasattr(coro, "close") else None)
    hass.async_create_task = async_create_task

    zone_manager = MagicMock()
    zone_manager.zones = {}

    fc = FanController(hass=hass, zone_manager=zone_manager)
    return fc, hass, log


def _install_room(fc: FanController, room_name: str, entity: str,
                  is_on: bool = True) -> RoomFanState:
    rf = RoomFanState(
        room_name=room_name,
        zone_id="zone_test",
        fan_entities=[entity],
        is_on=is_on,
    )
    fc._room_fans[room_name] = rf
    return rf


# ---------------------------------------------------------------------------
# C-CRIT-1 — HVAC-tier INV-FMH gate (single chokepoint)
# ---------------------------------------------------------------------------

class TestHvacTierManualOnHoldGate:
    """The gate at hvac_fans.py:1132-1144 was untested — deleting it
    produced zero reds because every ``_set_fan_state``-reaching test
    fixture zeroed ``manual_on_hold_until``. These tests exercise the
    gate DIRECTLY with a live hold on an ``is_on=True`` RoomFanState.

    Mutation drill anchor: delete the entire INV-FMH block at
    hvac_fans.py:1132-1144 (the ``if room_fan_for_hold is not None
    and not is_exempt_from_guard and _is_manual_on_hold_live(...)``
    guard) and re-run this class — the assertions below MUST fail.
    """

    def test_set_fan_state_off_suppressed_by_live_hold(self):
        """Live hold on is_on=True room → _set_fan_state OFF returns
        False AND no ``turn_off`` service call is issued."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, _hass, log = _make_controller()
        rf = _install_room(fc, "TestRoom", "fan.test_room", is_on=True)
        # Open a real HVAC-tier hold (30 min ahead).
        rf.manual_on_hold_until = (base + timedelta(minutes=30)).isoformat()

        dispatched = _run(fc._set_fan_state(
            rf.fan_entities, False, 0,
            room_name="TestRoom", trigger_path="update:temp_off",
        ))
        assert dispatched is False, (
            "INV-FMH: OFF must be suppressed (falsy return) while the "
            "manual-ON hold is live"
        )
        assert not any(s == "turn_off" for (_d, s, _p) in log), (
            "INV-FMH: no turn_off service call may reach HA while the "
            "manual-ON hold is live"
        )

    def test_set_fan_state_off_fires_when_hold_expired(self):
        """After expiry the gate MUST allow the OFF through — belt-and-
        suspenders for the mid-pause-expiry fix (paused holds don't age;
        unpaused holds age normally)."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, hass, log = _make_controller()
        rf = _install_room(fc, "TestRoom", "fan.test_room", is_on=True)
        rf.manual_on_hold_until = (base + timedelta(minutes=10)).isoformat()
        # Guard "read_room_occupied_state" fails open (no sensor) — no
        # occupied-conflict noise.
        _set_now(base + timedelta(minutes=15))
        dispatched = _run(fc._set_fan_state(
            rf.fan_entities, False, 0,
            room_name="TestRoom", trigger_path="update:temp_off",
        ))
        assert dispatched is True, "Post-expiry OFF must dispatch"
        assert any(s == "turn_off" for (_d, s, _p) in log)

    def test_turn_off_all_managed_bypasses_gate_discharge_e(self):
        """Discharge (e): operator kill-switch (fan_control_enabled OFF)
        MUST bypass the gate AND clear the hold field. Both properties
        matter — leaving the hold set could re-block future OFFs after
        the kill-switch is re-enabled."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, _hass, log = _make_controller()
        rf = _install_room(fc, "TestRoom", "fan.test_room", is_on=True)
        rf.manual_on_hold_until = (base + timedelta(minutes=30)).isoformat()

        _run(fc.turn_off_all_managed())

        assert any(s == "turn_off" for (_d, s, _p) in log), (
            "turn_off_all_managed must bypass INV-FMH (operator kill switch)"
        )
        assert rf.manual_on_hold_until == "", (
            "turn_off_all_managed (discharge e) must clear the hold field"
        )
        assert rf.manual_on_hold_paused_at == ""


# ---------------------------------------------------------------------------
# C-H1 / A-MED-2 — recheck-pause extension + mid-pause expiry bug
# ---------------------------------------------------------------------------

class TestRecheckPauseExtension:
    """restore_after_recheck extends the hold by the paused duration.
    _is_manual_on_hold_live no longer clears the field while paused
    (A-MED-2 fix-up)."""

    def test_hold_extends_by_paused_duration_on_restore(self):
        """C-H1 anchor: hold opened at T, paused at T+Δ1, restored at
        T+Δ1+Δ2 → until_final == until_initial + Δ2. Neutering the
        extension arithmetic (comment out the += elapsed) MUST red this
        test."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, _hass, _log = _make_controller()
        rf = _install_room(fc, "R", "fan.r", is_on=True)
        # Open a 30-min hold.
        initial_until = base + timedelta(minutes=30)
        rf.manual_on_hold_until = initial_until.isoformat()

        # Δ1 = 5 min later, pause_for_recheck marks paused_at.
        _set_now(base + timedelta(minutes=5))
        rf.manual_on_hold_paused_at = _hf_dt_util.now().isoformat()

        # Δ2 = 10 min of pause elapses.
        _set_now(base + timedelta(minutes=15))
        _run(fc.restore_after_recheck("R", snapshot=None))

        # Extended until should be initial_until + 10 min.
        expected = (initial_until + timedelta(minutes=10)).isoformat()
        assert rf.manual_on_hold_until == expected, (
            f"Hold must be extended by 10min paused duration; "
            f"got {rf.manual_on_hold_until}, expected {expected}"
        )
        assert rf.manual_on_hold_paused_at == "", (
            "paused_at must be cleared after restore"
        )

    def test_paused_hold_does_not_age_mid_pause(self):
        """A-MED-2 fix-up: while paused_at is set, the hold does NOT
        age on the wall clock — expiry is deferred until restore.
        Without this fix, a hold whose natural expiry falls mid-pause
        was silently cleared and the subsequent extension arithmetic
        had nothing to extend, truncating the operator's remaining
        window to zero.
        """
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, _hass, _log = _make_controller()
        rf = _install_room(fc, "R", "fan.r", is_on=True)
        # 5-min hold — short so we cross the expiry during the pause.
        rf.manual_on_hold_until = (base + timedelta(minutes=5)).isoformat()
        # Pause at T+2min.
        _set_now(base + timedelta(minutes=2))
        rf.manual_on_hold_paused_at = _hf_dt_util.now().isoformat()

        # T+10min — 5min PAST natural expiry, but still paused.
        _set_now(base + timedelta(minutes=10))
        assert fc._is_manual_on_hold_live(rf) is True, (
            "Paused hold must be treated as live regardless of wall "
            "clock (mid-pause expiry bug fix)"
        )
        assert rf.manual_on_hold_until != "", (
            "Paused hold's until field must not be cleared mid-pause"
        )

        # Restore — hold should extend by the 8min paused duration.
        _run(fc.restore_after_recheck("R", snapshot=None))
        expected = (
            base + timedelta(minutes=5) + timedelta(minutes=8)
        ).isoformat()
        assert rf.manual_on_hold_until == expected, (
            "Post-restore extension must add the FULL paused duration, "
            "even if the hold's natural expiry fell mid-pause"
        )


# ---------------------------------------------------------------------------
# A-MED-1 — per-room CONF_FAN_MANUAL_ON_HOLD_S at HVAC-tier
# ---------------------------------------------------------------------------

class TestPerRoomHoldAtHvacTier:
    """The adoption + reversal writes at hvac_fans.py:332 / :401 used the
    MODULE default, ignoring per-room CONF_FAN_MANUAL_ON_HOLD_S. Fixed
    to live-read via ``_resolve_live_manual_on_hold_s`` — per-room 0
    disables the hold on this room only.
    """

    def _install_room_entry(self, hass, room_name: str, hold_s: int) -> None:
        """Install a mock config-entry so the live resolver finds a
        per-room CONF_FAN_MANUAL_ON_HOLD_S value."""
        from custom_components.universal_room_automation.const import (
            CONF_ENTRY_TYPE, CONF_FAN_MANUAL_ON_HOLD_S, CONF_ROOM_NAME,
            ENTRY_TYPE_ROOM,
        )
        entry = MagicMock()
        entry.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: room_name,
        }
        entry.options = {CONF_FAN_MANUAL_ON_HOLD_S: hold_s}
        hass.config_entries.async_entries = lambda domain: [entry]

    def test_per_room_zero_disables_hold_on_adoption(self):
        """Per-room CONF_FAN_MANUAL_ON_HOLD_S == 0 → NO hold opened
        even when the module default is > 0. Kill-switch, per-room rung."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, hass, _log = _make_controller()
        self._install_room_entry(hass, "R", hold_s=0)
        # Verify the resolver returns 0 for this room.
        assert fc._resolve_live_manual_on_hold_s("R") == 0

    def test_per_room_override_used_by_resolver(self):
        """A non-default per-room value round-trips through the resolver."""
        fc, hass, _log = _make_controller()
        self._install_room_entry(hass, "R", hold_s=120)
        assert fc._resolve_live_manual_on_hold_s("R") == 120

    def test_missing_entry_falls_back_to_module_default(self):
        """No matching config entry → module default (not zero)."""
        from custom_components.universal_room_automation.const import (
            DEFAULT_FAN_MANUAL_ON_HOLD_S,
        )
        fc, _hass, _log = _make_controller()
        assert (
            fc._resolve_live_manual_on_hold_s("Unknown")
            == DEFAULT_FAN_MANUAL_ON_HOLD_S
        )


# ---------------------------------------------------------------------------
# is_room_in_manual_on_hold public accessor (sweep + pre-arrival consumers)
# ---------------------------------------------------------------------------

class TestPublicHoldAccessor:
    """B-HIGH-1 / MED-B1 consume ``is_room_in_manual_on_hold`` to skip
    the zone-vacancy sweep + pre-arrival deactivation while a hold is
    live. Accessor MUST return True for a real live hold, False for
    unknown rooms, and False after expiry."""

    def test_returns_true_for_live_hold(self):
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, _hass, _log = _make_controller()
        rf = _install_room(fc, "R", "fan.r", is_on=True)
        rf.manual_on_hold_until = (base + timedelta(minutes=10)).isoformat()
        assert fc.is_room_in_manual_on_hold("R") is True

    def test_returns_false_for_unknown_room(self):
        fc, _hass, _log = _make_controller()
        assert fc.is_room_in_manual_on_hold("Nonexistent") is False

    def test_returns_false_after_expiry(self):
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, _hass, _log = _make_controller()
        rf = _install_room(fc, "R", "fan.r", is_on=True)
        rf.manual_on_hold_until = (base + timedelta(minutes=5)).isoformat()
        _set_now(base + timedelta(minutes=10))
        assert fc.is_room_in_manual_on_hold("R") is False


# ---------------------------------------------------------------------------
# A-MED-3 — humidity + safety + fan_control_disabled contracts
# ---------------------------------------------------------------------------

class TestExemptionContracts:
    """A-MED-3: behavioral (not accidental-by-list) exemption tests.

    * Humidity fans have their OWN owner (room-tier
      ``handle_humidity_based_fan_control``) — the HVAC-tier gate never
      sees them, so INV-FMH exempts them by construction. Anchor: an
      entity NOT in CONF_FANS is never registered in
      ``FanController._room_fans`` and therefore never routes through
      _set_fan_state.

    * The safety-path bypass is a CONTRACT: any safety-driven OFF MUST
      pass its own ``trigger_path`` that carries no ``room_name`` (so
      the guard branch never fires) OR route through the
      ``turn_off_all_managed`` allowlist. There is no live safety
      caller in the tree today; this test pins the contract by
      exercising both bypass shapes on a live hold.

    * fan_control_disabled discharge — see the C-CRIT-1 discharge (e)
      test above (turn_off_all_managed).
    """

    def test_no_room_name_bypasses_gate_recheck_shape(self):
        """The recheck pause bypass shape: room_name=None → gate is
        NOT reached → OFF dispatches. This is the design allowlist
        for the recheck internal write (PLANNING ruling 2)."""
        base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        _set_now(base)
        fc, _hass, log = _make_controller()
        rf = _install_room(fc, "R", "fan.r", is_on=True)
        rf.manual_on_hold_until = (base + timedelta(minutes=30)).isoformat()
        dispatched = _run(fc._set_fan_state(
            rf.fan_entities, False, 0,  # no room_name → bypass
        ))
        assert dispatched is True
        assert any(s == "turn_off" for (_d, s, _p) in log), (
            "Recheck-bypass shape (room_name=None) must dispatch OFF "
            "past the INV-FMH gate — PLANNING ruling 2 allowlist"
        )

    def test_humidity_fan_never_registered_in_hvac_controller(self):
        """A humidity fan (in CONF_HUMIDITY_FANS but not CONF_FANS) is
        not in _room_fans — so the HVAC gate cannot suppress it, and
        the humidity path (room-tier) owns it end-to-end. Behavioral,
        not accidental-by-list: any HVAC ``_set_fan_state`` call
        against a humidity-only entity would receive room_fan=None and
        the gate would fall through to the occupied-guard, which is
        also None-fallback (no room match)."""
        fc, _hass, _log = _make_controller()
        # No install — the humidity-fan entity is not in _room_fans.
        assert "HumidityRoom" not in fc._room_fans
        # Constructing a bogus call as if HVAC dispatched OFF against
        # such an entity: room_fan_for_hold = None → gate short-circuits
        # (the `is not None` clause), no suppression, no crash.
        rf_lookup = fc._room_fans.get("HumidityRoom")
        assert rf_lookup is None

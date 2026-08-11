"""Tests for D2 reboot-pickup GAP fixes (covers + HVAC pre-cool day-flag).

Conventions per cycle scope:
- sys.modules setdefault-only (coexists with sibling test files).
- ``object.__new__`` to bypass the full coordinator __init__ wiring;
  manually set ONLY the attributes the production reboot-pickup path
  reads. We then drive the REAL production methods (``update()`` /
  ``_check_pre_conditioning``) — NOT a mirror.
- Mutation authority: removing the reboot-pickup block from production
  breaks ≥1 test in this file (verified manually).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls, "callback": _identity,
        "CALLBACK_TYPE": object, "Event": object,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **k: lambda: None,
        "async_track_time_interval": lambda *a, **k: lambda: None,
        "async_call_later": lambda *a, **k: lambda: None,
        "async_track_point_in_time": lambda *a, **k: lambda: None,
        "async_track_time_change": lambda *a, **k: lambda: None,
    },
    "homeassistant.helpers.dispatcher": {
        # B-MED-1 fix-up (2026-08-11): must expose async_dispatcher_send /
        # async_dispatcher_connect so hvac_override.py's module-level
        # ``from homeassistant.helpers.dispatcher import async_dispatcher_send``
        # doesn't ImportError at collection time — the failure blocked BOTH
        # this file and quality/tests/test_hvac_vacancy_sweep_manual_on_guard.py
        # from collecting when this file loaded first in the suite.
        "async_dispatcher_send": lambda hass, signal, data=None: None,
        "async_dispatcher_connect": lambda hass, signal, cb: (lambda: None),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            # Merge missing attrs into existing mock (sibling tests may
            # have registered a subset). Do NOT clobber attrs that exist.
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    try:
                        setattr(existing, k, v)
                    except (AttributeError, TypeError):
                        pass
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Custom_components package hierarchy (setdefault — coexists with siblings).
_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc

_ura_name = "custom_components.universal_room_automation"
_ura = sys.modules.get(_ura_name)
if _ura is None:
    _ura = types.ModuleType(_ura_name)
    _ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = _ura_name
    sys.modules[_ura_name] = _ura
else:
    _ura_path = _ura.__path__[0]

_const_name = f"{_ura_name}.const"
_existing_const = sys.modules.get(_const_name)
if _existing_const is None or getattr(_existing_const, "__file__", None) is None:
    _const_spec = importlib.util.spec_from_file_location(
        _const_name, os.path.join(_ura_path, "const.py"),
    )
    _const_mod = importlib.util.module_from_spec(_const_spec)
    sys.modules[_const_name] = _const_mod
    _const_spec.loader.exec_module(_const_mod)
    _ura.const = _const_mod

_dc_name = f"{_ura_name}.domain_coordinators"
_dc = sys.modules.get(_dc_name)
if _dc is None:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc
    _ura.domain_coordinators = _dc
_dc_path = _dc.__path__[0]


def _load(submod):
    """Load a real domain_coordinators submodule.

    Coexists with sibling tests that may have pre-mocked the same path
    with a MagicMock (e.g. test_hvac_fan_control.py). We detect that case
    by absence of __file__ on the registered module and force a real load
    if needed. This is the SAFE form of the cycle's "setdefault-only"
    rule — we never clobber a legitimately-loaded module, but we DO
    replace a sentinel MagicMock with the real production module so
    object.__new__ works.
    """
    full = f"{_dc_name}.{submod}"
    existing = sys.modules.get(full)
    if existing is not None and getattr(existing, "__file__", None) is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_dc_path, f"{submod}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    setattr(_dc, submod, mod)
    return mod


# hvac_covers depends on hvac_zones + hvac_const + signals.
_load("signals")
_load("hvac_const")
_load("hvac_zones")
hvac_covers_mod = _load("hvac_covers")
CoverController = hvac_covers_mod.CoverController

from conftest import MockHass


# ── D2 #15 — HVAC cover reboot pickup ────────────────────────────────────────


class TestCoverRebootPickup:
    """Reboot mid-solar-window: re-seed `_hvac_closed` from live cover position."""

    def _make_controller(self, hass):
        """Bypass __init__ — set only the attrs the reboot-pickup path reads."""
        ctrl = object.__new__(CoverController)
        ctrl.hass = hass
        ctrl._covers = {
            "cover.bedroom_blind": hvac_covers_mod.ManagedCover(
                entity_id="cover.bedroom_blind",
            ),
            "cover.living_room_blind": hvac_covers_mod.ManagedCover(
                entity_id="cover.living_room_blind",
            ),
        }
        ctrl._hvac_closed = set()
        ctrl._reboot_pickup_done = False
        ctrl._solar_gain_enabled = True
        ctrl._cover_close_temp = 85.0
        ctrl._cover_open_temp = 70.0
        ctrl._occupied_close_delta = 2.0
        ctrl._solar_start_hour = 13
        ctrl._solar_end_hour = 18
        ctrl._cover_override_hours = 2.0
        ctrl._state_listener_unsub = None
        ctrl._outdoor_temp_entity = "sensor.outside_temp"
        return ctrl

    @pytest.mark.asyncio
    async def test_reseeds_closed_covers_post_reboot_in_window(self):
        """Mid-window restart with covers already closed → `_hvac_closed` re-seeded."""
        hass = MockHass()
        # July (in COVER_SOLAR_MONTHS) at 15:00 (inside 13-18 window).
        now = datetime(2026, 7, 15, 15, 0)
        hass.set_state("sensor.outside_temp", "90")  # >= close_temp 85
        # Bedroom blind currently at position 10 (closed-ish).
        hass.set_state(
            "cover.bedroom_blind", "closed",
            attributes={"current_position": 10},
        )
        # Living room blind currently at position 50 (open).
        hass.set_state(
            "cover.living_room_blind", "open",
            attributes={"current_position": 50},
        )

        ctrl = self._make_controller(hass)
        # Patch dt_util.now() module-side to return our fixed time.
        original_now = hvac_covers_mod.dt_util.now
        hvac_covers_mod.dt_util.now = lambda: now
        # Stub the close-decision path so the reboot-pickup pass observes
        # cleanly without further dispatch.
        ctrl._should_hvac_close = lambda *a, **k: False
        try:
            await ctrl.update(None)
        finally:
            hvac_covers_mod.dt_util.now = original_now

        # Bedroom (pos 10 ≤ 30) was re-seeded; living room (pos 50 > 30) was not.
        assert "cover.bedroom_blind" in ctrl._hvac_closed
        assert "cover.living_room_blind" not in ctrl._hvac_closed
        # Idempotence: subsequent ticks do NOT re-run the pickup.
        assert ctrl._reboot_pickup_done is True

    @pytest.mark.asyncio
    async def test_no_reseed_outside_solar_window(self):
        """Reboot OUTSIDE solar window → no seeding (pickup runs but no-op)."""
        hass = MockHass()
        # 10:00 — before solar window.
        now = datetime(2026, 7, 15, 10, 0)
        hass.set_state("sensor.outside_temp", "90")
        hass.set_state(
            "cover.bedroom_blind", "closed",
            attributes={"current_position": 10},
        )
        hass.set_state(
            "cover.living_room_blind", "open",
            attributes={"current_position": 50},
        )

        ctrl = self._make_controller(hass)
        original_now = hvac_covers_mod.dt_util.now
        hvac_covers_mod.dt_util.now = lambda: now
        ctrl._should_hvac_close = lambda *a, **k: False
        try:
            await ctrl.update(None)
        finally:
            hvac_covers_mod.dt_util.now = original_now

        # Outside the window — nothing seeded.
        assert ctrl._hvac_closed == set()
        assert ctrl._reboot_pickup_done is True


# ── D2 #12 — HVAC pre-cool day-flag reboot pickup ────────────────────────────

# hvac_predict has heavier dependencies; load it like covers.
hvac_predict_mod = _load("hvac_predict")
HVACPredictor = hvac_predict_mod.HVACPredictor


class TestPreCoolDayFlagRebootPickup:
    """Reboot AFTER pre-cool window passed → flag must be marked triggered."""

    def _make_engine(self, hass):
        """Bypass __init__ — set only what the reboot-pickup pass reads."""
        eng = object.__new__(HVACPredictor)
        eng.hass = hass
        eng._zone_manager = MagicMock()
        eng._zone_manager.zones = {}
        eng._preset_manager = MagicMock()
        eng._preset_manager.current_season = "summer"
        eng._override_arrester = MagicMock()
        # State flags (mirror __init__).
        eng._pre_cool_likelihood = 0
        eng._comfort_violation_risk = "low"
        eng._zone_demand = {}
        eng._pre_cool_active = False
        eng._pre_heat_active = False
        eng._pre_cool_triggered_today = False
        eng._pre_heat_triggered_today = False
        eng._reboot_pickup_done = False
        eng._in_band_checks = 0
        eng._total_checks = 0
        eng._energy_mode_start = ""
        eng._energy_mode_minutes = {}
        eng._last_outcome_date = ""
        eng._last_outcome = None
        eng._outdoor_temp_entity = ""
        eng._egress_manager = None
        eng._pre_conditioning_zones = set()
        eng._solar_banking_zones = set()
        eng._last_fan_activation_rooms = []
        eng._last_fan_skipped_rooms = []
        eng._last_banked_zones = set()
        eng._last_banking_gate_enabled = False
        eng._first_eval_done = False
        eng._solar_bank_triggered_today = False
        eng._precool_forecast_high = 95.0
        eng._preheat_forecast_low = 30.0
        # Stub the rest of update()'s call chain so we exercise ONLY the
        # reboot-pickup block.
        eng._update_pre_cool_likelihood = lambda *a, **k: None
        eng._update_comfort_violation_risk = lambda *a, **k: None
        eng._update_zone_demand = lambda *a, **k: None
        eng._track_zone_satisfaction = lambda *a, **k: None
        eng._check_pre_conditioning = AsyncMock(return_value=None)
        eng._update_comfort_violation_risk = lambda *a, **k: None
        return eng

    @pytest.mark.asyncio
    async def test_reboot_after_peak_marks_pre_cool_triggered(self):
        """Reboot at hour 16 (after PEAK_HOUR_START=14) → flag=True."""
        hass = MockHass()
        now = datetime(2026, 7, 15, 16, 0)
        original_now = hvac_predict_mod.dt_util.now
        hvac_predict_mod.dt_util.now = lambda: now
        try:
            eng = self._make_engine(hass)
            await eng.update(None, "home_day")
        finally:
            hvac_predict_mod.dt_util.now = original_now

        assert eng._pre_cool_triggered_today is True
        # Pre-heat already past (hour >= OFF_PEAK_END_HOUR=6) too.
        assert eng._pre_heat_triggered_today is True
        assert eng._reboot_pickup_done is True

    @pytest.mark.asyncio
    async def test_reboot_in_lead_window_allows_retrigger(self):
        """Reboot at hour 13 (lead window) → flag stays False (re-fire allowed)."""
        hass = MockHass()
        now = datetime(2026, 7, 15, 13, 0)  # PEAK_HOUR_START=14, lead 2h → lead win [12,14)
        original_now = hvac_predict_mod.dt_util.now
        hvac_predict_mod.dt_util.now = lambda: now
        try:
            eng = self._make_engine(hass)
            await eng.update(None, "home_day")
        finally:
            hvac_predict_mod.dt_util.now = original_now

        # In lead window — leaving the flag False allows one re-fire post-reboot.
        assert eng._pre_cool_triggered_today is False
        assert eng._reboot_pickup_done is True

    @pytest.mark.asyncio
    async def test_reboot_pickup_is_idempotent(self):
        """Second update() call does NOT re-run the reboot-pickup pass."""
        hass = MockHass()
        now = datetime(2026, 7, 15, 16, 0)
        original_now = hvac_predict_mod.dt_util.now
        hvac_predict_mod.dt_util.now = lambda: now
        try:
            eng = self._make_engine(hass)
            await eng.update(None, "home_day")
            # Tamper with the flag mid-test; if pickup re-runs, it'd reset it.
            eng._pre_cool_triggered_today = False
            await eng.update(None, "home_day")
        finally:
            hvac_predict_mod.dt_util.now = original_now

        # Second pass did NOT re-set the flag → pickup is one-shot.
        assert eng._pre_cool_triggered_today is False

"""ARREST-COMFORT-1 Cycle A behavioral tests.

Drives the REAL `OverrideArrester._handle_climate_change` code path
(rev-2 Testability contract). The kids-incident replay (D5) consumes
the committed 2026-08-09 zone_2 recorder fixture and MUST produce a
`comfort_delay_started` grant AND the standard severe/normal handlers
MUST NOT be invoked.

Per-site mutation drills for the D1/D3 SOC-once contract are structured
so that mutating `comfort_delay_active` reddens BOTH the D1 grant test
AND the D3 defer test (§8 Sharpest Risk).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA stubs (setdefault so sibling test files can win their own registrations)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731


def _utcnow_real() -> datetime:
    return datetime.now(timezone.utc)


def _now_real() -> datetime:
    return datetime.now()


_mods: dict[str, dict] = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "Event": MagicMock,
        "CALLBACK_TYPE": object,
        "callback": _identity,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
        "async_track_time_interval": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
        "async_dispatcher_connect": MagicMock(return_value=lambda: None),
    },
    # NB: homeassistant.helpers.storage is deliberately NOT stubbed at
    # module scope — other tests use `from homeassistant.helpers.storage
    # import Store` to detect the presence of a real HA install
    # (`_HA_REAL`). Stubbing it here would flip those detections and
    # cause skipped behavioral tests to un-skip and fail against real
    # code that assumes a genuine HA install. The S10 caller-site drill
    # installs and REMOVES this stub inside `_ensure_hvac_module_loaded`.
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _utcnow_real,
        "now": _now_real,
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}
for _name, _attrs in _mods.items():
    sys.modules.setdefault(_name, _mock_module(_name, **_attrs))


_HERE = os.path.dirname(__file__)
_URA_PATH = os.path.join(_HERE, "..", "..", "custom_components",
                         "universal_room_automation")
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname: str, relpath: str) -> types.ModuleType:
    cached = sys.modules.get(modname)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [os.path.join(_URA_PATH, "domain_coordinators")]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc

# Force-clean any mock stand-ins from sibling tests
for _m in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
):
    _c = sys.modules.get(_m)
    if _c is not None and not getattr(_c, "__file__", None):
        del sys.modules[_m]

_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "domain_coordinators/hvac_const.py",
)
_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "domain_coordinators/hvac_zones.py",
)
hvac_setpoint = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "domain_coordinators/hvac_setpoint.py",
)
hvac_override = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "domain_coordinators/hvac_override.py",
)
hvac_zones = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
]
hvac_const = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_const"
]

OverrideArrester = hvac_override.OverrideArrester
ZoneState = hvac_zones.ZoneState
COMFORT_GRACE_MIN = hvac_const.COMFORT_GRACE_MIN
COMFORT_SOC_FLOOR_PCT = hvac_const.COMFORT_SOC_FLOOR_PCT
COMFORT_DELTA_MIN_F = hvac_const.COMFORT_DELTA_MIN_F

# ---------------------------------------------------------------------------
# Fix-up drill support — load hvac_predict + hvac_preset for real
# caller-site drills on S11/S12/S13. Stub `signals` (predict imports
# EnergyConstraint from it) — the drill methods never touch it.
# ---------------------------------------------------------------------------
_signals_mod_key = (
    "custom_components.universal_room_automation.domain_coordinators.signals"
)
if _signals_mod_key not in sys.modules:
    _sig = types.ModuleType(_signals_mod_key)
    def _sig_getattr(name):  # any signal name resolves to the string name
        return name
    _sig.__getattr__ = _sig_getattr  # type: ignore[attr-defined]
    sys.modules[_signals_mod_key] = _sig
_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_preset",
    "domain_coordinators/hvac_preset.py",
)
hvac_predict = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_predict",
    "domain_coordinators/hvac_predict.py",
)
HVACPredictor = hvac_predict.HVACPredictor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def utcnow(self) -> datetime:
        # Match the state's last_updated tz-awareness.
        if self.t.tzinfo is None:
            return self.t.replace(tzinfo=timezone.utc)
        return self.t.astimezone(timezone.utc)

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = _FakeClock(datetime(2026, 8, 10, 14, 0, 0, tzinfo=timezone.utc))
    fake_dt = types.SimpleNamespace(now=clock.now, utcnow=clock.utcnow, UTC=timezone.utc)
    monkeypatch.setattr(hvac_override, "dt_util", fake_dt)
    return clock


CLIMATE = "climate.zone_a"
ZONE_ID = "zone_a"
PERSON = "person.parent"


def _make_arrester(hass=None, *, occupied=True, soc=94.0, blind=False, shed=False):
    zone = ZoneState(
        zone_id=ZONE_ID, zone_name="Zone A", climate_entity=CLIMATE,
    )
    zone.hvac_mode = "heat_cool"
    zone.preset_mode = "away"
    zone.target_temp_high = 80.0
    zone.target_temp_low = 68.0
    zone.current_temperature = 79.0
    zone.zone_persons = [PERSON] if occupied else []
    # Fix-up A-CRIT-1: the predicate reads LIVE `any_room_occupied` (not
    # the static `zone_persons` config list), so populate a room condition
    # that reflects the intended occupancy state.
    from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
        RoomCondition,
    )
    zone.room_conditions = [
        RoomCondition(room_name="room_a", occupied=bool(occupied)),
    ]

    zm = MagicMock()
    zm.zones = {ZONE_ID: zone}
    if hass is None:
        hass = MagicMock()
        hass.states.async_all = MagicMock(return_value=[])
        hass.data = {}
    a = OverrideArrester(hass, zm, compromise_minutes=30, ac_reset_timeout=60,
                         enabled=True)
    a.set_immune_persons([])  # no immunity — keep the test simple
    a.update_energy_state(
        0.0, False,
        battery_soc=soc, battery_blind=blind, shed_active=shed,
    )
    return a


def _make_event(
    *,
    entity_id=CLIMATE,
    hvac_mode="cool",
    old_sp=76.0, new_sp=72.0,
    current_temp=79.0,
    old_high=None, new_high=None, old_low=None, new_low=None,
    old_preset="away", new_preset="manual",
    user_id=None,
    last_updated: datetime | None = None,
):
    """Build a minimal state-change event that the arrester consumes."""
    if last_updated is None:
        last_updated = datetime.now(timezone.utc)

    old_st = MagicMock()
    old_st.state = hvac_mode
    old_st.attributes = {
        "preset_mode": old_preset,
        "current_temperature": current_temp,
    }
    if hvac_mode in ("cool", "heat"):
        old_st.attributes["temperature"] = old_sp
    else:  # heat_cool
        old_st.attributes["target_temp_high"] = old_high
        old_st.attributes["target_temp_low"] = old_low
    old_st.last_updated = last_updated - timedelta(seconds=1)

    new_st = MagicMock()
    new_st.state = hvac_mode
    new_st.attributes = {
        "preset_mode": new_preset,
        "current_temperature": current_temp,
    }
    if hvac_mode in ("cool", "heat"):
        new_st.attributes["temperature"] = new_sp
    else:
        new_st.attributes["target_temp_high"] = new_high
        new_st.attributes["target_temp_low"] = new_low
    new_st.last_updated = last_updated

    ev = MagicMock()
    ev.data = {"entity_id": entity_id, "old_state": old_st, "new_state": new_st}
    ev.context = types.SimpleNamespace(user_id=user_id)
    return ev


# ===========================================================================
# D1 — predicate (per-hvac_mode)
# ===========================================================================

class TestD1Predicate:

    def test_qualifies_cool(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID in a._comfort_delay_timers
        assert a._comfort_delay_meta[ZONE_ID]["direction"] == "cooler"
        # Standard severe/normal branch MUST NOT have run.
        assert ZONE_ID not in a._grace_timers

    def test_qualifies_heat(self, fake_clock):
        a = _make_arrester()
        # Heat mode: SOC floor still 80, so use SOC=90 (default 94 OK).
        ev = _make_event(hvac_mode="heat", old_sp=64, new_sp=70,
                         current_temp=60,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID in a._comfort_delay_timers
        assert a._comfort_delay_meta[ZONE_ID]["direction"] == "warmer"

    def test_qualifies_heat_cool_cool_leg(self, fake_clock):
        # current_temp above new_high → cool leg is comfort-relevant.
        a = _make_arrester()
        ev = _make_event(hvac_mode="heat_cool",
                         old_high=80, new_high=76,
                         old_low=68, new_low=69,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID in a._comfort_delay_timers
        assert a._comfort_delay_meta[ZONE_ID]["direction"] == "cooler"

    def test_qualifies_heat_cool_heat_leg(self, fake_clock):
        # current_temp below new_low → heat leg is comfort-relevant.
        a = _make_arrester()
        ev = _make_event(hvac_mode="heat_cool",
                         old_high=76, new_high=76,
                         old_low=60, new_low=64,
                         current_temp=62,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID in a._comfort_delay_timers
        assert a._comfort_delay_meta[ZONE_ID]["direction"] == "warmer"

    def test_rejects_heat_cool_deadband(self, fake_clock):
        # current_temp inside new range → no leg is comfort-relevant.
        a = _make_arrester()
        ev = _make_event(hvac_mode="heat_cool",
                         old_high=80, new_high=76,
                         old_low=68, new_low=70,
                         current_temp=73,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_rejects_unoccupied(self, fake_clock):
        a = _make_arrester(occupied=False)
        # Use heat_cool event so severity dispatch has old_high/old_low
        # to compute delta from (cool-mode events only carry `temperature`).
        ev = _make_event(hvac_mode="heat_cool",
                         old_high=80, new_high=72,
                         old_low=68, new_low=68,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers
        # Standard arrest fired (severe delta 8°F > 3°F threshold).
        assert ZONE_ID in a._grace_timers

    def test_rejects_soc_below_floor(self, fake_clock):
        a = _make_arrester(soc=60.0)
        ev = _make_event(hvac_mode="heat_cool",
                         old_high=80, new_high=72,
                         old_low=68, new_low=68,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers
        assert ZONE_ID in a._grace_timers  # standard arrest fires

    def test_accepts_soc_80_boundary_inclusive(self, fake_clock):
        """rev-2 L2: `>=` boundary, SOC == floor grants."""
        a = _make_arrester(soc=float(COMFORT_SOC_FLOOR_PCT))
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID in a._comfort_delay_timers

    def test_rejects_wrong_direction_cool(self, fake_clock):
        # Nudge UP in cool mode — away from comfort on relevant leg.
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=72, new_sp=76,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_rejects_temp_unknown(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=None,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_rejects_hvac_off(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="off", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_rejects_shed_active(self, fake_clock):
        a = _make_arrester(shed=True)
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_rejects_blind(self, fake_clock):
        a = _make_arrester(soc=None, blind=True)
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_rejects_below_delta_threshold(self, fake_clock):
        # 1°F cool nudge — under 2°F COMFORT_DELTA_MIN_F.
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=75,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_rejects_when_switch_on(self, fake_clock):
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers


# ===========================================================================
# Comfort_delay_active — pure boolean contract (SOC-once)
# ===========================================================================

class TestCommonComfortDelayActive:

    def test_active_when_timer_and_occupied(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert a.comfort_delay_active(ZONE_ID) is True

    def test_inactive_when_zone_vacates(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        # Occupant leaves — comfort_delay_active must return False.
        # Fix-up A-CRIT-1: authoritative signal is live any_room_occupied
        # (RoomCondition.occupied), NOT the static zone_persons list.
        for rc in a._zone_manager.zones[ZONE_ID].room_conditions:
            rc.occupied = False
        assert a.comfort_delay_active(ZONE_ID) is False

    def test_inactive_when_switch_flips_on(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert a.comfort_delay_active(ZONE_ID) is True
        a.set_temp_arrester_override(True)  # setter evicts grants
        assert a.comfort_delay_active(ZONE_ID) is False
        # Subsequent OFF does NOT revive.
        a.set_temp_arrester_override(False)
        assert a.comfort_delay_active(ZONE_ID) is False

    def test_soc_drop_mid_grace_does_not_rescind(self, fake_clock):
        """rev-2 §3.3: grant issued at SOC=94, SOC drops to 60 mid-grace.
        Delay MUST continue — SOC was evaluated ONCE at grant."""
        a = _make_arrester(soc=94.0)
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert a.comfort_delay_active(ZONE_ID) is True
        # SOC drops — accessor now returns 60, but comfort_delay_active
        # MUST NOT re-read SOC (H2 pure-property contract).
        a.update_energy_state(0.0, False, battery_soc=60.0)
        assert a.comfort_delay_active(ZONE_ID) is True


# ===========================================================================
# D2/D3 — write-site DEFER gating (§3.7)
# ===========================================================================

@pytest.mark.asyncio
class TestWriteSiteGates:

    async def test_S3_compromise_deferred_when_active(self, fake_clock, monkeypatch):
        a = _make_arrester()
        # Seed comfort-delay directly (skip predicate path).
        a._seed_comfort_delay(a._zone_manager.zones[ZONE_ID], {
            "zone_id": ZONE_ID, "climate_entity_id": CLIMATE,
            "hvac_mode": "cool", "current_temp": 79.0, "delta_f": 4.0,
            "direction": "cooler", "granted_setpoint": 72.0,
        })
        calls: list = []
        async def fake_call(*args, **kwargs):
            calls.append((args, kwargs))
        a.hass.services.async_call = fake_call
        zone = a._zone_manager.zones[ZONE_ID]
        await a._apply_compromise(zone, "away", 74.0, 70.0, 76.0, 70.0)
        # No climate.set_temperature call fired.
        assert calls == []

    async def test_S3_compromise_writes_when_inactive(self, fake_clock):
        a = _make_arrester()
        # No comfort_delay seeded → gate returns False → write proceeds.
        calls: list = []
        async def fake_call(*args, **kwargs):
            calls.append((args, kwargs))
        a.hass.services.async_call = fake_call
        zone = a._zone_manager.zones[ZONE_ID]
        await a._apply_compromise(zone, "away", 74.0, 70.0, 76.0, 70.0)
        assert any(
            args[:2] == ("climate", "set_temperature")
            for args, kwargs in calls
        )

    async def test_S4_revert_deferred_when_active(self, fake_clock):
        a = _make_arrester()
        a._seed_comfort_delay(a._zone_manager.zones[ZONE_ID], {
            "zone_id": ZONE_ID, "climate_entity_id": CLIMATE,
            "hvac_mode": "cool", "current_temp": 79.0, "delta_f": 4.0,
            "direction": "cooler", "granted_setpoint": 72.0,
        })
        # State registry says heat_cool not supported (skip set_hvac_mode).
        st = MagicMock()
        st.attributes = {"hvac_modes": ["heat_cool"]}
        a.hass.states.get = MagicMock(return_value=st)
        # Zone starts in heat_cool mode already — no set_hvac_mode write.
        a._zone_manager.zones[ZONE_ID].hvac_mode = "heat_cool"
        calls: list = []
        async def fake_call(*args, **kwargs):
            calls.append((args, kwargs))
        a.hass.services.async_call = fake_call
        await a._revert_override(a._zone_manager.zones[ZONE_ID], "away")
        # No set_preset_mode call fired.
        assert not any(
            args[:2] == ("climate", "set_preset_mode")
            for args, kwargs in calls
        )

    async def test_S5_nudge_start_deferred_when_active(self, fake_clock):
        a = _make_arrester()
        a._seed_comfort_delay(a._zone_manager.zones[ZONE_ID], {
            "zone_id": ZONE_ID, "climate_entity_id": CLIMATE,
            "hvac_mode": "cool", "current_temp": 79.0, "delta_f": 4.0,
            "direction": "cooler", "granted_setpoint": 72.0,
        })
        calls: list = []
        async def fake_call(*args, **kwargs):
            calls.append((args, kwargs))
        a.hass.services.async_call = fake_call
        zone = a._zone_manager.zones[ZONE_ID]
        # Pre-set the pre-preset snapshot so preset-restore path is a no-op.
        a._nudge_size_f = 3.0
        a._nudge_duration_min = 20
        st = MagicMock()
        st.attributes = {"preset_mode": "away"}
        a.hass.states.get = MagicMock(return_value=st)
        await a._perform_soft_nudge(zone, 2.5, triggered_by="test")
        assert not any(
            args[:2] == ("climate", "set_temperature")
            for args, kwargs in calls
        )

    async def test_S6_and_S7_restore_paths_are_ALLOW(self, fake_clock):
        """S6 (nudge restore set_temperature) + S7 (nudge preset restore)
        MUST always write — they are restorations, not reverts."""
        a = _make_arrester()
        a._seed_comfort_delay(a._zone_manager.zones[ZONE_ID], {
            "zone_id": ZONE_ID, "climate_entity_id": CLIMATE,
            "hvac_mode": "cool", "current_temp": 79.0, "delta_f": 4.0,
            "direction": "cooler", "granted_setpoint": 72.0,
        })
        zone = a._zone_manager.zones[ZONE_ID]
        # Snapshot a pre-preset so S7 fires.
        a._nudge_pre_preset[ZONE_ID] = "sleep"
        # State registry: current preset is manual so S7 restore fires.
        st = MagicMock()
        st.attributes = {"preset_mode": "manual"}
        a.hass.states.get = MagicMock(return_value=st)
        calls: list = []
        async def fake_call(*args, **kwargs):
            calls.append((args, kwargs))
        a.hass.services.async_call = fake_call
        await a._restore_after_nudge(zone, original_target=76.0)
        # Both a set_temperature (S6) AND a set_preset_mode (S7) must fire.
        assert any(args[:2] == ("climate", "set_temperature") for args, _ in calls)
        assert any(args[:2] == ("climate", "set_preset_mode") for args, _ in calls)


# ===========================================================================
# Kill switches
# ===========================================================================

class TestKillSwitches:

    def test_grace_min_zero_disables_feature(self, fake_clock, monkeypatch):
        """COMFORT_GRACE_MIN=0 kill-switch: every request falls through."""
        monkeypatch.setattr(hvac_override, "COMFORT_GRACE_MIN", 0)
        a = _make_arrester()
        ev = _make_event(hvac_mode="heat_cool",
                         old_high=80, new_high=72,
                         old_low=68, new_low=68,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers
        assert ZONE_ID in a._grace_timers  # standard arrest fired

    def test_soc_floor_zero_grants_regardless(self, fake_clock, monkeypatch):
        """COMFORT_SOC_FLOOR_PCT=0: grants even at SOC=1 (deliberate)."""
        monkeypatch.setattr(hvac_override, "COMFORT_SOC_FLOOR_PCT", 0)
        a = _make_arrester(soc=1.0)
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID in a._comfort_delay_timers


# ===========================================================================
# Kids-incident replay fixture (D5)
# ===========================================================================

class TestKidsIncidentReplay:

    def test_kids_incident_2026_08_09_produces_comfort_delay(self, fake_clock):
        """D5 replay: drive the two zone_2 manual events through the real
        _handle_climate_change and confirm a comfort_delay_started fires
        AND severe/normal handlers do NOT."""
        fixture_path = os.path.join(
            _HERE, "fixtures", "arrester_comfort",
            "kids_incident_2026-08-09.json",
        )
        with open(fixture_path) as f:
            fixture = json.load(f)
        climate_rows = fixture["climate.up_hallway_zone_2"]
        # The two "away -> manual" transitions in the fixture (temp change
        # events on preset_mode flip):
        manual_transitions = [
            i for i in range(1, len(climate_rows))
            if climate_rows[i]["attrs"]["preset_mode"] == "manual"
            and climate_rows[i - 1]["attrs"]["preset_mode"] != "manual"
        ]
        assert len(manual_transitions) >= 2, "fixture must have >=2 manual flips"

        # Build arrester with fixture-consistent zone (occupied — kids).
        a = _make_arrester(soc=99.0)
        a._zone_manager.zones[ZONE_ID].hvac_mode = "heat_cool"

        # Only the FIRST manual transition (high 80->76, low 68->69,
        # current_temp 80) is unambiguously comfort-qualifying: current
        # is at/above new high AND new_high moved down by 4°F. The
        # second (high 80->80, low 68->73) is inside the new deadband
        # and correctly fails the predicate (§3.2 worked example
        # "reversed drag"). Assert grant on the first; do not require it
        # for the second.
        first_two = manual_transitions[:1]
        for i in first_two:
            old_r = climate_rows[i - 1]
            new_r = climate_rows[i]
            old_st = MagicMock()
            old_st.state = "heat_cool"
            old_st.attributes = dict(old_r["attrs"])
            old_st.last_updated = datetime.fromtimestamp(
                old_r["ts"], tz=timezone.utc,
            )
            new_st = MagicMock()
            new_st.state = "heat_cool"
            new_st.attributes = dict(new_r["attrs"])
            new_st.last_updated = datetime.fromtimestamp(
                new_r["ts"], tz=timezone.utc,
            )
            # Set fake clock to just after the state event so freshness
            # check passes.
            fake_clock.t = new_st.last_updated + timedelta(seconds=1)
            ev = MagicMock()
            ev.data = {"entity_id": CLIMATE, "old_state": old_st, "new_state": new_st}
            ev.context = types.SimpleNamespace(user_id=None)
            a._handle_climate_change(ev)
            # Each qualifying manual seeds a fresh grant.
            assert ZONE_ID in a._comfort_delay_timers
            # Standard severe/normal branch MUST NOT have run.
            assert ZONE_ID not in a._grace_timers

    def test_kids_incident_neutered_grace_falls_to_severe(self, fake_clock, monkeypatch):
        """Mutation drill: setting COMFORT_GRACE_MIN=0 (grace disabled)
        MUST make the replay red — the standard severe branch fires
        instead of the comfort-delay grant."""
        monkeypatch.setattr(hvac_override, "COMFORT_GRACE_MIN", 0)
        fixture_path = os.path.join(
            _HERE, "fixtures", "arrester_comfort",
            "kids_incident_2026-08-09.json",
        )
        with open(fixture_path) as f:
            fixture = json.load(f)
        climate_rows = fixture["climate.up_hallway_zone_2"]
        manual_transitions = [
            i for i in range(1, len(climate_rows))
            if climate_rows[i]["attrs"]["preset_mode"] == "manual"
            and climate_rows[i - 1]["attrs"]["preset_mode"] != "manual"
        ]
        a = _make_arrester(soc=99.0)
        a._zone_manager.zones[ZONE_ID].hvac_mode = "heat_cool"

        i = manual_transitions[0]
        old_r = climate_rows[i - 1]
        new_r = climate_rows[i]
        old_st = MagicMock()
        old_st.state = "heat_cool"
        old_st.attributes = dict(old_r["attrs"])
        old_st.last_updated = datetime.fromtimestamp(old_r["ts"], tz=timezone.utc)
        new_st = MagicMock()
        new_st.state = "heat_cool"
        new_st.attributes = dict(new_r["attrs"])
        new_st.last_updated = datetime.fromtimestamp(new_r["ts"], tz=timezone.utc)
        fake_clock.t = new_st.last_updated + timedelta(seconds=1)
        ev = MagicMock()
        ev.data = {"entity_id": CLIMATE, "old_state": old_st, "new_state": new_st}
        ev.context = types.SimpleNamespace(user_id=None)
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers
        # Standard severe grace timer fired (80->76 = 4°F delta > severe threshold 3°F).
        assert ZONE_ID in a._grace_timers


# ===========================================================================
# Fix-up tests (ARREST-COMFORT-1 consolidated fix-up cycle)
# ===========================================================================


class TestACRIT1LiveOccupancy:
    """A-CRIT-1: predicate + comfort_delay_active MUST read live
    any_room_occupied, not the static zone_persons config list."""

    def test_configured_persons_but_vacant_zone_does_not_grant(self, fake_clock):
        # zone_persons is populated (residents ARE configured) but no
        # room is currently occupied → predicate must fail.
        a = _make_arrester()
        # Zone still has zone_persons=[PERSON] from _make_arrester, but
        # flip live occupancy off:
        for rc in a._zone_manager.zones[ZONE_ID].room_conditions:
            rc.occupied = False
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_mid_grace_vacancy_flips_comfort_delay_active_false(self, fake_clock):
        # Grant, then flip live occupancy off — comfort_delay_active must
        # return False on next evaluation AND log expiry_reason=zone_unoccupied.
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert a.comfort_delay_active(ZONE_ID) is True
        for rc in a._zone_manager.zones[ZONE_ID].room_conditions:
            rc.occupied = False
        # comfort_delay_active returns False AND evicts the timer with
        # the ledger row expiry_reason="zone_unoccupied" (fix A-LOW-1).
        assert a.comfort_delay_active(ZONE_ID) is False
        assert ZONE_ID not in a._comfort_delay_timers


class TestALOW2LastUpdatedFailClosed:
    """A-LOW-2: last_updated is None MUST fail closed."""

    def test_last_updated_none_fails_closed(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        # Force last_updated=None on the new_state:
        ev.data["new_state"].last_updated = None
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers


class TestAHIGH1LiveKnobs:
    """A-HIGH-1: rung-3 knobs flow to predicate/gate via setter."""

    def test_soc_floor_setter_at_zero_disables_gate(self, fake_clock):
        a = _make_arrester(soc=1.0)
        # Live knob at 0 = SOC-blind grant.
        a.set_comfort_soc_floor_pct(0)
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID in a._comfort_delay_timers

    def test_grace_setter_at_zero_disables_feature(self, fake_clock):
        a = _make_arrester()
        a.set_comfort_grace_min(0)
        ev = _make_event(hvac_mode="heat_cool",
                         old_high=80, new_high=72,
                         old_low=68, new_low=68,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        # Feature dead: predicate branch skipped, falls through to
        # standard arrest (matches the module-const kill-switch test
        # in TestKillSwitches::test_grace_min_zero_disables_feature).
        assert ZONE_ID not in a._comfort_delay_timers
        assert ZONE_ID in a._grace_timers


class TestCH2BootWarn:
    """C-H2: caplog assertion for the SOC-floor boot WARN (0 < v < 20)."""

    def test_soc_floor_setter_warn_in_danger_band(self, fake_clock, caplog):
        a = _make_arrester()
        with caplog.at_level("WARNING"):
            a.set_comfort_soc_floor_pct(15)
        assert any(
            "below 20%" in rec.message for rec in caplog.records
        ), "boot WARN missing for 0<floor<20"

    def test_soc_floor_setter_no_warn_at_zero_kill_switch(self, fake_clock, caplog):
        a = _make_arrester()
        with caplog.at_level("WARNING"):
            a.set_comfort_soc_floor_pct(0)
        # 0 is the documented kill-switch — no danger-band WARN.
        assert not any(
            "below 20%" in rec.message for rec in caplog.records
        )


class TestDMED1RevertShortCircuit:
    """D-MED-1: _revert_override short-circuits under comfort-delay."""

    @pytest.mark.asyncio
    async def test_revert_no_set_hvac_mode_during_grace(self, fake_clock):
        a = _make_arrester()
        # Seed a grant so comfort_delay_active is True.
        a._seed_comfort_delay(a._zone_manager.zones[ZONE_ID], {
            "zone_id": ZONE_ID, "climate_entity_id": CLIMATE,
            "hvac_mode": "cool", "current_temp": 79.0, "delta_f": 4.0,
            "direction": "cooler", "granted_setpoint": 72.0,
        })
        # Zone in cool mode (not heat_cool) — pre-fix would emit
        # set_hvac_mode to re-assert heat_cool.
        a._zone_manager.zones[ZONE_ID].hvac_mode = "cool"
        st = MagicMock()
        st.attributes = {"hvac_modes": ["heat_cool", "cool"]}
        a.hass.states.get = MagicMock(return_value=st)
        calls: list = []
        async def fake_call(*args, **kwargs):
            calls.append((args, kwargs))
        a.hass.services.async_call = fake_call
        await a._revert_override(a._zone_manager.zones[ZONE_ID], "away")
        # Short-circuit: NEITHER set_hvac_mode NOR set_preset_mode fires.
        assert not any(args[:2] == ("climate", "set_hvac_mode") for args, _ in calls)
        assert not any(args[:2] == ("climate", "set_preset_mode") for args, _ in calls)


class TestCH1LedgerEmit:
    """C-H1: deferred write must queue a ledger row via _log_deferred_write."""

    @pytest.mark.asyncio
    async def test_S3_defer_emits_ledger_row(self, fake_clock, monkeypatch):
        import custom_components.universal_room_automation.domain_coordinators.hvac_setpoint as setpoint
        emitted: list = []
        def spy(hass, *, site, zone_id, entity_id, reason, would_have_emitted):
            emitted.append({"site": site, "zone_id": zone_id, "reason": reason})
        monkeypatch.setattr(setpoint, "_log_deferred_write", spy)
        a = _make_arrester()
        a._seed_comfort_delay(a._zone_manager.zones[ZONE_ID], {
            "zone_id": ZONE_ID, "climate_entity_id": CLIMATE,
            "hvac_mode": "cool", "current_temp": 79.0, "delta_f": 4.0,
            "direction": "cooler", "granted_setpoint": 72.0,
        })
        async def fake_call(*args, **kwargs):
            pass
        a.hass.services.async_call = fake_call
        await a._apply_compromise(a._zone_manager.zones[ZONE_ID],
                                  "away", 74.0, 70.0, 76.0, 70.0)
        assert any(e["site"] == "S3_compromise" for e in emitted)


class TestCLOWFailClosedAnchors:
    """C-LOW D6/D8/D10: fail-closed gates on hvac_mode off / temp None /
    battery_blind — each site's own check must be load-bearing."""

    def test_D6_hvac_off_fails_closed_even_with_populated_temps(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="off", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        # new_state carries valid temps but state=="off"
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_D8_current_temp_none_fails_closed(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=None,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers

    def test_D10_battery_blind_fails_closed_with_valid_soc(self, fake_clock):
        # blind=True even though we still supply a numeric SOC — the
        # blind flag alone must veto the grant.
        a = _make_arrester(soc=95.0, blind=True)
        ev = _make_event(hvac_mode="cool", old_sp=76, new_sp=72,
                         current_temp=79,
                         last_updated=fake_clock.utcnow())
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._comfort_delay_timers


# ===========================================================================
# Fix-up follow-up (orchestrator re-drill 2026-08-10): caller-site drills
# for S10 (hvac.py DPM apply), S11/S12/S13 (hvac_predict.py). The prior
# fix-up commit wired the gates but left NO test authority at these caller
# sites — mutating `gate=None` at the call site reddened zero tests. These
# tests drive the ACTUAL production methods so `gate=None` at the specific
# call site is a red-producing mutation.
# ===========================================================================


def _make_predictor(*, comfort_active: bool):
    """Construct a minimal HVACPredictor via __new__ (bypass __init__) with
    just enough attributes for the release-banked / pre-cool / pre-heat
    methods. The arrester's `comfort_delay_active` is forced to the
    requested return so the gate outcome is deterministic."""
    pred = HVACPredictor.__new__(HVACPredictor)
    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    calls: list = []
    async def _capture(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
    hass.services.async_call = _capture
    pred.hass = hass
    zone = ZoneState(
        zone_id=ZONE_ID, zone_name="Zone A", climate_entity=CLIMATE,
    )
    zone.target_temp_high = 78.0
    zone.target_temp_low = 68.0
    pred._zone_manager = types.SimpleNamespace(zones={ZONE_ID: zone})
    pred._egress_manager = None
    # Arrester with a hard-coded comfort_delay_active return.
    arrester = MagicMock()
    arrester.comfort_delay_active = MagicMock(return_value=bool(comfort_active))
    arrester.suppress = MagicMock()
    arrester.unsuppress = MagicMock()
    pred._override_arrester = arrester
    # HC backref: freeze inactive.
    pred._hvac_coord = types.SimpleNamespace(freeze_active=False)
    # Fields the release-banked path reads.
    pred._solar_bank_floor = 72.0
    return pred, calls


@pytest.mark.asyncio
class TestFixupWriteSiteCallerDrills:
    """Caller-site anchors: driving the REAL production method must defer
    (no service call) under grace AND fire under no-grace. Mutation of
    `gate=None` at the call site would leave the emit unconditional →
    grace test reds (asserts no call, gets a call)."""

    async def test_S11_release_banked_defers_under_grace(self):
        pred, calls = _make_predictor(comfort_active=True)
        # Seed a `_last_emitted_range` baseline so _resolve_baseline_range
        # returns a value (the release path needs it).
        pred._hvac_coord = types.SimpleNamespace(
            freeze_active=False,
            _last_emitted_range={ZONE_ID: (68.0, 78.0)},
        )
        await pred._release_banked_zones({ZONE_ID})
        assert not any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), "S11: release-banked emit MUST be deferred under active grace"

    async def test_S11_release_banked_fires_without_grace(self):
        pred, calls = _make_predictor(comfort_active=False)
        pred._hvac_coord = types.SimpleNamespace(
            freeze_active=False,
            _last_emitted_range={ZONE_ID: (68.0, 78.0)},
        )
        await pred._release_banked_zones({ZONE_ID})
        assert any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), "S11: release-banked emit MUST fire when grace is inactive"

    async def test_S12_pre_cool_defers_under_grace(self):
        pred, calls = _make_predictor(comfort_active=True)
        zone = pred._zone_manager.zones[ZONE_ID]
        await pred._execute_zone_pre_cool(zone, offset=-3.0, reason="test")
        assert not any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), "S12: pre-cool emit MUST be deferred under active grace"

    async def test_S12_pre_cool_fires_without_grace(self):
        pred, calls = _make_predictor(comfort_active=False)
        zone = pred._zone_manager.zones[ZONE_ID]
        await pred._execute_zone_pre_cool(zone, offset=-3.0, reason="test")
        assert any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), "S12: pre-cool emit MUST fire when grace is inactive"

    async def test_S13_pre_heat_defers_under_grace(self):
        pred, calls = _make_predictor(comfort_active=True)
        # any_room_occupied gate in _execute_pre_heat requires True.
        from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
            RoomCondition,
        )
        pred._zone_manager.zones[ZONE_ID].room_conditions = [
            RoomCondition(room_name="r", occupied=True),
        ]
        await pred._execute_pre_heat()
        assert not any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), "S13: pre-heat emit MUST be deferred under active grace"

    async def test_S13_pre_heat_fires_without_grace(self):
        pred, calls = _make_predictor(comfort_active=False)
        from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
            RoomCondition,
        )
        pred._zone_manager.zones[ZONE_ID].room_conditions = [
            RoomCondition(room_name="r", occupied=True),
        ]
        await pred._execute_pre_heat()
        assert any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), "S13: pre-heat emit MUST fire when grace is inactive"


# ---------------------------------------------------------------------------
# S10 (hvac.py DPM apply) caller-site drill — via a minimal HVACCoordinator
# instance driven through the actual `_async_apply_preset_overrides`.
# ---------------------------------------------------------------------------

# Load hvac.py real (needs base + covers + fans + egress + predict already
# loaded; predict is loaded above, others we stub).
def _ensure_hvac_module_loaded():
    key = "custom_components.universal_room_automation.domain_coordinators.hvac"
    if key in sys.modules and getattr(sys.modules[key], "__file__", None):
        return sys.modules[key]
    # LAZY storage stub: hvac.py needs `from homeassistant.helpers.storage
    # import Store`. Install just long enough for the import, then REMOVE
    # so the module-scope stub doesn't linger and flip the `_HA_REAL`
    # sentinel other test files use (see the note in `_mods`).
    _storage_key = "homeassistant.helpers.storage"
    _installed_storage = False
    if _storage_key not in sys.modules:
        _storage_stub = types.ModuleType(_storage_key)
        _storage_stub.Store = MagicMock  # type: ignore[attr-defined]
        sys.modules[_storage_key] = _storage_stub
        _installed_storage = True
    for stub_key, stub_attrs in (
        ("custom_components.universal_room_automation.domain_coordinators.base",
         {"BaseCoordinator": object,
          "CoordinatorAction": object,
          "Intent": object,
          "Severity": types.SimpleNamespace(
              LOW="low", MEDIUM="medium", HIGH="high", CRITICAL="critical")}),
        ("custom_components.universal_room_automation.domain_coordinators.hvac_covers",
         {"CoverController": object}),
        ("custom_components.universal_room_automation.domain_coordinators.hvac_fans",
         {"FanController": object}),
        ("custom_components.universal_room_automation.domain_coordinators.hvac_egress",
         {"EgressManager": object}),
    ):
        if stub_key not in sys.modules:
            m = types.ModuleType(stub_key)
            for k, v in stub_attrs.items():
                setattr(m, k, v)
            sys.modules[stub_key] = m
    try:
        mod = _load(key, "domain_coordinators/hvac.py")
    finally:
        # Roll back the lazy storage stub so we don't pollute the
        # `_HA_REAL` sentinel used by test_hvac_ac_ramp_savings and
        # sibling behavioral DAO tests. hvac.py already imported Store
        # into its namespace, so it continues to work after removal.
        if _installed_storage:
            sys.modules.pop(_storage_key, None)
    return mod


@pytest.mark.asyncio
class TestFixupS10DPMApplyCallerDrill:
    """S10_dpm_apply caller-site drill. Drive the REAL
    `HVACCoordinator._async_apply_preset_overrides` with an active
    comfort grace and assert NO climate.set_temperature service call
    lands. Then re-run with grace inactive and assert the call DOES land.
    Mutation `gate=None` at the S10 call site in hvac.py leaves the emit
    unconditional → the grace test reds (unexpected service call)."""

    def _build_hc(self, *, comfort_active: bool):
        hvac_mod = _ensure_hvac_module_loaded()
        HC = hvac_mod.HVACCoordinator
        hc = HC.__new__(HC)
        hass = MagicMock()
        hass.services = MagicMock()
        calls: list = []
        async def _capture(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
        hass.services.async_call = _capture
        # DOMAIN key path required by _async_apply_preset_overrides.
        from custom_components.universal_room_automation.const import DOMAIN
        # Fake EC exposes _dynamic_preset_overrides.
        ec = types.SimpleNamespace(_dynamic_preset_overrides={ZONE_ID: []})
        manager = types.SimpleNamespace(coordinators={"energy": ec})
        hass.data = {DOMAIN: {"coordinator_manager": manager}}
        hc.hass = hass
        # Minimal fields the method reads.
        hc._guest_mode_actuation_enabled = True
        hc._house_state = "home_day"
        hc._freeze_active = False
        hc._last_emitted_range = {}
        # Zone.
        zone = ZoneState(
            zone_id=ZONE_ID, zone_name="Zone A", climate_entity=CLIMATE,
        )
        hc._zone_manager = types.SimpleNamespace(
            zones={ZONE_ID: zone},
        )
        # Preset manager returns a baseline that will differ from
        # _last_emitted_range (so the throttle guard doesn't skip).
        pm = types.SimpleNamespace(
            get_preset_for_house_state=lambda _s: "home",
            get_seasonal_setpoints=lambda _p: (78.0, 68.0),
        )
        hc._preset_manager = pm
        # No egress pause.
        hc._egress_manager = None
        # Arrester with controlled comfort_delay_active + no shave.
        arrester = MagicMock()
        arrester.comfort_delay_active = MagicMock(return_value=bool(comfort_active))
        arrester._corrective_writes_suppressed = MagicMock(return_value=False)
        arrester.suppress = MagicMock()
        arrester.unsuppress = MagicMock()
        hc._override_arrester = arrester
        return hc, calls

    async def test_S10_dpm_apply_defers_under_grace(self):
        hc, calls = self._build_hc(comfort_active=True)
        await hc._async_apply_preset_overrides()
        assert not any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), (
            "S10: DPM apply emit MUST be deferred under active grace "
            "(mutation `gate=None` at hvac.py DPM apply site would leave "
            "the emit unconditional and this assert would red)"
        )

    async def test_S10_dpm_apply_fires_without_grace(self):
        hc, calls = self._build_hc(comfort_active=False)
        await hc._async_apply_preset_overrides()
        assert any(
            c["args"][:2] == ("climate", "set_temperature") for c in calls
        ), "S10: DPM apply emit MUST fire when grace is inactive"

    async def test_S10_defer_rolls_back_suppress(self):
        """Fix #9 companion: on defer at S10, the pre-emit suppress()
        stamp MUST be rolled back via unsuppress() so a real manual
        within SUPPRESS_TTL_SECONDS is not swallowed. Mutation removing
        the `unsuppress` on the defer branch would leave suppress stamped
        without a corresponding rollback and this assert reds."""
        hc, calls = self._build_hc(comfort_active=True)
        arrester = hc._override_arrester
        await hc._async_apply_preset_overrides()
        # suppress MUST have been called once by the DPM apply loop.
        assert arrester.suppress.called, "DPM apply should call suppress() pre-emit"
        # Then unsuppress MUST have been called to roll it back.
        assert arrester.unsuppress.called, (
            "S10 defer branch MUST call unsuppress() to roll back the "
            "pre-emit suppress stamp (fix #9 companion)"
        )


class TestCH5D3CoastGuard:
    """C-H5: D3 coast-precedence guard reason-ledger leaf `comfort_delay_active`
    is load-bearing (mutation of the accessor OR the `_cd_active` conjunct
    would flip the effective_preset back to away)."""

    def test_preset_change_reason_comfort_delay_active_leaf(self):
        # This is a smoke-anchor: the string literal
        # "comfort_delay_active" MUST appear in the D3 relabel branch in
        # hvac.py. Mutation of the assignment reddens this anchor.
        hvac_src = os.path.join(_URA_PATH, "domain_coordinators", "hvac.py")
        with open(hvac_src) as f:
            src = f.read()
        # There MUST be a preset_change_reason assignment to the leaf.
        assert 'preset_change_reason = "comfort_delay_active"' in src, (
            "Fix-up C-H5 anchor: the D3 relabel leaf assignment is missing"
        )

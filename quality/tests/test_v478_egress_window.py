"""v4.7.8 — Egress Window HVAC Pause.

Tier 2-DB cycle tests. Covers:
  - State-machine transitions
  - Manual override + cooldown
  - Multi-room aggregation
  - Restart resilience scenarios R1-R4 + first-tick gate
  - NM dispatch dedup + observation-mode gate
  - Source-grep / AST contracts on switch / numbers / sensors / cross-rule guards

HA modules are stubbed (see _load_egress_module) so this file can run without
a real Home Assistant install. Mirrors the loader shape used in
test_v4513_1_zone_dedup.py.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_REL = "custom_components/universal_room_automation"
EGRESS_PY = os.path.join(ROOT_REL, "domain_coordinators", "hvac_egress.py")
HVAC_PY = os.path.join(ROOT_REL, "domain_coordinators", "hvac.py")
HVAC_OVERRIDE_PY = os.path.join(ROOT_REL, "domain_coordinators", "hvac_override.py")
HVAC_PREDICT_PY = os.path.join(ROOT_REL, "domain_coordinators", "hvac_predict.py")
HVAC_ZONES_PY = os.path.join(ROOT_REL, "domain_coordinators", "hvac_zones.py")
HVAC_CONST_PY = os.path.join(ROOT_REL, "domain_coordinators", "hvac_const.py")
SWITCH_PY = os.path.join(ROOT_REL, "switch.py")
NUMBER_PY = os.path.join(ROOT_REL, "number.py")
CONFIG_FLOW_PY = os.path.join(ROOT_REL, "config_flow.py")
CONST_PY = os.path.join(ROOT_REL, "const.py")


def _read(path: str) -> str:
    """Read source files as utf-8 (em-dashes break locale-bound default reads)."""
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Module loader — stubs HA + ura package siblings, loads hvac_egress.
# ---------------------------------------------------------------------------


def _load_egress_module():
    if "ura_egress_under_test" in sys.modules:
        return sys.modules["ura_egress_under_test"]

    # Stub homeassistant surface.
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
        sys.modules["homeassistant"].__path__ = []
    if "homeassistant.core" not in sys.modules:
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = type("HomeAssistant", (), {})
        ha_core.callback = lambda f: f
        sys.modules["homeassistant.core"] = ha_core
    if "homeassistant.helpers" not in sys.modules:
        ha_helpers = types.ModuleType("homeassistant.helpers")
        ha_helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = ha_helpers
    if "homeassistant.helpers.dispatcher" not in sys.modules:
        ha_disp = types.ModuleType("homeassistant.helpers.dispatcher")
        ha_disp.async_dispatcher_send = lambda *a, **kw: None
        sys.modules["homeassistant.helpers.dispatcher"] = ha_disp
    if "homeassistant.util" not in sys.modules:
        ha_util = types.ModuleType("homeassistant.util")
        ha_util.__path__ = []
        sys.modules["homeassistant.util"] = ha_util
    # Only install our stub if no homeassistant.util.dt is registered yet.
    # If another test already installed one, we DON'T mutate it — we patch
    # the egress module's `dt_util` attribute directly after import below.
    if "homeassistant.util.dt" not in sys.modules:
        ha_util_dt = types.ModuleType("homeassistant.util.dt")
        ha_util_dt.now = lambda: datetime.now(timezone.utc)
        ha_util_dt.utcnow = lambda: datetime.now(timezone.utc)
        ha_util_dt.parse_datetime = lambda s: (
            datetime.fromisoformat(s) if s else None
        )
        sys.modules["homeassistant.util.dt"] = ha_util_dt

    # Stub ura package + const + hvac_const.
    pkg = types.ModuleType("ura_egress_pkg")
    pkg.__path__ = []
    sys.modules["ura_egress_pkg"] = pkg
    const = types.ModuleType("ura_egress_pkg.const")
    const.DOMAIN = "universal_room_automation"
    sys.modules["ura_egress_pkg.const"] = const
    coord_pkg = types.ModuleType("ura_egress_pkg.domain_coordinators")
    coord_pkg.__path__ = []
    sys.modules["ura_egress_pkg.domain_coordinators"] = coord_pkg

    # Load real hvac_const.
    hvac_const_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_const.py"
    spec = importlib.util.spec_from_file_location(
        "ura_egress_pkg.domain_coordinators.hvac_const", str(hvac_const_src),
    )
    hvac_const = importlib.util.module_from_spec(spec)
    sys.modules["ura_egress_pkg.domain_coordinators.hvac_const"] = hvac_const
    spec.loader.exec_module(hvac_const)

    # Stub hvac_zones (iter_canonical_hvac_zones monkey-patched per test).
    hvac_zones = types.ModuleType("ura_egress_pkg.domain_coordinators.hvac_zones")
    hvac_zones.iter_canonical_hvac_zones = lambda hass: []
    sys.modules["ura_egress_pkg.domain_coordinators.hvac_zones"] = hvac_zones

    # Stub base.Severity.
    base = types.ModuleType("ura_egress_pkg.domain_coordinators.base")
    class _Sev:
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        CRITICAL = "critical"
    base.Severity = _Sev
    sys.modules["ura_egress_pkg.domain_coordinators.base"] = base

    # Load hvac_egress.
    egress_src_path = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_egress.py"
    spec = importlib.util.spec_from_file_location(
        "ura_egress_pkg.domain_coordinators.hvac_egress", str(egress_src_path),
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "ura_egress_pkg.domain_coordinators"
    sys.modules["ura_egress_pkg.domain_coordinators.hvac_egress"] = mod
    spec.loader.exec_module(mod)

    # Replace dt_util on the loaded module with a controllable stub so
    # state_label / cooldown sweep comparisons are deterministic. We do NOT
    # mutate the global homeassistant.util.dt module — other tests rely on it.
    class _DtStub:
        _NOW_OVERRIDE = None

        @classmethod
        def now(cls):
            if cls._NOW_OVERRIDE is not None:
                return cls._NOW_OVERRIDE
            return datetime.now(timezone.utc)

        @classmethod
        def utcnow(cls):
            return cls.now()

        @staticmethod
        def parse_datetime(s):
            return datetime.fromisoformat(s) if s else None

    mod.dt_util = _DtStub
    sys.modules["ura_egress_under_test"] = mod
    return mod


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeRoomCondition:
    room_name: str
    is_egress_window: bool = True
    window_state: str | None = "off"
    window_sensor: str | None = None


@dataclass
class _FakeZoneState:
    zone_id: str
    zone_name: str
    climate_entity: str
    room_conditions: list = field(default_factory=list)


class _FakeZoneManager:
    def __init__(self, zones):
        self.zones = zones


class _FakeDB:
    def __init__(self):
        self.rows: dict = {}
        self.calls: list = []

    async def get_egress_state(self, zone_id):
        self.calls.append(f"get:{zone_id}")
        return self.rows.get(zone_id)

    async def save_egress_state(self, state):
        self.calls.append(f"save:{state['zone_id']}:{state['state']}")
        self.rows[state["zone_id"]] = dict(state)

    async def get_all_egress_state(self):
        self.calls.append("scan")
        return list(self.rows.values())

    async def clear_egress_state(self, zone_id):
        self.calls.append(f"clear:{zone_id}")
        self.rows.pop(zone_id, None)


class _FakeHassStates:
    def __init__(self):
        self._mapping = {}

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class _FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append({"domain": domain, "service": service,
                           "data": dict(data), "blocking": blocking})


class _FakeHass:
    def __init__(self, nm_calls):
        self.states = _FakeHassStates()
        self.services = _FakeServices()
        self.data = {}
        nm_calls_ref = nm_calls

        class _NMStub:
            async def async_notify(_self, **kw):
                nm_calls_ref.append(kw)

        self.data["universal_room_automation"] = {"notification_manager": _NMStub()}

    def set_state(self, entity_id, state, attrs=None):
        st = MagicMock()
        st.state = state
        st.attributes = attrs or {}
        self.states._mapping[entity_id] = st


def _make_em(
    *,
    threshold_min: int = 3,
    resume_delay_min: int = 1,
    enabled: bool = True,
    zones=None,
    db=None,
):
    mod = _load_egress_module()
    nm_calls: list = []
    hass = _FakeHass(nm_calls)
    zm = _FakeZoneManager(zones or {})
    db = db if db is not None else _FakeDB()
    em = mod.EgressManager(
        hass, zm, db=db,
        threshold_min=threshold_min,
        resume_delay_min=resume_delay_min,
        enabled=enabled,
    )
    # v4.7.8 fix-up B-H2 / B-H3: in tests, the master switch + 2 Numbers
    # do NOT exist — so their deferred-restore callbacks never land. Clear
    # the initial-restore gate so async_tick can fire. Real boot has the
    # 60s force-release timer in HVACCoordinator.async_setup.
    try:
        em.force_release_initial_restore_gate()
    except Exception:
        pass

    # Patch iter_canonical_hvac_zones inside the loaded hvac_zones stub.
    hvac_zones = sys.modules["ura_egress_pkg.domain_coordinators.hvac_zones"]

    def _fake_iter(_hass):
        return [
            {"zone_id": zid, "zone_name": z.zone_name,
             "climate_entity": z.climate_entity}
            for zid, z in zm.zones.items()
        ]

    hvac_zones.iter_canonical_hvac_zones = _fake_iter
    return em, hass, zm, db, nm_calls


def _rc_open(room_name, is_egress=True):
    return _FakeRoomCondition(room_name=room_name, is_egress_window=is_egress,
                              window_state="on")


def _rc_closed(room_name, is_egress=True):
    return _FakeRoomCondition(room_name=room_name, is_egress_window=is_egress,
                              window_state="off")


def _now_at(seconds=0):
    return datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def _set_test_now(when: datetime) -> None:
    """Override dt_util.now() inside the loaded module so state_label /
    cooldown comparisons are deterministic. Patches the module-local dt_util
    stub (not the global homeassistant.util.dt module)."""
    mod = _load_egress_module()
    mod.dt_util._NOW_OVERRIDE = when


# ---------------------------------------------------------------------------
# State-machine tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v478_state_idle_to_counting_to_paused():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool", {"preset_mode": "home"})
    t0 = _now_at(0)
    await em.async_tick(t0)
    assert em.state_label("zone_2") == "counting"
    await em.async_tick(t0 + timedelta(minutes=4))
    assert em.is_paused("zone_2")
    info = em.get_zone_info("zone_2")
    assert info["saved_mode"] == "heat_cool"
    assert info["saved_preset"] == "home"


@pytest.mark.asyncio
async def test_v478_paused_to_resume_countdown_to_restore():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3, resume_delay_min=1)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool", {"preset_mode": "home"})
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=4))
    assert em.is_paused("zone_2")
    z.room_conditions = [_rc_closed("jaya_bedroom")]
    hass.set_state("climate.up_hallway_zone_2", "off", {"preset_mode": "home"})
    await em.async_tick(t0 + timedelta(minutes=5))
    assert em.state_label("zone_2") == "resume_countdown"
    await em.async_tick(t0 + timedelta(minutes=7))
    assert not em.is_paused("zone_2")
    modes = [c["data"].get("hvac_mode") for c in hass.services.calls
             if c["service"] == "set_hvac_mode"]
    assert "heat_cool" in modes


@pytest.mark.asyncio
async def test_v478_threshold_resets_when_window_closes_before_threshold_hit():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0)
    assert em.state_label("zone_2") == "counting"
    z.room_conditions = [_rc_closed("jaya_bedroom")]
    await em.async_tick(t0 + timedelta(minutes=1))
    assert em.state_label("zone_2") == "idle"


@pytest.mark.asyncio
async def test_v478_multi_room_aggregation_per_canonical_zone():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    sahil_open = _rc_open("sahil_bedroom", is_egress=False)
    jaya_closed = _rc_closed("jaya_bedroom", is_egress=True)
    z.room_conditions = [sahil_open, jaya_closed]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=5))
    assert em.state_label("zone_2") == "idle"


@pytest.mark.asyncio
async def test_v478_manual_override_during_grace_does_not_engage_cooldown():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=4))
    assert em.is_paused("zone_2")
    hass.set_state("climate.up_hallway_zone_2", "cool")
    await em.async_tick(t0 + timedelta(minutes=4, seconds=10))
    assert em.state_label("zone_2") == "paused"
    assert "zone_2" not in em.get_cooldowns()


@pytest.mark.asyncio
async def test_v478_manual_override_after_grace_engages_cooldown_for_one_hour():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=4))
    assert em.is_paused("zone_2")
    hass.set_state("climate.up_hallway_zone_2", "cool")
    await em.async_tick(t0 + timedelta(minutes=6))
    # Freeze "now" inside state_label so the cooldown future comparison works.
    _set_test_now(t0 + timedelta(minutes=6))
    assert em.state_label("zone_2") == "cooldown"
    assert "zone_2" in em.get_cooldowns()


# ---------------------------------------------------------------------------
# Restart resilience scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v478_r1_restart_keeps_zone_paused_with_window_open():
    db = _FakeDB()
    t0 = _now_at(0)
    db.rows["zone_2"] = {
        "zone_id": "zone_2", "state": "paused",
        "first_open_at": None, "first_closed_at": None,
        "paused_at": t0.isoformat(),
        "saved_hvac_mode": "heat_cool", "saved_preset_mode": "home",
        "triggered_by_room": "jaya_bedroom",
        "thermostat_entity": "climate.up_hallway_zone_2",
        "cooldown_expires_at": None,
        "last_update_ts": t0.isoformat(),
    }
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, db=db)
    await em.async_rehydrate_from_db()
    assert em.rehydrate_done
    assert em.is_paused("zone_2")
    hass.set_state("climate.up_hallway_zone_2", "off")
    await em.async_tick(t0 + timedelta(seconds=5))
    assert em.is_paused("zone_2")
    assert len([c for c in hass.services.calls if c["service"] == "set_hvac_mode"]) == 0


@pytest.mark.asyncio
async def test_v478_r2_restart_then_window_closes_resumes_correctly():
    db = _FakeDB()
    t0 = _now_at(0)
    closed_at = t0 - timedelta(seconds=30)
    paused_at = t0 - timedelta(minutes=10)
    db.rows["zone_2"] = {
        "zone_id": "zone_2", "state": "resume_countdown",
        "first_open_at": None, "first_closed_at": closed_at.isoformat(),
        "paused_at": paused_at.isoformat(),
        "saved_hvac_mode": "heat_cool", "saved_preset_mode": "home",
        "triggered_by_room": "jaya_bedroom",
        "thermostat_entity": "climate.up_hallway_zone_2",
        "cooldown_expires_at": None,
        "last_update_ts": t0.isoformat(),
    }
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_closed("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, db=db, resume_delay_min=1)
    hass.set_state("climate.up_hallway_zone_2", "off")
    await em.async_rehydrate_from_db()
    assert em.is_paused("zone_2")
    assert em.state_label("zone_2") == "resume_countdown"
    await em.async_tick(t0 + timedelta(seconds=45))
    assert not em.is_paused("zone_2")


@pytest.mark.asyncio
async def test_v478_r2b_restart_then_window_closed_already_starts_resume_countdown():
    db = _FakeDB()
    t0 = _now_at(0)
    db.rows["zone_2"] = {
        "zone_id": "zone_2", "state": "paused",
        "first_open_at": None, "first_closed_at": None,
        "paused_at": (t0 - timedelta(minutes=5)).isoformat(),
        "saved_hvac_mode": "heat_cool", "saved_preset_mode": "home",
        "triggered_by_room": "jaya_bedroom",
        "thermostat_entity": "climate.up_hallway_zone_2",
        "cooldown_expires_at": None,
        "last_update_ts": t0.isoformat(),
    }
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_closed("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, db=db, resume_delay_min=1)
    hass.set_state("climate.up_hallway_zone_2", "off")
    await em.async_rehydrate_from_db()
    await em.async_tick(t0)
    assert em.state_label("zone_2") == "resume_countdown"
    await em.async_tick(t0 + timedelta(seconds=65))
    assert not em.is_paused("zone_2")


@pytest.mark.asyncio
async def test_v478_r3_restart_with_accumulated_threshold_continues():
    db = _FakeDB()
    t0 = _now_at(0)
    first_open = t0 - timedelta(minutes=2)
    db.rows["zone_2"] = {
        "zone_id": "zone_2", "state": "counting",
        "first_open_at": first_open.isoformat(),
        "first_closed_at": None, "paused_at": None,
        "saved_hvac_mode": None, "saved_preset_mode": None,
        "triggered_by_room": None, "thermostat_entity": None,
        "cooldown_expires_at": None, "last_update_ts": t0.isoformat(),
    }
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, db=db, threshold_min=3)
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    await em.async_rehydrate_from_db()
    await em.async_tick(t0 + timedelta(seconds=30))
    assert em.state_label("zone_2") == "counting"
    await em.async_tick(t0 + timedelta(seconds=90))
    assert em.is_paused("zone_2")


@pytest.mark.asyncio
async def test_v478_r4_restart_during_cooldown_preserves_expiry():
    db = _FakeDB()
    t0 = _now_at(0)
    expires = t0 + timedelta(minutes=30)
    db.rows["zone_2"] = {
        "zone_id": "zone_2", "state": "cooldown",
        "first_open_at": None, "first_closed_at": None, "paused_at": None,
        "saved_hvac_mode": None, "saved_preset_mode": None,
        "triggered_by_room": None, "thermostat_entity": None,
        "cooldown_expires_at": expires.isoformat(),
        "last_update_ts": t0.isoformat(),
    }
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, db=db, threshold_min=3)
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    await em.async_rehydrate_from_db()
    _set_test_now(t0)
    assert em.state_label("zone_2") == "cooldown"
    await em.async_tick(t0 + timedelta(minutes=5))
    _set_test_now(t0 + timedelta(minutes=5))
    assert em.state_label("zone_2") == "cooldown"
    await em.async_tick(t0 + timedelta(minutes=31))
    _set_test_now(t0 + timedelta(minutes=31))
    assert "zone_2" not in em.get_cooldowns()


@pytest.mark.asyncio
async def test_v478_first_tick_post_restart_rehydrates_state_before_action():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z})
    assert em._rehydrate_done is False
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0 + timedelta(minutes=10))
    assert em.state_label("zone_2") == "idle"
    assert not any(c["service"] == "set_hvac_mode" for c in hass.services.calls)


@pytest.mark.asyncio
async def test_v478_idempotent_restore_does_not_redispatch_when_already_off():
    db = _FakeDB()
    t0 = _now_at(0)
    db.rows["zone_2"] = {
        "zone_id": "zone_2", "state": "paused",
        "first_open_at": None, "first_closed_at": None,
        "paused_at": t0.isoformat(),
        "saved_hvac_mode": "heat_cool", "saved_preset_mode": "home",
        "triggered_by_room": "jaya_bedroom",
        "thermostat_entity": "climate.up_hallway_zone_2",
        "cooldown_expires_at": None,
        "last_update_ts": t0.isoformat(),
    }
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, db=db)
    hass.set_state("climate.up_hallway_zone_2", "off")
    await em.async_rehydrate_from_db()
    await em.async_tick(t0 + timedelta(seconds=10))
    assert em.is_paused("zone_2")
    assert not any(
        c["service"] == "set_hvac_mode" and c["data"].get("hvac_mode") == "off"
        for c in hass.services.calls
    )


# ---------------------------------------------------------------------------
# NM dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v478_nm_alert_paused_emits_once_per_day_per_zone():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, nm_calls = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=4))
    z.room_conditions = [_rc_closed("jaya_bedroom")]
    hass.set_state("climate.up_hallway_zone_2", "off")
    await em.async_tick(t0 + timedelta(minutes=5))
    await em.async_tick(t0 + timedelta(minutes=7))
    paused_n = sum(1 for c in nm_calls if c.get("hazard_type") == "hvac_egress"
                   and "paused" in c.get("title", "").lower())
    assert paused_n == 1


@pytest.mark.asyncio
async def test_v478_nm_alert_suppressed_in_observation_mode():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, nm_calls = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    fake_hvac = MagicMock()
    fake_hvac._observation_mode = True
    em.set_hvac_coord(fake_hvac)
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=4))
    assert nm_calls == []


@pytest.mark.asyncio
async def test_v478_disabled_clears_counters_but_keeps_paused_zone_paused():
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=4))
    assert em.is_paused("zone_2")
    em.enabled = False
    await em.async_tick(t0 + timedelta(minutes=5))
    assert em.is_paused("zone_2")


# ---------------------------------------------------------------------------
# Source-grep / AST contracts
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def egress_src():
    return _read(EGRESS_PY)


@pytest.fixture(scope="module")
def hvac_src():
    return _read(HVAC_PY)


@pytest.fixture(scope="module")
def override_src():
    return _read(HVAC_OVERRIDE_PY)


@pytest.fixture(scope="module")
def predict_src():
    return _read(HVAC_PREDICT_PY)


@pytest.fixture(scope="module")
def zones_src():
    return _read(HVAC_ZONES_PY)


@pytest.fixture(scope="module")
def const_src():
    return _read(CONST_PY)


@pytest.fixture(scope="module")
def hvac_const_src():
    return _read(HVAC_CONST_PY)


@pytest.fixture(scope="module")
def switch_src():
    return _read(SWITCH_PY)


@pytest.fixture(scope="module")
def number_src():
    return _read(NUMBER_PY)


@pytest.fixture(scope="module")
def config_flow_src():
    return _read(CONFIG_FLOW_PY)


@pytest.fixture(scope="module")
def sensor_src():
    return _read(os.path.join(ROOT_REL, "sensor.py"))


@pytest.fixture(scope="module")
def binary_sensor_src():
    return _read(os.path.join(ROOT_REL, "binary_sensor.py"))


def test_v478_is_egress_flag_default_true_when_absent(const_src):
    assert 'CONF_IS_EGRESS_WINDOW: Final = "is_egress_window"' in const_src
    assert "DEFAULT_IS_EGRESS_WINDOW: Final = True" in const_src


def test_v478_is_egress_flag_roundtrip_through_options_flow(config_flow_src):
    assert config_flow_src.count("CONF_IS_EGRESS_WINDOW") >= 3


def test_v478_egress_switch_default_on_after_first_install(switch_src):
    assert "class HVACEgressWindowPauseSwitch" in switch_src
    assert "return True  # default on" in switch_src
    assert "hvac_egress_window_pause" in switch_src


def test_v478_egress_switch_restore_off_survives_restart(switch_src):
    assert "SIGNAL_HVAC_COORDINATOR_READY" in switch_src
    assert "_handle_hvac_ready" in switch_src
    tree = ast.parse(switch_src)
    found = any(
        isinstance(n, ast.FunctionDef) and n.name == "_handle_hvac_ready"
        for n in ast.walk(tree)
    )
    assert found


def test_v478_egress_threshold_number_safe_unsub_no_double_call(number_src):
    assert "class HVACEgressPauseThresholdNumber" in number_src
    assert "def _safe_unsub() -> None:" in number_src
    assert "if unsubbed[0]:" in number_src


def test_v478_egress_resume_delay_number_safe_unsub_no_double_call(number_src):
    assert "class HVACEgressResumeDelayNumber" in number_src
    assert number_src.count("_safe_unsub") >= 2


def test_v478_hvac_egress_pause_skipped_in_apply_house_state_presets(hvac_src):
    assert "if self._egress_manager.is_paused(zone_id):" in hvac_src


def test_v478_paused_zone_skipped_in_ac_reset_check(override_src):
    assert "self._egress_manager" in override_src
    assert "is_paused(zone_id)" in override_src


def test_v478_paused_zone_skipped_in_predictor_apply(predict_src):
    """v4.7.8 fix-up C-L6: original test name was misleading — this checks
    the HVACPredictor pre-cool / pre-heat paths, NOT the DPM apply in
    hvac.py. DPM apply has its own dedicated test below
    (`test_v478_paused_zone_skipped_in_dpm_apply`).
    """
    assert "def set_egress_manager(self, egress_manager)" in predict_src
    assert predict_src.count("self._egress_manager.is_paused(zone.zone_id)") >= 2


def test_v478_paused_zone_skipped_in_dpm_apply(hvac_src):
    """v4.7.8 fix-up C-H1 (plan §D8 spec gap).

    `_async_apply_preset_overrides` in hvac.py iterates zones at the
    OverrideEngine apply site and dispatches `climate.set_temperature`.
    Without an `is_paused` guard, Ecobee thermostats re-engage mode on
    `set_temperature` after an explicit `off`, silently defeating the
    egress pause. Verify the guard is inside the per-zone loop and BEFORE
    the actual service-call dispatch (not the docstring mention).
    """
    apply_start = hvac_src.find("async def _async_apply_preset_overrides")
    assert apply_start >= 0
    # Find the next top-level `async def` to bound the body.
    apply_end = hvac_src.find("\n    async def ", apply_start + 1)
    apply_body = hvac_src[apply_start:apply_end if apply_end > 0 else len(hvac_src)]
    # Guard is present.
    assert "is_paused(zone_id)" in apply_body, \
        "DPM apply must skip egress-paused zones (Ecobee re-engages on " \
        "set_temperature)"
    # Guard appears BEFORE the services.async_call dispatch (the actual
    # service call, not the docstring mention of set_temperature).
    guard_idx = apply_body.find("is_paused(zone_id)")
    dispatch_idx = apply_body.find('"set_temperature"')
    assert guard_idx < dispatch_idx, \
        "is_paused guard must precede set_temperature dispatch in DPM apply"


def test_v478_force_charge_button_unaffected_by_egress_pause():
    src = _read(os.path.join(ROOT_REL, "button.py"))
    egress_refs = [line for line in src.splitlines()
                   if "egress" in line.lower() and not line.lstrip().startswith("#")]
    assert egress_refs == []


def test_v478_fan_and_cover_control_unaffected_by_egress_pause(hvac_src):
    assert "fan_controller.set_egress_manager" not in hvac_src
    assert "cover_controller.set_egress_manager" not in hvac_src


def test_v478_sensors_read_from_in_memory_not_db(sensor_src):
    for cls_name in ("HVACZoneEgressStateSensor", "HVACEgressPausedZonesSensor"):
        idx = sensor_src.find(f"class {cls_name}")
        assert idx >= 0
        body = sensor_src[idx:idx + 3500]
        assert "save_egress_state" not in body
        assert "_db_read" not in body


def test_v478_room_egress_binary_sensor_off_when_is_egress_false(binary_sensor_src):
    idx = binary_sensor_src.find("class RoomEgressWindowOpenSensor")
    assert idx >= 0
    body = binary_sensor_src[idx:idx + 4500]
    assert "if not self._is_egress:" in body
    assert "return False" in body


def test_v478_room_condition_lazy_default(zones_src):
    assert "CONF_IS_EGRESS_WINDOW" in zones_src
    assert "DEFAULT_IS_EGRESS_WINDOW" in zones_src


def test_v478_hvac_const_egress_block_present(hvac_const_src):
    for name in (
        "CONF_HVAC_EGRESS_PAUSE_ENABLED",
        "DEFAULT_HVAC_EGRESS_PAUSE_ENABLED",
        "CONF_HVAC_EGRESS_THRESHOLD_MIN",
        "DEFAULT_HVAC_EGRESS_THRESHOLD_MIN",
        "CONF_HVAC_EGRESS_RESUME_DELAY_MIN",
        "DEFAULT_HVAC_EGRESS_RESUME_DELAY_MIN",
        "HVAC_EGRESS_MANUAL_OVERRIDE_GRACE_S",
        "HVAC_EGRESS_MANUAL_COOLDOWN_S",
        "EGRESS_STATE_IDLE",
        "EGRESS_STATE_COUNTING",
        "EGRESS_STATE_PAUSED",
        "EGRESS_STATE_RESUME_COUNTDOWN",
        "EGRESS_STATE_COOLDOWN",
        "EGRESS_NM_EVENT_PAUSED",
        "EGRESS_NM_EVENT_RESUMED",
    ):
        assert name in hvac_const_src, f"missing {name}"


def test_v478_egress_manager_no_async_create_task(egress_src):
    # Allow `async_create_task` to appear in the module docstring as a
    # bug-class reference; forbid any actual code site.
    code_lines = []
    in_docstring = False
    for ln in egress_src.splitlines():
        stripped = ln.strip()
        if stripped.startswith('"""'):
            in_docstring = not in_docstring
            if stripped.count('"""') >= 2:
                in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        if "async_create_task" in ln:
            code_lines.append(ln)
    assert code_lines == [], f"unexpected async_create_task in code: {code_lines}"


def test_v478_egress_manager_uses_parse_datetime_not_fromisoformat(egress_src):
    # Only count fromisoformat in real code (not docstring text).
    code_lines = []
    in_docstring = False
    for ln in egress_src.splitlines():
        stripped = ln.strip()
        # Tracking docstring state is approximate; the only fromisoformat in this
        # file (if any) appears in the module docstring's bug-class list.
        if stripped.startswith('"""'):
            in_docstring = not in_docstring
            # Single-line triple-quote toggles back same line.
            if stripped.count('"""') >= 2:
                in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        if "fromisoformat" in ln:
            code_lines.append(ln)
    assert code_lines == [], f"unexpected fromisoformat code uses: {code_lines}"
    assert "dt_util.parse_datetime" in egress_src


def test_v478_nm_dispatch_gated_at_call_site(egress_src):
    # Find the DEFINITION of _maybe_dispatch_nm (not its call site).
    idx = egress_src.find("async def _maybe_dispatch_nm")
    assert idx >= 0
    body = egress_src[idx:idx + 2500]
    assert "_observation_mode" in body


# ===========================================================================
# v4.7.8 fix-up regression tests (Tier 2-DB review burn-down).
# Each test maps to a specific finding from the 3 parallel reviews.
# ===========================================================================


def test_v478_fixup_A_H1_room_condition_captured_without_coordinator(zones_src):
    """A-H1 (Bug Class #43): ZoneManager.update_room_conditions must STILL
    append a RoomCondition for a room whose coordinator hasn't booted yet,
    so EgressManager sees the egress window state on the first tick
    post-restart. The append path must use entry meta (window_sensor +
    is_egress_window) even when coordinator is None.
    """
    # Source-grep: the coordinator-None branch contains a RoomCondition
    # append (not just `continue`).
    upd_start = zones_src.find("def update_room_conditions")
    assert upd_start >= 0
    upd_end = zones_src.find("\n    def ", upd_start + 1)
    body = zones_src[upd_start:upd_end if upd_end > 0 else len(zones_src)]
    # The None branch now appends, not just continues.
    none_branch_idx = body.find("if coordinator is None:")
    assert none_branch_idx >= 0
    none_branch_body = body[none_branch_idx:none_branch_idx + 1500]
    assert "zone.room_conditions.append" in none_branch_body, \
        "coordinator-None branch must still append a RoomCondition with " \
        "window state (A-H1 Bug Class #43)"
    assert "is_egress_window" in none_branch_body


def test_v478_fixup_A_H2_startup_audit_skips_paused_zones(override_src):
    """A-H2 (Bug Class #33): async_startup_audit + async_startup_ramp_audit
    must add is_paused guards. Otherwise the post-restart first-tick can
    dispatch climate services against egress-paused zones.
    """
    # async_startup_audit: per-zone loop has the guard.
    audit_start = override_src.find("async def async_startup_audit")
    assert audit_start >= 0
    audit_end = override_src.find("\n    async def ", audit_start + 1)
    audit_body = override_src[audit_start:audit_end if audit_end > 0 else len(override_src)]
    assert "self._egress_manager is not None" in audit_body and \
        "is_paused(zone.zone_id)" in audit_body, \
        "async_startup_audit must skip egress-paused zones (A-H2)"

    # async_startup_ramp_audit: per-row loop has the guard on zone_id.
    ramp_start = override_src.find("async def async_startup_ramp_audit")
    assert ramp_start >= 0
    ramp_end = override_src.find("\n    async def ", ramp_start + 1)
    ramp_body = override_src[ramp_start:ramp_end if ramp_end > 0 else len(override_src)]
    assert "self._egress_manager is not None" in ramp_body and \
        "is_paused(zone_id)" in ramp_body, \
        "async_startup_ramp_audit must skip egress-paused zones (A-H2)"


def test_v478_fixup_B_H1_prune_wired_into_both_cleanup_lists():
    """B-H1 / C-H2 (Bug Class #27): prune_stale_egress_state must be wired
    into BOTH _cleanup_ops lists in __init__.py — primary maintenance path
    AND deferred maintenance path. Without this, the DAO is dead code and
    rows for removed zones / interrupted transitions leak.
    """
    src = _read(os.path.join(ROOT_REL, "__init__.py"))
    # Count must be >= 2 (one per list). Source has the string twice if
    # both are wired.
    n = src.count('"prune_stale_egress_state"')
    assert n >= 2, (
        f"prune_stale_egress_state appears {n} time(s); must be in BOTH "
        f"_cleanup_ops and _cleanup_ops_d lists"
    )


def test_v478_fixup_B_H2_initial_restore_gate_blocks_first_tick():
    """B-H2 (Bug Class #14 / lifecycle): the RestoreEntity Numbers don't
    push their saved value to EgressManager until async_added_to_hass
    completes. The initial decision cycle in HVACCoordinator.async_setup
    runs concurrently — so the first egress tick must early-return until
    deferred restores have landed.

    Verify the gate set is populated on construction and async_tick
    early-returns while it's non-empty.
    """
    import asyncio
    mod = _load_egress_module()
    # Fresh manager (do NOT call _make_em — it auto-releases the gate).
    nm_calls: list = []
    hass = _FakeHass(nm_calls)
    zm = _FakeZoneManager({})
    db = _FakeDB()
    em = mod.EgressManager(
        hass, zm, db=db, threshold_min=3, resume_delay_min=1, enabled=True,
    )
    assert em.initial_restore_pending is True, \
        "fresh EgressManager must gate first tick until restores land"
    em._rehydrate_done = True
    # Tick early-returns even with rehydrate done if restore pending.
    asyncio.get_event_loop().run_until_complete(em.async_tick(_now_at(0)))
    # No DB writes happened.
    assert db.calls == [], \
        f"tick acted while restore pending: {db.calls}"


def test_v478_fixup_B_H2_setters_clear_individual_restore_bits():
    """B-H2: each setter (enabled, set_threshold_min, set_resume_delay_min)
    must clear its own bit so the gate releases when ALL deferred restores
    have landed.
    """
    mod = _load_egress_module()
    nm_calls: list = []
    hass = _FakeHass(nm_calls)
    em = mod.EgressManager(
        hass, _FakeZoneManager({}), db=_FakeDB(),
        threshold_min=3, resume_delay_min=1, enabled=True,
    )
    pending = em._initial_restore_pending
    assert pending == {"enabled", "threshold_min", "resume_delay_min"}
    em.enabled = True  # setter; landed.
    assert "enabled" not in em._initial_restore_pending
    em.set_threshold_min(5)
    assert "threshold_min" not in em._initial_restore_pending
    em.set_resume_delay_min(2)
    assert em._initial_restore_pending == set()
    assert em.initial_restore_pending is False


def test_v478_fixup_B_H2_force_release_clears_gate():
    """B-H2: bounded fallback — force_release_initial_restore_gate must
    clear the pending set (called from a 60s timer in HVACCoordinator).
    """
    mod = _load_egress_module()
    nm_calls: list = []
    hass = _FakeHass(nm_calls)
    em = mod.EgressManager(
        hass, _FakeZoneManager({}), db=_FakeDB(),
        threshold_min=3, resume_delay_min=1, enabled=True,
    )
    em.force_release_initial_restore_gate()
    assert em.initial_restore_pending is False


def test_v478_fixup_B_H3_master_switch_clears_gate_on_no_saved_state(switch_src):
    """B-H3 (Bug Class #5): the switch's fresh-install path (no saved
    last_state) must also clear the gate so the next tick can proceed.
    """
    # Source-grep: the early-return branch discards the "enabled" bit.
    cls_start = switch_src.find("class HVACEgressWindowPauseSwitch")
    assert cls_start >= 0
    body = switch_src[cls_start:cls_start + 4500]
    # The fresh-install branch (last_state is None) calls discard("enabled").
    assert 'discard(\n                        "enabled"\n                    )' in body \
        or '_initial_restore_pending.discard("enabled")' in body, \
        "fresh-install branch must discard `enabled` bit so gate releases"


def test_v478_fixup_C_H1_DPM_apply_guards_egress_paused_zones(hvac_src):
    """C-H1 (plan §D8 spec gap): _async_apply_preset_overrides must skip
    egress-paused zones BEFORE the set_temperature dispatch. Ecobee
    re-engages mode on set_temperature after off, defeating the pause.

    This test is the dedicated regression for the DPM apply path
    (separate from test_v478_paused_zone_skipped_in_predictor_apply
    which validates HVACPredictor pre-cool / pre-heat).
    """
    apply_start = hvac_src.find("async def _async_apply_preset_overrides")
    assert apply_start >= 0
    apply_end = hvac_src.find("\n    async def ", apply_start + 1)
    body = hvac_src[apply_start:apply_end if apply_end > 0 else len(hvac_src)]
    # Guard appears before the actual service-call dispatch (the quoted
    # service name in services.async_call), not the docstring mention.
    g = body.find("is_paused(zone_id)")
    d = body.find('"set_temperature"')
    assert g >= 0 and d >= 0 and g < d, \
        "DPM apply guard must precede set_temperature dispatch (C-H1)"


def test_v478_fixup_C_H3_strings_json_has_egress_translations():
    """C-H3: strings.json must have helper text for `is_egress_window` in
    BOTH config-flow steps (install + reconfigure) AND entity translation
    entries for the new switch/numbers/sensors. Zero entries means the
    config-flow checkbox displays the raw schema key.
    """
    import json
    with open(os.path.join(ROOT_REL, "strings.json"), encoding="utf-8") as f:
        s = json.load(f)
    # Pretty-printed JSON content for source-grep.
    blob = json.dumps(s)
    # Per-room CONF helper text (BOTH install + reconfigure carry the key).
    assert blob.count('"is_egress_window"') >= 2, \
        "is_egress_window must appear in both install + reconfigure sensors steps"
    # Entity translations for the new entities.
    assert "hvac_egress_window_pause" in blob
    assert "hvac_egress_threshold_min" in blob
    assert "hvac_egress_resume_delay_min" in blob
    assert "egress_window_open" in blob
    assert "hvac_zone_egress_state" in blob
    assert "hvac_egress_paused_zones" in blob


def test_v478_fixup_C_H3_en_json_has_egress_translations():
    """C-H3: en.json mirrors strings.json. JSON validity preserved."""
    import json
    with open(os.path.join(ROOT_REL, "translations/en.json"), encoding="utf-8") as f:
        s = json.load(f)
    blob = json.dumps(s)
    assert blob.count('"is_egress_window"') >= 2
    assert "hvac_egress_window_pause" in blob
    assert "hvac_egress_threshold_min" in blob
    assert "hvac_egress_resume_delay_min" in blob
    assert "egress_window_open" in blob
    assert "hvac_zone_egress_state" in blob
    assert "hvac_egress_paused_zones" in blob


def test_v478_fixup_C_M1_egress_pause_frequency_in_suppressed_set(hvac_const_src):
    """C-M1 (v4.6.3.1 P2 doctrine): silent metrics must be explicitly
    listed in HVAC_SUPPRESSED_FROM_PERSISTENCE rather than absent.
    egress_pause_frequency is not yet wired — must be in the suppressed
    set so the parametric meta-test won't fail when we DO wire it.
    """
    # Find HVAC_SUPPRESSED_FROM_PERSISTENCE block.
    idx = hvac_const_src.find("HVAC_SUPPRESSED_FROM_PERSISTENCE")
    assert idx >= 0
    block = hvac_const_src[idx:idx + 600]
    assert '"egress_pause_frequency"' in block, \
        "egress_pause_frequency must be in HVAC_SUPPRESSED_FROM_PERSISTENCE " \
        "per v4.6.3.1 P2 doctrine"


def test_v478_fixup_C_M2_room_egress_inherits_universal_room_entity(binary_sensor_src):
    """C-M2: RoomEgressWindowOpenSensor must inherit from UniversalRoomEntity
    for consistent device_info + name-prefixing.
    """
    idx = binary_sensor_src.find("class RoomEgressWindowOpenSensor")
    assert idx >= 0
    cls_line = binary_sensor_src[idx:binary_sensor_src.find(":", idx) + 1]
    assert "UniversalRoomEntity" in cls_line, \
        "RoomEgressWindowOpenSensor must inherit UniversalRoomEntity (C-M2)"


def test_v478_fixup_C_M3_zone_enumeration_failure_is_warning(binary_sensor_src):
    """C-M3: silent debug-level swallow of zone-enumeration failures must
    be promoted to WARNING so silent failures during initial install
    surface in normal logs.
    """
    idx = binary_sensor_src.find("canonical zone enumeration for egress sensors failed")
    assert idx >= 0
    # Walk backwards to find the _LOGGER call.
    log_start = binary_sensor_src.rfind("_LOGGER.", 0, idx)
    assert log_start >= 0
    call_line = binary_sensor_src[log_start:idx + 20]
    assert "_LOGGER.warning" in call_line, \
        "zone-enumeration failure must be WARNING, not DEBUG (C-M3)"


def test_v478_fixup_C_L4_room_without_window_sensor_not_egress(zones_src):
    """C-L4: rooms with no window_sensor must NOT get is_egress_window=True
    in their RoomCondition meta. Cosmetic, but prevents config-flow surface
    confusion.
    """
    # update_room_conditions builds room_entry_meta; verify the and-clause.
    upd_start = zones_src.find("def update_room_conditions")
    assert upd_start >= 0
    upd_end = zones_src.find("\n    def ", upd_start + 1)
    body = zones_src[upd_start:upd_end if upd_end > 0 else len(zones_src)]
    # Look for the gating `and bool(_ws)` or equivalent.
    assert "and bool(_ws)" in body or \
        "bool(_ws)" in body and "is_egress_window" in body, \
        "is_egress default must be gated on window_sensor presence (C-L4)"


def test_v478_fixup_B_M1_zones_uses_dt_util_now_not_utcnow(zones_src):
    """B-M1 (Bug Class #11): unify on dt_util.now() — cross-module split
    with EgressManager (which uses dt_util.now()) is fragile.

    Verify update_room_conditions uses dt_util.now() (not utcnow) for the
    `now` variable used in occupancy-time bookkeeping.
    """
    upd_start = zones_src.find("def update_room_conditions")
    assert upd_start >= 0
    upd_end = zones_src.find("\n    def ", upd_start + 1)
    body = zones_src[upd_start:upd_end if upd_end > 0 else len(zones_src)]
    # The `now =` assignment uses dt_util.now() (not utcnow).
    assert "now = dt_util.now()" in body, \
        "update_room_conditions must use dt_util.now() for tz-aware consistency"


def test_v478_fixup_A_M6_db_helpers_consolidated(egress_src):
    """A-M6: 5 near-identical _db_save_* helpers consolidated into one
    `_db_save` core method. Verify the consolidation happened.
    """
    # The new core helper exists.
    assert "async def _db_save(self, zone_id: str, state: str, **fields)" in egress_src
    # The thin wrappers still exist (callers unchanged) but bodies are tiny.
    for w in (
        "_db_save_counting", "_db_save_paused_full", "_db_save_paused",
        "_db_save_resume_countdown", "_db_save_cooldown",
    ):
        assert f"async def {w}" in egress_src


@pytest.mark.asyncio
async def test_v478_fixup_A_LOW_triggered_by_room_rolls_forward():
    """A-LOW: when first-trigger room closes but a sibling is still open,
    triggered_by_room rolls forward in memory. Sensors / paused_zones() now
    surface the current trigger, not the historical first.
    """
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("room_a"), _rc_closed("room_b")]
    em, hass, _, _, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool", {"preset_mode": "home"})
    t0 = _now_at(0)
    await em.async_tick(t0)
    await em.async_tick(t0 + timedelta(minutes=4))
    assert em.is_paused("zone_2")
    info = em.get_zone_info("zone_2")
    assert info["triggered_by_room"] == "room_a"
    # Pause dispatched climate.set_hvac_mode: off — reflect that in HA
    # state so the manual-override branch doesn't kick in on the next tick.
    hass.set_state("climate.up_hallway_zone_2", "off", {"preset_mode": "home"})
    # Now room_a closes, room_b opens. Tick again — keep paused (window still open).
    z.room_conditions = [_rc_closed("room_a"), _rc_open("room_b")]
    await em.async_tick(t0 + timedelta(minutes=5))
    info = em.get_zone_info("zone_2")
    assert info["triggered_by_room"] == "room_b", \
        "triggered_by_room must roll forward when sibling becomes the trigger"


@pytest.mark.asyncio
async def test_v478_fixup_C_L3_disabled_path_clears_db_counting_row():
    """C-L3 / A-LOW-2: when feature is disabled mid-count, the disabled
    branch must also clear the DB row so it doesn't survive restart.
    """
    z = _FakeZoneState("zone_2", "Upstairs", "climate.up_hallway_zone_2")
    z.room_conditions = [_rc_open("jaya_bedroom")]
    em, hass, _, db, _ = _make_em(zones={"zone_2": z}, threshold_min=3)
    em._rehydrate_done = True
    hass.set_state("climate.up_hallway_zone_2", "heat_cool")
    t0 = _now_at(0)
    # First tick — start counting (writes DB counting row).
    await em.async_tick(t0)
    assert "zone_2" in db.rows
    assert db.rows["zone_2"]["state"] == "counting"
    # Disable mid-count.
    em.enabled = False
    await em.async_tick(t0 + timedelta(seconds=30))
    # Counter cleared in memory AND DB cleared.
    assert "zone_2" not in em._egress_first_open_at
    assert "zone_2" not in db.rows, "DB row must be cleared on disable mid-count"


def test_v478_fixup_B5_engage_pause_uses_none_sentinel_for_missing_preset(egress_src):
    """B-M5: distinguish "preset attribute missing" (None) from "preset
    explicitly empty" — typed annotation + isinstance check now in place.
    """
    pause_start = egress_src.find("async def _engage_pause")
    assert pause_start >= 0
    pause_end = egress_src.find("\n    async def ", pause_start + 1)
    body = egress_src[pause_start:pause_end if pause_end > 0 else len(egress_src)]
    # The sentinel-aware logic uses isinstance check.
    assert "isinstance(_pm, str)" in body or "prior_preset: str | None" in body, \
        "prior_preset must distinguish missing vs empty (B-M5)"


def test_v478_fixup_A_MED4_engage_resume_logs_warn_on_empty_saved_mode(egress_src):
    """A-MED-4: WARN log on silent clear in _engage_resume when saved_mode
    is empty. The next decision tick will catch the off zone, but
    visibility matters.
    """
    resume_start = egress_src.find("async def _engage_resume")
    assert resume_start >= 0
    resume_end = egress_src.find("\n    async def ", resume_start + 1)
    body = egress_src[resume_start:resume_end if resume_end > 0 else len(egress_src)]
    # WARN log present + references the resume-abort case.
    assert "_LOGGER.warning" in body, \
        "_engage_resume must WARN-log on empty saved_mode silent clear"


def test_v478_fixup_B10_db_save_state_change_warns_on_failure(egress_src):
    """B10: state-change DB write failures (paused / resume_countdown /
    cooldown) must promote to WARNING. Routine counting writes stay DEBUG.

    Verify the consolidated _db_save helper branches on state for log
    severity.
    """
    save_start = egress_src.find("async def _db_save(self, zone_id")
    assert save_start >= 0
    save_end = egress_src.find("\n    async def ", save_start + 1)
    body = egress_src[save_start:save_end if save_end > 0 else len(egress_src)]
    assert "_LOGGER.warning" in body, \
        "_db_save must escalate to WARNING for state-change writes (B10)"
    assert "_LOGGER.debug" in body, \
        "_db_save must keep DEBUG for routine counting writes (B10)"

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


def test_v478_paused_zone_skipped_in_dpm_apply(predict_src):
    assert "def set_egress_manager(self, egress_manager)" in predict_src
    assert predict_src.count("self._egress_manager.is_paused(zone.zone_id)") >= 2


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

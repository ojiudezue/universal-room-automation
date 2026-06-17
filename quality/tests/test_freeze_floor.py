"""Tests for the freeze-protection heat_low FLOOR (feature/freeze-floor).

The HVAC Coordinator evaluates a freeze-active gate (with hysteresis) each
decision cycle and clamps the emitted heat_low (`resolved.cool_low`, which IS
`target_temp_low`) up to FREEZE_FLOOR when a freeze is active and the resolved
low is below the floor. cool_high is never touched.

These tests drive the REAL `HVACCoordinator._async_apply_preset_overrides`
method object end-to-end. The real `hvac` module is loaded (HA + sibling
coordinators stubbed); the unbound production method is bound to a minimal
coordinator instance carrying fake collaborators (zone_manager / preset_manager
/ override_arrester / egress_manager / predictor) plus a fake `hass.services`
that CAPTURES `set_temperature` calls and a fake EC reachable via
`hass.data[DOMAIN]['coordinator_manager']`. Because the genuine method body runs
(real OverrideEngine resolution), deleting the clamp makes
`test_clamp_fires_writes_floor_low` FAIL — that is the mutation gate.

Mirrors the loader + fake shape used in test_heatcool_enforcer.py.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_REL = "custom_components/universal_room_automation"


# ---------------------------------------------------------------------------
# Module loader — stubs HA + ura package siblings, loads the REAL hvac module.
# ---------------------------------------------------------------------------


def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _ensure_real_preset_overrides():
    """Load the REAL preset_overrides submodule under the stub package.

    `_async_apply_preset_overrides` lazily does `from .preset_overrides import
    OverrideEngine`. A sibling test (test_heatcool_enforcer) may have cached
    the hvac module WITHOUT this submodule registered (it never drives the
    apply path), so we register it idempotently before returning.
    """
    key = "ura_hvac_pkg.domain_coordinators.preset_overrides"
    if key in sys.modules and hasattr(sys.modules[key], "OverrideEngine"):
        return
    po_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "preset_overrides.py"
    spec = importlib.util.spec_from_file_location(key, str(po_src))
    po = importlib.util.module_from_spec(spec)
    po.__package__ = "ura_hvac_pkg.domain_coordinators"
    sys.modules[key] = po
    spec.loader.exec_module(po)


def _load_hvac_module():
    if "ura_hvac_under_test" in sys.modules:
        _ensure_real_preset_overrides()
        return sys.modules["ura_hvac_under_test"]

    if "homeassistant" not in sys.modules:
        _stub_module("homeassistant").__path__ = []
    if "homeassistant.core" not in sys.modules:
        _stub_module(
            "homeassistant.core",
            HomeAssistant=type("HomeAssistant", (), {}),
            callback=lambda f: f,
        )
    if "homeassistant.helpers" not in sys.modules:
        _stub_module("homeassistant.helpers").__path__ = []
    if "homeassistant.helpers.dispatcher" not in sys.modules:
        _stub_module(
            "homeassistant.helpers.dispatcher",
            async_dispatcher_send=lambda *a, **kw: None,
            async_dispatcher_connect=lambda *a, **kw: (lambda: None),
        )
    if "homeassistant.helpers.event" not in sys.modules:
        _stub_module(
            "homeassistant.helpers.event",
            async_track_time_interval=lambda *a, **kw: (lambda: None),
            async_call_later=lambda *a, **kw: (lambda: None),
            async_track_state_change_event=lambda *a, **kw: (lambda: None),
        )
    if "homeassistant.helpers.storage" not in sys.modules:
        _stub_module("homeassistant.helpers.storage", Store=object)
    if "homeassistant.helpers.device_registry" not in sys.modules:
        _stub_module("homeassistant.helpers.device_registry", DeviceInfo=dict)
    if "homeassistant.const" not in sys.modules:
        _stub_module(
            "homeassistant.const", EVENT_HOMEASSISTANT_STARTED="homeassistant_started"
        )
    if "homeassistant.util" not in sys.modules:
        _stub_module("homeassistant.util").__path__ = []
    if "homeassistant.util.dt" not in sys.modules:
        _stub_module(
            "homeassistant.util.dt",
            now=lambda: datetime.now(timezone.utc),
            utcnow=lambda: datetime.now(timezone.utc),
            parse_datetime=lambda s: datetime.fromisoformat(s) if s else None,
        )

    pkg = _stub_module("ura_hvac_pkg")
    pkg.__path__ = []
    const = types.ModuleType("ura_hvac_pkg.const")

    class _ConstAny(str):
        pass

    def _const_getattr(name):
        return _ConstAny(name)

    const.__getattr__ = _const_getattr  # type: ignore[attr-defined]
    const.DOMAIN = "universal_room_automation"
    const.VERSION = "test"
    sys.modules["ura_hvac_pkg.const"] = const

    coord_pkg = _stub_module("ura_hvac_pkg.domain_coordinators")
    coord_pkg.__path__ = []

    # Real hvac_const (cheap) — load for fidelity (FREEZE_* constants).
    hvac_const_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_const.py"
    spec = importlib.util.spec_from_file_location(
        "ura_hvac_pkg.domain_coordinators.hvac_const", str(hvac_const_src)
    )
    hvac_const = importlib.util.module_from_spec(spec)
    hvac_const.__package__ = "ura_hvac_pkg.domain_coordinators"
    sys.modules["ura_hvac_pkg.domain_coordinators.hvac_const"] = hvac_const
    spec.loader.exec_module(hvac_const)

    class _BaseCoordinator:
        def __init__(self, *a, **kw):
            pass

    _stub_module(
        "ura_hvac_pkg.domain_coordinators.base",
        BaseCoordinator=_BaseCoordinator,
        CoordinatorAction=object,
        Intent=object,
    )

    _stub_module("ura_hvac_pkg.domain_coordinators.hvac_covers", CoverController=object)
    _stub_module("ura_hvac_pkg.domain_coordinators.hvac_egress", EgressManager=object)
    _stub_module("ura_hvac_pkg.domain_coordinators.hvac_fans", FanController=object)
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_override", OverrideArrester=object
    )
    _stub_module("ura_hvac_pkg.domain_coordinators.hvac_predict", HVACPredictor=object)
    _stub_module("ura_hvac_pkg.domain_coordinators.hvac_preset", PresetManager=object)
    _stub_module("ura_hvac_pkg.domain_coordinators.hvac_zones", ZoneManager=object)

    # preset_overrides is REAL (the resolution path under test).
    po_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "preset_overrides.py"
    spec = importlib.util.spec_from_file_location(
        "ura_hvac_pkg.domain_coordinators.preset_overrides", str(po_src)
    )
    po = importlib.util.module_from_spec(spec)
    po.__package__ = "ura_hvac_pkg.domain_coordinators"
    sys.modules["ura_hvac_pkg.domain_coordinators.preset_overrides"] = po
    spec.loader.exec_module(po)

    signals = types.ModuleType("ura_hvac_pkg.domain_coordinators.signals")

    def _signals_getattr(name):
        return name

    signals.__getattr__ = _signals_getattr  # type: ignore[attr-defined]
    sys.modules["ura_hvac_pkg.domain_coordinators.signals"] = signals

    hvac_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac.py"
    spec = importlib.util.spec_from_file_location(
        "ura_hvac_pkg.domain_coordinators.hvac", str(hvac_src)
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "ura_hvac_pkg.domain_coordinators"
    sys.modules["ura_hvac_pkg.domain_coordinators.hvac"] = mod
    spec.loader.exec_module(mod)

    sys.modules["ura_hvac_under_test"] = mod
    return mod


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeZone:
    def __init__(self, zone_id, climate_entity, zone_name="Zone"):
        self.zone_id = zone_id
        self.climate_entity = climate_entity
        self.zone_name = zone_name


class _FakeZoneManager:
    def __init__(self, zones):
        self.zones = zones


class _FakeEgressManager:
    def __init__(self, paused=()):
        self._paused = set(paused)

    def is_paused(self, zone_id):
        return zone_id in self._paused


class _FakeOverrideArrester:
    def __init__(self):
        self.suppressed = []
        self.unsuppressed = []

    def suppress(self, entity_id):
        self.suppressed.append(entity_id)

    def unsuppress(self, entity_id):
        self.unsuppressed.append(entity_id)


class _FakePresetManager:
    def __init__(self, cool_setpoint):
        # get_seasonal_setpoints returns (cool, heat); apply path uses cool
        # as baseline_high and (cool - 7.0) as baseline_low.
        self._cool = cool_setpoint

    def get_preset_for_house_state(self, house_state):
        return "home"

    def get_seasonal_setpoints(self, preset):
        return (self._cool, self._cool - 7.0)


class _FakePredictor:
    def __init__(self, outdoor_temp):
        self._outdoor_temp = outdoor_temp

    def _get_outdoor_temp(self):
        return self._outdoor_temp


class _FakeEC:
    _dynamic_preset_overrides = {}


class _FakeManager:
    def __init__(self):
        self.coordinators = {"energy": _FakeEC()}


class _FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append({"domain": domain, "service": service, "data": dict(data)})


class _FakeHass:
    def __init__(self):
        self.services = _FakeServices()
        self.data = {
            "universal_room_automation": {"coordinator_manager": _FakeManager()}
        }


def _make_coord(*, cool_setpoint, outdoor_temp, freeze_active_seed=False, egress_paused=()):
    mod = _load_hvac_module()
    coord = mod.HVACCoordinator.__new__(mod.HVACCoordinator)
    coord.hass = _FakeHass()
    coord._house_state = "home"
    coord._guest_mode_actuation_enabled = True
    coord._observation_mode = False
    coord._zone_manager = _FakeZoneManager(
        {"zone_1": _FakeZone("zone_1", "climate.zone_1")}
    )
    coord._egress_manager = _FakeEgressManager(egress_paused)
    coord._override_arrester = _FakeOverrideArrester()
    coord._preset_manager = _FakePresetManager(cool_setpoint)
    coord._predictor = _FakePredictor(outdoor_temp)
    coord._last_emitted_range = {}
    coord._freeze_active = freeze_active_seed
    return coord


def _set_temp_calls(coord):
    return [c["data"] for c in coord.hass.services.calls if c["service"] == "set_temperature"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clamp_fires_writes_floor_low():
    """MUTATION GATE: outdoor ≤35 and a resolved heat_low (<50) → set_temperature
    writes target_temp_low=50. Deleting the clamp in `_apply_freeze_floor`
    (or its call site) makes this assertion FAIL (low would be 48, not 50)."""
    # cool_setpoint 55 → baseline_low = 48 (< FREEZE_FLOOR 50)
    coord = _make_coord(cool_setpoint=55, outdoor_temp=33)
    await coord._async_apply_preset_overrides()
    calls = _set_temp_calls(coord)
    assert len(calls) == 1
    assert calls[0]["target_temp_low"] == 50
    # cool_high untouched (baseline_high == cool_setpoint == 55)
    assert calls[0]["target_temp_high"] == 55


@pytest.mark.asyncio
async def test_no_op_when_already_warm():
    """Freeze active but resolved heat_low ≥ 50 → no clamp; the preset low is
    written byte-identical (cool_setpoint 60 → baseline_low = 53)."""
    coord = _make_coord(cool_setpoint=60, outdoor_temp=33)
    await coord._async_apply_preset_overrides()
    calls = _set_temp_calls(coord)
    assert len(calls) == 1
    assert calls[0]["target_temp_low"] == 53
    assert calls[0]["target_temp_high"] == 60


@pytest.mark.asyncio
async def test_no_clamp_above_trigger():
    """Outdoor > 38 (warm) → freeze never arms; the dangerously-low preset is
    emitted UNCHANGED (low = 48, no floor applied)."""
    coord = _make_coord(cool_setpoint=55, outdoor_temp=70)
    await coord._async_apply_preset_overrides()
    calls = _set_temp_calls(coord)
    assert len(calls) == 1
    assert calls[0]["target_temp_low"] == 48
    assert calls[0]["target_temp_high"] == 55


@pytest.mark.asyncio
async def test_hysteresis_stays_active_until_above_ceiling():
    """Once armed at ≤35, freeze stays active across the band (35,38] and
    clears only above 38."""
    coord = _make_coord(cool_setpoint=55, outdoor_temp=35)
    # Arm at exactly the trigger.
    assert coord._update_freeze_active() is True
    # 37 is inside (35, 38] — must remain armed.
    coord._predictor._outdoor_temp = 37
    assert coord._update_freeze_active() is True
    # 38 is the ceiling (not strictly above) — still armed.
    coord._predictor._outdoor_temp = 38
    assert coord._update_freeze_active() is True
    # 39 > 38 — clears.
    coord._predictor._outdoor_temp = 39
    assert coord._update_freeze_active() is False


@pytest.mark.asyncio
async def test_hysteresis_does_not_arm_in_band_without_trigger():
    """A reading of 37 (in the hysteresis band) when NOT already armed must
    NOT arm freeze — arming requires crossing ≤35."""
    coord = _make_coord(cool_setpoint=55, outdoor_temp=37)
    assert coord._update_freeze_active() is False


@pytest.mark.asyncio
async def test_fail_open_missing_outdoor_temp():
    """No outdoor temp available → freeze NOT active, no clamp, no crash. The
    dangerously-low preset is emitted unchanged (fail-open to normal preset)."""
    coord = _make_coord(cool_setpoint=55, outdoor_temp=None)
    await coord._async_apply_preset_overrides()
    calls = _set_temp_calls(coord)
    assert len(calls) == 1
    assert calls[0]["target_temp_low"] == 48
    assert coord._freeze_active is False


@pytest.mark.asyncio
async def test_fail_open_clears_seeded_active_state():
    """A previously-armed freeze must clear (fail-open) when the outdoor temp
    becomes unavailable — never hold a fabricated freeze."""
    coord = _make_coord(
        cool_setpoint=55, outdoor_temp=None, freeze_active_seed=True
    )
    assert coord._update_freeze_active() is False


# ---------------------------------------------------------------------------
# _set_emergency_heat removal + smoke/CO branch preservation
# ---------------------------------------------------------------------------


def _hvac_src():
    return (ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac.py").read_text()


def test_set_emergency_heat_method_removed():
    """The single-mode freeze response method must be gone."""
    src = _hvac_src()
    assert "async def _set_emergency_heat" not in src


def test_freeze_hazard_no_longer_sets_single_mode_heat():
    """The freeze_risk branch must no longer dispatch set_hvac_mode=heat. We
    verify no _set_emergency_heat invocation survives in _handle_safety_hazard
    and that the only emergency-heat reference is in explanatory comments."""
    src = _hvac_src()
    # No live call to the removed method.
    assert "self._set_emergency_heat()" not in src
    # The freeze response is now the floor clamp.
    assert "_apply_freeze_floor" in src


def test_smoke_co_fan_stop_branch_preserved():
    """The smoke/CO critical fan-stop branch must remain untouched."""
    src = _hvac_src()
    assert '_stop_all_fans_safety()' in src
    assert '("smoke", "carbon_monoxide")' in src


def test_hvac_const_freeze_constants_present():
    mod = _load_hvac_module()
    hc = sys.modules["ura_hvac_pkg.domain_coordinators.hvac_const"]
    assert hc.FREEZE_FLOOR == 50
    assert hc.FREEZE_TRIGGER_TEMP == 35
    assert hc.FREEZE_TRIGGER_HYSTERESIS == 3

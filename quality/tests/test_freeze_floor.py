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
import contextlib
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

    # hvac_setpoint is REAL (the chokepoint under test). It only depends on
    # hvac_const, already loaded real above.
    setpoint_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_setpoint.py"
    spec = importlib.util.spec_from_file_location(
        "ura_hvac_pkg.domain_coordinators.hvac_setpoint", str(setpoint_src)
    )
    setpoint = importlib.util.module_from_spec(spec)
    setpoint.__package__ = "ura_hvac_pkg.domain_coordinators"
    sys.modules["ura_hvac_pkg.domain_coordinators.hvac_setpoint"] = setpoint
    spec.loader.exec_module(setpoint)

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

    def suppress(self, entity_id, kind=None):
        # v5.36.2 H6: production sites now pass kind="temp" (B1 completeness).
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
    _fill_init_defaults(coord, "hvac", "HVACCoordinator")
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
    writes target_temp_low=50. Deleting the clamp in `apply_setpoint_guards`
    (or its call site) makes this assertion FAIL (low would be 48, not 50)."""
    # cool_setpoint 55 → baseline_low = 48 (< FREEZE_FLOOR 50)
    coord = _make_coord(cool_setpoint=55, outdoor_temp=33)
    # D-HIGH-1: the decision cycle refreshes freeze state UNCONDITIONALLY
    # before the apply path; mirror that call order here.
    coord._update_freeze_active()
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
    coord._update_freeze_active()
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
    coord._update_freeze_active()
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
    coord._update_freeze_active()
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
    and that the freeze response is now the setpoint chokepoint."""
    src = _hvac_src()
    # No live call to the removed method.
    assert "self._set_emergency_heat()" not in src
    # The freeze response is now enforced at the setpoint chokepoint.
    assert "emit_set_temperature" in src


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


# ---------------------------------------------------------------------------
# CHOKEPOINT — hvac_setpoint.emit_set_temperature / apply_setpoint_guards
# ---------------------------------------------------------------------------


def _setpoint_mod():
    _load_hvac_module()
    return sys.modules["ura_hvac_pkg.domain_coordinators.hvac_setpoint"]


class _CapHass:
    """Minimal hass whose services.async_call captures set_temperature data."""

    def __init__(self):
        self.calls = []

        async def _async_call(domain, service, data, blocking=False):
            self.calls.append(
                {"domain": domain, "service": service, "data": dict(data),
                 "blocking": blocking}
            )

        self.services = types.SimpleNamespace(async_call=_async_call)


def test_apply_guards_pure_floor_raises_low():
    sp = _setpoint_mod()
    low, high = sp.apply_setpoint_guards(47, 60, freeze_active=True)
    assert low == 50
    assert high == 60  # already > low + deadband


def test_apply_guards_inactive_is_identity():
    sp = _setpoint_mod()
    low, high = sp.apply_setpoint_guards(47, 49, freeze_active=False)
    assert (low, high) == (47, 49)


def test_apply_guards_deadband_fix_no_inversion():
    """A-HIGH-1: clamping low to 50 with cool_high 49 must NOT invert; high is
    pushed to low + MIN_DEADBAND (52)."""
    sp = _setpoint_mod()
    low, high = sp.apply_setpoint_guards(47, 49, freeze_active=True)
    assert low == 50
    assert high == 52
    assert high > low  # never inverted


def test_apply_guards_preserves_none_bounds():
    sp = _setpoint_mod()
    # low only
    assert sp.apply_setpoint_guards(47, None, freeze_active=True) == (50, None)
    # high only — no low to floor, deadband not enforced
    assert sp.apply_setpoint_guards(None, 49, freeze_active=True) == (None, 49)


@pytest.mark.asyncio
async def test_emit_floors_low_during_freeze():
    sp = _setpoint_mod()
    hass = _CapHass()
    await sp.emit_set_temperature(
        hass, "climate.z", target_temp_low=47, target_temp_high=60,
        freeze_active=True, blocking=True,
    )
    assert hass.calls[0]["data"]["target_temp_low"] == 50
    assert hass.calls[0]["blocking"] is True


@pytest.mark.asyncio
async def test_emit_inactive_byte_identical():
    sp = _setpoint_mod()
    hass = _CapHass()
    await sp.emit_set_temperature(
        hass, "climate.z", target_temp_low=47, target_temp_high=60,
        freeze_active=False,
    )
    assert hass.calls[0]["data"]["target_temp_low"] == 47
    assert hass.calls[0]["data"]["target_temp_high"] == 60


@pytest.mark.asyncio
async def test_emit_above_floor_unchanged():
    sp = _setpoint_mod()
    hass = _CapHass()
    await sp.emit_set_temperature(
        hass, "climate.z", target_temp_low=53, target_temp_high=60,
        freeze_active=True,
    )
    assert hass.calls[0]["data"]["target_temp_low"] == 53


@pytest.mark.asyncio
async def test_emit_deadband_never_inverts():
    sp = _setpoint_mod()
    hass = _CapHass()
    await sp.emit_set_temperature(
        hass, "climate.z", target_temp_low=47, target_temp_high=49,
        freeze_active=True,
    )
    data = hass.calls[0]["data"]
    assert data["target_temp_low"] == 50
    assert data["target_temp_high"] == 52


# ---------------------------------------------------------------------------
# PER-EMISSION-CLASS: predict (pre-heat) + override (compromise) route through
# the chokepoint and get floored during a freeze.
# ---------------------------------------------------------------------------


def _stub_recorder_deps():
    """Stub the recorder modules hvac_override imports at module load time."""
    if "homeassistant.components" not in sys.modules:
        _stub_module("homeassistant.components").__path__ = []
    if "homeassistant.components.recorder" not in sys.modules:
        _stub_module(
            "homeassistant.components.recorder",
            get_instance=lambda *a, **kw: None,
        ).__path__ = []
    if "homeassistant.components.recorder.history" not in sys.modules:
        _stub_module(
            "homeassistant.components.recorder.history",
            get_significant_states=lambda *a, **kw: {},
        )
    if "homeassistant.core" in sys.modules:
        core = sys.modules["homeassistant.core"]
        if not hasattr(core, "CALLBACK_TYPE"):
            core.CALLBACK_TYPE = object
        if not hasattr(core, "Event"):
            core.Event = type("Event", (), {})
    # hvac_override imports ZoneState too; the hvac loader's hvac_zones stub
    # only carries ZoneManager.
    zkey = "ura_hvac_pkg.domain_coordinators.hvac_zones"
    zmod = sys.modules.get(zkey)
    if zmod is not None and not hasattr(zmod, "ZoneState"):
        zmod.ZoneState = type("ZoneState", (), {})


# Modules loaded REAL for per-emission-class tests. Once loaded we OVERWRITE
# the lightweight `object` stubs the hvac loader installed.
_REAL_LOADED: dict[str, object] = {}


# Sibling modules that a REAL-loaded module imports at module scope. The
# loader installs a lightweight stub for each BEFORE exec so the import
# resolves; only the symbol actually imported needs to exist.
#
# 2026-08-23: hvac_override.py:116 does `from .energy_billing import
# _get_effective_rate_kwh`. The loader placed hvac_override under the
# synthetic package `ura_hvac_pkg.domain_coordinators` but never provided that
# sibling, so exec_module raised
#   ModuleNotFoundError: No module named
#   'ura_hvac_pkg.domain_coordinators.energy_billing'
# and all four freeze-floor tests failed. The traceback POINTS AT PRODUCTION
# CODE (hvac_override.py:116), which is why the D1 triage classified these as
# real product defects — but the raise is a HARNESS gap, not a code defect.
# The production import is correct and works in HA.
@contextlib.asynccontextmanager
async def _noop_acm(*_a, **_kw):
    """Stand-in for hvac_excursion.auto_release_on_incomplete.

    Must be a genuine async context manager — the production nudge path does
    `async with hvac_excursion.auto_release_on_incomplete(...)`, so a MagicMock
    or bare attribute fails at __aenter__.
    """
    yield None


async def _noop_async_none(*_a, **_kw):
    return None


_SIBLING_STUBS: dict[str, dict] = {
    # hvac_override.py:116 — `from .energy_billing import _get_effective_rate_kwh`
    "energy_billing": {"_get_effective_rate_kwh": lambda *a, **kw: 0.0},
    # hvac_predict.py:1345 — `from . import hvac_excursion` (whole module).
    # Needs a REAL async context manager, not a MagicMock: the nudge path uses
    # `async with hvac_excursion.auto_release_on_incomplete(...)`, and a plain
    # attribute stub raises AttributeError at the `async with`.
    "hvac_excursion": {
        "auto_release_on_incomplete": _noop_acm,
        "begin_excursion": _noop_async_none,
        "return_excursion": _noop_async_none,
    },
}


def _install_sibling_stubs():
    """Provide sibling modules the REAL-loaded modules import at module scope.

    Two placements are needed, and only one is obvious:
      * sys.modules[pkg.sib] — satisfies `from .sib import name`
      * setattr(parent_pkg, sib) — ALSO required for `from . import sib`,
        which resolves the name as an ATTRIBUTE of the package. Without it
        that form raises "cannot import name 'hvac_excursion' from
        'ura_hvac_pkg.domain_coordinators' (unknown location)" even though
        sys.modules holds the module.
    """
    parent_key = "ura_hvac_pkg.domain_coordinators"
    parent = sys.modules.get(parent_key)
    for _sib, _attrs in _SIBLING_STUBS.items():
        _key = f"{parent_key}.{_sib}"
        _m = sys.modules.get(_key)
        if _m is None:
            _m = types.ModuleType(_key)
            _m.__package__ = parent_key
            for _k, _v in _attrs.items():
                setattr(_m, _k, _v)
            sys.modules[_key] = _m
        if parent is not None and not hasattr(parent, _sib):
            setattr(parent, _sib, _m)


def _load_real_submodule(name, attr):
    _load_hvac_module()  # package + hvac_const + hvac_setpoint
    _stub_recorder_deps()
    _install_sibling_stubs()
    key = f"ura_hvac_pkg.domain_coordinators.{name}"
    if key in _REAL_LOADED:
        return _REAL_LOADED[key]
    src = ROOT_DIR / ROOT_REL / "domain_coordinators" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(key, str(src))
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "ura_hvac_pkg.domain_coordinators"
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    _REAL_LOADED[key] = mod
    return mod


def _fill_init_defaults(obj, src_name, cls_name):
    """Set attributes the REAL __init__ would set that __new__ construction skips.

    2026-08-23. These tests build objects with `Cls.__new__(Cls)`, bypassing
    __init__ entirely, then hand-set only the attributes the author knew the
    path touched. Every later cycle that adds state to __init__ breaks them
    with an AttributeError raised INSIDE PRODUCTION CODE — which is exactly the
    traceback shape that made the D1 triage classify these as real product
    defects. They are not. Production __init__ is correct; the harness is
    incomplete.

    Rather than hand-listing attribute names (I guessed one wrong on the first
    attempt — `_hold_immunity` instead of `_immune_holds`), DERIVE them from the
    production source: parse __init__ and replay every simple
    `self.NAME = <literal>` assignment that the object does not already have.
    That self-maintains as __init__ grows, which is the property the previous
    approach lacked.

    Only fills what is MISSING, so a test that deliberately configures an
    attribute still wins.
    """
    import ast as _ast
    src = (ROOT_DIR / ROOT_REL / "domain_coordinators" / f"{src_name}.py").read_text()
    tree = _ast.parse(src)
    cls = next(
        (n for n in _ast.walk(tree)
         if isinstance(n, _ast.ClassDef) and n.name == cls_name),
        None,
    )
    if cls is None:
        return obj
    init = next(
        (n for n in cls.body
         if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
         and n.name == "__init__"),
        None,
    )
    if init is None:
        return obj
    for node in _ast.walk(init):
        target = value = None
        if isinstance(node, _ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        elif isinstance(node, _ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        if not isinstance(target, _ast.Attribute):
            continue
        if not (isinstance(target.value, _ast.Name) and target.value.id == "self"):
            continue
        try:
            default = _ast.literal_eval(value)   # literals only — skip calls
        except (ValueError, SyntaxError):
            continue
        if not hasattr(obj, target.attr):
            setattr(obj, target.attr, default)
    return obj


def _load_predict_module():
    # hvac_predict imports hvac_override at top → load override real first so
    # the `object` stub doesn't shadow it.
    _load_real_submodule("hvac_override", "OverrideArrester")
    return _load_real_submodule("hvac_predict", "HVACPredictor")


class _PHZone:
    def __init__(self, zid, entity, low, high):
        self.zone_id = zid
        self.climate_entity = entity
        self.zone_name = "Z"
        self.target_temp_low = low
        self.target_temp_high = high
        self.any_room_occupied = True


@pytest.mark.asyncio
async def test_predict_preheat_floored_via_chokepoint():
    """PER-CLASS (predict): pre-heat raises low+2; during a freeze with the
    result < 50 the chokepoint floors it to 50."""
    mod = _load_predict_module()
    pred = mod.HVACPredictor.__new__(mod.HVACPredictor)
    _fill_init_defaults(pred, "hvac_predict", "HVACPredictor")
    pred.hass = _CapHass()
    zone = _PHZone("z1", "climate.z1", low=46, high=70)  # low+2 = 48 < 50
    pred._zone_manager = types.SimpleNamespace(zones={"z1": zone})
    pred._egress_manager = None
    pred._override_arrester = None
    # freeze-active accessor reads HC backref:
    pred._hvac_coord = types.SimpleNamespace(freeze_active=True)
    await pred._execute_pre_heat()
    calls = [c["data"] for c in pred.hass.calls if c["service"] == "set_temperature"]
    assert len(calls) == 1
    assert calls[0]["target_temp_low"] == 50  # 48 floored to 50


@pytest.mark.asyncio
async def test_predict_preheat_no_freeze_unchanged():
    mod = _load_predict_module()
    pred = mod.HVACPredictor.__new__(mod.HVACPredictor)
    _fill_init_defaults(pred, "hvac_predict", "HVACPredictor")
    pred.hass = _CapHass()
    zone = _PHZone("z1", "climate.z1", low=46, high=70)
    pred._zone_manager = types.SimpleNamespace(zones={"z1": zone})
    pred._egress_manager = None
    pred._override_arrester = None
    pred._hvac_coord = types.SimpleNamespace(freeze_active=False)
    await pred._execute_pre_heat()
    calls = [c["data"] for c in pred.hass.calls if c["service"] == "set_temperature"]
    assert calls[0]["target_temp_low"] == 48  # low+2, no floor


def _load_override_module():
    return _load_real_submodule("hvac_override", "OverrideArrester")


@pytest.mark.asyncio
async def test_override_compromise_floored_via_chokepoint():
    """PER-CLASS (override): a compromise heat (low) below the floor during a
    freeze is raised to 50 through the chokepoint."""
    mod = _load_override_module()
    arr = mod.OverrideArrester.__new__(mod.OverrideArrester)
    _fill_init_defaults(arr, "hvac_override", "OverrideArrester")
    arr.hass = _CapHass()
    arr._compromise_active = {}
    arr._grace_timers = {}
    arr._compromise_timers = {}
    arr._compromise_minutes = 30
    # FIX B1 (2026-07-26): _apply_compromise now calls self.suppress(kind="temp")
    # to prevent induced preset_mode manual side effects from self-counting.
    # __new__ construction needs the suppression dicts.
    arr._suppressed_until = {}
    arr._suppress_kind = {}
    arr._hvac_coord = types.SimpleNamespace(freeze_active=True)
    zone = types.SimpleNamespace(
        zone_id="z1", climate_entity="climate.z1", zone_name="Z",
    )

    # Patch async_call_later (imported into the module) to a no-op canceller so
    # the revert scheduling doesn't blow up.
    mod.async_call_later = lambda *a, **kw: (lambda: None)

    await arr._apply_compromise(
        zone, original_preset="home",
        compromise_cool=60, compromise_heat=47,  # heat=low 47 < 50
        expected_cool=60, expected_heat=47,
    )
    calls = [c["data"] for c in arr.hass.calls if c["service"] == "set_temperature"]
    assert len(calls) == 1
    assert calls[0]["target_temp_low"] == 50  # 47 floored


# ---------------------------------------------------------------------------
# FULL-CYCLE LEAK (D-HIGH repro): preset-apply (low 48) THEN pre-heat run in
# sequence; the FINAL emitted low must be ≥ 50.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_cycle_preset_then_preheat_final_low_floored():
    """D-HIGH: custom low 47/48 path emits via preset-apply, then pre-heat runs
    after (low+2) — BOTH route through the chokepoint, so the final low ≥ 50."""
    # 1. preset-apply: cool_setpoint 55 → baseline_low 48, freeze armed.
    coord = _make_coord(cool_setpoint=55, outdoor_temp=30)
    coord._update_freeze_active()  # cycle refreshes before apply (D-HIGH-1)
    await coord._async_apply_preset_overrides()
    apply_calls = _set_temp_calls(coord)
    assert apply_calls[-1]["target_temp_low"] == 50  # floored at apply

    # 2. pre-heat runs AFTER: low+2 from a custom 47 base = 49 (< 50).
    mod = _load_predict_module()
    pred = mod.HVACPredictor.__new__(mod.HVACPredictor)
    _fill_init_defaults(pred, "hvac_predict", "HVACPredictor")
    pred.hass = _CapHass()
    zone = _PHZone("z1", "climate.z1", low=47, high=55)  # low+2 = 49
    pred._zone_manager = types.SimpleNamespace(zones={"z1": zone})
    pred._egress_manager = None
    pred._override_arrester = None
    pred._hvac_coord = types.SimpleNamespace(freeze_active=True)
    await pred._execute_pre_heat()
    ph_calls = [c["data"] for c in pred.hass.calls if c["service"] == "set_temperature"]
    # FINAL emission (pre-heat, the leak site) is also floored ≥ 50.
    assert ph_calls[-1]["target_temp_low"] == 50


# ---------------------------------------------------------------------------
# D-HIGH-1: `_update_freeze_active()` must refresh `_freeze_active`
# UNCONDITIONALLY once per decision cycle — BEFORE the predictor/arrester run —
# even when the DPM-apply path is gated off (guest-mode-actuation disabled
# AND observation mode). Mutation gate: if the refresh is reverted to its old
# location INSIDE `_async_apply_preset_overrides` (gated), `freeze_active`
# stays at its False default and the predictor's lazy read floors nothing.
# ---------------------------------------------------------------------------


class _LazyFreezePredictor:
    """Stands in for the real predictor: its per-cycle `update()` reads
    `coord.freeze_active` LAZILY (as the banking/pre-heat emitters do) and emits
    a sub-floor heat_low through the REAL setpoint chokepoint. Whether that emit
    is floored depends entirely on whether `_freeze_active` was refreshed BEFORE
    this runs."""

    def __init__(self, coord, outdoor_temp):
        self._coord = coord
        self._outdoor_temp = outdoor_temp
        self.flushed = False

    def _get_outdoor_temp(self):
        return self._outdoor_temp

    def flush_daily_outcome(self):
        self.flushed = True

    async def update(self, *a, **kw):
        from ura_hvac_pkg.domain_coordinators.hvac_setpoint import (
            emit_set_temperature,
        )

        # Lazy read — exactly like predict.py's `_freeze_active` property.
        await emit_set_temperature(
            self._coord.hass,
            "climate.zone_1",
            target_temp_low=46,  # < FREEZE_FLOOR
            target_temp_high=70,
            freeze_active=self._coord.freeze_active,
            blocking=False,
        )


class _CycleNoopArrester(_FakeOverrideArrester):
    async def async_startup_audit(self, *a, **kw):
        pass

    async def async_startup_ramp_audit(self, *a, **kw):
        pass

    def update_energy_state(self, *a, **kw):
        pass

    async def check_ac_reset(self, *a, **kw):
        pass


class _CycleZoneManager(_FakeZoneManager):
    def update_all_zones(self):
        pass

    def update_room_conditions(self):
        pass

    def reset_daily_counters(self):
        pass

    def get_state_snapshot(self):
        return {}


class _CycleEgress(_FakeEgressManager):
    async def async_tick(self, now):
        pass


def _make_cycle_coord(*, outdoor_temp, guest_mode, observation):
    """Coordinator wired to run the REAL `_run_decision_cycle` end-to-end with
    the predictor emitting lazily. DPM-apply path is gated off via
    guest_mode/observation so only the unconditional refresh can arm freeze."""
    import asyncio

    mod = _load_hvac_module()
    coord = mod.HVACCoordinator.__new__(mod.HVACCoordinator)
    _fill_init_defaults(coord, "hvac", "HVACCoordinator")
    coord.hass = _FakeHass()
    coord._enabled = True
    coord._boot_settle_done = True
    coord._decision_cycle_lock = asyncio.Lock()
    coord._house_state = "home"
    coord._guest_mode_actuation_enabled = guest_mode
    coord._observation_mode = observation
    coord._last_daily_reset = datetime.now(timezone.utc).date().isoformat()
    coord._zone_manager = _CycleZoneManager(
        {"zone_1": _FakeZone("zone_1", "climate.zone_1")}
    )
    coord._egress_manager = _CycleEgress()
    coord._override_arrester = _CycleNoopArrester()
    coord._preset_manager = _FakePresetManager(55)
    coord._predictor = _LazyFreezePredictor(coord, outdoor_temp)
    coord._last_emitted_range = {}
    coord._freeze_active = False  # default — pre-fix this stays False
    coord._startup_audit_done = True
    coord._zone_intelligence_enabled = False
    coord._energy_constraint = None
    coord._energy_offset = 0
    coord._energy_constraint_mode = "normal"
    coord._fan_control_enabled = False
    coord._defer_gate_enabled = False
    coord._pre_arrival_zones = set()
    coord._zone_state_save_counter = 0

    async def _noop(*a, **kw):
        pass

    coord._fan_controller = types.SimpleNamespace(
        update=_noop, turn_off_all_managed=_noop,
    )
    coord._cover_controller = types.SimpleNamespace(update=_noop)
    coord._record_anomaly_observations = _noop
    return coord


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guest_mode,observation",
    [
        # Observation mode: `_apply_house_state_presets` (and its DPM-apply
        # call) is skipped entirely; only the predictor runs.
        (True, True),
        # Both gates off (first-boot-shaped): guest-mode-actuation disabled AND
        # observation — the gated apply path can never refresh freeze.
        (False, True),
    ],
)
async def test_freeze_refreshed_before_predictor_with_apply_gated(
    guest_mode, observation
):
    """D-HIGH-1 MUTATION GATE: with the DPM-apply path gated off and a real
    freeze, the predictor's lazy emit during the cycle STILL gets floored,
    because `_update_freeze_active()` runs unconditionally BEFORE the predictor.

    Revert the refresh into `_async_apply_preset_overrides` (the gated path) and
    `freeze_active` stays False here → the emitted low is 46, not 50 → FAIL."""
    coord = _make_cycle_coord(
        outdoor_temp=30,  # ≤ FREEZE_TRIGGER_TEMP → arms
        guest_mode=guest_mode, observation=observation,
    )
    assert coord._freeze_active is False  # default before the cycle runs

    await coord._run_decision_cycle()

    # Freeze was armed unconditionally by the cycle, before the predictor emit.
    assert coord._freeze_active is True
    calls = _set_temp_calls(coord)
    assert len(calls) == 1
    assert calls[0]["target_temp_low"] == 50  # 46 floored — the fix proves out
    assert calls[0]["target_temp_high"] == 70

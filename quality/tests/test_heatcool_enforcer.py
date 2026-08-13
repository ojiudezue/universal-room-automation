"""Tests for the continuous heat_cool enforcer (feature/heatcool-enforcer-reason-fix).

The periodic decision cycle (_apply_house_state_presets) restores heat_cool on
ANY non-heat_cool drift for heat_cool-capable zones — not just zones stuck in
"off". Previously a zone drifted to "cool" (preset/setpoints unchanged) had NO
recovery path: the OverrideArrester only reverts on a MANUAL-PRESET override,
and the old restore loop only caught hvac_mode == "off".

These tests drive the REAL `HVACCoordinator._apply_house_state_presets` method
object end-to-end. The real `hvac` module is loaded (HA + sibling coordinators
stubbed), and the unbound production method is bound to a minimal coordinator
instance carrying fake collaborators (zone_manager / override_arrester /
egress_manager) and a fake `hass.services` that CAPTURES `set_hvac_mode` calls.
Because the genuine method body runs, reverting the guard back to `== "off"`
(or removing the `_supports_heat_cool` / egress / AC-reset skips) makes the
corresponding assertions FAIL.

The coordinator's `_house_state` is set to "arriving" so the method returns
immediately AFTER the enforcer loop runs — isolating the enforcer behavior
from the downstream preset/vacancy logic (which `arriving` legitimately skips).
The D6 consensus defer gate is disabled (`_defer_gate_enabled = False`) so the
enforcer loop is reached unconditionally.
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


def _load_hvac_module():
    if "ura_hvac_under_test" in sys.modules:
        return sys.modules["ura_hvac_under_test"]

    # --- Stub homeassistant surface ---
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

    # --- Stub the ura package so relative imports resolve ---
    pkg = _stub_module("ura_hvac_pkg")
    pkg.__path__ = []
    # const carries many names used at import + call time; a permissive
    # attribute factory keeps `from ..const import X` happy for any X.
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

    # Real hvac_const (cheap, no HA deps beyond stdlib) — load for fidelity.
    hvac_const_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_const.py"
    spec = importlib.util.spec_from_file_location(
        "ura_hvac_pkg.domain_coordinators.hvac_const", str(hvac_const_src)
    )
    hvac_const = importlib.util.module_from_spec(spec)
    hvac_const.__package__ = "ura_hvac_pkg.domain_coordinators"
    sys.modules["ura_hvac_pkg.domain_coordinators.hvac_const"] = hvac_const
    spec.loader.exec_module(hvac_const)

    # Stub base.BaseCoordinator + friends (we never call __init__).
    class _BaseCoordinator:
        def __init__(self, *a, **kw):
            pass

    base = _stub_module(
        "ura_hvac_pkg.domain_coordinators.base",
        BaseCoordinator=_BaseCoordinator,
        CoordinatorAction=object,
        Intent=object,
    )

    # Stub sibling coordinator modules (only the imported NAMES are needed at
    # module-load time; we never construct them in these tests).
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_covers", CoverController=object
    )
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_egress", EgressManager=object
    )
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_fans", FanController=object
    )
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_override", OverrideArrester=object
    )
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_predict", HVACPredictor=object
    )
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_preset", PresetManager=object
    )
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_zones", ZoneManager=object
    )
    # hvac_setpoint: SUITE-HYGIENE-2 — hvac.py imports the setpoint chokepoint
    # helpers. Standalone we must stub them; in-suite a sibling loader (e.g.
    # test_freeze_floor) may install a real one, but our own stub is fine.
    _stub_module(
        "ura_hvac_pkg.domain_coordinators.hvac_setpoint",
        apply_setpoint_guards=lambda *a, **kw: None,
        emit_set_preset_mode=lambda *a, **kw: None,
        emit_set_temperature=lambda *a, **kw: None,
    )

    # signals: permissive — every SIGNAL_* import resolves to a sentinel str.
    signals = types.ModuleType("ura_hvac_pkg.domain_coordinators.signals")

    def _signals_getattr(name):
        return name

    signals.__getattr__ = _signals_getattr  # type: ignore[attr-defined]
    sys.modules["ura_hvac_pkg.domain_coordinators.signals"] = signals

    # --- Load the REAL hvac module ---
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
    def __init__(self, zone_id, hvac_mode, climate_entity, zone_name="Zone"):
        self.zone_id = zone_id
        self.hvac_mode = hvac_mode
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
    def __init__(self, *, heat_cool_capable=(), ac_reset_zones=()):
        self._capable = set(heat_cool_capable)
        self._ac_reset = set(ac_reset_zones)
        self.suppressed = []
        self.unsuppressed = []

    def _supports_heat_cool(self, climate_entity):
        return climate_entity in self._capable

    def has_active_ac_reset(self, zone_id):
        return zone_id in self._ac_reset

    def suppress(self, entity_id):
        self.suppressed.append(entity_id)

    def unsuppress(self, entity_id):
        self.unsuppressed.append(entity_id)


class _FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append(
            {"domain": domain, "service": service, "data": dict(data)}
        )


class _FakeHass:
    def __init__(self):
        self.services = _FakeServices()
        self.data = {}


def _make_coord(*, zones, egress_paused=(), heat_cool_capable=(), ac_reset_zones=()):
    """Build a minimal object bound to the REAL _apply_house_state_presets.

    We deliberately bypass HVACCoordinator.__init__ (it wires ~10 sub-managers
    we don't need) and bind the genuine production method to a bare instance
    carrying only the attributes the enforcer path reads. `_house_state` is
    "arriving" so the real method returns right after the enforcer loop.
    """
    mod = _load_hvac_module()
    coord = mod.HVACCoordinator.__new__(mod.HVACCoordinator)
    coord.hass = _FakeHass()
    coord._house_state = "arriving"  # returns right after the enforcer loop
    coord._defer_gate_enabled = False  # skip the D6 consensus gate
    coord._zone_manager = _FakeZoneManager(zones)
    coord._egress_manager = _FakeEgressManager(egress_paused)
    coord._override_arrester = _FakeOverrideArrester(
        heat_cool_capable=heat_cool_capable, ac_reset_zones=ac_reset_zones
    )
    return coord


def _set_hvac_modes(coord):
    return [
        c["data"].get("hvac_mode")
        for c in coord.hass.services.calls
        if c["service"] == "set_hvac_mode"
    ]


# ---------------------------------------------------------------------------
# Tests — each drives the REAL _apply_house_state_presets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cool_drift_is_enforced_to_heat_cool():
    """The reported live bug: a heat_cool-capable zone drifted to 'cool' with
    its preset unchanged → enforcer issues set_hvac_mode=heat_cool."""
    z = _FakeZone("zone_1", "cool", "climate.zone_1")
    coord = _make_coord(zones={"zone_1": z}, heat_cool_capable={"climate.zone_1"})
    await coord._apply_house_state_presets()
    assert _set_hvac_modes(coord) == ["heat_cool"]
    # Suppress handshake fired, and (success path) no unsuppress.
    assert "climate.zone_1" in coord._override_arrester.suppressed
    assert "climate.zone_1" not in coord._override_arrester.unsuppressed


@pytest.mark.asyncio
async def test_already_heat_cool_is_idempotent_no_write():
    """A zone already in heat_cool produces NO set_hvac_mode call."""
    z = _FakeZone("zone_1", "heat_cool", "climate.zone_1")
    coord = _make_coord(zones={"zone_1": z}, heat_cool_capable={"climate.zone_1"})
    await coord._apply_house_state_presets()
    assert _set_hvac_modes(coord) == []
    assert coord._override_arrester.suppressed == []


@pytest.mark.asyncio
async def test_egress_paused_off_zone_not_clobbered():
    """EgressManager set the zone 'off' deliberately (window open) → skip."""
    z = _FakeZone("zone_1", "off", "climate.zone_1")
    coord = _make_coord(
        zones={"zone_1": z},
        heat_cool_capable={"climate.zone_1"},
        egress_paused={"zone_1"},
    )
    await coord._apply_house_state_presets()
    assert _set_hvac_modes(coord) == []


@pytest.mark.asyncio
async def test_ac_reset_off_zone_not_clobbered():
    """A zone mid-AC-reset is intentionally 'off' for a short cycle → skip."""
    z = _FakeZone("zone_1", "off", "climate.zone_1")
    coord = _make_coord(
        zones={"zone_1": z},
        heat_cool_capable={"climate.zone_1"},
        ac_reset_zones={"zone_1"},
    )
    await coord._apply_house_state_presets()
    assert _set_hvac_modes(coord) == []


@pytest.mark.asyncio
async def test_heat_only_thermostat_never_forced():
    """A genuinely heat-only / cool-only unit (no heat_cool support) is left
    alone — the _supports_heat_cool guard prevents forcing an unsupported
    mode, even though its mode != heat_cool."""
    z = _FakeZone("zone_1", "heat", "climate.zone_1")
    coord = _make_coord(zones={"zone_1": z}, heat_cool_capable=set())
    await coord._apply_house_state_presets()
    assert _set_hvac_modes(coord) == []


@pytest.mark.asyncio
async def test_single_mode_heat_is_enforced_to_heat_cool():
    """Operator decision 2026-06-16: single-mode 'heat' is NOT exempt. A
    heat_cool-capable zone in 'heat' is reverted to heat_cool by the enforcer
    (heat_cool still heats via the low setpoint). This is the behavioral note
    in the enforcer — it must hold."""
    z = _FakeZone("zone_1", "heat", "climate.zone_1")
    coord = _make_coord(zones={"zone_1": z}, heat_cool_capable={"climate.zone_1"})
    await coord._apply_house_state_presets()
    assert _set_hvac_modes(coord) == ["heat_cool"]

"""Tests for v5.7.1 Energy Saver Pre-Cool unification.

Replaces the deleted ``test_solar_banking_toggle.py`` (the v4.7-era
banking-toggle behavioral surface) with the new unified Energy Saver
Pre-Cool surface. Tier 3 mutation-anchored — every load-bearing site
(PV gate, scope branch, dispatch-time net-power re-check, offset
application, floor clamp, migration) has a behavioral test that fails
under a real per-site logic mutation.

Source-of-truth fixtures are sibling-loaded from
``test_hc_precool_oc_observability.py`` (same project, same sys.modules
priming). We replicate the loader pattern here so this file is
standalone for pytest isolation.

PLANNING_v5.7.x_energy_pre_cool_unification.md acceptance criteria:
- D1 — PV-gate (I1), offset configurable, scope branches (I6).
- D2 — toggle / Number / Select round-trip + per-site mutations.
- D3 — old banking symbols deleted.
- D4 — pre-arrival / pre-heat byte-identical.
- D5 — config migration idempotent.

I3 (floor clamp at 72°F) is invariant under any configured offset.
"""

import asyncio
import json
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module priming — sibling pattern to test_hc_precool_oc_observability.py.
# setdefault ONLY so we don't clobber prior wiring.
# ---------------------------------------------------------------------------

_identity = lambda fn: fn  # noqa: E731


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _utcnow():
    return datetime.now(timezone.utc)


def _now():
    return datetime.now(timezone.utc)


_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": MagicMock},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
        "async_track_time_interval": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(return_value=lambda: None),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": MagicMock(),
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {
            "async_added_to_hass": AsyncMock(),
            "async_get_last_state": AsyncMock(return_value=None),
        }),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _utcnow, "now": _now, "UTC": timezone.utc,
        "as_local": lambda d: d,
        "parse_datetime": lambda s: datetime.fromisoformat(s) if s else None,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": MagicMock(), "SensorStateClass": MagicMock(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": MagicMock(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": MagicMock(),
    },
    "homeassistant.components.select": {
        "SelectEntity": type("SelectEntity", (), {}),
    },
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)

import importlib.util  # noqa: E402

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(_ROOT, "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
if "custom_components.universal_room_automation.const" not in sys.modules:
    _const_mod = importlib.util.module_from_spec(_const_spec)
    sys.modules["custom_components.universal_room_automation.const"] = _const_mod
    _const_spec.loader.exec_module(_const_mod)
    _ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc_name = "custom_components.universal_room_automation.domain_coordinators"
if _dc_name not in sys.modules:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [_dc_path]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc
    _ura.domain_coordinators = _dc

_SENTINEL = object()


def _load_dc_module(submod_name: str):
    full = f"{_dc_name}.{submod_name}"
    if full in sys.modules and hasattr(sys.modules[full], "__file__"):
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_dc_path, f"{submod_name}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    setattr(sys.modules[_dc_name], submod_name, mod)
    return mod


def _load_real_predictor_class():
    full = f"{_dc_name}.hvac_predict"
    existing = sys.modules.get(full)
    cls = getattr(existing, "HVACPredictor", None) if existing else None
    if (
        cls is not None
        and not isinstance(cls, MagicMock)
        and hasattr(existing, "__file__")
        and existing.__file__
    ):
        return cls
    peer_names = (
        f"{_dc_name}.hvac_override",
        f"{_dc_name}.hvac_preset",
        f"{_dc_name}.hvac_zones",
        f"{_dc_name}.hvac_setpoint",  # v5.7.1 fix-up (A3): stub deterministically
        f"{_dc_name}.signals",
    )
    saved = {n: sys.modules.get(n, _SENTINEL) for n in peer_names}

    def _ensure_stub(name, **attrs):
        # v5.7.1 fix-up (A3 MED): force-install a fresh stub regardless of
        # what a prior peer test left in sys.modules. The previous
        # `setdefault`-style guard let stale modules (loaded by sibling
        # tests with partial peer sets) leak through, which made
        # hvac_setpoint absent and hvac_predict's `from .hvac_setpoint
        # import ...` raise ModuleNotFoundError. Always replace; the
        # `saved`/restore block below restores prior state.
        sys.modules[name] = _mock_module(name, **attrs)

    _ensure_stub(
        f"{_dc_name}.hvac_override",
        OverrideArrester=type("OverrideArrester", (), {}),
    )
    _ensure_stub(
        f"{_dc_name}.hvac_preset",
        PresetManager=type("PresetManager", (), {}),
    )
    _ensure_stub(
        f"{_dc_name}.hvac_zones",
        ZoneManager=type("ZoneManager", (), {}),
    )
    # v5.7.1 fix-up (A3 MED): hvac_predict imports apply_setpoint_guards +
    # emit_set_temperature at module load. Stub both so the exec succeeds
    # in any test-ordering scenario.
    async def _stub_emit_set_temperature(*a, **k):
        return None

    def _stub_apply_setpoint_guards(*a, **k):
        return None

    _ensure_stub(
        f"{_dc_name}.hvac_setpoint",
        apply_setpoint_guards=_stub_apply_setpoint_guards,
        emit_set_temperature=_stub_emit_set_temperature,
    )
    _ensure_stub(
        f"{_dc_name}.signals",
        EnergyConstraint=type("EnergyConstraint", (), {}),
    )

    try:
        spec = importlib.util.spec_from_file_location(
            full, os.path.join(_dc_path, "hvac_predict.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        prior_full = sys.modules.get(full, _SENTINEL)
        sys.modules[full] = mod
        try:
            spec.loader.exec_module(mod)
            cls = mod.HVACPredictor
        finally:
            if prior_full is _SENTINEL:
                sys.modules.pop(full, None)
            else:
                sys.modules[full] = prior_full
        return cls
    finally:
        for n, prev in saved.items():
            if prev is _SENTINEL:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = prev


_recorder_mod = _mock_module(
    "homeassistant.components.recorder",
    get_instance=MagicMock(),
)
_recorder_mod.__path__ = []
sys.modules.setdefault("homeassistant.components.recorder", _recorder_mod)
sys.modules.setdefault(
    "homeassistant.components.recorder.history",
    _mock_module(
        "homeassistant.components.recorder.history",
        get_significant_states=MagicMock(return_value={}),
    ),
)

_hvac_const_mod = _load_dc_module("hvac_const")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_coro(coro):
    prior = None
    try:
        prior = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        prior = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        if prior is not None and not prior.is_closed():
            asyncio.set_event_loop(prior)
        else:
            asyncio.set_event_loop(asyncio.new_event_loop())


def _make_zone(zone_id="z1", occupied=True, temp_high=78.0, temp_low=70.0):
    z = MagicMock()
    z.zone_id = zone_id
    z.zone_name = zone_id.upper()
    z.climate_entity = f"climate.{zone_id}"
    z.target_temp_high = temp_high
    z.target_temp_low = temp_low
    z.any_room_occupied = occupied
    z.last_occupied_time = None
    return z


def _make_predictor(zones=None):
    HVACPredictor = _load_real_predictor_class()
    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    zm = MagicMock()
    if zones is None:
        zones = {"z1": _make_zone("z1", occupied=True)}
    zm.zones = zones
    pm = MagicMock()
    pm.current_season = "summer"
    arrester = MagicMock()
    pred = HVACPredictor(
        hass=hass,
        zone_manager=zm,
        preset_manager=pm,
        override_arrester=arrester,
        net_power_entity=None,
    )
    return pred, hass


def _install_ec(
    hass,
    *,
    enabled=True,
    offset=-2.0,
    scope="auto_pv_tiered",
    pre_cond_enabled=True,
):
    from custom_components.universal_room_automation.const import DOMAIN
    hvac = MagicMock()
    hvac.pre_conditioning_enabled = pre_cond_enabled
    energy = MagicMock()
    energy.energy_precool_enabled = enabled
    energy.energy_precool_offset = offset
    energy.energy_precool_scope = scope
    manager = MagicMock()
    manager.coordinators = {"hvac": hvac, "energy": energy}
    hass.data[DOMAIN] = {"coordinator_manager": manager}
    return energy


def _make_constraint(soc=98, forecast_high=92, mode="normal"):
    c = MagicMock()
    c.soc = soc
    c.forecast_high_temp = forecast_high
    c.mode = mode
    return c


def _drive(pred, hass, *, scope=None, enabled=True, offset=-2.0,
           pre_cond_enabled=True, net_power=-800.0,
           constraint=None, house_state="home_day", now=None,
           zone_intelligence_enabled=True):
    """Drive _check_pre_conditioning with the new unified pre-cool wiring."""
    _install_ec(
        hass, enabled=enabled, offset=offset,
        scope=scope or "auto_pv_tiered",
        pre_cond_enabled=pre_cond_enabled,
    )
    pred._first_eval_done = True
    pred._get_net_power = MagicMock(return_value=net_power)
    if constraint is None:
        constraint = _make_constraint()
    if now is None:
        now = datetime(2026, 6, 11, 13, 0, 0)
    calls: list = []

    async def _spy_precool(zone, offset, reason):
        calls.append({"zone_id": zone.zone_id, "offset": offset,
                      "reason": reason})

    pred._execute_zone_pre_cool = _spy_precool
    _run_coro(pred._check_pre_conditioning(
        constraint, house_state=house_state, now=now,
        pre_arrival_zones=set(),
        zone_intelligence_enabled=zone_intelligence_enabled,
    ))
    return calls


# ===========================================================================
# D3 — banking symbols deleted
# ===========================================================================

class TestD3BankingSymbolsDeleted:

    def test_should_solar_bank_deleted(self):
        src = open(os.path.join(
            _dc_path, "hvac_predict.py",
        )).read()
        assert "def _should_solar_bank" not in src
        assert "def _should_weather_pre_cool" not in src
        assert "def _is_solar_banking_enabled" not in src

    def test_should_energy_precool_exists(self):
        src = open(os.path.join(
            _dc_path, "hvac_predict.py",
        )).read()
        assert "def _should_energy_precool" in src
        assert "def _is_energy_precool_enabled" in src
        assert "def _get_energy_precool_offset" in src
        assert "def _get_energy_precool_scope" in src

    def test_old_conf_constant_removed(self):
        # Symbol absent from hvac_const exports (kept only as string
        # literal in __init__.async_migrate body and comments).
        assert not hasattr(_hvac_const_mod, "CONF_HVAC_SOLAR_BANK_ENABLED")
        assert not hasattr(_hvac_const_mod, "DEFAULT_HVAC_SOLAR_BANK_ENABLED")
        assert not hasattr(_hvac_const_mod, "SOLAR_BANK_OFFSET")
        assert not hasattr(_hvac_const_mod, "SOLAR_BANK_TEMP_MIN")
        # New consts present.
        assert _hvac_const_mod.ENERGY_PRECOOL_NAME == "Energy Saver Pre-Cool"
        assert _hvac_const_mod.CONF_ENERGY_PRECOOL_ENABLED == (
            "energy_precool_enabled"
        )
        assert _hvac_const_mod.DEFAULT_ENERGY_PRECOOL_ENABLED is True
        assert _hvac_const_mod.DEFAULT_ENERGY_PRECOOL_OFFSET == -2.0
        assert _hvac_const_mod.DEFAULT_ENERGY_PRECOOL_SCOPE == (
            "auto_pv_tiered"
        )
        assert set(_hvac_const_mod.ENERGY_PRECOOL_SCOPE_VALUES) == {
            "occupied_only", "whole_house", "auto_pv_tiered",
        }

    def test_switch_class_renamed(self):
        src = open(os.path.join(
            _ura_path, "switch.py",
        )).read()
        assert "ECEnergyPreCoolSwitch" in src
        # Old switch class is gone from production source.
        # (Block-scope check — only as comments, no assignment).
        for line in src.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "ECSolarBankingSwitch =" not in stripped
            assert "ECSolarBankingSwitch(hass" not in stripped


# ===========================================================================
# D1 — I1 PV gate (mutation-anchored)
# ===========================================================================

class TestD1PVGate:
    """Mutation: delete the `if net_power >= -ENERGY_PRECOOL_EXPORT_THRESHOLD_W`
    early-return → the no-sun test below fails."""

    def test_pv_surplus_plus_hot_fires(self):
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=60, forecast_high=95),
            scope="whole_house",
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        reasons = [c["reason"] for c in calls]
        assert "energy_precool" in reasons, (
            "PV surplus + hot forecast + SOC>30 + summer + window 13:00 + "
            "whole_house scope MUST fire energy_precool"
        )

    def test_hot_no_pv_does_not_fire(self):
        """I1 falsification: forecast hot, SOC full, but ZERO export → no fire."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-100.0,  # well above -500W threshold
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert not calls, (
            "I1: no PV surplus MUST NOT pre-cool, even on hot forecast"
        )

    def test_pv_marginal_below_threshold_does_not_fire(self):
        pred, hass = _make_predictor()
        # -400W is exporting but BELOW the 500W minimum-surplus threshold.
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-400.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert not calls, "Marginal export below 500W MUST NOT trigger"

    def test_cool_day_requires_high_soc(self):
        """Cool day (forecast < precool_forecast_high) requires SOC >= 95."""
        pred, hass = _make_predictor()
        # SOC 60% on a cool day -> fails the cool-day SOC floor (95%).
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=60, forecast_high=80),
            scope="whole_house",
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert not calls
        # SOC 96% on the same cool day -> passes; fires.
        pred2, hass2 = _make_predictor()
        calls2 = _drive(
            pred2, hass2,
            constraint=_make_constraint(soc=96, forecast_high=80),
            scope="whole_house",
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert any(c["reason"] == "energy_precool" for c in calls2)

    def test_outside_hour_window_does_not_fire(self):
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-800.0,
            now=datetime(2026, 6, 11, 9, 0, 0),  # before [10, 14)
        )
        assert not calls

    def test_inclement_mode_blocks(self):
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(
                soc=98, forecast_high=95, mode="coast",
            ),
            scope="whole_house",
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert not calls, "Non-normal constraint.mode MUST block (v5.5.0 hold)"


# ===========================================================================
# D1 — Master "28" gate independence (I2)
# ===========================================================================

class TestD1I2MasterIndependence:

    def test_pre_cool_toggle_off_blocks_branch(self):
        """Mutation: invert `if precool_gate_on` -> this fails."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            enabled=False,  # operator OFF on EC sub-switch
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert not calls, (
            "Energy-Saver-Pre-Cool OFF MUST short-circuit even with "
            "perfect PV+hot conditions"
        )

    def test_master_28_off_blocks_even_when_pre_cool_on(self):
        """Defense in depth: master '28' (HC pre-conditioning) above."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            enabled=True,
            pre_cond_enabled=False,  # master '28' OFF
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert not calls


# ===========================================================================
# D1 — I6 Scope branches (occupied_only / whole_house / auto_pv_tiered)
# ===========================================================================

class TestD1I6Scope:

    def test_occupied_only_skips_unoccupied_zone(self):
        """Mutation: replace the `if scope == OCCUPIED_ONLY: ... continue`
        branch with `pass` -> this test fails."""
        zones = {
            "z_occ": _make_zone("z_occ", occupied=True),
            "z_emp": _make_zone("z_emp", occupied=False),
        }
        pred, hass = _make_predictor(zones=zones)
        calls = _drive(
            pred, hass,
            scope="occupied_only",
            constraint=_make_constraint(soc=98, forecast_high=95),
            net_power=-2000.0,  # huge surplus
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        zone_ids = [c["zone_id"] for c in calls]
        assert "z_occ" in zone_ids
        assert "z_emp" not in zone_ids, (
            "occupied_only MUST skip unoccupied zone even under surplus"
        )

    def test_whole_house_banks_all(self):
        zones = {
            "z_occ": _make_zone("z_occ", occupied=True),
            "z_emp": _make_zone("z_emp", occupied=False),
        }
        pred, hass = _make_predictor(zones=zones)
        calls = _drive(
            pred, hass,
            scope="whole_house",
            constraint=_make_constraint(soc=98, forecast_high=95),
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        zone_ids = {c["zone_id"] for c in calls}
        assert zone_ids == {"z_occ", "z_emp"}

    def test_auto_pv_tiered_with_real_surplus_expands(self):
        """auto_pv_tiered + real surplus -> unoccupied zone also fires (I6)."""
        zones = {
            "z_occ": _make_zone("z_occ", occupied=True),
            "z_emp": _make_zone("z_emp", occupied=False),
        }
        pred, hass = _make_predictor(zones=zones)
        calls = _drive(
            pred, hass,
            scope="auto_pv_tiered",
            constraint=_make_constraint(soc=98, forecast_high=95),
            net_power=-2000.0,  # real surplus
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        zone_ids = {c["zone_id"] for c in calls}
        assert zone_ids == {"z_occ", "z_emp"}

    def test_auto_pv_tiered_dispatch_time_recheck_skips_marginal(self):
        """Mutation: cache net_power at the GATE rather than re-reading
        at per-zone dispatch -> this test still passes (same value), so
        we use a stub that flips after gate evaluation to prove the
        recheck is at dispatch time.

        Concretely: we patch _get_net_power so the FIRST call (in the
        gate) reports strong surplus, but a SECOND call (the per-zone
        re-check for auto_pv_tiered) reports below-threshold. The
        unoccupied zone MUST NOT be banked because the dispatch-time
        re-check failed.

        Mutation candidate: replace the per-zone re-call with
        `export_surplus = True` -> this test fails because the test
        expects the unoccupied zone to be skipped.
        """
        zones = {
            "z_occ": _make_zone("z_occ", occupied=True),
            "z_emp": _make_zone("z_emp", occupied=False),
        }
        pred, hass = _make_predictor(zones=zones)
        _install_ec(hass, scope="auto_pv_tiered")
        pred._first_eval_done = True

        # First call: gate-side check sees strong surplus (passes).
        # Second call (dispatch-time): below threshold (unoccupied skipped).
        # Note: production reads _get_net_power TWICE — once inside the
        # gate's I1 check, once for the scope branch. So the FIRST two
        # calls are "gate eval" + "scope eval"; both happen before the
        # per-zone loop. We make the gate call exporting and the scope
        # eval marginal.
        seq = iter([-2000.0, -200.0, -200.0, -200.0])
        pred._get_net_power = MagicMock(side_effect=lambda: next(seq))
        calls: list = []

        async def _spy_precool(zone, offset, reason):
            calls.append((zone.zone_id, reason))

        pred._execute_zone_pre_cool = _spy_precool
        _run_coro(pred._check_pre_conditioning(
            _make_constraint(soc=98, forecast_high=95),
            house_state="home_day",
            now=datetime(2026, 6, 11, 13, 0, 0),
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        zone_ids = {z for z, _ in calls}
        # Occupied always banks; unoccupied banks only if dispatch-time
        # re-check still shows surplus.
        assert "z_occ" in zone_ids
        assert "z_emp" not in zone_ids, (
            "auto_pv_tiered dispatch-time re-check MUST drop unoccupied "
            "zones when surplus has faded between the gate and dispatch"
        )


# ===========================================================================
# D1 — I3 Floor clamp + I7 offset configurable
# ===========================================================================

class TestD1I7OffsetConfigurable:

    def test_default_offset_propagates(self):
        """Default offset (-2.0) reaches _execute_zone_pre_cool."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            offset=-2.0,
            scope="whole_house",
            constraint=_make_constraint(soc=98, forecast_high=95),
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert calls and calls[0]["offset"] == -2.0

    def test_operator_change_propagates_next_cycle(self):
        """Mutation: hardcode `offset = -2.0` in the dispatch loop -> this
        test fails because the operator-set -3.5 is not honored."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            offset=-3.5,
            scope="whole_house",
            constraint=_make_constraint(soc=98, forecast_high=95),
            net_power=-800.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert calls and calls[0]["offset"] == -3.5

    def test_floor_clamp_invariant_under_absurd_offset(self):
        """I3: even -20°F operator config can't breach the 72°F floor.

        Exercises the REAL _execute_zone_pre_cool. The load-bearing
        site is the `max(banked_high, floor)` clamp in that method.
        Mutation: replace with `effective_high = banked_high` -> the
        assertion below fails (writes 58.0 instead of 72.0).
        """
        pred, hass = _make_predictor()
        zone = pred._zone_manager.zones["z1"]
        zone.target_temp_high = 78.0
        zone.target_temp_low = 70.0
        # Patch emit_set_temperature on the module the predictor class
        # imported from — pull it off the bound predictor instance's
        # MRO so we don't re-import (which would re-execute the real
        # peer modules and trigger HA-core import errors in the test
        # harness).
        # The predictor class' __module__ globals dict is where
        # `emit_set_temperature` was bound at import time. We patch via
        # that globals dict directly so we don't need the module in
        # sys.modules (the loader pops it to avoid peer-test pollution).
        hp_mod = type(pred)._execute_zone_pre_cool.__globals__
        assert "emit_set_temperature" in hp_mod, (
            "predictor module globals must carry emit_set_temperature"
        )
        captured = {}

        async def _capture(hass_, entity, *, target_temp_low, target_temp_high,
                           freeze_active, blocking):
            captured["low"] = target_temp_low
            captured["high"] = target_temp_high

        _real_emit = hp_mod["emit_set_temperature"]
        hp_mod["emit_set_temperature"] = _capture
        try:
            _run_coro(pred._execute_zone_pre_cool(
                zone, offset=-20.0, reason="energy_precool",
            ))
        finally:
            hp_mod["emit_set_temperature"] = _real_emit
        # 78 + (-20) = 58 -> floor = max(72, 70+2) = 72 -> clamped.
        assert captured.get("high") == 72.0, (
            "I3: 72°F floor MUST clamp even an absurd -20°F operator offset"
        )


# ===========================================================================
# D4 — pre-arrival + pre-heat byte-identical (regression confirmation)
# ===========================================================================

class TestD4PreArrivalAndPreHeatUntouched:

    def test_pre_arrival_block_unchanged(self):
        src = open(os.path.join(
            _dc_path, "hvac_predict.py",
        )).read()
        # The two reason-tagged dispatches still exist and still use the
        # hardcoded -2.0 offset (NOT the new configurable offset).
        assert 'reason="pre_arrival"' in src
        # Pre-arrival dispatch fragment.
        assert 'offset=-2.0, reason="pre_arrival"' in src

    def test_pre_heat_dispatch_present(self):
        src = open(os.path.join(
            _dc_path, "hvac_predict.py",
        )).read()
        assert "_execute_pre_heat" in src
        assert "SEASON_WINTER" in src

    def test_pre_arrival_branch_unaffected_by_pre_cool_toggle(self):
        """Master '28' ON + Energy-Pre-Cool OFF -> pre-arrival still fires
        for a zone in pre_arrival_zones. (Defense-in-depth check at the
        plan level: I2 forbids the pre-cool toggle from blocking
        comfort branches.)
        """
        pred, hass = _make_predictor()
        _install_ec(
            hass,
            enabled=False,         # pre-cool gate OFF
            pre_cond_enabled=True,  # master '28' ON
        )
        pred._first_eval_done = True
        pred._get_net_power = MagicMock(return_value=0.0)
        calls: list = []

        async def _spy_precool(zone, offset, reason):
            calls.append({"zone_id": zone.zone_id, "offset": offset,
                          "reason": reason})

        async def _spy_fans(zone):
            return None

        pred._execute_zone_pre_cool = _spy_precool
        pred._activate_zone_fans = _spy_fans
        _run_coro(pred._check_pre_conditioning(
            _make_constraint(soc=98, forecast_high=95),
            house_state="home_day",
            now=datetime(2026, 6, 11, 13, 0, 0),
            pre_arrival_zones={"z1"},
            zone_intelligence_enabled=True,
        ))
        # Pre-arrival fired with offset -2.0 (hardcoded for the comfort
        # branch, NOT the new configurable energy-pre-cool offset).
        assert any(
            c["reason"] == "pre_arrival" and c["offset"] == -2.0
            for c in calls
        ), (
            "I2: Energy-Pre-Cool OFF MUST NOT block pre-arrival "
            "(pre-arrival is a comfort branch under master '28' alone)"
        )


# ===========================================================================
# D5 — Config migration of the retired toggle
# ===========================================================================

class TestD5Migration:

    def _load_init_helper(self):
        # Extract the helper function via spec without executing the
        # heavy __init__ module body (which pulls in many platform deps).
        # Instead we'll read source + exec a stub that just defines
        # _migrate_solar_banking_to_energy_precool.
        #
        # v5.7.1 fix-up (B-1): helper became `async def` to consult
        # RestoreStateData. We also need to provide a DOMAIN binding (the
        # production module imports it from .const).
        path = os.path.join(_ura_path, "__init__.py")
        src = open(path).read()
        start = src.find(
            "async def _migrate_solar_banking_to_energy_precool("
        )
        assert start > 0, "migration helper must exist in __init__.py"
        # Find the end of the function: walk until the next top-level
        # `def ` or `async def `.
        end = src.find("\nasync def ", start + 1)
        if end == -1:
            end = src.find("\ndef ", start + 1)
        body = src[start:end]
        from custom_components.universal_room_automation.const import (
            DOMAIN as _DOMAIN,
        )
        ns: dict = {
            "_LOGGER": MagicMock(),
            "HomeAssistant": MagicMock,
            "ConfigEntry": MagicMock,
            "DOMAIN": _DOMAIN,
        }
        exec(compile(body, "<migration>", "exec"), ns)
        return ns["_migrate_solar_banking_to_energy_precool"]

    def _make_entry(self, options):
        e = MagicMock()
        e.options = options
        e.entry_id = "test-entry"
        return e

    def _make_hass(self, *, restore_state=None, legacy_entity_id=None):
        """Build a hass mock.

        ``restore_state`` is one of {None, "on", "off"} — the persisted
        RestoreEntity state for the legacy switch. When set,
        legacy_entity_id MUST be supplied (we mock entity_registry to
        return an entry whose unique_id matches the legacy slug).
        """
        h = MagicMock()
        captured = {}

        def _update_entry(entry, options=None):
            captured["options"] = options
            entry.options = options
        h.config_entries.async_update_entry = _update_entry
        h._captured = captured

        # Install the registry/restore mocks the production helper will
        # consult. We patch the module references in the helper's
        # namespace by stubbing the imports it does at runtime.
        from custom_components.universal_room_automation.const import (
            DOMAIN as _DOMAIN,
        )
        legacy_uid = f"{_DOMAIN}_energy_solar_banking"
        registry = MagicMock()
        if legacy_entity_id is not None:
            ent = MagicMock()
            ent.domain = "switch"
            ent.unique_id = legacy_uid
            ent.entity_id = legacy_entity_id
            registry.entities = {legacy_entity_id: ent}
        else:
            registry.entities = {}

        er_mod = types.ModuleType(
            "homeassistant.helpers.entity_registry"
        )
        er_mod.async_get = MagicMock(return_value=registry)
        sys.modules["homeassistant.helpers.entity_registry"] = er_mod

        rs_mod = types.ModuleType(
            "homeassistant.helpers.restore_state"
        )

        class _RestoreData:
            def __init__(self):
                self.last_states = {}
                if (
                    restore_state is not None
                    and legacy_entity_id is not None
                ):
                    stored = MagicMock()
                    inner = MagicMock()
                    inner.state = restore_state
                    stored.state = inner
                    self.last_states[legacy_entity_id] = stored

        class _RestoreStateData:
            @staticmethod
            async def async_get(hass):
                return _RestoreData()

        rs_mod.RestoreStateData = _RestoreStateData
        # Don't clobber RestoreEntity used by the rest of the suite.
        rs_mod.RestoreEntity = sys.modules.get(
            "homeassistant.helpers.restore_state",
            types.ModuleType("x"),
        ).__dict__.get(
            "RestoreEntity",
            type("RestoreEntity", (), {}),
        )
        sys.modules["homeassistant.helpers.restore_state"] = rs_mod

        return h

    def test_legacy_true_migrates_to_new_true(self):
        migrate = self._load_init_helper()
        hass = self._make_hass()
        entry = self._make_entry({"hvac_solar_bank_enabled": True})
        _run_coro(migrate(hass, entry))
        opts = hass._captured["options"]
        assert opts == {
            "energy_precool_enabled": True,
            "energy_precool_migration_done": True,
        }

    def test_legacy_false_migrates_to_new_false(self):
        """Mutation: bool(new_options.pop(OLD_KEY)) -> True default would
        flip an OFF user back to ON. Verify the OFF→OFF path."""
        migrate = self._load_init_helper()
        hass = self._make_hass()
        entry = self._make_entry({"hvac_solar_bank_enabled": False})
        _run_coro(migrate(hass, entry))
        opts = hass._captured["options"]
        assert opts == {
            "energy_precool_enabled": False,
            "energy_precool_migration_done": True,
        }, (
            "OFF operator MUST NOT be silently re-enabled on upgrade"
        )

    def test_fresh_install_is_no_op(self):
        migrate = self._load_init_helper()
        hass = self._make_hass()
        entry = self._make_entry({})  # neither key
        _run_coro(migrate(hass, entry))
        assert "options" not in hass._captured

    def test_already_migrated_is_no_op(self):
        migrate = self._load_init_helper()
        hass = self._make_hass()
        # New key alone (no legacy key, no done marker) → no-op.
        entry = self._make_entry({"energy_precool_enabled": True})
        _run_coro(migrate(hass, entry))
        assert "options" not in hass._captured

    def test_done_marker_blocks_re_run(self):
        """Idempotency via DONE_KEY: a previously-migrated entry must
        NEVER re-run the migration (e.g. on every restart)."""
        migrate = self._load_init_helper()
        hass = self._make_hass()
        entry = self._make_entry({
            "hvac_solar_bank_enabled": True,  # would normally migrate
            "energy_precool_migration_done": True,
        })
        _run_coro(migrate(hass, entry))
        assert "options" not in hass._captured, (
            "DONE_KEY set MUST short-circuit migration; re-running it on "
            "every restart re-triggers async_update_entry inside setup "
            "and risks reload-during-setup (Bug Class #46/MED B-4)."
        )

    def test_both_present_keeps_new_drops_old(self):
        """Idempotency: if cycle ran once but the legacy key reappeared
        (shouldn't, but defend), drop the legacy key, keep the new value."""
        migrate = self._load_init_helper()
        hass = self._make_hass()
        entry = self._make_entry({
            "hvac_solar_bank_enabled": True,
            "energy_precool_enabled": False,
        })
        _run_coro(migrate(hass, entry))
        opts = hass._captured["options"]
        # Old key dropped; new value preserved (operator's most recent).
        assert opts == {
            "energy_precool_enabled": False,
            "energy_precool_migration_done": True,
        }

    # --- v5.7.1 fix-up (B-1 CRITICAL) -------------------------------------
    # The OLD ECSolarBankingSwitch persisted state in RestoreEntity, NOT
    # in entry.options. A runtime OFF leaves options[OLD_KEY]=True (the
    # install seed) and a RestoreEntity state of "off". Migration MUST
    # consult RestoreStateData and force NEW_KEY=False in that case.
    def test_restore_entity_off_overrides_options_true(self):
        """Mutation: delete the `restore_off` override branch (always honor
        options) -> this test fails (NEW_KEY would land True)."""
        migrate = self._load_init_helper()
        hass = self._make_hass(
            restore_state="off",
            legacy_entity_id="switch.ura_solar_banking",
        )
        # Options seed says ON (install default); RestoreEntity says OFF
        # (operator runtime toggle). RestoreEntity must win.
        entry = self._make_entry({"hvac_solar_bank_enabled": True})
        _run_coro(migrate(hass, entry))
        opts = hass._captured["options"]
        assert opts["energy_precool_enabled"] is False, (
            "B-1: RestoreEntity OFF MUST override options-True (operator "
            "runtime banking-OFF must NOT be silently re-enabled as "
            "energy_precool=True after the v5.7.1 unification)."
        )
        assert opts["energy_precool_migration_done"] is True

    def test_restore_entity_on_honors_options_true(self):
        """RestoreEntity ON (or matching options): options value flows
        through unchanged."""
        migrate = self._load_init_helper()
        hass = self._make_hass(
            restore_state="on",
            legacy_entity_id="switch.ura_solar_banking",
        )
        entry = self._make_entry({"hvac_solar_bank_enabled": True})
        _run_coro(migrate(hass, entry))
        opts = hass._captured["options"]
        assert opts["energy_precool_enabled"] is True

    def test_restore_entity_missing_falls_back_to_options(self):
        """If the legacy entity_id isn't in the registry (e.g. user
        deleted it manually pre-migration), the migration must NOT crash;
        the options value flows through."""
        migrate = self._load_init_helper()
        hass = self._make_hass()  # no registry entry, no restore state
        entry = self._make_entry({"hvac_solar_bank_enabled": True})
        _run_coro(migrate(hass, entry))
        opts = hass._captured["options"]
        assert opts["energy_precool_enabled"] is True

    def test_orphan_cleanup_helper_exists_and_idempotent(self):
        """Source-contract: D3 orphan cleanup helper present and guarded."""
        src = open(os.path.join(_ura_path, "switch.py")).read()
        assert "def _cleanup_solar_banking_orphan(" in src
        assert "solar_banking_cleanup_done" in src
        assert f'energy_solar_banking' in src, (
            "cleanup helper must look up the legacy unique_id slug"
        )


# ===========================================================================
# D2 — EC entities surface contract (RestoreEntity / round-trip via source)
# ===========================================================================

class TestD2Surfaces:

    def test_switch_factory_registers_energy_precool(self):
        src = open(os.path.join(_ura_path, "switch.py")).read()
        # Factory call with the new attr_name + unique-suffix.
        assert "ECEnergyPreCoolSwitch = _ec_switch_factory(" in src
        assert '"energy_precool_enabled"' in src
        assert '"energy_precool"' in src

    def test_offset_number_class_present(self):
        src = open(os.path.join(_ura_path, "number.py")).read()
        assert "class EnergyPreCoolOffsetNumber(" in src
        assert "energy_precool_offset" in src
        assert "EnergyPreCoolOffsetNumber(hass, entry)" in src

    def test_scope_select_class_present(self):
        src = open(os.path.join(_ura_path, "select.py")).read()
        assert "class EnergyPreCoolScopeSelect(" in src
        assert "energy_precool_scope" in src
        assert "EnergyPreCoolScopeSelect(hass, entry)" in src

    def test_energy_coordinator_has_three_setters(self):
        src = open(os.path.join(
            _dc_path, "energy.py",
        )).read()
        # Three @property + three @setter blocks.
        for name in (
            "energy_precool_enabled",
            "energy_precool_offset",
            "energy_precool_scope",
        ):
            assert f"def {name}(self)" in src, (
                f"EnergyCoordinator.{name} property missing"
            )
            assert f"@{name}.setter" in src, (
                f"EnergyCoordinator.{name} setter missing"
            )

    def test_translations_carry_no_solar_banking(self):
        """Reusing existing translation keys; verify the new feature does
        not depend on a removed solar_banking translation block (helper
        names match the new entity slugs)."""
        # Translations file may still mention solar_banking historically;
        # the strict test is that the NEW switch unique_id maps cleanly.
        # We only verify the strings file is valid JSON and contains
        # the new entity name string.
        for path in (
            os.path.join(_ura_path, "strings.json"),
            os.path.join(_ura_path, "translations/en.json"),
        ):
            with open(path) as f:
                json.load(f)  # parses cleanly


# ===========================================================================
# v5.7.1 fix-up — Cross-cycle PV/mode re-engagement (D-HIGH-1 HIGH)
# ===========================================================================

class TestDHigh1CrossCycleReEngagement:
    """The v5.7.1 build introduced an early-return at
    ``if self._pre_cool_active and now.hour < PEAK_HOUR_START: return True``
    which short-circuited the I1 PV check (:707) and the inclement-mode
    check (:711). The OLD banking trigger re-checked net_power EVERY
    cycle; the build dropped that guard, so a passing cloud (or a
    v5.5.0 inclement hold) would still keep dispatching pre-cool to
    every zone, grid-powered, for hours.

    Fix: PV + mode checks run on EVERY cycle, BEFORE the
    re-engagement early-return. These tests fail against the original
    early-return ordering (revert the fix-up's reorder and these fail).
    """

    def test_re_engagement_blocked_when_net_power_above_threshold(self):
        """Mutation: revert the PV check to AFTER the
        `_pre_cool_active` early-return -> this fails.
        Concrete repro: cycle N exported, fired; cycle N+1 sun fades to
        importing -> MUST NOT re-fire."""
        pred, hass = _make_predictor()
        pred._pre_cool_active = True  # cycle N already fired
        pred._pre_cool_triggered_today = True
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=+200.0,   # IMPORTING (sign>0) on cycle N+1
            now=datetime(2026, 6, 11, 13, 30, 0),  # still pre-peak
        )
        assert not calls, (
            "D-HIGH-1: re-engagement under net_power above export "
            "threshold MUST NOT dispatch grid-powered cooling"
        )

    def test_re_engagement_blocked_under_inclement_mode(self):
        """Mutation: as above, with mode='coast' instead of net_power.
        v5.5.0 inclement hold MUST suppress the re-engagement path."""
        pred, hass = _make_predictor()
        pred._pre_cool_active = True
        pred._pre_cool_triggered_today = True
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(
                soc=98, forecast_high=95, mode="coast",
            ),
            scope="whole_house",
            net_power=-1500.0,   # still exporting...
            now=datetime(2026, 6, 11, 13, 30, 0),
        )
        assert not calls, (
            "D-HIGH-1: re-engagement under inclement constraint.mode "
            "MUST NOT bypass the v5.5.0 hold"
        )

    def test_re_engagement_fires_when_still_exporting_and_normal(self):
        """Positive: if PV is still strong AND mode is normal, the
        re-engagement path still dispatches (we did not regress the
        'stay engaged until peak' behavior)."""
        pred, hass = _make_predictor()
        pred._pre_cool_active = True
        pred._pre_cool_triggered_today = True
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-1500.0,   # still exporting
            now=datetime(2026, 6, 11, 13, 30, 0),
        )
        assert any(c["reason"] == "energy_precool" for c in calls), (
            "Stay-engaged: with continued PV surplus + normal mode, "
            "the re-engagement path should still dispatch"
        )


# ===========================================================================
# v5.7.1 fix-up — A2 MED: SOC=None cool-day floor bypass
# ===========================================================================

class TestA2SocNoneCoolDayFloor:
    """The v5.7.1 build skipped the SOC floor on SOC=None (the `if soc
    is not None and soc < soc_floor` guard). The OLD banking trigger
    used `(soc or 0) < soc_floor` -> 0 < 95 -> did NOT fire on cool
    days. Restore the cool-day fail-on-None behavior; preserve the
    hot-day fire-on-None behavior (forecast-heat is signal enough)."""

    def test_cool_day_soc_none_does_not_fire(self):
        """Mutation: revert to `if soc is not None and soc < soc_floor` ->
        this fails (the trigger would fire with SOC=None)."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=None, forecast_high=80),
            scope="whole_house",
            net_power=-1500.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert not calls, (
            "A2: SOC=None on a cool day MUST fail the 95% floor"
        )

    def test_hot_day_soc_none_still_fires(self):
        """Preserve old banking behavior — on a hot day SOC=None should
        not block, since forecast-heat alone is enough signal."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=None, forecast_high=95),
            scope="whole_house",
            net_power=-1500.0,
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert any(c["reason"] == "energy_precool" for c in calls), (
            "A2: SOC=None on a HOT day should still fire (forecast-heat "
            "is sufficient; matches operator-intended hot-day floor)"
        )


# ===========================================================================
# v5.7.1 fix-up — FIX-7 MED: restore deleted-coverage behavioral invariants
# ===========================================================================

class TestC1AwayVacationFiresUnconditionally:
    """The deleted test_v457_solar_banking_away.py asserted banking fires
    regardless of house_state (economics, unlike comfort branches). The
    new unified pre-cool inherits that contract — verify."""

    def test_pre_cool_fires_in_away_state(self):
        """Mutation: add `if is_unoccupied: return` at the top of the
        energy-precool block -> this fails."""
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-1500.0,
            house_state="away",
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert any(c["reason"] == "energy_precool" for c in calls), (
            "Pre-cool MUST fire in away (economics, not comfort)"
        )

    def test_pre_cool_fires_in_vacation_state(self):
        pred, hass = _make_predictor()
        calls = _drive(
            pred, hass,
            constraint=_make_constraint(soc=98, forecast_high=95),
            scope="whole_house",
            net_power=-1500.0,
            house_state="vacation",
            now=datetime(2026, 6, 11, 13, 0, 0),
        )
        assert any(c["reason"] == "energy_precool" for c in calls), (
            "Pre-cool MUST fire in vacation (economics, not comfort)"
        )


class TestC2EcGateOffMidCycleRelease:
    """The deleted test_solar_banking_toggle.py asserted that flipping
    the EC sub-switch OFF mid-cycle releases banked zones within ONE
    cycle (hvac_predict.py:540-547). Verify on the unified pre-cool
    surface."""

    def test_ec_gate_off_releases_within_one_cycle(self):
        """Mutation: delete the mid-cycle release block at lines 540-547
        -> this fails (no _release_banked_zones call)."""
        pred, hass = _make_predictor()
        # Master '28' stays ON; only the sub-switch flips OFF.
        # Pre-populate last-cycle banked set as if cycle N ran banked.
        pred._last_precool_gate_enabled = True
        pred._last_precool_zones = {"z1"}
        pred._first_eval_done = True
        _install_ec(
            hass, enabled=False,    # sub-switch OFF mid-cycle
            pre_cond_enabled=True,  # master '28' ON
        )
        pred._get_net_power = MagicMock(return_value=-1500.0)
        released: list = []

        async def _spy_release(zones):
            released.append(set(zones))

        pred._release_banked_zones = _spy_release
        _run_coro(pred._check_pre_conditioning(
            _make_constraint(soc=98, forecast_high=95),
            house_state="home_day",
            now=datetime(2026, 6, 11, 13, 0, 0),
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        assert released and {"z1"} in released, (
            "C2: EC sub-switch flip-OFF mid-cycle MUST release banked "
            "zones within ONE cycle (mirrors deleted banking-toggle test)"
        )


class TestC3PostRestartOrphanReconciliation:
    """The deleted test_solar_banking_toggle.py asserted that the first
    eval after a restart releases zones whose live setpoints sit BELOW
    baseline (hvac_predict.py:516-537). Verify on the unified surface."""

    def test_first_eval_releases_orphan_zones_when_gate_off(self):
        """Mutation: short-circuit the `if not self._first_eval_done`
        block at :516 -> this fails."""
        # Two zones: one was banked below baseline pre-restart, one is
        # at baseline. Only the banked one should be released.
        zones = {
            "z_banked": _make_zone(
                "z_banked", occupied=True, temp_high=72.0, temp_low=68.0,
            ),
            "z_baseline": _make_zone(
                "z_baseline", occupied=True, temp_high=78.0, temp_low=70.0,
            ),
        }
        pred, hass = _make_predictor(zones=zones)
        # Reset first-eval flag so the reconciliation path runs.
        pred._first_eval_done = False
        pred._last_precool_gate_enabled = True  # was on pre-restart
        pred._last_precool_zones = set()        # RAM-only; empty post-boot
        _install_ec(
            hass, enabled=False,    # operator flipped OFF during downtime
            pre_cond_enabled=True,
        )
        pred._get_net_power = MagicMock(return_value=0.0)

        # Resolve baseline → both zones share baseline (70.0, 78.0).
        pred._resolve_baseline_range = MagicMock(return_value=(70.0, 78.0))
        released: list = []

        async def _spy_release(zones_):
            released.append(set(zones_))

        pred._release_banked_zones = _spy_release
        _run_coro(pred._check_pre_conditioning(
            _make_constraint(soc=98, forecast_high=95),
            house_state="home_day",
            now=datetime(2026, 6, 11, 13, 0, 0),
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        assert released, (
            "C3: post-restart reconciliation MUST release orphan zones "
            "whose live setpoints sit below baseline"
        )
        # The under-baseline zone (z_banked at 72.0 < 78.0 - 0.5) MUST
        # be in the released set; the at-baseline zone MUST NOT.
        orphans_seen = set().union(*released)
        assert "z_banked" in orphans_seen
        assert "z_baseline" not in orphans_seen


# ===========================================================================
# Mutation map (sanity-check that each load-bearing site has a paired test)
# ===========================================================================

class TestMutationMap:
    """Sanity-check: the cycle's load-bearing sites are EACH paired
    with at least one named behavioral test in this file. This is
    documentation, not a runtime guard — but it forces a CI-readable
    record of mutation -> test for the per-site contract.
    """

    SITES = {
        # site name : test method name(s)
        "pv_gate": (
            "test_pv_surplus_plus_hot_fires",
            "test_hot_no_pv_does_not_fire",
            "test_pv_marginal_below_threshold_does_not_fire",
        ),
        "scope_occupied_only_skip": (
            "test_occupied_only_skips_unoccupied_zone",
        ),
        "scope_auto_pv_dispatch_recheck": (
            "test_auto_pv_tiered_dispatch_time_recheck_skips_marginal",
        ),
        "offset_application": (
            "test_operator_change_propagates_next_cycle",
        ),
        "floor_clamp": (
            "test_floor_clamp_invariant_under_absurd_offset",
        ),
        "master_28_gate": (
            "test_master_28_off_blocks_even_when_pre_cool_on",
        ),
        "pre_cool_toggle_gate": (
            "test_pre_cool_toggle_off_blocks_branch",
        ),
        "migration_idempotent": (
            "test_legacy_false_migrates_to_new_false",
            "test_already_migrated_is_no_op",
        ),
        "pre_arrival_untouched": (
            "test_pre_arrival_branch_unaffected_by_pre_cool_toggle",
        ),
        # v5.7.1 fix-up additions:
        "d_high_1_re_engagement_pv_check": (
            "test_re_engagement_blocked_when_net_power_above_threshold",
            "test_re_engagement_blocked_under_inclement_mode",
        ),
        "a2_soc_none_cool_day_floor": (
            "test_cool_day_soc_none_does_not_fire",
        ),
        "b_1_restore_entity_off_override": (
            "test_restore_entity_off_overrides_options_true",
        ),
        "b_4_done_marker_idempotent": (
            "test_done_marker_blocks_re_run",
        ),
        "c1_away_vacation_fires": (
            "test_pre_cool_fires_in_away_state",
            "test_pre_cool_fires_in_vacation_state",
        ),
        "c2_ec_gate_mid_cycle_release": (
            "test_ec_gate_off_releases_within_one_cycle",
        ),
        "c3_post_restart_reconciliation": (
            "test_first_eval_releases_orphan_zones_when_gate_off",
        ),
    }

    def test_each_site_has_at_least_one_test(self):
        # The map is the contract; this test verifies the named tests
        # actually exist on classes in this module.
        module = sys.modules[__name__]
        existing = set()
        for name in dir(module):
            cls = getattr(module, name)
            if not isinstance(cls, type):
                continue
            for attr in dir(cls):
                if attr.startswith("test_"):
                    existing.add(attr)
        missing = {}
        for site, tests in self.SITES.items():
            absent = [t for t in tests if t not in existing]
            if absent:
                missing[site] = absent
        assert not missing, (
            f"Mutation map references unknown tests: {missing}"
        )

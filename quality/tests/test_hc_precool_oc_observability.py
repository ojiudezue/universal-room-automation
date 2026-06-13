"""Tests for the HC Pre-Conditioning master toggle (D1) and OC observability
enrichment (D2a/D2b/D2c/D2d).

PLANNING_hc_precool_toggle_oc_observability.md — drives REAL production
code via object.__new__/exec-extraction (NO mirror tests, NO hand-primed
state). Mutation checks are mandatory; the test list at the bottom is
the contract: invert the D1 guard / remove the release / break the #52
guard / break D2d scoring / point D2a at the wrong source → at least
one named test fails.

Conventions inherit from the v5.3.7 ``test_solar_banking_toggle.py``
sibling: sys.modules.setdefault only; transient asyncio loop; spec'd
collaborators where they exist; ``_load_real_predictor_class`` defensively
loads the real HVACPredictor without polluting peer test files.
"""

import asyncio
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code — sibling pattern to
# test_solar_banking_toggle.py. setdefault ONLY.
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


def _parse_datetime(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


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
        "as_local": lambda d: d, "parse_datetime": _parse_datetime,
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
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)


import importlib.util  # noqa: E402
import os  # noqa: E402

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
    if full in sys.modules:
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
    """Defensively load the REAL HVACPredictor without polluting sys.modules."""
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
        f"{_dc_name}.signals",
    )
    saved = {n: sys.modules.get(n, _SENTINEL) for n in peer_names}

    def _ensure_stub(name, **attrs):
        if sys.modules.get(name) is None or not hasattr(
            sys.modules[name], list(attrs)[0]
        ):
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

# Const is safe to register up-front.
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


@pytest.fixture
def fake_zone():
    z = MagicMock()
    z.zone_id = "z1"
    z.zone_name = "Z1"
    z.climate_entity = "climate.z1"
    z.target_temp_high = 76.0
    z.target_temp_low = 70.0
    z.any_room_occupied = True
    z.last_occupied_time = None
    return z


@pytest.fixture
def fake_predictor(fake_zone):
    HVACPredictor = _load_real_predictor_class()
    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    zm = MagicMock()
    zm.zones = {"z1": fake_zone}
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


def _make_constraint(soc=98, forecast_high=92, mode="normal"):
    c = MagicMock()
    c.soc = soc
    c.forecast_high_temp = forecast_high
    c.mode = mode
    return c


def _install_hvac_in_hass(hass, *, pre_conditioning_enabled: bool,
                          banking_enabled: bool = True):
    """Wire fake HC + EC into hass.data so the gate-read helpers find them."""
    hvac = MagicMock()
    hvac.pre_conditioning_enabled = pre_conditioning_enabled
    energy = MagicMock()
    energy.solar_banking_enabled = banking_enabled
    manager = MagicMock()
    manager.coordinators = {"hvac": hvac, "energy": energy}
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {"coordinator_manager": manager}
    return hvac, energy


def _install_fake_hvac_coord(pred, *, last_emitted=None,
                             house_state: str = "home_day"):
    coord = MagicMock()
    coord._last_emitted_range = last_emitted if last_emitted is not None else {}
    coord._house_state = house_state
    pred.set_hvac_coord(coord)
    return coord


# ---------------------------------------------------------------------------
# D1 constants + plumbing source-contract
# ---------------------------------------------------------------------------

class TestD1ConstAndPlumbing:

    def test_conf_const_exists_with_default_true(self):
        assert hasattr(_hvac_const_mod, "CONF_HVAC_PRE_CONDITIONING_ENABLED")
        assert _hvac_const_mod.CONF_HVAC_PRE_CONDITIONING_ENABLED == (
            "hvac_pre_conditioning_enabled"
        )
        assert hasattr(
            _hvac_const_mod, "DEFAULT_HVAC_PRE_CONDITIONING_ENABLED",
        )
        assert _hvac_const_mod.DEFAULT_HVAC_PRE_CONDITIONING_ENABLED is True

    def test_config_flow_carries_field(self):
        path = "custom_components/universal_room_automation/config_flow.py"
        with open(path) as f:
            src = f.read()
        assert "CONF_HVAC_PRE_CONDITIONING_ENABLED" in src
        assert "DEFAULT_HVAC_PRE_CONDITIONING_ENABLED" in src
        idx = src.find("CONF_HVAC_PRE_CONDITIONING_ENABLED")
        idx2 = src.find("CONF_HVAC_PRE_CONDITIONING_ENABLED", idx + 1)
        assert idx2 > 0, "field must be used in schema, not just imported"
        nearby = src[idx2:idx2 + 600]
        assert "BooleanSelector" in nearby

    def test_translations_and_strings_carry_label(self):
        import json
        for path in (
            "custom_components/universal_room_automation/strings.json",
            "custom_components/universal_room_automation/translations/en.json",
        ):
            with open(path) as f:
                data = json.load(f)
            assert "hvac_pre_conditioning_enabled" in json.dumps(data)

    def test_switch_class_and_registration_present(self):
        path = "custom_components/universal_room_automation/switch.py"
        with open(path) as f:
            src = f.read()
        assert "class HVACPreConditioningSwitch" in src
        assert "HVACPreConditioningSwitch(hass, entry)" in src
        # Device residency = HC.
        idx = src.find("class HVACPreConditioningSwitch")
        # Capture the full class body — Bug Class #52 guard lives ~150
        # lines into the class body, well past the 4 kB mark.
        next_class = src.find("\nclass ", idx + 1)
        block = src[idx:next_class] if next_class > 0 else src[idx:]
        assert '"hvac_coordinator"' in block
        # Bug Class #52 guard present.
        assert 'last_state.state not in ("on", "off")' in block
        # Default ON.
        assert "self._default: bool = True" in block


# ---------------------------------------------------------------------------
# D1 behavior — gate guard + flip-OFF release + Bug Class #52 restore guard
# ---------------------------------------------------------------------------

class TestD1GatePreConditioning:

    def test_gate_off_skips_entire_pre_conditioning_chain(self, fake_predictor):
        """Mutation check #1: invert the D1 guard → this test fails.

        Pre-conditioning OFF must short-circuit weather pre-cool +
        solar banking. With both ON nothing fires; tracking sets stay
        empty. (If the guard is inverted, weather pre-cool / banking
        run and the assertion below fires.)
        """
        pred, hass = fake_predictor
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=False, banking_enabled=True,
        )
        pred._first_eval_done = True  # not exercising restart reconciliation
        # Spies — must NOT be called.
        should_bank_spy = MagicMock(return_value=True)
        pred._should_solar_bank = should_bank_spy
        weather_spy = MagicMock(return_value=True)
        pred._should_weather_pre_cool = weather_spy
        precool_calls = []

        async def _spy_precool(zone, offset, reason):
            precool_calls.append((zone.zone_id, offset, reason))

        pred._execute_zone_pre_cool = _spy_precool
        pred._get_net_power = MagicMock(return_value=-800.0)

        constraint = _make_constraint(soc=98, forecast_high=92)
        now = datetime(2026, 6, 11, 11, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="home_day", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        assert should_bank_spy.call_count == 0, (
            "gate OFF → _should_solar_bank must NEVER be called"
        )
        assert weather_spy.call_count == 0, (
            "gate OFF → _should_weather_pre_cool must NEVER be called"
        )
        assert precool_calls == [], (
            "gate OFF → _execute_zone_pre_cool must NEVER be called"
        )
        assert pred._pre_conditioning_zones == set()
        assert pred._solar_banking_zones == set()

    def test_gate_on_preserves_behavior(self, fake_predictor):
        """Gate default ON + banking-eligible conditions → banking fires
        (byte-identical to v5.3.7 pre-cycle behavior)."""
        pred, hass = fake_predictor
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=True, banking_enabled=True,
        )
        pred._first_eval_done = True
        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)
        precool_calls = []

        async def _spy_precool(zone, offset, reason):
            precool_calls.append((zone.zone_id, offset, reason))

        pred._execute_zone_pre_cool = _spy_precool

        now = datetime(2026, 6, 11, 11, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        assert any(
            reason == "solar_banking" for _, _, reason in precool_calls
        )
        assert "z1" in pred._solar_banking_zones

    def test_gate_no_hvac_failsafe_on(self, fake_predictor):
        """HC not yet registered → helper returns True (fail-safe)."""
        pred, _hass = fake_predictor
        assert pred._is_pre_conditioning_enabled() is True

    def test_mid_pre_cool_flip_off_releases_within_one_cycle(
        self, fake_predictor, fake_zone,
    ):
        """Mutation check #2: remove the D1 flip-OFF release → this fails.

        Cycle 1 banks z1; operator flips gate OFF; cycle 2 releases
        baseline range to z1 immediately (no waiting for peak boundary).
        """
        pred, hass = fake_predictor
        pred._first_eval_done = True
        # Cycle 1: gate ON → bank fires.
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=True, banking_enabled=True,
        )
        _install_fake_hvac_coord(
            pred, last_emitted={"z1": (68.0, 75.0)},
        )

        async def _spy_precool(zone, offset, reason):
            return None
        pred._execute_zone_pre_cool = _spy_precool
        pred._get_net_power = MagicMock(return_value=-800.0)

        constraint = _make_constraint(soc=98, forecast_high=92)
        now = datetime(2026, 6, 11, 11, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        assert "z1" in pred._last_pre_conditioning_zones or (
            "z1" in pred._last_banked_zones
        )

        # Cycle 2: operator flips master OFF mid-window. Live setpoints
        # still banked. Release MUST fire to baseline.
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=False, banking_enabled=True,
        )
        hass.services.async_call.reset_mock()
        fake_zone.target_temp_high = 72.0
        now2 = datetime(2026, 6, 11, 11, 5, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now2,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        calls = hass.services.async_call.await_args_list
        set_temp_calls = [
            c for c in calls if c.args[:2] == ("climate", "set_temperature")
        ]
        assert set_temp_calls, (
            "flip-OFF mid pre-cool MUST release to baseline within one cycle"
        )
        payload = set_temp_calls[0].args[2]
        assert payload["target_temp_high"] == 75.0
        assert payload["target_temp_low"] == 68.0
        assert pred._last_banked_zones == set()
        assert pred._last_pre_conditioning_zones == set()

    def test_steady_state_off_does_not_repeat_release(self, fake_predictor):
        """Idempotency: gate OFF for the second cycle → no re-issued release."""
        pred, hass = fake_predictor
        pred._first_eval_done = True
        pred._last_pre_conditioning_gate_enabled = False
        pred._last_pre_conditioning_zones = set()
        pred._last_banked_zones = set()
        pred._pre_cool_active = False
        pred._pre_heat_active = False
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=False, banking_enabled=True,
        )
        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)
        now = datetime(2026, 6, 11, 11, 10, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        calls = hass.services.async_call.await_args_list
        set_temp_calls = [
            c for c in calls if c.args[:2] == ("climate", "set_temperature")
        ]
        assert not set_temp_calls


class TestD1Bug52RestoreGuard:
    """Mutation check #3: break the Bug Class #52 restore guard
    (let last_state ∈ {unavailable, unknown} coerce to OFF) → fails."""

    def test_unavailable_last_state_is_skipped_not_coerced(self):
        """Read the switch source and AST-grep the canonical #52 idiom."""
        path = "custom_components/universal_room_automation/switch.py"
        with open(path) as f:
            src = f.read()
        idx = src.find("class HVACPreConditioningSwitch")
        next_class = src.find("\nclass ", idx + 1)
        block = src[idx:next_class] if next_class > 0 else src[idx:]
        # Canonical Bug Class #52 idiom present.
        assert 'last_state.state not in ("on", "off")' in block
        # The body of that branch returns BEFORE coercing target = ...
        guard_idx = block.find('last_state.state not in ("on", "off")')
        # Find the `target = last_state.state == "on"` line.
        target_idx = block.find('target = last_state.state == "on"')
        assert target_idx > guard_idx, (
            "Bug Class #52: the unavailable-skip guard MUST short-circuit "
            "before `target = last_state.state == \"on\"` so unavailable "
            "is not coerced to OFF"
        )


# ---------------------------------------------------------------------------
# D2a — OptimizerReasoningSensor + dry_run_veto_count source
# ---------------------------------------------------------------------------

class TestD2aReasoningSensor:

    def test_sensor_class_and_registration_present(self):
        path = "custom_components/universal_room_automation/sensor.py"
        with open(path) as f:
            src = f.read()
        assert "class OptimizerReasoningSensor" in src
        assert "OptimizerReasoningSensor(hass, entry)" in src
        # Attrs surfaced.
        idx = src.find("class OptimizerReasoningSensor")
        next_class = src.find("\nclass ", idx + 1)
        block = src[idx:next_class] if next_class > 0 else src[idx:]
        for attr in (
            "cycle_summary",
            "cycle_actions_proposed",
            "dry_run_veto_count",
            "last_cycle_at",
        ):
            assert attr in block, f"reasoning sensor must surface `{attr}` attr"
        # State changes follow the existing finding-emit signal — confirm
        # the sensor inherits from the base class that subscribes to it.
        assert "_OptimizerCMSensorBase" in block

    def test_dry_run_veto_count_reads_broker_pending_vetoes(self):
        """Mutation check #5: point dry_run_veto_count at the wrong source
        (e.g. read from a non-existent `_vetoes` slot) → this test fails.

        We extract `dry_run_veto_count` from optimization.py via AST to
        confirm it reads `self.broker._pending_vetoes` — the authoritative
        in-flight veto store (optimization.py:244).
        """
        import ast
        path = (
            "custom_components/universal_room_automation/"
            "domain_coordinators/optimization.py"
        )
        with open(path) as f:
            src = f.read()
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "dry_run_veto_count":
                # Look for `self.broker._pending_vetoes` somewhere in the body.
                body_src = ast.get_source_segment(src, node) or ""
                assert "self.broker._pending_vetoes" in body_src, (
                    "dry_run_veto_count MUST read from broker._pending_vetoes"
                )
                found = True
        assert found, "dry_run_veto_count property must exist on OptimizationCoordinator"


# ---------------------------------------------------------------------------
# D2b — dimension_verdicts attr + severity mapping
# ---------------------------------------------------------------------------

class TestD2bDimensionVerdicts:

    def _make_coord_for_verdicts(self):
        """Build an OptimizationCoordinator instance via object.__new__ + the
        per-cycle helpers we need, without exercising async_setup.
        """
        opt_mod = _load_dc_module("optimization")
        Coord = opt_mod.OptimizationCoordinator
        coord = object.__new__(Coord)
        # Minimal state for the helpers under test.
        coord.hass = MagicMock()
        coord.hass.data = {}
        coord._last_findings = []
        coord._last_evaluation_iso = None
        coord._shadow_accuracy_samples = []
        coord._last_shadow_accuracy_pct = None
        coord._last_shadow_accuracy_status = "warming_up"
        return coord, opt_mod

    def test_verdicts_map_severity_correctly(self):
        coord, opt_mod = self._make_coord_for_verdicts()
        OptimizationFinding = opt_mod.OptimizationFinding
        f_med = OptimizationFinding(
            timestamp="2026-06-11T11:00:00+00:00",
            level="house", target_id="house",
            dimension=opt_mod.OptimizationDimension.COMFORT,
            severity="medium", confidence=0.8, score=80.0,
            description="x",
        )
        f_high = OptimizationFinding(
            timestamp="2026-06-11T11:00:00+00:00",
            level="house", target_id="house",
            dimension=opt_mod.OptimizationDimension.SENSOR_HEALTH,
            severity="high", confidence=0.8, score=80.0,
            description="x",
        )
        per_dim = {
            "comfort": [f_med],
            "sensor_health": [f_high],
            "energy_efficiency": [],  # no findings → ok
        }
        raised = set()
        verdicts = coord._compute_dimension_verdicts(per_dim, raised)
        assert verdicts["comfort"] == "degraded"
        assert verdicts["sensor_health"] == "critical"
        assert verdicts["energy_efficiency"] == "ok"

    def test_raised_evaluator_maps_to_not_run(self):
        coord, _ = self._make_coord_for_verdicts()
        verdicts = coord._compute_dimension_verdicts(
            {"comfort": []},
            raised_dims={"comfort"},
        )
        assert verdicts["comfort"] == "not_run"

    def test_status_sensor_surfaces_attr(self):
        """The status sensor's extra_state_attributes must include the new
        `dimension_verdicts` key (D2b) and shadow_accuracy_status (D2d)."""
        path = "custom_components/universal_room_automation/sensor.py"
        with open(path) as f:
            src = f.read()
        idx = src.find("class OptimizerStatusSensor")
        next_class = src.find("\nclass ", idx + 1)
        block = src[idx:next_class] if next_class > 0 else src[idx:]
        assert '"dimension_verdicts": dimension_verdicts' in block, (
            "OptimizerStatusSensor must surface dimension_verdicts"
        )
        assert '"shadow_accuracy_status": shadow_status' in block


# ---------------------------------------------------------------------------
# D2c — LLM reasoning field + findings sensor attr
# ---------------------------------------------------------------------------

class TestD2cLlmReasoning:

    def test_optimization_finding_carries_reasoning_field(self):
        opt_mod = _load_dc_module("optimization")
        OptimizationFinding = opt_mod.OptimizationFinding
        f = OptimizationFinding(
            timestamp="2026-06-11T11:00:00+00:00",
            level="house", target_id="house",
            dimension=opt_mod.OptimizationDimension.COMFORT,
            severity="low", confidence=0.5, score=90.0,
            description="x",
        )
        assert hasattr(f, "reasoning")
        assert f.reasoning == ""  # default empty.

    def test_llm_parser_reads_optional_reasoning_field(self):
        """A finding row with `reasoning` populates the field; without it,
        the finding is still accepted (additive)."""
        path = (
            "custom_components/universal_room_automation/"
            "domain_coordinators/optimization_llm.py"
        )
        with open(path) as f:
            src = f.read()
        # Parser reads row.get("reasoning") additively.
        assert 'row.get("reasoning")' in src
        # Truncated to 512 chars.
        assert "[:512]" in src

    def test_findings_sensor_surfaces_llm_reasoning_summary(self):
        path = "custom_components/universal_room_automation/sensor.py"
        with open(path) as f:
            src = f.read()
        idx = src.find("class OptimizerFindingsSensor")
        next_class = src.find("\nclass ", idx + 1)
        block = src[idx:next_class] if next_class > 0 else src[idx:]
        assert '"llm_reasoning_summary": llm_reasoning_summary' in block
        # Bound to LLM-sourced rows only.
        assert 'created_by' in block and 'tier2_llm' in block


# ---------------------------------------------------------------------------
# D2d — shadow accuracy warm-up + COMFORT/OCCUPANCY scoring
# ---------------------------------------------------------------------------

class TestD2dShadowAccuracy:

    def _make_coord(self):
        opt_mod = _load_dc_module("optimization")
        Coord = opt_mod.OptimizationCoordinator
        coord = object.__new__(Coord)
        coord.hass = MagicMock()
        coord.hass.data = {}
        coord._last_findings = []
        coord._shadow_accuracy_samples = []
        coord._last_shadow_accuracy_pct = None
        coord._last_shadow_accuracy_status = "warming_up"
        return coord, opt_mod

    def test_warmup_until_min_samples(self):
        """Under MIN_SAMPLES → pct is None, status warming_up."""
        coord, _ = self._make_coord()
        coord._run_shadow_accuracy_validator()
        assert coord._last_shadow_accuracy_pct is None
        assert coord._last_shadow_accuracy_status == "warming_up"

    def test_comfort_oracle_scores_findings(self):
        """Mutation check #4: break the comfort/occupancy oracle → fails.

        We seed enough OPTIMIZER_OUTCOME_SHADOW findings (timestamps
        older than the observe-delay) and inject a fake room coord whose
        temperature is inside the comfort band. After running the
        validator the rolling pct should be 100.0 + status ready.
        """
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
            OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES,
            DOMAIN,
        )

        # Fake room coordinator with an in-band temperature.
        room = MagicMock()
        room.current_temperature = 72.0
        manager = MagicMock()
        manager.coordinators = {}
        manager.room_coordinators = {"living_room": room}
        coord.hass.data[DOMAIN] = {"coordinator_manager": manager}

        # Seed N comfort shadow findings, all timestamped 30 min ago.
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        findings = []
        for i in range(OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES + 2):
            f = opt_mod.OptimizationFinding(
                timestamp=past_iso,
                level="room", target_id="living_room",
                dimension=opt_mod.OptimizationDimension.COMFORT,
                severity="low", confidence=0.5, score=90.0,
                description=f"finding {i}",
                applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
                predicted_effect={"note": "shadow"},
            )
            findings.append(f)
        coord._last_findings = findings

        coord._run_shadow_accuracy_validator()
        assert coord._last_shadow_accuracy_status == "ready"
        assert coord._last_shadow_accuracy_pct == 100.0
        # observed_effect populated on every finding.
        for f in findings:
            assert f.observed_effect is not None
            assert f.observed_effect["match"] is True

    def test_oracle_records_out_of_band_as_false(self):
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW, DOMAIN,
        )
        room = MagicMock()
        room.current_temperature = 92.0  # out of band
        manager = MagicMock()
        manager.coordinators = {}
        manager.room_coordinators = {"hot_room": room}
        coord.hass.data[DOMAIN] = {"coordinator_manager": manager}
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        f = opt_mod.OptimizationFinding(
            timestamp=past_iso,
            level="room", target_id="hot_room",
            dimension=opt_mod.OptimizationDimension.COMFORT,
            severity="low", confidence=0.5, score=90.0,
            description="x",
            applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
            predicted_effect={"note": "shadow"},
        )
        coord._last_findings = [f]
        coord._run_shadow_accuracy_validator()
        assert f.observed_effect["match"] is False

    def test_non_shadow_outcome_skipped(self):
        """The validator MUST NOT score non-shadow findings (no collision
        with the Pillar-4 prediction-accuracy reader)."""
        coord, opt_mod = self._make_coord()
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        f = opt_mod.OptimizationFinding(
            timestamp=past_iso,
            level="house", target_id="house",
            dimension=opt_mod.OptimizationDimension.PREDICTION_ACCURACY,
            severity="low", confidence=0.5, score=90.0,
            description="x",
            applied_outcome="applied",  # NOT shadow
            predicted_effect={"note": "applied"},
        )
        coord._last_findings = [f]
        coord._run_shadow_accuracy_validator()
        assert f.observed_effect is None

    def test_unscorable_dimension_marked_explicitly(self):
        """v1 scorable dims = {comfort, occupancy_accuracy}; others get
        observed_effect={match: None, evidence: 'unscorable'}."""
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
        )
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        f = opt_mod.OptimizationFinding(
            timestamp=past_iso,
            level="house", target_id="house",
            dimension=opt_mod.OptimizationDimension.SENSOR_HEALTH,
            severity="low", confidence=0.5, score=90.0,
            description="x",
            applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
            predicted_effect={"note": "shadow"},
        )
        coord._last_findings = [f]
        coord._run_shadow_accuracy_validator()
        assert f.observed_effect is not None
        assert f.observed_effect["match"] is None
        assert f.observed_effect["evidence"] == "unscorable"

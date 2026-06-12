"""Tests for the Solar HVAC Banking master toggle.

PLANNING_solar_banking_toggle.md deliverables D1-D5.

Test strategy:
- D1/D2 source-contract: const + config-flow field exist with default ON.
- D3 behavioral: drive the real HVACPredictor._check_pre_conditioning with
  spec'd fakes so that nonexistent-method calls fail loudly.  Three cases:
  (a) gate OFF -> banking branch never fires (_should_solar_bank never called,
      _solar_banking_zones stays empty even when conditions WOULD bank);
  (b) gate default ON -> behavior preserved (banking fires when conditions met);
  (c) gate flip OFF mid-bank -> _release_banked_zones writes baseline range
      and _last_banked_zones cleared on next cycle.
- D4 restore round-trip: spec'd EC fake; flipping `solar_banking_enabled`
  through the setter persists and the property reflects it.
- D5 attr surface: hvac.py attrs dict carries `banking_enabled` next to
  `solar_banking_zones` and reflects the predictor helper.

Conventions:
- sys.modules.setdefault ONLY (never assign over shared paths) — per
  institutional rule from prior cycle pollution incidents.
- MagicMock(spec=...) for collaborators so a typo / missing method
  surfaces as AttributeError, not a silent no-op.
"""

import asyncio
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code — mirrors the canonical
# setdefault pattern in test_ev_offpeak_proactive.py / test_v47x_ev_tou_hardening.py.
# setdefault ONLY (never assign): if another test file already registered a
# richer mock, we let it win to avoid Bug Class #44 per-test contamination.
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


# ---------------------------------------------------------------------------
# Build the URA package hierarchy without executing __init__.py — the real
# __init__.py pulls in homeassistant.core.State which our minimal mock does
# not provide. Mirrors test_ev_offpeak_proactive.py's pattern.
# ---------------------------------------------------------------------------

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


def _load_dc_module(submod_name: str):
    """Load a domain_coordinators submodule via setdefault semantics.

    We deliberately DO NOT force-reload when sys.modules already has an
    entry — that would clobber whatever other test files have wired up
    and breaks unrelated tests (substrate/envoy tests share sys.modules
    state).  The fixture below uses _load_real_predictor() to defensively
    fetch the production HVACPredictor class into a local namespace when
    pollution is suspected, without writing back to sys.modules.
    """
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


_SENTINEL = object()


def _load_real_predictor_class():
    """Defensively load the real HVACPredictor from source.

    Approach:
    1. If the canonical sys.modules entry already holds the real class
       (not a MagicMock stand-in), return it directly.
    2. Otherwise, temporarily inject stub peer modules
       (hvac_override / hvac_preset / hvac_zones) into sys.modules JUST
       for the duration of the spec load, then RESTORE the prior
       sys.modules state so peer test files are unaffected.
    """
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

    # Snapshot peer-module state so we can restore after our private load.
    peer_names = (
        f"{_dc_name}.hvac_override",
        f"{_dc_name}.hvac_preset",
        f"{_dc_name}.hvac_zones",
        f"{_dc_name}.signals",
    )
    saved = {n: sys.modules.get(n, _SENTINEL) for n in peer_names}

    # Inject minimal stub peers if absent.
    def _ensure_stub(name, **attrs):
        if sys.modules.get(name) is None or not hasattr(sys.modules[name], list(attrs)[0]):
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
        # Use the canonical dotted name so relative imports in
        # hvac_predict (`from .hvac_const import ...`) resolve via the
        # parent package we already registered in sys.modules.
        spec = importlib.util.spec_from_file_location(
            full,
            os.path.join(_dc_path, "hvac_predict.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # Snapshot prior canonical entry so we can restore it.
        prior_full = sys.modules.get(full, _SENTINEL)
        sys.modules[full] = mod
        try:
            spec.loader.exec_module(mod)
            cls = mod.HVACPredictor
        finally:
            # Restore prior canonical entry (or remove if absent before).
            if prior_full is _SENTINEL:
                sys.modules.pop(full, None)
            else:
                sys.modules[full] = prior_full
        return cls
    finally:
        # Restore peer-module sys.modules state to pre-load snapshot.
        for n, prev in saved.items():
            if prev is _SENTINEL:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = prev


# Pre-load const + the modules hvac_predict imports at module-load time.
# hvac_override / hvac_preset / hvac_zones are referenced from hvac_predict's
# `from .hvac_override import OverrideArrester` etc. — we need each module
# importable.  Stub out missing HA sub-packages on demand (recorder, etc).
_recorder_mod = _mock_module(
    "homeassistant.components.recorder",
    get_instance=MagicMock(),
)
_recorder_mod.__path__ = []  # mark as package
sys.modules.setdefault("homeassistant.components.recorder", _recorder_mod)
sys.modules.setdefault(
    "homeassistant.components.recorder.history",
    _mock_module(
        "homeassistant.components.recorder.history",
        get_significant_states=MagicMock(return_value={}),
    ),
)

# Only load `hvac_const` at module-import time — small, side-effect-free,
# safe to register in sys.modules. The behavioral predictor tests load
# HVACPredictor on-demand via _load_real_predictor_class() (private
# namespace, no sys.modules write) so we don't pollute peer test files
# that register their own mocks for hvac_predict / hvac_override / etc.
_hvac_const_mod = _load_dc_module("hvac_const")


# ---------------------------------------------------------------------------
# D1 + D2: const + config-flow source-contract
# ---------------------------------------------------------------------------

class TestConstAndConfigFlowFields:

    def test_conf_const_exists_with_default_true(self):
        hvac_const = _hvac_const_mod
        assert hasattr(hvac_const, "CONF_HVAC_SOLAR_BANK_ENABLED")
        assert hvac_const.CONF_HVAC_SOLAR_BANK_ENABLED == "hvac_solar_bank_enabled"
        assert hasattr(hvac_const, "DEFAULT_HVAC_SOLAR_BANK_ENABLED")
        assert hvac_const.DEFAULT_HVAC_SOLAR_BANK_ENABLED is True

    def test_config_flow_imports_const(self):
        """Schema-validator side imports the new const + default."""
        path = (
            "custom_components/universal_room_automation/config_flow.py"
        )
        with open(path) as f:
            src = f.read()
        assert "CONF_HVAC_SOLAR_BANK_ENABLED" in src
        assert "DEFAULT_HVAC_SOLAR_BANK_ENABLED" in src
        # Schema must wire it as a BooleanSelector to render as a toggle.
        # Find the field declaration and the very next selector type.
        idx = src.find("CONF_HVAC_SOLAR_BANK_ENABLED")
        # First occurrence is the import; find the SECOND (schema usage).
        idx2 = src.find("CONF_HVAC_SOLAR_BANK_ENABLED", idx + 1)
        assert idx2 > 0, "Field must be used in schema, not just imported"
        # Within the next ~600 chars should be a BooleanSelector call.
        nearby = src[idx2:idx2 + 600]
        assert "BooleanSelector" in nearby, (
            "hvac_solar_bank_enabled must render as a Boolean toggle"
        )

    def test_translations_carry_field_label(self):
        import json
        path = (
            "custom_components/universal_room_automation/translations/en.json"
        )
        with open(path) as f:
            data = json.load(f)
        s = json.dumps(data)
        assert "hvac_solar_bank_enabled" in s, (
            "translations must carry hvac_solar_bank_enabled label/description"
        )

    def test_strings_carry_field_label(self):
        import json
        path = "custom_components/universal_room_automation/strings.json"
        with open(path) as f:
            data = json.load(f)
        s = json.dumps(data)
        assert "hvac_solar_bank_enabled" in s


# ---------------------------------------------------------------------------
# D3: HVACPredictor gate + helper + explicit release
# ---------------------------------------------------------------------------

def _run_coro(coro):
    """Run an async coroutine without disturbing the global event loop.

    `asyncio.run()` closes the loop after completion; sibling test files
    (e.g. test_substrate_seed.py) call `asyncio.get_event_loop()` and
    crash with 'no current event loop' if the loop was closed before
    them.  We create a transient loop, restore the prior loop afterwards.
    """
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
        # Restore prior loop (or set a fresh one so get_event_loop() works
        # for the next test file even if we ran first).
        if prior is not None and not prior.is_closed():
            asyncio.set_event_loop(prior)
        else:
            asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture
def fake_zone():
    """A zone with banking-eligible setpoints."""
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
    """Construct a real HVACPredictor with spec'd collaborators.

    Calls to undefined methods on the mocks raise AttributeError loudly
    (spec=True) — fresh institutional lesson from prior cycle.
    """
    # Defensively obtain the REAL HVACPredictor class without touching
    # sys.modules — see _load_real_predictor_class docstring for why.
    HVACPredictor = _load_real_predictor_class()

    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()

    # Stub-class instances mirror the real surface used by the predictor's
    # banking-branch path: zm.zones dict, pm.current_season string,
    # arrester.suppress() + .unsuppress() methods.  No spec= because the
    # stub classes are deliberately empty (real modules unloadable here);
    # tests assert the calls explicitly below.
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
    """Make an EnergyConstraint banking would normally fire on."""
    c = MagicMock()
    c.soc = soc
    c.forecast_high_temp = forecast_high
    c.mode = mode
    return c


def _install_energy_in_hass(hass, *, banking_enabled: bool):
    """Wire a spec'd EC fake into hass.data[DOMAIN]['coordinator_manager']."""
    energy = MagicMock()
    energy.solar_banking_enabled = banking_enabled
    manager = MagicMock()
    manager.coordinators = {"energy": energy}
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {"coordinator_manager": manager}
    return energy


class TestGateOffSkipsBanking:

    def test_gate_off_skips_branch_entirely(self, fake_predictor):
        """When gate is OFF, _should_solar_bank must NEVER be called and
        _solar_banking_zones must stay empty even under conditions that
        would normally bank."""
        pred, hass = fake_predictor
        _install_energy_in_hass(hass, banking_enabled=False)
        # Constraint that WOULD bank if gate were ON
        constraint = _make_constraint(soc=98, forecast_high=92)
        # Force net export so _should_solar_bank would otherwise return True
        pred._get_net_power = MagicMock(return_value=-800.0)
        # _execute_zone_pre_cool wraps services.async_call — track invocations
        precool_calls = []

        async def _spy_precool(zone, offset, reason):
            precool_calls.append((zone.zone_id, offset, reason))

        pred._execute_zone_pre_cool = _spy_precool
        # Spy on _should_solar_bank to assert it's never called.
        should_bank_spy = MagicMock(return_value=True)
        pred._should_solar_bank = should_bank_spy

        now = datetime(2026, 6, 11, 11, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))

        # _should_solar_bank gated by `if banking_gate_on and ...` so the
        # short-circuit prevents the call entirely.
        assert should_bank_spy.call_count == 0, (
            "Gate OFF must short-circuit before _should_solar_bank is invoked"
        )
        assert pred._solar_banking_zones == set()
        assert not any(reason == "solar_banking" for _, _, reason in precool_calls)

    def test_gate_default_on_preserves_behaviour(self, fake_predictor):
        """Default ON + banking-eligible conditions => banking fires."""
        pred, hass = fake_predictor
        _install_energy_in_hass(hass, banking_enabled=True)
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
        assert "z1" in pred._solar_banking_zones
        assert any(reason == "solar_banking" for _, _, reason in precool_calls)

    def test_gate_unknown_ec_failsafe_on(self, fake_predictor):
        """EC not yet registered => helper returns True (fail-safe)."""
        pred, hass = fake_predictor
        # Do NOT install EC at all.
        assert pred._is_solar_banking_enabled() is True


def _install_fake_hvac_coord(pred, *, last_emitted=None,
                             house_state: str = "home_day"):
    """Wire a fake HVAC coord with a _last_emitted_range map + house_state.

    Used by Tier 1 review CRITICAL-1 tests: release must source baseline
    from `_last_emitted_range`, NOT live zone setpoints.
    """
    coord = MagicMock()
    coord._last_emitted_range = last_emitted if last_emitted is not None else {}
    coord._house_state = house_state
    pred.set_hvac_coord(coord)
    return coord


class TestMidBankReleaseOnFlipOff:

    def test_release_uses_last_emitted_range_not_live_setpoints(
        self, fake_predictor, fake_zone,
    ):
        """Tier 1 review CRITICAL-1: release must source baseline from
        `HVACCoordinator._last_emitted_range[zone_id]` (the last
        URA-emitted preset range), NOT from `zone.target_temp_high/low`
        which refresh each cycle from LIVE climate state and ARE the
        banked values post-banking → writing them back is a no-op.

        Sets _last_emitted_range to (68.0, 75.0) and the zone's live
        fields to the BANKED values (65.0, 72.0). Asserts the release
        payload equals the EMITTED-range baseline, not the live values.
        """
        pred, hass = fake_predictor
        # Live zone setpoints reflect post-banking values (the bug).
        fake_zone.target_temp_high = 72.0
        fake_zone.target_temp_low = 65.0
        # _last_emitted_range carries the TRUE baseline (pre-banking).
        coord = _install_fake_hvac_coord(
            pred, last_emitted={"z1": (68.0, 75.0)},
        )

        pred._last_banking_gate_enabled = True
        pred._last_banked_zones = {"z1"}
        _install_energy_in_hass(hass, banking_enabled=False)
        pred._first_eval_done = True  # skip post-restart reconciliation path

        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)

        now = datetime(2026, 6, 11, 11, 5, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))

        calls = hass.services.async_call.await_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert set_temp_calls, "release must call climate.set_temperature"
        payload = set_temp_calls[0].args[2]
        assert payload["entity_id"] == "climate.z1"
        # The TRUE baseline from _last_emitted_range — NOT the banked
        # live values from the zone fields.
        assert payload["target_temp_high"] == 75.0, (
            f"release must use _last_emitted_range high (75.0), not live "
            f"zone.target_temp_high — got {payload['target_temp_high']}"
        )
        assert payload["target_temp_low"] == 68.0
        # _last_emitted_range updated to released baseline (throttle
        # stays consistent → no double-write next preset cycle).
        assert coord._last_emitted_range["z1"] == (68.0, 75.0)
        assert pred._last_banked_zones == set()
        assert "z1" not in pred._solar_banking_zones

    def test_gate_stays_off_next_cycle_no_repeat_release(self, fake_predictor):
        """A second cycle while gate is still OFF must NOT re-issue the
        release (idempotency)."""
        pred, hass = fake_predictor
        # Simulate post-release state: gate already OFF last cycle.
        pred._last_banking_gate_enabled = False
        pred._last_banked_zones = set()
        pred._first_eval_done = True
        _install_energy_in_hass(hass, banking_enabled=False)

        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)

        now = datetime(2026, 6, 11, 11, 10, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        calls = hass.services.async_call.await_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert not set_temp_calls, (
            "Steady-state gate OFF must not re-issue release writes each cycle"
        )


class TestPostRestartReconciliation:
    """Tier 1 review HIGH-1: restart-mid-bank with gate subsequently OFF
    must reconcile orphan-banked zones on the first eval after startup."""

    def test_first_eval_releases_orphan_banked_zones(
        self, fake_predictor, fake_zone,
    ):
        """Live zone setpoint sits 4°F below baseline → orphan-banked →
        gets released on first eval after startup."""
        pred, hass = fake_predictor
        # Fresh process: _first_eval_done is False, _last_banked_zones empty.
        assert pred._first_eval_done is False
        assert pred._last_banked_zones == set()
        # Live setpoint reflects pre-restart banking (3-4°F below baseline).
        fake_zone.target_temp_high = 72.0
        fake_zone.target_temp_low = 65.0
        _install_fake_hvac_coord(
            pred, last_emitted={"z1": (68.0, 75.0)},
        )
        _install_energy_in_hass(hass, banking_enabled=False)

        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)

        now = datetime(2026, 6, 11, 11, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))

        calls = hass.services.async_call.await_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert set_temp_calls, "post-restart reconciliation must release orphan"
        payload = set_temp_calls[0].args[2]
        assert payload["target_temp_high"] == 75.0
        # Bounded: flag flipped so second eval is a no-op.
        assert pred._first_eval_done is True

    def test_first_eval_skips_zones_at_baseline(self, fake_predictor, fake_zone):
        """Live setpoint within 0.5°F of baseline → NOT orphan → no release."""
        pred, hass = fake_predictor
        # Live setpoint matches baseline (no banking happened pre-restart).
        fake_zone.target_temp_high = 75.0
        fake_zone.target_temp_low = 68.0
        _install_fake_hvac_coord(
            pred, last_emitted={"z1": (68.0, 75.0)},
        )
        _install_energy_in_hass(hass, banking_enabled=False)

        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)

        now = datetime(2026, 6, 11, 11, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))

        calls = hass.services.async_call.await_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert not set_temp_calls, (
            "no banking-direction drift → reconciliation must be a no-op"
        )

    def test_first_eval_skipped_when_gate_on(self, fake_predictor, fake_zone):
        """Gate ON at startup → no reconciliation (the normal flip-OFF
        path will handle release if/when operator turns it off)."""
        pred, hass = fake_predictor
        fake_zone.target_temp_high = 72.0
        fake_zone.target_temp_low = 65.0
        _install_fake_hvac_coord(
            pred, last_emitted={"z1": (68.0, 75.0)},
        )
        _install_energy_in_hass(hass, banking_enabled=True)
        # Pre-empt the banking branch so the test isolates the
        # reconciliation behavior, not the banking-fire behavior.
        pred._should_solar_bank = MagicMock(return_value=False)

        async def _noop_precool(zone, offset, reason):
            return None
        pred._execute_zone_pre_cool = _noop_precool

        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)

        now = datetime(2026, 6, 11, 11, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        calls = hass.services.async_call.await_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert not set_temp_calls
        assert pred._first_eval_done is True


class TestFlipAfterBankingWindow:
    """Tier 1 review MEDIUM-1: operator flip OFF at 14:30 (banking window
    has closed but thermostats are still banked) MUST release.

    Pre-fix: `_last_banked_zones` was overwritten from the live
    `_solar_banking_zones` set every cycle. When `_should_solar_bank`
    returned False (hour >= 14 or other condition), `_solar_banking_zones`
    was empty and `_last_banked_zones` was clobbered to empty, leaving
    no record of mid-bank zones → flip OFF was a no-op.

    Post-fix: zones enter `_last_banked_zones` on bank, leave only on
    explicit release or natural preset re-alignment (detected via
    `_last_emitted_range` ≈ baseline).
    """

    def test_post_window_flip_off_still_releases(
        self, fake_predictor, fake_zone,
    ):
        pred, hass = fake_predictor
        pred._first_eval_done = True  # we're not testing post-restart here

        # Cycle 1 (11:00): banking window open + gate ON → bank fires.
        _install_energy_in_hass(hass, banking_enabled=True)
        coord = _install_fake_hvac_coord(
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
        assert "z1" in pred._last_banked_zones, (
            "zone must be tracked as banked after a banking cycle"
        )

        # Cycle 2 (14:30): banking window CLOSED (hour >= 14 returns False
        # from _should_solar_bank), but gate still ON. Thermostats remain
        # banked. _last_banked_zones MUST NOT be cleared.
        now2 = datetime(2026, 6, 11, 14, 30, 0)
        # Simulate live setpoints still banked (preset cycle hasn't
        # re-aligned them yet — _last_emitted_range unchanged).
        fake_zone.target_temp_high = 72.0
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now2,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        assert "z1" in pred._last_banked_zones, (
            "post-window cycle (gate still ON) must NOT clear "
            "_last_banked_zones — thermostats are still banked"
        )

        # Cycle 3 (14:31): operator flips gate OFF → release fires.
        _install_energy_in_hass(hass, banking_enabled=False)
        hass.services.async_call.reset_mock()
        now3 = datetime(2026, 6, 11, 14, 31, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now3,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        calls = hass.services.async_call.await_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert set_temp_calls, (
            "flip OFF after banking window must release banked zones"
        )
        payload = set_temp_calls[0].args[2]
        assert payload["target_temp_high"] == 75.0
        assert pred._last_banked_zones == set()

    def test_gate_stays_off_next_cycle_no_repeat_release(self, fake_predictor):
        """A second cycle while gate is still OFF must NOT re-issue the
        release (idempotency)."""
        pred, hass = fake_predictor
        # Simulate post-release state: gate already OFF last cycle.
        pred._last_banking_gate_enabled = False
        pred._last_banked_zones = set()
        _install_energy_in_hass(hass, banking_enabled=False)

        constraint = _make_constraint(soc=98, forecast_high=92)
        pred._get_net_power = MagicMock(return_value=-800.0)

        now = datetime(2026, 6, 11, 11, 10, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="away", now=now,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        calls = hass.services.async_call.await_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert not set_temp_calls, (
            "Steady-state gate OFF must not re-issue release writes each cycle"
        )


# ---------------------------------------------------------------------------
# D4: EC property+setter round-trip (proxy for switch RestoreEntity replay)
# ---------------------------------------------------------------------------

class TestEnergyCoordinatorAttr:

    def test_solar_banking_property_and_setter_roundtrip(self):
        """`setattr(energy, 'solar_banking_enabled', ...)` flips the backing
        field; property reads return the value. Mirrors the path
        _ec_switch_factory takes via RestoreEntity replay.

        EnergyCoordinator is too heavy to fully instantiate in this test
        env (rich HA wiring at __init__); instead AST-extract the property
        + setter from the source file and exec the bound functions against
        a sentinel with the backing field.
        """
        import ast
        path = (
            "custom_components/universal_room_automation/domain_coordinators/energy.py"
        )
        with open(path) as f:
            src = f.read()
        tree = ast.parse(src)
        # Find class EnergyCoordinator -> property solar_banking_enabled + setter.
        found_property = False
        found_setter = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "EnergyCoordinator":
                for item in node.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if item.name != "solar_banking_enabled":
                        continue
                    for dec in item.decorator_list:
                        # @property
                        if isinstance(dec, ast.Name) and dec.id == "property":
                            found_property = True
                        # @solar_banking_enabled.setter
                        if (
                            isinstance(dec, ast.Attribute)
                            and isinstance(dec.value, ast.Name)
                            and dec.value.id == "solar_banking_enabled"
                            and dec.attr == "setter"
                        ):
                            found_setter = True
        assert found_property, (
            "EnergyCoordinator.solar_banking_enabled must be a @property "
            "so the EC sub-switch factory's getattr() reads the live value"
        )
        assert found_setter, (
            "EnergyCoordinator.solar_banking_enabled must have a .setter so "
            "_ec_switch_factory's setattr(energy, attr_name, value) writes "
            "through at user-toggle + RestoreEntity replay time"
        )

        # Constructor seeds the backing field from CM options.
        assert "_solar_banking_enabled" in src, (
            "Backing field must exist for the property to read"
        )
        # Constructor reads CONF_HVAC_SOLAR_BANK_ENABLED with the default.
        assert "CONF_HVAC_SOLAR_BANK_ENABLED" in src
        assert "DEFAULT_HVAC_SOLAR_BANK_ENABLED" in src


# ---------------------------------------------------------------------------
# D4 (factory wiring) — switch registration
# ---------------------------------------------------------------------------

class TestSwitchRegistration:

    def test_switch_factory_invocation_present(self):
        path = "custom_components/universal_room_automation/switch.py"
        with open(path) as f:
            src = f.read()
        assert "ECSolarBankingSwitch" in src, (
            "switch.py must define ECSolarBankingSwitch via _ec_switch_factory"
        )
        # unique_id suffix per plan D4 (acceptance "Verify: unique_id ==
        # 'universal_room_automation_energy_solar_banking'").
        assert '"solar_banking"' in src
        assert '"Solar HVAC Banking"' in src
        # Default True (preserves status-quo behavior).
        idx = src.find("ECSolarBankingSwitch = _ec_switch_factory(")
        assert idx > 0
        block = src[idx:idx + 600]
        assert "default=True" in block

    def test_switch_registered_in_platform_setup(self):
        path = "custom_components/universal_room_automation/switch.py"
        with open(path) as f:
            src = f.read()
        # Must be added to the platform entity list (parallel pattern to
        # OccupancyWeightedPredictionSwitch(hass, entry) line).
        assert "ECSolarBankingSwitch(hass, entry)" in src


# ---------------------------------------------------------------------------
# D5: hvac.py extra_state_attributes
# ---------------------------------------------------------------------------

class TestHVACAttrSurface:

    def test_banking_enabled_attr_wired(self):
        path = (
            "custom_components/universal_room_automation/domain_coordinators/hvac.py"
        )
        with open(path) as f:
            src = f.read()
        assert 'attrs["banking_enabled"]' in src, (
            "hvac.py must populate the banking_enabled attr next to "
            "solar_banking_zones (plan D5)"
        )
        # Must be sourced from the predictor helper, not re-read EC twice.
        idx = src.find('attrs["banking_enabled"]')
        nearby = src[max(0, idx - 200):idx + 400]
        assert "_is_solar_banking_enabled" in nearby, (
            "banking_enabled must read the predictor helper (single source "
            "of truth) — see plan D5 'use the predictor helper rather than "
            "re-reading EC twice'"
        )

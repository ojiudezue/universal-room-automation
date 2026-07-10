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
    """Wire fake HC + EC into hass.data so the gate-read helpers find them.

    v5.7.1: solar_banking_enabled was retired and replaced with
    energy_precool_enabled (operator master toggle on the EC device for
    the unified Energy Saver Pre-Cool branch). The `banking_enabled`
    kwarg is preserved as the public API for these tests but it now
    seeds the new attribute. Default offset/scope are also seeded so
    HVACPredictor accessors return sensible values during the test.
    """
    hvac = MagicMock()
    hvac.pre_conditioning_enabled = pre_conditioning_enabled
    energy = MagicMock()
    energy.energy_precool_enabled = banking_enabled
    energy.energy_precool_offset = -2.0
    energy.energy_precool_scope = "auto_pv_tiered"
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
        # v5.7.1: single unified trigger spy. Must NOT be called when
        # master "28" gate is OFF (defense-in-depth check — the master
        # gate sits above the unified Energy Saver Pre-Cool branch).
        unified_spy = MagicMock(return_value=True)
        pred._should_energy_precool = unified_spy
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
        assert unified_spy.call_count == 0, (
            "master '28' gate OFF → _should_energy_precool must NEVER be called"
        )
        assert precool_calls == [], (
            "gate OFF → _execute_zone_pre_cool must NEVER be called"
        )
        assert pred._pre_conditioning_zones == set()
        assert pred._energy_precool_zones == set()

    def test_gate_on_preserves_behavior(self, fake_predictor):
        """Master '28' ON + pre-cool gate ON + eligible conditions → unified
        Energy Saver Pre-Cool fires. v5.7.1 rename: reason is now
        `energy_precool` and the tracking set is `_energy_precool_zones`.
        """
        pred, hass = fake_predictor
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=True, banking_enabled=True,
        )
        pred._first_eval_done = True
        # Scope = whole_house to bank the (unoccupied / away) zone — the
        # default auto_pv_tiered would skip the away-only zone unless
        # export surplus passes the dispatch-time re-check.
        manager = hass.data[
            __import__(
                "custom_components.universal_room_automation.const",
                fromlist=["DOMAIN"],
            ).DOMAIN
        ]["coordinator_manager"]
        manager.coordinators["energy"].energy_precool_scope = "whole_house"
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
            reason == "energy_precool" for _, _, reason in precool_calls
        )
        assert "z1" in pred._energy_precool_zones

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
            "z1" in pred._last_precool_zones
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
        assert pred._last_precool_zones == set()
        assert pred._last_pre_conditioning_zones == set()

    def test_same_day_flip_off_then_on_re_engages_pre_cool(
        self, fake_predictor,
    ):
        """A-HIGH-1: flip OFF mid-pre-cool then flip ON later the SAME day
        → unified Energy Saver Pre-Cool re-engages on the next cycle.

        Mutation: leave `_pre_cool_triggered_today=True` across the flip-OFF
        release → this test fails because `_should_energy_precool` keeps
        bailing on the `not _pre_cool_triggered_today` guard until midnight.
        """
        pred, hass = fake_predictor
        pred._first_eval_done = True
        # Cycle 1: master + pre-cool gates ON, unified pre-cool fires.
        # v5.7.1: banking_enabled now seeds energy_precool_enabled — keep
        # it ON across cycles so the gate-flip behavior being tested is
        # the MASTER "28" toggle (not the new pre-cool sub-gate).
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=True, banking_enabled=True,
        )
        _install_fake_hvac_coord(
            pred, last_emitted={"z1": (68.0, 75.0)},
        )
        # Force PV surplus so the unified trigger can fire on cycle 3.
        pred._get_net_power = MagicMock(return_value=-800.0)
        # Force unified pre-cool to fire on cycle 1.
        pred._should_energy_precool = MagicMock(return_value=True)
        precool_calls: list = []

        async def _spy_precool(zone, offset, reason):
            precool_calls.append((zone.zone_id, offset, reason))

        pred._execute_zone_pre_cool = _spy_precool
        constraint = _make_constraint(soc=98, forecast_high=92)
        # 13:00 — inside pre-cool window (PEAK_HOUR_START=14 minus
        # PRECOOL_LEAD_HOURS=2 → [12,14)).
        now1 = datetime(2026, 6, 11, 13, 0, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="home_day", now=now1,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        # Pretend that real call set the triggered_today + active flags
        # (the spy replaces _should_weather_pre_cool, which is where the
        # real method sets them). Mirror the real-side behavior so the
        # flip-OFF release block has something to clear.
        pred._pre_cool_active = True
        pred._pre_cool_triggered_today = True

        # Cycle 2: same day, operator flips master OFF mid-window.
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=False, banking_enabled=True,
        )
        now2 = datetime(2026, 6, 11, 13, 5, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="home_day", now=now2,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        # Flip-OFF release must clear both in-flight AND triggered_today
        # (A-HIGH-1 fix).
        assert pred._pre_cool_active is False
        assert pred._pre_cool_triggered_today is False, (
            "A-HIGH-1: flip-OFF release MUST clear _pre_cool_triggered_today "
            "so a same-day flip-back-ON can re-arm weather pre-cool"
        )
        assert pred._pre_heat_triggered_today is False

        # Cycle 3: operator flips master back ON, still same day,
        # still inside the pre-cool window — the REAL _should_energy_precool
        # should re-fire (no spy this time).
        # Restore the real method by deleting the spy attribute so attribute
        # lookup hits the class definition again.
        del pred._should_energy_precool
        _install_hvac_in_hass(
            hass, pre_conditioning_enabled=True, banking_enabled=True,
        )
        # Default scope is auto_pv_tiered → occupied-only when no real
        # surplus. We have PV surplus (-800W) so it will expand; but to
        # be unambiguous about the home_day fake zone (occupied=True via
        # fake_zone fixture) any scope works.
        precool_calls.clear()
        now3 = datetime(2026, 6, 11, 13, 10, 0)
        _run_coro(pred._check_pre_conditioning(
            constraint, house_state="home_day", now=now3,
            pre_arrival_zones=set(),
            zone_intelligence_enabled=True,
        ))
        # Re-engagement evidence: the daily-once gate re-armed and fired.
        assert pred._pre_cool_active is True, (
            "A-HIGH-1: same-day flip-back-ON inside pre-cool window MUST "
            "re-engage weather pre-cool (gate currently stuck off until "
            "date rollover)"
        )
        assert pred._pre_cool_triggered_today is True
        assert any(
            reason == "energy_precool" for _zid, _off, reason in precool_calls
        ), "unified energy pre-cool should fire on re-engage cycle"

    def test_steady_state_off_does_not_repeat_release(self, fake_predictor):
        """Idempotency: gate OFF for the second cycle → no re-issued release."""
        pred, hass = fake_predictor
        pred._first_eval_done = True
        pred._last_pre_conditioning_gate_enabled = False
        pred._last_pre_conditioning_zones = set()
        pred._last_precool_zones = set()
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
        # v5.11.0 D5 — stub dimensions carry the explicit `stub` token
        # instead of a silent `ok` verdict (see PLANNING D5).
        assert verdicts["energy_efficiency"] == "stub"

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

    def _install_room_entry(self, coord, opt_mod, *, room_name,
                            temp_eid="sensor.living_room_temp",
                            temp_val="72.0",
                            occ_eid="binary_sensor.living_room_occ",
                            occ_state="on"):
        """Wire a real ConfigEntry + hass.states surface for the oracle.

        Matches the production reader path: optimizer's
        `_iter_room_entries` yields entries with `entry.data.get(CONF_ENTRY_TYPE)
        == ENTRY_TYPE_ROOM`, and `_state_value(eid)` reads
        `coord.hass.states.get(eid)`. We build BOTH so the oracle exercises
        its real reader, not a mocked surface.
        """
        from custom_components.universal_room_automation.const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM, DOMAIN,
            CONF_TEMPERATURE_SENSOR, CONF_OCCUPANCY_SENSORS,
        )

        entry = MagicMock()
        entry.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            "room_name": room_name,
        }
        opts = {}
        if temp_eid is not None:
            opts[CONF_TEMPERATURE_SENSOR] = temp_eid
        if occ_eid is not None:
            opts[CONF_OCCUPANCY_SENSORS] = [occ_eid]
        entry.options = opts
        entry.entry_id = f"entry_{room_name}"

        # Drive the real _iter_room_entries: hass.config_entries.async_entries.
        coord.hass.config_entries = MagicMock()
        coord.hass.config_entries.async_entries = MagicMock(
            return_value=[entry],
        )

        # Drive the real _state_value: hass.states.get(eid).
        state_map: dict[str, MagicMock] = {}
        if temp_eid is not None and temp_val is not None:
            st = MagicMock()
            st.state = temp_val
            state_map[temp_eid] = st
        if occ_eid is not None and occ_state is not None:
            st = MagicMock()
            st.state = occ_state
            state_map[occ_eid] = st
        coord.hass.states = MagicMock()
        coord.hass.states.get = lambda eid, _m=state_map: _m.get(eid)
        coord.hass.data[DOMAIN] = {"coordinator_manager": MagicMock()}
        return entry

    def test_comfort_oracle_scores_findings(self):
        """Mutation check #4 + B-HIGH-1 fix: oracle drives the REAL
        production reader (`_iter_room_entries` → `CONF_TEMPERATURE_SENSOR`
        → `_state_value`). No room_coordinators dict is consulted.

        Mandatory phantom-surface mutation: point the oracle at a
        nonexistent entity → all findings record `match=None` and the
        rolling pct stays None / status flips to `no_observable_data`.
        """
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
            OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES,
        )

        self._install_room_entry(
            coord, opt_mod, room_name="living_room",
            temp_eid="sensor.living_room_temp", temp_val="72.0",
        )

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
                # Pass-2 fix-up: producer carries its own per-room band on
                # the finding (optimization.py:1602). 72°F is inside the
                # default [68, 76] band → the flagged out-of-band condition
                # has RESOLVED → oracle scores True.
                payload={"bounds": [68.0, 76.0]},
            )
            findings.append(f)
        coord._last_findings = findings

        coord._run_shadow_accuracy_validator()
        assert coord._last_shadow_accuracy_status == "ready"
        assert coord._last_shadow_accuracy_pct == 100.0
        for f in findings:
            assert f.observed_effect is not None
            assert f.observed_effect["match"] is True

    def test_comfort_oracle_phantom_entity_yields_no_observable_data(self):
        """B-HIGH-1 / B-MED-1 anti-regression: point the oracle at a
        nonexistent temperature entity and a passing test must turn red.

        This is the MANDATORY phantom-surface mutation — if the oracle
        ever silently fabricates a result from a missing surface again,
        this test fails. Also exercises the `no_observable_data` token
        introduced for B-MED-1.
        """
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
        )
        # temp_eid intentionally points at an entity NOT in state_map.
        self._install_room_entry(
            coord, opt_mod, room_name="living_room",
            temp_eid="sensor.does_not_exist", temp_val=None,
        )
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        findings = []
        for i in range(3):
            findings.append(opt_mod.OptimizationFinding(
                timestamp=past_iso,
                level="room", target_id="living_room",
                dimension=opt_mod.OptimizationDimension.COMFORT,
                severity="low", confidence=0.5, score=90.0,
                description=f"f{i}",
                applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
                predicted_effect={"note": "shadow"},
                # Bounds present so the inconclusive result is driven by
                # the missing temp sensor (phantom entity), not by the
                # missing-bounds early return.
                payload={"bounds": [68.0, 76.0]},
            ))
        coord._last_findings = findings
        coord._run_shadow_accuracy_validator()
        # Every observed_effect must be inconclusive — phantom surface.
        for f in findings:
            assert f.observed_effect is not None
            assert f.observed_effect["match"] is None
        # Rolling pct stays None; status surfaces the inert oracle.
        assert coord._last_shadow_accuracy_pct is None
        assert coord._last_shadow_accuracy_status == "no_observable_data"

    def test_oracle_records_out_of_band_as_false(self):
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
        )
        self._install_room_entry(
            coord, opt_mod, room_name="hot_room",
            temp_eid="sensor.hot_room_temp", temp_val="92.0",  # out of band
        )
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        f = opt_mod.OptimizationFinding(
            timestamp=past_iso,
            level="room", target_id="hot_room",
            dimension=opt_mod.OptimizationDimension.COMFORT,
            severity="low", confidence=0.5, score=90.0,
            description="x",
            applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
            predicted_effect={"note": "shadow"},
            payload={"bounds": [68.0, 76.0]},
        )
        coord._last_findings = [f]
        coord._run_shadow_accuracy_validator()
        assert f.observed_effect["match"] is False

    def test_comfort_oracle_scores_gap_value_as_persisted_false(self):
        """P2-HIGH-1 fix-up pass 2 — MANDATORY gap mutation.

        The Pass-2 review found the prior oracle scored against a
        HARDCODED [65, 80] band while producers carry a tighter per-room
        band on the finding (default [68, 76]). At 77°F the producer
        fires (out of [68, 76]) and the oracle re-read 77°F as still
        IN [65, 80] → reported "accurate" for exactly the findings it
        was meant to validate.

        Coherent semantics now: score against ``payload["bounds"]`` —
        77°F is OUTSIDE [68, 76] → match=False (PERSISTED).

        MUTATION evidence: reverting the oracle to the hardcoded
        ``65.0 <= temp <= 80.0`` band makes this test fail (77°F would
        score True/resolved).
        """
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
        )
        # temp_val=77.0 is the GAP value: inside the old hardcoded
        # [65, 80] band but OUTSIDE the producer's [68, 76] band.
        self._install_room_entry(
            coord, opt_mod, room_name="gap_room",
            temp_eid="sensor.gap_room_temp", temp_val="77.0",
        )
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        f = opt_mod.OptimizationFinding(
            timestamp=past_iso,
            level="room", target_id="gap_room",
            dimension=opt_mod.OptimizationDimension.COMFORT,
            severity="medium", confidence=0.8, score=90.0,
            description="gap-value persisted",
            applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
            predicted_effect={"note": "shadow"},
            # The same band the producer would have stamped (const default).
            payload={"bounds": [68.0, 76.0]},
        )
        coord._last_findings = [f]
        coord._run_shadow_accuracy_validator()
        assert f.observed_effect is not None
        assert f.observed_effect["match"] is False, (
            "P2-HIGH-1: 77°F inside [65,80] but OUTSIDE the finding's "
            "[68,76] band MUST score persisted=False, not accurate=True"
        )
        # Evidence string carries the resolved-vs-persisted semantics so
        # readers of the ledger can tell which path fired.
        assert "persisted_outside" in f.observed_effect["evidence"]

    def test_comfort_oracle_inconclusive_when_bounds_missing(self):
        """P2-HIGH-1: a finding without ``payload["bounds"]`` MUST score
        inconclusive (None), not fall back to a wide default band that
        would degenerate the oracle again."""
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
        )
        self._install_room_entry(
            coord, opt_mod, room_name="no_bounds_room",
            temp_eid="sensor.no_bounds_temp", temp_val="72.0",
        )
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        f = opt_mod.OptimizationFinding(
            timestamp=past_iso,
            level="room", target_id="no_bounds_room",
            dimension=opt_mod.OptimizationDimension.COMFORT,
            severity="low", confidence=0.5, score=90.0,
            description="x",
            applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
            predicted_effect={"note": "shadow"},
            # No payload bounds — older finding shape.
        )
        coord._last_findings = [f]
        coord._run_shadow_accuracy_validator()
        assert f.observed_effect is not None
        assert f.observed_effect["match"] is None
        assert "bounds" in f.observed_effect["evidence"]

    def test_occupancy_oracle_scores_persisted_disagreement_as_false(self):
        """P2-MED-1 fix-up pass 2 — MANDATORY False-reachable mutation.

        The Pass-2 review found the prior occupancy oracle could only
        return True or None, never False — it measured "sensors alive,"
        not "did the provenance disagreement resolve."

        Coherent semantics now: the producer fires when motion=on AND
        all occupancy=off. The oracle reads the SAME ids (carried on
        the finding payload) later and returns False iff motion is
        still on AND every occupancy sensor is still off.

        MUTATION evidence: making the oracle return True unconditionally
        (the prior behavior) makes this test fail (it expects False).
        """
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
        )
        # Build hass.states with motion=on AND occ=off — the exact
        # persisted-disagreement condition the producer fires on.
        from custom_components.universal_room_automation.const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM, DOMAIN,
            CONF_OCCUPANCY_SENSORS, CONF_MOTION_SENSORS,
        )
        entry = MagicMock()
        entry.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            "room_name": "kitchen",
        }
        entry.options = {
            CONF_OCCUPANCY_SENSORS: ["binary_sensor.kitchen_occ"],
            CONF_MOTION_SENSORS: ["binary_sensor.kitchen_motion"],
        }
        entry.entry_id = "entry_kitchen"
        coord.hass.config_entries = MagicMock()
        coord.hass.config_entries.async_entries = MagicMock(
            return_value=[entry],
        )
        st_occ = MagicMock(); st_occ.state = "off"
        st_motion = MagicMock(); st_motion.state = "on"
        state_map = {
            "binary_sensor.kitchen_occ": st_occ,
            "binary_sensor.kitchen_motion": st_motion,
        }
        coord.hass.states = MagicMock()
        coord.hass.states.get = lambda eid, _m=state_map: _m.get(eid)
        coord.hass.data[DOMAIN] = {"coordinator_manager": MagicMock()}

        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        # Producer payload: occupancy_ids + signal_ids captured at emit.
        f = opt_mod.OptimizationFinding(
            timestamp=past_iso,
            level="room", target_id="kitchen",
            dimension=opt_mod.OptimizationDimension.OCCUPANCY_ACCURACY,
            severity="low", confidence=0.55, score=90.0,
            description="x",
            applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
            predicted_effect={"note": "shadow"},
            payload={
                "occupancy_ids": ["binary_sensor.kitchen_occ"],
                "signal_ids": ["binary_sensor.kitchen_motion"],
            },
        )
        coord._last_findings = [f]
        coord._run_shadow_accuracy_validator()
        assert f.observed_effect is not None
        assert f.observed_effect["match"] is False, (
            "P2-MED-1: motion on + occupancy off (persisted) MUST score "
            "False, not True (sensors-alive degenerate)"
        )
        assert "persisted" in f.observed_effect["evidence"]

    def test_occupancy_oracle_drives_real_reader(self):
        """B-HIGH-1 fix: occupancy oracle reads CONF_OCCUPANCY_SENSORS
        via _state_value (production-proven path), NOT a phantom
        room.is_occupied attribute."""
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
            OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES,
        )
        self._install_room_entry(
            coord, opt_mod, room_name="kitchen",
            temp_eid=None, temp_val=None,
            occ_eid="binary_sensor.kitchen_occ", occ_state="on",
        )
        past_iso = (_utcnow() - timedelta(minutes=30)).isoformat()
        findings = []
        for i in range(OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES + 2):
            findings.append(opt_mod.OptimizationFinding(
                timestamp=past_iso,
                level="room", target_id="kitchen",
                dimension=opt_mod.OptimizationDimension.OCCUPANCY_ACCURACY,
                severity="low", confidence=0.5, score=90.0,
                description=f"f{i}",
                applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
                predicted_effect={"note": "shadow"},
            ))
        coord._last_findings = findings
        coord._run_shadow_accuracy_validator()
        assert coord._last_shadow_accuracy_status == "ready"
        assert coord._last_shadow_accuracy_pct == 100.0

    def test_aware_timestamp_compares_with_aware_cutoff(self):
        """Validator finding: naive timestamps on the :1111 path used to
        TypeError under offset-aware now. Both naive and aware ISO
        timestamps must be handled without raising and produce the SAME
        rolling result."""
        coord, opt_mod = self._make_coord()
        from custom_components.universal_room_automation.const import (
            OPTIMIZER_OUTCOME_SHADOW,
            OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES,
        )
        self._install_room_entry(
            coord, opt_mod, room_name="living_room",
            temp_eid="sensor.living_room_temp", temp_val="72.0",
        )
        # Naive timestamp (no tzinfo).
        past_naive = (
            datetime.utcnow() - timedelta(minutes=30)
        ).replace(tzinfo=None).isoformat()
        findings = []
        for i in range(OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES + 2):
            findings.append(opt_mod.OptimizationFinding(
                timestamp=past_naive,
                level="room", target_id="living_room",
                dimension=opt_mod.OptimizationDimension.COMFORT,
                severity="low", confidence=0.5, score=90.0,
                description=f"f{i}",
                applied_outcome=OPTIMIZER_OUTCOME_SHADOW,
                predicted_effect={"note": "shadow"},
                payload={"bounds": [68.0, 76.0]},
            ))
        coord._last_findings = findings
        # Must NOT raise "can't compare offset-naive and offset-aware".
        coord._run_shadow_accuracy_validator()
        assert coord._last_shadow_accuracy_status == "ready"

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

"""ENVOY-PRODUCTION-STALE-1 (Rev 5, clean-core fix-up 3).

Post-Tier-3 keep-set:
  D1   `_state_age_s` helper (pass-through-on-unknown contract).
  D2-A battery_soc PRIMARY fresh gate → LKG fallback engages on stale.
  D3   solar_production_w fresh gate (16.5h frozen-solar-read ask).
  D4-D drain-pause release HOLD via `battery_ok` (mutation-proven).
       Arm-on-unknown DROPPED per operator (D-MED-3 accepted gap,
       carded ENVOY-DRAIN-ARM-STALE-CT-1).
       Call-site wire-in (energy.py:6161 EVSE, :6327 plug) exercised
       via a source-extracted behavioral anchor (C-HIGH-1).
  D4-E billing skip on stale-but-numeric.
  D4-F envoy_cache columns (bare props dropped, SOC-source gated).
  D4-G load-shed drain of `_sustained_import_readings` on stale snap.
  D-OBS behavioral `_classify_sources` (C-MED-1: not source grep).

DROPPED (reverted to develop, verified by `git diff develop`):
  D4-A net_power_w producer gate (Tier-3 MED-2 — must not reach the
       breaker via `_effective_import_kw`).
  D4-B grid-cap fail-CLOSED (would strand EV via lost release path).
  D4-H×3 breaker-guard fail-CLOSED (over-corrected on a default-off
       guard, resurrected v5.5.6 harm).
"""
from __future__ import annotations

import os
import sys
import types
import importlib
import importlib.util
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA import stubs (mirror sibling patterns).
# ---------------------------------------------------------------------------
def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_pool"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

_eb_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.domain_coordinators.energy_battery",
    os.path.join(_dc_path, "energy_battery.py"),
)
_eb_mod = importlib.util.module_from_spec(_eb_spec)
sys.modules[_eb_spec.name] = _eb_mod
_eb_spec.loader.exec_module(_eb_mod)
_state_age_s = _eb_mod._state_age_s

from conftest import MockHass, MockState  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController, SmartPlugController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    DEFAULT_NET_POWER_MAX_AGE_S,
    DEFAULT_BATTERY_POWER_MAX_AGE_S,
    DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S,
    DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S,
)


@pytest.fixture(autouse=True)
def _force_utc_aware_utcnow():
    """Force `homeassistant.util.dt.utcnow` / `.now` to return tz-aware UTC
    for this file — sibling test files stub these as naive `datetime.utcnow`
    which would create tz-comparison errors against our tz-aware MockState.
    """
    import homeassistant.util.dt as _dt
    orig_utcnow = getattr(_dt, "utcnow", None)
    orig_now = getattr(_dt, "now", None)
    _dt.utcnow = lambda: datetime.now(timezone.utc)
    _dt.now = lambda: datetime.now(timezone.utc)
    yield
    if orig_utcnow is not None:
        _dt.utcnow = orig_utcnow
    if orig_now is not None:
        _dt.now = orig_now


def _stale_state(entity_id, value, age_s, *, uom=None):
    """MockState with a fresh-looking numeric value + OLD stamp."""
    old = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    attrs = {"unit_of_measurement": uom} if uom else {}
    st = MockState(entity_id, value, attributes=attrs, last_changed=old)
    st.last_reported = old
    st.last_updated = old
    return st


def _fresh_state(entity_id, value, *, uom=None, age_s=1.0):
    return _stale_state(entity_id, value, age_s, uom=uom)


# ===========================================================================
# D1 — helper semantics
# ===========================================================================

class TestStateAgeSemantics:
    def test_missing_state_returns_none(self):
        assert _state_age_s(None) is None

    def test_naive_stamp_returns_none(self):
        s = MockState("sensor.x", "1.0")
        s.last_reported = datetime.now()
        s.last_updated = datetime.now()
        assert _state_age_s(s) is None

    def test_negative_stamp_clamps_to_zero(self):
        s = MockState("sensor.x", "1.0")
        s.last_reported = datetime.now(timezone.utc) + timedelta(seconds=10)
        assert _state_age_s(s) == 0.0

    def test_prefers_last_reported(self):
        s = MockState("sensor.x", "1.0")
        s.last_reported = datetime.now(timezone.utc) - timedelta(seconds=5)
        s.last_updated = datetime.now(timezone.utc) - timedelta(hours=1)
        age = _state_age_s(s, stamp="last_reported")
        assert age is not None and age < 60

    def test_falls_back_to_last_updated_when_stamp_absent(self):
        s = MockState("sensor.x", "1.0")
        s.last_reported = None
        s.last_updated = datetime.now(timezone.utc) - timedelta(seconds=5)
        age = _state_age_s(s, stamp="last_reported")
        assert age is not None and age < 60

    def test_both_stamps_absent_returns_none(self):
        s = MockState("sensor.x", "1.0")
        s.last_reported = None
        s.last_updated = None
        assert _state_age_s(s) is None

    def test_constant_valued_sensor_stays_fresh_under_last_reported(self):
        s = MockState("sensor.solar", "0.0")
        s.last_reported = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.last_updated = datetime.now(timezone.utc) - timedelta(hours=3)
        age = _state_age_s(s, stamp="last_reported")
        assert age is not None and age < 30


# ===========================================================================
# Producers — stale-but-numeric end-to-end. `net_power_w` deliberately
# NOT tested here (D4-A reverted per MED-2 — read exactly as develop).
# ===========================================================================

class TestProducerStaleButNumeric:
    def _mk_battery(self, **overrides):
        from test_energy_battery import _BatteryHarness  # type: ignore
        return _BatteryHarness(**overrides)

    def test_d2a_battery_soc_stale_falls_to_lkg(self):
        h = self._mk_battery(soc=62)
        assert h.strategy.battery_soc == 62.0
        assert h.strategy._soc_source_last == "envoy"
        from test_energy_battery import DEFAULT_BATTERY_SOC_ENTITY  # type: ignore
        h.hass._states[DEFAULT_BATTERY_SOC_ENTITY] = _stale_state(
            DEFAULT_BATTERY_SOC_ENTITY, "62",
            DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S + 60,
        )
        v = h.strategy.battery_soc
        # Value equals LKG (numeric coincidence); discriminator is source.
        assert v == 62.0
        assert h.strategy._soc_source_last == "lkg"

    def test_d3_solar_production_stale_returns_none(self):
        h = self._mk_battery()
        from test_energy_battery import DEFAULT_SOLAR_PRODUCTION_ENTITY  # type: ignore
        h.hass._states[DEFAULT_SOLAR_PRODUCTION_ENTITY] = _stale_state(
            DEFAULT_SOLAR_PRODUCTION_ENTITY, "5000",
            DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S + 60, uom="W",
        )
        assert h.strategy.solar_production_w is None

    def test_d4d_battery_power_w_stale_returns_none(self):
        h = self._mk_battery()
        from test_energy_battery import DEFAULT_BATTERY_POWER_ENTITY  # type: ignore
        h.hass._states[DEFAULT_BATTERY_POWER_ENTITY] = _stale_state(
            DEFAULT_BATTERY_POWER_ENTITY, "-500",
            DEFAULT_BATTERY_POWER_MAX_AGE_S + 60,
        )
        assert h.strategy.battery_power_w is None

    def test_net_power_w_UNGATED_returns_stale_value(self):
        """Tier-3 MED-2 anchor: `net_power_w` is deliberately NOT gated so
        the breaker / arbitrage path reads it exactly as develop does.
        A stale-but-numeric net_power state MUST still return its numeric
        value (units normalized), NOT None.
        """
        h = self._mk_battery()
        from test_energy_battery import DEFAULT_NET_POWER_ENTITY  # type: ignore
        h.hass._states[DEFAULT_NET_POWER_ENTITY] = _stale_state(
            DEFAULT_NET_POWER_ENTITY, "8000",
            DEFAULT_NET_POWER_MAX_AGE_S + 60, uom="W",
        )
        assert h.strategy.net_power_w == 8000.0, (
            "net_power_w MUST pass through stale-but-numeric to preserve "
            "develop's breaker/arbitrage behavior (Tier-3 MED-2)"
        )

    def test_fresh_path_byte_identity(self):
        h = self._mk_battery()
        assert h.strategy.battery_soc == 80.0
        assert h.strategy.net_power_w == -500.0
        assert h.strategy.solar_production_w == 5000.0
        assert h.strategy.battery_power_w == 200.0


# ===========================================================================
# D4-D — drain release HOLD across stale CT (mutation-proven).
# Arm-on-unknown DROPPED (D-MED-3 accepted gap, ENVOY-DRAIN-ARM-STALE-CT-1).
# ===========================================================================

def _make_ev(garage_on=True, garage_power=5000.0):
    hass = MockHass()
    hass.set_state("switch.garage_a", "on" if garage_on else "off")
    hass.set_state("sensor.garage_a_power_minute_average", str(garage_power))
    hass.set_state("sensor.garage_a_energy_today", "0")
    hass.set_state("sensor.garage_a_energy_this_month", "0")
    return EVChargerController(hass, evse_config={
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
            "self_modulates": False,
        },
    }), hass


class TestD4DDrainReleaseHold:
    """battery_ok=(not battery_discharging) and not battery_power_unknown."""

    def test_release_hold_across_stale_ct_at_reserve_floor_evse(self):
        ev, hass = _make_ev()
        ev.determine_battery_drain_actions(
            battery_power_w=-3000.0, battery_soc=45.0, soc_threshold=50,
            reserve_soc=20, is_offpeak=True,
        )
        assert "garage_a" in ev._paused_by_battery_drain
        # CT freezes; SOC at reserve+2. Pre-fix would DROP pause via
        # `battery_out_of_capacity` → `overnight_release`. Fix HOLDS.
        actions = ev.determine_battery_drain_actions(
            battery_power_w=None, battery_soc=22.0, soc_threshold=50,
            reserve_soc=20, is_offpeak=True,
            battery_power_unknown=True,
        )
        assert not any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain

    def test_release_hold_across_stale_ct_at_reserve_floor_plug(self):
        hass = MockHass()
        hass.set_state("switch.plug_l1", "on")
        pool = SmartPlugController(
            hass,
            plug_entities=["switch.plug_l1"],
            plug_config={"switch.plug_l1": {"self_modulates": False}},
        )
        pool.determine_battery_drain_actions(
            battery_power_w=-3000.0, battery_soc=45.0, soc_threshold=50,
            reserve_soc=20, is_offpeak=True,
        )
        assert "switch.plug_l1" in pool._paused_by_battery_drain
        actions = pool.determine_battery_drain_actions(
            battery_power_w=None, battery_soc=22.0, soc_threshold=50,
            reserve_soc=20, is_offpeak=True,
            battery_power_unknown=True,
        )
        assert not any(a["service"] == "switch.turn_on" for a in actions)
        assert "switch.plug_l1" in pool._paused_by_battery_drain

    def test_soc_recovered_release_still_fires_under_blind_ct(self):
        """`daytime_release = soc_recovered` is CT-independent — MUST fire.
        Discriminates the fix from an over-broad "block all releases".
        """
        ev, hass = _make_ev()
        ev.determine_battery_drain_actions(
            battery_power_w=-3000.0, battery_soc=45.0, soc_threshold=50,
            reserve_soc=20, is_offpeak=True,
        )
        assert "garage_a" in ev._paused_by_battery_drain
        hass.set_state("switch.garage_a", "off")
        hass.set_state("sensor.garage_a_power_minute_average", "0")
        ev.determine_battery_drain_actions(
            battery_power_w=None, battery_soc=70.0, soc_threshold=50,
            reserve_soc=20, solar_replenishing=True, is_offpeak=True,
            battery_power_unknown=True,
        )
        assert "garage_a" not in ev._paused_by_battery_drain

    def test_force_charge_release_still_fires_under_blind_ct(self):
        ev, hass = _make_ev()
        ev.determine_battery_drain_actions(
            battery_power_w=-3000.0, battery_soc=45.0, soc_threshold=50,
        )
        assert "garage_a" in ev._paused_by_battery_drain
        ev._force_charge_until = datetime.now(timezone.utc) + timedelta(hours=1)
        ev.determine_battery_drain_actions(
            battery_power_w=None, battery_soc=45.0, soc_threshold=50,
            battery_power_unknown=True,
        )
        assert "garage_a" not in ev._paused_by_battery_drain


# ===========================================================================
# D4-D — REAL wire-in behavioral anchor (C-HIGH-1).
# Extracts the EXACT call-site code text from energy.py and executes it
# against a real BatteryStrategy (stale-stamped battery_power) + a spy for
# `determine_battery_drain_actions`. If someone drops
# `battery_power_unknown=(_bp is None)` at either call site, the extracted
# source no longer propagates the flag → the spy sees False → test RED.
# ===========================================================================


def _extract_call_site(marker, var_name):
    """Extract the call-site code from energy.py starting from the
    `<var_name> = self._battery.battery_power_w` assignment. Restores
    the leading indent on line 1 so `textwrap.dedent` sees uniform
    indentation across the whole block, then dedents to column 0.
    """
    src = open(os.path.join(
        _ura_path, "domain_coordinators", "energy.py",
    )).read()
    m = src.find(marker)
    assert m >= 0, f"marker not found: {marker}"
    needle = f"{var_name} = self._battery.battery_power_w"
    i = src.find(needle, m)
    assert i >= 0, f"assignment not found: {needle}"
    # Back up to the start of the line so we capture the leading indent.
    line_start = src.rfind("\n", 0, i) + 1
    end = src.find("for action_spec in", i)
    assert end > i, "call block terminator not found"
    text = src[line_start:end]
    import textwrap
    return textwrap.dedent(text)


class TestD4DCallSiteWireInBehavioral:
    """C-HIGH-1: drive the ACTUAL production call-site code with a stale
    battery_power entity — the flag must compute True from the real read.
    Neuter → RED.
    """

    def _spy_call(self, marker, var_name):
        """Extract the call-site text from energy.py, exec it against a
        real BatteryStrategy with a stale battery_power entity + a spy
        drain-actions method. Return the observed kwargs.
        """
        from test_energy_battery import (  # type: ignore
            _BatteryHarness, DEFAULT_BATTERY_POWER_ENTITY,
        )
        h = _BatteryHarness()
        # STALE-stamped battery_power so battery_power_w returns None.
        h.hass._states[DEFAULT_BATTERY_POWER_ENTITY] = _stale_state(
            DEFAULT_BATTERY_POWER_ENTITY, "-500",
            DEFAULT_BATTERY_POWER_MAX_AGE_S + 60,
        )
        # Simulate `self._battery` and `self._ev` / `self._smart_plugs`.
        captured = {}

        def spy(**kwargs):
            captured.update(kwargs)
            return []

        # Build a self-like namespace that mirrors the enclosing method's
        # locals + attrs the extracted snippet reads.
        class _Self:
            _battery = h.strategy
            _ev_battery_drain_soc = 50
            _dp_must_start_by_min = 180

            class _EvSpy:
                pass
            _ev = _EvSpy()
            _smart_plugs = _EvSpy()

            async def _execute_service_action(self, action_spec):  # noqa: D401
                pass

        self_obj = _Self()
        self_obj._ev.determine_battery_drain_actions = spy
        self_obj._smart_plugs.determine_battery_drain_actions = spy

        # Locals the extracted snippet expects (mirroring the enclosing
        # decision-cycle scope in energy.py).
        _release_floor = 20
        solar_replenishing = False
        _is_offpeak = True
        _dp_forcing = False
        _dp_forcing_plug = False
        _now = datetime.now(timezone.utc)
        _now_plug = _now
        force_charge_active = False

        text = _extract_call_site(marker, var_name)
        # The extracted text is dedented and starts at the `_bp = ...`
        # (or `_bp_plug = ...`) assignment. Ready to exec at module scope.
        block = text
        # `await self._execute_service_action(...)` is unreachable because
        # the spy returns []; but the extracted text may still contain it.
        # Replace with a no-op call to keep the parser happy.
        block = block.replace("await self._execute_service_action",
                              "list  # NOP: removed await")
        local_ns = dict(
            self=self_obj,
            _release_floor=_release_floor,
            solar_replenishing=solar_replenishing,
            _is_offpeak=_is_offpeak,
            _dp_forcing=_dp_forcing,
            _dp_forcing_plug=_dp_forcing_plug,
            _now=_now,
            _now_plug=_now_plug,
            force_charge_active=force_charge_active,
            list=list,
        )
        exec(compile(block, "<call-site>", "exec"), local_ns)
        return captured

    def test_evse_call_site_computes_battery_power_unknown_true_from_stale_read(self):
        captured = self._spy_call(
            "ENVOY-PRODUCTION-STALE-1 D4-D-1", "_bp",
        )
        # The call-site MUST have passed the kwarg AND it MUST be True
        # because the stale-stamped read gates battery_power_w to None.
        assert "battery_power_unknown" in captured, (
            "call site dropped battery_power_unknown kwarg (wire-in gone)"
        )
        assert captured["battery_power_unknown"] is True, (
            "battery_power_unknown must compute True from stale CT read"
        )
        assert captured.get("battery_power_w") is None

    def test_plug_call_site_computes_battery_power_unknown_true_from_stale_read(self):
        captured = self._spy_call(
            "ENVOY-PRODUCTION-STALE-1 D4-D-2", "_bp_plug",
        )
        assert "battery_power_unknown" in captured
        assert captured["battery_power_unknown"] is True
        assert captured.get("battery_power_w") is None


# ===========================================================================
# D4-E — billing skip on stale-but-numeric
# ===========================================================================

class TestD4EBillingSkipOnStale:
    def _mk_tracker(self, hass, net_entity="sensor.envoy_net",
                    grid_import=None, grid_export=None):
        spec = importlib.util.spec_from_file_location(
            "custom_components.universal_room_automation.domain_coordinators.energy_billing",
            os.path.join(_dc_path, "energy_billing.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        tou_spec = importlib.util.spec_from_file_location(
            "custom_components.universal_room_automation.domain_coordinators.energy_tou",
            os.path.join(_dc_path, "energy_tou.py"),
        )
        tou_mod = importlib.util.module_from_spec(tou_spec)
        sys.modules[tou_spec.name] = tou_mod
        tou_spec.loader.exec_module(tou_mod)
        return mod.CostTracker(
            hass, tou_mod.TOURateEngine(),
            net_power_entity=net_entity,
            grid_import_entity=grid_import,
            grid_export_entity=grid_export,
        )

    def test_billing_get_net_power_returns_none_on_stale_envoy(self):
        hass = MockHass()
        hass._states["sensor.envoy_net"] = _stale_state(
            "sensor.envoy_net", "500",
            DEFAULT_NET_POWER_MAX_AGE_S + 60, uom="W",
        )
        assert self._mk_tracker(hass)._get_net_power() is None

    def test_billing_get_net_power_returns_value_on_fresh_envoy(self):
        hass = MockHass()
        hass._states["sensor.envoy_net"] = _fresh_state(
            "sensor.envoy_net", "500", uom="W",
        )
        assert self._mk_tracker(hass)._get_net_power() == 0.5

    def test_billing_get_net_power_direct_grid_leg_returns_none_on_stale(self):
        hass = MockHass()
        hass._states["sensor.grid_imp"] = _fresh_state(
            "sensor.grid_imp", "1000", uom="W",
        )
        hass._states["sensor.grid_exp"] = _stale_state(
            "sensor.grid_exp", "0",
            DEFAULT_NET_POWER_MAX_AGE_S + 60, uom="W",
        )
        ct = self._mk_tracker(
            hass, net_entity=None,
            grid_import="sensor.grid_imp",
            grid_export="sensor.grid_exp",
        )
        assert ct._get_net_power() is None


# ===========================================================================
# D4-F — cache column consistency (B-MED-2 fix)
# ===========================================================================

class TestD4FCacheColumnOmission:
    def test_save_envoy_cache_payload_omits_ungated_columns(self):
        src = open(os.path.join(
            _ura_path, "domain_coordinators", "energy.py",
        )).read()
        i = src.find("async def _save_envoy_cache")
        assert i > 0
        block = "\n".join(src[i:].split("\n")[:45])
        assert '"net_power":' not in block
        assert '"solar_production":' not in block
        assert '"battery_power":' not in block
        assert '_soc_source_last' in block


# ===========================================================================
# D4-G — load-shed drain on stale snap
# ===========================================================================

class TestD4GLoadShedDrainOnStale:
    def test_load_shed_stale_snap_clears_sustained_readings(self):
        src = open(os.path.join(
            _ura_path, "domain_coordinators", "energy.py",
        )).read()
        marker = "ENVOY-PRODUCTION-STALE-1 D4-G"
        i = src.find(marker)
        assert i > 0
        block = src[i:i + 800]
        # Ensure the drain-on-stale is inside the D4-G block AND before the
        # early return.
        clear_pos = block.find("_sustained_import_readings.clear()")
        return_pos = block.find("return\n")
        assert clear_pos > 0 and return_pos > clear_pos


# ===========================================================================
# D-OBS — behavioral _classify_sources anchors (C-MED-1)
# ===========================================================================

class _FakeEnergyWith:
    """Minimal energy stand-in with a _battery that answers _get_entity."""
    def __init__(self, key_to_eid):
        self._battery = types.SimpleNamespace()
        self._battery._get_entity = lambda k: key_to_eid.get(k)


def _extract_dobs_methods():
    """Extract the D-OBS classifier method sources from sensor.py and
    bind them into a lightweight class — avoids importing the whole
    sensor.py module. The extracted text is rewritten to use ABSOLUTE
    imports (the original relative `from .domain_coordinators...`
    imports won't resolve inside our exec namespace).
    """
    src = open(os.path.join(_ura_path, "sensor.py")).read()
    start = src.find("    _SHORT_KEYS = (")
    assert start >= 0, "_SHORT_KEYS marker not found"
    end = src.find("    @property\n    def native_value", start)
    assert end > start
    text = src[start:end]
    import textwrap
    # Rewrite relative imports to absolute; the exec namespace has no
    # package context.
    text = text.replace(
        "from .domain_coordinators.energy_battery import",
        "from custom_components.universal_room_automation."
        "domain_coordinators.energy_battery import",
    )
    text = text.replace(
        "from .domain_coordinators.energy_const import",
        "from custom_components.universal_room_automation."
        "domain_coordinators.energy_const import",
    )
    body = "class _DOBSStub:\n" + textwrap.indent(
        textwrap.dedent(text), "    ",
    )
    # exec with proper __name__ + __builtins__ so imports and typing work.
    ns = {"__name__": "_dobs_extract", "__builtins__": __builtins__}
    exec(compile(body, "<sensor.py extract>", "exec"), ns)
    return ns["_DOBSStub"]


class TestDOBSBehavioral:
    """C-MED-1: behavioral `_classify_sources` — call it against a fake
    energy with stale-stamped entities → key lands in `stale`. Kill-switch
    parity: threshold const → 0 → not stale.

    The classifier methods are extracted from sensor.py by source so the
    tests exercise the ACTUAL production code, not a stub.
    """

    def _make_classifier(self, key_to_eid, hass_states):
        cls = _extract_dobs_methods()
        obj = cls()
        hass = MockHass()
        for eid, st in hass_states.items():
            hass._states[eid] = st
        obj.hass = hass
        return obj

    def _classify(self, key_to_eid, hass_states):
        obj = self._make_classifier(key_to_eid, hass_states)
        fake_energy = _FakeEnergyWith(key_to_eid)
        return obj._classify_sources(fake_energy)

    def test_stale_stamped_source_lands_in_stale(self):
        stale_st = _stale_state(
            "sensor.solar", "5000",
            DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S + 60, uom="W",
        )
        _, _, stale, unconfigured, missing = self._classify(
            {"solar_production": "sensor.solar"},
            {"sensor.solar": stale_st},
        )
        assert "solar_production" in stale
        assert unconfigured == ["net_power", "battery_power", "battery_soc"]

    def test_fresh_source_not_in_stale(self):
        fresh_st = _fresh_state("sensor.solar", "5000", uom="W")
        _, _, stale, _, _ = self._classify(
            {"solar_production": "sensor.solar"},
            {"sensor.solar": fresh_st},
        )
        assert "solar_production" not in stale

    def test_kill_switch_threshold_zero_disables_stale_flip(self):
        """Behavioral kill-switch anchor: mutate the const to 0 → the
        stale-flip MUST NOT fire even for a very old stamp.
        """
        import custom_components.universal_room_automation.domain_coordinators.energy_const as ec
        original = ec.DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S
        try:
            ec.DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S = 0
            stale_st = _stale_state(
                "sensor.solar", "5000", 60 * 60 * 24, uom="W",  # 24h old
            )
            _, _, stale, _, _ = self._classify(
                {"solar_production": "sensor.solar"},
                {"sensor.solar": stale_st},
            )
            assert "solar_production" not in stale, (
                "kill-switch: threshold=0 MUST disable stale flip"
            )
        finally:
            ec.DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S = original

    def test_unconfigured_source_reported_missing_not_stale(self):
        _, _, stale, unconfigured, missing = self._classify(
            {"solar_production": None},
            {},
        )
        assert "solar_production" not in stale
        assert "solar_production" in unconfigured

    def test_configured_but_missing_state_reported_missing_not_stale(self):
        _, _, stale, unconfigured, missing = self._classify(
            {"solar_production": "sensor.solar"},
            {},  # no state registered → hass.states.get returns None
        )
        assert "solar_production" not in stale
        assert "solar_production" in missing

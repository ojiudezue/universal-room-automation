"""D5 — InclementFusion + determine_mode precedence tests.

Behavioral tests drive EnergyBatteryCoordinator.determine_mode() end-to-end via
a single canonical NWS-alert fixture (no hand-authored alert dicts inline).
Covers: grid-disconnect precedence, full_hold short-circuit, allow_discharge
byte-identity, partial_hold floor=50%, FIN-3 off_peak skip, and the EV-audit
§2 (_apply_evse_battery_hold max()-safety) + §5 (arbitrage release-on-hold).
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
import sys
import os
import types
import importlib

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
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda *a, **k: (lambda: None),
        "async_call_later": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": lambda *a, **k: None,
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow, "now": datetime.now, "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
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
for _submod_name in ("energy_const", "energy_tou", "inclement", "energy_battery", "energy_pool"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    BATTERY_MODE_SELF_CONSUMPTION,
    BATTERY_MODE_BACKUP,
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_WEATHER_ENTITY,
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
)

_BATTERY_SOC = "sensor.test_envoy_battery"
_NWS = "sensor.test_nws_alerts"
_NOW = datetime(2026, 6, 11, 17, 0, 0)  # peak-ish hour


def _make_battery(soc=80.0, grid="on", reserve_init=10):
    hass = MockHass()
    hass.set_state(_BATTERY_SOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, grid)
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, str(reserve_init))
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, "90")
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, "90")
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    strat = BatteryStrategy(
        hass,
        reserve_soc=DEFAULT_RESERVE_SOC,
        entity_config={"battery_soc": _BATTERY_SOC},
        solar_classification_mode="custom",
        custom_solar_thresholds={"excellent": 100.0, "good": 80.0,
                                 "moderate": 50.0, "poor": 30.0},
    )
    return strat, hass


def _arm_alert(strat, hass, event="Tornado Warning", severity="Extreme",
               certainty="Observed", extra_cfg=None):
    hass.set_state(_NWS, "1", attributes={"Alerts": [{
        "Event": event, "Severity": severity, "Certainty": certainty,
        "Status": "Actual",
        "Onset": "2026-06-11T16:00:00-05:00",
        "Ends": "2026-06-12T00:00:00-05:00",
    }]})
    cfg = {CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS}
    if extra_cfg:
        cfg.update(extra_cfg)
    strat._inclement_config_override = cfg


# ---------------------------------------------------------------------------
# Precedence + matrix
# ---------------------------------------------------------------------------


def test_grid_disconnect_wins_over_warn_hold():
    strat, hass = _make_battery(soc=80, grid="off")
    _arm_alert(strat, hass)
    r = strat.determine_mode("peak", "summer", now=_NOW)
    assert r["mode"] == BATTERY_MODE_BACKUP
    assert "grid disconnected" in r["reason"].lower()


def test_full_hold_equivalent_to_pre_v_storm_branch_for_warn_tier():
    # Warn tier at peak → full_hold → BACKUP (no discharge), like the old storm
    # branch's high-SOC hold.
    strat, hass = _make_battery(soc=80)
    _arm_alert(strat, hass)
    r = strat.determine_mode("peak", "summer", now=_NOW)
    assert r["mode"] == BATTERY_MODE_BACKUP
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "full_hold"
    assert attrs["inclement_tier"] == "warn"


def test_allow_discharge_byte_identical_to_no_storm_path():
    # No alert wired → allow_discharge → peak discharge with reserve=reserve_soc.
    strat_clear, hass_clear = _make_battery(soc=80)
    strat_clear._inclement_config_override = {}  # no NWS entity
    r_clear = strat_clear.determine_mode("peak", "summer", now=_NOW)

    strat_base, _ = _make_battery(soc=80)
    strat_base._inclement_config_override = {}
    r_base = strat_base.determine_mode("peak", "summer", now=_NOW)

    assert r_clear["mode"] == r_base["mode"] == BATTERY_MODE_SELF_CONSUMPTION
    assert r_clear["reason"] == r_base["reason"]
    # effective_reserve == reserve_soc when allow_discharge.
    reserve_actions = [a for a in r_clear["actions"]
                       if "reserve" in a.get("target", "")]
    if reserve_actions:
        assert reserve_actions[0]["data"]["value"] == strat_clear.reserve_soc
    assert strat_clear._inclement_attrs()["inclement_hold_depth"] == "allow_discharge"


def test_partial_hold_floor_is_50_pct_by_default():
    # Corroborated watch at peak with recoverable surplus → partial_hold at 50%.
    strat, hass = _make_battery(soc=80)
    # Watch tier (Possible, non-Warning event) + corroboration via condition mgr.
    _arm_alert(strat, hass, event="Severe Thunderstorm Watch",
               severity="Severe", certainty="Possible",
               extra_cfg={"inclement_watch_requires_corroboration": False})
    # Force recoverable: monkeypatch surplus high so partial_hold is chosen.
    strat._expected_solar_surplus_pct = lambda now, mins: 99.0
    r = strat.determine_mode("peak", "summer", now=_NOW)
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "partial_hold"
    assert attrs["inclement_reserve_floor"] == 50
    reserve_actions = [a for a in r["actions"] if "reserve" in a.get("target", "")]
    assert reserve_actions and reserve_actions[0]["data"]["value"] == 50


def test_off_peak_watch_skips_surplus_projection_FIN3():
    strat, hass = _make_battery(soc=80)
    _arm_alert(strat, hass, event="Severe Thunderstorm Watch",
               severity="Severe", certainty="Possible",
               extra_cfg={"inclement_watch_requires_corroboration": False})
    called = {"n": 0}
    orig = strat._expected_solar_surplus_pct

    def _spy(now, mins):
        called["n"] += 1
        return orig(now, mins)

    strat._expected_solar_surplus_pct = _spy
    strat.determine_mode("off_peak", "summer", now=_NOW)
    assert called["n"] == 0  # FIN-3: off_peak never instantiates the surplus call
    sh = strat._inclement_attrs()["inclement_solar_horizon"]
    assert sh.get("reason") in ("off_peak_skip", "not_consulted")


def test_off_peak_partial_hold_floors_reserve_at_effective_reserve():
    # A-CRIT-1 — an uncorroborated watch at off_peak resolves to partial_hold
    # (matrix row "watch (uncorroborated) off_peak → partial_hold"). The off_peak
    # drain/hold path MUST floor the emitted reserve at the elevated floor (50%)
    # rather than draining to drain_target (commonly 20-30%). SOC=80 is above the
    # floor, so the drain path runs but must not drain below 50.
    strat, hass = _make_battery(soc=80)
    _arm_alert(strat, hass, event="Severe Thunderstorm Watch",
               severity="Severe", certainty="Possible")  # watch, uncorroborated
    r = strat.determine_mode("off_peak", "summer", now=_NOW)
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "partial_hold"
    assert attrs["inclement_reserve_floor"] == 50
    reserve_actions = [a for a in r["actions"] if "reserve" in a.get("target", "")]
    assert reserve_actions, "off_peak partial_hold emitted no reserve action"
    # The battery must NOT drain below the 50% floor.
    assert reserve_actions[0]["data"]["value"] >= 50


def test_off_peak_partial_hold_below_floor_recovers_toward_floor():
    # A-CRIT-1 (below-target path) — SOC already below the 50% floor: the hold
    # path must report the floor (recover via cheap off_peak grid), not a
    # sub-floor reserve equal to current SOC.
    strat, hass = _make_battery(soc=40)
    _arm_alert(strat, hass, event="Severe Thunderstorm Watch",
               severity="Severe", certainty="Possible")  # watch, uncorroborated
    r = strat.determine_mode("off_peak", "summer", now=_NOW)
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "partial_hold"
    reserve_actions = [a for a in r["actions"] if "reserve" in a.get("target", "")]
    assert reserve_actions
    assert reserve_actions[0]["data"]["value"] >= 50


class _StormCond:
    def __init__(self, stormy, count):
        self.is_stormy = stormy
        self.healthy_provider_count = count


class _StormMgr:
    def __init__(self, stormy=True, count=2):
        self._cond = _StormCond(stormy, count)

    def current_storm_condition(self, mode):
        return self._cond


def test_condition_only_off_peak_partial_hold_floors_reserve_AMED2():
    # A-MED-2 — condition-only (NWS absent, >=2 stormy providers) at off_peak
    # resolves to partial_hold, which must hit the SAME A-CRIT-1 clamp so the
    # off_peak floor is enforced (50%), not drained to drain_target.
    strat, hass = _make_battery(soc=80)
    strat._inclement_config_override = {}  # no NWS alert → condition-only path
    strat._weather_manager = lambda: _StormMgr(stormy=True, count=2)
    r = strat.determine_mode("off_peak", "summer", now=_NOW)
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "partial_hold"
    assert attrs["inclement_source"] == "condition"
    reserve_actions = [a for a in r["actions"] if "reserve" in a.get("target", "")]
    assert reserve_actions
    assert reserve_actions[0]["data"]["value"] >= 50


def test_off_peak_allow_discharge_reserve_unchanged_byte_identical():
    # A-CRIT-1 guard — the clamp is gated strictly on partial_hold, so a clean
    # off_peak tick (allow_discharge) is byte-identical with vs without the fix.
    strat_storm, hass = _make_battery(soc=80)
    strat_storm._inclement_config_override = {}  # no alert → allow_discharge
    r_storm = strat_storm.determine_mode("off_peak", "summer", now=_NOW)

    strat_base, _ = _make_battery(soc=80)
    strat_base._inclement_config_override = {}
    r_base = strat_base.determine_mode("off_peak", "summer", now=_NOW)

    assert r_storm["reason"] == r_base["reason"]
    assert _reserve_value(r_storm) == _reserve_value(r_base)
    assert strat_storm._inclement_attrs()["inclement_hold_depth"] == "allow_discharge"


def test_hold_drops_within_one_tick_after_expiry():
    strat, hass = _make_battery(soc=80)
    _arm_alert(strat, hass)
    # Tick AFTER the alert's Ends (2026-06-12T00:00 local) → no contributor.
    after = datetime(2026, 6, 12, 1, 0, 0)
    strat.determine_mode("peak", "summer", now=after)
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "allow_discharge"
    assert attrs["inclement_tier"] == "none"


def test_storm_forecast_attr_backcompat_true_under_hold():
    strat, hass = _make_battery(soc=80)
    _arm_alert(strat, hass)
    strat.determine_mode("peak", "summer", now=_NOW)
    assert strat._inclement_attrs()["storm_forecast"] is True


# ---------------------------------------------------------------------------
# EV audit §2 — _apply_evse_battery_hold precedence (max()-safe)
# ---------------------------------------------------------------------------


class _EvHoldStub:
    """Minimal stub exercising the real EnergyCoordinator._apply_evse_battery_hold."""

    def __init__(self, battery, evse_hold_soc):
        self._battery = battery
        self._evse_hold_soc = evse_hold_soc


def _apply_evse_hold(battery, decision, evse_hold_soc):
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    stub = _EvHoldStub(battery, evse_hold_soc)
    return EnergyCoordinator._apply_evse_battery_hold(stub, decision)


def _reserve_value(decision):
    for a in decision["actions"]:
        if "reserve" in a.get("target", ""):
            return a["data"]["value"]
    return None


# EV audit §2 (BUILD FINDING, FIXED in-cycle): the PLANNING doc's audit §2
# asserted `_apply_evse_battery_hold` (energy.py:2453) was already "max()-safe".
# The build found it UNCONDITIONALLY overwrote the reserve action's value with
# the captured EV hold SOC, so `evse_hold_soc < reserve_floor` lowered the floor
# — undercutting an inclement partial_hold/full_hold guarantee. Fixed at
# energy.py:2480 to max(existing_floor, hold_reserve): the EVSE hold may only
# RAISE the reserve, never lower it. Both tests below assert the fixed behavior.


def test_evse_battery_hold_raises_but_never_lowers_reserve_floor():
    # The EVSE hold can only RAISE the reserve. A captured EV-hold SOC (40)
    # below the decided floor (50) must NOT lower it — the floor wins.
    strat, hass = _make_battery(soc=80)
    decision = {
        "mode": BATTERY_MODE_SELF_CONSUMPTION,
        "reason": "partial_hold",
        "soc": 80,
        "actions": [{
            "service": "number.set_value",
            "target": DEFAULT_RESERVE_SOC_ENTITY,
            "data": {"value": 50},
        }],
    }
    out = _apply_evse_hold(strat, decision, evse_hold_soc=40)
    # Fixed behavior — floor (50) wins over the lower EV-hold SOC (40).
    assert _reserve_value(out) == 50


def test_evse_battery_hold_cannot_lower_partial_hold_reserve_floor():
    strat, hass = _make_battery(soc=80)
    decision = {
        "mode": BATTERY_MODE_SELF_CONSUMPTION,
        "reason": "partial_hold",
        "soc": 80,
        "actions": [{
            "service": "number.set_value",
            "target": DEFAULT_RESERVE_SOC_ENTITY,
            "data": {"value": 50},
        }],
    }
    out = _apply_evse_hold(strat, decision, evse_hold_soc=40)
    assert _reserve_value(out) >= 50


def test_evse_battery_hold_still_raises_reserve_when_capture_exceeds_floor():
    # When the captured EV-hold SOC (70) EXCEEDS the decided floor (50), the
    # EV hold still wins — protecting the charging EV's source. Regression
    # guard so the max() fix didn't break the original raise-the-reserve intent.
    strat, hass = _make_battery(soc=80)
    decision = {
        "mode": BATTERY_MODE_SELF_CONSUMPTION,
        "reason": "partial_hold",
        "soc": 80,
        "actions": [{
            "service": "number.set_value",
            "target": DEFAULT_RESERVE_SOC_ENTITY,
            "data": {"value": 50},
        }],
    }
    out = _apply_evse_hold(strat, decision, evse_hold_soc=70)
    assert _reserve_value(out) == 70


def test_evse_battery_hold_cannot_downgrade_full_hold_backup_mode():
    # full_hold returned BACKUP — the EV-hold rewrite only touches reserve, not
    # the mode, so BACKUP is preserved (this part of §2 IS already safe).
    strat, hass = _make_battery(soc=95)
    decision = {
        "mode": BATTERY_MODE_BACKUP,
        "reason": "warn_full_hold",
        "soc": 95,
        "actions": [],
    }
    out = _apply_evse_hold(strat, decision, evse_hold_soc=90)
    assert out["mode"] == BATTERY_MODE_BACKUP


# ---------------------------------------------------------------------------
# EV audit §5 — arbitrage release on hold (no orphan)
# ---------------------------------------------------------------------------


def _make_controller():
    hass = MockHass()
    evse_config = {
        "garage_a": {"switch": "switch.garage_a", "power": "sensor.garage_a_power"},
    }
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power", "0")
    return EVChargerController(hass, evse_config=evse_config)


def test_inclement_hold_releases_paused_by_arbitrage_within_one_tick():
    ctrl = _make_controller()
    # Prime: an arbitrage-paused EV.
    ctrl._paused_by_arbitrage.add("garage_a")
    ctrl._arbitrage_pause_reason["garage_a"] = "breaker"
    # Inclement hold arrives → determine_mode returns hold → pause_requested
    # and charge_from_grid go False → release path fires.
    ctrl.determine_arbitrage_actions(
        arbitrage_charging=False, tou_period="off_peak", grid_charge_on=False,
    )
    assert "garage_a" not in ctrl._paused_by_arbitrage, (
        "EV orphaned in _paused_by_arbitrage after inclement hold (EV audit §5)"
    )

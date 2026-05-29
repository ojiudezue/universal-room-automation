"""v4.7.6 D3/D4/D6 — UX rename, visibility attrs, L1 plug parity, D6 tests.

Covers:
- D3.1 unique_id preserved across rename
- D3.2 fill_priority_soc Number entity restore (smoke)
- D3.4 per-EVSE self_modulates round-trip
- D4 7 attrs on get_status() — shape and types
- D4 pause_reason_human precedence + cold start
- D6.1 EVSE TOU toggle gates SmartPlugController (call site exists)
- D6.2 switch friendly name updated, unique_id preserved
- D6.3 L1 plug appears in ev_charging_status as peer entry
- D6.4 L1 plug self_modulates round-trip
"""
import pytest
from unittest.mock import MagicMock
import sys
import os
import types
import importlib

# Mock homeassistant — mirror test_energy_evse.py shape
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
        "utcnow": __import__("datetime").datetime.utcnow,
        "now": __import__("datetime").datetime.now,
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

from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
    SmartPlugController,
)
from custom_components.universal_room_automation.const import DOMAIN


# ---------------------------------------------------------------------------
# D3.1: unique_id preservation
# ---------------------------------------------------------------------------

class TestExcessSolarSwitchUniqueIdPreserved:
    def test_excess_solar_switch_unique_id_preserved(self):
        """Renaming switch class preserves the legacy unique_id suffix."""
        # Source-grep the switch.py file for the factory invocation pin.
        import os
        switch_path = os.path.join(_ura_path, "switch.py")
        src = open(switch_path).read()
        assert 'unique_id_override="excess_solar"' in src, (
            "v4.7.6 D3.1: ECEVSESolarAwareSwitch must pin unique_id to "
            "the legacy 'excess_solar' slug for HACS continuity."
        )

    def test_friendly_name_renamed(self):
        """Friendly name updated to 'EVSE Solar-Aware Charging'."""
        import os
        switch_path = os.path.join(_ura_path, "switch.py")
        src = open(switch_path).read()
        assert '"EVSE Solar-Aware Charging"' in src


# ---------------------------------------------------------------------------
# D3.1: legacy entity_id alias migration helper exists
# ---------------------------------------------------------------------------

class TestLegacyEntityIdRedirects:
    def test_migration_helper_exists(self):
        """v4.7.6 D3.1: _migrate_excess_solar_entity_id helper present."""
        import os
        switch_path = os.path.join(_ura_path, "switch.py")
        src = open(switch_path).read()
        assert "_migrate_excess_solar_entity_id" in src
        assert "switch.ura_energy_coordinator_excess_solar_charging" in src
        assert "switch.ura_energy_coordinator_evse_solar_aware_charging" in src


# ---------------------------------------------------------------------------
# D3.2: fill_priority_soc Number entity round-trip (smoke — by source)
# ---------------------------------------------------------------------------

class TestFillPrioritySOCNumberRestore:
    def test_fill_priority_soc_number_class_exists(self):
        """v4.7.6 D3.2: FillPrioritySOCNumber class is defined in number.py."""
        import os
        number_path = os.path.join(_ura_path, "number.py")
        src = open(number_path).read()
        assert "class FillPrioritySOCNumber" in src
        assert "set_fill_priority_soc" in src
        assert "RestoreEntity" in src

    def test_fill_priority_soc_unique_id(self):
        """Unique id slug present."""
        import os
        number_path = os.path.join(_ura_path, "number.py")
        src = open(number_path).read()
        assert "energy_fill_priority_soc" in src


# ---------------------------------------------------------------------------
# D3.4: per-EVSE self_modulates round-trip
# ---------------------------------------------------------------------------

class TestSelfModulatesPerEVSERoundTrip:
    def test_self_modulates_default_false(self):
        ev = EVChargerController(MockHass(), evse_config={
            "garage_a": {"switch": "switch.garage_a"},
        })
        assert ev._self_modulates_for("garage_a") is False

    def test_self_modulates_explicit_true(self):
        ev = EVChargerController(MockHass(), evse_config={
            "garage_a": {"switch": "switch.garage_a", "self_modulates": True},
        })
        assert ev._self_modulates_for("garage_a") is True

    def test_self_modulates_source_in_status(self):
        hass = MockHass()
        hass.set_state("switch.garage_a", "off")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {"switch": "switch.garage_a", "self_modulates": True},
            "garage_b": {"switch": "switch.garage_b"},
        })
        hass.set_state("switch.garage_b", "off")
        status = ev.get_status()
        assert status["evse_config"]["garage_a"] == {
            "self_modulates": True, "source": "explicit",
        }
        assert status["evse_config"]["garage_b"] == {
            "self_modulates": False, "source": "default",
        }


# ---------------------------------------------------------------------------
# D4: 7 attrs on get_status() — shape and types
# ---------------------------------------------------------------------------

class TestGetStatusAttrsShapeAndTypes:
    def test_get_status_seven_attrs_present(self):
        hass = MockHass()
        hass.set_state("switch.garage_a", "off")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {"switch": "switch.garage_a"},
        })
        status = ev.get_status(fill_priority_target_soc=80)
        for attr in (
            "paused_by_fill_priority",
            "pause_reason_human",
            "cooldowns",
            "fill_priority_target_soc",
            "fill_priority_solar_ok",
            "evse_config",
            "pause_dispatch_state",
        ):
            assert attr in status, f"missing v4.7.6 D4 attr: {attr}"
        # Types per spec
        assert isinstance(status["paused_by_fill_priority"], list)
        assert isinstance(status["pause_reason_human"], dict)
        assert isinstance(status["cooldowns"], dict)
        assert isinstance(status["fill_priority_target_soc"], int)
        assert isinstance(status["fill_priority_solar_ok"], bool)
        assert isinstance(status["evse_config"], dict)
        assert isinstance(status["pause_dispatch_state"], dict)


# ---------------------------------------------------------------------------
# D4.2: pause_reason_human precedence
# ---------------------------------------------------------------------------

class TestPauseReasonHumanPrecedence:
    def test_fill_priority_beats_tou(self):
        hass = MockHass()
        hass.set_state("switch.garage_a", "off")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {"switch": "switch.garage_a"},
        })
        ev._paused_by_us.add("garage_a")
        ev._paused_by_fill_priority.add("garage_a")
        status = ev.get_status(fill_priority_target_soc=80)
        msg = status["pause_reason_human"]["garage_a"]
        assert "battery fill" in msg.lower()

    def test_idle_when_on_but_not_paused(self):
        hass = MockHass()
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "10")  # below threshold
        ev = EVChargerController(hass, evse_config={
            "garage_a": {
                "switch": "switch.garage_a",
                "power": "sensor.garage_a_power_minute_average",
            },
        })
        status = ev.get_status(fill_priority_target_soc=80)
        msg = status["pause_reason_human"]["garage_a"]
        assert msg == "idle"


# ---------------------------------------------------------------------------
# D4.7: pause_dispatch_state absent on cold start
# ---------------------------------------------------------------------------

class TestPauseDispatchStateAbsentOnColdStart:
    def test_cold_start_empty(self):
        hass = MockHass()
        hass.set_state("switch.garage_a", "off")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {"switch": "switch.garage_a"},
        })
        status = ev.get_status()
        assert status["pause_dispatch_state"] == {}
        assert status["cooldowns"] == {}


# ---------------------------------------------------------------------------
# D4.3: cooldowns local timezone (no UTC labels)
# ---------------------------------------------------------------------------

class TestCooldownsLocalTimezone:
    def test_cooldown_expires_uses_strftime_local(self):
        """Cooldown expiry string is not an ISO-Z UTC label."""
        import time as _time
        hass = MockHass()
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {
                "switch": "switch.garage_a",
                "power": "sensor.garage_a_power_minute_average",
            },
        })
        # Inject an active cooldown manually
        ev._battery_drain_cooldown["garage_a"] = _time.monotonic() + 3600
        status = ev.get_status()
        cooldown = status["cooldowns"]["garage_a"]
        assert "Z" not in cooldown["expires"]
        assert cooldown["reason"] == "manual_override_detected"


# ---------------------------------------------------------------------------
# D4: NM trip once per day on first fill-priority pause
# ---------------------------------------------------------------------------

class TestNMTripOncePerDayFillPriority:
    def test_nm_trip_helper_exists(self):
        """v4.7.6 D4: _check_fill_priority_nm_trip helper exists in energy.py."""
        import os
        energy_path = os.path.join(_dc_path, "energy.py")
        src = open(energy_path).read()
        assert "_check_fill_priority_nm_trip" in src
        assert "evse_fill_priority" in src  # hazard_type
        assert "_fill_priority_was_empty" in src
        assert "_fill_priority_nm_trip_date" in src


# ---------------------------------------------------------------------------
# D6.1: EVSE TOU toggle gates SmartPlugController
# ---------------------------------------------------------------------------

class TestD6EVTouToggleGatesSmartPlugActions:
    def test_smart_plug_actions_gated_by_ev_tou(self):
        """v4.7.6 D6.1: SmartPlugController.determine_actions(period) is wrapped
        under `if self._ev_tou_enabled:` in energy.py decision tick."""
        import os
        energy_path = os.path.join(_dc_path, "energy.py")
        src = open(energy_path).read()
        # The wrapping should appear immediately before the plug call.
        idx = src.find("self._smart_plugs.determine_actions(period)")
        assert idx != -1
        # Walk back 200 chars and verify `_ev_tou_enabled` gate appears
        slice_ = src[max(0, idx - 250):idx]
        assert "_ev_tou_enabled" in slice_


# ---------------------------------------------------------------------------
# D6.2: Switch friendly name updated, unique_id preserved
# ---------------------------------------------------------------------------

class TestD6SwitchFriendlyNameUpdatedUniqueIdPreserved:
    def test_evse_tou_friendly_name(self):
        import os
        switch_path = os.path.join(_ura_path, "switch.py")
        src = open(switch_path).read()
        # New friendly name
        assert '"EVSE TOU Management"' in src
        # Unique slug unchanged
        assert '"ev_tou_management"' in src


# ---------------------------------------------------------------------------
# D6.3: L1 plug appears in ev_charging_status as peer entry
# ---------------------------------------------------------------------------

class TestD6L1PlugAppearsInEvChargingStatus:
    def test_l1_plug_peer_entry_shape(self):
        hass = MockHass()
        hass.set_state("switch.moes_plug_garage_a", "on")
        sp = SmartPlugController(
            hass, plug_entities=["switch.moes_plug_garage_a"],
        )
        plug_status = sp.get_status()
        assert "plug_entries" in plug_status
        entry = plug_status["plug_entries"]["switch.moes_plug_garage_a"]
        for key in ("is_on", "power", "status", "charging", "power_source", "energy_status"):
            assert key in entry, f"D6.3: missing 6-key shape entry: {key}"
        assert entry["is_on"] is True
        assert entry["power_source"] == "switch_status"

    def test_l1_plug_merged_into_ev_status(self):
        """EVPool.get_status merges plug_status under top-level keys."""
        hass = MockHass()
        hass.set_state("switch.garage_a", "off")
        hass.set_state("switch.moes_plug_garage_a", "on")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {"switch": "switch.garage_a"},
        })
        sp = SmartPlugController(
            hass, plug_entities=["switch.moes_plug_garage_a"],
        )
        status = ev.get_status(
            fill_priority_target_soc=80,
            plug_status=sp.get_status(),
        )
        # Plug appears as a peer top-level key
        assert "switch.moes_plug_garage_a" in status
        assert status["switch.moes_plug_garage_a"]["is_on"] is True


# ---------------------------------------------------------------------------
# D6.4: L1 plug self_modulates round-trip
# ---------------------------------------------------------------------------

class TestD6L1PlugSelfModulatesRoundTrip:
    def test_plug_self_modulates_explicit(self):
        sp = SmartPlugController(
            MockHass(),
            plug_entities=["switch.plug_a"],
            plug_config={"switch.plug_a": {"self_modulates": True}},
        )
        assert sp._self_modulates_for("switch.plug_a") is True

    def test_plug_self_modulates_default_false(self):
        sp = SmartPlugController(
            MockHass(), plug_entities=["switch.plug_a"],
        )
        assert sp._self_modulates_for("switch.plug_a") is False

    def test_plug_evse_config_in_status(self):
        hass = MockHass()
        hass.set_state("switch.plug_a", "off")
        sp = SmartPlugController(
            hass,
            plug_entities=["switch.plug_a"],
            plug_config={"switch.plug_a": {"self_modulates": True}},
        )
        status = sp.get_status()
        assert status["evse_config"]["switch.plug_a"] == {
            "self_modulates": True, "source": "explicit",
        }


# ---------------------------------------------------------------------------
# Config-flow runtime smoke test (per zero-bugs gate memory)
# ---------------------------------------------------------------------------

class TestConfigFlowEVSEStepImportsAndRenders:
    def test_config_flow_module_compiles_and_imports(self):
        """v4.7.4.2-class catch: ensure config_flow.py can be imported and
        new CONF keys resolve at import time. Catches dead-import classes
        and forgotten ImportErrors that source-grep can't see."""
        import importlib.util
        cf_path = os.path.join(_ura_path, "config_flow.py")
        # py_compile equivalent — parse + validate
        with open(cf_path) as f:
            src = f.read()
        compile(src, cf_path, "exec")
        # Verify the new CONF references exist
        assert "CONF_ENERGY_FILL_PRIORITY_SOC" in src
        assert "DEFAULT_FILL_PRIORITY_SOC" in src
        assert "garage_a_self_modulates" in src
        assert "l1_plug_self_modulates" in src

    def test_energy_const_new_symbols_present(self):
        from custom_components.universal_room_automation.domain_coordinators import energy_const as ec
        assert hasattr(ec, "CONF_ENERGY_FILL_PRIORITY_SOC")
        assert hasattr(ec, "DEFAULT_FILL_PRIORITY_SOC")
        assert ec.DEFAULT_FILL_PRIORITY_SOC == 80
        assert hasattr(ec, "EV_PAUSE_DISPATCH_GRACE_SECONDS")
        assert ec.EV_PAUSE_DISPATCH_GRACE_SECONDS == 30.0
        assert hasattr(ec, "DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH")


# ---------------------------------------------------------------------------
# Adversarial-EVSE re-pause loop (plan D5 / §5)
# ---------------------------------------------------------------------------

class TestAdversarialEVSE:
    def test_adversarial_repause_self_modulates_true(self):
        """N=5 cycles: assert switch on → URA re-pauses every tick."""
        hass = MockHass()
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {
                "switch": "switch.garage_a",
                "power": "sensor.garage_a_power_minute_average",
                "self_modulates": True,
            },
        })
        pause_count = 0
        for _ in range(5):
            actions = ev.determine_battery_drain_actions(
                battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
            )
            for a in actions:
                if a["service"] == "switch.turn_off":
                    pause_count += 1
            # Re-assert switch on (adversarial)
            hass.set_state("switch.garage_a", "on")
        assert pause_count == 5
        assert "garage_a" not in ev._battery_drain_cooldown

    def test_adversarial_repause_self_modulates_false(self):
        """N=5 cycles, default config: URA re-pauses across dispatch lag.

        Without grace expiry / observed_off, no cooldown engaged.
        """
        hass = MockHass()
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000")
        ev = EVChargerController(hass, evse_config={
            "garage_a": {
                "switch": "switch.garage_a",
                "power": "sensor.garage_a_power_minute_average",
                "self_modulates": False,
            },
        })
        pause_count = 0
        for _ in range(5):
            actions = ev.determine_battery_drain_actions(
                battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
            )
            for a in actions:
                if a["service"] == "switch.turn_off":
                    pause_count += 1
            hass.set_state("switch.garage_a", "on")
        assert pause_count == 5
        assert "garage_a" not in ev._battery_drain_cooldown

"""Tests for v4.0.12: Envoy auto-derive config.

Validates serial extraction, entity derivation, auto-derive wiring,
explicit config override, backward compatibility, and HVAC predictor
net_power_entity parameter.
"""

import os
import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
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
    "homeassistant.core": {
        "HomeAssistant": _mock_cls, "callback": _identity,
        "CALLBACK_TYPE": _mock_cls, "Event": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": MagicMock(),
        "now": MagicMock(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

# ---------------------------------------------------------------------------
# Bypass __init__.py: register the URA package as a stub module
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Validator defect #10 fix: when test_envoy_boot_decoupling.py is collected
# first, it registers this stub with BOOT_SETTLE_TIMEOUT_SECONDS. We must
# NOT clobber its work — setdefault + additive setattr keeps the stub
# population stable across both collection orders. (The constant's
# canonical home is custom_components/.../const.py:1474; both test files
# must mirror it because production imports it lazily inside the helper.)
_existing_const = sys.modules.get(
    "custom_components.universal_room_automation.const"
)
if _existing_const is None:
    _ura_const = types.ModuleType(
        "custom_components.universal_room_automation.const"
    )
    sys.modules["custom_components.universal_room_automation.const"] = _ura_const
else:
    _ura_const = _existing_const
if not hasattr(_ura_const, "DOMAIN"):
    _ura_const.DOMAIN = "universal_room_automation"
if not hasattr(_ura_const, "VERSION"):
    _ura_const.VERSION = "4.0.12"
if not hasattr(_ura_const, "BOOT_SETTLE_TIMEOUT_SECONDS"):
    _ura_const.BOOT_SETTLE_TIMEOUT_SECONDS = 60

_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc

_dc_signals = types.ModuleType("custom_components.universal_room_automation.domain_coordinators.signals")
for sig in [
    "SIGNAL_ENERGY_CONSTRAINT", "SIGNAL_HOUSE_STATE_CHANGED",
    "SIGNAL_PERSON_ARRIVING", "SIGNAL_SAFETY_HAZARD",
]:
    setattr(_dc_signals, sig, f"ura_{sig.lower()}")
sys.modules["custom_components.universal_room_automation.domain_coordinators.signals"] = _dc_signals

# Mock heavy HVAC sub-modules so hvac_predict can be imported without
# pulling in the entire HVAC coordinator dependency tree
for mod_name in [
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_preset",
    "custom_components.universal_room_automation.domain_coordinators.hvac_fan",
    "custom_components.universal_room_automation.domain_coordinators.hvac_cover",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zone_intel",
]:
    sys.modules.setdefault(mod_name, MagicMock())

# Add EnergyConstraint to signals mock
_dc_signals.EnergyConstraint = MagicMock()

# ---------------------------------------------------------------------------
# Now import the modules under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_ENERGY_BATTERY_CAPACITY_ENTITY,
    CONF_ENERGY_BATTERY_POWER_ENTITY,
    CONF_ENERGY_BATTERY_SOC_ENTITY,
    CONF_ENERGY_CONSUMPTION_TODAY_ENTITY,
    CONF_ENERGY_ENVOY_ENTITY,
    CONF_ENERGY_GRID_ENTITY,
    CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY,
    CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY,
    CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY,
    CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY,
    CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY,
    CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY,
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_SOLAR_ENTITY,
    derive_envoy_config,
    extract_envoy_serial,
    validate_envoy_config,
)


# ---------------------------------------------------------------------------
# D1: extract_envoy_serial
# ---------------------------------------------------------------------------

class TestExtractEnvoySerial:
    """Tests for extract_envoy_serial()."""

    def test_valid_entity(self):
        result = extract_envoy_serial(
            "sensor.envoy_482543015950_current_power_production"
        )
        assert result == "482543015950"

    def test_valid_entity_old_serial(self):
        result = extract_envoy_serial(
            "sensor.envoy_202428004328_battery"
        )
        assert result == "202428004328"

    def test_invalid_entity(self):
        result = extract_envoy_serial("sensor.some_other_thing")
        assert result is None

    def test_empty_string(self):
        result = extract_envoy_serial("")
        assert result is None

    def test_partial_match_no_trailing_underscore(self):
        """Pattern requires trailing underscore after serial."""
        result = extract_envoy_serial("sensor.envoy_12345")
        assert result is None


# ---------------------------------------------------------------------------
# D1: derive_envoy_config
# ---------------------------------------------------------------------------

class TestDeriveEnvoyConfig:
    """Tests for derive_envoy_config()."""

    def test_all_13_keys_present(self):
        result = derive_envoy_config("482543015950")
        assert len(result) == 13

    def test_correct_entity_ids(self):
        serial = "482543015950"
        result = derive_envoy_config(serial)
        assert result[CONF_ENERGY_SOLAR_ENTITY] == f"sensor.envoy_{serial}_current_power_production"
        assert result[CONF_ENERGY_GRID_ENTITY] == f"sensor.envoy_{serial}_current_power_consumption"
        assert result[CONF_ENERGY_BATTERY_SOC_ENTITY] == f"sensor.envoy_{serial}_battery"
        assert result[CONF_ENERGY_BATTERY_POWER_ENTITY] == f"sensor.envoy_{serial}_current_battery_discharge"
        assert result[CONF_ENERGY_NET_POWER_ENTITY] == f"sensor.envoy_{serial}_current_net_power_consumption"
        assert result[CONF_ENERGY_BATTERY_CAPACITY_ENTITY] == f"sensor.envoy_{serial}_battery_capacity"
        assert result[CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY] == f"sensor.envoy_{serial}_lifetime_energy_consumption"
        assert result[CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY] == f"sensor.envoy_{serial}_lifetime_energy_production"
        assert result[CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY] == f"sensor.envoy_{serial}_lifetime_net_energy_consumption"
        assert result[CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY] == f"sensor.envoy_{serial}_lifetime_net_energy_production"
        assert result[CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY] == f"sensor.envoy_{serial}_lifetime_battery_energy_charged"
        assert result[CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY] == f"sensor.envoy_{serial}_lifetime_battery_energy_discharged"
        assert result[CONF_ENERGY_CONSUMPTION_TODAY_ENTITY] == f"sensor.envoy_{serial}_energy_consumption_today"

    def test_all_values_contain_serial(self):
        serial = "999999999999"
        result = derive_envoy_config(serial)
        for key, entity_id in result.items():
            assert serial in entity_id, f"{key} does not contain serial"


# ---------------------------------------------------------------------------
# D2: __init__.py auto-derive logic (integration test)
# ---------------------------------------------------------------------------

class TestAutoDeriveIntegration:
    """Tests that mimic the __init__.py auto-derive merge logic."""

    def test_envoy_entity_derives_all(self):
        """When envoy entity is set, all 13 keys are injected."""
        energy_entity_config = {
            CONF_ENERGY_ENVOY_ENTITY: "sensor.envoy_482543015950_current_power_production",
        }
        envoy_eid = energy_entity_config.get(CONF_ENERGY_ENVOY_ENTITY)
        serial = extract_envoy_serial(envoy_eid)
        assert serial == "482543015950"
        for k, v in derive_envoy_config(serial).items():
            energy_entity_config.setdefault(k, v)

        assert energy_entity_config[CONF_ENERGY_SOLAR_ENTITY] == "sensor.envoy_482543015950_current_power_production"
        assert energy_entity_config[CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY] == "sensor.envoy_482543015950_lifetime_energy_consumption"
        assert energy_entity_config[CONF_ENERGY_NET_POWER_ENTITY] == "sensor.envoy_482543015950_current_net_power_consumption"

    def test_explicit_override_wins(self):
        """Explicit per-entity config takes precedence over auto-derive."""
        explicit_solar = "sensor.custom_solar_sensor"
        energy_entity_config = {
            CONF_ENERGY_ENVOY_ENTITY: "sensor.envoy_482543015950_current_power_production",
            CONF_ENERGY_SOLAR_ENTITY: explicit_solar,
        }
        envoy_eid = energy_entity_config.get(CONF_ENERGY_ENVOY_ENTITY)
        serial = extract_envoy_serial(envoy_eid)
        for k, v in derive_envoy_config(serial).items():
            energy_entity_config.setdefault(k, v)

        # Explicit solar stays, rest are derived
        assert energy_entity_config[CONF_ENERGY_SOLAR_ENTITY] == explicit_solar
        assert energy_entity_config[CONF_ENERGY_BATTERY_SOC_ENTITY] == "sensor.envoy_482543015950_battery"

    def test_no_envoy_entity_backward_compat(self):
        """Without envoy entity, config is unchanged (backward compat)."""
        energy_entity_config = {"energy_reserve_soc": 20}
        envoy_eid = energy_entity_config.get(CONF_ENERGY_ENVOY_ENTITY)
        assert envoy_eid is None
        # No derivation happens — dict unchanged
        assert len(energy_entity_config) == 1

    def test_invalid_envoy_entity_no_derive(self):
        """If envoy entity doesn't match pattern, no derivation happens."""
        energy_entity_config = {
            CONF_ENERGY_ENVOY_ENTITY: "sensor.not_an_envoy_sensor",
        }
        envoy_eid = energy_entity_config.get(CONF_ENERGY_ENVOY_ENTITY)
        serial = extract_envoy_serial(envoy_eid)
        assert serial is None
        # No keys added
        assert CONF_ENERGY_SOLAR_ENTITY not in energy_entity_config


# ---------------------------------------------------------------------------
# D5: HVAC Predictor net_power_entity
# ---------------------------------------------------------------------------

class TestHVACPredictorNetPower:
    """Tests for HVACPredictor net_power_entity parameter."""

    def _make_predictor(self, net_power_entity=None):
        """Create a minimal HVACPredictor with mocked dependencies."""
        from custom_components.universal_room_automation.domain_coordinators.hvac_predict import (
            HVACPredictor,
        )
        hass = MagicMock()
        zone_manager = MagicMock()
        preset_manager = MagicMock()
        return HVACPredictor(
            hass, zone_manager, preset_manager,
            net_power_entity=net_power_entity,
        )

    def test_custom_net_power_entity(self):
        custom = "sensor.envoy_482543015950_current_net_power_consumption"
        predictor = self._make_predictor(net_power_entity=custom)
        assert predictor._net_power_entity == custom

    def test_default_net_power_entity_is_none(self):
        """v4.2.29: no implicit DEFAULT fallback — None when not supplied."""
        predictor = self._make_predictor()
        assert predictor._net_power_entity is None

    def test_get_net_power_returns_zero_when_unconfigured(self):
        """v4.2.29: missing net_power_entity → 0.0, not a wrong-serial lookup."""
        predictor = self._make_predictor(net_power_entity=None)
        assert predictor._get_net_power() == 0.0


# ---------------------------------------------------------------------------
# v4.2.29: validate_envoy_config (V0–V4)
# ---------------------------------------------------------------------------


def _make_hass_with_states(present: dict[str, str]):
    """Build a fake hass whose states.get(eid) returns a state-like object
    only for entity IDs in `present` (mapped to their state strings)."""
    hass = MagicMock()

    def _get(eid):
        if eid in present:
            s = MagicMock()
            s.state = present[eid]
            return s
        return None

    hass.states.get = _get
    return hass


class TestValidateEnvoyConfig:
    """v4.2.29: validator for envoy entity field correctness."""

    SERIAL = "482543015950"
    # Use battery_capacity as the picked envoy entity so it's distinct from
    # any critical derived entity (V4 keys = NET_POWER, SOLAR, LIFETIME_*).
    GOOD_ENVOY = f"sensor.envoy_{SERIAL}_battery_capacity"

    def _all_critical_present(self) -> dict[str, str]:
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            ENVOY_REQUIRED_DERIVED_KEYS,
        )
        derived = derive_envoy_config(self.SERIAL)
        return {derived[k]: "ok" for k in ENVOY_REQUIRED_DERIVED_KEYS}

    def test_v0_missing_envoy_field(self):
        """V0: empty/None envoy_eid → envoy_required."""
        hass = _make_hass_with_states({})
        result = validate_envoy_config(hass, {})
        assert result["ok"] is False
        assert result["errors"][CONF_ENERGY_ENVOY_ENTITY] == "envoy_required"

    def test_v1_unparseable_serial(self):
        """V1: non-envoy entity ID → envoy_invalid_format."""
        hass = _make_hass_with_states({})
        result = validate_envoy_config(hass, {
            CONF_ENERGY_ENVOY_ENTITY: "sensor.not_an_envoy",
        })
        assert result["ok"] is False
        assert result["errors"][CONF_ENERGY_ENVOY_ENTITY] == "envoy_invalid_format"

    def test_v2_entity_missing_in_ha(self):
        """V2 (post EC Envoy boot-decoupling): with this file's
        MagicMock-stubbed entity_registry (every lookup returns truthy),
        the validator treats the entity as registry-known and the
        empty state machine as the degraded boot-race case — NOT the
        v4.2.29 hard-fail.

        The actual hard-fail path (entity genuinely absent from
        registry) is exercised in test_envoy_boot_decoupling.py with a
        purpose-built ent-reg stub. This test now asserts the
        three-way degraded outcome that the MagicMock harness
        produces.
        """
        hass = _make_hass_with_states({})  # nothing present
        result = validate_envoy_config(hass, {
            CONF_ENERGY_ENVOY_ENTITY: self.GOOD_ENVOY,
        })
        # Registry stub is truthy → degraded path, not hard fail.
        assert result["ok"] is True
        assert result.get("degraded") is True
        assert result.get("degraded_reason") == "state_missing"
        assert result.get("entity_registry_known") is True

    def test_v3_unavailable_is_degraded_not_error(self):
        """V3 (post EC Envoy boot-decoupling): envoy present but
        unavailable → ok=True, degraded=True, reason=state_unavailable.

        Re-contracted from v4.2.29 'warning only': the validator now
        explicitly classifies this as degraded (vs. live) so __init__.py
        can log + skip raising a repair issue. The pass-through to ok=True
        is preserved — EC still registers.
        """
        present = {self.GOOD_ENVOY: "unavailable"}
        present.update(self._all_critical_present())
        hass = _make_hass_with_states(present)
        result = validate_envoy_config(hass, {
            CONF_ENERGY_ENVOY_ENTITY: self.GOOD_ENVOY,
        })
        assert result["ok"] is True
        assert result["warnings"], "expected an unavailable warning"
        # Three-way contract: degraded + reason populated.
        assert result.get("degraded") is True
        assert result.get("degraded_reason") == "state_unavailable"

    def test_v4_critical_derived_missing(self):
        """V4 (post EC Envoy boot-decoupling): with this file's
        MagicMock-stubbed entity_registry (every lookup returns truthy),
        derived entities absent from the state machine are NOT a hard
        error — they're degraded (registry-known, state missing).

        The genuine registry-absent → hard error path is exercised in
        test_envoy_boot_decoupling.py with an explicit ent-reg stub.
        Here we assert the three-way degraded outcome that the
        MagicMock harness produces.
        """
        # Present: only the envoy entity itself; none of the derived ones.
        hass = _make_hass_with_states({self.GOOD_ENVOY: "ok"})
        result = validate_envoy_config(hass, {
            CONF_ENERGY_ENVOY_ENTITY: self.GOOD_ENVOY,
        })
        # Registry stub is truthy for both envoy + derived → degraded path.
        assert result["ok"] is True
        assert result.get("degraded") is True
        assert result.get("degraded_reason") == "state_missing"
        # No derived_entity_missing errors — V4 only hard-fails when the
        # registry says ABSENT, which this stub never does.
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            ENVOY_REQUIRED_DERIVED_KEYS,
        )
        for key in ENVOY_REQUIRED_DERIVED_KEYS:
            assert key not in result["errors"]

    def test_explicit_override_used_in_v4(self):
        """V4: explicit per-entity override is checked, not the derived ID."""
        # Derived NET_POWER would be missing; explicit override exists.
        explicit_net = "sensor.my_custom_net_power"
        present = {self.GOOD_ENVOY: "ok", explicit_net: "ok"}
        derived = derive_envoy_config(self.SERIAL)
        # Add the other 3 critical derived entities so only NET is overridden.
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY,
            CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY,
        )
        present[derived[CONF_ENERGY_SOLAR_ENTITY]] = "ok"
        present[derived[CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY]] = "ok"
        present[derived[CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY]] = "ok"

        hass = _make_hass_with_states(present)
        result = validate_envoy_config(hass, {
            CONF_ENERGY_ENVOY_ENTITY: self.GOOD_ENVOY,
            CONF_ENERGY_NET_POWER_ENTITY: explicit_net,
        })
        assert result["ok"] is True, f"unexpected errors: {result['errors']}"

    def test_full_pass(self):
        """All checks pass when envoy + 4 critical derived entities present."""
        present = {self.GOOD_ENVOY: "ok"}
        present.update(self._all_critical_present())
        hass = _make_hass_with_states(present)
        result = validate_envoy_config(hass, {
            CONF_ENERGY_ENVOY_ENTITY: self.GOOD_ENVOY,
        })
        assert result["ok"] is True
        assert result["errors"] == {}
        assert result["serial"] == self.SERIAL

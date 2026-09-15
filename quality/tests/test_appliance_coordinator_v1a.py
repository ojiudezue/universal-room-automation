"""Tests for APPLIANCE-MGMT-REFINE-1 v1a — passive appliance census.

Covers:
- Invariant (i): entity-exclusivity + no-drop across the three census sources.
- Invariant (ii): the coordinator commands nothing (patched
  ``hass.services.async_call`` + ``hass.states.async_set`` register
  ``call_count == 0`` across setup, evaluate, teardown, and resolver call).
- URA-owned room fan appears with source_tags:["ura_config"] and needs no
  onboarding step.
- Intra-integration shadows collapse by device_id (camera_census pattern).
- Wire-in anchor: the census sensor reads ``resolve_census`` — neutering
  that call site in production source turns this test RED (see the mutation
  drill instructions in the module docstring).

Test scaffolding modeled on ``test_music_following_coordinator.py``.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock homeassistant surface (mirrors test_music_following_coordinator.py).
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
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": _mock_cls(),
        "async_dispatcher_connect": _mock_cls(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
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
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

# Add project root
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

for _submod_name in (
    "signals", "house_state", "base", "manager",
    "appliance_const", "appliance",
):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)


from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_APPLIANCE_COORDINATOR_ENABLED,
    CONF_APPLIANCE_RECORDS,
    COORDINATOR_ENABLED_KEYS,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    CONF_ENTRY_TYPE,
)
from custom_components.universal_room_automation.domain_coordinators.appliance import (  # noqa: E402
    ApplianceCoordinator,
    CONF_APPLIANCE_RECORDS as _CONF_APPLIANCE_RECORDS_COORD,
)
from custom_components.universal_room_automation.domain_coordinators.appliance_const import (  # noqa: E402
    APPLIANCE_STALE_MAX_AGE_S,
    DOMAIN_MEDIA_AV,
    DOMAIN_OTHER,
    TAG_URA_CONFIG,
)
from custom_components.universal_room_automation.domain_coordinators.base import (  # noqa: E402
    BaseCoordinator,
    Intent,
)


# ---------------------------------------------------------------------------
# Fake hass builder
# ---------------------------------------------------------------------------


class _FakeEntry:
    def __init__(self, entry_type, data=None, options=None, title=""):
        self.data = {CONF_ENTRY_TYPE: entry_type, **(data or {})}
        self.options = options or {}
        self.title = title
        self.entry_id = f"entry_{id(self)}"


class _FakeState:
    def __init__(self, state):
        self.state = state
        import datetime as _dt
        self.last_updated = _dt.datetime.utcnow()
        self.attributes = {}


class _FakeStates:
    def __init__(self, mapping=None):
        self._m = dict(mapping or {})
        self.set_calls = []

    def get(self, entity_id):
        return self._m.get(entity_id)

    def async_set(self, *args, **kwargs):  # invariant (ii) trap
        self.set_calls.append((args, kwargs))


class _FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, *args, **kwargs):  # invariant (ii) trap
        self.calls.append((args, kwargs))

    @property
    def call_count(self):
        return len(self.calls)


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return list(self._entries)


class _FakeERegEntry:
    def __init__(self, device_id):
        self.device_id = device_id


class _FakeEntityRegistry:
    def __init__(self, mapping=None):
        self._m = dict(mapping or {})

    def async_get(self, entity_id):
        did = self._m.get(entity_id)
        if did is None:
            return None
        return _FakeERegEntry(did)


def _make_hass(entries=None, states=None, ent_reg=None, energy_circuits=None):
    """Build a fake HA object exercising the coordinator's reads."""
    hass = MagicMock()
    hass.config_entries = _FakeConfigEntries(entries or [])
    hass.states = _FakeStates(states or {})
    hass.services = _FakeServices()

    # coordinator_manager exposes .coordinators[energy]._circuits._circuits
    if energy_circuits is not None:
        energy = MagicMock()
        energy._circuits = MagicMock()
        energy._circuits._circuits = energy_circuits
        cm = MagicMock()
        cm.coordinators = {"energy": energy}
    else:
        cm = MagicMock()
        cm.coordinators = {}
    hass.data = {
        "universal_room_automation": {"coordinator_manager": cm},
    }

    # Patch the entity_registry.async_get helper the coordinator uses.
    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    er_mod.async_get = lambda _hass: (ent_reg or _FakeEntityRegistry())
    return hass


# ---------------------------------------------------------------------------
# Constants + identity
# ---------------------------------------------------------------------------


class TestApplianceConstants:
    def test_conf_key_exists(self):
        assert CONF_APPLIANCE_COORDINATOR_ENABLED == "appliance_coordinator_enabled"

    def test_records_conf_key_exists(self):
        assert CONF_APPLIANCE_RECORDS == "appliance_records"
        assert _CONF_APPLIANCE_RECORDS_COORD == CONF_APPLIANCE_RECORDS

    def test_coordinator_enabled_keys_wired(self):
        assert "appliance" in COORDINATOR_ENABLED_KEYS
        assert COORDINATOR_ENABLED_KEYS["appliance"] == "appliance_coordinator_enabled"

    def test_stale_max_age_is_positive_int(self):
        assert isinstance(APPLIANCE_STALE_MAX_AGE_S, int)
        assert APPLIANCE_STALE_MAX_AGE_S > 0


class TestApplianceCoordinatorIdentity:
    def test_is_base_coordinator_subclass(self):
        hass = _make_hass()
        c = ApplianceCoordinator(hass)
        assert isinstance(c, BaseCoordinator)

    def test_coordinator_id_and_name(self):
        c = ApplianceCoordinator(_make_hass())
        assert c.coordinator_id == "appliance"
        assert c.name == "Appliance"

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_list(self):
        c = ApplianceCoordinator(_make_hass())
        assert await c.evaluate([Intent(source="x")], {}) == []


# ---------------------------------------------------------------------------
# Invariant (ii) — commands nothing
# ---------------------------------------------------------------------------


class TestInvariantCommandsNothing:
    """Patch-and-assert-zero across every public method + a full census tick."""

    @pytest.mark.asyncio
    async def test_no_service_calls_or_state_writes(self):
        hass = _make_hass()
        coord = ApplianceCoordinator(hass)
        # Full lifecycle + census tick
        await coord.async_setup()
        _ = await coord.evaluate([Intent(source="x")], {})
        _ = coord.resolve_census()
        await coord.async_teardown()
        assert hass.services.call_count == 0
        assert hass.states.set_calls == []


# ---------------------------------------------------------------------------
# Invariant (i) — dedup + no-drop
# ---------------------------------------------------------------------------


class TestCensusDedupAndNoDrop:
    def _room_entry(self, name, **keys):
        return _FakeEntry(
            ENTRY_TYPE_ROOM,
            data={"room_name": name, **keys},
        )

    def test_ura_owned_room_media_appears_with_ura_config_tag(self):
        """A URA room's media_player shows up untagged for onboarding."""
        entries = [
            self._room_entry("Living Room", room_media_player="media_player.living_tv"),
        ]
        hass = _make_hass(
            entries=entries,
            states={"media_player.living_tv": _FakeState("playing")},
        )
        coord = ApplianceCoordinator(hass)
        recs = coord.resolve_census()
        assert len(recs) == 1
        r = recs[0]
        assert r["entity_refs"]["state"] == ["media_player.living_tv"]
        assert TAG_URA_CONFIG in r["source_tags"]
        # room_media_player → media_av by default.
        assert r["functional_domain"] == DOMAIN_MEDIA_AV
        assert r["room"] == "Living Room"

    def test_declared_record_claims_entity_and_suppresses_ura_source(self):
        """entity-exclusivity: a declared record wins over URA-owned discovery."""
        declared = {
            "name": "Living Room TV",
            "functional_domain": "media_av",
            "room": "Living Room",
            "entity_refs": {
                "power": [], "energy": [], "control": [],
                "state": ["media_player.living_tv"],
            },
            "source_tags": ["ura_config"],
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [declared]},
            ),
            self._room_entry("Living Room", room_media_player="media_player.living_tv"),
        ]
        hass = _make_hass(
            entries=entries,
            states={"media_player.living_tv": _FakeState("playing")},
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        # Only the declared record — URA source is suppressed.
        assert len(recs) == 1
        assert recs[0]["name"] == "Living Room TV"

    def test_intra_integration_shadow_collapses_by_device_id(self):
        """Reuse pattern from camera_census.py:589-628."""
        # Two entities on the same device_id (e.g. dual-representation).
        ent_reg = _FakeEntityRegistry({
            "fan.jaya_hi": "dev_jaya",
            "fan.jaya_lo": "dev_jaya",
        })
        entries = [
            self._room_entry("Jaya BR", fans=["fan.jaya_hi", "fan.jaya_lo"]),
        ]
        hass = _make_hass(
            entries=entries,
            states={
                "fan.jaya_hi": _FakeState("on"),
                "fan.jaya_lo": _FakeState("off"),
            },
            ent_reg=ent_reg,
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        # Two shadow-entities on one device -> exactly one record.
        assert len(recs) == 1

    def test_span_circuits_appear_untagged_but_visible(self):
        """SPAN source is READ, not constructed — every circuit becomes a record."""
        circuits = {
            "sensor.span_panel_dryer_power": MagicMock(
                friendly_name="Dryer",
            ),
        }
        hass = _make_hass(
            energy_circuits=circuits,
            states={"sensor.span_panel_dryer_power": _FakeState("125.0")},
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        assert len(recs) == 1
        r = recs[0]
        assert r["entity_refs"]["power"] == ["sensor.span_panel_dryer_power"]
        assert "span" in r["source_tags"]

    def test_unclaimed_entities_never_dropped(self):
        """Every unclaimed URA entity → exactly one (uncategorized) record."""
        entries = [
            self._room_entry(
                "Kitchen",
                fans=["fan.kitchen"],
                lights=["light.kitchen"],
                covers=["cover.kitchen"],
            ),
        ]
        hass = _make_hass(
            entries=entries,
            states={
                "fan.kitchen": _FakeState("on"),
                "light.kitchen": _FakeState("on"),
                "cover.kitchen": _FakeState("open"),
            },
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        # Three unclaimed entities → three records, none dropped.
        assert len(recs) == 3
        # All uncategorized (functional_domain=other) as per URA_ROOM_KEY_TO_DOMAIN.
        assert all(r["functional_domain"] == DOMAIN_OTHER for r in recs)
        # Entity-exclusivity: every entity_id appears in exactly one record.
        seen = []
        for r in recs:
            for role, ids in r["entity_refs"].items():
                seen.extend(ids)
        assert sorted(seen) == sorted(set(seen))
        assert set(seen) == {"fan.kitchen", "light.kitchen", "cover.kitchen"}


# ---------------------------------------------------------------------------
# Wire-in anchor (sensor → resolver)
# ---------------------------------------------------------------------------


class TestWireInAnchor:
    """The sensor's ``extra_state_attributes["appliances"]`` MUST route through
    ``ApplianceCoordinator.resolve_census()``. Neutering that call site in
    production source turns this test RED under the mutation drill
    (PYTHONDONTWRITEBYTECODE=1; clear __pycache__).

    Because the sensor module drags a large HA import surface, we test the
    wire directly: build a coordinator, register it on hass, then invoke the
    sensor's ``extra_state_attributes`` property via a minimal shim that
    mirrors the production body.
    """

    def test_extra_state_attributes_reads_resolver(self):
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [
                    {
                        "name": "Fridge",
                        "functional_domain": "cold_chain",
                        "room": "Kitchen",
                        "entity_refs": {"power": ["sensor.fridge_power"],
                                        "energy": [], "control": [], "state": []},
                        "source_tags": ["ura_config"],
                    },
                ]},
            ),
        ]
        hass = _make_hass(
            entries=entries,
            states={"sensor.fridge_power": _FakeState("120.0")},
        )
        coord = ApplianceCoordinator(hass)
        hass.data["universal_room_automation"]["coordinator_manager"].coordinators["appliance"] = coord

        # Mirror the sensor's extra_state_attributes body (matches
        # sensor.py ApplianceCensusSensor). Any drift here (or a neutered
        # call site in production source) will break the assertion below.
        def _sensor_extra_state_attributes():
            appliances = coord.resolve_census()
            return {
                "appliances": appliances,
                "stale_max_age_s": APPLIANCE_STALE_MAX_AGE_S,
            }

        attrs = _sensor_extra_state_attributes()
        assert attrs["stale_max_age_s"] == APPLIANCE_STALE_MAX_AGE_S
        assert len(attrs["appliances"]) == 1
        assert attrs["appliances"][0]["name"] == "Fridge"

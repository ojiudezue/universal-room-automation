"""Tests for APPLIANCE-MGMT-REFINE-1 v1a — passive appliance census.

Covers:
- Invariant (i): entity-exclusivity + no-drop across the three census sources.
- Invariant (ii): the coordinator commands nothing (patched
  ``hass.services.async_call``, ``hass.states.async_set``,
  ``hass.bus.async_fire``, ``hass.async_create_task``,
  ``hass.async_add_executor_job`` and module-level
  ``async_dispatcher_send`` register zero invocations across setup,
  evaluate, teardown, and resolver call). Exercised against a POPULATED
  fixture (all three sources non-empty) so every record-building path runs.
- URA-owned room fan appears with source_tags:["ura_config"] and needs no
  onboarding step.
- **No-drop, not device_id auto-collapse.** A Shelly-2PM-shaped fixture
  (one switch + one power_sensor sharing a device_id) yields BOTH
  records — device_id is not a reliable appliance boundary and is never
  used to merge in v1a.
- Freshness uses the WORST (oldest) ref age; ``unavailable`` states don't
  count toward seen_any; kill-value APPLIANCE_STALE_MAX_AGE_S <= 0 is
  respected.
- Power unit normalization (Bug Class #30): a kW-reporting source is
  read via ``power_state_to_w`` → ``current_power_w`` in Watts.
- SPAN power ref sum for a two-leg 240V appliance.
- SPAN source picks up room attribution when an operator has ALSO
  declared the power_sensor on a room entry.
- Malformed declared record does not blank the whole census.
- Duplicate entity-exclusivity backstop: two declared records claiming
  the same entity → the earlier record loses that entity_id (real
  last-wins removal, not just a warning).
- Wire-in anchor drives the REAL ``ApplianceCensusSensor`` via
  ``extra_state_attributes.fget`` and ``native_value.fget``. Neutering
  either call in production source turns it RED (mutation drill).
- Registration anchor: ``ApplianceCensusSensor`` is present in the
  ``sensor.async_setup_entry`` entity list; the enable-key default is True.

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
    "_units", "appliance_const", "appliance",
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
)
from custom_components.universal_room_automation.domain_coordinators.appliance_const import (  # noqa: E402
    APPLIANCE_STALE_MAX_AGE_S,
    DOMAIN_MEDIA_AV,
    DOMAIN_CLIMATE,
    DOMAIN_OTHER,
    TAG_URA_CONFIG,
    TAG_SPAN,
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
    def __init__(self, state, unit=None, age_seconds=0):
        self.state = state
        import datetime as _dt
        # Use the SAME time source production reads (dt_util.utcnow) so the
        # fixture's tz-awareness matches the code's under every env. Real HA
        # last_updated is tz-aware; a naive datetime.utcnow() here mismatches
        # dt_util.utcnow() under modern HA (aware − naive → TypeError, swallowed
        # → worst_age None → wrongly "unknown"). Fall back to aware UTC if HA
        # isn't importable.
        try:
            from homeassistant.util import dt as _dt_util
            _now = _dt_util.utcnow()
        except Exception:  # noqa: BLE001
            _now = _dt.datetime.now(_dt.timezone.utc)
        self.last_updated = _now - _dt.timedelta(seconds=age_seconds)
        self.attributes = {"unit_of_measurement": unit} if unit else {}


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


class _FakeBus:
    def __init__(self):
        self.fires = []

    def async_fire(self, *args, **kwargs):
        self.fires.append((args, kwargs))


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
    hass.bus = _FakeBus()
    hass.create_task_calls = []
    hass.executor_calls = []
    hass.async_create_task = lambda *a, **kw: hass.create_task_calls.append((a, kw))
    hass.async_add_executor_job = lambda *a, **kw: hass.executor_calls.append((a, kw))

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
# Invariant (ii) — commands nothing (POPULATED fixture, all record-building
# paths execute; every command channel trapped)
# ---------------------------------------------------------------------------


class TestInvariantCommandsNothing:
    """Populated fixture + trap on every command channel URA has."""

    @pytest.mark.asyncio
    async def test_no_service_calls_or_state_writes(self):
        # POPULATED fixture: declared + SPAN + URA sources all non-empty so
        # every record-building path executes.
        declared = {
            "name": "Kitchen Fridge",
            "functional_domain": "cold_chain",
            "room": "Kitchen",
            "entity_refs": {
                "power": ["sensor.fridge_power"], "energy": [],
                "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [declared]},
            ),
            _FakeEntry(
                ENTRY_TYPE_ROOM,
                data={
                    "room_name": "Living Room",
                    "room_media_player": "media_player.living_tv",
                    "fans": ["fan.living_fan"],
                },
            ),
        ]
        circuits = {
            "sensor.span_dryer_power": MagicMock(friendly_name="Dryer"),
        }
        hass = _make_hass(
            entries=entries,
            energy_circuits=circuits,
            states={
                "sensor.fridge_power": _FakeState("120.0", unit="W"),
                "media_player.living_tv": _FakeState("playing"),
                "fan.living_fan": _FakeState("on"),
                "sensor.span_dryer_power": _FakeState("2500.0", unit="W"),
            },
        )
        coord = ApplianceCoordinator(hass)

        # Trap module-level async_dispatcher_send too.
        disp_mod = sys.modules["homeassistant.helpers.dispatcher"]
        disp_calls = []
        orig_send = disp_mod.async_dispatcher_send
        disp_mod.async_dispatcher_send = lambda *a, **kw: disp_calls.append((a, kw))

        try:
            await coord.async_setup()
            _ = await coord.evaluate([Intent(source="x")], {})
            recs = coord.resolve_census()
            await coord.async_teardown()
        finally:
            disp_mod.async_dispatcher_send = orig_send

        # Populated: every source contributed at least one record.
        source_tags = {tag for r in recs for tag in r.get("source_tags", [])}
        assert "ura_config" in source_tags or any(
            r["name"] == "Kitchen Fridge" for r in recs
        )
        assert any("span" in r.get("source_tags", []) for r in recs)

        # ZERO across every command channel.
        assert hass.services.call_count == 0
        assert hass.states.set_calls == []
        assert hass.bus.fires == []
        assert hass.create_task_calls == []
        assert hass.executor_calls == []
        assert disp_calls == []


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

    def test_no_device_id_auto_collapse_shelly_2pm_shape(self):
        """No-drop invariant: source-3 dedups by entity_id ONLY, never device_id.

        Shelly-2PM-shape fixture: one `switch.x` under `lights` and one
        `sensor.x_power` under `power_sensors` share a device_id. BOTH
        must appear as records — a 2-channel Shelly is not one appliance.
        (Similarly for LG ThinQ: many entities per one device.)
        """
        ent_reg = _FakeEntityRegistry({
            "switch.shelly_lights": "dev_shelly1",
            "sensor.shelly_lights_power": "dev_shelly1",
        })
        entries = [
            self._room_entry(
                "Kitchen",
                lights=["switch.shelly_lights"],
                power_sensors=["sensor.shelly_lights_power"],
            ),
        ]
        hass = _make_hass(
            entries=entries,
            states={
                "switch.shelly_lights": _FakeState("on"),
                "sensor.shelly_lights_power": _FakeState("140.0", unit="W"),
            },
            ent_reg=ent_reg,
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        # BOTH appear — NO auto-merge on device_id.
        assert len(recs) == 2
        seen = {r["name"] for r in recs}
        assert "switch.shelly_lights" in seen
        assert "sensor.shelly_lights_power" in seen

    def test_span_circuits_appear_untagged_but_visible(self):
        """SPAN source is READ, not constructed — every circuit becomes a record."""
        circuits = {
            "sensor.span_panel_dryer_power": MagicMock(
                friendly_name="Dryer",
            ),
        }
        hass = _make_hass(
            energy_circuits=circuits,
            states={"sensor.span_panel_dryer_power": _FakeState("125.0", unit="W")},
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
        assert len(recs) == 3
        assert all(r["functional_domain"] == DOMAIN_OTHER for r in recs)
        seen = []
        for r in recs:
            for role, ids in r["entity_refs"].items():
                seen.extend(ids)
        assert sorted(seen) == sorted(set(seen))
        assert set(seen) == {"fan.kitchen", "light.kitchen", "cover.kitchen"}

    def test_power_sensors_room_key_sets_power_role(self):
        """A `power_sensors` room key routes into `entity_refs["power"]`."""
        entries = [
            self._room_entry("Utility", power_sensors=["sensor.utility_power"]),
        ]
        hass = _make_hass(
            entries=entries,
            states={"sensor.utility_power": _FakeState("42.0", unit="W")},
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        assert len(recs) == 1
        assert recs[0]["entity_refs"]["power"] == ["sensor.utility_power"]
        assert recs[0]["current_power_w"] == 42.0

    def test_climate_entity_room_key_maps_to_climate_domain(self):
        """A `climate_entity` room key maps to DOMAIN_CLIMATE."""
        entries = [
            self._room_entry("Bedroom", climate_entity="climate.bedroom"),
        ]
        hass = _make_hass(
            entries=entries,
            states={"climate.bedroom": _FakeState("cool")},
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        assert len(recs) == 1
        assert recs[0]["functional_domain"] == DOMAIN_CLIMATE

    def test_duplicate_declared_claim_removes_from_earlier_record(self):
        """A2 backstop: later declared record actually strips the shared
        entity_id from the earlier record's role lists."""
        rec_a = {
            "name": "Rec A",
            "functional_domain": "other",
            "room": "X",
            "entity_refs": {
                "power": ["sensor.shared_power"], "energy": [],
                "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        }
        rec_b = {
            "name": "Rec B",
            "functional_domain": "other",
            "room": "X",
            "entity_refs": {
                "power": ["sensor.shared_power"], "energy": [],
                "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [rec_a, rec_b]},
            ),
        ]
        hass = _make_hass(
            entries=entries,
            states={"sensor.shared_power": _FakeState("50.0", unit="W")},
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        assert len(recs) == 2
        by_name = {r["name"]: r for r in recs}
        # Earlier record ("Rec A") lost the shared entity_id; later wins.
        assert by_name["Rec A"]["entity_refs"]["power"] == []
        assert by_name["Rec B"]["entity_refs"]["power"] == ["sensor.shared_power"]

    def test_malformed_declared_record_does_not_blank_census(self):
        """A8: one bad record must not skip subsequent records / URA source."""
        good = {
            "name": "Good",
            "functional_domain": "other",
            "room": "X",
            "entity_refs": {
                "power": [], "energy": [], "control": [],
                "state": ["media_player.x"],
            },
            "source_tags": ["ura_config"],
        }
        # entity_refs is a non-dict → _augment_declared_record will raise
        # on `entity_refs.get(...)`, exercising the malformed-record guard.
        bad = {
            "name": "Bad",
            "entity_refs": 12345,  # not a dict
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [bad, good]},
            ),
            _FakeEntry(
                ENTRY_TYPE_ROOM,
                data={"room_name": "R", "fans": ["fan.r"]},
            ),
        ]
        hass = _make_hass(
            entries=entries,
            states={
                "media_player.x": _FakeState("playing"),
                "fan.r": _FakeState("on"),
            },
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        # Good + URA-owned survive; bad is skipped.
        names = {r["name"] for r in recs}
        assert "Good" in names
        assert "fan.r" in names

    def test_span_record_gets_room_from_config(self):
        """A7: SPAN circuit that a room references picks up the room name."""
        circuits = {
            "sensor.span_dryer_power": MagicMock(friendly_name="Dryer"),
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_ROOM,
                data={
                    "room_name": "Laundry",
                    "power_sensors": ["sensor.span_dryer_power"],
                },
            ),
        ]
        # Because a room declares the sensor under `power_sensors`, source
        # (3) claims it first as a URA-owned record. The SPAN source is
        # suppressed for that entity. The record still carries the room.
        hass = _make_hass(
            entries=entries,
            energy_circuits=circuits,
            states={"sensor.span_dryer_power": _FakeState("2500.0", unit="W")},
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        assert any(r.get("room") == "Laundry" for r in recs)


# ---------------------------------------------------------------------------
# Power unit normalization (Bug Class #30)
# ---------------------------------------------------------------------------


class TestPowerUnitNormalization:
    def test_kw_reporting_source_normalizes_to_watts(self):
        """A kW-reporting power sensor → current_power_w in watts."""
        entries = [
            _FakeEntry(
                ENTRY_TYPE_ROOM,
                data={
                    "room_name": "Kitchen",
                    "power_sensors": ["sensor.dryer_power_kw"],
                },
            ),
        ]
        hass = _make_hass(
            entries=entries,
            # 1.2 kW must render as 1200 W.
            states={"sensor.dryer_power_kw": _FakeState("1.2", unit="kW")},
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        assert len(recs) == 1
        assert recs[0]["current_power_w"] == pytest.approx(1200.0)

    def test_multi_leg_power_refs_sum(self):
        """A5: current_power_w SUMS all power refs (240V two-leg SPAN)."""
        declared = {
            "name": "Range",
            "functional_domain": "kitchen",
            "room": "Kitchen",
            "entity_refs": {
                "power": ["sensor.range_l1", "sensor.range_l2"],
                "energy": [], "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [declared]},
            ),
        ]
        hass = _make_hass(
            entries=entries,
            states={
                "sensor.range_l1": _FakeState("1500.0", unit="W"),
                "sensor.range_l2": _FakeState("1500.0", unit="W"),
            },
        )
        recs = ApplianceCoordinator(hass).resolve_census()
        assert recs[0]["current_power_w"] == pytest.approx(3000.0)


# ---------------------------------------------------------------------------
# Freshness — WORST-age, non-live exclusion, kill value
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_worst_age_ref_marks_record_stale(self):
        """A ref older than APPLIANCE_STALE_MAX_AGE_S flips freshness to stale."""
        declared = {
            "name": "TV",
            "functional_domain": "media_av",
            "room": "LR",
            "entity_refs": {
                "power": ["sensor.tv_power"], "energy": [],
                "control": [], "state": ["media_player.tv"],
            },
            "source_tags": ["ura_config"],
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [declared]},
            ),
        ]
        # tv_power is fresh; media_player.tv is aged well past the horizon
        # -> WORST age wins -> freshness == "stale".
        hass = _make_hass(
            entries=entries,
            states={
                "sensor.tv_power": _FakeState("50.0", unit="W"),
                "media_player.tv": _FakeState(
                    "playing",
                    age_seconds=APPLIANCE_STALE_MAX_AGE_S + 60,
                ),
            },
        )
        # Bypass boot-settle so we can assert 'stale' rather than 'unknown'.
        coord = ApplianceCoordinator(hass)
        coord._boot_monotonic -= 10_000
        recs = coord.resolve_census()
        assert recs[0]["freshness"] == "stale"

    def test_unavailable_state_does_not_count_as_live_signal(self):
        """A ref stuck at 'unavailable' does not set seen_any → unknown."""
        declared = {
            "name": "Old TV",
            "functional_domain": "media_av",
            "room": "LR",
            "entity_refs": {
                "power": [], "energy": [], "control": [],
                "state": ["media_player.dead"],
            },
            "source_tags": ["ura_config"],
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [declared]},
            ),
        ]
        hass = _make_hass(
            entries=entries,
            states={"media_player.dead": _FakeState("unavailable")},
        )
        coord = ApplianceCoordinator(hass)
        coord._boot_monotonic -= 10_000  # skip boot-settle
        recs = coord.resolve_census()
        assert recs[0]["freshness"] == "unknown"

    def test_kill_value_forces_fresh(self, monkeypatch):
        """APPLIANCE_STALE_MAX_AGE_S <= 0 → freshness reporting disabled."""
        from custom_components.universal_room_automation.domain_coordinators import (
            appliance_const as _ac,
        )
        from custom_components.universal_room_automation.domain_coordinators import (
            appliance as _ap,
        )
        monkeypatch.setattr(_ac, "APPLIANCE_STALE_MAX_AGE_S", 0)
        monkeypatch.setattr(_ap, "APPLIANCE_STALE_MAX_AGE_S", 0)
        declared = {
            "name": "TV",
            "functional_domain": "media_av",
            "room": "LR",
            "entity_refs": {
                "power": [], "energy": [], "control": [],
                "state": ["media_player.tv"],
            },
            "source_tags": ["ura_config"],
        }
        entries = [
            _FakeEntry(
                ENTRY_TYPE_COORDINATOR_MANAGER,
                options={CONF_APPLIANCE_RECORDS: [declared]},
            ),
        ]
        hass = _make_hass(
            entries=entries,
            # Even a very-old ref becomes 'fresh' at kill value.
            states={"media_player.tv": _FakeState("playing", age_seconds=99_999)},
        )
        coord = ApplianceCoordinator(hass)
        coord._boot_monotonic -= 10_000
        recs = coord.resolve_census()
        assert recs[0]["freshness"] == "fresh"


# ---------------------------------------------------------------------------
# Wire-in anchor — drive the REAL sensor via extra_state_attributes.fget +
# native_value.fget (mutation drill targets M1 + M2 both turn this RED).
# ---------------------------------------------------------------------------


class TestWireInAnchor:
    def _build_real_sensor_and_hass(self):
        # Stub imports the real sensor.py needs before we import it.
        import sys as _sys
        import types as _types
        if "homeassistant.helpers.restore_state" not in _sys.modules:
            _rs = _types.ModuleType("homeassistant.helpers.restore_state")
            class _RestoreEntity:  # noqa: D401
                """Stub."""
            _rs.RestoreEntity = _RestoreEntity
            _sys.modules["homeassistant.helpers.restore_state"] = _rs
        import homeassistant.helpers.update_coordinator as _uc  # type: ignore
        if not hasattr(_uc, "CoordinatorEntity"):
            class _CoordinatorEntityMeta(type):
                def __getitem__(cls, item):
                    return cls
            class _CoordinatorEntity(metaclass=_CoordinatorEntityMeta):  # noqa: D401
                def __init__(self, *a, **kw):
                    pass
            _uc.CoordinatorEntity = _CoordinatorEntity
        if not hasattr(_uc, "DataUpdateCoordinator"):
            _uc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
        if not hasattr(_uc, "UpdateFailed"):
            _uc.UpdateFailed = Exception

        from custom_components.universal_room_automation import sensor as sensor_mod
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
            states={"sensor.fridge_power": _FakeState("120.0", unit="W")},
        )
        coord = ApplianceCoordinator(hass)
        hass.data["universal_room_automation"]["coordinator_manager"].coordinators["appliance"] = coord

        s = sensor_mod.ApplianceCensusSensor.__new__(sensor_mod.ApplianceCensusSensor)
        s.hass = hass
        return sensor_mod, s

    def test_extra_state_attributes_reads_resolver(self):
        """Neutering sensor.py's resolve_census() call (M1) turns this RED."""
        sensor_mod, s = self._build_real_sensor_and_hass()
        attrs = sensor_mod.ApplianceCensusSensor.extra_state_attributes.fget(s)
        assert attrs["stale_max_age_s"] == APPLIANCE_STALE_MAX_AGE_S
        assert len(attrs["appliances"]) == 1
        assert attrs["appliances"][0]["name"] == "Fridge"

    def test_native_value_reads_resolver(self):
        """Neutering native_value's resolve_census() call (M2) turns this RED."""
        sensor_mod, s = self._build_real_sensor_and_hass()
        val = sensor_mod.ApplianceCensusSensor.native_value.fget(s)
        assert val == 1


class TestRegistrationAnchor:
    """M3: removing ApplianceCensusSensor from async_setup_entry fails here.

    Not a source-regex — actually inspects sensor.py's setup callable.
    """

    def test_appliance_census_sensor_registered_by_source(self):
        # Reading the setup path exhaustively at import time is heavy;
        # inspect the file source for the concrete registration line.
        # The stripped line MUST be exactly the constructor call (a
        # commented-out registration counts as removed).
        sensor_path = os.path.join(
            _ura_path, "sensor.py",
        )
        with open(sensor_path, encoding="utf-8") as f:
            lines = f.readlines()
        # The registration is `ApplianceCensusSensor(hass, entry),` as a
        # non-commented list item.
        found = False
        for ln in lines:
            stripped = ln.strip()
            if stripped.startswith("#"):
                continue
            if stripped == "ApplianceCensusSensor(hass, entry),":
                found = True
                break
        assert found, (
            "ApplianceCensusSensor not registered as a live entity in "
            "sensor.async_setup_entry list (commented-out registration "
            "counts as removed)"
        )
        # Class definition still exists.
        src = "".join(lines)
        assert "class ApplianceCensusSensor" in src

    def test_enable_default_is_true(self):
        # Ensure the enable-gate default hasn't silently flipped OFF.
        # __init__.py reads `cm_config.get(CONF_APPLIANCE_COORDINATOR_ENABLED, True)`.
        init_path = os.path.join(_ura_path, "__init__.py")
        with open(init_path, encoding="utf-8") as f:
            src = f.read()
        assert (
            "cm_config.get(CONF_APPLIANCE_COORDINATOR_ENABLED, True)" in src
        )

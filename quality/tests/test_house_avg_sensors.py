"""HOUSE-AVG-SENSORS-1 — filtered house-average indoor temp/humidity sensors.

Drives the production ``HouseAvgTemperatureSensor`` / ``HouseAvgHumiditySensor``
(aggregation.py) with room coordinators supplied through the module's own
``_get_room_coordinators`` helper. Classification flows through the REAL
``room_classification.get_room_classification`` and the REAL
``safety.outdoor_zone_names_snapshot`` (outdoor-zone set read from a Zone
Manager config entry), so no classification is faked.

Oracle (hand-derived): Bedroom 70F/40%, Kitchen 74F/50% are indoor;
AV Closet (room_type infrastructure) 90F/20% and Patio (zone "Outside",
zone_is_outdoor=True) 100F/80% are excluded.
  filtered temp = (70+74)/2 = 72.0 ; filtered humidity = (40+50)/2 = 45.0
  unfiltered temp = (70+74+90+100)/4 = 83.5 ; humidity = 47.5
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

DOMAIN = "universal_room_automation"


def _agg():
    return importlib.import_module(
        "custom_components.universal_room_automation.aggregation"
    )


def _room(entry_id, title, room_type, zone, temp, hum):
    entry = SimpleNamespace(
        entry_id=entry_id,
        title=title,
        data={"room_name": title, "room_type": room_type, "zone": zone},
        options={},
    )
    return SimpleNamespace(entry=entry, data={"temperature": temp, "humidity": hum})


def _hass(outdoor_zone=True):
    zm = SimpleNamespace(
        data={
            "entry_type": "zone_manager",
            "zones": {
                "Outside": {"zone_is_outdoor": outdoor_zone},
                "Upstairs": {"zone_is_outdoor": False},
            },
        },
        options={},
    )
    return SimpleNamespace(
        data={DOMAIN: {}},
        config_entries=SimpleNamespace(async_entries=lambda domain=None: [zm]),
    )


def _rooms():
    return [
        _room("r1", "Bedroom", "bedroom", "Upstairs", 70.0, 40.0),
        _room("r2", "Kitchen", "common_area", "Upstairs", 74.0, 50.0),
        _room("r3", "AV Closet", "infrastructure", "Upstairs", 90.0, 20.0),
        _room("r4", "Patio", "common_area", "Outside", 100.0, 80.0),
    ]


@pytest.fixture
def agg(monkeypatch):
    mod = _agg()
    rooms = _rooms()
    monkeypatch.setattr(mod, "_get_room_coordinators", lambda hass: list(rooms))
    return mod, rooms


def _entry():
    return SimpleNamespace(entry_id="integ", data={}, options={})


def test_constants_match_production_keys():
    """Guard the hand-written dict keys used by the fixture."""
    const = importlib.import_module(
        "custom_components.universal_room_automation.const"
    )
    assert const.CONF_ROOM_TYPE == "room_type"
    assert const.CONF_ZONE == "zone"
    assert const.CONF_ZONE_IS_OUTDOOR == "zone_is_outdoor"
    assert const.ENTRY_TYPE_ZONE_MANAGER == "zone_manager"
    assert const.STATE_TEMPERATURE == "temperature"
    assert const.STATE_HUMIDITY == "humidity"


def test_temperature_excludes_infrastructure_and_outdoor(agg):
    mod, _ = agg
    s = mod.HouseAvgTemperatureSensor(_hass(), _entry())
    assert s.native_value == 72.0
    attrs = s.extra_state_attributes
    assert attrs == {"rooms_included": 2, "rooms_excluded": ["AV Closet", "Patio"]}


def test_humidity_mirror(agg):
    mod, _ = agg
    s = mod.HouseAvgHumiditySensor(_hass(), _entry())
    assert s.native_value == 45.0
    assert s.extra_state_attributes == {
        "rooms_included": 2, "rooms_excluded": ["AV Closet", "Patio"],
    }


def test_outdoor_exclusion_alone(agg):
    """Patio's zone NOT outdoor -> only AV Closet dropped: (70+74+100)/3."""
    mod, _ = agg
    s = mod.HouseAvgTemperatureSensor(_hass(outdoor_zone=False), _entry())
    assert s.native_value == 81.3
    assert s.extra_state_attributes["rooms_excluded"] == ["AV Closet"]


def test_infrastructure_exclusion_alone(agg):
    """AV Closet reclassified generic -> only Patio dropped: (70+74+90)/3."""
    mod, rooms = agg
    rooms[2].entry.data["room_type"] = "generic"
    s = mod.HouseAvgTemperatureSensor(_hass(), _entry())
    assert s.native_value == 78.0
    assert s.extra_state_attributes["rooms_excluded"] == ["Patio"]


def test_no_rooms_returns_none(monkeypatch):
    mod = _agg()
    monkeypatch.setattr(mod, "_get_room_coordinators", lambda hass: [])
    for cls in (mod.HouseAvgTemperatureSensor, mod.HouseAvgHumiditySensor):
        s = cls(_hass(), _entry())
        assert s.native_value is None
        assert s.extra_state_attributes == {"rooms_included": 0, "rooms_excluded": []}


def test_room_without_reading_not_counted(agg):
    mod, rooms = agg
    rooms[0].data = {"temperature": None, "humidity": 40.0}
    s = mod.HouseAvgTemperatureSensor(_hass(), _entry())
    assert s.native_value == 74.0
    assert s.extra_state_attributes["rooms_included"] == 1


def test_existing_unfiltered_getters_unchanged(agg):
    """TempDeltaOutside / HumidityDeltaOutside / HVACDirection keep the
    unfiltered average (brief item 3)."""
    mod, _ = agg
    s = mod.HouseAvgTemperatureSensor(_hass(), _entry())
    assert s._get_house_avg_temp() == 83.5
    assert s._get_house_avg_humidity() == 47.5


def test_sensor_identity():
    mod = _agg()
    t = mod.HouseAvgTemperatureSensor(_hass(), _entry())
    h = mod.HouseAvgHumiditySensor(_hass(), _entry())
    assert t._attr_unique_id == "universal_room_automation_house_avg_temperature"
    assert h._attr_unique_id == "universal_room_automation_house_avg_humidity"
    assert t._attr_device_class == "temperature"
    assert h._attr_device_class == "humidity"
    assert t._attr_state_class == "measurement"
    assert h._attr_state_class == "measurement"
    assert t._attr_native_unit_of_measurement == "°F"
    assert h._attr_native_unit_of_measurement == "%"


@pytest.mark.asyncio
async def test_registered_in_aggregation_setup(monkeypatch):
    """Wire-in anchor: the integration-entry setup adds both sensors."""
    mod = _agg()
    hass = _hass()
    entry = SimpleNamespace(
        entry_id="integ", data={"entry_type": "integration"}, options={},
    )
    added: list = []
    await mod.async_setup_aggregation_sensors(hass, entry, added.extend)
    ids = {getattr(e, "_attr_unique_id", None) for e in added}
    assert "universal_room_automation_house_avg_temperature" in ids
    assert "universal_room_automation_house_avg_humidity" in ids

"""ANOMALY-FLOOD-ROWS-1 option A: path_implausible only for camera-covered moves.

`TransitValidator.validate_transition` used to label any no-sighting move
"path_implausible" (-0.15, plus a transit.path_implausible anomaly row from
transitions.py) whenever ANY shared-space camera fired in the last 10 min.
Now the penalty needs the move's from or to room to hold a shared-space
camera. Rooms resolve to areas through the room config (CONF_AREA_ID, via
`camera_census.build_room_to_area_id_map`), cameras through the entity
registry area (else the device's area). No name matching.

Drives the REAL production `validate_transition` (real package import through
`_sighting_rig`); only the HA registries and config entries are faked, scoped
by monkeypatch. Oracles are hand-derived from the card's rule.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import _sighting_rig as rig

DOMAIN = "universal_room_automation"
T0 = datetime(2026, 11, 17, 3, 0, 0, tzinfo=timezone.utc)
HALL_CAM = "binary_sensor.hallway_person_detected"
HALL_CAM_DEV = "binary_sensor.upstairs_landing_person"  # area via its device


@pytest.fixture
def m():
    with rig.import_real_modules(purge_tainted=True) as ns:
        yield ns


class _Entry:
    def __init__(self, data, options=None):
        self.data = data
        self.options = options or {}


def _room(name, area_id):
    return _Entry({"entry_type": "room", "room_name": name, "area_id": area_id})


ROOMS = [
    _room("Master Bedroom", "master_bedroom"),
    _room("Master Bathroom", "master_bathroom"),
    _room("Hallway", "hallway"),
    _room("Upstairs Landing", "upstairs_landing"),
    _Entry({"entry_type": "integration"}),
]


def _hass(entries=ROOMS):
    return SimpleNamespace(
        data={DOMAIN: {}},
        config_entries=SimpleNamespace(async_entries=lambda domain: list(entries)),
    )


def _install_registries(m, monkeypatch, *, lookups):
    ents = {
        HALL_CAM: SimpleNamespace(area_id="hallway", device_id=None),
        HALL_CAM_DEV: SimpleNamespace(area_id=None, device_id="dev_landing"),
    }
    devs = {"dev_landing": SimpleNamespace(area_id="upstairs_landing")}

    def _eget(eid):
        lookups.append(eid)
        return ents.get(eid)

    monkeypatch.setattr(
        m.transit.er_helper, "async_get",
        lambda _h: SimpleNamespace(async_get=_eget),
    )
    import homeassistant.helpers.device_registry as dr

    monkeypatch.setattr(
        dr, "async_get", lambda _h: SimpleNamespace(async_get=devs.get),
    )


def _validator(m, monkeypatch, cams, *, entries=ROOMS, lookups=None):
    v = m.transit.TransitValidator(_hass(entries))
    _install_registries(m, monkeypatch, lookups=lookups if lookups is not None else [])
    monkeypatch.setattr(v, "_get_shared_space_cameras", lambda: list(cams))
    monkeypatch.setattr(m.transit.dt_util, "now", lambda: T0)
    # Hallway camera fired 5 min ago: outside the checkpoint window,
    # inside the 10-min "cameras active" window.
    v._camera_sightings = {"unidentified": [{
        "camera_entity_id": cams[0],
        "timestamp": T0 - timedelta(seconds=300),
        "room": "Hallway",
        "person_id": "unidentified",
    }]}
    return v


def _move(frm, to):
    return SimpleNamespace(person_id="Oji Udezue", timestamp=T0, from_room=frm, to_room=to)


@pytest.mark.asyncio
async def test_bedroom_to_own_bathroom_with_hall_camera_active_is_no_camera_data(m, monkeypatch):
    v = _validator(m, monkeypatch, [HALL_CAM])
    r = await v.validate_transition(_move("Master Bedroom", "Master Bathroom"))
    assert r.path_method == "no_camera_data"
    assert r.path_confidence_delta == 0.0
    assert r.path_validated is False
    attrs = v.build_diagnostic_attrs()
    assert attrs["path_coverage_not_covered_count"] == 1
    assert attrs["path_coverage_room_unresolved_count"] == 0


@pytest.mark.asyncio
async def test_move_into_camera_room_without_sighting_stays_implausible(m, monkeypatch):
    v = _validator(m, monkeypatch, [HALL_CAM])
    r = await v.validate_transition(_move("Master Bedroom", "Hallway"))
    assert r.path_method == "path_implausible"
    assert r.path_confidence_delta == -0.15
    assert v.build_diagnostic_attrs()["path_coverage_not_covered_count"] == 0


@pytest.mark.asyncio
async def test_move_out_of_camera_room_is_implausible(m, monkeypatch):
    """from_room covered (not only to_room)."""
    v = _validator(m, monkeypatch, [HALL_CAM])
    r = await v.validate_transition(_move("Hallway", "Master Bedroom"))
    assert r.path_method == "path_implausible"


@pytest.mark.asyncio
async def test_camera_area_falls_back_to_device_area(m, monkeypatch):
    v = _validator(m, monkeypatch, [HALL_CAM_DEV])
    r = await v.validate_transition(_move("Master Bedroom", "Upstairs Landing"))
    assert r.path_method == "path_implausible"


@pytest.mark.asyncio
async def test_unresolvable_room_is_no_camera_data_and_counted(m, monkeypatch):
    v = _validator(m, monkeypatch, [HALL_CAM])
    # "Hallway" is a room string here but no room entry maps it: the only
    # entry list lacks it, so the camera's own room cannot be matched by name.
    entries = [e for e in ROOMS if e.data.get("room_name") != "Hallway"]
    v.hass = _hass(entries)
    r = await v.validate_transition(_move("Garden Shed", "Hallway"))
    assert r.path_method == "no_camera_data"
    assert r.path_confidence_delta == 0.0
    attrs = v.build_diagnostic_attrs()
    assert attrs["path_coverage_room_unresolved_count"] == 2
    assert attrs["path_coverage_not_covered_count"] == 1


@pytest.mark.asyncio
async def test_sighting_in_window_still_confirms(m, monkeypatch):
    v = _validator(m, monkeypatch, [HALL_CAM])
    v._camera_sightings["unidentified"].append({
        "camera_entity_id": HALL_CAM,
        "timestamp": T0 + timedelta(seconds=20),
        "room": "Hallway",
        "person_id": "unidentified",
    })
    r = await v.validate_transition(_move("Master Bedroom", "Master Bathroom"))
    assert r.path_method == "path_confirmed"
    assert r.path_confidence_delta == 0.10


@pytest.mark.asyncio
async def test_cameras_inactive_is_no_camera_data_not_counted(m, monkeypatch):
    v = _validator(m, monkeypatch, [HALL_CAM])
    v._camera_sightings = {}
    r = await v.validate_transition(_move("Master Bedroom", "Hallway"))
    assert r.path_method == "no_camera_data"
    assert v.build_diagnostic_attrs()["path_coverage_not_covered_count"] == 0


@pytest.mark.asyncio
async def test_camera_area_cached_and_cleared_by_rebuild(m, monkeypatch):
    lookups: list[str] = []
    v = _validator(m, monkeypatch, [HALL_CAM], lookups=lookups)
    await v.validate_transition(_move("Master Bedroom", "Hallway"))
    await v.validate_transition(_move("Master Bedroom", "Hallway"))
    assert lookups == [HALL_CAM]
    monkeypatch.setattr(
        m.transit, "_protect_sourced_checkpoint_entities", lambda _h: ([], {}, {}),
    )
    v._build_and_subscribe()
    await v.validate_transition(_move("Master Bedroom", "Hallway"))
    assert lookups == [HALL_CAM, HALL_CAM]


@pytest.mark.asyncio
async def test_presence_diagnostic_sensor_surfaces_coverage_counters(m, monkeypatch):
    """Consumer anchor: the counters reach sensor attributes (not just the helper)."""
    import importlib

    sensor_mod = importlib.import_module(f"{rig._PKG}.sensor")
    v = _validator(m, monkeypatch, [HALL_CAM])
    await v.validate_transition(_move("Master Bedroom", "Master Bathroom"))
    await v.validate_transition(_move("away", "Master Bathroom"))
    s = sensor_mod.PresenceDiagnosticSensor.__new__(sensor_mod.PresenceDiagnosticSensor)
    s.hass = SimpleNamespace(data={DOMAIN: {
        "coordinator_manager": SimpleNamespace(coordinators={"presence": SimpleNamespace()}),
        "transit_validator": v,
    }})
    attrs = s.extra_state_attributes
    assert attrs["path_coverage_not_covered_count"] == 2
    assert attrs["path_coverage_room_unresolved_count"] == 1

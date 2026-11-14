"""Shared REAL-HA rig for the person-sighting tests (FACE-ARRIVAL-REBUILD-1).

REAL Home Assistant core (phcc), REAL ``PresenceCoordinator`` /
``PersonSightingProducer`` / ``PersonCensus`` / ``CameraResolver`` over the
registry fixture EXTRACTED from the live house
(``fixtures/face_source_registry_2026_11.json``) plus two URA fused room
sensors. Config entries are plain objects returned by the real
``hass.config_entries`` methods (monkeypatched per test).

Modules are imported fresh inside ``_d7_isolation.import_scope`` (pattern:
test_presence_geofence_late_person) so donor stubs never leak in or out.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import homeassistant as _real_ha_pkg

from _d7_isolation import import_scope

_HA_DIR = Path(_real_ha_pkg.__file__).resolve().parent
_PKG = "custom_components.universal_room_automation"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "face_source_registry_2026_11.json"
DOMAIN = "universal_room_automation"

FAMILY = "binary_sensor.family_room_person_occupancy"
FAMILY_PROTECT = "binary_sensor.family_room_person_detected"
MASTER = "binary_sensor.master_hallway_person_occupancy"
FOYER = "binary_sensor.foyer_fisheye_person_occupancy"
UPSTAIRS = "binary_sensor.upstairs_hall_person_occupancy_2"
PLAYROOM = "binary_sensor.playroom_person_occupancy_2"
STAIRCASE = "binary_sensor.staircase_person_occupancy"
GARAGE_FUSED = "binary_sensor.garage_a_camera_person_detected"
STUDY_FUSED = "binary_sensor.study_b_camera_person_detected"
GARAGE_A_FRIGATE = "binary_sensor.garage_a_person_occupancy_2"
GARAGE_A_PROTECT = "binary_sensor.garage_a_person_detected"
FACE = {
    "family_room": "sensor.family_room_last_recognized_face_2",
    "master_hallway": "sensor.master_hallway_last_recognized_face_2",
    "foyer_fisheye": "sensor.foyer_fisheye_last_recognized_face_2",
    "upstairs_hall": "sensor.upstairs_hall_last_recognized_face_2",
    "playroom": "sensor.playroom_last_recognized_face_2",
    "staircase": "sensor.staircase_last_recognized_face_2",
    "garage_a": "sensor.garage_a_last_recognized_face_2",
}

DEFAULT_ZONES = {
    "Entertainment": [FAMILY, FOYER, MASTER],
    "Master Suite": [MASTER],
    "Upstairs": [UPSTAIRS, PLAYROOM],
    "Back Hallway": [GARAGE_FUSED],
    "Study": [STUDY_FUSED],
}
ROOM_AREAS = {
    "Family Room": "living_room",
    "Master Hallway": "master_hallway",
    "Upstairs Hall": "upstairs_hall",
    "Playroom": "playroom",
    "Garage A": "garage",
    "Study B": "study_b",
}
DEVICE_AREAS = {  # device-name -> area (Frigate and Protect legs alike)
    "Family Room": "living_room",
    "Master Hallway": "master_hallway",
    "Upstairs Hall": "upstairs_hall",
    "Playroom": "playroom",
    "Garage A": "garage",
}
TRACKED = ("person.oji_udezue", "person.jaya", "person.ezinne", "person.ziri")


def _is_real_ha(mod) -> bool:
    if not isinstance(mod, types.ModuleType):
        return False
    f = getattr(mod, "__file__", None)
    if not f:
        return False
    try:
        return Path(f).resolve().is_relative_to(_HA_DIR)
    except (OSError, ValueError):
        return False


_TESTS_DIR = Path(__file__).resolve().parent
# Never popped: the rig re-points this module's attributes itself, and a
# fresh copy would split HomeAssistant/State identity from phcc's.
_NO_PURGE = frozenset({"homeassistant", "homeassistant.core"})


def _is_foreign_stub(value) -> bool:
    """True for a test-authored stand-in: a mock, or a class/function
    defined in a module that lives under quality/tests."""
    from unittest.mock import NonCallableMock  # noqa: PLC0415

    if isinstance(value, NonCallableMock):
        return True
    if not isinstance(value, (type, types.FunctionType)):
        return False
    owner = sys.modules.get(getattr(value, "__module__", None) or "")
    f = getattr(owner, "__file__", None)
    if not f:
        return False
    try:
        return Path(f).resolve().is_relative_to(_TESTS_DIR)
    except (OSError, ValueError):
        return False


def purge_attr_tainted_ha() -> list[str]:
    """Pop REAL Home Assistant entity-platform modules (real ``__file__``)
    whose entity base classes a donor test file replaced in place, e.g.
    ``homeassistant.components.switch.SwitchEntity`` set to a stub class at
    collection time. The file-path check alone keeps such a module, and a
    URA platform imported afterwards subclasses the stub.

    Deliberately narrow: only ``homeassistant.components.<platform>``
    packages and ``homeassistant.helpers.restore_state``, and only when a
    tainted attribute is an entity base (``*Entity`` / ``*DeviceClass`` /
    ``*StateClass``). Re-importing those leaves is consistent with the
    retained real ``helpers.entity``; popping deeper helpers splits class
    identity (metaclass conflicts). Call inside an ``import_scope`` so the
    tainted copies are put back on exit. Returns the popped names."""
    popped = []
    for name in [k for k in sys.modules if k.startswith("homeassistant")]:
        parts = name.split(".")
        leaf = (len(parts) == 3 and parts[1] == "components") or (
            name == "homeassistant.helpers.restore_state")
        mod = sys.modules.get(name)
        if not leaf or name in _NO_PURGE or not _is_real_ha(mod):
            continue
        d = getattr(mod, "__dict__", None) or {}
        if any(
            k.endswith(("Entity", "DeviceClass", "StateClass"))
            and _is_foreign_stub(v)
            for k, v in list(d.items())
        ):
            sys.modules.pop(name, None)
            popped.append(name)
    return popped


def import_real_modules(*, purge_tainted: bool = False):
    """Context manager yielding a namespace of freshly imported REAL modules.

    ``purge_tainted``: also drop real HA modules whose attributes a donor
    replaced with test stubs (see ``purge_attr_tainted_ha``)."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        with import_scope(("custom_components", "homeassistant"), attrs=True):
            for name in [k for k in sys.modules if k == "custom_components"
                         or k.startswith("custom_components.")]:
                sys.modules.pop(name, None)
            for name in [k for k in sys.modules if k.startswith("homeassistant")]:
                if not _is_real_ha(sys.modules[name]):
                    sys.modules.pop(name, None)
            for name in ("homeassistant.helpers.dispatcher", "homeassistant.helpers.event"):
                sys.modules.pop(name, None)
            if purge_tainted:
                purge_attr_tainted_ha()
            _core = sys.modules["homeassistant.core"]

            def _real_callback(func):
                setattr(func, "_hass_callback", True)
                return func

            def _real_is_callback(func):
                return getattr(func, "_hass_callback", False) is True

            _core.callback = _real_callback
            _core.is_callback = _real_is_callback
            from pytest_homeassistant_custom_component import common as _phcc
            for _name in ("State", "Event", "HomeAssistant", "CoreState",
                          "ServiceCall", "SupportsResponse"):
                setattr(_core, _name, getattr(_phcc, _name))
            importlib.invalidate_caches()
            ns = SimpleNamespace(
                presence=importlib.import_module(f"{_PKG}.domain_coordinators.presence"),
                sighting=importlib.import_module(f"{_PKG}.person_sighting"),
                census=importlib.import_module(f"{_PKG}.camera_census"),
                resolver=importlib.import_module(f"{_PKG}.camera_resolver"),
                const=importlib.import_module(f"{_PKG}.const"),
                signals=importlib.import_module(f"{_PKG}.domain_coordinators.signals"),
                security=importlib.import_module(f"{_PKG}.domain_coordinators.security"),
                transit=importlib.import_module(f"{_PKG}.transit_validator"),
                paths=importlib.import_module(f"{_PKG}.interior_paths"),
                loader=importlib.import_module(f"{_PKG}.json_file_loader"),
                linker=importlib.import_module(f"{_PKG}.exterior_track_linker"),
                arrival_edges=importlib.import_module(f"{_PKG}.arrival_edges"),
                perimeter=importlib.import_module(f"{_PKG}.perimeter_alert"),
                button=importlib.import_module(f"{_PKG}.button"),
                dispatcher=importlib.import_module("homeassistant.helpers.dispatcher"),
                event=importlib.import_module("homeassistant.helpers.event"),
            )
            yield ns

    return _cm()


# ------------------------------------------------------------------ registry
class _Ent:
    def __init__(self, d: dict) -> None:
        self.entity_id = d["entity_id"]
        self.platform = d.get("platform")
        self.unique_id = d.get("unique_id")
        self.device_id = d.get("device_id")
        self.disabled_by = d.get("disabled_by")
        self.domain = self.entity_id.split(".", 1)[0]
        self.area_id = d.get("area_id")
        self.config_entry_id = d.get("config_entry_id")


class _ER:
    def __init__(self, ents):
        self.entities = {e.entity_id: e for e in ents}

    def async_get(self, eid):
        return self.entities.get(eid)


class _Dev:
    def __init__(self, d: dict) -> None:
        self.id = d["id"]
        self.name = d.get("name")
        self.identifiers = {tuple(x) for x in (d.get("identifiers") or [])}
        self.connections = set()
        self.via_device_id = d.get("via_device_id")
        self.area_id = DEVICE_AREAS.get(self.name)


class _DR:
    def __init__(self, devs):
        self.devices = {d.id: d for d in devs}

    def async_get(self, did):
        return self.devices.get(did)


def registries():
    fx = json.loads(FIXTURE.read_text())
    ents = [_Ent(e) for e in fx["entities"]]
    devs = [_Dev(d) for d in fx["devices"]]
    devs.append(_Dev({"id": "ura_room_garage_a", "name": "URA Garage A"}))
    devs.append(_Dev({"id": "ura_room_study_b", "name": "URA Study B"}))
    ents.append(_Ent({"entity_id": GARAGE_FUSED, "platform": DOMAIN,
                      "device_id": "ura_room_garage_a", "config_entry_id": "room_garage_a",
                      "unique_id": "room_garage_a_camera_person_detected"}))
    ents.append(_Ent({"entity_id": STUDY_FUSED, "platform": DOMAIN,
                      "device_id": "ura_room_study_b", "config_entry_id": "room_study_b",
                      "unique_id": "room_study_b_camera_person_detected"}))
    return _ER(ents), _DR(devs)


class _Mgr:
    def __init__(self, resolver):
        self.resolver = resolver
        self.calls = 0

    def _get_resolver(self):
        self.calls += 1
        return self.resolver

    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


def entries(m, *, zones=None, study_cameras=(STAIRCASE,), garage_cameras=(),
            strict=False, aliases=None):
    c = m.const
    integ = SimpleNamespace(entry_id="integ", data={
        c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION}, options={
        "tracked_persons": list(TRACKED),
        c.CONF_EGRESS_IDENTITY_FAILSAFE_STRICT: strict,
        c.CONF_EGRESS_CAMERAS: ["camera.garage_a_2", "camera.doorbell_lite"],
        c.CONF_KNOWN_FACE_GUESTS: ["Ojini"],
    })
    if aliases is not None:
        integ.options[c.CONF_FACE_NAME_ALIASES] = list(aliases)
    zm = SimpleNamespace(entry_id="zm", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_ZONE_MANAGER},
                         options={"zones": {
                             z: {"zone_cameras": list(p)}
                             for z, p in (zones if zones is not None else DEFAULT_ZONES).items()
                         }})
    garage = SimpleNamespace(entry_id="room_garage_a", data={
        c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_ROOM, c.CONF_ROOM_NAME: "Garage A",
        c.CONF_AREA_ID: "garage"}, options={c.CONF_ROOM_CAMERAS: list(garage_cameras)})
    study = SimpleNamespace(entry_id="room_study_b", data={
        c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_ROOM, c.CONF_ROOM_NAME: "Study B",
        c.CONF_AREA_ID: "study_b"}, options={c.CONF_ROOM_CAMERAS: list(study_cameras)})
    return [integ, zm, garage, study]


def install_entries(hass, monkeypatch, ents):
    by_id = {e.entry_id: e for e in ents}
    monkeypatch.setattr(hass.config_entries, "async_entries",
                        lambda domain=None, *a, **k: list(ents) if domain in (None, DOMAIN) else [])
    monkeypatch.setattr(hass.config_entries, "async_get_entry",
                        lambda entry_id: by_id.get(entry_id))
    return by_id


async def build(m, hass, monkeypatch, *, zones=None, past_boot=True, setup=True,
                study_cameras=(STAIRCASE,), garage_cameras=(), strict=False,
                aliases=None, persons=None, face_recognition=True):
    """Build the full rig; returns a namespace."""
    ents = entries(m, zones=zones, study_cameras=study_cameras,
                   garage_cameras=garage_cameras, strict=strict, aliases=aliases)
    install_entries(hass, monkeypatch, ents)
    er_, dr_ = registries()
    resolver = m.resolver.CameraResolver(er_, dr_, state_getter=hass.states.get)
    mgr = _Mgr(resolver)
    census = m.census.PersonCensus(hass, mgr)
    hass.data[DOMAIN] = {"census": census, "camera_manager": mgr}
    for face in FACE.values():
        hass.states.async_set(face, "Unknown")
    for pid, st in (persons or {p: "home" for p in TRACKED}).items():
        hass.states.async_set(pid, st)
    await hass.async_block_till_done()
    presence = m.presence.PresenceCoordinator(hass)
    presence._room_area_ids = dict(ROOM_AREAS)
    # The operator's Face Recognition switch (A2 gate); ON in the live house.
    presence._face_recognition_enabled = face_recognition
    zones_map = {"Entertainment": ["Family Room"], "Master Suite": ["Master Hallway"],
                 "Upstairs": ["Upstairs Hall", "Playroom"], "Back Hallway": ["Garage A"],
                 "Study": ["Study B"]}
    presence._zone_trackers = {
        z: m.presence.ZonePresenceTracker(hass, z, rooms) for z, rooms in zones_map.items()
    }
    presence._room_to_zone = {r: z for z, rooms in zones_map.items() for r in rooms}
    sightings: list = []

    def _capture(s):
        sightings.append(s)

    _capture._hass_callback = True  # run synchronously on the loop
    unsub = m.dispatcher.async_dispatcher_connect(
        hass, m.signals.SIGNAL_PERSON_SIGHTING, _capture)
    rig = SimpleNamespace(m=m, hass=hass, census=census, resolver=resolver, mgr=mgr,
                          presence=presence, sightings=sightings, unsubs=[unsub],
                          er=er_, dr=dr_)
    if setup:
        presence._setup_person_sightings()
        rig.producer = presence._person_sightings
        if past_boot and rig.producer is not None:
            rig.producer._setup_ts = time.time() - 700
    return rig


async def teardown(rig):
    for u in rig.unsubs:
        u()
    if rig.presence._person_sightings is not None:
        rig.presence._person_sightings.async_teardown()
    for unsub in list(rig.presence._unsub_listeners):
        try:
            unsub()
        except Exception:  # noqa: BLE001
            pass


def dt_now():
    from homeassistant.util import dt as dt_util
    return dt_util.utcnow()


def bridge(rig, camera, name):
    rig.census._on_frigate_face_msg(SimpleNamespace(
        payload=json.dumps({"type": "face", "name": name, "camera": camera}),
        retain=False))


async def face(rig, cam_key, name):
    rig.hass.states.async_set(FACE[cam_key], name)
    await rig.hass.async_block_till_done()


async def egress(rig, **data):
    payload = {
        "direction": "entry", "egress_camera": GARAGE_A_FRIGATE,
        "timestamp": None, "person_id": "oji_udezue", "confidence": 0.8,
        "identity_confidence": 0.6, "agreement_class": "single_source",
        "identity_synthetic_corroborated": False, "identity_provenance": "face",
    }
    payload.update(data)
    if payload["timestamp"] is None:
        from homeassistant.util import dt as dt_util
        payload["timestamp"] = dt_util.utcnow().isoformat()
    rig.hass.bus.async_fire("ura_person_egress_event", payload)
    await rig.hass.async_block_till_done()

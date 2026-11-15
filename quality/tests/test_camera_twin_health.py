"""Person-awareness layer ship 3b: the device-level dead-camera rule.

Plan: docs/planning/PLANNING_person_awareness_layer_ship3.md §6 (D6), §4
INV-DEAD-INPUT / INV-DEAD-CAMERA / INV-ANCHOR, §6.10 test and drill list.

Every test drives production code: the REAL room tracker through the REAL
room tick method (bound onto a bare room object, as the S1/S2 tests do), the
REAL ``CameraTwinHealth`` owner (twin map from a fresh REAL
``CameraResolver`` over hand-built registries in the live shapes), the REAL
house readers, the REAL census / zone tracker / Source 3 readers, and the
REAL ``fire_stuck_signal_ex`` (its inner dispatch is recorded, or the real
module path runs against a fake NotificationManager).

Fixtures use the live registry shapes (plan §13 D0 (f), §6.10): Frigate
devices with ONE camera entity; Protect devices with 2, 3 and 4 enabled
channels (never a one-camera Protect device, the presence §10 #41 trap); the
Reolink TrackMix with 2; ESPHome kiosk devices with ONE and with TWO camera
entities; a dual-lens doorbell (4 channels incl. the package camera); both
NVRs in setup retry (restored placeholders).

Oracles are hand-derived from the plan's rules; boundaries are literals
(grace 120 s -> 119 / 120 / 121; caps 900 s; NM_AFTER 1800 s; boot settle
600 s), never the imported constants.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstrap homeassistant mocks
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    PersonCensus,
)
from custom_components.universal_room_automation.const import (
    CONF_AREA_ID,
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_ENTRY_TYPE,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators import (
    _stuck_signal_nm as nm,
)
from custom_components.universal_room_automation.domain_coordinators import (
    camera_stream_health as csh,
)
from custom_components.universal_room_automation.domain_coordinators import (
    camera_twin_health as cth,
)
from custom_components.universal_room_automation.domain_coordinators.camera_stream_health import (  # noqa: E501
    CameraInputStreamHealth,
)
from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
    PresenceCoordinator,
    ZonePresenceTracker,
)
from custom_components.universal_room_automation.domain_coordinators.sensor_exclusion import (  # noqa: E501
    SensorExclusionSet,
)

T0 = datetime(2026, 11, 14, 10, 0, 0)
S2 = "camera_stream_hold_released"
S1 = "camera_stream_dead"
MEDIUM = "camera_stream_nvr_down_twin_covering"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Registries (live shapes)
# ---------------------------------------------------------------------------


class _Entities(dict):
    def get_entries_for_device_id(self, device_id, include_disabled=False):
        return [e for e in self.values() if e.device_id == device_id]


class _ER:
    def __init__(self, ents=()):
        self.entities = _Entities({e.entity_id: e for e in ents})
        self.raise_on_read = False

    def async_get(self, eid):
        if self.raise_on_read:
            raise RuntimeError("registry boom")
        return self.entities.get(eid)

    def add(self, *ents):
        for e in ents:
            self.entities[e.entity_id] = e


class _DR:
    def __init__(self, devs=()):
        self.devices = {d.id: d for d in devs}
        self.raise_on_read = False

    def async_get(self, did):
        if self.raise_on_read:
            raise RuntimeError("registry boom")
        return self.devices.get(did)


class _RaisingDevices(dict):
    def values(self):  # noqa: D401 — a registry that fails the build
        raise RuntimeError("device registry boom")


def _dev(did, name, *, idents=(), macs=(), name_by_user=None):
    return SimpleNamespace(
        id=did, name=name, name_by_user=name_by_user,
        identifiers=tuple(idents), connections={("mac", m) for m in macs},
    )


def _ent(eid, did, platform, *, disabled_by=None):
    return SimpleNamespace(
        entity_id=eid, device_id=did, platform=platform,
        disabled_by=disabled_by, domain=eid.split(".", 1)[0],
        unique_id=f"uid-{eid}", config_entry_id="ce", area_id=None,
    )


class World:
    """One house: registries, states, hass, NM capture, room entries."""

    def __init__(self):
        self.er = _ER()
        self.dr = _DR()
        self.states: dict = {}
        self.now = T0
        self.today = T0.date().isoformat()
        self.hass = make_hass()
        self.hass.states.get = lambda eid: self.states.get(eid)
        self.hass.data = {DOMAIN: {}}
        self.tasks: list = []
        self.entries: list = []
        self.hass.config_entries.async_entries = (
            lambda domain=None: list(self.entries)
        )
        self.census_entities: list[str] = []
        self.zone_entities: list[str] = []
        self.area_sensors: dict[str, list[str]] = {}
        self.rooms: list = []

        def _capture(coro, *a, **kw):
            self.tasks.append(coro)
            return MagicMock()

        self.hass.async_create_task = _capture

    # --- devices -----------------------------------------------------------
    def frigate(self, did, obj, name, *, cam=None, person=None):
        cam = cam or f"camera.{obj}"
        person = person or f"binary_sensor.{obj}_person_occupancy"
        self.dr.devices[did] = _dev(did, name, idents=[("frigate", f"inst1:{obj}")])
        self.er.add(_ent(cam, did, "frigate"), _ent(person, did, "frigate"))
        return cam, person

    def protect(self, did, name, stem, channels=2, *, mac="aa:bb:cc:00:00:01"):
        names = [
            f"camera.{stem}_high_resolution_channel",
            f"camera.{stem}_medium_resolution_channel",
            f"camera.{stem}_low_resolution_channel",
            f"camera.{stem}_package_camera",
        ][:channels]
        self.dr.devices[did] = _dev(did, name, macs=[mac])
        self.er.add(*(_ent(c, did, "unifiprotect") for c in names))
        person = f"binary_sensor.{stem}_person_detected"
        self.er.add(_ent(person, did, "unifiprotect"))
        return names, person

    def reolink_trackmix(self, did="d_tmix", stem="ptzcamreolinktmixpstudybporch"):
        cams = [f"camera.{stem}_clear", f"camera.{stem}_fluent"]
        self.dr.devices[did] = _dev(did, "PTZCamReolinkTMIXPStudyBPorch")
        self.er.add(*(_ent(c, did, "reolink") for c in cams))
        person = f"binary_sensor.{stem}_person"
        self.er.add(_ent(person, did, "reolink"))
        return cams, person

    def esphome_panel(self, did, name, stem, cameras=2):
        cams = [f"camera.{stem}_camera", f"camera.{stem}_screenshot"][:cameras]
        self.dr.devices[did] = _dev(did, name, idents=[("esphome", did)])
        self.er.add(*(_ent(c, did, "esphome") for c in cams))
        return cams

    # --- states ------------------------------------------------------------
    def set(self, **kv):
        for k, v in kv.items():
            self.states[k] = v if isinstance(v, SimpleNamespace) else st(v)

    def put(self, mapping):
        for k, v in mapping.items():
            self.states[k] = v if isinstance(v, SimpleNamespace) else st(v)

    # --- house plumbing ----------------------------------------------------
    def camera_manager(self):
        self.hass.data[DOMAIN]["camera_manager"] = SimpleNamespace(
            get_person_sensor_for_area=lambda area: list(
                self.area_sensors.get(area, ()),
            ),
        )

    def census(self):
        self.hass.data[DOMAIN]["census"] = SimpleNamespace(
            interior_camera_entities=lambda: list(self.census_entities),
        )

    def presence(self):
        pres = SimpleNamespace(zone_camera_entities=lambda: list(self.zone_entities))
        self.hass.data[DOMAIN]["coordinator_manager"] = SimpleNamespace(
            coordinators={"presence": pres},
        )

    def room_entry(self, name, area, *, motion=(), presence=(), occupancy=()):
        entry = MagicMock()
        entry.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: name,
            CONF_AREA_ID: area, CONF_MOTION_SENSORS: list(motion),
            CONF_MMWAVE_SENSORS: list(presence),
            ura_const.CONF_OCCUPANCY_SENSORS: list(occupancy),
        }
        entry.options = {}
        entry.entry_id = f"entry_{name}"
        self.entries.append(entry)
        return entry

    def owner(self, *, build=True, setup_at=None):
        o = cth.CameraTwinHealth(
            self.hass, clock=lambda: self.now,
            entity_registry_getter=lambda: self.er,
            device_registry_getter=lambda: self.dr,
        )
        o._setup_at = setup_at or self.now
        self.hass.data[DOMAIN][csh.TWIN_HEALTH_DATA_KEY] = o
        if build:
            o._rebuild()
        return o

    def drain(self):
        guard = 0
        while self.tasks and guard < 20:
            guard += 1
            batch, self.tasks = self.tasks, []
            for c in batch:
                _run(c)

    def close(self):
        for c in self.tasks:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self.tasks.clear()


def st(value, **attrs):
    return SimpleNamespace(state=value, attributes=dict(attrs), last_changed=None)


def restored():
    return st("unavailable", restored=True)


_ROOM_METHODS = (
    "_apply_camera_stream_health_tick", "_notify_substrate_stream_flips",
    "camera_input_stream_dead", "camera_stream_dead",
    "camera_input_stream_hold_expired", "camera_stream_hold_expired",
    "_camera_override_person_sensors", "_camera_override_live_person_sensors",
    "_substrate_edge_wants_refresh", "_fire_camera_hold_pages",
    "camera_input_stream_unavailable_held", "camera_input_room_quarantined",
    "_camera_stream_page_policy", "_camera_stream_page_key",
    "camera_stream_health_snapshot",
)


class RoomCoord:
    """Bare room coordinator: REAL tracker + exclusion set, REAL tick method
    (holds the page send sites) and REAL getters bound on."""

    def __init__(self, world, name, area, *, motion=(), presence=(),
                 occupancy=(), key=None, entry=True):
        self.world = world
        self.hass = world.hass
        self.name = name
        self.area = area
        self.motion = list(motion)
        self.presence = list(presence)
        self.occupancy = list(occupancy)
        self.entry = MagicMock()
        self.entry.data = {"room_name": name, CONF_ROOM_NAME: name}
        self.entry.options = {}
        self._exclusion_set = SensorExclusionSet(room_name=name)
        self._camera_stream_health = CameraInputStreamHealth(name)
        self._camera_stream_prev_dead = frozenset()
        self._camera_stream_prev_expired = frozenset()
        self._camera_stream_rechecking = False
        for meth in _ROOM_METHODS:
            fn = getattr(UniversalRoomCoordinator, meth)
            setattr(self, meth, fn.__get__(self, type(self)))
        self.key = key or f"entry_{name}"
        world.hass.data[DOMAIN][self.key] = self
        world.rooms.append(self)
        if entry:
            world.room_entry(
                name, area, motion=motion, presence=presence,
                occupancy=occupancy,
            )

    def _camera_stream_registry(self):
        return self.world.er

    def _camera_stream_device_registry(self):
        return self.world.dr

    def _get_room_area(self):
        return self.area

    def tick(self, now):
        self._exclusion_set.reset_tick()
        self._apply_camera_stream_health_tick(
            now, self.name, self.motion, self.presence, self.occupancy,
        )


class NMRec:
    """Records the inner ``fire_stuck_signal`` / ``fire_stuck_signal_recovered``
    calls (the dispatch count) behind the REAL ``fire_stuck_signal_ex``."""

    def __init__(self):
        self.pages: list[dict] = []
        self.recovers: list[dict] = []
        self.result = True

    def of(self, kind):
        return [p for p in self.pages if p["kind"] == kind]

    def rec_of(self, kind):
        return [r for r in self.recovers if r["kind"] == kind]


@pytest.fixture
def world():
    nm.reset_latches_for_tests()
    w = World()
    yield w
    w.close()
    nm.reset_latches_for_tests()


@pytest.fixture
def rec(monkeypatch):
    r = NMRec()

    async def _fire(hass, **kw):
        r.pages.append(kw)
        return r.result

    async def _recovered(hass, **kw):
        r.recovers.append(kw)
        return True

    monkeypatch.setattr(nm, "fire_stuck_signal", _fire)
    monkeypatch.setattr(nm, "fire_stuck_signal_recovered", _recovered)
    return r


class _FakeNM:
    def __init__(self):
        self.calls: list[dict] = []

    async def async_notify(self, **kw):
        self.calls.append(kw)


@pytest.fixture
def real_nm(world, monkeypatch):
    """The REAL stuck-signal module path (latches, notified set, recovery)
    against a fake NotificationManager; ``world.today`` drives the per-day
    latch date."""
    fake = _FakeNM()
    world.hass.data[DOMAIN]["notification_manager"] = fake
    monkeypatch.setattr(nm, "_kill_switch_on", lambda hass: True)
    monkeypatch.setattr(nm, "_today_iso", lambda now=None: world.today)
    return fake


def _high_titles(fake):
    return [c["title"] for c in fake.calls if str(c.get("title", "")).startswith("Camera dead")]


@pytest.fixture
def caps(monkeypatch):
    def _set(zone=900.0, census=900.0, nm_after=1800.0):
        knob(monkeypatch, "CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S", zone)
        knob(monkeypatch, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", census)
        knob(monkeypatch, "CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S", nm_after)
    return _set


def knob(monkeypatch, name, value):
    """Set a rung-1 knob on the const object the code under test holds."""
    monkeypatch.setattr(csh._const, name, value)
    if cth._const is not csh._const:
        monkeypatch.setattr(cth._const, name, value)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# The live-shape scenes
# ---------------------------------------------------------------------------

F_PLAY_CAM = "camera.playroom"
F_PLAY = "binary_sensor.playroom_person_occupancy"
P_PLAY_HI = "camera.playroom_high_resolution_channel"
P_PLAY_MED = "camera.playroom_medium_resolution_channel"
P_PLAY = "binary_sensor.playroom_person_detected"


def playroom_pair(world, *, channels=2):
    """Frigate Playroom (one camera) + Protect Playroom (2 channels): an
    admitted W1 pair (object name `playroom` == slug of the Protect device
    name)."""
    world.frigate("f_play", "playroom", "Playroom")
    cams, person = world.protect("p_play", "Playroom", "playroom", channels)
    return cams, person


def playroom_room(world, **kw):
    """The Playroom room watches both person sensors through its camera
    override (area lookup), like the live house."""
    world.camera_manager()
    world.area_sensors["playroom"] = [F_PLAY, P_PLAY]
    return RoomCoord(world, "Playroom", "playroom", **kw)


def live_pair(world, channels=2):
    cams = [F_PLAY_CAM, *[P_PLAY_HI, P_PLAY_MED,
                          "camera.playroom_low_resolution_channel",
                          "camera.playroom_package_camera"][:channels]]
    world.put({c: "streaming" for c in cams})
    world.put({F_PLAY: "off", P_PLAY: "off"})


def frigate_down(world):
    world.set(**{F_PLAY_CAM: "unavailable"})


def protect_down(world, channels=2):
    cams = [P_PLAY_HI, P_PLAY_MED, "camera.playroom_low_resolution_channel",
            "camera.playroom_package_camera"][:channels]
    world.put({c: "unavailable" for c in cams})


def protect_up(world, channels=2):
    cams = [P_PLAY_HI, P_PLAY_MED, "camera.playroom_low_resolution_channel",
            "camera.playroom_package_camera"][:channels]
    world.put({c: "streaming" for c in cams})


def run(world, owner, rooms, seconds):
    """Tick rooms then the owner at each time (seconds from T0); scheduled
    sends run after each step (as on the HA loop)."""
    for s in seconds:
        world.now = at(s)
        for r in rooms:
            r.tick(world.now)
        if owner is not None:
            owner.tick(world.now)
        world.drain()


# ===========================================================================
# 1. Device liveness (§6.1)
# ===========================================================================


def test_device_live_if_any_channel_live(world):
    """A 2-channel Protect device with ONE channel live is live: its person
    sensor (a camera-override extra) is never dead."""
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{P_PLAY: "on", P_PLAY_HI: "unavailable"})
    for s in (0, 120, 600):
        room.tick(at(s))
        assert room.camera_input_stream_dead(P_PLAY) is False


@pytest.mark.parametrize("channels", [2, 4], ids=["two", "four"])
def test_device_dead_needs_every_channel(world, channels):
    """Dead only when EVERY enabled channel reads `unavailable`: one live
    channel keeps it alive; all down -> dead at 120 s, not 119 s."""
    world.frigate("f_x", "front_x", "Front X")
    cams, person = world.protect("p_x", "Front X", "front_x", channels)
    world.camera_manager()
    world.area_sensors["front"] = [person]
    room = RoomCoord(world, "Front", "front")
    world.put({c: "unavailable" for c in cams[:-1]})
    world.set(**{cams[-1]: "streaming", person: "on"})
    room.tick(at(0))
    room.tick(at(300))
    assert room.camera_input_stream_dead(person) is False
    world.set(**{cams[-1]: "unavailable"})
    room.tick(at(400))
    room.tick(at(519))
    assert room.camera_input_stream_dead(person) is False
    room.tick(at(520))
    assert room.camera_input_stream_dead(person) is True


# Hand-derived golden for a one-camera Frigate device (today's rule):
# (seconds, camera reading, dead?)
_ONE_CAM_GOLDEN = [
    (0, "unavailable", False),     # stamp t0
    (60, "unavailable", False),
    (150, "unknown", False),       # past the grace but unknown: not dead
    (160, "unavailable", True),    # gap 100 s < grace: stamp kept -> dead
    (200, "restored", False),      # restored placeholder: no opinion
    (400, "unavailable", False),   # gap 240 s > grace: stamp restarts
    (519, "unavailable", False),
    (520, "unavailable", True),
]


@pytest.mark.parametrize("device_level", [True, False], ids=["device", "entity"])
def test_one_camera_device_rule_unchanged(world, monkeypatch, device_level):
    """INV-DEAD-INPUT: for a device whose member set is one camera entity,
    device level answers exactly the pre-3b per-camera rule, `unknown` and
    restored ticks included (golden above)."""
    knob(monkeypatch, "CAMERA_STREAM_DEVICE_LEVEL_INPUTS", device_level)
    cam, person = world.frigate("f_k", "kitchen_panel", "Kitchen Panel")
    room = RoomCoord(world, "Kitchen", "kitchen", presence=[person])
    world.set(**{person: "on"})
    got = []
    for s, reading, _want in _ONE_CAM_GOLDEN:
        world.states[cam] = restored() if reading == "restored" else st(reading)
        room.tick(at(s))
        got.append((s, room.camera_input_stream_dead(person)))
    assert got == [(s, want) for s, _r, want in _ONE_CAM_GOLDEN]


@pytest.mark.parametrize("variant", ["enable_live", "enable_while_dead"])
def test_member_set_change_rebuilds_device_rule(world, variant):
    """The member set is re-read on a registry invalidation. enable_live: a
    channel enabled live makes the device live. enable_while_dead: a channel
    that sorts FIRST is enabled while the device is dead; the stamp is keyed
    by the DEVICE, so grace and cap still count from t0 (no restart)."""
    cams, person = world.protect("p_y", "Yard Cam", "yard", 2)
    world.er.entities[cams[0]].disabled_by = "user"  # high channel disabled
    world.camera_manager()
    world.area_sensors["yard"] = [person]
    room = RoomCoord(world, "Yard", "yard")
    world.set(**{person: "on", cams[1]: "unavailable", cams[0]: "streaming"})
    room.tick(at(0))
    room.tick(at(120))
    assert room.camera_input_stream_dead(person) is True
    world.er.entities[cams[0]].disabled_by = None
    room._camera_stream_health.invalidate()
    if variant == "enable_live":
        room.tick(at(150))
        assert room.camera_input_stream_dead(person) is False
        return
    world.set(**{cams[0]: "unavailable"})
    room.tick(at(150))
    assert room.camera_input_stream_dead(person) is True
    room.tick(at(900))
    assert csh.input_stream_view(world.hass, person) == csh.VIEW_RELEASED
    # The dead map names the device's own canonical camera (now the
    # high channel, first sorted), never a twin.
    assert room._camera_stream_health._dead_now[person][0] == cams[0]


def test_loss_counts_restored_after_boot_settle(world):
    """Loss rule boot settle: a member no-opinion since setup is NOT lost at
    599 s and IS lost at 601 s (grace long passed)."""
    playroom_pair(world)
    playroom_room(world)
    world.census_entities = []
    owner = world.owner()
    world.put({F_PLAY_CAM: restored(), P_PLAY_HI: "streaming",
               P_PLAY_MED: "streaming"})
    world.now = at(0)
    owner.tick(at(0))
    owner.tick(at(599))
    assert owner._lost("f_play", at(599)) is False
    owner.tick(at(601))
    assert owner._lost("f_play", at(601)) is True


def test_reader_and_loss_rules_differ_on_restored(world):
    """Deliberate concept split (Bug Class #63): a restored placeholder never
    holds an input (reader rule: unknown is not dead) but counts toward
    LOSS after the boot settle (so NVRs stuck in setup retry still page)."""
    playroom_pair(world)
    room = playroom_room(world)
    owner = world.owner()
    world.put({F_PLAY_CAM: restored(), F_PLAY: "on", P_PLAY_HI: "streaming",
               P_PLAY_MED: "streaming", P_PLAY: "off"})
    run(world, owner, [room], (0, 300, 700))
    assert room.camera_input_stream_dead(F_PLAY) is False
    assert owner._lost("f_play", at(700)) is True


# ===========================================================================
# 2. Device-level readers (§6.2, decided Q12)
# ===========================================================================


def test_protect_override_sensor_dropped_when_device_dead(world):
    """Room camera override: a 2-channel Protect person sensor frozen `on`
    while its device is dead is dropped once the device is dead past the
    grace (before 3b it resolved `multi_camera` and kept holding)."""
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{P_PLAY: "on"})
    protect_down(world)
    room.tick(at(0))
    assert P_PLAY in room._camera_override_live_person_sensors()
    room.tick(at(119))
    assert P_PLAY in room._camera_override_live_person_sensors()
    room.tick(at(120))
    assert P_PLAY not in room._camera_override_live_person_sensors()
    assert F_PLAY in room._camera_override_live_person_sensors()


def test_protect_zone_camera_tier_held_then_released(world):
    """Zone camera tier: the Protect sensor's frozen detection holds the zone
    (unknown) from the grace to the 900 s cap, then counts as off."""
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{P_PLAY: "on"})
    tracker = ZonePresenceTracker(
        hass=world.hass, zone_name="Upstairs", room_names=["Playroom"],
    )
    protect_down(world)
    room.tick(at(0))
    tracker.update_camera_detection(P_PLAY, True)
    room.tick(at(120))
    assert tracker._any_camera_occupied() is True
    # an `off` update while dead is ignored (no absence signal)
    tracker.update_camera_detection(P_PLAY, False)
    assert P_PLAY in tracker._camera_stream_ignored
    room.tick(at(899))
    assert tracker._any_camera_occupied() is True
    room.tick(at(900))
    assert tracker._any_camera_occupied() is False


class _Mgr:
    def __init__(self, cameras):
        self._camera_by_entity = cameras

    def get_platform_for_camera(self, entity_id):
        info = self._camera_by_entity.get(entity_id)
        return info.platform if info else None

    def get_all_frigate_cameras(self):
        return [
            c for c in self._camera_by_entity.values()
            if c.platform == ura_const.CAMERA_PLATFORM_FRIGATE
        ]

    def resolve_configured_cameras(self, ids):
        return [self._camera_by_entity[i] for i in ids if i in self._camera_by_entity]


def _real_census(world, cameras):
    integ = MagicMock()
    integ.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    integ.options = {
        CONF_CAMERA_PERSON_ENTITIES: list(cameras),
        ura_const.CONF_ENHANCED_CENSUS: True,
    }
    world.entries.append(integ)
    return PersonCensus(world.hass, _Mgr(cameras))  # type: ignore[arg-type]


def _census_house(census, now):
    return _run(census._calculate_house_census(ble_persons=[], now=now))


def test_protect_census_entry_held_from_t0(world, monkeypatch):
    """Census: the Protect device drops off Wi-Fi with a body in view (the
    person sensor AND both channels `unavailable` at t0). Held from t0 (the
    last reading 1 keeps counting inside the grace), still held past it,
    then a MISSING term at the 900 s census cap."""
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: world.er, raising=False)
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    other = "binary_sensor.kitchen_person_detected"
    world.set(**{P_PLAY: "on", other: "off"})
    census = _real_census(world, {
        P_PLAY: CameraInfo(entity_id=P_PLAY, platform="unifiprotect",
                           area_id="playroom", person_binary_sensor=P_PLAY),
        other: CameraInfo(entity_id=other, platform="unifiprotect",
                          area_id="kitchen", person_binary_sensor=other),
    })
    room.tick(at(0))
    assert _census_house(census, at(0)).unifi_count == 1
    world.set(**{P_PLAY: "unavailable"})
    protect_down(world)
    # t0 of the outage = the first room tick that reads it (30 s).
    room.tick(at(30))
    assert _census_house(census, at(30)).unifi_count == 1  # held from t0
    room.tick(at(150))
    assert _census_house(census, at(150)).unifi_count == 1
    room.tick(at(929))
    assert _census_house(census, at(929)).unifi_count == 1
    room.tick(at(930))
    assert _census_house(census, at(930)).unifi_count == 0


def test_watched_device_non_input_entity_answers(world, monkeypatch):
    """House camera route (§6.2): a non-input entity on an IN-MAP
    multi-camera device that a room watches through another entity answers
    for its own device (before 3b: `multi_camera` -> None)."""
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: world.er, raising=False)
    playroom_pair(world)
    vehicle = "binary_sensor.playroom_vehicle_detected"
    world.er.add(_ent(vehicle, "p_play", "unifiprotect"))
    room = playroom_room(world)
    world.owner()
    assert world.hass.data[DOMAIN][csh.TWIN_HEALTH_DATA_KEY].in_map("p_play")
    live_pair(world)
    world.set(**{P_PLAY: "on", vehicle: "on"})
    room.tick(at(0))
    assert csh.entity_stream_dead(world.hass, vehicle) is False
    protect_down(world)
    room.tick(at(10))
    room.tick(at(130))
    assert csh.entity_stream_dead(world.hass, vehicle) is True
    assert csh.entity_stream_view(world.hass, vehicle) == csh.VIEW_HELD


def test_device_level_off_is_today(world, monkeypatch):
    """CAMERA_STREAM_DEVICE_LEVEL_INPUTS False: a multi-camera Protect person
    sensor is unresolved again (no opinion anywhere), a one-camera Frigate
    sensor is unchanged."""
    knob(monkeypatch, "CAMERA_STREAM_DEVICE_LEVEL_INPUTS", False)
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{P_PLAY: "on", F_PLAY: "on"})
    protect_down(world)
    frigate_down(world)
    room.tick(at(0))
    room.tick(at(200))
    assert room.camera_input_stream_dead(P_PLAY) is None
    assert csh.camera_stream_dead(world.hass, P_PLAY_HI) is None
    assert room.camera_input_stream_dead(F_PLAY) is True
    assert csh.camera_stream_dead(world.hass, F_PLAY_CAM) is True


# ===========================================================================
# 3. House tracker for cameras no room watches (§6.3)
# ===========================================================================

F_FOY_CAM = "camera.foyer_fisheye"
F_FOY = "binary_sensor.foyer_fisheye_person_occupancy"
P_FOY = "binary_sensor.foyer_fisheye_person_detected"
P_FOY_HI = "camera.foyer_fisheye_high_resolution_channel"
P_FOY_MED = "camera.foyer_fisheye_medium_resolution_channel"
K_CAM = "camera.kitchen_panel"
K_PERSON = "binary_sensor.kitchen_panel_person_occupancy"


def foyer_house(world, *, protect=True):
    """The live U: the foyer group (Frigate + 2-channel Protect), read by the
    census interior and (Frigate occupancy) the Entertainment zone_cameras;
    no room watches it. Plus a watched Kitchen room with a one-camera
    Frigate panel input (Wr)."""
    world.frigate("f_foy", "foyer_fisheye", "Foyer Fisheye")
    if protect:
        world.protect("p_foy", "Foyer Fisheye", "foyer_fisheye", 2,
                      mac="aa:bb:cc:00:00:02")
    world.frigate("f_kit", "kitchen_panel", "Kitchen Panel")
    world.camera_manager()
    world.census()
    world.presence()
    world.census_entities = [F_FOY] + ([P_FOY] if protect else [])
    world.zone_entities = [F_FOY]
    room = RoomCoord(world, "Kitchen", "kitchen", presence=[K_PERSON])
    world.put({F_FOY_CAM: "streaming", F_FOY: "on", K_CAM: "streaming",
               K_PERSON: "on"})
    if protect:
        world.put({P_FOY_HI: "streaming", P_FOY_MED: "streaming", P_FOY: "on"})
    return room


def _getter(name):
    if name == "camera_stream_dead":
        return lambda h, eid, cam: csh.camera_stream_dead(h, cam)
    if name == "camera_stream_hold_expired":
        return lambda h, eid, cam: csh.entity_stream_view(h, cam)
    if name == "entity_stream_dead":
        return lambda h, eid, cam: csh.entity_stream_dead(h, eid)
    if name == "entity_stream_view":
        return lambda h, eid, cam: csh.entity_stream_view(h, eid, census=True)
    return lambda h, eid, cam: csh.input_stream_view(h, eid)


@pytest.mark.parametrize("getter", [
    "camera_stream_dead", "camera_stream_hold_expired", "entity_stream_dead",
    "entity_stream_view", "input_stream_view",
])
def test_watched_camera_getters_unchanged(world, getter):
    """INV-DEAD-INPUT: (a) a camera a room watches answers exactly as with no
    owner; (b) an entity that LEFT U and whose sticky grace passed (no owner
    tick since: the house tracker still holds its stale stamp) answers as
    the rooms do (None), never from the house tracker."""
    room = foyer_house(world)
    owner = world.owner()
    get = _getter(getter)
    world.set(**{K_CAM: "unavailable", F_FOY_CAM: "unavailable"})
    run(world, owner, [room], (0, 60, 130))
    with_owner = get(world.hass, K_PERSON, K_CAM)
    world.hass.data[DOMAIN].pop(csh.TWIN_HEALTH_DATA_KEY)
    without_owner = get(world.hass, K_PERSON, K_CAM)
    world.hass.data[DOMAIN][csh.TWIN_HEALTH_DATA_KEY] = owner
    assert with_owner == without_owner
    assert with_owner is not None
    # (b) the foyer leaves U at 200 s (census and zone stop listing it):
    # sticky to 320 s; ticked at 250 s (still sticky, stamp kept).
    assert get(world.hass, F_FOY, F_FOY_CAM) is not None
    world.census_entities = [P_FOY]
    world.zone_entities = []
    run(world, owner, [room], (200, 250))
    assert get(world.hass, F_FOY, F_FOY_CAM) is not None  # sticky
    world.now = at(330)  # past the sticky grace, no owner tick yet
    assert get(world.hass, F_FOY, F_FOY_CAM) is None


def test_room_reload_window_answers_today(world):
    """A room that is reloading (its coordinator gone from hass.data, its
    config entry still there) keeps its cameras in Wr: the house tracker
    never answers for them (no room = None, as before 3b)."""
    room = foyer_house(world)
    owner = world.owner()
    world.set(**{K_CAM: "unavailable"})
    run(world, owner, [room], (0, 130))
    assert csh.input_stream_dead(world.hass, K_PERSON) is True
    world.hass.data[DOMAIN].pop(room.key)
    run(world, owner, [], (160, 300))
    assert csh.input_stream_dead(world.hass, K_PERSON) is None
    assert csh.camera_stream_dead(world.hass, K_CAM) is None
    assert K_PERSON not in owner.get_diagnostics()["unwatched"]


def test_no_house_answers_before_camera_manager(world):
    """No U and no house answer until the camera manager is present."""
    foyer_house(world)
    world.hass.data[DOMAIN].pop("camera_manager")
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0, 130, 300))
    assert owner.get_diagnostics()["unwatched"] == []
    assert csh.entity_stream_dead(world.hass, F_FOY) is None
    world.camera_manager()
    run(world, owner, [], (400, 530))
    assert csh.entity_stream_dead(world.hass, F_FOY) is True


def test_unwatched_census_camera_held_then_released(world):
    """The unwatched foyer camera dies with its census sensor frozen `on`:
    the census view is HELD from the grace to the 900 s census cap, then
    RELEASED (a missing term), exactly like a room-watched camera."""
    foyer_house(world)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0, 119))
    assert csh.entity_stream_view(world.hass, F_FOY, census=True) is None
    run(world, owner, [], (120,))
    assert csh.entity_stream_view(world.hass, F_FOY, census=True) == csh.VIEW_HELD
    run(world, owner, [], (899,))
    assert csh.entity_stream_view(world.hass, F_FOY, census=True) == csh.VIEW_HELD
    run(world, owner, [], (900,))
    assert csh.entity_stream_view(world.hass, F_FOY, census=True) == csh.VIEW_RELEASED


def test_unwatched_unavailable_with_camera_held_from_t0(world):
    """D-M1 on the house path: the foyer sensor goes `unavailable` together
    with its camera: HELD from t0 (inside the grace), not off."""
    foyer_house(world)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable", F_FOY: "unavailable"})
    run(world, owner, [], (0,))
    assert csh.input_stream_dead(world.hass, F_FOY) is False
    assert csh.input_stream_view(world.hass, F_FOY) == csh.VIEW_HELD
    assert csh.entity_stream_view(world.hass, F_FOY, census=True) == csh.VIEW_HELD


def test_unwatched_dead_before_owner_setup_is_stamped(world):
    """A camera already dead before the owner existed (no state change
    after setup) is stamped by the first owner tick's state read."""
    foyer_house(world)
    world.set(**{F_FOY_CAM: "unavailable"})
    owner = world.owner(setup_at=at(0))
    run(world, owner, [], (0, 119))
    assert csh.entity_stream_dead(world.hass, F_FOY) is False
    run(world, owner, [], (120,))
    assert csh.entity_stream_dead(world.hass, F_FOY) is True


def test_unknown_blip_does_not_restart_stamp(world):
    """`unknown` between two `unavailable` readings (gap < grace) keeps the
    house stamp: dead at 120 s from the first reading."""
    foyer_house(world)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0,))
    world.set(**{F_FOY_CAM: "unknown"})
    run(world, owner, [], (60,))
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (90, 119))
    assert csh.entity_stream_dead(world.hass, F_FOY) is False
    run(world, owner, [], (120,))
    assert csh.entity_stream_dead(world.hass, F_FOY) is True


def test_unwatched_set_flicker_keeps_stamp(world):
    """A census reload that briefly empties the list (one tick) never prunes
    a live stamp: the entity is sticky for one grace."""
    foyer_house(world)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0,))
    world.census_entities, world.zone_entities = [], []
    run(world, owner, [], (60,))
    world.census_entities, world.zone_entities = [F_FOY, P_FOY], [F_FOY]
    run(world, owner, [], (90,))
    run(world, owner, [], (120,))
    assert csh.entity_stream_dead(world.hass, F_FOY) is True


def test_camera_leaving_unwatched_set_pruned_after_grace(world):
    """An entity that leaves U for good is tracked for one grace (sticky),
    then pruned: the house answer goes back to None."""
    foyer_house(world)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0, 130))
    assert csh.entity_stream_dead(world.hass, F_FOY) is True
    world.census_entities, world.zone_entities = [P_FOY], []
    run(world, owner, [], (140, 250))
    assert csh.entity_stream_dead(world.hass, F_FOY) is True  # sticky to 260
    run(world, owner, [], (270,))
    assert csh.entity_stream_dead(world.hass, F_FOY) is None
    assert F_FOY_CAM not in owner._unwatched_tracker.dead_stamps().values()
    assert "f_foy" not in owner._unwatched_tracker.dead_stamps()


def test_unwatched_source3_foyer_skips_dead_camera(world, monkeypatch):
    """HVAC D6 Source 3 (check_zone_occupancy_confidence): the Entertainment
    zone camera `foyer_fisheye_person_occupancy` frozen `on` while its
    camera is dead confirms nothing once the house tracker holds it dead,
    so the D6 failsafe can release (before 3b: None -> it kept confirming)."""
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: world.er, raising=False)
    foyer_house(world)
    owner = world.owner()
    fake = SimpleNamespace(hass=world.hass)
    zone = SimpleNamespace(rooms=[], zone_cameras=[F_FOY], room_conditions=[])
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0,))
    assert PresenceCoordinator.check_zone_occupancy_confidence(fake, zone) == (1, 2)
    run(world, owner, [], (120,))
    assert PresenceCoordinator.check_zone_occupancy_confidence(fake, zone) == (0, 2)


def test_unwatched_set_from_public_reads(world):
    """U = (census interior_camera_entities() ∪ presence
    zone_camera_entities()) minus every entity on a watched device; read
    through the two public methods only."""
    foyer_house(world)
    world.census_entities = [F_FOY, P_FOY, K_PERSON]  # kitchen is watched
    world.zone_entities = [F_FOY, "binary_sensor.no_camera_device"]
    owner = world.owner()
    run(world, owner, [], (0,))
    assert owner.get_diagnostics()["unwatched"] == sorted([F_FOY, P_FOY])
    world.hass.data[DOMAIN]["census"] = SimpleNamespace()  # no public read
    run(world, owner, [], (30,))
    assert owner.get_diagnostics()["unwatched"] == [F_FOY]


def test_house_tracker_pages_discarded(world, rec, caps):
    """The house tracker's own page candidates (the foyer Frigate dead past
    the cap while its Protect twin is live) are discarded: the owner pages
    only through its group gate, so nothing is sent."""
    caps()
    foyer_house(world)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0, 120, 900, 930, 2000))
    assert owner._unwatched_tracker.hold_pages  # it computed a candidate
    assert rec.of(S2) == [] and rec.of(S1) == []


def test_owner_not_in_room_coordinators(world):
    """The owner never joins the room fold of the house readers."""
    room = foyer_house(world)
    owner = world.owner()
    coords = csh._room_coordinators(world.hass)
    assert room in coords
    assert owner not in coords


# ===========================================================================
# 4. Twin map (§6.4)
# ===========================================================================


@pytest.mark.parametrize("channels", [2, 3, 4])
def test_twin_map_multi_channel_protect(world, channels):
    """A Frigate device (one camera) and its W1 Protect sibling with 2, 3 or
    4 enabled channels (the live shapes) form ONE group, both directions."""
    playroom_pair(world, channels=channels)
    owner = world.owner()
    assert owner.group_for("f_play") == frozenset({"f_play", "p_play"})
    assert owner.group_for("p_play") == frozenset({"f_play", "p_play"})
    assert owner.in_map("f_play") and owner.in_map("p_play")
    assert owner.get_diagnostics()["pairs_admitted"] == [["f_play", "p_play"]]


@pytest.mark.parametrize("cameras", [1, 2], ids=["one_camera", "two_camera"])
def test_twin_map_rejects_non_nvr_sibling(world, cameras):
    """The W1 sibling of the Kitchen panel Frigate camera is an ESPHome kiosk
    panel (1 or 2 camera entities): W1 pairs it, the NVR-platform check
    rejects it, so it is a W1 candidate but not in the map."""
    world.frigate("f_kit", "kitchen_panel", "Kitchen Panel")
    world.esphome_panel("e_kit", "Kitchen Panel", "kitchen_panel", cameras)
    owner = world.owner()
    assert owner.get_diagnostics()["pairs_rejected"] == [["f_kit", "e_kit"]]
    assert not owner.in_map("f_kit") and not owner.in_map("e_kit")
    assert owner.is_map_candidate("f_kit")
    assert csh.page_camera_key(world.er, world.dr, "e_kit") == (
        "camera.kitchen_panel_camera"
    )


def test_twin_pairing_registry_only(world):
    """Pairing is registry evidence (Frigate identifier object name == slug
    of the DEVICE name), never entity-id strings: renamed entity ids still
    pair; a device whose entity ids look alike but whose device name differs
    does not."""
    world.dr.devices["f_g"] = _dev("f_g", "Garage A", idents=[("frigate", "inst1:garage_a")])
    world.er.add(_ent("camera.garage_a_2", "f_g", "frigate"),
                 _ent("binary_sensor.garage_a_person_occupancy_2", "f_g", "frigate"))
    world.dr.devices["p_g"] = _dev("p_g", "Garage A", macs=["11:22:33:44:55:66"])
    world.er.add(_ent("camera.renamed_cam_one", "p_g", "unifiprotect"),
                 _ent("camera.renamed_cam_two", "p_g", "unifiprotect"))
    world.dr.devices["p_lookalike"] = _dev("p_lookalike", "Driveway")
    world.er.add(_ent("camera.garage_a_high_resolution_channel", "p_lookalike",
                      "unifiprotect"),
                 _ent("camera.garage_a_low_resolution_channel", "p_lookalike",
                      "unifiprotect"))
    owner = world.owner()
    assert owner.group_for("f_g") == frozenset({"f_g", "p_g"})
    assert not owner.in_map("p_lookalike")


def test_twin_map_fresh_resolver_per_build(world):
    """Each build uses a FRESH resolver: a device renamed between two builds
    (name_by_user) unpairs on the second build."""
    playroom_pair(world)
    owner = world.owner()
    assert owner.in_map("p_play")
    world.dr.devices["p_play"].name_by_user = "Toy Room"
    owner._rebuild()
    assert not owner.in_map("p_play")
    assert not owner.in_map("f_play")


class _Later:
    """Captures async_call_later callbacks (the debounce)."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, hass, delay, cb):
        self.calls.append((delay, cb))
        return lambda: self.calls.remove((delay, cb)) if (delay, cb) in self.calls else None

    def fire_all(self):
        pending, self.calls = list(self.calls), []
        for _d, cb in pending:
            cb(None)


@pytest.fixture
def later(monkeypatch):
    import homeassistant.helpers.event as ev
    lat = _Later()
    monkeypatch.setattr(ev, "async_call_later", lat, raising=False)
    monkeypatch.setattr(
        ev, "async_track_time_interval", lambda *a, **k: (lambda: None),
        raising=False,
    )
    return lat


class _Bus:
    def __init__(self):
        self.listeners: dict[str, list] = {}

    def async_listen(self, event, cb):
        self.listeners.setdefault(event, []).append(cb)
        return lambda: self.listeners[event].remove(cb)

    def fire(self, event, data):
        for cb in list(self.listeners.get(event, ())):
            cb(SimpleNamespace(data=data))


def _setup_owner(world, later):
    bus = _Bus()
    world.hass.bus = bus
    o = cth.CameraTwinHealth(
        world.hass, clock=lambda: world.now,
        entity_registry_getter=lambda: world.er,
        device_registry_getter=lambda: world.dr,
    )
    world.hass.data[DOMAIN][csh.TWIN_HEALTH_DATA_KEY] = o
    _run(o.async_setup())
    return o, bus


DEV_EV = "device_registry_updated"
ENT_EV = "entity_registry_updated"


def test_twin_map_built_once_per_invalidation(world, later):
    """One relevant registry event -> exactly one debounced rebuild."""
    playroom_pair(world)
    owner, bus = _setup_owner(world, later)
    assert owner._build_count == 1  # the first build at setup
    bus.fire(ENT_EV, {"action": "update", "entity_id": P_PLAY_HI})
    assert len(later.calls) == 1
    later.fire_all()
    assert owner._build_count == 2


def test_twin_map_boot_storm_bounded(world, later):
    """A boot storm of 50 registry events inside one debounce window gives
    ONE debounce and ONE build."""
    playroom_pair(world)
    owner, bus = _setup_owner(world, later)
    for i in range(50):
        bus.fire(DEV_EV, {"action": "create", "device_id": f"d{i}"})
        bus.fire(ENT_EV, {"action": "create", "entity_id": f"camera.c{i}"})
    assert len(later.calls) == 1
    later.fire_all()
    assert owner._build_count == 2


def test_twin_map_rebuilt_on_device_rename(world, later):
    """A device RENAME (device registry update only, through the listener)
    rebuilds the map: the renamed Protect device unpairs."""
    playroom_pair(world)
    owner, bus = _setup_owner(world, later)
    assert owner.in_map("p_play")
    world.dr.devices["p_play"].name_by_user = "Toy Room"
    bus.fire(DEV_EV, {"action": "update", "device_id": "p_play",
                      "changes": {"name_by_user": None}})
    later.fire_all()
    assert not owner.in_map("p_play")


def test_twin_map_rebuilt_on_new_device(world, later):
    """The relevance filter runs at REBUILD time: a device update event that
    arrives before the device has its camera entities still rebuilds once
    the cameras exist (filtering at event time would drop it)."""
    world.frigate("f_play", "playroom", "Playroom")
    world.dr.devices["p_play"] = _dev("p_play", "Playroom", macs=["aa:00:00:00:00:09"])
    owner, bus = _setup_owner(world, later)
    assert not owner.in_map("f_play")
    bus.fire(DEV_EV, {"action": "update", "device_id": "p_play",
                      "changes": {"config_entries": []}})
    world.er.add(_ent(P_PLAY_HI, "p_play", "unifiprotect"),
                 _ent(P_PLAY_MED, "p_play", "unifiprotect"))
    later.fire_all()
    assert owner.group_for("f_play") == frozenset({"f_play", "p_play"})


def test_twin_map_rebuilt_on_camera_enable_disable(world, later):
    """An entity-registry update on a camera entity (enable / disable) is a
    rebuild trigger: disabling every Protect channel takes the pair out of
    the map (no enabled camera on that side)."""
    playroom_pair(world)
    owner, bus = _setup_owner(world, later)
    assert owner.in_map("p_play")
    for cam in (P_PLAY_HI, P_PLAY_MED):
        world.er.entities[cam].disabled_by = "user"
        bus.fire(ENT_EV, {"action": "update", "entity_id": cam,
                          "changes": {"disabled_by": None}})
    later.fire_all()
    assert not owner.in_map("p_play")


def test_failed_rebuild_keeps_old_map(world):
    """A rebuild that raises keeps the previous map."""
    playroom_pair(world)
    owner = world.owner()
    assert owner.in_map("p_play")
    world.dr.devices = _RaisingDevices(world.dr.devices)
    owner._rebuild()
    assert owner.in_map("p_play")
    assert owner._build_failures == 1


def test_failed_rebuild_sets_map_stale_since(world):
    """A failed rebuild flags the map stale (diagnostics) until a good one."""
    playroom_pair(world)
    owner = world.owner()
    assert owner.get_diagnostics()["map_stale_since"] is None
    good = world.dr.devices
    world.dr.devices = _RaisingDevices(good)
    world.now = at(50)
    owner._rebuild()
    assert owner.get_diagnostics()["map_stale_since"] == at(50).isoformat()
    world.dr.devices = good
    owner._rebuild()
    assert owner.get_diagnostics()["map_stale_since"] is None


def test_twin_map_requires_a_camera_each_side(world):
    """"Every camera is on an NVR platform" is never vacuous: a sibling with
    no ENABLED camera entity is rejected."""
    playroom_pair(world)
    for cam in (P_PLAY_HI, P_PLAY_MED):
        world.er.entities[cam].disabled_by = "integration"
    world.er.add(_ent("camera.playroom_extra", "p_play", "unifiprotect",
                      disabled_by="user"))
    owner = world.owner()
    assert not owner.in_map("p_play")


def test_failed_first_build_rooms_page(world, rec, caps):
    """The FIRST build raises: map_ready is still set (with an empty map),
    so rooms page the W1-paired device themselves (the room side reads the
    OWNER'S map, never the pure pairing: no silent outage)."""
    caps()
    playroom_pair(world)
    room = playroom_room(world)
    good = world.dr.devices
    world.dr.devices = _RaisingDevices(good)
    owner = world.owner()
    world.dr.devices = good  # the registry heals; the map stays empty
    assert owner.map_ready and not owner.in_map("p_play")
    live_pair(world)
    world.set(**{P_PLAY: "on"})
    protect_down(world)
    frigate_down(world)
    run(world, owner, [room], (0, 120, 900, 930))
    assert len(rec.of(S2)) == 2  # one per room-watched device, room keys
    assert {p["key"] for p in rec.of(S2)} == {(F_PLAY_CAM,)}


def test_rooms_defer_until_map_ready_bounded(world, rec, caps):
    """Owner present but not map-ready: rooms defer their pages (no latch),
    bounded by the 600 s boot settle from the owner's setup; past it they
    page."""
    caps(zone=300.0, census=300.0)
    cam, person = world.frigate("f_k", "kitchen_panel", "Kitchen Panel")
    room = RoomCoord(world, "Kitchen", "kitchen", presence=[person])
    world.owner(build=False, setup_at=at(0))
    world.set(**{person: "on", cam: "unavailable"})
    run(world, None, [room], (0, 300, 450, 599))
    assert rec.of(S2) == []
    run(world, None, [room], (600,))
    assert len(rec.of(S2)) == 1


def test_unload_mid_debounce_no_rebuild(world, later):
    """Teardown with a debounce pending: the callback checks `_torn_down`
    first and builds nothing; the data key is popped, listeners released."""
    playroom_pair(world)
    owner, bus = _setup_owner(world, later)
    bus.fire(DEV_EV, {"action": "create", "device_id": "x"})
    pending = list(later.calls)
    owner.async_teardown()
    assert csh.TWIN_HEALTH_DATA_KEY not in world.hass.data[DOMAIN]
    assert bus.listeners[DEV_EV] == [] and bus.listeners[ENT_EV] == []
    for _d, cb in pending:
        cb(None)
    assert owner._build_count == 1
    assert owner._unwatched_tracker._state_getter is None


# ===========================================================================
# 5. The group gate and the pages (§6.5, §6.6)
# ===========================================================================


def pair_scene(world, *, channels=2):
    """The watched Playroom pair: the room watches both person sensors
    (override extras); the owner maps the pair."""
    playroom_pair(world, channels=channels)
    room = playroom_room(world)
    owner = world.owner()
    live_pair(world, channels)
    world.set(**{F_PLAY: "on", P_PLAY: "on"})
    return room, owner


@pytest.mark.parametrize("twin", [
    "twin_live", "twin_lost", "twin_restored_after_settle", "twin_unknown",
    "twin_missing",
])
def test_physical_dead_requires_every_device(world, twin):
    """physical_camera_dead: True only when EVERY member device is LOST.
    Frigate dead from t0; the Protect twin per case."""
    room, owner = pair_scene(world)
    frigate_down(world)
    if twin == "twin_lost":
        protect_down(world)
    elif twin == "twin_restored_after_settle":
        world.put({P_PLAY_HI: restored(), P_PLAY_MED: restored()})
    elif twin == "twin_unknown":
        world.put({P_PLAY_HI: "unknown", P_PLAY_MED: "unknown"})
    elif twin == "twin_missing":
        world.states.pop(P_PLAY_HI)
        world.states.pop(P_PLAY_MED)
    run(world, owner, [room], (0, 119))
    assert cth.physical_camera_dead(world.hass, F_PLAY_CAM) is False
    run(world, owner, [room], (130, 599))
    want_599 = twin == "twin_lost"
    assert cth.physical_camera_dead(world.hass, F_PLAY_CAM) is want_599
    run(world, owner, [room], (601,))
    want = twin != "twin_live"
    assert cth.physical_camera_dead(world.hass, F_PLAY_CAM) is want
    assert cth.physical_camera_dead(world.hass, P_PLAY_HI) is want


def test_twin_blip_under_grace_no_high(world, rec, caps):
    """Frigate dead for an hour; the Protect twin blips `unavailable` for
    100 s (< grace 120 s): the twin is never LOST, the gate stays False, no
    HIGH is ever sent."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], (0, 900, 1800, 3600))
    protect_down(world)
    run(world, owner, [room], (3610, 3640, 3670, 3700))
    assert cth.physical_camera_dead(world.hass, F_PLAY_CAM) is False
    protect_up(world)
    run(world, owner, [room], (3710, 4500, 6000))
    assert rec.of(S2) == [] and rec.of(S1) == []


def test_staggered_deaths_clock(world, rec, caps):
    """Frigate dies at 0, Protect at 300: the group is fully lost from 300
    (latest member), so the HIGH goes at 300 + 900 = 1200, not at 1199."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], (0, 290))
    protect_down(world)
    run(world, owner, [room], (300, 600, 1199))
    assert rec.of(S2) == []
    run(world, owner, [room], (1200,))
    assert [p["key"] for p in rec.of(S2)] == [(F_PLAY_CAM,)]


@pytest.mark.parametrize("variant", ["caps_900", "caps_0"])
def test_one_high_per_outage(world, rec, caps, variant):
    """Both NVRs lose the camera for two hours: exactly ONE HIGH (S2 at the
    cap; with both caps 0 the owner S1 at NM_AFTER 1800 s), none from the
    rooms (in-map devices are owner-paged)."""
    if variant == "caps_900":
        caps()
    else:
        caps(zone=0.0, census=0.0)
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], range(0, 7201, 300))
    highs = rec.of(S2) + rec.of(S1)
    assert len(highs) == 1
    if variant == "caps_900":
        assert highs[0]["kind"] == S2 and highs[0]["key"] == (F_PLAY_CAM,)
    else:
        assert highs[0]["kind"] == S1
        assert highs[0]["key"] == ("<group>", F_PLAY_CAM)


def test_s1_page_silent_while_twin_live(world, rec, caps):
    """Room path: a room lists the Protect person sensor as a CONFIGURED
    input (S1-eligible) and the device is in the owner's map with a reader;
    the Frigate twin streams. Two consecutive days with Protect dead: no
    room page at all (the owner pages the group; the group is not dead)."""
    caps()
    playroom_pair(world)
    world.camera_manager()
    room = RoomCoord(world, "Playroom", "playroom", presence=[P_PLAY])
    owner = world.owner()
    live_pair(world)
    world.set(**{P_PLAY: "on"})
    protect_down(world)
    run(world, owner, [room], (0, 120, 900, 1800, 1830, 3600))
    world.today = (T0 + timedelta(days=1)).date().isoformat()
    run(world, owner, [room], (86400, 86400 + 1800, 86400 + 3600))
    assert rec.of(S1) == [] and rec.of(S2) == []
    assert len(rec.of(MEDIUM)) == 1


@pytest.mark.parametrize("variant", ["caps_0", "caps_900"])
def test_owner_s1_silent_while_twin_live(world, rec, caps, variant):
    """Owner path (the unwatched foyer group): Frigate dead long past
    NM_AFTER, Protect live: no owner S1 (and no S2)."""
    if variant == "caps_0":
        caps(zone=0.0, census=0.0)
    else:
        caps()
    foyer_house(world)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], range(0, 5401, 300))
    assert rec.of(S1) == [] and rec.of(S2) == []


def test_s2_page_silent_while_twin_live(world, rec, caps):
    """Owner path: Frigate dead long past the cap, the Protect twin streams:
    no S2 HIGH (one NVR down is the MEDIUM notice, not a camera-down)."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], range(0, 5401, 300))
    assert rec.of(S2) == []
    assert len(rec.of(MEDIUM)) == 1


def test_s1_page_fires_when_both_lost(world, rec, caps):
    """Caps both 0, both NVRs lost: the owner's S1 at the latest member's
    loss stamp + 1800 s (literal), key ("<group>", page key)."""
    caps(zone=0.0, census=0.0)
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], (0, 600, 1799))
    assert rec.of(S1) == []
    run(world, owner, [room], (1800,))
    assert [p["key"] for p in rec.of(S1)] == [("<group>", F_PLAY_CAM)]
    assert rec.of(S1)[0]["severity"] == "HIGH"


def test_both_nvrs_setup_retry_pages_after_settle(world, rec, caps):
    """Both NVR integrations stuck in setup retry since boot: every member is
    a restored placeholder (no reader stamp ever). The loss clock still
    pages: HIGH at setup + 900 s (after the 600 s settle), none at 899 s."""
    caps()
    room, owner = pair_scene(world)
    world.put({F_PLAY_CAM: restored(), P_PLAY_HI: restored(),
               P_PLAY_MED: restored()})
    run(world, owner, [room], (0, 300, 600, 899))
    assert rec.of(S2) == []
    run(world, owner, [room], (900,))
    assert [p["key"] for p in rec.of(S2)] == [(F_PLAY_CAM,)]


@pytest.mark.parametrize("variant", ["watched", "unwatched"])
def test_twin_dies_after_medium_pages_high(world, rec, caps, variant):
    """One NVR down: the MEDIUM at its loss + 900 s. The twin then dies too:
    the HIGH still goes (at the twin's loss + 900 s); the MEDIUM never
    stands in for it."""
    caps()
    if variant == "watched":
        room, owner = pair_scene(world)
        rooms = [room]
        f_cam, down_twin = F_PLAY_CAM, lambda: protect_down(world)
        world_set_f = lambda: frigate_down(world)  # noqa: E731
    else:
        foyer_house(world)
        owner = world.owner()
        rooms = []
        f_cam = F_FOY_CAM
        down_twin = lambda: world.put(  # noqa: E731
            {P_FOY_HI: "unavailable", P_FOY_MED: "unavailable"},
        )
        world_set_f = lambda: world.set(**{F_FOY_CAM: "unavailable"})  # noqa: E731
    world_set_f()
    run(world, owner, rooms, (0, 899, 900, 930))
    assert len(rec.of(MEDIUM)) == 1 and rec.of(S2) == []
    down_twin()
    run(world, owner, rooms, (1000, 1899))
    assert rec.of(S2) == []
    run(world, owner, rooms, (1900, 2200))
    assert [p["key"] for p in rec.of(S2)] == [(f_cam,)]


def test_permanently_dead_twin_does_not_mask_next_outage(world, rec, caps):
    """Frigate dies for good. Protect outage 1 -> HIGH; Protect recovers ->
    the episode ends (gate False one grace) although Frigate stays dead;
    Protect outage 2 -> a second HIGH."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], (0, 900, 1200))
    assert len(rec.of(S2)) == 1
    protect_up(world)
    run(world, owner, [room], (1300, 1450, 1600))
    assert [r["key"] for r in rec.rec_of(S2)] == [(F_PLAY_CAM,)]
    protect_down(world)
    run(world, owner, [room], (2000, 2900, 3000))
    assert len(rec.of(S2)) == 2


def test_medium_once_per_member_episode(world, rec, caps):
    """The MEDIUM goes once per member device episode (owner latch), however
    long the member stays down; a fresh member episode sends a fresh one."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], range(0, 7201, 300))
    assert len(rec.of(MEDIUM)) == 1
    m = rec.of(MEDIUM)[0]
    assert m["key"] == (F_PLAY_CAM,) and m["severity"] == "MEDIUM"
    world.set(**{F_PLAY_CAM: "streaming"})
    run(world, owner, [room], (7300, 7500))
    assert [r["key"] for r in rec.rec_of(MEDIUM)] == [(F_PLAY_CAM,)]
    frigate_down(world)
    run(world, owner, [room], (8000, 8900, 9000))
    assert len(rec.of(MEDIUM)) == 2


def test_low_on_episode_end(world, rec, caps):
    """After the HIGH, Protect comes back: once the gate has been False for
    one grace the owner sends the LOW for the group key, naming the NVR now
    live and the one still down."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], (0, 900, 1000))
    assert len(rec.of(S2)) == 1
    protect_up(world)
    run(world, owner, [room], (1100, 1219))
    assert rec.rec_of(S2) == []
    run(world, owner, [room], (1220,))
    lows = rec.rec_of(S2)
    assert [r["key"] for r in lows] == [(F_PLAY_CAM,)]
    assert lows[0]["message"] == (
        "camera.playroom is visible again on UniFi Protect; Frigate still down"
    )


def test_latch_not_set_when_send_fails(world, rec, caps):
    """A HIGH whose send returns NOT_SENT (NM missing / kill switch off /
    error) is NOT latched: the next owner tick sends it again."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    rec.result = False
    run(world, owner, [room], (0, 900))
    assert len(rec.of(S2)) == 1
    run(world, owner, [room], (930,))
    assert len(rec.of(S2)) == 2
    rec.result = True
    run(world, owner, [room], (960, 990))
    assert len(rec.of(S2)) == 3


def test_suppressed_by_shared_key_not_resent_after_midnight(world, real_nm, caps):
    """A room already sent the HIGH under the shared pure key (owner absent);
    the owner's own send reads ALREADY_SENT and is LATCHED (not retried), so
    after midnight, when the per-day latch would re-arm, nothing re-sends."""
    caps()
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{F_PLAY: "on", P_PLAY: "on"})
    frigate_down(world)
    protect_down(world)
    world.now = at(0)
    world.today = "2026-11-14"
    run(world, None, [room], (0, 900, 930))  # owner absent: rooms page
    assert len(_high_titles(real_nm)) == 1
    owner = world.owner()
    # The owner stamps from its own first tick (960 s): its S2 is due at
    # 960 + 900 and reads ALREADY_SENT.
    run(world, owner, [room], (960, 1100, 1860, 1890))
    assert len(_high_titles(real_nm)) == 1
    assert owner.last_results.get(f"high:{F_PLAY_CAM}") == nm.ALREADY_SENT
    world.today = "2026-11-15"
    run(world, owner, [room], (86400, 86430, 86460))
    assert len(_high_titles(real_nm)) == 1


def test_room_paged_then_owner_takeover_next_outage_pages(world, real_nm, caps):
    """Owner absent: the room pages HIGH. The owner takes over mid-outage
    (no second HIGH). The camera recovers: the room sends no LOW (in the
    map), the OWNER does (it owns the outage at its end). A later outage the
    same day pages again."""
    caps()
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{F_PLAY: "on", P_PLAY: "on"})
    frigate_down(world)
    protect_down(world)
    run(world, None, [room], (0, 900, 930))
    assert len(_high_titles(real_nm)) == 1
    owner = world.owner()
    run(world, owner, [room], (960, 1000))
    world.set(**{F_PLAY_CAM: "streaming"})
    protect_up(world)
    run(world, owner, [room], (1100, 1300))
    lows = [c for c in real_nm.calls if str(c["title"]).startswith("Stuck signal recovered")]
    assert len(lows) == 1
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], (2000, 2900, 3000))
    assert len(_high_titles(real_nm)) == 2


def test_device_leaves_map_room_sends_low(world, rec, caps, later):
    """Mid-outage the pair dissolves (the Protect device is renamed): the
    owner closes its episode (dissolve LOW); the room now pages the Protect
    device under its OWN key, and sends that LOW itself when it recovers."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], (0, 900, 1000))
    assert [p["key"] for p in rec.of(S2)] == [(F_PLAY_CAM,)]
    world.dr.devices["p_play"].name_by_user = "Toy Room"
    owner._rebuild()
    assert not owner.in_map("p_play")
    run(world, owner, [room], (1030, 1060))
    assert (P_PLAY_HI,) in [p["key"] for p in rec.of(S2)]
    protect_up(world)
    run(world, owner, [room], (1200, 1230))
    assert (P_PLAY_HI,) in [r["key"] for r in rec.rec_of(S2)]


def test_room_then_owner_same_device_one_dispatch(world, real_nm, caps):
    """Owner ABSENT when the room (watching the PROTECT member only) pages:
    the room keys its page with the PURE page key (the Frigate camera of the
    W1 pair), so the owner's later page of the same group reads
    ALREADY_SENT: ONE dispatch for the outage."""
    caps()
    playroom_pair(world)
    world.camera_manager()
    world.area_sensors["playroom"] = [P_PLAY]
    room = RoomCoord(world, "Playroom", "playroom")
    live_pair(world)
    world.set(**{P_PLAY: "on"})
    frigate_down(world)
    protect_down(world)
    run(world, None, [room], (0, 900, 930))
    assert len(_high_titles(real_nm)) == 1
    owner = world.owner()
    run(world, owner, [room], (960, 1200, 2000))
    assert len(_high_titles(real_nm)) == 1


def test_pair_dissolves_mid_outage_no_spurious_low(world, rec, caps):
    """The owner sent the HIGH under the episode-FROZEN group key. Mid-outage
    the Frigate camera entity is renamed (the pure key moves) and the pair
    dissolves: exactly one LOW, for the FROZEN key (the one latched), with
    the dissolve text; never a LOW under another key while the old one
    stays latched."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], (0, 900, 1000))
    assert [p["key"] for p in rec.of(S2)] == [(F_PLAY_CAM,)]
    renamed = "camera.playroom_frigate"
    world.er.entities.pop(F_PLAY_CAM)
    world.er.add(_ent(renamed, "f_play", "frigate"))
    world.set(**{renamed: "unavailable"})
    world.dr.devices["p_play"].name_by_user = "Toy Room"
    owner._rebuild()
    run(world, owner, [room], (1030,))
    lows = rec.rec_of(S2)
    assert [r["key"] for r in lows] == [(F_PLAY_CAM,)]
    assert lows[0]["message"] == (
        "camera.playroom is now watched per NVR; pages follow per device"
    )


def test_dissolve_low_text(world, rec, caps):
    """The dissolve LOW has its own text (not "visible again")."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], (0, 900, 1000))
    world.dr.devices["p_play"].name_by_user = "Toy Room"
    owner._rebuild()
    run(world, owner, [room], (1030,))
    texts = [r["message"] for r in rec.rec_of(S2)]
    assert texts and all("visible again" not in t for t in texts)
    assert "pages follow per device" in texts[0]


def test_twin_blip_after_long_outage_no_early_high(world, rec, caps):
    """Frigate dead since 0 (an hour); Protect has an ordinary 150 s outage
    at 3600: the group is fully lost only from Protect's loss, so the HIGH
    would need 3600 + 900: none in the blip (the earliest-member clock would
    page at once, two minutes into the only unobservable period)."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], (0, 900, 1800, 3590))
    protect_down(world)
    run(world, owner, [room], (3600, 3700, 3720, 3730, 3745))
    assert cth.physical_camera_dead(world.hass, F_PLAY_CAM) is True
    protect_up(world)
    run(world, owner, [room], (3750, 4000, 6000))
    assert rec.of(S2) == []


def test_owner_s1_never_with_positive_cap(world, rec, caps):
    """NM_AFTER below the cap (legal, rung 1): the owner sends only the S2 at
    the cap, never an S1 (so NM_AFTER < cap cannot give two HIGHs)."""
    caps(zone=900.0, census=900.0, nm_after=300.0)
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], range(0, 3601, 150))
    assert rec.of(S1) == []
    assert len(rec.of(S2)) == 1


def test_reader_less_group_never_pages(world, rec, caps):
    """An admitted pair no URA reader uses (a perimeter ring camera: no room,
    census or zone entry): both NVRs lose it, nothing pages from 3b."""
    caps()
    world.frigate("f_back", "back_yard", "Back Yard")
    world.protect("p_back", "Back Yard", "back_yard", 2, mac="aa:bb:cc:00:00:07")
    world.camera_manager()
    world.census()
    world.presence()
    owner = world.owner()
    assert owner.in_map("p_back")
    world.put({"camera.back_yard": "unavailable",
               "camera.back_yard_high_resolution_channel": "unavailable",
               "camera.back_yard_medium_resolution_channel": "unavailable"})
    run(world, owner, [], range(0, 3601, 300))
    assert rec.pages == []


def test_medium_for_member_in_setup_retry(world, rec, caps):
    """One NVR stuck in setup retry since boot (restored placeholders), its
    twin live: the MEDIUM still goes, on the LOSS clock (setup + 900 s,
    after the 600 s settle); a reader-stamp MEDIUM would never fire."""
    caps()
    room, owner = pair_scene(world)
    world.put({F_PLAY_CAM: restored()})
    run(world, owner, [room], (0, 600, 899))
    assert rec.of(MEDIUM) == []
    run(world, owner, [room], (900,))
    assert len(rec.of(MEDIUM)) == 1


def test_owner_page_texts(world, rec, caps):
    """The owner's texts (§6.6): MEDIUM, HIGH S2, LOW."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], (0, 900))
    assert rec.of(MEDIUM)[0]["diagnosis"] == (
        "Frigate has lost camera.playroom; UniFi Protect still sees it."
    )
    protect_down(world)
    run(world, owner, [room], (1000, 1900))
    high = rec.of(S2)[0]
    assert high["diagnosis"] == (
        "Every NVR has lost camera.playroom for 15 min; its URA inputs are "
        "released."
    )
    assert high["title_override"] == "Camera dead 15 min: camera.playroom"
    assert high["severity"] == "HIGH"
    world.set(**{F_PLAY_CAM: "streaming"})
    protect_up(world)
    run(world, owner, [room], (2000, 2200))
    assert rec.rec_of(S2)[0]["message"] == (
        "camera.playroom is visible again on Frigate, UniFi Protect"
    )


def test_camera_getter_never_answers_for_twin(world):
    """Readers get their OWN device's answer, keyed by its own canonical
    camera: a room watching only the Protect member never answers for the
    Frigate camera (and the exclusion reason / dead map name the Protect
    device's own camera, not the page key)."""
    playroom_pair(world)
    world.camera_manager()
    world.area_sensors["playroom"] = [P_PLAY]
    room = RoomCoord(world, "Playroom", "playroom")
    world.owner()
    live_pair(world)
    world.set(**{P_PLAY: "on"})
    frigate_down(world)
    room.tick(at(0))
    room.tick(at(200))
    assert csh.camera_stream_dead(world.hass, F_PLAY_CAM) is None
    assert csh.camera_stream_dead(world.hass, P_PLAY_HI) is False
    protect_down(world)
    room.tick(at(300))
    room.tick(at(420))
    assert csh.camera_stream_dead(world.hass, P_PLAY_HI) is True
    assert csh.camera_stream_dead(world.hass, P_PLAY_MED) is True
    assert csh.camera_stream_dead(world.hass, F_PLAY_CAM) is None
    assert room._camera_stream_health._dead_now[P_PLAY][0] == P_PLAY_HI
    assert room._exclusion_set.provenance(P_PLAY)["camera_stream_dead"].startswith(
        f"{P_PLAY_HI} unavailable since",
    )


@pytest.mark.parametrize("members", [
    "restored_unavailable", "unknown_unavailable", "live_unavailable",
])
def test_classifier_mixed_members(world, members):
    """The held-from-t0 classifier under device level reads ONE device value:
    DEAD-READ (no member live, at least one `unavailable` not restored)
    holds; any live member does not."""
    playroom_pair(world)
    room = playroom_room(world)
    other = {"restored_unavailable": restored(), "unknown_unavailable": st("unknown"),
             "live_unavailable": st("streaming")}[members]
    world.put({P_PLAY_HI: other, P_PLAY_MED: "unavailable",
               P_PLAY: "unavailable", F_PLAY_CAM: "streaming", F_PLAY: "off"})
    room.tick(at(0))
    want = members != "live_unavailable"
    assert room.camera_input_stream_unavailable_held(P_PLAY) is want
    assert (csh.input_stream_view(world.hass, P_PLAY) == csh.VIEW_HELD) is want


def test_unwatched_no_twin_pages_like_room(world, rec, caps):
    """A camera in U with NO twin (a one-member group): the owner pages it
    like a room would: S2 at its loss + 900 s, key its own camera."""
    caps()
    foyer_house(world, protect=False)
    owner = world.owner()
    world.set(**{F_FOY_CAM: "unavailable"})
    run(world, owner, [], (0, 899))
    assert rec.of(S2) == []
    run(world, owner, [], (900, 1800, 3600))
    assert [p["key"] for p in rec.of(S2)] == [(F_FOY_CAM,)]
    world.set(**{F_FOY_CAM: "streaming"})
    run(world, owner, [], (3700, 3900))
    assert [r["key"] for r in rec.rec_of(S2)] == [(F_FOY_CAM,)]


def test_owner_after_midnight_reload_no_second_high(world, real_nm, caps):
    """CM entry reload at 23:58 (owner absent); a room's S2 HIGH at 23:59;
    the owner back at 00:01: its send of the same pure key reads
    ALREADY_SENT (unrecovered, whatever the date), not a second HIGH."""
    caps()
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{F_PLAY: "on", P_PLAY: "on"})
    frigate_down(world)
    protect_down(world)
    base = 23 * 3600 + 44 * 60  # 23:44 local on T0's day
    world.today = "2026-11-14"
    run(world, None, [room], (base, base + 900))  # room S2 at 23:59
    assert len(_high_titles(real_nm)) == 1
    world.today = "2026-11-15"
    owner = world.owner(setup_at=at(base + 1020))
    run(world, owner, [room], (base + 1020, base + 1050, base + 1200))
    assert len(_high_titles(real_nm)) == 1


def test_owner_adopts_room_s1_key_caps_0(world, real_nm, caps):
    """Caps both 0: a room's S1 page (room, input) of a member device sent
    while the owner was absent is adopted as the group episode's HIGH: no
    owner S1 under ("<group>", key)."""
    caps(zone=0.0, census=0.0)
    playroom_pair(world)
    world.camera_manager()
    room = RoomCoord(world, "Playroom", "playroom", presence=[P_PLAY])
    live_pair(world)
    world.set(**{P_PLAY: "on"})
    frigate_down(world)
    protect_down(world)
    run(world, None, [room], (0, 1800, 1830))
    s1 = [c for c in real_nm.calls if str(c["title"]).startswith("Camera stream dead")]
    assert len(s1) == 1
    owner = world.owner()
    run(world, owner, [room], (1860, 1900, 3700, 4000))
    s1 = [c for c in real_nm.calls if str(c["title"]).startswith("Camera stream dead")]
    assert len(s1) == 1


def test_owner_reload_mid_outage_no_false_high(world, rec, caps):
    """The owner is rebuilt (CM reload) while Frigate is long dead and its
    Protect twin streams: the fresh owner sends no HIGH."""
    caps()
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], (0, 900, 3600))
    owner.async_teardown()
    owner2 = world.owner(setup_at=at(3610))
    run(world, owner2, [room], range(3610, 9000, 300))
    assert rec.of(S2) == [] and rec.of(S1) == []


def test_no_twin_pages_as_today(world, rec, caps):
    """A one-camera device a room watches with no twin (the Kitchen panel's
    W1 sibling is an ESPHome kiosk, rejected) pages from the room exactly as
    before 3b: S2 at the cap, key its own camera; LOW on recovery."""
    caps()
    cam, person = world.frigate("f_kit", "kitchen_panel", "Kitchen Panel")
    world.esphome_panel("e_kit", "Kitchen Panel", "kitchen_panel", 2)
    room = RoomCoord(world, "Kitchen", "kitchen", presence=[person])
    owner = world.owner()
    world.set(**{person: "on", cam: "unavailable"})
    run(world, owner, [room], (0, 899))
    assert rec.of(S2) == []
    run(world, owner, [room], (900, 930))
    assert [p["key"] for p in rec.of(S2)] == [(cam,)]
    assert "seen by room Kitchen" in rec.of(S2)[0]["diagnosis"]
    world.set(**{cam: "streaming"})
    run(world, owner, [room], (960,))
    assert [r["key"] for r in rec.rec_of(S2)] == [(cam,)]


@pytest.mark.parametrize("kind", ["s1", "s2"])
def test_not_sent_retries_next_tick(world, rec, caps, kind):
    """Room path: a page whose send returns NOT_SENT sets no latch; the
    candidate comes back on the next tick."""
    if kind == "s2":
        caps()
        want_kind, first = S2, 900
    else:
        caps(zone=0.0, census=0.0)
        want_kind, first = S1, 1800
    cam, person = world.frigate("f_kit", "kitchen_panel", "Kitchen Panel")
    room = RoomCoord(world, "Kitchen", "kitchen", presence=[person])
    world.set(**{person: "on", cam: "unavailable"})
    rec.result = False
    run(world, None, [room], (0, first))
    assert len(rec.of(want_kind)) == 1
    run(world, None, [room], (first + 30,))
    assert len(rec.of(want_kind)) == 2
    rec.result = True
    run(world, None, [room], (first + 60, first + 90))
    assert len(rec.of(want_kind)) == 3


@pytest.mark.parametrize("kind", ["s2", "s1_caps_0"])
def test_deferred_page_not_marked_hold_paged(world, rec, caps, kind):
    """A page deferred while the owner is not map-ready sets NO latch: once
    the deferral bound passes, the page is sent (once)."""
    if kind == "s2":
        caps(zone=300.0, census=300.0)
        want_kind = S2
    else:
        caps(zone=0.0, census=0.0, nm_after=300.0)
        want_kind = S1
    cam, person = world.frigate("f_kit", "kitchen_panel", "Kitchen Panel")
    room = RoomCoord(world, "Kitchen", "kitchen", presence=[person])
    world.owner(build=False, setup_at=at(0))
    world.set(**{person: "on", cam: "unavailable"})
    run(world, None, [room], (0, 300, 450, 599))
    assert rec.of(want_kind) == []
    assert not room._camera_stream_health._hold_paged
    assert not room._camera_stream_health._paged_episode
    run(world, None, [room], (600, 630, 660))
    assert len(rec.of(want_kind)) == 1


def test_takeover_mid_outage_no_spurious_low(world, real_nm, caps):
    """Regression (build finding): the owner takes over mid-outage after a
    room-sent HIGH while both NVRs are still dead. Its own loss stamps need
    one grace to mature; that unknown stretch must neither end the adopted
    episode (a false "visible again" LOW) nor lead to a second HIGH."""
    caps()
    playroom_pair(world)
    room = playroom_room(world)
    live_pair(world)
    world.set(**{F_PLAY: "on", P_PLAY: "on"})
    frigate_down(world)
    protect_down(world)
    run(world, None, [room], (0, 900, 930))
    assert len(_high_titles(real_nm)) == 1
    owner = world.owner()
    run(world, owner, [room], range(960, 3600, 30))
    lows = [c for c in real_nm.calls
            if str(c["title"]).startswith("Stuck signal recovered")]
    assert lows == []
    assert len(_high_titles(real_nm)) == 1


# ===========================================================================
# 6. Kill-switch matrix (§6.7) and config extremes
# ===========================================================================


def matrix_scene(world):
    """The watched Playroom pair (room override) + the unwatched foyer group
    (census / zone); everything dead from t0 except as the case says."""
    playroom_pair(world)
    world.frigate("f_foy", "foyer_fisheye", "Foyer Fisheye")
    world.protect("p_foy", "Foyer Fisheye", "foyer_fisheye", 2,
                  mac="aa:bb:cc:00:00:02")
    world.camera_manager()
    world.area_sensors["playroom"] = [F_PLAY, P_PLAY]
    world.census()
    world.presence()
    world.census_entities = [F_FOY, P_FOY]
    world.zone_entities = [F_FOY]
    room = RoomCoord(world, "Playroom", "playroom")
    owner = world.owner()
    live_pair(world)
    world.put({F_PLAY: "on", P_PLAY: "on", F_FOY: "on", P_FOY: "on",
               F_FOY_CAM: "unavailable", P_FOY_HI: "unavailable",
               P_FOY_MED: "unavailable"})
    frigate_down(world)
    protect_down(world)
    return room, owner


_MATRIX = {
    # name: (master, twin, stamps)
    "master_off": (False, True, True),
    "twin_off_stamps_off": (True, False, False),
    "twin_off_stamps_on": (True, False, True),
    "twin_on_stamps_off": (True, True, False),
    "full": (True, True, True),
}


@pytest.mark.parametrize("row", sorted(_MATRIX))
def test_kill_switch_matrix(world, rec, caps, monkeypatch, row):
    """Every §6.7 row. The twin rule is flipped AFTER the map build (a
    runtime flip leaves a stale map), so the page-scope and room-policy
    gates are what decide."""
    caps()
    master, twin, stamps = _MATRIX[row]
    room, owner = matrix_scene(world)
    knob(monkeypatch, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", master)
    knob(monkeypatch, "CAMERA_STREAM_DEAD_TWIN_RULE", twin)
    knob(monkeypatch, "CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED", stamps)
    run(world, owner, [room], (0, 120, 900, 930, 1200))
    s2_keys = sorted(p["key"] for p in rec.of(S2))
    house_foyer = csh.entity_stream_dead(world.hass, F_FOY)
    if row == "master_off":
        assert room.camera_input_stream_dead(P_PLAY) is False
        assert house_foyer is None
        assert rec.pages == []
        return
    assert room.camera_input_stream_dead(P_PLAY) is True
    if row == "twin_off_stamps_off":
        # rooms page every watched device (own keys); no owner pages; no
        # house answers
        assert s2_keys == sorted([(F_PLAY_CAM,), (P_PLAY_HI,)])
        assert house_foyer is None
    elif row == "twin_off_stamps_on":
        # house tracker for U; the owner pages U one-member groups; rooms
        # page every watched device
        assert house_foyer is True
        assert s2_keys == sorted([(F_PLAY_CAM,), (P_PLAY_HI,), (F_FOY_CAM,),
                                  (P_FOY_HI,)])
    elif row == "twin_on_stamps_off":
        # twin map and group pages; no house answers
        assert house_foyer is None
        assert s2_keys == sorted([(F_PLAY_CAM,), (F_FOY_CAM,)])
    else:
        assert house_foyer is True
        assert s2_keys == sorted([(F_PLAY_CAM,), (F_FOY_CAM,)])


def test_kill_switch_device_level_off_bullet(world, rec, caps, monkeypatch):
    """CAMERA_STREAM_DEVICE_LEVEL_INPUTS False: per entity as before 3b in
    every reader (the Protect multi-channel sensor has no opinion); the owner
    still uses device liveness for its pages."""
    caps()
    room, owner = matrix_scene(world)
    knob(monkeypatch, "CAMERA_STREAM_DEVICE_LEVEL_INPUTS", False)
    run(world, owner, [room], (0, 120, 900, 930))
    assert room.camera_input_stream_dead(P_PLAY) is None
    assert room.camera_input_stream_dead(F_PLAY) is True
    assert csh.entity_stream_dead(world.hass, P_FOY) is None
    assert csh.entity_stream_dead(world.hass, F_FOY) is True
    assert sorted(p["key"] for p in rec.of(S2)) == sorted(
        [(F_PLAY_CAM,), (F_FOY_CAM,)],
    )


def test_kill_switch_notice_off_bullet(world, rec, caps, monkeypatch):
    """CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED False: no MEDIUM."""
    caps()
    knob(monkeypatch, "CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED", False)
    room, owner = pair_scene(world)
    frigate_down(world)
    run(world, owner, [room], range(0, 3601, 300))
    assert rec.of(MEDIUM) == []


def test_kill_switch_caps_zero_bullet(world, rec, caps):
    """Caps both 0: S2 never fires, S1 does (owner, both lost); no hold
    expires, so no MEDIUM; the unpaired multi-camera devices reached only as
    override extras never page S1 (as Frigate extras today)."""
    caps(zone=0.0, census=0.0)
    room, owner = pair_scene(world)
    tmix_cams, tmix = world.reolink_trackmix()
    world.area_sensors["playroom"].append(tmix)
    world.put({c: "unavailable" for c in tmix_cams})
    world.set(**{tmix: "on"})
    frigate_down(world)
    run(world, owner, [room], range(0, 3601, 300))
    assert rec.of(S2) == [] and rec.of(MEDIUM) == []
    assert room.camera_input_stream_dead(tmix) is True
    assert rec.of(S1) == []  # Frigate alone down: no group S1; extras never S1
    protect_down(world)
    run(world, owner, [room], range(3700, 7300, 300))
    assert [p["key"] for p in rec.of(S1)] == [("<group>", F_PLAY_CAM)]


def test_kill_switch_nm_after_zero_bullet(world, rec, caps):
    """NM_AFTER 0 with caps 0: no S1 from anyone."""
    caps(zone=0.0, census=0.0, nm_after=0.0)
    room, owner = pair_scene(world)
    frigate_down(world)
    protect_down(world)
    run(world, owner, [room], range(0, 7201, 300))
    assert rec.pages == []


def test_unpaired_multi_camera_device_room_page(world, rec, caps):
    """Named new page (§6.0): an unpaired multi-camera device a room watches
    (the Reolink TrackMix, 2 cameras) now pages from the room per device at
    the cap, key its own canonical camera."""
    caps()
    cams, person = world.reolink_trackmix()
    world.camera_manager()
    world.area_sensors["patio"] = [person]
    room = RoomCoord(world, "Patio", "patio")
    owner = world.owner()
    world.put({c: "unavailable" for c in cams})
    world.set(**{person: "on"})
    run(world, owner, [room], (0, 120, 899))
    assert rec.of(S2) == []
    run(world, owner, [room], (900, 930))
    assert [p["key"] for p in rec.of(S2)] == [(cams[0],)]


def test_dual_lens_package_channel_is_a_member(world):
    """Dual-lens doorbell (4 channels incl. the package camera): the package
    channel is a device member (no registry field marks it; carded
    DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1), so a live package channel keeps
    the device live. Named residual, no live effect (no reader)."""
    cams, person = world.protect("p_g6", "Madrone G6 Entry", "madrone_g6_entry", 4)
    world.camera_manager()
    world.area_sensors["porch"] = [person]
    room = RoomCoord(world, "Porch", "porch")
    world.put({c: "unavailable" for c in cams[:3]})
    world.set(**{cams[3]: "streaming", person: "on"})
    room.tick(at(0))
    room.tick(at(300))
    assert room.camera_input_stream_dead(person) is False


# ===========================================================================
# 7. Readers held as today (INV-DEAD-INPUT, INV-ANCHOR)
# ===========================================================================


@pytest.mark.parametrize("reader", ["substrate", "census", "ledger"])
def test_dead_inputs_held_as_today(world, monkeypatch, reader):
    """A one-camera Frigate room input (the live Up Hallway panel shape)
    answers EXACTLY as before 3b with the owner present: the same view at
    the same boundaries for the substrate (zone cap), the census (census
    cap) and the ledger anchor (any non-None view holds, RELEASED included),
    owner present == owner absent."""
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: world.er, raising=False)
    cam, person = world.frigate("f_up", "up_hallway_panel", "Up Hallway Panel")
    world.camera_manager()
    world.census()
    world.presence()
    room = RoomCoord(world, "Upstairs Hallway", "upstairs_hallway", presence=[person])
    owner = world.owner()
    world.set(**{person: "on", cam: "unavailable"})
    census = reader == "census"
    want = {0: None, 119: None, 120: csh.VIEW_HELD, 899: csh.VIEW_HELD,
            900: csh.VIEW_RELEASED}
    for s in sorted(want):
        run(world, owner, [room], (s,))
        with_owner = (
            csh.input_stream_view(world.hass, person, census=census)
            if reader != "ledger" else csh.entity_stream_view(world.hass, person)
        )
        world.hass.data[DOMAIN].pop(csh.TWIN_HEALTH_DATA_KEY)
        without = (
            csh.input_stream_view(world.hass, person, census=census)
            if reader != "ledger" else csh.entity_stream_view(world.hass, person)
        )
        world.hass.data[DOMAIN][csh.TWIN_HEALTH_DATA_KEY] = owner
        assert with_owner == without == want[s], s
    if reader == "ledger":
        from custom_components.universal_room_automation import crossing_ledger as cl
        view = csh.entity_stream_view(world.hass, person)
        held, dead_held = cl.classify_held(
            {person: ("on", True if view is not None else None)}, {},
        )
        assert person in held and person in dead_held



# ===========================================================================
# 8. Wire-in anchors: the two public reads driven for real (the CM setup /
#    unload call sites: test_camera_twin_health_setup_wirein.py)
# ===========================================================================


def test_real_census_interior_camera_entities(world):
    """PersonCensus.interior_camera_entities() returns the RESOLVED person
    sensors of the configured interior cameras (not the stored camera ids)."""
    person = "binary_sensor.family_room_person_detected"
    census = _real_census(world, {
        "camera.family_room_high_resolution_channel": CameraInfo(
            entity_id="camera.family_room_high_resolution_channel",
            platform="unifiprotect", area_id="family_room",
            person_binary_sensor=person,
        ),
    })
    assert census.interior_camera_entities() == [person]


def test_real_presence_zone_camera_entities(world):
    """PresenceCoordinator.zone_camera_entities() = the zone camera tier's
    registered cameras ∪ the Zone Manager zones' zone_cameras picks."""
    tracker = ZonePresenceTracker(
        hass=world.hass, zone_name="Upstairs", room_names=["Playroom"],
    )
    tracker.register_camera(P_PLAY)
    zm = MagicMock()
    zm.data = {CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_ZONE_MANAGER}
    zm.options = {"zones": {"Entertainment": {"zone_cameras": [F_FOY]},
                            "Upstairs": {"zone_cameras": []}}}
    world.entries.append(zm)
    fake = SimpleNamespace(hass=world.hass, _zone_trackers={"Upstairs": tracker})
    assert PresenceCoordinator.zone_camera_entities(fake) == sorted([P_PLAY, F_FOY])

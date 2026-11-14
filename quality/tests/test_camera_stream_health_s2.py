"""Camera input stream health S2: zone tier, fan readers and census honour
the ONE room getter (``camera_input_stream_dead``) and its camera-keyed form.

Plan: docs/planning/PLANNING_camera_input_stream_health.md (S2, §7).
Bug classes guarded: #53 one missed site (every reader below is driven),
#62 hollow anchor (production code is driven, never grepped), #63 two views of
one fact (the zone and the room must agree on a dead input).

The room side is the REAL tracker evaluated by the REAL
``_apply_camera_stream_health_tick`` (the method that contains the S2
discharge call), with the REAL getters bound onto a bare room object. The
oracles are hand-derived from the Up Hallway outage shape: the panel person
sensor frozen ``on`` while its Frigate camera entity reads ``unavailable``;
grace boundaries use the literals 119 / 120 s.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstrap homeassistant mocks
from _provenance_harness import fake_room_entry, make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import fan_veto
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    PersonCensus,
)
from custom_components.universal_room_automation.const import (
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_ROOM_NAME,
    DOMAIN,
)
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators import (
    camera_stream_health as csh,
)
from custom_components.universal_room_automation.domain_coordinators.camera_stream_health import (  # noqa: E501
    CameraInputStreamHealth,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)
from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
    PresenceCoordinator,
    ZonePresenceTracker,
)
from custom_components.universal_room_automation.domain_coordinators.sensor_exclusion import (  # noqa: E501
    SensorExclusionSet,
)

ROOM = "Upstairs Hallway"
PANEL = "binary_sensor.up_hallway_panel_person_occupancy"
PANEL_CAM = "camera.up_hallway_panel"
PANEL_COUNT = "sensor.up_hallway_panel_person_count"
ZV = "binary_sensor.upstairs_hallway_motion_presence_2"
OTHER_CAM = "camera.kitchen_panel"
T0 = datetime(2026, 11, 11, 22, 52, 0)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Registry:
    def __init__(self, entries):
        self._by_id = {e.entity_id: e for e in entries}
        self.entities = self

    def async_get(self, entity_id):
        return self._by_id.get(entity_id)

    def get_entries_for_device_id(self, device_id, include_disabled=False):
        return [e for e in self._by_id.values() if e.device_id == device_id]


def _entry(eid, device_id, platform="frigate"):
    return SimpleNamespace(
        entity_id=eid, device_id=device_id, platform=platform, disabled_by=None,
    )


def _registry(panel_has_camera=True):
    entries = [
        _entry(PANEL, "dev_panel"),
        _entry(PANEL_COUNT, "dev_panel"),
        _entry(ZV, "dev_zv", platform="mqtt"),
        _entry(OTHER_CAM, "dev_kitchen"),
    ]
    if panel_has_camera:
        entries.append(_entry(PANEL_CAM, "dev_panel"))
    return _Registry(entries)


class _State(SimpleNamespace):
    pass


def _st(value, **attrs):
    return _State(state=value, attributes=dict(attrs), last_changed=None)


class _House:
    """hass with a states dict; hass.data[DOMAIN] holds the room."""

    def __init__(self):
        self.states: dict = {}
        self.hass = make_hass()
        self.hass.states.get = lambda eid: self.states.get(eid)
        self.hass.data = {DOMAIN: {}}
        self.tasks: list = []

        def _capture(coro, *a, **kw):
            self.tasks.append(coro)
            return MagicMock()

        self.hass.async_create_task = _capture

    def set(self, **kv):
        for k, v in kv.items():
            self.states[k] = v if isinstance(v, _State) else _st(v)

    def close(self):
        for c in self.tasks:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self.tasks.clear()


class _RoomCoord:
    """Bare room coordinator: REAL tracker + exclusion set, REAL tick method
    (which holds the S2 discharge call) and REAL getters bound on."""

    def __init__(self, house, registry, *, motion=(ZV,), presence=(PANEL,)):
        self.hass = house.hass
        self.registry = registry
        self.motion = list(motion)
        self.presence = list(presence)
        self.entry = MagicMock()
        self.entry.data = {"room_name": ROOM, CONF_ROOM_NAME: ROOM}
        self.entry.options = {}
        self._exclusion_set = SensorExclusionSet(room_name=ROOM)
        self._camera_stream_health = CameraInputStreamHealth(ROOM)
        self._camera_stream_prev_dead = frozenset()
        for name in (
            "_apply_camera_stream_health_tick", "_notify_substrate_stream_flips",
            "camera_input_stream_dead", "camera_stream_dead",
            "_camera_override_person_sensors",
        ):
            fn = getattr(UniversalRoomCoordinator, name)
            setattr(self, name, fn.__get__(self, type(self)))
        house.hass.data[DOMAIN]["entry_room"] = self

    def _camera_stream_registry(self):
        return self.registry

    def _get_room_area(self):
        return None

    def tick(self, now):
        self._exclusion_set.reset_tick()
        self._apply_camera_stream_health_tick(
            now, ROOM, self.motion, self.presence, [],
        )


@pytest.fixture
def switch_off(per_entity_off, monkeypatch):
    """per_entity_off, plus the const objects the code under test actually
    holds (another test file may have re-imported const since collection)."""
    for fn in (
        OccupancySubstrate.recheck_entities,
        PresenceCoordinator._zone_night_rooms,
    ):
        monkeypatch.setattr(
            fn.__globals__["_ura_const"], "ZONE_OCCUPANCY_PER_ENTITY_ENABLED",
            False,
        )
    return per_entity_off


@pytest.fixture
def house():
    h = _House()
    yield h
    h.close()


def _substrate(house, *, motion=(ZV,), presence=(PANEL,)):
    entry = fake_room_entry(
        ROOM, **{CONF_MOTION_SENSORS: list(motion),
                 CONF_MMWAVE_SENSORS: list(presence)},
    )
    house.hass.config_entries.async_entries.return_value = [entry]
    sub = OccupancySubstrate(house.hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    house.hass.data[DOMAIN]["occupancy_substrate"] = sub
    edges: list = []
    sub.subscribe(lambda r, k, v: edges.append((r, k, v)))
    return sub, edges


def _seed_states(house):
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})


def _outage(house, room):
    """Panel `on`, its camera `unavailable` from T0; ticks at T0 and +120 s."""
    _seed_states(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))


# ---------------------------------------------------------------------------
# Zone tier: substrate (seed, live event, discharge) and the zone tracker
# ---------------------------------------------------------------------------


def test_zone_not_held_by_dead_stream_input(house):
    """Up Hallway shape at zone tier: the substrate's mmwave kind (the
    zone's Tier-1 view) drops at the first room tick past the grace, via
    the room tick's discharge, and returns when the camera streams again."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, edges = _substrate(house)
    assert sub.is_kind_active(ROOM, "mmwave") is True
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=119))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []
    room.tick(T0 + timedelta(seconds=120))
    assert room.camera_input_stream_dead(PANEL) is True
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]
    # Camera back: the next tick re-reads the kind -> on edge.
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=150))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges[-1] == (ROOM, "mmwave", True)


def test_zone_live_event_does_not_revive_dead_input(house):
    """A state event for the dead input (attribute-only on -> on) is read
    through the getter: the kind stays off (event branch of _kind_on_now)."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    assert sub.is_kind_active(ROOM, "mmwave") is True
    _outage(house, room)
    assert sub.is_kind_active(ROOM, "mmwave") is False
    sub._handle_state_change(SimpleNamespace(data={
        "entity_id": PANEL, "new_state": _st("on"),
    }))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]


def test_zone_sibling_dead_input_does_not_hold_kind(house):
    """Two presence inputs: the dead panel and a live radar that turns off.
    The off event of the radar must not leave the kind held by the frozen
    panel (sibling branch of _kind_on_now)."""
    radar = "binary_sensor.upstairs_hallway_zk_presence"
    room = _RoomCoord(house, _registry(), presence=(PANEL, radar))
    _seed_states(house)
    house.set(**{radar: "on"})
    sub, _edges = _substrate(house, presence=(PANEL, radar))
    _outage(house, room)
    assert sub.is_kind_active(ROOM, "mmwave") is True  # radar holds it
    house.set(**{radar: "off"})
    sub._handle_state_change(SimpleNamespace(data={
        "entity_id": radar, "new_state": _st("off"),
    }))
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_zone_seed_honours_dead_stream(house):
    """A substrate refresh / re-seed after the input went dead seeds the
    kind off (seed path shares _kind_on_now)."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, _edges = _substrate(house)
    _outage(house, room)
    sub._raw_state[ROOM]["mmwave"] = True  # isolate the seed from the discharge
    sub._reset_and_seed_room_bucket(ROOM, {}, sub._entity_to_room_kind)
    assert sub.is_kind_active(ROOM, "mmwave") is False
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=150))
    sub._reset_and_seed_room_bucket(ROOM, {}, sub._entity_to_room_kind)
    assert sub.is_kind_active(ROOM, "mmwave") is True


def test_zone_switch_off_paths_honour_dead_stream(house, switch_off):
    """ZONE_OCCUPANCY_PER_ENTITY_ENABLED False (last-writer): the discharge
    and the live event both read the getter."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, edges = _substrate(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]
    sub._handle_state_change(SimpleNamespace(data={
        "entity_id": PANEL, "new_state": _st("on"),
    }))
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_room_tick_notifies_substrate_on_flip_only(house):
    """Wire-in anchor for the discharge call inside
    _apply_camera_stream_health_tick: once when the input turns dead, never
    on a steady dead tick, once when it comes back."""
    calls: list = []
    house.hass.data[DOMAIN]["occupancy_substrate"] = SimpleNamespace(
        recheck_entities=lambda eids: calls.append(list(eids)),
    )
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=119))
    assert calls == []
    room.tick(T0 + timedelta(seconds=120))
    assert calls == [[PANEL]]
    room.tick(T0 + timedelta(seconds=150))
    assert calls == [[PANEL]]
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=180))
    assert calls == [[PANEL], [PANEL]]


def test_restart_blip_not_dead_at_zone(house):
    """Camera `unavailable` 60 s (restart blip) then `streaming`: the zone
    kind never drops and no discharge fires."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, edges = _substrate(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=60))
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=90))
    room.tick(T0 + timedelta(seconds=300))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []


def test_restart_rebuilds_from_first_tick(house):
    """After an HA restart the tracker is fresh (RAM only): the zone counts
    the frozen input until the new room tick has seen the camera
    unavailable for the grace, then drops it (grace counted again)."""
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, _edges = _substrate(house)
    room = _RoomCoord(house, _registry())  # fresh process
    assert room.camera_input_stream_dead(PANEL) is None
    assert sub.is_kind_active(ROOM, "mmwave") is True
    room.tick(T0 + timedelta(hours=5))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    room.tick(T0 + timedelta(hours=5, seconds=120))
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_unresolved_and_kill_switch_byte_identical_at_zone(house, monkeypatch):
    """No camera on the panel's device (unresolved) -> the zone kind stays
    on for hours; same with the kill switch False and a resolved camera."""
    room = _RoomCoord(house, _registry(panel_has_camera=False))
    house.set(**{PANEL: "on", ZV: "off"})
    sub, edges = _substrate(house)
    for s in (0, 120, 3600):
        room.tick(T0 + timedelta(seconds=s))
    assert room.camera_input_stream_dead(PANEL) is None
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []

    house2 = _House()
    try:
        monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", False)
        room2 = _RoomCoord(house2, _registry())
        house2.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
        sub2, edges2 = _substrate(house2)
        for s in (0, 120, 3600):
            room2.tick(T0 + timedelta(seconds=s))
        assert room2.camera_input_stream_dead(PANEL) is False
        assert sub2.is_kind_active(ROOM, "mmwave") is True
        assert edges2 == []
    finally:
        house2.close()


def test_zone_camera_tier_ignores_dead_stream(house):
    """Zone camera tier (Tier 2): a frozen detection of a dead-stream
    camera entity does not hold the zone."""
    room = _RoomCoord(house, _registry())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is True
    room.tick(T0 + timedelta(seconds=120))
    assert tracker._any_camera_occupied() is False


def test_night_raw_switch_off_limb_ignores_dead_input(house, switch_off):
    """_zone_night_raw (switch-off live limb): a dead-stream input reading
    `on` does not make a SLEEP zone 'really occupied'."""
    room = _RoomCoord(house, _registry())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    tracker._has_sensors = True
    tracker._entity_to_room[PANEL] = ROOM
    fake = SimpleNamespace(hass=house.hass)
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    assert PresenceCoordinator._zone_night_rooms(fake, tracker) == [ROOM]
    room.tick(T0 + timedelta(seconds=120))
    assert PresenceCoordinator._zone_night_rooms(fake, tracker) == []


# ---------------------------------------------------------------------------
# Fan readers
# ---------------------------------------------------------------------------


def test_presence_radar_sole_gate_ignores_dead_input(house):
    """Presence fan-interference gate (_room_radar_sole_capable): the dead
    panel (presence list = radar-bearing kind) no longer makes the room
    radar-sole."""
    room = _RoomCoord(house, _registry())
    house.hass.config_entries.async_entries.return_value = [fake_room_entry(
        ROOM, **{CONF_MOTION_SENSORS: [ZV], CONF_MMWAVE_SENSORS: [PANEL]},
    )]
    fake = SimpleNamespace(hass=house.hass)
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    assert PresenceCoordinator._room_radar_sole_capable(fake, ROOM) is True
    room.tick(T0 + timedelta(seconds=120))
    assert PresenceCoordinator._room_radar_sole_capable(fake, ROOM) is False


def test_fan_veto_motion_ignores_dead_stream_input(house):
    """Comfort-fan AWAY veto, motion leg: a camera-derived motion input
    whose stream is dead is not trusted presence."""
    motion = "binary_sensor.up_hallway_panel_motion"
    reg = _registry()
    reg._by_id[motion] = _entry(motion, "dev_panel")
    room = _RoomCoord(house, reg, motion=(motion,), presence=())
    config = {CONF_MOTION_SENSORS: [motion], CONF_ROOM_NAME: ROOM}
    house.set(**{motion: "on", PANEL_CAM: "unavailable"})
    room.tick(T0)
    assert fan_veto._has_recent_motion(house.hass, config) is True
    room.tick(T0 + timedelta(seconds=120))
    assert fan_veto._has_recent_motion(house.hass, config) is False


def test_fan_veto_camera_leg_ignores_dead_stream(house):
    """Comfort-fan AWAY veto, legacy camera-person leg (allowlist room)."""
    room = _RoomCoord(house, _registry())
    config = {CONF_CAMERA_PERSON_ENTITIES: [PANEL]}
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    assert fan_veto._has_camera_person(house.hass, "Study A", config) is True
    room.tick(T0 + timedelta(seconds=120))
    assert fan_veto._has_camera_person(house.hass, "Study A", config) is False


def test_fan_recheck_ignores_dead_stream_input(house):
    """Fan pause-recheck VACATED read (any_radar_bearing_on_now) is the room
    tier's fusion-filtered on-set: a dead-stream panel is not 'radar on',
    so the verdict is VACATED, not OCCUPIED_CONFIRMED."""
    room = _RoomCoord(house, _registry())
    room.entry.data.update({CONF_MOTION_SENSORS: [ZV], CONF_MMWAVE_SENSORS: [PANEL]})
    for name in (
        "any_radar_bearing_on_now", "_live_on_set", "_fusion_filter_active",
        "is_radar",
    ):
        fn = getattr(UniversalRoomCoordinator, name)
        setattr(room, name, fn.__get__(room, type(room)))
    room._get_config = lambda key, default=None: room.entry.data.get(key, default)
    room._is_sensor_on = lambda eid: (
        house.states.get(eid) is not None and house.states[eid].state == "on"
    )
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    assert room.any_radar_bearing_on_now() is True
    room.tick(T0 + timedelta(seconds=120))
    assert room.any_radar_bearing_on_now() is False


# ---------------------------------------------------------------------------
# Census
# ---------------------------------------------------------------------------


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


PROTECT = "binary_sensor.kitchen_person_detected"


def _census(house, cameras):
    integ = MagicMock()
    integ.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    integ.options = {
        CONF_CAMERA_PERSON_ENTITIES: list(cameras),
        ura_const.CONF_ENHANCED_CENSUS: True,
    }
    house.hass.config_entries.async_entries.return_value = [integ]
    return PersonCensus(house.hass, _Mgr(cameras))  # type: ignore[arg-type]


def _house_census(census):
    return _run(
        census._calculate_house_census(ble_persons=[], now=T0),
    )


def _panel_cameras():
    return {
        PANEL: CameraInfo(
            entity_id=PANEL, platform=ura_const.CAMERA_PLATFORM_FRIGATE,
            area_id="upstairs_hallway", person_binary_sensor=PANEL,
            person_count_sensor=PANEL_COUNT,
        ),
        PROTECT: CameraInfo(
            entity_id=PROTECT, platform="unifiprotect", area_id="kitchen",
            person_binary_sensor=PROTECT,
        ),
    }


def test_census_dead_stream_is_missing_not_zero(house):
    """Frozen panel count 1 + a live Protect camera seeing nobody. Live
    stream: Frigate counts 1 (both platforms). Dead stream: the panel is a
    MISSING term: Frigate is not available at all (degraded, single source,
    Protect is the source), which a zero count would not produce
    (a zero would read frigate_count 0, degraded False)."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 PROTECT: "off", ZV: "off"})
    census = _census(house, _panel_cameras())
    room.tick(T0)
    live = _house_census(census)
    assert live.frigate_count == 1
    assert live.degraded_mode is False
    room.tick(T0 + timedelta(seconds=120))
    dead = _house_census(census)
    assert dead.frigate_count == 0
    assert dead.degraded_mode is True
    assert dead.source_agreement == ura_const.CENSUS_AGREEMENT_SINGLE


def test_census_cross_validation_off_skips_dead_stream(house, monkeypatch):
    """Cross-validation disabled path: the dead panel adds nothing."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 PROTECT: "off", ZV: "off"})
    census = _census(house, _panel_cameras())
    monkeypatch.setattr(census, "_is_cross_validation_enabled", lambda: False)
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: _registry(), raising=False)
    room.tick(T0)
    assert _house_census(census).frigate_count == 1
    room.tick(T0 + timedelta(seconds=120))
    assert _house_census(census).frigate_count == 0


def test_census_unrecognized_count_skips_dead_stream(house):
    """Guest path (_get_unrecognized_camera_count): a frozen unrecognised
    body on a dead-stream camera is not counted."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 PROTECT: "off", ZV: "off"})
    census = _census(house, _panel_cameras())
    room.tick(T0)
    assert census._get_unrecognized_camera_count() == 1
    room.tick(T0 + timedelta(seconds=120))
    assert census._get_unrecognized_camera_count() == 0


def test_census_own_camera_route_for_non_input_entity(house, monkeypatch):
    """A census person sensor that is not a room input resolves through its
    own camera (registry, same S1 resolver) to the camera-keyed getter."""
    other_person = "binary_sensor.up_hallway_panel_person_occupancy_2"
    reg = _registry()
    reg._by_id[other_person] = _entry(other_person, "dev_panel")
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: reg, raising=False)
    room = _RoomCoord(house, reg)
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    assert csh.entity_stream_dead(house.hass, other_person) is False
    room.tick(T0 + timedelta(seconds=120))
    assert csh.entity_stream_dead(house.hass, other_person) is True


# ---------------------------------------------------------------------------
# Camera-keyed getter + single-getter proof
# ---------------------------------------------------------------------------


def test_camera_keyed_getter(house, monkeypatch):
    """camera_stream_dead: None before any tick / for an unwatched camera /
    for a non-entity key; False while live; True once confirmed dead;
    a restored placeholder is never dead; kill switch -> False."""
    room = _RoomCoord(house, _registry())
    assert csh.camera_stream_dead(house.hass, PANEL_CAM) is None
    house.set(**{PANEL: "on", PANEL_CAM: "streaming", ZV: "off"})
    room.tick(T0)
    assert csh.camera_stream_dead(house.hass, PANEL_CAM) is False
    assert csh.camera_stream_dead(house.hass, OTHER_CAM) is None
    assert csh.camera_stream_dead(house.hass, "up_hallway_panel") is None
    house.set(**{PANEL_CAM: _st("unavailable", restored=True)})
    room.tick(T0 + timedelta(seconds=10))
    room.tick(T0 + timedelta(seconds=600))
    assert csh.camera_stream_dead(house.hass, PANEL_CAM) is False
    house.set(**{PANEL_CAM: "unavailable"})
    room.tick(T0 + timedelta(seconds=700))
    room.tick(T0 + timedelta(seconds=819))
    assert csh.camera_stream_dead(house.hass, PANEL_CAM) is False
    room.tick(T0 + timedelta(seconds=820))
    assert csh.camera_stream_dead(house.hass, PANEL_CAM) is True
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", False)
    room.tick(T0 + timedelta(seconds=900))
    assert csh.camera_stream_dead(house.hass, PANEL_CAM) is False


def test_house_fold_any_true_wins():
    """Two rooms answer: True beats False beats None; non-bools ignored."""
    assert csh._fold([None, False, True]) is True
    assert csh._fold([None, False]) is False
    assert csh._fold([None, MagicMock()]) is None


class _ForcedRoom:
    """A room whose ONE getter answers ``answer`` regardless of states."""

    def __init__(self, answer):
        self._camera_stream_health = object()
        self._answer = answer

    def camera_input_stream_dead(self, eid):
        return self._answer if eid == PANEL else None

    def camera_stream_dead(self, cam):
        return self._answer if cam == PANEL_CAM else None


@pytest.mark.parametrize("forced", [True, False])
def test_stream_dead_single_getter(house, forced):
    """INV-STREAM-ONE-GETTER, behavioural: every S2 reader follows the room
    getter and nothing else. Forced True with the camera STREAMING -> all
    readers drop the panel; forced False with the camera UNAVAILABLE for an
    hour -> all readers count it (no second liveness rule anywhere)."""
    house.hass.data[DOMAIN]["entry_room"] = _ForcedRoom(forced)
    cam_state = "streaming" if forced else "unavailable"
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: cam_state,
                 PROTECT: "off", ZV: "off"})
    counts = not forced
    # zone substrate
    sub, _e = _substrate(house)
    assert sub.is_kind_active(ROOM, "mmwave") is counts
    # zone camera tier
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is counts
    # presence fan-interference gate
    house.hass.config_entries.async_entries.return_value = [fake_room_entry(
        ROOM, **{CONF_MOTION_SENSORS: [ZV], CONF_MMWAVE_SENSORS: [PANEL]},
    )]
    fake = SimpleNamespace(hass=house.hass)
    assert PresenceCoordinator._room_radar_sole_capable(fake, ROOM) is counts
    # fan veto camera leg
    assert fan_veto._has_camera_person(
        house.hass, "Study A", {CONF_CAMERA_PERSON_ENTITIES: [PANEL]},
    ) is counts
    # census
    census = _census(house, _panel_cameras())
    assert (_house_census(census).frigate_count == 1) is counts

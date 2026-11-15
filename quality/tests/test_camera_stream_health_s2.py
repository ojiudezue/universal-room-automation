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
from homeassistant.util import dt as dt_util

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
        self._camera_stream_prev_expired = frozenset()
        self._camera_stream_rechecking = False
        for name in (
            "_apply_camera_stream_health_tick", "_notify_substrate_stream_flips",
            "camera_input_stream_dead", "camera_stream_dead",
            "camera_input_stream_hold_expired", "camera_stream_hold_expired",
            "_camera_override_person_sensors", "_substrate_edge_wants_refresh",
            "_fire_camera_hold_pages", "camera_input_stream_unavailable_held",
            "camera_input_room_quarantined", "_camera_stream_page_policy",
            "_camera_stream_page_key",
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
# Zone tier: substrate (seed, live event, discharge) and the zone tracker.
# Operator ruling 2026-11-14 (review B-M2): "A dead input holds instead of
# releasing. A dead camera is not a presence or absence of signal. Its faulty
# equipment." A dead input is UNKNOWN at the zone tier: it neither creates
# nor ends occupancy; the level holds until a LIVE input of the room goes
# on -> off, the camera streams again, or 15 min (900 s, literal below) pass
# from the camera's first `unavailable` reading.
# ---------------------------------------------------------------------------

HOLD_END = 900  # zone cap, seconds from T0 (the first `unavailable` tick)
CENSUS_HOLD_END = 900  # census cap (operator: both 15 min), same origin; literal


def _ev(eid, new, old=None):
    """A state_changed event payload (old state optional)."""
    data = {"entity_id": eid, "new_state": _st(new) if new is not None else None}
    if old is not None:
        data["old_state"] = _st(old)
    return SimpleNamespace(data=data)


def test_zone_dead_input_holds_prior_level(house):
    """Up Hallway shape: the panel's frozen `on` held the mmwave kind before
    the outage; once dead (grace 120 s) it is unknown and the kind KEEPS its
    level: no edge at the flip. Camera back: still on, still no edge."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, edges = _substrate(house)
    assert sub.is_kind_active(ROOM, "mmwave") is True
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    assert room.camera_input_stream_dead(PANEL) is True
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=150))
    assert room.camera_input_stream_dead(PANEL) is False
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []


def test_zone_dead_input_does_not_create(house):
    """The kind was off when the panel died: a dead input's `on` event (or
    the discharge) cannot turn it on (event branch of _kind_on_now)."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "off", PANEL_CAM: "unavailable", ZV: "off"})
    sub, edges = _substrate(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    assert room.camera_input_stream_dead(PANEL) is True
    house.set(**{PANEL: "on"})
    sub._handle_state_change(_ev(PANEL, "on", old="off"))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    sub.recheck_entities([PANEL])
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == []


def test_zone_dead_input_event_does_not_end(house):
    """A dead input's own off event does not end the hold (no absence
    signal from faulty equipment)."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    _outage(house, room)
    house.set(**{PANEL: "off"})
    sub._handle_state_change(_ev(PANEL, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []


@pytest.mark.per_entity_on_only
def test_zone_sibling_dead_input_holds_until_live_end(house):
    """Two presence inputs (same kind): the dead panel and a live radar.
    The radar going on -> off is a live end: the hold releases. A dead
    sibling alone keeps the kind (sibling branch of _kind_on_now)."""
    radar = "binary_sensor.upstairs_hallway_zk_presence"
    room = _RoomCoord(house, _registry(), presence=(PANEL, radar))
    _seed_states(house)
    house.set(**{radar: "off"})
    sub, edges = _substrate(house, presence=(PANEL, radar))
    _outage(house, room)
    # an unrelated attribute-only event of the live radar (off -> off)
    sub._handle_state_change(_ev(radar, "off", old="off"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    # a live radar unavailable is not an end either
    sub._handle_state_change(_ev(radar, "unavailable", old="off"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    house.set(**{radar: "on"})
    sub._handle_state_change(_ev(radar, "on", old="unavailable"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    # on -> unavailable (a live radar losing its signal) is not an end
    house.set(**{radar: "unavailable"})
    sub._handle_state_change(_ev(radar, "unavailable", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []
    sub._handle_state_change(_ev(radar, "on", old="unavailable"))
    house.set(**{radar: "off"})
    sub._handle_state_change(_ev(radar, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]


def test_zone_live_end_of_other_kind_releases_hold(house):
    """The panel (mmwave kind) is held; the live ZV (motion kind) going
    on -> off is a live end in the room and releases the mmwave hold."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    _outage(house, room)
    house.set(**{ZV: "on"})
    sub._handle_state_change(_ev(ZV, "on", old="off"))
    assert edges == [(ROOM, "motion", True)]
    house.set(**{ZV: "off"})
    sub._handle_state_change(_ev(ZV, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert sorted(edges[1:]) == [(ROOM, "mmwave", False), (ROOM, "motion", False)]
    assert sub.last_edge_entity_for(ROOM) == ZV


@pytest.mark.per_entity_on_only
def test_zone_live_end_release_names_its_cause(house):
    """The release edge names the live input that ended the hold, also when
    that input's own kind does not move (a second motion sensor holds it)."""
    m2 = "binary_sensor.upstairs_hallway_pir"
    room = _RoomCoord(house, _registry(), motion=(ZV, m2))
    _seed_states(house)
    house.set(**{m2: "on", ZV: "on"})
    sub, edges = _substrate(house, motion=(ZV, m2))
    _outage(house, room)
    house.set(**{ZV: "off"})
    sub._handle_state_change(_ev(ZV, "off", old="on"))
    assert edges == [(ROOM, "mmwave", False)]
    assert sub.is_kind_active(ROOM, "motion") is True
    assert sub.last_edge_entity_for(ROOM) == ZV


def test_zone_live_end_without_dead_input_touches_no_other_kind(house):
    """No camera dead: a ZV on -> off moves only its own kind (the release
    walk is a no-op; byte-identical)."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "streaming", ZV: "on"})
    sub, edges = _substrate(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=600))
    house.set(**{ZV: "off"})
    sub._handle_state_change(_ev(ZV, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == [(ROOM, "motion", False)]


def test_zone_hold_failsafe_releases_at_cap(house):
    """The hold ends 900 s after the camera's first `unavailable` tick:
    held at 899 s, released (off edge, via the room tick's discharge) at
    900 s."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    _outage(house, room)
    room.tick(T0 + timedelta(seconds=HOLD_END - 1))
    assert room.camera_input_stream_hold_expired(PANEL) is False
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert room.camera_input_stream_hold_expired(PANEL) is True
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]
    # released: the frozen `on` no longer counts on a later read either
    sub._handle_state_change(_ev(PANEL, "on", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_zone_hold_knob_zero_releases_at_once(house, monkeypatch):
    """CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S = 0: no hold, the dead input
    counts as off from the grace (the pre-ruling S2 behaviour)."""
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S", 0.0)
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    _outage(house, room)
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]


def test_zone_seed_honours_hold(house):
    """A substrate re-seed keeps a held kind's level (prior) and never
    creates it; after the hold ends the seed reads it off."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, _edges = _substrate(house)
    _outage(house, room)
    sub._reset_and_seed_room_bucket(ROOM, {}, sub._entity_to_room_kind)
    assert sub.is_kind_active(ROOM, "mmwave") is True
    sub._raw_state[ROOM]["mmwave"] = False
    sub._reset_and_seed_room_bucket(ROOM, {}, sub._entity_to_room_kind)
    assert sub.is_kind_active(ROOM, "mmwave") is False
    sub._raw_state[ROOM]["mmwave"] = True
    room.tick(T0 + timedelta(seconds=HOLD_END))
    sub._raw_state[ROOM]["mmwave"] = True  # isolate the seed from the discharge
    sub._reset_and_seed_room_bucket(ROOM, {}, sub._entity_to_room_kind)
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_zone_switch_off_paths_hold(house, switch_off):
    """ZONE_OCCUPANCY_PER_ENTITY_ENABLED False (last-writer): the discharge
    and the dead input's own events hold; a live ZV on -> off releases; the
    cap end releases."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    _outage(house, room)
    assert sub.is_kind_active(ROOM, "mmwave") is True
    sub._handle_state_change(_ev(PANEL, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    house.set(**{PANEL: "on"})
    room.tick(T0 + timedelta(seconds=HOLD_END - 1))
    sub.recheck_entities([PANEL])
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]


def test_zone_switch_off_live_end_releases(house, switch_off):
    """Switch off: the live ZV going on -> off releases the panel's hold."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    _outage(house, room)
    house.set(**{ZV: "on"})
    sub._handle_state_change(_ev(ZV, "on", old="off"))
    house.set(**{ZV: "off"})
    sub._handle_state_change(_ev(ZV, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert (ROOM, "mmwave", False) in edges


def test_room_tick_notifies_substrate_on_flip_only(house):
    """Wire-in anchor for the discharge call inside
    _apply_camera_stream_health_tick: once when the input turns dead, never
    on a steady dead tick, once when its hold ends, once when it comes back."""
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
    room.tick(T0 + timedelta(seconds=HOLD_END - 1))
    assert calls == [[PANEL]]
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert calls == [[PANEL], [PANEL]]
    room.tick(T0 + timedelta(seconds=HOLD_END + 30))
    assert calls == [[PANEL], [PANEL]]
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=HOLD_END + 60))
    assert calls == [[PANEL], [PANEL], [PANEL]]


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
    the frozen input, holds it once the new tick has seen the camera dead,
    and the cap clock restarts from the new first `unavailable` tick."""
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, edges = _substrate(house)
    room = _RoomCoord(house, _registry())  # fresh process
    assert room.camera_input_stream_dead(PANEL) is None
    t1 = T0 + timedelta(hours=5)
    room.tick(t1)
    room.tick(t1 + timedelta(seconds=120))
    assert room.camera_input_stream_dead(PANEL) is True
    assert sub.is_kind_active(ROOM, "mmwave") is True
    room.tick(t1 + timedelta(seconds=HOLD_END - 1))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    room.tick(t1 + timedelta(seconds=HOLD_END))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]


def test_unresolved_and_kill_switch_byte_identical_at_zone(house, monkeypatch):
    """No camera on the panel's device (unresolved) -> the zone kind stays
    on for hours; same with the kill switch False and a resolved camera."""
    room = _RoomCoord(house, _registry(panel_has_camera=False))
    house.set(**{PANEL: "on", ZV: "off"})
    sub, edges = _substrate(house)
    for s in (0, 120, 3600, HOLD_END + 60):
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
        for s in (0, 120, 3600, HOLD_END + 60):
            room2.tick(T0 + timedelta(seconds=s))
        assert room2.camera_input_stream_dead(PANEL) is False
        assert sub2.is_kind_active(ROOM, "mmwave") is True
        assert edges2 == []
    finally:
        house2.close()


class _CountingRoom:
    """A room whose getters count their calls (B-L3 ordering)."""

    def __init__(self):
        self._camera_stream_health = object()
        self.calls = 0

    def camera_input_stream_dead(self, eid):
        self.calls += 1
        return None

    def camera_stream_dead(self, cam):
        self.calls += 1
        return None

    def camera_input_stream_hold_expired(self, eid, census=False):
        self.calls += 1
        return None

    def camera_stream_hold_expired(self, cam, census=False):
        self.calls += 1
        return None


def test_zone_camera_tier_holds_dead_stream(house):
    """Zone camera tier (Tier 2): a frozen detection of a dead-stream camera
    keeps holding (unknown) until the 900 s cap, then counts as off."""
    room = _RoomCoord(house, _registry())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is True
    room.tick(T0 + timedelta(seconds=120))
    assert tracker._any_camera_occupied() is True
    room.tick(T0 + timedelta(seconds=HOLD_END - 1))
    assert tracker._any_camera_occupied() is True
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert tracker._any_camera_occupied() is False


def test_zone_camera_tier_dead_camera_does_not_create(house):
    """A camera that was NOT holding when first seen dead cannot start
    holding while dead (a detection arriving while dead is ignored); once
    it streams again its reading counts."""
    room = _RoomCoord(house, _registry())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    house.set(**{PANEL: "off", PANEL_CAM: "unavailable", ZV: "off"})
    tracker.update_camera_detection(PANEL, False)
    tracker._camera_last_seen[PANEL] = dt_util.utcnow() - timedelta(days=1)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    assert tracker._any_camera_occupied() is False  # first seen dead: idle
    house.set(**{PANEL: "on"})  # its sensor turns on while the stream is dead
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is False
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=150))
    assert tracker._any_camera_occupied() is True
    assert PANEL not in tracker._camera_stream_ignored


def test_zone_camera_tier_ignored_without_prior_detection_resyncs(house):
    """A camera never seen detecting gets an `on` while its stream is dead
    (ignored); when it streams again with the sensor still `on`, the read
    resyncs it from its live state."""
    room = _RoomCoord(house, _registry())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    house.set(**{PANEL: "off", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    house.set(**{PANEL: "on"})
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is False
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=150))
    assert tracker._any_camera_occupied() is True


def test_zone_camera_tier_dead_camera_does_not_end(house):
    """A frozen detection's own `off` update while the stream is dead is
    ignored (no absence signal); after recovery the live reading decides."""
    room = _RoomCoord(house, _registry())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    tracker.update_camera_detection(PANEL, True)
    tracker._camera_last_seen[PANEL] = dt_util.utcnow() - timedelta(days=1)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    house.set(**{PANEL: "off"})
    tracker.update_camera_detection(PANEL, False)
    assert tracker._any_camera_occupied() is True
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=150))
    assert tracker._any_camera_occupied() is False


def test_zone_camera_tier_asks_getter_only_for_a_holder(house):
    """Review B-L3: a camera that would not hold (idle, past its timeout)
    costs no getter call; a holding one does."""
    counting = _CountingRoom()
    house.hass.data[DOMAIN]["entry_count"] = counting
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    tracker.update_camera_detection(PANEL, False)
    tracker._camera_last_seen[PANEL] = dt_util.utcnow() - timedelta(days=1)
    assert tracker._any_camera_occupied() is False
    assert counting.calls == 0
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is True
    assert counting.calls > 0


def test_zone_camera_tier_camera_entity_key(house):
    """Review C-3: a zone camera key that IS a `camera.*` entity id routes
    through the camera-keyed getter (end to end)."""
    room = _RoomCoord(house, _registry())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    room.tick(T0)
    tracker.update_camera_detection(PANEL_CAM, True)
    room.tick(T0 + timedelta(seconds=120))
    assert csh.entity_stream_dead(house.hass, PANEL_CAM) is True
    assert csh.entity_stream_view(house.hass, PANEL_CAM) == csh.VIEW_HELD
    assert tracker._any_camera_occupied() is True
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert csh.entity_stream_view(house.hass, PANEL_CAM) == csh.VIEW_RELEASED
    assert tracker._any_camera_occupied() is False


def test_night_raw_switch_off_limb_holds_dead_input(house, switch_off):
    """_zone_night_raw (switch-off live limb): a dead-stream input reading
    `on` keeps a SLEEP zone 'really occupied' while held, not after the cap."""
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
    assert PresenceCoordinator._zone_night_rooms(fake, tracker) == [ROOM]
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert PresenceCoordinator._zone_night_rooms(fake, tracker) == []


# ---------------------------------------------------------------------------
# Reviewer B-M2 repro, end to end: house asleep, a phone-less guest, the
# camera input the only `on` input of its zone, the camera dies.
# ---------------------------------------------------------------------------


def _zone_stack(house, *, motion=(ZV,), presence=(PANEL,)):
    """REAL substrate feeding a REAL zone tracker (subscribed before the
    boot-settle release, as presence wires it)."""
    entry = fake_room_entry(
        ROOM, **{CONF_MOTION_SENSORS: list(motion),
                 CONF_MMWAVE_SENSORS: list(presence)},
    )
    house.hass.config_entries.async_entries.return_value = [entry]
    sub = OccupancySubstrate(house.hass)
    _run(sub.async_setup())
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    tracker._has_sensors = True
    sub.subscribe(lambda r, k, v: tracker.update_room_occupancy(r, v, kind=k))
    sub.release_boot_settle()
    house.hass.data[DOMAIN]["occupancy_substrate"] = sub
    return sub, tracker


def _sleep_infer(house, tracker):
    from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E501
        HouseState,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
        StateInferenceEngine,
    )
    fake = SimpleNamespace(hass=house.hass)
    night_raw = bool(PresenceCoordinator._zone_night_rooms(fake, tracker))
    engine = StateInferenceEngine(sleep_start_hour=22, sleep_end_hour=6)
    return engine.infer(
        census_count=0,  # phone-less guest: no BLE, not on a census camera
        current_state=HouseState.SLEEP,
        any_zone_occupied=False,  # SLEEP-pinned zone (mask)
        now=datetime(2026, 11, 12, 2, 0, 0),
        any_zone_occupied_for_empty=night_raw,
    ), HouseState


def test_repro_sleep_guest_camera_dies_no_away(house):
    """Camera dies: the zone stays held, nobody-home does not fire. A live
    input (ZV) going on -> off then releases it and nobody-home fires."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "streaming", ZV: "off"})
    sub, tracker = _zone_stack(house)
    tracker.set_sleep(True)
    room.tick(T0)
    house.set(**{PANEL_CAM: "unavailable"})
    room.tick(T0 + timedelta(seconds=30))
    room.tick(T0 + timedelta(seconds=150))
    assert room.camera_input_stream_dead(PANEL) is True
    proposed, HouseState = _sleep_infer(house, tracker)
    assert proposed != HouseState.AWAY
    house.set(**{ZV: "on"})
    sub._handle_state_change(_ev(ZV, "on", old="off"))
    house.set(**{ZV: "off"})
    sub._handle_state_change(_ev(ZV, "off", old="on"))
    proposed, HouseState = _sleep_infer(house, tracker)
    assert proposed == HouseState.AWAY


def test_repro_sleep_guest_failsafe_releases_at_cap(house):
    """Same repro, no live input ever ends it: AWAY only once the hold ends
    (900 s after the camera's first `unavailable` tick), not at the cap - 1 s."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, tracker = _zone_stack(house)
    tracker.set_sleep(True)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    room.tick(T0 + timedelta(seconds=HOLD_END - 1))
    proposed, HouseState = _sleep_infer(house, tracker)
    assert proposed != HouseState.AWAY
    room.tick(T0 + timedelta(seconds=HOLD_END))
    proposed, HouseState = _sleep_infer(house, tracker)
    assert proposed == HouseState.AWAY


def test_real_departure_away_not_slowed_by_hold(house):
    """A real departure (every tracked resident away, no unidentified body,
    no face) goes AWAY through path alpha on the SAME tick whether or not a
    dead camera holds the zone: alpha never reads zone occupancy."""
    from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E501
        HouseState,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
        StateInferenceEngine,
    )
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, tracker = _zone_stack(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    assert tracker.mode == "occupied"  # held by the dead panel
    noon = datetime(2026, 11, 12, 12, 0, 0)
    out = {}
    for held in (True, False):
        engine = StateInferenceEngine()
        out[held] = (engine.infer(
            census_count=0, current_state=HouseState.HOME_DAY,
            any_zone_occupied=held, now=noon, unidentified_count=0,
            all_tracked_persons_away=True, face_recognized_count=0,
        ), engine._veto_path)
    assert out[True][0] == HouseState.AWAY
    assert out[False][0] == HouseState.AWAY
    assert out[True][1] == "active"


# ---------------------------------------------------------------------------
# recheck_entities guards (review C-4, B-L4) and the room tick discharge
# ---------------------------------------------------------------------------


def test_recheck_guards(house):
    """Unmapped entities are skipped (the rest of the batch still runs); an
    unchanged kind is not re-dispatched; the edge names its entity; before
    the boot-settle release nothing is dispatched; after teardown it is a
    no-op."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    _outage(house, room)
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert edges == [(ROOM, "mmwave", False)]
    house.set(**{PANEL_CAM: "streaming"})
    room._camera_stream_health.evaluate(
        T0 + timedelta(seconds=HOLD_END + 30), [ZV, PANEL],
        house.hass.states.get, lambda: room.registry,
    )
    sub.recheck_entities(["binary_sensor.not_mapped", PANEL])
    assert edges[-1] == (ROOM, "mmwave", True)
    assert sub.last_edge_entity_for(ROOM) == PANEL
    sub.recheck_entities([PANEL])
    assert edges == [(ROOM, "mmwave", False), (ROOM, "mmwave", True)]
    # boot-settle gate: a fresh, unreleased substrate updates silently
    sub2 = OccupancySubstrate(house.hass)
    _run(sub2.async_setup())
    edges2: list = []
    sub2.subscribe(lambda r, k, v: edges2.append((r, k, v)))
    sub2._raw_state[ROOM]["mmwave"] = False
    sub2.recheck_entities([PANEL])
    assert sub2.is_kind_active(ROOM, "mmwave") is True
    assert edges2 == []
    # torn down: no-op
    _run(sub.async_teardown())
    sub._raw_state[ROOM]["mmwave"] = False
    sub.recheck_entities([PANEL])
    assert sub._raw_state[ROOM]["mmwave"] is False


def test_stream_recheck_marks_own_room_edges(house):
    """Review B-L1: while the room tick runs its substrate recheck, the
    room's own substrate edges ask for no second refresh; outside it they
    do; the flag is cleared even when the recheck raises."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, _edges = _substrate(house)
    seen: list = []
    sub.subscribe(lambda r, k, v: seen.append(room._substrate_edge_wants_refresh()))
    _outage(house, room)
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert seen == [False]
    assert room._substrate_edge_wants_refresh() is True

    def _boom(_eids):
        raise RuntimeError("substrate broke")

    house.hass.data[DOMAIN]["occupancy_substrate"] = SimpleNamespace(
        recheck_entities=_boom,
    )
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=HOLD_END + 30))  # must not raise
    assert room._substrate_edge_wants_refresh() is True


def test_room_substrate_handler_skips_own_recheck_edges(monkeypatch):
    """Wire-in anchor for the B-L1 guard inside the REAL first-refresh
    closure ``_on_substrate_kind_changed``: an own-room edge during the
    room's stream recheck spawns no refresh; outside it, it does."""
    from unittest.mock import AsyncMock, patch

    import homeassistant.helpers.frame as _frame

    from custom_components.universal_room_automation import coordinator as cmod
    from custom_components.universal_room_automation.domain_coordinators.signals import (  # noqa: E501
        SIGNAL_SUBSTRATE_KIND_CHANGED,
    )

    handlers: dict = {}

    def _connect(hass, signal, cb):
        handlers[signal] = cb
        return MagicMock()

    monkeypatch.setattr(cmod, "async_dispatcher_connect", _connect)
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    entry = MagicMock()
    entry.data = {"room_name": ROOM, CONF_ROOM_NAME: ROOM}
    entry.options = {}
    entry.entry_id = "E1"
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        c = UniversalRoomCoordinator(hass, entry)
    base = UniversalRoomCoordinator.__mro__[1]
    monkeypatch.setattr(base, "async_config_entry_first_refresh",
                        AsyncMock(return_value=None), raising=False)
    c._async_load_stuck_state = AsyncMock(return_value=None)
    c._update_signal_subscriptions = MagicMock()
    conf = {CONF_MOTION_SENSORS: [ZV], CONF_MMWAVE_SENSORS: [PANEL],
            CONF_ROOM_NAME: ROOM}
    c._get_config = lambda key, default=None: conf.get(key, default)
    _run(c.async_config_entry_first_refresh())
    handler = handlers[SIGNAL_SUBSTRATE_KIND_CHANGED]
    c.async_refresh = MagicMock(return_value=None)
    c._last_event_refresh = 0.0
    entry.async_create_background_task.reset_mock()
    c._camera_stream_rechecking = True
    handler(ROOM, "mmwave", False)
    assert entry.async_create_background_task.call_count == 0
    c._camera_stream_rechecking = False
    handler(ROOM, "mmwave", False)
    assert entry.async_create_background_task.call_count == 1


def test_source3_dead_zone_camera_confirms_nothing(house, monkeypatch):
    """Reviews A-M1 / B-M1: check_zone_occupancy_confidence Source 3 (HVAC
    D6 stale-occupancy failsafe input). A zone camera person sensor that is
    NOT a room input, frozen `on` with its camera dead, confirms nothing
    (own-camera route of the one getter), so D6 can release."""
    zone_cam = "binary_sensor.up_hallway_panel_person_occupancy_2"
    reg = _registry()
    reg._by_id[zone_cam] = _entry(zone_cam, "dev_panel")
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: reg, raising=False)
    room = _RoomCoord(house, reg)
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off",
                 zone_cam: "on"})
    house.hass.config_entries.async_entries.return_value = []
    fake = SimpleNamespace(hass=house.hass)
    zone = SimpleNamespace(rooms=[], zone_cameras=[zone_cam], room_conditions=[])
    room.tick(T0)
    assert PresenceCoordinator.check_zone_occupancy_confidence(fake, zone) == (1, 2)
    room.tick(T0 + timedelta(seconds=120))
    assert PresenceCoordinator.check_zone_occupancy_confidence(fake, zone) == (0, 2)


@pytest.mark.per_entity_on_only
def test_zone_hold_diagnosis_names_dead_holder(house, monkeypatch):
    """Review A-L2: the D4d `zone_hold_all_away` page names a dead-stream
    holder as such (display)."""
    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E501
        HouseState,
    )
    got: dict = {}

    async def _fire(hass, **kw):
        got.update(kw)

    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _fire)
    monkeypatch.setattr(_stuck_signal_nm, "stuck_signal_dispatch_ready", lambda hass: True)
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
    sub, tracker = _zone_stack(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    fake = SimpleNamespace(
        hass=house.hass, _zone_trackers={"Upstairs": tracker},
        _census_count=0, _substrate=sub,
        _zone_hold_all_away_since=dt_util.utcnow() - timedelta(days=1),
        _zone_hold_all_away_fired=False,
    )
    fake._zone_night_rooms = lambda t: PresenceCoordinator._zone_night_rooms(fake, t)
    PresenceCoordinator._check_zone_hold_all_away(
        fake, HouseState.HOME_DAY, True, 2, True,
    )
    for c in house.tasks:
        _run(c)
    house.tasks.clear()
    assert f"{PANEL} (camera stream dead, held)" in got["diagnosis"]


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


def test_census_dead_stream_holds_then_is_missing_not_zero(house):
    """Frozen panel count 1 + a live Protect camera seeing nobody. Live
    stream: Frigate counts 1 (both platforms). Dead stream, hold not over:
    unknown, the frozen count keeps counting (operator ruling: a camera
    dying cannot drop the census by itself). Hold over (900 s): the panel
    is a MISSING term: Frigate is not available at all (degraded, single
    source, Protect is the source), which a zero count would not produce
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
    held = _house_census(census)
    assert held.frigate_count == 1
    assert held.degraded_mode is False
    room.tick(T0 + timedelta(seconds=CENSUS_HOLD_END - 1))
    assert _house_census(census).frigate_count == 1
    room.tick(T0 + timedelta(seconds=CENSUS_HOLD_END))
    dead = _house_census(census)
    assert dead.frigate_count == 0
    assert dead.degraded_mode is True
    assert dead.source_agreement == ura_const.CENSUS_AGREEMENT_SINGLE


def test_census_cross_validation_off_skips_dead_stream(house, monkeypatch):
    """Cross-validation disabled path: the dead panel counts while held and
    adds nothing once its hold is over."""
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
    assert _house_census(census).frigate_count == 1
    room.tick(T0 + timedelta(seconds=CENSUS_HOLD_END))
    assert _house_census(census).frigate_count == 0


def test_census_unrecognized_count_skips_dead_stream(house):
    """Guest path (_get_unrecognized_camera_count): a frozen unrecognised
    body on a dead-stream camera counts while held, not after the hold."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 PROTECT: "off", ZV: "off"})
    census = _census(house, _panel_cameras())
    room.tick(T0)
    assert census._get_unrecognized_camera_count() == 1
    room.tick(T0 + timedelta(seconds=120))
    assert census._get_unrecognized_camera_count() == 1
    room.tick(T0 + timedelta(seconds=CENSUS_HOLD_END))
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
    """A room whose ONE getter answers ``answer`` (and its hold getter
    ``expired``) regardless of states."""

    def __init__(self, answer, expired=False):
        self._camera_stream_health = object()
        self._answer = answer
        self._expired = expired

    def camera_input_stream_dead(self, eid):
        return self._answer if eid == PANEL else None

    def camera_stream_dead(self, cam):
        return self._answer if cam == PANEL_CAM else None

    def camera_input_stream_hold_expired(self, eid, census=False):
        return (self._answer and self._expired) if eid == PANEL else None

    def camera_stream_hold_expired(self, cam, census=False):
        return (self._answer and self._expired) if cam == PANEL_CAM else None


@pytest.mark.parametrize(
    ("dead", "expired", "zone_seed", "camera_tier", "elsewhere", "census"),
    [
        # released (dead, hold over): every reader drops the panel
        (True, True, False, False, False, False),
        # held (dead, hold not over): unknown at the zone tier (a fresh
        # seed cannot create; a detection arriving while dead is ignored);
        # the census keeps its frozen count; the fan readers drop it
        (True, False, False, False, False, True),
        # live: every reader counts it
        (False, False, True, True, True, True),
    ],
)
def test_stream_dead_single_getter(
    house, dead, expired, zone_seed, camera_tier, elsewhere, census,
):
    """INV-STREAM-ONE-GETTER, behavioural: every S2 reader follows the room
    getters and nothing else. Forced dead with the camera STREAMING, or
    forced live with the camera UNAVAILABLE for an hour: the readers follow
    the getters (no second liveness rule anywhere)."""
    house.hass.data[DOMAIN]["entry_room"] = _ForcedRoom(dead, expired)
    cam_state = "streaming" if dead else "unavailable"
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: cam_state,
                 PROTECT: "off", ZV: "off"})
    # zone substrate (fresh seed: prior False)
    sub, _e = _substrate(house)
    assert sub.is_kind_active(ROOM, "mmwave") is zone_seed
    # zone camera tier
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is camera_tier
    # presence fan-interference gate
    house.hass.config_entries.async_entries.return_value = [fake_room_entry(
        ROOM, **{CONF_MOTION_SENSORS: [ZV], CONF_MMWAVE_SENSORS: [PANEL]},
    )]
    fake = SimpleNamespace(hass=house.hass)
    assert PresenceCoordinator._room_radar_sole_capable(fake, ROOM) is elsewhere
    # fan veto camera leg
    assert fan_veto._has_camera_person(
        house.hass, "Study A", {CONF_CAMERA_PERSON_ENTITIES: [PANEL]},
    ) is elsewhere
    # census
    cen = _census(house, _panel_cameras())
    assert (_house_census(cen).frigate_count == 1) is census


# ---------------------------------------------------------------------------
# Review C findings 1, 2, 5, 6
# ---------------------------------------------------------------------------


def test_census_unresolved_camera_counts(house):
    """C-1: a camera no room watches (getter None) is counted as before by
    every census site (None is no opinion, never dead)."""
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 PROTECT: "off", ZV: "off"})
    census = _census(house, _panel_cameras())
    assert csh.entity_stream_dead(house.hass, PANEL) is None
    assert _house_census(census).frigate_count == 1
    assert census._get_unrecognized_camera_count() == 1


def test_census_cross_validation_off_dead_after_device_dedup(house, monkeypatch):
    """Review A-L1: with cross-validation off, the dead skip runs AFTER the
    device dedup, exactly like an unavailable entity: a second entity on
    the same device is not counted in place of the dead first one."""
    second = "binary_sensor.up_hallway_panel_motion"
    reg = _registry()
    reg._by_id[second] = _entry(second, "dev_panel")
    cams = _panel_cameras()
    cams[second] = CameraInfo(
        entity_id=second, platform="unifiprotect", area_id="upstairs_hallway",
        person_binary_sensor=second,
    )
    room = _RoomCoord(house, reg)
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 PROTECT: "off", ZV: "off", second: "on"})
    census = _census(house, cams)
    monkeypatch.setattr(census, "_is_cross_validation_enabled", lambda: False)
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: reg, raising=False)
    monkeypatch.setattr(
        census, "_stream_dead_interior",
        lambda ids: frozenset({PANEL}) if PANEL in ids else frozenset(),
    )
    room.tick(T0)
    assert _house_census(census).frigate_count == 0


def test_camera_is_dead_is_keyed_by_camera(house):
    """C-2: one room watches two cameras; one dies. The other camera reads
    live (no cross-camera bleed), for the dead and the hold getters."""
    kitchen_in = "binary_sensor.kitchen_panel_person_occupancy"
    reg = _registry()
    reg._by_id[kitchen_in] = _entry(kitchen_in, "dev_kitchen")
    room = _RoomCoord(house, reg, presence=(PANEL, kitchen_in))
    house.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off",
                 kitchen_in: "on", OTHER_CAM: "streaming"})
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert csh.camera_stream_dead(house.hass, PANEL_CAM) is True
    assert csh.camera_stream_dead(house.hass, OTHER_CAM) is False
    assert room.camera_stream_hold_expired(PANEL_CAM) is True
    assert room.camera_stream_hold_expired(OTHER_CAM) is False


def test_camera_is_dead_before_first_tick_is_none():
    """C-6: a fresh tracker (no resolution yet) has no opinion."""
    h = CameraInputStreamHealth(ROOM)
    assert h.camera_is_dead(PANEL_CAM) is None
    assert h.camera_hold_expired(PANEL_CAM) is None
    assert h.is_hold_expired(PANEL) is None


class _SplitRoom:
    """Room A answers the INPUT live; room B says its camera is dead."""

    def __init__(self, input_answer, camera_answer):
        self._camera_stream_health = object()
        self._i = input_answer
        self._c = camera_answer

    def camera_input_stream_dead(self, eid):
        return self._i if eid == PANEL else None

    def camera_stream_dead(self, cam):
        return self._c if cam == PANEL_CAM else None

    def camera_input_stream_hold_expired(self, eid, census=False):
        return False if eid == PANEL and self._i is not None else None

    def camera_stream_hold_expired(self, cam, census=False):
        return False if cam == PANEL_CAM and self._c is not None else None


def test_entity_stream_dead_direct_false_wins(house, monkeypatch):
    """C-6: a room that resolves the entity as its input and reads it live
    is the answer; the own-camera route is only the fallback."""
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: _registry(), raising=False)
    house.hass.data[DOMAIN]["room_a"] = _SplitRoom(False, None)
    house.hass.data[DOMAIN]["room_b"] = _SplitRoom(None, True)
    assert csh.entity_stream_dead(house.hass, PANEL) is False
    assert csh.entity_stream_view(house.hass, PANEL) is None


class _RaisingRoom:
    """A room whose every stream getter raises."""

    _camera_stream_health = object()

    def _boom(self, *_a):
        raise RuntimeError("getter broke")

    camera_input_stream_dead = _boom
    camera_stream_dead = _boom
    camera_input_stream_hold_expired = _boom
    camera_stream_hold_expired = _boom


def _boom_fn(*_a, **_k):
    raise RuntimeError("house getter broke")


class _HoldRaisingRoom(_RaisingRoom):
    """Dead per the getter; its hold getter raises."""

    def camera_input_stream_dead(self, eid):
        return True if eid == PANEL else None


def test_hold_getter_raises_reads_held(house):
    """C-5 (hold getter): a raising hold getter is no opinion, so a dead
    input reads HELD (unknown, keeps the level), never a crash."""
    house.hass.data[DOMAIN]["entry_room"] = _HoldRaisingRoom()
    assert csh.input_stream_view(house.hass, PANEL) == csh.VIEW_HELD


@pytest.mark.parametrize("where", ["room_getters", "house_functions"])
def test_getter_raises_input_still_counts(house, monkeypatch, where):
    """C-5: fail-open contract. A getter that raises (in a room, or the
    house-level function itself) never drops real presence and never
    crashes a reader: every reader counts the panel as before."""
    if where == "room_getters":
        house.hass.data[DOMAIN]["entry_room"] = _RaisingRoom()
    else:
        for name in ("input_stream_dead", "camera_stream_dead",
                     "entity_stream_dead", "input_stream_view",
                     "entity_stream_view"):
            monkeypatch.setattr(csh, name, _boom_fn)
    zone_cam = "binary_sensor.up_hallway_panel_person_occupancy_2"
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 PROTECT: "off", ZV: "off", zone_cam: "on"})
    if where == "room_getters":
        assert csh.input_stream_dead(house.hass, PANEL) is None
        assert csh.camera_stream_dead(house.hass, PANEL_CAM) is None
        assert csh.input_stream_view(house.hass, PANEL) is None
    # substrate (seed + discharge)
    sub, edges = _substrate(house)
    assert sub.is_kind_active(ROOM, "mmwave") is True
    sub.recheck_entities([PANEL])
    sub._handle_state_change(_ev(PANEL, "on", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    # zone camera tier
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    tracker.update_camera_detection(PANEL, True)
    assert tracker._any_camera_occupied() is True
    fake = SimpleNamespace(hass=house.hass)
    # Source 3
    zone = SimpleNamespace(rooms=[], zone_cameras=[zone_cam], room_conditions=[])
    house.hass.config_entries.async_entries.return_value = []
    assert PresenceCoordinator.check_zone_occupancy_confidence(fake, zone)[0] == 1
    # radar-sole gate
    house.hass.config_entries.async_entries.return_value = [fake_room_entry(
        ROOM, **{CONF_MOTION_SENSORS: [ZV], CONF_MMWAVE_SENSORS: [PANEL]},
    )]
    assert PresenceCoordinator._room_radar_sole_capable(fake, ROOM) is True
    # fan veto, both legs
    assert fan_veto._has_camera_person(
        house.hass, "Study A", {CONF_CAMERA_PERSON_ENTITIES: [PANEL]},
    ) is True
    assert fan_veto._has_recent_motion(
        house.hass, {CONF_MOTION_SENSORS: [PANEL], CONF_ROOM_NAME: ROOM},
    ) is True
    # census
    census = _census(house, _panel_cameras())
    assert _house_census(census).frigate_count == 1
    assert census._get_unrecognized_camera_count() == 1


def test_night_limb_getter_raises_counts(house, switch_off, monkeypatch):
    """C-5 (switch-off night limb): a raising view function counts the
    input as before."""
    monkeypatch.setattr(csh, "input_stream_view", _boom_fn)
    tracker = ZonePresenceTracker(
        hass=house.hass, zone_name="Upstairs", room_names=[ROOM],
    )
    tracker._has_sensors = True
    tracker._entity_to_room[PANEL] = ROOM
    house.set(**{PANEL: "on"})
    fake = SimpleNamespace(hass=house.hass)
    assert PresenceCoordinator._zone_night_rooms(fake, tracker) == [ROOM]


def test_real_coordinator_first_tick_no_spurious_flip(monkeypatch):
    """C-6: the REAL constructor's flip state starts empty, so the first
    tick of a live room sends the substrate no recheck."""
    from unittest.mock import patch

    import homeassistant.helpers.frame as _frame

    hass = MagicMock()
    calls: list = []
    hass.data = {DOMAIN: {"occupancy_substrate": SimpleNamespace(
        recheck_entities=lambda eids: calls.append(list(eids)),
    )}}
    states = {PANEL: _st("on"), PANEL_CAM: _st("streaming"), ZV: _st("off")}
    hass.states.get = states.get
    entry = MagicMock()
    entry.data = {"room_name": ROOM, CONF_ROOM_NAME: ROOM}
    entry.options = {}
    entry.entry_id = "E1"
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        c = UniversalRoomCoordinator(hass, entry)
    assert c._camera_stream_rechecking is False
    c._camera_stream_registry = lambda: _registry()
    c._camera_override_person_sensors = lambda: []
    c._apply_camera_stream_health_tick(T0, ROOM, [ZV], [PANEL], [])
    assert c.camera_input_stream_dead(PANEL) is False
    assert calls == []


def test_zone_switch_off_recheck_is_last_writer(house, switch_off):
    """Switch off, the discharge keeps the last-writer shape (one entity's
    own reading): the released panel writes its kind off even while a live
    same-kind radar reads on (byte-identical to the switch-off path)."""
    radar = "binary_sensor.upstairs_hallway_zk_presence"
    room = _RoomCoord(house, _registry(), presence=(PANEL, radar))
    _seed_states(house)
    house.set(**{radar: "on"})
    sub, _edges = _substrate(house, presence=(PANEL, radar))
    _outage(house, room)
    room.tick(T0 + timedelta(seconds=HOLD_END))
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_recheck_survives_a_raising_state_read(house, switch_off):
    """recheck_entities never raises: a state read that raises for one
    entity skips it and the rest of the batch still runs."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, edges = _substrate(house)
    house.set(**{ZV: "on"})
    real_get = house.hass.states.get

    def _get(eid):
        if eid == PANEL:
            raise RuntimeError("state machine broke")
        return real_get(eid)

    house.hass.states.get = _get
    sub.recheck_entities([PANEL, ZV])
    assert edges == [(ROOM, "motion", True)]
    del room


# ---------------------------------------------------------------------------
# Fix-up round 2 (operator 2026-11-14): measured caps (zone 900 s, census
# 900 s, two constants), the hold-release page, review D-M1 (an input that
# goes unavailable together with its camera is held from t0), D-L2 (a
# quarantined sensor is no live end), D-L3 (frozen census body: AWAY delay
# bounded by the census cap). Boundaries are literals.
# ---------------------------------------------------------------------------


def test_caps_are_independent_constants(house, monkeypatch):
    """Census cap 300 / zone cap 900: at 300 s the census view is released
    while the zone view is still held; at 900 s both are released."""
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 300.0)
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=299))
    assert csh.input_stream_view(house.hass, PANEL, census=True) == csh.VIEW_HELD
    room.tick(T0 + timedelta(seconds=300))
    assert csh.input_stream_view(house.hass, PANEL, census=True) == csh.VIEW_RELEASED
    assert csh.input_stream_view(house.hass, PANEL) == csh.VIEW_HELD
    room.tick(T0 + timedelta(seconds=899))
    assert csh.input_stream_view(house.hass, PANEL) == csh.VIEW_HELD
    room.tick(T0 + timedelta(seconds=900))
    assert csh.input_stream_view(house.hass, PANEL) == csh.VIEW_RELEASED


@pytest.mark.parametrize("which", ["zone", "census"])
@pytest.mark.parametrize(
    ("cap", "held_at", "released_at"),
    [
        (0.0, None, 120),          # 0 = no hold: released at the grace
        (60.0, None, 120),         # below the grace: released at the grace
        (1e9, 10 * 86400, None),   # very large: still held after 10 days
    ],
)
def test_cap_config_extremes(house, monkeypatch, which, cap, held_at, released_at):
    name = (
        "CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S" if which == "zone"
        else "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S"
    )
    monkeypatch.setattr(csh._const, name, cap)
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=119))
    assert csh.input_stream_view(house.hass, PANEL, census=(which == "census")) is None
    t = released_at if released_at is not None else held_at
    room.tick(T0 + timedelta(seconds=t))
    want = csh.VIEW_RELEASED if released_at is not None else csh.VIEW_HELD
    assert csh.input_stream_view(
        house.hass, PANEL, census=(which == "census"),
    ) == want


def _hold_nm(monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    got = {"page": [], "recover": []}

    async def _page(hass, **kw):
        if kw["kind"] == "camera_stream_hold_released":
            got["page"].append(kw)
        return True  # the real fire_stuck_signal returns True on dispatch

    async def _rec(hass, **kw):
        if kw["kind"] == "camera_stream_hold_released":
            got["recover"].append(kw)

    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _page)
    monkeypatch.setattr(_stuck_signal_nm, "stuck_signal_dispatch_ready", lambda hass: True)
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal_recovered", _rec)
    return got


def _drain(house):
    for c in house.tasks:
        _run(c)
    house.tasks.clear()


def test_hold_release_pages_once_per_outage(house, monkeypatch):
    """Past the cap: ONE HIGH page naming the camera and how long it has been
    dead ("hardware or host failure, not a normal outage"); none at 899 s,
    none again on later ticks; LOW recovery when it streams; a second
    outage pages again."""
    got = _hold_nm(monkeypatch)
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=899))
    _drain(house)
    assert got["page"] == []
    room.tick(T0 + timedelta(seconds=900))
    room.tick(T0 + timedelta(seconds=930))
    room.tick(T0 + timedelta(seconds=5000))
    _drain(house)
    assert len(got["page"]) == 1
    p = got["page"][0]
    assert p["severity"] == "HIGH"
    assert p["key"] == (PANEL_CAM,)
    assert PANEL_CAM in p["diagnosis"]
    assert "dead for 15 min" in p["diagnosis"]
    assert "hardware or host failure, not a normal outage" in p["diagnosis"]
    house.set(**{PANEL_CAM: "streaming"})
    room.tick(T0 + timedelta(seconds=5030))
    _drain(house)
    assert [r["key"] for r in got["recover"]] == [(PANEL_CAM,)]
    house.set(**{PANEL_CAM: "unavailable"})
    t1 = T0 + timedelta(seconds=6000)
    room.tick(t1)
    room.tick(t1 + timedelta(seconds=900))
    _drain(house)
    assert len(got["page"]) == 2


def test_hold_release_page_at_first_cap_and_none_when_both_zero(house, monkeypatch):
    """Census cap 300 < zone 900: the page fires at 300 s (first release),
    once. Both caps 0 (no hold): no hold page at all."""
    got = _hold_nm(monkeypatch)
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 300.0)
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=299))
    _drain(house)
    assert got["page"] == []
    room.tick(T0 + timedelta(seconds=300))
    room.tick(T0 + timedelta(seconds=900))
    _drain(house)
    assert len(got["page"]) == 1
    house2 = _House()
    try:
        got2 = _hold_nm(monkeypatch)
        monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S", 0.0)
        monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 0.0)
        room2 = _RoomCoord(house2, _registry())
        house2.set(**{PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"})
        for s in (0, 120, 3600):
            room2.tick(T0 + timedelta(seconds=s))
        _drain(house2)
        assert got2["page"] == []
    finally:
        house2.close()


# --- review D-M1: Protect device disconnect --------------------------------

P_IN = "binary_sensor.guest_room_g4_person_detected"
P_CAM = "camera.guest_room_g4_medium"


def _protect_registry():
    reg = _registry()
    reg._by_id[P_IN] = _entry(P_IN, "dev_g4", platform="unifiprotect")
    reg._by_id[P_CAM] = _entry(P_CAM, "dev_g4", platform="unifiprotect")
    return reg


@pytest.mark.parametrize("camera_first", [False, True])
def test_repro_protect_disconnect_sleep_guest_no_away(house, camera_first):
    """Reviewer D-M1 repro: SLEEP, a phone-less guest seen only by a Protect
    camera whose person sensor is the room input, the device drops off
    Wi-Fi: input AND camera go `unavailable` in one update (either write
    order). The kind is held from t0 (no off edge), nobody-home does not
    fire within the 900 s cap, and fires at the cap."""
    room = _RoomCoord(house, _protect_registry(), motion=(ZV,), presence=(P_IN,))
    house.set(**{P_IN: "on", P_CAM: "streaming", ZV: "off"})
    sub, tracker = _zone_stack(house, presence=(P_IN,))
    tracker.set_sleep(True)
    room.tick(T0)
    if camera_first:
        house.set(**{P_CAM: "unavailable", P_IN: "unavailable"})
    else:
        house.set(**{P_IN: "unavailable"})  # input written before the camera
    sub._handle_state_change(_ev(P_IN, "unavailable", old="on"))
    house.set(**{P_CAM: "unavailable"})
    assert sub.is_kind_active(ROOM, "mmwave") is True
    proposed, HouseState = _sleep_infer(house, tracker)
    assert proposed != HouseState.AWAY
    t = T0 + timedelta(seconds=10)
    for s in (30, 150, 899):
        room.tick(t + timedelta(seconds=s - 10))
        proposed, HouseState = _sleep_infer(house, tracker)
        assert proposed != HouseState.AWAY, s
    # cap clock starts at the first tick that saw the camera unavailable
    # (T0 + 30 s): released at T0 + 930 s
    room.tick(T0 + timedelta(seconds=929))
    proposed, HouseState = _sleep_infer(house, tracker)
    assert proposed != HouseState.AWAY
    room.tick(T0 + timedelta(seconds=930))
    proposed, HouseState = _sleep_infer(house, tracker)
    assert proposed == HouseState.AWAY


def test_unavailable_input_with_live_camera_turns_off_on_next_tick(house):
    """An ordinary sensor outage (camera still live): held until the next
    room tick has seen the camera live, then the kind goes off (one edge)
    through the tick's flip discharge."""
    room = _RoomCoord(house, _protect_registry(), presence=(P_IN,))
    house.set(**{P_IN: "on", P_CAM: "streaming", ZV: "off"})
    sub, edges = _substrate(house, presence=(P_IN,))
    room.tick(T0)
    house.set(**{P_IN: "unavailable"})
    sub._handle_state_change(_ev(P_IN, "unavailable", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    assert edges == []
    room.tick(T0 + timedelta(seconds=30))
    assert sub.is_kind_active(ROOM, "mmwave") is False
    assert edges == [(ROOM, "mmwave", False)]


def test_unavailable_hold_kill_switch_off_is_develop(house, monkeypatch):
    """Kill switch False: an unavailable input counts as off at t0."""
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", False)
    room = _RoomCoord(house, _protect_registry(), presence=(P_IN,))
    house.set(**{P_IN: "on", P_CAM: "streaming", ZV: "off"})
    sub, _edges = _substrate(house, presence=(P_IN,))
    room.tick(T0)
    house.set(**{P_IN: "unavailable", P_CAM: "unavailable"})
    sub._handle_state_change(_ev(P_IN, "unavailable", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_census_protect_disconnect_holds_last_reading(house):
    """Census: the Protect sensor read `on` (a body), then goes unavailable
    with its camera. Held: it keeps counting 1 (not a missing term) until
    the census cap (900 s from the camera's first unavailable tick)."""
    cams = {P_IN: CameraInfo(
        entity_id=P_IN, platform="unifiprotect", area_id="guest_room",
        person_binary_sensor=P_IN,
    )}
    room = _RoomCoord(house, _protect_registry(), presence=(P_IN,))
    house.set(**{P_IN: "on", P_CAM: "streaming", ZV: "off"})
    census = _census(house, cams)
    room.tick(T0)
    assert _house_census(census).unifi_count == 1
    house.set(**{P_IN: "unavailable", P_CAM: "unavailable"})
    assert _house_census(census).unifi_count == 1  # t0, before any tick
    room.tick(T0 + timedelta(seconds=30))
    room.tick(T0 + timedelta(seconds=30 + 899))
    assert _house_census(census).unifi_count == 1
    room.tick(T0 + timedelta(seconds=30 + 900))
    assert _house_census(census).unifi_count == 0


def test_census_unavailable_with_live_camera_is_missing(house):
    """Census: an unavailable sensor whose camera a tick has seen live is a
    missing term (develop)."""
    cams = {P_IN: CameraInfo(
        entity_id=P_IN, platform="unifiprotect", area_id="guest_room",
        person_binary_sensor=P_IN,
    )}
    room = _RoomCoord(house, _protect_registry(), presence=(P_IN,))
    house.set(**{P_IN: "on", P_CAM: "streaming", ZV: "off"})
    census = _census(house, cams)
    room.tick(T0)
    assert _house_census(census).unifi_count == 1
    house.set(**{P_IN: "unavailable"})
    room.tick(T0 + timedelta(seconds=30))
    assert _house_census(census).unifi_count == 0


def test_census_frigate_count_held_when_unavailable_with_camera(house):
    """Frigate-wide loss shape (audit: sensors go unavailable ~78 s after
    the camera): the count sensor unavailable while held keeps its last
    reading in the house census and the guest count."""
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "streaming",
                 PROTECT: "off", ZV: "off"})
    census = _census(house, _panel_cameras())
    room.tick(T0)
    assert _house_census(census).frigate_count == 1
    house.set(**{PANEL_CAM: "unavailable"})
    room.tick(T0 + timedelta(seconds=30))
    room.tick(T0 + timedelta(seconds=150))
    house.set(**{PANEL: "unavailable", PANEL_COUNT: "unavailable"})
    assert _house_census(census).frigate_count == 1
    assert census._get_unrecognized_camera_count() == 1


# --- review D-L2 / D-L3 ------------------------------------------------------


def test_quarantined_live_sensor_does_not_end_hold(house):
    """D-L2: the live ZV is chatter-quarantined by its room; its on -> off
    does not release the dead panel's hold. Unquarantined, it does."""
    room = _RoomCoord(house, _registry())
    _seed_states(house)
    sub, _edges = _substrate(house)
    _outage(house, room)
    room._exclusion_set.promote("chatter", ZV, reason="physics_violation")
    house.set(**{ZV: "on"})
    sub._handle_state_change(_ev(ZV, "on", old="off"))
    house.set(**{ZV: "off"})
    sub._handle_state_change(_ev(ZV, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is True
    room._exclusion_set.release("chatter", ZV)
    house.set(**{ZV: "on"})
    sub._handle_state_change(_ev(ZV, "on", old="off"))
    house.set(**{ZV: "off"})
    sub._handle_state_change(_ev(ZV, "off", old="on"))
    assert sub.is_kind_active(ROOM, "mmwave") is False


def test_departure_with_frozen_census_body_bounded_by_census_cap(house):
    """D-L3: everyone leaves just after the panel camera dies with a frozen
    body count of 1. The census keeps the body while held (alpha blocked:
    unidentified 1) and drops it at the 900 s census cap, so path alpha
    proposes AWAY on that run: the extra delay is bounded by the cap."""
    from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E501
        HouseState,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
        StateInferenceEngine,
    )
    room = _RoomCoord(house, _registry())
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 ZV: "off"})
    # Frigate panel only (single source: no cross-platform downgrade)
    census = _census(house, {PANEL: _panel_cameras()[PANEL]})
    noon = datetime(2026, 11, 12, 12, 0, 0)

    def _alpha():
        res = _house_census(census)
        return StateInferenceEngine().infer(
            census_count=res.total_persons, current_state=HouseState.HOME_DAY,
            any_zone_occupied=False, now=noon,
            # enhanced census (default ON): unidentified = the guest count
            unidentified_count=census._get_unrecognized_camera_count(),
            all_tracked_persons_away=True, face_recognized_count=0,
        )

    room.tick(T0)
    room.tick(T0 + timedelta(seconds=120))
    assert _alpha() != HouseState.AWAY
    room.tick(T0 + timedelta(seconds=899))
    assert _alpha() != HouseState.AWAY
    room.tick(T0 + timedelta(seconds=900))
    assert _alpha() == HouseState.AWAY


def test_census_cross_validation_off_holds_unavailable_with_camera(house, monkeypatch):
    """D-M1, cross-validation-off path: the Protect sensor going unavailable
    with its camera keeps its last reading (1) until the census cap."""
    cams = {P_IN: CameraInfo(
        entity_id=P_IN, platform="unifiprotect", area_id="guest_room",
        person_binary_sensor=P_IN,
    )}
    reg = _protect_registry()
    room = _RoomCoord(house, reg, presence=(P_IN,))
    house.set(**{P_IN: "on", P_CAM: "streaming", ZV: "off"})
    census = _census(house, cams)
    monkeypatch.setattr(census, "_is_cross_validation_enabled", lambda: False)
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: reg, raising=False)
    room.tick(T0)
    assert _house_census(census).frigate_count == 1
    house.set(**{P_IN: "unavailable", P_CAM: "unavailable"})
    assert _house_census(census).frigate_count == 1
    room.tick(T0 + timedelta(seconds=30))
    room.tick(T0 + timedelta(seconds=929))
    assert _house_census(census).frigate_count == 1
    room.tick(T0 + timedelta(seconds=930))
    assert _house_census(census).frigate_count == 0


@pytest.mark.parametrize("route", ["input", "own_camera"])
def test_census_reads_the_census_cap_not_the_zone_cap(house, monkeypatch, route):
    """The two caps are equal today (operator: both 15 min), which would
    hide a census reader on the zone cap (Bug Class #63). With census 300 /
    zone 900 the census drops the dead camera's body at 300 s, through the
    input route (a room input) and through the own-camera route (a census
    sensor that is no room input)."""
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 300.0)
    reg = _registry()
    cams = _panel_cameras()
    if route == "own_camera":
        other = "binary_sensor.up_hallway_panel_person_occupancy_2"
        reg._by_id[other] = _entry(other, "dev_panel")
        cams = {other: CameraInfo(
            entity_id=other, platform=ura_const.CAMERA_PLATFORM_FRIGATE,
            area_id="upstairs_hallway", person_binary_sensor=other,
            person_count_sensor=PANEL_COUNT,
        )}
        house.set(**{other: "on"})
    else:
        cams = {PANEL: cams[PANEL]}
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "async_get", lambda hass: reg, raising=False)
    room = _RoomCoord(house, reg)
    house.set(**{PANEL: "on", PANEL_COUNT: "1", PANEL_CAM: "unavailable",
                 ZV: "off"})
    census = _census(house, cams)
    room.tick(T0)
    room.tick(T0 + timedelta(seconds=299))
    assert _house_census(census).frigate_count == 1
    room.tick(T0 + timedelta(seconds=300))
    assert _house_census(census).frigate_count == 0
    assert csh.input_stream_view(house.hass, PANEL) == csh.VIEW_HELD  # zone


# --- one HIGH page per outage: S1 1800 s page suppressed after S2 page -----


def _eval(tracker, states, now):
    return tracker.evaluate(
        now, [PANEL, ZV], lambda eid: states.get(eid), lambda: _registry(),
    )


def test_s1_page_suppressed_after_hold_release_page(monkeypatch):
    """Caps 900 s < S1 page 1800 s (hardcoded literals). The S2 hold-release
    page fires at 900 s; at 1800 s the S1 per-input page for the same
    camera's input must NOT fire (one HIGH page per outage). A fresh outage
    after recovery pages S2 again and still suppresses S1."""
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", True)
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_GRACE_S", 120.0)
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S", 1800.0)
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S", 900.0)
    monkeypatch.setattr(
        csh._const, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 900.0,
    )
    tr = CameraInputStreamHealth(ROOM)
    states = {PANEL: _st("on"), PANEL_CAM: _st("unavailable"), ZV: _st("off")}
    _eval(tr, states, T0)
    _eval(tr, states, T0 + timedelta(seconds=900))
    assert [p[0] for p in tr.hold_pages] == [PANEL_CAM]
    # Ship 3b latch after send: the S2 page is latched once its send is
    # confirmed (the room tick site calls mark_paged on SENT/ALREADY_SENT).
    tr.mark_paged(csh.NM_KIND_HOLD_RELEASED, PANEL_CAM, T0.date().isoformat())
    for s in (1799, 1800, 1801, 5000):
        dead, to_page, _rec = _eval(tr, states, T0 + timedelta(seconds=s))
        assert PANEL in dead
        assert to_page == []
    # Recovery, then a second outage: S2 pages again, S1 still suppressed.
    states[PANEL_CAM] = _st("streaming")
    _eval(tr, states, T0 + timedelta(seconds=5030))
    states[PANEL_CAM] = _st("unavailable")
    t1 = T0 + timedelta(days=1)
    _eval(tr, states, t1)
    _eval(tr, states, t1 + timedelta(seconds=900))
    assert [p[0] for p in tr.hold_pages] == [PANEL_CAM]
    tr.mark_paged(csh.NM_KIND_HOLD_RELEASED, PANEL_CAM, t1.date().isoformat())
    _d, to_page, _r = _eval(tr, states, t1 + timedelta(seconds=1800))
    assert to_page == []


def test_s1_page_still_fires_when_no_hold_page(monkeypatch):
    """Both caps 0 (no hold, so no S2 page): the S1 1800 s page fires as
    before (the suppression keys on the S2 page, not on the caps)."""
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", True)
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_GRACE_S", 120.0)
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S", 1800.0)
    monkeypatch.setattr(csh._const, "CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S", 0.0)
    monkeypatch.setattr(
        csh._const, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 0.0,
    )
    tr = CameraInputStreamHealth(ROOM)
    states = {PANEL: _st("on"), PANEL_CAM: _st("unavailable"), ZV: _st("off")}
    _eval(tr, states, T0)
    _d, to_page, _r = _eval(tr, states, T0 + timedelta(seconds=1799))
    assert to_page == []
    _d, to_page, _r = _eval(tr, states, T0 + timedelta(seconds=1800))
    assert [(e, c) for e, c, _s in to_page] == [(PANEL, PANEL_CAM)]
    assert tr.hold_pages == []

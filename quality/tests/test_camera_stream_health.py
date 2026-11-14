"""Camera input stream health S1 — room-tier exclusion of dead-stream inputs.

Plan: docs/planning/PLANNING_camera_input_stream_health.md (S1).
Bug classes guarded: #53 computed-but-not-consumed (the dead verdict must
reach room fusion), #62 hollow anchor (every test drives production code:
the real ``_async_update_data`` slice reset_tick -> presence leg, the real
tracker, the real resolver helper, the real sensor attribute builder).

Oracles are hand-derived: the Up Hallway outage shape (panel person sensor
frozen ``on``, its Frigate camera entity ``unavailable``) is replayed on a
synthetic clock; the grace boundary uses literals 119 / 120 / 121 s and the
NM boundary 1799 / 1800 s, never the imported constants.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstrap homeassistant mocks

from custom_components.universal_room_automation import coordinator as _coord_mod
from custom_components.universal_room_automation.const import (
    DOMAIN,
    STATE_MOTION_DETECTED,
    STATE_OCCUPANCY_SOURCE,
    STATE_OCCUPIED,
    STATE_PRESENCE_DETECTED,
    STATE_TIMEOUT_REMAINING,
)
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators import (
    _stuck_signal_nm,
)
from custom_components.universal_room_automation.domain_coordinators import (
    camera_stream_health as _csh,
)
from custom_components.universal_room_automation.domain_coordinators.camera_stream_health import (  # noqa: E501
    CameraInputStreamHealth,
)
from custom_components.universal_room_automation.domain_coordinators.sensor_exclusion import (  # noqa: E501
    SensorExclusionSet,
)

_COORD_SRC = (
    pathlib.Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation" / "coordinator.py"
)

ROOM = "Upstairs Hallway"
PANEL = "binary_sensor.up_hallway_panel_person_occupancy"
PANEL_CAM = "camera.up_hallway_panel"
ZV = "binary_sensor.upstairs_hallway_motion_presence_2"
T0 = datetime(2026, 11, 11, 22, 52, 0)


# ---------------------------------------------------------------------------
# The real tick slice: reset_tick -> P22 -> dutycycle -> chatter -> camera
# stream health -> motion leg -> presence leg (production source, executed).
# ---------------------------------------------------------------------------


def _slice(start_marker, end_marker):
    """Compile a contiguous block of ``_async_update_data`` (production
    source, executed, not grepped) dedented to module level."""
    src = _COORD_SRC.read_text(encoding="utf-8")
    start = src.index(start_marker)
    end = src.index(end_marker, start) + len(end_marker)
    lines = []
    for ln in src[start:end].splitlines():
        lines.append(ln[8:] if ln.startswith(" " * 8) else ln.strip())
    return compile("\n".join(lines), str(_COORD_SRC), "exec")


# reset_tick -> ... -> camera stream health -> motion, presence and
# occupancy legs.
_TICK = _slice(
    "        self._exclusion_set.reset_tick()\n",
    "            for s in self._fusion_filter_active(occupancy_sensors)\n"
    "        )\n",
)
# The v3.5.1 camera override block (review B-M1).
_OVERRIDE = _slice(
    "        # === v3.5.1: Camera extends room occupancy ===\n",
    "                    break\n",
)


class _Registry:
    """Entity registry double: ``async_get`` + the device index HA exposes as
    ``entities.get_entries_for_device_id``. Returns disabled entries too, so
    the production disabled filter is what is tested."""

    def __init__(self, entries):
        self._by_id = {e.entity_id: e for e in entries}
        self.entities = self
        self.lookups = 0

    def async_get(self, entity_id):
        self.lookups += 1
        return self._by_id.get(entity_id)

    def get_entries_for_device_id(self, device_id, include_disabled=False):
        return [e for e in self._by_id.values() if e.device_id == device_id]


def _entry(eid, device_id, platform="frigate", disabled_by=None):
    return SimpleNamespace(
        entity_id=eid, device_id=device_id, platform=platform,
        disabled_by=disabled_by,
    )


def _panel_registry(extra=()):
    return _Registry([
        _entry(PANEL, "dev_panel"),
        _entry(PANEL_CAM, "dev_panel"),
        _entry(ZV, "dev_zv", platform="mqtt"),
        *extra,
    ])


_ROOMS: list = []


class _Room:
    """Bare room: real production methods bound onto a stub, real
    SensorExclusionSet + real CameraInputStreamHealth. Unrelated writers in
    the slice (P22, duty-cycle, chatter) are quiet."""

    def __init__(self, registry, *, motion=(ZV,), presence=(PANEL,),
                 occupancy=(), override=()):
        # value: a state string, or (state, attributes).
        self.states: dict = {}
        self.registry = registry
        self.motion = list(motion)
        self.presence = list(presence)
        self.occupancy = list(occupancy)
        self.tasks: list = []
        self.occupancy_detected = None
        _ROOMS.append(self)
        self.hass = MagicMock()
        self.hass.states.get = self._get_state
        # Camera manager double for the v3.5.1 override: the person sensors
        # of cameras in this room's area (e.g. camera.up_hallway_panel added
        # to Upstairs Hallway, area upstairs_hallway).
        self.area = "upstairs_hallway"
        override_list = list(override)
        self.hass.data = {DOMAIN: {"camera_manager": SimpleNamespace(
            get_person_sensor_for_area=lambda area: (
                list(override_list) if area == "upstairs_hallway" else []
            ),
        )}} if override_list else {}
        # Room fields the override block reads / writes.
        self._failsafe_fired = False
        self._occupancy_timeout = 300
        self._last_motion_time = None
        self._became_occupied_time = None
        self._last_occupied_state = False
        self._last_occupied_time = None
        self._ble_only_hold_since = None
        self._ble_absent_since = None
        self._ble_grace_used = False

        def _capture(coro, *a, **kw):
            self.tasks.append(coro)
            return MagicMock()

        self.hass.async_create_task = _capture
        self.entry = MagicMock()
        self.entry.data = {"room_name": ROOM}
        self._exclusion_set = SensorExclusionSet(room_name=ROOM)
        self._camera_stream_health = CameraInputStreamHealth(ROOM)
        self._stuck_sensor_kinds = {}
        self._dutycycle_excluded_last_tick = set()
        self._dutycycle_excluded_now = {}
        self._d2_completed_cleanly = False
        self._unsub_state_listeners = []
        for name in (
            "_fusion_filter_active", "_is_sensor_on",
            "_apply_camera_stream_health_tick", "camera_input_stream_dead",
            "camera_stream_health_snapshot",
            "_subscribe_camera_stream_registry_updates",
            "_camera_override_person_sensors",
            "_camera_override_live_person_sensors",
        ):
            fn = getattr(UniversalRoomCoordinator, name)
            setattr(self, name, fn.__get__(self, type(self)))

    # HA seam + quiet writers -------------------------------------------
    def _get_state(self, eid):
        v = self.states.get(eid)
        if v is None:
            return None
        if isinstance(v, tuple):
            return SimpleNamespace(state=v[0], attributes=dict(v[1]))
        return SimpleNamespace(state=v, attributes={})

    def _get_room_area(self):
        return self.area

    def _camera_stream_registry(self):
        return self.registry

    def _p22_stuck_sensor_set(self, now):
        return set()

    def _emit_p22_stuck_sensor_for_tick(self, *a):
        pass

    def _detect_duty_cycle_stuck(self, **kw):
        return []

    def _dutycycle_notify_release(self, *a):
        pass

    def _release_edge_scan_should_run(self):
        return True

    def _apply_chatter_tick(self, *a):
        pass

    # Driver ---------------------------------------------------------------
    def tick(self, now):
        ns = {
            "self": self, "now": now, "data": {}, "room_name": ROOM,
            "motion_sensors": list(self.motion),
            "mmwave_sensors": list(self.presence),
            "occupancy_sensors": list(self.occupancy),
            "_LOGGER": logging.getLogger("camera_stream_health_test"),
            "STATE_MOTION_DETECTED": STATE_MOTION_DETECTED,
            "STATE_PRESENCE_DETECTED": STATE_PRESENCE_DETECTED,
        }
        exec(_TICK, ns)
        self.occupancy_detected = ns["occupancy_detected"]
        return ns["data"]

    def override(self, now):
        """Run the production camera override block on a vacant tick;
        returns (occupied, source)."""
        data = {STATE_OCCUPIED: False}
        ns = {
            "self": self, "now": now, "data": data, "room_name": ROOM,
            "_LOGGER": logging.getLogger("camera_stream_health_test"),
            "STATE_OCCUPIED": STATE_OCCUPIED,
            "STATE_OCCUPANCY_SOURCE": STATE_OCCUPANCY_SOURCE,
            "STATE_TIMEOUT_REMAINING": STATE_TIMEOUT_REMAINING,
        }
        exec(_OVERRIDE, ns)
        return data[STATE_OCCUPIED], data.get(STATE_OCCUPANCY_SOURCE)

    def close_tasks(self):
        for c in self.tasks:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self.tasks.clear()


def _pre_s1_room(registry):
    """The same room with the S1 call neutered: what develop computed."""
    r = _Room(registry)
    r._apply_camera_stream_health_tick = lambda *a, **k: None
    return r


@pytest.fixture(autouse=True)
def _nm_state():
    _stuck_signal_nm.reset_latches_for_tests()
    yield
    while _ROOMS:
        _ROOMS.pop().close_tasks()
    _stuck_signal_nm.reset_latches_for_tests()


@pytest.fixture
def nm_calls(monkeypatch):
    """Record the stuck-signal NM calls the tick site schedules."""
    calls = {"page": [], "recover": []}

    async def _page(hass, **kw):
        calls["page"].append(kw)
        return True

    async def _recover(hass, **kw):
        calls["recover"].append(kw)
        return True

    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _page)
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal_recovered", _recover)
    return calls


def _drain(room):
    loop = asyncio.new_event_loop()
    try:
        for c in room.tasks:
            loop.run_until_complete(c)
    finally:
        loop.close()
    room.tasks.clear()


# ---------------------------------------------------------------------------
# Named plan tests
# ---------------------------------------------------------------------------


def test_dead_stream_excludes_input_after_grace():
    """Up Hallway shape: panel person `on`, its camera `unavailable` from t0.
    Held at +119 s, released at +120 s with provenance camera_stream_dead."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    d = r.tick(T0)
    assert d[STATE_PRESENCE_DETECTED] is True
    d = r.tick(T0 + timedelta(seconds=119))
    assert d[STATE_PRESENCE_DETECTED] is True
    assert r.camera_input_stream_dead(PANEL) is False
    d = r.tick(T0 + timedelta(seconds=120))
    assert d[STATE_PRESENCE_DETECTED] is False
    assert r._exclusion_set.clients_for(PANEL) == {"camera_stream_dead"}
    assert r._exclusion_set.provenance(PANEL)["camera_stream_dead"] == (
        f"{PANEL_CAM} unavailable since {T0.isoformat()}"
    )
    assert r.camera_input_stream_dead(PANEL) is True
    d = r.tick(T0 + timedelta(seconds=121))
    assert d[STATE_PRESENCE_DETECTED] is False
    # Four hours later the input is still excluded every tick (the old shape
    # held the room until the 4 h stuck rule).
    d = r.tick(T0 + timedelta(hours=4))
    assert d[STATE_PRESENCE_DETECTED] is False


def test_dead_stream_cannot_create_occupancy():
    """INV-STREAM 'neither create nor hold': a dead-stream input turning `on`
    after the grace does not produce presence."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "off", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    r.states[PANEL] = "on"
    d = r.tick(T0 + timedelta(seconds=300))
    assert d[STATE_PRESENCE_DETECTED] is False


def test_restart_blip_not_excluded():
    """Camera unavailable 60 s, then streaming: never excluded; a later
    outage starts its grace afresh."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    r.tick(T0 + timedelta(seconds=60))
    r.states[PANEL_CAM] = "streaming"
    d = r.tick(T0 + timedelta(seconds=90))
    assert d[STATE_PRESENCE_DETECTED] is True
    r.states[PANEL_CAM] = "unavailable"
    d = r.tick(T0 + timedelta(seconds=150))  # 150 s after t0, 0 s into new outage
    assert d[STATE_PRESENCE_DETECTED] is True
    d = r.tick(T0 + timedelta(seconds=269))  # 119 s into the new outage
    assert d[STATE_PRESENCE_DETECTED] is True
    assert not r._exclusion_set.is_excluded(PANEL)
    d = r.tick(T0 + timedelta(seconds=270))  # 120 s
    assert d[STATE_PRESENCE_DETECTED] is False


@pytest.mark.parametrize("variant", ["no_device", "disabled_camera", "no_camera",
                                     "not_in_registry"])
def test_unresolved_camera_byte_identical(variant):
    """Unresolved camera → room fusion equals the pre-S1 code (call neutered)
    over the same outage, tick by tick, and the getter says None."""
    if variant == "no_device":
        reg = _Registry([_entry(PANEL, None), _entry(PANEL_CAM, "dev_panel"),
                         _entry(ZV, "dev_zv", platform="mqtt")])
    elif variant == "disabled_camera":
        reg = _Registry([_entry(PANEL, "dev_panel"),
                         _entry(PANEL_CAM, "dev_panel", disabled_by="user"),
                         _entry(ZV, "dev_zv", platform="mqtt")])
    elif variant == "no_camera":
        reg = _Registry([_entry(PANEL, "dev_panel"),
                         _entry(ZV, "dev_zv", platform="mqtt")])
    else:
        reg = _Registry([_entry(ZV, "dev_zv", platform="mqtt")])
    states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    new, old = _Room(reg), _pre_s1_room(reg)
    new.states, old.states = dict(states), dict(states)
    for s in (0, 119, 120, 600, 7200):
        now = T0 + timedelta(seconds=s)
        assert new.tick(now) == old.tick(now)
        assert new._exclusion_set.excluded() == old._exclusion_set.excluded()
    assert new.camera_input_stream_dead(PANEL) is None
    assert new.tasks == []


def test_multi_camera_device_unresolved():
    """A device hosting two camera entities (an NVR) cannot say which stream
    feeds the input: unresolved, never excluded, getter None."""
    reg = _panel_registry(extra=(_entry("camera.up_hallway_panel_sub",
                                        "dev_panel"),))
    r = _Room(reg)
    r.states = {PANEL: "on", PANEL_CAM: "unavailable",
                "camera.up_hallway_panel_sub": "unavailable", ZV: "off"}
    r.tick(T0)
    d = r.tick(T0 + timedelta(seconds=600))
    assert d[STATE_PRESENCE_DETECTED] is True
    assert r.camera_input_stream_dead(PANEL) is None
    assert r.camera_stream_health_snapshot()["camera_stream_inputs_resolved"] == 0


def test_live_stream_input_counts():
    """Discriminating: person `on` with camera `streaming` → occupied as
    today; getter False (resolved, counting)."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "streaming", ZV: "off"}
    for s in (0, 120, 3600):
        d = r.tick(T0 + timedelta(seconds=s))
        assert d[STATE_PRESENCE_DETECTED] is True
    assert r.camera_input_stream_dead(PANEL) is False
    assert r.camera_stream_health_snapshot() == {
        "camera_stream_dead_inputs": {},
        "camera_stream_inputs_resolved": 1,
    }


def test_nm_after_threshold_and_recovery(nm_calls):
    """HIGH page once at 1800 s of exclusion (not 1799), LOW recovered once
    on release, and no second page the same local day."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    r.tick(T0 + timedelta(seconds=1799))
    _drain(r)
    assert nm_calls["page"] == []
    r.tick(T0 + timedelta(seconds=1800))
    _drain(r)
    assert len(nm_calls["page"]) == 1
    r.tick(T0 + timedelta(seconds=1830))
    _drain(r)
    assert len(nm_calls["page"]) == 1
    page = nm_calls["page"][0]
    assert page["kind"] == "camera_stream_dead"
    assert page["key"] == (ROOM, PANEL)
    assert page["severity"] == "HIGH"
    assert page["exclusion_engaged"] is True
    assert PANEL_CAM in page["diagnosis"]
    r.states[PANEL_CAM] = "streaming"
    r.tick(T0 + timedelta(seconds=1860))
    r.tick(T0 + timedelta(seconds=1890))
    _drain(r)
    assert len(nm_calls["recover"]) == 1
    assert nm_calls["recover"][0]["key"] == (ROOM, PANEL)
    # The recovered NM pairs with the page: same kind.
    assert nm_calls["recover"][0]["kind"] == "camera_stream_dead"
    assert "counts again" in nm_calls["recover"][0]["message"]
    assert PANEL_CAM in nm_calls["recover"][0]["message"]
    assert page["title_override"] == f"Camera stream dead: {ROOM}"
    # Second outage the same day: excluded again, but no second page.
    r.states[PANEL_CAM] = "unavailable"
    r.tick(T0 + timedelta(seconds=1900))
    d = r.tick(T0 + timedelta(seconds=1900 + 1800))
    _drain(r)
    assert d[STATE_PRESENCE_DETECTED] is False
    assert len(nm_calls["page"]) == 1
    # Next local day the same episode may page again.
    r.tick(T0.replace(hour=0, minute=10) + timedelta(days=1))
    _drain(r)
    assert len(nm_calls["page"]) == 2


def test_nm_one_page_per_episode_across_midnight(nm_calls):
    """A continuous outage (the 39 h Up Hallway shape) pages once, not again
    at the next local day while the same episode lasts."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    r.tick(T0 + timedelta(seconds=1800))
    r.tick(T0 + timedelta(hours=3))  # next local day, same episode
    r.tick(T0 + timedelta(hours=27))
    _drain(r)
    assert len(nm_calls["page"]) == 1
    assert nm_calls["recover"] == []


def test_nm_after_zero_disables_page_not_exclusion(monkeypatch, nm_calls):
    monkeypatch.setattr(_csh._const, "CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S", 0)
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    d = r.tick(T0 + timedelta(hours=3))
    _drain(r)
    assert d[STATE_PRESENCE_DETECTED] is False
    assert nm_calls["page"] == []


def test_kill_switch_off_byte_identical(monkeypatch, nm_calls):
    monkeypatch.setattr(_csh._const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", False)
    reg = _panel_registry()
    new, old = _Room(reg), _pre_s1_room(reg)
    states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    new.states, old.states = dict(states), dict(states)
    for s in (0, 120, 1800, 7200):
        now = T0 + timedelta(seconds=s)
        assert new.tick(now) == old.tick(now)
        assert new._exclusion_set.excluded() == old._exclusion_set.excluded()
    _drain(new)
    assert nm_calls == {"page": [], "recover": []}
    assert new.camera_input_stream_dead(PANEL) is False


def test_kill_switch_flip_mid_episode_releases_and_recovers(monkeypatch, nm_calls):
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    r.tick(T0 + timedelta(seconds=1800))
    _drain(r)
    assert len(nm_calls["page"]) == 1
    monkeypatch.setattr(_csh._const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", False)
    d = r.tick(T0 + timedelta(seconds=1830))
    _drain(r)
    assert d[STATE_PRESENCE_DETECTED] is True
    assert len(nm_calls["recover"]) == 1


def test_unknown_state_no_opinion():
    """`unknown` / no state: no exclusion; an `unknown` gap neither starts
    nor clears an outage (the stamp survives it)."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unknown", ZV: "off"}
    r.tick(T0)
    d = r.tick(T0 + timedelta(seconds=600))
    assert d[STATE_PRESENCE_DETECTED] is True
    del r.states[PANEL_CAM]  # entity not loaded
    d = r.tick(T0 + timedelta(seconds=900))
    assert d[STATE_PRESENCE_DETECTED] is True
    r.states[PANEL_CAM] = "unavailable"
    r.tick(T0 + timedelta(seconds=1000))  # stamp at 1000
    r.states[PANEL_CAM] = "unknown"
    d = r.tick(T0 + timedelta(seconds=1060))
    assert d[STATE_PRESENCE_DETECTED] is True  # no opinion this tick
    r.states[PANEL_CAM] = "unavailable"
    # 120 s after the last `unavailable` reading (gap within the grace):
    # the stamp survived the `unknown` tick, so 120 s of outage -> excluded.
    d = r.tick(T0 + timedelta(seconds=1120))
    assert d[STATE_PRESENCE_DETECTED] is False


# ---------------------------------------------------------------------------
# Extra anchors: grace boundary on the tracker, other inputs untouched,
# getter, resolution cache, registry subscription, sensor surface.
# ---------------------------------------------------------------------------


def test_only_the_dead_cameras_inputs_are_excluded():
    """The healthy ZV beside the dead panel still votes."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "on"}
    r.tick(T0)
    d = r.tick(T0 + timedelta(seconds=300))
    assert d[STATE_MOTION_DETECTED] is True
    assert r._exclusion_set.excluded() == {PANEL}
    assert r.camera_input_stream_dead(ZV) is None  # mqtt, no camera
    assert r.camera_input_stream_dead("binary_sensor.elsewhere") is None


def test_grace_boundary_literals_on_tracker():
    h = CameraInputStreamHealth(ROOM)
    reg = _panel_registry()
    states = {PANEL_CAM: SimpleNamespace(state="unavailable")}
    h.evaluate(T0, [PANEL], states.get, lambda: reg)
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=119), [PANEL], states.get,
                              lambda: reg)
    assert dead == {}
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=120), [PANEL], states.get,
                              lambda: reg)
    assert dead == {PANEL: (PANEL_CAM, T0)}
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=121), [PANEL], states.get,
                              lambda: reg)
    assert dead == {PANEL: (PANEL_CAM, T0)}


def test_resolution_cached_until_invalidated():
    reg = _panel_registry()
    r = _Room(reg)
    r.states = {PANEL: "on", PANEL_CAM: "streaming", ZV: "off"}
    r.tick(T0)
    first = reg.lookups
    r.tick(T0 + timedelta(seconds=30))
    assert reg.lookups == first  # cached
    r._camera_stream_health.invalidate()
    r.tick(T0 + timedelta(seconds=60))
    assert reg.lookups > first


def test_resolution_rebuilt_when_room_inputs_change():
    """A room input list edited in options re-resolves without a registry
    event (cache keyed on the input tuple)."""
    reg = _panel_registry()
    h = CameraInputStreamHealth(ROOM)
    states = {PANEL_CAM: SimpleNamespace(state="unavailable")}
    h.evaluate(T0, [ZV], states.get, lambda: reg)
    assert h.is_dead(PANEL) is None
    h.evaluate(T0 + timedelta(seconds=10), [ZV, PANEL], states.get, lambda: reg)
    assert h.is_dead(PANEL) is False
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=130), [ZV, PANEL],
                              states.get, lambda: reg)
    assert dead == {PANEL: (PANEL_CAM, T0 + timedelta(seconds=10))}


def test_registry_subscription_invalidates_cache(monkeypatch):
    """The setup path: the entity-registry listener clears the resolution
    cache, so a camera added to the device later is picked up."""
    import homeassistant.helpers.entity_registry as er_mod
    monkeypatch.setattr(er_mod, "EVENT_ENTITY_REGISTRY_UPDATED",
                        "entity_registry_updated", raising=False)
    reg = _Registry([_entry(PANEL, "dev_panel"),
                     _entry(ZV, "dev_zv", platform="mqtt")])
    r = _Room(reg)
    listeners = {}

    def _listen(event_type, cb):
        listeners[event_type] = cb
        return MagicMock(name="unsub")

    r.hass.bus.async_listen = _listen
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    assert r.camera_input_stream_dead(PANEL) is None
    r._subscribe_camera_stream_registry_updates()
    assert "entity_registry_updated" in listeners
    assert len(r._unsub_state_listeners) == 1
    r.tick(T0 + timedelta(seconds=10))
    # The camera entity appears on the device; the registry event fires.
    reg._by_id[PANEL_CAM] = _entry(PANEL_CAM, "dev_panel")
    r.tick(T0 + timedelta(seconds=20))
    assert r.camera_input_stream_dead(PANEL) is None  # still cached
    listeners["entity_registry_updated"](MagicMock())
    r.tick(T0 + timedelta(seconds=30))
    assert r.camera_input_stream_dead(PANEL) is False  # resolved, stamp 30
    d = r.tick(T0 + timedelta(seconds=150))
    assert d[STATE_PRESENCE_DETECTED] is False


def test_first_refresh_subscribes_registry_listener(monkeypatch):
    """Call-site anchor: async_config_entry_first_refresh wires the
    registry subscription (driven on the real method)."""
    from unittest.mock import AsyncMock, patch

    import homeassistant.helpers.frame as _frame

    calls = []

    def _sub(self):
        calls.append("subscribed")

    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.data = {"room_name": ROOM}
    entry.options = {}
    entry.entry_id = "E1"
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        c = UniversalRoomCoordinator(hass, entry)
    base = UniversalRoomCoordinator.__mro__[1]
    monkeypatch.setattr(base, "async_config_entry_first_refresh",
                        AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(UniversalRoomCoordinator,
                        "_subscribe_camera_stream_registry_updates", _sub)
    c._async_load_stuck_state = AsyncMock(return_value=None)
    c._update_signal_subscriptions = MagicMock()
    c._get_config = lambda key, default=None: default
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(c.async_config_entry_first_refresh())
    finally:
        loop.close()
    assert calls == ["subscribed"]


def test_unresolved_camera_derived_input_warns_once(caplog):
    """Silence check: a camera-derived input that never resolves (two
    cameras) logs one WARNING per coordinator lifetime."""
    reg = _panel_registry(extra=(_entry("camera.up_hallway_panel_sub",
                                        "dev_panel"),))
    h = CameraInputStreamHealth(ROOM)
    with caplog.at_level(logging.WARNING):
        h.evaluate(T0, [PANEL, ZV], lambda e: None, lambda: reg)
        h.invalidate()
        h.evaluate(T0, [PANEL, ZV], lambda e: None, lambda: reg)
    warns = [r for r in caplog.records if "no single camera entity" in r.message]
    assert len(warns) == 1
    assert "multi_camera" in warns[0].message


def test_sensor_surface_attributes():
    """sensor.<room>_unavailable_entities carries the two display attrs
    from the real coordinator snapshot."""
    try:
        from custom_components.universal_room_automation import sensor as sen
    except Exception:  # noqa: BLE001
        pytest.skip("sensor.py not importable in this environment")
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    r.tick(T0 + timedelta(seconds=120))
    coord = MagicMock()
    coord.entry.data = {"presence_sensors": [PANEL], "motion_sensors": [ZV]}
    coord.entry.options = {}
    coord.hass = r.hass
    coord._chattering_entities = set()
    coord._chatter_detector = None
    coord._dutycycle_notify_active = None
    coord._actuator_reconciler = None
    coord.camera_stream_health_snapshot = r.camera_stream_health_snapshot
    s = object.__new__(sen.UnavailableEntitiesSensor)
    s.coordinator = coord
    attrs = s.extra_state_attributes
    assert attrs["camera_stream_dead_inputs"] == {
        PANEL: {"camera": PANEL_CAM, "since": T0.isoformat()},
    }
    assert attrs["camera_stream_inputs_resolved"] == 1
    assert {"camera_stream_dead_inputs", "camera_stream_inputs_resolved"} <= (
        sen.UnavailableEntitiesSensor._unrecorded_attributes
    )


# ---------------------------------------------------------------------------
# Fix-up round (reviews A / B / C)
# ---------------------------------------------------------------------------


def test_real_registry_seam_reaches_er_async_get(monkeypatch):
    """Review C HIGH-1: the production seam `_camera_stream_registry` (not a
    stub override) hands `er.async_get(self.hass)` to the tracker."""
    reg = _panel_registry()
    r = _Room(reg)
    r._camera_stream_registry = UniversalRoomCoordinator._camera_stream_registry.__get__(
        r, type(r),
    )
    seen = []

    def _async_get(hass):
        seen.append(hass)
        return reg if hass is r.hass else None

    monkeypatch.setattr(_coord_mod, "er", SimpleNamespace(async_get=_async_get))
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    d = r.tick(T0 + timedelta(seconds=120))
    assert seen and seen[0] is r.hass
    assert d[STATE_PRESENCE_DETECTED] is False
    assert r.camera_input_stream_dead(PANEL) is True


def test_camera_backed_input_in_motion_list_excluded():
    """Review C HIGH-2: a camera-backed input filed under motion_sensors."""
    r = _Room(_panel_registry(), motion=(PANEL,), presence=())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable"}
    d = r.tick(T0)
    assert d[STATE_MOTION_DETECTED] is True
    d = r.tick(T0 + timedelta(seconds=120))
    assert d[STATE_MOTION_DETECTED] is False
    assert r._exclusion_set.clients_for(PANEL) == {"camera_stream_dead"}


def test_camera_backed_input_in_occupancy_list_excluded():
    """Review C HIGH-2: a camera-backed input filed under occupancy_sensors."""
    r = _Room(_panel_registry(), motion=(), presence=(), occupancy=(PANEL,))
    r.states = {PANEL: "on", PANEL_CAM: "unavailable"}
    r.tick(T0)
    assert r.occupancy_detected is True
    r.tick(T0 + timedelta(seconds=120))
    assert r.occupancy_detected is False
    assert r._exclusion_set.clients_for(PANEL) == {"camera_stream_dead"}


def _real_coordinator(monkeypatch):
    """A real UniversalRoomCoordinator whose bus records every listener,
    with the real registry subscription (not patched)."""
    from unittest.mock import AsyncMock, patch

    import homeassistant.helpers.entity_registry as er_mod
    import homeassistant.helpers.frame as _frame

    monkeypatch.setattr(er_mod, "EVENT_ENTITY_REGISTRY_UPDATED",
                        "entity_registry_updated", raising=False)
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    subs = []  # (callback, unsub) for entity_registry_updated

    def _listen(event_type, cb):
        unsub = MagicMock(name=f"unsub_{event_type}_{len(subs)}")
        if event_type == "entity_registry_updated":
            subs.append((cb, unsub))
        return unsub

    hass.bus.async_listen = _listen
    entry = MagicMock()
    entry.data = {"room_name": ROOM}
    entry.options = {}
    entry.entry_id = "E1"
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        c = UniversalRoomCoordinator(hass, entry)
    base = UniversalRoomCoordinator.__mro__[1]
    monkeypatch.setattr(base, "async_config_entry_first_refresh",
                        AsyncMock(return_value=None), raising=False)
    c._async_load_stuck_state = AsyncMock(return_value=None)
    c._update_signal_subscriptions = MagicMock()
    c._get_config = lambda key, default=None: default
    return hass, entry, c, subs


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_registry_listener_survives_setup_clear_and_invalidates(monkeypatch):
    """Review C HIGH-3a: after the real first refresh the registry listener
    is live (subscribed AFTER the re-setup clear block) and its callback
    marks the resolution stale."""
    hass, entry, c, subs = _real_coordinator(monkeypatch)
    _run(c.async_config_entry_first_refresh())
    assert len(subs) == 1
    cb, unsub = subs[0]
    assert unsub in c._unsub_state_listeners
    unsub.assert_not_called()
    # Callback drives the real tracker: a camera added to the device after
    # the first resolution is picked up only after the registry event.
    reg = _Registry([_entry(PANEL, "dev_panel")])
    states = {PANEL_CAM: SimpleNamespace(state="unavailable", attributes={})}
    h = c._camera_stream_health
    h.evaluate(T0, [PANEL], states.get, lambda: reg)
    assert h.is_dead(PANEL) is None
    reg._by_id[PANEL_CAM] = _entry(PANEL_CAM, "dev_panel")
    h.evaluate(T0 + timedelta(seconds=10), [PANEL], states.get, lambda: reg)
    assert h.is_dead(PANEL) is None  # cached
    cb(MagicMock())
    h.evaluate(T0 + timedelta(seconds=20), [PANEL], states.get, lambda: reg)
    assert h.is_dead(PANEL) is False


def test_registry_listener_not_duplicated_on_resetup(monkeypatch):
    """Review C HIGH-3b: a second first refresh (re-setup) unsubscribes the
    old listener and leaves exactly one live one."""
    hass, entry, c, subs = _real_coordinator(monkeypatch)
    _run(c.async_config_entry_first_refresh())
    _run(c.async_config_entry_first_refresh())
    assert len(subs) == 2
    (_cb1, unsub1), (_cb2, unsub2) = subs
    unsub1.assert_called_once()
    unsub2.assert_not_called()
    live = [u for _c, u in subs if u in c._unsub_state_listeners]
    assert live == [unsub2]


def _real_async_unload_entry():
    """The production ``async_unload_entry`` from ``__init__.py``, compiled
    and executed on its own (the package ``__init__`` cannot be imported
    under the homeassistant stubs). Its module-level names are supplied;
    the room-entry branch runs verbatim."""
    import ast

    from custom_components.universal_room_automation import const as _c

    init_path = _COORD_SRC.with_name("__init__.py")
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_unload_entry"
    )
    mod = ast.Module(body=[fn], type_ignores=[])
    ns = {
        "__name__": "custom_components.universal_room_automation",
        "__package__": "custom_components.universal_room_automation",
        "_LOGGER": logging.getLogger("camera_stream_health_test_unload"),
        "HomeAssistant": object, "ConfigEntry": object,
        "DOMAIN": DOMAIN,
        "CONF_ENTRY_TYPE": _c.CONF_ENTRY_TYPE,
        "ENTRY_TYPE_INTEGRATION": _c.ENTRY_TYPE_INTEGRATION,
        "ENTRY_TYPE_ZONE_MANAGER": _c.ENTRY_TYPE_ZONE_MANAGER,
        "ENTRY_TYPE_COORDINATOR_MANAGER": _c.ENTRY_TYPE_COORDINATOR_MANAGER,
        "ENTRY_TYPE_ZONE": _c.ENTRY_TYPE_ZONE,
        "PLATFORMS": [], "INTEGRATION_PLATFORMS": [], "Platform": MagicMock(),
    }
    exec(compile(mod, str(init_path), "exec"), ns)
    return ns["async_unload_entry"]


def test_registry_listener_unsubscribed_on_unload(monkeypatch):
    """Review C HIGH-3c: the real room-entry unload releases the listener."""
    from unittest.mock import AsyncMock

    async_unload_entry = _real_async_unload_entry()
    hass, entry, c, subs = _real_coordinator(monkeypatch)
    _run(c.async_config_entry_first_refresh())
    hass.data[DOMAIN][entry.entry_id] = c
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=[])
    assert _run(async_unload_entry(hass, entry)) is True
    _cb, unsub = subs[0]
    unsub.assert_called_once()
    assert c._unsub_state_listeners == []


def test_tick_fail_open_when_tracker_raises():
    """Review C MEDIUM-4: a raise in the stream tick leaves this tick with
    pre-S1 fusion; the room tick itself does not raise."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}

    def _boom(*a, **k):
        raise RuntimeError("tracker exploded")

    r._camera_stream_health.evaluate = _boom
    d = r.tick(T0 + timedelta(seconds=600))
    assert d[STATE_PRESENCE_DETECTED] is True
    assert not r._exclusion_set.is_excluded(PANEL)


def test_missing_state_keeps_stamp():
    """Review C MEDIUM-5: no state (entity left the state machine) is no
    opinion: the stamp is neither set nor cleared."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)  # stamp at T0
    del r.states[PANEL_CAM]
    d = r.tick(T0 + timedelta(seconds=60))
    assert d[STATE_PRESENCE_DETECTED] is True
    r.states[PANEL_CAM] = "unavailable"
    d = r.tick(T0 + timedelta(seconds=120))  # gap 120 s, since still T0
    assert d[STATE_PRESENCE_DETECTED] is False
    assert r._exclusion_set.provenance(PANEL)["camera_stream_dead"] == (
        f"{PANEL_CAM} unavailable since {T0.isoformat()}"
    )


def test_no_opinion_stretch_longer_than_grace_restarts_stamp():
    """Review A LOW-1: `unavailable` must be continuous. A no-opinion gap of
    121 s (> grace) between two `unavailable` readings restarts the clock."""
    r = _Room(_panel_registry())
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    r.states[PANEL_CAM] = "unknown"
    r.tick(T0 + timedelta(seconds=60))
    r.states[PANEL_CAM] = "unavailable"
    d = r.tick(T0 + timedelta(seconds=121))  # 121 s since last reading
    assert d[STATE_PRESENCE_DETECTED] is True
    d = r.tick(T0 + timedelta(seconds=240))  # 119 s into the new stamp
    assert d[STATE_PRESENCE_DETECTED] is True
    d = r.tick(T0 + timedelta(seconds=241))  # 120 s
    assert d[STATE_PRESENCE_DETECTED] is False
    assert r._exclusion_set.provenance(PANEL)["camera_stream_dead"] == (
        f"{PANEL_CAM} unavailable since "
        f"{(T0 + timedelta(seconds=121)).isoformat()}"
    )


def test_stamp_pruned_when_camera_unwatched():
    """Review C MEDIUM-7: an input removed from the room drops its camera's
    stamp; re-added 60 s later it gets a fresh grace."""
    reg = _panel_registry()
    h = CameraInputStreamHealth(ROOM)
    states = {PANEL_CAM: SimpleNamespace(state="unavailable", attributes={})}
    h.evaluate(T0, [PANEL], states.get, lambda: reg)
    h.evaluate(T0 + timedelta(seconds=30), [ZV], states.get, lambda: reg)
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=90), [PANEL], states.get,
                              lambda: reg)
    assert dead == {}
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=209), [PANEL],
                              states.get, lambda: reg)
    assert dead == {}
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=210), [PANEL],
                              states.get, lambda: reg)
    assert dead == {PANEL: (PANEL_CAM, T0 + timedelta(seconds=90))}


def test_is_dead_before_first_tick_and_after_invalidate():
    """Review C MEDIUM-8 + review A LOW-2: the getter is None before any
    tick; after a registry event it keeps the old answer (True for an input
    the room is excluding) until the next tick rebuilds."""
    reg = _panel_registry()
    h = CameraInputStreamHealth(ROOM)
    assert h.is_dead(PANEL) is None
    states = {PANEL_CAM: SimpleNamespace(state="unavailable", attributes={})}
    h.evaluate(T0, [PANEL], states.get, lambda: reg)
    h.evaluate(T0 + timedelta(seconds=120), [PANEL], states.get, lambda: reg)
    assert h.is_dead(PANEL) is True
    h.invalidate()
    assert h.is_dead(PANEL) is True
    assert h.snapshot()["camera_stream_inputs_resolved"] == 1


def test_restored_unavailable_camera_is_no_opinion_no_page(nm_calls):
    """Review B-L1: Frigate in setup retry. HA writes its registry entities
    as `unavailable` with `restored: True`: not loaded = no opinion, so no
    exclusion and no HIGH page however long it lasts."""
    r = _Room(_panel_registry())
    r.states = {
        PANEL: "on",
        PANEL_CAM: ("unavailable", {"restored": True}),
        ZV: "off",
    }
    for s in (0, 120, 1800, 3600):
        d = r.tick(T0 + timedelta(seconds=s))
        assert d[STATE_PRESENCE_DETECTED] is True
    _drain(r)
    assert nm_calls == {"page": [], "recover": []}
    assert r.camera_input_stream_dead(PANEL) is False
    # Once loaded and really unavailable, the grace starts then.
    r.states[PANEL_CAM] = "unavailable"
    r.tick(T0 + timedelta(seconds=3630))
    d = r.tick(T0 + timedelta(seconds=3750))
    assert d[STATE_PRESENCE_DETECTED] is False


def test_input_removed_mid_episode_no_recovery_nm():
    """Review A LOW-3: a paged input removed from the room is dropped
    silently, no "counts again" message."""
    reg = _panel_registry()
    h = CameraInputStreamHealth(ROOM)
    states = {PANEL_CAM: SimpleNamespace(state="unavailable", attributes={})}
    h.evaluate(T0, [PANEL, ZV], states.get, lambda: reg)
    _d, page, _r = h.evaluate(T0 + timedelta(seconds=1800), [PANEL, ZV],
                              states.get, lambda: reg)
    assert [p[0] for p in page] == [PANEL]
    _d, _p, recover = h.evaluate(T0 + timedelta(seconds=1830), [ZV],
                                 states.get, lambda: reg)
    assert recover == []
    _d, _p, recover = h.evaluate(T0 + timedelta(seconds=1860), [ZV],
                                 states.get, lambda: reg)
    assert recover == []


def test_camera_override_not_held_by_dead_stream_input():
    """Review B-M1 repro: camera.up_hallway_panel added to Upstairs
    Hallway's cameras, so the v3.5.1 override reads the frozen panel person
    sensor that is also a presence input. Once its stream is dead past the
    grace the override cannot hold the room either."""
    r = _Room(_panel_registry(), override=(PANEL,))
    r.states = {PANEL: "on", PANEL_CAM: "unavailable", ZV: "off"}
    r.tick(T0)
    assert r.override(T0) == (True, "camera")  # before the grace: holds
    r.tick(T0 + timedelta(seconds=120))
    assert r.override(T0 + timedelta(seconds=120)) == (False, None)


def test_camera_override_still_holds_with_p22_stuck_input_live_stream():
    """Review D-M1 repro (Study A shape): the panel person sensor is a
    presence input AND its camera is in the room's cameras. A person seated
    >= 4 h keeps it `on`, so P22 excludes it from fusion; the camera stream
    is healthy. The override must still hold the room, as on develop: only
    the camera_stream_dead client narrows the override."""
    r = _Room(_panel_registry(), override=(PANEL,))
    r._p22_stuck_sensor_set = lambda now: {PANEL}
    r._sensor_on_since = {PANEL: T0 - timedelta(hours=5)}
    r.states = {PANEL: "on", PANEL_CAM: "streaming", ZV: "off"}
    r.tick(T0)
    r.tick(T0 + timedelta(seconds=150))
    assert r._exclusion_set.clients_for(PANEL) == {"p22_continuous"}
    assert r.override(T0 + timedelta(seconds=150)) == (True, "camera")


def test_camera_override_sensor_outside_inputs_watched_not_paged(nm_calls):
    """Review B-M1: an override person sensor that is NOT a configured room
    input is watched too (excluded once its camera is dead), but never paged
    and not shown on the sensor (it is not a configured input)."""
    r = _Room(_panel_registry(), motion=(ZV,), presence=(), override=(PANEL,))
    r.states = {PANEL: "on", PANEL_CAM: "streaming", ZV: "off"}
    r.tick(T0)
    assert r.override(T0) == (True, "camera")  # discriminator: live stream
    r.states[PANEL_CAM] = "unavailable"
    r.tick(T0 + timedelta(seconds=30))
    r.tick(T0 + timedelta(seconds=150))
    assert r.override(T0 + timedelta(seconds=150)) == (False, None)
    assert r.camera_input_stream_dead(PANEL) is True
    r.tick(T0 + timedelta(seconds=30 + 1800))
    _drain(r)
    assert nm_calls["page"] == []
    assert r.camera_stream_health_snapshot() == {
        "camera_stream_dead_inputs": {},
        "camera_stream_inputs_resolved": 0,
    }


def test_registry_getter_raise_fails_open():
    """Review C LOW: a raising registry getter -> every input unresolved
    (registry_error), nothing excluded, no raise."""
    h = CameraInputStreamHealth(ROOM)

    def _boom():
        raise RuntimeError("registry down")

    states = {PANEL_CAM: SimpleNamespace(state="unavailable", attributes={})}
    h.evaluate(T0, [PANEL], states.get, _boom)
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=600), [PANEL],
                              states.get, _boom)
    assert dead == {}
    assert h.is_dead(PANEL) is None


def test_state_getter_raise_is_no_opinion():
    """Review C LOW: a raising state getter is no state: no exclusion, and
    an existing stamp survives."""
    reg = _panel_registry()
    h = CameraInputStreamHealth(ROOM)
    ok = {PANEL_CAM: SimpleNamespace(state="unavailable", attributes={})}

    def _boom(_eid):
        raise RuntimeError("state machine hiccup")

    h.evaluate(T0, [PANEL], ok.get, lambda: reg)
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=60), [PANEL], _boom,
                              lambda: reg)
    assert dead == {}
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=120), [PANEL], ok.get,
                              lambda: reg)
    assert dead == {PANEL: (PANEL_CAM, T0)}


def test_unresolved_warn_silent_for_non_camera_and_partial_rooms(caplog):
    """Review C LOW: no WARNING for a room without camera-derived inputs,
    nor for a room where at least one camera-derived input resolves."""
    two_cam = _entry("camera.other_a", "dev_other")
    reg = _panel_registry(extra=(
        _entry("binary_sensor.other_person_occupancy", "dev_other"),
        two_cam, _entry("camera.other_b", "dev_other"),
    ))
    with caplog.at_level(logging.WARNING):
        CameraInputStreamHealth(ROOM).evaluate(T0, [ZV], lambda e: None,
                                               lambda: reg)
        CameraInputStreamHealth(ROOM).evaluate(
            T0, [PANEL, "binary_sensor.other_person_occupancy"],
            lambda e: None, lambda: reg,
        )
    assert not [r for r in caplog.records
                if "no single camera entity" in r.message]


def test_grace_read_from_const(monkeypatch):
    """Review C LOW: the grace comes from CAMERA_INPUT_STREAM_DEAD_GRACE_S."""
    monkeypatch.setattr(_csh._const, "CAMERA_INPUT_STREAM_DEAD_GRACE_S", 300.0)
    reg = _panel_registry()
    h = CameraInputStreamHealth(ROOM)
    states = {PANEL_CAM: SimpleNamespace(state="unavailable", attributes={})}
    for s in (0, 30, 60, 90, 120, 150, 180, 210, 240, 270):
        dead, _p, _r = h.evaluate(T0 + timedelta(seconds=s), [PANEL],
                                  states.get, lambda: reg)
        assert dead == {}
    dead, _p, _r = h.evaluate(T0 + timedelta(seconds=300), [PANEL],
                              states.get, lambda: reg)
    assert dead == {PANEL: (PANEL_CAM, T0)}


def test_sensor_surface_degrades_when_snapshot_raises():
    """Review C LOW (sn.exc-unguarded): a raising snapshot leaves the two
    attributes out and the rest of the sensor's attributes intact."""
    try:
        from custom_components.universal_room_automation import sensor as sen
    except Exception:  # noqa: BLE001
        pytest.skip("sensor.py not importable in this environment")
    hass = MagicMock()
    hass.states.get = lambda eid: None
    coord = MagicMock()
    coord.entry.data = {"presence_sensors": [PANEL], "motion_sensors": [ZV]}
    coord.entry.options = {}
    coord.hass = hass
    coord._chattering_entities = set()
    coord._chatter_detector = None
    coord._dutycycle_notify_active = None
    coord._actuator_reconciler = None

    def _boom():
        raise RuntimeError("snapshot broken")

    coord.camera_stream_health_snapshot = _boom
    s = object.__new__(sen.UnavailableEntitiesSensor)
    s.coordinator = coord
    attrs = s.extra_state_attributes
    assert "camera_stream_dead_inputs" not in attrs
    assert "camera_stream_inputs_resolved" not in attrs
    assert attrs  # the rest still built

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

from custom_components.universal_room_automation.const import (
    STATE_MOTION_DETECTED,
    STATE_PRESENCE_DETECTED,
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


def _tick_slice():
    src = _COORD_SRC.read_text(encoding="utf-8")
    start = src.index("        self._exclusion_set.reset_tick()\n")
    end_marker = "        data[STATE_PRESENCE_DETECTED] = presence_detected\n"
    end = src.index(end_marker, start) + len(end_marker)
    lines = []
    for ln in src[start:end].splitlines():
        lines.append(ln[8:] if ln.startswith(" " * 8) else ln.strip())
    return compile("\n".join(lines), str(_COORD_SRC), "exec")


_TICK = _tick_slice()


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

    def __init__(self, registry, *, motion=(ZV,), presence=(PANEL,)):
        self.states: dict[str, str] = {}
        self.registry = registry
        self.motion = list(motion)
        self.presence = list(presence)
        self.tasks: list = []
        _ROOMS.append(self)
        self.hass = MagicMock()
        self.hass.states.get = self._get_state

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
        ):
            fn = getattr(UniversalRoomCoordinator, name)
            setattr(self, name, fn.__get__(self, type(self)))

    # HA seam + quiet writers -------------------------------------------
    def _get_state(self, eid):
        v = self.states.get(eid)
        return SimpleNamespace(state=v) if v is not None else None

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
            "occupancy_sensors": [],
            "_LOGGER": logging.getLogger("camera_stream_health_test"),
            "STATE_MOTION_DETECTED": STATE_MOTION_DETECTED,
            "STATE_PRESENCE_DETECTED": STATE_PRESENCE_DETECTED,
        }
        exec(_TICK, ns)
        return ns["data"]

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
    d = r.tick(T0 + timedelta(seconds=1200))
    assert d[STATE_PRESENCE_DETECTED] is True  # no opinion this tick
    r.states[PANEL_CAM] = "unavailable"
    d = r.tick(T0 + timedelta(seconds=1250))  # 250 s after the 1000 stamp
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

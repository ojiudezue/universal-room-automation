"""Tests for the FRIGATE-FLEET-DARK tripwire + Camera Input Dark binary
sensor + presence α-veto suppression (PLANNING_frigate_down_tripwire.md
Rev 2).

Covers D1 and D3 acceptance criteria plus wire-in anchors and the
discriminating observations enumerated in the plan §6.

Reuses the mock bootstrap pattern from
``test_optimization_coordinator.py`` so the real production modules
import under pytest without a running Home Assistant.
"""
from __future__ import annotations

import inspect
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock


def _start_of_local_day():
    now = datetime.now()
    return datetime(now.year, now.month, now.day)


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "CALLBACK_TYPE": type(None),
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
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda *a, **k: (lambda: None),
        "async_call_later": lambda *a, **k: (lambda: None),
        "async_track_time_change": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
        "async_dispatcher_send": lambda *a, **k: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
        "CoordinatorEntity": type(
            "CoordinatorEntity", (),
            {"__class_getitem__": classmethod(lambda cls, item: cls)},
        ),
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
        "start_of_local_day": _start_of_local_day,
    },
    "homeassistant.components": {},
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": MagicMock(),
    },
    "homeassistant.components.select": {
        "SelectEntity": type("SelectEntity", (), {}),
    },
    "homeassistant.components.person": {"DOMAIN": "person"},
    "homeassistant.components.device_tracker": {"DOMAIN": "device_tracker"},
    "homeassistant.components.zone": {"DOMAIN": "zone"},
    "homeassistant.helpers.area_registry": {"async_get": _mock_cls()},
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        if name not in sys.modules:
            sys.modules[name] = attrs


@pytest.fixture(autouse=True)
def _evict_ura_stubs():
    """Match the pattern from test_optimization_coordinator.py."""
    for _modname in list(sys.modules):
        if (
            _modname == "custom_components.universal_room_automation"
            or _modname.startswith(
                "custom_components.universal_room_automation."
            )
        ):
            del sys.modules[_modname]
    cc_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..",
                     "custom_components")
    )
    cc = sys.modules.get("custom_components")
    if cc is None:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [cc_dir]
        sys.modules["custom_components"] = cc
    else:
        existing_path = list(getattr(cc, "__path__", []) or [])
        if cc_dir not in existing_path:
            existing_path.append(cc_dir)
            cc.__path__ = existing_path
    yield


# ---------------------------------------------------------------------------
# Mock HASS primitives (minimal subset of test_optimization_coordinator.py).
# ---------------------------------------------------------------------------


class _MockState:
    def __init__(self, state):
        self.state = state


class _MockEntry:
    def __init__(self, entry_id, entry_type, data=None, options=None):
        self.entry_id = entry_id
        self.data = {"entry_type": entry_type, **(data or {})}
        self.options = options or {}


class _MockConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, _domain):
        return list(self._entries)


class _MockServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, *a, **k):
        self.calls.append((a, k))


class _MockStates:
    def __init__(self):
        self._states = {}

    def get(self, eid):
        return self._states.get(eid)

    def set(self, eid, state):
        self._states[eid] = _MockState(state)


class _MockHass:
    def __init__(self):
        self.data = {"universal_room_automation": {}}
        self.config_entries = _MockConfigEntries([])
        self.services = _MockServices()
        self.states = _MockStates()
        self.bus = MagicMock()

    def async_create_task(self, coro):
        try:
            coro.close()
        except Exception:
            pass


class _FakeCameraInfo:
    def __init__(self, person_count_sensor):
        self.person_count_sensor = person_count_sensor
        self.platform = "frigate"


class _FakeCameraManager:
    def __init__(self, sensors):
        self._sensors = list(sensors)

    def get_all_frigate_cameras(self):
        return [_FakeCameraInfo(s) for s in self._sensors]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _coord(sensors=None, status2=None, boot_offset_s=10_000):
    """Build an OptimizationCoordinator wired to a fake camera_manager.

    ``boot_offset_s`` backdates ``_camera_input_dark_boot_ref`` so by
    default the tripwire is past BOOT_SETTLE_S (180s) — tests that
    want to assert boot suppression pass a small offset explicitly.
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from homeassistant.util import dt as _dt
    hass = _MockHass()
    hass.data["universal_room_automation"]["camera_manager"] = (
        _FakeCameraManager(sensors or [])
    )
    coord = OptimizationCoordinator(hass)
    coord._camera_input_dark_boot_ref = (
        _dt.utcnow() - timedelta(seconds=boot_offset_s)
    )
    if status2 is not None:
        hass.states.set("sensor.frigate_status_2", status2)
    for s in sensors or []:
        # Default to "0" (available/empty house) unless set below.
        hass.states.set(s, "0")
    return coord, hass


def _set_all(hass, sensors, state):
    for s in sensors:
        hass.states.set(s, state)


# ---------------------------------------------------------------------------
# D1 — camera_input_dark evaluator
# ---------------------------------------------------------------------------


def test_camera_input_dark_fires_on_fleet_unavailable():
    """24/24 unavailable, dwell satisfied, past boot settle → one finding."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    coord, hass = _coord(sensors=sensors, status2="running")
    _set_all(hass, sensors, "unavailable")

    # First tick arms the dwell anchor; subsequent tick with the anchor
    # back-dated past DWELL fires once.
    assert coord._evaluate_camera_input_dark_dimension() == []
    from homeassistant.util import dt as _dt
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=400)
    out = coord._evaluate_camera_input_dark_dimension()
    assert len(out) == 1
    f = out[0]
    assert f.dedup_key == ("camera_input_dark", "fleet")
    assert f.payload["denominator"] == 24
    assert f.payload["unavailable_count"] == 24
    assert f.payload["fraction"] == 1.0
    # Latched — subsequent ticks must not re-fire.
    assert coord._evaluate_camera_input_dark_dimension() == []


def test_camera_input_dark_single_flap_noop():
    """1/24 unavailable (fraction 0.042 << 0.75) → zero findings."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    coord, hass = _coord(sensors=sensors, status2="running")
    hass.states.set(sensors[0], "unavailable")
    # Even if the sensor stayed "unavailable" for an hour, fraction is
    # below threshold and status_2 is nominal → no finding.
    from homeassistant.util import dt as _dt
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=3600)
    assert coord._evaluate_camera_input_dark_dimension() == []
    assert coord._camera_input_dark_fired is False


def test_camera_input_dark_hysteresis_no_reflap_refire():
    """Fire once, 18/24 flap sits above CLEAR → no re-fire, no clear."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    coord, hass = _coord(sensors=sensors, status2="running")
    _set_all(hass, sensors, "unavailable")
    from homeassistant.util import dt as _dt
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=400)
    assert len(coord._evaluate_camera_input_dark_dimension()) == 1
    assert coord._camera_input_dark_fired is True

    # Partial recovery to 18/24 unavailable → fraction 0.75 at the fire
    # threshold, which is above CLEAR (0.25) → latch holds, no clear,
    # and (because latch is set) no re-fire.
    for s in sensors[:6]:
        hass.states.set(s, "0")
    assert coord._evaluate_camera_input_dark_dimension() == []
    assert coord._camera_input_dark_fired is True

    # Full recovery → clear.
    _set_all(hass, sensors, "0")
    assert coord._evaluate_camera_input_dark_dimension() == []
    assert coord._camera_input_dark_fired is False


def test_camera_input_dark_boot_suppressed():
    """Within BOOT_SETTLE_S since coordinator construction → no fire."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    coord, hass = _coord(
        sensors=sensors, status2="running", boot_offset_s=5,
    )
    _set_all(hass, sensors, "unavailable")
    from homeassistant.util import dt as _dt
    # Attempt to force dwell completion — boot-settle must beat it.
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=400)
    assert coord._evaluate_camera_input_dark_dimension() == []
    # Boot gate also resets the dwell anchor so the first post-settle
    # tick does not instant-fire.
    assert coord._camera_input_dark_since is None


def test_camera_input_dark_zero_denominator_inert():
    """No Frigate cameras configured → inert, one log, no finding."""
    coord, hass = _coord(sensors=[], status2=None)
    # Multiple ticks: only one inert log recorded.
    assert coord._evaluate_camera_input_dark_dimension() == []
    assert coord._camera_input_dark_inert_logged is True
    assert coord._evaluate_camera_input_dark_dimension() == []
    assert coord._camera_input_dark_last_denominator == 0


def test_camera_input_dark_empty_house_available_noop():
    """24/24 AVAILABLE but all reading '0' → zero findings. Discriminates
    'quiet' from 'dark' — the plan §6 explicit discriminator."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    coord, hass = _coord(sensors=sensors, status2="running")
    _set_all(hass, sensors, "0")
    from homeassistant.util import dt as _dt
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=3600)
    assert coord._evaluate_camera_input_dark_dimension() == []
    assert coord._camera_input_dark_fired is False
    assert coord._camera_input_dark_last_fraction == 0.0


def test_camera_input_dark_frigate_down_protect_up_fires():
    """Fleet all unavailable (Frigate down, Protect binaries up live on
    a different path) → D1 fires on fraction=1.0 regardless of Protect
    state; `camera_total` sourcing lives in camera_census (unchanged)."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(10)]
    coord, hass = _coord(sensors=sensors, status2="running")
    _set_all(hass, sensors, "unavailable")
    from homeassistant.util import dt as _dt
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=400)
    out = coord._evaluate_camera_input_dark_dimension()
    assert len(out) == 1
    assert out[0].payload["trigger_reason"] == "fleet_unavailable"


def test_camera_input_dark_frigate_status_2_or_trigger():
    """0/24 unavailable but sensor.frigate_status_2 unavailable → D1 fires
    on the OR-trigger."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    coord, hass = _coord(sensors=sensors, status2="unavailable")
    _set_all(hass, sensors, "0")
    from homeassistant.util import dt as _dt
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=400)
    out = coord._evaluate_camera_input_dark_dimension()
    assert len(out) == 1
    assert out[0].payload["trigger_reason"] == "frigate_status_2_down"
    assert out[0].payload["fraction"] == 0.0


def test_camera_input_dark_kill_switch(monkeypatch):
    """FIRE_THRESHOLD > 1.0 disables the fire path (kill switch)."""
    from custom_components.universal_room_automation.domain_coordinators import (
        optimization as opt_mod,
    )
    sensors = [f"sensor.cam{i}_person_count" for i in range(10)]
    coord, hass = _coord(sensors=sensors, status2="running")
    _set_all(hass, sensors, "unavailable")
    from homeassistant.util import dt as _dt
    coord._camera_input_dark_since = _dt.utcnow() - timedelta(seconds=400)
    monkeypatch.setattr(
        opt_mod, "CAMERA_INPUT_DEGRADED_FIRE_THRESHOLD", 2.0,
    )
    assert coord._evaluate_camera_input_dark_dimension() == []


# ---------------------------------------------------------------------------
# A-HIGH-1 / B1 — DELIVERY: camera_input_dark MUST reach NM with the
# default (empty) allowlist. Drives the REAL _notify_if_severe through
# should_defer_high_to_digest. A regression that re-closes the defer
# gate (removing the dedup_key exemption) turns this test red.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_camera_input_dark_pages_nm_despite_default_allowlist():
    """DELIVERY: a camera_input_dark high finding MUST call nm.async_notify
    with the default (empty) allowlist — bypasses the digest-defer gate
    for this specific dedup_key."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass = _MockHass()
    hass.data["universal_room_automation"]["camera_manager"] = (
        _FakeCameraManager([])
    )
    # NM present with the real `async_notify` surface mocked.
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    hass.data["universal_room_automation"]["notification_manager"] = nm
    # CM entry with the DEFAULT (empty) allowlist — this is the live config.
    entries = [_MockEntry("cm", "coordinator_manager")]
    hass.config_entries = _MockConfigEntries(entries)
    coord = OptimizationCoordinator(hass)

    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.SENSOR_HEALTH,
        severity="high", confidence=0.95, score=0.0,
        description="camera input dark",
        payload={"kind": "camera_input_dark", "denominator": 24},
        dedup_key=("camera_input_dark", "fleet"),
    )
    await coord._notify_if_severe(f)
    assert nm.async_notify.await_count == 1, (
        "camera_input_dark must bypass the HIGH→digest defer gate "
        "with the default (empty) allowlist"
    )


@pytest.mark.asyncio
async def test_other_sensor_health_high_still_defers_by_default():
    """Discriminator: a vanilla sensor_health HIGH (different dedup_key
    namespace) still defers to digest with the default allowlist, so we
    did NOT allowlist all of sensor_health."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass = _MockHass()
    hass.data["universal_room_automation"]["camera_manager"] = (
        _FakeCameraManager([])
    )
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    hass.data["universal_room_automation"]["notification_manager"] = nm
    entries = [_MockEntry("cm", "coordinator_manager")]
    hass.config_entries = _MockConfigEntries(entries)
    coord = OptimizationCoordinator(hass)

    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.SENSOR_HEALTH,
        severity="high", confidence=0.95, score=0.0,
        description="sensor_health stuck",
        payload={},
        dedup_key=("sensor_health", "kitchen", "sensor.kitchen_temp"),
    )
    await coord._notify_if_severe(f)
    assert nm.async_notify.await_count == 0, (
        "sensor_health HIGH must still defer to digest by default"
    )


# ---------------------------------------------------------------------------
# WIRE-IN ANCHOR: evaluator must be registered in the cycle.
# ---------------------------------------------------------------------------


def test_camera_input_dark_evaluator_registered():
    """WIRE-IN ANCHOR: `camera_input_dark` is in the evaluator table.

    Mutation drill: commenting out the tuple entry at optimization.py
    (search string below) causes this test to go red.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        optimization as opt_mod,
    )
    src = inspect.getsource(opt_mod)
    assert (
        '("camera_input_dark",\n             self._evaluate_camera_input_dark_dimension)'
        in src
        or '("camera_input_dark", self._evaluate_camera_input_dark_dimension)'
        in src
    ), "camera_input_dark evaluator is not registered in the cycle"


# ---------------------------------------------------------------------------
# D3-a — binary_sensor registration + mirror semantics.
# ---------------------------------------------------------------------------


def test_camera_input_degraded_binary_sensor_registered():
    """WIRE-IN ANCHOR: CameraInputDegradedBinarySensor is added to the
    CM-entry entity list.

    Mutation drill: removing the registration line in
    ``binary_sensor.async_setup_entry``'s coordinator_binary list
    causes this test to go red.
    """
    from custom_components.universal_room_automation import binary_sensor as bs_mod
    src = inspect.getsource(bs_mod)
    assert "CameraInputDegradedBinarySensor(hass, entry)" in src, (
        "CameraInputDegradedBinarySensor is not registered under the CM entry"
    )
    assert hasattr(bs_mod, "CameraInputDegradedBinarySensor")


def test_camera_input_degraded_binary_sensor_mirrors_degraded_mode():
    """Binary sensor state tracks CensusResult.house.degraded_mode."""
    from custom_components.universal_room_automation.binary_sensor import (
        CameraInputDegradedBinarySensor,
    )
    hass = _MockHass()
    entry = _MockEntry("cm", "coordinator_manager")
    # No census → False (fail-safe diagnostic).
    s = CameraInputDegradedBinarySensor(hass, entry)
    assert s.is_on is False

    # Install a fake census with degraded_mode True.
    class _House:
        degraded_mode = True

    class _Result:
        house = _House()

    class _Census:
        last_result = _Result()
        _face_producer_health_reason = "frigate_down"

    hass.data["universal_room_automation"]["census"] = _Census()
    assert s.is_on is True

    # Flip to healthy.
    _House.degraded_mode = False
    assert s.is_on is False


def test_camera_input_degraded_binary_sensor_attributes():
    """Attribute payload includes fraction/count/denominator/latch state."""
    from custom_components.universal_room_automation.binary_sensor import (
        CameraInputDegradedBinarySensor,
    )
    hass = _MockHass()
    entry = _MockEntry("cm", "coordinator_manager")
    s = CameraInputDegradedBinarySensor(hass, entry)

    # Install a fake optimizer with the diagnostic fields populated.
    class _Opt:
        _camera_input_dark_last_fraction = 0.83
        _camera_input_dark_last_unavailable = 20
        _camera_input_dark_last_denominator = 24
        _camera_input_dark_last_affected = [
            "sensor.cam0_person_count", "sensor.cam1_person_count",
        ]
        _camera_input_dark_last_status2_state = "unavailable"
        _camera_input_dark_fired = True
        from homeassistant.util import dt as _dt
        _camera_input_dark_boot_ref = _dt.utcnow()

    class _CM:
        coordinators = {"optimization": _Opt()}

    hass.data["universal_room_automation"]["coordinator_manager"] = _CM()
    attrs = s.extra_state_attributes
    assert attrs["fraction_unavailable"] == 0.83
    assert attrs["unavailable_count"] == 20
    assert attrs["denominator"] == 24
    assert attrs["frigate_status_2_state"] == "unavailable"
    assert attrs["nm_latch_fired"] is True
    assert len(attrs["affected_entities"]) == 2


# ---------------------------------------------------------------------------
# D3-b — presence α-veto suppression when camera input degraded.
# ---------------------------------------------------------------------------


def test_presence_alpha_veto_suppressed_when_camera_dark():
    """α-veto does NOT transition to AWAY while camera_input_degraded.

    Mutation drill: deleting the `if camera_input_degraded: return None`
    branch in `StateInferenceEngine.infer()` causes this test to go red.
    """
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        StateInferenceEngine, HouseState,
    )
    engine = StateInferenceEngine(sleep_start_hour=22, sleep_end_hour=6)
    # Noon so no sleep-hour interactions.
    now = datetime(2026, 10, 9, 12, 0, 0)
    result = engine.infer(
        census_count=1,  # BLE-inflated (stale phone) but path β-safe here
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,  # not nobody-home branch
        unidentified_count=0,
        face_recognized_count=0,
        all_tracked_persons_away=True,
        now=now,
        camera_input_degraded=True,
    )
    assert result is None, (
        "α-veto must be suppressed when camera input is dark"
    )
    assert engine._veto_path == "none"


def test_presence_alpha_veto_fires_when_camera_healthy():
    """Discriminator: same inputs, healthy camera → α-veto DOES fire.

    This paired test proves the gate reads `camera_input_degraded`,
    not something coincidental.
    """
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        StateInferenceEngine, HouseState,
    )
    engine = StateInferenceEngine(sleep_start_hour=22, sleep_end_hour=6)
    now = datetime(2026, 10, 9, 12, 0, 0)
    result = engine.infer(
        census_count=1,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,
        unidentified_count=0,
        face_recognized_count=0,
        all_tracked_persons_away=True,
        now=now,
        camera_input_degraded=False,
    )
    assert result == HouseState.AWAY
    assert engine._veto_path == "active"


def test_presence_handles_census_degraded_mode_payload_key():
    """`_handle_census_update` captures `degraded_mode` off the signal
    payload into `_census_degraded_mode`.

    Mutation drill: removing the try-block that reads the key from the
    payload causes this test to go red.
    """
    import inspect as _insp
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as presence_mod,
    )
    src = _insp.getsource(presence_mod.PresenceCoordinator._handle_census_update)
    assert "degraded_mode" in src, (
        "_handle_census_update does not read degraded_mode from payload"
    )
    assert "_census_degraded_mode" in src


def test_census_signal_payload_includes_degraded_mode():
    """WIRE-IN ANCHOR: SIGNAL_CENSUS_UPDATED payload carries
    `degraded_mode` (producer side)."""
    import inspect as _insp
    from custom_components.universal_room_automation import camera_census as cc_mod
    src = _insp.getsource(cc_mod)
    assert '"degraded_mode"' in src
    # Confirm it's inside the SIGNAL_CENSUS_UPDATED dispatch block —
    # look for both markers in the same window.
    # Co-locate with the face_recognized_count payload key — the known
    # marker inside the dispatch dict literal.
    i_face = src.find('"face_recognized_count": len(_face_recognized)')
    assert i_face >= 0
    i_degraded_in_window = src.find(
        '"degraded_mode"', i_face, i_face + 2000,
    )
    assert i_degraded_in_window >= 0, (
        "degraded_mode not present inside SIGNAL_CENSUS_UPDATED block"
    )

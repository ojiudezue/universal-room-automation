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


def test_camera_input_dark_mid_band_resets_dwell_anchor():
    """A-MED-2 LOW-1: a mid-band tick (fraction between CLEAR and FIRE,
    status_2 nominal) must reset `_since` so an above-CLEAR flap can't
    accumulate false dwell."""
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    coord, hass = _coord(sensors=sensors, status2="running")
    _set_all(hass, sensors, "unavailable")
    # Arm the dwell anchor on dark.
    coord._evaluate_camera_input_dark_dimension()
    assert coord._camera_input_dark_since is not None
    # Partial recovery to 10/24 unavailable (fraction 0.417): below FIRE
    # 0.75, above CLEAR 0.25 → not degraded_now.
    for s in sensors[:14]:
        hass.states.set(s, "0")
    coord._evaluate_camera_input_dark_dimension()
    assert coord._camera_input_dark_since is None, (
        "mid-band must reset `_since` (LOW-1)"
    )


def test_camera_input_dark_exempt_from_cap_findings():
    """A-MED-2 LOW-2: _cap_findings exempts the camera_input_dark
    one-shot (same posture as META). A flood of other high findings
    cannot drop the fleet-dark NM."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_MAX_FINDINGS_PER_CYCLE,
    )
    hass = _MockHass()
    coord = OptimizationCoordinator(hass)
    # Build a flood that EXCEEDS the cap, with ONE camera_input_dark
    # at the bottom of the list (so a naive sort by severity would drop
    # it if it weren't exempt).
    flood = []
    for i in range(OPTIMIZER_MAX_FINDINGS_PER_CYCLE + 50):
        flood.append(OptimizationFinding(
            timestamp="t", level="room", target_id=f"r{i}",
            dimension=OptimizationDimension.SENSOR_HEALTH,
            severity="high", confidence=0.9, score=0.0,
            description="flood",
            dedup_key=("sensor_health", f"r{i}"),
        ))
    cid_finding = OptimizationFinding(
        timestamp="t", level="house", target_id="house",
        dimension=OptimizationDimension.SENSOR_HEALTH,
        severity="high", confidence=0.95, score=0.0,
        description="fleet dark",
        dedup_key=("camera_input_dark", "fleet"),
    )
    flood.append(cid_finding)
    capped = coord._cap_findings(flood)
    assert cid_finding in capped, (
        "camera_input_dark must survive _cap_findings (LOW-2 exemption)"
    )


def test_camera_input_dark_dwell_constant_below_cycle():
    """A-MED-2: DWELL < 300s cycle so a two-cycle outage reliably trips."""
    from custom_components.universal_room_automation.const import (
        CAMERA_INPUT_DEGRADED_DWELL_S,
    )
    assert CAMERA_INPUT_DEGRADED_DWELL_S < 300


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


def test_camera_input_degraded_binary_sensor_mirrors_narrow_latch():
    """Binary sensor state tracks the NARROW
    PersonCensus._camera_input_dark_latched — NOT raw degraded_mode.

    This encodes B2's one-definition-of-dark: a Protect-only house
    reads OFF even though CensusResult.degraded_mode would be True.
    """
    from custom_components.universal_room_automation.binary_sensor import (
        CameraInputDegradedBinarySensor,
    )
    hass = _MockHass()
    entry = _MockEntry("cm", "coordinator_manager")
    # No census → False (fail-safe diagnostic).
    s = CameraInputDegradedBinarySensor(hass, entry)
    assert s.is_on is False

    class _Census:
        _camera_input_dark_latched = True
        _face_producer_health_reason = "frigate_down"

    hass.data["universal_room_automation"]["census"] = _Census()
    assert s.is_on is True

    # Flip to healthy — latch clears.
    _Census._camera_input_dark_latched = False
    assert s.is_on is False


def test_binary_sensor_off_on_protect_only_house():
    """DISCRIMINATOR for B2: a Protect-only house has
    CensusResult.degraded_mode permanently True but the NARROW latch
    stays False (denominator = 0). The binary sensor reads OFF."""
    from custom_components.universal_room_automation.binary_sensor import (
        CameraInputDegradedBinarySensor,
    )
    hass = _MockHass()
    entry = _MockEntry("cm", "coordinator_manager")
    s = CameraInputDegradedBinarySensor(hass, entry)

    class _House:
        degraded_mode = True  # Protect-only census marks True...

    class _Result:
        house = _House()

    class _Census:
        last_result = _Result()
        # ...but the NARROW latch is False because denominator == 0.
        _camera_input_dark_latched = False
        _face_producer_health_reason = "inert_no_frigate"

    hass.data["universal_room_automation"]["census"] = _Census()
    assert s.is_on is False, (
        "Protect-only house must read OFF — degraded_mode is NOT the "
        "trust gate"
    )


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


def test_presence_beta_still_reaches_away_while_degraded_outdoor_only():
    """A-HIGH-2/B3: degraded fleet + outdoor-only zone + all away → path
    β STILL reaches AWAY. This proves the α-gate is a SKIP, not a
    short-circuit — the engine falls through to β, GUEST exit, SLEEP."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        StateInferenceEngine, HouseState,
    )
    engine = StateInferenceEngine(sleep_start_hour=22, sleep_end_hour=6)
    now = datetime(2026, 10, 9, 12, 0, 0)
    result = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,  # outdoor-only pool zone, say
        unidentified_count=0,
        face_recognized_count=0,
        all_tracked_persons_away=True,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,  # indoor is clear
        grace_elapsed_for_lost_away=True,
        lost_away_persons_present=False,
        sleep_exempt_state=False,
        now=now,
        camera_input_degraded=True,
    )
    assert result == HouseState.AWAY, (
        "path β must still reach AWAY even while camera input is dark"
    )
    assert engine._veto_path.startswith("lost_admitted") or (
        engine._veto_path == "lost_admitted"
    )


def test_presence_guest_exit_still_works_while_degraded():
    """A-HIGH-2/B3: GUEST → HOME_* exit must still fire when the fleet is
    dark. The gate used to `return None`, which stalled this exit."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        StateInferenceEngine, HouseState,
    )
    engine = StateInferenceEngine(sleep_start_hour=22, sleep_end_hour=6)
    now = datetime(2026, 10, 9, 12, 0, 0)
    result = engine.infer(
        census_count=1,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,
        unidentified_count=0,
        face_recognized_count=0,
        guest_gate_armed=False,  # guest signal cleared
        all_tracked_persons_away=True,
        now=now,
        camera_input_degraded=True,
    )
    # Should be a time-based HOME state, NOT None, NOT AWAY, NOT GUEST.
    assert result not in (None, HouseState.AWAY, HouseState.GUEST)


def test_presence_degraded_flip_triggers_inference():
    """B4: a dark→healthy transition on the signal payload triggers
    inference immediately (change-detection block in
    _handle_census_update picks up the camera_input_dark key)."""
    import inspect as _insp
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as presence_mod,
    )
    src = _insp.getsource(presence_mod.PresenceCoordinator._handle_census_update)
    assert "old_camera_input_dark" in src
    assert "old_camera_input_dark != self._census_camera_input_dark" in src


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


def test_presence_handles_census_camera_input_dark_payload_key():
    """`_handle_census_update` captures the NARROW `camera_input_dark`
    key off the signal payload into `_census_camera_input_dark`."""
    import inspect as _insp
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as presence_mod,
    )
    src = _insp.getsource(presence_mod.PresenceCoordinator._handle_census_update)
    assert '"camera_input_dark"' in src
    assert "_census_camera_input_dark" in src


def test_census_signal_payload_includes_narrow_camera_input_dark():
    """WIRE-IN ANCHOR: SIGNAL_CENSUS_UPDATED payload carries the NARROW
    `camera_input_dark` key (producer side) — not just degraded_mode."""
    import inspect as _insp
    from custom_components.universal_room_automation import camera_census as cc_mod
    src = _insp.getsource(cc_mod)
    assert '"camera_input_dark": bool(' in src
    i_face = src.find('"face_recognized_count": len(_face_recognized)')
    assert i_face >= 0
    i_dark_in_window = src.find(
        '"camera_input_dark"', i_face, i_face + 2000,
    )
    assert i_dark_in_window >= 0, (
        "camera_input_dark not present inside SIGNAL_CENSUS_UPDATED block"
    )


# ---------------------------------------------------------------------------
# A-MED-1 / B2 — ONE DEFINITION OF DARK (shared helper, Protect-only off).
# ---------------------------------------------------------------------------


def test_compute_camera_input_dark_frame_zero_denominator_is_false():
    """Protect-only (no Frigate cameras) → dark_now False. B2
    discriminator — the whole point of the narrow definition."""
    from custom_components.universal_room_automation.camera_census import (
        compute_camera_input_dark_frame,
    )
    hass = _MockHass()
    frame = compute_camera_input_dark_frame(hass, _FakeCameraManager([]))
    assert frame.denominator == 0
    assert frame.dark_now is False


def test_compute_camera_input_dark_frame_fleet_unavailable():
    """24/24 unavailable + Frigate configured → dark_now True."""
    from custom_components.universal_room_automation.camera_census import (
        compute_camera_input_dark_frame,
    )
    sensors = [f"sensor.cam{i}_person_count" for i in range(24)]
    hass = _MockHass()
    for s in sensors:
        hass.states.set(s, "unavailable")
    frame = compute_camera_input_dark_frame(
        hass, _FakeCameraManager(sensors),
    )
    assert frame.denominator == 24
    assert frame.unavailable_count == 24
    assert frame.fraction == 1.0
    assert frame.dark_now is True


def test_compute_camera_input_dark_frame_status2_or_trigger():
    """0 unavailable but frigate_status_2 bad → dark_now True."""
    from custom_components.universal_room_automation.camera_census import (
        compute_camera_input_dark_frame,
    )
    sensors = [f"sensor.cam{i}_person_count" for i in range(10)]
    hass = _MockHass()
    for s in sensors:
        hass.states.set(s, "0")
    hass.states.set("sensor.frigate_status_2", "unavailable")
    frame = compute_camera_input_dark_frame(
        hass, _FakeCameraManager(sensors),
    )
    assert frame.status2_bad is True
    assert frame.dark_now is True


def test_hysteresis_latch_asymmetric_band():
    """apply_camera_input_dark_hysteresis contract matches the
    asymmetric band."""
    from custom_components.universal_room_automation.camera_census import (
        apply_camera_input_dark_hysteresis, CameraInputDarkFrame,
    )
    f_dark = CameraInputDarkFrame(10, 10, 1.0, "running", False, True, [])
    assert apply_camera_input_dark_hysteresis(False, f_dark) is True
    f_mid = CameraInputDarkFrame(10, 5, 0.5, "running", False, False, [])
    assert apply_camera_input_dark_hysteresis(True, f_mid) is True
    f_clear = CameraInputDarkFrame(10, 1, 0.1, "running", False, False, [])
    assert apply_camera_input_dark_hysteresis(True, f_clear) is False
    f_s2_bad = CameraInputDarkFrame(
        10, 1, 0.1, "unavailable", True, True, [],
    )
    assert apply_camera_input_dark_hysteresis(True, f_s2_bad) is True


def test_shared_helper_used_in_optimizer_and_census():
    """Both the optimizer evaluator and the census call the SAME
    compute_camera_input_dark_frame helper (one definition)."""
    import inspect as _insp
    from custom_components.universal_room_automation.domain_coordinators import (
        optimization as opt_mod,
    )
    from custom_components.universal_room_automation import camera_census as cc_mod
    assert "compute_camera_input_dark_frame" in _insp.getsource(opt_mod)
    assert "compute_camera_input_dark_frame" in _insp.getsource(cc_mod)

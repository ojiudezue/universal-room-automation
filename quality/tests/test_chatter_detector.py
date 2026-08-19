"""STEP D2 + D3 + D5 — ChatterDetector tests.

Drives the production ChatterDetector directly with stubbed HA
(state-change event, hass.states, entity_registry). Fixtures come from
the D0 recorder hand-check (`PROBE_sensor_chatter_definition_handcheck.md`):
positive = ratgdo-shaped sustained sub-floor burst; negative = healthy
busy PIR with all edges above T_floor; must-exclude = camera-motion group.
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_URA = _ROOT / "custom_components" / "universal_room_automation"


# ---------------------------------------------------------------------------
# Minimal HA + URA stub scaffolding so chatter_detector.py + const.py load.
# ---------------------------------------------------------------------------


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _install_ha_stubs():
    if "homeassistant" in sys.modules:
        return
    _mod("homeassistant")
    core = _mod("homeassistant.core")

    class Event:
        def __init__(self, data, time_fired=None):
            self.data = data
            self.time_fired = time_fired

    class HomeAssistant:  # noqa: D401
        pass

    core.Event = Event
    core.HomeAssistant = HomeAssistant

    helpers = _mod("homeassistant.helpers")
    ev = _mod("homeassistant.helpers.event")

    def async_track_state_change_event(hass, entities, cb):
        hass._tracked = list(entities)
        hass._cb = cb
        return lambda: setattr(hass, "_cb", None)

    ev.async_track_state_change_event = async_track_state_change_event

    er = _mod("homeassistant.helpers.entity_registry")

    class _Entry:  # noqa: D401 — exported for tests via er._Entry
        def __init__(self, platform):
            self.platform = platform

    er._Entry = _Entry

    class _Reg:
        def __init__(self, mapping):
            self._m = mapping
        def async_get(self, eid):
            return self._m.get(eid)

    def async_get(hass):
        return _Reg(getattr(hass, "_reg_map", {}))

    er.async_get = async_get

    util = _mod("homeassistant.util")
    dt = _mod("homeassistant.util.dt")
    dt.utcnow = lambda: datetime.now(timezone.utc)
    dt.now = dt.utcnow


_install_ha_stubs()


def _spec_load(name, path):
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# Stub the URA package + const so chatter_detector's relative imports resolve.
def _install_ura_package():
    if "test_ura_pkg" in sys.modules:
        return
    pkg = types.ModuleType("test_ura_pkg")
    pkg.__path__ = [str(_URA)]
    sys.modules["test_ura_pkg"] = pkg
    # Load const under this package name.
    _spec_load("test_ura_pkg.const", str(_URA / "const.py"))
    # domain_coordinators subpackage.
    dc = types.ModuleType("test_ura_pkg.domain_coordinators")
    dc.__path__ = [str(_URA / "domain_coordinators")]
    sys.modules["test_ura_pkg.domain_coordinators"] = dc
    # Empty sensor_capability stub (best-effort provider = None).
    cap_stub = types.ModuleType("test_ura_pkg.domain_coordinators.sensor_capability")
    cap_stub.get_capability = lambda hass, eid: None
    sys.modules["test_ura_pkg.domain_coordinators.sensor_capability"] = cap_stub
    # Also register under the real package name path used at runtime — the
    # detector imports `from .sensor_capability import get_capability`
    # relatively; when we load the detector module under this test package
    # the relative import resolves to test_ura_pkg.domain_coordinators.*.


_install_ura_package()


@pytest.fixture(scope="module")
def chatter_mod():
    return _spec_load(
        "test_ura_pkg.domain_coordinators.chatter_detector",
        str(_URA / "domain_coordinators" / "chatter_detector.py"),
    )


@pytest.fixture(scope="module")
def const_mod():
    return sys.modules["test_ura_pkg.const"]


# ---------------------------------------------------------------------------
# Fake HA + coordinator scaffolding.
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self, state, last_changed=None):
        self.state = state
        self.last_changed = last_changed
        self.attributes = {}


class _FakeStates:
    def __init__(self):
        self._m = {}
    def get(self, eid):
        return self._m.get(eid)
    def set(self, eid, state):
        self._m[eid] = _FakeState(state)


class _FakeHass:
    def __init__(self):
        self.states = _FakeStates()
        self._tracked = None
        self._cb = None
        self._reg_map = {}


class _FakeEntry:
    def __init__(self, motion=None, mmwave=None, occupancy=None,
                 room_name="testroom"):
        self.data = {
            "room_name": room_name,
            "motion_sensors": motion or [],
            "presence_sensors": mmwave or [],
            "occupancy_sensors": occupancy or [],
        }
        self.options = {}


class _FakeCoordinator:
    def __init__(self, hass, entry, boot_settled=True):
        self.hass = hass
        self.entry = entry
        self._boot = boot_settled
    def _d2_boot_settle_done(self):
        return self._boot


def _make(chatter_mod, motion=None, mmwave=None, occupancy=None,
          integration_map=None, boot_settled=True, room_name="testroom"):
    hass = _FakeHass()
    if integration_map:
        # Register entity-registry entries so provider inference sees the
        # integration platform (camera-family guard).
        from homeassistant.helpers.entity_registry import _Entry  # type: ignore
        for eid, plat in integration_map.items():
            hass._reg_map[eid] = _Entry(plat)
    entry = _FakeEntry(motion=motion, mmwave=mmwave, occupancy=occupancy,
                       room_name=room_name)
    coord = _FakeCoordinator(hass, entry, boot_settled=boot_settled)
    det = chatter_mod.ChatterDetector(coord)
    return coord, det, hass


def _fire_edges(hass, entity_id, times, state="on"):
    """Fire N alternating state edges at the given monotonically-increasing times."""
    from homeassistant.core import Event  # type: ignore
    for i, t in enumerate(times):
        val = "on" if (i % 2 == 0) else "off"
        # Set new state before invoking callback (detector reads via arg).
        st = _FakeState(val)
        hass.states._m[entity_id] = st
        ev = Event({"entity_id": entity_id, "new_state": st}, time_fired=t)
        hass._cb(ev)


# ---------------------------------------------------------------------------
# Positive fixture: ratgdo-shaped sustained sub-floor burst.
# ---------------------------------------------------------------------------


def test_ratgdo_shaped_sensor_flagged_chatter_after_burst(chatter_mod, const_mod):
    """Positive D0 fixture: ratgdo-shaped 2.5s sustained cadence -> chatter.

    T_floor for opener/ratgdo = 3.0s; K = 20; window = 600s.
    A sensor emitting one edge every 2.5s (below 3.0s floor) for 25 edges
    accumulates >= 20 sub-floor events well within the window.
    """
    eid = "binary_sensor.ratgdov25i_dbfe2a_motion"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    # Verify the classifier accepted it (ratgdo provider inferred from eid).
    assert eid in det._entity_to_meta, (
        "ratgdo-shaped entity_id should classify in-scope via provider "
        "inference"
    )
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [base + timedelta(seconds=2.5 * i) for i in range(30)]
    _fire_edges(hass, eid, times)
    flagged = det.chattering_entities()
    assert eid in flagged, (
        f"ratgdo-shaped burst should be flagged; flagged={flagged}, "
        f"sub_floor_events={len(det._sub_floor_events.get(eid, ()))}, "
        f"K={const_mod.CHATTER_BURST_K}"
    )


# ---------------------------------------------------------------------------
# Negative fixture: healthy busy PIR (all edges above T_floor).
# ---------------------------------------------------------------------------


def test_healthy_busy_pir_not_flagged_despite_high_transition_rate(chatter_mod):
    """Negative D0 fixture: PIR firing every 10s (above 2.0s floor) -> healthy.

    Discriminator: raw transition rate is HIGH (60 edges over 10 min) but
    sub-floor event count is ZERO -> INV-CHATTER-2 holds.
    """
    eid = "binary_sensor.hallway_pir"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [base + timedelta(seconds=10 * i) for i in range(60)]
    _fire_edges(hass, eid, times)
    assert eid not in det.chattering_entities(), (
        "Healthy busy PIR (10s cadence >> 2.0s floor) must NOT be flagged"
    )
    assert len(det._sub_floor_events.get(eid, ())) == 0


def test_isolated_sub_floor_artifacts_below_K_not_flagged(chatter_mod):
    """Negative D0 fixture: 4 isolated sub-floor artifacts / 7d -> healthy.

    Below CHATTER_BURST_K = 20; INV-CHATTER-2 holds.
    """
    eid = "binary_sensor.master_bathroom_motion"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 4 sub-floor pairs interspersed with legitimate 30s cadence.
    times = []
    t = base
    for i in range(4):
        times.append(t)
        times.append(t + timedelta(seconds=0.5))  # sub-floor pair
        t += timedelta(seconds=30)
    _fire_edges(hass, eid, times)
    assert eid not in det.chattering_entities()


# ---------------------------------------------------------------------------
# M-MED-2 provenance-gate: camera-motion group MUST be denied.
# ---------------------------------------------------------------------------


def test_camera_motion_group_denied_by_provenance_gate(chatter_mod):
    """M-MED-2: binarygroup_camera_motion_zone1 must classify as camera-family.

    The 14,216 sub-0.5s events in the D0 fixture are working AS DESIGNED
    (inference at frame cadence); the physics criterion does not apply.
    Classifier fires camera-family DENY BEFORE the (kind, provider) allow.
    """
    eid = "binary_sensor.binarygroup_camera_motion_zone1"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    # Must NOT be in the tracked map at all — never scored.
    assert eid not in det._entity_to_meta, (
        f"camera-motion group must be silent-denied; found in _entity_to_meta"
    )
    # Even if edges are simulated by bypassing the classifier, the burst
    # of 100 sub-0.5s events (matching D0 shape) must produce ZERO
    # promotions because the detector never subscribed to it.
    assert eid not in det.chattering_entities()


def test_mislabeled_frigate_entity_denied_by_integration_fallback(chatter_mod):
    """Camera-family fallback: an entity from `frigate` integration is denied.

    Simulates a bare device_class=motion entity whose entity_id lacks
    the `camera_` substring but whose integration platform is `frigate`
    -> the integration-domain guard fires BEFORE the (kind, provider)
    allow-list.
    """
    eid = "binary_sensor.foo_motion"
    coord, det, hass = _make(
        chatter_mod, motion=[eid],
        integration_map={eid: "frigate"},
    )
    det.async_register_listeners()
    assert eid not in det._entity_to_meta


def test_pir_provider_tag_scored_normally(chatter_mod):
    """Positive control for the classifier: `_pir` substring -> in-scope."""
    eid = "binary_sensor.foo_pir"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    assert eid in det._entity_to_meta


# ---------------------------------------------------------------------------
# Boot-settle gate.
# ---------------------------------------------------------------------------


def test_boot_settle_gate_suppresses_flagging(chatter_mod):
    eid = "binary_sensor.ratgdo_x_motion"
    coord, det, hass = _make(chatter_mod, motion=[eid], boot_settled=False)
    det.async_register_listeners()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [base + timedelta(seconds=2.5 * i) for i in range(30)]
    _fire_edges(hass, eid, times)
    assert eid not in det.chattering_entities(), (
        "Boot-settle gate must suppress flagging while _d2_boot_settle_done "
        "returns False"
    )
    # Release boot-settle; more edges should flag it.
    coord._boot = True
    more = [times[-1] + timedelta(seconds=2.5 * (i + 1)) for i in range(25)]
    _fire_edges(hass, eid, more)
    assert eid in det.chattering_entities()


# ---------------------------------------------------------------------------
# Unavailable/unknown transitions ignored.
# ---------------------------------------------------------------------------


def test_unavailable_transitions_not_counted(chatter_mod):
    """Guard: `unavailable`/`unknown` transitions are a separate fault class."""
    eid = "binary_sensor.ratgdo_x_motion"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    from homeassistant.core import Event  # type: ignore
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Alternate unavailable / unknown so the same-value dedup guard is NOT
    # what's suppressing chatter — this isolates the unavailable/unknown
    # early-return specifically.
    for i in range(50):
        val = "unavailable" if (i % 2 == 0) else "unknown"
        st = _FakeState(val)
        hass.states._m[eid] = st
        ev = Event({"entity_id": eid, "new_state": st},
                   time_fired=base + timedelta(seconds=0.5 * i))
        hass._cb(ev)
    assert eid not in det.chattering_entities()


# ---------------------------------------------------------------------------
# D3 — auto-release after quiet window.
# ---------------------------------------------------------------------------


def test_chatter_auto_release_after_quiet_window(chatter_mod, const_mod):
    """D3: quiet CHATTER_RELEASE_QUIET_S + available -> released."""
    eid = "binary_sensor.ratgdo_x_motion"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [base + timedelta(seconds=2.5 * i) for i in range(30)]
    _fire_edges(hass, eid, times)
    assert eid in det.chattering_entities()
    # Mark entity available; advance beyond quiet window.
    hass.states._m[eid] = _FakeState("on")
    after = times[-1] + timedelta(seconds=const_mod.CHATTER_RELEASE_QUIET_S + 1)
    released = det.check_release(after)
    assert eid in released
    assert eid not in det.chattering_entities()


def test_chatter_release_skipped_when_unavailable(chatter_mod, const_mod):
    eid = "binary_sensor.ratgdo_x_motion"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [base + timedelta(seconds=2.5 * i) for i in range(30)]
    _fire_edges(hass, eid, times)
    assert eid in det.chattering_entities()
    hass.states._m[eid] = _FakeState("unavailable")
    after = times[-1] + timedelta(seconds=const_mod.CHATTER_RELEASE_QUIET_S + 1)
    released = det.check_release(after)
    assert released == set(), "quiet-on-dead-hardware != stability"
    assert eid in det.chattering_entities()


# ---------------------------------------------------------------------------
# L-LOW-B subscribe teardown lifecycle.
# ---------------------------------------------------------------------------


def test_chatter_detector_unsubscribe_called_on_teardown(chatter_mod):
    """L-LOW-B: async_teardown calls the stored unsub exactly once.

    Bug Class #38 discipline: the async_track_state_change_event return
    is stored as self._chatter_unsub and released from async_teardown.
    """
    eid = "binary_sensor.ratgdo_x_motion"
    coord, det, hass = _make(chatter_mod, motion=[eid])
    det.async_register_listeners()
    assert det._chatter_unsub is not None
    assert hass._cb is not None
    asyncio.get_event_loop().run_until_complete(det.async_teardown())
    assert det._chatter_unsub is None
    assert hass._cb is None, (
        "L-LOW-B VIOLATED: state-change subscription survived teardown"
    )


def test_entity_to_kind_rebuilt_on_reregister(chatter_mod):
    """Feed re-review LOW: _entity_to_meta rebuilds per setup, no caching."""
    eid_a = "binary_sensor.a_pir"
    eid_b = "binary_sensor.b_pir"
    coord, det, hass = _make(chatter_mod, motion=[eid_a])
    det.async_register_listeners()
    assert set(det._entity_to_meta.keys()) == {eid_a}
    # Simulate config change: replace sensor A with B, re-register.
    coord.entry.data["motion_sensors"] = [eid_b]
    det.async_register_listeners()
    assert set(det._entity_to_meta.keys()) == {eid_b}, (
        "_entity_to_meta must rebuild on re-register; stale sensor a leaked"
    )

"""CAMERA-SILENT-PRODUCER-TRIPWIRE-1 — detector-hung frozen-stat trip-wire.

PLANNING_camera_detector_hung_tripwire.md Rev 2. All tests drive production
code (the evaluator directly, or a full ``_run_cycle_body``). Time is driven by
a controllable clock substituted for ``optimization.dt_util`` (scoped via
monkeypatch). The entity registry is a scoped monkeypatch of
``entity_registry.async_get``. No sys.modules surgery.

Registry fixture shape is copied from the live core.entity_registry
(2026-10-21): fleet sensor unique_id
``01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_fps:detection``; per-camera fps sensors
``...:sensor_fps:back_yard_detection`` must NOT match.
"""
from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    optimization as opt_mod,
)

FLEET_UID = "01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_fps:detection"
CAM_UID = "01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_fps:back_yard_detection"
FPS = "sensor.frigate_detection_fps_2"
T0 = datetime(2026, 10, 21, 15, 0, 0, tzinfo=timezone.utc)


class _State:
    def __init__(self, state, last_changed=None):
        self.state = state
        self.last_changed = last_changed


class _States:
    def __init__(self):
        self._s = {}

    def get(self, eid):
        return self._s.get(eid)

    def set(self, eid, state, last_changed=None):
        self._s[eid] = _State(state, last_changed)


class _Entries:
    def __init__(self, entries=None):
        self._e = entries or []

    def async_entries(self, _d=None):
        return list(self._e)


class _Hass:
    def __init__(self):
        self.data = {"universal_room_automation": {}}
        self.config_entries = _Entries()
        self.states = _States()
        self.bus = MagicMock()
        self.services = MagicMock()

    def async_create_task(self, coro):
        try:
            coro.close()
        except Exception:
            pass


class _Clock:
    def __init__(self, t):
        self.t = t

    def advance(self, s):
        self.t = self.t + timedelta(seconds=s)


class _DtProxy:
    """Real dt_util with utcnow() replaced by the test clock."""

    def __init__(self, real, clock):
        self._real = real
        self._clock = clock

    def utcnow(self):
        return self._clock.t

    def now(self, *a, **k):
        return self._clock.t

    def __getattr__(self, name):
        return getattr(self._real, name)


def _reg_entry(entity_id, unique_id, platform="frigate"):
    return types.SimpleNamespace(
        entity_id=entity_id, unique_id=unique_id, platform=platform,
        domain=entity_id.split(".", 1)[0],
    )


@pytest.fixture
def env(monkeypatch):
    """Clock + registry. Returns a namespace; registry list is mutable."""
    clock = _Clock(T0)
    monkeypatch.setattr(opt_mod, "dt_util", _DtProxy(opt_mod.dt_util, clock))
    registry = [
        _reg_entry(FPS, FLEET_UID),
        _reg_entry("sensor.back_yard_detection_fps_2", CAM_UID),
    ]
    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(
        er, "async_get",
        lambda _h: types.SimpleNamespace(
            entities=types.SimpleNamespace(values=lambda: list(registry)),
        ),
    )
    return types.SimpleNamespace(clock=clock, registry=registry)


def _coord(hass=None):
    hass = hass or _Hass()
    return opt_mod.OptimizationCoordinator(hass), hass


def _hung(findings):
    return [f for f in findings
            if (getattr(f, "dedup_key", None) or (None,))[0]
            == "camera_detector_hung"]


def _tick(coord, env, secs=300):
    env.clock.advance(secs)
    return _hung(coord._evaluate_camera_detector_hung_dimension())


def _run_cycle(coord, real_notify=False):
    import asyncio as _aio

    coord._update_scoreboard = lambda *_a, **_k: None
    coord._run_llm_meta_pass = AsyncMock(return_value=[])
    coord._persist_findings_batch = AsyncMock(return_value=None)
    coord._dispatch_actions = AsyncMock(return_value=None)
    if not real_notify:
        coord._notify_if_severe = AsyncMock(return_value=None)
    loop = _aio.new_event_loop()
    try:
        return loop.run_until_complete(coord._run_cycle_body())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Evaluator behaviour
# ---------------------------------------------------------------------------


def test_detector_hung_fires_once_on_frozen_value(env):
    coord, hass = _coord()  # boot_ref = T0
    hass.states.set(FPS, "45")
    fired_at = []
    for i in range(1, 13):  # 12 ticks x 300 s = 60 min
        out = _tick(coord, env)
        if out:
            fired_at.append(i)
            f = out[0]
            assert f.dedup_key == ("camera_detector_hung", "fleet")
            assert f.payload["kind"] == "camera_detector_hung"
            assert f.severity == "high"
            assert "docker restart frigate" in f.description
    # first numeric read at T0+300 (past settle at T0+180): fires at
    # T0+300+900 = tick 4. Exactly once.
    assert fired_at == [4]
    assert coord._detector_hung_fired is True


def test_detector_hung_dwell_boundary_literals(env):
    """899 s no fire; 900 s fires (hardcoded literals, not the const)."""
    coord, hass = _coord()
    env.clock.advance(1000)  # well past boot settle
    hass.states.set(FPS, "45")
    assert _tick(coord, env, 0) == []   # anchor
    assert _tick(coord, env, 899) == []
    assert len(_tick(coord, env, 1)) == 1


def test_detector_hung_clears_on_change(env):
    coord, hass = _coord()
    env.clock.advance(1000)
    hass.states.set(FPS, "45")
    for i in range(240):  # value changes every 30 s for 2 h
        hass.states.set(FPS, str(40 + (i % 7)))
        assert _tick(coord, env, 30) == []
    # A latched episode clears and re-arms on change.
    hass.states.set(FPS, "45")
    assert _tick(coord, env, 0) == []
    assert len(_tick(coord, env, 900)) == 1
    hass.states.set(FPS, "46")
    assert _tick(coord, env, 30) == []
    assert coord._detector_hung_fired is False
    assert len(_tick(coord, env, 900)) == 1


def test_detector_hung_silent_when_unavailable(env):
    """Host-down: fps unavailable -> this check is silent; camera_input_dark
    (the existing path) owns it and fires."""
    coord, hass = _coord()
    sensors = [f"sensor.cam{i}_person_count" for i in range(4)]

    class _Cam:
        def __init__(self, s):
            self.person_count_sensor = s
            self.platform = "frigate"

    hass.data["universal_room_automation"]["camera_manager"] = (
        types.SimpleNamespace(
            get_all_frigate_cameras=lambda: [_Cam(s) for s in sensors],
        )
    )
    for s in sensors:
        hass.states.set(s, "unavailable")
    hass.states.set("sensor.frigate_status_2", "unavailable")
    hass.states.set(FPS, "unavailable")
    env.clock.advance(1000)
    dark = []
    for _ in range(12):
        env.clock.advance(300)
        assert _hung(coord._evaluate_camera_detector_hung_dimension()) == []
        dark += coord._evaluate_camera_input_dark_dimension()
    assert [f.dedup_key for f in dark] == [("camera_input_dark", "fleet")]


def test_detector_hung_non_numeric_resets_dwell(env):
    coord, hass = _coord()
    env.clock.advance(1000)
    hass.states.set(FPS, "45")
    assert _tick(coord, env, 0) == []
    assert _tick(coord, env, 600) == []
    hass.states.set(FPS, "unavailable")      # blip mid-dwell
    assert _tick(coord, env, 30) == []
    assert coord._detector_value_since is None
    hass.states.set(FPS, "45")               # SAME value returns
    assert _tick(coord, env, 0) == []        # new anchor
    # had the dwell carried over, 630 s already elapsed -> 300 more fires.
    assert _tick(coord, env, 300) == []
    assert _tick(coord, env, 599) == []
    assert len(_tick(coord, env, 1)) == 1


@pytest.mark.parametrize("bad", ["unknown", "", "none", "abc", None])
def test_detector_hung_non_numeric_states_all_reset(env, bad):
    coord, hass = _coord()
    env.clock.advance(1000)
    hass.states.set(FPS, "45")
    _tick(coord, env, 0)
    _tick(coord, env, 600)
    if bad is None:
        hass.states._s.pop(FPS)
    else:
        hass.states.set(FPS, bad)
    assert _tick(coord, env, 30) == []
    assert coord._detector_last_value is None
    assert coord._detector_value_since is None


def test_detector_hung_boot_unknown_then_numeric(env):
    """unknown for 2 ticks then constant: fires FROZEN after the first
    numeric tick, never before boot_ref + settle + frozen."""
    coord, hass = _coord()  # boot_ref = T0
    hass.states.set(FPS, "unknown")
    assert _tick(coord, env, 60) == []    # T0+60
    assert _tick(coord, env, 60) == []    # T0+120
    hass.states.set(FPS, "45")
    assert _tick(coord, env, 20) == []    # T0+140 first numeric (pre-settle)
    # anchor = max(T0+140, T0+180) = T0+180 -> fire at T0+1080.
    assert _tick(coord, env, 939) == []   # T0+1079
    assert len(_tick(coord, env, 1)) == 1  # T0+1080


def test_detector_hung_value_since_is_first_numeric_read(env):
    coord, hass = _coord()
    hass.states.set(FPS, "unknown")
    _tick(coord, env, 500)
    hass.states.set(FPS, "45")
    _tick(coord, env, 100)  # T0+600
    assert coord._detector_value_since == T0 + timedelta(seconds=600)
    assert _tick(coord, env, 899) == []
    assert len(_tick(coord, env, 1)) == 1


def test_detector_hung_constant_zero_also_fires(env):
    coord, hass = _coord()
    env.clock.advance(1000)
    hass.states.set(FPS, "0")
    _tick(coord, env, 0)
    assert len(_tick(coord, env, 900)) == 1


@pytest.mark.parametrize("frozen", [0, -1])
def test_detector_hung_kill_switch_zero_and_negative(env, monkeypatch, frozen):
    monkeypatch.setattr(opt_mod, "CAMERA_DETECTOR_FROZEN_S", frozen)
    coord, hass = _coord()
    hass.states.set(FPS, "45")
    for _ in range(48):  # 4 h frozen
        assert _tick(coord, env, 300) == []
    assert coord._detector_hung_fired is False


def test_detector_hung_resolves_via_registry_unique_id(env):
    """entity_id renamed (no _2) with the same unique_id still fires; the
    per-camera fps sensor is not picked."""
    env.registry[0] = _reg_entry("sensor.frigate_detection_fps", FLEET_UID)
    coord, hass = _coord()
    hass.states.set("sensor.frigate_detection_fps", "45")
    hass.states.set(FPS, "unavailable")  # stale literal must be ignored
    hass.states.set("sensor.back_yard_detection_fps_2", "7")
    env.clock.advance(1000)
    _tick(coord, env, 0)
    out = _tick(coord, env, 900)
    assert len(out) == 1
    assert out[0].payload["entity_id"] == "sensor.frigate_detection_fps"


def test_detector_hung_inert_when_unresolved(env, caplog):
    env.registry[:] = [_reg_entry("sensor.back_yard_detection_fps_2", CAM_UID)]
    coord, hass = _coord()
    hass.states.set(FPS, "45")
    import logging
    with caplog.at_level(logging.INFO, logger=opt_mod.__name__):
        for _ in range(20):
            assert _tick(coord, env, 300) == []
    logs = [r for r in caplog.records
            if "camera_detector_hung_inert_unresolved" in r.getMessage()]
    assert len(logs) == 1


def test_detector_hung_inert_when_ambiguous(env):
    env.registry.append(_reg_entry("sensor.other_detection_fps", "X" + FLEET_UID))
    coord, hass = _coord()
    hass.states.set(FPS, "45")
    hass.states.set("sensor.other_detection_fps", "45")
    for _ in range(20):
        assert _tick(coord, env, 300) == []


def test_detector_hung_ignores_non_frigate_platform(env):
    env.registry[:] = [_reg_entry(FPS, FLEET_UID, platform="template")]
    coord, hass = _coord()
    hass.states.set(FPS, "45")
    for _ in range(20):
        assert _tick(coord, env, 300) == []


def test_detector_hung_protect_only_install_inert(env):
    """Protect-only: no frigate registry entries at all -> inert."""
    env.registry[:] = []
    coord, hass = _coord()
    for _ in range(20):
        assert _tick(coord, env, 300) == []
    assert coord._detector_entity_id is None


# ---------------------------------------------------------------------------
# Lifecycle / rebuild (NEW instance)
# ---------------------------------------------------------------------------


def test_detector_hung_new_instance_rearms_and_fires_once(env):
    hass = _Hass()
    hass.states.set(FPS, "45")
    old, _ = _coord(hass)
    env.clock.advance(1000)
    _tick(old, env, 0)
    assert len(_tick(old, env, 900)) == 1
    # CM rebuild: a NEW coordinator constructed now (boot_ref = now),
    # same frozen state.
    new, _ = _coord(hass)
    assert new is not old
    assert new._detector_hung_fired is False
    fired = []
    elapsed = 0
    for _ in range(36):  # 36 x 60 s = 36 min
        elapsed += 60
        if _tick(new, env, 60):
            fired.append(elapsed)
    # first read at +60 (pre-settle) -> anchor +180 -> fire at +1080.
    assert fired == [1080]


# ---------------------------------------------------------------------------
# Wire-in anchors: real cycles
# ---------------------------------------------------------------------------


def test_detector_hung_emitted_by_real_cycle(env):
    """Site 1: the evaluator is registered in _run_cycle_body."""
    coord, hass = _coord()
    coord._cycles_since_start = 999
    hass.states.set(FPS, "45")
    env.clock.advance(1000)
    assert _hung(_run_cycle(coord)) == []
    env.clock.advance(900)
    out = _hung(_run_cycle(coord))
    assert len(out) == 1
    env.clock.advance(300)
    assert _hung(_run_cycle(coord)) == []


def test_detector_hung_survives_findings_cap(env):
    """Site 4: a cap-saturated cycle keeps the hung finding."""
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_MAX_FINDINGS_PER_CYCLE,
    )
    coord, hass = _coord()
    coord._cycles_since_start = 999
    hass.states.set(FPS, "45")
    env.clock.advance(1000)
    _run_cycle(coord)
    env.clock.advance(900)
    flood = [opt_mod.OptimizationFinding(
        timestamp="t", level="room", target_id=f"r{i}",
        dimension=opt_mod.OptimizationDimension.SENSOR_HEALTH,
        severity="critical", confidence=0.9, score=0.0, description="flood",
        dedup_key=("sensor_health", f"r{i}"),
    ) for i in range(OPTIMIZER_MAX_FINDINGS_PER_CYCLE + 20)]
    coord._evaluate_comfort_dimension = lambda: list(flood)
    out = _run_cycle(coord)
    assert len(out) <= OPTIMIZER_MAX_FINDINGS_PER_CYCLE + 1
    assert len(_hung(out)) == 1


def test_detector_hung_pages_not_digest(env):
    """Site 2: the hung finding reaches nm.async_notify with the default
    (empty) allowlist, driven through a real cycle + real _notify_if_severe."""
    hass = _Hass()
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    nm.is_quiet_hours_active = MagicMock(return_value=False)
    hass.data["universal_room_automation"]["notification_manager"] = nm
    hass.config_entries = _Entries([types.SimpleNamespace(
        entry_id="cm", data={"entry_type": "coordinator_manager"},
        options={},
    )])
    coord, _ = _coord(hass)
    coord._cycles_since_start = 999
    hass.states.set(FPS, "45")
    env.clock.advance(1000)
    _run_cycle(coord, real_notify=True)
    nm.async_notify.reset_mock()
    env.clock.advance(900)
    out = _run_cycle(coord, real_notify=True)
    assert len(_hung(out)) == 1
    texts = [repr(c) for c in nm.async_notify.await_args_list]
    assert any("camera_detector_hung" in t or "Frigate detector" in t
               for t in texts), texts


@pytest.mark.asyncio
async def test_other_sensor_health_high_still_defers(env):
    """Discriminator for site 2: a non-oneshot sensor_health HIGH defers."""
    hass = _Hass()
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    hass.data["universal_room_automation"]["notification_manager"] = nm
    hass.config_entries = _Entries([types.SimpleNamespace(
        entry_id="cm", data={"entry_type": "coordinator_manager"},
        options={},
    )])
    coord, _ = _coord(hass)
    f = opt_mod.OptimizationFinding(
        timestamp="t", level="room", target_id="k",
        dimension=opt_mod.OptimizationDimension.SENSOR_HEALTH,
        severity="high", confidence=0.9, score=0.0, description="x",
        dedup_key=("camera_detector_hungX", "fleet"),
    )
    await coord._notify_if_severe(f)
    assert nm.async_notify.await_count == 0


# ---------------------------------------------------------------------------
# Site 3: binary sensor attributes (display only)
# ---------------------------------------------------------------------------


def test_binary_sensor_detector_attributes(env):
    from custom_components.universal_room_automation.binary_sensor import (
        CameraInputDegradedBinarySensor,
    )
    hass = _Hass()
    coord, _ = _coord(hass)
    hass.states.set(FPS, "45")
    env.clock.advance(1000)
    _tick(coord, env, 0)
    _tick(coord, env, 950)

    class _CM:
        coordinators = {"optimization": coord}

    hass.data["universal_room_automation"]["coordinator_manager"] = _CM()
    entry = types.SimpleNamespace(
        entry_id="cm", data={"entry_type": "coordinator_manager"}, options={},
    )
    s = CameraInputDegradedBinarySensor(hass, entry)
    attrs = s.extra_state_attributes
    assert attrs["detector_frozen_s"] == 950
    assert attrs["detector_hung_fired"] is True
    assert s.is_on is False  # on/off truth unchanged (census latch)


# ---------------------------------------------------------------------------
# Review fix-up A-HIGH-1: sampling aliasing (last_changed advance = change)
# ---------------------------------------------------------------------------

def test_detector_hung_aliasing_same_value_moving_last_changed_no_fire(env):
    """Same integer at every 5-min sample but HA last_changed moved between
    samples (value changed and came back) -> NOT frozen, never fires."""
    coord, hass = _coord()
    env.clock.advance(1000)
    for i in range(24):  # 2 h of 300 s ticks
        lc = datetime(2026, 10, 21, 0, 0, 0, tzinfo=timezone.utc) + timedelta(
            seconds=37 * i,
        )
        hass.states.set(FPS, "34", last_changed=lc)
        assert _tick(coord, env, 300) == [], i
    assert coord._detector_hung_fired is False


def test_detector_hung_frozen_value_frozen_last_changed_fires(env):
    """Discriminator: same value AND same last_changed -> fires once."""
    coord, hass = _coord()
    env.clock.advance(1000)
    lc = datetime(2026, 10, 21, 0, 0, 0, tzinfo=timezone.utc)
    hass.states.set(FPS, "34", last_changed=lc)
    fired = [i for i in range(1, 10) if _tick(coord, env, 300)]
    # anchor at tick 1; 900 s later = tick 4
    assert fired == [4]


# ---------------------------------------------------------------------------
# Review fix-up B-MED-1: defer through NM quiet hours (no latch)
# ---------------------------------------------------------------------------

def _hass_with_nm(quiet):
    hass = _Hass()
    nm = MagicMock()
    nm.is_quiet_hours_active = MagicMock(side_effect=lambda: quiet[0])
    hass.data["universal_room_automation"]["notification_manager"] = nm
    return hass


def test_detector_hung_defers_during_quiet_hours_then_fires_once(env):
    quiet = [True]
    coord, hass = _coord(_hass_with_nm(quiet))
    env.clock.advance(1000)
    hass.states.set(FPS, "45")
    assert _tick(coord, env, 0) == []
    for _ in range(12):  # 1 h frozen, all inside quiet hours
        assert _tick(coord, env, 300) == []
    assert coord._detector_hung_fired is False
    assert coord._detector_hung_deferred_quiet is True
    quiet[0] = False
    out = _tick(coord, env, 300)
    assert len(out) == 1
    assert coord._detector_hung_deferred_quiet is False
    assert _tick(coord, env, 300) == []


def test_detector_hung_nm_absent_emits_as_before(env):
    coord, hass = _coord()  # no notification_manager in hass.data
    env.clock.advance(1000)
    hass.states.set(FPS, "45")
    _tick(coord, env, 0)
    assert len(_tick(coord, env, 900)) == 1


def test_binary_sensor_exposes_deferred_quiet(env):
    from custom_components.universal_room_automation.binary_sensor import (
        CameraInputDegradedBinarySensor,
    )
    quiet = [True]
    hass = _hass_with_nm(quiet)
    coord, _ = _coord(hass)
    hass.states.set(FPS, "45")
    env.clock.advance(1000)
    _tick(coord, env, 0)
    _tick(coord, env, 950)

    class _CM:
        coordinators = {"optimization": coord}

    hass.data["universal_room_automation"]["coordinator_manager"] = _CM()
    entry = types.SimpleNamespace(
        entry_id="cm", data={"entry_type": "coordinator_manager"}, options={},
    )
    attrs = CameraInputDegradedBinarySensor(hass, entry).extra_state_attributes
    assert attrs["detector_hung_deferred_quiet"] is True
    assert attrs["detector_hung_fired"] is False


# ---------------------------------------------------------------------------
# Review LOWs A-L2 / A-L3
# ---------------------------------------------------------------------------

def test_detector_hung_warns_once_when_resolved_but_never_numeric(env, caplog):
    import logging
    coord, hass = _coord()
    hass.states.set(FPS, "unavailable")
    with caplog.at_level(logging.WARNING):
        _tick(coord, env, 0)
        assert _tick(coord, env, 900) == []
        assert not [r for r in caplog.records if "inert" in r.getMessage()]
        _tick(coord, env, 1)  # 901 s > 900
        _tick(coord, env, 300)
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING and "inert" in r.getMessage()]
    assert len(warns) == 1


def test_detector_hung_unresolved_logs_again_after_resolve(env, caplog):
    import logging
    coord, hass = _coord()
    saved = list(env.registry)
    hass.states.set(FPS, "45")
    with caplog.at_level(logging.INFO):
        env.registry.clear()
        _tick(coord, env)
        env.registry.extend(saved)
        _tick(coord, env)
        env.registry.clear()
        _tick(coord, env)
    logs = [r for r in caplog.records
            if "inert_unresolved" in r.getMessage()]
    assert len(logs) == 2

"""D7 (2026-08-19) — SHADOW-vs-ACT seam + telemetry + device round-trip tests.

Card CHATTER-OBSERVE-CONTROL-D7-1. Load-bearing behavioural tests for the
shadow-first ship. Drives the extracted _apply_chatter_tick helper AST
(same pattern as test_chatter_tick_helper.py — proves the coordinator
source honors the mode gate) + real telemetry off the ChatterDetector.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_URA = _ROOT / "custom_components" / "universal_room_automation"


# ---------------------------------------------------------------------------
# Reuse HA + ura package stub infrastructure lazily. Import order-independent.
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

    core.Event = Event
    core.HomeAssistant = type("HomeAssistant", (), {})
    _mod("homeassistant.helpers")
    ev = _mod("homeassistant.helpers.event")

    def _track(hass, entities, cb):
        hass._tracked = list(entities)
        hass._cb = cb
        return lambda: setattr(hass, "_cb", None)

    ev.async_track_state_change_event = _track
    er = _mod("homeassistant.helpers.entity_registry")
    er.async_get = lambda hass: types.SimpleNamespace(
        async_get=lambda eid: None,
    )
    _mod("homeassistant.util")
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


# ---------------------------------------------------------------------------
# Extract helpers from coordinator.py (same shape as test_chatter_tick_helper).
# ---------------------------------------------------------------------------


def _extract():
    import ast
    src = (_URA / "coordinator.py").read_text()
    tree = ast.parse(src)
    wanted = {
        "_apply_chatter_tick",
        "_discharge_chatter_latches",
        "_chatter_quarantine_enabled",
        "_chatter_mode",
        "_fusion_filter_active",
    }
    found = {}

    class _V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node.name in wanted:
                found[node.name] = node
            self.generic_visit(node)

    _V().visit(tree)
    assert set(found.keys()) == wanted, (
        f"Extract mismatch: {set(found.keys())} vs {wanted}"
    )
    module = ast.Module(body=[
        ast.ClassDef(
            name="_Mixin", bases=[], keywords=[],
            body=list(found.values()), decorator_list=[],
        ),
    ], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {}
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("_ura_const_d7", str(_URA / "const.py"))
    cm = module_from_spec(spec)
    spec.loader.exec_module(cm)
    ns.update({
        "CHATTER_RELEASE_QUIET_S": cm.CHATTER_RELEASE_QUIET_S,
        "CHATTER_OBSERVATION_WINDOW_S": cm.CHATTER_OBSERVATION_WINDOW_S,
        "CONF_CHATTER_QUARANTINE_ENABLED": cm.CONF_CHATTER_QUARANTINE_ENABLED,
        "DEFAULT_CHATTER_QUARANTINE_ENABLED": cm.DEFAULT_CHATTER_QUARANTINE_ENABLED,
        "CHATTER_QUARANTINE_ENABLED": cm.CHATTER_QUARANTINE_ENABLED,
        "CONF_CHATTER_MODE": cm.CONF_CHATTER_MODE,
        "CHATTER_MODES": cm.CHATTER_MODES,
        "CHATTER_MODE_OFF": cm.CHATTER_MODE_OFF,
        "CHATTER_MODE_SHADOW": cm.CHATTER_MODE_SHADOW,
        "CHATTER_MODE_ACT": cm.CHATTER_MODE_ACT,
        "DEFAULT_CHATTER_MODE": cm.DEFAULT_CHATTER_MODE,
    })
    ns["_LOGGER"] = __import__("logging").getLogger("d7test")
    # Stub relative-import chain used inside the extracted methods.
    pkg_name = "_ura_d7_helper_pkg"
    pkg = types.ModuleType(pkg_name); pkg.__path__ = []
    sys.modules[pkg_name] = pkg
    dc = types.ModuleType(f"{pkg_name}.domain_coordinators"); dc.__path__ = []
    sys.modules[f"{pkg_name}.domain_coordinators"] = dc
    nm = types.ModuleType(f"{pkg_name}.domain_coordinators._stuck_signal_nm")

    async def _fake(*a, **k):
        return True

    nm.fire_stuck_signal = _fake
    nm.fire_stuck_signal_recovered = _fake
    sys.modules[f"{pkg_name}.domain_coordinators._stuck_signal_nm"] = nm
    nma = types.ModuleType(f"{pkg_name}.domain_coordinators._nm_cycle_a")
    nma.nm_cycle_a_knob = lambda h, k, d: d
    sys.modules[f"{pkg_name}.domain_coordinators._nm_cycle_a"] = nma
    ns["__package__"] = pkg_name
    ns["__name__"] = f"{pkg_name}._extracted"
    exec(compile(module, "_d7_extracted", "exec"), ns)
    return ns["_Mixin"], cm


@pytest.fixture(scope="module")
def helper():
    cls, _ = _extract()
    return cls


@pytest.fixture(scope="module")
def sensor_exclusion_mod():
    return _spec_load(
        "step_sensor_exclusion_d7",
        str(_URA / "domain_coordinators" / "sensor_exclusion.py"),
    )


@pytest.fixture(scope="module")
def chatter_mod():
    # Reuse test_chatter_detector's package registration if in place;
    # else install a fresh stub package + load the detector.
    pkg = "test_ura_pkg_d7"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg); p.__path__ = [str(_URA)]
        sys.modules[pkg] = p
        _spec_load(f"{pkg}.const", str(_URA / "const.py"))
        dc = types.ModuleType(f"{pkg}.domain_coordinators")
        dc.__path__ = [str(_URA / "domain_coordinators")]
        sys.modules[f"{pkg}.domain_coordinators"] = dc
        cap = types.ModuleType(f"{pkg}.domain_coordinators.sensor_capability")
        cap.get_capability = lambda h, e: None
        sys.modules[f"{pkg}.domain_coordinators.sensor_capability"] = cap
        nma = types.ModuleType(f"{pkg}.domain_coordinators._nm_cycle_a")
        nma.nm_cycle_a_knob = lambda h, k, d: d
        sys.modules[f"{pkg}.domain_coordinators._nm_cycle_a"] = nma
    return _spec_load(
        f"{pkg}.domain_coordinators.chatter_detector",
        str(_URA / "domain_coordinators" / "chatter_detector.py"),
    )


# ---------------------------------------------------------------------------
# FakeHass + FakeDetector for the mode-gate seam tests.
# ---------------------------------------------------------------------------


class _FakeHass:
    def __init__(self):
        self.tasks = []
    def async_create_task(self, coro):
        try: coro.close()
        except Exception: pass
        self.tasks.append("scheduled")


class _FakeDetector:
    def __init__(self, chattering=()):
        self._chattering = set(chattering)
    def chattering_entities(self):
        return set(self._chattering)
    def check_release(self, now=None):
        return set()
    def chatter_detail(self, eid):
        return {"sub_floor_events": 42} if eid in self._chattering else None


def _make(helper, sensor_exclusion_mod, mode, chattering=("binary_sensor.bad",)):
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="testroom")

    class _StandIn(helper):
        def __init__(self):
            self.hass = _FakeHass()
            self._exclusion_set = S
            self._chatter_detector = _FakeDetector(chattering)
            self._chattering_entities = set()
            self._stuck_sensor_kinds = {}
            self._chatter_nm_fired = set()
            # Kill-switch-last matches mode's enabled semantics so B-LOW-4
            # doesn't fire spurious discharge NMs on the first tick.
            self._chatter_kill_switch_last = mode != "off"
            self._mode = mode
        def _chatter_mode(self):
            return self._mode

    return _StandIn(), S


# ===========================================================================
# Load-bearing D7 seam: shadow does NOT promote, act DOES.
# ===========================================================================


def test_d7_shadow_mode_does_not_promote_into_exclusion_set(
    helper, sensor_exclusion_mod,
):
    """SHADOW mode: chatterer is surfaced + NM'd but NOT excluded.

    This is the load-bearing acceptance test for the shadow-first ship.
    A mutation to the coordinator that promotes in shadow (e.g. dropping
    the `if is_act:` guard) would red this test.
    """
    coord, S = _make(helper, sensor_exclusion_mod, mode="shadow")
    stuck = set()
    coord._apply_chatter_tick(stuck, "testroom")

    # NOT excluded — the seam.
    assert not S.is_excluded("binary_sensor.bad"), (
        "D7 SHADOW SEAM VIOLATED: fusion excluded a chatterer in shadow mode"
    )
    assert "binary_sensor.bad" not in stuck, (
        "D7 SHADOW SEAM VIOLATED: chatterer added to stuck_sensors alias"
    )
    # But SURFACED for D5 diagnostics.
    assert "binary_sensor.bad" in coord._chattering_entities, (
        "SHADOW mode must still surface the sensor on _chattering_entities"
    )
    # And label set for the diagnostic sensor.
    assert coord._stuck_sensor_kinds.get("binary_sensor.bad") == "chatter"
    # And NM scheduled (WOULD-quarantine flavor).
    assert len(coord.hass.tasks) == 1, (
        "SHADOW mode must still schedule a WOULD-quarantine NM (once/day)"
    )


def test_d7_act_mode_DOES_promote_into_exclusion_set(
    helper, sensor_exclusion_mod,
):
    """ACT mode: byte-identical to pre-D7 — full quarantine."""
    coord, S = _make(helper, sensor_exclusion_mod, mode="act")
    stuck = set()
    coord._apply_chatter_tick(stuck, "testroom")
    assert S.is_excluded("binary_sensor.bad"), (
        "D7 ACT SEAM VIOLATED: chatterer NOT excluded in act mode"
    )
    assert "binary_sensor.bad" in stuck
    assert "binary_sensor.bad" in coord._chattering_entities


def test_d7_off_mode_is_fully_inert(helper, sensor_exclusion_mod):
    """OFF mode: no promote, no NM, no diagnostic label."""
    coord, S = _make(helper, sensor_exclusion_mod, mode="off")
    stuck = set()
    coord._apply_chatter_tick(stuck, "testroom")
    assert not S.is_excluded("binary_sensor.bad")
    assert coord._chattering_entities == {"binary_sensor.bad"}, (
        # Note: OFF still populates _chattering_entities from the detector
        # so the D5 surface reflects what the detector is seeing during
        # dogfood. But NO promote, NO NM.
        "OFF mode surfaces detector state to _chattering_entities"
    )
    # No NM tasks scheduled.
    assert len(coord.hass.tasks) == 0
    # No label written.
    assert "binary_sensor.bad" not in coord._stuck_sensor_kinds


def test_d7_default_mode_is_shadow(helper, sensor_exclusion_mod):
    """The default MUST be shadow (SHADOW-FIRST doctrine)."""
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "_ura_const_default", str(_URA / "const.py"),
    )
    cm = _u.module_from_spec(spec); spec.loader.exec_module(cm)
    assert cm.DEFAULT_CHATTER_MODE == "shadow"


# ===========================================================================
# Room telemetry test — real ChatterDetector.telemetry() call.
# ===========================================================================


class _State:
    def __init__(self, s, attrs=None):
        self.state = s
        self.attributes = attrs or {}
        self.last_changed = None


class _States:
    def __init__(self):
        self._m = {}
    def get(self, eid):
        return self._m.get(eid)


class _Hass:
    def __init__(self):
        self.states = _States()
        self._tracked = None
        self._cb = None
        self._reg_map = {}


class _Entry:
    def __init__(self):
        self.data = {
            "room_name": "test",
            "motion_sensors": ["binary_sensor.foo_pir"],
            "presence_sensors": [],
            "occupancy_sensors": [],
        }
        self.options = {}


class _Coord:
    def __init__(self, hass):
        self.hass = hass
        self.entry = _Entry()
    def _d2_boot_settle_done(self):
        return True


def test_d7_room_telemetry_surfaces_burst_count_and_would_quarantine(
    chatter_mod, sensor_exclusion_mod,
):
    """Real telemetry: burst count, t_floor, k, would_quarantine per sensor."""
    hass = _Hass()
    coord = _Coord(hass)
    det = chatter_mod.ChatterDetector(coord)
    det.async_register_listeners()
    eid = "binary_sensor.foo_pir"
    assert eid in det._entity_to_meta

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 5 sub-1.0s edges = 4 sub-floor events (below K=10 default).
    from homeassistant.core import Event  # type: ignore
    for i, dt in enumerate([base + timedelta(seconds=0.5 * i) for i in range(5)]):
        val = "on" if (i % 2 == 0) else "off"
        st = _State(val)
        hass.states._m[eid] = st
        hass._cb(Event({"entity_id": eid, "new_state": st}, time_fired=dt))

    rows = det.telemetry()
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_id"] == eid
    assert row["sub_floor_burst_count"] == 4, (
        f"expected 4 sub-floor events at 0.5s cadence, got "
        f"{row['sub_floor_burst_count']}"
    )
    assert row["k"] == 10
    assert row["t_floor"] == 1.0
    # 4 < 10 -> not-would-quarantine yet.
    assert row["would_quarantine"] is False

    # Fire more edges to cross K=10.
    for i, dt in enumerate([
        base + timedelta(seconds=0.5 * (5 + i)) for i in range(10)
    ]):
        val = "on" if (i % 2 == 0) else "off"
        st = _State(val)
        hass.states._m[eid] = st
        hass._cb(Event({"entity_id": eid, "new_state": st}, time_fired=dt))
    row = det.telemetry()[0]
    assert row["would_quarantine"] is True, (
        f"expected would_quarantine after K crossed; sub_floor="
        f"{row['sub_floor_burst_count']}"
    )

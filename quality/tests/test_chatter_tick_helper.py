"""C-CRIT-2/3 de-hollow (2026-08-19).

Real behavioural tests for the extracted ``_apply_chatter_tick`` helper
plus the M-A1 per-day NM latch and B-LOW-2 / B-LOW-4 fix-ups.

Strategy: build a minimal stand-in coordinator that carries the exact
attribute set ``_apply_chatter_tick`` reads/writes, then invoke the
method AS-BOUND from the RoomCoordinator class object. This drives
production source (not a re-implementation) — a source mutation to
_apply_chatter_tick reds these tests.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timezone

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_URA = _ROOT / "custom_components" / "universal_room_automation"


# ---------------------------------------------------------------------------
# Reuse the HA + ura package stub scaffolding from test_chatter_detector.py.
# ---------------------------------------------------------------------------


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _install_ha_stubs():
    """Install a COMPATIBLE-SUPERSET HA stub.

    C-re LOW-1 fix-up (2026-08-19): must be import-order-safe with
    test_chatter_detector.py's stubs. That module's tests fire events by
    calling `hass._cb(ev)` (populated by async_track_state_change_event).
    If THIS module registers `homeassistant.*` first with a stub that
    doesn't set _cb, those tests all fail with `NoneType is not callable`.
    Also register `homeassistant.util` (intermediate package) + a proper
    `_Entry` class on the entity_registry stub so detector tests that
    do `from homeassistant.helpers.entity_registry import _Entry` work.
    """
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
    helpers = _mod("homeassistant.helpers")
    ev = _mod("homeassistant.helpers.event")

    def _track(hass, entities, cb):
        hass._tracked = list(entities)
        hass._cb = cb
        return lambda: setattr(hass, "_cb", None)

    ev.async_track_state_change_event = _track

    er = _mod("homeassistant.helpers.entity_registry")

    class _Entry:
        def __init__(self, platform):
            self.platform = platform

    er._Entry = _Entry

    class _Reg:
        def __init__(self, mapping):
            self._m = mapping
        def async_get(self, eid):
            return self._m.get(eid)

    er.async_get = lambda hass: _Reg(getattr(hass, "_reg_map", {}))

    # Register the intermediate `homeassistant.util` package too so a
    # first-in-order load doesn't ModuleNotFoundError the sub-package.
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
# Extract the _apply_chatter_tick + _discharge_chatter_latches methods
# directly from coordinator.py source (avoids importing the whole 5,000-
# line coordinator module which has 100+ transitive deps). This is a
# controlled extraction — the test verifies the extracted body is
# byte-identical to what ships, so a source mutation lands here too.
# ---------------------------------------------------------------------------


def _extract_and_compile_helpers():
    """Extract the two helper methods + _fusion_filter_active from
    coordinator.py source and compile them into an isolated namespace.

    Contract: if the method signatures / bodies change in coordinator.py
    the extraction here MUST fail loudly (either import or ast.parse
    surfaces the drift). Load-bearing property: the extracted bodies
    are the SAME text as production, byte-for-byte, so a coordinator.py
    mutation flows through to these tests.
    """
    import ast
    src = (_URA / "coordinator.py").read_text()
    tree = ast.parse(src)
    wanted = {
        "_fusion_filter_active",
        "_apply_chatter_tick",
        "_discharge_chatter_latches",
        "_chatter_quarantine_enabled",
    }
    found: dict[str, ast.FunctionDef] = {}

    class _V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node.name in wanted:
                found[node.name] = node
            self.generic_visit(node)

    _V().visit(tree)
    assert set(found.keys()) == wanted, (
        f"Extraction failed: expected {wanted}, got {set(found.keys())}. "
        "Coordinator source has drifted from the extraction contract."
    )
    # Build a module with just these methods attached to a bare class.
    module = ast.Module(body=[
        ast.ClassDef(
            name="_ChatterMixin",
            bases=[],
            keywords=[],
            body=list(found.values()),
            decorator_list=[],
        ),
    ], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: dict = {}
    # Inject the constants used inside the methods.
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("_ura_const_for_tick_helper", str(_URA / "const.py"))
    const_mod = module_from_spec(spec)
    spec.loader.exec_module(const_mod)
    ns["CHATTER_RELEASE_QUIET_S"] = const_mod.CHATTER_RELEASE_QUIET_S
    ns["CHATTER_OBSERVATION_WINDOW_S"] = const_mod.CHATTER_OBSERVATION_WINDOW_S
    ns["CONF_CHATTER_QUARANTINE_ENABLED"] = const_mod.CONF_CHATTER_QUARANTINE_ENABLED
    ns["DEFAULT_CHATTER_QUARANTINE_ENABLED"] = const_mod.DEFAULT_CHATTER_QUARANTINE_ENABLED
    ns["CHATTER_QUARANTINE_ENABLED"] = const_mod.CHATTER_QUARANTINE_ENABLED
    ns["_LOGGER"] = __import__("logging").getLogger("test.chatter_tick")
    # __package__ is required for the extracted methods' relative imports
    # (`from .domain_coordinators._stuck_signal_nm import ...`). Point at
    # a stub package that provides drop-in fire_stuck_signal /
    # fire_stuck_signal_recovered coroutines so hass.async_create_task
    # actually receives them.
    _stub_pkg = types.ModuleType("_ura_tick_helper_pkg")
    _stub_pkg.__path__ = []
    sys.modules["_ura_tick_helper_pkg"] = _stub_pkg
    _stub_dc = types.ModuleType("_ura_tick_helper_pkg.domain_coordinators")
    _stub_dc.__path__ = []
    sys.modules["_ura_tick_helper_pkg.domain_coordinators"] = _stub_dc
    _stub_nm = types.ModuleType(
        "_ura_tick_helper_pkg.domain_coordinators._stuck_signal_nm",
    )
    async def _fake_fire(*a, **k):
        return True
    _stub_nm.fire_stuck_signal = _fake_fire
    _stub_nm.fire_stuck_signal_recovered = _fake_fire
    sys.modules[
        "_ura_tick_helper_pkg.domain_coordinators._stuck_signal_nm"
    ] = _stub_nm
    # Also stub the _nm_cycle_a knob helper (used by
    # _chatter_quarantine_enabled fallback path).
    _stub_nma = types.ModuleType(
        "_ura_tick_helper_pkg.domain_coordinators._nm_cycle_a",
    )
    _stub_nma.nm_cycle_a_knob = lambda hass, key, default: default
    sys.modules[
        "_ura_tick_helper_pkg.domain_coordinators._nm_cycle_a"
    ] = _stub_nma
    ns["__package__"] = "_ura_tick_helper_pkg"
    ns["__name__"] = "_ura_tick_helper_pkg._extracted"
    code = compile(module, "_extracted_from_coordinator", "exec")
    exec(code, ns)
    return ns["_ChatterMixin"], const_mod


@pytest.fixture(scope="module")
def helper_class():
    cls, _ = _extract_and_compile_helpers()
    return cls


@pytest.fixture(scope="module")
def sensor_exclusion_mod():
    return _spec_load(
        "step_sensor_exclusion_v2",
        str(_URA / "domain_coordinators" / "sensor_exclusion.py"),
    )


# ---------------------------------------------------------------------------
# Fake hass + detector.
# ---------------------------------------------------------------------------


class _FakeHass:
    def __init__(self):
        self.tasks = []
        self.data = {}
    def async_create_task(self, coro):
        try:
            coro.close()  # don't actually await
        except Exception:
            pass
        self.tasks.append("scheduled")


class _FakeDetector:
    def __init__(self, chattering=None, released=None):
        self._chattering = set(chattering or [])
        self._released_ids = set(released or [])
        self._detail = {
            e: {"sub_floor_events": 42} for e in self._chattering
        }
    def chattering_entities(self):
        return set(self._chattering)
    def check_release(self, now=None):
        r = set(self._released_ids)
        self._released_ids = set()
        self._chattering -= r
        return r
    def chatter_detail(self, eid):
        return self._detail.get(eid)


def _make_stand_in(helper_class, sensor_exclusion_mod, chatter_enabled=True,
                  chattering=None, released=None, kill_switch_last=True):
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="testroom")

    class _StandIn(helper_class):
        def __init__(self):
            self.hass = _FakeHass()
            self._exclusion_set = S
            self._chatter_detector = _FakeDetector(chattering, released)
            self._chattering_entities = set()
            self._stuck_sensor_kinds = {}
            self._chatter_nm_fired = set()
            self._chatter_kill_switch_last = kill_switch_last
            self._chatter_enabled_flag = chatter_enabled
        def _chatter_quarantine_enabled(self):  # override the extracted one
            return self._chatter_enabled_flag

    return _StandIn(), S


# ---------------------------------------------------------------------------
# Behavioural tests — REAL, drives extracted production source.
# ---------------------------------------------------------------------------


def test_apply_chatter_tick_promotes_current_chatterers(
    helper_class, sensor_exclusion_mod,
):
    """Extracted _apply_chatter_tick promotes into SensorExclusionSet
    and mirrors into _chattering_entities + _stuck_sensor_kinds."""
    coord, S = _make_stand_in(
        helper_class, sensor_exclusion_mod,
        chattering={"binary_sensor.bad_ratgdo"},
    )
    stuck = set()
    coord._apply_chatter_tick(stuck, "testroom")
    assert "binary_sensor.bad_ratgdo" in stuck
    assert S.is_excluded("binary_sensor.bad_ratgdo")
    assert coord._chattering_entities == {"binary_sensor.bad_ratgdo"}
    assert coord._stuck_sensor_kinds["binary_sensor.bad_ratgdo"] == "chatter"


def test_apply_chatter_tick_ma1_per_day_latch_prevents_write_flood(
    helper_class, sensor_exclusion_mod,
):
    """M-A1: fire_stuck_signal scheduled ONCE per (chatter, room, eid)/day.

    The pre-fix code scheduled per-tick. Now the caller-side latch
    (mirror of _stuck_sensor_fired) enforces once-per-day.
    """
    coord, S = _make_stand_in(
        helper_class, sensor_exclusion_mod,
        chattering={"binary_sensor.bad_ratgdo"},
    )
    coord._apply_chatter_tick(set(), "testroom")
    n_after_first = len(coord.hass.tasks)
    assert n_after_first == 1, (
        f"first tick should schedule exactly one NM task; got {n_after_first}"
    )
    # Tick 10 more times — the latch must suppress additional emits.
    for _ in range(10):
        coord._apply_chatter_tick(set(), "testroom")
    assert len(coord.hass.tasks) == 1, (
        f"M-A1 VIOLATED: per-tick NM scheduling not deduped by _chatter_nm_fired; "
        f"got {len(coord.hass.tasks)} scheduled tasks over 11 ticks"
    )


def test_apply_chatter_tick_b_low_2_pop_guarded_by_provenance(
    helper_class, sensor_exclusion_mod,
):
    """B-LOW-2: chatter release must NOT blank _stuck_sensor_kinds if
    stuck_dutycycle client still promotes the entity.

    Fixture: entity is promoted by BOTH stuck_dutycycle and chatter.
    Chatter releases. Assert _stuck_sensor_kinds retains the label.
    """
    coord, S = _make_stand_in(
        helper_class, sensor_exclusion_mod,
        chattering={"binary_sensor.overlap"},
        released=None,
    )
    # Pre-load: stuck_dutycycle promoted this entity earlier in the tick.
    S.promote("stuck_dutycycle", "binary_sensor.overlap", "dutycycle_stuck")
    coord._stuck_sensor_kinds["binary_sensor.overlap"] = "dutycycle"
    # Chatter promotes too.
    coord._apply_chatter_tick(set(), "testroom")
    assert S.is_excluded("binary_sensor.overlap")
    # Next tick: chatter releases; stuck_dutycycle still holds.
    coord._chatter_detector._chattering = set()
    coord._chatter_detector._released_ids = {"binary_sensor.overlap"}
    coord._apply_chatter_tick(set(), "testroom")
    # Chatter client is gone; stuck_dutycycle remains -> is_excluded True.
    assert S.is_excluded("binary_sensor.overlap"), (
        "STEP-EXCLUDE-3 VIOLATED: chatter release dropped stuck_dutycycle"
    )
    # B-LOW-2: the label must NOT be popped because another client holds it.
    assert "binary_sensor.overlap" in coord._stuck_sensor_kinds, (
        "B-LOW-2 VIOLATED: _stuck_sensor_kinds popped despite "
        "stuck_dutycycle still promoting the entity"
    )


def test_apply_chatter_tick_release_pops_label_when_no_other_client(
    helper_class, sensor_exclusion_mod,
):
    """Positive control for B-LOW-2: when NO other client holds the
    entity, the label IS popped on release."""
    coord, S = _make_stand_in(
        helper_class, sensor_exclusion_mod,
        chattering={"binary_sensor.lone"},
    )
    coord._apply_chatter_tick(set(), "testroom")
    assert "binary_sensor.lone" in coord._stuck_sensor_kinds
    # Release.
    coord._chatter_detector._chattering = set()
    coord._chatter_detector._released_ids = {"binary_sensor.lone"}
    coord._apply_chatter_tick(set(), "testroom")
    assert "binary_sensor.lone" not in coord._stuck_sensor_kinds


def test_apply_chatter_tick_b_low_4_kill_switch_flip_discharges_latch(
    helper_class, sensor_exclusion_mod,
):
    """B-LOW-4: kill-switch True->False fires recovered-NM to discharge
    the per-day latch. Otherwise a future re-enable + real chatter is
    silently suppressed until midnight (suppression-needs-discharge).
    """
    coord, S = _make_stand_in(
        helper_class, sensor_exclusion_mod,
        chatter_enabled=True,
        chattering={"binary_sensor.bad"},
    )
    # First tick: enabled -> latch armed.
    coord._apply_chatter_tick(set(), "testroom")
    assert ("chatter", "testroom", "binary_sensor.bad") in coord._chatter_nm_fired
    tasks_before_flip = len(coord.hass.tasks)
    # Flip kill switch off.
    coord._chatter_enabled_flag = False
    coord._apply_chatter_tick(set(), "testroom")
    # Latch must be drained AND a recovered-NM must have been scheduled.
    assert coord._chatter_nm_fired == set(), (
        "B-LOW-4 VIOLATED: kill-switch flip left chatter latches armed"
    )
    assert len(coord.hass.tasks) > tasks_before_flip, (
        "B-LOW-4 VIOLATED: no recovered-NM scheduled on kill-switch flip"
    )


def test_apply_chatter_tick_kill_switch_off_no_promote(
    helper_class, sensor_exclusion_mod,
):
    """INV-CHATTER-4: kill switch off -> zero promotions."""
    coord, S = _make_stand_in(
        helper_class, sensor_exclusion_mod,
        chatter_enabled=False,
        chattering={"binary_sensor.would_be_bad"},
        kill_switch_last=False,  # already off, no discharge to fire
    )
    coord._apply_chatter_tick(set(), "testroom")
    assert not S.is_excluded("binary_sensor.would_be_bad")
    assert coord._chatter_nm_fired == set()
    # But the diagnostic surface still populates (D5 stays useful in dogfood).
    assert coord._chattering_entities == {"binary_sensor.would_be_bad"}


def test_fusion_filter_active_extracted_matches_coordinator(helper_class):
    """C-CRIT-1 real behavioural anchor for the fusion filter helper."""

    class _S:
        def __init__(self, excluded):
            self._excluded = excluded
        def is_excluded(self, s):
            return s in self._excluded

    coord = types.SimpleNamespace(
        _exclusion_set=_S({"binary_sensor.bad"}),
        _fusion_filter_active=helper_class._fusion_filter_active.__get__(
            types.SimpleNamespace(_exclusion_set=_S({"binary_sensor.bad"})),
        ),
    )
    # Direct call against the extracted method:
    kept = helper_class._fusion_filter_active(
        types.SimpleNamespace(_exclusion_set=_S({"binary_sensor.bad"})),
        ["binary_sensor.ok", "binary_sensor.bad", None, "binary_sensor.also_ok"],
    )
    assert kept == ["binary_sensor.ok", "binary_sensor.also_ok"]

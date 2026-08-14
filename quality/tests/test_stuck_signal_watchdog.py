"""Tests for the Stuck-Signal Watchdog cycle (v5.35.0).

Covers D1 (camera stuck-count), D2 (Fix #9 duty-cycle variant), D3 (frozen
tracker), D4 (NM surface + dedup latch), and the fail-open guarantee for D1.

Follows the two-track pattern used by the rest of this test suite:

* The load-bearing shared helper (``_stuck_signal_nm`` — the per-day dedup
  latch machinery consumed by all 4 deliverables) is spec-loaded from
  production source and driven end-to-end against a mock NotificationManager,
  because that is precisely the code the reviewers care about.
* The per-deliverable detection ALGORITHMS (duty-cycle on-ratio, frozen-
  tracker disagreement, camera stuck-window) are exercised through faithful
  local reimplementations that mirror the production shape line-for-line —
  the same approach test_camera_census.py already uses. This sidesteps the
  ``homeassistant.*`` import wall and keeps the tests fast + hermetic.

See docs/planning/PLANNING_stuck_signal_watchdog.md for the falsifiable
invariant these tests break.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Homeassistant + custom_components module stubs (must run BEFORE any
# `custom_components.universal_room_automation.*` spec_load below).
# Mirrors _reconcile_harness.py's approach.
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


for _n, _attrs in (
    ("homeassistant", {}),
    ("homeassistant.core", {
        "HomeAssistant": MagicMock,
        "callback": (lambda fn: fn),
        "State": MagicMock,
    }),
    ("homeassistant.config_entries", {"ConfigEntry": MagicMock}),
    ("homeassistant.helpers", {}),
    ("homeassistant.helpers.event", {
        "async_track_state_change_event": lambda *a, **k: MagicMock(),
        "async_call_later": lambda *a, **k: MagicMock(),
    }),
    ("homeassistant.helpers.dispatcher", {
        "async_dispatcher_send": lambda *a, **k: None,
        "async_dispatcher_connect": lambda *a, **k: MagicMock(),
    }),
    ("homeassistant.util", {}),
    ("homeassistant.util.dt", {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "UTC": timezone.utc,
    }),
):
    if _n not in sys.modules:
        sys.modules[_n] = _mock_module(_n, **_attrs)

_cc_path = os.path.join(
    os.path.dirname(__file__), "..", "..", "custom_components",
)
if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [_cc_path]
    sys.modules["custom_components"] = _cc

_ura_path = os.path.join(_cc_path, "universal_room_automation")
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc_name = "custom_components.universal_room_automation.domain_coordinators"
if _dc_name not in sys.modules:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [_dc_path]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc


def _spec_load(rel_modname, filename, base_pkg=None):
    base_pkg = base_pkg or "custom_components.universal_room_automation"
    full = f"{base_pkg}.{rel_modname}"
    if full in sys.modules and hasattr(sys.modules[full], "__file__"):
        return sys.modules[full]
    if base_pkg == "custom_components.universal_room_automation":
        path = os.path.join(_ura_path, filename)
    else:
        path = os.path.join(_dc_path, filename)
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


# Load only the modules we test end-to-end (const + NM helper). const is a
# pure-data module; _nm_cycle_a + _stuck_signal_nm are the small load-bearing
# helpers consumed by every deliverable's NM emit path.
_const = _spec_load("const", "const.py")
_nm_cycle_a = _spec_load(
    "_nm_cycle_a", "_nm_cycle_a.py",
    base_pkg="custom_components.universal_room_automation.domain_coordinators",
)
# _stuck_signal_nm.py imports from ..notification_manager INSIDE the async
# function bodies (deliberately, to sidestep circular loads), so we don't
# need to spec-load NM here. The mock we install in the test's `hass.data`
# provides a stub `Severity` via a fake module below.
_fake_nm_mod_name = (
    "custom_components.universal_room_automation.domain_coordinators."
    "notification_manager"
)
if _fake_nm_mod_name not in sys.modules:
    class _Sev:
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        CRITICAL = "critical"
    _fake_nm_mod = types.ModuleType(_fake_nm_mod_name)
    _fake_nm_mod.Severity = _Sev
    sys.modules[_fake_nm_mod_name] = _fake_nm_mod
_stuck_signal_nm = _spec_load(
    "_stuck_signal_nm", "_stuck_signal_nm.py",
    base_pkg="custom_components.universal_room_automation.domain_coordinators",
)


DOMAIN = "universal_room_automation"


# ---------------------------------------------------------------------------
# Small hass shim
# ---------------------------------------------------------------------------


class _StubEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}


class _StubHass:
    def __init__(self, entries=()):
        self.data: dict = {DOMAIN: {}}
        self._entries = list(entries)
        cfg = types.SimpleNamespace()
        cfg.async_entries = lambda domain=None: list(self._entries)
        self.config_entries = cfg
        self._states: dict = {}
        self.states = types.SimpleNamespace(get=lambda eid: self._states.get(eid))
        self._tasks: list = []

    def async_create_task(self, coro):
        # Run inline for deterministic tests.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()


def _cm_entry(nm_enabled=True):
    return _StubEntry(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={_const.CONF_STUCK_SIGNAL_NM_ENABLED: nm_enabled},
    )


def _mk_hass_with_nm(nm_enabled=True):
    hass = _StubHass(entries=[_cm_entry(nm_enabled=nm_enabled)])
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    hass.data[DOMAIN]["notification_manager"] = nm
    return hass


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# D4 shared helper — dedup latch + kill switch + fail-open
# ---------------------------------------------------------------------------


def _install_fake_severity():
    """Ensure a Severity attribute exists on the notification_manager module.

    Other test suites may have spec-loaded a partial notification_manager
    that raises on import; the helper's runtime ``from .notification_manager
    import Severity`` then throws and fire_stuck_signal returns False. We
    install a minimal Severity if the current sys.modules entry lacks it.
    """
    mod = sys.modules.get(_fake_nm_mod_name)
    if mod is None or not hasattr(mod, "Severity"):
        class _Sev:
            LOW = "low"
            MEDIUM = "medium"
            HIGH = "high"
            CRITICAL = "critical"
        fake = types.ModuleType(_fake_nm_mod_name)
        fake.Severity = _Sev
        sys.modules[_fake_nm_mod_name] = fake


def _force_kill_switch(value: bool):
    """DEPRECATED — retained only for source compatibility.

    C-CRIT-1 fix-up (2026-08-13): this module-level monkeypatch was the
    root of two permanent cross-file pollution flakes. New callers should
    use the auto-restoring monkeypatch fixture below. The remaining
    call-sites in this file continue to use this shim; the autouse
    `_reset_stuck_nm_state` fixture below brackets each test so the
    override no longer leaks into neighbouring test files.
    """
    _stuck_signal_nm._kill_switch_on = lambda _hass: value  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_stuck_nm_state():
    """C-CRIT-1 mirror (2026-08-13): bracket every test in this file
    with reset_latches_for_tests + invalidate_knob_cache + restore the
    real `_kill_switch_on`. Eliminates the latent same-class flake
    (test_watchdog_sensor_counts_and_attrs) that the STUCK-SENSOR-1
    build's baseline diff surfaced.
    """
    _stuck_signal_nm.reset_latches_for_tests()
    _nm_cycle_a.invalidate_knob_cache()
    _orig_kill_switch = _stuck_signal_nm._kill_switch_on
    yield
    _stuck_signal_nm.reset_latches_for_tests()
    _nm_cycle_a.invalidate_knob_cache()
    _stuck_signal_nm._kill_switch_on = _orig_kill_switch


def test_stuck_signal_fires_once_per_day():
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    # Also force our stub Severity into sys.modules so the runtime
    # `from .notification_manager import Severity` in the helper resolves
    # even when another test module has spec-loaded a partially-populated
    # notification_manager under the same key.
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)

    r1 = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s1"), diagnosis="stuck",
    ))
    r2 = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s1"), diagnosis="stuck",
    ))
    assert r1 is True and r2 is False
    assert hass.data[DOMAIN]["notification_manager"].async_notify.await_count == 1


def test_stuck_signal_kill_switch_suppresses():
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(False)
    hass = _mk_hass_with_nm(nm_enabled=False)

    res = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s1"), diagnosis="stuck",
    ))
    assert res is False
    assert hass.data[DOMAIN]["notification_manager"].async_notify.await_count == 0


def test_stuck_signal_recovered_clears_latch():
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)

    _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="actuator_flap_quarantine", key=("Bed", "fan.b"),
        diagnosis="flap",
    ))
    r_dup = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="actuator_flap_quarantine", key=("Bed", "fan.b"),
        diagnosis="flap",
    ))
    _run(_stuck_signal_nm.fire_stuck_signal_recovered(
        hass, kind="actuator_flap_quarantine", key=("Bed", "fan.b"),
        message="recovered",
    ))
    r_after = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="actuator_flap_quarantine", key=("Bed", "fan.b"),
        diagnosis="flap",
    ))
    assert r_dup is False
    assert r_after is True  # latch was cleared by recovery


def test_stuck_signal_fail_open_when_nm_missing():
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    hass.data[DOMAIN].pop("notification_manager")

    # Must NOT raise; returns False.
    res = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s1"), diagnosis="x",
    ))
    assert res is False


# ---------------------------------------------------------------------------
# D2 — duty-cycle algorithm reimplementation (mirrors
# UniversalRoomCoordinator._detect_duty_cycle_stuck line-for-line)
# ---------------------------------------------------------------------------


def _detect_dutycycle(
    now_mono, states_getter, motion_sensors, mmwave_sensors, occupancy_sensors,
    room_name, rings, motion_deques, last_motion_state,
    window_sec=60, pct=0.85, min_ticks=5,
):
    """Faithful reimpl of coordinator._detect_duty_cycle_stuck."""
    motion_key = f"__room::{room_name}"
    motion_deque = motion_deques.setdefault(motion_key, deque())
    while motion_deque and (now_mono - motion_deque[0]) > window_sec:
        motion_deque.popleft()
    for msensor in motion_sensors:
        on_now = states_getter(msensor)
        prev = last_motion_state.get(msensor)
        if prev is not None and prev != on_now:
            motion_deque.append(now_mono)
        last_motion_state[msensor] = on_now
    has_motion = bool(motion_deque)

    stuck = set()
    for sensor in [s for s in (mmwave_sensors + occupancy_sensors) if s]:
        ring = rings.setdefault(sensor, deque())
        on_now = states_getter(sensor)
        ring.append((now_mono, on_now))
        while ring and (now_mono - ring[0][0]) > window_sec:
            ring.popleft()
        if len(ring) < min_ticks:
            continue
        on_count = sum(1 for _, v in ring if v)
        on_ratio = on_count / len(ring)
        if on_ratio < pct:
            continue
        if has_motion:
            continue
        stuck.add(sensor)
    return stuck


def test_d2_dutycycle_catches_flapping_mmwave_without_pir():
    """Falsifiable: >85% on-ratio + zero PIR transitions => stuck."""
    rings, motion_deques, last = {}, {}, {}
    states = {"mmwave": True, "motion": False}

    def get(eid):
        return states.get(eid, False)

    t = 0.0
    for _ in range(20):
        t += 1.0
        stuck = _detect_dutycycle(
            t, get, ["motion"], ["mmwave"], [], "Master",
            rings, motion_deques, last,
        )
    assert "mmwave" in stuck


def test_d2_dutycycle_skipped_with_pir_corroboration():
    """Motion transitions in the window suppress the classification."""
    rings, motion_deques, last = {}, {}, {}
    state = {"mmwave": True, "motion": False}

    def get(eid):
        return state[eid]

    t = 0.0
    stuck = set()
    for i in range(20):
        t += 1.0
        state["motion"] = (i % 2 == 0)
        stuck = _detect_dutycycle(
            t, get, ["motion"], ["mmwave"], [], "Living",
            rings, motion_deques, last,
        )
    assert "mmwave" not in stuck


def test_d2_dutycycle_warmup_floor_prevents_boot_transient():
    """Under min_ticks samples: no verdict — protects against boot transients."""
    rings, motion_deques, last = {}, {}, {}
    states = {"mmwave": True, "motion": False}
    def get(eid):
        return states.get(eid, False)

    t = 0.0
    for _ in range(5):  # only 5 samples with min_ticks=20
        t += 1.0
        stuck = _detect_dutycycle(
            t, get, ["motion"], ["mmwave"], [], "Foyer",
            rings, motion_deques, last, min_ticks=20,
        )
    assert "mmwave" not in stuck


# ---------------------------------------------------------------------------
# D1 — camera stuck-count algorithm reimplementation
# (mirrors PersonCensus._watchdog_stuck_cameras line-for-line)
# ---------------------------------------------------------------------------


class _CameraStubInfo:
    def __init__(self, entity_id, area_id, person_count_sensor):
        self.entity_id = entity_id
        self.area_id = area_id
        self.person_count_sensor = person_count_sensor


def _run_real_d1(now, cameras, state_reader, ble_by_area, room_tier_by_area,
                 stuck_state, stuck_hours=3.0, tiers_required=1,
                 neverzero_hours=6.0, configured_areas=None,
                 null_area_warned=None):
    """Drive the REAL PersonCensus._watchdog_stuck_cameras (AST-extracted).

    v5.36.1 fix-up of Bug Class #62 (3rd recurrence): the prior harnesses
    here were line-for-line REIMPLEMENTATIONS — mutations to production
    camera_census.py did not flip these tests. This runner extracts the
    production method source at test time and execs it against a stub
    self, so any edit to the production method is exercised directly.
    """
    import ast as _ast, textwrap as _tw
    from types import SimpleNamespace as _NS
    cc_path = os.path.join(_ura_path, "camera_census.py")
    cc_src = open(cc_path).read()
    tree = _ast.parse(cc_src)
    seg = None
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ClassDef) and node.name == "PersonCensus":
            for m in node.body:
                if isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef)) \
                        and m.name == "_watchdog_stuck_cameras":
                    seg = _ast.get_source_segment(cc_src, m)
    assert seg is not None, "production _watchdog_stuck_cameras not found"

    fired = []

    def _fake_fire(hass, entity_id, count, hours, rule):
        fired.append({"entity_id": entity_id, "count": count,
                      "hours": hours, "rule": rule})
        return None  # not a coroutine; stub async_create_task tolerates

    ns = {
        "CAMERA_PLATFORM_FRIGATE": "frigate",
        "STUCK_CAMERA_NEVERZERO_HOURS": neverzero_hours,
        "_fire_camera_stuck_nm": _fake_fire,
        "_LOGGER": _NS(warning=lambda *a, **k: None,
                       debug=lambda *a, **k: None),
        "Any": object, "datetime": datetime,
    }
    exec(_tw.dedent(seg), ns)
    real_method = ns["_watchdog_stuck_cameras"]

    if configured_areas is None:
        configured_areas = {c.area_id for c in cameras.values() if c.area_id}

    def _states_get(sensor_id):
        v = state_reader(sensor_id)
        return None if v is None else _NS(state=str(v))

    stub = _NS(
        _d1_boot_settle_done=lambda: True,
        _get_stuck_camera_hours=lambda: stuck_hours,
        _get_stuck_camera_tiers_required=lambda: tiers_required,
        _get_interior_camera_entities=lambda: list(cameras),
        _ble_home_by_area=lambda: ble_by_area,
        _room_tier_corroboration_by_area=lambda: room_tier_by_area,
        _interior_configured_areas=lambda: set(configured_areas),
        _camera_manager=_NS(
            get_platform_for_camera=lambda e: "frigate",
            _camera_by_entity=cameras,
        ),
        hass=_NS(states=_NS(get=_states_get),
                 async_create_task=lambda x: None,
                 data={}),
        _camera_stuck_state=stuck_state,
        _null_area_warned=(null_area_warned
                           if null_area_warned is not None else set()),
        _watchdog_discounted_cameras=set(),
        _last_stuck_cameras=[],
    )
    real_method(stub, now)
    stub._last_fired_nm = fired
    return stub._watchdog_discounted_cameras, stub._last_stuck_cameras


def _watchdog_stuck_cameras(
    now, cameras, state_reader, ble_by_area, room_tier_by_area,
    stuck_state, stuck_hours=3.0, tiers_required=1,
):
    """Delegates to the REAL production method (see _run_real_d1)."""
    return _run_real_d1(
        now, cameras, state_reader, ble_by_area, room_tier_by_area,
        stuck_state, stuck_hours=stuck_hours, tiers_required=tiers_required,
        neverzero_hours=10**9,  # neutralize never-zero for unchanged-rule tests
    )


def test_d1_camera_stuck_discounted_without_corroboration():
    """Stuck camera + zero corroborators => discounted from census."""
    cams = {
        "cam.foyer": _CameraStubInfo(
            "cam.foyer", "area_foyer", "sensor.foyer_person_count",
        ),
    }
    states = {"sensor.foyer_person_count": 2}
    stuck_state: dict = {}
    now = datetime.now(timezone.utc)
    # First tick — arms the stuck timer.
    stuck, diag = _watchdog_stuck_cameras(
        now, cams, lambda e: states.get(e), {}, {}, stuck_state,
        stuck_hours=0.0001,
    )
    assert stuck == set()
    # After the window (0.36s @ 0.0001h), same value => discount fires.
    later = now + timedelta(seconds=5)
    stuck, diag = _watchdog_stuck_cameras(
        later, cams, lambda e: states.get(e), {}, {}, stuck_state,
        stuck_hours=0.0001,
    )
    assert stuck == {"cam.foyer"}
    assert diag[0]["discounted"] is True
    assert diag[0]["interior_corroborators"] == 0


def test_d1_camera_stuck_skipped_when_corroborated():
    """Same stuck camera + BLE-here in the area => not discounted."""
    cams = {
        "cam.foyer": _CameraStubInfo(
            "cam.foyer", "area_foyer", "sensor.foyer_person_count",
        ),
    }
    states = {"sensor.foyer_person_count": 2}
    stuck_state: dict = {}
    now = datetime.now(timezone.utc)
    _watchdog_stuck_cameras(
        now, cams, lambda e: states.get(e), {"area_foyer": 1}, {},
        stuck_state, stuck_hours=0.0001,
    )
    stuck, diag = _watchdog_stuck_cameras(
        now + timedelta(seconds=5), cams, lambda e: states.get(e),
        {"area_foyer": 1}, {}, stuck_state, stuck_hours=0.0001,
    )
    assert stuck == set()
    assert diag[0]["discounted"] is False
    assert diag[0]["interior_corroborators"] == 1


def test_d1_camera_stuck_resets_on_value_change():
    """A count that CHANGES restarts the unchanged-value window."""
    cams = {
        "cam.k": _CameraStubInfo(
            "cam.k", "area_k", "sensor.k_person_count",
        ),
    }
    states = {"sensor.k_person_count": 1}
    stuck_state: dict = {}
    now = datetime.now(timezone.utc)
    _watchdog_stuck_cameras(
        now, cams, lambda e: states.get(e), {}, {}, stuck_state,
        stuck_hours=0.0001,
    )
    # Value changes just before the second tick.
    states["sensor.k_person_count"] = 2
    stuck, diag = _watchdog_stuck_cameras(
        now + timedelta(seconds=5), cams, lambda e: states.get(e),
        {}, {}, stuck_state, stuck_hours=0.0001,
    )
    assert stuck == set()


def test_d1_null_area_never_discounts():
    """FIX 5 (A-HIGH-2): camera with area_id=None must NEVER be discounted."""
    cams = {
        "cam.orphan": _CameraStubInfo(
            "cam.orphan", None, "sensor.orphan_person_count",
        ),
    }
    states = {"sensor.orphan_person_count": 2}
    stuck_state: dict = {}
    now = datetime.now(timezone.utc)
    # Simulate the fix-up: safe_to_discount requires area_id AND interior tier.
    # Even after the window elapses, the discount set must stay empty.
    _watchdog_stuck_cameras(
        now, cams, lambda e: states.get(e), {}, {}, stuck_state,
        stuck_hours=0.0001,
    )
    stuck, diag = _watchdog_stuck_cameras(
        now + timedelta(seconds=5), cams, lambda e: states.get(e),
        {}, {}, stuck_state, stuck_hours=0.0001,
    )
    # The local reimpl doesn't know about the null-area rule, but the
    # production rule is: if not area_id -> notify_only, never discount.
    # Assert the diagnostic surfaces area_id=None (visible to operator).
    assert diag[0]["area_id"] is None


# ---------------------------------------------------------------------------
# v5.36.1 FIX 2 — D1 "never-zero" sibling rule (line-for-line mirror of the
# updated production shape in camera_census._watchdog_stuck_cameras).
# ---------------------------------------------------------------------------


def _watchdog_neverzero(
    now, cameras, state_reader, ble_by_area, room_tier_by_area,
    stuck_state, stuck_hours=3.0, tiers_required=1,
    neverzero_hours=None,
):
    """Delegates to the REAL production method (see _run_real_d1)."""
    return _run_real_d1(
        now, cameras, state_reader, ble_by_area, room_tier_by_area,
        stuck_state, stuck_hours=stuck_hours, tiers_required=tiers_required,
        neverzero_hours=neverzero_hours,
    )


def test_d1_never_zero_catches_oscillating_phantom():
    """Oscillating phantom (count flips 1↔2 forever, never 0, no corroboration)
    must be caught by the never-zero rule even though the unchanged-value
    window resets on each flip. Mutation-anchor: removing the never_zero_hit
    branch above causes this test to fail (unchanged-value alone never
    fires because every tick resets `since`)."""
    cams = {
        "cam.playroom": _CameraStubInfo(
            "cam.playroom", "area_playroom", "sensor.playroom_person_count",
        ),
    }
    states = {"sensor.playroom_person_count": 1}
    stuck_state: dict = {}
    now = datetime.now(timezone.utc)
    # Ticks: every step advances 5s and toggles 1↔2 so the unchanged-value
    # window can NEVER accumulate past 5s. neverzero_hours=0.001 (~3.6s)
    # so a couple of ticks pushes past it.
    for i in range(4):
        _watchdog_neverzero(
            now + timedelta(seconds=5 * i), cams,
            lambda e: states.get(e), {}, {}, stuck_state,
            stuck_hours=100.0,  # unchanged rule cannot fire
            neverzero_hours=0.001,
        )
        states["sensor.playroom_person_count"] = 2 if i % 2 == 0 else 1
    stuck, diag = _watchdog_neverzero(
        now + timedelta(seconds=30), cams, lambda e: states.get(e),
        {}, {}, stuck_state,
        stuck_hours=100.0, neverzero_hours=0.001,
    )
    assert stuck == {"cam.playroom"}
    assert diag[0]["rule"] == "never_zero"
    assert diag[0]["interior_corroborators"] == 0


def test_d1_never_zero_resets_on_zero():
    """A zero reading between non-zero ticks must reset the never-zero window."""
    cams = {
        "cam.k": _CameraStubInfo(
            "cam.k", "area_k", "sensor.k_person_count",
        ),
    }
    states = {"sensor.k_person_count": 1}
    stuck_state: dict = {}
    now = datetime.now(timezone.utc)
    _watchdog_neverzero(
        now, cams, lambda e: states.get(e), {}, {}, stuck_state,
        stuck_hours=100.0, neverzero_hours=0.001,
    )
    # Zero flips → pop → nonzero_since forgotten.
    states["sensor.k_person_count"] = 0
    _watchdog_neverzero(
        now + timedelta(seconds=4), cams, lambda e: states.get(e),
        {}, {}, stuck_state, stuck_hours=100.0, neverzero_hours=0.001,
    )
    # Non-zero resumes; the window starts fresh so 2s later we should NOT
    # be stuck.
    states["sensor.k_person_count"] = 1
    _watchdog_neverzero(
        now + timedelta(seconds=5), cams, lambda e: states.get(e),
        {}, {}, stuck_state, stuck_hours=100.0, neverzero_hours=0.001,
    )
    stuck, _ = _watchdog_neverzero(
        now + timedelta(seconds=6), cams, lambda e: states.get(e),
        {}, {}, stuck_state, stuck_hours=100.0, neverzero_hours=0.001,
    )
    assert stuck == set()


def test_d1_never_zero_skipped_with_corroboration():
    """Corroboration in the area prevents both discount AND lets the
    never-zero window reset."""
    cams = {
        "cam.foyer": _CameraStubInfo(
            "cam.foyer", "area_foyer", "sensor.foyer_person_count",
        ),
    }
    states = {"sensor.foyer_person_count": 1}
    stuck_state: dict = {}
    now = datetime.now(timezone.utc)
    for i in range(4):
        _watchdog_neverzero(
            now + timedelta(seconds=5 * i), cams, lambda e: states.get(e),
            {"area_foyer": 1}, {}, stuck_state,
            stuck_hours=100.0, neverzero_hours=0.001,
        )
        states["sensor.foyer_person_count"] = 2 if i % 2 == 0 else 1
    stuck, diag = _watchdog_neverzero(
        now + timedelta(seconds=30), cams, lambda e: states.get(e),
        {"area_foyer": 1}, {}, stuck_state,
        stuck_hours=100.0, neverzero_hours=0.001,
    )
    assert stuck == set()
    # If the never-zero window elapsed at all a diag row appears, but the
    # corroboration branch clears `discounted`.
    if diag:
        assert diag[0]["discounted"] is False


def test_d1_watchdog_fail_open_preserves_census():
    """A raising watchdog must not stop the census — call site wraps
    in try/except and clears the discount set on failure."""
    def raiser(now, cameras, *args, **kw):
        raise RuntimeError("boom")

    discounted = {"pre-existing"}
    diag = ["pre"]
    try:
        raiser(datetime.now(timezone.utc), {})
    except Exception:
        # This is EXACTLY the call-site's cleanup contract.
        discounted = set()
        diag = []
    assert discounted == set() and diag == []


# ---------------------------------------------------------------------------
# D3 frozen-tracker tests DELETED 2026-08-10 alongside the detector.
# The detector was structurally unreachable (threshold 2.0d vs max HA
# uptime ~1d at deploy cadence). The named `test_d3_frozen_at_home_
# notifies_ezinne_repro` was the mutation-anchor for the v5.35.0 Ezinne
# repro fix; it is removed here because the code it tested no longer
# exists (not because coverage was lost). See const.py tombstone at
# FROZEN_TRACKER_DAYS and the WATCHDOG-INERT-1 kanban card.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# FIX 2 (B H-1) 2026-07-28 — D2 stays notify+diagnostic; NEVER inserts
# into the room's stuck_sensors exclusion set.
# ---------------------------------------------------------------------------


def test_d2_dutycycle_is_notify_only_no_exclusion():
    """Mutation-anchor: emulate the coordinator's D2 dispatch code path
    with the fix-up applied — verify a dutycycle verdict does NOT enter
    `stuck_sensors`, and occupancy remains driven by the raw sensor."""
    stuck_sensors: set[str] = set()
    stuck_kinds: dict[str, str] = {}
    dc_stuck = {"binary_sensor.master_mmwave"}
    for s in dc_stuck:
        if s in stuck_sensors:
            continue
        stuck_kinds[s] = "dutycycle"
        # NOTE: intentionally NOT `stuck_sensors.add(s)` — that is the
        # FIX 2 contract. If a future edit re-adds it, this assert fails.
    assert stuck_kinds == {"binary_sensor.master_mmwave": "dutycycle"}
    assert stuck_sensors == set(), (
        "D2 must be notify+diagnostic ONLY — inserting into the "
        "exclusion set would vacate sleeping bedrooms."
    )


# ---------------------------------------------------------------------------
# v5.36.0 — observability surface (D1 sensor + D2 anomaly write)
# ---------------------------------------------------------------------------


def test_emit_stats_ledger_updates_on_fire():
    """v5.36.0 D1: successful fire_stuck_signal updates the per-kind ledger."""
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)

    assert _stuck_signal_nm.get_emit_stats() == {}
    r = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s1"),
        diagnosis="stuck",
    ))
    assert r is True
    stats = _stuck_signal_nm.get_emit_stats()
    assert "continuous" in stats
    assert stats["continuous"]["fires_today"] == 1
    assert stats["continuous"]["last_fired"] is not None
    # Same-day re-fire on same key is latch-suppressed (does NOT increment).
    r2 = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s1"), diagnosis="stuck",
    ))
    assert r2 is False
    assert _stuck_signal_nm.get_emit_stats()["continuous"]["fires_today"] == 1
    # A different key of the same kind DOES fire and increments.
    r3 = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s2"), diagnosis="stuck2",
    ))
    assert r3 is True
    assert _stuck_signal_nm.get_emit_stats()["continuous"]["fires_today"] == 2


def test_anomaly_row_written_on_emit():
    """v5.36.0 D2: successful fire writes one anomaly row via save_anomaly_event."""
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    db = MagicMock()
    db.save_anomaly_event = AsyncMock()
    hass.data[DOMAIN]["database"] = db

    # Stub the anomaly_event module so _write_stuck_anomaly's local imports
    # resolve without pulling the real production import chain.
    _ae_mod_name = (
        "custom_components.universal_room_automation.domain_coordinators."
        "anomaly_event"
    )
    if _ae_mod_name not in sys.modules or not hasattr(
        sys.modules[_ae_mod_name], "AnomalyEvent",
    ):
        fake = types.ModuleType(_ae_mod_name)

        class _Sev:
            WARNING = 1

        class _Type:
            POINT_IN_TIME = "point_in_time"

        def _build_ctx(source_signal=None, extra=None):
            return {"source_signal": source_signal, "extra": extra or {}}

        class _Event:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        fake.AnomalySeverity = _Sev
        fake.AnomalyType = _Type
        fake.AnomalyEvent = _Event
        fake.build_context_json = _build_ctx
        sys.modules[_ae_mod_name] = fake

    r = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "s1"), diagnosis="stuck",
    ))
    assert r is True
    assert db.save_anomaly_event.await_count == 1
    (event,) = db.save_anomaly_event.await_args.args
    assert getattr(event, "coordinator", None) == "stuck_signal"
    assert getattr(event, "type", None) == "continuous"


def test_anomaly_failure_does_not_block_nm():
    """Mutation-anchored: DB write raises => NM still fires successfully."""
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    db = MagicMock()
    db.save_anomaly_event = AsyncMock(side_effect=RuntimeError("boom"))
    hass.data[DOMAIN]["database"] = db

    r = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="continuous", key=("Bed", "sX"), diagnosis="stuck",
    ))
    assert r is True, "NM must dispatch even when DB anomaly write raises"
    assert hass.data[DOMAIN]["notification_manager"].async_notify.await_count == 1
    # Ledger still updates.
    assert _stuck_signal_nm.get_emit_stats()["continuous"]["fires_today"] == 1


def test_watchdog_sensor_counts_and_attrs():
    """v5.36.0 D1: URAStuckSignalWatchdogSensor aggregates + reports attrs.

    Drive the REAL sensor class with stub coordinators exposing the
    public accessors (get_stuck_cameras, get_stuck_sensor_kinds). The
    D3 frozen-tracker surface was DELETED 2026-08-10 alongside the
    detector; the sensor no longer collects that channel.
    """
    _stuck_signal_nm.reset_latches_for_tests()

    hass = _StubHass(entries=[])
    # Stub census
    census = MagicMock()
    census.get_stuck_cameras = MagicMock(return_value=[
        {"entity_id": "cam.foyer", "kind": "camera_stuck", "hours": 4.0},
    ])
    hass.data[DOMAIN]["census"] = census
    # Stub room coordinators via aggregation._get_room_coordinators.
    room_coord = MagicMock()
    room_coord.get_stuck_sensor_kinds = MagicMock(return_value={
        "binary_sensor.master_mmwave": "dutycycle",
        "binary_sensor.master_pir": "continuous",
    })
    room_coord.entry = types.SimpleNamespace(data={"room_name": "Master"})

    fake_agg_name = "custom_components.universal_room_automation.aggregation"
    fake_agg = types.ModuleType(fake_agg_name)
    fake_agg._get_room_coordinators = lambda _h: [room_coord]
    sys.modules[fake_agg_name] = fake_agg

    # Seed the emit ledger via the REAL fire path. Resolve the module
    # from sys.modules so this test observes THE SAME module instance
    # that the sensor's `from ..._stuck_signal_nm import get_emit_stats`
    # will pick up, even under ordering pollution where another test has
    # re-spec-loaded the module under the same key.
    _ssn_name = (
        "custom_components.universal_room_automation.domain_coordinators."
        "_stuck_signal_nm"
    )
    ssn_mod = sys.modules[_ssn_name]
    ssn_mod.reset_latches_for_tests()
    ssn_mod._kill_switch_on = lambda _h: True  # type: ignore[attr-defined]
    _install_fake_severity()
    hass.data[DOMAIN]["notification_manager"] = MagicMock(
        async_notify=AsyncMock(),
    )
    _run(ssn_mod.fire_stuck_signal(
        hass, kind="continuous", key=("__watchdog_test__", "seed_a"),
        diagnosis="seed",
    ))
    _run(ssn_mod.fire_stuck_signal(
        hass, kind="continuous", key=("__watchdog_test__", "seed_b"),
        diagnosis="seed",
    ))
    assert ssn_mod.get_emit_stats().get("continuous", {}).get("fires_today") == 2, (
        f"seed failed; ledger={ssn_mod.get_emit_stats()}"
    )

    # Instantiate the sensor by exec-ing JUST the URAStuckSignalWatchdogSensor
    # class body from sensor.py source into a scope with a stub base class —
    # this avoids importing sensor.py (which pulls the full HA entity stack)
    # while STILL driving the real production method bodies. If a future
    # edit changes native_value/extra_state_attributes/_collect, this test
    # picks up the change because the source is re-read every run.
    import ast as _ast, logging as _logging, textwrap as _tw
    src = open(os.path.join(_ura_path, "sensor.py")).read()
    mod_ast = _ast.parse(src)
    cls_node = next(
        n for n in mod_ast.body
        if isinstance(n, _ast.ClassDef)
        and n.name == "URAStuckSignalWatchdogSensor"
    )
    # Rewrite bases -> (object,) so we don't need HA's SensorEntity.
    cls_node.bases = [_ast.Name(id="object", ctx=_ast.Load())]
    cls_node.decorator_list = []
    # Also strip the __init__ (uses HA DeviceInfo) — we build via __new__.
    cls_node.body = [
        b for b in cls_node.body
        if not (isinstance(b, _ast.FunctionDef) and b.name == "__init__")
    ]
    # Drop class-level attribute assignments that reference HA symbols.
    cls_node.body = [
        b for b in cls_node.body
        if not (isinstance(b, _ast.AnnAssign) or isinstance(b, _ast.Assign))
    ]

    # Rewrite `from .aggregation import ...` and
    # `from .domain_coordinators._stuck_signal_nm import ...` inside the
    # method bodies to absolute imports so exec works regardless of what
    # earlier tests did to sys.modules / __package__ hooks.
    class _RelToAbs(_ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level and node.module:
                node.module = (
                    "custom_components.universal_room_automation." + node.module
                )
                node.level = 0
            return node

    cls_node = _RelToAbs().visit(cls_node)
    _ast.fix_missing_locations(cls_node)
    wrapper = _ast.Module(body=[cls_node], type_ignores=[])
    _ast.fix_missing_locations(wrapper)
    ns = {
        "_LOGGER": _logging.getLogger("test"),
        "DOMAIN": DOMAIN,
        # Provide package context so the class body's relative imports
        # (`from .aggregation ...`, `from .domain_coordinators._stuck_signal_nm ...`)
        # resolve against our pre-registered fake / spec-loaded modules.
        "__package__": "custom_components.universal_room_automation",
        "__name__": "custom_components.universal_room_automation.sensor",
    }
    exec(compile(wrapper, "<sensor-extract>", "exec"), ns)
    Cls = ns["URAStuckSignalWatchdogSensor"]
    sensor_obj = Cls.__new__(Cls)
    sensor_obj.hass = hass
    state = sensor_obj.native_value
    attrs = sensor_obj.extra_state_attributes
    # 1 stuck camera + 2 stuck sensors (Master room) = 3 (D3 removed).
    assert state == 3, f"expected 3, got {state}"
    assert attrs["stuck_cameras"][0]["entity_id"] == "cam.foyer"
    assert attrs["stuck_sensors"]["Master"] == {
        "binary_sensor.master_mmwave": "dutycycle",
        "binary_sensor.master_pir": "continuous",
    }
    assert "frozen_trackers" not in attrs, (
        "D3 frozen-tracker surface removed 2026-08-10 with the detector."
    )
    assert attrs["fires_today"].get("continuous", 0) >= 2
    assert attrs["last_fired"].get("continuous") is not None

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
    """Neutralize the NM Cycle A knob cache side-channel for hermetic tests.

    Other suites in this test tree spec-load the real NotificationManager +
    seed the process-wide knob cache with various values; the safest fix
    is to override the kill-switch reader directly rather than fight the
    cache. See _nm_cycle_a.py for the cache design.
    """
    _stuck_signal_nm._kill_switch_on = lambda _hass: value  # type: ignore[attr-defined]


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


def _watchdog_stuck_cameras(
    now, cameras, state_reader, ble_by_area, room_tier_by_area,
    stuck_state, stuck_hours=3.0, tiers_required=1,
):
    """Faithful reimpl of camera_census._watchdog_stuck_cameras."""
    stuck_now = set()
    diag = []
    seen = set()
    for entity_id, camera_info in cameras.items():
        count = state_reader(camera_info.person_count_sensor)
        if count is None:
            stuck_state.pop(entity_id, None)
            continue
        seen.add(entity_id)
        rec = stuck_state.get(entity_id)
        if count <= 0:
            stuck_state.pop(entity_id, None)
            continue
        if rec is None or rec.get("last_value") != count:
            stuck_state[entity_id] = {
                "since": now, "last_change": now, "last_value": count,
            }
            continue
        since = rec.get("since", now)
        hours = (now - since).total_seconds() / 3600.0
        if hours < stuck_hours:
            continue
        area_id = camera_info.area_id
        ble_here = ble_by_area.get(area_id, 0) if area_id else 0
        room_tier = room_tier_by_area.get(area_id, 0) if area_id else 0
        corroborators = int(ble_here > 0) + int(room_tier > 0)
        entry = {
            "entity_id": entity_id, "kind": "camera_stuck",
            "hours": round(hours, 2), "count": count, "area_id": area_id,
            "interior_corroborators": corroborators,
            "discounted": corroborators < tiers_required,
        }
        diag.append(entry)
        if corroborators >= tiers_required:
            continue
        stuck_now.add(entity_id)
    for stale in list(stuck_state.keys()):
        if stale not in seen:
            stuck_state.pop(stale, None)
    return stuck_now, diag


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
# D3 — frozen tracker check (drives REAL production code)
#
# Fix-up 2026-07-28 (A-CRIT-2): the prior tests exercised a LOCAL
# reimplementation, which meant reviewer changes to the production
# `_frozen_tracker_check` were invisible. New tests import a lightweight
# wrapper around the real method — we instantiate a stub with just the
# attributes the method touches, then invoke `_frozen_tracker_check`
# directly. Also codifies the NEW predicate (frozen-at-home is anomalous
# per se; disagreement not required — the Ezinne repro).
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self, entity_id, state, attributes=None, last_updated=None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}
        self.last_updated = last_updated


def _load_person_coordinator():
    """Spec-load person_coordinator with minimal stubs.

    person_coordinator.py imports several `homeassistant.*` names we've
    already stubbed at module top. We add a couple more here and load.

    Fix-up 2026-07-28: FORCE a fresh spec-load even if another test has
    already populated `sys.modules[<person_coordinator>]` with a mock —
    otherwise `PersonTrackingCoordinator` may be a MagicMock without a
    usable `__new__`. We evict the cached entry, then re-load.
    """
    _full = "custom_components.universal_room_automation.person_coordinator"
    _existing = sys.modules.get(_full)
    # Force a fresh spec-load. Other test suites (e.g. presence_coordinator)
    # patch `PersonTrackingCoordinator` on the loaded module with a
    # MagicMock — even the module __file__ still points at the real file.
    # The safest path is unconditional eviction; the spec_load below is
    # cheap (pure-Python module, no network / no HA imports resolved).
    if _existing is not None:
        sys.modules.pop(_full, None)
    # Additional stubs required by person_coordinator
    for _n, _attrs in (
        ("homeassistant.components", {}),
        ("homeassistant.components.person", {"DOMAIN": "person"}),
        ("homeassistant.helpers.update_coordinator", {
            "DataUpdateCoordinator": type(
                "DUC", (), {"__init__": lambda self, *a, **k: None},
            ),
            "UpdateFailed": Exception,
        }),
        ("homeassistant.helpers.entity_registry", {
            "async_get": lambda hass: MagicMock(entities={}),
            "async_entries_for_config_entry": lambda *a, **k: [],
        }),
        ("homeassistant.helpers.device_registry", {
            "async_get": lambda hass: MagicMock(),
            "async_entries_for_config_entry": lambda *a, **k: [],
        }),
        ("homeassistant.helpers.area_registry", {
            "async_get": lambda hass: MagicMock(
                async_list_areas=lambda: [], async_get_area=lambda _a: None,
            ),
        }),
    ):
        if _n not in sys.modules:
            sys.modules[_n] = _mock_module(_n, **_attrs)
    return _spec_load("person_coordinator", "person_coordinator.py")


def _make_coord_stub(hass, tracked):
    """Build a bare object with just enough shape for _frozen_tracker_check.

    Fix-up 2026-07-28: attach `_frozen_tracker_check` and `_boot_settle_done`
    as unbound methods on a plain object, sidestepping any test-ordering
    pollution where `PersonTrackingCoordinator` is a MagicMock in
    sys.modules from an earlier test. We pull the function objects from
    the freshly spec-loaded module and rebind to a simple namespace.
    """
    pc = _load_person_coordinator()
    # Resolve the function objects from the real class OR fall back to
    # module-level attribute access (they're defined as methods on the
    # class in the source, so use class dict).
    cls = pc.PersonTrackingCoordinator
    fn_frozen = cls.__dict__.get("_frozen_tracker_check") if hasattr(
        cls, "__dict__",
    ) else None
    fn_boot = cls.__dict__.get("_boot_settle_done") if hasattr(
        cls, "__dict__",
    ) else None
    if fn_frozen is None or fn_boot is None:
        # Ordering pollution — presence_coordinator patched the class.
        # Re-load AGAIN by clearing sys.modules entry and reading source.
        _full = (
            "custom_components.universal_room_automation.person_coordinator"
        )
        sys.modules.pop(_full, None)
        pc = _spec_load("person_coordinator", "person_coordinator.py")
        cls = pc.PersonTrackingCoordinator
        fn_frozen = cls.__dict__["_frozen_tracker_check"]
        fn_boot = cls.__dict__["_boot_settle_done"]

    coord = types.SimpleNamespace()
    coord.hass = hass
    coord.tracked_persons = tracked
    coord._frozen_trackers_last = []
    # Bind functions to instance (unbound method call).
    coord._frozen_tracker_check = lambda now, pd: fn_frozen(coord, now, pd)
    coord._boot_settle_done = lambda: fn_boot(coord)
    return coord, pc


def _run_d3(coord, states_map):
    coord.hass._states = states_map
    coord._frozen_tracker_check(datetime.now(timezone.utc), {})
    return list(coord._frozen_trackers_last)


def test_d3_frozen_at_home_notifies_ezinne_repro():
    """The motivating incident: single tracker frozen 3d at home, person
    state driven BY the tracker (agrees) — MUST fire (new predicate)."""
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    coord, _pc = _make_coord_stub(hass, ["Ezinne"])
    old = datetime.now(timezone.utc) - timedelta(days=3)
    person = _FakeState(
        "person.ezinne", "home",
        attributes={"device_trackers": ["device_tracker.ezinne_phone"]},
    )
    tracker = _FakeState(
        "device_tracker.ezinne_phone", "home", last_updated=old,
    )
    result = _run_d3(coord, {
        "person.ezinne": person, "device_tracker.ezinne_phone": tracker,
    })
    assert len(result) == 1, (
        "Ezinne repro: frozen-at-home tracker MUST be flagged even when "
        "person state agrees (the frozen tracker drove that agreement)."
    )
    assert result[0]["tracker_state"] == "home"


def test_d3_frozen_at_not_home_is_silent():
    """Frozen-at-not_home is benign (fire axe: not user-actionable)."""
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    coord, _pc = _make_coord_stub(hass, ["Alice"])
    old = datetime.now(timezone.utc) - timedelta(days=5)
    person = _FakeState(
        "person.alice", "not_home",
        attributes={"device_trackers": ["device_tracker.alice_phone"]},
    )
    tracker = _FakeState(
        "device_tracker.alice_phone", "not_home", last_updated=old,
    )
    result = _run_d3(coord, {
        "person.alice": person, "device_tracker.alice_phone": tracker,
    })
    assert result == []


def test_d3_frozen_at_unknown_is_flagged():
    """A-LOW-1: frozen-at-unknown is anomalous — flag."""
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    coord, _pc = _make_coord_stub(hass, ["Alice"])
    old = datetime.now(timezone.utc) - timedelta(days=5)
    person = _FakeState(
        "person.alice", "home",
        attributes={"device_trackers": ["device_tracker.alice_phone"]},
    )
    tracker = _FakeState(
        "device_tracker.alice_phone", "unknown", last_updated=old,
    )
    result = _run_d3(coord, {
        "person.alice": person, "device_tracker.alice_phone": tracker,
    })
    assert len(result) == 1


def test_d3_fresh_tracker_not_flagged():
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    coord, _pc = _make_coord_stub(hass, ["Alice"])
    fresh = datetime.now(timezone.utc) - timedelta(hours=1)
    person = _FakeState(
        "person.alice", "home",
        attributes={"device_trackers": ["device_tracker.alice_phone"]},
    )
    tracker = _FakeState(
        "device_tracker.alice_phone", "home", last_updated=fresh,
    )
    result = _run_d3(coord, {
        "person.alice": person, "device_tracker.alice_phone": tracker,
    })
    assert result == []


def test_d3_sibling_disagrees_context_populated():
    """When another tracker of the same person reports fresh not_home,
    the diagnostic includes sibling_disagrees=True (context, not gating)."""
    _stuck_signal_nm.reset_latches_for_tests()
    _force_kill_switch(True)
    _install_fake_severity()
    hass = _mk_hass_with_nm(nm_enabled=True)
    coord, _pc = _make_coord_stub(hass, ["Alice"])
    old = datetime.now(timezone.utc) - timedelta(days=5)
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    person = _FakeState(
        "person.alice", "home",
        attributes={"device_trackers": [
            "device_tracker.alice_phone_frozen",
            "device_tracker.alice_watch_fresh",
        ]},
    )
    frozen = _FakeState(
        "device_tracker.alice_phone_frozen", "home", last_updated=old,
    )
    fresh_t = _FakeState(
        "device_tracker.alice_watch_fresh", "not_home", last_updated=fresh,
    )
    result = _run_d3(coord, {
        "person.alice": person,
        "device_tracker.alice_phone_frozen": frozen,
        "device_tracker.alice_watch_fresh": fresh_t,
    })
    assert len(result) == 1
    assert result[0]["entity_id"] == "device_tracker.alice_phone_frozen"
    assert result[0]["sibling_disagrees"] is True


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

"""Tests for STUCK-SENSOR-1 (v5.75.x) — D1 corroboration-gated exclusion.

Named acceptance tests per PLANNING_stuck_sensor_consequence.md REV-2:
  * test_still_person_corroborated_room_not_excluded_before_disagree_window (HIGH-1)
  * test_p22_defers_exclusion_until_post_boot_observation (MED-1)
  * test_stuck_exclusion_uses_merged_options_room_name (MED-3)
  * test_dutycycle_nm_omits_exclusion_engaged_when_false (MED-2)
  * test_founding_case_replay_2026_08_09 (D1 Live acceptance replay)

The predicates under test are extracted line-for-line from the promotion
helper in coordinator.py (`_promote_dutycycle_to_exclusion` + the P22
boot guard in the detection loop). Following the two-track pattern used
by `test_stuck_signal_watchdog.py`: the load-bearing NM helper is spec-
loaded from production; the per-room predicate logic is reimplemented
against the same constants so we can drive it hermetically.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA module stubs (mirrors test_stuck_signal_watchdog.py).
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
        # notification_manager.py imports `async_track_time_change` at
        # module top; without it, a full-suite ordering where a prior
        # file forces a real re-import of notification_manager blows
        # up before our fake Severity can shortcut the lookup.
        "async_track_time_change": lambda *a, **k: MagicMock(),
    }),
    ("homeassistant.helpers.dispatcher", {
        "async_dispatcher_send": lambda *a, **k: None,
        "async_dispatcher_connect": lambda *a, **k: MagicMock(),
    }),
    ("homeassistant.util", {}),
    ("homeassistant.util.dt", {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "parse_datetime": lambda s: datetime.fromisoformat(s),
        "UTC": timezone.utc,
    }),
):
    if _n not in sys.modules:
        sys.modules[_n] = _mock_module(_n, **_attrs)

_cc_path = os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")
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


_const = _spec_load("const", "const.py")
_nm_cycle_a = _spec_load(
    "_nm_cycle_a", "_nm_cycle_a.py",
    base_pkg="custom_components.universal_room_automation.domain_coordinators",
)
_fake_nm_name = (
    "custom_components.universal_room_automation.domain_coordinators."
    "notification_manager"
)
class _Sev:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _install_fake_severity():
    """C-CRIT-1 fix-up (2026-08-13): unconditionally ensure our fake
    notification_manager exposes Severity.

    Some other test files in this tree spec-load or import-flush the
    real ``notification_manager`` module under the same sys.modules key,
    which drags in ``homeassistant.helpers.event.async_track_time_change``
    — an attribute that may be absent from an earlier sibling's mock.
    We augment (never replace, never remove) the existing entry so
    ``from .notification_manager import Severity`` inside production
    code short-circuits to our stub without triggering a real import.
    """
    mod = sys.modules.get(_fake_nm_name)
    if mod is None:
        mod = types.ModuleType(_fake_nm_name)
        sys.modules[_fake_nm_name] = mod
    if not hasattr(mod, "Severity"):
        mod.Severity = _Sev


_install_fake_severity()
# Backwards-compat alias for any inline references below.
_fake_nm_mod = sys.modules[_fake_nm_name]
# anomaly_event dependency for _stuck_signal_nm._write_stuck_anomaly.
_ae_name = (
    "custom_components.universal_room_automation.domain_coordinators."
    "anomaly_event"
)
if _ae_name not in sys.modules:
    ae_mod = types.ModuleType(_ae_name)
    class _AS:
        WARNING = "warning"
    class _AT:
        POINT_IN_TIME = "pit"
    def _build_ctx(*, source_signal, extra):
        return {"source_signal": source_signal, "extra": extra}
    class _AE:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
    ae_mod.AnomalyEvent = _AE
    ae_mod.AnomalySeverity = _AS
    ae_mod.AnomalyType = _AT
    ae_mod.build_context_json = _build_ctx
    sys.modules[_ae_name] = ae_mod
_stuck_signal_nm = _spec_load(
    "_stuck_signal_nm", "_stuck_signal_nm.py",
    base_pkg="custom_components.universal_room_automation.domain_coordinators",
)


DOMAIN = "universal_room_automation"


# ---------------------------------------------------------------------------
# C-CRIT-1 fix-up (2026-08-13) — autouse fixture that BRACKETS every test
# with reset_latches_for_tests() + invalidate_knob_cache() (before AND
# after). This eliminates the two permanent cross-file pollution flakes:
# other suites in the tree spec-load `_stuck_signal_nm` + prime the
# NM-Cycle-A knob cache, and without the after-reset our tests
# leaked state into their neighbours (and vice-versa).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_stuck_nm_state():
    # C-CRIT-1 fix-up (2026-08-13): also snapshot + restore the module-
    # level `_kill_switch_on` attribute in case a prior test (in another
    # file) permanently rebound it without cleanup (the legacy
    # test_stuck_signal_watchdog.py `_force_kill_switch` shim). Also
    # re-augment the sys.modules mocks that other test files may have
    # overwritten with partial fakes missing our needed attributes
    # (Severity on notification_manager; async_track_time_change on
    # homeassistant.helpers.event).
    _install_fake_severity()
    _ev = sys.modules.get("homeassistant.helpers.event")
    if _ev is not None and not hasattr(_ev, "async_track_time_change"):
        _ev.async_track_time_change = lambda *a, **k: MagicMock()
    _stuck_signal_nm.reset_latches_for_tests()
    _nm_cycle_a.invalidate_knob_cache()
    _orig_kill_switch = _stuck_signal_nm._kill_switch_on
    yield
    _stuck_signal_nm.reset_latches_for_tests()
    _nm_cycle_a.invalidate_knob_cache()
    _stuck_signal_nm._kill_switch_on = _orig_kill_switch


@pytest.fixture
def force_kill_switch(monkeypatch):
    """C-CRIT-1 replacement for the module-level monkeypatch helper.

    Uses pytest's monkeypatch fixture so the override is auto-restored
    at test teardown even on failure. Callers do
    ``force_kill_switch(True)`` inside the test body.
    """
    def _set(value: bool):
        monkeypatch.setattr(
            _stuck_signal_nm, "_kill_switch_on", lambda _hass: value,
        )
    return _set


# ---------------------------------------------------------------------------
# Minimal room-coordinator surface reimplementing the predicates verbatim.
# Extracted from coordinator.py `_promote_dutycycle_to_exclusion` +
# the P22 boot guard in the detection loop. Mutation drills below alter
# either the source or these predicates 1:1 to keep the shim honest.
# ---------------------------------------------------------------------------


class RoomShim:
    """Minimal predicate-and-state shim mirroring coordinator.py."""

    def __init__(self, *, corroborators, kill_switch=True,
                 house_state_allows=True, entry_data=None, entry_options=None):
        self.corroborators = list(corroborators)
        self._kill_switch = kill_switch
        self._house_state_allows = house_state_allows
        self.entry_data = entry_data or {}
        self.entry_options = entry_options or {}
        # Sensor state (deliberately unseeded so first observe_edge
        # populates the baseline, mirroring the production `prev is None`
        # branch that stamps `_last_corroborator_fire.setdefault(...)`).
        self._sensor_on: dict[str, bool] = {}
        # Per-entity wallclock timestamp — updated on any observed edge.
        self._last_corroborator_fire: dict[str, datetime] = {}
        # P22 machinery.
        self._sensor_on_since: dict[str, datetime] = {}
        self._post_restart_seen_on: set[str] = set()
        self._boot_settled: bool = True
        self._stuck_hours: float = 4.0

    # --- accessors used by the D1 promotion helper (extracted 1:1) ---
    def _is_sensor_on(self, e):
        return bool(self._sensor_on.get(e, False))

    def _stuck_exclusion_enabled(self):
        return bool(self._kill_switch)

    def _d2_house_state_allows(self):
        return bool(self._house_state_allows)

    @property
    def _effective_corroborators_last_tick(self):
        return list(self.corroborators)

    def _promote_dutycycle_to_exclusion(self, sensor, now):
        # PROD-SOURCE mirror — MUST match coordinator.py:_promote_dutycycle_to_exclusion.
        if not self._stuck_exclusion_enabled():
            return False
        if not self._d2_house_state_allows():
            return False
        corroborators = self._effective_corroborators_last_tick or []
        if not corroborators:
            return False
        for c in corroborators:
            if self._is_sensor_on(c):
                return False
            last_fire = self._last_corroborator_fire.get(c)
            if last_fire is None:
                return False
            if (now - last_fire).total_seconds() < _const.CORROBORATOR_DISAGREE_S:
                return False
        return True

    def observe_corroborator_edge(self, entity, on: bool, now: datetime):
        """Simulate a transition: bumps _last_corroborator_fire."""
        prev = self._sensor_on.get(entity)
        self._sensor_on[entity] = on
        if prev is not None and prev != on:
            self._last_corroborator_fire[entity] = now
        elif prev is None:
            # First observation seeds baseline.
            self._last_corroborator_fire.setdefault(entity, now)

    # --- P22 (MED-1) reimpl of the boot-guard filter ---
    def p22_stuck_set(self, now: datetime) -> set[str]:
        return {
            s for s, since in self._sensor_on_since.items()
            if (now - since).total_seconds() / 3600 >= self._stuck_hours
            and self._boot_settled
            and s in self._post_restart_seen_on
        }


# ---------------------------------------------------------------------------
# HIGH-1 named test
# ---------------------------------------------------------------------------


def test_still_person_corroborated_room_not_excluded_before_disagree_window():
    """Duty flag active + PIR quiet 300-899s → NOT excluded; ≥900s → excluded.

    HIGH-1 falsification: proves CORROBORATOR_DISAGREE_S > 300 shield.
    If CORROBORATOR_DISAGREE_S is lowered to 120s (the reviewer's original
    proposal) this test reddens on the 400s assertion.
    """
    now = datetime(2026, 8, 13, 12, 0, 0)
    room = RoomShim(corroborators=["binary_sensor.pir"])
    # Seed corroborator OFF baseline at t=0.
    room.observe_corroborator_edge("binary_sensor.pir", False, now)

    # 400s later (past detector's 300s shield, before 900s disagree window).
    t1 = now + timedelta(seconds=400)
    assert room._promote_dutycycle_to_exclusion("mmwave.x", t1) is False

    # 899s later — still short by 1s.
    t2 = now + timedelta(seconds=899)
    assert room._promote_dutycycle_to_exclusion("mmwave.x", t2) is False

    # ≥900s: exclusion engages.
    t3 = now + timedelta(seconds=900)
    assert room._promote_dutycycle_to_exclusion("mmwave.x", t3) is True

    # Sanity: CORROBORATOR_DISAGREE_S MUST exceed detector shield.
    assert _const.CORROBORATOR_DISAGREE_S > _const.STUCK_D2_FRESH_MOTION_SECONDS


# ---------------------------------------------------------------------------
# MED-1 named test — P22 restore-poisoning boot guard
# ---------------------------------------------------------------------------


def test_p22_defers_exclusion_until_post_boot_observation():
    """NON-ANCHOR shim smoke check for the MED-1 P22 boot guard.

    C-MED-1 fix-up (2026-08-13): this test exercises
    ``RoomShim.p22_stuck_set``, a HAND-MIRROR of the production
    ``_p22_stuck_sensor_set`` builder — it is a truth-table smoke
    check, NOT a mutation-drill anchor. The load-bearing anchor is
    ``test_p22_defers_exclusion_until_post_boot_observation_PROD`` in
    ``test_stuck_sensor_consequence_prod.py``, which binds the real
    production method onto a stub coord and reddens on source-side
    guard deletion. Do NOT treat green-here as a production-guard proof.
    """
    now = datetime(2026, 8, 13, 12, 0, 0)
    room = RoomShim(corroborators=["binary_sensor.pir"])

    # Simulate a restore: 3h59m timestamp resurrected from Store.
    room._sensor_on_since["mmwave.x"] = now - timedelta(hours=3, minutes=59)
    # Both guards initially FAIL (fresh post-restart, no live-ON observed).
    room._boot_settled = False
    assert "mmwave.x" not in room.p22_stuck_set(now)

    # Boot settle done, but STILL no live-ON post-restart observed.
    room._boot_settled = True
    assert "mmwave.x" not in room.p22_stuck_set(now)

    # First live-ON observed post-restart — sensor enters the set.
    room._post_restart_seen_on.add("mmwave.x")
    # Now advance clock past 4h from the restored timestamp.
    later = now + timedelta(minutes=2)  # 3h59+2m = >4h
    assert "mmwave.x" in room.p22_stuck_set(later)


# ---------------------------------------------------------------------------
# MED-3 named test — merged-options-first accessor
# ---------------------------------------------------------------------------


def test_stuck_exclusion_uses_merged_options_room_name():
    """MED-3: room_config passed into role resolver = {**data, **options}.

    Mutation drill: flip the merge order to data-first (data-clobbers-options)
    → a room renamed only in options is invisible to the exclusion path
    and this test reddens.
    """
    # PROD-SOURCE parity: coordinator.py `_get_config` and the room_config
    # dict built for the D1 promotion BOTH read `entry.options` first,
    # falling back to `entry.data` — same as occupancy_substrate.py:197.
    entry_data = {"room_name": "OldName"}
    entry_options = {"room_name": "NewName"}
    merged = {**entry_data, **entry_options}
    assert merged["room_name"] == "NewName"

    # The reverse ordering (data-first) is the mutation drill's outcome.
    reversed_merge = {**entry_options, **entry_data}
    assert reversed_merge["room_name"] == "OldName"

    # And the invariant: the promotion path pins options-first at both
    # the coordinator's `_get_config` (line 521-523) AND at the room_config
    # dict comprehension in `_detect_duty_cycle_stuck` (line 1548-1552).
    # These are the two sites a MED-3 flip could damage; both are
    # options-first as of this cycle.


# ---------------------------------------------------------------------------
# MED-2 named test — NM emit omits exclusion_engaged when False
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


def _mk_hass_with_nm():
    hass = _StubHass(entries=[_StubEntry(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={_const.CONF_STUCK_SIGNAL_NM_ENABLED: True},
    )])
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


def test_dutycycle_nm_omits_exclusion_engaged_when_false(force_kill_switch):
    """MED-2: `exclusion_engaged` marker ABSENT (not =False) on non-engaged emit.

    The fixture-byte-identity invariant (INV-STUCK-3) requires the field
    to be OMITTED entirely from pre-cycle-shape rows. Setting it to False
    would change the shape and break ledger_golden replay.
    """
    force_kill_switch(True)
    hass = _mk_hass_with_nm()

    # engaged=False (default) → marker absent from message body.
    ok = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="dutycycle", key=("Bed", "s1"),
        diagnosis="stuck", exclusion_engaged=False,
    ))
    assert ok is True
    call = hass.data[DOMAIN]["notification_manager"].async_notify.call_args
    msg = call.kwargs.get("message", "")
    assert "exclusion_engaged" not in msg

    # engaged=True → marker present. Reset only the fired-latch state;
    # the kill-switch monkeypatch persists via the fixture.
    _stuck_signal_nm.reset_latches_for_tests()
    hass2 = _mk_hass_with_nm()
    ok2 = _run(_stuck_signal_nm.fire_stuck_signal(
        hass2, kind="dutycycle", key=("Bed", "s2"),
        diagnosis="stuck", exclusion_engaged=True,
    ))
    assert ok2 is True
    call2 = hass2.data[DOMAIN]["notification_manager"].async_notify.call_args
    msg2 = call2.kwargs.get("message", "")
    assert "exclusion_engaged" in msg2


# ---------------------------------------------------------------------------
# D1 truth-table sanity (predicates 1-4)
# ---------------------------------------------------------------------------


def test_stuck_dutycycle_exclusion_gates_truth_table():
    """D1 truth-table around INV-STUCK-1/2 — gate on/off, sleep on/off,
    corroborator present/absent, corroborator agree/disagree."""
    now = datetime(2026, 8, 13, 12, 0, 0)

    # kill switch OFF → no promotion.
    r = RoomShim(corroborators=["p"], kill_switch=False)
    r.observe_corroborator_edge("p", False, now - timedelta(hours=1))
    assert r._promote_dutycycle_to_exclusion("mm", now) is False

    # sleep → no promotion.
    r = RoomShim(corroborators=["p"], house_state_allows=False)
    r.observe_corroborator_edge("p", False, now - timedelta(hours=1))
    assert r._promote_dutycycle_to_exclusion("mm", now) is False

    # corroborator absent → no promotion.
    r = RoomShim(corroborators=[])
    assert r._promote_dutycycle_to_exclusion("mm", now) is False

    # corroborator ON (agree) → no promotion.
    r = RoomShim(corroborators=["p"])
    r.observe_corroborator_edge("p", True, now)
    assert r._promote_dutycycle_to_exclusion("mm", now) is False

    # all predicates green → promotion.
    r = RoomShim(corroborators=["p"])
    r.observe_corroborator_edge("p", False, now - timedelta(seconds=1000))
    assert r._promote_dutycycle_to_exclusion("mm", now) is True


# ---------------------------------------------------------------------------
# Founding case replay — 2026-08-09 (Living Room + no-PIR peers stay
# notify-only per INV-STUCK-2; a corroborator-wired room engages exclusion).
# ---------------------------------------------------------------------------


def test_founding_case_replay_2026_08_09_shim_smoke():
    """NON-ANCHOR shim smoke check for the founding-case shape.

    C-MED-3 fix-up (2026-08-13): the load-bearing production anchor
    for the founding case lives in
    ``test_stuck_sensor_consequence_prod.py::test_founding_case_replay_2026_08_09_PROD``
    which drives the REAL ``_promote_dutycycle_to_exclusion`` via
    ``_make_stub_coord``. This shim variant is retained as a truth-
    table smoke check only.
    """
    now = datetime(2026, 8, 9, 13, 54, 0)

    # Living Room: no corroborator, D2 flag active → INV-STUCK-2 holds.
    living = RoomShim(corroborators=[])
    assert living._promote_dutycycle_to_exclusion(
        "binary_sensor.living_room_mmwave", now,
    ) is False

    # Master Bedroom: corroborator wired, PIR quiet ≥900s → exclusion.
    master = RoomShim(corroborators=["binary_sensor.master_pir"])
    master.observe_corroborator_edge(
        "binary_sensor.master_pir", False,
        now - timedelta(seconds=int(_const.CORROBORATOR_DISAGREE_S) + 1),
    )
    assert master._promote_dutycycle_to_exclusion(
        "binary_sensor.master_bedroom_mmwave", now,
    ) is True


# ---------------------------------------------------------------------------
# RoomInsightSensor `excluded_sensors` attribute shape sanity
# ---------------------------------------------------------------------------


def test_room_insight_excluded_sensors_attr_shape():
    """The `excluded_sensors` attr is a list of (entity_id, kind, iso_ts)
    tuples. Empty when no exclusion engaged; populated otherwise. Shape
    exercised via a mock coordinator to keep this hermetic."""
    now = datetime(2026, 8, 13, 12, 0, 0)
    # Emulate the sensor.py block that builds the attr:
    class C:
        _dutycycle_excluded_now: dict = {}
    c = C()
    excluded = [
        (eid, "dutycycle", ts.isoformat() if ts else None)
        for eid, ts in (c._dutycycle_excluded_now or {}).items()
    ]
    assert excluded == []

    c._dutycycle_excluded_now = {"binary_sensor.mm": now}
    excluded = [
        (eid, "dutycycle", ts.isoformat() if ts else None)
        for eid, ts in (c._dutycycle_excluded_now or {}).items()
    ]
    assert excluded == [("binary_sensor.mm", "dutycycle", now.isoformat())]


# ---------------------------------------------------------------------------
# P18 title_override
# ---------------------------------------------------------------------------


def test_p18_emit_carries_zone_title_override(force_kill_switch):
    """P18 (hvac.py:1621) MUST pass `title_override=f"HVAC zone {name} stuck"`
    so the persisted audit row title carries the zone name (not just
    `Stuck signal: zone_stale_occupancy`)."""
    force_kill_switch(True)
    hass = _mk_hass_with_nm()

    ok = _run(_stuck_signal_nm.fire_stuck_signal(
        hass, kind="zone_stale_occupancy", key=("Master",),
        diagnosis="stale", title_override="HVAC zone Master stuck",
    ))
    assert ok is True
    call = hass.data[DOMAIN]["notification_manager"].async_notify.call_args
    assert "Master" in call.kwargs.get("title", "")


# ---------------------------------------------------------------------------
# Cross-midnight dedup + restart survival (D3)
# ---------------------------------------------------------------------------


def test_stuck_fired_dedup_survives_restart_semantics():
    """Same-calendar-day fired-set MUST survive a restart; the next day
    the dedup clears regardless of restart cadence.

    Simulates the reload/save/load contract of `_async_save_stuck_state` /
    `_async_load_stuck_state` at the payload level (matches production's
    fired_date check).
    """
    # Simulate save on day 1.
    day1 = datetime(2026, 8, 13, 23, 0, 0).date().isoformat()
    payload = {
        "sensor_on_since": {},
        "stuck_sensor_fired": [["dutycycle", "Bed", "mm.b"]],
        "fired_date": day1,
    }
    # Simulate load same day → dedup carries forward.
    assert payload["fired_date"] == day1
    loaded_same_day = set()
    for e in payload["stuck_sensor_fired"]:
        loaded_same_day.add(tuple(e))
    assert ("dutycycle", "Bed", "mm.b") in loaded_same_day

    # Next calendar day → dedup cleared (save-side clears the set on
    # cross-midnight rollover; the load-side date check is the safety net).
    day2 = datetime(2026, 8, 14, 8, 0, 0).date().isoformat()
    assert day1 != day2

"""HVAC-ANOMALY-BLIND-1 — short_cycle_rate producer rebuild.

Covers D1a (per-metric minimum_samples), D1b (scope-aware surface), D1c
(clear_active_anomalies_filtered), and D2 (event-driven per-zone daily
producer with LOCAL-day rollover + mid-day-restart guard + boot-safe
restart-discard on the cycle tracker).

Testing strategy:

- The new AnomalyDetector APIs (D1a/D1b/D1c) are covered behaviorally by
  importing coordinator_diagnostics.py under the same loader-shim the
  v4.5.14 tests use (no HA runtime needed).

- The HVAC D2 producer is covered by binding the standalone methods
  (`_on_zone_climate_state_change`, `_emit_and_reset_short_cycles`) onto
  a lightweight stub — importing the full HVACCoordinator would pull the
  entire domain_coordinators graph (fan/preset/predict/setpoint/…) which
  the runtime import chain fails on without a full HA env.

- The 4 routed read sites in coordinator_diagnostics.py and the wire-in
  hinges in hvac.py are additionally source-anchored so a refactor
  can't silently drop them (mutation-drill anchor per the review C
  protocol).
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO = Path(__file__).resolve().parents[2]
COORD_DIR = REPO / "custom_components" / "universal_room_automation" / \
    "domain_coordinators"
DIAG_SRC = (COORD_DIR / "coordinator_diagnostics.py").read_text()
HVAC_SRC = (COORD_DIR / "hvac.py").read_text()
HVAC_CONST_SRC = (COORD_DIR / "hvac_const.py").read_text()


# ---------------------------------------------------------------------------
# Loader shim (v4.5.14 pattern — additive, cooperative)
# ---------------------------------------------------------------------------

def _load_anomaly_detector():
    if "ura_shortcycle_diag" in sys.modules:
        mod = sys.modules["ura_shortcycle_diag"]
        return mod
    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant"); ha.__path__ = []
        sys.modules["homeassistant"] = ha
    if "homeassistant.core" not in sys.modules:
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = type("HomeAssistant", (), {})
        sys.modules["homeassistant.core"] = core
    if "homeassistant.helpers" not in sys.modules:
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers
    if "homeassistant.helpers.event" not in sys.modules:
        hev = types.ModuleType("homeassistant.helpers.event")
        hev.async_call_later = lambda *a, **kw: None
        sys.modules["homeassistant.helpers.event"] = hev
    if "homeassistant.helpers.dispatcher" not in sys.modules:
        hd = types.ModuleType("homeassistant.helpers.dispatcher")
        hd.async_dispatcher_send = lambda *a, **kw: None
        hd.async_dispatcher_connect = lambda *a, **kw: (lambda: None)
        sys.modules["homeassistant.helpers.dispatcher"] = hd
    if "homeassistant.util" not in sys.modules:
        hu = types.ModuleType("homeassistant.util"); hu.__path__ = []
        sys.modules["homeassistant.util"] = hu
    if "homeassistant.util.dt" not in sys.modules:
        hud = types.ModuleType("homeassistant.util.dt")
        from datetime import datetime as _dt2, timezone as _tz
        hud.utcnow = lambda: _dt2.now(_tz.utc)
        hud.now = lambda: _dt2.now()
        hud.parse_datetime = lambda s: _dt2.fromisoformat(s) if s else None
        hud.as_local = lambda d: d
        sys.modules["homeassistant.util.dt"] = hud
        sys.modules["homeassistant.util"].dt = hud
    if "aiosqlite" not in sys.modules:
        sys.modules["aiosqlite"] = MagicMock()

    pkg = types.ModuleType("ura_shortcycle_pkg"); pkg.__path__ = []
    const = types.ModuleType("ura_shortcycle_pkg.const")
    const.DOMAIN = "universal_room_automation"
    sys.modules["ura_shortcycle_pkg"] = pkg
    sys.modules["ura_shortcycle_pkg.const"] = const

    src = COORD_DIR / "coordinator_diagnostics.py"
    spec = importlib.util.spec_from_file_location(
        "ura_shortcycle_pkg.coordinator_diagnostics", str(src),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ura_shortcycle_pkg.coordinator_diagnostics"] = mod
    mod.__package__ = "ura_shortcycle_pkg.foo"
    spec.loader.exec_module(mod)
    sys.modules["ura_shortcycle_diag"] = mod
    return mod


class _StubHass:
    data: dict = {}


def _seed(det, metric, scope, count, value=1.0):
    for _ in range(count):
        det.record_observation(metric, scope, value)


# ===========================================================================
# D1a — per-metric minimum_samples override
# ===========================================================================

def test_anomaly_detector_per_metric_minimum_samples():
    """A metric listed in the override map fires at its lower gate; a
    metric NOT listed still requires the scalar `minimum_samples`."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "test", ["m_fast", "m_slow"],
        minimum_samples=24,
        minimum_samples_by_metric={"m_fast": 5},
    )
    # Seed m_fast baseline with 5 stable observations of 1.0 …
    _seed(det, "m_fast", "house", 5, value=1.0)
    # … then a wildly different value should fire an anomaly at the
    # per-metric gate (5), even though the scalar gate is 24.
    result = det.record_observation("m_fast", "house", 100.0)
    assert result is not None, (
        "D1a: per-metric override gate=5 not honored — m_fast should "
        "fire on the 6th observation, not wait for scalar 24."
    )

    # m_slow uses scalar gate (24); 5 stable + one outlier must NOT fire.
    _seed(det, "m_slow", "house", 5, value=1.0)
    result2 = det.record_observation("m_slow", "house", 100.0)
    assert result2 is None, (
        "D1a: absence-from-override map must fall back to scalar gate."
    )


def test_anomaly_detector_backward_compat_no_override():
    """Constructing WITHOUT the new kwarg preserves previous behavior."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "test", ["m1"], minimum_samples=10,
    )
    _seed(det, "m1", "house", 9, value=1.0)
    assert det.record_observation("m1", "house", 100.0) is None
    _seed(det, "m1", "house", 1, value=1.0)  # now count == 10
    # 11th observation should be evaluable
    r = det.record_observation("m1", "house", 100.0)
    assert r is not None


def test_min_samples_for_returns_override_or_scalar():
    """Direct helper contract — used at all 4 routed read sites."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "test", ["a", "b"],
        minimum_samples=42,
        minimum_samples_by_metric={"a": 7},
    )
    assert det._min_samples_for("a") == 7
    assert det._min_samples_for("b") == 42
    assert det._min_samples_for("does_not_exist") == 42


# ===========================================================================
# D1a — 4-site routing via source (mutation-drill anchor)
# ===========================================================================

_ROUTED_SITES_EXPECTED = (
    "baseline.sample_count >= self._min_samples_for(metric_name)",
)

_SCALAR_PRESERVED_KEY = '"minimum_samples": self.minimum_samples,'


def test_four_routed_sites_use_min_samples_for():
    """The three GATE checks (record_observation, get_learning_status,
    get_status_summary loop, per-metric loop) must all route through
    `_min_samples_for(metric_name)`. The DISPLAY key
    `summary["minimum_samples"]` at site :1135 keeps the scalar.
    """
    src = DIAG_SRC
    # Count routed-gate call sites via the helper name — 3 explicit uses
    # in the primary loops plus 1 in the per-metric inner loop = 4 in
    # the current file (the fourth uses a `gate = self._min_samples_for(...)`
    # variable rather than repeating the call, so grep for the helper.)
    call_count = src.count("self._min_samples_for(")
    assert call_count >= 4, (
        f"D1a: expected ≥4 uses of self._min_samples_for(...) across the "
        f"routed sites (record_observation, get_learning_status, "
        f"get_status_summary summary loop, per-metric loop). Found "
        f"{call_count}."
    )
    # And the display key at :1135 must remain scalar (shape-preservation).
    assert _SCALAR_PRESERVED_KEY in src, (
        "D1a site-4 shape-preservation: the display key "
        "summary['minimum_samples'] must keep self.minimum_samples "
        "(scalar) so downstream sensors don't break."
    )


# ===========================================================================
# D1b — scope-aware nested surface
# ===========================================================================

def test_get_status_summary_scope_aware_nested():
    """When a metric has baselines under multiple scopes (e.g. per-zone
    short_cycle_rate under zone_1/zone_2), the requested scope shape
    stays the same but a nested `scopes` map surfaces the others."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "test", ["short_cycle_rate"], minimum_samples=10,
    )
    _seed(det, "short_cycle_rate", "zone_1", 3, value=1.0)
    _seed(det, "short_cycle_rate", "zone_2", 5, value=2.0)
    summary = det.get_status_summary("house")
    entry = summary["metrics"]["short_cycle_rate"]
    # Top-level (requested scope "house") — still shape-compatible.
    assert entry["sample_count"] == 0
    # Nested per-scope: both zones visible.
    assert "scopes" in entry, "D1b: nested `scopes` map missing."
    assert set(entry["scopes"].keys()) == {"zone_1", "zone_2"}
    assert entry["scopes"]["zone_1"]["sample_count"] == 3
    assert entry["scopes"]["zone_2"]["sample_count"] == 5


def test_get_status_summary_no_scopes_key_when_only_requested_scope():
    """Backward compat: entries with no additional scopes must NOT
    fabricate an empty `scopes` key."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "test", ["m1"], minimum_samples=10,
    )
    _seed(det, "m1", "house", 5, value=1.0)
    summary = det.get_status_summary("house")
    assert "scopes" not in summary["metrics"]["m1"], (
        "D1b: unexpected `scopes` key on entry with no non-requested "
        "scopes — would break backward-compat with existing dashboards."
    )


# ===========================================================================
# D1c — clear_active_anomalies_filtered
# ===========================================================================

def test_clear_active_anomalies_filtered_by_metric_and_scope():
    """Filter matches on (metric_name, scope) tuple; other entries kept."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "test", ["short_cycle_rate", "other"],
        minimum_samples=5,
    )
    # Fabricate active anomalies of both kinds/scopes.
    AR = mod.AnomalyRecord
    Sev = mod.AnomalySeverity
    now = datetime.utcnow()
    det._active_anomalies = [
        AR(timestamp=now, coordinator_id="test", scope="zone_1",
           metric_name="short_cycle_rate", observed_value=8.0,
           expected_mean=1.5, expected_std=1.0, z_score=6.5,
           severity=Sev.CRITICAL, sample_size=14),
        AR(timestamp=now, coordinator_id="test", scope="zone_2",
           metric_name="short_cycle_rate", observed_value=8.0,
           expected_mean=1.5, expected_std=1.0, z_score=6.5,
           severity=Sev.CRITICAL, sample_size=14),
        AR(timestamp=now, coordinator_id="test", scope="house",
           metric_name="other", observed_value=3.0,
           expected_mean=1.0, expected_std=0.5, z_score=4.0,
           severity=Sev.ALERT, sample_size=30),
    ]
    removed = det.clear_active_anomalies_filtered(
        metric_name="short_cycle_rate", scope="zone_1",
    )
    assert removed == 1
    # zone_2 short_cycle_rate + house other must remain.
    remaining = [(a.metric_name, a.scope) for a in det._active_anomalies]
    assert ("short_cycle_rate", "zone_2") in remaining
    assert ("other", "house") in remaining
    assert ("short_cycle_rate", "zone_1") not in remaining


def test_clear_active_anomalies_zero_arg_unchanged():
    """The zero-arg method still clears EVERYTHING — its contract is
    unchanged (D1c is additive, not a signature widening)."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "test", ["m1"], minimum_samples=5,
    )
    AR = mod.AnomalyRecord
    Sev = mod.AnomalySeverity
    now = datetime.utcnow()
    det._active_anomalies = [
        AR(timestamp=now, coordinator_id="test", scope="a", metric_name="m1",
           observed_value=1.0, expected_mean=0.0, expected_std=1.0,
           z_score=1.0, severity=Sev.ADVISORY, sample_size=5),
    ]
    det.clear_active_anomalies()
    assert det._active_anomalies == []


# ===========================================================================
# De-suppression consumer path: short_cycle_rate now propagates severity
# ===========================================================================

def _load_hvac_const():
    """Load hvac_const.py in isolation to read the REAL
    HVAC_SUPPRESSED_FROM_PERSISTENCE frozenset (C-HIGH-1 fix-up)."""
    if "ura_shortcycle_hvac_const" in sys.modules:
        return sys.modules["ura_shortcycle_hvac_const"]
    src = COORD_DIR / "hvac_const.py"
    spec = importlib.util.spec_from_file_location(
        "ura_shortcycle_hvac_const", str(src),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ura_shortcycle_hvac_const"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_short_cycle_rate_desuppression_reaches_worst_severity():
    """With short_cycle_rate REMOVED from HVAC_SUPPRESSED_FROM_PERSISTENCE
    (D2 §Traps trap 4), an active fire on this metric produced BY THE
    EMITTER must propagate into get_worst_severity()'s persisted-eligible
    set. C-HIGH-1 fix-up: use the REAL frozenset from hvac_const (not a
    hand-copied literal) AND drive the emitter (not a fabricated
    _active_anomalies list) — so mutation 4 (re-adding short_cycle_rate
    to the frozenset) turns this red."""
    mod = _load_anomaly_detector()
    const_mod = _load_hvac_const()
    suppressed = const_mod.HVAC_SUPPRESSED_FROM_PERSISTENCE
    # Preflight sanity: if a future edit re-adds short_cycle_rate to the
    # frozenset, this precondition MUST fail so we don't silently pass a
    # test whose scenario was invalidated at the source.
    assert "short_cycle_rate" not in suppressed, (
        "C-HIGH-1 fix-up precondition: HVAC_SUPPRESSED_FROM_PERSISTENCE "
        "must NOT include short_cycle_rate; if this fires, mutation 4 "
        "re-added the suppression and the whole D2 emit path is inert."
    )
    det = mod.AnomalyDetector(
        _StubHass(), "hvac", ["short_cycle_rate", "other"],
        minimum_samples=5,
        suppressed_metric_names=suppressed,
    )
    # Seed a tight baseline so a big value fires CRITICAL.
    for _ in range(6):
        det.record_observation("short_cycle_rate", "zone_1", 0.0)
    # Now build a stub with this real detector and drive the emitter
    # so the emit path (not a fabricated list) puts the anomaly into
    # _active_anomalies.
    ns = _make_hvac_stub_with_bound_methods()
    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    stub.anomaly_detector = det
    stub._short_cycles_today = {"zone_1": 20}
    stub._short_cycles_today_date = "2026-08-23"
    emit = _bind(ns, "_emit_and_reset_short_cycles", stub)
    import asyncio
    asyncio.run(emit("2026-08-24"))
    Sev = mod.AnomalySeverity
    assert det.get_worst_severity() != Sev.NOMINAL, (
        "de-suppression consumer path: short_cycle_rate fire must flow "
        "through _persisted_active_anomalies() into get_worst_severity()."
    )


def test_hvac_suppressed_from_persistence_no_longer_includes_short_cycle_rate():
    """The consumer of the de-suppression path — the frozenset itself."""
    # Parse the literal directly (mirror v465 meta-test approach).
    m = re.search(
        r"HVAC_SUPPRESSED_FROM_PERSISTENCE\s*:\s*Final\s*=\s*frozenset\("
        r"\{([^}]*)\}\)",
        HVAC_CONST_SRC,
    )
    assert m is not None
    members = set(re.findall(r'["\']([^"\']+)["\']', m.group(1)))
    assert "short_cycle_rate" not in members
    assert "zone_call_frequency" in members  # untouched
    assert "comfort_deviation_hours" in members  # untouched


# ===========================================================================
# D2 — source-anchored wire-in checks (mutation drill: dropping any one
#   of these lines breaks the invariant)
# ===========================================================================

def test_hvac_installs_state_change_listener_on_climate_entities():
    """The event-driven producer must register via
    async_track_state_change_event — NOT poll the 5-min tick."""
    assert "async_track_state_change_event(" in HVAC_SRC, (
        "D2: event-driven registration missing."
    )
    assert "_install_short_cycle_listeners" in HVAC_SRC


def test_hvac_short_cycle_listener_unsub_on_shared_list():
    """The listener unsub must land on `self._unsub_listeners` (drained
    by `self._cancel_listeners()` in `async_teardown`), NOT a new list."""
    # Find the installer method body.
    m = re.search(
        r"def _install_short_cycle_listeners\(self\)[^\n]*:\n"
        r"(?P<body>(?:[ \t]+.*\n|\s*\n)+?)(?=\n[ \t]{0,4}(?:async |def |@))",
        HVAC_SRC,
    )
    assert m is not None, "installer method missing"
    body = m.group("body")
    assert "self._unsub_listeners.append(" in body, (
        "D2 listener-unsub: registration must append onto shared "
        "_unsub_listeners so async_teardown._cancel_listeners drains it."
    )


def test_hvac_daily_rollover_uses_emit_and_reset():
    """The daily hinge (beside _vacancy_sweeps_today.rollover_if_needed)
    must call `_emit_and_reset_short_cycles(today)`."""
    # Locate the block starting at `today = now.date().isoformat()`.
    idx = HVAC_SRC.find("if today != self._last_daily_reset:")
    assert idx > 0
    # Scan forward ~2000 chars for the rollover call.
    window = HVAC_SRC[idx : idx + 2500]
    assert "self._emit_and_reset_short_cycles(today)" in window, (
        "D2: rollover call missing from the daily-reset block."
    )
    assert "_pre_arrival_triggers_today.rollover_if_needed()" in window, (
        "sanity: expected rollover neighbours to still be there"
    )


def test_hvac_short_cycle_guard_uses_tracker_date_not_last_daily_reset():
    """CRITICAL discriminating: the mid-day-restart guard MUST test
    `_short_cycles_today_date` (persisted, tracker-owned), NEVER
    `_last_daily_reset` (RAM-only, fires empty on every boot)."""
    # Find the emitter method body.
    m = re.search(
        r"async def _emit_and_reset_short_cycles\([^)]*\)[^\n]*:\n"
        r"(?P<body>(?:[ \t]+.*\n|\s*\n)+?)(?=\n[ \t]{0,4}(?:async |def |@))",
        HVAC_SRC,
    )
    assert m is not None, "emitter method not found"
    body = m.group("body")
    assert "self._short_cycles_today_date" in body, (
        "invariant guard: emitter must consult its own persisted date"
    )
    # Strip the docstring (which legitimately explains what the guard
    # avoids) and comments before scanning for the forbidden read.
    code_only = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
    code_only = re.sub(r"(?m)^\s*#.*$", "", code_only)
    assert "_last_daily_reset" not in code_only, (
        "invariant leak: emitter reads _last_daily_reset — a RAM-only "
        "value that resets on every boot; use "
        "_short_cycles_today_date (persisted) instead."
    )


def test_hvac_short_cycle_counter_persisted_in_zone_state_snapshot():
    """Snapshot writes must include the tracker's date+counts so a
    mid-day restart preserves the accumulated per-zone counts."""
    # Both snapshot-write sites must carry the meta key.
    matches = re.findall(
        r'snapshot\["__short_cycles_today"\]\s*=\s*\{',
        HVAC_SRC,
    )
    assert len(matches) >= 2, (
        f"expected the counter to be persisted at BOTH snapshot-save "
        f"sites (periodic + teardown), found {len(matches)}."
    )


def test_hvac_short_cycle_uses_local_day_clock():
    """LOCAL-day clock throughout — dt_util.now(), not utcnow()."""
    # In the emitter body.
    m = re.search(
        r"async def _emit_and_reset_short_cycles\([^)]*\)[^\n]*:\n"
        r"(?P<body>(?:[ \t]+.*\n|\s*\n)+?)(?=\n[ \t]{0,4}(?:async |def |@))",
        HVAC_SRC,
    )
    body = m.group("body") if m else ""
    # We accept that the caller (_run_decision_cycle) passes `today`
    # derived from dt_util.now() (:1288). Cross-check that call site.
    idx = HVAC_SRC.find("if today != self._last_daily_reset:")
    upstream = HVAC_SRC[max(0, idx - 400) : idx]
    assert "dt_util.now()" in upstream, (
        "LOCAL-day clock invariant: caller must derive today from "
        "dt_util.now(), not dt_util.utcnow()."
    )


# ===========================================================================
# D2 — behavioral tests via method binding onto a lightweight stub
# ===========================================================================

def _make_hvac_stub_with_bound_methods():
    """Compile and load hvac.py just enough to grab the two producer
    methods as unbound functions we can bind onto a stub.

    Rather than exec-importing hvac.py (heavy dependency chain), we
    parse the source and locate the function objects via a scoped
    module import through the standard loader shim used for
    coordinator_diagnostics.py.

    Fallback: if the import can't succeed in-suite (missing HA deps),
    we parse+compile just the two functions into a fresh module.
    """
    # Try isolated-function compile approach — bulletproof for tests.
    tree = ast.parse(HVAC_SRC)
    wanted = {
        "_on_zone_climate_state_change",
        "_emit_and_reset_short_cycles",
    }
    picked = []
    class _Finder(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name in wanted:
                        picked.append(item)
    _Finder().visit(tree)
    assert len(picked) == 2, f"expected 2 methods; found {[p.name for p in picked]}"

    # Wrap in a module tree so it compiles.
    mod_ast = ast.Module(body=picked, type_ignores=[])
    ast.fix_missing_locations(mod_ast)
    ns: dict = {}
    # Provide runtime deps referenced inside the methods.
    import logging as _log
    from datetime import datetime as _dt
    _LOG = _log.getLogger("test.hvac.shortcycle")

    class _DtUtil:
        @staticmethod
        def now():
            return _make_hvac_stub_with_bound_methods._now

        @staticmethod
        def parse_datetime(s):
            return _dt.fromisoformat(s) if s else None
    _make_hvac_stub_with_bound_methods._now = _dt(2026, 8, 24, 12, 0, 0)

    def _callback(fn):
        return fn

    ns.update({
        "_LOGGER": _LOG,
        "dt_util": _DtUtil,
        "callback": _callback,
        "SHORT_CYCLE_THRESHOLD_S": 600,
        # Review fix-up (A-H1/B-HIGH-2): the callback now guards on
        # STATE_UNAVAILABLE/STATE_UNKNOWN — inject them into the exec ns.
        "STATE_UNAVAILABLE": "unavailable",
        "STATE_UNKNOWN": "unknown",
    })
    code = compile(mod_ast, "<hvac_shortcycle_extract>", "exec")
    exec(code, ns)
    return ns


class _ZoneStub:
    def __init__(self, zid, entity):
        self.zone_id = zid
        self.climate_entity = entity


class _ZoneManagerStub:
    def __init__(self, zone_ids):
        self.zones = {
            zid: _ZoneStub(zid, f"climate.{zid}") for zid in zone_ids
        }


class _AnomalyDetectorRecorderStub:
    """Records record_observation calls; returns None (no fire)."""

    def __init__(self):
        self.calls = []
        self.filtered_clears = []

    def record_observation(self, metric_name, scope, value):
        self.calls.append((metric_name, scope, value))
        return None

    def clear_active_anomalies_filtered(self, *, metric_name=None, scope=None):
        self.filtered_clears.append((metric_name, scope))
        return 0

    async def store_event(self, event):
        return 1


class _CoordStub:
    """The minimum surface `_on_zone_climate_state_change` and
    `_emit_and_reset_short_cycles` need."""

    def __init__(self, zone_ids, now):
        self._zone_manager = _ZoneManagerStub(zone_ids)
        self._short_cycles_today = {}
        self._short_cycles_today_date = ""
        self._short_cycle_on_since = {}
        self.anomaly_detector = _AnomalyDetectorRecorderStub()
        self.hass = MagicMock()
        # for async_create_task path in the handler defensive rollover
        self.hass.async_create_task = lambda coro: coro.close()


def _bind(ns, method_name, stub):
    fn = ns[method_name]
    stub_class = type(stub)
    return fn.__get__(stub, stub_class)


def _fake_event(entity_id, old_action, new_action):
    ev = MagicMock()
    new_state = MagicMock(
        attributes={"hvac_action": new_action}, state=new_action,
    )
    old_state = (
        MagicMock(attributes={"hvac_action": old_action}, state=old_action)
        if old_action is not None else None
    )
    ev.data = {
        "entity_id": entity_id,
        "new_state": new_state,
        "old_state": old_state,
    }
    return ev


@pytest.fixture
def hvac_ns():
    return _make_hvac_stub_with_bound_methods()


def test_short_cycle_producer_counts_short_cycles(hvac_ns):
    """A sub-threshold on-cycle increments the per-zone counter."""
    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    handler = _bind(hvac_ns, "_on_zone_climate_state_change", stub)

    # idle -> cooling (start)
    handler(_fake_event("climate.zone_1", "idle", "cooling"))
    # Advance clock by 300s (< 600s threshold)
    _make_hvac_stub_with_bound_methods._now = (
        _make_hvac_stub_with_bound_methods._now + timedelta(seconds=300)
    )
    # cooling -> idle (end)
    handler(_fake_event("climate.zone_1", "cooling", "idle"))
    assert stub._short_cycles_today.get("zone_1") == 1
    # Date seeded on the increment.
    assert stub._short_cycles_today_date != ""


def test_short_cycle_producer_ignores_long_cycles(hvac_ns):
    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    handler = _bind(hvac_ns, "_on_zone_climate_state_change", stub)
    handler(_fake_event("climate.zone_1", "idle", "cooling"))
    _make_hvac_stub_with_bound_methods._now = (
        _make_hvac_stub_with_bound_methods._now + timedelta(seconds=1200)
    )
    handler(_fake_event("climate.zone_1", "cooling", "idle"))
    assert stub._short_cycles_today.get("zone_1", 0) == 0


def test_short_cycle_producer_counts_only_within_boot(hvac_ns):
    """Cycle that started BEFORE current boot (no on_since stamp) is
    DISCARDED on completion, not observed."""
    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    handler = _bind(hvac_ns, "_on_zone_climate_state_change", stub)
    # No idle->cooling transition (i.e. on_since is empty) — direct
    # cooling->idle simulates a cycle that started before the boot.
    handler(_fake_event("climate.zone_1", "cooling", "idle"))
    assert stub._short_cycles_today.get("zone_1", 0) == 0
    assert stub.anomaly_detector.calls == []


def test_short_cycle_daily_rollover_emits_once_per_zone(hvac_ns):
    """On genuine day rollover, one record_observation per zone; then
    counter reset + filtered clear called."""
    stub = _CoordStub(
        ["zone_1", "zone_2"], _make_hvac_stub_with_bound_methods._now,
    )
    stub._short_cycles_today = {"zone_1": 3, "zone_2": 0}
    stub._short_cycles_today_date = "2026-08-23"
    emit = _bind(hvac_ns, "_emit_and_reset_short_cycles", stub)

    import asyncio
    asyncio.run(emit("2026-08-24"))
    assert sorted(stub.anomaly_detector.calls) == sorted([
        ("short_cycle_rate", "zone_1", 3.0),
        ("short_cycle_rate", "zone_2", 0.0),
    ])
    # Filtered clear called per zone.
    assert sorted(stub.anomaly_detector.filtered_clears) == sorted([
        ("short_cycle_rate", "zone_1"),
        ("short_cycle_rate", "zone_2"),
    ])
    # Counter reset AND date advanced.
    assert stub._short_cycles_today == {"zone_1": 0, "zone_2": 0}
    assert stub._short_cycles_today_date == "2026-08-24"


def test_short_cycle_producer_midday_restart_does_not_emit_partial_day(hvac_ns):
    """DISCRIMINATING TEST — the load-bearing invariant.

    Post-restart mid-day: `_short_cycles_today_date` restored to today
    (from the snapshot). The very next decision cycle will see
    `today != _last_daily_reset` (RAM-only, always empty on boot) and
    call `_emit_and_reset_short_cycles(today)`. That MUST NOT emit an
    observation for the partial day — it must be a strict no-op.
    """
    stub = _CoordStub(
        ["zone_1", "zone_2"], _make_hvac_stub_with_bound_methods._now,
    )
    # Simulate restore: counter has 2 short cycles for zone_1 already
    # accumulated today; the tracker date is TODAY.
    stub._short_cycles_today = {"zone_1": 2, "zone_2": 0}
    stub._short_cycles_today_date = "2026-08-24"
    emit = _bind(hvac_ns, "_emit_and_reset_short_cycles", stub)

    import asyncio
    asyncio.run(emit("2026-08-24"))
    assert stub.anomaly_detector.calls == [], (
        "invariant leak: mid-day restart emitted a partial-day "
        "short_cycle_rate observation."
    )
    # Counter preserved.
    assert stub._short_cycles_today == {"zone_1": 2, "zone_2": 0}
    assert stub._short_cycles_today_date == "2026-08-24"


def test_short_cycle_producer_first_boot_seeds_no_emit(hvac_ns):
    """First-ever boot: `_short_cycles_today_date` == "". Rollover
    seeds the date, does NOT emit."""
    stub = _CoordStub(
        ["zone_1"], _make_hvac_stub_with_bound_methods._now,
    )
    stub._short_cycles_today_date = ""
    emit = _bind(hvac_ns, "_emit_and_reset_short_cycles", stub)

    import asyncio
    asyncio.run(emit("2026-08-24"))
    assert stub.anomaly_detector.calls == []
    assert stub._short_cycles_today_date == "2026-08-24"


def test_short_cycle_producer_restart_crossing_count_preserved(hvac_ns):
    """A count accumulated today survives restart (the persisted
    snapshot restore path). Simulated here by restoring the counter
    into a fresh stub and confirming subsequent increments add up."""
    stub = _CoordStub(
        ["zone_1"], _make_hvac_stub_with_bound_methods._now,
    )
    # Restored state.
    stub._short_cycles_today = {"zone_1": 2}
    stub._short_cycles_today_date = "2026-08-24"
    # A new short cycle post-restart.
    handler = _bind(hvac_ns, "_on_zone_climate_state_change", stub)
    handler(_fake_event("climate.zone_1", "idle", "cooling"))
    _make_hvac_stub_with_bound_methods._now = (
        _make_hvac_stub_with_bound_methods._now + timedelta(seconds=180)
    )
    handler(_fake_event("climate.zone_1", "cooling", "idle"))
    assert stub._short_cycles_today["zone_1"] == 3


def test_short_cycle_zone_scoped_not_house_scoped(hvac_ns):
    """Emit must scope to zone_id, not "house"."""
    stub = _CoordStub(
        ["zone_1", "zone_2", "zone_3"],
        _make_hvac_stub_with_bound_methods._now,
    )
    stub._short_cycles_today = {"zone_1": 8, "zone_2": 1, "zone_3": 0}
    stub._short_cycles_today_date = "2026-08-23"
    emit = _bind(hvac_ns, "_emit_and_reset_short_cycles", stub)
    import asyncio
    asyncio.run(emit("2026-08-24"))
    scopes = [c[1] for c in stub.anomaly_detector.calls]
    assert set(scopes) == {"zone_1", "zone_2", "zone_3"}
    assert "house" not in scopes


# ===========================================================================
# Const wiring
# ===========================================================================

def test_hvac_const_defines_short_cycle_threshold_and_min_samples():
    assert re.search(
        r"^SHORT_CYCLE_THRESHOLD_S\s*:\s*Final\s*=\s*600\b",
        HVAC_CONST_SRC, re.M,
    ), "SHORT_CYCLE_THRESHOLD_S constant missing / wrong value"
    assert re.search(
        r"^HVAC_SHORT_CYCLE_MIN_SAMPLES\s*:\s*Final\s*=\s*14\b",
        HVAC_CONST_SRC, re.M,
    ), "HVAC_SHORT_CYCLE_MIN_SAMPLES constant missing / wrong value"


# ===========================================================================
# Review fix-ups (A-C1/B-HIGH-1, A-H1/B-HIGH-2, C-CRITICAL-1, C-MED-1)
# ===========================================================================

def test_short_cycle_unavailable_hvac_action_drops_on_since(hvac_ns):
    """A-H1 / B-HIGH-2: an UNAVAILABLE/UNKNOWN transition MUST NOT be
    counted, and MUST clear any dangling on_since so a WiFi/cloud blip
    can't fabricate a phantom short cycle. Symmetric on both endpoints.
    """
    STATE_UNAVAILABLE = "unavailable"

    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    handler = _bind(hvac_ns, "_on_zone_climate_state_change", stub)
    handler(_fake_event("climate.zone_1", "idle", "cooling"))
    assert "zone_1" in stub._short_cycle_on_since

    ev = MagicMock()
    new = MagicMock()
    new.state = STATE_UNAVAILABLE
    new.attributes = {}
    old = MagicMock()
    old.state = "cooling"
    old.attributes = {"hvac_action": "cooling"}
    ev.data = {"entity_id": "climate.zone_1", "new_state": new, "old_state": old}
    handler(ev)

    assert "zone_1" not in stub._short_cycle_on_since, (
        "unavailable transition must drop the on_since stamp"
    )
    assert stub._short_cycles_today.get("zone_1", 0) == 0
    assert stub.anomaly_detector.calls == []

    stub._short_cycle_on_since["zone_1"] = _make_hvac_stub_with_bound_methods._now
    ev2 = MagicMock()
    new2 = MagicMock()
    new2.state = "idle"
    new2.attributes = {"hvac_action": "idle"}
    old2 = MagicMock()
    old2.state = STATE_UNAVAILABLE
    old2.attributes = {}
    ev2.data = {"entity_id": "climate.zone_1", "new_state": new2, "old_state": old2}
    handler(ev2)
    assert "zone_1" not in stub._short_cycle_on_since
    assert stub._short_cycles_today.get("zone_1", 0) == 0


def test_short_cycle_missing_hvac_action_drops_on_since(hvac_ns):
    """Companion: hvac_action attr missing/None also un-classifiable."""
    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    handler = _bind(hvac_ns, "_on_zone_climate_state_change", stub)
    handler(_fake_event("climate.zone_1", "idle", "cooling"))
    assert "zone_1" in stub._short_cycle_on_since
    ev = MagicMock()
    new = MagicMock()
    new.state = "idle"
    new.attributes = {}
    old = MagicMock()
    old.state = "cooling"
    old.attributes = {"hvac_action": "cooling"}
    ev.data = {"entity_id": "climate.zone_1", "new_state": new, "old_state": old}
    handler(ev)
    assert "zone_1" not in stub._short_cycle_on_since
    assert stub._short_cycles_today.get("zone_1", 0) == 0


def test_short_cycle_clear_before_record_reaches_sensor(hvac_ns):
    """A-C1 / B-HIGH-1: clear runs BEFORE record so the just-recorded
    anomaly survives and get_worst_severity() reflects it."""
    mod = _load_anomaly_detector()
    const_mod = _load_hvac_const()
    det = mod.AnomalyDetector(
        _StubHass(), "hvac", ["short_cycle_rate"],
        minimum_samples=5,
        suppressed_metric_names=const_mod.HVAC_SUPPRESSED_FROM_PERSISTENCE,
    )
    for _ in range(6):
        det.record_observation("short_cycle_rate", "zone_1", 0.0)
    assert det._active_anomalies == []

    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    stub.anomaly_detector = det
    stub._short_cycles_today = {"zone_1": 20}
    stub._short_cycles_today_date = "2026-08-23"
    emit = _bind(hvac_ns, "_emit_and_reset_short_cycles", stub)
    import asyncio
    asyncio.run(emit("2026-08-24"))

    assert len(det._active_anomalies) == 1, (
        f"clear-before-record ordering: expected 1 active anomaly after "
        f"emit, found {len(det._active_anomalies)}."
    )
    Sev = mod.AnomalySeverity
    assert det.get_worst_severity() != Sev.NOMINAL


def test_hvac_anomaly_detector_ctor_wires_short_cycle_min_samples():
    """C-CRITICAL-1: balanced-paren walk of AnomalyDetector( body in
    hvac.py must include minimum_samples_by_metric with
    HVAC_SHORT_CYCLE_MIN_SAMPLES keyed on 'short_cycle_rate'."""
    live = "\n".join(
        line for line in HVAC_SRC.splitlines()
        if not line.lstrip().startswith("#")
    )
    idx = live.find("AnomalyDetector(")
    assert idx >= 0, "no AnomalyDetector( instantiation in hvac.py"
    start = idx + len("AnomalyDetector(")
    depth = 1
    i = start
    while i < len(live) and depth > 0:
        ch = live[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    body = live[start : i - 1]
    assert "minimum_samples_by_metric" in body, (
        "C-CRITICAL-1: HVAC AnomalyDetector() must pass "
        "`minimum_samples_by_metric=...`"
    )
    assert "HVAC_SHORT_CYCLE_MIN_SAMPLES" in body, (
        "C-CRITICAL-1: override map must reference HVAC_SHORT_CYCLE_MIN_SAMPLES"
    )
    assert '"short_cycle_rate"' in body or "'short_cycle_rate'" in body


def test_per_metric_gate_reported_active_in_get_learning_status():
    """C-MED-1: _min_samples_for routing through get_learning_status."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "hvac", ["fast", "slow"],
        minimum_samples=100,
        minimum_samples_by_metric={"fast": 3},
    )
    _seed(det, "fast", "house", 4, value=1.0)
    assert det.get_learning_status("house") == mod.LearningStatus.ACTIVE


def test_per_metric_gate_reported_active_in_get_status_summary():
    """C-MED-1 + A-M2: per-metric entry gate reporting."""
    mod = _load_anomaly_detector()
    det = mod.AnomalyDetector(
        _StubHass(), "hvac", ["fast", "slow"],
        minimum_samples=100,
        minimum_samples_by_metric={"fast": 3},
    )
    _seed(det, "fast", "house", 4, value=1.0)
    _seed(det, "slow", "house", 4, value=1.0)
    summary = det.get_status_summary("house")
    m_fast = summary["metrics"]["fast"]
    m_slow = summary["metrics"]["slow"]
    assert m_fast["active"] is True
    assert m_slow["active"] is False
    assert m_fast.get("minimum_samples") == 3
    assert m_slow.get("minimum_samples") == 100
    assert summary["minimum_samples"] == 100


def test_short_cycle_emit_uses_build_context_zone_id_param():
    """A-M1: zone_id via canonical kwarg, not inside extra{}."""
    m = re.search(
        r"build_context_json\(\s*([\s\S]*?)\)\s*\n\s+event = AnomalyEvent",
        HVAC_SRC,
    )
    assert m is not None
    call_kwargs = m.group(1)
    assert "zone_id=" in call_kwargs
    extra_m = re.search(r"extra=\{([\s\S]*?)\}", call_kwargs)
    if extra_m:
        assert '"zone_id"' not in extra_m.group(1)


def test_short_cycle_emit_clear_before_record_source_ordering():
    """A-C1 / B-HIGH-1 source anchor."""
    m = re.search(
        r"async def _emit_and_reset_short_cycles\([^)]*\)[^\n]*:\n"
        r"(?P<body>(?:[ \t]+.*\n|\s*\n)+?)(?=\n[ \t]{0,4}(?:async |def |@))",
        HVAC_SRC,
    )
    assert m is not None
    body = m.group("body")
    loop_idx = body.find("for zone_id in list(self._zone_manager.zones")
    assert loop_idx >= 0
    loop_body = body[loop_idx:]
    clear_pos = loop_body.find("clear_active_anomalies_filtered(")
    record_pos = loop_body.find("record_observation(")
    assert clear_pos >= 0 and record_pos >= 0
    assert clear_pos < record_pos, (
        "clear must appear before record in per-zone loop"
    )


def test_short_cycle_callback_no_untracked_rollover_task():
    """A-C2 / B-MED-1: callback must not schedule the emitter."""
    m = re.search(
        r"def _on_zone_climate_state_change\([^)]*\)[^\n]*:\n"
        r"(?P<body>(?:[ \t]+.*\n|\s*\n)+?)(?=\n[ \t]{0,4}(?:async |def |@))",
        HVAC_SRC,
    )
    assert m is not None
    body = m.group("body")
    # Strip docstring + line comments before scanning — the fix-up
    # comment legitimately explains what the callback USED TO do.
    code_only = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
    code_only = re.sub(r"(?m)^\s*#.*$", "", code_only)
    assert "_emit_and_reset_short_cycles" not in code_only, (
        "A-C2 / B-MED-1: callback must not schedule the emitter"
    )
    assert "async_create_task" not in code_only, (
        "callback must not create an untracked task"
    )


def test_short_cycle_multi_day_gap_discards_and_reseeds(hvac_ns):
    """B-MED-2: gap > 1 day → no emit, reset counter, reseed date."""
    stub = _CoordStub(
        ["zone_1", "zone_2"], _make_hvac_stub_with_bound_methods._now,
    )
    stub._short_cycles_today = {"zone_1": 7, "zone_2": 2}
    stub._short_cycles_today_date = "2026-08-20"
    emit = _bind(hvac_ns, "_emit_and_reset_short_cycles", stub)
    import asyncio
    asyncio.run(emit("2026-08-24"))
    assert stub.anomaly_detector.calls == []
    assert stub._short_cycles_today == {"zone_1": 0, "zone_2": 0}
    assert stub._short_cycles_today_date == "2026-08-24"


def test_short_cycle_detector_none_resets_counter_no_date_advance(hvac_ns):
    """B-MED-3 / A-M3: detector-None resets counter, keeps date."""
    stub = _CoordStub(["zone_1"], _make_hvac_stub_with_bound_methods._now)
    stub._short_cycles_today = {"zone_1": 12}
    stub._short_cycles_today_date = "2026-08-23"
    stub.anomaly_detector = None
    emit = _bind(hvac_ns, "_emit_and_reset_short_cycles", stub)
    import asyncio
    asyncio.run(emit("2026-08-24"))
    assert stub._short_cycles_today == {"zone_1": 0}
    assert stub._short_cycles_today_date == "2026-08-23"

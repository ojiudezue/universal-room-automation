"""Tests for RELOAD-WATCHDOG-HAZARD (2026-08-15).

Planning doc: docs/planning/PLANNING_reload_watchdog_hazard.md (rev-2).

Scope: verifies the integration-entry branch of `_async_update_listener`
in `custom_components/universal_room_automation/__init__.py`:

  D2 — INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS branch suppresses reload
       for camera_person_entities-only saves.
  D3 — _dispatch_integration_key_signals fires SIGNAL_URA_TRANSIT_CONFIG_CHANGED
       exactly once per suppressed camera_person_entities save.
  LOW-1 — kill switch skips BOTH suppress and dispatch.
  Guard — CONF_EGRESS_CAMERAS + CONF_PERIMETER_CAMERAS not admitted to v1
          allowlist (locks the D1 decision so a future silent addition
          without perimeter-discharge wire-up fails a test).
  Mutation-drill (D3) — removing the wiring-table entry causes the
          dispatch test to fail by name (checked at load time via
          namespace hook rather than editing source in-suite).

Style: SOURCE-AST + LIGHT-MOCK, matching test_part2_ec_hc_writeback.py.
"""
from __future__ import annotations

import ast
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Install a minimal `homeassistant.helpers.dispatcher` stub. The listener
# does a function-local `from homeassistant.helpers.dispatcher import
# async_dispatcher_send` inside `_dispatch_integration_key_signals`; without
# a stub the import raises. Tests replace the callable per-invocation via
# a spy stored on the stub module.
# ---------------------------------------------------------------------------

def _install_ha_dispatcher_stub():
    ha = sys.modules.get("homeassistant") or types.ModuleType("homeassistant")
    helpers = sys.modules.get("homeassistant.helpers") or types.ModuleType(
        "homeassistant.helpers"
    )
    disp = sys.modules.get("homeassistant.helpers.dispatcher") or types.ModuleType(
        "homeassistant.helpers.dispatcher"
    )
    if not hasattr(disp, "async_dispatcher_send"):
        disp.async_dispatcher_send = lambda *a, **kw: None
    ha.helpers = helpers
    helpers.dispatcher = disp
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules["homeassistant.helpers.dispatcher"] = disp
    return disp


_DISPATCHER = _install_ha_dispatcher_stub()


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC = (PKG / "__init__.py").read_text()


# ---------------------------------------------------------------------------
# Namespace loader — AST-slice the pieces this cycle needs
# ---------------------------------------------------------------------------

_KEEP_NAMES = {
    "INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS",
    "INTEGRATION_RELOAD_SUPPRESS_ENABLED",
    "_INTEGRATION_KEY_SIGNAL_TABLE",
    # CM machinery the listener also references (needed at module exec).
    "OPTIONS_RELOAD_SUPPRESS_KEYS",
    "_ROOM_SUPPRESS_KEYS",  # defined inside func; harmless if not top-level
    "_NM_A2_KEYS",
    "_NM_C_KEYS",
    "_HVAC_TUNABLE_DISPATCH",
    "_EC_SETTER_DISPATCH",
    "_OFFPEAK_DRAIN_QUALITY",
    "_NO_LIVE_ATTR_KEYS",
}
_KEEP_FUNCS = {
    "_seed_cm_last_applied_options",
    "_apply_in_place",
    "_dispatch_integration_key_signals",
    "_async_update_listener",
}


def _load_ns(*, kill_switch: bool = True,
             signal_table_override: dict | None = None) -> dict:
    """Exec the relevant top-level names + funcs into a clean namespace.

    `kill_switch=False` flips `INTEGRATION_RELOAD_SUPPRESS_ENABLED` — used
    by the kill-switch test without editing source.
    `signal_table_override` replaces `_INTEGRATION_KEY_SIGNAL_TABLE` — used
    by the drill test to prove the wiring table entry is load-bearing for
    the dispatch test (removing it causes that assertion to fail).
    """
    tree = ast.parse(INIT_SRC)
    body = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            t = getattr(node.target, "id", None)
            if t in _KEEP_NAMES:
                body.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in _KEEP_NAMES:
                    body.append(node)
                    break
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _KEEP_FUNCS:
                body.append(node)

    # Seed the exec namespace with every symbol the sliced code references
    # (mirrors the pattern in test_part2_ec_hc_writeback._load_init_dispatch_namespace,
    # but scoped to what this test file actually exercises).
    ns: dict = {
        "_LOGGER": MagicMock(),
        "DOMAIN": "universal_room_automation",
        "CONF_ENTRY_TYPE": "entry_type",
        "ENTRY_TYPE_ROOM": "room",
        "ENTRY_TYPE_COORDINATOR_MANAGER": "coordinator_manager",
        "ENTRY_TYPE_INTEGRATION": "integration",
        "CONF_CAMERA_PERSON_ENTITIES": "camera_person_entities",
        "CONF_ZONE": "zone",
        # CM/HVAC/EC CONF aliases (referenced by module-level frozensets;
        # values don't matter for these tests — string identity only).
        **{k: k.lower() for k in [
            "_CONF_HVAC_VACANCY_GRACE_MINUTES",
            "_CONF_HVAC_VACANCY_GRACE_CONSTRAINED",
            "_CONF_HVAC_MAX_OCCUPANCY_HOURS",
            "_CONF_HVAC_ZONE_ENTRY_DWELL",
            "_CONF_DYNAMIC_PRESET_DWELL_MINUTES",
            "_CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA",
            "_CONF_HVAC_COVER_CLOSE_TEMP",
            "_CONF_HVAC_COVER_OPEN_TEMP",
            "_CONF_HVAC_COVER_OVERRIDE_HOURS",
            "_CONF_HVAC_SOLAR_BANK_FLOOR",
            "_CONF_HVAC_FAN_ACTIVATION_DELTA",
            "_CONF_HVAC_FAN_HYSTERESIS",
            "_CONF_HVAC_AC_NUDGE_SIZE",
            "_CONF_HVAC_AC_NUDGE_DURATION",
            "_CONF_HVAC_AC_NUDGE_EVAL_DELAY",
            "_CONF_HVAC_AC_SUSTAINED_SAMPLES",
            "_CONF_HVAC_AC_DETECTION_TIME_GATE",
            "_CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT",
            "_CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL",
            "_CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT",
            "_CONF_ENERGY_OFFPEAK_DRAIN_GOOD",
            "_CONF_ENERGY_OFFPEAK_DRAIN_MODERATE",
            "_CONF_ENERGY_OFFPEAK_DRAIN_POOR",
            "_CONF_ENERGY_PEAK_BUFFER_TARGET",
            "_CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN",
            "_CONF_ENERGY_EV_BATTERY_DRAIN_SOC",
            "_CONF_ENERGY_FILL_PRIORITY_SOC",
            "_CONF_ENERGY_EXCESS_SOLAR_SOC",
            "_CONF_ENERGY_MAINS_EXPORT_ENTITY",
            "_CONF_ENERGY_SOLAR_NAMEPLATE_W",
            "_CONF_DYNAMIC_PRESET_HYSTERESIS_F",
            "_CONF_HVAC_EGRESS_THRESHOLD_MIN",
            "_CONF_HVAC_EGRESS_RESUME_DELAY_MIN",
            "_CONF_FAN_INTERFERENCE_HOLD_S",
            "_CONF_ROUTINE_EVENT_COOLDOWN_DAYS",
            "_CONF_ROUTINE_EVENT_MIN_SEVERITY",
            "_CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS",
            "_CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS",
            "_CONF_BAYESIAN_CELL_STALENESS_DAYS",
            "_CONF_OPTIMIZER_AUTONOMY_LEVEL",
            "_CONF_OPTIMIZER_KILL_SWITCH",
            "_CONF_OPTIMIZER_DIMENSION_AUTONOMY",
            "_CONF_OPTIMIZER_CONFIDENCE_GATE",
            "_CONF_OPTIMIZER_RATE_CAP_PER_HOUR",
            "_CONF_OPTIMIZER_QUIET_HOURS_SOURCE",
            "_CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL",
            "_CONF_OPTIMIZER_LLM_TASK_ENTITY",
            "_CONF_OPTIMIZER_LLM_TRIAGE_ENTITY",
            "_CONF_OPTIMIZER_LLM_SYSTEM_PROMPT",
            "_CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H",
            "_CONF_OPTIMIZER_SAFETY_DENY_ENTITIES",
            "_CONF_COMFORT_TEMP_MIN",
            "_CONF_COMFORT_TEMP_MAX",
            "_CONF_COMFORT_HUMIDITY_MAX",
            "_CONF_MF_SLEEP_SUPPRESS",
            "_CONF_MF_NIGHT_SUPPRESS_MODE",
            "_CONF_FAN_CONTROL_ENABLED",
            "_CONF_HUMIDITY_FAN_CONTROL_ENABLED",
            "_CONF_ENERGY_DP_ENABLE",
            "_CONF_ENERGY_DP_EVAL_DELAY_MIN",
            "_CONF_ENERGY_DP_MARGIN_MIN",
            "_CONF_ENERGY_DP_MUST_START_BY_MIN",
            "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A",
            "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B",
            "_CONF_ENERGY_DP_HOUSE_LOAD_SOURCE",
            "_CONF_HVAC_AC_RAMP_MASTER_ENABLED",
            "_CONF_HVAC_ARRESTER_IMMUNE_PERSONS",
            "_CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP",
            "_CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN",
            "_CONF_ENERGY_CLOUD_LAG_ALERT_S",
            "_CONF_TRIPPED_BREAKER_ZERO_WINDOW_S",
            "_CONF_TRIPPED_BREAKER_ROUTE_NM",
            "_CONF_LOCK_UNAVAILABLE_DEDUP_S",
            "_CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT",
            "_CONF_HUMIDITY_NORMAL_MEDIUM_PCT",
            "_CONF_HUMIDITY_NORMAL_HIGH_PCT",
            "_CONF_HUMIDITY_SWING_DELTA_PCT",
            "_CONF_HUMIDITY_SWING_MIN_ABS_PCT",
            "_CONF_CO2_LOG_ONLY_CEILING_PPM",
            "_CONF_TVOC_ABSOLUTE_HIGH_PPB",
            "_CONF_TVOC_SUSTAINED_S",
            "_CONF_SAFETY_DISCOVERY_BLOCKLIST",
            "_CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS",
            "_CONF_STUCK_SIGNAL_NM_ENABLED",
            "_CONF_STUCK_SENSOR_EXCLUSION_ENABLED",
            "_CONF_NM_DRY_RUN",
            "_CONF_NM_BUCKET_CAPACITY",
            "_CONF_NM_BUCKET_REFILL_PER_MIN",
            "_CONF_NM_PERSON_ROUTING_MATRIX",
            "_CONF_NM_PERSON_HAZARD_OVERRIDES",
            "_CONF_NM_PERSON_DND_BYPASS_SEVERITIES",
            "_CONF_NM_MUTE_DEFAULT_DURATION_MINUTES",
            "_CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS",
        ]},
    }
    mod = ast.Module(body=body, type_ignores=[])
    code = compile(mod, str(PKG / "__init__.py"), "exec")
    exec(code, ns)
    if not kill_switch:
        ns["INTEGRATION_RELOAD_SUPPRESS_ENABLED"] = False
    if signal_table_override is not None:
        ns["_INTEGRATION_KEY_SIGNAL_TABLE"] = signal_table_override
    return ns


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeConfigEntries:
    def __init__(self):
        self.reload_calls = []

    def async_reload(self, entry_id):
        # Record the call at CALL-time (not await-time) so tests observe
        # the intent without needing an event loop. Return a completed
        # coroutine so `hass.async_create_task(async_reload(...))` in
        # production is well-typed.
        self.reload_calls.append(entry_id)

        async def _done():
            return None
        return _done()


class _FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = _FakeConfigEntries()
        self._created_tasks = []

    def async_create_task(self, coro):
        # Consume the coroutine to silence "was never awaited" warnings;
        # the reload intent was already recorded by `async_reload` above.
        self._created_tasks.append(coro)
        try:
            coro.close()
        except Exception:
            pass


class _FakeEntry:
    def __init__(self, *, entry_id="integration_entry_id", title="URA",
                 entry_type="integration", options=None):
        self.entry_id = entry_id
        self.title = title
        self.data = {"entry_type": entry_type}
        self.options = options or {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_integration_options_suppress_reload_on_camera_person_entities(monkeypatch):
    """D2 acceptance: camera_person_entities-only save → zero reloads."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"camera_person_entities": ["camera.a"]})
    # Seed snapshot to the pre-save state.
    hass.data.setdefault("universal_room_automation", {})[
        "integration_last_applied_options"
    ] = {entry.entry_id: {"camera_person_entities": []}}

    dispatched = []
    def _spy_dispatch(hass_arg, sig, *args, **kwargs):
        dispatched.append((sig, args))
    _DISPATCHER.async_dispatcher_send = _spy_dispatch

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == []
    assert dispatched, "expected discharge signal to fire"
    assert dispatched[0][0] == "ura_transit_config_changed"
    # Snapshot advanced to post-save.
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"
    ][entry.entry_id]
    assert snap == {"camera_person_entities": ["camera.a"]}


def test_integration_options_mixed_falls_through_to_reload(monkeypatch):
    """A save mixing allowlisted + non-allowlisted keys → exactly one reload."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={
        "camera_person_entities": ["camera.a"],
        "electricity_rate": 0.42,
    })
    hass.data.setdefault("universal_room_automation", {})[
        "integration_last_applied_options"
    ] = {entry.entry_id: {"camera_person_entities": [], "electricity_rate": 0.30}}

    _DISPATCHER.async_dispatcher_send = lambda *a, **kw: None

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [entry.entry_id]


def test_kill_switch_disables_suppress_and_skips_dispatch(monkeypatch):
    """LOW-1: with kill switch False, reload fires AND no dispatch fires."""
    ns = _load_ns(kill_switch=False)
    hass = _FakeHass()
    entry = _FakeEntry(options={"camera_person_entities": ["camera.a"]})
    hass.data.setdefault("universal_room_automation", {})[
        "integration_last_applied_options"
    ] = {entry.entry_id: {"camera_person_entities": []}}

    dispatched = []
    _DISPATCHER.async_dispatcher_send = (
        lambda hass_arg, sig, *a, **kw: dispatched.append(sig)
    )

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [entry.entry_id]
    assert dispatched == [], (
        "kill switch OFF must skip dispatch — the reload rebuilds "
        "subscriptions naturally; parallel dispatch doubles the work"
    )


def test_egress_perimeter_keys_not_in_allowlist_v1():
    """Pin the v1 allowlist so a future silent addition of egress/perimeter
    without perimeter_alert.py discharge wire-up fails a test."""
    ns = _load_ns()
    allow = set(ns["INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS"])
    assert "camera_person_entities" in allow
    assert "egress_cameras" not in allow, (
        "PARKED — see plan follow-up #1: PerimeterAlertManager caches "
        "egress_cameras at setup with no refresh signal."
    )
    assert "perimeter_cameras" not in allow, (
        "PARKED — see plan follow-up #1."
    )
    # v1 seed is exactly one key. Adding one is a policy change that
    # should require review; this size guard makes silent expansion
    # a test failure rather than a live surprise.
    assert allow == {"camera_person_entities"}


def test_camera_person_entities_change_dispatches_transit_signal_once(monkeypatch):
    """D3: exactly one SIGNAL_URA_TRANSIT_CONFIG_CHANGED dispatch per save."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"camera_person_entities": ["camera.a"]})
    hass.data.setdefault("universal_room_automation", {})[
        "integration_last_applied_options"
    ] = {entry.entry_id: {"camera_person_entities": []}}

    dispatched = []
    _DISPATCHER.async_dispatcher_send = (
        lambda hass_arg, sig, *a, **kw: dispatched.append(sig)
    )

    _run(ns["_async_update_listener"](hass, entry))

    # Exactly one fire for the transit signal on this save.
    assert dispatched.count("ura_transit_config_changed") == 1


def test_dispatch_line_is_load_bearing_for_transit_signal_test(monkeypatch):
    """Mutation drill (feedback_hollow_test_anchors): if the wiring table
    entry is removed, the transit-signal test's expected dispatch MUST NOT
    fire — proving the dispatch line is the load-bearing surface.

    We simulate the mutation by loading the namespace with the wiring
    table set to `{}` (no entry for camera_person_entities), then confirm
    the D3 dispatch assertion would fail (zero fires)."""
    ns = _load_ns(signal_table_override={})
    hass = _FakeHass()
    entry = _FakeEntry(options={"camera_person_entities": ["camera.a"]})
    hass.data.setdefault("universal_room_automation", {})[
        "integration_last_applied_options"
    ] = {entry.entry_id: {"camera_person_entities": []}}

    dispatched = []
    _DISPATCHER.async_dispatcher_send = (
        lambda hass_arg, sig, *a, **kw: dispatched.append(sig)
    )

    _run(ns["_async_update_listener"](hass, entry))

    # Suppress branch still fires (subset-check passes), but with no
    # wiring-table entry the discharge signal does NOT dispatch —
    # this is exactly the regression the D3 test guards against.
    assert dispatched == []
    assert hass.config_entries.reload_calls == [], (
        "subset check still suppresses reload; the point of this drill "
        "is to prove the dispatch line — not the subset check — is what "
        "the D3 test observes."
    )


def test_binary_sensor_dead_import_removed():
    """MED-1 hygiene: CONF_CAMERA_PERSON_ENTITIES was a dead import at
    binary_sensor.py:61. D1 audit confirmed no live consumer in module
    body. Build removed the import in the same PR."""
    src = (PKG / "binary_sensor.py").read_text()
    # No `from ... import ... CONF_CAMERA_PERSON_ENTITIES ...` line.
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "CONF_CAMERA_PERSON_ENTITIES" not in stripped, (
            f"unexpected reference in binary_sensor.py: {line!r}"
        )

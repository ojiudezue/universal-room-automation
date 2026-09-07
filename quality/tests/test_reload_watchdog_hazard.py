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
    # Never overwrite an already-loaded homeassistant package (real HA
    # stubs loaded by sibling tests use `helpers` as a proper subpackage
    # with children like `storage`, `event`, `dispatcher`, etc.). Only
    # create missing rungs; only attach `async_dispatcher_send` if not
    # already present.
    ha = sys.modules.get("homeassistant")
    if ha is None:
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []  # mark as package so sibling imports resolve
        sys.modules["homeassistant"] = ha
    helpers = sys.modules.get("homeassistant.helpers")
    if helpers is None:
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []  # mark as package
        sys.modules["homeassistant.helpers"] = helpers
        setattr(ha, "helpers", helpers)
    disp = sys.modules.get("homeassistant.helpers.dispatcher")
    if disp is None:
        disp = types.ModuleType("homeassistant.helpers.dispatcher")
        sys.modules["homeassistant.helpers.dispatcher"] = disp
        setattr(helpers, "dispatcher", disp)
    if not hasattr(disp, "async_dispatcher_send"):
        disp.async_dispatcher_send = lambda *a, **kw: None
    return disp


_DISPATCHER = _install_ha_dispatcher_stub()

# Shared AST-slice guard (Review-C M-1).
from _ast_slice_guard import assert_ast_slice_names_covered as _ast_slice_names_covered  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC = (PKG / "__init__.py").read_text()


# ---------------------------------------------------------------------------
# Namespace loader — AST-slice the pieces this cycle needs
# ---------------------------------------------------------------------------

_KEEP_NAMES = {
    # F16 (2026-08-22, v5.89.0): dict read by _hvac_tunable_apply.
    "_HVAC_TUNABLE_SETTER_METHOD",
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
    # F16 (2026-08-22, v5.89.0): _apply_in_place routes tunables through it.
    "_hvac_tunable_apply",
    "_hvac_tunable_apply",
    "_seed_cm_last_applied_options",
    "_seed_integration_last_applied_options",  # H-1 fix-up (2026-08-15)
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
        # STEP chatter cycle (2026-08-19, v5.85.0) + F16/A2 (2026-08-22,
        # v5.89.0). These are ALIASED IMPORTS (`CONF_X as _CONF_X`) and a
        # module-level def, so a keep_names set that only matches
        # ast.Assign / ast.AnnAssign structurally cannot reach them.
        # Values mirror const.py:3859/3860/3877 exactly.
        "_CONF_CHATTER_BURST_K": "chatter_burst_k",
        "_CONF_CHATTER_T_FLOOR_S": "chatter_t_floor_s",
        "_CONF_CHATTER_MODE": "chatter_mode",
        # AC-RAMP-PIPELINE-HARDENING-1 A2 (2026-08-22, v5.89.0): the AC-ramp
        # knobs joined _HVAC_TUNABLE_DISPATCH. Aliased imports, so keep-sets
        # cannot reach them; values mirror hvac_const.py exactly.
        "_CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT": "hvac_ac_soft_nudge_daily_limit",
        "_CONF_HVAC_AC_RESET_DAY_BUDGET": "hvac_ac_reset_day_budget",
        "_CONF_HVAC_AC_RESET_NIGHT_BUDGET": "hvac_ac_reset_night_budget",
        "_CONF_HVAC_AC_RESET_OFF_DURATION": "hvac_ac_reset_off_duration",
        "_CONF_HVAC_AC_DURABILITY_WINDOW": "hvac_ac_durability_window",
        "_CONF_HVAC_AC_NIGHT_START_HHMM": "hvac_ac_night_start_hhmm",
        "_CONF_HVAC_AC_NIGHT_END_HHMM": "hvac_ac_night_end_hhmm",
        "_CONF_HVAC_AC_GATE4_PREDICATE_MODE": "hvac_ac_gate4_predicate_mode",
        "CONF_ENTRY_TYPE": "entry_type",
        "ENTRY_TYPE_ROOM": "room",
        "ENTRY_TYPE_COORDINATOR_MANAGER": "coordinator_manager",
        "ENTRY_TYPE_INTEGRATION": "integration",
        "CONF_CAMERA_PERSON_ENTITIES": "camera_person_entities",
        # INTEGRATION-RELOAD-COMPREHENSIVE Tier-1 (2026-09-06): the three
        # promoted fresh-read keys are referenced by the sliced allowlist
        # frozenset, so the exec namespace must define their string values
        # (mirror const.py:1473/2931/2340 exactly).
        "CONF_CENSUS_CROSS_VALIDATION": "census_cross_validation",
        "CONF_CENSUS_BLE_CANCEL_ENABLED": "census_ble_cancel_enabled",
        "CONF_KNOWN_FACE_GUESTS": "known_face_guests",
        "CONF_EGRESS_IDENTITY_FAILSAFE_STRICT": "egress_identity_failsafe_strict",
        # INTEGRATION-RELOAD-COMPREHENSIVE-1 Tier-2 (2026-09-07 plan D2.1):
        # perimeter-step keys admitted to the allowlist + wired to
        # SIGNAL_URA_PERIMETER_CONFIG_CHANGED (except zero-consumer
        # hours keys). Values mirror const.py exactly.
        "CONF_PERIMETER_CAMERAS": "perimeter_cameras",
        "CONF_EGRESS_CAMERAS": "egress_cameras",
        "CONF_PERIMETER_VEHICLE_HOURS_START": "perimeter_vehicle_hours_start",
        "CONF_PERIMETER_VEHICLE_HOURS_END": "perimeter_vehicle_hours_end",
        "CONF_PERIMETER_ENRICHMENT_ENABLED": "perimeter_enrichment_enabled",
        "CONF_PERIMETER_ENRICHMENT_PROVIDER": "perimeter_enrichment_provider",
        "CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS": "perimeter_enrichment_person_sensors",
        "CONF_PERIMETER_ENRICHMENT_MODEL": "perimeter_enrichment_model",
        "CONF_PERIMETER_ENRICHMENT_MAX_TOKENS": "perimeter_enrichment_max_tokens",
        "CONF_PERIMETER_ENRICHMENT_PROVIDER_ID": "perimeter_enrichment_provider_id",
        "CONF_EXTERIOR_SNAPSHOT_OFFSET_S": "exterior_snapshot_offset_s",
        "CONF_PERIMETER_ALERT_HOURS_START": "perimeter_alert_hours_start",
        "CONF_PERIMETER_ALERT_HOURS_END": "perimeter_alert_hours_end",
        "SIGNAL_URA_PERIMETER_CONFIG_CHANGED": "ura_perimeter_config_changed",
        # Deliberately NOT promoted (UNSAFE — structural listener reg at
        # __init__.py:2364); used by the fall-through test below.
        "CONF_ENHANCED_CENSUS": "enhanced_census",
        "CONF_ZONE": "zone",
        # Review-C M-1 fix-up (2026-08-15) — AST-slice guard requires
        # every Name load (including type annotations) to be present in
        # the namespace or built into Python.
        "ConfigEntry": type("ConfigEntry", (), {}),
        "HomeAssistant": type("HomeAssistant", (), {}),
        # B-MED-1 fix-up (2026-08-15): the wiring table now references
        # the imported const, so the sliced module reads it at exec time.
        "SIGNAL_URA_TRANSIT_CONFIG_CHANGED": "ura_transit_config_changed",
        # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18):
        "CONF_FACE_RECOGNITION_ENABLED": "face_recognition_enabled",
        "CONF_EGRESS_IDENTITY_ENABLED": "egress_identity_enabled",
        "SIGNAL_URA_FACE_RECOGNITION_CHANGED": "ura_face_recognition_changed",
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
            "_CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR",
            "_CONF_ENERGY_PEAK_BUFFER_TARGET",
            "_CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN",
            "_CONF_ENERGY_EV_BATTERY_DRAIN_SOC",
            # evse-charge-onset cycle knob.
            "_CONF_ENERGY_EVSE_CHARGE_ONSET_TIME",
            # Rev 6 D-A - dedicated enable toggle.
            "_CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED",
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
    # Review-C M-1 fix-up (2026-08-15): post-compile AST guard.
    # See docstring of `_ast_slice_guard.assert_ast_slice_names_covered`.
    _ast_slice_names_covered(mod, ns)
    exec(code, ns)
    if not kill_switch:
        ns["INTEGRATION_RELOAD_SUPPRESS_ENABLED"] = False
    if signal_table_override is not None:
        ns["_INTEGRATION_KEY_SIGNAL_TABLE"] = signal_table_override
    return ns


# (guard body now lives in `_ast_slice_guard.assert_ast_slice_names_covered`)


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
        #
        # FOOTNOTE (Review-C L-3, 2026-08-15): this fake asserts intent
        # ("was reload SCHEDULED?"), not side-effects of the reload
        # actually running. Production wraps in
        # `hass.async_create_task(async_reload(...))` and the reload
        # only executes when the loop schedules it. If a future test
        # wants to observe reload side-effects (unload symmetry, child
        # entry teardown), this fake needs to become a real coroutine
        # awaited by the loop — today's tests only need intent.
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
    """A save mixing allowlisted + non-allowlisted keys → exactly one reload.

    Review-C L-2 fix-up (2026-08-15): also asserts the FALL-THROUGH
    snapshot-advance write happens. Without this assertion a regression
    that dropped the reseed at `__init__.py:6620` would leave the snapshot
    at the pre-save value and ship green — matches the CM branch's
    B-HIGH-2 pattern (reseed BEFORE the reload so a concurrent second
    save diffs against a clean baseline).
    """
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={
        "camera_person_entities": ["camera.a"],
        "electricity_rate": 0.42,
    })
    pre_save_snap = {"camera_person_entities": [], "electricity_rate": 0.30}
    hass.data.setdefault("universal_room_automation", {})[
        "integration_last_applied_options"
    ] = {entry.entry_id: dict(pre_save_snap)}

    _DISPATCHER.async_dispatcher_send = lambda *a, **kw: None

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [entry.entry_id]
    # C-L-2: fall-through path must reseed the snapshot to post-save
    # options BEFORE scheduling the reload.
    post_save_snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"
    ][entry.entry_id]
    assert post_save_snap == {
        "camera_person_entities": ["camera.a"],
        "electricity_rate": 0.42,
    }
    assert post_save_snap != pre_save_snap, (
        "regression: fall-through path failed to advance the snapshot"
    )


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
    """Allowlist membership pin.

    INTEGRATION-RELOAD-COMPREHENSIVE-1 Tier-2 (2026-09-07, plan D2.1):
    egress_cameras + perimeter_cameras + 11 more perimeter-step keys
    are NOW allowlisted. PerimeterAlertManager subscribes to
    SIGNAL_URA_PERIMETER_CONFIG_CHANGED and narrow-re-reads its cached
    camera-list state per plan A4 (preserves boot-settle window).

    Prior "PARKED" assertions removed - parked follow-up #1 discharged.
    """
    ns = _load_ns()
    allow = set(ns["INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS"])
    assert "camera_person_entities" in allow
    assert "egress_cameras" in allow, (
        "Tier-2 D2.1 (2026-09-07): egress_cameras now discharges via "
        "SIGNAL_URA_PERIMETER_CONFIG_CHANGED (perimeter_alert.py) and "
        "SIGNAL_URA_TRANSIT_CONFIG_CHANGED (transit_validator.py)."
    )
    assert "perimeter_cameras" in allow
    # v1 seed was {camera_person_entities} only. CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1
    # (2026-08-18) added CONF_FACE_RECOGNITION_ENABLED (paired with
    # SIGNAL_URA_FACE_RECOGNITION_CHANGED discharge to transit_validator
    # + presence) and CONF_EGRESS_IDENTITY_ENABLED (fresh-read at all
    # consumers, no signal). INTEGRATION-RELOAD-COMPREHENSIVE Tier-1
    # (2026-09-06) added three MORE fresh-read (path-(a)) census keys —
    # census_cross_validation, census_ble_cancel_enabled, known_face_guests
    # — each verified sole-consumer fresh-read + confirmed by two
    # framing-disjoint plan reviews; NONE needs a discharge signal.
    # enhanced_census stays OUT (UNSAFE — structural listener reg at
    # __init__.py:2364). Any further expansion is a policy change that
    # should require review; this exact-set guard makes silent expansion
    # a test failure rather than a live surprise.
    assert "enhanced_census" not in allow, (
        "UNSAFE — gates event-census listener registration at "
        "__init__.py:2364; must stay on the reload path."
    )
    # CONF_EGRESS_IDENTITY_FAILSAFE_STRICT added (2026-09-06) as the
    # pair-invariant sibling of egress_identity_enabled (same options step).
    # INTEGRATION-RELOAD-COMPREHENSIVE-1 Tier-2 (2026-09-07): plan A2
    # admits the two retired hours keys as defence-in-depth against a
    # future write-path that forgets the strip; they have zero consumers
    # today (superseded by perimeter_vehicle_hours_*).
    assert "perimeter_alert_hours_start" in allow
    assert "perimeter_alert_hours_end" in allow
    assert allow == {
        # Tier-1 (rev-1 + Wave-1 census).
        "camera_person_entities",
        "face_recognition_enabled",
        "egress_identity_enabled",
        "census_cross_validation",
        "census_ble_cancel_enabled",
        "known_face_guests",
        "egress_identity_failsafe_strict",
        # Tier-2 D2.1 (2026-09-07) - 13 perimeter-step keys.
        "perimeter_cameras",
        "egress_cameras",
        "perimeter_vehicle_hours_start",
        "perimeter_vehicle_hours_end",
        "perimeter_enrichment_enabled",
        "perimeter_enrichment_provider",
        "perimeter_enrichment_person_sensors",
        "perimeter_enrichment_model",
        "perimeter_enrichment_max_tokens",
        "perimeter_enrichment_provider_id",
        "exterior_snapshot_offset_s",
        "perimeter_alert_hours_start",
        "perimeter_alert_hours_end",
    }


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


def test_wiring_table_entry_is_load_bearing_for_transit_signal_dispatch(monkeypatch):
    """Mutation drill (feedback_hollow_test_anchors) — TABLE LOOKUP variant.

    Reviews B-LOW-1 + C-M-2 (2026-08-15): the prior name
    ``test_dispatch_line_is_load_bearing_...`` overclaimed — this drill
    ONLY proves the wiring-table LOOKUP inside
    `_dispatch_integration_key_signals` is load-bearing (removing the
    table entry → zero dispatch). It does NOT prove the CALL SITE to
    `_dispatch_integration_key_signals` inside `_async_update_listener`
    is load-bearing; the sibling test
    ``test_dispatch_call_site_is_load_bearing_...`` below covers that.
    Both drills together anchor the surface end-to-end.
    """
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
    # wiring-table entry the discharge signal does NOT dispatch.
    assert dispatched == []
    assert hass.config_entries.reload_calls == [], (
        "subset check still suppresses reload; the point of this drill "
        "is to prove the TABLE LOOKUP — not the subset check — is what "
        "the D3 test observes."
    )


def test_dispatch_call_site_is_load_bearing_for_transit_signal_dispatch(monkeypatch):
    """Mutation drill — CALL-SITE variant (Reviews B-LOW-1 + C-M-2).

    Monkeypatches `_dispatch_integration_key_signals` in the loaded
    namespace to a no-op call recorder, replays the D3 flow, and
    asserts the recorder was called with `{CONF_CAMERA_PERSON_ENTITIES}`.
    Then flips the recorder to `None`-return (still callable, dispatch
    happens via the recorder's own body — for the "was it called at all"
    check the presence of the recorded call proves the wiring). To prove
    the CALL is load-bearing (as opposed to only the TABLE lookup), we
    then flip `_dispatch_integration_key_signals` to a no-op that does
    NOT record and asserts the behavioral consequence: replacing the
    dispatch call with a no-op means NO signal ever reaches the
    dispatcher stub — the sibling behavioral test
    `test_camera_person_entities_change_dispatches_transit_signal_once`
    would then see zero fires. We simulate that here in one test."""
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

    # Neuter the sibling helper to a no-op — mimics what happens if the
    # call site inside `_async_update_listener` is deleted/commented.
    calls = []
    def _noop(hass_arg, entry_arg, changed):
        calls.append(set(changed))
    ns["_dispatch_integration_key_signals"] = _noop

    _run(ns["_async_update_listener"](hass, entry))

    # The listener still routes through the sibling helper — that is the
    # positive load-bearing evidence for the call site (calls != []
    # confirms the listener DID invoke the helper). The behavioral
    # dispatcher stub sees nothing, matching the "call site deleted"
    # regression signature the reviewer requested we anchor.
    assert calls == [{"camera_person_entities"}], (
        "call site regression: listener did not invoke "
        "_dispatch_integration_key_signals with the changed keys"
    )
    assert dispatched == [], (
        "with the helper neutered, no signal must reach the dispatcher "
        "(this is the false-anchor scenario B-LOW-1 / C-M-2 flagged)"
    )


def test_binary_sensor_dead_import_removed():
    """MED-1 HYGIENE ASSERTION (not a behavior test — Review-C L-1):
    CONF_CAMERA_PERSON_ENTITIES was a dead import at binary_sensor.py:61.
    D1 audit confirmed no live consumer in module body. Build removed the
    import in the same PR. This test verifies the import stays removed;
    it does NOT cover the reload path. Do not mis-count it toward D2/D3
    behavioral coverage."""
    src = (PKG / "binary_sensor.py").read_text()
    # No `from ... import ... CONF_CAMERA_PERSON_ENTITIES ...` line.
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "CONF_CAMERA_PERSON_ENTITIES" not in stripped, (
            f"unexpected reference in binary_sensor.py: {line!r}"
        )


# ---------------------------------------------------------------------------
# Fix-up (2026-08-15) — Review A H-1 / Review B B-HIGH-1: integration-entry
# snapshot must be seeded at setup so the FIRST post-restart save doesn't
# see `old={}` and fall through to a full cascading reload.
# ---------------------------------------------------------------------------


def test_seed_helper_when_invoked_makes_first_save_suppress_reload():
    """Regression test for Reviews A H-1 / B B-HIGH-1 — HELPER-SCOPE.

    Orchestrator re-drill note (2026-08-15): the prior name
    `test_first_post_restart_save_suppresses_when_snapshot_unseeded_by_test_but_seeded_by_setup`
    overclaimed. This test proves the helper WORKS: if invoked at boot
    with an integration entry, the resulting snapshot is such that a
    subsequent single-key camera_person_entities save falls through the
    suppress path (no reload). It does NOT prove production's
    async_setup_entry actually calls the helper — that assurance lives
    in `test_seed_helper_call_node_exists_in_integration_setup_ast`
    (AST anchor, comment-invisible).

    Test discipline: DELIBERATELY does NOT pre-populate
    `hass.data[DOMAIN]["integration_last_applied_options"]`. It calls
    the seed helper directly (matching what the setup path does), then
    fires the listener with a single-key camera_person_entities change
    and asserts `reload_calls == []` (suppress path fires)."""
    ns = _load_ns()
    hass = _FakeHass()
    # Pre-save entry state — mirrors what's persisted before the save.
    pre_save_options = {"camera_person_entities": []}
    entry = _FakeEntry(options=dict(pre_save_options))

    # No pre-seeding of hass.data — this is the cold-restart state.
    assert "integration_last_applied_options" not in hass.data.get(
        "universal_room_automation", {},
    )

    # Setup-time seed — this is the fix under test. Invoke the same
    # helper the integration-setup path now calls (mirrors CM seed).
    ns["_seed_integration_last_applied_options"](hass, entry)

    # Simulate the operator's save: options is now the post-save dict.
    entry.options = {"camera_person_entities": ["camera.a"]}

    _DISPATCHER.async_dispatcher_send = lambda *a, **kw: None

    _run(ns["_async_update_listener"](hass, entry))

    # THE INCIDENT SCENARIO. Before the fix: reload_calls == [entry.entry_id]
    # (full cascade → 5-minute outage). After the fix: [] (suppress fires).
    assert hass.config_entries.reload_calls == [], (
        "H-1 regression: first post-restart save cascaded to reload "
        "(seed helper did not populate the snapshot, so subset check "
        "saw old={} and fell through — the exact 2026-08-07 incident)"
    )


def _find_integration_setup_if_body(tree: ast.Module) -> list:
    """Locate the `if entry_type == ENTRY_TYPE_INTEGRATION:` body inside
    the top-level `async def async_setup_entry(...)` — returns the list
    of AST statement nodes that form that branch's body.

    Fix-up 3/3 (2026-08-15, orchestrator re-drill): the previous
    string-grep anchor could not distinguish a live Call from a
    commented-out or pass-neutered line (grep sees the substring inside
    the block comment at the top of the integration setup, and a
    pass-replacement still leaves the substring in the file). AST walk
    is comment-invisible and requires a real Call node to pass.
    """
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry":
            for sub in node.body:
                # Match `if entry_type == ENTRY_TYPE_INTEGRATION:` exactly.
                if isinstance(sub, ast.If) and isinstance(sub.test, ast.Compare):
                    left = sub.test.left
                    comps = sub.test.comparators
                    if (
                        isinstance(left, ast.Name)
                        and left.id == "entry_type"
                        and len(sub.test.ops) == 1
                        and isinstance(sub.test.ops[0], ast.Eq)
                        and len(comps) == 1
                        and isinstance(comps[0], ast.Name)
                        and comps[0].id == "ENTRY_TYPE_INTEGRATION"
                    ):
                        return sub.body
    raise AssertionError(
        "async_setup_entry ENTRY_TYPE_INTEGRATION branch not found "
        "in __init__.py — structural refactor detected"
    )


def _iter_calls_by_name(nodes) -> list:
    """Yield `(lineno, ast.Call)` for every Call whose callee is a Name
    matching the seed helper. Walks the entire subtree of `nodes`
    (which is expected to be an iterable of statement nodes)."""
    out = []
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                out.append((sub.lineno, sub))
    return out


def test_seed_helper_call_node_exists_in_integration_setup_ast():
    """H-1 wire-in anchor (AST variant — orchestrator re-drill fix).

    The prior grep-based anchor was defeated by a `pass`-replacement
    (grep still matched the substring inside the block comment at
    `__init__.py:1601-1605` explaining Bug Class #46) AND by a comment-
    out (grep matches text inside comments). AST parse ignores both:
    only a live `Call` node with `func.id == '_seed_integration_last_applied_options'`
    passes.

    Drill discipline (both variants MUST fail this test):
      1. `sed -i 's/^        _seed_integration_last_applied_options.*$/        pass  # neutered/'`
         → live Call node deleted → red.
      2. `sed -i 's/^        _seed_integration_last_applied_options/        # _seed_integration/'`
         → live Call node becomes a comment → red.
    """
    tree = ast.parse(INIT_SRC)
    int_body = _find_integration_setup_if_body(tree)

    # Look for a live Call to the seed helper anywhere inside the
    # integration setup branch (AST walk is comment-invisible).
    seed_calls = [
        (lineno, call)
        for lineno, call in _iter_calls_by_name(int_body)
        if isinstance(call.func, ast.Name)
        and call.func.id == "_seed_integration_last_applied_options"
    ]
    assert seed_calls, (
        "H-1 wire-in regression: no live Call to "
        "`_seed_integration_last_applied_options` in the "
        "ENTRY_TYPE_INTEGRATION setup branch of async_setup_entry. "
        "Comments and `pass` lines don't count — the AST needs a real "
        "Call node. Consequence: first post-restart camera_person_entities "
        "save will cascade a full reload (2026-08-07 outage recurs)."
    )

    # Ordering: the seed call must appear BEFORE the
    # `entry.add_update_listener(_async_update_listener)` registration
    # (mirrors CM ordering rule). Anchor on the registration Call whose
    # callee is `entry.add_update_listener` and single arg is the
    # `_async_update_listener` name.
    listener_registrations = []
    for n in int_body:
        for sub in ast.walk(n):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "add_update_listener"
                and len(sub.args) == 1
                and isinstance(sub.args[0], ast.Name)
                and sub.args[0].id == "_async_update_listener"
            ):
                listener_registrations.append(sub.lineno)
    assert listener_registrations, (
        "H-1 sanity: could not locate the `entry.add_update_listener("
        "_async_update_listener)` call in the integration setup branch"
    )

    first_seed_line = min(ln for ln, _ in seed_calls)
    first_listener_line = min(listener_registrations)
    assert first_seed_line < first_listener_line, (
        "H-1 ordering regression: the seed helper must be called BEFORE "
        "add_update_listener is armed (else a re-entrant options save "
        f"could race the seed). seed@{first_seed_line}, "
        f"listener@{first_listener_line}"
    )


def test_seed_helper_populates_snapshot_from_entry_options():
    """Direct test that `_seed_integration_last_applied_options` writes
    a deep copy of entry.options into hass.data. Catches a regression
    that would neuter the seed (e.g. writing `{}` unconditionally)."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={
        "camera_person_entities": ["camera.a"],
        "electricity_rate": 0.42,
    })
    ns["_seed_integration_last_applied_options"](hass, entry)
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"
    ][entry.entry_id]
    assert snap == {
        "camera_person_entities": ["camera.a"],
        "electricity_rate": 0.42,
    }
    # Snapshot must be a fresh top-level dict (matches CM seed shape:
    # `dict(entry.options)` is a shallow copy — replacing the top-level
    # dict at seed time is what enables the diff at listener time).
    assert snap is not entry.options


# ---------------------------------------------------------------------------
# Fix-up (2026-08-15) — Review B B-MED-1: signal table references the
# authoritative constant, not a raw duplicate string.
# ---------------------------------------------------------------------------


def test_integration_key_signal_table_uses_transit_config_changed_const():
    """B-MED-1 regression guard: the wiring table value must be the same
    string as `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` in const.py (the
    subscriber at transit_validator.py:41 imports the same const). Test
    reads BOTH from source so a rename on either side flags the drift.
    """
    const_src = (PKG / "const.py").read_text()
    import re
    m = re.search(
        r"^SIGNAL_URA_TRANSIT_CONFIG_CHANGED\s*:\s*Final\s*=\s*\"([^\"]+)\"",
        const_src, re.MULTILINE,
    )
    assert m, "SIGNAL_URA_TRANSIT_CONFIG_CHANGED not found in const.py"
    const_value = m.group(1)

    ns = _load_ns()
    tbl = ns["_INTEGRATION_KEY_SIGNAL_TABLE"]
    assert tbl["camera_person_entities"] == (const_value,), (
        "B-MED-1 regression: wiring table dispatches a string that does "
        f"NOT equal SIGNAL_URA_TRANSIT_CONFIG_CHANGED={const_value!r} — "
        "subscriber will silently no-op on rename"
    )


# ---------------------------------------------------------------------------
# Fix-up (2026-08-15) — Review C M-1: post-compile AST guard proves it
# raises on an unstubbed symbol.
# ---------------------------------------------------------------------------


def test_ast_slice_guard_raises_on_unstubbed_symbol():
    """C-M-1 regression guard: the shared `assert_ast_slice_names_covered`
    walker must raise `RuntimeError` when the sliced code references a
    Name that is neither a builtin, nor pre-seeded in `ns`, nor a local
    assignment/def inside the slice. Verifies via a synthetic module
    that references a fake constant."""
    src = "x = FAKE_CONSTANT_THAT_DOES_NOT_EXIST + 1\n"
    mod = ast.parse(src)
    ns: dict = {}
    try:
        _ast_slice_names_covered(mod, ns)
    except RuntimeError as e:
        assert "FAKE_CONSTANT_THAT_DOES_NOT_EXIST" in str(e)
        return
    raise AssertionError(
        "C-M-1 regression: AST guard did not raise on an unstubbed name"
    )


def test_ast_slice_guard_accepts_pre_seeded_symbol():
    """Complement of the above: the guard must NOT raise when the
    referenced Name is present in `ns`."""
    src = "y = STUBBED_CONSTANT + 1\n"
    mod = ast.parse(src)
    _ast_slice_names_covered(mod, {"STUBBED_CONSTANT": 42})  # no raise


# ============================================================================
# INTEGRATION-RELOAD-COMPREHENSIVE Tier-1 (2026-09-06)
# Promote three fresh-read (path-(a)) census keys to the allowlist. They have
# NO _INTEGRATION_KEY_SIGNAL_TABLE row (no cached consumer), so a suppressed
# save fires ZERO reloads AND dispatches NOTHING. Mutation anchor: deleting a
# key from INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS makes its suppress test
# RED (the save falls through to a reload).
# ============================================================================

def _seed_snapshot(hass, entry, pre):
    hass.data.setdefault("universal_room_automation", {})[
        "integration_last_applied_options"
    ] = {entry.entry_id: dict(pre)}


def test_integration_suppress_reload_on_census_cross_validation(monkeypatch):
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"census_cross_validation": False})
    _seed_snapshot(hass, entry, {"census_cross_validation": True})
    dispatched = []
    _DISPATCHER.async_dispatcher_send = lambda h, sig, *a, **k: dispatched.append(sig)
    _run(ns["_async_update_listener"](hass, entry))
    assert hass.config_entries.reload_calls == []  # RED if key removed from allowlist
    assert dispatched == []  # path-(a): no signal-table row → no dispatch
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"][entry.entry_id]
    assert snap == {"census_cross_validation": False}  # snapshot advanced


def test_integration_suppress_reload_on_ble_cancel_and_known_guests(monkeypatch):
    """A save changing both remaining Tier-1 keys → zero reload, no dispatch."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={
        "census_ble_cancel_enabled": False,
        "known_face_guests": ["oji"],
    })
    _seed_snapshot(hass, entry, {
        "census_ble_cancel_enabled": True, "known_face_guests": [],
    })
    dispatched = []
    _DISPATCHER.async_dispatcher_send = lambda h, sig, *a, **k: dispatched.append(sig)
    _run(ns["_async_update_listener"](hass, entry))
    assert hass.config_entries.reload_calls == []  # RED if either key removed
    assert dispatched == []
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"][entry.entry_id]
    assert snap == {"census_ble_cancel_enabled": False, "known_face_guests": ["oji"]}


def test_integration_enhanced_census_falls_through_to_reload(monkeypatch):
    """CONF_ENHANCED_CENSUS is UNSAFE (structural listener reg at
    __init__.py:2364) and MUST NOT be in the allowlist — a save changing it
    reloads. RED if someone wrongly admits enhanced_census."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"enhanced_census": False})
    _seed_snapshot(hass, entry, {"enhanced_census": True})
    _DISPATCHER.async_dispatcher_send = lambda *a, **k: None
    _run(ns["_async_update_listener"](hass, entry))
    assert hass.config_entries.reload_calls == [entry.entry_id]


def test_integration_suppress_egress_pair_failsafe_and_enabled(monkeypatch):
    """PAIR-INVARIANT: a camera_census save that flips BOTH
    egress_identity_enabled AND egress_identity_failsafe_strict (they share
    the step) is fully suppressed. RED if failsafe_strict is dropped from the
    allowlist — the pair would no longer be a subset → reload."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={
        "egress_identity_enabled": False,
        "egress_identity_failsafe_strict": False,
    })
    _seed_snapshot(hass, entry, {
        "egress_identity_enabled": True, "egress_identity_failsafe_strict": True,
    })
    _DISPATCHER.async_dispatcher_send = lambda *a, **k: None
    _run(ns["_async_update_listener"](hass, entry))
    assert hass.config_entries.reload_calls == []  # RED if failsafe_strict removed
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"][entry.entry_id]
    assert snap == {
        "egress_identity_enabled": False, "egress_identity_failsafe_strict": False,
    }



# ============================================================================
# INTEGRATION-RELOAD-COMPREHENSIVE-1 Tier-2 (2026-09-07, plan D2.1 + D2.5)
# ============================================================================


def test_perimeter_step_key_dispatches_perimeter_signal_once(monkeypatch):
    """D2.1: a perimeter-step save fires SIGNAL_URA_PERIMETER_CONFIG_CHANGED
    exactly once per allowlisted key + zero reload calls."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"perimeter_vehicle_hours_start": 21})
    _seed_snapshot(hass, entry, {"perimeter_vehicle_hours_start": 22})
    dispatched = []
    _DISPATCHER.async_dispatcher_send = (
        lambda h, sig, *a, **k: dispatched.append(sig)
    )
    _run(ns["_async_update_listener"](hass, entry))
    assert hass.config_entries.reload_calls == []
    assert dispatched.count("ura_perimeter_config_changed") == 1
    # Snapshot advanced (dispatch succeeded).
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"][entry.entry_id]
    assert snap == {"perimeter_vehicle_hours_start": 21}


def test_camera_list_key_dispatches_both_transit_and_perimeter(monkeypatch):
    """D2.1 pair invariant: perimeter_cameras / egress_cameras are cached by
    BOTH transit_validator and perimeter_alert - must fire both signals."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"perimeter_cameras": ["camera.a"]})
    _seed_snapshot(hass, entry, {"perimeter_cameras": []})
    dispatched = []
    _DISPATCHER.async_dispatcher_send = (
        lambda h, sig, *a, **k: dispatched.append(sig)
    )
    _run(ns["_async_update_listener"](hass, entry))
    assert hass.config_entries.reload_calls == []
    assert dispatched.count("ura_transit_config_changed") == 1
    assert dispatched.count("ura_perimeter_config_changed") == 1


def test_snapshot_holds_key_when_dispatch_raises(monkeypatch):
    """D2.5 (plan A7): a swallowed dispatch must NOT advance the snapshot
    for that key - otherwise a cached-consumer regression is PERMANENT.

    Mutation drill: remove the `if k in dispatched_ok:` guard on snapshot
    advance (or the corresponding retention branch) and this test goes RED.
    """
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"perimeter_cameras": ["camera.a"]})
    pre = {"perimeter_cameras": []}
    _seed_snapshot(hass, entry, pre)

    def _raising(hass_arg, sig, *a, **kw):
        raise RuntimeError("dispatcher chose violence")
    _DISPATCHER.async_dispatcher_send = _raising

    _run(ns["_async_update_listener"](hass, entry))

    # Reload still suppressed (subset test passes).
    assert hass.config_entries.reload_calls == []
    # Snapshot MUST retain the pre-save value for the failed key so the
    # next save's diff still shows it as changed - otherwise the cached
    # consumer stays stale forever (Bug Class #7 amplifier).
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"][entry.entry_id]
    assert snap["perimeter_cameras"] == [], (
        "A7 regression: snapshot advanced for a key whose dispatch RAISED "
        f"- snap={snap!r}. A swallowed dispatch that advances the snapshot "
        "loses the change permanently (silent stale-consumer state)."
    )


def test_snapshot_advances_normally_when_dispatch_succeeds(monkeypatch):
    """A7 complement: successful dispatch advances the snapshot fully.
    Pins the success path so a future 'always-retain' fix-up regression
    (which would break every subsequent suppressed save) fails a test."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"perimeter_cameras": ["camera.a"]})
    _seed_snapshot(hass, entry, {"perimeter_cameras": []})
    _DISPATCHER.async_dispatcher_send = lambda *a, **k: None
    _run(ns["_async_update_listener"](hass, entry))
    snap = hass.data["universal_room_automation"][
        "integration_last_applied_options"][entry.entry_id]
    assert snap == {"perimeter_cameras": ["camera.a"]}


def test_dispatch_helper_returns_success_set(monkeypatch):
    """A7 helper contract: `_dispatch_integration_key_signals` returns a
    set of the keys whose dispatch fully succeeded. Fresh-read keys with
    NO wiring row are vacuously OK. Mutation drill: remove the return
    statement and this test fails BY NAME."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry()

    # Success case.
    _DISPATCHER.async_dispatcher_send = lambda *a, **k: None
    ok = ns["_dispatch_integration_key_signals"](
        hass, entry, {"perimeter_cameras", "census_cross_validation"},
    )
    assert isinstance(ok, set)
    # Both should be OK: perimeter_cameras dispatches its 2 signals
    # cleanly; census_cross_validation has no row (vacuously OK).
    assert ok == {"perimeter_cameras", "census_cross_validation"}

    # Failure case for ONE key only.
    calls = []
    def _selective(hass_arg, sig, *a, **kw):
        calls.append(sig)
        if sig == "ura_perimeter_config_changed":
            raise RuntimeError("nope")
    _DISPATCHER.async_dispatcher_send = _selective
    ok = ns["_dispatch_integration_key_signals"](
        hass, entry, {"perimeter_cameras", "camera_person_entities"},
    )
    # perimeter_cameras fires transit (OK) + perimeter (RAISE) -> NOT OK.
    # camera_person_entities fires transit only (OK).
    assert ok == {"camera_person_entities"}


# ----------------------------------------------------------------------------
# perimeter_alert.py wire-in anchors (mutation drills).
# ----------------------------------------------------------------------------

import ast as _ast


def _perimeter_src():
    return (PKG / "perimeter_alert.py").read_text()


def test_perimeter_config_signal_unsub_field_init_to_none():
    """Wire anchor (three-part template leg 1 - transit_validator.py:264).

    __init__ MUST initialize self._config_signal_unsub = None so
    async_setup's `if self._config_signal_unsub is None:` guard actually
    fires on first setup and idempotency holds on re-entry. Mutation drill:
    remove the field init and this test goes RED.
    """
    src = _perimeter_src()
    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ClassDef) and node.name == "PerimeterAlertManager":
            for sub in node.body:
                if isinstance(sub, _ast.FunctionDef) and sub.name == "__init__":
                    # Look for an Assign to self._config_signal_unsub or
                    # an AnnAssign of the same.
                    for stmt in _ast.walk(sub):
                        if isinstance(stmt, (_ast.Assign, _ast.AnnAssign)):
                            targets = (
                                stmt.targets if isinstance(stmt, _ast.Assign)
                                else [stmt.target]
                            )
                            for t in targets:
                                if (
                                    isinstance(t, _ast.Attribute)
                                    and isinstance(t.value, _ast.Name)
                                    and t.value.id == "self"
                                    and t.attr == "_config_signal_unsub"
                                ):
                                    val = stmt.value
                                    assert isinstance(val, _ast.Constant) and val.value is None, (
                                        "field init must be None, got "
                                        f"{_ast.dump(val)}"
                                    )
                                    return
    raise AssertionError(
        "perimeter_alert.py __init__ missing "
        "`self._config_signal_unsub = None` - D2.1 wire regression"
    )


def test_perimeter_config_signal_subscribed_in_async_setup():
    """Wire anchor (leg 2 - transit_validator.py:347-366).

    async_setup MUST call `async_dispatcher_connect` with
    SIGNAL_URA_PERIMETER_CONFIG_CHANGED (via the imported name) AND assign
    the result to self._config_signal_unsub. Mutation drill: delete the
    subscribe block or the assignment and this test goes RED.
    """
    src = _perimeter_src()
    tree = _ast.parse(src)
    setup_body = None
    for node in _ast.walk(tree):
        if isinstance(node, _ast.AsyncFunctionDef) and node.name == "async_setup":
            setup_body = node
            break
    assert setup_body is not None, "async_setup not found"

    # Locate an Assign whose target is self._config_signal_unsub and
    # whose value is a Call.
    found = False
    for stmt in _ast.walk(setup_body):
        if isinstance(stmt, _ast.Assign):
            for t in stmt.targets:
                if (
                    isinstance(t, _ast.Attribute)
                    and isinstance(t.value, _ast.Name)
                    and t.value.id == "self"
                    and t.attr == "_config_signal_unsub"
                    and isinstance(stmt.value, _ast.Call)
                ):
                    # Confirm SIGNAL_URA_PERIMETER_CONFIG_CHANGED appears
                    # as an arg (by Name).
                    for arg in stmt.value.args:
                        if (
                            isinstance(arg, _ast.Name)
                            and arg.id == "SIGNAL_URA_PERIMETER_CONFIG_CHANGED"
                        ):
                            found = True
                            break
    assert found, (
        "async_setup missing subscribe: no "
        "`self._config_signal_unsub = async_dispatcher_connect(..., "
        "SIGNAL_URA_PERIMETER_CONFIG_CHANGED, ...)` call. "
        "D2.1 discharge wire regression."
    )


def test_perimeter_config_signal_unsub_in_async_teardown():
    """Wire anchor (leg 3 - transit_validator.py:899-904).

    async_teardown MUST call self._config_signal_unsub() and clear the
    field. Mutation drill: remove the unsub block and this test goes RED
    (leak test - a signal handler surviving teardown accumulates across
    reload cycles).
    """
    src = _perimeter_src()
    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.AsyncFunctionDef) and node.name == "async_teardown":
            # Two conditions: (1) a Call on self._config_signal_unsub,
            # (2) an Assign self._config_signal_unsub = None.
            has_call = False
            has_reset = False
            for stmt in _ast.walk(node):
                if isinstance(stmt, _ast.Call):
                    f = stmt.func
                    if (
                        isinstance(f, _ast.Attribute)
                        and isinstance(f.value, _ast.Name)
                        and f.value.id == "self"
                        and f.attr == "_config_signal_unsub"
                    ):
                        has_call = True
                if isinstance(stmt, _ast.Assign):
                    for t in stmt.targets:
                        if (
                            isinstance(t, _ast.Attribute)
                            and isinstance(t.value, _ast.Name)
                            and t.value.id == "self"
                            and t.attr == "_config_signal_unsub"
                            and isinstance(stmt.value, _ast.Constant)
                            and stmt.value.value is None
                        ):
                            has_reset = True
            assert has_call, (
                "async_teardown missing unsub call - listener leaks across "
                "reload cycles (three-part template leg 3 regression)"
            )
            assert has_reset, (
                "async_teardown must reset self._config_signal_unsub = None "
                "after unsub so idempotency holds if teardown is called twice"
            )
            return
    raise AssertionError("async_teardown not found in perimeter_alert.py")


def test_perimeter_config_change_preserves_boot_settle_window():
    """A4 preservation contract: the handler MUST NOT reset self._setup_time.

    A rebuild that reset _setup_time would silently disarm the perimeter
    alarm for PERIMETER_BOOT_SETTLE_S - a security-affecting regression
    the reload path never causes. Mutation drill: introduce
    `self._setup_time = dt_util.now()` into the handler body (or remove
    the `self._setup_time = saved_setup_time` restore) and this test
    goes RED BY NAME.

    Structural (AST) assertion: the handler's finally-block MUST contain
    `self._setup_time = saved_setup_time` (or equivalent restore). This
    is comment-invisible; a delete of the restore line is directly RED.
    """
    src = _perimeter_src()
    tree = _ast.parse(src)
    handler = None
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.AsyncFunctionDef)
            and node.name == "_async_on_perimeter_config_changed"
        ):
            handler = node
            break
    assert handler is not None, (
        "handler _async_on_perimeter_config_changed missing - D2.1 not built"
    )

    # Assert: the handler contains a `try/finally` where the finally block
    # restores self._setup_time from a saved variable.
    restore_found = False
    for stmt in _ast.walk(handler):
        if isinstance(stmt, _ast.Try):
            for fstmt in _ast.walk(_ast.Module(body=stmt.finalbody, type_ignores=[])):
                if isinstance(fstmt, _ast.Assign):
                    for t in fstmt.targets:
                        if (
                            isinstance(t, _ast.Attribute)
                            and isinstance(t.value, _ast.Name)
                            and t.value.id == "self"
                            and t.attr == "_setup_time"
                        ):
                            v = fstmt.value
                            if isinstance(v, _ast.Name) and v.id.startswith("saved"):
                                restore_found = True
    assert restore_found, (
        "A4 regression: handler does not restore self._setup_time from a "
        "saved variable in its finally-block. A missing restore means "
        "self.async_setup() (called inside try) will overwrite _setup_time "
        "with dt_util.now(), silently disarming the perimeter alarm for "
        "the boot-settle window."
    )

    # Additional guard: the handler must NOT directly assign
    # `self._setup_time = dt_util.now()` outside the finally restore path.
    for stmt in _ast.walk(handler):
        if isinstance(stmt, _ast.Assign):
            for t in stmt.targets:
                if (
                    isinstance(t, _ast.Attribute)
                    and isinstance(t.value, _ast.Name)
                    and t.value.id == "self"
                    and t.attr == "_setup_time"
                ):
                    v = stmt.value
                    if isinstance(v, _ast.Call):
                        # A direct now() assignment is the mutation-drill
                        # forbidden shape.
                        raise AssertionError(
                            "A4 regression: handler directly assigns "
                            f"self._setup_time to a Call ({_ast.dump(v)}) - "
                            "this resets the boot-settle window"
                        )


def test_perimeter_handler_preserves_active_and_in_flight_state():
    """A4 preservation contract (extension): _active, _pending_dispatches,
    _dispatch_in_flight, _edge_captures MUST also be restored in the
    finally-block."""
    src = _perimeter_src()
    tree = _ast.parse(src)
    handler = None
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.AsyncFunctionDef)
            and node.name == "_async_on_perimeter_config_changed"
        ):
            handler = node
            break
    assert handler is not None
    must_restore = {
        "_active",
        "_pending_dispatches",
        "_dispatch_in_flight",
        "_edge_captures",
    }
    restored = set()
    for stmt in _ast.walk(handler):
        if isinstance(stmt, _ast.Try):
            for fstmt in _ast.walk(_ast.Module(body=stmt.finalbody, type_ignores=[])):
                if isinstance(fstmt, _ast.Assign):
                    for t in fstmt.targets:
                        if (
                            isinstance(t, _ast.Attribute)
                            and isinstance(t.value, _ast.Name)
                            and t.value.id == "self"
                            and t.attr in must_restore
                        ):
                            restored.add(t.attr)
    missing = must_restore - restored
    assert not missing, (
        f"A4 regression: handler finally-block does not restore {missing}. "
        "async_setup() re-invocation would leave the lifecycle state "
        "inconsistent."
    )


def test_perimeter_signal_const_matches_across_modules():
    """B-MED-1-shape guard for the perimeter signal (mirror of
    test_integration_key_signal_table_uses_transit_config_changed_const):
    the string used in the wiring table must equal the string defined in
    const.py. A rename on either side flags drift here."""
    import re as _re
    const_src = (PKG / "const.py").read_text()
    m = _re.search(
        r'^SIGNAL_URA_PERIMETER_CONFIG_CHANGED\s*:\s*Final\s*=\s*"([^"]+)"',
        const_src, _re.MULTILINE,
    )
    assert m, "SIGNAL_URA_PERIMETER_CONFIG_CHANGED not found in const.py"
    const_value = m.group(1)

    ns = _load_ns()
    tbl = ns["_INTEGRATION_KEY_SIGNAL_TABLE"]
    # Perimeter-step key discharges perimeter signal.
    assert const_value in tbl["perimeter_vehicle_hours_start"]
    # Camera-list key discharges both.
    assert "ura_transit_config_changed" in tbl["perimeter_cameras"]
    assert const_value in tbl["perimeter_cameras"]

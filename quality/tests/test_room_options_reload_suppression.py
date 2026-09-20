"""Behavioral tests for ROOM-entry options-flow reload suppression.

Cycle: ROOM-CONFIG-SAVE-FULL-RELOAD-STALL-1 (Tier 2-DB).
Plan: docs/planning/PLANNING_room_config_reload_suppression.md

Two styles of coverage:

1. **Behavioral (mutation-anchored).** AST-slice `_async_update_listener`
   + `_seed_room_last_applied_options` into a clean namespace, drive
   them with a `_FakeHass` / `_FakeEntry` that records reload intent,
   and assert on suppress vs fall-through. Mirrors the pattern from
   ``test_reload_watchdog_hazard.py`` which already drives the same
   listener for the INTEGRATION branch. Each of the listed tests
   is anchored — removing the corresponding production line makes a
   SPECIFIC named test go RED.

2. **Source-AST wire-up.** Structural checks for D0 seed call site
   ordering + D2 dedup-set init/gate (the parts that are structural
   invariants, not behavioral flows).
"""
from __future__ import annotations

import ast
import asyncio
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA dispatcher stub (the listener's ROOM branch does a function-local
# `from homeassistant.helpers.dispatcher import async_dispatcher_send`).
# ---------------------------------------------------------------------------

def _install_ha_dispatcher_stub():
    ha = sys.modules.get("homeassistant")
    if ha is None:
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []
        sys.modules["homeassistant"] = ha
    helpers = sys.modules.get("homeassistant.helpers")
    if helpers is None:
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers
        setattr(ha, "helpers", helpers)
    disp = sys.modules.get("homeassistant.helpers.dispatcher")
    if disp is None:
        disp = types.ModuleType("homeassistant.helpers.dispatcher")
        sys.modules["homeassistant.helpers.dispatcher"] = disp
        setattr(helpers, "dispatcher", disp)
    if not hasattr(disp, "async_dispatcher_send"):
        disp.async_dispatcher_send = lambda *a, **kw: None
    # Signals module — the listener imports SIGNAL_ROOM_ENTRY_LIFECYCLE
    # from ``.domain_coordinators.signals``. That import is not resolved
    # against a real package at test time; stub it out.
    ura = sys.modules.get("custom_components.universal_room_automation")
    return disp


_DISPATCHER = _install_ha_dispatcher_stub()


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC = (PKG / "__init__.py").read_text()
SUBSTRATE_SRC = (
    PKG / "domain_coordinators" / "occupancy_substrate.py"
).read_text()

# Shared AST-slice guard (Review-C M-1) — matches sibling tests.
from _ast_slice_guard import assert_ast_slice_names_covered as _ast_slice_names_covered  # noqa: E402


# ---------------------------------------------------------------------------
# AST slice loader — pull `_async_update_listener` + helpers + the
# allowlist frozensets into an execable namespace.
# ---------------------------------------------------------------------------

_KEEP_NAMES = {
    "OPTIONS_RELOAD_SUPPRESS_KEYS",
    "INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS",
    "INTEGRATION_RELOAD_SUPPRESS_ENABLED",
    "_INTEGRATION_KEY_SIGNAL_TABLE",
    "_ROOM_SUPPRESS_KEYS",
    "_NM_A2_KEYS",
    "_NM_C_KEYS",
    "_HVAC_TUNABLE_DISPATCH",
    "_EC_SETTER_DISPATCH",
    "_OFFPEAK_DRAIN_QUALITY",
    "_NO_LIVE_ATTR_KEYS",
    "_HVAC_TUNABLE_SETTER_METHOD",
}
_KEEP_FUNCS = {
    "_hvac_tunable_apply",
    "_seed_cm_last_applied_options",
    "_seed_integration_last_applied_options",
    "_seed_room_last_applied_options",
    "_apply_in_place",
    "_dispatch_integration_key_signals",
    "_async_update_listener",
}


def _load_ns() -> dict:
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

    # Namespace — mirror the sibling watchdog test's stubs and add every
    # _CONF_* alias the sliced code loads. String values are irrelevant
    # to the reload-vs-suppress decision — only KEY IDENTITY matters —
    # so we use the alias lowercased as the string except where a real
    # value is asserted in tests (kept truthful to const.py).
    conf_aliases_from_watchdog = [
        "_CONF_CHATTER_BURST_K", "_CONF_CHATTER_T_FLOOR_S", "_CONF_CHATTER_MODE",
        "_CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT", "_CONF_HVAC_AC_RESET_DAY_BUDGET",
        "_CONF_HVAC_AC_RESET_NIGHT_BUDGET", "_CONF_HVAC_AC_RESET_OFF_DURATION",
        "_CONF_HVAC_AC_DURABILITY_WINDOW", "_CONF_HVAC_AC_NIGHT_START_HHMM",
        "_CONF_HVAC_AC_NIGHT_END_HHMM", "_CONF_HVAC_AC_GATE4_PREDICATE_MODE",
        "_CONF_HVAC_VACANCY_GRACE_MINUTES", "_CONF_HVAC_VACANCY_GRACE_CONSTRAINED",
        "_CONF_HVAC_MAX_OCCUPANCY_HOURS", "_CONF_HVAC_ZONE_ENTRY_DWELL",
        "_CONF_DYNAMIC_PRESET_DWELL_MINUTES",
        "_CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA", "_CONF_HVAC_COVER_CLOSE_TEMP",
        "_CONF_HVAC_COVER_OPEN_TEMP", "_CONF_HVAC_COVER_OVERRIDE_HOURS",
        "_CONF_HVAC_SOLAR_BANK_FLOOR", "_CONF_HVAC_FAN_ACTIVATION_DELTA",
        "_CONF_HVAC_FAN_HYSTERESIS", "_CONF_HVAC_AC_NUDGE_SIZE",
        "_CONF_HVAC_AC_NUDGE_DURATION", "_CONF_HVAC_AC_NUDGE_EVAL_DELAY",
        "_CONF_HVAC_AC_SUSTAINED_SAMPLES", "_CONF_HVAC_AC_DETECTION_TIME_GATE",
        "_CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT", "_CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL",
        "_CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT", "_CONF_ENERGY_OFFPEAK_DRAIN_GOOD",
        "_CONF_ENERGY_OFFPEAK_DRAIN_MODERATE", "_CONF_ENERGY_OFFPEAK_DRAIN_POOR",
        "_CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR", "_CONF_ENERGY_PEAK_BUFFER_TARGET",
        "_CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN",
        "_CONF_ENERGY_EV_BATTERY_DRAIN_SOC",
        "_CONF_ENERGY_EVSE_CHARGE_ONSET_TIME",
        "_CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED",
        "_CONF_ENERGY_FILL_PRIORITY_SOC", "_CONF_ENERGY_EXCESS_SOLAR_SOC",
        "_CONF_ENERGY_MAINS_EXPORT_ENTITY", "_CONF_ENERGY_SOLAR_NAMEPLATE_W",
        "_CONF_DYNAMIC_PRESET_HYSTERESIS_F", "_CONF_HVAC_EGRESS_THRESHOLD_MIN",
        "_CONF_HVAC_EGRESS_RESUME_DELAY_MIN", "_CONF_FAN_INTERFERENCE_HOLD_S",
        "_CONF_ROUTINE_EVENT_COOLDOWN_DAYS", "_CONF_ROUTINE_EVENT_MIN_SEVERITY",
        "_CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS",
        "_CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS",
        "_CONF_BAYESIAN_CELL_STALENESS_DAYS",
        "_CONF_OPTIMIZER_AUTONOMY_LEVEL", "_CONF_OPTIMIZER_KILL_SWITCH",
        "_CONF_OPTIMIZER_DIMENSION_AUTONOMY", "_CONF_OPTIMIZER_CONFIDENCE_GATE",
        "_CONF_OPTIMIZER_RATE_CAP_PER_HOUR", "_CONF_OPTIMIZER_QUIET_HOURS_SOURCE",
        "_CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL",
        "_CONF_OPTIMIZER_LLM_TASK_ENTITY", "_CONF_OPTIMIZER_LLM_TRIAGE_ENTITY",
        "_CONF_OPTIMIZER_LLM_SYSTEM_PROMPT",
        "_CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H",
        "_CONF_OPTIMIZER_SAFETY_DENY_ENTITIES",
        "_CONF_COMFORT_TEMP_MIN", "_CONF_COMFORT_TEMP_MAX",
        "_CONF_COMFORT_HUMIDITY_MAX",
        "_CONF_MF_SLEEP_SUPPRESS", "_CONF_MF_NIGHT_SUPPRESS_MODE",
        "_CONF_FAN_CONTROL_ENABLED", "_CONF_HUMIDITY_FAN_CONTROL_ENABLED",
        "_CONF_ENERGY_DP_ENABLE", "_CONF_ENERGY_DP_EVAL_DELAY_MIN",
        "_CONF_ENERGY_DP_MARGIN_MIN", "_CONF_ENERGY_DP_MUST_START_BY_MIN",
        "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A", "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B",
        "_CONF_ENERGY_DP_HOUSE_LOAD_SOURCE",
        "_CONF_HVAC_AC_RAMP_MASTER_ENABLED",
        "_CONF_HVAC_ARRESTER_IMMUNE_PERSONS",
        "_CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP",
        "_CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN",
        "_CONF_ENERGY_CLOUD_LAG_ALERT_S",
        "_CONF_TRIPPED_BREAKER_ZERO_WINDOW_S", "_CONF_TRIPPED_BREAKER_ROUTE_NM",
        "_CONF_LOCK_UNAVAILABLE_DEDUP_S",
        "_CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT", "_CONF_HUMIDITY_NORMAL_MEDIUM_PCT",
        "_CONF_HUMIDITY_NORMAL_HIGH_PCT", "_CONF_HUMIDITY_SWING_DELTA_PCT",
        "_CONF_HUMIDITY_SWING_MIN_ABS_PCT",
        "_CONF_CO2_LOG_ONLY_CEILING_PPM", "_CONF_TVOC_ABSOLUTE_HIGH_PPB",
        "_CONF_TVOC_SUSTAINED_S", "_CONF_SAFETY_DISCOVERY_BLOCKLIST",
        "_CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS",
        "_CONF_STUCK_SIGNAL_NM_ENABLED", "_CONF_STUCK_SENSOR_EXCLUSION_ENABLED",
        "_CONF_NM_DRY_RUN", "_CONF_NM_BUCKET_CAPACITY",
        "_CONF_NM_BUCKET_REFILL_PER_MIN",
        "_CONF_NM_PERSON_ROUTING_MATRIX", "_CONF_NM_PERSON_HAZARD_OVERRIDES",
        "_CONF_NM_PERSON_DND_BYPASS_SEVERITIES",
        "_CONF_NM_MUTE_DEFAULT_DURATION_MINUTES",
        "_CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS",
    ]
    # Real string values for the D1-added ROOM allowlist keys — used by
    # behavioral tests that assert on specific key identities.
    room_new_conf_values = {
        "_CONF_HVAC_VACANCY_HOLD": "hvac_vacancy_hold",
        "_CONF_HVAC_VACANCY_HOLD_NIGHT": "hvac_vacancy_hold_night",
        "_CONF_HVAC_COORDINATION_ENABLED": "hvac_coordination_enabled",
        "_CONF_COMFORT_FAN_AWAY_VETO_ENABLED": "comfort_fan_away_veto_enabled",
        "_CONF_WET_ROOM": "wet_room",
        "_CONF_BLE_HOLD_CAP_ENABLED": "ble_hold_cap_enabled",
        "_CONF_FAN_TEMP_THRESHOLD": "fan_temp_threshold",
        "_CONF_HUMIDITY_FAN_THRESHOLD": "humidity_fan_threshold",
        "_CONF_HUMIDITY_FAN_TIMEOUT": "humidity_fan_timeout",
        "_CONF_HUMIDITY_FAN_MAX_RUNTIME": "humidity_fan_max_runtime",
        "_CONF_HUMIDITY_FAN_SPIKE_ENABLED": "humidity_fan_spike_enabled",
        "_CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT": "humidity_fan_spike_delta_pct",
        "_CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S": "humidity_fan_spike_ema_alpha_s",
        "_CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE": "humidity_fan_spike_baseline_mode",
        "_CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED": "humidity_fan_presence_runtime_enabled",
        "_CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S": "humidity_fan_presence_runtime_base_s",
        "_CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S": "humidity_fan_presence_runtime_per_min_s",
        "_CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S": "humidity_fan_presence_runtime_cap_s",
        "_CONF_FAN_SPEED_LOW_TEMP": "fan_speed_low_temp",
        "_CONF_FAN_SPEED_MED_TEMP": "fan_speed_med_temp",
        "_CONF_FAN_SPEED_HIGH_TEMP": "fan_speed_high_temp",
        "_CONF_TARGET_TEMP_HEAT": "target_temp_heat",
        "_CONF_TARGET_TEMP_COOL": "target_temp_cool",
    }

    ns: dict = {
        "_LOGGER": MagicMock(),
        "DOMAIN": "universal_room_automation",
        "CONF_ENTRY_TYPE": "entry_type",
        "ENTRY_TYPE_ROOM": "room",
        "ENTRY_TYPE_COORDINATOR_MANAGER": "coordinator_manager",
        "ENTRY_TYPE_INTEGRATION": "integration",
        "CONF_ZONE": "zone",
        "CONF_CAMERA_PERSON_ENTITIES": "camera_person_entities",
        "CONF_CENSUS_CROSS_VALIDATION": "census_cross_validation",
        "CONF_CENSUS_BLE_CANCEL_ENABLED": "census_ble_cancel_enabled",
        "CONF_KNOWN_FACE_GUESTS": "known_face_guests",
        "CONF_EGRESS_IDENTITY_FAILSAFE_STRICT": "egress_identity_failsafe_strict",
        "CONF_PERIMETER_VEHICLE_HOURS_START": "perimeter_vehicle_hours_start",
        "CONF_PERIMETER_VEHICLE_HOURS_END": "perimeter_vehicle_hours_end",
        "CONF_PERIMETER_ENRICHMENT_ENABLED": "perimeter_enrichment_enabled",
        "CONF_PERIMETER_ENRICHMENT_PROVIDER": "perimeter_enrichment_provider",
        "CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS": "perimeter_enrichment_person_sensors",
        "CONF_PERIMETER_ENRICHMENT_MODEL": "perimeter_enrichment_model",
        "CONF_PERIMETER_ENRICHMENT_MAX_TOKENS": "perimeter_enrichment_max_tokens",
        "CONF_PERIMETER_ENRICHMENT_PROVIDER_ID": "perimeter_enrichment_provider_id",
        "CONF_EXTERIOR_SNAPSHOT_OFFSET_S": "exterior_snapshot_offset_s",
        "CONF_APPLIANCE_RECORDS": "appliance_records",
        "CONF_ENHANCED_CENSUS": "enhanced_census",
        "CONF_FACE_RECOGNITION_ENABLED": "face_recognition_enabled",
        "CONF_EGRESS_IDENTITY_ENABLED": "egress_identity_enabled",
        "SIGNAL_URA_FACE_RECOGNITION_CHANGED": "ura_face_recognition_changed",
        "SIGNAL_URA_TRANSIT_CONFIG_CHANGED": "ura_transit_config_changed",
        "ConfigEntry": type("ConfigEntry", (), {}),
        "HomeAssistant": type("HomeAssistant", (), {}),
        **{k: k.lower() for k in conf_aliases_from_watchdog},
        **room_new_conf_values,
        # Real values for the 4 pre-existing ROOM allowlist aliases
        # (watchdog's `k.lower()` default would give the wrong string).
        "_CONF_COMFORT_TEMP_MIN": "comfort_temp_min",
        "_CONF_COMFORT_TEMP_MAX": "comfort_temp_max",
        "_CONF_COMFORT_HUMIDITY_MAX": "comfort_humidity_max",
        "_CONF_FAN_CONTROL_ENABLED": "fan_control_enabled",
        "_CONF_HUMIDITY_FAN_CONTROL_ENABLED": "humidity_fan_control_enabled",
    }
    mod = ast.Module(body=body, type_ignores=[])
    code = compile(mod, str(PKG / "__init__.py"), "exec")
    _ast_slice_names_covered(mod, ns)
    exec(code, ns)
    return ns


# ---------------------------------------------------------------------------
# Fakes (copied minimal from test_reload_watchdog_hazard.py)
# ---------------------------------------------------------------------------


class _FakeConfigEntries:
    def __init__(self):
        self.reload_calls = []

    def async_reload(self, entry_id):
        self.reload_calls.append(entry_id)

        async def _done():
            return None
        return _done()


class _FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = _FakeConfigEntries()

    def async_create_task(self, coro):
        try:
            coro.close()
        except Exception:
            pass


class _FakeEntry:
    def __init__(self, *, entry_id="room_entry_1", title="Bathroom",
                 entry_type="room", options=None, room_name="Bathroom"):
        self.entry_id = entry_id
        self.title = title
        self.data = {"entry_type": entry_type, "room_name": room_name}
        self.options = options or {}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# The 20-key climate-form default-materialization payload (per plan §D1
# and config_flow.py:11519-11746 Optional(default=...)).
# ---------------------------------------------------------------------------

_CLIMATE_FORM_KEYS_ALLOWLISTED = (
    # 4 pre-existing allowlisted:
    "fan_control_enabled", "humidity_fan_control_enabled",
    # comfort_temp_min/max, comfort_humidity_max live in the comfort step,
    # not climate — they're pre-existing allowlisted for the slider path.
    # 23 D1 additions:
    "hvac_vacancy_hold", "hvac_vacancy_hold_night",
    "hvac_coordination_enabled", "comfort_fan_away_veto_enabled",
    "wet_room", "ble_hold_cap_enabled",
    "fan_temp_threshold",
    "humidity_fan_threshold", "humidity_fan_timeout",
    "humidity_fan_max_runtime",
    "humidity_fan_spike_enabled", "humidity_fan_spike_delta_pct",
    "humidity_fan_spike_ema_alpha_s", "humidity_fan_spike_baseline_mode",
    "humidity_fan_presence_runtime_enabled",
    "humidity_fan_presence_runtime_base_s",
    "humidity_fan_presence_runtime_per_min_s",
    "humidity_fan_presence_runtime_cap_s",
    "fan_speed_low_temp", "fan_speed_med_temp", "fan_speed_high_temp",
    "target_temp_heat", "target_temp_cool",
)

_CLIMATE_FORM_KEY_EXCLUDED_ENTITY = "climate_entity"


# ===========================================================================
# BEHAVIORAL — D0 setup seeding + first-save suppression
# ===========================================================================


def test_d0_first_save_after_setup_suppresses_when_allowlisted_only():
    """Seed via `_seed_room_last_applied_options`, then a ROOM save that
    changed only an allowlisted key must NOT trigger reload. This is the
    guaranteed-first-save failure D0 exists to fix.
    """
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={"fan_control_enabled": True})
    # Simulate what the ROOM setup path now does: seed BEFORE the
    # listener could ever fire.
    ns["_seed_room_last_applied_options"](hass, entry)
    # Operator toggles the LIVE key from True -> False.
    entry.options = {"fan_control_enabled": False}

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [], (
        "first-save-after-setup on an allowlisted key must SUPPRESS"
    )


def test_d0_neuter_no_seed_first_save_falls_through_to_reload():
    """Neuter drill for the seed line.

    Without seeding, `old={}` and `new=entry.options`; every key in
    `entry.options` looks 'changed'. In production the ROOM entry's
    `entry.options` typically contains OTHER (non-climate-step) keys
    that live in earlier onboarding steps (motion sensors, etc.) which
    are NOT in `_ROOM_SUPPRESS_KEYS`. So the subset check fails and the
    save reloads.

    With D0 seeding those pre-existing keys are captured in the snapshot,
    so a save that only mutates an allowlisted key produces a
    `changed_keys` set that IS a subset of the allowlist, and suppress
    fires. This test simulates the pre-D0 world by NOT calling the seed
    helper: at least one non-allowlisted key (`motion_sensors`) is present
    in `entry.options` at save time.
    """
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={
        "motion_sensors": ["binary_sensor.bathroom_motion"],
        "fan_control_enabled": True,
    })
    # Deliberately DO NOT call `_seed_room_last_applied_options`.
    # Save mutates ONLY the allowlisted key — but without seeding,
    # motion_sensors also appears in `changed_keys` (present in new,
    # absent in old={}) → subset check fails → reload.
    entry.options = {
        "motion_sensors": ["binary_sensor.bathroom_motion"],
        "fan_control_enabled": False,
    }

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [entry.entry_id], (
        "Without D0 seeding, the first save must fall through when a "
        "non-allowlisted key is present in entry.options. This is the "
        "failure mode D0 fixes."
    )


# ===========================================================================
# BEHAVIORAL — D1 full-form Climate & Fans save
# ===========================================================================


def test_d1_full_climate_form_save_suppresses_when_no_excluded_key_touched():
    """The reported symptom fix.

    Operator saves the Climate & Fans step. HA materializes ~20 default
    fields into ``user_input``. With every non-entity climate-step key
    now allowlisted, a save whose ONLY effective delta is a bump to a
    single allowlisted knob (here: humidity_fan_threshold 60 -> 65)
    must SUPPRESS. The other ~19 keys have the same value in the
    snapshot and the new options — `changed_keys` reduces to
    {humidity_fan_threshold}, which is a subset of the allowlist.

    Anchored: if `humidity_fan_threshold` (or any of the 22 D1
    additions) is removed from `_ROOM_SUPPRESS_KEYS`, this test flips
    to reload and RED-flags.
    """
    ns = _load_ns()
    hass = _FakeHass()
    # Full-form snapshot at whatever the operator last saved.
    baseline = {k: 1 for k in _CLIMATE_FORM_KEYS_ALLOWLISTED}
    entry = _FakeEntry(options=baseline)
    ns["_seed_room_last_applied_options"](hass, entry)
    # Operator touches ONE knob; HA re-submits ALL climate-step defaults.
    new_options = dict(baseline)
    new_options["humidity_fan_threshold"] = 999
    entry.options = new_options

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [], (
        "full-form Climate & Fans save with only allowlisted delta "
        "must SUPPRESS — this is the reported symptom the cycle fixes"
    )
    # Snapshot advanced.
    snap = hass.data["universal_room_automation"][
        "room_last_applied_options"
    ][entry.entry_id]
    assert snap["humidity_fan_threshold"] == 999


def test_d1_climate_entity_change_still_reloads():
    """CONF_CLIMATE_ENTITY stays EXCLUDED — an entity_id rewire must
    still reload the room. Anchored: adding _CONF_CLIMATE_ENTITY to
    `_ROOM_SUPPRESS_KEYS` would make this test flip green (a silent
    admission of a structural-key we consider unsafe).
    """
    ns = _load_ns()
    hass = _FakeHass()
    baseline = {k: 1 for k in _CLIMATE_FORM_KEYS_ALLOWLISTED}
    baseline[_CLIMATE_FORM_KEY_EXCLUDED_ENTITY] = "climate.old"
    entry = _FakeEntry(options=baseline)
    ns["_seed_room_last_applied_options"](hass, entry)
    new_options = dict(baseline)
    new_options[_CLIMATE_FORM_KEY_EXCLUDED_ENTITY] = "climate.new"
    entry.options = new_options

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [entry.entry_id], (
        "CONF_CLIMATE_ENTITY change must RELOAD — structural rewire"
    )


def test_d1_virgin_room_first_save_default_materialization_suppresses():
    """Plan-review P7 virgin-room test.

    A room whose options dict is EMPTY at setup (no climate step ever
    saved) receives its first save. HA's Optional(default=...) fills
    ~20 fields into user_input. Because D0 seeded the snapshot from
    `entry.options={}` and the diff computes `changed_keys` against
    that, EVERY field looks changed on this first save — but all are
    now allowlisted, so the save SUPPRESSES.
    """
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={})
    ns["_seed_room_last_applied_options"](hass, entry)
    # First-ever climate save materializes all 23 defaults.
    entry.options = {k: 1 for k in _CLIMATE_FORM_KEYS_ALLOWLISTED}

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [], (
        "virgin-room first climate save with only allowlisted keys "
        "must SUPPRESS (default-materialization all-or-nothing)"
    )


def test_d1_virgin_room_first_save_with_climate_entity_falls_through():
    """Same virgin case but the first save also introduces a
    CONF_CLIMATE_ENTITY value — the whole form falls through to reload
    because ONE excluded key materialized."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={})
    ns["_seed_room_last_applied_options"](hass, entry)
    new_options = {k: 1 for k in _CLIMATE_FORM_KEYS_ALLOWLISTED}
    new_options[_CLIMATE_FORM_KEY_EXCLUDED_ENTITY] = "climate.picked"
    entry.options = new_options

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [entry.entry_id]


# ===========================================================================
# ALLOWLIST MEMBERSHIP — proven behaviorally, one test per allowlisted
# key. Mutation-anchored: dropping a key from _ROOM_SUPPRESS_KEYS makes
# its parametrized case flip to reload and RED-flag by name.
# ===========================================================================


@pytest.mark.parametrize("conf_string", list(_CLIMATE_FORM_KEYS_ALLOWLISTED))
def test_solo_key_change_suppresses(conf_string):
    """For EACH allowlisted climate-step key, a save whose only delta
    is that one key MUST suppress. Failure = the key silently left
    the allowlist."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={conf_string: "old"})
    ns["_seed_room_last_applied_options"](hass, entry)
    entry.options = {conf_string: "new"}

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [], (
        f"solo change to '{conf_string}' must SUPPRESS "
        "(D1 allowlist verdict LIVE or REFRESHED-with-coverage)"
    )


def test_solo_climate_entity_change_reloads():
    """CONF_CLIMATE_ENTITY intentionally EXCLUDED — entity-id rewire
    requires a full reload; audit block cites the reason."""
    ns = _load_ns()
    hass = _FakeHass()
    entry = _FakeEntry(options={
        _CLIMATE_FORM_KEY_EXCLUDED_ENTITY: "climate.old",
    })
    ns["_seed_room_last_applied_options"](hass, entry)
    entry.options = {_CLIMATE_FORM_KEY_EXCLUDED_ENTITY: "climate.new"}

    _run(ns["_async_update_listener"](hass, entry))

    assert hass.config_entries.reload_calls == [entry.entry_id]


# ===========================================================================
# SOURCE-AST — D0 wire-up ordering + D2 substrate dedup structure
# ===========================================================================


def test_seed_room_last_applied_options_called_before_add_update_listener():
    """The seed call MUST precede `add_update_listener` in ROOM setup —
    D0's raison d'etre. Neuter drill: comment the seed call → this
    test RED-flags on "seed call missing".
    """
    seed_pat = r"_seed_room_last_applied_options\(hass, entry\)"
    listener_pat = (
        r"entry\.async_on_unload\(entry\.add_update_listener\("
        r"_async_update_listener\)\)"
    )
    seeds = [m.start() for m in re.finditer(seed_pat, INIT_SRC)]
    listeners = [m.start() for m in re.finditer(listener_pat, INIT_SRC)]
    assert seeds, "_seed_room_last_applied_options call missing"
    assert listeners, "add_update_listener registration missing"
    assert any(s < l for s in seeds for l in listeners), (
        "seed must be called BEFORE add_update_listener in ROOM setup"
    )


def test_room_unload_pops_snapshot():
    assert re.search(
        r'"room_last_applied_options",\s*\{\},?\s*\)\s*\.pop\('
        r'entry\.entry_id,\s*None\)',
        INIT_SRC,
    ), "ROOM unload must pop entry_id from room_last_applied_options"


# ===========================================================================
# BEHAVIORAL — OccupancySubstrate WARN dedup (D2 + B-LOW-1)
# ===========================================================================


class _FakeSubstrateEntry:
    """Mimics the fields ``_discover_entity_map`` reads on each entry."""
    def __init__(self, *, room_name, motion=None, mmwave=None, occupancy=None):
        # ``_discover_entity_map`` reads ``entry.data`` and ``entry.options``
        # and merges them — put all fields in ``data`` for simplicity.
        self.data = {
            "entry_type": "room",
            "room_name": room_name,
            "motion_sensors": list(motion or []),
            "presence_sensors": list(mmwave or []),
            "occupancy_sensors": list(occupancy or []),
        }
        self.options = {}


class _FakeSubstrateHass:
    def __init__(self, entries):
        self._entries = list(entries)

        class _CE:
            def __init__(self, entries):
                self._entries = entries

            def async_entries(self, domain):
                return list(self._entries)

        self.config_entries = _CE(self._entries)


def _make_substrate(entries):
    """Build a bare OccupancySubstrate instance with the __init__ state
    the WARN dedup + fast-path rely on. Bypass the full __init__ (which
    the tests don't exercise) so nothing outside `_discover_entity_map`
    needs mocking."""
    from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
        OccupancySubstrate,
    )
    sub = object.__new__(OccupancySubstrate)
    sub.hass = _FakeSubstrateHass(entries)
    sub._warned_multi_conf = set()
    sub._warned_cross_room = set()
    return sub


def test_d2_cross_room_conflict_warns_once_then_dedupes(caplog):
    """Two ROOM entries claim the same entity → one WARN. Calling
    ``_discover_entity_map`` again re-runs the walk (same shape) and
    MUST NOT emit a second WARN.

    Anchored: removing the ``_warned_cross_room`` gate in
    ``occupancy_substrate.py`` flips this to two WARNs (test RED).
    """
    entries = [
        _FakeSubstrateEntry(room_name="RoomA", motion=["binary_sensor.shared"]),
        _FakeSubstrateEntry(room_name="RoomB", motion=["binary_sensor.shared"]),
    ]
    sub = _make_substrate(entries)

    import logging
    with caplog.at_level(
        logging.WARNING,
        logger=(
            "custom_components.universal_room_automation."
            "domain_coordinators.occupancy_substrate"
        ),
    ):
        sub._discover_entity_map()
        sub._discover_entity_map()

    cross_warnings = [
        r for r in caplog.records
        if "claimed by multiple" in r.getMessage()
    ]
    assert len(cross_warnings) == 1, (
        "cross-room-claim WARN must fire exactly once across two "
        "identical discovery passes"
    )


def test_d2_cross_room_conflict_changed_kind_re_warns(caplog):
    """B-LOW-1 fix-up.

    First pass: RoomA claims `binary_sensor.shared` as MOTION and RoomB
    as OCCUPANCY (kind mismatch). One WARN. Mutate RoomA to claim it as
    MMWAVE instead; the CHANGED conflict (`prior_kind` flipped) MUST
    fire a fresh WARN because the dedup key now includes both kinds
    (per B-LOW-1). Anchored: reverting the dedup-key to the narrower
    triple flips this test RED.
    """
    entry_a = _FakeSubstrateEntry(
        room_name="RoomA", motion=["binary_sensor.shared"],
    )
    entry_b = _FakeSubstrateEntry(
        room_name="RoomB", occupancy=["binary_sensor.shared"],
    )
    sub = _make_substrate([entry_a, entry_b])

    import logging
    with caplog.at_level(
        logging.WARNING,
        logger=(
            "custom_components.universal_room_automation."
            "domain_coordinators.occupancy_substrate"
        ),
    ):
        sub._discover_entity_map()
        # Reclassify RoomA's claim: motion → mmwave. Same entity, same
        # rooms, but the kinds differ from the first pass.
        entry_a.data["motion_sensors"] = []
        entry_a.data["presence_sensors"] = ["binary_sensor.shared"]
        sub._discover_entity_map()

    cross_warnings = [
        r for r in caplog.records
        if "claimed by multiple" in r.getMessage()
    ]
    assert len(cross_warnings) == 2, (
        "changed cross-room kind conflict must produce a second WARN "
        "(B-LOW-1: dedup key includes kinds)"
    )


def test_d2_multi_conf_conflict_warns_once_then_dedupes(caplog):
    """Same room lists the entity in TWO CONF slots (motion +
    occupancy) → one precedence-WARN. A second discovery pass must
    not re-emit.

    Anchored: removing the ``_warned_multi_conf`` gate re-emits every
    pass; the test RED-flags.
    """
    entry = _FakeSubstrateEntry(
        room_name="RoomC",
        motion=["binary_sensor.dual"],
        occupancy=["binary_sensor.dual"],
    )
    sub = _make_substrate([entry])

    import logging
    with caplog.at_level(
        logging.WARNING,
        logger=(
            "custom_components.universal_room_automation."
            "domain_coordinators.occupancy_substrate"
        ),
    ):
        sub._discover_entity_map()
        sub._discover_entity_map()

    multi = [
        r for r in caplog.records
        if "appears in multiple CONF lists" in r.getMessage()
    ]
    assert len(multi) == 1


def test_d2_multi_conf_changed_kind_re_warns(caplog):
    """B-LOW-1 for the multi-CONF case.

    First pass: RoomC has entity in motion AND occupancy — precedence
    keeps motion, drops occupancy → WARN. Mutate to motion + mmwave;
    now precedence keeps motion, drops mmwave — a DIFFERENT conflict
    (kind_dropped changed). Must WARN again because dedup key includes
    (entity, room, prior_kind, kind_dropped).
    """
    entry = _FakeSubstrateEntry(
        room_name="RoomC",
        motion=["binary_sensor.dual"],
        occupancy=["binary_sensor.dual"],
    )
    sub = _make_substrate([entry])

    import logging
    with caplog.at_level(
        logging.WARNING,
        logger=(
            "custom_components.universal_room_automation."
            "domain_coordinators.occupancy_substrate"
        ),
    ):
        sub._discover_entity_map()
        # Change the dropped-kind: occupancy → mmwave.
        entry.data["occupancy_sensors"] = []
        entry.data["presence_sensors"] = ["binary_sensor.dual"]
        sub._discover_entity_map()

    multi = [
        r for r in caplog.records
        if "appears in multiple CONF lists" in r.getMessage()
    ]
    assert len(multi) == 2, (
        "changed multi-CONF kind conflict must produce a second WARN "
        "(B-LOW-1: dedup key includes kinds)"
    )


# ===========================================================================
# BEHAVIORAL — A-H1 humidity handler refresh coverage
# ===========================================================================


def test_handle_humidity_based_fan_control_refreshes_config_first():
    """A-H1 pin test.

    ``handle_humidity_based_fan_control`` runs at
    ``coordinator.py:5034`` OUTSIDE all three automation branches, so
    the master-on tick refresh at ``coordinator.py:4934`` does NOT
    cover the manual-mode + cover-off path. The handler MUST refresh
    its own ``self.config`` at the top, mirroring
    ``handle_occupancy_change`` (``automation.py:922``).

    Anchored via AST parse: neutering the ``self._refresh_config()``
    line inside ``handle_humidity_based_fan_control`` flips this test
    RED — the first executable statement in the handler body would no
    longer be that call, and the assertion fails by name.
    """
    import ast
    automation_src = (PKG / "automation.py").read_text()
    tree = ast.parse(automation_src)
    handler = None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "handle_humidity_based_fan_control"
        ):
            handler = node
            break
    assert handler is not None, (
        "handle_humidity_based_fan_control not found in automation.py"
    )
    # Skip the docstring if present.
    body = list(handler.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    assert body, "handler body empty after docstring strip"
    first = body[0]
    # First executable statement must be ``self._refresh_config()``.
    assert isinstance(first, ast.Expr), (
        "first executable statement should be a bare call expression"
    )
    call = first.value
    assert isinstance(call, ast.Call), "expected a Call node"
    func = call.func
    assert (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
        and func.attr == "_refresh_config"
    ), (
        "handle_humidity_based_fan_control MUST call "
        "self._refresh_config() as its first executable statement "
        "(A-H1) — the manual-mode + cover-off tick has no other "
        "refresh site, so the ~12 humidity keys in "
        "_ROOM_SUPPRESS_KEYS would go stale without this"
    )


def test_substrate_no_diff_fast_path_preserved():
    """INV-B: substrate no-diff fast-path is what makes the suppressed-
    path SIGNAL_ROOM_ENTRY_LIFECYCLE dispatch cheap. If this guard
    disappears, INV-B is falsified. Structural source check — the
    guard is one line at the top of ``refresh_subscriptions``."""
    assert re.search(
        r"if not added and not removed and not reclassified:",
        SUBSTRATE_SRC,
    )

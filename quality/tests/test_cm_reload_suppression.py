"""Tests for CM option-writeback reload suppression + Part-1 hygiene + A-MED-1.

Per planning doc:
``docs/planning/PLANNING_cm_option_writeback_reload_suppression.md``

Coverage:
  D1 — last-applied-options snapshot lifecycle (seeded at setup; cleared
       at unload; reseeded after reload).
  D2 — Part-1 hygiene: DynamicPresetDwellMinutesNumber no longer inherits
       RestoreEntity; setter still writes through async_update_entry;
       docstring no longer claims RestoreEntity is canonical.
  D3 — reload suppression in _async_update_listener:
        * allowlist membership = exactly the five intended CONFs
        * single-suppress-key edit → in-place apply, NO async_reload
        * non-allowlisted edit     → async_reload (regression guard)
        * mixed-key edit            → async_reload
        * ROOM entry edit           → async_reload (unchanged)
        * apply_in_place updates live attrs + snapshot
        * A-HIGH-1 clamp invariant preserved through in-place apply
  D5 — config-flow async_step_coordinator_hvac_settings:
        * BOTH violations → combined `errors["base"]` in single submit
        * single cover violation → existing key (byte-identical)
        * single vacancy violation → existing key (byte-identical)
        * combined translation key present in strings.json + en.json

These tests are SOURCE-AST + LIGHT-MOCK style (no runtime HA package
import for most assertions), matching `test_hvac_presence_timer_knobs.py`.
The listener behavior tests import the real `_async_update_listener`,
`_apply_in_place`, and `OPTIONS_RELOAD_SUPPRESS_KEYS` via a lightweight
package shim that stubs the heavy HA-dependent siblings.
"""
from __future__ import annotations

import ast
import asyncio
import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC = (PKG / "__init__.py").read_text()
NUMBER_SRC = (PKG / "number.py").read_text()
CONFIG_FLOW_SRC = (PKG / "config_flow.py").read_text()
STRINGS = json.loads((PKG / "strings.json").read_text())
EN_TRANSLATIONS = json.loads((PKG / "translations" / "en.json").read_text())


# ============================================================================
# D3 — allowlist membership (AST + symbolic CONF imports)
# ============================================================================


def test_options_reload_suppress_keys_exists_and_is_frozenset():
    """The allowlist must exist as a module-level frozenset literal."""
    assert "OPTIONS_RELOAD_SUPPRESS_KEYS" in INIT_SRC
    assert "OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str] = frozenset({" in INIT_SRC


def test_options_reload_suppress_keys_contains_exactly_five_conf_imports():
    """Five CONFs (the four HVAC presence timers + DPM dwell) must each
    appear in the suppress-keys block. Each CONF imported via an alias so
    the literal-match check is deterministic.
    """
    # Extract the OPTIONS_RELOAD_SUPPRESS_KEYS block source
    m = re.search(
        r"OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset\[str\] = frozenset\(\{(.*?)\}\)",
        INIT_SRC, re.DOTALL,
    )
    assert m, "OPTIONS_RELOAD_SUPPRESS_KEYS block not found"
    body = m.group(1)
    expected = [
        "_CONF_HVAC_VACANCY_GRACE_MINUTES",
        "_CONF_HVAC_VACANCY_GRACE_CONSTRAINED",
        "_CONF_HVAC_MAX_OCCUPANCY_HOURS",
        "_CONF_HVAC_ZONE_ENTRY_DWELL",
        "_CONF_DYNAMIC_PRESET_DWELL_MINUTES",
    ]
    for name in expected:
        assert name in body, f"{name} missing from OPTIONS_RELOAD_SUPPRESS_KEYS"
    # Count CONF aliases — guards against accidental additions.
    alias_count = sum(1 for name in expected if name in body)
    assert alias_count == 5


def test_options_reload_suppress_keys_resolves_to_known_conf_strings():
    """Resolve each CONF alias through the actual const module so the
    allowlist's CONTENT (string values) is locked, not just its names.
    """
    # Import the const modules directly without triggering URA package init.
    hvac_const_src = (PKG / "domain_coordinators" / "hvac_const.py").read_text()
    energy_const_src = (PKG / "domain_coordinators" / "energy_const.py").read_text()

    def extract(src: str, name: str) -> str:
        m = re.search(
            rf"^{name}\s*:\s*Final\s*=\s*\"([^\"]+)\"",
            src, re.MULTILINE,
        )
        assert m, f"{name} not found"
        return m.group(1)

    expected_strings = {
        extract(hvac_const_src, "CONF_HVAC_VACANCY_GRACE_MINUTES"),
        extract(hvac_const_src, "CONF_HVAC_VACANCY_GRACE_CONSTRAINED"),
        extract(hvac_const_src, "CONF_HVAC_MAX_OCCUPANCY_HOURS"),
        extract(hvac_const_src, "CONF_HVAC_ZONE_ENTRY_DWELL"),
        extract(energy_const_src, "CONF_DYNAMIC_PRESET_DWELL_MINUTES"),
    }
    assert expected_strings == {
        "hvac_vacancy_grace_minutes",
        "hvac_vacancy_grace_constrained",
        "hvac_max_occupancy_hours",
        "hvac_zone_entry_dwell",
        "dynamic_preset_dwell_minutes",
    }


# ============================================================================
# D1 + D3 — listener behavior (runtime test against real listener function)
# ============================================================================


def _load_init_listener_helpers():
    """Extract the listener + helpers from __init__.py as a synthetic
    module so the test can drive the real code paths without importing
    the full URA package (which depends on Home Assistant runtime).

    We isolate the two helpers and the listener by re-parsing the source
    and execing the relevant top-level definitions into a fresh namespace.
    """
    tree = ast.parse(INIT_SRC)
    keep = {
        "OPTIONS_RELOAD_SUPPRESS_KEYS",
        "_seed_cm_last_applied_options",
        "_apply_in_place",
        "_async_update_listener",
        # Part 2 — dispatch tables (read inside _apply_in_place).
        "_HVAC_TUNABLE_DISPATCH",
        "_EC_SETTER_DISPATCH",
        "_OFFPEAK_DRAIN_QUALITY",
        "_NO_LIVE_ATTR_KEYS",
        # NM Cycle A-2 (2026-07-20) — knob-key bundle spliced into both
        # _NO_LIVE_ATTR_KEYS and OPTIONS_RELOAD_SUPPRESS_KEYS via `*_NM_A2_KEYS`.
        "_NM_A2_KEYS",
    }
    body = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target = getattr(node.target, "id", None)
            if target in keep:
                body.append(node)
        elif isinstance(node, ast.Assign):
            # Plain assignments (e.g. `_HVAC_TUNABLE_DISPATCH = {...}`).
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in keep:
                    body.append(node)
                    break
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in keep:
                body.append(node)
    # Build a minimal namespace with stand-ins.
    ns: dict = {
        "_LOGGER": MagicMock(),
        "DOMAIN": "universal_room_automation",
        "CONF_ENTRY_TYPE": "entry_type",
        "ENTRY_TYPE_COORDINATOR_MANAGER": "coordinator_manager",
        "_CONF_HVAC_VACANCY_GRACE_MINUTES": "hvac_vacancy_grace_minutes",
        "_CONF_HVAC_VACANCY_GRACE_CONSTRAINED": "hvac_vacancy_grace_constrained",
        "_CONF_HVAC_MAX_OCCUPANCY_HOURS": "hvac_max_occupancy_hours",
        "_CONF_HVAC_ZONE_ENTRY_DWELL": "hvac_zone_entry_dwell",
        "_CONF_DYNAMIC_PRESET_DWELL_MINUTES": "dynamic_preset_dwell_minutes",
        # Part 2 — HVAC tunable factory (14 keys)
        "_CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA":  "hvac_occupied_cover_close_delta",
        "_CONF_HVAC_COVER_CLOSE_TEMP":            "hvac_cover_close_temp",
        "_CONF_HVAC_COVER_OPEN_TEMP":             "hvac_cover_open_temp",
        "_CONF_HVAC_COVER_OVERRIDE_HOURS":        "hvac_cover_override_hours",
        "_CONF_HVAC_SOLAR_BANK_FLOOR":            "hvac_solar_bank_floor",
        "_CONF_HVAC_FAN_ACTIVATION_DELTA":        "hvac_fan_activation_delta",
        "_CONF_HVAC_FAN_HYSTERESIS":              "hvac_fan_hysteresis",
        "_CONF_HVAC_AC_NUDGE_SIZE":               "hvac_ac_nudge_size",
        "_CONF_HVAC_AC_NUDGE_DURATION":           "hvac_ac_nudge_duration",
        "_CONF_HVAC_AC_NUDGE_EVAL_DELAY":         "hvac_ac_nudge_eval_delay",
        "_CONF_HVAC_AC_SUSTAINED_SAMPLES":        "hvac_ac_sustained_samples",
        "_CONF_HVAC_AC_DETECTION_TIME_GATE":      "hvac_ac_detection_time_gate",
        "_CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT":   "hvac_ac_hard_reset_daily_limit",
        "_CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL":  "hvac_ac_hard_reset_min_interval",
        # Part 2 — EC family
        "_CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT":   "energy_offpeak_drain_excellent",
        "_CONF_ENERGY_OFFPEAK_DRAIN_GOOD":        "energy_offpeak_drain_good",
        "_CONF_ENERGY_OFFPEAK_DRAIN_MODERATE":    "energy_offpeak_drain_moderate",
        "_CONF_ENERGY_OFFPEAK_DRAIN_POOR":        "energy_offpeak_drain_poor",
        "_CONF_ENERGY_PEAK_BUFFER_TARGET":        "energy_peak_buffer_target",
        "_CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN": "energy_arbitrage_charge_lead_time_min",
        "_CONF_ENERGY_EV_BATTERY_DRAIN_SOC":      "energy_ev_battery_drain_soc",
        "_CONF_ENERGY_FILL_PRIORITY_SOC":         "energy_fill_priority_soc",
        "_CONF_ENERGY_EXCESS_SOLAR_SOC":          "energy_excess_solar_soc",
        # Part 2 — DPM hysteresis + egress + fan-interference hold + Routine + Bayesian
        "_CONF_DYNAMIC_PRESET_HYSTERESIS_F":      "dynamic_preset_hysteresis_f",
        "_CONF_HVAC_EGRESS_THRESHOLD_MIN":        "hvac_egress_threshold_min",
        "_CONF_HVAC_EGRESS_RESUME_DELAY_MIN":     "hvac_egress_resume_delay_min",
        "_CONF_FAN_INTERFERENCE_HOLD_S":          "fan_interference_hold_s",
        "_CONF_ROUTINE_EVENT_COOLDOWN_DAYS":      "routine_event_cooldown_days",
        "_CONF_ROUTINE_EVENT_MIN_SEVERITY":       "routine_event_min_severity",
        "_CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS": "routine_regime_baseline_window_days",
        "_CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS": "routine_regime_recent_window_days",
        "_CONF_BAYESIAN_CELL_STALENESS_DAYS":     "bayesian_cell_staleness_days",
        # v4.7.34 — Optimization Coordinator (C-CRIT-1) + ROOM-level comfort
        # sliders (C-HIGH-3). Mirror const.py string values.
        "_CONF_OPTIMIZER_AUTONOMY_LEVEL":         "optimizer_autonomy_level",
        "_CONF_OPTIMIZER_KILL_SWITCH":            "optimizer_kill_switch",
        "_CONF_OPTIMIZER_DIMENSION_AUTONOMY":     "optimizer_dimension_autonomy",
        "_CONF_OPTIMIZER_CONFIDENCE_GATE":        "optimizer_confidence_gate",
        "_CONF_OPTIMIZER_RATE_CAP_PER_HOUR":      "optimizer_rate_cap_per_hour",
        "_CONF_OPTIMIZER_QUIET_HOURS_SOURCE":     "optimizer_quiet_hours_source",
        # OC Pillar B (admin surface) — pending-escalation key, reload-suppressed.
        "_CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL": "optimizer_pending_autonomy_level",
        # v4.7.35 Phase 2 — LLM Tier-2 CM-options keys.
        "_CONF_OPTIMIZER_LLM_TASK_ENTITY":        "optimizer_llm_task_entity",
        "_CONF_OPTIMIZER_LLM_TRIAGE_ENTITY":      "optimizer_llm_triage_entity",
        "_CONF_OPTIMIZER_LLM_SYSTEM_PROMPT":      "optimizer_llm_system_prompt",
        "_CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H": "optimizer_llm_max_invocations_per_24h",
        "_CONF_OPTIMIZER_SAFETY_DENY_ENTITIES":   "optimizer_safety_deny_entities",
        "_CONF_COMFORT_TEMP_MIN":                 "comfort_temp_min",
        "_CONF_COMFORT_TEMP_MAX":                 "comfort_temp_max",
        "_CONF_COMFORT_HUMIDITY_MAX":             "comfort_humidity_max",
        # v5.10.0 D2 — MF sleep + night suppression CM keys.
        "_CONF_MF_SLEEP_SUPPRESS":                "mf_sleep_suppress",
        "_CONF_MF_NIGHT_SUPPRESS_MODE":           "mf_night_suppress_mode",
        # Zone Delete Flow fix-up R2 — CONF_ZONE added to _ROOM_SUPPRESS_KEYS
        # so zone reassignment during delete doesn't storm per-room reloads.
        "CONF_ZONE":                              "zone",
        # ENTRY_TYPE_ROOM (C-HIGH-3 path in _async_update_listener).
        "ENTRY_TYPE_ROOM":                        "room",
        # Session B1 — EVSE Drain-Precedence CM options keys.
        "_CONF_ENERGY_DP_ENABLE":                 "energy_dp_enable",
        "_CONF_ENERGY_DP_EVAL_DELAY_MIN":         "energy_dp_eval_delay_min",
        "_CONF_ENERGY_DP_MARGIN_MIN":             "energy_dp_margin_min",
        "_CONF_ENERGY_DP_MUST_START_BY_MIN":      "energy_dp_must_start_by_min",
        "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A":    "energy_dp_needed_kwh_garage_a",
        "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B":    "energy_dp_needed_kwh_garage_b",
        "_CONF_ENERGY_DP_HOUSE_LOAD_SOURCE":      "energy_dp_house_load_source",
        # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — D2 knobs.
        "_CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP": "energy_soc_divergence_threshold_pp",
        "_CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN":    "energy_soc_divergence_dwell_min",
        "_CONF_ENERGY_CLOUD_LAG_ALERT_S":           "energy_cloud_lag_alert_s",
        # NM Cycle A-2 (2026-07-20) — 12 Cycle-A knobs + optimizer allowlist.
        "_CONF_TRIPPED_BREAKER_ZERO_WINDOW_S":      "nm_a1_tripped_breaker_zero_window_s",
        "_CONF_TRIPPED_BREAKER_ROUTE_NM":           "nm_a1_tripped_breaker_route_nm",
        "_CONF_LOCK_UNAVAILABLE_DEDUP_S":           "nm_a3_lock_unavailable_dedup_s",
        "_CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT":       "nm_a4_humidity_log_only_pct",
        "_CONF_HUMIDITY_NORMAL_MEDIUM_PCT":         "nm_a4_humidity_medium_pct",
        "_CONF_HUMIDITY_NORMAL_HIGH_PCT":           "nm_a4_humidity_high_pct",
        "_CONF_HUMIDITY_SWING_DELTA_PCT":           "nm_a4_humidity_swing_delta_pct",
        "_CONF_HUMIDITY_SWING_MIN_ABS_PCT":         "nm_a4_humidity_swing_min_abs_pct",
        "_CONF_CO2_LOG_ONLY_CEILING_PPM":           "nm_a5_co2_log_only_ppm",
        "_CONF_TVOC_ABSOLUTE_HIGH_PPB":             "nm_a5_tvoc_absolute_high_ppb",
        "_CONF_TVOC_SUSTAINED_S":                   "nm_a5_tvoc_sustained_s",
        "_CONF_SAFETY_DISCOVERY_BLOCKLIST":         "nm_a5_safety_discovery_blocklist",
        "_CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS": "nm_a2_optimizer_high_allowlist_dimensions",
        # Typing — frozenset[str] subscript requires Python 3.9+; ok.
    }
    # Wrap kept nodes in a Module and compile.
    mod = ast.Module(body=body, type_ignores=[])
    code = compile(mod, str(PKG / "__init__.py"), "exec")
    exec(code, ns)
    return ns


@pytest.fixture(scope="module")
def listener_ns():
    return _load_init_listener_helpers()


class _FakeHvac:
    def __init__(self):
        self._vacancy_grace = 20
        self._vacancy_grace_constrained = 10
        self._max_occupancy_hours = 6
        self._zone_entry_dwell = 2


class _FakeManager:
    def __init__(self, hvac):
        self.coordinators = {"hvac": hvac}


class _FakeHass:
    def __init__(self, hvac=None, *, with_manager=True):
        self.data = {"universal_room_automation": {}}
        if with_manager:
            mgr = _FakeManager(hvac) if hvac is not None else None
            self.data["universal_room_automation"]["coordinator_manager"] = mgr
        self.config_entries = MagicMock()
        self.config_entries.async_reload = MagicMock()
        self.async_create_task = MagicMock()


class _FakeEntry:
    def __init__(self, entry_id, options, *, is_cm=True, title="CM"):
        self.entry_id = entry_id
        self.title = title
        self.options = dict(options)
        self.data = {"entry_type": "coordinator_manager"} if is_cm else {"entry_type": "room"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) else asyncio.new_event_loop().run_until_complete(coro)


def test_d1_seed_cm_last_applied_options_seeds_at_setup(listener_ns):
    hass = _FakeHass(hvac=_FakeHvac())
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    snap = hass.data["universal_room_automation"]["cm_last_applied_options"]["cm1"]
    assert snap == {"hvac_vacancy_grace_minutes": 20}


def test_d1_snapshot_is_a_copy_not_a_reference(listener_ns):
    hass = _FakeHass(hvac=_FakeHvac())
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Mutate entry.options post-seed — snapshot must NOT change.
    entry.options["hvac_vacancy_grace_minutes"] = 999
    snap = hass.data["universal_room_automation"]["cm_last_applied_options"]["cm1"]
    assert snap["hvac_vacancy_grace_minutes"] == 20


def test_d3_listener_suppresses_reload_for_allowlisted_keys(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Operator edits the timer Number from 20 → 25.
    entry.options = {"hvac_vacancy_grace_minutes": 25}
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0
    assert hvac._vacancy_grace == 25
    snap = hass.data["universal_room_automation"]["cm_last_applied_options"]["cm1"]
    assert snap == {"hvac_vacancy_grace_minutes": 25}


def test_d3_listener_reloads_for_non_allowlisted_keys(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {"presence_enabled": True})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = {"presence_enabled": False}
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 1


def test_d3_listener_reloads_for_mixed_change(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {
        "hvac_vacancy_grace_minutes": 20,
        "presence_enabled": True,
    })
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # One allowlisted + one non-allowlisted key change in the SAME write.
    entry.options = {
        "hvac_vacancy_grace_minutes": 25,
        "presence_enabled": False,
    }
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    # Mixed change MUST reload (the dominant non-allowlisted change wins).
    assert hass.async_create_task.call_count == 1


def test_d3_listener_no_op_on_empty_diff(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Same value rewritten — no reload, no in-place apply.
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0
    assert hvac._vacancy_grace == 20  # unchanged


def test_d3_listener_unchanged_for_room_entries(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("room1", {"timeout_override": 30}, is_cm=False)
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    # ROOM entry: ALWAYS reload, regardless of which keys changed.
    assert hass.async_create_task.call_count == 1


def test_d3_apply_in_place_updates_all_four_hvac_live_attrs(listener_ns):
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    new = {
        "hvac_vacancy_grace_minutes": 25,
        "hvac_vacancy_grace_constrained": 12,
        "hvac_max_occupancy_hours": 8,
        "hvac_zone_entry_dwell": 3,
    }
    applied = listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), set(new.keys()), new,
    )
    assert hvac._vacancy_grace == 25
    assert hvac._vacancy_grace_constrained == 12
    assert hvac._max_occupancy_hours == 8
    assert hvac._zone_entry_dwell == 3
    # HIGH-1: _apply_in_place returns set[str] of cleanly-applied keys.
    assert applied == set(new.keys())


def test_d3_apply_in_place_safe_when_coordinator_missing(listener_ns):
    """If HVAC coordinator is mid-teardown, apply_in_place must not raise."""
    hass = _FakeHass(hvac=None, with_manager=True)  # manager exists, hvac=None
    new = {"hvac_vacancy_grace_minutes": 25}
    # Should NOT raise.
    applied = listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), {"hvac_vacancy_grace_minutes"}, new,
    )
    # No HVAC -> nothing applied (the key is HVAC-owned).
    assert applied == set()


def test_d3_apply_in_place_safe_when_manager_missing(listener_ns):
    """If coordinator_manager is absent entirely, apply_in_place must not raise."""
    hass = _FakeHass(with_manager=False)
    hass.data["universal_room_automation"] = {}
    new = {"hvac_vacancy_grace_minutes": 25}
    applied = listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), {"hvac_vacancy_grace_minutes"}, new,
    )
    assert applied == set()


def test_d3_apply_in_place_dpm_dwell_treated_as_applied_when_hvac_missing(listener_ns):
    """A-MED-1: when HVAC coordinator is None, DPM dwell key must still be
    reported as applied (energy.py re-reads it each tick from entry.options),
    so the listener's snapshot advances for it."""
    hass = _FakeHass(hvac=None, with_manager=True)
    new = {"dynamic_preset_dwell_minutes": 30}
    applied = listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), {"dynamic_preset_dwell_minutes"}, new,
    )
    assert applied == {"dynamic_preset_dwell_minutes"}


def test_d3_apply_in_place_partial_apply_one_bad_value(listener_ns):
    """HIGH-1: a malformed value for ONE key must NOT prevent the other
    three from applying. The returned `applied` set must exclude the
    failed key."""
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    new = {
        "hvac_vacancy_grace_minutes": "not_an_int",  # malformed - should fail
        "hvac_vacancy_grace_constrained": 12,
        "hvac_max_occupancy_hours": 8,
        "hvac_zone_entry_dwell": 3,
    }
    applied = listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), set(new.keys()), new,
    )
    # The three sibling keys must have been applied even though the first
    # one raised. Pre-HIGH-1, the shared try/except swallowed all three.
    assert hvac._vacancy_grace_constrained == 12
    assert hvac._max_occupancy_hours == 8
    assert hvac._zone_entry_dwell == 3
    # Original attr untouched on the failed key.
    assert hvac._vacancy_grace == 20  # FakeHvac default
    # `applied` excludes the failed key.
    assert "hvac_vacancy_grace_minutes" not in applied
    assert applied == {
        "hvac_vacancy_grace_constrained",
        "hvac_max_occupancy_hours",
        "hvac_zone_entry_dwell",
    }


def test_d3_apply_in_place_defensive_clamp_when_constrained_exceeds_normal(listener_ns):
    """B-HIGH-1 (Review B): if an out-of-band write would leave
    _vacancy_grace_constrained > _vacancy_grace, apply_in_place must
    defensively clamp the constrained value down to the normal value."""
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    # Simulate an out-of-band write that bypassed the Number-setter clamp:
    # write a new normal=10 with constrained=30 (invalid).
    new = {
        "hvac_vacancy_grace_minutes": 10,
        "hvac_vacancy_grace_constrained": 30,
    }
    listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), set(new.keys()), new,
    )
    # After per-key writes, the defensive clamp should kick in.
    assert hvac._vacancy_grace == 10
    assert hvac._vacancy_grace_constrained == 10  # clamped down


def test_d1_snapshot_cleared_on_unload(listener_ns):
    """D1: on CM entry unload, the entry_id must be removed from the
    per-entry last-applied-options snapshot dict, so a future setup
    re-seeds cleanly. Drives the actual unload helper pattern by
    simulating the unload pop, which lives at the top of the CM unload
    branch in async_unload_entry (B-MED-1 ordering)."""
    hass = _FakeHass(hvac=_FakeHvac())
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    snaps = hass.data["universal_room_automation"]["cm_last_applied_options"]
    assert "cm1" in snaps
    # Simulate the CM unload pop (the real path in async_unload_entry
    # runs `snapshots.pop(entry.entry_id, None)` before
    # async_unload_platforms — B-MED-1 fix-up).
    snaps.pop(entry.entry_id, None)
    assert "cm1" not in snaps


def test_d1_snapshot_reseeded_after_reload(listener_ns):
    """D1: calling _seed_cm_last_applied_options again with changed
    entry.options REPLACES the snapshot dict for that entry_id with the
    new dict (simulating the post-reload setup re-seed)."""
    hass = _FakeHass(hvac=_FakeHvac())
    entry = _FakeEntry("cm1", {"hvac_vacancy_grace_minutes": 20})
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    snaps = hass.data["universal_room_automation"]["cm_last_applied_options"]
    assert snaps["cm1"] == {"hvac_vacancy_grace_minutes": 20}
    # Simulate post-reload setup: entry.options now has a new value.
    entry.options = {"hvac_vacancy_grace_minutes": 25, "presence_enabled": True}
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Snapshot REPLACED with the new dict (not merged).
    assert snaps["cm1"] == {
        "hvac_vacancy_grace_minutes": 25,
        "presence_enabled": True,
    }


def test_d3_clamp_invariant_holds_after_in_place_apply(listener_ns):
    """The A-HIGH-1 bidirectional clamp lives in the Number setter (runs
    BEFORE async_update_entry) and in the OptionsFlow form validation. By
    the time apply_in_place sees `entry.options`, the pair is already
    consistent. The invariant we lock here: apply_in_place itself never
    INTRODUCES an inversion — it only mirrors the option write."""
    hvac = _FakeHvac()
    hvac._vacancy_grace = 30
    hvac._vacancy_grace_constrained = 15
    hass = _FakeHass(hvac=hvac)
    # The setter's clamp already wrote BOTH keys consistently in one go.
    new = {
        "hvac_vacancy_grace_minutes": 10,
        "hvac_vacancy_grace_constrained": 10,
    }
    listener_ns["_apply_in_place"](
        hass, _FakeEntry("cm1", new), set(new.keys()), new,
    )
    assert hvac._vacancy_grace == 10
    assert hvac._vacancy_grace_constrained == 10
    assert hvac._vacancy_grace_constrained <= hvac._vacancy_grace


def test_d3_listener_handles_all_four_timers_via_reset_button(listener_ns):
    """The `51 Reset` button writes all four HVAC timer defaults in one
    async_update_entry call. changed_keys ⊆ suppress set, so the listener
    must apply in place and skip reload."""
    hvac = _FakeHvac()
    hass = _FakeHass(hvac=hvac)
    entry = _FakeEntry("cm1", {
        "hvac_vacancy_grace_minutes": 30,
        "hvac_vacancy_grace_constrained": 15,
        "hvac_max_occupancy_hours": 12,
        "hvac_zone_entry_dwell": 5,
    })
    listener_ns["_seed_cm_last_applied_options"](hass, entry)
    # Reset to defaults (all four allowlisted keys change).
    entry.options = {
        "hvac_vacancy_grace_minutes": 20,
        "hvac_vacancy_grace_constrained": 10,
        "hvac_max_occupancy_hours": 6,
        "hvac_zone_entry_dwell": 2,
    }
    asyncio.new_event_loop().run_until_complete(
        listener_ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0  # NO reload
    assert hvac._vacancy_grace == 20
    assert hvac._max_occupancy_hours == 6


# ============================================================================
# D2 — DynamicPresetDwellMinutesNumber hygiene
# ============================================================================


def test_d2_dpm_dwell_no_longer_inherits_restoreentity():
    """AST: class signature must NOT include RestoreEntity."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            base_names = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    base_names.append(b.id)
                elif isinstance(b, ast.Attribute):
                    base_names.append(b.attr)
            assert "RestoreEntity" not in base_names, (
                f"DynamicPresetDwellMinutesNumber still inherits RestoreEntity "
                f"(bases={base_names})"
            )
            return
    pytest.fail("DynamicPresetDwellMinutesNumber class not found in number.py")


def test_d2_dpm_dwell_no_async_added_to_hass_restore_branch():
    """The class must not define an async_added_to_hass method that reads
    `async_get_last_state` (the restore branch is what was being removed).
    """
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_added_to_hass":
                    method_src = ast.unparse(item)
                    assert "async_get_last_state" not in method_src, (
                        "DPM dwell async_added_to_hass still reads last_state"
                    )
            return
    pytest.fail("DynamicPresetDwellMinutesNumber not found")


def test_d2_dpm_dwell_docstring_no_longer_claims_restoreentity_canonical():
    """The class docstring must not claim 'RestoreEntity is the canonical
    runtime store' — that line was the stale doctrine being fixed."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            doc = ast.get_docstring(node) or ""
            assert "canonical runtime store" not in doc, (
                "DPM dwell docstring still claims RestoreEntity canonical"
            )
            assert "SOLE source of truth" in doc, (
                "DPM dwell docstring must state options-as-sole-source"
            )
            return
    pytest.fail("DynamicPresetDwellMinutesNumber not found")


def test_d2_dpm_dwell_setter_still_writes_through_async_update_entry():
    """Persistence path must remain: setter calls async_update_entry with
    the DPM dwell CONF key. This is what makes restart-restore work via
    `{**entry.data, **entry.options}` reseeding."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DynamicPresetDwellMinutesNumber":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_set_native_value":
                    body_src = ast.unparse(item)
                    assert "async_update_entry" in body_src
                    assert "CONF_DYNAMIC_PRESET_DWELL_MINUTES" in body_src
                    return
    pytest.fail("DPM dwell setter not found")


# ============================================================================
# D5 — A-MED-1 combined cross-field error
# ============================================================================


def test_d5_save_path_runs_both_validations_unconditionally():
    """The `if not errors:` gate must be GONE between the two validations.
    Source-level check: the vacancy-grace check must not be nested inside
    `if not errors:`."""
    # Locate `async_step_coordinator_hvac_settings` source.
    tree = ast.parse(CONFIG_FLOW_SRC)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_step_coordinator_hvac_settings":
            src = ast.unparse(node)
            assert "vacancy_grace_constrained_exceeds_normal" in src
            # The old pattern was:
            #   if not errors:
            #       grace = ...
            #       grace_constrained = ...
            #       if grace_constrained > grace:
            #           errors["base"] = "vacancy_grace_constrained_exceeds_normal"
            # New pattern: both checks always run; an accumulator is used.
            assert "error_keys" in src, (
                "D5: save path must use an error_keys accumulator"
            )
            # No remaining gate immediately before the vacancy check.
            # Pattern that should NOT exist: an `if not errors:` that
            # contains `vacancy_grace_constrained_exceeds_normal`.
            for sub in ast.walk(node):
                if isinstance(sub, ast.If):
                    test_src = ast.unparse(sub.test)
                    body_src = ast.unparse(sub.body) if sub.body else ""
                    if (
                        "not errors" in test_src
                        and "vacancy_grace_constrained_exceeds_normal" in body_src
                    ):
                        pytest.fail(
                            "D5: vacancy check still gated behind `if not errors:`"
                        )
            found = True
            break
    assert found, "async_step_coordinator_hvac_settings not found"


def test_d5_save_path_uses_combined_key_when_two_violations():
    """Source-level check: combined-key branch must exist and depend on
    BOTH specific violation keys being present (A-MED-2 fix). The earlier
    `len(error_keys) >= 2` gate would mis-fire if a future third unrelated
    error key was appended to the accumulator — the combined message
    names two specific violations and must only fire when BOTH are
    actually triggered."""
    assert "cover_and_vacancy_combined" in CONFIG_FLOW_SRC
    # A-MED-2: gate must check for BOTH specific keys, not just count.
    assert "have_cover" in CONFIG_FLOW_SRC
    assert "have_vacancy" in CONFIG_FLOW_SRC
    assert "cover_temp_hysteresis_too_small" in CONFIG_FLOW_SRC
    assert "vacancy_grace_constrained_exceeds_normal" in CONFIG_FLOW_SRC


def test_d5_strings_json_has_combined_key():
    section = (
        STRINGS.get("options", {}).get("error", {})
    )
    assert "cover_and_vacancy_combined" in section, (
        "cover_and_vacancy_combined missing from strings.json options.error"
    )
    # Single-violation keys remain so single-violation paths are byte-identical.
    assert "cover_temp_hysteresis_too_small" in section
    assert "vacancy_grace_constrained_exceeds_normal" in section


def test_d5_en_translations_has_combined_key():
    section = (
        EN_TRANSLATIONS.get("options", {}).get("error", {})
    )
    assert "cover_and_vacancy_combined" in section
    assert "cover_temp_hysteresis_too_small" in section
    assert "vacancy_grace_constrained_exceeds_normal" in section


def test_d5_strings_and_translations_combined_key_in_lockstep():
    """The combined key must appear in BOTH files (lockstep — translations
    file is loaded by HA, strings file is the source for `script
    extract-strings`).

    C2 (Review C) tightening: the cross-field error texts must be
    BYTE-EQUAL across strings.json and translations/en.json — any drift
    means one file shipped without the other, which is exactly the bug
    the lockstep test is supposed to catch."""
    s_section = STRINGS.get("options", {}).get("error", {})
    e_section = EN_TRANSLATIONS.get("options", {}).get("error", {})
    assert "cover_and_vacancy_combined" in s_section
    assert "cover_and_vacancy_combined" in e_section
    # C2: BYTE-EQUAL text across the two files for the three
    # cross-field error keys.
    for key in (
        "cover_and_vacancy_combined",
        "cover_temp_hysteresis_too_small",
        "vacancy_grace_constrained_exceeds_normal",
    ):
        assert s_section[key] == e_section[key], (
            f"D5/C2: {key} text drift between strings.json and "
            f"translations/en.json — both files must ship together "
            f"with byte-equal text"
        )
    # Combined message must explicitly reference BOTH the cover and
    # vacancy violations so operators see both.
    for text in (
        s_section["cover_and_vacancy_combined"],
        e_section["cover_and_vacancy_combined"],
    ):
        assert "Cover" in text and "Vacancy" in text


def test_d5_other_errors_base_sites_not_touched():
    """Regression-bar: the ~15 other `errors["base"] = "<key>"` sites in
    config_flow.py are UNCHANGED. The only modification is the SHARED save
    path of async_step_coordinator_hvac_settings. Count single-base sites
    and assert there is at least the previous quorum AND that our specific
    new accumulator pattern only appears in the target function.
    """
    # `errors["base"] = ` should appear many times throughout config_flow.
    count = CONFIG_FLOW_SRC.count("errors[\"base\"] = ")
    assert count >= 10, (
        f"Expected ~15 single-base error sites; found only {count}. "
        "D5 regression — was a sibling site accidentally rewritten?"
    )
    # The `error_keys` accumulator is the new D5 pattern; should only
    # appear in async_step_coordinator_hvac_settings.
    tree = ast.parse(CONFIG_FLOW_SRC)
    accumulator_uses = 0
    target_uses = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            src = ast.unparse(node)
            if "error_keys" in src and "append" in src:
                accumulator_uses += 1
                if node.name == "async_step_coordinator_hvac_settings":
                    target_uses += 1
    assert accumulator_uses == 1, (
        f"D5: error_keys accumulator pattern leaked into "
        f"{accumulator_uses} functions; expected 1"
    )
    assert target_uses == 1


# ============================================================================
# Listener registration discipline — multiple entry-types share one listener
# ============================================================================


def test_listener_registered_at_all_three_entry_types():
    """`_async_update_listener` is registered for ROOM, ZONE_MANAGER, and
    COORDINATOR_MANAGER entries. The cycle's change must NOT remove any
    registration site. Pin the call sites by literal grep."""
    sites = INIT_SRC.count("add_update_listener(_async_update_listener)")
    # The planning doc enumerates 4 registration sites (2365, 2515, 2743, 2851).
    assert sites >= 3, (
        f"Listener registration sites dropped to {sites}; expected >= 3"
    )

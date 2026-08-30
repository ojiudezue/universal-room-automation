"""Tests for Part 2 — EC + HVAC Options-Writeback Retrofit.

Per planning doc:
``docs/planning/PLANNING_part2_ec_hc_options_writeback_retrofit.md``

Coverage (suite-level + per-deliverable):
  D1 — EC Number family (drop RestoreEntity + add writeback + dispatch)
  D2 — Routine Number base-class retrofit (drop RestoreEntity + writeback)
  D3 — _HVACTunableNumber factory (drop RestoreEntity + add writeback +
       dispatch table; 14 keys covered)
  D4 — _HVACZoneKwhThresholdNumber: SPLIT OUT, asserted backlog memo filed.
  D5 — DPM hysteresis + egress pause/resume + fan-interference hold
  D6 (suite-level):
        * test_no_restoreentity_left_in_number_py (excluding D4 split-out)
        * test_options_reload_suppress_keys_membership (exact set lock)
        * test_apply_in_place_dispatch_coverage (1:1 with allowlist)
        * test_part2_retrofit_does_not_break_v4_7_25_keys (regression)

Style: SOURCE-AST + LIGHT-MOCK, matching test_cm_reload_suppression.py.
The dispatch-coverage and listener-behavior tests reuse the same AST
extractor pattern so they exercise the REAL production dispatch tables.
"""
from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC = (PKG / "__init__.py").read_text()
NUMBER_SRC = (PKG / "number.py").read_text()
HVAC_CONST_SRC = (PKG / "domain_coordinators" / "hvac_const.py").read_text()
ENERGY_CONST_SRC = (PKG / "domain_coordinators" / "energy_const.py").read_text()
CONST_SRC = (PKG / "const.py").read_text()


# ---------------------------------------------------------------------------
# Shared expected-allowlist (string values resolved from production CONFs)
# ---------------------------------------------------------------------------

def _extract_conf(src: str, name: str) -> str:
    """Pull `NAME: Final = "value"` from a const module source."""
    m = re.search(
        rf"^{name}\s*:\s*Final\s*=\s*\(?\s*\"([^\"]+)\"",
        src, re.MULTILINE,
    )
    assert m, f"{name} not found"
    return m.group(1)


EXPECTED_SUPPRESS_KEYS: set[str] = {
    # v4.7.26 Cycle 1
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_VACANCY_GRACE_MINUTES"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_VACANCY_GRACE_CONSTRAINED"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_MAX_OCCUPANCY_HOURS"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_ZONE_ENTRY_DWELL"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_DYNAMIC_PRESET_DWELL_MINUTES"),
    # D1 — EC family
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_OFFPEAK_DRAIN_GOOD"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_OFFPEAK_DRAIN_MODERATE"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_OFFPEAK_DRAIN_POOR"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_PEAK_BUFFER_TARGET"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_EV_BATTERY_DRAIN_SOC"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_FILL_PRIORITY_SOC"),
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_EXCESS_SOLAR_SOC"),
    # Blind-window guard cycle — D4 Emporia-mains backup export sensor.
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_MAINS_EXPORT_ENTITY"),
    # LKG wave 1 D2 — solar production upper-envelope nameplate.
    _extract_conf(ENERGY_CONST_SRC, "CONF_ENERGY_SOLAR_NAMEPLATE_W"),
    "bayesian_cell_staleness_days",
    # D2 — Routine family
    _extract_conf(CONST_SRC, "CONF_ROUTINE_EVENT_COOLDOWN_DAYS"),
    _extract_conf(CONST_SRC, "CONF_ROUTINE_EVENT_MIN_SEVERITY"),
    _extract_conf(CONST_SRC, "CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS"),
    _extract_conf(CONST_SRC, "CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS"),
    # D3 — HVAC tunable factory (14 keys)
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_COVER_CLOSE_TEMP"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_COVER_OPEN_TEMP"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_COVER_OVERRIDE_HOURS"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_SOLAR_BANK_FLOOR"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_FAN_ACTIVATION_DELTA"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_FAN_HYSTERESIS"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_AC_NUDGE_SIZE"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_AC_NUDGE_DURATION"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_AC_NUDGE_EVAL_DELAY"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_AC_SUSTAINED_SAMPLES"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_AC_DETECTION_TIME_GATE"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL"),
    # D5 — DPM hysteresis + egress + fan-interference
    _extract_conf(ENERGY_CONST_SRC, "CONF_DYNAMIC_PRESET_HYSTERESIS_F"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_EGRESS_THRESHOLD_MIN"),
    _extract_conf(HVAC_CONST_SRC, "CONF_HVAC_EGRESS_RESUME_DELAY_MIN"),
    _extract_conf(CONST_SRC, "CONF_FAN_INTERFERENCE_HOLD_S"),
    # v4.7.34 — Optimization Coordinator (C-CRIT-1). Six CM-level keys
    # whose changes must NOT tear down the CM entry; the coordinator
    # reads entry.options fresh every cycle.
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_AUTONOMY_LEVEL"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_KILL_SWITCH"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_DIMENSION_AUTONOMY"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_CONFIDENCE_GATE"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_RATE_CAP_PER_HOUR"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_QUIET_HOURS_SOURCE"),
    # v4.7.35 Phase 2 — LLM Tier-2 CM-options keys.
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_LLM_TASK_ENTITY"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_LLM_TRIAGE_ENTITY"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_LLM_SYSTEM_PROMPT"),
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H"),
    # v4.7.35 fix-up (B-B2) — safety/security deny-list.
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_SAFETY_DENY_ENTITIES"),
    # OC Pillar B (admin surface) — pending-escalation key. Editing it must
    # NOT tear down the CM entry (the confirm/cancel buttons read it fresh).
    _extract_conf(CONST_SRC, "CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL"),
    # v5.10.0 D2 — Music Following sleep + night suppression push
    # through MusicFollowing.update_gate_config() without a CM reload.
    _extract_conf(CONST_SRC, "CONF_MF_SLEEP_SUPPRESS"),
    _extract_conf(CONST_SRC, "CONF_MF_NIGHT_SUPPRESS_MODE"),
    # Session B1 — EVSE Drain-Precedence entity-owned CM options keys
    # (Switch: enable; Numbers: eval_delay/margin/must_start_by/needed_kwh_a/b;
    # Select: house_load_source). Edits push through EC setters without
    # a full CM reload. String values live in energy_const.py.
    "energy_dp_enable",
    "energy_dp_eval_delay_min",
    "energy_dp_margin_min",
    "energy_dp_must_start_by_min",
    "energy_dp_needed_kwh_garage_a",
    "energy_dp_needed_kwh_garage_b",
    "energy_dp_house_load_source",
    # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — D2 knobs.
    "energy_soc_divergence_threshold_pp",
    "energy_soc_divergence_dwell_min",
    "energy_cloud_lag_alert_s",
    # NM Cycle A-2 (2026-07-20) — 12 Cycle-A knobs + optimizer allowlist.
    "nm_a1_tripped_breaker_zero_window_s",
    "nm_a1_tripped_breaker_route_nm",
    "nm_a3_lock_unavailable_dedup_s",
    "nm_a4_humidity_log_only_pct",
    "nm_a4_humidity_medium_pct",
    "nm_a4_humidity_high_pct",
    "nm_a4_humidity_swing_delta_pct",
    "nm_a4_humidity_swing_min_abs_pct",
    "nm_a5_co2_log_only_ppm",
    "nm_a5_tvoc_absolute_high_ppb",
    "nm_a5_tvoc_sustained_s",
    "nm_a5_safety_discovery_blocklist",
    "nm_a2_optimizer_high_allowlist_dimensions",
    # NM Cycle B fix-up (2026-07-20, B-B1): dry-run + token-bucket keys.
    _extract_conf(CONST_SRC, "CONF_NM_DRY_RUN"),
    _extract_conf(CONST_SRC, "CONF_NM_BUCKET_CAPACITY"),
    _extract_conf(CONST_SRC, "CONF_NM_BUCKET_REFILL_PER_MIN"),
    # NM Cycle C (2026-07-20): per-recipient matrix + DND-bypass +
    # mute-shortcut CONF keys. All 4 belong to `_NM_C_KEYS` which is
    # splatted into both `_NO_LIVE_ATTR_KEYS` and
    # `OPTIONS_RELOAD_SUPPRESS_KEYS`.
    _extract_conf(CONST_SRC, "CONF_NM_PERSON_ROUTING_MATRIX"),
    _extract_conf(CONST_SRC, "CONF_NM_PERSON_HAZARD_OVERRIDES"),
    _extract_conf(CONST_SRC, "CONF_NM_PERSON_DND_BYPASS_SEVERITIES"),
    _extract_conf(CONST_SRC, "CONF_NM_MUTE_DEFAULT_DURATION_MINUTES"),
    # NM Cycle C-2 (2026-07-22, D2): additive-only life-safety extras.
    _extract_conf(CONST_SRC, "CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS"),
    # Arrester operator-immunity cycle (2026-08-06): AC-ramp master
    # option-persistence key. Added to OPTIONS_RELOAD_SUPPRESS_KEYS to
    # prevent write-through reload loop; the arrester seeds from the
    # option at init so a config-entry reload doesn't reset the master
    # to DEFAULT=False (operator-reported regression 2026-08-06).
    "hvac_ac_ramp_master_enabled",
    # Arrester operator-immunity fix-up (2026-08-06): live-tunable
    # immune-person list; write-through calls set_immune_persons().
    "hvac_arrester_immune_persons",
    # Temp Arrester Override marker (B-M2): switch write-through key.
    "hvac_temp_arrester_override_was_active",
    # STUCK-SENSOR-1 B-MED-2 fix-up (2026-08-13): both stuck-signal knobs
    # added to _NM_A2_KEYS which is splatted into OPTIONS_RELOAD_SUPPRESS_KEYS.
    "stuck_signal_nm_enabled",
    "stuck_sensor_exclusion_enabled",
    # STEP chatter cycle (2026-08-19, v5.85.0) — D2 fix-up added the two
    # safety-knob overrides and D7 added the operational mode. These were
    # added as DIRECT literals in OPTIONS_RELOAD_SUPPRESS_KEYS rather than
    # flowing through _HVAC_TUNABLE_DISPATCH, so unlike dispatch-derived
    # keys they do NOT self-track and this expectation had to be updated
    # by hand. That cycle grew the allowlist and left the guard behind;
    # the guard did its job and nobody read it for four days. -> 92
    "chatter_burst_k",
    "chatter_t_floor_s",
    "chatter_mode",
}


# C-MED-2 fix-up (2026-07-20): self-check every hand-typed string literal in
# EXPECTED_SUPPRESS_KEYS against the const source of truth. If a real CONF is
# renamed and its literal drifts, this would previously stay tautologically
# green because the same hand-typed value was also used in `_apply_in_place`
# fake dispatch. Now a rename fails this module import with a diagnostic.
def _verify_hand_typed_conf_literals() -> None:
    _pat = re.compile(
        r"^(CONF_[A-Z0-9_]+)\s*(?::\s*Final(?:\[[^\]]+\])?)?\s*=\s*\(?\s*\"([^\"]+)\"",
        re.MULTILINE,
    )
    canonical: dict[str, str] = {}
    for text in (CONST_SRC, HVAC_CONST_SRC, ENERGY_CONST_SRC):
        for m in _pat.finditer(text):
            canonical.setdefault(m.group(1), m.group(2))
    hand_typed_values = {
        # 7 EVSE Drain-Precedence keys.
        "energy_dp_enable": "CONF_ENERGY_DP_ENABLE",
        "energy_dp_eval_delay_min": "CONF_ENERGY_DP_EVAL_DELAY_MIN",
        "energy_dp_margin_min": "CONF_ENERGY_DP_MARGIN_MIN",
        "energy_dp_must_start_by_min": "CONF_ENERGY_DP_MUST_START_BY_MIN",
        "energy_dp_needed_kwh_garage_a": "CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A",
        "energy_dp_needed_kwh_garage_b": "CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B",
        "energy_dp_house_load_source": "CONF_ENERGY_DP_HOUSE_LOAD_SOURCE",
        # v5.21.0 D2 knobs.
        "energy_soc_divergence_threshold_pp": "CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP",
        "energy_soc_divergence_dwell_min": "CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN",
        "energy_cloud_lag_alert_s": "CONF_ENERGY_CLOUD_LAG_ALERT_S",
        # Bayesian.
        "bayesian_cell_staleness_days": "CONF_BAYESIAN_CELL_STALENESS_DAYS",
        # NM Cycle A-2 (12 knobs + optimizer allowlist).
        "nm_a1_tripped_breaker_zero_window_s": "CONF_TRIPPED_BREAKER_ZERO_WINDOW_S",
        "nm_a1_tripped_breaker_route_nm": "CONF_TRIPPED_BREAKER_ROUTE_NM",
        "nm_a3_lock_unavailable_dedup_s": "CONF_LOCK_UNAVAILABLE_DEDUP_S",
        "nm_a4_humidity_log_only_pct": "CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT",
        "nm_a4_humidity_medium_pct": "CONF_HUMIDITY_NORMAL_MEDIUM_PCT",
        "nm_a4_humidity_high_pct": "CONF_HUMIDITY_NORMAL_HIGH_PCT",
        "nm_a4_humidity_swing_delta_pct": "CONF_HUMIDITY_SWING_DELTA_PCT",
        "nm_a4_humidity_swing_min_abs_pct": "CONF_HUMIDITY_SWING_MIN_ABS_PCT",
        "nm_a5_co2_log_only_ppm": "CONF_CO2_LOG_ONLY_CEILING_PPM",
        "nm_a5_tvoc_absolute_high_ppb": "CONF_TVOC_ABSOLUTE_HIGH_PPB",
        "nm_a5_tvoc_sustained_s": "CONF_TVOC_SUSTAINED_S",
        "nm_a5_safety_discovery_blocklist": "CONF_SAFETY_DISCOVERY_BLOCKLIST",
        "nm_a2_optimizer_high_allowlist_dimensions":
            "CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS",
        # STUCK-SENSOR-1 B-MED-2 fix-up (2026-08-13).
        "stuck_signal_nm_enabled": "CONF_STUCK_SIGNAL_NM_ENABLED",
        "stuck_sensor_exclusion_enabled": "CONF_STUCK_SENSOR_EXCLUSION_ENABLED",
    }
    mismatches: list[str] = []
    for hand_value, conf_name in hand_typed_values.items():
        if conf_name not in canonical:
            mismatches.append(
                f"{conf_name}: not found in any const source (rename?)"
            )
            continue
        if canonical[conf_name] != hand_value:
            mismatches.append(
                f"{conf_name}: hand={hand_value!r} vs const={canonical[conf_name]!r}"
            )
    assert not mismatches, (
        "C-MED-2: hand-typed conf-key literals drifted from const source of "
        "truth:\n  " + "\n  ".join(mismatches)
    )


_verify_hand_typed_conf_literals()


# ---------------------------------------------------------------------------
# D6 suite-level — allowlist membership + dispatch coverage
# ---------------------------------------------------------------------------


def _extract_allowlist_block() -> str:
    m = re.search(
        r"OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset\[str\] = frozenset\(\{(.*?)^\}\)",
        INIT_SRC, re.DOTALL | re.MULTILINE,
    )
    assert m, "OPTIONS_RELOAD_SUPPRESS_KEYS not found"
    return m.group(1)


def test_options_reload_suppress_keys_membership_exact():
    """The allowlist must contain EXACTLY the documented set of CONFs
    (Cycle 1's five + this cycle's additions). Locks against silent
    drift in either direction."""
    body = _extract_allowlist_block()
    # Each expected CONF appears as a `_CONF_*` alias name in the block
    # OR via the splat `*_HVAC_TUNABLE_DISPATCH.keys()` (14 HVAC tunables).
    # Resolve the alias names → strings and assert set equality.
    ns = _load_init_dispatch_namespace()
    actual = ns["OPTIONS_RELOAD_SUPPRESS_KEYS"]
    assert set(actual) == EXPECTED_SUPPRESS_KEYS, (
        f"Allowlist drift. Missing: "
        f"{EXPECTED_SUPPRESS_KEYS - set(actual)}; "
        f"Extra: {set(actual) - EXPECTED_SUPPRESS_KEYS}"
    )


def test_options_reload_suppress_keys_count_matches_part2_scope():
    """Headline number: Cycle 1's 5 + 10 EC/Bayesian + 4 Routine +
    14 HVAC tunables + 4 D5 + 6 v4.7.34 Optimizer + 4 v4.7.35 LLM +
    1 v4.7.35 fix-up (safety deny-list) + 1 OC Pillar B
    (pending-escalation) + 2 v5.10.0 D2 (MF sleep + night)
    + 7 Session B1 (EVSE drain-precedence: 1 Switch + 5 Numbers + 1 Select)
    = 58 keys."""
    ns = _load_init_dispatch_namespace()
    # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — +3 D2 knobs
    # promoted to rung-2.
    # NM Cycle A-2 (2026-07-20) — +13 A knobs (12 Cycle-A + 1 optimizer allowlist).
    # NM Cycle B fix-up (2026-07-20, B-B1) — +3 keys (dry-run + capacity + refill).
    # NM Cycle C (2026-07-20) — +4 keys (routing matrix, hazard overrides,
    # DND-bypass severities, mute default duration).
    # +1 CONF_ENERGY_MAINS_EXPORT_ENTITY (blind-window guard D4)
    # +1 CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS (NM C-2 D2)
    # (both cycles merged 2026-07-23 -> combined count 83)
    # +1 CONF_ENERGY_SOLAR_NAMEPLATE_W (LKG wave 1 D2, 2026-07-24) -> 84
    # +1 CONF_HVAC_AC_RAMP_MASTER_ENABLED (Arrester operator-immunity
    #    cycle 2026-08-06: reload-safe persistence for the ramp master) -> 85
    # +1 CONF_HVAC_ARRESTER_IMMUNE_PERSONS (fix-up 2026-08-06: live-tunable
    #    immune-person list via set_immune_persons in _apply_in_place) -> 86
    # +1 hvac_temp_arrester_override_was_active (fix-up 2026-08-06:
    #    marker option so an unrelated reload doesn't silently drop the
    #    operator's engagement without a signal) -> 87
    # +2 STUCK-SENSOR-1 B-MED-2 fix-up (2026-08-13): stuck_signal_nm_enabled
    #    + stuck_sensor_exclusion_enabled added to _NM_A2_KEYS -> 89
    # +3 STEP chatter cycle (2026-08-19, v5.85.0): chatter_burst_k +
    #    chatter_t_floor_s (D2 fix-up safety-knob overrides) + chatter_mode
    #    (D7 operational mode), added as DIRECT literals -> 92
    # NOTE: the v5.89.0 AC-ramp knobs are NOT counted here — they enter via
    #    `*_HVAC_TUNABLE_DISPATCH.keys()`, so they appear on BOTH sides of
    #    the membership comparison and self-track. Only direct literals need
    #    a manual bump. That distinction is why this ledger stayed correct
    #    through v5.89.0 but broke on v5.85.0.
    # +1 CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR (OFFPEAK-DRAIN-VERYPOOR-SLIDER-1,
    #    2026-08-28): 5th operator-tunable off-peak drain slider -> 93
    assert len(ns["OPTIONS_RELOAD_SUPPRESS_KEYS"]) == 93


# ---------------------------------------------------------------------------
# D6 suite-level — dispatch coverage (1:1 with allowlist)
# ---------------------------------------------------------------------------


def _load_init_dispatch_namespace() -> dict:
    """Exec the dispatch tables + apply-in-place + listener from __init__.py
    into a clean namespace. Lighter-weight than the full module import path
    (which depends on HA runtime)."""
    tree = ast.parse(INIT_SRC)
    keep_names = {
        "OPTIONS_RELOAD_SUPPRESS_KEYS",
        "_HVAC_TUNABLE_DISPATCH",
        "_EC_SETTER_DISPATCH",
        "_OFFPEAK_DRAIN_QUALITY",
        "_NO_LIVE_ATTR_KEYS",
        # NM Cycle A-2 (2026-07-20) — knob-key bundle spliced into both
        # _NO_LIVE_ATTR_KEYS and OPTIONS_RELOAD_SUPPRESS_KEYS via `*_NM_A2_KEYS`.
        "_NM_A2_KEYS",
        # NM Cycle C (2026-07-20) — matrix/DND-bypass/mute-duration
        # bundle spliced into both _NO_LIVE_ATTR_KEYS and
        # OPTIONS_RELOAD_SUPPRESS_KEYS via `*_NM_C_KEYS`.
        "_NM_C_KEYS",
        # F16 (2026-08-22, v5.89.0): side table mapping conf keys to the
        # coordinator setter that owns each tunable. _hvac_tunable_apply
        # reads it, so slicing that helper requires this dict too.
        "_HVAC_TUNABLE_SETTER_METHOD",
    }
    keep_funcs = {
        "_seed_cm_last_applied_options",
        "_apply_in_place",
        "_async_update_listener",
        # F16 (2026-08-22, v5.89.0): _apply_in_place now routes tunables
        # through this helper so the coordinator setters' range guards
        # actually run. Slicing _apply_in_place without it leaves a free
        # Name load and the guard raises.
        "_hvac_tunable_apply",
    }
    body = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            t = getattr(node.target, "id", None)
            if t in keep_names:
                body.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in keep_names:
                    body.append(node)
                    break
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in keep_funcs:
                body.append(node)
    ns: dict = {
        "_LOGGER": MagicMock(),
        "DOMAIN": "universal_room_automation",
        "CONF_ENTRY_TYPE": "entry_type",
        "ENTRY_TYPE_COORDINATOR_MANAGER": "coordinator_manager",
        # RELOAD-WATCHDOG-HAZARD (2026-08-15): listener now has an
        # ENTRY_TYPE_INTEGRATION branch — inject the sentinel + the v1
        # allowlisted key so the sliced module compiles.
        "ENTRY_TYPE_INTEGRATION": "integration",
        "CONF_CAMERA_PERSON_ENTITIES": "camera_person_entities",
        # STEP D2/D7 (2026-08-19, v5.85.0): these three are ALIASED IMPORTS
        # (`CONF_X as _CONF_X`), not module-level assignments, so keep_names
        # — which only matches ast.Assign / ast.AnnAssign — structurally
        # cannot pick them up. They must be injected as namespace stubs.
        # Values mirror const.py:3859/3860/3877 exactly.
        "_CONF_CHATTER_BURST_K": "chatter_burst_k",
        "_CONF_CHATTER_T_FLOOR_S": "chatter_t_floor_s",
        "_CONF_CHATTER_MODE": "chatter_mode",
        # AC-RAMP-PIPELINE-HARDENING-1 A2 (2026-08-22, v5.89.0): the eight
        # AC-ramp knobs joined _HVAC_TUNABLE_DISPATCH so they seed from CM
        # options at init. Same aliased-import shape as the chatter three —
        # keep_names cannot see them. Values mirror hvac_const.py exactly.
        "_CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT": "hvac_ac_soft_nudge_daily_limit",
        "_CONF_HVAC_AC_RESET_DAY_BUDGET": "hvac_ac_reset_day_budget",
        "_CONF_HVAC_AC_RESET_NIGHT_BUDGET": "hvac_ac_reset_night_budget",
        "_CONF_HVAC_AC_RESET_OFF_DURATION": "hvac_ac_reset_off_duration",
        "_CONF_HVAC_AC_DURABILITY_WINDOW": "hvac_ac_durability_window",
        "_CONF_HVAC_AC_NIGHT_START_HHMM": "hvac_ac_night_start_hhmm",
        "_CONF_HVAC_AC_NIGHT_END_HHMM": "hvac_ac_night_end_hhmm",
        "_CONF_HVAC_AC_GATE4_PREDICATE_MODE": "hvac_ac_gate4_predicate_mode",
        # RELOAD-WATCHDOG-HAZARD fix-up (2026-08-15, Review C M-1):
        # AST-slice guard requires every referenced Name to be present.
        "ConfigEntry": type("ConfigEntry", (), {}),
        "HomeAssistant": type("HomeAssistant", (), {}),
        "INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS": frozenset(
            {"camera_person_entities"}
        ),
        "INTEGRATION_RELOAD_SUPPRESS_ENABLED": True,
        "_dispatch_integration_key_signals": lambda *a, **kw: None,
        "SIGNAL_URA_TRANSIT_CONFIG_CHANGED": "ura_transit_config_changed",
        # CONF aliases resolved to their string values (matches production).
        "_CONF_HVAC_VACANCY_GRACE_MINUTES": "hvac_vacancy_grace_minutes",
        "_CONF_HVAC_VACANCY_GRACE_CONSTRAINED": "hvac_vacancy_grace_constrained",
        "_CONF_HVAC_MAX_OCCUPANCY_HOURS": "hvac_max_occupancy_hours",
        "_CONF_HVAC_ZONE_ENTRY_DWELL": "hvac_zone_entry_dwell",
        "_CONF_DYNAMIC_PRESET_DWELL_MINUTES": "dynamic_preset_dwell_minutes",
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
        "_CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT":   "energy_offpeak_drain_excellent",
        "_CONF_ENERGY_OFFPEAK_DRAIN_GOOD":        "energy_offpeak_drain_good",
        "_CONF_ENERGY_OFFPEAK_DRAIN_MODERATE":    "energy_offpeak_drain_moderate",
        "_CONF_ENERGY_OFFPEAK_DRAIN_POOR":        "energy_offpeak_drain_poor",
        "_CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR":   "energy_offpeak_drain_very_poor",
        "_CONF_ENERGY_PEAK_BUFFER_TARGET":        "energy_peak_buffer_target",
        "_CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN": "energy_arbitrage_charge_lead_time_min",
        "_CONF_ENERGY_EV_BATTERY_DRAIN_SOC":      "energy_ev_battery_drain_soc",
        # evse-charge-onset cycle knob.
        "_CONF_ENERGY_EVSE_CHARGE_ONSET_TIME":    "energy_evse_charge_onset_time",
        "_CONF_ENERGY_FILL_PRIORITY_SOC":         "energy_fill_priority_soc",
        "_CONF_ENERGY_EXCESS_SOLAR_SOC":          "energy_excess_solar_soc",
        # Blind-window guard cycle — D4 Emporia-mains backup export sensor.
        "_CONF_ENERGY_MAINS_EXPORT_ENTITY":       "energy_mains_export_entity",
        # LKG wave 1 D2 — solar production upper-envelope nameplate.
        "_CONF_ENERGY_SOLAR_NAMEPLATE_W":         "energy_solar_nameplate_w",
        "_CONF_DYNAMIC_PRESET_HYSTERESIS_F":      "dynamic_preset_hysteresis_f",
        "_CONF_HVAC_EGRESS_THRESHOLD_MIN":        "hvac_egress_threshold_min",
        "_CONF_HVAC_EGRESS_RESUME_DELAY_MIN":     "hvac_egress_resume_delay_min",
        "_CONF_FAN_INTERFERENCE_HOLD_S":          "fan_interference_hold_s",
        "_CONF_ROUTINE_EVENT_COOLDOWN_DAYS":      "routine_event_cooldown_days",
        "_CONF_ROUTINE_EVENT_MIN_SEVERITY":       "routine_event_min_severity",
        "_CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS": "routine_regime_baseline_window_days",
        "_CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS": "routine_regime_recent_window_days",
        "_CONF_BAYESIAN_CELL_STALENESS_DAYS":     "bayesian_cell_staleness_days",
        # v4.7.34 — Optimization Coordinator (C-CRIT-1) + ROOM-level
        # comfort sliders (C-HIGH-3). Mirror const.py string values.
        "_CONF_OPTIMIZER_AUTONOMY_LEVEL":         "optimizer_autonomy_level",
        "_CONF_OPTIMIZER_KILL_SWITCH":            "optimizer_kill_switch",
        "_CONF_OPTIMIZER_DIMENSION_AUTONOMY":     "optimizer_dimension_autonomy",
        "_CONF_OPTIMIZER_CONFIDENCE_GATE":        "optimizer_confidence_gate",
        "_CONF_OPTIMIZER_RATE_CAP_PER_HOUR":      "optimizer_rate_cap_per_hour",
        "_CONF_OPTIMIZER_QUIET_HOURS_SOURCE":     "optimizer_quiet_hours_source",
        # OC Pillar B (admin surface) — pending-escalation key.
        "_CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL": "optimizer_pending_autonomy_level",
        # v4.7.35 Phase 2 — LLM tier keys.
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
        # Zone Delete Flow fix-up R2 — CONF_ZONE in _ROOM_SUPPRESS_KEYS.
        "CONF_ZONE":                              "zone",
        # Fan/humidity toggle-symmetry (2026-07-22) — HIGH F1 defect fix.
        "_CONF_FAN_CONTROL_ENABLED":              "fan_control_enabled",
        "_CONF_HUMIDITY_FAN_CONTROL_ENABLED":     "humidity_fan_control_enabled",
        "ENTRY_TYPE_ROOM":                        "room",
        # Session B1 — EVSE Drain-Precedence CM options keys.
        "_CONF_ENERGY_DP_ENABLE":                 "energy_dp_enable",
        "_CONF_ENERGY_DP_EVAL_DELAY_MIN":         "energy_dp_eval_delay_min",
        "_CONF_ENERGY_DP_MARGIN_MIN":             "energy_dp_margin_min",
        "_CONF_ENERGY_DP_MUST_START_BY_MIN":      "energy_dp_must_start_by_min",
        "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A":    "energy_dp_needed_kwh_garage_a",
        "_CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B":    "energy_dp_needed_kwh_garage_b",
        "_CONF_ENERGY_DP_HOUSE_LOAD_SOURCE":      "energy_dp_house_load_source",
        # Arrester operator-immunity cycle (2026-08-06): AC-ramp master
        # option-persistence key (reload-safe path). Added to
        # OPTIONS_RELOAD_SUPPRESS_KEYS to prevent write-through reload loop.
        "_CONF_HVAC_AC_RAMP_MASTER_ENABLED":       "hvac_ac_ramp_master_enabled",
        # Arrester operator-immunity fix-up (2026-08-06): live-tunable
        # immune-person list; wired via set_immune_persons in
        # _apply_in_place, so this shim mapping must be honoured.
        "_CONF_HVAC_ARRESTER_IMMUNE_PERSONS":      "hvac_arrester_immune_persons",
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
        # NM Cycle B fix-up (2026-07-20, B-B1) — dry-run + token-bucket keys.
        "_CONF_NM_DRY_RUN":                            "nm_dry_run",
        "_CONF_NM_BUCKET_CAPACITY":                    "nm_bucket_capacity",
        "_CONF_NM_BUCKET_REFILL_PER_MIN":              "nm_bucket_refill_per_min",
        # NM Cycle C (2026-07-20) — per-recipient matrix + DND-bypass +
        # mute-shortcut keys. All 4 belong to `_NM_C_KEYS` which is
        # splatted into both `_NO_LIVE_ATTR_KEYS` and
        # `OPTIONS_RELOAD_SUPPRESS_KEYS`.
        "_CONF_NM_PERSON_ROUTING_MATRIX":              "nm_person_routing_matrix",
        "_CONF_NM_PERSON_HAZARD_OVERRIDES":            "nm_person_hazard_overrides",
        "_CONF_NM_PERSON_DND_BYPASS_SEVERITIES":       "nm_person_dnd_bypass_severities",
        "_CONF_NM_MUTE_DEFAULT_DURATION_MINUTES":      "nm_mute_default_duration_minutes",
        # NM Cycle C-2 (2026-07-22, D2) — additive-only life-safety extras.
        "_CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS":          "nm_extra_life_safety_hazards",
        # STUCK-SENSOR-1 B-MED-2 fix-up (2026-08-13) — both stuck-signal
        # knobs added to `_NM_A2_KEYS`.
        "_CONF_STUCK_SIGNAL_NM_ENABLED":               "stuck_signal_nm_enabled",
        "_CONF_STUCK_SENSOR_EXCLUSION_ENABLED":        "stuck_sensor_exclusion_enabled",
    }
    mod = ast.Module(body=body, type_ignores=[])
    code = compile(mod, str(PKG / "__init__.py"), "exec")
    # Review-C M-1 fix-up (RELOAD-WATCHDOG-HAZARD, 2026-08-15): post-
    # compile AST guard. See _ast_slice_guard for rationale.
    from _ast_slice_guard import assert_ast_slice_names_covered  # noqa: PLC0415
    assert_ast_slice_names_covered(mod, ns)
    exec(code, ns)
    return ns


def test_apply_in_place_dispatch_coverage():
    """EVERY key in OPTIONS_RELOAD_SUPPRESS_KEYS must be covered by a
    dispatch path in `_apply_in_place`: either the HVAC presence-timer
    block (5 keys), the HVAC tunable factory table (14 keys), the egress
    setters (2 keys), the EC family (10 keys: 4 off-peak + 5 setter + 1
    arbitrage already in setter dict), the fan-interference hold (1 key),
    OR the `_NO_LIVE_ATTR_KEYS` snapshot-only set (DPM dwell + DPM hyst +
    4 routine + Bayesian = 7 keys).

    Total = 5 + 14 + 2 + 9 + 1 + 7 = 38. The allowlist has 37 because
    the 5 presence-timer keys include DPM dwell (which is also in
    _NO_LIVE_ATTR_KEYS — overlap). Adjusted total = 37."""
    ns = _load_init_dispatch_namespace()
    allowlist = set(ns["OPTIONS_RELOAD_SUPPRESS_KEYS"])
    covered = set()
    # HVAC presence timers (handled by hand-written branches in the func)
    covered.update({
        "hvac_vacancy_grace_minutes",
        "hvac_vacancy_grace_constrained",
        "hvac_max_occupancy_hours",
        "hvac_zone_entry_dwell",
    })
    # HVAC tunable factory
    covered.update(ns["_HVAC_TUNABLE_DISPATCH"].keys())
    # EC setters + off-peak drain
    covered.update(ns["_EC_SETTER_DISPATCH"].keys())
    covered.update(ns["_OFFPEAK_DRAIN_QUALITY"].keys())
    # Egress + fan-interference (hand-written branches)
    covered.update({
        "hvac_egress_threshold_min",
        "hvac_egress_resume_delay_min",
        "fan_interference_hold_s",
    })
    # v5.10.0 D2 — MF sleep + night suppression (hand-written branch calling
    # MusicFollowing.update_gate_config()).
    covered.update({
        "mf_sleep_suppress",
        "mf_night_suppress_mode",
    })
    # No-live-attr keys (Routine + Bayesian + DPM dwell + DPM hyst)
    covered.update(ns["_NO_LIVE_ATTR_KEYS"])
    missing = allowlist - covered
    assert not missing, (
        f"Dispatch coverage gap: {sorted(missing)} are in allowlist "
        "but have no dispatch branch in _apply_in_place"
    )


# ---------------------------------------------------------------------------
# D6 — no RestoreEntity left in number.py (excluding the D4 split-out)
# ---------------------------------------------------------------------------


def _classes_with_restoreentity() -> list[str]:
    tree = ast.parse(NUMBER_SRC)
    found: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for b in node.bases:
                name = None
                if isinstance(b, ast.Name):
                    name = b.id
                elif isinstance(b, ast.Attribute):
                    name = b.attr
                if name == "RestoreEntity":
                    found.append(node.name)
    # Also walk inner-classes (factory outputs).
    for outer in ast.walk(tree):
        if isinstance(outer, ast.ClassDef):
            for inner in outer.body:
                if isinstance(inner, ast.ClassDef):
                    for b in inner.bases:
                        name = None
                        if isinstance(b, ast.Name):
                            name = b.id
                        elif isinstance(b, ast.Attribute):
                            name = b.attr
                        if name == "RestoreEntity" and inner.name not in found:
                            found.append(inner.name)
    return found


def test_no_restoreentity_left_in_number_py_except_d4_split_out():
    """Post-Part-2, the only Number class allowed to still inherit
    RestoreEntity is `_HVACZoneKwhThresholdNumber` (D4 explicitly split
    out: there is no per-zone CONF in entry.options today, so the slider's
    RestoreEntity is its persistence mechanism until a follow-up cycle
    introduces a per-zone CONF family)."""
    leftovers = _classes_with_restoreentity()
    # The factory body's inner class is the only legitimate leftover.
    allowed = {"_HVACZoneKwhThresholdNumber"}
    surprising = set(leftovers) - allowed
    assert not surprising, (
        f"RestoreEntity still on: {sorted(surprising)} "
        "(only _HVACZoneKwhThresholdNumber is allowed per D4 split-out)"
    )


# ---------------------------------------------------------------------------
# D6 — Part 2 does not regress the v4.7.25 keys
# ---------------------------------------------------------------------------


def test_part2_retrofit_does_not_break_v4_7_25_keys():
    """The four HVAC presence timers + DPM dwell must remain on the
    allowlist AND have functioning dispatch (covered by their hand-written
    branches in apply_in_place). Re-asserted explicitly so a Part 2 edit
    that accidentally drops them shows up here."""
    ns = _load_init_dispatch_namespace()
    allowlist = set(ns["OPTIONS_RELOAD_SUPPRESS_KEYS"])
    for k in (
        "hvac_vacancy_grace_minutes",
        "hvac_vacancy_grace_constrained",
        "hvac_max_occupancy_hours",
        "hvac_zone_entry_dwell",
        "dynamic_preset_dwell_minutes",
    ):
        assert k in allowlist, f"v4.7.25 key {k} dropped from allowlist"


# ---------------------------------------------------------------------------
# D1 — per-class assertions (EC family)
# ---------------------------------------------------------------------------


EC_CLASSES = (
    "OffPeakDrainNumber",
    "PeakBufferTargetNumber",
    "ArbitrageChargeLeadTimeNumber",
    "EVBatteryDrainSOCNumber",
    "FillPrioritySOCNumber",
    "ExcessSolarSOCNumber",
    "BayesianCellStalenessNumber",
)


@pytest.mark.parametrize("cls_name", EC_CLASSES)
def test_d1_class_no_restoreentity(cls_name):
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)
            assert "RestoreEntity" not in bases, (
                f"{cls_name} still inherits RestoreEntity (bases={bases})"
            )
            return
    pytest.fail(f"{cls_name} not found")


@pytest.mark.parametrize("cls_name", EC_CLASSES)
def test_d1_class_setter_writes_through_async_update_entry(cls_name):
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_set_native_value":
                    src = ast.unparse(item)
                    assert "async_update_entry" in src, (
                        f"{cls_name}.async_set_native_value does not call "
                        "async_update_entry"
                    )
                    return
    pytest.fail(f"{cls_name}.async_set_native_value not found")


def test_d1_offpeak_drain_dispatch_uses_set_offpeak_drain_setter():
    """OffPeakDrain dispatch MUST call `energy.set_offpeak_drain(quality, value)`,
    NOT a direct attr write. The setter carries _check_threshold_ladder()
    side-effects that a raw setattr would silently skip."""
    apply_src = _get_apply_in_place_src()
    # set_offpeak_drain is invoked on the energy coordinator with the
    # quality string from _OFFPEAK_DRAIN_QUALITY.
    assert "energy.set_offpeak_drain(quality" in apply_src, (
        "OffPeakDrain dispatch must call energy.set_offpeak_drain(quality, ...) "
        "— direct attr write would skip _check_threshold_ladder side-effect"
    )


def test_d1_offpeak_drain_quality_mapping_complete():
    """All FIVE quality buckets must be in the dispatch map.

    OFFPEAK-DRAIN-VERYPOOR-SLIDER-1 added `very_poor` as the 5th knob.
    Mutation-anchor: removing `very_poor` from `_OFFPEAK_DRAIN_QUALITY`
    in `__init__.py` fails THIS test.
    """
    ns = _load_init_dispatch_namespace()
    assert set(ns["_OFFPEAK_DRAIN_QUALITY"].values()) == {
        "excellent", "good", "moderate", "poor", "very_poor",
    }


def test_d1_offpeak_drain_verypoor_slider_roundtrip():
    """OFFPEAK-DRAIN-VERYPOOR-SLIDER-1: end-to-end knob wiring.

    Asserts the 5th slider is present at every mirror site:
      - CONF constant in energy_const.py
      - Default constant in energy_const.py (mirrors poor at 30)
      - Number entity instantiated in async_setup_entry (number.py)
      - Number entity's _conf_map dict entries (both __init__ + setter)
      - config_flow form field
      - __init__.py _OFFPEAK_DRAIN_QUALITY dispatch mapping
      - __init__.py reload-suppression allowlist
      - Setter accepts "very_poor" quality (energy.py:set_offpeak_drain)

    Mutation-anchor: removing the `very_poor` _conf_map entry (either
    site in number.py) breaks the round-trip and this test fails.
    """
    # 1. CONF + DEFAULT constants
    assert "energy_offpeak_drain_very_poor" == _extract_conf(
        ENERGY_CONST_SRC, "CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR",
    )
    assert "DEFAULT_OFFPEAK_DRAIN_VERY_POOR" in ENERGY_CONST_SRC

    # 2. Number entity instantiated in async_setup_entry
    assert 'OffPeakDrainNumber(hass, entry, "very_poor"' in NUMBER_SRC, (
        "async_setup_entry missing the very_poor OffPeakDrainNumber "
        "instantiation (number.py)"
    )

    # 3. Both _conf_map dicts (constructor + setter) must map very_poor
    assert NUMBER_SRC.count(
        '"very_poor": CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR'
    ) == 2, (
        "OffPeakDrainNumber must reference very_poor in BOTH the "
        "constructor _conf_map AND the setter _conf_map (number.py)"
    )
    # And both import blocks must include the CONF
    assert NUMBER_SRC.count("CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR,") >= 2

    # 4. config_flow: form field with CONF + DEFAULT
    with open(_repo_root() / "custom_components/universal_room_automation/config_flow.py") as f:
        cf_src = f.read()
    assert "CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR" in cf_src, (
        "config_flow.py missing the very_poor selector"
    )
    assert "DEFAULT_OFFPEAK_DRAIN_VERY_POOR" in cf_src

    # 5. __init__.py dispatch map + allowlist
    ns = _load_init_dispatch_namespace()
    assert "very_poor" in set(ns["_OFFPEAK_DRAIN_QUALITY"].values())

    # 6. energy.py consumer wiring — offpeak_drain_targets["very_poor"]
    with open(_repo_root() / "custom_components/universal_room_automation/domain_coordinators/energy.py") as f:
        energy_src = f.read()
    assert 'CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR' in energy_src, (
        "energy.py must read CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR into "
        "offpeak_drain_targets so the Number entity feeds the strategy"
    )
    # Setter already accepts very_poor (added in v5.91.2, guarded by the
    # {'excellent','good','moderate','poor','very_poor'} valid set).
    assert '"very_poor"' in energy_src


def _repo_root():
    """Repo root helper (this file lives at quality/tests/)."""
    import pathlib
    return pathlib.Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# D2 — Routine base + 4 subclasses
# ---------------------------------------------------------------------------


def test_d2_routine_base_no_restoreentity():
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "_RoutineNumberBase":
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)
            assert "RestoreEntity" not in bases, (
                f"_RoutineNumberBase still inherits RestoreEntity (bases={bases})"
            )
            return
    pytest.fail("_RoutineNumberBase not found")


def test_d2_routine_base_setter_writes_through_async_update_entry():
    """The base class's `async_set_native_value` must call
    `async_update_entry` so all four subclasses inherit working persistence.
    Pre-Part-2 the base did NOT write back (only RoutineEventMinSeverityNumber
    had a one-shot migration write)."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "_RoutineNumberBase":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_set_native_value":
                    src = ast.unparse(item)
                    assert "async_update_entry" in src
                    assert "self._conf_key" in src or "_conf_key" in src
                    return
    pytest.fail("_RoutineNumberBase.async_set_native_value not found")


# ---------------------------------------------------------------------------
# D3 — _HVACTunableNumber factory
# ---------------------------------------------------------------------------


def test_d3_hvac_tunable_factory_inner_class_no_restoreentity():
    """The inner class produced by `_hvac_tunable_number_factory` must NOT
    inherit from RestoreEntity post-Part-2."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_hvac_tunable_number_factory":
            for inner in ast.walk(node):
                if isinstance(inner, ast.ClassDef) and inner.name == "_HVACTunableNumber":
                    bases = []
                    for b in inner.bases:
                        if isinstance(b, ast.Name):
                            bases.append(b.id)
                        elif isinstance(b, ast.Attribute):
                            bases.append(b.attr)
                    assert "RestoreEntity" not in bases
                    return
    pytest.fail("_HVACTunableNumber inner class not found")


def test_d3_hvac_tunable_factory_setter_calls_async_update_entry():
    """The factory's `async_set_native_value` must now write back
    to entry.options (it did NOT pre-Part-2)."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_hvac_tunable_number_factory":
            for inner in ast.walk(node):
                if isinstance(inner, ast.AsyncFunctionDef) and inner.name == "async_set_native_value":
                    src = ast.unparse(inner)
                    assert "async_update_entry" in src
                    assert "conf_key" in src
                    return
    pytest.fail("_HVACTunableNumber.async_set_native_value not found")


def test_d3_hvac_tunable_factory_signal_dispatcher_hookup_preserved():
    """The cross-coordinator init-race fix (SIGNAL_HVAC_ENTITIES_UPDATE
    listener in `async_added_to_hass`) MUST be preserved — only the
    `last_state` read should have been dropped."""
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_hvac_tunable_number_factory":
            for inner in ast.walk(node):
                if isinstance(inner, ast.AsyncFunctionDef) and inner.name == "async_added_to_hass":
                    src = ast.unparse(inner)
                    assert "SIGNAL_HVAC_ENTITIES_UPDATE" in src
                    assert "async_dispatcher_connect" in src
                    # Restore branch is removed.
                    assert "async_get_last_state" not in src
                    return
    pytest.fail("_HVACTunableNumber.async_added_to_hass not found")


def test_d3_hvac_tunable_dispatch_table_covers_all_14_factory_outputs():
    """The dispatch table in __init__.py must enumerate exactly the 14
    keys produced by `_build_hvac_v4510_numbers` + `_build_hvac_v4511_numbers`
    factory calls."""
    ns = _load_init_dispatch_namespace()
    expected = {
        "hvac_occupied_cover_close_delta",
        "hvac_cover_close_temp",
        "hvac_cover_open_temp",
        "hvac_cover_override_hours",
        "hvac_solar_bank_floor",
        "hvac_fan_activation_delta",
        "hvac_fan_hysteresis",
        "hvac_ac_nudge_size",
        "hvac_ac_nudge_duration",
        "hvac_ac_nudge_eval_delay",
        "hvac_ac_sustained_samples",
        "hvac_ac_detection_time_gate",
        "hvac_ac_hard_reset_daily_limit",
        "hvac_ac_hard_reset_min_interval",
    }
    assert set(ns["_HVAC_TUNABLE_DISPATCH"].keys()) == expected


def test_d3_hvac_tunable_dispatch_cast_correct_int_vs_float():
    """The 6 integer tunables must cast to int; the other 8 must cast to
    float. Mirrors the factory's `integer=` parameter."""
    ns = _load_init_dispatch_namespace()
    int_keys = {
        "hvac_ac_nudge_duration",
        "hvac_ac_nudge_eval_delay",
        "hvac_ac_sustained_samples",
        "hvac_ac_detection_time_gate",
        "hvac_ac_hard_reset_daily_limit",
        "hvac_ac_hard_reset_min_interval",
    }
    for key, (_sub, _field, cast_fn) in ns["_HVAC_TUNABLE_DISPATCH"].items():
        if key in int_keys:
            assert cast_fn is int, f"{key} should cast to int"
        else:
            assert cast_fn is float, f"{key} should cast to float"


# ---------------------------------------------------------------------------
# D5 — remaining HVAC RestoreEntity Numbers
# ---------------------------------------------------------------------------


D5_CLASSES = (
    "DynamicPresetHysteresisFNumber",
    "HVACEgressPauseThresholdNumber",
    "HVACEgressResumeDelayNumber",
    "FanInterferenceHoldNumber",
)


@pytest.mark.parametrize("cls_name", D5_CLASSES)
def test_d5_class_no_restoreentity(cls_name):
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)
            assert "RestoreEntity" not in bases, (
                f"{cls_name} still inherits RestoreEntity (bases={bases})"
            )
            return
    pytest.fail(f"{cls_name} not found")


@pytest.mark.parametrize("cls_name", D5_CLASSES)
def test_d5_class_setter_writes_through_async_update_entry(cls_name):
    tree = ast.parse(NUMBER_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_set_native_value":
                    src = ast.unparse(item)
                    assert "async_update_entry" in src, (
                        f"{cls_name}.async_set_native_value missing writeback"
                    )
                    return
    pytest.fail(f"{cls_name}.async_set_native_value not found")


# ---------------------------------------------------------------------------
# Runtime behavior — _apply_in_place against the new dispatch tables
# ---------------------------------------------------------------------------


class _FakeBattery:
    def __init__(self):
        self._drain_targets = {"excellent": 30, "good": 40, "moderate": 50, "poor": 60}
        self._peak_buffer_target = 80
        self._arbitrage_target = 80
        self._arbitrage_charge_lead_time_min = 360


class _FakeEnergy:
    def __init__(self):
        self._battery = _FakeBattery()
        self._ev_battery_drain_soc = 20
        self._fill_priority_soc = 80
        self._excess_solar_soc = 95
        self._threshold_ladder_checks = 0
        self.set_offpeak_drain_calls = []

    def set_offpeak_drain(self, quality, value):
        self.set_offpeak_drain_calls.append((quality, value))
        self._battery._drain_targets[quality] = value
        self._threshold_ladder_checks += 1

    def set_peak_buffer_target(self, value):
        self._battery._peak_buffer_target = int(value)
        self._threshold_ladder_checks += 1

    def set_arbitrage_charge_lead_time(self, value):
        self._battery._arbitrage_charge_lead_time_min = int(value)

    def set_ev_battery_drain_soc(self, value):
        self._ev_battery_drain_soc = int(value)

    def set_fill_priority_soc(self, value):
        self._fill_priority_soc = int(value)

    def set_excess_solar_soc(self, value):
        self._excess_solar_soc = int(value)


class _FakeSub:
    def __init__(self):
        # All the runtime_fields used by the 14 HVAC tunables.
        self._occupied_close_delta = 1.5
        self._cover_close_temp = 85
        self._cover_open_temp = 78
        self._cover_override_hours = 4.0
        self._solar_bank_floor = 70
        self._activation_delta = 1.0
        self._deactivation_delta = 1.0
        self._nudge_size_f = 1.0
        self._nudge_duration_min = 5
        self._nudge_eval_delay_s = 600
        self._sustained_samples = 3
        self._detection_time_gate_min = 10
        self._hard_reset_daily_limit = 2
        self._hard_reset_min_interval_min = 90


class _FakeEgressMgr:
    def __init__(self):
        self._threshold_min = 3
        self._resume_delay_min = 1

    def set_threshold_min(self, v):
        self._threshold_min = int(v)

    def set_resume_delay_min(self, v):
        self._resume_delay_min = int(v)


class _FakeHvacFull:
    def __init__(self):
        self._vacancy_grace = 20
        self._vacancy_grace_constrained = 10
        self._max_occupancy_hours = 6
        self._zone_entry_dwell = 2
        self._cover_controller = _FakeSub()
        self._predictor = _FakeSub()
        self._fan_controller = _FakeSub()
        self._override_arrester = _FakeSub()
        self.egress_manager = _FakeEgressMgr()


class _FakePresence:
    def __init__(self):
        self._fan_interference_hold_s = 300
        self.set_fan_interference_hold_s_calls = []

    def set_fan_interference_hold_s(self, v):
        self.set_fan_interference_hold_s_calls.append(int(v))
        self._fan_interference_hold_s = int(v)


class _FakeManagerFull:
    def __init__(self, hvac=None, energy=None, presence=None):
        self.coordinators = {
            "hvac": hvac, "energy": energy, "presence": presence,
        }


class _FakeHassFull:
    def __init__(self, hvac=None, energy=None, presence=None):
        self.data = {"universal_room_automation": {
            "coordinator_manager": _FakeManagerFull(hvac, energy, presence),
        }}
        self.config_entries = MagicMock()
        self.config_entries.async_reload = MagicMock()
        self.async_create_task = MagicMock()


class _FakeEntry:
    def __init__(self, entry_id="cm1", options=None, is_cm=True, title="CM"):
        self.entry_id = entry_id
        self.title = title
        self.options = dict(options or {})
        self.data = {"entry_type": "coordinator_manager"} if is_cm else {"entry_type": "room"}


def _get_apply_in_place_src() -> str:
    tree = ast.parse(INIT_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_in_place":
            return ast.unparse(node)
    pytest.fail("_apply_in_place not found")


# --- D1 EC family runtime ---


def test_d1_apply_in_place_routes_offpeak_drain_to_setter():
    """Editing CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT must call
    `energy.set_offpeak_drain('excellent', value)`."""
    ns = _load_init_dispatch_namespace()
    energy = _FakeEnergy()
    hass = _FakeHassFull(hvac=_FakeHvacFull(), energy=energy)
    new = {"energy_offpeak_drain_excellent": 35}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"energy_offpeak_drain_excellent"}, new,
    )
    assert ("excellent", 35) in energy.set_offpeak_drain_calls
    assert applied == {"energy_offpeak_drain_excellent"}


def test_d1_apply_in_place_routes_all_five_offpeak_quality_buckets():
    ns = _load_init_dispatch_namespace()
    energy = _FakeEnergy()
    hass = _FakeHassFull(hvac=_FakeHvacFull(), energy=energy)
    new = {
        "energy_offpeak_drain_excellent": 35,
        "energy_offpeak_drain_good":      45,
        "energy_offpeak_drain_moderate":  55,
        "energy_offpeak_drain_poor":      65,
        # OFFPEAK-DRAIN-VERYPOOR-SLIDER-1: 5th bucket.
        "energy_offpeak_drain_very_poor": 40,
    }
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), set(new.keys()), new,
    )
    qualities_called = {q for q, _ in energy.set_offpeak_drain_calls}
    assert qualities_called == {
        "excellent", "good", "moderate", "poor", "very_poor",
    }
    assert applied == set(new.keys())


def test_d1_apply_in_place_routes_ec_setter_keys():
    ns = _load_init_dispatch_namespace()
    energy = _FakeEnergy()
    hass = _FakeHassFull(hvac=_FakeHvacFull(), energy=energy)
    new = {
        "energy_peak_buffer_target": 85,
        "energy_arbitrage_charge_lead_time_min": 240,
        "energy_ev_battery_drain_soc": 25,
        "energy_fill_priority_soc": 82,
        "energy_excess_solar_soc": 92,
    }
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), set(new.keys()), new,
    )
    assert energy._battery._peak_buffer_target == 85
    assert energy._battery._arbitrage_charge_lead_time_min == 240
    assert energy._ev_battery_drain_soc == 25
    assert energy._fill_priority_soc == 82
    assert energy._excess_solar_soc == 92
    assert applied == set(new.keys())


def test_d1_apply_in_place_safe_when_energy_missing():
    """EC keys must not raise when the EC is None — they're persisted
    in entry.options already; setup will pick them up."""
    ns = _load_init_dispatch_namespace()
    hass = _FakeHassFull(hvac=_FakeHvacFull(), energy=None)
    new = {"energy_peak_buffer_target": 85}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"energy_peak_buffer_target"}, new,
    )
    # No EC → not applied (caller's snapshot will retry next time).
    assert applied == set()


def test_d1_bayesian_marked_applied_no_live_attr():
    """Bayesian cell staleness has no live coordinator attr; it must be
    marked applied via the no-live-attr path."""
    ns = _load_init_dispatch_namespace()
    hass = _FakeHassFull(hvac=_FakeHvacFull(), energy=_FakeEnergy())
    new = {"bayesian_cell_staleness_days": 21}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"bayesian_cell_staleness_days"}, new,
    )
    assert applied == {"bayesian_cell_staleness_days"}


# --- D2 Routine runtime ---


@pytest.mark.parametrize("key", [
    "routine_event_cooldown_days",
    "routine_event_min_severity",
    "routine_regime_baseline_window_days",
    "routine_regime_recent_window_days",
])
def test_d2_routine_keys_treated_as_no_live_attr(key):
    ns = _load_init_dispatch_namespace()
    hass = _FakeHassFull(hvac=_FakeHvacFull())
    new = {key: 42}
    applied = ns["_apply_in_place"](hass, _FakeEntry(options=new), {key}, new)
    assert applied == {key}


# --- D3 HVAC tunable runtime ---


@pytest.mark.parametrize("key, sub_attr, runtime_field, write_value, expect_int", [
    ("hvac_occupied_cover_close_delta",  "_cover_controller",  "_occupied_close_delta",      2.5, False),
    ("hvac_cover_close_temp",            "_cover_controller",  "_cover_close_temp",          84,  False),
    ("hvac_cover_open_temp",             "_cover_controller",  "_cover_open_temp",           76,  False),
    ("hvac_cover_override_hours",        "_cover_controller",  "_cover_override_hours",      5.0, False),
    ("hvac_solar_bank_floor",            "_predictor",         "_solar_bank_floor",          68,  False),
    ("hvac_fan_activation_delta",        "_fan_controller",    "_activation_delta",          1.5, False),
    ("hvac_fan_hysteresis",              "_fan_controller",    "_deactivation_delta",        2.0, False),
    ("hvac_ac_nudge_size",               "_override_arrester", "_nudge_size_f",              2.0, False),
    ("hvac_ac_nudge_duration",           "_override_arrester", "_nudge_duration_min",        7,   True),
    ("hvac_ac_nudge_eval_delay",         "_override_arrester", "_nudge_eval_delay_s",        900, True),
    ("hvac_ac_sustained_samples",        "_override_arrester", "_sustained_samples",         4,   True),
    ("hvac_ac_detection_time_gate",      "_override_arrester", "_detection_time_gate_min",   15,  True),
    ("hvac_ac_hard_reset_daily_limit",   "_override_arrester", "_hard_reset_daily_limit",    3,   True),
    ("hvac_ac_hard_reset_min_interval",  "_override_arrester", "_hard_reset_min_interval_min", 120, True),
])
def test_d3_apply_in_place_routes_hvac_tunable_keys(
    key, sub_attr, runtime_field, write_value, expect_int,
):
    """Every one of the 14 HVAC tunable factory keys must dispatch via
    setattr on the configured sub-controller / runtime field, with the
    correct cast (int vs float)."""
    ns = _load_init_dispatch_namespace()
    hvac = _FakeHvacFull()
    hass = _FakeHassFull(hvac=hvac)
    new = {key: write_value}
    applied = ns["_apply_in_place"](hass, _FakeEntry(options=new), {key}, new)
    sub = getattr(hvac, sub_attr)
    written = getattr(sub, runtime_field)
    assert applied == {key}
    if expect_int:
        assert written == int(write_value)
        assert isinstance(written, int)
    else:
        assert written == float(write_value)


def test_d3_apply_in_place_safe_when_hvac_sub_controller_missing():
    """If a sub-controller attribute is None on the hvac coord (e.g., not
    yet wired during init), dispatch must skip cleanly without raising."""
    ns = _load_init_dispatch_namespace()
    hvac = _FakeHvacFull()
    hvac._cover_controller = None
    hass = _FakeHassFull(hvac=hvac)
    new = {"hvac_cover_close_temp": 86}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"hvac_cover_close_temp"}, new,
    )
    # Not applied because the sub was None.
    assert "hvac_cover_close_temp" not in applied


# --- D5 runtime ---


def test_d5_egress_threshold_dispatch_calls_setter():
    ns = _load_init_dispatch_namespace()
    hvac = _FakeHvacFull()
    hass = _FakeHassFull(hvac=hvac)
    new = {"hvac_egress_threshold_min": 5}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"hvac_egress_threshold_min"}, new,
    )
    assert hvac.egress_manager._threshold_min == 5
    assert applied == {"hvac_egress_threshold_min"}


def test_d5_egress_resume_delay_dispatch_calls_setter():
    ns = _load_init_dispatch_namespace()
    hvac = _FakeHvacFull()
    hass = _FakeHassFull(hvac=hvac)
    new = {"hvac_egress_resume_delay_min": 4}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"hvac_egress_resume_delay_min"}, new,
    )
    assert hvac.egress_manager._resume_delay_min == 4
    assert applied == {"hvac_egress_resume_delay_min"}


def test_d5_fan_interference_hold_dispatch_calls_setter():
    ns = _load_init_dispatch_namespace()
    presence = _FakePresence()
    hass = _FakeHassFull(hvac=_FakeHvacFull(), presence=presence)
    new = {"fan_interference_hold_s": 600}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"fan_interference_hold_s"}, new,
    )
    assert 600 in presence.set_fan_interference_hold_s_calls
    assert applied == {"fan_interference_hold_s"}


def test_d5_dpm_hysteresis_treated_as_no_live_attr():
    """DPM hysteresis is read via _get_cm_options() each tick; no live
    push required."""
    ns = _load_init_dispatch_namespace()
    hass = _FakeHassFull(hvac=_FakeHvacFull())
    new = {"dynamic_preset_hysteresis_f": 1.5}
    applied = ns["_apply_in_place"](
        hass, _FakeEntry(options=new), {"dynamic_preset_hysteresis_f"}, new,
    )
    assert applied == {"dynamic_preset_hysteresis_f"}


# ---------------------------------------------------------------------------
# Mixed-key reload fallback regression — Part 2 keys included
# ---------------------------------------------------------------------------


def test_listener_still_reloads_for_mixed_change_with_part2_key():
    """A write that touches an EC key AND a non-allowlisted key must
    STILL trigger reload (mixed-change branch). Part 2 didn't change
    that contract."""
    ns = _load_init_dispatch_namespace()
    hvac = _FakeHvacFull()
    energy = _FakeEnergy()
    hass = _FakeHassFull(hvac=hvac, energy=energy)
    entry = _FakeEntry(options={
        "energy_peak_buffer_target": 80,
        "presence_enabled": True,
    })
    ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = {
        "energy_peak_buffer_target": 85,
        "presence_enabled": False,
    }
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 1


def test_listener_suppresses_reload_for_part2_only_change():
    """Writing only a Part 2 key (e.g. EC peak buffer) must suppress
    the reload — the new pattern landing."""
    ns = _load_init_dispatch_namespace()
    energy = _FakeEnergy()
    hass = _FakeHassFull(hvac=_FakeHvacFull(), energy=energy)
    entry = _FakeEntry(options={"energy_peak_buffer_target": 80})
    ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = {"energy_peak_buffer_target": 85}
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0
    assert energy._battery._peak_buffer_target == 85


def test_listener_suppresses_reload_for_hvac_tunable_change():
    """Cover-close-threshold edit must suppress reload AND push live attr."""
    ns = _load_init_dispatch_namespace()
    hvac = _FakeHvacFull()
    hass = _FakeHassFull(hvac=hvac)
    entry = _FakeEntry(options={"hvac_occupied_cover_close_delta": 1.5})
    ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = {"hvac_occupied_cover_close_delta": 2.5}
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry)
    )
    assert hass.async_create_task.call_count == 0
    assert hvac._cover_controller._occupied_close_delta == 2.5

"""Energy Coordinator constants — TOU rate tables, entity mappings, defaults."""

from __future__ import annotations

import re
from typing import Any, Final

# ============================================================================
# PEC TOU Rate Table (2026 Interconnect Time-of-Use)
# ============================================================================
# Source: docs/plans/TOU.md — PEC Interconnection Metering < 50kW
# Import and export rates are symmetric.
# Hours use 24h convention: (start_inclusive, end_exclusive)

PEC_TOU_RATES: Final = {
    "summer": {
        "months": [6, 7, 8, 9],
        "periods": {
            "off_peak": {
                "hours": [(0, 14), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(14, 16), (20, 21)],
                "import_rate": 0.093169,
                "export_rate": 0.093169,
            },
            "peak": {
                "hours": [(16, 20)],
                "import_rate": 0.161843,
                "export_rate": 0.161843,
            },
        },
    },
    "shoulder": {
        "months": [3, 4, 5, 10, 11],
        "periods": {
            "off_peak": {
                "hours": [(0, 17), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(17, 21)],
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
    "winter": {
        "months": [12, 1, 2],
        "periods": {
            "off_peak": {
                "hours": [(0, 5), (9, 17), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(5, 9), (17, 21)],
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
}

PEC_FIXED_CHARGES: Final = {
    "service_availability": 32.50,
    "delivery_per_kwh": 0.022546,
    "transmission_per_kwh": 0.019930,
}

# ============================================================================
# Solar Day Classification Thresholds (kWh)
# ============================================================================

# Per-month solar thresholds (kWh) derived from actual Enphase production data
# (50 panels, 19.4kW DC). Keyed by month number → (P25, P50, P75).
# Classification: excellent >= P75, good >= P50, moderate >= P25, poor < P25.
SOLAR_MONTHLY_THRESHOLDS: Final = {
    1: (33.0, 61.0, 83.0),   # Jan (extrapolated from Dec)
    2: (49.0, 66.0, 80.0),
    3: (60.0, 80.0, 95.0),
    4: (73.0, 93.0, 108.0),
    5: (85.0, 103.0, 118.0),
    6: (106.0, 125.0, 136.0),
    7: (100.0, 120.0, 133.0),
    8: (88.0, 108.0, 124.0),
    9: (68.0, 88.0, 104.0),
    10: (50.0, 68.0, 83.0),
    11: (36.0, 52.0, 66.0),
    12: (33.0, 61.0, 83.0),
}

# Fallback static thresholds for custom override mode
SOLAR_DAY_THRESHOLDS: Final = {
    "excellent": 100.0,
    "good": 80.0,
    "moderate": 50.0,
    "poor": 30.0,
    # below poor = very_poor
}

# ============================================================================
# R1 — Consumption regression (season + HDD/CDD, EV-decomposed) — v1
# ============================================================================
# Reviewed constants derived offline by
# `scripts/energy/fit_consumption_regression.py` (deterministic pure-OLS fit;
# reviewer re-runs the script and gets byte-identical values). See B0 probe
# (docs/planning/B0_net_energy_classification_probe.md §E) and the R1 planning
# doc (docs/planning/PLANNING_net_energy_program_R1_R7_R2.md) for full context.
#
# Structure — parsimony per operator directive 2026-07-16:
#     predicted_consumption(d, temp) = base_regression(d, temp)
#                                    + (ev_term_kwh if d >= ev_era_start else 0)
# The base regression is fit on 2025-only (EV-free by operator statement); the
# EV term is a single reviewed constant (mean of positive 2026 base-residual).
# A per-session / plan-aware EV term is deferred to R8.
#
# The `predicted_consumption_source` marker written to `energy_daily` tags each
# row with which arm produced the number (`v1_regression` / `dow_legacy` /
# `fallback`) — R2's future consumer gate refuses to widen unless the source is
# `v1_regression`.
#
# ----------------------------------------------------------------------------
# Numbers Get Knobs — rung placement:
#   - rung-1 (reviewed const, changing requires re-fit + review):
#       CONSUMPTION_REGRESSION_V1, EV_ERA_START_DATE, EV_TERM_KWH_PER_DAY.
#   - rung-2 (module const, no UI): CONF_R1_ESTIMATOR_SHADOW_ONLY default
#       (True on ship; flipped as R2 prereq after 14-day shadow proves out).
#   - rung-3 candidates flagged for operator (NOT created):
#       - Shadow-mode toggle as a Switch entity — pending operator decision.
#       - Rolling shadow-window length as a Number entity.
#
# D-MED-1 (R2-flip prerequisite): before flipping CONF_R1_ESTIMATOR_SHADOW_ONLY
# off, reset/exempt _adjustment_factor (legacy-trained multiplier) for the v1
# path — see review record (Tier-3 R1 review D-MED-1). The legacy adjustment
# was fit against the DOW baseline and would silently rescale the v1 output.
# ----------------------------------------------------------------------------
CONSUMPTION_REGRESSION_V1: Final[dict] = {
    "base":               92.4181,   # intercept kWh (winter baseline, 2025 EV-free fit)
    "cdd_coeff":          2.1976,    # kWh per cooling-degree-day (base 65°F)
    "hdd_coeff":          0.4981,    # kWh per heating-degree-day (base 65°F)
    "season_spring":      5.7807,
    "season_summer":      18.3129,
    "season_fall":        2.0104,
    "season_winter":      0.0,       # baseline (dummy encoding)
    "hdd_base_f":         65.0,
    "cdd_base_f":         65.0,
    "ev_term_kwh":        18.5788,   # constant kWh/day added when today >= ev_era_start
    "ev_era_start":       "2026-03-01",
    "fit_date":           "2026-07-16",
    "train_span":         "2025-02-25..2025-12-31",   # 2025 only (EV-free)
    "holdout_span":       "2026-05-01..2026-07-15",
    "n_train":            271,
    "n_ev_era_for_term":  69,
    "n_holdout":          57,
    "train_mae_kwh":      16.82,
    "train_r2":           0.4149,
    "holdout_mae_kwh":    16.06,     # combined base + EV_TERM (invariant: ≤ 20)
    "holdout_r2":         0.3668,
    "holdout_mae_base_only_kwh": 23.67,
}

# rung-2: shadow-mode gate. True = new v1 estimator computes + logs alongside
# the legacy DOW+fallback estimator, but the CONSUMED (published) value stays
# on the legacy path. Flipped False as R2 prerequisite after the 14-day
# shadow report clears the operator checkpoint. Not exposed as a CONF/UI in R1.
CONF_R1_ESTIMATOR_SHADOW_ONLY: Final[bool] = True

# Source markers written to `energy_daily.predicted_consumption_source`.
PRED_CONSUMPTION_SOURCE_V1_REGRESSION: Final[str] = "v1_regression"
PRED_CONSUMPTION_SOURCE_DOW_LEGACY:    Final[str] = "dow_legacy"
PRED_CONSUMPTION_SOURCE_FALLBACK:      Final[str] = "fallback"

# ============================================================================
# Battery Strategy Defaults
# ============================================================================

DEFAULT_RESERVE_SOC: Final = 10  # v4.3.0 D3: was 20; lowered to give arbitrage maneuvering room
DEFAULT_STORM_CHARGE_THRESHOLD: Final = 90
DEFAULT_DECISION_INTERVAL_MINUTES: Final = 5

# v5.17.3 D1: at-boundary TOU decision-tick delay.
# Fires one extra `_async_decision_cycle` at (next_boundary + DELAY),
# real wall clock. The tick evaluates the actual just-started period
# exactly like a periodic tick — no synthetic-clock override anywhere.
# The +5s guard rides past the second-of-boundary edge so
# `get_current_period` reliably reports the new period.
#
# KILL SWITCH: setting this to a NEGATIVE value CLEANLY DISABLES the
# at-boundary tick — `_arm_tou_boundary_listener` returns early, no
# `async_track_point_in_time` is registered, no boundary code path runs.
# Fall back to the periodic timer only.
TOU_BOUNDARY_TICK_DELAY_S: Final = 5
DEFAULT_BILL_CYCLE_START_DAY: Final = 23

# ============================================================================
# Energy Savings Unification (cycle #7) — display-only accounting constants
# ============================================================================
# Noise floor for peak-avoidance accumulation. Ticks with less than this much
# "served locally" (kW) are ignored so sub-noise-floor Envoy jitter cannot
# credit spurious fractions of a cent every 5 minutes.
PEAK_AVOIDANCE_MIN_SERVED_KW: Final = 0.05

# Battery round-trip efficiency assumption used for arbitrage savings math.
# Mirrors the historical `EnergyCoord._ARBITRAGE_RTE` class attribute (kept
# in-place for byte-identity of the existing arbitrage code path); exposed
# here so the new savings-family sensors can label their methodology.
ARBITRAGE_RTE: Final = 0.90

# Battery storage mode values (Enphase Enpower)
BATTERY_MODE_SELF_CONSUMPTION: Final = "self_consumption"
BATTERY_MODE_SAVINGS: Final = "savings"
BATTERY_MODE_BACKUP: Final = "backup"

# ============================================================================
# Entity ID Defaults (Enphase/Envoy)
# ============================================================================

# v4.3.1: The 13 envoy-derived DEFAULT_*_ENTITY constants were REMOVED.
# Production code now requires entity IDs to come via config (auto-derived
# in __init__.py from CONF_ENERGY_ENVOY_ENTITY), and consumer call sites
# handle None gracefully. Validation in validate_envoy_config() +
# __init__.py B1 startup gate ensures EC isn't started without resolved
# envoy entities. Test fixtures defined locally in test files.
#
# Removed: DEFAULT_SOLAR_PRODUCTION_ENTITY, DEFAULT_GRID_CONSUMPTION_ENTITY,
#   DEFAULT_BATTERY_SOC_ENTITY, DEFAULT_BATTERY_POWER_ENTITY,
#   DEFAULT_NET_POWER_ENTITY, DEFAULT_LIFETIME_*_ENTITY (×6),
#   DEFAULT_BATTERY_CAPACITY_ENTITY, DEFAULT_CONSUMPTION_TODAY_ENTITY.

# EC-HOUSE-ENTITY-DEFAULTS-1 (Rev 5, 2026-10-13): house-specific entity-id
# literals removed. Names preserved so callers don't break; values are now
# None / []. On this house, the one-shot pin migration in __init__.py copies
# today's resolved values into options at setup, so behaviour is byte-identical.
# On a 2nd install, options stay empty and operators pick real entities.
# Enpower control entities
DEFAULT_STORAGE_MODE_ENTITY: Final = None
DEFAULT_RESERVE_SOC_ENTITY: Final = None
DEFAULT_GRID_ENABLED_ENTITY: Final = None
DEFAULT_CHARGE_FROM_GRID_ENTITY: Final = None

# Solcast forecast
DEFAULT_SOLCAST_TODAY_ENTITY: Final = None
DEFAULT_SOLCAST_TOMORROW_ENTITY: Final = None
DEFAULT_SOLCAST_REMAINING_ENTITY: Final = None
DEFAULT_SOLCAST_PEAK_ENTITY: Final = None
DEFAULT_SOLCAST_PEAK_TIME_ENTITY: Final = None

# Weather
DEFAULT_WEATHER_ENTITY: Final = None
# v4.7.x Cycle A: WeatherProviderManager — ranked-list provider with failover
DEFAULT_WEATHER_STALENESS_MAX_HOURS: Final = 6
DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F: Final = 5.0

# EVSE (Emporia WiFi chargers)
DEFAULT_EVSE_GARAGE_A_POWER_ENTITY: Final = None
DEFAULT_EVSE_GARAGE_B_POWER_ENTITY: Final = None

# Monitored plugs (L1 charger — switch-only, no power sensor)
DEFAULT_L1_CHARGER_ENTITIES: Final = []

# TOU rate file path
DEFAULT_TOU_RATE_FILE: Final = "universal_room_automation/tou_rates.json"

# ============================================================================
# Config Keys (Energy-specific options flow)
# ============================================================================

CONF_ENERGY_RESERVE_SOC: Final = "energy_reserve_soc"
CONF_ENERGY_DECISION_INTERVAL: Final = "energy_decision_interval"
CONF_ENERGY_BILL_CYCLE_DAY: Final = "energy_bill_cycle_day"
# EC-BILL-CYCLE-DAY-WIRED-1: bounds match the options-form selector (1..28 —
# every month has a 28th, so the cycle day always exists). Rung 1: a form
# guard, not policy. A malformed/missing value falls back to the default.
BILL_CYCLE_DAY_MIN: Final = 1
BILL_CYCLE_DAY_MAX: Final = 28


def clamp_bill_cycle_day(value: object) -> int:
    """Coerce the configured bill-cycle day to an int in [1, 28]."""
    try:
        v = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_BILL_CYCLE_START_DAY
    return max(BILL_CYCLE_DAY_MIN, min(BILL_CYCLE_DAY_MAX, v))

CONF_ENERGY_SOLAR_ENTITY: Final = "energy_solar_entity"
CONF_ENERGY_GRID_ENTITY: Final = "energy_grid_entity"
CONF_ENERGY_BATTERY_SOC_ENTITY: Final = "energy_battery_soc_entity"
CONF_ENERGY_BATTERY_POWER_ENTITY: Final = "energy_battery_power_entity"
CONF_ENERGY_NET_POWER_ENTITY: Final = "energy_net_power_entity"
CONF_ENERGY_STORAGE_MODE_ENTITY: Final = "energy_storage_mode_entity"
CONF_ENERGY_RESERVE_SOC_ENTITY: Final = "energy_reserve_soc_entity"
CONF_ENERGY_GRID_ENABLED_ENTITY: Final = "energy_grid_enabled_entity"
CONF_ENERGY_CHARGE_FROM_GRID_ENTITY: Final = "energy_charge_from_grid_entity"
CONF_ENERGY_SOLCAST_TODAY_ENTITY: Final = "energy_solcast_today_entity"
CONF_ENERGY_SOLCAST_REMAINING_ENTITY: Final = "energy_solcast_remaining_entity"
CONF_ENERGY_SOLCAST_TOMORROW_ENTITY: Final = "energy_solcast_tomorrow_entity"
CONF_ENERGY_WEATHER_ENTITY: Final = "energy_weather_entity"
# v4.7.x Cycle A: WeatherProviderManager ranked-list fallback providers
CONF_ENERGY_WEATHER_FALLBACK_1: Final = "energy_weather_fallback_1"
CONF_ENERGY_WEATHER_FALLBACK_2: Final = "energy_weather_fallback_2"
CONF_WEATHER_STALENESS_MAX_HOURS: Final = "weather_staleness_max_hours"
CONF_WEATHER_DIVERGENCE_THRESHOLD_F: Final = "weather_divergence_threshold_f"

# v5.15.x — Envoy Write-Verification + Cloud Read-Fallback
CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY: Final = "energy_cloud_reserve_oracle_entity"
CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY: Final = (
    "energy_cloud_charge_from_grid_oracle_entity"
)
CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY: Final = (
    "energy_cloud_storage_mode_oracle_entity"
)
CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY: Final = (
    "energy_cloud_battery_soc_fallback_entity"
)
DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY: Final = None
DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY: Final = None
DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY: Final = None
DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY: Final = None
DEFAULT_WRITE_VERIFY_WINDOW_S: Final = 900
MIN_WRITE_VERIFY_WINDOW_S: Final = 300
MAX_WRITE_VERIFY_WINDOW_S: Final = 1800
DEFAULT_SOC_LKG_MAX_AGE_S: Final = 300
# v5.17.5 A1 — wall-clock staleness gate for the cloud-fallback SOC tier.
# Mirrors DEFAULT_SOC_LKG_MAX_AGE_S but sized for cloud freshness: the
# Enphase cloud sensor updates every ~5 min, so we accept up to 2 update
# intervals (600s) before treating the reading as stale. A frozen-stale
# cloud SOC number (unknown/unavailable was the ONLY prior reject path,
# missing the "value hasn't changed in hours" case) would otherwise let
# the relaxed gate PROCEED on hours-old data.
DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S: Final = 600
DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT: Final = 3

# ---------------------------------------------------------------------------
# EC-DEGRADED-DATA-POLICY-1 Phase 1 (PLANNING_ec_degraded_data_phase1.md).
# ---------------------------------------------------------------------------
# D1 — local MQTT stream SOC tier (between native Envoy and LKG).
# Rung-1 kill switch: a trust decision on a breaker-safety input; flipping it
# must be reviewed. False = today's resolver (envoy → LKG → cloud), byte-
# identical. Ships DORMANT (operator Q1); flipped only on the D0 A/B GO.
SOC_STREAM_TIER_ENABLED: Final = False
# Rung-2 (config flow, per-deployment wiring). Unset = tier off. No house-
# specific default: a second install without a stream degrades to today.
CONF_ENERGY_STREAM_BATTERY_SOC_ENTITY: Final = "energy_stream_battery_soc_entity"
# Rung-2. A fast-changing sibling stream entity (e.g. stream grid power)
# proving the producer is alive. MANDATORY when DEFAULT_SOC_STREAM_MAX_AGE_S
# is 0 (freshness mode "b"); optional otherwise.
CONF_ENERGY_STREAM_COWITNESS_ENTITY: Final = "energy_stream_cowitness_entity"
# Rung-1 protocol window. > 0 = freshness mode "a" (stream `last_reported`
# age must be <= this); 0 = mode "b" (rely on the MQTT `expire_after`
# contract + a mandatory co-witness). Pending the D0-S1 measurement; ships
# at 0 (the fail-closed mode — the tier refuses without a co-witness).
DEFAULT_SOC_STREAM_MAX_AGE_S: Final = 0
# Rung-1 protocol window: the co-witness must have CHANGED (last_updated)
# within this many seconds (~2x the producer's expire_after of 60 s).
DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S: Final = 120
# Rung-1 anti-flap count: consecutive compared samples beyond the divergence
# threshold (REUSED DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT) that quarantine the
# stream, and consecutive agreeing samples that restore trust.
DEFAULT_SOC_STREAM_QUARANTINE_TICKS: Final = 2
# Rung-1 (plan review #2 R2-5): a compared sample counts only if it is at
# least this many seconds after the previous compared sample, so two
# back-to-back `get_status` renders cannot satisfy "2 samples".
DEFAULT_SOC_STREAM_COMPARE_MIN_SPACING_S: Final = 60
# D2a — rung-1 (plan review #1 C1-3: its OWN kill switch, decoupled from the
# blind-window guard's CONF_BLIND_WINDOW_MAX_DEFER_MIN). How long an
# arbitrage-held EVSE stays held on untrusted-SOC ticks before release is
# allowed — and then ONLY when charge-from-grid is provably off.
# Kill switch: <= 0 disables the untrusted-tier release refusal entirely.
DEFAULT_ARB_RELEASE_UNTRUSTED_MAX_DEFER_MIN: Final = 60
# D4 — rung-1 (operator Q4: code constant). Page the operator when the SOC
# tier has been untrusted this close to a higher-rate boundary.
# Kill switch: <= 0 never pages.
DEFAULT_SOC_UNTRUSTED_PAGE_LEAD_MIN: Final = 90
# D4 — rung-1 alert debounce (wall clock, not ticks). Filters the 66% of
# Envoy outages shorter than 2 min. 0 = page on the first untrusted tick.
DEFAULT_SOC_UNTRUSTED_PAGE_DWELL_MIN: Final = 10

# ENVOY-PRODUCTION-STALE-1 (Rev 5, clean-core fix-up 3) — shared power-read
# staleness thresholds consumed by BatteryStrategy._read_fresh_* wrappers
# (D2-A battery_soc, D3 solar, D4-D battery_power) AND by
# CostTracker._get_net_power (D4-E, billing gates net_power itself) AND by
# the D-OBS observability sensor.
#
# Rung 1 (module-level: change requires code review). Kill-switch: set the
# value to 0 to disable the staleness gate at that surface — the read
# wrappers AND the D-OBS classifier both honor `<= 0` as a bypass.
#
# NOTE: `DEFAULT_NET_POWER_MAX_AGE_S` is NOT applied to the
# BatteryStrategy.net_power_w PRODUCER (per Tier-3 MED-2: the breaker /
# arbitrage path must see net_power exactly as develop does). Only
# `CostTracker._get_net_power` and the D-OBS observability sensor read
# this const; the arbitrage / breaker path is fed by the pre-cycle
# ungated net_power_w property.
DEFAULT_NET_POWER_MAX_AGE_S: Final = 180
DEFAULT_BATTERY_POWER_MAX_AGE_S: Final = 180
DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S: Final = 180
DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S: Final = 300
STORAGE_MODE_LOCAL_TO_CLOUD: Final = {
    "self_consumption": "Self-Consumption",
    "backup": "Backup",
    "savings": "Savings",
    "full_backup": "Full Backup",
}
STORAGE_MODE_CLOUD_TO_LOCAL: Final = {
    v: k for k, v in STORAGE_MODE_LOCAL_TO_CLOUD.items()
}
WRITE_VERIFY_SURFACE_RESERVE: Final = "reserve_soc"
WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID: Final = "charge_from_grid"
WRITE_VERIFY_SURFACE_STORAGE_MODE: Final = "storage_mode"
WRITE_VERIFY_NM_SURFACES: Final = (
    WRITE_VERIFY_SURFACE_RESERVE,
    WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID,
    WRITE_VERIFY_SURFACE_STORAGE_MODE,
)

# ============================================================================
# Cloud-reliance hardening (v5.20.0 — Tier 3 elevated)
# ------------------------------------------------------------------
# D2 read-side telemetry divergence + tier-disagreement observability. Sits
# ABOVE the read-side SOC resolver (energy_battery.py:battery_soc, ~:650-758)
# but STRICTLY BENEATH the write-verify surface (energy_write_verify.py — that
# cycle owns command_trail / pending / conduct; this cycle owns SOC READ
# witness divergence and cloud settings-lag freshness).
#
# All knobs are rung-1 MODULE CONSTANTS per Numbers Get Knobs ladder:
# every one is a safety trade-off / anti-flap / alert cadence. None is a
# policy the operator legitimately tunes by observation. Change requires
# reviewed code change. Kill-switch: setting CONF_CLOUD_LAG_ALERT_S = 0
# disables cloud-lag NM alerting (attribute still populated for
# observability). Divergence detection is disabled by
# CONF_SOC_DIVERGENCE_THRESHOLD_PP = 0 (attribute cleared, no NM).
#
# NOTE (naming): CONF_ prefix per operator spec, mirrors CONF_CONDUCT_* in
# the behavioral-write-verify surface. These are NOT config-flow fields —
# they are module constants. The prefix is a name-collision anchor for
# audits.
#
# DISTINCTNESS from write-verify: write-verify already exposes reserve /
# storage_mode / charge_from_grid oracle command_trail on the battery
# strategy sensor. This cycle adds a NEW attribute namespace
# `soc_resolution` (dict) documenting the SOC READ side: which resolver
# tier served this tick, per-tier values + ages, cloud-vs-local pp
# divergence, and cloud settings-write freshness. No key overlap.
# ============================================================================
CONF_SOC_DIVERGENCE_THRESHOLD_PP: Final = 10  # planner default
CONF_SOC_DIVERGENCE_DWELL_MIN: Final = 5      # planner default, anti-flap
CONF_SOC_DIVERGENCE_HYSTERESIS_PP: Final = 2  # planner default
CONF_CLOUD_LAG_ALERT_S: Final = 1800          # planner default (30 min).
                                              # Kill-switch: 0 disables NM.
CONF_CLOUD_LAG_DWELL_MIN: Final = 5           # planner default, anti-flap

# ----------------------------------------------------------------------------
# v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — rung-1 → rung-2
# promotion: three of the D2 detection knobs above are now operator-settable
# via the config-flow `cloud_verification` section. The MODULE constants
# above remain the DEFAULTS (kill-switch semantics preserved: threshold 0 =
# detection off; lag 0 = alert off, attribute still populated). The keys
# follow the sibling `energy_cloud_*` naming convention already used by the
# cloud-verification oracle entity keys.
#
# NOT promoted: HYSTERESIS_PP + CLOUD_LAG_DWELL_MIN (both anti-flap safety
# bounds — leave as reviewed-code-change constants per the placement ladder).
# ----------------------------------------------------------------------------
CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP: Final = "energy_soc_divergence_threshold_pp"
CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN: Final = "energy_soc_divergence_dwell_min"
CONF_ENERGY_CLOUD_LAG_ALERT_S: Final = "energy_cloud_lag_alert_s"

# ============================================================================
# Behavioral write-verify (v5.19.0 — Tier 3)
# ------------------------------------------------------------------
# Two behavioral tripwires on top of the echo-verify surface:
#   D1 CONDUCT — reserve floor commanded but SOC below floor AND battery
#                actively discharging for N consecutive ticks under NO
#                explicitly-commanded-drain state → anomaly + NM.
#   D2 PENDING — divergence between commanded and hardware-observed
#                oracle age past pending-timeout → anomaly + bounded-
#                escalation retry ladder (15/30/60 min, max 3 attempts)
#                with hard stand-down after attempt 3.
#
# All knobs are rung-1 module constants per Numbers Get Knobs:
#   safety bounds + retry policy against an external API are NOT
#   dashboard-tunable. Change requires reviewed code change.
# Values are seated per the 2026-07-17 B0 probe report in
# `docs/planning/PLANNING_behavioral_write_verify.md`.
# ============================================================================

# --- D1 conduct thresholds ------------------------------------------
# 15-min steady deviation before alarming (3 × 5-min decision ticks).
# B0-D1: incident #5 lasted 56 min (11 ticks); all legit blips = 1 tick.
CONF_CONDUCT_N_TICKS: Final = 3
# W. Discharge magnitude threshold. B0-D1: legit discharges never sit
# above 500 W for 3 ticks at depth; incident #5 sustained 2.3-7.8 kW.
# NOTE on sign: `BatteryStrategy.battery_power_w` is NEGATED at read
# (positive=charging, negative=discharging — energy_battery.py:868-908).
# The conduct check compares `battery_power_w < -CONF_CONDUCT_DISCHARGE_EPSILON_W`.
CONF_CONDUCT_DISCHARGE_EPSILON_W: Final = 500
# pp. B0-D1: incident depth reached 14 pp; attain sawtooth peaked at 3 pp.
CONF_CONDUCT_SOC_DEADBAND_PCT: Final = 4
# Kill switch (still rung-1 — a false-positive here fires an ALERT NM;
# operator can disable in code if a live incident of that class occurs).
CONF_CONDUCT_ENABLED: Final = True

# --- D2 pending / retry-ladder --------------------------------------
# Divergence age (s) before attempt #1. B0-D2: apply-lag p90 = 461 s
# (~7.7 min); 15 min waits ~2× p90 so no retry ever races a normal apply.
CONF_PENDING_ATTEMPT_1_AGE_S: Final = 900
# Attempt #2 spacing (30 min from commanded).
CONF_PENDING_ATTEMPT_2_AGE_S: Final = 1800
# Attempt #3 spacing (60 min from commanded).
CONF_PENDING_ATTEMPT_3_AGE_S: Final = 3600
# Hard cap. Change requires review — increasing this reopens the
# incident-#2 shape (self-heal-vs-operator loop).
CONF_PENDING_MAX_ATTEMPTS: Final = 3
# Post-stand-down cool-off before a single fresh probe attempt (s).
CONF_PENDING_STANDDOWN_COOLOFF_S: Final = 10800  # 3h — mid of ratified 2-4h.
# Kill switch — disables detection AND retry ladder together.
CONF_PENDING_WATCHDOG_ENABLED: Final = True

# H1 (2026-07-13): cloud-first battery writes are now the system's write
# topology, not a per-user knob. All three battery control surfaces
# (reserve number, charge_from_grid switch, storage_mode select) route
# through the configured cloud oracle entities (enphase_ev IQ_* entities)
# because live evidence on firmware 8.3.5167 shows local Envoy writes are
# accepted-then-ignored — the hardware follows the Enphase cloud leg. The
# LOCAL entities remain configured for use as a SECONDARY WITNESS in the
# reversion sweep (see energy_write_verify.py:_sweep_surface). Not exposed
# in config flow — operator directive: "rip off the band aid".
ENERGY_CLOUD_FIRST_WRITES: Final = True

# EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 B2 (A4) — battery write-churn
# trip-wire. More than this many dispatched writes to ONE battery surface
# (reserve / charge_from_grid / storage_mode) inside a rolling window →
# one anomaly + one NM per surface per day. Alert only; no behaviour
# change. Rung 1 (an alert threshold against an external API's rate
# limits — review-gated). 12/h set from probe P3 (2026-10-04): measured
# peak CFG 5/h, reserve 9/h. Alarm fires at the 13th write in the window.
# `<= 0` = trip-wire off.
DEFAULT_BATTERY_WRITE_CHURN_MAX_PER_H: Final = 12
# Rolling window for the churn count (s). Rung 1 (protocol window).
BATTERY_WRITE_CHURN_WINDOW_S: Final = 3600

# EC-EV-TOGGLE-TRIPWIRE-1 — strategy EV charger flip-flop detector.
# When URA's battery/EV strategy toggles a single EVSE switch
# (switch.turn_on + switch.turn_off count equally) MORE than this many
# times inside the rolling window → one anomaly + one NM per EVSE per
# LOCAL day. Alert only; never changes actuation. Rung 1 (protocol
# threshold; change requires review). `<= 0` = trip-wire DISABLED
# (kill-switch). Default 2 is intentionally tight: a legitimate strategy
# flip for one charger in an hour is already unusual; the 10-01 night
# event cycled an 11.6 kW charger ~12x/2h and we want the first ~3rd
# transition inside the hour to alert.
DEFAULT_EV_TOGGLE_TRIPWIRE_MAX_PER_H: Final = 2
# Rolling window for the EV-toggle trip-wire (s). Rung 1 (protocol
# window). In-memory only — restart resets the deque; the per-day latch
# also resets on restart. Not persisted by design (one hour of state).
DEFAULT_EV_TOGGLE_TRIPWIRE_WINDOW_S: Final = 3600

# B5 (resilience A3, probe P3 GO 2026-10-04) — a cloud charge-from-grid
# `off` read counts as OFF for the phase-1 predicates (D2a provably-off,
# D2c start block) only when the cloud settings readback
# (`_read_cloud_settings_max_age_s`) is at most this old. Older (or no
# readable cloud setting) → the `off` is treated as UNKNOWN (D2b rule).
# Rung 1 (trust bound on a safety input). `<= 0` = gate off (today's
# behaviour: any `off` is believed).
DEFAULT_CFG_OFF_READ_MAX_AGE_S: Final = 300

# Review A M3 — the enphase_ev integration's own "last successful cloud
# update" timestamp sensor. enphase_ev only advances it on a NON-stale
# refresh (`coordinator.py` `_record_status_refresh_success`: guarded by
# `not context.status_used_stale`), whereas the settings entities'
# `last_reported` also advances when the integration re-serves cached /
# fallback data (`return fallback_data` on scheduler-unavailable). B5 reads
# this first; when the entity does not exist on this install it falls back
# to the settings-entity age (multi-home). House-specific default, same
# posture as the DEFAULT_CLOUD_* oracles. Probe P3 confirmed the id live.
DEFAULT_CLOUD_LAST_SUCCESS_ENTITY: Final = None
# EC-HOUSE-ENTITY-DEFAULTS-1 fix-up: the last-successful-update sensor is a
# role-keyed option (pinned on this house by the one-shot migration).
CONF_ENERGY_CLOUD_LAST_SUCCESS_ENTITY: Final = "energy_cloud_last_success_entity"

# Review B MED / D-MED-4 — a persisted charge-from-grid command-ledger
# entry (`wv_commanded_ledger`) whose `commanded_at` is older than this is
# NOT restored at boot. The KV row is re-saved every 15 min, so the row age
# gate alone never expires a days-old `True`; a stale `True` would then
# hold EVs breaker-paused (D2b) after every restart. Rung 1 (restart-safety
# bound; review-gated). `<= 0` = always restore (pre-fix behaviour).
CFG_LEDGER_RESTORE_MAX_AGE_H: Final = 12

# Review D D-HIGH-1 — scope of the untrusted-SOC EV turn-on refusal.
# "arbitrage_release" = only the D2a arbitrage release refuses on an
# untrusted SOC tier. "all" (OPERATOR RULING 2026-10-04) = EVERY L2 EVSE and
# L1 plug turn-on refuses while the tick's SOC verdict is untrusted: DP
# reversion + must-start-by (`_ev_start_hold_label`), and in energy_pool via
# `_soc_untrusted_start_refused`: off-peak ensure-on (TOU-pause end),
# excess-solar, drain release, fill-priority release, grid-cap release,
# release_all_{tou,fill_priority,grid_cap}, load-shed restore. Kill switch:
# set back to "arbitrage_release". Rung 1 (trust decision on a safety input).
EV_UNTRUSTED_SOC_START_REFUSAL_SCOPE: Final = "all"

# Operator ruling 2026-10-04 (option 1): turn-on paths EXEMPT from the
# untrusted-SOC refusal above — the off-peak ensure-on (L2 + L1; TOU-pause
# end / overnight start) and should-start-by (must-start-by) deadline starts
# proceed under an untrusted SOC (car-charge liveness outranks the SOC
# doubt). Every OTHER gate on them (CFG breaker / grid_charge_on /
# `_ev_start_hold_label` grid leg / arbitrage / blind-window / drain holds)
# still applies. Empty set = refuse on every path. Rung 1 (trust decision).
EV_UNTRUSTED_SOC_EXEMPT_PATHS: Final = frozenset(
    {"offpeak_ensure_on", "should_start_by"}
)

# ============================================================================
# Inclement-weather detection + TOU/solar-horizon-aware battery hold
# (Robust Inclement-Weather Reserve cycle — supersedes has_storm_forecast()).
# Replaces Enphase Storm Guard reliance with a local alert + condition
# fusion producing a graduated hold-depth decision parameterized by
# (confidence tier, current TOU period, solar recovery horizon).
# ============================================================================

# Primary surface (4 knobs)
CONF_INCLEMENT_NWS_ALERTS_ENTITY: Final = "inclement_nws_alerts_entity"
# EC storm Stage B D-B5: the legacy key below is RETIRED (removed from the
# options flow; the product table + the Stage E operator selection replace
# it). KEEP+DOCUMENT: the constant (and its default list) are kept ONLY so
# `EnergyCoordinator._check_legacy_threat_list` can detect a customized
# stored value (repair issue) — never read by the decision path. Stage E
# E1.9 deleted the warn-min-severity key/default/options (0 readers).
CONF_INCLEMENT_POWER_THREAT_EVENTS: Final = "inclement_power_threat_events"
CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD: Final = "inclement_grid_precharge_on_hold"

# Advanced subsection (3 knobs)
CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: Final = "inclement_partial_hold_reserve_floor"
CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT: Final = "inclement_recoverable_surplus_margin_pct"
CONF_INCLEMENT_CONDITION_CORROBORATION_MODE: Final = "inclement_condition_corroboration_mode"

# Hidden / hardcoded (not exposed in v1 surface — see D-H / plan §Config)
CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION: Final = "inclement_watch_requires_corroboration"

# Section key for the collapsed "Advanced" config-flow subsection (FIN-1).
INCLEMENT_ADVANCED_SECTION: Final = "inclement_advanced"

# Defaults
# D-B (RETIRED, KEEP+DOCUMENT): the v5.5.0 power-threat default list. Read
# only by the legacy repair check (a stored list equal to this is silent).
DEFAULT_INCLEMENT_POWER_THREAT_EVENTS: Final = [
    "Tornado",
    "Severe Thunderstorm",
    "Ice Storm",
    "Winter Storm",
    "High Wind",
    "Extreme Wind",
    "Hurricane",
    "Blizzard",
]
# D-I: never burn grid energy to backup-fill on a watch (solar-first).
DEFAULT_INCLEMENT_GRID_PRECHARGE_ON_HOLD: Final = False
# D-E (FIN-1): reserve floor URA preserves during a partial_hold.
DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: Final = 50
# D-F (FIN-2): %SOC margin projected solar surplus must EXCEED the
# permitted discharge before that discharge counts as "recoverable".
DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT: Final = 5
# D-J: local condition cross-check mode.
DEFAULT_INCLEMENT_CONDITION_CORROBORATION_MODE: Final = "majority"
# D-H: low-certainty (watch) alerts require ≥1 corroborating provider.
DEFAULT_INCLEMENT_WATCH_REQUIRES_CORROBORATION: Final = True
# D-K: condition-only path decay after providers clear (minutes).
DEFAULT_INCLEMENT_CONDITION_DECAY_MINUTES: Final = 30

# EC storm/blind Stage A D-A5 (PLANNING_ec_storm_and_blind_decisions.md,
# Q2 ruling). Blind full-hold floor when SOC is unknown on every tier:
# `max(reserve_soc, partial_floor, slider)`. Rung 3 — the live value is the
# Number entity `InclementBlindFullHoldFloorNumber`, persisted ONLY in the
# CM `entry.options` under this key and re-read every tick by
# `BatteryStrategy._inclement_config()` (options-read path: the key is in
# `_NO_LIVE_ATTR_KEYS` + `OPTIONS_RELOAD_SUPPRESS_KEYS`; no setter). The
# constant is the default. Kill semantics: 100 = legacy pin (every blind
# full hold pins 100); 0 = the floor collapses to max(reserve_soc,
# partial_floor).
CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: Final = "inclement_blind_full_hold_floor"
INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT: Final = 60

# EC storm/blind Stage A D-A3, Q6 ruled A (2026-10-16). Rung 1.
# False = while fully blind, a manual reserve lower below the registered
# floor is re-asserted next tick (sighted-path parity). True = a manual
# lower (write-leg state below the last stamped desire and not the value
# URA last dispatched) ends decision-side blind reserve writes for the
# rest of the blind episode. Escape under either: the EC enable switch.
BLIND_RESPECT_MANUAL_LOWER: Final = False

# ----------------------------------------------------------------------------
# EC storm/blind Stage B (PLANNING_ec_storm_and_blind_decisions.md §6 D-B1..B7)
# All rung 1 unless stated: decision topology / evidence-set values whose
# change must be reviewed.
# ----------------------------------------------------------------------------
# D-B2 / D-B2a product table. Rows: (NWS code | None, exact event name
# (case-folded match), class, polygon_local, precharge_eligible).
# class: "warn" / "watch" (HOLD) or "notice" (shown + logged, never a hold).
# Unlisted products are gated out. Only the P3-verified codes are coded
# (AUDIT_ec_storm_stage0_probes.md P3); every other row matches by exact
# name only. precharge_eligible (D-B2a evidence table): may this product
# grid-charge (never changes class/tier/floor). Polygon rows are eligible
# ONLY through the capped verified-local immediate leg.
INCLEMENT_PRODUCT_TABLE: Final[tuple[tuple[str | None, str, str, bool, bool], ...]] = (
    # HOLD-warn
    (None, "Winter Storm Warning", "warn", False, True),
    (None, "Ice Storm Warning", "warn", False, True),
    (None, "Hard Freeze Warning", "warn", False, True),
    (None, "Extreme Cold Warning", "warn", False, True),
    (None, "Wind Chill Warning", "warn", False, True),
    (None, "Blizzard Warning", "warn", False, True),
    ("TOW", "Tornado Warning", "warn", True, True),
    ("SVW", "Severe Thunderstorm Warning", "warn", True, True),
    (None, "Extreme Wind Warning", "warn", True, True),
    (None, "Hurricane Warning", "warn", False, False),
    ("TRW", "Tropical Storm Warning", "warn", False, False),
    # HOLD-watch
    (None, "Winter Storm Watch", "watch", False, True),
    (None, "Hard Freeze Watch", "watch", False, True),
    (None, "Extreme Cold Watch", "watch", False, True),
    (None, "Wind Chill Watch", "watch", False, True),
    (None, "Tornado Watch", "watch", False, False),
    (None, "Severe Thunderstorm Watch", "watch", False, False),
    (None, "Hurricane Watch", "watch", False, False),
    (None, "Tropical Storm Watch", "watch", False, False),
    # EC storm Stage E E0 (NWS vocabulary re-sync, 2026-10-17): the NWS no
    # longer issues Hard Freeze / Wind Chill products (api.weather.gov
    # /alerts/types); Freeze Warning now carries the hard-freeze hazard and
    # Freeze Watch is its precursor. Watch class: partial hold on bottom-rate
    # frost nights, released at top rate unless the forecast confirms
    # (<= FORECAST_FREEZE_CONFIRM_F, air temp). Freeze Watch is name-only
    # (FZA unverified, P3 policy above); drift records the real code.
    ("FZW", "Freeze Warning", "watch", False, True),
    (None, "Freeze Watch", "watch", False, True),
    # NOTICE (never a hold)
    ("WIY", "Wind Advisory", "notice", False, False),
    ("HWW", "High Wind Warning", "notice", False, False),
    ("HWA", "High Wind Watch", "notice", False, False),
    ("WWY", "Winter Weather Advisory", "notice", False, False),
    (None, "Wind Chill Advisory", "notice", False, False),
    (None, "Cold Weather Advisory", "notice", False, False),
)
# Stage E E0 KEEP+DOCUMENT: the Hard Freeze Warning/Watch, Wind Chill
# Warning/Watch and Wind Chill Advisory rows above are RETIRED NWS names (not
# in NWS_WEATHER_EVENT_NAMES). Harmless: they still match replays. They are
# outside the operator selection domain (Stage E §E1.2): table behaviour
# always, never shown in the form, never an override delta.

# Stage E E1.2 (rung 1): the selectable NWS vocabulary -- the WEATHER subset
# of `GET https://api.weather.gov/alerts/types` (111 event names, fetched
# 2026-10-17). Excluded: marine / coastal / Pacific products (Gale, Storm,
# Storm Surge, Hurricane Force Wind, Typhoon, seas / surf / spray, Small
# Craft, Special Marine, Brisk Wind, Low Water, Coastal / Lakeshore Flood,
# Beach Hazards, Rip Current, Tsunami), statements and outlooks (Special /
# Severe Weather Statement, Hazardous Weather Outlook, Short Term Forecast,
# Flood / Flash Flood Statement, Hydrologic Outlook, Tropical Cyclone Local
# Statement, Marine Weather Statement), civil / 911 / test / administrative
# messages (incl. Earthquake Warning, Fire Warning, Hazardous Materials,
# Nuclear Power Plant, Radiological Hazard, Shelter In Place, Evacuation
# Immediate, Law Enforcement, Local Area Emergency, Blue Alert, Child
# Abduction, Civil Danger / Emergency), and geologic products (Volcano
# Warning, Ashfall Advisory / Warning). Refreshed only by a reviewed change
# (no runtime fetch); `test_vocab_snapshot_covers_table` fails loudly when a
# non-retired table row leaves it.
NWS_WEATHER_EVENT_NAMES: Final[tuple[str, ...]] = (
    "Air Quality Alert",
    "Air Stagnation Advisory",
    "Avalanche Advisory",
    "Avalanche Warning",
    "Avalanche Watch",
    "Blizzard Warning",
    "Blowing Dust Advisory",
    "Blowing Dust Warning",
    "Cold Weather Advisory",
    "Dense Fog Advisory",
    "Dense Smoke Advisory",
    "Dust Advisory",
    "Dust Storm Warning",
    "Extreme Cold Warning",
    "Extreme Cold Watch",
    "Extreme Fire Danger",
    "Extreme Heat Warning",
    "Extreme Heat Watch",
    "Extreme Wind Warning",
    "Fire Weather Watch",
    "Flash Flood Warning",
    "Flash Flood Watch",
    "Flood Advisory",
    "Flood Warning",
    "Flood Watch",
    "Freeze Warning",
    "Freeze Watch",
    "Freezing Fog Advisory",
    "Frost Advisory",
    "Heat Advisory",
    "High Wind Warning",
    "High Wind Watch",
    "Hurricane Warning",
    "Hurricane Watch",
    "Ice Storm Warning",
    "Lake Effect Snow Warning",
    "Lake Wind Advisory",
    "Red Flag Warning",
    "Severe Thunderstorm Warning",
    "Severe Thunderstorm Watch",
    "Snow Squall Warning",
    "Tornado Warning",
    "Tornado Watch",
    "Tropical Storm Warning",
    "Tropical Storm Watch",
    "Wind Advisory",
    "Winter Storm Warning",
    "Winter Storm Watch",
    "Winter Weather Advisory",
)
# Stage E E1.6 (rung 2): operator alert selection over the product table,
# stored as OVERRIDES (never a snapshot) in the CM entry.options. Each is a
# list of canonical NWS_WEATHER_EVENT_NAMES spellings, compared case-folded;
# empty lists = the table defaults. Read per tick by
# `BatteryStrategy._inclement_config` (and by the outage ledger via
# `EnergyCoordinator._get_cm_options`); listed in `_NO_LIVE_ATTR_KEYS` and
# `OPTIONS_RELOAD_SUPPRESS_KEYS` (a save does not reload the CM). Buy kill
# switch: `inclement_grid_precharge_on_hold` False.
CONF_INCLEMENT_HOLD_ADDED: Final = "inclement_hold_added"
CONF_INCLEMENT_HOLD_REMOVED: Final = "inclement_hold_removed"
CONF_INCLEMENT_BUY_ADDED: Final = "inclement_buy_added"
CONF_INCLEMENT_BUY_REMOVED: Final = "inclement_buy_removed"
# Form-only keys (two multi-selects); popped by the submit handler after the
# deltas are computed, never stored.
CONF_INCLEMENT_HOLD_PRODUCTS: Final = "inclement_hold_products"
CONF_INCLEMENT_BUY_PRODUCTS: Final = "inclement_buy_products"
# D-B1 / Q7 (ruled "notice"): what a polygon product does when the point
# feed is NOT polygon-exact. "table" keeps the table tier; "notice" demotes.
INCLEMENT_UNVERIFIED_POLYGON_TIER: Final = "notice"
# D-B2a: evidence that `?point=` is polygon-exact (P2(b), n=1). False =
# polygon rows follow INCLEMENT_UNVERIFIED_POLYGON_TIER and the immediate
# top-up leg is off.
INCLEMENT_POINT_FEED_POLYGON_EXACT: Final = True
# D-B2a: minutes after a verified-local polygon warning's start (per alert
# ID) that grid top-up may run, any TOU. 0 = immediate leg off. Measured
# per-storm union <= 100 min (IEM archive, plan "Cap, measured").
INCLEMENT_POLYGON_TOPUP_MAX_MIN: Final = 60
# D-B1: cap for an alert with neither Ends nor Expires (end = start + this).
INCLEMENT_ALERT_MAX_HOLD_H: Final = 48
# D-B3: feed staleness bound on the `last_updated` sibling's last_changed.
# P2(d)/(e): healthy poll gap max 302 s, unavailable drop max 245 s, so any
# value <= 310 self-triggers; 900 = ~3x margin. MUST stay > 310.
NWS_ALERTS_STALE_S: Final = 900
# D-B6: the prepare window (how far ahead of Onset a prepare alert is seen).
# Stage E E2 re-scoped it to the BUY HORIZON: the furthest slot a pre-onset
# grid buy may be scheduled in (T - H <= this). 0 = D-B6 off (both legs).
INCLEMENT_PREONSET_LEAD_H: Final = 12
# Stage E E2.3 (rung 1; it prices peak arbitrage): with no buy scheduled the
# pre-onset floor starts at T - this (one winter top-rate block, ~$1/event of
# forgone discharge, OQ-7). Effective value = min(this, LEAD_H). 0 = the
# floor exists only with a buy schedule.
INCLEMENT_PREONSET_FLOOR_LEAD_H: Final = 4
# Stage E E2.2 (rung 1; it sizes paid import): assumed grid-charge rate in
# SOC points per hour. Operator 2026-10-17 "charge from grid in 1-2 hours"
# (80 pp in ~1.6 h; OQ-6). UNMEASURED (no recorder grid-charge episode);
# below the 77 pp/h hardware ceiling. Smaller = more hours scheduled.
INCLEMENT_GRID_CHARGE_PP_PER_H: Final = 50
# Stage E E2.2 (rung 1): slack hours added to a needed buy (rate / SOC
# error). 0 = exact. Added only when a buy is needed.
INCLEMENT_PREONSET_BUY_MARGIN_H: Final = 1
# D-B6 rung 3: pre-onset floor slider default (Number entity
# `InclementPreonsetFloorNumber`, options key below, read per tick by
# `_inclement_config`; same options-read path as the blind slider).
CONF_INCLEMENT_PREONSET_FLOOR: Final = "inclement_preonset_floor"
INCLEMENT_PREONSET_FLOOR_PCT: Final = 80
# D-B7: Enphase Storm Guard trip-wire target (notice only, never a decision
# input), resolved at run time by entity-registry lookup — no house
# entity_id literal (EC-HOUSE-ENTITY-DEFAULTS-1; same pattern as the Stage L
# calendar resolution): the one `switch.*` entity of this platform whose
# unique_id ends with the suffix (live 2026-10-16: platform enphase_ev,
# unique_id enphase_ev_site_<id>_storm_guard). "" platform = trip-wire off.
STORM_GUARD_PLATFORM: Final = "enphase_ev"
STORM_GUARD_UNIQUE_ID_SUFFIX: Final = "_storm_guard"

# ----------------------------------------------------------------------------
# EC storm/blind Stage C (D-C2 forecast confirmation; rung 1). Thresholds
# for `inclement.forecast_confirms`. A forecast is raise-only corroboration:
# it can corroborate a watch and is REQUIRED for any zone-product grid buy
# (INV-6(vii)); it never demotes and never creates a hold.
# ----------------------------------------------------------------------------
# D-C1 hourly refresh cadence (minutes), per Stage 0 P1 (OWM hourly).
FORECAST_REFRESH_MIN: Final = 30
# Outlook older than this (minutes) = None (no corroboration, no buy).
FORECAST_STALE_MIN: Final = 120
# Stage E E3 (rung 1): bound on one `weather.get_forecasts` call (daily and
# hourly), so a hung provider can never hold the WPM-C1 `_refresh_lock`
# (parent §16 B-LOW-5). A timeout = that provider's fetch failed this pass.
FORECAST_FETCH_TIMEOUT_S: Final = 20
# Bounds the evaluated hazard window for a long Ends.
FORECAST_WINDOW_MAX_H: Final = 48
# NWS hard-freeze threshold (deg F): freeze/cold family confirms at min <= this.
FORECAST_FREEZE_CONFIRM_F: Final = 28
# Frozen-precip threshold (deg F) for the winter-storm family.
FORECAST_WINTER_STORM_CONFIRM_F: Final = 32
# Max precip probability (%) in the window for winter-storm (convective uses
# FORECAST_CONVECTIVE_PRECIP_CONFIRM_PCT below, operator 2026-10-17).
# NOT fitted: no recorded hourly PoP series exists yet (Stage 0 P1 /
# addendum: one live sample only). 50 is the plan §7 placeholder; revisit
# from the nws_alert ledger + OWM history once a season accrues.
FORECAST_PRECIP_CONFIRM_PCT: Final = 50
# Winter-storm AND convective precip leg for hours whose provider has NO
# precipitation_probability (Open-Meteo carries only an amount; coordinator
# provider policy 2026-10-16). Hourly amount (mm) treated as "precip
# forecast". NOT fitted (no history yet); revisit with the PCT value.
FORECAST_PRECIP_CONFIRM_MM: Final = 1.0
# Convective family (Tornado / Severe Thunderstorm / Hurricane / Tropical
# Storm / Extreme Wind) confirm rule. Operator 2026-10-17 (verbatim): "this is
# storm conditions right not just rainy weather? I think the rain chance
# should be higher and it should be storm conditions. I don't want grid buys
# on mere rain." Convective confirms iff the window carries a STORM condition
# AND a strong rain signal (probability >= this, else amount >=
# FORECAST_PRECIP_CONFIRM_MM on no-probability hours). NOT fitted (no hourly
# PoP history yet); operator-set placeholder, revisit with the PCT above.
FORECAST_CONVECTIVE_PRECIP_CONFIRM_PCT: Final = 70
# Storm conditions that count for the convective confirm. Operator 2026-10-17
# ruling above; NOT fitted. Deliberately EXCLUDES "pouring" / "snowy-rainy"
# (heavy rain is not a storm). Kept separate from weather_manager.
# _STORM_CONDITIONS, which is shared with condition corroboration.
FORECAST_CONVECTIVE_STORM_CONDITIONS: Final[frozenset[str]] = frozenset({
    "lightning", "lightning-rainy", "hail", "tornado", "hurricane",
    "exceptional",
})
# D-C2 forecast family per product (exact event name, case-folded at use).
# Rung 1 (reviewed set, not a tunable): products whose hazard IS the
# apparent temperature (wind chill / extreme cold). Their freeze-family
# confirm reads the forecast's min apparent temp when present (OWM and
# Open-Meteo hourly both carry `apparent_temperature`), else air temp.
# Operator 2026-10-17 (Review A A-INFO-1).
FORECAST_APPARENT_TEMP_PRODUCTS: Final[frozenset[str]] = frozenset({
    "Extreme Cold Warning",
    "Extreme Cold Watch",
    "Wind Chill Warning",
    "Wind Chill Watch",
    # Stage E E0: Wind Chill Advisory successor (apparent-temperature hazard).
    "Cold Weather Advisory",
})
INCLEMENT_FORECAST_FAMILY: Final[dict[str, str]] = {
    "Hard Freeze Warning": "freeze",
    "Hard Freeze Watch": "freeze",
    # Stage E E0: the current NWS freeze products (air temperature) and the
    # Wind Chill Advisory successor (apparent temperature, notice by default;
    # the family only matters when the operator widens it to hold, and it
    # can never buy: INV-7(c)).
    "Freeze Warning": "freeze",
    "Freeze Watch": "freeze",
    "Cold Weather Advisory": "freeze",
    "Extreme Cold Warning": "freeze",
    "Extreme Cold Watch": "freeze",
    "Wind Chill Warning": "freeze",
    "Wind Chill Watch": "freeze",
    "Winter Storm Warning": "winter_storm",
    "Winter Storm Watch": "winter_storm",
    "Ice Storm Warning": "winter_storm",
    "Blizzard Warning": "winter_storm",
    "Tornado Watch": "convective",
    "Severe Thunderstorm Watch": "convective",
    "Tornado Warning": "convective",
    "Severe Thunderstorm Warning": "convective",
    "Extreme Wind Warning": "convective",
    "Hurricane Warning": "convective",
    "Hurricane Watch": "convective",
    "Tropical Storm Warning": "convective",
    "Tropical Storm Watch": "convective",
}

# NWS severity ordering (CAP standard, low → high). Attrs only
# (`inclement._severity_rank` -> max_severity); never a gate.
INCLEMENT_SEVERITY_ORDER: Final = ["Unknown", "Minor", "Moderate", "Severe", "Extreme"]
# Operator-facing select option keys for CONDITION_CORROBORATION_MODE.
INCLEMENT_CONDITION_CORROBORATION_OPTIONS: Final = ["any", "majority", "unanimous"]

# v4.7.1 Cycle B: Dynamic Preset Override Source
# Bucket boundary deltas (apparent_high - zone_home_cool_high)
CONF_DYNAMIC_PRESET_DELTA_COOL_MAX: Final = "dynamic_preset_delta_cool_max"
CONF_DYNAMIC_PRESET_DELTA_MILD_MAX: Final = "dynamic_preset_delta_mild_max"
CONF_DYNAMIC_PRESET_DELTA_HOT_MAX: Final = "dynamic_preset_delta_hot_max"
# Runtime tunable knobs
CONF_DYNAMIC_PRESET_DWELL_MINUTES: Final = "dynamic_preset_dwell_minutes"
CONF_DYNAMIC_PRESET_HYSTERESIS_F: Final = "dynamic_preset_hysteresis_f"
# Master kill switch (persisted in RestoreEntity; also readable via CM options)
CONF_DYNAMIC_PRESET_ENABLED: Final = "dynamic_preset_enabled"
# Notification on bucket transition (opt-in, default OFF)
CONF_DYNAMIC_PRESET_NOTIFY_ON_TRANSITION: Final = "dynamic_preset_notify_on_transition"
# Defaults
DEFAULT_DYNAMIC_PRESET_DELTA_COOL_MAX: Final = -2.0
DEFAULT_DYNAMIC_PRESET_DELTA_MILD_MAX: Final = 8.0
DEFAULT_DYNAMIC_PRESET_DELTA_HOT_MAX: Final = 18.0
DEFAULT_DYNAMIC_PRESET_DWELL_MINUTES: Final = 60
DEFAULT_DYNAMIC_PRESET_HYSTERESIS_F: Final = 2.0
DEFAULT_DYNAMIC_PRESET_ENABLED: Final = False
DEFAULT_DYNAMIC_PRESET_NOTIFY_ON_TRANSITION: Final = False

# v4.7.17.2: Operator-facing DPM knobs (the only 2 surfaces the operator
# tunes for cool/hot-day behavior). Both house-wide, both °F, both 0.0-3.0
# range. Defaults from operator's framing memo example: "70-75 → 70-76 on
# cool day, 70-74 on hot day" → each knob = 1.0°F adjustment.
CONF_DPM_COOL_DAY_RELAX_F: Final = "dpm_cool_day_relax_f"
DEFAULT_DPM_COOL_DAY_RELAX_F: Final = 1.0  # °F added to cool_high on cool days
CONF_DPM_HOT_DAY_TIGHTEN_F: Final = "dpm_hot_day_tighten_f"
DEFAULT_DPM_HOT_DAY_TIGHTEN_F: Final = 1.0  # °F subtracted from cool_high on hot days

# v4.7.17.2: Internal-only constants for the rolling-median mechanic.
# NOT exposed in config_flow, NOT operator-tunable. Code-only adjustment
# requires a deploy. Calibration rationale per planning doc §3:
#  - 14-day window: long enough to smooth single-day forecast noise,
#    short enough to track seasonal transitions
#  - 7-day minimum: emit nothing below this (median would be too noisy)
#  - 2.0°F dead zone around median: prevents flicker when relative_delta
#    hovers near zero
DPM_ROLLING_WINDOW_DAYS: Final = 14
DPM_ROLLING_WINDOW_MIN_DAYS: Final = 7
DPM_RELATIVE_DELTA_DEADZONE_F: Final = 2.0

# v4.7.18 D3: rolling-window ring cap widened 14 → 90 days. The 14-day
# median used for relax/tighten math is unchanged (preserved by slicing
# `ring[-DPM_ROLLING_WINDOW_DAYS:]` inside `_rolling_median_apparent_high`
# — load-bearing). The wider 90-day window backs `_p25_apparent_high()`
# (25th percentile) which feeds the v4.7.18 self-tuning `relax_ceiling`
# auto mode. p25 requires DPM_P25_MIN_DAYS=30 entries before it emits;
# below the threshold the ceiling falls back to 90.0°F (moderate).
DPM_ROLLING_WINDOW_MAX_DAYS: Final = 90
DPM_P25_MIN_DAYS: Final = 30

# v4.7.18 D4: relax-ceiling mode (operator-facing dropdown on Surface 1).
# String enum — see _resolve_relax_ceiling() in dynamic_preset.py.
# Defaults to "auto" (p25 of 90-day apparent_high ring). Manual buckets
# are named (Conservative=85°F, Moderate=90°F, Aggressive=95°F) per
# operator framing — no raw threshold Number, no internal mechanics
# leaked to the operator surface.
CONF_DPM_RELAX_CEILING_MODE: Final = "dpm_relax_ceiling_mode"
DEFAULT_DPM_RELAX_CEILING_MODE: Final = "auto"
DPM_RELAX_CEILING_MODE_AUTO: Final = "auto"
DPM_RELAX_CEILING_MODE_CONSERVATIVE_85: Final = "conservative_85"
DPM_RELAX_CEILING_MODE_MODERATE_90: Final = "moderate_90"
DPM_RELAX_CEILING_MODE_AGGRESSIVE_95: Final = "aggressive_95"
DPM_RELAX_CEILING_MODE_OFF: Final = "off"
DPM_RELAX_CEILING_MODES: Final = (
    DPM_RELAX_CEILING_MODE_AUTO,
    DPM_RELAX_CEILING_MODE_CONSERVATIVE_85,
    DPM_RELAX_CEILING_MODE_MODERATE_90,
    DPM_RELAX_CEILING_MODE_AGGRESSIVE_95,
    DPM_RELAX_CEILING_MODE_OFF,
)
# Auto fallback when ring has < DPM_P25_MIN_DAYS entries (cold start)
# and for unrecognized mode strings (defensive).
DPM_RELAX_CEILING_AUTO_FALLBACK_F: Final = 90.0

# v4.7.17.2 fix-up (B-H2): canonical DPM skip-reason taxonomy. Single
# source of truth — referenced from the producer (dynamic_preset.py
# docstrings + return paths) and the consumer (energy.py
# _dynamic_preset_skip_reasons comment). Adding a new reason here is
# the gate: tests assert producer-return-set equals this frozenset, so
# drift is caught at test time. Keep alphabetical for diff stability.
DPM_SKIP_REASONS: Final[frozenset[str]] = frozenset({
    "canonical_label_mismatch",
    "dwell_pending",
    "evaluation_failed",
    "gate_disabled",
    "home_range_not_configured",
    "no_forecast_delta",
    "unknown_bucket",
    "winter_season",  # v4.7.17.2: calendar-direct winter gate
})

# Priority (lower than guest_mode=50; higher = wins)
DYNAMIC_PRESET_PRIORITY: Final = 30
GUEST_MODE_PRIORITY: Final = 50
# Minimum deadband for cool_low ≤ cool_high validation
MIN_DEADBAND: Final = 2.0
# Buckets
BUCKET_COOL: Final = "cool"
BUCKET_MILD: Final = "mild"
BUCKET_HOT: Final = "hot"
BUCKET_EXTREME: Final = "extreme"
BUCKET_NAMES: Final = (BUCKET_COOL, BUCKET_MILD, BUCKET_HOT, BUCKET_EXTREME)

# Per-zone dynamic preset CONF keys (stored in zones dict of Zone Manager entry)
CONF_ZONE_DYNAMIC_PRESET_ENABLED: Final = "zone_dynamic_preset_enabled"
CONF_ZONE_DYNAMIC_PRESET_OFFSET: Final = "zone_dynamic_preset_offset"
CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST: Final = "zone_dynamic_preset_reset_offset_guest"
CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED: Final = "zone_dynamic_preset_sleep_enabled"
# v4.7.4 D3: opt-in flag — when False, runtime derives bucket cells from baseline+offset
CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS: Final = "zone_dynamic_preset_customize_buckets"
# Per-bucket range keys: "zone_dynamic_preset_<bucket>_home_cool_low/high"
# and "zone_dynamic_preset_<bucket>_sleep_cool_low/high"
CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_LOW: Final = "zone_dynamic_preset_cool_home_low"
CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_HIGH: Final = "zone_dynamic_preset_cool_home_high"
CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_LOW: Final = "zone_dynamic_preset_mild_home_low"
CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_HIGH: Final = "zone_dynamic_preset_mild_home_high"
CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_LOW: Final = "zone_dynamic_preset_hot_home_low"
CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_HIGH: Final = "zone_dynamic_preset_hot_home_high"
CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_LOW: Final = "zone_dynamic_preset_extreme_home_low"
CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_HIGH: Final = "zone_dynamic_preset_extreme_home_high"
CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_LOW: Final = "zone_dynamic_preset_cool_sleep_low"
CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_HIGH: Final = "zone_dynamic_preset_cool_sleep_high"
CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_LOW: Final = "zone_dynamic_preset_mild_sleep_low"
CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_HIGH: Final = "zone_dynamic_preset_mild_sleep_high"
CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_LOW: Final = "zone_dynamic_preset_hot_sleep_low"
CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_HIGH: Final = "zone_dynamic_preset_hot_sleep_high"
CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_LOW: Final = "zone_dynamic_preset_extreme_sleep_low"
CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_HIGH: Final = "zone_dynamic_preset_extreme_sleep_high"

# Guest mode actuation (Phase 1 schema — owned by dynamic_preset plan as shared schema)
CONF_GUEST_MODE_ACTUATION_ENABLED: Final = "guest_mode_actuation_enabled"
CONF_PRESET_OVERRIDES: Final = "preset_overrides"
CONF_ZONE_GUEST_MODE_OPT_OUT: Final = "zone_guest_mode_opt_out"
# Per-zone guest mode override CONF keys
CONF_ZONE_GUEST_HOME_COOL_LOW: Final = "zone_guest_home_cool_low"
CONF_ZONE_GUEST_HOME_COOL_HIGH: Final = "zone_guest_home_cool_high"
CONF_ZONE_GUEST_SLEEP_COOL_LOW: Final = "zone_guest_sleep_cool_low"
CONF_ZONE_GUEST_SLEEP_COOL_HIGH: Final = "zone_guest_sleep_cool_high"

CONF_ENERGY_SOLAR_CLASSIFICATION_MODE: Final = "energy_solar_classification_mode"
CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT: Final = "energy_solar_threshold_excellent"
CONF_ENERGY_SOLAR_THRESHOLD_GOOD: Final = "energy_solar_threshold_good"
CONF_ENERGY_SOLAR_THRESHOLD_MODERATE: Final = "energy_solar_threshold_moderate"
CONF_ENERGY_SOLAR_THRESHOLD_POOR: Final = "energy_solar_threshold_poor"

# EVSE charge-onset gate (evse-charge-onset cycle). HH:MM string; blank ⇒
# disabled (baseline: overnight `battery_out_of_capacity` release fires
# as soon as SOC hits reserve, regardless of wall-clock). When set (default
# "01:00"), the OVERNIGHT-reserve leg of `determine_battery_drain_actions`
# holds until the session-anchored onset instant is reached (see
# EVChargerController._charge_onset_reached). The daytime-solar
# `soc_recovered` leg is UNGATED. Persisted on entry.options (sole source
# of truth); no RestoreEntity — re-seed pattern.
CONF_ENERGY_EVSE_CHARGE_ONSET_TIME: Final = "energy_evse_charge_onset_time"
DEFAULT_ENERGY_EVSE_CHARGE_ONSET_TIME: Final = "01:00"

# Rev-5 session-anchor age bound RETIRED in Rev 6 (no anchor to age).
# Retained here as a comment for grep-anchor: DRAIN_SESSION_MAX_RESTORE_AGE_H.

# evse-charge-onset Rev 6 (D-A) — dedicated ENABLE toggle. Reviewers
# proved HA TimeSelector + `time.set_value` both REJECT blank/None, so
# the Rev-5 "blank = off" kill was unreachable. A separate boolean gives
# the operator a real off switch that survives restart via the
# `EVChargeOnsetEnabledSwitch` (RestoreEntity + coord attr write-through).
# Ships DORMANT (v3: DEFAULT False) — operator flips on after live
# checkpoint via `switch.ura_ev_charge_onset_enabled` (which routes
# through `EnergyCoordinator.set_ev_charge_onset_enabled` fanning out
# to BOTH controllers).
CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED: Final = "energy_evse_charge_onset_enabled"
DEFAULT_ENERGY_EVSE_CHARGE_ONSET_ENABLED: Final = False  # v3 (funnel) — SHIP DORMANT; operator enables deliberately

# evse-charge-onset Rev 6 (D-B) — BOUNDED HOLD WINDOW replaces the Rev-5
# session-anchor + lookback mechanism. Hold the overnight leg ONLY when
# `now < onset_instant AND (onset_instant - now) <= ONSET_MAX_HOLD_H`.
# 8h anchors to the operator's real overnight span (reserve-hit typically
# 20:00-01:00 = 5h ahead of a 01:00 onset). A daytime reserve-hit at
# 10:00 with onset 01:00 is 15h ahead of NEXT 01:00 → outside the window
# → NOT held, byte-identical to baseline (kills the Rev-5 "18h daytime
# hold" review finding, kills the LOOKBACK cliff). After tonight's onset
# (say now=02:00, onset=01:00) → next 01:00 is 23h away → also NOT held.
# Rung-1 safety/allocation bound — CODE tunable only. Setting to a very
# large value (e.g. 24) effectively disables the ceiling; the sane KILL
# is the ENABLE toggle above.
ONSET_MAX_HOLD_H: Final = 8.0

CONF_ENERGY_EVSE_A_ENTITY: Final = "energy_evse_a_entity"
CONF_ENERGY_EVSE_B_ENTITY: Final = "energy_evse_b_entity"
# v5.12.0 SPAN circuit-identity re-key (companion to circuit baseline scope
# migration): the SPAN breaker `switch.` entity_id for each EVSE is
# rename-fragile (same failure mode as circuit baselines). Surface as options
# so the operator can retarget after a SPAN-app rename without a code change.
# Backward-compat: unset → falls back to DEFAULT_EVSE_ENTITIES in energy_pool.
CONF_ENERGY_EVSE_A_SPAN_BREAKER: Final = "energy_evse_a_span_breaker"
CONF_ENERGY_EVSE_B_SPAN_BREAKER: Final = "energy_evse_b_span_breaker"
# EC-HOUSE-ENTITY-DEFAULTS-1 fix-up: the remaining per-charger entity roles
# (formerly literals in energy_pool.DEFAULT_EVSE_ENTITIES). Unset = that role
# is not wired; a charger with no role configured at all is not managed.
CONF_ENERGY_EVSE_A_SWITCH_ENTITY: Final = "energy_evse_a_switch_entity"
CONF_ENERGY_EVSE_B_SWITCH_ENTITY: Final = "energy_evse_b_switch_entity"
CONF_ENERGY_EVSE_A_ENERGY_TODAY_ENTITY: Final = "energy_evse_a_energy_today_entity"
CONF_ENERGY_EVSE_B_ENERGY_TODAY_ENTITY: Final = "energy_evse_b_energy_today_entity"
CONF_ENERGY_EVSE_A_ENERGY_MONTH_ENTITY: Final = "energy_evse_a_energy_month_entity"
CONF_ENERGY_EVSE_B_ENERGY_MONTH_ENTITY: Final = "energy_evse_b_energy_month_entity"
CONF_ENERGY_EVSE_A_CURRENT_LIMIT_ENTITY: Final = "energy_evse_a_current_limit_entity"
CONF_ENERGY_EVSE_B_CURRENT_LIMIT_ENTITY: Final = "energy_evse_b_current_limit_entity"
# EC-HOUSE-ENTITY-DEFAULTS-1 fix-up: pool pump roles (formerly literals in
# energy_pool.DEFAULT_POOL_*). Unset = no pool management.
CONF_ENERGY_POOL_SPEED_ENTITY: Final = "energy_pool_speed_entity"
CONF_ENERGY_POOL_POWER_ENTITY: Final = "energy_pool_power_entity"
CONF_ENERGY_L1_CHARGER_ENTITIES: Final = "energy_l1_charger_entities"
CONF_ENERGY_TOU_RATE_FILE: Final = "energy_tou_rate_file"
# TOU-FILE-TOGGLE-AND-LOUD-FAILURE-1: explicit kill switch for TOU rate-file
# ingestion. Default True so behaviour is byte-identical to pre-toggle
# (file present + valid => file wins). Setting False makes the loader skip
# all filesystem access and use the built-in PEC table.
CONF_ENERGY_TOU_RATE_FILE_ENABLED: Final = "energy_tou_rate_file_enabled"
DEFAULT_ENERGY_TOU_RATE_FILE_ENABLED: Final = True

# v4.0.12: Envoy auto-derive — one entity picker derives all Envoy entities
CONF_ENERGY_ENVOY_ENTITY: Final = "energy_envoy_entity"
CONF_ENERGY_BATTERY_CAPACITY_ENTITY: Final = "energy_battery_capacity_entity"
CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY: Final = "energy_lifetime_consumption_entity"
CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY: Final = "energy_lifetime_production_entity"
# EC-SOLAR-LIFETIME-COUNTER-FLAP-1 (v5.103.82) — rung 1 (module constant):
# a lifetime production reading (snapshot or current) below
# (1 - this) x the in-memory high-water mark is a counter flap, not a real
# value; the day's solar AND consumption are written NULL (no legacy
# net-import fallback, no forecast learning) rather than a silent 0.0. Safety bound on a monotonic counter — changing it should
# require review. 1.0 disables the check (nothing is ever below 0 x hwm).
LIFETIME_PRODUCTION_MAX_DROP_FRACTION: Final = 0.5
# energy_state KV key recording which entity the persisted production
# snapshot was read from (snapshot provenance across entity swaps).
ENERGY_STATE_KEY_PRODUCTION_SNAPSHOT_ENTITY: Final = "lifetime_production_snapshot_entity"
CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY: Final = "energy_lifetime_net_import_entity"
CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY: Final = "energy_lifetime_net_export_entity"
CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY: Final = "energy_lifetime_battery_charged_entity"
CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY: Final = "energy_lifetime_battery_discharged_entity"
CONF_ENERGY_CONSUMPTION_TODAY_ENTITY: Final = "energy_consumption_today_entity"

# Solar classification modes
SOLAR_CLASS_MODE_AUTOMATIC: Final = "automatic"
SOLAR_CLASS_MODE_CUSTOM: Final = "custom"

# ============================================================================
# E6: Load Shedding + Constraint Config
# ============================================================================

CONF_ENERGY_LOAD_SHEDDING_ENABLED: Final = "energy_load_shedding_enabled"
CONF_ENERGY_LOAD_SHEDDING_THRESHOLD: Final = "energy_load_shedding_threshold_kw"
CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES: Final = "energy_load_shedding_sustained_minutes"
CONF_ENERGY_LOAD_SHEDDING_MODE: Final = "energy_load_shedding_mode"

CONF_ENERGY_CONSTRAINT_COAST_OFFSET: Final = "energy_constraint_coast_offset"
# RETIRED 2026-09-18: consumer branch deleted from
# `_update_hvac_constraint`; TOMBSTONED to keep stored config entries
# from stranding. See card EC-GRID-ANTICIPATORY-PRECOOL-GAP-1.
CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET: Final = "energy_constraint_precool_offset"
CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET: Final = "energy_constraint_preheat_offset"
CONF_ENERGY_CONSTRAINT_SHED_OFFSET: Final = "energy_constraint_shed_offset"
CONF_ENERGY_PREHEAT_TEMP_THRESHOLD: Final = "energy_preheat_temp_threshold"

# ============================================================================
# Off-Peak Drain Targets (% SOC) — based on tomorrow's solar forecast
# ============================================================================
# Aggressive drain: off-peak grid at $0.043 is 3.7x cheaper than peak ($0.162).
# Draining to low SOC overnight maximizes room for tomorrow's solar absorption.
# Risk is minimal: arbitrage catches poor-forecast + low-SOC scenarios.
# When SOC > target: drain stored solar (free energy) during cheap off-peak
# When SOC <= target: hold and import cheap grid at $0.043/kWh

DEFAULT_OFFPEAK_DRAIN_EXCELLENT: Final = 10
DEFAULT_OFFPEAK_DRAIN_GOOD: Final = 15
DEFAULT_OFFPEAK_DRAIN_MODERATE: Final = 20
DEFAULT_OFFPEAK_DRAIN_POOR: Final = 30
# 5th quality bucket — mirrors `poor` default (30) per the OFFPEAK-DRAIN-
# VERYPOOR-SLIDER-1 card. Operator may tune toward 40 by observation.
DEFAULT_OFFPEAK_DRAIN_VERY_POOR: Final = 30
DEFAULT_OFFPEAK_DRAIN_UNKNOWN: Final = 40

CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT: Final = "energy_offpeak_drain_excellent"
CONF_ENERGY_OFFPEAK_DRAIN_GOOD: Final = "energy_offpeak_drain_good"
CONF_ENERGY_OFFPEAK_DRAIN_MODERATE: Final = "energy_offpeak_drain_moderate"
CONF_ENERGY_OFFPEAK_DRAIN_POOR: Final = "energy_offpeak_drain_poor"
CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR: Final = "energy_offpeak_drain_very_poor"

# ============================================================================
# Grid Charge Arbitrage
# ============================================================================
# When tomorrow is poor/very_poor solar and SOC < trigger, charge from grid
# overnight at off-peak rate ($0.043) to avoid importing at mid-peak/peak later.

# v4.5.0 D2: DEFAULT_ARBITRAGE_SOC_TRIGGER and CONF_ENERGY_ARBITRAGE_SOC_TRIGGER
# removed — gate is now forecast-class only (no SOC trigger). The constant
# below is retained as a documented removed-field marker for the migration
# helper which strips the legacy CONF key from entry.options.
DEFAULT_ARBITRAGE_SOC_TARGET: Final = 80
CONF_ENERGY_ARBITRAGE_ENABLED: Final = "energy_arbitrage_enabled"
# Legacy key — kept on this line ONLY so the v4.5.0 D2 migration helper
# can pop it from entry.options. No production code reads this key.
CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY: Final = "energy_arbitrage_soc_trigger"
CONF_ENERGY_ARBITRAGE_SOC_TARGET: Final = "energy_arbitrage_soc_target"

# v4.5.0 D1/D2: rename of arbitrage_target → peak_buffer_target.
# Keeps DEFAULT_ARBITRAGE_SOC_TARGET as the canonical default for now;
# D2 swaps the public name. The number-entity hard min/max for the new
# live-tunable charge lead time are set per the plan's physics-floor
# analysis: 84 min minimum to charge 10→80% at 20 kW × 0.9 RTE; the 120
# floor adds ~36 min margin against Enphase stalls. Default 360 (6 h)
# biases earlier-start so same-day target windows benefit from intraday
# Solcast updates accumulated since sunrise.
DEFAULT_PEAK_BUFFER_TARGET: Final = DEFAULT_ARBITRAGE_SOC_TARGET  # 80
DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = 360
MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = 120
MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = 720
CONF_ENERGY_PEAK_BUFFER_TARGET: Final = "energy_peak_buffer_target"
CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = (
    "energy_arbitrage_charge_lead_time_min"
)
# v4.5.0.2: defensive grid-import guard for arbitrage CHARGE phase.
# If net_power_w during CHARGE exceeds this threshold, abort the chunk
# (set chunk_completed=True, return WAIT). One-shot per chunk — no
# saw-tooth flap. Acts as a software safety rail until v4.5.1 adds
# proper charge-rate control via barneyonline/ha-enphase-energy HACS.
#
# v4.5.0.3: default lowered 20 → 12 kW. Sized for the 60A DER breaker
# (BR260) on the IQ System Controller 3/3G — Enphase's smaller breaker
# option, common on residential installs. NEC 80% continuous-load
# derating: 60A × 240V × 0.8 = 11.52 kW; round up to 12 kW. With this
# default, the guard fires on a slow ramp before sustained import
# crosses the breaker rating. Installs with 80A breakers can raise to
# 15 kW; installs with 100A+ should set explicitly via
# CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW. (Note: even at the right
# threshold, the guard is tick-frequency limited — 5 min between ticks
# means a fast 30 kW ramp can trip the breaker before the next check.
# barneyonline rate control in v4.5.1 is the real fix; this guard is
# the safety rail.)
#
# Plan's original 20 kW assumption was based on the (incorrect) "solo
# battery 20 kW is within breaker capacity" reasoning — discovered live
# during v4.5.0 deploy when user's 8x IQ Battery 5P stack ramped to
# ~32 kW and tripped the breaker twice.
DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW: Final = 12.0
CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW: Final = (
    "energy_arbitrage_grid_import_guard_kw"
)
# v5.5.x cycle: expose the guard in config flow with an enable toggle,
# default OFF. Mirrors `CONF_ENERGY_GRID_IMPORT_CAP_ENABLED` — no
# DEFAULT_* const, the False default is applied at read sites and in
# the config-flow schema. When disabled, `BatteryStrategy` collapses
# the effective threshold to `float('inf')` so every consumer (helper
# + inline `snap[0] > ...` checks + chunk-lock) naturally no-ops.
# Justification: operator's Enphase battery firmware auto-curtails on
# breaker size, so the software guard is redundant for safety and was
# harming summer pre-charge (aborting the whole arbitrage chunk on
# >12 kW transient import). Guard kept as dormant opt-in.
CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED: Final = (
    "energy_arbitrage_grid_import_guard_enabled"
)
# Consecutive guard trips required before the chunk is locked. The
# battery_power CT lags net_power by one Envoy poll at CHARGE entry, so a
# single tick can read full inrush on net while battery still reads ~0 →
# a one-shot lock would lose the whole off-peak chunk to sensor lag. Two
# consecutive trips means a genuine house+EV overdraw still locks (one
# extra ~30s tick of import is well within the physical breaker margin),
# while a lone CT-lag tick is absorbed.
ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK: Final = 2
# v4.5.0 D3: multi-day Solcast lookback (D+2 awareness). Default OFF
# during calibration cycle per Open Question #3.
DEFAULT_SOLCAST_DAY_3_ENTITY: Final = None
CONF_ENERGY_SOLCAST_DAY_3_ENTITY: Final = "energy_solcast_day_3_entity"
CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED: Final = "energy_multi_day_horizon_enabled"

# ============================================================================
# EVSE Refinement
# ============================================================================

DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD: Final = 95
DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD: Final = 5.0
EVSE_CHARGING_POWER_THRESHOLD: Final = 100  # watts
EVSE_ESTIMATED_POWER_W: Final = 7600  # L2 charger estimated draw when sensor unavailable
CONF_ENERGY_EXCESS_SOLAR_ENABLED: Final = "energy_excess_solar_enabled"
CONF_ENERGY_EXCESS_SOLAR_SOC: Final = "energy_excess_solar_soc"
CONF_ENERGY_EXCESS_SOLAR_KWH: Final = "energy_excess_solar_kwh"

# LKG wave 1 D2 — solar production upper envelope. Config-flow field
# (rung 2, per operator ruling 2026-07-23): the installed inverter
# nameplate is per-install physical structure the operator sets ONCE
# at commissioning, not a comfort knob the operator tunes by observation
# (rung 3). NOT a module constant (rung 1) because the operator MUST be
# able to set this without a code change — a new install has a
# different array size, and hard-coding would require a patch release
# for every new deployment. See planning §3.2 + operator rulings appendix.
CONF_ENERGY_SOLAR_NAMEPLATE_W: Final = "energy_solar_nameplate_w"
# Theoretical array max: 19.4 kW (operator's installed fleet, 2026-07-23).
# The envelope's UPPER bound must reflect what the array CAN produce
# (not the highest observed clip). Under-sizing here would falsely admit
# excess-solar; over-sizing widens the envelope but is caught downstream
# by the SOC-lower guard and the mains-export witness.
#
# NO KILL SWITCH: the feature is always-on whenever Envoy is blind and a
# recent LKG exists. Setting the nameplate low does NOT disable the
# envelope — the config-flow selector clamps to min=1000 W (see
# config_flow.py NumberSelectorConfig for CONF_ENERGY_SOLAR_NAMEPLATE_W),
# and if the field is unwired on an older entry the battery method falls
# back to this default. To gate admits behind a real production floor
# see SOLAR_ENVELOPE_ADMIT_FLOOR_W (rung-1 safety-adjacent const).
DEFAULT_ENERGY_SOLAR_NAMEPLATE_W: Final[int] = 19400

# EV Battery Drain Protection (v4.2.17)
DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD: Final = 50
CONF_ENERGY_EV_BATTERY_DRAIN_SOC: Final = "energy_ev_battery_drain_soc"
EV_BATTERY_DRAIN_COOLDOWN_SECONDS: Final = 3600  # 1 hour after manual override

# v4.7.6 D1: Hybrid manual-override detection grace window. Skip the
# manual-override branch for `EV_PAUSE_DISPATCH_GRACE_SECONDS` after URA
# dispatches switch.turn_off so HA's state cache (which can briefly read
# is_on=True post-dispatch) doesn't trigger a false cooldown.
EV_PAUSE_DISPATCH_GRACE_SECONDS: Final = 30.0

# v4.7.6 D2: Fill-priority pause defaults.
# When SOC < fill_priority_soc AND solar forecast remaining >= excess_solar_kwh,
# URA pauses EVSEs/L1 plugs so the home battery fills first.
DEFAULT_FILL_PRIORITY_SOC: Final = 80
DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH: Final = 1.0
CONF_ENERGY_FILL_PRIORITY_SOC: Final = "energy_fill_priority_soc"

# EV-FILL-PRIORITY-SOC-CHATTER-1: resume → re-pause SOC hysteresis.
# After a fill-priority RESUME on the SOC-reached edge, suppress re-pause
# until SOC falls below (fill_priority_soc - DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT).
# The FIRST pause below fill_priority_soc (no live latch) is unchanged.
# Forecast-decay resumes do NOT set the latch; the forecast side has its
# own band (DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH).
# 0 disables (legacy single-threshold behaviour). Rung 1 (module constant):
# a stability margin, not per-deployment policy — change requires review.
# Read at CALL time by energy_pool (module-attribute access), never bound
# at import.
DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT: Final = 3

# evse-offpeak-fill-release D2: minimum TIME-windowed expected solar surplus
# (in %SOC, from `BatteryStrategy.expected_solar_surplus_now_pct`) for the EV
# battery-drain high-SOC release (`soc_recovered`) to be considered "solar is
# actively replenishing". Below this floor (e.g. at night, where the daylight-
# overlap term is ~0) the high-SOC release is suppressed and the ONLY release
# is the reserve-gated `battery_out_of_capacity` → overnight EV charge is
# guaranteed grid, not battery discharge. Small/conservative on purpose.
DEFAULT_EV_SOLAR_REPLENISH_SURPLUS_PCT: Final = 1.0

# v4.7.6 D1/D3.4: Per-EVSE / per-plug `self_modulates` config key suffix.
# Stored on the per-EVSE config dict at EVPool._evse[evse_id]["self_modulates"];
# defaults to False (smart manual-override detection on).
CONF_EVSE_SELF_MODULATES_SUFFIX: Final = "_self_modulates"

# v4.7.6 D6.3: L1 plug power estimate when no power sensor exists.
# ~12 A @ 120 V; conservative for dumb plug fallback display.
L1_ESTIMATED_POWER_W: Final = 1440

# EV Grid Import Cap (v4.0.18)
DEFAULT_GRID_IMPORT_CAP_KW: Final = 8.0
DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW: Final = 1.0
CONF_ENERGY_GRID_IMPORT_CAP_ENABLED: Final = "energy_grid_import_cap_enabled"
CONF_ENERGY_GRID_IMPORT_CAP_KW: Final = "energy_grid_import_cap_kw"

# v4.2.0: Circuit monitoring configurability
CONF_ENERGY_CIRCUIT_INTEGRATIONS: Final = "energy_circuit_integrations"
CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES: Final = "energy_circuit_extra_entities"
CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN: Final = "energy_circuit_autodiscover_span"
CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES: Final = "energy_circuit_exclude_entities"
CONF_ENERGY_GENERATOR_ENTITY: Final = "energy_generator_entity"

# v4.2.0: Direct grid import/export sensors (e.g., Emporia mains)
CONF_ENERGY_GRID_IMPORT_ENTITY: Final = "energy_grid_import_entity"
CONF_ENERGY_GRID_EXPORT_ENTITY: Final = "energy_grid_export_entity"

# v4.2.17: Utility company net energy meter (SmartHub, etc.)
CONF_ENERGY_UTILITY_METER_ENTITY: Final = "energy_utility_meter_entity"

# EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 (PLANNING_ec_bill_divergence_from_
# smarthub_stats.md): utility-side hourly long-term statistic ids (external
# statistics, e.g. ``smarthub:smarthub_energy_sensor_<acct>_<loc>``). Read
# LIVE from the CM options on every refresh (B-M1 fix-up; NOT in
# EC_CONSTRUCTION_ENTITY_KEYS, in OPTIONS_RELOAD_SUPPRESS_KEYS — no reload). Blank import id = feature OFF (kill switch; the legacy
# utility-meter-entity branch runs unchanged). Export blank = export treated 0.
CONF_ENERGY_UTILITY_IMPORT_STATISTIC_ID: Final = "energy_utility_import_statistic_id"
CONF_ENERGY_UTILITY_EXPORT_STATISTIC_ID: Final = "energy_utility_export_statistic_id"
# Rung 1 (module const): the utility data lands once a day, so an hourly
# re-read is ample and bounds recorder load. Not operator policy.
UTILITY_STATS_REFRESH_MIN: Final = 60
# Rung 1: normal newest-row age is 13-38 h (daily import, measured 2026-10-19);
# 48 h flags a missed daily import. Display flag only.
UTILITY_STATS_STALE_H: Final = 48
# Rung 1: a local date counts as complete when the utility series holds its
# local 23:00 hour row (DST-safe: 23- and 25-row days both carry 23:00).
UTILITY_DAY_COMPLETE_LAST_HOUR: Final = 23
# Rung 1: relative float tolerance when comparing an EC day's average import
# rate against the TOU engine's floor (avoids counting a day priced exactly
# at the floor as under-priced because of float noise).
UTILITY_RATE_FLOOR_REL_TOL: Final = 1e-6

# EC-BILL-PREDICTION-FORECAST-1 (PLANNING_ec_bill_prediction_forecast.md, D0
# winner P3). All rung 1: display-only feature, changes should be reviewed.
# Learning gate: no prediction before this many local days into the cycle
# (D0: P3 at day 3 is ~13% MAPE, comparable to day 7). Replaces the literal 7.
BILL_FORECAST_MIN_DAYS: Final = 3
# Fallback remainder rate when a remaining day has no same-weekday history:
# mean utility net cost over this many days before the utility window end.
BILL_FORECAST_TRAILING_DAYS: Final = 7
# Same-weekday mean looks back this many weeks (D0 backtest used 4).
BILL_FORECAST_DOW_WEEKS: Final = 4
# Horizons (local day of cycle) scored by the accuracy ledger.
BILL_ACCURACY_HORIZONS: Final = (7, 14, 21)
# Ledger keeps at most this many cycles (one year).
BILL_LEDGER_MAX_CYCLES: Final = 12
# A closed cycle not covered by the utility series within this many days of
# the next cycle start is written unscored (one week of SmartHub outage).
BILL_LEDGER_SCORE_DEADLINE_DAYS: Final = 7
# energy_state key holding the ledger JSON.
BILL_FORECAST_LEDGER_KEY: Final = "bill_forecast_ledger"

# ─────────────────────────────────────────────────────────────────────────────
# EC billing from Emporia daily counters (PLANNING_ec_billing_emporia_counters)
# ─────────────────────────────────────────────────────────────────────────────
# "Bill from" named-bucket select. Auto = detect counter sensors by uom and
# use them when fresh; Meter totals = force counter accrual (fail-fast when
# unavailable); Power readings = legacy power-integration path (today's
# behaviour, byte-identical when unset).
CONF_ENERGY_BILLING_SOURCE: Final = "energy_billing_source"
BILLING_SOURCE_AUTO: Final = "auto"
BILLING_SOURCE_METER: Final = "meter_totals"
BILLING_SOURCE_POWER: Final = "power_readings"
DEFAULT_ENERGY_BILLING_SOURCE: Final = BILLING_SOURCE_AUTO

# Backstop clamp for `energy_daily` writes. Rung 1 (safety bound).
MAX_PLAUSIBLE_DAILY_KWH: Final = 240.0
MAX_PLAUSIBLE_DAILY_SOLAR_KWH: Final = 120.0

# Counter accrual knobs — rung 1 (protocol / safety).
# Service cap in kW used as per-tick jump bound, scaled by elapsed hours.
# A 6h gap-recovery delta at 5 kW (30 kWh) is accepted; a 5-min tick at 10
# kWh is rejected. Retires the former flat MAX_COUNTER_JUMP_KWH.
MAX_COUNTER_KW_PLAUSIBLE: Final = 60.0
# Window to consider the counter "stuck" (no value drop, no advance).
COUNTER_STUCK_WINDOW_S: Final = 1800
# Day-level fallback flag threshold: measured staleness exceeding this at
# midnight rollover marks `energy_daily.billing_source = 'counter_gap'`.
COUNTER_OUTAGE_FALLBACK_HRS: Final = 4
# Value-drop reset detection epsilon.
RESET_EPSILON_KWH: Final = 0.1
# Counter-mode max-age for the cached net-kW inference. Emporia daily
# counters update every ~15 min (not every tick), so the Envoy-tuned
# `DEFAULT_NET_POWER_MAX_AGE_S=180` is wrong here — "unchanged for 3 min"
# is NOT a stale counter. Must comfortably cover one update cadence +
# jitter without accepting an outage as fresh (rung 1: safety-adjacent,
# tied to vendor polling, change requires code review).
COUNTER_NET_POWER_MAX_AGE_S: Final = 1200  # 20 min

# ─────────────────────────────────────────────────────────────────────────────
# EVSE solar-following amp modulation (SolarFollowController, D1)
# See docs/planning/PLANNING_evse_solar_follow_amps.md §8.
# ─────────────────────────────────────────────────────────────────────────────
# Amp bounds — safety-derived; changes MUST require code review.
SOLAR_FOLLOW_MIN_AMPS: Final[int] = 6            # J1772 pilot floor
SOLAR_FOLLOW_MAX_AMPS: Final[int] = 48           # DERIVED: 80% of 60A branch — DO NOT RAISE
SOLAR_FOLLOW_RESTORE_AMPS: Final[int] = 48       # capture-rejection + boot-backstop restore value
SOLAR_FOLLOW_PHASES: Final[int] = 1              # single-phase 240 V
SOLAR_FOLLOW_CAPTURE_SANITY_A: Final[int] = 20   # below this at capture time → use RESTORE_AMPS
SOLAR_FOLLOW_DEADBAND_A: Final[int] = 1
SOLAR_FOLLOW_UP_STEP_A: Final[int] = 4
SOLAR_FOLLOW_UP_MIN_TICKS: Final[int] = 3        # default for Number override; §5.10
SOLAR_FOLLOW_TICK_S: Final[int] = 60
SOLAR_FOLLOW_VERIFY_S: Final[int] = 8            # readback delay via async_call_later
SOLAR_FOLLOW_MAX_WRITES_PER_HOUR: Final[int] = 60
SOLAR_FOLLOW_STALE_GRACE_S: Final[int] = 300     # blind grace before WARNING
SOLAR_FOLLOW_BLIND_EXIT_S: Final[int] = 900      # restore-and-quiet after prolonged blind
SOLAR_POWER_FRESH_S: Final[int] = 180            # per-EVSE power reading freshness (uses last_updated)
SOLAR_FOLLOW_GRID_FRESH_S: Final[int] = 180      # grid source freshness, last_reported (INV-SF-10). 1.5x Emporia p90 (120s); tighter than 300 because a false-demote is a benign handoff to the fresher Envoy fallback, while too-high sizes on stale data (D-HIGH-4)
# CF-5 fix-up: bound the STALE_POWER hold. Rung 1 (module constant — safety
# knob, review-gated). After this many consecutive stale-power ticks the bay
# stops being HELD at its current amps and is treated as non-drawing (targets
# MIN). Guards INV-SF-4 against a wedged Emporia power sensor pinning 48 A
# indefinitely — a money leak at peak tariff. At 60 s tick × 5 = 5 min max
# hold; comfortably above the p90-250 s power sensor lag but tight enough to
# reject a truly stuck reading.
SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS: Final[int] = 5

# EVSE-SOLAR-IDLE-DERESERVE-1: after this many consecutive ticks in which a
# bay is `eligible` but not `drawing` and not in `stale_power`, drop its
# MIN-amp reservation from `parked_w`. Prevents a finished/absent bay from
# starving a charging sibling of surplus (parked_w inflates by
# SOLAR_FOLLOW_MIN_AMPS * 240 * PHASES per idle bay). At 60 s tick × 10 =
# ~10 min — comfortably above plug-in ramp-up (a bay still ramping from
# claim should NOT be de-reserved; a too-LOW value here would starve a
# just-plugged bay of its foothold).
#
# stale-power exemption is BOUNDED, not unconditional: a bay with a wedged
# power sensor is exempt from idle-counting only while it remains in the
# stale_power set, and CF-5 demotes it after SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS
# consecutive stale-power ticks. So a wedged charging bay CAN be de-reserved
# after roughly SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS + SOLAR_FOLLOW_IDLE_DERESERVE_TICKS
# ticks total (~15 ticks at defaults) — the exemption defers de-reserve, it
# does not veto it (A-MED-2).
#
# Kill-switch: set to a very large value (e.g. 100000) to disable de-reserve
# entirely and revert to pre-cycle behavior. NEVER set to <= 0 — the counter
# comparison is `>=`, so a value of 0 (or negative) trivially puts every
# eligible bay (including drawing bays whose counter is the default 0) into
# `long_idle`, breaking the eligible/drawing/idle distinction the allocator
# depends on (A-LOW-1).
# Rung: module constant — behavioral allocation bound whose change should
# require review.
SOLAR_FOLLOW_IDLE_DERESERVE_TICKS: Final[int] = 10

# Grid entities for solar-follow (deliberately NOT reusing CONF_ENERGY_GRID_IMPORT_ENTITY).
CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY: Final = "energy_solar_follow_grid_entity"
CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY: Final = "energy_solar_follow_grid_fallback_entity"
DEFAULT_SOLAR_FOLLOW_GRID_ENTITY: Final = None
DEFAULT_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY: Final = None

# CF-10 fix-up: the operator knob (rung 3) also lives here as a CONF key so
# EnergyCoordinator can read the options value at __init__ time, making the
# options-persisted value authoritative regardless of Number entity timing.
CONF_ENERGY_EXCESS_SOLAR_CONFIRM: Final = "energy_excess_solar_confirm"

# Load shedding defaults
DEFAULT_LOAD_SHEDDING_THRESHOLD_KW: Final = 5.0
DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES: Final = 15
LOAD_SHEDDING_MODE_FIXED: Final = "fixed"
LOAD_SHEDDING_MODE_AUTO: Final = "auto"
LOAD_SHEDDING_AUTO_MIN_DAYS: Final = 30
LOAD_SHEDDING_AUTO_PERCENTILE: Final = 90  # 90th percentile of peak import

# Constraint offset defaults (degrees F)
DEFAULT_CONSTRAINT_COAST_OFFSET: Final = 3.0
# RETIRED 2026-09-18: see CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET.
DEFAULT_CONSTRAINT_PRECOOL_OFFSET: Final = -2.0
DEFAULT_CONSTRAINT_PREHEAT_OFFSET: Final = 2.0
DEFAULT_CONSTRAINT_SHED_OFFSET: Final = 5.0
DEFAULT_PREHEAT_TEMP_THRESHOLD: Final = 40.0  # F — forecast low below this triggers pre_heat

# Load shedding priority order (cascade)
LOAD_SHEDDING_PRIORITY: Final = ["pool", "ev", "smart_plugs", "hvac"]


# ============================================================================
# Envoy Auto-Derive (v4.0.12)
# ============================================================================

_ENVOY_SERIAL_RE = re.compile(r"envoy_(\d+)_")


def extract_envoy_serial(entity_id: str) -> str | None:
    """Extract Envoy serial number from any Envoy entity ID.

    >>> extract_envoy_serial("sensor.envoy_482543015950_current_power_production")
    '482543015950'
    >>> extract_envoy_serial("sensor.some_other_thing") is None
    True
    """
    match = _ENVOY_SERIAL_RE.search(entity_id)
    return match.group(1) if match else None


def derive_envoy_config(serial: str) -> dict[str, str]:
    """Return CONF_ENERGY_* keys → derived entity IDs for given Envoy serial.

    Used in __init__.py to inject auto-derived entities into energy_entity_config.
    Explicit per-entity config keys override these via dict.setdefault().

    NOTE: Enpower entities (storage_mode, reserve_soc, grid_enabled,
    charge_from_grid) have a DIFFERENT serial than the Envoy and are
    not derived here. They must be configured separately if hardware changes.
    """
    return {
        CONF_ENERGY_SOLAR_ENTITY: f"sensor.envoy_{serial}_current_power_production",
        CONF_ENERGY_GRID_ENTITY: f"sensor.envoy_{serial}_current_power_consumption",
        CONF_ENERGY_BATTERY_SOC_ENTITY: f"sensor.envoy_{serial}_battery",
        CONF_ENERGY_BATTERY_POWER_ENTITY: f"sensor.envoy_{serial}_current_battery_discharge",
        CONF_ENERGY_NET_POWER_ENTITY: f"sensor.envoy_{serial}_current_net_power_consumption",
        CONF_ENERGY_BATTERY_CAPACITY_ENTITY: f"sensor.envoy_{serial}_battery_capacity",
        CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY: f"sensor.envoy_{serial}_lifetime_energy_consumption",
        # EC-SOLAR-LIFETIME-COUNTER-FLAP-1 (v5.103.82): the inverter-sum
        # ``lifetime_energy_production`` counter flaps to ~0.046 MWh (32 drops
        # in 686 hourly samples, 2026-09-20..10-21) → silent 0.0 / NULL solar
        # rows. The production-CT counter is monotonic, same unit (MWh), and
        # agrees with it when healthy. Explicit config still overrides.
        CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY: f"sensor.envoy_{serial}_production_ct_energy_delivered",
        CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY: f"sensor.envoy_{serial}_lifetime_net_energy_consumption",
        CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY: f"sensor.envoy_{serial}_lifetime_net_energy_production",
        CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY: f"sensor.envoy_{serial}_lifetime_battery_energy_charged",
        CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY: f"sensor.envoy_{serial}_lifetime_battery_energy_discharged",
        CONF_ENERGY_CONSUMPTION_TODAY_ENTITY: f"sensor.envoy_{serial}_energy_consumption_today",
    }


# EC-SELFHEAL-UNEXPLAINED-RESENDS-1 (2026-10-18): HA-core enphase_envoy
# unique_id suffixes (homeassistant/components/enphase_envoy/sensor.py:
# ``f"{envoy_serial_num}_{description.key}"``; keys ``battery_level`` and
# ``reserve_soc``). Protocol strings, not knobs. The write verifier anchors
# on the configured SOC sensor's unique_id to find the Envoy serial, then
# resolves the sibling ``sensor`` ``<serial>_reserve_soc`` as the reserve
# hardware witness (the Enpower ``number`` carries the same suffix under a
# different serial, so the sensor-domain filter is load-bearing).
ENVOY_SOC_UNIQUE_SUFFIX: Final = "_battery_level"
ENVOY_RESERVE_UNIQUE_SUFFIX: Final = "_reserve_soc"

# Critical Envoy-derived entities for V4 validation.
# Missing any of these breaks core EC capabilities (billing, battery decisions,
# daily lifetime accounting). Lifetime battery + capacity are NOT in this list
# because installs without battery legitimately won't have them.
ENVOY_REQUIRED_DERIVED_KEYS: Final = (
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_SOLAR_ENTITY,
    CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY,
    CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY,
)

# v4.3.1: Validator error codes — single source of truth.
# Keys MUST match strings.json `options.error.<code>` for HA's form
# rendering to localize them. Caller (validate_envoy_config) returns these
# as values in the errors dict; config_flow.py reads them and feeds them
# to async_show_form's `errors` param unchanged.
ENVOY_ERR_REQUIRED: Final = "envoy_required"
ENVOY_ERR_INVALID_FORMAT: Final = "envoy_invalid_format"
ENVOY_ERR_ENTITY_MISSING: Final = "envoy_entity_missing"
ENVOY_ERR_DERIVED_MISSING: Final = "derived_entity_missing"
ENVOY_ERR_BASE_DERIVED_MISSING: Final = "envoy_derived_missing"

# EC Envoy boot-decoupling cycle: degraded-but-OK reasons.
# Used when the entity is registry-known (i.e., user config is valid) but
# `hass.states.get` returns None or the state is `unavailable`/`unknown`
# because the device is mid-boot / mid-recovery. EC proceeds; runtime is
# already None-safe (energy_battery.py:928/945 holds state when Envoy
# blips). Repair issue is NOT raised at this layer; D3's deferred
# re-validation handles the post-EVENT_HOMEASSISTANT_STARTED surface.
ENVOY_DEGRADED_STATE_MISSING: Final = "state_missing"
ENVOY_DEGRADED_STATE_UNAVAILABLE: Final = "state_unavailable"


# v4.3.0 D3: Threshold ladder validator.
# The coherent ladder is:
#   reserve_soc ≤ drain_excellent ≤ drain_good ≤ drain_moderate ≤ drain_poor
#   reserve_soc < arbitrage_trigger < drain_poor   (strict on both sides)
#   arbitrage_target > drain_poor                   (no immediate re-drain)
# Drains below reserve_soc are incoherent (Enphase clamps to floor).
# Arbitrage trigger collisions cause drain↔arbitrage oscillation thrash.

def validate_threshold_ladder(
    reserve_soc: int,
    drain_targets: dict,
    arbitrage_trigger: int | None = None,
    arbitrage_target: int = 80,
    peak_buffer_target: int | None = None,
    *,
    fill_priority_soc: int | None = None,
    excess_solar_soc: int | None = None,
    ev_battery_drain_soc: int | None = None,
    inclement_partial_hold_reserve_floor: int | None = None,
) -> tuple[str, str] | None:
    """Validate the SOC threshold ladder for coherence.

    v4.5.0 D2: arbitrage_trigger is OPTIONAL — v4.5.0 removed the SOC
    trigger gate entirely (the gate is forecast-class only). When None,
    trigger checks are skipped. peak_buffer_target is preferred over
    arbitrage_target as the buffer-ceiling check input; the latter is
    accepted for back-compat.

    EC-SOC-LADDER-XVALIDATE-1: added cross-field checks (all optional,
    skipped when None) for four additional SOC knobs whose independent-
    slider design allows silent inversions that flip band polarity:
      - ``fill_priority_soc`` ≤ ``excess_solar_soc``
        (fill-priority band ends where excess-solar band begins;
        inversion oscillates EV pause/resume)
      - ``ev_battery_drain_soc`` ≥ ``reserve_soc``
        (EV drain-pause cannot go below the safety reserve floor)
      - ``inclement_partial_hold_reserve_floor`` ≥ ``reserve_soc``
        (a partial-hold floor BELOW the base reserve is incoherent — the
        raised floor is Enphase-clamped and the operator's intent silently
        collapses)

    Returns None if valid. Otherwise returns a ``(error_code, message)``
    tuple: ``error_code`` is a stable snake_case identifier suitable for
    a config-flow ``errors`` map key; ``message`` is human-readable and
    suitable for logging / sensor attribute.
    """
    drain_excellent = int(drain_targets.get("excellent", 0))
    drain_good = int(drain_targets.get("good", 0))
    drain_moderate = int(drain_targets.get("moderate", 0))
    drain_poor = int(drain_targets.get("poor", 0))
    # OFFPEAK-DRAIN-VERYPOOR-SLIDER-1: 5th quality bucket. very_poor is the
    # WORST forecast tier, so its drain target is the MOST PROTECTIVE — i.e.
    # the HIGHEST SOC floor in the ladder (drain LESS when tomorrow looks
    # even worse than "poor"). Default equals `poor` (30) which is a
    # coincidental equality masking a real concept split (Bug Class #63);
    # the validator MUST test the very_poor branch discriminatingly by
    # driving it OFF the default.
    _has_very_poor = "very_poor" in drain_targets
    drain_very_poor = (
        int(drain_targets.get("very_poor", drain_poor))
        if _has_very_poor else drain_poor
    )

    # Drain ladder: monotonic non-decreasing, all above reserve_soc.
    # Order: excellent <= good <= moderate <= poor <= very_poor.
    if drain_excellent < reserve_soc:
        return (
            "drain_excellent_below_reserve",
            f"drain_excellent ({drain_excellent}) < reserve_soc "
            f"({reserve_soc}) — value will be clamped by Enphase floor",
        )
    if _has_very_poor and drain_very_poor < reserve_soc:
        return (
            "drain_very_poor_below_reserve",
            f"drain_very_poor ({drain_very_poor}) < reserve_soc "
            f"({reserve_soc}) — value will be clamped by Enphase floor",
        )
    if not (drain_excellent <= drain_good <= drain_moderate <= drain_poor):
        return (
            "drain_ladder_not_monotonic",
            f"drain ladder not monotonic: "
            f"excellent={drain_excellent}, good={drain_good}, "
            f"moderate={drain_moderate}, poor={drain_poor}",
        )
    if _has_very_poor and drain_very_poor < drain_poor:
        return (
            "drain_ladder_not_monotonic",
            f"drain ladder not monotonic: "
            f"poor={drain_poor} > very_poor={drain_very_poor} "
            f"(very_poor must be >= poor: worse forecast → more protective)",
        )

    # v4.5.0: trigger checks are optional (kept for back-compat callers).
    if arbitrage_trigger is not None:
        if arbitrage_trigger <= reserve_soc:
            return (
                "arbitrage_trigger_below_reserve",
                f"arbitrage_trigger ({arbitrage_trigger}) ≤ reserve_soc "
                f"({reserve_soc}) — arbitrage would never fire above safety floor",
            )
        if arbitrage_trigger >= drain_poor:
            return (
                "arbitrage_trigger_at_or_above_drain_poor",
                f"arbitrage_trigger ({arbitrage_trigger}) ≥ drain_poor "
                f"({drain_poor}) — boundary collision causes drain↔arbitrage "
                f"oscillation when tomorrow=poor",
            )

    # Buffer ceiling (renamed from arbitrage_target in v4.5.0 D2).
    buffer_ceiling = (
        peak_buffer_target if peak_buffer_target is not None
        else arbitrage_target
    )
    _top_drain = max(drain_poor, drain_very_poor)
    if buffer_ceiling <= _top_drain:
        return (
            "peak_buffer_target_at_or_below_drain_poor",
            f"peak_buffer_target ({buffer_ceiling}) ≤ top-drain "
            f"({_top_drain}, from poor={drain_poor}, "
            f"very_poor={drain_very_poor}) — drain path would immediately "
            f"re-drain after arbitrage CHARGE completes",
        )

    # EC-SOC-LADDER-XVALIDATE-1 cross-field checks.
    if (
        fill_priority_soc is not None
        and excess_solar_soc is not None
        and int(fill_priority_soc) > int(excess_solar_soc)
    ):
        return (
            "fill_priority_above_excess_solar",
            f"fill_priority_soc ({fill_priority_soc}) > excess_solar_soc "
            f"({excess_solar_soc}) — inverted band flips EV pause/resume "
            f"polarity and oscillates",
        )

    if (
        ev_battery_drain_soc is not None
        and int(ev_battery_drain_soc) < int(reserve_soc)
    ):
        return (
            "ev_drain_below_reserve",
            f"ev_battery_drain_soc ({ev_battery_drain_soc}) < reserve_soc "
            f"({reserve_soc}) — EV drain-pause floor below safety reserve",
        )

    if (
        inclement_partial_hold_reserve_floor is not None
        and int(inclement_partial_hold_reserve_floor) < int(reserve_soc)
    ):
        return (
            "inclement_partial_hold_below_reserve",
            f"inclement_partial_hold_reserve_floor "
            f"({inclement_partial_hold_reserve_floor}) < reserve_soc "
            f"({reserve_soc}) — partial-hold floor is Enphase-clamped up "
            f"to reserve_soc, so the operator's intent silently collapses",
        )

    return None


# Ordered SOC-ladder invariants documented for reviewers + the operator:
#   1. reserve_soc <= drain_excellent <= drain_good <= drain_moderate
#      <= drain_poor <= drain_very_poor
#   2. peak_buffer_target > max(drain_poor, drain_very_poor)
#   3. arbitrage_trigger (if set): reserve_soc < arbitrage_trigger < drain_poor
#   4. fill_priority_soc <= excess_solar_soc
#   5. ev_battery_drain_soc >= reserve_soc
#   6. inclement_partial_hold_reserve_floor >= reserve_soc
# Enforcement (EC-SOC-LADDER-FULL-WIRING-1): #1 clamped at the seam
#   BatteryStrategy._get_offpeak_drain_target (raw dict stays raw);
#   #2 detect-only (design parked in PLANNING_ec_soc_ladder_full_wiring.md
#   §D2; revival trigger: any threshold_ladder_violation with the #2 code);
#   #3 detect-only (no consumer); #4/#5 EnergyCoordinator.safely_ordered_ladder;
#   #6 InclementFusion._partial_floor_value (emission + recoverability).
#   Validator + anomaly always read RAW operator values.
CANONICAL_SOC_LADDER_DOC: Final = (
    "reserve_soc <= drain_excellent <= drain_good <= drain_moderate "
    "<= drain_poor <= drain_very_poor < peak_buffer_target; "
    "fill_priority_soc <= excess_solar_soc; "
    "ev_battery_drain_soc >= reserve_soc; "
    "inclement_partial_hold_reserve_floor >= reserve_soc"
)


def _entity_in_registry(hass, entity_id: str) -> bool:
    """Return True iff entity_id is known to the entity registry.

    Used by validate_envoy_config to distinguish "user picked a non-existent
    entity" (registry-absent → hard fail) from "Enphase integration is
    still booting / device is recovering" (registry-known but state-missing
    → degraded, EC still starts). The entity registry is the durable
    source-of-truth (survives restart and is populated before state
    machine entries for the device come online).

    Safe-guarded: if entity_registry import or lookup raises (test harness
    without a real ent_reg fixture), fall back to the state-machine check.
    """
    try:
        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(hass)
        if ent_reg is None:  # defensive
            return hass.states.get(entity_id) is not None
        return ent_reg.async_get(entity_id) is not None
    except Exception:  # noqa: BLE001
        # Fallback: if registry isn't available in this context (rare —
        # only some unit-test harnesses), use the state-machine check so
        # behavior is at worst equivalent to the pre-cycle V2 contract.
        try:
            return hass.states.get(entity_id) is not None
        except Exception:  # noqa: BLE001
            return False


def validate_envoy_config(
    hass,
    energy_entity_config: dict,
) -> dict:
    """Validate envoy entity is set, parseable, present, and critical derived entities exist.

    v4.2.29: Replaces silent-fallback-to-wrong-default with explicit validation.

    EC Envoy boot-decoupling cycle: V2 and V4 are three-way now.
      - REGISTRY-ABSENT  → hard fail (user picked a non-existent entity).
      - REGISTRY-KNOWN + state missing/unavailable → DEGRADED (ok=True,
        degraded=True). EC still registers; runtime is None-safe.
      - REGISTRY-KNOWN + state present + not unavailable → LIVE
        (ok=True, degraded=False). Today's pass path.

    V0 (field set) and V1 (parseable serial) remain hard-fail unchanged —
    these are user-actionable config errors that cannot be boot-race-recovered.

    Returns a dict:
      - ok (bool): True iff no hard-fail check tripped.
      - errors (dict[str, str]): {field_or_'base': error_code}. Empty if ok.
      - warnings (list[str]): non-blocking issues (e.g., entity unavailable now).
      - serial (str | None): parsed serial when V1 passes, else None.
      - resolved (dict[str, str]): entities the EC would actually use, after
        applying explicit overrides on top of derived-from-serial defaults.
      - degraded (bool): True when the envoy entity is registry-known but
        its state is missing/unavailable (device mid-boot/recovery). This
        flag is independent of `ok`: `degraded=True` can co-occur with
        `ok=False` when the envoy is degraded AND a derived entity is
        registry-absent. Consumers MUST gate on `ok` first.
      - degraded_reason (str | None): one of ENVOY_DEGRADED_STATE_MISSING /
        ENVOY_DEGRADED_STATE_UNAVAILABLE when degraded; None otherwise.
      - entity_registry_known (bool): True iff the envoy entity is in the
        HA entity registry. False on V0/V1 hard-fail (no eid to look up).

    Used by:
      - config_flow.async_step_coordinator_energy: reject save on hard-fail.
      - __init__.py: skip EC registration ONLY on V0/V1/registry-absent;
        proceed otherwise (degraded is fine — runtime degrades gracefully).
      - repairs.py: re-run after user re-saves config to clear the issue.
    """
    errors: dict[str, str] = {}
    warnings: list[str] = []
    resolved: dict[str, str] = {}
    degraded: bool = False
    degraded_reason: str | None = None

    envoy_eid = (energy_entity_config or {}).get(CONF_ENERGY_ENVOY_ENTITY)

    # V0: required
    if not envoy_eid:
        errors[CONF_ENERGY_ENVOY_ENTITY] = ENVOY_ERR_REQUIRED
        return {
            "ok": False, "errors": errors, "warnings": warnings,
            "serial": None, "resolved": resolved,
            "degraded": False, "degraded_reason": None,
            "entity_registry_known": False,
        }

    # V1: parseable
    serial = extract_envoy_serial(envoy_eid)
    if not serial:
        errors[CONF_ENERGY_ENVOY_ENTITY] = ENVOY_ERR_INVALID_FORMAT
        return {
            "ok": False, "errors": errors, "warnings": warnings,
            "serial": None, "resolved": resolved,
            "degraded": False, "degraded_reason": None,
            "entity_registry_known": False,
        }

    # V2: entity registry membership (three-way).
    # Registry-absent is a genuine config error — user picked an entity
    # that does not exist or has been removed. Registry-known + state-missing
    # is the boot-race / device-recovery case and must NOT be a hard fail
    # (this is Failure B from the 2026-06-12 incident).
    envoy_registry_known = _entity_in_registry(hass, envoy_eid)
    if not envoy_registry_known:
        errors[CONF_ENERGY_ENVOY_ENTITY] = ENVOY_ERR_ENTITY_MISSING
        return {
            "ok": False, "errors": errors, "warnings": warnings,
            "serial": serial, "resolved": resolved,
            "degraded": False, "degraded_reason": None,
            "entity_registry_known": False,
        }

    # Registry-known: check live state for degraded reason.
    state = hass.states.get(envoy_eid)
    if state is None:
        degraded = True
        degraded_reason = ENVOY_DEGRADED_STATE_MISSING
        warnings.append(
            f"Envoy entity '{envoy_eid}' is registry-known but has no "
            "state yet (device still booting/recovering) — EC will start "
            "and degrade gracefully until state appears"
        )
    elif state.state in ("unavailable", "unknown"):
        degraded = True
        degraded_reason = ENVOY_DEGRADED_STATE_UNAVAILABLE
        warnings.append(
            f"Envoy entity '{envoy_eid}' is currently '{state.state}' — "
            "EC will start and degrade gracefully; verify Enphase "
            "integration is online if this persists"
        )

    # V4: critical derived entities — same three-way treatment.
    # Registry-absent → hard fail (config error). Registry-known but
    # state-missing → degraded (already covered above; do not add error).
    derived = derive_envoy_config(serial)
    for key, derived_eid in derived.items():
        # Explicit override wins over derived; mirrors __init__.py:1386 setdefault
        resolved[key] = (energy_entity_config or {}).get(key) or derived_eid

    for key in ENVOY_REQUIRED_DERIVED_KEYS:
        eid = resolved.get(key)
        if not eid:
            errors[key] = ENVOY_ERR_DERIVED_MISSING
            continue
        # B2 fix: existence = registry-known OR state-present. State-only
        # entities (e.g. YAML template sensors without unique_id) have no
        # registry row but a live state; pre-cycle V4 used hass.states.get
        # so they passed. Restore that behavior.
        if (
            not _entity_in_registry(hass, eid)
            and hass.states.get(eid) is None
        ):
            errors[key] = ENVOY_ERR_DERIVED_MISSING
            continue
        # Registry-known or state-known but state may be None / unavailable
        # / unknown (mid-boot). Do NOT hard-fail; mark degraded if not
        # already. B3 fix: treat unavailable/unknown as degraded, mirroring
        # V2 (energy_const.py:823) — Bug Class #22 (enum/state mismatch).
        _derived_state = hass.states.get(eid)
        if _derived_state is None and not degraded:
            degraded = True
            degraded_reason = ENVOY_DEGRADED_STATE_MISSING
            warnings.append(
                f"Envoy derived entity '{eid}' is registry-known but has "
                "no state yet (device mid-boot)"
            )
        elif (
            _derived_state is not None
            and _derived_state.state in ("unavailable", "unknown")
            and not degraded
        ):
            degraded = True
            degraded_reason = ENVOY_DEGRADED_STATE_UNAVAILABLE
            warnings.append(
                f"Envoy derived entity '{eid}' is currently "
                f"'{_derived_state.state}' (device mid-boot/recovery)"
            )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "serial": serial,
        "resolved": resolved,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "entity_registry_known": True,
    }


# ============================================================================
# R7 — Projection Singleton (Numbers Get Knobs: module-constant rung)
# ============================================================================
# Kill-switch for the unified `EnergyProjector.project_soc_at_boundary`
# primitive. When TRUE, every SOC-at-boundary projection site (rung 0/1,
# attain entry, attain hold-current) routes through the primitive. When
# FALSE, sites fall back to inline arithmetic (one-release fallback path
# per PLANNING_net_energy_program_R1_R7_R2.md R7 §Kill-switch). This is a
# code-review-governed knob (never operator-tuned), so it lives here rather
# than options-flow or an entity.
R7_USE_UNIFIED_PROJECTOR: Final[bool] = True

# ============================================================================
# EVSE Drain-Precedence (Tier 3 — hold-then-eval)
# ------------------------------------------------------------------
# Session-A skeleton: knobs + state machine + KV persist/restore + observability.
# Session B wires actuation, evaluation, and read sites into the tick loop.
#
# Numbers Get Knobs rung placement (operator rule 2026-07-16):
#   All CONF_DP_* below are rung-1 MODULE CONSTANTS for this session.
#   The plan (§68-84) proposes eventual promotion of SEVERAL of these
#   to Number/Switch/Select entities (`CONF_DP_ENABLE` → Switch,
#   `CONF_DP_EVAL_DELAY_MIN` / `CONF_DP_MARGIN_MIN` /
#   `CONF_DP_MUST_START_BY` / `CONF_DP_NEEDED_KWH_FALLBACK` → Number,
#   `CONF_DP_HOUSE_LOAD_SOURCE` → Select) — but the operator ratifications
#   at §246-264 ratify DEFAULT VALUES only, not entity promotion. Promotion
#   is deferred to Session B (which wires the entity surface + persistence).
#
#   Rungs annotated per constant. `KILL:` documents kill-switch semantics.
# ============================================================================

# --- Master kill switch ---------------------------------------------
# Rung-1 (module constant this session; plan §74 promotes to Switch in
# Session B). False → hold-only, today's behavior; state machine stays in
# HOLD_ONLY and the eval path is never entered.
# KILL: CONF_DP_ENABLE = False disables all transition eval + actuation.
CONF_DP_ENABLE: Final[bool] = False

# --- Eval timing ----------------------------------------------------
# Rung-1 (module const; Session B → Number entity). Minimum minutes hold
# must be active before an eval fires. Un-probed (no hold-flap data in
# probe window); Bug Class #48 conservatism → 10 min default.
CONF_DP_EVAL_DELAY_MIN: Final[int] = 10

# --- Safety margin --------------------------------------------------
# Rung-1 (module const; Session B → Number entity). Margin (minutes) added
# to drain_hours + charge_hours before the "fits before must-start-by"
# check. P4 replay showed 0/7 miss at 60 min with worst-case headroom
# 1.75 h → 60 min default.
CONF_DP_MARGIN_MIN: Final[int] = 60

# --- Must-start-by --------------------------------------------------
# Rung-1 (module const; Session B → Number entity, minutes-past-midnight).
# Operator ratification §255-256: 03:00 (L1 chargers are slow; more
# conservative than the 04:00 candidate). Stored as minutes past midnight
# so Session B's Number entity is a simple int surface.
CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT: Final[int] = 3 * 60  # 03:00

# --- House-load source ---------------------------------------------
# Rung-1 (module const; Session B → Select entity). Ratification §257:
# max(live SPAN, R1 base prediction) — conservative blend. String enum:
# "max_span_r1" | "live_span" | "r1_base". Only max_span_r1 is ratified
# for ship; the others are opt-in for probe re-runs.
CONF_DP_HOUSE_LOAD_SOURCE: Final[str] = "max_span_r1"
DP_HOUSE_LOAD_SOURCES: Final = ("max_span_r1", "live_span", "r1_base")

# --- Needed-kWh priors ---------------------------------------------
# Rung-1 (module const; Session B → Number entity). garage_a-only prior;
# probe P3 car-stop p90 = 22.3 kWh (n=4) → 25 kWh rounded up. Session B
# will surface per-EVSE knobs.
CONF_DP_NEEDED_KWH_GARAGE_A: Final[float] = 25.0

# Rung-1 (module const; Session B → Number entity). Worst-case fallback
# when car SOC is unknown or car has no session history (garage_b). Set to
# full EV battery capacity minus 10% buffer — operator specifies concrete
# vehicle capacity via CONF once entity surface arrives; module default is
# a conservative 75 kWh (large EV worst-case).
CONF_DP_NEEDED_KWH_GARAGE_B_FALLBACK: Final[float] = 75.0

# --- L1 charger auto-hold threshold --------------------------------
# Rung-1 (module const; safety threshold, requires review). If the only
# connected charger is L1 (rate <= this kW), the eval MUST return HOLD
# immediately per P4 verdict (16 h L1 charge can never fit a 9 h night).
# 3.0 kW cleanly separates L1 (~1.4 kW) from L2 (~7.6 kW).
DP_L1_RATE_THRESHOLD_KW: Final[float] = 3.0
DP_CHARGER_RATE_L1_KW: Final[float] = 1.4
DP_CHARGER_RATE_L2_KW: Final[float] = 11.5

# --- Physical / model constants ------------------------------------
# Rung-1 (module const, physical property — change requires review).
# 40,000 Wh / 100 pp = 0.40 kWh per SOC percentage point (probe confirmed
# via sensor.envoy_482543015950_battery_capacity).
DP_CAPACITY_KWH_PER_SOC_PP: Final[float] = 0.40

# Rung-1 (module const, safety bound for INV-DP1 slack — change requires
# review). Tolerance kW above measured house load during the transitioned
# window before the reversion sweep flags "over-discharge".
DP_HOUSE_LOAD_TOLERANCE_KW: Final[float] = 1.0

# Rung-1 (module const, safety bound — change requires review). Caps how
# long a transition can hold the paused-EVSE + released-reserve state
# before force-releasing to CHARGING (must-start-by acts as the primary
# guard; this is the belt-and-suspenders bound).
DP_TRANSITION_MAX_DURATION_H: Final[float] = 8.0

# --- Night window --------------------------------------------------
# Rung-1 (module const). Night window used for the "fits before must-start-by"
# arithmetic: 21:00 → 06:00 = 9 h. Reviewed constant; probe derived.
DP_NIGHT_WINDOW_HOURS: Final[float] = 9.0
DP_NIGHT_WINDOW_START_HOUR: Final[int] = 21
DP_NIGHT_WINDOW_END_HOUR: Final[int] = 6

# --- KV persistence key --------------------------------------------
# Rung-1 (module const, wire-format contract). Single JSON blob under this
# key in the `energy_state` KV table. Change requires migration.
DP_KV_KEY: Final[str] = "drain_precedence_state_v1"

# ============================================================================
# Session B1 — CONF OPTION KEYS for entity persistence (plan §68-84).
# ------------------------------------------------------------------
# The `CONF_DP_*` constants above are default VALUES (bool/int/float/str)
# consumed directly by the state machine in `energy_drain_precedence.py`.
# The `CONF_ENERGY_DP_*` string keys BELOW are the persisted-config keys
# used by the Switch/Number/Select entities and CM options-writeback:
# they live in `entry.options` as the sole source of truth (mirrors the
# OffPeakDrainNumber / PeakBufferTargetNumber pattern at number.py:710+).
# On restart the entity constructor re-seeds `self._value` from
# `{**entry.data, **entry.options}` under these keys; the state-machine
# defaults above are the first-boot fallback.
# ============================================================================

CONF_ENERGY_DP_ENABLE: Final[str] = "energy_dp_enable"
CONF_ENERGY_DP_EVAL_DELAY_MIN: Final[str] = "energy_dp_eval_delay_min"
CONF_ENERGY_DP_MARGIN_MIN: Final[str] = "energy_dp_margin_min"
CONF_ENERGY_DP_MUST_START_BY_MIN: Final[str] = "energy_dp_must_start_by_min"
CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A: Final[str] = "energy_dp_needed_kwh_garage_a"
CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B: Final[str] = "energy_dp_needed_kwh_garage_b"
CONF_ENERGY_DP_HOUSE_LOAD_SOURCE: Final[str] = "energy_dp_house_load_source"
# EC-HOUSE-ENTITY-DEFAULTS-1 fix-up: the two mains power readings the
# "live_span" house-load source sums (formerly literals in
# EnergyCoordinator._dp_house_load_kw). Unset = that reading is absent.
CONF_ENERGY_DP_SPAN_R1_ENTITY: Final[str] = "energy_dp_span_r1_entity"
CONF_ENERGY_DP_SPAN_R2_ENTITY: Final[str] = "energy_dp_span_r2_entity"

# v5.21.0 D4 — BAEC shadow-eval INFO-log rate-limit interval (seconds).
# Rung-1 module constant (safety bound; log-volume incident risk mitigation
# — the v5.2.x DB write-flood family taught us untuned per-tick logs saturate
# quickly). 300s ≈ 5 min: dense enough to see edges (plug-in, drain-target
# crossing, wake) without carpeting the log during a quiescent overnight
# window. Not operator-tunable by design — turning this up hides evidence,
# turning it down burns disk. Kill: not exposed as a knob.
DP_SHADOW_LOG_RATE_LIMIT_S: Final[int] = 300

# fill-priority-daylight-restoration fix-up A-M2 (Numbers-Get-Knobs rung-1):
# Fallback civil sunrise/sunset hours used by
# ``BatteryStrategy._daylight_bounds`` when ``sun.sun`` is unavailable OR
# its `next_rising` / `next_setting` attrs fail to parse. Named rung-1
# module constants — not operator-tunable; widening these silently
# changes the daytime hold surface everywhere the daylight bool is
# consumed. Kill semantics: N/A — a bad value degrades the fallback
# envelope but does not disable the feature (genuine helper exceptions
# still yield None, which the pool treats as "preserve v5.5.5 off_peak-
# inert").
DAYLIGHT_FALLBACK_SUNRISE_HOUR: Final[int] = 7
DAYLIGHT_FALLBACK_SUNSET_HOUR: Final[int] = 19

# ============================================================================
# Blind-window EVSE guard + DP eval persistence + LKG envelope
# (see docs/planning/PLANNING_ec_blind_window_evse_guard.md)
# ============================================================================

# Rung-1 (module const, safety-vs-liveness tradeoff — change requires review).
# Bounds how long the blind-window guard may DEFER an EVSE ensure-on before it
# must yield to the DP must-start-by machinery so cars still charge overnight.
# Default derived from D3 probe (PROBE_envoy_outage_frequency.md: ~2-3 outages
# >30min per day; 60 min covers 78%+ of tail while preserving overnight liveness
# ahead of must-start-by pressure). Kill-switch: value 0 disables the defer
# (D1 becomes a no-op — emergency backout via a code-change hotfix).
CONF_BLIND_WINDOW_MAX_DEFER_MIN: Final[int] = 60

# Rung-1 (module const, anti-flap bound). Sub-2-min Envoy blips are 66% of
# events per D3 probe; without a debounce the fail-safe pause leg would cycle
# chargers on 90-second blips — the same disconcerting-actuation class the fan
# pause work fought. The guard "opens" only after the entry-predicate holds
# for this many consecutive seconds (i.e. at least one full ~5-min decision
# tick under blind conditions). Kill: 0 disables debounce (fires immediately).
CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S: Final[int] = 120

# Rung-1 (module const, forensic-scope decision — change requires review).
# Retention window for `decision_log` rows tagged `decision_type='dp_eval'`.
# 90 days is comfortably above the 7-14 day forensic windows past incidents
# have needed. See D2 in the planning doc.
CONF_DP_EVAL_LOG_RETENTION_DAYS: Final[int] = 90

# Rung-1 (module const, freshness bound — change requires review).
# Fix-up A-CRIT-1 (Batch 1): a reserve write-verify record is only
# "verifiable" if its `verified_at` timestamp is fresher than this bound.
# Between write episodes the record RESTS in STATUS_OK; without a freshness
# gate, `is_reserve_verifiable()` would return True forever on a resting-OK
# record even during a live Envoy blackout — the guard's entry predicate
# could never engage in a quiet outage. Style-matched to the 600s
# `_desired_stamped_at` staleness gate in energy_write_verify.py at
# ~line 815 (`_age > 600`). Kill-switch: value 0 disables freshness gating
# (record status alone governs) — emergency backout.
CONF_RESERVE_VERIFIABLE_MAX_AGE_S: Final[int] = 600

# Rung-2 (CONF, per-deployment). Optional Emporia-mains backup net/export
# sensor consulted by the excess-solar path when Envoy is blind. Default
# unset = current behavior (excess-solar claim requires Envoy). Registry-
# verified candidates (2026-07-21): sensor.mains_vue_2_mainstogrid_*,
# sensor.mainw_vue_balance_power_minute_average. Positive-export convention:
# operator supplies an entity whose numeric state is > 0 when the house
# is exporting to the grid (surplus solar). See D4 in the planning doc.
#
# Fix-up A-MED-1 (Batch 3) — UNIT CONTRACT is W-only for threshold math.
# `EnergyCoordinator.mains_export_active(threshold_w)` normalizes the
# entity's raw numeric state to WATTS by reading `unit_of_measurement`:
#   * "W" / None / "" → identity (already W).
#   * "kW" / "kw"    → multiplied by 1000.
#   * any other unit → refused as inconclusive (fail-safe None); operator
#     must fix the wiring rather than have URA silently admit mixed units
#     (Bug Class #30). Thresholds are ALWAYS expressed in W.
CONF_ENERGY_MAINS_EXPORT_ENTITY: Final = "energy_mains_export_entity"

# Rung-1 (module const, physical property — change requires code review).
# Home battery physics used by the LKG SOC envelope. Live health data:
# 40 kWh capacity, 30.72 kW max power (2x IQ Battery 10T at 15.36 kW each).
# The envelope widens LKG bounds by ± max_power*Δt/capacity*100 per second
# so a bounded-uncertainty SOC estimate remains usable beyond the LKG's
# freshness cap. See D5 in the planning doc.
BATTERY_CAPACITY_KWH: Final[float] = 40.0
BATTERY_MAX_CHARGE_KW: Final[float] = 30.72
BATTERY_MAX_DISCHARGE_KW: Final[float] = 30.72

# Rung-1 (module const). Absolute upper age (seconds) for the LKG envelope
# to remain queryable after primary/cloud tiers die. Beyond this, the envelope
# is so wide it's useless and the guard treats SOC as fully unknown. 6 hours
# is long enough to bridge the worst observed 84-min outage plus margin.
DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S: Final[int] = 6 * 3600


def soc_bounds(
    capacity_kwh: float,
    max_charge_kw: float,
    max_discharge_kw: float,
    max_age_s: float,
):
    """Return a :data:`..lkg.BoundsFn` closing over battery physics constants.

    LKG wave 1 D1: physics factory for the SOC LKG envelope. Consumed by
    the ``SOCEnvelope`` shim in ``energy_battery`` and directly by any
    caller building an ``LkgValue`` for SOC. Placed at rung 1 (module
    constant / factory) — capacity + max power are per-install physical
    numbers whose change should require code review.

    Envelope math (byte-identical to the shipped ``SOCEnvelope.compute``):
        down_pp = max_discharge_kw * age_s / (36 * capacity_kwh)
        up_pp   = max_charge_kw    * age_s / (36 * capacity_kwh)
        lo      = max(0.0, value - down_pp)
        hi      = min(100.0, value + up_pp)

    Tier crossovers (survey §4 shape):
        fresh        age < 60 s  (live-cadence read)
        lkg_bounded  age < 600 s (10 min — money-path safe)
        lkg_stale    age < max_age_s (bounded but wide)
        expired      age >= max_age_s (unusable — caller should treat as unknown)

    Epsilon convention (A3 / B1 fix-up, wave 1 D1):
        The boundary at ``age == max_age_s`` is EXPIRED in this factory
        (strict-less-than gate at ``age < hard_max``). The shipped
        ``SOCEnvelope.compute`` shim used to return a bounded pair AT the
        boundary; it preserves that legacy behavior by passing
        ``max_age_s + 1e-6`` when it constructs its per-call factory. That
        ``+1e-6`` widening lives IN THE CALLER, not here — direct callers
        of ``soc_bounds`` get expired AT ``max_age_s``. Future
        signal-specific factories (solar, outdoor temp in D2/D3) should
        adopt an explicit ``boundary_inclusive: bool`` parameter rather
        than replicating the widen-at-the-caller idiom.
    """
    if capacity_kwh <= 0:
        raise ValueError(f"capacity_kwh must be > 0, got {capacity_kwh!r}")
    cap = float(capacity_kwh)
    chg = float(max(0.0, max_charge_kw))
    dsg = float(max(0.0, max_discharge_kw))
    hard_max = float(max_age_s)

    def _bounds(value, at, now):
        try:
            age = (now - at).total_seconds()
        except Exception:  # noqa: BLE001
            return (0.0, 0.0, "expired")
        if age < 0:
            age = 0.0
        if age >= hard_max:
            return (0.0, 0.0, "expired")
        if age < 60:
            tier = "fresh"
        elif age < 600:
            tier = "lkg_bounded"
        else:
            tier = "lkg_stale"
        try:
            v = float(value)
        except (TypeError, ValueError):
            return (0.0, 0.0, "expired")
        down_pp = (dsg * age) / (36.0 * cap)
        up_pp = (chg * age) / (36.0 * cap)
        lo = max(0.0, v - down_pp)
        hi = min(100.0, v + up_pp)
        if hi < lo:
            hi = lo
        return (lo, hi, tier)

    return _bounds


# ---------------------------------------------------------------------
# LKG wave 1 D2 — solar production upper envelope factory
# ---------------------------------------------------------------------
# Rung-1 (module const). Upper-decay time constant: how long the envelope's
# upper bound stays anchored on the LKG value before widening toward the
# nameplate. 300 s = 5 min: linear widening from LKG → nameplate over this
# window. Beyond `hard_max_age_s` (below) the envelope is expired
# (nameplate is useless as a freshness signal).
SOLAR_LKG_UPPER_DECAY_S: Final[int] = 300
# Rung-1 (module const, safety-adjacent). Absolute lower-bound of stamped
# LKG production required before the excess-solar CONTINUE gate admits.
# Fix-up A-HIGH-1: the admit MUST be evidenced by a real live production
# reading (the STAMPED LKG value), NOT by the envelope's upper bound —
# the upper widens toward nameplate purely with age and would admit even
# off a stamped 0 W dusk reading. 500 W is well below any EVSE draw
# (~3-4 kW) but proves the array was recently doing real work.
SOLAR_ENVELOPE_ADMIT_FLOOR_W: Final[int] = 500
# Rung-1. Absolute upper age for the solar envelope. Solar can invert
# entirely across a passing cloud front — after 15 min the LKG carries no
# defensible information about now.
DEFAULT_SOLAR_LKG_ENVELOPE_MAX_AGE_S: Final[int] = 15 * 60


def solar_upper_bounds(
    nameplate_w: float,
    upper_decay_s: float = SOLAR_LKG_UPPER_DECAY_S,
    max_age_s: float = DEFAULT_SOLAR_LKG_ENVELOPE_MAX_AGE_S,
):
    """Return a :data:`..lkg.BoundsFn` for solar production (asymmetric UPPER).

    LKG wave 1 D2: physics factory for the solar production envelope.
    Asymmetric by construction — solar production can drop to zero
    instantaneously (cloud edge), so the LOWER bound collapses to 0. It
    cannot exceed the installed array nameplate, so the UPPER bound is
    clamped to ``nameplate_w`` and widens LINEARLY from ``lkg`` toward
    that ceiling over ``upper_decay_s`` seconds.

    Envelope math::

        age    = (now - at).total_seconds()
        frac   = min(1.0, age / upper_decay_s)
        lo     = 0.0                                    # physics: instant drop
        hi_raw = value + (nameplate_w - value) * frac   # widen to nameplate
        hi     = min(nameplate_w, max(0.0, hi_raw))

    Tier crossovers (mirror the SOC envelope shape for cross-signal
    consistency; see planning §3.2)::

        fresh        age < 60 s
        lkg_bounded  age < upper_decay_s (money-path safe)
        lkg_stale    age < max_age_s (bounded but wide — envelope has
                     already widened to full nameplate)
        expired      age >= max_age_s (unusable — caller should treat
                     as raw-None binary, matches pre-D2 behavior)

    Rung-1 factory. ``nameplate_w`` is supplied by the caller from the
    config-flow field ``CONF_ENERGY_SOLAR_NAMEPLATE_W`` (rung 2) —
    physical structure, per-install.
    """
    cap = float(max(0.0, nameplate_w))
    decay = float(max(1.0, upper_decay_s))
    hard_max = float(max_age_s)

    def _bounds(value, at, now):
        try:
            age = (now - at).total_seconds()
        except Exception:  # noqa: BLE001
            return (0.0, 0.0, "expired")
        if age < 0:
            age = 0.0
        if age >= hard_max:
            return (0.0, 0.0, "expired")
        try:
            v = float(value)
        except (TypeError, ValueError):
            return (0.0, 0.0, "expired")
        # Clamp value into physical range before widening (a spurious
        # over-nameplate reading upstream must not persist through the
        # envelope).
        v = max(0.0, min(cap, v))
        if age < 60:
            tier = "fresh"
        elif age < decay:
            tier = "lkg_bounded"
        else:
            tier = "lkg_stale"
        frac = min(1.0, age / decay)
        hi_raw = v + (cap - v) * frac
        hi = min(cap, max(0.0, hi_raw))
        lo = 0.0  # asymmetric: solar can drop to zero instantly
        if hi < lo:
            hi = lo
        return (lo, hi, tier)

    return _bounds


# ============================================================================
# EC-HOUSE-ENTITY-DEFAULTS-1 (Rev 5, 2026-10-13)
# ----------------------------------------------------------------------------
# EC_ROLE_KEY_DEFAULTS maps each role-named CONF option key → the entity_id
# (or list) that used to live as a DEFAULT_* literal in this module. On this
# house (Phalanx), setup runs a one-shot "pin today's resolved values into
# options" migration (``_bootstrap_pin_ec_defaults_once`` in __init__.py)
# which copies the OLD default into THIS house's options IFF the key is
# unset AND the entity still exists in the registry. The module-level
# DEFAULT_* constants are now None/[]; the migration preserves G3
# byte-identity on existing installs while a 2nd install sees empty fields
# and is forced to configure real entities (satisfies G1 + G2).
# ============================================================================
EC_ROLE_KEY_DEFAULTS: Final[dict[str, Any]] = {
    # Enpower control (local writes)
    CONF_ENERGY_STORAGE_MODE_ENTITY: "select.enpower_482348004678_storage_mode",
    CONF_ENERGY_RESERVE_SOC_ENTITY: (
        "number.enpower_482348004678_reserve_battery_level"
    ),
    CONF_ENERGY_GRID_ENABLED_ENTITY: (
        "switch.enpower_482348004678_grid_enabled"
    ),
    CONF_ENERGY_CHARGE_FROM_GRID_ENTITY: (
        "switch.enpower_482348004678_charge_from_grid"
    ),
    # Solcast forecast
    CONF_ENERGY_SOLCAST_TODAY_ENTITY: (
        "sensor.solcast_pv_forecast_forecast_today"
    ),
    CONF_ENERGY_SOLCAST_TOMORROW_ENTITY: (
        "sensor.solcast_pv_forecast_forecast_tomorrow"
    ),
    CONF_ENERGY_SOLCAST_REMAINING_ENTITY: (
        "sensor.solcast_pv_forecast_forecast_remaining_today"
    ),
    CONF_ENERGY_SOLCAST_DAY_3_ENTITY: (
        "sensor.solcast_pv_forecast_forecast_day_3"
    ),
    # Weather
    CONF_ENERGY_WEATHER_ENTITY: "weather.phalanxmadrone",
    # EVSE power
    CONF_ENERGY_EVSE_A_ENTITY: "sensor.garage_a_power_minute_average",
    CONF_ENERGY_EVSE_B_ENTITY: "sensor.garage_b_power_minute_average",
    # L1 chargers (list)
    CONF_ENERGY_L1_CHARGER_ENTITIES: [
        "switch.smartplug_moes_wifi_garagealeftfront_socket_1",
        "switch.smartplug_moes_wifi_garagealeftfront_socket_2",
        "switch.smartplug_moes_wifi_garagealeftfront_socket_3",
        "switch.smartplug_moes_wifi_garagealeftfront_socket_4",
    ],
    # Cloud oracles (read-back / fallback)
    CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY: (
        "number.iq_battery_hacs_battery_reserve"
    ),
    CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY: (
        "switch.iq_battery_hacs_charge_battery_from_grid"
    ),
    CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY: (
        "select.iq_gateway_hacs_system_profile"
    ),
    CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY: (
        "sensor.iq_battery_hacs_battery_overall_charge"
    ),
    # Solar-follow grid-power inputs
    CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY: (
        "sensor.mains_vue_3_power_minute_average"
    ),
    CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY: (
        "sensor.envoy_482543015950_current_net_power_consumption"
    ),
    # Fix-up additions (review G1 completeness).
    # EVSE per-charger roles (formerly energy_pool.DEFAULT_EVSE_ENTITIES).
    CONF_ENERGY_EVSE_A_SWITCH_ENTITY: "switch.garage_a",
    CONF_ENERGY_EVSE_A_ENERGY_TODAY_ENTITY: "sensor.garage_a_energy_today",
    CONF_ENERGY_EVSE_A_ENERGY_MONTH_ENTITY: (
        "sensor.garage_a_energy_this_month"
    ),
    CONF_ENERGY_EVSE_A_SPAN_BREAKER: "switch.span_panel_car_charger_breaker",
    CONF_ENERGY_EVSE_A_CURRENT_LIMIT_ENTITY: (
        "number.garage_a_evse_emporia_wifi_garagea_current_limit"
    ),
    CONF_ENERGY_EVSE_B_SWITCH_ENTITY: "switch.garage_b",
    CONF_ENERGY_EVSE_B_ENERGY_TODAY_ENTITY: "sensor.garage_b_energy_today",
    CONF_ENERGY_EVSE_B_ENERGY_MONTH_ENTITY: (
        "sensor.garage_b_energy_this_month"
    ),
    CONF_ENERGY_EVSE_B_SPAN_BREAKER: "switch.span_panel_garage_b_evse_breaker",
    CONF_ENERGY_EVSE_B_CURRENT_LIMIT_ENTITY: (
        "number.garage_b_evse_emporia_wifi_garageb_current_limit"
    ),
    # Drain-precedence live house-load mains readings.
    CONF_ENERGY_DP_SPAN_R1_ENTITY: "sensor.span_panel_current_power",
    CONF_ENERGY_DP_SPAN_R2_ENTITY: "sensor.span_panel_current_power_2",
    # Cloud last-successful-update stamp.
    CONF_ENERGY_CLOUD_LAST_SUCCESS_ENTITY: (
        "sensor.enphase_cloud_last_successful_update"
    ),
    # Pool pump (formerly energy_pool.DEFAULT_POOL_*).
    CONF_ENERGY_POOL_SPEED_ENTITY: (
        "number.pentair_pool_variable_speed_pump_1_speed"
    ),
    CONF_ENERGY_POOL_POWER_ENTITY: (
        "sensor.pentair_pool_variable_speed_pump_1_power"
    ),
    # Generator status (key already existed; set on this house — pinned only
    # where unset, registry-gated like every other row).
    CONF_ENERGY_GENERATOR_ENTITY: "sensor.generac_2325624_status_2",
}


# EC_ROLE_KEY_SET — the full set of role-key CONF names the migration pins
# AND that the setup/hourly repair-issue scanner inspects. Keep aligned
# with ``EC_ROLE_KEY_DEFAULTS``. These keys are deliberately NOT in
# ``OPTIONS_RELOAD_SUPPRESS_KEYS``: an operator edit must reload the CM so
# the new entity takes effect. The one-shot pin avoids that reload by
# reseeding the listener snapshot (see ``_bootstrap_pin_ec_defaults_once``).
EC_ROLE_KEY_SET: Final[frozenset[str]] = frozenset(EC_ROLE_KEY_DEFAULTS)



# EC-HOUSE-ENTITY-DEFAULTS-1 (review D I3, operator option A) — energy
# entity-mapping keys that are read ONLY when the EnergyCoordinator (and its
# helpers) is CONSTRUCTED during the parent (integration) entry's setup, so a
# saved change needs a PARENT reload to take effect (a CM-entry reload does
# not rebuild the EC). How derived (2026-10-13): every `CONF_ENERGY_*_ENTITY /
# _ENTITIES / _BREAKER / WEATHER_FALLBACK_n` constant in this module, kept iff
# it is read in `EnergyCoordinator.__init__` / `_build_entity_map`
# (energy.py) or in the EC/weather-manager construction block of
# `__init__.py` (`cm_config` → EVSE builder, L1 list, envoy anchor,
# `WeatherProviderManager(hass, cm_config)`), and NOT live-applied (not in
# `OPTIONS_RELOAD_SUPPRESS_KEYS` — e.g. CONF_ENERGY_MAINS_EXPORT_ENTITY is
# excluded). The DP mains readings are read per tick but from the
# `_entity_config` copy taken at construction, so they belong here too.
EC_CONSTRUCTION_ENTITY_KEYS: Final[frozenset[str]] = EC_ROLE_KEY_SET | frozenset({
    CONF_ENERGY_SOLAR_ENTITY,
    CONF_ENERGY_GRID_ENTITY,
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_BATTERY_SOC_ENTITY,
    CONF_ENERGY_BATTERY_POWER_ENTITY,
    CONF_ENERGY_BATTERY_CAPACITY_ENTITY,
    CONF_ENERGY_CONSUMPTION_TODAY_ENTITY,
    CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY,
    CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY,
    CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY,
    CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY,
    CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY,
    CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY,
    CONF_ENERGY_GRID_IMPORT_ENTITY,
    CONF_ENERGY_GRID_EXPORT_ENTITY,
    CONF_ENERGY_UTILITY_METER_ENTITY,
    CONF_ENERGY_ENVOY_ENTITY,
    CONF_ENERGY_STREAM_BATTERY_SOC_ENTITY,
    CONF_ENERGY_STREAM_COWITNESS_ENTITY,
    CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES,
    CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES,
    CONF_ENERGY_WEATHER_FALLBACK_1,
    CONF_ENERGY_WEATHER_FALLBACK_2,
})


# ============================================================================
# EC-RESERVE-WRITE-GOVERNOR-1 — reserve write governor (Rev 3.2)
# ============================================================================
#
# Rung 1 (module constant — change requires review): importance of the
# per-dispatch `reserve_write` activity row. Same value as
# `hvac_const.CLIMATE_WRITE_LOG_IMPORTANCE` (parity with the HVAC write
# row; `notable` = 30 d retention, database.py:5827-5834).
RESERVE_WRITE_LOG_IMPORTANCE: Final = "notable"

# Rung 1: production allowlist of every statically visible `number` /
# `set_value` writer in the package, enforced by the AST lint
# `quality/tests/test_reserve_write_chokepoint_lint.py` (INV-G1).
# (module, enclosing function, kind, pinned occurrence count).
#   kind: "reserve"     — a reserve-entity write (dispatch covered by C1/C3)
#         "reader"      — a `"number.set_value"` comparison, not a write
#         "non_reserve" — writes to a non-reserve number (pool, EVSE amps,
#                         load-shed, radar device numbers)
# Counting rule (lint §4): +1 per Call whose first two positional args are
# ("number", "set_value") or whose keywords are domain="number",
# service="set_value"; +1 per ast.Constant == "number.set_value". The
# constant args of a counted Call are not counted again. A topology change
# (new writer, moved writer) MUST update this table in the same commit.
RESERVE_SET_VALUE_WRITERS: tuple[tuple[str, str, str, int], ...] = (
    # EC storm/blind Stage A D-A2: the ONE decision-side reserve writer
    # (sighted `_result` and every fully-blind rule route through it).
    ("energy_battery.py", "_reserve_action",            "reserve",     1),
    ("energy_battery.py", "force_redispatch",           "reserve",     2),  # async_call + failure record
    ("energy.py",         "_apply_evse_battery_hold",   "reserve",     1),
    ("energy.py",         "_tap_write_verifier",        "reader",      1),  # svc compare (C1)
    ("energy.py",         "_evaluate_battery",          "reader",      1),  # svc compare (C2)
    ("energy.py",         "_execute_shed_action",       "non_reserve", 2),  # pool speed
    ("energy_pool.py",    "determine_actions",          "non_reserve", 2),  # pool speed
    ("energy_pool.py",    "_write_amps",                "non_reserve", 1),  # EVSE amps
    ("radar_tuning.py",   "async_send_radar_settings",  "non_reserve", 1),  # radar device numbers
)

# EC storm Stage B D-B6 item 8 (rung 1): every `charge_from_grid=True`
# keyword in energy_battery.py, per enclosing function (AST lint
# `test_cfg_true_emission_sites_pinned`). All reach the decision dict via
# `_result`; `"switch.turn_on"` literals live only in `_result`.
# determine_mode: storm precharge x2 (degraded + plain) + pre-onset x1.
CFG_TRUE_EMISSION_SITES: tuple[tuple[str, str, int], ...] = (
    ("energy_battery.py", "_get_arbitrage_decision", 1),
    ("energy_battery.py", "_get_attainability_decision", 1),
    ("energy_battery.py", "determine_mode", 3),
)


# ============================================================================
# EC-OUTAGE-LEDGER (PLANNING_ec_storm_and_blind_decisions.md Stage L)
# ============================================================================
#
# All rung 1 (module constants; change requires review). The ledger is
# evidence-only: no decision path reads these rows. Retention is governed
# by `const.ACTIVITY_LEDGER_RETAINED_ACTIONS` (the prune exemption), so the
# importance below is parity only.
ACTIVITY_LEDGER_IMPORTANCE: Final = RESERVE_WRITE_LOG_IMPORTANCE

# Cloud-calendar sweep (primary outage witness, Rev 2.1 / P4). 0 disables.
OUTAGE_SWEEP_INTERVAL_H: Final = 24
# First sweep after setup, off the boot path.
OUTAGE_SWEEP_INITIAL_DELAY_S: Final = 300
# Lookback per sweep: overlaps one missed day; well inside the ~7-week
# calendar retention and the weekly query window that is known to work.
OUTAGE_SWEEP_LOOKBACK_H: Final = 48
# A local_only row within this many minutes of a cloud off-grid event start
# marks the cloud row corroborated_by_local (5-min tick + cloud lag).
OUTAGE_DEDUP_TOLERANCE_MIN: Final = 10
# calendar.get_events timeout (long windows time out on this calendar).
OUTAGE_SWEEP_TIMEOUT_S: Final = 30
# Case-folded SUBSTRING classifiers, never equality. Live summaries read
# 2026-10-16 from the calendar for the 2026-09-16 outage:
#   "Your system is now off grid or disconnected from the grid."
#   "Your system is now connected to the grid."
#   "Your generator is now turned on as per Automatic profile" / "...turned off."
# The off-grid test runs first. Empty off-grid substring = sweep writes nothing.
OUTAGE_CALENDAR_OFFGRID_SUBSTR: Final = "off grid"
OUTAGE_CALENDAR_ONGRID_SUBSTR: Final = "connected to the grid"
OUTAGE_CALENDAR_GENERATOR_SUBSTR: Final = "generator"
# Registry platform of the Enphase cloud system-event calendar (P4(iv)).
# Empty = sweep disabled.
OUTAGE_CALENDAR_PLATFORM: Final = "enphase_ev"
OUTAGE_CALENDAR_ENTITY_SUFFIX: Final = "_system_event_history"
# Hard ceiling on each RAM seen-set (alert IDs are also pruned to the live
# feed every tick; this guards a pathological feed).
OUTAGE_LEDGER_MAX_SEEN: Final = 500
# Cross-boot dedup seed: lookback for existing nws_alert rows. Covers the
# 48 h INCLEMENT_ALERT_MAX_HOLD_H cap plus a day of margin.
OUTAGE_LEDGER_ALERT_SEED_LOOKBACK_H: Final = 72
# Seed read attempts (one per tick for alerts, one per sweep for cloud rows)
# before the ledger proceeds UNSEEDED (a restart may then re-log rows). Keeps
# a persistently failing DB read from silencing the ledger forever.
OUTAGE_LEDGER_SEED_MAX_ATTEMPTS: Final = 3
# Pages of query_activities (200 rows each) read per seed; bounds the read.
OUTAGE_LEDGER_SEED_MAX_PAGES: Final = 10
# Minimum gap between two local_only rows for the SAME sensor. Why: a real
# on/off flap of grid_status/grid_enabled could write 288 never-pruned rows
# a day; the cloud row is the episode record, so one local row per 30 min
# per sensor keeps the corroboration signal. Suppressed edges are still kept
# in RAM for corroboration and counted on the next row. 0 = no gap.
OUTAGE_LOCAL_MIN_GAP_MIN: Final = 30

# EC-SHUTDOWN-SAVE-AFTER-WRITER-CLOSED-1: bound on the Stage-1 shutdown-job
# persist of EC state (rung 1: a protocol window — it must stay under HA's
# 20 s STOPPING_STAGE_SHUTDOWN_TIMEOUT, which runs every shutdown job
# concurrently, incl. the 15 s anomaly-baseline flush; changing it needs review).
EC_STOP_SAVE_TIMEOUT_S: Final = 10
# Before persisting, the stop job waits at most this long for an in-flight
# decision cycle to finish (rung 1, same protocol window; worst-case job wall
# time = this + EC_STOP_SAVE_TIMEOUT_S = 13 s, still under HA's 20 s Stage 1).
EC_STOP_CYCLE_WAIT_S: Final = 3

"""Constants for HVAC Coordinator.

v3.8.0-H1: Initial implementation.
"""

from __future__ import annotations

from typing import Final

# ============================================================================
# Coordinator identity
# ============================================================================

HVAC_COORDINATOR_ID: Final = "hvac"
HVAC_COORDINATOR_NAME: Final = "HVAC Coordinator"
HVAC_COORDINATOR_PRIORITY: Final = 30

# ============================================================================
# Config keys
# ============================================================================

# Per-zone setpoints (dynamic: hvac_zone_{n}_cool_setpoint, etc.)
CONF_HVAC_COVER_ENTITIES: Final = "hvac_cover_entities"
CONF_HVAC_MAX_SLEEP_OFFSET: Final = "hvac_max_sleep_offset"
CONF_HVAC_COMPROMISE_MINUTES: Final = "hvac_compromise_minutes"
CONF_HVAC_AC_RESET_TIMEOUT: Final = "hvac_ac_reset_timeout"
CONF_HVAC_FAN_ACTIVATION_DELTA: Final = "hvac_fan_activation_delta"
CONF_HVAC_FAN_HYSTERESIS: Final = "hvac_fan_hysteresis"
CONF_HVAC_FAN_MIN_RUNTIME: Final = "hvac_fan_min_runtime"
# v4.5.9.2: occupancy-aware solar-gain cover close threshold.
# When a room is occupied, HVAC only closes its covers if room temp
# is at least this many °F above the zone's cooling setpoint. Default
# 2.0°F, configurable per-house from the coordinator_hvac config step.
# Read by CoverController._should_close_for_occupied_room.
CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA: Final = "hvac_occupied_cover_close_delta"
DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA: Final = 2.0  # °F

# v4.5.10 — Solar-gain cover management tunables (CM-level / HVAC step)
# Master toggle for the entire CoverController feature (parallels
# CONF_HVAC_FAN_CONTROL_ENABLED for fans). When False, CoverController
# .update() early-returns and no close/open commands fire — regardless
# of per-room CONF_COVER_HVAC_MANAGED settings.
CONF_HVAC_SOLAR_GAIN_COVER_ENABLED: Final = "hvac_solar_gain_cover_enabled"
DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED: Final = True

# Solar-gain temperature thresholds (was hardcoded as
# COVER_CLOSE_TEMP / COVER_OPEN_TEMP module constants).
CONF_HVAC_COVER_CLOSE_TEMP: Final = "hvac_cover_close_temp"
DEFAULT_HVAC_COVER_CLOSE_TEMP: Final = 85.0  # °F (matches v3.8.4 COVER_CLOSE_TEMP)
CONF_HVAC_COVER_OPEN_TEMP: Final = "hvac_cover_open_temp"
DEFAULT_HVAC_COVER_OPEN_TEMP: Final = 80.0  # °F (matches v3.8.4 COVER_OPEN_TEMP)

# Manual-override duration after a user touches a managed cover
# (was hardcoded as COVER_MANUAL_OVERRIDE_HOURS = 2).
CONF_HVAC_COVER_OVERRIDE_HOURS: Final = "hvac_cover_override_hours"
DEFAULT_HVAC_COVER_OVERRIDE_HOURS: Final = 2.0  # hours

# Solar banking floor: the coolest setpoint solar banking will drive
# zones to (was hardcoded as SOLAR_BANK_FLOOR = 72.0).
CONF_HVAC_SOLAR_BANK_FLOOR: Final = "hvac_solar_bank_floor"
DEFAULT_HVAC_SOLAR_BANK_FLOOR: Final = 72.0  # °F (matches v3.8.4 SOLAR_BANK_FLOOR)

# Solar window hours — when HVAC watches for solar-gain conditions
# (was hardcoded as COVER_SOLAR_HOUR_START / END = 13 / 18).
CONF_HVAC_COVER_SOLAR_START_HOUR: Final = "hvac_cover_solar_start_hour"
DEFAULT_HVAC_COVER_SOLAR_START_HOUR: Final = 13
CONF_HVAC_COVER_SOLAR_END_HOUR: Final = "hvac_cover_solar_end_hour"
DEFAULT_HVAC_COVER_SOLAR_END_HOUR: Final = 18

# Solar banking battery threshold — minimum SOC for banking to fire
# (was hardcoded as SOLAR_BANK_SOC_MIN = 95).
CONF_HVAC_SOLAR_BANK_SOC_MIN: Final = "hvac_solar_bank_soc_min"
DEFAULT_HVAC_SOLAR_BANK_SOC_MIN: Final = 95  # %

# Solar HVAC Banking master enable — operator-facing master switch (EC device).
# When OFF, the solar-banking branch in HVACPredictor._check_pre_conditioning
# short-circuits. Default ON preserves status-quo banking behavior. Surfaced
# as an EC sub-switch (switch.py) so the operator can disable from the
# "URA: Energy Coordinator" device card on a good-solar-day if banking is
# over-cooling. See PLANNING_solar_banking_toggle.md.
CONF_HVAC_SOLAR_BANK_ENABLED: Final = "hvac_solar_bank_enabled"
DEFAULT_HVAC_SOLAR_BANK_ENABLED: Final = True

# HC Pre-Conditioning master enable (HVAC sub-switch on HC device).
# When OFF, ALL pre-conditioning branches in
# HVACPredictor._check_pre_conditioning (weather pre-cool, solar banking,
# pre-arrival, pre-heat) short-circuit. Default ON preserves status-quo
# behavior. Mirrors the Solar HVAC Banking sibling toggle (CONF_HVAC_SOLAR_
# BANK_ENABLED) — but lives on the HC device (HVACPreConditioningSwitch),
# not the EC device, because pre-conditioning is owned end-to-end by HC.
# See PLANNING_hc_precool_toggle_oc_observability.md (D1).
CONF_HVAC_PRE_CONDITIONING_ENABLED: Final = "hvac_pre_conditioning_enabled"
DEFAULT_HVAC_PRE_CONDITIONING_ENABLED: Final = True

# Pre-cool / pre-heat forecast triggers
# (was hardcoded in hvac_predict.py as PRECOOL_FORECAST_HIGH = 90.0,
#  PREHEAT_FORECAST_LOW = 35.0).
CONF_HVAC_PRECOOL_FORECAST_HIGH: Final = "hvac_precool_forecast_high"
DEFAULT_HVAC_PRECOOL_FORECAST_HIGH: Final = 90.0  # °F
CONF_HVAC_PREHEAT_FORECAST_LOW: Final = "hvac_preheat_forecast_low"
DEFAULT_HVAC_PREHEAT_FORECAST_LOW: Final = 35.0  # °F

# v4.5.10: Hysteresis safety floor — Cover Open Temp must be at least
# this many °F below Cover Close Temp to prevent solar-gain flapping.
COVER_HYSTERESIS_MIN_GAP: Final = 3.0  # °F
CONF_HVAC_ARRESTER_ENABLED: Final = "hvac_arrester_enabled"
CONF_HVAC_AC_RESET_ENABLED: Final = "hvac_ac_reset_enabled"
# v4.7.7 A1: AC Nudge decouple — standalone soft-nudge feature toggle, paired
# with (not gated by) AC Reset. Default ON. See hvac_override.py Gate 0a/0b.
CONF_HVAC_AC_NUDGE_ENABLED: Final = "hvac_ac_nudge_enabled"
CONF_HVAC_FAN_CONTROL_ENABLED: Final = "hvac_fan_control_enabled"

# v3.17.0: Zone Intelligence config keys
CONF_HVAC_VACANCY_GRACE_MINUTES: Final = "hvac_vacancy_grace_minutes"
CONF_HVAC_VACANCY_GRACE_CONSTRAINED: Final = "hvac_vacancy_grace_constrained"
CONF_HVAC_MAX_OCCUPANCY_HOURS: Final = "hvac_max_occupancy_hours"
CONF_ZONE_VACANCY_SWEEP_ENABLED: Final = "zone_vacancy_sweep_enabled"
CONF_PERSON_PREFERRED_ZONES: Final = "person_preferred_zones"
CONF_ZONE_PERSONS: Final = "zone_persons"
CONF_ZONE_CAMERAS: Final = "zone_cameras"
CONF_PRE_ARRIVAL_SOURCES: Final = "pre_arrival_sources"
DEFAULT_PRE_ARRIVAL_SOURCES: Final = ["geofence", "ble"]

# v3.19.0: Face-confirmed arrivals
FACE_FRESHNESS_SECONDS: Final = 30
FACE_ARRIVAL_COOLDOWN_SECONDS: Final = 60

# ============================================================================
# Defaults
# ============================================================================

DEFAULT_MAX_SLEEP_OFFSET: Final = 1.5  # F
DEFAULT_COMPROMISE_MINUTES: Final = 30
DEFAULT_AC_RESET_TIMEOUT: Final = 10  # minutes
DEFAULT_FAN_ACTIVATION_DELTA: Final = 2.0  # F
DEFAULT_FAN_HYSTERESIS: Final = 1.5  # F
DEFAULT_FAN_MIN_RUNTIME: Final = 10  # minutes
DEFAULT_ARRESTER_ENABLED: Final = True
DEFAULT_AC_RESET_ENABLED: Final = True
# v4.7.7 A1: AC Nudge default — ON. Mirror DEFAULT_AC_RESET_ENABLED so a fresh
# install gets soft-nudge detection out of the box.
DEFAULT_HVAC_AC_NUDGE_ENABLED: Final = True
DEFAULT_FAN_CONTROL_ENABLED: Final = True

# v3.17.0: Zone Intelligence defaults
DEFAULT_VACANCY_GRACE_MINUTES: Final = 15  # Normal grace period
DEFAULT_VACANCY_GRACE_CONSTRAINED: Final = 5  # Grace during energy coast/shed
DEFAULT_MAX_OCCUPANCY_HOURS: Final = 8  # Stale sensor failsafe threshold
DEFAULT_ZONE_ENTRY_DWELL_MINUTES: Final = 3  # v4.2.2: Min occupancy before preset change
CONF_HVAC_ZONE_ENTRY_DWELL: Final = "hvac_zone_entry_dwell"  # Config key

# v3.17.0: Solar banking
SOLAR_BANK_SOC_MIN: Final = 95  # % — battery must be effectively full
SOLAR_BANK_TEMP_MIN: Final = 85.0  # °F — forecast must be hot
SOLAR_BANK_OFFSET: Final = -3.0  # °F from target_temp_high
SOLAR_BANK_FLOOR: Final = 72.0  # °F — absolute minimum cooling setpoint
MIN_DEADBAND: Final = 2.0  # °F — Ecobee auto mode minimum

# v3.17.0: Pre-arrival
PRE_ARRIVAL_FAN_TIMEOUT: Final = 15  # Minutes before auto-off
PRE_ARRIVAL_TIMEOUT_MINUTES: Final = 30  # Minutes before stale pre-arrival cleared

# v3.17.0: Duty cycle
DUTY_CYCLE_WINDOW_SECONDS: Final = 20 * 60  # 20-minute rolling window
DUTY_CYCLE_SHED: Final = 0.50  # 50% max runtime during shed
DUTY_CYCLE_COAST: Final = 0.75  # 75% max runtime during coast

# Override Arrester thresholds
OVERRIDE_SEVERE_DELTA: Final = 3.0  # F — severe override threshold
OVERRIDE_NORMAL_DELTA: Final = 1.0  # F — normal override threshold
OVERRIDE_SEVERE_GRACE_MINUTES: Final = 2  # grace before reverting severe
OVERRIDE_NORMAL_GRACE_MINUTES: Final = 5  # grace before compromise on normal
OVERRIDE_COAST_TOLERANCE_BONUS: Final = 1.0  # F — widen tolerance during energy coast

# AC Reset (legacy v3.8.3 — preserved for hard-reset escalation path)
AC_RESET_MAX_PER_DAY: Final = 2  # max resets per zone per day
AC_RESET_STUCK_MINUTES: Final = 10  # minutes past setpoint before reset
AC_RESET_OFF_DURATION_SECONDS: Final = 60  # seconds to hold off during reset

# ============================================================================
# v4.5.11 — AC Energy-Aware Ramp-Down
# ----------------------------------------------------------------------------
# Detects "AC reached setpoint, kept cooling, kept burning kWh" — the dominant
# Texas-summer waste pattern that v3.8.3 AC Reset doesn't catch (it only fires
# when current > target). Soft nudge (target + Δ°F for N min) tries to coax a
# variable-speed compressor to ramp down before falling back to the existing
# hard reset. kWh-rate is the primary gate; sustained-time is secondary
# debounce. Master switch defaults OFF (opt-in).
# ============================================================================

# Master toggle for the entire AC ramp-down feature. House-wide kill-switch.
# Default OFF on first install (feature is invasive — user opts in after
# they've seen the controls and configured per-zone ac_load_sensor).
CONF_HVAC_AC_RAMP_MASTER_ENABLED: Final = "hvac_ac_ramp_master_enabled"
DEFAULT_HVAC_AC_RAMP_MASTER_ENABLED: Final = False

# House-wide tunables (Number sliders on URA: HVAC Coordinator device)
CONF_HVAC_AC_NUDGE_SIZE: Final = "hvac_ac_nudge_size"
DEFAULT_HVAC_AC_NUDGE_SIZE: Final = 1.5  # °F — added to target_temp_high

CONF_HVAC_AC_NUDGE_DURATION: Final = "hvac_ac_nudge_duration"
DEFAULT_HVAC_AC_NUDGE_DURATION: Final = 5  # minutes nudge held before restore

# v4.7.17.1: Runtime-tunable post-restore evaluation window. Was the const
# AC_NUDGE_EVALUATION_DELAY_S below (still kept as a fallback default + as
# a backward-compatible import target). Range 60-1200s lets the operator
# tune empirically without re-deploying. Mid-flight change of this value
# does NOT reschedule the currently-active eval timer (one-shot
# async_call_later); the next nudge picks up the new value.
CONF_HVAC_AC_NUDGE_EVAL_DELAY: Final = "hvac_ac_nudge_eval_delay"
DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY: Final = 600  # seconds — preserves legacy default

CONF_HVAC_AC_SUSTAINED_SAMPLES: Final = "hvac_ac_sustained_samples"
DEFAULT_HVAC_AC_SUSTAINED_SAMPLES: Final = 3  # consecutive samples > threshold

CONF_HVAC_AC_DETECTION_TIME_GATE: Final = "hvac_ac_detection_time_gate"
DEFAULT_HVAC_AC_DETECTION_TIME_GATE: Final = 10  # minutes overshoot before action

CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT: Final = "hvac_ac_hard_reset_daily_limit"
DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT: Final = 2  # compressor protection cap

CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL: Final = "hvac_ac_hard_reset_min_interval"
DEFAULT_HVAC_AC_HARD_RESET_MIN_INTERVAL: Final = 120  # minutes between hard resets

# Per-zone tunable (one Number slider per AC zone — kwh threshold scales
# with AC tonnage, the only variable that does, so house-wide would force
# a 4-ton unit to use the 3-ton threshold or vice versa). Stored on
# ZoneState.kwh_rate_threshold.
CONF_HVAC_AC_KWH_RATE_THRESHOLD: Final = "hvac_ac_kwh_rate_threshold"
DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD: Final = 0.8  # kW (3-ton heuristic; 4-ton ≈ 1.0)

# Per-zone form field — entity_id of the kW/kWh sensor for this zone's AC
# (Span panel circuit, Emporia Vue, etc.). Optional. When unset, the ramp-
# down feature is OFF for that zone (graceful degrade — no false triggers).
CONF_HVAC_AC_LOAD_SENSOR: Final = "hvac_ac_load_sensor"

# Per-zone form field — opt-out at zone level even when master is ON.
CONF_HVAC_AC_RAMP_ZONE_ENABLED: Final = "hvac_ac_ramp_zone_enabled"
DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED: Final = True

# Internal constants (not user-facing)
AC_NUDGE_OVERSHOOT_GAP: Final = 0.0            # °F — current <= target - this. v4.7.16.2 hotfix: variable-speed Bryant modulates AT setpoint and rarely undershoots 0.5°F; previous 0.5°F gap suppressed auto-nudge for the exact waste pattern it was designed to catch. Downstream gates 7 (kwh_rate > threshold), 7b (sustained samples), and 8 (time-sustained) already provide three independent false-positive guards.
AC_NUDGE_EVALUATION_DELAY_S: Final = 600       # seconds after restore = evaluate (LEGACY — runtime value lives on OverrideArrester._nudge_eval_delay_s, seeded from CONF_HVAC_AC_NUDGE_EVAL_DELAY. This const remains as the runtime-default + back-compat import target.)

# v4.7.17.1: Post-restore minimum drop fraction for the new eval rule.
# If trailing-window min kW during [restore, restore + eval_delay] is
# >= this fraction of kwh_rate_before, classify as ineffective and
# escalate to hard reset.
#
# Calibrated against the v4.7.17.x dataset (6 attributable nudges
# 2026-06-01 — 15:56/16:01/16:36/16:41/16:51/17:36 UTC):
#  - 5 effective in-hold compressor releases at 71-89% kW reduction
#    during the 5-min hold. All 5 had post_min <= 0.05 of before
#    (compressor fully released during the post-restore window before
#    rebounding).
#  - 1 true ineffective (17:36) with 5% in-hold reduction and
#    post_min/before = 0.92 (compressor never released).
# Threshold 0.50 sits safely in the gap between 0.05 and 0.92 and
# tolerates broader future cases. Promote to a runtime Number entity
# if a second install or future evidence demands.
AC_NUDGE_EVAL_MIN_DROP_FRAC: Final = 0.50

# v4.7.17.1: Below this kwh_rate_before floor (kW), the eval rule's
# signal-to-noise is too low to trust. Classify as "inconclusive" and
# EXCLUDE from FP statistics rather than treating as ineffective.
# Mirrors Gate 7's kwh threshold semantic (DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD
# = 0.8 kW). The 0.3 kW floor is lower than the gate because there's a
# transient sampling window between Gate 7's check and the nudge-start
# kwh_rate_before capture where load can briefly dip.
AC_NUDGE_KWH_RATE_BEFORE_FLOOR: Final = 0.3
AC_KWH_SENSOR_STALENESS_S: Final = 600         # 10 min stale = treat as None
AC_KWH_STALE_WARN_INTERVAL_S: Final = 21600    # 6 hr — rate-limit stale warnings
AC_KWH_AVOIDED_PROJECTION_CAP_MIN: Final = 30  # max minutes to project savings

# Ramp state-machine state strings (D7 sensor enumeration)
AC_RAMP_STATE_IDLE: Final = "idle"
AC_RAMP_STATE_DETECTING: Final = "detecting"
AC_RAMP_STATE_NUDGING: Final = "nudging"
AC_RAMP_STATE_AWAITING_EVAL: Final = "awaiting_evaluation"
AC_RAMP_STATE_ESCALATING: Final = "escalating"
AC_RAMP_STATE_LOCKED_OUT: Final = "locked_out"
AC_RAMP_STATE_DISABLED: Final = "disabled"

AC_RAMP_STATES: Final = (
    AC_RAMP_STATE_IDLE,
    AC_RAMP_STATE_DETECTING,
    AC_RAMP_STATE_NUDGING,
    AC_RAMP_STATE_AWAITING_EVAL,
    AC_RAMP_STATE_ESCALATING,
    AC_RAMP_STATE_LOCKED_OUT,
    AC_RAMP_STATE_DISABLED,
)

# Event-log event_type strings
AC_RAMP_EVENT_DETECTION_FIRED: Final = "detection_fired"
AC_RAMP_EVENT_NUDGE_STARTED: Final = "nudge_started"
AC_RAMP_EVENT_NUDGE_RESTORED: Final = "nudge_restored"
AC_RAMP_EVENT_NUDGE_EVALUATED: Final = "nudge_evaluated"
AC_RAMP_EVENT_HARD_RESET_STARTED: Final = "hard_reset_started"
AC_RAMP_EVENT_HARD_RESET_COMPLETED: Final = "hard_reset_completed"
AC_RAMP_EVENT_LOCKOUT_ENGAGED: Final = "lockout_engaged"
AC_RAMP_EVENT_MANUAL_OVERRIDE: Final = "manual_override"
AC_RAMP_EVENT_CANCEL_INVOKED: Final = "cancel_invoked"
AC_RAMP_EVENT_STARTUP_RESTORE: Final = "startup_restore"

# Fan speed scaling (above cooling setpoint)
FAN_SPEED_LOW_PCT: Final = 33
FAN_SPEED_MED_PCT: Final = 66
FAN_SPEED_HIGH_PCT: Final = 100
FAN_SPEED_LOW_DELTA: Final = 2.0  # +2-3F -> low
FAN_SPEED_MED_DELTA: Final = 3.0  # +3-5F -> med
FAN_SPEED_HIGH_DELTA: Final = 5.0  # >+5F -> high
DEFAULT_FAN_VACANCY_HOLD: Final = 300  # 5 min hold after vacancy
# v4.6.2.1: Humidity-fan on/off thresholds moved to ..const as
# DEFAULT_HUMIDITY_THRESHOLD and DEFAULT_HUMIDITY_FAN_HYSTERESIS.

# Night-window occupant fan-trust states.
# Extends the v4.7.13 sleep-only trust to the two states that flank
# sleep — HOME_NIGHT (winding down, often in bed before official sleep)
# and WAKING (groggy, still in bed). In all three states mmWave equally
# degrades on still bodies; bedroom occupants don't want fans cycled by
# presence blips. Bare-string tuple intentional — values match the
# HouseState StrEnum tokens at house_state.py:29-31 ("home_night",
# "sleep", "waking"); using bare strings here avoids an import cycle
# (hvac_const.py is leaf-level).
# Consumed at hvac_fans.py (speed cap, sleep_occupied_hold, vacancy-hold
# person-trust) and hvac.py (zone-preset person-trust). Mode-2 BLE
# recheck (presence_fan_recheck.py) deliberately stays sleep-only.
FAN_TRUST_STATES: Final = ("home_night", "sleep", "waking")

# Cover Controller
COVER_SOLAR_MONTHS: Final = frozenset({4, 5, 6, 7, 8, 9, 10})
COVER_SOLAR_HOUR_START: Final = 13
COVER_SOLAR_HOUR_END: Final = 18
COVER_CLOSE_TEMP: Final = 85.0  # F
COVER_OPEN_TEMP: Final = 80.0  # F (5F hysteresis)
COVER_MANUAL_OVERRIDE_HOURS: Final = 2
COVER_COMMAND_WINDOW_SECONDS: Final = 120  # ignore state changes within this window (covers take 45-90s to move)

# ============================================================================
# Seasonal preset ranges (cool_setpoint, heat_setpoint)
# ============================================================================

SEASON_SUMMER: Final = "summer"
SEASON_SHOULDER: Final = "shoulder"
SEASON_WINTER: Final = "winter"

# Month ranges
SUMMER_MONTHS: Final = {6, 7, 8, 9}
WINTER_MONTHS: Final = {12, 1, 2}
# Shoulder = everything else (3, 4, 5, 10, 11)

# Default seasonal ranges: {season: {preset: (cool, heat)}}
# ============================================================================
# Freeze-protection heat_low FLOOR (feature/freeze-floor).
#
# HC-owned safety net: when the best-available outdoor temp drops to freezing,
# ensure each zone's heat_cool LOW bound (resolved.cool_low / target_temp_low)
# is at least a pipe-safe floor. Normal winter presets already hold ≥58°F, so
# this only catches a custom/edge preset set dangerously low. NOT exposed as
# config in v1 (parsimony — operator confirmed). Defaults tuned for Central TX.
# ============================================================================
FREEZE_FLOOR: Final = 50           # °F — minimum heat_low when freeze active
FREEZE_TRIGGER_TEMP: Final = 35    # °F — outdoor temp at/below which freeze arms
FREEZE_TRIGGER_HYSTERESIS: Final = 3  # °F — clears when outdoor > 35+3 = 38

SEASONAL_DEFAULTS: Final = {
    SEASON_SUMMER: {
        "home": (77, 70),
        "sleep": (76, 70),
        "away": (82, 60),
        "vacation": (85, 58),
    },
    SEASON_SHOULDER: {
        "home": (74, 70),
        "sleep": (73, 68),
        "away": (80, 62),
        "vacation": (82, 58),
    },
    SEASON_WINTER: {
        "home": (72, 70),
        "sleep": (70, 68),
        "away": (78, 60),
        "vacation": (80, 58),
    },
}

# ============================================================================
# v4.7.3 D3: Editable baseline preset CONF keys + DEFAULT integers
#
# Naming: CONF_HVAC_BASELINE_<SEASON>_<PRESET>_<DIM>
#   <SEASON>: SUMMER | SHOULDER | WINTER
#   <PRESET>: HOME | SLEEP | AWAY | VACATION
#   <DIM>:    COOL (cool_high) | HEAT (heat_low)
#
# DEFAULT_* values mirror SEASONAL_DEFAULTS above so existing users see no
# behaviour change when CONFs are absent from entry.options.
# ============================================================================

# --- Summer ---
CONF_HVAC_BASELINE_SUMMER_HOME_COOL: Final = "hvac_baseline_summer_home_cool"
CONF_HVAC_BASELINE_SUMMER_HOME_HEAT: Final = "hvac_baseline_summer_home_heat"
CONF_HVAC_BASELINE_SUMMER_SLEEP_COOL: Final = "hvac_baseline_summer_sleep_cool"
CONF_HVAC_BASELINE_SUMMER_SLEEP_HEAT: Final = "hvac_baseline_summer_sleep_heat"
CONF_HVAC_BASELINE_SUMMER_AWAY_COOL: Final = "hvac_baseline_summer_away_cool"
CONF_HVAC_BASELINE_SUMMER_AWAY_HEAT: Final = "hvac_baseline_summer_away_heat"
CONF_HVAC_BASELINE_SUMMER_VACATION_COOL: Final = "hvac_baseline_summer_vacation_cool"
CONF_HVAC_BASELINE_SUMMER_VACATION_HEAT: Final = "hvac_baseline_summer_vacation_heat"

DEFAULT_HVAC_BASELINE_SUMMER_HOME_COOL: Final = 77
DEFAULT_HVAC_BASELINE_SUMMER_HOME_HEAT: Final = 70
DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_COOL: Final = 76
DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_HEAT: Final = 70
DEFAULT_HVAC_BASELINE_SUMMER_AWAY_COOL: Final = 82
DEFAULT_HVAC_BASELINE_SUMMER_AWAY_HEAT: Final = 60
DEFAULT_HVAC_BASELINE_SUMMER_VACATION_COOL: Final = 85
DEFAULT_HVAC_BASELINE_SUMMER_VACATION_HEAT: Final = 58

# --- Shoulder ---
CONF_HVAC_BASELINE_SHOULDER_HOME_COOL: Final = "hvac_baseline_shoulder_home_cool"
CONF_HVAC_BASELINE_SHOULDER_HOME_HEAT: Final = "hvac_baseline_shoulder_home_heat"
CONF_HVAC_BASELINE_SHOULDER_SLEEP_COOL: Final = "hvac_baseline_shoulder_sleep_cool"
CONF_HVAC_BASELINE_SHOULDER_SLEEP_HEAT: Final = "hvac_baseline_shoulder_sleep_heat"
CONF_HVAC_BASELINE_SHOULDER_AWAY_COOL: Final = "hvac_baseline_shoulder_away_cool"
CONF_HVAC_BASELINE_SHOULDER_AWAY_HEAT: Final = "hvac_baseline_shoulder_away_heat"
CONF_HVAC_BASELINE_SHOULDER_VACATION_COOL: Final = "hvac_baseline_shoulder_vacation_cool"
CONF_HVAC_BASELINE_SHOULDER_VACATION_HEAT: Final = "hvac_baseline_shoulder_vacation_heat"

DEFAULT_HVAC_BASELINE_SHOULDER_HOME_COOL: Final = 74
DEFAULT_HVAC_BASELINE_SHOULDER_HOME_HEAT: Final = 70
DEFAULT_HVAC_BASELINE_SHOULDER_SLEEP_COOL: Final = 73
DEFAULT_HVAC_BASELINE_SHOULDER_SLEEP_HEAT: Final = 68
DEFAULT_HVAC_BASELINE_SHOULDER_AWAY_COOL: Final = 80
DEFAULT_HVAC_BASELINE_SHOULDER_AWAY_HEAT: Final = 62
DEFAULT_HVAC_BASELINE_SHOULDER_VACATION_COOL: Final = 82
DEFAULT_HVAC_BASELINE_SHOULDER_VACATION_HEAT: Final = 58

# --- Winter ---
CONF_HVAC_BASELINE_WINTER_HOME_COOL: Final = "hvac_baseline_winter_home_cool"
CONF_HVAC_BASELINE_WINTER_HOME_HEAT: Final = "hvac_baseline_winter_home_heat"
CONF_HVAC_BASELINE_WINTER_SLEEP_COOL: Final = "hvac_baseline_winter_sleep_cool"
CONF_HVAC_BASELINE_WINTER_SLEEP_HEAT: Final = "hvac_baseline_winter_sleep_heat"
CONF_HVAC_BASELINE_WINTER_AWAY_COOL: Final = "hvac_baseline_winter_away_cool"
CONF_HVAC_BASELINE_WINTER_AWAY_HEAT: Final = "hvac_baseline_winter_away_heat"
CONF_HVAC_BASELINE_WINTER_VACATION_COOL: Final = "hvac_baseline_winter_vacation_cool"
CONF_HVAC_BASELINE_WINTER_VACATION_HEAT: Final = "hvac_baseline_winter_vacation_heat"

DEFAULT_HVAC_BASELINE_WINTER_HOME_COOL: Final = 72
DEFAULT_HVAC_BASELINE_WINTER_HOME_HEAT: Final = 70
DEFAULT_HVAC_BASELINE_WINTER_SLEEP_COOL: Final = 70
DEFAULT_HVAC_BASELINE_WINTER_SLEEP_HEAT: Final = 68
DEFAULT_HVAC_BASELINE_WINTER_AWAY_COOL: Final = 78
DEFAULT_HVAC_BASELINE_WINTER_AWAY_HEAT: Final = 60
DEFAULT_HVAC_BASELINE_WINTER_VACATION_COOL: Final = 80
DEFAULT_HVAC_BASELINE_WINTER_VACATION_HEAT: Final = 58

# Minimum deadband between cool_high and heat_low for baseline presets
BASELINE_MIN_DEADBAND: Final = 3

# ============================================================================
# House state -> preset mapping
# ============================================================================

HOUSE_STATE_PRESET_MAP: Final = {
    "home_day": "home",
    "home_evening": "home",
    "home_night": "home",
    "sleep": "sleep",
    "waking": "home",
    "away": "away",
    "vacation": "vacation",
    "arriving": "home",
    "guest": "home",
}

# ============================================================================
# Anomaly detection metrics
# ============================================================================

HVAC_METRICS: Final = [
    "zone_call_frequency",
    "short_cycle_rate",
    "override_frequency",
    "comfort_deviation_hours",
    # v4.7.8 fix-up C-M1: defined for symmetry, not yet wired. Listed in
    # HVAC_SUPPRESSED_FROM_PERSISTENCE below per v4.6.3.1 P2 doctrine.
    "egress_pause_frequency",
]

# v4.6.5.1 P2: Module-level suppression registry — promoted from a local set
# inside _record_anomaly_observations so the parametric meta-test
# (test_v465_observability_gap.py::test_every_metric_is_wired_or_suppressed)
# can introspect it. Every metric in HVAC_METRICS must be EITHER wired (have
# a record_observation call site in hvac.py) OR listed here with a comment
# explaining why.
#
# Reasons each entry is suppressed:
# - zone_call_frequency: cardinality audit (v4.6.5 pre-deploy) showed
#   mean=0.378 std=0.678 on a 3-zone install → active_count=2 → z=2.39 →
#   ADVISORY would fire routinely. Same shape family as the suppressed
#   census_count (v4.6.3.3). record_observation is still called so the
#   per-coordinator anomaly sensor keeps counting; only persistence is gated.
# - short_cycle_rate / comfort_deviation_hours: defined in HVAC_METRICS but
#   no record_observation call site exists — they are silent slots.
#   Documented per v4.6.3.1 doctrine: silent metrics must be explicitly
#   listed rather than silently absent.
#
# v4.7.8 fix-up C-M1: egress_pause_frequency is reserved per v4.6.3.1 P2
# doctrine — silent metrics MUST be explicitly listed rather than absent.
# Not yet wired (no record_observation call site exists). Will be wired in
# a follow-up cycle once a baseline is available (≥ HVAC_ANOMALY_MIN_SAMPLES
# observations / ~14 days). Deferred per plan §13.
HVAC_SUPPRESSED_FROM_PERSISTENCE: Final = frozenset({
    "zone_call_frequency",
    "short_cycle_rate",
    "comfort_deviation_hours",
    "egress_pause_frequency",
})

# Minimum samples before anomaly detection activates (14 days * 24/day)
HVAC_ANOMALY_MIN_SAMPLES: Final = 336

# ============================================================================
# Dispatcher signal for HVAC entity updates
# ============================================================================

SIGNAL_HVAC_ENTITIES_UPDATE: Final = "ura_hvac_entities_update"


# ============================================================================
# v4.7.8 — Egress Window HVAC Pause
# ----------------------------------------------------------------------------
# When a room's window opens AND is_egress=True (per-room flag), URA pauses
# the canonical HVAC zone serving that room (climate.set_hvac_mode: off).
# Snapshot prior mode + preset and restore on resume. Master enabled here
# (one switch on URA: HVAC Coordinator) + two house-wide tunables (threshold
# minutes, resume-delay minutes). Manual user override during pause engages
# a 1-hour cooldown to avoid fighting the user.
# ============================================================================

# Master toggle (default ON — kid-forgetfulness coverage matters).
CONF_HVAC_EGRESS_PAUSE_ENABLED: Final = "hvac_egress_pause_enabled"
DEFAULT_HVAC_EGRESS_PAUSE_ENABLED: Final = True

# Minutes the egress window must be open before pause fires.
CONF_HVAC_EGRESS_THRESHOLD_MIN: Final = "hvac_egress_threshold_min"
DEFAULT_HVAC_EGRESS_THRESHOLD_MIN: Final = 3  # minutes
HVAC_EGRESS_THRESHOLD_MIN_MIN: Final = 1
HVAC_EGRESS_THRESHOLD_MIN_MAX: Final = 15

# Minutes all egress windows must be closed before resume fires.
CONF_HVAC_EGRESS_RESUME_DELAY_MIN: Final = "hvac_egress_resume_delay_min"
DEFAULT_HVAC_EGRESS_RESUME_DELAY_MIN: Final = 1  # minutes
HVAC_EGRESS_RESUME_DELAY_MIN_MIN: Final = 1
HVAC_EGRESS_RESUME_DELAY_MIN_MAX: Final = 10

# Manual-override grace + cooldown (mirror AC Nudge / Drain conventions).
HVAC_EGRESS_MANUAL_OVERRIDE_GRACE_S: Final = 30
HVAC_EGRESS_MANUAL_COOLDOWN_S: Final = 3600  # 1 hour

# State-machine labels (exposed via HVACZoneEgressStateSensor).
EGRESS_STATE_IDLE: Final = "idle"
EGRESS_STATE_COUNTING: Final = "counting"
EGRESS_STATE_PAUSED: Final = "paused"
EGRESS_STATE_RESUME_COUNTDOWN: Final = "resume_countdown"
EGRESS_STATE_COOLDOWN: Final = "cooldown"

EGRESS_STATES: Final = (
    EGRESS_STATE_IDLE,
    EGRESS_STATE_COUNTING,
    EGRESS_STATE_PAUSED,
    EGRESS_STATE_RESUME_COUNTDOWN,
    EGRESS_STATE_COOLDOWN,
)

# NM event-type strings (LOW severity; once-per-day per zone per event).
EGRESS_NM_EVENT_PAUSED: Final = "egress_paused"
EGRESS_NM_EVENT_RESUMED: Final = "egress_resumed"

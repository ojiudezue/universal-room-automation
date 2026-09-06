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

# v5.7.1 — Solar HVAC Banking master enable is RETIRED.
# Folded into the unified Energy Saver Pre-Cool feature below
# (CONF_ENERGY_PRECOOL_ENABLED). The legacy CONF key is kept as a
# back-compat string literal in __init__.async_migrate_entry so we can
# detect+migrate pre-v5.7.1 options. Do NOT re-introduce the constant.
# See PLANNING_v5.7.x_energy_pre_cool_unification.md (D3, D5).

# ---------- Energy Saver Pre-Cool (v5.7.1 unification) ----------
# Working name (user-facing). The constant NAME stays ENERGY_PRECOOL_NAME
# and is the single source for the display string used by the switch /
# Number / Select on the EC device. Rename later is a one-line value swap
# + a strings.json / translations/en.json edit.
ENERGY_PRECOOL_NAME: Final = "Energy Saver Pre-Cool"

# Operator master gate (EC device sub-switch). Replaces
# CONF_HVAC_SOLAR_BANK_ENABLED. Default ON so the new install gets the
# unified PV-aware pre-cool out of the box (matches the prior banking
# default). Migration of the old key's value lives in
# __init__.async_migrate_entry.
CONF_ENERGY_PRECOOL_ENABLED: Final = "energy_precool_enabled"
DEFAULT_ENERGY_PRECOOL_ENABLED: Final = True

# Operator-configurable pre-cool offset (°F from target_temp_high).
# Default -2.0 (per operator 2026-06-28: "make the space not too cold
# suddenly"). Sign convention: negative = cooler. The 72°F floor
# (SOLAR_BANK_FLOOR) still clamps the resulting setpoint (I3) — an
# absurd configured value cannot breach the floor.
CONF_ENERGY_PRECOOL_OFFSET: Final = "energy_precool_offset"
DEFAULT_ENERGY_PRECOOL_OFFSET: Final = -2.0
ENERGY_PRECOOL_OFFSET_MIN: Final = -5.0
ENERGY_PRECOOL_OFFSET_MAX: Final = 0.0
ENERGY_PRECOOL_OFFSET_STEP: Final = 0.5

# Operator-configurable pre-cool scope. Three values:
#   occupied_only — comfort-first; never bank empty zones.
#   whole_house   — operator explicitly opts in to unconditional whole-house
#                   banking when the trigger fires (still respects floor + PV).
#   auto_pv_tiered — default. Occupied-zones-only normally; expand to
#                    unoccupied zones ONLY when there is real export surplus
#                    at per-zone dispatch time (re-check, not cached).
CONF_ENERGY_PRECOOL_SCOPE: Final = "energy_precool_scope"
ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY: Final = "occupied_only"
ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE: Final = "whole_house"
ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED: Final = "auto_pv_tiered"
ENERGY_PRECOOL_SCOPE_VALUES: Final = (
    ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY,
    ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE,
    ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED,
)
DEFAULT_ENERGY_PRECOOL_SCOPE: Final = ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED

# Net-power threshold: must be exporting more than this (W) to qualify
# as "real solar surplus". Sign convention: negative = exporting.
# Inherited from the deleted hardcoded SOLAR_BANK threshold (was `< -500`
# at hvac_predict.py:707). Also used by the auto_pv_tiered scope's
# per-zone dispatch-time re-check (I6).
ENERGY_PRECOOL_EXPORT_THRESHOLD_W: Final = 500.0

# Hour window. Union of the two deleted windows:
#   banking: [10, 14)
#   weather: [12, 14)
# Unified window: [10, 14). End is PEAK_HOUR_START (=14) — kept as a
# Python constant in hvac_predict.py for symmetry with PEAK_HOUR_END.
ENERGY_PRECOOL_HOUR_START: Final = 10

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

# =============================================================================
# Arrester Operator-Immunity Cycle (2026-08-06)
# =============================================================================
# Livability gap: the OverrideArrester (compromise/severe/revert paths in
# hvac_override.py) and the AC-ramp (soft-nudge in the same file) can shave
# the operator's OWN manual quick-cool during peak. The arrester was designed
# to catch guest/child manual holds; shaving the operator is undocumented
# behavior. This cycle adds:
#   1. Person-scoped hold immunity — an operator-listed person's manual holds
#      are stamped immune=True and every shave path SKIPS with a ledger row.
#   2. Comfort Override — a house-wide switch that suppresses ALL corrective
#      writes for the operator when they explicitly want no interference.
#   3. Sunset — immune status and Comfort Override auto-expire on the first
#      of: durable-state transition / next_activity boundary / max-age
#      backstop; then governance resumes without force-clearing anything.

# Config-flow list (person entity_ids) of users whose manual holds are
# arrester-immune. Empty default = resolved at runtime to the first tracked
# person (the operator) — mirrors CONF_NM_SECURITY_ACK_PERSONS semantics.
CONF_HVAC_ARRESTER_IMMUNE_PERSONS: Final = "hvac_arrester_immune_persons"

# ARRESTER_IMMUNE_HOLD_MAX_S — RUNG 1 (module constant, review-required).
# Safety backstop capping how long an operator's manual hold can bypass
# arrester governance. Not a routinely-tuned knob: changing it changes the
# SAFETY envelope of the immunity feature (an accidentally-left manual
# would sit uncontrolled indefinitely otherwise). 4h ≈ typical peak-window
# comfort push duration; longer holds are more likely a "forgot to reset"
# than an active intent worth respecting.
ARRESTER_IMMUNE_HOLD_MAX_S: Final = 4 * 3600  # seconds; 4 hours

# COMFORT_OVERRIDE_MAX_S — RUNG 1 (module constant, review-required).
# House-wide "please leave me alone" sunset. 6h ≈ one evening / peak window.
# Same rationale as ARRESTER_IMMUNE_HOLD_MAX_S: safety envelope, not a
# live-tunable comfort dial. Kill-switch semantics: setting to 0 disables
# the max-age sunset (durable-state sunset still fires).
COMFORT_OVERRIDE_MAX_S: Final = 6 * 3600  # seconds; 6 hours

# DURABLE_HOUSE_STATES — LEGACY. No longer the arrester policy source.
# Kept ONLY so old imports don't crash. All arrester-family sunset sites
# now consult ``house_state_invalidates_arrester_hold`` (defined below),
# which uses ARRESTER_HOLD_PRESERVING_STATES as the single denylist source
# of truth (ARREST-SUNSET-1, 2026-08-07). Do NOT add new readers of this
# constant — they'll silently drift from the real policy.
DURABLE_HOUSE_STATES: Final = frozenset({"sleep", "away", "vacation"})

# ARRESTER_HOLD_PRESERVING_STATES — the DENYLIST source of truth for
# whether a house-state transition sunsets an arrester-family hold (Temp
# Arrester Override + operator immune-holds). Operator-directed rule
# 2026-08-07: only ``arriving`` and ``guest`` preserve the hold; every
# other transition invalidates it.
#
# Chosen as a denylist (not an allowlist) so that an UNCLASSIFIED future
# house state defaults to INVALIDATING — the fail-safe direction: the
# arrester regains governance rather than a stale suppression persisting
# forever. Full house-state vocabulary lives in
# const.py:HOUSE_STATE_TRIGGER_VALUES (imported by the tests to keep the
# denylist honest — adding a 10th state breaks the parametrized coverage
# test until it is classified).
ARRESTER_HOLD_PRESERVING_STATES: Final = frozenset(
    {"arriving", "guest", "waking"}
)
# ``waking`` is the morning-twin of ``arriving`` (see house_state.py): a
# transient shim reachable ONLY from SLEEP (SLEEP: {WAKING, AWAY}) that
# exits to HOME_DAY/AWAY within ~60s of hysteresis. Same non-durable
# tier as ARRIVING (60s) — contrast with HOME_* (120s) / GUEST (300s) /
# SLEEP (600s) / VACATION (7200s). The state machine itself classifies
# it as transient, so it belongs in the preserve set.

# ARRESTER_OVERRIDE_MIN_LIFE_S — RUNG 1 (module constant, review-required).
# Minimum life grace for arrester-family holds: a state-transition sunset
# cannot fire while (now - started_ts) < ARRESTER_OVERRIDE_MIN_LIFE_S.
# Rationale: without this grace, preserving the transient states
# (arriving/waking/guest) is decorative — an override engaged during
# ``waking`` is nullified ~60s later when the house settles into
# HOME_DAY, which invalidates. The grace makes the contract predictable
# in one sentence: "flipping it on always buys at least 15 minutes;
# after that, any real context change ends it."
#
# INVARIANT: min-life MUST NOT outrank max-age (COMFORT_OVERRIDE_MAX_S,
# ARRESTER_IMMUNE_HOLD_MAX_S). 900 < 21600 today, but code defensively
# so a future retune of either knob cannot let a hold outlive its cap.
#
# Kill-switch semantics: set to 0 to disable the grace entirely (a
# state-transition sunset fires immediately regardless of age).
ARRESTER_OVERRIDE_MIN_LIFE_S: Final = 15 * 60  # seconds; 15 minutes

# ARRESTER_OVERRIDE_EXPIRY_WARN_S — RUNG 1 (module constant, review-required).
# OVERRIDE-NOTIFY-1 (operator-approved 2026-08-08): pre-warn lead time.
# Schedules a one-shot LOW NM note at
# (COMFORT_OVERRIDE_MAX_S - ARRESTER_OVERRIDE_EXPIRY_WARN_S) after
# engagement so the operator has time to re-engage before the auto-
# release. Operator: "the only real optimization is getting a text that
# says your override is about to expire 5 mins before a boundary."
# Kill-switch: set to 0 to disable pre-warn scheduling entirely.
ARRESTER_OVERRIDE_EXPIRY_WARN_S: Final = 5 * 60  # seconds; 5 minutes


def house_state_invalidates_arrester_hold(state: str | None) -> bool:
    """Return True iff transitioning INTO ``state`` should sunset an
    arrester-family hold. Empty / None state → False (transient, no
    decision yet). This is the SINGLE source of truth consulted by both
    ``sunset_temp_arrester_override`` and ``sunset_immune_holds``; keeping
    two independent expressions of the policy is exactly the fork that
    was the original ARREST-SUNSET-1 bug.
    """
    return bool(state) and state not in ARRESTER_HOLD_PRESERVING_STATES

# Marker option (persisted in entry.options) recording whether Temp Arrester
# Override was ACTIVE when HA shut down / reloaded. Read at setup:
# * If True → Temp Arrester Override was ON pre-restart. Because the switch
#   is deliberately NOT a RestoreEntity (default-OFF is the safe state), the
#   post-restart value is OFF. Fire a one-time LOW NM note at setup so the
#   operator knows their engagement was dropped, and clear the marker.
# * If absent/False → nothing to do.
# Written by set_comfort_override() (via the switch) on every toggle.
CONF_HVAC_TEMP_ARRESTER_OVERRIDE_MARKER: Final = (
    "hvac_temp_arrester_override_was_active"
)

# ARRESTER_IMMUNITY_VOICE_CONTEXTS — RUNG 1 (module constant, review-required).
# Operator-ruled 2026-08-06 (default False): voice/Assist-originated calls
# that happen to carry an immune user's user_id MUST NOT inherit immunity.
# The arrester's manual-hold detection SHOULD only respect immunity for
# direct operator actions (frontend touch of the thermostat card, physical
# thermostat dial that the operator's account authored — the "I meant it"
# moment). Voice pipelines running under the operator's HA user are NOT
# a reliable expression of the operator's intent to override arrester
# governance for hours.
#
# ==== HONEST DISCRIMINATOR INVESTIGATION (2026-08-06) ====
# HA's ``homeassistant.core.Context`` exposes: ``id``, ``user_id``,
# ``parent_id`` (+ deprecated ``origin_event``). There is NO explicit
# "originated from voice pipeline" flag. The only usable signals are:
#   1. ``user_id``: identifies the HA user; useless for voice-vs-app
#      when both share the operator account.
#   2. ``parent_id``: the id of the context that STARTED this chain
#      (e.g. an automation trigger event, or the conversation intent
#      event from the assist pipeline).
#
# Direct frontend UI calls (Lovelace card tap, thermostat entity card,
# Developer Tools -> Services) generally arrive via the WebSocket API
# with ``parent_id == None`` — they are USER-initiated with no chained
# origin. Voice/Assist calls, automation-triggered calls, script calls,
# scene activations, and any recovered-from-event chain generally have
# a non-None ``parent_id`` (the pipeline / automation / script id).
#
# LANDING TIER: **Tier 3 — documented best-effort.** With False, we
# additionally require ``context.parent_id is None`` before stamping
# immunity. This EXCLUDES voice pipelines (parent_id references the
# conversation intent context), automation-driven writes, and any
# chained call. It DOES NOT exclude a voice agent that happens to
# issue a direct service call with no parent — no such pattern is
# known in current HA, but it is not architecturally forbidden. The
# strict guarantee therefore requires an operational discipline: keep
# voice/Assist authenticated as a DEDICATED HA user (not the operator).
# See ``hvac_override._is_immunity_context_eligible`` and the setup
# WARNING emitted from ``__init__.async_setup_entry`` when this
# constant is False.
#
# True = permissive — any context whose user resolves to an immune
#        person stamps immunity (voice pipelines included). The
#        documented escape hatch, retained for the operator's option.
# False = restrictive (SHIPPED DEFAULT) — additionally require
#        ``context.parent_id is None`` as described above.
ARRESTER_IMMUNITY_VOICE_CONTEXTS: Final = False

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
DEFAULT_PRE_ARRIVAL_SOURCES: Final = ["geofence", "ble", "camera_face"]

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

# v3.17.0 → v5.7.1: Solar banking constants.
# SOLAR_BANK_SOC_MIN + SOLAR_BANK_FLOOR retained — both still referenced
# by the unified Energy Saver Pre-Cool path (the SOC floor for cool-day
# banking; the absolute 72°F floor clamp invariant I3).
# SOLAR_BANK_TEMP_MIN + SOLAR_BANK_OFFSET deleted in v5.7.1 — the offset
# is now operator-configurable (CONF_ENERGY_PRECOOL_OFFSET) and the
# forecast-hot threshold is unified with the weather-pre-cool threshold
# self._precool_forecast_high.
SOLAR_BANK_SOC_MIN: Final = 95  # % — battery must be effectively full
SOLAR_BANK_FLOOR: Final = 72.0  # °F — absolute minimum cooling setpoint
MIN_DEADBAND: Final = 2.0  # °F — Ecobee auto mode minimum

# v3.17.0: Pre-arrival
PRE_ARRIVAL_FAN_TIMEOUT: Final = 15  # Minutes before auto-off
PRE_ARRIVAL_TIMEOUT_MINUTES: Final = 30  # Minutes before stale pre-arrival cleared

# v3.17.0: Duty cycle
DUTY_CYCLE_WINDOW_SECONDS: Final = 20 * 60  # 20-minute rolling window
DUTY_CYCLE_SHED: Final = 0.50  # 50% max runtime during shed
DUTY_CYCLE_COAST: Final = 0.75  # 75% max runtime during coast

# ============================================================================
# ARREST-COMFORT-1 Cycle A — Comfort-Delay grace (2026-08-10)
# ----------------------------------------------------------------------------
# When an occupant makes a "toward-comfort" manual thermostat change in an
# occupied zone with SOC ≥ floor and no active shed, the arrester DELAYS its
# corrective write for COMFORT_GRACE_MIN. See docs/planning/PLANNING_arrester
# _comfort_delay.md rev-2. Grants are keyed by zone_id alone (probe measured
# zero multi-thermostat zones — AUDIT §metric 4 simplification). All knobs
# kill-switched per §4.6.
# ============================================================================

# COMFORT_GRACE_MIN — RUNG 3 default (entity-knob, persisted Number).
# Length of the delay in minutes. `0` = feature disabled: every request falls
# through to standard arrest (verified by unit test). Fix-up A-HIGH-1: this
# module constant is now the DEFAULT seeded into the ComfortGraceMinutesNumber
# entity; the LIVE value is read via HVACCoordinator.comfort_grace_min.
COMFORT_GRACE_MIN: Final = 30  # minutes
CONF_COMFORT_GRACE_MIN: Final = "hvac_comfort_grace_min"
DEFAULT_COMFORT_GRACE_MIN: Final = COMFORT_GRACE_MIN
MIN_COMFORT_GRACE_MIN: Final = 0
MAX_COMFORT_GRACE_MIN: Final = 240

# COMFORT_SOC_FLOOR_PCT — RUNG 3 default (entity-knob, persisted Number).
# Battery SOC (percent) at grant instant, at or above which the delay is
# granted. `0` = SOC gate disabled — grants regardless of battery
# (deliberate blackout-risk acceptance). Boot WARN when 0 < v < 20.
# Fix-up A-HIGH-1: LIVE value read via HVACCoordinator.comfort_soc_floor_pct.
COMFORT_SOC_FLOOR_PCT: Final = 80  # percent
CONF_COMFORT_SOC_FLOOR_PCT: Final = "hvac_comfort_soc_floor_pct"
DEFAULT_COMFORT_SOC_FLOOR_PCT: Final = COMFORT_SOC_FLOOR_PCT
MIN_COMFORT_SOC_FLOOR_PCT: Final = 0
MAX_COMFORT_SOC_FLOOR_PCT: Final = 100

# COMFORT_DELTA_MIN_F — RUNG 1 (module constant, review-required).
# Minimum |setpoint delta| on the comfort-relevant leg for the predicate to
# fire. Guards against phantom-taps and drive-by nudges being latched as
# comfort requests. Effectively-∞ (large number) = predicate never fires.
COMFORT_DELTA_MIN_F: Final = 2.0  # °F

# ============================================================================
# HVAC-PRESET-FLAP-1: Duty off-phase honesty (2026-08-11)
# ----------------------------------------------------------------------------
# When the D5 duty limiter forces the off-phase in an OCCUPIED zone, route
# the write through emit_set_temperature at (home_target_high + OFFSET)
# instead of `set_preset_mode("away")`. Attribute + distinct ledger reason
# expose the mechanism honestly. See docs/planning/PLANNING_preset_flap_
# offphase_honesty.md. Kill-switch: hvac_offphase_honesty_enabled.
# ============================================================================

# COMFORT_OFFPHASE_OFFSET_F — RUNG 3 default (entity-knob, persisted Number).
# Degrees F above the home cool baseline to hold during the duty off-phase.
# `0` = admitted DIAGNOSTIC config: the off-phase ceiling collapses to the
# raw home cool baseline, which may still permit compressor demand. INV #1
# is documented INERT at 0 (§1 inertness clause (f)); boot INFO log emitted.
COMFORT_OFFPHASE_OFFSET_F: Final = 2.0  # °F
CONF_COMFORT_OFFPHASE_OFFSET_F: Final = "hvac_comfort_offphase_offset_f"
DEFAULT_COMFORT_OFFPHASE_OFFSET_F: Final = COMFORT_OFFPHASE_OFFSET_F
MIN_COMFORT_OFFPHASE_OFFSET_F: Final = 0.0
MAX_COMFORT_OFFPHASE_OFFSET_F: Final = 6.0

# HVAC_OFFPHASE_HONESTY_ENABLED — RUNG 3 kill-switch (persisted Switch).
# False = pre-cycle behavior: D5 else-limb falls through to
# `effective_preset = "away"` (S1 forced-away preset write). Boot WARN when
# False so a persisted kill-switch state is visible in logs.
CONF_HVAC_OFFPHASE_HONESTY_ENABLED: Final = "hvac_offphase_honesty_enabled"
DEFAULT_HVAC_OFFPHASE_HONESTY_ENABLED: Final = True

# HVAC-GOVERNED-EXCURSION-1 D2 §4.7 — Excursion Primitive kill switch.
# Default ON. OFF => `begin_excursion` returns None (no state row, no
# lease, no suppress, no wire write). Already-persisted rows continue to
# fire `return_excursion` at their timer callback and at the boot audit
# regardless of the switch — the switch is BEGIN-ONLY.
CONF_EXCURSION_PRIMITIVE_ENABLED: Final = "excursion_primitive_enabled"
DEFAULT_EXCURSION_PRIMITIVE_ENABLED: Final = True

# COMFORT_TEMP_MAX_AGE_S — RUNG 1 (module constant).
# Maximum age (seconds) of the `current_temperature` attribute for the
# predicate to trust the direction check. Stale reads fail closed.
# `0` = every read treated as stale → predicate always fails closed.
COMFORT_TEMP_MAX_AGE_S: Final = 900  # seconds; 15 minutes

# COMFORT_TOTAL_MAX_MIN — RUNG 1 (module constant).
# Absolute backstop for concession-ladder duration (Cycle B; inert in
# Cycle A). Present now so both cycles reference one source of truth.
# `0` = no concession possible in Cycle B.
COMFORT_TOTAL_MAX_MIN: Final = 60  # minutes

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

# HVAC-GOVERNED-EXCURSION-1 D1: delay after the restore sequence completes
# before re-reading thermostat state to record the SETTLED restore verdict
# into `ac_ramp_events.restore_ok`. The IMMEDIATE verdict
# (`restore_ok_immediate`) is written synchronously with the log row; the
# SETTLED verdict is written by a scheduled callback this many seconds
# later. The pair `(immediate=1, settled=0)` is the load-bearing signature
# for the late-cloud-poll clobber this cycle exists to measure — reading
# only at t=0 would systematically record success in the failure case.
#
# 12s is chosen because:
#   - Observed clobber latency was ~509 ms; 12s is >20x margin.
#   - Bryant/Carrier + Ecobee cloud-polled climate integrations settle
#     attribute updates within a few seconds of a write; 12s comfortably
#     exceeds that envelope.
#   - Well below the nudge evaluation delay (600s default) so the settled
#     write always lands before evaluation reads the row.
# Rung: module constant (numbers-get-knobs ladder rung 1). This is a
# measurement window, not an operator-tunable policy — changing it should
# require code review.
# AC_NUDGE_RESTORE_SETTLE_DELAY_S — settled preset-restore verdict delay.
#
# 2026-08-23 fix-up (F8 REVERSED after operator measurement):
# The 2026-08-22 option-(c) ruling that disabled this sample was built
# on an unmeasured number. I took `DEFAULT_UPDATE_INTERVAL_MINUTES = 30`
# from ha_carrier/const.py:46 and treated it as the real refresh
# cadence. The recorder shows the climate entities actually update
# every 42-79 s median (p90 167-323 s) — not every 30 min. There is
# no unsatisfiable window; option (c) was wrong.
#
# Worse, disabling the verdict would have blinded us to a REAL,
# PRE-EXISTING defect. Measured cross-tab of 47 paired nudges
# (2026-08-22, T+1/2/5/10/20/30 min after restore):
#   intent == "manual" (restore is a no-op):
#     97% match at T+1m — trivially true.
#   intent is a REAL preset (away / home / sleep):
#     0/10 at T+1m and T+2m; 1/10 (10%) from T+5m onward.
# When there is a real preset to restore, the restore does NOT take,
# at any delay out to 30 min. More time does not help — time was
# never the variable. This is a genuine defect the sample must
# measure, not an instrument artifact, and it likely explains the
# per-zone dwell in `manual` (62/46/26%). Owned by card
# HVAC-MANUAL-PRESET-CONTRACT-1.
#
# Chosen delay: **180 s (3 min)** — comfortably past the 42-79 s
# entity-refresh envelope, far inside the 25-min inter-nudge cadence,
# and orders of magnitude below the actuation-lag risk that would
# have justified anything longer.
#
# **VERDICTS RECORDED BEFORE THIS RELEASE ARE INADMISSIBLE** — they
# were taken at 12 s under the pre-fix-up delay. That statement is
# still true; only the reasoning behind it has changed.
AC_NUDGE_RESTORE_SETTLE_DELAY_S: Final = 180
# Structured reason strings written into `settled_reason` when the
# settled verdict is deliberately NOT a True/False. Genuinely
# unreadable-at-settle cases only — the pre-fix
# "poll_interval_30min_exceeds_nudge_cadence_25min" claim was based
# on the unmeasured 30-min figure and is retired.
AC_NUDGE_SETTLED_REASON_ENTITY_MISSING: Final = "entity_missing_at_settle"
AC_NUDGE_SETTLED_REASON_CANCELLED_BY_RENUDGE: Final = "cancelled_by_renudge"

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

# AC-RAMP-PIPELINE-HARDENING-1 (this cycle)
# Additional ac_ramp_events event_type strings for the observability
# ledger. All are edge-triggered (see D8) — never per-tick.
AC_RAMP_EVENT_GATE4_DIVERGENCE_SHADOW: Final = "gate4_divergence_shadow"
AC_RAMP_EVENT_HARD_RESET_DECLINED: Final = "hard_reset_declined"

# D-GATE4 — draw-based Gate 4 predicate primitives (module const rung 1).
# Changing either should require code review; both are safety-adjacent
# (a wrong low value permits spurious cooling nudges during heating
# cycles; a wrong high value silently disables the predicate).
AC_ACTIVELY_COOLING_KW_MIN: Final = 0.5
AC_ACTIVELY_COOLING_BLOWER_RPM_MIN: Final = 100
# Invariant P bound (display-only fraction, 0.0-1.0).
GATE4_MAX_BLIND_FRACTION: Final = 0.01

# D-GATE4 predicate mode Select values + default.
HVAC_AC_GATE4_MODE_LEGACY: Final = "legacy"
HVAC_AC_GATE4_MODE_SHADOW: Final = "shadow"
HVAC_AC_GATE4_MODE_LIVE: Final = "live"
HVAC_AC_GATE4_MODES: Final = (
    HVAC_AC_GATE4_MODE_LEGACY,
    HVAC_AC_GATE4_MODE_SHADOW,
    HVAC_AC_GATE4_MODE_LIVE,
)
CONF_HVAC_AC_GATE4_PREDICATE_MODE: Final = "hvac_ac_gate4_predicate_mode"
# 2026-08-23 fix-up: default flipped SHADOW -> LIVE. Operator: "I don't
# have time for shadows. It works or not and we can fix or rip."
# Rollback path is flipping the Select to `legacy` — which restores
# the pre-cycle cloud-reported hvac_action predicate verbatim; that
# path is tested to work on a cold boot with no persisted state.
DEFAULT_HVAC_AC_GATE4_PREDICATE_MODE: Final = HVAC_AC_GATE4_MODE_LIVE

# D-SCORE — durability window (options rung 2). The delayed classifier
# passively re-reads kW at nudge-eval-time + this window and writes
# durable/durable_minutes onto the nudge_evaluated row.
CONF_HVAC_AC_DURABILITY_WINDOW: Final = "hvac_ac_durability_window"
DEFAULT_HVAC_AC_DURABILITY_WINDOW: Final = 30  # minutes

# D3 — soft-nudge daily runaway BACKSTOP (Number rung 3). Manual
# force_nudge bypasses this cap by design.
# 2026-08-23 fix-up: default 50 -> 40. Rationale: max daily nudges
# ever observed is 36 (zone_1). 40 sits above the observed envelope
# so it never touches a normal night, but low enough to actually
# trip a genuine runaway. At 50 it was unreachable in all recorded
# history — a guard that could never fire. This is a safety BACKSTOP
# and NOT a policy cap: each nudge is measured to buy ~19 min of
# compressor-off, so suppressing them costs savings; the value
# should stay above the operating envelope.
CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT: Final = "hvac_ac_soft_nudge_daily_limit"
DEFAULT_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT: Final = 40

# D2 — partitioned day/night reset budgets (Numbers rung 3, operator ruled
# 2/2 2026-08-22). Wall-clock window (options rung 2).
CONF_HVAC_AC_RESET_DAY_BUDGET: Final = "hvac_ac_reset_day_budget"
DEFAULT_HVAC_AC_RESET_DAY_BUDGET: Final = 2
CONF_HVAC_AC_RESET_NIGHT_BUDGET: Final = "hvac_ac_reset_night_budget"
DEFAULT_HVAC_AC_RESET_NIGHT_BUDGET: Final = 2
CONF_HVAC_AC_NIGHT_START_HHMM: Final = "hvac_ac_night_start_hhmm"
DEFAULT_HVAC_AC_NIGHT_START_HHMM: Final = "22:00"
CONF_HVAC_AC_NIGHT_END_HHMM: Final = "hvac_ac_night_end_hhmm"
DEFAULT_HVAC_AC_NIGHT_END_HHMM: Final = "06:00"

# D7 — promote AC_RESET_OFF_DURATION_SECONDS to a live Number (rung 3).
# The module const above stays as the first-boot seed value.
CONF_HVAC_AC_RESET_OFF_DURATION: Final = "hvac_ac_reset_off_duration"
DEFAULT_HVAC_AC_RESET_OFF_DURATION: Final = AC_RESET_OFF_DURATION_SECONDS

# D6 — reset-outcome settle window (module const rung 1, sibling of
# AC_NUDGE_RESTORE_SETTLE_DELAY_S). Passive re-read only.
AC_RESET_OUTCOME_SETTLE_S: Final = 60

# F6 fix-up (2026-08-22): the temp LEVEL classification is defensible at
# 60s (see AC_RESET_OUTCOME_SETTLE_S), but the measured
# command-to-physical-response lag for zone kW is p50 72-101s across the
# three zones — a 60s kW read samples INSIDE the actuation lag and
# systematically returns ~0.0, which reads as evidence the reset worked
# even when it didn't. The kW capture uses its own longer settle so the
# reading lands AFTER the compressor has had a chance to respond.
# Reserved: verdicts taken before this change may be inadmissible for
# real durability analysis — see fix-up note on
# AC_NUDGE_RESTORE_SETTLE_DELAY_S below (F8).
AC_RESET_OUTCOME_KWH_SETTLE_S: Final = 150

# D6 outcome classification strings.
AC_RESET_OUTCOME_JUSTIFIED_RAMP: Final = "justified_ramp"
AC_RESET_OUTCOME_FLOOR_SURVIVED: Final = "floor_survived"
AC_RESET_OUTCOME_INCONCLUSIVE: Final = "inconclusive"

# D8 — declined-reason codes (edge-triggered writes; see coordinator
# `_maybe_write_declined`).
AC_RESET_DECLINED_DAY_BUDGET: Final = "day_budget_exhausted"
AC_RESET_DECLINED_NIGHT_BUDGET: Final = "night_budget_exhausted"
AC_RESET_DECLINED_GLOBAL_MIN_INTERVAL: Final = "global_min_interval"
AC_RESET_DECLINED_FEATURE_DISABLED: Final = "feature_disabled"
AC_RESET_DECLINED_MASTER_OFF: Final = "master_off"
AC_RESET_DECLINED_COMFORT_DEFERRED: Final = "comfort_deferred"
# F4 fix-up: distinct reason for true total-cap exhaustion via the
# decline path (`engage_lockout_on_cap=False`). Distinct from the
# per-partition reasons so operators can tell "one bucket full" (rare,
# expected) from "both buckets full but caller chose no-lockout" (rare,
# non-auto).
AC_RESET_DECLINED_TRUE_CAP_EXHAUSTED: Final = "true_cap_exhausted"

# Edge-triggered declined-row floor (seconds; same reason cannot re-log
# within this window per zone).
AC_RESET_DECLINED_MIN_INTERVAL_S: Final = 900  # 15 min

# Fan speed scaling (above cooling setpoint)
FAN_SPEED_LOW_PCT: Final = 33
FAN_SPEED_MED_PCT: Final = 66
FAN_SPEED_HIGH_PCT: Final = 100
FAN_SPEED_LOW_DELTA: Final = 2.0  # +2-3F -> low
FAN_SPEED_MED_DELTA: Final = 3.0  # +3-5F -> med
FAN_SPEED_HIGH_DELTA: Final = 5.0  # >+5F -> high
DEFAULT_FAN_VACANCY_HOLD: Final = 300  # 5 min hold after vacancy
# hotfix/fan-sweep-trio (2026-08-03): externally-adopted fans get a longer
# vacancy hold before HVAC turns them off. Rationale: an adopted fan was
# lit by something the operator (or another automation) chose — don't yank
# it as aggressively as one URA itself put on. Multiplier applied ONLY to
# room_fan.trigger == "external". Kill-switch: set to 1.0 to disable
# (behaves identically to a URA-lit fan). Rung-1 module const per
# "Numbers Get Knobs" — changing this affects sweep timing and should
# require review.
FAN_ADOPTED_VACANCY_HOLD_MULT: Final = 2.0
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
# - comfort_deviation_hours: defined in HVAC_METRICS but no
#   record_observation call site exists — silent slot. Documented per
#   v4.6.3.1 doctrine: silent metrics must be explicitly listed rather
#   than silently absent.
# - short_cycle_rate: HVAC-ANOMALY-BLIND-1 D2 wired it as an event-driven
#   per-zone daily observation (see hvac.py `_emit_and_reset_short_cycles`)
#   and removed it from this frozenset. Kept out of this comment's silent
#   list to reflect the new reality.
#
# v4.7.8 fix-up C-M1: egress_pause_frequency is reserved per v4.6.3.1 P2
# doctrine — silent metrics MUST be explicitly listed rather than absent.
# Not yet wired (no record_observation call site exists). Will be wired in
# a follow-up cycle once a baseline is available (≥ HVAC_ANOMALY_MIN_SAMPLES
# observations / ~14 days). Deferred per plan §13.
# HVAC-ANOMALY-BLIND-1 D2: short_cycle_rate is now WIRED (per-zone daily
# count, event-driven producer) and its per-day cardinality is well-
# conditioned (measured std 0.78-1.71 across 7-8 days of live data — see
# PLANNING_hvac_short_cycle_producer.md §Design Decision). It ships
# PERSISTED — removed from the suppression frozenset — because its shape is
# nothing like the degenerate zone_call_frequency mean=0.378 that motivated
# the original v4.6.5 suppression. Worst-case anomaly_log write rate is
# 3 rows/day (one per zone); typical is zero.
HVAC_SUPPRESSED_FROM_PERSISTENCE: Final = frozenset({
    "zone_call_frequency",
    "comfort_deviation_hours",
    "egress_pause_frequency",
})

# Minimum samples before anomaly detection activates (14 days * 24/day)
HVAC_ANOMALY_MIN_SAMPLES: Final = 336

# HVAC-ANOMALY-BLIND-1 D2: per-metric override for short_cycle_rate.
# Sampling cadence is 1 observation / day / zone (fired at local-day
# rollover). With HVAC_ANOMALY_MIN_SAMPLES=336 the maturation gate would
# be 336 DAYS, so we override to 14 days — matching the probe window that
# established the fixture (per-zone std 0.78-1.71). See planning doc
# §Design Decision. Knob ladder rung: module constant (safety-adjacent
# tuning; changing the maturation window should require code review).
HVAC_SHORT_CYCLE_MIN_SAMPLES: Final = 14

# HVAC-ANOMALY-BLIND-1 D2: sub-cycle threshold — an on-cycle whose
# duration (idle→active→idle) is under this many seconds counts as a
# "short cycle". Rung: module constant (compressor-short-cycling
# protection semantics; retuning should require review). Picked at 10 min
# against measured medians ~20-22m and sub-5min share 2.7-4.8%; 10-min
# threshold captures the 5-min band a shorter knob would miss.
SHORT_CYCLE_THRESHOLD_S: Final = 600

# ============================================================================
# Dispatcher signal for HVAC entity updates
# ============================================================================

SIGNAL_HVAC_ENTITIES_UPDATE: Final = "ura_hvac_entities_update"

# Arrester Operator-Immunity (2026-08-06): dedicated dispatcher signal
# fired by every Temp Arrester Override engage/release/sunset path so the
# HVACTempArresterOverrideSwitch entity refreshes its UI state without
# relying on the coarse SIGNAL_HVAC_ENTITIES_UPDATE tick (which fires once
# per decision cycle — ~5 min lag between an operator toggle and the
# switch card visibly reflecting reality; noticeable on sunset).
SIGNAL_HVAC_TEMP_ARRESTER_OVERRIDE_UPDATE: Final = (
    "ura_hvac_temp_arrester_override_update"
)


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

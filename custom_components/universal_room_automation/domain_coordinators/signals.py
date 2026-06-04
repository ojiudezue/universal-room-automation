"""Signal constants and shared data classes for domain coordinators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

# ============================================================================
# Dispatcher signal constants
# ============================================================================

SIGNAL_HOUSE_STATE_CHANGED: Final = "ura_house_state_changed"
SIGNAL_ENERGY_CONSTRAINT: Final = "ura_energy_constraint"
SIGNAL_CENSUS_UPDATED: Final = "ura_census_updated"
SIGNAL_SAFETY_HAZARD: Final = "ura_safety_hazard"
SIGNAL_SAFETY_ENTITIES_UPDATE: Final = "ura_safety_entities_update"
SIGNAL_SECURITY_EVENT: Final = "ura_security_event"
SIGNAL_SECURITY_ENTITIES_UPDATE: Final = "ura_security_entities_update"
SIGNAL_NM_ENTITIES_UPDATE: Final = "ura_nm_entities_update"
SIGNAL_NM_ALERT_STATE_CHANGED: Final = "ura_nm_alert_state_changed"
SIGNAL_PERSON_ARRIVING: Final = "ura_person_arriving"
SIGNAL_ENERGY_ENTITIES_UPDATE: Final = "ura_energy_entities_update"
SIGNAL_ACTIVITY_LOGGED: Final = "ura_activity_logged"
# v4.6.5.3 M2: dispatched once from __init__.py when the URA database is
# first added to hass.data[DOMAIN]["database"]. Sensors that need the DB on
# startup (e.g. URARecentAnomaliesSensor) subscribe to this instead of
# polling hass.data. Replaces v4.6.5.2's 30-attempt × 1s polling helper.
SIGNAL_DATABASE_READY: Final = "ura_database_ready"
SIGNAL_BAYESIAN_UPDATED: Final = "ura_bayesian_updated"
SIGNAL_OCCUPANCY_ANOMALY: Final = "ura_occupancy_anomaly"

# v4.5.20: per-coord refresh signals for Presence + MF anomaly sensors.
# Pre-v4.5.20, PresenceAnomalySensor and MusicFollowingAnomalySensor had
# no `async_added_to_hass` subscription to any refresh signal — their
# attrs only refreshed when HA naturally re-queried. Filed at v4.5.14
# when anomaly visibility shipped; addressed here. Convention matches
# SIGNAL_SAFETY_/_SECURITY_/_NM_ENTITIES_UPDATE (centralized in this
# file, NOT in domain-specific const files — the v4.5.10.1 import-fail
# precedent argues against the HVAC-style outlier).
SIGNAL_PRESENCE_ENTITIES_UPDATE: Final = "ura_presence_entities_update"
SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE: Final = "ura_music_following_entities_update"

# v4.6.0: dispatched from TransitionDetector._score_prediction() each time a
# next-room prediction result is written to prediction_results. Accuracy sensors
# (D4/D5) subscribe here so they refresh attrs on every score event, not on a
# polling timer — mirrors the SIGNAL_PRESENCE_/_MUSIC_FOLLOWING_ pattern above.
SIGNAL_NEXT_ROOM_PREDICTION_UPDATE: Final = "ura_next_room_prediction_update"

# v4.6.2 D5/D6: routine status signals.
# SIGNAL_ROUTINE_STATUS_UPDATE — dispatched by RegimeDetector after a successful
# _emit_regime_event() AND by the acknowledge button after the recovery_at UPDATE.
# D5 sensors subscribe to refresh their state.
# SIGNAL_REGIME_EVENT_EMITTED — dispatched by RegimeDetector immediately after
# save_anomaly_event() succeeds. Payload: dict with person_id, severity, cell.
# NotificationManager subscribes to trigger event/digest dispatch.
SIGNAL_ROUTINE_STATUS_UPDATE: Final = "ura_routine_status_update"
SIGNAL_REGIME_EVENT_EMITTED: Final = "ura_regime_event_emitted"

# v4.6.9: coordinator-ready signals for CM-device buttons that need to
# re-evaluate `available` once their backing coordinator is registered.
# Dispatch sites in __init__.py immediately after hass.data[DOMAIN][key] is set.
# Mirrors the SIGNAL_DATABASE_READY pattern (v4.6.5.3).
SIGNAL_NM_READY: Final = "ura_notification_manager_ready"
SIGNAL_BAYESIAN_READY: Final = "ura_bayesian_predictor_ready"

# v4.7.x D2: dispatched from EnergyCoordinator.async_setup() after init
# completes (DB restore + first decision cycle).  EC sub-switches subscribe
# here so they can reliably restore saved values even when EC coord init is
# delayed beyond the v4.5.3 retry budget (e.g. Envoy validation race).
# Mirrors the SIGNAL_DATABASE_READY / SIGNAL_NM_READY / SIGNAL_BAYESIAN_READY
# pattern — one-shot fire-and-forget after the backing service is registered.
SIGNAL_ENERGY_COORDINATOR_READY: Final = "ura_energy_coordinator_ready"

# v4.7.3.1: dispatched from HVACCoordinator.async_setup() after init
# completes (zone discovery + first decision cycle).  Bespoke HVAC switches
# (HVACGuestModeActuationSwitch, HVACOverrideArresterSwitch,
# HVACACRampMasterSwitch) subscribe here so they can complete deferred
# restores when HVAC coord isn't registered at async_added_to_hass time.
# Parallel pattern to SIGNAL_ENERGY_COORDINATOR_READY above (Bug Class #5).
SIGNAL_HVAC_COORDINATOR_READY: Final = "ura_hvac_coordinator_ready"

# v4.7.x Cycle A: WeatherProviderManager signals
# SIGNAL_WEATHER_PROVIDER_CHANGED — dispatched when active provider changes (failover).
#   Payload: {"active": entity_id | None, "reason": str}
# SIGNAL_WEATHER_DIVERGENCE_DETECTED — dispatched when ≥2 providers diverge beyond threshold.
#   Payload: {"divergence_f": float, "provider_highs": dict}
SIGNAL_WEATHER_PROVIDER_CHANGED: Final = "ura_weather_provider_changed"
SIGNAL_WEATHER_DIVERGENCE_DETECTED: Final = "ura_weather_divergence_detected"

# v4.7.1 Cycle B: Dynamic Preset Override Source signals
# Dispatched by DynamicPresetOverrideSource when a zone transitions to a new bucket.
# Payload: dict with keys zone_id, previous_bucket, new_bucket, delta_f, now_iso
SIGNAL_DYNAMIC_PRESET_TRANSITIONED: Final = "ura_dynamic_preset_transitioned"
# Dispatched when the override list changes (bucket change OR enable/disable).
# Sensors subscribe to refresh their state.
SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED: Final = "ura_dynamic_preset_overrides_updated"

# v4.7.9 D2: dispatched from EnergyCoordinator._async_evaluate_dynamic_presets
# when the per-zone DPM skip_reasons dict changes between ticks BUT the
# overrides dict itself is unchanged. Carry-forward from v4.7.7 Reviewer B-M1:
# DynamicPresetOverridesAppliedSensor.skipped_zones_with_reason only refreshes
# when SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED fires (which gates on overrides
# changing), so reason-only deltas were stale for up to 24h on stable-empty
# days. Sensor recomputes from latest state; idempotent re-fire is safe.
# Edge-detection happens AFTER overrides edge-detection so the four combinations
# of (overrides_changed x reasons_changed) all dispatch correctly. When BOTH
# change, both signals fire; sensor's _on_signal is idempotent.
SIGNAL_DPM_SKIP_REASONS_UPDATED: Final = "ura_dpm_skip_reasons_updated"

# Fan-noise mitigation D1: dispatched once per inference tick whenever the
# Layer-1 gate applied a fresh hold (i.e. a room moved from "no hold" to
# "hold active" because it was fan-interference-suspect AND the BLE ladder
# did not corroborate). Payload: ``{"rooms": list[str], "ladder": dict[str,
# str]}`` where ladder maps room -> "L1" | "L2" | "L3" | "none" naming the
# strongest non-fired layer for the room. Observation channel for UI
# refresh + diagnostic sensors; downstream consumers MUST NOT actuate on
# this signal (D2 actuation is build-gated separately).
SIGNAL_FAN_INTERFERENCE_GATE_FIRED: Final = "ura_fan_interference_gate_fired"


# ============================================================================
# Shared data classes for inter-coordinator communication
# ============================================================================

@dataclass
class HouseStateChange:
    """Payload for SIGNAL_HOUSE_STATE_CHANGED."""

    previous_state: str
    new_state: str
    confidence: float
    trigger: str


@dataclass
class EnergyConstraint:
    """Payload for SIGNAL_ENERGY_CONSTRAINT."""

    mode: str  # normal | pre_cool | pre_heat | coast | shed
    setpoint_offset: float  # degrees F, negative = lower, positive = raise
    occupied_only: bool = True
    max_runtime_minutes: int | None = None
    fan_assist: bool = False
    reason: str = ""
    solar_class: str = ""
    forecast_high_temp: float | None = None
    soc: int | None = None
    # v4.7.x Cycle A: apparent-temperature forecast high (from WeatherProviderManager).
    # Added additively alongside forecast_high_temp to preserve back-compat (Bug #37).
    # forecast_high_temp continues to carry raw_high for existing HVAC consumers.
    apparent_forecast_high_temp: float | None = None


@dataclass
class SafetyHazard:
    """Payload for SIGNAL_SAFETY_HAZARD."""

    hazard_type: str  # smoke | co | water_leak | freeze | air_quality
    severity: str  # critical | high | medium | low
    source_entity: str = ""
    value: float | None = None
    details: str = ""


@dataclass
class SecurityEvent:
    """Payload for SIGNAL_SECURITY_EVENT."""

    event_type: str  # entry_alert | unknown_person | lock_check | armed_change
    severity: str  # critical | high | medium | low
    source_entity: str = ""
    armed_state: str = ""
    details: str = ""

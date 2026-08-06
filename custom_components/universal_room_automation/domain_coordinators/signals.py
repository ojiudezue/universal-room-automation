"""Signal constants and shared data classes for domain coordinators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

# ============================================================================
# Dispatcher signal constants
# ============================================================================

SIGNAL_HOUSE_STATE_CHANGED: Final = "ura_house_state_changed"
# House-State Rung 2a (v5.39.0): dispatched by CoordinatorManager whenever
# the house-policy diagnostic (active_policies / last_state_driven_action)
# changes. Subscribed by ``HousePolicySensor`` on the CM device (INV-1).
SIGNAL_HOUSE_POLICY_UPDATE: Final = "ura_house_policy_update"
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

# build/pc-observability: dispatched from PresenceCoordinator.async_setup()
# after init completes (_ready_event.set()). New kill-switch entities on the
# presence device (guest detection, arriving re-arm, away-veto) subscribe
# here so they can complete deferred RestoreEntity restores when the presence
# coord isn't yet registered at async_added_to_hass time.
# Mirrors the SIGNAL_HVAC_COORDINATOR_READY / SIGNAL_ENERGY_COORDINATOR_READY
# pattern (Bug Class #5).
SIGNAL_PRESENCE_COORDINATOR_READY: Final = "ura_presence_coordinator_ready"

# (module-top import used by presence.py — see B-M2 fix-up.)

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

# Inclement-weather reserve cycle: dispatched by EnergyBatteryCoordinator on a
# transition of (inclement tier, hold_depth). Future HVAC / EV / NM consumers
# subscribe here rather than coupling to battery internals.
#   Payload: {"tier": str, "hold_depth": str, "source": str,
#             "expires_at": str | None, "reserve_floor": int, "reason": str}
SIGNAL_INCLEMENT_STATE_CHANGED: Final = "ura_inclement_state_changed"

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

# mmWave fan-corroboration demotion (Tier-3 D2). Dispatched on the
# tick a room transitions INTO the demoted set. Payload:
#   {"room_name": str, "reason": "mmwave_sole_fan_on_no_corroboration",
#    "fan_on_since": iso, "last_pir_motion_time": iso_or_none}
# Observability only — downstream actuation MUST NOT depend on this
# (the demotion has already been applied at the coordinator's own
# `_async_update_data` seam).
SIGNAL_MMWAVE_FAN_DEMOTED: Final = "ura_mmwave_fan_demoted"

# Fan-noise Mode-2 mitigation (room-tier BLE-gated fan-pause + clean recheck).
# Fired when the state machine transitions idle -> armed for a room.
# Payload: ``{"room": str, "ble_ladder_layer": str}``.
SIGNAL_FAN_RECHECK_STARTED: Final = "ura_fan_recheck_started"

# Fired when the state machine transitions restoring -> cooldown for a room.
# Payload: ``{"room": str, "outcome": "vacated" | "occupied_confirmed"}``.
SIGNAL_FAN_RECHECK_FINISHED: Final = "ura_fan_recheck_finished"

# Occupancy substrate unification cycle: per-room, per-kind raw-signal edge.
# Dispatched by ``OccupancySubstrate`` on every False<->True edge in the
# per-kind raw view of a configured ROOM entry, sourced exclusively from the
# operator's curated ``CONF_MOTION_SENSORS`` / ``CONF_MMWAVE_SENSORS`` /
# ``CONF_OCCUPANCY_SENSORS`` lists (NO area-sweep, NO substring heuristic).
# Payload positional args: ``(room_name: str, kind: str, new_state: bool)``
# where ``kind`` ∈ ``TIER1_KINDS`` ("motion", "mmwave", "occupancy"). The
# substrate sits BENEATH the room + zone tiers as a unified raw-signal
# input layer — it is NOT a new tier and does NOT supersede either of the
# existing room or zone tiers; both tiers continue to apply their own
# legitimate temporal smoothing on top of this common substrate.
SIGNAL_SUBSTRATE_KIND_CHANGED: Final = "ura_substrate_kind_changed"

# Substrate re-subscribe on room add/remove/edit (post-v5.11.0 fix cycle).
# Dispatched from ROOM entry lifecycle sites in __init__.py:
#   - ROOM async_setup_entry (action="loaded")   — after coordinator stored
#   - ROOM async_unload_entry (action="unloaded") — before hass.data pop
#   - _async_update_listener  (action="options_updated") — comfort-slider
#     suppressed writes AND fall-through to reload paths (fire once at
#     the listener boundary so future _ROOM_SUPPRESS_KEYS expansion
#     cannot silently re-open the v4.7.24 blind spot).
# Payload positional args: ``(entry_id: str, room_name: str, action: str)``
# where action ∈ {"loaded", "unloaded", "options_updated"}.
# PresenceCoordinator subscribes and drives
# ``OccupancySubstrate.refresh_subscriptions()`` (diff-based atomic swap).
# Restores the pre-v4.7.24 (commit e165e1cb) per-room-onboarding guarantee:
# a room added WITHOUT an HA restart is event-driven immediately from
# ROOM setup, not gated on the ~34s poll interval (Master Bath Toilet
# live evidence 2026-07-09).
SIGNAL_ROOM_ENTRY_LIFECYCLE: Final = "ura_room_entry_lifecycle"


# Optimization Coordinator (Phase 1, v4.7.34 candidate).
# SIGNAL_OPTIMIZER_INTENT — fired by OptimizerIntentBroker BEFORE an L2+
#   actuation (and as a `shadow_dry_run` at L1). Payload: dict with keys
#   ``action_id`` (UUID str), ``target_entity``, ``service``,
#   ``service_data``, ``source_dimension``, ``proposed_at_iso``,
#   ``veto_window_s``, ``action_class`` (``reversible_device`` |
#   ``config_write``), ``effective_level``.
# SIGNAL_OPTIMIZER_INTENT_VETO — sibling coordinators dispatch this with
#   payload ``{action_id, vetoed_by, reason}`` to veto an L2/L3 intent
#   inside the veto window.
# SIGNAL_OPTIMIZER_FINDING_EMITTED — fired after every finding is written
#   to ``optimization_findings``. Optimizer sensors subscribe at
#   ``async_added_to_hass`` and store the unsub on ``self._unsub_*`` to
#   avoid Bug Class #50.
SIGNAL_OPTIMIZER_INTENT: Final = "ura_optimizer_intent"
SIGNAL_OPTIMIZER_INTENT_VETO: Final = "ura_optimizer_intent_veto"
SIGNAL_OPTIMIZER_FINDING_EMITTED: Final = "ura_optimizer_finding_emitted"


# Zone Delete Flow (v5.12+): dispatched by ``_delete_zone`` AFTER the ZM
# options mutation has removed a zone from the zones dict. Subscribers:
#   - HVAC coordinator: prune the deleted zone_id from
#     ``ZoneManager.zones`` AND rewrite the persisted zone-state snapshot
#     (hvac.py) so a restart doesn't RESURRECT the zone via
#     ``restore_state_snapshot``.
#   - Presence coordinator: prune ``_zone_trackers`` for the deleted
#     zone_name (the ``_discover_zones`` prune block is dead code on the
#     delete path because presence lives on the parent entry and never
#     reloads on a ZM options mutation).
#   - Zone-available cache in ``ZoneAvailabilityStatusSwitch`` (R9):
#     invalidate the cached zones-keyset so the next ``available()``
#     scan hits fresh state.
# Payload: ``{"deleted_zone_name": str, "deleted_zone_id": str | None}``.
SIGNAL_ZM_ZONES_UPDATED: Final = "ura_zm_zones_updated"


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
